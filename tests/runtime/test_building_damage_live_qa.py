"""Safe read-only QA-clone building-damage plugin adapter tests."""
from __future__ import annotations
import hashlib
import json
import re
import sys
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import qa_building_damage_live as Q  # noqa: E402


class ReadOnlyLivePluginTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

    def test_runner_is_independent_of_chainloader_plugin_and_heartbeats(self):
        source = Q.SRC.read_text(encoding="utf-8")
        self.assertIn("internal sealed class BuildingDamageRuntimeObserver", source)
        self.assertIn("BuildingDamageRuntimeObserver.Start(Logger);", source)
        self.assertNotIn("new UnityEngine.GameObject", source)
        self.assertNotIn("UnityEngine.MonoBehaviour", source)
        self.assertIn("UnityEngine.Application.onBeforeRender += OnBeforeRender;", source)
        self.assertIn("UnityEngine.Application.quitting += OnQuitting;", source)
        self.assertIn("UnityEngine.Application.onBeforeRender -= OnBeforeRender;", source)
        self.assertIn("_harmony.UnpatchSelf();", source)
        self.assertIn("static BuildingDamageRuntimeObserver _active", source)
        self.assertIn("event=runner_heartbeat", source)
        self.assertIn("event=host_destroyed", source)
        self.assertIn("private void OnDestroy()", source)
        log = self.base / "runner.log"
        log.write_text("\n".join([
            "SHCDE_DAMAGE_QA|event=start|status=read_only",
            "SHCDE_DAMAGE_QA|event=host_destroyed|runner_independent=true",
            "SHCDE_DAMAGE_QA|event=runner_heartbeat|frames=60",
            "SHCDE_DAMAGE_QA|event=runner_heartbeat|frames=300",
        ]), encoding="utf-8")
        outcome = Q.evaluate_log(log)
        self.assertEqual(outcome["runnerHeartbeatCount"], 2)
        self.assertTrue(outcome["runnerSurvivedHost"])
        self.assertFalse(outcome["rendererReplacementProved"])

    def test_marker_blocks_random_game_directories(self):
        with self.assertRaisesRegex(Q.QAFailure, "QA-Klon"):
            Q.verify_root(self.base)

    def test_marker_exactness_and_missing_sdk_files(self):
        (self.base / ".sprite-suite-qa-copy.marker").write_text(
            "I am an unrelated game root", encoding="utf-8")
        with self.assertRaisesRegex(Q.QAFailure, "markierter QA-Klon"):
            Q.verify_root(self.base)
        (self.base / ".sprite-suite-qa-copy.marker").write_text(
            Q.EXPECTED_MARKER, encoding="utf-8")
        with self.assertRaisesRegex(Q.QAFailure, "Vertragsdatei"):
            Q.verify_root(self.base)

    def test_installer_is_additive_exclusive_and_rollback_is_sha_bound(self):
        qa = self.base / "qa"
        (qa / "BepInEx" / "plugins").mkdir(parents=True)
        source = self.base / "built.dll"
        source.write_bytes(b"fake-assembly-not-executed")
        result = {
            "dll": source,
            "gameSha256": Q.GAME_SHA,
            "scriptExtenderSha256": Q.SE_SHA
        }
        installed = Q.install_qa(qa, self.base, result)
        self.assertTrue(installed["installedQA"])
        target = Path(installed["path"])
        self.assertEqual(target.read_bytes(), source.read_bytes())
        with self.assertRaisesRegex(Q.QAFailure, "existiert bereits"):
            Q.install_qa(qa, self.base, result)
        target.write_bytes(target.read_bytes() + b"x")
        with self.assertRaisesRegex(Q.QAFailure, "verändert"):
            Q.remove_qa(qa)
        target.write_bytes(source.read_bytes())
        self.assertTrue(Q.remove_qa(qa)["removedQA"])
        self.assertFalse(target.parent.exists())

    def test_extra_user_file_prevents_uninstall(self):
        qa = self.base / "qa"
        (qa / "BepInEx" / "plugins").mkdir(parents=True)
        source = self.base / "built.dll"
        source.write_bytes(b"fake")
        output = Q.install_qa(qa, self.base, {
            "dll": source, "gameSha256": Q.GAME_SHA,
            "scriptExtenderSha256": Q.SE_SHA
        })
        (Path(output["path"]).parent / "user-notes.txt").write_text("keep")
        with self.assertRaisesRegex(Q.QAFailure, "Unbekannte Dateien"):
            Q.remove_qa(qa)

    def test_canary_receipt_requires_explicit_non_readonly_mode_and_hash_lock(self):
        qa = self.base / "qa_canary"
        (qa / "BepInEx" / "plugins").mkdir(parents=True)
        source = self.base / "canary.dll"
        source.write_bytes(b"fake-canary-test-only")
        result = Q.install_qa(qa, self.base, {
            "dll": source, "qaCanary": True,
            "gameSha256": Q.GAME_SHA,
            "scriptExtenderSha256": Q.SE_SHA
        })
        receipt = result["receipt"]
        self.assertIs(receipt["readOnly"], False)
        self.assertIs(receipt["rendererWrites"], True)
        self.assertIs(receipt["qaCanary"], True)
        self.assertTrue(Q.remove_qa(qa)["removedQA"])

    def test_log_report_requires_actual_live_observations(self):
        log = self.base / "LogOutput.log"
        log.write_text("[Info] SHCDE_DAMAGE_QA|event=start|status=read_only|renderer_modified=false\n"
                       "[Info] SHCDE_DAMAGE_QA|event=tile_graphic|building_id=9|global_id=111|tile_id=301|sprite=abbey_0|renderer_modified=false\n"
                       "[Info] SHCDE_DAMAGE_QA|event=building_footprint|building_id=9|global_id=111|grid=5|tiles=301:10,20;302:11,20\n",
                       encoding="utf-8")
        report = Q.evaluate_log(log)
        self.assertEqual(report["sourceLogSHA256"], hashlib.sha256(log.read_bytes()).hexdigest())
        self.assertTrue(report["readOnlyProbeStarted"])
        self.assertEqual(report["tileGraphicObservations"], 1)
        self.assertEqual(report["buildingFootprintObservations"], 1)
        self.assertEqual(report["correlatedTiles"], 1)
        self.assertTrue(report["liveTileFootprintCorrelationObserved"])
        self.assertFalse(report["liveGraphicMappingProved"])
        self.assertFalse(report["rendererReplacementProved"])
        self.assertFalse(report["inGameFullDamageSwitchingProved"])
        log.write_text("[Info] SHCDE_DAMAGE_QA|event=start|status=read_only\n"
                       "[Info] SHCDE_DAMAGE_QA|event=tile_graphic|building_id=9|global_id=112|tile_id=301|sprite=abbey_0|renderer_modified=false\n"
                       "[Info] SHCDE_DAMAGE_QA|event=building_footprint|building_id=9|global_id=111|tiles=301:10,20\n",
                       encoding="utf-8")
        self.assertFalse(Q.evaluate_log(log)["liveTileFootprintCorrelationObserved"])
        log.write_text("[Warning] SHCDE_DAMAGE_QA|event=start|status=disabled|reason=assembly_hash_mismatch\n",
                       encoding="utf-8")
        self.assertFalse(Q.evaluate_log(log)["readOnlyProbeStarted"])

    def test_direct_building_sprite_samples_require_real_assigned_pixels(self):
        log = self.base / "delayed_render.log"
        log.write_text("\n".join([
            "SHCDE_DAMAGE_QA|event=start|status=read_only",
            "SHCDE_DAMAGE_QA|event=building_render_tiles|building_id=12|global_id=202|type=26|assigned_sprites=0|tilemap_sprites=0|renderer_modified=false",
            "SHCDE_DAMAGE_QA|event=building_render_tiles|building_id=12|global_id=202|type=26|assigned_sprites=12|tilemap_sprites=0|renderer_modified=false",
            "SHCDE_DAMAGE_QA|event=building_render_tiles|building_id=14|global_id=204|type=19|assigned_sprites=9|tilemap_sprites=3|renderer_modified=false",
            "SHCDE_DAMAGE_QA|event=building_render_tiles|building_id=18|global_id=208|type=99|assigned_sprites=8|tilemap_sprites=8|renderer_modified=true",
        ]), encoding="utf-8")
        result = Q.evaluate_log(log)
        self.assertEqual(result["buildingRendererTileSamples"], 4)
        self.assertEqual(result["buildingSamplesWithAssignedSprite"], 2)
        self.assertEqual(result["buildingSamplesWithTilemapSprite"], 1)
        self.assertEqual(result["directlySampledBuildingTypes"], ["19", "26"])
        self.assertFalse(result["liveGraphicMappingProved"])
        self.assertFalse(result["rendererReplacementProved"])

    def test_canary_log_requires_actual_single_rebind_and_verified_restore(self):
        log = self.base / "canary.log"
        lines = [
            "SHCDE_DAMAGE_QA|event=start|status=qa_sprite_canary",
            "SHCDE_DAMAGE_QA|event=qa_canary|status=applied|building_id=8|global_id=901|tile_id=111|writes=1",
            "SHCDE_DAMAGE_QA|event=qa_canary|status=restored|building_id=8|global_id=901|tile_id=111|original_restored=True|writes=2",
            "SHCDE_DAMAGE_QA|event=shutdown|status=unpatched|sprite_writes=2",
        ]
        log.write_text("\n".join(lines), encoding="utf-8")
        report = Q.evaluate_log(log)
        self.assertTrue(report["qaSpriteCanaryStarted"])
        self.assertTrue(report["qaCanaryTileRestoredVerified"])
        self.assertTrue(report["qaCanaryCleanShutdownVerified"])
        self.assertTrue(report["qaCanaryRebindAndRestoreVerified"])
        self.assertEqual(report["qaCanaryApplications"], 1)
        self.assertEqual(report["qaCanaryRestorations"], 1)
        self.assertFalse(report["inGameFullDamageSwitchingProved"])
        log.write_text("\n".join(lines[:-1]), encoding="utf-8")
        self.assertTrue(Q.evaluate_log(log)["qaCanaryTileRestoredVerified"])
        self.assertFalse(Q.evaluate_log(log)["qaCanaryRebindAndRestoreVerified"])
        changed = lines.copy()
        changed[2] = changed[2].replace("global_id=901", "global_id=902")
        log.write_text("\n".join(changed), encoding="utf-8")
        self.assertFalse(Q.evaluate_log(log)["qaCanaryRebindAndRestoreVerified"])

    def test_probe_source_contains_no_sprite_or_game_state_writes(self):
        source = Q.SRC.read_text(encoding="utf-8")
        self.assertIn("sprite_writes=0", source)
        # The default read-only assembly excludes all explicitly opt-in
        # SHCDE_QA_SPRITE_CANARY compilation blocks.
        default_source = re.sub(
            r"(?ms)^#if SHCDE_QA_SPRITE_CANARY\n(.*?)^#endif\n",
            lambda block: block[1].partition("#else\n")[2],
            source,
        )
        self.assertIsNone(re.search(r"\b\w+\.tileImage\s*=(?!=)", default_source))
        for renderer_write in ("SetSprite(", "SetTile(", "RefreshTile("):
            self.assertNotIn(renderer_write, default_source)
        self.assertIsNone(re.search(r"\bsprRenderer\.sprite\s*=(?!=)", default_source))
        self.assertNotIn("SetCurrentHealth", source)
        self.assertNotIn("SetTileGraphic", source)
        self.assertIn("renderer_modified=false", source)
        self.assertIn("GetTileBuildingId", source)

    def test_tilemap_evidence_reads_real_sprite_references(self):
        source = Q.SRC.read_text(encoding="utf-8")
        self.assertIn("tile.tilemapRef.GetSprite(", source)
        self.assertIn("GameMap.instance.getMapTile(", source)
        self.assertIn("event=building_render_tiles", source)
        self.assertIn("|tilemap_sprite=", source)
        self.assertIn("renderer_modified=false", source)
        self.assertIn("sample_count=", source)
        self.assertIn('app.ReportFailure("tilemap_sprite", readError)', source)
        self.assertIn('ReportFailure("render_tilemap_sprite", readError)', source)
        self.assertIn("UnityEngine.TilemapModule.dll", " ".join(Q.REFS))
        self.assertIn("UnityEngine.GridModule.dll", " ".join(Q.REFS))


if __name__ == "__main__":
    unittest.main()

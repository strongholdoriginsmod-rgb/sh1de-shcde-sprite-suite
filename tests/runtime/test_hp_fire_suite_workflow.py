"""Creative HP/fire runtime packaging, mapping and non-blocking QA contracts."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import building_damage_bindings as B
import building_damage_package_check as P
import qa_hp_fire_live_log as L
import suite_building_damage_live_mod as W
from suite_tool_policy import classify
from suite_tool_registry import SPECIALISTS


def graphic(x, y, name, index, occupied):
    return {
        "x": str(x), "y": str(y), "sprite": name, "gm": "6",
        "image": str(index), "occupied_index": str(occupied),
        "global_id": "661027", "type": "104",
    }


def test_grid_order_and_rotations_are_independent_of_whitelisted_games():
    assert B.stage_positions(2, 2) == [(0, 0), (1, 0), (0, 1), (1, 1)]
    assert len(B.stage_positions(5, 5)) == 25
    assert len(B.stage_positions(8, 8)) == 64
    assert set(B.TRANSFORMS) == {
        "identity", "rotate90", "rotate180", "rotate270",
        "reflect_u", "reflect_v", "swap", "reverse_swap"
    }


def test_artwork_outside_gameplay_footprint_receives_editable_owner_offsets():
    events = [
        graphic(10, 20, "tile_buildings1 1", 1, 0),
        graphic(11, 20, "tile_buildings1 2", 2, 1),
        graphic(10, 21, "tile_buildings1 3", 3, -1),
        graphic(11, 21, "tile_buildings1 4", 4, -1),
    ]
    result = B.propose(events, 2, 2, "my-building", 104)
    assert len(result["bindings"]) == 4
    assert result["provenance"]["proposedOverhangOwnerOffsets"] == 2
    assert result["provenance"]["unresolvedOverhangOwnerOffsets"] == 0
    assert {(b["ownerOffsetX"], b["ownerOffsetY"]) for b in result["bindings"]} == {
        (0, 0), (0, -1)
    }
    assert result["provenance"]["mappingConfirmedInGame"] is False


def test_empty_occupancy_is_a_diagnostic_not_an_approval_gate():
    events = [graphic(10, 20, "custom", 19, -1)]
    result = B.propose(events, 1, 1, "my-building", 99999)
    assert len(result["bindings"]) == 1
    assert result["provenance"]["unresolvedOverhangOwnerOffsets"] == 1
    assert result["bindings"][0]["ownerOffsetX"] == 0


def test_user_creative_unreviewed_archive_inspection(tmp_path):
    src = tmp_path / "creative-art.zip"
    png = b"\x89PNG\r\n\x1a\n" + b"example-synthetic-data"
    manifest = {
        "format": "stronghold-building-damage-library", "version": 719,
        "buildings": [{
            "id": "custom-building", "gameBuildingType": 735,
            "stages": [{
                "id": "creative-stage", "damageKind": "fire", "hpAtOrBelow": 33,
                "reviewStatus": "draft",
                "tiles": [{
                    "slot": 9, "image": "damage/custom/9.png",
                    "sha256": hashlib.sha256(png).hexdigest()
                }]
            }]
        }]
    }
    with ZipFile(src, "x") as archive:
        archive.writestr("damage-manifest.json", json.dumps(manifest))
        archive.writestr("damage/custom/9.png", png)
    settings = {"bindings": [{"buildingGroupId": "custom-building",
                              "buildingType": 735, "slot": 9}]}
    report = P.inspect_archive(src, settings)
    assert report["validPngEntries"] == 1
    assert report["bindingsWithStageArt"] == 1
    assert not report["findings"]
    assert report["visualHpAndFireRuntimeTested"] is False


def test_command_builder_does_not_limit_version_folder_or_mod_content(tmp_path):
    root = tmp_path / "Spiel mit Sonderzeichen äöü"
    out = tmp_path / "other-output"
    settings = tmp_path / "user-runtime.json"
    archive = tmp_path / "any-version.zip"
    args = W.command(root, out, install=True, damage_archive=archive,
                     runtime_config=settings)
    assert "-Install" in args
    assert str(root) in args
    assert str(settings) in args
    assert str(archive) in args
    assert W.command(root, out).count("-Install") == 0
    assert classify("suite_building_damage_live_mod.py", ["--install"]).category == "game"
    assert classify("suite_building_damage_live_mod.py", []).category == "workspace"
    assert classify("building_damage_package_check.py", []).category == "read"


def test_suite_index_exposes_real_live_damage_workflows():
    names = [item.filename for item in SPECIALISTS]
    for name in ("suite_building_damage_live_mod.py",
                 "building_damage_bindings.py",
                 "building_damage_package_check.py"):
        assert names.count(name) == 1
        assert (ROOT / "tools" / name).is_file()


def simulated_cycle():
    values = []
    for event, props in [
        ("stage_applied", {"kind": "mechanical", "stage": "m75", "preview": "True",
                           "renderer_modified": "true"}),
        ("stage_applied", {"kind": "fire", "stage": "f40", "preview": "True",
                           "renderer_modified": "true"}),
        ("restored", {})]:
        p = dict(props, event=event, global_id="311", building_id="2",
                 x="3", y="5", live_hp="100", live_max="100", live_fire_ticks="0")
        values.append(p)
    return values


def test_log_report_checks_same_tiles_and_order_without_fake_live_hp_claims():
    report = L.report(simulated_cycle())
    assert report["mechanicalApplyEvents"] == 1
    assert report["fireApplyEvents"] == 1
    assert report["vanillaRestoreEvents"] == 1
    assert report["orderedCompletedTileCycles"] == 1
    assert report["completePreviewCycleObserved"] is True
    assert report["appliedEventsArePreviewOnly"] is True
    assert report["actualGameplayHpChangeProved"] is False
    assert report["screenPixelsVisuallyReviewed"] is False


def test_log_report_rejects_reverse_rollback_order():
    events = simulated_cycle()
    report = L.report([events[2], events[0], events[1]])
    assert report["completePreviewCycleObserved"] is False
    assert report["orderedCompletedTileCycles"] == 0


def test_log_report_does_not_match_stages_across_a_restore_or_call_live_data_preview():
    mechanical, fire, restored = simulated_cycle()
    report = L.report([mechanical, restored, fire, restored])
    assert report["orderedCompletedTileCycles"] == 0
    assert not report["completePreviewCycleObserved"]
    fire["preview"] = "False"
    report = L.report([mechanical, fire, restored])
    assert report["orderedCompletedTileCycles"] == 1
    assert not report["completePreviewCycleObserved"]


def test_log_parser_finds_nested_fields_without_game_process():
    source = "\n".join(
        "[Info] SPRITESUITE_DAMAGE|" +
        "|".join(str(k) + "=" + str(v) for k, v in event.items())
        for event in simulated_cycle())
    output = L.report(L.parse_events(source))
    assert output["completePreviewCycleObserved"]
    with pytest.raises(ValueError, match="Duplicate"):
        L.parse_events("SPRITESUITE_DAMAGE|event=restored|event=again")


def test_full_runtime_source_avoids_missing_framework_assemblies():
    runtime = (ROOT / "runtime" / "StrongholdEuropeDE.BuildingDamage.LiveMod"
               / "runtime" / "BuildingDamageLiveMod.cs").read_text("utf-8")
    parser = (ROOT / "runtime" / "StrongholdEuropeDE.BuildingDamage.LiveMod"
              / "runtime" / "DamageJsonParser.cs")
    assert parser.is_file()
    assert "using System.IO.Compression" not in runtime
    assert "ZipArchive" not in runtime
    assert "DamageJsonParser.Library(json)" in runtime
    assert "t.Tile.tileImage = replacement;" in runtime
    assert "t.Tile.tileImage = t.Original;" in runtime
    assert "SPRITESUITE_DAMAGE|event=controls_reloaded" in runtime


@pytest.mark.skipif(sys.platform != "win32" or not shutil.which("powershell.exe"),
                    reason="Windows PowerShell installer")
def test_installer_preserves_previous_files_on_conflict_or_partial_update(tmp_path, monkeypatch):
    game = tmp_path / "Spiel äöü"
    out = tmp_path / "compile"
    plugin = game / "BepInEx" / "plugins" / "SpriteSuiteBuildingDamageRuntime"
    for group, names in {
        "BepInEx/core": ("BepInEx.dll", "0Harmony.dll"),
        "BepInEx/plugins/000shcdese": ("SHCDESE.dll",),
        "Stronghold Crusader Definitive Edition_Data/Managed": (
            "Assembly-CSharp.dll", "UnityEngine.dll", "UnityEngine.CoreModule.dll",
            "UnityEngine.TilemapModule.dll", "UnityEngine.GridModule.dll",
            "UnityEngine.ImageConversionModule.dll", "UnityEngine.JSONSerializeModule.dll",
            "UnityEngine.InputLegacyModule.dll",
        ),
    }.items():
        parent = game / group
        parent.mkdir(parents=True)
        for name in names:
            (parent / name).touch()

    # The compiler is unrelated to the transaction. Use a deterministic stand-in
    # so the regression test needs neither private game binaries nor a C# SDK.
    script = tmp_path / "compiler.py"
    script.write_text(
        "from pathlib import Path\n"
        "import sys\n"
        "target = next(arg[5:] for arg in sys.argv[1:] if arg.startswith('/out:'))\n"
        "Path(target).write_bytes(Path(__file__).with_suffix('.data').read_bytes())\n",
        encoding="utf-8",
    )
    compiler = tmp_path / "compiler.cmd"
    # cmd.exe reads batch text in the OEM code page. Keep the script ASCII
    # so portable installations and workspaces with Unicode paths still work.
    monkeypatch.setenv("SPRITESUITE_TEST_COMPILER_PYTHON", sys.executable)
    compiler.write_text('@"%SPRITESUITE_TEST_COMPILER_PYTHON%" "%~dp0compiler.py" %*\n',
                        encoding="ascii")
    input_binary = script.with_suffix(".data")
    input_binary.write_bytes(b"first build")
    config = tmp_path / "runtime.json"
    config.write_text(json.dumps({"damageDirectory": "Grafiken äöü"}, ensure_ascii=False),
                      encoding="utf-8")
    archive = tmp_path / "damage.zip"
    with ZipFile(archive, "w") as package:
        package.writestr("damage-manifest.json", '{"buildings":[]}')
    command = W.command(game, out, install=True, runtime_config=config)

    def install(*extra):
        return subprocess.run([*command, "-Csc", str(compiler), *extra],
                              capture_output=True, encoding="utf-8", errors="replace",
                              timeout=120, check=False)

    first = install("-DamageArchive", str(archive))
    assert first.returncode == 0, first.stderr
    assert (plugin / "Grafiken äöü" / "damage-manifest.json").is_file()
    before = {file.name: file.read_bytes() for file in plugin.iterdir() if file.is_file()}
    input_binary.write_bytes(b"second build")
    # Keep the original art destination in the attempted replacement config.
    config.write_text(json.dumps({"enabled": False, "damageDirectory": "Grafiken äöü"},
                                 ensure_ascii=False), encoding="utf-8")
    duplicate = install("-DamageArchive", str(archive))
    assert duplicate.returncode != 0
    assert "already exists" in duplicate.stderr
    assert all((plugin / name).read_bytes() == data for name, data in before.items())

    # Fail after replacement of the DLL, while leaving user-owned content alone.
    info = plugin / "info.json"
    info.unlink()
    info.mkdir()
    failed = install()
    assert failed.returncode != 0
    assert info.is_dir()
    assert (plugin / W.DLL_NAME).read_bytes() == before[W.DLL_NAME]
    assert (plugin / "runtime.json").read_bytes() == before["runtime.json"]

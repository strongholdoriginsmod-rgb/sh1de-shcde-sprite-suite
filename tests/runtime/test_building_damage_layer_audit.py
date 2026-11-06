"""Adversarial, no-network tests of the SHCDE building graphics/footprint audit."""
from __future__ import annotations
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import building_damage_layer_audit as L  # noqa: E402

def sample_events() -> bytes:
    return ("\n".join([
        "[Info] SHCDE_DAMAGE_QA|event=building_footprint|building_id=8|global_id=9001|type=104|grid=2|tile_count=2|tiles=111:10,20;112:11,20",
        "[Info] SHCDE_DAMAGE_QA|event=tile_graphic|building_id=8|global_id=9001|type=104|tile_id=111|x=10|y=20|sprite=tile_buildings1 500|gm=6|image=500|occupied_index=0|occupied_count=2|renderer_modified=false",
        "[Info] SHCDE_DAMAGE_QA|event=tile_graphic|building_id=8|global_id=9001|type=104|tile_id=113|x=12|y=20|sprite=tile_buildings1 502|gm=6|image=502|occupied_index=-1|occupied_count=2|renderer_modified=false",
        "[Info] SHCDE_DAMAGE_QA|event=building_render_tiles|building_id=8|global_id=9001|type=104|assigned_sprites=2|tilemap_sprites=0|samples=111:10,20:tile_land_macros 004~64x32~64:none;112:11,20:tile_rocks8 002~64x39~64:none|renderer_modified=false",
    ]) + "\n").encode("utf-8")

class LayerAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.log = self.directory / "qa.log"
        self.raw = sample_events()
        self.log.write_bytes(self.raw)

    def test_occupied_and_outside_draws_are_not_merged_into_one_layer(self):
        result = L.analyze_events(L.parse_log_bytes(self.raw))
        total = result["summary"]
        self.assertEqual(total["uniqueBuildingIdentities"], 1)
        self.assertEqual(total["identitiesWithBothFootprintAndGraphic"], 1)
        self.assertEqual(total["graphics_within_gameplay_footprint"], 1)
        self.assertEqual(total["graphics_outside_gameplay_footprint"], 1)
        self.assertEqual(total["drawingSpriteFamilies"]["tile_buildings1"], 2)
        building = result["buildings"][0]
        self.assertEqual(building["footprintTileCount"], 2)
        self.assertEqual(building["drawingIDsAlsoInReportedFootprint"], 1)
        self.assertEqual(building["defaultLayerSpriteFamilies"],
                         {"tile_land_macros": 1, "tile_rocks8": 1})
        self.assertFalse(result["directRendererMutationAllowed"])
        self.assertFalse(building["rendererMappingVerified"])
        self.assertFalse(result["inGameDamageSwitchVerified"])

    def test_global_identity_reuse_is_not_merged(self):
        entries = self.raw + (
            "[Info] SHCDE_DAMAGE_QA|event=tile_graphic|building_id=8|global_id=9002|type=104|tile_id=114|x=13|y=20|sprite=tile_buildings1 503|gm=6|image=503|occupied_index=-1|occupied_count=2\n"
        ).encode()
        result = L.analyze_events(L.parse_log_bytes(entries))
        self.assertEqual(result["summary"]["uniqueBuildingIdentities"], 2)

    def test_changed_type_with_same_global_identity_is_rejected(self):
        entries = self.raw + (
            "SHCDE_DAMAGE_QA|event=tile_graphic|building_id=8|global_id=9001|type=105|tile_id=114|x=13|y=20|occupied_index=-1|occupied_count=2\n"
        ).encode()
        with self.assertRaisesRegex(L.AuditError, "Building type changed"):
            L.analyze_events(L.parse_log_bytes(entries))

    def test_corrupt_or_duplicated_log_evidence_is_rejected(self):
        with self.assertRaisesRegex(L.AuditError, "Duplicate field"):
            L.parse_log_bytes(b"SHCDE_DAMAGE_QA|event=tile_graphic|building_id=8|building_id=9\n")
        with self.assertRaisesRegex(L.AuditError, "Duplicated footprint"):
            L.tile_set("111:10,20;111:11,20")
        with self.assertRaisesRegex(L.AuditError, "Malformed render"):
            L.parse_render_samples("111:10,20:only_three_parts")

    def test_sha_pinned_output_is_exclusive(self):
        checksum = hashlib.sha256(self.raw).hexdigest()
        out = self.directory / "report.json"
        with redirect_stdout(io.StringIO()):
            self.assertEqual(L.main(["--log", str(self.log),
                                     "--expected-sha256", checksum,
                                     "--output", str(out)]), 0)
        result = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(result["sourceLogSHA256"], checksum)
        self.assertFalse(result["directRendererMutationAllowed"])
        with redirect_stderr(io.StringIO()):
            self.assertEqual(L.main(["--log", str(self.log),
                                     "--expected-sha256", checksum,
                                     "--output", str(out)]), 2)
            self.assertEqual(L.main(["--log", str(self.log),
                                     "--expected-sha256", "0" * 64]), 2)

if __name__ == "__main__":
    unittest.main()

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

    def test_full_drawn_square_uses_sprite_suite_diagonal_order_without_approving_orientation(self):
        drawing = []
        for y in range(3):
            for x in range(3):
                drawing.append({"tileId": 100 + y * 3 + x, "x": 10 + x,
                    "y": 20 + y, "gm": "6", "image": str(200 + y * 3 + x),
                    "withinGameFootprint": x < 2 and y < 2})
        plan = L.graphics_slot_hypotheses(list(reversed(drawing)))
        self.assertEqual(plan["status"], "complete_drawn_rectangle_orientation_unverified")
        self.assertFalse(plan["verified"])
        self.assertTrue(plan["orientationChoiceRequired"])
        self.assertEqual(len(plan["hypotheses"]), 8)
        normal = next(p for p in plan["hypotheses"] if p["orientation"] == "xy+u+v")
        self.assertEqual((normal["spriteA"], normal["spriteB"]), (3, 3))
        self.assertEqual([slot["tileId"] for slot in normal["slots"]],
                         [100, 101, 103, 102, 104, 106, 105, 107, 108])
        self.assertEqual(sum(s["inNativeFootprint"] for s in normal["slots"]), 4)
        self.assertFalse(normal["verified"])
        # Permuting incoming engine callback order never changes the slot list.
        permuted = L.graphics_slot_hypotheses(drawing[3:] + drawing[:3])
        other = next(p for p in permuted["hypotheses"] if p["orientation"] == "xy+u+v")
        self.assertEqual(normal["slots"], other["slots"])

    def test_full_visual_rectangle_uses_all_drawing_tiles_not_occupied_subset(self):
        drawing = []
        for y in range(3):
            for x in range(2):
                drawing.append({"tileId": 100 + y * 2 + x,
                    "x": 20 + x, "y": 30 + y, "gm": "6",
                    "image": str(300 + y * 2 + x),
                    "withinGameFootprint": x == 0})
        plan = L.graphics_slot_hypotheses(drawing)
        self.assertEqual(len(plan["hypotheses"]), 8)
        self.assertEqual({(o["spriteA"], o["spriteB"])
                          for o in plan["hypotheses"]}, {(2, 3), (3, 2)})
        self.assertEqual([o["orientation"] for o in plan["hypotheses"][:2]],
                         ["xy+u+v", "xy+u-v"])

    def test_single_tile_never_becomes_approved_renderer_mapping(self):
        single = [{"tileId": 29, "x": 2, "y": 3,
                   "gm": "1", "image": "2", "withinGameFootprint": True}]
        plan = L.graphics_slot_hypotheses(single)
        self.assertEqual(len(plan["hypotheses"]), 1)
        self.assertFalse(plan["verified"])
        self.assertFalse(plan["hypotheses"][0]["verified"])

    def test_incomplete_duplicate_or_inconsistent_drawings_never_generate_targets(self):
        original = [{"tileId": i, "x": i % 3, "y": i // 3,
                     "gm": "6", "image": str(100 + i),
                     "withinGameFootprint": True} for i in range(9)]
        incomplete = L.graphics_slot_hypotheses(original[:7])
        self.assertEqual(incomplete["status"], "incomplete_graphics_rectangle")
        self.assertEqual(incomplete["hypotheses"], [])
        duplicate_graphic = original[:] + [dict(original[0], image="changed")]
        self.assertEqual(L.graphics_slot_hypotheses(duplicate_graphic)["status"],
                         "multiple_graphics_per_coordinate")
        moved = original[:] + [dict(original[0], x=20)]
        self.assertEqual(L.graphics_slot_hypotheses(moved)["status"],
                         "same_graphic_tile_id_at_multiple_positions")

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

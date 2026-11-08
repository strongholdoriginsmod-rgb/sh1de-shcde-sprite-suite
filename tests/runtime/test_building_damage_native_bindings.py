"""Native granary slot proposals are pixel-checked and never enabled by tests."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import building_damage_native_bindings as N  # noqa: E402


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


class NativeGranaryBindingTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / "raw_sprites").mkdir()
        self.manifest = self.root / "original_sprite_reference.json"
        self.draft = self.root / "draft_pipeline_manifest.json"
        original = {}
        slots = []
        for v in range(4):
            for u in range(4):
                n = 278 + v * 4 + u
                name = f"tile_buildings2 {n}"
                raw = Image.new("RGBA", (64, 32), (u, v, n % 255, 255))
                output = io.BytesIO()
                raw.save(output, format="PNG")
                data = output.getvalue()
                (self.root / "raw_sprites" / f"tile_buildings2_{n}.png").write_bytes(data)
                original[name] = {
                    "png": f"raw_sprites/tile_buildings2_{n}.png",
                    "pngSHA256": sha(data), "rgbaSHA256": sha(raw.tobytes()),
                    "width": 64, "height": 32, "pivotX": .5, "pivotY": .5,
                    "ppu": 64.0,
                }
                slots.append({
                    "sprite": name, "gm": "7", "image": str(n),
                    "tileId": 86875 + n, "x": 250 - u, "y": 294 - v,
                    "inNativeFootprint": True,
                })
        preview = b"synthetic-preview-for-tests-only"
        (self.root / "preview_xy-u-v.png").write_bytes(preview)
        self.reference_obj = {
            "format": "spritesuite-shcde-original-graphics-visual-proof",
            "gameBuildingType": 19,
            "gameBuildingTypeName": "STRUCT_GRANARY",
            "graphicsGridA": 4, "graphicsGridB": 4,
            "drawnSpriteTileCount": 16, "orientationVerifiedInGame": False,
            "approvedDamageModelsAvailable": False, "buildingId": 172,
            "globalId": 7333542, "gameAssetSHA256": "a"*64,
            "mappingSHA256": "b"*64, "sourceGameLogSHA256": "c"*64,
            "nativeSpriteImages": original,
            "orientations": [{
                "orientation": "xy-u-v", "reviewed": False,
                "approvedForRenderer": False, "spriteA": 4, "spriteB": 4,
                "slots": slots, "preview": "preview_xy-u-v.png",
                "previewSHA256": sha(preview),
            }]
        }
        self.draft_obj = {
            "format": "spritesuite-building-damage-draft-generation-requests",
            "gameBuildingType": 19, "nativeBaseSceneId": "g_native_19",
            "modelGenerationExecuted": False, "generatedDamageAssets": 0,
            "approvedDamageStages": 0, "readyRequestCount": 2,
            "blockedRequestCount": 6, "requests": [{} for _ in range(8)],
        }

    def make(self, ref=None, draft=None):
        self.manifest.write_text(json.dumps(ref if ref is not None else self.reference_obj),
                                 encoding="utf-8")
        self.draft.write_text(json.dumps(draft if draft is not None else self.draft_obj),
                              encoding="utf-8")
        return N.generate(self.manifest, sha(self.manifest.read_bytes()),
                          self.draft, sha(self.draft.read_bytes()))

    def test_exact_sprites_create_disabled_instance_scoped_binding(self):
        report = self.make()
        self.assertIs(report["enabled"], False)
        self.assertIs(report["previewEnabled"], False)
        self.assertEqual(len(report["bindings"]), 16)
        self.assertEqual({row["slot"] for row in report["bindings"]}, set(range(16)))
        self.assertEqual({row["buildingGlobalId"] for row in report["bindings"]}, {7333542})
        self.assertEqual({row["buildingType"] for row in report["bindings"]}, {19})
        self.assertTrue(all(not row["overridePivot"] and not row["overridePpu"]
                            for row in report["bindings"]))
        self.assertFalse(report["provenance"]["mappingConfirmedInGame"])
        self.assertEqual(report["provenance"]["originalPngRGBAValidated"], 16)
        self.assertEqual(report["provenance"]["approvedDamageStages"], 0)

    def test_source_byte_change_rejected(self):
        self.make()
        target = self.root / "raw_sprites" / "tile_buildings2_278.png"
        target.write_bytes(target.read_bytes() + b"tamper")
        with self.assertRaisesRegex(N.BindingError, "Source SHA-256 mismatch"):
            self.make()

    def test_false_generated_or_approved_draft_rejected(self):
        for key, value in (("approvedDamageStages", 1),
                           ("modelGenerationExecuted", True),
                           ("generatedDamageAssets", 8)):
            with self.subTest(key=key):
                draft = deepcopy(self.draft_obj)
                draft[key] = value
                with self.assertRaisesRegex(N.BindingError, "unapproved"):
                    self.make(draft=draft)

    def test_wrong_type_or_already_approved_mapping_rejected(self):
        for key, value in (("gameBuildingType", 104),
                           ("orientationVerifiedInGame", True)):
            with self.subTest(key=key):
                reference = deepcopy(self.reference_obj)
                reference[key] = value
                with self.assertRaisesRegex(N.BindingError, "contract"):
                    self.make(ref=reference)

    def test_duplicate_or_outside_footprint_rejected(self):
        for key, value in (("tileId", self.reference_obj["orientations"][0]["slots"][0]["tileId"]),
                           ("inNativeFootprint", False)):
            reference = deepcopy(self.reference_obj)
            reference["orientations"][0]["slots"][1][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(N.BindingError, "slot"):
                self.make(ref=reference)

    def test_preview_and_ppu_mismatch_rejected(self):
        reference = deepcopy(self.reference_obj)
        reference["nativeSpriteImages"]["tile_buildings2 278"]["ppu"] = 100.0
        with self.assertRaisesRegex(N.BindingError, "pivot or PPU"):
            self.make(ref=reference)
        self.make()
        (self.root / "preview_xy-u-v.png").write_bytes(b"altered")
        with self.assertRaisesRegex(N.BindingError, "SHA-256 mismatch"):
            self.make()


if __name__ == "__main__":
    unittest.main()

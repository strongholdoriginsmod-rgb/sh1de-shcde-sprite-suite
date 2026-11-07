"""Offline tests: native SHCDE source extraction, bitmap order and provenance."""
from __future__ import annotations

import gzip
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"tools"))
import building_damage_original_reference as B

NAME = "tile_buildings1 "


def synthetic_log() -> bytes:
    lines=[
        "SHCDE_DAMAGE_QA|event=building_footprint|building_id=19|global_id=9001|type=19|grid=2|tile_count=4|tiles=101:10,20;102:11,20;103:10,21;104:11,21"
    ]
    for i,(x,y) in enumerate(((10,20),(11,20),(10,21),(11,21))):
        lines.append("SHCDE_DAMAGE_QA|event=tile_graphic|building_id=19|global_id=9001|type=19|tile_id="+str(101+i)+
                     "|x="+str(x)+"|y="+str(y)+"|sprite="+NAME+str(100+i)+
                     "|gm=6|image="+str(100+i)+"|occupied_index="+str(i)+
                     "|occupied_count=4|renderer_modified=false")
    return ("\n".join(lines)+"\n").encode()


class OriginalReferenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name)
        self.log=self.base/"game.log"
        self.raw=synthetic_log()
        self.log.write_bytes(self.raw)
        self.rows=[
            {"group":"tile_buildings1","name":NAME+str(100+i),
             "target":{"path_id":200+i,"width":64,"height":32,
                       "pivot_x":.5,"pivot_y":.5,"pixels_per_unit":64.0,
                       "texture_name":"AllTileSprites"}}
            for i in range(4)
        ]
        data={"target_build_id":"local-shcde-2.80-unity-2021.3.45f2",
              "sprites":self.rows}
        self.mapping=self.base/"mapping.json.gz"
        self.mapping.write_bytes(gzip.compress(json.dumps(data).encode()))

    def test_pin_mapping_and_native_labels(self):
        rows=B.verified_mapping(self.mapping,B.digest(self.mapping.read_bytes()))
        self.assertEqual(len(rows),4)
        self.assertEqual(rows[NAME+"101"]["target"]["path_id"],201)
        with self.assertRaisesRegex(B.OriginalImageError,"SHA-256 mismatch"):
            B.verified_mapping(self.mapping,"0"*64)
        data={"target_build_id":"wrong-version","sprites":self.rows}
        self.mapping.write_bytes(gzip.compress(json.dumps(data).encode()))
        with self.assertRaisesRegex(B.OriginalImageError,"another game build"):
            B.verified_mapping(self.mapping,B.digest(self.mapping.read_bytes()))

    def test_gzip_mapping_expansion_is_bounded_before_json_parse(self):
        # A compressed file may have an enormous uncompressed expansion
        # even when the compressed bytes and SHA match.
        mapped=B.digest(self.mapping.read_bytes())
        with patch.object(B,"MAX_MAPPING_DECOMPRESSED_BYTES",64):
            with self.assertRaisesRegex(B.OriginalImageError,
                                         "Decompressed sprite mapping"):
                B.verified_mapping(self.mapping,mapped)

    def test_duplicate_native_unity_sprite_path_ids_refused(self):
        original = self.rows[0]
        duplicate = dict(self.rows[1])
        duplicate["target"] = {**self.rows[1]["target"],
                               "path_id": original["target"]["path_id"]}
        mapping={original["name"]: original, duplicate["name"]:duplicate}
        file=self.base/"resources.assets"
        file.write_bytes(b"synthetic asset file; never loaded")
        with self.assertRaisesRegex(B.OriginalImageError,
                                    "Multiple native sprite names"):
            B.read_original_frames(file,[
                {"sprite":original["name"]},{"sprite":duplicate["name"]}],mapping)

    def test_export_failure_cleans_only_its_own_partial_directory(self):
        building,visual=B.target_from_log(self.log,B.digest(self.raw),19,9001)
        output=self.base/"failed_export"
        with self.assertRaises(KeyError):
            B.save_export(output,building,visual,{},
                          "a"*64,"b"*64,B.digest(self.raw))
        self.assertFalse(output.exists())
        self.assertEqual(list(self.base.glob("failed_export.spritesuite-*.working")),[])
        self.assertTrue(self.log.is_file())

    def test_native_game_type_catalog_distinguishes_granary_from_pond(self):
        catalog = self.base / "types.json"
        payload = {"format":"spritesuite-shcdese-building-type-index",
                   "version":1, "sourceDLLSHA256":B.SHCDESE_BUILDING_API_SHA256,
                   "enumType":"SHCDESE.Interop.eStructs",
                   "values":[
                       {"value":19,"name":"STRUCT_GRANARY"},
                       {"value":104,"name":"STRUCT_POND"},
                       {"value":108,"name":"STRUCT_BEDOUIN_STOCKADE"},
                   ]}
        catalog.write_text(json.dumps(payload), encoding="utf8")
        checksum=B.digest(catalog.read_bytes())
        self.assertEqual(B.game_type_label(catalog,checksum,19),"STRUCT_GRANARY")
        self.assertEqual(B.game_type_label(catalog,checksum,104),"STRUCT_POND")
        self.assertEqual(B.game_type_label(catalog,checksum,108),"STRUCT_BEDOUIN_STOCKADE")
        with self.assertRaisesRegex(B.OriginalImageError,"Missing or ambiguous"):
            B.game_type_label(catalog,checksum,37)
        payload["values"].append({"value":19,"name":"STRUCT_FAKE_GRANARY"})
        catalog.write_text(json.dumps(payload),encoding="utf8")
        with self.assertRaisesRegex(B.OriginalImageError,"ambiguous"):
            B.game_type_label(catalog,B.digest(catalog.read_bytes()),19)
        payload["sourceDLLSHA256"]="a"*64
        catalog.write_text(json.dumps(payload),encoding="utf8")
        with self.assertRaisesRegex(B.OriginalImageError,"verified SHCDESE"):
            B.game_type_label(catalog,B.digest(catalog.read_bytes()),19)

    def test_duplicate_mapping_labels_fail(self):
        data={"target_build_id":"local-shcde-2.80-unity-2021.3.45f2",
              "sprites":self.rows+[self.rows[0]]}
        self.mapping.write_bytes(gzip.compress(json.dumps(data).encode()))
        with self.assertRaisesRegex(B.OriginalImageError,"Duplicate"):
            B.verified_mapping(self.mapping,B.digest(self.mapping.read_bytes()))

    def test_real_graphics_grid_selected_by_global_identity(self):
        building,visual=B.target_from_log(self.log,B.digest(self.raw),19,9001)
        self.assertEqual(building["drawingEventCount"],4)
        self.assertEqual(visual["distinctGraphicTiles"],4)
        self.assertEqual(len(visual["hypotheses"]),8)
        with self.assertRaisesRegex(B.OriginalImageError,"absent"):
            B.target_from_log(self.log,B.digest(self.raw),19,9002)
        with self.assertRaisesRegex(B.OriginalImageError,"SHA-256"):
            B.target_from_log(self.log,"0"*64,19,9001)

    def test_native_sprite_geometry_follows_sprite_suite_diagonal_contract(self):
        positions=B.visual_positions(2,2)
        self.assertEqual([(p["u"],p["v"],p["x"],p["bottom"]) for p in positions],
                         [(0,0,0,0),(1,0,-32,-16),(0,1,32,-16),(1,1,0,-32)])
        for w,h in ((4,4),(7,7),(8,8),(3,4)):
            positions=B.visual_positions(w,h)
            self.assertEqual(len(positions),w*h)
            self.assertEqual({(p["u"],p["v"]) for p in positions},
                             {(i,j) for i in range(w) for j in range(h)})

    def test_exact_original_frames_preserved_in_all_preview_hypotheses(self):
        building, visual=B.target_from_log(self.log,B.digest(self.raw),19,9001)
        sprites={}
        for i in range(4):
            rgba=Image.new("RGBA",(64,32),(33+i*20,44+i*10,55+i*3,255))
            sprites[NAME+str(100+i)]={
                "image":rgba,"pathId":200+i,"pivotX":.5,"pivotY":.5,
                "ppu":64.0,"nativeTexture":"AllTileSprites"}
        preview,sheet=B.build_frames(building,visual,sprites)
        self.assertEqual(len(preview),8)
        self.assertEqual(sheet.size,(2480,800))
        self.assertEqual({p["orientation"] for p in preview},{
            "xy+u+v","xy+u-v","xy-u+v","xy-u-v",
            "yx+u+v","yx+u-v","yx-u+v","yx-u-v"})
        self.assertTrue(all(p["composite"].getchannel("A").getbbox()
                            for p in preview))
        directory=self.base/"visual-reference"
        result=B.save_export(directory,building,visual,sprites,
                    "a"*64,"b"*64,B.digest(self.raw))
        self.assertEqual(result["drawnSpriteTileCount"],4)
        self.assertEqual(len(result["orientations"]),8)
        self.assertFalse(result["orientationVerifiedInGame"])
        self.assertFalse(result["approvedDamageModelsAvailable"])
        for name,meta in result["nativeSpriteImages"].items():
            data=(directory/meta["png"]).read_bytes()
            self.assertEqual(B.digest(data),meta["pngSHA256"])
            with Image.open(io.BytesIO(data)) as png:
                self.assertEqual(B.digest(png.convert("RGBA").tobytes()),
                                 meta["rgbaSHA256"])
        with self.assertRaisesRegex(B.OriginalImageError,"already exists"):
            B.save_export(directory,building,visual,sprites,
                    "a"*64,"b"*64,B.digest(self.raw))

    def test_no_imaginary_completed_graphics_accepted(self):
        extra=self.raw.replace(b"tile_id=103",b"tile_id=102").replace(b"x=10|y=21",b"x=11|y=20")
        log=self.base/"bad.log"
        log.write_bytes(extra)
        with self.assertRaisesRegex(B.OriginalImageError,"complete visual sprite grid"):
            B.target_from_log(log,B.digest(extra),19,9001)


if __name__=="__main__":
    unittest.main()

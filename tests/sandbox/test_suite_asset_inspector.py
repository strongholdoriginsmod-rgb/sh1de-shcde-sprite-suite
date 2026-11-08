"""Synthetic non-destructive shared asset-inspector regression."""
from pathlib import Path
import hashlib
import json
import struct

import pytest
from PIL import Image
from suite_asset_inspector import inspect_assets, AssetInspectionError, _dds_info


def build_assets(tmp_path):
    root = tmp_path / "assets"
    (root / "Override" / "Sprites").mkdir(parents=True)
    (root / "Patches" / "Assets" / "GUI" / "XAML").mkdir(parents=True)
    img = root / "Override" / "Sprites" / "tower.png"
    Image.new("RGBA", (12, 19), (44, 56, 66, 233)).save(img)
    mask = img.with_name("tower_m.png")
    Image.new("RGBA", (12, 19), (14, 14, 14, 255)).save(mask)
    atlas = root / "Override" / "Sprites" / "atlas.json"
    atlas.write_text(json.dumps({
        "frames": {
            "tower": {"frame": {"x": 0, "y": 0, "w": 12, "h": 19}},
            "bad": {"frame": {"x": 2, "y": 4, "w": 0, "h": 9}}
        }
    }), encoding="utf8")
    xaml = root / "Patches" / "Assets" / "GUI" / "XAML" / "Patch.xaml"
    xaml.write_text('<Patches><Patch XPath="//TextBlock" /></Patches>', encoding="utf8")
    return root, img, mask, xaml


def test_shared_project_inspector_uses_original_bytes_and_scans_frames_masks_and_xpath(tmp_path):
    root, img, mask, xaml = build_assets(tmp_path)
    before = {p: p.read_bytes() for p in (img, mask, xaml)}
    proof = inspect_assets(root)
    assert proof["summary"]["count"] == 4
    assert proof["source_modified"] is False and proof["game_modified"] is False
    assert proof["noesis_runtime_verified"] is False
    rows = {r["path"]: r for r in proof["assets"]}
    sprite = rows["Override/Sprites/tower.png"]
    assert sprite["inspection"]["width"] == 12
    assert sprite["inspection"]["height"] == 19
    assert sprite["sha256"] == hashlib.sha256(img.read_bytes()).hexdigest()
    assert rows["Override/Sprites/tower_m.png"]["status"] == "ok"
    atlas = rows["Override/Sprites/atlas.json"]
    assert atlas["inspection"]["kind"] == "atlas_metadata"
    assert atlas["inspection"]["frames"] == 2 and atlas["status"] == "warning"
    patch = rows["Patches/Assets/GUI/XAML/Patch.xaml"]
    assert patch["inspection"]["xpath_attributes_first_30"] == ["//TextBlock"]
    assert patch["inspection"]["noesis_bindings_verified"] is False
    assert all(p.read_bytes() == contents for p, contents in before.items())


def test_mask_mismatch_and_missing_base_report_warnings(tmp_path):
    root, img, mask, _ = build_assets(tmp_path)
    Image.new("RGBA", (7, 3), (0, 0, 0, 255)).save(mask)
    assert next(r for r in inspect_assets(root)["assets"] if r["path"].endswith("_m.png"))["status"] == "warning"
    img.unlink()
    assert "fehlt" in next(r for r in inspect_assets(root)["assets"] if r["path"].endswith("_m.png"))["inspection"]["mask_warning"]


def test_xaml_entity_and_malformed_xml_are_invalid_but_do_not_parse_external_reference(tmp_path):
    root, _, _, xaml = build_assets(tmp_path)
    xaml.write_text('<!DOCTYPE a [<!ENTITY evil SYSTEM "file:///C:/Users/private.txt">]><a>&evil;</a>', encoding="utf8")
    row = next(r for r in inspect_assets(root)["assets"] if r["path"].endswith(".xaml"))
    assert row["status"] == "invalid" and "DOCTYPE/ENTITY" in row["inspection"]["error"]
    xaml.write_text('<invalid>', encoding="utf8")
    row = next(r for r in inspect_assets(root)["assets"] if r["path"].endswith(".xaml"))
    assert row["status"] == "invalid"


def test_legacy_pivot_schema_reuses_existing_python_validator(tmp_path):
    root = tmp_path / "legacy"
    root.mkdir()
    file = root / "zinnen.json"
    file.write_text(json.dumps({
        "schema":"zinnenlineal.versatz.v1",
        "frames":[{"name":"anim_castle 002", "gruppe":"anim_castle", "nummer":2,
                  "rechts":0,"hoch":18,"breite":333,"hoehe":165,
                  "pivot_x":0.0,"pivot_y":1.10909091,
                  "neu_pivot_x":0.0,"neu_pivot_y":1.0}]
    }), encoding="utf8")
    record = inspect_assets(root)["assets"][0]
    assert record["inspection"]["kind"] == "legacy_pivot_measurement"
    assert record["inspection"]["records"] == 1
    old = json.loads(file.read_text(encoding="utf8"))
    old["frames"][0]["neu_pivot_y"] = .3
    file.write_text(json.dumps(old), encoding="utf8")
    assert inspect_assets(root)["assets"][0]["status"] == "invalid"


@pytest.mark.parametrize("fourcc,expected", [(b"DXT1","BC1"),(b"DXT5","BC3"),(b"DX10","BC7")])
def test_dds_bc_header_recognition_with_no_transcoding(tmp_path, fourcc, expected):
    f = tmp_path / "tex.dds"
    data = bytearray(148 if fourcc == b"DX10" else 128)
    data[:4] = b"DDS "
    struct.pack_into("<I",data,4,124)
    struct.pack_into("<II",data,12,45,64)
    data[84:88] = fourcc
    if fourcc == b"DX10": struct.pack_into("<I",data,128,98)
    f.write_bytes(data)
    out = _dds_info(f)
    assert out["compression"] == expected
    assert out["header_only"] is True
    assert out["decoded_pixels_verified"] is False


def test_linked_content_rejected_when_permissions_allow(tmp_path):
    root, _, _, _ = build_assets(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "private.png").write_bytes(b"not a png")
    link = root / "evil"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError,NotImplementedError):
        pytest.skip("Symlinks not allowed")
    with pytest.raises(AssetInspectionError):
        inspect_assets(root)


def test_script_data_never_runs_and_no_game_is_modified(tmp_path):
    root = tmp_path / "assets"
    root.mkdir()
    script = root / "init.lua"
    script.write_text("error('DONT EXECUTE'); os.execute('bad')",encoding="utf8")
    proof = inspect_assets(root)
    assert proof["summary"]["count"] == 1
    assert proof["assets"][0]["inspection"]["not_executed"] is True
    assert proof["game_compatibility_verified"] is False

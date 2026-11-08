"""Source-only shared Asset Inspector regression: no game or private materials."""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import struct
import sys

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tools")]

from stronghold_europe_de.asset_inspector import (
    AssetInspectionError, inspect_asset, inspect_image_mask,
)
import hud_menu_workspace as hud
import suite_unified_project as unified


def _png(width=12, height=8, *, hidden=False, alpha=255) -> bytes:
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    image.putpixel((2, 3), (100, 130, 160, alpha))
    if hidden:
        image.putpixel((0, 0), (5, 25, 45, 0))
    target = BytesIO()
    image.save(target, "PNG")
    return target.getvalue()


def _dds(dx10=True, width=8, height=8) -> bytes:
    header = bytearray(148 if dx10 else 128)
    header[:4] = b"DDS "
    struct.pack_into("<I", header, 4, 124)
    struct.pack_into("<II", header, 12, height, width)
    struct.pack_into("<I", header, 76, 32)
    header[84:88] = b"DX10" if dx10 else b"DXT1"
    if dx10:
        struct.pack_into("<I", header, 128, 98)
    count = ((width + 3) // 4) * ((height + 3) // 4) * (
        16 if dx10 else 8
    )
    return bytes(header) + bytes(count)


def test_png_inspection_tracks_alpha_hidden_rgb_and_source_identity(tmp_path):
    source = tmp_path / "sprite.png"
    payload = _png(hidden=True, alpha=128)
    source.write_bytes(payload)
    result = inspect_asset(source)
    assert result["sha256"] == sha256(payload).hexdigest()
    assert result["details"]["format"] == "PNG"
    assert result["details"]["visible_pixels"] == 1
    assert result["details"]["partial_alpha_pixels"] == 1
    assert result["details"]["hidden_rgb_pixels"] == 1
    assert {"HIDDEN_RGB_ALPHA", "PARTIAL_ALPHA"} <= {
        item["code"] for item in result["checks"]
    }
    assert not result["native_game_compatibility"]
    assert source.read_bytes() == payload


def test_mask_dimensions_are_independently_checked(tmp_path):
    first, second = tmp_path / "color.png", tmp_path / "color_m.png"
    first.write_bytes(_png(12, 8))
    second.write_bytes(_png(13, 8))
    report = inspect_image_mask(first, second)
    assert report["status"] == "BLOCK"
    assert not report["dimensions_match"]
    second.write_bytes(_png(12, 8))
    report = inspect_image_mask(first, second)
    assert report["status"] == "REVIEW"
    assert report["dimensions_match"]
    assert not report["material_semantics_verified"]


def test_dds_bc7_vs_bc1_headers_and_truncated_blocks_fail_closed(tmp_path):
    path = tmp_path / "atlas.dds"
    bc7 = _dds()
    path.write_bytes(bc7)
    out = inspect_asset(path)["details"]
    assert out["compression"] == "BC7"
    assert out["base_level_bytes"] == 64
    assert not out["complete_mip_chain_verified"]
    path.write_bytes(_dds(dx10=False))
    out = inspect_asset(path)["details"]
    assert out["compression"] == "BC1"
    assert out["base_level_bytes"] == 32
    path.write_bytes(bc7[:-5])
    with pytest.raises(AssetInspectionError, match="abgeschnitten"):
        inspect_asset(path)


def test_atlas_json_duplicates_and_bom_rejected(tmp_path):
    path = tmp_path / "atlas.json"
    path.write_bytes(b'{"frames": {"one": {}}, "meta": {"format": "RGBA"}}')
    out = inspect_asset(path)["details"]
    assert out["format"] == "Atlas-JSON"
    assert out["sprite_names"] == ["one"]
    assert not out["atlas_schema_verified"]
    path.write_bytes(b'{"x":1,"x":2}')
    with pytest.raises(AssetInspectionError, match="Doppelter"):
        inspect_asset(path)
    path.write_bytes(b'\xef\xbb\xbf{}')
    with pytest.raises(AssetInspectionError, match="BOM"):
        inspect_asset(path)


def test_bad_image_and_linked_assets_rejected(tmp_path):
    path = tmp_path / "broken.png"
    path.write_bytes(b"not a PNG")
    with pytest.raises(AssetInspectionError):
        inspect_asset(path)
    import os
    link = tmp_path / "link.png"
    try:
        os.symlink(path, link)
    except (OSError, NotImplementedError):
        return
    with pytest.raises(AssetInspectionError, match="verknüpft"):
        inspect_asset(link)


@pytest.fixture
def isolated_project(tmp_path, monkeypatch):
    work = tmp_path / "suite" / "work"
    work.mkdir(parents=True)
    monkeypatch.setattr(hud, "WORK", work)
    monkeypatch.setattr(hud, "ROOT", work.parent)
    monkeypatch.setattr(hud, "DEFAULT", work / "hud-menu-werkstatt")
    return unified.ProjectPipeline(unified.new_project("shared-assets"))


def test_unified_project_reuses_exact_same_inspector_without_game_writes(
    isolated_project, tmp_path
):
    project = isolated_project
    original = tmp_path / "Button.png"
    data = _png(hidden=True)
    original.write_bytes(data)
    imported = project.import_image(original)
    relative = imported.relative_to(project.project).as_posix()
    report = project.inspect_asset(relative)
    assert report["sha256"] == sha256(data).hexdigest()
    assert report["details"]["hidden_rgb_pixels"] == 1
    audit = project.audit()
    assert any(entry["path"] == relative for entry in audit["asset_inspections"])
    assert audit["native_game_runtime_verified"] is False
    assert original.read_bytes() == data
    with pytest.raises(unified.UnifiedFlowError, match="genau ein"):
        project.inspect_asset("../../other.png")


def test_unified_project_rejects_corrupted_work_png_before_any_package(
    isolated_project, tmp_path
):
    project = isolated_project
    original = tmp_path / "Image.png"
    original.write_bytes(_png())
    imported = project.import_image(original)
    imported.write_bytes(b"corrupted")
    with pytest.raises(unified.UnifiedFlowError, match="Inspektion blockiert"):
        project.audit()
    assert original.read_bytes() == _png()


def test_unified_project_detects_mismatched_material_mask_before_export(
    isolated_project, tmp_path
):
    project = isolated_project
    first, second = tmp_path / "Flag.png", tmp_path / "Flag_m.png"
    first.write_bytes(_png(12, 8))
    second.write_bytes(_png(13, 8))
    project.import_image(first)
    project.import_image(second)
    with pytest.raises(unified.UnifiedFlowError, match="unterschiedliche Größe"):
        project.audit()

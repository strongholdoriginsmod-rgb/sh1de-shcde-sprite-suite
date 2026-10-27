"""Read-only importer regression tests (including optional installed-game QA)."""
from __future__ import annotations

import struct
from pathlib import Path

import pytest

from stronghold_europe_de.sandbox.map_importer import (
    MapFormatError, PREVIEW_LENGTH, inspect_map, preview_rgb,
    find_maps, load_radar_preview,
)

MAPS = Path("E:/SSGameQA/Stronghold Crusader Definitive Edition_Data/StreamingAssets/Maps")


def test_invalid_header_id(tmp_path):
    bad = tmp_path / "bad.map"
    bad.write_bytes(struct.pack("<4i", 2, 12, PREVIEW_LENGTH, 1) + b"\x00" * 32)
    with pytest.raises(MapFormatError, match="Unsupported"):
        inspect_map(bad)


def test_truncated_radar(tmp_path):
    bad = tmp_path / "cut.map"
    bad.write_bytes(struct.pack("<4i", -2, 100, PREVIEW_LENGTH, 88) + b"\x00" * 24)
    with pytest.raises(MapFormatError, match="beyond file"):
        inspect_map(bad)


def test_bad_preview_size():
    with pytest.raises(MapFormatError):
        preview_rgb(b"\x00" * 32)


def test_rgb555_palette():
    palette = bytearray(512)
    struct.pack_into("<H", palette, 2, 0x001F)
    data = bytes(palette) + bytes([0, 1] + [0] * 39998)
    rgb = preview_rgb(data)
    assert len(rgb) == 120000
    assert rgb[:3] == b"\x00\x00\x00"
    assert rgb[3:6] == bytes((0,0,255))


@pytest.mark.skipif(not MAPS.is_dir(), reason="Original game maps not installed")
def test_real_map_headers():
    maps = find_maps(MAPS)
    assert len(maps) >= 3
    antioch = next(m for m in maps if m.name == "Antioch")
    assert antioch.world_size == 300
    assert antioch.max_players == 3
    assert antioch.editable
    assert any(x >= 0 for x, _ in antioch.keeps)


@pytest.mark.skipif(not MAPS.is_dir(), reason="Original game maps not installed")
@pytest.mark.parametrize("name", ["Antioch.map", "Ancient River.map", "Crusader Demo.map"])
def test_real_radar_pixels(name):
    header, img = load_radar_preview(MAPS / name)
    assert header.name == Path(name).stem
    assert img.size == (200, 200)
    assert len(img.getcolors(40000)) > 10

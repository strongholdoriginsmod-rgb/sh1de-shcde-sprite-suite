"""Validated SHCDE section directories and checksum-protected read-only extraction."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import struct

import pytest

from stronghold_europe_de.sandbox.map_importer import MapFormatError
from stronghold_europe_de.sandbox.map_sections import (
    DIRECTORY_BYTES, DIRECTORY_SLOTS, NATIVE_TILES, NATIVE_DIAMOND,
    discover_sections, load_section, tile_index, tile_row_length,
    render_native_tile_values,
)

MAPS = Path("E:/SSGameQA/Stronghold Crusader Definitive Edition_Data/StreamingAssets/Maps")


def _small_map(path):
    sections = [0] * DIRECTORY_SLOTS
    header = bytearray(DIRECTORY_BYTES)
    struct.pack_into("<III", header, 0, DIRECTORY_BYTES, 3, 1)
    struct.pack_into("<I", header, 32, 3)  # uncompressed length
    struct.pack_into("<I", header, 32 + DIRECTORY_SLOTS * 4, 3)  # stored length
    struct.pack_into("<I", header, 32 + DIRECTORY_SLOTS * 8, 3005)
    path.write_bytes(header + b"abc")


def test_raw_section_roundtrip(tmp_path):
    path = tmp_path / "small.map"
    _small_map(path)
    directory = discover_sections(path)
    assert directory.section_ids == (3005,)
    assert load_section(directory, 3005) == b"abc"
    with pytest.raises(KeyError):
        load_section(directory, 3003)


def test_directory_rejects_bad_section_length(tmp_path):
    path = tmp_path / "bad.map"
    _small_map(path)
    b = bytearray(path.read_bytes())
    struct.pack_into("<I", b, 32 + DIRECTORY_SLOTS * 4, 5)
    path.write_bytes(b)
    with pytest.raises(MapFormatError):
        discover_sections(path)


@pytest.mark.parametrize("name", ["Antioch.map", "Crusader Demo.map", "A Mighty Oasis.map"])
@pytest.mark.skipif(not MAPS.is_dir(), reason="Installed SHCDE maps unavailable")
def test_actual_sections_verified(name):
    directory = discover_sections(MAPS / name)
    assert len(directory.sections) > 100
    assert {3003, 3004, 3005}.issubset(directory.section_ids)
    assert directory.get(3005).unpacked_size == 320800
    heights = load_section(directory, 3005)
    assert len(heights) == 320800
    assert 8 in heights
    assert len(set(heights)) > 1
    picture = render_native_tile_values(heights, false_color=True)
    assert picture.size == (800, 800)
    assert tile_index(399, 0) == 0
    assert tile_index(400, 0) == 1
    assert tile_index(399, 799) == NATIVE_TILES - 2
    assert tile_index(400, 799) == NATIVE_TILES - 1


@pytest.mark.skipif(not (MAPS / "Antioch.map").is_file(), reason="Real map unavailable")
def test_packed_section_corruption_rejected(tmp_path):
    source = MAPS / "Antioch.map"
    folder = discover_sections(source)
    fake = tmp_path / "damaged.map"
    payload = bytearray(source.read_bytes())
    entry = folder.get(3005)
    corrupt_at = folder.data_offset + entry.offset + 13
    payload[corrupt_at] ^= 0x8F
    fake.write_bytes(payload)
    damaged = discover_sections(fake)
    with pytest.raises(MapFormatError):
        load_section(damaged, 3005)

def test_native_tile_layout_is_bijective():
    from stronghold_europe_de.sandbox.map_sections import tile_row_length
    offsets = []
    for row in range(800):
        width = tile_row_length(row)
        left = (800 - width) // 2
        offsets.extend(tile_index(x, row) for x in range(left, left + width))
    assert len(offsets) == NATIVE_TILES
    assert offsets == list(range(NATIVE_TILES))
    with pytest.raises(IndexError):
        tile_index(0, 0)
    with pytest.raises(IndexError):
        tile_index(800, 400)


@pytest.mark.skipif(not (MAPS / "Antioch.map").is_file(), reason="Real map unavailable")
def test_native_raw_multichannel_inspection():
    from stronghold_europe_de.sandbox.map_sections import (
        load_native_tile_channels, NATIVE_SECTION_WIDTHS,
    )
    layer = load_native_tile_channels(MAPS / "Antioch.map")
    assert set(NATIVE_SECTION_WIDTHS).issubset(layer.channels)
    for k, width in NATIVE_SECTION_WIDTHS.items():
        assert len(layer.channels[k]) == NATIVE_TILES * width
    first = layer.at(399, 0)
    assert first[3005] == 8
    assert first[3003] > 0
    assert layer.at(400, 799)[3005] == layer.channels[3005][-1]

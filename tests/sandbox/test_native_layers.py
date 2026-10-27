"""Read-only 3003 playable mask and 3004 object-footprint evidence."""
from pathlib import Path
import struct

import pytest

from stronghold_europe_de.sandbox.native_layers import (
    native_geometry, render_native_masked_overview, VOID_3003
)
from stronghold_europe_de.sandbox.map_importer import MapFormatError
from stronghold_europe_de.sandbox.map_sections import (
    load_native_tile_channels, NATIVE_TILES, tile_index,
)

MAPS = Path("E:/SSGameQA/Stronghold Crusader Definitive Edition_Data/StreamingAssets/Maps")


@pytest.mark.skipif(not MAPS.is_dir(), reason="Installed game maps unavailable")
@pytest.mark.parametrize("name, padding, occupied", [
    ("Antioch.map", 276679, 2503),
    ("Crusader Demo.map", 276652, 2407),
    ("A Mighty Oasis.map", 241992, 1541),
])
def test_original_playable_mask_and_occupancy(name, padding, occupied):
    path = MAPS / name
    before = (path.stat().st_mtime_ns, path.stat().st_size)
    channels = load_native_tile_channels(path).channels
    geom = native_geometry(channels)
    assert geom.padding_tiles == padding
    assert geom.nonpadding_tiles == NATIVE_TILES - padding
    assert geom.occupied_tiles == occupied
    assert geom.is_padding_index(tile_index(399, 0))
    assert not geom.is_padding_index(tile_index(400, 400))
    assert geom.occupancy_id(tile_index(400, 400)) == int.from_bytes(
        channels[3004][2*tile_index(400, 400):2*tile_index(400, 400)+2], "little"
    )
    assert geom.min_x < 400 < geom.max_x
    assert geom.min_y < 400 < geom.max_y
    assert geom.max_x - geom.min_x < 450
    assert geom.max_y - geom.min_y < 450
    assert sum(fp.cells for fp in geom.footprints) == occupied
    assert len(geom.footprints) > 1000
    assert (path.stat().st_mtime_ns, path.stat().st_size) == before


@pytest.mark.skipif(not MAPS.is_dir(), reason="Installed game maps unavailable")
@pytest.mark.parametrize("name, width", [
    ("Antioch.map", 4),
    ("Crusader Demo.map", 2),
])
def test_raw_object_4310_has_verified_rectangular_footprint(name, width):
    geom = native_geometry(load_native_tile_channels(MAPS / name).channels)
    record = next(fp for fp in geom.footprints if fp.raw_id == 4310)
    assert record.rectangular
    assert record.max_x-record.min_x+1 == width
    assert record.max_y-record.min_y+1 == width
    assert record.cells == width * width
    # 4310 is a native occupancy ID, NOT a sprite atlas frame index.


def test_masked_overview_really_omits_padding():
    # Build a synthetic but fully native-sized diamond in memory.
    flags = bytearray(struct.pack("<I", VOID_3003) * NATIVE_TILES)
    occupancy = bytearray(NATIVE_TILES * 2)
    center = tile_index(400, 400)
    struct.pack_into("<I", flags, center * 4, 32768)
    struct.pack_into("<H", occupancy, center * 2, 4310)
    layers = native_geometry({3003: bytes(flags), 3004: bytes(occupancy)})
    assert layers.padding_tiles == NATIVE_TILES - 1
    assert layers.occupied_tiles == 1
    assert layers.bounds == (400, 400, 400, 400)
    assert layers.is_padding_index(tile_index(399, 0))
    assert not layers.is_padding_index(center)
    assert layers.occupancy_id(center) == 4310
    pix = render_native_masked_overview(bytes([8]) * NATIVE_TILES, layers)
    assert pix.size == (800, 800)
    assert pix.getpixel((399, 0)) == (13, 21, 22, 255)
    assert pix.getpixel((400, 400)) != (13, 21, 22, 255)


def test_occupied_padding_is_rejected_and_missing_flags_preserved():
    flags = bytes(struct.pack("<I", VOID_3003) * NATIVE_TILES)
    occupied = bytearray(NATIVE_TILES * 2)
    struct.pack_into("<H", occupied, 0, 13)
    with pytest.raises(MapFormatError):
        native_geometry({3003: flags, 3004: bytes(occupied)})
    plain = native_geometry({3005: bytes([8]) * NATIVE_TILES})
    assert plain.padding_tiles == 0
    assert plain.nonpadding_tiles == NATIVE_TILES
    assert plain.occupied_tiles == 0
    assert plain.bounds == (0, 0, 799, 799)


def test_real_surface_overview_uses_3037_and_height_separately():
    flags=bytearray(struct.pack("<I",VOID_3003)*NATIVE_TILES)
    height=bytearray([8]*NATIVE_TILES)
    surface=bytearray([0]*NATIVE_TILES)
    positions=[(400,400),(401,400),(402,400),(403,400)]
    for x,y in positions:
        struct.pack_into("<I",flags,4*tile_index(x,y),0x8000)
    # Same height but different actual ground textures.
    surface[tile_index(400,400)]=16
    surface[tile_index(401,400)]=2
    # Same ground texture but different height.
    surface[tile_index(402,400)]=2
    height[tile_index(402,400)]=128
    # True water candidate overrides dry sand-colour but does not alter bytes.
    surface[tile_index(403,400)]=2
    struct.pack_into("<I",flags,4*tile_index(403,400),0x100000)
    from stronghold_europe_de.sandbox.native_layers import (
        SURFACE_PREVIEW_RGB, WATER_PREVIEW_RGB
    )
    geom=native_geometry({3003:bytes(flags)})
    preview=render_native_masked_overview(bytes(height),geom,bytes(surface))
    assert preview.getpixel((400,400))[:3]==SURFACE_PREVIEW_RGB[16]
    assert preview.getpixel((401,400))[:3]==SURFACE_PREVIEW_RGB[2]
    assert preview.getpixel((402,400))[0]>preview.getpixel((401,400))[0]
    assert preview.getpixel((403,400))[:3]==WATER_PREVIEW_RGB
    assert preview.getpixel((399,0))==(13,21,22,255)
    with pytest.raises(MapFormatError,match="3037"):
        render_native_masked_overview(bytes(height),geom,b"invalid")

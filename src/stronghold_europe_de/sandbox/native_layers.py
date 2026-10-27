"""Verified native SHCDE layer geometry, independent of graphical guesses.

Section 3003 values 16 and 32 mark the non-playable backdrop and outer fringes in three inspected
original maps. Section 3004 contains occupancy IDs, frequently repeated in
rectangular 2x2/3x3/4x4 footprints. Their *game meanings* remain unknown.
This module reports only directly evidenced native byte properties.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import struct

from .map_sections import NATIVE_DIAMOND, NATIVE_TILES, NATIVE_SECTION_WIDTHS
from .map_importer import MapFormatError

VOID_3003 = 16
VOID_3003_FLAGS = frozenset({16, 32})


@dataclass(frozen=True)
class NativeFootprint:
    raw_id: int
    min_x: int
    min_y: int
    max_x: int
    max_y: int
    cells: int

    @property
    def rectangular(self):
        return self.cells == (self.max_x-self.min_x+1) * (self.max_y-self.min_y+1)


@dataclass(frozen=True)
class NativeLayerGeometry:
    flags: bytes | None
    occupancy: bytes | None
    width: int
    min_x: int
    min_y: int
    max_x: int
    max_y: int
    u_min: float
    u_max: float
    v_min: float
    v_max: float
    padding_tiles: int
    nonpadding_tiles: int
    occupied_tiles: int
    footprints: tuple[NativeFootprint, ...]

    @property
    def bounds(self):
        return (self.min_x, self.min_y, self.max_x, self.max_y)

    def original_flags_at(self, index: int) -> int:
        """Exact bitfield 3003, without guessing the other bit meanings."""
        if not 0 <= index < NATIVE_TILES:
            raise IndexError(index)
        return (struct.unpack_from("<I", self.flags, index * 4)[0]
                if self.flags is not None else 0)

    def is_padding_index(self, index: int) -> bool:
        return self.flags is not None and self.original_flags_at(index) in VOID_3003_FLAGS

    def occupancy_id(self, index: int) -> int:
        if not 0 <= index < NATIVE_TILES:
            raise IndexError(index)
        if self.occupancy is None:
            return 0
        return struct.unpack_from("<H", self.occupancy, index * 2)[0]


def native_geometry(channels: dict[int, bytes]) -> NativeLayerGeometry:
    """Collect native bounds and section-3004 footprints once per opened map.

    The native diamond includes 320,800 sample positions. Do NOT confuse
    sample positions with 320,800 playable world tiles.
    """
    flags = channels.get(3003)
    occupancy = channels.get(3004)
    for key, payload in ((3003, flags), (3004, occupancy)):
        if payload is not None and len(payload) != NATIVE_TILES * NATIVE_SECTION_WIDTHS[key]:
            raise MapFormatError(f"Sektion {key} hat unerwartete native Länge: {len(payload)}")
    min_x = NATIVE_DIAMOND
    min_y = NATIVE_DIAMOND
    max_x = -1
    max_y = -1
    u_min = v_min = float("inf")
    u_max = v_max = float("-inf")
    padding = 0
    occupied = 0
    coords = defaultdict(list)
    index = 0
    for y in range(NATIVE_DIAMOND):
        row_length = 2 * (y + 1 if y < 400 else NATIVE_DIAMOND - y)
        first_x = (NATIVE_DIAMOND - row_length) // 2
        for dx in range(row_length):
            x = first_x + dx
            border = flags is not None and struct.unpack_from("<I", flags, index * 4)[0] in VOID_3003_FLAGS
            raw_id = struct.unpack_from("<H", occupancy, index * 2)[0] if occupancy is not None else 0
            if border:
                padding += 1
                if raw_id:
                    raise MapFormatError(
                        f"Originalbelegung 3004={raw_id} liegt in 3003-Randfeld ({x},{y})"
                    )
            else:
                min_x, min_y = min(min_x, x), min(min_y, y)
                max_x, max_y = max(max_x, x), max(max_y, y)
                # The native diamond is a 45° transform of the logical
                # world. Map coordinates are bounded in *both* these axes.
                u, v = (x + y - 399) / 2, (y - x + 399) / 2
                u_min, u_max = min(u_min, u), max(u_max, u)
                v_min, v_max = min(v_min, v), max(v_max, v)
            if raw_id:
                occupied += 1
                coords[raw_id].append((x, y))
            index += 1
    assert index == NATIVE_TILES
    nonpadding = NATIVE_TILES - padding
    if nonpadding == 0:
        raise MapFormatError("Originalkarte enthält keine nicht-randmarkierten Kacheln")
    footprints = []
    for raw_id, points in coords.items():
        footprints.append(NativeFootprint(
            raw_id,
            min(point[0] for point in points),
            min(point[1] for point in points),
            max(point[0] for point in points),
            max(point[1] for point in points),
            len(points),
        ))
    footprints.sort(key=lambda obj: obj.raw_id)
    return NativeLayerGeometry(
        flags, occupancy, NATIVE_DIAMOND,
        min_x, min_y, max_x, max_y,
        u_min, u_max, v_min, v_max,
        padding, nonpadding, occupied, tuple(footprints)
    )


# Values are diagnostic RGB estimates from the three installed game radar
# previews. They are NOT a reconstructed Unity terrain shader or exact atlas.
SURFACE_PREVIEW_RGB = {
    0: (172, 149, 107),   # sand/earth from radar samples
    1: (153, 138, 80),    # vegetation-earth mix
    2: (169, 145, 108),  # dry earth/sand
    8: (185, 156, 106),  # high rocky terrain
    16: (109, 108, 44),  # dark ground/grass
    64: (174, 143, 94),  # cliff/rock terrain
    128: (138, 124, 63), # light olive/vegetated terrain
}
WATER_PREVIEW_RGB = (66, 114, 122)
PADDING_PREVIEW_RGB = (13, 21, 22, 255)


def render_native_masked_overview(
    height_values: bytes, geom: NativeLayerGeometry,
    surface_values: bytes | None = None,
):
    """Display the original playable diamond using separate original fields.

    3037 chooses a diagnostic ground texture colour, 3005 modulates apparent
    relief gently, 3003 is an independently verified *water indicator* and
    padding mask. None is a guaranteed game shader/texture-frame identity.

    When channel 3037 is not available, preserve the older 3005-only preview
    for fixtures/maps that have not been reverse engineered.
    """
    from PIL import Image
    from .map_sections import render_native_tile_values
    if len(height_values) != NATIVE_TILES:
        raise MapFormatError("Originalkanal 3005 ist unvollständig")
    if surface_values is not None and len(surface_values) != NATIVE_TILES:
        raise MapFormatError("Originalkanal 3037 ist unvollständig")

    if surface_values is None:
        rgb = render_native_tile_values(height_values).convert("RGBA")
        if geom.flags is None:
            return rgb
        canvas = bytearray(rgb.tobytes())
    else:
        canvas = bytearray(PADDING_PREVIEW_RGB * (NATIVE_DIAMOND ** 2))

    index = 0
    for y in range(NATIVE_DIAMOND):
        row_length = 2 * (y + 1 if y < 400 else NATIVE_DIAMOND - y)
        x0 = (NATIVE_DIAMOND-row_length)//2
        for dx in range(row_length):
            offset = 4*(y*NATIVE_DIAMOND + x0 + dx)
            if geom.is_padding_index(index):
                canvas[offset:offset+4] = bytes(PADDING_PREVIEW_RGB)
            elif surface_values is not None:
                flags = geom.original_flags_at(index)
                if flags & 0x100000:
                    r,g,b = WATER_PREVIEW_RGB
                else:
                    r,g,b = SURFACE_PREVIEW_RGB.get(
                        surface_values[index], SURFACE_PREVIEW_RGB[0]
                    )
                    # 3005 is the *height* field (classic SHC 1005). Keep
                    # shading subtle, because one byte does not encode the
                    # complete original terrain slope/transition shader.
                    delta = max(-12, min(28, (height_values[index]-8)//4))
                    r,g,b = (max(0,min(255,c+delta)) for c in (r,g,b))
                canvas[offset:offset+4] = bytes((r,g,b,255))
            index += 1
    return Image.frombytes("RGBA",(NATIVE_DIAMOND,NATIVE_DIAMOND),bytes(canvas))

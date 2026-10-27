"""Strict read-only section directory reader for some SHC:DE .map formats.

Section IDs and byte layouts are *raw game data*. The meaning and coordinate
mapping of most sections remain under investigation. Neither imported
sections nor original game maps are ever mutated by this module.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import struct
import zlib

from .map_importer import MapFormatError, decompress_dcl

# Observed in modern SHCDE maps with magic 0xFFFFFFFE.
DIRECTORY_SLOTS = 150
DIRECTORY_BYTES = 36 + DIRECTORY_SLOTS * 20
MAX_DIRECTORY_SEARCH = 256 * 1024
MAX_UNPACKED_SECTION = 64 * 1024 * 1024
MAX_SECTION_AREA = 128 * 1024 * 1024
U32S = "<" + str(DIRECTORY_SLOTS) + "I"


@dataclass(frozen=True)
class SectionInfo:
    id: int
    offset: int           # Relative to data_offset.
    packed_size: int      # Includes the 12-byte size/checksum header if compressed.
    unpacked_size: int
    compressed: bool


@dataclass(frozen=True)
class SectionDirectory:
    path: Path
    table_offset: int
    data_offset: int
    section_bytes: int
    sections: tuple[SectionInfo, ...]

    def get(self, key: int) -> SectionInfo:
        for section in self.sections:
            if section.id == key:
                return section
        raise KeyError(f"No section {key} in {self.path.name}")

    @property
    def section_ids(self) -> tuple[int, ...]:
        return tuple(s.id for s in self.sections)


def _parse_directory(data: bytes, pos: int, source: Path) -> SectionDirectory | None:
    if pos + DIRECTORY_BYTES > len(data):
        return None
    directory_bytes, section_bytes, count = struct.unpack_from("<III", data, pos)
    if directory_bytes != DIRECTORY_BYTES or not (1 <= count <= DIRECTORY_SLOTS):
        return None
    if not 0 < section_bytes <= MAX_SECTION_AREA:
        return None
    start = pos + DIRECTORY_BYTES
    if start + section_bytes != len(data):
        # Modern validated map sections are the last part of the file.
        return None
    base = pos + 32
    lengths = struct.unpack_from(U32S, data, base)
    stored = struct.unpack_from(U32S, data, base + DIRECTORY_SLOTS * 4)
    keys = struct.unpack_from(U32S, data, base + DIRECTORY_SLOTS * 8)
    flags = struct.unpack_from(U32S, data, base + DIRECTORY_SLOTS * 12)
    offsets = struct.unpack_from(U32S, data, base + DIRECTORY_SLOTS * 16)
    sections = []
    seen = set()
    expected_offset = 0
    for i in range(count):
        sid = keys[i]
        size = stored[i]
        original = lengths[i]
        if (not 1000 <= sid <= 9999 or sid in seen or size == 0
                or not 0 < original <= MAX_UNPACKED_SECTION
                or flags[i] not in (0, 1) or offsets[i] != expected_offset
                or expected_offset + size > section_bytes):
            return None
        if flags[i]:
            if size < 15:
                return None
            unpacked, packed, _checksum = struct.unpack_from("<III", data, start + expected_offset)
            if unpacked != original or packed != size - 12:
                return None
        elif size != original:
            return None
        seen.add(sid)
        sections.append(SectionInfo(sid, expected_offset, size, original, bool(flags[i])))
        expected_offset += size
    if expected_offset != section_bytes:
        return None
    return SectionDirectory(source, pos, start, section_bytes, tuple(sections))


def discover_sections(path: str | Path) -> SectionDirectory:
    """Read a validated section directory, or reject maps of unknown layout.

    Some official SHCDE maps use a different layout; never fabricate a
    directory for those variants.
    """
    source = Path(path)
    raw = source.read_bytes()
    signature = struct.pack("<I", DIRECTORY_BYTES)
    limit = min(MAX_DIRECTORY_SEARCH, len(raw) - DIRECTORY_BYTES)
    search_end = min(len(raw), MAX_DIRECTORY_SEARCH + len(signature))
    pos = raw.find(signature, 0, search_end)
    while pos >= 0 and pos <= limit:
        found = _parse_directory(raw, pos, source)
        if found is not None:
            return found
        pos = raw.find(signature, pos + 1, search_end)
    raise MapFormatError(
        f"Verifiziertes SHCDE-Sektionsverzeichnis in {source.name} nicht gefunden"
    )


def load_section(directory: SectionDirectory, section_id: int) -> bytes:
    """Return one validated, CRC-checked unpacked section, without writing."""
    desc = directory.get(section_id)
    with directory.path.open("rb") as stream:
        stream.seek(directory.data_offset + desc.offset)
        block = stream.read(desc.packed_size)
    if len(block) != desc.packed_size:
        raise MapFormatError(f"Abschnitt {section_id}: Datei abgeschnitten")
    if not desc.compressed:
        return block
    length, packed, checksum = struct.unpack_from("<III", block)
    if length != desc.unpacked_size or packed != desc.packed_size - 12:
        raise MapFormatError(f"Abschnitt {section_id}: Größenfelder widersprüchlich")
    raw = decompress_dcl(block[12:], length)
    if zlib.crc32(raw) & 0xFFFFFFFF != checksum:
        raise MapFormatError(f"Abschnitt {section_id}: CRC32-Prüfung fehlgeschlagen")
    return raw


# Section 3005 contains exactly 320,800 one-byte tile values. The visually
# verified native projection is a diamond of 800 rows with padded row lengths
# 2, 4, ..., 800, 800, ..., 4, 2 (not two 400x401 byte channels).
NATIVE_DIAMOND = 800
NATIVE_TILES = 320800


def tile_row_length(row: int) -> int:
    if not 0 <= row < NATIVE_DIAMOND:
        raise IndexError(f"Ungültige Kachelzeile: {row}")
    return 2 * (row + 1 if row < 400 else NATIVE_DIAMOND - row)


def tile_index(x: int, y: int) -> int:
    """Map a projected diamond pixel to the exact serialized tile index.

    Raises IndexError for padding, out-of-bounds or non-integer coordinates.
    The diamond layout is confirmed by three actual maps and their radar image.
    """
    # bool is a subclass of int in Python, but JSON true/false can never
    # designate an authentic native tile coordinate. Reject it here at the
    # common map-index boundary, not only in individual overlay editors.
    if type(x) is not int or type(y) is not int:
        raise TypeError("Kachelkoordinaten müssen Ganzzahlen sein")
    width = tile_row_length(y)
    left = (NATIVE_DIAMOND - width) // 2
    if not left <= x < left + width:
        raise IndexError("Kachel liegt außerhalb des originalen Diamantrasters")
    if y < 400:
        first = y * (y + 1)
    else:
        k = y - 400
        first = 160400 + 800 * k - k * (k - 1)
    return first + x - left


def render_native_tile_values(data: bytes, false_color: bool = True):
    """Render native diamond tiles using their real section-3005 byte values.

    This is the original *data shape* with a diagnostic palette, NOT the
    original in-game textured terrain. Colour-to-material interpretation is
    provisional and must not be used as a guaranteed water/height mapping.
    """
    from PIL import Image
    if len(data) != NATIVE_TILES:
        raise MapFormatError(
            f"Sektion 3005: {len(data)} statt {NATIVE_TILES} native Kachelwerte"
        )
    if false_color:
        colors = []
        for value in range(256):
            if value == 8:
                colors.append(bytes((65, 102, 74)))
            elif value == 0:
                colors.append(bytes((33, 58, 106)))
            elif value < 8:
                colors.append(bytes((40, 80 + value * 6, 115 + value * 5)))
            elif value >= 128:
                colors.append(bytes((175, 130 + (value - 128) // 5, 76)))
            else:
                colors.append(bytes((105 + min(value, 70), 113, 68)))
        canvas = bytearray(bytes((13, 21, 22)) * (NATIVE_DIAMOND ** 2))
    else:
        canvas = bytearray(NATIVE_DIAMOND ** 2)
    first = 0
    for y in range(NATIVE_DIAMOND):
        width = tile_row_length(y)
        left = (NATIVE_DIAMOND - width) // 2
        row_values = data[first:first + width]
        offset = y * NATIVE_DIAMOND + left
        if false_color:
            pixels = b"".join(colors[value] for value in row_values)
            canvas[3 * offset:3 * (offset + width)] = pixels
        else:
            canvas[offset:offset + width] = row_values
        first += width
    assert first == NATIVE_TILES
    return Image.frombytes(
        "RGB" if false_color else "L",
        (NATIVE_DIAMOND, NATIVE_DIAMOND),
        bytes(canvas),
    )


def load_native_tile_values(path: str | Path) -> bytes:
    """Load verified byte-per-native-tile channel 3005 from an original map."""
    return load_section(discover_sections(path), 3005)

# Byte widths are verified against the decoded lengths of 3003/3004/3005,
# 3037 and 3043 in all three supported original maps.
NATIVE_SECTION_WIDTHS = {3003: 4, 3004: 2, 3005: 1, 3037: 1, 3043: 1}


@dataclass(frozen=True)
class NativeTileChannels:
    path: Path
    channels: dict[int, bytes]

    def at(self, x: int, y: int) -> dict[int, int]:
        number = tile_index(x, y)
        return {
            key: int.from_bytes(data[number * size:(number + 1) * size], "little")
            for key, data in self.channels.items()
            for size in (NATIVE_SECTION_WIDTHS[key],)
        }


def load_native_tile_channels(path: str | Path) -> NativeTileChannels:
    directory = discover_sections(path)
    buffers = {}
    for section_id, width in NATIVE_SECTION_WIDTHS.items():
        if section_id not in directory.section_ids:
            continue
        desc = directory.get(section_id)
        if desc.unpacked_size != width * NATIVE_TILES:
            raise MapFormatError(
                f"Sektion {section_id}: {desc.unpacked_size} Bytes statt "
                f"{width * NATIVE_TILES} für das native Diamantgitter"
            )
        buffers[section_id] = load_section(directory, section_id)
    if 3005 not in buffers:
        raise MapFormatError("Benötigte native Tile-Sektion 3005 fehlt")
    return NativeTileChannels(Path(path), buffers)


@dataclass(frozen=True)
class NativeOriginalBuilding:
    """Verified position and identity of a real, read-only map building."""
    record_number: int
    type_id: int
    owner: int
    uid: int
    x: int
    y: int
    native_tile_number: int
    footprint: int


def load_original_buildings(path: str | Path) -> list[NativeOriginalBuilding]:
    """Decode section 1013's 812-byte building records.

    Position fields (offsets 238/240/244) were verified on Antioch,
    Crusader Demo and A Mighty Oasis against the native diamond index.
    Type-ID to visual building sprite is *not* inferred.
    """
    directory = discover_sections(path)
    if 1013 not in directory.section_ids:
        return []
    data = load_section(directory, 1013)
    record_size = 812
    if len(data) != 2000 * record_size:
        raise MapFormatError(f"Nicht unterstützte native Gebäude-Länge: {len(data)}")
    output = []
    for rec_no in range(2000):
        off = rec_no * record_size
        rec = data[off:off + record_size]
        if not any(rec):
            continue
        group_type = struct.unpack_from("<H", rec, 210)[0]
        owner = struct.unpack_from("<H", rec, 214)[0]
        uid = struct.unpack_from("<H", rec, 216)[0]
        x = struct.unpack_from("<H", rec, 238)[0]
        y = struct.unpack_from("<H", rec, 240)[0]
        native = struct.unpack_from("<I", rec, 244)[0]
        footprint = struct.unpack_from("<H", rec, 248)[0]
        try:
            calculated = tile_index(x, y)
        except (IndexError, TypeError):
            continue
        if native != calculated:
            continue
        output.append(NativeOriginalBuilding(
            rec_no, group_type, owner, uid, x, y, native, footprint
        ))
    return output

@dataclass(frozen=True)
class NativeOriginalTree:
    """Tree record from 1014; native X/Y are verified, sprite type unclassified."""
    record_number: int
    raw_variant: int
    raw_group: int
    raw_state: int
    x: int
    y: int


def load_original_trees(path: str | Path) -> list[NativeOriginalTree]:
    """Read genuine vegetation coordinates from 4000 x 156-byte SHCDE records.

    Offsets 98 and 100 contain native diamond X/Y; all 3431 nonempty tree
    records across Antioch, Crusader Demo and A Mighty Oasis pass bounds.
    Offsets 0/4/8 are preserved without asserting a sprite animation mapping.
    """
    directory = discover_sections(path)
    if 1014 not in directory.section_ids:
        return []
    records = load_section(directory, 1014)
    size = 156
    if len(records) != 4000 * size:
        raise MapFormatError(
            f"Unbekanntes Format für Baumsektion 1014: {len(records)} Bytes"
        )
    found = []
    for rec_no in range(4000):
        record = records[rec_no * size:(rec_no + 1) * size]
        if not any(record):
            continue
        x, y = struct.unpack_from("<HH", record, 98)
        try:
            tile_index(x, y)
        except (IndexError, TypeError):
            # Leave unknown format variants unrepresented rather than creating
            # bogus vegetation coordinates.
            continue
        a, b, state = struct.unpack_from("<III", record, 0)
        found.append(NativeOriginalTree(rec_no, a, b, state, x, y))
    return found

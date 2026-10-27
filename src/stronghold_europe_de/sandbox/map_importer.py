"""Read-only SHCDE map header and authentic radar-preview importer.

The preview is the map's own 200x200 radar raster, NOT a reconstruction of
terrain tiles. This module never writes to the original map file.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import struct
import subprocess

PREVIEW_SIZE = 200
PREVIEW_LENGTH = 512 + PREVIEW_SIZE * PREVIEW_SIZE
MAX_RADAR_BLOCK = 512_000
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DECODER = PROJECT_ROOT / "tools" / "vendor" / "decode_implode.js"


class MapFormatError(ValueError):
    """File is not a supported or valid SHCDE map."""


class MapDecoderUnavailable(RuntimeError):
    """PKWare decoder or Node.js runtime is unavailable."""


def _int32(data: bytes, at: int) -> int:
    if at < 0 or at + 4 > len(data):
        raise MapFormatError(f"Map header truncated at byte {at}")
    return struct.unpack_from("<i", data, at)[0]


@dataclass(frozen=True)
class MapHeader:
    path: Path
    header_id: int
    radar_block_size: int
    radar_packed_size: int
    map_type: int | None = None
    max_players: int | None = None
    world_size: int | None = None
    mission_lock_type: int | None = None
    keeps: tuple[tuple[int, int], ...] = ()

    @property
    def name(self) -> str:
        return self.path.stem

    @property
    def editable(self) -> bool:
        return self.mission_lock_type == 0


def _parse_extra_header(data: bytes, offset: int) -> dict:
    """Parse known optional metadata; do not interpret unknown payload."""
    out = {}
    try:
        n = offset
        sz = _int32(data, n)
        if sz <= 0 or sz > 100_000:
            return out
        n += 4 + sz

        sz = _int32(data, n)
        if sz <= 0:
            return out
        n += 12  # length and first eight bytes

        sz = _int32(data, n)
        if sz <= 0:
            return out
        n += 4
        raw_type = _int32(data, n)
        out["map_type"] = 1 if raw_type < 0 else raw_type
        n += 24  # map type, five keep references
        out["max_players"] = _int32(data, n)
        n += 4

        sz = _int32(data, n)
        n += 4
        if sz <= 0:
            return out
        n += 4  # mission type
        if sz <= 4:
            return out
        n += 4  # siege / invasion
        if sz <= 8:
            return out
        out["mission_lock_type"] = _int32(data, n)
        n += 4

        if _int32(data, 0) == -1:
            n += sz - 16 + 4
        elif sz > 12:
            extra = _int32(data, n)
            n += 4
            if extra > 0:
                if extra > 100_000:
                    return out
                n += extra
            n += 10  # mode and three achievement shorts

        sz = _int32(data, n)
        n += 4
        if sz <= 0:
            return out
        king = _int32(data, n)
        if king > 0:
            out["max_players"] -= 1
        n += 4
        if sz <= 4:
            return out
        n += 4  # skirmish map marker
        if sz <= 8:
            return out
        n += 8  # autosave and balance
        if sz <= 16:
            return out

        keeps = []
        for _ in range(8):
            keeps.append((_int32(data, n), _int32(data, n + 4)))
            n += 8
        out["keeps"] = tuple(keeps)
        if sz > 80:
            size = _int32(data, n)
            if 0 < size <= 4096:
                out["world_size"] = size
    except MapFormatError:
        # Metadata is optional; a corrupt truncated required radar is not.
        pass
    return out


def inspect_map(path: str | Path) -> MapHeader:
    path = Path(path)
    with path.open("rb") as handle:
        header = handle.read(256 * 1024)
    if len(header) < 32:
        raise MapFormatError("Map file too short")
    version = _int32(header, 0)
    if version >= 0:
        raise MapFormatError(f"Unsupported map header ID: {version}")
    size = _int32(header, 4)
    unpacked = _int32(header, 8)
    packed = _int32(header, 12)
    if not 12 <= size <= MAX_RADAR_BLOCK:
        raise MapFormatError(f"Invalid radar block size: {size}")
    if unpacked != PREVIEW_LENGTH:
        raise MapFormatError(f"Unsupported radar raster size: {unpacked}")
    if packed <= 0 or packed > size - 12:
        raise MapFormatError(f"Invalid radar compressed size: {packed}")
    if 8 + size > path.stat().st_size:
        raise MapFormatError("Radar block extends beyond file")
    if len(header) < 20 + packed:
        raise MapFormatError("Insufficient data for radar image")
    kw = _parse_extra_header(header, 8 + size)
    return MapHeader(path, version, size, packed, **kw)


def _node_executable() -> str:
    path = shutil.which("node")
    if path:
        return path
    default = Path("C:/Program Files/nodejs/node.exe")
    if default.is_file():
        return str(default)
    raise MapDecoderUnavailable("Node.js is required for PKWare radar decompression")


def decompress_dcl(packed: bytes, expected_length: int) -> bytes:
    """Decode bounded PKWare DCL bytes, rejecting truncated/mismatched output."""
    if not isinstance(expected_length, int) or not 0 < expected_length <= 64 * 1024 * 1024:
        raise MapFormatError("Unzulässige Größe eines entpackten Datenabschnitts")
    if not DECODER.is_file():
        raise MapDecoderUnavailable(f"MIT-licensed decoder is missing: {DECODER}")
    try:
        result = subprocess.run([_node_executable(), str(DECODER)], input=packed,
                                capture_output=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MapDecoderUnavailable(str(exc)) from exc
    if result.returncode:
        raise MapFormatError(result.stderr.decode("utf-8", errors="replace")[:500])
    if len(result.stdout) != expected_length:
        raise MapFormatError(
            f"DCL decoded into {len(result.stdout)} instead of {expected_length} bytes"
        )
    return result.stdout


def decompress_radar(packed: bytes) -> bytes:
    return decompress_dcl(packed, PREVIEW_LENGTH)


def preview_rgb(data: bytes) -> bytes:
    """Convert 256 RGB555 entries and indexed pixels into a true-colour image."""
    if len(data) != PREVIEW_LENGTH:
        raise MapFormatError(f"Invalid preview byte count: {len(data)}")
    colors = []
    for i in range(0, 512, 2):
        rgb = struct.unpack_from("<H", data, i)[0]
        colors.append(bytes((round(((rgb >> 10) & 31) * 255 / 31),
                             round(((rgb >> 5) & 31) * 255 / 31),
                             round((rgb & 31) * 255 / 31))))
    return b"".join(colors[index] for index in data[512:])


def load_radar_preview(path: str | Path):
    """Return (MapHeader, PIL RGB image). Does not claim full terrain parity."""
    from PIL import Image
    info = inspect_map(path)
    with info.path.open("rb") as handle:
        handle.seek(20)
        packed = handle.read(info.radar_packed_size)
    image = Image.frombytes("RGB", (PREVIEW_SIZE, PREVIEW_SIZE),
                            preview_rgb(decompress_radar(packed)))
    return info, image


def find_maps(game_root: str | Path) -> list[MapHeader]:
    root = Path(game_root)
    map_dir = root / "Stronghold Crusader Definitive Edition_Data" / "StreamingAssets" / "Maps"
    # Game directory or a directly selected folder with original .map files.
    if root.name.lower() == "maps" or (
            root.is_dir() and any(root.glob("*.map"))):
        map_dir = root
    if not map_dir.is_dir():
        return []
    result = []
    for path in sorted(map_dir.glob("*.map"), key=lambda p: p.name.casefold()):
        try:
            result.append(inspect_map(path))
        except (OSError, MapFormatError):
            pass
    return result

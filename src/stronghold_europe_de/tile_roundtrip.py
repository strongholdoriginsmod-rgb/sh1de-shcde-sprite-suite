"""Lossless editor round-trip for objects made from isometric tile sprites.

Stronghold does not draw a keep, gatehouse or workshop as one bitmap.  The
native simulation assigns one sprite to every occupied map tile.  A useful art
view therefore has to assemble those sprites, while a safe delivery path has
to preserve the individual layers.  Flattening and cutting a composite back
into rectangles is not reversible: tall neighbouring sprites overlap.

This module uses OpenRaster (``.ora``) as the editable object document.  Every
game tile is one named layer at its measured screen position.  The splitter
accepts exactly those layers, maps them back to their original rectangles and
rejects visible pixels outside a tile's delivery canvas.  An untouched package
therefore round-trips pixel-for-pixel; edited packages still produce the exact
frame names and canvases expected by ``tools/sprites.py import``.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any, Iterable
import xml.etree.ElementTree as ET
import zipfile

from PIL import Image


SCHEMA_VERSION = 2
ORA_MIMETYPE = b"image/openraster"
CURRENT_PREVIEW_NAME = "object-current-preview.png"
TILE_WIDTH = 64
TILE_HALF_WIDTH = 32
TILE_HALF_HEIGHT = 16
TILE_PIVOT_Y = 16.5
_GEOMETRY_TOLERANCE = 0.01
_SAFE_NAME = re.compile(r"^[^<>:\"/\\|?*\x00-\x1f]+$")
_TRAILING_NUMBER = re.compile(r"(\d+)\s*$")

LAYOUTS = (
    # Die Teilfolge der Original-GM1 (diagonal von vorne nach hinten), aus
    # allen tile_*.gm1 von Crusader HD abgeleitet und widerspruchsfrei fuer
    # 4..169 Teile - config/kachelobjekt-raster.json. Am 29.09.2026 im
    # Vorschau-Sandkasten gegengeprueft: nur diese Folge setzt Huetten und den
    # Bergfriedsockel stimmig zusammen; "row-major" zerfaellt in Streifen.
    "gm1",
    "row-major",
    "row-major-flip-x",
    "row-major-flip-y",
    "row-major-rotate-180",
    "column-major",
    "column-major-flip-x",
    "column-major-flip-y",
    "column-major-rotate-180",
)


class TileRoundtripError(RuntimeError):
    """The object package cannot be proven safe to split or deliver."""


@dataclass(frozen=True)
class LayerSpec:
    name: str
    file: str
    number: int
    tile_x: int
    tile_y: int
    x: int
    y: int
    width: int
    height: int
    order: int
    baseline_pixels_sha256: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "file": self.file,
            "number": self.number,
            "tile_x": self.tile_x,
            "tile_y": self.tile_y,
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "order": self.order,
            "baseline_pixels_sha256": self.baseline_pixels_sha256,
        }


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _pixel_digest(image: Image.Image) -> str:
    rgba = image if image.mode == "RGBA" else image.convert("RGBA")
    return _sha256(rgba.tobytes())


def _frame_number(name: str) -> int:
    match = _TRAILING_NUMBER.search(name)
    if match is None:
        raise TileRoundtripError(f"Frame has no trailing number: {name}")
    return int(match.group(1))


def _safe_flat_name(value: str, label: str) -> str:
    if not value or not _SAFE_NAME.fullmatch(value) or value in {".", ".."}:
        raise TileRoundtripError(f"Unsafe {label}: {value!r}")
    return value


def _read_json_object(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise TileRoundtripError(f"{label} is not readable: {path} ({exc})") from exc
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise TileRoundtripError(f"{label} is not UTF-8 JSON: {path} ({exc})") from exc
    if not isinstance(value, dict):
        raise TileRoundtripError(f"{label} is not a JSON object: {path}")
    return value, payload


def _integral(value: float, label: str) -> int:
    rounded = round(value)
    if not math.isclose(value, rounded, abs_tol=_GEOMETRY_TOLERANCE):
        raise TileRoundtripError(f"{label} is not integral: {value}")
    return int(rounded)


def _layout_coordinate(
    position: int, columns: int, rows: int, layout: str
) -> tuple[int, int]:
    if layout not in LAYOUTS:
        raise TileRoundtripError(f"Unknown tile layout: {layout}")
    if layout == "gm1":
        table_path = Path(__file__).resolve().parents[2] / "config" / "kachelobjekt-raster.json"
        try:
            table = json.loads(table_path.read_text(encoding="utf-8")).get(str(columns * rows))
        except (OSError, ValueError):
            table = None
        if not table or columns != rows:
            raise TileRoundtripError(
                f"GM1-Raster fuer {columns}x{rows} unbekannt ({table_path.name})"
            )
        x, y = table[position]
        return int(x), int(y)
    column_major = layout.startswith("column-major")
    if column_major:
        x, y = divmod(position, rows)
    else:
        y, x = divmod(position, columns)
    if layout.endswith("flip-x") or layout.endswith("rotate-180"):
        x = columns - 1 - x
    if layout.endswith("flip-y") or layout.endswith("rotate-180"):
        y = rows - 1 - y
    return x, y


def _validate_export_frame(
    directory: Path, frame: dict[str, Any]
) -> tuple[str, Path, Image.Image, dict[str, Any]]:
    name = str(frame.get("name", ""))
    _safe_flat_name(name, "frame name")
    filename = str(frame.get("file", ""))
    _safe_flat_name(filename, "frame filename")
    path = directory / filename
    if path.parent != directory or not path.is_file():
        raise TileRoundtripError(f"Frame file is missing: {path}")
    target = frame.get("crusader")
    if not isinstance(target, dict):
        raise TileRoundtripError(f"{name}: Crusader target geometry is missing")
    width = _integral(float(target.get("width", 0)), f"{name} target width")
    height = _integral(float(target.get("height", 0)), f"{name} target height")
    pivot_x = float(target.get("pivot_x", 0)) * width
    pivot_y = float(target.get("pivot_y", 0)) * height
    if width != TILE_WIDTH:
        raise TileRoundtripError(
            f"{name}: target width {width}, but the tile-object route requires "
            f"the measured {TILE_WIDTH}px building-tile canvas"
        )
    if not math.isclose(pivot_x, TILE_HALF_WIDTH, abs_tol=_GEOMETRY_TOLERANCE):
        raise TileRoundtripError(
            f"{name}: target pivot x is {pivot_x:.4f}px instead of "
            f"{TILE_HALF_WIDTH}px"
        )
    if not math.isclose(pivot_y, TILE_PIVOT_Y, abs_tol=_GEOMETRY_TOLERANCE):
        raise TileRoundtripError(
            f"{name}: target pivot y is {pivot_y:.4f}px instead of "
            f"{TILE_PIVOT_Y}px"
        )
    try:
        with Image.open(path) as opened:
            image = opened.convert("RGBA")
    except Exception as exc:
        raise TileRoundtripError(f"{name}: PNG is not readable ({exc})") from exc
    if image.size != (width, height):
        raise TileRoundtripError(
            f"{name}: working PNG is {image.width}x{image.height}, target slot is "
            f"{width}x{height}. Export the group with --game crusader before "
            "building an editable tile object."
        )
    return name, path, image, target


def _prepare_directory(destination: Path, replace: bool) -> Path:
    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if not destination.is_dir():
            raise TileRoundtripError(f"Output is not a directory: {destination}")
        if any(destination.iterdir()) and not replace:
            raise TileRoundtripError(
                f"Output directory is not empty: {destination}. Use --replace only "
                "after preserving any edited ORA file."
            )
    staging = Path(
        tempfile.mkdtemp(prefix=f".{destination.name}.tile-roundtrip-", dir=destination.parent)
    )
    return staging


def _commit_directory(staging: Path, destination: Path, replace: bool) -> None:
    destination = destination.resolve()
    backup: Path | None = None
    try:
        if destination.exists():
            if not replace and any(destination.iterdir()):
                raise TileRoundtripError(f"Output directory changed during write: {destination}")
            backup = destination.with_name(destination.name + ".tile-roundtrip-backup")
            if backup.exists():
                raise TileRoundtripError(
                    f"Stale tile-roundtrip backup blocks replacement: {backup}"
                )
            os.replace(destination, backup)
        os.replace(staging, destination)
        if backup is not None:
            shutil.rmtree(backup)
    except Exception:
        if destination.exists() and backup is not None and backup.exists():
            shutil.rmtree(destination)
        if backup is not None and backup.exists() and not destination.exists():
            os.replace(backup, destination)
        raise


def _render_preview(layers: Iterable[tuple[LayerSpec, Image.Image]], size: tuple[int, int]) -> Image.Image:
    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    for spec, image in sorted(layers, key=lambda item: item[0].order):
        canvas.alpha_composite(image, (spec.x, spec.y))
    return canvas


def _png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=False, compress_level=9)
    return buffer.getvalue()


def _write_ora(
    path: Path,
    *,
    object_name: str,
    size: tuple[int, int],
    layers: list[tuple[LayerSpec, Image.Image]],
    merged: Image.Image,
) -> None:
    width, height = size
    image_root = ET.Element(
        "image",
        {
            "version": "0.0.1",
            "w": str(width),
            "h": str(height),
            "name": object_name,
        },
    )
    stack = ET.SubElement(image_root, "stack", {"name": object_name})
    # OpenRaster lists the top layer first.  `order` is back-to-front, so the
    # XML order is reversed.  The splitter does not infer delivery order from
    # XML; it uses the pinned manifest.
    for storage_index, (spec, _image) in enumerate(
        sorted(layers, key=lambda item: item[0].order, reverse=True)
    ):
        ET.SubElement(
            stack,
            "layer",
            {
                "name": spec.name,
                "src": f"data/layer-{storage_index:04d}.png",
                "x": str(spec.x),
                "y": str(spec.y),
                "opacity": "1.0",
                "visibility": "visible",
                "composite-op": "svg:src-over",
            },
        )
    xml_payload = ET.tostring(image_root, encoding="utf-8", xml_declaration=True)
    thumbnail = merged.copy()
    thumbnail.thumbnail((256, 256), Image.Resampling.LANCZOS)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            zipfile.ZipInfo("mimetype"), ORA_MIMETYPE, compress_type=zipfile.ZIP_STORED
        )
        archive.writestr("stack.xml", xml_payload, compress_type=zipfile.ZIP_DEFLATED)
        archive.writestr(
            "mergedimage.png", _png_bytes(merged), compress_type=zipfile.ZIP_DEFLATED
        )
        archive.writestr(
            "Thumbnails/thumbnail.png",
            _png_bytes(thumbnail),
            compress_type=zipfile.ZIP_DEFLATED,
        )
        ordered = sorted(layers, key=lambda item: item[0].order, reverse=True)
        for storage_index, (_spec, image) in enumerate(ordered):
            archive.writestr(
                f"data/layer-{storage_index:04d}.png",
                _png_bytes(image),
                compress_type=zipfile.ZIP_DEFLATED,
            )


def compose_object(
    export_directory: Path,
    output_directory: Path,
    *,
    start: int,
    end: int,
    columns: int,
    rows: int,
    layout: str = "row-major",
    object_name: str | None = None,
    replace: bool = False,
    semantic_contract: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Create a layered ORA package from a consecutive rectangular tile block."""

    export_directory = export_directory.resolve()
    index, index_payload = _read_json_object(export_directory / "index.json", "export index")
    group = _safe_flat_name(str(index.get("group", "")), "group")
    if columns <= 0 or rows <= 0:
        raise TileRoundtripError("rows and columns must both be positive")
    if start < 0 or end < start:
        raise TileRoundtripError(f"invalid frame range: {start}..{end}")
    expected_count = columns * rows
    if end - start + 1 != expected_count:
        raise TileRoundtripError(
            f"range {start}..{end} has {end - start + 1} frames, but "
            f"{columns}x{rows} requires {expected_count}"
        )
    frames = index.get("frames")
    if not isinstance(frames, list) or any(not isinstance(frame, dict) for frame in frames):
        raise TileRoundtripError("export index frames must be a list of objects")
    numbered: dict[int, dict[str, Any]] = {}
    for frame in frames:
        number = _frame_number(str(frame.get("name", "")))
        if number in numbered:
            raise TileRoundtripError(f"duplicate numeric frame index: {number}")
        numbered[number] = frame
    wanted_numbers = list(range(start, end + 1))
    missing = [number for number in wanted_numbers if number not in numbered]
    if missing:
        raise TileRoundtripError(f"export is missing selected frames: {missing[:12]}")

    raw_layers: list[dict[str, Any]] = []
    fractional_x: set[float] = set()
    fractional_y: set[float] = set()
    for position, number in enumerate(wanted_numbers):
        name, path, image, target = _validate_export_frame(
            export_directory, numbered[number]
        )
        tile_x, tile_y = _layout_coordinate(position, columns, rows, layout)
        anchor_x = (tile_x - tile_y) * TILE_HALF_WIDTH
        anchor_y = (tile_x + tile_y) * TILE_HALF_HEIGHT
        # `_validate_export_frame` has already proved both authored pivots are
        # within 0.01 px of the measured tile anchor.  Unity serialises that
        # same 16.5 px value with frame-dependent float noise (observed up to
        # about 0.00004 px in tile_castle 1193..1313).  Normalise only after
        # that proof; retaining the noise would invent many fractional grids
        # even though no pixel is resampled and every frame uses one anchor.
        pivot_x = TILE_HALF_WIDTH
        pivot_y = TILE_PIVOT_Y
        left = anchor_x - pivot_x
        top = anchor_y - (image.height - pivot_y)
        fractional_x.add(round(left - math.floor(left), 6))
        fractional_y.add(round(top - math.floor(top), 6))
        raw_layers.append(
            {
                "name": name,
                "file": path.name,
                "number": number,
                "tile_x": tile_x,
                "tile_y": tile_y,
                "left": left,
                "top": top,
                "image": image,
                "baseline": _pixel_digest(image),
            }
        )
    # A common half-pixel residue is harmless: normalising by the minimum
    # makes every layer offset integral.  Different residues would require
    # resampling and are therefore rejected.
    if len(fractional_x) != 1 or len(fractional_y) != 1:
        raise TileRoundtripError(
            "selected tiles do not share one pixel grid; composition would require resampling"
        )
    min_left = min(float(layer["left"]) for layer in raw_layers)
    min_top = min(float(layer["top"]) for layer in raw_layers)
    specs_and_images: list[tuple[LayerSpec, Image.Image]] = []
    for layer in raw_layers:
        image = layer["image"]
        x = _integral(float(layer["left"]) - min_left, f"{layer['name']} x offset")
        y = _integral(float(layer["top"]) - min_top, f"{layer['name']} y offset")
        # Tilemap rows are drawn back-to-front by their projected row.  The
        # second key makes ties deterministic and mirrors increasing x.
        order = int(layer["tile_x"]) + int(layer["tile_y"])
        order = order * max(columns, rows) + int(layer["tile_x"])
        spec = LayerSpec(
            name=str(layer["name"]),
            file=str(layer["file"]),
            number=int(layer["number"]),
            tile_x=int(layer["tile_x"]),
            tile_y=int(layer["tile_y"]),
            x=x,
            y=y,
            width=image.width,
            height=image.height,
            order=order,
            baseline_pixels_sha256=str(layer["baseline"]),
        )
        specs_and_images.append((spec, image))
    canvas_width = max(spec.x + spec.width for spec, _image in specs_and_images)
    canvas_height = max(spec.y + spec.height for spec, _image in specs_and_images)
    size = (canvas_width, canvas_height)
    merged = _render_preview(specs_and_images, size)

    name = object_name or f"{group}-{start}-{end}"
    _safe_flat_name(name, "object name")
    output_directory = output_directory.resolve()
    staging = _prepare_directory(output_directory, replace)
    try:
        source_index_name = "source-index.json"
        (staging / source_index_name).write_bytes(index_payload)
        preview_name = "object-preview.png"
        merged.save(staging / preview_name, format="PNG", optimize=False, compress_level=9)
        ora_name = f"{name}.ora"
        _write_ora(
            staging / ora_name,
            object_name=name,
            size=size,
            layers=specs_and_images,
            merged=merged,
        )
        semantic = (
            {
                "status": "verified-preset",
                "preset_id": str(semantic_contract["preset_id"]),
                "contract_sha256": str(semantic_contract["contract_sha256"]),
            }
            if semantic_contract is not None
            else {
                "status": "custom-unconfirmed",
                "preset_id": None,
                "contract_sha256": None,
            }
        )
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "kind": "stronghold_europe_tile_object",
            "name": name,
            "group": group,
            "frame_range": {"from": start, "to": end},
            "grid": {
                "columns": columns,
                "rows": rows,
                "layout": layout,
                "tile_width": TILE_WIDTH,
                "tile_half_width": TILE_HALF_WIDTH,
                "tile_half_height": TILE_HALF_HEIGHT,
                "pivot_y_px": TILE_PIVOT_Y,
            },
            "canvas": {"width": canvas_width, "height": canvas_height},
            "source_index": source_index_name,
            "source_index_sha256": _sha256(index_payload),
            "semantic": semantic,
            "ora": ora_name,
            "preview": preview_name,
            "layers": [
                spec.as_dict() for spec, _image in sorted(specs_and_images, key=lambda i: i[0].number)
            ],
        }
        (staging / "object.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        _commit_directory(staging, output_directory, replace)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return manifest


def _manifest_layers(manifest: dict[str, Any]) -> list[LayerSpec]:
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise TileRoundtripError(
            f"unsupported object schema: {manifest.get('schema_version')!r}"
        )
    if manifest.get("kind") != "stronghold_europe_tile_object":
        raise TileRoundtripError(f"not a tile-object package: {manifest.get('kind')!r}")
    semantic = manifest.get("semantic")
    if not isinstance(semantic, dict) or set(semantic) != {
        "status", "preset_id", "contract_sha256"
    }:
        raise TileRoundtripError("object manifest semantic contract is missing")
    if semantic.get("status") not in {"verified-preset", "custom-unconfirmed"}:
        raise TileRoundtripError("object manifest semantic status is unknown")
    if semantic["status"] == "verified-preset":
        if (
            not isinstance(semantic.get("preset_id"), str)
            or not semantic["preset_id"]
            or not isinstance(semantic.get("contract_sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", semantic["contract_sha256"])
        ):
            raise TileRoundtripError("verified preset contract is incomplete")
    elif semantic.get("preset_id") is not None or semantic.get("contract_sha256") is not None:
        raise TileRoundtripError("custom semantic contract carries forged preset fields")
    raw = manifest.get("layers")
    if not isinstance(raw, list) or not raw or any(not isinstance(item, dict) for item in raw):
        raise TileRoundtripError("object manifest layers must be a non-empty list")
    layers: list[LayerSpec] = []
    for item in raw:
        try:
            spec = LayerSpec(
                name=_safe_flat_name(str(item["name"]), "layer name"),
                file=_safe_flat_name(str(item["file"]), "frame filename"),
                number=int(item["number"]),
                tile_x=int(item["tile_x"]),
                tile_y=int(item["tile_y"]),
                x=int(item["x"]),
                y=int(item["y"]),
                width=int(item["width"]),
                height=int(item["height"]),
                order=int(item["order"]),
                baseline_pixels_sha256=str(item["baseline_pixels_sha256"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise TileRoundtripError(f"invalid layer manifest entry: {item!r}") from exc
        if spec.width <= 0 or spec.height <= 0 or spec.x < 0 or spec.y < 0:
            raise TileRoundtripError(f"invalid layer geometry for {spec.name}")
        layers.append(spec)
    names = [layer.name for layer in layers]
    files = [layer.file.casefold() for layer in layers]
    if len(set(names)) != len(names) or len(set(files)) != len(files):
        raise TileRoundtripError("object manifest contains duplicate layer names or files")
    frame_range = manifest.get("frame_range")
    if not isinstance(frame_range, dict):
        raise TileRoundtripError("object manifest frame range is missing")
    try:
        start = int(frame_range["from"])
        end = int(frame_range["to"])
    except (KeyError, TypeError, ValueError) as exc:
        raise TileRoundtripError("object manifest frame range is invalid") from exc
    numbers = sorted(layer.number for layer in layers)
    if numbers != list(range(start, end + 1)):
        raise TileRoundtripError(
            "object layers are not the consecutive frame range recorded in the manifest"
        )
    grid = manifest.get("grid")
    if not isinstance(grid, dict):
        raise TileRoundtripError("object manifest grid is missing")
    try:
        columns = int(grid["columns"])
        rows = int(grid["rows"])
        layout = str(grid["layout"])
    except (KeyError, TypeError, ValueError) as exc:
        raise TileRoundtripError("object manifest grid is invalid") from exc
    if columns <= 0 or rows <= 0 or columns * rows != len(layers):
        raise TileRoundtripError("object grid no longer matches its layer count")
    if layout not in LAYOUTS:
        raise TileRoundtripError(f"object manifest uses an unknown layout: {layout}")
    for position, layer in enumerate(sorted(layers, key=lambda item: item.number)):
        expected_tile = _layout_coordinate(position, columns, rows, layout)
        if (layer.tile_x, layer.tile_y) != expected_tile:
            raise TileRoundtripError(
                f"{layer.name}: tile coordinate no longer matches the pinned layout"
            )
    return layers


def _read_ora_layers(
    ora_path: Path, expected_size: tuple[int, int]
) -> dict[str, tuple[Image.Image, int, int]]:
    try:
        archive = zipfile.ZipFile(ora_path, "r")
    except (OSError, zipfile.BadZipFile) as exc:
        raise TileRoundtripError(f"ORA is not readable: {ora_path} ({exc})") from exc
    with archive:
        names = set(archive.namelist())
        if "mimetype" not in names or archive.read("mimetype") != ORA_MIMETYPE:
            raise TileRoundtripError("ORA has no valid unmodified mimetype entry")
        try:
            root = ET.fromstring(archive.read("stack.xml"))
        except (KeyError, ET.ParseError) as exc:
            raise TileRoundtripError(f"ORA stack.xml is invalid ({exc})") from exc
        try:
            actual_size = (int(root.attrib["w"]), int(root.attrib["h"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise TileRoundtripError("ORA canvas size is missing or invalid") from exc
        if actual_size != expected_size:
            raise TileRoundtripError(
                f"ORA canvas is {actual_size[0]}x{actual_size[1]} instead of "
                f"{expected_size[0]}x{expected_size[1]}"
            )
        result: dict[str, tuple[Image.Image, int, int]] = {}
        sources: set[str] = set()
        for element in root.iter("layer"):
            name = str(element.attrib.get("name", ""))
            if name in result:
                raise TileRoundtripError(f"ORA contains duplicate layer: {name}")
            if element.attrib.get("visibility", "visible") != "visible":
                raise TileRoundtripError(f"tile layer is hidden: {name}")
            if element.attrib.get("composite-op", "svg:src-over") != "svg:src-over":
                raise TileRoundtripError(f"unsupported composite mode on layer: {name}")
            try:
                opacity = float(element.attrib.get("opacity", "1"))
                x = int(element.attrib.get("x", "0"))
                y = int(element.attrib.get("y", "0"))
                source = str(element.attrib["src"])
            except (KeyError, TypeError, ValueError) as exc:
                raise TileRoundtripError(f"invalid ORA layer attributes: {name}") from exc
            if not math.isclose(opacity, 1.0, abs_tol=1e-9):
                raise TileRoundtripError(f"tile layer opacity is not 100%: {name}")
            if source.startswith(("/", "\\")) or ".." in Path(source).parts:
                raise TileRoundtripError(f"unsafe ORA layer source: {source}")
            if source in sources:
                raise TileRoundtripError(f"ORA reuses one image for multiple layers: {source}")
            sources.add(source)
            try:
                payload = archive.read(source)
                with Image.open(io.BytesIO(payload)) as opened:
                    image = opened.convert("RGBA")
            except Exception as exc:
                raise TileRoundtripError(f"ORA layer image is not readable: {name} ({exc})") from exc
            result[name] = (image, x, y)
        return result


def inspect_object(package_directory: Path) -> dict[str, Any]:
    """Validate an ORA package and return split images plus a public summary."""

    package_directory = package_directory.resolve()
    manifest, _manifest_payload = _read_json_object(
        package_directory / "object.json", "object manifest"
    )
    layers = _manifest_layers(manifest)
    canvas = manifest.get("canvas")
    if not isinstance(canvas, dict):
        raise TileRoundtripError("object manifest canvas is missing")
    try:
        size = (int(canvas["width"]), int(canvas["height"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise TileRoundtripError("object manifest canvas is invalid") from exc
    if size[0] <= 0 or size[1] <= 0:
        raise TileRoundtripError("object canvas must be positive")
    source_index_name = _safe_flat_name(str(manifest.get("source_index", "")), "source index")
    source_index_path = package_directory / source_index_name
    source_index, source_index_payload = _read_json_object(source_index_path, "source index")
    if _sha256(source_index_payload) != manifest.get("source_index_sha256"):
        raise TileRoundtripError("source-index.json changed after the object package was created")
    group = _safe_flat_name(str(manifest.get("group", "")), "group")
    if source_index.get("group") != group:
        raise TileRoundtripError("source index group no longer matches the object manifest")
    source_frames = source_index.get("frames")
    if not isinstance(source_frames, list) or any(
        not isinstance(item, dict) for item in source_frames
    ):
        raise TileRoundtripError("source index frames must be a list of objects")
    indexed: dict[str, dict[str, Any]] = {}
    for item in source_frames:
        indexed_name = str(item.get("name", ""))
        if indexed_name in indexed:
            raise TileRoundtripError(f"duplicate frame in source index: {indexed_name}")
        indexed[indexed_name] = item
    if set(indexed) < {layer.name for layer in layers}:
        raise TileRoundtripError("source index no longer covers every object layer")
    for layer in layers:
        entry = indexed[layer.name]
        if str(entry.get("file", "")) != layer.file:
            raise TileRoundtripError(f"{layer.name}: frame filename differs from source index")
        if _frame_number(layer.name) != layer.number:
            raise TileRoundtripError(f"{layer.name}: frame number differs from manifest")
        target = entry.get("crusader")
        if not isinstance(target, dict):
            raise TileRoundtripError(f"{layer.name}: Crusader geometry is missing")
        target_width = _integral(float(target.get("width", 0)), f"{layer.name} width")
        target_height = _integral(float(target.get("height", 0)), f"{layer.name} height")
        if (target_width, target_height) != (layer.width, layer.height):
            raise TileRoundtripError(
                f"{layer.name}: delivery canvas differs from the source index"
            )
    ora_name = _safe_flat_name(str(manifest.get("ora", "")), "ORA filename")
    ora_layers = _read_ora_layers(package_directory / ora_name, size)
    expected_names = {layer.name for layer in layers}
    actual_names = set(ora_layers)
    if actual_names != expected_names:
        missing = sorted(expected_names - actual_names)
        extra = sorted(actual_names - expected_names)
        raise TileRoundtripError(
            f"ORA layer set changed; missing={missing[:8]}, extra={extra[:8]}. "
            "Paint must be merged into one of the named tile layers before splitting."
        )

    split_images: dict[str, Image.Image] = {}
    changed: list[str] = []
    moved: list[str] = []
    for spec in layers:
        layer_image, layer_x, layer_y = ora_layers[spec.name]
        expected_box = (spec.x, spec.y, spec.x + spec.width, spec.y + spec.height)
        actual_box = (
            layer_x,
            layer_y,
            layer_x + layer_image.width,
            layer_y + layer_image.height,
        )
        overlap = (
            max(expected_box[0], actual_box[0]),
            max(expected_box[1], actual_box[1]),
            min(expected_box[2], actual_box[2]),
            min(expected_box[3], actual_box[3]),
        )
        if overlap[0] >= overlap[2] or overlap[1] >= overlap[3]:
            if layer_image.getchannel("A").getbbox() is not None:
                raise TileRoundtripError(f"{spec.name}: moved completely outside its tile canvas")
            tile = Image.new("RGBA", (spec.width, spec.height), (0, 0, 0, 0))
        else:
            # Reject visible pixels outside the fixed delivery rectangle.  The
            # layer may be moved or enlarged, but the game has nowhere to put
            # those pixels and silently clipping them would recreate the bug
            # this route exists to prevent.
            alpha = layer_image.getchannel("A")
            allowed_in_layer = (
                overlap[0] - layer_x,
                overlap[1] - layer_y,
                overlap[2] - layer_x,
                overlap[3] - layer_y,
            )
            outside = alpha.copy()
            outside.paste(0, allowed_in_layer)
            if outside.getbbox() is not None:
                raise TileRoundtripError(
                    f"{spec.name}: visible pixels leave its {spec.width}x{spec.height} "
                    "delivery canvas; move them back instead of clipping"
                )
            # Copy raw RGBA instead of alpha-compositing.  Alpha composition
            # may rewrite RGB bytes below fully transparent pixels; those bytes
            # are invisible but are still part of a lossless exported frame
            # and of sprites.py's pixel digest.
            tile = Image.new("RGBA", (spec.width, spec.height), (0, 0, 0, 0))
            source_crop = layer_image.crop(allowed_in_layer)
            tile.paste(
                source_crop,
                (overlap[0] - spec.x, overlap[1] - spec.y),
            )
        if tile.size != (spec.width, spec.height):
            raise TileRoundtripError(f"internal split geometry error for {spec.name}")
        split_images[spec.name] = tile
        if _pixel_digest(tile) != spec.baseline_pixels_sha256:
            changed.append(spec.name)
        if (layer_x, layer_y) != (spec.x, spec.y):
            moved.append(spec.name)
    summary = {
        "name": manifest.get("name"),
        "group": manifest.get("group"),
        "frame_count": len(layers),
        "changed_count": len(changed),
        "changed": changed,
        "moved_count": len(moved),
        "moved": moved,
        "canvas": {"width": size[0], "height": size[1]},
        "ora": ora_name,
        "semantic": dict(manifest["semantic"]),
    }
    return {"manifest": manifest, "source_index": source_index, "images": split_images, "summary": summary}


def render_current_preview(package_directory: Path) -> tuple[Image.Image, dict[str, Any]]:
    """Render the validated, current ORA layers in their pinned game order.

    ``object-preview.png`` records the package at composition time. Editors do
    not have to refresh OpenRaster's optional ``mergedimage.png``, so neither
    file proves what the named layers contain after editing. This renderer uses
    the exact same validated layer images that ``split_object`` will deliver.
    The preview can therefore never hide clipping, extra layers or stale merged
    data from the return path.
    """

    inspected = inspect_object(package_directory)
    manifest = inspected["manifest"]
    images: dict[str, Image.Image] = inspected["images"]
    specs = _manifest_layers(manifest)
    canvas = manifest["canvas"]
    size = (int(canvas["width"]), int(canvas["height"]))
    layers = [(spec, images[spec.name]) for spec in specs]
    return _render_preview(layers, size), inspected["summary"]


def write_current_preview(package_directory: Path) -> tuple[Path, dict[str, Any]]:
    """Atomically write a current-layer preview next to the editable ORA."""

    package_directory = package_directory.resolve()
    image, summary = render_current_preview(package_directory)
    destination = package_directory / CURRENT_PREVIEW_NAME
    temporary = package_directory / (CURRENT_PREVIEW_NAME + ".tmp")
    try:
        image.save(temporary, format="PNG", optimize=False, compress_level=9)
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    return destination, summary


def split_object(
    package_directory: Path,
    output_directory: Path,
    *,
    replace: bool = False,
    confirm_custom_layout: bool = False,
) -> dict[str, Any]:
    """Split the named ORA layers back into an ordinary sprites.py workspace."""

    inspected = inspect_object(package_directory)
    manifest = inspected["manifest"]
    source_index = inspected["source_index"]
    images: dict[str, Image.Image] = inspected["images"]
    semantic = manifest["semantic"]
    if semantic["status"] != "verified-preset" and not confirm_custom_layout:
        raise TileRoundtripError(
            "custom tile layout is not semantically verified; inspect the current "
            "preview and repeat with explicit custom-layout confirmation"
        )
    output_directory = output_directory.resolve()
    staging = _prepare_directory(output_directory, replace)
    try:
        # Keep only this object's frames, but retain their original export
        # digests.  sprites.py then identifies edited pixels correctly and its
        # ordinary `check` command does not report every frame outside the
        # selected building as missing.
        selected_names = set(images)
        split_index = dict(source_index)
        split_index["frames"] = [
            item
            for item in source_index.get("frames", [])
            if isinstance(item, dict) and str(item.get("name")) in selected_names
        ]
        (staging / "index.json").write_text(
            json.dumps(split_index, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        indexed = {
            str(item.get("name")): item
            for item in source_index.get("frames", [])
            if isinstance(item, dict)
        }
        for name, image in sorted(images.items(), key=lambda item: _frame_number(item[0])):
            filename = _safe_flat_name(str(indexed[name]["file"]), "frame filename")
            image.save(staging / filename, format="PNG", optimize=False, compress_level=9)
        result_summary = dict(inspected["summary"])
        if semantic["status"] == "custom-unconfirmed":
            result_summary["semantic"] = {
                "status": "user-confirmed",
                "preset_id": None,
                "contract_sha256": None,
            }
        (staging / "tile-object-result.json").write_text(
            json.dumps(result_summary, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        _commit_directory(staging, output_directory, replace)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return result_summary

"""Read-only shared sprite, atlas, DDS, mask and XAML asset inspector.

No Unity deserialization, DDS transcoding, Script Extender invocation, game
writes or XAML execution. All checks are structural, version-neutral hints.
"""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import file_digest
import json
from pathlib import Path
import struct
from typing import Any
from xml.etree import ElementTree

from PIL import Image, UnidentifiedImageError
from suite_environment_discovery import _safe_path

SCHEMA = "sprite-suite.shared-asset-inspection.v1"
SUFFIXES = frozenset({".png", ".dds", ".json", ".xaml", ".xml", ".lua", ".dll", ".cs", ".txt", ".webm"})
MAX_FILES = 2500
MAX_FILE_SIZE = 512 * 1024**2
MAX_TOTAL_SIZE = 2 * 1024**3
MAX_JSON = 4 * 1024**2
MAX_XML = 4 * 1024**2
MAX_IMAGE_PIXELS = 30_000_000
MAX_DEPTH = 12
SKIP = frozenset({".git", ".venv", "__pycache__", "node_modules", "vendor", "dist", "build", ".cache"})


class AssetInspectionError(ValueError):
    pass


class AssetInspectionBudgetError(AssetInspectionError):
    """Inspection was skipped; this does not establish malformed input."""


def _image_info(file: Path) -> dict:
    from stronghold_europe_de.asset_inspector import (
        inspect_asset, AssetInspectionError as SharedInspectionError,
    )
    try:
        details = inspect_asset(file)["details"]
    except SharedInspectionError as exc:
        raise AssetInspectionError(str(exc)) from exc
    return {"width": details["width"], "height": details["height"],
            "mode": details["source_mode"],
            "alpha": details["source_mode"] in {"RGBA", "LA", "P"},
            "alpha_bbox": tuple(details["alpha_bbox"]) if details["alpha_bbox"] else None,
            "rgba_sha256": details["rgba_sha256"],
            "hidden_rgb_pixels": details["hidden_rgb_pixels"],
            "partial_alpha_pixels": details["partial_alpha_pixels"]}


def _dds_info(file: Path) -> dict:
    with file.open("rb") as inp:
        header = inp.read(148)
    if len(header) < 128 or header[:4] != b"DDS " or struct.unpack_from("<I", header, 4)[0] != 124:
        raise AssetInspectionError("Ungültiger DDS-Header")
    height, width = struct.unpack_from("<II", header, 12)
    if not width or not height or width > 32768 or height > 32768:
        raise AssetInspectionError("DDS-Abmessungen unplausibel")
    fourcc = header[84:88]
    fmt = {b"DXT1": "BC1", b"DXT3": "BC2", b"DXT5": "BC3"}.get(fourcc, None)
    if fourcc == b"DX10":
        if len(header) < 148:
            raise AssetInspectionError("DX10-DDS-Header unvollständig")
        dxgi = struct.unpack_from("<I", header, 128)[0]
        fmt = {71: "BC1", 72: "BC1_sRGB", 74: "BC2", 75: "BC2_sRGB",
               77: "BC3", 78: "BC3_sRGB", 98: "BC7", 99: "BC7_sRGB"}.get(dxgi, "DXGI_"+str(dxgi))
    return {"width": width, "height": height, "compression": fmt or fourcc.decode("ascii", "replace"),
            "header_only": True, "decoded_pixels_verified": False}


def _json_info(file: Path) -> dict:
    if file.stat().st_size > MAX_JSON:
        return {"warning": "JSON größer als 4 MB: nicht geparst"}
    try:
        doc = json.loads(file.read_text(encoding="utf-8-sig"))
    except (ValueError, UnicodeError) as exc:
        raise AssetInspectionError("JSON ist ungültig") from exc
    if isinstance(doc, dict) and doc.get("schema") == "zinnenlineal.versatz.v1":
        from stronghold_europe_de.pivot_measurements import load_measurements
        try:
            rows = load_measurements(file)
        except ValueError as exc:
            raise AssetInspectionError("Historische Zinnenlineal-Messung ungültig") from exc
        return {"kind": "legacy_pivot_measurement", "records": len(rows.entries),
                "read_only_import": True}
    if not isinstance(doc, dict):
        return {"kind": "json_data", "top_type": type(doc).__name__}
    frames = doc.get("frames")
    if isinstance(frames, (dict, list)):
        if len(frames) > 100000:
            raise AssetInspectionError("Atlas hat zu viele Frames")
        problems = []
        for key, frame in (frames.items() if isinstance(frames, dict) else enumerate(frames)):
            if not isinstance(frame, dict):
                problems.append(str(key)); continue
            rect = frame.get("frame", frame)
            if not isinstance(rect, dict):
                problems.append(str(key)); continue
            if not all(isinstance(rect.get(c), (int, float)) and
                       not isinstance(rect.get(c), bool) and
                       0 <= rect[c] <= 32768 for c in ("x", "y", "w", "h")):
                problems.append(str(key)); continue
            if rect["w"] <= 0 or rect["h"] <= 0:
                problems.append(str(key))
            if len(problems) > 20:
                break
        return {"kind": "atlas_metadata", "frames": len(frames),
                "invalid_records_first_21": problems, "coordinates_verified_against_image": False}
    return {"kind": "json_data", "keys": sorted(doc)[:35]}


def _xaml_info(file: Path) -> dict:
    if file.stat().st_size > MAX_XML:
        raise AssetInspectionBudgetError(
            "XAML/XML überschreitet das 4-MiB-Inspektionsbudget; XML wurde nicht geparst")
    raw = file.read_bytes()
    upper = raw.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise AssetInspectionError("DOCTYPE/ENTITY in XAML/XML unzulässig")
    try:
        root = ElementTree.fromstring(raw)
    except (ElementTree.ParseError, UnicodeError, ValueError) as exc:
        raise AssetInspectionError("XAML/XML ungültig") from exc
    count = 0
    xpath = []
    for node in root.iter():
        count += 1
        if count > 100000:
            raise AssetInspectionError("XAML/XML enthält zu viele Elemente")
        for key, value in node.attrib.items():
            if key.rsplit("}", 1)[-1].lower() in {"xpath", "select"} and len(xpath) < 30:
                xpath.append(value[:256])
    return {"root": root.tag[:200], "nodes": count,
            "xpath_attributes_first_30": xpath,
            "noesis_bindings_verified": False, "game_version_verified": False}


def _walk(root: Path):
    stack = [(root, 0)]
    count = 0
    while stack:
        directory, depth = stack.pop()
        if _safe_path(directory) is None:
            raise AssetInspectionError("Verknüpftes Quellverzeichnis")
        for child in sorted(directory.iterdir(), key=lambda x: x.name.casefold()):
            if child.is_symlink() or _safe_path(child) is None:
                raise AssetInspectionError("Verknüpfter Assetpfad: " + child.name)
            if child.is_dir():
                if child.name in SKIP:
                    continue
                if depth >= MAX_DEPTH:
                    raise AssetInspectionError("Asset-Ordner zu tief verschachtelt")
                stack.append((child, depth+1))
            elif child.is_file() and child.suffix.lower() in SUFFIXES:
                count += 1
                if count > MAX_FILES:
                    raise AssetInspectionError("Mehr als 2500 Asset-Dateien")
                yield child


def inspect_assets(source: Path | str) -> dict:
    root = _safe_path(source)
    if root is None or not root.is_dir():
        raise AssetInspectionError("Asset-Ordner existiert nicht oder ist verknüpft")
    rows: list[dict[str, Any]] = []
    image_dimensions = {}
    total = 0
    for file in _walk(root):
        size = file.stat().st_size
        total += size
        if size > MAX_FILE_SIZE or total > MAX_TOTAL_SIZE:
            raise AssetInspectionError("Asset-Paket überschreitet die Lesebegrenzung")
        before = file.stat()
        with file.open("rb") as inp:
            digest = file_digest(inp, "sha256").hexdigest()
        row: dict[str, Any] = {
            "path": file.relative_to(root).as_posix(),
            "type": file.suffix.lower()[1:],
            "size": size, "sha256": digest,
            "status": "ok", "inspection": {}
        }
        try:
            if file.suffix.lower() == ".png":
                row["inspection"] = _image_info(file)
                image_dimensions[file.relative_to(root).as_posix().casefold()] = row["inspection"]
            elif file.suffix.lower() == ".dds":
                row["inspection"] = _dds_info(file)
            elif file.suffix.lower() == ".json":
                row["inspection"] = _json_info(file)
                if row["inspection"].get("invalid_records_first_21"):
                    row["status"] = "warning"
            elif file.suffix.lower() in (".xaml", ".xml"):
                row["inspection"] = _xaml_info(file)
            elif file.suffix.lower() in (".dll", ".lua", ".cs"):
                row["inspection"] = {"executable_or_source_data": True,
                                     "not_executed": True, "native_abi_verified": False}
            else:
                row["inspection"] = {"hash_only": True}
        except AssetInspectionBudgetError as exc:
            row["status"] = "warning"
            row["inspection"] = {"warning": str(exc), "xml_parsed": False}
        except (AssetInspectionError, OSError, OverflowError) as exc:
            row["status"] = "invalid"
            row["inspection"] = {"error": str(exc)}
        after = file.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise AssetInspectionError("Quelldatei hat sich während des Lesens verändert")
        rows.append(row)
    for row in rows:
        if row["type"] == "png" and row["path"].casefold().endswith("_m.png"):
            original = row["path"][:-6] + ".png"
            base = image_dimensions.get(original.casefold())
            current = row.get("inspection", {})
            if base is None:
                row["status"] = "warning" if row["status"] == "ok" else row["status"]
                row["inspection"]["mask_warning"] = "Farb-PNG zur Maske fehlt"
            elif current.get("width") != base.get("width") or current.get("height") != base.get("height"):
                row["status"] = "warning" if row["status"] == "ok" else row["status"]
                row["inspection"]["mask_warning"] = "Farb- und Maskenabmessungen unterscheiden sich"
    counts = Counter(row["status"] for row in rows)
    return {
        "schema": SCHEMA, "source": str(root), "assets": rows,
        "summary": {"count": len(rows), "bytes": total, "status": dict(counts)},
        "source_modified": False, "game_modified": False, "game_compatibility_verified": False,
        "noesis_runtime_verified": False, "dds_pixels_decoded": False
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="Read-only existing asset project")
    args = parser.parse_args(argv)
    try:
        proof = inspect_assets(args.source)
    except (OSError, AssetInspectionError) as exc:
        parser.error(str(exc))
    print(json.dumps(proof, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

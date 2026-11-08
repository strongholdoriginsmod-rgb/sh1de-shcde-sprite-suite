#!/usr/bin/env python3
"""Inspect and author SHCDE Custom Lord/AIVJSON packages and visual build plans.

Uses documented .lordjson, .aivjson, lordmeta.json and local Override assets.
For opaque proprietary AIV content, it preserves bytes and reports that no
visual build steps were decoded instead of inventing a native mapping.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
from xml.sax.saxutils import escape

from shcde_mod_composer import compose, sha256_file

CLASSIFY = {
    ".lordjson": "ai_lord",
    ".aivjson": "ai_castle",
    ".aic": "legacy_ai_config",
    ".aiv": "legacy_ai_castle",
    ".modlord.json": "mod_lord_data",
    ".map": "map",
    ".png": "image",
    ".dds": "texture",
    ".lua": "script",
    ".xaml": "noesis",
    ".ogg": "audio",
    ".wav": "audio",
    ".webm": "video",
    ".dll": "managed_or_native_plugin",
}


def category(name: str) -> str:
    lowered = name.casefold()
    if lowered.endswith(".modlord.json"):
        return "mod_lord_data"
    for suffix, kind in CLASSIFY.items():
        if lowered.endswith(suffix):
            return kind
    return "custom"


def index_lord(folder: Path) -> dict:
    root = Path(folder).resolve(strict=True)
    if not root.is_dir():
        raise NotADirectoryError(root)
    files = sorted((f for f in root.rglob("*") if f.is_file()),
                   key=lambda f: f.relative_to(root).as_posix().casefold())
    list_ = []
    count = Counter()
    for file in files:
        if file.is_symlink():
            raise ValueError("Linked file is not a portable mod asset: " + str(file))
        rel = file.relative_to(root).as_posix()
        group = category(rel)
        count[group] += 1
        list_.append({"relative": rel, "kind": group, "bytes": file.stat().st_size,
                      "sha256": sha256_file(file)})
    lords = [p for p in files if p.parent == root and p.name.casefold().endswith(".lordjson")]
    castles = [p for p in files if p.parent == root and p.name.casefold().endswith(".aivjson")]
    has_extra = (root / "lordmeta.json").is_file()
    requirements = []
    if not lords:
        requirements.append("No base .lordjson found in the Lord folder.")
    if not castles:
        requirements.append("No base .aivjson found in the Lord folder.")
    if has_extra and not (root / "info.json").is_file():
        requirements.append("lordmeta.json requires a root info.json.")
    return {
        "directory": str(root), "files": list_, "classCounts": dict(count),
        "baseLordConfigs": len(lords), "baseCastles": len(castles),
        "hasExtendedLordMetadata": has_extra,
        "compatibilityFindings": requirements,
        "opaqueAivEngineFormatModified": False,
        "gameWasExecuted": False,
    }


def prepare_lord(folder: Path, *, name: str, guid: str, author: str,
                 version: str = "1.0.0",
                 metadata: dict | None = None) -> dict:
    report = index_lord(folder)
    root = Path(folder)
    if report["baseLordConfigs"] == 0 or report["baseCastles"] == 0:
        raise ValueError("Working .lordjson and .aivjson are needed before authoring extensions")
    if not name.strip() or not guid.strip():
        raise ValueError("Provide package name and GUID")
    if (root / "info.json").exists() or (root / "lordmeta.json").exists():
        raise FileExistsError("Existing Lord metadata is never silently overwritten")
    info = {
        "GUID": guid, "Author": author, "Name": name,
        "Description": "Custom Lord extended with SpriteSuite",
        "Version": version, "Dependencies": [], "Manifest": 0,
        "AssetMode": "Local", "NetworkMode": 0,
    }
    extra = metadata or {"LocalizedDisplayName": {"en-US": name}}
    if not isinstance(extra, dict):
        raise ValueError("Extended Lord metadata must be a JSON object")
    with (root / "info.json").open("x", encoding="utf-8") as file:
        json.dump(info, file, ensure_ascii=False, indent=2)
    with (root / "lordmeta.json").open("x", encoding="utf-8") as file:
        json.dump(extra, file, ensure_ascii=False, indent=2)
    return {"created": ["info.json", "lordmeta.json"], "root": str(root),
            "currentGameLordValidated": False}


def _iter_placements(node: object, *, depth: int = 0):
    if depth > 40:
        return
    if isinstance(node, dict):
        if all(key in node for key in ("x", "y")):
            try:
                x, y = int(node["x"]), int(node["y"])
            except (TypeError, ValueError):
                pass
            else:
                if any(key in node for key in ("buildingType", "type", "building", "kind")):
                    yield {"x": x, "y": y, "type": str(node.get("buildingType",
                        node.get("type", node.get("building", node.get("kind"))))),
                        "step": node.get("step", node.get("phase", 0))}
        for value in node.values():
            yield from _iter_placements(value, depth=depth + 1)
    elif isinstance(node, list):
        for value in node:
            yield from _iter_placements(value, depth=depth + 1)


def aiv_layout(document: dict) -> dict:
    buildings = list(_iter_placements(document))
    seen = set()
    unique = []
    for building in buildings:
        key = (building["x"], building["y"], building["type"], str(building["step"]))
        if key not in seen:
            seen.add(key)
            unique.append(building)
    return {
        "schema": "spritesuite.shcde.aiv-graphic-plan.v1",
        "placements": unique, "count": len(unique),
        "nativeAivGridFormatDecoded": False,
        "usesAuthorProvidedCoordinates": True,
        "visualProjection": "isometric",
    }


def layout_svg(layout: dict, width: int = 980, height: int = 640) -> str:
    placements = layout.get("placements", [])
    if not placements:
        raise ValueError("No drawable coordinate entries found in this AIVJSON")
    if width <= 100 or height <= 100:
        raise ValueError("Canvas must fit readable map labels")
    # Coordinates are author-supplied. No hidden y*800+x tile assumption.
    projected = [(0.5 * (row["x"] - row["y"]),
                  0.25 * (row["x"] + row["y"]), row) for row in placements]
    xs = [x for x, _, _ in projected]
    ys = [y for _, y, _ in projected]
    spanx = max(xs) - min(xs) + 2
    spany = max(ys) - min(ys) + 2
    scale = min((width - 80) / spanx, (height - 80) / spany)
    scale = max(0.1, scale)
    pieces = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<svg xmlns="http://www.w3.org/2000/svg" width="' + str(width) +
        '" height="' + str(height) + '" viewBox="0 0 ' + str(width) + " " +
        str(height) + '">',
        '<rect width="100%" height="100%" fill="#171d29"/>',
    ]
    for x, y, row in sorted(projected, key=lambda a: (a[1], a[0])):
        px = 40 + (x - min(xs) + 0.5) * scale
        py = 40 + (y - min(ys) + 0.5) * scale
        half = max(5, min(30, scale * 0.42))
        h = max(3, half * 0.5)
        typ = str(row["type"])
        color = "#" + hashlib.md5(typ.encode("utf-8")).hexdigest()[:6]
        points = [(px, py-h), (px+half, py), (px, py+h), (px-half, py)]
        polygon = " ".join(f"{a:.1f},{b:.1f}" for a, b in points)
        pieces.append(f'<polygon points="{polygon}" fill="{color}" '
                      'stroke="#e2e8f0" stroke-width="1"/>')
        pieces.append(f'<title>{escape(typ)} at {row["x"]},{row["y"]} '
                      f'step {escape(str(row["step"]))}</title>')
        pieces.append(f'<text x="{px:.1f}" y="{py+3:.1f}" '
                      'font-size="9" text-anchor="middle" fill="white">' +
                      escape(typ[:8]) + '</text>')
    pieces.append("</svg>")
    return "\n".join(pieces) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="action", required=True)
    catalog = sub.add_parser("inspect")
    catalog.add_argument("--lord-directory", type=Path, required=True)
    metadata = sub.add_parser("extend")
    metadata.add_argument("--lord-directory", type=Path, required=True)
    metadata.add_argument("--name", required=True)
    metadata.add_argument("--guid", required=True)
    metadata.add_argument("--author", default="Creator")
    metadata.add_argument("--version", default="1.0.0")
    metadata.add_argument("--metadata", type=Path)
    aiv = sub.add_parser("aiv-preview")
    aiv.add_argument("--json", type=Path, required=True)
    aiv.add_argument("--output", type=Path, required=True)
    mod = sub.add_parser("package")
    mod.add_argument("--lord-directory", type=Path, required=True)
    mod.add_argument("--output", type=Path, required=True)
    args = p.parse_args(argv)
    try:
        if args.action == "inspect":
            result = index_lord(args.lord_directory)
        elif args.action == "extend":
            content = json.loads(args.metadata.read_text(encoding="utf-8-sig")) if args.metadata else None
            result = prepare_lord(args.lord_directory, name=args.name, guid=args.guid,
                                  author=args.author, version=args.version,
                                  metadata=content)
        elif args.action == "aiv-preview":
            content = json.loads(args.json.read_text(encoding="utf-8-sig"))
            layout = aiv_layout(content)
            if args.output.exists():
                raise FileExistsError("Existing SVG preview cannot be overwritten")
            args.output.write_text(layout_svg(layout), encoding="utf-8")
            result = {"svg": str(args.output), "placements": layout["count"],
                      "nativeAivValidatedInGame": False}
        else:
            report = index_lord(args.lord_directory)
            result = compose([args.lord_directory], args.output)
            result["lordCompatibilityFindings"] = report["compatibilityFindings"]
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, TypeError) as error:
        print("Custom Lord/AIV studio: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

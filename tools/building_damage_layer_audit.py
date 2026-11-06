#!/usr/bin/env python3
"""Audit real SHCDE building graphics vs gameplay occupation, without writing game data.

The same game tile coordinates can have different drawing layers. Never infer
per-building damage replacement targets from GameMap.getMapTile terrain sprites.
This tool only analyzes SHA-pinned, read-only SpriteSuite QA log evidence.
"""
from __future__ import annotations
import argparse
import collections
import hashlib
import json
from pathlib import Path
import re
import sys

MARKER = "SHCDE_DAMAGE_QA|"
MAX_LOG_BYTES = 64 * 1024 * 1024
MAX_EVENTS = 200_000
EXPECTED_EVENTS = {"building_footprint", "tile_graphic", "building_render_tiles"}

class AuditError(ValueError):
    pass

def ensure(cond: bool, reason: str) -> None:
    if not cond:
        raise AuditError(reason)

def parse_log_bytes(raw: bytes) -> list[dict[str, str]]:
    ensure(len(raw) <= MAX_LOG_BYTES, "QA log exceeds budget.")
    events = []
    for line in raw.decode("utf-8", "replace").splitlines():
        if MARKER not in line:
            continue
        values = line.split(MARKER, 1)[1]
        event = {}
        for segment in values.split("|"):
            if "=" not in segment:
                continue
            key, value = segment.split("=", 1)
            ensure(key not in event, "Duplicate field in QA log event: " + key[:50])
            ensure(re.fullmatch(r"[a-zA-Z_][a-zA-Z_0-9]{0,63}", key) is not None,
                   "Malformed QA event field.")
            event[key] = value
        if event.get("event") in EXPECTED_EVENTS:
            ensure(len(events) < MAX_EVENTS, "QA log has excessive events.")
            events.append(event)
    return events

def positive(value: str, label: str) -> int:
    ensure(value.isdecimal() and len(value) <= 12, "Invalid " + label)
    result = int(value)
    ensure(result >= 0, "Negative " + label)
    return result

def tile_set(value: str) -> dict[int, tuple[int, int]]:
    result = {}
    for item in value.split(";"):
        if not item:
            continue
        columns = item.split(":")
        ensure(len(columns) == 2, "Invalid footprint tile.")
        number = positive(columns[0], "footprint tile ID")
        pair = columns[1].split(",")
        ensure(len(pair) == 2, "Invalid footprint tile coordinates.")
        xy = (positive(pair[0], "tile x"), positive(pair[1], "tile y"))
        ensure(number not in result, "Duplicated footprint tile ID.")
        result[number] = xy
    return result

def parse_render_samples(value: str) -> list[dict]:
    items = []
    for item in value.split(";"):
        if not item:
            continue
        parts = item.split(":", 3)
        ensure(len(parts) == 4, "Malformed render layer sample.")
        xy = parts[1].split(",")
        ensure(len(xy) == 2, "Malformed sample xy.")
        items.append({
            "tileId": positive(parts[0], "sample tile"),
            "x": positive(xy[0], "sample x"),
            "y": positive(xy[1], "sample y"),
            "groundOrDefaultSprite": parts[2],
            "tilemapSpriteAtReportedPosition": parts[3],
        })
    return items

def analyze_events(events: list[dict[str, str]]) -> dict:
    by_id = {}
    totals = collections.Counter()
    for event in events:
        kind = event["event"]
        building_id = positive(event.get("building_id", ""), "building ID")
        global_id = positive(event.get("global_id", ""), "building global ID")
        building_type = positive(event.get("type", ""), "building type")
        ensure(building_id > 0 and global_id > 0 and building_type <= 4095,
               "Invalid building identity.")
        key = (building_id, global_id)
        if key not in by_id:
            by_id[key] = {
                "buildingId": building_id,
                "globalId": global_id,
                "buildingType": building_type,
                "footprint": None,
                "drawingEvents": [],
                "tileLayerSamples": [],
            }
        item = by_id[key]
        ensure(item["buildingType"] == building_type,
               "Building type changed inside a single global identity.")
        totals[kind] += 1
        if kind == "building_footprint":
            tiles = tile_set(event.get("tiles", ""))
            ensure(len(tiles) > 0, "Empty reported building footprint.")
            if item["footprint"] is not None:
                ensure(item["footprint"] == tiles, "Footprint changes during one identity.")
            item["footprint"] = tiles
        elif kind == "tile_graphic":
            tile_id = positive(event.get("tile_id", ""), "draw tile")
            x = positive(event.get("x", ""), "draw x")
            y = positive(event.get("y", ""), "draw y")
            index = event.get("occupied_index", "")
            ensure(index == "-1" or index.isdecimal(),
                   "Missing graphical tile membership evidence.")
            inside = int(index) >= 0
            item["drawingEvents"].append({
                "tileId": tile_id, "x": x, "y": y,
                "sprite": event.get("sprite", ""),
                "gm": event.get("gm", ""),
                "image": event.get("image", ""),
                "withinGameFootprint": inside,
                "nativeFootprintIndex": int(index),
                "reportedNativeTileCount": int(event.get("occupied_count", "-1")),
            })
        else:
            item["tileLayerSamples"].extend(
                parse_render_samples(event.get("samples", "")))
    out = []
    summary = collections.Counter()
    graphical_families = collections.Counter()
    mapped_keys = []
    for key, item in sorted(by_id.items()):
        f = item["footprint"]
        drawing = item["drawingEvents"]
        render = item["tileLayerSamples"]
        native_inside = sum(x["withinGameFootprint"] for x in drawing)
        native_outside = len(drawing) - native_inside
        reported_ids = {x["tileId"] for x in drawing}
        overlap = None if f is None else len(set(f) & reported_ids)
        terrain_family = collections.Counter()
        for x in render:
            family = x["groundOrDefaultSprite"].split("~", 1)[0]
            family = re.sub(r"\s+\d{1,4}$", "", family)
            terrain_family[family] += 1
        for x in drawing:
            family = re.sub(r"\s+\d{1,4}$", "", x["sprite"])
            graphical_families[family] += 1
        summary["graphics_within_gameplay_footprint"] += native_inside
        summary["graphics_outside_gameplay_footprint"] += native_outside
        summary["drawable_tile_events"] += len(drawing)
        summary["terrain_or_default_layer_samples"] += len(render)
        if f is not None:
            summary["footprints"] += 1
        if drawing and f is not None:
            mapped_keys.append(key)
        out.append({
            "buildingId": item["buildingId"],
            "globalId": item["globalId"],
            "buildingType": item["buildingType"],
            "footprintTileCount": len(f) if f is not None else None,
            "drawingEventCount": len(drawing),
            "drawingTilesWithinNativeFootprint": native_inside,
            "drawingTilesOutsideNativeFootprint": native_outside,
            "drawingIDsAlsoInReportedFootprint": overlap,
            "defaultLayerSamples": len(render),
            "defaultLayerSpriteFamilies": dict(sorted(terrain_family.items())),
            "drawingGraphics": drawing,
            "defaultLayer": render,
            "rendererMappingVerified": False,
            "writableGameTileBindingVerified": False,
        })
    return {
        "format": "spritesuite-shcde-building-layer-audit",
        "version": 1,
        "readOnly": True,
        "inGameDamageSwitchVerified": False,
        "directRendererMutationAllowed": False,
        "summary": {
            **dict(summary),
            "uniqueBuildingIdentities": len(out),
            "identitiesWithBothFootprintAndGraphic": len(mapped_keys),
            "drawingSpriteFamilies": dict(sorted(graphical_families.items())),
            "needsDistinctBuildingGraphicLayer": True,
        },
        "buildings": out,
    }

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--expected-sha256", type=str, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        ensure(re.fullmatch(r"[0-9a-f]{64}", args.expected_sha256) is not None,
               "Expected SHA-256 must be lowercase hexadecimal.")
        ensure(args.log.is_file() and not args.log.is_symlink(), "QA log is missing.")
        ensure(args.log.stat().st_size <= MAX_LOG_BYTES, "QA log exceeds budget.")
        raw = args.log.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        ensure(digest == args.expected_sha256, "QA log SHA-256 does not match.")
        result = analyze_events(parse_log_bytes(raw))
        result["sourceLogSHA256"] = digest
        result["eventCounts"] = dict(sorted(collections.Counter(
            row["event"] for row in parse_log_bytes(raw)).items()))
        if args.output is not None:
            ensure(not args.output.exists() and args.output.parent.is_dir(),
                   "Output path must be new, in an existing directory.")
            with args.output.open("x", encoding="utf-8", newline="\n") as file:
                json.dump(result, file, ensure_ascii=False, indent=2)
                file.write("\n")
        print(json.dumps({
            "sourceLogSHA256": digest,
            "eventCounts": result["eventCounts"],
            "summary": result["summary"],
            "output": str(args.output) if args.output else None,
        }, indent=2, ensure_ascii=False))
        return 0
    except (AuditError, OSError, ValueError) as err:
        print("Building-layer audit: " + str(err), file=sys.stderr)
        return 2

if __name__ == "__main__":
    sys.exit(main())

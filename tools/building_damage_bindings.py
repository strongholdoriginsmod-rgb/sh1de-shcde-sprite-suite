#!/usr/bin/env python3
"""Generate editable runtime sprite-slot bindings from a real QA SpriteMapping log.

All eight isometric orientations are listed when possible. A proposed mapping
is not a proven renderer mapping; the game has extra visual layers and its
footprint can differ from the artwork's grid.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile, BadZipFile

TRANSFORMS = {
    "identity": lambda u, v: (u, v),
    "rotate90": lambda u, v: (-v, u),
    "rotate180": lambda u, v: (-u, -v),
    "rotate270": lambda u, v: (v, -u),
    "reflect_u": lambda u, v: (-u, v),
    "reflect_v": lambda u, v: (u, -v),
    "swap": lambda u, v: (v, u),
    "reverse_swap": lambda u, v: (-v, -u),
}


def stage_positions(a: int, b: int) -> list[tuple[int, int]]:
    if a <= 0 or b <= 0:
        raise ValueError("Stage grid dimensions must be positive")
    return [(u, d-u) for d in range(a+b-1)
            for u in range(min(a-1, d), max(0, d-b+1)-1, -1)]


def read_graphic_events(log: Path, building_type: int, global_id: int | None):
    chosen = []
    for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
        if "SHCDE_DAMAGE_QA|event=tile_graphic|" not in line:
            continue
        fields = {}
        for item in line.split("SHCDE_DAMAGE_QA|", 1)[1].split("|"):
            if "=" in item:
                k, v = item.split("=", 1)
                fields[k] = v
        if int(fields.get("type", "-1")) != building_type:
            continue
        gid = int(fields.get("global_id", "-1"))
        if global_id is not None and gid != global_id:
            continue
        if not all(k in fields for k in ("x", "y", "gm", "image", "sprite")):
            continue
        chosen.append(fields)
    if global_id is None:
        by_gid = {}
        for event in chosen:
            by_gid.setdefault(event["global_id"], set()).add((event["x"], event["y"]))
        if not by_gid:
            return []
        best = max(by_gid, key=lambda gid: len(by_gid[gid]))
        chosen = [event for event in chosen if event["global_id"] == best]
    # Multiple sprite redraws of one cell are possible. Use the last event per
    # coordinate; retain source GM and image for the editable user mapping.
    by_xy = {}
    for event in chosen:
        by_xy[(int(event["x"]), int(event["y"]))] = event
    return list(by_xy.values())


def propose(events: list[dict], a: int, b: int, group_id: str,
            building_type: int, orientation: str = "identity") -> dict:
    if orientation not in TRANSFORMS:
        raise ValueError("Unknown orientation")
    positions = stage_positions(a, b)
    by_xy = {(int(e["x"]), int(e["y"])): e for e in events}
    measured = set(by_xy)
    options = {}
    for name, transform in TRANSFORMS.items():
        points = [transform(u, v) for u, v in positions]
        x_min = min(x for x, _ in points)
        y_min = min(y for _, y in points)
        xs = min((x for x, y in measured), default=0)
        ys = min((y for x, y in measured), default=0)
        translated = [(x-x_min+xs, y-y_min+ys) for x,y in points]
        count = sum(xy in measured for xy in translated)
        options[name] = {"matched": count, "total": len(positions),
                         "matchesAllPositions": len(positions) == len(measured) == count}
    pts = [TRANSFORMS[orientation](*xy) for xy in positions]
    min_x, min_y = min(x for x, y in pts), min(y for x, y in pts)
    xs = min((x for x, y in measured), default=0)
    ys = min((y for x, y in measured), default=0)
    # Real SHCDE building graphics often overhang the gameplay footprint.
    # For such cells, propose the nearest *observed* owned drawing cell so
    # the runtime can resolve the correct building without assuming y*800+x.
    occupied = []
    for event in events:
        raw_index = event.get("occupied_index")
        if raw_index is not None and raw_index.lstrip("-").isdigit() and int(raw_index) >= 0:
            occupied.append((int(event["x"]), int(event["y"])))
    bindings = []
    inferred_owner_offsets = 0
    unresolved_overhangs = 0
    for slot, (x,y) in enumerate(pts):
        item = by_xy.get((x-min_x+xs, y-min_y+ys))
        if item is None:
            continue
        cell = (int(item["x"]), int(item["y"]))
        raw_index = item.get("occupied_index")
        outside = raw_index is not None and raw_index.strip() == "-1"
        owner_offset = (0, 0)
        if outside and occupied:
            owner = min(occupied, key=lambda p: (abs(p[0]-cell[0])+abs(p[1]-cell[1]),
                                                  abs(p[0]-cell[0]),p[0],p[1]))
            owner_offset = (owner[0]-cell[0], owner[1]-cell[1])
            inferred_owner_offsets += 1
        elif outside:
            unresolved_overhangs += 1
        bindings.append({
            "buildingType": building_type,
            "buildingGroupId": group_id,
            "sourceSprite": item["sprite"],
            "matchGmImage": True,
            "gm": int(item["gm"]),
            "image": int(item["image"]),
            "slot": slot,
            "ownerOffsetX": owner_offset[0],
            "ownerOffsetY": owner_offset[1],
        })
    return {"damageArchive": "gebaeudeschaden_alle.zip",
            "enabled": True, "firePersistsUntilRepaired": True, "pollFrames": 12,
            "bindings": bindings,
            "provenance": {"mappingConfirmedInGame": False,
                           "chosenOrientation": orientation,
                           "sourceGraphicCells": len(events),
                           "spriteGridSlots": len(positions),
                           "orientationCandidates": options,
                           "sourceOccupiedArtCells": len(occupied),
                           "proposedOverhangOwnerOffsets": inferred_owner_offsets,
                           "unresolvedOverhangOwnerOffsets": unresolved_overhangs,
                           "requiresGameplayOwnerOffsetReview": True}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--expected-log-sha256", help="Optional exact source-log SHA-256")
    parser.add_argument("--archive", type=Path, help="SpriteSuite damage ZIP to read the sprite grid")
    parser.add_argument("--grid-a", type=int, help="Explicit source-art grid dimension A")
    parser.add_argument("--grid-b", type=int, help="Explicit source-art grid dimension B")
    parser.add_argument("--building-group", required=True)
    parser.add_argument("--building-type", type=int, required=True)
    parser.add_argument("--global-id", type=int)
    parser.add_argument("--orientation", choices=list(TRANSFORMS), default="identity")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        digest = hashlib.sha256(args.log.read_bytes()).hexdigest()
        if args.expected_log_sha256 and digest != args.expected_log_sha256.lower():
            raise ValueError("Graphics QA log does not match its expected SHA-256")
        a, b = args.grid_a, args.grid_b
        if (a is None) != (b is None):
            raise ValueError("Provide both --grid-a and --grid-b")
        if args.archive:
            with ZipFile(args.archive) as archive:
                manifest = json.loads(archive.read("damage-manifest.json"))
            matches = [building for building in manifest["buildings"]
                       if building["id"] == args.building_group]
            if len(matches) != 1 or not matches[0].get("stages"):
                raise ValueError("Archive must identify one building with a stage grid")
            settings = matches[0]["stages"][0]["settings"]
            archive_grid = settings["a"], settings["b"]
            if a is not None and (a, b) != archive_grid:
                raise ValueError("Explicit grid differs from the archive grid")
            a, b = archive_grid
        if type(a) is not int or type(b) is not int or a <= 0 or b <= 0:
            raise ValueError("Provide an archive or positive --grid-a and --grid-b")
        events = read_graphic_events(args.log, args.building_type, args.global_id)
        report = propose(events, a, b, args.building_group,
                         args.building_type, args.orientation)
        # A proposal remains freely editable. It can include partial logs and
        # unresolved overhangs, which the provenance describes for the caller.
        report["enabled"] = False
        report["previewEnabled"] = False
        report["provenance"]["graphicsLogSHA256"] = digest
        with args.output.open("x", encoding="utf-8", newline="\n") as output:
            json.dump(report, output, ensure_ascii=False, indent=2)
            output.write("\n")
        print("PROPOSED_BINDINGS=" + str(len(report["bindings"])))
        print("CONFIRMED_IN_GAME=false")
        print("ENABLED=false")
        return 0
    except (OSError, ValueError, KeyError, TypeError, BadZipFile) as error:
        parser.exit(2, "Runtime binding proposal: " + str(error) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())

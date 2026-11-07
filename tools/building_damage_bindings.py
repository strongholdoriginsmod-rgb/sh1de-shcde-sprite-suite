#!/usr/bin/env python3
"""Generate editable runtime sprite-slot bindings from a real QA SpriteMapping log.

All eight isometric orientations are listed when possible. A proposed mapping
is not a proven renderer mapping; the game has extra visual layers and its
footprint can differ from the artwork's grid.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from zipfile import ZipFile

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


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--log", type=Path, required=True)
    p.add_argument("--archive", type=Path, required=True)
    p.add_argument("--building-group", required=True)
    p.add_argument("--building-type", type=int, required=True)
    p.add_argument("--global-id", type=int)
    p.add_argument("--orientation", choices=list(TRANSFORMS), default="identity")
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    with ZipFile(args.archive) as zip:
        manifest = json.loads(zip.read("damage-manifest.json"))
    profile = next(b for b in manifest["buildings"] if b["id"] == args.building_group)
    scene = profile["stages"][0]["settings"]
    events = read_graphic_events(args.log, args.building_type, args.global_id)
    report = propose(events, scene["a"], scene["b"], args.building_group,
                     args.building_type, args.orientation)
    if args.output.exists():
        raise FileExistsError("Output already exists: " + str(args.output))
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print("PROPOSED_BINDINGS="+str(len(report["bindings"])))
    print("CONFIRMED_IN_GAME=false")


if __name__ == "__main__":
    main()

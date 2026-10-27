"""Locate every Unity object behind one or more GM groups.

Answers, for any unit, building or effect group: which loader registration it
has, which atlas holds its pixels, where those pixels physically live, which
sprite PathIDs belong to it, which frame slots are occupied, and whether
Stronghold 1 DE has any donor frames at all.

This runs entirely on the inventories the pipeline already produces, so it needs
no extraction step and touches neither installation.

Usage::

    python tools/locate_unit.py body_horse_archer body_horse_archer_top
    python tools/locate_unit.py body_swordsman --json
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from stronghold_europe_de.loader_groups import LOADER_GROUP_TABLE  # noqa: E402
from stronghold_europe_de.mapping import _group_name  # noqa: E402
from stronghold_europe_de.unity_inventory import read_inventory  # noqa: E402


def contiguous_blocks(values: list[int]) -> list[tuple[int, int]]:
    blocks: list[tuple[int, int]] = []
    start = previous = None
    for value in sorted(values):
        if start is None:
            start = previous = value
            continue
        if value == previous + 1:
            previous = value
            continue
        blocks.append((start, previous))
        start = previous = value
    if start is not None:
        blocks.append((start, previous))
    return blocks


def describe(group: str, target: dict, source: dict) -> dict:
    loader = LOADER_GROUP_TABLE.get(group)
    textures = {t["name"]: t for t in target["textures"]}
    sprites = [s for s in target["sprites"] if _group_name(str(s["name"])) == group]
    donors = [s for s in source["sprites"] if _group_name(str(s["name"])) == group]
    if not sprites:
        raise SystemExit(f"No target sprites belong to {group!r}")

    main: list[int] = []
    alt: list[int] = []
    for sprite in sprites:
        suffix = str(sprite["name"])[len(group) + 1 :]
        (alt if suffix.endswith("x") else main).append(int(suffix.rstrip("x")))

    atlases = sorted({str(s["texture_name"]) for s in sprites})
    atlas_records = []
    for atlas in atlases:
        record = textures[atlas]
        entry = {"name": atlas, **{k: record[k] for k in
                 ("path_id", "width", "height", "texture_format",
                  "stream_path", "stream_offset", "stream_size")}}
        mask = textures.get(atlas + "_m")
        if mask:
            entry["mask"] = {"name": atlas + "_m", **{k: mask[k] for k in
                             ("path_id", "width", "height", "texture_format",
                              "stream_path", "stream_offset", "stream_size")}}
        atlas_records.append(entry)

    sizes = Counter((int(s["width"]), int(s["height"])) for s in sprites)
    path_ids = [int(s["path_id"]) for s in sprites]
    highest = max(main + alt)
    return {
        "group": group,
        "loader": None if loader is None else {
            "gm_enum": loader.gm_enum,
            "dash_format": loader.dash_format,
            "plain_shader": loader.plain_shader,
            "declared_image_count": loader.declared_image_count,
            "custom_palette": loader.custom_palette,
            "id_offset": loader.id_offset,
            "additional_storage": loader.additional_storage,
            "owns_its_gm_arrays": loader.owns_its_gm_arrays,
            "mask_policy": "forbidden" if loader.plain_shader else "required",
        },
        "target_frame_count": len(sprites),
        "source_donor_frame_count": len(donors),
        "atlases": atlas_records,
        "main_frames": len(main),
        "alt_frames": len(alt),
        "main_blocks": contiguous_blocks(main),
        "alt_blocks": contiguous_blocks(alt),
        "highest_index": highest,
        "loader_array_size": highest + 1,
        "distinct_canvas_sizes": len(sizes),
        "most_common_canvas_sizes": [
            {"width": w, "height": h, "count": c} for (w, h), c in sizes.most_common(5)
        ],
        "sprite_path_id_range": [min(path_ids), max(path_ids)],
    }


def render(entry: dict) -> None:
    loader = entry["loader"]
    print("-" * 78)
    print(f"GROUP {entry['group']}")
    print("-" * 78)
    if loader is None:
        print("  not registered by the pinned loader")
    else:
        print(f"  GM enum            : {loader['gm_enum']}")
        print(f"  addGMFile          : count={loader['declared_image_count']} "
              f"dashFormat={str(loader['dash_format']).lower()} "
              f"plainShader={str(loader['plain_shader']).lower()}")
        print(f"  mask policy        : {loader['mask_policy']}")
        print(f"  custom palette     : {loader['custom_palette']}")
        print(f"  owns its GM arrays : {loader['owns_its_gm_arrays']} "
              f"(ID_Offset={loader['id_offset']}, extra={loader['additional_storage']})")
    print(f"  frames in Crusader : {entry['target_frame_count']}")
    print(f"  donor frames in SH1: {entry['source_donor_frame_count']}")
    for atlas in entry["atlases"]:
        print(f"  atlas {atlas['name']}: {atlas['width']}x{atlas['height']} "
              f"fmt={atlas['texture_format']} PathID={atlas['path_id']}")
        print(f"    pixels in {atlas['stream_path']} @ {atlas['stream_offset']}, "
              f"{atlas['stream_size']} bytes")
        mask = atlas.get("mask")
        if mask:
            print(f"  mask  {mask['name']}: {mask['width']}x{mask['height']} "
                  f"fmt={mask['texture_format']} PathID={mask['path_id']}")
            print(f"    pixels in {mask['stream_path']} @ {mask['stream_offset']}, "
                  f"{mask['stream_size']} bytes")
    print(f"  main frames        : {entry['main_frames']}  blocks {entry['main_blocks']}")
    print(f"  alt frames         : {entry['alt_frames']}  blocks {entry['alt_blocks']}")
    print(f"  loader array size  : {entry['loader_array_size']}")
    print(f"  canvas sizes       : {entry['distinct_canvas_sizes']} distinct")
    print(f"  sprite PathIDs     : {entry['sprite_path_id_range'][0]} .. "
          f"{entry['sprite_path_id_range'][1]}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("groups", nargs="+", help="GM group names")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of a report")
    args = parser.parse_args(argv)

    inventory_dir = REPO_ROOT / "work" / "inventory"
    target = read_inventory(inventory_dir / "target.resources.json.gz")
    source = read_inventory(inventory_dir / "source.resources.json.gz")

    entries = [describe(group, target, source) for group in args.groups]
    if args.json:
        print(json.dumps(entries, indent=2))
        return 0
    for entry in entries:
        render(entry)
    total = sum(e["target_frame_count"] for e in entries)
    donors = sum(e["source_donor_frame_count"] for e in entries)
    print()
    print(f"{total} Crusader frames, {donors} Stronghold 1 DE donor frames.")
    if donors == 0:
        print("No donor material: these groups can be extracted and studied, but not")
        print("converted. New art or a KEEP decision is the only way forward.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

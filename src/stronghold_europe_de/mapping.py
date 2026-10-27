from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import gzip
import json
from math import isclose
from pathlib import Path
import re
from typing import Any

from .loader_groups import loader_group_for_sprite
from .unity_inventory import read_inventory


GEOMETRY_TOLERANCE = 1e-4
EUROPE_MUSIC_SOURCE_NAMES = {
    "appytimes",
    "castlejam",
    "chantloop1",
    "darktime",
    "exploration",
    "journeys",
    "mandloop1",
    "mandloop2",
    "mattsjig",
    "monks1",
    "paranoia",
    "sadtimesa",
    "sadtimesb",
    "stainedglass1",
    "the maidena",
    "the maidenb",
    "underanoldtree",
}


def _close(left: float, right: float) -> bool:
    return isclose(left, right, abs_tol=GEOMETRY_TOLERANCE)


def _absolute_pivot(sprite: dict[str, Any]) -> tuple[float, float]:
    return (
        float(sprite["pivot_x"]) * float(sprite["width"]),
        float(sprite["pivot_y"]) * float(sprite["height"]),
    )


def _geometry_equal(source: dict[str, Any], target: dict[str, Any]) -> bool:
    source_pivot = _absolute_pivot(source)
    target_pivot = _absolute_pivot(target)
    return (
        _close(float(source["width"]), float(target["width"]))
        and _close(float(source["height"]), float(target["height"]))
        and _close(source_pivot[0], target_pivot[0])
        and _close(source_pivot[1], target_pivot[1])
        and _close(float(source["pixels_per_unit"]), float(target["pixels_per_unit"]))
    )


def _group_name(sprite_name: str) -> str:
    """Return the loader group a sprite belongs to.

    The registered `addGMFile` table is authoritative because no naming rule can
    recover the grouping on its own: `anim_castle 001` and `blast3-64` are frames
    of one group each, while `smoke-30x30` and `puff of smoke` are group names
    that themselves contain a dash and spaces. The regex below is only the
    fallback for the few names the pinned loader never registers, such as the
    `Debug Logic` and `Info Tile` development overlays.
    """

    registered = loader_group_for_sprite(sprite_name)
    if registered is not None:
        return registered
    if sprite_name.startswith(("body_", "anim_", "tree_", "Tree_")):
        return re.sub(r"-\d+x?$", "", sprite_name)
    if sprite_name.startswith("tile_"):
        return re.sub(r"[ -]\d+x?$", "", sprite_name)
    return sprite_name.split(" ", 1)[0]


def _proposal(source: dict[str, Any] | None, target: dict[str, Any]) -> dict[str, Any]:
    target_pivot = _absolute_pivot(target)
    base = {
        "name": target["name"],
        "group": _group_name(str(target["name"])),
        "target": {
            "path_id": target["path_id"],
            "texture_name": target["texture_name"],
            "rect_x": target.get("rect_x", 0.0),
            "rect_y": target.get("rect_y", 0.0),
            "width": target["width"],
            "height": target["height"],
            "pivot_x": target["pivot_x"],
            "pivot_y": target["pivot_y"],
            "pivot_px_x": target_pivot[0],
            "pivot_px_y": target_pivot[1],
            "pixels_per_unit": target["pixels_per_unit"],
        },
    }
    if source is None:
        return {
            **base,
            "action": "KEEP_CRUSADER",
            "confidence": 1.0,
            "reason": "No same-name SH1DE sprite; keep the functional target fallback",
            "source": None,
            "transform": None,
        }

    source_pivot = _absolute_pivot(source)
    paste_left = target_pivot[0] - source_pivot[0]
    paste_bottom = target_pivot[1] - source_pivot[1]
    placed_right = paste_left + float(source["width"])
    placed_top = paste_bottom + float(source["height"])
    same_atlas = source["texture_name"] == target["texture_name"]
    exact_geometry = _geometry_equal(source, target)
    if not same_atlas:
        action = "REVIEW_MANUAL"
        confidence = 0.5
        reason = "Same sprite name but different source/target atlas"
    elif exact_geometry:
        action = "REPLACE_EXACT"
        confidence = 1.0
        reason = "Same semantic name, atlas, dimensions, absolute pivot, and PPU"
    else:
        action = "REPLACE_DERIVED"
        confidence = 0.95
        reason = "Same semantic name and atlas; adapt source pixels to target geometry"

    return {
        **base,
        "action": action,
        "confidence": confidence,
        "reason": reason,
        "source": {
            "path_id": source["path_id"],
            "texture_name": source["texture_name"],
            "rect_x": source.get("rect_x", 0.0),
            "rect_y": source.get("rect_y", 0.0),
            "width": source["width"],
            "height": source["height"],
            "pivot_x": source["pivot_x"],
            "pivot_y": source["pivot_y"],
            "pivot_px_x": source_pivot[0],
            "pivot_px_y": source_pivot[1],
            "pixels_per_unit": source["pixels_per_unit"],
        },
        "transform": {
            "paste_left": paste_left,
            "paste_bottom": paste_bottom,
            "placed_right": placed_right,
            "placed_top": placed_top,
            "geometric_clip_risk": (
                paste_left < -GEOMETRY_TOLERANCE
                or paste_bottom < -GEOMETRY_TOLERANCE
                or placed_right > float(target["width"]) + GEOMETRY_TOLERANCE
                or placed_top > float(target["height"]) + GEOMETRY_TOLERANCE
            ),
            "resampling": "none",
            "target_metadata_authoritative": True,
        },
    }


def keep_crusader(proposal: dict[str, Any]) -> dict[str, Any]:
    """Return `proposal` stripped of its donor, as a Crusader-only frame.

    The same shape `_proposal` produces when SH1DE has no sprite of that name,
    so every downstream check - the approved-action gate, the keep partition,
    the provenance digest, the builder's copy path - sees a case it already
    knows.  Used where a donor exists but is unfit for the slot; the reason is
    carried so the built mod can say why a frame stayed Crusader.
    """

    return {
        "name": proposal["name"],
        "group": proposal["group"],
        "target": proposal["target"],
        "action": "KEEP_CRUSADER",
        "confidence": 1.0,
        "reason": "Frame override: the SH1DE donor is unfit for this slot",
        "source": None,
        "transform": None,
    }


def redirect_source(
    proposal: dict[str, Any], donor: dict[str, Any]
) -> dict[str, Any]:
    """Return `proposal` with a different SH1DE donor, transform recomputed.

    `donor` is the `source` block of another proposal, so the paste offsets and
    the clip risk are derived by the same arithmetic that produced them in the
    first place rather than by a second copy of it.
    """

    target = {**proposal["target"], "name": proposal["name"]}
    return _proposal(donor, target)


def propose_mappings(
    source_inventory: dict[str, Any],
    target_inventory: dict[str, Any],
    source_build_id: str,
    target_build_id: str,
) -> dict[str, Any]:
    source_by_name = {sprite["name"]: sprite for sprite in source_inventory["sprites"]}
    proposals = [
        _proposal(source_by_name.get(target["name"]), target)
        for target in target_inventory["sprites"]
    ]
    action_counts = Counter(item["action"] for item in proposals)
    atlas_counts: dict[str, Counter[str]] = defaultdict(Counter)
    group_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for item in proposals:
        atlas_counts[item["target"]["texture_name"]][item["action"]] += 1
        group_counts[item["group"]][item["action"]] += 1

    source_audio = {clip["name"]: clip for clip in source_inventory["audio_clips"]}
    target_audio_names = {clip["name"] for clip in target_inventory["audio_clips"]}
    audio = []
    for target_clip in target_inventory["audio_clips"]:
        source_clip = source_audio.get(target_clip["name"])
        audio.append(
            {
                "name": target_clip["name"],
                "action": "KEEP_CRUSADER",
                "reason": (
                    "Same-name SH1DE audio exists, but target audio remains authoritative; "
                    "shared speech is commonly higher-rate in SHCDE"
                    if source_clip
                    else "No same-name SH1DE audio"
                ),
                "shared_source_available": source_clip is not None,
                "source_path_id": source_clip["path_id"] if source_clip else None,
                "target_path_id": target_clip["path_id"],
                "source": source_clip,
                "target": target_clip,
            }
        )

    source_only_audio = []
    for source_clip in source_inventory["audio_clips"]:
        if source_clip["name"] in target_audio_names:
            continue
        is_europe_music = source_clip["name"].casefold() in EUROPE_MUSIC_SOURCE_NAMES
        source_only_audio.append(
            {
                "name": source_clip["name"],
                "action": "EUROPE_MUSIC_SOURCE" if is_europe_music else "REVIEW_SOURCE_ONLY",
                "source": source_clip,
            }
        )

    return {
        "schema_version": 2,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_build_id": source_build_id,
        "target_build_id": target_build_id,
        "sprite_summary": {
            "source_count": len(source_inventory["sprites"]),
            "target_count": len(target_inventory["sprites"]),
            "action_counts": dict(sorted(action_counts.items())),
            "atlas_counts": {
                atlas: dict(sorted(counts.items()))
                for atlas, counts in sorted(atlas_counts.items())
            },
            "group_counts": {
                group: dict(sorted(counts.items()))
                for group, counts in sorted(group_counts.items())
            },
        },
        "sprites": proposals,
        "audio_clips": audio,
        "source_only_audio": source_only_audio,
    }


def write_mapping(mapping: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    with gzip.open(temporary, "wt", encoding="utf-8", newline="\n") as stream:
        json.dump(mapping, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        stream.write("\n")
    temporary.replace(output_path)


def read_mapping(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        mapping = json.load(stream)
    if mapping.get("schema_version") != 2:
        raise ValueError(f"Unsupported mapping schema: {mapping.get('schema_version')}")
    return mapping


def write_mapping_report(mapping: dict[str, Any], output_path: Path) -> None:
    summary = mapping["sprite_summary"]
    lines = [
        "# Generated mapping summary",
        "",
        f"- Source build: `{mapping['source_build_id']}`",
        f"- Target build: `{mapping['target_build_id']}`",
        f"- Source sprites: {summary['source_count']:,}",
        f"- Target sprites: {summary['target_count']:,}",
        "",
        "## Actions",
        "",
        "| Action | Count |",
        "|---|---:|",
    ]
    for action, count in summary["action_counts"].items():
        lines.append(f"| `{action}` | {count:,} |")
    lines.extend(
        [
            "",
            "## Atlas breakdown",
            "",
            "| Atlas | REPLACE_EXACT | REPLACE_DERIVED | REVIEW_MANUAL | KEEP_CRUSADER |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for atlas, counts in summary["atlas_counts"].items():
        lines.append(
            f"| `{atlas or '(none)'}` | {counts.get('REPLACE_EXACT', 0):,} | "
            f"{counts.get('REPLACE_DERIVED', 0):,} | {counts.get('REVIEW_MANUAL', 0):,} | "
            f"{counts.get('KEEP_CRUSADER', 0):,} |"
        )
    lines.extend(
        [
            "",
            "`REPLACE_DERIVED` is only a geometry candidate. Pixel extraction must prove",
            "that pivot-aligned placement does not clip non-transparent source pixels.",
            "",
        ]
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")


def build_mapping_from_files(
    source_path: Path,
    target_path: Path,
    output_path: Path,
    report_path: Path,
    source_build_id: str,
    target_build_id: str,
) -> dict[str, Any]:
    mapping = propose_mappings(
        read_inventory(source_path),
        read_inventory(target_path),
        source_build_id,
        target_build_id,
    )
    write_mapping(mapping, output_path)
    write_mapping_report(mapping, report_path)
    return mapping

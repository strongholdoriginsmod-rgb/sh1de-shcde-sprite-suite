from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Iterable

from .mapping import _group_name


def _grouped_names(sprites: Iterable[dict[str, Any]]) -> dict[str, set[str]]:
    grouped: dict[str, set[str]] = defaultdict(set)
    for sprite in sprites:
        grouped[_group_name(str(sprite["name"]))].add(str(sprite["name"]))
    return dict(grouped)


def _relation(source: set[str], target: set[str]) -> str:
    if source and target and source == target:
        return "EXACT_NAME_SET"
    if source and source < target:
        return "SOURCE_SUBSET"
    if target and target < source:
        return "TARGET_SUBSET"
    if source and target:
        return "DIVERGED"
    if target:
        return "TARGET_EXCLUSIVE"
    return "SOURCE_EXCLUSIVE"


def _category(group: str) -> str:
    if group.startswith("tile_") or group in {
        "killing_pits",
        "pitch_ditches",
        "rock_chips",
        "cracks",
    }:
        return "terrain_buildings"
    if group.startswith(("tree_", "Tree_")):
        return "vegetation"
    if group.startswith("anim_"):
        return "animation"
    if group.startswith("body_"):
        return "body"
    return "technical_effect"


def _production_gate(
    relation: str,
    action_counts: Counter[str],
    target_count: int,
) -> str:
    if relation == "SOURCE_EXCLUSIVE":
        return "SOURCE_REFERENCE_ONLY"
    if relation == "TARGET_EXCLUSIVE":
        return "KEEP_CRUSADER_REQUIRED"
    if action_counts["REVIEW_MANUAL"]:
        return "REVIEW_ATLAS_MISMATCH"
    if relation == "DIVERGED":
        return "MANUAL_FRAME_POLICY"
    if relation == "SOURCE_SUBSET":
        return "PARTIAL_REPLACE_KEEP_TARGET_ONLY"
    if relation == "TARGET_SUBSET":
        return "IGNORE_SOURCE_ONLY_FRAMES"
    if action_counts["KEEP_CRUSADER"]:
        return "KEEP_CRUSADER_REQUIRED"
    if action_counts["REPLACE_DERIVED"]:
        return "DERIVED_REQUIRES_PIXEL_PROOF"
    if action_counts["REPLACE_EXACT"] == target_count:
        return "EXACT_ATLAS_CANDIDATE"
    return "REVIEW_MANUAL"


def audit_groups(
    mapping: dict[str, Any],
    source_inventory: dict[str, Any],
    target_inventory: dict[str, Any],
) -> dict[str, Any]:
    source_names = _grouped_names(source_inventory["sprites"])
    target_names = _grouped_names(target_inventory["sprites"])
    proposals: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for proposal in mapping["sprites"]:
        proposals[str(proposal["group"])].append(proposal)

    source_textures = {str(item["name"]) for item in source_inventory["textures"]}
    groups: list[dict[str, Any]] = []
    for group in sorted(set(source_names) | set(target_names)):
        source = source_names.get(group, set())
        target = target_names.get(group, set())
        relation = _relation(source, target)
        rows = proposals.get(group, [])
        action_counts = Counter(str(row["action"]) for row in rows)
        source_atlases = sorted(
            {
                str(row["source"]["texture_name"])
                for row in rows
                if row.get("source") is not None
            }
        )
        target_atlases = sorted(
            {str(row["target"]["texture_name"]) for row in rows}
        )
        groups.append(
            {
                "group": group,
                "category": _category(group),
                "relation": relation,
                "production_gate": _production_gate(
                    relation, action_counts, len(target)
                ),
                "source_count": len(source),
                "target_count": len(target),
                "common_count": len(source & target),
                "source_only_count": len(source - target),
                "target_only_count": len(target - source),
                "source_atlases": source_atlases,
                "target_atlases": target_atlases,
                "source_mask_available": bool(source_atlases)
                and all(atlas + "_m" in source_textures for atlas in source_atlases),
                "actions": dict(sorted(action_counts.items())),
            }
        )

    relation_counts = Counter(item["relation"] for item in groups)
    gate_counts = Counter(item["production_gate"] for item in groups)
    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_build_id": mapping["source_build_id"],
        "target_build_id": mapping["target_build_id"],
        "summary": {
            "group_count": len(groups),
            "relation_counts": dict(sorted(relation_counts.items())),
            "production_gate_counts": dict(sorted(gate_counts.items())),
        },
        "groups": groups,
    }


def write_group_audit(audit: dict[str, Any], json_path: Path, report_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(audit, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    lines = [
        "# Sprite group audit",
        "",
        f"- Source build: `{audit['source_build_id']}`",
        f"- Target build: `{audit['target_build_id']}`",
        f"- Groups in union: {audit['summary']['group_count']:,}",
        "",
        "## Production gates",
        "",
        "| Gate | Groups |",
        "|---|---:|",
    ]
    for gate, count in audit["summary"]["production_gate_counts"].items():
        lines.append(f"| `{gate}` | {count:,} |")
    lines.extend(
        [
            "",
            "## Group matrix",
            "",
            "| Group | Category | Relation | Source | Target | Common | Gate | Mask |",
            "|---|---|---|---:|---:|---:|---|---|",
        ]
    )
    for item in audit["groups"]:
        lines.append(
            f"| `{item['group']}` | {item['category']} | `{item['relation']}` | "
            f"{item['source_count']:,} | {item['target_count']:,} | "
            f"{item['common_count']:,} | `{item['production_gate']}` | "
            f"{'yes' if item['source_mask_available'] else 'no'} |"
        )
    lines.extend(
        [
            "",
            "`KEEP_CRUSADER_REQUIRED` is an explicit compatibility decision, not a",
            "missing conversion. No target-only frame may become transparent or be",
            "removed from the target sprite arrays.",
            "",
        ]
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")

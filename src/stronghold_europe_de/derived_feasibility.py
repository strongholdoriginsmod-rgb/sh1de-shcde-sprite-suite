from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import gc
import json
from math import ceil, floor, isfinite
from pathlib import Path
import re
from typing import Any, Callable, Iterable

from PIL import Image

from .unity_inventory import _import_unitypy, load_unity_asset


class DerivedFeasibilityError(ValueError):
    """Raised when a derived-frame proof cannot be performed safely."""


OFFSET_TOLERANCE = 1e-3
PLACEMENT_PROOF_ALGORITHM = "integral_target_pivot_main_alpha_support_v1"


def _loader_frame_sort_key(item: dict[str, Any]) -> tuple[int, bool, str]:
    """Sort proof rows by their real GM array slot, never lexicographically."""

    name = str(item.get("name", ""))
    group = str(item.get("group", ""))
    for separator in ("-", " "):
        prefix = group + separator
        if name.startswith(prefix):
            match = re.fullmatch(r"([0-9]+)(x?)", name[len(prefix) :])
            if match is not None:
                return int(match.group(1)), bool(match.group(2)), name
    raise DerivedFeasibilityError(
        f"Cannot derive loader slot from feasibility frame: {name!r}"
    )


@dataclass(frozen=True)
class OffsetCandidate:
    paste_left: int
    paste_bottom: int
    residual_x: float
    residual_y: float
    main_lost_alpha: int
    mask_lost_alpha: int

    @property
    def lossless(self) -> bool:
        return self.main_lost_alpha == 0 and self.mask_lost_alpha == 0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["lossless"] = self.lossless
        return data


def _integer_dimension(value: Any, label: str) -> int:
    number = float(value)
    rounded = round(number)
    if not isfinite(number) or abs(number - rounded) > OFFSET_TOLERANCE or rounded <= 0:
        raise DerivedFeasibilityError(f"Invalid non-integral {label}: {value}")
    return int(rounded)


def _axis_candidates(value: float) -> tuple[int, ...]:
    if not isfinite(value):
        raise DerivedFeasibilityError(f"Non-finite ideal offset: {value}")
    rounded = round(value)
    if abs(value - rounded) <= OFFSET_TOLERANCE:
        return (int(rounded),)
    return tuple(sorted({floor(value), ceil(value)}))


def nearest_integral_offsets(
    ideal_left: float,
    ideal_bottom: float,
) -> tuple[tuple[int, int], ...]:
    """Return every nearest pixel-grid placement around an ideal pivot offset.

    Fractional pixel art is never resampled.  A half-pixel axis therefore has
    two candidates and two half-pixel axes have four.  More distant offsets are
    intentionally excluded: they would introduce avoidable anchor error.
    """

    offsets = [
        (left, bottom)
        for left in _axis_candidates(ideal_left)
        for bottom in _axis_candidates(ideal_bottom)
    ]
    return tuple(
        sorted(
            offsets,
            key=lambda item: (
                (item[0] - ideal_left) ** 2 + (item[1] - ideal_bottom) ** 2,
                item[0],
                item[1],
            ),
        )
    )


def alpha_sum(image: Image.Image) -> int:
    return sum(image.convert("RGBA").getchannel("A").get_flattened_data())


def alpha_bbox_bottom_left(image: Image.Image) -> dict[str, int] | None:
    rgba = image.convert("RGBA")
    bbox = rgba.getchannel("A").getbbox()
    if bbox is None:
        return None
    left, top, right, bottom = bbox
    return {
        "left": left,
        "bottom": rgba.height - bottom,
        "right": right,
        "top": rgba.height - top,
    }


def alpha_loss_at_offset(
    image: Image.Image,
    target_size: tuple[int, int],
    paste_left: int,
    paste_bottom: int,
) -> int:
    """Measure alpha clipped by a bottom-left-relative integer placement."""

    rgba = image.convert("RGBA")
    target_width, target_height = target_size
    if target_width <= 0 or target_height <= 0:
        raise DerivedFeasibilityError(f"Invalid target size: {target_size}")

    source_left = max(0, -paste_left)
    source_bottom = max(0, -paste_bottom)
    source_right = min(rgba.width, target_width - paste_left)
    source_top = min(rgba.height, target_height - paste_bottom)
    visible_alpha = 0
    if source_right > source_left and source_top > source_bottom:
        pil_top = rgba.height - source_top
        pil_bottom = rgba.height - source_bottom
        visible_alpha = alpha_sum(
            rgba.crop((source_left, pil_top, source_right, pil_bottom))
        )
    return alpha_sum(rgba) - visible_alpha


def assess_derived_sprite(
    source_image: Image.Image,
    proposal: dict[str, Any],
    source_mask: Image.Image | None = None,
) -> dict[str, Any]:
    if proposal.get("action") != "REPLACE_DERIVED":
        raise DerivedFeasibilityError(
            f"Expected REPLACE_DERIVED proposal: {proposal.get('name')!r}"
        )
    source_meta = proposal.get("source")
    target_meta = proposal.get("target")
    if not isinstance(source_meta, dict) or not isinstance(target_meta, dict):
        raise DerivedFeasibilityError("Derived proposal is missing source/target metadata")

    source_width = _integer_dimension(source_meta["width"], "source width")
    source_height = _integer_dimension(source_meta["height"], "source height")
    target_width = _integer_dimension(target_meta["width"], "target width")
    target_height = _integer_dimension(target_meta["height"], "target height")
    rgba = source_image.convert("RGBA")
    if rgba.size != (source_width, source_height):
        raise DerivedFeasibilityError(
            f"Decoded source size for {proposal.get('name')} is {rgba.size}, "
            f"expected {(source_width, source_height)}"
        )
    mask_rgba = None
    if source_mask is not None:
        mask_rgba = source_mask.convert("RGBA")
        if mask_rgba.size != rgba.size:
            raise DerivedFeasibilityError(
                f"Mask size for {proposal.get('name')} is {mask_rgba.size}, "
                f"expected {rgba.size}"
            )
        # Team-mask texels are sampled only where the main sprite contributes
        # alpha.  Mask atlases commonly contain opaque padding/background data;
        # treating that invisible padding as renderable would create false
        # clipping failures for otherwise lossless target-authoritative crops.
        # Preserve the mask pixels themselves, but measure their relevance with
        # the complete (including partially transparent) main-alpha support.
        mask_rgba.putalpha(rgba.getchannel("A"))

    ideal_left = (
        float(target_meta["pivot_x"]) * target_width
        - float(source_meta["pivot_x"]) * source_width
    )
    ideal_bottom = (
        float(target_meta["pivot_y"]) * target_height
        - float(source_meta["pivot_y"]) * source_height
    )
    # Stronghold 1 fuehrt fuer dieselbe Bildsorte zwei Pivot-Konventionen, und
    # das ist gemessen, nicht vermutet: In anim_castle tragen die Turmschaefte
    # 49-76 auf beiden Seiten pivot_y = 0.0 und setzen sich verlustfrei um,
    # waehrend die Schaefte 94-121 - gleiche Motivsorte, gleiche Masse - auf der
    # Quellseite pivot_y = 1.0 tragen. Fuer sie rechnet die Formel
    # ideal_bottom = 0*h - 1*h = -h; das Bild landet vollstaendig UNTER dem
    # Zielrechteck, verliert sein gesamtes Alpha und faellt als
    # BLOCKED_ALPHA_CLIP auf die Crusader-Kachel zurueck. Sichtbar ist das als
    # Bruch innerhalb eines Turms: grauer Kalkstein neben gelbem Sandstein.
    #
    # Traegt die Quelle ihren Anker an der GEGENUEBERLIEGENDEN Kante und sind
    # die Bilder gleich hoch, ist das kein Versatz, sondern eine andere
    # Schreibweise fuer denselben Anker - die Leinwaende decken sich. Die
    # Bedingung ist absichtlich so eng: Sie greift nur, wo die bisherige
    # Rechnung nachweislich das ganze Bild verwirft, und laesst jede
    # Groessenabweichung unberuehrt (anim_castle 117 ist 190 gegen 188 hoch und
    # bleibt deshalb blockiert).
    if (
        source_height == target_height
        and float(source_meta["pivot_y"]) == 1.0
        and float(target_meta["pivot_y"]) == 0.0
    ):
        ideal_bottom = 0.0
    integral = (
        abs(ideal_left - round(ideal_left)) <= OFFSET_TOLERANCE
        and abs(ideal_bottom - round(ideal_bottom)) <= OFFSET_TOLERANCE
    )

    candidates: list[OffsetCandidate] = []
    for left, bottom in nearest_integral_offsets(ideal_left, ideal_bottom):
        candidates.append(
            OffsetCandidate(
                paste_left=left,
                paste_bottom=bottom,
                residual_x=left - ideal_left,
                residual_y=bottom - ideal_bottom,
                main_lost_alpha=alpha_loss_at_offset(
                    rgba, (target_width, target_height), left, bottom
                ),
                mask_lost_alpha=(
                    alpha_loss_at_offset(
                        mask_rgba, (target_width, target_height), left, bottom
                    )
                    if mask_rgba is not None
                    else 0
                ),
            )
        )

    lossless = [candidate for candidate in candidates if candidate.lossless]
    if not lossless:
        status = "BLOCKED_ALPHA_CLIP"
        chosen = None
    elif integral:
        status = "AUTO_LOSSLESS_INTEGRAL"
        chosen = lossless[0]
    else:
        status = "REVIEW_LOSSLESS_FRACTIONAL"
        chosen = None

    return {
        "name": str(proposal["name"]),
        "group": str(proposal["group"]),
        "source_path_id": int(source_meta["path_id"]),
        "source_texture": str(source_meta["texture_name"]),
        "source_size": [source_width, source_height],
        "target_size": [target_width, target_height],
        "ideal_offset": {"left": ideal_left, "bottom": ideal_bottom},
        "ideal_offset_integral": integral,
        "main_alpha_sum": alpha_sum(rgba),
        "main_alpha_bbox": alpha_bbox_bottom_left(rgba),
        "mask_checked": mask_rgba is not None,
        "mask_relevance": (
            "main_alpha_support" if mask_rgba is not None else None
        ),
        "mask_alpha_sum": alpha_sum(mask_rgba) if mask_rgba is not None else None,
        "mask_alpha_bbox": (
            alpha_bbox_bottom_left(mask_rgba) if mask_rgba is not None else None
        ),
        "status": status,
        "chosen_offset": chosen.to_dict() if chosen is not None else None,
        "candidates": [candidate.to_dict() for candidate in candidates],
    }


def summarize_assessments(
    mapping: dict[str, Any],
    assessments: Iterable[dict[str, Any]],
    selected_groups: Iterable[str],
    *,
    placement_action: str = "REPLACE_DERIVED",
) -> dict[str, Any]:
    selected = set(selected_groups)
    by_group: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for assessment in assessments:
        by_group[str(assessment["group"])].append(assessment)

    mapping_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for proposal in mapping["sprites"]:
        group = str(proposal["group"])
        if group in selected:
            mapping_counts[group][str(proposal["action"])] += 1

    group_rows = []
    for group in sorted(selected):
        rows = sorted(by_group.get(group, []), key=_loader_frame_sort_key)
        statuses = Counter(str(row["status"]) for row in rows)
        if statuses.get("BLOCKED_ALPHA_CLIP"):
            decision = "BLOCKED"
        elif statuses.get("REVIEW_LOSSLESS_FRACTIONAL"):
            decision = "REVIEW_FRACTIONAL"
        else:
            decision = "AUTO_LOSSLESS"
        group_rows.append(
            {
                "group": group,
                "mapping_actions": dict(sorted(mapping_counts[group].items())),
                "derived_statuses": dict(sorted(statuses.items())),
                "decision": decision,
                "derived_frames": rows,
            }
        )

    decisions = Counter(row["decision"] for row in group_rows)
    statuses = Counter(
        assessment["status"]
        for rows in by_group.values()
        for assessment in rows
    )
    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_build_id": mapping["source_build_id"],
        "target_build_id": mapping["target_build_id"],
        "placement_action": placement_action,
        "proof_algorithm": PLACEMENT_PROOF_ALGORITHM,
        "summary": {
            "selected_group_count": len(selected),
            "derived_frame_count": sum(statuses.values()),
            "derived_statuses": dict(sorted(statuses.items())),
            "group_decisions": dict(sorted(decisions.items())),
        },
        "groups": group_rows,
    }


ImageProvider = Callable[[dict[str, Any]], tuple[Image.Image, Image.Image | None]]


def assess_mapping_groups(
    mapping: dict[str, Any],
    selected_groups: Iterable[str],
    image_provider: ImageProvider,
    *,
    placement_action: str = "REPLACE_DERIVED",
    ignored_actions: Iterable[str] = ("REPLACE_EXACT",),
) -> dict[str, Any]:
    """Decode and prove only the derived frames in complete selected groups.

    Exact same-geometry frames need no pixel placement proof.  Restricting the
    provider calls to ``REPLACE_DERIVED`` keeps large Unity atlases practical
    while the mapping action counts still make the whole-group scope explicit.
    """

    selected = tuple(dict.fromkeys(str(group) for group in selected_groups))
    if not selected or any(not group for group in selected):
        raise DerivedFeasibilityError("At least one non-empty group is required")
    selected_set = set(selected)
    proposals = [
        proposal
        for proposal in mapping.get("sprites", [])
        if str(proposal.get("group", "")) in selected_set
    ]
    present = {str(proposal["group"]) for proposal in proposals}
    missing = sorted(selected_set - present)
    if missing:
        raise DerivedFeasibilityError(
            f"Selected mapping groups do not exist: {', '.join(missing)}"
        )

    ignored = frozenset(str(action) for action in ignored_actions)
    if not placement_action or placement_action in ignored:
        raise DerivedFeasibilityError("Placement action/ignored actions overlap")

    assessments = []
    for proposal in proposals:
        action = str(proposal.get("action", ""))
        if action == placement_action:
            if proposal.get("source") is None:
                raise DerivedFeasibilityError(
                    f"Derived proposal has no source: {proposal.get('name')}"
                )
            source_image, source_mask = image_provider(proposal)
            proof_proposal = proposal
            if placement_action != "REPLACE_DERIVED":
                proof_proposal = {**proposal, "action": "REPLACE_DERIVED"}
            assessments.append(
                assess_derived_sprite(source_image, proof_proposal, source_mask)
            )
        elif action not in ignored:
            raise DerivedFeasibilityError(
                f"Group {proposal.get('group')} contains non-portable action "
                f"{action} for {proposal.get('name')}"
            )
    return summarize_assessments(
        mapping,
        assessments,
        selected,
        placement_action=placement_action,
    )


def _scan_unity_placement_groups(
    source_asset_path: Path,
    mapping: dict[str, Any],
    selected_groups: Iterable[str],
    *,
    placement_action: str,
    ignored_actions: Iterable[str],
) -> dict[str, Any]:
    """Read SH1DE sprites once and produce a metadata-only feasibility proof."""

    if not source_asset_path.is_file():
        raise FileNotFoundError(source_asset_path)
    UnityPy = _import_unitypy()
    environment = load_unity_asset(source_asset_path, unitypy=UnityPy)
    by_id = {int(obj.path_id): obj for obj in environment.objects}
    texture_objects: dict[str, Any] = {}
    texture_trees: dict[str, dict[str, Any]] = {}
    for obj in environment.objects:
        if obj.type.name != "Texture2D":
            continue
        tree = obj.read_typetree()
        name = str(tree.get("m_Name", ""))
        texture_objects[name] = obj
        texture_trees[name] = tree
    mask_cache: dict[str, Image.Image] = {}

    def crop_mask(
        mask: Image.Image,
        main_tree: dict[str, Any],
        sprite_tree: dict[str, Any],
        logical_size: tuple[int, int],
    ) -> Image.Image:
        main_width = int(main_tree["m_Width"])
        main_height = int(main_tree["m_Height"])
        scale_x = mask.width / main_width
        scale_y = mask.height / main_height
        rect = sprite_tree["m_Rect"]
        left = round(float(rect["x"]) * scale_x)
        right = round((float(rect["x"]) + float(rect["width"])) * scale_x)
        bottom = round(float(rect["y"]) * scale_y)
        top_from_bottom = round(
            (float(rect["y"]) + float(rect["height"])) * scale_y
        )
        result = mask.crop(
            (left, mask.height - top_from_bottom, right, mask.height - bottom)
        )
        if result.size != logical_size:
            result = result.resize(logical_size, Image.Resampling.NEAREST)
        return result

    def provide(
        proposal: dict[str, Any],
    ) -> tuple[Image.Image, Image.Image | None]:
        source = proposal["source"]
        path_id = int(source["path_id"])
        obj = by_id.get(path_id)
        if obj is None or obj.type.name != "Sprite":
            raise DerivedFeasibilityError(
                f"Source Sprite PathID is missing for {proposal['name']}: {path_id}"
            )
        data = obj.read()
        if str(data.m_Name) != str(proposal["name"]):
            raise DerivedFeasibilityError(
                f"Source PathID/name mismatch: {data.m_Name} != {proposal['name']}"
            )
        texture_name = str(source["texture_name"])
        main_tree = texture_trees.get(texture_name)
        if main_tree is None:
            raise DerivedFeasibilityError(
                f"Source Texture2D is missing for {proposal['name']}: {texture_name}"
            )
        source_mask = None
        mask_name = texture_name + "_m"
        mask_obj = texture_objects.get(mask_name)
        if mask_obj is not None:
            if mask_name not in mask_cache:
                mask_cache[mask_name] = mask_obj.read().image.convert("RGBA")
            logical_size = (
                _integer_dimension(source["width"], "source mask width"),
                _integer_dimension(source["height"], "source mask height"),
            )
            source_mask = crop_mask(
                mask_cache[mask_name],
                main_tree,
                obj.read_typetree(),
                logical_size,
            )
        return data.image.convert("RGBA"), source_mask

    try:
        return assess_mapping_groups(
            mapping,
            selected_groups,
            provide,
            placement_action=placement_action,
            ignored_actions=ignored_actions,
        )
    finally:
        del mask_cache
        del texture_objects
        del texture_trees
        del by_id
        del environment
        gc.collect()


def scan_unity_derived_groups(
    source_asset_path: Path,
    mapping: dict[str, Any],
    selected_groups: Iterable[str],
) -> dict[str, Any]:
    """Prove mapped ``REPLACE_DERIVED`` placements without weakening review gates."""

    return _scan_unity_placement_groups(
        source_asset_path,
        mapping,
        selected_groups,
        placement_action="REPLACE_DERIVED",
        ignored_actions=("REPLACE_EXACT",),
    )


def scan_unity_review_groups(
    source_asset_path: Path,
    mapping: dict[str, Any],
    selected_groups: Iterable[str],
) -> dict[str, Any]:
    """Measure manual atlas-mismatch placements; never promotes them by itself."""

    return _scan_unity_placement_groups(
        source_asset_path,
        mapping,
        selected_groups,
        placement_action="REVIEW_MANUAL",
        ignored_actions=("KEEP_CRUSADER",),
    )


def write_feasibility_report(
    report: dict[str, Any],
    json_path: Path,
    markdown_path: Path,
) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = json_path.with_suffix(json_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(json_path)

    summary = report["summary"]
    placement_action = str(report.get("placement_action", "REPLACE_DERIVED"))
    title = (
        "Atlas-mismatch geometry feasibility"
        if placement_action == "REVIEW_MANUAL"
        else "Derived geometry feasibility"
    )
    lines = [
        f"# {title}",
        "",
        f"- Groups checked: {summary['selected_group_count']:,}",
        f"- Derived frames decoded: {summary['derived_frame_count']:,}",
        f"- Placement action: `{placement_action}`",
        "",
        "| Group | Exact | Derived | Decision |",
        "|---|---:|---:|---|",
    ]
    for group in report["groups"]:
        actions = group["mapping_actions"]
        lines.append(
            f"| `{group['group']}` | {actions.get('REPLACE_EXACT', 0):,} | "
            f"{actions.get('REPLACE_DERIVED', 0):,} | `{group['decision']}` |"
        )
    lines.extend(
        [
            "",
            "`AUTO_LOSSLESS` proves zero alpha loss at the exact integral pivot "
            "offset. Fractional offsets remain a manual group-level animation "
            "decision even when one or more nearest placements are lossless.",
            "",
        ]
    )
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text("\n".join(lines), encoding="utf-8")

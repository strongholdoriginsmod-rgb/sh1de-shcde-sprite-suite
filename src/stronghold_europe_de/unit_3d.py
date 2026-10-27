"""Reproducible 3-D unit production for Stronghold sprite families.

The game export is a motion-capture source, never an appearance source.  Only
its alpha, team-mask pixels, canvas, pivot and ordering are admitted to a pose
manifest.  Blender then renders a project-owned model twice from one scene:

* a transparent beauty pass;
* an unlit material-ID pass with identical geometry and camera.

The Stronghold mask is derived from those two renders.  Keeping pose capture,
3-D rendering and delivery finalisation as separate, fingerprinted stages is
intentional: it makes donor-RGB leakage and partially completed exports
structurally impossible.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
from types import SimpleNamespace
from typing import Any, Iterable, Mapping, Sequence

from PIL import Image

from .unit_production import Pose, UnitProductionError, extract_pose


SPEC_SCHEMA = 2
POSE_MANIFEST_SCHEMA = 1
RENDER_REPORT_SCHEMA = 1
HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
ALLOWED_GENERATED_ROOTS = frozenset({"work", "cache", "state", "dist"})
MATERIAL_ROLES = (
    "background",
    "skin",
    "felt",
    "team",
    "cloth",
    "leather",
    "metal",
    "stone",
    "shadow",
    "blood",
)


class Unit3DError(UnitProductionError):
    """Raised before a changed toolchain or incomplete 3-D frame set can ship."""


Point = tuple[float, float]
RGBA = tuple[int, int, int, int]


@dataclass(frozen=True)
class ReferenceAsset:
    path: Path
    sha256: str
    purpose: str


@dataclass(frozen=True)
class BlenderContract:
    version: str
    build_hash: str
    executable_sha256: str
    portable_archive_sha256: str


@dataclass(frozen=True)
class Unit3DSpec:
    path: Path
    project_root: Path
    unit_id: str
    display_name: str
    group: str
    expected_frames: int
    expected_main: int
    expected_alternate: int
    references: tuple[ReferenceAsset, ...]
    headwear: str
    wearer_right_equipment: str
    wearer_left_equipment: str
    direction_map: tuple[int, ...]
    pose_extractor: str
    pose_proportions: Mapping[str, float]
    model_recipe: Path
    model_recipe_sha256: str
    model_contract: str
    model_height_m: float
    required_objects: tuple[str, ...]
    blender: BlenderContract
    engine: str
    supersample: int
    samples: int
    transparent: bool
    camera_contract: str
    colour_management: str
    material_ids: Mapping[str, RGBA]
    mask_background: RGBA
    mask_team_role: str
    mask_visible_blue: int
    mask_pivot_green: float
    mask_green_per_pixel: float
    min_pose_confidence: float
    max_border_ratio: float
    max_empty_alpha_ratio: float
    max_id_unclassified_ratio: float


@dataclass(frozen=True)
class PoseFrame:
    name: str
    file: str
    mask_file: str
    slot: int
    alternate: bool
    direction: int
    reference_direction: int
    width: int
    height: int
    pivot_x: float
    pivot_y: float
    pixels_per_unit: float
    confidence: float
    lying: bool
    action_hint: str
    source_alpha_sha256: str
    source_mask_sha256: str
    landmarks: Mapping[str, Point | None]


@dataclass(frozen=True)
class PoseManifestReport:
    path: Path
    frame_count: int
    main_count: int
    alternate_count: int
    source_index_sha256: str
    source_motion_sha256: str
    min_pose_confidence: float


@dataclass(frozen=True)
class FinalizedFrameStats:
    name: str
    width: int
    height: int
    visible_pixels: int
    team_pixels: int
    border_pixels: int
    border_ratio: float
    id_unclassified_subpixels: int
    id_unclassified_ratio: float
    team_non_neutral_subpixels: int
    colour_pixels_sha256: str
    mask_pixels_sha256: str


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_object(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise Unit3DError(f"{label}: expected object")
    return value


def _require_exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    present = set(value)
    if present != expected:
        missing = sorted(expected - present)
        extra = sorted(present - expected)
        raise Unit3DError(f"{label}: key mismatch; missing={missing}, extra={extra}")


def _integer(value: Any, label: str, *, minimum: int = 0, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise Unit3DError(f"{label}: expected integer >= {minimum}")
    if maximum is not None and value > maximum:
        raise Unit3DError(f"{label}: expected integer <= {maximum}")
    return value


def _number(value: Any, label: str, *, minimum: float = 0.0, maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise Unit3DError(f"{label}: expected number")
    result = float(value)
    if not math.isfinite(result) or result < minimum:
        raise Unit3DError(f"{label}: expected finite number >= {minimum}")
    if maximum is not None and result > maximum:
        raise Unit3DError(f"{label}: expected number <= {maximum}")
    return result


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise Unit3DError(f"{label}: expected non-empty string")
    return value


def _sha(value: Any, label: str) -> str:
    result = _string(value, label)
    if not HEX_SHA256.fullmatch(result):
        raise Unit3DError(f"{label}: expected lowercase SHA-256")
    return result


def _rgba(value: Any, label: str) -> RGBA:
    if (
        not isinstance(value, list)
        or len(value) != 4
        or any(isinstance(channel, bool) or not isinstance(channel, int) for channel in value)
        or any(channel < 0 or channel > 255 for channel in value)
    ):
        raise Unit3DError(f"{label}: expected four byte values")
    return tuple(value)  # type: ignore[return-value]


def _project_path(project_root: Path, relative: Any, label: str) -> Path:
    raw = _string(relative, label)
    path = (project_root / raw).resolve()
    try:
        path.relative_to(project_root)
    except ValueError as exc:
        raise Unit3DError(f"{label}: path escapes project root") from exc
    return path


def load_unit_3d_spec(path: Path, *, project_root: Path | None = None) -> Unit3DSpec:
    """Load and fingerprint a strict schema-2 unit production contract."""

    path = path.resolve()
    root = project_root.resolve() if project_root else path.parents[2]
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Unit3DError(f"Cannot read unit 3-D manifest {path}: {exc}") from exc
    raw = _require_object(raw, "unit manifest")
    _require_exact_keys(
        raw,
        {
            "schema_version",
            "unit_id",
            "display_name",
            "group",
            "expected",
            "art_direction",
            "source_motion",
            "model",
            "render",
            "team_mask",
            "quality",
        },
        "unit manifest",
    )
    if raw["schema_version"] != SPEC_SCHEMA:
        raise Unit3DError(f"Unsupported unit 3-D manifest schema {raw['schema_version']!r}")

    expected = _require_object(raw["expected"], "expected")
    _require_exact_keys(expected, {"frames", "main", "alternate"}, "expected")
    expected_frames = _integer(expected["frames"], "expected.frames", minimum=1)
    expected_main = _integer(expected["main"], "expected.main")
    expected_alt = _integer(expected["alternate"], "expected.alternate")
    if expected_main + expected_alt != expected_frames:
        raise Unit3DError("expected.main + expected.alternate must equal expected.frames")

    art = _require_object(raw["art_direction"], "art_direction")
    _require_exact_keys(
        art,
        {"references", "headwear", "wearer_right_equipment", "wearer_left_equipment"},
        "art_direction",
    )
    references_raw = art["references"]
    if not isinstance(references_raw, list) or not references_raw:
        raise Unit3DError("art_direction.references must be a non-empty list")
    references: list[ReferenceAsset] = []
    for index, item in enumerate(references_raw):
        item = _require_object(item, f"art_direction.references[{index}]")
        _require_exact_keys(item, {"path", "sha256", "purpose"}, f"art_direction.references[{index}]")
        asset_path = _project_path(root, item["path"], f"art_direction.references[{index}].path")
        expected_hash = _sha(item["sha256"], f"art_direction.references[{index}].sha256")
        if not asset_path.is_file():
            raise Unit3DError(f"Missing art-direction reference: {asset_path}")
        actual_hash = sha256_file(asset_path)
        if actual_hash != expected_hash:
            raise Unit3DError(
                f"Reference fingerprint changed for {asset_path}: expected {expected_hash}, found {actual_hash}"
            )
        references.append(
            ReferenceAsset(asset_path, expected_hash, _string(item["purpose"], f"references[{index}].purpose"))
        )
    headwear = _string(art["headwear"], "art_direction.headwear")
    if headwear != "felt_hat":
        raise Unit3DError("European slinger contract requires headwear='felt_hat', never a helmet")

    motion = _require_object(raw["source_motion"], "source_motion")
    _require_exact_keys(
        motion,
        {"allowed_channels", "forbid_rgb", "direction_map", "pose_extractor", "proportions"},
        "source_motion",
    )
    if motion["allowed_channels"] != ["alpha", "team_mask"] or motion["forbid_rgb"] is not True:
        raise Unit3DError("source_motion must admit only alpha/team_mask and explicitly forbid RGB")
    direction_raw = motion["direction_map"]
    if (
        not isinstance(direction_raw, list)
        or len(direction_raw) != 8
        or sorted(direction_raw) != list(range(8))
        or any(isinstance(value, bool) for value in direction_raw)
    ):
        raise Unit3DError("source_motion.direction_map must be a permutation of 0..7")
    proportions_raw = _require_object(motion["proportions"], "source_motion.proportions")
    required_proportions = {"torso_half_width", "shoulder_half_width"}
    _require_exact_keys(proportions_raw, required_proportions, "source_motion.proportions")
    proportions = {
        key: _number(value, f"source_motion.proportions.{key}", minimum=0.001, maximum=0.5)
        for key, value in proportions_raw.items()
    }

    model = _require_object(raw["model"], "model")
    _require_exact_keys(
        model,
        {"recipe", "recipe_sha256", "contract", "height_m", "required_objects"},
        "model",
    )
    recipe = _project_path(root, model["recipe"], "model.recipe")
    recipe_sha = _sha(model["recipe_sha256"], "model.recipe_sha256")
    if not recipe.is_file():
        raise Unit3DError(f"Model recipe is missing: {recipe}")
    actual_recipe_sha = sha256_file(recipe)
    if actual_recipe_sha != recipe_sha:
        raise Unit3DError(
            f"Model recipe fingerprint changed: expected {recipe_sha}, found {actual_recipe_sha}"
        )
    required_objects_raw = model["required_objects"]
    if (
        not isinstance(required_objects_raw, list)
        or not required_objects_raw
        or any(not isinstance(value, str) or not value for value in required_objects_raw)
        or len(required_objects_raw) != len(set(required_objects_raw))
    ):
        raise Unit3DError("model.required_objects must contain unique non-empty names")

    render = _require_object(raw["render"], "render")
    _require_exact_keys(
        render,
        {
            "blender",
            "engine",
            "supersample",
            "samples",
            "transparent",
            "camera_contract",
            "colour_management",
            "material_ids",
        },
        "render",
    )
    blender_raw = _require_object(render["blender"], "render.blender")
    _require_exact_keys(
        blender_raw,
        {"version", "build_hash", "executable_sha256", "portable_archive_sha256"},
        "render.blender",
    )
    material_ids_raw = _require_object(render["material_ids"], "render.material_ids")
    _require_exact_keys(material_ids_raw, set(MATERIAL_ROLES) - {"background"}, "render.material_ids")
    material_ids = {key: _rgba(value, f"render.material_ids.{key}") for key, value in material_ids_raw.items()}
    if len(set(material_ids.values())) != len(material_ids):
        raise Unit3DError("render.material_ids values must be unique")

    mask = _require_object(raw["team_mask"], "team_mask")
    _require_exact_keys(
        mask,
        {"background", "team_role", "visible_blue", "pivot_green", "green_per_pixel"},
        "team_mask",
    )
    team_role = _string(mask["team_role"], "team_mask.team_role")
    if team_role not in material_ids:
        raise Unit3DError("team_mask.team_role is not a render material role")

    quality = _require_object(raw["quality"], "quality")
    _require_exact_keys(
        quality,
        {"min_pose_confidence", "max_border_ratio", "max_empty_alpha_ratio", "max_id_unclassified_ratio"},
        "quality",
    )

    spec = Unit3DSpec(
        path=path,
        project_root=root,
        unit_id=_string(raw["unit_id"], "unit_id"),
        display_name=_string(raw["display_name"], "display_name"),
        group=_string(raw["group"], "group"),
        expected_frames=expected_frames,
        expected_main=expected_main,
        expected_alternate=expected_alt,
        references=tuple(references),
        headwear=headwear,
        wearer_right_equipment=_string(art["wearer_right_equipment"], "art_direction.wearer_right_equipment"),
        wearer_left_equipment=_string(art["wearer_left_equipment"], "art_direction.wearer_left_equipment"),
        direction_map=tuple(direction_raw),
        pose_extractor=_string(motion["pose_extractor"], "source_motion.pose_extractor"),
        pose_proportions=proportions,
        model_recipe=recipe,
        model_recipe_sha256=recipe_sha,
        model_contract=_string(model["contract"], "model.contract"),
        model_height_m=_number(model["height_m"], "model.height_m", minimum=1.0, maximum=2.5),
        required_objects=tuple(required_objects_raw),
        blender=BlenderContract(
            version=_string(blender_raw["version"], "render.blender.version"),
            build_hash=_string(blender_raw["build_hash"], "render.blender.build_hash"),
            executable_sha256=_sha(blender_raw["executable_sha256"], "render.blender.executable_sha256"),
            portable_archive_sha256=_sha(
                blender_raw["portable_archive_sha256"], "render.blender.portable_archive_sha256"
            ),
        ),
        engine=_string(render["engine"], "render.engine"),
        supersample=_integer(render["supersample"], "render.supersample", minimum=2, maximum=8),
        samples=_integer(render["samples"], "render.samples", minimum=1, maximum=256),
        transparent=render["transparent"] is True,
        camera_contract=_string(render["camera_contract"], "render.camera_contract"),
        colour_management=_string(render["colour_management"], "render.colour_management"),
        material_ids=material_ids,
        mask_background=_rgba(mask["background"], "team_mask.background"),
        mask_team_role=team_role,
        mask_visible_blue=_integer(mask["visible_blue"], "team_mask.visible_blue", maximum=255),
        mask_pivot_green=_number(mask["pivot_green"], "team_mask.pivot_green", maximum=255.0),
        mask_green_per_pixel=_number(mask["green_per_pixel"], "team_mask.green_per_pixel", maximum=16.0),
        min_pose_confidence=_number(
            quality["min_pose_confidence"], "quality.min_pose_confidence", maximum=1.0
        ),
        max_border_ratio=_number(quality["max_border_ratio"], "quality.max_border_ratio", maximum=1.0),
        max_empty_alpha_ratio=_number(
            quality["max_empty_alpha_ratio"], "quality.max_empty_alpha_ratio", maximum=1.0
        ),
        max_id_unclassified_ratio=_number(
            quality["max_id_unclassified_ratio"], "quality.max_id_unclassified_ratio", maximum=1.0
        ),
    )
    if not spec.transparent:
        raise Unit3DError("render.transparent must be true")
    if spec.engine != "BLENDER_EEVEE":
        raise Unit3DError("Only the pinned BLENDER_EEVEE production engine is accepted")
    if spec.camera_contract != "orthographic-pivot-locked-v1":
        raise Unit3DError("Unknown render.camera_contract")
    if spec.colour_management != "AgX-MediumHighContrast-sRGB-v1":
        raise Unit3DError("Unknown render.colour_management")
    if spec.wearer_right_equipment != "open_stone_satchel" or spec.wearer_left_equipment != "small_utility_pouch":
        raise Unit3DError("Slinger equipment side contract changed")
    return spec


def _safe_generated_path(path: Path, project_root: Path, label: str) -> Path:
    path = path.resolve()
    try:
        relative = path.relative_to(project_root.resolve())
    except ValueError as exc:
        raise Unit3DError(f"{label} must stay below the project root") from exc
    if not relative.parts or relative.parts[0] not in ALLOWED_GENERATED_ROOTS:
        raise Unit3DError(
            f"{label} must be below one of {sorted(ALLOWED_GENERATED_ROOTS)}, found {relative}"
        )
    return path


def _frame_slot(name: str, group: str) -> tuple[int, bool]:
    prefix = group + "-"
    if not name.startswith(prefix):
        raise Unit3DError(f"Frame {name!r} does not belong to {group}")
    suffix = name[len(prefix) :]
    alternate = suffix.endswith("x")
    numeric = suffix[:-1] if alternate else suffix
    if not numeric.isdigit():
        raise Unit3DError(f"Invalid frame name {name!r}")
    return int(numeric), alternate


def _action_hint(slot: int, alternate: bool) -> str:
    """Coarse hints only; exact animation contracts are pinned separately."""

    if alternate:
        return "alternate"
    if slot < 128:
        return "walk"
    if slot < 256:
        return "run"
    if 464 <= slot < 744:
        return "ranged_attack"
    if 1024 <= slot:
        return "hit_or_death"
    return "state_or_transition"


def _pose_landmarks(pose: Pose) -> dict[str, Point | None]:
    return {
        "head": pose.head,
        "shoulder_left": pose.shoulder_left,
        "shoulder_right": pose.shoulder_right,
        "elbow_left": pose.elbow_left,
        "elbow_right": pose.elbow_right,
        "hand_left": pose.hand_left,
        "hand_right": pose.hand_right,
        "hip_left": pose.hip_left,
        "hip_right": pose.hip_right,
        "knee_left": pose.knee_left,
        "knee_right": pose.knee_right,
        "ankle_left": pose.ankle_left,
        "ankle_right": pose.ankle_right,
        "ground": pose.ground,
        "weapon_tip": pose.weapon_tip,
        "axis": pose.axis,
        "normal": pose.normal,
        "stature": (pose.stature, 0.0),
    }


def _source_frames(source_dir: Path, spec: Unit3DSpec) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    index_path = source_dir / "index.json"
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Unit3DError(f"Cannot read source export index {index_path}: {exc}") from exc
    if not isinstance(index, dict) or index.get("schema_version") != 1:
        raise Unit3DError("Source export must use sprite index schema 1")
    if index.get("group") != spec.group:
        raise Unit3DError(f"Source group {index.get('group')!r} does not match {spec.group}")
    frames = index.get("frames")
    if not isinstance(frames, list) or len(frames) != spec.expected_frames:
        raise Unit3DError(
            f"Expected {spec.expected_frames} source frames, found "
            f"{len(frames) if isinstance(frames, list) else 'invalid'}"
        )
    names: list[str] = []
    main = alternate = 0
    for position, frame in enumerate(frames):
        if not isinstance(frame, dict):
            raise Unit3DError(f"Source frame {position} is not an object")
        required = {"name", "file", "mask_file", "width", "height", "effective"}
        if not required <= set(frame):
            raise Unit3DError(f"Source frame {position} misses {sorted(required - set(frame))}")
        name = _string(frame["name"], f"frames[{position}].name")
        _, is_alt = _frame_slot(name, spec.group)
        alternate += int(is_alt)
        main += int(not is_alt)
        names.append(name)
    if len(names) != len(set(names)):
        raise Unit3DError("Source export contains duplicate frame names")
    if (main, alternate) != (spec.expected_main, spec.expected_alternate):
        raise Unit3DError(
            f"Expected main/alternate {spec.expected_main}/{spec.expected_alternate}, found {main}/{alternate}"
        )
    return index, frames


def extract_pose_manifest(source_dir: Path, output_path: Path, spec: Unit3DSpec) -> PoseManifestReport:
    """Convert an exported group into an RGB-free, atomically written pose manifest."""

    source_dir = source_dir.resolve()
    output_path = _safe_generated_path(output_path, spec.project_root, "pose manifest")
    index, source_frames = _source_frames(source_dir, spec)
    adapter = SimpleNamespace(
        group=spec.group,
        direction_map=spec.direction_map,
        proportions=spec.pose_proportions,
        weapon="sling",
    )
    pose_frames: list[PoseFrame] = []
    motion_digest = hashlib.sha256()
    for position, frame in enumerate(source_frames):
        name = str(frame["name"])
        colour_path = source_dir / str(frame["file"])
        mask_path = source_dir / str(frame["mask_file"])
        if not colour_path.is_file() or not mask_path.is_file():
            raise Unit3DError(f"{name}: colour or team mask is missing")
        with Image.open(colour_path) as opened:
            colour = opened.convert("RGBA")
        with Image.open(mask_path) as opened:
            team_mask = opened.convert("RGBA")
        expected_size = (int(frame["width"]), int(frame["height"]))
        if colour.size != expected_size or team_mask.size != expected_size:
            raise Unit3DError(
                f"{name}: expected {expected_size}, found {colour.size}/{team_mask.size}"
            )

        # Deliberately destroy every donor RGB channel before pose extraction.
        # A regression that tries to read RGB therefore receives only zeroes.
        alpha = colour.getchannel("A")
        blinded = Image.new("RGBA", colour.size, (0, 0, 0, 0))
        blinded.putalpha(alpha)
        pose = extract_pose(blinded, team_mask, adapter, name)  # type: ignore[arg-type]
        if pose.confidence < spec.min_pose_confidence:
            raise Unit3DError(
                f"{name}: pose confidence {pose.confidence:.3f} below {spec.min_pose_confidence:.3f}"
            )
        slot, alternate = _frame_slot(name, spec.group)
        effective = _require_object(frame["effective"], f"{name}.effective")
        pivot_x = _number(effective.get("pivot_x"), f"{name}.pivot_x", maximum=2.0)
        pivot_y = _number(effective.get("pivot_y"), f"{name}.pivot_y", maximum=2.0)
        ppu = _number(effective.get("pixels_per_unit"), f"{name}.pixels_per_unit", minimum=1.0)
        alpha_sha = _sha256_bytes(alpha.tobytes())
        mask_sha = _sha256_bytes(team_mask.tobytes())
        motion_digest.update(name.encode("utf-8"))
        motion_digest.update(alpha_sha.encode("ascii"))
        motion_digest.update(mask_sha.encode("ascii"))
        motion_digest.update(json.dumps(effective, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        pose_frames.append(
            PoseFrame(
                name=name,
                file=str(frame["file"]),
                mask_file=str(frame["mask_file"]),
                slot=slot,
                alternate=alternate,
                direction=pose.direction,
                reference_direction=pose.reference_direction,
                width=expected_size[0],
                height=expected_size[1],
                pivot_x=pivot_x,
                pivot_y=pivot_y,
                pixels_per_unit=ppu,
                confidence=pose.confidence,
                lying=pose.lying,
                action_hint=_action_hint(slot, alternate),
                source_alpha_sha256=alpha_sha,
                source_mask_sha256=mask_sha,
                landmarks=_pose_landmarks(pose),
            )
        )

    index_sha = sha256_file(source_dir / "index.json")
    payload = {
        "schema_version": POSE_MANIFEST_SCHEMA,
        "unit_id": spec.unit_id,
        "group": spec.group,
        "extractor": spec.pose_extractor,
        "source_channels": ["alpha", "team_mask"],
        "donor_rgb_used": False,
        "source_index_sha256": index_sha,
        "source_motion_sha256": motion_digest.hexdigest(),
        "spec_sha256": sha256_file(spec.path),
        "frame_count": len(pose_frames),
        "frames": [asdict(frame) for frame in pose_frames],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    with tempfile.NamedTemporaryFile(
        prefix=output_path.name + ".tmp-", dir=output_path.parent, delete=False
    ) as handle:
        temporary = Path(handle.name)
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.replace(temporary, output_path)
    finally:
        temporary.unlink(missing_ok=True)
    return PoseManifestReport(
        path=output_path,
        frame_count=len(pose_frames),
        main_count=sum(not frame.alternate for frame in pose_frames),
        alternate_count=sum(frame.alternate for frame in pose_frames),
        source_index_sha256=index_sha,
        source_motion_sha256=motion_digest.hexdigest(),
        min_pose_confidence=min(frame.confidence for frame in pose_frames),
    )


def load_pose_manifest(path: Path, spec: Unit3DSpec) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Unit3DError(f"Cannot read pose manifest {path}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != POSE_MANIFEST_SCHEMA:
        raise Unit3DError("Unsupported pose manifest")
    if payload.get("unit_id") != spec.unit_id or payload.get("group") != spec.group:
        raise Unit3DError("Pose manifest unit/group differs from the unit contract")
    if payload.get("donor_rgb_used") is not False or payload.get("source_channels") != ["alpha", "team_mask"]:
        raise Unit3DError("Pose manifest violates the donor-RGB exclusion contract")
    if payload.get("spec_sha256") != sha256_file(spec.path):
        raise Unit3DError("Pose manifest was produced from another unit contract")
    frames = payload.get("frames")
    if not isinstance(frames, list) or len(frames) != spec.expected_frames:
        raise Unit3DError("Pose manifest is incomplete")
    names = [frame.get("name") for frame in frames if isinstance(frame, dict)]
    if len(names) != len(frames) or len(set(names)) != len(names):
        raise Unit3DError("Pose manifest frame names are invalid or duplicated")
    return payload


def load_blender_toolchain_contract(project_root: Path) -> Mapping[str, Any]:
    path = project_root.resolve() / "config" / "blender-toolchain.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Unit3DError(f"Cannot read Blender toolchain contract {path}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise Unit3DError("Unsupported Blender toolchain contract")
    return payload


def find_blender(spec: Unit3DSpec) -> Path:
    """Locate Blender and reject anything except the pinned executable bytes."""

    toolchain = load_blender_toolchain_contract(spec.project_root)
    candidates: list[Path] = []
    override_name = str(toolchain.get("environment_override", ""))
    if override_name and os.environ.get(override_name):
        candidates.append(Path(os.environ[override_name]))
    portable = toolchain.get("portable_relative_path")
    if isinstance(portable, str) and portable:
        local = os.environ.get("LOCALAPPDATA")
        if local:
            candidates.append(Path(local) / Path(portable))
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if not resolved.is_file():
            continue
        actual = sha256_file(resolved)
        if actual != spec.blender.executable_sha256:
            raise Unit3DError(
                f"Blender executable fingerprint changed: expected {spec.blender.executable_sha256}, found {actual}"
            )
        return resolved
    raise Unit3DError(
        "Pinned Blender executable not found; install the portable toolchain or set "
        f"{override_name}"
    )


def verify_blender(spec: Unit3DSpec) -> Mapping[str, str]:
    executable = find_blender(spec)
    completed = subprocess.run(
        [str(executable), "--background", "--factory-startup", "--version"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    output = completed.stdout + completed.stderr
    if completed.returncode != 0:
        raise Unit3DError(f"Blender version check failed ({completed.returncode}): {output[-2000:]}")
    if f"Blender {spec.blender.version}" not in output or spec.blender.build_hash not in output:
        raise Unit3DError("Blender version/build hash differs from the unit contract")
    return {
        "executable": str(executable),
        "version": spec.blender.version,
        "build_hash": spec.blender.build_hash,
        "executable_sha256": spec.blender.executable_sha256,
    }


def run_blender_script(
    spec: Unit3DSpec,
    script: Path,
    arguments: Sequence[str],
    *,
    timeout: int = 900,
) -> subprocess.CompletedProcess[str]:
    executable = find_blender(spec)
    script = script.resolve()
    try:
        script.relative_to(spec.project_root)
    except ValueError as exc:
        raise Unit3DError("Blender script must reside inside the project") from exc
    if not script.is_file():
        raise Unit3DError(f"Blender script is missing: {script}")
    completed = subprocess.run(
        [
            str(executable),
            "--background",
            "--factory-startup",
            "--python-exit-code",
            "17",
            "--python",
            str(script),
            "--",
            *arguments,
        ],
        cwd=spec.project_root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if completed.returncode != 0:
        tail = (completed.stdout + "\n" + completed.stderr)[-12000:]
        raise Unit3DError(f"Blender script failed ({completed.returncode}):\n{tail}")
    return completed


def pose_manifest_frame_names(payload: Mapping[str, Any]) -> tuple[str, ...]:
    frames = payload.get("frames")
    if not isinstance(frames, list):
        raise Unit3DError("Pose manifest has no frames")
    return tuple(str(frame["name"]) for frame in frames)


def assert_requested_frames(payload: Mapping[str, Any], requested: Iterable[str]) -> tuple[str, ...]:
    names = pose_manifest_frame_names(payload)
    allowed = set(names)
    result = tuple(requested)
    if not result or len(result) != len(set(result)):
        raise Unit3DError("Requested render frames must be non-empty and unique")
    unknown = sorted(set(result) - allowed)
    if unknown:
        raise Unit3DError(f"Unknown render frames: {unknown}")
    return result


def _round_half_up(value: float) -> int:
    return int(math.floor(value + 0.5))


def _nearest_material_role(rgb: Sequence[int], spec: Unit3DSpec) -> tuple[str, int]:
    role, colour = min(
        spec.material_ids.items(),
        key=lambda item: sum((int(rgb[index]) - item[1][index]) ** 2 for index in range(3)),
    )
    distance_sq = sum((int(rgb[index]) - colour[index]) ** 2 for index in range(3))
    return role, distance_sq


def _border_visible(alpha: Image.Image) -> int:
    if alpha.width == 0 or alpha.height == 0:
        return 0
    pixels = alpha.load()
    coordinates = {(x, 0) for x in range(alpha.width)}
    coordinates.update((x, alpha.height - 1) for x in range(alpha.width))
    coordinates.update((0, y) for y in range(alpha.height))
    coordinates.update((alpha.width - 1, y) for y in range(alpha.height))
    return sum(pixels[x, y] > 12 for x, y in coordinates)


def finalize_render_pair(
    beauty_path: Path,
    id_path: Path,
    frame: Mapping[str, Any],
    spec: Unit3DSpec,
) -> tuple[Image.Image, Image.Image, FinalizedFrameStats]:
    """Downsample one paired Blender render and derive the functional game mask."""

    width = int(frame["width"])
    height = int(frame["height"])
    supersample = spec.supersample
    expected_raw = (width * supersample, height * supersample)
    with Image.open(beauty_path) as opened:
        beauty = opened.convert("RGBA")
    with Image.open(id_path) as opened:
        material_id = opened.convert("RGBA")
    if beauty.size != expected_raw or material_id.size != expected_raw:
        raise Unit3DError(
            f"{frame['name']}: expected raw geometry {expected_raw}, found "
            f"{beauty.size}/{material_id.size}"
        )

    beauty_pixels = beauty.load()
    id_pixels = material_id.load()
    output = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    output_pixels = output.load()
    output_mask = Image.new("RGBA", (width, height), spec.mask_background)
    mask_pixels = output_mask.load()
    id_unclassified = 0
    classified_visible = 0
    non_neutral_team = 0
    team_pixels = 0
    visible_pixels = 0
    sample_count = supersample * supersample

    pivot_y_px = float(frame["pivot_y"]) * height
    for target_y in range(height):
        z_from_pivot = target_y - (height - pivot_y_px)
        green = max(
            0,
            min(
                255,
                _round_half_up(spec.mask_green_per_pixel * z_from_pivot + spec.mask_pivot_green),
            ),
        )
        for target_x in range(width):
            alpha_sum = 0
            red_premultiplied = 0
            green_premultiplied = 0
            blue_premultiplied = 0
            team_alpha_sum = 0
            for offset_y in range(supersample):
                raw_y = target_y * supersample + offset_y
                for offset_x in range(supersample):
                    raw_x = target_x * supersample + offset_x
                    red, green_beauty, blue, alpha = beauty_pixels[raw_x, raw_y]
                    if alpha:
                        alpha_sum += alpha
                        red_premultiplied += red * alpha
                        green_premultiplied += green_beauty * alpha
                        blue_premultiplied += blue * alpha
                        id_red, id_green, id_blue, id_alpha = id_pixels[raw_x, raw_y]
                        if id_alpha <= 2:
                            id_unclassified += 1
                            continue
                        role, distance_sq = _nearest_material_role(
                            (id_red, id_green, id_blue), spec
                        )
                        classified_visible += 1
                        # Exact interiors differ by at most a few PNG levels.
                        # A larger distance means beauty/ID geometry drifted or
                        # colour management contaminated the data pass.
                        if id_alpha >= 224 and distance_sq > 48:
                            id_unclassified += 1
                        if role == spec.mask_team_role:
                            team_alpha_sum += alpha
                            if alpha >= 64 and max(red, green_beauty, blue) - min(
                                red, green_beauty, blue
                            ) > 6:
                                non_neutral_team += 1
            if alpha_sum == 0:
                continue
            alpha_out = max(1, min(255, _round_half_up(alpha_sum / sample_count)))
            output_pixels[target_x, target_y] = (
                max(0, min(255, _round_half_up(red_premultiplied / alpha_sum))),
                max(0, min(255, _round_half_up(green_premultiplied / alpha_sum))),
                max(0, min(255, _round_half_up(blue_premultiplied / alpha_sum))),
                alpha_out,
            )
            team_red = max(0, min(255, _round_half_up(255.0 * team_alpha_sum / alpha_sum)))
            mask_pixels[target_x, target_y] = (
                team_red,
                green,
                spec.mask_visible_blue,
                255,
            )
            visible_pixels += 1
            team_pixels += int(team_red > 0)

    if visible_pixels == 0:
        raise Unit3DError(f"{frame['name']}: Blender beauty pass is empty")
    considered = max(1, classified_visible + id_unclassified)
    unclassified_ratio = id_unclassified / considered
    if unclassified_ratio > spec.max_id_unclassified_ratio:
        raise Unit3DError(
            f"{frame['name']}: ID unclassified ratio {unclassified_ratio:.6f} exceeds "
            f"{spec.max_id_unclassified_ratio:.6f}"
        )
    if non_neutral_team:
        raise Unit3DError(
            f"{frame['name']}: {non_neutral_team} team-material subpixels are not neutral grey"
        )
    alpha = output.getchannel("A")
    border = _border_visible(alpha)
    border_ratio = border / visible_pixels
    if border_ratio > spec.max_border_ratio:
        raise Unit3DError(
            f"{frame['name']}: visible border ratio {border_ratio:.4f} exceeds "
            f"{spec.max_border_ratio:.4f}; model is clipped"
        )
    # Functional invariants of Unlit/TeamColour: mask alpha is data-only and
    # therefore always opaque; visible B is zero; invisible pixels use the
    # canonical background marker.
    for pixel, mask_pixel in zip(output.get_flattened_data(), output_mask.get_flattened_data()):
        if mask_pixel[3] != 255:
            raise Unit3DError(f"{frame['name']}: mask alpha is not fully opaque")
        if pixel[3] == 0 and mask_pixel != spec.mask_background:
            raise Unit3DError(f"{frame['name']}: transparent mask background differs")
        if pixel[3] > 0 and mask_pixel[2] != spec.mask_visible_blue:
            raise Unit3DError(f"{frame['name']}: visible mask B differs")
    return output, output_mask, FinalizedFrameStats(
        name=str(frame["name"]),
        width=width,
        height=height,
        visible_pixels=visible_pixels,
        team_pixels=team_pixels,
        border_pixels=border,
        border_ratio=border_ratio,
        id_unclassified_subpixels=id_unclassified,
        id_unclassified_ratio=unclassified_ratio,
        team_non_neutral_subpixels=non_neutral_team,
        colour_pixels_sha256=_sha256_bytes(output.tobytes()),
        mask_pixels_sha256=_sha256_bytes(output_mask.tobytes()),
    )


def finalize_render_batch(
    raw_dir: Path,
    output_dir: Path,
    pose_manifest_path: Path,
    spec: Unit3DSpec,
    frame_names: Iterable[str],
) -> tuple[FinalizedFrameStats, ...]:
    """Finalize a new, non-overwriting batch below a generated project root."""

    raw_dir = _safe_generated_path(raw_dir, spec.project_root, "raw render directory")
    output_dir = _safe_generated_path(output_dir, spec.project_root, "finalized render directory")
    if output_dir.exists():
        raise Unit3DError(f"Finalized output already exists; refusing to overwrite: {output_dir}")
    payload = load_pose_manifest(pose_manifest_path, spec)
    requested = assert_requested_frames(payload, frame_names)
    by_name = {str(frame["name"]): frame for frame in payload["frames"]}
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=output_dir.name + ".tmp-", dir=output_dir.parent))
    stats: list[FinalizedFrameStats] = []
    try:
        for name in requested:
            frame = by_name[name]
            beauty_path = raw_dir / f"{name}.beauty.png"
            id_path = raw_dir / f"{name}.id.png"
            if not beauty_path.is_file() or not id_path.is_file():
                raise Unit3DError(f"{name}: raw beauty/ID pair is incomplete")
            colour, mask, frame_stats = finalize_render_pair(
                beauty_path, id_path, frame, spec
            )
            colour.save(
                temporary / str(frame["file"]),
                format="PNG",
                optimize=False,
                compress_level=9,
            )
            mask.save(
                temporary / str(frame["mask_file"]),
                format="PNG",
                optimize=False,
                compress_level=9,
            )
            stats.append(frame_stats)
        report = {
            "schema_version": RENDER_REPORT_SCHEMA,
            "unit_id": spec.unit_id,
            "group": spec.group,
            "pose_manifest_sha256": sha256_file(pose_manifest_path),
            "spec_sha256": sha256_file(spec.path),
            "frame_count": len(stats),
            "frames": [asdict(item) for item in stats],
        }
        (temporary / "finalize-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(output_dir)
        return tuple(stats)
    except Exception:
        # The temporary directory contains generated data only and is never an
        # accepted output.  Remove files individually to avoid a broad delete.
        for path in sorted(temporary.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
        temporary.rmdir()
        raise

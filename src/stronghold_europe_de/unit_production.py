"""Manifest-driven production of genuinely new animated unit artwork.

The shipped game frame is used as a *motion capture plate* only.  Its alpha
and semantic team mask reveal the pose, direction and animation timing.  The
RGB pixels are deliberately never read by the renderer.  Every visible output
pixel is drawn by the articulated European paper-doll renderer described by a
versioned unit manifest.

That separation is the central safety contract for this module: changing all
donor RGB values while retaining alpha and mask bytes must produce a
bit-identical result.  It prevents a future unit production run from silently
degrading into a recolour.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from collections import deque
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any, Iterable, Mapping, Sequence

from PIL import Image, ImageChops, ImageDraw


SPEC_SCHEMA = 1
REPORT_SCHEMA = 2
_HEX_COLOUR = re.compile(r"^#[0-9a-fA-F]{6}$")
_HEX_256 = re.compile(r"^[0-9a-f]{64}$")


class UnitProductionError(RuntimeError):
    """Raised before incomplete, donor-coloured or geometrically unsafe art ships."""


Point = tuple[float, float]
Colour = tuple[int, int, int]
MaskColour = tuple[int, int, int, int]


@dataclass(frozen=True)
class UnitSpec:
    path: Path
    unit_id: str
    display_name: str
    group: str
    expected_frames: int
    expected_main: int
    expected_alternate: int
    reference_path: Path
    reference_sha256: str
    reference_mask_path: Path
    reference_mask_sha256: str
    reference_columns: int
    reference_rows: int
    reference_chroma_key: Colour
    reference_chroma_tolerance: int
    direction_map: tuple[int, ...]
    supersample: int
    headwear: str
    palette: Mapping[str, Colour]
    team_mask: Mapping[str, MaskColour]
    proportions: Mapping[str, float]
    weapon: str
    blood_start: int
    blood_end: int
    min_pose_confidence: float
    min_alpha_change_ratio: float
    max_source_rgb_equal_ratio: float
    max_border_ratio: float


@dataclass(frozen=True)
class Pose:
    head: Point
    axis: Point
    normal: Point
    stature: float
    shoulder_left: Point
    shoulder_right: Point
    elbow_left: Point
    elbow_right: Point
    hand_left: Point
    hand_right: Point
    hip_left: Point
    hip_right: Point
    knee_left: Point
    knee_right: Point
    ankle_left: Point
    ankle_right: Point
    ground: Point
    weapon_tip: Point | None
    direction: int
    reference_direction: int
    confidence: float
    lying: bool


@dataclass(frozen=True)
class FrameRenderStats:
    name: str
    width: int
    height: int
    direction: int
    reference_direction: int
    pose_confidence: float
    source_visible_pixels: int
    output_visible_pixels: int
    alpha_changed_pixels: int
    mask_changed_pixels: int
    source_rgb_equal_pixels: int
    source_rgb_equal_ratio: float
    alpha_change_ratio: float
    border_visible_pixels: int
    border_ratio: float
    colour_sha256: str
    mask_sha256: str


@dataclass(frozen=True)
class UnitBuildReport:
    schema_version: int
    unit_id: str
    group: str
    renderer: str
    frame_count: int
    main_count: int
    alternate_count: int
    source_names_sha256: str
    reference_sha256: str
    output_payload_sha256: str
    min_pose_confidence: float
    max_source_rgb_equal_ratio: float
    min_alpha_change_ratio: float
    max_border_ratio: float
    changed_alpha_frames: int
    changed_mask_frames: int


@dataclass(frozen=True)
class _ReferencePiece:
    name: str
    colour: Image.Image
    team_mask: Image.Image
    anchor: Point
    end: Point


@dataclass(frozen=True)
class _ReferenceView:
    direction: int
    stature: float
    pieces: Mapping[str, _ReferencePiece]


@dataclass(frozen=True)
class _ReferenceRig:
    sha256: str
    views: tuple[_ReferenceView, ...]


_REFERENCE_RIG_CACHE: dict[str, _ReferenceRig] = {}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_exact_keys(value: Mapping[str, Any], keys: set[str], label: str) -> None:
    present = set(value)
    if present != keys:
        missing = sorted(keys - present)
        extra = sorted(present - keys)
        raise UnitProductionError(
            f"{label}: wrong fields; missing={missing or '-'}, extra={extra or '-'}"
        )


def _as_int(value: Any, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise UnitProductionError(f"{label}: expected integer >= {minimum}")
    return value


def _as_float(value: Any, label: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise UnitProductionError(f"{label}: expected number")
    result = float(value)
    if not math.isfinite(result) or result < minimum:
        raise UnitProductionError(f"{label}: expected finite number >= {minimum}")
    return result


def _parse_colour(value: Any, label: str) -> Colour:
    if not isinstance(value, str) or not _HEX_COLOUR.fullmatch(value):
        raise UnitProductionError(f"{label}: expected #RRGGBB")
    return tuple(bytes.fromhex(value[1:]))  # type: ignore[return-value]


def _parse_mask_colour(value: Any, label: str) -> MaskColour:
    if (
        not isinstance(value, list)
        or len(value) != 4
        or any(isinstance(item, bool) or not isinstance(item, int) for item in value)
        or any(item < 0 or item > 255 for item in value)
    ):
        raise UnitProductionError(f"{label}: expected four bytes")
    return tuple(value)  # type: ignore[return-value]


def load_unit_spec(path: Path, *, project_root: Path | None = None) -> UnitSpec:
    """Load and fully validate one reusable unit production manifest."""

    path = path.resolve()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UnitProductionError(f"Cannot read unit manifest {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise UnitProductionError("Unit manifest root must be an object")
    _require_exact_keys(
        raw,
        {
            "schema_version",
            "unit_id",
            "display_name",
            "group",
            "expected",
            "reference",
            "renderer",
            "quality",
        },
        "unit manifest",
    )
    if raw["schema_version"] != SPEC_SCHEMA:
        raise UnitProductionError(
            f"Unsupported unit manifest schema {raw['schema_version']!r}"
        )
    for key in ("unit_id", "display_name", "group"):
        if not isinstance(raw[key], str) or not raw[key].strip():
            raise UnitProductionError(f"{key}: expected non-empty string")

    expected = raw["expected"]
    reference = raw["reference"]
    renderer = raw["renderer"]
    quality = raw["quality"]
    if not all(isinstance(item, dict) for item in (expected, reference, renderer, quality)):
        raise UnitProductionError("expected/reference/renderer/quality must be objects")
    _require_exact_keys(expected, {"frames", "main", "alternate"}, "expected")
    _require_exact_keys(
        reference,
        {
            "path",
            "sha256",
            "mask_path",
            "mask_sha256",
            "columns",
            "rows",
            "chroma_key",
            "chroma_tolerance",
            "direction_map",
        },
        "reference",
    )
    _require_exact_keys(
        renderer,
        {
            "supersample",
            "headwear",
            "palette",
            "team_mask",
            "proportions",
            "weapon",
            "blood_frames",
        },
        "renderer",
    )
    _require_exact_keys(
        quality,
        {
            "min_pose_confidence",
            "min_alpha_change_ratio",
            "max_source_rgb_equal_ratio",
            "max_border_ratio",
        },
        "quality",
    )
    frame_count = _as_int(expected["frames"], "expected.frames", minimum=1)
    main_count = _as_int(expected["main"], "expected.main")
    alternate_count = _as_int(expected["alternate"], "expected.alternate")
    if main_count + alternate_count != frame_count:
        raise UnitProductionError("expected.main + expected.alternate must equal frames")

    columns = _as_int(reference["columns"], "reference.columns", minimum=1)
    rows = _as_int(reference["rows"], "reference.rows", minimum=1)
    direction_map_raw = reference["direction_map"]
    if (
        not isinstance(direction_map_raw, list)
        or len(direction_map_raw) != 8
        or sorted(direction_map_raw) != list(range(8))
        or any(isinstance(item, bool) for item in direction_map_raw)
    ):
        raise UnitProductionError("reference.direction_map must be a permutation of 0..7")
    chroma = reference["chroma_key"]
    if (
        not isinstance(chroma, list)
        or len(chroma) != 3
        or any(isinstance(item, bool) or not isinstance(item, int) for item in chroma)
        or any(item < 0 or item > 255 for item in chroma)
    ):
        raise UnitProductionError("reference.chroma_key must contain three bytes")
    reference_hash = reference["sha256"]
    if not isinstance(reference_hash, str) or not _HEX_256.fullmatch(reference_hash):
        raise UnitProductionError("reference.sha256 must be lowercase SHA-256")
    reference_relative = reference["path"]
    if not isinstance(reference_relative, str) or not reference_relative:
        raise UnitProductionError("reference.path must be non-empty")
    root = project_root.resolve() if project_root else path.parents[2]
    reference_path = (root / reference_relative).resolve()
    try:
        reference_path.relative_to(root)
    except ValueError as exc:
        raise UnitProductionError("reference.path escapes the project root") from exc
    if not reference_path.is_file():
        raise UnitProductionError(f"Reference image is missing: {reference_path}")
    actual_reference_hash = _sha256_file(reference_path)
    if actual_reference_hash != reference_hash:
        raise UnitProductionError(
            "Reference image fingerprint changed: "
            f"expected {reference_hash}, found {actual_reference_hash}"
        )
    reference_mask_hash = reference["mask_sha256"]
    if not isinstance(reference_mask_hash, str) or not _HEX_256.fullmatch(reference_mask_hash):
        raise UnitProductionError("reference.mask_sha256 must be lowercase SHA-256")
    reference_mask_relative = reference["mask_path"]
    if not isinstance(reference_mask_relative, str) or not reference_mask_relative:
        raise UnitProductionError("reference.mask_path must be non-empty")
    reference_mask_path = (root / reference_mask_relative).resolve()
    try:
        reference_mask_path.relative_to(root)
    except ValueError as exc:
        raise UnitProductionError("reference.mask_path escapes the project root") from exc
    if not reference_mask_path.is_file():
        raise UnitProductionError(f"AI material mask is missing: {reference_mask_path}")
    actual_mask_hash = _sha256_file(reference_mask_path)
    if actual_mask_hash != reference_mask_hash:
        raise UnitProductionError(
            "AI material-mask fingerprint changed: "
            f"expected {reference_mask_hash}, found {actual_mask_hash}"
        )

    palette_raw = renderer["palette"]
    mask_raw = renderer["team_mask"]
    proportions_raw = renderer["proportions"]
    if not all(isinstance(item, dict) for item in (palette_raw, mask_raw, proportions_raw)):
        raise UnitProductionError("palette/team_mask/proportions must be objects")
    palette_required = {
        "outline",
        "shadow",
        "skin_dark",
        "skin",
        "skin_light",
        "metal_dark",
        "metal",
        "metal_light",
        "felt_dark",
        "felt",
        "felt_light",
        "team_dark",
        "team",
        "team_light",
        "tunic_dark",
        "tunic",
        "tunic_light",
        "breeches_dark",
        "breeches",
        "wrap_dark",
        "wrap",
        "leather_dark",
        "leather",
        "blood_dark",
        "blood",
    }
    _require_exact_keys(palette_raw, palette_required, "renderer.palette")
    mask_required = {"background", "head", "body", "cloth", "shadow", "equipment"}
    _require_exact_keys(mask_raw, mask_required, "renderer.team_mask")
    proportion_required = {
        "torso_half_width",
        "shoulder_half_width",
        "cape_depth",
        "head_radius",
        "arm_width",
        "leg_width",
        "hand_radius",
        "boot_width",
        "pouch_radius",
    }
    _require_exact_keys(proportions_raw, proportion_required, "renderer.proportions")
    palette = {
        key: _parse_colour(value, f"renderer.palette.{key}")
        for key, value in palette_raw.items()
    }
    team_mask = {
        key: _parse_mask_colour(value, f"renderer.team_mask.{key}")
        for key, value in mask_raw.items()
    }
    proportions = {
        key: _as_float(value, f"renderer.proportions.{key}", minimum=0.001)
        for key, value in proportions_raw.items()
    }
    weapon = renderer["weapon"]
    if weapon not in {"none", "sling"}:
        raise UnitProductionError("renderer.weapon must be 'none' or 'sling'")
    headwear = renderer["headwear"]
    if headwear not in {"felt_hat", "kettle_helmet", "none"}:
        raise UnitProductionError(
            "renderer.headwear must be 'felt_hat', 'kettle_helmet', or 'none'"
        )
    blood_frames = renderer["blood_frames"]
    if (
        not isinstance(blood_frames, list)
        or len(blood_frames) != 2
        or any(isinstance(item, bool) or not isinstance(item, int) for item in blood_frames)
        or blood_frames[0] < 0
        or blood_frames[1] < blood_frames[0]
    ):
        raise UnitProductionError("renderer.blood_frames must be [first,last]")

    spec = UnitSpec(
        path=path,
        unit_id=raw["unit_id"],
        display_name=raw["display_name"],
        group=raw["group"],
        expected_frames=frame_count,
        expected_main=main_count,
        expected_alternate=alternate_count,
        reference_path=reference_path,
        reference_sha256=reference_hash,
        reference_mask_path=reference_mask_path,
        reference_mask_sha256=reference_mask_hash,
        reference_columns=columns,
        reference_rows=rows,
        reference_chroma_key=tuple(chroma),  # type: ignore[arg-type]
        reference_chroma_tolerance=_as_int(
            reference["chroma_tolerance"], "reference.chroma_tolerance"
        ),
        direction_map=tuple(direction_map_raw),
        supersample=_as_int(renderer["supersample"], "renderer.supersample", minimum=2),
        headwear=headwear,
        palette=palette,
        team_mask=team_mask,
        proportions=proportions,
        weapon=weapon,
        blood_start=blood_frames[0],
        blood_end=blood_frames[1],
        min_pose_confidence=_as_float(
            quality["min_pose_confidence"], "quality.min_pose_confidence"
        ),
        min_alpha_change_ratio=_as_float(
            quality["min_alpha_change_ratio"], "quality.min_alpha_change_ratio"
        ),
        max_source_rgb_equal_ratio=_as_float(
            quality["max_source_rgb_equal_ratio"],
            "quality.max_source_rgb_equal_ratio",
        ),
        max_border_ratio=_as_float(quality["max_border_ratio"], "quality.max_border_ratio"),
    )
    if spec.supersample > 8:
        raise UnitProductionError("renderer.supersample above 8 is not supported")
    if any(value > 1.0 for value in (
        spec.min_pose_confidence,
        spec.min_alpha_change_ratio,
        spec.max_source_rgb_equal_ratio,
        spec.max_border_ratio,
    )):
        raise UnitProductionError("quality ratios must be between 0 and 1")
    _validate_reference_sheet(spec)
    return spec


def _validate_reference_sheet(spec: UnitSpec) -> None:
    """Reject a changed layout or a non-segmentable character reference."""

    with Image.open(spec.reference_path) as opened:
        image = opened.convert("RGB")
    with Image.open(spec.reference_mask_path) as opened:
        authored_mask = opened.convert("RGB")
    if authored_mask.size != image.size:
        raise UnitProductionError(
            "AI material mask and character reference have different dimensions"
        )
    if image.width % spec.reference_columns or image.height % spec.reference_rows:
        raise UnitProductionError("Reference dimensions are not divisible by its grid")
    cell_w = image.width // spec.reference_columns
    cell_h = image.height // spec.reference_rows
    key = spec.reference_chroma_key
    tolerance = spec.reference_chroma_tolerance
    occupied_cells = 0
    for row in range(spec.reference_rows):
        for column in range(spec.reference_columns):
            cell = image.crop(
                (column * cell_w, row * cell_h, (column + 1) * cell_w, (row + 1) * cell_h)
            )
            foreground = 0
            for red, green, blue in cell.get_flattened_data():
                if max(abs(red - key[0]), abs(green - key[1]), abs(blue - key[2])) > tolerance:
                    foreground += 1
            ratio = foreground / (cell_w * cell_h)
            if ratio >= 0.08:
                occupied_cells += 1
    if occupied_cells != 8:
        raise UnitProductionError(
            f"Reference must contain eight occupied direction cells, found {occupied_cells}"
        )


def _looks_like_magenta(pixel: Sequence[int]) -> bool:
    red, green, blue = pixel[:3]
    return (
        red >= 145
        and blue >= 105
        and green <= 125
        and red - green >= 58
        and blue - green >= 42
    )


def _largest_foreground_component(image: Image.Image) -> Image.Image:
    """Return the actor alpha while discarding the separately drawn weapon prop."""

    rgb = image.convert("RGB")
    width, height = rgb.size
    pixels = list(rgb.get_flattened_data())
    foreground = bytearray(
        0 if _looks_like_magenta(pixel) else 1 for pixel in pixels
    )
    visited = bytearray(width * height)
    largest: list[int] = []
    for start, present in enumerate(foreground):
        if not present or visited[start]:
            continue
        visited[start] = 1
        queue: deque[int] = deque([start])
        component: list[int] = []
        while queue:
            index = queue.popleft()
            component.append(index)
            x = index % width
            y = index // width
            for neighbour in (
                index - 1 if x else -1,
                index + 1 if x + 1 < width else -1,
                index - width if y else -1,
                index + width if y + 1 < height else -1,
            ):
                if neighbour >= 0 and foreground[neighbour] and not visited[neighbour]:
                    visited[neighbour] = 1
                    queue.append(neighbour)
        if len(component) > len(largest):
            largest = component
    if len(largest) < width * height * 0.035:
        raise UnitProductionError("Reference cell contains no plausible character component")
    alpha = Image.new("L", (width, height), 0)
    alpha_pixels = alpha.load()
    for index in largest:
        alpha_pixels[index % width, index // width] = 255
    return alpha


def _mask_semantic(
    pixel: Sequence[int], default: str, spec: UnitSpec
) -> MaskColour:
    """Quantise the model-authored material map to exact engine lookup bytes."""

    red, green, blue = pixel[:3]
    classes: tuple[tuple[Colour, str], ...] = (
        ((255, 255, 255), "head"),
        ((255, 0, 0), "body"),
        ((0, 255, 255), "body"),
        ((255, 255, 0), "cloth"),
        ((0, 0, 255), "equipment"),
    )
    if _looks_like_magenta(pixel):
        return spec.team_mask[default]
    _, semantic = min(
        classes,
        key=lambda item: (
            (red - item[0][0]) ** 2
            + (green - item[0][1]) ** 2
            + (blue - item[0][2]) ** 2
        ),
    )
    return spec.team_mask[semantic]


def _piece_shape_mask(
    size: tuple[int, int],
    points: Sequence[Point],
    width: float,
    *,
    polygon: bool = False,
) -> Image.Image:
    result = Image.new("L", size, 0)
    draw = ImageDraw.Draw(result)
    integer_points = [(round(x), round(y)) for x, y in points]
    if polygon:
        draw.polygon(integer_points, fill=255)
    else:
        draw.line(integer_points, fill=255, width=max(1, round(width)), joint="curve")
        radius = max(1, round(width / 2.0))
        for x, y in (integer_points[0], integer_points[-1]):
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=255)
    return result


def _extract_reference_piece(
    name: str,
    colour: Image.Image,
    authored_mask: Image.Image,
    actor_alpha: Image.Image,
    shape_mask: Image.Image,
    anchor: Point,
    end: Point,
    default_semantic: str,
    spec: UnitSpec,
) -> _ReferencePiece:
    alpha = ImageChops.multiply(actor_alpha, shape_mask)
    bbox = alpha.getbbox()
    if bbox is None:
        raise UnitProductionError(f"Reference piece {name} is empty")
    padding = 3
    bbox = (
        max(0, bbox[0] - padding),
        max(0, bbox[1] - padding),
        min(colour.width, bbox[2] + padding),
        min(colour.height, bbox[3] + padding),
    )
    piece_colour = colour.convert("RGBA")
    piece_colour.putalpha(alpha)
    semantic = Image.new("RGBA", colour.size, (0, 0, 0, 0))
    semantic_pixels = semantic.load()
    authored_pixels = authored_mask.convert("RGB").load()
    alpha_pixels = alpha.load()
    for y in range(bbox[1], bbox[3]):
        for x in range(bbox[0], bbox[2]):
            value = alpha_pixels[x, y]
            if value:
                lookup = _mask_semantic(
                    authored_pixels[x, y], default_semantic, spec
                )
                semantic_pixels[x, y] = (*lookup[:3], value)
    return _ReferencePiece(
        name=name,
        colour=piece_colour.crop(bbox),
        team_mask=semantic.crop(bbox),
        anchor=(anchor[0] - bbox[0], anchor[1] - bbox[1]),
        end=(end[0] - bbox[0], end[1] - bbox[1]),
    )


def _reference_view(
    direction: int,
    colour: Image.Image,
    authored_mask: Image.Image,
    spec: UnitSpec,
) -> _ReferenceView:
    actor_alpha = _largest_foreground_component(colour)
    bbox = actor_alpha.getbbox()
    if bbox is None:
        raise UnitProductionError(f"Reference direction {direction} is empty")
    left, top, right, bottom = bbox
    stature = float(bottom - top)
    centre_x = (left + right) / 2.0

    def joint(lateral: float, vertical: float) -> Point:
        return centre_x + lateral * stature, top + vertical * stature

    head = joint(0.0, 0.105)
    neck = joint(0.0, 0.205)
    shoulder_left = joint(-0.135, 0.245)
    shoulder_right = joint(0.135, 0.245)
    elbow_left = joint(-0.205, 0.365)
    elbow_right = joint(0.205, 0.365)
    hand_left = joint(-0.275, 0.505)
    hand_right = joint(0.275, 0.505)
    hip_left = joint(-0.078, 0.565)
    hip_right = joint(0.078, 0.565)
    knee_left = joint(-0.085, 0.745)
    knee_right = joint(0.085, 0.745)
    ankle_left = joint(-0.095, 0.925)
    ankle_right = joint(0.095, 0.925)
    shoulder_centre = joint(0.0, 0.245)
    hip_centre = joint(0.0, 0.565)

    shapes: dict[str, tuple[Image.Image, Point, Point, str]] = {}
    shapes["head"] = (
        _piece_shape_mask(
            colour.size,
            [
                joint(-0.125, -0.005),
                joint(0.125, -0.005),
                joint(0.145, 0.245),
                joint(-0.145, 0.245),
            ],
            1,
            polygon=True,
        ),
        head,
        joint(0.0, 0.205),
        "head",
    )
    shapes["torso"] = (
        _piece_shape_mask(
            colour.size,
            [
                joint(-0.205, 0.185),
                joint(0.205, 0.185),
                joint(0.235, 0.665),
                joint(-0.235, 0.665),
            ],
            1,
            polygon=True,
        ),
        shoulder_centre,
        hip_centre,
        "cloth",
    )
    segment_definitions = {
        "arm_left_upper": (shoulder_left, elbow_left, 0.125, "cloth"),
        "arm_left_lower": (elbow_left, hand_left, 0.105, "cloth"),
        "arm_right_upper": (shoulder_right, elbow_right, 0.125, "cloth"),
        "arm_right_lower": (elbow_right, hand_right, 0.105, "cloth"),
        "leg_left_upper": (hip_left, knee_left, 0.165, "cloth"),
        "leg_left_lower": (knee_left, ankle_left, 0.145, "cloth"),
        "leg_right_upper": (hip_right, knee_right, 0.165, "cloth"),
        "leg_right_lower": (knee_right, ankle_right, 0.145, "cloth"),
    }
    for name, (start, end, width, semantic) in segment_definitions.items():
        shapes[name] = (
            _piece_shape_mask(colour.size, [start, end], stature * width),
            start,
            end,
            semantic,
        )
    pieces = {
        name: _extract_reference_piece(
            name,
            colour,
            authored_mask,
            actor_alpha,
            shape,
            anchor,
            end,
            semantic,
            spec,
        )
        for name, (shape, anchor, end, semantic) in shapes.items()
    }
    return _ReferenceView(direction=direction, stature=stature, pieces=pieces)


def load_reference_rig(spec: UnitSpec) -> _ReferenceRig:
    """Build the eight textured paper-doll views once per pinned AI asset pair."""

    cache_key = spec.reference_sha256 + spec.reference_mask_sha256
    cached = _REFERENCE_RIG_CACHE.get(cache_key)
    if cached is not None:
        return cached
    with Image.open(spec.reference_path) as opened:
        reference = opened.convert("RGB")
    with Image.open(spec.reference_mask_path) as opened:
        authored_mask = opened.convert("RGB")
    cell_width = reference.width // spec.reference_columns
    cell_height = reference.height // spec.reference_rows
    views: list[_ReferenceView] = []
    for direction in range(8):
        column = direction % spec.reference_columns
        row = direction // spec.reference_columns
        box = (
            column * cell_width,
            row * cell_height,
            (column + 1) * cell_width,
            (row + 1) * cell_height,
        )
        views.append(
            _reference_view(
                direction,
                reference.crop(box),
                authored_mask.crop(box),
                spec,
            )
        )
    rig = _ReferenceRig(
        sha256=cache_key,
        views=tuple(views),
    )
    _REFERENCE_RIG_CACHE[cache_key] = rig
    return rig


def _add(a: Point, b: Point) -> Point:
    return a[0] + b[0], a[1] + b[1]


def _sub(a: Point, b: Point) -> Point:
    return a[0] - b[0], a[1] - b[1]


def _mul(a: Point, factor: float) -> Point:
    return a[0] * factor, a[1] * factor


def _dot(a: Point, b: Point) -> float:
    return a[0] * b[0] + a[1] * b[1]


def _distance(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _centroid(points: Sequence[Point]) -> Point | None:
    if not points:
        return None
    return (
        sum(point[0] for point in points) / len(points),
        sum(point[1] for point in points) / len(points),
    )


def _quantile(values: Sequence[float], fraction: float) -> float:
    if not values:
        raise UnitProductionError("Cannot calculate quantile of an empty set")
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def _frame_number(name: str, group: str) -> int:
    prefix = group + "-"
    if not name.startswith(prefix):
        raise UnitProductionError(f"Frame {name!r} does not belong to {group}")
    suffix = name[len(prefix) :]
    if suffix.endswith("x"):
        suffix = suffix[:-1]
    if not suffix.isdigit():
        raise UnitProductionError(f"Frame {name!r} has no numeric animation slot")
    return int(suffix)


def _classify_pose_pixels(
    alpha: Image.Image, mask: Image.Image
) -> tuple[list[Point], list[Point], list[Point], list[Point], list[Point], list[Point]]:
    ap = alpha.load()
    mp = mask.load()
    visible: list[Point] = []
    head: list[Point] = []
    body: list[Point] = []
    legs: list[Point] = []
    shadow: list[Point] = []
    other: list[Point] = []
    for y in range(alpha.height):
        for x in range(alpha.width):
            if ap[x, y] <= 12:
                continue
            point = (float(x), float(y))
            visible.append(point)
            red, green, blue, _ = mp[x, y]
            if blue < 144 and red >= 165 and green <= 92:
                head.append(point)
            elif blue < 144 and red >= 150 and green > 84:
                legs.append(point)
            elif blue < 144 and red <= 88 and green >= 218:
                shadow.append(point)
            elif blue < 144 and red <= 88 and green < 218:
                body.append(point)
            else:
                other.append(point)
    return visible, head, body, legs, shadow, other


def _principal_axis(points: Sequence[Point]) -> Point:
    centre = _centroid(points)
    if centre is None:
        return (0.0, 1.0)
    xx = yy = xy = 0.0
    for x, y in points:
        dx = x - centre[0]
        dy = y - centre[1]
        xx += dx * dx
        yy += dy * dy
        xy += dx * dy
    theta = 0.5 * math.atan2(2.0 * xy, xx - yy)
    return math.cos(theta), math.sin(theta)


def _choose_two_endpoints(
    points: Sequence[Point], root: Point, stature: float
) -> tuple[Point, Point]:
    if not points:
        return (
            (root[0] - stature * 0.12, root[1] + stature * 0.38),
            (root[0] + stature * 0.12, root[1] + stature * 0.38),
        )
    ranked = sorted(points, key=lambda point: _distance(point, root), reverse=True)
    first = ranked[0]
    minimum_separation = max(2.0, stature * 0.11)
    second = max(
        ranked,
        key=lambda point: _distance(point, root)
        * min(1.0, _distance(point, first) / minimum_separation),
    )
    if _distance(first, second) < minimum_separation:
        direction = _sub(first, root)
        length = max(1.0, math.hypot(*direction))
        normal = (-direction[1] / length, direction[0] / length)
        second = _add(first, _mul(normal, minimum_separation))
    return first, second


def _assign_endpoints(
    first: Point, second: Point, left_root: Point, right_root: Point
) -> tuple[Point, Point]:
    direct = _distance(first, left_root) + _distance(second, right_root)
    crossed = _distance(second, left_root) + _distance(first, right_root)
    return (first, second) if direct <= crossed else (second, first)


def _joint_midpoint(root: Point, tip: Point, side: float, stature: float) -> Point:
    delta = _sub(tip, root)
    length = max(1.0, math.hypot(*delta))
    normal = (-delta[1] / length, delta[0] / length)
    bend = min(stature * 0.055, length * 0.18) * side
    return _add(_add(root, _mul(delta, 0.52)), _mul(normal, bend))


def extract_pose(source: Image.Image, mask: Image.Image, spec: UnitSpec, name: str) -> Pose:
    """Infer an articulated 2-D rig without reading one donor RGB channel."""

    source = source.convert("RGBA")
    mask = mask.convert("RGBA")
    if source.size != mask.size:
        raise UnitProductionError(f"{name}: colour {source.size} and mask {mask.size} differ")
    alpha = source.getchannel("A")
    visible, head_points, body_points, leg_points, shadow_points, other_points = (
        _classify_pose_pixels(alpha, mask)
    )
    if len(visible) < 24:
        raise UnitProductionError(f"{name}: too few visible pose pixels")
    visible_centre = _centroid(visible) or (source.width / 2.0, source.height / 2.0)
    head = _centroid(head_points)
    legs_centre = _centroid(leg_points)
    confidence_parts = [bool(head_points), bool(body_points), bool(leg_points)]
    if head is None:
        min_y = min(point[1] for point in visible)
        head = (visible_centre[0], min_y + 2.0)
    if legs_centre is None:
        legs_centre = visible_centre
    axis_delta = _sub(legs_centre, head)
    axis_length = math.hypot(*axis_delta)
    if axis_length < 5.0:
        axis_delta = _principal_axis(visible)
        if _dot(axis_delta, _sub(legs_centre, head)) < 0:
            axis_delta = _mul(axis_delta, -1.0)
        axis_length = 1.0
    axis = (axis_delta[0] / axis_length, axis_delta[1] / axis_length)
    normal = (-axis[1], axis[0])
    projections = [_dot(_sub(point, head), axis) for point in leg_points or visible]
    stature = max(24.0, _quantile(projections, 0.97))
    if stature > max(source.width, source.height) * 1.5:
        stature = float(max(source.width, source.height))

    shoulder_centre = _add(head, _mul(axis, stature * 0.22))
    hip_centre = _add(head, _mul(axis, stature * 0.60))
    shoulder_half = max(2.5, stature * spec.proportions["shoulder_half_width"])
    torso_half = max(2.4, stature * spec.proportions["torso_half_width"])
    shoulder_left = _add(shoulder_centre, _mul(normal, -shoulder_half))
    shoulder_right = _add(shoulder_centre, _mul(normal, shoulder_half))
    hip_left = _add(hip_centre, _mul(normal, -torso_half * 0.62))
    hip_right = _add(hip_centre, _mul(normal, torso_half * 0.62))

    arm_candidates: list[Point] = []
    for point in body_points:
        longitudinal = _dot(_sub(point, head), axis)
        lateral = abs(_dot(_sub(point, shoulder_centre), normal))
        in_torso = (
            stature * 0.12 <= longitudinal <= stature * 0.67
            and lateral <= torso_half * 0.82
        )
        if not in_torso and longitudinal <= stature * 0.78:
            arm_candidates.append(point)
    arm_first, arm_second = _choose_two_endpoints(
        arm_candidates or body_points, shoulder_centre, stature
    )
    hand_left, hand_right = _assign_endpoints(
        arm_first, arm_second, shoulder_left, shoulder_right
    )
    maximum_arm = stature * 0.58
    if _distance(hand_left, shoulder_left) > maximum_arm:
        delta = _sub(hand_left, shoulder_left)
        hand_left = _add(shoulder_left, _mul(delta, maximum_arm / _distance(hand_left, shoulder_left)))
    if _distance(hand_right, shoulder_right) > maximum_arm:
        delta = _sub(hand_right, shoulder_right)
        hand_right = _add(
            shoulder_right, _mul(delta, maximum_arm / _distance(hand_right, shoulder_right))
        )
    elbow_left = _joint_midpoint(shoulder_left, hand_left, -1.0, stature)
    elbow_right = _joint_midpoint(shoulder_right, hand_right, 1.0, stature)

    leg_candidates = [
        point
        for point in leg_points
        if _dot(_sub(point, head), axis) >= stature * 0.48
    ]
    leg_first, leg_second = _choose_two_endpoints(
        leg_candidates or leg_points, hip_centre, stature
    )
    ankle_left, ankle_right = _assign_endpoints(
        leg_first, leg_second, hip_left, hip_right
    )
    knee_left = _joint_midpoint(hip_left, ankle_left, -0.35, stature)
    knee_right = _joint_midpoint(hip_right, ankle_right, 0.35, stature)

    ground = _centroid(shadow_points)
    if ground is None:
        ground = _add(
            _mul(_add(ankle_left, ankle_right), 0.5),
            _mul(axis, stature * 0.035),
        )

    weapon_tip: Point | None = None
    if spec.weapon == "sling" and other_points:
        body_centre = _mul(_add(shoulder_centre, hip_centre), 0.5)
        candidates = [
            point
            for point in other_points
            if _distance(point, body_centre) >= stature * 0.30
            and min(_distance(point, hand_left), _distance(point, hand_right)) >= stature * 0.08
        ]
        if candidates:
            candidate = max(
                candidates,
                key=lambda point: min(
                    _distance(point, hand_left), _distance(point, hand_right)
                ),
            )
            if min(_distance(candidate, hand_left), _distance(candidate, hand_right)) <= stature * 0.82:
                weapon_tip = candidate

    number = _frame_number(name, spec.group)
    direction = number % 8
    reference_direction = spec.direction_map[direction]
    bbox = alpha.getbbox()
    lying = False
    if bbox:
        lying = (bbox[2] - bbox[0]) > (bbox[3] - bbox[1]) * 1.10 or abs(axis[0]) > 0.72
    region_score = sum(confidence_parts) / 3.0
    arm_score = min(1.0, min(
        _distance(hand_left, shoulder_left), _distance(hand_right, shoulder_right)
    ) / max(1.0, stature * 0.14))
    leg_score = min(1.0, _distance(ankle_left, ankle_right) / max(1.0, stature * 0.08))
    confidence = min(1.0, region_score * 0.72 + arm_score * 0.16 + leg_score * 0.12)
    return Pose(
        head=head,
        axis=axis,
        normal=normal,
        stature=stature,
        shoulder_left=shoulder_left,
        shoulder_right=shoulder_right,
        elbow_left=elbow_left,
        elbow_right=elbow_right,
        hand_left=hand_left,
        hand_right=hand_right,
        hip_left=hip_left,
        hip_right=hip_right,
        knee_left=knee_left,
        knee_right=knee_right,
        ankle_left=ankle_left,
        ankle_right=ankle_right,
        ground=ground,
        weapon_tip=weapon_tip,
        direction=direction,
        reference_direction=reference_direction,
        confidence=confidence,
        lying=lying,
    )


def _shade(colour: Colour, factor: float) -> Colour:
    return tuple(max(0, min(255, round(channel * factor))) for channel in colour)  # type: ignore[return-value]


class _Painter:
    """Supersampled colour and team-mask painter sharing identical geometry."""

    def __init__(self, size: tuple[int, int], spec: UnitSpec) -> None:
        self.native_size = size
        self.spec = spec
        self.scale = spec.supersample
        scaled = (size[0] * self.scale, size[1] * self.scale)
        self.colour = Image.new("RGBA", scaled, (0, 0, 0, 0))
        self.mask = Image.new("RGBA", scaled, spec.team_mask["background"])
        self.draw = ImageDraw.Draw(self.colour, "RGBA")
        self.mask_draw = ImageDraw.Draw(self.mask, "RGBA")

    def p(self, point: Point) -> tuple[int, int]:
        return round(point[0] * self.scale), round(point[1] * self.scale)

    def width(self, value: float) -> int:
        return max(1, round(value * self.scale))

    def line(
        self,
        points: Sequence[Point],
        width: float,
        base: Colour,
        semantic: str,
        *,
        highlight: Colour | None = None,
    ) -> None:
        scaled = [self.p(point) for point in points]
        outline_width = self.width(width + 1.15)
        main_width = self.width(width)
        self.draw.line(
            scaled,
            fill=(*self.spec.palette["outline"], 255),
            width=outline_width,
            joint="curve",
        )
        self.draw.line(scaled, fill=(*base, 255), width=main_width, joint="curve")
        for point in (scaled[0], scaled[-1]):
            radius = main_width // 2
            self.draw.ellipse(
                (point[0] - radius, point[1] - radius, point[0] + radius, point[1] + radius),
                fill=(*base, 255),
            )
        if highlight is not None and width >= 2.2:
            shifted = [(x - self.width(0.35), y - self.width(0.35)) for x, y in scaled]
            self.draw.line(
                shifted,
                fill=(*highlight, 180),
                width=max(1, self.width(width * 0.28)),
                joint="curve",
            )
        self.mask_draw.line(
            scaled,
            fill=self.spec.team_mask[semantic],
            width=outline_width,
            joint="curve",
        )
        for point in (scaled[0], scaled[-1]):
            radius = outline_width // 2
            self.mask_draw.ellipse(
                (point[0] - radius, point[1] - radius, point[0] + radius, point[1] + radius),
                fill=self.spec.team_mask[semantic],
            )

    def polygon(
        self,
        points: Sequence[Point],
        base: Colour,
        semantic: str,
        *,
        highlight_edge: tuple[int, int] | None = None,
    ) -> None:
        scaled = [self.p(point) for point in points]
        self.draw.polygon(scaled, fill=(*base, 255))
        self.draw.line(
            scaled + [scaled[0]],
            fill=(*self.spec.palette["outline"], 255),
            width=self.width(0.9),
            joint="curve",
        )
        if highlight_edge is not None:
            first, second = highlight_edge
            self.draw.line(
                [scaled[first], scaled[second]],
                fill=(*_shade(base, 1.24), 150),
                width=self.width(0.55),
            )
        self.mask_draw.polygon(scaled, fill=self.spec.team_mask[semantic])
        self.mask_draw.line(
            scaled + [scaled[0]],
            fill=self.spec.team_mask[semantic],
            width=self.width(1.2),
            joint="curve",
        )

    def ellipse(
        self,
        centre: Point,
        radius_x: float,
        radius_y: float,
        base: Colour,
        semantic: str,
        *,
        outline: bool = True,
    ) -> None:
        cx, cy = self.p(centre)
        rx = self.width(radius_x)
        ry = self.width(radius_y)
        box = (cx - rx, cy - ry, cx + rx, cy + ry)
        self.draw.ellipse(
            box,
            fill=(*base, 255),
            outline=(*self.spec.palette["outline"], 255) if outline else None,
            width=self.width(0.8) if outline else 1,
        )
        self.mask_draw.ellipse(box, fill=self.spec.team_mask[semantic])

    def reference_piece(
        self,
        piece: _ReferencePiece,
        target_anchor: Point,
        target_end: Point,
        *,
        global_scale: float,
    ) -> None:
        """Rotate/scale a model-authored texture part around its rig joint."""

        source_vector = _sub(piece.end, piece.anchor)
        target_vector = _sub(target_end, target_anchor)
        source_length = max(1.0, math.hypot(*source_vector))
        target_length = max(0.5, math.hypot(*target_vector))
        desired_scale = target_length * self.scale / source_length
        minimum = global_scale * 0.62
        maximum = global_scale * 1.55
        scale = max(minimum, min(maximum, desired_scale))
        source_angle = math.degrees(math.atan2(source_vector[1], source_vector[0]))
        target_angle = math.degrees(math.atan2(target_vector[1], target_vector[0]))
        rotation = target_angle - source_angle

        corners = (
            (0.0, 0.0),
            (float(piece.colour.width), 0.0),
            (0.0, float(piece.colour.height)),
            (float(piece.colour.width), float(piece.colour.height)),
        )
        radius = max(_distance(piece.anchor, corner) for corner in corners) + 3.0
        side = max(8, math.ceil(radius * 2.0))
        centre = side / 2.0

        def centred(image: Image.Image) -> Image.Image:
            canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
            canvas.alpha_composite(
                image,
                (
                    round(centre - piece.anchor[0]),
                    round(centre - piece.anchor[1]),
                ),
            )
            scaled_side = max(2, round(side * scale))
            resized = canvas.resize(
                (scaled_side, scaled_side), Image.Resampling.LANCZOS
            )
            return resized.rotate(
                rotation,
                resample=Image.Resampling.BICUBIC,
                expand=False,
                center=(scaled_side / 2.0, scaled_side / 2.0),
            )

        colour = centred(piece.colour)
        team_mask = centred(piece.team_mask)
        target = self.p(target_anchor)
        destination = (
            round(target[0] - colour.width / 2.0),
            round(target[1] - colour.height / 2.0),
        )
        self.colour.alpha_composite(colour, destination)
        self.mask.alpha_composite(team_mask, destination)

    def finish(self) -> tuple[Image.Image, Image.Image]:
        colour = self.colour.resize(self.native_size, Image.Resampling.LANCZOS)
        mask = self.mask.resize(self.native_size, Image.Resampling.LANCZOS)
        # The game mask is a full lookup texture, including transparent colour
        # pixels; its own alpha must therefore remain fully opaque.
        mask.putalpha(Image.new("L", self.native_size, 255))
        return colour, mask


def _local(pose: Pose, centre: Point, lateral: float, longitudinal: float) -> Point:
    return _add(
        _add(centre, _mul(pose.normal, lateral)),
        _mul(pose.axis, longitudinal),
    )


def _draw_shadow(painter: _Painter, pose: Pose) -> None:
    width = pose.stature * (0.34 if not pose.lying else 0.58)
    height = pose.stature * (0.055 if not pose.lying else 0.085)
    painter.ellipse(
        (pose.ground[0] + 1.2, pose.ground[1] + 1.2),
        width,
        height,
        painter.spec.palette["shadow"],
        "shadow",
        outline=False,
    )


def _draw_blood(painter: _Painter, pose: Pose, frame_number: int, spec: UnitSpec) -> None:
    if not (spec.blood_start <= frame_number <= spec.blood_end) or not pose.lying:
        return
    phase = ((frame_number - spec.blood_start) // 8) % 16
    amount = max(1, min(5, 1 + phase // 3))
    for index in range(amount):
        angle = (frame_number * 0.71 + index * 2.17) % (math.pi * 2.0)
        distance = pose.stature * (0.035 + 0.027 * index)
        centre = (
            pose.ground[0] + math.cos(angle) * distance,
            pose.ground[1] + math.sin(angle) * distance * 0.38,
        )
        painter.ellipse(
            centre,
            pose.stature * (0.025 + index * 0.004),
            pose.stature * (0.011 + index * 0.002),
            spec.palette["blood"] if index % 2 else spec.palette["blood_dark"],
            "shadow",
            outline=False,
        )


def _draw_leg(
    painter: _Painter,
    pose: Pose,
    hip: Point,
    knee: Point,
    ankle: Point,
    *,
    back: bool,
) -> None:
    spec = painter.spec
    stature = pose.stature
    factor = 0.80 if back else 1.0
    thigh_width = stature * spec.proportions["leg_width"]
    painter.line(
        [hip, knee],
        thigh_width,
        _shade(spec.palette["breeches"], factor),
        "cloth",
        highlight=_shade(spec.palette["breeches"], factor * 1.15),
    )
    painter.line(
        [knee, ankle],
        thigh_width * 0.78,
        _shade(spec.palette["wrap"], factor),
        "cloth",
        highlight=_shade(spec.palette["wrap"], factor * 1.13),
    )
    segment = _sub(ankle, knee)
    segment_length = max(1.0, math.hypot(*segment))
    segment_normal = (-segment[1] / segment_length, segment[0] / segment_length)
    for fraction in (0.20, 0.38, 0.56, 0.74):
        centre = _add(knee, _mul(segment, fraction))
        half = thigh_width * 0.42
        painter.line(
            [
                _add(centre, _mul(segment_normal, -half)),
                _add(centre, _mul(segment_normal, half)),
            ],
            max(0.55, stature * 0.010),
            _shade(spec.palette["wrap_dark"], factor),
            "cloth",
        )
    toe_sign = -1.0 if pose.reference_direction in {0, 1, 2, 3} else 1.0
    toe = _add(ankle, _mul(pose.normal, toe_sign * stature * 0.055))
    painter.line(
        [ankle, toe],
        stature * spec.proportions["boot_width"],
        _shade(spec.palette["leather"], factor),
        "equipment",
        highlight=_shade(spec.palette["leather"], factor * 1.16),
    )


def _draw_arm(
    painter: _Painter,
    pose: Pose,
    shoulder: Point,
    elbow: Point,
    hand: Point,
    *,
    back: bool,
) -> None:
    spec = painter.spec
    factor = 0.78 if back else 1.0
    width = pose.stature * spec.proportions["arm_width"]
    painter.line(
        [shoulder, elbow, hand],
        width,
        _shade(spec.palette["tunic"], factor),
        "cloth",
        highlight=_shade(spec.palette["tunic_light"], factor),
    )
    painter.ellipse(
        hand,
        pose.stature * spec.proportions["hand_radius"],
        pose.stature * spec.proportions["hand_radius"] * 0.86,
        _shade(spec.palette["skin"], factor),
        "body",
    )


def _draw_torso(painter: _Painter, pose: Pose) -> None:
    spec = painter.spec
    stature = pose.stature
    shoulder_centre = _mul(_add(pose.shoulder_left, pose.shoulder_right), 0.5)
    hip_centre = _mul(_add(pose.hip_left, pose.hip_right), 0.5)
    torso_half = stature * spec.proportions["torso_half_width"]
    tunic_bottom = _add(hip_centre, _mul(pose.axis, stature * 0.13))
    points = [
        _add(pose.shoulder_left, _mul(pose.normal, torso_half * 0.14)),
        _add(pose.shoulder_right, _mul(pose.normal, -torso_half * 0.14)),
        _add(tunic_bottom, _mul(pose.normal, torso_half * 1.05)),
        _add(tunic_bottom, _mul(pose.normal, -torso_half * 1.05)),
    ]
    painter.polygon(points, spec.palette["tunic"], "cloth", highlight_edge=(0, 1))

    cape_depth = stature * spec.proportions["cape_depth"]
    cape_centre = _add(shoulder_centre, _mul(pose.axis, cape_depth))
    cape_half = torso_half * 1.38
    cape_points: list[Point] = [
        _add(pose.shoulder_left, _mul(pose.normal, -torso_half * 0.28)),
        _add(pose.shoulder_right, _mul(pose.normal, torso_half * 0.28)),
    ]
    for step in range(6, -1, -1):
        lateral = -cape_half + (2.0 * cape_half * step / 6.0)
        tooth = stature * (0.018 if step % 2 else -0.008)
        cape_points.append(_local(pose, cape_centre, lateral, tooth))
    painter.polygon(cape_points, spec.palette["team"], "body", highlight_edge=(0, 1))

    belt_left = _add(hip_centre, _mul(pose.normal, -torso_half * 0.92))
    belt_right = _add(hip_centre, _mul(pose.normal, torso_half * 0.92))
    painter.line(
        [belt_left, belt_right],
        stature * 0.030,
        spec.palette["leather"],
        "equipment",
        highlight=spec.palette["leather_dark"],
    )
    # Asymmetric equipment must remain attached to anatomical sides while the
    # actor rotates.  reference_direction 0 is front and 4 is back, so cosine
    # moves the wearer's right hip continuously from screen-left to
    # screen-right.  A mirrored-per-view shortcut is forbidden: it is exactly
    # what made the first technical reference swap the bag in rear views.
    right_screen = math.cos(pose.reference_direction * math.pi / 4.0)
    stone_bag = _local(
        pose,
        hip_centre,
        right_screen * torso_half * 1.02,
        stature * 0.095,
    )
    utility_pouch = _local(
        pose,
        hip_centre,
        -right_screen * torso_half * 0.90,
        stature * 0.055,
    )
    left_shoulder = _local(
        pose,
        shoulder_centre,
        -right_screen * torso_half * 0.92,
        -stature * 0.015,
    )
    painter.line(
        [left_shoulder, stone_bag],
        stature * 0.024,
        spec.palette["leather"],
        "equipment",
        highlight=spec.palette["leather_dark"],
    )
    painter.ellipse(
        stone_bag,
        stature * spec.proportions["pouch_radius"] * 1.18,
        stature * spec.proportions["pouch_radius"] * 1.38,
        spec.palette["leather"],
        "equipment",
    )
    bag_top = _add(stone_bag, _mul(pose.axis, -stature * 0.055))
    painter.line(
        [
            _add(bag_top, _mul(pose.normal, -stature * 0.052)),
            _add(bag_top, _mul(pose.normal, stature * 0.052)),
        ],
        stature * 0.025,
        spec.palette["leather_dark"],
        "equipment",
    )
    # Three stones survive the native downsample more reliably than six tiny
    # dots, while still reading as a filled ammunition satchel in game scale.
    for lateral, longitudinal in ((-0.035, -0.070), (0.0, -0.078), (0.035, -0.068)):
        painter.ellipse(
            _local(pose, stone_bag, stature * lateral, stature * longitudinal),
            stature * 0.027,
            stature * 0.023,
            spec.palette["metal"],
            "equipment",
        )
    painter.ellipse(
        utility_pouch,
        stature * spec.proportions["pouch_radius"] * 0.68,
        stature * spec.proportions["pouch_radius"] * 0.86,
        spec.palette["leather"],
        "equipment",
    )


def _draw_head(painter: _Painter, pose: Pose) -> None:
    spec = painter.spec
    stature = pose.stature
    radius = stature * spec.proportions["head_radius"]
    face_visible = pose.reference_direction in {0, 1, 2, 6, 7}
    face = _add(pose.head, _mul(pose.axis, radius * 0.18))
    if face_visible:
        painter.ellipse(
            face,
            radius * 0.60,
            radius * 0.78,
            spec.palette["skin"],
            "body",
        )
        nose_side = -0.28 if pose.reference_direction in {1, 2} else 0.28
        if pose.reference_direction in {6, 7}:
            nose_side *= -1.0
        painter.ellipse(
            _local(pose, face, nose_side * radius, radius * 0.05),
            radius * 0.10,
            radius * 0.08,
            spec.palette["skin_light"],
            "body",
            outline=False,
        )
    else:
        painter.ellipse(
            face,
            radius * 0.62,
            radius * 0.74,
            spec.palette["skin_dark"],
            "body",
        )
    if spec.headwear == "none":
        return
    crown = _local(pose, pose.head, 0.0, -radius * 0.38)
    if spec.headwear == "felt_hat":
        # Soft, asymmetrical edges and a broad drooping brim distinguish this
        # from a kettle helmet even after the sprite is reduced to game size.
        # No metal palette entry is touched on this branch.
        crown_points = [
            _local(pose, crown, -radius * 0.72, radius * 0.46),
            _local(pose, crown, -radius * 0.55, -radius * 0.18),
            _local(pose, crown, -radius * 0.10, -radius * 0.86),
            _local(pose, crown, radius * 0.18, -radius * 0.82),
            _local(pose, crown, radius * 0.57, -radius * 0.15),
            _local(pose, crown, radius * 0.70, radius * 0.47),
        ]
        painter.polygon(
            crown_points,
            spec.palette["felt"],
            "head",
            highlight_edge=(1, 2),
        )
        seam_top = _local(pose, crown, 0.0, -radius * 0.70)
        seam_bottom = _local(pose, crown, 0.0, radius * 0.08)
        painter.line(
            [seam_top, seam_bottom],
            radius * 0.07,
            spec.palette["felt_dark"],
            "head",
        )
        band_left = _local(pose, crown, -radius * 0.68, radius * 0.20)
        band_right = _local(pose, crown, radius * 0.68, radius * 0.20)
        painter.line(
            [band_left, band_right],
            radius * 0.22,
            spec.palette["team"],
            "body",
            highlight=spec.palette["team_light"],
        )
        brim_points = [
            _local(pose, crown, -radius * 1.06, radius * 0.43),
            _local(pose, crown, -radius * 0.62, radius * 0.55),
            _local(pose, crown, 0.0, radius * 0.49),
            _local(pose, crown, radius * 0.68, radius * 0.60),
            _local(pose, crown, radius * 1.04, radius * 0.45),
            _local(pose, crown, radius * 0.72, radius * 0.70),
            _local(pose, crown, 0.0, radius * 0.68),
            _local(pose, crown, -radius * 0.70, radius * 0.72),
        ]
        painter.polygon(brim_points, spec.palette["felt_dark"], "head")
        painter.line(
            [
                _local(pose, crown, -radius * 0.82, radius * 0.55),
                _local(pose, crown, radius * 0.82, radius * 0.57),
            ],
            radius * 0.08,
            spec.palette["felt_light"],
            "head",
        )
        return

    helmet_points = [
        _local(pose, crown, -radius * 0.78, radius * 0.55),
        _local(pose, crown, -radius * 0.58, -radius * 0.25),
        _local(pose, crown, 0.0, -radius * 0.78),
        _local(pose, crown, radius * 0.58, -radius * 0.25),
        _local(pose, crown, radius * 0.78, radius * 0.55),
    ]
    painter.polygon(helmet_points, spec.palette["metal"], "head", highlight_edge=(1, 2))
    band_left = _local(pose, crown, -radius * 0.70, radius * 0.28)
    band_right = _local(pose, crown, radius * 0.70, radius * 0.28)
    painter.line(
        [band_left, band_right],
        radius * 0.24,
        spec.palette["team"],
        "body",
        highlight=spec.palette["team_light"],
    )
    brim_left = _local(pose, crown, -radius * 0.96, radius * 0.57)
    brim_right = _local(pose, crown, radius * 0.96, radius * 0.57)
    painter.line(
        [brim_left, brim_right],
        radius * 0.20,
        spec.palette["metal_dark"],
        "head",
        highlight=spec.palette["metal_light"],
    )


def _draw_sling(painter: _Painter, pose: Pose) -> None:
    if painter.spec.weapon != "sling":
        return
    if pose.weapon_tip is not None:
        left_distance = _distance(pose.weapon_tip, pose.hand_left)
        right_distance = _distance(pose.weapon_tip, pose.hand_right)
        hand = pose.hand_left if left_distance <= right_distance else pose.hand_right
        tip = pose.weapon_tip
    else:
        hand = pose.hand_right
        tip = _local(pose, hand, pose.stature * 0.035, pose.stature * 0.25)
    delta = _sub(tip, hand)
    length = max(1.0, math.hypot(*delta))
    normal = (-delta[1] / length, delta[0] / length)
    separation = max(0.7, pose.stature * 0.009)
    for sign in (-1.0, 1.0):
        painter.line(
            [
                _add(hand, _mul(normal, sign * separation)),
                _add(tip, _mul(normal, sign * separation * 0.45)),
            ],
            max(0.45, pose.stature * 0.008),
            painter.spec.palette["leather"],
            "equipment",
        )
    painter.ellipse(
        tip,
        pose.stature * 0.025,
        pose.stature * 0.025,
        painter.spec.palette["metal"],
        "equipment",
    )


def _visible_count(image: Image.Image) -> int:
    return sum(alpha > 12 for alpha in image.getchannel("A").get_flattened_data())


def _border_count(image: Image.Image) -> int:
    alpha = image.getchannel("A")
    points: set[tuple[int, int]] = set()
    for x in range(image.width):
        points.add((x, 0))
        points.add((x, image.height - 1))
    for y in range(image.height):
        points.add((0, y))
        points.add((image.width - 1, y))
    return sum(alpha.getpixel(point) > 12 for point in points)


def render_unit_frame(
    source: Image.Image, mask: Image.Image, spec: UnitSpec, *, name: str
) -> tuple[Image.Image, Image.Image, FrameRenderStats]:
    """Render one wholly new frame while retaining only the source motion rig."""

    donor = source.convert("RGBA")
    donor_mask = mask.convert("RGBA")
    pose = extract_pose(donor, donor_mask, spec, name)
    if pose.confidence < spec.min_pose_confidence:
        raise UnitProductionError(
            f"{name}: pose confidence {pose.confidence:.3f} below "
            f"{spec.min_pose_confidence:.3f}"
        )
    painter = _Painter(donor.size, spec)
    frame_number = _frame_number(name, spec.group)
    _draw_shadow(painter, pose)
    _draw_blood(painter, pose, frame_number, spec)

    back_is_left = pose.reference_direction in {0, 1, 2, 3}
    leg_order = [
        (pose.hip_left, pose.knee_left, pose.ankle_left, back_is_left),
        (pose.hip_right, pose.knee_right, pose.ankle_right, not back_is_left),
    ]
    leg_order.sort(key=lambda item: not item[3])
    for hip, knee, ankle, back in leg_order:
        _draw_leg(painter, pose, hip, knee, ankle, back=back)

    arm_order = [
        (pose.shoulder_left, pose.elbow_left, pose.hand_left, back_is_left),
        (pose.shoulder_right, pose.elbow_right, pose.hand_right, not back_is_left),
    ]
    arm_order.sort(key=lambda item: not item[3])
    for shoulder, elbow, hand, back in arm_order:
        _draw_arm(painter, pose, shoulder, elbow, hand, back=back)
    _draw_torso(painter, pose)
    _draw_head(painter, pose)
    _draw_sling(painter, pose)
    output, output_mask = painter.finish()

    source_alpha = donor.getchannel("A")
    output_alpha = output.getchannel("A")
    alpha_changed = sum(
        before != after
        for before, after in zip(
            source_alpha.get_flattened_data(), output_alpha.get_flattened_data()
        )
    )
    mask_changed = sum(
        before != after
        for before, after in zip(
            donor_mask.get_flattened_data(), output_mask.get_flattened_data()
        )
    )
    source_visible = _visible_count(donor)
    output_visible = _visible_count(output)
    union = max(1, sum(
        before > 12 or after > 12
        for before, after in zip(
            source_alpha.get_flattened_data(), output_alpha.get_flattened_data()
        )
    ))
    alpha_change_ratio = alpha_changed / union
    equal_rgb = 0
    overlap = 0
    for source_pixel, output_pixel in zip(
        donor.get_flattened_data(), output.get_flattened_data()
    ):
        if source_pixel[3] > 12 and output_pixel[3] > 12:
            overlap += 1
            if source_pixel[:3] == output_pixel[:3]:
                equal_rgb += 1
    equal_ratio = equal_rgb / max(1, overlap)
    border = _border_count(output)
    border_ratio = border / max(1, output_visible)
    if alpha_change_ratio < spec.min_alpha_change_ratio:
        raise UnitProductionError(
            f"{name}: new silhouette ratio {alpha_change_ratio:.3f} below "
            f"{spec.min_alpha_change_ratio:.3f}; possible recolour"
        )
    if equal_ratio > spec.max_source_rgb_equal_ratio:
        raise UnitProductionError(
            f"{name}: donor RGB equality {equal_ratio:.3f} above "
            f"{spec.max_source_rgb_equal_ratio:.3f}; possible donor leakage"
        )
    if border_ratio > spec.max_border_ratio:
        raise UnitProductionError(
            f"{name}: visible border ratio {border_ratio:.3f} above "
            f"{spec.max_border_ratio:.3f}; generated model may be clipped"
        )
    return output, output_mask, FrameRenderStats(
        name=name,
        width=output.width,
        height=output.height,
        direction=pose.direction,
        reference_direction=pose.reference_direction,
        pose_confidence=pose.confidence,
        source_visible_pixels=source_visible,
        output_visible_pixels=output_visible,
        alpha_changed_pixels=alpha_changed,
        mask_changed_pixels=mask_changed,
        source_rgb_equal_pixels=equal_rgb,
        source_rgb_equal_ratio=equal_ratio,
        alpha_change_ratio=alpha_change_ratio,
        border_visible_pixels=border,
        border_ratio=border_ratio,
        colour_sha256=hashlib.sha256(output.tobytes()).hexdigest(),
        mask_sha256=hashlib.sha256(output_mask.tobytes()).hexdigest(),
    )


def _slot_counts(names: Iterable[str], group: str) -> tuple[int, int]:
    main = alternate = 0
    for name in names:
        suffix = name.removeprefix(group + "-")
        if suffix.endswith("x"):
            alternate += 1
        else:
            main += 1
    return main, alternate


def _name_digest(names: Iterable[str]) -> str:
    digest = hashlib.sha256()
    for name in sorted(names):
        encoded = name.encode("utf-8")
        digest.update(len(encoded).to_bytes(4, "big"))
        digest.update(encoded)
    return digest.hexdigest()


def _payload_digest(paths: Iterable[Path], root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        payload = path.read_bytes()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def _load_export_contract(source_dir: Path, spec: UnitSpec) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    index_path = source_dir / "index.json"
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UnitProductionError(f"Cannot read source export {index_path}: {exc}") from exc
    if not isinstance(index, dict) or index.get("schema_version") != 1:
        raise UnitProductionError("Source export must use sprite index schema 1")
    if index.get("group") != spec.group:
        raise UnitProductionError(
            f"Source export group {index.get('group')!r} does not match {spec.group}"
        )
    frames = index.get("frames")
    if not isinstance(frames, list) or len(frames) != spec.expected_frames:
        raise UnitProductionError(
            f"Expected {spec.expected_frames} source frames, found "
            f"{len(frames) if isinstance(frames, list) else 'invalid'}"
        )
    typed_frames: list[dict[str, Any]] = []
    names: list[str] = []
    for position, raw_frame in enumerate(frames):
        if not isinstance(raw_frame, dict):
            raise UnitProductionError(f"Frame {position} is not an object")
        for key in ("name", "file", "mask_file", "width", "height"):
            if key not in raw_frame:
                raise UnitProductionError(f"Frame {position} is missing {key}")
        name = raw_frame["name"]
        if not isinstance(name, str):
            raise UnitProductionError(f"Frame {position}.name is invalid")
        names.append(name)
        typed_frames.append(raw_frame)
    if len(names) != len(set(names)):
        raise UnitProductionError("Source export contains duplicate frame names")
    main, alternate = _slot_counts(names, spec.group)
    if (main, alternate) != (spec.expected_main, spec.expected_alternate):
        raise UnitProductionError(
            f"Expected main/alternate {spec.expected_main}/{spec.expected_alternate}, "
            f"found {main}/{alternate}"
        )
    return index, typed_frames


def build_unit_series(source_dir: Path, output_dir: Path, spec: UnitSpec) -> UnitBuildReport:
    """Render a complete frame family atomically and pin all quality evidence."""

    source_dir = source_dir.resolve()
    output_dir = output_dir.resolve()
    index, frames = _load_export_contract(source_dir, spec)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temp_root = Path(tempfile.mkdtemp(prefix=output_dir.name + ".tmp-", dir=output_dir.parent))
    stats: list[FrameRenderStats] = []
    try:
        shutil.copy2(source_dir / "index.json", temp_root / "index.json")
        for frame in frames:
            name = str(frame["name"])
            filename = str(frame["file"])
            mask_filename = str(frame["mask_file"])
            colour_path = source_dir / filename
            mask_path = source_dir / mask_filename
            if not colour_path.is_file() or not mask_path.is_file():
                raise UnitProductionError(f"{name}: colour or team mask is missing")
            with Image.open(colour_path) as opened:
                colour = opened.convert("RGBA")
            with Image.open(mask_path) as opened:
                mask = opened.convert("RGBA")
            expected_size = (int(frame["width"]), int(frame["height"]))
            if colour.size != expected_size or mask.size != expected_size:
                raise UnitProductionError(
                    f"{name}: expected {expected_size}, found {colour.size}/{mask.size}"
                )
            rendered, rendered_mask, frame_stats = render_unit_frame(
                colour, mask, spec, name=name
            )
            rendered.save(temp_root / filename, format="PNG", optimize=False, compress_level=9)
            rendered_mask.save(
                temp_root / mask_filename, format="PNG", optimize=False, compress_level=9
            )
            stats.append(frame_stats)

        names = [str(frame["name"]) for frame in frames]
        main, alternate = _slot_counts(names, spec.group)
        payload_paths = list(temp_root.glob("*.png"))
        report = UnitBuildReport(
            schema_version=REPORT_SCHEMA,
            unit_id=spec.unit_id,
            group=spec.group,
            renderer="articulated-reference-v1",
            frame_count=len(stats),
            main_count=main,
            alternate_count=alternate,
            source_names_sha256=_name_digest(names),
            reference_sha256=spec.reference_sha256,
            output_payload_sha256=_payload_digest(payload_paths, temp_root),
            min_pose_confidence=min(item.pose_confidence for item in stats),
            max_source_rgb_equal_ratio=max(item.source_rgb_equal_ratio for item in stats),
            min_alpha_change_ratio=min(item.alpha_change_ratio for item in stats),
            max_border_ratio=max(item.border_ratio for item in stats),
            changed_alpha_frames=sum(item.alpha_changed_pixels > 0 for item in stats),
            changed_mask_frames=sum(item.mask_changed_pixels > 0 for item in stats),
        )
        if report.changed_alpha_frames != spec.expected_frames:
            raise UnitProductionError("Not every frame received a new silhouette")
        if report.changed_mask_frames != spec.expected_frames:
            raise UnitProductionError("Not every frame received a new team mask")
        (temp_root / "unit-production-report.json").write_text(
            json.dumps(
                {**asdict(report), "spec": spec.path.as_posix(), "frames": [asdict(item) for item in stats]},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        if output_dir.exists():
            shutil.rmtree(output_dir)
        temp_root.replace(output_dir)
        return report
    except Exception:
        shutil.rmtree(temp_root, ignore_errors=True)
        raise


def render_prototype(
    source_dir: Path,
    output_dir: Path,
    spec: UnitSpec,
    frame_names: Sequence[str],
) -> list[FrameRenderStats]:
    """Render a selected cross-section without pretending it is production-ready."""

    source_dir = source_dir.resolve()
    output_dir = output_dir.resolve()
    _, frames = _load_export_contract(source_dir, spec)
    by_name = {str(frame["name"]): frame for frame in frames}
    missing = sorted(set(frame_names) - set(by_name))
    if missing:
        raise UnitProductionError(f"Unknown prototype frames: {missing}")
    output_dir.mkdir(parents=True, exist_ok=True)
    stats: list[FrameRenderStats] = []
    for name in frame_names:
        frame = by_name[name]
        with Image.open(source_dir / str(frame["file"])) as opened:
            colour = opened.convert("RGBA")
        with Image.open(source_dir / str(frame["mask_file"])) as opened:
            mask = opened.convert("RGBA")
        rendered, rendered_mask, frame_stats = render_unit_frame(colour, mask, spec, name=name)
        rendered.save(output_dir / str(frame["file"]), format="PNG", compress_level=9)
        rendered_mask.save(output_dir / str(frame["mask_file"]), format="PNG", compress_level=9)
        stats.append(frame_stats)
    (output_dir / "prototype-report.json").write_text(
        json.dumps([asdict(item) for item in stats], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return stats


def build_comparison_sheet(
    source_dir: Path,
    rendered_dir: Path,
    output_path: Path,
    spec: UnitSpec,
    frame_names: Sequence[str],
) -> None:
    """Build a labelled donor/new/mask board for human adversarial review."""

    _, frames = _load_export_contract(source_dir.resolve(), spec)
    by_name = {str(frame["name"]): frame for frame in frames}
    scale = 4
    cell_w = 180
    cell_h = 170
    sheet = Image.new("RGBA", (cell_w * len(frame_names), cell_h * 3), (31, 32, 35, 255))
    draw = ImageDraw.Draw(sheet)
    labels = ("Pose only (donor)", "New European render", "New team mask")
    for column, name in enumerate(frame_names):
        frame = by_name.get(name)
        if frame is None:
            raise UnitProductionError(f"Unknown sheet frame {name}")
        paths = (
            source_dir / str(frame["file"]),
            rendered_dir / str(frame["file"]),
            rendered_dir / str(frame["mask_file"]),
        )
        for row, path in enumerate(paths):
            if not path.is_file():
                raise UnitProductionError(f"Comparison input is missing: {path}")
            with Image.open(path) as opened:
                image = opened.convert("RGBA")
            image = image.resize((image.width * scale, image.height * scale), Image.Resampling.NEAREST)
            x = column * cell_w + (cell_w - image.width) // 2
            y = row * cell_h + 30 + (cell_h - 35 - image.height) // 2
            sheet.alpha_composite(image, (x, y))
            draw.text((column * cell_w + 5, row * cell_h + 5), f"{labels[row]} | {name}", fill=(238, 238, 238, 255))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.convert("RGB").save(output_path, format="PNG", compress_level=9)

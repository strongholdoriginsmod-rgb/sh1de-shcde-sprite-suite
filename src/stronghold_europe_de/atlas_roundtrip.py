from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
from math import isfinite
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

from .gm_atlas import AtlasFrame, FrameSlot, parse_loader_frame_name


class AtlasRoundtripError(ValueError):
    """Raised when serialized GM-atlas output does not round-trip exactly."""


@dataclass(frozen=True, order=True)
class AtlasRect:
    """An atlas rectangle expressed in the loader's bottom-left coordinates."""

    x: int
    y: int
    width: int
    height: int

    def pillow_box(self, atlas_height: int) -> tuple[int, int, int, int]:
        top = atlas_height - self.y - self.height
        return (self.x, top, self.x + self.width, top + self.height)

    def overlaps(self, other: "AtlasRect") -> bool:
        return not (
            self.x + self.width <= other.x
            or other.x + other.width <= self.x
            or self.y + self.height <= other.y
            or other.y + other.height <= self.y
        )


@dataclass(frozen=True)
class RoundtrippedFrame:
    name: str
    slot: FrameSlot
    rect: AtlasRect
    pillow_box: tuple[int, int, int, int]
    main_sha256: str
    mask_sha256: str | None


@dataclass(frozen=True)
class AtlasRoundtripResult:
    atlas_size: tuple[int, int]
    has_mask: bool
    unique_rect_count: int
    frames: tuple[RoundtrippedFrame, ...]


@dataclass(frozen=True)
class _ParsedFrame:
    name: str
    slot: FrameSlot
    rect: AtlasRect
    pivot_x: float
    pivot_y: float
    pixels_per_unit: float


def _pixel_digest(image: Image.Image) -> str:
    return hashlib.sha256(image.tobytes()).hexdigest()


def _require_number(value: object, label: str) -> float:
    if isinstance(value, bool):
        raise AtlasRoundtripError(f"{label} must be a finite number")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise AtlasRoundtripError(f"{label} must be a finite number") from exc
    if not isfinite(result):
        raise AtlasRoundtripError(f"{label} must be a finite number")
    return result


def _expected_by_name(
    expected_frames: Sequence[AtlasFrame],
    gm_file_name: str,
    dash_format: bool,
) -> tuple[dict[str, AtlasFrame], bool]:
    if not expected_frames:
        raise AtlasRoundtripError("Expected frame set is empty")
    by_name: dict[str, AtlasFrame] = {}
    slots: set[FrameSlot] = set()
    mask_presence: set[bool] = set()
    for index, frame in enumerate(expected_frames):
        if not isinstance(frame, AtlasFrame):
            raise AtlasRoundtripError(
                f"Expected frame {index} is not a gm_atlas.AtlasFrame"
            )
        parsed_slot = parse_loader_frame_name(
            frame.name, gm_file_name, dash_format
        )
        if parsed_slot is None or parsed_slot != frame.slot:
            raise AtlasRoundtripError(
                f"Expected frame name/slot mismatch: {frame.name!r} / {frame.slot}"
            )
        if frame.name in by_name:
            raise AtlasRoundtripError(f"Duplicate expected frame name: {frame.name}")
        if frame.slot in slots:
            raise AtlasRoundtripError(f"Duplicate expected loader slot: {frame.slot}")
        if frame.image.mode != "RGBA" or frame.image.width <= 0 or frame.image.height <= 0:
            raise AtlasRoundtripError(
                f"Expected main frame is not positive-size RGBA: {frame.name}"
            )
        if frame.mask is not None and (
            frame.mask.mode != "RGBA" or frame.mask.size != frame.image.size
        ):
            raise AtlasRoundtripError(
                f"Expected mask mode/geometry differs for {frame.name}"
            )
        if (
            not isfinite(frame.pivot_x)
            or not isfinite(frame.pivot_y)
            or not isfinite(frame.pixels_per_unit)
            or frame.pixels_per_unit <= 0
        ):
            raise AtlasRoundtripError(f"Expected metadata is invalid for {frame.name}")
        by_name[frame.name] = frame
        slots.add(frame.slot)
        mask_presence.add(frame.mask is not None)
    if len(mask_presence) != 1:
        raise AtlasRoundtripError(
            "Expected frames mix masked and unmasked entries in one GM atlas"
        )
    return by_name, mask_presence == {True}


def _parse_rect(raw: object, name: str, atlas_size: tuple[int, int]) -> AtlasRect:
    if not isinstance(raw, Mapping):
        raise AtlasRoundtripError(f"atlas.json rect is not an object for {name}")
    values: list[int] = []
    for field in ("x", "y", "w", "h"):
        value = raw.get(field)
        if isinstance(value, bool) or not isinstance(value, int):
            raise AtlasRoundtripError(
                f"atlas.json rect field {field} is not integral for {name}"
            )
        values.append(value)
    x, y, width, height = values
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        raise AtlasRoundtripError(f"atlas.json rect is invalid for {name}")
    atlas_width, atlas_height = atlas_size
    if x + width > atlas_width or y + height > atlas_height:
        raise AtlasRoundtripError(f"atlas.json rect escapes the atlas for {name}")
    return AtlasRect(x=x, y=y, width=width, height=height)


def _parse_json_frames(
    atlas_json: Mapping[str, Any],
    atlas_size: tuple[int, int],
    gm_file_name: str,
    dash_format: bool,
) -> tuple[_ParsedFrame, ...]:
    raw_frames = atlas_json.get("frames")
    if not isinstance(raw_frames, list) or not raw_frames:
        raise AtlasRoundtripError("atlas.json frames must be a non-empty list")
    default_ppu = atlas_json.get("pixelsPerUnit")
    parsed: list[_ParsedFrame] = []
    names: set[str] = set()
    slots: set[FrameSlot] = set()
    for index, raw_frame in enumerate(raw_frames):
        label = f"atlas.json frames[{index}]"
        if not isinstance(raw_frame, Mapping):
            raise AtlasRoundtripError(f"{label} is not an object")
        name = raw_frame.get("name")
        if not isinstance(name, str) or not name:
            raise AtlasRoundtripError(f"{label}.name must be a non-empty string")
        if name in names:
            raise AtlasRoundtripError(f"Duplicate atlas frame name: {name}")
        slot = parse_loader_frame_name(name, gm_file_name, dash_format)
        if slot is None:
            raise AtlasRoundtripError(f"Unparseable atlas frame name: {name!r}")
        if slot in slots:
            raise AtlasRoundtripError(f"Duplicate atlas loader slot: {slot}")
        names.add(name)
        slots.add(slot)

        rect = _parse_rect(raw_frame.get("rect"), name, atlas_size)
        raw_pivot = raw_frame.get("pivot")
        if not isinstance(raw_pivot, Mapping):
            raise AtlasRoundtripError(f"atlas.json pivot is not an object for {name}")
        pivot_x = _require_number(raw_pivot.get("x"), f"{name}.pivot.x")
        pivot_y = _require_number(raw_pivot.get("y"), f"{name}.pivot.y")
        ppu = _require_number(
            raw_frame.get("pixelsPerUnit", default_ppu),
            f"{name}.pixelsPerUnit",
        )
        if ppu <= 0:
            raise AtlasRoundtripError(f"{name}.pixelsPerUnit must be positive")
        parsed.append(
            _ParsedFrame(
                name=name,
                slot=slot,
                rect=rect,
                pivot_x=pivot_x,
                pivot_y=pivot_y,
                pixels_per_unit=ppu,
            )
        )
    return tuple(parsed)


def _reject_unequal_overlaps(frames: Sequence[_ParsedFrame]) -> None:
    for index, left in enumerate(frames):
        for right in frames[index + 1 :]:
            if left.rect != right.rect and left.rect.overlaps(right.rect):
                raise AtlasRoundtripError(
                    f"Unequal atlas rects overlap: {left.name} and {right.name}"
                )


def _verify_shared_rect_expectations(
    frames: Sequence[_ParsedFrame],
    expected: Mapping[str, AtlasFrame],
) -> None:
    names_by_rect: dict[AtlasRect, list[str]] = {}
    for frame in frames:
        names_by_rect.setdefault(frame.rect, []).append(frame.name)
    for rect, names in names_by_rect.items():
        if len(names) < 2:
            continue
        canonical = expected[names[0]]
        canonical_main = canonical.image.tobytes()
        canonical_mask = canonical.mask.tobytes() if canonical.mask is not None else None
        for name in names[1:]:
            candidate = expected[name]
            candidate_mask = (
                candidate.mask.tobytes() if candidate.mask is not None else None
            )
            if (
                candidate.image.size != canonical.image.size
                or candidate.image.tobytes() != canonical_main
                or candidate_mask != canonical_mask
            ):
                raise AtlasRoundtripError(
                    f"Deduplicated rect {rect} maps non-identical expected RGBA "
                    f"frames: {names[0]} and {name}"
                )


def verify_atlas_roundtrip(
    atlas_json: Mapping[str, Any],
    atlas: Image.Image,
    mask: Image.Image | None,
    expected_frames: Sequence[AtlasFrame],
    *,
    gm_file_name: str,
    dash_format: bool,
) -> AtlasRoundtripResult:
    """Verify exact logical-frame recovery from a serialized GM atlas.

    Rectangles in ``atlas_json`` are interpreted with the SHCDE-SE/Unity
    bottom-left origin and converted to Pillow's top-left crop coordinates.
    Identical rectangles may be shared only by byte-identical expected main
    and mask frames. Any unequal overlap, missing logical frame, metadata drift,
    or pixel drift raises :class:`AtlasRoundtripError`.
    """

    if not isinstance(atlas_json, Mapping):
        raise AtlasRoundtripError("atlas_json must be a mapping")
    if not isinstance(gm_file_name, str) or not gm_file_name:
        raise AtlasRoundtripError("gm_file_name must be a non-empty string")
    if not isinstance(dash_format, bool):
        raise AtlasRoundtripError("dash_format must be boolean")
    if atlas.mode != "RGBA" or atlas.width <= 0 or atlas.height <= 0:
        raise AtlasRoundtripError("atlas.png must be a positive-size RGBA image")

    expected, requires_mask = _expected_by_name(
        expected_frames, gm_file_name, dash_format
    )
    if requires_mask:
        if mask is None:
            raise AtlasRoundtripError("atlas_m.png is required by expected frames")
        if mask.mode != "RGBA" or mask.size != atlas.size:
            raise AtlasRoundtripError(
                "atlas_m.png must be RGBA and match atlas.png geometry"
            )
    elif mask is not None:
        raise AtlasRoundtripError(
            "atlas_m.png was supplied for an unmasked expected frame set"
        )

    parsed = _parse_json_frames(
        atlas_json, atlas.size, gm_file_name, dash_format
    )
    actual_names = {frame.name for frame in parsed}
    expected_names = set(expected)
    if actual_names != expected_names:
        raise AtlasRoundtripError(
            "Atlas logical frame set differs from expected: "
            f"missing={sorted(expected_names - actual_names)}, "
            f"extra={sorted(actual_names - expected_names)}"
        )
    _reject_unequal_overlaps(parsed)
    _verify_shared_rect_expectations(parsed, expected)

    roundtripped: list[RoundtrippedFrame] = []
    for frame in parsed:
        intended = expected[frame.name]
        if frame.slot != intended.slot:
            raise AtlasRoundtripError(
                f"Loader slot differs for {frame.name}: "
                f"actual={frame.slot} expected={intended.slot}"
            )
        if (frame.rect.width, frame.rect.height) != intended.image.size:
            raise AtlasRoundtripError(
                f"Rect geometry differs for {frame.name}: "
                f"actual={(frame.rect.width, frame.rect.height)} "
                f"expected={intended.image.size}"
            )
        if (
            frame.pivot_x != intended.pivot_x
            or frame.pivot_y != intended.pivot_y
            or frame.pixels_per_unit != intended.pixels_per_unit
        ):
            raise AtlasRoundtripError(
                f"Serialized pivot/PPU differs for {frame.name}"
            )

        pillow_box = frame.rect.pillow_box(atlas.height)
        main_crop = atlas.crop(pillow_box)
        expected_main = intended.image.tobytes()
        actual_main = main_crop.tobytes()
        if actual_main != expected_main:
            raise AtlasRoundtripError(
                f"Main RGBA mismatch for {frame.name}: "
                f"expected={hashlib.sha256(expected_main).hexdigest()} "
                f"actual={hashlib.sha256(actual_main).hexdigest()}"
            )

        mask_digest: str | None = None
        if requires_mask:
            assert mask is not None and intended.mask is not None
            mask_crop = mask.crop(pillow_box)
            expected_mask = intended.mask.tobytes()
            actual_mask = mask_crop.tobytes()
            if actual_mask != expected_mask:
                raise AtlasRoundtripError(
                    f"Mask RGBA mismatch for {frame.name}: "
                    f"expected={hashlib.sha256(expected_mask).hexdigest()} "
                    f"actual={hashlib.sha256(actual_mask).hexdigest()}"
                )
            mask_digest = _pixel_digest(mask_crop)

        roundtripped.append(
            RoundtrippedFrame(
                name=frame.name,
                slot=frame.slot,
                rect=frame.rect,
                pillow_box=pillow_box,
                main_sha256=_pixel_digest(main_crop),
                mask_sha256=mask_digest,
            )
        )
    return AtlasRoundtripResult(
        atlas_size=atlas.size,
        has_mask=requires_mask,
        unique_rect_count=len({frame.rect for frame in parsed}),
        frames=tuple(roundtripped),
    )


def _load_rgba_candidate(path: Path | str, label: str) -> Image.Image:
    candidate = Path(path)
    try:
        with Image.open(candidate) as opened:
            opened.load()
            return opened.copy()
    except (OSError, UnidentifiedImageError) as exc:
        raise AtlasRoundtripError(f"Cannot read {label}: {candidate}") from exc


def verify_atlas_roundtrip_files(
    atlas_json_path: Path | str,
    atlas_path: Path | str,
    mask_path: Path | str | None,
    expected_frames: Sequence[AtlasFrame],
    *,
    gm_file_name: str,
    dash_format: bool,
) -> AtlasRoundtripResult:
    """Load ``atlas.json``/PNG files and run :func:`verify_atlas_roundtrip`."""

    json_path = Path(atlas_json_path)
    try:
        raw_json = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AtlasRoundtripError(f"Cannot parse atlas JSON: {json_path}") from exc
    if not isinstance(raw_json, Mapping):
        raise AtlasRoundtripError("atlas.json root must be an object")
    atlas = _load_rgba_candidate(atlas_path, "atlas.png")
    mask = _load_rgba_candidate(mask_path, "atlas_m.png") if mask_path else None
    return verify_atlas_roundtrip(
        raw_json,
        atlas,
        mask,
        expected_frames,
        gm_file_name=gm_file_name,
        dash_format=dash_format,
    )

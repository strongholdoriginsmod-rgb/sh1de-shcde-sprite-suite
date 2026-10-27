from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
import json
from math import isfinite
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import subprocess
import tempfile
from typing import Any
import unicodedata
import zlib

from PIL import Image, UnidentifiedImageError, __version__ as PILLOW_VERSION

from .asset_stream_quality import (
    QUALITY_CROPS_DIRECTORY,
    QUALITY_ACCEPTANCE_MODE,
    QUALITY_MEASUREMENT_MODE,
    FrameQualityEvidence,
    QualityCropCollector,
    build_quality_report,
    measure_frame,
    write_observed_quality_envelope,
    write_quality_crop_artifacts,
    write_quality_report,
)

from .asset_stream_contract import (
    AssetStreamContractError,
    AtlasFrame,
    GroupIndexRecordV2,
    GROUP_MASK_MATERIAL_BINDING,
    MAX_ABSOLUTE_SPRITE_PIVOT,
    MAX_PREFLIGHT_ARRAY_SIZE,
    MAX_PREFLIGHT_FRAMES_PER_GROUP,
    OMISSION_FOLIAGE_MULTIPAGE,
    OMISSION_FRAME_COUNT,
    OMISSION_FRAME_DIMENSION,
    OMISSION_PAGE_COUNT,
    OMISSION_SLOT_COUNT,
    VANILLA_OMISSION_REASONS,
    VanillaOmittedGroup,
    canonical_group_slug,
    calculate_peak_admission_bytes,
    expected_material_binding,
    parse_atlas_v2,
    parse_atlas_v3,
)


UNITY_VERSION = "2021.3.45f2"
UNITY_REVISION = "88f88f591b2e"
UNITY_FULL_VERSION = f"{UNITY_VERSION} ({UNITY_REVISION})"
BUILD_TARGET = "StandaloneWindows64"
MAX_PAGE_DIMENSION = 4096
MAX_GROUPS = 234
MAX_PAGES_PER_GROUP = 16
MAX_FRAMES_PER_GROUP = 4096
MAX_ATLAS_BYTES = 4 * 1024 * 1024
MAX_INDEX_BYTES = 4 * 1024 * 1024
MAX_REPORT_BYTES = 64 * 1024 * 1024
BUILD_OPTIONS = (
    "ChunkBasedCompression",
    "DeterministicAssetBundle",
    "ForceRebuildAssetBundle",
    "StrictMode",
)

ATLAS_SCHEMA = "stronghold-europe-de.atlas.v2"
INDEX_SCHEMA = "stronghold-europe-de.asset-bundle-index.v1"
INDEX_TEMPLATE_SCHEMA = "stronghold-europe-de.asset-bundle-index-template.v1"
BUILD_INPUT_SCHEMA = "stronghold-europe-de.asset-bundle-build-input.v1"
BUILD_REPORT_SCHEMA = "stronghold-europe-de.asset-bundle-build-report.v1"
PACKER_ID = "maxrects-bssf-no-rotation-v1"
EDITOR_METHOD = "StrongholdEuropeDE.AssetBundles.BuildFromCommandLine.Build"

# V2 is intentionally additive.  The legacy constants above remain the exact
# defaults of every public V1 entry point.
BC7_BACKEND_KIND = "unity_assetbundle_bc7_visual_equivalence_v2"
BC7_ATLAS_SCHEMA = "stronghold-europe-de.atlas.v3"
BC7_INDEX_SCHEMA = "stronghold-europe-de.asset-bundle-index.v2"
BC7_INDEX_TEMPLATE_SCHEMA = "stronghold-europe-de.asset-bundle-index-template.v2"
BC7_BUILD_INPUT_SCHEMA = "stronghold-europe-de.asset-bundle-build-input.v2"
BC7_BUILD_REPORT_SCHEMA = "stronghold-europe-de.asset-bundle-build-report.v2"
BC7_PREPARATION_SEED_SCHEMA = "stronghold-europe-de.asset-bundle-preparation-seed.v2"
BC7_PACKER_ID = "maxrects-bssf-no-rotation-cell4-rgba-extrude-v2"
BC7_ENCODER_ID = "unity-2021.3.45f2-bc7-hq100-force-max-v1"
BC7_BUNDLE_SUFFIX = ".bc7.v2"
BC7_ATLAS_ASSET_FILENAME = "atlas.v3.json"
BC7_BLOCK_ALIGNMENT_PIXELS = 4
BC7_MINIMUM_BORDER_PIXELS = 1
BC7_MAIN_BC7_MASK_TEXTURE_POLICY_ID = "bc7-main-bc7-mask-hq100-v1"
BC7_MAIN_RGBA32_MASK_TEXTURE_POLICY_ID = "bc7-main-rgba32-mask-hq100-v1"
BC7_MEASUREMENT_POLICY_ID = "bc7_visual_equivalence_measurement_v1"
BC7_MEASUREMENT_POLICY_SHA256 = (
    "ef1799a23471a41f93df5e9ed8a79839e6051221cd699d988e7b6ae0a34f17e1"
)
BC7_VERIFIER_ID = "unitypy-1.25.3-bc7-frame-metrics-v1"
BC7_UNITY_TIMEOUT_SECONDS = 43_200
BC7_GROUP_QUALITY_EVIDENCE_DIRECTORY = "group-quality-evidence.v1"

_EDITOR_SOURCE_RELATIVE = Path(
    "tools/unity_asset_bundle/StrongholdEuropeAssetBundleBuilder.cs"
)
_EDITOR_ASSET_PATH = "Assets/Editor/StrongholdEuropeAssetBundleBuilder.cs"
_OUTPUT_RELATIVE_PATH = "../output/Runtime/AssetBundles/win64"
_INDEX_OUTPUT_RELATIVE_PATH = "../output/Runtime/AssetBundles/index.json"
_MOD_BUNDLE_DIRECTORY = "Runtime/AssetBundles/win64"
_MOD_INDEX_PATH = "Runtime/AssetBundles/index.json"
_WORK_CONTAINER_DIRECTORY = "unity-ab"
_BUILD_DIRECTORY_ID_CHARACTERS = 16
_GUID_NAMESPACE = b"stronghold-europe-de.unity-guid.v1\0"
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_HASH128_RE = re.compile(r"[0-9a-f]{32}\Z")
_CRC32_RE = re.compile(r"[0-9a-f]{8}\Z")
_SLUG_RE = re.compile(r"[a-z0-9][a-z0-9._-]*\Z")
_BUNDLE_RE = re.compile(r"sede\.gm\.[a-z0-9][a-z0-9._-]*\.v2\Z")
_BC7_BUNDLE_RE = re.compile(r"sede\.gm\.[a-z0-9][a-z0-9._-]*\.bc7\.v2\Z")


_TEXTURE_CONTRACT: dict[str, object] = {
    "format": "RGBA32",
    "s_rgb": True,
    "mipmaps": False,
    "readable": False,
    "filter_mode": "Point",
    "wrap_mode": "Clamp",
    "alpha_source": "FromInput",
    "alpha_is_transparency": False,
    "npot_scale": "None",
}


def _bc7_texture_contract(filter_mode: str, *, format_name: str = "BC7") -> dict[str, object]:
    if filter_mode not in {"Point", "Bilinear"}:
        raise UnityAssetBundleError(f"Unsupported V2 filter mode: {filter_mode!r}")
    if format_name not in {"BC7", "RGBA32"}:
        raise UnityAssetBundleError(f"Unsupported V2 texture format: {format_name!r}")
    compressed = format_name == "BC7"
    return {
        "allows_alpha_splitting": False,
        "alpha_is_transparency": False,
        "alpha_source": "FromInput",
        "aniso_level": 0,
        "compression": "CompressedHQ" if compressed else "Uncompressed",
        "compression_quality": 100,
        "crunched_compression": False,
        "filter_mode": filter_mode,
        "force_maximum_compression_quality_bc6h_bc7": compressed,
        "format": format_name,
        "gpu_block_bytes": 16 if compressed else 4,
        "gpu_block_height": 4 if compressed else 1,
        "gpu_block_width": 4 if compressed else 1,
        "ignore_png_gamma": True,
        "max_texture_size": MAX_PAGE_DIMENSION,
        "mipmaps": False,
        "npot_scale": "None",
        "platform_override": True,
        "readable": False,
        "s_rgb": True,
        "streaming_mipmaps": False,
        "texture_type": "Default",
        "unity_texture_format": 25 if compressed else 4,
        "wrap_mode": "Clamp",
    }


class UnityAssetBundleError(RuntimeError):
    """Raised when deterministic bundle preparation cannot be proven exact."""


@dataclass(frozen=True)
class PackItem:
    """One positive-size rectangle to place without rotation."""

    key: str
    width: int
    height: int
    slot_index: int = 0
    alt: bool = False
    ordinal_name: str | None = None


@dataclass(frozen=True)
class PackedRect:
    """A content rectangle in top-left packing coordinates."""

    key: str
    page: int
    x: int
    y: int
    width: int
    height: int
    storage_x: int | None = None
    storage_y: int | None = None
    storage_width: int | None = None
    storage_height: int | None = None


@dataclass(frozen=True)
class PackedPage:
    id: int
    width: int
    height: int


@dataclass(frozen=True)
class PackingResult:
    pages: tuple[PackedPage, ...]
    rects: tuple[PackedRect, ...]
    padding_pixels: int
    max_page_dimension: int


@dataclass(frozen=True)
class FrameSource:
    """One synthetic or locally extracted RGBA frame and its Unity metadata."""

    name: str
    index: int
    alt: bool
    main_path: Path
    mask_path: Path | None
    width: int
    height: int
    pivot_x: float
    pivot_y: float
    pixels_per_unit: float


@dataclass(frozen=True)
class AtlasGroupInput:
    """One GM group to package into one deterministic AssetBundle."""

    group: str
    gm_id: int
    dash_format: bool
    array_size: int
    lifetime: str
    mask_policy: str
    material_binding: str
    frames: tuple[FrameSource, ...]
    padding_pixels: int = 1
    filter_mode: str = "Bilinear"


@dataclass(frozen=True)
class AtlasGroupPreflight:
    groups: tuple[AtlasGroupInput, ...]
    vanilla_omitted_groups: tuple[VanillaOmittedGroup, ...]
    plans: tuple["AtlasGroupPlan", ...] = ()


@dataclass(frozen=True)
class PreparedUnityProject:
    workspace_root: Path
    build_root: Path
    project_path: Path
    index_template_path: Path
    index_path: Path
    build_input_path: Path
    output_path: Path
    report_path: Path
    log_path: Path
    build_id: str
    group_count: int
    omitted_group_count: int
    page_count: int
    pipeline_version: int = 1
    unity_report_path: Path | None = None
    quality_report_path: Path | None = None
    quality_policy_id: str | None = None
    quality_policy_sha256: str | None = None
    quality_mode: str | None = None
    texture_policy_id: str | None = None
    quality_acceptance_envelope: Mapping[str, object] | None = None


@dataclass(frozen=True)
class BundleArtifact:
    name: str
    mod_relative_path: str
    size_bytes: int
    sha256: str
    manifest_hash: str


@dataclass(frozen=True)
class ValidatedBuildReport:
    build_id: str
    unity_version: str
    unity_revision: str
    index_sha256: str
    bundles: tuple[BundleArtifact, ...]
    quality_report_sha256: str | None = None


@dataclass(frozen=True)
class _Rect:
    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    def intersects(self, other: "_Rect") -> bool:
        return not (
            self.right <= other.x
            or other.right <= self.x
            or self.bottom <= other.y
            or other.bottom <= self.y
        )

    def contains(self, other: "_Rect") -> bool:
        return (
            self.x <= other.x
            and self.y <= other.y
            and self.right >= other.right
            and self.bottom >= other.bottom
        )


@dataclass
class _PageState:
    id: int
    dimension: int
    free: list[_Rect]
    used: list[_Rect]

    @classmethod
    def create(cls, page_id: int, dimension: int) -> "_PageState":
        return cls(
            id=page_id,
            dimension=dimension,
            free=[_Rect(0, 0, dimension, dimension)],
            used=[],
        )

    def best_short_side_fit(self, width: int, height: int) -> tuple[int, ...] | None:
        candidates: list[tuple[int, ...]] = []
        for free_index, free_rect in enumerate(self.free):
            if width > free_rect.width or height > free_rect.height:
                continue
            leftover_width = free_rect.width - width
            leftover_height = free_rect.height - height
            candidates.append(
                (
                    min(leftover_width, leftover_height),
                    max(leftover_width, leftover_height),
                    free_rect.y,
                    free_rect.x,
                    free_rect.width * free_rect.height,
                    free_rect.height,
                    free_rect.width,
                    free_index,
                )
            )
        return min(candidates) if candidates else None

    def place(self, width: int, height: int, score: tuple[int, ...]) -> _Rect:
        free_rect = self.free[score[-1]]
        used = _Rect(free_rect.x, free_rect.y, width, height)
        next_free: list[_Rect] = []
        for candidate in self.free:
            if not candidate.intersects(used):
                next_free.append(candidate)
                continue
            if used.x > candidate.x:
                next_free.append(
                    _Rect(
                        candidate.x,
                        candidate.y,
                        used.x - candidate.x,
                        candidate.height,
                    )
                )
            if used.right < candidate.right:
                next_free.append(
                    _Rect(
                        used.right,
                        candidate.y,
                        candidate.right - used.right,
                        candidate.height,
                    )
                )
            if used.y > candidate.y:
                next_free.append(
                    _Rect(
                        candidate.x,
                        candidate.y,
                        candidate.width,
                        used.y - candidate.y,
                    )
                )
            if used.bottom < candidate.bottom:
                next_free.append(
                    _Rect(
                        candidate.x,
                        used.bottom,
                        candidate.width,
                        candidate.bottom - used.bottom,
                    )
                )
        self.free = _prune_free_rectangles(next_free)
        self.used.append(used)
        return used


@dataclass(frozen=True)
class _LoadedFrame:
    source: FrameSource
    main_rgba_sha256: str
    mask_rgba_sha256: str | None


@dataclass(frozen=True)
class AtlasGroupPlan:
    """Immutable validated/deduplicated/packed input reused after preflight."""

    spec: AtlasGroupInput
    slug: str
    loaded_frames: tuple[_LoadedFrame, ...]
    representative_frames: tuple[_LoadedFrame, ...]
    representative_by_name: tuple[tuple[str, str], ...]
    packing: PackingResult
    pipeline_version: int


@dataclass(frozen=True)
class AtlasGroupFingerprint:
    """Validated V2 source identity before any rectangle/atlas work.

    Computing this value decodes and hashes the source frames so a cache key
    can prove that the inputs are unchanged.  It deliberately performs no
    rectangle packing, atlas composition, Unity import, BC7 encoding, or
    quality measurement.
    """

    spec: AtlasGroupInput
    slug: str
    loaded_frames: tuple[_LoadedFrame, ...]
    frame_bindings: Mapping[str, object]
    pipeline_version: int = 2


def _prune_free_rectangles(rectangles: Sequence[_Rect]) -> list[_Rect]:
    positive = sorted(
        {rect for rect in rectangles if rect.width > 0 and rect.height > 0},
        key=lambda rect: (rect.y, rect.x, rect.width, rect.height),
    )
    kept: list[_Rect] = []
    for index, candidate in enumerate(positive):
        if any(
            other.contains(candidate)
            for other_index, other in enumerate(positive)
            if other_index != index
        ):
            continue
        kept.append(candidate)
    return kept


def _next_power_of_two(value: int) -> int:
    if value <= 1:
        return 1
    return 1 << (value - 1).bit_length()


def pack_rectangles(
    items: Sequence[PackItem],
    *,
    max_page_dimension: int = MAX_PAGE_DIMENSION,
    padding_pixels: int = 1,
) -> PackingResult:
    """Pack rectangles with deterministic MaxRects/BSSF and no rotation.

    Input order is deliberately irrelevant. Rectangles are inserted largest
    first, and every placement uses best-short-side-fit with a fully specified
    ordinal tie break. Returned coordinates use a top-left origin; atlas JSON
    conversion to Unity's bottom-left origin happens during project preparation.
    """

    if (
        isinstance(max_page_dimension, bool)
        or not isinstance(max_page_dimension, int)
        or max_page_dimension <= 0
        or max_page_dimension > MAX_PAGE_DIMENSION
    ):
        raise UnityAssetBundleError(
            f"max_page_dimension must be in 1..{MAX_PAGE_DIMENSION}"
        )
    if (
        isinstance(padding_pixels, bool)
        or not isinstance(padding_pixels, int)
        or padding_pixels < 0
        or padding_pixels > 64
    ):
        raise UnityAssetBundleError("padding_pixels must be in 0..64")
    if not items:
        raise UnityAssetBundleError("Cannot pack an empty rectangle set")

    checked: list[PackItem] = []
    keys: set[str] = set()
    for position, item in enumerate(items):
        if not isinstance(item, PackItem):
            raise UnityAssetBundleError(f"items[{position}] is not a PackItem")
        key = _require_nfc_string(item.key, f"items[{position}].key")
        if key in keys:
            raise UnityAssetBundleError(f"Duplicate packing key: {key}")
        keys.add(key)
        if (
            isinstance(item.width, bool)
            or not isinstance(item.width, int)
            or isinstance(item.height, bool)
            or not isinstance(item.height, int)
            or item.width <= 0
            or item.height <= 0
        ):
            raise UnityAssetBundleError(f"Packing size must be positive for {key}")
        if (
            isinstance(item.slot_index, bool)
            or not isinstance(item.slot_index, int)
            or item.slot_index < 0
            or not isinstance(item.alt, bool)
        ):
            raise UnityAssetBundleError(f"Invalid packing slot metadata for {key}")
        if item.ordinal_name is not None:
            _require_nfc_string(item.ordinal_name, f"items[{position}].ordinal_name")
        outer_width = item.width + 2 * padding_pixels
        outer_height = item.height + 2 * padding_pixels
        if outer_width > max_page_dimension or outer_height > max_page_dimension:
            raise UnityAssetBundleError(
                f"Frame {key} plus padding is {outer_width}x{outer_height}, "
                f"larger than {max_page_dimension}"
            )
        checked.append(item)

    ordered = sorted(
        checked,
        key=lambda item: (
            -(
                (item.width + 2 * padding_pixels)
                * (item.height + 2 * padding_pixels)
            ),
            -max(item.width + 2 * padding_pixels, item.height + 2 * padding_pixels),
            -(item.height + 2 * padding_pixels),
            -(item.width + 2 * padding_pixels),
            item.slot_index,
            item.alt,
            item.ordinal_name if item.ordinal_name is not None else item.key,
        ),
    )
    page_states: list[_PageState] = []
    placements: list[PackedRect] = []
    for item in ordered:
        outer_width = item.width + 2 * padding_pixels
        outer_height = item.height + 2 * padding_pixels
        page_candidates: list[tuple[tuple[int, ...], int]] = []
        for page in page_states:
            score = page.best_short_side_fit(outer_width, outer_height)
            if score is not None:
                page_candidates.append((score, page.id))
        if page_candidates:
            score, page_id = min(
                page_candidates,
                key=lambda pair: (
                    pair[0][0],
                    pair[0][1],
                    pair[0][2],
                    pair[0][3],
                    pair[1],
                    *pair[0][4:-1],
                    pair[0][-1],
                ),
            )
            page = page_states[page_id]
        else:
            page = _PageState.create(len(page_states), max_page_dimension)
            page_states.append(page)
            score = page.best_short_side_fit(outer_width, outer_height)
            if score is None:  # guarded above; retained as a fail-closed invariant
                raise UnityAssetBundleError(f"Packer could not place {item.key}")
        outer = page.place(outer_width, outer_height, score)
        placements.append(
            PackedRect(
                key=item.key,
                page=page.id,
                x=outer.x + padding_pixels,
                y=outer.y + padding_pixels,
                width=item.width,
                height=item.height,
            )
        )

    pages: list[PackedPage] = []
    for page in page_states:
        used_width = max(rect.right for rect in page.used)
        used_height = max(rect.bottom for rect in page.used)
        minimum_page_dimension = min(256, max_page_dimension)
        width = max(minimum_page_dimension, _next_power_of_two(used_width))
        height = max(minimum_page_dimension, _next_power_of_two(used_height))
        if width > max_page_dimension or height > max_page_dimension:
            raise UnityAssetBundleError(
                f"Packed page {page.id} escaped {max_page_dimension}"
            )
        pages.append(PackedPage(page.id, width, height))

    ordered_placements = tuple(sorted(placements, key=lambda rect: rect.key))
    _verify_packing(tuple(pages), ordered_placements, padding_pixels)
    return PackingResult(
        pages=tuple(pages),
        rects=ordered_placements,
        padding_pixels=padding_pixels,
        max_page_dimension=max_page_dimension,
    )


def _verify_packing(
    pages: Sequence[PackedPage],
    rects: Sequence[PackedRect],
    padding_pixels: int,
) -> None:
    pages_by_id = {page.id: page for page in pages}
    if tuple(sorted(pages_by_id)) != tuple(range(len(pages))):
        raise UnityAssetBundleError("Packed page ids are not contiguous")
    outer_by_page: dict[int, list[tuple[str, _Rect]]] = {
        page.id: [] for page in pages
    }
    for rect in rects:
        page = pages_by_id.get(rect.page)
        if page is None:
            raise UnityAssetBundleError(f"Packed rect uses missing page: {rect.key}")
        outer = _Rect(
            rect.x - padding_pixels,
            rect.y - padding_pixels,
            rect.width + 2 * padding_pixels,
            rect.height + 2 * padding_pixels,
        )
        if (
            outer.x < 0
            or outer.y < 0
            or outer.right > page.width
            or outer.bottom > page.height
        ):
            raise UnityAssetBundleError(f"Packed rect escapes page: {rect.key}")
        for other_key, other in outer_by_page[rect.page]:
            if outer.intersects(other):
                raise UnityAssetBundleError(
                    f"Packed rects overlap: {other_key} and {rect.key}"
                )
        outer_by_page[rect.page].append((rect.key, outer))


def _align_up(value: int, alignment: int) -> int:
    return ((value + alignment - 1) // alignment) * alignment


def _ordered_cell_items(
    items: Sequence[PackItem], *, order: str = "area"
) -> tuple[PackItem, ...]:
    if order == "area":
        key = lambda item: (
            -(item.width * item.height),
            -max(item.width, item.height),
            -item.height,
            -item.width,
            item.slot_index,
            item.alt,
            item.ordinal_name if item.ordinal_name is not None else item.key,
        )
    elif order == "height":
        key = lambda item: (
            -item.height,
            -item.width,
            item.slot_index,
            item.alt,
            item.ordinal_name if item.ordinal_name is not None else item.key,
        )
    elif order == "width":
        key = lambda item: (
            -item.width,
            -item.height,
            item.slot_index,
            item.alt,
            item.ordinal_name if item.ordinal_name is not None else item.key,
        )
    else:  # internal-only call surface; retained as a fail-closed invariant
        raise UnityAssetBundleError(f"Unknown BC7 cell order: {order!r}")
    return tuple(
        sorted(
            items,
            key=key,
        )
    )


def _pack_cells_in_rectangle(
    items: Sequence[PackItem],
    *,
    page_id: int,
    width: int,
    height: int,
    order: str = "area",
) -> tuple[PackedRect, ...] | None:
    """Try one deterministic MaxRects/BSSF placement in a rectangular page."""

    page = _PageState(
        id=page_id,
        dimension=max(width, height),
        free=[_Rect(0, 0, width, height)],
        used=[],
    )
    result: list[PackedRect] = []
    for item in _ordered_cell_items(items, order=order):
        score = page.best_short_side_fit(item.width, item.height)
        if score is None:
            return None
        storage = page.place(item.width, item.height, score)
        result.append(
            PackedRect(
                key=item.key,
                page=page_id,
                x=storage.x + BC7_MINIMUM_BORDER_PIXELS,
                y=storage.y + BC7_MINIMUM_BORDER_PIXELS,
                # The caller restores the visible dimensions after placement.
                width=item.width,
                height=item.height,
                storage_x=storage.x,
                storage_y=storage.y,
                storage_width=storage.width,
                storage_height=storage.height,
            )
        )
    return tuple(result)


def _power_of_two_page_candidates(
    items: Sequence[PackItem], *, max_page_dimension: int
) -> tuple[tuple[int, int], ...]:
    minimum = min(256, max_page_dimension)
    powers: list[int] = []
    value = minimum
    while value <= max_page_dimension:
        powers.append(value)
        value *= 2
    total_area = sum(item.width * item.height for item in items)
    minimum_width = max(item.width for item in items)
    minimum_height = max(item.height for item in items)
    return tuple(
        sorted(
            (
                (width, height)
                for width in powers
                for height in powers
                if width >= minimum_width
                and height >= minimum_height
                and width * height >= total_area
            ),
            key=lambda size: (
                size[0] * size[1],
                max(size),
                size[0],
                size[1],
            ),
        )
    )


def _pack_bc7_single_page(
    items: Sequence[PackItem], *, max_page_dimension: int
) -> tuple[tuple[int, int], tuple[PackedRect, ...]] | None:
    """Try reviewed deterministic BSSF orders without changing valid layouts.

    Area order is the established V2 order and therefore always has priority.
    Height/width orders are attempted only when area order cannot represent the
    complete group on any allowed power-of-two page.  This rescues dense,
    similarly sized sets whose total cell area fits but whose area-first free
    rectangles fragment; no already representable one-page layout can change.
    """

    candidates = _power_of_two_page_candidates(
        items, max_page_dimension=max_page_dimension
    )
    for order in ("area", "height", "width"):
        for width, height in candidates:
            attempt = _pack_cells_in_rectangle(
                items,
                page_id=0,
                width=width,
                height=height,
                order=order,
            )
            if attempt is not None:
                return (width, height), attempt
    return None


def pack_rectangles_bc7(
    items: Sequence[PackItem],
    *,
    max_page_dimension: int = MAX_PAGE_DIMENSION,
    single_page_required: bool = False,
) -> PackingResult:
    """Pack every visible frame into an independent, 4x4-aligned BC7 cell.

    A caller whose material route requires exactly one page may request a
    deterministic whole-set BSSF search before the established page assignment.
    The initial 4096-page assignment is otherwise followed by a deterministic
    search for the smallest successful power-of-two rectangle for each already
    assigned page.  The original valid page geometry/placement is retained as
    the final fallback, so compaction can never make a previously valid plan
    fail.
    """

    if not items:
        raise UnityAssetBundleError("Cannot pack an empty BC7 rectangle set")
    if (
        isinstance(max_page_dimension, bool)
        or not isinstance(max_page_dimension, int)
        or max_page_dimension < 4
        or max_page_dimension > MAX_PAGE_DIMENSION
        or max_page_dimension % BC7_BLOCK_ALIGNMENT_PIXELS
    ):
        raise UnityAssetBundleError("BC7 max_page_dimension is invalid")
    if not isinstance(single_page_required, bool):
        raise UnityAssetBundleError("single_page_required must be a bool")

    checked: list[PackItem] = []
    visible_by_key: dict[str, PackItem] = {}
    cell_by_key: dict[str, PackItem] = {}
    for position, item in enumerate(items):
        if not isinstance(item, PackItem):
            raise UnityAssetBundleError(f"items[{position}] is not a PackItem")
        key = _require_nfc_string(item.key, f"items[{position}].key")
        if key in visible_by_key:
            raise UnityAssetBundleError(f"Duplicate packing key: {key}")
        if (
            isinstance(item.width, bool)
            or not isinstance(item.width, int)
            or isinstance(item.height, bool)
            or not isinstance(item.height, int)
            or item.width <= 0
            or item.height <= 0
        ):
            raise UnityAssetBundleError(f"Packing size must be positive for {key}")
        cell_width = _align_up(
            item.width + 2 * BC7_MINIMUM_BORDER_PIXELS,
            BC7_BLOCK_ALIGNMENT_PIXELS,
        )
        cell_height = _align_up(
            item.height + 2 * BC7_MINIMUM_BORDER_PIXELS,
            BC7_BLOCK_ALIGNMENT_PIXELS,
        )
        if cell_width > max_page_dimension or cell_height > max_page_dimension:
            raise UnityAssetBundleError(
                f"Frame {key} BC7 cell is {cell_width}x{cell_height}, larger "
                f"than {max_page_dimension}"
            )
        checked.append(item)
        visible_by_key[key] = item
        cell_by_key[key] = PackItem(
            key=key,
            width=cell_width,
            height=cell_height,
            slot_index=item.slot_index,
            alt=item.alt,
            ordinal_name=item.ordinal_name,
        )

    if single_page_required:
        page_items = tuple(cell_by_key[key] for key in sorted(cell_by_key))
        single_page = _pack_bc7_single_page(
            page_items, max_page_dimension=max_page_dimension
        )
        if single_page is not None:
            chosen_size, chosen_cells = single_page
            result = PackingResult(
                pages=(PackedPage(0, *chosen_size),),
                rects=tuple(
                    sorted(
                        (
                            PackedRect(
                                key=cell.key,
                                page=0,
                                x=cell.x,
                                y=cell.y,
                                width=visible_by_key[cell.key].width,
                                height=visible_by_key[cell.key].height,
                                storage_x=cell.storage_x,
                                storage_y=cell.storage_y,
                                storage_width=cell.storage_width,
                                storage_height=cell.storage_height,
                            )
                            for cell in chosen_cells
                        ),
                        key=lambda rect: rect.key,
                    )
                ),
                padding_pixels=BC7_MINIMUM_BORDER_PIXELS,
                max_page_dimension=max_page_dimension,
            )
            _verify_bc7_packing(result)
            return result

    # Reuse the established deterministic BSSF page assignment.  Cell sizes
    # and zero padding guarantee every assigned origin is 4-pixel aligned.
    base = pack_rectangles(
        tuple(cell_by_key[item.key] for item in checked),
        max_page_dimension=max_page_dimension,
        padding_pixels=0,
    )
    base_by_key = {rect.key: rect for rect in base.rects}
    result_pages: list[PackedPage] = []
    result_rects: list[PackedRect] = []
    for base_page in base.pages:
        page_items = tuple(
            cell_by_key[key]
            for key in sorted(cell_by_key)
            if base_by_key[key].page == base_page.id
        )
        candidates = _power_of_two_page_candidates(
            page_items, max_page_dimension=max_page_dimension
        )
        chosen_size: tuple[int, int] | None = None
        chosen_cells: tuple[PackedRect, ...] | None = None
        for width, height in candidates:
            attempt = _pack_cells_in_rectangle(
                page_items,
                page_id=base_page.id,
                width=width,
                height=height,
            )
            if attempt is not None:
                chosen_size = (width, height)
                chosen_cells = attempt
                break
        if chosen_cells is None:
            # The base placement was already verified and is an immutable safe
            # fallback if all rectangular re-packs fail.
            chosen_size = (base_page.width, base_page.height)
            chosen_cells = tuple(
                PackedRect(
                    key=item.key,
                    page=base_page.id,
                    x=base_by_key[item.key].x + 1,
                    y=base_by_key[item.key].y + 1,
                    width=item.width,
                    height=item.height,
                    storage_x=base_by_key[item.key].x,
                    storage_y=base_by_key[item.key].y,
                    storage_width=item.width,
                    storage_height=item.height,
                )
                for item in page_items
            )
        assert chosen_size is not None
        result_pages.append(PackedPage(base_page.id, *chosen_size))
        for cell in chosen_cells:
            visible = visible_by_key[cell.key]
            result_rects.append(
                PackedRect(
                    key=cell.key,
                    page=cell.page,
                    x=cell.x,
                    y=cell.y,
                    width=visible.width,
                    height=visible.height,
                    storage_x=cell.storage_x,
                    storage_y=cell.storage_y,
                    storage_width=cell.storage_width,
                    storage_height=cell.storage_height,
                )
            )

    result = PackingResult(
        pages=tuple(result_pages),
        rects=tuple(sorted(result_rects, key=lambda rect: rect.key)),
        padding_pixels=BC7_MINIMUM_BORDER_PIXELS,
        max_page_dimension=max_page_dimension,
    )
    _verify_bc7_packing(result)
    return result


def _verify_bc7_packing(packing: PackingResult) -> None:
    pages = {page.id: page for page in packing.pages}
    if tuple(sorted(pages)) != tuple(range(len(pages))):
        raise UnityAssetBundleError("BC7 page ids are not contiguous")
    cells_by_page: dict[int, list[tuple[str, _Rect]]] = {
        page_id: [] for page_id in pages
    }
    for rect in packing.rects:
        values = (
            rect.storage_x,
            rect.storage_y,
            rect.storage_width,
            rect.storage_height,
        )
        if any(value is None for value in values):
            raise UnityAssetBundleError(f"BC7 storage cell is missing: {rect.key}")
        storage = _Rect(*(int(value) for value in values))
        page = pages.get(rect.page)
        if (
            page is None
            or storage.x % 4
            or storage.y % 4
            or storage.width % 4
            or storage.height % 4
            or storage.x < 0
            or storage.y < 0
            or storage.right > page.width
            or storage.bottom > page.height
            or rect.x != storage.x + 1
            or rect.y != storage.y + 1
            or rect.x + rect.width >= storage.right
            or rect.y + rect.height >= storage.bottom
        ):
            raise UnityAssetBundleError(f"Invalid BC7 storage cell: {rect.key}")
        for other_key, other in cells_by_page[rect.page]:
            if storage.intersects(other):
                raise UnityAssetBundleError(
                    f"BC7 cells overlap/share blocks: {other_key} and {rect.key}"
                )
        cells_by_page[rect.page].append((rect.key, storage))


def _require_nfc_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise UnityAssetBundleError(f"{label} must be a non-empty string")
    if unicodedata.normalize("NFC", value) != value:
        raise UnityAssetBundleError(f"{label} must already be NFC-normalized")
    if any(ord(character) < 32 for character in value):
        raise UnityAssetBundleError(f"{label} contains a control character")
    return value


def group_slug(group: str) -> str:
    group = _require_nfc_string(group, "group")
    try:
        slug = canonical_group_slug(group)
    except AssetStreamContractError as exc:
        raise UnityAssetBundleError(
            f"Unsupported GM group name: {group!r}"
        ) from exc
    if _SLUG_RE.fullmatch(slug) is None:
        raise UnityAssetBundleError(f"Could not derive the exact safe slug from {group!r}")
    return slug


def _safe_relative_path(value: str, label: str) -> str:
    value = _require_nfc_string(value, label)
    if "\\" in value:
        raise UnityAssetBundleError(f"{label} must use forward slashes")
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if (
        posix.is_absolute()
        or windows.is_absolute()
        or bool(windows.drive)
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise UnityAssetBundleError(f"{label} is not a safe relative path: {value}")
    return value


def stable_unity_guid(asset_path: str) -> str:
    """Derive one stable lowercase Unity GUID from a canonical logical path."""

    canonical = _safe_relative_path(asset_path, "Unity asset path")
    return sha256(_GUID_NAMESPACE + canonical.encode("utf-8")).hexdigest()[:32]


def _canonical_json_bytes(value: object, *, final_lf: bool) -> bytes:
    try:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise UnityAssetBundleError("Value is not canonical-JSON serializable") from exc
    return payload + (b"\n" if final_lf else b"")


def _sha256_bytes(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def _sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _crc32_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    value = 0
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            value = zlib.crc32(chunk, value)
    return f"{value & 0xFFFFFFFF:08x}"


def _resident_charge_bytes(raw_rgba_bytes: int) -> int:
    adjusted = (raw_rgba_bytes * 9 + 7) // 8
    alignment = 64 * 1024 * 1024
    return ((adjusted + alignment - 1) // alignment) * alignment


def _predicted_load_peak_bytes(
    resident_charge_bytes: int, bundle_size_bytes: int
) -> int:
    """Use the single canonical upload-peak formula shared with admission."""

    try:
        return calculate_peak_admission_bytes(
            resident_charge_bytes, bundle_size_bytes
        )
    except AssetStreamContractError as exc:
        raise UnityAssetBundleError(
            "Could not calculate the predicted one-group load peak"
        ) from exc


def _write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def _write_canonical_json(path: Path, value: object) -> bytes:
    payload = _canonical_json_bytes(value, final_lf=True)
    _write_bytes(path, payload)
    return payload


def _resolved_input_file(path: Path, label: str) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        raise UnityAssetBundleError(f"{label} must be an absolute resolved path")
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise UnityAssetBundleError(f"{label} does not exist: {candidate}") from exc
    if resolved != candidate or not resolved.is_file():
        raise UnityAssetBundleError(
            f"{label} must be a canonical non-reparse regular file: {candidate}"
        )
    return resolved


def _load_rgba_png(
    path: Path,
    *,
    expected_size: tuple[int, int],
    label: str,
) -> tuple[Image.Image, str]:
    source = _resolved_input_file(path, label)
    try:
        with Image.open(source) as opened:
            opened.load()
            if opened.format != "PNG" or opened.mode != "RGBA":
                raise UnityAssetBundleError(
                    f"{label} must be an RGBA PNG without an implicit conversion"
                )
            if opened.size != expected_size:
                raise UnityAssetBundleError(
                    f"{label} size changed: expected={expected_size}, actual={opened.size}"
                )
            image = opened.copy()
    except (OSError, UnidentifiedImageError) as exc:
        raise UnityAssetBundleError(f"Could not decode {label}: {source}") from exc
    return image, _rgba_sha256_image(image)


def _rgba_sha256_image(image: Image.Image, rows_per_chunk: int = 64) -> str:
    if image.mode != "RGBA" or image.width <= 0 or image.height <= 0:
        raise UnityAssetBundleError("RGBA digest requires a positive RGBA image")
    digest = sha256()
    for top in range(0, image.height, rows_per_chunk):
        bottom = min(top + rows_per_chunk, image.height)
        with image.crop((0, top, image.width, bottom)) as strip:
            digest.update(strip.tobytes())
    return digest.hexdigest()


def _rgba_sha256_box(
    image: Image.Image,
    box: tuple[int, int, int, int],
    *,
    rows_per_chunk: int = 64,
) -> str:
    """Hash one top-left PIL box while allocating at most a bounded row strip."""

    left, top, right, bottom = box
    if (
        image.mode != "RGBA"
        or left < 0
        or top < 0
        or right > image.width
        or bottom > image.height
        or left >= right
        or top >= bottom
    ):
        raise UnityAssetBundleError(f"Invalid RGBA frame crop: {box!r}")
    digest = sha256()
    for row in range(top, bottom, rows_per_chunk):
        row_bottom = min(row + rows_per_chunk, bottom)
        with image.crop((left, row, right, row_bottom)) as strip:
            digest.update(strip.tobytes())
    return digest.hexdigest()


def _verify_post_unity_frame_roundtrips(
    image: Image.Image,
    frames: Sequence[AtlasFrame],
    *,
    page_id: int,
    plane: str,
    group_name: str,
) -> None:
    """Crop every frame back from one decoded page and verify its RGBA bytes.

    Atlas rects use Unity bottom-left coordinates, whereas Pillow images use a
    top-left origin. Exact duplicate frames may share a rect; their records are
    all bound to the same verified crop while each unique crop is hashed only
    once. Memory stays bounded to one decoded page plus a 64-row crop strip.
    """

    if plane not in {"main", "mask"}:
        raise UnityAssetBundleError(f"Unknown post-Unity frame plane: {plane!r}")
    if image.mode != "RGBA" or not (0 <= page_id < MAX_PAGES_PER_GROUP):
        raise UnityAssetBundleError("Invalid post-Unity page roundtrip input")
    if not 1 <= len(frames) <= MAX_FRAMES_PER_GROUP:
        raise UnityAssetBundleError("Post-Unity frame count exceeds its bound")

    verified: dict[tuple[int, int, int, int], str] = {}
    matched = 0
    for frame in frames:
        if frame.page != page_id:
            continue
        matched += 1
        rect = frame.rect
        left = rect.x
        top = image.height - rect.y - rect.height
        right = left + rect.width
        bottom = top + rect.height
        if (
            left < 1
            or top < 1
            or right + 1 > image.width
            or bottom + 1 > image.height
        ):
            raise UnityAssetBundleError(
                f"Post-Unity frame escaped its 1px edge padding: "
                f"{group_name}/{frame.name}"
            )
        expected_digest = (
            frame.main_rgba_sha256
            if plane == "main"
            else frame.mask_rgba_sha256
        )
        if expected_digest is None:
            raise UnityAssetBundleError(
                f"Post-Unity {plane} digest is missing: {group_name}/{frame.name}"
            )
        key = (left, top, right, bottom)
        prior_digest = verified.get(key)
        if prior_digest is not None:
            if prior_digest != expected_digest:
                raise UnityAssetBundleError(
                    f"Post-Unity shared {plane} rect has conflicting RGBA digests: "
                    f"{group_name}/{frame.name}"
                )
            continue

        actual_digest = _rgba_sha256_box(image, key)
        if actual_digest != expected_digest:
            raise UnityAssetBundleError(
                f"Post-Unity {plane} frame RGBA roundtrip drifted: "
                f"{group_name}/{frame.name}"
            )
        padding_boxes = (
            (left - 1, top - 1, right + 1, top),
            (left - 1, bottom, right + 1, bottom + 1),
            (left - 1, top, left, bottom),
            (right, top, right + 1, bottom),
        )
        for padding_box in padding_boxes:
            with image.crop(padding_box) as strip:
                if any(strip.tobytes()):
                    raise UnityAssetBundleError(
                        f"Post-Unity {plane} frame 1px padding is not null RGBA: "
                        f"{group_name}/{frame.name}"
                    )
        verified[key] = expected_digest
    if matched == 0:
        raise UnityAssetBundleError(
            f"Post-Unity atlas page has no frames: {group_name} page={page_id}"
        )


def _rgba_png_pixels_equal(
    left_path: Path,
    right_path: Path,
    *,
    expected_size: tuple[int, int],
    label: str,
    rows_per_chunk: int = 64,
) -> bool:
    """Confirm a digest match with an exact four-channel pixel comparison."""

    try:
        if left_path.resolve(strict=True) == right_path.resolve(strict=True):
            return True
    except (OSError, RuntimeError) as exc:
        raise UnityAssetBundleError(f"Could not resolve duplicate candidate: {label}") from exc
    left, _left_digest = _load_rgba_png(
        left_path, expected_size=expected_size, label=f"{label} left"
    )
    right, _right_digest = _load_rgba_png(
        right_path, expected_size=expected_size, label=f"{label} right"
    )
    try:
        for top in range(0, expected_size[1], rows_per_chunk):
            bottom = min(top + rows_per_chunk, expected_size[1])
            box = (0, top, expected_size[0], bottom)
            with left.crop(box) as left_strip, right.crop(box) as right_strip:
                if left_strip.tobytes() != right_strip.tobytes():
                    return False
        return True
    finally:
        left.close()
        right.close()


def _deduplicate_loaded_frames(
    frames: Sequence[_LoadedFrame], *, mask_policy: str
) -> tuple[tuple[_LoadedFrame, ...], dict[str, str]]:
    """Deduplicate only byte-exact main/mask RGBA planes.

    SHA-256 is used solely as the candidate key. Every candidate match is then
    compared byte-for-byte across all four channels before it may share a rect.
    """

    candidates: dict[
        tuple[int, int, str, str | None], list[_LoadedFrame]
    ] = {}
    representatives: list[_LoadedFrame] = []
    representative_by_name: dict[str, str] = {}
    for frame in frames:
        source = frame.source
        key = (
            source.width,
            source.height,
            frame.main_rgba_sha256,
            frame.mask_rgba_sha256,
        )
        representative: _LoadedFrame | None = None
        for candidate in candidates.get(key, []):
            size = (source.width, source.height)
            if not _rgba_png_pixels_equal(
                source.main_path,
                candidate.source.main_path,
                expected_size=size,
                label=f"duplicate main {source.name}/{candidate.source.name}",
            ):
                continue
            if mask_policy == "required":
                if source.mask_path is None or candidate.source.mask_path is None:
                    raise UnityAssetBundleError(
                        f"Required duplicate mask is missing: {source.name}"
                    )
                if not _rgba_png_pixels_equal(
                    source.mask_path,
                    candidate.source.mask_path,
                    expected_size=size,
                    label=f"duplicate mask {source.name}/{candidate.source.name}",
                ):
                    continue
            representative = candidate
            break
        if representative is None:
            representatives.append(frame)
            candidates.setdefault(key, []).append(frame)
            representative = frame
        representative_by_name[source.name] = representative.source.name
    return tuple(representatives), representative_by_name


def _validated_groups(
    groups: Sequence[AtlasGroupInput],
    *,
    enforce_v1_bounds: bool = True,
) -> tuple[tuple[AtlasGroupInput, str, tuple[_LoadedFrame, ...]], ...]:
    if not groups:
        raise UnityAssetBundleError("At least one atlas group is required")
    if len(groups) > MAX_GROUPS:
        raise UnityAssetBundleError(
            f"Atlas group count exceeds pinned Enums.GM size: {len(groups)}"
        )
    validated: list[tuple[AtlasGroupInput, str, tuple[_LoadedFrame, ...]]] = []
    seen_groups: set[str] = set()
    seen_slugs: set[str] = set()
    seen_gm_ids: set[int] = set()
    for group_position, spec in enumerate(groups):
        if not isinstance(spec, AtlasGroupInput):
            raise UnityAssetBundleError(
                f"groups[{group_position}] is not an AtlasGroupInput"
            )
        name = _require_nfc_string(spec.group, f"groups[{group_position}].group")
        slug = group_slug(name)
        if name.casefold() in seen_groups:
            raise UnityAssetBundleError(f"Duplicate case-insensitive GM group: {name}")
        if slug in seen_slugs:
            raise UnityAssetBundleError(f"GM group slug collision: {slug}")
        seen_groups.add(name.casefold())
        seen_slugs.add(slug)
        if (
            isinstance(spec.gm_id, bool)
            or not isinstance(spec.gm_id, int)
            or not 0 <= spec.gm_id < MAX_GROUPS
        ):
            raise UnityAssetBundleError(f"Invalid Enums.GM id for {name}")
        if spec.gm_id in seen_gm_ids:
            raise UnityAssetBundleError(f"Duplicate Enums.GM id: {spec.gm_id}")
        seen_gm_ids.add(spec.gm_id)
        if not isinstance(spec.dash_format, bool):
            raise UnityAssetBundleError(f"dash_format must be boolean for {name}")
        if (
            isinstance(spec.array_size, bool)
            or not isinstance(spec.array_size, int)
            or not 1
            <= spec.array_size
            <= (
                MAX_FRAMES_PER_GROUP
                if enforce_v1_bounds
                else MAX_PREFLIGHT_ARRAY_SIZE
            )
        ):
            raise UnityAssetBundleError(f"Invalid loader array_size for {name}")
        if spec.lifetime != "map":
            raise UnityAssetBundleError(f"lifetime for {name} must be 'map'")
        if spec.mask_policy not in {"required", "forbidden"}:
            raise UnityAssetBundleError(
                f"Unsupported mask policy for {name}: {spec.mask_policy!r}"
            )
        expected_binding = expected_material_binding(name, spec.mask_policy)
        if spec.material_binding != expected_binding:
            raise UnityAssetBundleError(
                f"Material binding for {name} must be {expected_binding!r}"
            )
        if spec.padding_pixels != 1 or isinstance(spec.padding_pixels, bool):
            raise UnityAssetBundleError(f"padding_pixels for {name} must be exactly 1")
        if not spec.frames:
            raise UnityAssetBundleError(f"GM group has no frames: {name}")
        maximum_frames = (
            MAX_FRAMES_PER_GROUP
            if enforce_v1_bounds
            else MAX_PREFLIGHT_FRAMES_PER_GROUP
        )
        if len(spec.frames) > maximum_frames:
            raise UnityAssetBundleError(
                f"GM group exceeds hard preflight frame bound {maximum_frames}: {name}"
            )

        names: set[str] = set()
        slots: set[tuple[int, bool]] = set()
        loaded: list[_LoadedFrame] = []
        for frame_position, frame in enumerate(spec.frames):
            label = f"{name}.frames[{frame_position}]"
            if not isinstance(frame, FrameSource):
                raise UnityAssetBundleError(f"{label} is not a FrameSource")
            frame_name = _require_nfc_string(frame.name, f"{label}.name")
            if frame_name in names:
                raise UnityAssetBundleError(f"Duplicate frame name: {frame_name}")
            names.add(frame_name)
            if (
                isinstance(frame.index, bool)
                or not isinstance(frame.index, int)
                or not 0 <= frame.index < spec.array_size
                or not isinstance(frame.alt, bool)
            ):
                raise UnityAssetBundleError(f"Invalid loader slot for {frame_name}")
            slot = (frame.index, frame.alt)
            if slot in slots:
                raise UnityAssetBundleError(
                    f"Duplicate loader slot for {name}: index={frame.index}, alt={frame.alt}"
                )
            slots.add(slot)
            if (
                isinstance(frame.width, bool)
                or not isinstance(frame.width, int)
                or isinstance(frame.height, bool)
                or not isinstance(frame.height, int)
                or frame.width <= 0
                or frame.height <= 0
            ):
                raise UnityAssetBundleError(f"Invalid frame size for {frame_name}")
            if (
                not all(
                    isfinite(value)
                    for value in (frame.pivot_x, frame.pivot_y, frame.pixels_per_unit)
                )
                or not -MAX_ABSOLUTE_SPRITE_PIVOT
                <= frame.pivot_x
                <= MAX_ABSOLUTE_SPRITE_PIVOT
                or not -MAX_ABSOLUTE_SPRITE_PIVOT
                <= frame.pivot_y
                <= MAX_ABSOLUTE_SPRITE_PIVOT
                or not 1.0 / 1024.0 <= frame.pixels_per_unit <= 4096.0
            ):
                raise UnityAssetBundleError(f"Invalid sprite metadata for {frame_name}")

            expected_size = (frame.width, frame.height)
            main, main_digest = _load_rgba_png(
                frame.main_path,
                expected_size=expected_size,
                label=f"{frame_name} main",
            )
            mask: Image.Image | None = None
            mask_digest: str | None = None
            try:
                if spec.mask_policy == "required":
                    if frame.mask_path is None:
                        raise UnityAssetBundleError(
                            f"Required mask is missing: {frame_name}"
                        )
                    mask, mask_digest = _load_rgba_png(
                        frame.mask_path,
                        expected_size=expected_size,
                        label=f"{frame_name} mask",
                    )
                elif frame.mask_path is not None:
                    raise UnityAssetBundleError(
                        f"Forbidden mask was supplied for {frame_name}"
                    )
                loaded.append(
                    _LoadedFrame(
                        source=frame,
                        main_rgba_sha256=main_digest,
                        mask_rgba_sha256=mask_digest,
                    )
                )
            finally:
                main.close()
                if mask is not None:
                    mask.close()
        if not any(not frame.source.alt for frame in loaded):
            raise UnityAssetBundleError(f"GM group has no primary frame: {name}")
        loaded.sort(
            key=lambda item: (
                item.source.index,
                item.source.alt,
                item.source.name,
            )
        )
        validated.append((spec, slug, tuple(loaded)))
    validated.sort(key=lambda item: item[0].group)
    return tuple(validated)


def _input_frame_records(
    frames: Sequence[_LoadedFrame],
) -> list[dict[str, object]]:
    return [
        {
            "name": frame.source.name,
            "index": frame.source.index,
            "alt": frame.source.alt,
            "width": frame.source.width,
            "height": frame.source.height,
            "pivot": {
                "x": 0.0 if frame.source.pivot_x == 0 else frame.source.pivot_x,
                "y": 0.0 if frame.source.pivot_y == 0 else frame.source.pivot_y,
            },
            "pixels_per_unit": frame.source.pixels_per_unit,
            "main_rgba_sha256": frame.main_rgba_sha256,
            "mask_rgba_sha256": frame.mask_rgba_sha256,
        }
        for frame in frames
    ]


def _frame_bindings_from_loaded(
    frames: Sequence[_LoadedFrame],
) -> dict[str, object]:
    records = _input_frame_records(frames)
    names = [str(record["name"]) for record in records]
    metadata = [
        {
            "alt": record["alt"],
            "height": record["height"],
            "index": record["index"],
            "name": record["name"],
            "pixels_per_unit": record["pixels_per_unit"],
            "pivot": record["pivot"],
            "width": record["width"],
        }
        for record in records
    ]
    main = [
        {
            "alt": record["alt"],
            "index": record["index"],
            "name": record["name"],
            "sha256": record["main_rgba_sha256"],
        }
        for record in records
    ]
    masks = [
        {
            "alt": record["alt"],
            "index": record["index"],
            "name": record["name"],
            "sha256": record["mask_rgba_sha256"],
        }
        for record in records
    ]
    if all(record["sha256"] is None for record in masks):
        mask_digest: str | None = None
    elif any(record["sha256"] is None for record in masks):
        raise UnityAssetBundleError("V2 source has a partially populated mask set")
    else:
        mask_digest = _sha256_bytes(
            _canonical_json_bytes(masks, final_lf=False)
        )
    return {
        "count": len(records),
        "main_rgba_sha256": _sha256_bytes(
            _canonical_json_bytes(main, final_lf=False)
        ),
        "mask_rgba_sha256": mask_digest,
        "metadata_sha256": _sha256_bytes(
            _canonical_json_bytes(metadata, final_lf=False)
        ),
        "names_sha256": _sha256_bytes(
            _canonical_json_bytes(names, final_lf=False)
        ),
    }


def fingerprint_atlas_groups_v2(
    groups: Sequence[AtlasGroupInput],
) -> tuple[AtlasGroupFingerprint, ...]:
    """Validate/hash every V2 source group without doing atlas work."""

    validated = _validated_groups(groups, enforce_v1_bounds=True)
    result: list[AtlasGroupFingerprint] = []
    for spec, slug, loaded_frames in validated:
        if spec.padding_pixels != BC7_MINIMUM_BORDER_PIXELS:
            raise UnityAssetBundleError(
                f"V2 minimum border must be one pixel: {spec.group}"
            )
        if spec.filter_mode not in {"Point", "Bilinear"}:
            raise UnityAssetBundleError(
                f"V2 filter mode is invalid for {spec.group}: {spec.filter_mode!r}"
            )
        result.append(
            AtlasGroupFingerprint(
                spec=spec,
                slug=slug,
                loaded_frames=loaded_frames,
                frame_bindings=_frame_bindings_from_loaded(loaded_frames),
            )
        )
    return tuple(result)


def preflight_atlas_groups(
    groups: Sequence[AtlasGroupInput],
    *,
    foliage_groups: Sequence[str] = (),
) -> AtlasGroupPreflight:
    """Classify every selected group without turning expected v1 bounds global.

    All source files and semantic fields are still validated first. Only the
    five enumerated, deterministic v1 representation limits may produce a
    vanilla omission; every other failure remains fail-closed for the build.
    """

    validated = _validated_groups(groups, enforce_v1_bounds=False)
    foliage = {str(name).casefold() for name in foliage_groups}
    accepted: list[AtlasGroupInput] = []
    omitted: list[VanillaOmittedGroup] = []
    for spec, _slug, loaded_frames in validated:
        records = _input_frame_records(loaded_frames)
        names_sha256 = _sha256_bytes(
            _canonical_json_bytes(
                [record["name"] for record in records], final_lf=False
            )
        )
        frames_sha256 = _sha256_bytes(
            _canonical_json_bytes(records, final_lf=False)
        )

        reason: str | None = None
        if len(loaded_frames) > MAX_FRAMES_PER_GROUP:
            reason = OMISSION_FRAME_COUNT
        elif spec.array_size > MAX_FRAMES_PER_GROUP or any(
            frame.source.index >= MAX_FRAMES_PER_GROUP for frame in loaded_frames
        ):
            reason = OMISSION_SLOT_COUNT
        elif any(
            frame.source.width + 2 * spec.padding_pixels > MAX_PAGE_DIMENSION
            or frame.source.height + 2 * spec.padding_pixels > MAX_PAGE_DIMENSION
            for frame in loaded_frames
        ):
            reason = OMISSION_FRAME_DIMENSION
        else:
            representatives, _representative_by_name = _deduplicate_loaded_frames(
                loaded_frames, mask_policy=spec.mask_policy
            )
            packing = pack_rectangles(
                [
                    PackItem(
                        frame.source.name,
                        frame.source.width,
                        frame.source.height,
                        slot_index=frame.source.index,
                        alt=frame.source.alt,
                        ordinal_name=frame.source.name,
                    )
                    for frame in representatives
                ],
                max_page_dimension=MAX_PAGE_DIMENSION,
                padding_pixels=spec.padding_pixels,
            )
            if len(packing.pages) > MAX_PAGES_PER_GROUP:
                reason = OMISSION_PAGE_COUNT
            elif len(packing.pages) > 1 and spec.group.casefold() in foliage:
                reason = OMISSION_FOLIAGE_MULTIPAGE
            elif (
                len(packing.pages) > 1
                and spec.material_binding == GROUP_MASK_MATERIAL_BINDING
            ):
                reason = OMISSION_PAGE_COUNT

        if reason is None:
            accepted.append(spec)
            continue
        omitted.append(
            VanillaOmittedGroup(
                group=spec.group,
                gm_id=spec.gm_id,
                reason=reason,
                array_size=spec.array_size,
                frame_count=len(loaded_frames),
                names_sha256=names_sha256,
                frames_sha256=frames_sha256,
            )
        )
    return AtlasGroupPreflight(tuple(accepted), tuple(omitted))


def preflight_atlas_groups_v2(
    groups: Sequence[AtlasGroupInput],
    *,
    foliage_groups: Sequence[str] = (),
) -> AtlasGroupPreflight:
    """Create the immutable Full-build plan used verbatim by V2 preparation.

    Unlike V1, V2 never turns a selected group into a vanilla omission.  The
    owner requested a complete build, so every representation failure is a
    hard failure rather than a visually mixed fallback.
    """

    return preflight_atlas_fingerprints_v2(
        fingerprint_atlas_groups_v2(groups), foliage_groups=foliage_groups
    )


def preflight_atlas_fingerprints_v2(
    fingerprints: Sequence[AtlasGroupFingerprint],
    *,
    foliage_groups: Sequence[str] = (),
) -> AtlasGroupPreflight:
    """Pack only already fingerprinted V2 groups (normally cache misses)."""

    if not fingerprints:
        raise UnityAssetBundleError("At least one V2 fingerprint is required")
    ordered = tuple(sorted(fingerprints, key=lambda item: item.spec.group))
    if any(
        not isinstance(item, AtlasGroupFingerprint)
        or item.pipeline_version != 2
        or item.slug != group_slug(item.spec.group)
        or tuple(frame.source for frame in item.loaded_frames) != item.spec.frames
        or item.spec.padding_pixels != BC7_MINIMUM_BORDER_PIXELS
        or item.spec.filter_mode not in {"Point", "Bilinear"}
        or item.frame_bindings != _frame_bindings_from_loaded(item.loaded_frames)
        for item in ordered
    ):
        raise UnityAssetBundleError("V2 source fingerprint binding drifted")
    if len({item.spec.group.casefold() for item in ordered}) != len(ordered):
        raise UnityAssetBundleError("V2 source fingerprints repeat a group")
    foliage = {str(name).casefold() for name in foliage_groups}
    plans: list[AtlasGroupPlan] = []
    for fingerprint in ordered:
        spec = fingerprint.spec
        slug = fingerprint.slug
        loaded_frames = fingerprint.loaded_frames
        representatives, representative_by_name = _deduplicate_loaded_frames(
            loaded_frames, mask_policy=spec.mask_policy
        )
        packing = pack_rectangles_bc7(
            tuple(
                PackItem(
                    frame.source.name,
                    frame.source.width,
                    frame.source.height,
                    slot_index=frame.source.index,
                    alt=frame.source.alt,
                    ordinal_name=frame.source.name,
                )
                for frame in representatives
            ),
            max_page_dimension=MAX_PAGE_DIMENSION,
            single_page_required=(
                spec.material_binding == GROUP_MASK_MATERIAL_BINDING
                or spec.group.casefold() in foliage
            ),
        )
        if len(packing.pages) > MAX_PAGES_PER_GROUP:
            raise UnityAssetBundleError(
                f"V2 group exceeds {MAX_PAGES_PER_GROUP} pages: {spec.group}"
            )
        if len(packing.pages) > 1 and spec.group.casefold() in foliage:
            raise UnityAssetBundleError(
                f"V2 foliage group is not representable on one page: {spec.group}"
            )
        if (
            len(packing.pages) > 1
            and spec.material_binding == GROUP_MASK_MATERIAL_BINDING
        ):
            raise UnityAssetBundleError(
                f"V2 group-mask binding is not representable on multiple pages: {spec.group}"
            )
        plans.append(
            AtlasGroupPlan(
                spec=spec,
                slug=slug,
                loaded_frames=loaded_frames,
                representative_frames=representatives,
                representative_by_name=tuple(sorted(representative_by_name.items())),
                packing=packing,
                pipeline_version=2,
            )
        )
    return AtlasGroupPreflight(
        groups=tuple(plan.spec for plan in plans),
        vanilla_omitted_groups=(),
        plans=tuple(plans),
    )


def _default_editor_source(workspace_root: Path) -> Path:
    return workspace_root / _EDITOR_SOURCE_RELATIVE


def _validated_omissions(
    items: Sequence[VanillaOmittedGroup],
    accepted: Sequence[tuple[AtlasGroupInput, str, tuple[_LoadedFrame, ...]]],
) -> tuple[VanillaOmittedGroup, ...]:
    result: list[VanillaOmittedGroup] = []
    seen_groups = {spec.group.casefold() for spec, _slug, _frames in accepted}
    seen_ids = {spec.gm_id for spec, _slug, _frames in accepted}
    for position, item in enumerate(items):
        if not isinstance(item, VanillaOmittedGroup):
            raise UnityAssetBundleError(
                f"vanilla_omitted_groups[{position}] is not a VanillaOmittedGroup"
            )
        group = _require_nfc_string(
            item.group, f"vanilla_omitted_groups[{position}].group"
        )
        group_slug(group)
        if group.casefold() in seen_groups:
            raise UnityAssetBundleError(
                f"Duplicate/colliding selected GM group: {group}"
            )
        if (
            isinstance(item.gm_id, bool)
            or not isinstance(item.gm_id, int)
            or not 0 <= item.gm_id < MAX_GROUPS
            or item.gm_id in seen_ids
        ):
            raise UnityAssetBundleError(f"Invalid/duplicate omitted gm_id: {item.gm_id}")
        if item.reason not in VANILLA_OMISSION_REASONS:
            raise UnityAssetBundleError(
                f"Invalid vanilla omission reason for {group}: {item.reason!r}"
            )
        if (
            isinstance(item.array_size, bool)
            or not isinstance(item.array_size, int)
            or not 1 <= item.array_size <= MAX_PREFLIGHT_ARRAY_SIZE
            or isinstance(item.frame_count, bool)
            or not isinstance(item.frame_count, int)
            or not 1 <= item.frame_count <= MAX_PREFLIGHT_FRAMES_PER_GROUP
            or _SHA256_RE.fullmatch(item.names_sha256) is None
            or _SHA256_RE.fullmatch(item.frames_sha256) is None
        ):
            raise UnityAssetBundleError(f"Invalid omission binding for {group}")
        seen_groups.add(group.casefold())
        seen_ids.add(item.gm_id)
        result.append(item)
    if tuple(item.group for item in result) != tuple(
        sorted(item.group for item in result)
    ):
        raise UnityAssetBundleError(
            "vanilla_omitted_groups must be sorted by group ordinal"
        )
    if not 1 <= len(accepted) + len(result) <= MAX_GROUPS:
        raise UnityAssetBundleError("Selected GM group count is outside v1 limits")
    return tuple(result)


def _build_seed(
    groups: Sequence[tuple[AtlasGroupInput, str, tuple[_LoadedFrame, ...]]],
    vanilla_omitted_groups: Sequence[VanillaOmittedGroup],
    editor_source_sha256: str,
    preparer_source_sha256: str,
) -> dict[str, object]:
    return {
        "schema": "stronghold-europe-de.asset-bundle-preparation-seed.v1",
        "unity": {"version": UNITY_VERSION, "revision": UNITY_REVISION},
        "build_target": BUILD_TARGET,
        "build_options": list(BUILD_OPTIONS),
        "packer": PACKER_ID,
        "preparer_source_sha256": preparer_source_sha256,
        "png_encoder": (
            f"pillow-{PILLOW_VERSION}-zlib-{zlib.ZLIB_VERSION}-"
            "rgba-png-compress9-no-optimize-v1"
        ),
        "max_page_dimension": MAX_PAGE_DIMENSION,
        "editor_script_sha256": editor_source_sha256,
        "groups": [
            {
                "group": spec.group,
                "slug": slug,
                "gm_id": spec.gm_id,
                "dash_format": spec.dash_format,
                "array_size": spec.array_size,
                "lifetime": spec.lifetime,
                "mask_policy": spec.mask_policy,
                "material_binding": spec.material_binding,
                "padding_pixels": spec.padding_pixels,
                "frames": _input_frame_records(frames),
            }
            for spec, slug, frames in groups
        ],
        "vanilla_omitted_groups": [
            {
                "group": item.group,
                "gm_id": item.gm_id,
                "reason": item.reason,
                "array_size": item.array_size,
                "frame_count": item.frame_count,
                "names_sha256": item.names_sha256,
                "frames_sha256": item.frames_sha256,
            }
            for item in vanilla_omitted_groups
        ],
    }


def _build_seed_v2(
    plans: Sequence[AtlasGroupPlan],
    *,
    editor_source_sha256: str,
    preparer_source_sha256: str,
    texture_policy_id: str,
    quality_policy_id: str,
    quality_policy_sha256: str,
    quality_mode: str,
) -> dict[str, object]:
    texture_formats = _v2_texture_formats(texture_policy_id)
    return {
        "backend": BC7_BACKEND_KIND,
        "build_options": list(BUILD_OPTIONS),
        "build_target": BUILD_TARGET,
        "editor_script_sha256": editor_source_sha256,
        "encoder_id": BC7_ENCODER_ID,
        "groups": [
            {
                "array_size": plan.spec.array_size,
                "dash_format": plan.spec.dash_format,
                "filter_mode": plan.spec.filter_mode,
                "frames": _input_frame_records(plan.loaded_frames),
                "gm_id": plan.spec.gm_id,
                "group": plan.spec.group,
                "lifetime": plan.spec.lifetime,
                "mask_policy": plan.spec.mask_policy,
                "material_binding": plan.spec.material_binding,
                "packing": {
                    "pages": [
                        {"height": page.height, "id": page.id, "width": page.width}
                        for page in plan.packing.pages
                    ],
                    "rects": [
                        {
                            "height": rect.height,
                            "key": rect.key,
                            "page": rect.page,
                            "storage_height": rect.storage_height,
                            "storage_width": rect.storage_width,
                            "storage_x": rect.storage_x,
                            "storage_y": rect.storage_y,
                            "width": rect.width,
                            "x": rect.x,
                            "y": rect.y,
                        }
                        for rect in plan.packing.rects
                    ],
                },
                "slug": plan.slug,
            }
            for plan in plans
        ],
        "max_page_dimension": MAX_PAGE_DIMENSION,
        "packer_id": BC7_PACKER_ID,
        "png_encoder": (
            f"pillow-{PILLOW_VERSION}-zlib-{zlib.ZLIB_VERSION}-"
            "rgba-png-compress9-no-optimize-v1"
        ),
        "preparer_source_sha256": preparer_source_sha256,
        "quality_policy": {
            "id": quality_policy_id,
            "sha256": quality_policy_sha256,
            "state": quality_mode,
            "verifier_id": BC7_VERIFIER_ID,
        },
        "schema": BC7_PREPARATION_SEED_SCHEMA,
        "texture_policy": {
            "id": texture_policy_id,
            "main_format": texture_formats[0],
            "mask_format": texture_formats[1],
        },
        "unity": {"revision": UNITY_REVISION, "version": UNITY_VERSION},
    }


def _v2_texture_formats(texture_policy_id: str) -> tuple[str, str]:
    if texture_policy_id == BC7_MAIN_BC7_MASK_TEXTURE_POLICY_ID:
        return ("BC7", "BC7")
    if texture_policy_id == BC7_MAIN_RGBA32_MASK_TEXTURE_POLICY_ID:
        return ("BC7", "RGBA32")
    raise UnityAssetBundleError(
        f"Unsupported global V2 texture policy: {texture_policy_id!r}"
    )


def _texture_gpu_bytes(width: int, height: int, format_name: str) -> int:
    if format_name == "BC7":
        return ((width + 3) // 4) * ((height + 3) // 4) * 16
    if format_name == "RGBA32":
        return width * height * 4
    raise UnityAssetBundleError(f"Unsupported V2 texture format: {format_name!r}")


def _bc7_group_resident_charge(gpu_bytes: int) -> int:
    if isinstance(gpu_bytes, bool) or not isinstance(gpu_bytes, int) or gpu_bytes <= 0:
        raise UnityAssetBundleError("V2 group GPU bytes must be positive")
    adjusted = (gpu_bytes * 9 + 7) // 8
    alignment = 4 * 1024 * 1024
    return _align_up(adjusted, alignment)


def _texture_contract_id(plane: str, format_name: str, filter_mode: str) -> str:
    if plane not in {"main", "mask"} or filter_mode not in {"Point", "Bilinear"}:
        raise UnityAssetBundleError("Invalid texture-contract identity components")
    if plane == "main" and format_name != "BC7":
        raise UnityAssetBundleError("V2 main textures must be BC7")
    if plane == "mask" and format_name not in {"BC7", "RGBA32"}:
        raise UnityAssetBundleError("V2 mask texture format is invalid")
    return f"{plane}-{format_name.lower()}-{filter_mode.lower()}-v1"


def _folder_meta(guid: str) -> bytes:
    return (
        "fileFormatVersion: 2\n"
        f"guid: {guid}\n"
        "folderAsset: yes\n"
        "DefaultImporter:\n"
        "  externalObjects: {}\n"
        "  userData: \n"
        "  assetBundleName: \n"
        "  assetBundleVariant: \n"
    ).encode("utf-8")


def _text_meta(guid: str) -> bytes:
    return (
        "fileFormatVersion: 2\n"
        f"guid: {guid}\n"
        "TextScriptImporter:\n"
        "  externalObjects: {}\n"
        "  userData: \n"
        "  assetBundleName: \n"
        "  assetBundleVariant: \n"
    ).encode("utf-8")


def _mono_meta(guid: str) -> bytes:
    return (
        "fileFormatVersion: 2\n"
        f"guid: {guid}\n"
        "MonoImporter:\n"
        "  externalObjects: {}\n"
        "  serializedVersion: 2\n"
        "  defaultReferences: []\n"
        "  executionOrder: 0\n"
        "  icon: {instanceID: 0}\n"
        "  userData: \n"
        "  assetBundleName: \n"
        "  assetBundleVariant: \n"
    ).encode("utf-8")


def _texture_meta(guid: str) -> bytes:
    """Unity 2021.3 TextureImporter YAML mirrored by the Editor build guard."""

    return (
        "fileFormatVersion: 2\n"
        f"guid: {guid}\n"
        "TextureImporter:\n"
        "  internalIDToNameTable: []\n"
        "  externalObjects: {}\n"
        "  serializedVersion: 12\n"
        "  mipmaps:\n"
        "    mipMapMode: 0\n"
        "    enableMipMap: 0\n"
        "    sRGBTexture: 1\n"
        "    linearTexture: 0\n"
        "    fadeOut: 0\n"
        "    borderMipMap: 0\n"
        "    mipMapsPreserveCoverage: 0\n"
        "    alphaTestReferenceValue: 0.5\n"
        "    mipMapFadeDistanceStart: 1\n"
        "    mipMapFadeDistanceEnd: 3\n"
        "  bumpmap:\n"
        "    convertToNormalMap: 0\n"
        "    externalNormalMap: 0\n"
        "    heightScale: 0.25\n"
        "    normalMapFilter: 0\n"
        "  isReadable: 0\n"
        "  streamingMipmaps: 0\n"
        "  streamingMipmapsPriority: 0\n"
        "  vTOnly: 0\n"
        "  ignoreMasterTextureLimit: 0\n"
        "  grayScaleToAlpha: 0\n"
        "  generateCubemap: 6\n"
        "  cubemapConvolution: 0\n"
        "  seamlessCubemap: 0\n"
        "  textureFormat: 1\n"
        f"  maxTextureSize: {MAX_PAGE_DIMENSION}\n"
        "  textureSettings:\n"
        "    serializedVersion: 2\n"
        "    filterMode: 0\n"
        "    aniso: 0\n"
        "    mipBias: 0\n"
        "    wrapU: 1\n"
        "    wrapV: 1\n"
        "    wrapW: 1\n"
        "  nPOTScale: 0\n"
        "  lightmap: 0\n"
        "  compressionQuality: 100\n"
        "  spriteMode: 0\n"
        "  spriteExtrude: 1\n"
        "  spriteMeshType: 1\n"
        "  alignment: 0\n"
        "  spritePivot: {x: 0.5, y: 0.5}\n"
        "  spritePixelsToUnits: 100\n"
        "  spriteBorder: {x: 0, y: 0, z: 0, w: 0}\n"
        "  spriteGenerateFallbackPhysicsShape: 0\n"
        "  alphaUsage: 1\n"
        "  alphaIsTransparency: 0\n"
        "  spriteTessellationDetail: -1\n"
        "  textureType: 0\n"
        "  textureShape: 1\n"
        "  singleChannelComponent: 0\n"
        "  flipbookRows: 1\n"
        "  flipbookColumns: 1\n"
        "  maxTextureSizeSet: 0\n"
        "  compressionQualitySet: 0\n"
        "  textureFormatSet: 0\n"
        "  ignorePngGamma: 1\n"
        "  applyGammaDecoding: 0\n"
        "  cookieLightType: 0\n"
        "  platformSettings:\n"
        "  - serializedVersion: 3\n"
        "    buildTarget: DefaultTexturePlatform\n"
        f"    maxTextureSize: {MAX_PAGE_DIMENSION}\n"
        "    resizeAlgorithm: 0\n"
        "    textureFormat: 4\n"
        "    textureCompression: 0\n"
        "    compressionQuality: 100\n"
        "    crunchedCompression: 0\n"
        "    allowsAlphaSplitting: 0\n"
        "    overridden: 1\n"
        "    androidETC2FallbackOverride: 0\n"
        "    forceMaximumCompressionQuality_BC6H_BC7: 0\n"
        "  - serializedVersion: 3\n"
        "    buildTarget: Standalone\n"
        f"    maxTextureSize: {MAX_PAGE_DIMENSION}\n"
        "    resizeAlgorithm: 0\n"
        "    textureFormat: 4\n"
        "    textureCompression: 0\n"
        "    compressionQuality: 100\n"
        "    crunchedCompression: 0\n"
        "    allowsAlphaSplitting: 0\n"
        "    overridden: 1\n"
        "    androidETC2FallbackOverride: 0\n"
        "    forceMaximumCompressionQuality_BC6H_BC7: 0\n"
        "  spriteSheet:\n"
        "    serializedVersion: 2\n"
        "    sprites: []\n"
        "    outline: []\n"
        "    physicsShape: []\n"
        "    bones: []\n"
        "    spriteID: \n"
        "    internalID: 0\n"
        "    vertices: []\n"
        "    indices: \n"
        "    edges: []\n"
        "    weights: []\n"
        "    secondaryTextures: []\n"
        "    nameFileIdTable: {}\n"
        "  mipmapLimitGroupName: \n"
        "  pSDRemoveMatte: 0\n"
        "  userData: \n"
        "  assetBundleName: \n"
        "  assetBundleVariant: \n"
    ).encode("utf-8")


def _texture_meta_v2(
    guid: str,
    *,
    filter_mode: str,
    format_name: str,
) -> bytes:
    """Exact Unity-2021.3 YAML present before the editor imports a V2 PNG."""

    contract = _bc7_texture_contract(filter_mode, format_name=format_name)
    filter_value = 0 if filter_mode == "Point" else 1
    format_value = 25 if format_name == "BC7" else 4
    compression_value = 2 if format_name == "BC7" else 0
    force_maximum = 1 if format_name == "BC7" else 0
    text = _texture_meta(guid).decode("utf-8")
    text = text.replace("    filterMode: 0\n", f"    filterMode: {filter_value}\n", 1)
    text = text.replace(
        "    textureFormat: 4\n",
        f"    textureFormat: {format_value}\n",
    )
    text = text.replace(
        "    textureCompression: 0\n",
        f"    textureCompression: {compression_value}\n",
    )
    text = text.replace(
        "    forceMaximumCompressionQuality_BC6H_BC7: 0\n",
        f"    forceMaximumCompressionQuality_BC6H_BC7: {force_maximum}\n",
    )
    if (
        text.count(f"    textureFormat: {format_value}\n") != 2
        or text.count(f"    textureCompression: {compression_value}\n") != 2
        or text.count(
            f"    forceMaximumCompressionQuality_BC6H_BC7: {force_maximum}\n"
        )
        != 2
        or "  textureFormat: 1\n" not in text
        or contract["mipmaps"] is not False
    ):
        raise UnityAssetBundleError("V2 TextureImporter meta transformation drifted")
    return text.encode("utf-8")


def _write_asset_meta(project: Path, asset_path: str, kind: str) -> None:
    guid = stable_unity_guid(asset_path)
    destination = project.joinpath(*asset_path.split("/")).with_name(
        PurePosixPath(asset_path).name + ".meta"
    )
    if kind == "folder":
        payload = _folder_meta(guid)
    elif kind == "text":
        payload = _text_meta(guid)
    elif kind == "mono":
        payload = _mono_meta(guid)
    elif kind == "texture":
        payload = _texture_meta(guid)
    else:  # pragma: no cover - internal call sites are fixed
        raise AssertionError(kind)
    _write_bytes(destination, payload)


def _write_texture_meta_v2(
    project: Path,
    asset_path: str,
    *,
    filter_mode: str,
    format_name: str,
) -> None:
    destination = project.joinpath(*asset_path.split("/")).with_name(
        PurePosixPath(asset_path).name + ".meta"
    )
    _write_bytes(
        destination,
        _texture_meta_v2(
            stable_unity_guid(asset_path),
            filter_mode=filter_mode,
            format_name=format_name,
        ),
    )


def _write_png(path: Path, image: Image.Image) -> str:
    if image.mode != "RGBA":
        raise UnityAssetBundleError("Generated atlas page is not RGBA")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        image.save(stream, format="PNG", optimize=False, compress_level=9)
        stream.flush()
        os.fsync(stream.fileno())
    return _sha256_file(path)


def _compose_atlas_page(
    page: PackedPage,
    frames: Sequence[_LoadedFrame],
    packed_by_name: Mapping[str, PackedRect],
    *,
    mask_plane: bool,
) -> Image.Image:
    """Compose one plane while keeping memory bounded to one page and frame."""

    result = Image.new("RGBA", (page.width, page.height), (0, 0, 0, 0))
    try:
        for frame in frames:
            packed = packed_by_name[frame.source.name]
            if packed.page != page.id:
                continue
            source_path = frame.source.mask_path if mask_plane else frame.source.main_path
            expected_digest = (
                frame.mask_rgba_sha256 if mask_plane else frame.main_rgba_sha256
            )
            if source_path is None or expected_digest is None:
                raise UnityAssetBundleError(
                    f"Missing {'mask' if mask_plane else 'main'} plane: "
                    f"{frame.source.name}"
                )
            source, actual_digest = _load_rgba_png(
                source_path,
                expected_size=(frame.source.width, frame.source.height),
                label=(
                    f"{frame.source.name} "
                    f"{'mask' if mask_plane else 'main'} during composition"
                ),
            )
            try:
                if actual_digest != expected_digest:
                    raise UnityAssetBundleError(
                        f"Source pixels changed during preparation: {frame.source.name}"
                    )
                result.paste(source, (packed.x, packed.y))
            finally:
                source.close()
        return result
    except Exception:
        result.close()
        raise


def _extruded_bc7_cell(
    source: Image.Image,
    *,
    cell_width: int,
    cell_height: int,
) -> Image.Image:
    """Fill every guard pixel with the nearest visible RGBA edge pixel."""

    if (
        source.mode != "RGBA"
        or cell_width % BC7_BLOCK_ALIGNMENT_PIXELS
        or cell_height % BC7_BLOCK_ALIGNMENT_PIXELS
        or cell_width < source.width + 2
        or cell_height < source.height + 2
    ):
        raise UnityAssetBundleError("Invalid BC7 extrusion cell")
    right_guard = cell_width - source.width - 1
    bottom_guard = cell_height - source.height - 1
    cell = Image.new("RGBA", (cell_width, cell_height), (0, 0, 0, 0))
    try:
        cell.paste(source, (1, 1))
        strips = (
            ((0, 0, 1, source.height), (0, 1, 1, source.height)),
            (
                (source.width - 1, 0, source.width, source.height),
                (source.width + 1, 1, right_guard, source.height),
            ),
            ((0, 0, source.width, 1), (1, 0, source.width, 1)),
            (
                (0, source.height - 1, source.width, source.height),
                (1, source.height + 1, source.width, bottom_guard),
            ),
            ((0, 0, 1, 1), (0, 0, 1, 1)),
            (
                (source.width - 1, 0, source.width, 1),
                (source.width + 1, 0, right_guard, 1),
            ),
            (
                (0, source.height - 1, 1, source.height),
                (0, source.height + 1, 1, bottom_guard),
            ),
            (
                (source.width - 1, source.height - 1, source.width, source.height),
                (source.width + 1, source.height + 1, right_guard, bottom_guard),
            ),
        )
        for crop_box, destination in strips:
            x, y, width, height = destination
            if width <= 0 or height <= 0:
                raise UnityAssetBundleError("BC7 extrusion guard is empty")
            with source.crop(crop_box) as pixel_or_strip:
                expanded = pixel_or_strip.resize(
                    (width, height), resample=Image.Resampling.NEAREST
                )
                try:
                    cell.paste(expanded, (x, y))
                finally:
                    expanded.close()
        return cell
    except Exception:
        cell.close()
        raise


def _compose_atlas_page_v2(
    page: PackedPage,
    frames: Sequence[_LoadedFrame],
    packed_by_name: Mapping[str, PackedRect],
    *,
    mask_plane: bool,
) -> Image.Image:
    """Compose one BC7-safe plane with full nearest-edge RGBA extrusion."""

    result = Image.new("RGBA", (page.width, page.height), (0, 0, 0, 0))
    try:
        for frame in frames:
            packed = packed_by_name[frame.source.name]
            if packed.page != page.id:
                continue
            if any(
                value is None
                for value in (
                    packed.storage_x,
                    packed.storage_y,
                    packed.storage_width,
                    packed.storage_height,
                )
            ):
                raise UnityAssetBundleError(
                    f"BC7 storage cell disappeared: {frame.source.name}"
                )
            source_path = frame.source.mask_path if mask_plane else frame.source.main_path
            expected_digest = (
                frame.mask_rgba_sha256 if mask_plane else frame.main_rgba_sha256
            )
            if source_path is None or expected_digest is None:
                raise UnityAssetBundleError(
                    f"Missing {'mask' if mask_plane else 'main'} plane: "
                    f"{frame.source.name}"
                )
            source, actual_digest = _load_rgba_png(
                source_path,
                expected_size=(frame.source.width, frame.source.height),
                label=(
                    f"{frame.source.name} "
                    f"{'mask' if mask_plane else 'main'} during V2 composition"
                ),
            )
            try:
                if actual_digest != expected_digest:
                    raise UnityAssetBundleError(
                        f"Source pixels changed during V2 preparation: {frame.source.name}"
                    )
                cell = _extruded_bc7_cell(
                    source,
                    cell_width=int(packed.storage_width),
                    cell_height=int(packed.storage_height),
                )
                try:
                    result.paste(
                        cell,
                        (int(packed.storage_x), int(packed.storage_y)),
                    )
                finally:
                    cell.close()
            finally:
                source.close()
        return result
    except Exception:
        result.close()
        raise


def _safe_cleanup_staging(staging: Path, container: Path) -> None:
    try:
        resolved_staging = staging.resolve(strict=True)
        resolved_container = container.resolve(strict=True)
    except (OSError, RuntimeError):
        return
    if (
        resolved_staging.parent != resolved_container
        or not resolved_staging.name.startswith(".prepare-")
    ):
        raise UnityAssetBundleError(
            f"Refusing to clean unexpected preparation path: {resolved_staging}"
        )
    shutil.rmtree(resolved_staging)


def prepare_unity_asset_bundle_project(
    workspace_root: Path,
    groups: Sequence[AtlasGroupInput],
    *,
    vanilla_omitted_groups: Sequence[VanillaOmittedGroup] = (),
    editor_source: Path | None = None,
) -> PreparedUnityProject:
    """Prepare one immutable, ephemeral Unity project below ``work/``.

    Source PNGs are read but never changed. The returned project is placed at
    ``work/unity-ab/<build-id-prefix>/project``. Existing build ids are not
    overwritten; a caller must validate/reuse or choose a clean workspace.
    """

    try:
        root = Path(workspace_root).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise UnityAssetBundleError(
            f"Workspace root does not exist: {workspace_root}"
        ) from exc
    if not root.is_dir():
        raise UnityAssetBundleError(f"Workspace root is not a directory: {root}")
    editor = _resolved_input_file(
        editor_source or _default_editor_source(root),
        "Unity Editor builder source",
    )
    editor_payload = editor.read_bytes()
    editor_digest = _sha256_bytes(editor_payload)
    preparer_digest = _sha256_file(Path(__file__).resolve(strict=True))
    validated = _validated_groups(groups) if groups else ()
    omitted = _validated_omissions(vanilla_omitted_groups, validated)
    seed = _build_seed(validated, omitted, editor_digest, preparer_digest)
    build_id = _sha256_bytes(_canonical_json_bytes(seed, final_lf=False))

    work_root = root / "work"
    container = work_root / _WORK_CONTAINER_DIRECTORY
    container.mkdir(parents=True, exist_ok=True)
    resolved_container = container.resolve(strict=True)
    if resolved_container != container.absolute().resolve():
        raise UnityAssetBundleError(
            f"Unity work container is not canonical: {container}"
        )
    final_root = resolved_container / build_id[:_BUILD_DIRECTORY_ID_CHARACTERS]
    if final_root.exists():
        raise UnityAssetBundleError(
            f"Prepared Unity build already exists and will not be overwritten: {final_root}"
        )

    staging = Path(tempfile.mkdtemp(prefix=f".prepare-{build_id[:12]}-", dir=container))
    project = staging / "project"
    try:
        (project / "Assets").mkdir(parents=True)
        (project / "Packages").mkdir()
        (project / "ProjectSettings").mkdir()
        _write_bytes(
            project / "ProjectSettings" / "ProjectVersion.txt",
            (
                f"m_EditorVersion: {UNITY_VERSION}\n"
                f"m_EditorVersionWithRevision: {UNITY_FULL_VERSION}\n"
            ).encode("utf-8"),
        )
        _write_canonical_json(
            project / "Packages" / "manifest.json", {"dependencies": {}}
        )

        editor_asset = project.joinpath(*_EDITOR_ASSET_PATH.split("/"))
        _write_bytes(editor_asset, editor_payload)
        _write_asset_meta(project, "Assets/Editor", "folder")
        _write_asset_meta(project, _EDITOR_ASSET_PATH, "mono")
        _write_asset_meta(project, "Assets/Generated", "folder")
        _write_asset_meta(project, "Assets/Generated/Groups", "folder")

        index_groups: list[dict[str, object]] = []
        texture_inputs: list[dict[str, object]] = []
        bundle_inputs: list[dict[str, object]] = []
        total_pages = 0
        for spec, slug, loaded_frames in validated:
            group_asset_dir = f"Assets/Generated/Groups/{slug}"
            _write_asset_meta(project, group_asset_dir, "folder")
            representative_frames, representative_by_name = _deduplicate_loaded_frames(
                loaded_frames, mask_policy=spec.mask_policy
            )
            packing = pack_rectangles(
                [
                    PackItem(
                        frame.source.name,
                        frame.source.width,
                        frame.source.height,
                        slot_index=frame.source.index,
                        alt=frame.source.alt,
                        ordinal_name=frame.source.name,
                    )
                    for frame in representative_frames
                ],
                max_page_dimension=MAX_PAGE_DIMENSION,
                padding_pixels=spec.padding_pixels,
            )
            if len(packing.pages) > MAX_PAGES_PER_GROUP:
                raise UnityAssetBundleError(
                    f"GM group exceeds {MAX_PAGES_PER_GROUP} pages: {spec.group}"
                )
            if (
                spec.material_binding == GROUP_MASK_MATERIAL_BINDING
                and len(packing.pages) != 1
            ):
                raise UnityAssetBundleError(
                    "group_mask_single_page_v1 cannot represent a multi-page "
                    f"GM group: {spec.group} has {len(packing.pages)} pages"
                )
            total_pages += len(packing.pages)
            packed_representatives = {rect.key: rect for rect in packing.rects}
            packed_by_name = {
                frame.source.name: packed_representatives[
                    representative_by_name[frame.source.name]
                ]
                for frame in loaded_frames
            }
            page_records: list[dict[str, object]] = []
            group_bundle_assets: list[dict[str, str]] = []
            for page in packing.pages:
                main_asset = f"{group_asset_dir}/page-{page.id:03d}-main.png"
                main_address = f"sede/gm/{slug}/page/{page.id:03d}/main"
                main = _compose_atlas_page(
                    page, representative_frames, packed_representatives, mask_plane=False
                )
                try:
                    main_rgba_sha256 = _rgba_sha256_image(main)
                    main_png_sha256 = _write_png(
                        project.joinpath(*main_asset.split("/")), main
                    )
                finally:
                    main.close()
                _write_asset_meta(project, main_asset, "texture")
                main_record = {
                    "asset_path": main_asset,
                    "address": main_address,
                    "png_sha256": main_png_sha256,
                    "rgba_sha256": main_rgba_sha256,
                }
                texture_inputs.append(
                    {
                        "asset_path": main_asset,
                        "width": page.width,
                        "height": page.height,
                        "png_sha256": main_record["png_sha256"],
                    }
                )
                group_bundle_assets.append(
                    {"asset_path": main_asset, "address": main_address}
                )

                mask_record: dict[str, str] | None = None
                if spec.mask_policy == "required":
                    mask_asset = f"{group_asset_dir}/page-{page.id:03d}-mask.png"
                    mask_address = f"sede/gm/{slug}/page/{page.id:03d}/mask"
                    mask = _compose_atlas_page(
                        page, representative_frames, packed_representatives, mask_plane=True
                    )
                    try:
                        mask_rgba_sha256 = _rgba_sha256_image(mask)
                        mask_png_sha256 = _write_png(
                            project.joinpath(*mask_asset.split("/")), mask
                        )
                    finally:
                        mask.close()
                    _write_asset_meta(project, mask_asset, "texture")
                    mask_record = {
                        "asset_path": mask_asset,
                        "address": mask_address,
                        "png_sha256": mask_png_sha256,
                        "rgba_sha256": mask_rgba_sha256,
                    }
                    texture_inputs.append(
                        {
                            "asset_path": mask_asset,
                            "width": page.width,
                            "height": page.height,
                            "png_sha256": mask_record["png_sha256"],
                        }
                    )
                    group_bundle_assets.append(
                        {"asset_path": mask_asset, "address": mask_address}
                    )
                page_records.append(
                    {
                        "id": page.id,
                        "width": page.width,
                        "height": page.height,
                        "main": main_record,
                        "mask": mask_record,
                    }
                )

            frame_records: list[dict[str, object]] = []
            page_by_id = {page.id: page for page in packing.pages}
            for frame in loaded_frames:
                packed = packed_by_name[frame.source.name]
                page = page_by_id[packed.page]
                unity_y = page.height - packed.y - packed.height
                if unity_y < 0:
                    raise UnityAssetBundleError(
                        f"Bottom-left conversion escaped page: {frame.source.name}"
                    )
                frame_records.append(
                    {
                        "name": frame.source.name,
                        "index": frame.source.index,
                        "alt": frame.source.alt,
                        "page": packed.page,
                        "rect": {
                            "x": packed.x,
                            "y": unity_y,
                            "width": packed.width,
                            "height": packed.height,
                        },
                        "pivot": {
                            "x": 0.0
                            if frame.source.pivot_x == 0
                            else frame.source.pivot_x,
                            "y": 0.0
                            if frame.source.pivot_y == 0
                            else frame.source.pivot_y,
                        },
                        "pixels_per_unit": frame.source.pixels_per_unit,
                        "main_rgba_sha256": frame.main_rgba_sha256,
                        "mask_rgba_sha256": frame.mask_rgba_sha256,
                    }
                )
            frame_records.sort(
                key=lambda frame: (frame["index"], frame["alt"], frame["name"])
            )
            bundle_name = f"sede.gm.{slug}.v2"
            atlas_asset = f"{group_asset_dir}/atlas.v2.json"
            atlas_address = f"sede/gm/{slug}/atlas.v2.json"
            atlas_document = {
                "schema": ATLAS_SCHEMA,
                "group": spec.group,
                "slug": slug,
                "bundle": bundle_name,
                "mask_policy": spec.mask_policy,
                "material_binding": spec.material_binding,
                "coordinate_system": "unity_bottom_left",
                "padding_pixels": spec.padding_pixels,
                "max_page_dimension": MAX_PAGE_DIMENSION,
                "texture_contract": dict(_TEXTURE_CONTRACT),
                "pages": page_records,
                "frames": frame_records,
                "frames_sha256": _sha256_bytes(
                    _canonical_json_bytes(frame_records, final_lf=False)
                ),
            }
            frames_sha256 = str(atlas_document["frames_sha256"])
            names_sha256 = _sha256_bytes(
                _canonical_json_bytes(
                    [frame["name"] for frame in frame_records], final_lf=False
                )
            )
            raw_rgba_bytes = sum(
                int(page["width"])
                * int(page["height"])
                * 4
                * (2 if page["mask"] is not None else 1)
                for page in page_records
            )
            atlas_payload = _write_canonical_json(
                project.joinpath(*atlas_asset.split("/")), atlas_document
            )
            if len(atlas_payload) > MAX_ATLAS_BYTES:
                raise UnityAssetBundleError(
                    f"atlas.v2 exceeds {MAX_ATLAS_BYTES} bytes: {spec.group}"
                )
            _write_asset_meta(project, atlas_asset, "text")
            group_bundle_assets.append(
                {"asset_path": atlas_asset, "address": atlas_address}
            )
            group_bundle_assets.sort(key=lambda asset: asset["address"])
            bundle_inputs.append(
                {"name": bundle_name, "assets": group_bundle_assets}
            )
            index_groups.append(
                {
                    "group": spec.group,
                    "slug": slug,
                    "gm_id": spec.gm_id,
                    "dash_format": spec.dash_format,
                    "array_size": spec.array_size,
                    "lifetime": spec.lifetime,
                    "bundle": bundle_name,
                    "atlas_asset_path": atlas_asset,
                    "atlas_address": atlas_address,
                    "atlas_sha256": _sha256_bytes(atlas_payload),
                    "mask_policy": spec.mask_policy,
                    "material_binding": spec.material_binding,
                    "page_count": len(page_records),
                    "frame_count": len(frame_records),
                    "names_sha256": names_sha256,
                    "frames_sha256": frames_sha256,
                    "raw_rgba_bytes": raw_rgba_bytes,
                    "resident_charge_bytes": _resident_charge_bytes(raw_rgba_bytes),
                    "pages": [
                        {
                            "id": page["id"],
                            "width": page["width"],
                            "height": page["height"],
                            "main_address": page["main"]["address"],
                            "main_rgba_sha256": page["main"]["rgba_sha256"],
                            "mask_address": (
                                None
                                if page["mask"] is None
                                else page["mask"]["address"]
                            ),
                            "mask_rgba_sha256": (
                                None
                                if page["mask"] is None
                                else page["mask"]["rgba_sha256"]
                            ),
                        }
                        for page in page_records
                    ],
                }
            )

        index_groups.sort(key=lambda group: group["group"])
        index_document = {
            "schema": INDEX_TEMPLATE_SCHEMA,
            "build_id": build_id,
            "unity": {"version": UNITY_VERSION, "revision": UNITY_REVISION},
            "build_target": BUILD_TARGET,
            "max_page_dimension": MAX_PAGE_DIMENSION,
            "groups": index_groups,
            "vanilla_omitted_groups": [
                {
                    "group": item.group,
                    "gm_id": item.gm_id,
                    "reason": item.reason,
                    "array_size": item.array_size,
                    "frame_count": item.frame_count,
                    "names_sha256": item.names_sha256,
                    "frames_sha256": item.frames_sha256,
                }
                for item in omitted
            ],
        }
        index_asset = "Assets/Generated/index.template.json"
        index_path = project.joinpath(*index_asset.split("/"))
        index_payload = _write_canonical_json(index_path, index_document)
        if len(index_payload) > MAX_INDEX_BYTES:
            raise UnityAssetBundleError(
                f"Index template exceeds {MAX_INDEX_BYTES} bytes"
            )
        _write_asset_meta(project, index_asset, "text")
        bundle_inputs.sort(key=lambda bundle: bundle["name"])
        texture_inputs.sort(key=lambda texture: texture["asset_path"])

        build_input_document = {
            "schema": BUILD_INPUT_SCHEMA,
            "build_id": build_id,
            "unity": {"version": UNITY_VERSION, "revision": UNITY_REVISION},
            "build_target": BUILD_TARGET,
            "build_options": list(BUILD_OPTIONS),
            "max_page_dimension": MAX_PAGE_DIMENSION,
            "output_relative_path": _OUTPUT_RELATIVE_PATH,
            "index_template_asset_path": index_asset,
            "index_output_relative_path": _INDEX_OUTPUT_RELATIVE_PATH,
            "editor_script_sha256": editor_digest,
            "bundles": bundle_inputs,
            "textures": texture_inputs,
        }
        build_input_asset = "Assets/Generated/build-input.json"
        build_input_path = project.joinpath(*build_input_asset.split("/"))
        _write_canonical_json(build_input_path, build_input_document)
        _write_asset_meta(project, build_input_asset, "text")

        try:
            os.replace(staging, final_root)
        except OSError as exc:
            raise UnityAssetBundleError(
                f"Could not publish prepared Unity project: {final_root}"
            ) from exc
    except Exception:
        if staging.exists():
            _safe_cleanup_staging(staging, container)
        raise

    prepared = PreparedUnityProject(
        workspace_root=root,
        build_root=final_root,
        project_path=final_root / "project",
        index_template_path=(
            final_root / "project" / "Assets" / "Generated" / "index.template.json"
        ),
        index_path=final_root / "output" / "Runtime" / "AssetBundles" / "index.json",
        build_input_path=(
            final_root / "project" / "Assets" / "Generated" / "build-input.json"
        ),
        output_path=(
            final_root / "output" / "Runtime" / "AssetBundles" / "win64"
        ),
        report_path=final_root / "output" / "build-report.json",
        log_path=final_root / "output" / "unity-editor.log",
        build_id=build_id,
        group_count=len(validated),
        omitted_group_count=len(omitted),
        page_count=total_pages,
    )
    validate_prepared_project(prepared)
    return prepared


def prepare_unity_asset_bundle_project_v2(
    workspace_root: Path,
    preflight: AtlasGroupPreflight,
    *,
    editor_source: Path | None = None,
    texture_policy_id: str = BC7_MAIN_BC7_MASK_TEXTURE_POLICY_ID,
    quality_policy_id: str = BC7_MEASUREMENT_POLICY_ID,
    quality_policy_sha256: str = BC7_MEASUREMENT_POLICY_SHA256,
    quality_mode: str = "measurement_nonpromotable",
    acceptance_envelope: Mapping[str, object] | None = None,
) -> PreparedUnityProject:
    """Materialize an immutable BC7 project from the one preflight pack plan."""

    try:
        root = Path(workspace_root).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise UnityAssetBundleError(
            f"Workspace root does not exist: {workspace_root}"
        ) from exc
    if not root.is_dir():
        raise UnityAssetBundleError(f"Workspace root is not a directory: {root}")
    if (
        not isinstance(preflight, AtlasGroupPreflight)
        or preflight.vanilla_omitted_groups
        or not preflight.plans
        or tuple(plan.spec for plan in preflight.plans) != preflight.groups
        or any(plan.pipeline_version != 2 for plan in preflight.plans)
    ):
        raise UnityAssetBundleError(
            "V2 preparation requires one complete immutable V2 preflight plan"
        )
    for plan in preflight.plans:
        _verify_bc7_packing(plan.packing)
        if tuple(frame.source for frame in plan.loaded_frames) != plan.spec.frames:
            raise UnityAssetBundleError(
                f"V2 preflight frame order/binding drifted: {plan.spec.group}"
            )
    if quality_mode == "measurement_nonpromotable":
        if (
            quality_policy_id != BC7_MEASUREMENT_POLICY_ID
            or quality_policy_sha256 != BC7_MEASUREMENT_POLICY_SHA256
            or acceptance_envelope is not None
        ):
            raise UnityAssetBundleError("Measurement quality policy binding drifted")
    elif quality_mode == "frozen":
        if (
            not quality_policy_id
            or _SHA256_RE.fullmatch(quality_policy_sha256) is None
            or acceptance_envelope is None
        ):
            raise UnityAssetBundleError(
                "Frozen quality mode requires an explicit policy and envelope"
            )
    else:
        raise UnityAssetBundleError(f"Unsupported V2 quality mode: {quality_mode!r}")

    main_format, mask_format = _v2_texture_formats(texture_policy_id)
    editor = _resolved_input_file(
        editor_source or _default_editor_source(root),
        "Unity Editor builder source",
    )
    editor_payload = editor.read_bytes()
    editor_digest = _sha256_bytes(editor_payload)
    preparer_digest = _sha256_file(Path(__file__).resolve(strict=True))
    seed = _build_seed_v2(
        preflight.plans,
        editor_source_sha256=editor_digest,
        preparer_source_sha256=preparer_digest,
        texture_policy_id=texture_policy_id,
        quality_policy_id=quality_policy_id,
        quality_policy_sha256=quality_policy_sha256,
        quality_mode=quality_mode,
    )
    build_id = _sha256_bytes(_canonical_json_bytes(seed, final_lf=False))

    container = root / "work" / _WORK_CONTAINER_DIRECTORY
    container.mkdir(parents=True, exist_ok=True)
    resolved_container = container.resolve(strict=True)
    final_root = resolved_container / build_id[:_BUILD_DIRECTORY_ID_CHARACTERS]
    if final_root.exists():
        raise UnityAssetBundleError(
            f"Prepared Unity build already exists and will not be overwritten: {final_root}"
        )
    staging = Path(tempfile.mkdtemp(prefix=f".prepare-{build_id[:12]}-", dir=container))
    project = staging / "project"
    total_pages = 0
    try:
        (project / "Assets").mkdir(parents=True)
        (project / "Packages").mkdir()
        (project / "ProjectSettings").mkdir()
        _write_bytes(
            project / "ProjectSettings" / "ProjectVersion.txt",
            (
                f"m_EditorVersion: {UNITY_VERSION}\n"
                f"m_EditorVersionWithRevision: {UNITY_FULL_VERSION}\n"
            ).encode("utf-8"),
        )
        _write_canonical_json(
            project / "Packages" / "manifest.json", {"dependencies": {}}
        )
        editor_asset = project.joinpath(*_EDITOR_ASSET_PATH.split("/"))
        _write_bytes(editor_asset, editor_payload)
        _write_asset_meta(project, "Assets/Editor", "folder")
        _write_asset_meta(project, _EDITOR_ASSET_PATH, "mono")
        _write_asset_meta(project, "Assets/Generated", "folder")
        _write_asset_meta(project, "Assets/Generated/Groups", "folder")

        index_groups: list[dict[str, object]] = []
        texture_inputs: list[dict[str, object]] = []
        texture_contract_by_id: dict[str, dict[str, object]] = {}
        bundle_inputs: list[dict[str, object]] = []
        for plan in preflight.plans:
            spec = plan.spec
            slug = plan.slug
            loaded_frames = plan.loaded_frames
            representatives = plan.representative_frames
            representative_by_name = dict(plan.representative_by_name)
            packing = plan.packing
            group_asset_dir = f"Assets/Generated/Groups/{slug}"
            _write_asset_meta(project, group_asset_dir, "folder")
            packed_representatives = {rect.key: rect for rect in packing.rects}
            packed_by_name = {
                frame.source.name: packed_representatives[
                    representative_by_name[frame.source.name]
                ]
                for frame in loaded_frames
            }
            main_contract = _bc7_texture_contract(
                spec.filter_mode, format_name=main_format
            )
            main_contract_id = _texture_contract_id(
                "main", main_format, spec.filter_mode
            )
            prior_contract = texture_contract_by_id.setdefault(
                main_contract_id, main_contract
            )
            if prior_contract != main_contract:
                raise UnityAssetBundleError(
                    f"V2 main texture-contract id collision: {main_contract_id}"
                )
            group_mask_format = mask_format if spec.mask_policy == "required" else None
            mask_contract = (
                None
                if group_mask_format is None
                else _bc7_texture_contract(
                    "Point", format_name=group_mask_format
                )
            )
            mask_contract_id: str | None = None
            if group_mask_format is not None and mask_contract is not None:
                mask_contract_id = _texture_contract_id(
                    "mask", group_mask_format, "Point"
                )
                prior_contract = texture_contract_by_id.setdefault(
                    mask_contract_id, mask_contract
                )
                if prior_contract != mask_contract:
                    raise UnityAssetBundleError(
                        f"V2 mask texture-contract id collision: {mask_contract_id}"
                    )
            page_records: list[dict[str, object]] = []
            index_pages: list[dict[str, object]] = []
            bundle_assets: list[dict[str, str]] = []
            group_gpu_bytes = 0
            group_source_rgba_bytes = 0
            for page in packing.pages:
                main_asset = f"{group_asset_dir}/page-{page.id:03d}-main.png"
                main_address = f"sede/gm/{slug}/page/{page.id:03d}/main"
                main = _compose_atlas_page_v2(
                    page,
                    representatives,
                    packed_representatives,
                    mask_plane=False,
                )
                try:
                    main_rgba_sha256 = _rgba_sha256_image(main)
                    main_png_sha256 = _write_png(
                        project.joinpath(*main_asset.split("/")), main
                    )
                finally:
                    main.close()
                _write_texture_meta_v2(
                    project,
                    main_asset,
                    filter_mode=spec.filter_mode,
                    format_name=main_format,
                )
                main_gpu_bytes = _texture_gpu_bytes(page.width, page.height, main_format)
                main_source_bytes = page.width * page.height * 4
                main_record = {
                    "address": main_address,
                    "asset_path": main_asset,
                    "format": main_format,
                    "gpu_bytes": main_gpu_bytes,
                    "source_png_sha256": main_png_sha256,
                    "source_rgba_bytes": main_source_bytes,
                    "source_rgba_sha256": main_rgba_sha256,
                }
                texture_inputs.append(
                    {
                        "asset_path": main_asset,
                        "gpu_bytes": main_gpu_bytes,
                        "height": page.height,
                        "plane": "main",
                        "source_png_sha256": main_png_sha256,
                        "source_rgba_bytes": main_source_bytes,
                        "source_rgba_sha256": main_rgba_sha256,
                        "texture_contract_id": main_contract_id,
                        "width": page.width,
                    }
                )
                bundle_assets.append(
                    {"address": main_address, "asset_path": main_asset}
                )

                mask_record: dict[str, object] | None = None
                mask_gpu_bytes: int | None = None
                mask_source_bytes = 0
                mask_rgba_sha256: str | None = None
                mask_address: str | None = None
                if spec.mask_policy == "required":
                    assert (
                        group_mask_format is not None
                        and mask_contract is not None
                        and mask_contract_id is not None
                    )
                    mask_asset = f"{group_asset_dir}/page-{page.id:03d}-mask.png"
                    mask_address = f"sede/gm/{slug}/page/{page.id:03d}/mask"
                    mask = _compose_atlas_page_v2(
                        page,
                        representatives,
                        packed_representatives,
                        mask_plane=True,
                    )
                    try:
                        mask_rgba_sha256 = _rgba_sha256_image(mask)
                        mask_png_sha256 = _write_png(
                            project.joinpath(*mask_asset.split("/")), mask
                        )
                    finally:
                        mask.close()
                    _write_texture_meta_v2(
                        project,
                        mask_asset,
                        filter_mode="Point",
                        format_name=group_mask_format,
                    )
                    mask_gpu_bytes = _texture_gpu_bytes(
                        page.width, page.height, group_mask_format
                    )
                    mask_source_bytes = page.width * page.height * 4
                    mask_record = {
                        "address": mask_address,
                        "asset_path": mask_asset,
                        "format": group_mask_format,
                        "gpu_bytes": mask_gpu_bytes,
                        "source_png_sha256": mask_png_sha256,
                        "source_rgba_bytes": mask_source_bytes,
                        "source_rgba_sha256": mask_rgba_sha256,
                    }
                    texture_inputs.append(
                        {
                            "asset_path": mask_asset,
                            "gpu_bytes": mask_gpu_bytes,
                            "height": page.height,
                            "plane": "mask",
                            "source_png_sha256": mask_png_sha256,
                            "source_rgba_bytes": mask_source_bytes,
                            "source_rgba_sha256": mask_rgba_sha256,
                            "texture_contract_id": mask_contract_id,
                            "width": page.width,
                        }
                    )
                    bundle_assets.append(
                        {"address": mask_address, "asset_path": mask_asset}
                    )
                page_records.append(
                    {
                        "height": page.height,
                        "id": page.id,
                        "main": main_record,
                        "mask": mask_record,
                        "width": page.width,
                    }
                )
                index_pages.append(
                    {
                        "height": page.height,
                        "id": page.id,
                        "main_address": main_address,
                        "main_format": main_format,
                        "main_gpu_bytes": main_gpu_bytes,
                        "main_source_rgba_sha256": main_rgba_sha256,
                        "mask_address": mask_address,
                        "mask_format": group_mask_format,
                        "mask_gpu_bytes": mask_gpu_bytes,
                        "mask_source_rgba_sha256": mask_rgba_sha256,
                        "width": page.width,
                    }
                )
                group_gpu_bytes += main_gpu_bytes + (mask_gpu_bytes or 0)
                group_source_rgba_bytes += main_source_bytes + mask_source_bytes

            page_by_id = {page.id: page for page in packing.pages}
            frame_records: list[dict[str, object]] = []
            for frame in loaded_frames:
                packed = packed_by_name[frame.source.name]
                page = page_by_id[packed.page]
                if any(
                    value is None
                    for value in (
                        packed.storage_x,
                        packed.storage_y,
                        packed.storage_width,
                        packed.storage_height,
                    )
                ):
                    raise UnityAssetBundleError(
                        f"V2 storage cell vanished: {frame.source.name}"
                    )
                rect_y = page.height - packed.y - packed.height
                storage_y = (
                    page.height
                    - int(packed.storage_y)
                    - int(packed.storage_height)
                )
                frame_records.append(
                    {
                        "alt": frame.source.alt,
                        "index": frame.source.index,
                        "main_source_rgba_sha256": frame.main_rgba_sha256,
                        "mask_source_rgba_sha256": frame.mask_rgba_sha256,
                        "name": frame.source.name,
                        "page": packed.page,
                        "pixels_per_unit": frame.source.pixels_per_unit,
                        "pivot": {
                            "x": 0.0 if frame.source.pivot_x == 0 else frame.source.pivot_x,
                            "y": 0.0 if frame.source.pivot_y == 0 else frame.source.pivot_y,
                        },
                        "rect": {
                            "height": packed.height,
                            "width": packed.width,
                            "x": packed.x,
                            "y": rect_y,
                        },
                        "storage_cell": {
                            "height": int(packed.storage_height),
                            "width": int(packed.storage_width),
                            "x": int(packed.storage_x),
                            "y": storage_y,
                        },
                    }
                )
            frame_records.sort(
                key=lambda frame: (frame["index"], frame["alt"], frame["name"])
            )
            bundle_name = f"sede.gm.{slug}{BC7_BUNDLE_SUFFIX}"
            atlas_asset = f"{group_asset_dir}/{BC7_ATLAS_ASSET_FILENAME}"
            atlas_address = f"sede/gm/{slug}/{BC7_ATLAS_ASSET_FILENAME}"
            atlas_document = {
                "block_alignment_pixels": BC7_BLOCK_ALIGNMENT_PIXELS,
                "bundle": bundle_name,
                "coordinate_system": "unity_bottom_left",
                "extrusion_mode": "nearest_edge_full_rgba_v1",
                "frames": frame_records,
                "frames_sha256": _sha256_bytes(
                    _canonical_json_bytes(frame_records, final_lf=False)
                ),
                "group": spec.group,
                "mask_policy": spec.mask_policy,
                "material_binding": spec.material_binding,
                "max_page_dimension": MAX_PAGE_DIMENSION,
                "minimum_border_pixels": BC7_MINIMUM_BORDER_PIXELS,
                "pages": page_records,
                "schema": BC7_ATLAS_SCHEMA,
                "slug": slug,
                "texture_contracts": {"main": main_contract, "mask": mask_contract},
            }
            atlas_payload = _write_canonical_json(
                project.joinpath(*atlas_asset.split("/")), atlas_document
            )
            if len(atlas_payload) > MAX_ATLAS_BYTES:
                raise UnityAssetBundleError(
                    f"atlas.v3 exceeds {MAX_ATLAS_BYTES} bytes: {spec.group}"
                )
            _write_asset_meta(project, atlas_asset, "text")
            bundle_assets.append({"address": atlas_address, "asset_path": atlas_asset})
            bundle_assets.sort(key=lambda item: item["address"])
            bundle_inputs.append({"assets": bundle_assets, "name": bundle_name})
            names_sha256 = _sha256_bytes(
                _canonical_json_bytes(
                    [frame["name"] for frame in frame_records], final_lf=False
                )
            )
            resident = _bc7_group_resident_charge(group_gpu_bytes)
            index_groups.append(
                {
                    "array_size": spec.array_size,
                    "atlas_address": atlas_address,
                    "atlas_asset_path": atlas_asset,
                    "atlas_sha256": _sha256_bytes(atlas_payload),
                    "bundle": bundle_name,
                    "dash_format": spec.dash_format,
                    "frame_count": len(frame_records),
                    "frames_sha256": atlas_document["frames_sha256"],
                    "gm_id": spec.gm_id,
                    "gpu_bytes": group_gpu_bytes,
                    "group": spec.group,
                    "lifetime": spec.lifetime,
                    "mask_policy": spec.mask_policy,
                    "material_binding": spec.material_binding,
                    "names_sha256": names_sha256,
                    "page_count": len(page_records),
                    "pages": index_pages,
                    "resident_charge_bytes": resident,
                    "slug": slug,
                    "source_rgba_bytes": group_source_rgba_bytes,
                }
            )
            total_pages += len(page_records)

        index_groups.sort(key=lambda item: str(item["group"]))
        quality_policy = {
            "id": quality_policy_id,
            "sha256": quality_policy_sha256,
            "state": quality_mode,
            "verifier_id": BC7_VERIFIER_ID,
        }
        texture_policy = {
            "id": texture_policy_id,
            "main_format": main_format,
            "mask_format": mask_format,
        }
        index_document = {
            "backend_kind": BC7_BACKEND_KIND,
            "build_id": build_id,
            "build_target": BUILD_TARGET,
            "encoder_id": BC7_ENCODER_ID,
            "groups": index_groups,
            "max_page_dimension": MAX_PAGE_DIMENSION,
            "packer_id": BC7_PACKER_ID,
            "quality_policy": quality_policy,
            "quality_report_sha256": None,
            "schema": BC7_INDEX_TEMPLATE_SCHEMA,
            "texture_policy": texture_policy,
            "total_gpu_bytes": sum(int(group["gpu_bytes"]) for group in index_groups),
            "total_resident_charge_bytes": sum(
                int(group["resident_charge_bytes"]) for group in index_groups
            ),
            "total_source_rgba_bytes": sum(
                int(group["source_rgba_bytes"]) for group in index_groups
            ),
            "unity": {"revision": UNITY_REVISION, "version": UNITY_VERSION},
            "vanilla_omitted_groups": [],
        }
        index_asset = "Assets/Generated/index.v2.template.json"
        index_path = project.joinpath(*index_asset.split("/"))
        index_payload = _write_canonical_json(index_path, index_document)
        if len(index_payload) > MAX_INDEX_BYTES:
            raise UnityAssetBundleError("V2 index template exceeds its 4-MiB bound")
        _write_asset_meta(project, index_asset, "text")
        bundle_inputs.sort(key=lambda item: str(item["name"]))
        texture_inputs.sort(key=lambda item: str(item["asset_path"]))
        texture_contract_bindings = [
            {"id": contract_id, "texture_contract": texture_contract_by_id[contract_id]}
            for contract_id in sorted(texture_contract_by_id)
        ]
        build_input_document = {
            "backend_kind": BC7_BACKEND_KIND,
            "build_id": build_id,
            "build_options": list(BUILD_OPTIONS),
            "build_target": BUILD_TARGET,
            "bundles": bundle_inputs,
            "editor_script_sha256": editor_digest,
            "editor_texture_compression_override": "NoOverride",
            "encoder_id": BC7_ENCODER_ID,
            "index_output_relative_path": _INDEX_OUTPUT_RELATIVE_PATH,
            "index_template_asset_path": index_asset,
            "max_page_dimension": MAX_PAGE_DIMENSION,
            "output_relative_path": _OUTPUT_RELATIVE_PATH,
            "packer_id": BC7_PACKER_ID,
            "quality_policy": quality_policy,
            "quality_report_output_relative_path": "../output/bc7-quality-report.v1.json",
            "schema": BC7_BUILD_INPUT_SCHEMA,
            "texture_contracts": texture_contract_bindings,
            "texture_policy": texture_policy,
            "textures": texture_inputs,
            "unity": {"revision": UNITY_REVISION, "version": UNITY_VERSION},
        }
        build_input_asset = "Assets/Generated/build-input.v2.json"
        build_input_path = project.joinpath(*build_input_asset.split("/"))
        _write_canonical_json(build_input_path, build_input_document)
        _write_asset_meta(project, build_input_asset, "text")
        try:
            os.replace(staging, final_root)
        except OSError as exc:
            raise UnityAssetBundleError(
                f"Could not publish prepared V2 Unity project: {final_root}"
            ) from exc
    except Exception:
        if staging.exists():
            _safe_cleanup_staging(staging, container)
        raise

    prepared = PreparedUnityProject(
        workspace_root=root,
        build_root=final_root,
        project_path=final_root / "project",
        index_template_path=final_root / "project" / "Assets" / "Generated" / "index.v2.template.json",
        index_path=final_root / "output" / "Runtime" / "AssetBundles" / "index.json",
        build_input_path=final_root / "project" / "Assets" / "Generated" / "build-input.v2.json",
        output_path=final_root / "output" / "Runtime" / "AssetBundles" / "win64",
        report_path=final_root / "output" / "build-report.json",
        log_path=final_root / "output" / "unity-editor.log",
        build_id=build_id,
        group_count=len(preflight.plans),
        omitted_group_count=0,
        page_count=total_pages,
        pipeline_version=2,
        unity_report_path=final_root / "output" / "unity-build-report.v2.json",
        quality_report_path=final_root / "output" / "bc7-quality-report.v1.json",
        quality_policy_id=quality_policy_id,
        quality_policy_sha256=quality_policy_sha256,
        quality_mode=quality_mode,
        texture_policy_id=texture_policy_id,
        quality_acceptance_envelope=acceptance_envelope,
    )
    validate_prepared_project_v2(prepared)
    return prepared


def _reject_duplicate_pairs(pairs: Sequence[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise UnityAssetBundleError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _read_json_bytes(
    path: Path,
    *,
    canonical: bool,
    maximum_bytes: int | None = None,
) -> tuple[bytes, dict[str, object]]:
    try:
        if maximum_bytes is not None:
            size = path.stat().st_size
            if size < 1 or size > maximum_bytes:
                raise UnityAssetBundleError(
                    f"JSON file size is outside 1..{maximum_bytes}: {path}"
                )
        payload = path.read_bytes()
    except OSError as exc:
        raise UnityAssetBundleError(f"Could not read JSON file: {path}") from exc
    if payload.startswith(b"\xef\xbb\xbf"):
        raise UnityAssetBundleError(f"JSON file must be BOM-free UTF-8: {path}")
    try:
        text = payload.decode("utf-8", errors="strict")
        value = json.loads(text, object_pairs_hook=_reject_duplicate_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UnityAssetBundleError(f"Invalid strict JSON file: {path}") from exc
    if not isinstance(value, dict):
        raise UnityAssetBundleError(f"JSON root must be an object: {path}")
    if canonical and payload != _canonical_json_bytes(value, final_lf=True):
        raise UnityAssetBundleError(f"JSON file is not canonical UTF-8/LF: {path}")
    return payload, value


def _canonical_json_object_from_bytes(
    payload: bytes,
    *,
    label: str,
    maximum_bytes: int,
) -> dict[str, object]:
    if not 1 <= len(payload) <= maximum_bytes or payload.startswith(b"\xef\xbb\xbf"):
        raise UnityAssetBundleError(f"{label} is empty, oversized, or BOM-prefixed")
    try:
        value = json.loads(
            payload.decode("utf-8", errors="strict"),
            object_pairs_hook=_reject_duplicate_pairs,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UnityAssetBundleError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict) or payload != _canonical_json_bytes(value, final_lf=True):
        raise UnityAssetBundleError(f"{label} is not canonical JSON")
    return value


def _require_exact_keys(
    value: Mapping[str, object], expected: set[str], label: str
) -> None:
    actual = set(value)
    if actual != expected:
        raise UnityAssetBundleError(
            f"Invalid {label} keys: missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )


def validate_prepared_project(prepared: PreparedUnityProject) -> None:
    if not isinstance(prepared, PreparedUnityProject):
        raise UnityAssetBundleError("prepared must be a PreparedUnityProject")
    project = prepared.project_path.resolve(strict=True)
    work = (prepared.workspace_root / "work").resolve(strict=True)
    if not project.is_relative_to(work):
        raise UnityAssetBundleError("Prepared Unity project escaped workspace work/")
    expected_project = (
        work
        / _WORK_CONTAINER_DIRECTORY
        / prepared.build_id[:_BUILD_DIRECTORY_ID_CHARACTERS]
        / "project"
    )
    if project != expected_project:
        raise UnityAssetBundleError(
            f"Prepared Unity project path changed: {project} != {expected_project}"
        )
    version_bytes = (project / "ProjectSettings" / "ProjectVersion.txt").read_bytes()
    expected_version = (
        f"m_EditorVersion: {UNITY_VERSION}\n"
        f"m_EditorVersionWithRevision: {UNITY_FULL_VERSION}\n"
    ).encode("utf-8")
    if version_bytes != expected_version:
        raise UnityAssetBundleError("Prepared Unity version/revision drifted")

    _input_payload, build_input = _read_json_bytes(
        prepared.build_input_path, canonical=True
    )
    expected_input_keys = {
        "schema",
        "build_id",
        "unity",
        "build_target",
        "build_options",
        "max_page_dimension",
        "output_relative_path",
        "index_template_asset_path",
        "index_output_relative_path",
        "editor_script_sha256",
        "bundles",
        "textures",
    }
    _require_exact_keys(build_input, expected_input_keys, "build input")
    if (
        build_input["schema"] != BUILD_INPUT_SCHEMA
        or build_input["build_id"] != prepared.build_id
        or build_input["unity"]
        != {"version": UNITY_VERSION, "revision": UNITY_REVISION}
        or build_input["build_target"] != BUILD_TARGET
        or build_input["build_options"] != list(BUILD_OPTIONS)
        or build_input["max_page_dimension"] != MAX_PAGE_DIMENSION
        or build_input["output_relative_path"] != _OUTPUT_RELATIVE_PATH
        or build_input["index_template_asset_path"]
        != "Assets/Generated/index.template.json"
        or build_input["index_output_relative_path"] != _INDEX_OUTPUT_RELATIVE_PATH
    ):
        raise UnityAssetBundleError("Prepared Unity build input constants drifted")
    editor_path = project.joinpath(*_EDITOR_ASSET_PATH.split("/"))
    if _sha256_file(editor_path) != build_input["editor_script_sha256"]:
        raise UnityAssetBundleError("Prepared Unity Editor source hash drifted")

    _index_payload, index = _read_json_bytes(
        prepared.index_template_path,
        canonical=True,
        maximum_bytes=MAX_INDEX_BYTES,
    )
    if len(_index_payload) > MAX_INDEX_BYTES:
        raise UnityAssetBundleError(
            f"Prepared index template exceeds {MAX_INDEX_BYTES} bytes"
        )
    _require_exact_keys(
        index,
        {
            "schema",
            "build_id",
            "unity",
            "build_target",
            "max_page_dimension",
            "groups",
            "vanilla_omitted_groups",
        },
        "bundle index template",
    )
    if (
        index["schema"] != INDEX_TEMPLATE_SCHEMA
        or index["build_id"] != prepared.build_id
        or index["unity"]
        != {"version": UNITY_VERSION, "revision": UNITY_REVISION}
        or index["build_target"] != BUILD_TARGET
        or index["max_page_dimension"] != MAX_PAGE_DIMENSION
    ):
        raise UnityAssetBundleError("Prepared asset-bundle index template drifted")
    raw_groups = index["groups"]
    raw_omitted = index["vanilla_omitted_groups"]
    if (
        not isinstance(raw_groups, list)
        or not 0 <= len(raw_groups) <= MAX_GROUPS
        or len(raw_groups) != prepared.group_count
        or not isinstance(raw_omitted, list)
        or len(raw_omitted) != prepared.omitted_group_count
        or not 1 <= len(raw_groups) + len(raw_omitted) <= MAX_GROUPS
    ):
        raise UnityAssetBundleError("Prepared asset-bundle group count drifted")
    selected_names: set[str] = set()
    selected_ids: set[int] = set()
    omitted_names: list[str] = []
    for position, omitted in enumerate(raw_omitted):
        if not isinstance(omitted, dict):
            raise UnityAssetBundleError("Omitted group record is not an object")
        _require_exact_keys(
            omitted,
            {
                "group",
                "gm_id",
                "reason",
                "array_size",
                "frame_count",
                "names_sha256",
                "frames_sha256",
            },
            f"vanilla_omitted_groups[{position}]",
        )
        omitted_name = _require_nfc_string(
            omitted["group"], f"vanilla_omitted_groups[{position}].group"
        )
        group_slug(omitted_name)
        omitted_id = omitted["gm_id"]
        if (
            omitted_name.casefold() in selected_names
            or isinstance(omitted_id, bool)
            or not isinstance(omitted_id, int)
            or not 0 <= omitted_id < MAX_GROUPS
            or omitted_id in selected_ids
            or omitted["reason"] not in VANILLA_OMISSION_REASONS
            or isinstance(omitted["array_size"], bool)
            or not isinstance(omitted["array_size"], int)
            or not 1 <= omitted["array_size"] <= MAX_PREFLIGHT_ARRAY_SIZE
            or isinstance(omitted["frame_count"], bool)
            or not isinstance(omitted["frame_count"], int)
            or not 1 <= omitted["frame_count"] <= MAX_PREFLIGHT_FRAMES_PER_GROUP
            or not isinstance(omitted["names_sha256"], str)
            or _SHA256_RE.fullmatch(omitted["names_sha256"]) is None
            or not isinstance(omitted["frames_sha256"], str)
            or _SHA256_RE.fullmatch(omitted["frames_sha256"]) is None
        ):
            raise UnityAssetBundleError(
                f"Invalid omitted group binding: {omitted_name}"
            )
        selected_names.add(omitted_name.casefold())
        selected_ids.add(omitted_id)
        omitted_names.append(omitted_name)
    if omitted_names != sorted(omitted_names):
        raise UnityAssetBundleError(
            "vanilla_omitted_groups must be sorted by group ordinal"
        )
    page_total = 0
    expected_bundle_assets: dict[str, list[dict[str, str]]] = {}
    expected_texture_inputs: dict[str, dict[str, object]] = {}
    for group in raw_groups:
        if not isinstance(group, dict):
            raise UnityAssetBundleError("Index group record is not an object")
        _require_exact_keys(
            group,
            {
                "group",
                "slug",
                "gm_id",
                "dash_format",
                "array_size",
                "lifetime",
                "bundle",
                "atlas_asset_path",
                "atlas_address",
                "atlas_sha256",
                "mask_policy",
                "material_binding",
                "page_count",
                "frame_count",
                "names_sha256",
                "frames_sha256",
                "raw_rgba_bytes",
                "resident_charge_bytes",
                "pages",
            },
            "index template group",
        )
        group_name = _require_nfc_string(group["group"], "index group.group")
        gm_id = group["gm_id"]
        array_size = group["array_size"]
        page_count = group["page_count"]
        frame_count = group["frame_count"]
        if (
            group_name.casefold() in selected_names
            or gm_id in selected_ids
            or
            isinstance(gm_id, bool)
            or not isinstance(gm_id, int)
            or not 0 <= gm_id < MAX_GROUPS
            or isinstance(array_size, bool)
            or not isinstance(array_size, int)
            or not 1 <= array_size <= MAX_FRAMES_PER_GROUP
            or isinstance(page_count, bool)
            or not isinstance(page_count, int)
            or not 1 <= page_count <= MAX_PAGES_PER_GROUP
            or isinstance(frame_count, bool)
            or not isinstance(frame_count, int)
            or not 1 <= frame_count <= MAX_FRAMES_PER_GROUP
        ):
            raise UnityAssetBundleError(
                f"Prepared group exceeds the v1 parser bounds: {group_name}"
            )
        selected_names.add(group_name.casefold())
        selected_ids.add(gm_id)
        try:
            expected_binding = expected_material_binding(
                group_name, str(group["mask_policy"])
            )
        except ValueError as exc:
            raise UnityAssetBundleError(
                f"Prepared mask/material contract drifted: {group_name}"
            ) from exc
        if group["material_binding"] != expected_binding:
            raise UnityAssetBundleError(
                f"Prepared material binding drifted: {group_name}"
            )
        if (
            expected_binding == GROUP_MASK_MATERIAL_BINDING
            and page_count != 1
        ):
            raise UnityAssetBundleError(
                f"Prepared group-mask group is not single-page: {group_name}"
            )
        atlas_asset = _safe_relative_path(
            str(group["atlas_asset_path"]), "atlas_asset_path"
        )
        atlas_path = project.joinpath(*atlas_asset.split("/"))
        atlas_payload, atlas = _read_json_bytes(
            atlas_path, canonical=True, maximum_bytes=MAX_ATLAS_BYTES
        )
        if len(atlas_payload) > MAX_ATLAS_BYTES:
            raise UnityAssetBundleError(
                f"Prepared atlas.v2 exceeds {MAX_ATLAS_BYTES} bytes: {group_name}"
            )
        if _sha256_bytes(atlas_payload) != group["atlas_sha256"]:
            raise UnityAssetBundleError(
                f"Atlas document hash drifted: {group['group']}"
            )
        if (
            atlas.get("schema") != ATLAS_SCHEMA
            or atlas.get("group") != group["group"]
            or atlas.get("slug") != group["slug"]
            or atlas.get("bundle") != group["bundle"]
            or atlas.get("mask_policy") != group["mask_policy"]
            or atlas.get("material_binding") != group["material_binding"]
        ):
            raise UnityAssetBundleError(
                f"Index/atlas identity drifted: {group['group']}"
            )
        if (
            group["slug"] != group_slug(group_name)
            or group["bundle"] != f"sede.gm.{group['slug']}.v2"
            or not isinstance(group["dash_format"], bool)
            or group["lifetime"] != "map"
        ):
            raise UnityAssetBundleError(
                f"Index loader identity drifted: {group['group']}"
            )
        pages = atlas.get("pages")
        frames = atlas.get("frames")
        if (
            not isinstance(pages, list)
            or len(pages) != group["page_count"]
            or not isinstance(frames, list)
            or len(frames) != group["frame_count"]
        ):
            raise UnityAssetBundleError(
                f"Index/atlas counts drifted: {group['group']}"
            )
        if (
            atlas.get("frames_sha256") != group["frames_sha256"]
            or group["frames_sha256"]
            != _sha256_bytes(_canonical_json_bytes(frames, final_lf=False))
            or group["names_sha256"]
            != _sha256_bytes(
                _canonical_json_bytes(
                    [frame.get("name") for frame in frames if isinstance(frame, dict)],
                    final_lf=False,
                )
            )
        ):
            raise UnityAssetBundleError(
                f"Index/atlas frame digests drifted: {group['group']}"
            )
        summaries = group["pages"]
        if not isinstance(summaries, list) or len(summaries) != len(pages):
            raise UnityAssetBundleError(
                f"Index page summaries drifted: {group['group']}"
            )
        bundle_assets: list[dict[str, str]] = [
            {
                "asset_path": str(group["atlas_asset_path"]),
                "address": str(group["atlas_address"]),
            }
        ]
        raw_rgba_bytes = 0
        for page_position, (page, summary) in enumerate(
            zip(pages, summaries, strict=True)
        ):
            if not isinstance(page, dict) or not isinstance(summary, dict):
                raise UnityAssetBundleError("Atlas/index page is not an object")
            _require_exact_keys(
                page, {"id", "width", "height", "main", "mask"}, "atlas page"
            )
            _require_exact_keys(
                summary,
                {
                    "id",
                    "width",
                    "height",
                    "main_address",
                    "main_rgba_sha256",
                    "mask_address",
                    "mask_rgba_sha256",
                },
                "index page summary",
            )
            if (
                page["id"] != page_position
                or page["width"] != summary["width"]
                or page["height"] != summary["height"]
                or summary["id"] != page_position
                or isinstance(page["width"], bool)
                or not isinstance(page["width"], int)
                or isinstance(page["height"], bool)
                or not isinstance(page["height"], int)
                or not 256 <= page["width"] <= MAX_PAGE_DIMENSION
                or not 256 <= page["height"] <= MAX_PAGE_DIMENSION
                or page["width"] & (page["width"] - 1)
                or page["height"] & (page["height"] - 1)
            ):
                raise UnityAssetBundleError(
                    f"Atlas page geometry drifted: {group['group']}[{page_position}]"
                )
            main = page["main"]
            mask = page["mask"]
            if not isinstance(main, dict):
                raise UnityAssetBundleError("Atlas main page texture is not an object")
            _require_exact_keys(
                main,
                {"asset_path", "address", "png_sha256", "rgba_sha256"},
                "atlas main page texture",
            )
            if (
                main["address"] != summary["main_address"]
                or main["rgba_sha256"] != summary["main_rgba_sha256"]
            ):
                raise UnityAssetBundleError("Index main page summary drifted")
            bundle_assets.append(
                {"asset_path": str(main["asset_path"]), "address": str(main["address"])}
            )
            expected_texture_inputs[str(main["asset_path"])] = {
                "asset_path": main["asset_path"],
                "width": page["width"],
                "height": page["height"],
                "png_sha256": main["png_sha256"],
            }
            planes = 1
            if mask is None:
                if (
                    group["mask_policy"] != "forbidden"
                    or summary["mask_address"] is not None
                    or summary["mask_rgba_sha256"] is not None
                ):
                    raise UnityAssetBundleError("Forbidden-mask page summary drifted")
            else:
                if not isinstance(mask, dict) or group["mask_policy"] != "required":
                    raise UnityAssetBundleError("Required-mask page summary drifted")
                _require_exact_keys(
                    mask,
                    {"asset_path", "address", "png_sha256", "rgba_sha256"},
                    "atlas mask page texture",
                )
                if (
                    mask["address"] != summary["mask_address"]
                    or mask["rgba_sha256"] != summary["mask_rgba_sha256"]
                ):
                    raise UnityAssetBundleError("Index mask page summary drifted")
                bundle_assets.append(
                    {
                        "asset_path": str(mask["asset_path"]),
                        "address": str(mask["address"]),
                    }
                )
                expected_texture_inputs[str(mask["asset_path"])] = {
                    "asset_path": mask["asset_path"],
                    "width": page["width"],
                    "height": page["height"],
                    "png_sha256": mask["png_sha256"],
                }
                planes = 2
            raw_rgba_bytes += page["width"] * page["height"] * 4 * planes
        if (
            group["raw_rgba_bytes"] != raw_rgba_bytes
            or group["resident_charge_bytes"]
            != _resident_charge_bytes(raw_rgba_bytes)
        ):
            raise UnityAssetBundleError(
                f"Index resident accounting drifted: {group['group']}"
            )
        bundle_assets.sort(key=lambda asset: asset["address"])
        expected_bundle_assets[str(group["bundle"])] = bundle_assets
        page_total += len(pages)
    if page_total != prepared.page_count:
        raise UnityAssetBundleError("Prepared asset-bundle page count drifted")

    raw_textures = build_input["textures"]
    if (
        not isinstance(raw_textures, list)
        or len(raw_textures) > MAX_GROUPS * MAX_PAGES_PER_GROUP * 2
        or (bool(raw_groups) != bool(raw_textures))
    ):
        raise UnityAssetBundleError("Prepared build input has no textures")
    if raw_textures != [
        expected_texture_inputs[path] for path in sorted(expected_texture_inputs)
    ]:
        raise UnityAssetBundleError("Prepared texture input order/set drifted")
    for texture in raw_textures:
        if not isinstance(texture, dict):
            raise UnityAssetBundleError("Texture input is not an object")
        _require_exact_keys(
            texture,
            {"asset_path", "width", "height", "png_sha256"},
            "texture input",
        )
        asset_path = _safe_relative_path(
            str(texture["asset_path"]), "texture asset_path"
        )
        path = project.joinpath(*asset_path.split("/"))
        if _sha256_file(path) != texture["png_sha256"]:
            raise UnityAssetBundleError(f"Prepared texture hash drifted: {asset_path}")
        with Image.open(path) as image:
            image.load()
            if (
                image.mode != "RGBA"
                or image.size != (texture["width"], texture["height"])
            ):
                raise UnityAssetBundleError(
                    f"Prepared texture geometry/format drifted: {asset_path}"
                )

    raw_bundles = build_input["bundles"]
    if (
        not isinstance(raw_bundles, list)
        or not 0 <= len(raw_bundles) <= MAX_GROUPS
        or len(raw_bundles) != len(raw_groups)
    ):
        raise UnityAssetBundleError("Prepared build input bundles must be a list")
    if [bundle.get("name") for bundle in raw_bundles if isinstance(bundle, dict)] != sorted(
        expected_bundle_assets
    ):
        raise UnityAssetBundleError("Prepared build input bundle order/set drifted")
    for bundle in raw_bundles:
        if not isinstance(bundle, dict):
            raise UnityAssetBundleError("Prepared bundle input is not an object")
        _require_exact_keys(bundle, {"name", "assets"}, "bundle input")
        if bundle["assets"] != expected_bundle_assets.get(str(bundle["name"])):
            raise UnityAssetBundleError(
                f"Prepared bundle assets drifted: {bundle['name']}"
            )


def validate_prepared_project_v2(prepared: PreparedUnityProject) -> None:
    """Fail closed over every generated V2 input before Unity is launched."""

    if not isinstance(prepared, PreparedUnityProject) or prepared.pipeline_version != 2:
        raise UnityAssetBundleError("prepared is not a V2 Unity project")
    project = prepared.project_path.resolve(strict=True)
    work = (prepared.workspace_root / "work").resolve(strict=True)
    expected_project = (
        work
        / _WORK_CONTAINER_DIRECTORY
        / prepared.build_id[:_BUILD_DIRECTORY_ID_CHARACTERS]
        / "project"
    )
    if project != expected_project or not project.is_relative_to(work):
        raise UnityAssetBundleError("Prepared V2 project escaped its exact work path")
    version = (project / "ProjectSettings" / "ProjectVersion.txt").read_bytes()
    if version != (
        f"m_EditorVersion: {UNITY_VERSION}\n"
        f"m_EditorVersionWithRevision: {UNITY_FULL_VERSION}\n"
    ).encode("utf-8"):
        raise UnityAssetBundleError("Prepared V2 Unity identity drifted")

    input_payload, build_input = _read_json_bytes(
        prepared.build_input_path, canonical=True, maximum_bytes=MAX_REPORT_BYTES
    )
    del input_payload
    _require_exact_keys(
        build_input,
        {
            "backend_kind",
            "build_id",
            "build_options",
            "build_target",
            "bundles",
            "editor_script_sha256",
            "editor_texture_compression_override",
            "encoder_id",
            "index_output_relative_path",
            "index_template_asset_path",
            "max_page_dimension",
            "output_relative_path",
            "packer_id",
            "quality_policy",
            "quality_report_output_relative_path",
            "schema",
            "texture_contracts",
            "texture_policy",
            "textures",
            "unity",
        },
        "V2 build input",
    )
    if (
        build_input["backend_kind"] != BC7_BACKEND_KIND
        or build_input["schema"] != BC7_BUILD_INPUT_SCHEMA
        or build_input["build_id"] != prepared.build_id
        or build_input["build_options"] != list(BUILD_OPTIONS)
        or build_input["build_target"] != BUILD_TARGET
        or build_input["unity"]
        != {"revision": UNITY_REVISION, "version": UNITY_VERSION}
        or build_input["editor_texture_compression_override"] != "NoOverride"
        or build_input["encoder_id"] != BC7_ENCODER_ID
        or build_input["packer_id"] != BC7_PACKER_ID
        or build_input["max_page_dimension"] != MAX_PAGE_DIMENSION
        or build_input["output_relative_path"] != _OUTPUT_RELATIVE_PATH
        or build_input["index_output_relative_path"] != _INDEX_OUTPUT_RELATIVE_PATH
        or build_input["index_template_asset_path"]
        != "Assets/Generated/index.v2.template.json"
        or build_input["quality_report_output_relative_path"]
        != "../output/bc7-quality-report.v1.json"
    ):
        raise UnityAssetBundleError("Prepared V2 build constants drifted")
    editor_path = project.joinpath(*_EDITOR_ASSET_PATH.split("/"))
    if _sha256_file(editor_path) != build_input["editor_script_sha256"]:
        raise UnityAssetBundleError("Prepared V2 editor source hash drifted")

    quality = build_input["quality_policy"]
    texture_policy = build_input["texture_policy"]
    if not isinstance(quality, dict) or set(quality) != {
        "id",
        "sha256",
        "state",
        "verifier_id",
    }:
        raise UnityAssetBundleError("Prepared V2 quality policy is malformed")
    if (
        quality["id"] != prepared.quality_policy_id
        or quality["sha256"] != prepared.quality_policy_sha256
        or quality["state"] != prepared.quality_mode
        or quality["verifier_id"] != BC7_VERIFIER_ID
    ):
        raise UnityAssetBundleError("Prepared V2 quality policy binding drifted")
    if not isinstance(texture_policy, dict) or set(texture_policy) != {
        "id",
        "main_format",
        "mask_format",
    }:
        raise UnityAssetBundleError("Prepared V2 texture policy is malformed")
    main_format, mask_format = _v2_texture_formats(str(texture_policy["id"]))
    if (
        texture_policy
        != {
            "id": prepared.texture_policy_id,
            "main_format": main_format,
            "mask_format": mask_format,
        }
    ):
        raise UnityAssetBundleError("Prepared V2 texture policy binding drifted")

    raw_contracts = build_input["texture_contracts"]
    if not isinstance(raw_contracts, list):
        raise UnityAssetBundleError("V2 texture_contracts must be a list")
    contract_by_id: dict[str, dict[str, object]] = {}
    contract_ids: list[str] = []
    contract_pattern = re.compile(
        r"(main|mask)-(bc7|rgba32)-(point|bilinear)-v1\Z"
    )
    for raw in raw_contracts:
        if not isinstance(raw, dict):
            raise UnityAssetBundleError("V2 texture contract is not an object")
        _require_exact_keys(raw, {"id", "texture_contract"}, "V2 texture contract")
        contract_id = str(raw["id"])
        match = contract_pattern.fullmatch(contract_id)
        if match is None or contract_id in contract_by_id:
            raise UnityAssetBundleError(f"Invalid V2 texture contract id: {contract_id}")
        plane, format_token, filter_token = match.groups()
        format_name = "BC7" if format_token == "bc7" else "RGBA32"
        filter_mode = "Point" if filter_token == "point" else "Bilinear"
        if plane == "main" and format_name != "BC7":
            raise UnityAssetBundleError("V2 main contract is not BC7")
        expected_contract = _bc7_texture_contract(
            filter_mode, format_name=format_name
        )
        if raw["texture_contract"] != expected_contract:
            raise UnityAssetBundleError(
                f"V2 texture contract values drifted: {contract_id}"
            )
        contract_by_id[contract_id] = expected_contract
        contract_ids.append(contract_id)
    if contract_ids != sorted(contract_ids):
        raise UnityAssetBundleError("V2 texture contracts are not id-sorted")

    raw_textures = build_input["textures"]
    if (
        not isinstance(raw_textures, list)
        or not raw_textures
        or len(raw_textures) > MAX_GROUPS * MAX_PAGES_PER_GROUP * 2
    ):
        raise UnityAssetBundleError("Prepared V2 textures are missing/oversized")
    texture_paths: list[str] = []
    used_contract_ids: set[str] = set()
    texture_by_path: dict[str, dict[str, object]] = {}
    for raw in raw_textures:
        if not isinstance(raw, dict):
            raise UnityAssetBundleError("Prepared V2 texture is not an object")
        _require_exact_keys(
            raw,
            {
                "asset_path",
                "gpu_bytes",
                "height",
                "plane",
                "source_png_sha256",
                "source_rgba_bytes",
                "source_rgba_sha256",
                "texture_contract_id",
                "width",
            },
            "V2 texture input",
        )
        asset_path = _safe_relative_path(str(raw["asset_path"]), "V2 texture asset_path")
        contract_id = str(raw["texture_contract_id"])
        contract = contract_by_id.get(contract_id)
        if contract is None:
            raise UnityAssetBundleError(
                f"V2 texture references an unknown contract: {asset_path}"
            )
        used_contract_ids.add(contract_id)
        plane = raw["plane"]
        width = raw["width"]
        height = raw["height"]
        if (
            plane not in {"main", "mask"}
            or not contract_id.startswith(f"{plane}-")
            or isinstance(width, bool)
            or not isinstance(width, int)
            or isinstance(height, bool)
            or not isinstance(height, int)
            or not 256 <= width <= MAX_PAGE_DIMENSION
            or not 256 <= height <= MAX_PAGE_DIMENSION
            or width & (width - 1)
            or height & (height - 1)
            or raw["gpu_bytes"]
            != _texture_gpu_bytes(width, height, str(contract["format"]))
            or raw["source_rgba_bytes"] != width * height * 4
            or _SHA256_RE.fullmatch(str(raw["source_png_sha256"])) is None
            or _SHA256_RE.fullmatch(str(raw["source_rgba_sha256"])) is None
        ):
            raise UnityAssetBundleError(f"Prepared V2 texture fields drifted: {asset_path}")
        path = project.joinpath(*asset_path.split("/"))
        if _sha256_file(path) != raw["source_png_sha256"]:
            raise UnityAssetBundleError(f"Prepared V2 PNG drifted: {asset_path}")
        with Image.open(path) as image:
            image.load()
            if (
                image.mode != "RGBA"
                or image.size != (width, height)
                or _rgba_sha256_image(image) != raw["source_rgba_sha256"]
            ):
                raise UnityAssetBundleError(
                    f"Prepared V2 source pixels drifted: {asset_path}"
                )
        filter_mode = str(contract["filter_mode"])
        meta = path.with_name(path.name + ".meta").read_bytes()
        if meta != _texture_meta_v2(
            stable_unity_guid(asset_path),
            filter_mode=filter_mode,
            format_name=str(contract["format"]),
        ):
            raise UnityAssetBundleError(
                f"Prepared V2 TextureImporter meta drifted: {asset_path}"
            )
        if asset_path in texture_by_path:
            raise UnityAssetBundleError(f"Duplicate V2 texture path: {asset_path}")
        texture_paths.append(asset_path)
        texture_by_path[asset_path] = raw
    if texture_paths != sorted(texture_paths) or used_contract_ids != set(contract_by_id):
        raise UnityAssetBundleError(
            "V2 texture inputs/contracts are unsorted, unused, or incomplete"
        )

    _index_payload, index = _read_json_bytes(
        prepared.index_template_path, canonical=True, maximum_bytes=MAX_INDEX_BYTES
    )
    _require_exact_keys(
        index,
        {
            "backend_kind",
            "build_id",
            "build_target",
            "encoder_id",
            "groups",
            "max_page_dimension",
            "packer_id",
            "quality_policy",
            "quality_report_sha256",
            "schema",
            "texture_policy",
            "total_gpu_bytes",
            "total_resident_charge_bytes",
            "total_source_rgba_bytes",
            "unity",
            "vanilla_omitted_groups",
        },
        "V2 index template",
    )
    if (
        index["backend_kind"] != BC7_BACKEND_KIND
        or index["schema"] != BC7_INDEX_TEMPLATE_SCHEMA
        or index["build_id"] != prepared.build_id
        or index["build_target"] != BUILD_TARGET
        or index["encoder_id"] != BC7_ENCODER_ID
        or index["packer_id"] != BC7_PACKER_ID
        or index["max_page_dimension"] != MAX_PAGE_DIMENSION
        or index["quality_policy"] != quality
        or index["quality_report_sha256"] is not None
        or index["texture_policy"] != texture_policy
        or index["unity"] != {"revision": UNITY_REVISION, "version": UNITY_VERSION}
        or index["vanilla_omitted_groups"] != []
    ):
        raise UnityAssetBundleError("Prepared V2 index constants drifted")
    groups = index["groups"]
    if (
        not isinstance(groups, list)
        or len(groups) != prepared.group_count
        or [group.get("group") for group in groups if isinstance(group, dict)]
        != sorted(group.get("group") for group in groups if isinstance(group, dict))
    ):
        raise UnityAssetBundleError("Prepared V2 index group order/count drifted")

    expected_bundle_assets: dict[str, list[dict[str, str]]] = {}
    total_gpu = total_resident = total_source = page_count = 0
    group_keys = {
        "array_size", "atlas_address", "atlas_asset_path", "atlas_sha256",
        "bundle", "dash_format", "frame_count", "frames_sha256", "gm_id",
        "gpu_bytes", "group", "lifetime", "mask_policy", "material_binding",
        "names_sha256", "page_count", "pages", "resident_charge_bytes", "slug",
        "source_rgba_bytes",
    }
    atlas_root_keys = {
        "block_alignment_pixels", "bundle", "coordinate_system", "extrusion_mode",
        "frames", "frames_sha256", "group", "mask_policy", "material_binding",
        "max_page_dimension", "minimum_border_pixels", "pages", "schema", "slug",
        "texture_contracts",
    }
    for group in groups:
        if not isinstance(group, dict):
            raise UnityAssetBundleError("Prepared V2 index group is not an object")
        _require_exact_keys(group, group_keys, "V2 index group")
        slug = group_slug(str(group["group"]))
        bundle = str(group["bundle"])
        if (
            group["slug"] != slug
            or _BC7_BUNDLE_RE.fullmatch(bundle) is None
            or bundle != f"sede.gm.{slug}{BC7_BUNDLE_SUFFIX}"
            or group["lifetime"] != "map"
            or group["resident_charge_bytes"]
            != _bc7_group_resident_charge(int(group["gpu_bytes"]))
        ):
            raise UnityAssetBundleError(f"Prepared V2 group identity drifted: {slug}")
        atlas_asset = str(group["atlas_asset_path"])
        atlas_payload, atlas = _read_json_bytes(
            project.joinpath(*atlas_asset.split("/")),
            canonical=True,
            maximum_bytes=MAX_ATLAS_BYTES,
        )
        _require_exact_keys(atlas, atlas_root_keys, "atlas.v3")
        if (
            _sha256_bytes(atlas_payload) != group["atlas_sha256"]
            or atlas["schema"] != BC7_ATLAS_SCHEMA
            or atlas["group"] != group["group"]
            or atlas["slug"] != slug
            or atlas["bundle"] != bundle
            or atlas["coordinate_system"] != "unity_bottom_left"
            or atlas["extrusion_mode"] != "nearest_edge_full_rgba_v1"
            or atlas["block_alignment_pixels"] != 4
            or atlas["minimum_border_pixels"] != 1
            or atlas["max_page_dimension"] != MAX_PAGE_DIMENSION
            or atlas["frames_sha256"] != group["frames_sha256"]
        ):
            raise UnityAssetBundleError(f"Prepared atlas.v3 binding drifted: {slug}")
        frames = atlas["frames"]
        pages = atlas["pages"]
        if (
            not isinstance(frames, list)
            or len(frames) != group["frame_count"]
            or not isinstance(pages, list)
            or len(pages) != group["page_count"]
        ):
            raise UnityAssetBundleError(f"Prepared atlas.v3 counts drifted: {slug}")
        for frame in frames:
            if not isinstance(frame, dict):
                raise UnityAssetBundleError("atlas.v3 frame is not an object")
            _require_exact_keys(
                frame,
                {
                    "alt", "index", "main_source_rgba_sha256",
                    "mask_source_rgba_sha256", "name", "page",
                    "pixels_per_unit", "pivot", "rect", "storage_cell",
                },
                "atlas.v3 frame",
            )
            rect = frame["rect"]
            cell = frame["storage_cell"]
            if (
                not isinstance(rect, dict)
                or not isinstance(cell, dict)
                or set(rect) != {"height", "width", "x", "y"}
                or set(cell) != {"height", "width", "x", "y"}
                or any(int(cell[key]) % 4 for key in ("height", "width", "x", "y"))
                or rect["x"] != cell["x"] + 1
                or rect["y"]
                != cell["y"] + cell["height"] - rect["height"] - 1
                or rect["x"] + rect["width"] >= cell["x"] + cell["width"]
                or rect["y"] + rect["height"] >= cell["y"] + cell["height"]
            ):
                raise UnityAssetBundleError(
                    f"atlas.v3 frame cell is not BC7-isolated: {frame.get('name')}"
                )
        assets = [{"address": str(group["atlas_address"]), "asset_path": atlas_asset}]
        for page in pages:
            if not isinstance(page, dict) or set(page) != {"height", "id", "main", "mask", "width"}:
                raise UnityAssetBundleError("atlas.v3 page is malformed")
            for plane in ("main", "mask"):
                record = page[plane]
                if record is None:
                    if plane != "mask" or group["mask_policy"] != "forbidden":
                        raise UnityAssetBundleError("atlas.v3 plane is unexpectedly null")
                    continue
                if not isinstance(record, dict) or set(record) != {
                    "address", "asset_path", "format", "gpu_bytes",
                    "source_png_sha256", "source_rgba_bytes",
                    "source_rgba_sha256",
                }:
                    raise UnityAssetBundleError("atlas.v3 plane is malformed")
                texture = texture_by_path.get(str(record["asset_path"]))
                if (
                    texture is None
                    or texture["plane"] != plane
                    or texture["gpu_bytes"] != record["gpu_bytes"]
                    or texture["source_png_sha256"] != record["source_png_sha256"]
                    or texture["source_rgba_bytes"] != record["source_rgba_bytes"]
                    or texture["source_rgba_sha256"] != record["source_rgba_sha256"]
                ):
                    raise UnityAssetBundleError("atlas.v3 texture binding drifted")
                assets.append(
                    {"address": str(record["address"]), "asset_path": str(record["asset_path"])}
                )
        assets.sort(key=lambda item: item["address"])
        expected_bundle_assets[bundle] = assets
        total_gpu += int(group["gpu_bytes"])
        total_resident += int(group["resident_charge_bytes"])
        total_source += int(group["source_rgba_bytes"])
        page_count += int(group["page_count"])
    if (
        index["total_gpu_bytes"] != total_gpu
        or index["total_resident_charge_bytes"] != total_resident
        or index["total_source_rgba_bytes"] != total_source
        or page_count != prepared.page_count
    ):
        raise UnityAssetBundleError("Prepared V2 index totals drifted")

    bundles = build_input["bundles"]
    if not isinstance(bundles, list) or [bundle.get("name") for bundle in bundles if isinstance(bundle, dict)] != sorted(expected_bundle_assets):
        raise UnityAssetBundleError("Prepared V2 bundle order/set drifted")
    for bundle in bundles:
        if not isinstance(bundle, dict):
            raise UnityAssetBundleError("Prepared V2 bundle is not an object")
        _require_exact_keys(bundle, {"assets", "name"}, "V2 bundle input")
        if bundle["assets"] != expected_bundle_assets.get(str(bundle["name"])):
            raise UnityAssetBundleError(
                f"Prepared V2 bundle assets drifted: {bundle.get('name')}"
            )


def build_headless_command(
    prepared: PreparedUnityProject, editor_executable: Path
) -> tuple[str, ...]:
    if prepared.pipeline_version == 2:
        validate_prepared_project_v2(prepared)
    else:
        validate_prepared_project(prepared)
    editor = _resolved_input_file(editor_executable, "Unity Editor executable")
    report_path = (
        prepared.unity_report_path
        if prepared.pipeline_version == 2
        else prepared.report_path
    )
    if report_path is None:
        raise UnityAssetBundleError("Prepared Unity report path is missing")
    return (
        str(editor),
        "-batchmode",
        "-nographics",
        "-quit",
        "-noUpm",
        "-buildTarget",
        "Win64",
        "-job-worker-count",
        "1",
        "-projectPath",
        str(prepared.project_path),
        "-executeMethod",
        EDITOR_METHOD,
        "-sedeBuildInput",
        str(prepared.build_input_path),
        "-sedeBuildReport",
        str(report_path),
        "-logFile",
        str(prepared.log_path),
    )


def _report_error(report_path: Path) -> str | None:
    if not report_path.is_file():
        return None
    try:
        _payload, report = _read_json_bytes(report_path, canonical=True)
    except UnityAssetBundleError:
        return None
    error = report.get("error")
    return error if isinstance(error, str) and error else None


def _validate_final_index(
    prepared: PreparedUnityProject,
    artifacts: Sequence[BundleArtifact],
) -> str:
    template_payload, template = _read_json_bytes(
        prepared.index_template_path,
        canonical=True,
        maximum_bytes=MAX_INDEX_BYTES,
    )
    del template_payload
    index_payload, index = _read_json_bytes(
        prepared.index_path, canonical=True, maximum_bytes=MAX_INDEX_BYTES
    )
    root_keys = {
        "schema",
        "build_id",
        "unity",
        "build_target",
        "max_page_dimension",
        "groups",
        "vanilla_omitted_groups",
    }
    _require_exact_keys(index, root_keys, "external asset-bundle index")
    if index["schema"] != INDEX_SCHEMA:
        raise UnityAssetBundleError("External index schema drifted")
    for key in root_keys - {"schema", "groups"}:
        if index[key] != template[key]:
            raise UnityAssetBundleError(f"External index {key} drifted from template")
    template_groups = template["groups"]
    final_groups = index["groups"]
    if not isinstance(template_groups, list) or not isinstance(final_groups, list):
        raise UnityAssetBundleError("External index groups must be lists")
    if (
        not 0 <= len(final_groups) <= MAX_GROUPS
        or len(final_groups) != len(template_groups)
    ):
        raise UnityAssetBundleError("External index group count drifted")
    artifacts_by_name = {artifact.name: artifact for artifact in artifacts}
    artifact_keys = {
        "bundle_path",
        "bundle_size_bytes",
        "bundle_sha256",
        "bundle_crc32",
        "predicted_load_peak_bytes",
        "unity_hash128",
    }
    for position, (template_group, final_group) in enumerate(
        zip(template_groups, final_groups, strict=True)
    ):
        if not isinstance(template_group, dict) or not isinstance(final_group, dict):
            raise UnityAssetBundleError("External index group is not an object")
        _require_exact_keys(
            final_group,
            set(template_group) | artifact_keys,
            f"external index group[{position}]",
        )
        for key, value in template_group.items():
            if final_group[key] != value:
                raise UnityAssetBundleError(
                    f"External index group[{position}].{key} drifted from template"
                )
        bundle_name = template_group["bundle"]
        artifact = artifacts_by_name.get(bundle_name)
        if artifact is None:
            raise UnityAssetBundleError(
                f"External index references unreported bundle: {bundle_name}"
            )
        bundle_path = f"{_MOD_BUNDLE_DIRECTORY}/{artifact.name}"
        crc32 = final_group["bundle_crc32"]
        predicted_load_peak = final_group["predicted_load_peak_bytes"]
        expected_load_peak = _predicted_load_peak_bytes(
            int(template_group["resident_charge_bytes"]), artifact.size_bytes
        )
        if (
            final_group["bundle_path"] != bundle_path
            or final_group["bundle_size_bytes"] != artifact.size_bytes
            or final_group["bundle_sha256"] != artifact.sha256
            or final_group["unity_hash128"] != artifact.manifest_hash
            or not isinstance(crc32, str)
            or _CRC32_RE.fullmatch(crc32) is None
            or isinstance(predicted_load_peak, bool)
            or not isinstance(predicted_load_peak, int)
            or predicted_load_peak != expected_load_peak
        ):
            raise UnityAssetBundleError(
                f"External index artifact metadata drifted: {artifact.name}"
            )
        bundle_file = (prepared.build_root / "output").joinpath(
            *bundle_path.split("/")
        )
        if _crc32_file(bundle_file) != crc32:
            raise UnityAssetBundleError(
                f"External index CRC32 drifted: {artifact.name}"
            )
    if set(artifacts_by_name) != {
        group["bundle"] for group in template_groups if isinstance(group, dict)
    }:
        raise UnityAssetBundleError("External index/report bundle set drifted")
    expected_parent = (
        prepared.build_root / "output" / "Runtime" / "AssetBundles"
    ).resolve(strict=True)
    if prepared.index_path.resolve(strict=True).parent != expected_parent:
        raise UnityAssetBundleError("External index escaped Runtime/AssetBundles")
    return _sha256_bytes(index_payload)


def _validate_asset_bundle_payload(
    bundle_path: Path,
    group: Mapping[str, object],
) -> bytes:
    """Decode one built bundle and prove its serialized lossless contract."""

    try:
        import UnityPy
    except ImportError as exc:  # pragma: no cover - guarded by the assets extra
        raise UnityAssetBundleError(
            "UnityPy 1.25.3 is required for post-build bundle verification"
        ) from exc

    try:
        environment = UnityPy.load(str(bundle_path.resolve(strict=True)))
        readers = tuple(environment.objects)
    except Exception as exc:
        raise UnityAssetBundleError(
            f"Built AssetBundle could not be decoded: {bundle_path.name}"
        ) from exc
    by_path_id: dict[int, object] = {}
    bundle_readers: list[object] = []
    for reader in readers:
        path_id = getattr(reader, "path_id", None)
        if not isinstance(path_id, int) or path_id in by_path_id:
            raise UnityAssetBundleError(
                f"Built AssetBundle has invalid object ids: {bundle_path.name}"
            )
        by_path_id[path_id] = reader
        if getattr(getattr(reader, "type", None), "name", None) == "AssetBundle":
            bundle_readers.append(reader)
    if len(bundle_readers) != 1:
        raise UnityAssetBundleError(
            f"Built file does not contain exactly one AssetBundle object: {bundle_path.name}"
        )

    try:
        bundle_object = bundle_readers[0].read()
        container_pairs = tuple(bundle_object.m_Container)
        dependencies = tuple(bundle_object.m_Dependencies)
    except Exception as exc:
        raise UnityAssetBundleError(
            f"Built AssetBundle metadata could not be read: {bundle_path.name}"
        ) from exc
    if (
        getattr(bundle_object, "m_Name", None) != group["bundle"]
        or getattr(bundle_object, "m_AssetBundleName", None) != group["bundle"]
        or dependencies
        or bool(getattr(bundle_object, "m_IsStreamedSceneAssetBundle", True))
    ):
        raise UnityAssetBundleError(
            f"Built AssetBundle identity/dependencies drifted: {bundle_path.name}"
        )

    address_to_path_id: dict[str, int] = {}
    for pair in container_pairs:
        try:
            address = pair[0]
            path_id = pair[1].asset.m_PathID
        except Exception as exc:
            raise UnityAssetBundleError(
                f"Built AssetBundle container is malformed: {bundle_path.name}"
            ) from exc
        if (
            not isinstance(address, str)
            or not isinstance(path_id, int)
            or address in address_to_path_id
            or path_id not in by_path_id
        ):
            raise UnityAssetBundleError(
                f"Built AssetBundle address map is invalid: {bundle_path.name}"
            )
        address_to_path_id[address] = path_id

    raw_pages = group["pages"]
    if not isinstance(raw_pages, list):
        raise UnityAssetBundleError("External index pages are not a list")
    expected_addresses = {str(group["atlas_address"])}
    for page in raw_pages:
        if not isinstance(page, dict):
            raise UnityAssetBundleError("External index page is not an object")
        expected_addresses.add(str(page["main_address"]))
        if page["mask_address"] is not None:
            expected_addresses.add(str(page["mask_address"]))
    if set(address_to_path_id) != expected_addresses:
        raise UnityAssetBundleError(
            f"Built AssetBundle address set drifted: {bundle_path.name}"
        )
    if len(readers) != len(expected_addresses) + 1:
        raise UnityAssetBundleError(
            f"Built AssetBundle contains unaddressed serialized objects: {bundle_path.name}"
        )

    atlas_reader = by_path_id[address_to_path_id[str(group["atlas_address"])]]
    if getattr(getattr(atlas_reader, "type", None), "name", None) != "TextAsset":
        raise UnityAssetBundleError(
            f"Built atlas contract is not a TextAsset: {bundle_path.name}"
        )
    try:
        atlas_script = atlas_reader.read().m_Script
    except Exception as exc:
        raise UnityAssetBundleError(
            f"Built atlas TextAsset could not be read: {bundle_path.name}"
        ) from exc
    if not isinstance(atlas_script, str):
        raise UnityAssetBundleError(
            f"Built atlas TextAsset is not UTF-8 text: {bundle_path.name}"
        )
    atlas_payload = atlas_script.encode("utf-8", errors="strict")
    if _sha256_bytes(atlas_payload) != group["atlas_sha256"]:
        raise UnityAssetBundleError(
            f"Built atlas TextAsset bytes drifted: {bundle_path.name}"
        )
    try:
        atlas = parse_atlas_v2(
            atlas_payload,
            label=f"{group['group']} post-Unity atlas.v2",
        )
    except AssetStreamContractError as exc:
        raise UnityAssetBundleError(
            f"Built atlas TextAsset contract drifted: {bundle_path.name}"
        ) from exc
    if (
        atlas.group != group["group"]
        or atlas.slug != group["slug"]
        or atlas.bundle != group["bundle"]
        or atlas.padding_pixels != 1
        or len(atlas.pages) != len(raw_pages)
        or len(atlas.frames) != group["frame_count"]
    ):
        raise UnityAssetBundleError(
            f"Built atlas TextAsset identity/counts drifted: {bundle_path.name}"
        )

    for page in raw_pages:
        for plane in ("main", "mask"):
            image: Image.Image | None = None
            address = page[f"{plane}_address"]
            digest = page[f"{plane}_rgba_sha256"]
            if address is None:
                if digest is not None:
                    raise UnityAssetBundleError(
                        f"Built {plane} page digest exists without an address"
                    )
                continue
            reader = by_path_id[address_to_path_id[str(address)]]
            if getattr(getattr(reader, "type", None), "name", None) != "Texture2D":
                raise UnityAssetBundleError(
                    f"Built {plane} page is not a Texture2D: {bundle_path.name}"
                )
            try:
                texture = reader.read()
                settings = texture.m_TextureSettings
                image = texture.image
                if (
                    texture.m_Width != page["width"]
                    or texture.m_Height != page["height"]
                    or int(texture.m_TextureFormat) != 4
                    or texture.m_MipCount != 1
                    or bool(texture.m_IsReadable)
                    or settings.m_FilterMode != 0
                    or settings.m_Aniso != 0
                    or settings.m_WrapU != 1
                    or settings.m_WrapV != 1
                    or settings.m_WrapW != 1
                    or image.mode != "RGBA"
                    or image.size != (page["width"], page["height"])
                    or _rgba_sha256_image(image) != digest
                ):
                    raise UnityAssetBundleError(
                        f"Built {plane} Texture2D contract drifted: "
                        f"{group['group']} page={page['id']}"
                    )
                _verify_post_unity_frame_roundtrips(
                    image,
                    atlas.frames,
                    page_id=int(page["id"]),
                    plane=plane,
                    group_name=str(group["group"]),
                )
            except UnityAssetBundleError:
                raise
            except Exception as exc:
                raise UnityAssetBundleError(
                    f"Built {plane} Texture2D could not be decoded: "
                    f"{group['group']} page={page['id']}"
                ) from exc
            finally:
                if image is not None:
                    image.close()
    return atlas_payload


def _v2_group_field(
    group: GroupIndexRecordV2 | Mapping[str, object], key: str
) -> object:
    if isinstance(group, Mapping):
        if key not in group:
            raise UnityAssetBundleError(f"V2 group is missing {key!r}")
        return group[key]
    if not isinstance(group, GroupIndexRecordV2) or not hasattr(group, key):
        raise UnityAssetBundleError("V2 group has an unsupported representation")
    return getattr(group, key)


def _v2_page_field(page: object, key: str) -> object:
    if isinstance(page, Mapping):
        if key not in page:
            raise UnityAssetBundleError(f"V2 page is missing {key!r}")
        return page[key]
    if not hasattr(page, key):
        raise UnityAssetBundleError("V2 page has an unsupported representation")
    return getattr(page, key)


def validate_asset_bundle_payload_v2_external(
    bundle_path: Path,
    group: GroupIndexRecordV2 | Mapping[str, object],
) -> bytes:
    """Revalidate one finalized V2 bundle without source PNG dependencies.

    This installed-artifact verifier deliberately stops at the serialized
    atlas and Texture2D contract.  The build-time verifier below additionally
    compares every decoded frame with its prepared source and emits quality
    evidence; those source files are intentionally unavailable after staging.
    """

    try:
        import UnityPy
    except ImportError as exc:  # pragma: no cover - dependency pin guards this
        raise UnityAssetBundleError(
            "UnityPy 1.25.3 is required for V2 bundle verification"
        ) from exc
    try:
        environment = UnityPy.load(str(Path(bundle_path).resolve(strict=True)))
        readers = tuple(environment.objects)
    except Exception as exc:
        raise UnityAssetBundleError(
            f"Final V2 AssetBundle could not be decoded: {Path(bundle_path).name}"
        ) from exc

    by_path_id: dict[int, object] = {}
    bundle_readers: list[object] = []
    for reader in readers:
        path_id = getattr(reader, "path_id", None)
        if not isinstance(path_id, int) or path_id in by_path_id:
            raise UnityAssetBundleError(
                f"Final V2 AssetBundle has invalid object ids: {Path(bundle_path).name}"
            )
        by_path_id[path_id] = reader
        if getattr(getattr(reader, "type", None), "name", None) == "AssetBundle":
            bundle_readers.append(reader)
    if len(bundle_readers) != 1:
        raise UnityAssetBundleError(
            f"Final V2 file does not contain one AssetBundle: {Path(bundle_path).name}"
        )

    try:
        bundle_object = bundle_readers[0].read()
        container_pairs = tuple(bundle_object.m_Container)
        dependencies = tuple(bundle_object.m_Dependencies)
    except Exception as exc:
        raise UnityAssetBundleError(
            f"Final V2 AssetBundle metadata could not be read: {Path(bundle_path).name}"
        ) from exc
    bundle_name = str(_v2_group_field(group, "bundle"))
    if (
        getattr(bundle_object, "m_Name", None) != bundle_name
        or getattr(bundle_object, "m_AssetBundleName", None) != bundle_name
        or dependencies
        or bool(getattr(bundle_object, "m_IsStreamedSceneAssetBundle", True))
    ):
        raise UnityAssetBundleError(
            f"Final V2 AssetBundle identity/dependencies drifted: {Path(bundle_path).name}"
        )

    address_to_path_id: dict[str, int] = {}
    for pair in container_pairs:
        try:
            address = pair[0]
            path_id = pair[1].asset.m_PathID
        except Exception as exc:
            raise UnityAssetBundleError(
                f"Final V2 AssetBundle container is malformed: {Path(bundle_path).name}"
            ) from exc
        if (
            not isinstance(address, str)
            or not isinstance(path_id, int)
            or address in address_to_path_id
            or path_id not in by_path_id
        ):
            raise UnityAssetBundleError(
                f"Final V2 address map is invalid: {Path(bundle_path).name}"
            )
        address_to_path_id[address] = path_id

    atlas_address = str(_v2_group_field(group, "atlas_address"))
    atlas_reader = by_path_id.get(address_to_path_id.get(atlas_address, -1))
    if (
        atlas_reader is None
        or getattr(getattr(atlas_reader, "type", None), "name", None) != "TextAsset"
    ):
        raise UnityAssetBundleError("Final V2 atlas.v3 is not a TextAsset")
    try:
        atlas_script = atlas_reader.read().m_Script
        if not isinstance(atlas_script, str):
            raise TypeError("m_Script")
        atlas_payload = atlas_script.encode("utf-8", errors="strict")
    except Exception as exc:
        raise UnityAssetBundleError("Final V2 atlas.v3 text could not be read") from exc
    if _sha256_bytes(atlas_payload) != str(_v2_group_field(group, "atlas_sha256")):
        raise UnityAssetBundleError("Final V2 atlas.v3 bytes drifted")
    try:
        atlas = parse_atlas_v3(
            atlas_payload,
            label=f"{_v2_group_field(group, 'group')} installed atlas.v3",
        )
    except AssetStreamContractError as exc:
        raise UnityAssetBundleError("Final V2 atlas.v3 contract drifted") from exc
    if (
        atlas.group != _v2_group_field(group, "group")
        or atlas.slug != _v2_group_field(group, "slug")
        or atlas.bundle != bundle_name
        or len(atlas.pages) != _v2_group_field(group, "page_count")
        or len(atlas.frames) != _v2_group_field(group, "frame_count")
        or atlas.frames_sha256 != _v2_group_field(group, "frames_sha256")
    ):
        raise UnityAssetBundleError("Final V2 atlas.v3 identity/counts drifted")

    group_pages_raw = _v2_group_field(group, "pages")
    if not isinstance(group_pages_raw, Sequence) or isinstance(
        group_pages_raw, (str, bytes, bytearray)
    ):
        raise UnityAssetBundleError("Final V2 index pages are malformed")
    group_pages = tuple(group_pages_raw)
    if len(group_pages) != len(atlas.pages):
        raise UnityAssetBundleError("Final V2 page count drifted")
    expected_addresses = {atlas_address}
    texture_work: list[tuple[object, str, object, object]] = []
    for ordinal, (atlas_page, summary) in enumerate(zip(atlas.pages, group_pages)):
        if (
            atlas_page.id != _v2_page_field(summary, "id")
            or atlas_page.width != _v2_page_field(summary, "width")
            or atlas_page.height != _v2_page_field(summary, "height")
        ):
            raise UnityAssetBundleError(
                f"Final V2 page geometry drifted: page={ordinal}"
            )
        for plane in ("main", "mask"):
            texture_record = getattr(atlas_page, plane)
            contract = (
                atlas.main_texture_contract
                if plane == "main"
                else atlas.mask_texture_contract
            )
            summary_address = _v2_page_field(summary, f"{plane}_address")
            summary_format = _v2_page_field(summary, f"{plane}_format")
            summary_gpu = _v2_page_field(summary, f"{plane}_gpu_bytes")
            summary_source = _v2_page_field(
                summary, f"{plane}_source_rgba_sha256"
            )
            if texture_record is None:
                if any(
                    value is not None
                    for value in (
                        contract,
                        summary_address,
                        summary_format,
                        summary_gpu,
                        summary_source,
                    )
                ):
                    raise UnityAssetBundleError(
                        f"Final V2 absent {plane} page has metadata: page={ordinal}"
                    )
                continue
            if (
                contract is None
                or texture_record.address != summary_address
                or texture_record.format != summary_format
                or texture_record.gpu_bytes != summary_gpu
                or texture_record.source_rgba_sha256 != summary_source
            ):
                raise UnityAssetBundleError(
                    f"Final V2 {plane} page/index binding drifted: page={ordinal}"
                )
            expected_addresses.add(texture_record.address)
            texture_work.append((atlas_page, plane, texture_record, contract))
    if (
        set(address_to_path_id) != expected_addresses
        or len(readers) != len(expected_addresses) + 1
    ):
        raise UnityAssetBundleError(
            f"Final V2 AssetBundle address/object set drifted: {Path(bundle_path).name}"
        )

    for atlas_page, plane, record, contract in texture_work:
        reader = by_path_id[address_to_path_id[record.address]]
        if getattr(getattr(reader, "type", None), "name", None) != "Texture2D":
            raise UnityAssetBundleError(
                f"Final V2 {plane} page is not Texture2D: page={atlas_page.id}"
            )
        image: Image.Image | None = None
        try:
            texture = reader.read()
            settings = texture.m_TextureSettings
            image = texture.image
            expected_format = 25 if record.format == "BC7" else 4
            expected_gpu = int(record.gpu_bytes)
            stream = getattr(texture, "m_StreamData", None)
            stream_size = int(getattr(stream, "size", 0)) if stream is not None else 0
            stream_path = str(getattr(stream, "path", "")) if stream is not None else ""
            inline = getattr(texture, "m_ImageData", None)
            inline_size = (
                len(inline)
                if isinstance(inline, (bytes, bytearray, memoryview))
                else 0
            )
            expected_filter = 0 if contract.filter_mode == "Point" else 1
            payload_exact = (
                stream_size == expected_gpu and bool(stream_path)
            ) or (stream_size == 0 and inline_size == expected_gpu)
            if (
                int(texture.m_Width) != atlas_page.width
                or int(texture.m_Height) != atlas_page.height
                or int(texture.m_TextureFormat) != expected_format
                or int(getattr(texture, "m_ColorSpace", -1)) != 1
                or int(texture.m_MipCount) != 1
                or bool(texture.m_IsReadable)
                or int(getattr(texture, "m_CompleteImageSize", -1)) != expected_gpu
                or not payload_exact
                or int(settings.m_FilterMode) != expected_filter
                or int(settings.m_Aniso) != 0
                or int(settings.m_WrapU) != 1
                or int(settings.m_WrapV) != 1
                or int(settings.m_WrapW) != 1
                or image.mode != "RGBA"
                or image.size != (atlas_page.width, atlas_page.height)
            ):
                raise UnityAssetBundleError(
                    f"Final V2 {plane} Texture2D contract drifted: "
                    f"{atlas.group} page={atlas_page.id}"
                )
        except UnityAssetBundleError:
            raise
        except Exception as exc:
            raise UnityAssetBundleError(
                f"Final V2 {plane} Texture2D could not be decoded: "
                f"{atlas.group} page={atlas_page.id}"
            ) from exc
        finally:
            if image is not None:
                image.close()
    return atlas_payload


def _validate_asset_bundle_payload_v2(
    bundle_path: Path,
    group: Mapping[str, object],
    prepared: PreparedUnityProject,
    crop_collector: QualityCropCollector,
) -> tuple[FrameQualityEvidence, ...]:
    """Decode BC7/RGBA32 pages and measure every visible frame."""

    try:
        import UnityPy
    except ImportError as exc:  # pragma: no cover - dependency pin guards this
        raise UnityAssetBundleError(
            "UnityPy 1.25.3 is required for V2 bundle verification"
        ) from exc
    try:
        environment = UnityPy.load(str(bundle_path.resolve(strict=True)))
        readers = tuple(environment.objects)
    except Exception as exc:
        raise UnityAssetBundleError(
            f"Built V2 AssetBundle could not be decoded: {bundle_path.name}"
        ) from exc
    by_path_id: dict[int, object] = {}
    bundle_readers: list[object] = []
    for reader in readers:
        path_id = getattr(reader, "path_id", None)
        if not isinstance(path_id, int) or path_id in by_path_id:
            raise UnityAssetBundleError(
                f"Built V2 AssetBundle has invalid object ids: {bundle_path.name}"
            )
        by_path_id[path_id] = reader
        if getattr(getattr(reader, "type", None), "name", None) == "AssetBundle":
            bundle_readers.append(reader)
    if len(bundle_readers) != 1:
        raise UnityAssetBundleError(
            f"Built V2 file does not contain one AssetBundle: {bundle_path.name}"
        )
    try:
        bundle_object = bundle_readers[0].read()
        container_pairs = tuple(bundle_object.m_Container)
        dependencies = tuple(bundle_object.m_Dependencies)
    except Exception as exc:
        raise UnityAssetBundleError(
            f"Built V2 AssetBundle metadata could not be read: {bundle_path.name}"
        ) from exc
    if (
        getattr(bundle_object, "m_Name", None) != group["bundle"]
        or getattr(bundle_object, "m_AssetBundleName", None) != group["bundle"]
        or dependencies
        or bool(getattr(bundle_object, "m_IsStreamedSceneAssetBundle", True))
    ):
        raise UnityAssetBundleError(
            f"Built V2 AssetBundle identity/dependencies drifted: {bundle_path.name}"
        )
    address_to_path_id: dict[str, int] = {}
    for pair in container_pairs:
        try:
            address = pair[0]
            path_id = pair[1].asset.m_PathID
        except Exception as exc:
            raise UnityAssetBundleError(
                f"Built V2 AssetBundle container is malformed: {bundle_path.name}"
            ) from exc
        if (
            not isinstance(address, str)
            or not isinstance(path_id, int)
            or address in address_to_path_id
            or path_id not in by_path_id
        ):
            raise UnityAssetBundleError(
                f"Built V2 address map is invalid: {bundle_path.name}"
            )
        address_to_path_id[address] = path_id

    atlas_address = str(group["atlas_address"])
    atlas_reader = by_path_id.get(address_to_path_id.get(atlas_address, -1))
    if (
        atlas_reader is None
        or getattr(getattr(atlas_reader, "type", None), "name", None) != "TextAsset"
    ):
        raise UnityAssetBundleError("Built V2 atlas.v3 is not a TextAsset")
    try:
        atlas_script = atlas_reader.read().m_Script
        if not isinstance(atlas_script, str):
            raise TypeError("m_Script")
        atlas_payload = atlas_script.encode("utf-8", errors="strict")
    except Exception as exc:
        raise UnityAssetBundleError("Built V2 atlas.v3 text could not be read") from exc
    if _sha256_bytes(atlas_payload) != group["atlas_sha256"]:
        raise UnityAssetBundleError("Built V2 atlas.v3 bytes drifted")
    atlas = _canonical_json_object_from_bytes(
        atlas_payload,
        label=f"{group['group']} post-Unity atlas.v3",
        maximum_bytes=MAX_ATLAS_BYTES,
    )
    if (
        atlas.get("schema") != BC7_ATLAS_SCHEMA
        or atlas.get("group") != group["group"]
        or atlas.get("slug") != group["slug"]
        or atlas.get("bundle") != group["bundle"]
    ):
        raise UnityAssetBundleError("Built V2 atlas.v3 identity drifted")
    raw_pages = atlas.get("pages")
    raw_frames = atlas.get("frames")
    if not isinstance(raw_pages, list) or not isinstance(raw_frames, list):
        raise UnityAssetBundleError("Built V2 atlas.v3 pages/frames are malformed")
    expected_addresses = {atlas_address}
    for page in raw_pages:
        if not isinstance(page, dict):
            raise UnityAssetBundleError("Built V2 atlas page is not an object")
        for plane in ("main", "mask"):
            record = page[plane]
            if record is not None:
                expected_addresses.add(str(record["address"]))
    if set(address_to_path_id) != expected_addresses or len(readers) != len(expected_addresses) + 1:
        raise UnityAssetBundleError(
            f"Built V2 AssetBundle address/object set drifted: {bundle_path.name}"
        )

    frames_by_page: dict[int, list[dict[str, object]]] = {}
    for raw in raw_frames:
        if not isinstance(raw, dict):
            raise UnityAssetBundleError("Built V2 frame is not an object")
        frames_by_page.setdefault(int(raw["page"]), []).append(raw)
    evidence: list[FrameQualityEvidence] = []
    for page in raw_pages:
        page_id = int(page["id"])
        width = int(page["width"])
        height = int(page["height"])
        decoded: dict[str, Image.Image] = {}
        sources: dict[str, Image.Image] = {}
        try:
            for plane in ("main", "mask"):
                record = page[plane]
                if record is None:
                    continue
                address = str(record["address"])
                reader = by_path_id[address_to_path_id[address]]
                if getattr(getattr(reader, "type", None), "name", None) != "Texture2D":
                    raise UnityAssetBundleError(
                        f"Built V2 {plane} page is not Texture2D"
                    )
                try:
                    texture = reader.read()
                    settings = texture.m_TextureSettings
                    image = texture.image
                except Exception as exc:
                    raise UnityAssetBundleError(
                        f"Built V2 {plane} texture could not be decoded"
                    ) from exc
                expected_format = 25 if record["format"] == "BC7" else 4
                expected_gpu = int(record["gpu_bytes"])
                stream = getattr(texture, "m_StreamData", None)
                stream_size = int(getattr(stream, "size", 0)) if stream is not None else 0
                stream_path = str(getattr(stream, "path", "")) if stream is not None else ""
                inline = getattr(texture, "m_ImageData", None)
                inline_size = len(inline) if isinstance(inline, (bytes, bytearray, memoryview)) else 0
                contract = atlas["texture_contracts"][plane]
                expected_filter = 0 if contract["filter_mode"] == "Point" else 1
                if (
                    int(texture.m_Width) != width
                    or int(texture.m_Height) != height
                    or int(texture.m_TextureFormat) != expected_format
                    or int(getattr(texture, "m_ColorSpace", -1)) != 1
                    or int(texture.m_MipCount) != 1
                    or bool(texture.m_IsReadable)
                    or int(getattr(texture, "m_CompleteImageSize", -1)) != expected_gpu
                    or not (
                        (stream_size == expected_gpu and bool(stream_path))
                        or (stream_size == 0 and inline_size == expected_gpu)
                    )
                    or int(settings.m_FilterMode) != expected_filter
                    or int(settings.m_Aniso) != 0
                    or int(settings.m_WrapU) != 1
                    or int(settings.m_WrapV) != 1
                    or int(settings.m_WrapW) != 1
                    or image.mode != "RGBA"
                    or image.size != (width, height)
                ):
                    image.close()
                    raise UnityAssetBundleError(
                        f"Built V2 {plane} Texture2D contract drifted: "
                        f"{group['group']} page={page_id}"
                    )
                decoded[plane] = image
                source_path = prepared.project_path.joinpath(
                    *str(record["asset_path"]).split("/")
                )
                source, source_digest = _load_rgba_png(
                    source_path,
                    expected_size=(width, height),
                    label=f"V2 quality source {group['group']} page={page_id} {plane}",
                )
                if source_digest != record["source_rgba_sha256"]:
                    source.close()
                    raise UnityAssetBundleError(
                        f"V2 quality source page drifted: {group['group']} page={page_id}"
                    )
                sources[plane] = source

            for frame in frames_by_page.get(page_id, []):
                rect = frame["rect"]
                if not isinstance(rect, dict):
                    raise UnityAssetBundleError("V2 quality frame rect is malformed")
                left = int(rect["x"])
                top = height - int(rect["y"]) - int(rect["height"])
                box = (
                    left,
                    top,
                    left + int(rect["width"]),
                    top + int(rect["height"]),
                )
                source_main = sources["main"].crop(box)
                decoded_main = decoded["main"].crop(box)
                source_mask = sources["mask"].crop(box) if "mask" in sources else None
                decoded_mask = decoded["mask"].crop(box) if "mask" in decoded else None
                try:
                    if _rgba_sha256_image(source_main) != frame["main_source_rgba_sha256"]:
                        raise UnityAssetBundleError(
                            f"V2 source frame binding drifted: {group['group']}/{frame['name']}"
                        )
                    if source_mask is not None and _rgba_sha256_image(source_mask) != frame["mask_source_rgba_sha256"]:
                        raise UnityAssetBundleError(
                            f"V2 source mask binding drifted: {group['group']}/{frame['name']}"
                        )
                    frame_evidence = measure_frame(
                        group=str(group["group"]),
                        name=str(frame["name"]),
                        index=int(frame["index"]),
                        alt=bool(frame["alt"]),
                        page=page_id,
                        source_main=source_main,
                        decoded_main=decoded_main,
                        source_mask=source_mask,
                        decoded_mask=decoded_mask,
                    )
                    crop_collector.consider(
                        frame_evidence,
                        source_main=source_main,
                        decoded_main=decoded_main,
                        source_mask=source_mask,
                        decoded_mask=decoded_mask,
                    )
                    evidence.append(frame_evidence)
                finally:
                    source_main.close()
                    decoded_main.close()
                    if source_mask is not None:
                        source_mask.close()
                    if decoded_mask is not None:
                        decoded_mask.close()
        finally:
            for image in decoded.values():
                image.close()
            for image in sources.values():
                image.close()
    if len(evidence) != int(group["frame_count"]):
        raise UnityAssetBundleError(
            f"V2 quality evidence count drifted: {group['group']}"
        )
    return tuple(evidence)


def _v2_predicted_load_peak(resident_charge_bytes: int, bundle_size_bytes: int) -> int:
    if resident_charge_bytes <= 0 or bundle_size_bytes <= 0:
        raise UnityAssetBundleError("V2 predicted load peak inputs must be positive")
    return (
        2 * resident_charge_bytes
        + _align_up(bundle_size_bytes, 64 * 1024 * 1024)
        + 256 * 1024 * 1024
    )


def _validate_v2_unity_report(
    prepared: PreparedUnityProject,
) -> tuple[dict[str, object], tuple[BundleArtifact, ...]]:
    if prepared.unity_report_path is None:
        raise UnityAssetBundleError("V2 Unity report path is missing")
    build_input_payload, build_input = _read_json_bytes(
        prepared.build_input_path, canonical=True, maximum_bytes=MAX_REPORT_BYTES
    )
    _payload, report = _read_json_bytes(
        prepared.unity_report_path, canonical=True, maximum_bytes=MAX_REPORT_BYTES
    )
    _require_exact_keys(
        report,
        {
            "build_id", "build_input_sha256", "build_options", "build_target",
            "bundles", "error", "index_sha256", "quality_report_sha256", "schema",
            "success", "textures", "unity", "verified",
        },
        "V2 Unity build report",
    )
    if (
        report["schema"] != BC7_BUILD_REPORT_SCHEMA
        or report["success"] is not True
        or report["verified"] is not False
        or report["error"] != ""
        or report["index_sha256"] is not None
        or report["quality_report_sha256"] is not None
        or report["build_id"] != prepared.build_id
        or report["build_input_sha256"] != _sha256_bytes(build_input_payload)
        or report["build_options"] != list(BUILD_OPTIONS)
        or report["build_target"] != BUILD_TARGET
        or report["unity"] != {"revision": UNITY_REVISION, "version": UNITY_VERSION}
    ):
        raise UnityAssetBundleError("V2 Unity build report identity/status drifted")

    expected_textures = build_input["textures"]
    actual_textures = report["textures"]
    if not isinstance(expected_textures, list) or not isinstance(actual_textures, list):
        raise UnityAssetBundleError("V2 Unity texture report is malformed")
    expected_by_path = {str(item["asset_path"]): item for item in expected_textures}
    if [item.get("asset_path") for item in actual_textures if isinstance(item, dict)] != sorted(expected_by_path):
        raise UnityAssetBundleError("V2 Unity texture report order/set drifted")
    for raw in actual_textures:
        if not isinstance(raw, dict):
            raise UnityAssetBundleError("V2 Unity texture report entry is not an object")
        _require_exact_keys(
            raw,
            {
                "asset_path", "gpu_bytes", "height", "plane", "source_png_sha256",
                "source_rgba_bytes", "source_rgba_sha256", "texture_contract", "width",
            },
            "V2 Unity texture report entry",
        )
        expected = expected_by_path.get(str(raw["asset_path"]))
        if expected is None or raw != {
            "asset_path": expected["asset_path"],
            "gpu_bytes": expected["gpu_bytes"],
            "height": expected["height"],
            "plane": expected["plane"],
            "source_png_sha256": expected["source_png_sha256"],
            "source_rgba_bytes": expected["source_rgba_bytes"],
            "source_rgba_sha256": expected["source_rgba_sha256"],
            "texture_contract": expected["texture_contract_id"],
            "width": expected["width"],
        }:
            raise UnityAssetBundleError(
                f"V2 Unity texture report drifted: {raw.get('asset_path')}"
            )

    expected_names = sorted(str(bundle["name"]) for bundle in build_input["bundles"])
    raw_bundles = report["bundles"]
    if not isinstance(raw_bundles, list) or [item.get("name") for item in raw_bundles if isinstance(item, dict)] != expected_names:
        raise UnityAssetBundleError("V2 Unity bundle report order/set drifted")
    artifacts: list[BundleArtifact] = []
    for raw in raw_bundles:
        if not isinstance(raw, dict):
            raise UnityAssetBundleError("V2 Unity bundle report entry is not an object")
        _require_exact_keys(
            raw,
            {"manifest_hash", "mod_relative_path", "name", "sha256", "size_bytes"},
            "V2 bundle artifact",
        )
        name = str(raw["name"])
        relative = _safe_relative_path(
            str(raw["mod_relative_path"]), "V2 bundle mod_relative_path"
        )
        size = raw["size_bytes"]
        digest = str(raw["sha256"])
        manifest_hash = str(raw["manifest_hash"])
        if (
            _BC7_BUNDLE_RE.fullmatch(name) is None
            or relative != f"{_MOD_BUNDLE_DIRECTORY}/{name}"
            or isinstance(size, bool)
            or not isinstance(size, int)
            or size <= 0
            or _SHA256_RE.fullmatch(digest) is None
            or _HASH128_RE.fullmatch(manifest_hash) is None
        ):
            raise UnityAssetBundleError(f"Invalid V2 bundle artifact: {name}")
        path = prepared.build_root.joinpath("output", *relative.split("/"))
        if (
            path.resolve(strict=True).parent != prepared.output_path.resolve(strict=True)
            or path.stat().st_size != size
            or _sha256_file(path) != digest
        ):
            raise UnityAssetBundleError(f"V2 bundle artifact bytes drifted: {name}")
        artifacts.append(
            BundleArtifact(name, relative, size, digest, manifest_hash)
        )
    allowed = set(expected_names)
    allowed.update(f"{name}.manifest" for name in expected_names)
    allowed.update({"win64", "win64.manifest"})
    actual = {path.name for path in prepared.output_path.iterdir() if path.is_file()}
    if actual != allowed or any(path.is_dir() for path in prepared.output_path.iterdir()):
        raise UnityAssetBundleError("V2 Unity output file set drifted")
    return report, tuple(artifacts)


def _write_v2_final_index(
    prepared: PreparedUnityProject,
    artifacts: Sequence[BundleArtifact],
    quality_report_sha256: str,
) -> str:
    _payload, template = _read_json_bytes(
        prepared.index_template_path, canonical=True, maximum_bytes=MAX_INDEX_BYTES
    )
    if template.get("schema") != BC7_INDEX_TEMPLATE_SCHEMA or template.get("quality_report_sha256") is not None:
        raise UnityAssetBundleError("V2 final index template state drifted")
    artifacts_by_name = {artifact.name: artifact for artifact in artifacts}
    raw_groups = template.get("groups")
    if not isinstance(raw_groups, list):
        raise UnityAssetBundleError("V2 index template groups are malformed")
    final_groups: list[dict[str, object]] = []
    for raw in raw_groups:
        if not isinstance(raw, dict):
            raise UnityAssetBundleError("V2 index template group is malformed")
        artifact = artifacts_by_name.get(str(raw["bundle"]))
        if artifact is None:
            raise UnityAssetBundleError(
                f"V2 index references an unbuilt bundle: {raw['bundle']}"
            )
        group = dict(raw)
        bundle_path = prepared.build_root.joinpath(
            "output", *artifact.mod_relative_path.split("/")
        )
        group.update(
            {
                "bundle_crc32": _crc32_file(bundle_path),
                "bundle_path": artifact.mod_relative_path,
                "bundle_sha256": artifact.sha256,
                "bundle_size_bytes": artifact.size_bytes,
                "predicted_load_peak_bytes": _v2_predicted_load_peak(
                    int(raw["resident_charge_bytes"]), artifact.size_bytes
                ),
                "unity_hash128": artifact.manifest_hash,
            }
        )
        final_groups.append(group)
    if set(artifacts_by_name) != {str(group["bundle"]) for group in raw_groups}:
        raise UnityAssetBundleError("V2 final index/report bundle set drifted")
    final = dict(template)
    final["groups"] = final_groups
    final["quality_report_sha256"] = quality_report_sha256
    final["schema"] = BC7_INDEX_SCHEMA
    payload = _canonical_json_bytes(final, final_lf=True)
    if len(payload) > MAX_INDEX_BYTES:
        raise UnityAssetBundleError("V2 final index exceeds its 4-MiB bound")
    _write_bytes(prepared.index_path, payload)
    return _sha256_bytes(payload)


def group_quality_frames_path(
    prepared: PreparedUnityProject, group: str
) -> Path:
    """Return the work-only full evidence sidecar for one built V2 group."""

    if not isinstance(prepared, PreparedUnityProject) or prepared.pipeline_version != 2:
        raise UnityAssetBundleError("Group quality evidence requires a V2 project")
    return (
        prepared.build_root
        / "output"
        / BC7_GROUP_QUALITY_EVIDENCE_DIRECTORY
        / group_slug(group)
        / "quality-frames.v1.jsonl"
    )


def validate_build_report_v2(prepared: PreparedUnityProject) -> ValidatedBuildReport:
    """Finish the cycle-free V2 chain after Unity and visual measurement."""

    validate_prepared_project_v2(prepared)
    intermediate, artifacts = _validate_v2_unity_report(prepared)
    _template_payload, template = _read_json_bytes(
        prepared.index_template_path, canonical=True, maximum_bytes=MAX_INDEX_BYTES
    )
    groups = template.get("groups")
    if not isinstance(groups, list):
        raise UnityAssetBundleError("V2 index template groups are missing")
    group_by_bundle = {
        str(group["bundle"]): group for group in groups if isinstance(group, dict)
    }
    evidence: list[FrameQualityEvidence] = []
    crop_collector = QualityCropCollector()
    for artifact in artifacts:
        group = group_by_bundle.get(artifact.name)
        if group is None:
            raise UnityAssetBundleError(
                f"V2 bundle has no index group: {artifact.name}"
            )
        bundle_path = prepared.build_root.joinpath(
            "output", *artifact.mod_relative_path.split("/")
        )
        evidence.extend(
            _validate_asset_bundle_payload_v2(
                bundle_path, group, prepared, crop_collector
            )
        )
    evidence_by_group: dict[str, list[FrameQualityEvidence]] = {}
    for frame in evidence:
        evidence_by_group.setdefault(frame.group, []).append(frame)
    expected_group_names = {
        str(group["group"]) for group in groups if isinstance(group, dict)
    }
    if set(evidence_by_group) != expected_group_names:
        raise UnityAssetBundleError("V2 per-group quality evidence set drifted")
    for group_name in sorted(expected_group_names):
        frames = sorted(
            evidence_by_group[group_name],
            key=lambda item: (item.index, item.alt, item.name),
        )
        payload = b"".join(
            _canonical_json_bytes(frame.as_dict(), final_lf=True)
            for frame in frames
        )
        _write_bytes(group_quality_frames_path(prepared, group_name), payload)
    report_mode = (
        QUALITY_MEASUREMENT_MODE
        if prepared.quality_mode == "measurement_nonpromotable"
        else QUALITY_ACCEPTANCE_MODE
    )
    quality_payload, quality_document = build_quality_report(
        build_id=prepared.build_id,
        backend=BC7_BACKEND_KIND,
        encoder_id=BC7_ENCODER_ID,
        texture_policy_id=str(prepared.texture_policy_id),
        bundles=[
            {
                "name": artifact.name,
                "sha256": artifact.sha256,
                "size_bytes": artifact.size_bytes,
            }
            for artifact in artifacts
        ],
        frames=evidence,
        mode=report_mode,
        quality_policy_id=str(prepared.quality_policy_id),
        quality_policy_sha256=str(prepared.quality_policy_sha256),
        acceptance_envelope=prepared.quality_acceptance_envelope,
    )
    if prepared.quality_report_path is None:
        raise UnityAssetBundleError("V2 quality report path is missing")
    quality_sha256 = write_quality_report(
        prepared.quality_report_path, quality_payload
    )
    write_observed_quality_envelope(
        prepared.quality_report_path.parent / "quality-envelope-observed.v1.json",
        build_id=prepared.build_id,
        quality_report_sha256=quality_sha256,
        frames=evidence,
    )
    write_quality_crop_artifacts(
        prepared.quality_report_path.parent / QUALITY_CROPS_DIRECTORY,
        build_id=prepared.build_id,
        quality_report_sha256=quality_sha256,
        collector=crop_collector,
    )
    crop_collector.close()
    if prepared.quality_mode == "frozen" and (
        quality_document.get("accepted") is not True
        or quality_document.get("promotable") is not True
    ):
        raise UnityAssetBundleError(
            "V2 build exceeded its explicitly frozen visual-quality envelope"
        )
    index_sha256 = _write_v2_final_index(
        prepared, artifacts, quality_sha256
    )
    final_report = dict(intermediate)
    final_report["index_sha256"] = index_sha256
    final_report["quality_report_sha256"] = quality_sha256
    final_report["verified"] = True
    final_payload = _canonical_json_bytes(final_report, final_lf=True)
    if len(final_payload) > MAX_REPORT_BYTES:
        raise UnityAssetBundleError("V2 final build report exceeds its 64-MiB bound")
    _write_bytes(prepared.report_path, final_payload)
    return ValidatedBuildReport(
        build_id=prepared.build_id,
        unity_version=UNITY_VERSION,
        unity_revision=UNITY_REVISION,
        index_sha256=index_sha256,
        bundles=artifacts,
        quality_report_sha256=quality_sha256,
    )


def run_headless_build(
    prepared: PreparedUnityProject,
    editor_executable: Path,
    *,
    timeout_seconds: int = 3600,
    runner: Callable[..., Any] = subprocess.run,
) -> ValidatedBuildReport:
    """Run exact Unity in batch mode and accept only a fresh, exact report."""

    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, int)
        or not 1 <= timeout_seconds <= 24 * 60 * 60
    ):
        raise UnityAssetBundleError("timeout_seconds must be in 1..86400")
    if prepared.pipeline_version == 2 and timeout_seconds != BC7_UNITY_TIMEOUT_SECONDS:
        raise UnityAssetBundleError(
            f"V2 Unity timeout must be exactly {BC7_UNITY_TIMEOUT_SECONDS} seconds"
        )
    command = build_headless_command(prepared, editor_executable)
    unity_report = (
        prepared.unity_report_path
        if prepared.pipeline_version == 2
        else prepared.report_path
    )
    if unity_report is None:
        raise UnityAssetBundleError("Unity report path is missing")
    stale_paths = [unity_report]
    if prepared.pipeline_version == 2:
        stale_paths.extend(
            path
            for path in (
                prepared.report_path,
                prepared.index_path,
                prepared.quality_report_path,
            )
            if path is not None
        )
    if any(path.exists() for path in stale_paths):
        raise UnityAssetBundleError(
            f"Refusing to trust or overwrite stale Unity/V2 output: {stale_paths}"
        )
    unity_report.parent.mkdir(parents=True, exist_ok=True)
    try:
        completed = runner(
            list(command),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise UnityAssetBundleError(
            f"Unity AssetBundle build timed out after {timeout_seconds} seconds"
        ) from exc
    except OSError as exc:
        raise UnityAssetBundleError("Unity Editor could not be started") from exc
    return_code = getattr(completed, "returncode", None)
    if return_code != 0:
        detail = _report_error(unity_report)
        if detail is None:
            stderr = str(getattr(completed, "stderr", "")).strip()
            detail = stderr or (
                "no build report; verify the exact editor installation and that "
                "the user's Unity license is activated"
            )
        raise UnityAssetBundleError(
            f"Unity AssetBundle build failed with exit code {return_code}: {detail}"
        )
    if prepared.pipeline_version == 2:
        return validate_build_report_v2(prepared)
    return validate_build_report(prepared)


def validate_build_report(
    prepared: PreparedUnityProject,
    *,
    bundle_payload_validator: Callable[[Path, Mapping[str, object]], None]
    | None = None,
) -> ValidatedBuildReport:
    """Validate Unity's report, imported textures and every bundle byte."""

    validate_prepared_project(prepared)
    build_input_payload, build_input = _read_json_bytes(
        prepared.build_input_path, canonical=True
    )
    _report_payload, report = _read_json_bytes(
        prepared.report_path,
        canonical=True,
        maximum_bytes=MAX_REPORT_BYTES,
    )
    _require_exact_keys(
        report,
        {
            "schema",
            "success",
            "error",
            "build_id",
            "build_input_sha256",
            "unity",
            "build_target",
            "build_options",
            "textures",
            "bundles",
        },
        "build report",
    )
    if report["schema"] != BUILD_REPORT_SCHEMA:
        raise UnityAssetBundleError("Unity build report schema changed")
    if report["success"] is not True or report["error"] != "":
        raise UnityAssetBundleError(
            f"Unity build report is not successful: {report['error']!r}"
        )
    if (
        report["build_id"] != prepared.build_id
        or report["build_input_sha256"] != _sha256_bytes(build_input_payload)
        or report["unity"]
        != {"version": UNITY_VERSION, "revision": UNITY_REVISION}
        or report["build_target"] != BUILD_TARGET
        or report["build_options"] != list(BUILD_OPTIONS)
    ):
        raise UnityAssetBundleError("Unity build report identity/constants drifted")

    expected_textures = build_input["textures"]
    actual_textures = report["textures"]
    if not isinstance(expected_textures, list) or not isinstance(actual_textures, list):
        raise UnityAssetBundleError("Unity texture report must be a list")
    if [item.get("asset_path") for item in actual_textures if isinstance(item, dict)] != sorted(
        item["asset_path"] for item in expected_textures
    ):
        raise UnityAssetBundleError("Unity texture report order/set drifted")
    expected_by_path = {item["asset_path"]: item for item in expected_textures}
    texture_keys = {
        "asset_path",
        "width",
        "height",
        "format",
        "s_rgb",
        "mipmaps",
        "readable",
        "filter_mode",
        "wrap_mode",
        "alpha_source",
        "alpha_is_transparency",
        "npot_scale",
        "png_sha256",
    }
    for texture in actual_textures:
        if not isinstance(texture, dict):
            raise UnityAssetBundleError("Unity texture report entry is not an object")
        _require_exact_keys(texture, texture_keys, "build report texture")
        expected = expected_by_path.get(texture["asset_path"])
        if expected is None:
            raise UnityAssetBundleError(
                f"Unity reported an unexpected texture: {texture['asset_path']}"
            )
        exact = {
            "asset_path": expected["asset_path"],
            "width": expected["width"],
            "height": expected["height"],
            **_TEXTURE_CONTRACT,
            "png_sha256": expected["png_sha256"],
        }
        if texture != exact:
            raise UnityAssetBundleError(
                f"Unity texture import contract drifted: {texture['asset_path']}"
            )

    expected_bundles = build_input["bundles"]
    actual_bundles = report["bundles"]
    if not isinstance(expected_bundles, list) or not isinstance(actual_bundles, list):
        raise UnityAssetBundleError("Unity bundle report must be a list")
    expected_names = sorted(bundle["name"] for bundle in expected_bundles)
    if [bundle.get("name") for bundle in actual_bundles if isinstance(bundle, dict)] != expected_names:
        raise UnityAssetBundleError("Unity bundle report order/set drifted")
    artifacts: list[BundleArtifact] = []
    artifact_keys = {
        "name",
        "mod_relative_path",
        "size_bytes",
        "sha256",
        "manifest_hash",
    }
    for raw in actual_bundles:
        if not isinstance(raw, dict):
            raise UnityAssetBundleError("Unity bundle report entry is not an object")
        _require_exact_keys(raw, artifact_keys, "bundle artifact")
        name = raw["name"]
        if not isinstance(name, str) or _BUNDLE_RE.fullmatch(name) is None:
            raise UnityAssetBundleError(f"Invalid reported bundle name: {name!r}")
        expected_relative = f"{_MOD_BUNDLE_DIRECTORY}/{name}"
        relative = _safe_relative_path(
            str(raw["mod_relative_path"]), "bundle mod_relative_path"
        )
        if relative != expected_relative:
            raise UnityAssetBundleError(
                f"Bundle output path drifted: {relative} != {expected_relative}"
            )
        size = raw["size_bytes"]
        digest = raw["sha256"]
        manifest_hash = raw["manifest_hash"]
        if (
            isinstance(size, bool)
            or not isinstance(size, int)
            or size <= 0
            or not isinstance(digest, str)
            or _SHA256_RE.fullmatch(digest) is None
            or not isinstance(manifest_hash, str)
            or _HASH128_RE.fullmatch(manifest_hash) is None
        ):
            raise UnityAssetBundleError(f"Invalid bundle metadata: {name}")
        bundle_path = (prepared.build_root / "output").joinpath(
            *relative.split("/")
        )
        try:
            resolved_bundle = bundle_path.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise UnityAssetBundleError(f"Reported bundle is missing: {name}") from exc
        if (
            resolved_bundle.parent != prepared.output_path.resolve(strict=True)
            or not resolved_bundle.is_file()
            or resolved_bundle.stat().st_size != size
            or _sha256_file(resolved_bundle) != digest
        ):
            raise UnityAssetBundleError(f"Reported bundle bytes drifted: {name}")
        artifacts.append(
            BundleArtifact(
                name=name,
                mod_relative_path=relative,
                size_bytes=size,
                sha256=digest,
                manifest_hash=manifest_hash,
            )
        )

    allowed_output_files = set(expected_names)
    allowed_output_files.update(f"{name}.manifest" for name in expected_names)
    allowed_output_files.update({"win64", "win64.manifest"})
    actual_output_files = {
        path.name
        for path in prepared.output_path.iterdir()
        if path.is_file()
    }
    if actual_output_files != allowed_output_files:
        raise UnityAssetBundleError(
            "Unity output file set drifted: "
            f"missing={sorted(allowed_output_files - actual_output_files)}, "
            f"extra={sorted(actual_output_files - allowed_output_files)}"
        )
    if any(path.is_dir() for path in prepared.output_path.iterdir()):
        raise UnityAssetBundleError("Unity output unexpectedly contains directories")
    index_sha256 = _validate_final_index(prepared, artifacts)
    _index_payload, final_index = _read_json_bytes(prepared.index_path, canonical=True)
    final_groups = final_index.get("groups")
    if not isinstance(final_groups, list):
        raise UnityAssetBundleError("External index groups must be a list")
    final_by_bundle = {
        str(group["bundle"]): group
        for group in final_groups
        if isinstance(group, dict) and "bundle" in group
    }
    validator = bundle_payload_validator or _validate_asset_bundle_payload
    for artifact in artifacts:
        group = final_by_bundle.get(artifact.name)
        if group is None:
            raise UnityAssetBundleError(
                f"External index group is missing for bundle: {artifact.name}"
            )
        bundle_path = (prepared.build_root / "output").joinpath(
            *artifact.mod_relative_path.split("/")
        )
        validator(bundle_path, group)
    return ValidatedBuildReport(
        build_id=prepared.build_id,
        unity_version=UNITY_VERSION,
        unity_revision=UNITY_REVISION,
        index_sha256=index_sha256,
        bundles=tuple(artifacts),
    )

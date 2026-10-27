"""Fail-closed contracts for the lossless GM AssetBundle streaming backend.

This module is deliberately independent from the builder and the Unity runtime.
It freezes the profile, generated JSON, artifact-report, and admission contracts
that those components must share.  It performs no file-system writes and does
not accept an approximate or partially specified production policy.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import math
import re
import unicodedata
from typing import Iterable, Mapping, Sequence


MIB = 1024 * 1024
GIB = 1024 * MIB
MAX_SIGNED_INT64 = (1 << 63) - 1

ATLAS_BACKEND_KIND = "unity_assetbundle_lossless_streaming_v1"
RESOURCE_POLICY_KIND = "windows_24gb_igpu_safe_v1"
INDEX_SCHEMA = "stronghold-europe-de.asset-bundle-index.v1"
ATLAS_SCHEMA = "stronghold-europe-de.atlas.v2"
BUILD_REPORT_SCHEMA = "stronghold-europe-de.asset-bundle-build-report.v1"

# BC7 V2 is a separate, discriminated contract.  The V1 names above are kept
# byte- and meaning-stable because already-built artifacts and their runtime
# companion still import them directly.
BC7_ATLAS_BACKEND_KIND = "unity_assetbundle_bc7_visual_equivalence_v2"
BC7_RESOURCE_POLICY_KIND_V3 = "windows_24gb_igpu_bc7_8gib_commit_v3"
BC7_RESOURCE_POLICY_KIND = (
    "windows_24gb_igpu_bc7_12gib_process_private_v5"
)
BC7_INDEX_SCHEMA = "stronghold-europe-de.asset-bundle-index.v2"
BC7_INDEX_TEMPLATE_SCHEMA = "stronghold-europe-de.asset-bundle-index-template.v2"
BC7_BUILD_INPUT_SCHEMA = "stronghold-europe-de.asset-bundle-build-input.v2"
BC7_BUILD_REPORT_SCHEMA = "stronghold-europe-de.asset-bundle-build-report.v2"
BC7_ATLAS_SCHEMA = "stronghold-europe-de.atlas.v3"
BC7_QUALITY_REPORT_SCHEMA = (
    "stronghold-europe-de.asset-bundle-quality-report.v1"
)
BC7_PREPARATION_SEED_SCHEMA = (
    "stronghold-europe-de.asset-bundle-preparation-seed.v2"
)

# Descriptive aliases make call sites explicit without changing the historical
# public constants used by V1.
ATLAS_BACKEND_KIND_V2 = BC7_ATLAS_BACKEND_KIND
RESOURCE_POLICY_KIND_V2 = BC7_RESOURCE_POLICY_KIND
RESOURCE_POLICY_KIND_V3 = BC7_RESOURCE_POLICY_KIND_V3
RESOURCE_POLICY_KIND_V4 = BC7_RESOURCE_POLICY_KIND
INDEX_SCHEMA_V2 = BC7_INDEX_SCHEMA
INDEX_TEMPLATE_SCHEMA_V2 = BC7_INDEX_TEMPLATE_SCHEMA
BUILD_INPUT_SCHEMA_V2 = BC7_BUILD_INPUT_SCHEMA
BUILD_REPORT_SCHEMA_V2 = BC7_BUILD_REPORT_SCHEMA
ATLAS_SCHEMA_V3 = BC7_ATLAS_SCHEMA
QUALITY_REPORT_SCHEMA_V1 = BC7_QUALITY_REPORT_SCHEMA
PREPARATION_SEED_SCHEMA_V2 = BC7_PREPARATION_SEED_SCHEMA

UNITY_VERSION = "2021.3.45f2"
UNITY_REVISION = "88f88f591b2e"
BUILD_TARGET = "StandaloneWindows64"
MAX_PAGE_DIMENSION = 4096
MIN_PAGE_DIMENSION = 256
INDEX_OUTPUT_PATH = "Runtime/AssetBundles/index.json"
ASSET_BUNDLE_OUTPUT_PREFIX = "Runtime/AssetBundles/win64/"
ASSET_STREAM_OUTPUT_PREFIX = "Runtime/AssetBundles/"
LEGACY_ATLAS_OUTPUT_PREFIX = "Override/Atlas/"
LEGACY_SPRITE_OUTPUT_PREFIX = "Override/Sprites/"
ASSET_BUNDLE_CATEGORY = "asset_bundle"
ASSET_BUNDLE_INDEX_CATEGORY = "asset_bundle_index"

RESOURCE_POLICY_KEYS = frozenset(
    {
        "kind",
        "additional_gm_resident_bytes",
        "ui_resident_bytes",
        "audio_stream_bytes",
        "process_private_ceiling_bytes",
        "global_commit_reserve_bytes",
        "minimum_free_physical_bytes",
        "peak_admission_bytes",
    }
)
RESOURCE_POLICY_VALUES: Mapping[str, int | str] = {
    "kind": RESOURCE_POLICY_KIND,
    "additional_gm_resident_bytes": 3 * GIB,
    "ui_resident_bytes": 1 * GIB,
    "audio_stream_bytes": 16 * MIB,
    "process_private_ceiling_bytes": 16 * GIB,
    "global_commit_reserve_bytes": 8 * GIB,
    "minimum_free_physical_bytes": 4 * GIB,
    "peak_admission_bytes": 2 * GIB,
}

BC7_RESOURCE_POLICY_VALUES: Mapping[str, int | str] = {
    "kind": BC7_RESOURCE_POLICY_KIND,
    # This is an independent GM-residency envelope, not the total-process
    # ceiling encoded by the policy id.  Three GiB contains the current
    # Full152 charge (2,353,004,544 bytes) with useful growth headroom.
    "additional_gm_resident_bytes": 3 * GIB,
    "ui_resident_bytes": 1 * GIB,
    "audio_stream_bytes": 16 * MIB,
    "process_private_ceiling_bytes": 12 * GIB,
    "global_commit_reserve_bytes": 4 * GIB,
    "minimum_free_physical_bytes": 256 * MIB,
    "peak_admission_bytes": 2 * GIB,
}
BC7_MAXIMUM_TOTAL_RESIDENT_CHARGE_BYTES = 3 * GIB

BC7_MAIN_BC7_MASK_TEXTURE_POLICY_ID = "bc7-main-bc7-mask-hq100-v1"
BC7_MAIN_RGBA32_MASK_TEXTURE_POLICY_ID = "bc7-main-rgba32-mask-hq100-v1"
BC7_TEXTURE_POLICY_VALUES: Mapping[str, tuple[str, str]] = {
    BC7_MAIN_BC7_MASK_TEXTURE_POLICY_ID: ("BC7", "BC7"),
    BC7_MAIN_RGBA32_MASK_TEXTURE_POLICY_ID: ("BC7", "RGBA32"),
}
BC7_QUALITY_STATES = frozenset({"measurement_nonpromotable", "frozen"})
BC7_QUALITY_VERIFIER_ID = "unitypy-1.25.3-bc7-frame-metrics-v1"
BC7_MEASUREMENT_QUALITY_POLICY_ID = "bc7_visual_equivalence_measurement_v1"
BC7_MEASUREMENT_QUALITY_POLICY_SHA256 = (
    "ef1799a23471a41f93df5e9ed8a79839e6051221cd699d988e7b6ae0a34f17e1"
)
BC7_FROZEN_QUALITY_POLICY_ID = "bc7_visual_equivalence_v2"

BC7_PACKER_ID = "maxrects-bssf-no-rotation-cell4-rgba-extrude-v2"
BC7_ENCODER_ID = "unity-2021.3.45f2-bc7-hq100-force-max-v1"
BC7_BUNDLE_SUFFIX = ".bc7.v2"
BC7_ATLAS_ASSET_FILENAME = "atlas.v3.json"
BC7_EXTRUSION_MODE = "nearest_edge_full_rgba_v1"
BC7_BLOCK_ALIGNMENT_PIXELS = 4
BC7_MINIMUM_BORDER_PIXELS = 1
BC7_BUILD_INPUT_ASSET_PATH = "Assets/Generated/build-input.v2.json"
BC7_INDEX_TEMPLATE_ASSET_PATH = "Assets/Generated/index.v2.template.json"
BC7_OUTPUT_RELATIVE_PATH = "../output/Runtime/AssetBundles/win64"
BC7_INDEX_OUTPUT_RELATIVE_PATH = "../output/Runtime/AssetBundles/index.json"
BC7_QUALITY_REPORT_OUTPUT_RELATIVE_PATH = "../output/bc7-quality-report.v1.json"
BC7_EDITOR_TEXTURE_COMPRESSION_OVERRIDE = "NoOverride"
BC7_TEXTURE_CONTRACT_IDENTITIES: Mapping[str, tuple[str, str, str]] = {
    "main-bc7-point-v1": ("main", "BC7", "Point"),
    "main-bc7-bilinear-v1": ("main", "BC7", "Bilinear"),
    "mask-bc7-point-v1": ("mask", "BC7", "Point"),
    "mask-rgba32-point-v1": ("mask", "RGBA32", "Point"),
}

UPLOAD_FIXED_OVERHEAD_BYTES = 256 * MIB
RESOURCE_ALIGNMENT_BYTES = 64 * MIB
BC7_GROUP_RESIDENT_ALIGNMENT_BYTES = 4 * MIB
BC7_BUNDLE_ALIGNMENT_BYTES = 64 * MIB
BC7_MAX_PAGES_PER_GROUP = 64
MAX_INDEX_BYTES = 4 * MIB
MAX_ATLAS_BYTES = 4 * MIB
MAX_REPORT_BYTES = 64 * MIB
MAX_GROUPS = 234
MAX_PAGES_PER_GROUP = 16
MAX_FRAMES_PER_GROUP = 4096
MAX_PREFLIGHT_FRAMES_PER_GROUP = 65536
MAX_PREFLIGHT_ARRAY_SIZE = 2_147_483_647
# Unity's Sprite.Create accepts authored pivots outside the normalized sprite
# rectangle.  The pinned games use that deliberately (for example blast3 uses
# 100/-99), so this is a defensive JSON bound rather than a rendering limit.
# 100 is the exact inclusive maximum in the pinned 135,352-sprite source/target
# inventory.  Unknown larger metadata therefore still fails closed.
MAX_ABSOLUTE_SPRITE_PIVOT = 100.0

OMISSION_FRAME_COUNT = "v1_frame_count_exceeded"
OMISSION_SLOT_COUNT = "v1_slot_count_exceeded"
OMISSION_FRAME_DIMENSION = "v1_frame_dimension_exceeded"
OMISSION_PAGE_COUNT = "v1_page_count_exceeded"
OMISSION_FOLIAGE_MULTIPAGE = "v1_foliage_multipage"
VANILLA_OMISSION_REASONS = frozenset(
    {
        OMISSION_FRAME_COUNT,
        OMISSION_SLOT_COUNT,
        OMISSION_FRAME_DIMENSION,
        OMISSION_PAGE_COUNT,
        OMISSION_FOLIAGE_MULTIPAGE,
    }
)

PLAIN_MATERIAL_BINDING = "plain_shared_v1"
GROUP_MASK_MATERIAL_BINDING = "group_mask_single_page_v1"
POSTFIX_PAGE_MASK_MATERIAL_BINDING = "set_body_sprite_postfix_page_mask_v1"
POSTFIX_PAGE_MASK_GROUPS = frozenset(
    {
        "body_trebutchet",
        "body_archer",
        "body_battering_ram",
        "body_catapult",
        "body_deer",
        "body_farmer",
    }
)

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_HASH128_RE = re.compile(r"[0-9a-f]{32}\Z")
_CRC32_RE = re.compile(r"[0-9a-f]{8}\Z")
# GM identity is semantic, not a filesystem component.  The pinned loader has
# one canonical spaced identity ("puff of smoke").  Spaces must be single,
# interior, and followed by an ASCII alphanumeric; paths always use the
# separately validated underscore slug.
_GROUP_RE = re.compile(
    r"[A-Za-z0-9](?:[A-Za-z0-9._-]| [A-Za-z0-9])*\Z"
)
_SLUG_RE = re.compile(r"[a-z0-9][a-z0-9._-]*\Z")
_BUNDLE_RE = re.compile(r"sede\.gm\.[a-z0-9][a-z0-9._-]*\.v2\Z")
_BC7_BUNDLE_RE = re.compile(
    r"sede\.gm\.[a-z0-9][a-z0-9._-]*\.bc7\.v2\Z"
)

_TEXTURE_CONTRACT_VALUES: Mapping[str, object] = {
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
_TEXTURE_KEYS = frozenset(_TEXTURE_CONTRACT_VALUES)
_TEXTURE_CONTRACT_V2_KEYS = frozenset(
    {
        "allows_alpha_splitting",
        "alpha_is_transparency",
        "alpha_source",
        "aniso_level",
        "compression",
        "compression_quality",
        "crunched_compression",
        "filter_mode",
        "force_maximum_compression_quality_bc6h_bc7",
        "format",
        "gpu_block_bytes",
        "gpu_block_height",
        "gpu_block_width",
        "ignore_png_gamma",
        "max_texture_size",
        "mipmaps",
        "npot_scale",
        "platform_override",
        "readable",
        "s_rgb",
        "streaming_mipmaps",
        "texture_type",
        "unity_texture_format",
        "wrap_mode",
    }
)
_BUILD_OPTIONS = (
    "ChunkBasedCompression",
    "DeterministicAssetBundle",
    "ForceRebuildAssetBundle",
    "StrictMode",
)


def expected_material_binding(group: str, mask_policy: str) -> str:
    """Return the only reviewed runtime material path for one GM group."""

    if mask_policy == "forbidden":
        return PLAIN_MATERIAL_BINDING
    if mask_policy == "required":
        if group.casefold() in POSTFIX_PAGE_MASK_GROUPS:
            return POSTFIX_PAGE_MASK_MATERIAL_BINDING
        return GROUP_MASK_MATERIAL_BINDING
    raise AssetStreamContractError(
        f"mask_policy: must be 'required' or 'forbidden', got {mask_policy!r}"
    )


class AssetStreamContractError(ValueError):
    """Raised when any streaming contract is incomplete or inconsistent."""


@dataclass(frozen=True, slots=True)
class ResourcePolicy:
    kind: str
    additional_gm_resident_bytes: int
    ui_resident_bytes: int
    audio_stream_bytes: int
    process_private_ceiling_bytes: int
    global_commit_reserve_bytes: int
    minimum_free_physical_bytes: int
    peak_admission_bytes: int


@dataclass(frozen=True, slots=True)
class TexturePolicy:
    """One global V2 texture policy; per-group or per-page mixing is forbidden."""

    id: str
    main_format: str
    mask_format: str


@dataclass(frozen=True, slots=True)
class QualityPolicy:
    """Portable visual-quality policy identity bound by the V2 profile."""

    state: str
    id: str
    sha256: str
    verifier_id: str

    @property
    def promotable(self) -> bool:
        return self.state == "frozen"


@dataclass(frozen=True, slots=True)
class AtlasBackend:
    kind: str
    resource_policy: ResourcePolicy
    texture_policy: TexturePolicy | None = None
    quality_policy: QualityPolicy | None = None

    @property
    def lossless(self) -> bool:
        # V2 promises a reviewed visual equivalence envelope, not byte identity.
        return self.kind == ATLAS_BACKEND_KIND

    @property
    def visual_equivalence(self) -> bool:
        return self.kind == BC7_ATLAS_BACKEND_KIND

    @property
    def promotable(self) -> bool:
        if self.kind == ATLAS_BACKEND_KIND:
            return True
        return self.quality_policy is not None and self.quality_policy.promotable

    @property
    def fallback(self) -> str:
        return "keep_crusader" if self.kind == ATLAS_BACKEND_KIND else "fail_closed"


@dataclass(frozen=True, slots=True)
class ResourceUsage:
    gm_resident_charge_bytes: int
    ui_resident_bytes: int
    audio_stream_bytes: int
    load_in_flight: bool = False


@dataclass(frozen=True, slots=True)
class ResourceSnapshot:
    process_private_bytes: int | None
    global_available_commit_bytes: int | None
    available_physical_bytes: int | None


class AdmissionReason(str, Enum):
    ADMITTED = "admitted"
    LOAD_ALREADY_IN_FLIGHT = "load_already_in_flight"
    METRIC_UNAVAILABLE = "metric_unavailable"
    UI_BUDGET_EXCEEDED = "ui_budget_exceeded"
    AUDIO_BUDGET_EXCEEDED = "audio_budget_exceeded"
    GM_BUDGET_EXCEEDED = "gm_budget_exceeded"
    PEAK_BUDGET_EXCEEDED = "peak_budget_exceeded"
    PROCESS_PRIVATE_CEILING = "process_private_ceiling"
    GLOBAL_COMMIT_RESERVE = "global_commit_reserve"
    MINIMUM_FREE_PHYSICAL = "minimum_free_physical"


@dataclass(frozen=True, slots=True)
class AdmissionDecision:
    admitted: bool
    reason: AdmissionReason
    charge_bytes: int
    peak_bytes: int

    @property
    def use_vanilla_fallback(self) -> bool:
        return not self.admitted


@dataclass(frozen=True, slots=True)
class UnityIdentity:
    version: str
    revision: str


@dataclass(frozen=True, slots=True)
class TextureContract:
    format: str
    s_rgb: bool
    mipmaps: bool
    readable: bool
    filter_mode: str
    wrap_mode: str
    alpha_source: str
    alpha_is_transparency: bool
    npot_scale: str


@dataclass(frozen=True, slots=True)
class PageTexture:
    asset_path: str
    address: str
    png_sha256: str
    rgba_sha256: str


@dataclass(frozen=True, slots=True)
class AtlasPage:
    id: int
    width: int
    height: int
    main: PageTexture
    mask: PageTexture | None

    @property
    def raw_rgba_bytes(self) -> int:
        planes = 2 if self.mask is not None else 1
        return self.width * self.height * 4 * planes


@dataclass(frozen=True, slots=True)
class FrameRect:
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class FramePivot:
    x: float
    y: float


@dataclass(frozen=True, slots=True)
class AtlasFrame:
    name: str
    index: int
    alt: bool
    page: int
    rect: FrameRect
    pivot: FramePivot
    pixels_per_unit: float
    main_rgba_sha256: str
    mask_rgba_sha256: str | None


@dataclass(frozen=True, slots=True)
class AtlasV2:
    schema: str
    group: str
    slug: str
    bundle: str
    mask_policy: str
    material_binding: str
    coordinate_system: str
    padding_pixels: int
    max_page_dimension: int
    texture_contract: TextureContract
    pages: tuple[AtlasPage, ...]
    frames: tuple[AtlasFrame, ...]
    frames_sha256: str
    file_sha256: str

    @property
    def raw_rgba_bytes(self) -> int:
        return sum(page.raw_rgba_bytes for page in self.pages)

    @property
    def charge_bytes(self) -> int:
        return calculate_resident_charge(self.raw_rgba_bytes)


@dataclass(frozen=True, slots=True)
class IndexPageSummary:
    id: int
    width: int
    height: int
    main_address: str
    main_rgba_sha256: str
    mask_address: str | None
    mask_rgba_sha256: str | None


@dataclass(frozen=True, slots=True)
class GroupIndexRecord:
    group: str
    slug: str
    gm_id: int
    dash_format: bool
    array_size: int
    lifetime: str
    bundle: str
    bundle_path: str
    bundle_size_bytes: int
    bundle_sha256: str
    bundle_crc32: str
    unity_hash128: str
    atlas_asset_path: str
    atlas_address: str
    atlas_sha256: str
    mask_policy: str
    material_binding: str
    page_count: int
    frame_count: int
    names_sha256: str
    frames_sha256: str
    raw_rgba_bytes: int
    resident_charge_bytes: int
    predicted_load_peak_bytes: int
    pages: tuple[IndexPageSummary, ...]
    atlas: AtlasV2


@dataclass(frozen=True, slots=True)
class VanillaOmittedGroup:
    group: str
    gm_id: int
    reason: str
    array_size: int
    frame_count: int
    names_sha256: str
    frames_sha256: str


@dataclass(frozen=True, slots=True)
class AssetBundleIndex:
    schema: str
    build_id: str
    unity: UnityIdentity
    build_target: str
    max_page_dimension: int
    groups: tuple[GroupIndexRecord, ...]
    vanilla_omitted_groups: tuple[VanillaOmittedGroup, ...]
    file_size_bytes: int
    file_sha256: str


@dataclass(frozen=True, slots=True)
class TextureBuildRecord:
    asset_path: str
    width: int
    height: int
    format: str
    s_rgb: bool
    mipmaps: bool
    readable: bool
    filter_mode: str
    wrap_mode: str
    alpha_source: str
    alpha_is_transparency: bool
    npot_scale: str
    png_sha256: str


@dataclass(frozen=True, slots=True)
class BundleArtifact:
    name: str
    mod_relative_path: str
    size_bytes: int
    sha256: str
    manifest_hash: str


@dataclass(frozen=True, slots=True)
class AssetBundleBuildReport:
    schema: str
    success: bool
    error: str
    build_id: str
    build_input_sha256: str
    unity: UnityIdentity
    build_target: str
    build_options: tuple[str, ...]
    textures: tuple[TextureBuildRecord, ...]
    bundles: tuple[BundleArtifact, ...]
    file_sha256: str

    def bundle(self, name: str) -> BundleArtifact:
        for artifact in self.bundles:
            if artifact.name == name:
                return artifact
        raise AssetStreamContractError(f"Build report has no bundle {name!r}")


@dataclass(frozen=True, slots=True)
class TextureContractV2:
    allows_alpha_splitting: bool
    alpha_is_transparency: bool
    alpha_source: str
    aniso_level: int
    compression: str
    compression_quality: int
    crunched_compression: bool
    filter_mode: str
    force_maximum_compression_quality_bc6h_bc7: bool
    format: str
    gpu_block_bytes: int
    gpu_block_height: int
    gpu_block_width: int
    ignore_png_gamma: bool
    max_texture_size: int
    mipmaps: bool
    npot_scale: str
    platform_override: bool
    readable: bool
    s_rgb: bool
    streaming_mipmaps: bool
    texture_type: str
    unity_texture_format: int
    wrap_mode: str


@dataclass(frozen=True, slots=True)
class PageTextureV2:
    asset_path: str
    address: str
    format: str
    gpu_bytes: int
    source_png_sha256: str
    source_rgba_bytes: int
    source_rgba_sha256: str


@dataclass(frozen=True, slots=True)
class AtlasPageV3:
    id: int
    width: int
    height: int
    main: PageTextureV2
    mask: PageTextureV2 | None

    @property
    def gpu_bytes(self) -> int:
        return self.main.gpu_bytes + (0 if self.mask is None else self.mask.gpu_bytes)

    @property
    def source_rgba_bytes(self) -> int:
        return self.main.source_rgba_bytes + (
            0 if self.mask is None else self.mask.source_rgba_bytes
        )


@dataclass(frozen=True, slots=True)
class AtlasFrameV3:
    name: str
    index: int
    alt: bool
    page: int
    rect: FrameRect
    storage_cell: FrameRect
    pivot: FramePivot
    pixels_per_unit: float
    main_source_rgba_sha256: str
    mask_source_rgba_sha256: str | None


@dataclass(frozen=True, slots=True)
class AtlasV3:
    schema: str
    group: str
    slug: str
    bundle: str
    mask_policy: str
    material_binding: str
    coordinate_system: str
    extrusion_mode: str
    minimum_border_pixels: int
    block_alignment_pixels: int
    max_page_dimension: int
    main_texture_contract: TextureContractV2
    mask_texture_contract: TextureContractV2 | None
    pages: tuple[AtlasPageV3, ...]
    frames: tuple[AtlasFrameV3, ...]
    frames_sha256: str
    file_sha256: str

    @property
    def gpu_bytes(self) -> int:
        return sum(page.gpu_bytes for page in self.pages)

    @property
    def source_rgba_bytes(self) -> int:
        return sum(page.source_rgba_bytes for page in self.pages)

    @property
    def resident_charge_bytes(self) -> int:
        return calculate_bc7_group_resident_charge(self.gpu_bytes)


@dataclass(frozen=True, slots=True)
class IndexPageSummaryV2:
    id: int
    width: int
    height: int
    main_address: str
    main_format: str
    main_gpu_bytes: int
    main_source_rgba_sha256: str
    mask_address: str | None
    mask_format: str | None
    mask_gpu_bytes: int | None
    mask_source_rgba_sha256: str | None


@dataclass(frozen=True, slots=True)
class GroupIndexRecordV2:
    group: str
    slug: str
    gm_id: int
    dash_format: bool
    array_size: int
    lifetime: str
    bundle: str
    atlas_asset_path: str
    atlas_address: str
    atlas_sha256: str
    mask_policy: str
    material_binding: str
    page_count: int
    frame_count: int
    names_sha256: str
    frames_sha256: str
    source_rgba_bytes: int
    gpu_bytes: int
    resident_charge_bytes: int
    pages: tuple[IndexPageSummaryV2, ...]
    atlas: AtlasV3
    bundle_path: str | None = None
    bundle_size_bytes: int | None = None
    bundle_sha256: str | None = None
    bundle_crc32: str | None = None
    unity_hash128: str | None = None
    predicted_load_peak_bytes: int | None = None


@dataclass(frozen=True, slots=True)
class AssetBundleIndexV2:
    schema: str
    backend_kind: str
    build_id: str
    unity: UnityIdentity
    build_target: str
    max_page_dimension: int
    packer_id: str
    encoder_id: str
    texture_policy: TexturePolicy
    quality_policy: QualityPolicy
    quality_report_sha256: str | None
    groups: tuple[GroupIndexRecordV2, ...]
    vanilla_omitted_groups: tuple[VanillaOmittedGroup, ...]
    total_source_rgba_bytes: int
    total_gpu_bytes: int
    total_resident_charge_bytes: int
    file_size_bytes: int
    file_sha256: str

    @property
    def is_template(self) -> bool:
        return self.schema == BC7_INDEX_TEMPLATE_SCHEMA

    @property
    def promotable(self) -> bool:
        return (
            not self.is_template
            and self.quality_policy.promotable
            and self.quality_report_sha256 is not None
            and not self.vanilla_omitted_groups
        )


@dataclass(frozen=True, slots=True)
class TextureContractBindingV2:
    id: str
    texture_contract: TextureContractV2


@dataclass(frozen=True, slots=True)
class TextureBuildInputV2:
    asset_path: str
    width: int
    height: int
    plane: str
    texture_contract_id: str
    gpu_bytes: int
    source_png_sha256: str
    source_rgba_bytes: int
    source_rgba_sha256: str


@dataclass(frozen=True, slots=True)
class BundleAssetInputV2:
    address: str
    asset_path: str


@dataclass(frozen=True, slots=True)
class BundleBuildInputV2:
    name: str
    assets: tuple[BundleAssetInputV2, ...]


@dataclass(frozen=True, slots=True)
class AssetBundleBuildInputV2:
    schema: str
    backend_kind: str
    build_id: str
    unity: UnityIdentity
    build_target: str
    build_options: tuple[str, ...]
    max_page_dimension: int
    output_relative_path: str
    index_template_asset_path: str
    index_output_relative_path: str
    quality_report_output_relative_path: str
    editor_script_sha256: str
    editor_texture_compression_override: str
    packer_id: str
    encoder_id: str
    texture_policy: TexturePolicy
    quality_policy: QualityPolicy
    texture_contracts: tuple[TextureContractBindingV2, ...]
    textures: tuple[TextureBuildInputV2, ...]
    bundles: tuple[BundleBuildInputV2, ...]
    file_sha256: str


@dataclass(frozen=True, slots=True)
class TextureBuildRecordV2:
    asset_path: str
    width: int
    height: int
    plane: str
    texture_contract: str
    gpu_bytes: int
    source_png_sha256: str
    source_rgba_bytes: int
    source_rgba_sha256: str


@dataclass(frozen=True, slots=True)
class AssetBundleBuildReportV2:
    schema: str
    success: bool
    verified: bool
    error: str
    build_id: str
    build_input_sha256: str
    unity: UnityIdentity
    build_target: str
    build_options: tuple[str, ...]
    textures: tuple[TextureBuildRecordV2, ...]
    bundles: tuple[BundleArtifact, ...]
    index_sha256: str | None
    quality_report_sha256: str | None
    file_sha256: str

    def bundle(self, name: str) -> BundleArtifact:
        for artifact in self.bundles:
            if artifact.name == name:
                return artifact
        raise AssetStreamContractError(f"V2 build report has no bundle {name!r}")


def _fail(label: str, detail: str) -> None:
    raise AssetStreamContractError(f"{label}: {detail}")


def _require_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        _fail(label, "must be an object")
    return value


def _require_list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        _fail(label, "must be an array")
    return value


def _require_exact_keys(
    value: Mapping[str, object], expected: Iterable[str], label: str
) -> None:
    expected_set = set(expected)
    actual = set(value)
    if actual != expected_set:
        missing = sorted(expected_set - actual)
        extra = sorted(actual - expected_set)
        _fail(label, f"key set changed; missing={missing}, extra={extra}")


def _require_string(value: object, label: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        _fail(label, "must be a string")
    if not allow_empty and not value:
        _fail(label, "must not be empty")
    if unicodedata.normalize("NFC", value) != value:
        _fail(label, "must be NFC-normalized")
    return value


def _require_bool(value: object, label: str) -> bool:
    if type(value) is not bool:
        _fail(label, "must be a JSON boolean")
    return value


def _require_int(
    value: object,
    label: str,
    *,
    minimum: int = 0,
    maximum: int = MAX_SIGNED_INT64,
) -> int:
    if type(value) is not int:
        _fail(label, "must be an integer")
    if value < minimum or value > maximum:
        _fail(label, f"must be in [{minimum}, {maximum}], got {value}")
    return value


def _require_page_dimension(value: object, label: str) -> int:
    dimension = _require_int(
        value,
        label,
        minimum=MIN_PAGE_DIMENSION,
        maximum=MAX_PAGE_DIMENSION,
    )
    if dimension & (dimension - 1):
        _fail(label, "must be a power of two")
    return dimension


def _require_finite_number(
    value: object,
    label: str,
    *,
    minimum: float,
    maximum: float,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(label, "must be a finite number")
    result = float(value)
    if not math.isfinite(result) or result < minimum or result > maximum:
        _fail(label, f"must be finite and in [{minimum}, {maximum}]")
    return result


def _require_sha256(value: object, label: str) -> str:
    digest = _require_string(value, label)
    if _SHA256_RE.fullmatch(digest) is None:
        _fail(label, "must be 64 lowercase hexadecimal characters")
    return digest


def _require_hash128(value: object, label: str) -> str:
    digest = _require_string(value, label)
    if _HASH128_RE.fullmatch(digest) is None:
        _fail(label, "must be 32 lowercase hexadecimal characters")
    return digest


def _require_crc32(value: object, label: str) -> str:
    digest = _require_string(value, label)
    if _CRC32_RE.fullmatch(digest) is None:
        _fail(label, "must be 8 lowercase hexadecimal characters")
    return digest


def _require_group(value: object, label: str) -> str:
    group = _require_string(value, label)
    if _GROUP_RE.fullmatch(group) is None:
        _fail(label, "must be a canonical ASCII GM group identity")
    return group


def _require_slug(value: object, label: str) -> str:
    slug = _require_string(value, label)
    if _SLUG_RE.fullmatch(slug) is None:
        _fail(label, "must be a safe lowercase ASCII slug")
    return slug


def canonical_group_slug(group: object, label: str = "group") -> str:
    """Map one semantic GM identity to its canonical path-safe slug."""

    value = _require_group(group, label)
    slug = value.lower().replace(" ", "_")
    return _require_slug(slug, f"{label} slug")


def canonical_bc7_bundle_name(group: object, label: str = "group") -> str:
    """Return the authoritative BC7 V2 bundle name for one GM identity."""

    return f"sede.gm.{canonical_group_slug(group, label)}.bc7.v2"


def _require_bundle_name(value: object, label: str) -> str:
    bundle = _require_string(value, label)
    if _BUNDLE_RE.fullmatch(bundle) is None:
        _fail(label, "is not a recognized v1 bundle name")
    return bundle


def _require_bc7_bundle_name(value: object, label: str) -> str:
    bundle = _require_string(value, label)
    if _BC7_BUNDLE_RE.fullmatch(bundle) is None:
        _fail(label, "is not a recognized BC7 V2 bundle name")
    return bundle


def _require_frame_name(value: object, label: str) -> str:
    name = _require_string(value, label)
    if "\x00" in name or any(ord(char) < 0x20 for char in name):
        _fail(label, "must not contain NUL or control characters")
    return name


def require_safe_relative_path(value: object, label: str = "path") -> str:
    """Return a canonical POSIX relative path or fail closed."""

    path = _require_string(value, label)
    if "\\" in path or path.startswith("/") or re.match(r"[A-Za-z]:", path):
        _fail(label, "must be a canonical POSIX relative path")
    parts = path.split("/")
    if not parts or any(part in {"", ".", ".."} for part in parts):
        _fail(label, "contains an empty, dot, or parent segment")
    if any("\x00" in part for part in parts):
        _fail(label, "contains NUL")
    return path


def _reject_json_constant(token: str) -> None:
    raise AssetStreamContractError(f"JSON contains forbidden constant {token}")


def _object_without_duplicate_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise AssetStreamContractError(f"JSON contains duplicate key {key!r}")
        result[key] = value
    return result


def canonical_json_bytes(value: object) -> bytes:
    """Serialize a JSON value using the byte contract used by Unity inputs."""

    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise AssetStreamContractError(f"Value is not canonical JSON: {exc}") from exc
    return text.encode("utf-8")


def _ensure_nfc_tree(value: object, label: str) -> None:
    if isinstance(value, str):
        if unicodedata.normalize("NFC", value) != value:
            _fail(label, "contains a non-NFC string")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _ensure_nfc_tree(item, f"{label}[{index}]")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            _ensure_nfc_tree(key, f"{label}.<key>")
            _ensure_nfc_tree(item, f"{label}.{key}")


def _load_canonical_json_file(raw: bytes, label: str, maximum_bytes: int) -> object:
    if not isinstance(raw, bytes):
        _fail(label, "must be supplied as raw bytes so its hash remains provable")
    if not raw or len(raw) > maximum_bytes:
        _fail(label, f"byte size must be in [1, {maximum_bytes}]")
    if raw.startswith(b"\xef\xbb\xbf"):
        _fail(label, "must not contain a UTF-8 BOM")
    if not raw.endswith(b"\n") or raw.endswith(b"\n\n") or b"\r" in raw:
        _fail(label, "must have exactly one LF terminator and no CR characters")
    try:
        text = raw[:-1].decode("utf-8", errors="strict")
        value = json.loads(
            text,
            object_pairs_hook=_object_without_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AssetStreamContractError(f"{label}: invalid strict UTF-8 JSON: {exc}") from exc
    _ensure_nfc_tree(value, label)
    if canonical_json_bytes(value) + b"\n" != raw:
        _fail(label, "bytes are not canonical compact sorted-key JSON")
    return value


def _parse_exact_resource_policy(
    raw: object,
    expected_values: Mapping[str, int | str],
) -> ResourcePolicy:
    policy = _require_mapping(raw, "resource_policy")
    _require_exact_keys(policy, RESOURCE_POLICY_KEYS, "resource_policy")
    for key, expected in expected_values.items():
        actual = policy[key]
        if key == "kind":
            actual = _require_string(actual, f"resource_policy.{key}")
        else:
            actual = _require_int(actual, f"resource_policy.{key}", minimum=1)
        if actual != expected:
            _fail(
                f"resource_policy.{key}",
                f"production value changed; expected {expected!r}, got {actual!r}",
            )
    return ResourcePolicy(**{key: policy[key] for key in expected_values})  # type: ignore[arg-type]


def parse_resource_policy(raw: object) -> ResourcePolicy:
    """Parse the historical V1 policy only; V2 never cross-parses here."""

    return _parse_exact_resource_policy(raw, RESOURCE_POLICY_VALUES)


def parse_bc7_resource_policy(raw: object) -> ResourcePolicy:
    """Parse the exact hard-private, commit-first BC7 V4 policy."""

    return _parse_exact_resource_policy(raw, BC7_RESOURCE_POLICY_VALUES)


def parse_texture_policy(raw: object) -> TexturePolicy:
    """Parse one of the two globally qualified V2 plane-format policies."""

    label = "texture_policy"
    value = _require_mapping(raw, label)
    _require_exact_keys(value, {"id", "main_format", "mask_format"}, label)
    policy_id = _require_string(value["id"], f"{label}.id")
    main_format = _require_string(value["main_format"], f"{label}.main_format")
    mask_format = _require_string(value["mask_format"], f"{label}.mask_format")
    expected = BC7_TEXTURE_POLICY_VALUES.get(policy_id)
    if expected is None:
        _fail(f"{label}.id", f"unsupported global policy {policy_id!r}")
    if (main_format, mask_format) != expected:
        _fail(
            label,
            f"policy {policy_id!r} requires main/mask formats {expected!r}, "
            f"got {(main_format, mask_format)!r}",
        )
    return TexturePolicy(policy_id, main_format, mask_format)


def parse_quality_policy(raw: object) -> QualityPolicy:
    """Parse the explicit V2 quality state and its portable verifier binding."""

    label = "quality_policy"
    value = _require_mapping(raw, label)
    _require_exact_keys(value, {"state", "id", "sha256", "verifier_id"}, label)
    state = _require_string(value["state"], f"{label}.state")
    if state not in BC7_QUALITY_STATES:
        _fail(f"{label}.state", f"must be one of {sorted(BC7_QUALITY_STATES)!r}")
    policy_id = _require_slug(value["id"], f"{label}.id")
    sha256 = _require_sha256(value["sha256"], f"{label}.sha256")
    verifier_id = _require_string(value["verifier_id"], f"{label}.verifier_id")
    if verifier_id != BC7_QUALITY_VERIFIER_ID:
        _fail(
            f"{label}.verifier_id",
            f"must be the pinned verifier {BC7_QUALITY_VERIFIER_ID!r}",
        )
    if state == "measurement_nonpromotable":
        expected_identity = (
            BC7_MEASUREMENT_QUALITY_POLICY_ID,
            BC7_MEASUREMENT_QUALITY_POLICY_SHA256,
        )
        if (policy_id, sha256) != expected_identity:
            _fail(
                label,
                "measurement_nonpromotable requires the canonical measurement "
                "policy id/SHA256",
            )
    elif policy_id != BC7_FROZEN_QUALITY_POLICY_ID:
        _fail(
            f"{label}.id",
            f"frozen policy id must be {BC7_FROZEN_QUALITY_POLICY_ID!r}",
        )
    return QualityPolicy(state, policy_id, sha256, verifier_id)


def parse_atlas_backend_block(raw: object, *, runtime_enabled: bool) -> AtlasBackend:
    if type(runtime_enabled) is not bool:
        _fail("runtime_enabled", "must be a boolean")
    backend = _require_mapping(raw, "atlas_backend")
    if "kind" not in backend:
        _fail("atlas_backend", "key set changed; missing=['kind'], extra=[]")
    kind = _require_string(backend.get("kind"), "atlas_backend.kind")
    if kind == ATLAS_BACKEND_KIND:
        _require_exact_keys(backend, {"kind", "resource_policy"}, "atlas_backend")
        resource_policy = parse_resource_policy(backend["resource_policy"])
        texture_policy = None
        quality_policy = None
    elif kind == BC7_ATLAS_BACKEND_KIND:
        _require_exact_keys(
            backend,
            {"kind", "resource_policy", "texture_policy", "quality_policy"},
            "atlas_backend",
        )
        resource_policy = parse_bc7_resource_policy(backend["resource_policy"])
        texture_policy = parse_texture_policy(backend["texture_policy"])
        quality_policy = parse_quality_policy(backend["quality_policy"])
    else:
        _fail("atlas_backend.kind", f"unsupported backend {kind!r}")
    if not runtime_enabled:
        _fail("atlas_backend", "requires runtime.enabled=true")
    return AtlasBackend(
        kind=kind,
        resource_policy=resource_policy,
        texture_policy=texture_policy,
        quality_policy=quality_policy,
    )


def parse_atlas_backend(profile: Mapping[str, object]) -> AtlasBackend | None:
    """Parse the optional profile block and enforce its runtime dependency."""

    if "atlas_backend" not in profile:
        return None
    runtime = _require_mapping(profile.get("runtime"), "runtime")
    runtime_enabled = runtime.get("enabled")
    if type(runtime_enabled) is not bool:
        _fail("runtime.enabled", "must be a boolean when atlas_backend is present")
    return parse_atlas_backend_block(
        profile["atlas_backend"], runtime_enabled=runtime_enabled
    )


def align_up(value: int, alignment: int = RESOURCE_ALIGNMENT_BYTES) -> int:
    value = _require_int(value, "value")
    alignment = _require_int(alignment, "alignment", minimum=1)
    result = ((value + alignment - 1) // alignment) * alignment
    if result > MAX_SIGNED_INT64:
        _fail("aligned value", "overflows signed 64-bit accounting")
    return result


def calculate_resident_charge(raw_rgba_bytes: int) -> int:
    """Charge decoded RGBA plus 12.5%, rounded to the next 64 MiB."""

    raw = _require_int(raw_rgba_bytes, "raw_rgba_bytes", minimum=1)
    adjusted = (raw * 9 + 7) // 8
    charge = align_up(adjusted)
    if charge > MAX_SIGNED_INT64:
        _fail("resident charge", "overflows signed 64-bit accounting")
    return charge


def calculate_peak_admission_bytes(charge_bytes: int, bundle_file_bytes: int) -> int:
    """Return the conservative one-group upload peak used by admission."""

    charge = _require_int(charge_bytes, "charge_bytes", minimum=1)
    bundle = _require_int(bundle_file_bytes, "bundle_file_bytes", minimum=1)
    peak = 2 * charge + align_up(bundle) + UPLOAD_FIXED_OVERHEAD_BYTES
    if peak > MAX_SIGNED_INT64:
        _fail("peak admission", "overflows signed 64-bit accounting")
    return peak


def calculate_texture_gpu_bytes(width: int, height: int, texture_format: str) -> int:
    """Return the exact resident plane payload for a qualified V2 format.

    BC7 stores one 16-byte block for every 4x4 block footprint, including
    partial edge blocks.  RGBA32 stores four bytes per pixel.  No inferred or
    platform-dependent format is accepted.
    """

    width_value = _require_int(width, "width", minimum=1)
    height_value = _require_int(height, "height", minimum=1)
    format_value = _require_string(texture_format, "texture_format")
    if format_value == "BC7":
        result = ((width_value + 3) // 4) * ((height_value + 3) // 4) * 16
    elif format_value == "RGBA32":
        result = width_value * height_value * 4
    else:
        _fail("texture_format", "must be exactly 'BC7' or 'RGBA32'")
    if result > MAX_SIGNED_INT64:
        _fail("texture gpu bytes", "overflows signed 64-bit accounting")
    return result


def calculate_page_gpu_bytes(
    width: int,
    height: int,
    *,
    main_format: str,
    mask_format: str | None,
) -> int:
    """Sum a page's explicit main and optional mask plane payloads."""

    total = calculate_texture_gpu_bytes(width, height, main_format)
    if mask_format is not None:
        total += calculate_texture_gpu_bytes(width, height, mask_format)
    if total > MAX_SIGNED_INT64:
        _fail("page gpu bytes", "overflows signed 64-bit accounting")
    return total


def calculate_bc7_group_resident_charge(gpu_bytes: int) -> int:
    """Apply 9/8 overhead and one 4-MiB alignment to the complete group."""

    gpu = _require_int(gpu_bytes, "gpu_bytes", minimum=1)
    adjusted = (gpu * 9 + 7) // 8
    charge = align_up(adjusted, BC7_GROUP_RESIDENT_ALIGNMENT_BYTES)
    if charge > MAX_SIGNED_INT64:
        _fail("BC7 group resident charge", "overflows signed 64-bit accounting")
    return charge


def calculate_bc7_peak_admission_bytes(
    resident_charge_bytes: int,
    bundle_file_bytes: int,
) -> int:
    """Return ``2*charge + align64MiB(bundle) + 256MiB`` for V2."""

    charge = _require_int(
        resident_charge_bytes, "resident_charge_bytes", minimum=1
    )
    bundle = _require_int(bundle_file_bytes, "bundle_file_bytes", minimum=1)
    peak = (
        2 * charge
        + align_up(bundle, BC7_BUNDLE_ALIGNMENT_BYTES)
        + UPLOAD_FIXED_OVERHEAD_BYTES
    )
    if peak > MAX_SIGNED_INT64:
        _fail("BC7 peak admission", "overflows signed 64-bit accounting")
    return peak


# Explicit V2 aliases for callers that name the schema generation rather than
# the encoding.  Both resolve to the exact functions above.
calculate_v2_resident_charge = calculate_bc7_group_resident_charge
calculate_v2_peak_admission_bytes = calculate_bc7_peak_admission_bytes


def decide_admission(
    policy: ResourcePolicy,
    usage: ResourceUsage,
    snapshot: ResourceSnapshot,
    *,
    raw_rgba_bytes: int,
    bundle_file_bytes: int,
) -> AdmissionDecision:
    """Decide whether one GM group may load; every rejection means vanilla."""

    if policy != parse_resource_policy(
        {
            "kind": policy.kind,
            "additional_gm_resident_bytes": policy.additional_gm_resident_bytes,
            "ui_resident_bytes": policy.ui_resident_bytes,
            "audio_stream_bytes": policy.audio_stream_bytes,
            "process_private_ceiling_bytes": policy.process_private_ceiling_bytes,
            "global_commit_reserve_bytes": policy.global_commit_reserve_bytes,
            "minimum_free_physical_bytes": policy.minimum_free_physical_bytes,
            "peak_admission_bytes": policy.peak_admission_bytes,
        }
    ):
        _fail("resource policy", "dataclass did not survive exact validation")
    gm_used = _require_int(usage.gm_resident_charge_bytes, "usage.gm_resident_charge_bytes")
    ui_used = _require_int(usage.ui_resident_bytes, "usage.ui_resident_bytes")
    audio_used = _require_int(usage.audio_stream_bytes, "usage.audio_stream_bytes")
    in_flight = _require_bool(usage.load_in_flight, "usage.load_in_flight")
    charge = calculate_resident_charge(raw_rgba_bytes)
    peak = calculate_peak_admission_bytes(charge, bundle_file_bytes)

    def reject(reason: AdmissionReason) -> AdmissionDecision:
        return AdmissionDecision(False, reason, charge, peak)

    if in_flight:
        return reject(AdmissionReason.LOAD_ALREADY_IN_FLIGHT)
    if ui_used > policy.ui_resident_bytes:
        return reject(AdmissionReason.UI_BUDGET_EXCEEDED)
    if audio_used > policy.audio_stream_bytes:
        return reject(AdmissionReason.AUDIO_BUDGET_EXCEEDED)
    if gm_used + charge > policy.additional_gm_resident_bytes:
        return reject(AdmissionReason.GM_BUDGET_EXCEEDED)
    if peak > policy.peak_admission_bytes:
        return reject(AdmissionReason.PEAK_BUDGET_EXCEEDED)

    counters = (
        snapshot.process_private_bytes,
        snapshot.global_available_commit_bytes,
        snapshot.available_physical_bytes,
    )
    if any(value is None for value in counters):
        return reject(AdmissionReason.METRIC_UNAVAILABLE)
    process_private = _require_int(counters[0], "snapshot.process_private_bytes")
    if process_private == 0:
        return reject(AdmissionReason.METRIC_UNAVAILABLE)
    available_commit = _require_int(
        counters[1], "snapshot.global_available_commit_bytes"
    )
    available_physical = _require_int(
        counters[2], "snapshot.available_physical_bytes"
    )
    if process_private + peak > policy.process_private_ceiling_bytes:
        return reject(AdmissionReason.PROCESS_PRIVATE_CEILING)
    if available_commit < policy.global_commit_reserve_bytes + peak:
        return reject(AdmissionReason.GLOBAL_COMMIT_RESERVE)
    if available_physical < policy.minimum_free_physical_bytes + peak:
        return reject(AdmissionReason.MINIMUM_FREE_PHYSICAL)
    return AdmissionDecision(True, AdmissionReason.ADMITTED, charge, peak)


def decide_bc7_admission(
    policy: ResourcePolicy,
    usage: ResourceUsage,
    snapshot: ResourceSnapshot,
    *,
    gpu_bytes: int,
    bundle_file_bytes: int,
) -> AdmissionDecision:
    """Apply the exact hard-private, commit-first BC7 V4 admission contract.

    The transient peak is charged against process-private memory and available
    commit.  Available physical memory is deliberately an absolute emergency
    floor: adding the peak to that floor would double-charge shared-GPU memory
    and reproduces the production failure this policy replaces.
    """

    if policy != parse_bc7_resource_policy(
        {
            "kind": policy.kind,
            "additional_gm_resident_bytes": policy.additional_gm_resident_bytes,
            "ui_resident_bytes": policy.ui_resident_bytes,
            "audio_stream_bytes": policy.audio_stream_bytes,
            "process_private_ceiling_bytes": policy.process_private_ceiling_bytes,
            "global_commit_reserve_bytes": policy.global_commit_reserve_bytes,
            "minimum_free_physical_bytes": policy.minimum_free_physical_bytes,
            "peak_admission_bytes": policy.peak_admission_bytes,
        }
    ):
        _fail("BC7 resource policy", "dataclass did not survive exact validation")
    gm_used = _require_int(
        usage.gm_resident_charge_bytes, "usage.gm_resident_charge_bytes"
    )
    ui_used = _require_int(usage.ui_resident_bytes, "usage.ui_resident_bytes")
    audio_used = _require_int(
        usage.audio_stream_bytes, "usage.audio_stream_bytes"
    )
    in_flight = _require_bool(usage.load_in_flight, "usage.load_in_flight")
    charge = calculate_bc7_group_resident_charge(gpu_bytes)
    peak = calculate_bc7_peak_admission_bytes(charge, bundle_file_bytes)

    def reject(reason: AdmissionReason) -> AdmissionDecision:
        return AdmissionDecision(False, reason, charge, peak)

    if in_flight:
        return reject(AdmissionReason.LOAD_ALREADY_IN_FLIGHT)
    if ui_used > policy.ui_resident_bytes:
        return reject(AdmissionReason.UI_BUDGET_EXCEEDED)
    if audio_used > policy.audio_stream_bytes:
        return reject(AdmissionReason.AUDIO_BUDGET_EXCEEDED)
    if gm_used + charge > policy.additional_gm_resident_bytes:
        return reject(AdmissionReason.GM_BUDGET_EXCEEDED)
    if peak > policy.peak_admission_bytes:
        return reject(AdmissionReason.PEAK_BUDGET_EXCEEDED)

    counters = (
        snapshot.process_private_bytes,
        snapshot.global_available_commit_bytes,
        snapshot.available_physical_bytes,
    )
    if any(value is None for value in counters):
        return reject(AdmissionReason.METRIC_UNAVAILABLE)
    process_private = _require_int(
        counters[0], "snapshot.process_private_bytes"
    )
    if process_private == 0:
        return reject(AdmissionReason.METRIC_UNAVAILABLE)
    available_commit = _require_int(
        counters[1], "snapshot.global_available_commit_bytes"
    )
    available_physical = _require_int(
        counters[2], "snapshot.available_physical_bytes"
    )
    if process_private + peak > policy.process_private_ceiling_bytes:
        return reject(AdmissionReason.PROCESS_PRIVATE_CEILING)
    if available_commit < policy.global_commit_reserve_bytes + peak:
        return reject(AdmissionReason.GLOBAL_COMMIT_RESERVE)
    if available_physical < policy.minimum_free_physical_bytes:
        return reject(AdmissionReason.MINIMUM_FREE_PHYSICAL)
    return AdmissionDecision(True, AdmissionReason.ADMITTED, charge, peak)


def _parse_unity_identity(raw: object, label: str) -> UnityIdentity:
    value = _require_mapping(raw, label)
    _require_exact_keys(value, {"version", "revision"}, label)
    version = _require_string(value["version"], f"{label}.version")
    revision = _require_string(value["revision"], f"{label}.revision")
    if (version, revision) != (UNITY_VERSION, UNITY_REVISION):
        _fail(label, f"must be exact Unity {UNITY_VERSION} revision {UNITY_REVISION}")
    return UnityIdentity(version, revision)


def _parse_texture_contract(raw: object, label: str) -> TextureContract:
    value = _require_mapping(raw, label)
    _require_exact_keys(value, _TEXTURE_KEYS, label)
    parsed: dict[str, object] = {}
    for key, expected in _TEXTURE_CONTRACT_VALUES.items():
        actual = value[key]
        if isinstance(expected, bool):
            actual = _require_bool(actual, f"{label}.{key}")
        else:
            actual = _require_string(actual, f"{label}.{key}")
        if actual != expected:
            _fail(f"{label}.{key}", f"expected {expected!r}, got {actual!r}")
        parsed[key] = actual
    return TextureContract(**parsed)  # type: ignore[arg-type]


def _parse_page_texture(raw: object, label: str) -> PageTexture:
    value = _require_mapping(raw, label)
    _require_exact_keys(
        value, {"asset_path", "address", "png_sha256", "rgba_sha256"}, label
    )
    return PageTexture(
        asset_path=require_safe_relative_path(value["asset_path"], f"{label}.asset_path"),
        address=require_safe_relative_path(value["address"], f"{label}.address"),
        png_sha256=_require_sha256(value["png_sha256"], f"{label}.png_sha256"),
        rgba_sha256=_require_sha256(value["rgba_sha256"], f"{label}.rgba_sha256"),
    )


def _parse_rect(raw: object, label: str) -> FrameRect:
    value = _require_mapping(raw, label)
    _require_exact_keys(value, {"x", "y", "width", "height"}, label)
    return FrameRect(
        x=_require_int(value["x"], f"{label}.x"),
        y=_require_int(value["y"], f"{label}.y"),
        width=_require_int(value["width"], f"{label}.width", minimum=1),
        height=_require_int(value["height"], f"{label}.height", minimum=1),
    )


def _parse_pivot(raw: object, label: str) -> FramePivot:
    value = _require_mapping(raw, label)
    _require_exact_keys(value, {"x", "y"}, label)
    return FramePivot(
        x=_require_finite_number(
            value["x"],
            f"{label}.x",
            minimum=-MAX_ABSOLUTE_SPRITE_PIVOT,
            maximum=MAX_ABSOLUTE_SPRITE_PIVOT,
        ),
        y=_require_finite_number(
            value["y"],
            f"{label}.y",
            minimum=-MAX_ABSOLUTE_SPRITE_PIVOT,
            maximum=MAX_ABSOLUTE_SPRITE_PIVOT,
        ),
    )


def _parse_frame(raw: object, label: str, mask_required: bool) -> AtlasFrame:
    value = _require_mapping(raw, label)
    _require_exact_keys(
        value,
        {
            "name",
            "index",
            "alt",
            "page",
            "rect",
            "pivot",
            "pixels_per_unit",
            "main_rgba_sha256",
            "mask_rgba_sha256",
        },
        label,
    )
    mask_value = value["mask_rgba_sha256"]
    if mask_required:
        mask_sha = _require_sha256(mask_value, f"{label}.mask_rgba_sha256")
    else:
        if mask_value is not None:
            _fail(f"{label}.mask_rgba_sha256", "must be null for forbidden masks")
        mask_sha = None
    return AtlasFrame(
        name=_require_frame_name(value["name"], f"{label}.name"),
        index=_require_int(value["index"], f"{label}.index", maximum=2_000_000_000),
        alt=_require_bool(value["alt"], f"{label}.alt"),
        page=_require_int(value["page"], f"{label}.page", maximum=MAX_PAGES_PER_GROUP - 1),
        rect=_parse_rect(value["rect"], f"{label}.rect"),
        pivot=_parse_pivot(value["pivot"], f"{label}.pivot"),
        pixels_per_unit=_require_finite_number(
            value["pixels_per_unit"],
            f"{label}.pixels_per_unit",
            minimum=1 / 1024,
            maximum=4096,
        ),
        main_rgba_sha256=_require_sha256(
            value["main_rgba_sha256"], f"{label}.main_rgba_sha256"
        ),
        mask_rgba_sha256=mask_sha,
    )


def _rectangles_overlap(left: FrameRect, right: FrameRect) -> bool:
    return not (
        left.x + left.width <= right.x
        or right.x + right.width <= left.x
        or left.y + left.height <= right.y
        or right.y + right.height <= left.y
    )


def _validate_frame_rectangles(
    pages: Sequence[AtlasPage], frames: Sequence[AtlasFrame], padding: int, label: str
) -> None:
    buckets: dict[tuple[int, int, int], list[int]] = {}
    representative_by_rect: dict[tuple[int, int, int, int, int], int] = {}
    bucket_size = 64
    for frame_number, frame in enumerate(frames):
        page = pages[frame.page]
        rect = frame.rect
        padded = FrameRect(
            rect.x - padding,
            rect.y - padding,
            rect.width + 2 * padding,
            rect.height + 2 * padding,
        )
        if (
            padded.x < 0
            or padded.y < 0
            or padded.x + padded.width > page.width
            or padded.y + padded.height > page.height
        ):
            _fail(
                f"{label}.frames[{frame_number}].rect",
                f"is outside page {frame.page} after {padding}px edge padding",
            )
        rect_key = (frame.page, rect.x, rect.y, rect.width, rect.height)
        representative_number = representative_by_rect.get(rect_key)
        if representative_number is not None:
            representative = frames[representative_number]
            if (
                frame.main_rgba_sha256 != representative.main_rgba_sha256
                or frame.mask_rgba_sha256 != representative.mask_rgba_sha256
            ):
                _fail(
                    f"{label}.frames[{frame_number}].rect",
                    "shares an atlas rectangle without identical main/mask RGBA digests",
                )
            continue
        x0 = padded.x // bucket_size
        x1 = (padded.x + padded.width - 1) // bucket_size
        y0 = padded.y // bucket_size
        y1 = (padded.y + padded.height - 1) // bucket_size
        candidates: set[int] = set()
        for bucket_x in range(x0, x1 + 1):
            for bucket_y in range(y0, y1 + 1):
                candidates.update(buckets.get((frame.page, bucket_x, bucket_y), ()))
        for other_number in candidates:
            other = frames[other_number]
            other_padded = FrameRect(
                other.rect.x - padding,
                other.rect.y - padding,
                other.rect.width + 2 * padding,
                other.rect.height + 2 * padding,
            )
            if _rectangles_overlap(padded, other_padded):
                _fail(
                    f"{label}.frames[{frame_number}].rect",
                    f"overlaps the padded allocation of frame {other.name!r} "
                    f"on page {frame.page}",
                )
        for bucket_x in range(x0, x1 + 1):
            for bucket_y in range(y0, y1 + 1):
                buckets.setdefault((frame.page, bucket_x, bucket_y), []).append(
                    frame_number
                )
        representative_by_rect[rect_key] = frame_number


def _parse_texture_contract_v2(
    raw: object,
    label: str,
) -> TextureContractV2:
    value = _require_mapping(raw, label)
    _require_exact_keys(value, _TEXTURE_CONTRACT_V2_KEYS, label)
    allows_alpha_splitting = _require_bool(
        value["allows_alpha_splitting"], f"{label}.allows_alpha_splitting"
    )
    alpha_is_transparency = _require_bool(
        value["alpha_is_transparency"], f"{label}.alpha_is_transparency"
    )
    alpha_source = _require_string(value["alpha_source"], f"{label}.alpha_source")
    aniso_level = _require_int(
        value["aniso_level"], f"{label}.aniso_level", maximum=16
    )
    compression = _require_string(value["compression"], f"{label}.compression")
    compression_quality = _require_int(
        value["compression_quality"],
        f"{label}.compression_quality",
        maximum=100,
    )
    crunched_compression = _require_bool(
        value["crunched_compression"], f"{label}.crunched_compression"
    )
    filter_mode = _require_string(value["filter_mode"], f"{label}.filter_mode")
    force_maximum = _require_bool(
        value["force_maximum_compression_quality_bc6h_bc7"],
        f"{label}.force_maximum_compression_quality_bc6h_bc7",
    )
    texture_format = _require_string(value["format"], f"{label}.format")
    if texture_format not in {"BC7", "RGBA32"}:
        _fail(f"{label}.format", "must be exactly 'BC7' or 'RGBA32'")
    gpu_block_bytes = _require_int(
        value["gpu_block_bytes"], f"{label}.gpu_block_bytes", minimum=1
    )
    gpu_block_height = _require_int(
        value["gpu_block_height"], f"{label}.gpu_block_height", minimum=1
    )
    gpu_block_width = _require_int(
        value["gpu_block_width"], f"{label}.gpu_block_width", minimum=1
    )
    ignore_png_gamma = _require_bool(
        value["ignore_png_gamma"], f"{label}.ignore_png_gamma"
    )
    max_texture_size = _require_int(
        value["max_texture_size"], f"{label}.max_texture_size", minimum=1
    )
    mipmaps = _require_bool(value["mipmaps"], f"{label}.mipmaps")
    npot_scale = _require_string(value["npot_scale"], f"{label}.npot_scale")
    platform_override = _require_bool(
        value["platform_override"], f"{label}.platform_override"
    )
    readable = _require_bool(value["readable"], f"{label}.readable")
    s_rgb = _require_bool(value["s_rgb"], f"{label}.s_rgb")
    streaming_mipmaps = _require_bool(
        value["streaming_mipmaps"], f"{label}.streaming_mipmaps"
    )
    texture_type = _require_string(value["texture_type"], f"{label}.texture_type")
    unity_texture_format = _require_int(
        value["unity_texture_format"], f"{label}.unity_texture_format"
    )
    wrap_mode = _require_string(value["wrap_mode"], f"{label}.wrap_mode")
    common = (
        allows_alpha_splitting is False
        and alpha_is_transparency is False
        and alpha_source == "FromInput"
        and aniso_level == 0
        and compression_quality == 100
        and crunched_compression is False
        and filter_mode in {"Point", "Bilinear"}
        and ignore_png_gamma is True
        and max_texture_size == MAX_PAGE_DIMENSION
        and mipmaps is False
        and npot_scale == "None"
        and platform_override is True
        and readable is False
        and s_rgb is True
        and streaming_mipmaps is False
        and texture_type == "Default"
        and wrap_mode == "Clamp"
    )
    if texture_format == "BC7":
        format_specific = (
            compression == "CompressedHQ"
            and force_maximum is True
            and gpu_block_bytes == 16
            and gpu_block_height == 4
            and gpu_block_width == 4
            and unity_texture_format == 25
        )
    else:
        format_specific = (
            compression == "Uncompressed"
            and force_maximum is False
            and gpu_block_bytes == 4
            and gpu_block_height == 1
            and gpu_block_width == 1
            and unity_texture_format == 4
        )
    if not common or not format_specific:
        _fail(label, f"does not match the qualified {texture_format} import contract")
    return TextureContractV2(
        allows_alpha_splitting=allows_alpha_splitting,
        alpha_is_transparency=alpha_is_transparency,
        alpha_source=alpha_source,
        aniso_level=aniso_level,
        compression=compression,
        compression_quality=compression_quality,
        crunched_compression=crunched_compression,
        filter_mode=filter_mode,
        force_maximum_compression_quality_bc6h_bc7=force_maximum,
        format=texture_format,
        gpu_block_bytes=gpu_block_bytes,
        gpu_block_height=gpu_block_height,
        gpu_block_width=gpu_block_width,
        ignore_png_gamma=ignore_png_gamma,
        max_texture_size=max_texture_size,
        mipmaps=mipmaps,
        npot_scale=npot_scale,
        platform_override=platform_override,
        readable=readable,
        s_rgb=s_rgb,
        streaming_mipmaps=streaming_mipmaps,
        texture_type=texture_type,
        unity_texture_format=unity_texture_format,
        wrap_mode=wrap_mode,
    )


def _parse_page_texture_v2(
    raw: object,
    label: str,
    *,
    width: int,
    height: int,
    expected_format: str,
) -> PageTextureV2:
    value = _require_mapping(raw, label)
    _require_exact_keys(
        value,
        {
            "address",
            "asset_path",
            "format",
            "gpu_bytes",
            "source_png_sha256",
            "source_rgba_bytes",
            "source_rgba_sha256",
        },
        label,
    )
    texture_format = _require_string(value["format"], f"{label}.format")
    if texture_format != expected_format:
        _fail(
            f"{label}.format",
            f"expected global plane format {expected_format!r}, got {texture_format!r}",
        )
    gpu_bytes = _require_int(value["gpu_bytes"], f"{label}.gpu_bytes", minimum=1)
    expected_gpu_bytes = calculate_texture_gpu_bytes(width, height, texture_format)
    if gpu_bytes != expected_gpu_bytes:
        _fail(
            f"{label}.gpu_bytes",
            f"expected exact {texture_format} payload {expected_gpu_bytes}, got {gpu_bytes}",
        )
    source_rgba_bytes = _require_int(
        value["source_rgba_bytes"], f"{label}.source_rgba_bytes", minimum=1
    )
    expected_source_rgba_bytes = width * height * 4
    if source_rgba_bytes != expected_source_rgba_bytes:
        _fail(
            f"{label}.source_rgba_bytes",
            f"expected exact RGBA source payload {expected_source_rgba_bytes}, "
            f"got {source_rgba_bytes}",
        )
    return PageTextureV2(
        asset_path=require_safe_relative_path(
            value["asset_path"], f"{label}.asset_path"
        ),
        address=require_safe_relative_path(value["address"], f"{label}.address"),
        format=texture_format,
        gpu_bytes=gpu_bytes,
        source_png_sha256=_require_sha256(
            value["source_png_sha256"], f"{label}.source_png_sha256"
        ),
        source_rgba_bytes=source_rgba_bytes,
        source_rgba_sha256=_require_sha256(
            value["source_rgba_sha256"], f"{label}.source_rgba_sha256"
        ),
    )


def _parse_frame_v3(raw: object, label: str, mask_required: bool) -> AtlasFrameV3:
    value = _require_mapping(raw, label)
    _require_exact_keys(
        value,
        {
            "alt",
            "index",
            "main_source_rgba_sha256",
            "mask_source_rgba_sha256",
            "name",
            "page",
            "pixels_per_unit",
            "pivot",
            "rect",
            "storage_cell",
        },
        label,
    )
    mask_raw = value["mask_source_rgba_sha256"]
    if mask_required:
        mask_sha = _require_sha256(
            mask_raw, f"{label}.mask_source_rgba_sha256"
        )
    else:
        if mask_raw is not None:
            _fail(
                f"{label}.mask_source_rgba_sha256",
                "must be null for forbidden masks",
            )
        mask_sha = None
    return AtlasFrameV3(
        name=_require_frame_name(value["name"], f"{label}.name"),
        index=_require_int(
            value["index"], f"{label}.index", maximum=MAX_PREFLIGHT_ARRAY_SIZE
        ),
        alt=_require_bool(value["alt"], f"{label}.alt"),
        page=_require_int(
            value["page"],
            f"{label}.page",
            maximum=BC7_MAX_PAGES_PER_GROUP - 1,
        ),
        rect=_parse_rect(value["rect"], f"{label}.rect"),
        storage_cell=_parse_rect(value["storage_cell"], f"{label}.storage_cell"),
        pivot=_parse_pivot(value["pivot"], f"{label}.pivot"),
        pixels_per_unit=_require_finite_number(
            value["pixels_per_unit"],
            f"{label}.pixels_per_unit",
            minimum=1 / 1024,
            maximum=4096,
        ),
        main_source_rgba_sha256=_require_sha256(
            value["main_source_rgba_sha256"],
            f"{label}.main_source_rgba_sha256",
        ),
        mask_source_rgba_sha256=mask_sha,
    )


def _validate_v3_storage_cells(
    pages: Sequence[AtlasPageV3],
    frames: Sequence[AtlasFrameV3],
    label: str,
) -> None:
    buckets: dict[tuple[int, int, int], list[int]] = {}
    representatives: dict[tuple[int, int, int, int, int], int] = {}
    bucket_size = 64
    for ordinal, frame in enumerate(frames):
        page = pages[frame.page]
        rect = frame.rect
        cell = frame.storage_cell
        if (
            cell.x % BC7_BLOCK_ALIGNMENT_PIXELS
            or cell.y % BC7_BLOCK_ALIGNMENT_PIXELS
            or cell.width % BC7_BLOCK_ALIGNMENT_PIXELS
            or cell.height % BC7_BLOCK_ALIGNMENT_PIXELS
        ):
            _fail(
                f"{label}.frames[{ordinal}].storage_cell",
                "origin and dimensions must be aligned to the 4x4 BC7 block grid",
            )
        expected_cell_width = align_up(
            rect.width + 2 * BC7_MINIMUM_BORDER_PIXELS,
            BC7_BLOCK_ALIGNMENT_PIXELS,
        )
        expected_cell_height = align_up(
            rect.height + 2 * BC7_MINIMUM_BORDER_PIXELS,
            BC7_BLOCK_ALIGNMENT_PIXELS,
        )
        if (
            rect.x != cell.x + BC7_MINIMUM_BORDER_PIXELS
            or rect.y
            != cell.y
            + cell.height
            - rect.height
            - BC7_MINIMUM_BORDER_PIXELS
            or cell.width != expected_cell_width
            or cell.height != expected_cell_height
        ):
            _fail(
                f"{label}.frames[{ordinal}].storage_cell",
                "must be the minimal 4x4-aligned cell with 1px left/top borders",
            )
        if (
            cell.x + cell.width > page.width
            or cell.y + cell.height > page.height
        ):
            _fail(
                f"{label}.frames[{ordinal}].storage_cell",
                f"is outside page {frame.page}",
            )
        key = (frame.page, cell.x, cell.y, cell.width, cell.height)
        representative_number = representatives.get(key)
        if representative_number is not None:
            representative = frames[representative_number]
            if (
                frame.rect != representative.rect
                or frame.main_source_rgba_sha256
                != representative.main_source_rgba_sha256
                or frame.mask_source_rgba_sha256
                != representative.mask_source_rgba_sha256
            ):
                _fail(
                    f"{label}.frames[{ordinal}].storage_cell",
                    "is shared without identical geometry and main/mask RGBA digests",
                )
            continue
        x0 = cell.x // bucket_size
        x1 = (cell.x + cell.width - 1) // bucket_size
        y0 = cell.y // bucket_size
        y1 = (cell.y + cell.height - 1) // bucket_size
        candidates: set[int] = set()
        for bucket_x in range(x0, x1 + 1):
            for bucket_y in range(y0, y1 + 1):
                candidates.update(buckets.get((frame.page, bucket_x, bucket_y), ()))
        for other_number in candidates:
            if _rectangles_overlap(cell, frames[other_number].storage_cell):
                _fail(
                    f"{label}.frames[{ordinal}].storage_cell",
                    f"shares BC7 blocks with frame {frames[other_number].name!r}",
                )
        for bucket_x in range(x0, x1 + 1):
            for bucket_y in range(y0, y1 + 1):
                buckets.setdefault((frame.page, bucket_x, bucket_y), []).append(ordinal)
        representatives[key] = ordinal


def parse_atlas_v3(raw: bytes, *, label: str = "atlas.v3.json") -> AtlasV3:
    """Parse a canonical block-isolated BC7 atlas contract."""

    data = _require_mapping(_load_canonical_json_file(raw, label, MAX_ATLAS_BYTES), label)
    _require_exact_keys(
        data,
        {
            "block_alignment_pixels",
            "bundle",
            "coordinate_system",
            "extrusion_mode",
            "frames",
            "frames_sha256",
            "group",
            "mask_policy",
            "material_binding",
            "max_page_dimension",
            "minimum_border_pixels",
            "pages",
            "schema",
            "slug",
            "texture_contracts",
        },
        label,
    )
    schema = _require_string(data["schema"], f"{label}.schema")
    if schema != BC7_ATLAS_SCHEMA:
        _fail(f"{label}.schema", f"expected {BC7_ATLAS_SCHEMA!r}")
    group = _require_group(data["group"], f"{label}.group")
    slug = _require_slug(data["slug"], f"{label}.slug")
    if slug != canonical_group_slug(group, f"{label}.group"):
        _fail(f"{label}.slug", "does not equal the canonical group slug")
    bundle = _require_bc7_bundle_name(data["bundle"], f"{label}.bundle")
    expected_bundle = f"sede.gm.{slug}{BC7_BUNDLE_SUFFIX}"
    if bundle != expected_bundle:
        _fail(f"{label}.bundle", f"must be {expected_bundle!r}")
    mask_policy = _require_string(data["mask_policy"], f"{label}.mask_policy")
    if mask_policy not in {"required", "forbidden"}:
        _fail(f"{label}.mask_policy", "must be 'required' or 'forbidden'")
    material_binding = _require_string(
        data["material_binding"], f"{label}.material_binding"
    )
    expected_binding = expected_material_binding(group, mask_policy)
    if material_binding != expected_binding:
        _fail(f"{label}.material_binding", f"must be {expected_binding!r}")
    coordinate_system = _require_string(
        data["coordinate_system"], f"{label}.coordinate_system"
    )
    if coordinate_system != "unity_bottom_left":
        _fail(f"{label}.coordinate_system", "must be 'unity_bottom_left'")
    extrusion_mode = _require_string(
        data["extrusion_mode"], f"{label}.extrusion_mode"
    )
    if extrusion_mode != BC7_EXTRUSION_MODE:
        _fail(f"{label}.extrusion_mode", f"must be {BC7_EXTRUSION_MODE!r}")
    border = _require_int(
        data["minimum_border_pixels"], f"{label}.minimum_border_pixels"
    )
    if border != BC7_MINIMUM_BORDER_PIXELS:
        _fail(f"{label}.minimum_border_pixels", "must be exactly 1")
    block_alignment = _require_int(
        data["block_alignment_pixels"], f"{label}.block_alignment_pixels"
    )
    if block_alignment != BC7_BLOCK_ALIGNMENT_PIXELS:
        _fail(f"{label}.block_alignment_pixels", "must be exactly 4")
    max_dimension = _require_int(
        data["max_page_dimension"], f"{label}.max_page_dimension", minimum=1
    )
    if max_dimension != MAX_PAGE_DIMENSION:
        _fail(f"{label}.max_page_dimension", f"must be {MAX_PAGE_DIMENSION}")

    contracts = _require_mapping(data["texture_contracts"], f"{label}.texture_contracts")
    _require_exact_keys(contracts, {"main", "mask"}, f"{label}.texture_contracts")
    main_contract = _parse_texture_contract_v2(
        contracts["main"], f"{label}.texture_contracts.main"
    )
    if main_contract.format != "BC7":
        _fail(
            f"{label}.texture_contracts.main.format",
            "V2 main textures must use BC7",
        )
    if mask_policy == "required":
        if contracts["mask"] is None:
            _fail(f"{label}.texture_contracts.mask", "is required")
        mask_contract = _parse_texture_contract_v2(
            contracts["mask"], f"{label}.texture_contracts.mask"
        )
        if mask_contract.filter_mode != "Point":
            _fail(
                f"{label}.texture_contracts.mask.filter_mode",
                "required SHCDE target masks must use Point",
            )
    else:
        if contracts["mask"] is not None:
            _fail(f"{label}.texture_contracts.mask", "must be null")
        mask_contract = None

    raw_pages = _require_list(data["pages"], f"{label}.pages")
    if not 1 <= len(raw_pages) <= BC7_MAX_PAGES_PER_GROUP:
        _fail(
            f"{label}.pages",
            f"page count must be in [1, {BC7_MAX_PAGES_PER_GROUP}]",
        )
    pages: list[AtlasPageV3] = []
    seen_assets: set[str] = set()
    seen_addresses: set[str] = set()
    for ordinal, raw_page in enumerate(raw_pages):
        page_label = f"{label}.pages[{ordinal}]"
        page = _require_mapping(raw_page, page_label)
        _require_exact_keys(page, {"height", "id", "main", "mask", "width"}, page_label)
        page_id = _require_int(page["id"], f"{page_label}.id")
        if page_id != ordinal:
            _fail(f"{page_label}.id", "pages must be contiguous from zero")
        width = _require_page_dimension(page["width"], f"{page_label}.width")
        height = _require_page_dimension(page["height"], f"{page_label}.height")
        main = _parse_page_texture_v2(
            page["main"],
            f"{page_label}.main",
            width=width,
            height=height,
            expected_format=main_contract.format,
        )
        if mask_policy == "required":
            if page["mask"] is None or mask_contract is None:
                _fail(f"{page_label}.mask", "is required")
            mask = _parse_page_texture_v2(
                page["mask"],
                f"{page_label}.mask",
                width=width,
                height=height,
                expected_format=mask_contract.format,
            )
        else:
            if page["mask"] is not None:
                _fail(f"{page_label}.mask", "must be null")
            mask = None
        expected_main_path = f"Assets/Generated/Groups/{slug}/page-{page_id:03d}-main.png"
        expected_main_address = f"sede/gm/{slug}/page/{page_id:03d}/main"
        if (main.asset_path, main.address) != (expected_main_path, expected_main_address):
            _fail(f"{page_label}.main", "path/address do not match page identity")
        if mask is not None:
            expected_mask_path = f"Assets/Generated/Groups/{slug}/page-{page_id:03d}-mask.png"
            expected_mask_address = f"sede/gm/{slug}/page/{page_id:03d}/mask"
            if (mask.asset_path, mask.address) != (expected_mask_path, expected_mask_address):
                _fail(f"{page_label}.mask", "path/address do not match page identity")
        for plane in (main, mask):
            if plane is None:
                continue
            if plane.asset_path.casefold() in seen_assets or plane.address.casefold() in seen_addresses:
                _fail(page_label, "contains duplicate/case-colliding plane identity")
            seen_assets.add(plane.asset_path.casefold())
            seen_addresses.add(plane.address.casefold())
        pages.append(AtlasPageV3(page_id, width, height, main, mask))

    raw_frames = _require_list(data["frames"], f"{label}.frames")
    if not 1 <= len(raw_frames) <= MAX_PREFLIGHT_FRAMES_PER_GROUP:
        _fail(f"{label}.frames", "frame count is outside V2 limits")
    frames_sha = _require_sha256(data["frames_sha256"], f"{label}.frames_sha256")
    if hashlib.sha256(canonical_json_bytes(raw_frames)).hexdigest() != frames_sha:
        _fail(f"{label}.frames_sha256", "does not bind the canonical frame array")
    frames = tuple(
        _parse_frame_v3(item, f"{label}.frames[{ordinal}]", mask_policy == "required")
        for ordinal, item in enumerate(raw_frames)
    )
    order = tuple((frame.index, frame.alt, frame.name) for frame in frames)
    if order != tuple(sorted(order)):
        _fail(f"{label}.frames", "must be sorted by (index, alt, name)")
    if not any(not frame.alt for frame in frames):
        _fail(f"{label}.frames", "must contain at least one main frame")
    seen_names: set[str] = set()
    seen_slots: set[tuple[int, bool]] = set()
    for ordinal, frame in enumerate(frames):
        if frame.name in seen_names:
            _fail(f"{label}.frames[{ordinal}].name", "duplicates another name")
        slot = (frame.index, frame.alt)
        if slot in seen_slots:
            _fail(f"{label}.frames[{ordinal}]", f"duplicates loader slot {slot}")
        if frame.page >= len(pages):
            _fail(f"{label}.frames[{ordinal}].page", "references a missing page")
        seen_names.add(frame.name)
        seen_slots.add(slot)
    if {frame.page for frame in frames} != set(range(len(pages))):
        _fail(f"{label}.pages", "every page must be referenced")
    _validate_v3_storage_cells(pages, frames, label)
    return AtlasV3(
        schema,
        group,
        slug,
        bundle,
        mask_policy,
        material_binding,
        coordinate_system,
        extrusion_mode,
        border,
        block_alignment,
        max_dimension,
        main_contract,
        mask_contract,
        tuple(pages),
        frames,
        frames_sha,
        hashlib.sha256(raw).hexdigest(),
    )


def parse_atlas_v2(raw: bytes, *, label: str = "atlas.v2.json") -> AtlasV2:
    data = _require_mapping(
        _load_canonical_json_file(raw, label, MAX_ATLAS_BYTES), label
    )
    _require_exact_keys(
        data,
        {
            "schema",
            "group",
            "slug",
            "bundle",
            "mask_policy",
            "material_binding",
            "coordinate_system",
            "padding_pixels",
            "max_page_dimension",
            "texture_contract",
            "pages",
            "frames",
            "frames_sha256",
        },
        label,
    )
    schema = _require_string(data["schema"], f"{label}.schema")
    if schema != ATLAS_SCHEMA:
        _fail(f"{label}.schema", f"expected {ATLAS_SCHEMA!r}")
    group = _require_group(data["group"], f"{label}.group")
    slug = _require_slug(data["slug"], f"{label}.slug")
    if slug != canonical_group_slug(group, f"{label}.group"):
        _fail(
            f"{label}.slug",
            "must equal the canonical lowercased/underscore group slug",
        )
    bundle = _require_bundle_name(data["bundle"], f"{label}.bundle")
    if bundle != f"sede.gm.{slug}.v2":
        _fail(f"{label}.bundle", "does not match the group slug")
    mask_policy = _require_string(data["mask_policy"], f"{label}.mask_policy")
    material_binding = _require_string(
        data["material_binding"], f"{label}.material_binding"
    )
    if mask_policy not in {"required", "forbidden"}:
        _fail(f"{label}.mask_policy", "must be 'required' or 'forbidden'")
    expected_binding = expected_material_binding(group, mask_policy)
    if material_binding != expected_binding:
        _fail(
            f"{label}.material_binding",
            f"must be {expected_binding!r} for group {group!r}",
        )
    coordinate_system = _require_string(
        data["coordinate_system"], f"{label}.coordinate_system"
    )
    if coordinate_system != "unity_bottom_left":
        _fail(f"{label}.coordinate_system", "must be 'unity_bottom_left'")
    padding = _require_int(data["padding_pixels"], f"{label}.padding_pixels")
    if padding != 1:
        _fail(f"{label}.padding_pixels", "must be exactly 1")
    max_dimension = _require_int(
        data["max_page_dimension"], f"{label}.max_page_dimension", minimum=1
    )
    if max_dimension != MAX_PAGE_DIMENSION:
        _fail(f"{label}.max_page_dimension", f"must be {MAX_PAGE_DIMENSION}")
    texture_contract = _parse_texture_contract(
        data["texture_contract"], f"{label}.texture_contract"
    )

    page_values = _require_list(data["pages"], f"{label}.pages")
    if not 1 <= len(page_values) <= MAX_PAGES_PER_GROUP:
        _fail(f"{label}.pages", "page count is outside the v1 limits")
    if (
        material_binding == GROUP_MASK_MATERIAL_BINDING
        and len(page_values) != 1
    ):
        _fail(
            f"{label}.pages",
            "group_mask_single_page_v1 requires exactly one page",
        )
    pages: list[AtlasPage] = []
    seen_assets: set[str] = set()
    seen_addresses: set[str] = set()
    for ordinal, raw_page in enumerate(page_values):
        page_label = f"{label}.pages[{ordinal}]"
        value = _require_mapping(raw_page, page_label)
        _require_exact_keys(value, {"id", "width", "height", "main", "mask"}, page_label)
        page_id = _require_int(value["id"], f"{page_label}.id")
        if page_id != ordinal:
            _fail(f"{page_label}.id", f"pages must be ordered contiguously from 0")
        width = _require_page_dimension(value["width"], f"{page_label}.width")
        height = _require_page_dimension(value["height"], f"{page_label}.height")
        main = _parse_page_texture(value["main"], f"{page_label}.main")
        mask_raw = value["mask"]
        if mask_policy == "required":
            if mask_raw is None:
                _fail(f"{page_label}.mask", "is required")
            mask = _parse_page_texture(mask_raw, f"{page_label}.mask")
        else:
            if mask_raw is not None:
                _fail(f"{page_label}.mask", "must be null for forbidden masks")
            mask = None
        expected_main_path = (
            f"Assets/Generated/Groups/{slug}/page-{page_id:03d}-main.png"
        )
        expected_main_address = f"sede/gm/{slug}/page/{page_id:03d}/main"
        if (main.asset_path, main.address) != (expected_main_path, expected_main_address):
            _fail(f"{page_label}.main", "path/address do not match page identity")
        if mask is not None:
            expected_mask_path = (
                f"Assets/Generated/Groups/{slug}/page-{page_id:03d}-mask.png"
            )
            expected_mask_address = f"sede/gm/{slug}/page/{page_id:03d}/mask"
            if (mask.asset_path, mask.address) != (
                expected_mask_path,
                expected_mask_address,
            ):
                _fail(f"{page_label}.mask", "path/address do not match page identity")
        for texture in (main, mask):
            if texture is None:
                continue
            folded_path = texture.asset_path.casefold()
            folded_address = texture.address.casefold()
            if folded_path in seen_assets or folded_address in seen_addresses:
                _fail(page_label, "contains a duplicate/case-colliding texture identity")
            seen_assets.add(folded_path)
            seen_addresses.add(folded_address)
        pages.append(AtlasPage(page_id, width, height, main, mask))

    frame_values = _require_list(data["frames"], f"{label}.frames")
    if not 1 <= len(frame_values) <= MAX_FRAMES_PER_GROUP:
        _fail(f"{label}.frames", "frame count is outside the v1 limits")
    expected_frames_sha = _require_sha256(
        data["frames_sha256"], f"{label}.frames_sha256"
    )
    actual_frames_sha = hashlib.sha256(canonical_json_bytes(frame_values)).hexdigest()
    if actual_frames_sha != expected_frames_sha:
        _fail(
            f"{label}.frames_sha256",
            f"does not bind frames; expected {expected_frames_sha}, got {actual_frames_sha}",
        )
    frames = tuple(
        _parse_frame(frame, f"{label}.frames[{ordinal}]", mask_policy == "required")
        for ordinal, frame in enumerate(frame_values)
    )
    order = tuple((frame.index, frame.alt, frame.name) for frame in frames)
    if order != tuple(sorted(order)):
        _fail(f"{label}.frames", "must be sorted by (index, alt, name)")
    if not any(not frame.alt for frame in frames):
        _fail(f"{label}.frames", "must contain at least one main frame")
    names: set[str] = set()
    slots: set[tuple[int, bool]] = set()
    for ordinal, frame in enumerate(frames):
        slot = (frame.index, frame.alt)
        if frame.name in names:
            _fail(f"{label}.frames[{ordinal}].name", "duplicates another frame name")
        if slot in slots:
            _fail(f"{label}.frames[{ordinal}]", f"duplicates loader slot {slot}")
        names.add(frame.name)
        slots.add(slot)
        if frame.page >= len(pages):
            _fail(f"{label}.frames[{ordinal}].page", "references a missing page")
    referenced_pages = {frame.page for frame in frames}
    if referenced_pages != set(range(len(pages))):
        _fail(f"{label}.pages", "every page must be referenced by at least one frame")
    _validate_frame_rectangles(pages, frames, padding, label)

    return AtlasV2(
        schema=schema,
        group=group,
        slug=slug,
        bundle=bundle,
        mask_policy=mask_policy,
        material_binding=material_binding,
        coordinate_system=coordinate_system,
        padding_pixels=padding,
        max_page_dimension=max_dimension,
        texture_contract=texture_contract,
        pages=tuple(pages),
        frames=frames,
        frames_sha256=expected_frames_sha,
        file_sha256=hashlib.sha256(raw).hexdigest(),
    )


def parse_asset_bundle_index(
    raw: bytes,
    *,
    atlas_documents: Mapping[str, bytes],
    expected_groups: Sequence[str] | None = None,
) -> AssetBundleIndex:
    """Parse the external index and every embedded ``atlas.v2`` TextAsset.

    The index is a normal runtime file, not an AssetBundle.  Each group record
    binds its one bundle's final bytes and the exact atlas TextAsset embedded in
    that bundle.  No Unity root/index bundle or manifest sidecar is accepted.
    """

    label = "index.json"
    data = _require_mapping(
        _load_canonical_json_file(raw, label, MAX_INDEX_BYTES), label
    )
    _require_exact_keys(
        data,
        {
            "schema",
            "build_id",
            "unity",
            "build_target",
            "max_page_dimension",
            "groups",
            "vanilla_omitted_groups",
        },
        label,
    )
    schema = _require_string(data["schema"], f"{label}.schema")
    if schema != INDEX_SCHEMA:
        _fail(f"{label}.schema", f"expected {INDEX_SCHEMA!r}")
    build_id = _require_sha256(data["build_id"], f"{label}.build_id")
    unity = _parse_unity_identity(data["unity"], f"{label}.unity")
    build_target = _require_string(data["build_target"], f"{label}.build_target")
    if build_target != BUILD_TARGET:
        _fail(f"{label}.build_target", f"must be {BUILD_TARGET!r}")
    max_dimension = _require_int(
        data["max_page_dimension"], f"{label}.max_page_dimension", minimum=1
    )
    if max_dimension != MAX_PAGE_DIMENSION:
        _fail(f"{label}.max_page_dimension", f"must be {MAX_PAGE_DIMENSION}")
    raw_groups = _require_list(data["groups"], f"{label}.groups")
    raw_omitted = _require_list(
        data["vanilla_omitted_groups"], f"{label}.vanilla_omitted_groups"
    )
    if (
        not 0 <= len(raw_groups) <= MAX_GROUPS
        or not 0 <= len(raw_omitted) <= MAX_GROUPS
        or not 1 <= len(raw_groups) + len(raw_omitted) <= MAX_GROUPS
    ):
        _fail(f"{label}.groups", "group count is outside the v1 limits")

    normalized_documents: dict[str, bytes] = {}
    document_paths: set[str] = set()
    for supplied_path, document in atlas_documents.items():
        path = require_safe_relative_path(supplied_path, "atlas_documents key")
        folded = path.casefold()
        if folded in document_paths:
            _fail("atlas_documents", "contains duplicate/case-colliding paths")
        if not isinstance(document, bytes):
            _fail(f"atlas_documents[{path!r}]", "must be raw bytes")
        document_paths.add(folded)
        normalized_documents[path] = document

    groups: list[GroupIndexRecord] = []
    seen_groups: set[str] = set()
    seen_slugs: set[str] = set()
    seen_bundles: set[str] = set()
    seen_bundle_paths: set[str] = set()
    seen_gm_ids: set[int] = set()
    expected_document_paths: set[str] = set()
    group_keys = {
        "group",
        "slug",
        "gm_id",
        "dash_format",
        "array_size",
        "lifetime",
        "bundle",
        "bundle_path",
        "bundle_size_bytes",
        "bundle_sha256",
        "bundle_crc32",
        "unity_hash128",
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
        "predicted_load_peak_bytes",
        "pages",
    }
    for ordinal, raw_group in enumerate(raw_groups):
        group_label = f"{label}.groups[{ordinal}]"
        value = _require_mapping(raw_group, group_label)
        _require_exact_keys(value, group_keys, group_label)
        group = _require_group(value["group"], f"{group_label}.group")
        slug = _require_slug(value["slug"], f"{group_label}.slug")
        if slug != canonical_group_slug(group, f"{group_label}.group"):
            _fail(
                f"{group_label}.slug",
                "must equal the canonical lowercased/underscore group slug",
            )
        gm_id = _require_int(
            value["gm_id"], f"{group_label}.gm_id", maximum=MAX_GROUPS - 1
        )
        dash_format = _require_bool(
            value["dash_format"], f"{group_label}.dash_format"
        )
        array_size = _require_int(
            value["array_size"],
            f"{group_label}.array_size",
            minimum=1,
            maximum=MAX_FRAMES_PER_GROUP,
        )
        lifetime = _require_string(value["lifetime"], f"{group_label}.lifetime")
        if lifetime != "map":
            _fail(f"{group_label}.lifetime", "must be 'map'")
        bundle = _require_bundle_name(value["bundle"], f"{group_label}.bundle")
        expected_bundle = f"sede.gm.{slug}.v2"
        if bundle != expected_bundle:
            _fail(f"{group_label}.bundle", f"must be {expected_bundle!r}")
        bundle_path = require_safe_relative_path(
            value["bundle_path"], f"{group_label}.bundle_path"
        )
        expected_bundle_path = ASSET_BUNDLE_OUTPUT_PREFIX + bundle
        if bundle_path != expected_bundle_path:
            _fail(
                f"{group_label}.bundle_path", f"must be {expected_bundle_path!r}"
            )
        bundle_size = _require_int(
            value["bundle_size_bytes"],
            f"{group_label}.bundle_size_bytes",
            minimum=1,
        )
        bundle_sha = _require_sha256(
            value["bundle_sha256"], f"{group_label}.bundle_sha256"
        )
        bundle_crc = _require_crc32(
            value["bundle_crc32"], f"{group_label}.bundle_crc32"
        )
        unity_hash = _require_hash128(
            value["unity_hash128"], f"{group_label}.unity_hash128"
        )
        atlas_path = require_safe_relative_path(
            value["atlas_asset_path"], f"{group_label}.atlas_asset_path"
        )
        expected_atlas_path = f"Assets/Generated/Groups/{slug}/atlas.v2.json"
        if atlas_path != expected_atlas_path:
            _fail(
                f"{group_label}.atlas_asset_path",
                f"must be {expected_atlas_path!r}",
            )
        atlas_address = require_safe_relative_path(
            value["atlas_address"], f"{group_label}.atlas_address"
        )
        expected_address = f"sede/gm/{slug}/atlas.v2.json"
        if atlas_address != expected_address:
            _fail(f"{group_label}.atlas_address", f"must be {expected_address!r}")
        atlas_sha = _require_sha256(
            value["atlas_sha256"], f"{group_label}.atlas_sha256"
        )
        mask_policy = _require_string(
            value["mask_policy"], f"{group_label}.mask_policy"
        )
        material_binding = _require_string(
            value["material_binding"], f"{group_label}.material_binding"
        )
        page_count = _require_int(
            value["page_count"],
            f"{group_label}.page_count",
            minimum=1,
            maximum=MAX_PAGES_PER_GROUP,
        )
        frame_count = _require_int(
            value["frame_count"],
            f"{group_label}.frame_count",
            minimum=1,
            maximum=MAX_FRAMES_PER_GROUP,
        )
        names_sha = _require_sha256(
            value["names_sha256"], f"{group_label}.names_sha256"
        )
        frames_sha = _require_sha256(
            value["frames_sha256"], f"{group_label}.frames_sha256"
        )
        raw_rgba_bytes = _require_int(
            value["raw_rgba_bytes"], f"{group_label}.raw_rgba_bytes", minimum=1
        )
        resident_charge = _require_int(
            value["resident_charge_bytes"],
            f"{group_label}.resident_charge_bytes",
            minimum=1,
        )
        if resident_charge != calculate_resident_charge(raw_rgba_bytes):
            _fail(
                f"{group_label}.resident_charge_bytes",
                "does not equal the exact 9/8-aligned resident charge",
            )
        predicted_load_peak = _require_int(
            value["predicted_load_peak_bytes"],
            f"{group_label}.predicted_load_peak_bytes",
            minimum=1,
        )
        expected_load_peak = calculate_peak_admission_bytes(
            resident_charge, bundle_size
        )
        if predicted_load_peak != expected_load_peak:
            _fail(
                f"{group_label}.predicted_load_peak_bytes",
                "does not equal 2 * resident charge + the 64-MiB-aligned "
                "bundle size + 256 MiB",
            )

        for item, seen, item_label in (
            (group.casefold(), seen_groups, "group"),
            (slug.casefold(), seen_slugs, "slug"),
            (bundle.casefold(), seen_bundles, "bundle"),
            (bundle_path.casefold(), seen_bundle_paths, "bundle_path"),
        ):
            if item in seen:
                _fail(group_label, f"duplicate/case-colliding {item_label}")
            seen.add(item)
        if gm_id in seen_gm_ids:
            _fail(f"{group_label}.gm_id", "duplicates another loader GM id")
        seen_gm_ids.add(gm_id)

        expected_document_paths.add(atlas_path)
        if atlas_path not in normalized_documents:
            _fail(group_label, f"missing raw atlas document {atlas_path!r}")
        atlas_raw = normalized_documents[atlas_path]
        actual_atlas_sha = hashlib.sha256(atlas_raw).hexdigest()
        if actual_atlas_sha != atlas_sha:
            _fail(
                f"{group_label}.atlas_sha256",
                f"raw file mismatch; expected {atlas_sha}, got {actual_atlas_sha}",
            )
        atlas = parse_atlas_v2(atlas_raw, label=atlas_path)
        cross_fields = {
            "group": (group, atlas.group),
            "slug": (slug, atlas.slug),
            "bundle": (bundle, atlas.bundle),
            "mask_policy": (mask_policy, atlas.mask_policy),
            "material_binding": (material_binding, atlas.material_binding),
            "page_count": (page_count, len(atlas.pages)),
            "frame_count": (frame_count, len(atlas.frames)),
            "frames_sha256": (frames_sha, atlas.frames_sha256),
            "raw_rgba_bytes": (raw_rgba_bytes, atlas.raw_rgba_bytes),
            "resident_charge_bytes": (resident_charge, atlas.charge_bytes),
            "max_page_dimension": (max_dimension, atlas.max_page_dimension),
        }
        changed = [name for name, (left, right) in cross_fields.items() if left != right]
        if changed:
            _fail(group_label, f"index/atlas fields disagree: {changed}")
        actual_names_sha = hashlib.sha256(
            canonical_json_bytes([frame.name for frame in atlas.frames])
        ).hexdigest()
        if names_sha != actual_names_sha:
            _fail(f"{group_label}.names_sha256", "does not bind atlas frame names")
        if any(frame.index >= array_size for frame in atlas.frames):
            _fail(group_label, "atlas frame index is outside array_size")

        raw_summaries = _require_list(value["pages"], f"{group_label}.pages")
        if len(raw_summaries) != page_count:
            _fail(f"{group_label}.pages", "does not match page_count")
        summaries: list[IndexPageSummary] = []
        for page_ordinal, (raw_summary, atlas_page) in enumerate(
            zip(raw_summaries, atlas.pages, strict=True)
        ):
            page_label = f"{group_label}.pages[{page_ordinal}]"
            summary = _require_mapping(raw_summary, page_label)
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
                page_label,
            )
            page_id = _require_int(summary["id"], f"{page_label}.id")
            width = _require_page_dimension(
                summary["width"], f"{page_label}.width"
            )
            height = _require_page_dimension(
                summary["height"], f"{page_label}.height"
            )
            main_address = require_safe_relative_path(
                summary["main_address"], f"{page_label}.main_address"
            )
            main_rgba_sha = _require_sha256(
                summary["main_rgba_sha256"], f"{page_label}.main_rgba_sha256"
            )
            if summary["mask_address"] is None:
                mask_address = None
            else:
                mask_address = require_safe_relative_path(
                    summary["mask_address"], f"{page_label}.mask_address"
                )
            if summary["mask_rgba_sha256"] is None:
                mask_rgba_sha = None
            else:
                mask_rgba_sha = _require_sha256(
                    summary["mask_rgba_sha256"],
                    f"{page_label}.mask_rgba_sha256",
                )
            expected_mask_address = (
                None if atlas_page.mask is None else atlas_page.mask.address
            )
            expected_mask_sha = (
                None if atlas_page.mask is None else atlas_page.mask.rgba_sha256
            )
            actual_summary = (
                page_id,
                width,
                height,
                main_address,
                main_rgba_sha,
                mask_address,
                mask_rgba_sha,
            )
            expected_summary = (
                atlas_page.id,
                atlas_page.width,
                atlas_page.height,
                atlas_page.main.address,
                atlas_page.main.rgba_sha256,
                expected_mask_address,
                expected_mask_sha,
            )
            if actual_summary != expected_summary:
                _fail(page_label, "does not exactly summarize atlas.v2")
            summaries.append(IndexPageSummary(*actual_summary))

        groups.append(
            GroupIndexRecord(
                group=group,
                slug=slug,
                gm_id=gm_id,
                dash_format=dash_format,
                array_size=array_size,
                lifetime=lifetime,
                bundle=bundle,
                bundle_path=bundle_path,
                bundle_size_bytes=bundle_size,
                bundle_sha256=bundle_sha,
                bundle_crc32=bundle_crc,
                unity_hash128=unity_hash,
                atlas_asset_path=atlas_path,
                atlas_address=atlas_address,
                atlas_sha256=atlas_sha,
                mask_policy=mask_policy,
                material_binding=material_binding,
                page_count=page_count,
                frame_count=frame_count,
                names_sha256=names_sha,
                frames_sha256=frames_sha,
                raw_rgba_bytes=raw_rgba_bytes,
                resident_charge_bytes=resident_charge,
                predicted_load_peak_bytes=predicted_load_peak,
                pages=tuple(summaries),
                atlas=atlas,
            )
        )
    actual_order = tuple(group.group for group in groups)
    if actual_order != tuple(sorted(actual_order)):
        _fail(f"{label}.groups", "must be sorted by group ordinal")
    if set(normalized_documents) != expected_document_paths:
        extra = sorted(set(normalized_documents) - expected_document_paths)
        missing = sorted(expected_document_paths - set(normalized_documents))
        _fail("atlas_documents", f"file set changed; missing={missing}, extra={extra}")
    omitted: list[VanillaOmittedGroup] = []
    omitted_order: list[str] = []
    omitted_keys = {
        "group",
        "gm_id",
        "reason",
        "array_size",
        "frame_count",
        "names_sha256",
        "frames_sha256",
    }
    for ordinal, raw_item in enumerate(raw_omitted):
        item_label = f"{label}.vanilla_omitted_groups[{ordinal}]"
        value = _require_mapping(raw_item, item_label)
        _require_exact_keys(value, omitted_keys, item_label)
        group = _require_group(value["group"], f"{item_label}.group")
        gm_id = _require_int(
            value["gm_id"], f"{item_label}.gm_id", maximum=MAX_GROUPS - 1
        )
        reason = _require_string(value["reason"], f"{item_label}.reason")
        if reason not in VANILLA_OMISSION_REASONS:
            _fail(f"{item_label}.reason", "is not a canonical v1 omission reason")
        array_size = _require_int(
            value["array_size"],
            f"{item_label}.array_size",
            minimum=1,
            maximum=MAX_PREFLIGHT_ARRAY_SIZE,
        )
        frame_count = _require_int(
            value["frame_count"],
            f"{item_label}.frame_count",
            minimum=1,
            maximum=MAX_PREFLIGHT_FRAMES_PER_GROUP,
        )
        names_sha = _require_sha256(
            value["names_sha256"], f"{item_label}.names_sha256"
        )
        frames_sha = _require_sha256(
            value["frames_sha256"], f"{item_label}.frames_sha256"
        )
        if reason == OMISSION_FRAME_COUNT:
            justified = frame_count > MAX_FRAMES_PER_GROUP
        elif reason == OMISSION_SLOT_COUNT:
            justified = (
                frame_count <= MAX_FRAMES_PER_GROUP
                and array_size > MAX_FRAMES_PER_GROUP
            )
        else:
            justified = (
                frame_count <= MAX_FRAMES_PER_GROUP
                and array_size <= MAX_FRAMES_PER_GROUP
            )
        if not justified:
            _fail(f"{item_label}.reason", "contradicts the bound-precedence fields")
        folded = group.casefold()
        if folded in seen_groups:
            _fail(item_label, "duplicates/collides with another selected group")
        if gm_id in seen_gm_ids:
            _fail(f"{item_label}.gm_id", "duplicates another selected GM id")
        seen_groups.add(folded)
        seen_gm_ids.add(gm_id)
        omitted_order.append(group)
        omitted.append(
            VanillaOmittedGroup(
                group=group,
                gm_id=gm_id,
                reason=reason,
                array_size=array_size,
                frame_count=frame_count,
                names_sha256=names_sha,
                frames_sha256=frames_sha,
            )
        )
    if tuple(omitted_order) != tuple(sorted(omitted_order)):
        _fail(
            f"{label}.vanilla_omitted_groups",
            "must be sorted by group ordinal",
        )
    selected_order = tuple(sorted((*actual_order, *omitted_order)))
    if expected_groups is not None:
        expected = tuple(
            _require_group(item, "expected_groups item") for item in expected_groups
        )
        if selected_order != expected:
            _fail(
                label,
                f"GM order/set changed; expected={expected}, actual={selected_order}",
            )
    return AssetBundleIndex(
        schema=schema,
        build_id=build_id,
        unity=unity,
        build_target=build_target,
        max_page_dimension=max_dimension,
        groups=tuple(groups),
        vanilla_omitted_groups=tuple(omitted),
        file_size_bytes=len(raw),
        file_sha256=hashlib.sha256(raw).hexdigest(),
    )


_INDEX_V2_ROOT_KEYS = frozenset(
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
    }
)
_INDEX_V2_TEMPLATE_GROUP_KEYS = frozenset(
    {
        "array_size",
        "atlas_address",
        "atlas_asset_path",
        "atlas_sha256",
        "bundle",
        "dash_format",
        "frame_count",
        "frames_sha256",
        "gm_id",
        "gpu_bytes",
        "group",
        "lifetime",
        "mask_policy",
        "material_binding",
        "names_sha256",
        "page_count",
        "pages",
        "resident_charge_bytes",
        "slug",
        "source_rgba_bytes",
    }
)
_INDEX_V2_FINAL_GROUP_EXTRA_KEYS = frozenset(
    {
        "bundle_crc32",
        "bundle_path",
        "bundle_sha256",
        "bundle_size_bytes",
        "predicted_load_peak_bytes",
        "unity_hash128",
    }
)
_INDEX_V2_PAGE_KEYS = frozenset(
    {
        "height",
        "id",
        "main_address",
        "main_format",
        "main_gpu_bytes",
        "main_source_rgba_sha256",
        "mask_address",
        "mask_format",
        "mask_gpu_bytes",
        "mask_source_rgba_sha256",
        "width",
    }
)


def _parse_v2_omissions(
    raw: object,
    *,
    label: str,
    seen_groups: set[str],
    seen_gm_ids: set[int],
) -> tuple[VanillaOmittedGroup, ...]:
    values = _require_list(raw, label)
    if len(values) > MAX_GROUPS:
        _fail(label, "contains too many groups")
    result: list[VanillaOmittedGroup] = []
    order: list[str] = []
    keys = {
        "group",
        "gm_id",
        "reason",
        "array_size",
        "frame_count",
        "names_sha256",
        "frames_sha256",
    }
    for ordinal, raw_item in enumerate(values):
        item_label = f"{label}[{ordinal}]"
        item = _require_mapping(raw_item, item_label)
        _require_exact_keys(item, keys, item_label)
        group = _require_group(item["group"], f"{item_label}.group")
        gm_id = _require_int(item["gm_id"], f"{item_label}.gm_id", maximum=MAX_GROUPS - 1)
        reason = _require_string(item["reason"], f"{item_label}.reason")
        if reason not in VANILLA_OMISSION_REASONS:
            _fail(f"{item_label}.reason", "is not a canonical omission reason")
        array_size = _require_int(
            item["array_size"],
            f"{item_label}.array_size",
            minimum=1,
            maximum=MAX_PREFLIGHT_ARRAY_SIZE,
        )
        frame_count = _require_int(
            item["frame_count"],
            f"{item_label}.frame_count",
            minimum=1,
            maximum=MAX_PREFLIGHT_FRAMES_PER_GROUP,
        )
        if reason == OMISSION_FRAME_COUNT:
            justified = frame_count > MAX_FRAMES_PER_GROUP
        elif reason == OMISSION_SLOT_COUNT:
            justified = (
                frame_count <= MAX_FRAMES_PER_GROUP
                and array_size > MAX_FRAMES_PER_GROUP
            )
        else:
            justified = (
                frame_count <= MAX_FRAMES_PER_GROUP
                and array_size <= MAX_FRAMES_PER_GROUP
            )
        if not justified:
            _fail(
                f"{item_label}.reason",
                "contradicts the unchanged V1 omission-precedence fields",
            )
        folded = group.casefold()
        if folded in seen_groups or gm_id in seen_gm_ids:
            _fail(item_label, "duplicates/collides with a selected group or GM id")
        seen_groups.add(folded)
        seen_gm_ids.add(gm_id)
        order.append(group)
        result.append(
            VanillaOmittedGroup(
                group,
                gm_id,
                reason,
                array_size,
                frame_count,
                _require_sha256(item["names_sha256"], f"{item_label}.names_sha256"),
                _require_sha256(item["frames_sha256"], f"{item_label}.frames_sha256"),
            )
        )
    if order != sorted(order):
        _fail(label, "must be sorted by group ordinal")
    return tuple(result)


def _parse_asset_bundle_index_v2_common(
    raw: bytes,
    *,
    atlas_documents: Mapping[str, bytes],
    expect_template: bool,
    expected_groups: Sequence[str] | None,
) -> AssetBundleIndexV2:
    label = "index.v2.template.json" if expect_template else "index.json"
    data = _require_mapping(_load_canonical_json_file(raw, label, MAX_INDEX_BYTES), label)
    _require_exact_keys(data, _INDEX_V2_ROOT_KEYS, label)
    schema = _require_string(data["schema"], f"{label}.schema")
    expected_schema = BC7_INDEX_TEMPLATE_SCHEMA if expect_template else BC7_INDEX_SCHEMA
    if schema != expected_schema:
        _fail(f"{label}.schema", f"expected {expected_schema!r}")
    backend_kind = _require_string(data["backend_kind"], f"{label}.backend_kind")
    if backend_kind != BC7_ATLAS_BACKEND_KIND:
        _fail(f"{label}.backend_kind", f"must be {BC7_ATLAS_BACKEND_KIND!r}")
    build_id = _require_sha256(data["build_id"], f"{label}.build_id")
    unity = _parse_unity_identity(data["unity"], f"{label}.unity")
    build_target = _require_string(data["build_target"], f"{label}.build_target")
    if build_target != BUILD_TARGET:
        _fail(f"{label}.build_target", f"must be {BUILD_TARGET!r}")
    max_dimension = _require_int(
        data["max_page_dimension"], f"{label}.max_page_dimension", minimum=1
    )
    if max_dimension != MAX_PAGE_DIMENSION:
        _fail(f"{label}.max_page_dimension", f"must be {MAX_PAGE_DIMENSION}")
    packer_id = _require_string(data["packer_id"], f"{label}.packer_id")
    if packer_id != BC7_PACKER_ID:
        _fail(f"{label}.packer_id", f"must be {BC7_PACKER_ID!r}")
    encoder_id = _require_string(data["encoder_id"], f"{label}.encoder_id")
    if encoder_id != BC7_ENCODER_ID:
        _fail(f"{label}.encoder_id", f"must be {BC7_ENCODER_ID!r}")
    texture_policy = parse_texture_policy(data["texture_policy"])
    quality_policy = parse_quality_policy(data["quality_policy"])
    quality_raw = data["quality_report_sha256"]
    if expect_template:
        if quality_raw is not None:
            _fail(f"{label}.quality_report_sha256", "must be null in the template")
        quality_sha = None
    else:
        quality_sha = _require_sha256(quality_raw, f"{label}.quality_report_sha256")

    normalized_documents: dict[str, bytes] = {}
    seen_document_paths: set[str] = set()
    for supplied_path, document in atlas_documents.items():
        path = require_safe_relative_path(supplied_path, "atlas_documents key")
        if path.casefold() in seen_document_paths:
            _fail("atlas_documents", "contains duplicate/case-colliding paths")
        if not isinstance(document, bytes):
            _fail(f"atlas_documents[{path!r}]", "must be raw bytes")
        seen_document_paths.add(path.casefold())
        normalized_documents[path] = document

    raw_groups = _require_list(data["groups"], f"{label}.groups")
    if not 1 <= len(raw_groups) <= MAX_GROUPS:
        _fail(f"{label}.groups", "group count is outside V2 limits")
    group_keys = (
        _INDEX_V2_TEMPLATE_GROUP_KEYS
        if expect_template
        else _INDEX_V2_TEMPLATE_GROUP_KEYS | _INDEX_V2_FINAL_GROUP_EXTRA_KEYS
    )
    groups: list[GroupIndexRecordV2] = []
    seen_groups: set[str] = set()
    seen_slugs: set[str] = set()
    seen_gm_ids: set[int] = set()
    seen_bundles: set[str] = set()
    seen_bundle_paths: set[str] = set()
    expected_document_paths: set[str] = set()
    for ordinal, raw_group in enumerate(raw_groups):
        group_label = f"{label}.groups[{ordinal}]"
        value = _require_mapping(raw_group, group_label)
        _require_exact_keys(value, group_keys, group_label)
        group = _require_group(value["group"], f"{group_label}.group")
        slug = _require_slug(value["slug"], f"{group_label}.slug")
        if slug != canonical_group_slug(group, f"{group_label}.group"):
            _fail(f"{group_label}.slug", "does not equal the canonical group slug")
        gm_id = _require_int(value["gm_id"], f"{group_label}.gm_id", maximum=MAX_GROUPS - 1)
        dash_format = _require_bool(value["dash_format"], f"{group_label}.dash_format")
        array_size = _require_int(
            value["array_size"],
            f"{group_label}.array_size",
            minimum=1,
            maximum=MAX_PREFLIGHT_ARRAY_SIZE,
        )
        lifetime = _require_string(value["lifetime"], f"{group_label}.lifetime")
        if lifetime != "map":
            _fail(f"{group_label}.lifetime", "must be 'map'")
        bundle = _require_bc7_bundle_name(value["bundle"], f"{group_label}.bundle")
        expected_bundle = f"sede.gm.{slug}{BC7_BUNDLE_SUFFIX}"
        if bundle != expected_bundle:
            _fail(f"{group_label}.bundle", f"must be {expected_bundle!r}")
        atlas_path = require_safe_relative_path(
            value["atlas_asset_path"], f"{group_label}.atlas_asset_path"
        )
        expected_atlas_path = f"Assets/Generated/Groups/{slug}/{BC7_ATLAS_ASSET_FILENAME}"
        if atlas_path != expected_atlas_path:
            _fail(f"{group_label}.atlas_asset_path", f"must be {expected_atlas_path!r}")
        atlas_address = require_safe_relative_path(
            value["atlas_address"], f"{group_label}.atlas_address"
        )
        expected_atlas_address = f"sede/gm/{slug}/{BC7_ATLAS_ASSET_FILENAME}"
        if atlas_address != expected_atlas_address:
            _fail(f"{group_label}.atlas_address", f"must be {expected_atlas_address!r}")
        atlas_sha = _require_sha256(value["atlas_sha256"], f"{group_label}.atlas_sha256")
        mask_policy = _require_string(value["mask_policy"], f"{group_label}.mask_policy")
        material_binding = _require_string(
            value["material_binding"], f"{group_label}.material_binding"
        )
        page_count = _require_int(
            value["page_count"],
            f"{group_label}.page_count",
            minimum=1,
            maximum=BC7_MAX_PAGES_PER_GROUP,
        )
        frame_count = _require_int(
            value["frame_count"],
            f"{group_label}.frame_count",
            minimum=1,
            maximum=MAX_PREFLIGHT_FRAMES_PER_GROUP,
        )
        names_sha = _require_sha256(value["names_sha256"], f"{group_label}.names_sha256")
        frames_sha = _require_sha256(value["frames_sha256"], f"{group_label}.frames_sha256")
        source_rgba_bytes = _require_int(
            value["source_rgba_bytes"], f"{group_label}.source_rgba_bytes", minimum=1
        )
        gpu_bytes = _require_int(value["gpu_bytes"], f"{group_label}.gpu_bytes", minimum=1)
        resident_charge = _require_int(
            value["resident_charge_bytes"],
            f"{group_label}.resident_charge_bytes",
            minimum=1,
        )
        if resident_charge != calculate_bc7_group_resident_charge(gpu_bytes):
            _fail(
                f"{group_label}.resident_charge_bytes",
                "does not apply 9/8 and one 4-MiB group alignment",
            )
        folded_group = group.casefold()
        folded_slug = slug.casefold()
        folded_bundle = bundle.casefold()
        if folded_group in seen_groups or folded_slug in seen_slugs or folded_bundle in seen_bundles:
            _fail(group_label, "contains duplicate/case-colliding identity")
        if gm_id in seen_gm_ids:
            _fail(f"{group_label}.gm_id", "duplicates another GM id")
        seen_groups.add(folded_group)
        seen_slugs.add(folded_slug)
        seen_bundles.add(folded_bundle)
        seen_gm_ids.add(gm_id)

        expected_document_paths.add(atlas_path)
        if atlas_path not in normalized_documents:
            _fail(group_label, f"missing raw atlas document {atlas_path!r}")
        atlas_raw = normalized_documents[atlas_path]
        if hashlib.sha256(atlas_raw).hexdigest() != atlas_sha:
            _fail(f"{group_label}.atlas_sha256", "does not bind the atlas bytes")
        atlas = parse_atlas_v3(atlas_raw, label=atlas_path)
        cross_fields = {
            "group": (group, atlas.group),
            "slug": (slug, atlas.slug),
            "bundle": (bundle, atlas.bundle),
            "mask_policy": (mask_policy, atlas.mask_policy),
            "material_binding": (material_binding, atlas.material_binding),
            "page_count": (page_count, len(atlas.pages)),
            "frame_count": (frame_count, len(atlas.frames)),
            "frames_sha256": (frames_sha, atlas.frames_sha256),
            "source_rgba_bytes": (source_rgba_bytes, atlas.source_rgba_bytes),
            "gpu_bytes": (gpu_bytes, atlas.gpu_bytes),
            "resident_charge_bytes": (resident_charge, atlas.resident_charge_bytes),
            "max_page_dimension": (max_dimension, atlas.max_page_dimension),
        }
        changed = [name for name, pair in cross_fields.items() if pair[0] != pair[1]]
        if changed:
            _fail(group_label, f"index/atlas fields disagree: {changed}")
        if atlas.main_texture_contract.format != texture_policy.main_format:
            _fail(group_label, "main texture format disagrees with the global policy")
        if atlas.mask_policy == "required":
            if (
                atlas.mask_texture_contract is None
                or atlas.mask_texture_contract.format != texture_policy.mask_format
            ):
                _fail(group_label, "mask texture format disagrees with the global policy")
        actual_names_sha = hashlib.sha256(
            canonical_json_bytes([frame.name for frame in atlas.frames])
        ).hexdigest()
        if names_sha != actual_names_sha:
            _fail(f"{group_label}.names_sha256", "does not bind atlas frame names")
        if any(frame.index >= array_size for frame in atlas.frames):
            _fail(group_label, "atlas frame index is outside array_size")

        raw_pages = _require_list(value["pages"], f"{group_label}.pages")
        if len(raw_pages) != page_count:
            _fail(f"{group_label}.pages", "does not match page_count")
        summaries: list[IndexPageSummaryV2] = []
        for page_ordinal, (raw_summary, atlas_page) in enumerate(
            zip(raw_pages, atlas.pages, strict=True)
        ):
            page_label = f"{group_label}.pages[{page_ordinal}]"
            summary = _require_mapping(raw_summary, page_label)
            _require_exact_keys(summary, _INDEX_V2_PAGE_KEYS, page_label)
            page_id = _require_int(summary["id"], f"{page_label}.id")
            width = _require_page_dimension(summary["width"], f"{page_label}.width")
            height = _require_page_dimension(summary["height"], f"{page_label}.height")
            main_address = require_safe_relative_path(
                summary["main_address"], f"{page_label}.main_address"
            )
            main_format = _require_string(summary["main_format"], f"{page_label}.main_format")
            main_gpu = _require_int(summary["main_gpu_bytes"], f"{page_label}.main_gpu_bytes", minimum=1)
            main_sha = _require_sha256(
                summary["main_source_rgba_sha256"], f"{page_label}.main_source_rgba_sha256"
            )
            null_mask = atlas_page.mask is None
            mask_fields = (
                summary["mask_address"],
                summary["mask_format"],
                summary["mask_gpu_bytes"],
                summary["mask_source_rgba_sha256"],
            )
            if null_mask:
                if any(item is not None for item in mask_fields):
                    _fail(page_label, "all mask summary fields must be null")
                mask_address = mask_format = mask_sha = None
                mask_gpu = None
            else:
                assert atlas_page.mask is not None
                mask_address = require_safe_relative_path(
                    summary["mask_address"], f"{page_label}.mask_address"
                )
                mask_format = _require_string(summary["mask_format"], f"{page_label}.mask_format")
                mask_gpu = _require_int(summary["mask_gpu_bytes"], f"{page_label}.mask_gpu_bytes", minimum=1)
                mask_sha = _require_sha256(
                    summary["mask_source_rgba_sha256"],
                    f"{page_label}.mask_source_rgba_sha256",
                )
            actual_summary = (
                page_id,
                width,
                height,
                main_address,
                main_format,
                main_gpu,
                main_sha,
                mask_address,
                mask_format,
                mask_gpu,
                mask_sha,
            )
            expected_summary = (
                atlas_page.id,
                atlas_page.width,
                atlas_page.height,
                atlas_page.main.address,
                atlas_page.main.format,
                atlas_page.main.gpu_bytes,
                atlas_page.main.source_rgba_sha256,
                None if atlas_page.mask is None else atlas_page.mask.address,
                None if atlas_page.mask is None else atlas_page.mask.format,
                None if atlas_page.mask is None else atlas_page.mask.gpu_bytes,
                None if atlas_page.mask is None else atlas_page.mask.source_rgba_sha256,
            )
            if actual_summary != expected_summary:
                _fail(page_label, "does not exactly summarize atlas.v3")
            summaries.append(IndexPageSummaryV2(*actual_summary))

        if expect_template:
            bundle_path = None
            bundle_size = None
            bundle_sha = None
            bundle_crc = None
            unity_hash = None
            predicted_peak = None
        else:
            bundle_path = require_safe_relative_path(
                value["bundle_path"], f"{group_label}.bundle_path"
            )
            expected_bundle_path = ASSET_BUNDLE_OUTPUT_PREFIX + bundle
            if bundle_path != expected_bundle_path:
                _fail(f"{group_label}.bundle_path", f"must be {expected_bundle_path!r}")
            if bundle_path.casefold() in seen_bundle_paths:
                _fail(f"{group_label}.bundle_path", "duplicates another path")
            seen_bundle_paths.add(bundle_path.casefold())
            bundle_size = _require_int(
                value["bundle_size_bytes"], f"{group_label}.bundle_size_bytes", minimum=1
            )
            bundle_sha = _require_sha256(value["bundle_sha256"], f"{group_label}.bundle_sha256")
            bundle_crc = _require_crc32(value["bundle_crc32"], f"{group_label}.bundle_crc32")
            unity_hash = _require_hash128(value["unity_hash128"], f"{group_label}.unity_hash128")
            predicted_peak = _require_int(
                value["predicted_load_peak_bytes"],
                f"{group_label}.predicted_load_peak_bytes",
                minimum=1,
            )
            expected_peak = calculate_bc7_peak_admission_bytes(resident_charge, bundle_size)
            if predicted_peak != expected_peak:
                _fail(
                    f"{group_label}.predicted_load_peak_bytes",
                    "does not equal the exact V2 peak formula",
                )
        groups.append(
            GroupIndexRecordV2(
                group,
                slug,
                gm_id,
                dash_format,
                array_size,
                lifetime,
                bundle,
                atlas_path,
                atlas_address,
                atlas_sha,
                mask_policy,
                material_binding,
                page_count,
                frame_count,
                names_sha,
                frames_sha,
                source_rgba_bytes,
                gpu_bytes,
                resident_charge,
                tuple(summaries),
                atlas,
                bundle_path,
                bundle_size,
                bundle_sha,
                bundle_crc,
                unity_hash,
                predicted_peak,
            )
        )
    group_order = [group.group for group in groups]
    if group_order != sorted(group_order):
        _fail(f"{label}.groups", "must be sorted by group ordinal")
    if set(normalized_documents) != expected_document_paths:
        _fail(
            "atlas_documents",
            f"file set changed; missing={sorted(expected_document_paths-set(normalized_documents))}, "
            f"extra={sorted(set(normalized_documents)-expected_document_paths)}",
        )
    omitted = _parse_v2_omissions(
        data["vanilla_omitted_groups"],
        label=f"{label}.vanilla_omitted_groups",
        seen_groups=seen_groups,
        seen_gm_ids=seen_gm_ids,
    )
    if len(groups) + len(omitted) > MAX_GROUPS:
        _fail(label, "selected group count exceeds the GM table")
    selected_order = tuple(sorted((*group_order, *(item.group for item in omitted))))
    if expected_groups is not None:
        expected = tuple(_require_group(item, "expected_groups item") for item in expected_groups)
        if selected_order != expected:
            _fail(label, f"GM order/set changed; expected={expected}, actual={selected_order}")
    totals = {
        "total_source_rgba_bytes": sum(group.source_rgba_bytes for group in groups),
        "total_gpu_bytes": sum(group.gpu_bytes for group in groups),
        "total_resident_charge_bytes": sum(group.resident_charge_bytes for group in groups),
    }
    parsed_totals: dict[str, int] = {}
    for key, expected in totals.items():
        actual = _require_int(data[key], f"{label}.{key}", minimum=1)
        if actual != expected:
            _fail(f"{label}.{key}", f"expected exact group sum {expected}, got {actual}")
        parsed_totals[key] = actual
    if (
        parsed_totals["total_resident_charge_bytes"]
        > BC7_MAXIMUM_TOTAL_RESIDENT_CHARGE_BYTES
    ):
        _fail(
            f"{label}.total_resident_charge_bytes",
            "exceeds the exact 3-GiB V4 GM resident budget",
        )
    return AssetBundleIndexV2(
        schema,
        backend_kind,
        build_id,
        unity,
        build_target,
        max_dimension,
        packer_id,
        encoder_id,
        texture_policy,
        quality_policy,
        quality_sha,
        tuple(groups),
        omitted,
        parsed_totals["total_source_rgba_bytes"],
        parsed_totals["total_gpu_bytes"],
        parsed_totals["total_resident_charge_bytes"],
        len(raw),
        hashlib.sha256(raw).hexdigest(),
    )


def parse_asset_bundle_index_template_v2(
    raw: bytes,
    *,
    atlas_documents: Mapping[str, bytes],
    expected_groups: Sequence[str] | None = None,
) -> AssetBundleIndexV2:
    return _parse_asset_bundle_index_v2_common(
        raw,
        atlas_documents=atlas_documents,
        expect_template=True,
        expected_groups=expected_groups,
    )


def parse_asset_bundle_index_v2(
    raw: bytes,
    *,
    atlas_documents: Mapping[str, bytes],
    expected_groups: Sequence[str] | None = None,
) -> AssetBundleIndexV2:
    return _parse_asset_bundle_index_v2_common(
        raw,
        atlas_documents=atlas_documents,
        expect_template=False,
        expected_groups=expected_groups,
    )


_BUILD_INPUT_V2_ROOT_KEYS = frozenset(
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
    }
)
_BUILD_INPUT_V2_TEXTURE_KEYS = frozenset(
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
    }
)
_BUILD_REPORT_V2_ROOT_KEYS = frozenset(
    {
        "build_id",
        "build_input_sha256",
        "build_options",
        "build_target",
        "bundles",
        "error",
        "index_sha256",
        "quality_report_sha256",
        "schema",
        "success",
        "textures",
        "unity",
        "verified",
    }
)
_BUILD_REPORT_V2_TEXTURE_KEYS = frozenset(
    {
        "asset_path",
        "gpu_bytes",
        "height",
        "plane",
        "source_png_sha256",
        "source_rgba_bytes",
        "source_rgba_sha256",
        "texture_contract",
        "width",
    }
)


def _parse_build_options(raw: object, label: str) -> tuple[str, ...]:
    values = _require_list(raw, label)
    options = tuple(
        _require_string(item, f"{label}[{ordinal}]")
        for ordinal, item in enumerate(values)
    )
    if options != _BUILD_OPTIONS:
        _fail(label, f"must be exactly {_BUILD_OPTIONS}")
    return options


def _validate_texture_contract_identity(
    contract_id: str,
    contract: TextureContractV2,
    label: str,
) -> tuple[str, str, str]:
    identity = BC7_TEXTURE_CONTRACT_IDENTITIES.get(contract_id)
    if identity is None:
        _fail(label, f"unsupported texture-contract id {contract_id!r}")
    plane, texture_format, filter_mode = identity
    if (contract.format, contract.filter_mode) != (texture_format, filter_mode):
        _fail(
            label,
            f"id requires format/filter {(texture_format, filter_mode)!r}, got "
            f"{(contract.format, contract.filter_mode)!r}",
        )
    return identity


def parse_asset_bundle_build_input_v2(raw: bytes) -> AssetBundleBuildInputV2:
    """Parse Unity's complete canonical BC7 build request."""

    label = "build-input.v2.json"
    data = _require_mapping(_load_canonical_json_file(raw, label, MAX_REPORT_BYTES), label)
    _require_exact_keys(data, _BUILD_INPUT_V2_ROOT_KEYS, label)
    schema = _require_string(data["schema"], f"{label}.schema")
    if schema != BC7_BUILD_INPUT_SCHEMA:
        _fail(f"{label}.schema", f"expected {BC7_BUILD_INPUT_SCHEMA!r}")
    backend_kind = _require_string(data["backend_kind"], f"{label}.backend_kind")
    if backend_kind != BC7_ATLAS_BACKEND_KIND:
        _fail(f"{label}.backend_kind", f"must be {BC7_ATLAS_BACKEND_KIND!r}")
    build_id = _require_sha256(data["build_id"], f"{label}.build_id")
    unity = _parse_unity_identity(data["unity"], f"{label}.unity")
    build_target = _require_string(data["build_target"], f"{label}.build_target")
    if build_target != BUILD_TARGET:
        _fail(f"{label}.build_target", f"must be {BUILD_TARGET!r}")
    build_options = _parse_build_options(data["build_options"], f"{label}.build_options")
    max_dimension = _require_int(
        data["max_page_dimension"], f"{label}.max_page_dimension", minimum=1
    )
    if max_dimension != MAX_PAGE_DIMENSION:
        _fail(f"{label}.max_page_dimension", f"must be {MAX_PAGE_DIMENSION}")
    exact_strings = {
        "output_relative_path": BC7_OUTPUT_RELATIVE_PATH,
        "index_template_asset_path": BC7_INDEX_TEMPLATE_ASSET_PATH,
        "index_output_relative_path": BC7_INDEX_OUTPUT_RELATIVE_PATH,
        "quality_report_output_relative_path": BC7_QUALITY_REPORT_OUTPUT_RELATIVE_PATH,
        "editor_texture_compression_override": BC7_EDITOR_TEXTURE_COMPRESSION_OVERRIDE,
        "packer_id": BC7_PACKER_ID,
        "encoder_id": BC7_ENCODER_ID,
    }
    parsed_strings: dict[str, str] = {}
    for key, expected in exact_strings.items():
        actual = _require_string(data[key], f"{label}.{key}")
        if actual != expected:
            _fail(f"{label}.{key}", f"must be {expected!r}")
        parsed_strings[key] = actual
    editor_sha = _require_sha256(
        data["editor_script_sha256"], f"{label}.editor_script_sha256"
    )
    texture_policy = parse_texture_policy(data["texture_policy"])
    quality_policy = parse_quality_policy(data["quality_policy"])

    raw_bindings = _require_list(data["texture_contracts"], f"{label}.texture_contracts")
    if not 1 <= len(raw_bindings) <= len(BC7_TEXTURE_CONTRACT_IDENTITIES):
        _fail(f"{label}.texture_contracts", "count is outside the qualified set")
    bindings: list[TextureContractBindingV2] = []
    binding_by_id: dict[str, TextureContractV2] = {}
    for ordinal, raw_binding in enumerate(raw_bindings):
        binding_label = f"{label}.texture_contracts[{ordinal}]"
        binding = _require_mapping(raw_binding, binding_label)
        _require_exact_keys(binding, {"id", "texture_contract"}, binding_label)
        contract_id = _require_string(binding["id"], f"{binding_label}.id")
        if contract_id in binding_by_id:
            _fail(f"{binding_label}.id", "duplicates another contract")
        contract = _parse_texture_contract_v2(
            binding["texture_contract"], f"{binding_label}.texture_contract"
        )
        plane, texture_format, _ = _validate_texture_contract_identity(
            contract_id, contract, f"{binding_label}.id"
        )
        expected_policy_format = (
            texture_policy.main_format if plane == "main" else texture_policy.mask_format
        )
        if texture_format != expected_policy_format:
            _fail(binding_label, "contract format is outside the global texture policy")
        binding_by_id[contract_id] = contract
        bindings.append(TextureContractBindingV2(contract_id, contract))
    if [item.id for item in bindings] != sorted(item.id for item in bindings):
        _fail(f"{label}.texture_contracts", "must be sorted by id ordinal")

    raw_textures = _require_list(data["textures"], f"{label}.textures")
    if not raw_textures:
        _fail(f"{label}.textures", "must not be empty")
    textures: list[TextureBuildInputV2] = []
    seen_texture_paths: set[str] = set()
    used_contract_ids: set[str] = set()
    for ordinal, raw_texture in enumerate(raw_textures):
        texture_label = f"{label}.textures[{ordinal}]"
        value = _require_mapping(raw_texture, texture_label)
        _require_exact_keys(value, _BUILD_INPUT_V2_TEXTURE_KEYS, texture_label)
        asset_path = require_safe_relative_path(value["asset_path"], f"{texture_label}.asset_path")
        if asset_path.casefold() in seen_texture_paths:
            _fail(f"{texture_label}.asset_path", "duplicates/case-collides")
        seen_texture_paths.add(asset_path.casefold())
        width = _require_int(value["width"], f"{texture_label}.width", minimum=1, maximum=MAX_PAGE_DIMENSION)
        height = _require_int(value["height"], f"{texture_label}.height", minimum=1, maximum=MAX_PAGE_DIMENSION)
        plane = _require_string(value["plane"], f"{texture_label}.plane")
        if plane not in {"main", "mask"}:
            _fail(f"{texture_label}.plane", "must be 'main' or 'mask'")
        contract_id = _require_string(
            value["texture_contract_id"], f"{texture_label}.texture_contract_id"
        )
        contract = binding_by_id.get(contract_id)
        if contract is None:
            _fail(f"{texture_label}.texture_contract_id", "references a missing contract")
        contract_plane, _, _ = _validate_texture_contract_identity(
            contract_id, contract, f"{texture_label}.texture_contract_id"
        )
        if contract_plane != plane:
            _fail(texture_label, "plane disagrees with texture-contract id")
        gpu_bytes = _require_int(value["gpu_bytes"], f"{texture_label}.gpu_bytes", minimum=1)
        expected_gpu = calculate_texture_gpu_bytes(width, height, contract.format)
        if gpu_bytes != expected_gpu:
            _fail(f"{texture_label}.gpu_bytes", f"expected {expected_gpu}")
        source_rgba_bytes = _require_int(
            value["source_rgba_bytes"], f"{texture_label}.source_rgba_bytes", minimum=1
        )
        expected_source = width * height * 4
        if source_rgba_bytes != expected_source:
            _fail(f"{texture_label}.source_rgba_bytes", f"expected {expected_source}")
        used_contract_ids.add(contract_id)
        textures.append(
            TextureBuildInputV2(
                asset_path,
                width,
                height,
                plane,
                contract_id,
                gpu_bytes,
                _require_sha256(value["source_png_sha256"], f"{texture_label}.source_png_sha256"),
                source_rgba_bytes,
                _require_sha256(value["source_rgba_sha256"], f"{texture_label}.source_rgba_sha256"),
            )
        )
    if [item.asset_path for item in textures] != sorted(item.asset_path for item in textures):
        _fail(f"{label}.textures", "must be sorted by asset_path ordinal")
    if used_contract_ids != set(binding_by_id):
        _fail(
            f"{label}.texture_contracts",
            f"referential set changed; unused={sorted(set(binding_by_id)-used_contract_ids)}",
        )

    raw_bundles = _require_list(data["bundles"], f"{label}.bundles")
    if not raw_bundles:
        _fail(f"{label}.bundles", "must not be empty")
    bundles: list[BundleBuildInputV2] = []
    seen_bundle_names: set[str] = set()
    seen_asset_paths: set[str] = set()
    seen_addresses: set[str] = set()
    for ordinal, raw_bundle in enumerate(raw_bundles):
        bundle_label = f"{label}.bundles[{ordinal}]"
        value = _require_mapping(raw_bundle, bundle_label)
        _require_exact_keys(value, {"assets", "name"}, bundle_label)
        name = _require_bc7_bundle_name(value["name"], f"{bundle_label}.name")
        if name.casefold() in seen_bundle_names:
            _fail(f"{bundle_label}.name", "duplicates/case-collides")
        seen_bundle_names.add(name.casefold())
        raw_assets = _require_list(value["assets"], f"{bundle_label}.assets")
        if not raw_assets:
            _fail(f"{bundle_label}.assets", "must not be empty")
        assets: list[BundleAssetInputV2] = []
        for asset_ordinal, raw_asset in enumerate(raw_assets):
            asset_label = f"{bundle_label}.assets[{asset_ordinal}]"
            asset = _require_mapping(raw_asset, asset_label)
            _require_exact_keys(asset, {"address", "asset_path"}, asset_label)
            address = require_safe_relative_path(asset["address"], f"{asset_label}.address")
            asset_path = require_safe_relative_path(asset["asset_path"], f"{asset_label}.asset_path")
            if asset_path.casefold() in seen_asset_paths or address.casefold() in seen_addresses:
                _fail(asset_label, "duplicates/case-collides across bundles")
            seen_asset_paths.add(asset_path.casefold())
            seen_addresses.add(address.casefold())
            assets.append(BundleAssetInputV2(address, asset_path))
        if [item.address for item in assets] != sorted(item.address for item in assets):
            _fail(f"{bundle_label}.assets", "must be sorted by address ordinal")
        bundles.append(BundleBuildInputV2(name, tuple(assets)))
    if [item.name for item in bundles] != sorted(item.name for item in bundles):
        _fail(f"{label}.bundles", "must be sorted by name ordinal")
    supplied_texture_assets = {item.asset_path.casefold() for item in textures}
    if not supplied_texture_assets.issubset(seen_asset_paths):
        _fail(f"{label}.bundles", "does not include every texture asset exactly once")
    return AssetBundleBuildInputV2(
        schema,
        backend_kind,
        build_id,
        unity,
        build_target,
        build_options,
        max_dimension,
        parsed_strings["output_relative_path"],
        parsed_strings["index_template_asset_path"],
        parsed_strings["index_output_relative_path"],
        parsed_strings["quality_report_output_relative_path"],
        editor_sha,
        parsed_strings["editor_texture_compression_override"],
        parsed_strings["packer_id"],
        parsed_strings["encoder_id"],
        texture_policy,
        quality_policy,
        tuple(bindings),
        tuple(textures),
        tuple(bundles),
        hashlib.sha256(raw).hexdigest(),
    )


def _parse_bc7_bundle_artifact(raw: object, label: str) -> BundleArtifact:
    value = _require_mapping(raw, label)
    _require_exact_keys(
        value,
        {"manifest_hash", "mod_relative_path", "name", "sha256", "size_bytes"},
        label,
    )
    name = _require_bc7_bundle_name(value["name"], f"{label}.name")
    path = require_safe_relative_path(value["mod_relative_path"], f"{label}.mod_relative_path")
    expected_path = ASSET_BUNDLE_OUTPUT_PREFIX + name
    if path != expected_path:
        _fail(f"{label}.mod_relative_path", f"must be {expected_path!r}")
    return BundleArtifact(
        name,
        path,
        _require_int(value["size_bytes"], f"{label}.size_bytes", minimum=1),
        _require_sha256(value["sha256"], f"{label}.sha256"),
        _require_hash128(value["manifest_hash"], f"{label}.manifest_hash"),
    )


def parse_asset_bundle_build_report_v2(
    raw: bytes,
    *,
    build_input: AssetBundleBuildInputV2 | None = None,
    require_verified: bool = True,
) -> AssetBundleBuildReportV2:
    """Parse a failure, Unity-intermediate, or fully verified V2 report."""

    if type(require_verified) is not bool:
        _fail("require_verified", "must be a boolean")
    label = "build-report.v2.json"
    data = _require_mapping(_load_canonical_json_file(raw, label, MAX_REPORT_BYTES), label)
    _require_exact_keys(data, _BUILD_REPORT_V2_ROOT_KEYS, label)
    schema = _require_string(data["schema"], f"{label}.schema")
    if schema != BC7_BUILD_REPORT_SCHEMA:
        _fail(f"{label}.schema", f"expected {BC7_BUILD_REPORT_SCHEMA!r}")
    success = _require_bool(data["success"], f"{label}.success")
    verified = _require_bool(data["verified"], f"{label}.verified")
    error = _require_string(data["error"], f"{label}.error", allow_empty=True)
    if verified and not success:
        _fail(label, "verified=true requires success=true")
    if success == bool(error):
        _fail(label, "success requires empty error; failure requires non-empty error")
    if require_verified and not (success and verified):
        _fail(label, f"build is not fully verified: {error or 'intermediate report'}")
    build_id = _require_sha256(data["build_id"], f"{label}.build_id")
    build_input_sha = _require_sha256(
        data["build_input_sha256"], f"{label}.build_input_sha256"
    )
    unity = _parse_unity_identity(data["unity"], f"{label}.unity")
    build_target = _require_string(data["build_target"], f"{label}.build_target")
    if build_target != BUILD_TARGET:
        _fail(f"{label}.build_target", f"must be {BUILD_TARGET!r}")
    build_options = _parse_build_options(data["build_options"], f"{label}.build_options")
    index_raw = data["index_sha256"]
    quality_raw = data["quality_report_sha256"]
    if success and verified:
        index_sha = _require_sha256(index_raw, f"{label}.index_sha256")
        quality_sha = _require_sha256(quality_raw, f"{label}.quality_report_sha256")
    else:
        if index_raw is not None or quality_raw is not None:
            _fail(label, "unverified/failure reports require null index and quality SHAs")
        index_sha = quality_sha = None

    raw_textures = _require_list(data["textures"], f"{label}.textures")
    textures: list[TextureBuildRecordV2] = []
    seen_texture_paths: set[str] = set()
    for ordinal, raw_texture in enumerate(raw_textures):
        texture_label = f"{label}.textures[{ordinal}]"
        value = _require_mapping(raw_texture, texture_label)
        _require_exact_keys(value, _BUILD_REPORT_V2_TEXTURE_KEYS, texture_label)
        asset_path = require_safe_relative_path(value["asset_path"], f"{texture_label}.asset_path")
        if asset_path.casefold() in seen_texture_paths:
            _fail(f"{texture_label}.asset_path", "duplicates/case-collides")
        seen_texture_paths.add(asset_path.casefold())
        width = _require_int(value["width"], f"{texture_label}.width", minimum=1, maximum=MAX_PAGE_DIMENSION)
        height = _require_int(value["height"], f"{texture_label}.height", minimum=1, maximum=MAX_PAGE_DIMENSION)
        plane = _require_string(value["plane"], f"{texture_label}.plane")
        if plane not in {"main", "mask"}:
            _fail(f"{texture_label}.plane", "must be 'main' or 'mask'")
        contract_id = _require_string(value["texture_contract"], f"{texture_label}.texture_contract")
        identity = BC7_TEXTURE_CONTRACT_IDENTITIES.get(contract_id)
        if identity is None or identity[0] != plane:
            _fail(f"{texture_label}.texture_contract", "is not qualified for this plane")
        gpu_bytes = _require_int(value["gpu_bytes"], f"{texture_label}.gpu_bytes", minimum=1)
        expected_gpu = calculate_texture_gpu_bytes(width, height, identity[1])
        if gpu_bytes != expected_gpu:
            _fail(f"{texture_label}.gpu_bytes", f"expected {expected_gpu}")
        source_rgba_bytes = _require_int(
            value["source_rgba_bytes"], f"{texture_label}.source_rgba_bytes", minimum=1
        )
        if source_rgba_bytes != width * height * 4:
            _fail(f"{texture_label}.source_rgba_bytes", "does not equal width*height*4")
        textures.append(
            TextureBuildRecordV2(
                asset_path,
                width,
                height,
                plane,
                contract_id,
                gpu_bytes,
                _require_sha256(value["source_png_sha256"], f"{texture_label}.source_png_sha256"),
                source_rgba_bytes,
                _require_sha256(value["source_rgba_sha256"], f"{texture_label}.source_rgba_sha256"),
            )
        )
    if [item.asset_path for item in textures] != sorted(item.asset_path for item in textures):
        _fail(f"{label}.textures", "must be sorted by asset_path ordinal")
    bundles = tuple(
        _parse_bc7_bundle_artifact(item, f"{label}.bundles[{ordinal}]")
        for ordinal, item in enumerate(_require_list(data["bundles"], f"{label}.bundles"))
    )
    if [item.name for item in bundles] != sorted(item.name for item in bundles):
        _fail(f"{label}.bundles", "must be sorted by name ordinal")
    if len({item.name.casefold() for item in bundles}) != len(bundles):
        _fail(f"{label}.bundles", "contains duplicate/case-colliding names")
    if success and not bundles:
        _fail(f"{label}.bundles", "successful reports must contain bundles")

    if build_input is not None:
        if not isinstance(build_input, AssetBundleBuildInputV2):
            _fail("build_input", "must be a parsed V2 build input")
        if (
            build_id != build_input.build_id
            or build_input_sha != build_input.file_sha256
            or unity != build_input.unity
            or build_target != build_input.build_target
            or build_options != build_input.build_options
        ):
            _fail(label, "identity/toolchain fields disagree with build-input.v2")
        expected_textures = {
            item.asset_path: (
                item.width,
                item.height,
                item.plane,
                item.texture_contract_id,
                item.gpu_bytes,
                item.source_png_sha256,
                item.source_rgba_bytes,
                item.source_rgba_sha256,
            )
            for item in build_input.textures
        }
        actual_textures = {
            item.asset_path: (
                item.width,
                item.height,
                item.plane,
                item.texture_contract,
                item.gpu_bytes,
                item.source_png_sha256,
                item.source_rgba_bytes,
                item.source_rgba_sha256,
            )
            for item in textures
        }
        if success and actual_textures != expected_textures:
            _fail(f"{label}.textures", "do not exactly repeat build-input textures")
        expected_bundle_names = {item.name for item in build_input.bundles}
        if success and {item.name for item in bundles} != expected_bundle_names:
            _fail(f"{label}.bundles", "do not exactly match build-input bundles")
    return AssetBundleBuildReportV2(
        schema,
        success,
        verified,
        error,
        build_id,
        build_input_sha,
        unity,
        build_target,
        build_options,
        tuple(textures),
        bundles,
        index_sha,
        quality_sha,
        hashlib.sha256(raw).hexdigest(),
    )


def _parse_texture_build_record(raw: object, label: str) -> TextureBuildRecord:
    value = _require_mapping(raw, label)
    expected_keys = {"asset_path", "width", "height", "png_sha256", *_TEXTURE_KEYS}
    _require_exact_keys(value, expected_keys, label)
    parsed_contract = _parse_texture_contract(
        {key: value[key] for key in _TEXTURE_KEYS}, label
    )
    return TextureBuildRecord(
        asset_path=require_safe_relative_path(value["asset_path"], f"{label}.asset_path"),
        width=_require_int(value["width"], f"{label}.width", minimum=1, maximum=MAX_PAGE_DIMENSION),
        height=_require_int(value["height"], f"{label}.height", minimum=1, maximum=MAX_PAGE_DIMENSION),
        format=parsed_contract.format,
        s_rgb=parsed_contract.s_rgb,
        mipmaps=parsed_contract.mipmaps,
        readable=parsed_contract.readable,
        filter_mode=parsed_contract.filter_mode,
        wrap_mode=parsed_contract.wrap_mode,
        alpha_source=parsed_contract.alpha_source,
        alpha_is_transparency=parsed_contract.alpha_is_transparency,
        npot_scale=parsed_contract.npot_scale,
        png_sha256=_require_sha256(value["png_sha256"], f"{label}.png_sha256"),
    )


def _parse_bundle_artifact(raw: object, label: str) -> BundleArtifact:
    value = _require_mapping(raw, label)
    _require_exact_keys(
        value, {"name", "mod_relative_path", "size_bytes", "sha256", "manifest_hash"}, label
    )
    name = _require_bundle_name(value["name"], f"{label}.name")
    path = require_safe_relative_path(value["mod_relative_path"], f"{label}.mod_relative_path")
    expected_path = ASSET_BUNDLE_OUTPUT_PREFIX + name
    if path != expected_path:
        _fail(f"{label}.mod_relative_path", f"must be {expected_path!r}")
    return BundleArtifact(
        name=name,
        mod_relative_path=path,
        size_bytes=_require_int(value["size_bytes"], f"{label}.size_bytes", minimum=1),
        sha256=_require_sha256(value["sha256"], f"{label}.sha256"),
        manifest_hash=_require_hash128(value["manifest_hash"], f"{label}.manifest_hash"),
    )


def parse_asset_bundle_build_report(
    raw: bytes,
    *,
    index: AssetBundleIndex,
    require_success: bool = True,
) -> AssetBundleBuildReport:
    """Parse and cross-check Unity's canonical post-build artifact report."""

    label = "build-report.v1.json"
    data = _require_mapping(
        _load_canonical_json_file(raw, label, MAX_REPORT_BYTES), label
    )
    _require_exact_keys(
        data,
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
        label,
    )
    schema = _require_string(data["schema"], f"{label}.schema")
    if schema != BUILD_REPORT_SCHEMA:
        _fail(f"{label}.schema", f"expected {BUILD_REPORT_SCHEMA!r}")
    success = _require_bool(data["success"], f"{label}.success")
    error = _require_string(data["error"], f"{label}.error", allow_empty=True)
    if success == bool(error):
        _fail(label, "success requires empty error; failure requires non-empty error")
    if require_success and not success:
        _fail(label, f"Unity build failed: {error}")
    build_id = _require_sha256(data["build_id"], f"{label}.build_id")
    if build_id != index.build_id:
        _fail(f"{label}.build_id", "does not match index.json")
    build_input_sha = _require_sha256(
        data["build_input_sha256"], f"{label}.build_input_sha256"
    )
    unity = _parse_unity_identity(data["unity"], f"{label}.unity")
    target = _require_string(data["build_target"], f"{label}.build_target")
    if target != BUILD_TARGET or target != index.build_target:
        _fail(f"{label}.build_target", "does not match the pinned index target")
    option_values = _require_list(data["build_options"], f"{label}.build_options")
    options = tuple(
        _require_string(option, f"{label}.build_options[{ordinal}]")
        for ordinal, option in enumerate(option_values)
    )
    if options != _BUILD_OPTIONS:
        _fail(f"{label}.build_options", f"must be exactly {_BUILD_OPTIONS}")
    textures = tuple(
        _parse_texture_build_record(item, f"{label}.textures[{ordinal}]")
        for ordinal, item in enumerate(_require_list(data["textures"], f"{label}.textures"))
    )
    bundles = tuple(
        _parse_bundle_artifact(item, f"{label}.bundles[{ordinal}]")
        for ordinal, item in enumerate(_require_list(data["bundles"], f"{label}.bundles"))
    )
    if not success:
        return AssetBundleBuildReport(
            schema,
            success,
            error,
            build_id,
            build_input_sha,
            unity,
            target,
            options,
            textures,
            bundles,
            hashlib.sha256(raw).hexdigest(),
        )

    expected_textures: dict[str, tuple[int, int, str]] = {}
    for group in index.groups:
        for page in group.atlas.pages:
            for texture in (page.main, page.mask):
                if texture is None:
                    continue
                if texture.asset_path in expected_textures:
                    _fail(label, f"duplicate indexed texture {texture.asset_path!r}")
                expected_textures[texture.asset_path] = (
                    page.width,
                    page.height,
                    texture.png_sha256,
                )
    texture_paths = tuple(texture.asset_path for texture in textures)
    if texture_paths != tuple(sorted(texture_paths)):
        _fail(f"{label}.textures", "must be sorted by asset_path ordinal")
    if set(texture_paths) != set(expected_textures):
        _fail(
            f"{label}.textures",
            "texture set does not exactly equal all indexed main/mask pages",
        )
    if len(texture_paths) != len(set(path.casefold() for path in texture_paths)):
        _fail(f"{label}.textures", "contains duplicate/case-colliding paths")
    for texture in textures:
        if (texture.width, texture.height, texture.png_sha256) != expected_textures[
            texture.asset_path
        ]:
            _fail(
                f"{label}.textures[{texture.asset_path}]",
                "dimensions or PNG hash disagree with atlas.v2",
            )

    expected_bundles = {group.bundle for group in index.groups}
    bundle_names = tuple(bundle.name for bundle in bundles)
    if bundle_names != tuple(sorted(bundle_names)):
        _fail(f"{label}.bundles", "must be sorted by name ordinal")
    if set(bundle_names) != expected_bundles or len(bundle_names) != len(expected_bundles):
        _fail(f"{label}.bundles", "bundle set does not exactly equal the GM groups")
    if len(bundle_names) != len(set(name.casefold() for name in bundle_names)):
        _fail(f"{label}.bundles", "contains duplicate/case-colliding names")
    artifacts_by_name = {artifact.name: artifact for artifact in bundles}
    for group in index.groups:
        artifact = artifacts_by_name[group.bundle]
        if (
            artifact.mod_relative_path != group.bundle_path
            or artifact.size_bytes != group.bundle_size_bytes
            or artifact.sha256 != group.bundle_sha256
            or artifact.manifest_hash != group.unity_hash128
        ):
            _fail(
                f"{label}.bundles[{group.bundle}]",
                "does not match the final external index artifact metadata",
            )
    return AssetBundleBuildReport(
        schema,
        success,
        error,
        build_id,
        build_input_sha,
        unity,
        target,
        options,
        textures,
        bundles,
        hashlib.sha256(raw).hexdigest(),
    )


def expected_bundle_output_paths(index: AssetBundleIndex) -> tuple[str, ...]:
    """Return only the shipped GM bundle paths (the index is not a bundle)."""

    return tuple(sorted(group.bundle_path for group in index.groups))


def expected_stream_output_paths(index: AssetBundleIndex) -> tuple[str, ...]:
    """Return the complete runtime stream payload: external index plus bundles."""

    return (INDEX_OUTPUT_PATH, *expected_bundle_output_paths(index))


def expected_bundle_output_paths_v2(index: AssetBundleIndexV2) -> tuple[str, ...]:
    """Return final V2 bundle paths and reject an unmaterialized template."""

    if not isinstance(index, AssetBundleIndexV2) or index.is_template:
        _fail("index", "must be a parsed final V2 index")
    paths: list[str] = []
    for group in index.groups:
        if group.bundle_path is None:
            _fail("index", f"group {group.group!r} has no final bundle path")
        paths.append(group.bundle_path)
    return tuple(sorted(paths))


def expected_stream_output_paths_v2(index: AssetBundleIndexV2) -> tuple[str, ...]:
    return (INDEX_OUTPUT_PATH, *expected_bundle_output_paths_v2(index))


def find_legacy_atlas_outputs(relative_paths: Iterable[str]) -> tuple[str, ...]:
    """Find all legacy GM files superseded by the streaming backend.

    The historical function name is kept for callers, but the exclusive
    legacy payload includes both full atlases and sparse sprite overrides.
    """

    found: list[str] = []
    for ordinal, raw_path in enumerate(relative_paths):
        path = require_safe_relative_path(raw_path, f"output_paths[{ordinal}]")
        if path.casefold().startswith(
            (
                LEGACY_ATLAS_OUTPUT_PREFIX.casefold(),
                LEGACY_SPRITE_OUTPUT_PREFIX.casefold(),
            )
        ):
            found.append(path)
    return tuple(sorted(found, key=str.casefold))


def find_stream_bundle_outputs(relative_paths: Iterable[str]) -> tuple[str, ...]:
    """Find every file owned by the stream backend, including its external index."""

    found: list[str] = []
    for ordinal, raw_path in enumerate(relative_paths):
        path = require_safe_relative_path(raw_path, f"output_paths[{ordinal}]")
        if path.casefold().startswith(ASSET_STREAM_OUTPUT_PREFIX.casefold()):
            found.append(path)
    return tuple(sorted(found, key=str.casefold))


def validate_backend_output_exclusivity(
    backend: AtlasBackend | None,
    relative_paths: Iterable[str],
    *,
    index: AssetBundleIndex | AssetBundleIndexV2 | None = None,
) -> None:
    """Reject legacy/stream duality and incomplete streamed output sets."""

    paths = tuple(relative_paths)
    folded = [require_safe_relative_path(path, "output path").casefold() for path in paths]
    if len(folded) != len(set(folded)):
        _fail("output paths", "contain duplicates or Windows case-collisions")
    legacy = find_legacy_atlas_outputs(paths)
    streamed = find_stream_bundle_outputs(paths)
    if backend is None:
        if streamed:
            _fail("output paths", f"legacy profile unexpectedly owns streamed bundles: {streamed}")
        return
    if legacy:
        _fail("output paths", f"streaming profile also owns legacy atlases: {legacy}")
    if index is None:
        _fail("output paths", "streaming mode requires a parsed index")
    if backend.kind == ATLAS_BACKEND_KIND:
        if not isinstance(index, AssetBundleIndex):
            _fail("index", "V1 backend requires a parsed V1 index")
        expected = set(expected_stream_output_paths(index))
    elif backend.kind == BC7_ATLAS_BACKEND_KIND:
        if not isinstance(index, AssetBundleIndexV2):
            _fail("index", "BC7 V2 backend requires a parsed V2 index")
        expected = set(expected_stream_output_paths_v2(index))
    else:
        _fail("atlas_backend.kind", "was not parsed by this contract")
    if set(streamed) != expected:
        _fail(
            "output paths",
            f"stream bundle set changed; missing={sorted(expected-set(streamed))}, "
            f"extra={sorted(set(streamed)-expected)}",
        )


def validate_bundle_output_records(
    index: AssetBundleIndex,
    report: AssetBundleBuildReport,
    output_records: Iterable[Mapping[str, object]],
) -> None:
    """Bind the external index and every GM bundle to generic OutputRecords."""

    if not report.success:
        _fail("build report", "failed reports cannot own manifest outputs")
    actual: dict[str, Mapping[str, object]] = {}
    all_paths: list[str] = []
    for ordinal, raw_record in enumerate(output_records):
        record = _require_mapping(raw_record, f"output_records[{ordinal}]")
        if "relative_path" not in record:
            _fail(f"output_records[{ordinal}]", "missing relative_path")
        path = require_safe_relative_path(
            record["relative_path"], f"output_records[{ordinal}].relative_path"
        )
        all_paths.append(path)
        if path.casefold().startswith(ASSET_STREAM_OUTPUT_PREFIX.casefold()):
            if path in actual or any(existing.casefold() == path.casefold() for existing in actual):
                _fail("output_records", "duplicate/case-colliding streamed path")
            actual[path] = record
    validate_backend_output_exclusivity(
        AtlasBackend(ATLAS_BACKEND_KIND, parse_resource_policy(RESOURCE_POLICY_VALUES)),
        all_paths,
        index=index,
    )
    expected_paths = set(expected_stream_output_paths(index))
    if set(actual) != expected_paths:
        _fail("output_records", "stream artifact set disagrees with the final index")

    index_record = actual[INDEX_OUTPUT_PATH]
    index_category = _require_string(
        index_record.get("category"), f"output_records[{INDEX_OUTPUT_PATH}].category"
    )
    if index_category != ASSET_BUNDLE_INDEX_CATEGORY:
        _fail(
            f"output_records[{INDEX_OUTPUT_PATH}].category",
            f"must be {ASSET_BUNDLE_INDEX_CATEGORY!r}",
        )
    index_size = _require_int(
        index_record.get("size"), f"output_records[{INDEX_OUTPUT_PATH}].size", minimum=1
    )
    index_sha = _require_sha256(
        index_record.get("sha256"), f"output_records[{INDEX_OUTPUT_PATH}].sha256"
    )
    if (index_size, index_sha) != (index.file_size_bytes, index.file_sha256):
        _fail(
            f"output_records[{INDEX_OUTPUT_PATH}]",
            "size/SHA do not bind the canonical external index bytes",
        )
    index_metadata = _require_mapping(
        index_record.get("metadata"), f"output_records[{INDEX_OUTPUT_PATH}].metadata"
    )
    expected_index_metadata = {
        "kind": ATLAS_BACKEND_KIND,
        "schema": INDEX_SCHEMA,
        "build_id": index.build_id,
        "group_count": len(index.groups),
        "vanilla_omitted_group_count": len(index.vanilla_omitted_groups),
        "selected_group_count": (
            len(index.groups) + len(index.vanilla_omitted_groups)
        ),
        "index_sha256": index.file_sha256,
        "unity_version": index.unity.version,
        "unity_revision": index.unity.revision,
        "build_target": index.build_target,
    }
    _require_exact_keys(
        index_metadata,
        expected_index_metadata,
        f"output_records[{INDEX_OUTPUT_PATH}].metadata",
    )
    if index_metadata != expected_index_metadata:
        _fail(
            f"output_records[{INDEX_OUTPUT_PATH}].metadata",
            "does not bind the external index identity",
        )

    artifacts_by_name = {artifact.name: artifact for artifact in report.bundles}
    for group in index.groups:
        path = group.bundle_path
        artifact = artifacts_by_name.get(group.bundle)
        if artifact is None:
            _fail("build report", f"has no GM bundle {group.bundle!r}")
        record = actual[path]
        category = _require_string(record.get("category"), f"output_records[{path}].category")
        if category != ASSET_BUNDLE_CATEGORY:
            _fail(f"output_records[{path}].category", f"must be {ASSET_BUNDLE_CATEGORY!r}")
        size = _require_int(record.get("size"), f"output_records[{path}].size", minimum=1)
        sha = _require_sha256(record.get("sha256"), f"output_records[{path}].sha256")
        if (size, sha) != (
            artifact.size_bytes,
            artifact.sha256,
        ) or (size, sha) != (group.bundle_size_bytes, group.bundle_sha256):
            _fail(
                f"output_records[{path}]",
                "size/SHA disagree with the Unity report or external index",
            )
        metadata = _require_mapping(record.get("metadata"), f"output_records[{path}].metadata")
        expected_metadata = {
            "kind": ATLAS_BACKEND_KIND,
            "bundle": group.bundle,
            "group": group.group,
            "gm_id": group.gm_id,
            "unity_hash128": group.unity_hash128,
            "crc32": group.bundle_crc32,
            "resident_charge_bytes": group.resident_charge_bytes,
        }
        _require_exact_keys(
            metadata, expected_metadata, f"output_records[{path}].metadata"
        )
        if metadata != expected_metadata:
            _fail(f"output_records[{path}].metadata", "does not bind the bundle artifact")


def validate_bundle_output_records_v2(
    index: AssetBundleIndexV2,
    report: AssetBundleBuildReportV2,
    output_records: Iterable[Mapping[str, object]],
) -> None:
    """Bind the verified V2 index/bundles to their exact OutputRecord envelope."""

    if not isinstance(index, AssetBundleIndexV2) or index.is_template:
        _fail("index", "must be a parsed final V2 index")
    if not isinstance(report, AssetBundleBuildReportV2) or not (
        report.success and report.verified
    ):
        _fail("build report", "must be a fully verified V2 report")
    if (
        report.build_id != index.build_id
        or report.index_sha256 != index.file_sha256
        or report.quality_report_sha256 != index.quality_report_sha256
    ):
        _fail("build report", "does not bind the final index/quality identities")
    actual: dict[str, Mapping[str, object]] = {}
    all_paths: list[str] = []
    for ordinal, raw_record in enumerate(output_records):
        record = _require_mapping(raw_record, f"output_records[{ordinal}]")
        if "relative_path" not in record:
            _fail(f"output_records[{ordinal}]", "missing relative_path")
        path = require_safe_relative_path(
            record["relative_path"], f"output_records[{ordinal}].relative_path"
        )
        all_paths.append(path)
        if path.casefold().startswith(ASSET_STREAM_OUTPUT_PREFIX.casefold()):
            if any(existing.casefold() == path.casefold() for existing in actual):
                _fail("output_records", "duplicate/case-colliding streamed path")
            actual[path] = record
    backend = AtlasBackend(
        BC7_ATLAS_BACKEND_KIND,
        parse_bc7_resource_policy(BC7_RESOURCE_POLICY_VALUES),
        index.texture_policy,
        index.quality_policy,
    )
    validate_backend_output_exclusivity(backend, all_paths, index=index)
    expected_paths = set(expected_stream_output_paths_v2(index))
    if set(actual) != expected_paths:
        _fail("output_records", "stream artifact set disagrees with the final V2 index")

    index_record = actual[INDEX_OUTPUT_PATH]
    if _require_string(
        index_record.get("category"), f"output_records[{INDEX_OUTPUT_PATH}].category"
    ) != ASSET_BUNDLE_INDEX_CATEGORY:
        _fail(f"output_records[{INDEX_OUTPUT_PATH}].category", "is not the index category")
    size = _require_int(
        index_record.get("size"), f"output_records[{INDEX_OUTPUT_PATH}].size", minimum=1
    )
    sha = _require_sha256(
        index_record.get("sha256"), f"output_records[{INDEX_OUTPUT_PATH}].sha256"
    )
    if (size, sha) != (index.file_size_bytes, index.file_sha256):
        _fail(f"output_records[{INDEX_OUTPUT_PATH}]", "does not bind final index bytes")
    metadata = _require_mapping(
        index_record.get("metadata"), f"output_records[{INDEX_OUTPUT_PATH}].metadata"
    )
    expected_index_metadata = {
        "kind": BC7_ATLAS_BACKEND_KIND,
        "schema": BC7_INDEX_SCHEMA,
        "build_id": index.build_id,
        "group_count": len(index.groups),
        "vanilla_omitted_group_count": len(index.vanilla_omitted_groups),
        "selected_group_count": len(index.groups) + len(index.vanilla_omitted_groups),
        "index_sha256": index.file_sha256,
        "quality_report_sha256": index.quality_report_sha256,
        "quality_policy_id": index.quality_policy.id,
        "quality_policy_sha256": index.quality_policy.sha256,
        "texture_policy_id": index.texture_policy.id,
        "total_gpu_bytes": index.total_gpu_bytes,
        "total_resident_charge_bytes": index.total_resident_charge_bytes,
        "total_source_rgba_bytes": index.total_source_rgba_bytes,
        "packer_id": index.packer_id,
        "encoder_id": index.encoder_id,
        "unity_version": index.unity.version,
        "unity_revision": index.unity.revision,
        "build_target": index.build_target,
    }
    _require_exact_keys(
        metadata,
        expected_index_metadata,
        f"output_records[{INDEX_OUTPUT_PATH}].metadata",
    )
    if metadata != expected_index_metadata:
        _fail(f"output_records[{INDEX_OUTPUT_PATH}].metadata", "does not bind V2 index")

    report_bundles = {artifact.name: artifact for artifact in report.bundles}
    if len(report_bundles) != len(report.bundles):
        _fail("build report", "contains duplicate V2 bundle names")
    expected_report_bundles = {group.bundle for group in index.groups}
    if set(report_bundles) != expected_report_bundles:
        _fail(
            "build report",
            "bundle set does not exactly match the final V2 index",
        )
    for group in index.groups:
        if (
            group.bundle_path is None
            or group.bundle_size_bytes is None
            or group.bundle_sha256 is None
            or group.bundle_crc32 is None
            or group.unity_hash128 is None
            or group.predicted_load_peak_bytes is None
        ):
            _fail("index", f"group {group.group!r} is not final")
        artifact = report_bundles.get(group.bundle)
        if artifact is None:
            _fail("build report", f"has no V2 bundle {group.bundle!r}")
        path = group.bundle_path
        record = actual[path]
        if _require_string(record.get("category"), f"output_records[{path}].category") != ASSET_BUNDLE_CATEGORY:
            _fail(f"output_records[{path}].category", "is not the bundle category")
        record_size = _require_int(record.get("size"), f"output_records[{path}].size", minimum=1)
        record_sha = _require_sha256(record.get("sha256"), f"output_records[{path}].sha256")
        if (
            (record_size, record_sha) != (artifact.size_bytes, artifact.sha256)
            or (record_size, record_sha)
            != (group.bundle_size_bytes, group.bundle_sha256)
            or artifact.mod_relative_path != group.bundle_path
            or artifact.manifest_hash != group.unity_hash128
        ):
            _fail(f"output_records[{path}]", "disagrees with V2 index/build report")
        bundle_metadata = _require_mapping(
            record.get("metadata"), f"output_records[{path}].metadata"
        )
        expected_bundle_metadata = {
            "kind": BC7_ATLAS_BACKEND_KIND,
            "bundle": group.bundle,
            "group": group.group,
            "gm_id": group.gm_id,
            "unity_hash128": group.unity_hash128,
            "crc32": group.bundle_crc32,
            "gpu_bytes": group.gpu_bytes,
            "source_rgba_bytes": group.source_rgba_bytes,
            "resident_charge_bytes": group.resident_charge_bytes,
            "predicted_load_peak_bytes": group.predicted_load_peak_bytes,
            "texture_policy_id": index.texture_policy.id,
        }
        _require_exact_keys(
            bundle_metadata,
            expected_bundle_metadata,
            f"output_records[{path}].metadata",
        )
        if bundle_metadata != expected_bundle_metadata:
            _fail(f"output_records[{path}].metadata", "does not bind V2 bundle")


def decide_group_admission(
    policy: ResourcePolicy,
    usage: ResourceUsage,
    snapshot: ResourceSnapshot,
    *,
    group: GroupIndexRecord,
    report: AssetBundleBuildReport,
) -> AdmissionDecision:
    """Convenience admission using the exact atlas footprint and bundle size."""

    artifact = report.bundle(group.bundle)
    if (
        artifact.mod_relative_path != group.bundle_path
        or artifact.size_bytes != group.bundle_size_bytes
        or artifact.sha256 != group.bundle_sha256
        or artifact.manifest_hash != group.unity_hash128
    ):
        _fail("group admission", "index and build report bundle metadata disagree")
    return decide_admission(
        policy,
        usage,
        snapshot,
        raw_rgba_bytes=group.raw_rgba_bytes,
        bundle_file_bytes=artifact.size_bytes,
    )


def decide_bc7_group_admission(
    policy: ResourcePolicy,
    usage: ResourceUsage,
    snapshot: ResourceSnapshot,
    *,
    group: GroupIndexRecordV2,
    report: AssetBundleBuildReportV2,
) -> AdmissionDecision:
    """Convenience BC7 V4 admission bound to a final V2 group artifact."""

    if (
        group.bundle_path is None
        or group.bundle_size_bytes is None
        or group.bundle_sha256 is None
        or group.unity_hash128 is None
        or group.predicted_load_peak_bytes is None
    ):
        _fail("BC7 group admission", "group is not a final V2 artifact")
    artifact = report.bundle(group.bundle)
    if (
        artifact.mod_relative_path != group.bundle_path
        or artifact.size_bytes != group.bundle_size_bytes
        or artifact.sha256 != group.bundle_sha256
        or artifact.manifest_hash != group.unity_hash128
    ):
        _fail(
            "BC7 group admission",
            "index and V2 build report bundle metadata disagree",
        )
    decision = decide_bc7_admission(
        policy,
        usage,
        snapshot,
        gpu_bytes=group.gpu_bytes,
        bundle_file_bytes=artifact.size_bytes,
    )
    if (
        decision.charge_bytes != group.resident_charge_bytes
        or decision.peak_bytes != group.predicted_load_peak_bytes
    ):
        _fail("BC7 group admission", "index accounting changed")
    return decision

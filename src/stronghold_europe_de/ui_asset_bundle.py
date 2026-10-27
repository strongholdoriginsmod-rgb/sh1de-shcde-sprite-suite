from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import subprocess
import tempfile
from typing import Any
import unicodedata
import zlib

import numpy as np
from PIL import Image, UnidentifiedImageError, __version__ as PILLOW_VERSION

from .unity_asset_bundle import (
    BUILD_OPTIONS,
    BUILD_TARGET,
    UNITY_REVISION,
    UNITY_VERSION,
    _folder_meta,
    _mono_meta,
    _write_bytes,
    stable_unity_guid,
)
from .workspace_lock import exclusive_workspace_lock


SOURCE_SCHEMA = "stronghold-europe-de.ui-texture-sources.v1"
BUILD_INPUT_SCHEMA = "stronghold-europe-de.ui-asset-bundle-build-input.v1"
BUILD_REPORT_SCHEMA = "stronghold-europe-de.ui-asset-bundle-build-report.v1"
CACHE_RECORD_SCHEMA = "stronghold-europe-de.ui-asset-bundle-cache-record.v1"
RUNTIME_MANIFEST_SCHEMA = "stronghold-europe-ui-textures\t2"
ALPHA_MODE = "premultiply-u8-round-nearest-v1"
BLOCK_PADDING_MODE = "edge-extend-right-bottom-to-bc-block-v1"
TEXTURE_CONTRACT_ID_POINT = "ui-bc7-point-premultiplied-v1"
TEXTURE_CONTRACT_ID_BILINEAR = "ui-bc7-bilinear-premultiplied-v1"
ENCODER_ID = "unity-2021.3.45f2-bc7-hq100-force-max-ui-v1"
UI_BACKEND_KIND = "unity_assetbundle_bc7_direct_ui_v1"
EDITOR_METHOD = (
    "StrongholdEuropeDE.UiAssetBundles."
    "StrongholdEuropeUiTextureBundleBuilder.Build"
)

MAX_ENTRIES = 512
MAX_DIMENSION = 8192
MAX_SOURCE_BYTES = 512 * 1024 * 1024
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_REPORT_BYTES = 32 * 1024 * 1024
MAX_CACHE_RECORD_BYTES = 4 * 1024 * 1024
MAX_TOTAL_GPU_BYTES = 2 * 1024 * 1024 * 1024
RESIDENT_NUMERATOR = 9
RESIDENT_DENOMINATOR = 8
RESIDENT_FIXED_BYTES = 64 * 1024
TRANSIENT_FIXED_BYTES = 64 * 1024 * 1024
TRANSIENT_ALIGNMENT_BYTES = 4 * 1024 * 1024
MAX_TRANSIENT_PEAK_BYTES = 2 * 1024 * 1024 * 1024
QUALITY_POLICY_SCHEMA = "stronghold-europe-de.ui-bc7-quality-policy.v1"
QUALITY_RECORD_SCHEMA = "stronghold-europe-de.ui-bc7-quality-record.v1"
QUALITY_POLICY_ID = "bc7_ui_visual_equivalence_v1"
QUALITY_VERIFIER_ID = "unitypy-1.25.3-ui-bc7-premultiplied-metrics-v1"

_EDITOR_SOURCE_RELATIVE = Path(
    "tools/unity_asset_bundle/StrongholdEuropeUiTextureBundleBuilder.cs"
)
_EDITOR_ASSET_PATH = (
    "Assets/Editor/StrongholdEuropeUiTextureBundleBuilder.cs"
)
_BUILD_INPUT_RELATIVE = Path("ui-build-input.v1.json")
_OUTPUT_RELATIVE = Path("output/Runtime/UiAssetBundles/win64")
_REPORT_RELATIVE = Path("output/ui-build-report.v1.json")
_MOD_BUNDLE_ROOT = PurePosixPath("Runtime/UiAssetBundles/win64")
_MOD_RUNTIME_MANIFEST = PurePosixPath("Runtime/ui-textures-v2.tsv")
_PROJECT_TEXTURE_ROOT = PurePosixPath("Assets/Generated/UiTextures")
_PROJECT_CONTAINER_DIRECTORY = "unity-ui-ab"
_CACHE_DIRECTORY = Path("ui-asset-bundles/v1")
_PROFILE_SOURCE_MANIFEST_PATH = "config/ui-textures-bc7-v1.json"
_PROFILE_QUALITY_POLICY_PATH = "config/ui-bc7-quality-v1.json"
_PROFILE_EDITOR_SOURCE_PATH = (
    "tools/unity_asset_bundle/StrongholdEuropeUiTextureBundleBuilder.cs"
)
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_HASH128_RE = re.compile(r"[0-9a-f]{32}\Z")
_CRC32_RE = re.compile(r"[0-9a-f]{8}\Z")
_ID_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,95}\Z")
_HASH16_RE = re.compile(r"[0-9a-f]{16}\Z")
_BUNDLE_RE = re.compile(r"sede\.ui\.[0-9a-f]{16}\.bc7\.v1\Z")

_SOURCE_ROOT_KEYS = {
    "alpha_mode",
    "entries",
    "expected_entry_count",
    "expected_entry_set_sha256",
    "schema",
    "texture_contract",
}
_SOURCE_ENTRY_KEYS = {
    "bundle",
    "expected_source_sha256",
    "filter_mode",
    "height",
    "id",
    "noesis_path",
    "source",
    "source_kind",
    "width",
}
_TEXTURE_CONTRACT = {
    "alpha_is_transparency": False,
    "aniso_level": 0,
    "bc_block_padding": BLOCK_PADDING_MODE,
    "compression": "BC7-HQ100-force-maximum",
    "format": "BC7",
    "mipmaps": False,
    "npot_scale": "None",
    "readable": False,
    "s_rgb": True,
    "wrap_mode": "Clamp",
}


class UiAssetBundleError(RuntimeError):
    """Raised when UI texture packaging cannot be proven exact."""


@dataclass(frozen=True)
class UiTextureSourceEntry:
    id: str
    noesis_path: str
    source_kind: str
    source: str
    expected_source_sha256: str
    width: int
    height: int
    filter_mode: str
    bundle: str

    @property
    def path_hash16(self) -> str:
        return sha256(self.noesis_path.encode("utf-8")).hexdigest()[:16]

    @property
    def bundle_name(self) -> str:
        return f"sede.ui.{self.path_hash16}.bc7.v1"

    @property
    def address(self) -> str:
        return f"sede/ui/{self.path_hash16}/texture"

    @property
    def texture_name(self) -> str:
        return self.path_hash16

    @property
    def asset_path(self) -> str:
        return f"{_PROJECT_TEXTURE_ROOT.as_posix()}/{self.path_hash16}.png"

    @property
    def gpu_bytes(self) -> int:
        return bc7_gpu_bytes(self.storage_width, self.storage_height)

    @property
    def storage_width(self) -> int:
        return (self.width + 3) // 4 * 4

    @property
    def storage_height(self) -> int:
        return (self.height + 3) // 4 * 4

    @property
    def resident_charge_bytes(self) -> int:
        return resident_charge_bytes(self.gpu_bytes)

    @property
    def texture_contract_id(self) -> str:
        return texture_contract_id(self.filter_mode)


@dataclass(frozen=True)
class UiTextureSourceManifest:
    path: Path
    entries: tuple[UiTextureSourceEntry, ...]
    sha256: str
    entry_set_sha256: str


@dataclass(frozen=True)
class UiTexturePackagePlan:
    entry: UiTextureSourceEntry
    source_path: Path
    source_png_sha256: str
    package_key: str


@dataclass(frozen=True)
class PreparedUiTexture:
    plan: UiTexturePackagePlan
    entry: UiTextureSourceEntry
    source_path: Path
    asset_path: str
    premultiplied_png_path: Path
    source_png_sha256: str
    source_rgba_sha256: str
    premultiplied_png_sha256: str
    premultiplied_rgba_sha256: str
    package_key: str


@dataclass(frozen=True)
class PreparedUiBundleProject:
    workspace_root: Path
    build_root: Path
    project_path: Path
    build_input_path: Path
    output_path: Path
    report_path: Path
    log_path: Path
    build_id: str
    textures: tuple[PreparedUiTexture, ...]
    editor_source_sha256: str


@dataclass(frozen=True)
class UiBundleArtifact:
    entry_id: str
    bundle_name: str
    mod_relative_path: str
    size_bytes: int
    sha256: str
    crc32: str
    unity_hash128: str
    package_key: str


@dataclass(frozen=True)
class UiQualityMetric:
    channels: int
    samples_per_channel: int
    max_abs: tuple[int, ...]
    absolute_error_sum: tuple[int, ...]
    squared_error_sum: tuple[int, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "absolute_error_sum": list(self.absolute_error_sum),
            "channels": self.channels,
            "max_abs": list(self.max_abs),
            "samples_per_channel": self.samples_per_channel,
            "squared_error_sum": list(self.squared_error_sum),
        }


@dataclass(frozen=True)
class UiTextureQualityEvidence:
    entry_id: str
    noesis_path: str
    source_rgba_sha256: str
    decoded_rgba_sha256: str
    metrics: Mapping[str, UiQualityMetric]

    def as_dict(self) -> dict[str, object]:
        return {
            "decoded_rgba_sha256": self.decoded_rgba_sha256,
            "entry_id": self.entry_id,
            "metrics": {
                key: self.metrics[key].as_dict() for key in sorted(self.metrics)
            },
            "noesis_path": self.noesis_path,
            "source_rgba_sha256": self.source_rgba_sha256,
        }


@dataclass(frozen=True)
class UiQualityPolicy:
    path: Path
    sha256: str
    envelope: Mapping[str, object]


@dataclass(frozen=True)
class CachedUiBundle:
    artifact: UiBundleArtifact
    bundle_path: Path
    quality_path: Path
    quality_sha256: str
    source_rgba_sha256: str
    premultiplied_rgba_sha256: str


@dataclass(frozen=True)
class UiRuntimePayload:
    manifest_path: Path
    manifest_sha256: str
    manifest_size_bytes: int
    bundles: tuple[UiBundleArtifact, ...]
    removed_png_paths: tuple[str, ...]
    declared_gpu_bytes: int
    declared_resident_charge_bytes: int


@dataclass(frozen=True)
class UiUnityBuildResult:
    build_id: str
    build_input_sha256: str
    artifacts: tuple[UiBundleArtifact, ...]


@dataclass(frozen=True)
class UiTextureBuildResult:
    runtime: UiRuntimePayload
    cache_hit_count: int
    cache_miss_count: int
    unity_build_root: Path | None


@dataclass(frozen=True)
class UiTextureBackendSelection:
    source_manifest_path: Path
    source_manifest_sha256: str
    quality_policy_path: Path
    quality_policy_sha256: str
    editor_source_path: Path
    editor_source_sha256: str
    expected_entry_count: int


def _reject_duplicate_pairs(
    pairs: Sequence[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise UiAssetBundleError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _canonical_json_bytes(value: object, *, final_lf: bool) -> bytes:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return payload + (b"\n" if final_lf else b"")


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
    return f"{value & 0xffffffff:08x}"


def _is_reparse_or_link(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        attributes = int(path.stat().st_file_attributes)
    except AttributeError:
        return False
    return bool(attributes & 0x400)


def _read_exact_file(path: Path, maximum_bytes: int, label: str) -> bytes:
    candidate = Path(path)
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise UiAssetBundleError(f"{label} does not exist: {candidate}") from exc
    if resolved != candidate or not resolved.is_file() or resolved.is_symlink():
        raise UiAssetBundleError(
            f"{label} must be a canonical non-linked regular file: {candidate}"
        )
    size = resolved.stat().st_size
    if not 1 <= size <= maximum_bytes:
        raise UiAssetBundleError(f"{label} has an unsupported byte size: {size}")
    before = (size, resolved.stat().st_mtime_ns)
    payload = resolved.read_bytes()
    after_stat = resolved.stat()
    after = (after_stat.st_size, after_stat.st_mtime_ns)
    if before != after or len(payload) != size:
        raise UiAssetBundleError(f"{label} changed while it was read")
    return payload


def _read_json_object(path: Path, maximum_bytes: int, label: str) -> tuple[dict[str, Any], bytes]:
    payload = _read_exact_file(path, maximum_bytes, label)
    try:
        value = json.loads(
            payload.decode("utf-8", errors="strict"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=lambda token: (_ for _ in ()).throw(
                UiAssetBundleError(f"Non-finite JSON value: {token}")
            ),
        )
    except UiAssetBundleError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UiAssetBundleError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise UiAssetBundleError(f"{label} root must be an object")
    return value, payload


def _read_canonical_json_object(
    path: Path,
    maximum_bytes: int,
    label: str,
) -> tuple[dict[str, Any], bytes]:
    value, payload = _read_json_object(path, maximum_bytes, label)
    if payload != _canonical_json_bytes(value, final_lf=True):
        raise UiAssetBundleError(f"{label} is not canonical JSON")
    return value, payload


def _require_nfc_string(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != unicodedata.normalize("NFC", value)
        or "\x00" in value
        or "\r" in value
        or "\n" in value
        or "\t" in value
    ):
        raise UiAssetBundleError(f"{label} must be a nonempty NFC string")
    return value


def _safe_relative_path(value: object, label: str) -> str:
    text = _require_nfc_string(value, label)
    if (
        "\\" in text
        or PurePosixPath(text).is_absolute()
        or PureWindowsPath(text).is_absolute()
        or text.startswith("/")
        or "//" in text
        or text.endswith("/")
    ):
        raise UiAssetBundleError(f"{label} is not a canonical relative path")
    parts = PurePosixPath(text).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise UiAssetBundleError(f"{label} contains an unsafe path component")
    return text


def _require_noesis_path(value: object, label: str) -> str:
    path = _safe_relative_path(value, label)
    if not path.startswith("Assets/GUI/") or not path.endswith(".png"):
        raise UiAssetBundleError(
            f"{label} must be an exact Assets/GUI/*.png path"
        )
    return path


def _require_dimension(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_DIMENSION:
        raise UiAssetBundleError(f"{label} must be in 1..{MAX_DIMENSION}")
    return value


def _require_sha256(value: object, label: str) -> str:
    text = _require_nfc_string(value, label)
    if _SHA256_RE.fullmatch(text) is None:
        raise UiAssetBundleError(f"{label} must be lowercase SHA-256")
    return text


def bc7_gpu_bytes(width: int, height: int) -> int:
    if (
        isinstance(width, bool)
        or not isinstance(width, int)
        or isinstance(height, bool)
        or not isinstance(height, int)
        or not 1 <= width <= MAX_DIMENSION
        or not 1 <= height <= MAX_DIMENSION
    ):
        raise UiAssetBundleError("BC7 dimensions are out of range")
    return ((width + 3) // 4) * ((height + 3) // 4) * 16


def resident_charge_bytes(gpu_bytes: int) -> int:
    if isinstance(gpu_bytes, bool) or not isinstance(gpu_bytes, int) or gpu_bytes <= 0:
        raise UiAssetBundleError("UI GPU byte count is invalid")
    return (
        (gpu_bytes * RESIDENT_NUMERATOR + RESIDENT_DENOMINATOR - 1)
        // RESIDENT_DENOMINATOR
        + RESIDENT_FIXED_BYTES
    )


def transient_peak_bytes(gpu_bytes: int, bundle_size_bytes: int) -> int:
    if (
        isinstance(bundle_size_bytes, bool)
        or not isinstance(bundle_size_bytes, int)
        or bundle_size_bytes <= 0
    ):
        raise UiAssetBundleError("UI bundle byte count is invalid")
    raw = 2 * gpu_bytes + bundle_size_bytes + TRANSIENT_FIXED_BYTES
    aligned = (
        (raw + TRANSIENT_ALIGNMENT_BYTES - 1)
        // TRANSIENT_ALIGNMENT_BYTES
        * TRANSIENT_ALIGNMENT_BYTES
    )
    if aligned > MAX_TRANSIENT_PEAK_BYTES:
        raise UiAssetBundleError("UI bundle transient peak exceeds the 2-GiB bound")
    return aligned


def texture_contract_id(filter_mode: str) -> str:
    if filter_mode == "Point":
        return TEXTURE_CONTRACT_ID_POINT
    if filter_mode == "Bilinear":
        return TEXTURE_CONTRACT_ID_BILINEAR
    raise UiAssetBundleError(f"Unsupported UI filter mode: {filter_mode!r}")


def entry_set_sha256(entries: Iterable[UiTextureSourceEntry]) -> str:
    rows = [
        {"id": entry.id, "noesis_path": entry.noesis_path}
        for entry in sorted(entries, key=lambda item: item.id)
    ]
    return sha256(_canonical_json_bytes(rows, final_lf=False)).hexdigest()


def load_ui_texture_source_manifest(path: Path) -> UiTextureSourceManifest:
    resolved = Path(path).resolve(strict=True)
    value, payload = _read_json_object(
        resolved,
        MAX_MANIFEST_BYTES,
        "UI texture source manifest",
    )
    if set(value) != _SOURCE_ROOT_KEYS:
        raise UiAssetBundleError("UI texture source manifest root keys changed")
    if value["schema"] != SOURCE_SCHEMA or value["alpha_mode"] != ALPHA_MODE:
        raise UiAssetBundleError("UI texture source manifest identity changed")
    if value["texture_contract"] != _TEXTURE_CONTRACT:
        raise UiAssetBundleError("UI texture source contract changed")
    raw_entries = value["entries"]
    expected_count = value["expected_entry_count"]
    if (
        isinstance(expected_count, bool)
        or not isinstance(expected_count, int)
        or not 1 <= expected_count <= MAX_ENTRIES
        or not isinstance(raw_entries, list)
        or len(raw_entries) != expected_count
    ):
        raise UiAssetBundleError("UI texture entry count changed")
    entries: list[UiTextureSourceEntry] = []
    ids: set[str] = set()
    noesis_paths: set[str] = set()
    bundles: set[str] = set()
    source_paths: set[tuple[str, str]] = set()
    for index, raw in enumerate(raw_entries):
        label = f"entries[{index}]"
        if not isinstance(raw, dict) or set(raw) != _SOURCE_ENTRY_KEYS:
            raise UiAssetBundleError(f"{label} keys changed")
        entry_id = _require_nfc_string(raw["id"], f"{label}.id")
        if _ID_RE.fullmatch(entry_id) is None:
            raise UiAssetBundleError(f"{label}.id is not a safe identifier")
        noesis_path = _require_noesis_path(
            raw["noesis_path"], f"{label}.noesis_path"
        )
        source_kind = _require_nfc_string(
            raw["source_kind"], f"{label}.source_kind"
        )
        if source_kind not in {"profile_output", "private_work_file"}:
            raise UiAssetBundleError(f"{label}.source_kind is unsupported")
        source = _safe_relative_path(raw["source"], f"{label}.source")
        if source_kind == "profile_output":
            expected_source = "Override/" + noesis_path
            if source != expected_source:
                raise UiAssetBundleError(
                    f"{label}.source must equal its exact profile output path"
                )
        elif not source.startswith("work/private-inputs/"):
            raise UiAssetBundleError(
                f"{label}.source must remain below work/private-inputs"
            )
        filter_mode = _require_nfc_string(
            raw["filter_mode"], f"{label}.filter_mode"
        )
        texture_contract_id(filter_mode)
        entry = UiTextureSourceEntry(
            id=entry_id,
            noesis_path=noesis_path,
            source_kind=source_kind,
            source=source,
            expected_source_sha256=_require_sha256(
                raw["expected_source_sha256"],
                f"{label}.expected_source_sha256",
            ),
            width=_require_dimension(raw["width"], f"{label}.width"),
            height=_require_dimension(raw["height"], f"{label}.height"),
            filter_mode=filter_mode,
            bundle=_require_nfc_string(raw["bundle"], f"{label}.bundle"),
        )
        if entry.bundle != "per_entry_v1":
            raise UiAssetBundleError(f"{label}.bundle must be per_entry_v1")
        folded = entry.noesis_path.casefold()
        source_key = (entry.source_kind, entry.source.casefold())
        if (
            entry.id in ids
            or folded in noesis_paths
            or entry.bundle_name in bundles
            or source_key in source_paths
        ):
            raise UiAssetBundleError(f"{label} collides with another UI entry")
        ids.add(entry.id)
        noesis_paths.add(folded)
        bundles.add(entry.bundle_name)
        source_paths.add(source_key)
        entries.append(entry)
    if entries != sorted(entries, key=lambda item: item.id):
        raise UiAssetBundleError("UI texture entries are not ordered by id")
    actual_set_sha = entry_set_sha256(entries)
    if _require_sha256(
        value["expected_entry_set_sha256"],
        "expected_entry_set_sha256",
    ) != actual_set_sha:
        raise UiAssetBundleError("UI texture entry set digest changed")
    if sum(entry.gpu_bytes for entry in entries) > MAX_TOTAL_GPU_BYTES:
        raise UiAssetBundleError("UI texture source set exceeds the 2-GiB GPU bound")
    return UiTextureSourceManifest(
        path=resolved,
        entries=tuple(entries),
        sha256=sha256(payload).hexdigest(),
        entry_set_sha256=actual_set_sha,
    )


def resolve_source_path(
    entry: UiTextureSourceEntry,
    *,
    workspace_root: Path,
    mod_root: Path,
) -> Path:
    root = mod_root if entry.source_kind == "profile_output" else workspace_root
    root = Path(root).resolve(strict=True)
    candidate = root.joinpath(*PurePosixPath(entry.source).parts)
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise UiAssetBundleError(
            f"UI texture source does not exist: {entry.source}"
        ) from exc
    prefix = str(root).rstrip("\\/") + os.sep
    if (
        resolved != candidate
        or resolved.is_symlink()
        or not resolved.is_file()
        or not str(resolved).startswith(prefix)
    ):
        raise UiAssetBundleError(
            f"UI texture source escaped or is linked: {entry.source}"
        )
    return resolved


def _rgba_sha256_image(image: Image.Image, rows_per_chunk: int = 64) -> str:
    if image.mode != "RGBA" or image.width <= 0 or image.height <= 0:
        raise UiAssetBundleError("RGBA digest requires a positive RGBA image")
    digest = sha256()
    for top in range(0, image.height, rows_per_chunk):
        bottom = min(top + rows_per_chunk, image.height)
        with image.crop((0, top, image.width, bottom)) as strip:
            digest.update(strip.tobytes())
    return digest.hexdigest()


def _metric_from_chunks(
    *,
    channels: int,
    samples: int,
    maximum: np.ndarray,
    absolute_sum: np.ndarray,
    squared_sum: np.ndarray,
) -> UiQualityMetric:
    return UiQualityMetric(
        channels=channels,
        samples_per_channel=samples,
        max_abs=tuple(int(value) for value in maximum.tolist()),
        absolute_error_sum=tuple(int(value) for value in absolute_sum.tolist()),
        squared_error_sum=tuple(int(value) for value in squared_sum.tolist()),
    )


def measure_ui_texture_quality(
    texture: PreparedUiTexture,
    decoded: Image.Image,
    *,
    rows_per_chunk: int = 32,
) -> UiTextureQualityEvidence:
    """Compare premultiplied source pixels directly with decoded BC7 pixels."""

    if (
        decoded.mode != "RGBA"
        or decoded.size
        != (texture.entry.storage_width, texture.entry.storage_height)
        or isinstance(rows_per_chunk, bool)
        or not isinstance(rows_per_chunk, int)
        or rows_per_chunk <= 0
    ):
        raise UiAssetBundleError("UI BC7 quality inputs differ in shape")
    source_path = texture.premultiplied_png_path.resolve(strict=True)
    try:
        with Image.open(source_path) as opened:
            opened.load()
            if opened.format != "PNG" or opened.mode != "RGBA":
                raise UiAssetBundleError("Prepared UI quality source is not RGBA PNG")
            source = opened.copy()
    except UiAssetBundleError:
        raise
    except (OSError, UnidentifiedImageError) as exc:
        raise UiAssetBundleError("Prepared UI quality source cannot be decoded") from exc

    metric_shapes = {
        "alpha": 1,
        "composite_black": 3,
        "composite_desert": 3,
        "composite_white": 3,
        "premultiplied_rgb": 3,
    }
    maxima = {
        name: np.zeros(channels, dtype=np.uint16)
        for name, channels in metric_shapes.items()
    }
    absolute_sums = {
        name: np.zeros(channels, dtype=np.uint64)
        for name, channels in metric_shapes.items()
    }
    squared_sums = {
        name: np.zeros(channels, dtype=np.uint64)
        for name, channels in metric_shapes.items()
    }
    source_digest = sha256()
    decoded_digest = sha256()

    def add_metric(name: str, left: np.ndarray, right: np.ndarray) -> None:
        difference = np.abs(left.astype(np.int16) - right.astype(np.int16)).astype(
            np.uint16
        )
        flattened = difference.reshape(-1, difference.shape[-1])
        maxima[name] = np.maximum(maxima[name], flattened.max(axis=0))
        absolute_sums[name] += flattened.sum(axis=0, dtype=np.uint64)
        squared = flattened.astype(np.uint32) * flattened.astype(np.uint32)
        squared_sums[name] += squared.sum(axis=0, dtype=np.uint64)

    backgrounds = {
        "composite_black": np.array([0, 0, 0], dtype=np.uint16),
        "composite_desert": np.array([181, 148, 104], dtype=np.uint16),
        "composite_white": np.array([255, 255, 255], dtype=np.uint16),
    }
    try:
        for top in range(0, source.height, rows_per_chunk):
            bottom = min(top + rows_per_chunk, source.height)
            box = (0, top, source.width, bottom)
            with source.crop(box) as source_strip, decoded.crop(box) as decoded_strip:
                source_u8 = np.asarray(source_strip, dtype=np.uint8).copy()
                decoded_u8 = np.asarray(decoded_strip, dtype=np.uint8).copy()
            source_digest.update(source_u8.tobytes())
            decoded_digest.update(decoded_u8.tobytes())
            source16 = source_u8.astype(np.uint16)
            decoded16 = decoded_u8.astype(np.uint16)
            add_metric(
                "alpha",
                source16[:, :, 3:4],
                decoded16[:, :, 3:4],
            )
            add_metric(
                "premultiplied_rgb",
                source16[:, :, :3],
                decoded16[:, :, :3],
            )
            for name, background in backgrounds.items():
                source_composite = np.minimum(
                    255,
                    source16[:, :, :3]
                    + (
                        background.reshape((1, 1, 3))
                        * (255 - source16[:, :, 3:4])
                        + 127
                    )
                    // 255,
                )
                decoded_composite = np.minimum(
                    255,
                    decoded16[:, :, :3]
                    + (
                        background.reshape((1, 1, 3))
                        * (255 - decoded16[:, :, 3:4])
                        + 127
                    )
                    // 255,
                )
                add_metric(name, source_composite, decoded_composite)
    finally:
        source.close()
    source_sha = source_digest.hexdigest()
    if source_sha != texture.premultiplied_rgba_sha256:
        raise UiAssetBundleError("Prepared UI quality source RGBA digest changed")
    samples = texture.entry.storage_width * texture.entry.storage_height
    return UiTextureQualityEvidence(
        entry_id=texture.entry.id,
        noesis_path=texture.entry.noesis_path,
        source_rgba_sha256=source_sha,
        decoded_rgba_sha256=decoded_digest.hexdigest(),
        metrics={
            name: _metric_from_chunks(
                channels=channels,
                samples=samples,
                maximum=maxima[name],
                absolute_sum=absolute_sums[name],
                squared_sum=squared_sums[name],
            )
            for name, channels in sorted(metric_shapes.items())
        },
    )


def load_ui_quality_policy(path: Path) -> UiQualityPolicy:
    resolved = Path(path).resolve(strict=True)
    value, payload = _read_json_object(
        resolved,
        MAX_MANIFEST_BYTES,
        "UI BC7 quality policy",
    )
    if set(value) != {
        "acceptance_envelope",
        "id",
        "mode",
        "schema",
        "verifier_id",
    }:
        raise UiAssetBundleError("UI BC7 quality policy root keys changed")
    if (
        value["schema"] != QUALITY_POLICY_SCHEMA
        or value["id"] != QUALITY_POLICY_ID
        or value["mode"] != "frozen"
        or value["verifier_id"] != QUALITY_VERIFIER_ID
    ):
        raise UiAssetBundleError("UI BC7 quality policy identity changed")
    envelope = value["acceptance_envelope"]
    expected_channels = {
        "alpha": 1,
        "composite_black": 3,
        "composite_desert": 3,
        "composite_white": 3,
        "premultiplied_rgb": 3,
    }
    if not isinstance(envelope, dict) or set(envelope) != set(expected_channels):
        raise UiAssetBundleError("UI BC7 quality envelope metric set changed")
    for metric_name, channels in expected_channels.items():
        raw = envelope[metric_name]
        if not isinstance(raw, dict) or set(raw) != {
            "max_abs",
            "maximum_absolute_error_sum_per_sample",
            "maximum_squared_error_sum_per_sample",
        }:
            raise UiAssetBundleError(
                f"UI BC7 quality envelope changed: {metric_name}"
            )
        for key in (
            "max_abs",
            "maximum_absolute_error_sum_per_sample",
            "maximum_squared_error_sum_per_sample",
        ):
            values = raw[key]
            if (
                not isinstance(values, list)
                or len(values) != channels
                or any(
                    isinstance(item, bool)
                    or not isinstance(item, int)
                    or item < 0
                    for item in values
                )
            ):
                raise UiAssetBundleError(
                    f"UI BC7 quality envelope values changed: {metric_name}.{key}"
                )
    return UiQualityPolicy(
        path=resolved,
        sha256=sha256(payload).hexdigest(),
        envelope=envelope,
    )


def load_ui_texture_backend_selection(
    workspace_root: Path,
    profile: Mapping[str, object],
) -> UiTextureBackendSelection | None:
    raw = profile.get("ui_texture_backend")
    if raw is None:
        return None
    if not isinstance(raw, dict) or set(raw) != {
        "editor_source_path",
        "editor_source_sha256",
        "expected_entry_count",
        "kind",
        "quality_policy_path",
        "quality_policy_sha256",
        "source_manifest_path",
        "source_manifest_sha256",
    }:
        raise UiAssetBundleError("ui_texture_backend fields changed")
    if raw["kind"] != UI_BACKEND_KIND:
        raise UiAssetBundleError("ui_texture_backend kind changed")
    source_relative = _safe_relative_path(
        raw["source_manifest_path"], "ui_texture_backend.source_manifest_path"
    )
    quality_relative = _safe_relative_path(
        raw["quality_policy_path"], "ui_texture_backend.quality_policy_path"
    )
    editor_relative = _safe_relative_path(
        raw["editor_source_path"], "ui_texture_backend.editor_source_path"
    )
    if (
        source_relative != _PROFILE_SOURCE_MANIFEST_PATH
        or quality_relative != _PROFILE_QUALITY_POLICY_PATH
        or editor_relative != _PROFILE_EDITOR_SOURCE_PATH
    ):
        raise UiAssetBundleError("ui_texture_backend canonical paths changed")
    expected_count = raw["expected_entry_count"]
    if (
        isinstance(expected_count, bool)
        or not isinstance(expected_count, int)
        or not 1 <= expected_count <= MAX_ENTRIES
    ):
        raise UiAssetBundleError("ui_texture_backend entry count is invalid")
    root = Path(workspace_root).resolve(strict=True)
    source_path = root.joinpath(*PurePosixPath(source_relative).parts)
    quality_path = root.joinpath(*PurePosixPath(quality_relative).parts)
    editor_path = root.joinpath(*PurePosixPath(editor_relative).parts)
    source = load_ui_texture_source_manifest(source_path)
    quality = load_ui_quality_policy(quality_path)
    editor_sha = sha256(
        _read_exact_file(editor_path, 4 * 1024 * 1024, "UI Unity editor builder")
    ).hexdigest()
    source_pin = _require_sha256(
        raw["source_manifest_sha256"],
        "ui_texture_backend.source_manifest_sha256",
    )
    quality_pin = _require_sha256(
        raw["quality_policy_sha256"],
        "ui_texture_backend.quality_policy_sha256",
    )
    editor_pin = _require_sha256(
        raw["editor_source_sha256"],
        "ui_texture_backend.editor_source_sha256",
    )
    if (
        len(source.entries) != expected_count
        or source.sha256 != source_pin
        or quality.sha256 != quality_pin
        or editor_sha != editor_pin
    ):
        raise UiAssetBundleError("ui_texture_backend pinned input changed")
    return UiTextureBackendSelection(
        source_manifest_path=source.path,
        source_manifest_sha256=source.sha256,
        quality_policy_path=quality.path,
        quality_policy_sha256=quality.sha256,
        editor_source_path=editor_path,
        editor_source_sha256=editor_sha,
        expected_entry_count=expected_count,
    )


def build_ui_quality_record(
    evidence: UiTextureQualityEvidence,
    *,
    texture: PreparedUiTexture,
    artifact: UiBundleArtifact,
    policy: UiQualityPolicy,
) -> tuple[bytes, dict[str, object]]:
    failures: list[dict[str, object]] = []
    for metric_name, metric in evidence.metrics.items():
        limits = policy.envelope[metric_name]
        for channel in range(metric.channels):
            if (
                metric.max_abs[channel] > limits["max_abs"][channel]
                or metric.absolute_error_sum[channel]
                > limits["maximum_absolute_error_sum_per_sample"][channel]
                * metric.samples_per_channel
                or metric.squared_error_sum[channel]
                > limits["maximum_squared_error_sum_per_sample"][channel]
                * metric.samples_per_channel
            ):
                failures.append(
                    {"channel": channel, "metric": metric_name}
                )
    document: dict[str, object] = {
        "accepted": not failures,
        "bundle_sha256": artifact.sha256,
        "bundle_size_bytes": artifact.size_bytes,
        "encoder_id": ENCODER_ID,
        "entry_id": texture.entry.id,
        "evidence": evidence.as_dict(),
        "failure_count": len(failures),
        "failures": failures,
        "package_key": texture.package_key,
        "quality_policy_id": QUALITY_POLICY_ID,
        "quality_policy_sha256": policy.sha256,
        "schema": QUALITY_RECORD_SCHEMA,
        "texture_contract_id": texture.entry.texture_contract_id,
        "verifier_id": QUALITY_VERIFIER_ID,
    }
    payload = _canonical_json_bytes(document, final_lf=True)
    if len(payload) > MAX_CACHE_RECORD_BYTES:
        raise UiAssetBundleError("UI quality record exceeds its exact bound")
    return payload, document


def validate_ui_bundle_payload(
    bundle_path: Path,
    texture: PreparedUiTexture,
) -> Image.Image:
    """Validate one direct Texture2D bundle and return a decoded RGBA copy."""

    try:
        import UnityPy
    except ImportError as exc:  # pragma: no cover - prerequisite pin guards this
        raise UiAssetBundleError(
            "UnityPy 1.25.3 is required for UI BC7 verification"
        ) from exc
    path = Path(bundle_path).resolve(strict=True)
    try:
        environment = UnityPy.load(str(path))
        readers = tuple(environment.objects)
    except Exception as exc:
        raise UiAssetBundleError(
            f"UI AssetBundle could not be decoded: {path.name}"
        ) from exc
    by_path_id: dict[int, object] = {}
    bundle_readers: list[object] = []
    for reader in readers:
        path_id = getattr(reader, "path_id", None)
        if not isinstance(path_id, int) or path_id in by_path_id:
            raise UiAssetBundleError("UI AssetBundle has invalid object ids")
        by_path_id[path_id] = reader
        if getattr(getattr(reader, "type", None), "name", None) == "AssetBundle":
            bundle_readers.append(reader)
    if len(bundle_readers) != 1:
        raise UiAssetBundleError("UI bundle does not contain exactly one AssetBundle")
    try:
        bundle = bundle_readers[0].read()
        container = tuple(bundle.m_Container)
        dependencies = tuple(bundle.m_Dependencies)
    except Exception as exc:
        raise UiAssetBundleError("UI AssetBundle metadata cannot be read") from exc
    if (
        getattr(bundle, "m_Name", None) != texture.entry.bundle_name
        or getattr(bundle, "m_AssetBundleName", None) != texture.entry.bundle_name
        or dependencies
        or bool(getattr(bundle, "m_IsStreamedSceneAssetBundle", True))
        or len(container) != 1
    ):
        raise UiAssetBundleError("UI AssetBundle identity/dependencies changed")
    try:
        address = container[0][0]
        path_id = container[0][1].asset.m_PathID
    except Exception as exc:
        raise UiAssetBundleError("UI AssetBundle address map is malformed") from exc
    reader = by_path_id.get(path_id)
    if (
        address != texture.entry.address
        or reader is None
        or getattr(getattr(reader, "type", None), "name", None) != "Texture2D"
        or len(readers) != 2
    ):
        raise UiAssetBundleError("UI AssetBundle address/object set changed")
    decoded: Image.Image | None = None
    try:
        value = reader.read()
        settings = value.m_TextureSettings
        image = value.image
        stream = getattr(value, "m_StreamData", None)
        stream_size = int(getattr(stream, "size", 0)) if stream is not None else 0
        stream_path = str(getattr(stream, "path", "")) if stream is not None else ""
        inline = getattr(value, "m_ImageData", None)
        inline_size = (
            len(inline)
            if isinstance(inline, (bytes, bytearray, memoryview))
            else 0
        )
        expected_filter = 0 if texture.entry.filter_mode == "Point" else 1
        payload_exact = (
            stream_size == texture.entry.gpu_bytes and bool(stream_path)
        ) or (stream_size == 0 and inline_size == texture.entry.gpu_bytes)
        if (
            getattr(value, "m_Name", None) != texture.entry.texture_name
            or int(value.m_Width) != texture.entry.storage_width
            or int(value.m_Height) != texture.entry.storage_height
            or int(value.m_TextureFormat) != 25
            or int(getattr(value, "m_ColorSpace", -1)) != 1
            or int(value.m_MipCount) != 1
            or bool(value.m_IsReadable)
            or int(getattr(value, "m_CompleteImageSize", -1))
            != texture.entry.gpu_bytes
            or not payload_exact
            or int(settings.m_FilterMode) != expected_filter
            or int(settings.m_Aniso) != 0
            or int(settings.m_WrapU) != 1
            or int(settings.m_WrapV) != 1
            or int(settings.m_WrapW) != 1
            or image.mode != "RGBA"
            or image.size
            != (texture.entry.storage_width, texture.entry.storage_height)
        ):
            raise UiAssetBundleError("UI Texture2D runtime contract changed")
        decoded = image.copy()
    except UiAssetBundleError:
        raise
    except Exception as exc:
        raise UiAssetBundleError("UI Texture2D could not be decoded") from exc
    finally:
        try:
            image.close()
        except (NameError, AttributeError):
            pass
    if decoded is None:  # pragma: no cover - defensive after exact branches
        raise UiAssetBundleError("UI Texture2D decoder returned no image")
    return decoded


def premultiply_rgba_exact(
    source: Image.Image,
    *,
    rows_per_chunk: int = 64,
) -> Image.Image:
    """Premultiply RGB by alpha with exact round-to-nearest u8 arithmetic."""

    if source.mode != "RGBA" or source.width <= 0 or source.height <= 0:
        raise UiAssetBundleError("UI premultiplication requires a positive RGBA image")
    if isinstance(rows_per_chunk, bool) or not isinstance(rows_per_chunk, int) or rows_per_chunk <= 0:
        raise UiAssetBundleError("UI premultiplication row chunk is invalid")
    output = Image.new("RGBA", source.size, (0, 0, 0, 0))
    for top in range(0, source.height, rows_per_chunk):
        bottom = min(top + rows_per_chunk, source.height)
        with source.crop((0, top, source.width, bottom)) as strip:
            values = np.asarray(strip, dtype=np.uint8).astype(np.uint16)
        alpha = values[:, :, 3:4]
        values[:, :, :3] = (values[:, :, :3] * alpha + 127) // 255
        values8 = values.astype(np.uint8)
        with Image.fromarray(values8, mode="RGBA") as premultiplied:
            output.paste(premultiplied, (0, top))
    return output


def pad_rgba_to_bc_blocks(source: Image.Image) -> Image.Image:
    """Edge-extend an RGBA texture to physical dimensions divisible by four."""

    if source.mode != "RGBA" or source.width <= 0 or source.height <= 0:
        raise UiAssetBundleError("UI BC block padding requires positive RGBA input")
    width = (source.width + 3) // 4 * 4
    height = (source.height + 3) // 4 * 4
    output = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    output.paste(source, (0, 0))
    if width != source.width:
        with source.crop((source.width - 1, 0, source.width, source.height)) as edge:
            with edge.resize(
                (width - source.width, source.height),
                resample=Image.Resampling.NEAREST,
            ) as extended:
                output.paste(extended, (source.width, 0))
    if height != source.height:
        with output.crop((0, source.height - 1, width, source.height)) as edge:
            with edge.resize(
                (width, height - source.height),
                resample=Image.Resampling.NEAREST,
            ) as extended:
                output.paste(extended, (0, source.height))
    return output


def _write_png(path: Path, image: Image.Image) -> str:
    if image.mode != "RGBA":
        raise UiAssetBundleError("Generated UI texture is not RGBA")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        image.save(stream, format="PNG", optimize=False, compress_level=9)
        stream.flush()
        os.fsync(stream.fileno())
    return _sha256_file(path)


def _ui_texture_meta(guid: str, filter_mode: str) -> bytes:
    filter_value = 0 if filter_mode == "Point" else 1
    texture_contract_id(filter_mode)
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
        f"  maxTextureSize: {MAX_DIMENSION}\n"
        "  textureSettings:\n"
        "    serializedVersion: 2\n"
        f"    filterMode: {filter_value}\n"
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
        f"    maxTextureSize: {MAX_DIMENSION}\n"
        "    resizeAlgorithm: 0\n"
        "    textureFormat: 25\n"
        "    textureCompression: 2\n"
        "    compressionQuality: 100\n"
        "    crunchedCompression: 0\n"
        "    allowsAlphaSplitting: 0\n"
        "    overridden: 1\n"
        "    androidETC2FallbackOverride: 0\n"
        "    forceMaximumCompressionQuality_BC6H_BC7: 1\n"
        "  - serializedVersion: 3\n"
        "    buildTarget: Standalone\n"
        f"    maxTextureSize: {MAX_DIMENSION}\n"
        "    resizeAlgorithm: 0\n"
        "    textureFormat: 25\n"
        "    textureCompression: 2\n"
        "    compressionQuality: 100\n"
        "    crunchedCompression: 0\n"
        "    allowsAlphaSplitting: 0\n"
        "    overridden: 1\n"
        "    androidETC2FallbackOverride: 0\n"
        "    forceMaximumCompressionQuality_BC6H_BC7: 1\n"
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


def _package_key(
    entry: UiTextureSourceEntry,
    *,
    editor_source_sha256: str,
    source_png_sha256: str,
) -> str:
    descriptor = {
        "alpha_mode": ALPHA_MODE,
        "asset_path": entry.asset_path,
        "bc_block_padding": BLOCK_PADDING_MODE,
        "bundle_name": entry.bundle_name,
        "editor_source_sha256": editor_source_sha256,
        "encoder_id": ENCODER_ID,
        "entry_id": entry.id,
        "filter_mode": entry.filter_mode,
        "height": entry.height,
        "noesis_path": entry.noesis_path,
        "numpy_version": np.__version__,
        "pillow_version": PILLOW_VERSION,
        "source_png_sha256": source_png_sha256,
        "storage_height": entry.storage_height,
        "storage_width": entry.storage_width,
        "texture_contract_id": entry.texture_contract_id,
        "unity_revision": UNITY_REVISION,
        "unity_version": UNITY_VERSION,
        "width": entry.width,
    }
    return sha256(_canonical_json_bytes(descriptor, final_lf=False)).hexdigest()


def plan_ui_texture_packages(
    *,
    workspace_root: Path,
    mod_root: Path,
    source_manifest: UiTextureSourceManifest,
    editor_source: Path | None = None,
) -> tuple[tuple[UiTexturePackagePlan, ...], str]:
    """Hash and header-check sources without decoding or premultiplying them."""

    workspace = Path(workspace_root).resolve(strict=True)
    mod = Path(mod_root).resolve(strict=True)
    editor = Path(
        editor_source
        if editor_source is not None
        else workspace / _EDITOR_SOURCE_RELATIVE
    ).resolve(strict=True)
    editor_payload = _read_exact_file(
        editor,
        4 * 1024 * 1024,
        "UI Unity editor builder",
    )
    editor_sha = sha256(editor_payload).hexdigest()
    result: list[UiTexturePackagePlan] = []
    for entry in source_manifest.entries:
        source = resolve_source_path(
            entry,
            workspace_root=workspace,
            mod_root=mod,
        )
        payload = _read_exact_file(
            source,
            MAX_SOURCE_BYTES,
            f"UI texture source {entry.id}",
        )
        source_sha = sha256(payload).hexdigest()
        if source_sha != entry.expected_source_sha256:
            raise UiAssetBundleError(f"UI texture source hash changed: {entry.id}")
        try:
            with Image.open(source) as image:
                if (
                    image.format != "PNG"
                    or image.mode != "RGBA"
                    or image.size != (entry.width, entry.height)
                    or getattr(image, "n_frames", 1) != 1
                ):
                    raise UiAssetBundleError(
                        f"UI texture header contract changed: {entry.id}"
                    )
        except UiAssetBundleError:
            raise
        except (OSError, UnidentifiedImageError) as exc:
            raise UiAssetBundleError(
                f"UI texture header cannot be decoded: {entry.id}"
            ) from exc
        result.append(
            UiTexturePackagePlan(
                entry=entry,
                source_path=source,
                source_png_sha256=source_sha,
                package_key=_package_key(
                    entry,
                    editor_source_sha256=editor_sha,
                    source_png_sha256=source_sha,
                ),
            )
        )
    return tuple(result), editor_sha


def _prepare_texture(
    plan: UiTexturePackagePlan,
    *,
    project_path: Path,
) -> PreparedUiTexture:
    entry = plan.entry
    source_path = plan.source_path
    payload = _read_exact_file(
        source_path,
        MAX_SOURCE_BYTES,
        f"UI texture source {entry.id}",
    )
    source_png_sha256 = sha256(payload).hexdigest()
    if (
        source_png_sha256 != entry.expected_source_sha256
        or source_png_sha256 != plan.source_png_sha256
    ):
        raise UiAssetBundleError(f"UI texture source hash changed: {entry.id}")
    try:
        with Image.open(source_path) as opened:
            opened.load()
            if opened.format != "PNG" or opened.mode != "RGBA":
                raise UiAssetBundleError(
                    f"UI texture must be an explicit RGBA PNG: {entry.id}"
                )
            if opened.size != (entry.width, entry.height):
                raise UiAssetBundleError(f"UI texture dimensions changed: {entry.id}")
            source = opened.copy()
    except UiAssetBundleError:
        raise
    except (OSError, UnidentifiedImageError) as exc:
        raise UiAssetBundleError(f"UI texture cannot be decoded: {entry.id}") from exc
    try:
        source_rgba_sha256 = _rgba_sha256_image(source)
        premultiplied = premultiply_rgba_exact(source)
    finally:
        source.close()
    try:
        padded = pad_rgba_to_bc_blocks(premultiplied)
    finally:
        premultiplied.close()
    try:
        premultiplied_rgba_sha256 = _rgba_sha256_image(padded)
        png_path = project_path.joinpath(*PurePosixPath(entry.asset_path).parts)
        premultiplied_png_sha256 = _write_png(png_path, padded)
    finally:
        padded.close()
    meta_path = png_path.with_name(png_path.name + ".meta")
    _write_bytes(
        meta_path,
        _ui_texture_meta(stable_unity_guid(entry.asset_path), entry.filter_mode),
    )
    return PreparedUiTexture(
        plan=plan,
        entry=entry,
        source_path=source_path,
        asset_path=entry.asset_path,
        premultiplied_png_path=png_path,
        source_png_sha256=source_png_sha256,
        source_rgba_sha256=source_rgba_sha256,
        premultiplied_png_sha256=premultiplied_png_sha256,
        premultiplied_rgba_sha256=premultiplied_rgba_sha256,
        package_key=plan.package_key,
    )


def prepare_ui_bundle_project(
    *,
    workspace_root: Path,
    mod_root: Path,
    source_manifest: UiTextureSourceManifest,
    build_container: Path,
    plans: Sequence[UiTexturePackagePlan] | None = None,
    editor_source: Path | None = None,
) -> PreparedUiBundleProject:
    workspace = Path(workspace_root).resolve(strict=True)
    mod = Path(mod_root).resolve(strict=True)
    container = Path(build_container).resolve(strict=True)
    if container != workspace / "work" / _PROJECT_CONTAINER_DIRECTORY:
        raise UiAssetBundleError("UI Unity build container is not the canonical work path")
    planned_all: tuple[UiTexturePackagePlan, ...]
    planned_editor_sha: str
    if plans is None:
        planned_all, planned_editor_sha = plan_ui_texture_packages(
            workspace_root=workspace,
            mod_root=mod,
            source_manifest=source_manifest,
            editor_source=editor_source,
        )
        selected = planned_all
    else:
        selected = tuple(plans)
        planned_editor_sha = ""
    if not selected or len(selected) > MAX_ENTRIES:
        raise UiAssetBundleError("UI Unity build selection is empty or too large")
    if selected != tuple(sorted(selected, key=lambda item: item.entry.id)):
        raise UiAssetBundleError("UI Unity build selection is not ordered")
    manifest_by_id = {entry.id: entry for entry in source_manifest.entries}
    if any(
        manifest_by_id.get(plan.entry.id) != plan.entry
        for plan in selected
    ):
        raise UiAssetBundleError("UI Unity build selection escaped the source manifest")
    editor = Path(
        editor_source
        if editor_source is not None
        else workspace / _EDITOR_SOURCE_RELATIVE
    ).resolve(strict=True)
    editor_payload = _read_exact_file(
        editor,
        4 * 1024 * 1024,
        "UI Unity editor builder",
    )
    editor_sha = sha256(editor_payload).hexdigest()
    if planned_editor_sha and planned_editor_sha != editor_sha:
        raise UiAssetBundleError("UI Unity editor changed after package planning")
    if any(
        plan.package_key
        != _package_key(
            plan.entry,
            editor_source_sha256=editor_sha,
            source_png_sha256=plan.source_png_sha256,
        )
        for plan in selected
    ):
        raise UiAssetBundleError("UI package plan key changed before preparation")

    seed = {
        "editor_source_sha256": editor_sha,
        "encoder_id": ENCODER_ID,
        "entry_ids": [plan.entry.id for plan in selected],
        "source_manifest_sha256": source_manifest.sha256,
        "unity_revision": UNITY_REVISION,
        "unity_version": UNITY_VERSION,
    }
    seed_id = sha256(_canonical_json_bytes(seed, final_lf=False)).hexdigest()
    staging = Path(tempfile.mkdtemp(prefix=f".prepare-ui-{seed_id[:12]}-", dir=container))
    try:
        project = staging / "project"
        output = staging / _OUTPUT_RELATIVE
        report = staging / _REPORT_RELATIVE
        build_input_path = staging / _BUILD_INPUT_RELATIVE
        log_path = staging / "unity-editor.log"
        for asset_folder in (
            "Assets",
            "Assets/Editor",
            "Assets/Generated",
            _PROJECT_TEXTURE_ROOT.as_posix(),
        ):
            folder = project.joinpath(*PurePosixPath(asset_folder).parts)
            folder.mkdir(parents=True, exist_ok=False)
            if asset_folder != "Assets":
                _write_bytes(
                    folder.with_name(folder.name + ".meta"),
                    _folder_meta(stable_unity_guid(asset_folder)),
                )
        (project / "ProjectSettings").mkdir(parents=True, exist_ok=False)
        _write_bytes(
            project / "ProjectSettings/ProjectVersion.txt",
            (
                f"m_EditorVersion: {UNITY_VERSION}\n"
                f"m_EditorVersionWithRevision: {UNITY_VERSION} ({UNITY_REVISION})\n"
            ).encode("utf-8"),
        )
        editor_asset = project.joinpath(*PurePosixPath(_EDITOR_ASSET_PATH).parts)
        _write_bytes(editor_asset, editor_payload)
        _write_bytes(
            editor_asset.with_name(editor_asset.name + ".meta"),
            _mono_meta(stable_unity_guid(_EDITOR_ASSET_PATH)),
        )
        prepared: list[PreparedUiTexture] = []
        for plan in selected:
            prepared.append(
                _prepare_texture(
                    plan,
                    project_path=project,
                )
            )
        build_id_descriptor = {
            "editor_source_sha256": editor_sha,
            "encoder_id": ENCODER_ID,
            "packages": [
                {"entry_id": item.entry.id, "package_key": item.package_key}
                for item in prepared
            ],
            "schema": BUILD_INPUT_SCHEMA,
            "unity_revision": UNITY_REVISION,
            "unity_version": UNITY_VERSION,
        }
        content_build_id = sha256(
            _canonical_json_bytes(build_id_descriptor, final_lf=False)
        ).hexdigest()
        build_id = ""
        final_root: Path | None = None
        for attempt in range(1024):
            candidate_id = sha256(
                _canonical_json_bytes(
                    {
                        "attempt": attempt,
                        "content_build_id": content_build_id,
                        "schema": BUILD_INPUT_SCHEMA,
                    },
                    final_lf=False,
                )
            ).hexdigest()
            candidate_root = container / candidate_id[:16]
            if os.path.lexists(candidate_root):
                if _is_reparse_or_link(candidate_root):
                    raise UiAssetBundleError(
                        "UI Unity build attempt path is linked"
                    )
                continue
            build_id = candidate_id
            final_root = candidate_root
            break
        if final_root is None:
            raise UiAssetBundleError("UI Unity build attempt namespace is exhausted")
        input_value = {
            "build_id": build_id,
            "build_options": list(BUILD_OPTIONS),
            "build_target": BUILD_TARGET,
            "editor_script_sha256": editor_sha,
            "entries": [
                {
                    "address": item.entry.address,
                    "alpha": True,
                    "asset_path": item.asset_path,
                    "bundle_name": item.entry.bundle_name,
                    "filter_mode": item.entry.filter_mode,
                    "gpu_bytes": item.entry.gpu_bytes,
                    "height": item.entry.storage_height,
                    "id": item.entry.id,
                    "noesis_path": item.entry.noesis_path,
                    "source_png_sha256": item.premultiplied_png_sha256,
                    "texture_name": item.entry.texture_name,
                    "width": item.entry.storage_width,
                }
                for item in prepared
            ],
            "output_relative_path": "../output/Runtime/UiAssetBundles/win64",
            "report_relative_path": "../output/ui-build-report.v1.json",
            "schema": BUILD_INPUT_SCHEMA,
            "unity": {"revision": UNITY_REVISION, "version": UNITY_VERSION},
        }
        _write_bytes(
            build_input_path,
            _canonical_json_bytes(input_value, final_lf=True),
        )
        staging.rename(final_root)
        return PreparedUiBundleProject(
            workspace_root=workspace,
            build_root=final_root,
            project_path=final_root / "project",
            build_input_path=final_root / _BUILD_INPUT_RELATIVE,
            output_path=final_root / _OUTPUT_RELATIVE,
            report_path=final_root / _REPORT_RELATIVE,
            log_path=final_root / "unity-editor.log",
            build_id=build_id,
            textures=tuple(
                PreparedUiTexture(
                    plan=item.plan,
                    entry=item.entry,
                    source_path=item.source_path,
                    asset_path=item.asset_path,
                    premultiplied_png_path=final_root
                    / item.premultiplied_png_path.relative_to(staging),
                    source_png_sha256=item.source_png_sha256,
                    source_rgba_sha256=item.source_rgba_sha256,
                    premultiplied_png_sha256=item.premultiplied_png_sha256,
                    premultiplied_rgba_sha256=item.premultiplied_rgba_sha256,
                    package_key=item.package_key,
                )
                for item in prepared
            ),
            editor_source_sha256=editor_sha,
        )
    except Exception:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise


def build_headless_command(
    unity_editor: Path,
    prepared: PreparedUiBundleProject,
) -> list[str]:
    editor = Path(unity_editor).resolve(strict=True)
    return [
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
        "-logFile",
        str(prepared.log_path),
    ]


def _expected_report_entry(texture: PreparedUiTexture) -> dict[str, object]:
    return {
        "address": texture.entry.address,
        "alpha": True,
        "asset_path": texture.asset_path,
        "bundle_name": texture.entry.bundle_name,
        "filter_mode": texture.entry.filter_mode,
        "gpu_bytes": texture.entry.gpu_bytes,
        "height": texture.entry.storage_height,
        "id": texture.entry.id,
        "noesis_path": texture.entry.noesis_path,
        "source_png_sha256": texture.premultiplied_png_sha256,
        "texture_name": texture.entry.texture_name,
        "width": texture.entry.storage_width,
    }


def validate_ui_build_report(
    prepared: PreparedUiBundleProject,
) -> UiUnityBuildResult:
    """Accept only the exact fresh Unity report and its exact output file set."""

    report, _payload = _read_canonical_json_object(
        prepared.report_path,
        MAX_REPORT_BYTES,
        "UI Unity build report",
    )
    if set(report) != {
        "build_id",
        "build_input_sha256",
        "build_options",
        "build_target",
        "entries",
        "error",
        "schema",
        "success",
        "unity",
    }:
        raise UiAssetBundleError("UI Unity build report root keys changed")
    build_input_sha = _sha256_file(prepared.build_input_path)
    if (
        report["schema"] != BUILD_REPORT_SCHEMA
        or report["build_id"] != prepared.build_id
        or report["build_input_sha256"] != build_input_sha
        or report["build_options"] != list(BUILD_OPTIONS)
        or report["build_target"] != BUILD_TARGET
        or report["unity"]
        != {"revision": UNITY_REVISION, "version": UNITY_VERSION}
        or report["success"] is not True
        or report["error"] != ""
    ):
        detail = str(report.get("error", "")).strip()
        raise UiAssetBundleError(
            "UI Unity build report rejected"
            + (f": {detail}" if detail else "")
        )
    rows = report["entries"]
    if not isinstance(rows, list) or len(rows) != len(prepared.textures):
        raise UiAssetBundleError("UI Unity build report entry set changed")
    exact_entry_keys = {
        "address",
        "alpha",
        "asset_path",
        "bundle_crc32",
        "bundle_name",
        "bundle_relative_path",
        "bundle_sha256",
        "bundle_size_bytes",
        "filter_mode",
        "gpu_bytes",
        "height",
        "id",
        "noesis_path",
        "source_png_sha256",
        "texture_name",
        "unity_hash128",
        "width",
    }
    artifacts: list[UiBundleArtifact] = []
    expected_output_names = {"win64", "win64.manifest"}
    for texture, row in zip(prepared.textures, rows, strict=True):
        if not isinstance(row, dict) or set(row) != exact_entry_keys:
            raise UiAssetBundleError("UI Unity build report entry keys changed")
        base = _expected_report_entry(texture)
        if any(row.get(key) != value for key, value in base.items()):
            raise UiAssetBundleError(
                f"UI Unity build report source binding changed: {texture.entry.id}"
            )
        expected_relative = (
            _MOD_BUNDLE_ROOT / texture.entry.bundle_name
        ).as_posix()
        size = row["bundle_size_bytes"]
        bundle_sha = row["bundle_sha256"]
        crc32 = row["bundle_crc32"]
        unity_hash128 = row["unity_hash128"]
        if (
            row["bundle_relative_path"] != expected_relative
            or isinstance(size, bool)
            or not isinstance(size, int)
            or size <= 0
            or _SHA256_RE.fullmatch(str(bundle_sha)) is None
            or _CRC32_RE.fullmatch(str(crc32)) is None
            or _HASH128_RE.fullmatch(str(unity_hash128)) is None
        ):
            raise UiAssetBundleError(
                f"UI Unity build report artifact metadata changed: {texture.entry.id}"
            )
        bundle_path = prepared.output_path / texture.entry.bundle_name
        try:
            resolved_bundle = bundle_path.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise UiAssetBundleError(
                f"Built UI bundle is missing: {texture.entry.bundle_name}"
            ) from exc
        if (
            resolved_bundle != bundle_path
            or resolved_bundle.parent != prepared.output_path
            or not resolved_bundle.is_file()
            or _is_reparse_or_link(resolved_bundle)
            or resolved_bundle.stat().st_size != size
            or _sha256_file(resolved_bundle) != bundle_sha
            or _crc32_file(resolved_bundle) != crc32
        ):
            raise UiAssetBundleError(
                f"Built UI bundle payload changed: {texture.entry.bundle_name}"
            )
        expected_output_names.add(texture.entry.bundle_name)
        expected_output_names.add(texture.entry.bundle_name + ".manifest")
        artifacts.append(
            UiBundleArtifact(
                entry_id=texture.entry.id,
                bundle_name=texture.entry.bundle_name,
                mod_relative_path=expected_relative,
                size_bytes=size,
                sha256=str(bundle_sha),
                crc32=str(crc32),
                unity_hash128=str(unity_hash128),
                package_key=texture.package_key,
            )
        )
    if not prepared.output_path.is_dir() or _is_reparse_or_link(prepared.output_path):
        raise UiAssetBundleError("UI Unity output directory is missing or linked")
    output_entries = tuple(prepared.output_path.iterdir())
    if (
        any(not path.is_file() or _is_reparse_or_link(path) for path in output_entries)
        or {path.name for path in output_entries} != expected_output_names
    ):
        raise UiAssetBundleError("UI Unity output file set changed")
    return UiUnityBuildResult(
        build_id=prepared.build_id,
        build_input_sha256=build_input_sha,
        artifacts=tuple(artifacts),
    )


def run_ui_headless_build(
    prepared: PreparedUiBundleProject,
    unity_editor: Path,
    *,
    timeout_seconds: int = 3 * 60 * 60,
    runner: Callable[..., Any] = subprocess.run,
) -> UiUnityBuildResult:
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, int)
        or not 1 <= timeout_seconds <= 24 * 60 * 60
    ):
        raise UiAssetBundleError("UI Unity timeout must be in 1..86400 seconds")
    if prepared.report_path.exists() or prepared.output_path.exists():
        raise UiAssetBundleError("Refusing to use stale UI Unity output")
    command = build_headless_command(unity_editor, prepared)
    try:
        completed = runner(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise UiAssetBundleError(
            f"UI Unity build timed out after {timeout_seconds} seconds"
        ) from exc
    except OSError as exc:
        raise UiAssetBundleError("Unity Editor could not be started") from exc
    if getattr(completed, "returncode", None) != 0:
        detail = str(getattr(completed, "stderr", "")).strip()
        if prepared.report_path.is_file():
            try:
                report, _ = _read_json_object(
                    prepared.report_path,
                    MAX_REPORT_BYTES,
                    "failed UI Unity build report",
                )
                detail = str(report.get("error", "")).strip() or detail
            except UiAssetBundleError:
                pass
        raise UiAssetBundleError(
            "UI Unity build failed with exit code "
            f"{getattr(completed, 'returncode', None)}"
            + (f": {detail}" if detail else "")
        )
    return validate_ui_build_report(prepared)


def _package_plan(
    value: UiTexturePackagePlan | PreparedUiTexture,
) -> UiTexturePackagePlan:
    return value.plan if isinstance(value, PreparedUiTexture) else value


def cache_directory(
    workspace_root: Path,
    texture: UiTexturePackagePlan | PreparedUiTexture,
) -> Path:
    workspace = Path(workspace_root).resolve(strict=True)
    plan = _package_plan(texture)
    return workspace / "cache" / _CACHE_DIRECTORY / "objects" / plan.package_key


def _cache_record(
    texture: PreparedUiTexture,
    artifact: UiBundleArtifact,
    *,
    quality_sha256: str,
    quality_size_bytes: int,
    policy: UiQualityPolicy,
) -> dict[str, object]:
    return {
        "bundle": {
            "crc32": artifact.crc32,
            "filename": artifact.bundle_name,
            "sha256": artifact.sha256,
            "size_bytes": artifact.size_bytes,
            "unity_hash128": artifact.unity_hash128,
        },
        "entry_id": texture.entry.id,
        "package_key": texture.package_key,
        "quality": {
            "accepted": True,
            "filename": "quality.v1.json",
            "policy_id": QUALITY_POLICY_ID,
            "policy_sha256": policy.sha256,
            "sha256": quality_sha256,
            "size_bytes": quality_size_bytes,
            "verifier_id": QUALITY_VERIFIER_ID,
        },
        "schema": CACHE_RECORD_SCHEMA,
        "source": {
            "premultiplied_png_sha256": texture.premultiplied_png_sha256,
            "premultiplied_rgba_sha256": texture.premultiplied_rgba_sha256,
            "source_png_sha256": texture.source_png_sha256,
            "source_rgba_sha256": texture.source_rgba_sha256,
        },
        "texture": {
            "address": texture.entry.address,
            "bc_block_padding": BLOCK_PADDING_MODE,
            "bundle_name": texture.entry.bundle_name,
            "filter_mode": texture.entry.filter_mode,
            "gpu_bytes": texture.entry.gpu_bytes,
            "logical_height": texture.entry.height,
            "logical_width": texture.entry.width,
            "name": texture.entry.texture_name,
            "noesis_path": texture.entry.noesis_path,
            "resident_charge_bytes": texture.entry.resident_charge_bytes,
            "storage_height": texture.entry.storage_height,
            "storage_width": texture.entry.storage_width,
            "texture_contract_id": texture.entry.texture_contract_id,
        },
        "toolchain": {
            "editor_source_sha256": None,
            "encoder_id": ENCODER_ID,
            "unity_revision": UNITY_REVISION,
            "unity_version": UNITY_VERSION,
        },
    }


def publish_cache_object(
    *,
    workspace_root: Path,
    texture: PreparedUiTexture,
    artifact: UiBundleArtifact,
    built_bundle_path: Path,
    quality_payload: bytes,
    quality_document: Mapping[str, object],
    policy: UiQualityPolicy,
    editor_source_sha256: str,
) -> CachedUiBundle:
    workspace = Path(workspace_root).resolve(strict=True)
    source_bundle = Path(built_bundle_path).resolve(strict=True)
    if (
        artifact.entry_id != texture.entry.id
        or artifact.bundle_name != texture.entry.bundle_name
        or artifact.package_key != texture.package_key
        or artifact.sha256 != _sha256_file(source_bundle)
        or artifact.crc32 != _crc32_file(source_bundle)
        or artifact.size_bytes != source_bundle.stat().st_size
    ):
        raise UiAssetBundleError("UI cache publication bundle binding changed")
    if (
        not quality_document.get("accepted")
        or quality_document.get("package_key") != texture.package_key
        or quality_document.get("bundle_sha256") != artifact.sha256
        or quality_payload
        != _canonical_json_bytes(dict(quality_document), final_lf=True)
    ):
        raise UiAssetBundleError("UI cache publication quality binding changed")
    quality_sha = sha256(quality_payload).hexdigest()
    final = cache_directory(workspace, texture)
    objects = final.parent
    staging_root = objects.parent / "staging"
    objects.mkdir(parents=True, exist_ok=True)
    staging_root.mkdir(parents=True, exist_ok=True)
    if final.exists():
        return validate_cache_object(
            workspace_root=workspace,
            texture=texture,
            policy=policy,
            expected_editor_source_sha256=editor_source_sha256,
        )
    staging = Path(tempfile.mkdtemp(prefix=f".{texture.package_key[:16]}-", dir=staging_root))
    try:
        bundle_destination = staging / artifact.bundle_name
        shutil.copyfile(source_bundle, bundle_destination)
        if (
            _sha256_file(bundle_destination) != artifact.sha256
            or bundle_destination.stat().st_size != artifact.size_bytes
        ):
            raise UiAssetBundleError("UI cache staging bundle copy changed")
        quality_path = staging / "quality.v1.json"
        _write_bytes(quality_path, quality_payload)
        record = _cache_record(
            texture,
            artifact,
            quality_sha256=quality_sha,
            quality_size_bytes=len(quality_payload),
            policy=policy,
        )
        record["toolchain"]["editor_source_sha256"] = editor_source_sha256
        _write_bytes(
            staging / "object.v1.json",
            _canonical_json_bytes(record, final_lf=True),
        )
        staging.rename(final)
    except FileExistsError:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise
    return validate_cache_object(
        workspace_root=workspace,
        texture=texture,
        policy=policy,
        expected_editor_source_sha256=editor_source_sha256,
    )


def validate_cache_object(
    *,
    workspace_root: Path,
    texture: UiTexturePackagePlan | PreparedUiTexture,
    policy: UiQualityPolicy,
    expected_editor_source_sha256: str,
) -> CachedUiBundle:
    plan = _package_plan(texture)
    entry = plan.entry
    directory = cache_directory(workspace_root, texture)
    try:
        resolved = directory.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise UiAssetBundleError(
            f"UI cache object is missing: {plan.package_key}"
        ) from exc
    if resolved != directory or not resolved.is_dir() or _is_reparse_or_link(resolved):
        raise UiAssetBundleError("UI cache object is linked or noncanonical")
    names = {path.name for path in resolved.iterdir()}
    expected_names = {entry.bundle_name, "object.v1.json", "quality.v1.json"}
    if names != expected_names:
        raise UiAssetBundleError("UI cache object file set changed")
    for path in resolved.iterdir():
        if not path.is_file() or _is_reparse_or_link(path):
            raise UiAssetBundleError("UI cache object contains a linked/non-file entry")
    record, _record_payload = _read_canonical_json_object(
        resolved / "object.v1.json",
        MAX_CACHE_RECORD_BYTES,
        "UI cache object record",
    )
    if set(record) != {
        "bundle",
        "entry_id",
        "package_key",
        "quality",
        "schema",
        "source",
        "texture",
        "toolchain",
    }:
        raise UiAssetBundleError("UI cache record root keys changed")
    if (
        record["schema"] != CACHE_RECORD_SCHEMA
        or record["entry_id"] != entry.id
        or record["package_key"] != plan.package_key
    ):
        raise UiAssetBundleError("UI cache record identity changed")
    source = record["source"]
    if not isinstance(source, dict) or set(source) != {
        "premultiplied_png_sha256",
        "premultiplied_rgba_sha256",
        "source_png_sha256",
        "source_rgba_sha256",
    }:
        raise UiAssetBundleError("UI cache source record changed")
    if (
        source["source_png_sha256"] != plan.source_png_sha256
        or any(
            _SHA256_RE.fullmatch(str(source[key])) is None
            for key in (
                "premultiplied_png_sha256",
                "premultiplied_rgba_sha256",
                "source_png_sha256",
                "source_rgba_sha256",
            )
        )
        or (
            isinstance(texture, PreparedUiTexture)
            and source
            != {
                "premultiplied_png_sha256": texture.premultiplied_png_sha256,
                "premultiplied_rgba_sha256": texture.premultiplied_rgba_sha256,
                "source_png_sha256": texture.source_png_sha256,
                "source_rgba_sha256": texture.source_rgba_sha256,
            }
        )
    ):
        raise UiAssetBundleError("UI cache source binding changed")
    expected_texture = {
        "address": entry.address,
        "bc_block_padding": BLOCK_PADDING_MODE,
        "bundle_name": entry.bundle_name,
        "filter_mode": entry.filter_mode,
        "gpu_bytes": entry.gpu_bytes,
        "logical_height": entry.height,
        "logical_width": entry.width,
        "name": entry.texture_name,
        "noesis_path": entry.noesis_path,
        "resident_charge_bytes": entry.resident_charge_bytes,
        "storage_height": entry.storage_height,
        "storage_width": entry.storage_width,
        "texture_contract_id": entry.texture_contract_id,
    }
    expected_toolchain = {
        "editor_source_sha256": expected_editor_source_sha256,
        "encoder_id": ENCODER_ID,
        "unity_revision": UNITY_REVISION,
        "unity_version": UNITY_VERSION,
    }
    if (
        record["texture"] != expected_texture
        or record["toolchain"] != expected_toolchain
    ):
        raise UiAssetBundleError("UI cache record source/texture/toolchain changed")
    bundle = record["bundle"]
    quality = record["quality"]
    if not isinstance(bundle, dict) or set(bundle) != {
        "crc32",
        "filename",
        "sha256",
        "size_bytes",
        "unity_hash128",
    }:
        raise UiAssetBundleError("UI cache bundle record changed")
    if not isinstance(quality, dict) or set(quality) != {
        "accepted",
        "filename",
        "policy_id",
        "policy_sha256",
        "sha256",
        "size_bytes",
        "verifier_id",
    }:
        raise UiAssetBundleError("UI cache quality record changed")
    if (
        bundle["filename"] != entry.bundle_name
        or _SHA256_RE.fullmatch(str(bundle["sha256"])) is None
        or _CRC32_RE.fullmatch(str(bundle["crc32"])) is None
        or _HASH128_RE.fullmatch(str(bundle["unity_hash128"])) is None
        or isinstance(bundle["size_bytes"], bool)
        or not isinstance(bundle["size_bytes"], int)
        or bundle["size_bytes"] <= 0
        or quality["accepted"] is not True
        or quality["filename"] != "quality.v1.json"
        or quality["policy_id"] != QUALITY_POLICY_ID
        or quality["policy_sha256"] != policy.sha256
        or quality["verifier_id"] != QUALITY_VERIFIER_ID
        or _SHA256_RE.fullmatch(str(quality["sha256"])) is None
        or isinstance(quality["size_bytes"], bool)
        or not isinstance(quality["size_bytes"], int)
        or quality["size_bytes"] <= 0
    ):
        raise UiAssetBundleError("UI cache bundle/quality values changed")
    bundle_path = resolved / entry.bundle_name
    quality_path = resolved / "quality.v1.json"
    if (
        bundle_path.stat().st_size != bundle["size_bytes"]
        or _sha256_file(bundle_path) != bundle["sha256"]
        or _crc32_file(bundle_path) != bundle["crc32"]
        or quality_path.stat().st_size != quality["size_bytes"]
        or _sha256_file(quality_path) != quality["sha256"]
    ):
        raise UiAssetBundleError("UI cache payload hash or size changed")
    quality_document, quality_payload = _read_canonical_json_object(
        quality_path,
        MAX_CACHE_RECORD_BYTES,
        "UI cache quality record",
    )
    if (
        quality_document.get("schema") != QUALITY_RECORD_SCHEMA
        or quality_document.get("accepted") is not True
        or quality_document.get("entry_id") != entry.id
        or quality_document.get("package_key") != plan.package_key
        or quality_document.get("bundle_sha256") != bundle["sha256"]
        or quality_document.get("quality_policy_sha256") != policy.sha256
        or sha256(quality_payload).hexdigest() != quality["sha256"]
    ):
        raise UiAssetBundleError("UI cache quality evidence binding changed")
    artifact = UiBundleArtifact(
        entry_id=entry.id,
        bundle_name=entry.bundle_name,
        mod_relative_path=(
            _MOD_BUNDLE_ROOT / entry.bundle_name
        ).as_posix(),
        size_bytes=int(bundle["size_bytes"]),
        sha256=str(bundle["sha256"]),
        crc32=str(bundle["crc32"]),
        unity_hash128=str(bundle["unity_hash128"]),
        package_key=plan.package_key,
    )
    return CachedUiBundle(
        artifact=artifact,
        bundle_path=bundle_path,
        quality_path=quality_path,
        quality_sha256=str(quality["sha256"]),
        source_rgba_sha256=str(source["source_rgba_sha256"]),
        premultiplied_rgba_sha256=str(source["premultiplied_rgba_sha256"]),
    )


def runtime_manifest_relative_path() -> str:
    return _MOD_RUNTIME_MANIFEST.as_posix()


def _virtual_relative_path(entry: UiTextureSourceEntry) -> str:
    return f"Runtime/UiTextures/virtual/{entry.path_hash16}.png"


def materialize_ui_runtime_payload(
    *,
    mod_root: Path,
    plans: Sequence[UiTexturePackagePlan],
    cached: Sequence[CachedUiBundle],
    source_manifest: UiTextureSourceManifest,
    quality_policy: UiQualityPolicy,
    editor_source_sha256: str,
) -> UiRuntimePayload:
    """Copy verified cache objects, write v2 TSV, then remove all GUI PNGs."""

    root = Path(mod_root).resolve(strict=True)
    ordered_plans = tuple(sorted(plans, key=lambda item: item.entry.id))
    if (
        not ordered_plans
        or len(ordered_plans) != len(cached)
        or len({plan.entry.id for plan in ordered_plans}) != len(ordered_plans)
    ):
        raise UiAssetBundleError("UI runtime materialization input set changed")
    if (
        tuple(plan.entry for plan in ordered_plans) != source_manifest.entries
        or _SHA256_RE.fullmatch(source_manifest.sha256) is None
        or _SHA256_RE.fullmatch(source_manifest.entry_set_sha256) is None
        or _SHA256_RE.fullmatch(quality_policy.sha256) is None
        or _SHA256_RE.fullmatch(editor_source_sha256) is None
    ):
        raise UiAssetBundleError("UI runtime manifest provenance changed")
    cached_by_id = {item.artifact.entry_id: item for item in cached}
    if set(cached_by_id) != {plan.entry.id for plan in ordered_plans}:
        raise UiAssetBundleError("UI runtime cache set differs from package plans")
    gui_root = root / "Override/Assets/GUI"
    actual_pngs = (
        {
            path.relative_to(root).as_posix(): path
            for path in gui_root.rglob("*")
            if path.is_file() and path.suffix.casefold() == ".png"
        }
        if gui_root.is_dir()
        else {}
    )
    expected_pngs = {
        plan.entry.source: plan
        for plan in ordered_plans
        if plan.entry.source_kind == "profile_output"
    }
    if set(actual_pngs) != set(expected_pngs):
        extra = sorted(set(actual_pngs) - set(expected_pngs))
        missing = sorted(set(expected_pngs) - set(actual_pngs))
        raise UiAssetBundleError(
            f"Undeclared or missing active GUI PNGs: extra={extra}, missing={missing}"
        )
    for relative, plan in expected_pngs.items():
        if _sha256_file(actual_pngs[relative]) != plan.source_png_sha256:
            raise UiAssetBundleError(f"Active GUI PNG changed before removal: {relative}")
    bundle_root = root.joinpath(*_MOD_BUNDLE_ROOT.parts)
    manifest_path = root.joinpath(*_MOD_RUNTIME_MANIFEST.parts)
    if bundle_root.exists() or manifest_path.exists():
        raise UiAssetBundleError("UI runtime payload output already exists")
    bundle_root.mkdir(parents=True, exist_ok=False)
    artifacts: list[UiBundleArtifact] = []
    for plan in ordered_plans:
        item = cached_by_id[plan.entry.id]
        artifact = item.artifact
        if (
            artifact.bundle_name != plan.entry.bundle_name
            or artifact.package_key != plan.package_key
            or artifact.mod_relative_path
            != (_MOD_BUNDLE_ROOT / plan.entry.bundle_name).as_posix()
        ):
            raise UiAssetBundleError("UI runtime cache artifact binding changed")
        destination = bundle_root / plan.entry.bundle_name
        shutil.copyfile(item.bundle_path, destination)
        if (
            destination.stat().st_size != artifact.size_bytes
            or _sha256_file(destination) != artifact.sha256
            or _crc32_file(destination) != artifact.crc32
        ):
            raise UiAssetBundleError("UI runtime bundle copy changed")
        artifacts.append(artifact)

    declared_gpu = sum(plan.entry.gpu_bytes for plan in ordered_plans)
    declared_resident = sum(
        plan.entry.resident_charge_bytes for plan in ordered_plans
    )
    lines = [
        RUNTIME_MANIFEST_SCHEMA,
        f"source_schema\t{SOURCE_SCHEMA}",
        f"source_manifest_sha256\t{source_manifest.sha256}",
        f"source_entry_set_sha256\t{source_manifest.entry_set_sha256}",
        f"quality_policy_schema\t{QUALITY_POLICY_SCHEMA}",
        f"quality_policy_id\t{QUALITY_POLICY_ID}",
        f"quality_policy_sha256\t{quality_policy.sha256}",
        f"quality_verifier_id\t{QUALITY_VERIFIER_ID}",
        f"encoder_id\t{ENCODER_ID}",
        f"editor_source_sha256\t{editor_source_sha256}",
        f"unity_version\t{UNITY_VERSION}",
        f"unity_revision\t{UNITY_REVISION}",
        f"alpha_mode\t{ALPHA_MODE}",
        f"bc_block_padding\t{BLOCK_PADDING_MODE}",
        f"entry_count\t{len(ordered_plans)}",
        f"bundle_count\t{len(artifacts)}",
        f"declared_gpu_bytes\t{declared_gpu}",
        f"declared_resident_charge_bytes\t{declared_resident}",
        "bundle\tid\tplugin_relative_path\tsha256\tsize_bytes\tcrc32"
        "\tunity_hash128",
    ]
    for plan in ordered_plans:
        artifact = cached_by_id[plan.entry.id].artifact
        lines.append(
            "\t".join(
                (
                    "bundle",
                    plan.entry.id,
                    artifact.mod_relative_path,
                    artifact.sha256,
                    str(artifact.size_bytes),
                    artifact.crc32,
                    artifact.unity_hash128,
                )
            )
        )
    lines.append(
        "texture\tnoesis_path\tvirtual_relative_path\tbundle_id\taddress"
        "\tsource_png_sha256\tpremultiplied_rgba_sha256"
        "\tlogical_width\tlogical_height\tstorage_width\tstorage_height"
        "\tgpu_bytes\tresident_charge_bytes\ttransient_peak_bytes"
        "\ttexture_contract_id\tbc_block_padding"
    )
    for plan in sorted(ordered_plans, key=lambda item: item.entry.noesis_path):
        item = cached_by_id[plan.entry.id]
        entry = plan.entry
        fields = (
            entry.noesis_path,
            _virtual_relative_path(entry),
            entry.id,
            entry.address,
            plan.source_png_sha256,
            item.premultiplied_rgba_sha256,
            entry.texture_contract_id,
        )
        if any("\t" in value or "\r" in value or "\n" in value for value in fields):
            raise UiAssetBundleError("UI runtime TSV field contains controls")
        lines.append(
            "\t".join(
                (
                    "texture",
                    entry.noesis_path,
                    _virtual_relative_path(entry),
                    entry.id,
                    entry.address,
                    plan.source_png_sha256,
                    item.premultiplied_rgba_sha256,
                    str(entry.width),
                    str(entry.height),
                    str(entry.storage_width),
                    str(entry.storage_height),
                    str(entry.gpu_bytes),
                    str(entry.resident_charge_bytes),
                    str(transient_peak_bytes(entry.gpu_bytes, item.artifact.size_bytes)),
                    entry.texture_contract_id,
                    BLOCK_PADDING_MODE,
                )
            )
        )
    manifest_payload = ("\n".join(lines) + "\n").encode("utf-8")
    if len(manifest_payload) > MAX_MANIFEST_BYTES:
        raise UiAssetBundleError("UI runtime manifest exceeds its exact bound")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    _write_bytes(manifest_path, manifest_payload)

    removed: list[str] = []
    for relative in sorted(expected_pngs):
        path = actual_pngs[relative]
        path.unlink()
        removed.append(relative)
    if gui_root.is_dir() and any(
        path.is_file() and path.suffix.casefold() == ".png"
        for path in gui_root.rglob("*")
    ):
        raise UiAssetBundleError("An active GUI PNG survived UI bundle materialization")
    return UiRuntimePayload(
        manifest_path=manifest_path,
        manifest_sha256=sha256(manifest_payload).hexdigest(),
        manifest_size_bytes=len(manifest_payload),
        bundles=tuple(artifacts),
        removed_png_paths=tuple(removed),
        declared_gpu_bytes=declared_gpu,
        declared_resident_charge_bytes=declared_resident,
    )


def build_ui_texture_backend(
    *,
    workspace_root: Path,
    mod_root: Path,
    source_manifest_path: Path,
    quality_policy_path: Path,
    unity_editor: Path | None,
    max_resident_bytes: int = 1024 * 1024 * 1024,
    timeout_seconds: int = 7200,
    runner: Callable[..., Any] = subprocess.run,
    headless_builder: Callable[..., UiUnityBuildResult] = run_ui_headless_build,
    bundle_validator: Callable[[Path, PreparedUiTexture], Image.Image]
    = validate_ui_bundle_payload,
) -> UiTextureBuildResult:
    """Build only cache misses, then compose the exact final BC7 UI payload."""

    workspace = Path(workspace_root).resolve(strict=True)
    mod = Path(mod_root).resolve(strict=True)
    if (
        isinstance(max_resident_bytes, bool)
        or not isinstance(max_resident_bytes, int)
        or not 1 <= max_resident_bytes <= 8 * 1024 * 1024 * 1024
    ):
        raise UiAssetBundleError("UI resident budget is outside 1 byte..8 GiB")
    manifest = load_ui_texture_source_manifest(
        Path(source_manifest_path).resolve(strict=True)
    )
    policy = load_ui_quality_policy(Path(quality_policy_path).resolve(strict=True))
    container = workspace / "work" / _PROJECT_CONTAINER_DIRECTORY
    container.mkdir(parents=True, exist_ok=True)
    prepared: PreparedUiBundleProject | None = None
    hit_count = 0
    miss_count = 0
    with exclusive_workspace_lock(
        workspace / "work",
        "ui-asset-bundles-v1",
        "UI-BC7-Paketcache",
    ):
        plans, editor_sha = plan_ui_texture_packages(
            workspace_root=workspace,
            mod_root=mod,
            source_manifest=manifest,
        )
        declared_resident = sum(
            plan.entry.resident_charge_bytes for plan in plans
        )
        if declared_resident > max_resident_bytes:
            raise UiAssetBundleError(
                "UI BC7 payload exceeds the profile resident budget: "
                f"{declared_resident} > {max_resident_bytes}"
            )
        cached_by_id: dict[str, CachedUiBundle] = {}
        misses: list[UiTexturePackagePlan] = []
        for plan in plans:
            candidate = cache_directory(workspace, plan)
            if os.path.lexists(candidate):
                cached_by_id[plan.entry.id] = validate_cache_object(
                    workspace_root=workspace,
                    texture=plan,
                    policy=policy,
                    expected_editor_source_sha256=editor_sha,
                )
                hit_count += 1
            else:
                misses.append(plan)
        miss_count = len(misses)
        if misses:
            if unity_editor is None:
                raise UiAssetBundleError(
                    "Pinned Unity Editor is required for UI BC7 cache misses"
                )
            prepared = prepare_ui_bundle_project(
                workspace_root=workspace,
                mod_root=mod,
                source_manifest=manifest,
                build_container=container,
                plans=tuple(misses),
            )
            built = headless_builder(
                prepared,
                Path(unity_editor),
                timeout_seconds=timeout_seconds,
                runner=runner,
            )
            if built.build_id != prepared.build_id:
                raise UiAssetBundleError("UI Unity build result identity changed")
            artifacts_by_id = {
                artifact.entry_id: artifact for artifact in built.artifacts
            }
            if set(artifacts_by_id) != {item.entry.id for item in prepared.textures}:
                raise UiAssetBundleError("UI Unity artifact set changed")
            for texture in prepared.textures:
                artifact = artifacts_by_id[texture.entry.id]
                built_bundle = prepared.output_path / artifact.bundle_name
                decoded = bundle_validator(built_bundle, texture)
                try:
                    evidence = measure_ui_texture_quality(texture, decoded)
                finally:
                    decoded.close()
                quality_payload, quality_document = build_ui_quality_record(
                    evidence,
                    texture=texture,
                    artifact=artifact,
                    policy=policy,
                )
                if quality_document["accepted"] is not True:
                    raise UiAssetBundleError(
                        f"UI BC7 quality gate rejected {texture.entry.id}"
                    )
                cached_by_id[texture.entry.id] = publish_cache_object(
                    workspace_root=workspace,
                    texture=texture,
                    artifact=artifact,
                    built_bundle_path=built_bundle,
                    quality_payload=quality_payload,
                    quality_document=quality_document,
                    policy=policy,
                    editor_source_sha256=prepared.editor_source_sha256,
                )
        ordered_cached = tuple(
            cached_by_id[plan.entry.id] for plan in plans
        )
        runtime = materialize_ui_runtime_payload(
            mod_root=mod,
            plans=plans,
            cached=ordered_cached,
            source_manifest=manifest,
            quality_policy=policy,
            editor_source_sha256=editor_sha,
        )
    return UiTextureBuildResult(
        runtime=runtime,
        cache_hit_count=hit_count,
        cache_miss_count=miss_count,
        unity_build_root=prepared.build_root if prepared is not None else None,
    )

"""Immutable, content-addressed cache objects for one GM AssetBundle group.

This module defines the durable object boundary used by the incremental V2
builder:

* the cache key contains only group-local, reproducible inputs;
* one immutable object owns the bundle, its final-index group record, the
  embedded ``atlas.v3`` contract, and complete per-frame quality evidence;
* an immutable ref makes a fully published object discoverable;
* absent objects are misses, while malformed or changed objects fail closed.

No game file, build output, runtime file, profile, or install slot is modified
by this module.  Publications are confined to ``cache/`` below the supplied
workspace root.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import ctypes
import errno
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import stat as stat_module
import tempfile
import unicodedata
import uuid
import zlib

from .asset_stream_contract import (
    BC7_ATLAS_SCHEMA,
    AssetStreamContractError,
    AtlasV3,
    calculate_bc7_group_resident_charge,
    calculate_bc7_peak_admission_bytes,
    canonical_bc7_bundle_name,
    canonical_group_slug,
    parse_atlas_v3,
)
from .asset_stream_quality import ErrorMetric, FrameQualityEvidence


INPUT_SCHEMA = "stronghold-europe-de.asset-stream-group-cache-input.v1"
OBJECT_SCHEMA = "stronghold-europe-de.asset-stream-group-cache-object.v1"
REF_SCHEMA = "stronghold-europe-de.asset-stream-group-cache-ref.v1"
INDEX_GROUP_SCHEMA = (
    "stronghold-europe-de.asset-stream-group-index-fragment.v1"
)
QUALITY_JSONL_SCHEMA = (
    "stronghold-europe-de.asset-stream-group-quality-frames-jsonl.v1"
)

CACHE_DIRECTORY = "asset-stream-group-cache-v1"
OBJECT_MANIFEST_FILENAME = "object.v1.json"
INDEX_GROUP_FILENAME = "index-group.v1.json"
ATLAS_FILENAME = "atlas.v3.json"
QUALITY_FRAMES_FILENAME = "quality-frames.v1.jsonl"

MAX_OBJECT_MANIFEST_BYTES = 512 * 1024
MAX_REF_BYTES = 64 * 1024
MAX_ATLAS_BYTES = 16 * 1024 * 1024
MAX_INDEX_GROUP_BYTES = 2 * 1024 * 1024
MAX_QUALITY_JSONL_BYTES = 512 * 1024 * 1024
MAX_QUALITY_LINE_BYTES = 1024 * 1024
MAX_BUNDLE_BYTES = 2 * 1024 * 1024 * 1024
MAX_FRAMES = 200_000
MAX_GM_ID = 255

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_HASH128_RE = re.compile(r"[0-9a-f]{32}\Z")
_CRC32_RE = re.compile(r"[0-9a-f]{8}\Z")
_ID_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}\Z")

_INPUT_ROOT_KEYS = frozenset(
    {
        "editor",
        "encoder",
        "frames",
        "group",
        "packer",
        "quality_policy",
        "runtime_capabilities",
        "schema",
        "texture_policy",
        "unity",
    }
)
_GROUP_KEYS = frozenset({"contract_sha256", "gm_id", "name", "slug"})
_FRAME_KEYS = frozenset(
    {
        "count",
        "main_rgba_sha256",
        "mask_rgba_sha256",
        "metadata_sha256",
        "names_sha256",
    }
)
_PACKER_KEYS = frozenset({"id", "settings_sha256", "source_sha256", "version"})
_UNITY_KEYS = frozenset(
    {"build_target", "executable_sha256", "revision", "version"}
)
_EDITOR_KEYS = frozenset({"id", "source_sha256"})
_ENCODER_KEYS = frozenset({"id", "settings_sha256", "version"})
_POLICY_KEYS = frozenset({"id", "sha256"})
_QUALITY_POLICY_KEYS = frozenset(
    {"id", "sha256", "verifier_id", "verifier_sha256"}
)
_RUNTIME_CAPABILITY_KEYS = frozenset({"id", "sha256"})

_INDEX_TEMPLATE_GROUP_KEYS = frozenset(
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
_INDEX_FINAL_KEYS = frozenset(
    {
        "bundle_crc32",
        "bundle_path",
        "bundle_sha256",
        "bundle_size_bytes",
        "predicted_load_peak_bytes",
        "unity_hash128",
    }
)
_INDEX_PAGE_KEYS = frozenset(
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

_QUALITY_FRAME_KEYS = frozenset(
    {
        "alt",
        "decoded_main_rgba_sha256",
        "decoded_mask_rgba_sha256",
        "group",
        "index",
        "metrics",
        "name",
        "page",
        "source_main_rgba_sha256",
        "source_mask_rgba_sha256",
    }
)
_QUALITY_METRIC_KEYS = frozenset(
    {
        "absolute_error_sum",
        "channels",
        "max_abs",
        "samples_per_channel",
        "squared_error_sum",
    }
)
_MAIN_METRICS = {
    "alpha": 1,
    "composite_black": 3,
    "composite_desert": 3,
    "composite_white": 3,
    "premultiplied_rgb": 3,
}
_MASK_METRICS = {"mask_g": 1, "mask_r": 1}

_OBJECT_ROOT_KEYS = frozenset(
    {
        "artifact_set_sha256",
        "artifacts",
        "cache_key",
        "group",
        "input",
        "schema",
    }
)
_ARTIFACT_KEYS = frozenset(
    {"atlas", "bundle", "index_group", "quality_frames"}
)
_COMMON_ARTIFACT_KEYS = frozenset(
    {"crc32", "filename", "sha256", "size_bytes"}
)
_REF_KEYS = frozenset(
    {
        "cache_key",
        "gm_id",
        "group",
        "manifest_sha256",
        "object_relative_path",
        "schema",
    }
)

_ALLOWED_SOURCE_TOP_LEVELS = frozenset({"cache", "dist", "work"})
_WINDOWS_REPARSE_ATTRIBUTE = 0x400


class GroupCacheError(RuntimeError):
    """Base class for isolated group-cache failures."""


class GroupCacheInputError(GroupCacheError):
    """Raised when a key descriptor is incomplete or ambiguous."""


class GroupCachePublicationError(GroupCacheError):
    """Raised before an invalid or conflicting publication can become visible."""


class GroupCacheCorruptionError(GroupCacheError):
    """Raised when a present/refenced cache object is not an exact hit."""


@dataclass(frozen=True, slots=True)
class GroupCacheInput:
    """Validated immutable key input.

    ``canonical_payload`` has no trailing LF because its SHA-256 is the object
    key.  Serialized cache files do have one trailing LF.
    """

    cache_key: str
    group: str
    slug: str
    gm_id: int
    frame_count: int
    canonical_payload: bytes

    def as_dict(self) -> dict[str, object]:
        value = _decode_json(self.canonical_payload, "group cache input")
        assert isinstance(value, dict)
        return value


@dataclass(frozen=True, slots=True)
class FileFingerprint:
    size_bytes: int
    sha256: str
    crc32: str


@dataclass(frozen=True, slots=True)
class CachedAssetStreamGroup:
    descriptor: GroupCacheInput
    object_directory: Path
    ref_path: Path
    manifest_path: Path
    manifest_sha256: str
    bundle_path: Path
    index_group_path: Path
    atlas_path: Path
    quality_frames_path: Path
    unity_hash128: str
    quality_evidence_sha256: str
    atlas: AtlasV3
    index_group_record: Mapping[str, object]
    quality_frames: tuple[FrameQualityEvidence, ...]


@dataclass(frozen=True, slots=True)
class _CacheLayout:
    workspace: Path
    root: Path
    objects: Path
    refs: Path
    staging: Path


def _canonical_json_bytes(value: object, *, final_lf: bool) -> bytes:
    try:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise GroupCacheInputError("Value is not canonical JSON") from exc
    return payload + (b"\n" if final_lf else b"")


def _reject_duplicate_pairs(
    pairs: Sequence[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise GroupCacheError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_nonfinite(token: str) -> object:
    raise GroupCacheError(f"Non-finite JSON value: {token}")


def _decode_json(payload: bytes, label: str) -> object:
    try:
        return json.loads(
            payload.decode("utf-8", errors="strict"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_nonfinite,
        )
    except GroupCacheError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GroupCacheError(f"{label} is not strict UTF-8 JSON") from exc


def _mapping(
    value: object,
    keys: frozenset[str] | set[str],
    label: str,
    error_type: type[GroupCacheError],
) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise error_type(f"{label} must be an object")
    if set(value) != set(keys):
        raise error_type(
            f"{label} keys changed: expected={sorted(keys)}, actual={sorted(value)}"
        )
    return value


def _text(
    value: object,
    label: str,
    error_type: type[GroupCacheError],
    *,
    maximum: int = 256,
) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > maximum
        or value != unicodedata.normalize("NFC", value)
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in value)
    ):
        raise error_type(f"{label} must be nonempty bounded NFC text")
    return value


def _identifier(
    value: object, label: str, error_type: type[GroupCacheError]
) -> str:
    text = _text(value, label, error_type, maximum=128)
    if _ID_RE.fullmatch(text) is None:
        raise error_type(f"{label} is not a canonical lowercase identifier")
    return text


def _sha256(
    value: object,
    label: str,
    error_type: type[GroupCacheError],
    *,
    nullable: bool = False,
) -> str | None:
    if nullable and value is None:
        return None
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise error_type(f"{label} must be a lowercase SHA-256")
    return value


def _crc32(
    value: object, label: str, error_type: type[GroupCacheError]
) -> str:
    if not isinstance(value, str) or _CRC32_RE.fullmatch(value) is None:
        raise error_type(f"{label} must be a lowercase CRC32")
    return value


def _hash128(
    value: object, label: str, error_type: type[GroupCacheError]
) -> str:
    if not isinstance(value, str) or _HASH128_RE.fullmatch(value) is None:
        raise error_type(f"{label} must be a lowercase Unity Hash128")
    return value


def _integer(
    value: object,
    label: str,
    error_type: type[GroupCacheError],
    *,
    minimum: int = 0,
    maximum: int | None = None,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise error_type(f"{label} must be an integer >= {minimum}")
    if maximum is not None and value > maximum:
        raise error_type(f"{label} exceeds {maximum}")
    return value


def _safe_relative_path(
    value: object, label: str, error_type: type[GroupCacheError]
) -> str:
    text = _text(value, label, error_type, maximum=512)
    if (
        "\\" in text
        or PurePosixPath(text).is_absolute()
        or PureWindowsPath(text).is_absolute()
        or text.startswith("/")
        or "//" in text
        or text.endswith("/")
    ):
        raise error_type(f"{label} is not a canonical relative path")
    parts = PurePosixPath(text).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise error_type(f"{label} contains an unsafe path component")
    if any(part.endswith((" ", ".")) for part in parts):
        raise error_type(f"{label} is unsafe on Windows")
    return text


def _validate_input_document(value: object) -> GroupCacheInput:
    root = _mapping(value, _INPUT_ROOT_KEYS, "group cache input", GroupCacheInputError)
    if root["schema"] != INPUT_SCHEMA:
        raise GroupCacheInputError(f"group cache input.schema must be {INPUT_SCHEMA!r}")

    group = _mapping(root["group"], _GROUP_KEYS, "group", GroupCacheInputError)
    name = _text(group["name"], "group.name", GroupCacheInputError, maximum=128)
    try:
        canonical_slug = canonical_group_slug(name, "group.name")
    except AssetStreamContractError as exc:
        raise GroupCacheInputError(str(exc)) from exc
    slug = _identifier(group["slug"], "group.slug", GroupCacheInputError)
    if slug != canonical_slug:
        raise GroupCacheInputError("group.slug does not match the canonical group name")
    gm_id = _integer(
        group["gm_id"], "group.gm_id", GroupCacheInputError, maximum=MAX_GM_ID
    )
    _sha256(group["contract_sha256"], "group.contract_sha256", GroupCacheInputError)

    frames = _mapping(root["frames"], _FRAME_KEYS, "frames", GroupCacheInputError)
    frame_count = _integer(
        frames["count"],
        "frames.count",
        GroupCacheInputError,
        minimum=1,
        maximum=MAX_FRAMES,
    )
    for key in ("main_rgba_sha256", "metadata_sha256", "names_sha256"):
        _sha256(frames[key], f"frames.{key}", GroupCacheInputError)
    _sha256(
        frames["mask_rgba_sha256"],
        "frames.mask_rgba_sha256",
        GroupCacheInputError,
        nullable=True,
    )

    packer = _mapping(root["packer"], _PACKER_KEYS, "packer", GroupCacheInputError)
    _identifier(packer["id"], "packer.id", GroupCacheInputError)
    _text(packer["version"], "packer.version", GroupCacheInputError, maximum=128)
    _sha256(packer["source_sha256"], "packer.source_sha256", GroupCacheInputError)
    _sha256(
        packer["settings_sha256"], "packer.settings_sha256", GroupCacheInputError
    )

    unity = _mapping(root["unity"], _UNITY_KEYS, "unity", GroupCacheInputError)
    _text(unity["version"], "unity.version", GroupCacheInputError, maximum=64)
    _text(unity["revision"], "unity.revision", GroupCacheInputError, maximum=128)
    _text(unity["build_target"], "unity.build_target", GroupCacheInputError, maximum=64)
    _sha256(
        unity["executable_sha256"], "unity.executable_sha256", GroupCacheInputError
    )

    editor = _mapping(root["editor"], _EDITOR_KEYS, "editor", GroupCacheInputError)
    _identifier(editor["id"], "editor.id", GroupCacheInputError)
    _sha256(editor["source_sha256"], "editor.source_sha256", GroupCacheInputError)

    encoder = _mapping(root["encoder"], _ENCODER_KEYS, "encoder", GroupCacheInputError)
    _identifier(encoder["id"], "encoder.id", GroupCacheInputError)
    _text(encoder["version"], "encoder.version", GroupCacheInputError, maximum=128)
    _sha256(
        encoder["settings_sha256"], "encoder.settings_sha256", GroupCacheInputError
    )

    texture_policy = _mapping(
        root["texture_policy"], _POLICY_KEYS, "texture_policy", GroupCacheInputError
    )
    _identifier(texture_policy["id"], "texture_policy.id", GroupCacheInputError)
    _sha256(
        texture_policy["sha256"], "texture_policy.sha256", GroupCacheInputError
    )

    quality_policy = _mapping(
        root["quality_policy"],
        _QUALITY_POLICY_KEYS,
        "quality_policy",
        GroupCacheInputError,
    )
    _identifier(quality_policy["id"], "quality_policy.id", GroupCacheInputError)
    _sha256(quality_policy["sha256"], "quality_policy.sha256", GroupCacheInputError)
    _identifier(
        quality_policy["verifier_id"], "quality_policy.verifier_id", GroupCacheInputError
    )
    _sha256(
        quality_policy["verifier_sha256"],
        "quality_policy.verifier_sha256",
        GroupCacheInputError,
    )

    capabilities = _mapping(
        root["runtime_capabilities"],
        _RUNTIME_CAPABILITY_KEYS,
        "runtime_capabilities",
        GroupCacheInputError,
    )
    _identifier(capabilities["id"], "runtime_capabilities.id", GroupCacheInputError)
    _sha256(
        capabilities["sha256"],
        "runtime_capabilities.sha256",
        GroupCacheInputError,
    )

    payload = _canonical_json_bytes(dict(root), final_lf=False)
    return GroupCacheInput(
        cache_key=sha256(payload).hexdigest(),
        group=name,
        slug=slug,
        gm_id=gm_id,
        frame_count=frame_count,
        canonical_payload=payload,
    )


def parse_group_cache_input(value: Mapping[str, object]) -> GroupCacheInput:
    """Validate and hash one exact group-local key descriptor.

    The exact schema has no ``build_id`` or profile-wide field.  Unknown keys
    are rejected, making accidental coupling to a full-build identity
    impossible rather than merely undocumented.
    """

    return _validate_input_document(value)


def _coerce_descriptor(
    value: GroupCacheInput | Mapping[str, object],
) -> GroupCacheInput:
    """Reparse even public dataclass instances; construction is not authority."""

    if not isinstance(value, GroupCacheInput):
        return parse_group_cache_input(value)
    try:
        raw = _decode_json(value.canonical_payload, "group cache input")
    except GroupCacheError as exc:
        raise GroupCacheInputError(str(exc)) from exc
    parsed = _validate_input_document(raw)
    if parsed != value:
        raise GroupCacheInputError(
            "Directly constructed GroupCacheInput differs from its canonical payload"
        )
    return parsed


def load_group_cache_input(path: Path) -> GroupCacheInput:
    """Load an exact canonical descriptor file (strict UTF-8, one final LF)."""

    candidate = Path(path)
    payload, _fingerprint = _read_direct_file(
        candidate,
        maximum_bytes=MAX_OBJECT_MANIFEST_BYTES,
        label="group cache input",
        error_type=GroupCacheInputError,
        require_single_link=False,
    )
    value = _decode_json(payload, "group cache input")
    if not isinstance(value, dict):
        raise GroupCacheInputError("group cache input root must be an object")
    descriptor = _validate_input_document(value)
    if payload != descriptor.canonical_payload + b"\n":
        raise GroupCacheInputError("group cache input file is not canonical JSON")
    return descriptor


def group_contract_sha256(
    *,
    array_size: int,
    dash_format: bool,
    lifetime: str,
    mask_policy: str,
    material_binding: str,
    filter_mode: str,
) -> str:
    """Digest the group-level fields which affect packing/runtime semantics."""

    if (
        isinstance(array_size, bool)
        or not isinstance(array_size, int)
        or array_size <= 0
        or not isinstance(dash_format, bool)
        or lifetime != "map"
        or mask_policy not in {"required", "forbidden"}
        or filter_mode not in {"Point", "Bilinear"}
    ):
        raise GroupCacheInputError("Group contract values are malformed")
    binding = _text(
        material_binding,
        "material_binding",
        GroupCacheInputError,
        maximum=128,
    )
    payload = _canonical_json_bytes(
        {
            "array_size": array_size,
            "dash_format": dash_format,
            "lifetime": lifetime,
            "mask_policy": mask_policy,
            "material_binding": binding,
            "filter_mode": filter_mode,
        },
        final_lf=False,
    )
    return sha256(payload).hexdigest()


def frame_bindings_from_atlas(atlas: AtlasV3) -> dict[str, object]:
    """Derive the pre-packable frame bindings represented by ``atlas.v3``."""

    names = [frame.name for frame in atlas.frames]
    metadata = [
        {
            "alt": frame.alt,
            "height": frame.rect.height,
            "index": frame.index,
            "name": frame.name,
            "pixels_per_unit": frame.pixels_per_unit,
            "pivot": {"x": frame.pivot.x, "y": frame.pivot.y},
            "width": frame.rect.width,
        }
        for frame in atlas.frames
    ]
    main = [
        {
            "alt": frame.alt,
            "index": frame.index,
            "name": frame.name,
            "sha256": frame.main_source_rgba_sha256,
        }
        for frame in atlas.frames
    ]
    masks = [
        {
            "alt": frame.alt,
            "index": frame.index,
            "name": frame.name,
            "sha256": frame.mask_source_rgba_sha256,
        }
        for frame in atlas.frames
    ]
    if all(row["sha256"] is None for row in masks):
        mask_digest: str | None = None
    elif any(row["sha256"] is None for row in masks):
        raise GroupCacheInputError("Atlas has a partially populated mask frame set")
    else:
        mask_digest = sha256(
            _canonical_json_bytes(masks, final_lf=False)
        ).hexdigest()
    return {
        "count": len(atlas.frames),
        "main_rgba_sha256": sha256(
            _canonical_json_bytes(main, final_lf=False)
        ).hexdigest(),
        "mask_rgba_sha256": mask_digest,
        "metadata_sha256": sha256(
            _canonical_json_bytes(metadata, final_lf=False)
        ).hexdigest(),
        "names_sha256": sha256(
            _canonical_json_bytes(names, final_lf=False)
        ).hexdigest(),
    }


def _is_reparse_or_link(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        attributes = int(getattr(path.lstat(), "st_file_attributes", 0))
    except OSError:
        return True
    return bool(attributes & _WINDOWS_REPARSE_ATTRIBUTE)


def _workspace_root(path: Path) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        raise GroupCachePublicationError("Workspace root must be absolute")
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise GroupCachePublicationError("Workspace root does not exist") from exc
    if resolved != candidate or not resolved.is_dir():
        raise GroupCachePublicationError(
            "Workspace root must be a canonical direct directory"
        )
    current = resolved
    while True:
        if _is_reparse_or_link(current):
            raise GroupCachePublicationError(
                f"Workspace root has a link, junction, or reparse ancestor: {current}"
            )
        if current.parent == current:
            break
        current = current.parent
    return resolved


def _assert_direct_directory(
    path: Path, label: str, error_type: type[GroupCacheError]
) -> None:
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise error_type(f"{label} does not exist: {path}") from exc
    if resolved != path or not path.is_dir() or _is_reparse_or_link(path):
        raise error_type(f"{label} is linked, reparsed, or noncanonical: {path}")


def _existing_child(
    parent: Path,
    name: str,
    *,
    directory: bool,
    label: str,
    error_type: type[GroupCacheError],
) -> Path | None:
    _assert_direct_directory(parent, f"{label} parent", error_type)
    try:
        matches = [
            entry for entry in parent.iterdir() if entry.name.casefold() == name.casefold()
        ]
    except OSError as exc:
        raise error_type(f"Could not enumerate {label} parent: {parent}") from exc
    if not matches:
        return None
    if len(matches) != 1 or matches[0].name != name:
        raise error_type(f"{label} has a Windows case-colliding path")
    child = matches[0]
    try:
        resolved = child.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise error_type(f"{label} cannot be resolved directly") from exc
    if resolved != child or _is_reparse_or_link(child):
        raise error_type(f"{label} is linked, junctioned, or reparsed")
    if directory != child.is_dir() or (not directory and not child.is_file()):
        raise error_type(f"{label} has the wrong file type")
    return child


def _ensure_child_directory(parent: Path, name: str, label: str) -> Path:
    existing = _existing_child(
        parent,
        name,
        directory=True,
        label=label,
        error_type=GroupCachePublicationError,
    )
    if existing is not None:
        return existing
    candidate = parent / name
    try:
        candidate.mkdir(exist_ok=False)
    except FileExistsError:
        existing = _existing_child(
            parent,
            name,
            directory=True,
            label=label,
            error_type=GroupCachePublicationError,
        )
        if existing is None:
            raise GroupCachePublicationError(f"{label} raced with an unsafe path")
        return existing
    except OSError as exc:
        raise GroupCachePublicationError(f"Could not create {label}: {candidate}") from exc
    _assert_direct_directory(candidate, label, GroupCachePublicationError)
    return candidate


def _prepare_layout(workspace_root: Path) -> _CacheLayout:
    workspace = _workspace_root(workspace_root)
    cache = _ensure_child_directory(workspace, "cache", "workspace cache")
    root = _ensure_child_directory(cache, CACHE_DIRECTORY, "group cache root")
    objects = _ensure_child_directory(root, "objects", "group cache objects")
    refs = _ensure_child_directory(root, "refs", "group cache refs")
    staging = _ensure_child_directory(root, "staging", "group cache staging")
    return _CacheLayout(workspace, root, objects, refs, staging)


def _existing_layout(workspace_root: Path) -> _CacheLayout | None:
    workspace = _workspace_root(workspace_root)
    cache = _existing_child(
        workspace,
        "cache",
        directory=True,
        label="workspace cache",
        error_type=GroupCacheCorruptionError,
    )
    if cache is None:
        return None
    root = _existing_child(
        cache,
        CACHE_DIRECTORY,
        directory=True,
        label="group cache root",
        error_type=GroupCacheCorruptionError,
    )
    if root is None:
        return None
    objects = _existing_child(
        root,
        "objects",
        directory=True,
        label="group cache objects",
        error_type=GroupCacheCorruptionError,
    )
    refs = _existing_child(
        root,
        "refs",
        directory=True,
        label="group cache refs",
        error_type=GroupCacheCorruptionError,
    )
    staging = _existing_child(
        root,
        "staging",
        directory=True,
        label="group cache staging",
        error_type=GroupCacheCorruptionError,
    )
    if objects is None or refs is None or staging is None:
        raise GroupCacheCorruptionError("Group cache layout is only partially present")
    return _CacheLayout(workspace, root, objects, refs, staging)


def _assert_exact_case_below(
    base: Path, target: Path, label: str, error_type: type[GroupCacheError]
) -> None:
    try:
        relative = target.relative_to(base)
    except ValueError as exc:
        raise error_type(f"{label} escapes the workspace") from exc
    current = base
    for component in relative.parts:
        child = _existing_child(
            current,
            component,
            directory=(current / component) != target,
            label=label,
            error_type=error_type,
        )
        if child is None:
            raise error_type(f"{label} does not exist")
        current = child


def _generated_source(
    workspace: Path,
    path: Path,
    label: str,
) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        raise GroupCachePublicationError(f"{label} must be absolute")
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise GroupCachePublicationError(f"{label} does not exist: {candidate}") from exc
    if resolved != candidate:
        raise GroupCachePublicationError(f"{label} is linked or noncanonical")
    try:
        relative = resolved.relative_to(workspace)
    except ValueError as exc:
        raise GroupCachePublicationError(f"{label} is outside the workspace") from exc
    if not relative.parts or relative.parts[0] not in _ALLOWED_SOURCE_TOP_LEVELS:
        raise GroupCachePublicationError(
            f"{label} must come from workspace work/, cache/, or dist/"
        )
    _assert_exact_case_below(
        workspace, resolved, label, GroupCachePublicationError
    )
    if not resolved.is_file() or _is_reparse_or_link(resolved):
        raise GroupCachePublicationError(f"{label} is not a direct regular file")
    return resolved


def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        int(value.st_dev),
        int(value.st_ino),
        int(value.st_size),
        int(value.st_mtime_ns),
        int(getattr(value, "st_file_attributes", 0)),
    )


def _fingerprint_stream(
    stream: object, *, maximum_bytes: int, capture: bool
) -> tuple[FileFingerprint, bytes]:
    digest = sha256()
    crc = 0
    chunks: list[bytes] = []
    size = 0
    while True:
        chunk = stream.read(8 * 1024 * 1024)  # type: ignore[attr-defined]
        if not chunk:
            break
        size += len(chunk)
        if size > maximum_bytes:
            raise GroupCacheError(f"File exceeds its {maximum_bytes}-byte bound")
        digest.update(chunk)
        crc = zlib.crc32(chunk, crc)
        if capture:
            chunks.append(chunk)
    return FileFingerprint(size, digest.hexdigest(), f"{crc & 0xffffffff:08x}"), b"".join(chunks)


def _read_direct_file(
    path: Path,
    *,
    maximum_bytes: int,
    label: str,
    error_type: type[GroupCacheError],
    require_single_link: bool,
) -> tuple[bytes, FileFingerprint]:
    try:
        before = path.lstat()
    except OSError as exc:
        raise error_type(f"{label} cannot be inspected: {path}") from exc
    if (
        _is_reparse_or_link(path)
        or not stat_module.S_ISREG(before.st_mode)
        or (require_single_link and int(before.st_nlink) != 1)
    ):
        raise error_type(f"{label} is linked, reparsed, hardlinked, or non-regular")
    if not 0 < before.st_size <= maximum_bytes:
        raise error_type(f"{label} has an unsupported byte size: {before.st_size}")
    try:
        with path.open("rb") as stream:
            opened_before = os.fstat(stream.fileno())
            fingerprint, payload = _fingerprint_stream(
                stream, maximum_bytes=maximum_bytes, capture=True
            )
            opened_after = os.fstat(stream.fileno())
    except GroupCacheError as exc:
        raise error_type(f"{label}: {exc}") from exc
    except OSError as exc:
        raise error_type(f"{label} could not be read") from exc
    try:
        after = path.lstat()
    except OSError as exc:
        raise error_type(f"{label} disappeared while being read") from exc
    identities = {
        _stat_identity(before),
        _stat_identity(opened_before),
        _stat_identity(opened_after),
        _stat_identity(after),
    }
    if len(identities) != 1 or fingerprint.size_bytes != before.st_size:
        raise error_type(f"{label} changed while being read")
    return payload, fingerprint


def _fingerprint_direct_file(
    path: Path,
    *,
    maximum_bytes: int,
    label: str,
    error_type: type[GroupCacheError],
    require_single_link: bool,
) -> FileFingerprint:
    try:
        before = path.lstat()
    except OSError as exc:
        raise error_type(f"{label} cannot be inspected: {path}") from exc
    if (
        _is_reparse_or_link(path)
        or not stat_module.S_ISREG(before.st_mode)
        or (require_single_link and int(before.st_nlink) != 1)
        or not 0 < before.st_size <= maximum_bytes
    ):
        raise error_type(
            f"{label} is linked, reparsed, hardlinked, non-regular, or oversized"
        )
    try:
        with path.open("rb") as stream:
            opened_before = os.fstat(stream.fileno())
            fingerprint, _unused = _fingerprint_stream(
                stream, maximum_bytes=maximum_bytes, capture=False
            )
            opened_after = os.fstat(stream.fileno())
        after = path.lstat()
    except GroupCacheError as exc:
        raise error_type(f"{label}: {exc}") from exc
    except OSError as exc:
        raise error_type(f"{label} could not be read") from exc
    if (
        len(
            {
                _stat_identity(before),
                _stat_identity(opened_before),
                _stat_identity(opened_after),
                _stat_identity(after),
            }
        )
        != 1
        or fingerprint.size_bytes != before.st_size
    ):
        raise error_type(f"{label} changed while being read")
    return fingerprint


def _write_exclusive(path: Path, payload: bytes, label: str) -> FileFingerprint:
    digest = sha256(payload).hexdigest()
    crc = f"{zlib.crc32(payload) & 0xffffffff:08x}"
    try:
        with path.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise GroupCachePublicationError(f"Refusing to overwrite {label}: {path}") from exc
    except OSError as exc:
        raise GroupCachePublicationError(f"Could not write {label}: {path}") from exc
    return FileFingerprint(len(payload), digest, crc)


def _copy_exclusive(
    source: Path,
    destination: Path,
    *,
    maximum_bytes: int,
    label: str,
) -> FileFingerprint:
    try:
        before = source.lstat()
        if _is_reparse_or_link(source) or not stat_module.S_ISREG(before.st_mode):
            raise GroupCachePublicationError(f"{label} source is not direct")
        digest = sha256()
        crc = 0
        size = 0
        with source.open("rb") as reader, destination.open("xb") as writer:
            opened_before = os.fstat(reader.fileno())
            while chunk := reader.read(8 * 1024 * 1024):
                size += len(chunk)
                if size > maximum_bytes:
                    raise GroupCachePublicationError(
                        f"{label} exceeds its {maximum_bytes}-byte bound"
                    )
                digest.update(chunk)
                crc = zlib.crc32(chunk, crc)
                writer.write(chunk)
            writer.flush()
            os.fsync(writer.fileno())
            opened_after = os.fstat(reader.fileno())
        after = source.lstat()
    except FileExistsError as exc:
        raise GroupCachePublicationError(f"Refusing to overwrite {label}") from exc
    except GroupCachePublicationError:
        raise
    except OSError as exc:
        raise GroupCachePublicationError(f"Could not copy {label}") from exc
    if (
        len(
            {
                _stat_identity(before),
                _stat_identity(opened_before),
                _stat_identity(opened_after),
                _stat_identity(after),
            }
        )
        != 1
        or size != before.st_size
        or size <= 0
    ):
        raise GroupCachePublicationError(f"{label} source changed while copied")
    return FileFingerprint(size, digest.hexdigest(), f"{crc & 0xffffffff:08x}")


def _parse_atlas(
    payload: bytes,
    *,
    label: str,
    error_type: type[GroupCacheError],
) -> AtlasV3:
    try:
        return parse_atlas_v3(payload, label=label)
    except AssetStreamContractError as exc:
        raise error_type(f"{label} is not an exact atlas.v3 contract: {exc}") from exc


def _expected_index_pages(atlas: AtlasV3) -> list[dict[str, object]]:
    return [
        {
            "height": page.height,
            "id": page.id,
            "main_address": page.main.address,
            "main_format": page.main.format,
            "main_gpu_bytes": page.main.gpu_bytes,
            "main_source_rgba_sha256": page.main.source_rgba_sha256,
            "mask_address": None if page.mask is None else page.mask.address,
            "mask_format": None if page.mask is None else page.mask.format,
            "mask_gpu_bytes": None if page.mask is None else page.mask.gpu_bytes,
            "mask_source_rgba_sha256": (
                None if page.mask is None else page.mask.source_rgba_sha256
            ),
            "width": page.width,
        }
        for page in atlas.pages
    ]


def _validate_group_record(
    raw: object,
    *,
    descriptor: GroupCacheInput,
    atlas: AtlasV3,
    atlas_fingerprint: FileFingerprint,
    bundle_fingerprint: FileFingerprint,
    error_type: type[GroupCacheError],
) -> dict[str, object]:
    label = "index group record"
    record = _mapping(
        raw,
        _INDEX_TEMPLATE_GROUP_KEYS | _INDEX_FINAL_KEYS,
        label,
        error_type,
    )
    record_gm_id = _integer(
        record["gm_id"], f"{label}.gm_id", error_type, maximum=MAX_GM_ID
    )
    if (
        record["group"] != descriptor.group
        or record["slug"] != descriptor.slug
        or record_gm_id != descriptor.gm_id
    ):
        raise error_type(f"{label} identity does not match the cache input")
    try:
        expected_bundle = canonical_bc7_bundle_name(
            descriptor.group, "group cache descriptor.group"
        )
    except AssetStreamContractError as exc:
        raise error_type("Index group bundle identity is invalid") from exc
    if record["bundle"] != expected_bundle:
        raise error_type(f"{label}.bundle changed")
    if (
        atlas.group != descriptor.group
        or atlas.slug != descriptor.slug
        or atlas.bundle != expected_bundle
    ):
        raise error_type("atlas identity does not match the cache input")

    array_size = _integer(
        record["array_size"],
        f"{label}.array_size",
        error_type,
        minimum=1,
        maximum=MAX_FRAMES,
    )
    if any(frame.index >= array_size for frame in atlas.frames):
        raise error_type(f"{label}.array_size excludes an atlas frame")
    if not isinstance(record["dash_format"], bool) or record["lifetime"] != "map":
        raise error_type(f"{label} dash/lifetime contract changed")
    if (
        record["mask_policy"] != atlas.mask_policy
        or record["material_binding"] != atlas.material_binding
    ):
        raise error_type(f"{label} material contract differs from atlas.v3")
    try:
        contract_digest = group_contract_sha256(
            array_size=array_size,
            dash_format=bool(record["dash_format"]),
            lifetime=str(record["lifetime"]),
            mask_policy=str(record["mask_policy"]),
            material_binding=str(record["material_binding"]),
            filter_mode=atlas.main_texture_contract.filter_mode,
        )
    except GroupCacheInputError as exc:
        raise error_type(f"{label} group contract is malformed: {exc}") from exc
    input_document = descriptor.as_dict()
    input_group = input_document["group"]
    assert isinstance(input_group, dict)
    if contract_digest != input_group["contract_sha256"]:
        raise error_type(f"{label} differs from group.contract_sha256")

    expected_atlas_path = f"Assets/Generated/Groups/{descriptor.slug}/{ATLAS_FILENAME}"
    expected_atlas_address = f"sede/gm/{descriptor.slug}/{ATLAS_FILENAME}"
    if (
        record["atlas_asset_path"] != expected_atlas_path
        or record["atlas_address"] != expected_atlas_address
        or record["atlas_sha256"] != atlas_fingerprint.sha256
    ):
        raise error_type(f"{label} atlas binding changed")
    for key in ("atlas_asset_path", "atlas_address"):
        _safe_relative_path(record[key], f"{label}.{key}", error_type)

    try:
        actual_bindings = frame_bindings_from_atlas(atlas)
    except GroupCacheInputError as exc:
        raise error_type(f"atlas frame bindings are malformed: {exc}") from exc
    input_frames = input_document["frames"]
    assert isinstance(input_frames, dict)
    if actual_bindings != input_frames:
        raise error_type("atlas frames do not match the cache input frame digests")
    expected_names = actual_bindings["names_sha256"]
    frame_count = _integer(
        record["frame_count"],
        f"{label}.frame_count",
        error_type,
        minimum=1,
        maximum=MAX_FRAMES,
    )
    page_count = _integer(
        record["page_count"],
        f"{label}.page_count",
        error_type,
        minimum=1,
        maximum=64,
    )
    if (
        frame_count != len(atlas.frames)
        or frame_count != descriptor.frame_count
        or record["frames_sha256"] != atlas.frames_sha256
        or record["names_sha256"] != expected_names
        or page_count != len(atlas.pages)
    ):
        raise error_type(f"{label} frame/page summary changed")
    for key in ("frames_sha256", "names_sha256"):
        _sha256(record[key], f"{label}.{key}", error_type)

    expected_resource_values = {
        "gpu_bytes": atlas.gpu_bytes,
        "resident_charge_bytes": calculate_bc7_group_resident_charge(atlas.gpu_bytes),
        "source_rgba_bytes": atlas.source_rgba_bytes,
    }
    for key in expected_resource_values:
        _integer(record[key], f"{label}.{key}", error_type, minimum=1)
    if any(record[key] != value for key, value in expected_resource_values.items()):
        raise error_type(f"{label} resource summary changed")

    raw_pages = record["pages"]
    if not isinstance(raw_pages, list) or len(raw_pages) != len(atlas.pages):
        raise error_type(f"{label}.pages changed")
    for ordinal, raw_page in enumerate(raw_pages):
        page_label = f"{label}.pages[{ordinal}]"
        page = _mapping(raw_page, _INDEX_PAGE_KEYS, page_label, error_type)
        for key in ("height", "id", "main_gpu_bytes", "width"):
            _integer(page[key], f"{page_label}.{key}", error_type)
        for key in ("main_address",):
            _safe_relative_path(page[key], f"{page_label}.{key}", error_type)
        _text(page["main_format"], f"{page_label}.main_format", error_type)
        _sha256(
            page["main_source_rgba_sha256"],
            f"{page_label}.main_source_rgba_sha256",
            error_type,
        )
        mask_values = (
            page["mask_address"],
            page["mask_format"],
            page["mask_gpu_bytes"],
            page["mask_source_rgba_sha256"],
        )
        if all(value is None for value in mask_values):
            pass
        elif any(value is None for value in mask_values):
            raise error_type(f"{page_label} has a partial mask summary")
        else:
            _safe_relative_path(
                page["mask_address"], f"{page_label}.mask_address", error_type
            )
            _text(page["mask_format"], f"{page_label}.mask_format", error_type)
            _integer(
                page["mask_gpu_bytes"],
                f"{page_label}.mask_gpu_bytes",
                error_type,
                minimum=1,
            )
            _sha256(
                page["mask_source_rgba_sha256"],
                f"{page_label}.mask_source_rgba_sha256",
                error_type,
            )
    if raw_pages != _expected_index_pages(atlas):
        raise error_type(f"{label}.pages does not exactly summarize atlas.v3")

    expected_bundle_path = f"Runtime/AssetBundles/win64/{expected_bundle}"
    bundle_size = _integer(
        record["bundle_size_bytes"],
        f"{label}.bundle_size_bytes",
        error_type,
        minimum=1,
        maximum=MAX_BUNDLE_BYTES,
    )
    if (
        record["bundle_path"] != expected_bundle_path
        or bundle_size != bundle_fingerprint.size_bytes
        or record["bundle_sha256"] != bundle_fingerprint.sha256
        or record["bundle_crc32"] != bundle_fingerprint.crc32
    ):
        raise error_type(f"{label} bundle anchors changed")
    _safe_relative_path(record["bundle_path"], f"{label}.bundle_path", error_type)
    _sha256(record["bundle_sha256"], f"{label}.bundle_sha256", error_type)
    _crc32(record["bundle_crc32"], f"{label}.bundle_crc32", error_type)
    _hash128(record["unity_hash128"], f"{label}.unity_hash128", error_type)
    expected_peak = calculate_bc7_peak_admission_bytes(
        atlas.resident_charge_bytes, bundle_fingerprint.size_bytes
    )
    predicted_peak = _integer(
        record["predicted_load_peak_bytes"],
        f"{label}.predicted_load_peak_bytes",
        error_type,
        minimum=1,
    )
    if predicted_peak != expected_peak:
        raise error_type(f"{label}.predicted_load_peak_bytes changed")

    # Canonicalize to a detached JSON-only value before it reaches a manifest.
    payload = _canonical_json_bytes(dict(record), final_lf=False)
    detached = _decode_json(payload, label)
    assert isinstance(detached, dict)
    return detached


def _validate_metric(
    raw: object,
    *,
    label: str,
    expected_channels: int,
    expected_samples: int,
    error_type: type[GroupCacheError],
) -> ErrorMetric:
    metric = _mapping(raw, _QUALITY_METRIC_KEYS, label, error_type)
    channels = _integer(metric["channels"], f"{label}.channels", error_type, minimum=1, maximum=4)
    samples = _integer(
        metric["samples_per_channel"],
        f"{label}.samples_per_channel",
        error_type,
        minimum=1,
    )
    if channels != expected_channels or samples != expected_samples:
        raise error_type(f"{label} channel/sample geometry changed")
    limits = {
        "max_abs": 255,
        "absolute_error_sum": samples * 255,
        "squared_error_sum": samples * 255 * 255,
    }
    for key, maximum in limits.items():
        values = metric[key]
        if not isinstance(values, list) or len(values) != channels:
            raise error_type(f"{label}.{key} has the wrong channel count")
        for ordinal, value in enumerate(values):
            _integer(
                value,
                f"{label}.{key}[{ordinal}]",
                error_type,
                maximum=maximum,
            )
    return ErrorMetric(
        channels=channels,
        samples_per_channel=samples,
        max_abs=tuple(int(item) for item in metric["max_abs"]),
        absolute_error_sum=tuple(
            int(item) for item in metric["absolute_error_sum"]
        ),
        squared_error_sum=tuple(
            int(item) for item in metric["squared_error_sum"]
        ),
    )


def _validate_quality_record(
    raw: object,
    *,
    atlas: AtlasV3,
    ordinal: int,
    error_type: type[GroupCacheError],
) -> FrameQualityEvidence:
    label = f"quality frame[{ordinal}]"
    value = _mapping(raw, _QUALITY_FRAME_KEYS, label, error_type)
    frame = atlas.frames[ordinal]
    if not isinstance(value["alt"], bool):
        raise error_type(f"{label}.alt must be a boolean")
    _integer(value["index"], f"{label}.index", error_type)
    _integer(value["page"], f"{label}.page", error_type)
    expected_identity = {
        "alt": frame.alt,
        "group": atlas.group,
        "index": frame.index,
        "name": frame.name,
        "page": frame.page,
        "source_main_rgba_sha256": frame.main_source_rgba_sha256,
        "source_mask_rgba_sha256": frame.mask_source_rgba_sha256,
    }
    if any(value[key] != expected for key, expected in expected_identity.items()):
        raise error_type(f"{label} identity/source digest changed")
    _sha256(value["decoded_main_rgba_sha256"], f"{label}.decoded_main_rgba_sha256", error_type)
    decoded_mask = _sha256(
        value["decoded_mask_rgba_sha256"],
        f"{label}.decoded_mask_rgba_sha256",
        error_type,
        nullable=True,
    )
    if (frame.mask_source_rgba_sha256 is None) != (decoded_mask is None):
        raise error_type(f"{label} mask evidence completeness changed")
    metrics = value["metrics"]
    expected_metrics = dict(_MAIN_METRICS)
    if frame.mask_source_rgba_sha256 is not None:
        expected_metrics.update(_MASK_METRICS)
    if not isinstance(metrics, Mapping) or set(metrics) != set(expected_metrics):
        raise error_type(f"{label}.metrics set changed")
    samples = frame.rect.width * frame.rect.height
    parsed_metrics: dict[str, ErrorMetric] = {}
    for metric_name in sorted(expected_metrics):
        parsed_metrics[metric_name] = _validate_metric(
            metrics[metric_name],
            label=f"{label}.metrics.{metric_name}",
            expected_channels=expected_metrics[metric_name],
            expected_samples=samples,
            error_type=error_type,
        )
    return FrameQualityEvidence(
        group=atlas.group,
        name=frame.name,
        index=frame.index,
        alt=frame.alt,
        page=frame.page,
        source_main_rgba_sha256=frame.main_source_rgba_sha256,
        decoded_main_rgba_sha256=str(value["decoded_main_rgba_sha256"]),
        source_mask_rgba_sha256=frame.mask_source_rgba_sha256,
        decoded_mask_rgba_sha256=decoded_mask,
        metrics=parsed_metrics,
    )


def _validate_quality_jsonl(
    path: Path,
    *,
    atlas: AtlasV3,
    descriptor: GroupCacheInput,
    error_type: type[GroupCacheError],
    require_single_link: bool,
) -> tuple[FileFingerprint, str, tuple[FrameQualityEvidence, ...]]:
    label = "full per-frame quality JSONL"
    try:
        before = path.lstat()
    except OSError as exc:
        raise error_type(f"{label} cannot be inspected") from exc
    if (
        _is_reparse_or_link(path)
        or not stat_module.S_ISREG(before.st_mode)
        or (require_single_link and int(before.st_nlink) != 1)
        or not 0 < before.st_size <= MAX_QUALITY_JSONL_BYTES
    ):
        raise error_type(f"{label} is linked, hardlinked, non-regular, or oversized")
    digest = sha256()
    crc = 0
    evidence_digest = sha256()
    evidence_digest.update(b"[")
    count = 0
    parsed_frames: list[FrameQualityEvidence] = []
    try:
        with path.open("rb") as stream:
            opened_before = os.fstat(stream.fileno())
            for line in stream:
                digest.update(line)
                crc = zlib.crc32(line, crc)
                if (
                    not line.endswith(b"\n")
                    or line.endswith(b"\r\n")
                    or len(line) > MAX_QUALITY_LINE_BYTES
                    or line == b"\n"
                ):
                    raise error_type(f"{label} line {count} is not one canonical JSON line")
                if count >= len(atlas.frames):
                    raise error_type(f"{label} contains extra frame records")
                try:
                    raw = _decode_json(line[:-1], f"{label} line {count}")
                except GroupCacheError as exc:
                    raise error_type(str(exc)) from exc
                if _canonical_json_bytes(raw, final_lf=True) != line:
                    raise error_type(f"{label} line {count} is not canonical JSON")
                parsed_frames.append(
                    _validate_quality_record(
                        raw,
                        atlas=atlas,
                        ordinal=count,
                        error_type=error_type,
                    )
                )
                if count:
                    evidence_digest.update(b",")
                evidence_digest.update(line[:-1])
                count += 1
            opened_after = os.fstat(stream.fileno())
        after = path.lstat()
    except error_type:
        raise
    except OSError as exc:
        raise error_type(f"{label} could not be read") from exc
    if (
        len(
            {
                _stat_identity(before),
                _stat_identity(opened_before),
                _stat_identity(opened_after),
                _stat_identity(after),
            }
        )
        != 1
        or count != len(atlas.frames)
        or count != descriptor.frame_count
    ):
        raise error_type(f"{label} changed or does not cover every frame")
    evidence_digest.update(b"]")
    return (
        FileFingerprint(before.st_size, digest.hexdigest(), f"{crc & 0xffffffff:08x}"),
        evidence_digest.hexdigest(),
        tuple(parsed_frames),
    )


def _artifact_common(filename: str, fingerprint: FileFingerprint) -> dict[str, object]:
    return {
        "crc32": fingerprint.crc32,
        "filename": filename,
        "sha256": fingerprint.sha256,
        "size_bytes": fingerprint.size_bytes,
    }


def _object_manifest(
    *,
    descriptor: GroupCacheInput,
    bundle: FileFingerprint,
    bundle_name: str,
    unity_hash128: str,
    index_group: FileFingerprint,
    atlas: FileFingerprint,
    quality: FileFingerprint,
    quality_evidence_sha256: str,
) -> dict[str, object]:
    artifacts: dict[str, object] = {
        "atlas": {
            **_artifact_common(ATLAS_FILENAME, atlas),
            "schema": BC7_ATLAS_SCHEMA,
        },
        "bundle": {
            **_artifact_common(bundle_name, bundle),
            "unity_hash128": unity_hash128,
        },
        "index_group": {
            **_artifact_common(INDEX_GROUP_FILENAME, index_group),
            "schema": INDEX_GROUP_SCHEMA,
        },
        "quality_frames": {
            **_artifact_common(QUALITY_FRAMES_FILENAME, quality),
            "evidence_sha256": quality_evidence_sha256,
            "frame_count": descriptor.frame_count,
            "schema": QUALITY_JSONL_SCHEMA,
        },
    }
    return {
        "artifact_set_sha256": sha256(
            _canonical_json_bytes(artifacts, final_lf=False)
        ).hexdigest(),
        "artifacts": artifacts,
        "cache_key": descriptor.cache_key,
        "group": {
            "gm_id": descriptor.gm_id,
            "name": descriptor.group,
            "slug": descriptor.slug,
        },
        "input": descriptor.as_dict(),
        "schema": OBJECT_SCHEMA,
    }


def _object_relative_path(descriptor: GroupCacheInput) -> str:
    return f"objects/{descriptor.cache_key[:2]}/{descriptor.cache_key}"


def _ref_document(
    descriptor: GroupCacheInput, *, manifest_sha256: str
) -> dict[str, object]:
    return {
        "cache_key": descriptor.cache_key,
        "gm_id": descriptor.gm_id,
        "group": descriptor.group,
        "manifest_sha256": manifest_sha256,
        "object_relative_path": _object_relative_path(descriptor),
        "schema": REF_SCHEMA,
    }


def _cleanup_flat_staging(path: Path) -> None:
    """Remove only a known, flat staging directory created by this module."""

    if not path.exists():
        return
    if _is_reparse_or_link(path) or not path.is_dir():
        raise GroupCachePublicationError(
            f"Refusing to clean unsafe group-cache staging path: {path}"
        )
    entries = list(path.iterdir())
    for entry in entries:
        if _is_reparse_or_link(entry) or not entry.is_file():
            raise GroupCachePublicationError(
                f"Refusing to clean non-flat group-cache staging entry: {entry}"
            )
    for entry in entries:
        entry.unlink()
    path.rmdir()


def _rename_directory_noreplace(source: Path, destination: Path) -> None:
    """Atomically publish a directory without replacement on Windows/Linux."""

    if os.name == "nt":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        move_file = kernel32.MoveFileExW
        move_file.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
        move_file.restype = ctypes.c_int
        # MOVEFILE_WRITE_THROUGH, deliberately without MOVEFILE_REPLACE_EXISTING.
        if move_file(str(source), str(destination), 0x8):
            return
        code = ctypes.get_last_error()
        if code in {80, 183}:
            raise FileExistsError(str(destination))
        raise OSError(code, os.strerror(code), str(destination))

    if os.name == "posix" and hasattr(ctypes.CDLL(None), "renameat2"):
        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = libc.renameat2
        renameat2.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameat2.restype = ctypes.c_int
        if renameat2(-100, os.fsencode(source), -100, os.fsencode(destination), 1) == 0:
            return
        code = ctypes.get_errno()
        if code == errno.EEXIST:
            raise FileExistsError(str(destination))
        raise OSError(code, os.strerror(code), str(destination))
    raise GroupCachePublicationError(
        "This platform lacks an atomic no-replace directory publication primitive"
    )


def _publish_ref_no_replace(
    layout: _CacheLayout,
    descriptor: GroupCacheInput,
    *,
    manifest_sha256: str,
) -> Path:
    group_refs = _ensure_child_directory(layout.refs, descriptor.slug, "group ref directory")
    filename = f"{descriptor.cache_key}.v1.json"
    existing = _existing_child(
        group_refs,
        filename,
        directory=False,
        label="group cache ref",
        error_type=GroupCachePublicationError,
    )
    expected_payload = _canonical_json_bytes(
        _ref_document(descriptor, manifest_sha256=manifest_sha256), final_lf=True
    )
    if existing is not None:
        payload, _fingerprint = _read_direct_file(
            existing,
            maximum_bytes=MAX_REF_BYTES,
            label="group cache ref",
            error_type=GroupCachePublicationError,
            require_single_link=True,
        )
        if payload != expected_payload:
            raise GroupCachePublicationError("Existing group cache ref differs")
        return existing

    temporary = layout.staging / f".ref-{uuid.uuid4().hex}.tmp"
    _write_exclusive(temporary, expected_payload, "staged group cache ref")
    destination = group_refs / filename
    try:
        # Linking a completely flushed staging file gives an atomic no-clobber
        # publication on NTFS and POSIX.  Removing the temporary name restores
        # a single link, which validation requires.
        os.link(temporary, destination)
    except FileExistsError:
        pass
    except OSError as exc:
        raise GroupCachePublicationError("Could not atomically publish group cache ref") from exc
    finally:
        if temporary.exists():
            temporary.unlink()
    payload, _fingerprint = _read_direct_file(
        destination,
        maximum_bytes=MAX_REF_BYTES,
        label="published group cache ref",
        error_type=GroupCachePublicationError,
        require_single_link=True,
    )
    if payload != expected_payload:
        raise GroupCachePublicationError("Published group cache ref differs")
    return destination


def _object_path_for_publication(
    layout: _CacheLayout, descriptor: GroupCacheInput
) -> tuple[Path, Path]:
    shard = _ensure_child_directory(
        layout.objects, descriptor.cache_key[:2], "group cache object shard"
    )
    return shard, shard / descriptor.cache_key


def _existing_object_path(
    layout: _CacheLayout, descriptor: GroupCacheInput
) -> Path | None:
    shard = _existing_child(
        layout.objects,
        descriptor.cache_key[:2],
        directory=True,
        label="group cache object shard",
        error_type=GroupCacheCorruptionError,
    )
    if shard is None:
        return None
    return _existing_child(
        shard,
        descriptor.cache_key,
        directory=True,
        label="group cache object",
        error_type=GroupCacheCorruptionError,
    )


def _existing_ref_path(
    layout: _CacheLayout, descriptor: GroupCacheInput
) -> Path | None:
    group_refs = _existing_child(
        layout.refs,
        descriptor.slug,
        directory=True,
        label="group ref directory",
        error_type=GroupCacheCorruptionError,
    )
    if group_refs is None:
        return None
    return _existing_child(
        group_refs,
        f"{descriptor.cache_key}.v1.json",
        directory=False,
        label="group cache ref",
        error_type=GroupCacheCorruptionError,
    )


def _artifact_record(
    value: object,
    *,
    role: str,
    expected_filename: str,
    extra_keys: set[str],
) -> Mapping[str, object]:
    record = _mapping(
        value,
        _COMMON_ARTIFACT_KEYS | extra_keys,
        f"object artifacts.{role}",
        GroupCacheCorruptionError,
    )
    if record["filename"] != expected_filename:
        raise GroupCacheCorruptionError(f"object artifacts.{role}.filename changed")
    _sha256(record["sha256"], f"object artifacts.{role}.sha256", GroupCacheCorruptionError)
    _crc32(record["crc32"], f"object artifacts.{role}.crc32", GroupCacheCorruptionError)
    _integer(
        record["size_bytes"],
        f"object artifacts.{role}.size_bytes",
        GroupCacheCorruptionError,
        minimum=1,
    )
    return record


def _read_canonical_cache_json(
    path: Path, *, maximum_bytes: int, label: str
) -> tuple[dict[str, object], bytes, FileFingerprint]:
    payload, fingerprint = _read_direct_file(
        path,
        maximum_bytes=maximum_bytes,
        label=label,
        error_type=GroupCacheCorruptionError,
        require_single_link=True,
    )
    try:
        value = _decode_json(payload, label)
    except GroupCacheError as exc:
        raise GroupCacheCorruptionError(str(exc)) from exc
    if not isinstance(value, dict) or payload != _canonical_json_bytes(value, final_lf=True):
        raise GroupCacheCorruptionError(f"{label} is not canonical JSON")
    return value, payload, fingerprint


def _validate_object_directory(
    object_directory: Path,
    *,
    descriptor: GroupCacheInput,
) -> CachedAssetStreamGroup:
    _assert_direct_directory(
        object_directory, "group cache object", GroupCacheCorruptionError
    )
    expected_bundle = f"sede.gm.{descriptor.slug}.bc7.v2"
    expected_names = {
        ATLAS_FILENAME,
        expected_bundle,
        INDEX_GROUP_FILENAME,
        OBJECT_MANIFEST_FILENAME,
        QUALITY_FRAMES_FILENAME,
    }
    try:
        entries = list(object_directory.iterdir())
    except OSError as exc:
        raise GroupCacheCorruptionError("Could not enumerate group cache object") from exc
    folded = [entry.name.casefold() for entry in entries]
    if len(folded) != len(set(folded)) or {entry.name for entry in entries} != expected_names:
        raise GroupCacheCorruptionError("Group cache object file set or spelling changed")
    for entry in entries:
        if _is_reparse_or_link(entry) or not entry.is_file() or entry.lstat().st_nlink != 1:
            raise GroupCacheCorruptionError(
                "Group cache object contains a linked, reparsed, or non-file entry"
            )

    manifest_path = object_directory / OBJECT_MANIFEST_FILENAME
    manifest, manifest_payload, _manifest_fingerprint = _read_canonical_cache_json(
        manifest_path,
        maximum_bytes=MAX_OBJECT_MANIFEST_BYTES,
        label="group cache object manifest",
    )
    _mapping(manifest, _OBJECT_ROOT_KEYS, "object manifest", GroupCacheCorruptionError)
    if manifest["schema"] != OBJECT_SCHEMA or manifest["cache_key"] != descriptor.cache_key:
        raise GroupCacheCorruptionError("Object manifest identity changed")
    try:
        embedded = _validate_input_document(manifest["input"])
    except GroupCacheInputError as exc:
        raise GroupCacheCorruptionError(f"Object manifest input changed: {exc}") from exc
    if (
        embedded.cache_key != descriptor.cache_key
        or embedded.canonical_payload != descriptor.canonical_payload
    ):
        raise GroupCacheCorruptionError("Object manifest input binding changed")
    manifest_group = _mapping(
        manifest["group"],
        {"gm_id", "name", "slug"},
        "object manifest group",
        GroupCacheCorruptionError,
    )
    _integer(
        manifest_group["gm_id"],
        "object manifest group.gm_id",
        GroupCacheCorruptionError,
        maximum=MAX_GM_ID,
    )
    _text(
        manifest_group["name"],
        "object manifest group.name",
        GroupCacheCorruptionError,
        maximum=128,
    )
    _identifier(
        manifest_group["slug"],
        "object manifest group.slug",
        GroupCacheCorruptionError,
    )
    expected_group = {
        "gm_id": descriptor.gm_id,
        "name": descriptor.group,
        "slug": descriptor.slug,
    }
    if manifest_group != expected_group:
        raise GroupCacheCorruptionError("Object manifest group identity changed")

    artifacts = _mapping(
        manifest["artifacts"], _ARTIFACT_KEYS, "object artifacts", GroupCacheCorruptionError
    )
    bundle_record = _artifact_record(
        artifacts["bundle"],
        role="bundle",
        expected_filename=expected_bundle,
        extra_keys={"unity_hash128"},
    )
    unity_hash = _hash128(
        bundle_record["unity_hash128"],
        "object artifacts.bundle.unity_hash128",
        GroupCacheCorruptionError,
    )
    atlas_record = _artifact_record(
        artifacts["atlas"],
        role="atlas",
        expected_filename=ATLAS_FILENAME,
        extra_keys={"schema"},
    )
    index_record = _artifact_record(
        artifacts["index_group"],
        role="index_group",
        expected_filename=INDEX_GROUP_FILENAME,
        extra_keys={"schema"},
    )
    quality_record = _artifact_record(
        artifacts["quality_frames"],
        role="quality_frames",
        expected_filename=QUALITY_FRAMES_FILENAME,
        extra_keys={"evidence_sha256", "frame_count", "schema"},
    )
    if (
        atlas_record["schema"] != BC7_ATLAS_SCHEMA
        or index_record["schema"] != INDEX_GROUP_SCHEMA
        or quality_record["schema"] != QUALITY_JSONL_SCHEMA
        or quality_record["frame_count"] != descriptor.frame_count
    ):
        raise GroupCacheCorruptionError("Object artifact schema/count changed")
    quality_evidence_sha = _sha256(
        quality_record["evidence_sha256"],
        "object artifacts.quality_frames.evidence_sha256",
        GroupCacheCorruptionError,
    )
    assert quality_evidence_sha is not None
    expected_artifact_set_sha = sha256(
        _canonical_json_bytes(dict(artifacts), final_lf=False)
    ).hexdigest()
    if manifest["artifact_set_sha256"] != expected_artifact_set_sha:
        raise GroupCacheCorruptionError("Object artifact_set_sha256 changed")

    bundle_path = object_directory / expected_bundle
    atlas_path = object_directory / ATLAS_FILENAME
    index_path = object_directory / INDEX_GROUP_FILENAME
    quality_path = object_directory / QUALITY_FRAMES_FILENAME
    bundle_fp = _fingerprint_direct_file(
        bundle_path,
        maximum_bytes=MAX_BUNDLE_BYTES,
        label="cached group bundle",
        error_type=GroupCacheCorruptionError,
        require_single_link=True,
    )
    atlas_payload, atlas_fp = _read_direct_file(
        atlas_path,
        maximum_bytes=MAX_ATLAS_BYTES,
        label="cached atlas.v3",
        error_type=GroupCacheCorruptionError,
        require_single_link=True,
    )
    atlas = _parse_atlas(
        atlas_payload,
        label="cached atlas.v3",
        error_type=GroupCacheCorruptionError,
    )

    def matches(record: Mapping[str, object], fingerprint: FileFingerprint) -> bool:
        return (
            record["size_bytes"] == fingerprint.size_bytes
            and record["sha256"] == fingerprint.sha256
            and record["crc32"] == fingerprint.crc32
        )

    if not matches(bundle_record, bundle_fp) or not matches(atlas_record, atlas_fp):
        raise GroupCacheCorruptionError("Cached bundle or atlas anchors changed")

    fragment, _fragment_payload, fragment_fp = _read_canonical_cache_json(
        index_path,
        maximum_bytes=MAX_INDEX_GROUP_BYTES,
        label="cached index group fragment",
    )
    _mapping(
        fragment,
        {"cache_key", "gm_id", "group", "record", "schema", "slug"},
        "index group fragment",
        GroupCacheCorruptionError,
    )
    if (
        fragment["schema"] != INDEX_GROUP_SCHEMA
        or fragment["cache_key"] != descriptor.cache_key
        or fragment["group"] != descriptor.group
        or fragment["slug"] != descriptor.slug
        or _integer(
            fragment["gm_id"],
            "index group fragment.gm_id",
            GroupCacheCorruptionError,
            maximum=MAX_GM_ID,
        )
        != descriptor.gm_id
    ):
        raise GroupCacheCorruptionError("Index group fragment identity changed")
    validated_record = _validate_group_record(
        fragment["record"],
        descriptor=descriptor,
        atlas=atlas,
        atlas_fingerprint=atlas_fp,
        bundle_fingerprint=bundle_fp,
        error_type=GroupCacheCorruptionError,
    )
    if validated_record != fragment["record"] or not matches(index_record, fragment_fp):
        raise GroupCacheCorruptionError("Index group fragment anchors changed")

    quality_fp, observed_evidence_sha, quality_frames = _validate_quality_jsonl(
        quality_path,
        atlas=atlas,
        descriptor=descriptor,
        error_type=GroupCacheCorruptionError,
        require_single_link=True,
    )
    if (
        not matches(quality_record, quality_fp)
        or observed_evidence_sha != quality_evidence_sha
    ):
        raise GroupCacheCorruptionError("Full quality evidence anchors changed")

    return CachedAssetStreamGroup(
        descriptor=descriptor,
        object_directory=object_directory,
        ref_path=Path(),
        manifest_path=manifest_path,
        manifest_sha256=sha256(manifest_payload).hexdigest(),
        bundle_path=bundle_path,
        index_group_path=index_path,
        atlas_path=atlas_path,
        quality_frames_path=quality_path,
        unity_hash128=unity_hash,
        quality_evidence_sha256=quality_evidence_sha,
        atlas=atlas,
        index_group_record=validated_record,
        quality_frames=quality_frames,
    )


def _validate_ref(
    path: Path,
    *,
    descriptor: GroupCacheInput,
    object_value: CachedAssetStreamGroup,
) -> None:
    value, _payload, _fingerprint = _read_canonical_cache_json(
        path, maximum_bytes=MAX_REF_BYTES, label="group cache ref"
    )
    _mapping(value, _REF_KEYS, "group cache ref", GroupCacheCorruptionError)
    _sha256(value["cache_key"], "group cache ref.cache_key", GroupCacheCorruptionError)
    _integer(
        value["gm_id"],
        "group cache ref.gm_id",
        GroupCacheCorruptionError,
        maximum=MAX_GM_ID,
    )
    _text(
        value["group"],
        "group cache ref.group",
        GroupCacheCorruptionError,
        maximum=128,
    )
    _sha256(
        value["manifest_sha256"],
        "group cache ref.manifest_sha256",
        GroupCacheCorruptionError,
    )
    _safe_relative_path(
        value["object_relative_path"],
        "group cache ref.object_relative_path",
        GroupCacheCorruptionError,
    )
    expected = _ref_document(
        descriptor, manifest_sha256=object_value.manifest_sha256
    )
    if value != expected:
        raise GroupCacheCorruptionError("Group cache ref binding changed")


def load_group_cache_object(
    *,
    workspace_root: Path,
    descriptor: GroupCacheInput | Mapping[str, object],
) -> CachedAssetStreamGroup | None:
    """Return a fully verified hit, ``None`` for absence, or fail closed.

    A valid object without its immutable ref is an interrupted publication and
    therefore remains a miss.  A present ref without its exact object, or any
    changed byte in a referenced object, raises ``GroupCacheCorruptionError``.
    """

    parsed = _coerce_descriptor(descriptor)
    layout = _existing_layout(workspace_root)
    if layout is None:
        return None
    object_path = _existing_object_path(layout, parsed)
    ref_path = _existing_ref_path(layout, parsed)
    if object_path is None:
        if ref_path is not None:
            raise GroupCacheCorruptionError("Group cache ref points to a missing object")
        return None
    object_value = _validate_object_directory(object_path, descriptor=parsed)
    if ref_path is None:
        return None
    _validate_ref(ref_path, descriptor=parsed, object_value=object_value)
    return CachedAssetStreamGroup(
        descriptor=object_value.descriptor,
        object_directory=object_value.object_directory,
        ref_path=ref_path,
        manifest_path=object_value.manifest_path,
        manifest_sha256=object_value.manifest_sha256,
        bundle_path=object_value.bundle_path,
        index_group_path=object_value.index_group_path,
        atlas_path=object_value.atlas_path,
        quality_frames_path=object_value.quality_frames_path,
        unity_hash128=object_value.unity_hash128,
        quality_evidence_sha256=object_value.quality_evidence_sha256,
        atlas=object_value.atlas,
        index_group_record=object_value.index_group_record,
        quality_frames=object_value.quality_frames,
    )


def publish_group_cache_object(
    *,
    workspace_root: Path,
    descriptor: GroupCacheInput | Mapping[str, object],
    bundle_path: Path,
    atlas_path: Path,
    index_group_record: Mapping[str, object],
    quality_frames_path: Path,
) -> CachedAssetStreamGroup:
    """Publish one immutable group object and immutable content ref.

    Existing exact objects are reused.  Existing changed/corrupt objects are
    never removed or overwritten; publication fails closed instead.
    """

    parsed = _coerce_descriptor(descriptor)
    layout = _prepare_layout(workspace_root)
    bundle_source = _generated_source(layout.workspace, bundle_path, "group bundle")
    atlas_source = _generated_source(layout.workspace, atlas_path, "atlas.v3")
    quality_source = _generated_source(
        layout.workspace, quality_frames_path, "full per-frame quality JSONL"
    )
    expected_bundle_name = f"sede.gm.{parsed.slug}.bc7.v2"
    if bundle_source.name != expected_bundle_name:
        raise GroupCachePublicationError("Group bundle filename changed")

    bundle_source_fp = _fingerprint_direct_file(
        bundle_source,
        maximum_bytes=MAX_BUNDLE_BYTES,
        label="group bundle",
        error_type=GroupCachePublicationError,
        require_single_link=False,
    )
    atlas_payload, atlas_source_fp = _read_direct_file(
        atlas_source,
        maximum_bytes=MAX_ATLAS_BYTES,
        label="atlas.v3",
        error_type=GroupCachePublicationError,
        require_single_link=False,
    )
    atlas = _parse_atlas(
        atlas_payload,
        label="atlas.v3",
        error_type=GroupCachePublicationError,
    )
    validated_record = _validate_group_record(
        index_group_record,
        descriptor=parsed,
        atlas=atlas,
        atlas_fingerprint=atlas_source_fp,
        bundle_fingerprint=bundle_source_fp,
        error_type=GroupCachePublicationError,
    )
    quality_source_fp, quality_evidence_sha, _quality_frames = _validate_quality_jsonl(
        quality_source,
        atlas=atlas,
        descriptor=parsed,
        error_type=GroupCachePublicationError,
        require_single_link=False,
    )

    shard, final_object = _object_path_for_publication(layout, parsed)
    existing = _existing_child(
        shard,
        parsed.cache_key,
        directory=True,
        label="group cache object",
        error_type=GroupCachePublicationError,
    )
    if existing is None:
        staging = Path(
            tempfile.mkdtemp(
                prefix=f".{parsed.cache_key[:16]}-",
                dir=layout.staging,
            )
        )
        try:
            staged_bundle_fp = _copy_exclusive(
                bundle_source,
                staging / expected_bundle_name,
                maximum_bytes=MAX_BUNDLE_BYTES,
                label="staged group bundle",
            )
            staged_atlas_fp = _write_exclusive(
                staging / ATLAS_FILENAME, atlas_payload, "staged atlas.v3"
            )
            if staged_bundle_fp != bundle_source_fp or staged_atlas_fp != atlas_source_fp:
                raise GroupCachePublicationError("Staged bundle/atlas bytes changed")

            fragment = {
                "cache_key": parsed.cache_key,
                "gm_id": parsed.gm_id,
                "group": parsed.group,
                "record": validated_record,
                "schema": INDEX_GROUP_SCHEMA,
                "slug": parsed.slug,
            }
            fragment_payload = _canonical_json_bytes(fragment, final_lf=True)
            if len(fragment_payload) > MAX_INDEX_GROUP_BYTES:
                raise GroupCachePublicationError("Index group fragment is oversized")
            staged_index_fp = _write_exclusive(
                staging / INDEX_GROUP_FILENAME,
                fragment_payload,
                "staged index group fragment",
            )
            staged_quality_fp = _copy_exclusive(
                quality_source,
                staging / QUALITY_FRAMES_FILENAME,
                maximum_bytes=MAX_QUALITY_JSONL_BYTES,
                label="staged full quality evidence",
            )
            if staged_quality_fp != quality_source_fp:
                raise GroupCachePublicationError("Staged quality evidence bytes changed")
            copied_quality_fp, copied_evidence_sha, _copied_frames = _validate_quality_jsonl(
                staging / QUALITY_FRAMES_FILENAME,
                atlas=atlas,
                descriptor=parsed,
                error_type=GroupCachePublicationError,
                require_single_link=True,
            )
            if (
                copied_quality_fp != quality_source_fp
                or copied_evidence_sha != quality_evidence_sha
            ):
                raise GroupCachePublicationError("Staged quality evidence changed")

            unity_hash = _hash128(
                validated_record["unity_hash128"],
                "index group unity_hash128",
                GroupCachePublicationError,
            )
            manifest = _object_manifest(
                descriptor=parsed,
                bundle=staged_bundle_fp,
                bundle_name=expected_bundle_name,
                unity_hash128=unity_hash,
                index_group=staged_index_fp,
                atlas=staged_atlas_fp,
                quality=staged_quality_fp,
                quality_evidence_sha256=quality_evidence_sha,
            )
            manifest_payload = _canonical_json_bytes(manifest, final_lf=True)
            if len(manifest_payload) > MAX_OBJECT_MANIFEST_BYTES:
                raise GroupCachePublicationError("Object manifest is oversized")
            _write_exclusive(
                staging / OBJECT_MANIFEST_FILENAME,
                manifest_payload,
                "staged object manifest",
            )
            try:
                _rename_directory_noreplace(staging, final_object)
            except FileExistsError:
                _cleanup_flat_staging(staging)
            except OSError as exc:
                raise GroupCachePublicationError(
                    "Could not atomically publish group cache object"
                ) from exc
        except Exception:
            if staging.exists():
                _cleanup_flat_staging(staging)
            raise

    try:
        object_value = _validate_object_directory(final_object, descriptor=parsed)
    except GroupCacheCorruptionError as exc:
        raise GroupCachePublicationError(
            f"Existing/published group cache object is corrupt; refusing overwrite: {exc}"
        ) from exc
    existing_bundle_fp = _fingerprint_direct_file(
        object_value.bundle_path,
        maximum_bytes=MAX_BUNDLE_BYTES,
        label="published group bundle",
        error_type=GroupCachePublicationError,
        require_single_link=True,
    )
    existing_atlas_fp = _fingerprint_direct_file(
        object_value.atlas_path,
        maximum_bytes=MAX_ATLAS_BYTES,
        label="published atlas.v3",
        error_type=GroupCachePublicationError,
        require_single_link=True,
    )
    existing_quality_fp = _fingerprint_direct_file(
        object_value.quality_frames_path,
        maximum_bytes=MAX_QUALITY_JSONL_BYTES,
        label="published full quality evidence",
        error_type=GroupCachePublicationError,
        require_single_link=True,
    )
    if (
        existing_bundle_fp != bundle_source_fp
        or existing_atlas_fp != atlas_source_fp
        or existing_quality_fp != quality_source_fp
        or object_value.index_group_record != validated_record
        or object_value.quality_evidence_sha256 != quality_evidence_sha
    ):
        raise GroupCachePublicationError(
            "The same group cache key produced different artifacts; refusing reuse"
        )
    ref_path = _publish_ref_no_replace(
        layout, parsed, manifest_sha256=object_value.manifest_sha256
    )
    try:
        _validate_ref(ref_path, descriptor=parsed, object_value=object_value)
    except GroupCacheCorruptionError as exc:
        raise GroupCachePublicationError(str(exc)) from exc
    return CachedAssetStreamGroup(
        descriptor=object_value.descriptor,
        object_directory=object_value.object_directory,
        ref_path=ref_path,
        manifest_path=object_value.manifest_path,
        manifest_sha256=object_value.manifest_sha256,
        bundle_path=object_value.bundle_path,
        index_group_path=object_value.index_group_path,
        atlas_path=object_value.atlas_path,
        quality_frames_path=object_value.quality_frames_path,
        unity_hash128=object_value.unity_hash128,
        quality_evidence_sha256=object_value.quality_evidence_sha256,
        atlas=object_value.atlas,
        index_group_record=object_value.index_group_record,
        quality_frames=object_value.quality_frames,
    )


__all__ = [
    "ATLAS_FILENAME",
    "CACHE_DIRECTORY",
    "INDEX_GROUP_FILENAME",
    "INDEX_GROUP_SCHEMA",
    "INPUT_SCHEMA",
    "OBJECT_MANIFEST_FILENAME",
    "OBJECT_SCHEMA",
    "QUALITY_FRAMES_FILENAME",
    "QUALITY_JSONL_SCHEMA",
    "REF_SCHEMA",
    "CachedAssetStreamGroup",
    "GroupCacheCorruptionError",
    "GroupCacheError",
    "GroupCacheInput",
    "GroupCacheInputError",
    "GroupCachePublicationError",
    "frame_bindings_from_atlas",
    "group_contract_sha256",
    "load_group_cache_input",
    "load_group_cache_object",
    "parse_group_cache_input",
    "publish_group_cache_object",
]

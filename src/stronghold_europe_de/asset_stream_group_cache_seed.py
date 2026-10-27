"""Fail-closed migration of one proven Cold-A/B V2 build into group-cache-v1.

The migration never invokes Unity and never encodes or recompresses a texture.
It revalidates the immutable A/B payload pair, reconstructs complete quality
evidence by decoding Cold-A, and publishes only through
``publish_group_cache_object`` after every global gate has passed.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import stat as stat_module
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from . import unity_asset_bundle as unity_module
from . import asset_stream_incremental_v2 as incremental_module
from .asset_stream_contract import (
    BC7_ATLAS_BACKEND_KIND,
    BC7_ATLAS_SCHEMA,
    AssetStreamContractError,
    AtlasV3,
    QualityPolicy,
    TexturePolicy,
    canonical_group_slug,
    parse_asset_bundle_index_v2,
    parse_atlas_backend,
    parse_atlas_v3,
)
from .asset_stream_group_cache import (
    CachedAssetStreamGroup,
    GroupCacheInput,
    frame_bindings_from_atlas,
    load_group_cache_object,
    publish_group_cache_object,
)
from .asset_stream_incremental_v2 import build_group_cache_descriptors
from .asset_stream_quality import (
    FrameQualityEvidence,
    QualityCropCollector,
    canonical_json_bytes,
)
from .unity_asset_bundle import (
    AtlasGroupFingerprint,
    AtlasGroupInput,
    PreparedUnityProject,
)


QUALITY_REPORT_SCHEMA = "stronghold-europe-de.asset-bundle-quality-report.v1"
AUDIT_REPORT_SCHEMA = (
    "stronghold-europe-de.asset-stream-group-cache-seed-audit.v1"
)
_QUALITY_REPORT_KEYS = frozenset(
    {
        "acceptance_envelope_sha256",
        "accepted",
        "backend",
        "build_id",
        "bundles",
        "encoder_id",
        "failure_count",
        "failures",
        "failures_truncated",
        "frame_count",
        "frames",
        "frames_sha256",
        "mode",
        "promotable",
        "quality_policy_id",
        "quality_policy_sha256",
        "schema",
        "texture_policy_id",
        "worst_case",
    }
)
_QUALITY_FRAME_KEYS = frozenset(
    {"alt", "evidence_sha256", "group", "index", "name", "page"}
)
_QUALITY_BUNDLE_KEYS = frozenset({"name", "sha256", "size_bytes"})
_SHA256_HEX = frozenset("0123456789abcdef")


class ColdABGroupCacheSeedError(RuntimeError):
    """Raised before unproven Cold-A/B data can become a cache ref."""


@dataclass(frozen=True, slots=True)
class SourceBridgePins:
    """Exact reviewed bridge from the cold packer source to the current key."""

    cold_packer_source: Path
    cold_packer_sha256: str
    current_packer_source: Path
    current_packer_sha256: str
    current_quality_source: Path
    current_quality_sha256: str
    editor_source: Path
    editor_sha256: str
    bridge_id: str


@dataclass(frozen=True, slots=True)
class RuntimeCapabilityFilePin:
    """One exact source file contributing to the target runtime cache lane."""

    relative_path: str
    path: Path
    sha256: str


@dataclass(frozen=True, slots=True)
class RuntimeCapabilityPins:
    """Exact target runtime-capability identity for the new cache keys."""

    id: str
    sha256: str
    files: tuple[RuntimeCapabilityFilePin, ...]


@dataclass(frozen=True, slots=True)
class ColdABGroupCacheSeedSpec:
    workspace_root: Path
    cold_a_build_root: Path
    cold_b_build_root: Path
    cold_profile_path: Path
    target_profile_path: Path
    evidence_work_parent: Path
    build_id: str
    unity_executable_sha256: str
    expected_group_count: int
    expected_frame_count: int
    final_index_sha256: str
    quality_report_sha256: str
    quality_frames_sha256: str
    source_bridge: SourceBridgePins
    runtime_capabilities: RuntimeCapabilityPins
    foliage_groups: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ColdABGroupCacheSeedResult:
    build_id: str
    cache_keys: tuple[str, ...]
    evidence_root: Path
    audit_report_path: Path
    audit_report_sha256: str
    group_proofs_sha256: str
    runtime_capabilities_sha256: str
    validated_group_count: int
    validated_frame_count: int
    published_count: int
    hit_count: int


@dataclass(frozen=True, slots=True)
class _StableFile:
    path: Path
    signature: tuple[int, int, int, int, int, int]
    sha256: str


@dataclass(frozen=True, slots=True)
class _GroupSeed:
    descriptor: GroupCacheInput
    atlas: AtlasV3
    atlas_path: Path
    bundle_path: Path
    index_record: Mapping[str, object]
    expected_quality_rows: tuple[Mapping[str, object], ...]


GateRunner = Callable[[], None]
EvidenceRehydrator = Callable[
    [Path, Mapping[str, object], PreparedUnityProject],
    Sequence[FrameQualityEvidence],
]
DescriptorBuilder = Callable[..., tuple[GroupCacheInput, ...]]
Publisher = Callable[..., CachedAssetStreamGroup]
Loader = Callable[..., CachedAssetStreamGroup | None]


def _fail(message: str) -> None:
    raise ColdABGroupCacheSeedError(message)


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and set(value) <= _SHA256_HEX
    )


def _signature(path: Path) -> tuple[int, int, int, int, int, int]:
    value = path.stat()
    return (
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
        getattr(value, "st_dev", 0),
        getattr(value, "st_ino", 0),
        getattr(value, "st_file_attributes", 0),
    )


def _is_link_or_reparse(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if is_junction is not None and is_junction():
        return True
    try:
        attributes = path.lstat().st_file_attributes
    except (AttributeError, OSError):
        return False
    return bool(
        attributes
        & getattr(stat_module, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def _reject_reparse_chain(path: Path, label: str) -> None:
    absolute = Path(os.path.abspath(path))
    for component in (absolute, *absolute.parents):
        if os.path.lexists(component) and _is_link_or_reparse(component):
            _fail(f"{label} traverses a link/junction: {component}")


def _inside(root: Path, path: Path, label: str) -> Path:
    _reject_reparse_chain(path, label)
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ColdABGroupCacheSeedError(f"{label} is missing: {path}") from exc
    if resolved != root and root not in resolved.parents:
        _fail(f"{label} escaped the repository workspace: {resolved}")
    return resolved


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _pin_file(
    root: Path,
    path: Path,
    label: str,
    *,
    expected_sha256: str | None = None,
) -> _StableFile:
    resolved = _inside(root, path, label)
    if not resolved.is_file():
        _fail(f"{label} is not a regular file: {resolved}")
    before = _signature(resolved)
    digest = _sha256_file(resolved)
    if _signature(resolved) != before:
        _fail(f"{label} changed while hashing: {resolved}")
    if expected_sha256 is not None and digest != expected_sha256:
        _fail(
            f"{label} SHA-256 changed: expected={expected_sha256} actual={digest}"
        )
    return _StableFile(resolved, before, digest)


def _verify_stable(files: Sequence[_StableFile]) -> None:
    for item in files:
        if not os.path.lexists(item.path) or _signature(item.path) != item.signature:
            _fail(f"Verified seed input changed before publication: {item.path}")


def _reject_duplicate_pairs(
    pairs: Sequence[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            _fail(f"JSON repeats key {key!r}")
        result[key] = value
    return result


def _strict_json(payload: bytes, label: str) -> object:
    try:
        return json.loads(
            payload.decode("utf-8", errors="strict"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=lambda token: _fail(
                f"{label} contains non-finite JSON value {token!r}"
            ),
        )
    except ColdABGroupCacheSeedError:
        raise
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ColdABGroupCacheSeedError(f"Could not parse {label}") from exc


def _canonical_object(payload: bytes, label: str) -> dict[str, object]:
    value = _strict_json(payload, label)
    if not isinstance(value, dict):
        _fail(f"{label} root is not an object")
    if payload != canonical_json_bytes(value, final_lf=True):
        _fail(f"{label} is not canonical UTF-8 JSON plus one LF")
    return value


def _profile_object(path: Path, root: Path, label: str) -> dict[str, object]:
    pinned = _pin_file(root, path, label)
    value = _strict_json(pinned.path.read_bytes(), label)
    if not isinstance(value, dict):
        _fail(f"{label} root is not an object")
    return value


def _validate_profile_lanes(
    *,
    root: Path,
    cold_profile_path: Path,
    target_profile_path: Path,
) -> tuple[TexturePolicy, QualityPolicy]:
    cold = _profile_object(cold_profile_path, root, "Cold profile")
    target = _profile_object(target_profile_path, root, "target V2 profile")
    for lane in ("gm_atlases", "authored_sprites"):
        if target.get(lane) != cold.get(lane):
            _fail(f"Target profile {lane} differs from the proven Cold profile")
    cold_backend = cold.get("atlas_backend")
    target_backend_raw = target.get("atlas_backend")
    if not isinstance(cold_backend, Mapping) or not isinstance(
        target_backend_raw, Mapping
    ):
        _fail("Cold/target profile has no atlas_backend object")
    # The frozen Cold profile predates the current hard-private resource-policy V4
    # and is deliberately rejected by today's whole-backend parser.  Resource
    # budgets are not a group-cache key lane.  The complete A/B gate pins that
    # historical profile; compare the three group-local backend lanes raw and
    # parse the current target backend with today's authoritative contract.
    for lane in ("kind", "texture_policy", "quality_policy"):
        if target_backend_raw.get(lane) != cold_backend.get(lane):
            _fail(f"Target profile atlas_backend.{lane} differs from Cold-A/B")
    try:
        target_backend = parse_atlas_backend(target)
    except AssetStreamContractError as exc:
        raise ColdABGroupCacheSeedError("Profile backend contract is invalid") from exc
    if (
        target_backend is None
        or target_backend.kind != BC7_ATLAS_BACKEND_KIND
        or target_backend.texture_policy is None
        or target_backend.quality_policy is None
        or not target_backend.quality_policy.promotable
    ):
        _fail("Target profile V2 texture/quality lanes differ from Cold-A/B")
    return target_backend.texture_policy, target_backend.quality_policy


def _validate_source_bridge(
    root: Path, pins: SourceBridgePins
) -> tuple[_StableFile, ...]:
    if not pins.bridge_id or not all(
        _is_sha256(value)
        for value in (
            pins.cold_packer_sha256,
            pins.current_packer_sha256,
            pins.current_quality_sha256,
            pins.editor_sha256,
        )
    ):
        _fail("Source bridge pins are malformed")
    files = (
        _pin_file(
            root,
            pins.cold_packer_source,
            "Cold packer source",
            expected_sha256=pins.cold_packer_sha256,
        ),
        _pin_file(
            root,
            pins.current_packer_source,
            "current packer source",
            expected_sha256=pins.current_packer_sha256,
        ),
        _pin_file(
            root,
            pins.current_quality_source,
            "current quality verifier source",
            expected_sha256=pins.current_quality_sha256,
        ),
        _pin_file(
            root,
            pins.editor_source,
            "Unity editor builder source",
            expected_sha256=pins.editor_sha256,
        ),
    )
    if files[0].sha256 == files[1].sha256:
        _fail("Source bridge unexpectedly has identical old/current packer hashes")
    return files


def _require_byte_identical(
    cold_a: _StableFile,
    cold_b: _StableFile,
    label: str,
) -> None:
    """Compare two already-hashed artifacts byte for byte with bounded memory."""

    if (
        cold_a.signature[0] != cold_b.signature[0]
        or cold_a.sha256 != cold_b.sha256
    ):
        _fail(f"Cold-A/B {label} size or SHA-256 differs")
    try:
        with cold_a.path.open("rb") as left, cold_b.path.open("rb") as right:
            while True:
                a_chunk = left.read(8 * 1024 * 1024)
                b_chunk = right.read(8 * 1024 * 1024)
                if a_chunk != b_chunk:
                    _fail(f"Cold-A/B {label} bytes differ")
                if not a_chunk:
                    break
    except OSError as exc:
        raise ColdABGroupCacheSeedError(
            f"Could not compare Cold-A/B {label} bytes"
        ) from exc
    if (
        _signature(cold_a.path) != cold_a.signature
        or _signature(cold_b.path) != cold_b.signature
    ):
        _fail(f"Cold-A/B {label} changed during byte comparison")


def _validate_runtime_capability_pins(
    root: Path,
    pins: RuntimeCapabilityPins,
) -> tuple[tuple[_StableFile, ...], tuple[dict[str, object], ...]]:
    if (
        pins.id != incremental_module.RUNTIME_CAPABILITIES_ID
        or not _is_sha256(pins.sha256)
        or not pins.files
    ):
        _fail("Target runtime-capability pins are malformed")
    authoritative = tuple(sorted(incremental_module._RUNTIME_CAPABILITY_FILES))
    supplied = tuple(item.relative_path for item in pins.files)
    if supplied != authoritative or len(set(supplied)) != len(supplied):
        _fail("Target runtime-capability source set changed")

    stable: list[_StableFile] = []
    records: list[dict[str, object]] = []
    for ordinal, item in enumerate(pins.files):
        relative = _safe_relative(
            item.relative_path,
            f"runtime capability files[{ordinal}].relative_path",
        )
        if not _is_sha256(item.sha256):
            _fail(f"Runtime capability source pin is malformed: {relative}")
        expected_path = root.joinpath(*PurePosixPath(relative).parts)
        try:
            supplied_path = item.path.resolve(strict=True)
            canonical_path = expected_path.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ColdABGroupCacheSeedError(
                f"Runtime capability source is missing: {relative}"
            ) from exc
        if supplied_path != canonical_path:
            _fail(f"Runtime capability source path changed: {relative}")
        pinned = _pin_file(
            root,
            canonical_path,
            f"runtime capability source {relative}",
            expected_sha256=item.sha256,
        )
        stable.append(pinned)
        records.append(
            {
                "path": relative,
                "sha256": pinned.sha256,
                "size_bytes": pinned.signature[0],
            }
        )
    digest_records = [
        {"path": item["path"], "sha256": item["sha256"]}
        for item in records
    ]
    calculated = sha256(
        canonical_json_bytes(digest_records, final_lf=False)
    ).hexdigest()
    if calculated != pins.sha256:
        _fail(
            "Target runtime-capability digest changed: "
            f"expected={pins.sha256} actual={calculated}"
        )
    return tuple(stable), tuple(records)


def _write_audit_report(path: Path, report: Mapping[str, object]) -> str:
    payload = canonical_json_bytes(dict(report), final_lf=True)
    try:
        with path.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        raise ColdABGroupCacheSeedError(
            f"Could not create canonical cache-seed audit report: {path}"
        ) from exc
    return sha256(payload).hexdigest()


def _safe_relative(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or "\x00" in value
        or PurePosixPath(value).is_absolute()
        or PureWindowsPath(value).is_absolute()
    ):
        _fail(f"{label} is not a canonical relative path")
    parts = PurePosixPath(value).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        _fail(f"{label} has an unsafe path component")
    return value


def _raw_group_inventory(
    index: Mapping[str, object], expected_count: int
) -> tuple[Mapping[str, object], ...]:
    raw = index.get("groups")
    if not isinstance(raw, list) or len(raw) != expected_count:
        _fail("Cold index group count changed")
    groups: list[Mapping[str, object]] = []
    names: list[str] = []
    for ordinal, item in enumerate(raw):
        if not isinstance(item, Mapping):
            _fail(f"Cold index groups[{ordinal}] is not an object")
        group = item.get("group")
        slug = item.get("slug")
        if not isinstance(group, str) or not isinstance(slug, str):
            _fail(f"Cold index groups[{ordinal}] identity is invalid")
        try:
            expected_slug = canonical_group_slug(group, f"groups[{ordinal}].group")
        except AssetStreamContractError as exc:
            raise ColdABGroupCacheSeedError(
                f"Cold index groups[{ordinal}] has an invalid GM identity"
            ) from exc
        if slug != expected_slug:
            _fail(f"Cold index groups[{ordinal}] slug changed")
        groups.append(item)
        names.append(group)
    if names != sorted(names) or len(set(names)) != len(names):
        _fail("Cold index group identities are unsorted or duplicated")
    return tuple(groups)


def _prepared_for_cold_root(
    build_root: Path, spec: ColdABGroupCacheSeedSpec
) -> PreparedUnityProject:
    output = build_root / "output"
    project = build_root / "project"
    return PreparedUnityProject(
        workspace_root=build_root.parents[2],
        build_root=build_root,
        project_path=project,
        index_template_path=project / "Assets" / "Generated" / "index.v2.template.json",
        index_path=output / "Runtime" / "AssetBundles" / "index.json",
        build_input_path=project / "Assets" / "Generated" / "build-input.v2.json",
        output_path=output / "Runtime" / "AssetBundles" / "win64",
        report_path=output / "build-report.json",
        log_path=output / "unity-editor.log",
        build_id=spec.build_id,
        group_count=spec.expected_group_count,
        omitted_group_count=0,
        page_count=0,
        pipeline_version=2,
        unity_report_path=output / "unity-build-report.v2.json",
        quality_report_path=output / "bc7-quality-report.v1.json",
    )


def _default_rehydrate(
    bundle_path: Path,
    group: Mapping[str, object],
    prepared: PreparedUnityProject,
) -> Sequence[FrameQualityEvidence]:
    collector = QualityCropCollector()
    try:
        return unity_module._validate_asset_bundle_payload_v2(  # noqa: SLF001
            bundle_path, group, prepared, collector
        )
    finally:
        collector.close()


def _write_quality_sidecar(
    path: Path,
    frames: Sequence[FrameQualityEvidence],
    expected_rows: Sequence[Mapping[str, object]],
    global_digest: Any,
    global_ordinal: int,
) -> int:
    ordered = tuple(sorted(frames, key=lambda item: (item.index, item.alt, item.name)))
    if len(ordered) != len(expected_rows):
        _fail(f"Rehydrated quality frame count changed for {path.parent.name}")
    path.parent.mkdir(parents=True, exist_ok=False)
    try:
        stream = path.open("xb")
    except OSError as exc:
        raise ColdABGroupCacheSeedError(
            f"Could not create quality evidence sidecar: {path}"
        ) from exc
    try:
        for frame, expected in zip(ordered, expected_rows, strict=True):
            full = canonical_json_bytes(frame.as_dict(), final_lf=False)
            compact = {
                "alt": frame.alt,
                "evidence_sha256": sha256(full).hexdigest(),
                "group": frame.group,
                "index": frame.index,
                "name": frame.name,
                "page": frame.page,
            }
            if compact != dict(expected):
                _fail(
                    "Rehydrated quality evidence differs from the frozen report: "
                    f"{frame.group}/{frame.name}"
                )
            if global_ordinal:
                global_digest.update(b",")
            global_digest.update(full)
            global_ordinal += 1
            stream.write(full + b"\n")
        stream.flush()
        os.fsync(stream.fileno())
    finally:
        stream.close()
    return global_ordinal


def _quality_rows_by_group(
    report: Mapping[str, object],
    *,
    spec: ColdABGroupCacheSeedSpec,
    groups: Sequence[Mapping[str, object]],
) -> dict[str, tuple[Mapping[str, object], ...]]:
    if set(report) != set(_QUALITY_REPORT_KEYS):
        _fail("Cold quality report fields changed")
    if (
        report.get("schema") != QUALITY_REPORT_SCHEMA
        or report.get("backend") != BC7_ATLAS_BACKEND_KIND
        or report.get("build_id") != spec.build_id
        or report.get("accepted") is not True
        or report.get("promotable") is not True
        or report.get("failure_count") != 0
        or report.get("failures") != []
        or report.get("frame_count") != spec.expected_frame_count
        or report.get("frames_sha256") != spec.quality_frames_sha256
    ):
        _fail("Cold quality report acceptance/digest contract changed")
    frames = report.get("frames")
    if not isinstance(frames, list) or len(frames) != spec.expected_frame_count:
        _fail("Cold quality compact frame set changed")
    ordered_identities: list[tuple[str, int, bool, str]] = []
    by_group: dict[str, list[Mapping[str, object]]] = {}
    for ordinal, row in enumerate(frames):
        if not isinstance(row, Mapping) or set(row) != set(_QUALITY_FRAME_KEYS):
            _fail(f"Cold quality frames[{ordinal}] is malformed")
        if (
            not isinstance(row["group"], str)
            or isinstance(row["index"], bool)
            or not isinstance(row["index"], int)
            or row["index"] < 0
            or not isinstance(row["alt"], bool)
            or not isinstance(row["name"], str)
            or not isinstance(row["page"], int)
            or not _is_sha256(row["evidence_sha256"])
        ):
            _fail(f"Cold quality frames[{ordinal}] values are malformed")
        identity = (
            str(row["group"]),
            int(row["index"]),
            bool(row["alt"]),
            str(row["name"]),
        )
        ordered_identities.append(identity)
        by_group.setdefault(identity[0], []).append(row)
    if ordered_identities != sorted(ordered_identities) or len(
        set(ordered_identities)
    ) != len(ordered_identities):
        _fail("Cold quality compact frames are unsorted or duplicated")
    group_names = {str(item["group"]) for item in groups}
    if set(by_group) != group_names:
        _fail("Cold index and quality report group sets differ")
    expected_bundles = [
        {
            "name": item["bundle"],
            "sha256": item["bundle_sha256"],
            "size_bytes": item["bundle_size_bytes"],
        }
        for item in groups
    ]
    bundles = report.get("bundles")
    if (
        not isinstance(bundles, list)
        or any(
            not isinstance(item, Mapping)
            or set(item) != set(_QUALITY_BUNDLE_KEYS)
            for item in bundles
        )
        or bundles != sorted(expected_bundles, key=lambda item: str(item["name"]))
    ):
        _fail("Cold quality report bundle binding differs from the final index")
    return {group: tuple(rows) for group, rows in by_group.items()}


def seed_cold_ab_group_cache_v1(
    *,
    spec: ColdABGroupCacheSeedSpec,
    run_ab_gate: GateRunner,
    publish: bool,
    evidence_rehydrator: EvidenceRehydrator = _default_rehydrate,
    descriptor_builder: DescriptorBuilder = build_group_cache_descriptors,
    publisher: Publisher = publish_group_cache_object,
    loader: Loader = load_group_cache_object,
) -> ColdABGroupCacheSeedResult:
    """Validate, rehydrate, and optionally publish one exact Cold-A/B seed.

    Publication begins only after the complete A/B, profile, source bridge,
    atlas, index, bundle, and reconstructed global quality-evidence gates pass.
    """

    try:
        root = spec.workspace_root.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ColdABGroupCacheSeedError("Workspace root is missing") from exc
    if not root.is_dir():
        _fail("Workspace root is not a directory")
    if (
        not callable(run_ab_gate)
        or not _is_sha256(spec.build_id)
        or not _is_sha256(spec.unity_executable_sha256)
        or not _is_sha256(spec.final_index_sha256)
        or not _is_sha256(spec.quality_report_sha256)
        or not _is_sha256(spec.quality_frames_sha256)
        or spec.expected_group_count <= 0
        or spec.expected_frame_count <= 0
    ):
        _fail("Cold-A/B seed specification is malformed")

    run_ab_gate()
    stable_files: list[_StableFile] = list(
        _validate_source_bridge(root, spec.source_bridge)
    )
    runtime_files, runtime_source_records = _validate_runtime_capability_pins(
        root, spec.runtime_capabilities
    )
    stable_files.extend(runtime_files)
    cold_profile_file = _pin_file(
        root, spec.cold_profile_path, "Cold profile"
    )
    target_profile_file = _pin_file(
        root, spec.target_profile_path, "target V2 profile"
    )
    stable_files.extend((cold_profile_file, target_profile_file))
    texture_policy, quality_policy = _validate_profile_lanes(
        root=root,
        cold_profile_path=spec.cold_profile_path,
        target_profile_path=spec.target_profile_path,
    )
    cold_a = _inside(root, spec.cold_a_build_root, "Cold-A build root")
    cold_b = _inside(root, spec.cold_b_build_root, "Cold-B build root")
    if not cold_a.is_dir() or not cold_b.is_dir() or cold_a == cold_b:
        _fail("Cold-A/B build roots are invalid or alias each other")

    index_relative = Path("output/Runtime/AssetBundles/index.json")
    a_index = _pin_file(
        root,
        cold_a / index_relative,
        "Cold-A final index",
        expected_sha256=spec.final_index_sha256,
    )
    b_index = _pin_file(
        root,
        cold_b / index_relative,
        "Cold-B final index",
        expected_sha256=spec.final_index_sha256,
    )
    stable_files.extend((a_index, b_index))
    a_index_raw = a_index.path.read_bytes()
    _require_byte_identical(a_index, b_index, "final index")
    index_document = _canonical_object(a_index_raw, "Cold-A/B final index")
    if index_document.get("build_id") != spec.build_id:
        _fail("Cold-A/B final index build id changed")
    raw_groups = _raw_group_inventory(
        index_document, spec.expected_group_count
    )

    atlas_documents: dict[str, bytes] = {}
    atlases: dict[str, AtlasV3] = {}
    atlas_proofs: dict[str, dict[str, object]] = {}
    for raw_group in raw_groups:
        group = str(raw_group["group"])
        slug = str(raw_group["slug"])
        asset_relative = _safe_relative(
            raw_group.get("atlas_asset_path"), f"{group}.atlas_asset_path"
        )
        expected_relative = f"Assets/Generated/Groups/{slug}/atlas.v3.json"
        if asset_relative != expected_relative:
            _fail(f"Cold atlas path changed for {group}")
        a_atlas = _pin_file(
            root, cold_a / "project" / Path(asset_relative), f"Cold-A atlas {group}"
        )
        b_atlas = _pin_file(
            root, cold_b / "project" / Path(asset_relative), f"Cold-B atlas {group}"
        )
        stable_files.extend((a_atlas, b_atlas))
        atlas_raw = a_atlas.path.read_bytes()
        _require_byte_identical(a_atlas, b_atlas, f"atlas {group}")
        if sha256(atlas_raw).hexdigest() != raw_group.get("atlas_sha256"):
            _fail(f"Cold atlas/index hash binding changed for {group}")
        try:
            atlas = parse_atlas_v3(atlas_raw, label=f"Cold atlas {group}")
        except AssetStreamContractError as exc:
            raise ColdABGroupCacheSeedError(
                f"Cold atlas contract is invalid for {group}"
            ) from exc
        if (
            atlas.schema != BC7_ATLAS_SCHEMA
            or atlas.group != group
            or atlas.slug != slug
            or atlas.bundle != raw_group.get("bundle")
        ):
            _fail(f"Cold atlas identity changed for {group}")
        atlas_documents[asset_relative] = atlas_raw
        atlases[group] = atlas
        atlas_proofs[group] = {
            "byte_identical": True,
            "cold_a_sha256": a_atlas.sha256,
            "cold_b_sha256": b_atlas.sha256,
            "relative_path": asset_relative,
            "sha256": a_atlas.sha256,
            "size_bytes": a_atlas.signature[0],
        }

    try:
        parsed_index = parse_asset_bundle_index_v2(
            a_index_raw,
            atlas_documents=atlas_documents,
            expected_groups=tuple(str(item["group"]) for item in raw_groups),
        )
    except AssetStreamContractError as exc:
        raise ColdABGroupCacheSeedError(
            "Cold-A/B final index contract is invalid"
        ) from exc
    if (
        parsed_index.build_id != spec.build_id
        or len(parsed_index.groups) != spec.expected_group_count
        or sum(item.frame_count for item in parsed_index.groups)
        != spec.expected_frame_count
        or parsed_index.texture_policy != texture_policy
        or parsed_index.quality_policy != quality_policy
        or parsed_index.quality_report_sha256 != spec.quality_report_sha256
    ):
        _fail("Cold index totals/policies differ from the seed specification")

    quality_relative = Path("output/bc7-quality-report.v1.json")
    a_quality = _pin_file(
        root,
        cold_a / quality_relative,
        "Cold-A quality report",
        expected_sha256=spec.quality_report_sha256,
    )
    b_quality = _pin_file(
        root,
        cold_b / quality_relative,
        "Cold-B quality report",
        expected_sha256=spec.quality_report_sha256,
    )
    stable_files.extend((a_quality, b_quality))
    quality_raw = a_quality.path.read_bytes()
    _require_byte_identical(a_quality, b_quality, "quality report")
    quality_report = _canonical_object(quality_raw, "Cold-A/B quality report")
    quality_rows = _quality_rows_by_group(
        quality_report, spec=spec, groups=raw_groups
    )

    fingerprints: list[AtlasGroupFingerprint] = []
    bundle_paths: dict[str, Path] = {}
    group_proofs: dict[str, dict[str, object]] = {}
    raw_by_group = {str(item["group"]): item for item in raw_groups}
    for parsed_group in parsed_index.groups:
        raw_group = raw_by_group[parsed_group.group]
        if (
            parsed_group.bundle_path is None
            or parsed_group.bundle_sha256 is None
            or parsed_group.bundle_size_bytes is None
        ):
            _fail(f"Cold index group is not final: {parsed_group.group}")
        relative = _safe_relative(
            parsed_group.bundle_path, f"{parsed_group.group}.bundle_path"
        )
        a_bundle = _pin_file(
            root,
            cold_a / "output" / Path(relative),
            f"Cold-A bundle {parsed_group.bundle}",
            expected_sha256=parsed_group.bundle_sha256,
        )
        b_bundle = _pin_file(
            root,
            cold_b / "output" / Path(relative),
            f"Cold-B bundle {parsed_group.bundle}",
            expected_sha256=parsed_group.bundle_sha256,
        )
        stable_files.extend((a_bundle, b_bundle))
        if (
            a_bundle.signature[0] != parsed_group.bundle_size_bytes
            or b_bundle.signature[0] != parsed_group.bundle_size_bytes
        ):
            _fail(f"Cold-A/B bundle size/index binding changed: {parsed_group.group}")
        _require_byte_identical(
            a_bundle, b_bundle, f"bundle {parsed_group.group}"
        )
        manifest_relative = relative + ".manifest"
        a_manifest = _pin_file(
            root,
            cold_a / "output" / Path(manifest_relative),
            f"Cold-A Unity manifest {parsed_group.bundle}",
        )
        b_manifest = _pin_file(
            root,
            cold_b / "output" / Path(manifest_relative),
            f"Cold-B Unity manifest {parsed_group.bundle}",
        )
        stable_files.extend((a_manifest, b_manifest))
        _require_byte_identical(
            a_manifest,
            b_manifest,
            f"Unity manifest {parsed_group.group}",
        )
        atlas = atlases[parsed_group.group]
        spec_input = AtlasGroupInput(
            group=parsed_group.group,
            gm_id=parsed_group.gm_id,
            dash_format=parsed_group.dash_format,
            array_size=parsed_group.array_size,
            lifetime=parsed_group.lifetime,
            mask_policy=parsed_group.mask_policy,
            material_binding=parsed_group.material_binding,
            frames=(),
            padding_pixels=atlas.minimum_border_pixels,
            filter_mode=atlas.main_texture_contract.filter_mode,
        )
        fingerprints.append(
            AtlasGroupFingerprint(
                spec=spec_input,
                slug=parsed_group.slug,
                loaded_frames=(),
                frame_bindings=frame_bindings_from_atlas(atlas),
            )
        )
        bundle_paths[parsed_group.group] = a_bundle.path
        if raw_group.get("bundle") != parsed_group.bundle:
            _fail(f"Raw/parsed index bundle differs for {parsed_group.group}")
        index_group_payload = canonical_json_bytes(
            dict(raw_group), final_lf=False
        )
        group_proofs[parsed_group.group] = {
            "atlas": atlas_proofs[parsed_group.group],
            "bundle": {
                "byte_identical": True,
                "cold_a_sha256": a_bundle.sha256,
                "cold_b_sha256": b_bundle.sha256,
                "relative_path": relative,
                "sha256": a_bundle.sha256,
                "size_bytes": a_bundle.signature[0],
            },
            "frame_count": parsed_group.frame_count,
            "group": parsed_group.group,
            "index_group_manifest": {
                "byte_identical": True,
                "cold_a_sha256": sha256(index_group_payload).hexdigest(),
                "cold_b_sha256": sha256(index_group_payload).hexdigest(),
                "sha256": sha256(index_group_payload).hexdigest(),
                "size_bytes": len(index_group_payload),
            },
            "slug": parsed_group.slug,
            "unity_manifest": {
                "byte_identical": True,
                "cold_a_sha256": a_manifest.sha256,
                "cold_b_sha256": b_manifest.sha256,
                "relative_path": manifest_relative,
                "sha256": a_manifest.sha256,
                "size_bytes": a_manifest.signature[0],
            },
        }

    descriptors = descriptor_builder(
        project_root=root,
        fingerprints=tuple(fingerprints),
        editor_source=spec.source_bridge.editor_source,
        unity_executable_sha256=spec.unity_executable_sha256,
        texture_policy=texture_policy,
        quality_policy=quality_policy,
        foliage_groups=spec.foliage_groups,
    )
    descriptor_by_group = {item.group: item for item in descriptors}
    if (
        len(descriptor_by_group) != spec.expected_group_count
        or set(descriptor_by_group) != set(raw_by_group)
    ):
        _fail("Current descriptor factory returned a different group set")
    for fingerprint in fingerprints:
        descriptor = descriptor_by_group[fingerprint.spec.group]
        document = descriptor.as_dict()
        if (
            document.get("frames") != dict(fingerprint.frame_bindings)
            or document.get("packer", {}).get("source_sha256")
            != spec.source_bridge.current_packer_sha256
            or document.get("editor", {}).get("source_sha256")
            != spec.source_bridge.editor_sha256
        ):
            _fail(f"Current cache descriptor source/frame bridge changed: {descriptor.group}")
        runtime_capabilities = document.get("runtime_capabilities")
        if runtime_capabilities != {
            "id": spec.runtime_capabilities.id,
            "sha256": spec.runtime_capabilities.sha256,
        }:
            _fail(
                "Current cache descriptor runtime-capability bridge changed: "
                f"{descriptor.group}"
            )
        descriptor_payload = canonical_json_bytes(document, final_lf=False)
        descriptor_sha256 = sha256(descriptor_payload).hexdigest()
        if descriptor_sha256 != descriptor.cache_key:
            _fail(f"Current cache descriptor digest changed: {descriptor.group}")
        group_proofs[descriptor.group]["target_cache_descriptor"] = {
            "cache_key": descriptor.cache_key,
            "runtime_capabilities_id": spec.runtime_capabilities.id,
            "runtime_capabilities_sha256": spec.runtime_capabilities.sha256,
            "sha256": descriptor_sha256,
            "size_bytes": len(descriptor_payload),
        }

    evidence_parent = Path(os.path.abspath(spec.evidence_work_parent))
    if evidence_parent != root / "work" and root / "work" not in evidence_parent.parents:
        _fail("Evidence work parent must remain below repository work/")
    (root / "work").mkdir(exist_ok=True)
    evidence_parent.mkdir(parents=True, exist_ok=True)
    _reject_reparse_chain(evidence_parent, "evidence work parent")
    evidence_root = evidence_parent / (
        f"{spec.build_id[:16]}-{uuid4().hex[:12]}"
    )
    evidence_root.mkdir(exist_ok=False)

    prepared = _prepared_for_cold_root(cold_a, spec)
    global_digest = sha256()
    global_digest.update(b"[")
    global_ordinal = 0
    sidecars: dict[str, Path] = {}
    for group in sorted(raw_by_group):
        raw_group = raw_by_group[group]
        try:
            frames = tuple(
                evidence_rehydrator(bundle_paths[group], raw_group, prepared)
            )
        except ColdABGroupCacheSeedError:
            raise
        except Exception as exc:
            raise ColdABGroupCacheSeedError(
                f"Could not rehydrate quality evidence for {group}"
            ) from exc
        if any(
            not isinstance(frame, FrameQualityEvidence) or frame.group != group
            for frame in frames
        ):
            _fail(f"Rehydrated quality evidence type/group changed for {group}")
        sidecar = evidence_root / canonical_group_slug(group) / "quality-frames.v1.jsonl"
        global_ordinal = _write_quality_sidecar(
            sidecar,
            frames,
            quality_rows[group],
            global_digest,
            global_ordinal,
        )
        sidecars[group] = sidecar
        sidecar_file = _pin_file(
            root,
            sidecar,
            f"rehydrated quality sidecar {group}",
        )
        stable_files.append(sidecar_file)
        group_proofs[group]["quality_evidence_sidecar"] = {
            "frame_count": len(frames),
            "relative_path": sidecar.relative_to(evidence_root).as_posix(),
            "sha256": sidecar_file.sha256,
            "size_bytes": sidecar_file.signature[0],
        }
    global_digest.update(b"]")
    recomputed_quality_frames_sha256 = global_digest.hexdigest()
    if (
        global_ordinal != spec.expected_frame_count
        or recomputed_quality_frames_sha256 != spec.quality_frames_sha256
    ):
        _fail(
            "Rehydrated global quality evidence digest differs from Cold-A/B"
        )

    _verify_stable(stable_files)
    ordered_group_proofs = [
        group_proofs[group] for group in sorted(group_proofs)
    ]
    group_proofs_sha256 = sha256(
        canonical_json_bytes(ordered_group_proofs, final_lf=False)
    ).hexdigest()
    cache_key_records = [
        {
            "cache_key": descriptor_by_group[group].cache_key,
            "group": group,
        }
        for group in sorted(descriptor_by_group)
    ]
    cache_keys_sha256 = sha256(
        canonical_json_bytes(cache_key_records, final_lf=False)
    ).hexdigest()
    audit_report: dict[str, object] = {
        "build_id": spec.build_id,
        "cache_publish_requested": publish,
        "cache_writes_before_report": 0,
        "cold_ab": {
            "byte_identical_artifact_classes": [
                "atlas_v3",
                "bundle",
                "final_index",
                "quality_report",
                "unity_bundle_manifest",
            ],
            "cold_a_build_root": cold_a.relative_to(root).as_posix(),
            "cold_b_build_root": cold_b.relative_to(root).as_posix(),
            "complete_gate_passed": True,
            "final_index": {
                "byte_identical": True,
                "cold_a_sha256": a_index.sha256,
                "cold_b_sha256": b_index.sha256,
                "sha256": a_index.sha256,
                "size_bytes": a_index.signature[0],
            },
            "quality_report": {
                "byte_identical": True,
                "cold_a_sha256": a_quality.sha256,
                "cold_b_sha256": b_quality.sha256,
                "sha256": a_quality.sha256,
                "size_bytes": a_quality.signature[0],
            },
        },
        "evidence": {
            "frame_count": global_ordinal,
            "quality_frames_sha256": recomputed_quality_frames_sha256,
        },
        "group_count": len(ordered_group_proofs),
        "group_proofs_sha256": group_proofs_sha256,
        "groups": ordered_group_proofs,
        "mode": "prepublication_audit",
        "profiles": {
            "cold": {
                "relative_path": cold_profile_file.path.relative_to(root).as_posix(),
                "sha256": cold_profile_file.sha256,
            },
            "target": {
                "relative_path": target_profile_file.path.relative_to(root).as_posix(),
                "sha256": target_profile_file.sha256,
            },
        },
        "runtime_capabilities": {
            "id": spec.runtime_capabilities.id,
            "sha256": spec.runtime_capabilities.sha256,
            "sources": list(runtime_source_records),
        },
        "schema": AUDIT_REPORT_SCHEMA,
        "source_bridge": {
            "bridge_id": spec.source_bridge.bridge_id,
            "cold_packer_sha256": spec.source_bridge.cold_packer_sha256,
            "current_packer_sha256": spec.source_bridge.current_packer_sha256,
            "editor_sha256": spec.source_bridge.editor_sha256,
            "quality_verifier_sha256": spec.source_bridge.current_quality_sha256,
        },
        "target_cache_keys_sha256": cache_keys_sha256,
    }
    audit_report_path = evidence_root / "audit-report.v1.json"
    audit_report_sha256 = _write_audit_report(
        audit_report_path, audit_report
    )
    if _canonical_object(
        audit_report_path.read_bytes(), "cache-seed audit report"
    ) != audit_report:
        _fail("Canonical cache-seed audit report changed after writing")
    stable_files.append(
        _pin_file(root, audit_report_path, "cache-seed audit report")
    )
    _verify_stable(stable_files)

    objects: list[CachedAssetStreamGroup] = []
    if publish:
        for group in sorted(raw_by_group):
            descriptor = descriptor_by_group[group]
            objects.append(
                publisher(
                    workspace_root=root,
                    descriptor=descriptor,
                    bundle_path=bundle_paths[group],
                    atlas_path=(
                        cold_a
                        / "project"
                        / Path(str(raw_by_group[group]["atlas_asset_path"]))
                    ),
                    index_group_record=raw_by_group[group],
                    quality_frames_path=sidecars[group],
                )
            )
        loaded = [
            loader(workspace_root=root, descriptor=descriptor_by_group[group])
            for group in sorted(raw_by_group)
        ]
        if any(item is None for item in loaded):
            _fail("Post-publication cache lookup did not return every seeded group")
        for group, item in zip(sorted(raw_by_group), loaded, strict=True):
            if item is None or item.descriptor.cache_key != descriptor_by_group[group].cache_key:
                _fail(f"Post-publication cache descriptor changed for {group}")

    _verify_stable(stable_files)
    return ColdABGroupCacheSeedResult(
        build_id=spec.build_id,
        cache_keys=tuple(
            descriptor_by_group[group].cache_key for group in sorted(raw_by_group)
        ),
        evidence_root=evidence_root,
        audit_report_path=audit_report_path,
        audit_report_sha256=audit_report_sha256,
        group_proofs_sha256=group_proofs_sha256,
        runtime_capabilities_sha256=spec.runtime_capabilities.sha256,
        validated_group_count=spec.expected_group_count,
        validated_frame_count=global_ordinal,
        published_count=len(objects),
        hit_count=len(objects) if publish else 0,
    )


__all__ = [
    "AUDIT_REPORT_SCHEMA",
    "ColdABGroupCacheSeedError",
    "ColdABGroupCacheSeedResult",
    "ColdABGroupCacheSeedSpec",
    "RuntimeCapabilityFilePin",
    "RuntimeCapabilityPins",
    "SourceBridgePins",
    "seed_cold_ab_group_cache_v1",
]

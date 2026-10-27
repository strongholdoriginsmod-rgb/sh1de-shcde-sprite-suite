"""Per-GM incremental orchestration for the BC7 V2 AssetStream builder.

The expensive boundary is one GM group.  Source frames are decoded only far
enough to establish their exact cache key; cache hits never enter rectangle
packing, atlas composition, Unity import, BC7 encoding, or quality
measurement.  All misses are built together as one controlled Unity batch and
published as immutable group objects.  The final global build input, quality
report, index, and verified report are then composed deterministically from
the complete validated object set.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
from typing import Any

from . import asset_stream_quality as quality_module
from . import unity_asset_bundle as unity_module
from .asset_stream_contract import (
    BC7_ATLAS_BACKEND_KIND,
    BC7_BUILD_INPUT_SCHEMA,
    BC7_BUILD_REPORT_SCHEMA,
    BC7_INDEX_SCHEMA,
    BC7_INDEX_TEMPLATE_SCHEMA,
    AssetStreamContractError,
    QualityPolicy,
    TexturePolicy,
    parse_asset_bundle_build_input_v2,
    parse_asset_bundle_build_report_v2,
    parse_asset_bundle_index_v2,
)
from .asset_stream_group_cache import (
    INPUT_SCHEMA,
    CachedAssetStreamGroup,
    GroupCacheInput,
    group_contract_sha256,
    load_group_cache_object,
    parse_group_cache_input,
    publish_group_cache_object,
)
from .asset_stream_quality import (
    QUALITY_ACCEPTANCE_MODE,
    QUALITY_MEASUREMENT_MODE,
    FrameQualityEvidence,
    build_quality_report,
    write_observed_quality_envelope,
    write_quality_report,
)
from .unity_asset_bundle import (
    BC7_ATLAS_ASSET_FILENAME,
    BC7_ENCODER_ID,
    BC7_PACKER_ID,
    BC7_UNITY_TIMEOUT_SECONDS,
    BC7_VERIFIER_ID,
    BUILD_OPTIONS,
    BUILD_TARGET,
    MAX_PAGE_DIMENSION,
    UNITY_REVISION,
    UNITY_VERSION,
    AtlasGroupFingerprint,
    AtlasGroupInput,
    AtlasGroupPreflight,
    PreparedUnityProject,
    UnityAssetBundleError,
    fingerprint_atlas_groups_v2,
    group_quality_frames_path,
    group_slug,
    preflight_atlas_fingerprints_v2,
    prepare_unity_asset_bundle_project_v2,
    run_headless_build,
)


INCREMENTAL_COMPOSITION_SCHEMA = (
    "stronghold-europe-de.asset-stream-incremental-composition.v1"
)
RUNTIME_CAPABILITIES_ID = "asset-stream-runtime-v2"
EDITOR_ID = "stronghold-europe-assetbundle-builder-v2"
PACKER_VERSION = "2"
ENCODER_VERSION = UNITY_VERSION

_FINAL_GROUP_KEYS = frozenset(
    {
        "bundle_crc32",
        "bundle_path",
        "bundle_sha256",
        "bundle_size_bytes",
        "predicted_load_peak_bytes",
        "unity_hash128",
    }
)
_RUNTIME_CAPABILITY_FILES = (
    "runtime/StrongholdEuropeDE.Runtime/AssetStreamManifest.cs",
    "runtime/StrongholdEuropeDE.Runtime/AssetStreamPageMaskOwnership.cs",
    "runtime/StrongholdEuropeDE.Runtime/AssetStreamRuntimeLane.cs",
    "runtime/StrongholdEuropeDE.Runtime/AssetStreamStrictJson.cs",
    "runtime/StrongholdEuropeDE.Runtime/AssetStreamUnityBackend.cs",
    "runtime/StrongholdEuropeDE.Runtime/AssetStreamUnityContract.cs",
    "runtime/StrongholdEuropeDE.Runtime/RuntimeAssetStreamController.cs",
)


class IncrementalV2BuildError(RuntimeError):
    """Raised when an incremental build cannot be proven exact."""


@dataclass(frozen=True, slots=True)
class ResolvedGroupCachePlan:
    objects: tuple[CachedAssetStreamGroup, ...]
    hit_count: int
    rebuilt_count: int


@dataclass(frozen=True, slots=True)
class IncrementalV2BuildResult:
    prepared: PreparedUnityProject
    descriptors: tuple[GroupCacheInput, ...]
    objects: tuple[CachedAssetStreamGroup, ...]
    hit_count: int
    rebuilt_count: int
    unity_batch_count: int


def _canonical(value: object, *, final_lf: bool = True) -> bytes:
    try:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise IncrementalV2BuildError("Value is not canonical JSON") from exc
    return payload + (b"\n" if final_lf else b"")


def _sha_file(path: Path, label: str) -> str:
    try:
        resolved = path.resolve(strict=True)
        before = resolved.stat()
    except (OSError, RuntimeError) as exc:
        raise IncrementalV2BuildError(f"{label} is missing: {path}") from exc
    if not resolved.is_file() or resolved.is_symlink():
        raise IncrementalV2BuildError(f"{label} is not a direct regular file")
    digest = sha256()
    try:
        with resolved.open("rb") as stream:
            for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
                digest.update(chunk)
        after = resolved.stat()
    except OSError as exc:
        raise IncrementalV2BuildError(f"Could not hash {label}") from exc
    if (
        before.st_size,
        before.st_mtime_ns,
        getattr(before, "st_ino", None),
    ) != (
        after.st_size,
        after.st_mtime_ns,
        getattr(after, "st_ino", None),
    ):
        raise IncrementalV2BuildError(f"{label} changed while hashing")
    return digest.hexdigest()


def _combined_source_sha(
    root: Path, relative_paths: Sequence[str], label: str
) -> str:
    records: list[dict[str, str]] = []
    resolved_root = root.resolve(strict=True)
    for relative in sorted(relative_paths):
        path = resolved_root.joinpath(*relative.split("/"))
        try:
            resolved = path.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise IncrementalV2BuildError(f"{label} source is missing: {relative}") from exc
        if resolved_root not in resolved.parents:
            raise IncrementalV2BuildError(f"{label} source escaped the repository")
        records.append({"path": relative, "sha256": _sha_file(resolved, label)})
    return sha256(_canonical(records, final_lf=False)).hexdigest()


def _detached_mapping(value: Mapping[str, object]) -> dict[str, object]:
    decoded = json.loads(_canonical(dict(value), final_lf=False).decode("utf-8"))
    assert isinstance(decoded, dict)
    return decoded


def _validate_cached_identity(
    descriptor: GroupCacheInput, value: object
) -> CachedAssetStreamGroup:
    if not isinstance(value, CachedAssetStreamGroup):
        raise IncrementalV2BuildError("Cache loader returned a non-group object")
    if (
        value.descriptor != descriptor
        or value.atlas.group != descriptor.group
        or value.atlas.slug != descriptor.slug
        or len(value.quality_frames) != descriptor.frame_count
        or value.index_group_record.get("group") != descriptor.group
        or value.index_group_record.get("gm_id") != descriptor.gm_id
    ):
        raise IncrementalV2BuildError(
            f"Cache object semantic identity drifted: {descriptor.group}"
        )
    return value


def resolve_group_cache_plan(
    descriptors: Sequence[GroupCacheInput],
    *,
    loader: Callable[[GroupCacheInput], CachedAssetStreamGroup | None],
    rebuild_misses: Callable[
        [tuple[GroupCacheInput, ...]], Sequence[CachedAssetStreamGroup]
    ],
    semantic_validator: Callable[
        [GroupCacheInput, object], CachedAssetStreamGroup
    ] = _validate_cached_identity,
) -> ResolvedGroupCachePlan:
    """Partition a complete descriptor set and rebuild exactly the misses."""

    ordered = tuple(sorted(descriptors, key=lambda item: item.group))
    if not ordered or any(not isinstance(item, GroupCacheInput) for item in ordered):
        raise IncrementalV2BuildError("Cache plan requires validated descriptors")
    if len({item.group.casefold() for item in ordered}) != len(ordered):
        raise IncrementalV2BuildError("Cache plan repeats a group")
    if len({item.cache_key for item in ordered}) != len(ordered):
        raise IncrementalV2BuildError("Cache plan repeats a cache key")

    resolved: dict[str, CachedAssetStreamGroup] = {}
    misses: list[GroupCacheInput] = []
    for descriptor in ordered:
        hit = loader(descriptor)
        if hit is None:
            misses.append(descriptor)
            continue
        resolved[descriptor.cache_key] = semantic_validator(descriptor, hit)

    if misses:
        rebuilt = tuple(rebuild_misses(tuple(misses)))
        if len(rebuilt) != len(misses):
            raise IncrementalV2BuildError("Miss builder returned the wrong group count")
        rebuilt_by_key: dict[str, CachedAssetStreamGroup] = {}
        for value in rebuilt:
            descriptor = getattr(value, "descriptor", None)
            if not isinstance(descriptor, GroupCacheInput):
                raise IncrementalV2BuildError("Miss builder returned an invalid object")
            if descriptor.cache_key in rebuilt_by_key:
                raise IncrementalV2BuildError("Miss builder repeated a cache object")
            rebuilt_by_key[descriptor.cache_key] = semantic_validator(descriptor, value)
        expected = {item.cache_key for item in misses}
        if set(rebuilt_by_key) != expected:
            raise IncrementalV2BuildError("Miss builder returned a different descriptor set")
        resolved.update(rebuilt_by_key)

    return ResolvedGroupCachePlan(
        objects=tuple(resolved[item.cache_key] for item in ordered),
        hit_count=len(ordered) - len(misses),
        rebuilt_count=len(misses),
    )


def _descriptor_documents(
    *,
    project_root: Path,
    fingerprints: Sequence[AtlasGroupFingerprint],
    editor_source: Path,
    unity_executable_sha256: str,
    texture_policy: TexturePolicy,
    quality_policy: QualityPolicy,
    foliage_groups: Sequence[str],
) -> tuple[GroupCacheInput, ...]:
    source_root = Path(unity_module.__file__).resolve(strict=True).parent.parent.parent
    if source_root != project_root.resolve(strict=True):
        raise IncrementalV2BuildError("Imported builder source is outside project_root")
    packer_source_sha = _sha_file(
        Path(unity_module.__file__).resolve(strict=True), "V2 packer source"
    )
    verifier_sha = _combined_source_sha(
        project_root,
        (
            Path(unity_module.__file__).resolve(strict=True)
            .relative_to(project_root.resolve(strict=True))
            .as_posix(),
            Path(quality_module.__file__).resolve(strict=True)
            .relative_to(project_root.resolve(strict=True))
            .as_posix(),
        ),
        "V2 quality verifier",
    )
    runtime_sha = _combined_source_sha(
        project_root, _RUNTIME_CAPABILITY_FILES, "AssetStream runtime capability"
    )
    editor_sha = _sha_file(editor_source, "Unity editor builder source")
    foliage = {str(item).casefold() for item in foliage_groups}
    descriptors: list[GroupCacheInput] = []
    for fingerprint in sorted(fingerprints, key=lambda item: item.spec.group):
        spec = fingerprint.spec
        single_page_required = (
            spec.material_binding == "group_mask_single_page_v1"
            or spec.group.casefold() in foliage
        )
        packer_settings = {
            "block_alignment_pixels": 4,
            "maximum_page_dimension": MAX_PAGE_DIMENSION,
            "maximum_pages_per_group": 16,
            "minimum_border_pixels": 1,
            "single_page_required": single_page_required,
        }
        encoder_settings = {
            "build_options": list(BUILD_OPTIONS),
            "encoder_id": BC7_ENCODER_ID,
            "main_format": texture_policy.main_format,
            "mask_format": texture_policy.mask_format,
            "quality": 100,
        }
        texture_settings = {
            "filter_mode": spec.filter_mode,
            "id": texture_policy.id,
            "main_format": texture_policy.main_format,
            "mask_filter_mode": "Point",
            "mask_format": texture_policy.mask_format,
        }
        document = {
            "editor": {"id": EDITOR_ID, "source_sha256": editor_sha},
            "encoder": {
                "id": BC7_ENCODER_ID,
                "settings_sha256": sha256(
                    _canonical(encoder_settings, final_lf=False)
                ).hexdigest(),
                "version": ENCODER_VERSION,
            },
            "frames": dict(fingerprint.frame_bindings),
            "group": {
                "contract_sha256": group_contract_sha256(
                    array_size=spec.array_size,
                    dash_format=spec.dash_format,
                    lifetime=spec.lifetime,
                    mask_policy=spec.mask_policy,
                    material_binding=spec.material_binding,
                    filter_mode=spec.filter_mode,
                ),
                "gm_id": spec.gm_id,
                "name": spec.group,
                "slug": fingerprint.slug,
            },
            "packer": {
                "id": BC7_PACKER_ID,
                "settings_sha256": sha256(
                    _canonical(packer_settings, final_lf=False)
                ).hexdigest(),
                "source_sha256": packer_source_sha,
                "version": PACKER_VERSION,
            },
            "quality_policy": {
                "id": quality_policy.id,
                "sha256": quality_policy.sha256,
                "verifier_id": quality_policy.verifier_id,
                "verifier_sha256": verifier_sha,
            },
            "runtime_capabilities": {
                "id": RUNTIME_CAPABILITIES_ID,
                "sha256": runtime_sha,
            },
            "schema": INPUT_SCHEMA,
            "texture_policy": {
                "id": texture_policy.id,
                "sha256": sha256(
                    _canonical(texture_settings, final_lf=False)
                ).hexdigest(),
            },
            "unity": {
                "build_target": BUILD_TARGET,
                "executable_sha256": unity_executable_sha256,
                "revision": UNITY_REVISION,
                "version": UNITY_VERSION,
            },
        }
        descriptors.append(parse_group_cache_input(document))
    return tuple(descriptors)


def build_group_cache_descriptors(
    *,
    project_root: Path,
    fingerprints: Sequence[AtlasGroupFingerprint],
    editor_source: Path,
    unity_executable_sha256: str,
    texture_policy: TexturePolicy,
    quality_policy: QualityPolicy,
    foliage_groups: Sequence[str],
) -> tuple[GroupCacheInput, ...]:
    """Build cache keys through the same descriptor factory as normal V2 builds."""

    return _descriptor_documents(
        project_root=project_root,
        fingerprints=fingerprints,
        editor_source=editor_source,
        unity_executable_sha256=unity_executable_sha256,
        texture_policy=texture_policy,
        quality_policy=quality_policy,
        foliage_groups=foliage_groups,
    )


def _load_canonical_object(path: Path, label: str) -> dict[str, object]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise IncrementalV2BuildError(f"Could not read {label}") from exc
    if not isinstance(value, dict) or raw != _canonical(value):
        raise IncrementalV2BuildError(f"{label} is not canonical JSON")
    return value


def _miss_quality_envelope(
    acceptance_envelope: Mapping[str, object] | None,
    fingerprints: Sequence[AtlasGroupFingerprint],
) -> Mapping[str, object] | None:
    """Restrict a frozen envelope to metrics emitted by one miss batch.

    A cache miss batch can contain only plain-shader groups even when the
    completed build also reuses masked groups from cache.  The Unity verifier
    deliberately emits ``mask_r``/``mask_g`` only when the current batch has a
    mask plane.  Applying the global mixed-group metric set to that plain-only
    batch therefore rejects valid evidence before the final, complete quality
    report can be composed.
    """

    if acceptance_envelope is None:
        return None
    has_mask_plane = any(
        frame.mask_rgba_sha256 is not None
        for fingerprint in fingerprints
        for frame in fingerprint.loaded_frames
    )
    if has_mask_plane:
        return acceptance_envelope
    return {
        name: acceptance_envelope[name]
        for name in sorted(acceptance_envelope)
        if name not in {"mask_g", "mask_r"}
    }


def _build_and_publish_misses(
    *,
    workspace_root: Path,
    batch_workspace: Path,
    fingerprints_by_group: Mapping[str, AtlasGroupFingerprint],
    descriptors: tuple[GroupCacheInput, ...],
    editor_source: Path,
    editor_executable: Path,
    texture_policy: TexturePolicy,
    quality_policy: QualityPolicy,
    acceptance_envelope: Mapping[str, object] | None,
    foliage_groups: Sequence[str],
    preflight_factory: Callable[..., AtlasGroupPreflight],
    prepare_factory: Callable[..., PreparedUnityProject],
    build_runner: Callable[..., Any],
) -> tuple[CachedAssetStreamGroup, ...]:
    misses = tuple(fingerprints_by_group[item.group] for item in descriptors)
    preflight = preflight_factory(misses, foliage_groups=foliage_groups)
    miss_envelope = _miss_quality_envelope(acceptance_envelope, misses)
    batch_workspace.mkdir(parents=True, exist_ok=False)
    prepared = prepare_factory(
        batch_workspace,
        preflight,
        editor_source=editor_source,
        texture_policy_id=texture_policy.id,
        quality_policy_id=quality_policy.id,
        quality_policy_sha256=quality_policy.sha256,
        quality_mode=quality_policy.state,
        acceptance_envelope=miss_envelope,
    )
    build_runner(
        prepared,
        editor_executable,
        timeout_seconds=BC7_UNITY_TIMEOUT_SECONDS,
    )
    index = _load_canonical_object(prepared.index_path, "miss-batch index")
    raw_groups = index.get("groups")
    if not isinstance(raw_groups, list):
        raise IncrementalV2BuildError("Miss-batch index has no groups")
    group_records = {
        str(item.get("group")): item for item in raw_groups if isinstance(item, dict)
    }
    if set(group_records) != {item.group for item in descriptors}:
        raise IncrementalV2BuildError("Miss-batch index group set drifted")
    published: list[CachedAssetStreamGroup] = []
    for descriptor in descriptors:
        slug = descriptor.slug
        bundle_name = f"sede.gm.{slug}.bc7.v2"
        published.append(
            publish_group_cache_object(
                workspace_root=workspace_root,
                descriptor=descriptor,
                bundle_path=prepared.output_path / bundle_name,
                atlas_path=(
                    prepared.project_path
                    / "Assets"
                    / "Generated"
                    / "Groups"
                    / slug
                    / BC7_ATLAS_ASSET_FILENAME
                ),
                index_group_record=group_records[descriptor.group],
                quality_frames_path=group_quality_frames_path(
                    prepared, descriptor.group
                ),
            )
        )
    return tuple(published)


def _write_exclusive(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise IncrementalV2BuildError(f"Refusing to overwrite assembled file: {path}") from exc


def _copy_exclusive(source: Path, target: Path, expected_sha256: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with source.open("rb") as incoming, target.open("xb") as outgoing:
            shutil.copyfileobj(incoming, outgoing, length=8 * 1024 * 1024)
            outgoing.flush()
            os.fsync(outgoing.fileno())
    except (OSError, FileExistsError) as exc:
        raise IncrementalV2BuildError(f"Could not materialize cached artifact: {target}") from exc
    if _sha_file(target, "assembled cached artifact") != expected_sha256:
        raise IncrementalV2BuildError("Assembled cached artifact differs from cache")


def _texture_contract_id(plane: str, texture_format: str, filter_mode: str) -> str:
    if plane not in {"main", "mask"} or filter_mode not in {"Point", "Bilinear"}:
        raise IncrementalV2BuildError("Invalid cached texture-contract identity")
    return f"{plane}-{texture_format.lower()}-{filter_mode.lower()}-v1"


def _compose_global_build(
    *,
    assembly_parent: Path,
    objects: Sequence[CachedAssetStreamGroup],
    texture_policy: TexturePolicy,
    quality_policy: QualityPolicy,
    acceptance_envelope: Mapping[str, object] | None,
) -> PreparedUnityProject:
    ordered = tuple(sorted(objects, key=lambda item: item.descriptor.group))
    if not ordered:
        raise IncrementalV2BuildError("Cannot compose an empty V2 build")
    identity_docs = [item.descriptor.as_dict() for item in ordered]
    editor_shas = {str(doc["editor"]["source_sha256"]) for doc in identity_docs}
    if len(editor_shas) != 1:
        raise IncrementalV2BuildError("Cached editor identities differ")
    common_identity = {
        _canonical(
            {
                "editor": document["editor"],
                "encoder": document["encoder"],
                "packer_source_sha256": document["packer"]["source_sha256"],
                "packer_version": document["packer"]["version"],
                "quality_verifier_sha256": document["quality_policy"][
                    "verifier_sha256"
                ],
                "runtime_capabilities": document["runtime_capabilities"],
                "unity": document["unity"],
            },
            final_lf=False,
        )
        for document in identity_docs
    }
    if len(common_identity) != 1:
        raise IncrementalV2BuildError("Cached common tool identities differ")
    for document in identity_docs:
        unity = document["unity"]
        packer = document["packer"]
        encoder = document["encoder"]
        cached_texture_policy = document["texture_policy"]
        cached_quality_policy = document["quality_policy"]
        if (
            unity["version"] != UNITY_VERSION
            or unity["revision"] != UNITY_REVISION
            or unity["build_target"] != BUILD_TARGET
            or packer["id"] != BC7_PACKER_ID
            or encoder["id"] != BC7_ENCODER_ID
            or cached_texture_policy["id"] != texture_policy.id
            or cached_quality_policy["id"] != quality_policy.id
            or cached_quality_policy["sha256"] != quality_policy.sha256
            or cached_quality_policy["verifier_id"] != quality_policy.verifier_id
        ):
            raise IncrementalV2BuildError("Cached tool/policy identity differs")
    seed = {
        "composition_source_sha256": _sha_file(
            Path(__file__).resolve(strict=True), "incremental composition source"
        ),
        "groups": [
            {
                "cache_key": item.descriptor.cache_key,
                "manifest_sha256": item.manifest_sha256,
            }
            for item in ordered
        ],
        "quality_policy": {
            "id": quality_policy.id,
            "sha256": quality_policy.sha256,
            "state": quality_policy.state,
            "verifier_id": quality_policy.verifier_id,
        },
        "schema": INCREMENTAL_COMPOSITION_SCHEMA,
        "texture_policy": {
            "id": texture_policy.id,
            "main_format": texture_policy.main_format,
            "mask_format": texture_policy.mask_format,
        },
        "unity": {"revision": UNITY_REVISION, "version": UNITY_VERSION},
    }
    build_id = sha256(_canonical(seed, final_lf=False)).hexdigest()
    build_root = assembly_parent / f"assembled-{build_id[:16]}"
    try:
        build_root.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise IncrementalV2BuildError(
            f"Assembled V2 build already exists: {build_root}"
        ) from exc
    project = build_root / "project"
    output_root = build_root / "output"
    bundle_root = output_root / "Runtime" / "AssetBundles" / "win64"
    index_path = output_root / "Runtime" / "AssetBundles" / "index.json"
    quality_path = output_root / "bc7-quality-report.v1.json"
    report_path = output_root / "build-report.json"
    template_path = project / "Assets" / "Generated" / "index.v2.template.json"
    build_input_path = project / "Assets" / "Generated" / "build-input.v2.json"

    final_groups: list[dict[str, object]] = []
    template_groups: list[dict[str, object]] = []
    texture_contracts: dict[str, dict[str, object]] = {}
    texture_inputs: list[dict[str, object]] = []
    bundle_inputs: list[dict[str, object]] = []
    report_textures: list[dict[str, object]] = []
    report_bundles: list[dict[str, object]] = []
    atlas_documents: dict[str, bytes] = {}
    quality_frames: list[FrameQualityEvidence] = []

    for item in ordered:
        record = _detached_mapping(item.index_group_record)
        final_groups.append(record)
        template_groups.append(
            {key: value for key, value in record.items() if key not in _FINAL_GROUP_KEYS}
        )
        bundle_name = str(record["bundle"])
        bundle_sha = str(record["bundle_sha256"])
        _copy_exclusive(item.bundle_path, bundle_root / bundle_name, bundle_sha)
        report_bundles.append(
            {
                "manifest_hash": item.unity_hash128,
                "mod_relative_path": record["bundle_path"],
                "name": bundle_name,
                "sha256": bundle_sha,
                "size_bytes": record["bundle_size_bytes"],
            }
        )

        atlas_asset_path = str(record["atlas_asset_path"])
        atlas_target = project.joinpath(*atlas_asset_path.split("/"))
        atlas_raw = item.atlas_path.read_bytes()
        if sha256(atlas_raw).hexdigest() != record["atlas_sha256"]:
            raise IncrementalV2BuildError("Cached atlas changed after validation")
        _write_exclusive(atlas_target, atlas_raw)
        atlas_documents[atlas_asset_path] = atlas_raw
        atlas = item.atlas
        assets: list[dict[str, str]] = []
        for plane, contract in (
            ("main", atlas.main_texture_contract),
            ("mask", atlas.mask_texture_contract),
        ):
            if contract is None:
                continue
            contract_id = _texture_contract_id(
                plane, contract.format, contract.filter_mode
            )
            contract_document = asdict(contract)
            prior = texture_contracts.setdefault(contract_id, contract_document)
            if prior != contract_document:
                raise IncrementalV2BuildError("Cached texture-contract id collision")
        for page in atlas.pages:
            planes = (("main", page.main), ("mask", page.mask))
            for plane, texture in planes:
                if texture is None:
                    continue
                contract = (
                    atlas.main_texture_contract
                    if plane == "main"
                    else atlas.mask_texture_contract
                )
                assert contract is not None
                contract_id = _texture_contract_id(
                    plane, texture.format, contract.filter_mode
                )
                texture_input = {
                    "asset_path": texture.asset_path,
                    "gpu_bytes": texture.gpu_bytes,
                    "height": page.height,
                    "plane": plane,
                    "source_png_sha256": texture.source_png_sha256,
                    "source_rgba_bytes": texture.source_rgba_bytes,
                    "source_rgba_sha256": texture.source_rgba_sha256,
                    "texture_contract_id": contract_id,
                    "width": page.width,
                }
                texture_inputs.append(texture_input)
                report_texture = dict(texture_input)
                report_texture["texture_contract"] = report_texture.pop(
                    "texture_contract_id"
                )
                report_textures.append(report_texture)
                assets.append(
                    {"address": texture.address, "asset_path": texture.asset_path}
                )
        assets.append(
            {"address": str(record["atlas_address"]), "asset_path": atlas_asset_path}
        )
        bundle_inputs.append(
            {"assets": sorted(assets, key=lambda row: row["address"]), "name": bundle_name}
        )
        quality_frames.extend(item.quality_frames)

    final_groups.sort(key=lambda item: str(item["group"]))
    template_groups.sort(key=lambda item: str(item["group"]))
    texture_inputs.sort(key=lambda item: str(item["asset_path"]))
    report_textures.sort(key=lambda item: str(item["asset_path"]))
    bundle_inputs.sort(key=lambda item: str(item["name"]))
    report_bundles.sort(key=lambda item: str(item["name"]))
    quality_policy_document = {
        "id": quality_policy.id,
        "sha256": quality_policy.sha256,
        "state": quality_policy.state,
        "verifier_id": quality_policy.verifier_id,
    }
    texture_policy_document = {
        "id": texture_policy.id,
        "main_format": texture_policy.main_format,
        "mask_format": texture_policy.mask_format,
    }
    template = {
        "backend_kind": BC7_ATLAS_BACKEND_KIND,
        "build_id": build_id,
        "build_target": BUILD_TARGET,
        "encoder_id": BC7_ENCODER_ID,
        "groups": template_groups,
        "max_page_dimension": MAX_PAGE_DIMENSION,
        "packer_id": BC7_PACKER_ID,
        "quality_policy": quality_policy_document,
        "quality_report_sha256": None,
        "schema": BC7_INDEX_TEMPLATE_SCHEMA,
        "texture_policy": texture_policy_document,
        "total_gpu_bytes": sum(int(row["gpu_bytes"]) for row in final_groups),
        "total_resident_charge_bytes": sum(
            int(row["resident_charge_bytes"]) for row in final_groups
        ),
        "total_source_rgba_bytes": sum(
            int(row["source_rgba_bytes"]) for row in final_groups
        ),
        "unity": {"revision": UNITY_REVISION, "version": UNITY_VERSION},
        "vanilla_omitted_groups": [],
    }
    _write_exclusive(template_path, _canonical(template))
    build_input = {
        "backend_kind": BC7_ATLAS_BACKEND_KIND,
        "build_id": build_id,
        "build_options": list(BUILD_OPTIONS),
        "build_target": BUILD_TARGET,
        "bundles": bundle_inputs,
        "editor_script_sha256": next(iter(editor_shas)),
        "editor_texture_compression_override": "NoOverride",
        "encoder_id": BC7_ENCODER_ID,
        "index_output_relative_path": "../output/Runtime/AssetBundles/index.json",
        "index_template_asset_path": "Assets/Generated/index.v2.template.json",
        "max_page_dimension": MAX_PAGE_DIMENSION,
        "output_relative_path": "../output/Runtime/AssetBundles/win64",
        "packer_id": BC7_PACKER_ID,
        "quality_policy": quality_policy_document,
        "quality_report_output_relative_path": "../output/bc7-quality-report.v1.json",
        "schema": BC7_BUILD_INPUT_SCHEMA,
        "texture_contracts": [
            {"id": key, "texture_contract": texture_contracts[key]}
            for key in sorted(texture_contracts)
        ],
        "texture_policy": texture_policy_document,
        "textures": texture_inputs,
        "unity": {"revision": UNITY_REVISION, "version": UNITY_VERSION},
    }
    build_input_payload = _canonical(build_input)
    _write_exclusive(build_input_path, build_input_payload)
    try:
        parsed_input = parse_asset_bundle_build_input_v2(build_input_payload)
    except AssetStreamContractError as exc:
        raise IncrementalV2BuildError(f"Global build input is invalid: {exc}") from exc

    report_mode = (
        QUALITY_MEASUREMENT_MODE
        if quality_policy.state == "measurement_nonpromotable"
        else QUALITY_ACCEPTANCE_MODE
    )
    quality_payload, quality_document = build_quality_report(
        build_id=build_id,
        backend=BC7_ATLAS_BACKEND_KIND,
        encoder_id=BC7_ENCODER_ID,
        texture_policy_id=texture_policy.id,
        bundles=[
            {
                "name": row["name"],
                "sha256": row["sha256"],
                "size_bytes": row["size_bytes"],
            }
            for row in report_bundles
        ],
        frames=quality_frames,
        mode=report_mode,
        quality_policy_id=quality_policy.id,
        quality_policy_sha256=quality_policy.sha256,
        acceptance_envelope=acceptance_envelope,
    )
    if quality_policy.state == "frozen" and (
        quality_document.get("accepted") is not True
        or quality_document.get("promotable") is not True
    ):
        raise IncrementalV2BuildError("Cached evidence exceeds the frozen envelope")
    quality_sha = write_quality_report(quality_path, quality_payload)
    write_observed_quality_envelope(
        output_root / "quality-envelope-observed.v1.json",
        build_id=build_id,
        quality_report_sha256=quality_sha,
        frames=quality_frames,
    )

    final_index = dict(template)
    final_index["groups"] = final_groups
    final_index["quality_report_sha256"] = quality_sha
    final_index["schema"] = BC7_INDEX_SCHEMA
    index_payload = _canonical(final_index)
    _write_exclusive(index_path, index_payload)
    index_sha = sha256(index_payload).hexdigest()
    report = {
        "build_id": build_id,
        "build_input_sha256": parsed_input.file_sha256,
        "build_options": list(BUILD_OPTIONS),
        "build_target": BUILD_TARGET,
        "bundles": report_bundles,
        "error": "",
        "index_sha256": index_sha,
        "quality_report_sha256": quality_sha,
        "schema": BC7_BUILD_REPORT_SCHEMA,
        "success": True,
        "textures": report_textures,
        "unity": {"revision": UNITY_REVISION, "version": UNITY_VERSION},
        "verified": True,
    }
    report_payload = _canonical(report)
    _write_exclusive(report_path, report_payload)

    expected_groups = tuple(item.descriptor.group for item in ordered)
    try:
        parsed_index = parse_asset_bundle_index_v2(
            index_payload,
            atlas_documents=atlas_documents,
            expected_groups=expected_groups,
        )
        parsed_report = parse_asset_bundle_build_report_v2(
            report_payload, build_input=parsed_input
        )
    except AssetStreamContractError as exc:
        raise IncrementalV2BuildError(f"Global composition is invalid: {exc}") from exc
    if (
        parsed_report.index_sha256 != parsed_index.file_sha256
        or parsed_report.quality_report_sha256 != parsed_index.quality_report_sha256
    ):
        raise IncrementalV2BuildError("Global report/index binding drifted")

    return PreparedUnityProject(
        workspace_root=assembly_parent.resolve(strict=True),
        build_root=build_root,
        project_path=project,
        index_template_path=template_path,
        index_path=index_path,
        build_input_path=build_input_path,
        output_path=bundle_root,
        report_path=report_path,
        log_path=output_root / "incremental-composition.log",
        build_id=build_id,
        group_count=len(ordered),
        omitted_group_count=0,
        page_count=sum(len(item.atlas.pages) for item in ordered),
        pipeline_version=2,
        unity_report_path=None,
        quality_report_path=quality_path,
        quality_policy_id=quality_policy.id,
        quality_policy_sha256=quality_policy.sha256,
        quality_mode=quality_policy.state,
        texture_policy_id=texture_policy.id,
        quality_acceptance_envelope=acceptance_envelope,
    )


def build_incremental_v2_asset_stream(
    *,
    project_root: Path,
    unity_work_root: Path,
    groups: Sequence[AtlasGroupInput],
    editor_source: Path,
    editor_executable: Path,
    unity_executable_sha256: str,
    texture_policy: TexturePolicy,
    quality_policy: QualityPolicy,
    acceptance_envelope: Mapping[str, object] | None,
    foliage_groups: Sequence[str] = (),
    fingerprint_factory: Callable[
        [Sequence[AtlasGroupInput]], tuple[AtlasGroupFingerprint, ...]
    ] = fingerprint_atlas_groups_v2,
    preflight_factory: Callable[..., AtlasGroupPreflight] = preflight_atlas_fingerprints_v2,
    prepare_factory: Callable[..., PreparedUnityProject] = prepare_unity_asset_bundle_project_v2,
    build_runner: Callable[..., Any] = run_headless_build,
) -> IncrementalV2BuildResult:
    """Build/reuse every selected V2 GM group and compose one exact result."""

    if not isinstance(texture_policy, TexturePolicy) or not isinstance(
        quality_policy, QualityPolicy
    ):
        raise IncrementalV2BuildError("Incremental V2 policies are not parsed contracts")
    if quality_policy.verifier_id != BC7_VERIFIER_ID:
        raise IncrementalV2BuildError("Incremental V2 verifier identity drifted")
    root = project_root.resolve(strict=True)
    work_root = unity_work_root.resolve(strict=True)
    if root not in work_root.parents:
        raise IncrementalV2BuildError("Incremental work root is outside project_root")
    fingerprints = fingerprint_factory(groups)
    descriptors = build_group_cache_descriptors(
        project_root=root,
        fingerprints=fingerprints,
        editor_source=editor_source,
        unity_executable_sha256=unity_executable_sha256,
        texture_policy=texture_policy,
        quality_policy=quality_policy,
        foliage_groups=foliage_groups,
    )
    fingerprints_by_group = {item.spec.group: item for item in fingerprints}

    def loader(descriptor: GroupCacheInput) -> CachedAssetStreamGroup | None:
        return load_group_cache_object(workspace_root=root, descriptor=descriptor)

    def rebuild(
        misses: tuple[GroupCacheInput, ...]
    ) -> tuple[CachedAssetStreamGroup, ...]:
        return _build_and_publish_misses(
            workspace_root=root,
            batch_workspace=work_root / "miss-batch",
            fingerprints_by_group=fingerprints_by_group,
            descriptors=misses,
            editor_source=editor_source,
            editor_executable=editor_executable,
            texture_policy=texture_policy,
            quality_policy=quality_policy,
            acceptance_envelope=acceptance_envelope,
            foliage_groups=foliage_groups,
            preflight_factory=preflight_factory,
            prepare_factory=prepare_factory,
            build_runner=build_runner,
        )

    plan = resolve_group_cache_plan(
        descriptors, loader=loader, rebuild_misses=rebuild
    )
    prepared = _compose_global_build(
        assembly_parent=work_root,
        objects=plan.objects,
        texture_policy=texture_policy,
        quality_policy=quality_policy,
        acceptance_envelope=acceptance_envelope,
    )
    return IncrementalV2BuildResult(
        prepared=prepared,
        descriptors=descriptors,
        objects=plan.objects,
        hit_count=plan.hit_count,
        rebuilt_count=plan.rebuilt_count,
        unity_batch_count=1 if plan.rebuilt_count else 0,
    )


__all__ = [
    "INCREMENTAL_COMPOSITION_SCHEMA",
    "IncrementalV2BuildError",
    "IncrementalV2BuildResult",
    "ResolvedGroupCachePlan",
    "build_group_cache_descriptors",
    "build_incremental_v2_asset_stream",
    "resolve_group_cache_plan",
]

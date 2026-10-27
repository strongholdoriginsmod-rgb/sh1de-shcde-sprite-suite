from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import asdict, dataclass, fields, replace
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tempfile
from typing import Any

from .asset_stream_builder import AssetStreamBuildError, _resolve_toolchain
from .asset_stream_contract import (
    ASSET_BUNDLE_CATEGORY,
    ASSET_BUNDLE_INDEX_CATEGORY,
    BC7_ATLAS_BACKEND_KIND,
    AssetStreamContractError,
    AtlasBackend,
    parse_atlas_backend,
)
from .builds import BuildMatch
from .config import BuilderConfig
from .mod_builder import (
    ModBuildError,
    OutputRecord,
    _build_logo,
    _build_texture_overrides,
    _copy_authored_backgrounds,
    _copy_authored_ui_atlases,
    _integrate_ui_texture_build,
    _is_link_or_junction,
    _prepare_authored_backgrounds,
    _prepare_authored_ui_atlases,
    _prepare_mod_root,
    _record,
    _safe_output,
    _validate_manifest_owned_output,
    _validate_output_records_unique,
    load_profile,
    sha256_file,
)
from .profile_contract import profile_output_contract_checks
from .runtime_build import (
    RuntimeArtifact,
    RuntimeBuildError,
    build_runtime_artifacts,
    parse_ui_texture_runtime_manifest_v2,
)
from .ui_asset_bundle import (
    UI_BACKEND_KIND,
    UiAssetBundleError,
    UiTextureBackendSelection,
    UiTextureBuildResult,
    UiTextureSourceManifest,
    build_ui_texture_backend,
    load_ui_texture_backend_selection,
    load_ui_texture_source_manifest,
)


_MANIFEST_KEYS = frozenset(
    {
        "schema_version",
        "profile_id",
        "profile_description",
        "source_build_id",
        "target_build_id",
        "mod_info",
        "outputs",
    }
)
_OUTPUT_RECORD_KEYS = frozenset(field.name for field in fields(OutputRecord))
_UI_V1_MANIFEST = "Runtime/ui-textures-v1.tsv"
_UI_V2_MANIFEST = "Runtime/ui-textures-v2.tsv"
_UI_BUNDLE_PREFIX = "Runtime/UiAssetBundles/win64/"
_RUNTIME_REBUILT_PATHS = frozenset(
    {
        "Runtime/audio-profile.tsv",
        "Runtime/unit-roster.tsv",
        "StrongholdEuropeDE.Runtime.dll",
    }
)
_RUNTIME_REBUILT_CATEGORIES = frozenset(
    {
        "runtime_companion",
        "runtime_contract",
        "runtime_roster_contract",
        "runtime_pcm_stream_contract",
        "europe_music_pcm_stream",
        "europe_music",
        "runtime_ui_texture_contract",
    }
)
_FRONTEND_LIST_KEYS = (
    "texture_overrides",
    "authored_backgrounds",
    "authored_ui_atlases",
)


class UiCandidateComposeError(RuntimeError):
    """Raised before a staged UI-only candidate can be promoted."""


@dataclass(frozen=True)
class ValidatedBaseCandidate:
    root: Path
    manifest_sha256: str
    manifest: Mapping[str, object]
    records: tuple[OutputRecord, ...]
    ui_mode: str
    ui_profile_paths: frozenset[str]
    reusable_profile_sources: bool


@dataclass(frozen=True)
class UiCandidateComposeResult:
    output_root: Path
    prior_manifest_sha256: str
    manifest_sha256: str
    ui_manifest_sha256: str
    ui_cache_hit_count: int
    ui_cache_miss_count: int
    cloned_hardlink_count: int
    cloned_copy_count: int


def _reject_duplicate_json_pairs(
    pairs: Sequence[tuple[str, object]],
) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise UiCandidateComposeError(
                f"Base build manifest repeats JSON key {key!r}"
            )
        value[key] = item
    return value


def _load_canonical_manifest(path: Path) -> dict[str, object]:
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise UiCandidateComposeError(
            f"Cannot read base build manifest: {path}"
        ) from exc
    if (
        not payload
        or payload.startswith(b"\xef\xbb\xbf")
        or not payload.endswith(b"\n")
        or payload.endswith(b"\n\n")
        or b"\r" in payload
    ):
        raise UiCandidateComposeError(
            "Base build manifest is not BOM-free canonical UTF-8/LF"
        )
    try:
        value = json.loads(
            payload.decode("utf-8", errors="strict"),
            object_pairs_hook=_reject_duplicate_json_pairs,
            parse_constant=lambda token: (_ for _ in ()).throw(
                UiCandidateComposeError(
                    f"Base build manifest contains non-finite number {token!r}"
                )
            ),
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise UiCandidateComposeError(
            "Base build manifest is not strict JSON"
        ) from exc
    if not isinstance(value, dict) or set(value) != _MANIFEST_KEYS:
        raise UiCandidateComposeError("Base build manifest root fields changed")
    expected = (
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    ).encode("utf-8")
    if payload != expected:
        raise UiCandidateComposeError("Base build manifest is not canonical")
    return value


def _record_from_manifest(raw: object, ordinal: int) -> OutputRecord:
    if not isinstance(raw, dict) or set(raw) != _OUTPUT_RECORD_KEYS:
        raise UiCandidateComposeError(
            f"Base output record {ordinal} fields changed"
        )
    metadata = raw.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        raise UiCandidateComposeError(
            f"Base output record {ordinal} metadata is not an object/null"
        )
    try:
        return OutputRecord(**deepcopy(raw))
    except TypeError as exc:
        raise UiCandidateComposeError(
            f"Base output record {ordinal} cannot be decoded"
        ) from exc


def _frontend_profile_paths(profile: Mapping[str, object]) -> frozenset[str]:
    paths: list[str] = []
    for key in _FRONTEND_LIST_KEYS:
        values = profile.get(key, [])
        if not isinstance(values, list):
            raise UiCandidateComposeError(f"Profile {key!r} is not a list")
        for ordinal, raw in enumerate(values):
            if not isinstance(raw, dict) or not isinstance(raw.get("output"), str):
                raise UiCandidateComposeError(
                    f"Profile {key}[{ordinal}] has no output path"
                )
            paths.append(raw["output"])
    logo = profile.get("mod_logo")
    if logo is not None:
        if not isinstance(logo, dict) or not isinstance(logo.get("output"), str):
            raise UiCandidateComposeError("Profile mod_logo has no output path")
        paths.append(logo["output"])
    if len(paths) != len({path.casefold() for path in paths}):
        raise UiCandidateComposeError("Frontend profile outputs collide on Windows")
    return frozenset(paths)


def _sanitized_base_profile(
    profile: Mapping[str, object],
    ui_paths: frozenset[str],
) -> dict[str, object]:
    sanitized = deepcopy(dict(profile))
    sanitized.pop("ui_texture_backend", None)
    for key in _FRONTEND_LIST_KEYS:
        sanitized[key] = [
            item
            for item in sanitized.get(key, [])
            if item.get("output") not in ui_paths
        ]
    logo = sanitized.get("mod_logo")
    if isinstance(logo, dict) and logo.get("output") in ui_paths:
        sanitized.pop("mod_logo")
    return sanitized


def _sanitized_base_records(
    records: Sequence[OutputRecord],
    ui_paths: frozenset[str],
) -> dict[str, dict[str, object]]:
    declared = {
        record.relative_path: asdict(record)
        for record in records
        if record.relative_path not in ui_paths
        and record.relative_path not in {_UI_V1_MANIFEST, _UI_V2_MANIFEST}
        and not record.relative_path.startswith(_UI_BUNDLE_PREFIX)
    }
    runtime = declared.get("StrongholdEuropeDE.Runtime.dll")
    if runtime is not None:
        metadata = runtime.get("metadata")
        if not isinstance(metadata, dict):
            raise UiCandidateComposeError(
                "Base runtime DLL record has no metadata object"
            )
        metadata["ui_texture_streaming_enabled"] = False
        metadata["ui_texture_manifest_sha256"] = ""
    return declared


def _parse_legacy_ui_v1(
    root: Path,
    records_by_path: Mapping[str, OutputRecord],
    ui_paths: frozenset[str],
) -> str:
    manifest_record = records_by_path.get(_UI_V1_MANIFEST)
    if manifest_record is None:
        raise UiCandidateComposeError("Legacy UI v1 record is missing")
    path = root / "Runtime" / "ui-textures-v1.tsv"
    payload = path.read_bytes()
    if (
        payload.startswith(b"\xef\xbb\xbf")
        or not payload.endswith(b"\n")
        or payload.endswith(b"\n\n")
        or b"\r" in payload
    ):
        raise UiCandidateComposeError("Legacy UI v1 manifest byte envelope changed")
    try:
        lines = payload[:-1].decode("utf-8", errors="strict").split("\n")
    except UnicodeError as exc:
        raise UiCandidateComposeError("Legacy UI v1 manifest is not UTF-8") from exc
    if (
        len(lines) != 4 + len(ui_paths)
        or lines[0] != "stronghold-europe-ui-textures\t1"
        or lines[1] != f"entry_count\t{len(ui_paths)}"
        or lines[3]
        != (
            "texture\tnoesis_path\tplugin_relative_path\tsha256"
            "\tencoded_bytes\twidth\theight\ttransient_peak_bytes"
        )
    ):
        raise UiCandidateComposeError("Legacy UI v1 manifest shape changed")
    try:
        declared_rgba = int(lines[2].removeprefix("declared_rgba_bytes\t"))
    except ValueError as exc:
        raise UiCandidateComposeError(
            "Legacy UI v1 declared RGBA value changed"
        ) from exc
    seen: set[str] = set()
    actual_rgba = 0
    transient_values: list[int] = []
    prior_noesis: str | None = None
    for ordinal, line in enumerate(lines[4:]):
        fields = line.split("\t")
        if len(fields) != 8 or fields[0] != "texture":
            raise UiCandidateComposeError(
                f"Legacy UI v1 row {ordinal} shape changed"
            )
        noesis, relative, digest, size_text, width_text, height_text, peak_text = (
            fields[1:]
        )
        if (
            relative not in ui_paths
            or noesis != relative.removeprefix("Override/")
            or (prior_noesis is not None and prior_noesis >= noesis)
            or relative in seen
        ):
            raise UiCandidateComposeError(
                f"Legacy UI v1 row {ordinal} identity changed"
            )
        record = records_by_path.get(relative)
        try:
            size = int(size_text)
            width = int(width_text)
            height = int(height_text)
            peak = int(peak_text)
        except ValueError as exc:
            raise UiCandidateComposeError(
                f"Legacy UI v1 row {ordinal} numbers changed"
            ) from exc
        if (
            record is None
            or digest != record.sha256
            or size != record.size
            or width != record.width
            or height != record.height
            or width <= 0
            or height <= 0
            or peak <= 0
        ):
            raise UiCandidateComposeError(
                f"Legacy UI v1 row {ordinal} disagrees with its PNG record"
            )
        seen.add(relative)
        prior_noesis = noesis
        actual_rgba += width * height * 4
        transient_values.append(peak)
    metadata = manifest_record.metadata
    manifest_sha = hashlib.sha256(payload).hexdigest()
    if (
        seen != set(ui_paths)
        or declared_rgba != actual_rgba
        or manifest_record.category != "runtime_ui_texture_contract"
        or manifest_record.source_reference
        != "generated:Override/Assets/GUI/**/*.png"
        or manifest_record.size != len(payload)
        or manifest_record.sha256 != manifest_sha
        or metadata
        != {
            "kind": "stronghold_europe_ui_textures_v1",
            "manifest_sha256": manifest_sha,
            "entry_count": len(ui_paths),
            "declared_rgba_bytes": declared_rgba,
            "max_transient_peak_bytes": max(transient_values),
        }
    ):
        raise UiCandidateComposeError(
            "Legacy UI v1 record/declared totals changed"
        )
    return manifest_sha


def _parse_existing_ui_v2(
    root: Path,
    records_by_path: Mapping[str, OutputRecord],
    selection: UiTextureBackendSelection,
) -> str:
    manifest_record = records_by_path.get(_UI_V2_MANIFEST)
    if manifest_record is None or not isinstance(manifest_record.metadata, dict):
        raise UiCandidateComposeError("Existing UI v2 manifest record is missing")
    metadata = manifest_record.metadata
    required_metadata = {
        "kind",
        "manifest_sha256",
        "entry_count",
        "bundle_count",
        "declared_gpu_bytes",
        "declared_resident_charge_bytes",
        "source_manifest_sha256",
        "source_entry_set_sha256",
        "quality_policy_sha256",
        "editor_source_sha256",
    }
    if set(metadata) != required_metadata:
        raise UiCandidateComposeError("Existing UI v2 metadata fields changed")
    try:
        base_selection = replace(
            selection,
            source_manifest_sha256=str(metadata["source_manifest_sha256"]),
            quality_policy_sha256=str(metadata["quality_policy_sha256"]),
            editor_source_sha256=str(metadata["editor_source_sha256"]),
            expected_entry_count=int(metadata["entry_count"]),
        )
        parsed = parse_ui_texture_runtime_manifest_v2(
            root,
            expected_source_manifest_sha256=base_selection.source_manifest_sha256,
            expected_quality_policy_sha256=base_selection.quality_policy_sha256,
            expected_editor_source_sha256=base_selection.editor_source_sha256,
            expected_entry_count=base_selection.expected_entry_count,
            max_resident_bytes=8 * 1024 * 1024 * 1024,
        )
    except (OSError, RuntimeBuildError, TypeError, ValueError) as exc:
        raise UiCandidateComposeError(
            "Existing UI v2 payload failed its self-contained contract"
        ) from exc
    expected_metadata = {
        "kind": "stronghold_europe_ui_textures_v2",
        "manifest_sha256": parsed.sha256,
        "entry_count": parsed.entry_count,
        "bundle_count": len(parsed.bundles),
        "declared_gpu_bytes": parsed.declared_gpu_bytes,
        "declared_resident_charge_bytes": parsed.declared_resident_charge_bytes,
        "source_manifest_sha256": parsed.source_manifest_sha256,
        "source_entry_set_sha256": parsed.source_entry_set_sha256,
        "quality_policy_sha256": parsed.quality_policy_sha256,
        "editor_source_sha256": parsed.editor_source_sha256,
    }
    if (
        manifest_record.category != "runtime_ui_texture_contract"
        or manifest_record.source_reference
        != "generated:config/ui-textures-bc7-v1.json"
        or manifest_record.size != parsed.size_bytes
        or manifest_record.sha256 != parsed.sha256
        or metadata != expected_metadata
    ):
        raise UiCandidateComposeError("Existing UI v2 manifest record changed")
    expected_bundle_paths = {bundle.relative_path for bundle in parsed.bundles}
    actual_bundle_paths = {
        relative
        for relative in records_by_path
        if relative.startswith(_UI_BUNDLE_PREFIX)
    }
    if actual_bundle_paths != expected_bundle_paths:
        raise UiCandidateComposeError("Existing UI v2 bundle record set changed")
    for bundle in parsed.bundles:
        record = records_by_path[bundle.relative_path]
        name = PurePosixPath(bundle.relative_path).name
        if (
            record.category != "ui_texture_asset_bundle"
            or record.source_reference
            != f"unity-ui-assetbundle:{bundle.entry_id}:{name}"
            or record.size != bundle.size_bytes
            or record.sha256 != bundle.sha256
            or record.metadata
            != {
                "kind": UI_BACKEND_KIND,
                "entry_id": bundle.entry_id,
                "bundle": name,
                "unity_hash128": bundle.unity_hash128,
                "crc32": bundle.crc32,
            }
        ):
            raise UiCandidateComposeError(
                f"Existing UI v2 bundle record changed: {bundle.entry_id}"
            )
    return parsed.sha256


def validate_base_candidate(
    root: Path,
    profile: Mapping[str, object],
    build_match: BuildMatch,
    selection: UiTextureBackendSelection,
    source_manifest: UiTextureSourceManifest,
    atlas_backend: AtlasBackend,
    *,
    owned_manifest_sha256: str | None = None,
) -> ValidatedBaseCandidate:
    """Validate the immutable full-build base while isolating only its UI lane."""

    base = Path(root).resolve(strict=True)
    profile_id = profile.get("id")
    if not isinstance(profile_id, str):
        raise UiCandidateComposeError("Compose profile has no string id")
    if atlas_backend.kind != BC7_ATLAS_BACKEND_KIND:
        raise UiCandidateComposeError("UI compose requires the production GM BC7 backend")
    if owned_manifest_sha256 is None:
        try:
            manifest_sha = _validate_manifest_owned_output(base, profile_id)
        except ModBuildError as exc:
            raise UiCandidateComposeError(
                f"Base candidate is not manifest-owned: {exc}"
            ) from exc
    else:
        manifest_sha = owned_manifest_sha256
        if sha256_file(base / "build-manifest.json") != manifest_sha:
            raise UiCandidateComposeError(
                "Base manifest changed after the transaction ownership check"
            )
    manifest = _load_canonical_manifest(base / "build-manifest.json")
    if (
        manifest.get("schema_version") != 1
        or manifest.get("profile_id") != profile_id
        or manifest.get("source_build_id") != build_match.source_id
        or manifest.get("target_build_id") != build_match.target_id
        or manifest.get("profile_description") != profile.get("description", "")
        or manifest.get("mod_info") != profile.get("mod_info")
    ):
        raise UiCandidateComposeError(
            "Base manifest identity differs from the selected profile/build pair"
        )
    raw_outputs = manifest.get("outputs")
    if not isinstance(raw_outputs, list):
        raise UiCandidateComposeError("Base manifest outputs are not a list")
    records = tuple(
        _record_from_manifest(raw, ordinal)
        for ordinal, raw in enumerate(raw_outputs)
    )
    paths = [record.relative_path for record in records]
    if paths != sorted(paths) or len(paths) != len({p.casefold() for p in paths}):
        raise UiCandidateComposeError(
            "Base output records are unsorted, duplicated, or case-colliding"
        )
    records_by_path = {record.relative_path: record for record in records}

    source_ui_paths = frozenset(
        entry.source
        for entry in source_manifest.entries
        if entry.source_kind == "profile_output"
    )
    frontend_paths = _frontend_profile_paths(profile)
    if frontend_paths != source_ui_paths:
        raise UiCandidateComposeError(
            "UI source manifest and frontend profile output set differ: "
            f"frontend={sorted(frontend_paths)} source={sorted(source_ui_paths)}"
        )
    gui_png_records = {
        relative
        for relative in records_by_path
        if relative.casefold().startswith("override/assets/gui/")
        and relative.casefold().endswith(".png")
    }
    has_v1 = _UI_V1_MANIFEST in records_by_path
    has_v2 = _UI_V2_MANIFEST in records_by_path
    if has_v1 == has_v2:
        raise UiCandidateComposeError(
            "Base candidate must contain exactly one UI manifest generation"
        )
    if has_v1:
        if gui_png_records != source_ui_paths or any(
            path.startswith(_UI_BUNDLE_PREFIX) for path in records_by_path
        ):
            raise UiCandidateComposeError(
                "Legacy UI base has an incomplete or dual active payload"
            )
        ui_manifest_sha = _parse_legacy_ui_v1(
            base, records_by_path, source_ui_paths
        )
        ui_mode = "legacy-v1"
    else:
        if gui_png_records or _UI_V1_MANIFEST in records_by_path:
            raise UiCandidateComposeError("UI v2 base still owns active GUI PNGs/v1")
        ui_manifest_sha = _parse_existing_ui_v2(base, records_by_path, selection)
        ui_mode = "direct-bc7-v2"

    sanitized_profile = _sanitized_base_profile(profile, source_ui_paths)
    sanitized_declared = _sanitized_base_records(records, source_ui_paths)
    failed_checks = [
        check
        for check in profile_output_contract_checks(
            base,
            sanitized_profile,
            manifest,
            sanitized_declared,
        )
        if not check.ok
    ]
    if failed_checks:
        summary = "; ".join(
            f"{check.name}: {check.detail}" for check in failed_checks[:8]
        )
        raise UiCandidateComposeError(
            "Base candidate failed its non-UI profile/GM/PCM contract: " + summary
        )

    gm_bundles = [r for r in records if r.category == ASSET_BUNDLE_CATEGORY]
    index_record = records_by_path.get("Runtime/AssetBundles/index.json")
    pcm_records = [r for r in records if r.category == "europe_music_pcm_stream"]
    pcm_manifest = records_by_path.get("Runtime/Audio/pcm-stream-manifest.tsv")
    if (
        len(gm_bundles) != 152
        or index_record is None
        or index_record.category != ASSET_BUNDLE_INDEX_CATEGORY
        or len(pcm_records) != 17
        or pcm_manifest is None
        or pcm_manifest.category != "runtime_pcm_stream_contract"
    ):
        raise UiCandidateComposeError(
            "Production base is not the exact 152-GM/17-PCM candidate"
        )
    dll = records_by_path.get("StrongholdEuropeDE.Runtime.dll")
    dll_metadata = dll.metadata if dll is not None else None
    if (
        not isinstance(dll_metadata, dict)
        or dll_metadata.get("asset_stream_enabled") is not True
        or dll_metadata.get("asset_stream_index_sha256") != index_record.sha256
        or dll_metadata.get("pcm_streaming_enabled") is not True
        or dll_metadata.get("pcm_stream_manifest_sha256") != pcm_manifest.sha256
        or dll_metadata.get("ui_texture_streaming_enabled") is not True
        or dll_metadata.get("ui_texture_manifest_sha256") != ui_manifest_sha
    ):
        raise UiCandidateComposeError(
            "Base runtime anchors do not bind its GM/PCM/UI manifests"
        )

    reusable_profile_sources = ui_mode == "legacy-v1" and all(
        records_by_path[entry.source].sha256 == entry.expected_source_sha256
        and records_by_path[entry.source].width == entry.width
        and records_by_path[entry.source].height == entry.height
        for entry in source_manifest.entries
        if entry.source_kind == "profile_output"
    )
    return ValidatedBaseCandidate(
        root=base,
        manifest_sha256=manifest_sha,
        manifest=manifest,
        records=records,
        ui_mode=ui_mode,
        ui_profile_paths=source_ui_paths,
        reusable_profile_sources=reusable_profile_sources,
    )


def _is_rebuilt_record(
    record: OutputRecord,
    ui_profile_paths: frozenset[str],
) -> bool:
    relative = record.relative_path
    return (
        relative in ui_profile_paths
        or relative in {_UI_V1_MANIFEST, _UI_V2_MANIFEST}
        or relative.startswith(_UI_BUNDLE_PREFIX)
        or relative in _RUNTIME_REBUILT_PATHS
        or relative.startswith("Runtime/Audio/")
        or record.category in _RUNTIME_REBUILT_CATEGORIES
    )


def _clone_payload_file(
    source: Path,
    destination: Path,
    *,
    immutable_gm_bundle: bool,
) -> bool:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if immutable_gm_bundle:
        try:
            os.link(source, destination)
            return True
        except OSError:
            pass
    shutil.copy2(source, destination)
    return False


def _clone_base_payload(
    base: ValidatedBaseCandidate,
    staging_root: Path,
) -> tuple[list[OutputRecord], int, int]:
    records: list[OutputRecord] = []
    hardlinks = 0
    copies = 0
    for record in base.records:
        if _is_rebuilt_record(record, base.ui_profile_paths):
            continue
        source = _safe_output(base.root, record.relative_path)
        destination = _safe_output(staging_root, record.relative_path)
        # Only the exact, already validated GM bundle payload is immutable by
        # definition in this UI-only transaction.  Copy every other reused
        # file, even when a hardlink would be faster.  That makes future
        # runtime writers unable to truncate the manifest-owned base if a new
        # output path is added without extending today's rebuilt-path list.
        if _clone_payload_file(
            source,
            destination,
            immutable_gm_bundle=(record.category == ASSET_BUNDLE_CATEGORY),
        ):
            hardlinks += 1
        else:
            copies += 1
        if (
            destination.stat().st_size != record.size
            or sha256_file(destination) != record.sha256
        ):
            raise UiCandidateComposeError(
                f"Base clone changed immutable payload: {record.relative_path}"
            )
        records.append(record)
    return records, hardlinks, copies


def _copy_legacy_profile_sources(
    base: ValidatedBaseCandidate,
    staging_root: Path,
    source_manifest: UiTextureSourceManifest,
) -> list[OutputRecord]:
    by_path = {record.relative_path: record for record in base.records}
    copied: list[OutputRecord] = []
    for entry in source_manifest.entries:
        if entry.source_kind != "profile_output":
            continue
        record = by_path[entry.source]
        source = _safe_output(base.root, entry.source)
        destination = _safe_output(staging_root, entry.source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        if (
            destination.stat().st_size != record.size
            or sha256_file(destination) != entry.expected_source_sha256
        ):
            raise UiCandidateComposeError(
                f"Legacy UI source copy changed: {entry.id}"
            )
        copied.append(record)
    if {record.relative_path for record in copied} != set(base.ui_profile_paths):
        raise UiCandidateComposeError("Legacy UI source copy set changed")
    return copied


def _materialize_current_frontend_sources(
    config: BuilderConfig,
    staging_root: Path,
    profile: dict[str, Any],
    source_manifest: UiTextureSourceManifest,
) -> list[OutputRecord]:
    records: list[OutputRecord] = []
    records.extend(_build_texture_overrides(config, staging_root, profile))
    records.extend(_build_logo(config, staging_root, profile.get("mod_logo")))
    prepared_backgrounds = _prepare_authored_backgrounds(config, profile)
    records.extend(
        _copy_authored_backgrounds(staging_root, prepared_backgrounds)
    )
    prepared_ui = _prepare_authored_ui_atlases(config, profile)
    records.extend(_copy_authored_ui_atlases(staging_root, prepared_ui))
    expected = {
        entry.source
        for entry in source_manifest.entries
        if entry.source_kind == "profile_output"
    }
    actual = {record.relative_path for record in records}
    if actual != expected or len(records) != len(actual):
        raise UiCandidateComposeError(
            "Frontend helpers produced a different UI source set: "
            f"expected={sorted(expected)} actual={sorted(actual)}"
        )
    return records


def _atomic_write_build_manifest(path: Path, manifest: Mapping[str, object]) -> None:
    payload = (
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    ).encode("utf-8")
    handle, temporary_name = tempfile.mkstemp(
        prefix=".build-manifest.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _prune_empty_staging_directories(staging_root: Path) -> None:
    """Remove only empty directories inside this run's private staging tree."""

    root = Path(staging_root).resolve(strict=True)
    for directory, child_directories, _files in os.walk(root, topdown=False):
        path = Path(directory)
        if path == root:
            continue
        if _is_link_or_junction(path):
            raise UiCandidateComposeError(
                f"Compose staging contains a linked directory: {path}"
            )
        try:
            path.rmdir()
        except OSError:
            # Non-empty directories are the expected case.  A later exact-tree
            # ownership check still catches every unsupported leftover.
            pass


def _default_precommit_validator(
    root: Path,
    profile: dict[str, Any],
    build_match: BuildMatch,
) -> None:
    from .validation import validate_mod

    checks = validate_mod(
        root,
        expected_profile_id=str(profile["id"]),
        expected_source_build_id=build_match.source_id,
        expected_target_build_id=build_match.target_id,
        expected_profile=profile,
    )
    failed = [check for check in checks if not check.ok]
    if failed:
        summary = "; ".join(
            f"{check.name}: {check.detail}" for check in failed[:12]
        )
        raise UiCandidateComposeError(
            "Composed candidate failed precommit validation: " + summary
        )


def compose_ui_candidate(
    config: BuilderConfig,
    build_match: BuildMatch,
    profile_path: Path,
    *,
    ui_texture_backend_fn: Callable[..., UiTextureBuildResult]
    = build_ui_texture_backend,
    runtime_builder_fn: Callable[..., list[RuntimeArtifact]]
    = build_runtime_artifacts,
    frontend_materializer_fn: Callable[
        [BuilderConfig, Path, dict[str, Any], UiTextureSourceManifest],
        list[OutputRecord],
    ] = _materialize_current_frontend_sources,
    base_validator_fn: Callable[..., ValidatedBaseCandidate]
    = validate_base_candidate,
    precommit_validator_fn: Callable[[Path], None] | None = None,
) -> UiCandidateComposeResult:
    """Replace one validated production base through a UI-only transaction."""

    try:
        profile = load_profile(Path(profile_path))
        selection = load_ui_texture_backend_selection(config.project_root, profile)
        atlas_backend = parse_atlas_backend(profile)
        if selection is None:
            raise UiCandidateComposeError(
                "Compose profile has no explicit ui_texture_backend"
            )
        if atlas_backend is None:
            raise UiCandidateComposeError(
                "Compose profile has no atlas_backend resource policy"
            )
        source_manifest = load_ui_texture_source_manifest(
            selection.source_manifest_path
        )
    except (
        OSError,
        UnicodeError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        ModBuildError,
        UiAssetBundleError,
        AssetStreamContractError,
    ) as exc:
        raise UiCandidateComposeError(
            f"Compose profile/UI contract is invalid: {exc}"
        ) from exc
    runtime_selection = profile.get("runtime")
    if not isinstance(runtime_selection, dict) or runtime_selection.get("enabled") is not True:
        raise UiCandidateComposeError("UI compose requires runtime.enabled")

    transaction = _prepare_mod_root(config, str(profile["id"]), replace=True)
    staging = transaction.staging_root
    try:
        owned_sha = getattr(transaction, "_prior_manifest_sha256", None)
        if not isinstance(owned_sha, str):
            raise UiCandidateComposeError(
                "UI compose requires an existing manifest-owned base candidate"
            )
        base = base_validator_fn(
            transaction.final_root,
            profile,
            build_match,
            selection,
            source_manifest,
            atlas_backend,
            owned_manifest_sha256=owned_sha,
        )
        records, hardlinks, copies = _clone_base_payload(base, staging)
        if base.reusable_profile_sources:
            records.extend(
                _copy_legacy_profile_sources(base, staging, source_manifest)
            )
        else:
            records.extend(
                frontend_materializer_fn(
                    config,
                    staging,
                    profile,
                    source_manifest,
                )
            )

        try:
            toolchain = _resolve_toolchain(config.project_root, None)
            ui_result = ui_texture_backend_fn(
                workspace_root=config.project_root,
                mod_root=staging,
                source_manifest_path=selection.source_manifest_path,
                quality_policy_path=selection.quality_policy_path,
                unity_editor=toolchain.executable,
                max_resident_bytes=(
                    atlas_backend.resource_policy.ui_resident_bytes
                ),
                timeout_seconds=toolchain.timeout_seconds,
            )
        except (AssetStreamBuildError, UiAssetBundleError) as exc:
            raise UiCandidateComposeError(
                f"UI-only AssetBundle build failed closed: {exc}"
            ) from exc
        records = _integrate_ui_texture_build(
            staging,
            records,
            ui_result,
            source_manifest,
            max_resident_bytes=atlas_backend.resource_policy.ui_resident_bytes,
        )

        try:
            runtime_artifacts = runtime_builder_fn(
                config,
                build_match,
                staging,
                str(profile["id"]),
                runtime_selection,
                profile.get("dock_placement_rules"),
                atlas_backend,
                selection,
            )
        except RuntimeBuildError as exc:
            raise UiCandidateComposeError(
                f"UI-only runtime rebuild failed closed: {exc}"
            ) from exc
        records.extend(
            _record(
                staging,
                artifact.path,
                artifact.category,
                artifact.source_reference,
                metadata=artifact.metadata,
            )
            for artifact in runtime_artifacts
        )
        _validate_output_records_unique(records)
        manifest = {
            "schema_version": 1,
            "profile_id": str(profile["id"]),
            "profile_description": profile.get("description", ""),
            "source_build_id": build_match.source_id,
            "target_build_id": build_match.target_id,
            "mod_info": profile["mod_info"],
            "outputs": [
                asdict(record)
                for record in sorted(records, key=lambda item: item.relative_path)
            ],
        }
        _prune_empty_staging_directories(staging)
        manifest_path = staging / "build-manifest.json"
        _atomic_write_build_manifest(manifest_path, manifest)
        if precommit_validator_fn is None:
            _default_precommit_validator(staging, profile, build_match)
        else:
            precommit_validator_fn(staging)
        final_root = transaction.commit()
        final_manifest_sha = sha256_file(final_root / "build-manifest.json")
        return UiCandidateComposeResult(
            output_root=final_root,
            prior_manifest_sha256=base.manifest_sha256,
            manifest_sha256=final_manifest_sha,
            ui_manifest_sha256=ui_result.runtime.manifest_sha256,
            ui_cache_hit_count=ui_result.cache_hit_count,
            ui_cache_miss_count=ui_result.cache_miss_count,
            cloned_hardlink_count=hardlinks,
            cloned_copy_count=copies,
        )
    except BaseException:
        transaction.abort()
        raise
    finally:
        transaction.close()

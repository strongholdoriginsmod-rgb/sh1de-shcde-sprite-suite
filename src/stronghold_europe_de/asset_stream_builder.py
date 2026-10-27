"""Transactional production bridge from staged GM overrides to AssetBundles."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
import hashlib
import json
from math import isfinite
import os
import re
from pathlib import Path, PurePosixPath, PureWindowsPath
import shutil
import subprocess
import sys
from typing import Any
from uuid import uuid4

from PIL import Image, UnidentifiedImageError

from .asset_stream_contract import (
    ASSET_BUNDLE_CATEGORY,
    ASSET_BUNDLE_INDEX_CATEGORY,
    ATLAS_BACKEND_KIND,
    BC7_ATLAS_ASSET_FILENAME,
    BC7_ATLAS_BACKEND_KIND,
    BC7_QUALITY_VERIFIER_ID,
    INDEX_OUTPUT_PATH,
    MAX_ABSOLUTE_SPRITE_PIVOT,
    AssetStreamContractError,
    VanillaOmittedGroup,
    expected_material_binding,
    parse_asset_bundle_build_report,
    parse_asset_bundle_build_input_v2,
    parse_asset_bundle_build_report_v2,
    parse_asset_bundle_index,
    parse_asset_bundle_index_v2,
    parse_atlas_backend,
    validate_bundle_output_records,
    validate_bundle_output_records_v2,
)
from .asset_stream_group_cache import GroupCacheError
from .asset_stream_incremental_v2 import (
    IncrementalV2BuildError,
    build_incremental_v2_asset_stream,
)
from .gm_atlas import describe_group_manifest, parse_loader_frame_name
from .hashing import sha256_file
from .loader_groups import LOADER_GROUP_TABLE
from .unity_toolchain import UnityToolchainError, inspect_unity_editor, standard_unity_editor_paths
from .unity_asset_bundle import (
    BUILD_OPTIONS,
    BUILD_TARGET,
    UNITY_REVISION,
    UNITY_VERSION,
    AtlasGroupFingerprint,
    AtlasGroupInput,
    FrameSource,
    PreparedUnityProject,
    UnityAssetBundleError,
    fingerprint_atlas_groups_v2,
    group_slug,
    preflight_atlas_groups,
    prepare_unity_asset_bundle_project,
    run_headless_build,
)


class AssetStreamBuildError(RuntimeError):
    """Raised when streamed output cannot be proven exact."""


class _DeterministicProgress:
    """Best-effort, count-based diagnostics that never affect build output."""

    def __init__(self, phase: str, unit: str, total: int, **context: int) -> None:
        self.phase = phase
        self.unit = unit
        self.total = total
        self.completed = 0
        self.next_percent = 5
        fields = " ".join(f"{key}={context[key]}" for key in sorted(context))
        suffix = f" {fields}" if fields else ""
        self._emit(f"[asset-stream] {phase} start {unit}=0/{total} percent=0{suffix}")

    @staticmethod
    def _emit(message: str) -> None:
        try:
            print(message, file=sys.stderr, flush=True)
        except (BrokenPipeError, OSError, ValueError):
            # Progress is diagnostic only; a closed/redirection-broken stderr
            # must not change cache, artifact, or fail-closed build semantics.
            pass

    def advance(self) -> None:
        self.completed += 1
        if self.completed > self.total:
            return
        percent = 100 if self.total == 0 else self.completed * 100 // self.total
        if self.completed < self.total and percent >= self.next_percent:
            self._emit(
                f"[asset-stream] {self.phase} progress "
                f"{self.unit}={self.completed}/{self.total} percent={percent}"
            )
            self.next_percent = (percent // 5 + 1) * 5

    def finish(self) -> None:
        self._emit(
            f"[asset-stream] {self.phase} complete "
            f"{self.unit}={self.completed}/{self.total} percent=100"
        )


class _ProgressFrames(tuple):
    """A content-identical tuple that reports a frame after it was consumed."""

    def __new__(
        cls,
        frames: tuple[FrameSource, ...],
        progress: _DeterministicProgress,
    ) -> "_ProgressFrames":
        instance = super().__new__(cls, frames)
        instance._progress = progress
        return instance

    def __iter__(self):
        for frame in tuple.__iter__(self):
            yield frame
            self._progress.advance()


def _fingerprint_atlas_groups_v2_with_progress(
    groups: Sequence[AtlasGroupInput],
) -> tuple[AtlasGroupFingerprint, ...]:
    """Observe V2 hashing without changing the hash-bearing packer source."""

    total_frames = sum(len(group.frames) for group in groups)
    progress = _DeterministicProgress(
        "fingerprint-v2", "frames", total_frames, groups=len(groups)
    )
    wrapped: list[AtlasGroupInput] = []
    originals: dict[int, AtlasGroupInput] = {}
    for group in groups:
        observed = replace(group, frames=_ProgressFrames(group.frames, progress))
        wrapped.append(observed)
        originals[id(observed)] = group
    fingerprints = fingerprint_atlas_groups_v2(tuple(wrapped))
    restored = tuple(
        replace(fingerprint, spec=originals[id(fingerprint.spec)])
        for fingerprint in fingerprints
    )
    progress.finish()
    return restored


@dataclass(frozen=True)
class StreamOutputRecord:
    relative_path: str
    category: str
    size: int
    sha256: str
    width: int | None = None
    height: int | None = None
    source_reference: str | None = None
    lost_alpha: int | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class AssetStreamBuildResult:
    outputs: tuple[StreamOutputRecord, ...]
    removed_relative_paths: tuple[str, ...]
    build_id: str
    group_count: int
    omitted_group_count: int
    unity_work_root: Path


@dataclass(frozen=True)
class _Toolchain:
    executable: Path
    timeout_seconds: int
    executable_sha256: str


@dataclass(frozen=True)
class _LegacyFrame:
    source: FrameSource
    origin: str


_TOOLCHAIN_CONFIG = "config/unity-assetbundle-toolchain.json"
_TOOLCHAIN_SCHEMA = "stronghold-europe-de.unity-assetbundle-toolchain.v1"
_TOOLCHAIN_KEYS = {
    "schema", "product", "version", "revision", "build_target",
    "build_options", "windows_executable_size_bytes",
    "windows_executable_sha256", "environment_override",
    "discovery_relative_paths", "timeout_seconds",
}
_UNITY_EXE_SIZE = 72_405_240
_UNITY_EXE_SHA256 = (
    "0904c55d483e49115d7b22373812f07a0e5f66ff4656a1433cf73bcd6db99644"
)
_UNITY_ENVIRONMENT = "STRONGHOLD_EUROPE_UNITY_EDITOR"
_UNITY_DISCOVERY = ("work/toolchains/unity-2021.3.45f2/Editor/Unity.exe",)
_UNITY_TIMEOUT_SECONDS = 7200
_FROZEN_QUALITY_CONFIG = "config/asset-stream-bc7-quality-v2.json"
_MAX_FROZEN_QUALITY_CONFIG_BYTES = 1024 * 1024

_ASSEMBLY_CSHARP_SIZE = 3_693_056
_ASSEMBLY_CSHARP_SHA256 = (
    "01da4c57f8a0e04a77804e78f79bacb1ae63d934d6d391f0dcaf3742bcca5de3"
)
_ASSEMBLY_IDENTITY = (
    "Assembly-CSharp",
    "0.0.0.0",
    "1ad0eaf4-bb64-4eb8-9126-ff328de7f68c",
)
_ATLAS_PREFIX = "Override/Atlas/"
_SPRITE_PREFIX = "Override/Sprites/"
_STREAM_PREFIX = "Runtime/AssetBundles/"
_FOLIAGE_GROUPS = frozenset(
    name.casefold()
    for name in (
        "tree_apple", "tree_pine", "tree_birch", "Tree_Oak",
        "Tree_Chestnut", "tree_shrub1", "tree_shrub2",
    )
)


def _error(detail: str) -> None:
    raise AssetStreamBuildError(detail)


def _safe_relative(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        _error(f"{label} is not a canonical relative path: {value!r}")
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if (
        posix.is_absolute()
        or windows.is_absolute()
        or bool(windows.drive)
        or posix.as_posix() != value
        or any(part in {"", ".", ".."} for part in posix.parts)
    ):
        _error(f"{label} is not a safe relative path: {value!r}")
    return value


def _mod_path(mod_root: Path, relative: str, label: str) -> Path:
    safe = _safe_relative(relative, label)
    root = mod_root.resolve(strict=True)
    candidate = root.joinpath(*safe.split("/"))
    existing = candidate.parent
    while not existing.exists() and existing != root:
        existing = existing.parent
    try:
        resolved_existing = existing.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise AssetStreamBuildError(f"{label} has no safe parent: {safe}") from exc
    if resolved_existing != root and root not in resolved_existing.parents:
        _error(f"{label} escaped staging: {safe}")
    return candidate


def _load_json(path: Path, label: str) -> Mapping[str, object]:
    try:
        raw = path.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            _error(f"{label} has a UTF-8 BOM")
        text = raw.decode("utf-8", errors="strict")

        def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, value in items:
                if key in result:
                    _error(f"{label} contains duplicate JSON key {key!r}")
                result[key] = value
            return result

        value = json.loads(text, object_pairs_hook=pairs)
    except AssetStreamBuildError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise AssetStreamBuildError(f"Could not parse {label}: {exc}") from exc
    if not isinstance(value, Mapping):
        _error(f"{label} root is not an object")
    return value


def _exact_keys(value: Mapping[str, object], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        _error(
            f"{label} fields changed: missing={sorted(expected-actual)}, "
            f"extra={sorted(actual-expected)}"
        )


def _load_frozen_quality_envelope(
    project_root: Path, quality_policy: object
) -> Mapping[str, object]:
    """Load the one canonical, SHA-bound acceptance envelope for V2."""

    path = project_root / _FROZEN_QUALITY_CONFIG
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise AssetStreamBuildError(
            f"Frozen BC7 quality policy is missing: {path}"
        ) from exc
    if not 1 <= len(raw) <= _MAX_FROZEN_QUALITY_CONFIG_BYTES:
        _error("Frozen BC7 quality policy size is outside 1..1048576 bytes")
    document = _load_json(path, "frozen BC7 quality policy")
    _exact_keys(
        document,
        {"acceptance_envelope", "id", "mode", "verifier_id"},
        "frozen BC7 quality policy",
    )
    try:
        canonical = json.dumps(
            document,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise AssetStreamBuildError(
            f"Frozen BC7 quality policy is not canonical JSON: {exc}"
        ) from exc
    if raw != canonical + b"\n":
        _error("Frozen BC7 quality policy is not canonical UTF-8 plus one LF")
    policy_id = getattr(quality_policy, "id", None)
    policy_sha256 = getattr(quality_policy, "sha256", None)
    verifier_id = getattr(quality_policy, "verifier_id", None)
    if (
        document["id"] != policy_id
        or document["mode"] != "frozen"
        or document["verifier_id"] != verifier_id
        or verifier_id != BC7_QUALITY_VERIFIER_ID
        or hashlib.sha256(canonical).hexdigest() != policy_sha256
    ):
        _error("Frozen BC7 quality policy identity/SHA binding drifted")
    envelope = document["acceptance_envelope"]
    if not isinstance(envelope, Mapping) or not envelope:
        _error("Frozen BC7 quality acceptance_envelope is empty or malformed")
    return envelope


def _stable_pinned_file(path: Path, size: int, digest: str, label: str) -> Path:
    try:
        resolved = path.resolve(strict=True)
        before = resolved.stat()
    except (OSError, RuntimeError) as exc:
        raise AssetStreamBuildError(f"{label} is missing: {path}") from exc
    if not resolved.is_file() or before.st_size != size:
        _error(f"{label} size changed: {resolved}")
    actual = sha256_file(resolved)
    after = resolved.stat()
    if (
        before.st_size,
        before.st_mtime_ns,
        getattr(before, "st_ino", None),
    ) != (
        after.st_size,
        after.st_mtime_ns,
        getattr(after, "st_ino", None),
    ):
        _error(f"{label} changed while hashing: {resolved}")
    if actual != digest:
        _error(f"{label} SHA-256 changed: expected={digest} actual={actual}")
    return resolved


def _resolve_toolchain(project_root: Path, explicit: Path | None) -> _Toolchain:
    config = _load_json(
        project_root / _TOOLCHAIN_CONFIG, "Unity AssetBundle toolchain config"
    )
    _exact_keys(config, _TOOLCHAIN_KEYS, "Unity AssetBundle toolchain config")
    expected: dict[str, object] = {
        "schema": _TOOLCHAIN_SCHEMA,
        "product": "Unity Editor",
        "version": UNITY_VERSION,
        "revision": UNITY_REVISION,
        "build_target": BUILD_TARGET,
        "build_options": list(BUILD_OPTIONS),
        "windows_executable_size_bytes": _UNITY_EXE_SIZE,
        "windows_executable_sha256": _UNITY_EXE_SHA256,
        "environment_override": _UNITY_ENVIRONMENT,
        "discovery_relative_paths": list(_UNITY_DISCOVERY),
        "timeout_seconds": _UNITY_TIMEOUT_SECONDS,
    }
    if config != expected:
        _error("Unity AssetBundle toolchain config differs from its reviewed pin")
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(explicit)
    else:
        override = os.environ.get(_UNITY_ENVIRONMENT)
        if override:
            candidates.append(Path(override))
        candidates.extend(
            project_root.joinpath(*relative.split("/"))
            for relative in _UNITY_DISCOVERY
        )
        candidates.extend(standard_unity_editor_paths(UNITY_VERSION))
    chosen = next((candidate for candidate in candidates if candidate.is_file()), None)
    if chosen is None:
        _error(f"Unity Editor was not found: {[str(x) for x in candidates]}")
    try:
        editor = inspect_unity_editor(chosen, UNITY_VERSION, UNITY_REVISION)
    except UnityToolchainError as exc:
        raise AssetStreamBuildError(str(exc)) from exc
    return _Toolchain(editor.executable, _UNITY_TIMEOUT_SECONDS, editor.sha256)


def _parse_exact_gm_enum_output(
    stdout: str,
    *,
    required: set[str] | None = None,
) -> dict[str, int]:
    lines = stdout.splitlines()
    identity = lines[0].split("\t") if lines else []
    if (
        len(identity) != 4
        or identity[:2] != ["ASSEMBLY", "Assembly-CSharp"]
        or re.fullmatch(r"[0-9]+(?:\.[0-9]+){3}", identity[2]) is None
        or re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", identity[3]) is None
    ):
        _error(f"Invalid target managed identity: {identity!r}")
    result: dict[str, int] = {}
    used: set[int] = set()
    for line in lines[1:]:
        fields = line.split("\t")
        if len(fields) != 2 or not fields[0].startswith("GM_"):
            _error(f"Malformed Enums.GM row: {line!r}")
        try:
            value = int(fields[1], 10)
        except ValueError as exc:
            raise AssetStreamBuildError(f"Malformed Enums.GM row: {line!r}") from exc
        if fields[0] in result or value in used or not 0 <= value <= 233:
            _error(f"Duplicate/invalid Enums.GM row: {line!r}")
        result[fields[0]] = value
        used.add(value)
    # Each selected group is checked against its actual enum below. Unused
    # registrations do not constrain a smaller profile.
    required_names = set() if required is None else required
    if not required_names <= set(result):
        _error(
            f"Pinned Enums.GM is incomplete: "
            f"{sorted(required_names-set(result))}"
        )
    return result


def _read_exact_gm_enum_ids(assembly_path: Path) -> dict[str, int]:
    """Read installed Enums.GM metadata without executing game code."""

    try:
        assembly = assembly_path.resolve(strict=True)
        before = assembly.stat()
    except OSError as exc:
        raise AssetStreamBuildError(f"Target Assembly-CSharp.dll is missing: {assembly_path}") from exc
    if not assembly.is_file() or before.st_size == 0:
        _error("Target Assembly-CSharp.dll is empty or not a regular file")
    digest = sha256_file(assembly)
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if powershell is None:
        _error("PowerShell is required to inspect pinned Enums.GM metadata")
    environment = os.environ.copy()
    environment["SEDE_GM_ASSEMBLY"] = str(assembly)
    script = (
        "$a=[Reflection.Assembly]::ReflectionOnlyLoadFrom($env:SEDE_GM_ASSEMBLY);"
        "$i=$a.GetName();"
        "$m=$a.ManifestModule.ModuleVersionId.ToString('D').ToLowerInvariant();"
        "[Console]::Out.WriteLine('ASSEMBLY' + [char]9 + $i.Name + [char]9 + "
        "$i.Version.ToString() + [char]9 + $m);"
        "$t=$a.GetType('Enums+GM',$true);"
        "$flags=[Reflection.BindingFlags]'Public,Static';"
        "foreach($f in $t.GetFields($flags)){"
        "$v=[Convert]::ToInt32($f.GetRawConstantValue());"
        "[Console]::Out.WriteLine($f.Name + [char]9 + $v.ToString())}"
    )
    try:
        completed = subprocess.run(
            [powershell, "-NoProfile", "-NonInteractive", "-Command", script],
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AssetStreamBuildError("Could not inspect pinned Enums.GM") from exc
    if completed.returncode != 0:
        _error(
            "Could not inspect pinned Enums.GM: "
            + (completed.stderr.strip() or f"exit {completed.returncode}")
        )
    after = assembly.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or sha256_file(assembly) != digest:
        _error("Target Assembly-CSharp.dll changed during enum inspection")
    return _parse_exact_gm_enum_output(completed.stdout)


def _integer(value: object, label: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        _error(f"{label} must be an integer >= {minimum}")
    return value


def _finite(value: object, label: str, positive: bool = False) -> float:
    if isinstance(value, bool):
        _error(f"{label} must be finite")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise AssetStreamBuildError(f"{label} must be finite") from exc
    if not isfinite(result) or (positive and result <= 0):
        _error(f"{label} must be {'positive and ' if positive else ''}finite")
    return result


def _open_rgba(path: Path, label: str) -> Image.Image:
    try:
        with Image.open(path) as image:
            image.load()
            if image.mode != "RGBA" or image.width <= 0 or image.height <= 0:
                _error(f"{label} is not a positive-size RGBA PNG")
            return image.copy()
    except AssetStreamBuildError:
        raise
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        raise AssetStreamBuildError(f"Could not decode {label}: {path}") from exc


def _save_png_exclusive(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            image.save(stream, format="PNG", optimize=False, compress_level=9)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise AssetStreamBuildError(f"Frame staging collision: {path}") from exc


def _legacy_atlas_frames(
    mod_root: Path, group: str, frame_root: Path
) -> tuple[dict[str, _LegacyFrame], int]:
    loader = LOADER_GROUP_TABLE.get(group)
    if loader is None:
        _error(f"Atlas group is absent from pinned loader table: {group}")
    prefix = f"{_ATLAS_PREFIX}{group}/"
    atlas_path = _mod_path(mod_root, prefix + "atlas.png", f"{group} atlas")
    json_path = _mod_path(mod_root, prefix + "atlas.json", f"{group} descriptor")
    mask_path = _mod_path(mod_root, prefix + "atlas_m.png", f"{group} mask")
    if not atlas_path.is_file() or not json_path.is_file():
        _error(f"Legacy atlas payload is incomplete for {group}")
    requires_mask = not loader.plain_shader
    if mask_path.exists() != requires_mask:
        _error(
            f"Legacy mask policy changed for {group}: "
            f"required={requires_mask} present={mask_path.exists()}"
        )
    document = _load_json(json_path, f"{group}/atlas.json")
    _exact_keys(document, {"pixelsPerUnit", "frames"}, f"{group}/atlas.json")
    _finite(document["pixelsPerUnit"], f"{group}.pixelsPerUnit", positive=True)
    raw_frames = document["frames"]
    if not isinstance(raw_frames, list) or not 1 <= len(raw_frames) <= 4096:
        _error(f"{group}/atlas.json frame count is outside 1..4096")
    atlas = _open_rgba(atlas_path, f"{group}/atlas.png")
    mask = _open_rgba(mask_path, f"{group}/atlas_m.png") if requires_mask else None
    try:
        if mask is not None and mask.size != atlas.size:
            _error(f"Legacy atlas/mask geometry differs for {group}")
        result: dict[str, _LegacyFrame] = {}
        slots: set[tuple[int, bool]] = set()
        cached: dict[tuple[int, int, int, int], tuple[Path, Path | None]] = {}
        max_index = -1
        for ordinal, raw in enumerate(raw_frames):
            label = f"{group}.frames[{ordinal}]"
            if not isinstance(raw, Mapping):
                _error(f"{label} is not an object")
            _exact_keys(raw, {"name", "rect", "pivot", "pixelsPerUnit"}, label)
            name = raw["name"]
            if not isinstance(name, str) or not name:
                _error(f"{label}.name is invalid")
            slot = parse_loader_frame_name(name, group, loader.dash_format)
            if slot is None or name in result or (slot.index, slot.is_alt) in slots:
                _error(f"Invalid/duplicate loader slot in {group}: {name!r}")
            rect = raw["rect"]
            pivot = raw["pivot"]
            if not isinstance(rect, Mapping) or not isinstance(pivot, Mapping):
                _error(f"{label} rect/pivot is not an object")
            _exact_keys(rect, {"x", "y", "w", "h"}, f"{label}.rect")
            _exact_keys(pivot, {"x", "y"}, f"{label}.pivot")
            x = _integer(rect["x"], f"{label}.rect.x")
            y = _integer(rect["y"], f"{label}.rect.y")
            width = _integer(rect["w"], f"{label}.rect.w", 1)
            height = _integer(rect["h"], f"{label}.rect.h", 1)
            if x + width > atlas.width or y + height > atlas.height:
                _error(f"Bottom-left atlas rect escapes for {name}")
            pivot_x = _finite(pivot["x"], f"{label}.pivot.x")
            pivot_y = _finite(pivot["y"], f"{label}.pivot.y")
            ppu = _finite(raw["pixelsPerUnit"], f"{label}.pixelsPerUnit", True)
            if (
                not -MAX_ABSOLUTE_SPRITE_PIVOT
                <= pivot_x
                <= MAX_ABSOLUTE_SPRITE_PIVOT
                or not -MAX_ABSOLUTE_SPRITE_PIVOT
                <= pivot_y
                <= MAX_ABSOLUTE_SPRITE_PIVOT
            ):
                _error(f"Pivot is outside streamed v1 range: {name}")
            key = (x, y, width, height)
            paths = cached.get(key)
            if paths is None:
                # Legacy JSON is bottom-left; Pillow crops from top-left.
                top = atlas.height - y - height
                box = (x, top, x + width, top + height)
                suffix = hashlib.sha256(
                    f"{x}:{y}:{width}:{height}".encode("ascii")
                ).hexdigest()[:20]
                main_out = frame_root / group_slug(group) / f"{suffix}-main.png"
                crop = atlas.crop(box)
                try:
                    _save_png_exclusive(crop, main_out)
                finally:
                    crop.close()
                mask_out: Path | None = None
                if mask is not None:
                    mask_out = frame_root / group_slug(group) / f"{suffix}-mask.png"
                    crop = mask.crop(box)
                    try:
                        _save_png_exclusive(crop, mask_out)
                    finally:
                        crop.close()
                paths = (main_out, mask_out)
                cached[key] = paths
            source = FrameSource(
                name=name, index=slot.index, alt=slot.is_alt,
                main_path=paths[0], mask_path=paths[1],
                width=width, height=height,
                pivot_x=pivot_x, pivot_y=pivot_y, pixels_per_unit=ppu,
            )
            result[name] = _LegacyFrame(source, "legacy_atlas")
            slots.add((slot.index, slot.is_alt))
            max_index = max(max_index, slot.index)
        return result, max_index + 1
    finally:
        atlas.close()
        if mask is not None:
            mask.close()


def _mapping_by_name(mapping: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    raw = mapping.get("sprites")
    if not isinstance(raw, list):
        _error("Mapping sprites must be a list")
    result: dict[str, Mapping[str, object]] = {}
    for ordinal, proposal in enumerate(raw):
        if not isinstance(proposal, Mapping):
            _error(f"mapping.sprites[{ordinal}] is not an object")
        name = proposal.get("name")
        if not isinstance(name, str) or not name or name in result:
            _error(f"mapping.sprites[{ordinal}] has invalid/duplicate name")
        result[name] = proposal
    return result


def _proposal_group(name: str, proposal: Mapping[str, object]) -> str:
    declared = proposal.get("group")
    if isinstance(declared, str) and declared in LOADER_GROUP_TABLE:
        loader = LOADER_GROUP_TABLE[declared]
        if parse_loader_frame_name(name, declared, loader.dash_format) is not None:
            return declared
    matches = [
        group
        for group, loader in LOADER_GROUP_TABLE.items()
        if parse_loader_frame_name(name, group, loader.dash_format) is not None
    ]
    if len(matches) != 1:
        _error(f"Sparse frame has no unique loader group: {name!r} -> {matches}")
    return matches[0]


def _sparse_frames(
    mod_root: Path,
    record_by_path: Mapping[str, Mapping[str, object]],
    proposals: Mapping[str, Mapping[str, object]],
) -> dict[str, dict[str, _LegacyFrame]]:
    paths = sorted(
        path for path in record_by_path
        if path.casefold().startswith(_SPRITE_PREFIX.casefold())
    )
    folded = {path.casefold(): path for path in paths}
    if len(folded) != len(paths):
        _error("Sparse output paths collide case-insensitively")
    mains = [path for path in paths if not path.casefold().endswith("_m.png")]
    used_masks: set[str] = set()
    result: dict[str, dict[str, _LegacyFrame]] = {}
    for relative in mains:
        if not relative.endswith(".png") or "/" in relative[len(_SPRITE_PREFIX):]:
            _error(f"Sparse output is not a flat canonical PNG: {relative}")
        name = relative[len(_SPRITE_PREFIX):-4]
        proposal = proposals.get(name)
        if proposal is None:
            _error(f"Sparse output has no exact target mapping: {name}")
        group = _proposal_group(name, proposal)
        loader = LOADER_GROUP_TABLE[group]
        slot = parse_loader_frame_name(name, group, loader.dash_format)
        assert slot is not None
        target = proposal.get("target")
        if not isinstance(target, Mapping):
            _error(f"Sparse frame has no target metadata: {name}")
        main_path = _mod_path(mod_root, relative, f"sparse frame {name}")
        image = _open_rgba(main_path, f"sparse frame {name}")
        try:
            width, height = image.size
        finally:
            image.close()
        expected_size = (
            round(_finite(target.get("width"), f"{name}.target.width", True)),
            round(_finite(target.get("height"), f"{name}.target.height", True)),
        )
        if (width, height) != expected_size:
            _error(
                f"Sparse geometry differs from target for {name}: "
                f"actual={(width,height)} expected={expected_size}"
            )
        mask_relative = f"{_SPRITE_PREFIX}{name}_m.png"
        actual_mask = folded.get(mask_relative.casefold())
        if loader.plain_shader:
            if actual_mask is not None:
                _error(f"Plain sparse GM frame unexpectedly has mask: {name}")
            mask_path = None
        else:
            if actual_mask != mask_relative:
                _error(f"Team-colour sparse GM frame is missing exact mask: {name}")
            mask_path = _mod_path(mod_root, mask_relative, f"sparse mask {name}")
            image = _open_rgba(mask_path, f"sparse mask {name}")
            try:
                if image.size != (width, height):
                    _error(f"Sparse main/mask geometry differs: {name}")
            finally:
                image.close()
            used_masks.add(mask_relative)
        source = FrameSource(
            name=name, index=slot.index, alt=slot.is_alt,
            main_path=main_path, mask_path=mask_path,
            width=width, height=height,
            pivot_x=_finite(target.get("pivot_x"), f"{name}.target.pivot_x"),
            pivot_y=_finite(target.get("pivot_y"), f"{name}.target.pivot_y"),
            pixels_per_unit=_finite(
                target.get("pixels_per_unit"), f"{name}.target.ppu", True
            ),
        )
        group_frames = result.setdefault(group, {})
        if name in group_frames or any(
            (item.source.index, item.source.alt) == (slot.index, slot.is_alt)
            for item in group_frames.values()
        ):
            _error(f"Sparse group duplicates loader slot: {name}")
        group_frames[name] = _LegacyFrame(source, "sparse_override")
    orphan_masks = sorted(
        path for path in paths
        if path.casefold().endswith("_m.png") and path not in used_masks
    )
    if orphan_masks:
        _error(f"Sparse payload has orphan/forbidden masks: {orphan_masks[:20]}")
    return result


def _expected_group_names(
    mapping_sprites: Sequence[Mapping[str, object]], group: str
) -> set[str]:
    try:
        manifest = describe_group_manifest(list(mapping_sprites), group)
    except Exception as exc:
        raise AssetStreamBuildError(
            f"Could not derive pinned loader manifest for {group}: {exc}"
        ) from exc
    loader = LOADER_GROUP_TABLE[group]
    names = {
        str(proposal.get("name"))
        for proposal in mapping_sprites
        if parse_loader_frame_name(
            str(proposal.get("name", "")), group, loader.dash_format
        ) is not None
    }
    if len(names) != manifest["expected_frame_count"]:
        _error(f"Mapping manifest/name set disagrees for {group}")
    return names


def _collect_group_inputs(
    mod_root: Path,
    mapping: Mapping[str, object],
    output_records: Sequence[Mapping[str, object]],
    frame_root: Path,
    gm_ids: Mapping[str, int],
    *,
    filter_modes: Mapping[str, str] | None = None,
) -> tuple[tuple[AtlasGroupInput, ...], tuple[str, ...]]:
    record_by_path: dict[str, Mapping[str, object]] = {}
    folded: set[str] = set()
    for ordinal, record in enumerate(output_records):
        if not isinstance(record, Mapping):
            _error(f"output_records[{ordinal}] is not a mapping")
        relative = _safe_relative(
            record.get("relative_path"), f"output_records[{ordinal}].relative_path"
        )
        if relative.casefold() in folded:
            _error(f"OutputRecords collide before streaming: {relative}")
        folded.add(relative.casefold())
        record_by_path[relative] = record
    if any(path.casefold().startswith(_STREAM_PREFIX.casefold()) for path in record_by_path):
        _error("Staging already contains streamed AssetBundle OutputRecords")

    groups: dict[str, dict[str, _LegacyFrame]] = {}
    array_sizes: dict[str, int] = {}
    descriptors = sorted(
        path for path in record_by_path
        if path.casefold().startswith(_ATLAS_PREFIX.casefold())
        and path.casefold().endswith("/atlas.json")
    )
    extraction_progress = _DeterministicProgress(
        "frame-extraction", "groups", len(descriptors)
    )
    expected_atlas_paths: set[str] = set()
    for relative in descriptors:
        parts = PurePosixPath(relative).parts
        if len(parts) != 4 or parts[:2] != ("Override", "Atlas"):
            _error(f"Legacy atlas descriptor path changed: {relative}")
        group = parts[2]
        if group in groups:
            _error(f"Legacy atlas group repeats: {group}")
        groups[group], array_sizes[group] = _legacy_atlas_frames(
            mod_root, group, frame_root
        )
        extraction_progress.advance()
        expected_atlas_paths.update(
            {
                f"{_ATLAS_PREFIX}{group}/atlas.png",
                f"{_ATLAS_PREFIX}{group}/atlas.json",
            }
        )
        if not LOADER_GROUP_TABLE[group].plain_shader:
            expected_atlas_paths.add(f"{_ATLAS_PREFIX}{group}/atlas_m.png")
    extraction_progress.finish()
    actual_atlas_paths = {
        path
        for path in record_by_path
        if path.casefold().startswith(_ATLAS_PREFIX.casefold())
    }
    if actual_atlas_paths != expected_atlas_paths:
        _error(
            "Legacy atlas OutputRecord set is incomplete or contains extras: "
            f"missing={sorted(expected_atlas_paths-actual_atlas_paths)} "
            f"extra={sorted(actual_atlas_paths-expected_atlas_paths)}"
        )

    proposals = _mapping_by_name(mapping)
    raw_sprites = mapping.get("sprites")
    assert isinstance(raw_sprites, list)
    mapping_sprites = [item for item in raw_sprites if isinstance(item, Mapping)]
    sparse = _sparse_frames(mod_root, record_by_path, proposals)
    for group, frames in sparse.items():
        if group in groups:
            # Individual Override/Sprites is the loader's final word.
            groups[group].update(frames)
            array_sizes[group] = max(
                array_sizes[group],
                max(item.source.index for item in frames.values()) + 1,
            )
        else:
            groups[group] = dict(frames)
            array_sizes[group] = max(item.source.index for item in frames.values()) + 1
    if not groups:
        _error("Streaming backend was selected without a GM group")
    if len(groups) > 234:
        _error(f"Streaming group count exceeds pinned Enums.GM outer size: {len(groups)}")

    result: list[AtlasGroupInput] = []
    seen_ids: set[int] = set()
    for group in sorted(groups):
        expected_names = _expected_group_names(mapping_sprites, group)
        actual_names = set(groups[group])
        if actual_names != expected_names:
            _error(
                f"Streamed group is incomplete for {group}: "
                f"missing={sorted(expected_names-actual_names)[:20]} "
                f"extra={sorted(actual_names-expected_names)[:20]}"
            )
        loader = LOADER_GROUP_TABLE[group]
        gm_id = gm_ids.get(loader.gm_enum)
        if gm_id is None or gm_id in seen_ids:
            _error(
                f"Missing/duplicate exact Enums.GM value for {group}: "
                f"{loader.gm_enum}={gm_id}"
            )
        seen_ids.add(gm_id)
        ordered = tuple(
            item.source for item in sorted(
                groups[group].values(),
                key=lambda item: (
                    item.source.index, item.source.alt, item.source.name
                ),
            )
        )
        mask_policy = "forbidden" if loader.plain_shader else "required"
        result.append(
            AtlasGroupInput(
                group=group,
                gm_id=gm_id,
                dash_format=loader.dash_format,
                array_size=array_sizes[group],
                lifetime="map",
                mask_policy=mask_policy,
                material_binding=expected_material_binding(group, mask_policy),
                frames=ordered,
                padding_pixels=1,
                filter_mode=(
                    "Bilinear"
                    if filter_modes is None
                    else filter_modes.get(group, "Bilinear")
                ),
            )
        )
    legacy_paths = tuple(sorted(
        path for path in record_by_path
        if path.casefold().startswith(_ATLAS_PREFIX.casefold())
        or path.casefold().startswith(_SPRITE_PREFIX.casefold())
    ))
    return tuple(result), legacy_paths


def _profile_group_filter_modes(
    profile: Mapping[str, object],
) -> dict[str, str]:
    """Bind the generated atlas sampler to each pinned source texture family."""

    raw_groups = profile.get("gm_atlases")
    if not isinstance(raw_groups, list):
        _error("Profile gm_atlases must be a list for streamed filtering")
    result: dict[str, str] = {}
    for ordinal, raw in enumerate(raw_groups):
        if not isinstance(raw, Mapping):
            _error(f"profile.gm_atlases[{ordinal}] is not an object")
        group = raw.get("gm_file_name")
        source_texture = raw.get("source_texture")
        target_texture = raw.get("target_texture")
        if not isinstance(group, str) or not group:
            _error(f"profile.gm_atlases[{ordinal}] has no group identity")
        if group in result:
            _error(f"Profile repeats streamed filter contract: {group}")
        if not isinstance(source_texture, str) or not isinstance(target_texture, str):
            _error(f"Profile has incomplete texture-family contract: {group}")
        result[group] = (
            "Point"
            if "AllTileSprites" in {source_texture, target_texture}
            else "Bilinear"
        )
    return result


def _copy_exclusive(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with source.open("rb") as incoming, target.open("xb") as outgoing:
            shutil.copyfileobj(incoming, outgoing, length=8 * 1024 * 1024)
            outgoing.flush()
            os.fsync(outgoing.fileno())
    except FileExistsError as exc:
        raise AssetStreamBuildError(f"Stream output collision: {target}") from exc
    if (
        source.stat().st_size != target.stat().st_size
        or sha256_file(source) != sha256_file(target)
    ):
        _error(f"Copied stream output differs from validated Unity bytes: {target}")


def _parse_prepared_contract(
    prepared: PreparedUnityProject,
    groups: Sequence[AtlasGroupInput],
    vanilla_omitted_groups: Sequence[VanillaOmittedGroup],
    index_payload: bytes,
):
    atlas_filename = (
        BC7_ATLAS_ASSET_FILENAME
        if prepared.pipeline_version == 2
        else "atlas.v2.json"
    )
    documents = {
        f"Assets/Generated/Groups/{group_slug(group.group)}/{atlas_filename}":
        (
            prepared.project_path / "Assets" / "Generated" / "Groups"
            / group_slug(group.group) / atlas_filename
        ).read_bytes()
        for group in groups
    }
    if prepared.pipeline_version == 2:
        if vanilla_omitted_groups:
            _error("V2 finalization cannot carry vanilla omissions")
        index = parse_asset_bundle_index_v2(
            index_payload,
            atlas_documents=documents,
            expected_groups=tuple(sorted(group.group for group in groups)),
        )
        build_input = parse_asset_bundle_build_input_v2(
            prepared.build_input_path.read_bytes()
        )
        report = parse_asset_bundle_build_report_v2(
            prepared.report_path.read_bytes(),
            build_input=build_input,
        )
        if (
            report.index_sha256 != index.file_sha256
            or report.quality_report_sha256 != index.quality_report_sha256
        ):
            _error("V2 build report does not bind final index/quality bytes")
        return index, report
    index = parse_asset_bundle_index(
        index_payload,
        atlas_documents=documents,
        expected_groups=tuple(
            sorted(
                [group.group for group in groups]
                + [group.group for group in vanilla_omitted_groups]
            )
        ),
    )
    if index.vanilla_omitted_groups != tuple(vanilla_omitted_groups):
        _error("Final index vanilla omission bindings drifted from preflight")
    report = parse_asset_bundle_build_report(
        prepared.report_path.read_bytes(), index=index
    )
    return index, report


def _stage_stream_outputs(
    mod_root: Path,
    prepared: PreparedUnityProject,
    groups: Sequence[AtlasGroupInput],
    vanilla_omitted_groups: Sequence[VanillaOmittedGroup],
) -> tuple[StreamOutputRecord, ...]:
    index_target = _mod_path(mod_root, INDEX_OUTPUT_PATH, "stream index")
    _copy_exclusive(prepared.index_path.resolve(strict=True), index_target)
    index, report = _parse_prepared_contract(
        prepared, groups, vanilla_omitted_groups, index_target.read_bytes()
    )
    if prepared.pipeline_version == 2:
        index_metadata = {
            "kind": BC7_ATLAS_BACKEND_KIND,
            "schema": index.schema,
            "build_id": index.build_id,
            "group_count": len(index.groups),
            "vanilla_omitted_group_count": len(index.vanilla_omitted_groups),
            "selected_group_count": (
                len(index.groups) + len(index.vanilla_omitted_groups)
            ),
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
    else:
        index_metadata = {
            "kind": ATLAS_BACKEND_KIND,
            "schema": index.schema,
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
    records: list[StreamOutputRecord] = [
        StreamOutputRecord(
            relative_path=INDEX_OUTPUT_PATH,
            category=ASSET_BUNDLE_INDEX_CATEGORY,
            size=index_target.stat().st_size,
            sha256=sha256_file(index_target),
            source_reference=f"unity-assetbundle:{index.build_id}:external-index",
            metadata=index_metadata,
        )
    ]
    artifacts = {artifact.name: artifact for artifact in report.bundles}
    for group in index.groups:
        if not isinstance(group.bundle_path, str):
            _error(f"Final group has no bundle path: {group.group}")
        source = prepared.build_root.joinpath(
            "output", *group.bundle_path.split("/")
        )
        target = _mod_path(mod_root, group.bundle_path, f"bundle {group.group}")
        _copy_exclusive(source, target)
        artifact = artifacts[group.bundle]
        if prepared.pipeline_version == 2:
            if any(
                value is None
                for value in (
                    group.unity_hash128,
                    group.bundle_crc32,
                    group.predicted_load_peak_bytes,
                )
            ):
                _error(f"Final V2 group metadata is incomplete: {group.group}")
            bundle_metadata = {
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
        else:
            bundle_metadata = {
                "kind": ATLAS_BACKEND_KIND,
                "bundle": group.bundle,
                "group": group.group,
                "gm_id": group.gm_id,
                "unity_hash128": group.unity_hash128,
                "crc32": group.bundle_crc32,
                "resident_charge_bytes": group.resident_charge_bytes,
            }
        records.append(
            StreamOutputRecord(
                relative_path=group.bundle_path,
                category=ASSET_BUNDLE_CATEGORY,
                size=target.stat().st_size,
                sha256=sha256_file(target),
                source_reference=(
                    f"unity-assetbundle:{index.build_id}:{group.bundle}"
                ),
                metadata=bundle_metadata,
            )
        )
        if (artifact.size_bytes, artifact.sha256) != (
            records[-1].size, records[-1].sha256
        ):
            _error(f"Staged bundle drifted from Unity report: {group.bundle}")
    if prepared.pipeline_version == 2:
        validate_bundle_output_records_v2(
            index, report, [asdict(record) for record in records]
        )
    else:
        validate_bundle_output_records(
            index, report, [asdict(record) for record in records]
        )
    return tuple(records)


def _remove_exact_legacy(mod_root: Path, legacy_paths: Sequence[str]) -> None:
    expected = set(legacy_paths)
    actual: set[str] = set()
    for prefix in (_ATLAS_PREFIX, _SPRITE_PREFIX):
        root = mod_root.joinpath(*PurePosixPath(prefix.rstrip("/")).parts)
        if not root.exists():
            continue
        resolved = root.resolve(strict=True)
        staging = mod_root.resolve(strict=True)
        if staging not in resolved.parents:
            _error(f"Legacy cleanup escaped staging: {resolved}")
        for path in root.rglob("*"):
            if path.is_symlink():
                _error(f"Legacy cleanup refuses link/junction: {path}")
            if path.is_file():
                actual.add(path.relative_to(mod_root).as_posix())
    if actual != expected:
        _error(
            "Legacy file set differs from OutputRecords: "
            f"missing={sorted(expected-actual)} extra={sorted(actual-expected)}"
        )
    for relative in sorted(expected):
        _mod_path(mod_root, relative, "legacy cleanup").unlink()
    for prefix in (_ATLAS_PREFIX, _SPRITE_PREFIX):
        root = mod_root.joinpath(*PurePosixPath(prefix.rstrip("/")).parts)
        if not root.exists():
            continue
        directories = sorted(
            (path for path in root.rglob("*") if path.is_dir()),
            key=lambda path: len(path.parts),
            reverse=True,
        )
        for directory in directories:
            directory.rmdir()
        root.rmdir()
    # A GM-only streaming canary can leave the common Override parent empty
    # after both eager legacy roots are removed.  The build manifest binds the
    # complete directory set, so remove only that exact, empty, non-link
    # staging parent.  Profiles with any other Override payload keep it.
    override_root = mod_root / "Override"
    if override_root.exists():
        if override_root.is_symlink() or not override_root.is_dir():
            _error(f"Legacy cleanup refuses unsafe Override parent: {override_root}")
        if not any(override_root.iterdir()):
            override_root.rmdir()


def build_asset_stream_backend(
    config: Any,
    mod_root: Path,
    profile: Mapping[str, object],
    mapping: Mapping[str, object],
    output_records: Sequence[Mapping[str, object]],
    *,
    editor_executable: Path | None = None,
) -> AssetStreamBuildResult | None:
    """Build the optional backend; backend absence preserves legacy behavior."""

    try:
        backend = parse_atlas_backend(profile)
    except AssetStreamContractError as exc:
        raise AssetStreamBuildError(f"Invalid atlas_backend contract: {exc}") from exc
    if backend is None:
        return None
    project_root = Path(config.project_root).resolve(strict=True)
    work_dir = Path(config.output.work_dir).resolve(strict=True)
    if work_dir != project_root and project_root not in work_dir.parents:
        _error(f"Configured work directory is outside repository: {work_dir}")
    toolchain = _resolve_toolchain(project_root, editor_executable)
    gm_ids = _read_exact_gm_enum_ids(
        Path(config.target.data_dir) / "Managed" / "Assembly-CSharp.dll"
    )
    # Keep the generated Unity root deliberately short.  The game/repository
    # can live below a long Windows install path and Unity adds another deep
    # project/Assets/Generated tree; the former descriptive directory name
    # pushed valid .meta paths past legacy MAX_PATH before Unity even started.
    # Twelve hex characters retain a 48-bit collision-resistant diagnostic
    # namespace while keeping Unity's deeper Generated/*.meta paths below the
    # legacy Windows MAX_PATH limit.  mkdir(exist_ok=False) still fails closed
    # on the already-improbable collision instead of reusing another run.
    unity_work_root = work_dir / "u" / uuid4().hex[:12]
    unity_work_root.mkdir(parents=True, exist_ok=False)
    try:
        is_v2 = backend.kind == BC7_ATLAS_BACKEND_KIND
        if is_v2:
            selected_groups, legacy_paths = _collect_group_inputs(
                mod_root, mapping, output_records,
                unity_work_root / "frame-inputs", gm_ids,
                filter_modes=_profile_group_filter_modes(profile),
            )
        else:
            selected_groups, legacy_paths = _collect_group_inputs(
                mod_root, mapping, output_records,
                unity_work_root / "frame-inputs", gm_ids,
            )
        editor_source = (
            project_root / "tools" / "unity_asset_bundle"
            / "StrongholdEuropeAssetBundleBuilder.cs"
        )
        if is_v2:
            if backend.texture_policy is None or backend.quality_policy is None:
                _error("V2 backend is missing texture/quality policy bindings")
            acceptance_envelope = (
                _load_frozen_quality_envelope(
                    project_root, backend.quality_policy
                )
                if backend.quality_policy.state == "frozen"
                else None
            )
            incremental = build_incremental_v2_asset_stream(
                project_root=project_root,
                unity_work_root=unity_work_root,
                groups=selected_groups,
                editor_source=editor_source,
                editor_executable=toolchain.executable,
                unity_executable_sha256=toolchain.executable_sha256,
                texture_policy=backend.texture_policy,
                quality_policy=backend.quality_policy,
                acceptance_envelope=acceptance_envelope,
                foliage_groups=tuple(_FOLIAGE_GROUPS),
                fingerprint_factory=_fingerprint_atlas_groups_v2_with_progress,
            )
            prepared = incremental.prepared
            groups = tuple(selected_groups)
            vanilla_omitted_groups: tuple[VanillaOmittedGroup, ...] = ()
        else:
            preflight = preflight_atlas_groups(
                selected_groups, foliage_groups=tuple(_FOLIAGE_GROUPS)
            )
            groups = preflight.groups
            vanilla_omitted_groups = preflight.vanilla_omitted_groups
            prepared = prepare_unity_asset_bundle_project(
                unity_work_root,
                groups,
                vanilla_omitted_groups=vanilla_omitted_groups,
                editor_source=editor_source,
            )
            run_headless_build(
                prepared,
                toolchain.executable,
                timeout_seconds=toolchain.timeout_seconds,
            )
        stream_records = _stage_stream_outputs(
            mod_root, prepared, groups, vanilla_omitted_groups
        )
        removed = set(legacy_paths)
        prospective = [
            record for record in output_records
            if str(record.get("relative_path")) not in removed
        ] + [asdict(record) for record in stream_records]
        index, report = _parse_prepared_contract(
            prepared,
            groups,
            vanilla_omitted_groups,
            (mod_root / Path(INDEX_OUTPUT_PATH)).read_bytes(),
        )
        if is_v2:
            validate_bundle_output_records_v2(index, report, prospective)
        else:
            validate_bundle_output_records(index, report, prospective)
        if any(
            str(record.get("relative_path", "")).casefold().startswith(
                _SPRITE_PREFIX.casefold()
            )
            for record in prospective
        ):
            _error("Prospective stream OutputRecords still contain Override/Sprites")
        _remove_exact_legacy(mod_root, legacy_paths)
        return AssetStreamBuildResult(
            outputs=stream_records,
            removed_relative_paths=legacy_paths,
            build_id=prepared.build_id,
            group_count=len(groups),
            omitted_group_count=len(vanilla_omitted_groups),
            unity_work_root=unity_work_root,
        )
    except AssetStreamBuildError:
        raise
    except (
        AssetStreamContractError,
        GroupCacheError,
        IncrementalV2BuildError,
        UnityAssetBundleError,
    ) as exc:
        raise AssetStreamBuildError(
            f"Streamed GM build failed closed; diagnostics: {unity_work_root}: {exc}"
        ) from exc
    except Exception as exc:
        raise AssetStreamBuildError(
            f"Streamed GM build failed closed; diagnostics: {unity_work_root}: {exc}"
        ) from exc

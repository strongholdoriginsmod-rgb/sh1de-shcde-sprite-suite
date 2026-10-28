from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import subprocess
from typing import Any

from .hashing import sha256_file


class RuntimePrerequisiteError(RuntimeError):
    """Raised when the companion's pinned build/runtime inputs are not exact."""


@dataclass(frozen=True)
class VerifiedRuntimePrerequisite:
    id: str
    roles: tuple[str, ...]
    relative_path: str
    path: Path
    size: int
    sha256: str
    assembly_name: str
    assembly_version: str
    mvid: str


@dataclass(frozen=True)
class RuntimePrerequisiteVerification:
    config_id: str
    runtime_id: str
    target_framework: str
    script_extender_version: str
    game_root: Path
    files: tuple[VerifiedRuntimePrerequisite, ...]


_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "config_id",
        "runtime_id",
        "target_framework",
        "script_extender_version",
        "files",
    }
)
_FILE_KEYS = frozenset(
    {
        "id",
        "roles",
        "relative_path",
        "size",
        "sha256",
        "assembly_name",
        "assembly_version",
        "mvid",
    }
)
_VALID_ROLES = frozenset({"build", "runtime"})
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_ASSEMBLY_VERSION = re.compile(r"[0-9]+(?:\.[0-9]+){1,3}\Z")
_MVID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z"
)

# These identities and paths are part of the reviewed net481 companion design.
# Changing one requires a code/config review rather than silently trusting an
# edited JSON file.
_REQUIRED_DEPENDENCIES: dict[str, tuple[str, str, str, str]] = {
    "shcdese": (
        "BepInEx/plugins/000shcdese/SHCDESE.dll",
        "SHCDESE",
        "2.11.0.0",
        "4b17e151-08fd-463f-9596-415bf3435ca1",
    ),
    "nlua": (
        "BepInEx/plugins/000shcdese/NLua.dll",
        "NLua",
        "1.7.9.0",
        "401e1007-417b-4366-a608-f6b8ffe5ca2e",
    ),
    "keralua": (
        "BepInEx/plugins/000shcdese/KeraLua.dll",
        "KeraLua",
        "1.4.9.0",
        "4ab3a0be-7da2-4255-8556-dcab69a7adc4",
    ),
    # SE 2.x replaced Zhuqiaomon with RedBird (NativePointer<T> etc. now live
    # in RedBird.Core); the companion compiles against it.
    "redbird_core": (
        "BepInEx/plugins/000shcdese/RedBird.Core.dll",
        "RedBird.Core",
        "1.5.0.0",
        "0ca8fc0a-fb1d-4661-b68d-51f2000bad45",
    ),
    "system_memory": (
        "BepInEx/plugins/000shcdese/System.Memory.dll",
        "System.Memory",
        "4.0.5.0",
        "27c7dfb4-b639-4500-8914-8d6e6caca8cb",
    ),
    "bepinex_core": (
        "BepInEx/core/BepInEx.dll",
        "BepInEx",
        "5.4.23.5",
        "d1b92069-86c2-41dc-ad96-bb21eee55a97",
    ),
    "harmony": (
        "BepInEx/core/0Harmony.dll",
        "0Harmony",
        "2.9.0.0",
        "474744d6-5d8e-460f-a08c-d5fd82b5d65f",
    ),
    "r3": (
        "BepInEx/plugins/000shcdese/R3.dll",
        "R3",
        "1.3.1.0",
        "b58e2dc8-2e7f-419e-bf7d-bc9786b1bf15",
    ),
    "assembly_csharp": (
        "Stronghold Crusader Definitive Edition_Data/Managed/Assembly-CSharp.dll",
        "Assembly-CSharp",
        "0.0.0.0",
        "1ad0eaf4-bb64-4eb8-9126-ff328de7f68c",
    ),
    "noesis_gui": (
        "Stronghold Crusader Definitive Edition_Data/Managed/Noesis.NoesisGUI.dll",
        "Noesis.NoesisGUI",
        "0.0.0.0",
        "7383317c-d471-469f-ac85-2aafde4cb013",
    ),
    "unity_engine": (
        "Stronghold Crusader Definitive Edition_Data/Managed/UnityEngine.dll",
        "UnityEngine",
        "0.0.0.0",
        "2098d95a-268b-46a0-9676-e36d11d685a5",
    ),
    "unity_engine_core_module": (
        "Stronghold Crusader Definitive Edition_Data/Managed/UnityEngine.CoreModule.dll",
        "UnityEngine.CoreModule",
        "0.0.0.0",
        "806021f9-55ec-43bb-97cd-1adca41e00da",
    ),
    "unity_engine_asset_bundle_module": (
        "Stronghold Crusader Definitive Edition_Data/Managed/UnityEngine.AssetBundleModule.dll",
        "UnityEngine.AssetBundleModule",
        "0.0.0.0",
        "90538353-7aa0-4a16-ad89-f45382d0c777",
    ),
    "unity_engine_audio_module": (
        "Stronghold Crusader Definitive Edition_Data/Managed/UnityEngine.AudioModule.dll",
        "UnityEngine.AudioModule",
        "0.0.0.0",
        "54f216ae-0646-4f4f-aa73-c4817fcfcede",
    ),
    "unity_engine_image_conversion_module": (
        "Stronghold Crusader Definitive Edition_Data/Managed/UnityEngine.ImageConversionModule.dll",
        "UnityEngine.ImageConversionModule",
        "0.0.0.0",
        "ee44ec0b-022d-49ac-b713-628f3e55be93",
    ),
}


# The managed Unsafe.As/Add adapter must use the same official runtime copy
# as the chosen SE. v3 dynamically verifies this additional 16th dependency;
# original v2 validation remains backward compatible.
_ADAPTIVE_EXTRA_DEPENDENCIES: dict[str, tuple[str, str]] = {
    "unsafe": (
        "BepInEx/plugins/000shcdese/System.Runtime.CompilerServices.Unsafe.dll",
        "System.Runtime.CompilerServices.Unsafe",
    )
}


@dataclass(frozen=True)
class _ExpectedFile:
    id: str
    roles: tuple[str, ...]
    relative_path: str
    size: int
    sha256: str
    assembly_name: str
    assembly_version: str
    mvid: str


def _read_managed_assembly_metadata(path: Path) -> tuple[str, str, str]:
    """Read name, version and MVID without executing assembly code."""

    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if powershell is None:
        raise RuntimePrerequisiteError(
            "PowerShell is required to inspect pinned managed assembly metadata"
        )
    environment = os.environ.copy()
    environment["SEDE_PREREQUISITE_PATH"] = str(path)
    script = (
        "$assembly=[Reflection.Assembly]::ReflectionOnlyLoadFrom("
        "$env:SEDE_PREREQUISITE_PATH);"
        "$identity=$assembly.GetName();"
        "[Console]::Out.Write($identity.Name + \"`t\" + "
        "$identity.Version.ToString() + \"`t\" + "
        "$assembly.ManifestModule.ModuleVersionId.ToString('D').ToLowerInvariant())"
    )
    try:
        completed = subprocess.run(
            [powershell, "-NoProfile", "-NonInteractive", "-Command", script],
            env=environment,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimePrerequisiteError(
            f"Could not inspect managed assembly metadata: {path}"
        ) from exc
    fields = completed.stdout.strip().split("\t")
    if completed.returncode != 0 or len(fields) != 3 or not all(fields):
        diagnostic = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimePrerequisiteError(
            f"Invalid managed assembly metadata for {path}: {diagnostic}"
        )
    name, version, mvid = fields
    if _ASSEMBLY_VERSION.fullmatch(version) is None or _MVID.fullmatch(mvid) is None:
        raise RuntimePrerequisiteError(
            f"Invalid managed assembly identity/MVID for {path}"
        )
    return name, version, mvid


def _require_exact_keys(
    value: Mapping[str, Any],
    expected: frozenset[str],
    label: str,
) -> None:
    keys = set(value)
    missing = sorted(expected - keys)
    extra = sorted(keys - expected)
    if missing or extra:
        raise RuntimePrerequisiteError(
            f"Invalid {label} keys: missing={missing}, extra={extra}"
        )


def _require_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise RuntimePrerequisiteError(f"{label} must be a non-empty string")
    return value


def _relative_path(value: object, label: str) -> str:
    raw = _require_string(value, label)
    if "\\" in raw or "\x00" in raw:
        raise RuntimePrerequisiteError(
            f"{label} must use canonical forward-slash relative syntax"
        )
    parts = raw.split("/")
    windows_path = PureWindowsPath(raw)
    posix_path = PurePosixPath(raw)
    if (
        posix_path.is_absolute()
        or windows_path.is_absolute()
        or bool(windows_path.drive)
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise RuntimePrerequisiteError(f"{label} is not a safe relative path: {raw}")
    return raw


def _expected_files(
    config: Mapping[str, Any], *, adaptive: bool = False
) -> tuple[_ExpectedFile, ...]:
    raw_files = config["files"]
    if not isinstance(raw_files, list) or not raw_files:
        raise RuntimePrerequisiteError("files must be a non-empty list")

    parsed: list[_ExpectedFile] = []
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    for index, raw_entry in enumerate(raw_files):
        label = f"files[{index}]"
        if not isinstance(raw_entry, Mapping):
            raise RuntimePrerequisiteError(f"{label} must be an object")
        _require_exact_keys(raw_entry, _FILE_KEYS, label)

        dependency_id = _require_string(raw_entry["id"], f"{label}.id")
        folded_id = dependency_id.casefold()
        if folded_id in seen_ids:
            raise RuntimePrerequisiteError(f"Duplicate dependency id: {dependency_id}")
        seen_ids.add(folded_id)

        relative_path = _relative_path(
            raw_entry["relative_path"], f"{label}.relative_path"
        )
        folded_path = relative_path.casefold()
        if folded_path in seen_paths:
            raise RuntimePrerequisiteError(
                f"Duplicate dependency path: {relative_path}"
            )
        seen_paths.add(folded_path)

        raw_roles = raw_entry["roles"]
        if not isinstance(raw_roles, list) or not raw_roles:
            raise RuntimePrerequisiteError(f"{label}.roles must be a non-empty list")
        roles = tuple(_require_string(role, f"{label}.roles") for role in raw_roles)
        if len(set(roles)) != len(roles) or not set(roles) <= _VALID_ROLES:
            raise RuntimePrerequisiteError(
                f"{label}.roles must contain unique values from {sorted(_VALID_ROLES)}"
            )

        size = raw_entry["size"]
        if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
            raise RuntimePrerequisiteError(f"{label}.size must be a positive integer")
        digest = _require_string(raw_entry["sha256"], f"{label}.sha256")
        if _SHA256.fullmatch(digest) is None:
            raise RuntimePrerequisiteError(
                f"{label}.sha256 must be a lowercase SHA-256 digest"
            )
        assembly_name = _require_string(
            raw_entry["assembly_name"], f"{label}.assembly_name"
        )
        assembly_version = _require_string(
            raw_entry["assembly_version"], f"{label}.assembly_version"
        )
        if _ASSEMBLY_VERSION.fullmatch(assembly_version) is None:
            raise RuntimePrerequisiteError(
                f"{label}.assembly_version is not a numeric assembly version"
            )
        mvid = _require_string(raw_entry["mvid"], f"{label}.mvid")
        if _MVID.fullmatch(mvid) is None:
            raise RuntimePrerequisiteError(
                f"{label}.mvid must be a lowercase canonical GUID"
            )

        parsed.append(
            _ExpectedFile(
                id=dependency_id,
                roles=roles,
                relative_path=relative_path,
                size=size,
                sha256=digest,
                assembly_name=assembly_name,
                assembly_version=assembly_version,
                mvid=mvid,
            )
        )

    by_id = {entry.id: entry for entry in parsed}
    required = set(_REQUIRED_DEPENDENCIES)
    if adaptive:
        required |= set(_ADAPTIVE_EXTRA_DEPENDENCIES)
    missing = sorted(required - set(by_id))
    if missing:
        raise RuntimePrerequisiteError(
            f"Required companion dependencies are missing: {missing}"
        )
    if adaptive and set(by_id) != required:
        raise RuntimePrerequisiteError(
            "Unexpected adaptive runtime dependencies: "
            + repr(sorted(set(by_id) - required))
        )
    for dependency_id, identity in _ADAPTIVE_EXTRA_DEPENDENCIES.items():
        if not adaptive:
            break
        entry = by_id[dependency_id]
        if (entry.relative_path, entry.assembly_name) != identity:
            raise RuntimePrerequisiteError(
                "Pinned identity mismatch for " + dependency_id
            )
    for dependency_id, identity in _REQUIRED_DEPENDENCIES.items():
        entry = by_id[dependency_id]
        expected_path, expected_name, expected_version, expected_mvid = identity
        actual_identity = (
            entry.relative_path,
            entry.assembly_name,
            entry.assembly_version,
            entry.mvid,
        )
        if (actual_identity[:2] != identity[:2] if adaptive
                else actual_identity != identity):
            raise RuntimePrerequisiteError(
                f"Pinned identity mismatch for {dependency_id}: "
                f"expected={(expected_path, expected_name, expected_version, expected_mvid)!r}, "
                f"actual={actual_identity!r}"
            )
    return tuple(parsed)


def _validated_config(
    config: Mapping[str, Any],
) -> tuple[str, str, str, str, tuple[_ExpectedFile, ...]]:
    if not isinstance(config, Mapping):
        raise RuntimePrerequisiteError("config must be a mapping loaded from JSON")
    _require_exact_keys(config, _TOP_LEVEL_KEYS, "runtime prerequisite config")
    schema = config["schema_version"]
    if isinstance(schema, bool) or schema not in (2, 3):
        raise RuntimePrerequisiteError(
            f"Unsupported runtime prerequisite schema: {schema!r}"
        )
    adaptive = schema == 3
    config_id = _require_string(config["config_id"], "config_id")
    runtime_id = _require_string(config["runtime_id"], "runtime_id")
    target_framework = _require_string(
        config["target_framework"], "target_framework"
    )
    extender_version = _require_string(
        config["script_extender_version"], "script_extender_version"
    )
    if runtime_id != "win-x64":
        raise RuntimePrerequisiteError(
            f"Unsupported companion runtime: {runtime_id!r}; expected 'win-x64'"
        )
    if target_framework != "net481":
        raise RuntimePrerequisiteError(
            f"Unsupported companion target framework: {target_framework!r}; "
            "expected 'net481'"
        )
    if not adaptive and extender_version != "2.11.0":
        raise RuntimePrerequisiteError(
            f"Unsupported historic SHCDE-SE version: {extender_version!r}; "
            "expected '2.11.0'"
        )
    if adaptive:
        version_match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", extender_version)
        if (version_match is None or int(version_match.group(1)) < 2):
            raise RuntimePrerequisiteError(
                "Adaptive native runtime requires RedBird-generation SE 2.x "
                "or newer with a verified interface layout"
            )
        shcdese = next(
            (entry for entry in config["files"]
             if isinstance(entry, Mapping) and entry.get("id") == "shcdese"),
            None,
        )
        if (not isinstance(shcdese, Mapping)
                or shcdese.get("assembly_version") != extender_version + ".0"):
            raise RuntimePrerequisiteError(
                "Adaptive SE version does not match the pinned assembly identity"
            )
    return (
        config_id,
        runtime_id,
        target_framework,
        extender_version,
        _expected_files(config, adaptive=adaptive),
    )


def _nachsicht() -> bool:
    """Standard: Abweichungen vom Referenzstand warnen nur (SEDE_STRENG=1 = streng)."""
    from .gm_atlas import nachsicht_aktiv

    return nachsicht_aktiv()


def verify_runtime_prerequisites(
    config: Mapping[str, Any],
    path: Path | str,
) -> RuntimePrerequisiteVerification:
    """Verify exact net481 companion inputs below an SHCDE game root.

    ``config`` is the decoded contents of ``runtime-prerequisites.json`` and
    ``path`` is the SHCDE game root. The function is read-only and either
    returns one complete immutable verification result or raises
    :class:`RuntimePrerequisiteError`; it never returns partial success.
    """

    (
        config_id,
        runtime_id,
        target_framework,
        extender_version,
        expected_files,
    ) = _validated_config(config)

    try:
        game_root = Path(path).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise RuntimePrerequisiteError(
            f"SHCDE game root does not resolve: {path}"
        ) from exc
    if not game_root.is_dir():
        raise RuntimePrerequisiteError(
            f"SHCDE game root is not a directory: {game_root}"
        )

    # Dynamic schema v3 must always verify exact bytes/MVID, even when the
    # user selected lenient diagnostic mode. A compiler ABI is not a warning.
    adaptive_exact = config["schema_version"] == 3
    verified: list[VerifiedRuntimePrerequisite] = []
    failures: list[str] = []
    warnings: list[str] = []
    for entry in expected_files:
        candidate = game_root.joinpath(*PurePosixPath(entry.relative_path).parts)
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError):
            failures.append(f"{entry.id}: missing file {entry.relative_path}")
            continue
        if game_root not in resolved.parents:
            failures.append(
                f"{entry.id}: resolved path escapes game root: {entry.relative_path}"
            )
            continue
        if not resolved.is_file():
            failures.append(f"{entry.id}: not a regular file: {entry.relative_path}")
            continue

        before = resolved.stat()
        if before.st_size != entry.size:
            message = (
                f"{entry.id}: size mismatch for {entry.relative_path}: "
                f"expected={entry.size} actual={before.st_size}"
            )
            if adaptive_exact or not _nachsicht():
                failures.append(message)
                continue
            warnings.append(message)
        digest = sha256_file(resolved)
        after = resolved.stat()
        stable_identity = (
            before.st_size,
            before.st_mtime_ns,
            getattr(before, "st_ino", None),
        ) == (
            after.st_size,
            after.st_mtime_ns,
            getattr(after, "st_ino", None),
        )
        if not stable_identity:
            failures.append(
                f"{entry.id}: file changed while hashing: {entry.relative_path}"
            )
            continue
        if digest != entry.sha256:
            message = (
                f"{entry.id}: SHA-256 mismatch for {entry.relative_path}: "
                f"expected={entry.sha256} actual={digest}"
            )
            if adaptive_exact or not _nachsicht():
                failures.append(message)
                continue
            warnings.append(message)
        try:
            actual_metadata = _read_managed_assembly_metadata(resolved)
        except RuntimePrerequisiteError as exc:
            failures.append(f"{entry.id}: {exc}")
            continue
        metadata_after = resolved.stat()
        if (
            after.st_size,
            after.st_mtime_ns,
            getattr(after, "st_ino", None),
        ) != (
            metadata_after.st_size,
            metadata_after.st_mtime_ns,
            getattr(metadata_after, "st_ino", None),
        ):
            failures.append(
                f"{entry.id}: file changed while inspecting managed metadata: "
                f"{entry.relative_path}"
            )
            continue
        expected_metadata = (
            entry.assembly_name,
            entry.assembly_version,
            entry.mvid,
        )
        if actual_metadata != expected_metadata:
            message = (
                f"{entry.id}: managed assembly identity/MVID mismatch for "
                f"{entry.relative_path}: expected={expected_metadata!r} "
                f"actual={actual_metadata!r}"
            )
            if adaptive_exact or not _nachsicht():
                failures.append(message)
                continue
            warnings.append(message)
        verified.append(
            VerifiedRuntimePrerequisite(
                id=entry.id,
                roles=entry.roles,
                relative_path=entry.relative_path,
                path=resolved,
                size=after.st_size,
                sha256=digest,
                assembly_name=actual_metadata[0],
                assembly_version=actual_metadata[1],
                mvid=actual_metadata[2],
            )
        )

    for message in warnings:
        print("WARNUNG (Nachsicht): Laufzeitvoraussetzung weicht vom Referenzstand ab - " + message, flush=True)
    if failures:
        raise RuntimePrerequisiteError(
            "Runtime prerequisite verification failed:\n- " + "\n- ".join(failures)
        )
    return RuntimePrerequisiteVerification(
        config_id=config_id,
        runtime_id=runtime_id,
        target_framework=target_framework,
        script_extender_version=extender_version,
        game_root=game_root,
        files=tuple(verified),
    )

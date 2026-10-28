"""Capture exact local managed runtime references for SHCDE-SE 2.x builds.

This replaces obsolete 2.11 hardcoding *during the C# build*, not at game
startup. A native-hook layout is accepted only after validating known measured
struct widths/offsets. An unknown release/layout is never assumed compatible.

The game, SE plugin and game settings remain read-only. No referenced DLL
bytes are included in the project, index, or resulting report.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
from typing import Any, Mapping

from .runtime_prerequisites import (
    _REQUIRED_DEPENDENCIES,
    _ADAPTIVE_EXTRA_DEPENDENCIES,
    _read_managed_assembly_metadata,
    _validated_config,
    RuntimePrerequisiteError,
)


class RuntimeReferenceCaptureError(RuntimePrerequisiteError):
    """The selected local SHCDE / Script Extender ABI could not be proven."""


# These offsets were verified against actual SHCDE-SE DLLs:
# 2.10.4 GameUnit legacy layout; official 2.14.3 refactored layout.
# Other versions may qualify *only* when their actual public structures
# independently pass these strict layouts. Names alone are insufficient.
_INTEROP_PS = r"""
$ErrorActionPreference='Stop'
$assembly=[Reflection.Assembly]::ReflectionOnlyLoadFrom($env:SEDE_INTEROP_SOURCE)
$unit=$assembly.GetType('SHCDESE.Interop.GameUnit',$true)
$resource=$assembly.GetType('SHCDESE.Interop.GamePlayerResources',$true)
if($unit.StructLayoutAttribute.Size -ne 1168 -or
   $resource.StructLayoutAttribute.Size -ne 22588){
 throw 'Unknown native structure sizes'
}
function Member([Type]$type,[string]$name,[string]$expected,[int]$at){
 $field=$type.GetField($name,[Reflection.BindingFlags]'Instance,Public')
 if($null -eq $field -or $field.FieldType.FullName -ne $expected){
  return $false
 }
 return [Runtime.InteropServices.Marshal]::OffsetOf($type,$name).ToInt32() -eq $at
}
$old=(
 (Member $unit 'N000000A7' 'System.UInt16' 672) -and
 (Member $unit 'N0000019A' 'System.UInt32' 668) -and
 (Member $unit 'r_SelectionRelevant3' 'System.UInt16' 852) -and
 (Member $unit 'N000000D0' 'System.UInt16' 1000) -and
 (Member $resource 'r_AISiegePlayerIdTarget' 'System.UInt32' 11224)
)
$modern=(
 (Member $unit 'r_SelectionAllowed' 'System.UInt16' 672) -and
 (Member $unit 'r_IsKilledByProjectile' 'System.UInt16' 668) -and
 (Member $unit 'r_InterestingTodo4MaybeRandomPathing' 'System.UInt16' 670) -and
 (Member $unit 'r_AIObjectiveState' 'System.UInt16' 852) -and
 (Member $unit 'r_ChimpName1' 'System.Byte' 1000) -and
 (Member $resource 'r_SiegeAttackTargetPlayerId' 'System.UInt32' 11224)
)
if($old -and -not $modern){[Console]::Out.Write('legacy')}
elseif($modern -and -not $old){[Console]::Out.Write('modern')}
else{throw 'No reviewed SHCDE-SE native field layout matches'}
"""


def _inside(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise RuntimeReferenceCaptureError("Ungültiger lokaler DLL-Referenzpfad")
    parts = PurePosixPath(relative).parts
    if not parts or ".." in parts or PurePosixPath(relative).is_absolute():
        raise RuntimeReferenceCaptureError("Ungültiger relativer DLL-Pfad")
    raw = root.joinpath(*parts)
    if raw.is_symlink():
        raise RuntimeReferenceCaptureError("Verknüpfte Runtime-Referenz gesperrt")
    try:
        resolved = raw.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise RuntimeReferenceCaptureError(
            "Benötigte Runtime-Assembly fehlt: " + relative
        ) from exc
    if not resolved.is_file() or not resolved.is_relative_to(root):
        raise RuntimeReferenceCaptureError(
            "Runtime-Referenz liegt außerhalb des Zielspiels: " + relative
        )
    return resolved


def attest_native_layout(se_assembly: Path) -> str:
    """Inspect actual native structure sizes/types/offsets, without loading code."""
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if not powershell:
        raise RuntimeReferenceCaptureError("PowerShell ist für den ABI-Check nötig")
    environment = os.environ.copy()
    environment["SEDE_INTEROP_SOURCE"] = str(se_assembly)
    try:
        result = subprocess.run(
            [powershell, "-NoProfile", "-NonInteractive", "-Command", _INTEROP_PS],
            capture_output=True,
            text=True,
            env=environment,
            timeout=25,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeReferenceCaptureError(
            "Native SE-Strukturen können nicht geprüft werden"
        ) from exc
    if result.returncode != 0 or result.stdout.strip() not in {"legacy", "modern"}:
        raise RuntimeReferenceCaptureError(
            "Unbekannte native Script-Extender-Struktur: "
            + (result.stderr.strip() or result.stdout.strip())[:280]
        )
    return result.stdout.strip()


def capture_runtime_references(
    legacy_template: Mapping[str, Any],
    source_root: Path | str,
) -> tuple[dict[str, Any], str]:
    """Create strict schema-v3 pins from *actual* local DLLs and proven ABI.

    The historic config template supplies only allowed paths and roles;
    it cannot insert arbitrary new dependencies. Its old MVID/versions are
    deliberately not used for v3, while exact measured hashes and MVIDs are.
    """
    # Reject a forged or edited historical template before trusting its paths.
    try:
        _validated_config(legacy_template)
    except RuntimePrerequisiteError as exc:
        raise RuntimeReferenceCaptureError(
            "Historische Runtime-Pfadliste wurde verändert"
        ) from exc
    try:
        root = Path(source_root).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise RuntimeReferenceCaptureError("Zielspiel-Referenzen nicht erreichbar") from exc
    if not root.is_dir():
        raise RuntimeReferenceCaptureError("Referenzverzeichnis ist kein Ordner")

    by_id = {x["id"]: x for x in legacy_template["files"]}
    if set(by_id) != set(_REQUIRED_DEPENDENCIES):
        raise RuntimeReferenceCaptureError(
            "Unbekannte oder fehlende Runtime-Referenz-IDs"
        )
    captured: list[dict[str, Any]] = []
    for identity in legacy_template["files"]:
        relative = identity["relative_path"]
        path = _inside(root, relative)
        before = path.stat()
        if before.st_size < 10_000 or before.st_size > 70 * 1024 * 1024:
            raise RuntimeReferenceCaptureError(
                "Ungewöhnliche Runtime-Assembly-Größe: " + relative
            )
        h = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
                h.update(chunk)
        try:
            name, version, mvid = _read_managed_assembly_metadata(path)
        except RuntimePrerequisiteError as exc:
            raise RuntimeReferenceCaptureError(
                "Assembly-Identität nicht lesbar: " + relative
            ) from exc
        after = path.stat()
        if (before.st_size, before.st_mtime_ns, getattr(before, "st_ino", None)) != (
            after.st_size, after.st_mtime_ns, getattr(after, "st_ino", None)
        ):
            raise RuntimeReferenceCaptureError(
                "Runtime-Referenz hat sich beim Lesen verändert: " + relative
            )
        expected_path, expected_name, _, _ = _REQUIRED_DEPENDENCIES[identity["id"]]
        if expected_path != relative or name != expected_name:
            raise RuntimeReferenceCaptureError(
                "Runtime-Assembly-Name/Pfad abweichend: " + relative
            )
        captured.append({
            "id": identity["id"],
            "roles": list(identity["roles"]),
            "relative_path": relative,
            "size": before.st_size,
            "sha256": h.hexdigest(),
            "assembly_name": name,
            "assembly_version": version,
            "mvid": mvid,
        })

    # Unsafe.As/Add is an actual compiled and runtime dependency, not merely
    # a convenient copy next to SHCDESE. Pin its on-disk bytes and MVID as
    # the 16th source identity; never accept a foreign or missing DLL.
    for dependency_id, (relative, expected_name) in (
        _ADAPTIVE_EXTRA_DEPENDENCIES.items()
    ):
        path = _inside(root, relative)
        before = path.stat()
        if before.st_size < 10_000 or before.st_size > 10 * 1024 * 1024:
            raise RuntimeReferenceCaptureError(
                "Unsupported Unsafe-assembly size: " + relative
            )
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
                digest.update(chunk)
        name, version, mvid = _read_managed_assembly_metadata(path)
        after = path.stat()
        if (before.st_size, before.st_mtime_ns, getattr(before, "st_ino", None)) != (
            after.st_size, after.st_mtime_ns, getattr(after, "st_ino", None)
        ):
            raise RuntimeReferenceCaptureError(
                "Unsafe reference changed during capture"
            )
        if name != expected_name:
            raise RuntimeReferenceCaptureError(
                "Expected Unsafe managed assembly identity"
            )
        captured.append({
            "id": dependency_id,
            "roles": ["build", "runtime"],
            "relative_path": relative,
            "size": before.st_size,
            "sha256": digest.hexdigest(),
            "assembly_name": name,
            "assembly_version": version,
            "mvid": mvid,
        })

    extender = next(x for x in captured if x["id"] == "shcdese")
    version_match = re.fullmatch(
        r"(\d+)\.(\d+)\.(\d+)\.0", extender["assembly_version"]
    )
    if version_match is None or int(version_match.group(1)) < 2:
        raise RuntimeReferenceCaptureError(
            "Die native C#-Runtime unterstützt nur geprüfte RedBird-SE-2.x-APIs; "
            "SE 1.x hat eine andere Hook-/Assembly-Generation"
        )
    abi_layout = attest_native_layout(_inside(
        root, _REQUIRED_DEPENDENCIES["shcdese"][0]
    ))
    # A normal game install has these two prerequisites. Avoid building a
    # DLL against an unrelated BepInEx major-generation assembly.
    if not next(x for x in captured if x["id"] == "bepinex_core")[
        "assembly_version"
    ].startswith("5."):
        raise RuntimeReferenceCaptureError("BepInEx-5-API fehlt")

    digest = hashlib.sha256()
    for item in captured:
        digest.update(
            f"{item['id']}\t{item['relative_path']}\t{item['size']}\t"
            f"{item['sha256']}\t{item['assembly_version']}\t{item['mvid']}\n"
            .encode("utf-8")
        )
    config = {
        "schema_version": 3,
        "config_id": "measured-se-abi-" + digest.hexdigest()[:20],
        "runtime_id": "win-x64",
        "target_framework": "net481",
        "script_extender_version": ".".join(version_match.groups()),
        "files": captured,
    }
    return config, abi_layout

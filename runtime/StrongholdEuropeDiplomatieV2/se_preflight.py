"""Read-only SE upgrade gate for an already built Diplomacy DLL.

Only the checker and reports are written, under the project's work directory.
No target assembly is loaded or executed. No download, installation or pin change.
"""
from __future__ import annotations

import argparse
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CHECKER_ROOT = PROJECT_ROOT / "runtime" / "StrongholdEuropeDiplomatieV2.Vertragspruefung"
CHECKER_NAME = "StrongholdEuropeDiplomatieV2.Vertragspruefung"
SCOPE = {
    "checked": "Direct external TypeRef-parent MemberRefs of the supplied mod DLL: field and method signatures.",
    "not_checked": [
        "TypeSpec/ModuleRef-parent references, inherited member resolution, CLR access rules and transitive dependencies",
        "Reflection-only API contracts and native bridge return layouts",
        "Native ABI, RVA, hook implementation, argument roles, struct offsets, thread and stack behaviour",
        "Save/load, combat, UI and gameplay in a running game",
        "Availability or stability of any future Script Extender release",
    ],
    "build_baseline": json.loads((PROJECT_ROOT / "runtime" / "StrongholdEuropeDiplomatieV2" / "extender-pins.json").read_text(encoding="utf-8"))["baseline_version"],
    "upgrade_release_gate": "UNGEPRUEFT: a passing metadata gate alone does not approve an upgrade",
}


def managed_pe(path: Path) -> bool:
    """Read PE/CLI header presence; never import a target DLL."""
    try:
        with path.open("rb") as stream:
            if stream.read(2) != b"MZ":
                return False
            stream.seek(0x3C)
            pe = struct.unpack("<I", stream.read(4))[0]
            stream.seek(pe)
            if stream.read(4) != b"PE\0\0":
                return False
            stream.seek(pe + 20)
            optional_size = struct.unpack("<H", stream.read(2))[0]
            stream.seek(pe + 24)
            magic = struct.unpack("<H", stream.read(2))[0]
            directory = {0x10B: 96, 0x20B: 112}.get(magic)
            if directory is None or optional_size < directory + 15 * 8:
                return False
            stream.seek(pe + 24 + directory - 4)
            if struct.unpack("<I", stream.read(4))[0] < 15:
                return False
            stream.seek(pe + 24 + directory + 14 * 8)
            rva, size = struct.unpack("<II", stream.read(8))
            return rva != 0 and size >= 0x48
    except (OSError, struct.error):
        return False


def file_version(path: Path) -> str | None:
    """Windows VERSIONINFO, explicitly not an AssemblyVersion claim."""
    if os.name != "nt":
        return None
    version = ctypes.windll.version
    unused = ctypes.c_uint32()
    length = version.GetFileVersionInfoSizeW(str(path), ctypes.byref(unused))
    if not length:
        return None
    buffer = ctypes.create_string_buffer(length)
    if not version.GetFileVersionInfoW(str(path), 0, length, buffer):
        return None
    pointer = ctypes.c_void_p()
    size = ctypes.c_uint32()
    if not version.VerQueryValueW(buffer, "\\", ctypes.byref(pointer), ctypes.byref(size)) or size.value < 52:
        return None
    values = ctypes.cast(pointer, ctypes.POINTER(ctypes.c_uint32))
    if values[0] != 0xFEEF04BD:
        return None
    return ".".join(str(part) for part in (
        values[2] >> 16, values[2] & 0xFFFF, values[3] >> 16, values[3] & 0xFFFF))


def fingerprint(path: Path) -> dict:
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": str(path), "bytes": path.stat().st_size,
            "sha256": digest, "windows_file_version": file_version(path)}


def target_files(game: Path, se: Path, extra_dirs: list[Path]) -> tuple[list[Path], list[dict]]:
    if se.name.casefold() != "shcdese.dll" or not managed_pe(se):
        raise ValueError("--se-dll must be a managed file named SHCDESE.dll")
    managed = game / "Stronghold Crusader Definitive Edition_Data" / "Managed"
    core = game / "BepInEx" / "core"
    for required in (managed / "Assembly-CSharp.dll", core / "BepInEx.dll", core / "0Harmony.dll"):
        if not managed_pe(required):
            raise ValueError(f"Required game dependency is missing or not managed: {required}")
    installed_se_dir = game / "BepInEx" / "plugins" / "000shcdese"
    directories = [*extra_dirs, se.parent]
    if installed_se_dir.is_dir():
        directories.append(installed_se_dir)
    directories.extend((core, managed))
    chosen = {"shcdese": se}
    shadowed = []
    for directory in dict.fromkeys(directories):
        if not directory.is_dir():
            raise ValueError(f"Dependency directory is missing: {directory}")
        for path in sorted(directory.glob("*.dll"), key=lambda value: value.name.casefold()):
            path = path.resolve()
            key = path.stem.casefold()
            if not managed_pe(path):
                continue
            if key in chosen:
                if path != chosen[key]:
                    shadowed.append({"selected": str(chosen[key]), "not_selected": str(path)})
            else:
                chosen[key] = path
    targets = sorted(chosen.values(), key=lambda value: value.name.casefold())
    if any(";" in str(path) for path in targets):
        raise ValueError("The existing checker cannot represent semicolons in dependency paths")
    return targets, shadowed


def gate_passed(result: dict, returncode: int) -> bool:
    """The underlying checker permits skips; this wrapper does not."""
    rows = result.get("results", [])
    return (returncode == 0 and result.get("kind") == "member_ref_signatures"
            and result.get("compatible") is True and len(rows) == 1
            and isinstance(result.get("member_refs"), int) and result["member_refs"] > 0
            and rows[0].get("checked") == result["member_refs"]
            and rows[0].get("skipped") == 0 and rows[0].get("missing_count") == 0
            and rows[0].get("missing") == [])


def run_process(command: list[str], cwd: Path, environment: dict, timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(command, cwd=cwd, env=environment, capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False)


def preflight(args: argparse.Namespace) -> tuple[dict, Path]:
    game = args.game_dir.resolve(strict=True)
    mod = args.mod_dll.resolve(strict=True)
    se = (args.se_dll or game / "BepInEx" / "plugins" / "000shcdese" / "SHCDESE.dll").resolve(strict=True)
    if not managed_pe(mod):
        raise ValueError(f"Mod DLL is not a managed PE: {mod}")
    targets, shadowed = target_files(game, se, [path.resolve(strict=True) for path in args.dependency_dir])
    dotnet = (args.dotnet or PROJECT_ROOT / "work" / "toolchains" / "dotnet-10.0.301" / "dotnet.exe").resolve(strict=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8]
    work = (PROJECT_ROOT / "work" / "se-preflight" / run_id).resolve()
    # Also reject a user-supplied game tree situated inside our output tree.
    if work.is_relative_to(game) or mod.is_relative_to(work) or se.is_relative_to(work):
        raise ValueError("Preflight output must be separate from game and artifact inputs")
    work.mkdir(parents=True)
    nuget = work / "NuGet.Config"
    nuget.write_text('<configuration><packageSources><clear /></packageSources></configuration>\n', encoding="utf-8")
    environment = dict(os.environ)
    environment.update(DOTNET_CLI_HOME=str(work / "dotnet-home"),
                       DOTNET_CLI_TELEMETRY_OPTOUT="1", DOTNET_SKIP_FIRST_TIME_EXPERIENCE="1",
                       DOTNET_GENERATE_ASPNET_CERTIFICATE="false", DOTNET_NOLOGO="true",
                       DOTNET_ADD_GLOBAL_TOOLS_TO_PATH="false",
                       DOTNET_ROLL_FORWARD="Major", NUGET_PACKAGES=str(work / "packages"))
    # Compile the existing checker sources in an isolated net10 project. Its
    # checked-in net8 project remains unchanged and needs no downloaded pack.
    source_paths = sorted(CHECKER_ROOT.glob("*.cs"))
    source_before = [fingerprint(path) for path in source_paths]
    project = ET.Element("Project", Sdk="Microsoft.NET.Sdk")
    properties = ET.SubElement(project, "PropertyGroup")
    for key, value in {"OutputType": "Exe", "TargetFramework": "net10.0",
                       "Nullable": "enable", "ImplicitUsings": "disable",
                       "InvariantGlobalization": "true", "EnableDefaultCompileItems": "false",
                       "AssemblyName": CHECKER_NAME, "UseAppHost": "false",
                       "AppendTargetFrameworkToOutputPath": "false"}.items():
        ET.SubElement(properties, key).text = value
    sources = ET.SubElement(project, "ItemGroup")
    for path in source_paths:
        ET.SubElement(sources, "Compile", Include=str(path))
    generated_project = work / "checker.csproj"
    ET.ElementTree(project).write(generated_project, encoding="utf-8", xml_declaration=True)
    build_command = [str(dotnet), "build", str(generated_project),
                     "-c", "Release", "--nologo", "--configfile", str(nuget),
                     "-p:NuGetAudit=false", "-p:OutputPath=" + str(work / "checker" / "bin"),
                     "-p:BaseIntermediateOutputPath=" + str(work / "checker" / "obj") + os.sep]
    build = run_process(build_command, PROJECT_ROOT, environment, 300)
    (work / "checker-build.txt").write_text(build.stdout + build.stderr, encoding="utf-8")
    checker = work / "checker" / "bin" / (CHECKER_NAME + ".dll")
    if build.returncode != 0 or not checker.is_file():
        raise RuntimeError(f"Fresh offline checker build failed; see {work / 'checker-build.txt'}")
    inputs = [mod, *targets]
    inputs += [path for path in (game / "CrusaderDE.dll", game / "Stronghold Crusader Definitive Edition.exe")
               if path.is_file() and path not in inputs]
    before = {str(path): fingerprint(path) for path in inputs}
    command = [str(dotnet), str(checker), "--signaturen", str(mod),
               "candidate=" + ";".join(str(path) for path in targets)]
    checked = run_process(command, PROJECT_ROOT, environment, 120)
    (work / "checker-stdout.json").write_text(checked.stdout, encoding="utf-8")
    (work / "checker-stderr.txt").write_text(checked.stderr, encoding="utf-8")
    try:
        result = json.loads(checked.stdout)
    except json.JSONDecodeError:
        result = {}
    changed = [str(path) for path in inputs if fingerprint(path) != before[str(path)]]
    source_changed = source_before != [fingerprint(path) for path in source_paths]
    passed = gate_passed(result, checked.returncode) and not changed and not source_changed
    report = {"schema": 1, "utc": datetime.now(timezone.utc).isoformat(),
              "managed_memberref_gate": "PASS" if passed else "FAIL",
              "game_dir": str(game), "mod_dll": str(mod), "se_dll": str(se),
              "scope": SCOPE, "checker": fingerprint(checker),
              "checker_sources": source_before, "checker_sources_changed_during_check": source_changed,
              "generated_checker_project": fingerprint(generated_project),
              "build_command": build_command, "check_command": command,
              "checker_exit_code": checked.returncode, "checker_result": result,
              "inputs": list(before.values()), "inputs_changed_during_check": changed,
              "dependency_precedence": "Explicit SE; then --dependency-dir in order; SE parent; installed SE; core; Managed",
              "shadowed_dependencies": shadowed}
    report_path = work / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report, report_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-dir", type=Path, required=True)
    parser.add_argument("--mod-dll", type=Path, required=True, help="Already built mod artifact; never rebuilt by this command")
    parser.add_argument("--se-dll", type=Path, help="Optional alternate SHCDESE.dll; its sibling dependencies take priority over installed SE")
    parser.add_argument("--dependency-dir", type=Path, action="append", default=[], help="Additional dependency directory; earlier arguments take priority")
    parser.add_argument("--dotnet", type=Path, help="Local .NET 10 SDK executable; defaults to the project's pinned SDK")
    args = parser.parse_args(argv)
    try:
        report, path = preflight(args)
        print(f"Managed MemberRef gate: {report['managed_memberref_gate']}")
        print(f"Report: {path}")
        print("Native ABI, hook layouts, reflection bridges and in-game behaviour remain UNGEPRUEFT.")
        return 0 if report["managed_memberref_gate"] == "PASS" else 1
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"Preflight could not complete: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

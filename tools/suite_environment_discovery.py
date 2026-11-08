"""Read-only SpriteSuite environment discovery. Findings are hints, never release attestation.

Does not execute discovered binaries, crawl drives, install software or modify
saved configuration. Explicit game roots and Steam libraries are both supported.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sys

from suite_toolchain_inventory import (
    safe as _safe_path, unity_editors, preferred_unity, python_interpreters,
)

GAME_DATA = {
    "sh1de": "Stronghold 1 Definitive Edition_Data",
    "shcde": "Stronghold Crusader Definitive Edition_Data",
}
GAME_NAMES = {
    "sh1de": ("Stronghold 1 Definitive Edition",),
    "shcde": ("Stronghold Crusader Definitive Edition",),
}
GAME_ENV = {
    "sh1de": "SPRITESUITE_SH1DE",
    "shcde": "SPRITESUITE_SHCDE",
}
EXTENDER_DIR = Path("BepInEx/plugins/000shcdese")
_CAPABILITY_RELATIVE = Path("config/studio-runtime-capabilities-20261108.json")
_RUNTIME_PINS = Path("config/runtime-prerequisites.json")
_NATIVE_BASELINE = "fbcb93195fc7efca9bdac5204852efdd76f9818f59a6711750d77c9cef2831e2"
_API_RELEASE = "0.27.0"
_API_SE_MIN = "2.14.0"
_RUNTIME_FILE_PATHS = {
    "bepinex_core": "BepInEx/core/BepInEx.dll",
    "shcdese": "BepInEx/plugins/000shcdese/SHCDESE.dll",
    "api_shared": "BepInEx/plugins/APIShared_Serp/APIShared.dll",
    "api_shared_content": "BepInEx/plugins/APIShared_Serp/APIShared.Content.dll",
    "assembly_csharp": "Stronghold Crusader Definitive Edition_Data/Managed/Assembly-CSharp.dll",
    "native_game": "Stronghold Crusader Definitive Edition_Data/Plugins/x86_64/CrusaderDE.dll",
}
_VERSION_TRIPLE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")



def _parse_libraries(steam: Path) -> list[Path]:
    paths = [steam]
    vdf = steam / "steamapps" / "libraryfolders.vdf"
    if not vdf.is_file() or vdf.is_symlink() or vdf.stat().st_size > 512_000:
        return paths
    try:
        raw = vdf.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        return paths
    for item in re.findall(r'"path"\s*"([^"\r\n]+)"', raw, re.I)[:32]:
        path = _safe_path(item.replace("\\\\", "\\"))
        if path is not None:
            paths.append(path)
    return paths


def _roots(environment: dict[str, str], extra: list[str | Path]) -> list[tuple[Path, str]]:
    observed: list[tuple[Path, str]] = []
    for value in extra[:40]:
        if (path := _safe_path(value)) is not None:
            observed.append((path, "explicit"))
    for kind, variable in GAME_ENV.items():
        if environment.get(variable):
            if (path := _safe_path(environment[variable])) is not None:
                observed.append((path, variable))
    steam_locations = []
    for variable in ("ProgramFiles(x86)", "ProgramFiles", "PROGRAMFILES(X86)"):
        if environment.get(variable):
            steam_locations.append(Path(environment[variable]) / "Steam")
    if environment.get("SPRITESUITE_STEAM_ROOT"):
        steam_locations.append(Path(environment["SPRITESUITE_STEAM_ROOT"]))
    for steam in steam_locations[:8]:
        if (valid := _safe_path(steam)) is None:
            continue
        for library in _parse_libraries(valid):
            for kind, names in GAME_NAMES.items():
                for name in names:
                    observed.append((library / "steamapps" / "common" / name, "steam"))
    unique = {}
    for path, source in observed:
        unique.setdefault(os.path.normcase(str(path)), (path, source))
    return list(unique.values())[:160]


def _game_candidate(path: Path, source: str) -> dict | None:
    if not path.is_dir() or _safe_path(path) is None:
        return None
    for kind, data_name in GAME_DATA.items():
        root = path.parent if path.name.casefold() == data_name.casefold() else path
        data = root / data_name
        if _safe_path(data) is None or not (data / "resources.assets").is_file():
            continue
        result = {
            "kind": kind, "root": str(root), "data_dir": str(data),
            "source": source, "structural_match": True,
            "game_version_verified": False,
            "runtime_compatibility_verified": False,
        }
        if kind == "shcde":
            plugins = root / EXTENDER_DIR
            info_file = plugins / "info.json"
            version = None
            if (_safe_path(info_file) is not None and info_file.is_file()
                    and info_file.stat().st_size <= 65_536):
                try:
                    info = json.loads(info_file.read_text(encoding="utf-8"))
                    if info.get("GUID") == "000shcdese":
                        version = str(info.get("Version", ""))[:64] or None
                except (UnicodeError, OSError, ValueError, TypeError):
                    pass
            result["script_extender"] = {
                "installed": (plugins / "SHCDESE.dll").is_file()
                             and _safe_path(plugins / "SHCDESE.dll") is not None,
                "declared_version": version,
                "abi_verified": False,
            }
            plugin_root = root / "BepInEx" / "plugins"
            components = {"APIShared": [], "Serp": []}
            if plugin_root.is_dir() and _safe_path(plugin_root) is not None:
                for candidate in list(plugin_root.iterdir())[:256]:
                    if _safe_path(candidate) is None:
                        continue
                    files = [candidate] if candidate.is_file() else (
                        list(candidate.iterdir())[:128] if candidate.is_dir() else [])
                    for file in files:
                        if _safe_path(file) is None or not file.is_file():
                            continue
                        for component in components:
                            if component.casefold() in file.name.casefold() and file.suffix.lower() == ".dll":
                                components[component].append(str(file))
            result["components"] = components
        return result
    return None


def _version(value: object) -> tuple[int, int, int] | None:
    m = _VERSION_TRIPLE.fullmatch(value) if isinstance(value, str) else None
    return tuple(int(part) for part in m.groups()) if m else None


def _read_capability_snapshot(project: Path) -> dict:
    """The external research snapshot is a version pin, not installed API proof."""
    path = project / _CAPABILITY_RELATIVE
    if not path.is_file():
        return {"status": "NO_LOCAL_SNAPSHOT", "api_shared": _API_RELEASE,
                "script_extender_minimum": _API_SE_MIN,
                "native_baseline_sha256": _NATIVE_BASELINE}
    if _safe_path(path) is None or path.stat().st_size > 32_768:
        raise ValueError("Unsafe or oversized SpriteSuite capability snapshot")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        api, serp = raw["api_shared"], raw["serp"]
        if (raw["schema"] != "sprite-suite.runtime-capability-snapshot.v1"
                or api["release"] != _API_RELEASE
                or api["minimum_script_extender"] != _API_SE_MIN
                or api["plugin_guid"] != "APIShared_Serp"
                or serp["native_dll_sha256"] != _NATIVE_BASELINE):
            raise ValueError("unexpected research version or native baseline pin")
    except (ValueError, UnicodeError, TypeError, KeyError) as exc:
        raise ValueError("Capability snapshot changed; explicit ABI/source review required") from exc
    return {"status": "RESEARCH_SNAPSHOT_ONLY", "api_shared": _API_RELEASE,
            "script_extender_minimum": _API_SE_MIN,
            "native_baseline_sha256": _NATIVE_BASELINE,
            "source_commit": api["source_commit"]}


def _runtime_pin_entries(project: Path) -> dict[str, dict]:
    manifest = project / _RUNTIME_PINS
    if _safe_path(manifest) is None or not manifest.is_file() or manifest.stat().st_size > 128_000:
        return {}
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        rows = payload.get("files", [])
        if not isinstance(rows, list):
            return {}
        return {row["id"]: row for row in rows if isinstance(row, dict)
                and isinstance(row.get("sha256"), str)
                and isinstance(row.get("size"), int)
                and row.get("relative_path") in _RUNTIME_FILE_PATHS.values()}
    except (ValueError, TypeError, OSError, KeyError):
        return {}


def _file_evidence(root: Path, relative: str, pin: dict | None) -> dict:
    """Hash a fixed allow-listed DLL path with stable before/after stat; no PE load."""
    file = root.joinpath(*relative.split("/"))
    item = {"relative_path": relative, "size_bytes": None, "sha256": None,
            "expected_sha256": pin.get("sha256") if pin else None,
            "state": "MISSING", "assembly_signature_verified": False}
    if _safe_path(file) is None:
        item["state"] = "LINKED_OR_NONCANONICAL"
        return item
    if not file.is_file():
        return item
    try:
        first = file.stat()
        if first.st_size <= 0 or first.st_size > 64 * 1024 * 1024:
            item["state"] = "OUT_OF_BOUNDS"
            return item
        digest = sha256()
        with file.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        after = file.stat()
        if (first.st_size, first.st_mtime_ns, getattr(first, "st_ino", 0)) != (
                after.st_size, after.st_mtime_ns, getattr(after, "st_ino", 0)):
            item["state"] = "CHANGED_WHILE_HASHING"
            return item
        item["size_bytes"] = after.st_size
        item["sha256"] = digest.hexdigest()
        if not pin:
            item["state"] = "FOUND_UNPINNED"
        elif after.st_size == pin["size"] and digest.hexdigest() == pin["sha256"]:
            item["state"] = "SOURCE_PIN_BYTE_MATCH"
        else:
            item["state"] = "SOURCE_PIN_MISMATCH"
    except OSError:
        item["state"] = "UNREADABLE"
    return item


def runtime_evidence(game: dict, project: Path, snapshot: dict) -> dict:
    """Separate source pin, SE/APIShared prerequisites and live QA gates."""
    root = Path(game["root"])
    pins = _runtime_pin_entries(project)
    files = {}
    for name, relative in _RUNTIME_FILE_PATHS.items():
        pin = pins.get(name)
        if pin and pin.get("relative_path") != relative:
            pin = None
        files[name] = _file_evidence(root, relative, pin)
    se = game["script_extender"]["declared_version"]
    api_info = root / "BepInEx/plugins/APIShared_Serp/info.json"
    api_version = None
    if _safe_path(api_info) is not None and api_info.is_file():
        try:
            if api_info.stat().st_size <= 65_536:
                manifest = json.loads(api_info.read_text(encoding="utf-8"))
                if isinstance(manifest, dict) and manifest.get("GUID") == "APIShared_Serp":
                    declared = manifest.get("Version")
                    api_version = declared if _version(declared) else None
        except (ValueError, TypeError, OSError, UnicodeError):
            pass
    problems = []
    if files["shcdese"]["state"] == "SOURCE_PIN_MISMATCH":
        problems.append("Existing SpriteSuite runtime is pinned to another Script Extender binary")
    if files["api_shared"]["state"] == "MISSING":
        problems.append("APIShared.dll is missing; no shared feature can be claimed")
    if files["api_shared_content"]["state"] == "MISSING":
        problems.append("APIShared.Content.dll is missing; shared package is incomplete")
    if (api_version and api_version != _API_RELEASE):
        problems.append("Installed APIShared declaration does not match the reviewed 0.27.0 source")
    if (files["api_shared"]["state"] != "MISSING" and
            _version(se) and _version(se) < _version(_API_SE_MIN)):
        problems.append("APIShared 0.27 requires Script Extender >=2.14.0")
    for name, data in files.items():
        if data["state"] in {"CHANGED_WHILE_HASHING", "LINKED_OR_NONCANONICAL",
                             "UNREADABLE", "OUT_OF_BOUNDS", "SOURCE_PIN_MISMATCH"}:
            problems.append(name + ": " + data["state"])
    source_pin_ids = [name for name in files if files[name]["expected_sha256"]]
    exact_source_pins = bool(source_pin_ids) and all(
        files[name]["state"] == "SOURCE_PIN_BYTE_MATCH" for name in source_pin_ids
    )
    native_match = files["native_game"]["sha256"] == _NATIVE_BASELINE
    return {
        "status": "BLOCKED" if problems else "REVIEW",
        "source_snapshot": snapshot, "source_pin_file": _RUNTIME_PINS.as_posix(),
        "verified_source_pin_bytes": exact_source_pins,
        "native_baseline_exact_byte_match": native_match,
        "script_extender_declared_version": se,
        "api_shared_declared_version": api_version,
        "api_shared_target": _API_RELEASE,
        "api_shared_minimum_script_extender": _API_SE_MIN,
        "files": files, "blocking_reasons": sorted(set(problems)),
        "metadata_signatures_verified": False, "runtime_abi_verified": False,
        "interop_hooks_verified": False, "in_game_qa_verified": False,
        "performed_live_injection": False,
    }


def discover(project: Path, *, roots: list[str | Path] | None = None,
             environment: dict[str, str] | None = None) -> dict:
    """Inventory only: detecting a file is not proof of safe runtime hooks."""
    env = dict(os.environ) if environment is None else environment
    candidates = _roots(env, roots or [])
    # Existing explicit saved setup is a hint, never write it back.
    try:
        from stronghold_europe_de.suite_setup import read_game_path_hints, inspect_toolchain_hints
        hints, warnings = read_game_path_hints(project)
        chain, chain_warnings = inspect_toolchain_hints(project)
    except (ImportError, OSError, ValueError):
        hints, warnings, chain, chain_warnings = {}, (), {}, ()
    for kind in ("source", "target"):
        if hints.get(kind) and (p := _safe_path(hints[kind])) is not None:
            candidates.insert(0, (p, "saved_config"))
    found = {}
    for path, source in candidates:
        row = _game_candidate(path, source)
        if row:
            key = (row["kind"], os.path.normcase(row["root"]))
            found.setdefault(key, row)
    games = sorted(found.values(), key=lambda r: (r["kind"], r["root"].casefold()))
    source_snapshot = _read_capability_snapshot(Path(project))
    for row in games:
        if row["kind"] == "shcde":
            row["runtime_capabilities"] = runtime_evidence(row, Path(project), source_snapshot)
    suggestions = {}
    for kind in GAME_DATA:
        matches = [row for row in games if row["kind"] == kind]
        suggestions[kind] = matches[0]["root"] if len(matches) == 1 else None
    from stronghold_europe_de.sdk_toolchain import (
        find_dotnet_sdk, resolve_dotnet_directory, installed_sdk_versions,
    )
    editors = unity_editors(env, chain.get("unity_editor"))
    unity = preferred_unity(editors)
    sdk_candidates = []
    for source, value in (
        ("saved_config", chain.get("dotnet_directory")),
        ("auto_discovery", find_dotnet_sdk(project)),
    ):
        if not value or not (path := _safe_path(value)):
            continue
        try:
            root = resolve_dotnet_directory(path)
            versions = installed_sdk_versions(root)
            if versions and not any(x["path"] == str(root) for x in sdk_candidates):
                sdk_candidates.append({"path": str(root), "source": source,
                    "sdk_versions": list(versions), "executed": False})
        except (OSError, ValueError, RuntimeError):
            continue
    dotnet = sdk_candidates[0]["path"] if sdk_candidates else None
    python_candidates = python_interpreters(project, env)
    return {
        "schema": "sprite-suite.environment-discovery.v2",
        "games": games, "suggestions": suggestions,
        "unity_editor": unity, "unity_candidates": editors,
        "dotnet_directory": dotnet, "dotnet_candidates": sdk_candidates,
        "python_executables": [r["path"] for r in python_candidates],
        "python_candidates": python_candidates,
        "python_current_version": sys.version.split()[0],
        "warnings": list(warnings) + list(chain_warnings),
        "capability_source_snapshot": source_snapshot,
        "automatic_install": False, "executed_discovered_binaries": False,
        "modified_game_or_config": False, "release_attested": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--game-root", type=Path, action="append", default=[])
    args = parser.parse_args(argv)
    print(json.dumps(discover(args.project, roots=args.game_root), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Read-only SpriteSuite environment discovery. Findings are hints, never release attestation.

Does not execute discovered binaries, crawl drives, install software or modify
saved configuration. Explicit game roots and Steam libraries are both supported.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys

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


def _safe_path(value: str | Path) -> Path | None:
    """Reject junctions/reparse points rather than follow installed-game links."""
    try:
        path = Path(value).expanduser().absolute()
        for part in (path, *path.parents):
            if not part.exists():
                continue
            if part.is_symlink():
                return None
            flags = getattr(part.lstat(), "st_file_attributes", 0)
            if flags & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
                return None
        return path
    except (ValueError, OSError, RuntimeError):
        return None


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
    suggestions = {}
    for kind in GAME_DATA:
        matches = [row for row in games if row["kind"] == kind]
        suggestions[kind] = matches[0]["root"] if len(matches) == 1 else None
    from stronghold_europe_de.sdk_toolchain import find_dotnet_sdk
    from stronghold_europe_de.unity_toolchain import standard_unity_editor_paths
    unity_candidates = [chain.get("unity_editor"), env.get("STRONGHOLD_EUROPE_UNITY_EDITOR")]
    unity_candidates += [str(p) for p in standard_unity_editor_paths("2021.3.45f2")]
    unity = next((str(p) for v in unity_candidates if v
                  if (p := _safe_path(v)) and p.is_file() and p.name.lower() == "unity.exe"), None)
    dotnet = None
    if chain.get("dotnet_directory") and (p := _safe_path(chain["dotnet_directory"])) and p.exists():
        dotnet = str(p)
    if not dotnet:
        sdk = find_dotnet_sdk(project)
        dotnet = str(sdk) if sdk else None
    python_paths = []
    for raw in (sys.executable, shutil.which("python"), shutil.which("python3")):
        if raw and (p := _safe_path(raw)) and p.is_file() and str(p) not in python_paths:
            python_paths.append(str(p))
    return {
        "schema": "sprite-suite.environment-discovery.v1",
        "games": games, "suggestions": suggestions,
        "unity_editor": unity, "dotnet_directory": dotnet,
        "python_executables": python_paths,
        "python_current_version": sys.version.split()[0],
        "warnings": list(warnings) + list(chain_warnings),
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

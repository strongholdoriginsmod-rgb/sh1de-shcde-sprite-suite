#!/usr/bin/env python3
"""Build an optional, read-only real-game SHCDE building and unit inspector.

The compiler reads actual installed BepInEx/SHCDESE/Unity ABI assemblies.
No version whitelist, gameplay state write, game process spawn or engine
patch is performed. Installation is an explicit separate command.
"""
from __future__ import annotations

import argparse
from collections import Counter
from shcde_managed_builder import compile_managed, _plugin_directory, _component
from suite_windows_paths import is_link_or_reparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "runtime" / "SpriteSuite.ShcdeInspector" / "SpriteSuiteInspector.cs"
DLL_NAME = "SpriteSuite.ShcdeInspector.dll"
PLUGIN_NAME = "SpriteSuiteShcdeInspector"
DEFAULT_CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework" / "v4.0.30319" / "csc.exe"
REFERENCES = (
    "BepInEx/core/BepInEx.dll",
    "BepInEx/plugins/000shcdese/SHCDESE.dll",
    "Stronghold Crusader Definitive Edition_Data/Managed/Assembly-CSharp.dll",
    "Stronghold Crusader Definitive Edition_Data/Managed/UnityEngine.dll",
    "Stronghold Crusader Definitive Edition_Data/Managed/UnityEngine.CoreModule.dll",
)
OPTIONAL = (
    "BepInEx/plugins/000shcdese/RedBird.Core.dll",
    "BepInEx/core/RedBird.Core.dll",
    "Stronghold Crusader Definitive Edition_Data/Managed/netstandard.dll",
)
CONFIG = (
    "# Editable runtime inspector settings; no gameplay values are changed.\n"
    "buildings=true\nunits=true\ninterval_frames=180\nmax_reports=10000\n"
    "max_buildings=512\nmax_units=512\nglobal_id=0\n"
)
RECEIPT = "sprite-suite-inspector-receipt.json"


def checksum(file: Path) -> str:
    hash_ = hashlib.sha256()
    with file.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hash_.update(chunk)
    return hash_.hexdigest()


def compile_inspector(game: Path, output: Path, csc: Path = DEFAULT_CSC) -> dict:
    result = compile_managed(game, SOURCE, Path(output) / DLL_NAME, csc=csc)
    return {**result, "readOnly": True, "inGameExecuted": False}



def install_inspector(game: Path, source: Path) -> dict:
    target = _plugin_directory(game, PLUGIN_NAME)
    if target.exists():
        raise FileExistsError("Inspector mod already exists; no files replaced")
    target.mkdir(parents=True, exist_ok=False)
    metadata = {
        "GUID": "org.spritesuite.shcde.inspector",
        "Name": "SpriteSuite SHCDE Object Inspector",
        "Author": "SpriteSuite",
        "Version": "0.1.0",
        "Description": "Read-only building and unit runtime snapshots",
        "Manifest": 1, "NetworkMode": 1,
    }
    try:
        files = {
            DLL_NAME: source.read_bytes(),
            "info.json": (json.dumps(metadata, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
            "inspector.ini": CONFIG.encode("utf-8"),
        }
        for name, content in files.items():
            with (target / name).open("xb") as stream:
                stream.write(content)
        receipt = {
            "schema": "spritesuite.shcde.inspector-install.v1",
            "readOnly": True, "gameBuildRestricted": False,
            "files": {name: checksum(target / name) for name in files},
        }
        with (target / RECEIPT).open("x", encoding="utf-8") as stream:
            json.dump(receipt, stream, indent=2)
        return {"installed": str(target), "dllSHA256": receipt["files"][DLL_NAME]}
    except BaseException:
        for name in (DLL_NAME, "info.json", "inspector.ini", RECEIPT):
            (target / name).unlink(missing_ok=True)
        target.rmdir()
        raise


def remove_inspector(game: Path) -> dict:
    target = _plugin_directory(game, PLUGIN_NAME)
    receipt_path = target / RECEIPT
    if is_link_or_reparse(receipt_path):
        raise ValueError("Linked inspector receipt")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8-sig"))
    if receipt.get("schema") != "spritesuite.shcde.inspector-install.v1":
        raise ValueError("Unknown installer receipt")
    files = receipt.get("files")
    if not isinstance(files, dict):
        raise ValueError("Invalid inspector file inventory")
    for name in files:
        _component(name)
        if is_link_or_reparse(target / name):
            raise ValueError("Linked installed inspector file")
    names = {p.name for p in target.iterdir()}
    if names != set(files) | {RECEIPT}:
        raise ValueError("Unknown file in inspector directory")
    for name, expected in files.items():
        if checksum(target / name) != expected:
            raise ValueError("Inspector changed after install: " + name)
    for name in files:
        (target / name).unlink()
    receipt_path.unlink()
    target.rmdir()
    return {"removed": str(target), "otherGameFilesModified": False}


def parse_log(path: Path) -> dict:
    events = []
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        if "SHCDE_INSPECT|" not in line:
            continue
        record = {}
        for field in line.split("SHCDE_INSPECT|", 1)[1].split("|"):
            if "=" in field:
                key, value = field.split("=", 1)
                record[key] = value
        events.append(record)
    counts = Counter(entry.get("event") for entry in events)
    return {"source": str(path), "sha256": checksum(Path(path)),
            "events": dict(counts),
            "buildings": len({v.get("global_id") for v in events
                              if v.get("event") == "building"}),
            "units": len({v.get("global_id") for v in events
                          if v.get("event") == "unit"}),
            "errors": [v for v in events if v.get("event") == "read_error"],
            "spriteChangesVerified": False,
            "gameStateWriteClaimed": False}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    group = p.add_subparsers(dest="action", required=True)
    build = group.add_parser("build")
    build.add_argument("--game", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--install", action="store_true")
    build.add_argument("--csc", type=Path, default=DEFAULT_CSC)
    remove = group.add_parser("remove")
    remove.add_argument("--game", type=Path, required=True)
    report = group.add_parser("log")
    report.add_argument("--file", type=Path, required=True)
    args = p.parse_args(argv)
    try:
        if args.action == "build":
            result = compile_inspector(args.game, args.output, csc=args.csc)
            if args.install:
                result.update(install_inspector(args.game, Path(result["dll"])))
        elif args.action == "remove":
            result = remove_inspector(args.game)
        else:
            result = parse_log(args.file)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as err:
        print("SHCDE object inspector: " + str(err), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

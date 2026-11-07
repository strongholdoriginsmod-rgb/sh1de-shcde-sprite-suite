#!/usr/bin/env python3
"""Build or install the optional HP/fire-dependent SHCDE building sprite runtime.

Creative graphics, project versions, game folders and mod metadata are
user-selected. The installer expands the standard SpriteSuite damage ZIP so
Unity's Mono runtime never requires System.IO.Compression.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "runtime" / "StrongholdEuropeDE.BuildingDamage.LiveMod" / "build_windows.ps1"
DEFAULT_OUTPUT = ROOT / "work" / "hp-fire-runtime-build"
DLL_NAME = "SpriteSuite.BuildingDamage.Live.dll"


def sha256_file(path: Path) -> str:
    hash_ = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            hash_.update(chunk)
    return hash_.hexdigest()


def command(game_root: Path, output: Path, *, install: bool = False,
            damage_archive: Path | None = None,
            runtime_config: Path | None = None,
            powershell: str = "powershell.exe") -> list[str]:
    cmd = [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass",
           "-File", str(BUILDER), "-GameRoot", str(game_root),
           "-Output", str(output)]
    if install:
        cmd.append("-Install")
    if damage_archive:
        cmd.extend(["-DamageArchive", str(damage_archive)])
    if runtime_config:
        cmd.extend(["-RuntimeConfig", str(runtime_config)])
    return cmd


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-root", type=Path, required=True,
                        help="Existing SHCDE game folder, chosen by the modder")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                        help="Workspace directory for the compiled DLL")
    parser.add_argument("--install", action="store_true",
                        help="Install into the explicitly selected game folder")
    parser.add_argument("--damage-archive", type=Path,
                        help="Your SpriteSuite HP damage ZIP, extracted on install")
    parser.add_argument("--runtime-config", type=Path,
                        help="Your own sprite-to-building mapping runtime.json")
    args = parser.parse_args(argv)
    try:
        if not BUILDER.is_file():
            raise FileNotFoundError(BUILDER)
        process = subprocess.run(
            command(args.game_root, args.output, install=args.install,
                    damage_archive=args.damage_archive,
                    runtime_config=args.runtime_config),
            text=True, encoding="utf-8", errors="replace",
            capture_output=True, check=False,
            timeout=240)
        if process.stdout:
            print(process.stdout.rstrip())
        if process.stderr:
            print(process.stderr.rstrip(), file=sys.stderr)
        if process.returncode != 0:
            return process.returncode
        dll = args.output / DLL_NAME
        if not dll.is_file():
            print("Compiler completed without creating a DLL.", file=sys.stderr)
            return 2
        result = {
            "compiledDLL": str(dll),
            "sha256": sha256_file(dll),
            "gameRoot": str(args.game_root),
            "installed": bool(args.install),
            "creativeStageApprovalsRequired": False,
            "gameBuildVersionRestrictions": False,
            "dynamicHpAndFireSupported": True,
            "nativeVisualGameQAProved": False,
        }
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (OSError, subprocess.TimeoutExpired) as error:
        print("HP/Fire runtime build failed: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

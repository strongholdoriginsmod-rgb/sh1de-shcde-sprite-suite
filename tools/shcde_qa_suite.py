#!/usr/bin/env python3
"""Reproducible QA runner for SpriteSuite SHCDE workbench and installed game SDK.

Never alters game originals, installs plugins, rewrites test fixtures, or
presents a compile-only result as in-game verification. Full-suite execution
is opt-in because GUI/game tests have separate prerequisites.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
QUICK = [
    "tests/shcde/test_expansion.py",
    "tests/sandbox/test_suite_tool_policy.py",
    "tests/sandbox/test_suite_tool_inventory.py",
]
FULL = [
    "tests/runtime/test_building_damage_render_evidence.py",
    "tests/runtime/test_building_damage_live_qa.py",
    "tests/sandbox/test_se_asset_package.py",
    "tests/sandbox/test_suite_unified_project.py",
]


def run_check(command: list[str], cwd: Path, *, timeout: int = 120) -> dict:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(filter(None, (
        str(ROOT / "tools"), str(ROOT / "src"),
        environment.get("PYTHONPATH", ""))))
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        done = subprocess.run(command, cwd=cwd, capture_output=True,
                              env=environment,
                              text=True, errors="replace", timeout=timeout, check=False)
        return {"command": command, "returncode": done.returncode,
                "passed": done.returncode == 0,
                "stdoutTail": "\n".join(done.stdout.splitlines()[-25:]),
                "stderrTail": "\n".join(done.stderr.splitlines()[-25:])}
    except subprocess.TimeoutExpired:
        return {"command": command, "returncode": None, "passed": False,
                "reason": "test_timeout"}
    except OSError as exc:
        return {"command": command, "returncode": None, "passed": False,
                "reason": str(exc)}


def run_qa(*, project: Path | None = None, archive: Path | None = None,
           game: Path | None = None, full: bool = False,
           include_pytest: bool = True) -> dict:
    checks: list[dict] = []
    if project is not None:
        from shcde_mod_project import inspect_project
        try:
            result = inspect_project(project)
            checks.append({"name": "project_assets", "passed":
                not result["assetIntegrityIssues"] and not result["externalSourceIssues"],
                "result": result})
        except (OSError, ValueError) as err:
            checks.append({"name": "project_assets", "passed": False, "error": str(err)})
    if archive is not None:
        from shcde_mod_composer import inspect
        try:
            result = inspect(archive)
            checks.append({"name": "mod_zip_crc", "passed": not result["integrityErrors"],
                           "result": {"sha256": result["sha256"],
                                      "integrityErrors": result["integrityErrors"]}})
        except (OSError, ValueError) as err:
            checks.append({"name": "mod_zip_crc", "passed": False, "error": str(err)})
    if game is not None:
        from shcde_api_native_index import get_installed_assemblies, sha256
        try:
            references = get_installed_assemblies(game)
            checks.append({
                "name": "game_sdk_dlls",
                "passed": True,
                "references": [{"name": p.name, "sha256": sha256(p)} for p in references],
                "gameProcessStarted": False,
            })
        except (OSError, ValueError) as err:
            checks.append({"name": "game_sdk_dlls", "passed": False, "error": str(err)})
    if include_pytest:
        tests = [str(ROOT / t) for t in QUICK if (ROOT / t).is_file()]
        if full:
            tests += [str(ROOT / t) for t in FULL if (ROOT / t).is_file()]
        if tests:
            test = run_check([sys.executable, "-m", "pytest", "-q",
                              "-p", "no:cacheprovider", *tests], ROOT,
                             timeout=360 if full else 120)
            test["name"] = "pytest"
            checks.append(test)
        else:
            checks.append({"name": "pytest", "passed": False,
                           "reason": "No test sources available"})
    return {
        "schema": "spritesuite.shcde.qa-suite.v1",
        "checks": checks,
        "passed": bool(checks) and all(check.get("passed") for check in checks),
        "gameInstalledModsChanged": False,
        "runtimeGameCompatibilityProved": False,
        "visualInGameAbnahmeProved": False,
        "requiredManualGates": ["Actual game rendering", "Multi-peer/host-client synchronization"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path)
    parser.add_argument("--mod-zip", type=Path)
    parser.add_argument("--game", type=Path)
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--skip-pytest", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    result = run_qa(project=args.project, archive=args.mod_zip,
                    game=args.game, full=args.full,
                    include_pytest=not args.skip_pytest)
    encoded = json.dumps(result, ensure_ascii=False, indent=2)
    if args.report:
        with args.report.open("x", encoding="utf-8") as target:
            target.write(encoded + "\n")
    print(encoded)
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

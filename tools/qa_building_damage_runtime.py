#!/usr/bin/env python3
"""Reproduce the SHCDE damage-library -> read-only C# contract in a temporary folder.

No game access, no installation, no network, no permanent build output.
Requires Python 3.11+, Node and the Windows .NET Framework C# compiler.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime" / "BuildingDamageOffline"
TESTS = ROOT / "tests" / "runtime"
TOOLS = ROOT / "tools"


def available_csc(path: str | None) -> Path:
    if path:
        candidate = Path(path)
    else:
        known = Path(r"C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe")
        candidate = known if known.is_file() else Path(shutil.which("csc") or "")
    if not candidate.is_file():
        raise RuntimeError("C#-Compiler fehlt. Keine Spiel-DLL wird als Ersatz verwendet.")
    return candidate


def run(command: list[str], cwd: Path, label: str) -> str:
    process = subprocess.run(command, cwd=cwd, capture_output=True, text=True,
                             errors="replace", timeout=90, check=False)
    if process.returncode:
        tail = "\n".join((process.stdout + process.stderr).splitlines()[-18:])
        raise RuntimeError(f"{label}: exit {process.returncode}\n{tail}")
    return (process.stdout + process.stderr).strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csc", help="Expliziter C#-Compilerpfad")
    args = parser.parse_args(argv)
    try:
        node = shutil.which("node")
        if not node:
            raise RuntimeError("Node.js fehlt.")
        csc = available_csc(args.csc)
        result = {"status": "passed", "gameModified": False,
                  "apiCalls": False, "rendererHookInstalled": False,
                  "checks": []}
        def mark(name: str):
            result["checks"].append(name)
        with tempfile.TemporaryDirectory(prefix="shcde_building_damage_qa_") as temp:
            folder = Path(temp)
            package = folder / "building-damage-example.zip"
            prepare = folder / "read-only-preview"
            table = prepare / "building-damage-candidate.tsv"
            selection = folder / "selector.exe"
            observer = folder / "read-only-observer.exe"

            logs = run([sys.executable, "-m", "unittest", "discover", "-s",
                        str(TESTS), "-p", "test_building_damage_runtime_preflight.py", "-q"],
                       ROOT, "Python-Preflight-Test")
            count = re.search(r"Ran (\d+) tests?", logs)
            if not count or int(count.group(1)) < 18 or "OK" not in logs:
                raise RuntimeError("Python-Preflight-Tests enthalten keine vollständige Abnahme.")
            mark(count.group(1) + " Python-Preflight-Regressionen")

            built = run([node, str(TESTS / "building_damage_export_fixture.cjs"),
                         str(package)], ROOT, "SpriteSuite-Export")
            exported = json.loads(built.splitlines()[-1])
            if exported["stages"] != 2 or exported["files"] < 50:
                raise RuntimeError("Sprite-Editor-Export enthält nicht beide Schadenspfade.")
            mark("SpriteSuite erzeugt reale 5x5-Tile-Bibliothek")

            run([sys.executable, str(TOOLS / "building_damage_runtime_preflight.py"),
                 "--package", str(package), "--prepare", "--output", str(prepare)],
                ROOT, "Preflight/TSV-Erzeugung")
            preflight = json.loads((prepare / "building-damage-preflight.json").read_text(encoding="utf-8"))
            if (preflight.get("runtimeHookInstalled") is not False or
                preflight.get("inGameTested") is not False or
                preflight.get("rendererMappingValidated") is not False or
                preflight.get("mappedTypes") != [108] or
                preflight.get("unboundApprovedStages")):
                raise RuntimeError("Unverifiziertes Renderer- oder Spielmapping wurde als erfolgreich behauptet.")
            if "\r" in table.read_text(encoding="utf-8"):
                raise RuntimeError("Kandidaten-TSV enthält nicht-normalisierte Zeilenenden.")
            mark("ZIP/PNG/SHA-256-Paket validiert; nur read-only TSV ausgegeben")

            compile_select = [str(csc), "/nologo", "/target:exe",
                              "/out:" + str(selection),
                              str(RUNTIME / "BuildingDamageStageSelector.cs"),
                              str(RUNTIME / "BuildingDamageProfileTable.cs"),
                              str(TESTS / "building_damage_selector_harness.cs")]
            run(compile_select, ROOT, "Offline-C#-Selector-Kompilation")
            log = run([str(selection), str(table), str(package)], ROOT,
                      "C#-Paket-/HP-Selektor")
            count = re.search(r"(\d+) assertions", log)
            if not count or int(count.group(1)) < 56:
                raise RuntimeError("C#-Selektor führte nicht alle Assertions aus.")
            mark(count.group(1) + " C#-Selector-/TSV-/ZIP-Assertions")

            compile_probe = [str(csc), "/nologo",
                             "/define:SHCDE_BUILDING_DAMAGE_READONLY_API",
                             "/target:exe", "/out:" + str(observer),
                             str(RUNTIME / "BuildingDamageStageSelector.cs"),
                             str(RUNTIME / "BuildingDamageReadOnlyProbe.cs"),
                             str(RUNTIME / "BuildingDamageGameBuildingSource.cs"),
                             str(TESTS / "building_damage_probe_harness.cs")]
            run(compile_probe, ROOT, "Opt-in-API-Adapter-Kompilation")
            log = run([str(observer)], ROOT, "API-Adapter/ReadOnly-Probe")
            count = re.search(r"(\d+) assertions", log)
            if not count or int(count.group(1)) < 29:
                raise RuntimeError("API-Adapter-Testabdeckung ist nicht vollständig.")
            mark(count.group(1) + " Read-only-Building-API-Assertions")

        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print("QA nicht bestanden: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

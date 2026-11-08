#!/usr/bin/env python3
"""Offline explorer for installed Script Extender/APIShared and Serp native baseline.

Assembly metadata is read by Mono.Cecil, never loaded or executed. Native RVA
claims are always accompanied by their exact baseline DLL fingerprint; an RVA
is not a version-independent hook address. All input locations are editable.
"""
from __future__ import annotations

import argparse
from collections import Counter
from tempfile import TemporaryDirectory
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PROBE_SOURCE = Path(__file__).with_name("shcde_api_probe.cs")
DEFAULT_CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework" / "v4.0.30319" / "csc.exe"
MARKER = "SHCDESE.dll"
BASELINE_NAMES = frozenset({
    "function-claims.jsonl", "hook-spans.jsonl", "api-contracts.jsonl",
    "native-field-catalog.json", "managed-native-links.jsonl",
    "xaml-index.jsonl", "functions.jsonl", "xrefs.jsonl",
    "chore-opcodes.jsonl", "chore-contracts.jsonl",
})


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def get_installed_assemblies(game: Path) -> list[Path]:
    plugins = Path(game) / "BepInEx" / "plugins"
    if not plugins.is_dir():
        raise FileNotFoundError("Missing BepInEx/plugins: " + str(plugins))
    extender = plugins / "000shcdese" / MARKER
    if not extender.is_file():
        raise FileNotFoundError("Missing installed SHCDESE.dll: " + str(extender))
    files = [extender]
    for item in plugins.rglob("APIShared.dll"):
        if item.is_file() and not item.is_symlink():
            files.append(item)
    return sorted(set(files), key=lambda path: (path.name.lower() != "shcdese.dll", str(path).casefold()))


def _compilation_args(csc: Path, cecil: Path, exe: Path) -> list[str]:
    return [str(csc), "/nologo", "/target:exe", "/optimize+",
            "/out:" + str(exe), "/reference:" + str(cecil),
            str(PROBE_SOURCE)]


def probe_assemblies(assemblies: list[Path], game: Path | None = None,
                     *, csc: Path = DEFAULT_CSC, cecil: Path | None = None,
                     public_only: bool = True,
                     name_filter: str = "", limit: int = 2000) -> dict:
    if not assemblies:
        raise ValueError("No assemblies selected")
    if not csc.is_file() or not PROBE_SOURCE.is_file():
        raise FileNotFoundError("C# compiler or bundled metadata probe missing")
    if cecil is None:
        if game is None:
            raise ValueError("Select a game directory or Mono.Cecil.dll")
        cecil = Path(game) / "BepInEx" / "core" / "Mono.Cecil.dll"
    if not cecil.is_file():
        raise FileNotFoundError("Missing Mono.Cecil.dll: " + str(cecil))
    checked = [Path(p).resolve(strict=True) for p in assemblies]
    for file in checked:
        if not file.is_file():
            raise ValueError("Not a managed DLL: " + str(file))
    with TemporaryDirectory(prefix="spritesuite_api_catalog_") as temporary:
        where = Path(temporary)
        exe = where / "SpriteSuiteCecilProbe.exe"
        built = subprocess.run(_compilation_args(csc, cecil, exe),
                               capture_output=True, text=True, errors="replace",
                               timeout=120, check=False)
        if built.returncode:
            raise RuntimeError("Cecil probe compiler error: " +
                               "\n".join((built.stdout + built.stderr).splitlines()[-12:]))
        # .NET's assembly loader resolves the Cecil reference beside the EXE.
        shutil.copy2(cecil, where / cecil.name)
        read = subprocess.run([str(exe), *map(str, checked)],
                              capture_output=True, text=True,
                              errors="replace", timeout=120, check=False)
        if read.returncode:
            raise RuntimeError("Metadata probe failed: " +
                               "\n".join((read.stderr or read.stdout).splitlines()[-15:]))
    result: list[dict] = []
    total = Counter()
    needle = name_filter.casefold()
    for line in read.stdout.splitlines():
        parts = line.split("\t")
        if not parts or parts[0] not in ("A", "T", "M", "F"):
            continue
        kind = {"A": "assembly", "T": "type", "M": "method", "F": "field"}[parts[0]]
        total[kind] += 1
        if parts[0] in ("M", "F") and len(parts) >= 6:
            row = {"kind": kind, "assembly": parts[1], "declaringType": parts[2],
                   "name": parts[3], "returnOrFieldType": parts[4]}
            if parts[0] == "M":
                row["parameters"] = parts[5]
                row["visibility"] = parts[6] if len(parts) > 6 else ""
            else:
                row["visibility"] = parts[5]
        elif parts[0] == "T" and len(parts) >= 4:
            row = {"kind": kind, "assembly": parts[1], "name": parts[2],
                   "visibility": parts[3]}
        elif parts[0] == "A" and len(parts) >= 3:
            row = {"kind": kind, "assembly": parts[1], "name": parts[2],
                   "visibility": "public"}
        else:
            continue
        if public_only and row.get("visibility") == "other":
            continue
        if needle and needle not in " ".join(str(x) for x in row.values()).casefold():
            continue
        if len(result) < limit:
            result.append(row)
    native = None
    if game is not None:
        # The engine's native binaries may be in multiple Unity build layouts.
        candidates = list((Path(game) / "Stronghold Crusader Definitive Edition_Data" / "Plugins").rglob("CrusaderDE.dll"))
        if candidates:
            native = {"path": str(candidates[0]), "sha256": sha256(candidates[0])}
    return {
        "schema": "spritesuite.shcde.api-index.v1",
        "sourceAssemblies": [
            {"name": path.name, "sha256": sha256(path), "bytes": path.stat().st_size}
            for path in checked
        ],
        "gameNativeBinary": native,
        "managedCodeExecuted": False,
        "gameStarted": False,
        "totalDeclarations": dict(total),
        "matches": result,
        "matchesTruncated": len(result) == limit,
    }


def baseline_identity(root: Path) -> dict:
    current = Path(root) / "CURRENT.md"
    if not current.is_file():
        # The documented Serp baseline is often nested under _inspect.
        current = Path(root) / "_inspect" / "CrusaderDE-Native-Baseline" / "CURRENT.md"
    if not current.is_file():
        return {"available": False, "reason": "CURRENT.md not found"}
    contents = current.read_text(encoding="utf-8-sig", errors="replace")
    match = re.search(r"Current canonical DLL SHA-256:\s*[\r\n]+[\r\n]*\x60?([0-9A-Fa-f]{64})", contents)
    return {"available": True, "source": str(current),
            "canonicalDLLSHA256": match.group(1).lower() if match else None}


def _baseline_files(root: Path) -> list[Path]:
    base = Path(root)
    if (base / "_inspect" / "CrusaderDE-Native-Baseline").is_dir():
        base = base / "_inspect" / "CrusaderDE-Native-Baseline"
    return sorted((p for p in base.rglob("*") if p.is_file() and
                   p.name in BASELINE_NAMES),
                  key=lambda path: str(path).casefold())


def _matches_record(obj: object, needle: str) -> bool:
    if not needle:
        return True
    try:
        return needle in json.dumps(obj, ensure_ascii=False).casefold()
    except (TypeError, UnicodeError):
        return False


def query_baseline(root: Path, needle: str, *,
                   limit: int = 100, max_rows: int = 500000,
                   full_record: bool = False) -> dict:
    identity = baseline_identity(root)
    files = _baseline_files(root)
    if not files:
        return {**identity, "schema": "spritesuite.shcde.native-baseline.v1",
                "filesScanned": [], "matches": [], "rowsScanned": 0,
                "message": "Select a local Serp native baseline directory containing JSONL exports."}
    matches = []
    rows = 0
    errors = []
    for file in files:
        with file.open("r", encoding="utf-8-sig", errors="replace") as source:
            if file.suffix.lower() == ".json":
                try:
                    records = json.load(source)
                except ValueError as exc:
                    errors.append(str(file) + ": " + str(exc)[:150])
                    continue
                if not isinstance(records, list):
                    records = [records]
            else:
                records = source
            for number, entry in enumerate(records, 1):
                if rows >= max_rows:
                    break
                rows += 1
                try:
                    record = json.loads(entry) if isinstance(entry, str) else entry
                except ValueError:
                    errors.append(str(file) + ":" + str(number) + ": bad JSONL")
                    continue
                if _matches_record(record, needle.casefold()) and len(matches) < limit:
                    value = record if full_record else json.dumps(record, ensure_ascii=False)[:950]
                    matches.append({"file": str(file), "line": number,
                                    "record": value, "nativeHash": identity.get("canonicalDLLSHA256"),
                                    "verifiedForOtherVersions": False})
        if rows >= max_rows:
            break
    return {"schema": "spritesuite.shcde.native-baseline.v1", **identity,
            "filesScanned": [str(f) for f in files], "rowsScanned": rows,
            "limitReached": rows >= max_rows, "matches": matches,
            "parseErrors": errors[:50],
            "memoryPatchProposed": False}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    commands = p.add_subparsers(dest="action", required=True)
    managed = commands.add_parser("api")
    managed.add_argument("--game", type=Path)
    managed.add_argument("--assembly", type=Path, action="append")
    managed.add_argument("--cecil", type=Path)
    managed.add_argument("--csc", type=Path, default=DEFAULT_CSC)
    managed.add_argument("--query", default="")
    managed.add_argument("--limit", type=int, default=250)
    managed.add_argument("--all-declarations", action="store_true")
    baseline = commands.add_parser("native")
    baseline.add_argument("--baseline-root", type=Path, required=True)
    baseline.add_argument("--query", required=True)
    baseline.add_argument("--limit", type=int, default=80)
    baseline.add_argument("--max-rows", type=int, default=500000)
    baseline.add_argument("--full", action="store_true")
    args = p.parse_args(argv)
    try:
        if args.action == "api":
            assemblies = list(args.assembly or [])
            if args.game:
                assemblies = get_installed_assemblies(args.game) + assemblies
            result = probe_assemblies(assemblies, args.game, csc=args.csc,
                                      cecil=args.cecil, name_filter=args.query,
                                      limit=args.limit,
                                      public_only=not args.all_declarations)
        else:
            result = query_baseline(args.baseline_root, args.query,
                                    limit=args.limit, max_rows=args.max_rows,
                                    full_record=args.full)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print("SpriteSuite API/Native: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

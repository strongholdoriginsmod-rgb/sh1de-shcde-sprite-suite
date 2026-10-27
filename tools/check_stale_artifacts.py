"""Report `dist/` artifacts whose runtime DLL is older than the runtime source.

A `dist/` tree keeps whatever DLL it was built with. Installing such a tree
reproduces the old runtime behaviour exactly, which makes a stale artifact look
like a live defect — or worse, makes an already-fixed defect look unfixed.

That is not hypothetical. On 2026-08-09 the `gm-atlas-slice` runtime report was
the only failing gate in the project. Its artifact had been built at 19:29:32 on
08-08; the foliage fix landed 23 minutes later. Rebuilding and rerunning turned
79 checks green without a single source change.

Usage::

    python tools/check_stale_artifacts.py           # report, exit 1 if any stale
    python tools/check_stale_artifacts.py --quiet   # only the summary line

Run it before `install`.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNTIME_SOURCE = REPO_ROOT / "runtime" / "StrongholdEuropeDE.Runtime"
DIST = REPO_ROOT / "dist"
RUNTIME_DLL = Path("StrongholdEuropeDE") / "StrongholdEuropeDE.Runtime.dll"
SOURCE_SUFFIXES = {".cs", ".csproj", ".json"}


def newest_runtime_source() -> tuple[Path, float]:
    candidates = [
        path
        for path in RUNTIME_SOURCE.rglob("*")
        if path.is_file()
        and path.suffix in SOURCE_SUFFIXES
        and "obj" not in path.parts
        and "bin" not in path.parts
    ]
    if not candidates:
        raise SystemExit(f"No runtime sources found below {RUNTIME_SOURCE}")
    newest = max(candidates, key=lambda path: path.stat().st_mtime)
    return newest, newest.stat().st_mtime


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quiet", action="store_true", help="print only the summary")
    args = parser.parse_args(argv)

    newest, source_mtime = newest_runtime_source()
    if not args.quiet:
        print(
            f"Newest runtime source: {newest.name} "
            f"({datetime.fromtimestamp(source_mtime):%Y-%m-%d %H:%M:%S})\n"
        )

    stale: list[str] = []
    current: list[str] = []
    for profile_dir in sorted(p for p in DIST.iterdir() if p.is_dir()) if DIST.is_dir() else []:
        dll = profile_dir / RUNTIME_DLL
        if not dll.is_file():
            continue
        mtime = dll.stat().st_mtime
        label = "STALE" if mtime < source_mtime else "current"
        (stale if mtime < source_mtime else current).append(profile_dir.name)
        if not args.quiet:
            print(
                f"  [{label:>7}] {profile_dir.name:<32}"
                f"{datetime.fromtimestamp(mtime):%Y-%m-%d %H:%M:%S}  "
                f"{dll.stat().st_size:>8} bytes"
            )

    if not args.quiet:
        print()
    if stale:
        print(
            f"{len(stale)} stale runtime artifact(s): {', '.join(stale)}. "
            "Rebuild before installing, or the run proves the old behaviour."
        )
        return 1
    print(f"No stale runtime artifacts ({len(current)} checked).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

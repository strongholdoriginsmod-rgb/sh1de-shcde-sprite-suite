#!/usr/bin/env python3
"""Read-only inventory of Git worktrees, local edits, refs, stashes and reflogs.

No working-tree content is copied. Optional JSON output must be a NEW file.
Pass each independent repository once; linked worktrees are discovered from Git.
This inventories currently reachable evidence, not vanished untracked files.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import subprocess

MAX_HASH_BYTES = 32 * 1024 * 1024
MAX_RECORDS = 30000


def git(repo: Path, *args: str, raw: bool = False) -> str | bytes:
    command = ["git", "-C", str(repo), "-c", "core.quotepath=false", *args]
    result = subprocess.run(command, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, check=False)
    if result.returncode:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(f"Git failed in {repo}: {message[:300]}")
    if raw:
        return result.stdout
    return result.stdout.decode("utf-8", errors="replace")


def worktrees(repo: Path) -> list[dict]:
    result: list[dict] = []
    current: dict = {}
    for line in git(repo, "worktree", "list", "--porcelain").splitlines():
        if not line:
            if current:
                result.append(current)
            current = {}
        elif line.startswith("worktree "):
            current["path"] = line[9:]
        elif line.startswith("HEAD "):
            current["head"] = line[5:]
        elif line.startswith("branch "):
            current["branch"] = line[7:].removeprefix("refs/heads/")
        elif line.startswith("detached"):
            current["detached"] = True
        elif line.startswith("prunable"):
            current["prunable"] = True
    if current:
        result.append(current)
    return result


def changed_paths(tree: Path) -> list[dict]:
    """Parse NUL-delimited porcelain including renamed files and Unicode."""
    raw = git(tree, "status", "--porcelain=v1", "-z", "--untracked-files=all", raw=True)
    fields = raw.split(b"\x00")
    if len(fields) > MAX_RECORDS * 2:
        raise ValueError(f"Too many changes to audit safely: {tree}")
    records = []
    pos = 0
    while pos < len(fields):
        item = fields[pos]
        pos += 1
        if not item:
            break
        if len(item) < 4 or item[2:3] != b" ":
            raise ValueError(f"Unexpected Git porcelain record in {tree}")
        status = item[:2].decode("ascii", errors="replace")
        path = item[3:].decode("utf-8", errors="replace")
        former = None
        if "R" in status or "C" in status:
            if pos >= len(fields):
                raise ValueError("Incomplete Git rename record")
            former = fields[pos].decode("utf-8", errors="replace")
            pos += 1
        itempath = tree / path
        record = {"status": status, "path": path}
        if former is not None:
            record["formerPath"] = former
        if itempath.is_symlink():
            record["kind"] = "symlink"
        elif itempath.is_file():
            size = itempath.stat().st_size
            record["kind"] = "file"
            record["bytes"] = size
            if size <= MAX_HASH_BYTES:
                with itempath.open("rb") as handle:
                    checksum = sha256()
                    for block in iter(lambda: handle.read(1024 * 1024), b""):
                        checksum.update(block)
                record["sha256"] = checksum.hexdigest()
            else:
                record["hashSkipped"] = "size-exceeds-32MiB"
        elif itempath.is_dir():
            record["kind"] = "directory"
        else:
            record["kind"] = "deleted-or-unreadable"
        record["group"] = classify(path)
        records.append(record)
    return records


def classify(name: str) -> str:
    lower = name.replace("\\", "/").casefold()
    basename = lower.rsplit("/", 1)[-1]
    if basename.startswith(".") and basename.endswith(".tmp"):
        return "temporary"
    if lower.startswith("runtime/") or lower.endswith(".cs"):
        return "runtime"
    if lower.startswith("tests/"):
        return "tests"
    if lower.startswith("docs/"):
        return "documentation"
    if lower.startswith(("assets/", "backgrounds/")):
        return "assets"
    if lower.startswith(("config/", "profiles/")):
        return "profiles"
    if lower.startswith(("tools/", "src/")):
        return "suite-source"
    return "other"


def inspect_repository(repo: Path) -> dict:
    repo = repo.resolve()
    top = Path(git(repo, "rev-parse", "--show-toplevel").strip())
    all_worktrees = worktrees(top)
    branches = []
    for line in git(top, "for-each-ref", "--format=%(refname:short)|%(objectname)",
                    "refs/heads").splitlines():
        if "|" in line:
            name, head = line.split("|", 1)
            branches.append({"branch": name, "head": head})
    refs_count = int(git(top, "rev-list", "--count", "--all").strip())
    recent_reflog = git(top, "reflog", "--all", "--format=%H").splitlines()
    active_reflog_commits = len(set(recent_reflog))
    stash = git(top, "stash", "list", "--format=%gd|%H").splitlines()
    inspected = []
    for item in all_worktrees:
        location = Path(item["path"])
        if not location.is_dir():
            inspected.append({**item, "available": False})
            continue
        files = changed_paths(location)
        inspected.append({**item, "available": True, "statusCount": len(files),
                          "groups": dict(sorted(Counter(f["group"] for f in files).items())),
                          "changes": files})
    return {"repository": str(top), "branches": branches,
            "branchCount": len(branches), "reachableCommits": refs_count,
            "reflogCommitCount": active_reflog_commits, "stashes": stash,
            "worktrees": inspected, "worktreeCount": len(inspected)}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", type=Path, action="append", required=True)
    p.add_argument("--out", type=Path, help="Optional new JSON evidence file")
    args = p.parse_args(argv)
    reports = []
    seen = set()
    for repo in args.repo:
        top = Path(git(repo, "rev-parse", "--show-toplevel").strip()).resolve()
        key = str(top).casefold()
        if key in seen:
            continue
        seen.add(key)
        reports.append(inspect_repository(top))
    report = {
        "schema": "sprite-suite.workstream-census.v1",
        "capturedUTC": datetime.now(timezone.utc).isoformat(),
        "scopeNote": "Git worktrees and currently reachable refs/reflogs/stashes; "
                     "deleted untracked content and unmounted historical disks are not recoverable.",
        "repositories": reports,
    }
    overview = {
        "repos": len(reports),
        "worktrees": sum(item["worktreeCount"] for item in reports),
        "uncommittedRecords": sum(t.get("statusCount", 0)
                                  for item in reports for t in item["worktrees"]),
        "branches": sum(item["branchCount"] for item in reports),
        "outputsContainFileContents": False,
    }
    report["summary"] = overview
    if args.out:
        dest = args.out.resolve(strict=False)
        if dest.exists() or dest.is_symlink():
            raise ValueError("Audit output exists: refusing overwrite")
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        print(json.dumps(overview, ensure_ascii=False))
        print("AUDIT_JSON=" + str(dest))
    else:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

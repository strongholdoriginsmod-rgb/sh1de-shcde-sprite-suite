"""Offline census tests with a disposable Git repository only."""
from __future__ import annotations

from pathlib import Path
import subprocess

import qa_workstream_census as census


def command(root, *args):
    subprocess.run(["git", "-C", str(root), *args],
                   check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def test_census_reads_dirty_files_branches_and_history_without_writing(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    command(repo, "init", "-q")
    command(repo, "config", "user.name", "QA")
    command(repo, "config", "user.email", "qa@example.invalid")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    command(repo, "add", "README.md")
    command(repo, "commit", "-qm", "initial")
    (repo / "README.md").write_text("revised\n", encoding="utf-8")
    (repo / "Änderung.txt").write_text("unique content", encoding="utf-8")
    before = census.git(repo, "status", "--porcelain=v1", "-z", raw=True)
    report = census.inspect_repository(repo)
    assert report["branchCount"] == 1
    assert report["reachableCommits"] == 1
    assert report["stashes"] == []
    assert report["worktreeCount"] == 1
    records = report["worktrees"][0]["changes"]
    by_name = {item["path"]: item for item in records}
    assert set(by_name) == {"README.md", "Änderung.txt"}
    assert all(item["sha256"] for item in records)
    assert by_name["Änderung.txt"]["status"] == "??"
    assert by_name["README.md"]["status"] == " M"
    after = census.git(repo, "status", "--porcelain=v1", "-z", raw=True)
    assert before == after


def test_census_classifies_ephemeral_files_separately():
    assert census.classify("tools/.hud-synch-editor-123.tmp") == "temporary"
    assert census.classify("runtime/X.cs") == "runtime"
    assert census.classify("src/module.py") == "suite-source"
    assert census.classify("assets/building.png") == "assets"

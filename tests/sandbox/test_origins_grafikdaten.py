"""The complete Origins graphics source tree is browsable without public binaries.

Test synthetic Git/LFS copy contracts and the real pinned 13,562-entry
inventory. Tests never modify a game directory or remote repository.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"tools"))
import origins_grafikdaten as gfx

FIXTURE_ASSET = "assets/ui/derived/origins-blue-silver/UI-MasterAtlas.png"


def git(repo: Path, *args: str) -> str:
    run=subprocess.run(["git","-C",str(repo),*args],
                       capture_output=True,text=True,check=True)
    return run.stdout.strip()


@pytest.fixture
def source(tmp_path, monkeypatch):
    repo=tmp_path/"graphics-source"
    repo.mkdir()
    git(repo,"init","-b","main")
    git(repo,"config","user.name","Origins Graphics QA")
    git(repo,"config","user.email","synthetic@example.invalid")
    git(repo,"remote","add","origin",gfx.OFFICIAL_URL)
    file=repo/FIXTURE_ASSET
    file.parent.mkdir(parents=True)
    Image.new("RGBA",(11,7),(10,20,30,225)).save(file,"PNG")
    original=file.read_bytes()
    digest=hashlib.sha256(original).hexdigest()
    pointer=f"version https://git-lfs.github.com/spec/v1\noid sha256:{digest}\nsize {len(original)}\n".encode()
    file.write_bytes(pointer)
    git(repo,"add","--",FIXTURE_ASSET)
    git(repo,"commit","-m","qa synthetic LFS pointer")
    revision=git(repo,"rev-parse","HEAD")
    monkeypatch.setattr(gfx,"SOURCE_REVISION",revision)
    # Represents a successful local git lfs pull; the Git object stays pointer.
    file.write_bytes(original)
    monkeypatch.setattr(gfx,"ROOT",tmp_path/"Suite")
    monkeypatch.setattr(gfx,"WORK",tmp_path/"Suite"/"work") if hasattr(gfx,"WORK") else None
    (gfx.ROOT/"work").mkdir(parents=True)
    return repo, file, original


def test_complete_historical_origins_inventory_index():
    catalog=gfx.load_inventory()
    assert catalog["source_commit"]=="66dd212217831016d454483f41859258d5d3dc89"
    assert catalog["entry_count"]==13562
    assert catalog["categories"]["hud-gui"]==4086
    assert catalog["asset_blobs_embedded"] is False
    assert sum(catalog["categories"].values()) == catalog["entry_count"]
    names={r["path"] for r in catalog["entries"]}
    assert "sandbox/hud/hud.png" in names
    assert "daten/origins/ui-blue-silver/index.json" in names
    assert "assets/ui/derived/origins-blue-silver/UI-MasterAtlas.png" in names


def test_win_drive_backtracking_and_reserved_names_are_rejected():
    for name in (
        "../outside.png","/absolute.png","C:/Windows/secret.txt",
        "assets/../secret","a//b.png","a\\b.png","aux.png","hud/COM1.png",
        "hud/image.png.","hud/a:stream.png","hud/a?.png",
    ):
        with pytest.raises(gfx.GraphicsDataError):
            gfx.secure_relative(name)


def test_synthetic_git_lfs_file_verified_and_copied_only_into_work(source):
    repo, path, original=source
    inventory=gfx.inventory_from_tree(repo)
    assert inventory["entry_count"]==1
    row=inventory["entries"][0]
    assert row["path"]==FIXTURE_ASSET
    assert row["kind"]=="hud-gui"
    assert row["requires_lfs"] is True
    assert gfx.checked_source_file(repo,row)==path
    dest=gfx.ROOT/"work"/"edited"
    output, sidecar=gfx.copy_for_editing(repo,inventory,FIXTURE_ASSET,dest)
    assert output.read_bytes()==original
    receipt=json.loads(sidecar.read_text(encoding="utf8"))
    assert receipt["original_sha256"]==hashlib.sha256(original).hexdigest()
    assert receipt["relative_path"]==FIXTURE_ASSET
    assert path.read_bytes()==original
    with pytest.raises(gfx.GraphicsDataError,match="existiert bereits"):
        gfx.copy_for_editing(repo,inventory,FIXTURE_ASSET,dest)


def test_reject_unfetched_lfs_pointer(source):
    repo,path,original=source
    index=gfx.inventory_from_tree(repo)
    row=index["entries"][0]
    path.write_bytes(gfx.git_output(repo,"cat-file","blob",row["git_blob_sha1"]))
    with pytest.raises(gfx.GraphicsDataError,match="LFS"):
        gfx.checked_source_file(repo,row)


def test_reject_modified_worktree_asset(source):
    repo,path,original=source
    index=gfx.inventory_from_tree(repo)
    path.write_bytes(original+b"\x00")
    with pytest.raises(gfx.GraphicsDataError,match="Git-LFS-Pin"):
        gfx.checked_source_file(repo,index["entries"][0])


def test_reject_forged_tree_blob_identity(source):
    repo,path,original=source
    item=gfx.inventory_from_tree(repo)["entries"][0].copy()
    item["git_blob_sha1"]="f"*40
    with pytest.raises(gfx.GraphicsDataError,match="Git-Baum"):
        gfx.checked_source_file(repo,item)


def test_reject_source_nonofficial_clone(source):
    repo,path,original=source
    git(repo,"remote","set-url","origin","https://example.invalid/unknown.git")
    with pytest.raises(gfx.GraphicsDataError,match="nicht das bekannte"):
        gfx.source_repo(repo)


def test_source_user_edits_do_not_change_dataset_commit(source):
    repo,path,original=source
    marker=repo/"work"/"private"
    marker.parent.mkdir(parents=True)
    marker.write_bytes(b"mine")
    assert gfx.source_repo(repo)==repo
    assert gfx.checked_source_file(repo,gfx.inventory_from_tree(repo)["entries"][0])==path


def test_reject_copy_to_outside_suite_work(source):
    repo,path,original=source
    index=gfx.inventory_from_tree(repo)
    with pytest.raises(gfx.GraphicsDataError,match="work"):
        gfx.copy_for_editing(repo,index,FIXTURE_ASSET,gfx.ROOT/"dist")
    assert not (gfx.ROOT/"dist").exists()


def test_existing_nested_symlink_must_not_redirect_workcopy(source, tmp_path):
    repo,path,original=source
    index=gfx.inventory_from_tree(repo)
    dest=gfx.ROOT/"work"/"edited"
    outside=tmp_path/"outside"
    outside.mkdir()
    link=dest/"assets"
    link.parent.mkdir(parents=True)
    try:
        link.symlink_to(outside,target_is_directory=True)
    except (OSError,NotImplementedError):
        pytest.skip("Local test account cannot create symlinks")
    with pytest.raises(gfx.GraphicsDataError,match="außerhalb|Verknüpf"):
        gfx.copy_for_editing(repo,index,FIXTURE_ASSET,dest)
    assert not (outside/"ui").exists()


@pytest.mark.parametrize("remote_url", [
    gfx.PRIVATE_GITHUB_URL,
    gfx.PRIVATE_GITHUB_URL.removesuffix(".git"),
    "https://strongholdoriginsmod-rgb@github.com/strongholdoriginsmod-rgb/sh1de-shcde-sprite-suite.git",
    "git@github.com:strongholdoriginsmod-rgb/sh1de-shcde-sprite-suite.git",
])
def test_private_github_graphics_branch_reuses_the_pinned_source_commit(
    source, remote_url
):
    repo, _file, _original = source
    git(repo, "remote", "set-url", "origin", remote_url)
    assert gfx.source_repo(repo) == repo.resolve()


def test_private_github_like_other_owner_is_not_trusted(source):
    repo, _file, _original = source
    git(repo, "remote", "set-url", "origin",
        "https://github.com/unrelated/sh1de-shcde-sprite-suite.git")
    with pytest.raises(gfx.GraphicsDataError, match="nicht das bekannte"):
        gfx.source_repo(repo)

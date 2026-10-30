"""Untrusted project-input ZIPs never overwrite user artwork or escape work."""
from __future__ import annotations
from hashlib import sha256
import json
from pathlib import Path
import stat
import sys
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import project_inputs as tool


@pytest.fixture
def sample(tmp_path):
    root = tmp_path / "original"
    (root / "config").mkdir(parents=True)
    (root / "profiles").mkdir()
    image = root / "assets" / "images" / "demo.bin"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"our original art")
    (root / "profiles" / "sample.json").write_text(
        '{"art":"assets/images/demo.bin"}', encoding="utf8")
    (root / "config" / "ui-textures-bc7-v1.json").write_text(
        '{"same":"assets/images/demo.bin"}', encoding="utf8")
    archive = tmp_path / "input-pack.zip"
    assert tool.pack(root, archive)["files"] == 1
    target = tmp_path / "other"
    return root, archive, target


def make_zip(path: Path, contents: dict[str, bytes], *, rows=None):
    rows = ([{"path":name, "bytes":len(data), "sha256":sha256(data).hexdigest()}
             for name,data in contents.items()] if rows is None else rows)
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as zipfile:
        for name, data in contents.items():
            zipfile.writestr(name, data)
        zipfile.writestr(tool.MANIFEST,
                         json.dumps({"schema":1,"files":rows}))


def test_pack_restore_dry_run_and_repeated_idempotent_import(sample):
    root, archive, target = sample
    original = (root / "assets/images/demo.bin").read_bytes()
    assert tool.install(archive, target) == {
        "checked":1, "new_files":1, "written":0}
    assert not target.exists()
    assert tool.install(archive, target, write=True)["written"] == 1
    output = target / "assets/images/demo.bin"
    assert output.read_bytes() == original
    assert tool.install(archive, target, write=True)["new_files"] == 0
    assert (root / "assets/images/demo.bin").read_bytes() == original


def test_import_never_replaces_changed_existing_input(sample):
    _root, archive, target = sample
    output = target / "assets/images/demo.bin"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"manually edited artwork")
    with pytest.raises(ValueError, match="Existing modified"):
        tool.install(archive, target, write=True)
    assert output.read_bytes() == b"manually edited artwork"


@pytest.mark.parametrize("name", [
    "../escape", "assets/../outside", "assets//empty", "assets/.",
    "assets/CON.png", "assets/LPT1.png", "assets/a.", "assets/x ",
    "work\\evil", "/assets/absolute", "assets/C:/x.png", "config/x",
    "assets/COM¹.png", "assets/a?b.png",
])
def test_unsafe_archive_input_paths_refused(name):
    with pytest.raises(ValueError):
        tool.safe_relative(name)


def test_duplicate_case_collisions_rejected_before_any_write(tmp_path):
    contents = {"assets/Art.bin":b"a","assets/art.bin":b"b"}
    archive = tmp_path / "collision.zip"
    make_zip(archive, contents)
    target = tmp_path / "destination"
    with pytest.raises(ValueError, match="Duplicate"):
        tool.install(archive, target, write=True)
    assert not target.exists()


def test_zip_symlinks_and_invalid_manifest_types_rejected(tmp_path):
    archive = tmp_path / "symlink.zip"
    name = "assets/sneaky.bin"
    info = ZipInfo(name)
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with ZipFile(archive, "w") as writer:
        writer.writestr(info, b"../../escape")
        writer.writestr(tool.MANIFEST, json.dumps({"schema":1,"files":[{
            "path":name,"bytes":12,"sha256":sha256(b"../../escape").hexdigest()
        }]}))
    with pytest.raises(ValueError, match="linked"):
        tool.install(archive, tmp_path / "target", True)

    bad = tmp_path / "bad-type.zip"
    make_zip(bad, {name:b"ok"}, rows=[{
        "path":name,"bytes":True,"sha256":sha256(b"ok").hexdigest()
    }])
    with pytest.raises(ValueError, match="Inconsistent"):
        tool.install(bad, tmp_path / "target", True)


def test_unlisted_member_and_mismatch_refuse_to_create_files(tmp_path):
    archive = tmp_path / "tampered.zip"
    a = "assets/changed.bin"
    make_zip(archive, {a:b"changed"}, rows=[{
        "path":a,"bytes":7,"sha256":"0"*64
    }])
    dest = tmp_path / "destination"
    with pytest.raises(ValueError, match="checksum"):
        tool.install(archive, dest, True)
    assert not dest.exists()
    unlisted = tmp_path / "unlisted.zip"
    make_zip(unlisted, {a:b"good"}, rows=[])
    with pytest.raises(ValueError, match="incomplete"):
        tool.install(unlisted, dest, True)


def test_compression_bomb_is_rejected_before_extraction(tmp_path):
    archive = tmp_path / "bomb.zip"
    make_zip(archive, {"assets/huge.bin":b"0"*(2*1024*1024)})
    with pytest.raises(ValueError, match="size limits"):
        tool.install(archive, tmp_path / "target", True)
    assert not (tmp_path / "target").exists()


def test_target_created_between_preflight_and_write_is_preserved(sample, monkeypatch):
    _root, archive, target = sample
    output = target / "assets/images/demo.bin"
    original = tool._copy_checked

    def race(archive_obj, row, path):
        path.write_bytes(b"other process data")
        return original(archive_obj, row, path)

    monkeypatch.setattr(tool, "_copy_checked", race)
    with pytest.raises(FileExistsError):
        tool.install(archive, target, True)
    assert output.read_bytes() == b"other process data"


def test_failed_second_write_rolls_back_only_our_new_files(tmp_path, monkeypatch):
    contents = {"assets/a.bin":b"a", "assets/z.bin":b"z"}
    archive = tmp_path / "two-files.zip"
    make_zip(archive, contents)
    target = tmp_path / "target"
    original = tool._copy_checked

    def fail_second(archive_obj, row, path):
        if row["path"] == "assets/z.bin":
            raise OSError("simulated disk failure")
        return original(archive_obj, row, path)

    monkeypatch.setattr(tool, "_copy_checked", fail_second)
    with pytest.raises(OSError, match="disk failure"):
        tool.install(archive, target, True)
    assert not (target / "assets/a.bin").exists()
    assert not (target / "assets/z.bin").exists()


def test_source_modification_removes_partial_archive_without_overwriting(sample, tmp_path, monkeypatch):
    root, archive, _target = sample
    with pytest.raises(FileExistsError):
        tool.pack(root, archive)
    before = archive.read_bytes()
    output = tmp_path / "partial.zip"
    original = ZipFile.write

    def change_source(archive_obj, path, arcname=None, *a, **kw):
        result = original(archive_obj, path, arcname, *a, **kw)
        Path(path).write_bytes(b"externally modified during packing")
        return result

    with monkeypatch.context() as m:
        m.setattr(ZipFile, "write", change_source)
        with pytest.raises(ValueError, match="changed during"):
            tool.pack(root, output)
    assert not output.exists()
    assert archive.read_bytes() == before

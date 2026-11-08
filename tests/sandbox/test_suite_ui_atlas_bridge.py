"""Real atlas publication into isolated projects, including guarded rollback."""
from hashlib import sha256
import json
from pathlib import Path

from PIL import Image
import pytest

import hud_menu_workspace as hud
import suite_ui_atlas_bridge as bridge
from suite_output_transaction import OutputConflictError
from ui_atlas_workspace import AtlasProject


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    root = tmp_path / "suite"
    work = root / "work"
    project = work / "projects" / "atlas-project"
    project.mkdir(parents=True)
    monkeypatch.setattr(hud, "ROOT", root)
    monkeypatch.setattr(hud, "WORK", work)
    monkeypatch.setattr(hud, "DEFAULT", project)
    return project, work


def atlas_pair(tmp_path, work, *, uri="master.png"):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    png = inputs / Path(uri).name
    with Image.new("RGBA", (12, 8), (20, 30, 40, 0)) as image:
        image.putpixel((0, 0), (101, 202, 33, 255))
        image.save(png)
    xaml = inputs / "UI-MasterAtlas.xaml"
    xaml.write_text(
        '<ResourceDictionary xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" '
        'xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml">'
        f'<BitmapImage x:Key="Master" UriSource="{uri}"/>'
        '<CroppedBitmap x:Key="Icon" Source="{StaticResource Master}" SourceRect="2,3,3,2"/>'
        '</ResourceDictionary>', encoding="utf8")
    atlas = AtlasProject.create(png, xaml, work / "atlas-workspace")
    return atlas, png, xaml


def export_pair(atlas, name="v1"):
    folder = atlas.workspace / "exports"
    folder.mkdir(exist_ok=True)
    return atlas.export_pair(folder / name)


def replace(atlas, tmp_path, color=(210, 10, 80, 127)):
    png = tmp_path / "replacement.png"
    with Image.new("RGBA", (3, 2), color) as image:
        image.save(png)
    atlas.replace("Icon", png)


def targets(project, uri="master.png"):
    base = project / "Override/Assets/GUI/Sprites"
    return base / uri, base / "UI-MasterAtlas.xaml"


def seed_previous(project, uri):
    png, xaml = targets(project, uri)
    png.parent.mkdir(parents=True, exist_ok=True)
    xaml.parent.mkdir(parents=True, exist_ok=True)
    with Image.new("RGBA", (12, 8), (120, 90, 60, 255)) as image:
        image.save(png)
    xaml.write_bytes(b"<previous/>")
    return {png: png.read_bytes(), xaml: xaml.read_bytes()}


def test_publish_exact_pair_originals_and_provenance(isolated, tmp_path):
    project, work = isolated
    atlas, original_png, original_xaml = atlas_pair(tmp_path, work)
    before = {path: path.read_bytes() for path in (original_png, original_xaml)}
    replace(atlas, tmp_path)
    pair = export_pair(atlas)
    result = bridge.publish_pair(project, pair)
    png, xaml = targets(project)
    assert png.read_bytes() == Path(pair["png"]).read_bytes()
    assert xaml.read_bytes() == original_xaml.read_bytes()
    with Image.open(png) as image:
        assert image.getpixel((2, 3)) == (210, 10, 80, 127)
        assert image.getpixel((0, 0)) == (101, 202, 33, 255)
    receipt = json.loads(Path(result["receipt"]).read_text("utf8"))
    assert receipt["revision"] == pair["revision"]
    assert receipt["original_game_files_modified"] is False
    assert receipt["installed_into_game"] is False
    assert {row["relative_path"]: row["sha256"] for row in receipt["files"]} == {
        path.relative_to(project).as_posix(): digest(path) for path in (png, xaml)}
    assert all(path.read_bytes() == contents for path, contents in before.items())


def test_update_retains_exact_previous_project_files(isolated, tmp_path):
    project, work = isolated
    atlas, _, original_xaml = atlas_pair(tmp_path, work)
    first = bridge.publish_pair(project, export_pair(atlas))
    png, xaml = targets(project)
    previous = (png.read_bytes(), xaml.read_bytes())
    replace(atlas, tmp_path)
    second = bridge.publish_pair(project, export_pair(atlas, "v2"))
    revisions = Path(second["revisions"])
    assert (revisions / "before-0.png").read_bytes() == previous[0]
    assert (revisions / "before-1.xaml").read_bytes() == previous[1]
    assert png.read_bytes() != previous[0]
    assert xaml.read_bytes() == original_xaml.read_bytes()
    assert first["revision"] != second["revision"]


def test_uri_subdirectory_retained_by_unchanged_xaml(isolated, tmp_path):
    project, work = isolated
    uri = "sheets/master.png"
    atlas, _, original_xaml = atlas_pair(tmp_path, work, uri=uri)
    pair = export_pair(atlas)
    bridge.publish_pair(project, pair)
    png, xaml = targets(project, uri)
    assert png.read_bytes() == Path(pair["png"]).read_bytes()
    assert xaml.read_bytes() == original_xaml.read_bytes()
    assert not (xaml.parent / "master.png").exists()


def test_stale_export_rejected_before_any_project_write(isolated, tmp_path):
    project, work = isolated
    atlas, _, _ = atlas_pair(tmp_path, work)
    pair = export_pair(atlas)
    replace(atlas, tmp_path)
    with pytest.raises(ValueError, match="seit dem Export"):
        bridge.publish_pair(project, pair)
    assert not list(project.rglob("*"))


@pytest.mark.parametrize("kind", ["png", "xaml", "png_and_receipt"])
def test_export_tamper_including_joint_png_receipt_is_rejected(isolated, tmp_path, kind):
    project, work = isolated
    atlas, _, _ = atlas_pair(tmp_path, work)
    pair = export_pair(atlas)
    if kind in {"png", "png_and_receipt"}:
        with Image.new("RGBA", (12, 8), (255, 90, 10, 255)) as image:
            image.save(pair["png"])
    if kind == "xaml":
        Path(pair["xaml"]).write_bytes(Path(pair["xaml"]).read_bytes() + b"<!-- foreign edit -->")
    if kind == "png_and_receipt":
        path = Path(pair["receipt"])
        proof = json.loads(path.read_text("utf8"))
        proof["png"]["sha256"] = digest(pair["png"])
        path.write_text(json.dumps(proof), encoding="utf8")
    with pytest.raises(ValueError, match="Export"):
        bridge.publish_pair(project, pair)
    assert not list(project.rglob("*"))


def test_revision_change_during_staging_preserves_project(isolated, tmp_path, monkeypatch):
    project, work = isolated
    atlas, _, _ = atlas_pair(tmp_path, work)
    pair = export_pair(atlas)
    previous = seed_previous(project, "master.png")
    original_copy = bridge.shutil.copyfile
    changed = False
    def copy_and_change(source, destination, *args, **kwargs):
        nonlocal changed
        result = original_copy(source, destination, *args, **kwargs)
        if Path(source) == Path(pair["png"]) and not changed:
            changed = True
            replace(atlas, tmp_path)
        return result
    monkeypatch.setattr(bridge.shutil, "copyfile", copy_and_change)
    with pytest.raises(OutputConflictError, match="inzwischen verändert"):
        bridge.publish_pair(project, pair)
    assert changed and all(path.read_bytes() == content for path, content in previous.items())


@pytest.mark.parametrize("uri", ["master.png", "sheets/master.png"])
def test_publication_receipt_write_failure_rolls_back_both_files(isolated, tmp_path, monkeypatch, uri):
    project, work = isolated
    atlas, _, _ = atlas_pair(tmp_path, work, uri=uri)
    pair = export_pair(atlas)
    previous = seed_previous(project, uri)
    real_write = Path.write_text
    def fail_proof(path, *args, **kwargs):
        if path.name == "publication.json":
            raise OSError("Injected publication proof write failure")
        return real_write(path, *args, **kwargs)
    monkeypatch.setattr(Path, "write_text", fail_proof)
    with pytest.raises(OSError, match="proof write failure"):
        bridge.publish_pair(project, pair)
    assert all(path.read_bytes() == content for path, content in previous.items())
    assert not list(hud._metadata_dir(project).rglob("publication.json"))


def test_foreign_edit_during_outer_rollback_is_preserved_with_recovery(isolated, tmp_path, monkeypatch):
    project, work = isolated
    uri = "sheets/master.png"
    atlas, _, _ = atlas_pair(tmp_path, work, uri=uri)
    pair = export_pair(atlas)
    previous = seed_previous(project, uri)
    png, xaml = targets(project, uri)
    real_publish = bridge.OutputBatch.publish
    count = 0
    foreign = b"a user's newer file must survive rollback"
    def fail_second_batch(batch):
        nonlocal count
        count += 1
        if count == 2:
            png.write_bytes(foreign)
            raise OSError("Injected second batch failure")
        return real_publish(batch)
    monkeypatch.setattr(bridge.OutputBatch, "publish", fail_second_batch)
    with pytest.raises(OutputConflictError, match="Fremde Dateien erhalten"):
        bridge.publish_pair(project, pair)
    assert png.read_bytes() == foreign
    assert xaml.read_bytes() == previous[xaml]
    backups = list(hud._metadata_dir(project).rglob("before-0.png"))
    assert len(backups) == 1 and backups[0].read_bytes() == previous[png]


def test_cancel_between_uri_batches_restores_previous_pair(isolated, tmp_path):
    project, work = isolated
    uri = "sheets/master.png"
    atlas, _, _ = atlas_pair(tmp_path, work, uri=uri)
    pair = export_pair(atlas)
    previous = seed_previous(project, uri)
    calls = 0
    def cancel_after_first_publication():
        nonlocal calls
        calls += 1
        return calls >= 3
    with pytest.raises(ValueError, match="abgebrochen"):
        bridge.publish_pair(project, pair, cancel=cancel_after_first_publication)
    assert calls >= 3
    assert all(path.read_bytes() == content for path, content in previous.items())

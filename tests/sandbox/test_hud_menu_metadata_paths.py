"""Portable metadata regression tests without installed game assets."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import json
import shutil
import sys

from PIL import Image
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/"tools"),str(ROOT/"src")]

import hud_menu_metadata_paths as paths
import hud_menu_workspace as workspace
import hud_menu_layout as layout
import suite_hud_menu_session as session


def digest(data:bytes)->str:
    return sha256(data).hexdigest()


class MetadataError(ValueError):
    pass


def meta(project:Path, work:Path)->Path:
    return paths.metadata_dir(project,work=work,folder=".hud-menu-metadata",
                              sha=digest,error=MetadataError)


def test_new_metadata_location_survives_moving_an_entire_work_folder(tmp_path):
    old_work=tmp_path/"first windows install"/"work"
    project=old_work/"my-hud"
    project.mkdir(parents=True)
    original=meta(project,old_work)
    (original/"layouts").mkdir(parents=True)
    (original/"layouts"/"Original.scene.json").write_text('{"test":true}',encoding="utf8")
    new_work=tmp_path/"different user and drive"/"work"
    shutil.copytree(old_work,new_work)
    moved=meta(new_work/"my-hud",new_work)
    assert moved.name==original.name
    assert (moved/"layouts"/"Original.scene.json").read_text("utf8")=='{"test":true}'


def test_legacy_data_is_copied_verified_and_never_deleted(tmp_path):
    work=tmp_path/"SpriteSuite"/"work"
    project=work/"my-menu"
    project.mkdir(parents=True)
    legacy=work/".hud-menu-metadata"/digest(
        str(project.resolve()).casefold().encode("utf8"))[:24]
    payloads={
        "layouts/MeinMenu.scene.json":b"previous editable scene",
        "layouts/revisions/old.scene.json":b"previous revision",
        "import-baselines/button.png":b"original pixels",
        "exports/Menu.png.json":b"previous export",
        "qa-installs/my-mod.json":b"previous QA receipt",
    }
    for key,value in payloads.items():
        dest=legacy/key
        dest.parent.mkdir(parents=True,exist_ok=True)
        dest.write_bytes(value)
    portable=meta(project,work)
    assert portable!=legacy
    for key,value in payloads.items():
        assert (portable/key).read_bytes()==value
        assert (legacy/key).read_bytes()==value
    assert meta(project,work)==portable


def test_portable_metadata_has_priority_without_overwriting_legacy(tmp_path):
    work=tmp_path/"suite"/"work"
    project=work/"project"
    project.mkdir(parents=True)
    portable=meta(project,work)
    portable.mkdir(parents=True)
    (portable/"important.txt").write_text("portable",encoding="utf8")
    legacy=work/".hud-menu-metadata"/digest(
        str(project.resolve()).casefold().encode("utf8"))[:24]
    legacy.mkdir()
    (legacy/"important.txt").write_text("legacy",encoding="utf8")
    assert meta(project,work)==portable
    assert (portable/"important.txt").read_text("utf8")=="portable"
    assert (legacy/"important.txt").read_text("utf8")=="legacy"


def test_migration_refuses_linked_sources_and_keeps_legacy(tmp_path):
    work=tmp_path/"suite"/"work"
    project=work/"project"
    project.mkdir(parents=True)
    legacy=work/".hud-menu-metadata"/digest(
        str(project.resolve()).casefold().encode("utf8"))[:24]
    legacy.mkdir(parents=True)
    outside=tmp_path/"personal-secret.txt"
    outside.write_text("leave unchanged",encoding="utf8")
    try:
        (legacy/"linked.txt").symlink_to(outside)
    except (OSError,NotImplementedError):
        pytest.skip("Junction/symlink privileges unavailable")
    with pytest.raises(MetadataError,match="Metadaten enthalten"):
        meta(project,work)
    assert outside.read_text("utf8")=="leave unchanged"
    assert not list((work/".hud-menu-metadata").glob("portable-*"))


def test_directory_and_traversal_guards_are_kept(tmp_path):
    work=tmp_path/"suite"/"work"
    work.mkdir(parents=True)
    outside=tmp_path/"outside"
    outside.mkdir()
    with pytest.raises(MetadataError,match="innerhalb"):
        meta(outside,work)
    project=work/"valid"
    project.mkdir()
    (work/".hud-menu-metadata").write_text("not a directory",encoding="utf8")
    with pytest.raises(MetadataError,match="Ungültiger"):
        meta(project,work)


@pytest.fixture
def portable_workspace(tmp_path,monkeypatch):
    suite=tmp_path/"Suite 1"
    work=suite/"work"
    work.mkdir(parents=True)
    monkeypatch.setattr(workspace,"ROOT",suite)
    monkeypatch.setattr(workspace,"WORK",work)
    monkeypatch.setattr(layout,"WORK",work)
    project=work/"my-project"
    source=tmp_path/"raw-menu.png"
    image=Image.new("RGBA",(32,24),(39,120,210,190))
    image.save(source)
    reference=source.read_bytes()
    asset=workspace.import_image(source,project=project)
    return suite,project,source,asset,reference


def test_end_to_end_import_layout_export_move_and_reload(portable_workspace,monkeypatch,tmp_path):
    suite,project,source,asset,reference=portable_workspace
    scene=layout.Scene(name="MyMenu",width=96,height=64,
                       background=(0,0,0,0))
    layer=layout.add_layer(scene,project,asset.relative_to(project).as_posix(),
                           x=8,y=11)
    layout.set_geometry(scene,layer.id,x=21.5,y=19.0,
                        width=45,height=30,rotation=20)
    scene.target_resource="Override/Assets/GUI/Images/MenuComposite.png"
    _,token=layout.save_scene(scene,project)
    outcome=layout.export_composition(scene,project,resource_name="MenuComposite",
                                       scene_sha256=token)
    assert layout.audit_export(scene,project,scene_sha256=token)["png_sha256"]==outcome["sha256"]
    previous_art=Path(outcome["png"]).read_bytes()
    previous_baseline=workspace._baseline(project,asset.relative_to(project).as_posix())[0].read_bytes()
    previous_scene=scene.as_json()
    session.save_session(project,asset.relative_to(project).as_posix(),scene="MyMenu")

    moved=tmp_path/"Moved Suite to another Windows PC"
    shutil.copytree(suite,moved)
    new_work=moved/"work"
    monkeypatch.setattr(workspace,"ROOT",moved)
    monkeypatch.setattr(workspace,"WORK",new_work)
    monkeypatch.setattr(layout,"WORK",new_work)
    new_project=new_work/"my-project"
    assert session.read_session()["project"]==new_project
    saved,loaded_token=layout.load_scene(new_project,"MyMenu")
    assert loaded_token==token
    assert saved.as_json()==previous_scene
    assert layout.audit_export(saved,new_project,scene_sha256=token)["png_sha256"]==outcome["sha256"]
    assert (new_project/saved.target_resource).read_bytes()==previous_art
    assert workspace._baseline(new_project,asset.relative_to(project).as_posix())[0].read_bytes()==previous_baseline
    assert source.read_bytes()==reference


def test_migrate_real_legacy_layout_then_move(portable_workspace,monkeypatch,tmp_path):
    suite,project,source,asset,reference=portable_workspace
    metadata=workspace._metadata_dir(project)
    legacy=metadata.parent/digest(str(project.resolve()).casefold().encode("utf8"))[:24]
    legacy.mkdir(exist_ok=True)
    # Legacy bytes come from the real stored baseline metadata.
    assert (metadata/"import-baselines").is_dir()
    shutil.copytree(metadata,legacy,dirs_exist_ok=True)
    shutil.rmtree(metadata)
    scene=layout.Scene(name="LegacyMenu",width=64,height=48)
    layout.add_layer(scene,project,asset.relative_to(project).as_posix())
    saved_path,checksum=layout.save_scene(scene,project)
    assert saved_path.is_file() and metadata.is_dir()
    assert legacy.is_dir()
    moved=tmp_path/"portable new home"
    shutil.copytree(suite,moved)
    monkeypatch.setattr(workspace,"ROOT",moved)
    monkeypatch.setattr(workspace,"WORK",moved/"work")
    monkeypatch.setattr(layout,"WORK",moved/"work")
    loaded,_=layout.load_scene(moved/"work"/"my-project","LegacyMenu")
    assert loaded.as_json()==scene.as_json()
    assert source.read_bytes()==reference

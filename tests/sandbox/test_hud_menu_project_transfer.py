"""Portable project archive safety and cross-installation round-trip tests."""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import sys
from zipfile import ZipFile

import pytest
from PIL import Image

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/"tools"),str(ROOT/"src")]
import hud_menu_workspace as workspace
import hud_menu_layout as layout
import hud_menu_project_transfer as transfer
import suite_hud_menu_session as session


@pytest.fixture
def sample(tmp_path,monkeypatch):
    suite=tmp_path/"First Suite Installation"
    work=suite/"work"
    work.mkdir(parents=True)
    monkeypatch.setattr(workspace,"ROOT",suite)
    monkeypatch.setattr(workspace,"WORK",work)
    monkeypatch.setattr(layout,"WORK",work)
    project=work/"my-project"
    source=tmp_path/"original-unchanged.png"
    Image.new("RGBA",(36,21),(80,42,127,230)).save(source)
    original=source.read_bytes()
    asset=workspace.import_image(source,project=project)
    scene=layout.Scene(name="MyMenu",width=64,height=48,
                       background=(0,0,0,0))
    layer=layout.add_layer(scene,project,
                           asset.relative_to(project).as_posix(),x=5,y=10)
    scene.target_resource="Override/Assets/GUI/Images/Composite.png"
    token=layout.save_scene(scene,project)[1]
    layout.set_geometry(scene,layer.id,x=10.5,width=42,rotation=15)
    token=layout.save_scene(scene,project,expected_hash=token)[1]
    session.save_session(project,asset.relative_to(project).as_posix(),
                         scene="MyMenu")
    exported=layout.export_composition(scene,project,
                                        resource_name="Composite",
                                        scene_sha256=token)
    meta=workspace._metadata_dir(project)
    (meta/"qa-installs").mkdir()
    (meta/"qa-installs"/"OldGameReceipt.json").write_text(
        '{"game":"C:/SomeoneElse/SSGameQA"}',encoding="utf8")
    return suite,project,source,original,scene,token,exported


def test_project_archive_contains_editable_assets_history_and_provenance(sample,tmp_path):
    suite,project,source,original,scene,token,exported=sample
    out=tmp_path/"backup.zip"
    report=transfer.create_archive(project,out)
    assert report["files"]>=5
    assert report["sha256"]==sha256(out.read_bytes()).hexdigest()
    with ZipFile(out) as archive:
        names=set(archive.namelist())
        assert transfer.MANIFEST in names
        assert "project/Override/Assets/GUI/Images/Composite.png" in names
        assert any(s.startswith("metadata/layouts/") and
                   s.endswith(".scene.json") for s in names)
        assert any(s.startswith("metadata/layouts/revisions/") for s in names)
        assert any(s.startswith("metadata/import-baselines/") for s in names)
        assert any(s.startswith("metadata/exports/") for s in names)
        assert not any("qa-installs" in s for s in names)
        manifest=json.loads(archive.read(transfer.MANIFEST))
        assert manifest["schema"]==transfer.SCHEMA
        assert str(suite) not in archive.read(transfer.MANIFEST).decode("utf8")
        assert manifest["project_name"]=="my-project"
        assert manifest["selected_scene"]=="MyMenu"
        assert manifest["selected_asset"].endswith("original-unchanged.png")
    assert source.read_bytes()==original


def test_restore_after_moving_to_other_computer_preserves_layout_and_export(
    sample,tmp_path,monkeypatch,
):
    suite,project,source,original,scene,token,exported=sample
    backup=tmp_path/"my-project.zip"
    transfer.create_archive(project,backup)
    second=tmp_path/"Different Windows Installation"
    second_work=second/"work"
    second_work.mkdir(parents=True)
    monkeypatch.setattr(workspace,"ROOT",second)
    monkeypatch.setattr(workspace,"WORK",second_work)
    monkeypatch.setattr(layout,"WORK",second_work)
    restored=transfer.restore_archive(backup)
    new_project=Path(restored["project"])
    assert new_project==second_work/"my-project"
    recovered,recovered_token=layout.load_scene(new_project,"MyMenu")
    assert recovered_token==token
    assert recovered.as_json()==scene.as_json()
    attestation=layout.audit_export(recovered,new_project,
                                     scene_sha256=recovered_token)
    assert attestation["png_sha256"]==exported["sha256"]
    assert workspace.list_assets(new_project)
    assert session.read_session()["scene"]=="MyMenu"
    assert session.read_session()["asset"].endswith("original-unchanged.png")
    assert source.read_bytes()==original


def test_restoring_as_new_name_rebinds_metadata_without_changing_assets(
    sample,tmp_path,monkeypatch,
):
    suite,project,source,original,scene,token,exported=sample
    backup=tmp_path/"project-copy.zip"
    transfer.create_archive(project,backup)
    restored=transfer.restore_archive(backup,project_name="NewProject")
    assert Path(restored["project"]).name=="NewProject"
    copied,_=layout.load_scene(restored["project"],"MyMenu")
    assert copied.layers[0].asset==scene.layers[0].asset
    assert workspace.list_assets(restored["project"])
    assert source.read_bytes()==original


def test_no_overwrite_of_archives_or_existing_projects(sample,tmp_path):
    suite,project,source,original,scene,token,exported=sample
    backup=tmp_path/"safe.zip"
    first=transfer.create_archive(project,backup)
    before=backup.read_bytes()
    with pytest.raises(workspace.WorkshopError,match="existiert"):
        transfer.create_archive(project,backup)
    assert backup.read_bytes()==before
    with pytest.raises(workspace.WorkshopError,match="existieren"):
        transfer.restore_archive(backup)
    assert source.read_bytes()==original


def test_tampered_bytes_fail_without_partial_destination(sample,tmp_path,monkeypatch):
    suite,project,source,original,scene,token,exported=sample
    backup=tmp_path/"good.zip"
    transfer.create_archive(project,backup)
    corrupt=tmp_path/"tampered.zip"
    with ZipFile(backup) as reader, ZipFile(corrupt,"w") as writer:
        for info in reader.infolist():
            content=reader.read(info)
            if info.filename.endswith("/Composite.png"):
                content=b"X"+content[1:]
            writer.writestr(info.filename,content)
    with pytest.raises(workspace.WorkshopError,match="Prüfsumme"):
        transfer.restore_archive(corrupt,project_name="RestoreFailed")
    assert not (suite/"work"/"RestoreFailed").exists()
    assert not workspace._metadata_dir(suite/"work"/"my-project").is_symlink()
    assert source.read_bytes()==original


def test_traversal_or_unlisted_members_are_rejected(sample,tmp_path):
    suite,project,source,original,scene,token,exported=sample
    attack=tmp_path/"unsafe.zip"
    with ZipFile(attack,"w") as file:
        file.writestr("project/../../escape.py",b"malicious")
        file.writestr(transfer.MANIFEST,json.dumps({
            "schema":transfer.SCHEMA,"project_name":"malicious",
            "files":[{"path":"project/../../escape.py","bytes":9,
                      "sha256":sha256(b"malicious").hexdigest()}],
        }))
    with pytest.raises(workspace.WorkshopError):
        transfer.archive_info(attack)
    with pytest.raises(workspace.WorkshopError):
        transfer.restore_archive(attack)
    assert not (tmp_path/"escape.py").exists()
    assert source.read_bytes()==original


def test_absolute_and_qa_receipt_sections_are_rejected(sample,tmp_path):
    suite,project,source,original,scene,token,exported=sample
    for key in ("metadata/qa-installs/receipt.json",
                "project/Windows/evil.exe","project/C:/Windows/file.txt",
                "project/Override/../evil.txt"):
        with pytest.raises(workspace.WorkshopError):
            transfer._safe_member(key)
    assert source.read_bytes()==original


def test_archive_manifest_and_member_case_collisions_are_rejected(sample,tmp_path):
    suite,project,source,original,scene,token,exported=sample
    attack=tmp_path/"dup.zip"
    with ZipFile(attack,"w") as zipfile:
        zipfile.writestr("project/Override/Sprites/Icon.png",b"a")
        zipfile.writestr("project/Override/Sprites/icon.png",b"b")
        zipfile.writestr(transfer.MANIFEST,b"{}")
    with pytest.raises(workspace.WorkshopError,match="Doppelte"):
        transfer.archive_info(attack)
    assert source.read_bytes()==original


def test_invalid_archive_name_or_target_does_not_write_anything(sample,tmp_path):
    suite,project,source,original,scene,token,exported=sample
    out=tmp_path/"a.zip"
    transfer.create_archive(project,out)
    for name in ("../outside","CON","bad/name"," trailing","x"*65):
        with pytest.raises(workspace.WorkshopError):
            transfer.restore_archive(out,project_name=name)
    assert not (tmp_path/"outside").exists()


def test_export_output_must_not_live_inside_project(sample,tmp_path):
    suite,project,source,original,scene,token,exported=sample
    with pytest.raises(workspace.WorkshopError,match="nicht in den"):
        transfer.create_archive(project,project/"Override"/"Assets"/"new.zip")


def test_archive_accepts_readable_unicode_project_name(sample,tmp_path):
    suite,project,source,original,scene,token,exported=sample
    backup=tmp_path/"mein-layout.zip"
    transfer.create_archive(project,backup)
    report=transfer.restore_archive(backup,project_name="Mein Menü 2")
    restored=Path(report["project"])
    assert restored.name=="Mein Menü 2"
    loaded,_=layout.load_scene(restored,"MyMenu")
    assert loaded.layers[0].x==10.5
    assert source.read_bytes()==original


def test_archive_rejects_unsupported_resource_files_and_zip_bombs(sample,tmp_path):
    suite,project,source,original,scene,token,exported=sample
    for name in ("project/Override/Assets/GUI/Images/suspicious.exe",
                 "project/Override/Other/hidden.png"):
        with pytest.raises(workspace.WorkshopError):
            transfer._safe_member(name)

    from zipfile import ZIP_DEFLATED
    compressed=tmp_path/"suspicious-compression.zip"
    payload=b"0"*(2*1024*1024)
    path="project/Override/Assets/GUI/Images/large.png"
    with ZipFile(compressed,"w",ZIP_DEFLATED) as archive:
        archive.writestr(path,payload)
        archive.writestr(transfer.MANIFEST,json.dumps({
            "schema":transfer.SCHEMA,
            "project_name":"MyProject",
            "files":[{"path":path,"bytes":len(payload),
                      "sha256":sha256(payload).hexdigest()}],
        }))
    with pytest.raises(workspace.WorkshopError,match="komprimierter"):
        transfer.archive_info(compressed)
    assert source.read_bytes()==original


def test_archive_rejects_missing_last_scene_even_with_valid_file_list(sample,tmp_path):
    suite,project,source,original,scene,token,exported=sample
    path=tmp_path/"missing-scene.zip"
    with ZipFile(path,"w") as z:
        z.writestr(transfer.MANIFEST,json.dumps({
            "schema":transfer.SCHEMA,
            "project_name":"MyProject",
            "selected_scene":"AbsentLayout",
            "files":[],
        }))
    with pytest.raises(workspace.WorkshopError,match="gespeichertes Layout fehlt"):
        transfer.archive_info(path)


def test_auto_suggests_new_project_name_when_old_one_exists(sample):
    suite,project,source,original,scene,token,exported=sample
    assert transfer.suggest_project_name("my-project")=="my-project-Kopie"
    other=workspace.workspace(suite/"work"/"my-project-Kopie",create=True)
    assert other.is_dir()
    assert transfer.suggest_project_name("my-project")=="my-project-Kopie-2"
    assert transfer.suggest_project_name("UnbenutztesProjekt")=="UnbenutztesProjekt"
    assert source.read_bytes()==original


def test_corrupt_zip_member_crc_cleans_temporary_restore(sample,tmp_path):
    from zipfile import ZIP_STORED
    suite,project,source,original,scene,token,exported=sample
    archive=tmp_path/"crc-error.zip"
    key="project/Override/Assets/GUI/Images/Icon.png"
    payload=b"ICON_UNIQUE_CRC_BYTES"
    with ZipFile(archive,"w",compression=ZIP_STORED) as file:
        file.writestr(key,payload)
        file.writestr(transfer.MANIFEST,json.dumps({
            "schema":transfer.SCHEMA,"project_name":"CRCTest",
            "files":[{"path":key,"bytes":len(payload),
                      "sha256":sha256(payload).hexdigest()}],
        }))
    mutated=bytearray(archive.read_bytes())
    place=mutated.find(payload)
    assert place>=0
    mutated[place:place+1]=b"X"
    archive.write_bytes(mutated)
    assert transfer.archive_info(archive)["files"]==1
    with pytest.raises(workspace.WorkshopError,match="beschädigt"):
        transfer.restore_archive(archive)
    assert not (suite/"work"/"CRCTest").exists()
    assert not list((suite/"work").glob(".restore-project-*"))
    assert not list((suite/"work"/workspace.BASELINES).glob(".restore-metadata-*"))
    assert source.read_bytes()==original

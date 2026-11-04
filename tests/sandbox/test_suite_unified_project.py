"""Real source -> image edit -> Noesis revision -> audit -> validated mod ZIP.

Tests use an isolated work/ tree. Never install into a game, never call a
mock renderer and never count a ZIP's mere existence as a successful build.
"""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from pathlib import Path
import json
import sys
import zipfile

from PIL import Image
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/"tools"),str(ROOT/"src")]

import hud_menu_workspace as hud
import se_asset_package as package
import suite_unified_project as flow
from suite_hud_menu_session import read_session
from origins_visual_document import VisualXamlDocument

XAML=(b'<?xml version="1.0" encoding="utf-8"?>'
      b'<UserControl xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation">'
      b'<Grid><Button Name="MainButton" Width="200" Content="OLD"/></Grid>'
      b'</UserControl>')


@pytest.fixture
def isolated(tmp_path,monkeypatch):
    root=tmp_path/"suite"
    work=root/"work"
    work.mkdir(parents=True)
    monkeypatch.setattr(hud,"WORK",work)
    monkeypatch.setattr(hud,"ROOT",root)
    monkeypatch.setattr(hud,"DEFAULT",work/"hud-menu-werkstatt")
    monkeypatch.setattr(package,"ROOT",root)
    monkeypatch.setattr(package,"WORK",work)
    monkeypatch.setattr(package,"OUT",work/"se-asset-mods")
    return root,work


def _png_bytes(color):
    stream=BytesIO()
    Image.new("RGBA",(48,30),color).save(stream,"PNG")
    return stream.getvalue()


def test_single_real_editable_project_roundtrips_and_builds_exact_zip(
    isolated,tmp_path
):
    _,work=isolated
    project=flow.new_project("origins-menue")
    pipeline=flow.ProjectPipeline(project)
    assert pipeline.activate()==project
    assert flow.project_from_recent()==project
    bitmap=tmp_path/"Shield.png"
    bitmap.write_bytes(_png_bytes((50,80,120,255)))
    actual_png=pipeline.import_image(bitmap)
    assert actual_png.is_file() and bitmap.read_bytes()==_png_bytes((50,80,120,255))
    imported_rel=actual_png.relative_to(project).as_posix()
    assert imported_rel=="Override/Assets/GUI/Images/Shield.png"
    # The SAME project's pixel editor writes the file using the real
    # compare-and-swap SHA guard, never changing the user's original PNG.
    hud.write_png(imported_rel,_png_bytes((220,90,35,240)),
                  project=project,expected_sha256=sha256(
                      actual_png.read_bytes()).hexdigest())
    assert actual_png.read_bytes()!=bitmap.read_bytes()

    original=tmp_path/"FrontendMenus.xaml"
    original.write_bytes(XAML)
    saved_original=pipeline.register_original_xaml(original)
    assert saved_original.is_file()
    assert pipeline.original_xaml()==saved_original
    assert saved_original.read_bytes()==XAML
    doc=VisualXamlDocument(saved_original)
    assert doc.attributes((0,0))["Content"]=="OLD"
    doc.edit((0,0),"Content","NEUES MENUE")
    revision=doc.save_revision(project,publish=True,overwrite_existing=True)
    assert revision["published"] is True
    assert pipeline.latest_visual_revision()==Path(revision["revision_dir"])
    assert VisualXamlDocument.reopen(pipeline.latest_visual_revision()).attributes(
        (0,0))["Content"]=="NEUES MENUE"
    patch=project/"Patches"/"Assets"/"GUI"/"XAML"/"FrontendMenus.xaml"
    assert patch.is_file()
    assert b"NEUES MENUE" in patch.read_bytes()

    check=pipeline.audit()
    assert check["assets"]==2
    assert check["original_game_files_modified"] is False
    assert "Shield.png" in " ".join(check["warnings"])
    built=pipeline.build(guid="spritesuite.origins-menus",name="Origins Menue",
                         output=work/"se-asset-mods"/"out-first")
    assert built["zip_verified_against_project"] is True
    assert built["asset_count"]==2
    assert built["installed_into_game"] is False
    assert built["native_game_runtime_verified"] is False
    assert Path(built["receipt"]).is_file()
    archive=Path(built["zip"])
    assert sha256(archive.read_bytes()).hexdigest()==built["zip_sha256"]
    with zipfile.ZipFile(archive) as zipped:
        assert zipped.testzip() is None
        prefix="BepInEx/plugins/spritesuite.origins-menus/"
        assert zipped.read(prefix+imported_rel)==actual_png.read_bytes()
        assert zipped.read(prefix+"Patches/Assets/GUI/XAML/FrontendMenus.xaml")==patch.read_bytes()
        meta=json.loads(zipped.read(prefix+"info.json"))
        assert meta["Manifest"]==0 and meta["GUID"]=="spritesuite.origins-menus"
    assert original.read_bytes()==XAML
    assert bitmap.read_bytes()==_png_bytes((50,80,120,255))
    assert saved_original.read_bytes()==XAML

    # Continue later, edit the SAME project and export another revision.
    next_project=flow.ProjectPipeline(flow.project_from_recent())
    assert next_project.original_xaml()==saved_original
    assert next_project.latest_visual_revision()==Path(revision["revision_dir"])
    doc2=VisualXamlDocument.reopen(next_project.latest_visual_revision())
    doc2.edit((0,0),"Content","WEITERBEARBEITET")
    version2=doc2.save_revision(project,publish=True,overwrite_existing=True)
    assert version2["revision"]==2
    assert next_project.latest_visual_revision()==Path(version2["revision_dir"])
    exported2=next_project.build(guid="spritesuite.origins-menus",
                  name="Origins Menue",output=work/"se-asset-mods"/"out-second")
    assert exported2["assets_sha256"]!=built["assets_sha256"]
    assert exported2["zip_sha256"]!=built["zip_sha256"]
    assert archive.is_file()  # never overwritten


def test_rejects_empty_project_and_does_not_claim_package(isolated):
    _,work=isolated
    project=flow.new_project("empty-assets")
    with pytest.raises(package.AssetModError,match="Keine Override-/Patch"):
        flow.ProjectPipeline(project).build(guid="valid.id",name="Empty",
                      output=work/"se-asset-mods"/"should-not-exist")
    assert not (work/"se-asset-mods"/"should-not-exist.zip").exists()


def test_full_xaml_not_misclassified_as_an_installable_patch(isolated,tmp_path):
    _,_=isolated
    project=flow.new_project("xaml-source")
    pipeline=flow.ProjectPipeline(project)
    full=tmp_path/"FrontendMenus.xaml"
    full.write_bytes(XAML)
    with pytest.raises(flow.UnifiedFlowError,match="Seiten-Designer"):
        pipeline.import_patch(full)
    assert pipeline.assets()==[]
    assert pipeline.register_original_xaml(full).exists()
    assert pipeline.assets()==[]  # source itself is NOT an authored mod patch


def test_wrong_xaml_or_changed_original_snapshot_fails_closed(isolated,tmp_path):
    _,work=isolated
    project=flow.new_project("bad-source")
    pipeline=flow.ProjectPipeline(project)
    original=tmp_path/"FrontendMenus.xaml"
    original.write_bytes(XAML)
    snapshot=pipeline.register_original_xaml(original)
    snapshot.write_bytes(XAML.replace(b"OLD",b"BAD"))
    with pytest.raises(flow.UnifiedFlowError,match="SHA-256|geändert"):
        pipeline.original_xaml()
    with pytest.raises(flow.UnifiedFlowError,match="Original-XAML-Snapshot"):
        pipeline.latest_visual_revision()


def test_cannot_create_duplicate_workspace_or_leave_worktree(isolated,tmp_path):
    _,work=isolated
    first=flow.new_project("one-project")
    assert first==work/"projects"/"one-project"
    with pytest.raises(flow.UnifiedFlowError,match="existiert"):
        flow.new_project("one-project")
    with pytest.raises(ValueError):
        flow.ProjectPipeline(tmp_path/"outside")
    with pytest.raises(flow.UnifiedFlowError):
        flow.new_project("../escape")


def test_legacy_menu_commands_are_never_claimed_to_be_runtime_verified(
    isolated,tmp_path
):
    _,work=isolated
    project=flow.new_project("legacy-menu")
    source=tmp_path/"custom.xaml"
    source.write_text(
        '<Patch><Operation Type="Add" XPath="/n:UserControl">'
        '<Content><Button xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" '
        'CommandParameter="LegacyStart"/></Content></Operation></Patch>',
        encoding="utf8")
    file=flow.ProjectPipeline(project).import_patch(
          source,game_document="XAML/FrontendMenus.xaml")
    assert file.is_file()
    audit=flow.ProjectPipeline(project).audit()
    assert any("C#-Handler" in w for w in audit["warnings"])
    result=flow.ProjectPipeline(project).build(guid="legacy.test",name="Legacy",
              output=work/"se-asset-mods"/"legacy")
    assert result["native_game_runtime_verified"] is False
    assert result["installed_into_game"] is False



def test_portable_backup_restores_noesis_original_and_editable_revisions(
    isolated, tmp_path, monkeypatch,
):
    import hud_menu_project_transfer as transfer
    import hud_menu_layout as layout
    first_root, first_work=isolated
    project=flow.new_project("portable-noesis")
    pipeline=flow.ProjectPipeline(project)
    pipeline.activate()
    original=tmp_path/"FrontendMenus.xaml"
    original.write_bytes(XAML)
    pipeline.register_original_xaml(original)
    document=VisualXamlDocument(pipeline.original_xaml())
    document.edit((0,0),"Content","Erste portable Bearbeitung")
    first_revision=document.save_revision(project,publish=True,
                                          overwrite_existing=True)
    expected=Path(first_revision["revision_dir"])
    assert expected.is_relative_to(hud._metadata_dir(project))
    assert pipeline.latest_visual_revision()==expected
    image=tmp_path/"Flag.png"
    image.write_bytes(_png_bytes((16,60,119,255)))
    pipeline.import_image(image)
    first_export=pipeline.build(guid="portable.noesis",name="First",
        output=first_work/"se-asset-mods"/"before-backup")
    assert pipeline.latest_export()["zip_verified_against_project"]

    backup=tmp_path/"editable-project-backup.zip"
    result=transfer.create_archive(project,backup)
    assert result["files"]>=7
    with zipfile.ZipFile(backup) as zipped:
        names=set(zipped.namelist())
        assert "metadata/origins-sources/current.json" in names
        assert any(n.startswith("metadata/origins-sources/") and
                   n.endswith("/FrontendMenus.xaml") for n in names)
        assert any(n.endswith("rev-0001/edited.xaml") for n in names)
        assert "metadata/origins-sources/last-export.json" not in names
        assert original.read_bytes()==XAML

    second_root=tmp_path/"second-suite"
    second_work=second_root/"work"
    second_work.mkdir(parents=True)
    monkeypatch.setattr(hud,"ROOT",second_root)
    monkeypatch.setattr(hud,"WORK",second_work)
    monkeypatch.setattr(hud,"DEFAULT",second_work/"hud-menu-werkstatt")
    monkeypatch.setattr(layout,"WORK",second_work)
    monkeypatch.setattr(package,"ROOT",second_root)
    monkeypatch.setattr(package,"WORK",second_work)
    monkeypatch.setattr(package,"OUT",second_work/"se-asset-mods")

    restored=transfer.restore_archive(backup,project_name="CopiedProject")
    copy=Path(restored["project"])
    copied=flow.ProjectPipeline(copy)
    assert copied.original_xaml().read_bytes()==XAML
    resumed=copied.latest_visual_revision()
    assert resumed is not None
    assert resumed.is_relative_to(hud._metadata_dir(copy))
    reopened=VisualXamlDocument.reopen(resumed)
    assert reopened.attributes((0,0))["Content"]=="Erste portable Bearbeitung"
    assert copied.latest_export() is None  # stale machine-specific ZIP not archived
    reopened.edit((0,0),"Content","Nach Wiederherstellung")
    revision2=reopened.save_revision(copy,publish=True,
                                    overwrite_existing=True)
    assert revision2["revision"]==2
    done=copied.build(guid="portable.noesis",name="After restore",
                      output=second_work/"se-asset-mods"/"restored")
    with zipfile.ZipFile(done["zip"]) as zipped:
        assert b"Nach Wiederherstellung" in zipped.read(
            "BepInEx/plugins/portable.noesis/"
            "Patches/Assets/GUI/XAML/FrontendMenus.xaml")
    assert original.read_bytes()==XAML


def test_noesis_archive_whitelist_rejects_foreign_paths():
    import hud_menu_project_transfer as transfer
    from hud_menu_workspace import WorkshopError
    with pytest.raises(WorkshopError):
        transfer._safe_member("metadata/origins-sources/last-export.json")
    with pytest.raises(WorkshopError):
        transfer._safe_member("metadata/origins-revisions/x.xaml/rev-0001/evil.exe")
    with pytest.raises(WorkshopError):
        transfer._safe_member("metadata/origins-revisions/../x.xaml/rev-0001/edited.xaml")

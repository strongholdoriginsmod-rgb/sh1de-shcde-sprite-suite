"""Synthetic HUD & menu editing: version-neutral, no game or source writes."""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from pathlib import Path
import json
import os
import sys

from PIL import Image
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/"tools"),str(ROOT/"src")]
import hud_menu_workspace as work
import se_asset_package as se
from suite_hud_menu_editor import stroke


@pytest.fixture
def example(tmp_path,monkeypatch):
    suite=tmp_path/"SpriteSuite"
    (suite/"work").mkdir(parents=True)
    monkeypatch.setattr(work,"ROOT",suite)
    monkeypatch.setattr(work,"WORK",suite/"work")
    monkeypatch.setattr(se,"WORK",suite/"work")
    monkeypatch.setattr(se,"OUT",suite/"work"/"se-asset-mods")
    project=suite/"work"/"my-hud-menu"
    source=tmp_path/"user-owned-menu.png"
    image=Image.new("RGBA",(11,7),(12,34,56,121))
    image.putpixel((5,4),(220,45,19,0))
    image.save(source)
    return project,source,image,suite


def png(image):
    buf=BytesIO();image.save(buf,format="PNG");return buf.getvalue()


def test_import_preserves_alpha_dimensions_and_never_changes_source(example):
    project,source,original,suite=example
    old=source.read_bytes()
    out=work.import_image(source,folder="HUD / UI-Sprites",project=project)
    assert out.relative_to(project).as_posix()=="Override/Assets/GUI/Sprites/user-owned-menu.png"
    with Image.open(out) as current:
        assert current.size==(11,7)
        assert current.getpixel((5,4))==(220,45,19,0)
        assert current.getpixel((0,0))==(12,34,56,121)
    assert source.read_bytes()==old
    entries=work.list_assets(project)
    assert len(entries)==1 and entries[0].status=="Unverändert"
    assert entries[0].baseline_path.is_file()
    assert entries[0].baseline_path.parent.parent.parent!=project
    assert not (project/work.BASELINES).exists()
    assert work.audit_assets(project)["assets"]==1


def test_new_blank_image_duplicate_and_resource_key_preserved(example):
    project,source,original,suite=example
    first=work.create_image("PauseMenu",32,16,project=project)
    with Image.open(first) as image:
        assert image.size==(32,16)
        assert image.getpixel((10,7))==(0,0,0,0)
    copy=work.duplicate_image(
        "Override/Assets/GUI/Images/PauseMenu.png",
        folder="HUD / UI-Sprites",name="PauseMenuAlt",project=project)
    assert copy.relative_to(project).as_posix()==(
        "Override/Assets/GUI/Sprites/PauseMenuAlt.png")
    assert first.read_bytes()==copy.read_bytes()
    assert len(work.list_assets(project))==2
    assert work.audit_assets(project)["assets"]==2


@pytest.mark.parametrize("unsafe",["../other","C:/Windows/sprite","con",
                                      ".hidden","A"*100,"bad:colon",r"a\b"])
def test_unsafe_names_are_not_accepted(example,unsafe):
    project,source,original,suite=example
    with pytest.raises(work.WorkshopError):
        work.create_image(unsafe,5,5,project=project)
    assert not list(project.rglob("*.png"))


def test_import_never_overwrites_existing_resource_or_source(example):
    project,source,original,suite=example
    first=work.import_image(source,project=project)
    before=first.read_bytes()
    with pytest.raises(work.WorkshopError,match="already exists|never replaced"):
        work.import_image(source,project=project)
    assert first.read_bytes()==before


def test_edited_preview_and_restoration_keeps_a_versioned_backup(example):
    project,source,original,suite=example
    output=work.import_image(source,project=project)
    relative=output.relative_to(project).as_posix()
    imported=output.read_bytes()
    current=sha256(imported).hexdigest()
    changed=original.copy();changed.putpixel((0,0),(99,88,77,66))
    work.write_png(relative,png(changed),project=project,
                   expected_sha256=current)
    entries=work.list_assets(project)
    assert entries[0].status=="Bearbeitet"
    old_edit=output.read_bytes()
    assert old_edit!=imported
    work.restore_image(relative,project=project)
    assert output.read_bytes()==imported
    assert len(list((work._metadata_dir(project)/"revisions").glob("*.png")))==1
    assert list((work._metadata_dir(project)/"revisions").glob("*.png"))[0].read_bytes()==old_edit
    assert work.list_assets(project)[0].status=="Unverändert"


def test_concurrent_editor_writes_cannot_overwrite_newer_changes(example):
    project,source,original,suite=example
    output=work.import_image(source,project=project)
    relative=output.relative_to(project).as_posix()
    stale=sha256(output.read_bytes()).hexdigest()
    altered=original.copy();altered.putpixel((2,3),(1,2,3,4))
    output.write_bytes(png(altered))
    with pytest.raises(work.WorkshopError,match="changed externally"):
        work.write_png(relative,png(original),project=project,
                       expected_sha256=stale)
    assert output.read_bytes()==png(altered)


def test_bad_or_tampered_baseline_is_not_silent_original(example):
    project,source,original,suite=example
    out=work.import_image(source,project=project)
    relative=out.relative_to(project).as_posix()
    baseline,meta=work._baseline(project,relative)
    baseline.write_bytes(b"forged original")
    with pytest.raises(work.WorkshopError,match="Corrupt baseline"):
        work.list_assets(project)
    with pytest.raises(work.WorkshopError,match="SHA-256"):
        work.restore_image(relative,project=project)


def test_root_of_work_and_adjacent_game_are_never_workspace(example):
    project,source,original,suite=example
    with pytest.raises(work.WorkshopError):
        work.workspace(suite/"work",create=True)
    with pytest.raises(work.WorkshopError):
        work.workspace(suite.parent/"Stronghold Crusader Definitive Edition",create=True)
    assert not (suite.parent/"Stronghold Crusader Definitive Edition").exists()


def test_synthetic_xaml_patch_is_valid_and_in_package(example):
    project,source,original,suite=example
    work.import_image(source,project=project)
    patch=suite.parent/"my_patch.xaml"
    patch.write_text(
        '<Patch><Operation Type="SetAttribute" XPath="/ResourceDictionary" '
        'Name="Opacity" Value="0.75"/></Patch>',encoding="utf8")
    out=work.import_patch(patch,project=project)
    assert out.relative_to(project).as_posix()=="Patches/Assets/GUI/my_patch.xaml"
    assert len(work.list_assets(project))==2
    report=work.audit_assets(project)
    assert report["assets"]==2
    built=se.build(project,"europemenu",name="Europe menu",author="Test")
    assert built["runtime_dll"] is False
    assert built["se_version_required"] is None
    assert built["manifest"]["Manifest"]==0
    assert Path(built["zip"]).is_file()
    assert patch.read_text("utf8").startswith("<Patch>")
    assert not (suite.parent/"Stronghold Crusader Definitive Edition").exists()


def test_unsafe_or_invalid_xaml_is_rejected_without_output(example):
    project,source,original,suite=example
    bad=suite.parent/"invalid.xaml"
    bad.write_text('<!DOCTYPE danger><Patch/>',encoding="utf8")
    with pytest.raises((work.WorkshopError,se.AssetModError)):
        work.import_patch(bad,project=project)
    assert not list(project.rglob("*.xaml"))


@pytest.mark.parametrize("width,height",[(0,1),(2,0),(99999,8),(4096,4097)])
def test_invalid_dimensions_are_rejected(example,width,height):
    project,_,_,_=example
    with pytest.raises(work.WorkshopError):
        work.create_image("Wrong",width,height,project=project)


def test_pixel_tools_modify_only_a_copy():
    source=Image.new("RGBA",(7,7),(1,2,3,255))
    edited=source.copy()
    assert stroke(edited,(2,2),mode="Pinsel",rgba=(2,200,99,150),brush=1)
    assert edited.getpixel((2,2))==(2,200,99,150)
    assert stroke(edited,(2,2),mode="Radierer",rgba=(0,0,0,0),brush=1)
    assert edited.getpixel((2,2))==(0,0,0,0)
    assert not stroke(edited,(-1,0),mode="Pinsel",
                      rgba=(1,1,1,1),brush=1)
    assert source.getpixel((2,2))==(1,2,3,255)
    filled=Image.new("RGBA",(5,5),(9,9,9,255))
    filled.putpixel((4,4),(80,80,80,255))
    assert stroke(filled,(2,2),mode="Füllen",rgba=(70,20,10,200))
    assert filled.getpixel((4,4))==(80,80,80,255)


def test_suite_and_editors_have_real_named_connections():
    main=(ROOT/"tools/suite_universal.pyw").read_text("utf8")
    gui=(ROOT/"tools/suite_hud_menu_workshop.py").read_text("utf8")
    assert 'self.hud_menu_tab = HudMenuWorkshop(self.notebook, self)' in main
    assert 'text="HUD & Menüs"' in main
    assert '("HUD & Menüs", "HUD & menus", self.hud_menu_tab)' in main
    for name in ("Sh1HudStudio","OriginsGraphicsTab","ExchangeTab"):
        assert name in main
    assert "def import_origins(" in gui
    assert "checked_source_file" in gui
    assert "def goto_noesis(" in gui
    assert "se_asset_package.py" in gui

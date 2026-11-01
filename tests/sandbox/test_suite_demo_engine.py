"""Demo Mode contracts: production operations, genuine outputs, isolation."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from zipfile import ZipFile
import json
import sys
import xml.etree.ElementTree as ET

import pytest
from PIL import Image

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/"tools"),str(ROOT/"src")]
import hud_menu_workspace as work
import hud_menu_layout as layout
import se_asset_package as asset_mod
from suite_demo_engine import DemoSession,MODULES
from origins_visual_document import VisualXamlDocument

ALL_OFFLINE=[x.key for x in MODULES if x.key!="video"]


@pytest.fixture
def isolated(tmp_path,monkeypatch):
    root=tmp_path/"suite"
    wd=root/"work";wd.mkdir(parents=True)
    monkeypatch.setattr(work,"ROOT",root)
    monkeypatch.setattr(work,"WORK",wd)
    monkeypatch.setattr(layout,"WORK",wd)
    monkeypatch.setattr(asset_mod,"ROOT",root)
    monkeypatch.setattr(asset_mod,"WORK",wd)
    monkeypatch.setattr(asset_mod,"OUT",wd/"se-asset-mods")
    return root


@pytest.mark.parametrize("module",ALL_OFFLINE)
def test_module_executes_all_real_steps_and_stored_receipts(isolated,module):
    if module in ("campaign","season"):
        from suite_demo_engine import runtime_qa
        if not runtime_qa.COMPILER.is_file():
            pytest.skip("Managed C# compiler is missing in this Windows environment")
    session=DemoSession.start(module)
    assert session.project.is_dir()
    assert session.next_step==0
    output_hashes={}
    for step in session.module.steps:
        report=session.execute_next()
        assert report["title"]==step.title
        assert report["game_original_modified"] is False
        assert report["native_game_calls"] is False
        assert report["outputs"]
        for asset in report["outputs"]:
            file=Path(asset["path"])
            assert file.is_file()
            assert file.stat().st_size==asset["bytes"]
            assert len(asset["sha256"])==64
            assert asset["sha256"]==sha256(file.read_bytes()).hexdigest()
            if "snapshot" in asset:
                assert Path(asset["snapshot"]).read_bytes()==file.read_bytes()
            output_hashes[file]=asset["sha256"]
    assert session.complete
    verified=session.verify_receipts()
    assert verified["valid"],verified
    assert verified["historical_snapshots"]>=len(session.module.steps)
    saved=json.loads((session.root/"demo-protokoll.json").read_text("utf8"))
    assert saved["module"]==module
    assert saved["completed"] is True
    assert len(saved["steps"])==len(session.module.steps)
    assert saved["installation_modified"] is False
    assert not list(isolated.rglob("Game.exe"))
    assert not list(isolated.rglob("StrongholdCrusader.exe"))
    zip_paths=[Path(item["path"]) for item in session.receipts[-1]["outputs"]
               if item["path"].lower().endswith(".zip")]
    for p in zip_paths:
        with ZipFile(p) as archive:
            assert archive.testzip() is None
            assert archive.namelist()
            assert all(name.startswith("BepInEx/plugins/")
                       for name in archive.namelist())


def test_original_noesis_code_selected_by_user_is_read_only(isolated,tmp_path):
    original=tmp_path/"FrontendMenus.xaml"
    original.write_text('''<UserControl
       xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation">
      <Grid Name="RealMain">
        <Button Name="RealButton" Content="Existing"
          Command="{Binding ButtonMainMenuCommand}" CommandParameter="Roadmap"/>
      </Grid></UserControl>''',encoding="utf8")
    old=original.read_bytes()
    session=DemoSession.start("noesis",source=original)
    while not session.complete:
        session.execute_next()
    assert original.read_bytes()==old
    active=session.project/"Patches/Assets/GUI/XAML/FrontendMenus.xaml"
    assert active.is_file()
    assert b"SpriteSuiteDemoAction" in active.read_bytes()
    assert session.verify_receipts()["valid"]
    revisions=list((session.root/"belege").rglob("*.xaml"))
    assert len(revisions)>=3


def test_original_xaml_patch_demo_applies_named_target(isolated,tmp_path):
    source=tmp_path/"FrontendMenus.xaml"
    source.write_text('''<UserControl
       xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation">
       <Grid Name="Root"><Button Name="RunButton" Margin="0,0,0,0"
         Content="Run"/></Grid></UserControl>''',encoding="utf8")
    saved=source.read_bytes()
    run=DemoSession.start("patch",source=source)
    while not run.complete:run.execute_next()
    assert source.read_bytes()==saved
    assert b"Aus Original-Patch weiterbearbeitet" in (
        run.project/"Patches/Assets/GUI/XAML/FrontendMenus.xaml").read_bytes()
    assert run.verify_receipts()["valid"]


def test_original_file_modified_during_demo_blocks_false_success(isolated,tmp_path):
    source=tmp_path/"FrontendMenus.xaml"
    source.write_bytes(
        b'<UserControl xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation">'
        b'<Grid Name="Root"><Button Name="Demo"/></Grid></UserControl>')
    run=DemoSession.start("noesis",source=source)
    run.execute_next()
    source.write_bytes(source.read_bytes()+b"<!-- new revision outside demo -->")
    with pytest.raises(RuntimeError,match="Originaldatei"):
        run.execute_next()
    assert run.next_step==1


def test_changed_private_output_is_a_diagnostic_not_a_write_lock(isolated):
    session=DemoSession.start("pixels")
    while not session.complete:session.execute_next()
    edited=session.project/"Override/Assets/GUI/Sprites/DemoHUD.png"
    assert edited.is_file()
    with Image.open(edited) as inp:render=inp.convert("RGBA")
    render.putpixel((2,3),(255,0,0,255))
    render.save(edited)
    check=session.verify_receipts()
    assert check["valid"] is False
    assert "extern verändert" in check["problems"][0]
    # User is permitted to keep custom edits; verification does not rewrite.
    assert Image.open(edited).convert("RGBA").getpixel((2,3))==(255,0,0,255)


def test_error_in_real_export_does_not_mark_step_as_success(isolated,monkeypatch):
    run=DemoSession.start("pixels")
    run.execute_next();run.execute_next()
    def broken(*_args,**_kwargs):
        raise RuntimeError("Disk full in actual builder")
    monkeypatch.setattr(asset_mod,"build",broken)
    with pytest.raises(RuntimeError,match="Disk full"):
        run.execute_next()
    assert run.next_step==2
    assert len(run.receipts)==2
    assert not run.complete


def test_prepared_video_demonstrates_real_import_if_original_available(isolated):
    original=Path(r"E:\SpriteSuite_Origins_Manuell_20261101\work\private-origins-static-qa"
                  r"\Override\Assets\GUI\Video\front_end_background_low.webm")
    if not original.is_file():
        pytest.skip("No user-owned real WebM available to test actual replacement")
    digest=sha256(original.read_bytes()).hexdigest()
    run=DemoSession.start("video",source=original)
    while not run.complete:
        run.execute_next()
    assert sha256(original.read_bytes()).hexdigest()==digest
    assert run.verify_receipts()["valid"]
    zip_path=Path(run.receipts[-1]["outputs"][0]["path"])
    with ZipFile(zip_path) as result:
        member=next(s for s in result.namelist() if s.endswith("demo-background.webm"))
        assert sha256(result.read(member)).hexdigest()==digest


@pytest.mark.parametrize("invalid",["", "does-not-exist", "../escape", "VIDEO"])
def test_unknown_modules_cannot_create_arbitrary_outputs(isolated,invalid):
    with pytest.raises(ValueError):
        DemoSession.start(invalid)
    assert not (isolated/"work"/"demo-sessions").exists()


def test_video_module_requires_a_real_selected_file(isolated):
    with pytest.raises(ValueError,match=r"\.webm"):
        DemoSession.start("video")
    assert not (isolated/"work"/"demo-sessions").exists()

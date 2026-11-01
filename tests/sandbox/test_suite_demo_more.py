"""More real end-to-end specialty tours with measurable image deltas."""
from __future__ import annotations
import json
from pathlib import Path
import sys
from zipfile import ZipFile
from PIL import Image,ImageChops
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/"tools"),str(ROOT/"src")]
import hud_menu_workspace as work
import hud_menu_layout as layout
import se_asset_package as packages
import origins_menu_mock_qa as mock
from suite_demo_engine import DemoSession,MODULES


@pytest.fixture
def isolated(tmp_path,monkeypatch):
    home=tmp_path/"suite";(home/"work").mkdir(parents=True)
    monkeypatch.setattr(work,"ROOT",home)
    monkeypatch.setattr(work,"WORK",home/"work")
    monkeypatch.setattr(layout,"WORK",home/"work")
    monkeypatch.setattr(packages,"ROOT",home)
    monkeypatch.setattr(packages,"WORK",home/"work")
    monkeypatch.setattr(packages,"OUT",home/"work"/"se-asset-mods")
    return home


NAMES=("background_masked","button_states","vegetation","gold_relief","menu_behavior")


@pytest.mark.parametrize("name",NAMES)
def test_all_real_production_extra_modules_replay_and_integrity(isolated,name):
    assert name in {m.key for m in MODULES}
    session=DemoSession.start(name)
    for index,step in enumerate(session.module.steps):
        proof=session.execute_next()
        assert proof["index"]==index and proof["outputs"]
        assert all(Path(f["path"]).is_file() for f in proof["outputs"])
    assert session.complete
    check=session.verify_receipts()
    assert check["valid"],check
    assert check["historical_snapshots"]>=len(session.module.steps)
    meta=json.loads((session.root/"demo-protokoll.json").read_text("utf8"))
    assert meta["completed"] is True
    assert meta["installation_modified"] is False
    assert not (isolated/"BepInEx").exists()


def test_background_mask_blend_modifies_exactly_selected_pixels(isolated):
    session=DemoSession.start("background_masked")
    while not session.complete:session.execute_next()
    original=Image.open(session.data["mask_source"]).convert("RGBA")
    edited=Image.open(session.project/session.data["extra_asset"]).convert("RGBA")
    assert original.size==edited.size
    data=json.loads((session.samples/"background-blend-report.json").read_text("utf8"))
    assert data["outside_mask_bit_exact"] is True
    assert data["outside_mask_changed_pixels"]==0
    assert data["alpha_bit_exact"] is True
    assert data["changed_pixels"]>0
    # Original pixels inside the explicit subtract/protected selection remain.
    mask=Image.open(session.data["mask_result"]["mask"]).convert("L")
    x0,y0,_,_=session.data["mask_crop"]
    assert mask.getpixel((89,54))==0
    assert original.getpixel((x0+89,y0+54))==edited.getpixel((x0+89,y0+54))
    assert original.getpixel((10,10))==edited.getpixel((10,10))
    assert session.verify_receipts()["valid"]


def test_button_four_states_are_distinct_and_edited_state_equals_hover(isolated):
    session=DemoSession.start("button_states")
    while not session.complete:session.execute_next()
    states=[Image.open(session.samples/("ButtonState-"+x+".png")).convert("RGBA")
            for x in ("ruhend","ueberfahren","gedrueckt","aus")]
    assert len({s.tobytes() for s in states})==4
    with Image.open(session.project/session.data["extra_asset"]) as result:
        assert result.convert("RGBA").tobytes()==states[1].tobytes()
    archive=next(Path(a["path"]) for a in session.receipts[-1]["outputs"])
    with ZipFile(archive) as z:assert z.testzip() is None


def test_vegetation_original_foot_position_and_recomposition_are_real(isolated):
    session=DemoSession.start("vegetation")
    while not session.complete:session.execute_next()
    entries=json.loads((session.samples/"vegetation-position-report.json").read_text("utf8"))
    assert len(entries)==2
    assert all(len(item["foot_from_below"])==2 for item in entries)
    first=Image.open(session.samples/"VegetationOriginalComposite.png").convert("RGBA")
    final=Image.open(session.project/session.data["extra_asset"]).convert("RGBA")
    assert first.size==(156,144) and final.size==(156,144)
    assert ImageChops.difference(first,final).getbbox() is not None


def test_gold_silver_relief_uses_same_shape_but_different_pixels(isolated):
    session=DemoSession.start("gold_relief")
    while not session.complete:session.execute_next()
    compare=Image.open(session.samples/"GoldAndSilverRelief.png").convert("RGBA")
    assert compare.size==(192,96)
    first=compare.crop((0,0,96,96))
    second=compare.crop((96,0,192,96))
    # In RGBA, unchanged alpha would mask RGB-only differences in getbbox.
    assert ImageChops.difference(first.convert('RGB'),second.convert('RGB')).getbbox() is not None
    mask=Image.open(session.samples/"GoldEmblemMask.png").convert("L")
    assert mask.getpixel((48,47))==255
    assert mask.getpixel((0,0))==0
    actual=Image.open(session.project/session.data["extra_asset"]).convert("RGBA")
    assert actual.getpixel((48,47))!=actual.getpixel((0,0))


def test_failed_menu_fake_host_does_not_mark_demo_success(isolated,monkeypatch,tmp_path):
    demo=DemoSession.start("menu_behavior")
    demo.execute_next()
    broken=tmp_path/"broken-menu-qa.cs"
    broken.write_text("not valid C#",encoding="utf8")
    monkeypatch.setattr(mock,"HARNESS",broken)
    with pytest.raises(work.WorkshopError,match="failed"):
        demo.execute_next()
    assert demo.next_step==1
    assert len(demo.receipts)==1
    assert not demo.complete
    report=json.loads((demo.root/"demo-protokoll.json").read_text("utf8"))
    assert report["completed"] is False


def test_menu_mock_demo_executed_real_unmodified_adapter_with_assertions(isolated):
    demo=DemoSession.start("menu_behavior")
    while not demo.complete:demo.execute_next()
    logfile=Path(demo.data["mock_report"]["log"]).read_text("utf8")
    assert "SPRITESUITE_MOCK_MENU_ASSERTIONS=29" in logfile
    assert "MOCK_HARMONY_PATCHES=1" in logfile
    assert "MOCK_HARMONY_UNPATCHES=1" in logfile
    assert "REAL_GAME_DLL_LOADED=0" in logfile
    assert demo.verify_receipts()["valid"]

"""Actual Windows/Tk Demo UI event handling with real processing and export."""
from pathlib import Path
import sys
import tkinter as tk

from PIL import Image
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/"tools"),str(ROOT/"src")]
import hud_menu_workspace as work
import hud_menu_layout as layout
import se_asset_package as asset_mod
import suite_demo_mode
from suite_demo_mode import DemoMode
from suite_demo_engine import MODULES


@pytest.fixture(scope="module")
def tk_root():
    try:
        root=tk.Tk()
        root.withdraw()
    except tk.TclError as error:
        pytest.skip("Windows Tcl/Tk could not start: "+str(error))
    yield root
    root.destroy()


@pytest.fixture
def gui(tmp_path,monkeypatch,tk_root):
    suite=tmp_path/"suite";wd=suite/"work"
    wd.mkdir(parents=True)
    monkeypatch.setattr(work,"ROOT",suite)
    monkeypatch.setattr(work,"WORK",wd)
    monkeypatch.setattr(layout,"WORK",wd)
    monkeypatch.setattr(asset_mod,"ROOT",suite)
    monkeypatch.setattr(asset_mod,"WORK",wd)
    monkeypatch.setattr(asset_mod,"OUT",wd/"se-asset-mods")
    editor=DemoMode(tk_root)
    tk_root.update()
    try:
        yield editor,wd,monkeypatch
    finally:
        editor.destroy()


def choose(editor,key):
    index=next(i for i,m in enumerate(MODULES) if m.key==key)
    editor.module_list.selection_clear(0,"end")
    editor.module_list.selection_set(index)
    editor._select_module()
    assert editor.active_key==key


def test_real_gui_executes_png_demo_and_shows_actual_pixels(gui):
    editor,wd,_=gui
    assert editor.winfo_exists()
    assert editor.module_list.size()==len(MODULES)
    choose(editor,"pixels")
    assert editor.next_button.instate(("disabled",))
    run=editor.start()
    assert not editor.next_button.instate(("disabled",))
    first=editor.execute()
    assert len(first["outputs"])==2
    assert editor._file_map
    assert "1 von 3 Schritten" not in editor.progress.get()  # progress shows real action
    editor.run_all()
    assert run.complete
    assert editor.verify_outputs()
    assert editor.next_button.instate(("disabled",))
    assert any(Path(item["path"]).suffix==".zip" for item in run.receipts[-1]["outputs"])
    assert all(Path(info["path"]).is_file() for step in run.receipts for info in step["outputs"])


def test_module_switch_keeps_real_results_and_creates_distinct_project(gui):
    editor,wd,_=gui
    choose(editor,"layout")
    editor.run_all()
    old=editor.runs["layout"]
    assert old.complete
    assert editor.verify_outputs()
    choose(editor,"noesis")
    editor.run_all()
    new=editor.runs["noesis"]
    assert new.complete
    assert editor.verify_outputs()
    assert new.root!=old.root
    choose(editor,"layout")
    assert editor._run() is old
    assert editor.verify_outputs()


def test_user_original_xaml_file_accepted_and_never_overwritten(gui,tmp_path,monkeypatch):
    editor,wd,_=gui
    original=tmp_path/"FrontendMenus.xaml"
    original.write_text('''<UserControl
      xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation">
      <Grid Name="Root"><Button Name="Real" Content="Before"/></Grid>
      </UserControl>''',encoding="utf8")
    before=original.read_bytes()
    choose(editor,"noesis")
    monkeypatch.setattr(suite_demo_mode.filedialog,"askopenfilename",
                        lambda **_kw: str(original))
    editor.choose_original()
    assert editor.source_paths["noesis"]==original
    editor.run_all()
    assert editor.runs["noesis"].complete
    assert editor.verify_outputs()
    assert original.read_bytes()==before
    assert "Original-Menüseiten" in editor.module_details.get()


def test_video_missing_original_shows_error_and_does_not_claim_success(gui,monkeypatch):
    editor,wd,_=gui
    choose(editor,"video")
    errors=[]
    monkeypatch.setattr(suite_demo_mode.messagebox,"showerror",
                        lambda title,text,**_kw:errors.append((title,text)))
    assert editor.start() is None
    assert errors
    assert editor.next_button.instate(("disabled",))
    assert editor._run() is None
    assert not any(wd.rglob("*.webm"))


def test_existing_user_edits_warn_without_reverting(gui):
    editor,wd,_=gui
    choose(editor,"pixels")
    editor.run_all()
    assert editor.verify_outputs()
    file=editor._run().project/"Override/Assets/GUI/Sprites/DemoHUD.png"
    with Image.open(file) as source:
        edited=source.convert("RGBA")
    edited.putpixel((2,2),(2,3,4,255))
    edited.save(file)
    assert editor.verify_outputs() is False
    assert "Hinweise, keine Sperren" in editor.progress.get()
    assert Image.open(file).convert("RGBA").getpixel((2,2))==(2,3,4,255)



def test_demo_opens_actual_pixel_and_noesis_editors_on_its_outputs(gui):
    editor,wd,_=gui
    choose(editor,"pixels")
    editor.start()
    editor.execute()
    specialist=editor.open_editor()
    assert specialist is not None
    from suite_hud_menu_editor import HudMenuPixelEditor
    assert isinstance(specialist,HudMenuPixelEditor)
    assert specialist.winfo_exists()
    specialist.destroy()

    choose(editor,"noesis")
    editor.start()
    editor.execute()
    editor.execute()
    specialist=editor.open_editor()
    from suite_origins_visual_editor import OriginsVisualEditor
    assert isinstance(specialist,OriginsVisualEditor)
    assert any(x.attrs.get("CommandParameter")=="SpriteSuiteDemoAction"
               for x in specialist.doc.outline())
    specialist.destroy()



def test_selecting_earlier_step_shows_real_snapshot_not_newest_file(gui):
    editor,wd,_=gui
    choose(editor,"pixels")
    editor.run_all()
    assert editor.verify_outputs()
    editor.steps.selection_set("step0")
    editor._show_selected_step()
    old=next(file for file in editor._file_map.values()
             if file.name.endswith("DemoHUD.png"))
    assert "belege" in old.parts
    with Image.open(old) as im:
        original_pixel=im.convert("RGBA").getpixel((80,35))
    assert original_pixel!=(233,67,88,255)
    editor.steps.selection_set("step1")
    editor._show_selected_step()
    modified=next(file for file in editor._file_map.values()
                  if file.name.endswith("DemoHUD.png"))
    with Image.open(modified) as im:
        new_pixel=im.convert("RGBA").getpixel((80,35))
    assert new_pixel==(233,67,88,255)
    assert editor.verify_outputs()



def test_specialist_demo_editor_opening_and_search_filter(gui):
    editor,wd,_=gui
    editor.module_search.set("BC7")
    editor._filter_modules()
    assert editor.module_list.size()==1
    assert editor.active_key=="bc7"
    editor.module_search.set("")
    editor._filter_modules()
    assert editor.module_list.size()==len(MODULES)
    choose(editor,"stone")
    assert editor.practice_button.instate(("disabled",))
    editor.execute()
    assert not editor.practice_button.instate(("disabled",))
    specialist=editor.open_editor()
    from suite_hud_menu_editor import HudMenuPixelEditor
    assert isinstance(specialist,HudMenuPixelEditor)
    assert specialist.winfo_exists()
    specialist.destroy()

    choose(editor,"capture_diff")
    editor.execute()
    assert editor.practice_button.instate(("disabled",))
    assert editor.open_editor() is None


def test_campaign_demo_populates_real_workshop_on_editor_handoff(gui):
    editor,wd,_=gui
    choose(editor,"campaign")
    editor.run_all()
    workshop=editor.open_editor()
    from suite_origins_runtime_workshop import OriginsRuntimeWorkshop
    assert isinstance(workshop,OriginsRuntimeWorkshop)
    assert workshop.name.get()=="demo-kampagne"
    assert len(workshop.missions)==3
    assert workshop.saved_campaign_slug=="demo-kampagne"
    workshop.destroy()


def test_season_demo_opens_saved_pack_in_real_workshop(gui):
    editor,wd,_=gui
    choose(editor,"season")
    editor.run_all()
    workshop=editor.open_editor()
    assert workshop.pack_id.get()=="demo-winter"
    assert workshop.saved_season_pack=="demo-winter"
    assert workshop.season_groups["tree_pine"].is_dir()
    workshop.destroy()



def test_native_menu_demo_requires_game_and_opens_real_campaign_workshop(gui,monkeypatch):
    from pathlib import Path
    from origins_native_menu_compiler import CSC
    game=Path(r"D:\Games\Stronghold Crusader Definitive Edition")
    if not game.is_dir() or not CSC.is_file():
        pytest.skip("Actual installed game and Windows compiler required")
    editor,wd,_=gui
    choose(editor,"native_menu")
    errors=[]
    monkeypatch.setattr(suite_demo_mode.messagebox,"showerror",
                        lambda title,msg,**kwargs:errors.append((title,msg)))
    assert editor.start() is None
    assert errors
    monkeypatch.setattr(suite_demo_mode.filedialog,"askdirectory",
                        lambda **kwargs:str(game))
    editor.choose_original()
    assert editor.source_paths["native_menu"]==game
    editor.run_all()
    assert editor._run().complete
    assert editor.verify_outputs()
    special=editor.open_editor()
    from suite_origins_runtime_workshop import OriginsRuntimeWorkshop
    assert isinstance(special,OriginsRuntimeWorkshop)
    assert special.name.get()=="demo-native-menu"
    assert len(special.missions)==1
    assert special.saved_campaign_slug=="demo-native-menu"
    special.destroy()

"""Actual Windows/Tk control, theme and runtime authoring windows."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys
import tkinter as tk

import pytest
from PIL import Image

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"tools"))
import hud_menu_workspace as work
from suite_origins_xaml_editor import OriginsXamlEditor
from suite_origins_theme_editor import OriginsThemeEditor
from suite_origins_runtime_workshop import OriginsRuntimeWorkshop


@pytest.fixture(scope="module")
def tkinter_root():
    # One live interpreter per module: Tcl/Tk resource resolution on this
    # portable Windows Python may be inconsistent after repeated Tk teardown.
    try:
        from suite_tcl_runtime import create_tk_root
        root=create_tk_root()
        root.withdraw()
    except tk.TclError as exc:
        pytest.skip("Tk cannot open windows: "+str(exc))
    try:
        yield root
    finally:
        root.destroy()


@pytest.fixture
def gui(tmp_path,monkeypatch,tkinter_root):
    suite=tmp_path/"suite";(suite/"work").mkdir(parents=True)
    monkeypatch.setattr(work,"ROOT",suite)
    monkeypatch.setattr(work,"WORK",suite/"work")
    yield tkinter_root,suite/"work"/"project"


def test_noesis_controls_can_be_selected_and_previewed_without_game_changes(
    gui,tmp_path,monkeypatch,
):
    root,project=gui
    source=tmp_path/"FrontendMenus.xaml"
    source.write_text(
        '<UserControl xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation">'
        '<Grid Name="RootGrid"><Button Name="MyButton" Margin="0,100,0,0" '
        'Command="{Binding ButtonMainMenuCommand}" CommandParameter="Roadmap" />'
        '</Grid></UserControl>',encoding="utf8")
    before=source.read_bytes()
    editor=OriginsXamlEditor(root,project=project,source=source)
    editor.update_idletasks()
    assert editor.listbox.size()==2
    assert "Andere" in editor.section_combo.cget("values")
    editor.search.set("MyButton")
    assert editor.listbox.size()==1
    assert editor.selected_node().name=="MyButton"
    editor.search.set("")
    assert editor.listbox.size()==2
    editor.listbox.selection_clear(0,"end");editor.listbox.selection_set(1)
    editor.choose_node()
    editor.prop.set("Margin")
    editor.value.set("0,150,0,0")
    editor.op.set("SetAttribute")
    editor.preview()
    assert "Offline gültig" in editor.status.get()
    monkeypatch.setattr("suite_origins_xaml_editor.messagebox.askyesno",lambda *_a,**_k: True)
    editor.save()
    assert (project/"Patches/Assets/GUI/XAML/FrontendMenus.xaml").is_file()
    assert source.read_bytes()==before
    editor.destroy()


def test_theme_ui_color_change_saved_to_new_workspace(gui,tmp_path,monkeypatch):
    root,project=gui
    file=tmp_path/"Theme.Brushes.DarkRed.xaml"
    file.write_text(
        '<ResourceDictionary xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" '
        'xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml">'
        '<Color x:Key="Color.Accent">#FF001133</Color>'
        '<SolidColorBrush x:Key="Brush.Accent" Color="{StaticResource Color.Accent}"/>'
        '</ResourceDictionary>',encoding="utf8")
    before=file.read_bytes()
    view=OriginsThemeEditor(root,project=project,source=file)
    view.update_idletasks()
    assert view.list.size()==1
    view.value.set("#FF3399AA")
    view.update_color()
    monkeypatch.setattr("suite_origins_theme_editor.messagebox.askyesno",lambda *_a,**_k:True)
    view.save()
    assert (project/"Override/Assets/GUI/XAMLResources/Theme.Brushes.DarkRed.xaml").is_file()
    assert file.read_bytes()==before
    view.destroy()


def test_origins_campaign_and_season_workshop_has_interactive_forms(gui,monkeypatch):
    root,project=gui
    view=OriginsRuntimeWorkshop(root,project=project)
    view.update_idletasks()
    view.add_mission()
    assert len(view.missions)==1
    assert view.mission_list.exists("1")
    monkeypatch.setattr("suite_origins_runtime_workshop.messagebox.askyesno",lambda *_a,**_k:True)
    view.save_campaign()
    folder=project.parent/".origins-runtime-candidates"/"meine-kampagne"
    assert (folder/"FrontendMenus.draft.xaml").is_file()
    assert (folder/"OriginsCampaignData.g.cs").is_file()
    view.missions.clear()
    view._render_missions()
    monkeypatch.setattr(
        "suite_origins_runtime_workshop.simpledialog.askstring",
        lambda *_a,**_k:"meine-kampagne",
    )
    view.load_campaign()
    assert len(view.missions)==1 and view.missions[1]["map"]=="Antioch.map"
    view.compile_campaign()
    assert (folder/"OriginsAuthoredCore.dll").is_file()
    assert (folder/"offline-compile-evidence.json").is_file()
    assert not (project/"Patches").exists()
    view.destroy()


def test_season_ui_maps_are_explicit_and_offline_compilation_runs(gui,tmp_path,monkeypatch):
    root,project=gui
    project.mkdir(parents=True)
    atlas=project/"tree_pine"
    atlas.mkdir()
    Image.new("RGBA",(16,16),(120,30,20,255)).save(atlas/"atlas.png")
    (atlas/"atlas.json").write_text('{"frames":[]}',encoding="utf8")
    editor=OriginsRuntimeWorkshop(root,project=project)
    editor.season_maps.set("Antioch.map; Demo.map")
    editor.atlas_path.set(str(atlas))
    editor.group.set("tree_pine")
    editor.pack_id.set("mywinterpack")
    editor.add_season()
    assert editor.season_groups["tree_pine"]==atlas
    monkeypatch.setattr(
        "suite_origins_runtime_workshop.messagebox.askyesno",
        lambda *_a,**_k:True,
    )
    editor.save_season()
    expected=project.parent/".origins-runtime-candidates"/"season-mywinterpack"
    assert (expected/"OriginsSeasonData.g.cs").is_file()
    editor.season_groups.clear()
    editor.season_maps.set("")
    monkeypatch.setattr(
        "suite_origins_runtime_workshop.simpledialog.askstring",
        lambda *_a,**_k:"mywinterpack",
    )
    editor.load_season()
    assert editor.season_maps.get()=="Antioch.map; Demo.map"
    assert editor.season_groups["tree_pine"]==expected/"tree_pine"
    editor.compile_season()
    assert (expected/"OriginsAuthoredCore.dll").is_file()
    assert (expected/"offline-compile-evidence.json").is_file()
    assert not (project/"Seasons").exists()
    editor.destroy()



def test_campaign_and_season_joint_offline_qa_is_accessible_in_gui(gui,monkeypatch):
    root,project=gui
    project.mkdir(parents=True)
    atlas=project/"tree_pine"
    atlas.mkdir()
    Image.new("RGBA",(8,8),(55,90,120,255)).save(atlas/"atlas.png")
    (atlas/"atlas.json").write_text('{"schema":1,"frames":[]}',encoding="utf8")
    window=OriginsRuntimeWorkshop(root,project=project)
    monkeypatch.setattr(
        "suite_origins_runtime_workshop.messagebox.askyesno",
        lambda *_a,**_k:True)
    window.add_mission()
    window.save_campaign()
    assert window.saved_campaign_slug=="meine-kampagne"
    window.atlas_path.set(str(atlas))
    window.season_maps.set("Antioch.map")
    window.add_season()
    window.save_season()
    assert window.saved_season_pack=="mein-winterpaket"
    window.check_runtime()
    assert "Gesamtabnahme bestanden" in window.status.get()
    candidates=list((project.parent/".origins-offline-qa").glob(
        "campaign-qa-*/qa-report.json"))
    assert len(candidates)==1
    import json
    report=json.loads(candidates[0].read_text("utf8"))
    assert report["season_pack_id"]=="mein-winterpaket"
    assert report["managed_core_and_authored_data_compiled"] is True
    assert report["steam_game_modified"] is False
    window.destroy()

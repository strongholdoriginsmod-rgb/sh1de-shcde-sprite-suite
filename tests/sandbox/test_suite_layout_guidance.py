"""Visible next-step guidance for the layout editor; synthetic files only."""
from __future__ import annotations

from pathlib import Path
import sys
import tkinter as tk

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/"tools"),str(ROOT/"src")]
from suite_layout_flow import layout_advice


@pytest.mark.parametrize("count,source,dirty,verified,stage,action",[
    (0,False,True,False,"image","import"),
    (0,True,True,False,"image","add"),
    (1,True,True,False,"save","save"),
    (1,True,False,False,"export","export"),
    (1,True,False,True,"ready","noesis"),
])
def test_pure_layout_flow(count,source,dirty,verified,stage,action):
    result=layout_advice(layer_count=count,has_source=source,unsaved=dirty,
                          export_verified=verified)
    assert result.stage==stage
    assert result.action==action
    assert result.button


@pytest.fixture
def designer(tmp_path,monkeypatch):
    from PIL import Image
    import hud_menu_workspace as assets
    import hud_menu_layout as model
    import suite_hud_menu_layout_editor as gui
    import se_asset_package as package

    suite=tmp_path/"suite"
    work=suite/"work"
    work.mkdir(parents=True)
    monkeypatch.setattr(assets,"ROOT",suite)
    monkeypatch.setattr(assets,"WORK",work)
    monkeypatch.setattr(model,"WORK",work)
    monkeypatch.setattr(package,"WORK",work)
    monkeypatch.setattr(package,"OUT",work/"se-asset-mods")
    external=tmp_path/"user-source.png"
    Image.new("RGBA",(34,24),(154,95,53,200)).save(external)
    reference=external.read_bytes()
    project=work/"user-project"
    source=assets.import_image(external,project=project)
    root=tk.Tk()
    root.withdraw()
    editor=gui.HudMenuLayoutEditor(root,project=project,
                     source_asset=source.relative_to(project).as_posix())
    editor.geometry("980x660+20+20")
    root.update()
    editor.fit()
    root.update()
    try:
        yield root,editor,external,reference
    finally:
        editor.destroy()
        root.destroy()


def test_next_step_shows_saved_and_export_states(designer,monkeypatch):
    import suite_hud_menu_layout_editor as gui
    root,editor,source,original=designer
    assert editor._next_action=="add"
    assert editor.source_display.get().startswith("user-source.png ·")
    assert editor.source_choice.get().endswith("/user-source.png")
    assert "Bild platzieren" in editor.guide_heading.get()
    assert "Eine Ebene auswählen" in editor.selection_detail.get()
    assert editor.next_button.winfo_ismapped()
    editor.next_step()
    root.update()
    assert len(editor.scene.layers)==1
    assert editor.selection_detail.get().startswith("Ausgewählt:")
    assert editor._next_action=="save"
    assert editor.next_step()
    assert editor._next_action=="export"
    monkeypatch.setattr(gui.simpledialog,"askstring",
                        lambda *args,**kw:"GuidedMenu")
    monkeypatch.setattr(gui.messagebox,"showinfo",lambda *a,**kw:None)
    result=editor.next_step()
    root.update()
    assert result and Path(result["png"]).is_file()
    assert editor._next_action=="noesis"
    assert editor._export_verified
    # Editing position without exporting never leaves the old output valid.
    editor._selection=[editor.scene.layers[0].id]
    editor._keyboard_nudge(type("Event",(),{"state":0})(),5,0)
    assert editor._next_action=="save"
    assert editor.save()
    assert editor._next_action=="export"
    assert editor._check_export_status() is False
    result=editor.export()
    assert result and editor._export_verified
    assert editor._next_action=="noesis"
    assert source.read_bytes()==original


def test_pixel_changes_mark_last_export_as_stale(designer,monkeypatch):
    import suite_hud_menu_layout_editor as gui
    from PIL import Image
    root,editor,external,original=designer
    editor.add_asset()
    monkeypatch.setattr(gui.simpledialog,"askstring",lambda *a,**kw:"PixelMenu")
    monkeypatch.setattr(gui.messagebox,"showinfo",lambda *a,**kw:None)
    assert editor.export()
    assert editor._next_action=="noesis"
    layer=editor.scene.layers[0]
    path=editor.project/layer.asset
    with Image.open(path) as opened:
        new=opened.convert("RGBA")
    new.putpixel((0,0),(99,127,211,200))
    new.save(path)
    editor._image_saved()
    assert editor._next_action=="export"
    assert not editor._export_verified
    assert external.read_bytes()==original


def test_edit_actions_are_available_without_offscreen_toolbar(designer):
    root,editor,source,original=designer
    assert editor.more_button.winfo_ismapped()
    names=[editor.more_menu.entrycget(i,"label")
           for i in range(editor.more_menu.index("end")+1)]
    for expected in ("Kopieren","Einfügen","Duplizieren","Löschen",
                     "Ebene nach vorne","Ebene nach hinten",
                     "Asset-Mod-Paket bauen","Exportstand prüfen"):
        assert expected in names
    # Primary action rows must fit on a sub-1000px desktop.
    width=editor.winfo_rootx()+editor.winfo_width()
    for name in ("PNG importieren","Bild einfügen",
                 "Layout → PNG + Positionsdaten",
                 "Spieloberfläche anbinden (Noesis)"):
        buttons=[]
        widgets=[editor]
        from tkinter import ttk
        while widgets:
            parent=widgets.pop()
            widgets.extend(parent.winfo_children())
            if isinstance(parent,ttk.Button) and parent.cget("text")==name:
                buttons.append(parent)
        assert buttons
        assert all(button.winfo_ismapped() for button in buttons)
        assert all(button.winfo_rootx()+button.winfo_width()<=width+2
                   for button in buttons)
    assert source.read_bytes()==original


def test_resource_picker_uses_filename_first_without_changing_resource_key(
    designer,
):
    import hud_menu_workspace as assets
    root,editor,external,original=designer
    assets.import_image(external,folder="HUD / UI-Sprites",project=editor.project)
    editor._refresh_assets()
    labels=list(editor._asset_choices)
    assert len(labels)==2
    assert all(label.startswith("user-source.png ·") for label in labels)
    selected=next(label for label in labels if "HUD / UI-Sprites" in label)
    editor.source_display.set(selected)
    editor._picked_source()
    assert editor.source_choice.get()=="Override/Assets/GUI/Sprites/user-source.png"
    assert editor._next_action=="add"
    assert external.read_bytes()==original


def test_guide_and_more_menu_follow_active_language(designer):
    from types import SimpleNamespace
    root,editor,source,original=designer
    root.app=SimpleNamespace(language=tk.StringVar(master=root,value="EN"))
    editor._update_guidance()
    assert editor._next_action=="add"
    assert editor.next_button.cget("text")=="Insert image"
    assert editor.more_menu.entrycget(0,"label")=="Copy"
    root.app.language.set("DE")
    editor._update_guidance()
    assert editor.next_button.cget("text")=="Bild einfügen"
    assert editor.more_menu.entrycget(0,"label")=="Kopieren"
    assert source.read_bytes()==original


def test_pristine_empty_layout_does_not_prompt_to_save(designer,monkeypatch):
    import suite_hud_menu_layout_editor as gui
    root,editor,source,original=designer
    assert not editor.scene.layers
    assert not editor.is_dirty()
    monkeypatch.setattr(gui.messagebox,"askyesnocancel",
                        lambda *args,**kw:pytest.fail(
                            "An untouched empty layout must close without a prompt"))
    assert editor._can_discard() is True
    assert source.read_bytes()==original


def test_editor_reopens_last_saved_named_scene(designer):
    import suite_hud_menu_layout_editor as gui
    from suite_hud_menu_session import read_session
    root,editor,source,before=designer
    editor.scene.name="MeinMenu-2"
    editor.add_asset()
    assert editor.save()
    assert read_session()["scene"]=="MeinMenu-2"
    other=gui.HudMenuLayoutEditor(
        root,project=editor.project,source_asset=editor.source_choice.get())
    root.update()
    assert other.scene.name=="MeinMenu-2"
    assert len(other.scene.layers)==1
    assert other._next_action=="export"
    other.close_editor()
    assert source.read_bytes()==before

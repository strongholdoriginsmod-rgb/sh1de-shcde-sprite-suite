"""Real Tk direct-manipulation tests with synthetic menus and no game writes."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import tkinter as tk
from types import SimpleNamespace
import sys

from PIL import Image
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/"tools"),str(ROOT/"src")]
import hud_menu_layout as model
import hud_menu_workspace as assets
import se_asset_package as package
import suite_hud_menu_layout_editor as gui


@pytest.fixture
def designer(tmp_path,monkeypatch):
    suite=tmp_path/"suite"
    work=suite/"work"
    work.mkdir(parents=True)
    monkeypatch.setattr(assets,"ROOT",suite)
    monkeypatch.setattr(assets,"WORK",work)
    monkeypatch.setattr(model,"WORK",work)
    monkeypatch.setattr(package,"WORK",work)
    monkeypatch.setattr(package,"OUT",work/"se-asset-mods")
    project=work/"my-hud-menu"
    user_image=tmp_path/"unaltered-original.png"
    Image.new("RGBA",(30,20),(110,45,190,255)).save(user_image)
    before=user_image.read_bytes()
    source=assets.import_image(user_image,project=project)
    try:
        root=tk.Tk()
        root.withdraw()
        editor=gui.HudMenuLayoutEditor(
            root,project=project,source_asset=source.relative_to(project).as_posix())
        editor.geometry("1500x920+40+40")
        root.update()
        editor.fit()
        root.update()
    except tk.TclError as exc:
        pytest.skip("Native Tcl/Tk missing: "+str(exc))
    try:
        yield root,editor,project,user_image,before
    finally:
        try:
            editor.destroy()
        except tk.TclError:
            pass
        root.destroy()


def _screen(editor,scene_x,scene_y):
    scale=editor._scale
    margin=gui._CANVAS_MARGIN
    return round(margin+scene_x*scale),round(margin+scene_y*scale)


def _mouse(editor,start,end):
    editor.canvas.event_generate("<ButtonPress-1>",x=start[0],y=start[1])
    editor.canvas.event_generate("<B1-Motion>",x=end[0],y=end[1])
    editor.canvas.event_generate("<ButtonRelease-1>",x=end[0],y=end[1])
    editor.update()


def test_drag_scale_rotate_save_reload_and_composite(designer,monkeypatch):
    root,editor,project,source,before=designer
    assert not editor.scene.layers
    editor.add_asset()
    root.update()
    assert len(editor.scene.layers)==1
    layer=editor.scene.layers[0]
    oldx,oldy=layer.x,layer.y
    start=_screen(editor,oldx+5,oldy+5)
    end=(start[0]+38,start[1]+22)
    _mouse(editor,start,end)
    moved=editor.scene.layers[0]
    assert moved.x!=oldx and moved.y!=oldy
    assert editor.is_dirty()
    canvas_size=editor.scene.width,editor.scene.height
    assert canvas_size==(1280,720)
    handle=editor._handles["se"]
    grip=(int(handle[0]-editor.canvas.canvasx(0)),
          int(handle[1]-editor.canvas.canvasy(0)))
    _mouse(editor,grip,(grip[0]+26,grip[1]+16))
    resized=editor.scene.layers[0]
    assert resized.width>30 and resized.height>20
    before_rotation=resized.rotation
    handle=editor._handles["rotate"]
    grip=(int(handle[0]-editor.canvas.canvasx(0)),
          int(handle[1]-editor.canvas.canvasy(0)))
    _mouse(editor,grip,(grip[0]+17,grip[1]-32))
    assert editor.scene.layers[0].rotation!=before_rotation
    editor.undo()
    assert editor.scene.layers[0].rotation==before_rotation
    editor.redo()
    assert editor.scene.layers[0].rotation!=before_rotation
    assert editor.save()
    assert not editor.is_dirty()
    scene_before=editor.scene.as_json()
    assert source.read_bytes()==before
    assert editor.reload_scene() is None
    assert editor.scene.as_json()==scene_before
    assert source.read_bytes()==before
    monkeypatch.setattr(gui.simpledialog,"askstring",
                        lambda *args,**kwargs:"NewMenuComposite")
    monkeypatch.setattr(gui.messagebox,"showinfo",lambda *a,**kw:None)
    result=editor.export()
    assert result and Path(result["png"]).is_file()
    assert "NewMenuComposite.png" in result["resource"]
    assert Path(result["manifest"]).is_file()
    assert not (suite_dir:=project.parent.parent/"Stronghold Crusader Definitive Edition_Data").exists()
    export=package.build(project,"hudlayoutrun",name="HUD Layout",author="Test")
    assert export["runtime_dll"] is False
    assert export["se_version_required"] is None


def test_layers_clipboard_multiselect_nudge_and_lock(designer,monkeypatch):
    root,editor,project,source,before=designer
    editor.add_asset()
    editor.select_only(editor.scene.layers[0].id)
    editor.copy()
    editor.paste()
    editor.duplicate()
    assert len(editor.scene.layers)==3
    assert len({layer.id for layer in editor.scene.layers})==3
    ids=[layer.id for layer in editor.scene.layers]
    editor._selection=ids[:2]
    editor._refresh_layers()
    originals=[(l.x,l.y) for l in editor.scene.layers[:2]]
    editor._keyboard_nudge(SimpleNamespace(state=1),1,0)
    assert all(l.x==originals[i][0]+10 for i,l in enumerate(editor.scene.layers[:2]))
    editor.select_only(ids[0])
    editor.toggle_locked()
    assert model.layer_by_id(editor.scene,ids[0]).locked
    editor._selection=ids[:2]
    monkeypatch.setattr(gui.messagebox,"showerror",lambda *a,**kw:None)
    editor.delete()
    assert len(editor.scene.layers)==3  # all-or-nothing, locked protects originals
    editor.toggle_locked(ids[0])
    editor.delete()
    assert len(editor.scene.layers)==1
    editor.undo()
    assert len(editor.scene.layers)==3
    assert source.read_bytes()==before


def test_workshop_button_opens_visual_designer(designer):
    root,editor,project,source,before=designer
    source_text=(ROOT/"tools/suite_hud_menu_workshop.py").read_text("utf8")
    assert "def open_layout(self)" in source_text
    assert "HudMenuLayoutEditor" in source_text
    assert "Layout · Live-Vorschau" in source_text
    assert "direkt ziehen & skalieren" in source_text


def test_gui_build_routes_only_final_composite_to_asset_package(designer,monkeypatch):
    root,editor,project,original_file,source_bytes=designer
    editor.add_asset()
    monkeypatch.setattr(gui.messagebox,"showinfo",lambda *a,**kw:None)
    monkeypatch.setattr(gui.messagebox,"askyesno",lambda *a,**kw:True)
    monkeypatch.setattr(gui.simpledialog,"askstring",
                        lambda *a,**kw:"MainMenuComposite")
    result=editor.export()
    assert result and Path(result["png"]).is_file()
    replies=iter(("gui_baked_layout","Menu layout test"))
    monkeypatch.setattr(gui.simpledialog,"askstring",
                        lambda *a,**kw:next(replies))
    built=editor.build_mod()
    assert built is not None and built["source_files"]==1
    import zipfile
    with zipfile.ZipFile(built["zip"]) as package_zip:
        paths=package_zip.namelist()
        assert any("MainMenuComposite.png" in p for p in paths)
        assert all("unaltered-original.png" not in p for p in paths)
    assert original_file.read_bytes()==source_bytes


def test_gui_rejects_stale_position_before_package_build(designer,monkeypatch):
    root,editor,project,original_file,source_bytes=designer
    editor.add_asset()
    monkeypatch.setattr(gui.messagebox,"showinfo",lambda *a,**kw:None)
    monkeypatch.setattr(gui.simpledialog,"askstring",
                        lambda *a,**kw:"StaleComposite")
    assert editor.export()
    old=editor.scene.clone()
    editor.scene.layers[0].x+=32
    editor.history.commit(old)
    problems=[]
    monkeypatch.setattr(gui.messagebox,"showerror",
                        lambda title,text,**kw:problems.append((title,text)))
    assert editor.build_mod() is None
    assert any("erneut exportieren" in message for _,message in problems)
    assert not list((project.parent/"se-asset-mods").glob("*/info.json"))
    assert original_file.read_bytes()==source_bytes


def test_designer_english_labels_follow_suite_language(designer):
    root,editor,project,source,before=designer
    from types import SimpleNamespace
    editor.master.app=SimpleNamespace(
        language=tk.StringVar(master=root,value="EN")
    )
    editor._apply_initial_language()
    captions=[]
    children=[editor]
    from tkinter import ttk
    while children:
        widget=children.pop()
        children.extend(widget.winfo_children())
        if isinstance(widget,ttk.Button):
            captions.append(widget.cget("text"))
    assert "Insert image" in captions
    assert "Layout → PNG + positions" in captions
    assert "Save · Ctrl+S" in captions


def test_small_window_keeps_editable_inspector_scrollable(designer):
    root,editor,project,source,before=designer
    editor.geometry("900x590+15+15")
    root.update()
    editor.add_asset()
    root.update()
    scroll=editor.inspector_scroll
    assert scroll.canvas.winfo_ismapped()
    assert scroll.scrollbar.winfo_ismapped()
    assert editor.canvas.winfo_width()>150
    assert scroll.canvas.winfo_width()>150
    assert editor._property_vars["x"].get() != ""
    # Scrolling the inspector exposes all exact numeric fields and buttons.
    scroll.canvas.yview_moveto(1.)
    root.update()
    assert scroll.body.winfo_exists()
    editor._property_vars["rotation"].set("28.5")
    editor.apply_properties()
    assert editor.scene.layers[0].rotation==28.5
    assert source.read_bytes()==before


def test_numeric_positions_pivots_anchors_and_opacity_survive_save_load(designer):
    root,editor,project,source,before=designer
    editor.add_asset()
    editor._property_vars["x"].set("123.25")
    editor._property_vars["y"].set("52.75")
    editor._property_vars["width"].set("90")
    editor._property_vars["height"].set("35")
    editor._property_vars["rotation"].set("42.5")
    editor._property_vars["opacity"].set("145")
    editor._property_vars["pivot_x"].set("0.2")
    editor._property_vars["pivot_y"].set("0.7")
    editor.anchor_var.set("center")
    editor.apply_properties()
    item=editor.scene.layers[0]
    assert (item.x,item.y,item.width,item.height)==(123.25,52.75,90,35)
    assert (item.rotation,item.opacity,item.anchor)==(42.5,145,"center")
    assert (item.pivot_x,item.pivot_y)==(.2,.7)
    assert editor.save()
    editor.reload_scene()
    item=editor.scene.layers[0]
    assert item.x==123.25 and item.y==52.75
    assert item.width==90 and item.height==35
    assert item.opacity==145 and item.anchor=="center"
    assert item.rotation==42.5 and item.pivot_x==.2 and item.pivot_y==.7
    assert source.read_bytes()==before


def test_windows_image_clipboard_inserts_separate_editable_layer(designer,monkeypatch):
    root,editor,project,source,before=designer
    # Synthetic in-memory clipboard. Never touch the real desktop clipboard.
    monkeypatch.setattr(gui.ImageGrab,"grabclipboard",
                        lambda:Image.new("RGBA",(14,9),(15,66,177,121)))
    monkeypatch.setattr(gui.simpledialog,"askstring",
                        lambda *a,**kw:"CopiedMenuIcon")
    editor.paste()
    assert len(editor.scene.layers)==1
    item=editor.scene.layers[0]
    assert "CopiedMenuIcon.png" in item.asset
    with Image.open(project/item.asset) as picture:
        assert picture.size==(14,9)
        assert picture.convert("RGBA").getpixel((1,1))==(15,66,177,121)
    assert editor.save()
    editor.reload_scene()
    assert editor.scene.layers[0].asset==item.asset
    assert source.read_bytes()==before


def test_designer_selects_real_noesis_grid_and_builds_bound_game_mod(
    designer,monkeypatch
):
    import suite_hud_menu_noesis_dialog as binding_ui
    import hud_menu_noesis_integration as binding
    import zipfile
    import json
    root,editor,project,owned,owned_content=designer
    # Synthetic install with the same layout as the local read-only QA game.
    gamedir=project.parent.parent/"SyntheticGame"
    plugin=gamedir/"BepInEx/plugins/000shcdese"
    xaml=plugin/"Override/Assets/GUI/XAML"
    xaml.mkdir(parents=True)
    (plugin/"info.json").write_text(
        json.dumps({"GUID":"000shcdese","Version":"3.0.0"}),
        encoding="utf8",
    )
    sample=xaml/"MainHUD.xaml"
    sample.write_text(
        '<UserControl xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" '
        'xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml">'
        '<Grid x:Name="HUD_Main"><TextBlock Text="demo"/></Grid>'
        '</UserControl>',encoding="utf8")
    original_xaml=sample.read_bytes()
    monkeypatch.setattr(binding,"WORK",project.parent)
    editor.add_asset()
    monkeypatch.setattr(gui.simpledialog,"askstring",
                        lambda *args,**kwargs:"NativeGameImage")
    monkeypatch.setattr(gui.messagebox,"showinfo",lambda *a,**kw:None)
    assert editor.export()
    window=editor.bind_noesis()
    assert window is not None and window.winfo_exists()
    window.source.set(str(gamedir))
    window.scan()
    candidates=[label for label,item in window.targets.items()
                if item.xaml_document=="MainHUD.xaml" and
                   item.grid_name=="HUD_Main"]
    assert len(candidates)==1  # The anonymous root is also an eligible target.
    window.target_choice.set(candidates[0])
    assert window.preview_patch()
    window.guid.set("native_ui_test")
    window.name.set("Native target static XAML")
    monkeypatch.setattr(binding_ui.messagebox,"askyesno",lambda *a,**kw:True)
    monkeypatch.setattr(binding_ui.messagebox,"showinfo",lambda *a,**kw:None)
    built=window.build()
    assert built is not None
    with zipfile.ZipFile(built["zip"]) as archive:
        files=archive.namelist()
        assert len(files)==3
        assert any(name.endswith("Patches/Assets/GUI/XAML/MainHUD.xaml")
                   for name in files)
        assert any(name.endswith("/Images/NativeGameImage.png") for name in files)
    assert built["target"]["installed_extender_version"]=="3.0.0"
    assert built["target"]["target_grid"]=="HUD_Main"
    assert built["target"]["ingame_rendering_verified"] is False
    assert sample.read_bytes()==original_xaml
    assert owned.read_bytes()==owned_content
    window.destroy()


def test_designer_refuses_noesis_without_saved_composite(designer,monkeypatch):
    root,editor,project,owned,owned_content=designer
    errors=[]
    monkeypatch.setattr(gui.messagebox,"showerror",
                        lambda title,message,**kw:errors.append(message))
    editor.add_asset()
    assert editor.bind_noesis() is None
    assert errors
    assert not list(project.rglob("*.xaml"))
    assert owned.read_bytes()==owned_content


def test_noesis_dialog_qa_install_launch_and_verified_rollback(
    designer,monkeypatch
):
    import suite_hud_menu_noesis_dialog as binding_ui
    import hud_menu_noesis_integration as binding
    import hud_menu_noesis_qa as qa
    import json
    root,editor,project,owned,owned_content=designer
    gamedir=project.parent.parent/"SyntheticGame"
    plugin=gamedir/"BepInEx/plugins/000shcdese"
    xaml=plugin/"Override/Assets/GUI/XAML"
    xaml.mkdir(parents=True)
    (gamedir/qa.MARKER).write_text("explicit QA game",encoding="utf8")
    (gamedir/"Stronghold Crusader Definitive Edition.exe").write_bytes(b"qa-exe")
    (plugin/"info.json").write_text(
        json.dumps({"GUID":"000shcdese","Version":"0.0.1"}),
        encoding="utf8",
    )
    source=xaml/"FrontendMenus.xaml"
    source.write_text(
        '<UserControl xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" '
        'xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml">'
        '<Grid x:Name="MainMenu"/></UserControl>',encoding="utf8")
    base_hash=source.read_bytes()
    monkeypatch.setattr(binding,"WORK",project.parent)
    monkeypatch.setattr(qa,"_game_running",lambda:False)
    editor.add_asset()
    monkeypatch.setattr(gui.simpledialog,"askstring",
                        lambda *args,**kwargs:"MenuQAComposite")
    monkeypatch.setattr(gui.messagebox,"showinfo",lambda *a,**kw:None)
    assert editor.export()
    dialog=editor.bind_noesis()
    assert dialog is not None
    dialog.source.set(str(gamedir))
    dialog.scan()
    label=next(k for k in dialog.targets if "MainMenu" in k)
    dialog.target_choice.set(label)
    dialog.guid.set("qa_dialog_test")
    monkeypatch.setattr(binding_ui.messagebox,"askyesno",lambda *a,**kw:True)
    monkeypatch.setattr(binding_ui.messagebox,"showinfo",lambda *a,**kw:None)
    assert dialog.build()
    installed=gamedir/"BepInEx/plugins/qa_dialog_test"
    errors=[]
    monkeypatch.setattr(binding_ui.messagebox,"showerror",
                        lambda *args,**kw:errors.append(args))
    editor.scene.layers[0].x+=4
    assert dialog.install_qa() is None
    assert errors and not installed.exists()
    editor.scene.layers[0].x-=4
    source.write_bytes(base_hash+b"\n")
    assert dialog.install_qa() is None
    assert not installed.exists()
    source.write_bytes(base_hash)
    assert dialog.start_qa_game() is None  # No tracked QA mod installed yet.
    assert not installed.exists()
    assert dialog.install_qa()
    assert installed.is_dir()
    started=[]
    monkeypatch.setattr(binding_ui.os,"startfile",
                        lambda p,**kw:started.append((p,kw)))
    assert dialog.start_qa_game()
    assert len(started)==1
    assert started[0][0].endswith("Stronghold Crusader Definitive Edition.exe")
    assert started[0][1]["cwd"]==str(gamedir)
    receipt=dialog.remove_qa()
    assert receipt and receipt["removed_guid"]=="qa_dialog_test"
    assert not installed.exists()
    assert source.read_bytes()==base_hash
    assert owned.read_bytes()==owned_content
    dialog.destroy()

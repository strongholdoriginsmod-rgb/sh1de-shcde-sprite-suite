"""Native Tk HUD/menu workshop smoke tests with isolated synthetic images."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
import sys
import tkinter as tk
from tkinter import ttk

from PIL import Image
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"tools"))
import hud_menu_workspace as model
import suite_hud_menu_workshop as gui
import suite_hud_menu_editor as editor


class DummyPreview(ttk.Frame):
    def __init__(self,parent,empty_text=""):
        super().__init__(parent)
        self.current=None
        self.empty_text=empty_text

    def show(self,path,*,title="",detail=""):
        self.current=Path(path)

    def clear(self,text=""):
        self.current=None


@pytest.fixture
def workshop(tmp_path,monkeypatch):
    suite=tmp_path/"suite"
    (suite/"work").mkdir(parents=True)
    monkeypatch.setattr(model,"ROOT",suite)
    monkeypatch.setattr(model,"WORK",suite/"work")
    monkeypatch.setattr(gui,"ROOT",suite)
    try:
        root=tk.Tk()
        root.geometry("1200x760+30+30")
    except tk.TclError as exc:
        pytest.skip("Native Tk is unavailable: "+str(exc))
    links=[]
    commands=[]
    app=SimpleNamespace(
        tab_ui=SimpleNamespace(preview=DummyPreview(root)),
        hud_tab="sh1hud",
        origins_graphics_tab=SimpleNamespace(selected_item=lambda:None),
        exchange_tab="exchange",
        open_tab=lambda tab:links.append(tab),
        run=lambda args,label:commands.append((args,label)),
    )
    view=gui.HudMenuWorkshop(root,app)
    view.pack(fill="both",expand=True)
    view.project_var.set(str(suite/"work"/"gui-assets"))
    root.update()
    try:
        yield suite,root,view,links,commands
    finally:
        root.destroy()


def test_integrated_workshop_image_selection_paint_save_and_undo(workshop,monkeypatch):
    suite,root,view,links,commands=workshop
    source=suite/"external-owned.png"
    Image.new("RGBA",(18,10),(100,50,20,180)).save(source)
    import_source=source.read_bytes()
    file=model.import_image(source,folder="Menüs / UI-Bilder",
                            project=view._project(create=True))
    view.refresh()
    root.update()
    assert len(view._assets)==1
    assert view.selected_asset().relative_path.endswith("external-owned.png")
    assert view.preview.current==file
    assert view.original.current.is_file()
    assert view.selected_asset().status=="Unverändert"
    view.edit_selected()
    root.update()
    windows=[w for w in view.winfo_children() if isinstance(w,editor.HudMenuPixelEditor)]
    assert len(windows)==1
    painter=windows[0]
    painter.color.set("#1877ac")
    painter.opacity.set(255)
    painter.mode.set("Pinsel")
    painter.canvas.event_generate("<ButtonPress-1>",x=8,y=8)
    painter.canvas.event_generate("<ButtonRelease-1>",x=8,y=8)
    root.update()
    location=(4,4) if painter.zoom.get()==2 else (8,8)
    assert painter.image.getpixel(location)==(24,119,172,255)
    with Image.open(file) as disk:
        assert disk.getpixel(location)==(100,50,20,180)
    painter.undo()
    assert painter.image.getpixel(location)==(100,50,20,180)
    painter.redo()
    assert painter.image.getpixel(location)==(24,119,172,255)
    painter.save()
    root.update()
    assert view.selected_asset().status=="Bearbeitet"
    assert view.preview.current==file
    assert source.read_bytes()==import_source
    assert view.original.current.is_file()
    painter.close()
    view.goto_sh1()
    view.goto_exchange()
    assert links==["sh1hud","exchange"]
    assert commands==[]


def test_workshop_menu_packaging_routes_only_to_version_free_tool(workshop,monkeypatch):
    suite,root,view,links,commands=workshop
    source=suite/"user-menu.png"
    Image.new("RGBA",(13,9),(22,88,33,255)).save(source)
    model.import_image(source,folder="HUD / UI-Sprites",
                       project=view._project(create=True))
    view.refresh()
    assert view._assets[0].kind=="HUD / UI-Sprites"
    view.copy_key()
    assert root.clipboard_get().endswith("user-menu.png")
    from suite_hud_menu_workshop import messagebox,simpledialog
    monkeypatch.setattr(messagebox,"askyesno",lambda *a,**kw:True)
    responses=iter(("hudmenu","Meine Menues"))
    monkeypatch.setattr(simpledialog,"askstring",lambda *a,**kw:next(responses))
    view.build()
    assert len(commands)==1
    args,label=commands[0]
    assert args[0].endswith("se_asset_package.py")
    assert "--source" in args
    assert "--guid" in args
    assert "hudmenu" in args
    assert not (suite/"BepInEx").exists()
    assert not (suite/"Stronghold Crusader Definitive Edition_Data").exists()

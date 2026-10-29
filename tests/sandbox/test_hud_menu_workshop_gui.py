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
import hud_menu_layout as layout
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
    monkeypatch.setattr(layout,"WORK",suite/"work")
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


def test_main_hud_menu_workshop_opens_real_layer_designer(workshop):
    suite,root,view,links,commands=workshop
    source=suite/"own-menu-background.png"
    Image.new("RGBA",(20,12),(155,55,100,190)).save(source)
    asset=model.import_image(source,project=view._project(create=True))
    view.refresh()
    root.update()
    window=view.open_layout()
    assert window is not None and window.winfo_exists()
    assert window.source_choice.get()==asset.relative_to(view._project()).as_posix()
    window.add_asset()
    root.update()
    assert len(window.scene.layers)==1
    assert window.save()
    metadata=window.scene.name
    assert window._save_hash is not None
    window.close_editor()
    assert not window.winfo_exists()
    new_window=view.open_layout()
    root.update()
    assert new_window.scene.name==metadata
    assert len(new_window.scene.layers)==1
    new_window.close_editor()
    assert source.is_file()
    assert not (suite/"Stronghold Crusader Definitive Edition_Data").exists()


def test_last_project_and_image_survive_workshop_reopening(workshop):
    from suite_hud_menu_session import read_session
    suite,root,view,links,commands=workshop
    folder=view._project(create=True)
    first=suite/"first.png"
    last=suite/"last.png"
    Image.new("RGBA",(14,10),(20,90,50,255)).save(first)
    Image.new("RGBA",(14,10),(80,20,50,255)).save(last)
    path_a=model.import_image(first,project=folder)
    path_b=model.import_image(last,project=folder)
    view.refresh()
    view._select_path(path_b)
    saved=read_session()
    assert saved["project"]==folder
    assert saved["asset"].endswith("last.png")
    app=view.app
    view.destroy()
    reopened=gui.HudMenuWorkshop(root,app)
    reopened.pack(fill="both",expand=True)
    reopened.refresh()
    root.update()
    assert reopened._project()==folder
    assert reopened.selected_asset().relative_path.endswith("last.png")
    assert "Aktives Projekt:" in reopened.project_summary.get()
    assert first.is_file() and last.is_file()
    reopened.destroy()


def test_file_import_selects_last_successfully_imported_file(workshop,monkeypatch):
    from suite_hud_menu_session import read_session
    suite,root,view,links,commands=workshop
    first=suite/"zz-top.png"
    second=suite/"aa-bottom.png"
    Image.new("RGBA",(19,13),(12,32,65,255)).save(first)
    Image.new("RGBA",(18,12),(22,42,75,255)).save(second)
    before=(first.read_bytes(),second.read_bytes())
    monkeypatch.setattr(gui.filedialog,"askopenfilenames",
                        lambda *args,**kw:(str(first),str(second)))
    monkeypatch.setattr(gui.messagebox,"askyesno",lambda *args,**kw:True)
    view.filter_var.set("previous-unmatched-key")
    view.edited_only.set(True)
    view.import_images()
    root.update()
    assert view.filter_var.get()==""
    assert view.edited_only.get() is False
    assert view.tabs.index(view.tabs.select())==0
    assert len(view._assets)==2
    assert view.selected_asset().relative_path.endswith("aa-bottom.png")
    assert view.preview.current.name=="aa-bottom.png"
    assert read_session()["asset"].endswith("aa-bottom.png")
    assert (first.read_bytes(),second.read_bytes())==before


def test_project_switch_remembers_only_valid_work_folder(workshop,monkeypatch):
    from suite_hud_menu_session import read_session
    suite,root,view,links,commands=workshop
    target=model.workspace(suite/"work"/"another-project",create=True)
    png=suite/"different-image.png"
    Image.new("RGBA",(6,6),(1,2,3,255)).save(png)
    model.import_image(png,project=target)
    monkeypatch.setattr(gui.filedialog,"askdirectory",
                        lambda *args,**kw:str(target))
    view.pick_project()
    root.update()
    assert view._project()==target
    assert view.selected_asset().relative_path.endswith("different-image.png")
    assert read_session()["project"]==target
    assert "another-project" in view.project_summary.get()


def test_export_prepare_opens_live_step_without_extra_modal(workshop,monkeypatch):
    suite,root,view,links,commands=workshop
    source=suite/"export-preview.png"
    Image.new("RGBA",(11,7),(8,9,10,255)).save(source)
    model.import_image(source,project=view._project(create=True))
    view.refresh()
    monkeypatch.setattr(gui.messagebox,"showinfo",
                        lambda *a,**kw:pytest.fail("Redundant export pop-up"))
    monkeypatch.setattr(gui.messagebox,"showerror",
                        lambda *args,**kw:pytest.fail(
                            "Layout failed to open: " + repr(args)))
    editor=view.export_help()
    assert editor is not None and editor.winfo_exists()
    assert editor._next_action=="add"
    assert editor.next_button.winfo_exists()
    assert editor.source_choice.get().endswith("export-preview.png")
    editor.close_editor()


def test_empty_project_is_remembered_after_manual_refresh(workshop):
    from suite_hud_menu_session import read_session
    suite,root,view,links,commands=workshop
    empty=model.workspace(suite/"work"/"new-empty-workspace",create=True)
    view.project_var.set(str(empty))
    view.refresh()
    root.update()
    assert not view._assets
    assert read_session()["project"]==empty
    assert "new-empty-workspace" in view.project_summary.get()


def test_project_switch_opens_even_if_recent_preference_cannot_be_written(
    workshop,monkeypatch,
):
    suite,root,view,links,commands=workshop
    another=model.workspace(suite/"work"/"safe-target",create=True)
    monkeypatch.setattr(gui.filedialog,"askdirectory",
                        lambda *args,**kw:str(another))
    monkeypatch.setattr(gui,"save_session",
                        lambda *args,**kw:(_ for _ in ()).throw(
                            model.WorkshopError("Preference file is linked")))
    monkeypatch.setattr(gui.messagebox,"showerror",
                        lambda *args,**kw:pytest.fail("Opening should work"))
    view.pick_project()
    root.update()
    assert view._project()==another
    assert "Projekt geöffnet" in view.message.get()


def test_full_project_archive_backup_and_restore_via_visible_buttons(
    workshop,monkeypatch,
):
    import hud_menu_project_transfer as transfers
    suite,root,view,links,commands=workshop
    project=view._project(create=True)
    source=suite/"real-menu.png"
    Image.new("RGBA",(24,18),(25,97,171,225)).save(source)
    source_bytes=source.read_bytes()
    imported=model.import_image(source,project=project)
    view.refresh()
    archive=suite/"MyProjectBackup.zip"
    monkeypatch.setattr(gui.filedialog,"asksaveasfilename",
                        lambda *args,**kwargs:str(archive))
    monkeypatch.setattr(gui.messagebox,"showinfo",lambda *args,**kwargs:None)
    monkeypatch.setattr(gui.messagebox,"showerror",
                        lambda *args,**kwargs:pytest.fail(
                            "Unexpected project archive error: "+repr(args)))
    report=view.export_project_archive()
    assert report is not None and archive.is_file()
    assert transfers.archive_info(archive)["files"]>=2
    assert source.read_bytes()==source_bytes

    monkeypatch.setattr(gui.filedialog,"askopenfilename",
                        lambda *args,**kwargs:str(archive))
    monkeypatch.setattr(gui.simpledialog,"askstring",
                        lambda *args,**kwargs:"ImportedMenu")
    monkeypatch.setattr(gui.messagebox,"askyesno",
                        lambda *args,**kwargs:True)
    restored=view.import_project_archive()
    root.update()
    assert restored is not None
    assert view._project().name=="ImportedMenu"
    assert view.selected_asset().relative_path.endswith("real-menu.png")
    assert view.selected_asset().baseline_path is not None
    assert imported.is_file() and source.read_bytes()==source_bytes


def test_gui_rejects_archive_import_over_existing_project_without_overwrite(
    workshop,monkeypatch,
):
    suite,root,view,links,commands=workshop
    source=suite/"existing-image.png"
    Image.new("RGBA",(14,11),(42,33,24,255)).save(source)
    original=source.read_bytes()
    file=model.import_image(source,project=view._project(create=True))
    view.refresh()
    backup=suite/"backup.zip"
    from hud_menu_project_transfer import create_archive
    create_archive(view._project(),backup)
    monkeypatch.setattr(gui.filedialog,"askopenfilename",
                        lambda *a,**kw:str(backup))
    monkeypatch.setattr(gui.simpledialog,"askstring",
                        lambda *a,**kw:view._project().name)
    monkeypatch.setattr(gui.messagebox,"askyesno",lambda *a,**kw:True)
    errors=[]
    monkeypatch.setattr(gui.messagebox,"showerror",
                        lambda *a,**kw:errors.append(a))
    assert view.import_project_archive() is None
    assert errors and "existieren" in str(errors[0])
    assert view._project().is_dir()
    assert file.read_bytes()==original


def test_project_import_proposes_new_name_when_original_exists(workshop,monkeypatch):
    from hud_menu_project_transfer import create_archive
    suite,root,view,links,commands=workshop
    project=view._project(create=True)
    original=suite/"original.png"
    Image.new("RGBA",(9,8),(90,80,70,255)).save(original)
    model.import_image(original,project=project)
    view.refresh()
    zipfile=suite/"backup-name-suggestion.zip"
    create_archive(project,zipfile)
    suggested=[]
    monkeypatch.setattr(gui.filedialog,"askopenfilename",
                        lambda *a,**kw:str(zipfile))
    monkeypatch.setattr(gui.simpledialog,"askstring",
                        lambda *a,**kw:suggested.append(kw["initialvalue"]) or None)
    assert view.import_project_archive() is None  # Cancel at name input.
    assert suggested==["gui-assets-Kopie"]
    assert not (suite/"work"/"gui-assets-Kopie").exists()

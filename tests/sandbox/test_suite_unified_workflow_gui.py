"""Live Tk smoke for the ONE shared project instead of unrelated editor tabs."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from io import BytesIO
import importlib.machinery
import importlib.util
import json
import sys
import tkinter as tk
import zipfile

from PIL import Image
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/"tools"),str(ROOT/"src")]

import hud_menu_workspace as hud
import se_asset_package as package
import suite_unified_workflow as flow_ui
from suite_unified_project import ProjectPipeline
# Import modules with cached WORK aliases before the isolated root patch;
# otherwise a later unrelated GUI test may inherit a deleted tmp directory.
import hud_menu_layout as layout_model
import suite_hud_menu_layout_editor as layout_window
import hud_menu_project_transfer as project_transfer
import suite_hud_menu_workshop as legacy_workshop
import suite_hud_menu_editor as pixel_text_editors
import suite_origins_visual_editor as visual_editor


@pytest.fixture
def app_and_tree(tmp_path,monkeypatch):
    workroot=tmp_path/"private-suite"
    work=workroot/"work"
    work.mkdir(parents=True)
    monkeypatch.setattr(hud,"ROOT",workroot)
    monkeypatch.setattr(hud,"WORK",work)
    monkeypatch.setattr(layout_model,"WORK",work)
    monkeypatch.setattr(hud,"DEFAULT",work/"hud-menu-werkstatt")
    monkeypatch.setattr(package,"ROOT",workroot)
    monkeypatch.setattr(package,"WORK",work)
    monkeypatch.setattr(package,"OUT",work/"se-asset-mods")
    import stronghold_europe_de.workspace_lock as lock
    monkeypatch.setattr(lock,"lock_path",
                        lambda _root,_name:tmp_path/"workflow-gui-instance.lock")
    loader=importlib.machinery.SourceFileLoader(
        "suite_unified_gui_test",str(ROOT/"tools"/"suite_universal.pyw"))
    spec=importlib.util.spec_from_loader(loader.name,loader)
    module=importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    old=module.LANG.code
    module.LANG.code="de"
    monkeypatch.setattr(module,"SETTINGS",tmp_path/"workflow-settings.json")
    app=module.Universal()
    try:
        app.geometry("1250x890+15+15")
        app.update()
        yield app,work,monkeypatch
    finally:
        module.LANG.code=old
        app.destroy()


def _image(path:Path):
    Image.new("RGBA",(80,42),(32,84,147,255)).save(path)


def _xaml(path:Path):
    path.write_bytes(
        b'<UserControl xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation">'
        b'<Grid><Button Name="MenuTest" Width="200" Content="Old"/></Grid>'
        b'</UserControl>')


def test_workflow_is_first_page_and_hud_tab_uses_same_project(app_and_tree):
    app,work,_=app_and_tree
    tab=app.workflow_tab
    assert app.notebook.select()==str(tab)
    assert app.modern_shell.buttons["start"].winfo_ismapped()
    assert tab.project_text.get().startswith("Aktives Projekt:")
    assert len(app.modern_shell.PRIMARY)==5
    assert app.modern_shell.buttons["menus"].winfo_ismapped()
    assert not app.modern_shell.buttons.get("hud",None)
    assert tab.pipeline.project==app.hud_menu_tab._project(create=True)
    assert len(app.notebook.tabs())>=17
    app.modern_shell.buttons["menus"].invoke()
    assert app.notebook.select()==str(app.hud_menu_tab)
    app.modern_shell.buttons["start"].invoke()
    assert app.notebook.select()==str(tab)


def test_source_edit_revision_and_actual_mod_zip_are_connected(app_and_tree,tmp_path):
    app,work,monkeypatch=app_and_tree
    tab=app.workflow_tab
    monkeypatch.setattr(flow_ui.simpledialog,"askstring",
                        lambda *args,**kwargs:"menue-erweiterung")
    tab.create_project()
    assert tab.pipeline.project==work/"projects"/"menue-erweiterung"
    assert app.hud_menu_tab._project()==tab.pipeline.project
    png=tmp_path/"Wappen.png";_image(png)
    original=tmp_path/"FrontendMenus.xaml";_xaml(original)
    before_source=original.read_bytes()
    monkeypatch.setattr(flow_ui.filedialog,"askopenfilenames",
                        lambda *a,**k:(str(png),str(original)))
    tab.add_sources()
    app.update()
    assert tab.source_text.get().startswith("Noesis-Original:")
    assert len(tab.pipeline.assets())==1
    editor=tab._visual_window
    assert editor is not None and editor.winfo_exists()
    assert not editor.is_dirty()
    assert tab.open_noesis() is editor  # reuse, do not create duplicate editor
    editor.doc.edit((0,0),"Content","Neu")
    assert editor.is_dirty()
    assert editor.save() is True
    assert not editor.is_dirty()
    asset=tab.pipeline.assets()[0]
    tab.select_asset(asset.path)
    pixel=tab.edit_selected()
    assert pixel is not None and pixel.winfo_exists()
    assert tab.edit_selected() is pixel  # single active editor for the asset
    pixel.image.putpixel((0,0),(188,29,18,250))
    pixel.dirty=True
    pixel.save()
    assert not pixel.dirty
    assert tab.check_project()["assets"]==2
    exported=tab.build_package()
    assert exported is not None
    assert exported["asset_count"]==2
    assert exported["zip_verified_against_project"] is True
    assert exported["installed_into_game"] is False
    assert Path(exported["zip"]).is_file()
    with zipfile.ZipFile(exported["zip"]) as zipfile_:
        root="BepInEx/plugins/spritesuite-menue-erweiterung/"
        assert zipfile_.read(root+"Override/Assets/GUI/Images/Wappen.png")==asset.path.read_bytes()
        assert b"Neu" in zipfile_.read(root+"Patches/Assets/GUI/XAML/FrontendMenus.xaml")
    assert original.read_bytes()==before_source
    assert png.read_bytes()!=asset.path.read_bytes()
    assert "FERTIG" in tab.result_text.get()
    assert Path(exported["receipt"]).is_file()
    pixel.close()
    editor.close_editor()


def test_build_wont_lose_unsaved_visual_edit(app_and_tree,tmp_path):
    app,work,monkeypatch=app_and_tree
    tab=app.workflow_tab
    original=tmp_path/"FrontendMenus.xaml";_xaml(original)
    tab.pipeline.register_original_xaml(original)
    editor=tab.open_noesis()
    assert editor is not None
    editor.doc.edit((0,0),"Content","Nicht gespeichert")
    assert editor.is_dirty()
    monkeypatch.setattr(flow_ui.messagebox,"askyesno",lambda *a,**k:False)
    assert tab.build_package() is None
    assert not any((work/"se-asset-mods").glob("*.zip")) if (
        work/"se-asset-mods").exists() else True
    assert not (tab.pipeline.project/"Patches").exists()
    assert editor.is_dirty()
    # User declines discard too; editor remains usable.
    assert editor.close_editor() is False
    monkeypatch.setattr(flow_ui.messagebox,"askyesno",lambda *a,**k:True)
    assert editor.close_editor() is True


def test_empty_project_does_not_show_fake_success(app_and_tree):
    app,work,_=app_and_tree
    tab=app.workflow_tab
    assert tab.build_package() is None
    assert "Kein gültiges Paket" in tab.result_text.get()
    assert not (work/"se-asset-mods").exists()


def test_share_selected_asset_with_hud_workshop(app_and_tree,tmp_path):
    app,_,_=app_and_tree
    tab=app.workflow_tab
    source=tmp_path/"Button.png";_image(source)
    image=tab.pipeline.import_image(source,category="HUD / UI-Sprites")
    tab.refresh()
    tab.select_asset(image)
    app.open_tab(app.hud_menu_tab)
    app.hud_menu_tab.refresh()
    assert app.hud_menu_tab._project()==tab.pipeline.project
    assert any(asset.relative_path=="Override/Assets/GUI/Sprites/Button.png"
               for asset in app.hud_menu_tab._assets)
    app.open_tab(tab)
    assert tab.selected_asset().path==image



def test_project_png_links_to_selected_noesis_image_without_duplicate_import(
    app_and_tree,tmp_path,
):
    app,work,_=app_and_tree
    tab=app.workflow_tab
    image=tmp_path/"Shield.png";_image(image)
    stored=tab.pipeline.import_image(image)
    source=tmp_path/"FrontendMenus.xaml"
    source.write_bytes(
        b'<UserControl xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation">'
        b'<Grid><Image Name="MenuLogo" Source="old.png"/></Grid>'
        b'</UserControl>')
    tab.pipeline.register_original_xaml(source)
    tab.refresh();tab.select_asset(stored)
    editor=tab.open_noesis()
    assert editor is not None
    # A selected Grid is not an Image. No implicit guess/no wrong attribute.
    assert tab.bind_selected_image() is None
    editor.select_path((0,0))
    assert tab.bind_selected_image()=="../Images/Shield.png"
    assert editor.doc.attributes((0,0))["Source"]=="../Images/Shield.png"
    assert editor.is_dirty() is True
    assert editor.save() is True
    assert len(tab.pipeline.assets())==2  # Exactly one PNG + one XAML patch.
    assert tab.check_project()["warnings"]==[]
    built=tab.build_package()
    assert built and built["zip_verified_against_project"]
    with zipfile.ZipFile(built["zip"]) as pkg:
        p="BepInEx/plugins/"+built["guid"]+"/"
        patch=pkg.read(p+"Patches/Assets/GUI/XAML/FrontendMenus.xaml")
        assert b"../Images/Shield.png" in patch
        assert pkg.read(p+"Override/Assets/GUI/Images/Shield.png")==stored.read_bytes()
    editor.close_editor()


def test_unified_project_backup_and_restore_survives_new_workspace(
    app_and_tree,tmp_path,monkeypatch
):
    app,work,_=app_and_tree
    tab=app.workflow_tab
    image=tmp_path/"Badge.png";_image(image)
    tab.pipeline.import_image(image)
    original=tmp_path/"FrontendMenus.xaml";_xaml(original)
    tab.pipeline.register_original_xaml(original)
    editor=tab.open_noesis()
    editor.doc.edit((0,0),"Content","Portable Original")
    assert editor.save() is True
    editor.close_editor()
    backup=tmp_path/"editable-suite-project.zip"
    monkeypatch.setattr(flow_ui.filedialog,"asksaveasfilename",
                        lambda *a,**k:str(backup))
    saved=tab.backup_project()
    assert saved is not None and backup.is_file()
    with zipfile.ZipFile(backup) as zipfile_:
        assert zipfile_.testzip() is None
        names=zipfile_.namelist()
        assert "metadata/origins-sources/current.json" in names
        assert any(n.endswith("rev-0001/edited.xaml") for n in names)
    monkeypatch.setattr(flow_ui.filedialog,"askopenfilename",
                        lambda *a,**k:str(backup))
    monkeypatch.setattr(flow_ui.simpledialog,"askstring",
                        lambda *a,**k:"RestoredNoesis")
    restored=tab.restore_project()
    assert restored is not None
    assert tab.pipeline.project==work/"RestoredNoesis"
    assert app.hud_menu_tab._project()==tab.pipeline.project
    assert tab.pipeline.original_xaml().is_file()
    assert tab.pipeline.latest_visual_revision().is_dir()
    reopened=tab.open_noesis()
    assert reopened.doc.attributes((0,0))["Content"]=="Portable Original"
    reopened.doc.edit((0,0),"Content","Still editable")
    assert reopened.save() is True
    assert tab.pipeline.latest_visual_revision().name=="rev-0002"
    exported=tab.build_package()
    assert exported is not None and exported["zip_verified_against_project"]
    reopened.close_editor()



def test_changing_noesis_source_saves_or_blocks_existing_dirty_editor(
    app_and_tree,tmp_path,monkeypatch
):
    app,work,_=app_and_tree
    tab=app.workflow_tab
    first=tmp_path/"FirstMenu.xaml"
    second=tmp_path/"OtherMenu.xaml"
    _xaml(first)
    second.write_bytes(first.read_bytes().replace(b"Old",b"Other Source"))
    tab.pipeline.register_original_xaml(first)
    old=tab.open_noesis()
    old.doc.edit((0,0),"Content","Unsaved first menu")
    assert old.is_dirty()
    monkeypatch.setattr(flow_ui.filedialog,"askopenfilenames",
                        lambda *a,**k:(str(second),))
    monkeypatch.setattr(flow_ui.messagebox,"askyesno",
                        lambda *a,**k:False)
    assert tab.add_sources() is None
    assert tab.pipeline.original_xaml().name=="FirstMenu.xaml"
    assert old.winfo_exists() and old.is_dirty()

    # User accepts saving the old source before choosing the new one.
    monkeypatch.setattr(flow_ui.messagebox,"askyesno",
                        lambda *a,**k:True)
    tab.add_sources()
    assert not old.winfo_exists()
    assert tab.pipeline.original_xaml().name=="OtherMenu.xaml"
    assert tab._visual_window is not None
    assert tab._visual_window is not old
    assert tab._visual_window.doc.attributes((0,0))["Content"]=="Other Source"
    assert (tab.pipeline.project/"Patches/Assets/GUI/XAML/FirstMenu.xaml").is_file()
    tab._visual_window.close_editor()


def test_creating_project_does_not_orphan_unsaved_noesis_work(
    app_and_tree,tmp_path,monkeypatch
):
    app,work,_=app_and_tree
    tab=app.workflow_tab
    original=tmp_path/"FrontendMenus.xaml";_xaml(original)
    tab.pipeline.register_original_xaml(original)
    editor=tab.open_noesis()
    editor.doc.edit((0,0),"Content","Not yet saved")
    prior=tab.pipeline.project
    monkeypatch.setattr(flow_ui.simpledialog,"askstring",
                        lambda *a,**k:"second-project")
    monkeypatch.setattr(flow_ui.messagebox,"askyesno",
                        lambda *a,**k:False)
    tab.create_project()
    assert tab.pipeline.project==prior
    assert not (work/"projects"/"second-project").exists()
    assert editor.is_dirty() and editor.winfo_exists()
    editor.doc.edit((0,0),"Content","saved")
    assert editor.save()
    editor.close_editor()


def test_declined_project_switch_does_not_create_unwanted_workspace(
    app_and_tree,tmp_path,monkeypatch
):
    app,work,_=app_and_tree
    tab=app.workflow_tab
    original=tmp_path/"FrontendMenus.xaml";_xaml(original)
    tab.pipeline.register_original_xaml(original)
    editor=tab.open_noesis()
    editor.doc.edit((0,0),"Content","Unsaved original")
    previous=tab.pipeline.project
    destination=work/"must-not-exist"
    assert not destination.exists()
    monkeypatch.setattr(flow_ui.messagebox,"askyesno",lambda *a,**k:False)

    assert tab.activate_project(destination) is False
    assert not destination.exists()  # no stray folder after declining Save
    assert tab.pipeline.project==previous
    assert editor.winfo_exists() and editor.is_dirty()
    assert editor.close_editor() is False
    monkeypatch.setattr(flow_ui.messagebox,"askyesno",lambda *a,**k:True)
    assert editor.close_editor() is True


def test_switch_requires_existing_project_before_changing_session(
    app_and_tree,
):
    app,work,_=app_and_tree
    tab=app.workflow_tab
    old=tab.pipeline.project
    candidate=work/"unknown-project"
    assert not candidate.exists()
    with pytest.raises(ValueError,match="existiert"):
        tab.activate_project(candidate)
    assert not candidate.exists()
    assert tab.pipeline.project==old


def test_failed_session_activation_preserves_existing_project_editor(
    app_and_tree,tmp_path,monkeypatch
):
    app,work,_=app_and_tree
    tab=app.workflow_tab
    original=tmp_path/"FrontendMenus.xaml";_xaml(original)
    tab.pipeline.register_original_xaml(original)
    editor=tab.open_noesis()
    assert editor is not None and editor.winfo_exists()
    previous=tab.pipeline.project
    destination=flow_ui.new_project("destination-project")
    actual=flow_ui.ProjectPipeline.activate

    def fail_only_new(self):
        if self.project==destination:
            raise OSError("Synthetic session write failed")
        return actual(self)

    monkeypatch.setattr(flow_ui.ProjectPipeline,"activate",fail_only_new)
    with pytest.raises(OSError,match="Synthetic session"):
        tab.activate_project(destination)
    assert tab.pipeline.project==previous
    assert editor.winfo_exists()
    assert tab.open_noesis() is editor
    assert editor.close_editor() is True


def test_failed_second_build_does_not_open_old_zip_as_new_result(
    app_and_tree,tmp_path,monkeypatch
):
    app,work,_=app_and_tree
    tab=app.workflow_tab
    source=tmp_path/"Asset.png";_image(source)
    tab.pipeline.import_image(source)
    tab.refresh()
    good=tab.build_package()
    assert good and Path(good["zip"]).is_file()
    monkeypatch.setattr(flow_ui.os,"startfile",lambda *_:pytest.fail(
        "Old export opened after failed new build"))
    tab.guid.set("not a valid guid!")
    assert tab.build_package() is None
    assert tab._last_export is None
    assert tab.open_result() is None
    assert Path(good["zip"]).is_file()  # don't delete the prior verified ZIP


@pytest.mark.parametrize("change",["zip","project"])
def test_result_button_rechecks_hash_and_project_state(
    app_and_tree,tmp_path,monkeypatch,change
):
    app,work,_=app_and_tree
    tab=app.workflow_tab
    source=tmp_path/"Asset.png";_image(source)
    stored=tab.pipeline.import_image(source)
    tab.refresh()
    good=tab.build_package()
    assert good and Path(good["zip"]).is_file()
    monkeypatch.setattr(flow_ui.os,"startfile",lambda *_:pytest.fail(
        "Unverified or stale export must not be opened"))
    if change=="zip":
        with Path(good["zip"]).open("ab") as archive:
            archive.write(b"tampered-after-build")
    else:
        edited=BytesIO()
        Image.new("RGBA",(80,42),(99,88,77,255)).save(edited,"PNG")
        hud.write_png(stored.relative_to(tab.pipeline.project).as_posix(),
                      edited.getvalue(),
                      project=tab.pipeline.project,
                      expected_sha256=sha256(stored.read_bytes()).hexdigest())



    assert tab.open_result() is None
    assert Path(good["zip"]).is_file()  # preserve evidence, block usage


def test_reselecting_same_project_keeps_open_noesis_editor(
    app_and_tree,tmp_path
):
    app,work,_=app_and_tree
    tab=app.workflow_tab
    original=tmp_path/"FrontendMenus.xaml";_xaml(original)
    tab.pipeline.register_original_xaml(original)
    editor=tab.open_noesis()
    assert editor is not None and editor.winfo_exists()
    assert tab.activate_project(tab.pipeline.project) is True
    assert editor.winfo_exists()
    assert tab.open_noesis() is editor
    assert editor.close_editor() is True


def test_verified_current_package_can_open_its_folder(
    app_and_tree,tmp_path,monkeypatch
):
    app,work,_=app_and_tree
    tab=app.workflow_tab
    source=tmp_path/"Asset.png";_image(source)
    tab.pipeline.import_image(source)
    tab.refresh()
    good=tab.build_package()
    assert good is not None and good["zip_verified_against_project"]
    opened=[]
    monkeypatch.setattr(flow_ui.os,"startfile",opened.append)
    assert tab.open_result()==Path(good["zip"])
    assert opened==[str(Path(good["zip"]).parent)]


def test_steam_version_check_is_read_only_and_uses_background_runner(
    app_and_tree, monkeypatch,
):
    app, work, _ = app_and_tree
    tab = app.workflow_tab
    submitted = []
    def accept_job(args, label):
        submitted.append((args, label))
        return True
    monkeypatch.setattr(app, "run", accept_job)
    previous = tab.pipeline.project
    assert tab.check_steam_compatibility() is True
    assert len(submitted) == 1
    args, label = submitted[0]
    assert args == [
        str(ROOT / "tools" / "suite_steam_compatibility.py"),
        "--project", str(ROOT),
    ]
    assert "Steam" in label
    assert not any(flag in args for flag in (
        "--install", "--promote", "--replace", "--write"))
    assert tab.pipeline.project == previous
    assert not (work / "mapping" / "proposals.json.gz").exists()
    assert "Keine Modinstallation" in tab.message.get()

    # A busy worker must not present a successful check or change projects.
    monkeypatch.setattr(app, "run", lambda *_args: False)
    assert tab.check_steam_compatibility() is False
    assert tab.pipeline.project == previous




def test_workbench_keeps_checks_export_and_project_actions_visible_on_small_screen(
    app_and_tree,
):
    app, _, _ = app_and_tree
    app.geometry("1020x680+30+30")
    app.open_tab(app.workflow_tab)
    app.update()
    view = app.workflow_tab
    right = app.winfo_rootx() + app.winfo_width()
    bottom = app.winfo_rooty() + app.winfo_height()
    for widget in (view.source_button, view.tree, view.preview,
                   view.check_button, view.export_button, view.details_toggle):
        assert widget.winfo_ismapped(), str(widget)
        assert widget.winfo_rootx() + widget.winfo_width() <= right + 3
        assert widget.winfo_rooty() + widget.winfo_height() <= bottom + 3
    assert view.preview.winfo_height() >= 170
    assert view.export_details.winfo_manager() == ""
    view.details_toggle.invoke()
    app.update()
    assert view.export_details.winfo_manager() == "pack"
    assert view.export_button.winfo_ismapped()
    view.details_toggle.invoke()
    assert view.export_details.winfo_manager() == ""
    shell = app.modern_shell
    assert shell.more_panel.winfo_manager() == ""
    shell.more_toggle.invoke()
    app.update()
    assert shell.more_panel.winfo_manager() == "pack"
    shell.more_toggle.invoke()
    assert shell.more_panel.winfo_manager() == ""


def test_workbench_preview_fits_available_space_without_resampling_to_tiny_card(
    app_and_tree, tmp_path,
):
    from PIL import Image
    app, _, _ = app_and_tree
    app.geometry("1150x760+30+30")
    image = tmp_path / "wide_preview.png"
    Image.new("RGBA", (1200, 620), (60, 110, 164, 255)).save(image)
    view = app.workflow_tab
    stored = view.pipeline.import_image(image)
    view.refresh()
    view.select_asset(stored)
    app.open_tab(view)
    app.update()
    view._render_selected_preview()
    assert view._photo is not None
    assert view._photo.width() >= 280
    assert view._photo.height() >= 120
    assert view._photo.width() <= view.preview.winfo_width()
    assert view._photo.height() <= view.preview.winfo_height()


def test_layout_designer_uses_real_canvas_fit_and_visible_property_inspector(
    app_and_tree,
):
    from tkinter import ttk
    app, _, _ = app_and_tree
    editor = app.workflow_tab.open_layout()
    assert editor is not None
    try:
        editor.geometry("1280x800+30+30")
        app.update()
        editor.update()
        assert editor.canvas.winfo_width() >= 470
        assert editor.canvas.winfo_height() >= 340
        # Initial fit must use the mapped canvas, not the 150-px fallback
        assert editor._first_fit_pending is False
        assert editor._zoom_value() > 0.30
        assert editor.layers.winfo_height() < 300
        assert editor.more_button.winfo_ismapped()
        action_labels=[]
        remaining=[editor]
        while remaining:
            node=remaining.pop()
            remaining.extend(node.winfo_children())
            if isinstance(node,ttk.Button) and node.winfo_ismapped():
                action_labels.append(node.cget("text"))
        assert "Layout → PNG + Positionsdaten" in action_labels
        assert "Asset-Mod-Paket bauen" in action_labels
    finally:
        editor.close_editor()

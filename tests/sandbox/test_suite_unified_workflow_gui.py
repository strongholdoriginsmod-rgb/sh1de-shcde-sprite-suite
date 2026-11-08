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


def test_project_menu_imports_binary_and_exports_to_chosen_zip(app_and_tree, tmp_path):
    app, _, monkeypatch = app_and_tree
    tab = app.workflow_tab
    binary = tmp_path / "Modular.dll"
    binary.write_bytes(b"MZ\x00\xff")
    monkeypatch.setattr(flow_ui.filedialog, "askopenfilenames", lambda **_: (str(binary),))
    monkeypatch.setattr(flow_ui.simpledialog, "askstring", lambda *_, **__: "Plugins/")
    tab.actions_menu.invoke(tab.mod_files_menu_index)
    assert tab.selected_asset().relative_path == "Plugins/Modular.dll"
    assert tab.edit_button.instate(["disabled"])

    output = tmp_path / "Meine.Mod.zip"
    tab.mod_author.set("Mod author")
    tab.mod_version.set("preview 2")
    monkeypatch.setattr(flow_ui.filedialog, "asksaveasfilename", lambda **_: str(output))
    tab.actions_menu.invoke(tab.custom_export_menu_index)
    assert tab._last_export is not None, tab.result_text.get()
    assert Path(tab._last_export["zip"]) == output
    prefix = f"BepInEx/plugins/{tab.guid.get()}/"
    with zipfile.ZipFile(output) as archive:
        assert archive.read(prefix + "Plugins/Modular.dll") == binary.read_bytes()
        manifest = json.loads(archive.read(prefix + "info.json"))
    assert manifest["Author"] == "Mod author" and manifest["Version"] == "preview 2"
    reopened = ProjectPipeline(tab.pipeline.project).latest_export()
    assert reopened["project_current"] is True
    assert reopened["user_selected_output"] is True
    assert Path(reopened["zip"]) == output



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
    tab.guid.set("invalid/guid")
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



def test_workbench_language_switch_translates_live_status_without_changing_project(
    app_and_tree, tmp_path,
):
    app, _work, _ = app_and_tree
    tab=app.workflow_tab
    original_project=tab.pipeline.project
    original_guid=tab.guid.get()
    app.set_language("en")
    app.update()
    assert tab.project_text.get().startswith("Active project: ")
    assert tab.source_text.get().startswith("No original Noesis")
    assert tab.selection_text.get().startswith("No file yet.")
    assert "Validation required before export" in tab.check_text.get()
    assert "No verified export" in tab.result_text.get()
    assert tab.stage_text.get().startswith("ADD SOURCES")
    assert tab.source_button.cget("text")=="+  Add files"
    assert tab.export_button.cget("text")=="Build verified mod ZIP"
    assert tab.category_choice.get()=="Menu images"
    assert tab.category.get()=="Menüs / UI-Bilder"
    assert tab.pipeline.project==original_project
    assert tab.guid.get()==original_guid

    # Changing a translated display label must still select the canonical
    # on-disk category, never save an English path or new identifier.
    tab.category_choice.set("Game sprites")
    tab._category_changed()
    assert tab.category.get()=="Spiel-Sprites"
    img=tmp_path/"EnglishBadge.png"
    _image(img)
    stored=tab.pipeline.import_image(img,category=tab.category.get())
    assert stored.relative_to(tab.pipeline.project).as_posix().startswith(
        "Override/Sprites/")
    tab.refresh()
    assert tab.category_choice.get()=="Game sprites"
    assert "1 workspace file(s)" in tab.check_text.get()
    assert tab.check_project() is not None
    assert "files checked" in tab.check_text.get()
    result=tab.build_package()
    assert result and result["zip_verified_against_project"] is True
    assert tab.result_text.get().startswith("DONE:")
    export_receipt=result["zip_sha256"]
    assert tab.pipeline.latest_export()["zip_sha256"]==export_receipt

    app.set_language("de")
    app.update()
    assert tab.project_text.get().startswith("Aktives Projekt: ")
    assert tab.result_text.get().startswith("FERTIG:")
    assert tab.category_choice.get()=="Spiel-Sprites"
    assert tab.category.get()=="Spiel-Sprites"
    assert tab.pipeline.project==original_project
    assert tab.pipeline.latest_export()["zip_sha256"]==export_receipt
    assert tab.guid.get()==original_guid


def test_workflow_status_translation_is_reversible_without_revalidating(
    app_and_tree,
):
    app,_work,_=app_and_tree
    tab=app.workflow_tab
    raw_message="Prüfe das Projekt und erstelle das Paket …"
    tab.message.set(raw_message)
    app.set_language("en")
    assert tab.message.get()=="Checking project and building package…"
    app.set_language("de")
    assert tab.message.get()==raw_message
    tab.check_text.set("Prüfung fehlgeschlagen: synthetic missing image")
    app.set_language("en")
    assert tab.check_text.get()=="Validation failed: synthetic missing image"
    app.set_language("de")
    assert tab.check_text.get()=="Prüfung fehlgeschlagen: synthetic missing image"



def test_english_compact_workspace_keeps_menu_and_file_status_visible(app_and_tree):
    app, _work, _ = app_and_tree
    app.geometry("1020x680+20+20")
    app.set_language("en")
    app.open_tab(app.workflow_tab)
    app.update()
    tab=app.workflow_tab
    more=tab.more_actions_button
    assert more.cget("text")=="More ▾"
    assert more.winfo_ismapped()
    right=app.winfo_rootx()+app.winfo_width()
    for widget in (more,tab.noesis_button,tab.layout_button,tab.edit_button):
        assert widget.winfo_rootx()+widget.winfo_width()<=right+3
        assert widget.winfo_ismapped()
    assert tab.tree.heading("state","text")=="Status"
    columns=sum(tab.tree.column(column,"width") for column in ("#0","typ","state"))
    assert columns<=tab.tree.winfo_width()+2
    hint=app.modern_shell.rail_hint
    assert int(hint.cget("wraplength"))<=hint.winfo_width()



def test_minimum_layout_editor_reduces_layer_panel_and_wraps_status(app_and_tree):
    app,_work,_=app_and_tree
    editor=app.workflow_tab.open_layout()
    assert editor is not None
    try:
        editor.geometry("880x570+20+20")
        editor.update()
        app.update()
        assert int(editor.layers.cget("height"))==4
        assert editor.canvas.winfo_width()>=390
        assert editor.canvas.winfo_height()>=275
        assert editor._zoom_value()>0.20
        assert int(editor.status_label.cget("wraplength"))<=editor.winfo_width()
        bottom=editor.winfo_rooty()+editor.winfo_height()
        assert editor.status_label.winfo_rooty()+editor.status_label.winfo_height()<=bottom
    finally:
        editor.close_editor()


def test_modding_studio_uses_current_project_metadata_and_portable_backup(app_and_tree, tmp_path):
    app, work, monkeypatch = app_and_tree
    pipeline = app.workflow_tab.pipeline
    marker = tmp_path / "StudioButton.png"
    _image(marker)
    pipeline.import_image(marker)
    original_theme = __import__("tkinter.ttk", fromlist=["Style"]).Style(app).theme_use()
    studio = app.open_modding_studio()
    assert studio is not None
    studio.root.withdraw()
    assert studio._suite_project == pipeline.project
    assert studio.workspace == hud._metadata_dir(pipeline.project) / "modding-studio"
    assert app.open_modding_studio() is studio
    assert __import__("tkinter.ttk", fromlist=["Style"]).Style(app).theme_use() == original_theme
    before = (studio.workspace / "project.json").read_bytes()
    backup = tmp_path / "StudioProject.zip"
    project_transfer.create_archive(pipeline.project, backup)
    with zipfile.ZipFile(backup) as archive:
        assert archive.read("metadata/modding-studio/project.json") == before
    restored = project_transfer.restore_archive(backup, project_name="StudioRestored")
    restored_project = Path(restored["project"])
    assert (hud._metadata_dir(restored_project) / "modding-studio" / "project.json").read_bytes() == before
    studio.root.destroy()


def test_visible_project_menu_opens_bound_studio_and_backup_saves_revision(app_and_tree, tmp_path):
    app, work, monkeypatch = app_and_tree
    tab = app.workflow_tab
    app.update()
    assert tab.more_actions_button.winfo_ismapped()
    menu = tab.actions_menu
    index = next(i for i in range(menu.index("end") + 1)
                 if menu.type(i) == "command" and menu.entrycget(i, "label") == "Modding Studio")
    menu.invoke(index)
    studio = app._modding_studio_window
    assert studio.root.master is app
    assert studio.project_bound
    studio.project["title"] = "Draft in the shared project"
    assert studio in tab._dirty_windows()
    destination = work / "project-copy"
    destination.mkdir()
    monkeypatch.setattr(flow_ui.messagebox, "askyesno", lambda *a, **k: False)
    assert not tab.activate_project(destination)
    assert studio.root.winfo_exists()
    assert studio.is_dirty()
    archive = tmp_path / "studio-project.zip"
    monkeypatch.setattr(flow_ui.filedialog, "asksaveasfilename", lambda **kwargs: str(archive))
    monkeypatch.setattr(flow_ui.messagebox, "askyesno", lambda *a, **k: True)
    result = tab.backup_project()
    assert result is not None
    assert not studio.is_dirty()
    with zipfile.ZipFile(archive) as opened:
        assert "metadata/modding-studio/current.json" in opened.namelist()
        assert any(name.startswith("metadata/modding-studio/revisions/") for name in opened.namelist())
    assert tab.activate_project(destination)
    assert not studio.root.winfo_exists()


@pytest.mark.parametrize("size,scale", [("1020x680",1.25),("1280x720",1.5)])
def test_expanded_details_and_lower_sidebar_remain_reachable(app_and_tree, size, scale):
    app, _work, _monkeypatch = app_and_tree
    previous_scaling = float(app.tk.call("tk", "scaling"))
    previous_wheel = app.bind_all("<MouseWheel>")
    try:
        app.tk.call("tk", "scaling", previous_scaling * scale)
        app.geometry(size + "+30+30")
        view = app.workflow_tab
        if not view.export_details.winfo_manager():
            view.details_toggle.invoke()
        app.update()
        view.workarea.reveal(view.version_entry)
        app.update()
        def visible(widget, canvas):
            assert widget.winfo_ismapped()
            assert widget.winfo_rootx() >= canvas.winfo_rootx() - 2
            assert widget.winfo_rooty() >= canvas.winfo_rooty() - 2
            assert widget.winfo_rootx() + widget.winfo_width() <= canvas.winfo_rootx() + canvas.winfo_width() + 2
            assert widget.winfo_rooty() + widget.winfo_height() <= canvas.winfo_rooty() + canvas.winfo_height() + 2
        visible(view.version_entry, view.workarea.canvas)
        view.workarea.canvas.yview_moveto(0)
        view.workarea.canvas.xview_moveto(0)
        view.version_entry.event_generate("<FocusIn>")
        app.update()
        visible(view.version_entry, view.workarea.canvas)
        shell = app.modern_shell
        if not shell.more_expanded:
            shell.more_toggle.invoke()
        app.update()
        shell.scroll.reveal(shell.strict)
        app.update()
        visible(shell.strict, shell.scroll.canvas)
        app.open_tab(app.catalog_page)
        app.update()
        app.notebook_viewport.reveal(app.catalog_run_button)
        app.update()
        visible(app.catalog_run_button, app.notebook_viewport.canvas)
        assert app.bind_all("<MouseWheel>") == previous_wheel
    finally:
        app.tk.call("tk", "scaling", previous_scaling)


def test_visible_assistant_menu_and_sidebar_reuse_one_native_window(app_and_tree):
    app, _work, _monkeypatch = app_and_tree
    app._assistant_extra_delegates = ()
    menu = app.workflow_tab.actions_menu
    index = next(i for i in range(menu.index("end")+1)
                 if menu.type(i) == "command" and menu.entrycget(i,"label") == "KI-Assistent")
    menu.invoke(index)
    host = app._ai_assistant_window
    app.update()
    assert host.root.winfo_exists()
    assert host._session is None
    app.modern_shell.scroll.reveal(app.modern_shell.ai_button)
    app.update()
    assert app.modern_shell.ai_button.winfo_ismapped()
    app.modern_shell.ai_button.invoke()
    assert app._ai_assistant_window is host
    assert host.close()


def test_status_labels_wrap_to_their_actual_width_after_pane_resize(app_and_tree):
    app, _work, _monkeypatch = app_and_tree
    app.geometry("1020x680+20+20")
    view = app.workflow_tab
    text = "Langer überprüfbarer Status mit Dateinamen und mehreren Wörtern. " * 12
    for variable in (view.source_text,view.selection_text,view.message,view.result_text):
        variable.set(text)
    app.update()
    view.main_split.sashpos(0,240)
    app.update()
    for label in (view.source_label,view.selection_text_label,view.message_label,view.result_label):
        assert int(label.cget("wraplength")) <= label.winfo_width()
        assert label.winfo_reqheight() > 25

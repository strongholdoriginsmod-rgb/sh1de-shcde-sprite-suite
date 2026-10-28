"""GUI contract for the simplified Suite navigation and editing entry points."""
from __future__ import annotations

import importlib.machinery
import importlib.util
from pathlib import Path
import sys
import tkinter as tk

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"tools"))


@pytest.fixture
def ui(tmp_path,monkeypatch):
    import stronghold_europe_de.workspace_lock as lock_module
    monkeypatch.setattr(
        lock_module,"lock_path",
        lambda _root,_name: tmp_path/"modern-ui-instance.lock",
    )
    loader=importlib.machinery.SourceFileLoader(
        "suite_modern_integration_test",str(ROOT/"tools"/"suite_universal.pyw"))
    spec=importlib.util.spec_from_loader(loader.name,loader)
    mod=importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    monkeypatch.setattr(mod,"SETTINGS",tmp_path/"ui-settings.json")
    old=mod.LANG.code
    mod.LANG.code="de"
    app=mod.Universal()
    try:
        app.geometry("1080x780+20+20")
        app.update()
        yield mod,app
    finally:
        mod.LANG.code=old
        app.destroy()


def test_default_has_visible_sidebar_and_preserves_actual_notebook(ui):
    mod,app=ui
    shell=app.modern_shell
    assert app.notebook.select()==str(app.tab_home)
    assert app.notebook.cget("style")=="Modern.TNotebook"
    assert shell.rail.winfo_ismapped()
    assert shell.buttons["menus"].winfo_ismapped()
    assert app.quick_picker.winfo_ismapped()
    assert len(shell.PRIMARY)==9
    assert len(app.notebook.tabs())>=16
    # Sidebar navigation never runs a build, modifies games or imports files.
    app.run=lambda *a,**kw:pytest.fail("Navigation started a tool")
    shell.buttons["menus"].invoke()
    app.update()
    assert app.notebook.select()==str(app.hud_menu_tab)
    assert shell.buttons["menus"].cget("style")=="RailActive.TButton"
    assert "Bild" in app._workspace_hint.cget("text")


def test_sidebar_fits_small_window_and_can_reveal_legacy_tabs(ui):
    mod,app=ui
    app.geometry("1020x680+40+40")
    app.update()
    shell=app.modern_shell
    assert shell.rail.winfo_width()<=180
    assert app.notebook.winfo_width()>=650
    app.open_tab(app.hud_menu_tab)
    app.update()
    assert app.hud_menu_tab.tree.winfo_width()>180
    assert app.hud_menu_tab.tabs.winfo_width()>130
    app.toggle_tab_strip()
    app.update()
    assert app.notebook.cget("style")=="TNotebook"
    app.toggle_tab_strip()
    app.update()
    assert app.notebook.cget("style")=="Modern.TNotebook"


def test_sidebar_language_and_advanced_controls_track_suite_state(ui):
    mod,app=ui
    shell=app.modern_shell
    app.set_language("en")
    app.update()
    assert shell.buttons["menus"].cget("text")=="HUD & menus"
    assert app.hud_menu_tab.project_summary.get().startswith("Active project:")
    assert shell.search_button.cget("text")=="Search (Ctrl+K)"
    assert app.tab_home.quick_buttons["designer"][0].cget("text")=="Arrange layout"
    app.set_language("de")
    app.update()
    assert shell.buttons["menus"].cget("text")=="HUD & Menüs"
    assert app.hud_menu_tab.project_summary.get().startswith("Aktives Projekt:")
    shell.advanced.invoke()
    assert app.advanced.get() is True


def test_workshop_hides_technical_controls_and_toggles_them(ui):
    mod,app=ui
    view=app.hud_menu_tab
    assert view.project_row.winfo_manager()==""
    assert view.tools_row.winfo_manager()==""
    view.project_toggle.invoke()
    view.tools_toggle.invoke()
    app.open_tab(view)
    app.update()
    assert view.project_row.winfo_ismapped()
    assert view.tools_row.winfo_ismapped()
    view.project_toggle.invoke()
    view.tools_toggle.invoke()
    assert view.project_row.winfo_manager()==""
    assert view.tools_row.winfo_manager()==""


def test_home_shortcuts_only_open_relevant_workspace(ui):
    mod,app=ui
    app.run=lambda *a,**kw:pytest.fail("A shortcut must not build anything")
    app.tab_home.quick_buttons["hud_menu_tab"][0].invoke()
    assert app.notebook.select()==str(app.hud_menu_tab)
    app.tab_home.quick_buttons["sandbox_tab"][0].invoke()
    assert app.notebook.select()==str(app.sandbox_tab)
    app.tab_home.quick_buttons["bc7_page"][0].invoke()
    assert app.notebook.select()==str(app.bc7_page)


def test_open_layout_guide_changes_language_without_restart(ui):
    mod,app=ui
    app.open_tab(app.hud_menu_tab)
    editor=app.hud_menu_tab.open_layout()
    assert editor is not None
    app.update()
    # An empty worktree has no imported game assets; never create them here.
    assert editor.guide_heading.get().startswith("1 / 4")
    assert editor._next_action=="import"
    app.set_language("en")
    app.update()
    assert "Open an image" in editor.guide_heading.get()
    assert editor.more_menu.entrycget(0,"label")=="Copy"
    app.set_language("de")
    app.update()
    assert "Bild öffnen" in editor.guide_heading.get()
    editor.close_editor()

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
    # Other GUI tests may have enabled advanced mode in this process.
    # Verify the control toggles the current state, not a global default.
    before = app.advanced.get()
    shell.advanced.invoke()
    assert app.advanced.get() is (not before)


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


def test_project_archive_actions_are_visible_at_minimum_suite_width(ui):
    from tkinter import ttk
    _module, app=ui
    app.geometry("1020x680+32+32")
    app.open_tab(app.hud_menu_tab)
    app.update()
    root=app.hud_menu_tab
    found={}
    queue=[root]
    while queue:
        widget=queue.pop()
        queue.extend(widget.winfo_children())
        if isinstance(widget,ttk.Button):
            label=widget.cget("text")
            if label.startswith(("Projekt sichern", "Projekt aus ZIP")):
                found[label]=widget
    assert len(found)==2
    right=app.winfo_rootx()+app.winfo_width()
    for button in found.values():
        assert button.winfo_ismapped()
        assert button.winfo_rootx()>=app.winfo_rootx()
        assert button.winfo_rootx()+button.winfo_width()<=right


def test_project_archive_actions_translate_to_english(ui):
    from tkinter import ttk
    _module,app=ui
    view=app.hud_menu_tab
    app.set_language("en")
    app.open_tab(view)
    app.update()
    labels=[]
    pending=[view]
    while pending:
        widget=pending.pop()
        pending.extend(widget.winfo_children())
        if isinstance(widget,ttk.Button):
            labels.append(widget.cget("text"))
    assert "Back up project…" in labels
    assert "Open project ZIP…" in labels
    app.set_language("de")
    app.update()
    labels=[]
    pending=[view]
    while pending:
        widget=pending.pop()
        pending.extend(widget.winfo_children())
        if isinstance(widget,ttk.Button):
            labels.append(widget.cget("text"))
    assert "Projekt sichern …" in labels
    assert "Projekt aus ZIP öffnen …" in labels


def test_advanced_sidebar_checkbox_uses_correct_tk_interpreter_with_old_root(
    tmp_path, monkeypatch,
):
    """A previously created Tk root must not steal this window's variables."""
    import stronghold_europe_de.workspace_lock as lock_module
    monkeypatch.setattr(
        lock_module, "lock_path",
        lambda _root, _name: tmp_path / "second-root-instance.lock",
    )
    from suite_tcl_runtime import create_tk_root
    older = create_tk_root()
    older.withdraw()
    app = None
    try:
        loader = importlib.machinery.SourceFileLoader(
            "suite_second_root_integration_test",
            str(ROOT / "tools" / "suite_universal.pyw"),
        )
        spec = importlib.util.spec_from_loader(loader.name, loader)
        mod = importlib.util.module_from_spec(spec)
        loader.exec_module(mod)
        monkeypatch.setattr(mod, "SETTINGS", tmp_path / "second-root-settings.json")
        previous_language = mod.LANG.code
        mod.LANG.code = "de"
        try:
            app = mod.Universal()
            app.update()
            assert app.advanced._root is app
            assert app.language._root is app
            assert app.strict._root is app
            before = app.advanced.get()
            app.modern_shell.advanced.invoke()
            assert app.advanced.get() is not before
        finally:
            mod.LANG.code = previous_language
    finally:
        if app is not None:
            app.destroy()
        older.destroy()



def test_main_sidebar_launches_actual_module_demo_and_executes_files(ui,tmp_path,monkeypatch):
    import hud_menu_workspace as demo_work
    import hud_menu_layout as demo_layout
    import se_asset_package as demo_package
    mod,app=ui
    suite=tmp_path/"demo-suite"
    (suite/"work").mkdir(parents=True)
    monkeypatch.setattr(demo_work,"ROOT",suite)
    monkeypatch.setattr(demo_work,"WORK",suite/"work")
    monkeypatch.setattr(demo_layout,"WORK",suite/"work")
    monkeypatch.setattr(demo_package,"ROOT",suite)
    monkeypatch.setattr(demo_package,"WORK",suite/"work")
    monkeypatch.setattr(demo_package,"OUT",suite/"work"/"se-asset-mods")
    shell=app.modern_shell
    assert shell.demo_button.winfo_exists()
    window=shell.open_demo()
    try:
        app.update()
        assert window.module_list.size()>=20
        idx=next(i for i,m in enumerate(__import__("suite_demo_engine").MODULES)
                 if m.key=="pixels")
        window.module_list.selection_clear(0,"end")
        window.module_list.selection_set(idx)
        window._select_module()
        window.run_all()
        assert window._run().complete
        assert window.verify_outputs()
        assert (window._run().root/"demo-protokoll.json").is_file()
    finally:
        window.destroy()

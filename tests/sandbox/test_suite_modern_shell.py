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
    import hud_menu_layout as layout
    import hud_menu_workspace as hud

    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setattr(hud, "ROOT", tmp_path)
    monkeypatch.setattr(hud, "WORK", work)
    monkeypatch.setattr(hud, "DEFAULT", work / "hud-menu-werkstatt")
    monkeypatch.setattr(layout, "WORK", work)
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
    assert app.notebook.select()==str(app.workflow_tab)
    assert app.notebook.cget("style")=="Modern.TNotebook"
    assert shell.rail.winfo_ismapped()
    assert shell.buttons["menus"].winfo_ismapped()
    assert not app.quick_picker.winfo_ismapped()
    assert len(shell.PRIMARY)==5
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
    assert shell.buttons["menus"].cget("text")=="Pixels & layout"
    assert app.hud_menu_tab.project_summary.get().startswith("Active project:")
    assert shell.search_button.cget("text")=="Search (Ctrl+K)"
    assert app.tab_home.quick_buttons["designer"][0].cget("text")=="Arrange layout"
    app.set_language("de")
    app.update()
    assert shell.buttons["menus"].cget("text")=="Pixel & Layout"
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
    # This fixture starts with a private, empty project.
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
    app.open_tab(app.workflow_tab)
    app.update()
    # The two essential backup/restore actions now belong to the one
    # shared project page, instead of a second HUD-specific wizard.
    found={}
    queue=[app.workflow_tab]
    while queue:
        widget=queue.pop()
        queue.extend(widget.winfo_children())
        if isinstance(widget,ttk.Button):
            label=widget.cget("text")
            if label in ("Projekt sichern (ZIP)","Projekt-ZIP öffnen"):
                found[label]=widget
    assert set(found)=={"Projekt sichern (ZIP)","Projekt-ZIP öffnen"}
    right=app.winfo_rootx()+app.winfo_width()
    for button in found.values():
        assert button.winfo_ismapped()
        assert button.winfo_rootx()>=app.winfo_rootx()
        assert button.winfo_rootx()+button.winfo_width()<=right
    view=app.hud_menu_tab
    assert view.project_actions_row.winfo_manager()==""
    assert view.journey.winfo_manager()==""
    # The old project actions remain reachable under specialists.
    view.tools_toggle.invoke()
    assert view.project_actions_row.winfo_manager()=="pack"
    assert view.journey.winfo_manager()=="pack"
    view.tools_toggle.invoke()
    assert view.project_actions_row.winfo_manager()==""


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



def test_idle_cancel_is_hidden_and_only_exposed_for_accepted_jobs(ui,monkeypatch):
    mod,app=ui
    assert app.stop_button.winfo_manager()==""
    monkeypatch.setattr(mod.center.Center,"run",lambda *_args,**_kw:False)
    assert app.run(["unused"],"fake") is False
    assert app.stop_button.winfo_manager()==""
    monkeypatch.setattr(mod.center.Center,"run",lambda *_args,**_kw:True)
    assert app.run(["unused"],"fake") is True
    assert app.stop_button.winfo_manager()=="pack"
    assert "disabled" not in app.stop_button.state() or not app.runner.busy
    app._drain()
    assert app.stop_button.winfo_manager()==""


def test_sandbox_empty_map_hint_points_to_setup_and_disappears_for_real_map(
    ui,monkeypatch,
):
    from types import SimpleNamespace
    _mod,app=ui
    view=app.sandbox_tab
    assert view.empty_map_banner.winfo_manager()==""
    fake_canvas=SimpleNamespace(has_map=lambda:False)
    view.bridge=SimpleNamespace(window=SimpleNamespace(native_canvas=fake_canvas))
    try:
        view._refresh_map_hint()
        assert view.empty_map_banner.winfo_manager()=="pack"
        assert "Keine Karte geladen" in view.map_hint_text.get()
        app.set_language("en")
        assert "No map loaded" in view.map_hint_text.get()
        assert view.setup_map_button.cget("text")=="Set up game folder"
        monkeypatch.setattr(fake_canvas,"has_map",lambda:True)
        view._refresh_map_hint()
        assert view.empty_map_banner.winfo_manager()==""
    finally:
        view.bridge=None


def test_legacy_exchange_bottom_tools_can_be_reached_by_section_picker(ui):
    from tkinter import ttk
    _mod,app=ui
    app.geometry("1020x680+20+20")
    view=app.exchange_tab
    app.open_tab(view)
    app.update()
    section=next(k for k in view.section_targets if "Mehrteilige" in k)
    view.section_choice.set(section)
    view.jump_to_section()
    app.update()
    bottom=app.winfo_rooty()+app.winfo_height()
    actions=[]
    pending=[view.form_scroll.body]
    while pending:
        node=pending.pop()
        pending.extend(node.winfo_children())
        if isinstance(node,ttk.Button) and node.cget("text") in (
            "Als ORA zusammensetzen","ORA zuruecknehmen ..."):
            actions.append(node)
    assert len(actions)==2
    for widget in actions:
        assert widget.winfo_ismapped()
        assert widget.winfo_rooty()>=app.winfo_rooty()
        assert widget.winfo_rooty()+widget.winfo_height()<=bottom


def test_header_switches_language_without_navigation_or_reloading_project(ui):
    _mod,app=ui
    original=app.workflow_tab.pipeline.project
    app.set_language("en")
    app.update()
    assert app.title()=="SpriteSuite – Graphics and mod packages"
    subtitle=[x for x in app.status_label.master.winfo_children()
              if hasattr(x,"cget") and "text" in x.keys()
              and x.cget("text")=="Graphics workshop for Stronghold"]
    assert subtitle
    app.set_language("de")
    app.update()
    assert app.title()=="SpriteSuite – Grafiken und Modpakete"
    assert subtitle[0].cget("text")=="Grafikwerkstatt für Stronghold"
    assert app.workflow_tab.pipeline.project==original

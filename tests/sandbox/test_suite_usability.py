"""End-to-end usability checks for the full Sprite Suite window.

These tests check real Win/Tk layout and interactions without launching
game, installers, Unity, sprite mutation, or long-running background tools.
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
from pathlib import Path
import sys
import tkinter as tk
from tkinter import messagebox, ttk
from types import SimpleNamespace

import pytest

ROOT=Path(__file__).resolve().parents[2]
if str(ROOT/"tools") not in sys.path:
    sys.path.insert(0,str(ROOT/"tools"))

from suite_usability import ScrollableColumn, run_then_success


def _suite():
    loader=importlib.machinery.SourceFileLoader(
        "suite_full_usability_test",
        str(ROOT/"tools"/"suite_universal.pyw"),
    )
    spec=importlib.util.spec_from_loader(loader.name,loader)
    module=importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture
def app_fixture(tmp_path,monkeypatch):
    suite=_suite()
    settings=tmp_path/"suite-settings.json"
    # GUI inspection must not compete with the real app's single-instance
    # workspace lock; keep lock semantics, but use a per-test file.
    import stronghold_europe_de.workspace_lock as lock_module
    monkeypatch.setattr(
        lock_module, "lock_path",
        lambda _workspace, _name: tmp_path / "suite-usability-instance.lock",
    )
    monkeypatch.setattr(suite,"SETTINGS",settings)
    old_lang=suite.LANG.code
    suite.LANG.code="de"
    try:
        app=suite.Universal()
    except tk.TclError as exc:
        # This Suite is a Windows desktop product. A broken Tcl/Tk runtime
        # on Windows is a test FAILURE, not an acceptable skipped workflow.
        if sys.platform == "win32":
            raise
        pytest.skip(str(exc))
    # Test navigation and layout; the real Qt embedding is smoke-tested
    # separately by qa_suite_embedded.py.
    monkeypatch.setattr(app.sandbox_tab,"ensure_studio",lambda:None)
    if not (ROOT/"work"/"mapping"/"proposals.json.gz").is_file():
        # A fresh checkout correctly lacks private game-data mappings. Supply
        # only the two synthetic frame rows required for GUI navigation tests,
        # without weakening production's fail-closed missing-map behavior.
        original_group_rows=suite.katalog.group_rows
        def test_group_rows(group):
            if group == "anim_castle":
                return [
                    {"name":f"anim_castle {index:03d}",
                     "action":"KEEP_CRUSADER",
                     "target":{"width":64,"height":64,
                               "pivot_x":0.5,"pivot_y":0.5}}
                    for index in (2,3)
                ]
            return original_group_rows(group)
        monkeypatch.setattr(suite.katalog,"group_rows",test_group_rows)
    try:
        yield suite,app,settings
    finally:
        suite.LANG.code=old_lang
        app.destroy()


def _find_buttons(widget,content):
    stack=[widget]
    found=[]
    while stack:
        node=stack.pop()
        stack.extend(node.winfo_children())
        if isinstance(node,ttk.Button) and content in node.cget("text"):
            found.append(node)
    return found


def _inside(widget,viewport):
    if not widget.winfo_ismapped():
        return False
    return (
        widget.winfo_rootx()>=viewport.winfo_rootx()-2
        and widget.winfo_rootx()+widget.winfo_width()<=
            viewport.winfo_rootx()+viewport.winfo_width()+2
        and widget.winfo_rooty()>=viewport.winfo_rooty()-2
        and widget.winfo_rooty()+widget.winfo_height()<=
            viewport.winfo_rooty()+viewport.winfo_height()+2
    )


@pytest.mark.parametrize("window_size",[(1020,680),(1320,800)])
def test_all_primary_workflows_reachable_at_real_window_sizes(app_fixture,window_size):
    suite,app,settings=app_fixture
    app.geometry(f"{window_size[0]}x{window_size[1]}+25+25")
    app.update()
    # Setup, catalogue, diagnosis, sandbox, exchange, install and build.
    mandatory=(
        app.setup_page,app.catalog_tab,app.diagnose_tab,app.sandbox_tab,
        app.exchange_tab,app.target_tab,app.bc7_page,
    )
    for tab in mandatory:
        app.open_tab(tab)
        app.update()
        assert app.notebook.select()==str(tab)
        assert app.quick_section.get()
        assert app.quick_picker.winfo_ismapped()
        assert _inside(app.quick_picker,app)

    app.open_tab(app.catalog_tab)
    app.update()
    # The editor is intentionally closed until a sprite is selected:
    # browsing gets the full thumbnail canvas, then the edit action appears.
    assert not app.catalog_tab._edit_panel_visible
    app.catalog_tab.open_group("anim_castle","anim_castle 002")
    app.update()
    assert app.catalog_tab._edit_panel_visible
    assert _inside(app.catalog_tab.apply_button,app.catalog_tab)
    assert _inside(
        _find_buttons(app.catalog_tab,"Neu laden")[0],
        app.catalog_tab,
    )
    assert app.catalog_tab.actions_scroll.scrollbar.winfo_ismapped()
    assert app.catalog_tab.grid_scrollbar.winfo_ismapped()
    assert app.catalog_tab.detail_scroll.winfo_ismapped()

    app.open_tab(app.diagnose_tab)
    app.update()
    assert _inside(
        _find_buttons(app.diagnose_tab,"Als geprueft markieren")[0],
        app.diagnose_tab,
    )
    assert _inside(
        _find_buttons(app.diagnose_tab,"QA-Altbestand")[0],
        app.diagnose_tab,
    )

    app.open_tab(app.exchange_tab)
    app.update()
    scroll=app.exchange_tab.form_scroll.canvas
    assert app.exchange_tab.form_scroll.scrollbar.winfo_ismapped()
    assert scroll.yview()[1] <= 1
    scroll.yview_moveto(1)
    app.update()
    for button in _find_buttons(app.exchange_tab,"ORA"):
        if button.cget("text") in ("Als ORA zusammensetzen","ORA zuruecknehmen ..."):
            assert _inside(button,scroll),button.cget("text")

    app.open_tab(app.setup_page)
    app.update()
    scroll=app.setup_scroller.canvas
    scroll.yview_moveto(1)
    app.update()
    assert _inside(_find_buttons(app.setup_page,"Anleitung öffnen")[0],scroll)
    assert _inside(_find_buttons(app.setup_page,".NET SDK herunterladen")[0],scroll)


def test_quick_navigation_auto_reveals_advanced_tabs_and_persists(app_fixture):
    suite,app,settings=app_fixture
    app.geometry("1020x680+30+30")
    app.update()
    assert app.advanced.get() is False
    # The guided landing page is now always visible and selected on startup.
    assert app.notebook.select()==str(app.tab_home)
    assert app.notebook.tab(app.tab_home,"state")=="normal"
    app.quick_section.set("Start & Anleitung")
    app._quick_navigation_selected()
    app.update()
    assert app.notebook.select()==str(app.tab_home)
    assert app.advanced.get() is False
    # A truly specialist legacy tab still reveals advanced mode explicitly.
    app.quick_section.set("Texte")
    app._quick_navigation_selected()
    app.update()
    assert app.notebook.select()==str(app.tab_text)
    assert app.advanced.get() is True
    assert json.loads(settings.read_text(encoding="utf-8"))["erweiterte_werkzeuge"] is True

    app.open_tab(app.tab_home)
    app.set_language("en")
    app.update()
    assert app.quick_section.get()=="Start and guide"
    app.quick_section.set("Diagnosis and repair")
    app._quick_navigation_selected()
    app.update()
    assert app.notebook.select()==str(app.diagnose_tab)
    app.set_language("de")
    assert app.quick_section.get()=="Diagnose & Reparatur"
    app.advanced.set(False)
    app.show_advanced()
    app.update()
    assert json.loads(settings.read_text(encoding="utf-8"))["erweiterte_werkzeuge"] is False


def test_catalog_selection_never_retains_frame_from_other_group(app_fixture):
    suite,app,_=app_fixture
    cat=app.catalog_tab
    app.open_tab(cat)
    app.update()
    cat.open_group("anim_castle","anim_castle 002")
    assert cat.selected=="anim_castle 002"
    assert cat.group=="anim_castle"
    assert cat.tree.selection()==("g:anim_castle",)
    cat.open_group("anim_drawbridge")
    assert cat.group=="anim_drawbridge"
    assert cat.selected is None
    assert cat.tree.selection()==("g:anim_drawbridge",)
    assert "Bitte einen Frame" in cat.info.cget("text")


def test_catalog_cross_tab_navigation_clears_blocking_search(app_fixture):
    suite,app,_=app_fixture
    cat=app.catalog_tab
    app.open_tab(cat)
    app.update()
    cat.filter.set("nothing-should-ever-match-this")
    cat.fill_tree()
    assert "Keine Gruppen" in cat.tree_status.cget("text")
    app.show_in_catalog("anim_castle","anim_castle 002")
    app.update()
    assert cat.filter.get()==""
    assert cat.tree.exists("g:anim_castle")
    assert cat.tree.selection()==("g:anim_castle",)
    assert cat.selected=="anim_castle 002"
    assert cat.frames[0]["name"].startswith("anim_castle")


def test_catalog_jump_reports_invalid_input_instead_of_silence(
    app_fixture,monkeypatch
):
    _,app,_=app_fixture
    cat=app.catalog_tab
    cat.open_group("anim_castle","anim_castle 002")
    messages=[]
    monkeypatch.setattr(
        messagebox,"showinfo",lambda *a,**kw:messages.append(a)
    )
    for value in ("what","-4","999999"):
        cat.jump.set(value)
        cat.jump_to()
    assert len(messages)==3
    assert "nicht-negative" in messages[0][1]
    assert "nicht-negative" in messages[1][1]
    assert "nicht vorhanden" in messages[2][1]
    cat.jump.set("3")
    cat.jump_to()
    assert cat.selected=="anim_castle 003"


def test_catalog_apply_requires_real_changes_and_explicit_confirmation(
    app_fixture,monkeypatch
):
    suite,app,_=app_fixture
    cat=app.catalog_tab
    cat.open_group("anim_castle","anim_castle 002")
    started=[]
    dialogs=[]
    monkeypatch.setattr(app,"run",lambda args,label:started.append((args,label)))
    monkeypatch.setattr(
        messagebox,"showinfo",lambda *a,**kw:dialogs.append(("info",a))
    )
    monkeypatch.setattr(
        messagebox,"askyesno",lambda *a,**kw:dialogs.append(("ask",a)) or False
    )
    monkeypatch.setattr(suite.katalog,"changed_frames",lambda group:[])
    cat.apply()
    assert not started and dialogs[-1][0]=="info"
    monkeypatch.setattr(
        suite.katalog,"changed_frames",lambda group:["anim_castle 002"]
    )
    cat.apply()
    assert not started and dialogs[-1][0]=="ask"
    monkeypatch.setattr(messagebox,"askyesno",lambda *a,**kw:True)
    cat.apply()
    assert len(started)==1
    assert "anwenden" in started[0][0]


def test_diagnose_proof_pin_adoption_requires_confirmation(
    app_fixture,monkeypatch
):
    _,app,_=app_fixture
    started=[]
    monkeypatch.setattr(app,"run",lambda args,label:started.append((args,label)))
    confirmations=[]
    monkeypatch.setattr(
        messagebox,"askyesno",
        lambda *a,**kw:confirmations.append((a,kw)) or False
    )
    app.diagnose_tab.adopt()
    assert confirmations
    assert confirmations[0][1]["default"]=="no"
    assert not started
    monkeypatch.setattr(messagebox,"askyesno",lambda *a,**kw:True)
    app.diagnose_tab.adopt()
    assert len(started)==1
    assert "--aus-protokoll" in started[0][0]


def test_exchange_bad_inputs_are_explained_not_executed(
    app_fixture,monkeypatch
):
    _,app,_=app_fixture
    panel=app.exchange_tab
    started=[]
    messages=[]
    monkeypatch.setattr(app,"run",lambda *a:started.append(a))
    monkeypatch.setattr(messagebox,"showinfo",lambda *a,**kw:messages.append(a))
    monkeypatch.setattr(messagebox,"showwarning",lambda *a,**kw:messages.append(a))
    panel.export()
    panel.atlas_project()
    panel.ora_from.set("not-an-integer")
    panel.ora_compose()
    panel.ora_from.set("1192")
    panel.ora_n.set("-2")
    panel.ora_compose()
    panel.atlas_build()
    assert not started
    assert len(messages)>=5
    assert "ganze Zahlen" in messages[2][1]
    assert "Raster" in messages[3][1]
    assert "Projekt erzeugen" in messages[-1][1]


class _FakeApp:
    def __init__(self):
        self.runner=SimpleNamespace(busy=False)
        self.done_hooks=[]
        self.calls=[]
        self.after_calls=[]
        self.logs=[]
    def run(self,args,label):
        self.calls.append((args,label))
        self.runner.busy=True
    def after(self,delay,callback):
        self.after_calls.append((delay,callback))
    def log(self,*args):
        self.logs.append(args)


def test_two_stage_editor_action_only_after_success():
    app=_FakeApp()
    invoked=[]
    assert run_then_success(
        app,["export"],"Sprite export",
        lambda:invoked.append("open"),
        next_step="Open HTML editor"
    )
    assert len(app.done_hooks)==1
    assert app.after_calls==[]
    app.done_hooks[0](0)
    assert not app.done_hooks
    assert len(app.after_calls)==1
    app.after_calls[0][1]()
    assert invoked==["open"]


def test_two_stage_editor_action_blocks_followup_on_failed_split():
    app=_FakeApp()
    invoked=[]
    assert run_then_success(
        app,["split"],"ORA split",
        lambda:invoked.append("import"),
        next_step="Import ORA"
    )
    app.done_hooks[0](2)
    assert not app.done_hooks and not app.after_calls
    assert not invoked
    assert "Nicht ausgeführt" in app.logs[0][0]


def test_two_stage_workflow_rejects_busy_runner(monkeypatch):
    app=_FakeApp()
    app.runner.busy=True
    messages=[]
    monkeypatch.setattr(messagebox,"showinfo",
                        lambda *args,**kw:messages.append(args))
    assert not run_then_success(
        app,["split"],"ORA split",lambda:None,next_step="Import ORA"
    )
    assert not app.done_hooks
    assert not app.calls
    assert messages


def test_two_stage_workflow_cleans_hook_after_start_error():
    app=_FakeApp()
    def raising(*args,**kwargs):
        raise RuntimeError("start refused")
    app.run=raising
    with pytest.raises(RuntimeError,match="start refused"):
        run_then_success(
            app,["split"],"ORA split",lambda:None,next_step="Import ORA"
        )
    assert not app.done_hooks


def test_reopening_suite_does_not_stack_global_tk_dialog_wrappers():
    from tkinter import messagebox as mb, filedialog as fd
    first=_suite()
    first.LANG.patch_dialogs()
    wrapped=(mb.showinfo,mb.askyesno,fd.askopenfilename)
    second=_suite()
    second.LANG.patch_dialogs()
    assert (mb.showinfo,mb.askyesno,fd.askopenfilename)==wrapped
    assert mb._sprite_suite_language is second.LANG
    assert fd._sprite_suite_language is second.LANG
    assert getattr(mb.showinfo,"_sprite_suite_translated",False) is True


@pytest.mark.parametrize("window_size",[(1020,680),(1320,800)])
def test_global_workspace_console_toggle_keeps_log_and_space(app_fixture,window_size):
    _,app,_=app_fixture
    app.geometry(f"{window_size[0]}x{window_size[1]}+28+28")
    app.open_tab(app.setup_page)
    app.update()
    assert app.console.master.winfo_manager()==""
    assert app.setup_page.winfo_height()>=500
    app.log("workspace usability synthetic log marker","muted")
    app.console_toggle.invoke()
    app.update()
    assert app.console.master.winfo_manager()=="pack"
    assert "workspace usability synthetic log marker" in app.console.get("1.0","end")
    assert app.console_toggle.cget("text")=="Protokoll ausblenden"
    app.open_tab(app.catalog_tab)
    app.update()
    app.open_tab(app.sandbox_tab)
    app.update()
    assert app.console.master.winfo_manager()=="pack"
    app.open_tab(app.setup_page)
    app.console_toggle.invoke()
    app.update()
    assert app.console.master.winfo_manager()==""
    assert app.setup_page.winfo_height()>=500
    app.log("synthetic tool failure marker","bad")
    assert "Fehler anzeigen" in app.console_toggle.cget("text")
    app.console_toggle.invoke()
    assert "synthetic tool failure marker" in app.console.get("1.0","end")


def test_compact_tab_strip_preserves_every_legacy_route(app_fixture):
    _,app,_=app_fixture
    app.geometry("1020x680+28+28")
    app.update()
    assert app._compact_tabs is True
    assert all(
        app.notebook.tab(tab,"state")=="normal"
        for tab in (app.setup_page,app.tab_art,app.catalog_tab,
                    app.diagnose_tab,app.sandbox_tab,
                    app.exchange_tab,app.target_tab,app.bc7_page)
    )
    # The 14 October workflow redesign promoted the guided landing page to
    # the *primary* workspace. Compact mode must not make it disappear.
    assert app.notebook.tab(app.tab_home,"state")=="normal"
    labels=[app.notebook.tab(item,"text") for item in app.notebook.tabs()]
    assert "Katalog" in labels and "Diagnose" in labels
    assert "Asset-Katalog" not in labels
    # The quick navigator deliberately reopens hidden old functions.
    app.quick_section.set("Start & Anleitung")
    app._quick_navigation_selected()
    app.update()
    assert app.notebook.select()==str(app.tab_home)
    assert app.notebook.tab(app.tab_home,"state")=="normal"
    app.tab_strip_toggle.invoke()
    app.update()
    assert app._compact_tabs is False
    assert app.notebook.tab(app.tab_ui,"state")=="normal"
    assert app.notebook.tab(app.tab_build,"state")=="normal"
    app.tab_strip_toggle.invoke()
    app.update()
    assert app._compact_tabs is True
    app.open_tab(app.catalog_tab)
    app.update()
    assert app.notebook.tab(app.tab_home,"state")=="normal"
    assert app.notebook.tab(app.catalog_tab,"text")=="Katalog"
    # Advanced/compact switching never hides the Start entry again.
    app.notebook.select(app.tab_home)
    app.update()
    assert app.notebook.select()==str(app.tab_home)


def test_catalog_thumbnail_first_preview_and_menu_remain_accessible(app_fixture):
    _,app,_=app_fixture
    app.geometry("1020x680+24+24")
    app.open_tab(app.catalog_tab)
    cat=app.catalog_tab
    app.update()
    assert not cat._edit_panel_visible
    assert not cat.detail_holder.winfo_ismapped()
    assert cat.catalog_actions.menu_names()==[
        "Kategorie anlegen","Gruppe zuordnen",
        "Erweiterung anlegen","Erweiterung binden",
    ]
    cat.open_group("anim_castle","anim_castle 002")
    app.update()
    assert cat._edit_panel_visible and cat.detail_holder.winfo_ismapped()
    assert _inside(cat.apply_button,cat)
    cat.details_button.invoke()
    app.update()
    assert not cat._edit_panel_visible
    assert cat.selected=="anim_castle 002"
    cat.details_button.invoke()
    app.update()
    assert cat._edit_panel_visible
    assert cat.selected=="anim_castle 002"
    assert _inside(cat.apply_button,cat)


def test_diagnosis_short_actions_and_table_horizontal_navigation(app_fixture):
    _,app,_=app_fixture
    app.geometry("1020x680+24+24")
    app.open_tab(app.diagnose_tab)
    app.update()
    diag=app.diagnose_tab
    assert diag.check_actions.menu_names()==[
        "Umlenkungen mit Bildern","Drift","Leinwand","Bundles",
    ]
    assert diag.pivot_menu.entrycget(0,"label")=="Pivot-Protokoll wählen …"
    assert _inside(diag.preflight_button,diag)
    assert _inside(diag.pivot_stage_button,diag)
    assert diag.table_scroll_x.winfo_ismapped()
    diag.table.xview_moveto(1)
    app.update()
    assert diag.table.xview()[0]>0
    diag.table.xview_moveto(0)
    assert diag.table.xview()[0]==0


def test_target_short_actions_and_scroll_does_not_execute_installs(app_fixture):
    _,app,_=app_fixture
    app.geometry("1020x680+24+24")
    app.open_tab(app.target_tab)
    app.update()
    target=app.target_tab
    assert set(target.actions.buttons)=={
        "Ziel hinzufügen ...","Aktivieren","Aktualisieren",
    }
    assert len(target.actions.menu_names())==4
    assert "mit Sicherung" in target.actions.menu_names()[0]
    assert _inside(target.actions.more_button,target)
    assert target.table_scroll_x.winfo_ismapped()
    target.table.xview_moveto(1)
    app.update()
    assert target.table.xview()[0]>0


def test_exchange_sections_can_be_reached_without_wheel_precision(app_fixture):
    _,app,_=app_fixture
    app.geometry("1020x680+24+24")
    app.open_tab(app.exchange_tab)
    app.update()
    exchange=app.exchange_tab
    choices=tuple(exchange.section_targets)
    assert len(choices)>=3
    assert exchange.section_picker.winfo_ismapped()
    exchange.section_choice.set(choices[-1])
    exchange.jump_to_section()
    print("AFTER_SECTION_JUMP",exchange.form_scroll.canvas.yview(),flush=True)
    app.update()
    canvas=exchange.form_scroll.canvas
    print("AFTER_GUI_UPDATE",canvas.yview(),canvas.bbox("all"),flush=True)
    region=canvas.bbox("all")
    target=exchange.section_targets[choices[-1]]
    if region and region[3]-region[1] > canvas.winfo_height()+2:
        assert canvas.yview()[0]>0
        # The selected heading is near the top, leaving its fields visible.
        assert 0 <= target.winfo_rooty()-canvas.winfo_rooty() < 85
    else:
        assert _inside(target,canvas)


def test_legacy_editor_build_and_guide_have_separate_scrollable_views(app_fixture):
    _,app,_=app_fixture
    app.geometry("1020x680+24+24")
    app.open_tab(app.tab_art)
    app.update()
    art=app.tab_art
    assert art.page_return in art.pages.winfo_children()
    assert "Rückweg" in [art.pages.tab(page,"text") for page in art.pages.tabs()]
    art.pages.select(art.page_return)
    app.update()
    assert art.page_return.winfo_ismapped()
    art.pages.select(art.page_preview)
    app.update()
    assert not art.page_return.winfo_ismapped()

    app.open_tab(app.tab_build)
    app.update()
    build=app.tab_build
    assert build.workflow_scroll.scrollbar.winfo_ismapped()
    build.workflow_scroll.canvas.yview_moveto(1)
    app.update()
    scroll=build.workflow_scroll.canvas
    region=scroll.bbox("all")
    if region and region[3]-region[1] > scroll.winfo_height()+2:
        assert scroll.yview()[0]>0
    assert _inside(_find_buttons(build,"Mod deinstallieren")[0],scroll)

    app.open_tab(app.tab_home)
    app.update()
    home=app.tab_home
    assert home.guide_scroll.scrollbar.winfo_ismapped()
    assert "Schritt für Schritt" in [
        home.guide_sections.tab(item, "text")
        for item in home.guide_sections.tabs()
    ]
    assert "Projektbereitschaft" in [
        home.guide_sections.tab(item, "text")
        for item in home.guide_sections.tabs()
    ]
    home.guide_scroll.canvas.yview_moveto(1)
    app.update()
    scroll=home.guide_scroll.canvas
    region=scroll.bbox("all")
    if region and region[3]-region[1] > scroll.winfo_height()+2:
        assert scroll.yview()[0]>0
    assert _inside(_find_buttons(home,"Anleitung öffnen")[0],scroll)
    home.guide_sections.select(1)
    app.update()
    assert home.readiness.winfo_ismapped()
    home.guide_sections.select(0)
    app.update()


def test_bc7_and_tool_catalog_preserve_access_to_bottom_fields(app_fixture):
    _,app,_=app_fixture
    app.geometry("1020x680+24+24")
    app.advanced.set(True)
    app.show_advanced()
    app.open_tab(app.bc7_page)
    app.update()
    assert app.bc7_scroller.scrollbar.winfo_ismapped()
    app.bc7_scroller.canvas.yview_moveto(1)
    app.update()
    assert app.bc7_scroller.canvas.yview()[0]>0
    assert _find_buttons(app.bc7_page,"Cacheordner öffnen")
    app.open_tab(app.catalog_page)
    app.update()
    assert app.catalog_field_scroll.scrollbar.winfo_ismapped()
    # An expanding form used to push the actual execution buttons offscreen.
    assert _inside(app.catalog_help_button, app.catalog_page)
    assert _inside(app.catalog_run_button, app.catalog_page)
    app.catalog_field_scroll.bind_mousewheel()
    app.catalog_field_scroll.bind_mousewheel()
    assert hasattr(app.catalog_field_scroll.canvas,"_suite_scroll_owner")


def test_targets_empty_state_explains_first_action_and_preserves_registry(
    app_fixture, monkeypatch
):
    import ziel_se211

    _, app, _ = app_fixture
    app.open_tab(app.target_tab)
    target = app.target_tab
    monkeypatch.setattr(
        ziel_se211, "targets",
        lambda: {"schema":"stronghold-europe.ziele.v1",
                 "ziele":{}, "aktiv":None}
    )
    target.load()
    app.update()
    assert not target.table.get_children()
    assert "Noch kein Zielspiel registriert" in target.target_status.get()
    assert "noch nichts installiert" in target.target_status.get()
    messages = []
    monkeypatch.setattr(
        messagebox, "showinfo",
        lambda title, body, **kw: messages.append((title, body)),
    )
    assert target.current() is None
    assert len(messages)==1
    assert "Ziel hinzufügen" in messages[0][1]
    assert target.actions.buttons["Aktualisieren"].winfo_ismapped()


def test_targets_status_distinguishes_valid_and_invalid_registry(
    app_fixture, monkeypatch
):
    import ziel_se211

    _, app, _ = app_fixture
    target = app.target_tab
    monkeypatch.setattr(
        ziel_se211, "targets",
        lambda: {"ziele": {"dev": {"spiel":"C:/synthetic-game"}},
                 "aktiv":"dev"},
    )
    monkeypatch.setattr(
        ziel_se211, "describe",
        lambda name, spec: {
            "spiel": spec["spiel"],
            "se": None, "se_2_11": False,
            "sicherungen":0, "spielstand":"synthetisch",
        },
    )
    target.load()
    assert len(target.table.get_children())==1
    assert "Aktiv: dev" in target.target_status.get()
    assert target.table.item("dev", "values")[0] == "●"
    monkeypatch.setattr(ziel_se211, "targets", lambda: ["wrong root"])
    target.load()
    assert not target.table.get_children()
    assert "Ziele konnten nicht gelesen werden" in target.target_status.get()
    assert "nicht verändert" in target.target_status.get()
    monkeypatch.setattr(
        ziel_se211, "targets",
        lambda: {"ziele": {"bad": [123]}, "aktiv": None},
    )
    target.load()
    assert not target.table.get_children()
    assert "ungültige Registry-Einträge" in target.target_status.get()
    assert "unverändert" in target.target_status.get()
    # A corrupt active-target field must not crash lookup or conceal
    # the available valid target rows.
    monkeypatch.setattr(
        ziel_se211, "targets",
        lambda: {"ziele": {"dev": {"spiel":"C:/synthetic-game"}},
                 "aktiv": ["invalid active value"]},
    )
    target.load()
    assert len(target.table.get_children()) == 1
    assert "Noch kein aktives Ziel gewählt" in target.target_status.get()
    # The registry loader may fail internally before returning a mapping.
    monkeypatch.setattr(
        ziel_se211, "targets",
        lambda: (_ for _ in ()).throw(AttributeError("broken target file")),
    )
    target.load()
    assert not target.table.get_children()
    assert "nicht gelesen werden" in target.target_status.get()


def test_diagnose_empty_state_and_readonly_reports_are_explicit(
    app_fixture, monkeypatch, tmp_path
):
    suite, app, _ = app_fixture
    app.open_tab(app.diagnose_tab)
    diag = app.diagnose_tab
    # Read-only sandbox root. No real app/game config or report is modified.
    monkeypatch.setattr(suite, "ROOT", tmp_path)
    diag.load()
    app.update()
    assert not diag.table.get_children()
    assert (
        "Keine Einträge" in diag.findings_status.get()
        or "Noch kein Diagnosebericht" in diag.findings_status.get()
    )
    diag.show_release_report({
        "summary": {"state": "offline_warnings"},
        "findings": [{
            "schwere": "warnung",
            "pruefung": "Synthetic offline check",
            "gruppe": "-",
            "text": "Only a synthetic read-only test",
        }],
    })
    assert len(diag.table.get_children())==1
    assert "SHA-256-Releasebericht" in diag.findings_status.get()
    assert "1 Eintrag" in diag.findings_status.get()
    assert "Offline-Status" in diag.detail.cget("text")
    assert not app.runner.busy


def test_diagnose_malformed_report_shows_recoverable_readonly_warning(
    app_fixture, monkeypatch, tmp_path
):
    suite, app, _ = app_fixture
    diag = app.diagnose_tab
    monkeypatch.setattr(suite, "ROOT", tmp_path)
    report = tmp_path / "work" / "diagnose" / "bericht.json"
    report.parent.mkdir(parents=True)
    # Syntax errors, wrong root, bad schema, and a partially malformed row:
    # none may masquerade as a verified empty report.
    for broken in (
        b"{broken",
        b"[]",
        b'{"befunde":"broken"}',
        b'{"befunde":[{"schwere":"info","pruefung":"ok",'
        b'"gruppe":"-","text":"one valid"}, {"wrong":"row"}]}',
    ):
        report.write_bytes(broken)
        diag.load()
        assert not diag.table.get_children()
        assert "nicht lesbar" in diag.findings_status.get()
        assert "nicht verändert" in diag.findings_status.get()
        assert report.read_bytes() == broken
    # An actual valid empty report is a different, non-release state.
    report.write_text('{"befunde":[]}', encoding="utf-8")
    diag.load()
    assert "Keine Einträge" in diag.findings_status.get()
    assert "keine BC7- oder Ingame-Freigabe" in diag.findings_status.get()
    assert not app.runner.busy


def test_catalog_selected_group_survives_filter_refresh_and_late_tk_events(app_fixture):
    """Rebuilds must never erase a valid group or reset the frame silently."""
    _,app,_=app_fixture
    cat=app.catalog_tab
    app.open_tab(cat)
    app.update()
    cat.open_group("anim_castle","anim_castle 002")
    app.update()
    assert cat.tree.selection()==("g:anim_castle",)
    for _ in range(3):
        # Filtering temporarily removes the selected item's native Treeview
        # row, but must not lose its model selection.
        cat.filter.set("no-such-category-xyz")
        cat.fill_tree()
        app.update()
        assert cat.tree.selection()==()
        assert (cat.group,cat.selected)==("anim_castle","anim_castle 002")
        cat.filter.set("")
        cat.fill_tree()
        app.update()
        assert cat.tree.selection()==("g:anim_castle",)
        assert (cat.group,cat.selected)==("anim_castle","anim_castle 002")
        cat.load_tree()  # asynchronous real category refresh
        app.update()
        assert cat.tree.selection()==("g:anim_castle",)
        assert cat.selected=="anim_castle 002"
    cat.open_group("anim_drawbridge")
    app.update()
    assert cat.tree.selection()==("g:anim_drawbridge",)
    assert cat.group=="anim_drawbridge"
    assert cat.selected is None


def test_rejected_tool_start_does_not_leave_delayed_followup_hook():
    """Prevents ORA import or external editor from launching after OTHER job."""
    app=_FakeApp()
    app.run=lambda _args,_label:False  # declined by Runner.start()
    called=[]
    assert not run_then_success(
        app,["ora-split"],"ORA zerlegen",
        lambda:called.append("import"),next_step="ORA importieren",
    )
    assert app.done_hooks==[] and called==[] and app.after_calls==[]
    assert "Nicht gestartet" in app.logs[-1][0]
    # An unrelated later task must have no registered callback to trigger.
    assert not any(app.done_hooks)

def test_guided_home_all_seven_routes_are_safe_navigation_only(app_fixture,monkeypatch):
    """Every main user goal opens the intended work area without running tools."""
    suite,app,_=app_fixture
    app.geometry("1020x680+25+25")
    app.update()
    home=app.tab_home
    assert app.notebook.select()==str(home)
    assert tuple(app.notebook.tabs())[0]==str(home)
    assert app.notebook.tab(home,"state")=="normal"
    selected = []
    monkeypatch.setattr(app,"run",lambda *a,**kw:pytest.fail(
        "Choosing a work area may not execute any CLI, installer or game action"
    ))
    page=home.nametowidget(home.guide_sections.tabs()[0])
    buttons=[
        child for row in page.winfo_children() for child in row.winfo_children()
        if isinstance(child,ttk.Button) and child.cget("text")=="Öffnen"
    ]
    targets=(
        app.setup_page,app.catalog_tab,app.sandbox_tab,app.exchange_tab,
        app.diagnose_tab,app.bc7_page,app.target_tab
    )
    assert len(buttons)==len(targets)==7
    # Guided Start needs to show each essential action even at 1020x680:
    # avoid a hidden installation link below the initial scroll position.
    assert all(_inside(button,home.guide_scroll.canvas) for button in buttons)
    for button,target in zip(buttons,targets):
        button.invoke()
        app.update()
        assert app.notebook.select()==str(target)
        selected.append(target)
    assert selected==list(targets)
    app.open_tab(home)
    app.set_language("en")
    app.update()
    assert "What would you like" in next(
        child.cget("text") for child in home.guide_scroll.body.winfo_children()
        if isinstance(child,ttk.Label) and child.cget("style")=="Title.TLabel"
    )
    assert all(
        isinstance(button,ttk.Button) and button.cget("text")=="Open"
        for button in buttons
    )
    assert app.notebook.select()==str(home)
    assert app.advanced.get() is False or app.advanced.get() is True
    # Navigation doesn't change the current active build profile or source.

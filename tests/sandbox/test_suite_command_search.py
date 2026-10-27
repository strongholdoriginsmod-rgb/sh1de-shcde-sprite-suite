"""Safe bilingual navigation across every Sprite Suite workspace."""
from __future__ import annotations
import importlib.machinery
import importlib.util
import tkinter as tk
from pathlib import Path
import sys
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/"tools"),str(ROOT/"src")]
from suite_command_search import normalize_search,find_targets,build_navigation_targets

def suite_module():
    loader=importlib.machinery.SourceFileLoader(
        "suite_command_search_under_test",str(ROOT/"tools"/"suite_universal.pyw"))
    spec=importlib.util.spec_from_loader(loader.name,loader)
    module=importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module

@pytest.fixture
def suite_gui(tmp_path,monkeypatch):
    suite=suite_module()
    import stronghold_europe_de.workspace_lock as lock
    monkeypatch.setattr(lock,"lock_path",
                        lambda _workspace,_name:tmp_path/"suite-finder.lock")
    monkeypatch.setattr(suite,"SETTINGS",tmp_path/"settings.json")
    old=suite.LANG.code
    suite.LANG.code="de"
    try:
        app=suite.Universal()
    except tk.TclError as exc:
        pytest.skip(str(exc))
    monkeypatch.setattr(app.sandbox_tab,"ensure_studio",lambda:None)
    app.geometry("1020x680+25+25")
    app.update()
    try:
        yield suite,app
    finally:
        suite.LANG.code=old
        dialog=getattr(app,"_command_search",None)
        if dialog is not None and dialog.winfo_exists():
            dialog.close()
        app.destroy()

@pytest.mark.parametrize("source,expected",[
    ("Küstenstraße","kuestenstrasse"),
    ("Zinnen/Lineal","zinnen lineal"),
    ("Prüfung/Atlas","pruefung atlas"),
    ("Öffnen: Pixelvergleich","oeffnen pixelvergleich"),
    ("  Game   HUD  ","game hud"),
])
def test_normalize_query(source,expected):
    assert normalize_search(source)==expected

def test_ctrl_k_dialog_en_de_navigation_and_reuse(suite_gui,monkeypatch):
    suite,app=suite_gui
    invoked=[]
    monkeypatch.setattr(app,"run",lambda *a,**kw:invoked.append(a))
    targets=build_navigation_targets(app)
    assert len({target.key for target in targets})==len(targets)
    # The integrated HUD Studio is now an additional primary workspace.
    assert sum(target.key.startswith("workspace:") for target in targets)==15
    assert len(targets)>=25
    for search,required in (
        ("zinnenlineal","editor:2"),("Game HUD","sandbox:hud"),
        ("OpenRaster","editor:3"),("Animation","sandbox:animation"),
        ("AtlasBuilder","editor:1"),("Kartenordner","sandbox:folder"),
    ):
        assert required in [x.key for x in find_targets(targets,search)]
    assert not invoked
    assert app.bind_all("<Control-k>")
    assert app.command_search_button.winfo_ismapped()
    app.command_search_button.invoke()
    app.update()
    dlg=app._command_search
    assert dlg.winfo_exists()
    dlg.query.set("zinnenlineal")
    app.update()
    assert dlg.visible
    assert dlg.visible[0].key=="editor:2"
    assert dlg.execute_selected()=="break"
    app.update()
    assert not dlg.winfo_exists()
    assert app.notebook.select()==str(app.exchange_tab)
    assert "Pivot" in app.exchange_tab.section_choice.get()
    assert not invoked

    app.set_language("en")
    app.update()
    assert "Search" in app.command_search_button.cget("text")
    other=app.show_command_search()
    other.query.set("build")
    app.update()
    assert other.visible
    assert other.title()=="Find a workspace or tool"
    # Stable by semantic destination, not a numeric tab index: the HUD-Studio
    # adds an extra workspace before "Build packages".
    assert any(item.key.startswith("workspace:")
               and item.title_en == "Build packages" for item in other.visible)
    app.set_language("de")
    app.update()
    assert other.language=="de"
    assert other.title()=="Bereich oder Werkzeug suchen"
    app.set_language("en")
    app.update()
    assert other.language=="en"
    assert other.title()=="Find a workspace or tool"
    assert app.show_command_search() is other
    other.query.set("nonexistent result xxxxxxxxx")
    app.update()
    assert not other.visible
    assert other.execute_selected()=="break"
    assert other.winfo_exists()
    other.close()
    assert not other.winfo_exists()
    assert not invoked


def test_search_opens_palette_and_inspector_idempotently():
    from types import SimpleNamespace
    from suite_command_search import build_navigation_targets

    class Dock:
        def __init__(self,title): self.title=title
        def windowTitle(self): return self.title

    palette=Dock("Sprite-Palette")
    inspector=Dock("Karten-Inspector")
    exposed=[]
    workspace=SimpleNamespace(_left_docks=[palette],
                              show_tool=lambda dock:exposed.append(dock))
    bridge=SimpleNamespace(workspace=workspace,
                           window=SimpleNamespace(_native_dock=inspector))
    navigated=[]
    sandbox=SimpleNamespace(ensure_studio=lambda:bridge,
                            show_game_map=lambda:None,
                            show_game_hud=lambda:None,show_animation=lambda:None,
                            choose_folder=lambda:None,compare=lambda:None)
    app=SimpleNamespace(
        _navigation_entries=(),
        exchange_tab=SimpleNamespace(section_targets={}),
        sandbox_tab=sandbox,
        diagnose_tab=object(),bc7_page=object(),
        open_tab=lambda tab:navigated.append(tab),
    )
    targets=build_navigation_targets(app)
    palette_action=next(row for row in targets if row.key=="sandbox:palette")
    inspector_action=next(row for row in targets if row.key=="sandbox:inspector")
    palette_action.navigate()
    palette_action.navigate()
    inspector_action.navigate()
    inspector_action.navigate()
    assert exposed==[palette,palette,inspector,inspector]
    assert navigated==[sandbox]*4

def test_game_map_destination_reveals_actual_canvas_not_only_tk_tab():
    from types import SimpleNamespace
    suite=suite_module()
    visited=[]
    fake=SimpleNamespace(
        app=SimpleNamespace(open_tab=lambda tab:visited.append(tab)),
        ensure_studio=lambda:SimpleNamespace(
            window=SimpleNamespace(show_native_map=lambda:visited.append("Qt map"))
        ),
    )
    suite.SandboxTab.show_game_map(fake)
    assert visited==[fake,"Qt map"]

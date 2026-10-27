"""Bilingual UI audit: visible buttons, live controls and Tk popup menus."""
from __future__ import annotations
import importlib.machinery
import importlib.util
from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/"src"),str(ROOT/"tools")]


@pytest.fixture
def bilingual_suite(monkeypatch,tmp_path):
    import stronghold_europe_de.workspace_lock as lock_module
    monkeypatch.setattr(
        lock_module,"lock_path",
        lambda _root,_name:tmp_path/"ui-language-test.lock",
    )
    loader=importlib.machinery.SourceFileLoader(
        "suite_english_ui_audit",str(ROOT/"tools"/"suite_universal.pyw")
    )
    spec=importlib.util.spec_from_loader(loader.name,loader)
    suite=importlib.util.module_from_spec(spec)
    loader.exec_module(suite)
    monkeypatch.setattr(suite,"SETTINGS",tmp_path/"lang-settings.json")
    previous=suite.LANG.code
    suite.LANG.code="de"
    try:
        app=suite.Universal()
    except tk.TclError as exc:
        pytest.skip(str(exc))
    monkeypatch.setattr(app.sandbox_tab,"ensure_studio",lambda:None)
    try:
        yield suite,app
    finally:
        suite.LANG.code=previous
        app.destroy()


def test_english_live_controls_and_menus_are_truly_reversible(bilingual_suite):
    suite,app=bilingual_suite
    app.geometry("1320x800+28+28")
    app.update()
    app.set_language("en")
    app.update()
    assert "The map editor loads in this tab" in app.sandbox_tab.message.get()
    status=app.target_tab.target_status.get()
    assert ("target" in status.lower() or "settings" in status.lower()),status
    assert "Noch kein Zielspiel" not in status
    app.diagnose_tab._diagnostic_status=("missing",None)
    app.diagnose_tab.refresh_status()
    assert "No diagnostic report yet" in app.diagnose_tab.findings_status.get()
    assert app.console_toggle.cget("text")=="Show log"
    assert app.tab_strip_toggle.cget("text")=="All tabs"
    assert app.catalog_tab.details_button.cget("text")=="Preview / edit"
    # Geometry-only tests miss text clipped *inside* its own button.
    # New descriptive pager/reset buttons must fit their translated labels.
    from tkinter import font as tkfont
    app.open_tab(app.catalog_tab)
    app.update()
    font=tkfont.nametofont("TkDefaultFont")
    for expected in ("◀ Previous","Next ▶","Clear"):
        matches=[]
        nodes=[app.catalog_tab]
        while nodes:
            node=nodes.pop()
            nodes.extend(node.winfo_children())
            if isinstance(node,ttk.Button) and node.cget("text")==expected:
                matches.append(node)
        assert len(matches)==1,expected
        assert matches[0].winfo_width()>=font.measure(expected)+8,expected
    assert "More checks" in app.diagnose_tab.check_actions.more_button.cget("text")

    menu=app.target_tab.actions.menu
    assert menu is not None
    assert "Install SE" in menu.entrycget(0,"label")
    assert "Remove mod" in menu.entrycget(2,"label")
    assert "Groups & extensions" in app.catalog_tab.catalog_actions.more_button.cget("text")
    assert app.catalog_tab.catalog_actions.menu.entrycget(0,"label")=="Create category" or (
        "category" in app.catalog_tab.catalog_actions.menu.entrycget(0,"label").lower()
    )

    app.console_toggle.invoke()
    assert app.console_toggle.cget("text")=="Hide log"
    app.console_toggle.invoke()
    assert app.console_toggle.cget("text")=="Show log"
    app.tab_strip_toggle.invoke()
    assert app.tab_strip_toggle.cget("text")=="Group tabs"
    app.tab_strip_toggle.invoke()
    assert app.tab_strip_toggle.cget("text")=="All tabs"
    app.catalog_tab.details_button.invoke()
    assert app.catalog_tab.details_button.cget("text")=="Close preview"
    app.catalog_tab.details_button.invoke()
    assert app.catalog_tab.details_button.cget("text")=="Preview / edit"

    app.set_language("de")
    app.update()
    assert "Beim ersten Öffnen" in app.sandbox_tab.message.get()
    assert "Noch kein Diagnosebericht" in app.diagnose_tab.findings_status.get()
    assert app.console_toggle.cget("text")=="Protokoll anzeigen"
    assert app.tab_strip_toggle.cget("text")=="Alle Reiter"
    assert app.catalog_tab.details_button.cget("text")=="Vorschau / Bearbeiten"
    assert "installieren" in menu.entrycget(0,"label").lower()
    app.set_language("en")
    assert "Install SE" in menu.entrycget(0,"label")


def test_english_shell_translation_catalog_contains_verified_labels():
    import json
    translations=json.loads(
        (ROOT / "config/suite-sprachen.json").read_text(encoding="utf-8")
    )["en"]
    critical=[
        "Bereich öffnen / Go to:","Protokoll anzeigen","Protokoll ausblenden",
        "Reiter bündeln","Alle Reiter","Kartenordner wählen","Animation / Frames",
        "Spiel-HUD","Pivot-Messungen prüfen …","Installation & Sicherungen ▾",
        "Weitere Prüfarten ▾","Profiländerungen ▾","Vorschau / Bearbeiten",
        "Vorschau schließen","Originalgrafik im Katalog","Karte öffnen",
        "Mod installieren ... (mit Sicherung)","Mod entfernen (mit Sicherung)",
    ]
    for german in critical:
        assert german in translations and translations[german].strip(),german
        assert translations[german]!=german,german

"""Main Tk UI: live numerical status text must translate reversibly.

Tests label semantics rather than mutating sprite indices or profile data.
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
from pathlib import Path
import sys
import pytest

try:
    import tkinter as tk
    from tkinter import ttk
except ImportError:
    tk=None

ROOT=Path(__file__).resolve().parents[2]


def load_ui():
    loader=importlib.machinery.SourceFileLoader(
        "suite_dynamic_translation_test",
        str(ROOT/"tools"/"suite_universal.pyw"),
    )
    spec=importlib.util.spec_from_loader(loader.name,loader)
    module=importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_main_suite_reversible_profile_counts_and_real_numbers():
    ui=load_ui()
    language=ui.Language()
    language.code="de"
    original="149 Gruppen im Profil. 76.388 Frames"
    assert language.tr(original)==original
    language.code="en"
    assert language.tr(original)=="149 groups in profile. 76.388 frames"
    assert language.tr("12 Gruppen im Profil. 1.234 Frames")==(
        "12 groups in profile. 1.234 frames"
    )
    language.code="de"
    assert language.tr("12 groups in profile. 1.234 frames")==(
        "12 Gruppen im Profil. 1.234 Frames"
    )


@pytest.mark.skipif(tk is None,reason="No Tk available")
def test_dynamic_profile_label_survives_three_language_switches():
    ui=load_ui()
    language=ui.Language()
    try:
        root=tk.Tk()
    except tk.TclError:
        pytest.skip("Tk desktop unavailable")
    root.withdraw()
    label=ttk.Label(root,text="149 Gruppen im Profil. 76.388 Frames")
    label.pack()
    try:
        language.code="de"
        language.apply(root)
        assert label.cget("text")=="149 Gruppen im Profil. 76.388 Frames"
        language.code="en"
        language.apply(root)
        assert label.cget("text")=="149 groups in profile. 76.388 frames"
        language.code="de"
        language.apply(root)
        assert label.cget("text")=="149 Gruppen im Profil. 76.388 Frames"
        label.configure(text="151 Gruppen im Profil. 76.444 Frames")
        language.code="en"
        language.apply(root)
        assert label.cget("text")=="151 groups in profile. 76.444 frames"
        language.code="de"
        language.apply(root)
        assert label.cget("text")=="151 Gruppen im Profil. 76.444 Frames"
    finally:
        root.destroy()


def test_long_main_workflow_instructions_have_english_versions():
    ui=load_ui()
    tr=ui.Language()
    tr.code="en"
    examples=[
        "Noch kein Diagnosebericht vorhanden. Mit »Alles prüfen« oder einer konkreten Prüfart beginnen. Die Prüfung läuft ohne Spielinstallation.",
        "Noch kein Zielspiel registriert. Mit »Ziel hinzufügen …« einen vorhandenen Crusader-DE-Spielordner auswählen. Es wird dadurch noch nichts installiert.",
        "Sucht arabisches und Kreuzzugs-Vokabular im Spieltext und ersetzt es nach den Regeln in assets/locales/entarabisierung.json. Die Ersetzung achtet auf Wortgrenzen und erhält die Großschreibung.",
    ]
    for german in examples:
        assert tr.tr(german)!=german
    tr.code="de"
    for german in examples:
        assert tr.tr(german)==german


@pytest.mark.skipif(tk is None,reason="No Tk available")
def test_english_cli_help_is_german_in_german_main_suite():
    ui=load_ui()
    lang=ui.Language()
    try:
        root=tk.Tk()
    except tk.TclError:
        pytest.skip("Tk desktop unavailable")
    root.withdraw()
    english="Export game sprites as ordinary PNGs, and bring hand-drawn ones back."
    german=("Spielsprites als normale PNG-Dateien exportieren und "
            "von Hand gezeichnete Bilder zurückholen.")
    label=ttk.Label(root,text=english)
    label.pack()
    try:
        lang.code="de"
        lang.apply(root)
        assert label.cget("text")==german
        lang.code="en"
        lang.apply(root)
        assert label.cget("text")==english
        lang.code="de"
        lang.apply(root)
        assert label.cget("text")==german
    finally:
        root.destroy()

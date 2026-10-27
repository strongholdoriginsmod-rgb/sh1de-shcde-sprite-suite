"""Project-wide release preflight is reachable inside the existing Suite."""
from __future__ import annotations

import importlib.machinery
import importlib.util
from pathlib import Path
import sys
import time
import tkinter as tk
from tkinter import ttk

import pytest

ROOT=Path(__file__).resolve().parents[2]
if str(ROOT/"tools") not in sys.path:
    sys.path.insert(0,str(ROOT/"tools"))


def _suite():
    loader=importlib.machinery.SourceFileLoader(
        "suite_universal_release_preflight_gui_test",
        str(ROOT/"tools"/"suite_universal.pyw"),
    )
    spec=importlib.util.spec_from_loader(loader.name,loader)
    module=importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_release_preflight_button_is_async_and_does_not_install(monkeypatch,tmp_path):
    suite=_suite()
    import stronghold_europe_de.release_preflight as api
    try:
        root=tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"No Tk desktop available: {exc}")
    root.withdraw()
    root.done_hooks=[]
    logs=[]
    opened=[]
    root.log=lambda *args:logs.append(args)
    root.run=lambda *args:pytest.fail("Preflight must not start an installer")
    root.show_in_catalog=lambda *args:opened.append(args)
    root.show_in_sandbox=lambda *args:pytest.fail("Must not open a game scene")

    calls=[]
    fake_report={
        "profile_id":"sprite-suite-world-bc7-v2",
        "summary":{"state":"offline_ok","warnings":0,"errors":0},
        "stats":{"expected_outputs":2,"verified_outputs":2},
        "findings":[
            {"schwere":"info","pruefung":"Release",
             "gruppe":"Datei-Integrität","text":"Zwei SHA-256 bestätigt"},
            {"schwere":"info","pruefung":"Release",
             "gruppe":"Bundle-Gruppen","text":"Eine Gruppe stimmt überein"},
        ],
    }

    def fake_audit(project_root,profile_id,approval_file=None):
        calls.append((project_root,profile_id,approval_file))
        time.sleep(.04)  # Busy thread, not the Tk event loop.
        return fake_report

    def fake_save(report,project_root):
        assert report is fake_report
        path=tmp_path/"fake-release-preflight.json"
        path.write_text("safe report",encoding="utf-8")
        return path

    monkeypatch.setattr(api,"audit_release",fake_audit)
    monkeypatch.setattr(api,"save_preflight",fake_save)
    notebook=ttk.Notebook(root)
    notebook.pack(fill="both",expand=True)
    view=suite.DiagnoseTab(notebook,root)
    notebook.add(view,text="Diagnose & Reparatur")
    try:
        view.release_profile.set("sprite-suite-world-bc7-v2")
        view.inspect_release()
        assert str(view.preflight_button["state"])=="disabled"
        view.inspect_release()
        deadline=time.monotonic()+3
        while view._release_pending is not None and time.monotonic()<deadline:
            root.update()
            time.sleep(.03)
        assert view._release_pending is None
        assert str(view.preflight_button["state"])=="normal"
        assert len(calls)==1
        assert calls[0][1:] == ("sprite-suite-world-bc7-v2",None)
        assert len(view.findings)==2
        assert len(view.table.get_children())==2
        view.table.selection_set("0")
        view.open_in_catalog()
        assert not opened
        assert "Offline-Status" in view.detail.cget("text")
        assert any("2/2 Dateien" in args[0] for args in logs)
        assert (tmp_path/"fake-release-preflight.json").is_file()
        original_language = suite.LANG.code
        try:
            suite.LANG.code = "en"
            view._refresh_release_approval_label()
            assert view.release_approval_label.get() == "Pivot approval: none"
            suite.LANG.code = "de"
            view._refresh_release_approval_label()
            assert view.release_approval_label.get() == "Pivot-Freigabe: keine"
        finally:
            suite.LANG.code = original_language
    finally:
        root.destroy()

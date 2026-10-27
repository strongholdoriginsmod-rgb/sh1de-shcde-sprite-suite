"""Synthetic BC7 V2 rehearsal is integrated without a Unity/game process."""
from __future__ import annotations

import importlib.machinery
import importlib.util
from pathlib import Path
import json
import sys
import time
import tkinter as tk
from tkinter import ttk

import pytest

PROJECT=Path(__file__).resolve().parents[2]


def _suite():
    loader=importlib.machinery.SourceFileLoader(
        "pivot_rehearsal_gui_test",str(PROJECT/"tools"/"suite_universal.pyw")
    )
    spec=importlib.util.spec_from_loader(loader.name,loader)
    module=importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_rehearsal_button_runs_only_background_synthetic_builder_inputs(tmp_path,monkeypatch):
    import stronghold_europe_de.pivot_bc7_rehearsal as rehearsal_api
    suite=_suite()
    try:
        root=tk.Tk()
    except tk.TclError as exc:
        pytest.skip(str(exc))
    root.withdraw()
    root.done_hooks=[]
    logs=[]
    visits=[]
    root.log=lambda *args:logs.append(args)
    root.run=lambda *args:pytest.fail("Must not launch game or Unity subprocess")
    root.show_in_catalog=lambda *args:visits.append(args)
    root.show_in_sandbox=lambda *args:pytest.fail("No game map for synthetic inputs")
    reporter=tmp_path/"synthetic-attestation.json"
    payload={
        "schema":rehearsal_api.SCHEMA,
        "release_allowed":False,"installation_allowed":False,
        "unity_executed":False,"asset_bundle_produced":False,
        "pinned_unity_editor":{
            "required_version":"2021.3.45f2",
            "discovery_status":"exact_editor_missing",
        },
        "tested":{
            "pixel_pages_identical":True,
            "old":{"groups":{
                "anim_castle":{"pivot":[0,1.109090924],"cache_key_projection":"a"*64},
                "anim_drawbridge":{"pivot":[0,1],"cache_key_projection":"c"*64},
            }},
            "proposed":{"groups":{
                "anim_castle":{"pivot":[0,1],"cache_key_projection":"b"*64},
                "anim_drawbridge":{"pivot":[0,1],"cache_key_projection":"c"*64},
            }},
        }
    }
    reporter.write_text(json.dumps(payload),encoding="utf-8")
    calls=[]
    def fake_preparer(root_path):
        calls.append(root_path)
        time.sleep(.04)
        return reporter
    monkeypatch.setattr(rehearsal_api,"prepare_synthetic_pivot_rehearsal",fake_preparer)
    book=ttk.Notebook(root)
    book.pack(fill="both",expand=True)
    diagnose=suite.DiagnoseTab(book,root)
    book.add(diagnose,text="Diagnose")
    try:
        assert str(diagnose.rehearsal_button["state"])=="normal"
        diagnose.run_synthetic_bc7_rehearsal()
        assert str(diagnose.rehearsal_button["state"])=="disabled"
        assert str(diagnose.preflight_button["state"])=="disabled"
        assert str(diagnose.pivot_stage_button["state"])=="disabled"
        diagnose.run_synthetic_bc7_rehearsal()
        deadline=time.monotonic()+3
        while diagnose._rehearsal_pending is not None and time.monotonic()<deadline:
            root.update()
            time.sleep(.02)
        assert diagnose._rehearsal_pending is None
        assert len(calls)==1 and calls[0]==suite.ROOT
        assert str(diagnose.rehearsal_button["state"])=="normal"
        assert str(diagnose.preflight_button["state"])=="normal"
        assert str(diagnose.pivot_stage_button["state"])=="normal"
        assert len(diagnose.findings)==2
        assert diagnose.findings[0]["pruefung"]=="BC7-Probe"
        assert diagnose.findings[0]["schwere"]=="info"
        assert diagnose.findings[1]["gruppe"]=="Unity-Editor"
        assert len(diagnose.table.get_children())==2
        diagnose.table.selection_set("0")
        diagnose.open_in_catalog()
        assert not visits
        assert "kein" in diagnose.detail.cget("text").lower()
        assert any("kein Bundle oder Spiel geändert" in log[0] for log in logs)
        assert not (tmp_path/"dist").exists()
    finally:
        root.destroy()

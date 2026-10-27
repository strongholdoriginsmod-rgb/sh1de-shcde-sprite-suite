"""Native frozen pivot proof accessible from the existing Diagnose tab."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
from pathlib import Path
import sys
import time
import tkinter as tk
from tkinter import ttk

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"tools"))


def _suite():
    loader=importlib.machinery.SourceFileLoader(
        "native_pivot_proof_gui_test",
        str(ROOT/"tools"/"suite_universal.pyw"),
    )
    spec=importlib.util.spec_from_loader(loader.name,loader)
    suite=importlib.util.module_from_spec(spec)
    loader.exec_module(suite)
    return suite


def test_read_only_native_proof_integrated_and_non_blocking(tmp_path,monkeypatch):
    import stronghold_europe_de.pivot_native_provenance as native
    suite=_suite()
    try:
        root=tk.Tk()
    except tk.TclError as exc:
        pytest.skip(str(exc))
    root.withdraw()
    root.done_hooks=[]
    logs=[]
    visited=[]
    root.log=lambda *args:logs.append(args)
    root.run=lambda *args:pytest.fail("Native proof must never run installer or game")
    root.show_in_catalog=lambda *args:visited.append(args)
    root.show_in_sandbox=lambda *args:pytest.fail("Native proof not a game action")
    report_path=tmp_path/"test-native-geometry.json"
    sample={
        "schema":native.SCHEMA,"group_proof":{
            "group":"anim_castle","total_frames":106,
            "native_source_frames":95,"target_keep_frames":11,
            "native_proof":{
                "geometry_proof_sha256":"f"*64,
                "source_rgba_sha256":"c"*64,
                "runtime_anchor_max_error_px":0.0000037,
            },
            "review_partition":{"provenance_sha256":"d"*64},
            "frames":[
                {
                    "name": f"anim_castle {i:03d}",
                    "action":("REVIEW_MANUAL" if i<=95 else "KEEP_CRUSADER"),
                    "origin":("SOURCE_SH1DE" if i<=95 else "TARGET_SHCDE"),
                    "pivot":[0.0,1.0],
                    "geometry":[333,165] if i<=95 else [60,114],
                    "source_path_id":12414 if i<=95 else None,
                    "target_path_id":86476,
                }
                for i in range(1,107)
            ],
        },
    }
    calls=[]
    def fake_audit(root_path,profile,group):
        calls.append((root_path,profile,group))
        time.sleep(.04)
        return sample
    def fake_save(result,root_path):
        assert result is sample
        report_path.write_text(json.dumps(sample),encoding="utf-8")
        return report_path
    monkeypatch.setattr(native,"audit_native_geometry",fake_audit)
    monkeypatch.setattr(native,"save_native_geometry_audit",fake_save)
    book=ttk.Notebook(root)
    book.pack(fill="both",expand=True)
    tab=suite.DiagnoseTab(book,root)
    book.add(tab,text="Diagnose & Reparatur")
    try:
        assert str(tab.native_button["state"])=="normal"
        tab.release_profile.set("sprite-suite-world-bc7-v2")
        tab.inspect_native_geometry()
        assert str(tab.native_button["state"])=="disabled"
        assert str(tab.rehearsal_button["state"])=="disabled"
        assert str(tab.pivot_stage_button["state"])=="disabled"
        assert str(tab.preflight_button["state"])=="disabled"
        tab.inspect_native_geometry()
        deadline=time.monotonic()+3
        while tab._native_pending is not None and time.monotonic()<deadline:
            root.update()
            time.sleep(.02)
        assert tab._native_pending is None
        assert str(tab.native_button["state"])=="normal"
        assert str(tab.preflight_button["state"])=="normal"
        assert len(calls)==1 and calls[0]==(
            suite.ROOT,"sprite-suite-world-bc7-v2","anim_castle"
        )
        assert len(tab.findings)==110
        assert {item["pruefung"] for item in tab.findings}=={
            "Nativ-Proof","Nativ-Frame"
        }
        assert tab.findings[0]["schwere"]=="info"
        assert tab.findings[3]["schwere"]=="warnung"
        assert len(tab.table.get_children())==110
        tab.table.selection_set("0")
        tab.open_in_catalog()
        assert not visited
        tab.table.selection_set("4")
        tab.open_in_catalog()
        assert visited==[("anim_castle","anim_castle 001")]
        # A forged native proof row is never a path/execution action.
        tab.findings[4]["frames"]=["../unauthorized"]
        tab.open_in_catalog()
        assert len(visited)==1
        assert "Kein erneuter Unity-Encoderlauf" in tab.detail.cget("text")
        assert report_path.is_file()
        assert any("95 SH1DE + 11 Crusader" in x[0] for x in logs)
    finally:
        root.destroy()

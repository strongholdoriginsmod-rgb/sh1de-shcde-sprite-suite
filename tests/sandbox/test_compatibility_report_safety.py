"""Regression gates for honest compatibility reports and no-clobber exports."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import json
import sys
import tkinter as tk

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/"tools"),str(ROOT/"src")]
import suite_compatibility_preflight as preflight
import suite_compatibility_window as window


def _fake_dialog(report):
    return SimpleNamespace(report=report,
           _label=lambda german, english:german)


def test_diagnostic_save_never_replaces_an_existing_user_file(
    tmp_path,monkeypatch,
):
    """The save-file picker is not permission to silently clobber a file."""
    target=tmp_path/"user-report.json"
    target.write_bytes(b"precious user report")
    errors=[]
    monkeypatch.setattr(window.filedialog,"asksaveasfilename",
                        lambda **_kw:str(target))
    monkeypatch.setattr(window.messagebox,"showerror",
                        lambda *a,**kw:errors.append((a,kw)))
    fake=_fake_dialog({"schema":"sprite-suite.compatibility-readonly.v1",
                       "writes_to_game":False,"checks":[]})
    window.CompatibilityWindow.save_report(fake)
    assert target.read_bytes()==b"precious user report"
    assert errors


def test_diagnostic_save_creates_new_exclusive_json_file(
    tmp_path,monkeypatch,
):
    target=tmp_path/"read-only-status.json"
    assert not target.exists()
    errors=[]
    monkeypatch.setattr(window.filedialog,"asksaveasfilename",
                        lambda **_kw:str(target))
    monkeypatch.setattr(window.messagebox,"showerror",
                        lambda *a,**kw:errors.append((a,kw)))
    report={"schema":"sprite-suite.compatibility-readonly.v1",
            "native_game_approved":False,"writes_to_game":False,"checks":[]}
    window.CompatibilityWindow.save_report(_fake_dialog(report))
    assert json.loads(target.read_text(encoding="utf-8"))==report
    assert not errors


@pytest.mark.parametrize("sentinel",[
    "tcl8.6/init.tcl",
    "tk8.6/tk.tcl",
    "tk8.6/ttk/ttk.tcl",
    "tk8.6/ttk/panedwindow.tcl",
])
def test_incomplete_bundled_tcl_never_reports_ready(
    tmp_path,monkeypatch,sentinel,
):
    """All four bootstrap scripts matter; a broken 8.6 copy is not Ready."""
    monkeypatch.setattr(tk,"TclVersion",8.6)
    monkeypatch.setattr(tk,"TkVersion",8.6)
    root=tmp_path/"suite"
    runtime=root/"python"/"tcl"
    from suite_tcl_runtime import SENTINELS
    for name in SENTINELS:
        path=runtime/name
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text("script fixture",encoding="utf8")
    (runtime/sentinel).unlink()
    result=preflight._tcl(root)
    assert result["name"]=="Tcl/Tk"
    assert result["status"]=="limited"
    assert "Tcl" in result["detail"] or "Tk" in result["detail"]


def test_complete_bundled_tcl_scripts_can_be_reported_ready(
    tmp_path,monkeypatch,
):
    monkeypatch.setattr(tk,"TclVersion",8.6)
    monkeypatch.setattr(tk,"TkVersion",8.6)
    runtime=tmp_path/"suite"/"python"/"tcl"
    from suite_tcl_runtime import SENTINELS
    for name in SENTINELS:
        path=runtime/name
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text("script fixture",encoding="utf8")
    result=preflight._tcl(tmp_path/"suite")
    assert result["status"]=="ready"
    assert "Bundled" in result["detail"]

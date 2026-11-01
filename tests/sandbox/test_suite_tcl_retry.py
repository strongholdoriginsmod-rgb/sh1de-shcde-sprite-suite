"""Deterministic fault injection into the actual full SpriteSuite root startup."""
from __future__ import annotations

import importlib.machinery
import importlib.util
from pathlib import Path
import sys
import tkinter as tk

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/"tools"),str(ROOT/"src")]


def _module(tmp_path,monkeypatch):
    import stronghold_europe_de.workspace_lock as locks
    monkeypatch.setattr(locks,"lock_path",
                        lambda _r,_name:tmp_path/"retry-qa-instance.lock")
    loader=importlib.machinery.SourceFileLoader(
        "suite_tcl_retry_diagnostics",str(ROOT/"tools"/"suite_universal.pyw"))
    spec=importlib.util.spec_from_loader(loader.name,loader)
    target=importlib.util.module_from_spec(spec)
    loader.exec_module(target)
    monkeypatch.setattr(target,"SETTINGS",tmp_path/"settings.json")
    return target


def test_full_suite_root_retries_only_unreadable_tcl_init(tmp_path,monkeypatch):
    imported=_module(tmp_path,monkeypatch)
    original=tk.Tk.__init__
    attempts={"value":0}
    def injected(self,*args,**kwargs):
        attempts["value"]+=1
        if attempts["value"]<3:
            raise tk.TclError(
                "Can't find a usable init.tcl in the following directories: C:/mock")
        return original(self,*args,**kwargs)
    monkeypatch.setattr(tk.Tk,"__init__",injected)
    gui=None
    try:
        gui=imported.Universal()
        gui.update_idletasks()
        assert gui.winfo_exists()
        assert attempts["value"]==3
    finally:
        if gui is not None:gui.destroy()


def test_full_suite_root_does_not_retry_unrelated_tcl_errors(tmp_path,monkeypatch):
    imported=_module(tmp_path,monkeypatch)
    attempts={"value":0}
    def injected(self,*args,**kwargs):
        attempts["value"]+=1
        raise tk.TclError("Invalid Tk class in unrelated component")
    monkeypatch.setattr(tk.Tk,"__init__",injected)
    with pytest.raises(tk.TclError,match="unrelated"):
        imported.Universal()
    assert attempts["value"]==1

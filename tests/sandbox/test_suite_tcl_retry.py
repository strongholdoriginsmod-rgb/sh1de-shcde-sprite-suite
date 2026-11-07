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
        assert 3<=attempts["value"]<=5
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



@pytest.mark.parametrize("script", ["tcl8.6/init.tcl", "tcl8.6/auto.tcl", "tk8.6/tk.tcl"])
def test_standalone_tk_root_factory_retries_transient_script_reads(monkeypatch, script):
    from suite_tcl_runtime import create_tk_root
    original=tk.Tk.__init__
    seen={"count":0}
    def interrupted(self,*args,**kwargs):
        seen["count"]+=1
        if seen["count"]<=2:
            raise tk.TclError(f'couldn\'t read file "C:/private/{script}": no such file or directory')
        return original(self,*args,**kwargs)
    monkeypatch.setattr(tk.Tk,"__init__",interrupted)
    result=create_tk_root()
    try:
        assert result.winfo_exists()
        assert 3<=seen["count"]<=5
    finally:
        result.destroy()


def test_standalone_tk_root_does_not_hide_bad_configuration(monkeypatch):
    from suite_tcl_runtime import create_tk_root
    seen={"count":0}
    def invalid(self,*_args,**_kwargs):
        seen["count"]+=1
        raise tk.TclError("Unknown Tk display or invalid argument")
    monkeypatch.setattr(tk.Tk,"__init__",invalid)
    with pytest.raises(tk.TclError,match="invalid argument"):
        create_tk_root()
    assert seen["count"]==1



def test_full_suite_root_recovers_from_tcl_findlibrary_bootstrap_failure(
    tmp_path,monkeypatch,
):
    imported=_module(tmp_path,monkeypatch)
    original=tk.Tk.__init__
    attempts={"count":0}
    def fail_first(self,*a,**kw):
        attempts["count"]+=1
        if attempts["count"]==1:
            raise tk.TclError('invalid command name "tcl_findLibrary"')
        return original(self,*a,**kw)
    monkeypatch.setattr(tk.Tk,"__init__",fail_first)
    ui=None
    try:
        ui=imported.Universal()
        assert ui.winfo_exists()
        assert 2<=attempts["count"]<=5
    finally:
        if ui is not None:ui.destroy()


def test_standalone_factory_recovers_findlibrary_but_not_unrelated_commands(
    monkeypatch,
):
    from suite_tcl_runtime import create_tk_root
    original=tk.Tk.__init__
    attempts={"count":0}
    def fail_first(self,*a,**kw):
        attempts["count"]+=1
        if attempts["count"]==1:
            raise tk.TclError('invalid command name "tcl_findLibrary"')
        return original(self,*a,**kw)
    monkeypatch.setattr(tk.Tk,"__init__",fail_first)
    ui=create_tk_root()
    try:
        assert ui.winfo_exists()
        assert 2<=attempts["count"]<=5
    finally:ui.destroy()


def test_unrelated_tcl_invalid_command_still_not_retried(monkeypatch):
    from suite_tcl_runtime import create_tk_root
    tries={"count":0}
    def unrelated(self,*a,**kw):
        tries["count"]+=1
        raise tk.TclError('invalid command name "user_modified_widget"')
    monkeypatch.setattr(tk.Tk,"__init__",unrelated)
    with pytest.raises(tk.TclError,match="user_modified_widget"):
        create_tk_root()
    assert tries["count"]==1

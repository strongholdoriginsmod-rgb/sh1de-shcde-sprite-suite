"""Sprite Suite's two new tools are genuinely accessible from the Tk UI."""
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk

import pytest
from PIL import Image

PROJECT=Path(__file__).resolve().parents[2]
TOOLS=str(PROJECT/"tools")
if TOOLS not in sys.path:
    sys.path.insert(0,TOOLS)


def _suite():
    loader=importlib.machinery.SourceFileLoader(
        "sprite_suite_pivot_tools_integration",str(PROJECT/"tools"/"suite_universal.pyw")
    )
    spec=importlib.util.spec_from_loader(loader.name,loader)
    module=importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_tools_open_from_existing_editor_and_diagnose_tabs(monkeypatch,tmp_path):
    suite=_suite()
    try:
        root=tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"No Tk window system available: {exc}")
    root.title("QA Pivot und Altwerkzeuge")
    root.geometry("1250x950")
    root.done_hooks=[]
    messages=[]
    root.log=lambda msg,tag=None:messages.append(msg)
    selected=[]
    root.show_in_catalog=lambda group,name:selected.append((group,name))
    root.show_in_sandbox=lambda group,num:selected.append((group,num))
    root.run=lambda *args:pytest.fail("QA tool must not run old CLI scripts")
    tabs=ttk.Notebook(root)
    tabs.pack(fill="both",expand=True)
    app=suite.ExchangeTab(tabs,root)
    tabs.add(app,text="Editor & Austausch")
    diagnose=suite.DiagnoseTab(tabs,root)
    tabs.add(diagnose,text="Diagnose & Reparatur")

    old=tmp_path/"QA Altprojekt"
    (old/"tools").mkdir(parents=True)
    (old/"tests").mkdir()
    (old/"tools"/"ram_acceptance.py").write_text("OLD",encoding="utf-8")
    (old/"tools"/"runtime_install.py").write_text("DANGEROUS",encoding="utf-8")
    monkeypatch.setattr(suite.filedialog,"askdirectory",lambda **kwargs:str(old))

    report_dir=tmp_path/"Zinnenlineal"
    report_dir.mkdir()
    frame={
        "name":"anim_castle 002","gruppe":"anim_castle","nummer":2,
        "rechts":0,"hoch":18,"breite":333,"hoehe":165,
        "pivot_x":0,"pivot_y":1.10909091,
        "neu_pivot_x":0,"neu_pivot_y":1.0,
    }
    path=report_dir/"zinnen-versatz.json"
    path.write_text(json.dumps({"schema":"zinnenlineal.versatz.v1","frames":[frame]}),
                    encoding="utf-8")
    try:
        pivot=app.open_pivot_review()
        assert app.open_pivot_review() is pivot
        assert pivot.load(path)
        assert pivot.current() is not None
        pivot.show_in_catalog()
        pivot.show_in_sandbox()
        assert selected==[("anim_castle","anim_castle 002"),("anim_castle",2)]
        diagnose.inventory_qa()
        assert diagnose.findings
        assert any(item["gruppe"]=="runtime_install.py"
                   for item in diagnose.findings)
        chosen=next(i for i,v in enumerate(diagnose.findings)
                    if v["gruppe"]=="runtime_install.py")
        diagnose.table.selection_set(str(chosen))
        diagnose.open_in_catalog()
        assert len(selected)==2  # never treats script names as sprite groups
        assert any("QA-Altbestand" in msg for msg in messages)
    finally:
        root.destroy()

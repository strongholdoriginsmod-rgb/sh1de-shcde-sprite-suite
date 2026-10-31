"""Every dynamic tool must display its side-effect risk before executing."""
from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path
import importlib.machinery
import importlib.util
import sys

from suite_tool_policy import classify,explain


def test_unknown_tool_fails_closed_to_unclassified_not_read_only():
    assert classify("unreviewed_tool.py",[]).category=="unknown"
    assert "nicht klassifiziert" in explain("unreviewed_tool.py",[])


def test_risk_classification_for_known_important_paths():
    assert classify("ziel_se211.py",["installieren"]).category=="game"
    assert classify("ziel_se211.py",["zurueckspielen"]).category=="game"
    assert classify("project_inputs.py",["install"]).category=="read"
    assert classify("project_inputs.py",["install","--write"]).category=="workspace"
    assert classify("ui_atlas_layout_port.py",[]).category=="workspace"
    assert classify("origins_grafikdaten.py",[]).category=="external"
    assert classify("Pipeline",["install"]).category=="game"
    assert classify("Pipeline",["doctor"]).category=="read"
    assert classify("unknown.py",["--help"]).category=="read"


def test_dynamic_gui_catalogue_requires_risk_confirmation(monkeypatch):
    from pathlib import Path
    root=Path(__file__).resolve().parents[2]
    loader=importlib.machinery.SourceFileLoader(
        "suite_center_risk_test",str(root/"tools"/"suite_center.pyw"))
    spec=importlib.util.spec_from_loader(loader.name,loader)
    module=importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    shown=[]
    launched=[]
    monkeypatch.setattr(module.messagebox,"askyesno",
                        lambda title,body,**kwargs:shown.append(body) or False)
    fake=SimpleNamespace(
        catalog_tool=SimpleNamespace(get=lambda:"ziel_se211.py"),
        active_command=("installieren",),
        active_fields=[],
        field_values=[],
        extra=SimpleNamespace(get=lambda:""),
        run_catalog=lambda args:launched.append(args)
    )
    module.Center.catalog_run(fake)
    assert len(shown)==1
    assert "Spiel" in shown[0]
    assert not launched
    monkeypatch.setattr(module.messagebox,"askyesno",
                        lambda title,body,**kwargs:True)
    module.Center.catalog_run(fake)
    assert launched

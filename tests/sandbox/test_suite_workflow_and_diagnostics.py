"""Explicit project progress and privacy-safe local diagnostics."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"tools"))
from suite_workflow_status import milestones,milestone_text
from suite_diagnostics import save_diagnostic,read_only_summary


def test_presence_does_not_claim_a_validated_package_or_ingame_approval(tmp_path):
    root=tmp_path/"isolated suite"
    (root/"dist"/"europe-production").mkdir(parents=True)
    (root/"work"/"hud-menu-werkstatt").mkdir(parents=True)
    steps=milestones(root)
    assert len(steps)==5
    by_name={name:state for name,state,_ in steps}
    assert by_name["Arbeitsprojekt"]=="vorhanden"
    assert by_name["Modpaket"]=="nicht validiert"
    assert by_name["QA-Spielkopie"]=="nicht nachgewiesen"
    assert by_name["Ingame"]=="nicht abgenommen"
    assert "Ingame: nicht abgenommen" in milestone_text(root)


def test_empty_project_never_invents_a_success(tmp_path):
    by_name={name:state for name,state,_ in milestones(tmp_path)}
    assert by_name["Arbeitsprojekt"]=="offen"
    assert by_name["Modpaket"]=="offen"
    assert all(state!="freigegeben" for state in by_name.values())


def test_diagnostic_excludes_private_config_paths_and_is_explicit(tmp_path):
    root=tmp_path/"private-user-directory"
    (root/"config").mkdir(parents=True)
    (root/"work").mkdir()
    (root/"VERSION").write_text("2.0.0\n",encoding="utf8")
    secret=r"C:\Users\PrivatePerson\Games\SomeSecretPath"
    (root/"config"/"installations.local.toml").write_text(
        f'[target]\ngame_dir="{secret}"\n',encoding="utf8")
    info=read_only_summary(root)
    assert info["configuration"]["game_paths_configured"] is True
    folder=tmp_path/"export"
    folder.mkdir()
    out=folder/"support.json"
    assert not out.exists()
    saved=save_diagnostic(root,out)
    assert out.exists()
    raw=out.read_text("utf8")
    assert secret not in raw
    assert str(root) not in raw
    assert "PrivatePerson" not in raw
    assert saved["provenance"]["in_game_approval"]=="not-proven-by-diagnostic"
    assert json.loads(raw)["application_version"]=="2.0.0"
    with pytest.raises(FileExistsError):
        save_diagnostic(root,out)
    assert json.loads(out.read_text("utf8"))==json.loads(raw)


def test_diagnostic_rejects_linked_output_and_non_json(tmp_path):
    root=tmp_path/"safe"
    root.mkdir()
    with pytest.raises(ValueError):
        save_diagnostic(root,tmp_path/"bad.zip")
    link=tmp_path/"link.json"
    existing=tmp_path/"target.json"
    existing.write_bytes(b"original")
    try:
        link.symlink_to(existing)
    except (OSError,NotImplementedError):
        return
    with pytest.raises(ValueError):
        save_diagnostic(root,link)
    assert existing.read_bytes()==b"original"


def test_gui_diagnostics_requires_choose_destination(tmp_path,monkeypatch):
    loader=importlib.machinery.SourceFileLoader(
        "suite_diagnostics_gui_test",str(ROOT/"tools"/"suite.pyw"))
    spec=importlib.util.spec_from_loader(loader.name,loader)
    suite=importlib.util.module_from_spec(spec)
    loader.exec_module(suite)
    monkeypatch.setattr(suite,"PROJECT_ROOT",tmp_path)
    target=tmp_path/"checked-diagnostic.json"
    chosen=[]
    monkeypatch.setattr(suite.filedialog,"asksaveasfilename",
                        lambda **kw:chosen.append(kw) or str(target))
    success=[]
    monkeypatch.setattr(suite.messagebox,"showinfo",
                        lambda *a,**kw:success.append(a))
    monkeypatch.setattr(suite.messagebox,"showerror",
                        lambda *a,**kw:pytest.fail("No error expected"))
    suite.HomeTab.export_diagnostics(object())
    assert target.is_file()
    assert chosen and success
    assert json.loads(target.read_text("utf8"))["schema"].startswith("spritesuite.")

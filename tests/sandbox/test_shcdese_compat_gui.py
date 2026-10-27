"""GUI contract: the SE 2.14.3 check only starts the read-only checker."""
from __future__ import annotations

import importlib.machinery
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT=Path(__file__).resolve().parents[2]


def _gui():
    file=ROOT/"tools"/"suite_universal.pyw"
    loader=importlib.machinery.SourceFileLoader("se2143_suite_gui_test",str(file))
    spec=importlib.util.spec_from_loader(loader.name,loader)
    module=importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.mark.parametrize("valid",[True,False])
def test_se_2143_gui_uses_read_only_checker_and_never_installs(tmp_path,monkeypatch,valid):
    gui=_gui()
    game=tmp_path/"game"
    game.mkdir()
    if valid:
        (game/"Stronghold Crusader Definitive Edition_Data").mkdir()
    warnings=[]
    started=[]
    monkeypatch.setattr(gui.filedialog,"askdirectory",lambda **kw:str(game))
    monkeypatch.setattr(
        gui.messagebox,"showwarning",
        lambda *args,**kw:warnings.append((args,kw)),
    )
    fake=SimpleNamespace(
        table=SimpleNamespace(selection=lambda:()),
        app=SimpleNamespace(run=lambda args,label:started.append((args,label))),
    )
    before={p.relative_to(game):p.read_bytes()
            for p in game.rglob("*") if p.is_file()}
    gui.TargetTab.check_se(fake)
    after={p.relative_to(game):p.read_bytes()
           for p in game.rglob("*") if p.is_file()}
    assert before==after
    if valid:
        assert not warnings and len(started)==1
        args,label=started[0]
        assert Path(args[0]).name=="shcdese_compat_check.py"
        assert args[1:]==["--game",str(game)]
        assert "2.14.3" in label and "pr" in label.casefold()
    else:
        assert not started and len(warnings)==1

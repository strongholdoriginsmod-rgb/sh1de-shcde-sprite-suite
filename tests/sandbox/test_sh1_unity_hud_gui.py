"""Tk smoke test for guarded offline Unity candidate button; no real assets."""
from __future__ import annotations

import sys
import runpy
from pathlib import Path
from types import SimpleNamespace

import pytest

tk = pytest.importorskip("tkinter", reason="Tk user interface not installed")

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "src")]


@pytest.fixture
def gui(monkeypatch, tmp_path):
    import tkinter.messagebox as messages
    import tkinter.filedialog as dialogs

    try:
        window = tk.Tk()
        window.withdraw()
    except tk.TclError as exc:
        pytest.skip(f"Tk display unavailable: {exc}")
    namespace = runpy.run_path(str(ROOT / "tools" / "suite.pyw"),
                               run_name="sh1_unity_candidate_gui_test")
    methods = namespace["UiTab"]
    calls = []

    def run(args, label):
        calls.append((args, label))
        return True

    app = SimpleNamespace(run=run)
    tab = methods(window, app)
    monkeypatch.setitem(methods.sh1_hud_unity_candidate.__globals__,
                        "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(dialogs, "askopenfilename",
                        lambda *args, **kw: "X:/own-install/globalgamemanagers.assets")
    monkeypatch.setattr(messages, "askyesno", lambda *args, **kw: True)
    warnings = []
    monkeypatch.setattr(messages, "showwarning",
                        lambda *args, **kw: warnings.append((args, kw)))
    yield tab, calls, warnings
    tab.destroy()
    window.destroy()


def test_unity_copy_action_requires_sh1_workspace(gui):
    tab, calls, warnings = gui
    tab._sh1_mode = False
    tab.sh1_hud_unity_candidate()
    assert not calls
    assert warnings


def test_unity_copy_action_only_builds_isolated_candidate(gui):
    tab, calls, warnings = gui
    tab._sh1_mode = True
    tab.folder.delete(0, "end")
    tab.folder.insert(0, "work/sh1-hud-editierbar")
    tab.sh1_hud_unity_candidate()
    assert len(calls) == 1
    args, label = calls[0]
    assert args[0] == str(ROOT / "tools" / "ui_sh1_unity_patch.py")
    assert args[1:3] == ["--source", "X:/own-install/globalgamemanagers.assets"]
    assert args[3] == "--from"
    assert args[5] == "--out"
    assert Path(args[6]).parent == tab._folder_path().parents[1] / "dist"
    assert "--replace" not in args
    assert not warnings


def test_unity_copy_rejects_other_asset(gui, monkeypatch):
    import tkinter.filedialog as dialogs
    tab, calls, warnings = gui
    tab._sh1_mode = True
    monkeypatch.setattr(dialogs, "askopenfilename", lambda *a, **kw: "X:/other_file.dll")
    tab.sh1_hud_unity_candidate()
    assert not calls
    assert warnings

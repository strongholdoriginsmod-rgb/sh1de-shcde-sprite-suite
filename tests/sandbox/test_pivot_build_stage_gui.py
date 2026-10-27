"""The pinned Pivot/BC7 intent appears inside existing diagnostics."""
from __future__ import annotations

import importlib.machinery
import importlib.util
from pathlib import Path
import sys
import time
import tkinter as tk
from tkinter import messagebox, ttk

import pytest

PROJECT = Path(__file__).resolve().parents[2]
if str(PROJECT / "tools") not in sys.path:
    sys.path.insert(0, str(PROJECT / "tools"))


def _suite():
    loader = importlib.machinery.SourceFileLoader(
        "suite_pivot_bc7_stage_gui_test", str(PROJECT / "tools" / "suite_universal.pyw")
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_gui_never_applies_pivots_and_stages_asynchronously(tmp_path, monkeypatch):
    suite = _suite()
    import stronghold_europe_de.pivot_build_stage as api
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(str(exc))
    root.withdraw()
    root.done_hooks = []
    logs = []
    selected = []
    root.log = lambda *args: logs.append(args)
    root.run = lambda *args: pytest.fail("Staging must not run an installer/atlas tool")
    root.show_in_catalog = lambda *args: selected.append(args)
    root.show_in_sandbox = lambda *args: pytest.fail("Staging must not launch sandbox")

    stage = {
        "schema": api.SCHEMA, "profile_id": "sprite-suite-world-bc7-v2",
        "state": "requires_separate_bc7_rebuild",
        "change_count": 1,
        "changes": [{
            "name": "anim_castle 003", "group": "anim_castle",
            "old_pivot": [0.0, 1.10909091], "proposed_pivot": [0.0, 1.0],
        }],
    }
    calls = []
    def fake_prepare(root_path, profile, approval, measured):
        calls.append((root_path, profile, approval, measured))
        time.sleep(.04)
        return stage

    def fake_save(plan, root_path):
        assert plan is stage
        result = tmp_path / "preview-only.json"
        result.write_text("read-only-stage-fixture", encoding="utf-8")
        return result

    monkeypatch.setattr(api, "prepare_pivot_build_stage", fake_prepare)
    monkeypatch.setattr(api, "save_pivot_build_stage", fake_save)
    messages = []
    monkeypatch.setattr(messagebox, "showinfo", lambda *a, **kw: messages.append(a))
    monkeypatch.setattr(
        suite.filedialog, "askopenfilename", lambda **kw: str(tmp_path / "Zinnenlineal.json")
    )
    book = ttk.Notebook(root)
    book.pack(fill="both", expand=True)
    view = suite.DiagnoseTab(book, root)
    book.add(view, text="Diagnose & Reparatur")
    try:
        view.release_profile.set("sprite-suite-world-bc7-v2")
        view.prepare_pivot_stage()
        assert messages  # explicit approval required before even selecting a measurement
        assert view._stage_pending is None
        view.release_approval.set(str(tmp_path / "explicit-approval.json"))
        view.prepare_pivot_stage()
        assert str(view.pivot_stage_button["state"]) == "disabled"
        assert str(view.preflight_button["state"]) == "disabled"
        view.prepare_pivot_stage()  # no second thread started
        deadline = time.monotonic() + 3
        while view._stage_pending is not None and time.monotonic() < deadline:
            root.update()
            time.sleep(.025)
        assert view._stage_pending is None
        assert str(view.pivot_stage_button["state"]) == "normal"
        assert str(view.preflight_button["state"]) == "normal"
        assert len(calls) == 1
        assert calls[0][1] == "sprite-suite-world-bc7-v2"
        assert calls[0][2] == str(tmp_path / "explicit-approval.json")
        assert calls[0][3] == str(tmp_path / "Zinnenlineal.json")
        assert len(view.findings) == 2
        assert all(row["pruefung"] == "Pivot-Stufe" for row in view.findings)
        view.table.selection_set("1")
        view.open_in_catalog()
        assert not selected
        assert "keine Atlas- oder Spieländerung" in view.detail.cget("text")
        assert (tmp_path / "preview-only.json").is_file()
        assert any("Nicht anwendbar" in logged[0] for logged in logs)
    finally:
        root.destroy()

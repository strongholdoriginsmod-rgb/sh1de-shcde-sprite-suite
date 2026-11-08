"""Tk user-flow smoke tests (one reusable interpreter, no game installation)."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from stronghold_europe_de.modding_studio.gui import StudioWindow
from stronghold_europe_de.modding_studio.model import load_project, new_project


@pytest.fixture(scope="module")
def tk_runtime():
    """Avoid tearing down Tcl's global libraries between GUI test cases."""
    try:
        from suite_tcl_runtime import create_tk_root
        root = create_tk_root()
        root.withdraw()
    except tk.TclError as exc:
        pytest.skip("native Tk is unavailable: " + str(exc)[:240])
    try:
        yield root
    finally:
        root.destroy()


@pytest.fixture()
def gui_root(tk_runtime):
    child = tk.Toplevel(tk_runtime)
    try:
        yield child
    finally:
        if child.winfo_exists():
            child.destroy()


def test_gui_load_module_switch_check_and_revision(tmp_path: Path, gui_root):
    directory = tmp_path / "gui_project"
    source = new_project(directory, "gui_studio", "GUI Project")
    studio = StudioWindow(gui_root, directory)
    assert studio.current_module == "sdk"
    editor = studio.editor
    content = json.loads(editor.get("1.0", tk.END))
    assert content == {"requires": []}
    content["requires"] = ["hud_extras"]
    editor.delete("1.0", tk.END)
    editor.insert("1.0", json.dumps(content))
    assert studio._collect_module()
    studio.run_check()
    assert "REVIEW" in studio.status.get()
    studio.save_revision()
    assert studio.project["revision"] == 2
    assert studio.source_path.startswith("revisions/")
    assert load_project(directory)[0]["revision"] == 1
    assert source.is_file()


def test_gui_opens_sdk_catalog_without_modifying_game(tmp_path: Path, gui_root):
    directory = tmp_path / "gui_project"
    new_project(directory, "gui_studio", "GUI Project")
    studio = StudioWindow(gui_root, directory)
    studio.open_sdk()
    gui_root.update_idletasks()
    assert any(
        isinstance(child, tk.Toplevel)
        for child in gui_root.winfo_children()
    )
    assert studio.project is not None


def test_gui_castle_and_route_canvas_previews(tmp_path: Path, gui_root):
    def descendants(widget):
        for child in widget.winfo_children():
            yield child
            yield from descendants(child)
    directory = tmp_path / "preview_project"
    new_project(directory, "visual_studio", "Canvas Preview")
    studio = StudioWindow(gui_root, directory)
    for index in (2, 7):
        studio._changing = True
        studio.module_list.selection_clear(0, tk.END)
        studio.module_list.selection_set(index)
        studio._changing = False
        studio._on_module_select(None)
        studio.preview()
        gui_root.update_idletasks()
        canvases = [
            child for top in gui_root.winfo_children()
            if isinstance(top, tk.Toplevel)
            for child in descendants(top)
            if isinstance(child, tk.Canvas) and len(child.find_all()) > 1
        ]
        assert canvases, "preview does not contain a drawing canvas"
    assert studio.source_path == "project.json"
    assert load_project(directory)[0]["revision"] == 1


def test_embedded_studio_preserves_parent_theme_and_styles(gui_root):
    style = ttk.Style(gui_root)
    theme = style.theme_use()
    names = (".", "Heading.TLabel", "Vertical.TScrollbar", "TFrame", "TLabel")
    original = {name: style.configure(name) for name in names}
    StudioWindow(gui_root, None)
    assert gui_root.title() == "SpriteSuite – Modding Studio"
    assert style.theme_use() == theme
    assert {name: style.configure(name) for name in names} == original


def test_studio_dirty_close_cancel_save_and_reopen_latest(tmp_path, gui_root, monkeypatch):
    from stronghold_europe_de.modding_studio import gui
    directory = tmp_path / "lifecycle"
    new_project(directory, "life_studio", "Original")
    studio = StudioWindow(gui_root, directory)
    assert not studio.is_dirty()
    # Invalid JSON must also be protected against a canceled close.
    studio._set_editor("{draft")
    assert studio.is_dirty()
    monkeypatch.setattr(gui.messagebox, "askyesnocancel", lambda *a, **k: None)
    assert studio.close() is False
    assert gui_root.winfo_exists()
    studio._set_editor(json.dumps(studio.project["modules"][studio.current_module]))
    studio.project["title"] = "Saved through close guard"
    assert studio.is_dirty()
    monkeypatch.setattr(gui.messagebox, "askyesnocancel", lambda *a, **k: True)
    assert studio.confirm_saved("dem Schließen") is True
    assert not studio.is_dirty()
    reopened = StudioWindow(gui_root, directory)
    assert reopened.project["title"] == "Saved through close guard"
    assert reopened.project["revision"] == 2


def test_studio_close_saves_before_destroy_and_reopens_last_revision(tmp_path, gui_root, monkeypatch):
    from stronghold_europe_de.modding_studio import gui
    directory = tmp_path / "close-save"
    new_project(directory, "close_studio", "Original")
    window = tk.Toplevel(gui_root)
    studio = StudioWindow(window, directory)
    studio.project["title"] = "Revision saved on close"
    monkeypatch.setattr(gui.messagebox, "askyesnocancel", lambda *a, **k: True)
    assert studio.close()
    assert not window.winfo_exists()
    reopened = StudioWindow(tk.Toplevel(gui_root), directory)
    assert reopened.project["revision"] == 2
    assert reopened.project["title"] == "Revision saved on close"
    assert not reopened.is_dirty()

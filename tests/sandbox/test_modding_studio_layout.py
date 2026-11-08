"""Small-window/DPI reachability using synthetic Studio sources only."""
from __future__ import annotations

import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk

import pytest

from stronghold_europe_de.modding_studio.catalog import MODULES
from stronghold_europe_de.modding_studio.gui import StudioWindow
from stronghold_europe_de.modding_studio.model import new_project


@pytest.fixture(scope="module")
def layout_runtime():
    from suite_tcl_runtime import create_tk_root
    try:
        root = create_tk_root()
    except tk.TclError as exc:
        pytest.skip("native Tk is unavailable: " + str(exc))
    root.withdraw()
    original_scaling = root.tk.call("tk", "scaling")
    try:
        yield root
    finally:
        root.tk.call("tk", "scaling", original_scaling)
        root.destroy()


def _descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from _descendants(child)


def _visible(widget, window):
    assert widget.winfo_ismapped(), str(widget) + " is not mapped"
    x = widget.winfo_rootx() - window.winfo_rootx()
    y = widget.winfo_rooty() - window.winfo_rooty()
    width, height = widget.winfo_width(), widget.winfo_height()
    assert width > 4 and height > 4, (str(widget), width, height)
    assert x >= 0 and y >= 0, (str(widget), x, y)
    assert x + width <= window.winfo_width(), (str(widget), x, width, window.winfo_width())
    assert y + height <= window.winfo_height(), (str(widget), y, height, window.winfo_height())


@pytest.fixture(params=[(950, 630, 1.25), (950, 630, 1.5),
                       (1020, 680, 1.25), (1020, 680, 1.5)])
def small_studio(request, layout_runtime, tmp_path):
    width, height, text_scale = request.param
    # Scaling is local to this isolated Tcl runtime, never Windows settings.
    layout_runtime.tk.call("tk", "scaling", 96 / 72 * text_scale)
    directory = tmp_path / "synthetic-studio"
    new_project(directory, "layout_studio", "Layout-only source")
    original = {p.relative_to(directory): p.read_bytes()
                for p in directory.rglob("*") if p.is_file()}
    window = tk.Toplevel(layout_runtime)
    studio = StudioWindow(window, directory)
    window.geometry(f"{width}x{height}+30+30")
    window.update()
    try:
        yield studio, window, directory
    finally:
        assert {p.relative_to(directory): p.read_bytes()
                for p in directory.rglob("*") if p.is_file()} == original
        if window.winfo_exists():
            window.destroy()


def test_all_actions_and_status_remain_reachable_in_small_scaled_window(small_studio):
    studio, window, _ = small_studio
    buttons = [w for w in _descendants(window) if isinstance(w, ttk.Button)]
    assert len(buttons) == 10
    for button in buttons:
        _visible(button, window)
        assert button.winfo_width() >= button.winfo_reqwidth()
    _visible(studio.status_view, window)
    # All twelve modules remain selectable even if the pane shows fewer rows.
    studio.module_list.see(len(MODULES) - 1)
    window.update()
    last = studio.module_list.bbox(len(MODULES) - 1)
    assert last is not None
    assert 0 <= last[1] < studio.module_list.winfo_height()
    assert last[1] + last[3] <= studio.module_list.winfo_height()


def test_json_and_findings_scroll_to_last_field_and_last_row(small_studio):
    studio, window, _ = small_studio
    value = {f"field-{index:03}": "value" * 120 for index in range(180)}
    studio._set_editor(json.dumps(value, indent=2))
    studio.editor.see("end-1c")
    studio.editor.xview_moveto(1)
    for index in range(140):
        last = studio.results.insert("", tk.END, values=(
            "module-" + str(index), "REVIEW", "LONG_RESULT_CODE", "detail " * 100,
        ))
    studio.results.see(last)
    studio.results.xview_moveto(1)
    window.update()
    assert studio.editor.yview()[0] > 0
    assert studio.editor.xview()[0] > 0
    assert studio.editor.dlineinfo("end-1c") is not None
    row = studio.results.bbox(last)
    assert row
    assert row[1] + row[3] <= studio.results.winfo_height()
    assert studio.results.xview()[0] > 0
    for control in (studio.editor_xbar, studio.editor_ybar,
                    studio.results_xbar, studio.results_ybar,
                    studio.module_xbar, studio.module_ybar):
        _visible(control, window)


def test_every_module_can_be_selected_scrolled_and_checked_without_source_writes(small_studio):
    studio, window, _ = small_studio
    for index, (module, _, _) in enumerate(MODULES):
        studio.module_list.selection_clear(0, tk.END)
        studio.module_list.selection_set(index)
        studio.module_list.see(index)
        studio._on_module_select(None)
        window.update()
        studio.editor.see("end-1c")
        window.update()
        assert studio.current_module == module
        assert studio.editor.dlineinfo("end-1c") is not None
    studio.run_check()
    window.update()
    last = studio.results.get_children()[-1]
    studio.results.see(last)
    window.update()
    assert studio.results.bbox(last)


def test_sdk_explorer_last_action_remains_visible_at_large_text(small_studio):
    studio, window, _ = small_studio
    studio.open_sdk()
    window.update()
    sdk = next(w for w in window.winfo_children() if isinstance(w, tk.Toplevel))
    sdk.geometry("950x630+30+30")
    sdk.update()
    button = next(w for w in _descendants(sdk) if isinstance(w, ttk.Button)
                  and "PublicApi.txt" in str(w.cget("text")))
    _visible(button, sdk)


def test_long_status_and_preview_corners_are_reachable_without_expanding_window(small_studio):
    from suite_workarea import ScrollableWorkarea
    studio, window, _ = small_studio
    studio.status.set("Long diagnostic " * 150 + " LAST_STATUS_DETAIL")
    studio.status_view.see("end-1c")
    window.update()
    assert studio.status_view.dlineinfo("end-1c") is not None
    assert studio.status_view.yview()[0] > 0
    _visible(studio.status_view, window)
    _visible(studio.status_ybar, window)
    for index in (2, 7):
        studio.module_list.selection_clear(0, tk.END)
        studio.module_list.selection_set(index)
        studio._on_module_select(None)
        studio.preview()
        preview = [w for w in window.winfo_children() if isinstance(w, tk.Toplevel)][-1]
        preview.geometry("420x360+30+30")
        preview.update()
        area = next(w for w in _descendants(preview) if isinstance(w, ScrollableWorkarea))
        area.canvas.xview_moveto(1)
        area.canvas.yview_moveto(1)
        preview.update()
        assert area.canvas.xview()[0] > 0
        assert area.canvas.yview()[0] > 0
        _visible(area.xbar, preview)
        _visible(area.ybar, preview)
        footer = next(w for w in preview.winfo_children() if isinstance(w, ttk.Label))
        _visible(footer, preview)


def test_long_status_has_current_scroll_metrics_before_idle_callbacks(small_studio):
    studio, window, _ = small_studio
    # Tk 9 can return (-1, 1) while its deferred display-line metric tasks are
    # still pending. Native count -update makes the scrollbar usable directly
    # after a diagnostic replacement; update()/dlineinfo() must not hide this.
    studio.status.set("Long diagnostic " * 150 + " LAST_STATUS_DETAIL")
    studio.status_view.see("end-1c")
    start, end = studio.status_view.yview()
    assert 0 < start < end <= 1
    assert studio.status_view.get("end-20c", "end-1c").endswith("LAST_STATUS_DETAIL")
    assert studio.status_view.dlineinfo("end-1c") is not None
    studio.status_view.yview_moveto(0)
    assert studio.status_view.dlineinfo("1.0") is not None
    studio.status_view.yview_moveto(1)
    assert studio.status_view.dlineinfo("end-1c") is not None
    _visible(studio.status_view, window)


@pytest.mark.parametrize("destroy_default", [False, True])
def test_studio_owns_variables_when_default_root_is_foreign_or_destroyed(
        layout_runtime, tmp_path, monkeypatch, destroy_default):
    # Embedded windows must use their own interpreter even if another tool
    # created/destroyed Tk's implicit default. Do not repair global Tk state.
    foreign = tk.Tk()
    foreign.withdraw()
    if destroy_default:
        foreign.destroy()
    monkeypatch.setattr(tk, "_default_root", foreign)
    directory = tmp_path / "owned-studio"
    new_project(directory, "owned_studio", "Explicit interpreter")
    window = tk.Toplevel(layout_runtime)
    try:
        studio = StudioWindow(window, directory)
        window.geometry("950x630+30+30")
        window.update()
        for variable in (studio.info, studio.section_title, studio.section_summary, studio.status):
            assert variable._tk is window.tk
            assert variable._tk is not foreign.tk
        info_entry = next(w for w in _descendants(window) if isinstance(w, ttk.Entry)
                          and str(w.cget("textvariable")) == str(studio.info))
        assert info_entry.get() == studio.info.get() and directory.name in info_entry.get()
        for index in (2, 7):
            studio.module_list.selection_clear(0, tk.END)
            studio.module_list.selection_set(index)
            studio._on_module_select(None)
            window.update()
            assert studio.current_module == MODULES[index][0]
            label = next(w for w in _descendants(window) if isinstance(w, ttk.Label)
                         and str(w.cget("textvariable")) == str(studio.section_title))
            assert label.tk.call("set", str(studio.section_title)) == studio.section_title.get()
        studio.status.set("Long diagnostic " * 150 + " LAST_STATUS_DETAIL")
        studio.status_view.see("end-1c")
        assert 0 < studio.status_view.yview()[0] < 1
        assert studio.status_view.get("end-20c", "end-1c").endswith("LAST_STATUS_DETAIL")
        assert tk._default_root is foreign
    finally:
        window.destroy()
        if not destroy_default:
            foreign.destroy()

"""Real Tk atlas replacement with synthetic PNG/XAML pairs only."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import threading
import time
import tkinter as tk
from tkinter import ttk

from PIL import Image
import pytest

import hud_menu_workspace as hud
from suite_tcl_runtime import create_tk_root
from suite_ui_atlas_workspace import AtlasWorkspaceWindow, open_workspace
from ui_atlas_workspace import AtlasProject


@pytest.fixture(scope="module")
def runtime():
    root = create_tk_root()
    root.withdraw()
    try:
        yield root
    finally:
        root.destroy()


@pytest.fixture
def workspace(tmp_path, monkeypatch, runtime):
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setattr(hud, "ROOT", tmp_path)
    monkeypatch.setattr(hud, "WORK", work)
    project = work / "suite-project"
    project.mkdir()
    parent = tk.Toplevel(runtime)
    parent.withdraw()
    parent.language = tk.StringVar(master=parent, value="DE")
    views = []
    def make(**kwargs):
        view = AtlasWorkspaceWindow(parent, **kwargs)
        view.root.geometry("950x630+20+20")
        views.append(view)
        view.root.update()
        return view
    yield make, parent, project, tmp_path
    for view in views:
        if view.root.winfo_exists():
            view.close()
            deadline = time.monotonic() + 5
            while view.root.winfo_exists() and time.monotonic() < deadline:
                parent.update()
                time.sleep(.01)
    parent.destroy()


def pair(folder, name, color, *, size=(64, 32), entry_size=(8, 8)):
    folder.mkdir(parents=True, exist_ok=True)
    png, xaml = folder / (name + ".png"), folder / (name + ".xaml")
    image = Image.new("RGBA", size, (5, 10, 15, 255))
    image.paste(color, (4, 4, 4 + entry_size[0], 4 + entry_size[1]))
    image.save(png)
    xaml.write_text(
        '<ResourceDictionary xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" '
        'xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml">'
        f'<BitmapImage x:Key="Sheet" UriSource="{png.name}"/>'
        f'<CroppedBitmap x:Key="{name}Icon" Source="{{StaticResource Sheet}}" '
        f'SourceRect="4,4,{entry_size[0]},{entry_size[1]}"/>'
        f'<CroppedBitmap x:Key="{name}Other" Source="{{StaticResource Sheet}}" SourceRect="20,4,8,8"/>'
        '</ResourceDictionary>', encoding="utf8")
    return png, xaml


def wait(view, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        view.root.update()
        if not view.busy and not view._pending_preview:
            return
        time.sleep(.01)
    pytest.fail("Atlas GUI worker did not settle: " + view.status.get())


def load_pair(view, files, *, source=False):
    (view.source_png if source else view.target_png).set(str(files[0]))
    (view.source_xaml if source else view.target_xaml).set(str(files[1]))
    assert view.create_atlas(source=source)
    wait(view)
    assert (view.source_project if source else view.atlas_project) is not None, view.status.get()


def test_native_source_selection_replace_undo_redo_exports_and_reopens(workspace):
    make, _parent, project, scratch = workspace
    target = pair(scratch / "inputs", "target", (180, 20, 40, 255))
    source = pair(scratch / "inputs", "source", (10, 220, 80, 127))
    original = {path: path.read_bytes() for path in (*target, *source)}
    published = []
    view = make(project=project, on_export=lambda path: published.append((path, threading.get_ident())))
    load_pair(view, target)
    load_pair(view, source, source=True)
    view.target_tree.selection_set("targetIcon")
    view.source_tree.selection_set("sourceIcon")
    view.root.update()
    wait(view)
    assert view.replace_selected()
    wait(view)
    assert view.atlas_project.preview("targetIcon").getpixel((0, 0)) == (10, 220, 80, 127)
    assert view.atlas_project.original_preview("targetIcon").getpixel((0, 0)) == (180, 20, 40, 255)
    assert view.undo()
    wait(view)
    assert view.atlas_project.preview("targetIcon").getpixel((0, 0)) == (180, 20, 40, 255)
    assert view.redo()
    wait(view)
    assert view.atlas_project.preview("targetIcon").getpixel((0, 0)) == (10, 220, 80, 127)
    crop, atlas = scratch / "chosen-crop.png", scratch / "chosen-atlas.png"
    assert view.export_png(crop, crop=True)
    wait(view)
    assert Image.open(crop).size == (8, 8)
    assert view.export_png(atlas)
    wait(view)
    assert Image.open(atlas).getpixel((4, 4)) == (10, 220, 80, 127)
    assert Image.open(atlas).getpixel((30, 20)) == (5, 10, 15, 255)
    assert published == [(atlas, threading.get_ident())]
    saved = view.current_workspace
    assert view.save() and not view.is_dirty()
    view.close()
    reopened = make(project=project)
    assert reopened.load_workspace(saved)
    wait(reopened)
    assert reopened.atlas_project.preview("targetIcon").getpixel((0, 0)) == (10, 220, 80, 127)
    reopened.target_tree.selection_set("targetIcon")
    assert reopened.restore_selected()
    wait(reopened)
    assert reopened.atlas_project.preview("targetIcon").getpixel((0, 0)) == (180, 20, 40, 255)
    assert all(path.read_bytes() == before for path, before in original.items())


def test_replacement_png_explicit_fit_and_export_overwrite_error(workspace):
    make, _parent, _project, scratch = workspace
    view = make()
    load_pair(view, pair(scratch / "inputs", "target", (180, 20, 40, 255)))
    replacement = scratch / "small.png"
    Image.new("RGBA", (2, 4), (60, 200, 90, 255)).save(replacement)
    view.source_kind.set("png")
    view.replacement_png.set(str(replacement))
    wait(view)
    assert view.replace_selected()
    wait(view)
    assert view.atlas_project.preview("targetIcon").getpixel((0, 0)) == (180, 20, 40, 255)
    assert "size" in view.status.get().lower() or "dimension" in view.status.get().lower()
    view.fit.set("contain")
    assert view.replace_selected()
    wait(view)
    crop = view.atlas_project.preview("targetIcon")
    assert crop.getpixel((0, 0))[3] == 0 and crop.getpixel((4, 4)) == (60, 200, 90, 255)
    view.fit.set("stretch")
    assert view.replace_selected()
    wait(view)
    assert view.atlas_project.preview("targetIcon").getpixel((0, 0)) == (60, 200, 90, 255)
    destination = scratch / "already-exists.png"
    before = b"user-owned-file"
    destination.write_bytes(before)
    assert view.export_png(destination)
    wait(view)
    assert destination.read_bytes() == before
    assert "exist" in view.status.get().lower()


def test_cancel_import_keeps_current_target_and_close_waits_without_tk_worker(workspace, monkeypatch):
    make, parent, project, scratch = workspace
    view = make(project=project)
    load_pair(view, pair(scratch / "inputs", "first", (10, 30, 50, 255)))
    first = view.atlas_project
    started, release = threading.Event(), threading.Event()
    real_create = AtlasProject.create
    main_thread = threading.get_ident()
    def slow(png, xaml, destination, *, cancel=None):
        assert threading.get_ident() != main_thread
        started.set()
        assert release.wait(3)
        return real_create(png, xaml, destination, cancel=cancel)
    monkeypatch.setattr(AtlasProject, "create", slow)
    files = pair(scratch / "inputs", "second", (90, 80, 70, 255))
    view.target_png.set(str(files[0]))
    view.target_xaml.set(str(files[1]))
    assert view.create_atlas()
    assert started.wait(1)
    assert view.is_dirty()
    with pytest.raises(ValueError):
        view.save()
    closed = []
    assert view.close(on_closed=lambda: closed.append(threading.get_ident())) is False
    assert view.root.winfo_exists()
    release.set()
    deadline = time.monotonic() + 4
    while view.root.winfo_exists() and time.monotonic() < deadline:
        parent.update()
        time.sleep(.01)
    parent.update()
    assert not view.root.winfo_exists()
    assert closed == [main_thread]
    assert view.atlas_project is first


def test_filter_and_previews_are_bounded_roi_images(workspace):
    make, _parent, _project, scratch = workspace
    view = make()
    load_pair(view, pair(scratch / "inputs", "target", (180, 20, 40, 255), size=(2048, 1024)))
    assert set(view._preview_images) == {"before", "current"}
    assert all(image.size == (8, 8) for image in view._preview_images.values())
    assert all(photo.width() <= 512 and photo.height() <= 384 for photo in view._photos.values())
    view.target_filter.set("Other")
    view.root.update()
    wait(view)
    assert view.target_tree.get_children() == ("targetOther",)
    assert view._key(view.target_tree) == "targetOther"
    view.target_filter.set("no match")
    view.root.update()
    wait(view)
    assert not view.target_tree.get_children()


@pytest.mark.parametrize("scaling", [1.25, 1.5])
def test_small_scaled_workspace_reaches_last_action_and_preview(workspace, scaling):
    make, parent, _project, scratch = workspace
    before = parent.tk.call("tk", "scaling")
    parent.tk.call("tk", "scaling", 96 / 72 * scaling)
    try:
        view = make()
        load_pair(view, pair(scratch / "inputs", "target", (180, 20, 40, 255)))
        view.root.geometry("780x460+20+20")
        view.root.update()
        assert view.area.canvas.yview()[1] < 1
        view.area.canvas.yview_moveto(1)
        view.root.update()
        preview = view.preview_canvases["current"]
        assert preview.winfo_ismapped()
        y = preview.winfo_rooty() - view.root.winfo_rooty()
        assert 0 <= y and y + preview.winfo_height() <= view.root.winfo_height()
        assert view.cancel_button.winfo_rooty() + view.cancel_button.winfo_height() <= view.root.winfo_rooty() + view.root.winfo_height()
        button = next(button for button in view._controls if isinstance(button, ttk.Button)
                      and button.cget("text") == view.tr("atlas_export"))
        view.area.reveal(button)
        view.root.update()
        y = button.winfo_rooty() - view.root.winfo_rooty()
        assert 0 <= y and y + button.winfo_height() <= view.root.winfo_height()
    finally:
        parent.tk.call("tk", "scaling", before)


def test_factory_caches_bound_project_and_explicit_masters(workspace):
    _make, parent, project, _scratch = workspace
    parent.language.set("EN")
    first = open_workspace(parent, project)
    try:
        assert open_workspace(parent, project) is first
        assert parent._ui_atlas_workspace is first
        assert first.root._atlas_controller is first
        assert first.project == first.root.project == project
        assert first.root.title() == "UI atlas · PNG + XAML"
        for variable in (first.target_png, first.target_xaml, first.fit, first.status):
            assert variable._tk is first.root.tk
    finally:
        first.close()


def test_bound_publish_is_explicit_pair_callback_on_main_thread(workspace):
    make, _parent, project, scratch = workspace
    events = []
    view = make(project=project, on_publish=lambda pair: events.append((pair, threading.get_ident())))
    assert view.publish_button.instate(["disabled"])
    load_pair(view, pair(scratch / "inputs", "target", (180, 20, 40, 255)))
    assert not events
    assert view.publish()
    wait(view)
    assert len(events) == 1 and events[0][1] == threading.get_ident()
    receipt = events[0][0]
    assert Path(receipt["png"]).is_file() and Path(receipt["xaml"]).is_file()
    assert Path(receipt["xaml"]).read_bytes() == (scratch / "inputs/target.xaml").read_bytes()
    assert Path(receipt["png"]).parent.is_relative_to(view.current_workspace / "exports")


def test_cancel_after_pair_export_never_publishes_later(workspace, monkeypatch):
    make, _parent, project, scratch = workspace
    published = []
    view = make(project=project, on_publish=published.append)
    load_pair(view, pair(scratch / "inputs", "target", (180, 20, 40, 255)))
    real_export = view.atlas_project.export_pair
    exports = []
    def export(destination, **kwargs):
        result = real_export(destination, **kwargs)
        exports.append(result)
        return result
    monkeypatch.setattr(view.atlas_project, "export_pair", export)
    assert view.publish()
    # The worker has returned and queued its success, but Tk has not pumped it.
    view._worker.join(3)
    assert not view._worker.is_alive() and not published
    view.cancel()
    wait(view)
    assert not published
    assert len(exports) == 1 and Path(exports[0]["png"]).is_file()
    assert view.status.get() == view.tr("publish_cancelled")


def test_invalid_replacement_preview_uses_core_png_validation(workspace):
    make, _parent, _project, scratch = workspace
    view = make()
    load_pair(view, pair(scratch / "inputs", "target", (180, 20, 40, 255)))
    replacement = scratch / "not-really-png.png"
    Image.new("RGB", (8, 8), "red").save(replacement, format="JPEG")
    view.source_kind.set("png")
    view.replacement_png.set(str(replacement))
    wait(view)
    assert "PNG" in view.status.get()
    assert "source_preview" not in view._preview_images
    assert view.atlas_project.info()["history_count"] == 0


def test_external_core_edit_is_not_overwritten_by_stale_gui(workspace):
    make, _parent, _project, scratch = workspace
    view = make()
    load_pair(view, pair(scratch / "inputs", "target", (180, 20, 40, 255)))
    replacement = scratch / "replacement.png"
    Image.new("RGBA", (8, 8), (10, 80, 220, 255)).save(replacement)
    external = AtlasProject.open(view.current_workspace)
    external.replace("targetIcon", replacement)
    revision = external.info()["revision"]
    assert view.restore_selected()
    wait(view)
    assert "another session" in view.status.get()
    assert AtlasProject.open(view.current_workspace).info()["revision"] == revision
    assert view.load_workspace(view.current_workspace)
    wait(view)
    assert view.atlas_project.preview("targetIcon").getpixel((0, 0)) == (10, 80, 220, 255)


def test_long_status_does_not_hide_workarea_or_final_actions(workspace):
    make, parent, _project, scratch = workspace
    old_scale = parent.tk.call("tk", "scaling")
    parent.tk.call("tk", "scaling", 2.0)
    try:
        view = make()
        load_pair(view, pair(scratch / "inputs", "target", (180, 20, 40, 255)))
        view.root.geometry("780x460+20+20")
        view.root.update()
        view.status.set("Long diagnostic with a source path " * 90 + " LAST_STATUS_DETAIL")
        view.status_view.see("end-1c")
        view.root.update()
        assert view.status_view.dlineinfo("end-1c") is not None
        assert view.status_view.yview()[0] > 0
        assert view.area.canvas.winfo_height() > 150
        button = next(button for button in view._controls if isinstance(button, ttk.Button)
                      and button.cget("text") == view.tr("atlas_export"))
        view.area.reveal(button)
        view.root.update()
        assert 0 <= button.winfo_rooty() - view.root.winfo_rooty()
        assert button.winfo_rooty() + button.winfo_height() <= view.area.canvas.winfo_rooty() + view.area.canvas.winfo_height()
    finally:
        parent.tk.call("tk", "scaling", old_scale)


def test_explicit_atlas_key_binds_renamed_extracted_png(workspace):
    make, _parent, _project, scratch = workspace
    view = make()
    png, xaml = pair(scratch / "inputs", "declared", (180, 20, 40, 255))
    renamed = png.with_name("extracted-file.png")
    png.rename(renamed)
    view.target_png.set(str(renamed))
    view.target_xaml.set(str(xaml))
    assert view.create_atlas()
    wait(view)
    assert view.atlas_project is None
    view.target_atlas_key.set("Sheet")
    assert view.create_atlas()
    wait(view)
    assert view.target_info["atlas_key"] == "Sheet"
    assert view.target_info["sheet"] == "declared.png"
    assert view.atlas_project.preview("declaredIcon").size == (8, 8)


def test_cancel_after_committed_replace_retains_pixels_and_autosave_state(workspace):
    make, _parent, _project, scratch = workspace
    view = make()
    load_pair(view, pair(scratch / "inputs", "target", (180, 20, 40, 255)))
    replacement = scratch / "replacement.png"
    Image.new("RGBA", (8, 8), (10, 80, 220, 255)).save(replacement)
    view.source_kind.set("png")
    view.replacement_png.set(str(replacement))
    wait(view)
    assert view.replace_selected()
    view._worker.join(3)
    assert not view._worker.is_alive()
    view.cancel()
    wait(view)
    assert view.target_info["history_count"] == 1
    assert view.atlas_project.preview("targetIcon").getpixel((0, 0)) == (10, 80, 220, 255)
    reopened = AtlasProject.open(view.current_workspace)
    assert reopened.info()["history_count"] == 1
    assert reopened.preview("targetIcon").getpixel((0, 0)) == (10, 80, 220, 255)

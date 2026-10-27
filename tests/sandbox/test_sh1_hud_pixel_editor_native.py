"""Real Tk SH1 HUD pixel editor: safe edit/undo/save/conflict, no game files."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import sys
import tkinter as tk

from PIL import Image
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))


def test_sh1_pixel_editor_mouse_undo_redo_save_and_concurrent_change(
    tmp_path, monkeypatch
):
    from suite_sh1_hud_editor import Sh1HudPixelEditor
    import ui_sh1_hud
    import suite_sh1_hud_editor as editor_module

    project = tmp_path / "test-project"
    source_dir = project / "original-game"
    source_dir.mkdir(parents=True)
    source = source_dir / "immutable-globalgamemanagers.assets"
    source.write_bytes(b"ORIGINAL-GAME-MUST-NOT-BE-TOUCHED")
    source_sha = sha256(source.read_bytes()).hexdigest()

    # The strengthened editor requires a complete indexed HUD project.
    # Retain real mouse/undo/conflict tests against a synthetic Noesis export.
    from test_sh1_hud_edit_roundtrip import make
    import suite_sh1_hud_core as core
    import json
    work = make(project)
    metadata = work / "sh1_hud_source.json"
    record = json.loads(metadata.read_text(encoding="utf8"))
    record["source"] = "Stronghold 1 Definitive Edition"
    metadata.write_text(json.dumps(record), encoding="utf8")
    atlas = work / "UI-MasterAtlas"
    file = atlas / "UI-HUD 007.png"
    original = (181, 126, 77, 255)
    monkeypatch.setattr(ui_sh1_hud, "DEFAULT_WORK", work)
    monkeypatch.setattr(core, "ROOT", project)
    monkeypatch.setattr(core, "WORK", project / "work")
    errors = []
    monkeypatch.setattr(
        editor_module.messagebox, "showerror",
        lambda title, body, **kw: errors.append((title, body)),
    )
    root = tk.Tk()
    root.geometry("880x670+40+40")
    saved = []
    instance = None
    try:
        instance = Sh1HudPixelEditor(
            root, file, after_save=lambda: saved.append(True)
        )
        root.update()
        before = file.read_bytes()
        instance.color.set("#d91e48")
        # Real canvas event, not only a direct call to the PIL helper.
        instance.canvas.event_generate("<ButtonPress-1>", x=8, y=8)
        instance.canvas.event_generate("<ButtonRelease-1>", x=8, y=8)
        root.update()
        position = (4, 4) if instance.zoom.get() == 2 else (8, 8)
        assert instance.image.getpixel(position) == (217, 30, 72, 255)
        assert file.read_bytes() == before
        instance.undo()
        assert instance.image.getpixel(position) == original
        instance.redo()
        assert instance.image.getpixel(position) == (217, 30, 72, 255)
        instance.save()
        assert saved == [True] and not errors
        with Image.open(file) as image:
            assert image.size == (6, 5)
            assert image.convert("RGBA").getpixel(position) == (
                217, 30, 72, 255
            )
        assert not list(atlas.glob(".sh1-hud-save-*.png"))

        # Another editor changes the disk file after this window loaded it.
        external_colour = (31, 210, 37, 255)
        Image.new("RGBA", (6, 5), external_colour).save(file)
        changed_by_other_editor = file.read_bytes()
        instance.mode.set("Radierer")
        instance.canvas.event_generate("<ButtonPress-1>", x=4, y=4)
        instance.canvas.event_generate("<ButtonRelease-1>", x=4, y=4)
        root.update()
        instance.save()
        assert errors and "außerhalb des Editors" in errors[-1][1]
        assert file.read_bytes() == changed_by_other_editor
        assert saved == [True]
        assert not list(atlas.glob(".sh1-hud-save-*.png"))
        assert sha256(source.read_bytes()).hexdigest() == source_sha

        # Close has an explicit cancelable unsaved-changes confirmation.
        monkeypatch.setattr(
            editor_module.messagebox, "askyesno",
            lambda *args, **kwargs: False,
        )
        instance.close_editor()
        assert instance.winfo_exists()
        monkeypatch.setattr(
            editor_module.messagebox, "askyesno",
            lambda *args, **kwargs: True,
        )
        instance.close_editor()
        assert not instance.winfo_exists()
    finally:
        if instance is not None:
            try:
                if instance.winfo_exists():
                    instance.destroy()
            except tk.TclError:
                pass
        root.destroy()


def test_sh1_pixel_editor_rejects_nonworkspace_png(
    tmp_path, monkeypatch
):
    import ui_sh1_hud
    from suite_sh1_hud_editor import Sh1HudPixelEditor

    work = tmp_path / "work/sh1-hud-editierbar"
    work.mkdir(parents=True)
    outside = tmp_path / "original-source.png"
    Image.new("RGBA", (4, 4), (10, 20, 30, 255)).save(outside)
    original_hash = sha256(outside.read_bytes()).hexdigest()
    monkeypatch.setattr(ui_sh1_hud, "DEFAULT_WORK", work)
    # The path guard runs before Toplevel.__init__: an unsafe source must
    # fail without opening a Tk window (and without reinitializing Tcl after
    # an unrelated Qt GUI test in the same pytest process).
    with pytest.raises(ValueError, match="Arbeitskopien"):
        Sh1HudPixelEditor(None, outside)
    assert sha256(outside.read_bytes()).hexdigest() == original_hash

"""Tk interaction tests for the Stronghold 1 HUD editor; no game graphics."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

tk = pytest.importorskip("tkinter", reason="Tk-GUI-Tests benötigen tkinter")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import ui_sh1_hud


@pytest.fixture
def editor_env(tmp_path, monkeypatch):
    # Use a complete Noesis/PNG export; the editor rightly rejects loose
    # unindexed work PNGs even if they happen to be in a named atlas folder.
    import json
    import suite_sh1_hud_core as core
    from test_sh1_hud_edit_roundtrip import make
    root = make(tmp_path)
    metadata = root / "sh1_hud_source.json"
    source = json.loads(metadata.read_text(encoding="utf8"))
    source["source"] = "Stronghold 1 Definitive Edition"
    metadata.write_text(json.dumps(source), encoding="utf8")
    target = root / "UI-MasterAtlas" / "UI-HUD 007.png"
    monkeypatch.setattr(ui_sh1_hud, "DEFAULT_WORK", root)
    monkeypatch.setattr(core, "ROOT", tmp_path)
    monkeypatch.setattr(core, "WORK", tmp_path / "work")
    try:
        window = tk.Tk()
        window.withdraw()
    except tk.TclError as error:
        pytest.skip(f"Display für Tk nicht vorhanden: {error}")
    from suite_sh1_hud_editor import Sh1HudPixelEditor
    yield window, target, Sh1HudPixelEditor
    window.destroy()


def test_editor_opens_and_paints_png(editor_env, monkeypatch):
    window, target, klass = editor_env
    editor = klass(window, target)
    assert editor.image.size == (6, 5)
    assert editor.mode.get() == "Pinsel"
    editor.mouse_wheel(SimpleNamespace(delta=-120))
    editor.color.set("#FF0000")
    editor.mouse_down(SimpleNamespace(x=3, y=3))
    editor.mouse_up(SimpleNamespace(x=3, y=3))
    changed = editor.image.tobytes()
    editor.undo()
    assert editor.image.tobytes() != changed
    editor.redo()
    assert editor.image.tobytes() == changed
    editor.save()
    with Image.open(target) as opened:
        assert opened.convert("RGBA").tobytes() == editor.image.tobytes()
    editor.close_editor()


def test_editor_rejects_symlink_and_baseline_target(editor_env):
    window, target, klass = editor_env
    baseline = target.parents[1] / "baseline" / "UI-MasterAtlas.png"
    baseline.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (12, 12)).save(baseline)
    with pytest.raises(ValueError, match="Arbeitskopien"):
        klass(window, baseline)
    link = target.with_name("alias.png")
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("Windows-Testbenutzer darf keine Symlinks erstellen")
    with pytest.raises(ValueError):
        klass(window, link)


def test_editor_prevents_overwrite_after_external_changes(editor_env, monkeypatch):
    window, target, klass = editor_env
    editor = klass(window, target)
    calls = []
    monkeypatch.setattr(
        "suite_sh1_hud_editor.messagebox.showerror",
        lambda *a, **k: calls.append(a),
    )
    editor.color.set("#FF0000")
    editor.mouse_down(SimpleNamespace(x=4, y=4))
    editor.mouse_up(SimpleNamespace(x=4, y=4))
    # Simulate another application saving a new image after the editor loaded.
    external = Image.new("RGBA", (6, 5), (17, 129, 229, 255))
    external.save(target)
    editor.save()
    with Image.open(target) as readback:
        assert readback.convert("RGBA").getpixel((0, 0)) == (17, 129, 229, 255)
    assert calls, "external update must produce a visible error instead of overwriting"
    editor.destroy()


def test_editor_works_without_default_tk_root(editor_env, monkeypatch):
    # A parent GUI can disable implicit default-root behavior.
    window, target, klass = editor_env
    monkeypatch.setattr(tk, "_default_root", None)
    monkeypatch.setattr(tk, "_support_default_root", False)
    editor = klass(window, target)
    assert editor.image.size == (6, 5)
    editor.destroy()

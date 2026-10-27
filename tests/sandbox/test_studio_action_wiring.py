"""Qt offscreen regressions for sprite-selector and HUD action wiring.

Only in-memory edits and temporary maps; do not mutate original game sources.
"""
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))


@pytest.fixture
def studio(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("SEDE_SPRACHE", "de")
    import sandbox_studio
    monkeypatch.setattr(sandbox_studio, "ROOT", tmp_path)
    app = QApplication.instance() or QApplication([])
    window = sandbox_studio.SandboxStudio(tmp_path)
    try:
        yield window, app
    finally:
        window.native_canvas._poll.stop()
        window.board._asset_poll.stop()
        window.asset_preview.timer.stop()
        window._saved_scene = window.board.history.scene.serialize()
        window._saved_overlay = (
            window.native_canvas.history.overlay.serialize()
            if window.native_canvas.history is not None else None
        )
        window.close()
        app.processEvents()


def test_native_hud_pixel_button_edits_its_visible_sprite_not_stale_preview(studio, monkeypatch):
    from sandbox_pixel_editor import SpritePixelEditor
    window, app = studio
    created = []

    class FakePixelEditor:
        def __init__(self, group, frame, parent):
            created.append((group, frame, parent))
            self.saved_frame = SimpleNamespace(connect=lambda callback: None)
            self.closed = SimpleNamespace(connect=lambda callback: None)
        def show(self):
            pass

    monkeypatch.setattr("sandbox_pixel_editor.SpritePixelEditor", FakePixelEditor)
    window.asset_preview.group.setCurrentText("body_archer")
    window.asset_preview.frame.setValue(3)
    window.native_hud.group.setCurrentText("tile_castle")
    window.native_hud.frame.setValue(1193)
    window.native_hud.open_edit.click()
    assert created == [("tile_castle", 1193, window)]
    assert len(window._pixel_dialogs) == 1
    assert window._pixel_dialogs[0].__class__ is FakePixelEditor


def test_visible_hud_and_asset_preview_stay_on_same_sprite(studio):
    window, _ = studio
    window.native_hud.group.setCurrentText("tile_castle")
    window.native_hud.frame.setValue(1193)
    assert (window.asset_preview.group.currentText(), window.asset_preview.frame.value()) == (
        "tile_castle", 1193
    )
    window.asset_preview.group.setCurrentText("body_archer")
    window.asset_preview.frame.setValue(7)
    assert (window.native_hud.group.currentText(), window.native_hud.frame.value()) == (
        "body_archer", 7
    )


def test_frame_selection_does_not_silently_clamp_between_tools(studio):
    window, _ = studio
    # Both the current scene model and HUD allow frame indices up to 999999.
    window.native_hud.group.setCurrentText("anim_armourer")
    window.native_hud.frame.setValue(234567)
    assert window.asset_preview.frame.value() == 234567
    window.asset_preview.frame.setValue(345678)
    assert window.native_hud.frame.value() == 345678


def test_original_hud_binding_requires_a_real_native_map(studio, monkeypatch):
    window, _ = studio
    commands = []
    monkeypatch.setattr(window.native_canvas, "arm_placement",
                        lambda group, frame: commands.append((group, frame)))
    window._hud_bindings = SimpleNamespace(
        get=lambda command: SimpleNamespace(group="tile_castle", frame=1193)
    )
    window._hud_art_selected("Bau_test")
    assert not commands
    assert not window.native_canvas.has_map()
    assert "Originalkarte" in window.statusBar().currentMessage()



def test_switching_to_empty_maps_folder_drops_old_native_map(studio, monkeypatch, tmp_path):
    from hashlib import sha256
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    import stronghold_europe_de.sandbox.maps_configuration as maps_config

    window, _ = studio
    source = Path(
        "E:/SSGameQA/Stronghold Crusader Definitive Edition_Data/"
        "StreamingAssets/Maps/Antioch.map"
    )
    if not source.is_file():
        pytest.skip("Read-only QA map not installed")
    original_hash = sha256(source.read_bytes()).hexdigest()
    assert window.open_map(source) and window.native_canvas.has_map()
    other = tmp_path / "no-maps-here"
    other.mkdir()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: str(other))
    monkeypatch.setattr(maps_config, "save_maps_root",
                        lambda root, path: Path(path))
    # If opening the original map leaves a dirty user overlay, explicitly
    # choose Discard. A real modal QMessageBox must not block headless QA.
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *_args, **_kw: QMessageBox.StandardButton.Discard,
    )
    window.choose_folder()
    assert window._root == other
    assert window._current is None
    assert window._image is None
    assert not window.native_canvas.has_map()
    assert window._saved_overlay is None
    assert window.tabs.currentIndex() == 0
    assert not window.save_active()
    assert sha256(source.read_bytes()).hexdigest() == original_hash


def test_export_radar_write_error_reports_failure_without_raising(studio, monkeypatch, tmp_path):
    from PIL import Image
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    window, _ = studio
    window._image = Image.new("RGB", (10, 10))
    impossible = tmp_path / "work" / "out.png"
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        lambda *args: (str(impossible), "PNG-Bild"))
    import sandbox_png_export
    def deny_replace(*_):
        raise OSError("Simulierter Schreibschutz beim Ersetzen")
    monkeypatch.setattr(sandbox_png_export.os, "replace", deny_replace)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *args: warnings.append(args))
    assert window.save_preview() is False
    assert warnings and "Radar" in warnings[0][1]
    assert not impossible.exists()
    assert not list(impossible.parent.glob(".*.png"))

"""Regression checks for actual GUI live reload and editor lifecycle."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sys
import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication

TOOLS = str(Path(__file__).resolve().parents[2] / "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)
import sandbox_studio
import asset_katalog as katalog
from stronghold_europe_de.sandbox.native_visual_mapping import OriginalVisualMappings

MAP = Path("E:/SSGameQA/Stronghold Crusader Definitive Edition_Data/StreamingAssets/Maps/Antioch.map")


@pytest.fixture
def real_studio(tmp_path, monkeypatch):
    if not MAP.is_file():
        pytest.skip("Real game map not available")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setattr(sandbox_studio, "ROOT", tmp_path)
    app = QApplication.instance() or QApplication([])
    studio = sandbox_studio.SandboxStudio(MAP.parent)
    studio.show()
    app.processEvents()
    assert studio.native_canvas.has_map()
    try:
        yield studio, app
    finally:
        for dlg in list(studio._pixel_dialogs):
            dlg._saved = dlg.pixel.image.copy()
            dlg.close()
        studio.native_canvas._poll.stop()
        studio.board._asset_poll.stop()
        studio.asset_preview.timer.stop()
        studio._saved_scene = studio.board.history.scene.serialize()
        studio._saved_overlay = studio.native_canvas.history.overlay.serialize()
        studio.close()


def test_terrain_preview_immediately_invalidates_chunk_cache(real_studio):
    studio, app = real_studio
    canvas = studio.native_canvas
    original_map = hashlib.sha256(MAP.read_bytes()).hexdigest()
    canvas._terrain_chunk(22, 20)
    assert canvas._terrain_chunks
    previous_source = canvas._source
    studio._update_map_asset("tile_land8", katalog.native_name("tile_land8", 1))
    assert not canvas._terrain_chunks
    assert not canvas._texture_signatures
    assert canvas._source is not previous_source
    assert hashlib.sha256(MAP.read_bytes()).hexdigest() == original_map


def test_original_mapped_sprite_change_refreshes_directly(real_studio, monkeypatch):
    studio, app = real_studio
    mapping = OriginalVisualMappings()
    mapping.assign("tree", 31, "anim_armourer", 0)
    studio.native_canvas.set_visual_mappings(mapping)
    calls = []
    original = studio.native_canvas.refresh_asset
    def spy(group, frame):
        calls.append((group, frame))
        return original(group, frame)
    monkeypatch.setattr(studio.native_canvas, "refresh_asset", spy)
    studio._update_map_asset("anim_armourer", katalog.native_name("anim_armourer", 0))
    assert ("anim_armourer", 0) in calls


def test_closed_pixel_editor_does_not_remain_in_open_dialogs(real_studio, monkeypatch):
    # This test verifies the parent's Qt signal/dialog lifetime contract,
    # independent of user-private working sprite PNGs that are not in Git.
    # Real PNG modification and undo/redo are tested in test_pixel_editor.py.
    from PySide6.QtCore import Signal
    from PySide6.QtWidgets import QDialog
    import sandbox_pixel_editor

    class DisposableEditor(QDialog):
        saved_frame = Signal(str, int)
        closed = Signal()

        def __init__(self, group, number, parent=None):
            super().__init__(parent)
            self.group, self.number = group, number

        def closeEvent(self, event):
            self.closed.emit()
            super().closeEvent(event)

    monkeypatch.setattr(sandbox_pixel_editor, "SpritePixelEditor", DisposableEditor)
    studio, app = real_studio
    studio.asset_preview.group.setCurrentText("anim_armourer")
    studio.asset_preview.frame.setValue(0)
    assert studio.open_pixel_editor()
    assert len(studio._pixel_dialogs) == 1
    dialog = studio._pixel_dialogs[0]
    assert isinstance(dialog, DisposableEditor)
    dialog.close()
    app.processEvents()
    assert not studio._pixel_dialogs

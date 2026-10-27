"""Deterministic sprite animation previews must not alter scene saves/history."""
from __future__ import annotations

import sys
from pathlib import Path
from PIL import Image
import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

TOOLS = str(Path(__file__).resolve().parents[2] / "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)
import sandbox_test_board as boardmod
from sandbox_animation_panel import SpriteAnimationPanel


@pytest.fixture
def animation(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    class Frame:
        def __init__(self):
            self.image = Image.new("RGBA", (40, 48), (200, 90, 35, 255))
            self.mask = None
            self.foot = (20, 44)
            self.side = "geliefert"
    class Source:
        def __init__(self, *args, **kwargs):
            pass
        def frame(self, group, name):
            return Frame()
    monkeypatch.setattr(boardmod, "FrameSource", Source)
    monkeypatch.setattr(boardmod.katalog, "native_name", lambda group, n: f"{group}-{n}")
    board = boardmod.SpriteTestBoard()
    panel = SpriteAnimationPanel(board)
    yield app, board, panel
    panel.stop()
    panel._timer.stop()
    board._asset_poll.stop()
    panel.close()
    board.close()


def test_selected_sprite_animates_without_dirty_scene(animation):
    app, board, panel = animation
    uid = board.history.place("unit", 2, 4, 5)
    board.rebuild(focus_id=uid)
    assert panel._ident == uid
    panel.end_frame.setValue(5)
    before = board.history.scene.serialize()
    undo_before = len(board.history._undo)
    assert board.preview_object_frame(uid, 5)
    panel.position.setValue(3)
    assert panel._last_frame == 3
    assert panel.label.text().startswith("Frame 3")
    panel.step_forward()
    assert panel.position.value() == 4
    panel.toggle()
    assert panel._playing
    panel.pause()
    assert not panel._playing
    panel.stop()
    assert board.history.scene.serialize() == before
    assert len(board.history._undo) == undo_before


def test_animation_deletes_selected_object_safely(animation):
    app, board, panel = animation
    uid = board.history.place("unit", 0, 1, 1)
    board.rebuild(focus_id=uid)
    panel.toggle()
    assert panel._playing
    board.delete_selected()
    app.processEvents()
    assert not panel._playing
    assert panel._record() is None

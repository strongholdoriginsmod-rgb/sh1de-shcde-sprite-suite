"""Qt headless tests for interactive test field with isolated SpriteSource."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
from PIL import Image
from stronghold_europe_de.sandbox.scene_model import tile_anchor, load_scene

PySide6 = pytest.importorskip("PySide6")
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

TOOL_DIR = str(Path(__file__).resolve().parents[2] / "tools")
if TOOL_DIR not in sys.path:
    sys.path.insert(0, TOOL_DIR)
import sandbox_test_board as boardmod


@pytest.fixture
def setup_gui(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    class FakeFrame:
        def __init__(self):
            self.side = "arbeit"
            self.foot = (16, 32)
            self.image = Image.new("RGBA", (32, 32), (0, 255, 90, 150))
    class Source:
        def __init__(self, *args, **kwargs):
            self.calls = []
        def frame(self, group, name):
            self.calls.append((group, name))
            return FakeFrame()
    monkeypatch.setattr(boardmod, "FrameSource", Source)
    monkeypatch.setattr(boardmod.katalog, "native_name", lambda g, f: f"{g}-{f}")
    yield app, Source
    # QApplication belongs to test session; another test may reuse it.


def test_board_mouse_place_move_undo_delete(setup_gui, tmp_path):
    app, _ = setup_gui
    board = boardmod.SpriteTestBoard()
    board.resize(960, 700)
    board.show()
    app.processEvents()
    try:
        board.arm_placement("unit_test", 3)
        cx, cy = tile_anchor(4, 7)
        click = board.mapFromScene(cx, cy)
        QTest.mouseClick(board.viewport(), Qt.MouseButton.LeftButton, pos=click)
        app.processEvents()
        assert len(board.history.scene.objects) == 1
        obj = board.history.scene.objects[0]
        assert (obj.x, obj.y, obj.group, obj.frame) == (4, 7, "unit_test", 3)
        ident = obj.id
        board.cancel_placement()
        item = board._items[ident]
        assert item.pixmap().hasAlphaChannel()
        pos = tile_anchor(8, 9)
        board.finish_move_id(ident, *pos)
        assert (board.history.scene.objects[0].x, board.history.scene.objects[0].y) == (8, 9)
        board.undo()
        assert (board.history.scene.objects[0].x, board.history.scene.objects[0].y) == (4, 7)
        board.redo()
        assert (board.history.scene.objects[0].x, board.history.scene.objects[0].y) == (8, 9)
        board._items[ident].setSelected(True)
        board.delete_selected()
        assert not board.history.scene.objects
        board.undo()
        assert len(board.history.scene.objects) == 1
    finally:
        board._asset_poll.stop()
        board.close()


def test_only_changed_asset_reloaded_with_no_scene_reset(setup_gui, tmp_path, monkeypatch):
    app, Source = setup_gui
    monkeypatch.setattr(boardmod.katalog, "work_dir", lambda group: tmp_path)
    board = boardmod.SpriteTestBoard()
    try:
        ident = board.history.place("unit_test", 2, 3, 4)
        board.rebuild(focus_id=ident)
        before = board.history.scene.serialize()
        board.refresh_assets("unit_test", "unit_test-2")
        assert board.history.scene.serialize() == before
        calls = []
        board.refresh_assets = lambda group, name: calls.append((group, name))
        board._known_signatures[("unit_test", "unit_test-2")] = board._signature_for("unit_test", "unit_test-2")
        (tmp_path / "unit_test-2.png").write_bytes(b"new file content")
        board.poll_changed_assets()
        assert calls == [("unit_test", "unit_test-2")]
    finally:
        board._asset_poll.stop()
        board.close()

def test_ground_never_hides_test_objects(setup_gui):
    app, _ = setup_gui
    board = boardmod.SpriteTestBoard()
    try:
        board.set_ground_sprites(True)
        ident = board.history.place("unit_test", 0, 12, 12)
        board.rebuild(focus_id=ident)
        item = board._items[ident]
        assert board.show_ground_sprites
        assert item.zValue() > 0
        assert all(scene_item.zValue() < item.zValue()
                   for scene_item in board.scene().items()
                   if scene_item is not item)
        assert not item.pixmap().isNull()
    finally:
        board._asset_poll.stop()
        board.close()

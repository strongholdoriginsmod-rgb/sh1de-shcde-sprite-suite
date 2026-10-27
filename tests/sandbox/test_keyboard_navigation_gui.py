"""Native sandbox can be inspected and edited entirely with the keyboard.

Original game maps remain read-only. Arrow cursor is an ephemeral Qt marker,
not a persisted/dragged sprite. Return places only into the working overlay.
"""
from pathlib import Path
import sys
import pytest

TOOLS = Path(__file__).resolve().parents[2] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0,str(TOOLS))

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from stronghold_europe_de.sandbox.map_sections import tile_index

from sandbox_native_canvas import NativeMapCanvas

MAP=Path("E:/SSGameQA/Stronghold Crusader Definitive Edition_Data/StreamingAssets/Maps/Antioch.map")


@pytest.fixture
def canvas(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM","offscreen")
    app=QApplication.instance() or QApplication([])
    obj=NativeMapCanvas()
    if not MAP.is_file():
        pytest.skip("Original game map not installed")
    before=MAP.stat()
    obj.open_map(MAP)
    obj.resize(840,560)
    obj.show()
    obj.setFocus()
    app.processEvents()
    yield obj,app
    assert MAP.stat().st_size==before.st_size
    assert MAP.stat().st_mtime_ns==before.st_mtime_ns
    obj._poll.stop()
    obj.close()


def test_arrows_navigate_actual_tiles_and_preserve_read_only_original(canvas):
    view,app=canvas
    picks=[]
    view.picked.connect(lambda x,y,*_:picks.append((x,y)))
    assert view._select_keyboard_tile(400,400)
    assert view._keyboard_tile==(400,400)
    assert view._keyboard_marker is not None
    QTest.keyClick(view,Qt.Key.Key_Right)
    assert view._keyboard_tile==(401,400)
    QTest.keyClick(view,Qt.Key.Key_Up)
    assert view._keyboard_tile==(401,399)
    assert picks[-1]==(401,399)
    assert view.scene().selectedItems()==[]
    assert view.history.overlay.objects==[]
    QTest.keyClick(view,Qt.Key.Key_Escape)
    assert view._keyboard_tile is None
    assert view._keyboard_marker is None


def test_enter_places_only_in_working_overlay_with_undo_history(canvas):
    view,app=canvas
    assert view._select_keyboard_tile(400,400)
    assert view.is_editable_native(400,400)
    saved=view.history.overlay.serialize()
    view.arm_placement("tile_land8",1)
    assert view.hasFocus()
    QTest.keyClick(view,Qt.Key.Key_Return)
    assert len(view.history.overlay.objects)==1
    assert (view.history.overlay.objects[0].x,view.history.overlay.objects[0].y)==(400,400)
    assert view._keyboard_tile==(400,400)
    assert view._keyboard_marker is not None # survives rebuild
    view.undo()
    assert view.history.overlay.serialize()==saved


def test_border_cannot_be_selected_or_placed_by_keyboard(canvas):
    view,app=canvas
    assert tile_index(399,0)>=0
    assert not view.is_editable_native(399,0)
    assert not view._select_keyboard_tile(399,0)
    view._keyboard_tile=(399,0) # simulate a stale externally restored cursor
    view.arm_placement("tile_land8",1)
    before=len(view.history.overlay.objects)
    messages=[]
    view.message.connect(messages.append)
    QTest.keyClick(view,Qt.Key.Key_Return)
    assert len(view.history.overlay.objects)==before
    assert any("Ungültige Position" in msg or "Rand" in msg for msg in messages)
    QTest.keyClick(view,Qt.Key.Key_Escape)
    assert view._keyboard_tile is None
    assert view._placing is None

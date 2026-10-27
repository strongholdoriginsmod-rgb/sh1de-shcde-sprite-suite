"""The native map uses the real data mask and never allows padding placement."""
from pathlib import Path
import sys

import pytest
pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPixmap, QPainter
from PySide6.QtCore import QRectF

from stronghold_europe_de.sandbox.map_sections import tile_index

TOOLS = str(Path(__file__).resolve().parents[2] / "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)
from sandbox_native_canvas import NativeMapCanvas, TILE_X, TILE_Y
from sandbox_game_hud import NativeGameHUD
from sandbox_native_panel import NativeObjectInspector

MAP = Path("E:/SSGameQA/Stronghold Crusader Definitive Edition_Data/StreamingAssets/Maps/Antioch.map")


@pytest.mark.skipif(not MAP.is_file(), reason="Installed game map unavailable")
def test_original_world_bounds_and_padding_unpainted(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    canvas = NativeMapCanvas()
    try:
        canvas.open_map(MAP)
        assert canvas.native_geometry is not None
        assert canvas.native_geometry.padding_tiles == 276679
        assert canvas.scene().sceneRect().width() < 15000
        assert canvas.scene().sceneRect().height() < 8500
        assert not canvas.select_native(399, 0)
        assert not canvas.is_editable_native(399, 0)
        assert canvas.is_editable_native(400, 400)
        assert canvas.select_native(400, 400)

        # The original outer corner must never request any grass/rock/water
        # sprite. This catches the previously visible giant fake terrain.
        requested = []
        canvas._get_terrain_texture = lambda *args: requested.append(args) or None
        target = QPixmap(500, 100)
        target.fill()
        painter = QPainter(target)
        painter.translate(-390*TILE_X, 0)
        canvas._draw_terrain_area(painter, QRectF(390*TILE_X, 0, 500, 100))
        painter.end()
        assert requested == []
    finally:
        canvas._poll.stop()
        canvas.close()


@pytest.mark.skipif(not MAP.is_file(), reason="Installed game map unavailable")
def test_hud_occupancy_diagnostics_are_toggleable(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    canvas = NativeMapCanvas()
    hud = NativeGameHUD(canvas)
    inspector = NativeObjectInspector(canvas)
    try:
        canvas.open_map(MAP)
        hud.display_map(MAP)
        assert "44,121" in hud.map_title.text()
        assert "Objektbelegung 3004" in hud.show_occupancy.text()
        assert not canvas.show_occupancy
        hud.show_occupancy.setChecked(True)
        assert canvas.show_occupancy
        hud.show_occupancy.setChecked(False)
        assert not canvas.show_occupancy
        assert canvas.select_native(400, 400)
        assert inspector._terrain_code is not None
        assert "3003=" in hud.values.text()
        assert "3004=" in hud.values.text()
        assert "3005=" in hud.values.text()
        assert canvas.select_native(464, 319)
        assert "3004-Belegung #4310" in inspector.detail.text()
        assert "4×4" in inspector.detail.text()
        canvas.history.place("tile_land8", 1, 400, 400)
        canvas.rebuild()
        obj = canvas.history.overlay.objects[0]
        before = canvas.history.overlay.serialize()
        # Even a property-panel move is blocked outside the original world.
        canvas._items[obj.id].setSelected(True)
        inspector.select(obj.id)
        inspector.x.setValue(399)
        inspector.y.setValue(0)
        inspector.apply_changes()
        assert canvas.history.overlay.serialize() == before
        assert "Randbereiche" in inspector.detail.text()
    finally:
        hud._stop()
        canvas._poll.stop()
        inspector.close()
        hud.close()
        canvas.close()

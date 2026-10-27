"""Real-map original-object visual mapping via Qt inspector and native editor."""
from pathlib import Path
import sys
import pytest
from PIL import Image

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication, QGraphicsPixmapItem
from stronghold_europe_de.sandbox.native_visual_mapping import load_mappings

TOOLS = str(Path(__file__).resolve().parents[2] / "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)
import sandbox_studio
import sandbox_native_canvas

MAP = Path("E:/SSGameQA/Stronghold Crusader Definitive Edition_Data/StreamingAssets/Maps/Antioch.map")


@pytest.mark.skipif(not MAP.is_file(), reason="Installed original map unavailable")
def test_original_tree_sprite_mapping_live_reload_and_persistence(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setattr(sandbox_studio, "ROOT", tmp_path)
    app = QApplication.instance() or QApplication([])

    class MockFrame:
        image = Image.new("RGBA", (64, 96), (80, 170, 43, 230))
        foot = (32, 86)
        mask = None
        side = "arbeit"

    class Source:
        def __init__(self, *args, **kwargs):
            pass
        def frame(self, group, name):
            return MockFrame()

    monkeypatch.setattr(sandbox_native_canvas, "FrameSource", Source)
    win = sandbox_studio.SandboxStudio(tmp_path)
    try:
        assert win.open_map(MAP)
        assert len(win.native_canvas.original_trees) == 1139
        source = next(t for t in win.native_canvas.original_trees if t.raw_group == 31)
        marker = next(item for item in win.native_canvas.scene().items()
                      if item.data(1) is not None
                      and item.data(1).record_number == source.record_number)
        marker.setSelected(True)
        app.processEvents()
        assert win.native_canvas.selected_original()[0:2] == ("tree", 31)
        assert win.native_inspector._original == ("tree", 31)

        win.asset_preview.group.setCurrentText("tree_birch")
        win.asset_preview.frame.setValue(0)
        assert win.assign_original_visual()
        visual = win._native_visuals.get("tree", 31)
        assert visual.group == "tree_birch" and visual.frame == 0
        assert win._mapping_path.is_file()
        assert load_mappings(win._mapping_path).get("tree", 31) == visual
        assert win.native_canvas.selected_original()[0:2] == ("tree", 31)
        items = [item for item in win.native_canvas.scene().items()
                 if item.data(1) is not None and item.data(1).raw_group == 31]
        assert items
        assert all(isinstance(item, QGraphicsPixmapItem) for item in items)
        assert all(item.flags() & item.GraphicsItemFlag.ItemIsSelectable for item in items)

        first_id = items[0].data(1).record_number
        win.native_canvas.refresh_asset("tree_birch", 0)
        updated = [item for item in win.native_canvas.scene().items()
                   if item.data(1) is not None
                   and item.data(1).record_number == first_id]
        assert len(updated) == 1 and isinstance(updated[0], QGraphicsPixmapItem)
        assert win.native_canvas.selected_original()[0:2] == ("tree", 31)
        assert win.clear_original_visual()
        assert load_mappings(win._mapping_path).get("tree", 31) is None
        restored = [item for item in win.native_canvas.scene().items()
                    if item.data(1) is not None and item.data(1).raw_group == 31]
        assert all(not isinstance(item, QGraphicsPixmapItem) for item in restored)
    finally:
        win.native_canvas._poll.stop()
        win.board._asset_poll.stop()
        win.asset_preview.timer.stop()
        win._saved_scene = win.board.history.scene.serialize()
        if win.native_canvas.has_map():
            win._saved_overlay = win.native_canvas.history.overlay.serialize()
        win.close()

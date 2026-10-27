"""Palette signals and frame-paging regression tests."""
import sys
from pathlib import Path
from PIL import Image
import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication
TOOLS = str(Path(__file__).resolve().parents[2] / "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)
import sandbox_sprite_palette as palette


def test_frame_palette_selection_and_placement(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(palette.katalog, "known_groups", lambda: ["fake"])
    monkeypatch.setattr(palette.katalog, "native_name", lambda g, n: f"f{n}")
    (tmp_path / "index.json").write_text("{}")
    monkeypatch.setattr(palette.katalog, "side_dir", lambda side, group: tmp_path)
    monkeypatch.setattr(palette.katalog, "index_of", lambda folder: {
        "frames": [{"name": f"f{i}"} for i in (0, 1, 32)]
    })
    class Frame:
        image = Image.new("RGBA", (24, 32), (190, 200, 30, 255))
        side = "arbeit"
    class Source:
        def __init__(self, *args, **kwargs):
            pass
        def frame(self, group, name):
            number = int(name[1:])
            return Frame() if number in (0, 1, 32) else None
    monkeypatch.setattr(palette, "FrameSource", Source)
    p = palette.SpritePalette()
    selected, placed = [], []
    p.frame_selected.connect(lambda g, f: selected.append((g, f)))
    p.placement_requested.connect(lambda g, f: placed.append((g, f)))
    try:
        p.reload()
        assert p.tiles.count() == 2
        p._selected(p.tiles.item(1))
        p._place(p.tiles.item(0))
        assert selected == [("fake", 1)]
        assert placed == [("fake", 0)]
        p.next.click()
        assert p.page.value() == 1
        assert p.tiles.count() == 1
        assert p.tiles.item(0).text() == "32"
    finally:
        p.close()

"""Headless regression test for the real-map Qt explorer."""
import importlib.util
import sys
from pathlib import Path

import pytest

MAPS = Path("E:/SSGameQA/Stronghold Crusader Definitive Edition_Data/StreamingAssets/Maps")
QT_AVAILABLE = importlib.util.find_spec("PySide6") is not None


@pytest.mark.skipif(not QT_AVAILABLE or not MAPS.is_dir(),
                    reason="Qt or installed SHCDE maps are unavailable")
def test_qt_map_explorer(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("test_sandbox_studio", root / "tools" / "sandbox_studio.py")
    studio = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = studio
    spec.loader.exec_module(studio)
    app = QApplication.instance() or QApplication([])
    win = studio.SandboxStudio(MAPS)
    try:
        assert len(win._infos) >= 3
        assert win._image is not None
        assert win.open_map(MAPS / "Antioch.map")
        assert win.show_height_section()
        assert win.tabs.currentIndex() == 2
        assert win._height_image.size == (800, 800)
        assert win.height_view.scene().sceneRect().width() == 800
        assert len(win._native_values) == 320800
        win._raw_pixel_picked(399, 0)
        win.tabs.setCurrentIndex(0)
        win.viewer.zoom(1.2)
        win.viewer.select_pixel(60, 80)
        win.filter.setText("Antioch")
        assert win.maplist.count() >= 1
        assert win._current.name == "Antioch.map"
    finally:
        win.close()
        app.quit()

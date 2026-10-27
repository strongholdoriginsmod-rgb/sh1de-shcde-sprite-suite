"""Asset comparison dock: dynamic labels, in-place refresh and absent assets."""
import importlib.util
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
from PIL import Image
from PySide6.QtWidgets import QApplication


@pytest.fixture
def panel(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    import sys
    tools = str(Path(__file__).resolve().parents[2] / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    import sandbox_asset_preview as preview
    monkeypatch.setattr(preview.katalog, "known_groups", lambda: ["unit_test_group"])
    monkeypatch.setattr(preview.katalog, "native_name", lambda group, frame: f"{group}-{frame}")
    monkeypatch.setattr(preview.katalog, "work_dir", lambda group: tmp_path)
    monkeypatch.setattr(preview.katalog, "target_game_dir", lambda: tmp_path)
    class FakeFrame:
        def __init__(self, mode, color):
            self.side = mode
            self.image = Image.new("RGBA", (32, 32), color)
    class FakeSource:
        def __init__(self, mode, **_):
            self.mode = mode
        def frame(self, group, name):
            return FakeFrame(self.mode, (255, 30, 10, 255))
    monkeypatch.setattr(preview, "FrameSource", FakeSource)
    widget = preview.AssetPreview()
    yield widget, preview, tmp_path
    widget.timer.stop()
    widget.close()


def test_source_labels_and_refresh(panel):
    widget, preview, tmp_path = panel
    widget.refresh()
    assert widget.original_caption.text() == "Referenz: crusader"
    assert widget.work_caption.text() == "Aktuell: arbeit"
    assert not widget.work.pixmap().isNull()
    calls = []
    widget.refresh = lambda: calls.append(True)
    widget._watch()
    assert len(calls) == 0
    (tmp_path / "unit_test_group-0.png").write_bytes(b"new work sprite")
    widget._watch()
    assert len(calls) == 1


def test_selecting_new_frame_resets_watcher(panel):
    widget, preview, tmp_path = panel
    widget.refresh()
    widget.frame.setValue(5)
    assert widget._last_selection is None

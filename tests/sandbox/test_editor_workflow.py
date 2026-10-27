"""Full Sandbox Studio GUI save/open/inspect workflow without external assets."""
import importlib.util
import sys
from pathlib import Path

import pytest
from PIL import Image

QT_AVAILABLE = importlib.util.find_spec("PySide6") is not None
pytestmark = pytest.mark.skipif(not QT_AVAILABLE, reason="PySide6 not installed")


def test_editor_workflow(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    tools = Path(__file__).resolve().parents[2] / "tools"
    if str(tools) not in sys.path:
        sys.path.insert(0, str(tools))
    import sandbox_test_board
    class FakeFrame:
        def __init__(self):
            self.side = "arbeit"
            self.foot = (10, 20)
            self.image = Image.new("RGBA", (30, 35), (100, 150, 90, 190))
    class Source:
        def __init__(self, *args, **kwargs):
            pass
        def frame(self, *args):
            return FakeFrame()
    monkeypatch.setattr(sandbox_test_board, "FrameSource", Source)
    import sandbox_studio

    app = QApplication.instance() or QApplication([])
    win = sandbox_studio.SandboxStudio(tmp_path)
    try:
        assert win.board.history.scene.objects == []
        assert win.tabs.currentIndex() == 0
        win.show_test_field()
        assert win.tabs.currentIndex() == 1
        uid = win.board.history.place("fake_sprite", 4, 1, 2)
        win.board.rebuild(focus_id=uid)
        assert win._saved_scene != win.board.history.scene.serialize()
        assert win.tabs.tabText(1).startswith("* ")
        assert win.inspector._ident == uid
        assert win.animation_panel._ident == uid
        refreshed = []
        win.asset_preview.refresh = lambda: refreshed.append(True)
        win._show_selected_asset(uid)
        assert win.asset_preview.group.currentText() == "fake_sprite"
        assert win.asset_preview.frame.value() == 4
        assert refreshed == [True]
        win.inspector.x.setValue(8)
        win.inspector.y.setValue(6)
        win.inspector.frame.setValue(10)
        # Team names are localized in the UI, but the serialized team
        # identity is a stable scene code. Never select by translated text.
        team_idx = win.inspector.team.findData("blau")
        assert team_idx >= 0
        win.inspector.team.setCurrentIndex(team_idx)
        assert win.inspector.team.currentData() == "blau"
        win.inspector.apply_changes()
        current = win.board.history.scene.objects[0]
        assert (current.x, current.y, current.frame, current.team) == (8, 6, 10, "blau")
        win.undo_test()
        current = win.board.history.scene.objects[0]
        assert (current.x, current.y, current.frame, current.team) == (1, 2, 4, "rot")
        win.redo_test()
        target = tmp_path / "sprite-test.json"
        assert win.save_test_scene(target)
        assert not win.tabs.tabText(1).startswith("* ")
        assert target.exists()
        assert win.new_scene()
        assert not win.board.history.scene.objects
        assert win.load_test_scene(target)
        assert win.board.history.scene.objects[0].frame == 10
        assert not win.tabs.tabText(1).startswith("* ")
    finally:
        # Undo changes already persisted, no save dialog on teardown.
        win._saved_scene = win.board.history.scene.serialize()
        win.board._asset_poll.stop()
        win.asset_preview.timer.stop()
        win.close()
        app.processEvents()

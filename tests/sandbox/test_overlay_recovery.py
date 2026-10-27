"""The real-map renderer survives a corrupt overlay without overwriting it."""
from pathlib import Path
import sys

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication, QMessageBox
from stronghold_europe_de.sandbox.native_overlay import new_overlay

TOOLS = str(Path(__file__).resolve().parents[2] / "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)
import sandbox_studio

MAP = Path("E:/SSGameQA/Stronghold Crusader Definitive Edition_Data/StreamingAssets/Maps/Antioch.map")


@pytest.mark.skipif(not MAP.is_file(), reason="Real SHCDE test map unavailable")
def test_corrupt_overlay_falls_back_to_safe_recovery(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(sandbox_studio, "ROOT", tmp_path)
    reported = []
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *args: reported.append(args[2]) or QMessageBox.StandardButton.Ok)
    original = new_overlay(MAP)
    dest = tmp_path / "sandbox" / "overlays" / (
        f"{MAP.stem}-{original.source_sha256[:12]}.overlay.json"
    )
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"{damaged overlay: not valid JSON")
    initial_bytes = dest.read_bytes()
    win = sandbox_studio.SandboxStudio(tmp_path)
    try:
        assert win.open_map(MAP)
        assert win.native_canvas.has_map()
        assert reported and "unangetastet" in reported[0]
        assert dest.read_bytes() == initial_bytes
        assert win._overlay_path != dest
        assert win._overlay_path.name.endswith(".recovery.overlay.json")
        win.native_canvas.history.place("unit_test", 0, 400, 400)
        assert win.save_map_overlay()
        assert win._overlay_path.exists()
        assert dest.read_bytes() == initial_bytes
        # Reload recovers the safe overlay rather than reverting to blank scene.
        assert win.open_map(MAP)
        assert len(win.native_canvas.history.overlay.objects) == 1
    finally:
        win.native_canvas._poll.stop()
        win.board._asset_poll.stop()
        win.asset_preview.timer.stop()
        win._saved_scene = win.board.history.scene.serialize()
        if win.native_canvas.has_map():
            win._saved_overlay = win.native_canvas.history.overlay.serialize()
        win.close()

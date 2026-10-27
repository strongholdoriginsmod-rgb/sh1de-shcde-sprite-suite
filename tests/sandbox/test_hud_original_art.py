"""Real XAML-derived HUD art is displayed, clickable and bound to safe overlays.

These are tests of the *test interface* and local sprite resources, not claims
that the proprietary runtime's HUD behavior is fully reconstructed.
"""
from pathlib import Path
import sys
import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

TOOLS = str(Path(__file__).resolve().parents[2] / "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)
from sandbox_hud_original_art import (
    OriginalHudArtPanel, OriginalHudArt, load_hud_contract, GROUPS, ROOT
)

# Cropped game art is intentionally not checked into Git; the interactive
# rendering smoke tests only run on machines with that authorized local art.
HAS_LOCAL_ART = (ROOT / "assets/ui/derived/sandbox-hud-crops").is_dir()
from stronghold_europe_de.sandbox.hud_command_bindings import (
    HudCommandBindings, load_bindings, save_bindings
)

MAP = Path("E:/SSGameQA/Stronghold Crusader Definitive Edition_Data/StreamingAssets/Maps/Antioch.map")


def test_hud_mapping_commands_must_come_from_xaml(tmp_path):
    art = load_hud_contract()
    assert len(art["commands"]) >= 140
    allowed = {row["command"] for row in art["commands"] if row["command"]}
    bindings = HudCommandBindings(allowed=allowed)
    command = art["commands"][1]["command"]
    bindings.bind(command, "tile_castle", 1193)
    target = tmp_path / "hud-commands.json"
    save_bindings(target, bindings)
    again = load_bindings(target, allowed)
    assert again.get(command).group == "tile_castle"
    assert again.get(command).frame == 1193
    with pytest.raises(ValueError):
        again.bind("NOT_IN_XAML_COMMAND", "tile_castle", 1)
    again.clear(command)
    save_bindings(target, again)
    assert load_bindings(target, allowed).get(command) is None


@pytest.mark.skipif(not HAS_LOCAL_ART, reason="Authorized local HUD PNG crops unavailable")
def test_every_xaml_hud_page_renders_and_selects_real_command(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    art = load_hud_contract()
    original = OriginalHudArt(art)
    panel = OriginalHudArtPanel(contract=art, art=original)
    selected = []
    panel.command_selected.connect(selected.append)
    try:
        panel.resize(1100, 280)
        panel.show()
        app.processEvents()
        all_commands = set()
        for page_idx, page in enumerate(GROUPS):
            panel.page.setCurrentIndex(page_idx)
            app.processEvents()
            entries = [c for c in art["commands"] if c["page"] == page]
            assert len(panel.icons) == len(entries), page
            assert len(panel.icons) > 0, page
            for icon in panel.icons:
                assert not icon.pixmap().isNull()
                assert icon.pixmap().width() > 0
                assert icon.spec["command"]
                all_commands.add(icon.spec["command"])
        command = next(c["command"] for c in art["commands"] if c["page"] == "H")
        assert panel.select_command(command)
        assert selected[-1] == command
        assert panel.active_command == command
        triggered = []
        panel.bind_requested.connect(triggered.append)
        panel.bind_button.click()
        assert triggered == [command]
        assert len(art['commands']) == 141
        assert all_commands == {entry['command'] for entry in art['commands']}
        # Several original menu buttons intentionally share one XAML command.
        assert len(all_commands) == 134
    finally:
        panel.close()


@pytest.mark.skipif(not MAP.is_file() or not HAS_LOCAL_ART,
                    reason="Installed game map or authorized local HUD art unavailable")
def test_xaml_hud_button_drives_native_canvas_placement(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from sandbox_studio import SandboxStudio
    from stronghold_europe_de.sandbox.native_overlay import load_overlay
    app = QApplication.instance() or QApplication([])
    studio = SandboxStudio(tmp_path)
    try:
        assert studio.original_hud is not None
        assert studio._hud_bindings is not None
        assert studio.open_map(MAP)
        target = tmp_path / "hud-commands.json"
        studio._hud_bindings_path = target
        command = next(c["command"] for c in studio.original_hud.contract["commands"]
                       if c["command"] == "STRUCT_KEEP_ONE")
        studio.asset_preview.group.setCurrentText("tile_castle")
        studio.asset_preview.frame.setValue(1193)
        assert studio._hud_art_bind(command)
        assert load_bindings(target, studio._hud_bindings.allowed).get(command).frame == 1193
        assert studio.original_hud.select_command(command)
        app.processEvents()
        assert studio.native_canvas._placing == ("tile_castle", 1193)
        assert studio.native_canvas.history.overlay.objects == []
        assert studio._hud_art_clear(command)
        assert load_bindings(target, studio._hud_bindings.allowed).get(command) is None
        assert studio.native_canvas._map_path.read_bytes() == MAP.read_bytes()
    finally:
        studio.native_canvas._poll.stop()
        studio._saved_scene = studio.board.history.scene.serialize()
        if studio.native_canvas.has_map():
            studio._saved_overlay = studio.native_canvas.history.overlay.serialize()
        studio.close()

@pytest.mark.skipif(not HAS_LOCAL_ART, reason="Authorized local HUD PNG crops unavailable")
def test_visible_hud_icon_receives_real_qt_mouse_click(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    app = QApplication.instance() or QApplication([])
    panel = OriginalHudArtPanel()
    clicks = []
    panel.command_selected.connect(clicks.append)
    try:
        panel.resize(1200, 330)
        panel.show()
        panel.page.setCurrentIndex(list(GROUPS).index("B"))
        app.processEvents()
        expected = next(spec for spec in panel.contract["commands"]
                        if spec["command"] == "STRUCT_KEEP_ONE")
        item = next(icon for icon in panel.icons
                    if icon.spec is expected or icon.spec["name"] == expected["name"])
        target = panel.view.mapFromScene(item.mapToScene(item.boundingRect().center()))
        assert panel.view.viewport().rect().contains(target)
        QTest.mouseClick(panel.view.viewport(), Qt.MouseButton.LeftButton, pos=target)
        app.processEvents()
        assert clicks and clicks[-1] == "STRUCT_KEEP_ONE"
    finally:
        panel.close()


@pytest.mark.skipif(not HAS_LOCAL_ART, reason="Authorized local HUD PNG crops unavailable")
def test_hud_view_refits_after_delayed_dock_layout(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QMainWindow, QDockWidget
    from PySide6.QtCore import Qt
    app=QApplication.instance() or QApplication([])
    window=QMainWindow()
    panel=OriginalHudArtPanel()
    dock=QDockWidget("Original HUD",window)
    dock.setWidget(panel)
    window.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea,dock)
    window.resize(1100,500)
    window.show()
    try:
        app.processEvents();app.processEvents()
        assert panel.view.transform().m11() > .45
        window.resize(1300,700)
        app.processEvents();app.processEvents()
        assert panel.view.transform().m11() > .45
    finally:
        window.close()

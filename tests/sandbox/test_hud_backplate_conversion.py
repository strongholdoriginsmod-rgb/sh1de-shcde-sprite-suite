"""HUD conversion fidelity: native source pixels, undistorted XAML artwork.

The gameplay HUD is a partial reconstruction; these tests deliberately do
not claim a live economy, historical advisor AI or full Unity shaders.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "src")]

from sandbox_hud_chrome_geometry import hud_backplate_source_rect


@pytest.mark.parametrize(
    "source, viewport",
    [
        ((1752, 206), (320, 60)),
        ((1752, 206), (600, 110)),
        ((1752, 206), (300, 110)),
        ((80, 100), (300, 60)),
        ((100, 100), (100, 100)),
        ((1752, 206), (1, 1)),
    ],
)
def test_hud_parchment_uniform_pixel_aspect_crop(source, viewport):
    x, y, width, height = hud_backplate_source_rect(source, viewport)
    assert 0 <= x < source[0]
    assert 0 <= y < source[1]
    assert 0 < width <= source[0]
    assert 0 < height <= source[1]
    assert x * 2 + width == pytest.approx(source[0])
    assert y * 2 + height == pytest.approx(source[1])
    assert width / viewport[0] == pytest.approx(
        height / viewport[1], abs=1e-10
    )


@pytest.mark.parametrize("bad_source,bad_target", [
    ((0, 206), (300, 75)),
    ((1752, 0), (300, 75)),
    ((1752, 206), (0, 75)),
    ((1752, 206), (300, -1)),
])
def test_hud_parchment_invalid_area_is_not_drawn(bad_source, bad_target):
    with pytest.raises(ValueError, match="ungültige"):
        hud_backplate_source_rect(bad_source, bad_target)


def test_qt_hud_paint_crops_original_source_instead_of_stretching(
    monkeypatch
):
    """At a square viewport only the center of a very wide strip is visible."""
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QColor, QPixmap
    from PySide6.QtWidgets import QApplication
    from sandbox_gameplay_mode import OriginalSourceCommandShelf

    app = QApplication.instance() or QApplication([])
    image = QPixmap(400, 80)
    image.fill(QColor("#00ff00"))
    from PySide6.QtGui import QPainter
    painter = QPainter(image)
    painter.fillRect(0, 0, 100, 80, QColor("#ff0000"))
    painter.fillRect(300, 0, 100, 80, QColor("#0000ff"))
    painter.end()

    widget = OriginalSourceCommandShelf(None)
    widget.original_backplate = image
    widget.resize(100, 80)
    try:
        widget.show()
        app.processEvents()
        output = widget.grab().toImage()
        assert output.width() >= 100
        assert output.height() >= 80
        for x, y in ((5, 5), (50, 40), (95, 75)):
            colour = output.pixelColor(x, y)
            assert colour.green() > 220
            assert colour.red() < 30 and colour.blue() < 30
    finally:
        widget.close()
        app.processEvents()


def test_sha_pinned_hud_command_gallery_has_all_source_pixels():
    """Audit every named XAML command; do not infer the live game command state."""
    contract = json.loads(
        (ROOT / "config/sandbox-hud-original-art-v1.json").read_text(encoding="utf8")
    )
    cache = ROOT / "work/original-ui-native-crops-20261015/manifest.json"
    if not cache.is_file():
        pytest.skip("Private original-game crop cache not available")
    manifest = json.loads(cache.read_text(encoding="utf8"))
    assert manifest["source_kind"] == "UNMODIFIED_LOCAL_GAME_UNITY_UI_TEXTURE"
    entries = manifest["entries"]
    commands = contract["commands"]
    assert commands and len(commands) >= 140
    pages = {command["page"] for command in commands}
    assert len(pages) == 14
    assert not [
        (spec["page"], spec["name"], "normal")
        for spec in commands if spec.get("image") not in entries
    ]
    assert not [
        (spec["page"], spec["name"], "hover")
        for spec in commands
        if spec.get("hover_image")
        and spec.get("hover_image") not in entries
    ]
    assert manifest["scribe_state_mapping"] == (
        "UNVERIFIED_MANUAL_REFERENCE_ONLY"
    )


def test_all_original_hud_xaml_pages_and_conditions_have_live_qt_controls(
    tmp_path, monkeypatch
):
    """Prove that every documented alternative can be selected in the GUI.

    This validates command wiring/pixel selection only. The game does not
    supply actual building conditions, so selecting an alternative is a
    manual, non-gameplay action.
    """
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from types import SimpleNamespace
    from PySide6.QtWidgets import QApplication
    from sandbox_studio import SandboxStudio
    from sandbox_suite_embed import EmbeddedSandboxStudio
    from sandbox_hud_original_art import OriginalHudArtPanel

    app = QApplication.instance() or QApplication([])
    studio = SandboxStudio(tmp_path)
    host = SimpleNamespace(_window=studio)
    try:
        EmbeddedSandboxStudio._compact_for_suite(host)
        if studio.original_hud is None:
            pytest.skip("Original-HUD-XAML-Kontrakt lokal nicht verfügbar")
        hud = host.workspace.game_hud
        hud.setVisible(True)
        studio.show()
        app.processEvents()
        contract = studio.original_hud.contract
        commands = contract["commands"]
        checked_names: set[str] = set()
        for page in sorted({item["page"] for item in commands}):
            index = hud.category.findData(page)
            assert index >= 0, f"XAML-Menü {page} nicht auswählbar"
            hud.category.setCurrentIndex(index)
            app.processEvents()
            page_commands = [
                spec for spec in commands if spec["page"] == page
            ]
            slots = {OriginalHudArtPanel.slot(spec) for spec in page_commands}
            assert len(hud._visible_buttons) == len(slots)
            for spec in page_commands:
                combo_idx = hud.command_choice.findData(spec["name"])
                assert combo_idx > 0, (
                    page, spec["name"], "Befehl fehlt in der Auswahl"
                )
                hud.command_choice.setCurrentIndex(combo_idx)
                app.processEvents()
                assert hud._current_name == spec["name"]
                assert hud.command_choice.currentData() == spec["name"]
                matching = [
                    button for button, visible in hud._visible_buttons
                    if OriginalHudArtPanel.slot(visible)
                    == OriginalHudArtPanel.slot(spec)
                    and visible["name"] == spec["name"]
                ]
                assert len(matching) == 1, (
                    page, spec["name"], "XAML-Alternative nicht sichtbar"
                )
                button = matching[0]
                assert button.isCheckable() and button.isChecked()
                assert button.accessibleName()
                assert button.toolTip()
                if hud.native_icons is not None:
                    assert not button.icon().isNull(), (
                        page, spec["name"], "gepinntes Originalicon nicht sichtbar"
                    )
                checked_names.add(spec["name"])
            # Selecting pages is not allowed to change a test overlay/map.
            assert studio.native_canvas.history is None
            assert studio.native_canvas._placing is None
        assert checked_names == {spec["name"] for spec in commands}
        assert len(checked_names) >= 140
    finally:
        try:
            if host.workspace.game_mode:
                host.workspace.set_mode("editor")
        except AttributeError:
            pass
        studio.native_canvas._poll.stop()
        studio.board._asset_poll.stop()
        studio.asset_preview.timer.stop()
        studio._saved_scene = studio.board.history.scene.serialize()
        studio.close()
        app.processEvents()

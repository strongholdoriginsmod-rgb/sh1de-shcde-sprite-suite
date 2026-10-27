"""Workspace usability, not merely successful Qt import / HWND parenting.

Uses a synthetic empty maps root and never writes original game assets.
Native Win32/DPI coverage is separately in tools/qa_suite_embedded.py.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    # Tests check canonical German control keys regardless of the desktop
    # user preference or an earlier test that switched to English.
    monkeypatch.setenv("SEDE_SPRACHE", "de")
    if str(ROOT / "tools") not in sys.path:
        sys.path.insert(0, str(ROOT / "tools"))
    from PySide6.QtWidgets import QApplication
    from sandbox_studio import SandboxStudio
    from sandbox_suite_embed import EmbeddedSandboxStudio

    app = QApplication.instance() or QApplication([])
    studio = SandboxStudio(tmp_path)
    host = SimpleNamespace(_window=studio)
    try:
        EmbeddedSandboxStudio._compact_for_suite(host)
        studio.show()
        app.processEvents()
        yield app, studio, host.workspace
    finally:
        studio.native_canvas._poll.stop()
        studio.board._asset_poll.stop()
        studio.asset_preview.timer.stop()
        studio._saved_scene = studio.board.history.scene.serialize()
        studio.close()
        app.processEvents()


def test_canvas_first_layout_and_discoverable_tools(workspace):
    app, studio, layout = workspace
    assert not layout.left_open and layout.right_open and not layout.focused
    assert all(not panel.isVisible() for panel in layout._left_docks)
    assert studio._native_dock.isVisible()
    assert len(layout._right_docks) >= 6
    labels = [
        layout.tool_picker.itemText(i) for i in range(layout.tool_picker.count())
    ]
    assert "Spiel-HUD" in labels and "Animation" in labels
    assert "Karten-Inspector" in labels
    assert all(
        not dock.isVisible() for dock in layout._right_docks
        if dock is not studio._native_dock
    )
    assert [studio.tabs.tabText(i) for i in range(4)] == [
        "Radar", "Testfeld", "Kacheldaten", "Spielkarte",
    ]


@pytest.mark.parametrize("width,height", [(1168, 550), (784, 350)])
def test_canvas_majority_and_inspector_content_not_horizontally_clipped(
    workspace, width, height
):
    app, studio, layout = workspace
    studio.resize(width, height)
    layout.refresh_size()
    app.processEvents()
    layout.refresh_size()
    app.processEvents()
    assert studio.tabs.width() >= studio.width() * .55
    assert studio.tabs.height() >= studio.height() * .50
    assert studio._native_inspector_scroll.horizontalScrollBar().maximum() == 0
    assert studio._native_dock.width() < studio.width() * .45


def test_focus_palette_and_repeated_tool_selection(workspace):
    app, studio, layout = workspace
    initial_width = studio.tabs.width()
    layout.set_focus(True)
    app.processEvents()
    assert layout.focused
    assert not layout.left_open and not layout.right_open
    assert all(not dock.isVisible() for dock in (
        *layout._left_docks, *layout._right_docks
    ))
    assert studio.tabs.width() >= initial_width
    layout.toggle_palette()
    app.processEvents()
    assert not layout.focused and layout.left_open
    assert layout._selected_left.isVisible()
    assert layout._selected_right.isVisible()
    layout.toggle_inspector()
    app.processEvents()
    assert not layout.right_open
    assert layout.tool_picker.currentIndex() == 0
    layout.show_tool(studio._hud_dock)
    app.processEvents()
    assert layout.right_open and layout._selected_right is studio._hud_dock
    assert studio._hud_dock.isVisible()
    layout.toggle_inspector()
    app.processEvents()
    assert not layout.right_open and layout.tool_picker.currentIndex() == 0
    index = layout.tool_picker.findText("Spiel-HUD")
    layout.tool_picker.setCurrentIndex(index)
    app.processEvents()
    assert layout.right_open and studio._hud_dock.isVisible()
    layout.restore()
    app.processEvents()
    assert not layout.left_open and layout.right_open
    assert layout.tool_picker.currentText() == "Karten-Inspector"
    assert studio._native_dock.isVisible()


def test_embedded_docks_cannot_float_into_new_window(workspace):
    from PySide6.QtWidgets import QDockWidget

    _, studio, layout = workspace
    for dock in (*layout._left_docks, *layout._right_docks):
        assert dock.features() == QDockWidget.DockWidgetFeature.NoDockWidgetFeatures
        # Dock width remains resizeable through Qt splitters, but a tiny X
        # or accidental drag can no longer hide/relocate the selected tool.


def test_compact_inspector_preserves_existing_button_actions(workspace):
    app, studio, layout = workspace
    inspector = studio.native_inspector
    assert inspector.map_visual.text() == "Originaltyp zuordnen"
    assert inspector.map_visual.toolTip()
    assert inspector.engine_edit.text() == "Kachelgrafik bearbeiten"
    assert inspector.clear_terrain.text() == "Höhentest zurücksetzen"
    assert inspector.group.wordWrap()
    # Buttons and their Qt signal connections are the original widgets.
    assert inspector.map_visual is studio.native_inspector.map_visual


def test_compact_layout_preserves_real_file_actions_and_shortcuts(workspace):
    """Shared menu/toolbar actions must survive the compact toolbar rebuild.

    Before this fix QToolBar.clear() destroyed the original Save/Open
    QActions, silently removing their menu entries and keyboard shortcuts.
    """
    from PySide6.QtGui import QAction
    from PySide6.QtWidgets import QMenu

    app, studio, layout = workspace
    studio.set_ui_language("de")
    expected={
        "Originalkarte öffnen": "Ctrl+O",
        "Aktuelle Szene speichern": "Ctrl+S",
        "Original-Radar": "F1",
        "Interaktives Testfeld": "F2",
        "Spielkarte mit Sprites": "F4",
    }
    menu_actions=[
        action for menu in studio.menuBar().findChildren(QMenu)
        for action in menu.actions()
    ]
    for label, shortcut in expected.items():
        candidates=[a for a in menu_actions if a.text()==label]
        assert len(candidates)==1,label
        assert candidates[0].shortcut().toString()==shortcut
        assert candidates[0] in studio.findChildren(QAction)

    studio.set_ui_language("en")
    for german, shortcut in expected.items():
        label=studio.ui_language.en.get(german,german)
        matches=[a for a in menu_actions if a.text()==label]
        assert len(matches)==1,label
        assert matches[0].shortcut().toString()==shortcut

    studio.set_ui_language("de")
    assert {a.text() for a in menu_actions if a.text() in expected}==set(expected)


def test_compact_tool_switching_stays_functional_after_locale_change(workspace):
    app, studio, layout=workspace
    studio.set_ui_language("en")
    assert layout.tool_picker.accessibleName()=="Choose Sandbox tool"
    values=[layout.tool_picker.itemText(i)
            for i in range(layout.tool_picker.count())]
    assert "Map inspector" in values
    assert "Game HUD" in values
    index=layout.tool_picker.findText("Game HUD")
    layout.tool_picker.setCurrentIndex(index)
    app.processEvents()
    assert studio._hud_dock.isVisible()
    assert layout._selected_right is studio._hud_dock
    studio.set_ui_language("de")
    assert layout.tool_picker.currentData() is studio._hud_dock
    assert layout.tool_picker.currentText()=="Spiel-HUD"


def test_real_keyboard_shortcuts_survive_embed_and_language_switch(workspace):
    """An enabled QAction in the menu is not enough; keyboard must work."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    app,studio,layout=workspace
    studio.set_ui_language("en")
    assert not layout.left_open
    studio.tabs.setCurrentIndex(1)
    QTest.keyClick(studio,Qt.Key.Key_F1)
    app.processEvents()
    assert studio.tabs.currentIndex()==0
    QTest.keyClick(studio,Qt.Key.Key_F2)
    app.processEvents()
    assert studio.tabs.currentIndex()==1

    QTest.keyClick(studio,Qt.Key.Key_F6)
    app.processEvents()
    assert layout.left_open
    QTest.keyClick(studio,Qt.Key.Key_F9)
    app.processEvents()
    assert layout.focused and not layout.left_open and not layout.right_open
    QTest.keyClick(studio,Qt.Key.Key_F9)
    app.processEvents()
    assert not layout.focused
    assert layout.left_open
    studio.set_ui_language("de")
    QTest.keyClick(studio,Qt.Key.Key_F1)
    app.processEvents()
    assert studio.tabs.currentIndex()==0

def test_compact_game_tabs_are_english_and_revert_without_changing_ids(workspace):
    app,studio,layout=workspace
    assert [studio.tabs.tabText(i) for i in range(4)]==[
        "Radar","Testfeld","Kacheldaten","Spielkarte",
    ]
    original_index=studio.tabs.currentIndex()
    studio.set_ui_language("en")
    assert [studio.tabs.tabText(i) for i in range(4)]==[
        "Radar","Test field","Tile data","Game map",
    ]
    assert studio.tabs.currentIndex()==original_index
    studio.set_ui_language("de")
    assert [studio.tabs.tabText(i) for i in range(4)]==[
        "Radar","Testfeld","Kacheldaten","Spielkarte",
    ]


def test_game_hud_tool_picker_uses_stable_dock_across_de_en(workspace):
    """Changing the global Suite language must not break actual HUD routing.

    Display labels change, but Qt itemData remains the QDockWidget identity.
    """
    app,studio,layout=workspace
    for lang in ("de","en","de"):
        studio.set_ui_language(lang)
        app.processEvents()
        index=layout.tool_picker.findData(studio._hud_dock)
        assert index>0,lang
        layout.show_tool(studio._native_dock)
        app.processEvents()
        layout.tool_picker.setCurrentIndex(index)
        app.processEvents()
        assert layout.right_open
        assert layout._selected_right is studio._hud_dock
        assert studio._hud_dock.isVisible()
        assert layout.tool_picker.currentData() is studio._hud_dock

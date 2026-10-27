"""Whole-Sandbox cross-view routing, not an isolated HUD widget test.

Checks users can leave Game mode via editor actions, and a sprite from the
Tk catalogue remains on the actual gameplay canvas. Original .map and
all asset files are READ ONLY. This suite encodes currently open integration
requirements; acceptance is not implied by test existence.
"""
from pathlib import Path
from types import SimpleNamespace
import hashlib,sys

import pytest
pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/"tools"),str(ROOT/"src")]


@pytest.fixture
def workspace(tmp_path,monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM","offscreen")
    monkeypatch.setenv("SEDE_SPRACHE","de")
    from sandbox_studio import SandboxStudio
    from sandbox_suite_embed import EmbeddedSandboxStudio

    app=QApplication.instance() or QApplication([])
    studio=SandboxStudio(tmp_path)
    bridge=SimpleNamespace(_window=studio)
    EmbeddedSandboxStudio._compact_for_suite(bridge)
    studio.resize(1168,542)
    studio.show()
    app.processEvents()
    try:
        yield app,studio,bridge.workspace
    finally:
        if bridge.workspace.game_mode:
            bridge.workspace.set_mode("editor")
        studio.native_canvas._poll.stop()
        studio.board._asset_poll.stop()
        studio.asset_preview.timer.stop()
        studio._saved_scene=studio.board.history.scene.serialize()
        if studio.native_canvas.history is not None:
            studio._saved_overlay=studio.native_canvas.history.overlay.serialize()
        studio.close()
        app.processEvents()



@pytest.fixture
def real_map_session(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM","offscreen")
    monkeypatch.setenv("SEDE_SPRACHE","de")
    maps=Path("E:/SSGameQA/Stronghold Crusader Definitive Edition_Data/StreamingAssets/Maps")
    if not maps.is_dir():
        pytest.skip("Private read-only game QA maps unavailable")
    from sandbox_studio import SandboxStudio
    from sandbox_suite_embed import EmbeddedSandboxStudio
    app=QApplication.instance() or QApplication([])
    studio=SandboxStudio(maps)
    bridge=SimpleNamespace(_window=studio)
    EmbeddedSandboxStudio._compact_for_suite(bridge)
    studio.show()
    app.processEvents()
    if not studio.native_canvas.has_map():
        pytest.skip("No supported loaded native map")
    try:
        yield app,studio,bridge.workspace
    finally:
        if bridge.workspace.game_mode:
            bridge.workspace.set_mode("editor")
        studio.native_canvas.cancel_placement()
        studio.native_canvas._poll.stop()
        studio.board._asset_poll.stop()
        studio.asset_preview.timer.stop()
        studio._saved_scene=studio.board.history.scene.serialize()
        if studio.native_canvas.history is not None:
            studio._saved_overlay=studio.native_canvas.history.overlay.serialize()
        studio.close()
        app.processEvents()


def test_editor_tab_navigation_cannot_leave_hidden_tab_bar_and_map_hud(
    workspace
):
    app,studio,layout=workspace
    canvas=studio.native_canvas
    tabs=studio.tabs
    assert tabs.currentIndex()==0
    layout.set_mode("game")
    app.processEvents()
    assert layout.game_mode
    assert tabs.currentIndex()==3
    assert layout.game_hud.isVisible()
    assert not tabs.tabBar().isVisible()

    # F2 / Testfeld / New test scene are editor tasks, not game overlays.
    studio.show_test_field()
    app.processEvents()
    assert not layout.game_mode
    assert tabs.currentIndex()==1
    assert tabs.tabBar().isVisible()
    assert layout._toolbar.isVisible()
    assert not layout.game_hud.isVisible()
    assert tabs.widget(3) is canvas
    assert tabs.widget(1) is studio.board
    # The previous native inspector was irrelevant in the Testfeld.
    assert layout._selected_right is studio.inspector_dock
    assert studio.inspector_dock.isVisible()

    layout.set_mode("game")
    app.processEvents()
    # F1 / original radar from the Qt menu (same tab navigation).
    tabs.setCurrentIndex(0)
    app.processEvents()
    assert not layout.game_mode
    assert tabs.tabBar().isVisible()
    assert not layout.game_hud.isVisible()
    assert tabs.currentWidget() is studio.viewer

    layout.set_mode("game")
    app.processEvents()
    assert studio.new_scene()
    app.processEvents()
    assert not layout.game_mode
    assert tabs.currentWidget() is studio.board
    assert layout._toolbar.isVisible()


def test_catalogue_to_live_game_keeps_game_mode_not_hidden_inspector(
    monkeypatch
):
    from sandbox_studio import SandboxStudio
    from sandbox_suite_embed import EmbeddedSandboxStudio
    monkeypatch.setenv("QT_QPA_PLATFORM","offscreen")
    monkeypatch.setenv("SEDE_SPRACHE","de")
    maps=Path("E:/SSGameQA/Stronghold Crusader Definitive Edition_Data/StreamingAssets/Maps")
    if not maps.is_dir():
        pytest.skip("Local original read-only test maps unavailable")
    app=QApplication.instance() or QApplication([])
    studio=SandboxStudio(maps)
    bridge=SimpleNamespace(_window=studio)
    EmbeddedSandboxStudio._compact_for_suite(bridge)
    layout=bridge.workspace
    studio.show();app.processEvents()
    canvas=studio.native_canvas
    if not canvas.has_map():
        pytest.skip("No loaded original map")
    source=Path(studio._current)
    original_sha=hashlib.sha256(source.read_bytes()).hexdigest()
    history=canvas.history
    before=history.overlay.serialize()
    owner=SimpleNamespace(
        _closed=False,_window=studio,workspace=layout,
        status=lambda _:None
    )
    try:
        assert layout.game_mode and studio.tabs.currentIndex()==3
        EmbeddedSandboxStudio.select_sprite(owner,"tree_pine",20)
        app.processEvents()
        assert layout.game_mode, "Catalog must not silently change game to editor"
        assert layout.game_hud.isVisible()
        assert not studio.tabs.tabBar().isVisible()
        assert not layout.right_open
        assert canvas._placing==("tree_pine",20)
        assert "tree_pine/20" in layout.game_hud.place.toolTip()
        assert EmbeddedSandboxStudio.selected_sprite(owner)==("tree_pine",20)
        layout.game_hud.place.click()  # visible cancel, not an inserted sprite
        app.processEvents()
        assert canvas._placing is None
        assert layout.game_mode
        assert canvas.history is history
        assert canvas.history.overlay.serialize()==before
        assert hashlib.sha256(source.read_bytes()).hexdigest()==original_sha
        # Explicit Editor is still available when a user actually asks for it.
        layout.game_hud.edit.click()
        app.processEvents()
        assert not layout.game_mode
        assert studio._native_dock.isVisible()
    finally:
        if layout.game_mode:
            layout.set_mode("editor")
        canvas.cancel_placement()
        canvas._poll.stop()
        studio.board._asset_poll.stop()
        studio.asset_preview.timer.stop()
        studio._saved_scene=studio.board.history.scene.serialize()
        studio._saved_overlay=history.overlay.serialize()
        studio.close();app.processEvents()



def test_ctrl_s_saves_only_the_current_editable_workspace(workspace,monkeypatch):
    """Never save a hidden Testfeld while the user views read-only diagnostics."""
    app,studio,layout=workspace
    calls=[]
    monkeypatch.setattr(studio,"save_map_overlay",lambda:calls.append("overlay") or True)
    monkeypatch.setattr(studio,"save_test_scene",lambda:calls.append("scene") or True)
    for index in (0,2):
        studio.tabs.setCurrentIndex(index)
        assert studio.save_active() is False
        assert not calls
        assert "nur lesbar" in studio.statusBar().currentMessage()
    studio.tabs.setCurrentIndex(1)
    assert studio.save_active() is True
    assert calls==["scene"]
    studio.tabs.setCurrentIndex(3)
    assert studio.save_active() is True
    assert calls==["scene","overlay"]

    # A Game HUD's own save action is still the separate map overlay save;
    # the old diagnostics cannot create any hidden file by Ctrl+S.
    layout.set_mode("game")
    app.processEvents()
    assert studio.tabs.currentIndex()==3
    assert studio.save_active() is True
    assert calls==["scene","overlay","overlay"]
    studio.tabs.setCurrentIndex(0)
    app.processEvents()
    assert not layout.game_mode
    assert studio.save_active() is False
    assert calls==["scene","overlay","overlay"]



def test_leaving_test_board_disarms_old_click_and_stops_hidden_animation(
    workspace
):
    """An armed click may not survive the switch to read-only Radar."""
    from PySide6.QtCore import Qt,QPoint
    from PySide6.QtTest import QTest
    app,studio,layout=workspace
    board=studio.board
    studio.show_test_field()
    app.processEvents()
    original=board.history.scene.serialize()
    board.arm_placement("tree_pine",20)
    assert board._placing==("tree_pine",20)
    studio.tabs.setCurrentIndex(0)  # F1 radar/navigation
    app.processEvents()
    assert board._placing is None, "Hidden test-field placement survived F1"
    studio.show_test_field()
    app.processEvents()
    QTest.mouseClick(board.viewport(),Qt.MouseButton.LeftButton,
                     pos=QPoint(board.viewport().width()//2,
                                board.viewport().height()//2))
    app.processEvents()
    assert board.history.scene.serialize()==original

    ident=board.history.place("tree_pine",20,2,3)
    board.rebuild(focus_id=ident)
    anim=studio.animation_panel
    anim.start_frame.setValue(20)
    anim.end_frame.setValue(22)
    anim.toggle()
    assert anim._playing
    studio.tabs.setCurrentIndex(0) # view moved, animation cannot continue
    app.processEvents()
    assert not anim._playing, "Hidden test-field animation survived F1"
    assert not anim._timer.isActive()
    assert anim._last_frame is None


def test_native_armed_placement_cancels_only_when_leaving_map(real_map_session):
    app,studio,layout=real_map_session
    canvas=studio.native_canvas
    assert layout.game_mode
    before=canvas.history.overlay.serialize()
    canvas.arm_placement("tree_pine",20)
    assert canvas._placing==("tree_pine",20)
    # Mere game/editor mode switching stays on the same real map.
    layout.set_mode("editor")
    app.processEvents()
    assert canvas._placing==("tree_pine",20)
    layout.set_mode("game")
    app.processEvents()
    assert canvas._placing==("tree_pine",20)
    studio.show_test_field()
    app.processEvents()
    assert not layout.game_mode
    assert canvas._placing is None
    assert canvas.history.overlay.serialize()==before
    assert not studio.board._placing



def test_editor_inspector_always_matches_active_editing_surface(workspace):
    """Testfeld must not inherit Originalkarten-Inspector from the Game page."""
    app,studio,layout=workspace
    assert layout._selected_right is studio._native_dock
    layout.set_mode("game")
    studio.show_test_field()
    app.processEvents()
    assert not layout.game_mode
    assert layout._selected_right is studio.inspector_dock
    assert studio.inspector_dock.isVisible()
    assert layout.tool_picker.currentData() is studio.inspector_dock

    # Explicitly requested animation is valid while the test board is open.
    layout.show_tool(studio._animation_dock)
    app.processEvents()
    assert layout._selected_right is studio._animation_dock
    studio.show_test_field()
    assert layout._selected_right is studio._animation_dock

    # Leaving the test board must remove that now-unrelated control and
    # show the correct original map/diagnostic inspector.
    studio.tabs.setCurrentIndex(0)
    app.processEvents()
    assert layout._selected_right is studio._native_dock
    assert studio._native_dock.isVisible()
    assert layout.tool_picker.currentData() is studio._native_dock
    studio.tabs.setCurrentIndex(1)
    app.processEvents()
    assert layout._selected_right is studio.inspector_dock
    studio.tabs.setCurrentIndex(2)
    app.processEvents()
    assert layout._selected_right is studio._native_dock
    studio.tabs.setCurrentIndex(3)
    app.processEvents()
    assert layout._selected_right is studio._native_dock



def test_radar_status_matches_active_view_source_and_language(workspace):
    app,studio,layout=workspace
    studio.show_test_field()
    assert "Isometrisches Testfeld" in studio.statusBar().currentMessage()
    studio.tabs.setCurrentIndex(0)
    app.processEvents()
    assert studio.statusBar().currentMessage().startswith(
        "Originalradar: Keine Karte geladen."
    )
    studio.set_ui_language("en")
    app.processEvents()
    assert studio.statusBar().currentMessage().startswith(
        "Original radar: No map loaded."
    )
    studio.set_ui_language("de")
    app.processEvents()
    assert "Originalradar:" in studio.statusBar().currentMessage()
    assert "Testfeld" not in studio.statusBar().currentMessage()


def test_loaded_radar_source_status_never_inherits_other_view(real_map_session):
    app,studio,layout=real_map_session
    path=studio._current.name
    assert studio._image is not None
    studio.show_test_field()
    studio.tabs.setCurrentIndex(0)
    app.processEvents()
    assert "Originalradar:" in studio.statusBar().currentMessage()
    assert path in studio.statusBar().currentMessage()
    assert "Kartenvorschau" in studio.statusBar().currentMessage()
    studio.set_ui_language("en")
    app.processEvents()
    assert "Original radar:" in studio.statusBar().currentMessage()
    assert path in studio.statusBar().currentMessage()
    assert "read-only map preview" in studio.statusBar().currentMessage()

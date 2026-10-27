"""Original Sandkasten v1 -> current integrated UI/wiring parity gates.

Provenance: historical E:/SU/projekt/tools/sandkasten.py and current
E:/SpriteSuite/tools/sandkasten.py have identical SHA-256. Assertions cover
supported TEAM_COLOURS, BC7 rendering in the active test board (not just
preview), and context-specific QAction routing.

These gates do NOT claim V1 scene/GM1/timed-animation equivalence.
"""
from pathlib import Path
from types import SimpleNamespace
import sys
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/"tools"),str(ROOT/"src")]
from sandkasten import TEAM_COLOURS
from stronghold_europe_de.sandbox.scene_model import (
    EditableScene,SceneHistory,SpritePlacement,
)


def test_all_historical_team_colour_codes_roundtrip_as_editable_work_data(tmp_path):
    from stronghold_europe_de.sandbox.native_overlay import NativeOverlay
    required=set(TEAM_COLOURS)
    assert {"orange","lila","tuerkis","grau"}.issubset(required)
    for colour in required:
        history=SceneHistory()
        item=history.place("body_archer",1,5,6,team=colour)
        assert history.scene.objects[0].team==colour
        saved=history.scene.serialize()
        assert EditableScene.deserialize(saved).objects[0].team==colour
        overlay=NativeOverlay("Antioch.map","a"*64,[
            SpritePlacement(item,"body_archer",1,400,420,colour)
        ])
        assert NativeOverlay.deserialize(overlay.serialize()).objects[0].team==colour


@pytest.fixture
def studio(monkeypatch,tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM","offscreen")
    monkeypatch.setenv("SEDE_SPRACHE","de")
    from PySide6.QtWidgets import QApplication
    from sandbox_studio import SandboxStudio
    app=QApplication.instance() or QApplication([])
    window=SandboxStudio(tmp_path)
    window.show()
    app.processEvents()
    try:
        yield app,window
    finally:
        window.native_canvas._poll.stop()
        window.board._asset_poll.stop()
        window.asset_preview.timer.stop()
        window._saved_scene=window.board.history.scene.serialize()
        window.close()
        app.processEvents()


def test_historical_colours_are_exposed_by_actual_object_inspector(studio):
    app,win=studio
    from PySide6.QtWidgets import QComboBox
    assert set(TEAM_COLOURS)=={
        win.inspector.team.itemData(i)
        for i in range(win.inspector.team.count())
    }
    win.show_test_field()
    uid=win.board.history.place("body_archer",4,5,6,team="orange")
    win.board.rebuild(focus_id=uid)
    app.processEvents()
    assert win.inspector.team.currentData()=="orange"
    win.inspector.team.setCurrentIndex(
        win.inspector.team.findData("tuerkis")
    )
    win.inspector.apply_changes()
    assert win.board.history.scene.objects[0].team=="tuerkis"
    win.board.undo()
    assert win.board.history.scene.objects[0].team=="orange"


def test_bc7_checkbox_changes_render_source_of_live_board_not_just_preview(studio):
    app,win=studio
    board=win.board
    preview=win.asset_preview
    win.show_test_field()
    first_scene=board.history.scene.serialize()
    assert not board._source.bc7
    assert not preview.bc7.isChecked()
    preview.bc7.setChecked(True)
    app.processEvents()
    assert board._source.bc7, "BC7 switch must reach actual Testfeld renderer"
    assert board.history.scene.serialize()==first_scene
    assert board.bc7_simulation
    preview.bc7.setChecked(False)
    app.processEvents()
    assert not board._source.bc7
    assert not board.bc7_simulation
    assert board.history.scene.serialize()==first_scene


def test_readonly_views_have_no_dangerous_edit_buttons_and_labels_are_true(studio):
    app,win=studio
    actions=win._workspace_actions
    for key in ("save","overlay","reload","place","delete","undo","redo",
                "original_radar_export","ground"):
        assert key in actions, f"Untracked QAction: {key}"
    for readonly in (0,2):
        win.tabs.setCurrentIndex(readonly)
        win._update_action_context()
        assert all(not actions[key].isEnabled()
                   for key in ("save","overlay","place","delete","undo","redo","ground"))
    win.show_test_field()
    assert actions["save"].isEnabled()
    assert "Testszene" in actions["save"].text()
    assert "Sprite" in actions["reload"].text()
    assert actions["ground"].isEnabled()
    assert not actions["overlay"].isEnabled()
    uid=win.board.history.place("body_archer",4,2,3)
    win.board.rebuild(focus_id=uid)
    app.processEvents()
    assert actions["undo"].isEnabled()
    assert actions["delete"].isEnabled()
    win.tabs.setCurrentIndex(0)
    app.processEvents()
    assert not actions["undo"].isEnabled()
    assert not actions["delete"].isEnabled()


def test_f5_reload_current_test_board_uses_original_working_frame_tool_not_map(studio,monkeypatch):
    app,win=studio
    calls=[]
    win.show_test_field()
    monkeypatch.setattr(win.board,"reload_source",lambda:calls.append("test_board") or True)
    monkeypatch.setattr(win,"open_map",lambda *_:calls.append("wrong_game_map") or True)
    win.reload_current()
    assert calls==["test_board"]

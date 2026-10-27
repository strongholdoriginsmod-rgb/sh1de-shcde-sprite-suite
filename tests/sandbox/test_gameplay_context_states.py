"""Provenance: HUD context never guesses a sprite type or game economy."""
from pathlib import Path
from types import SimpleNamespace
import sys

ROOT=Path(__file__).resolve().parents[2]
if str(ROOT/"tools") not in sys.path:
    sys.path.insert(0,str(ROOT/"tools"))

from sandbox_gameplay_context import describe_hud_context


def canvas_stub(*, map_loaded=True, selected="", original=None, objects=(),
                hit=None):
    return SimpleNamespace(
        has_map=lambda:map_loaded,
        select_id=lambda:selected,
        selected_original=lambda:original,
        history=SimpleNamespace(overlay=SimpleNamespace(objects=list(objects))),
        last_engine_pick=hit,
    )


def test_without_a_native_map_displays_no_fake_economy():
    state=describe_hud_context(canvas_stub(map_loaded=False),language="de")
    assert state.kind=="none"
    assert "Keine Originalkarte" in state.title
    assert not state.editable_overlay


def test_overlay_uses_only_real_working_copy_identity_and_allows_inspector():
    obj=SimpleNamespace(id="abcdef0123456789",group="tree_pine",frame=20,
                        x=397,y=431,team="rot")
    state=describe_hud_context(canvas_stub(selected=obj.id,objects=[obj]))
    assert state.kind=="overlay"
    assert state.editable_overlay
    assert "tree_pine/20" in state.brief
    assert "(397,431)" in state.brief
    assert "abcdef012345" in state.detail
    assert "Originalkarte nur lesen" in state.source


def test_deleted_overlay_cannot_remain_as_a_fake_selected_record():
    state=describe_hud_context(canvas_stub(selected="already-deleted",objects=[]))
    assert state.kind=="idle"
    assert not state.editable_overlay


def test_original_building_is_raw_read_only_not_an_inferred_building_name():
    b=SimpleNamespace(type_id=37,owner=4,uid=8088,x=353,y=415,
                      record_number=9)
    c=canvas_stub(original=("building",b.type_id,b))
    state=describe_hud_context(c)
    assert state.kind=="building"
    assert "Typ-ID 37" in state.brief
    assert "8088" in state.detail
    assert "1013" in state.source
    assert not state.editable_overlay
    assert "Haus" not in state.tooltip


def test_original_vegetation_keeps_raw_group_and_state_not_species():
    t=SimpleNamespace(raw_group=19,raw_variant=3,raw_state=7,
                      record_number=12,x=410,y=380)
    state=describe_hud_context(canvas_stub(original=("tree",19,t)),
                               language="en")
    assert state.kind=="tree"
    assert "Raw group 19" in state.brief
    assert "Variant 3" in state.detail
    assert "State 7" in state.detail
    assert "1014" in state.source
    assert "unclassified" in state.source
    assert not state.editable_overlay


def test_engine_pick_uses_paused_engine_command_provenance():
    hit=SimpleNamespace(kind="actor",
                        ref=SimpleNamespace(group="body_swordsman",frame=5),
                        x=312,y=324,source_file=108,source_frame=14)
    state=describe_hud_context(canvas_stub(hit=hit))
    assert state.kind=="engine"
    assert "body_swordsman/5" in state.brief
    assert "GM 108/14" in state.detail
    assert "Shader offen" in state.source


def test_tile_channel_values_are_raw_and_missing_is_explicit():
    c=canvas_stub()
    tile=(5,6,{3005:255,3004:0,3037:42})
    state=describe_hud_context(c,tile=tile)
    assert state.kind=="tile"
    assert "3005=255" in state.brief
    assert "3004=0" in state.detail
    assert "3037=42" in state.detail
    assert "kein Material geraten" in state.source
    missing=describe_hud_context(c,tile=(5,6,{}))
    assert "3005=–" in missing.brief
    assert not missing.editable_overlay



def test_action_projection_requires_native_map_and_valid_group():
    from sandbox_gameplay_context import gameplay_action_state
    history=SimpleNamespace(
        overlay=SimpleNamespace(serialize=lambda:{"objects":[]}),
        undo_stack=[],redo_stack=[],
    )
    canvas=SimpleNamespace(has_map=lambda:False,history=None,_placing=None)
    group=SimpleNamespace(currentText=lambda:"tree_pine")
    studio=SimpleNamespace(native_canvas=canvas,
                           native_hud=SimpleNamespace(group=group),
                           _saved_overlay={"objects":[]})
    state=gameplay_action_state(studio)
    assert not any((state.loaded,state.placing,state.can_place,
                    state.can_undo,state.can_redo,state.can_save))
    canvas.has_map=lambda:True
    canvas.history=history
    state=gameplay_action_state(studio)
    assert state.loaded and state.can_place
    assert not any((state.placing,state.can_undo,state.can_redo,state.can_save))
    group.currentText=lambda:"invalid group?"
    assert not gameplay_action_state(studio).can_place


def test_action_projection_tracks_dirty_history_and_active_placement():
    from sandbox_gameplay_context import gameplay_action_state
    payload={"objects":[]}
    history=SimpleNamespace(
        overlay=SimpleNamespace(serialize=lambda:dict(payload)),
        undo_stack=[],redo_stack=[],
    )
    canvas=SimpleNamespace(has_map=lambda:True,history=history,_placing=None)
    group=SimpleNamespace(currentText=lambda:"tile_castle")
    studio=SimpleNamespace(native_canvas=canvas,
                           native_hud=SimpleNamespace(group=group),
                           _saved_overlay={"objects":[]})
    history.undo_stack.append("one-step")
    payload["objects"]=[{"id":"test-asset"}]
    canvas._placing=("tile_castle",1193)
    state=gameplay_action_state(studio)
    assert state.loaded and state.placing and state.can_place
    assert state.can_undo and state.can_save
    assert not state.can_redo
    history.undo_stack.clear()
    history.redo_stack.append("undo-snapshot")
    state=gameplay_action_state(studio)
    assert not state.can_undo and state.can_redo
    studio._saved_overlay=None
    assert not gameplay_action_state(studio).can_save

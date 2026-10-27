from pathlib import Path

import pytest

from stronghold_europe_de.sandbox.scene_model import (
    SCHEMA, EditableScene, SceneError, SceneHistory, SpritePlacement,
    load_scene, save_scene, tile_anchor, tile_at,
)


@pytest.mark.parametrize("x,y", [(0, 0), (4, 7), (25, 25), (14, 0), (0, 15)])
def test_iso_projection_roundtrip(x, y):
    ax, ay = tile_anchor(x, y)
    assert tile_at(ax, ay) == (x, y)


def test_history_undo_redo_and_roundtrip(tmp_path):
    history = SceneHistory()
    uid = history.place("anim_armourer", 0, 4, 3)
    history.move(uid, 6, 5)
    assert (history.scene.objects[0].x, history.scene.objects[0].y) == (6, 5)
    history.undo()
    assert (history.scene.objects[0].x, history.scene.objects[0].y) == (4, 3)
    history.redo()
    assert (history.scene.objects[0].x, history.scene.objects[0].y) == (6, 5)
    path = tmp_path / "testscene.json"
    save_scene(path, history.scene)
    assert path.is_file()
    assert load_scene(path).serialize() == history.scene.serialize()
    history.delete(uid)
    assert history.scene.objects == []
    history.undo()
    assert history.scene.objects[0].id == uid


def test_reject_invalid_and_original_map_write(tmp_path):
    h = SceneHistory()
    with pytest.raises(SceneError):
        h.place("hello/world", 0, 1, 1)
    assert h.scene.objects == []
    with pytest.raises(SceneError):
        h.place("hello", 0, -1, 1)
    assert h.scene.objects == []
    with pytest.raises(SceneError):
        save_scene(tmp_path / "real.map", EditableScene())
    bad = EditableScene()
    bad.objects = [
        SpritePlacement("a" * 32, "x", 1, 0, 0),
        SpritePlacement("a" * 32, "y", 1, 1, 1),
    ]
    with pytest.raises(SceneError):
        bad.serialize()
    with pytest.raises(SceneError):
        EditableScene.deserialize({"schema": SCHEMA, "name": "x", "width": 1,
                                   "height": 1, "objects": [{"id": "a" * 32, "group": "x",
                                                            "frame": 1, "x": 0, "y": 0,
                                                            "unknown": "nope"}]})

def test_scene_size_limit_and_noop_inspector_update():
    with pytest.raises(SceneError):
        EditableScene(width=65).validate()
    history = SceneHistory()
    ident = history.place("unit", 3, 1, 2)
    before = len(history._undo)
    history.update(ident, x=1, y=2, frame=3, team="rot")
    assert len(history._undo) == before
    assert len(history.scene.objects) == 1

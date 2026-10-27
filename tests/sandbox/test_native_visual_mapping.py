from pathlib import Path
import json
import pytest
from stronghold_europe_de.sandbox.native_visual_mapping import (
    OriginalVisualMappings, VisualMappingError, load_mappings, save_mappings
)


def test_visual_mappings_versioned_atomic_roundtrip(tmp_path):
    path = tmp_path / "original-visuals.json"
    models = OriginalVisualMappings()
    models.assign("tree", 200, "tree_birch", 12)
    models.assign("building", 41, "tile_castle", 1193)
    save_mappings(path, models)
    assert load_mappings(path).serialize() == models.serialize()
    models.unassign("tree", 200)
    save_mappings(path, models)
    assert load_mappings(path).get("tree", 200) is None
    assert load_mappings(path).get("building", 41).frame == 1193


@pytest.mark.parametrize("kind,code,group,frame", [
    ("unit", 1, "tree_birch", 0), ("tree", -1, "x", 1),
    ("building", 0, "../bad", 1), ("tree", 200, "x", -2),
    ("tree", 200, "x", True), ("tree", 70000, "x", 0),
])
def test_reject_invalid_user_sprite_mappings(kind, code, group, frame):
    with pytest.raises(VisualMappingError):
        OriginalVisualMappings().assign(kind, code, group, frame)


def test_mapping_file_does_not_touch_game_map(tmp_path):
    original = tmp_path / "Antioch.map"
    original.write_bytes(b"real map bytes")
    overlay = tmp_path / "new" / "visuals.json"
    value = OriginalVisualMappings()
    value.assign("tree", 72, "tree_cactii", 3)
    save_mappings(overlay, value)
    assert original.read_bytes() == b"real map bytes"
    assert not list(tmp_path.rglob("*.tmp"))
    with pytest.raises(VisualMappingError):
        OriginalVisualMappings.deserialize({
            "schema": "stronghold-europe.sandbox.original-visuals.v1",
            "assignments": {"tree:200": {"group": "x", "frame": 1, "unknown": True}}
        })

"""Native original-map overlays are validated, isolated and undoable."""
from pathlib import Path
import pytest
from stronghold_europe_de.sandbox.native_overlay import (
    new_overlay, save_overlay, load_overlay, OverlayHistory,
)
from stronghold_europe_de.sandbox.scene_model import SceneError
from stronghold_europe_de.sandbox.map_sections import tile_index,load_original_buildings

MAPS=Path("E:/SSGameQA/Stronghold Crusader Definitive Edition_Data/StreamingAssets/Maps")


def test_overlay_roundtrip_original_untouched(tmp_path):
    native = tmp_path / "scene.map"
    native.write_bytes(b"real game data, never edited by the sandbox")
    original = native.read_bytes()
    hist = OverlayHistory(new_overlay(native))
    uid = hist.place("tile_castle",1193,400,400)
    hist.move(uid,401,400)
    hist.set_properties(uid, frame=15, team="blau")
    assert hist.overlay.objects[0].frame == 15
    hist.undo()
    assert hist.overlay.objects[0].frame == 1193
    hist.redo()
    target=tmp_path/"overlay.json"
    save_overlay(target,hist.overlay)
    loaded=load_overlay(target,native)
    assert loaded.serialize() == hist.overlay.serialize()
    hist.delete(uid)
    assert not hist.overlay.objects
    hist.undo()
    assert len(hist.overlay.objects)==1
    assert native.read_bytes()==original
    native.write_bytes(b"altered original")
    with pytest.raises(SceneError,match="anderen Kartenversion"):
        load_overlay(target,native)


def test_invalid_overlay_coords_and_ids(tmp_path):
    raw=tmp_path/"a.map"
    raw.write_bytes(b"source")
    hist=OverlayHistory(new_overlay(raw))
    with pytest.raises(SceneError):
        hist.place("group",1,0,0)
    with pytest.raises(SceneError):
        hist.place("!bad",1,400,400)
    assert not hist.overlay.objects
    uid=hist.place("unit",0,399,0)
    assert tile_index(399,0)==0
    with pytest.raises(SceneError):
        hist.move(uid,999,999)


@pytest.mark.skipif(not MAPS.is_dir(),reason="Real game not installed")
@pytest.mark.parametrize("name,min_count",[
    ("Antioch.map",20),
    ("A Mighty Oasis.map",5),
    ("Crusader Demo.map",40),
])
def test_native_real_building_positions_match_tile_indices(name,min_count):
    buildings=load_original_buildings(MAPS/name)
    assert len(buildings)>=min_count
    for b in buildings:
        assert tile_index(b.x,b.y)==b.native_tile_number
        assert 0 <= b.type_id <= 200
        assert b.footprint >=1

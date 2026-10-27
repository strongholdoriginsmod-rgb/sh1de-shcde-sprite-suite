"""Pure headless Sandbox model input-integrity and forward-data-loss guards.

No Qt, Tk, UI windows, installed game files or real user JSON.
"""
from copy import deepcopy
from uuid import uuid4

import pytest

from stronghold_europe_de.sandbox.scene_model import (
    EditableScene, SpritePlacement, SceneError
)
from stronghold_europe_de.sandbox.native_overlay import NativeOverlay

KEY="a"*32
SHA="b"*64


def clean_overlay():
    return NativeOverlay("safe.map",SHA,[])


@pytest.mark.parametrize("schema",["scene","overlay"])
def test_unknown_future_top_level_data_must_not_silently_disappear(schema):
    source=EditableScene() if schema=="scene" else clean_overlay()
    raw=source.serialize()
    raw["future_editor_payload"]={"do_not_erase":["important","user metadata"]}
    with pytest.raises(SceneError):
        (EditableScene if schema=="scene" else NativeOverlay).deserialize(raw)


@pytest.mark.parametrize("field",["frame","x","y"])
def test_boolean_integers_are_never_accepted_as_real_scene_coordinates(field):
    item=SpritePlacement(KEY,"tree_pine",20,1,1)
    setattr(item,field,True)
    with pytest.raises(SceneError):
        item.validate(26,26)


@pytest.mark.parametrize("field",["width","height"])
def test_boolean_dimensions_are_never_accepted_as_scene_size(field):
    scene=EditableScene()
    setattr(scene,field,True)
    with pytest.raises(SceneError):
        scene.validate()


@pytest.mark.parametrize("field",["frame","x","y"])
def test_boolean_numbers_not_accepted_as_original_map_coordinates(field):
    # (399,399), (True,399) and (399,True) are all inside the
    # arithmetic diamond, but bool is NOT a native map integer.
    item=SpritePlacement(KEY,"tree_pine",20,399,399)
    setattr(item,field,True)
    layer=clean_overlay()
    layer.objects=[item]
    with pytest.raises(SceneError):
        layer.validate()


@pytest.mark.parametrize("schema",["scene","overlay"])
def test_excessive_number_of_records_is_rejected_before_object_construction(schema):
    source=EditableScene() if schema=="scene" else clean_overlay()
    raw=source.serialize()
    # Sentinel entries would fail any record decoder. The limit should be
    # checked BEFORE iterating 10001 potentially hostile records.
    raw["objects"]=[None]*10_001
    with pytest.raises(SceneError,match="Zu viele"):
        (EditableScene if schema=="scene" else NativeOverlay).deserialize(raw)


@pytest.mark.parametrize("schema",["scene","overlay"])
def test_deserialize_valid_case_retains_exact_json_values(schema):
    source=EditableScene() if schema=="scene" else clean_overlay()
    source.objects=[SpritePlacement(KEY,"tree_pine",20,1,1)] if schema=="scene" else [
        SpritePlacement(KEY,"tree_pine",20,399,399)
    ]
    raw=source.serialize()
    restored=(EditableScene if schema=="scene" else NativeOverlay).deserialize(
        deepcopy(raw)
    )
    assert restored.serialize()==raw


def test_original_map_source_name_cannot_contain_path_components():
    layer=NativeOverlay("../someone-elses.map",SHA,[])
    with pytest.raises(SceneError):
        layer.validate()
    layer.source_name=r"C:\Games\other.map"
    with pytest.raises(SceneError):
        layer.validate()

"""Headless safety gates: Sandbox saves must not replace unrelated JSON files.

This suite deliberately uses temporary fake game maps and temporary app
settings. No original game .map, project settings, installed assets or GUI.
"""
from pathlib import Path
import hashlib
import json

import pytest

from stronghold_europe_de.sandbox.scene_model import (
    EditableScene, SceneError, SceneHistory, load_scene, save_scene
)
from stronghold_europe_de.sandbox.native_overlay import (
    OverlayHistory, load_overlay, new_overlay, save_overlay
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("save_kind", ["scene", "overlay"])
@pytest.mark.parametrize("payload", [
    {"schema":"sprite-suite.user-settings.v1","profiles":["original"]},
    {"schema":"stronghold-europe.sandbox.map-overlay.v1","untrusted":"invalid"},
    {"schema":"stronghold-europe.sandbox.scene.v2","untrusted":"invalid"},
])
def test_existing_unrelated_json_is_never_replaced(tmp_path,save_kind,payload):
    source=tmp_path/"fake-original.map"
    source.write_bytes(b"never mutate this fake original")
    original_sha=digest(source)
    settings=tmp_path/"important-existing.json"
    settings.write_text(json.dumps(payload),encoding="utf-8")
    settings_sha=digest(settings)
    with pytest.raises(SceneError):
        if save_kind=="scene":
            save_scene(settings,EditableScene())
        else:
            save_overlay(settings,OverlayHistory(new_overlay(source)).overlay)
    assert digest(settings)==settings_sha
    assert digest(source)==original_sha


@pytest.mark.parametrize("kind",["scene","overlay"])
def test_existing_malformed_json_is_not_silently_repaired_on_save(tmp_path,kind):
    source=tmp_path/"original.map"
    source.write_bytes(b"source")
    corrupt=tmp_path/"corrupt.json"
    corrupt.write_bytes(b"{not valid JSON, preserve for recovery")
    before=digest(corrupt)
    with pytest.raises(SceneError):
        if kind=="scene":
            save_scene(corrupt,EditableScene())
        else:
            save_overlay(corrupt,new_overlay(source))
    assert digest(corrupt)==before


def test_existing_valid_scene_can_be_explicitly_saved_again(tmp_path):
    path=tmp_path/"scene.json"
    original=EditableScene()
    save_scene(path,original)
    after=SceneHistory(original)
    after.place("tree_pine",20,3,4)
    save_scene(path,after.scene)
    assert load_scene(path).serialize()==after.scene.serialize()


def test_overlay_cannot_replace_sidecar_for_different_map_version(tmp_path):
    one=tmp_path/"one.map"
    two=tmp_path/"two.map"
    one.write_bytes(b"map A bytes")
    two.write_bytes(b"map B bytes")
    path=tmp_path/"old.overlay.json"
    save_overlay(path,new_overlay(one))
    before=digest(path)
    with pytest.raises(SceneError):
        save_overlay(path,new_overlay(two))
    assert digest(path)==before


def test_matching_overlay_can_be_saved_again_without_touching_map(tmp_path):
    source=tmp_path/"fake-game.map"
    source.write_bytes(b"original bytes")
    path=tmp_path/"working.overlay.json"
    history=OverlayHistory(new_overlay(source))
    original_sha=digest(source)
    save_overlay(path,history.overlay)
    history.place("tree_pine",20,397,431)
    save_overlay(path,history.overlay)
    assert load_overlay(path,source).serialize()==history.overlay.serialize()
    assert digest(source)==original_sha


@pytest.mark.parametrize("kind",["scene","overlay"])
def test_original_map_extension_cannot_be_written(tmp_path,kind):
    target=tmp_path/"actual-source.map"
    target.write_bytes(b"immutable-map")
    before=digest(target)
    with pytest.raises(SceneError):
        if kind=="scene":
            save_scene(target,EditableScene())
        else:
            save_overlay(target,new_overlay(target))
    assert digest(target)==before



@pytest.mark.parametrize("kind",["scene","overlay"])
def test_failed_atomic_replace_leaves_old_saved_data_and_no_temp_files(
    tmp_path,monkeypatch,kind
):
    """An I/O failure after writing the temp file may not destroy the old save."""
    import os
    source=tmp_path/"fake.map"
    source.write_bytes(b"protected original bytes")
    target=tmp_path/("active.scene.json" if kind=="scene" else "active.overlay.json")
    if kind=="scene":
        before=EditableScene()
        save_scene(target,before)
        updated=SceneHistory(before)
        updated.place("tree_pine",20,2,3)
        save_again=lambda:save_scene(target,updated.scene)
    else:
        before=new_overlay(source)
        save_overlay(target,before)
        updated=OverlayHistory(before)
        updated.place("tree_pine",20,399,399)
        save_again=lambda:save_overlay(target,updated.overlay)
    original_target=digest(target)
    original_map=digest(source)
    first_names={p.name for p in tmp_path.iterdir()}
    def deny_swap(_src,_target):
        raise PermissionError("simulated file system refusing atomic replacement")
    monkeypatch.setattr(os,"replace",deny_swap)
    with pytest.raises(PermissionError,match="simulated"):
        save_again()
    assert digest(target)==original_target
    assert digest(source)==original_map
    assert {p.name for p in tmp_path.iterdir()}==first_names


@pytest.mark.parametrize("kind",["scene","overlay"])
def test_corrupt_save_target_is_left_unmodified_even_if_working_data_valid(
    tmp_path,kind
):
    """Accidentally selecting an existing malformed JSON must fail closed."""
    p=tmp_path/"do-not-overwrite.json"
    p.write_text("not-json\n",encoding="utf-8")
    before=digest(p)
    with pytest.raises(SceneError,match="unverändert"):
        if kind=="scene":
            save_scene(p,EditableScene())
        else:
            source=tmp_path/"fake.map"
            source.write_bytes(b"original")
            save_overlay(p,new_overlay(source))
    assert digest(p)==before

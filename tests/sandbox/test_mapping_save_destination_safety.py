"""Headless isolation for every persistent Sandbox mapping sidecar.

Covers visual, 3005 terrain, 3037 surface and XAML HUD binding writers.
No Qt/Tk, original game assets, release output or user settings touched.
"""
from pathlib import Path
import hashlib
import json

import pytest

from stronghold_europe_de.sandbox.native_visual_mapping import (
    OriginalVisualMappings, VisualMappingError, load_mappings, save_mappings,
)
from stronghold_europe_de.sandbox.native_terrain_mapping import (
    TerrainTestMappings, TerrainMappingError,
    load_terrain_tests, save_terrain_tests,
)
from stronghold_europe_de.sandbox.native_surface_mapping import (
    SurfaceTestMappings, load_surface_tests, save_surface_tests,
)
from stronghold_europe_de.sandbox.hud_command_bindings import (
    HudCommandBindings, load_bindings, save_bindings,
)

SHA_A="a"*64
SHA_B="b"*64
ALLOWED={"BUILD_TREE"}


def build(kind,sha=SHA_A):
    if kind=="visual":
        model=OriginalVisualMappings()
        model.assign("tree",12,"tree_pine",20)
        return model
    if kind=="terrain":
        model=TerrainTestMappings(sha)
        model.assign(16,"tree_pine",20)
        return model
    if kind=="surface":
        model=SurfaceTestMappings(sha)
        model.assign(16,"tree_pine",20)
        return model
    if kind=="hud":
        model=HudCommandBindings(allowed=ALLOWED)
        model.bind("BUILD_TREE","tree_pine",20)
        return model
    raise AssertionError(kind)


def save(kind,path,model):
    return {
        "visual":save_mappings,"terrain":save_terrain_tests,
        "surface":save_surface_tests,"hud":save_bindings,
    }[kind](path,model)


def deserialize(kind,data,sha=SHA_A):
    if kind=="visual":
        return OriginalVisualMappings.deserialize(data)
    if kind=="terrain":
        return TerrainTestMappings.deserialize(data,sha)
    if kind=="surface":
        return SurfaceTestMappings.deserialize(data,sha)
    if kind=="hud":
        return HudCommandBindings.deserialize(data,ALLOWED)
    raise AssertionError(kind)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("kind",["visual","terrain","surface","hud"])
def test_unrelated_existing_json_must_not_be_overwritten(tmp_path,kind):
    target=tmp_path/"critical-other-data.json"
    target.write_text(json.dumps({
        "schema":"sprite-suite.catalog-index.v1",
        "important":["user","sprite","metadata"],
    }),encoding="utf8")
    before=sha(target)
    with pytest.raises(ValueError):
        save(kind,target,build(kind))
    assert sha(target)==before


@pytest.mark.parametrize("kind",["visual","terrain","surface","hud"])
def test_corrupt_existing_mapping_file_is_preserved(tmp_path,kind):
    target=tmp_path/"existing.json"
    target.write_bytes(b"{invalid but precious original config")
    before=sha(target)
    with pytest.raises(ValueError):
        save(kind,target,build(kind))
    assert sha(target)==before


@pytest.mark.parametrize("kind",["visual","terrain","surface","hud"])
def test_unknown_future_metadata_is_not_silently_discarded(kind):
    data=build(kind).serialize()
    data["future_extension"]={"important":["not","to","delete"]}
    with pytest.raises(ValueError):
        deserialize(kind,data)


@pytest.mark.parametrize("kind",["visual","terrain","surface","hud"])
def test_matching_sidecar_can_still_be_explicitly_updated(tmp_path,kind):
    target=tmp_path/f"{kind}.json"
    model=build(kind)
    save(kind,target,model)
    initial=sha(target)
    if kind=="visual":
        model.assign("building",13,"tile_castle",2)
    elif kind in ("terrain","surface"):
        model.assign(17,"tile_castle",2)
    else:
        model.bind("BUILD_TREE","tile_castle",2)
    save(kind,target,model)
    assert sha(target)!=initial
    restored=deserialize(kind,json.loads(target.read_text(encoding="utf8")))
    assert restored.serialize()==model.serialize()


@pytest.mark.parametrize("kind",["terrain","surface"])
def test_another_map_version_cannot_replace_mapping(tmp_path,kind):
    target=tmp_path/"map-specific.json"
    save(kind,target,build(kind,SHA_A))
    before=sha(target)
    with pytest.raises(ValueError):
        save(kind,target,build(kind,SHA_B))
    assert sha(target)==before


@pytest.mark.parametrize("kind",["visual","terrain","surface","hud"])
def test_original_map_extension_is_forbidden(tmp_path,kind):
    target=tmp_path/"real-game.map"
    target.write_bytes(b"protected game file")
    before=sha(target)
    with pytest.raises(ValueError):
        save(kind,target,build(kind))
    assert sha(target)==before



@pytest.mark.parametrize("kind",["visual","terrain","surface","hud"])
def test_failed_atomic_mapping_swap_keeps_saved_sidecar_and_cleans_temp(
    tmp_path,monkeypatch,kind
):
    """No mapping writer may lose its last good data after a failed rename."""
    import os
    target=tmp_path/(kind+".json")
    model=build(kind)
    save(kind,target,model)
    original=sha(target)
    before={p.name for p in tmp_path.iterdir()}
    if kind=="visual":
        model.assign("building",17,"tile_castle",2)
    elif kind in ("terrain","surface"):
        model.assign(17,"tile_castle",2)
    else:
        model.bind("BUILD_TREE","tile_castle",2)
    def deny(_source,_target):
        raise PermissionError("simulated atomic-swap failure")
    monkeypatch.setattr(os,"replace",deny)
    with pytest.raises(PermissionError,match="simulated"):
        save(kind,target,model)
    assert sha(target)==original
    assert {p.name for p in tmp_path.iterdir()}==before


@pytest.mark.parametrize("kind",["visual","terrain","surface","hud"])
def test_foreign_symlink_save_target_is_never_followed_if_supported(
    tmp_path,kind
):
    destination=tmp_path/"important.json"
    destination.write_text('{"schema":"user-important-settings.v1"}',encoding="utf8")
    alias=tmp_path/(kind+".json")
    try:
        alias.symlink_to(destination)
    except (OSError,NotImplementedError):
        pytest.skip("Windows account disallows symlink creation")
    before=sha(destination)
    with pytest.raises(ValueError):
        save(kind,alias,build(kind))
    assert sha(destination)==before
    assert alias.is_symlink()

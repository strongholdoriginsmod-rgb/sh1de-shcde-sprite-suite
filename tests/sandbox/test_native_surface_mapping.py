"""SHCDE texture channel 3037 is independent of height 3005."""
from pathlib import Path
import json
import sys
import pytest

from stronghold_europe_de.sandbox.native_surface_mapping import (
    SurfaceTestMappings, load_surface_tests, save_surface_tests,
    provisional_surface_material, SURFACE_SCHEMA,
)
from stronghold_europe_de.sandbox.native_terrain_mapping import TerrainMappingError
from stronghold_europe_de.sandbox.map_sections import load_native_tile_channels

MAPS = Path("E:/SSGameQA/Stronghold Crusader Definitive Edition_Data/StreamingAssets/Maps")
HASH = "a"*64


def test_surface_mapping_schema_and_legacy_safety(tmp_path):
    game_map=tmp_path/"original.map"
    game_map.write_bytes(b"game data immutable")
    mapping=SurfaceTestMappings(HASH)
    mapping.assign(16,"tile_land8",12)
    mapping.assign(2,"tile_land_and_stones",2)
    dest=tmp_path/"surface-tests"/"test.json"
    save_surface_tests(dest,mapping)
    raw=json.loads(dest.read_text(encoding="utf-8"))
    assert raw["schema"]==SURFACE_SCHEMA and raw["section"]==3037
    assert load_surface_tests(dest,HASH).serialize()==raw
    assert load_surface_tests(dest.with_name("missing.json"),HASH).assignments == {}
    assert game_map.read_bytes()==b"game data immutable"
    with pytest.raises(TerrainMappingError, match="anderen Kartenversion"):
        load_surface_tests(dest,"b"*64)
    raw["section"]=3005
    dest.write_text(json.dumps(raw),encoding="utf-8")
    with pytest.raises(TerrainMappingError):
        load_surface_tests(dest,HASH)
    assert game_map.read_bytes()==b"game data immutable"


@pytest.mark.skipif(not MAPS.is_dir(),reason="Game maps not installed")
@pytest.mark.parametrize("name",["Antioch.map","Crusader Demo.map","A Mighty Oasis.map"])
def test_independent_height_and_surface_bytes(name):
    d=load_native_tile_channels(MAPS/name).channels
    assert len(d[3037])==320800
    assert len(d[3005])==320800
    surface=set(d[3037])
    assert {0,1,2,16,128}.issubset(surface)
    # We can find multiple heights under one actual texture class.
    assert len({d[3005][i] for i,v in enumerate(d[3037]) if v==0})>1
    assert provisional_surface_material(16)=="grass"
    assert provisional_surface_material(8)=="rock"
    assert provisional_surface_material(2)=="shore"


pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication, QMessageBox
TOOLS=str(Path(__file__).resolve().parents[2]/"tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)
import sandbox_studio


@pytest.mark.skipif(not MAPS.is_dir(),reason="Game maps not installed")
def test_studio_assign_3037_without_mutating_heights_and_legacy(tmp_path,monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM","offscreen")
    monkeypatch.setattr(sandbox_studio,"ROOT",tmp_path)
    app=QApplication.instance() or QApplication([])
    studio=sandbox_studio.SandboxStudio(tmp_path)
    path=MAPS/"Antioch.map"
    first=path.stat()
    try:
        assert studio.open_map(path)
        canvas=studio.native_canvas
        assert canvas.select_native(400,400)
        surface=studio.native_inspector._surface_code
        height=studio.native_inspector._terrain_code
        assert surface == canvas._channels.at(400,400)[3037]
        assert height == canvas._channels.at(400,400)[3005]
        assert studio.native_inspector.assign_surface.isEnabled()
        assert f"3037={surface}" in studio.native_inspector.surface_info.text()

        studio.asset_preview.group.setCurrentText("tile_land8")
        studio.asset_preview.frame.setValue(12)
        assert studio.assign_surface_test()
        assert f"TEST tile_land8/12" in studio.native_inspector.surface_info.text()
        assert load_surface_tests(studio._surface_test_path,canvas.history.overlay.source_sha256).get(surface).frame==12
        visited=[]
        canvas._load_texture=lambda group,frame: visited.append((group,frame)) or None
        canvas._get_terrain_texture(height,400,400,0,surface)
        assert visited==[("tile_land8",12)]
        # Original height-based experiments take precedence without being
        # silently deleted or transformed into texture mappings.
        canvas.terrain_tests.assign(height,"tile_castle",21)
        canvas._get_terrain_texture(height,400,400,0,surface)
        assert visited[-1]==("tile_castle",21)
        canvas.terrain_tests.unassign(height)
        assert studio.clear_surface_test()
        assert canvas.surface_tests.get(surface) is None
        assert "Näherung:" in studio.native_inspector.surface_info.text()
        # Reopen exact map keeps its own dedicated texture test file.
        assert studio.open_map(path)
        assert studio.native_canvas.surface_tests.get(surface) is None
        assert (path.stat().st_size,path.stat().st_mtime_ns)==(first.st_size,first.st_mtime_ns)
    finally:
        studio.native_canvas._poll.stop()
        studio._saved_scene=studio.board.history.scene.serialize()
        if studio.native_canvas.has_map():
            studio._saved_overlay=studio.native_canvas.history.overlay.serialize()
        studio.close()


@pytest.mark.skipif(not MAPS.is_dir(),reason="Game maps not installed")
def test_surface_corrupt_recovery_preserves_original_file(tmp_path,monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM","offscreen")
    monkeypatch.setattr(sandbox_studio,"ROOT",tmp_path)
    app=QApplication.instance() or QApplication([])
    studio=sandbox_studio.SandboxStudio(tmp_path)
    try:
        path=MAPS/"Antioch.map"
        # First open resolves the correct source digest without modifying it.
        assert studio.open_map(path)
        dest=studio._surface_test_path
        dest.parent.mkdir(parents=True,exist_ok=True)
        dest.write_bytes(b"invalid original JSON")
        preserved=dest.read_bytes()
        messages=[]
        monkeypatch.setattr(QMessageBox,"warning",
                            lambda *args: messages.append(args[2]) or QMessageBox.StandardButton.Ok)
        assert studio.open_map(path)
        assert messages and studio._surface_test_path != dest
        assert dest.read_bytes()==preserved
        assert studio.native_canvas.select_native(400,400)
        studio.asset_preview.group.setCurrentText("tile_land8")
        studio.asset_preview.frame.setValue(1)
        assert studio.assign_surface_test()
        assert dest.read_bytes()==preserved
        assert studio.open_map(path)
        assert studio.native_canvas.surface_tests.get(
            studio.native_canvas._channels.at(400,400)[3037]) is not None
    finally:
        studio.native_canvas._poll.stop()
        studio._saved_scene=studio.board.history.scene.serialize()
        if studio.native_canvas.has_map():
            studio._saved_overlay=studio.native_canvas.history.overlay.serialize()
        studio.close()

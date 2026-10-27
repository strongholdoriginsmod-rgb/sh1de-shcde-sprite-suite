"""Safe, map-version-specific experimentation with original channel 3005."""
from pathlib import Path
import json
import sys

import pytest
from stronghold_europe_de.sandbox.native_terrain_mapping import (
    TerrainMappingError, TerrainTestMappings, load_terrain_tests, save_terrain_tests,
)

HASH_A = "a" * 64
HASH_B = "b" * 64


def test_terrain_mapping_roundtrip_and_no_game_modification(tmp_path):
    game_map = tmp_path / "Antioch.map"
    game_map.write_bytes(b"original game data (must not change)")
    target = tmp_path / "terrain" / "Antioch.terrain.json"
    data = TerrainTestMappings(HASH_A)
    data.assign(8, "tile_land8", 27)
    data.assign(0, "tile_sea8", 2)
    save_terrain_tests(target, data)
    assert load_terrain_tests(target, HASH_A).serialize() == data.serialize()
    assert game_map.read_bytes() == b"original game data (must not change)"
    assert load_terrain_tests(target.with_name("unmapped.json"), HASH_A).assignments == {}
    with pytest.raises(TerrainMappingError, match="anderen Kartenversion"):
        load_terrain_tests(target, HASH_B)
    data.unassign(8)
    save_terrain_tests(target, data)
    assert load_terrain_tests(target, HASH_A).get(8) is None
    assert load_terrain_tests(target, HASH_A).get(0).frame == 2
    assert not list(tmp_path.rglob("*.tmp"))


@pytest.mark.parametrize("code,group,frame", [
    (-1, "tile_land8", 0), (256, "tile_land8", 0),
    (8.0, "tile_land8", 0), (True, "tile_land8", 0),
    (8, "../evil", 0), (8, "tile_land8", -1),
    (8, "tile_land8", True),
])
def test_reject_invalid_terrain_mapping(code, group, frame):
    data = TerrainTestMappings(HASH_A)
    with pytest.raises(TerrainMappingError):
        data.assign(code, group, frame)
    assert data.assignments == {}


def test_invalid_mapping_payload_rejected(tmp_path):
    path = tmp_path / "terrain.json"
    sample = TerrainTestMappings(HASH_A)
    sample.assign(8, "tile_land8", 1)
    base = sample.serialize()
    for value in [
        {"08": {"group": "x", "frame": 0}},
        {"256": {"group": "x", "frame": 0}},
        {"-1": {"group": "x", "frame": 0}},
        {"8": {"group": "x", "frame": 0, "extra": "x"}},
        {"8": {"group": "../game", "frame": 0}},
    ]:
        payload = dict(base, assignments=value)
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(TerrainMappingError):
            load_terrain_tests(path, HASH_A)


def test_empty_or_wrong_hash_and_invalid_json_are_rejected(tmp_path):
    path = tmp_path / "bad.json"
    with pytest.raises(TerrainMappingError):
        TerrainTestMappings("not a hash").validate()
    path.write_text("{ broken")
    with pytest.raises(TerrainMappingError):
        load_terrain_tests(path, HASH_A)
    with pytest.raises(TerrainMappingError):
        TerrainTestMappings.deserialize({}, HASH_A)


pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtGui import QPixmap

TOOLS = str(Path(__file__).resolve().parents[2] / "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)
import sandbox_studio
from sandbox_native_canvas import NativeMapCanvas, CHUNK_W, CHUNK_H
from stronghold_europe_de.sandbox.native_overlay import new_overlay

MAP = Path("E:/SSGameQA/Stronghold Crusader Definitive Edition_Data/StreamingAssets/Maps/Antioch.map")


@pytest.mark.skipif(not MAP.is_file(), reason="Real game map not installed")
def test_original_tile_click_assign_reload_and_reset(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setattr(sandbox_studio, "ROOT", tmp_path)
    app = QApplication.instance() or QApplication([])
    studio = sandbox_studio.SandboxStudio(tmp_path)
    try:
        assert studio.open_map(MAP)
        canvas = studio.native_canvas
        assert canvas.has_map()
        assert canvas.select_native(400, 400)
        code = studio.native_inspector._terrain_code
        assert code == canvas._channels.at(400, 400)[3005]
        assert studio.native_inspector.assign_terrain.isEnabled()
        assert 'Näherungsdarstellung' in studio.native_inspector.terrain_info.text()
        assert str(canvas._channels.channels[3005].count(code)) in (
            studio.native_inspector.terrain_info.text().replace(",", "")
        )

        studio.asset_preview.group.setCurrentText("tile_land8")
        studio.asset_preview.frame.setValue(1)
        original_bytes = MAP.read_bytes()
        canvas._terrain_chunks[(0, 0)] = QPixmap(CHUNK_W, CHUNK_H)
        assert studio.assign_terrain_test()
        assert not canvas._terrain_chunks
        assert canvas.terrain_tests.get(code).group == "tile_land8"
        assert canvas.terrain_tests.get(code).frame == 1
        assert 'TEST: tile_land8/1' in studio.native_inspector.terrain_info.text()
        assert load_terrain_tests(studio._terrain_test_path,
                                  canvas.history.overlay.source_sha256).get(code).frame == 1
        visited = []
        cached = canvas._load_texture
        canvas._load_texture = lambda group, frame: visited.append((group, frame)) or None
        assert canvas._get_terrain_texture(code, 400, 400) is None
        assert visited == [("tile_land8", 1)]
        canvas._load_texture = cached

        # Save signal reloads terrain even for a custom non-default texture.
        studio.asset_preview.group.setCurrentText("tile_castle")
        studio.asset_preview.frame.setValue(2)
        assert studio.assign_terrain_test()
        refresh = []
        canvas.refresh_terrain_assets = lambda: refresh.append(True)
        studio._update_map_asset("tile_castle", "tile_castle-2")
        assert refresh
        assert studio.clear_terrain_test()
        assert canvas.terrain_tests.get(code) is None
        assert 'Näherungsdarstellung' in studio.native_inspector.terrain_info.text()
        assert MAP.read_bytes() == original_bytes
    finally:
        studio.native_canvas._poll.stop()
        studio._saved_scene = studio.board.history.scene.serialize()
        if studio.native_canvas.has_map():
            studio._saved_overlay = studio.native_canvas.history.overlay.serialize()
        studio.close()


@pytest.mark.skipif(not MAP.is_file(), reason="Real game map not installed")
def test_bad_terrain_mapping_preserved_and_recovery_separate(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setattr(sandbox_studio, "ROOT", tmp_path)
    original_overlay = new_overlay(MAP)
    target = tmp_path / "sandbox" / "terrain-mappings" / (
        f"{MAP.stem}-{original_overlay.source_sha256[:12]}.terrain.json"
    )
    target.parent.mkdir(parents=True)
    target.write_bytes(b"garbled terrain test JSON")
    preserved = target.read_bytes()
    messages = []
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *args: messages.append(args[2]) or QMessageBox.StandardButton.Ok)
    app = QApplication.instance() or QApplication([])
    studio = sandbox_studio.SandboxStudio(tmp_path)
    try:
        assert studio.open_map(MAP)
        assert studio.native_canvas.has_map()
        assert messages
        assert target.read_bytes() == preserved
        assert studio._terrain_test_path != target
        assert studio.native_canvas.select_native(400, 400)
        studio.asset_preview.group.setCurrentText("tile_land8")
        studio.asset_preview.frame.setValue(2)
        assert studio.assign_terrain_test()
        assert target.read_bytes() == preserved
        assert studio._terrain_test_path.exists()
        assert studio.open_map(MAP)
        assert studio.native_canvas.terrain_tests.get(
            studio.native_canvas._channels.at(400,400)[3005]) is not None
    finally:
        studio.native_canvas._poll.stop()
        studio._saved_scene = studio.board.history.scene.serialize()
        if studio.native_canvas.has_map():
            studio._saved_overlay = studio.native_canvas.history.overlay.serialize()
        studio.close()

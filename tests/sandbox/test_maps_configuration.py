"""Portable game-folder selection for the *normal* Sprite Suite startup."""
from pathlib import Path

from stronghold_europe_de.sandbox.maps_configuration import configured_map_root


def test_missing_or_invalid_game_config_has_no_qa_disk_fallback(tmp_path):
    assert configured_map_root(tmp_path) == tmp_path
    config=tmp_path/"config"/"installations.local.toml"
    config.parent.mkdir()
    config.write_text("garbled +++ toml",encoding="utf-8")
    assert configured_map_root(tmp_path) == tmp_path
    config.write_text('[target]\ngame_dir = "E:/definitely-no-such-local-game-directory"\n',
                      encoding="utf-8")
    assert configured_map_root(tmp_path) == tmp_path


def test_valid_configured_game_maps_are_selected_read_only(tmp_path):
    source=tmp_path/"my-game"
    maps=source/"Stronghold Crusader Definitive Edition_Data"/"StreamingAssets"/"Maps"
    maps.mkdir(parents=True)
    fake=maps/"Example.map"
    fake.write_bytes(b"game map untouched")
    cfg=tmp_path/"config"/"installations.local.toml"
    cfg.parent.mkdir()
    cfg.write_text('[target]\ngame_dir = "'+source.as_posix()+'"\n',encoding="utf-8")
    assert configured_map_root(tmp_path) == source
    assert fake.read_bytes() == b"game map untouched"
    assert configured_map_root(source) == source  # missing config falls back there


def test_explicit_maps_directory_can_be_configured(tmp_path):
    maps=tmp_path/"Maps"
    maps.mkdir()
    cfg=tmp_path/"config"/"installations.local.toml"
    cfg.parent.mkdir()
    cfg.write_text('[target]\ngame_dir = "'+maps.as_posix()+'"\n',encoding="utf-8")
    assert configured_map_root(tmp_path)==maps


def test_source_without_a_maps_directory_is_not_a_valid_game_installation(tmp_path):
    game=tmp_path/"invalid-game"
    game.mkdir()
    cfg=tmp_path/"config"/"installations.local.toml"
    cfg.parent.mkdir()
    cfg.write_text('[target]\ngame_dir = "'+game.as_posix()+'"\n',encoding="utf-8")
    assert configured_map_root(tmp_path)==tmp_path

def test_selected_map_folder_persists_across_normal_suite_starts(tmp_path):
    from stronghold_europe_de.sandbox.maps_configuration import (
        SCHEMA, save_maps_root, usable_maps_root
    )
    import json
    chosen=tmp_path/"My Saved Original Maps"
    chosen.mkdir()
    path=chosen/"Antioch.map"
    path.write_bytes(b"private game map remains unchanged")
    assert usable_maps_root(chosen)
    result=save_maps_root(tmp_path,chosen)
    assert result==chosen.resolve()
    settings=tmp_path/"config"/"sandbox-maps.local.json"
    payload=json.loads(settings.read_text(encoding="utf-8"))
    assert payload["schema"]==SCHEMA
    assert payload["maps_root"]==str(chosen.resolve())
    assert configured_map_root(tmp_path)==chosen.resolve()
    assert path.read_bytes()==b"private game map remains unchanged"
    assert not list((tmp_path/"config").glob("*.tmp"))


def test_invalid_folder_does_not_replace_previous_working_selection(tmp_path):
    from stronghold_europe_de.sandbox.maps_configuration import save_maps_root
    import pytest
    maps=tmp_path/"Maps"
    maps.mkdir()
    (maps/"ready.map").write_bytes(b"source")
    save_maps_root(tmp_path,maps)
    settings=tmp_path/"config"/"sandbox-maps.local.json"
    before=settings.read_bytes()
    invalid=tmp_path/"empty"
    invalid.mkdir()
    with pytest.raises(ValueError,match="keine SHCDE-Originalkarten"):
        save_maps_root(tmp_path,invalid)
    assert settings.read_bytes()==before
    assert configured_map_root(tmp_path)==maps


def test_corrupted_saved_folder_falls_back_to_target_game_config(tmp_path):
    maps=tmp_path/"Alternate Maps"
    maps.mkdir()
    (maps/"case.map").write_bytes(b"case")
    cfg=tmp_path/"config"
    cfg.mkdir()
    (cfg/"sandbox-maps.local.json").write_bytes(b"not json")
    (cfg/"installations.local.toml").write_text(
        '[target]\ngame_dir = "'+maps.as_posix()+'"\n',encoding="utf-8"
    )
    assert configured_map_root(tmp_path)==maps


def test_map_importer_accepts_custom_named_directory_with_map_files(tmp_path,monkeypatch):
    from stronghold_europe_de.sandbox import map_importer
    maps=tmp_path/"Stronghold Custom Maps"
    maps.mkdir()
    paths=[maps/"Beta.map",maps/"Alpha.map"]
    for path in paths:path.write_bytes(b"test only")
    seen=[]
    def inspect(path):
        seen.append(path.name)
        return path.name
    monkeypatch.setattr(map_importer,"inspect_map",inspect)
    assert map_importer.find_maps(maps)==["Alpha.map","Beta.map"]
    assert seen==["Alpha.map","Beta.map"]

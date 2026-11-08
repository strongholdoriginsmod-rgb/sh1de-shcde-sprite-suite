"""Read-only environment discovery with synthetic Steam libraries."""
import importlib.util
import json
from pathlib import Path

MODULE = Path(__file__).resolve().parents[2] / "tools" / "suite_environment_discovery.py"
spec = importlib.util.spec_from_file_location("suite_environment_discovery", MODULE)
discovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(discovery)


def game(library, kind):
    name = discovery.GAME_NAMES[kind][0]
    root = library / "steamapps" / "common" / name
    data = root / discovery.GAME_DATA[kind]
    data.mkdir(parents=True)
    (data / "resources.assets").write_bytes(b"fake-unity-file")
    return root


def test_steam_library_discovery_and_extender_component_identity(tmp_path):
    steam = tmp_path / "Steam"
    library = tmp_path / "Library"
    (steam / "steamapps").mkdir(parents=True)
    (steam / "steamapps" / "libraryfolders.vdf").write_text(
        '"libraryfolders"\n{\n "1" { "path" "' +
        str(library).replace("\\", "\\\\") + '" }\n}', encoding="utf-8")
    sh1 = game(library, "sh1de")
    crusader = game(library, "shcde")
    ext = crusader / "BepInEx" / "plugins" / "000shcdese"
    ext.mkdir(parents=True)
    (ext / "SHCDESE.dll").write_bytes(b"test")
    (ext / "info.json").write_text(json.dumps({
        "GUID": "000shcdese", "Version": "2.1.1"
    }), encoding="utf-8")
    (ext / "APIShared.dll").write_bytes(b"api")
    (ext / "Serp.baseline.dll").write_bytes(b"serp")
    env = {"SPRITESUITE_STEAM_ROOT": str(steam)}
    result = discovery.discover(tmp_path, environment=env)
    assert result["suggestions"]["sh1de"] == str(sh1)
    assert result["suggestions"]["shcde"] == str(crusader)
    row = next(g for g in result["games"] if g["kind"] == "shcde")
    assert row["script_extender"]["declared_version"] == "2.1.1"
    assert row["script_extender"]["installed"]
    assert len(row["components"]["APIShared"]) == 1
    assert len(row["components"]["Serp"]) == 1
    assert not row["runtime_compatibility_verified"]
    assert not result["executed_discovered_binaries"]
    assert not result["modified_game_or_config"]


def test_ambiguity_does_not_choose_wrong_game(tmp_path):
    roots = [game(tmp_path / str(n), "shcde") for n in (1, 2)]
    r = discovery.discover(tmp_path, roots=roots, environment={})
    assert len([g for g in r["games"] if g["kind"] == "shcde"]) == 2
    assert r["suggestions"]["shcde"] is None
    assert all(g["script_extender"]["installed"] is False for g in r["games"])


def test_untrusted_metadata_never_attests_runtime(tmp_path):
    sh = game(tmp_path, "shcde")
    ext = sh / "BepInEx" / "plugins" / "000shcdese"
    ext.mkdir(parents=True)
    (ext / "SHCDESE.dll").write_bytes(b"test")
    (ext / "info.json").write_text('{"GUID": "other", "Version": "99"}')
    snapshot = (ext / "info.json").read_bytes()
    result = discovery.discover(tmp_path, roots=[sh], environment={})
    row = result["games"][0]
    assert row["script_extender"]["declared_version"] is None
    assert not row["script_extender"]["abi_verified"]
    assert (ext / "info.json").read_bytes() == snapshot


def test_symlink_game_root_is_not_followed(tmp_path):
    import os
    import pytest
    original = game(tmp_path, "shcde")
    link = tmp_path / "link"
    try:
        os.symlink(original, link, target_is_directory=True)
    except (OSError, NotImplementedError) as error:
        pytest.skip(f"Symlinks unavailable: {error}")
    result = discovery.discover(tmp_path, roots=[link], environment={})
    assert not result["games"]

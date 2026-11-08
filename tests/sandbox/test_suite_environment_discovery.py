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



def test_pinned_runtime_byte_evidence_and_apishared_version_gate(tmp_path):
    from hashlib import sha256
    crusader = game(tmp_path / "games", "shcde")
    ext = crusader / "BepInEx/plugins/000shcdese"
    ext.mkdir(parents=True)
    payload = b"synthetic-not-an-assembly"
    (ext / "SHCDESE.dll").write_bytes(payload)
    (ext / "info.json").write_text(
        json.dumps({"GUID": "000shcdese", "Version": "2.11.0"}), encoding="utf-8"
    )
    api = crusader / "BepInEx/plugins/APIShared_Serp"
    api.mkdir()
    (api / "APIShared.dll").write_bytes(b"fake-api")
    (api / "APIShared.Content.dll").write_bytes(b"fake-content")
    (api / "info.json").write_text(
        json.dumps({"GUID": "APIShared_Serp", "Version": "0.27.0"}), encoding="utf-8"
    )
    config = tmp_path / "config"
    config.mkdir()
    (config / "runtime-prerequisites.json").write_text(json.dumps({
        "files": [{
            "id": "shcdese",
            "relative_path": "BepInEx/plugins/000shcdese/SHCDESE.dll",
            "size": len(payload),
            "sha256": sha256(payload).hexdigest(),
        }]
    }), encoding="utf-8")
    result = discovery.discover(tmp_path, roots=[crusader], environment={})
    evidence = result["games"][0]["runtime_capabilities"]
    assert evidence["status"] == "BLOCKED"
    assert evidence["files"]["shcdese"]["state"] == "SOURCE_PIN_BYTE_MATCH"
    assert evidence["verified_source_pin_bytes"]
    assert evidence["script_extender_declared_version"] == "2.11.0"
    assert evidence["api_shared_declared_version"] == "0.27.0"
    assert "APIShared 0.27 requires Script Extender >=2.14.0" in evidence["blocking_reasons"]
    assert not evidence["runtime_abi_verified"]
    assert not evidence["metadata_signatures_verified"]
    assert not evidence["performed_live_injection"]


def test_runtime_digest_change_is_blocked_not_silently_accepted(tmp_path):
    from hashlib import sha256
    crusader = game(tmp_path, "shcde")
    ext = crusader / "BepInEx/plugins/000shcdese"
    ext.mkdir(parents=True)
    source = b"trusted-candidate"
    (ext / "SHCDESE.dll").write_bytes(b"tampered-candidate")
    (ext / "info.json").write_text(
        json.dumps({"GUID": "000shcdese", "Version": "2.14.0"}), encoding="utf-8"
    )
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "runtime-prerequisites.json").write_text(json.dumps({
        "files": [{
            "id": "shcdese",
            "relative_path": "BepInEx/plugins/000shcdese/SHCDESE.dll",
            "size": len(source), "sha256": sha256(source).hexdigest(),
        }]
    }), encoding="utf-8")
    evidence = discovery.discover(tmp_path, roots=[crusader], environment={})["games"][0]["runtime_capabilities"]
    assert evidence["files"]["shcdese"]["state"] == "SOURCE_PIN_MISMATCH"
    assert evidence["status"] == "BLOCKED"
    assert not evidence["verified_source_pin_bytes"]
    assert not evidence["in_game_qa_verified"]


def test_snapshot_cannot_claim_unreviewed_new_release(tmp_path):
    crusader = game(tmp_path, "shcde")
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "studio-runtime-capabilities-20261108.json").write_text(json.dumps({
        "schema": "sprite-suite.runtime-capability-snapshot.v1",
        "api_shared": {
            "release": "9.0.0", "minimum_script_extender": "2.14.0",
            "plugin_guid": "APIShared_Serp", "source_commit": "fake"
        },
        "serp": {"native_dll_sha256": discovery._NATIVE_BASELINE},
    }), encoding="utf-8")
    import pytest
    with pytest.raises(ValueError, match="explicit ABI"):
        discovery.discover(tmp_path, roots=[crusader], environment={})


def test_declared_version_rejects_noncanonical_strings():
    assert discovery._version("2.14.0") == (2, 14, 0)
    assert discovery._version("0.27.0") == (0, 27, 0)
    for version in ("v2.14.0", "2.14", "2.14.0-other", "02.14.0", "n/a"):
        assert discovery._version(version) is None

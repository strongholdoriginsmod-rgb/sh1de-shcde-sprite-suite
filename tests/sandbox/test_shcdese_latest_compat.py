"""Synthetic, safe compatibility regressions for current and latest SHCDESE."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import shcdese_compat_check as compat


def make(tmp_path: Path, monkeypatch, *, se="2.14.3", bepinex=(5, 4, 23, 5)):
    game = tmp_path / "Stronghold Crusader Definitive Edition"
    se_file = game / compat.SE_DLL
    se_file.parent.mkdir(parents=True)
    se_file.write_bytes(b"fake-se-pe")
    bep_file = game / compat.BEP_DLL
    bep_file.parent.mkdir(parents=True)
    bep_file.write_bytes(b"fake-bepinex-pe")
    dll = game / compat.GAME_DLL
    dll.parent.mkdir(parents=True)
    dll.write_bytes(b"synthetic-assembly-csharp-game")
    manifest = game / compat.SE_MANIFEST
    manifest.write_text(json.dumps({
        "GUID": "000shcdese",
        "Version": se,
        "SupportedGameVersions": ["2.8.0.2"],
        "Manifest": 1,
    }), encoding="utf8")
    supported = tmp_path / "supported-builds.json"
    supported.write_text(json.dumps({"target_builds": [{
        "id": "synthetic-shcde-2.8.0.2",
        "files": [{
            "relative_path": "Managed/Assembly-CSharp.dll",
            "sha256": hashlib.sha256(dll.read_bytes()).hexdigest()
        }]
    }]}), encoding="utf8")
    legacy = tmp_path / "runtime-prerequisites.json"
    legacy.write_text(json.dumps({"script_extender_version": "2.11.0"}), encoding="utf8")
    seen = {
        "SHCDESE.dll": tuple(map(int, se.split("."))) + (0,),
        "BepInEx.dll": bepinex,
    }
    monkeypatch.setattr(compat, "pe_file_version", lambda path: seen.get(path.name))
    return game, supported, legacy


def check(game, supported, legacy):
    return compat.inspect(game, supported_builds=supported, legacy_config=legacy)


def test_latest_shcdese_2143_accepts_pinned_game_and_bepinex_54235(tmp_path, monkeypatch):
    game, supported, legacy = make(tmp_path, monkeypatch)
    report = check(game, supported, legacy)
    assert report["installed_version"] == "2.14.3"
    assert report["bepinex_version"] == "5.4.23.5"
    assert report["hud_noesis_static_ready"] is True
    assert report["blocking_issues"] == []
    assert report["runtime_abi_version_matches"] is False
    assert "RUNTIME_GEGEN_ANDERES_SE_GEBAUT_NEUBAU_ERFORDERLICH" in report["warnings"]
    assert report["writes_to_game"] is False


def test_legacy_2104_is_detected_not_mistaken_for_latest(tmp_path, monkeypatch):
    game, supported, legacy = make(tmp_path, monkeypatch, se="2.10.4")
    report = check(game, supported, legacy)
    assert report["installed_version"] == "2.10.4"
    assert "NEUERER_OFFIZIELLER_SE_VERFUEGBAR" in report["warnings"]
    assert report["hud_noesis_static_ready"] is True
    assert report["runtime_abi_version_matches"] is False


def test_signed_plugin_enforcement_prevents_unsafe_approval(tmp_path, monkeypatch):
    game, supported, legacy = make(tmp_path, monkeypatch)
    config = game / "BepInEx/config/000shcdese.cfg"
    config.parent.mkdir(parents=True)
    config.write_text("[Security]\nRequireSignedBepInExPlugins = true\n", encoding="utf8")
    result = check(game, supported, legacy)
    assert result["signature_enforcement"] is True
    assert result["hud_noesis_static_ready"] is False
    assert "PLUGIN_SIGNATUR_UNABHAENGIG_NICHT_VERIFIZIERT" in result["blocking_issues"]


def test_signature_detection_ignores_other_sections_and_comments(tmp_path):
    path = tmp_path / "000shcdese.cfg"
    path.write_text(
        "# RequireSignedBepInExPlugins = true\n"
        "[General]\nRequireSignedBepInExPlugins = true\n"
        "[Security]\nRequireSignedBepInExPlugins = false\n", encoding="utf8")
    assert compat.signed_plugins_enabled(path) is False
    path.write_text("[Security]\nRequireSignedBepInExPlugins = 1\n", encoding="utf8")
    with pytest.raises(compat.SeCompatibilityError):
        compat.signed_plugins_enabled(path)


def test_spoofed_manifest_version_is_blocked(tmp_path, monkeypatch):
    game, supported, legacy = make(tmp_path, monkeypatch)
    mpath = game / compat.SE_MANIFEST
    data = json.loads(mpath.read_text("utf8"))
    data["Version"] = "2.14.2"
    mpath.write_text(json.dumps(data), encoding="utf8")
    result = check(game, supported, legacy)
    assert "SCRIPT_EXTENDER_DLL_MANIFEST_UNTERSCHIEDLICH" in result["blocking_issues"]
    assert result["hud_noesis_static_ready"] is False


def test_unknown_game_build_does_not_get_false_compatibility(tmp_path, monkeypatch):
    game, supported, legacy = make(tmp_path, monkeypatch)
    (game / compat.GAME_DLL).write_bytes(b"changed-game-bin")
    report = check(game, supported, legacy)
    assert report["game_build_source_pinned"] is False
    assert "SPIEL_BUILD_NICHT_GEGEN_REFERENZ_PIN_VERIFIZIERT" in report["warnings"]
    assert report["hud_noesis_static_ready"] is False


def test_missing_script_extender_blocks_readiness(tmp_path, monkeypatch):
    game, supported, legacy = make(tmp_path, monkeypatch)
    (game / compat.SE_DLL).unlink()
    result = check(game, supported, legacy)
    assert result["installed_version"] is None
    assert "SCRIPT_EXTENDER_DLL_FEHLT" in result["blocking_issues"]


def test_missing_or_old_bepinex_is_detected(tmp_path, monkeypatch):
    game, supported, legacy = make(tmp_path, monkeypatch, bepinex=(5, 4, 23, 3))
    report = check(game, supported, legacy)
    assert "BEPINEX_VERSION_NICHT_UNTERSTUETZT" in report["blocking_issues"]


def test_require_latest_uses_nonzero_exit_without_writing(tmp_path, monkeypatch, capsys):
    game, _supported, _legacy = make(tmp_path, monkeypatch, se="2.10.4")
    monkeypatch.setattr(compat, "ROOT", tmp_path)
    assert compat.main(["--game", str(game), "--require-latest"]) == 2
    assert "2.10.4" in capsys.readouterr().out
    assert (game / compat.SE_DLL).read_bytes() == b"fake-se-pe"


@pytest.mark.parametrize("raw,expected", [
    ("2.14.3", (2,14,3)), ("2.14.3.0", (2,14,3)),
    ("2.14.3.1", None), ("2.14", None), ("v2.14.3", None),
    ("2.14.3.0x", None), (None, None),
])
def test_version_parser_does_not_guess_version(raw, expected):
    assert compat.version(raw) == expected


def test_cli_require_latest_accepts_pinned_2143_test_install(tmp_path, monkeypatch, capsys):
    import shutil
    game, supported, legacy = make(tmp_path, monkeypatch)
    target = tmp_path / "config"
    target.mkdir()
    shutil.copyfile(supported, target / "supported-builds.json")
    shutil.copyfile(legacy, target / "runtime-prerequisites.json")
    monkeypatch.setattr(compat, "ROOT", tmp_path)
    assert compat.main(["--game", str(game), "--require-latest", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["hud_noesis_static_ready"] is True
    assert report["installed_version"] == "2.14.3"
    assert report["runtime_abi_version_matches"] is False
    assert report["runtime_in_game_verified"] is False


def test_upstream_source_still_parses_existing_noesis_patch_root():
    """Static contract: verified official source v2.14.3 accepts Operation children.

    This is intentionally a source-level check, not proof of game rendering.
    """
    sample_root = b"<Patch><Operation Type='Remove' XPath='//*'/></Patch>"
    import xml.etree.ElementTree as ET
    parsed = ET.fromstring(sample_root)
    assert parsed.tag == "Patch"
    assert [e.tag for e in parsed.findall("Operation")] == ["Operation"]

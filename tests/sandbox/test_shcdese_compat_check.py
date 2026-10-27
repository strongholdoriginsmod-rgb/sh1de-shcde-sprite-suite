"""Source-only SHCDESE 2.14.3 read-only compatibility gate regression."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import shcdese_compat_check as se


@pytest.mark.parametrize(("value","expected"), [
    ("2.14.3", (2,14,3)),
    ("2.14.3.0", (2,14,3)),
    ("1.44.0", (1,44,0)),
    ("2.14", None),
    ("2.14.3.1", None),
    ("2.14.3-dev", None),
    ("../../2.14.3", None),
    ("", None),
    (None, None),
])
def test_no_version_injection_or_accidental_major_version(value,expected):
    assert se.version(value)==expected


def test_missing_game_files_blocks_without_writes(tmp_path):
    before={p.relative_to(tmp_path):p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    report=se.inspect(tmp_path)
    assert report["schema"]=="sprite-suite.shcdese-compatibility.v1"
    assert "SCRIPT_EXTENDER_DLL_FEHLT" in report["blocking_issues"]
    assert "BEPINEX_5_NICHT_VERIFIZIERT" in report["blocking_issues"]
    assert not report["hud_noesis_static_ready"]
    assert not report["runtime_in_game_verified"]
    assert not report["writes_to_game"]
    assert {p.relative_to(tmp_path):p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}==before


@pytest.mark.parametrize("value", ["true","false"])
def test_signature_security_option_only_in_exact_section(tmp_path,value):
    cfg=tmp_path/"000shcdese.cfg"
    cfg.write_text(
        "[Other]\nRequireSignedBepInExPlugins = true\n"
        "[Security]\nRequireSignedBepInExPlugins = " + value + "\n",
        encoding="utf8",
    )
    assert se.signed_plugins_enabled(cfg) is (value=="true")


def test_duplicate_signature_flags_are_rejected(tmp_path):
    cfg=tmp_path/"000shcdese.cfg"
    cfg.write_text(
        "[Security]\nRequireSignedBepInExPlugins = true\n"
        "RequireSignedBepInExPlugins = false\n",encoding="utf8",
    )
    with pytest.raises(se.SeCompatibilityError,match="Doppelte"):
        se.signed_plugins_enabled(cfg)


@pytest.fixture
def fake_pinned_game(tmp_path,monkeypatch):
    game=tmp_path/"game"
    sepath=game/se.SE_DLL
    manifest=game/se.SE_MANIFEST
    bepinex=game/se.BEP_DLL
    dll=game/se.GAME_DLL
    for p in (sepath,manifest,bepinex,dll):
        p.parent.mkdir(parents=True,exist_ok=True)
    sepath.write_bytes(b"dummy synthetic se")
    bepinex.write_bytes(b"dummy synthetic BepInEx")
    dll.write_bytes(b"dummy synthetic game managed assembly")
    manifest.write_text(json.dumps({
        "GUID":"000shcdese",
        "Version":"2.14.3",
        "SupportedGameVersions":["2.8.0.2"],
    }),encoding="utf8")
    (game/"BepInEx/config").mkdir(parents=True)
    (game/"BepInEx/config/000shcdese.cfg").write_text(
        "[Security]\nRequireSignedBepInExPlugins = false\n",
        encoding="utf8"
    )
    monkeypatch.setattr(
        se,"pe_file_version",
        lambda path: (2,14,3,0) if Path(path).name=="SHCDESE.dll" else (5,4,23,4),
    )
    pins=tmp_path/"supported-builds.json"
    pins.write_text(json.dumps({"target_builds":[{"id":"synthetic-pinned",
        "files":[{"relative_path":"Managed/Assembly-CSharp.dll",
                  "sha256":hashlib.sha256(dll.read_bytes()).hexdigest()}]}]}),
        encoding="utf8"
    )
    runtime=tmp_path/"runtime-pin.json"
    runtime.write_text(json.dumps({"script_extender_version":"2.11.0"}),encoding="utf8")
    return game,pins,runtime


def test_valid_noesis_preflight_does_not_falsely_certify_runtime(fake_pinned_game):
    game,pins,runtime=fake_pinned_game
    before={p.relative_to(game):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in game.rglob("*") if p.is_file()}
    report=se.inspect(game,supported_builds=pins,legacy_config=runtime)
    assert report["installed_version"]=="2.14.3"
    assert report["upstream_game_compatibility_declared"]
    assert report["game_build_source_pinned"]
    assert report["hud_noesis_static_ready"]  # Static inputs only!
    assert report["runtime_compiled_for"]=="2.11.0"
    assert not report["runtime_abi_version_matches"]
    assert "RUNTIME_GEGEN_ANDERES_SE_GEBAUT_NEUBAU_ERFORDERLICH" in report["warnings"]
    assert not report["runtime_in_game_verified"] and not report["writes_to_game"]
    assert {p.relative_to(game):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in game.rglob("*") if p.is_file()}==before


def test_signed_plugins_require_independent_crypto_review(fake_pinned_game):
    game,pins,runtime=fake_pinned_game
    (game/"BepInEx/config/000shcdese.cfg").write_text(
        "[Security]\nRequireSignedBepInExPlugins = true\n",encoding="utf8"
    )
    report=se.inspect(game,supported_builds=pins,legacy_config=runtime)
    assert "PLUGIN_SIGNATUR_UNABHAENGIG_NICHT_VERIFIZIERT" in report["blocking_issues"]
    assert not report["hud_noesis_static_ready"]


def test_compatibility_cli_rejects_nonexistent_game(tmp_path):
    assert se.main(["--game",str(tmp_path/"no-game"),"--json"])==2

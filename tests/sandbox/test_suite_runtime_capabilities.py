"""Static DLL detection evidence: never execute a discovered binary."""
import hashlib
import json
from pathlib import Path
import struct

import pytest

from suite_runtime_capabilities import (
    RuntimeCapabilityError, hash_reference, inspect_game, pe_signature,
)


def fake_game(tmp_path):
    game = tmp_path / "SHCDE QA"
    (game / "Stronghold Crusader Definitive Edition_Data").mkdir(parents=True)
    (game / "Stronghold Crusader Definitive Edition_Data" / "resources.assets").write_bytes(b"test")
    plugins = game / "BepInEx" / "plugins"
    (plugins / "000shcdese").mkdir(parents=True)
    (plugins / "APIShared").mkdir()
    (plugins / "Serp").mkdir()
    ext = plugins / "000shcdese" / "SHCDESE.dll"
    ext.write_bytes(b"fake DLL cannot be loaded")
    (plugins / "APIShared" / "APIShared.dll").write_bytes(b"MZ fake")
    (plugins / "Serp" / "SerpExtra.dll").write_bytes(b"x"*200)
    return game, ext


def make_managed_pe(path: Path):
    data = bytearray(0x600)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<HHIIIHH", data, 0x84, 0x14c, 1, 0, 0, 0, 224, 0x210E)
    start = 0x98
    struct.pack_into("<H", data, start, 0x10B)
    struct.pack_into("<II", data, start+96+14*8, 0x2100, 0x48)
    sec = start+224
    data[sec:sec+5] = b".text"
    struct.pack_into("<IIII", data, sec+8, 0x1000, 0x2000, 0x400, 0x200)
    struct.pack_into("<I", data, 0x300, 0x48)
    struct.pack_into("<II", data, 0x308, 0x2200, 0x90)
    data[0x400:0x404] = b"BSJB"
    struct.pack_into("<I", data, 0x40C, 12)
    data[0x410:0x41c] = b"v4.0.30319\0\0"
    path.write_bytes(data)


def test_offline_scan_finds_components_without_claiming_runtime_abi(tmp_path):
    game, ext = fake_game(tmp_path)
    raw = ext.read_bytes()
    proof = inspect_game(game)
    assert proof["game_structural_match"] is True
    assert proof["counts"] == {"ScriptExtender": 1, "APIShared": 1, "Serp": 1}
    assert proof["runtime_abi_verified"] is False
    assert proof["executed_discovered_dlls"] is False
    assert proof["modified_game"] is False
    assert ext.read_bytes() == raw
    row = next(c for c in proof["components"] if c["component"] == "ScriptExtender")
    assert row["sha256"] == hashlib.sha256(raw).hexdigest()
    assert row["signature"]["pe"] is False
    assert row["abi_verified"] is False
    assert row["in_game_lifecycle_verified"] is False


def test_managed_and_native_pe_detection_is_static(tmp_path):
    lib = tmp_path / "managed.dll"
    make_managed_pe(lib)
    assert pe_signature(lib)["managed_cli"] is True
    assert pe_signature(lib)["metadata_version"].startswith("v4.0")
    data = bytearray(lib.read_bytes())
    struct.pack_into("<II", data, 0x98+96+14*8, 0, 0)
    lib.write_bytes(data)
    assert pe_signature(lib)["pe"] is True
    assert pe_signature(lib)["managed_cli"] is False


def test_supplied_hash_whitelist_is_evidence_not_abi_approval(tmp_path):
    game, ext = fake_game(tmp_path)
    correct = hashlib.sha256(ext.read_bytes()).hexdigest()
    path = tmp_path / "hashes.json"
    path.write_text(json.dumps({
        "schema": "sprite-suite.runtime-reference-hashes.v1",
        "expected": {"ScriptExtender": [correct], "APIShared": ["0"*64]}
    }), encoding="utf-8")
    proof = inspect_game(game, reference=hash_reference(path))
    rows = {r["component"]: r for r in proof["components"]}
    assert rows["ScriptExtender"]["reference_sha256_match"] is True
    assert rows["APIShared"]["reference_sha256_match"] is False
    assert all(r["abi_verified"] is False for r in rows.values())


@pytest.mark.parametrize("expected", [
    None, {}, {"Wrong": ["a"*64]}, {"Serp": ["0"]},
    {"APIShared": "0"*64}, {"Serp": []}, {"Serp": [False]},
])
def test_invalid_expected_reference_rejected(tmp_path, expected):
    path = tmp_path / "refs.json"
    path.write_text(json.dumps({
        "schema": "sprite-suite.runtime-reference-hashes.v1",
        "expected": expected
    }), encoding="utf-8")
    with pytest.raises(RuntimeCapabilityError):
        hash_reference(path)


def test_non_game_source_reports_no_game_structural_approval(tmp_path):
    empty = tmp_path / "folder"
    empty.mkdir()
    proof = inspect_game(empty)
    assert proof["game_structural_match"] is False
    assert not proof["components"]


def test_symbolic_plugin_components_are_not_followed(tmp_path):
    game, _ = fake_game(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "APIShared.dll").write_bytes(b"secret")
    link = game / "BepInEx" / "plugins" / "external-api"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink disabled for current account")
    paths = [r["file"] for r in inspect_game(game)["components"]]
    assert not any("external-api" in row for row in paths)

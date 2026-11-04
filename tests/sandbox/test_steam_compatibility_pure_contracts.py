"""Steam cross-version compatibility: metadata/bytes stay strict and read-only."""
from __future__ import annotations

import importlib.machinery
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"tools"))

import steam_sprite_compat_diff as compare
import steam_serialized_graphics_compare as raw
import steam_reimport_target as importer
import suite_steam_compatibility as compat


def test_compare_records_id_stability_without_requiring_same_game_patch():
    old=[{"path_id":1,"name":"sprite_a","pivot_x":.5},
         {"path_id":2,"name":"sprite_b","pivot_x":.25}]
    new=[{"path_id":2,"name":"sprite_b","pivot_x":.25},
         {"path_id":1,"name":"sprite_a","pivot_x":.5}]
    result=compare._compare_records(old,new,anchor="path_id")
    assert result["identical"]
    assert result["added"]==result["removed"]==result["changed"]==0
    changed=[{"path_id":1,"name":"sprite_a","pivot_x":.5001},
             {"path_id":3,"name":"sprite_c","pivot_x":.25}]
    result=compare._compare_records(old,changed,anchor="path_id")
    assert not result["identical"]
    assert (result["added"],result["removed"],result["changed"])==(1,1,1)


def test_compare_records_never_silently_merges_duplicate_sprites():
    old=[{"path_id":1,"name":"x"},{"path_id":1,"name":"y"}]
    with pytest.raises(ValueError,match="Nonunique"):
        compare._compare_records(old,[{"path_id":1,"name":"x"}],anchor="path_id")


def test_reimport_guard_rejects_game_dir_output_and_existing_target(tmp_path):
    root=tmp_path/"suite"
    root.mkdir()
    game=tmp_path/"Stronghold Crusader Definitive Edition"
    game.mkdir()
    with pytest.raises(ValueError,match="Never write"):
        importer.reimport_target(game,root,game/"unwanted.json.gz")
    file=root/"safe.json.gz"
    file.write_bytes(b"previous user file")
    with pytest.raises(ValueError,match="Do not replace"):
        importer.reimport_target(game,root,file)
    assert file.read_bytes()==b"previous user file"


def test_reimport_does_not_accept_target_outside_work(tmp_path):
    project=tmp_path/"suite"
    project.mkdir()
    game=tmp_path/"Stronghold Crusader Definitive Edition"
    game.mkdir()
    with pytest.raises(ValueError,match="inside the isolated work directory"):
        importer.reimport_target(game,project,project/"config"/"new.json.gz")


def test_native_abi_comparison_requires_both_original_verified_hashes(tmp_path):
    project=tmp_path/"app"
    contract=project/"contract.json"
    project.mkdir()
    data=tmp_path/compat.DATA_DIR
    native=data/"Plugins"/"x86_64"/"CrusaderDE.dll"
    managed=data/"Managed"/"Assembly-CSharp.dll"
    native.parent.mkdir(parents=True)
    managed.parent.mkdir(parents=True)
    native.write_bytes(b"fake test native bytes")
    managed.write_bytes(b"fake test managed bytes")
    import json
    contract.write_text(json.dumps({
        "schema":"sprite-suite.native-render-contract.v1",
        "dll_sha256":compat._sha(native),
        "managed_sha256":compat._sha(managed),
    }),encoding="utf8")
    game=tmp_path
    assert compat._native_abi_matches(game,contract)["status"]=="exact-pins-match"
    managed.write_bytes(b"changed fake dll")
    result=compat._native_abi_matches(game,contract)
    assert result["status"]=="unverified-binary-abi"
    assert result["dll_matching"] is True
    assert result["managed_matching"] is False


def test_existing_inventory_receipt_rejects_invalid_gzip_even_with_matching_hash(
    tmp_path,
):
    path=tmp_path/"target.resources.json.gz"
    path.write_bytes(b"invalid gzip")
    import json
    evidence=path.with_suffix(".evidence.json")
    actual=tmp_path/"resources.assets"
    actual.write_bytes(b"not an actual unity asset")
    evidence.write_text(json.dumps({
        "schema":"sprite-suite.steam-target-inventory.v1",
        "target_build_id":"source-independent-id",
        "inventory_sha256":compat._sha(path),
        "steam_resources_sha256":compat._sha(actual),
    }),encoding="utf8")
    assert compat._inventory_status(path,"source-independent-id",actual)=="invalid"


def test_gui_steam_button_runs_only_an_asynchronous_readonly_check():
    loader=importlib.machinery.SourceFileLoader(
        "suite_steam_compat_gui_test",str(ROOT/"tools"/"suite.pyw"))
    spec=importlib.util.spec_from_loader(loader.name,loader)
    suite=importlib.util.module_from_spec(spec)
    loader.exec_module(suite)
    submitted=[]
    fake=SimpleNamespace(app=SimpleNamespace(
        run=lambda args,label:submitted.append((args,label))))
    suite.HomeTab.check_steam_compatibility(fake)
    assert len(submitted)==1
    args,title=submitted[0]
    assert args[0]==str(ROOT/"tools"/"suite_steam_compatibility.py")
    assert args[1:]==["--project",str(ROOT)]
    assert "Steam" in title
    assert not any(word in args for word in ("--install","--promote","--replace"))

"""New and legacy Steam versions: safe capability detection, no game writes."""
from __future__ import annotations

from hashlib import sha256
import gzip
import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"tools"))
import suite_steam_compatibility as compat
from suite_steam_compatibility import SteamCompatibilityError
from target_selection_guard import inspect_target,DATA,CANONICAL


def sha(data:bytes)->str:
    return sha256(data).hexdigest()


@pytest.fixture
def game_fixture(tmp_path):
    root=tmp_path/"fixture"
    project=root/"app"
    cfg=project/"config"
    cfg.mkdir(parents=True)
    steam=root/"steam"
    library=steam/"steamapps"
    game=library/"common"/compat.GAME_DIR
    data=game/DATA
    data.mkdir(parents=True)
    all_files=[]
    for index,relative in enumerate(CANONICAL):
        target=data/relative
        target.parent.mkdir(parents=True,exist_ok=True)
        value=(relative+"-synthetic-"+str(index)).encode("utf8")
        target.write_bytes(value)
        all_files.append({"relative_path":relative,
                          "size":len(value),"sha256":sha(value)})
    (data/"StreamingAssets"/"Maps").mkdir(parents=True)
    native=data/"Plugins"/"x86_64"/"CrusaderDE.dll"
    native.parent.mkdir(parents=True)
    native.write_bytes(b"synthetic-fake-native-dll")
    (data/"resources.assets.resS").write_bytes(b"synthetic unity streaming bytes")
    current=inspect_target(game,cfg/"supported-builds.json") if False else None
    (cfg/"supported-builds.json").write_text(
        json.dumps({"schema_version":1,"target_builds":[],
                    "source_builds":[]}),encoding="utf8")
    (cfg/"sandbox-native-render-contract-v1.json").write_text(
        json.dumps({"schema":"sprite-suite.native-render-contract.v1",
                    "dll_sha256":sha(native.read_bytes()),
                    "managed_sha256":sha((data/"Managed"/"Assembly-CSharp.dll").read_bytes())}),
        encoding="utf8")
    manifest=library/f"appmanifest_{compat.APPID}.acf"
    manifest.write_text(
        '"AppState"\n{\n'
        '  "appid" "3024040"\n'
        '  "name" "Stronghold Crusader: Definitive Edition"\n'
        '  "buildid" "99999"\n'
        '  "TargetBuildID" "99999"\n'
        '  "StateFlags" "4"\n'
        '  "LastUpdated" "1792600000"\n'
        '  "installdir" "Stronghold Crusader Definitive Edition"\n'
        '}\n',encoding="utf8")
    return project,steam,game,data,manifest


def test_unknown_steam_build_detected_without_any_version_allowlist(game_fixture):
    project,steam,game,data,manifest=game_fixture
    att=inspect_target(game,project/"config"/"supported-builds.json")
    result=compat.inspect_steam(game,project)
    assert result["steam_build_id"]=="99999"
    assert result["detected_build_id"]==att.build_id
    assert result["build_detected_from_five_file_sha256"]
    assert result["capabilities"]["original_maps_readable"]
    assert result["capabilities"]["unity_resource_inventory_readable"]
    assert result["mapping_status"]=="missing"
    assert result["native_abi"]["status"]=="exact-pins-match"
    assert not result["capabilities"]["mod_installation_approved"]
    assert not result["capabilities"]["in_game_noesis_controls_qa_approved"]


def test_stale_mapping_is_refused_while_steam_map_preview_remains_usable(game_fixture,tmp_path):
    project,steam,game,data,manifest=game_fixture
    mapping=project/"work"/"mapping"/"proposals.json.gz"
    mapping.parent.mkdir(parents=True)
    with gzip.open(mapping,"wt",encoding="utf8") as file:
        json.dump({"schema_version":2,"target_build_id":"old-game","sprites":[]},file)
    result=compat.inspect_steam(game,project,mapping=mapping)
    assert result["mapping_status"]=="different-build"
    assert result["mapping_target_build_id"]=="old-game"
    assert not result["capabilities"]["current_sprite_mapping_exact"]
    assert result["capabilities"]["original_maps_readable"]
    assert not result["capabilities"]["mod_installation_approved"]


def test_reimported_exact_mapping_is_accepted_for_mapping_only(game_fixture):
    project,steam,game,data,manifest=game_fixture
    build_id=inspect_target(game,project/"config"/"supported-builds.json").build_id
    mapping=project/"mapping.json.gz"
    with gzip.open(mapping,"wt",encoding="utf8") as file:
        json.dump({"schema_version":2,"target_build_id":build_id},file)
    result=compat.inspect_steam(game,project,mapping=mapping)
    assert result["mapping_status"]=="compatible"
    assert result["capabilities"]["current_sprite_mapping_exact"]
    assert not result["capabilities"]["mod_installation_approved"]


def test_changed_native_binary_stays_blocked_even_with_valid_sprite_mapping(game_fixture):
    project,steam,game,data,manifest=game_fixture
    dll=data/"Plugins"/"x86_64"/"CrusaderDE.dll"
    original=dll.read_bytes()
    dll.write_bytes(b"synthetic-untrusted-new-game-engine")
    result=compat.inspect_steam(game,project)
    assert result["native_abi"]["status"]=="unverified-binary-abi"
    assert result["native_abi"]["dll_matching"] is False
    assert result["capabilities"]["original_maps_readable"]
    assert not result["capabilities"]["native_engine_paused_snapshot_exact_pins"]
    assert dll.read_bytes()==b"synthetic-untrusted-new-game-engine"
    assert original!=dll.read_bytes()


@pytest.mark.parametrize("value",["../escape","C:\\Private","wrong-game","CON",""])
def test_malicious_or_wrong_installdir_is_not_accepted(game_fixture,value):
    project,steam,game,data,manifest=game_fixture
    before=manifest.read_text("utf8")
    manifest.write_text(before.replace(compat.GAME_DIR,value),encoding="utf8")
    with pytest.raises(SteamCompatibilityError):
        compat.read_appmanifest(manifest)
    assert game.is_dir()


def test_steam_incomplete_update_does_not_report_verified(game_fixture):
    project,steam,game,data,manifest=game_fixture
    text=manifest.read_text("utf8")
    manifest.write_text(text.replace('"TargetBuildID" "99999"',
                                     '"TargetBuildID" "100000"'),encoding="utf8")
    with pytest.raises(SteamCompatibilityError,match="incomplete"):
        compat.inspect_steam(game,project)


def test_libraryfolders_discovery_and_existing_project_not_modified(game_fixture, tmp_path):
    project,steam,game,data,manifest=game_fixture
    duplicate=tmp_path/"other-library"
    other_root=duplicate/"steamapps"/"common"/compat.GAME_DIR
    other_root.mkdir(parents=True)
    other_manifest=duplicate/"steamapps"/f"appmanifest_{compat.APPID}.acf"
    other_manifest.write_bytes(manifest.read_bytes())
    (steam/"steamapps"/"libraryfolders.vdf").write_text(
        '"libraryfolders"\n{\n"0" { "path" "'+str(steam).replace("\\","\\\\")+
        '" }\n"1" { "path" "'+str(duplicate).replace("\\","\\\\")+'" }\n}',
        encoding="utf8")
    discovered=compat.discover_steam_games(steam)
    assert len(discovered)==2
    assert {x[0].resolve() for x in discovered}=={game.resolve(),other_root.resolve()}
    assert not list(project.glob("work/*"))


def test_inventory_receipt_requires_matching_build_and_source(game_fixture):
    project,steam,game,data,manifest=game_fixture
    build_id=inspect_target(game,project/"config"/"supported-builds.json").build_id
    inv=project/"target.resources.json.gz"
    content={
        "schema_version":1,"role":"target",
        "asset_path":str((data/"resources.assets").resolve()),
        "sprites":[{"path_id":123,"name":"a synthetic sprite"}],
        "textures":[{"path_id":77,"name":"a texture"}],
    }
    with gzip.open(inv,"wt",encoding="utf8") as stream:
        json.dump(content,stream)
    raw=inv.read_bytes()
    receipt=inv.with_suffix(".evidence.json")
    receipt.write_text(json.dumps({
        "schema":"sprite-suite.steam-target-inventory.v1",
        "target_build_id":build_id,
        "steam_resources_sha256":compat._sha(data/"resources.assets"),
        "inventory_sha256":sha(raw),
    }),encoding="utf8")
    assert compat._inventory_status(inv,build_id,data/"resources.assets")=="verified-for-current-steam"
    inv.write_bytes(b"modified inventory")
    assert compat._inventory_status(inv,build_id,data/"resources.assets")=="modified-since-import"


def test_report_target_is_exclusive_and_within_project(game_fixture,tmp_path):
    project,steam,game,data,manifest=game_fixture
    output=project/"steam-version.json"
    assert compat.main(["--project",str(project),"--game",str(game),
                        "--output",str(output)])==0
    before=output.read_bytes()
    with pytest.raises(SystemExit):
        compat.main(["--project",str(project),"--game",str(game),
                     "--output",str(output)])
    assert output.read_bytes()==before
    outside=tmp_path/"not-inside-project.json"
    with pytest.raises(SystemExit):
        compat.main(["--project",str(project),"--game",str(game),
                     "--output",str(outside)])
    assert not outside.exists()


def test_any_locally_installed_steam_build_is_recognized_readonly():
    installations=compat.discover_steam_games()
    if not installations:
        pytest.skip("Optional Steam game is not installed on this QA machine")
    if len(installations)>1:
        pytest.skip("Multiple Steam libraries: select one explicitly in QA")
    steam,manifest,metadata=installations[0]
    if metadata["buildid"]!=metadata["TargetBuildID"] or metadata["StateFlags"]!="4":
        pytest.skip("Steam game update is incomplete")
    repo=ROOT
    result=compat.inspect_steam(steam,repo)
    assert result["steam_build_id"]==metadata["buildid"]
    assert result["steam_app_id"]=="3024040"
    assert result["detected_build_id"].startswith(("installed-target-","local-shcde-"))
    assert not result["capabilities"]["mod_installation_approved"]
    assert result["capabilities"]["original_maps_readable"]
    assert result["capabilities"]["unity_resource_inventory_readable"]


def test_duplicated_steam_appmanifest_fields_are_rejected(game_fixture):
    project,steam,game,data,manifest=game_fixture
    text=manifest.read_text("utf8")
    manifest.write_text(
        text.replace('"buildid" "99999"',
                     '"buildid" "99999"\n"buildid" "99999"'),
        encoding="utf8",
    )
    with pytest.raises(SteamCompatibilityError,match="duplicated"):
        compat.read_appmanifest(manifest)


def test_invalid_inventory_with_syntactically_correct_receipt_is_still_rejected(
    game_fixture,
):
    project,steam,game,data,manifest=game_fixture
    build_id=inspect_target(game,project/"config"/"supported-builds.json").build_id
    fake=project/"fake.resources.json.gz"
    fake.write_bytes(b"not-a-valid-gzip-inventory")
    receipt=fake.with_suffix(".evidence.json")
    receipt.write_text(json.dumps({
        "schema":"sprite-suite.steam-target-inventory.v1",
        "target_build_id":build_id,
        "steam_resources_sha256":compat._sha(data/"resources.assets"),
        "inventory_sha256":compat._sha(fake),
    }),encoding="utf8")
    assert compat._inventory_status(fake,build_id,data/"resources.assets")=="invalid"

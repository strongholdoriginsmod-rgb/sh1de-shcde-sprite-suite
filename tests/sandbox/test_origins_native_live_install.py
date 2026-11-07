"""Installed-game native plugin candidate QA: safe hashes and reversible install.

No tests below modify the REAL game installation. The activation/rollback
test patches only the preflight provider and touches isolated fake directories.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import json
import os
import sys

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/"tools"),str(ROOT/"src")]
import origins_native_live_install as live
from origins_live_patch import build_native_menu_patch,verify_original_xpaths,NativePatchError


def _fake_game(tmp_path,monkeypatch):
    root=tmp_path/"game"
    plugins=root/"BepInEx"/"plugins"
    plugins.mkdir(parents=True)
    workspace=tmp_path/"suite"/"work"
    workspace.mkdir(parents=True)
    monkeypatch.setattr(live,"ROOT",workspace.parent)
    original={"game":"a"*64,"frontend":"b"*64}
    monkeypatch.setattr(live,"preflight_game",lambda _root:{
        "game_root":str(root.resolve()),
        "original_sha256":original,
        "original_gui":{"entry_grid_matches":1,"original_viewport_matches":1},
    })
    bundle_dir=workspace/"bundle-v3"
    package=bundle_dir/live.PLUGIN_FOLDER
    (package/"Patches"/"Assets"/"GUI"/"XAML").mkdir(parents=True)
    (package/"info.json").write_text('{"GUID":"spritesuiteoriginslive"}',encoding="utf8")
    (package/"SpriteSuite.Origins.Live.dll").write_bytes(b"MZ"+b"\x00"*64)
    (package/"Patches"/"Assets"/"GUI"/"XAML"/"FrontendMenus.xaml").write_bytes(
        b"<Patch><Operation Type='Add'/></Patch>")
    digests={f.relative_to(package).as_posix():sha256(f.read_bytes()).hexdigest()
             for f in package.rglob("*") if f.is_file()}
    (bundle_dir/"build-receipt.json").write_text(json.dumps({
       "game_originals_sha256":original,"plugin_contents_sha256":digests,
    }),encoding="utf8")
    return root,package,bundle_dir


def test_selected_real_game_original_hashes_and_noesis_patch_are_read_only():
    game=Path(r"D:\Games\Stronghold Crusader Definitive Edition")
    if os.name!="nt" or not game.is_dir():
        pytest.skip("Original user-installed Windows game needed")
    prior=live.preflight_game(game)
    assert prior["original_sha256"]=={key:sha256((game/rel).read_bytes()).hexdigest()
                                     for key,rel in live.GAME_REL.items()}
    original=game/live.GAME_REL["frontend"]
    before=original.read_bytes()
    plan={"name":"qa-original","title":"Live QA",
          "missions":[{"number":1,"title":"Antioch","map":"Antioch.map","act":"I"}]}
    result=build_native_menu_patch(plan,original)
    assert result.startswith(b"<?xml")
    assert result.count(b"Type=\"Add\"")==2
    assert b"OriginsLegacyCampaign" in result
    assert b"LegacyStart" in result
    assert b"SpriteSuiteOriginsCampaignScreen" in result
    assert b"ScrollViewer" in result
    assert original.read_bytes()==before
    assert verify_original_xpaths(original)["entry_grid_matches"]==1


def test_duplicate_original_anchors_cannot_generate_synthetic_success(tmp_path):
    original=tmp_path/"FrontendMenus.xaml"
    original.write_text('<UserControl xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation">'
        '<Grid Width="1920" Height="1080" Visibility="Show_FrontMenus">'
        '<Button Name="MainMenu_OptionsButton"/></Grid>'
        '<Grid Width="1920" Height="1080" Visibility="Show_FrontMenus">'
        '<Button Name="MainMenu_OptionsButton"/></Grid></UserControl>',encoding="utf8")
    with pytest.raises(NativePatchError,match="ambiguous"):
        verify_original_xpaths(original)


def test_fake_plugin_installer_and_rollback_are_byte_exact(tmp_path,monkeypatch):
    game,package,bundle_dir=_fake_game(tmp_path,monkeypatch)
    proof=live.activate_bundle(package,game)
    installed=game/"BepInEx"/"plugins"/live.PLUGIN_FOLDER
    assert proof["installed"] is True
    assert proof["game_originals_unmodified"] is True
    assert installed.is_dir()
    for rel,hash_value in proof["installed_plugin_sha256"].items():
        assert sha256((installed/rel).read_bytes()).hexdigest()==hash_value
    with pytest.raises(live.LiveInstallError,match="already exists"):
        live.activate_bundle(package,game)
    removed=live.rollback(game)
    assert removed["rolled_back"] is True
    assert removed["installed"] is False
    assert not installed.exists()
    assert package.is_dir()
    assert json.loads((bundle_dir/"install-receipt.json").read_text("utf8"))[
        "rolled_back"] is True


def test_rollback_refuses_to_delete_owner_modified_plugin(tmp_path,monkeypatch):
    game,package,bundle_dir=_fake_game(tmp_path,monkeypatch)
    live.activate_bundle(package,game)
    installed=game/"BepInEx"/"plugins"/live.PLUGIN_FOLDER
    asset=installed/"Patches"/"Assets"/"GUI"/"XAML"/"FrontendMenus.xaml"
    asset.write_bytes(asset.read_bytes()+b"\n<!-- user changed this -->")
    with pytest.raises(live.LiveInstallError,match="changed"):
        live.rollback(game)
    assert installed.is_dir()
    assert b"user changed this" in asset.read_bytes()


def test_native_plugin_bundle_compiles_against_exact_game_binaries():
    game=Path(r"D:\Games\Stronghold Crusader Definitive Edition")
    if os.name!="nt" or not game.is_dir() or not live.CSC.is_file():
        pytest.skip("Native installed game & Windows compiler needed")
    output=live.ROOT/"work"/("native-qa-pytest-"+__import__("secrets").token_hex(7))
    result=live.build_bundle(game,output)
    folder=Path(result["bundle"])
    assert folder.is_dir()
    assert (folder/"SpriteSuite.Origins.Live.dll").read_bytes()[:2]==b"MZ"
    metadata=(output/"native-metadata.log").read_text("utf8")
    assert "LIVE_NOESIS_RENDER_TEXTURE_CAPTURE_CODE=1" in metadata
    assert "LIVE_ORIGINAL_GAME_MAP_LOADER_CALL=1" in metadata
    assert result["native_plugin_compiles"] is True
    assert result["compiled_native_plugin_metadata_attested"] is True
    assert result["native_plugin_loaded_in_running_game"] is False
    assert result["actual_season_atlas_swap_attested"] is False
    assert result["game_installation_modified"] is False


def test_experimental_season_memory_swap_not_shipped_without_cleanup_proof():
    """Incomplete direct memory mutation cannot enter an installable plugin."""
    assert not any("OriginsNativeSeasonAtlas.cs" in src
                   for src in live.CS_FILES)
    project=(ROOT/"runtime"/"SpriteSuite.Origins.Authoring"/
             "OriginsNativeLivePlugin.cs").read_text("utf8")
    assert "OriginsSeasonAtlasController" not in project
    assert "SeasonSession.OnMapLoaded" not in project
    assert "Seasons.OnMapLoaded" in project
    assert "season_atlas_visual_override_verified" in project

def test_selected_game_hashes_are_embedded_for_each_runtime_input():
    hashes={key:sha256(key.encode("utf8")).hexdigest() for key in live.GAME_REL}
    source=live._verified_game_inputs(hashes).decode("utf8")
    assert "VerifiedGameInputs" in source
    for key,relative in live.GAME_REL.items():
        assert json.dumps(relative) in source
        assert json.dumps(hashes[key]) in source

def test_install_rejects_unattested_files_and_rolls_back_on_receipt_error(tmp_path,monkeypatch):
    game,package,bundle_dir=_fake_game(tmp_path,monkeypatch)
    extra=package/"extra.dll"
    extra.write_bytes(b"unattested")
    with pytest.raises(live.LiveInstallError,match="files differ"):
        live.activate_bundle(package,game)
    extra.unlink()
    installed=game/"BepInEx"/"plugins"/live.PLUGIN_FOLDER
    def fail_receipt(*_args):
        raise PermissionError("Cannot publish install receipt")
    monkeypatch.setattr(live.os,"replace",fail_receipt)
    with pytest.raises(PermissionError,match="publish install receipt"):
        live.activate_bundle(package,game)
    assert not installed.exists()
    assert not list(installed.parent.glob(".spritesuite-installing-*"))
    assert not list(bundle_dir.glob(".spritesuite-receipt-*.json"))

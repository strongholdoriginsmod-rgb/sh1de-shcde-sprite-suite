"""Do not grant native in-game release from a file, mock DLL or mere install."""
from __future__ import annotations
from pathlib import Path
import json
import sys

from PIL import Image
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/"tools"),str(ROOT/"src")]
import origins_native_live_verify as evidence
import suite_noesis_native_live_preview as viewer


@pytest.fixture
def fake_install(tmp_path,monkeypatch):
    game=tmp_path/"game"
    installed=game/"BepInEx"/"plugins"/"SpriteSuite_Origins_Live_20261101"
    installed.mkdir(parents=True)
    (installed/"SpriteSuite.Origins.Live.dll").write_bytes(b"MZ")
    monkeypatch.setattr(evidence,"preflight_game",lambda _game:{
        "original_sha256":{"game":"a"*64},
        "game_root":str(game),
    })
    # The false/true process provider is injected only inside a pure QA test.
    monkeypatch.setattr(viewer,"game_process_is_live",lambda pid:False)
    folder=tmp_path/"telemetry"
    return game,folder


def test_install_and_absent_game_cannot_approve_menu_or_render(fake_install):
    game,folder=fake_install
    result=evidence.native_live_evidence(game,folder)
    assert result["native_plugin_binary_installed"] is True
    assert result["game_process_alive_and_matching_name"] is False
    assert result["live_game_abi_verified"] is False
    assert result["native_in_game_menu_approved"] is False
    assert result["native_noesis_rendertexture_pixel_frame_observed"] is False
    assert result["full_in_game_release_approved"] is False


def test_mocked_capture_telemetry_distinguishes_types_and_never_approves_seasons(
    fake_install,monkeypatch
):
    game,folder=fake_install
    folder.mkdir()
    sample=folder/"native-frame-00001.png"
    Image.new("RGBA",(240,160),(30,80,120,255)).save(sample)
    from test_origins_native_live_preview import _write_status
    status=_write_status(folder,sample,"native-noesis-rendertexture",
        game_assembly_sha256="a"*64,
        game_installation_root=str(game),
        native_menu_actions_handled=2,
        last_native_menu_command="LegacyStart",
        native_mission_launch_verified=True,
        native_map_postload_callback_count=1)
    monkeypatch.setattr(viewer,"game_process_is_live",lambda pid:True)
    reported=evidence.native_live_evidence(game,folder)
    assert reported["live_game_abi_verified"] is True
    assert reported["native_in_game_menu_approved"] is True
    assert reported["native_in_game_map_start_approved"] is True
    assert reported["native_noesis_rendertexture_pixel_frame_observed"] is True
    assert reported["season_route_map_event_observed"] is True
    assert reported["season_atlas_swapped_and_visually_verified"] is False
    assert reported["full_in_game_release_approved"] is False
    # A Unity game screenshot cannot be claimed as an isolated Noesis bitmap.
    status.update({
        "frame_source":"unity-game-composited-screen",
        "pixel_exact_native_noesis_texture":False,
        "pixel_exact_composited_game_screenshot":True})
    (folder/"live-status.json").write_text(json.dumps(status),encoding="utf8")
    composed=evidence.native_live_evidence(game,folder)
    assert composed["native_noesis_rendertexture_pixel_frame_observed"] is False
    assert composed["native_composited_game_frame_observed"] is True


def test_inactive_game_never_attests_stale_successful_record(fake_install):
    game,folder=fake_install
    folder.mkdir()
    _write=__import__("test_origins_native_live_preview",
                      fromlist=["_write_status"])._write_status
    _write(folder,None,None,game_assembly_sha256="a"*64,
        game_installation_root=str(game),
        native_menu_actions_handled=12,
        native_mission_launch_verified=True)
    result=evidence.native_live_evidence(game,folder)
    assert result["native_in_game_menu_approved"] is False
    assert result["native_in_game_map_start_approved"] is False
    assert result["full_in_game_release_approved"] is False


def test_wrong_game_hash_blocks_fake_success(fake_install,monkeypatch):
    game,folder=fake_install
    folder.mkdir()
    from test_origins_native_live_preview import _write_status
    _write_status(folder,None,None,game_assembly_sha256="f"*64,
                  game_installation_root=str(game),
                  native_menu_actions_handled=3)
    monkeypatch.setattr(viewer,"game_process_is_live",lambda pid:True)
    result=evidence.native_live_evidence(game,folder)
    assert result["live_game_abi_verified"] is False
    assert result["native_in_game_menu_approved"] is False
    assert result["full_in_game_release_approved"] is False


def test_running_game_with_correct_binary_but_other_installation_is_not_approved(
    fake_install,monkeypatch,
):
    game,folder=fake_install
    from test_origins_native_live_preview import _write_status
    _write_status(folder,None,None,
                  game_assembly_sha256="a"*64,
                  game_installation_root=str(game.parent/"other-game-copy"),
                  native_menu_actions_handled=3,
                  native_mission_launch_verified=True)
    monkeypatch.setattr(viewer,"game_process_is_live",lambda _pid:True)
    result=evidence.native_live_evidence(game,folder)
    assert result["game_binary_hash_matches_requested"] is True
    assert result["game_process_alive_and_matching_name"] is True
    assert result["game_installation_path_matches_requested"] is False
    assert result["live_game_abi_verified"] is False
    assert result["native_in_game_menu_approved"] is False
    assert result["native_in_game_map_start_approved"] is False

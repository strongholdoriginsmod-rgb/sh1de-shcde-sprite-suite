"""Evaluate *actual* in-game SpriteSuite native bridge evidence, not mock success.

Run after manually starting installed SHCDE. Reports each observed live
condition separately; a compiled or installed DLL alone can NEVER pass.
Native Noesis pixel attestation requires a completed PNG from an actual
NoesisView RenderTexture (not just a composited Unity screenshot).
Map launch requires explicit callback evidence from the requested mission.
Season atlas switching requires separate visual/ABI proof and remains false.
"""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
from hashlib import sha256

from suite_noesis_native_live_preview import live_directory,read_live_frame,LiveFrameError
from origins_native_live_install import preflight_game,LiveInstallError

ROOT=Path(__file__).resolve().parents[1]


def native_live_evidence(game:Path,status_dir:Path|None=None)->dict:
    preflight=preflight_game(game)
    folder=Path(status_dir) if status_dir is not None else live_directory()
    frame,status=read_live_frame(folder)
    alive=status.get("source_game_process_alive") is True
    gamehash=preflight["original_sha256"]["game"]
    binary_matches=status.get("game_assembly_sha256")==gamehash
    observed_root=status.get("game_installation_root")
    root_matches=bool(isinstance(observed_root,str) and observed_root.strip() and
                      Path(observed_root).resolve(strict=False)==Path(game).resolve(strict=False))
    verified=bool(alive and binary_matches and root_matches and
                  status.get("runtime_game_abi_verified") is True)
    menu_hooks=bool(verified and status.get("native_menu_hook_registered") is True)
    map_hooks=bool(verified and status.get("native_map_hooks_registered") is True)
    menu_count=status.get("native_menu_actions_handled",0)
    menu_command=status.get("last_native_menu_command")
    menu_received=bool(menu_hooks and type(menu_count) is int and menu_count>0)
    requested=status.get("pending_mission_launch")
    confirmed=bool(map_hooks and
        status.get("native_mission_launch_verified") is True)
    native_noesis=bool(verified and frame is not None and
        frame.pixel_exact_native_noesis)
    composite=bool(verified and frame is not None and
        frame.pixel_exact_composited_game)
    season_route=bool(map_hooks and
        type(status.get("map_load_event_count")) is int and
        status["map_load_event_count"]>0 and
        isinstance(status.get("active_season_route"),str) and
        bool(status.get("active_season_route")))
    result={
        "schema":"sprite-suite.origins-live-release-evidence.v1",
        "checked_utc":datetime.now(timezone.utc).isoformat(),
        "game_root":str(game),
        "native_plugin_binary_installed":(
            Path(game)/"BepInEx"/"plugins"/
            "SpriteSuite_Origins_Live_20261101"/
            "SpriteSuite.Origins.Live.dll").is_file(),
        "game_process_alive_and_matching_name":alive,
        "game_installation_path_matches_requested":root_matches,
        "game_binary_hash_matches_requested":binary_matches,
        "live_game_abi_verified":verified,
        "native_menu_harmony_hook_registered":menu_hooks,
        "native_menu_callback_executed_in_game":menu_received,
        "native_menu_callback_count":menu_count,
        "last_menu_command":menu_command,
        "native_map_load_unload_handlers_registered":map_hooks,
        "native_map_load_callback_count":status.get("map_load_event_count",0)
              if verified else 0,
        "native_map_unload_callback_count":status.get("map_unload_event_count",0)
              if verified else 0,
        "requested_map_file":requested if verified else None,
        "native_requested_mission_loaded":confirmed,
        "native_noesis_rendertexture_pixel_frame_observed":native_noesis,
        "native_composited_game_frame_observed":composite,
        "captured_frame_sha256":(
            sha256(frame.path.read_bytes()).hexdigest()
            if frame and verified else None),
        "captured_frame_size":list(frame.size) if frame and verified else None,
        "season_route_map_event_observed":season_route,
        "season_atlas_swapped_and_visually_verified":False,
        "native_noesis_live_renderer_fully_integrated":native_noesis,
        "native_in_game_menu_approved":menu_received,
        "native_in_game_map_start_approved":confirmed,
        "native_in_game_season_atlases_approved":False,
        "full_in_game_release_approved":False,
        "reason_full_release_not_approved":
            "Season atlas overrides have no reversible live-game proof. "
            "Do not substitute offline mock data or menu registration for a "
            "native Noesis render and actual map/season lifecycle QA.",
        "game_original_files_modified":False,
        "status_dir":str(folder),
        "last_plugin_error":status.get("last_error") if verified else None,
    }
    return result


def main(argv=None)->int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game",type=Path,required=True)
    parser.add_argument("--status-dir",type=Path)
    parser.add_argument("--out",type=Path)
    parser.add_argument("--require",choices=("none","plugin","menu","map","noesis",
                                             "complete"),default="none")
    args=parser.parse_args(argv)
    try:
        result=native_live_evidence(args.game,args.status_dir)
        if args.out is not None:
            destination=Path(args.out)
            if destination.exists() or destination.is_symlink() or not (
                destination.resolve(strict=False).is_relative_to((ROOT/"work").resolve())
            ):
                raise LiveInstallError("Verification receipt must be NEW and inside work/")
            destination.parent.mkdir(parents=True,exist_ok=True)
            destination.write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n",
                                   encoding="utf8")
        print(json.dumps(result,ensure_ascii=False,indent=2))
        success={
            "none":True,
            "plugin":result["live_game_abi_verified"],
            "menu":result["native_menu_callback_executed_in_game"],
            "map":result["native_requested_mission_loaded"],
            "noesis":result["native_noesis_rendertexture_pixel_frame_observed"],
            "complete":result["full_in_game_release_approved"],
        }[args.require]
        return 0 if success else 2
    except (OSError,ValueError,RuntimeError) as exc:
        print("NATIVE_GAME_PROOF_ERROR: "+str(exc))
        return 3


if __name__=="__main__":
    raise SystemExit(main())

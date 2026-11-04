"""Read-only Steam build discovery and capability checks for SpriteSuite.

The newest *locally installed* Steam build can be imported independently of
older pinned game versions. Native ABI, stale sprite mappings, and interactive
Noesis integration are never enabled merely by a newer version number.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import sys

from target_selection_guard import (
    inspect_target, mapping_target_build_id, TargetSelectionError,
)
from stronghold_europe_de.unity_inventory import read_inventory

ROOT=Path(__file__).resolve().parents[1]
APPID="3024040"
GAME_TITLE="Stronghold Crusader: Definitive Edition"
GAME_DIR="Stronghold Crusader Definitive Edition"
DATA_DIR="Stronghold Crusader Definitive Edition_Data"
HEX_SHA=re.compile(r"[0-9a-f]{64}\Z")
_MANIFEST_FIELD=re.compile(r'^\s*"([^"]+)"\s*"([^"]*)"',re.M)


class SteamCompatibilityError(ValueError):
    """The installation could not be safely identified or verified."""


def _sha(path:Path)->str:
    hasher=sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(4*1024*1024),b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def read_appmanifest(path:Path)->dict[str,str]:
    file=Path(path)
    if file.is_symlink() or not file.is_file() or file.stat().st_size>1048576:
        raise SteamCompatibilityError("Missing, linked or oversized Steam manifest")
    found=_MANIFEST_FIELD.findall(file.read_text("utf8",errors="replace"))
    critical={"appid","name","installdir","buildid","TargetBuildID","LastUpdated","StateFlags"}
    if any(sum(key==name for name,_value in found)>1 for key in critical):
        raise SteamCompatibilityError("Ambiguous duplicated Steam installation metadata")
    pairs=dict(found)
    if pairs.get("appid")!=APPID or pairs.get("name")!=GAME_TITLE:
        raise SteamCompatibilityError("Steam manifest does not identify SHCDE AppID 3024040")
    folder=pairs.get("installdir","")
    if folder!=GAME_DIR:
        raise SteamCompatibilityError("Unexpected or unsafe installed Steam game directory")
    for name in ("buildid","TargetBuildID","LastUpdated","StateFlags"):
        if not pairs.get(name,"").isdigit():
            raise SteamCompatibilityError("Missing numeric Steam manifest attribute "+name)
    return pairs


def _registry_steam_root()->Path|None:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r"Software\Valve\Steam") as key:
            value,_=winreg.QueryValueEx(key,"SteamPath")
        return Path(value) if isinstance(value,str) and value else None
    except (ImportError,OSError,ValueError):
        return None


def discover_steam_games(steam_root:Path|None=None)->list[tuple[Path,Path,dict]]:
    """Return installed games from all local Steam libraries; never assume first."""
    root=Path(steam_root) if steam_root is not None else _registry_steam_root()
    if root is None or not root.is_dir():
        return []
    libraries=[root]
    folder_config=root/"steamapps"/"libraryfolders.vdf"
    if folder_config.is_file() and not folder_config.is_symlink():
        if folder_config.stat().st_size<=2*1024*1024:
            for field in re.findall(r'"path"\s*"([^"]+)"',
                                    folder_config.read_text("utf8",errors="replace")):
                candidate=Path(field.replace("\\\\","\\"))
                if candidate not in libraries:
                    libraries.append(candidate)
    found={}
    for lib in libraries:
        appmanifest=lib/"steamapps"/f"appmanifest_{APPID}.acf"
        if not appmanifest.is_file():continue
        try:
            data=read_appmanifest(appmanifest)
        except SteamCompatibilityError:
            continue
        game=lib/"steamapps"/"common"/data["installdir"]
        if not game.is_dir():
            continue
        identity=str(game.resolve(strict=False)).casefold()
        found[identity]=(game,appmanifest,data)
    # Multiple local installations are listed, not silently conflated.
    return sorted(found.values(),key=lambda item:(
        -int(item[2]["LastUpdated"]),str(item[0]).casefold()))


def _current_mapping(mapping:Path|None,build_id:str)->tuple[str,str|None]:
    if mapping is None or not mapping.is_file():
        return "missing",None
    if mapping.is_symlink() or mapping.stat().st_size>128*1024*1024:
        return "invalid",None
    try:
        target=mapping_target_build_id(mapping)
    except (OSError,TargetSelectionError,ValueError,EOFError):
        return "invalid",None
    return ("compatible" if target==build_id else "different-build"),target


def _native_abi_matches(game:Path,contract_path:Path)->dict:
    dll=game/DATA_DIR/"Plugins"/"x86_64"/"CrusaderDE.dll"
    managed=game/DATA_DIR/"Managed"/"Assembly-CSharp.dll"
    if not dll.is_file() or not managed.is_file():
        return {"status":"not-installed-or-missing","dll_matching":False,
                "managed_matching":False}
    try:
        contract=json.loads(contract_path.read_text("utf8"))
    except (OSError,UnicodeError,ValueError):
        return {"status":"contract-missing","dll_matching":False,
                "managed_matching":False}
    if contract.get("schema")!="sprite-suite.native-render-contract.v1":
        return {"status":"contract-invalid","dll_matching":False,
                "managed_matching":False}
    old_dll=contract.get("dll_sha256")
    old_managed=contract.get("managed_sha256")
    if not isinstance(old_dll,str) or not HEX_SHA.fullmatch(old_dll):
        return {"status":"contract-invalid","dll_matching":False,
                "managed_matching":False}
    if not isinstance(old_managed,str) or not HEX_SHA.fullmatch(old_managed):
        return {"status":"contract-invalid","dll_matching":False,
                "managed_matching":False}
    same_dll=_sha(dll)==old_dll
    same_managed=_sha(managed)==old_managed
    return {"status":"exact-pins-match" if same_dll and same_managed
            else "unverified-binary-abi","dll_matching":same_dll,
            "managed_matching":same_managed}


def _inventory_status(inventory_path:Path|None,build_id:str,
                      resources:Path)->str:
    if inventory_path is None or not inventory_path.is_file():
        return "not-imported"
    if inventory_path.is_symlink() or inventory_path.stat().st_size>64*1024*1024:
        return "invalid"
    evidence=inventory_path.with_suffix(".evidence.json")
    if evidence.is_symlink() or not evidence.is_file():
        return "unattested"
    if evidence.stat().st_size>256*1024:
        return "invalid"
    try:
        record=json.loads(evidence.read_text("utf8"))
    except (OSError,UnicodeError,ValueError):
        return "invalid"
    if record.get("schema")!="sprite-suite.steam-target-inventory.v1":
        return "invalid"
    if record.get("target_build_id")!=build_id:
        return "different-build"
    if record.get("inventory_sha256")!=_sha(inventory_path):
        return "modified-since-import"
    if record.get("steam_resources_sha256")!=_sha(resources):
        return "steam-updated-since-import"
    try:
        inventory=read_inventory(inventory_path)
        if (inventory.get("role")!="target" or
            Path(inventory.get("asset_path","")).resolve(strict=False)
            !=resources.resolve(strict=False) or
            not isinstance(inventory.get("sprites"),list) or
            not isinstance(inventory.get("textures"),list) or
            not inventory["sprites"]):
            return "invalid"
    except (OSError,UnicodeError,ValueError,KeyError,TypeError,EOFError):
        return "invalid"
    return "verified-for-current-steam"


def inspect_steam(game:Path,project:Path, *,
                  mapping:Path|None=None,inventory:Path|None=None,
                  manifest:Path|None=None)->dict:
    repo=Path(project).resolve(strict=True)
    candidate=Path(game).resolve(strict=True)
    source_manifest=Path(manifest) if manifest else candidate.parent.parent/f"appmanifest_{APPID}.acf"
    data=read_appmanifest(source_manifest)
    if candidate.name!=data["installdir"]:
        raise SteamCompatibilityError("Game directory does not match Steam manifest")
    complete=(data["buildid"]==data["TargetBuildID"]
              and data["StateFlags"]=="4")
    if not complete:
        raise SteamCompatibilityError("Steam game update is incomplete; retry after update")
    game_root=repo/"config"/"supported-builds.json"
    att=inspect_target(candidate,game_root)
    map_status,map_build=_current_mapping(mapping,att.build_id)
    native=_native_abi_matches(candidate,repo/"config"/"sandbox-native-render-contract-v1.json")
    inventory_status=_inventory_status(
        inventory,att.build_id,att.data_dir/"resources.assets")
    extender=(candidate/"BepInEx"/"plugins"/"000shcdese")
    capabilities={
        "original_maps_readable":(
            att.data_dir.joinpath("StreamingAssets","Maps").is_dir()
            and not att.data_dir.joinpath("StreamingAssets","Maps").is_symlink()
        ),
        "unity_resource_inventory_readable":(
            att.data_dir.joinpath("resources.assets").is_file()
            and att.data_dir.joinpath("resources.assets.resS").is_file()
        ),
        "steam_target_inventory_verified":inventory_status=="verified-for-current-steam",
        "current_sprite_mapping_exact":map_status=="compatible",
        "native_engine_paused_snapshot_exact_pins":native["status"]=="exact-pins-match",
        # A script extender folder alone cannot prove correct XAML bindings,
        # click handling or successful in-game overlay installation.
        "in_game_noesis_controls_qa_approved":False,
        "mod_installation_approved":False,
    }
    return {
        "schema":"sprite-suite.steam-compatibility.v1",
        "game_title":GAME_TITLE,
        "steam_app_id":APPID,
        "steam_build_id":data["buildid"],
        "steam_update_completed":complete,
        "build_last_updated_utc":datetime.fromtimestamp(
            int(data["LastUpdated"]),timezone.utc).isoformat(),
        "game_root":str(candidate),
        "detected_build_id":att.build_id,
        "build_detected_from_five_file_sha256":att.files_checked==5,
        "mapping_status":map_status,
        "mapping_target_build_id":map_build,
        "target_inventory_status":inventory_status,
        "native_abi":native,
        "script_extender_installed":extender.is_dir(),
        "capabilities":capabilities,
        "next_steps":[
            "Steam original maps and Unity resources can be inspected without modifying the game",
            ("Sprite mapping is SHA-bound to this Steam build; verify the donor "
             "SH1DE source and complete profile/build validation before using a package"
             if map_status=="compatible"
             else "Reimport the actual Steam target; an old version's sprite mapping cannot be installed"),
            ("Target Unity inventory has a matching SHA-based provenance receipt"
             if inventory_status=="verified-for-current-steam"
             else "The current Steam target inventory is missing, outdated or unverified"),
            ("Native snapshots match both approved binary pins"
             if native["status"]=="exact-pins-match"
             else "Native DLL/Noesis runtime tests require a new independent QA/ABI proof"),
        ],
        "original_steam_files_modified":False,
        "server_latest_version_claimed":False,
    }


def main(argv:list[str]|None=None)->int:
    parser=argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--steam-root",type=Path,
                        help="Steam installation root (auto-detected by default)")
    parser.add_argument("--game",type=Path,
                        help="Explicit Steam SHCDE game directory")
    parser.add_argument("--project",type=Path,default=ROOT)
    parser.add_argument("--mapping",type=Path)
    parser.add_argument("--inventory",type=Path)
    parser.add_argument("--output",type=Path,
                        help="NEW local JSON diagnostic; original games never written")
    args=parser.parse_args(argv)
    repo=args.project.resolve(strict=True)
    if args.game is None:
        entries=discover_steam_games(args.steam_root)
        if not entries:
            parser.error("No local Steam SHCDE installation found")
        if len(entries)>1:
            parser.error("Several Steam installations found; select one with --game")
        game,manifest,_=entries[0]
    else:
        game=args.game
        manifest=(args.steam_root/"steamapps"/f"appmanifest_{APPID}.acf"
                  if args.steam_root else None)
    selected_mapping=args.mapping if args.mapping is not None else repo/"work"/"mapping"/"proposals.json.gz"
    selected_inventory=args.inventory if args.inventory is not None else None
    result=inspect_steam(game,repo,mapping=selected_mapping,
                         inventory=selected_inventory,manifest=manifest)
    raw=json.dumps(result,ensure_ascii=False,indent=2)+"\n"
    if args.output:
        dest=args.output.resolve(strict=False)
        if (repo not in dest.parents or
            dest.exists() or dest.is_symlink() or dest.parent.is_symlink()):
            parser.error("Output must be a NEW regular file inside the project")
        dest.parent.mkdir(parents=True,exist_ok=True)
        with dest.open("x",encoding="utf8") as file:
            file.write(raw)
    print(raw)
    return 0


if __name__=="__main__":
    raise SystemExit(main())

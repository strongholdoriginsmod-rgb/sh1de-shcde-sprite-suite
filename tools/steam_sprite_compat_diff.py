"""Compare a freshly imported Steam Sprite catalogue to a pinned prior catalogue.

No game writes. This report never rebases a version-bound production mapping:
even if Sprite rectangles and texture metadata are unchanged, sprite hashes and
the donor SH1DE source must be independently proven before installation.
"""
from __future__ import annotations

import argparse
from collections import Counter,defaultdict
from hashlib import sha256
import json
from pathlib import Path

from stronghold_europe_de.unity_inventory import read_inventory
from target_selection_guard import inspect_target


def _digest(path: Path) -> str:
    hasher=sha256()
    with Path(path).open("rb") as file:
        for chunk in iter(lambda: file.read(4*1024*1024),b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _entry_key(row:dict)->str:
    return json.dumps(row,ensure_ascii=False,sort_keys=True,separators=(",",":"))


def _compare_records(old:list[dict],new:list[dict], *,
                     anchor:str,examples:int=12)->dict:
    old_by={row[anchor]:row for row in old}
    new_by={row[anchor]:row for row in new}
    if len(old_by)!=len(old) or len(new_by)!=len(new):
        raise ValueError(f"Nonunique {anchor} in compared Unity catalogue")
    keys=old_by.keys()|new_by.keys()
    added=[];removed=[];changed=[]
    for key in sorted(keys):
        a=old_by.get(key);b=new_by.get(key)
        if a is None: added.append(key)
        elif b is None:removed.append(key)
        elif a!=b:changed.append(key)
    return {"previous_count":len(old),"steam_count":len(new),
            "added":len(added),"removed":len(removed),"changed":len(changed),
            "identical":len(added)+len(removed)+len(changed)==0,
            "examples":{"added":added[:examples],"removed":removed[:examples],
                        "changed":changed[:examples]}}


def compare(steam_game:Path, repo:Path, old_inv:Path,new_inv:Path,
            supported:Path) -> dict:
    target=inspect_target(steam_game,supported)
    prior=read_inventory(old_inv)
    latest=read_inventory(new_inv)
    if prior.get("role")!="target" or latest.get("role")!="target":
        raise ValueError("Only TARGET Unity inventories may be compared")
    actual=(target.data_dir/"resources.assets").resolve(strict=True)
    if Path(latest.get("asset_path","")).resolve(strict=False)!=actual:
        raise ValueError("Latest catalogue does not identify actual Steam resources.assets")
    old_targets=json.loads(supported.read_text("utf8"))["target_builds"]
    old=next((item for item in old_targets if item["id"]=="local-shcde-2.80-unity-2021.3.45f2"),None)
    if old is None:raise ValueError("Missing historical target fingerprint")
    old_stream=next(item for item in old["files"] if item["relative_path"]=="resources.assets.resS")
    original_stream=target.data_dir/"resources.assets.resS"
    stream_same=(original_stream.stat().st_size==old_stream["size"]
                 and _digest(original_stream)==old_stream["sha256"])
    textures=_compare_records(prior["textures"],latest["textures"],anchor="path_id")
    sprites=_compare_records(prior["sprites"],latest["sprites"],anchor="path_id")
    audio=_compare_records(prior["audio_clips"],latest["audio_clips"],anchor="path_id")
    previous_group_names=Counter(item["name"] for item in prior["sprites"])
    new_group_names=Counter(item["name"] for item in latest["sprites"])
    names_equal=previous_group_names==new_group_names
    report={
        "schema":"spritesuite.steam-sprite-metadata-compatibility.v1",
        "steam_target_build_id":target.build_id,
        "prior_target_build_id":old["id"],
        "resources_stream_is_byte_identical_to_prior":stream_same,
        "sprite_records":sprites,
        "texture_records":textures,
        "audio_records":audio,
        "sprite_name_multiset_identical":names_equal,
        "content_equivalent_for_unity_inventory":(
            stream_same and sprites["identical"] and textures["identical"]
        ),
        "source_sh1de_game_verified":False,
        "full_pixel_equivalence_across_all_unity_asset_types_verified":False,
        "game_engine_abi_approved":False,
        "previous_mapping_install_authorized":False,
        "game_files_modified":False,
        "note":"Even exact sprite metadata and .resS cannot prove all Unity asset-payload semantics.",
    }
    return report


def main(argv:list[str]|None=None)->int:
    parser=argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--steam-game",type=Path,required=True)
    parser.add_argument("--project",type=Path,required=True)
    parser.add_argument("--old-target-inventory",type=Path,required=True)
    parser.add_argument("--steam-target-inventory",type=Path,required=True)
    parser.add_argument("--report",type=Path,required=True)
    args=parser.parse_args(argv)
    repo=args.project.resolve(strict=True)
    out=args.report.resolve(strict=False)
    if repo not in out.parents or out.exists():
        parser.error("Report must be NEW and inside the isolated project")
    report=compare(args.steam_game,repo,args.old_target_inventory,
                   args.steam_target_inventory,repo/"config"/"supported-builds.json")
    out.parent.mkdir(parents=True,exist_ok=True)
    with out.open("x",encoding="utf8") as file:
        json.dump(report,file,ensure_ascii=False,indent=2)
        file.write("\n")
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0


if __name__=="__main__":
    raise SystemExit(main())

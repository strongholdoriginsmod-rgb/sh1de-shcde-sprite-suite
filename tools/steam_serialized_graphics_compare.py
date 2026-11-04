"""Independently compare old/new raw Unity sprite, texture and audio objects.

Unlike high-level inventory comparison, this includes embedded texture pixel
data and unknown serialized fields. It is a read-only, content-bound graphics
compatibility check, never an approval of native binary ABI or mod installation.
"""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import time

from stronghold_europe_de.unity_inventory import load_unity_asset
from target_selection_guard import inspect_target

DATA="Stronghold Crusader Definitive Edition_Data"
KINDS=frozenset(("Texture2D","Sprite","AudioClip"))


def _sha(path:Path)->str:
    hasher=sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda:stream.read(4*1024*1024),b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _raw_object_digests(asset:Path)->dict[tuple[str,int],str]:
    env=load_unity_asset(asset)
    result={}
    for obj in env.objects:
        kind=obj.type.name
        if kind not in KINDS:
            continue
        key=(kind,obj.path_id)
        if key in result:
            raise ValueError(f"Ambiguous serialized Unity object: {key}")
        if obj.byte_size>64*1024*1024:
            raise ValueError(f"Oversized inline Unity object: {key}")
        result[key]=sha256(obj.get_raw_data()).hexdigest()
    return result


def compare(previous_game:Path, steam_game:Path, project:Path)->dict:
    previous=Path(previous_game).resolve(strict=True)
    steam=Path(steam_game).resolve(strict=True)
    repo=Path(project).resolve(strict=True)
    if previous==steam:
        raise ValueError("Two different game versions must be compared")
    refs=json.loads((repo/"config"/"supported-builds.json").read_text("utf8"))
    old=next(x for x in refs["target_builds"] if x["id"]=="local-shcde-2.80-unity-2021.3.45f2")
    known={x["relative_path"]:x["sha256"] for x in old["files"]}
    old_data=previous/DATA
    steam_data=steam/DATA
    old_asset=old_data/"resources.assets"
    new_asset=steam_data/"resources.assets"
    if _sha(old_asset)!=known["resources.assets"]:
        raise ValueError("Old game does not match the approved 2.80 original")
    att=inspect_target(steam,repo/"config"/"supported-builds.json")
    old_stream=old_data/"resources.assets.resS"
    new_stream=steam_data/"resources.assets.resS"
    if _sha(old_stream)!=known["resources.assets.resS"]:
        raise ValueError("Prior .resS is not the known old game stream")
    streams_equal=_sha(new_stream)==known["resources.assets.resS"]
    old_before=_sha(old_asset)
    new_before=_sha(new_asset)
    started=time.monotonic()
    older=_raw_object_digests(old_asset)
    newer=_raw_object_digests(new_asset)
    kinds={}
    for kind in sorted(KINDS):
        a={id:value for (type_name,id),value in older.items() if type_name==kind}
        b={id:value for (type_name,id),value in newer.items() if type_name==kind}
        keys=a.keys()|b.keys()
        changed=sorted(k for k in keys if a.get(k)!=b.get(k))
        kinds[kind]={"prior_objects":len(a),"steam_objects":len(b),
                     "raw_serialized_object_hashes_equal":not changed,
                     "changed_or_unmatched_count":len(changed),
                     "changed_object_ids_sample":changed[:10]}
    if _sha(old_asset)!=old_before or _sha(new_asset)!=new_before:
        raise ValueError("Unity assets changed during raw graphic comparison")
    att_after=inspect_target(steam,repo/"config"/"supported-builds.json")
    if att_after.build_id!=att.build_id:
        raise ValueError("Steam build changed during raw graphics comparison")
    return {
        "schema":"spritesuite.steam-unity-raw-graphics-equivalence.v1",
        "previous_build":"local-shcde-2.80-unity-2021.3.45f2",
        "steam_target_build_id":att.build_id,
        "stream_resS_sha256_identical":streams_equal,
        "serialized_object_types":kinds,
        "all_sprite_texture_audio_serialized_bytes_equal":(
            streams_equal and all(x["raw_serialized_object_hashes_equal"] for x in kinds.values())
        ),
        "comparison_seconds":round(time.monotonic()-started,2),
        "steam_original_game_modified":False,
        "prior_game_modified":False,
        "native_abi_attestation":False,
        "source_sh1de_revalidated":False,
        "install_authorized":False,
    }


def main(argv=None)->int:
    parser=argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--old-game",type=Path,required=True)
    parser.add_argument("--steam-game",type=Path,required=True)
    parser.add_argument("--project",type=Path,required=True)
    parser.add_argument("--report",type=Path,required=True)
    args=parser.parse_args(argv)
    dest=args.report.resolve(strict=False)
    root=args.project.resolve(strict=True)
    if dest.exists() or root not in dest.parents:
        parser.error("Select a new private report file inside the project")
    report=compare(args.old_game,args.steam_game,args.project)
    dest.parent.mkdir(parents=True,exist_ok=True)
    with dest.open("x",encoding="utf8") as target:
        json.dump(report,target,ensure_ascii=False,indent=2)
        target.write("\n")
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0


if __name__=="__main__":
    raise SystemExit(main())

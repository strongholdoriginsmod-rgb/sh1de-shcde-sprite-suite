"""Generate a build-bound Steam mapping CANDIDATE after exact raw graphics proof.

This is a metadata-preserving migration in a separate work/ directory. It
NEVER replaces the active mapping, mutates game files, installs a mod, or
attests the unavailable SH1DE donor. Source validation is still mandatory.
"""
from __future__ import annotations

import argparse
from datetime import datetime,timezone
from hashlib import sha256
import json
from pathlib import Path
import re

from stronghold_europe_de.mapping import read_mapping,write_mapping
from stronghold_europe_de.unity_inventory import read_inventory
from steam_serialized_graphics_compare import compare as raw_compare
from target_selection_guard import inspect_target
from suite_output_transaction import OutputBatch
from suite_windows_paths import is_link_or_reparse
from suite_steam_compatibility import read_appmanifest, APPID


_OLD_TARGET="local-shcde-2.80-unity-2021.3.45f2"
_TARGET_GEOMETRY=(
    "width","height","rect_x","rect_y",
    "texture_name","pivot_x","pivot_y","pixels_per_unit",
)


def _sha(path:Path)->str:
    h=sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(4*1024*1024),b""):
            h.update(block)
    return h.hexdigest()


def validate_rebase_inputs(previous_mapping:dict,source:dict,
                           old_target:dict,steam_target:dict,
                           allowed_source_ids:set[str])->dict:
    if (previous_mapping.get("schema_version")!=2 or
        previous_mapping.get("target_build_id")!=_OLD_TARGET):
        raise ValueError("Previous mapping does not belong to verified 2.80 build")
    src_id=previous_mapping.get("source_build_id")
    if src_id not in allowed_source_ids:
        raise ValueError("Previous source build ID not in approved SH1DE references")
    if (source.get("role")!="source" or old_target.get("role")!="target"
        or steam_target.get("role")!="target"):
        raise ValueError("Inventory roles are inconsistent")
    entries=previous_mapping.get("sprites")
    if not isinstance(entries,list):
        raise ValueError("Previous mapping does not have a sprite list")
    summary=previous_mapping.get("sprite_summary",{})
    if (summary.get("source_count")!=len(source["sprites"])
        or summary.get("target_count")!=len(old_target["sprites"])
        or len(entries)!=len(steam_target["sprites"])):
        raise ValueError("Legacy mapping and inventory counts differ")
    lookups={x["path_id"]:x for x in steam_target["sprites"]}
    if len(lookups)!=len(steam_target["sprites"]):
        raise ValueError("Steam inventory has duplicate sprite path IDs")
    old_by={x["path_id"]:x for x in old_target["sprites"]}
    if len(old_by)!=len(old_target["sprites"]):
        raise ValueError("Old target inventory has duplicate sprite path IDs")
    seen=set()
    mismatches=[]
    for record in entries:
        if not isinstance(record,dict) or not isinstance(record.get("target"),dict):
            raise ValueError("Malformed old sprite mapping row")
        target=record["target"]
        path_id=target.get("path_id")
        before=old_by.get(path_id)
        after=lookups.get(path_id)
        if path_id in seen or before is None or after is None:
            mismatches.append(str(path_id))
            continue
        seen.add(path_id)
        if before!=after or record.get("name")!=after["name"] or any(
            target.get(k)!=after.get(k) for k in _TARGET_GEOMETRY
        ):
            mismatches.append(str(path_id))
    if mismatches or len(seen)!=len(lookups):
        raise ValueError("Some old mapping destinations differ from Steam; "
                         f"first mismatches: {mismatches[:8]}")
    return {"mapped_sprites":len(entries),
            "source_id":src_id,"target_geom_exact":True,
            "donor_source_current_sha_verified":False}


def create_preview(*,repo:Path,old_game:Path,steam_game:Path,
                   previous_mapping:Path,source_inventory:Path,
                   old_target_inventory:Path,steam_target_inventory:Path,
                   output_dir:Path)->dict:
    project=Path(repo).resolve(strict=True)
    steam=Path(steam_game).resolve(strict=True)
    out=Path(output_dir).resolve(strict=False)
    # Future Steam updates must be supported without hard-coding a build ID.
    # Every candidate is isolated per actually installed local Steam build.
    manifest=read_appmanifest(steam.parent.parent/f"appmanifest_{APPID}.acf")
    version=manifest["buildid"]
    allowed=project/"work"/f"steam-{version}"
    if (not (out==allowed/"candidate") or
        manifest["buildid"]!=manifest["TargetBuildID"] or
        manifest["StateFlags"]!="4" or
        out.exists() or
        any(is_link_or_reparse(item) for item in
            (out.parent, out, project/"work"))):
        raise ValueError("Select only a NEW private directory for the current Steam build")
    inputs=[Path(p) for p in (
        previous_mapping,source_inventory,old_target_inventory,
        steam_target_inventory
    )]
    if any(not path.is_file() or is_link_or_reparse(path) for path in inputs):
        raise ValueError("Missing/linked source inventory or old mapping")
    initial=[_sha(path) for path in inputs]
    old_map=read_mapping(inputs[0])
    source=read_inventory(inputs[1])
    prior=read_inventory(inputs[2])
    latest=read_inventory(inputs[3])
    ids={
        item["id"] for item in
        json.loads((project/"config"/"supported-builds.json").read_text("utf8"))["source_builds"]
    }
    records=validate_rebase_inputs(old_map,source,prior,latest,ids)
    proof=raw_compare(old_game,steam,project)
    if not proof["all_sprite_texture_audio_serialized_bytes_equal"]:
        raise ValueError("Raw Steam sprite/textures differ from old game: migration blocked")
    att=inspect_target(steam,project/"config"/"supported-builds.json")
    if att.build_id!=proof["steam_target_build_id"]:
        raise ValueError("Steam build changed during graphics proof")
    if Path(latest["asset_path"]).resolve(strict=True)!=(
        steam/"Stronghold Crusader Definitive Edition_Data"/"resources.assets").resolve(strict=True):
        raise ValueError("Steam inventory asset path does not match current game")
    evidence=inputs[3].with_suffix(".evidence.json")
    if (not evidence.is_file() or evidence.is_symlink()):
        raise ValueError("New Steam inventory lacks a verified receipt")
    doc=json.loads(evidence.read_text("utf8"))
    if (doc.get("target_build_id")!=att.build_id or
        doc.get("inventory_sha256")!=initial[3] or
        doc.get("steam_resources_sha256")!=_sha(
            steam/"Stronghold Crusader Definitive Edition_Data"/"resources.assets")):
        raise ValueError("Steam inventory provenance differs from current game")
    if [_sha(p) for p in inputs]!=initial:
        raise ValueError("Old source or Steam inventory changed during migration")
    result=dict(old_map)
    result["target_build_id"]=att.build_id
    result["generated_at_utc"]=datetime.now(timezone.utc).isoformat()
    receipt={
        "schema":"sprite-suite.steam-mapping-candidate.v1",
        "source_mapping_sha256":initial[0],
        "source_inventory_sha256":initial[1],
        "prior_target_inventory_sha256":initial[2],
        "steam_target_inventory_sha256":initial[3],
        "old_target_build_id":_OLD_TARGET,
        "steam_target_build_id":att.build_id,
        "source_build_id":records["source_id"],
        "mapped_sprites":records["mapped_sprites"],
        "all_mapped_geometry_verified":records["target_geom_exact"],
        "raw_graphic_equivalence_verified":True,
        "serialized_graphic_object_counts":proof["serialized_object_types"],
        "original_sh1de_source_revalidated":False,
        "native_engine_abi_revalidated":False,
        "writable_mod_install_approved":False,
        "actual_steam_installation_modified":False,
        "warning":"QA mapping candidate only. Never overwrite work/mapping/proposals.json.gz "
                  "without re-verifying the original SH1DE donor and completing game QA.",
    }
    with OutputBatch(out) as batch:
        target=batch.stage("steam-proposals.preview.json.gz")
        write_mapping(result,target)
        receipt["candidate_sha256"]=_sha(target)
        batch.stage("migration-evidence.json").write_text(
            json.dumps(receipt,indent=2,ensure_ascii=False)+"\n",encoding="utf8")
        batch.publish()
    assert _sha(out/"steam-proposals.preview.json.gz")==receipt["candidate_sha256"]
    return receipt


def main(argv:list[str]|None=None)->int:
    parser=argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for name in (
        "repo","old-game","steam-game","previous-mapping",
        "source-inventory","old-target-inventory","steam-target-inventory",
        "output-dir"):
        parser.add_argument("--"+name,type=Path,required=True)
    data=vars(parser.parse_args(argv))
    result=create_preview(**{
        "repo":data["repo"],"old_game":data["old_game"],
        "steam_game":data["steam_game"],
        "previous_mapping":data["previous_mapping"],
        "source_inventory":data["source_inventory"],
        "old_target_inventory":data["old_target_inventory"],
        "steam_target_inventory":data["steam_target_inventory"],
        "output_dir":data["output_dir"],
    })
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0


if __name__=="__main__":
    raise SystemExit(main())

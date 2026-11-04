"""Promote an exact Steam graphics mapping only into a NEW isolated QA workspace.

Require verified original SH1DE donor, current Steam game, previous known 2.80
original, independent serialized graphic equality, and immutable candidate.
Do not create game-target registry, change Steam, modify an existing mapping,
install native code, or authorize Noesis/in-game modifications.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

from stronghold_europe_de.config import Installation
from stronghold_europe_de.fingerprint import fingerprint_installation
from stronghold_europe_de.builds import match_fingerprint,installation_build_id
from stronghold_europe_de.mapping import read_mapping
from steam_serialized_graphics_compare import compare as raw_compare
from target_selection_guard import (
    inspect_target,verify_source,verify_target,DATA,
)
from suite_output_transaction import OutputBatch
from suite_windows_paths import is_link_or_reparse


def _sha(path:Path)->str:
    h=sha256()
    with Path(path).open("rb") as file:
        for chunk in iter(lambda:file.read(4*1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()


def _source_build_id(source:Path,repo:Path)->str:
    source_data=verify_source(source,repo/"config"/"supported-builds.json")
    fingerprint=fingerprint_installation(
        Installation("Verified SH1DE original",source_data))
    builds=json.loads((repo/"config"/"supported-builds.json").read_text("utf8"))
    pinned=match_fingerprint(fingerprint,builds["source_builds"])
    return pinned or installation_build_id("source",fingerprint)


def promote(*,repo:Path,source:Path,steam_game:Path,old_game:Path,
            candidate:Path,old_mapping:Path)->dict:
    root=Path(repo).resolve(strict=True)
    steam=Path(steam_game).resolve(strict=True)
    candidate=Path(candidate).resolve(strict=True)
    old_map=Path(old_mapping).resolve(strict=True)
    target_dir=root/"work"/"mapping"
    if (target_dir.exists() or
        any(is_link_or_reparse(path) for path in (
            target_dir, target_dir.parent,root/"work"))
        or root/"work" not in candidate.parents
        or candidate.name!="steam-proposals.preview.json.gz"):
        raise ValueError("Only a new private work/mapping is allowed")
    if any(is_link_or_reparse(x) for x in (old_map,candidate)):
        raise ValueError("Linked mapping files are forbidden")
    receipt_path=candidate.parent/"migration-evidence.json"
    if not receipt_path.is_file() or is_link_or_reparse(receipt_path):
        raise ValueError("Candidate has no independently verifiable receipt")
    doc=json.loads(receipt_path.read_text("utf8"))
    if (doc.get("schema")!="sprite-suite.steam-mapping-candidate.v1"
        or doc.get("raw_graphic_equivalence_verified") is not True
        or doc.get("all_mapped_geometry_verified") is not True
        or doc.get("original_sh1de_source_revalidated") is not False
        or doc.get("writable_mod_install_approved") is not False
        or doc.get("candidate_sha256")!=_sha(candidate)
        or doc.get("source_mapping_sha256")!=_sha(old_map)):
        raise ValueError("Previous Steam mapping candidate proof is not trustworthy")
    old=read_mapping(old_map)
    proposed=read_mapping(candidate)
    if (old.get("source_build_id")!=doc.get("source_build_id") or
        proposed.get("source_build_id")!=doc.get("source_build_id") or
        proposed.get("target_build_id")!=doc.get("steam_target_build_id") or
        proposed.get("schema_version")!=2):
        raise ValueError("Source and target IDs have been changed")
    expected=dict(old)
    expected["target_build_id"]=proposed["target_build_id"]
    expected["generated_at_utc"]=proposed.get("generated_at_utc")
    if proposed!=expected:
        raise ValueError("Mapping contents changed beyond target identity/timestamp")
    before=_source_build_id(source,root)
    if before!=proposed["source_build_id"]:
        raise ValueError("Actual SH1DE donor is not the mapped original source build")
    att=inspect_target(steam,root/"config"/"supported-builds.json")
    if att.build_id!=proposed["target_build_id"]:
        raise ValueError("Current Steam game changed since candidate creation")
    full=raw_compare(old_game,steam,root)
    if (not full["all_sprite_texture_audio_serialized_bytes_equal"] or
        full["steam_target_build_id"]!=att.build_id):
        raise ValueError("Current Steam graphics no longer match the old target")
    after=_source_build_id(source,root)
    if before!=after:
        raise ValueError("SH1DE original source changed while verifying")
    if (_sha(old_map)!=doc["source_mapping_sha256"]
        or _sha(candidate)!=doc["candidate_sha256"]):
        raise ValueError("Candidate or source mapping changed during verification")
    proof={
        "schema":"sprite-suite.steam-mapping-promotion.v1",
        "steam_target_build_id":att.build_id,
        "source_build_id":before,
        "source_five_original_files_verified":True,
        "steam_five_original_files_verified":True,
        "previous_280_original_binary_art_verified":True,
        "all_sprite_texture_audio_bytes_identical":True,
        "mapped_sprites":doc["mapped_sprites"],
        "active_mapping_sha256":doc["candidate_sha256"],
        "original_mapping_unchanged":True,
        "steam_original_game_modified":False,
        "sh1de_original_game_modified":False,
        "no_steam_game_install_target_registered":True,
        "native_engine_abi_approved":False,
        "noesis_ingame_qa_approved":False,
        "user_mod_installation_approved":False,
        "note":"Read-only SpriteSuite QA mapping. Mod builds still need explicit "
               "version-matched target selection and independent validation.",
    }
    with OutputBatch(target_dir) as transaction:
        path=transaction.stage("proposals.json.gz")
        # Byte-for-byte copy preserves authored source/review overrides.
        path.write_bytes(candidate.read_bytes())
        transaction.stage("steam-mapping-provenance.json").write_text(
            json.dumps(proof,indent=2,ensure_ascii=False)+"\n",encoding="utf8")
        transaction.publish()
    activated=target_dir/"proposals.json.gz"
    if _sha(activated)!=doc["candidate_sha256"]:
        raise RuntimeError("The new QA mapping differs from proof")
    verified=verify_target(steam,root/"config"/"supported-builds.json",activated)
    if verified.build_id!=att.build_id:
        raise RuntimeError("Version gate rejected newly pinned QA mapping")
    return proof


def main(argv:list[str]|None=None)->int:
    parser=argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for key in ("repo","source","steam-game","old-game","candidate","old-mapping"):
        parser.add_argument("--"+key,type=Path,required=True)
    args=parser.parse_args(argv)
    proof=promote(repo=args.repo,source=args.source,
                  steam_game=args.steam_game,old_game=args.old_game,
                  candidate=args.candidate,old_mapping=args.old_mapping)
    print(json.dumps(proof,ensure_ascii=False,indent=2))
    return 0


if __name__=="__main__":
    raise SystemExit(main())

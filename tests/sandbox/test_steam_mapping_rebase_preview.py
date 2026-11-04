"""Steam graphics mapping migration: exact input proofs and no active mapping writes."""
from __future__ import annotations

import gzip
from hashlib import sha256
import json
from pathlib import Path
import sys

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"tools"))
import steam_mapping_rebase_preview as migrator
from stronghold_europe_de.mapping import read_mapping,write_mapping
from stronghold_europe_de.unity_inventory import write_inventory
from target_selection_guard import inspect_target,CANONICAL,DATA


def digest(path:Path)->str:
    with Path(path).open("rb") as f:
        return sha256(f.read()).hexdigest()


@pytest.fixture
def setup_pair(tmp_path,monkeypatch):
    repo=tmp_path/"independent-project"
    config=repo/"config"
    config.mkdir(parents=True)
    oldgame=tmp_path/"old-original-280"
    oldgame.mkdir()
    steamroot=tmp_path/"Steam"/"steamapps"
    steam=steamroot/"common"/"Stronghold Crusader Definitive Edition"
    data=steam/DATA
    data.mkdir(parents=True)
    canonical=[]
    for index,name in enumerate(CANONICAL):
        file=data/name
        file.parent.mkdir(parents=True,exist_ok=True)
        file.write_bytes(f"mock steam canonical {index}".encode())
        canonical.append({"relative_path":name,
                          "size":file.stat().st_size,
                          "sha256":digest(file)})
    (config/"supported-builds.json").write_text(json.dumps({
        "source_builds":[{"id":"source-old-pinned","files":[]}],
        "target_builds":[{"id":"local-shcde-2.80-unity-2021.3.45f2",
                          "files":canonical}],
    }),encoding="utf8")
    manifest=steamroot/"appmanifest_3024040.acf"
    manifest.write_text(
        '"AppState"\n{\n'
        '"appid" "3024040"\n'
        '"name" "Stronghold Crusader: Definitive Edition"\n'
        '"installdir" "Stronghold Crusader Definitive Edition"\n'
        '"buildid" "99999"\n'
        '"TargetBuildID" "99999"\n'
        '"StateFlags" "4"\n'
        '"LastUpdated" "1792600000"\n}\n',encoding="utf8")
    ident=inspect_target(steam,config/"supported-builds.json").build_id
    target_sprite={"name":"tree-001","path_id":42,
                   "width":12.0,"height":16.0,
                   "rect_x":7.0,"rect_y":9.0,
                   "texture_name":"Tree",
                   "pivot_x":.5,"pivot_y":.2,
                   "pixels_per_unit":64.0}
    oldmap={
        "schema_version":2,
        "source_build_id":"source-old-pinned",
        "target_build_id":"local-shcde-2.80-unity-2021.3.45f2",
        "sprite_summary":{"source_count":1,"target_count":1},
        "sprites":[{"name":"tree-001","target":target_sprite,
                    "source":{"path_id":11,"name":"SH1tree"},
                    "action":"REPLACE_EXACT","confidence":.99}],
        "audio_clips":[],
    }
    inventory_root=tmp_path/"input-inventories"
    inventory_root.mkdir()
    mapping=inventory_root/"old-proposals.json.gz"
    write_mapping(oldmap,mapping)
    files=[]
    for name,role,sprites in (
        ("source","source",[{"path_id":11,"name":"SH1tree"}]),
        ("prior-target","target",[target_sprite]),
        ("steam-target","target",[target_sprite]),
    ):
        file=inventory_root/(name+".resources.json.gz")
        raw={"schema_version":1,"role":role,
             "asset_path":str((data/"resources.assets").resolve()),
             "sprites":sprites,"textures":[],"audio_clips":[]}
        write_inventory(raw,file)
        files.append(file)
    fresh=files[2]
    evidence=fresh.with_suffix(".evidence.json")
    evidence.write_text(json.dumps({
        "schema":"sprite-suite.steam-target-inventory.v1",
        "target_build_id":ident,
        "inventory_sha256":digest(fresh),
        "steam_resources_sha256":digest(data/"resources.assets"),
    }),encoding="utf8")
    monkeypatch.setattr(migrator,"raw_compare",lambda a,b,c:{
        "steam_target_build_id":ident,
        "all_sprite_texture_audio_serialized_bytes_equal":True,
        "serialized_object_types":{"Sprite":{"prior_objects":1,"steam_objects":1,
                                              "raw_serialized_object_hashes_equal":True}},
    })
    out=repo/"work"/"steam-99999"/"candidate"
    return repo,oldgame,steam,mapping,*files,out,ident


def do_rebase(t):
    repo,oldgame,steam,mapping,source,prior,new,out,_id=t
    return migrator.create_preview(
        repo=repo,old_game=oldgame,steam_game=steam,
        previous_mapping=mapping,source_inventory=source,
        old_target_inventory=prior,steam_target_inventory=new,
        output_dir=out,
    )


def test_complete_synthetic_source_target_rebase_preserves_all_inputs(setup_pair):
    t=setup_pair
    inputs=list(t[3:7])
    previous={p.name:p.read_bytes() for p in inputs}
    result=do_rebase(t)
    repo,oldgame,steam,mapping,source,prior,new,out,ident=t
    candidate=out/"steam-proposals.preview.json.gz"
    receipt=out/"migration-evidence.json"
    assert result["mapped_sprites"]==1
    assert result["steam_target_build_id"]==ident
    assert result["raw_graphic_equivalence_verified"] is True
    assert result["original_sh1de_source_revalidated"] is False
    assert result["writable_mod_install_approved"] is False
    assert read_mapping(candidate)["target_build_id"]==ident
    assert read_mapping(candidate)["source_build_id"]=="source-old-pinned"
    assert digest(candidate)==result["candidate_sha256"]
    assert json.loads(receipt.read_text("utf8"))==result
    assert not (repo/"work"/"mapping"/"proposals.json.gz").exists()
    assert {p.name:p.read_bytes() for p in inputs}==previous


def test_changed_sprite_geometry_is_blocking_even_if_raw_comparison_claims_equal(setup_pair):
    t=setup_pair
    source=t[4]
    prior=t[5]
    fake=migrator.read_inventory(prior)
    fake["sprites"][0]["width"]=99
    write_inventory(fake,prior)
    with pytest.raises(ValueError,match="Some old mapping destinations"):
        do_rebase(t)
    assert not t[7].exists()


def test_raw_byte_mismatch_refuses_mapping_candidate(setup_pair,monkeypatch):
    t=setup_pair
    proof={
        "all_sprite_texture_audio_serialized_bytes_equal":False,
        "steam_target_build_id":t[8],
        "serialized_object_types":{},
    }
    monkeypatch.setattr(migrator,"raw_compare",lambda *_a:proof)
    with pytest.raises(ValueError,match="Raw Steam"):
        do_rebase(t)
    assert not t[7].exists()


def test_source_identity_must_be_one_of_pinned_source_builds(setup_pair):
    t=setup_pair
    repo,oldgame,steam,mapping,source,prior,new,out,ident=t
    m=read_mapping(mapping)
    m["source_build_id"]="unauthorized-source-build"
    write_mapping(m,mapping)
    with pytest.raises(ValueError,match="approved SH1DE"):
        do_rebase(t)
    assert not out.exists()


def test_refuse_existing_candidate_and_never_overwrite_active_mapping(setup_pair):
    t=setup_pair
    do_rebase(t)
    with pytest.raises(ValueError,match="NEW private"):
        do_rebase(t)
    assert not (t[0]/"work"/"mapping"/"proposals.json.gz").exists()


def test_direct_active_mapping_path_is_forbidden(setup_pair):
    t=setup_pair
    repo,oldgame,steam,mapping,source,prior,new,out,ident=t
    with pytest.raises(ValueError,match="NEW private"):
        migrator.create_preview(
            repo=repo,old_game=oldgame,steam_game=steam,
            previous_mapping=mapping,source_inventory=source,
            old_target_inventory=prior,steam_target_inventory=new,
            output_dir=repo/"work"/"mapping",
        )
    assert not (repo/"work"/"mapping").exists()


def test_invalid_target_inventory_receipt_blocks_without_output(setup_pair):
    t=setup_pair
    latest=t[6]
    latest.with_suffix(".evidence.json").write_bytes(b'{"not-a-real-receipt":0}')
    with pytest.raises(ValueError,match="provenance"):
        do_rebase(t)
    assert not t[7].exists()


def test_actual_steam_candidate_is_separate_and_bound_to_exact_build():
    repo=ROOT
    candidate=repo/"work"/"steam-24816905"/"candidate"/"steam-proposals.preview.json.gz"
    receipt=candidate.parent/"migration-evidence.json"
    if not candidate.is_file() or not receipt.is_file():
        pytest.skip("Private Steam mapping migration was not executed on this QA machine")
    proof=json.loads(receipt.read_text("utf8"))
    reloaded=read_mapping(candidate)
    att=inspect_target(
        Path(r"C:\Program Files (x86)\Steam\steamapps\common\Stronghold Crusader Definitive Edition"),
        repo/"config"/"supported-builds.json",
    )
    if reloaded["target_build_id"]!=att.build_id:
        pytest.skip("Steam updated since this original QA candidate; reimport required")
    assert proof["candidate_sha256"]==digest(candidate)
    assert len(reloaded["sprites"])==135354
    assert not proof["writable_mod_install_approved"]
    assert not proof["original_sh1de_source_revalidated"]


def _prepare_promotion(t,tmp_path,monkeypatch):
    from steam_mapping_promote import promote
    import steam_mapping_promote as promoted
    repo,oldgame,steam,mapping,src_inventory,old_target,steam_inv,out,steam_id=t
    do_rebase(t)
    source=tmp_path/"Stronghold 1 Definitive Edition_Data"
    source.mkdir()
    source_files=[]
    for i,rel in enumerate(CANONICAL):
        path=source/rel
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes((f"SH1-original-{i}").encode())
        source_files.append({
            "relative_path":rel,"size":path.stat().st_size,
            "sha256":digest(path),
        })
    builds_file=repo/"config"/"supported-builds.json"
    builds=json.loads(builds_file.read_text("utf8"))
    builds["source_builds"][0]["files"]=source_files
    builds_file.write_text(json.dumps(builds),encoding="utf8")
    monkeypatch.setattr(promoted,"raw_compare",lambda *_args:{
        "steam_target_build_id":steam_id,
        "all_sprite_texture_audio_serialized_bytes_equal":True,
    })
    kwargs={
        "repo":repo,"source":source,"steam_game":steam,
        "old_game":oldgame,
        "candidate":out/"steam-proposals.preview.json.gz",
        "old_mapping":mapping,
    }
    return kwargs,source


def test_true_source_attestation_promotes_into_only_private_work_mapping(
    setup_pair,tmp_path,monkeypatch,
):
    import steam_mapping_promote as promoted
    kwargs,source=_prepare_promotion(setup_pair,tmp_path,monkeypatch)
    repo=kwargs["repo"]
    target=kwargs["steam_game"]
    before={p.name:p.read_bytes() for p in source.rglob("*") if p.is_file()}
    proof=promoted.promote(**kwargs)
    live=repo/"work"/"mapping"/"proposals.json.gz"
    assert live.is_file()
    assert proof["source_five_original_files_verified"]
    assert proof["steam_five_original_files_verified"]
    assert proof["all_sprite_texture_audio_bytes_identical"]
    assert proof["no_steam_game_install_target_registered"]
    assert not proof["user_mod_installation_approved"]
    assert not (repo/"config"/"installations.local.toml").exists()
    assert not (repo/"config"/"ziele.json").exists()
    assert not (target/"BepInEx").exists()
    assert read_mapping(live)["target_build_id"]==setup_pair[8]
    assert {p.name:p.read_bytes() for p in source.rglob("*") if p.is_file()}==before
    with pytest.raises(ValueError,match="new private"):
        promoted.promote(**kwargs)


def test_source_changed_after_preview_blocks_release_without_active_mapping(
    setup_pair,tmp_path,monkeypatch,
):
    import steam_mapping_promote as promoted
    kwargs,source=_prepare_promotion(setup_pair,tmp_path,monkeypatch)
    source.joinpath("Managed","Assembly-CSharp.dll").write_bytes(b"different SH1 build")
    with pytest.raises(ValueError,match="Actual SH1DE donor"):
        promoted.promote(**kwargs)
    assert not (kwargs["repo"]/"work"/"mapping").exists()


def test_candidate_forgery_does_not_activate_mapping(
    setup_pair,tmp_path,monkeypatch,
):
    import steam_mapping_promote as promoted
    kwargs,source=_prepare_promotion(setup_pair,tmp_path,monkeypatch)
    path=kwargs["candidate"]
    path.write_bytes(b"forged preview")
    with pytest.raises(ValueError,match="not trustworthy"):
        promoted.promote(**kwargs)
    assert not (kwargs["repo"]/"work"/"mapping").exists()


def test_fake_new_steam_version_cannot_reuse_old_candidate(
    setup_pair,tmp_path,monkeypatch,
):
    import steam_mapping_promote as promoted
    kwargs,source=_prepare_promotion(setup_pair,tmp_path,monkeypatch)
    newest=kwargs["steam_game"]/DATA/"Managed"/"Assembly-CSharp.dll"
    newest.write_bytes(b"modified steam game build")
    with pytest.raises(ValueError,match="Steam game changed"):
        promoted.promote(**kwargs)
    assert not (kwargs["repo"]/"work"/"mapping").exists()

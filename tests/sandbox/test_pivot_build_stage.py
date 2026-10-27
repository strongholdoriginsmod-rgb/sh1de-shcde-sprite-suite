"""A human-approved Pivot is a pinned build *intent*, not an atlas patch."""
from __future__ import annotations

from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys

from PIL import Image
import pytest

from stronghold_europe_de.pivot_approvals import (
    PivotDecision, save_approval_report,
)
from stronghold_europe_de.pivot_measurements import (
    load_measurements, review_measurements,
)
from stronghold_europe_de.pivot_build_stage import (
    SCHEMA, PivotStageError, prepare_pivot_build_stage, save_pivot_build_stage,
)

PROFILE = "test-pivot-bc7"
GROUP = "anim_castle"


def _json(path, value):
    payload = (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return payload


def _record(path, category, payload):
    return {"relative_path":path, "category":category,
            "sha256":sha256(payload).hexdigest(),"size":len(payload)}


def _world(tmp_path, status="pruefen", with_decision=True):
    root = tmp_path
    game = root/"dist"/PROFILE/"StrongholdEuropeDE"
    mod_info = {"GUID":"strongholdeuropede.testing","Version":"1.0",
                "Name":"Testmod", "Manifest":0}
    profile = root/"profiles"/f"{PROFILE}.json"
    _json(profile,{
        "id":PROFILE,"schema_version":1,"mod_info":mod_info,
        "atlas_backend":{"kind":"unity_assetbundle_bc7_visual_equivalence_v2"},
        "gm_atlases":[{
            "gm_file_name":GROUP,"geometry_policy":{
                "mode":"native_source_reanchored_v1",
                "expected_geometry_proof_sha256":"a"*64,
                "expected_origin_proof_sha256":"b"*64,
            },
            "review_frame_policy":{
                "mode":"source_native_geometry_else_keep_v3",
                "expected_provenance_sha256":"c"*64,
            },
        }],
    })
    bundlepath="Runtime/AssetBundles/win64/sede.gm.anim_castle.bc7.v2"
    bundle=b"Fake bundle fixture"
    (game/bundlepath).parent.mkdir(parents=True,exist_ok=True)
    (game/bundlepath).write_bytes(bundle)
    bundlehash=sha256(bundle).hexdigest()
    idxpath="Runtime/AssetBundles/index.json"
    index=_json(game/idxpath,{
        "backend_kind":"unity_assetbundle_bc7_visual_equivalence_v2",
        "groups":[{"group":GROUP,"slug":GROUP,"gm_id":54,
                   "atlas_sha256":"a"*64,"frames_sha256":"b"*64,
                   "bundle_path":bundlepath,"bundle_sha256":bundlehash}],
    })
    info=_json(game/"info.json",mod_info)
    runtime=(game/"StrongholdEuropeDE.Runtime.dll")
    runtime.write_bytes(b"fixture runtime")
    _json(game/"build-manifest.json",{
        "schema_version":1,"profile_id":PROFILE,"mod_info":mod_info,
        "outputs":[
            _record(idxpath,"asset_bundle_index",index),
            _record(bundlepath,"asset_bundle",bundle),
            _record("info.json","mod_metadata",info),
            _record(runtime.name,"runtime",runtime.read_bytes()),
        ],
    })
    delivered=root/"work"/"katalog"/"geliefert"/GROUP
    delivered.mkdir(parents=True,exist_ok=True)
    sprite=delivered/"anim_castle 002.png"
    Image.new("RGBA",(333,165),(15,70,145,255)).save(sprite)
    old_y=1.10909091 if status=="pruefen" else 1.0
    sprite_index=delivered/"index.json"
    _json(sprite_index,{
        "group":GROUP,"frames":[{
            "name":"anim_castle 002","file":sprite.name,
            "width":333,"height":165,"pivot_x":0.0,"pivot_y":old_y,
        }],
    })
    measured=root/"Zinnenlineal"/"zinnen-versatz.json"
    _json(measured,{"schema":"zinnenlineal.versatz.v1","frames":[{
        "name":"anim_castle 002","gruppe":GROUP,"nummer":2,
        "rechts":0,"hoch":18,"breite":333,"hoehe":165,
        "pivot_x":0.0,"pivot_y":1.10909091,
        "neu_pivot_x":0.0,"neu_pivot_y":1.0,
    }]})
    source=load_measurements(measured)
    checks=review_measurements(source,root)
    assert checks[0].status==status
    action = "freigegeben" if status=="pruefen" else "abgelehnt"
    if with_decision:
        approval=save_approval_report(
            source,checks,root,{"anim_castle 002":PivotDecision(
                action,recorded_at="2026-10-11T19:22:00+00:00"
            )}
        )
    else:
        approval=None
    return profile,game,sprite_index,sprite,measured,approval


def _build(root,approval,measured):
    return prepare_pivot_build_stage(root,PROFILE,approval,measured)


def test_verified_change_intent_is_not_a_bc7_patch(tmp_path):
    profile,game,source_idx,sprite,measured,approval=_world(tmp_path)
    important=[profile,game/"build-manifest.json",game/"Runtime/AssetBundles/index.json",
               source_idx,sprite,measured,approval]
    before={path:path.read_bytes() for path in important}
    plan=_build(tmp_path,approval,measured)
    assert plan["schema"]==SCHEMA
    assert plan["state"]=="requires_separate_bc7_rebuild"
    assert plan["installation_allowed"] is False
    assert plan["change_count"]==1
    entry=plan["changes"][0]
    assert entry["name"]=="anim_castle 002"
    assert entry["old_pivot"]==[0.0,1.10909091]
    assert entry["proposed_pivot"]==[0.0,1.0]
    assert entry["size"]==[333,165] and entry["measured_offset_px"]==[0,18]
    assert entry["geometry_policy"]["mode"]=="native_source_reanchored_v1"
    assert entry["review_frame_policy"]["expected_provenance_sha256"]=="c"*64
    assert entry["requires_proof_recalculation"]
    assert entry["requires_bundle_rebuild"]
    assert entry["application_allowed"] is False
    assert plan["baseline"]["verified_outputs"]==4
    assert plan["source_hashes"]["bundle_index_sha256"]==sha256(
        (game/"Runtime/AssetBundles/index.json").read_bytes()
    ).hexdigest()
    assert not (tmp_path/"work"/"reports"/"pivot-bc7-stage").exists()
    assert all(path.read_bytes()==v for path,v in before.items())

    output=save_pivot_build_stage(plan,tmp_path)
    assert output.parent==tmp_path/"work"/"reports"/"pivot-bc7-stage"
    assert output.is_file()
    assert save_pivot_build_stage(plan,tmp_path)==output
    assert sorted(output.parent.iterdir())==[output]
    assert json.loads(output.read_text(encoding="utf-8"))==plan
    assert all(path.read_bytes()==v for path,v in before.items())


@pytest.mark.parametrize("tamper",["measurement","png","index","manifest","bundle","profile"])
def test_edited_sources_fail_closed_before_stage_write(tmp_path,tamper):
    profile,game,index,sprite,measured,approval=_world(tmp_path)
    paths={
        "measurement":measured,"png":sprite,"index":index,
        "manifest":game/"build-manifest.json",
        "bundle":game/"Runtime/AssetBundles/win64/sede.gm.anim_castle.bc7.v2",
        "profile":profile,
    }
    current=paths[tamper].read_bytes()
    if tamper=="manifest":
        paths[tamper].write_bytes(current+b" INVALID")  # malformed JSON
    elif tamper=="profile":
        doc=json.loads(current.decode("utf-8"))
        doc["id"]="unrelated-profile"
        _json(paths[tamper],doc)
    else:
        paths[tamper].write_bytes(current+b"\n ")
    with pytest.raises(PivotStageError):
        _build(tmp_path,approval,measured)
    assert not (tmp_path/"work"/"reports"/"pivot-bc7-stage").exists()


def test_changes_after_preparation_fail_at_save_gate(tmp_path):
    _,_,_,sprite,measured,approval=_world(tmp_path)
    plan=_build(tmp_path,approval,measured)
    with Image.open(sprite) as original:
        img=original.copy()
    img.putpixel((1,1),(244,100,80,255))
    img.save(sprite)
    with pytest.raises(PivotStageError,match="Quellen|ungültig|widerspricht"):
        save_pivot_build_stage(plan,tmp_path)
    assert not (tmp_path/"work"/"reports"/"pivot-bc7-stage").exists()


def test_corrupt_approval_even_with_renamed_digest_is_blocked(tmp_path):
    _,_,_,_,measured,approval=_world(tmp_path)
    document=json.loads(approval.read_text(encoding="utf-8"))
    document["rows"][0]["measured_new"]=[0.0,0.875]
    payload=(json.dumps(document,sort_keys=True,ensure_ascii=False,indent=2)+"\n").encode("utf-8")
    tampered=approval.with_name(
        f"zinnen-entscheidung-{document['measurement_sha256'][:12]}-"
        f"{sha256(payload).hexdigest()[:16]}.json"
    )
    tampered.write_bytes(payload)
    with pytest.raises(PivotStageError,match="measured_new"):
        _build(tmp_path,tampered,measured)


def test_changed_approval_data_with_original_filename_is_blocked(tmp_path):
    _,_,_,_,measured,approval=_world(tmp_path)
    document=json.loads(approval.read_text(encoding="utf-8"))
    document["approved_count"]=0
    _json(approval,document)
    with pytest.raises(PivotStageError,match="dateiname"):
        _build(tmp_path,approval,measured)


def test_unselected_external_approval_is_rejected(tmp_path):
    _,_,_,_,measured,approval=_world(tmp_path)
    other=tmp_path/"unreviewed.json"
    other.write_bytes(approval.read_bytes())
    with pytest.raises(PivotStageError,match="berichtordner"):
        _build(tmp_path,other,measured)


def test_explicit_original_measurement_must_match_path(tmp_path):
    _,_,_,_,measured,approval=_world(tmp_path)
    copy=tmp_path/"moved-zinnen-versatz.json"
    copy.write_bytes(measured.read_bytes())
    with pytest.raises(PivotStageError,match="damals geprüfte Datei"):
        _build(tmp_path,approval,copy)


def test_wrong_profile_identity_and_unpublished_build_are_blocked(tmp_path):
    _,game,_,_,measured,approval=_world(tmp_path)
    with pytest.raises(PivotStageError):
        prepare_pivot_build_stage(tmp_path,"../other",approval,measured)
    with pytest.raises(PivotStageError):
        prepare_pivot_build_stage(tmp_path,"other-profile",approval,measured)
    (game/"build-manifest.json").unlink()
    with pytest.raises(PivotStageError,match="Produktionsstand"):
        _build(tmp_path,approval,measured)


def test_no_approved_changes_yields_explicit_noop_stage(tmp_path):
    _,_,_,_,measured,approval=_world(tmp_path)
    report=json.loads(approval.read_text(encoding="utf-8"))
    report["rows"][0]["decision"]="abgelehnt"
    report["approved_count"]=0
    report["rejected_count"]=1
    payload=(json.dumps(report,sort_keys=True,ensure_ascii=False,indent=2)+"\n").encode("utf-8")
    altered=approval.with_name(
        f"zinnen-entscheidung-{report['measurement_sha256'][:12]}-"
        f"{sha256(payload).hexdigest()[:16]}.json"
    )
    altered.write_bytes(payload)
    result=_build(tmp_path,altered,measured)
    assert result["state"]=="no_changes"
    assert result["change_count"]==0
    assert not result["changes"]


def test_already_correct_anim_castle_can_never_be_staged_as_approved(tmp_path):
    _,_,_,_,measured,approval=_world(tmp_path,status="bereits_passend")
    with pytest.raises(PivotStageError,match="Ablehnung ohne prüfbare"):
        _build(tmp_path,approval,measured)
    report=json.loads(approval.read_text(encoding="utf-8"))
    report["rows"][0]["decision"]="freigegeben"
    report["approved_count"]=1
    report["rejected_count"]=0
    payload=(json.dumps(report,sort_keys=True,ensure_ascii=False,indent=2)+"\n").encode("utf-8")
    altered=approval.with_name(
        f"zinnen-entscheidung-{report['measurement_sha256'][:12]}-"
        f"{sha256(payload).hexdigest()[:16]}.json"
    )
    altered.write_bytes(payload)
    with pytest.raises(PivotStageError,match="keine gültige"):
        _build(tmp_path,altered,measured)


def test_cli_consumes_explicit_inputs_and_does_not_mutate_artifacts(tmp_path,monkeypatch):
    path=Path(__file__).resolve().parents[2]/"tools"/"pivot_bc7_stage.py"
    spec=importlib.util.spec_from_file_location("pivot_bc7_stage_test_cli",path)
    cli=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    _,game,_,sprite,measured,approval=_world(tmp_path)
    before=(game/"build-manifest.json").read_bytes()
    monkeypatch.setattr(cli,"ROOT",tmp_path)
    args=["--profile",PROFILE,"--approval",str(approval),"--measurement",str(measured)]
    assert cli.main(args+["--check-only"])==0
    assert not (tmp_path/"work"/"reports"/"pivot-bc7-stage").exists()
    assert cli.main(args)==0
    assert len(list((tmp_path/"work"/"reports"/"pivot-bc7-stage").glob("*.json")))==1
    assert (game/"build-manifest.json").read_bytes()==before


def test_stage_output_directory_link_is_rejected(tmp_path,monkeypatch):
    import stronghold_europe_de.pivot_build_stage as module
    _,_,_,_,measured,approval=_world(tmp_path)
    report=_build(tmp_path,approval,measured)
    forbidden=tmp_path/"work"/"reports"/"pivot-bc7-stage"
    original=module._is_link
    monkeypatch.setattr(module,"_is_link",lambda path:
                        Path(path)==forbidden or original(path))
    with pytest.raises(PivotStageError,match="Link/Junction"):
        save_pivot_build_stage(report,tmp_path)
    assert not forbidden.exists()


@pytest.mark.parametrize("tamper",["profile","manifest"])
def test_stage_save_rejects_source_byte_drift_even_when_semantics_same(tmp_path,tamper):
    profile,game,_,_,measured,approval=_world(tmp_path)
    report=_build(tmp_path,approval,measured)
    selected=profile if tamper=="profile" else game/"build-manifest.json"
    selected.write_bytes(selected.read_bytes()+b" \n")
    with pytest.raises(PivotStageError,match="Quellen|Build seit"):
        save_pivot_build_stage(report,tmp_path)
    assert not (tmp_path/"work"/"reports"/"pivot-bc7-stage").exists()


def test_forged_boolean_pivot_is_not_numeric_provenance(tmp_path):
    _,_,_,_,measured,approval=_world(tmp_path)
    doc=json.loads(approval.read_text(encoding="utf-8"))
    doc["rows"][0]["measured_new"]=[False,True]
    payload=(json.dumps(doc,ensure_ascii=False,sort_keys=True,indent=2)+"\n").encode("utf-8")
    forged=approval.with_name(
        f"zinnen-entscheidung-{doc['measurement_sha256'][:12]}-"
        f"{sha256(payload).hexdigest()[:16]}.json"
    )
    forged.write_bytes(payload)
    with pytest.raises(PivotStageError,match="measured_new"):
        _build(tmp_path,forged,measured)


def test_already_correct_frame_is_skipped_in_mixed_stage(tmp_path):
    _,_,index,sprite,measured,_=_world(tmp_path)
    document=json.loads(index.read_text(encoding="utf-8"))
    document["frames"][0]["pivot_y"]=1.0  # already corrected!
    secondary={
        "name":"anim_castle 003","file":"anim_castle 003.png",
        "width":333,"height":165,"pivot_x":0.0,"pivot_y":1.10909091,
    }
    document["frames"].append(secondary)
    _json(index,document)
    Image.new("RGBA",(333,165),(56,70,144,255)).save(sprite.parent/secondary["file"])
    contents=json.loads(measured.read_text(encoding="utf-8"))
    second=dict(contents["frames"][0],name="anim_castle 003",nummer=3)
    contents["frames"].append(second)
    _json(measured,contents)
    measured_obj=load_measurements(measured)
    checks=review_measurements(measured_obj,tmp_path)
    assert [r.status for r in checks]==["bereits_passend","pruefen"]
    approval=save_approval_report(
        measured_obj,checks,tmp_path,{
            "anim_castle 003":PivotDecision(
                "freigegeben",recorded_at="2026-10-11T19:22:00+00:00"
            )
        }
    )
    preview=_build(tmp_path,approval,measured)
    assert preview["change_count"]==1
    assert [r["name"] for r in preview["changes"]]==["anim_castle 003"]
    assert preview["changes"][0]["application_allowed"] is False


def test_published_bc7_already_matches_approval_and_stage_is_noop(tmp_path,monkeypatch):
    import stronghold_europe_de.pivot_build_stage as stage_module
    _,_,_,_,measured,approval=_world(tmp_path)
    sentinel=object()
    monkeypatch.setattr(stage_module,"locate_published_group",
                        lambda root,index:sentinel)
    inspected=[]
    def fake_inspect(cached,name,*,measured_size,measured_old,measured_new):
        assert cached is sentinel and name=="anim_castle 002"
        assert measured_size==(333,165)
        assert measured_old==(0.,1.10909091)
        assert measured_new==(0.,1.)
        inspected.append(name)
        return {"status":"bereits_im_bc7","bc7_pivot":[0.,1.],
                "cache_key":"c"*64}
    monkeypatch.setattr(stage_module,"inspect_published_pivot",fake_inspect)
    monkeypatch.setattr(stage_module,"project_group_cache_metadata",
                        lambda *args,**kwargs:pytest.fail("No rebuild projection for already-aligned BC7"))
    plan=_build(tmp_path,approval,measured)
    assert inspected==["anim_castle 002"]
    assert plan["change_count"]==0 and plan["state"]=="no_changes"
    assert not plan["changes"]
    assert plan["already_in_published_bc7_count"]==1
    assert plan["already_in_published_bc7"][0]["name"]=="anim_castle 002"
    assert plan["already_in_published_bc7"][0]["bc7_pivot"]==[0.,1.]
    assert not plan["verified_cache_group_impacts"]
    assert not plan["unverified_cache_groups"]


def test_real_cache_metadata_projection_changes_only_one_group_key(tmp_path,monkeypatch):
    import stronghold_europe_de.pivot_build_stage as stage_module
    _,_,_,_,measured,approval=_world(tmp_path)
    sentinel=object()
    monkeypatch.setattr(stage_module,"locate_published_group",
                        lambda root,index:sentinel)
    def fake_inspect(cached,name,*,measured_size,measured_old,measured_new):
        assert cached is sentinel
        return {"name":name,"status":"bc7_neubau_erforderlich",
                "bc7_pivot":[0.,1.10909091],"cache_key":"a"*64,
                "cache_verified":True}
    effects=[]
    def fake_project(cached,pivots):
        assert cached is sentinel
        assert pivots=={"anim_castle 002":(0.,1.)}
        effects.append(pivots)
        return {
            "original_cache_key":"a"*64,"projected_cache_key":"b"*64,
            "original_metadata_sha256":"c"*64,
            "projected_metadata_sha256":"d"*64,
            "changed_frames":["anim_castle 002"],
        }
    monkeypatch.setattr(stage_module,"inspect_published_pivot",fake_inspect)
    monkeypatch.setattr(stage_module,"project_group_cache_metadata",fake_project)
    plan=_build(tmp_path,approval,measured)
    assert len(effects)==1
    assert plan["change_count"]==1
    assert plan["changes"][0]["published_bc7_evidence"]["cache_verified"]
    assert plan["changes"][0]["current_cache_key"]=="a"*64
    assert plan["changes"][0]["projected_cache_key"]=="b"*64
    assert plan["verified_cache_group_impacts"][0]["projected_metadata_sha256"]=="d"*64
    assert not plan["unverified_cache_groups"]


def test_published_bc7_cache_conflict_blocks_stage_not_fallback(tmp_path,monkeypatch):
    import stronghold_europe_de.pivot_build_stage as stage_module
    import stronghold_europe_de.pivot_bc7_cache as cache_module
    _,_,_,_,measured,approval=_world(tmp_path)
    def bad_cache(root,index):
        raise cache_module.PivotCacheEvidenceError("bundle hash mismatch")
    monkeypatch.setattr(stage_module,"locate_published_group",bad_cache)
    with pytest.raises(PivotStageError,match="publizierter BC7-Atlas"):
        _build(tmp_path,approval,measured)
    assert not (tmp_path/"work"/"reports"/"pivot-bc7-stage").exists()


@pytest.mark.parametrize("item",["bundle","index"])
def test_source_changed_during_atlas_resolution_is_blocked(tmp_path,monkeypatch,item):
    import stronghold_europe_de.pivot_build_stage as stage_module
    _,game,_,_,measured,approval=_world(tmp_path)
    bundle=game/"Runtime"/"AssetBundles"/"win64"/"sede.gm.anim_castle.bc7.v2"
    index=game/"Runtime"/"AssetBundles"/"index.json"
    target=bundle if item=="bundle" else index
    called=[]
    def racing_lookup(root,index_group):
        called.append(index_group["group"])
        target.write_bytes(target.read_bytes()+b"changed-mid-preflight")
        return None
    monkeypatch.setattr(stage_module,"locate_published_group",racing_lookup)
    with pytest.raises(PivotStageError,match="während der Prüfung"):
        _build(tmp_path,approval,measured)
    assert called==["anim_castle"]
    assert not (tmp_path/"work"/"reports"/"pivot-bc7-stage").exists()

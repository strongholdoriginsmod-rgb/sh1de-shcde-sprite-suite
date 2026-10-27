"""Real pinned native source/target geometry vs shipped BC7 group proof.

Tests reconstruct the production native proof without decoding game files or
writing to the build/install directory. Negative tests mutate only Python
in-memory objects or private tempfile mapping fixtures.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import gzip
import importlib.util
import json
from pathlib import Path

import pytest

from stronghold_europe_de.gm_atlas import (
    AtlasGroupSpec, GMAtlasError, validate_complete_group,
)
from stronghold_europe_de.mapping import read_mapping
from stronghold_europe_de.pivot_bc7_cache import locate_published_group
from stronghold_europe_de.pivot_native_provenance import (
    SCHEMA, PivotNativeProvenanceError, _positive_dimension,
    _read_pinned_mapping, audit_native_geometry, reconstruct_group_proof,
    save_native_geometry_audit,
)
ROOT=Path(__file__).resolve().parents[2]
GROUP="anim_castle"
PROFILE="sprite-suite-world-bc7-v2"


@pytest.fixture(scope="module")
def native_fixture():
    required=[
        ROOT/"work/mapping/proposals.json.gz",
        ROOT/f"profiles/{PROFILE}.json",
        ROOT/f"dist/{PROFILE}/StrongholdEuropeDE/Runtime/AssetBundles/index.json",
        ROOT/"cache/asset-stream-group-cache-v1/refs/anim_castle",
    ]
    if any(not p.exists() for p in required):
        pytest.skip("Private local original mappings and published BC7 cache are absent")
    profile=json.loads(required[1].read_text(encoding="utf-8"))
    raw_spec=next(r for r in profile["gm_atlases"] if r.get("gm_file_name")==GROUP)
    spec=AtlasGroupSpec.from_profile(raw_spec)
    mapping=read_mapping(required[0])
    valid=validate_complete_group(mapping["sprites"],spec)
    index=json.loads(required[2].read_text(encoding="utf-8"))
    group_row=next(r for r in index["groups"] if r.get("group")==GROUP)
    cached=locate_published_group(ROOT,group_row)
    assert cached is not None
    return valid,cached


def test_reconstruct_all_frozen_native_and_review_proofs(native_fixture):
    validated,cached=native_fixture
    result=reconstruct_group_proof(validated,cached,GROUP)
    assert result["status"]=="frozen_native_geometry_reconstructed"
    assert (result["total_frames"],result["native_source_frames"],
            result["target_keep_frames"])==(106,95,11)
    frozen=validated.spec.native_source_geometry_policy
    assert result["native_proof"]["geometry_proof_sha256"]==frozen.expected_geometry_proof_sha256
    assert result["native_proof"]["origin_proof_sha256"]==frozen.expected_origin_proof_sha256
    assert result["native_proof"]["source_rgba_sha256"]==frozen.expected_source_rgba_sha256
    assert result["review_partition"]["provenance_sha256"]==(
        validated.spec.review_frame_policy.expected_provenance_sha256
    )
    selected={f["name"]:f for f in result["frames"]}
    assert selected["anim_castle 002"]["pivot"]==[0.0,1.0]
    assert selected["anim_castle 002"]["geometry"]==[333,165]
    assert selected["anim_castle 002"]["source_path_id"]==12414
    assert selected["anim_castle 002"]["target_path_id"]==86476
    assert result["native_proof"]["runtime_anchor_max_error_px"]<0.0001
    assert result["native_proof"]["source_anchor_max_error_px"]==260.0


def test_full_production_audit_binds_manifest_mapping_and_atlas(native_fixture):
    result=audit_native_geometry(ROOT)
    assert result["schema"]==SCHEMA
    assert result["group_proof"]["total_frames"]==106
    assert result["group_proof"]["native_source_frames"]==95
    assert result["source_hashes"]["mapping_gzip_sha256"]==(
        "60c4b823d183876f304d8ebd9d3ec3d7563dece89326853fc81d283ca79c6dab"
    )
    assert result["source_hashes"]["group_cache_key"].startswith("f069eb9187a0")
    assert result["mapping_relative_path"]=="work/mapping/proposals.json.gz"
    assert result["release_allowed"] is False
    assert result["rebuild_performed"] is False
    assert "not independently decoded" in result["disclaimer"]


@pytest.mark.parametrize("mutation",[
    "source_pivot","target_pivot","target_size","keep_target_pivot","action"
])
def test_mutated_mapping_rejected_before_pivot_authority(native_fixture,mutation):
    validated,cached=native_fixture
    rows=deepcopy(list(validated.proposals))
    if mutation=="source_pivot":
        item=next(x for x in rows if x["name"]=="anim_castle 002")
        item["source"]["pivot_y"]=0.4
    elif mutation=="target_pivot":
        item=next(x for x in rows if x["name"]=="anim_castle 002")
        item["target"]["pivot_y"]=0.0
    elif mutation=="target_size":
        item=next(x for x in rows if x["name"]=="anim_castle 002")
        item["target"]["height"]=156.0
    elif mutation=="action":
        item=next(x for x in rows if x["name"]=="anim_castle 002")
        item["action"]="KEEP_CRUSADER"
    else:
        item=next(x for x in rows if x["action"]=="KEEP_CRUSADER")
        item["target"]["pivot_y"]=0.123456
    changed=replace(validated,proposals=tuple(rows))
    with pytest.raises((PivotNativeProvenanceError,GMAtlasError)):
        reconstruct_group_proof(changed,cached,GROUP)


@pytest.mark.parametrize("mutation",[
    "frame_pivot","frame_rgba","frame_order","frame_geometry","frame_ppu"
])
def test_tampered_cached_atlas_never_reuses_frozen_proof(native_fixture,mutation):
    validated,cached=native_fixture
    atlas=cached.atlas
    frames=list(atlas.frames)
    if mutation=="frame_order":
        frames[0],frames[1]=frames[1],frames[0]
    else:
        candidate=frames[1]  # anim_castle 002
        if mutation=="frame_pivot":
            candidate=replace(candidate,pivot=replace(candidate.pivot,y=0.9))
        elif mutation=="frame_rgba":
            candidate=replace(candidate,main_source_rgba_sha256="0"*64)
        elif mutation=="frame_geometry":
            candidate=replace(candidate,rect=replace(candidate.rect,height=166))
        elif mutation=="frame_ppu":
            candidate=replace(candidate,pixels_per_unit=32.)
        frames[1]=candidate
    changed=replace(cached,atlas=replace(atlas,frames=tuple(frames)))
    with pytest.raises(PivotNativeProvenanceError):
        reconstruct_group_proof(validated,changed,GROUP)


def test_missing_group_and_wrong_profile_are_blocked_without_reads():
    with pytest.raises(PivotNativeProvenanceError,match="nur anim_castle"):
        audit_native_geometry(ROOT,group="anim_maypole")
    with pytest.raises(PivotNativeProvenanceError,match="Profil-ID"):
        audit_native_geometry(ROOT,profile_id="../../invalid")


def test_gzip_mapping_strict_and_bounded_in_temp_directory(tmp_path,monkeypatch):
    import stronghold_europe_de.pivot_native_provenance as source
    path=tmp_path/"proposals.json.gz"
    def gz(payload:bytes):
        with gzip.open(path,"wb") as stream:
            stream.write(payload)
    gz(b'{"schema_version":2,"sprites":[],"source_build_id":"x","target_build_id":"y"}')
    mapping,digest=_read_pinned_mapping(path)
    assert mapping["sprites"]==[]
    assert len(digest)==64
    gz(b'{"schema_version":2,"schema_version":2,"sprites":[]}')
    with pytest.raises(PivotNativeProvenanceError,match="Doppeltes"):
        _read_pinned_mapping(path)
    gz(b'{"schema_version":2,"sprites":[],"value":NaN}')
    with pytest.raises(PivotNativeProvenanceError,match="Sonderzahl"):
        _read_pinned_mapping(path)
    gz(b"a"*120)
    monkeypatch.setattr(source,"MAX_MAPPING_DECOMPRESSED",100)
    with pytest.raises(PivotNativeProvenanceError,match="dekomprimiert"):
        _read_pinned_mapping(path)


@pytest.mark.parametrize("number",[False,float("nan"),1.5,-5,0,"45"])
def test_dimensions_reject_non_integral_and_unsafe_numbers(number):
    with pytest.raises((PivotNativeProvenanceError,ValueError,OverflowError)):
        _positive_dimension(number,"frame.height")


def test_stale_native_audit_export_is_refused_without_writes(tmp_path,monkeypatch):
    import stronghold_europe_de.pivot_native_provenance as source
    report={
        "schema":SCHEMA,"profile_id":PROFILE,
        "group_proof":{"group":GROUP},"status":"old",
    }
    monkeypatch.setattr(source,"audit_native_geometry",lambda *args,**kwargs:{
        **report,"status":"changed"
    })
    with pytest.raises(PivotNativeProvenanceError,match="seit dem Bericht"):
        save_native_geometry_audit(report,tmp_path)
    assert not (tmp_path/"work").exists()


def test_cli_rejects_unapproved_group_without_writes(tmp_path,monkeypatch):
    script=ROOT/"tools/qa_native_pivot_provenance.py"
    spec=importlib.util.spec_from_file_location("native_pivot_cli_test",script)
    cli=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    monkeypatch.setattr(cli,"ROOT",tmp_path)
    assert cli.main(["--group","../evil"])==2
    assert not (tmp_path/"work").exists()


def test_native_report_is_content_addressed_idempotent_and_rejects_edits(
    tmp_path,monkeypatch
):
    import stronghold_europe_de.pivot_native_provenance as source
    document={
        "schema":SCHEMA,"profile_id":PROFILE,
        "group_proof":{"group":"anim_castle","native_source_frames":95},
        "release_allowed":False,
    }
    calls=[]
    def recheck(*args):
        calls.append(args)
        return document
    monkeypatch.setattr(source,"audit_native_geometry",recheck)
    output=save_native_geometry_audit(document,tmp_path)
    assert output.is_file()
    assert output.parent==tmp_path/"work"/"reports"/"pivot-native-provenance"
    payload=output.read_bytes()
    assert save_native_geometry_audit(document,tmp_path)==output
    assert output.read_bytes()==payload
    assert len(list(output.parent.glob("*.json")))==1
    assert len(calls)==2
    output.write_bytes(payload+b"changed")
    with pytest.raises(PivotNativeProvenanceError,match="verändert"):
        save_native_geometry_audit(document,tmp_path)


def test_native_report_rejects_linked_output_without_following_it(
    tmp_path,monkeypatch
):
    import stronghold_europe_de.pivot_native_provenance as source
    document={"schema":SCHEMA,"profile_id":PROFILE,
              "group_proof":{"group":"anim_castle"}}
    monkeypatch.setattr(source,"audit_native_geometry",lambda *args:document)
    unsafe=tmp_path/"work"/"reports"/"pivot-native-provenance"
    original=source._is_link
    monkeypatch.setattr(source,"_is_link",lambda path:
                        path==unsafe or original(path))
    with pytest.raises(PivotNativeProvenanceError,match="Verlinkter"):
        save_native_geometry_audit(document,tmp_path)
    assert not unsafe.exists()


def test_gzip_source_changed_during_decode_is_rejected(tmp_path,monkeypatch):
    import stronghold_europe_de.pivot_native_provenance as source
    mapping=tmp_path/"proposals.json.gz"
    with gzip.open(mapping,"wb") as stream:
        stream.write(b'{"schema_version":2,"sprites":[]}')
    hashes=iter(("a"*64,"b"*64))
    monkeypatch.setattr(source,"_sha256_file",lambda path:next(hashes))
    with pytest.raises(PivotNativeProvenanceError,match="während der Einlesung"):
        _read_pinned_mapping(mapping)

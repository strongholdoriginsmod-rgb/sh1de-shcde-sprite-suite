"""Published bundle/cache pivot provenance and safe projected V2 metadata keys."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from stronghold_europe_de.asset_stream_group_cache import (
    INPUT_SCHEMA, frame_bindings_from_atlas, parse_group_cache_input,
)
from stronghold_europe_de.pivot_bc7_cache import (
    PivotCacheEvidenceError, inspect_published_pivot,
    locate_published_group, project_group_cache_metadata,
)


@dataclass(frozen=True)
class Pivot:
    x: float
    y: float


@dataclass(frozen=True)
class Rect:
    width: int
    height: int


@dataclass(frozen=True)
class Frame:
    name: str
    index: int
    alt: bool
    rect: Rect
    pivot: Pivot
    pixels_per_unit: float
    main_source_rgba_sha256: str
    mask_source_rgba_sha256: str | None = None


@dataclass(frozen=True)
class Atlas:
    frames: tuple[Frame, ...]
    frames_sha256: str = "c"*64


def _cache():
    atlas = Atlas((
        Frame("anim_castle 002",2,False,Rect(333,165),Pivot(0.,1.),64.,"e"*64),
        Frame("anim_castle 003",3,False,Rect(333,165),Pivot(0.,1.10909091),64.,"f"*64),
    ))
    bindings=frame_bindings_from_atlas(atlas)
    sha="a"*64
    contract={
        "schema":INPUT_SCHEMA,
        "group":{"name":"anim_castle","slug":"anim_castle",
                 "gm_id":54,"contract_sha256":sha},
        "frames":bindings,
        "editor":{"id":"stronghold-europe-assetbundle-builder-v2","source_sha256":sha},
        "encoder":{"id":"unity-2021.3.45f2-bc7-hq100-force-max-v1",
                   "settings_sha256":sha,"version":"2021.3.45f2"},
        "packer":{"id":"maxrects-bssf-no-rotation-cell4-rgba-extrude-v2",
                  "settings_sha256":sha,"source_sha256":sha,"version":"2"},
        "quality_policy":{"id":"bc7_visual_equivalence_v2","sha256":sha,
                          "verifier_id":"unitypy-1.25.3-bc7-frame-metrics-v1",
                          "verifier_sha256":sha},
        "runtime_capabilities":{"id":"asset-stream-runtime-v2","sha256":sha},
        "texture_policy":{"id":"bc7-main-bc7-mask-hq100-v1","sha256":sha},
        "unity":{"build_target":"StandaloneWindows64",
                 "executable_sha256":sha,"revision":"88f88f591b2e",
                 "version":"2021.3.45f2"},
    }
    descriptor=parse_group_cache_input(contract)
    return SimpleNamespace(
        descriptor=descriptor,
        atlas=atlas,
        atlas_path=Path("atlas.v3.json"),
        index_group_record=None,
    )


def _store_json(path,doc):
    path.parent.mkdir(parents=True,exist_ok=True)
    data=json.dumps(doc,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()+b"\n"
    path.write_bytes(data)
    return sha256(data).hexdigest()


def _published(tmp_path,cache_obj=None):
    obj=cache_obj or _cache()
    sha="b"*64
    group={
        "group":"anim_castle","slug":"anim_castle","gm_id":54,
        "bundle_sha256":sha,"atlas_sha256":"c"*64,
        "frames_sha256":obj.atlas.frames_sha256,
    }
    obj.index_group_record=dict(group)
    key=obj.descriptor.cache_key
    folder=tmp_path/"cache"/"asset-stream-group-cache-v1"
    root_ref=folder/"refs"/"anim_castle"/f"{key}.v1.json"
    root_obj=folder/"objects"/key[:2]/key
    _store_json(root_ref,{
        "cache_key":key,"group":"anim_castle","gm_id":54,
        "object_relative_path":f"objects/{key[:2]}/{key}",
    })
    _store_json(root_obj/"object.v1.json",{
        "cache_key":key, "input":obj.descriptor.as_dict(),
        "artifacts":{
            "bundle":{"sha256":sha},
            "atlas":{"sha256":group["atlas_sha256"]},
        }
    })
    (root_obj/"atlas.v3.json").write_bytes(b"ignored fixture atlas")
    obj.atlas_path=root_obj/"atlas.v3.json"
    return group, obj, root_ref, root_obj


def test_published_pivot_and_metadata_projection_share_exact_cache_contract():
    obj=_cache()
    matching=inspect_published_pivot(
        obj,"anim_castle 002",
        measured_size=(333,165),
        measured_old=(0.,1.10909091),
        measured_new=(0.,1.),
    )
    assert matching["status"]=="bereits_im_bc7"
    assert matching["bc7_pivot"]==[0.,1.]
    assert matching["source_main_rgba_sha256"]=="e"*64
    pending=inspect_published_pivot(
        obj,"anim_castle 003",
        measured_size=(333,165),
        measured_old=(0.,1.10909091),
        measured_new=(0.,1.),
    )
    assert pending["status"]=="bc7_neubau_erforderlich"
    projection=project_group_cache_metadata(
        obj,{"anim_castle 003":(0.,1.)}
    )
    assert projection["original_cache_key"]==obj.descriptor.cache_key
    assert projection["projected_cache_key"]!=obj.descriptor.cache_key
    assert projection["original_metadata_sha256"]!=projection["projected_metadata_sha256"]
    assert projection["main_rgba_sha256"]==obj.descriptor.as_dict()["frames"]["main_rgba_sha256"]
    assert projection["mask_rgba_sha256"] is None
    assert projection["changed_frames"]==["anim_castle 003"]
    assert not projection["actual_builder_rebuild_verified"]
    assert projection["runtime_bundle_unchanged"]
    assert frame_bindings_from_atlas(obj.atlas)==obj.descriptor.as_dict()["frames"]


@pytest.mark.parametrize("case",["bad_geometry","conflicting","unknown","noop","bad_number"])
def test_pivot_conflicts_never_generate_apparent_cache_approval(case):
    obj=_cache()
    if case=="bad_geometry":
        with pytest.raises(PivotCacheEvidenceError,match="Geometrie"):
            inspect_published_pivot(obj,"anim_castle 002",measured_size=(200,165),
                measured_old=(0,1.10909091),measured_new=(0,1))
    elif case=="conflicting":
        with pytest.raises(PivotCacheEvidenceError,match="weder"):
            inspect_published_pivot(obj,"anim_castle 002",measured_size=(333,165),
                measured_old=(0,.9),measured_new=(0,1.2))
    elif case=="unknown":
        with pytest.raises(PivotCacheEvidenceError,match="unbekannten"):
            project_group_cache_metadata(obj,{"anim_castle 999":(0,1)})
    elif case=="noop":
        with pytest.raises(PivotCacheEvidenceError,match="bereits"):
            project_group_cache_metadata(obj,{"anim_castle 002":(0,1)})
    else:
        with pytest.raises(PivotCacheEvidenceError,match="endliche"):
            project_group_cache_metadata(obj,{"anim_castle 003":(True,1)})


def test_duplicate_group_frames_fail_closed():
    obj=_cache()
    obj.atlas=Atlas((obj.atlas.frames[0],obj.atlas.frames[0]))
    with pytest.raises(PivotCacheEvidenceError,match="mehrfach"):
        inspect_published_pivot(
            obj,"anim_castle 002",measured_size=(333,165),
            measured_old=(0,1.1),measured_new=(0,1),
        )


def test_exact_published_cache_selection_ignores_older_unmatched_refs(tmp_path,monkeypatch):
    import stronghold_europe_de.pivot_bc7_cache as api
    group,obj,ref,object_dir=_published(tmp_path)
    other_cache=_cache()
    other_key="0"*64
    _store_json(ref.parent/f"{other_key}.v1.json",{
        "cache_key":other_key,"group":"anim_castle","gm_id":54,
        "object_relative_path":f"objects/{other_key[:2]}/{other_key}",
    })
    _store_json(
        tmp_path/"cache"/"asset-stream-group-cache-v1"/"objects"/other_key[:2]/
        other_key/"object.v1.json",
        {"cache_key":other_key,"artifacts":{"bundle":{"sha256":"d"*64},
                                           "atlas":{"sha256":"e"*64}}}
    )
    loaded=[]
    def fake_load(*,workspace_root,descriptor):
        loaded.append((workspace_root,descriptor.cache_key))
        return obj
    monkeypatch.setattr(api,"load_group_cache_object",fake_load)
    monkeypatch.setattr(api,"_sha256_file",lambda path:group["atlas_sha256"])
    result=locate_published_group(tmp_path,group)
    assert result is obj
    assert loaded==[(tmp_path.resolve(),obj.descriptor.cache_key)]


def test_missing_cache_is_unverified_not_approved(tmp_path):
    obj=_cache()
    data={"group":"anim_castle","slug":"anim_castle","gm_id":54,
          "bundle_sha256":"a"*64,"atlas_sha256":"b"*64,
          "frames_sha256":obj.atlas.frames_sha256}
    assert locate_published_group(tmp_path,data) is None


def test_corrupt_matching_cache_is_not_treated_as_cache_miss(tmp_path,monkeypatch):
    import stronghold_europe_de.pivot_bc7_cache as api
    group,obj,_,_= _published(tmp_path)
    monkeypatch.setattr(api,"load_group_cache_object",lambda **kwargs:None)
    with pytest.raises(PivotCacheEvidenceError,match="keine gültige"):
        locate_published_group(tmp_path,group)


def test_same_bundle_different_atlas_digest_is_error(tmp_path):
    group,obj,_,manifest_root = _published(tmp_path)
    manifest=manifest_root/"object.v1.json"
    raw=json.loads(manifest.read_text())
    raw["artifacts"]["atlas"]["sha256"]="9"*64
    _store_json(manifest,raw)
    with pytest.raises(PivotCacheEvidenceError,match="Atlas-SHA"):
        locate_published_group(tmp_path,group)


def test_ref_escape_and_symlink_are_denied(tmp_path,monkeypatch):
    import stronghold_europe_de.pivot_bc7_cache as api
    group,_,ref,_ = _published(tmp_path)
    record=json.loads(ref.read_text())
    record["object_relative_path"]="../../outside"
    _store_json(ref,record)
    with pytest.raises(PivotCacheEvidenceError,match="fremden Pfad"):
        locate_published_group(tmp_path,group)
    record["object_relative_path"]=f"objects/{record['cache_key'][:2]}/{record['cache_key']}"
    _store_json(ref,record)
    original=api._is_link
    monkeypatch.setattr(api,"_is_link",lambda p:p==ref or original(p))
    with pytest.raises(PivotCacheEvidenceError,match="Unsichere"):
        locate_published_group(tmp_path,group)


def test_one_frame_published_audit_rechecks_manifest_and_cache(tmp_path,monkeypatch):
    import stronghold_europe_de.pivot_bc7_cache as api
    import stronghold_europe_de.release_preflight as preflight_api
    from stronghold_europe_de.pivot_measurements import Measurement

    group,obj,_,_= _published(tmp_path)
    profile="test-published-bc7"
    bundle_root=tmp_path/"dist"/profile/"StrongholdEuropeDE"
    index_file=bundle_root/"Runtime"/"AssetBundles"/"index.json"
    manifest_file=bundle_root/"build-manifest.json"
    _store_json(index_file,{"groups":[group]})
    _store_json(manifest_file,{"profile_id":profile})
    index_sha=sha256(index_file.read_bytes()).hexdigest()
    manifest_sha=sha256(manifest_file.read_bytes()).hexdigest()
    monkeypatch.setattr(preflight_api,"audit_release",lambda root,profile_id:{
        "summary":{"errors":0},
        "source_hashes":{
            "index_sha256":index_sha,
            "manifest_sha256":manifest_sha,
        },
    })
    called=[]
    monkeypatch.setattr(api,"locate_published_group",
                        lambda root,index:called.append(index) or obj)
    measurement=Measurement(
        "anim_castle 002","anim_castle",2,0,18,333,165,
        0.,1.10909091,0.,1.,
    )
    result=api.audit_published_measurement(tmp_path,profile,measurement)
    assert result["status"]=="bereits_im_bc7"
    assert result["profile_id"]==profile
    assert result["manifest_sha256"]==manifest_sha
    assert result["bundle_sha256"]==group["bundle_sha256"]
    assert len(called)==1


def test_one_frame_published_audit_refuses_stale_manifest(tmp_path,monkeypatch):
    import stronghold_europe_de.pivot_bc7_cache as api
    import stronghold_europe_de.release_preflight as preflight_api
    from stronghold_europe_de.pivot_measurements import Measurement
    group,obj,_,_=_published(tmp_path)
    profile="test-published-bc7"
    path=tmp_path/"dist"/profile/"StrongholdEuropeDE"/"Runtime"/"AssetBundles"/"index.json"
    _store_json(path,{"groups":[group]})
    manifest=tmp_path/"dist"/profile/"StrongholdEuropeDE"/"build-manifest.json"
    _store_json(manifest,{"profile_id":profile})
    monkeypatch.setattr(preflight_api,"audit_release",lambda root,profile_id:{
        "summary":{"errors":0},
        "source_hashes":{
            "index_sha256":sha256(path.read_bytes()).hexdigest(),
            "manifest_sha256":"f"*64,  # deliberately stale
        },
    })
    monkeypatch.setattr(api,"locate_published_group",lambda root,index:obj)
    measurement=Measurement(
        "anim_castle 002","anim_castle",2,0,18,333,165,
        0.,1.10909091,0.,1.,
    )
    with pytest.raises(PivotCacheEvidenceError,match="Manifest"):
        api.audit_published_measurement(tmp_path,profile,measurement)


def test_cli_report_can_check_a_measurement_without_an_approval(tmp_path,monkeypatch,capsys):
    import importlib.util
    from stronghold_europe_de.pivot_measurements import Measurement
    script=Path(__file__).resolve().parents[2]/"tools"/"qa_bc7_pivot_audit.py"
    spec=importlib.util.spec_from_file_location("qa_bc7_pivot_cli_test",script)
    cli=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    monkeypatch.setattr(cli,"ROOT",tmp_path)
    measurement=Measurement("anim_castle 002","anim_castle",2,0,18,333,165,
                            0.,1.10909091,0.,1.)
    fake_input=SimpleNamespace(entries=(measurement,))
    fake_review=SimpleNamespace(
        measurement=measurement,status="bereits_passend",
        side="geliefert",reason="Already matched"
    )
    monkeypatch.setattr(cli,"load_measurements",lambda path:fake_input)
    monkeypatch.setattr(cli,"review_measurements",
                        lambda *args:[fake_review])
    monkeypatch.setattr(cli,"audit_release",lambda *args:{
        "summary":{"errors":0},
    })
    monkeypatch.setattr(cli,"_read_json",lambda *args:(
        {"groups":[{"group":"anim_castle"}]},"a"*64))
    sentinel=object()
    monkeypatch.setattr(cli,"locate_published_group",lambda *args:sentinel)
    monkeypatch.setattr(cli,"inspect_published_pivot",lambda *args,**kwargs:{
        "status":"bereits_im_bc7","bc7_pivot":[0.,1.],
        "cache_key":"f"*64,
    })
    assert cli.main([
        "--profile","test-profile", "--measurement","example.json",
    ])==0
    result=capsys.readouterr().out
    assert "BEREITS IM BC7 anim_castle 002" in result
    assert "0 potenzielle Neupr" in result
    assert not (tmp_path/"work").exists()

"""Project-wide SHA-pinned preflight; no modifications to built assets."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sys

import pytest
from PIL import Image

from stronghold_europe_de.release_preflight import (
    SCHEMA, ReleasePreflightError, audit_release, save_preflight,
)
from stronghold_europe_de.pivot_measurements import (
    load_measurements, review_measurements,
)
from stronghold_europe_de.pivot_approvals import PivotDecision, save_approval_report

PROFILE = "test-bc7-world"
BACKEND = "unity_assetbundle_bc7_visual_equivalence_v2"
GROUP = "anim_castle"


def _json(path: Path, document: dict) -> bytes:
    data=(json.dumps(document,ensure_ascii=False,sort_keys=True)+"\n").encode("utf-8")
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(data)
    return data


def _file(path: Path, data: bytes) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


def _artifact(path: str, category: str, data: bytes) -> dict:
    return {
        "relative_path":path, "category":category,
        "sha256":sha256(data).hexdigest(), "size":len(data),
    }


def _world(tmp_path: Path):
    mod=tmp_path/"dist"/PROFILE/"StrongholdEuropeDE"
    profile=tmp_path/"profiles"/f"{PROFILE}.json"
    m={"GUID":"private.sprites","Version":"1.0","Name":"Tests","Manifest":0}
    _json(profile, {
        "schema_version":1,"id":PROFILE,"mod_info":m,
        "atlas_backend":{"kind":BACKEND},
        "gm_atlases":[{"gm_file_name":GROUP}],
    })
    bundlepath="Runtime/AssetBundles/win64/sede.gm.anim_castle.bc7.v2"
    bundled=_file(mod/bundlepath,b"BUNDLE_BYTES_fake_bc7")
    bundle_rec=_artifact(bundlepath,"asset_bundle",bundled)
    idxpath="Runtime/AssetBundles/index.json"
    index=_json(mod/idxpath,{
        "backend_kind":BACKEND,
        "groups":[{
            "group":GROUP,"bundle_path":bundlepath,
            "bundle_sha256":bundle_rec["sha256"],
        }],
    })
    info=_json(mod/"info.json",m)
    runtime=_file(mod/"StrongholdEuropeDE.Runtime.dll",b"fake-test-runtime")
    records=[
        _artifact(idxpath,"asset_bundle_index",index),bundle_rec,
        _artifact("info.json","mod_metadata",info),
        _artifact("StrongholdEuropeDE.Runtime.dll","runtime",runtime),
    ]
    _json(mod/"build-manifest.json",{
        "schema_version":1,"profile_id":PROFILE,
        "mod_info":m,"outputs":records,
    })
    _json(tmp_path/"work"/"reports"/f"{PROFILE}-validation.json",{
        "schema_version":1,"passed":12,"failed":0,"ok":True,"checks":[],
    })
    return mod,profile


def _checks(report,level=None):
    return [row for row in report["findings"]
            if level is None or row["schwere"]==level]


def test_full_build_integrity_and_deterministic_report(tmp_path):
    mod,profile=_world(tmp_path)
    existing={p:p.read_bytes() for p in mod.rglob("*") if p.is_file()}
    report=audit_release(tmp_path,PROFILE)
    assert report["schema"]==SCHEMA
    assert report["summary"]=={"errors":0,"warnings":0,"state":"offline_ok"}
    assert report["stats"]=={
        "expected_outputs":4,"verified_outputs":4,
        "verified_bytes":sum(r["size"] for r in json.loads(
            (mod/"build-manifest.json").read_text(encoding="utf-8"))["outputs"]),
        "profile_groups":1,"index_groups":1,
    }
    assert report["source_hashes"]["manifest_sha256"]==sha256(
        (mod/"build-manifest.json").read_bytes()).hexdigest()
    assert report["source_hashes"]["index_sha256"]
    assert report["source_hashes"]["profile_sha256"]==sha256(profile.read_bytes()).hexdigest()
    assert report["source_hashes"]["validation_report_sha256"]
    assert any("Historischer Nachweis" in r["text"] for r in report["findings"])
    assert all(p.read_bytes()==data for p,data in existing.items())
    assert not (tmp_path/"work"/"reports"/"release-preflight").exists()
    target=save_preflight(report,tmp_path)
    assert save_preflight(report,tmp_path)==target
    assert json.loads(target.read_text(encoding="utf-8"))==report
    assert len(list(target.parent.glob("*.json")))==1
    assert not list(target.parent.glob("*.tmp"))
    assert all(p.read_bytes()==data for p,data in existing.items())


def test_tampered_runtime_or_bundle_causes_blocker(tmp_path):
    mod,_=_world(tmp_path)
    runtime=mod/"StrongholdEuropeDE.Runtime.dll"
    original=runtime.read_bytes()
    runtime.write_bytes(bytes(x^1 for x in original))
    report=audit_release(tmp_path,PROFILE)
    assert report["summary"]["state"]=="blockiert"
    assert report["stats"]["verified_outputs"]==3
    assert any("SHA-256 verändert" in x["text"] for x in _checks(report,"fehler"))
    assert runtime.read_bytes()!=original
    # A stale report cannot suppress a current hash failure.
    assert report["source_hashes"]["validation_report_sha256"]


def test_extra_unmanifested_file_and_missing_file_are_blockers(tmp_path):
    mod,_=_world(tmp_path)
    (mod/"untracked.txt").write_text("manual",encoding="utf-8")
    (mod/"info.json").unlink()
    report=audit_release(tmp_path,PROFILE)
    assert report["summary"]["errors"]>=2
    messages=" ".join(x["text"] for x in _checks(report,"fehler"))
    assert "zusätzlich" in messages and "fehlend" in messages


@pytest.mark.parametrize("bad",["../secret.dll","/absolute.dll","Runtime\\bad.dll","Info.json"])
def test_invalid_relative_or_duplicate_casefold_output_rejected(tmp_path,bad):
    mod,_=_world(tmp_path)
    manifest=mod/"build-manifest.json"
    data=json.loads(manifest.read_text(encoding="utf-8"))
    # 'Info.json' collides case-insensitively with info.json on Windows.
    data["outputs"].append(_artifact(bad,"runtime",b"example"))
    _json(manifest,data)
    findings=_checks(audit_release(tmp_path,PROFILE),"fehler")
    assert findings
    assert any("Datei-Integrität"==f["gruppe"] for f in findings)


@pytest.mark.parametrize("variant",["backend","group","bundle"])
def test_wrong_profile_and_bundle_index_bindings_fail(tmp_path,variant):
    mod,profile=_world(tmp_path)
    if variant=="group":
        source=json.loads(profile.read_text(encoding="utf-8"))
        source["gm_atlases"]=[{"gm_file_name":"tree_apple"}]
        _json(profile,source)
    elif variant=="backend":
        source=json.loads(profile.read_text(encoding="utf-8"))
        source["atlas_backend"]["kind"]="unrelated_atlas"
        _json(profile,source)
    else:
        indexfile=mod/"Runtime"/"AssetBundles"/"index.json"
        source=json.loads(indexfile.read_text(encoding="utf-8"))
        source["groups"][0]["bundle_sha256"]="0"*64
        updated=_json(indexfile,source)
        manifestfile=mod/"build-manifest.json"
        manifest=json.loads(manifestfile.read_text(encoding="utf-8"))
        manifest["outputs"][0]=_artifact(
            "Runtime/AssetBundles/index.json","asset_bundle_index",updated
        )
        _json(manifestfile,manifest)
    report=audit_release(tmp_path,PROFILE)
    assert report["summary"]["errors"]>=1


def test_wrong_profile_id_and_missing_manifest_fail_closed(tmp_path):
    mod,_=_world(tmp_path)
    with pytest.raises(ReleasePreflightError):
        audit_release(tmp_path,"../escape")
    (mod/"build-manifest.json").unlink()
    report=audit_release(tmp_path,PROFILE)
    assert report["summary"]["state"]=="blockiert"


def test_no_validation_is_warning_not_false_release_certificate(tmp_path):
    _world(tmp_path)
    (tmp_path/"work"/"reports"/f"{PROFILE}-validation.json").unlink()
    report=audit_release(tmp_path,PROFILE)
    assert report["summary"]=={"errors":0,"warnings":1,"state":"hinweise"}
    assert "Ingame-Abnahme" in report["disclaimer"]


def _approval(tmp_path: Path):
    folder=tmp_path/"work"/"katalog"/"geliefert"/GROUP
    folder.mkdir(parents=True,exist_ok=True)
    picture=folder/"anim_castle 002.png"
    Image.new("RGBA",(333,165),(72,90,150,255)).save(picture)
    _json(folder/"index.json",{
        "group":GROUP,
        "frames":[{"name":"anim_castle 002","file":picture.name,
                   "width":333,"height":165,
                   "pivot_x":0.0,"pivot_y":1.10909091}],
    })
    measure=tmp_path/"Zinnenlineal"/"zinnen-versatz.json"
    _json(measure,{
        "schema":"zinnenlineal.versatz.v1","frames":[{
            "name":"anim_castle 002","gruppe":GROUP,"nummer":2,
            "breite":333,"hoehe":165,"rechts":0,"hoch":18,
            "pivot_x":0.0,"pivot_y":1.10909091,
            "neu_pivot_x":0.0,"neu_pivot_y":1.0,
        }],
    })
    source=load_measurements(measure)
    checks=review_measurements(source,tmp_path)
    assert checks[0].status=="pruefen"
    return save_approval_report(
        source,checks,tmp_path,{
            "anim_castle 002":PivotDecision(
                "freigegeben",recorded_at="2026-10-11T18:00:00+00:00"
            )
        }
    ),picture


def test_selected_pivot_approval_warning_and_staleness_are_explicit(tmp_path):
    _world(tmp_path)
    approval,picture=_approval(tmp_path)
    report=audit_release(tmp_path,PROFILE,approval_file=approval)
    assert report["summary"]["errors"]==0
    assert report["summary"]["warnings"]==1
    assert report["source_hashes"]["approval_sha256"]==sha256(approval.read_bytes()).hexdigest()
    assert any("Metadaten-/BC7-Releasevertrag" in r["text"] for r in report["findings"])
    picture.write_bytes(picture.read_bytes()+b"changed")
    stale=audit_release(tmp_path,PROFILE,approval_file=approval)
    assert stale["summary"]["errors"]>0
    assert "ungültige/veraltete Freigaben" in " ".join(r["text"] for r in stale["findings"])


def test_unselected_or_external_approval_is_not_silently_trusted(tmp_path):
    _world(tmp_path)
    foreign=tmp_path/"other-approval.json"
    _json(foreign,{"schema":"stronghold-europe.pivot-approval.v1","rows":[]})
    clean=audit_release(tmp_path,PROFILE)
    assert not clean["source_hashes"]["approval_sha256"]
    unsafe=audit_release(tmp_path,PROFILE,approval_file=foreign)
    assert unsafe["summary"]["state"]=="blockiert"
    assert any("außerhalb" in f["text"] for f in _checks(unsafe,"fehler"))


def test_cli_argument_parser_runs_without_modification(tmp_path,monkeypatch):
    import importlib.util
    toolpath=Path(__file__).resolve().parents[2]/"tools"/"qa_release_preflight.py"
    spec=importlib.util.spec_from_file_location("release_preflight_cli_qa",toolpath)
    cli=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    _world(tmp_path)
    monkeypatch.setattr(cli,"ROOT",tmp_path)
    assert cli.main(["--profile",PROFILE,"--check-only"])==0
    assert not (tmp_path/"work"/"reports"/"release-preflight").exists()
    assert cli.main(["--profile",PROFILE])==0
    assert list((tmp_path/"work"/"reports"/"release-preflight").glob("*.json"))


def test_extra_empty_folder_is_not_a_valid_published_build(tmp_path):
    mod,_=_world(tmp_path)
    (mod/"unexpected").mkdir()
    report=audit_release(tmp_path,PROFILE)
    assert report["summary"]["errors"]>0
    assert any("fremde Ordner" in f["text"]
               for f in _checks(report,"fehler"))


def test_manifest_bundle_must_have_matching_index_reference(tmp_path):
    mod,_=_world(tmp_path)
    unused=_file(mod/"Runtime"/"AssetBundles"/"win64"/"unexpected.bc7",b"extra")
    manifestfile=mod/"build-manifest.json"
    manifest=json.loads(manifestfile.read_text(encoding="utf-8"))
    manifest["outputs"].append(_artifact(
        "Runtime/AssetBundles/win64/unexpected.bc7","asset_bundle",unused
    ))
    _json(manifestfile,manifest)
    report=audit_release(tmp_path,PROFILE)
    assert report["summary"]["errors"]>0
    assert any("nicht referenziert" in f["text"]
               for f in _checks(report,"fehler"))

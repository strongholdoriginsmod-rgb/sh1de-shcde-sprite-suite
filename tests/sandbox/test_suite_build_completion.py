"""Independent post-build classification (no Unity or game changes)."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import stronghold_europe_de.suite_build_completion as complete


def _world(root: Path, monkeypatch, *, custom=False, existing=False):
    profile="test-build"
    output_base=root/("custom-dist" if custom else "dist")
    output=output_base/profile/"StrongholdEuropeDE"
    cfg=root/"config"/"installations.local.toml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("# artificial output config",encoding="utf-8")
    monkeypatch.setattr(
        complete,"load_config",
        lambda path:SimpleNamespace(output=SimpleNamespace(
            dist_dir=output_base,mod_folder_name="StrongholdEuropeDE"
        )),
    )
    manifest=output/"build-manifest.json"
    if existing:
        output.mkdir(parents=True)
        manifest.write_text(
            json.dumps({"schema_version":1,"profile_id":profile}),
            encoding="utf-8",
        )
    before=complete.capture_build_before(root,profile,output)
    return profile,output,manifest,before


def _successful_audit(path: Path, *, warnings=0, errors=0):
    digest=sha256(path.read_bytes()).hexdigest()
    return {
        "summary":{"errors":errors,"warnings":warnings,
                   "state":"blockiert" if errors else
                   "hinweise" if warnings else "offline_ok"},
        "stats":{"expected_outputs":2,"verified_outputs":2,
                 "verified_bytes":12000,"index_groups":1},
        "source_hashes":{"manifest_sha256":digest},
        "findings":[
            {"schwere":"warnung","gruppe":"Historical QA",
             "text":"No source-pinned validation report"}
        ] if warnings else [],
    }


def test_failed_cli_cannot_recycle_existing_valid_release(tmp_path,monkeypatch):
    profile,output,manifest,before=_world(tmp_path,monkeypatch,existing=True)
    monkeypatch.setattr(
        complete,"audit_release",
        lambda *a,**kw:pytest.fail("Failed/cancelled build cannot audit old package")
    )
    result=complete.inspect_completed_build(
        tmp_path,profile,output,exit_code=7,before=before
    )
    assert result["state"]=="tool_failed"
    assert result["exit_code"]==7
    assert result["offline_integrity_ok"] is False
    assert result["ingame_approved"] is False
    assert result["release_approved"] is False
    assert result["verified_files"]==0
    assert manifest.is_file()


def test_output_after_cli_success_receives_independent_offline_sha_check(
    tmp_path,monkeypatch
):
    profile,output,manifest,before=_world(tmp_path,monkeypatch)
    assert before["prior_output_exists"] is False
    output.mkdir(parents=True)
    manifest.write_text(
        json.dumps({"schema_version":1,"profile_id":profile}),
        encoding="utf-8",
    )
    invoked=[]
    def audit(root,name):
        invoked.append((root,name))
        return _successful_audit(manifest)
    monkeypatch.setattr(complete,"audit_release",audit)
    result=complete.inspect_completed_build(
        tmp_path,profile,output,exit_code=0,before=before
    )
    assert invoked==[(tmp_path.resolve(),profile)]
    assert result["state"]=="offline_ok"
    assert result["offline_integrity_ok"] is True
    assert result["verified_files"]==2
    assert result["verified_bytes"]==12000
    assert len(result["manifest_sha256"])==64
    assert result["same_manifest_as_before"] is False
    assert not result["ingame_approved"]
    assert not result["release_approved"]
    assert not result["installation_performed"]


def test_original_manifest_same_as_before_does_not_claim_new_output(
    tmp_path,monkeypatch
):
    profile,output,manifest,before=_world(tmp_path,monkeypatch,existing=True)
    monkeypatch.setattr(
        complete,"audit_release",
        lambda *args:_successful_audit(manifest)
    )
    result=complete.inspect_completed_build(
        tmp_path,profile,output,exit_code=0,before=before
    )
    assert result["state"]=="same_manifest"
    assert result["offline_integrity_ok"] is True
    assert result["same_manifest_as_before"] is True
    assert "cannot prove newly generated" in result["detail"]


@pytest.mark.parametrize("errors,warnings,expected",[
    (0,2,"offline_warnings"),
    (3,0,"offline_failed"),
])
def test_warnings_and_errors_never_look_like_unqualified_release(
    tmp_path,monkeypatch,errors,warnings,expected
):
    profile,output,manifest,before=_world(tmp_path,monkeypatch)
    output.mkdir(parents=True)
    manifest.write_text('{"schema_version":1}',encoding="utf-8")
    monkeypatch.setattr(
        complete,"audit_release",
        lambda *args:_successful_audit(manifest,warnings=warnings,errors=errors),
    )
    result=complete.inspect_completed_build(
        tmp_path,profile,output,exit_code=0,before=before
    )
    assert result["state"]==expected
    assert result["errors"]==errors
    assert result["warnings"]==warnings
    assert result["release_approved"] is False
    assert result["ingame_approved"] is False
    assert result["offline_integrity_ok"] is (errors==0)


def test_noncanonical_dist_is_not_pretended_to_be_offline_verified(
    tmp_path,monkeypatch
):
    profile,output,manifest,before=_world(tmp_path,monkeypatch,custom=True)
    called=[]
    monkeypatch.setattr(
        complete,"audit_release",
        lambda *args:called.append(args) or pytest.fail("Wrong auditor output"),
    )
    result=complete.inspect_completed_build(
        tmp_path,profile,output,exit_code=0,before=before
    )
    assert result["state"]=="unsupported_output"
    assert not result["offline_integrity_ok"]
    assert not called


def test_cli_success_without_manifest_is_still_offline_failure(
    tmp_path,monkeypatch
):
    profile,output,manifest,before=_world(tmp_path,monkeypatch)
    called=[]
    monkeypatch.setattr(
        complete,"audit_release",
        lambda *a:called.append(1) or {
            "summary":{"errors":2,"warnings":0},
            "stats":{"expected_outputs":0,"verified_outputs":0,
                     "verified_bytes":0,"index_groups":0},
            "source_hashes":{"manifest_sha256":None},
            "findings":[{"schwere":"fehler","gruppe":"Manifest",
                         "text":"Kein Buildmanifest vorhanden"}],
        },
    )
    result=complete.inspect_completed_build(
        tmp_path,profile,output,exit_code=0,before=before
    )
    assert result["state"] in ("offline_failed","audit_failed")
    assert not result["offline_integrity_ok"]


def test_modified_manifest_during_offline_scan_refuses_success(tmp_path,monkeypatch):
    profile,output,manifest,before=_world(tmp_path,monkeypatch)
    output.mkdir(parents=True)
    manifest.write_text('{"schema_version":1}',encoding="utf-8")
    def auditing(*args):
        record=_successful_audit(manifest)
        manifest.write_bytes(manifest.read_bytes()+b" ")
        return record
    monkeypatch.setattr(complete,"audit_release",auditing)
    result=complete.inspect_completed_build(
        tmp_path,profile,output,exit_code=0,before=before
    )
    assert result["state"]=="audit_failed"
    assert not result["offline_integrity_ok"]
    assert "changed" in result["detail"]


def test_bad_audit_counts_cannot_produce_success(tmp_path,monkeypatch):
    profile,output,manifest,before=_world(tmp_path,monkeypatch)
    output.mkdir(parents=True)
    manifest.write_text('{"schema_version":1}',encoding="utf-8")
    report=_successful_audit(manifest)
    report["stats"]["verified_outputs"]=1
    monkeypatch.setattr(complete,"audit_release",lambda *args:report)
    result=complete.inspect_completed_build(
        tmp_path,profile,output,exit_code=0,before=before
    )
    assert result["state"]=="audit_failed"
    assert not result["offline_integrity_ok"]


@pytest.mark.parametrize("problem",["foreign_profile","wrong_output","bad_digest","bool_code"])
def test_wrong_result_binding_or_types_fails_closed(tmp_path,monkeypatch,problem):
    profile,output,manifest,before=_world(tmp_path,monkeypatch)
    if problem=="foreign_profile":
        before["profile_id"]="some-other-profile"
    elif problem=="wrong_output":
        before["output"]=str(tmp_path/"dist"/"evil")
    elif problem=="bad_digest":
        before["prior_manifest_sha256"]="nope"
    code=True if problem=="bool_code" else 1
    with pytest.raises(complete.BuildCompletionError):
        complete.inspect_completed_build(
            tmp_path,profile,output,exit_code=code,before=before
        )


def test_failed_cli_classified_even_after_config_deleted(tmp_path,monkeypatch):
    profile,output,manifest,before=_world(tmp_path,monkeypatch,existing=True)
    (tmp_path/"config"/"installations.local.toml").unlink()
    result=complete.inspect_completed_build(
        tmp_path,profile,output,exit_code=-1,before=before
    )
    assert result["state"]=="tool_failed"
    assert result["exit_code"]==-1
    assert not result["offline_integrity_ok"]



def test_success_exit_with_lost_output_config_is_not_a_success(
    tmp_path, monkeypatch
):
    from stronghold_europe_de.config import ConfigurationError
    profile, output, manifest, before = _world(tmp_path, monkeypatch)
    monkeypatch.setattr(
        complete,"load_config",
        lambda path:(_ for _ in ()).throw(
            ConfigurationError("Missing config after build")
        ),
    )
    monkeypatch.setattr(
        complete,"audit_release",
        lambda *args:pytest.fail("Config mismatch must fail before offline audit"),
    )
    result=complete.inspect_completed_build(
        tmp_path,profile,output,exit_code=0,before=before
    )
    assert result["state"]=="audit_failed"
    assert "output binding" in result["detail"]
    assert result["exit_code"]==0
    assert result["offline_integrity_ok"] is False
    assert result["release_approved"] is False

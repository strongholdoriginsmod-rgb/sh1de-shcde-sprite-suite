"""Tamper-resistant local build history: bounded, chained, non-promotable."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import pytest

import stronghold_europe_de.suite_build_history as history
from stronghold_europe_de.suite_build_completion import SCHEMA as COMPLETION


PROFILE = "sprite-suite-world-bc7-v2"


def _before(root,profile=PROFILE):
    return {
        "schema":COMPLETION, "profile_id":profile,
        "output":str(root/"dist"/profile/"StrongholdEuropeDE"),
        "prior_manifest_sha256":None,
        "prior_output_exists":False,
    }


def _result(root,profile=PROFILE,*,state="tool_failed",code=17):
    return {
        "schema":COMPLETION, "profile_id":profile,
        "output":_before(root,profile)["output"],
        "state":state,
        "detail":"Synthetic build completion, no actual game changes",
        "exit_code":code,
        "verified_files":0,"verified_bytes":0,
        "errors":1,"warnings":0,
        "manifest_sha256":None,
        "same_manifest_as_before":None,
        "issues":["Synthetic failure"],
        "offline_integrity_ok":False,"release_approved":False,
        "ingame_approved":False,
        "installation_performed":False,
        "no_output_written_by_audit":True,
    }


def _journal(root):
    return root/"work"/"reports"/"suite-build-history"


def test_empty_read_never_creates_directories(tmp_path):
    assert history.read_build_history(tmp_path)==[]
    assert not (tmp_path/"work").exists()


def test_one_failure_persists_on_restart_and_does_not_claim_success(tmp_path):
    profile=PROFILE
    before=_before(tmp_path)
    run_id=history.append_started(tmp_path,profile,before,replace=False)
    assert len(run_id)==32
    initial=history.read_build_history(tmp_path)
    assert len(initial)==1
    assert initial[0]["state"]=="unbestaetigt"
    assert initial[0]["result"] is None
    assert "kein Abschluss" in initial[0]["message"]
    event=history.append_completed(
        tmp_path,run_id,profile,_result(tmp_path)
    )
    assert event.is_file()
    recorded=history.read_build_history(tmp_path)
    assert len(recorded)==1
    assert recorded[0]["state"]=="tool_failed"
    assert recorded[0]["result"]["exit_code"]==17
    assert recorded[0]["result"]["ingame_approved"] is False
    assert recorded[0]["result"]["release_approved"] is False
    assert recorded[0]["result"]["installation_performed"] is False
    assert len(list(_journal(tmp_path).glob("*.json")))==2
    assert not (tmp_path/"dist").exists()
    assert history.read_build_history(tmp_path)==recorded


def test_different_runs_preserve_timestamp_order_and_previous_chain(tmp_path):
    before=_before(tmp_path)
    first=history.append_started(tmp_path,PROFILE,before,replace=True)
    history.append_completed(tmp_path,first,PROFILE,_result(tmp_path))
    second=history.append_started(tmp_path,PROFILE,before,replace=False)
    recent=history.read_build_history(tmp_path)
    assert len(recent)==2
    assert recent[0]["run_id"]==second
    assert recent[0]["state"]=="unbestaetigt"
    assert recent[0]["replace"] is False
    assert recent[1]["run_id"]==first
    assert recent[1]["state"]=="tool_failed"
    files=sorted(_journal(tmp_path).iterdir())
    assert len(files)==3
    data=[json.loads(p.read_bytes()) for p in files]
    assert data[0]["previous_sha256"] is None
    assert data[1]["previous_sha256"]==sha256(files[0].read_bytes()).hexdigest()
    assert data[2]["previous_sha256"]==sha256(files[1].read_bytes()).hexdigest()


def test_launch_failure_is_recorded_as_failure_without_manifest(tmp_path):
    before=_before(tmp_path)
    run=history.append_started(tmp_path,PROFILE,before,replace=False)
    history.append_launch_failed(tmp_path,run,PROFILE,"Synthetic process spawn failed")
    latest=history.read_build_history(tmp_path)[0]
    assert latest["state"]=="start_fehlgeschlagen"
    assert latest["result"] is None
    assert "Synthetic" in latest["message"]


def test_truncated_unconfirmed_attempt_survives_restart_without_claim(tmp_path):
    run=history.append_started(tmp_path,PROFILE,_before(tmp_path),replace=False)
    assert history.read_build_history(tmp_path)[0]["run_id"]==run
    assert history.read_build_history(tmp_path)[0]["state"]=="unbestaetigt"


@pytest.mark.parametrize("attack",["bytes","extra","rename","delete_first",
                                    "delete_middle","noncanonical","linked"])
def test_history_tampering_fails_closed(tmp_path,monkeypatch,attack):
    run=history.append_started(tmp_path,PROFILE,_before(tmp_path),replace=False)
    history.append_completed(tmp_path,run,PROFILE,_result(tmp_path))
    second=history.append_started(tmp_path,PROFILE,_before(tmp_path),replace=True)
    paths=sorted(_journal(tmp_path).glob("*.json"))
    if attack=="bytes":
        paths[0].write_bytes(paths[0].read_bytes()+b" ")
    elif attack=="extra":
        (_journal(tmp_path)/"unrecognized.txt").write_bytes(b"x")
    elif attack=="rename":
        paths[2].rename(paths[2].with_name("000006-"+paths[2].name[7:]))
    elif attack=="delete_first":
        paths[0].unlink()
    elif attack=="delete_middle":
        paths[1].unlink()
    elif attack=="noncanonical":
        original=paths[0]
        payload=json.loads(original.read_bytes())
        revised=json.dumps(payload,indent=2,sort_keys=True).encode()+b"\n"
        destination=original.with_name(
            "000001-"+sha256(revised).hexdigest()+".json"
        )
        original.unlink()
        destination.write_bytes(revised)
    else:
        from stronghold_europe_de import suite_build_history as target
        original=target._is_link
        monkeypatch.setattr(
            target,"_is_link",
            lambda path:path==paths[1] or original(path)
        )
    with pytest.raises(history.BuildHistoryError):
        history.read_build_history(tmp_path)
    assert not (tmp_path/"dist").exists()


@pytest.mark.parametrize("mutation",["foreign_profile","wrong_output",
                                     "duplicate","in_game_approved",
                                     "release_approved","successful_failed_cli"])
def test_forged_completion_is_never_appended(tmp_path,mutation):
    run=history.append_started(tmp_path,PROFILE,_before(tmp_path),replace=False)
    payload=_result(tmp_path)
    profile=PROFILE
    if mutation=="foreign_profile":
        profile="someone-else"
        payload["profile_id"]=profile
    elif mutation=="wrong_output":
        payload["output"]="C:/other/project/game"
    elif mutation=="in_game_approved":
        payload["ingame_approved"]=True
    elif mutation=="release_approved":
        payload["release_approved"]=True
    elif mutation=="successful_failed_cli":
        payload["state"]="offline_ok"
    elif mutation=="duplicate":
        history.append_completed(tmp_path,run,PROFILE,payload)
    with pytest.raises(history.BuildHistoryError):
        history.append_completed(tmp_path,run,profile,payload)
    assert len(history.read_build_history(tmp_path))==1


def test_existing_lock_blocks_writer_and_never_deletes_it(tmp_path):
    directory=_journal(tmp_path)
    directory.mkdir(parents=True)
    mutex=directory/".write-lock"
    mutex.mkdir()
    with pytest.raises(history.BuildHistoryError,match="lock"):
        history.append_started(tmp_path,PROFILE,_before(tmp_path),replace=False)
    assert mutex.is_dir()
    with pytest.raises(history.BuildHistoryError):
        history.read_build_history(tmp_path)


def test_written_result_larger_than_limit_is_rejected_without_partial_file(tmp_path):
    run=history.append_started(tmp_path,PROFILE,_before(tmp_path),replace=False)
    result=_result(tmp_path)
    result["detail"]="x"*(history.MAX_FILE_BYTES+100)
    with pytest.raises(history.BuildHistoryError,match="size"):
        history.append_completed(tmp_path,run,PROFILE,result)
    assert len(list(_journal(tmp_path).glob("*.json")))==1
    assert not list(_journal(tmp_path).glob(".temporary-*"))


def test_event_count_limit_avoids_overwriting_existing_history(tmp_path,monkeypatch):
    monkeypatch.setattr(history,"MAX_EVENTS",1)
    history.append_started(tmp_path,PROFILE,_before(tmp_path),replace=False)
    before=list(_journal(tmp_path).iterdir())
    with pytest.raises(history.BuildHistoryError,match="full"):
        history.append_started(tmp_path,PROFILE,_before(tmp_path),replace=False)
    assert list(_journal(tmp_path).iterdir())==before


def test_output_directory_symlink_or_reparse_is_not_followed(tmp_path,monkeypatch):
    import stronghold_europe_de.suite_build_history as target
    forbidden=tmp_path/"work"/"reports"/"suite-build-history"
    original=target._is_link
    monkeypatch.setattr(
        target,"_is_link",
        lambda path:path==forbidden or original(path)
    )
    with pytest.raises(history.BuildHistoryError,match="link"):
        history.append_started(tmp_path,PROFILE,_before(tmp_path),replace=False)
    assert not forbidden.exists()


def test_start_snapshot_wrong_schema_fails_without_commit(tmp_path):
    before=_before(tmp_path)
    before["schema"]="another-product"
    with pytest.raises(history.BuildHistoryError):
        history.append_started(tmp_path,PROFILE,before,replace=False)
    assert not list(_journal(tmp_path).glob("*.json"))



def test_inspection_exception_has_its_own_persistent_failed_state(tmp_path):
    run=history.append_started(tmp_path,PROFILE,_before(tmp_path),replace=False)
    history.append_inspection_failed(
        tmp_path,run,PROFILE,0,
        "Offline checker unexpectedly unavailable after a successful CLI"
    )
    latest=history.read_build_history(tmp_path)[0]
    assert latest["state"]=="abschlusspruefung_fehlgeschlagen"
    assert latest["result"] is None
    assert "unavailable" in latest["message"]


@pytest.mark.parametrize("mutation",["false_release","inconsistent_integrity",
                                     "no_audit_bytes","malformed_issues"])
def test_history_cannot_store_inconsistent_integrity_success(
    tmp_path,mutation
):
    run=history.append_started(tmp_path,PROFILE,_before(tmp_path),replace=False)
    result=_result(tmp_path)
    result.update({
        "state":"offline_ok","exit_code":0,
        "verified_files":12,"verified_bytes":2048,
        "errors":0,"warnings":0,"offline_integrity_ok":True,
        "manifest_sha256":"f"*64,"issues":[],
    })
    if mutation=="false_release":
        result["release_approved"]=True
    elif mutation=="inconsistent_integrity":
        result["offline_integrity_ok"]=False
    elif mutation=="no_audit_bytes":
        result["verified_files"]=0
    else:
        result["issues"]=[True]
    with pytest.raises(history.BuildHistoryError):
        history.append_completed(tmp_path,run,PROFILE,result)
    assert history.read_build_history(tmp_path)[0]["state"]=="unbestaetigt"



def test_read_only_cli_survives_windows_legacy_encoding(
    tmp_path,monkeypatch,capsys
):
    import importlib.util
    script=Path(__file__).resolve().parents[2]/"tools"/"qa_suite_build_history.py"
    spec=importlib.util.spec_from_file_location("suite_history_cli_tests",script)
    cli=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    monkeypatch.setattr(cli,"ROOT",tmp_path)
    started=history.append_started(
        tmp_path,PROFILE,_before(tmp_path),replace=False
    )
    assert cli.main(["--limit","5"]) == 0
    out=capsys.readouterr().out
    assert "1 Versuche" in out
    assert "unbestaetigt" in out
    assert started[:12] in out
    assert not (tmp_path/"dist").exists()
    first=next(_journal(tmp_path).glob("*.json"))
    first.write_bytes(first.read_bytes()+b"corrupted")
    assert cli.main([])==2
    assert "BUILD HISTORY INVALID" in capsys.readouterr().err


def test_source_hashes_are_bound_to_build_start_and_survive_restart(tmp_path):
    pinned = {
        "profile_sha256": "1" * 64,
        "config_sha256": "2" * 64,
        "mapping_sha256": "3" * 64,
        "unity_contract_sha256": "4" * 64,
        "toolchains_sha256": "5" * 64,
    }
    run = history.append_started(
        tmp_path, PROFILE, _before(tmp_path), replace=False,
        source_hashes=pinned,
    )
    found = history.read_build_history(tmp_path)
    assert len(found) == 1
    assert found[0]["run_id"] == run
    assert found[0]["source_hashes"] == pinned
    assert found[0]["state"] == "unbestaetigt"
    # A new reader sees the exact original SHA-256 input identities.
    assert history.read_build_history(tmp_path)[0]["source_hashes"] == pinned
    assert not (tmp_path / "dist").exists()


@pytest.mark.parametrize("payload", [
    {"profile_sha256": "a" * 64},
    {"profile_sha256": "a" * 64, "config_sha256": "b" * 64,
     "mapping_sha256": "malformed"},
    {"profile_sha256": "a" * 64, "config_sha256": "b" * 64,
     "mapping_sha256": "c" * 64, "untrusted": "d" * 64},
    {"profile_sha256": True, "config_sha256": "b" * 64,
     "mapping_sha256": "c" * 64},
])
def test_invalid_source_provenance_blocks_history_start(tmp_path, payload):
    with pytest.raises(history.BuildHistoryError, match="source SHA-256"):
        history.append_started(
            tmp_path, PROFILE, _before(tmp_path), replace=False,
            source_hashes=payload,
        )
    assert not list(_journal(tmp_path).glob("*.json"))
    assert not (tmp_path / "work").exists()


@pytest.mark.parametrize("mutate", ["invalid_kind", "impossible_date"])
def test_correctly_rehashed_but_malformed_event_is_a_controlled_error(
    tmp_path, mutate
):
    history.append_started(tmp_path, PROFILE, _before(tmp_path), replace=False)
    source = next(_journal(tmp_path).glob("*.json"))
    row = json.loads(source.read_bytes())
    if mutate == "invalid_kind":
        row["kind"] = []  # formerly raised an unhandled TypeError
    else:
        row["created_utc"] = "2026-99-99T22:10:11.000001+00:00"
    revised = history._encode(row)
    destination = source.with_name(
        f"000001-{sha256(revised).hexdigest()}.json"
    )
    source.unlink()
    destination.write_bytes(revised)
    with pytest.raises(history.BuildHistoryError):
        history.read_build_history(tmp_path)
    assert not (tmp_path / "dist").exists()


@pytest.mark.parametrize("mutation", [
    "success_without_digest",
    "offline_ok_with_warnings",
    "offline_ok_without_bytes",
    "invalid_comparison",
    "claim_old_manifest_as_new",
    "identical_claim_without_old_manifest",
])
def test_forged_offline_success_cannot_be_recorded(tmp_path, mutation):
    before = _before(tmp_path)
    if mutation == "claim_old_manifest_as_new":
        before["prior_manifest_sha256"] = "f" * 64
        before["prior_output_exists"] = True
    run = history.append_started(tmp_path, PROFILE, before, replace=False)
    result = _result(tmp_path)
    result.update({
        "state": "offline_ok", "exit_code": 0,
        "verified_files": 12, "verified_bytes": 2048,
        "errors": 0, "warnings": 0,
        "manifest_sha256": "f" * 64,
        "same_manifest_as_before": False,
        "offline_integrity_ok": True,
        "issues": [],
    })
    if mutation == "success_without_digest":
        result["manifest_sha256"] = None
    elif mutation == "offline_ok_with_warnings":
        result["warnings"] = 3
    elif mutation == "offline_ok_without_bytes":
        result["verified_bytes"] = 0
    elif mutation == "invalid_comparison":
        result["same_manifest_as_before"] = "no"
    elif mutation == "identical_claim_without_old_manifest":
        result["state"] = "same_manifest"
        result["same_manifest_as_before"] = True
    with pytest.raises(history.BuildHistoryError):
        history.append_completed(tmp_path, run, PROFILE, result)
    assert history.read_build_history(tmp_path)[0]["state"] == "unbestaetigt"


def test_saved_same_manifest_success_requires_original_manifest_identity(tmp_path):
    before = _before(tmp_path)
    before["prior_manifest_sha256"] = "f" * 64
    before["prior_output_exists"] = True
    run = history.append_started(tmp_path, PROFILE, before, replace=True)
    result = _result(tmp_path)
    result.update({
        "state": "same_manifest", "exit_code": 0,
        "verified_files": 2, "verified_bytes": 700,
        "errors": 0, "warnings": 0,
        "manifest_sha256": "f" * 64,
        "same_manifest_as_before": True,
        "offline_integrity_ok": True,
        "issues": [],
    })
    history.append_completed(tmp_path, run, PROFILE, result)
    recorded = history.read_build_history(tmp_path)[0]
    assert recorded["state"] == "same_manifest"
    assert recorded["result"]["same_manifest_as_before"] is True
    assert recorded["result"]["release_approved"] is False


def test_read_only_cli_displays_saved_input_hashes(tmp_path, monkeypatch, capsys):
    import importlib.util
    script = Path(__file__).resolve().parents[2] / "tools" / "qa_suite_build_history.py"
    spec = importlib.util.spec_from_file_location("suite_history_source_cli_test", script)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    hashes = {
        "profile_sha256": "a" * 64,
        "config_sha256": "b" * 64,
        "mapping_sha256": "c" * 64,
    }
    history.append_started(
        tmp_path, PROFILE, _before(tmp_path), replace=False,
        source_hashes=hashes,
    )
    assert cli.main(["--limit", "5"]) == 0
    output = capsys.readouterr().out
    assert "Eingangs-SHA:" in output
    assert "profile_sha256=aaaaaaaaaaaa" in output
    assert "mapping_sha256=cccccccccccc" in output
    assert "KEIN verifizierter Abschluss" in output
    assert not (tmp_path / "dist").exists()

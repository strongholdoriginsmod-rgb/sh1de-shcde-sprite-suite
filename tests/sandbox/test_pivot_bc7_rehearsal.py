"""Synthetic V2 BC7 preparation: proof of metadata-only invalidation.

Test both real production V2 project preparation functions and the
no-publication, fail-closed attestation boundary. Never run Unity/game.
"""
from __future__ import annotations

from hashlib import sha256
import importlib.util
import json
from pathlib import Path

import pytest

from stronghold_europe_de.pivot_bc7_rehearsal import (
    SCHEMA, PivotRehearsalError, _canonical, _direct, _hash, _prior,
    _safe_sources, _snapshot, _walk_exact, prepare_synthetic_pivot_rehearsal,
)
from stronghold_europe_de.unity_asset_bundle import (
    BC7_MEASUREMENT_POLICY_ID, validate_prepared_project_v2,
)
from stronghold_europe_de.asset_stream_contract import parse_atlas_v3

PROJECT=Path(__file__).resolve().parents[2]


def _evidence_directory(tmp_path: Path):
    out=tmp_path/"synthetic-rehearsal"
    out.mkdir()
    (out/"work").mkdir()
    fixture=out/"work"/"fixture.txt"
    fixture.write_bytes(b"immutable fixture")
    artifacts,dirs=_walk_exact(out)
    data={
        "schema":SCHEMA,"run_id":"abcdef0123456789abcd",
        "artifacts":artifacts,"directories":dirs,
        "release_allowed":False,"unity_executed":False,
        "assertion":"synthetic-only",
    }
    raw=_canonical(data)
    p=out/f"evidence-{sha256(raw).hexdigest()[:16]}.json"
    p.write_bytes(raw)
    return out,p


def test_real_v2_preparer_proves_exact_pivot_only_change_and_unchanged_control(tmp_path):
    editor,sources=_safe_sources(PROJECT)
    data=_snapshot(
        PROJECT,tmp_path,
        old_y=1.1090909242630005,new_y=1.0,editor=editor,
    )
    assert data["pixel_pages_identical"] is True
    assert data["changed_group_key_invalidated"] is True
    assert data["unaffected_group_key_stable"] is True
    assert set(data["synthetic_fixture_sha256"])=={"anim_castle","anim_drawbridge"}
    first=data["old"]; second=data["proposed"]
    assert first["build_id"]!=second["build_id"]
    assert first["build_input_sha256"]!=second["build_input_sha256"]
    assert first["template_sha256"]!=second["template_sha256"]
    a,b=first["groups"]["anim_castle"],second["groups"]["anim_castle"]
    assert a["pivot"] == [0.,1.1090909242630005]
    assert b["pivot"] == [0.,1.]
    assert a["cache_key_projection"]!=b["cache_key_projection"]
    assert a["frame_bindings"]["metadata_sha256"]!=b["frame_bindings"]["metadata_sha256"]
    assert a["frames_sha256"]!=b["frames_sha256"]
    assert a["page_png_sha256"]==b["page_png_sha256"]
    assert a["frame_bindings"]["main_rgba_sha256"]==b["frame_bindings"]["main_rgba_sha256"]
    assert a["rect"]==b["rect"]==[48,40]
    assert a["pixels_per_unit"]==b["pixels_per_unit"]==64.
    assert first["groups"]["anim_drawbridge"]==second["groups"]["anim_drawbridge"]
    for revision in (first,second):
        input_path=tmp_path/revision["input_relative_path"]
        index_doc=json.loads(input_path.read_text(encoding="utf-8"))
        assert index_doc["quality_policy"]["state"]=="measurement_nonpromotable"
        assert index_doc["quality_policy"]["id"]==BC7_MEASUREMENT_POLICY_ID
        project_path=tmp_path/revision["project_relative_path"]
        assert project_path.is_dir()
        assert (project_path/"ProjectSettings"/"ProjectVersion.txt").is_file()
        assert not list(project_path.rglob("*.bc7.v2"))
    assert set(sources)
    # Main and mask source images are never touched by the V2 preparer.
    assert not (tmp_path/"cache").exists()
    assert not (tmp_path/"dist").exists()


def test_pinned_attestation_exactly_reuses_identical_unmodified_tree(tmp_path):
    folder,filename=_evidence_directory(tmp_path)
    assert _prior(folder,"abcdef0123456789abcd")==filename
    with pytest.raises(PivotRehearsalError,match="identity"):
        _prior(folder,"wrong-id")


@pytest.mark.parametrize("tamper",["payload","extra","missing","directory","attestation"])
def test_immutable_rehearsal_rejects_modified_artifacts(tmp_path,tamper):
    folder,filename=_evidence_directory(tmp_path)
    if tamper=="payload":
        (folder/"work"/"fixture.txt").write_bytes(b"changed!")
    elif tamper=="extra":
        (folder/"unknown.dat").write_bytes(b"extra")
    elif tamper=="missing":
        (folder/"work"/"fixture.txt").unlink()
    elif tamper=="directory":
        (folder/"extra-empty").mkdir()
    else:
        filename.write_bytes(filename.read_bytes()+b" ")
    with pytest.raises(PivotRehearsalError):
        _prior(folder,"abcdef0123456789abcd")


@pytest.mark.parametrize("old,new",[
    (1,1),
    (1.000001,1),
    (float("nan"),1),
    (float("inf"),1),
    (True,1.5),
    (5,1),
])
def test_invalid_or_already_matched_pivot_does_not_write(tmp_path,old,new):
    with pytest.raises(PivotRehearsalError):
        prepare_synthetic_pivot_rehearsal(
            tmp_path,old_pivot_y=old,new_pivot_y=new
        )
    assert not (tmp_path/"work").exists()


def test_path_links_are_rejected_before_any_rehearsal_write(tmp_path,monkeypatch):
    import stronghold_europe_de.pivot_bc7_rehearsal as source
    linked=tmp_path/"work"/"pivot-bc7-rehearsals"
    original=source._is_link
    monkeypatch.setattr(source,"_is_link",lambda path:
                        path==linked or original(path))
    with pytest.raises(PivotRehearsalError,match="Linked"):
        _direct(tmp_path,Path("work")/"pivot-bc7-rehearsals")


def test_changed_builder_source_is_rejected_and_draft_is_cleaned(tmp_path,monkeypatch):
    import stronghold_europe_de.pivot_bc7_rehearsal as source
    editor=tmp_path/"tools"/"unity_asset_bundle"/"StrongholdEuropeAssetBundleBuilder.cs"
    editor.parent.mkdir(parents=True)
    editor.write_bytes(b"pinned synthetic editor source")
    other=tmp_path/"dummy"
    other.write_bytes(b"no writes elsewhere")
    tracked={str(editor):sha256(editor.read_bytes()).hexdigest()}
    monkeypatch.setattr(source,"_safe_sources",lambda root:(editor,tracked))
    monkeypatch.setattr(source,"_unity_readiness",
                        lambda root:{"discovery_status":"synthetic_mock"})
    def fake_snapshot(root,scratch,**kwargs):
        (scratch/"synthetic-fixtures").mkdir()
        (scratch/"synthetic-fixtures"/"sample.png").write_bytes(b"image")
        return {"fake_fixture":True}
    monkeypatch.setattr(source,"_snapshot",fake_snapshot)
    recorded=source._hash
    def changed_hash(path):
        if path==editor:
            return "f"*64
        return recorded(path)
    monkeypatch.setattr(source,"_hash",changed_hash)
    with pytest.raises(PivotRehearsalError,match="source changed"):
        source.prepare_synthetic_pivot_rehearsal(tmp_path)
    container=tmp_path/"work"/"pivot-bc7-rehearsals"
    assert not list(container.iterdir())
    assert other.read_bytes()==b"no writes elsewhere"


def test_cli_invalid_pivot_reports_blocker_without_publication(tmp_path,monkeypatch):
    script=PROJECT/"tools"/"qa_pivot_bc7_rehearsal.py"
    spec=importlib.util.spec_from_file_location("pivot_rehearsal_cli_test",script)
    command=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(command)
    monkeypatch.setattr(command,"ROOT",tmp_path)
    assert command.main(["--old-y","1","--new-y","1"])==2
    assert not (tmp_path/"work").exists()


def test_pinned_unity_editor_readiness_is_explicitly_not_a_build(tmp_path):
    from stronghold_europe_de.pivot_bc7_rehearsal import _unity_readiness
    from stronghold_europe_de.unity_asset_bundle import UNITY_VERSION,UNITY_REVISION,BUILD_TARGET
    config=tmp_path/"config"/"unity-assetbundle-toolchain.json"
    config.parent.mkdir()
    payload={
        "version":UNITY_VERSION, "revision":UNITY_REVISION,
        "build_target":BUILD_TARGET,
        "windows_executable_size_bytes":32,
        "windows_executable_sha256":"a"*64,
        "discovery_relative_paths":[
            "work/toolchains/unity-2021.3.45f2/Editor/Unity.exe",
        ],
    }
    config.write_text(json.dumps(payload),encoding="utf-8")
    found=_unity_readiness(tmp_path)
    assert found["discovery_status"]=="exact_editor_missing"
    assert found["unity_was_launched"] is False
    assert found["unity_binary_fully_usable"] is False
    # A mismatching executable must never qualify as an editor pin.
    candidate=tmp_path/"work"/"toolchains"/"unity-2021.3.45f2"/"Editor"/"Unity.exe"
    candidate.parent.mkdir(parents=True)
    candidate.write_bytes(b"x"*32)
    with pytest.raises(PivotRehearsalError,match="SHA-256"):
        _unity_readiness(tmp_path)
    assert candidate.read_bytes()==b"x"*32


@pytest.mark.parametrize("tamper",["version","sha","discovery","size"])
def test_invalid_unity_pin_prevents_preparation(tmp_path,tamper):
    from stronghold_europe_de.pivot_bc7_rehearsal import _unity_readiness
    from stronghold_europe_de.unity_asset_bundle import UNITY_VERSION,UNITY_REVISION,BUILD_TARGET
    config=tmp_path/"config"/"unity-assetbundle-toolchain.json"
    config.parent.mkdir()
    contract={
        "version":UNITY_VERSION, "revision":UNITY_REVISION,
        "build_target":BUILD_TARGET,
        "windows_executable_size_bytes":32,
        "windows_executable_sha256":"a"*64,
        "discovery_relative_paths":["work/toolchains/unity-2021.3.45f2/Editor/Unity.exe"],
    }
    if tamper=="version":
        contract["version"]="6000.5.9f1"
    elif tamper=="sha":
        contract["windows_executable_sha256"]="not-a-sha"
    elif tamper=="discovery":
        contract["discovery_relative_paths"]=["../../outside/Unity.exe"]
    else:
        contract["windows_executable_size_bytes"]=0
    config.write_text(json.dumps(contract),encoding="utf-8")
    with pytest.raises(PivotRehearsalError):
        _unity_readiness(tmp_path)
    assert not (tmp_path/"work").exists()

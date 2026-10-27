"""Read-only build readiness, blockers, consistency and source changes."""
from __future__ import annotations

import gzip
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import stronghold_europe_de.suite_build_readiness as ready

ROOT = Path(__file__).resolve().parents[2]


def _fixture(tmp_path, monkeypatch):
    root = tmp_path
    profile_id = "test-profile"
    profile = root/"profiles"/f"{profile_id}.json"
    profile.parent.mkdir()
    profile.write_text('{"profile":"placeholder"}',encoding="utf-8")
    game1=root/"fake-games"/"Stronghold 1 Definitive Edition_Data"
    game2=root/"fake-games"/"Stronghold Crusader Definitive Edition_Data"
    for folder in (game1,game2):
        folder.mkdir(parents=True)
        (folder/"resources.assets").write_bytes(b"not-real-art")
    game=(root/"fake-games"/"target-game")
    game.mkdir()
    source=root/"config"/"installations.local.toml"
    source.parent.mkdir()
    source.write_text("fake-config = true",encoding="utf-8")
    mapfile=root/"work"/"mapping"/"proposals.json.gz"
    mapfile.parent.mkdir(parents=True)
    with gzip.open(mapfile,"wb") as fd:
        fd.write(json.dumps({
            "schema_version":2,"source_build_id":"one","target_build_id":"two",
            "sprites":[{"name":"anim_castle 002"}],
        }).encode("utf-8"))
    unityfile=root/"config"/"unity-assetbundle-toolchain.json"
    unityfile.write_text(json.dumps({"windows_executable_sha256":"f"*64}),encoding="utf-8")
    config=SimpleNamespace(
        source=SimpleNamespace(data_dir=game1),
        target=SimpleNamespace(data_dir=game2,game_dir=game),
        output=SimpleNamespace(dist_dir=root/"dist",mod_folder_name="StrongholdEuropeDE"),
    )
    monkeypatch.setattr(ready,"load_config",lambda path:config)
    monkeypatch.setattr(ready,"load_profile",lambda path:{
        "id":profile_id,"runtime":{"kind":"fixture"},
        "atlas_backend":{"kind":"unity_assetbundle_bc7_visual_equivalence_v2"},
    })
    monkeypatch.setattr(ready,"_validate_group_backend_selection",lambda profile:None)
    editor=root/"tools"/"fake-unity"/"Unity.exe"
    editor.parent.mkdir(parents=True)
    editor.write_bytes(b"synthetic-editor")
    monkeypatch.setattr(ready,"_resolve_toolchain",lambda root,explicit:
                        SimpleNamespace(executable=editor,executable_sha256="f"*64))
    monkeypatch.setattr(ready,"_sdk_on_disk",lambda hint:(True,"SDK fixture vorhanden"))
    return root, profile_id, config


def test_current_public_profile_exposes_real_missing_prerequisites():
    report = ready.audit_build_readiness(ROOT,"sprite-suite-world-bc7-v2")
    assert report["schema"]==ready.SCHEMA
    assert report["ready_for_attempt"] is False
    assert report["build_executed"] is False
    assert report["release_certified"] is False
    assert report["no_changes_made"] is True
    assert report["blocker_count"]>=2
    statuses={item["name"]:item["state"] for item in report["checks"]}
    assert statuses["Profil"]=="ok"
    # On a fresh worktree there is no user's private mapping cache. The
    # readiness gate must report its absence instead of inventing approval.
    has_mapping=(ROOT/"work"/"mapping"/"proposals.json.gz").is_file()
    assert statuses["Mapping"]==("ok" if has_mapping else "blockiert")
    assert statuses["Unity-BC7"]=="blockiert"


def test_fixture_readiness_is_only_permission_to_attempt_build(tmp_path,monkeypatch):
    root,profile_id,_=_fixture(tmp_path,monkeypatch)
    before={p.relative_to(root):p.read_bytes() for p in root.rglob("*") if p.is_file()}
    report=ready.audit_build_readiness(root,profile_id)
    assert report["state"]=="bauversuch_moeglich"
    assert report["ready_for_attempt"] is True
    assert report["blocker_count"]==0
    assert report["notice_count"]==0
    assert report["checks"][0]["name"]=="Profil"
    assert report["source_hashes"]["mapping_sha256"]
    assert "does not verify a complete Unity/BC7 build" in report["disclaimer"]
    assert report["build_executed"] is False
    assert {p.relative_to(root):p.read_bytes() for p in root.rglob("*") if p.is_file()} == before


@pytest.mark.parametrize("failure",[
    "games","mapping","unity","sdk","wrong_profile","invalid_profile",
])
def test_missing_or_incorrect_input_fails_closed(tmp_path,monkeypatch,failure):
    root,pid,config=_fixture(tmp_path,monkeypatch)
    if failure=="games":
        (config.target.data_dir/"resources.assets").unlink()
    elif failure=="mapping":
        (root/"work"/"mapping"/"proposals.json.gz").unlink()
    elif failure=="unity":
        monkeypatch.setattr(ready,"_resolve_toolchain",
                            lambda root,explicit:SimpleNamespace(
                                executable=root/"tools"/"fake-unity"/"Unity.exe",
                                executable_sha256="a"*64,
                            ))
    elif failure=="sdk":
        monkeypatch.setattr(ready,"_sdk_on_disk",lambda hint:(False,"No SDK"))
    elif failure=="wrong_profile":
        monkeypatch.setattr(ready,"load_profile",
                            lambda path:{"id":"wrong"})
    else:
        (root/"profiles"/f"{pid}.json").unlink()
    report=ready.audit_build_readiness(root,pid)
    assert not report["ready_for_attempt"]
    assert report["blocker_count"]>=1
    assert not (root/"dist").exists()


def test_existing_package_not_replaced_without_explicit_choice(tmp_path,monkeypatch):
    root,pid,config=_fixture(tmp_path,monkeypatch)
    target=config.output.dist_dir/pid/config.output.mod_folder_name
    target.mkdir(parents=True)
    artifact=target/"protected-bundle.bin"
    artifact.write_bytes(b"keep-original")
    block=ready.audit_build_readiness(root,pid)
    assert block["state"]=="blockiert"
    assert [r for r in block["checks"] if r["name"]=="Paketausgabe"][0]["state"]=="blockiert"
    opted=ready.audit_build_readiness(root,pid,replace=True)
    assert opted["ready_for_attempt"] is True
    assert [r for r in opted["checks"] if r["name"]=="Paketausgabe"][0]["state"]=="hinweis"
    assert artifact.read_bytes()==b"keep-original"


def test_untrusted_output_symlink_is_blocked(tmp_path,monkeypatch):
    root,pid,config=_fixture(tmp_path,monkeypatch)
    target=config.output.dist_dir/pid/config.output.mod_folder_name
    original=ready._is_link
    monkeypatch.setattr(ready,"_is_link",lambda path:
                        path==target or original(path))
    report=ready.audit_build_readiness(root,pid,replace=True)
    assert report["blocker_count"]==1
    assert [r for r in report["checks"] if r["name"]=="Paketausgabe"][0]["state"]=="blockiert"


def test_source_drift_after_processing_is_hard_error(tmp_path,monkeypatch):
    root,pid,_=_fixture(tmp_path,monkeypatch)
    original=ready._sha256_file
    profile=root/"profiles"/f"{pid}.json"
    attempts={}
    def drifting_hash(path):
        value=original(path)
        if path==profile:
            attempts[str(path)]=attempts.get(str(path),0)+1
            if attempts[str(path)]>1:
                return "0"*64
        return value
    monkeypatch.setattr(ready,"_sha256_file",drifting_hash)
    with pytest.raises(ready.BuildReadinessError,match="während der Prüfung"):
        ready.audit_build_readiness(root,pid)


def test_invalid_profile_ids_and_boolean_shape_rejected(tmp_path):
    for name in ("../evil","", "Bad Space"):
        with pytest.raises(ready.BuildReadinessError,match="Profil-ID"):
            ready.audit_build_readiness(tmp_path,name)
    with pytest.raises(ready.BuildReadinessError,match="boolesch"):
        ready.audit_build_readiness(tmp_path,"some-profile",replace=1)


def test_sdks_detected_without_executing_program(tmp_path,monkeypatch):
    tool=tmp_path/"dotnet"
    tool.mkdir()
    (tool/"dotnet.exe").write_bytes(b"not-executed")
    sub=tool/"sdk"
    sub.mkdir()
    (sub/"8.0.100").mkdir()
    assert ready._sdk_on_disk(str(tool))[0] is True
    (sub/"8.0.100").rename(sub/"7.0.100")
    check,detail=ready._sdk_on_disk(str(tool))
    assert check is False and "Kein stabiles" in detail


def test_cli_utf_8_text_survives_legacy_windows_cp1252():
    import importlib.util
    p=ROOT/"tools"/"qa_suite_build_readiness.py"
    spec=importlib.util.spec_from_file_location("suite_readiness_cli_test",p)
    cli=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    class CpStream:
        encoding="cp1252"
        def __init__(self):
            self.data=""
        def write(self,s):
            s.encode(self.encoding)
            self.data+=s
    fake=CpStream()
    cli._line("Einrichten → Pfade speichern",file=fake)
    assert "Einrichten" in fake.data
    assert "\\u2192" in fake.data


def test_fresh_ready_report_is_rechecked_before_launch(tmp_path,monkeypatch):
    root,profile_id,_=_fixture(tmp_path,monkeypatch)
    report=ready.audit_build_readiness(root,profile_id)
    ready.recheck_build_readiness_before_start(
        root,profile_id,replace=False,report=report
    )
    assert report["output_target"]==str(
        root/"dist"/profile_id/"StrongholdEuropeDE"
    )
    assert report["output_exists_at_check"] is False


@pytest.mark.parametrize("input_file",[
    "profiles/test-profile.json",
    "config/installations.local.toml",
    "work/mapping/proposals.json.gz",
    "config/unity-assetbundle-toolchain.json",
])
def test_ready_report_rejected_if_input_changes_before_build(
    tmp_path,monkeypatch,input_file
):
    root,profile_id,_=_fixture(tmp_path,monkeypatch)
    report=ready.audit_build_readiness(root,profile_id)
    target=root/input_file
    target.write_bytes(target.read_bytes()+b"changed-after-check")
    with pytest.raises(ready.BuildReadinessError,match="Quellstand"):
        ready.recheck_build_readiness_before_start(
            root,profile_id,replace=False,report=report
        )
    assert not (root/"dist").exists()


@pytest.mark.parametrize("change",[
    "profile_id", "replace", "blocker_count", "missing_hash", "untrusted_flag",
])
def test_malformed_readiness_cannot_start_build(tmp_path,monkeypatch,change):
    root,profile_id,_=_fixture(tmp_path,monkeypatch)
    report=ready.audit_build_readiness(root,profile_id)
    if change=="profile_id":
        report["profile_id"]="different-profile"
    elif change=="replace":
        report["replace_selected"]=True
    elif change=="blocker_count":
        report["blocker_count"]=1
    elif change=="missing_hash":
        report["source_hashes"].pop("profile_sha256")
    else:
        report["release_certified"]=True
    with pytest.raises(ready.BuildReadinessError):
        ready.recheck_build_readiness_before_start(
            root,profile_id,replace=False,report=report
        )
    assert not (root/"dist").exists()


def test_build_confirmation_detects_new_output_folder(tmp_path,monkeypatch):
    root,profile_id,config=_fixture(tmp_path,monkeypatch)
    report=ready.audit_build_readiness(root,profile_id,replace=True)
    target=config.output.dist_dir/profile_id/config.output.mod_folder_name
    target.mkdir(parents=True)
    file=target/"unapproved-output"
    file.write_bytes(b"preserve")
    with pytest.raises(ready.BuildReadinessError,match="Paketausgabe"):
        ready.recheck_build_readiness_before_start(
            root,profile_id,replace=True,report=report
        )
    assert file.read_bytes()==b"preserve"


def test_existing_target_must_be_directory_even_with_replace(tmp_path,monkeypatch):
    root,profile_id,config=_fixture(tmp_path,monkeypatch)
    target=config.output.dist_dir/profile_id/config.output.mod_folder_name
    target.parent.mkdir(parents=True)
    target.write_bytes(b"file-not-directory")
    report=ready.audit_build_readiness(root,profile_id,replace=True)
    assert report["ready_for_attempt"] is False
    assert any("kein Verzeichnis" in row["detail"] for row in report["checks"])
    assert target.read_bytes()==b"file-not-directory"




@pytest.mark.parametrize("field",["unity","dotnet","source","target"])
def test_unsaved_setup_text_cannot_produce_false_build_readiness(
    tmp_path,monkeypatch,field
):
    root,pid,config=_fixture(tmp_path,monkeypatch)
    unsaved=root/"separate-new-location"
    if field=="unity":
        unsaved.write_bytes(b"not-saved")
        report=ready.audit_build_readiness(root,pid,unity_hint=str(unsaved))
        section="Unity-BC7"
    elif field=="dotnet":
        unsaved.mkdir()
        (unsaved/"dotnet.exe").write_bytes(b"not-saved")
        report=ready.audit_build_readiness(root,pid,dotnet_hint=str(unsaved))
        section=".NET-SDK"
    elif field=="source":
        report=ready.audit_build_readiness(root,pid,source_hint=str(unsaved))
        section="Originalspiele"
    else:
        report=ready.audit_build_readiness(root,pid,target_hint=str(unsaved))
        section="Originalspiele"
    assert report["ready_for_attempt"] is False
    assert report["blocker_count"]>=1
    assert [x for x in report["checks"] if x["name"]==section][0]["state"]=="blockiert"
    assert not (root/"dist").exists()


def test_saved_paths_match_actual_builder_and_are_pinned(tmp_path,monkeypatch):
    root,pid,config=_fixture(tmp_path,monkeypatch)
    editor=root/"tools"/"fake-unity"/"Unity.exe"
    sdk=root/"selected-sdk"
    sdk.mkdir()
    (sdk/"dotnet.exe").write_bytes(b"synthetic-sdk")
    (sdk/"sdk"/"8.0.100").mkdir(parents=True)
    record={"unity_editor":str(editor),"dotnet_directory":str(sdk)}
    local=root/"config"/"toolchains.local.json"
    local.write_text(json.dumps(record),encoding="utf-8")
    report=ready.audit_build_readiness(
        root,pid,unity_hint=str(editor),dotnet_hint=str(sdk),
        source_hint=str(config.source.data_dir),
        target_hint=str(config.target.game_dir),
    )
    assert report["ready_for_attempt"] is True
    assert "toolchains_sha256" in report["source_hashes"]
    ready.recheck_build_readiness_before_start(
        root,pid,replace=False,report=report
    )
    local.write_bytes(local.read_bytes()+b" ")
    with pytest.raises(ready.BuildReadinessError,match="Quellstand"):
        ready.recheck_build_readiness_before_start(
            root,pid,replace=False,report=report
        )


def test_saved_toolchain_settings_with_invalid_json_block(tmp_path,monkeypatch):
    root,pid,_=_fixture(tmp_path,monkeypatch)
    path=root/"config"/"toolchains.local.json"
    path.write_text("{nope",encoding="utf-8")
    report=ready.audit_build_readiness(root,pid)
    assert report["ready_for_attempt"] is False
    assert any(row["name"]=="Toolchain-Einstellungen"
               and row["state"]=="blockiert" for row in report["checks"])


def test_saved_toolchain_path_overrides_unsaved_unity_entry(
    tmp_path,monkeypatch
):
    root,pid,_=_fixture(tmp_path,monkeypatch)
    editor=root/"tools"/"fake-unity"/"Unity.exe"
    path=root/"config"/"toolchains.local.json"
    path.write_text(json.dumps({"unity_editor":str(editor)}),encoding="utf-8")
    seen=[]
    def fake_resolve(root,explicit):
        seen.append(explicit)
        return SimpleNamespace(executable=editor,executable_sha256="f"*64)
    monkeypatch.setattr(ready,"_resolve_toolchain",fake_resolve)
    report=ready.audit_build_readiness(root,pid)
    assert seen==[editor]
    assert report["ready_for_attempt"] is True



@pytest.mark.parametrize("bad_json",[
    '{"unity_editor":"first","unity_editor":"second"}',
    '{"dotnet_directory":NaN}',
    '{"unity_editor":true}',
])
def test_ambiguous_or_malformed_saved_toolchain_file_blocks(
    tmp_path,monkeypatch,bad_json
):
    root,pid,_=_fixture(tmp_path,monkeypatch)
    settings=root/"config"/"toolchains.local.json"
    settings.write_text(bad_json,encoding="utf-8")
    report=ready.audit_build_readiness(root,pid)
    assert report["ready_for_attempt"] is False
    assert any(
        row["name"]=="Toolchain-Einstellungen"
        and row["state"]=="blockiert"
        for row in report["checks"]
    )
    assert not (root/"dist").exists()

"""No-write community compatibility and third-party coexistence safety gates."""
from __future__ import annotations
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace
import shutil
import sys

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"tools"))
import community_mod_compat as compat
import ziel_se211 as manager

def put_info(folder,guid,ver="0.1.0",**extra):
    folder.mkdir(parents=True,exist_ok=True)
    (folder/"info.json").write_text(
        json.dumps(dict(GUID=guid,Version=ver,**extra)),encoding="utf-8")

@pytest.fixture
def setup(tmp_path):
    project=tmp_path/"project"
    cfg=project/"config"
    cfg.mkdir(parents=True)
    shutil.copyfile(ROOT/"config"/"shcde-community-compat-20261022.json",
                    cfg/"shcde-community-compat-20261022.json")
    game=tmp_path/"game"
    plugin_dir=game/"BepInEx"/"plugins"
    put_info(plugin_dir/"000shcdese","000shcdese","2.11.0")
    put_info(plugin_dir/"StrongholdEuropeDE","strongholdeuropede.private","0.16.0-europe")
    se=plugin_dir/"000shcdese"/"SHCDESE.dll"
    core=game/"BepInEx"/"core"/"BepInEx.dll"
    core.parent.mkdir(parents=True)
    se.write_bytes(b"fake pinned SE 2.11.0")
    core.write_bytes(b"fake pinned BepInEx core")
    pins={"script_extender_version":"2.11.0","files":[{
        "id":code,"relative_path":rel,"size":path.stat().st_size,
        "sha256":sha256(path.read_bytes()).hexdigest(),
        "assembly_version":version
    } for code,rel,path,version in (
        ("shcdese",compat.SE_DLL,se,"2.11.0.0"),
        ("bepinex_core",compat.BEP_DLL,core,"5.4.23.5"))]}
    (cfg/"runtime-prerequisites.json").write_text(json.dumps(pins),encoding="utf-8")
    candidate=project/"dist"/"StrongholdEuropeDE"
    put_info(candidate,compat.OWN_GUID,"0.16.0-europe")
    (candidate/"StrongholdEuropeDE.Runtime.dll").write_bytes(b"private only")
    attestation=candidate/"Runtime"/"audio-profile.tsv"
    attestation.parent.mkdir(parents=True)
    attestation.write_text(
        "stronghold-europe-audio-profile\t1\n"
        "plugin_id\tstrongholdeuropede.runtime.private\n"
        "script_extender_version\t2.11.0.0\n",encoding="utf-8")
    return project,game,candidate

def codes(result):
    return {r["code"] for r in result["issues"] if r["severity"]=="BLOCK"}

def test_pinned_private_package_is_static_safe_but_gameplay_is_unproven(setup):
    project,game,candidate=setup
    initial=sha256((game/compat.SE_DLL).read_bytes()).digest()
    result=compat.check(game,candidate,project=project)
    assert not codes(result)
    assert result["status"]=="REVIEW_REQUIRED"
    assert compat.require_safe_to_install(game,candidate,project=project)
    assert result["installed_script_extender_version"]=="2.11.0"
    assert sha256((game/compat.SE_DLL).read_bytes()).digest()==initial

def test_central_apishared_092_blocks_extender_211(setup):
    project,game,candidate=setup
    put_info(game/"BepInEx/plugins/APIShared_Serp","APIShared_Serp","0.9.2",
             MinimumScriptExtenderVersion="2.14.0")
    result=compat.check(game,candidate,project=project)
    assert "API_SHARED_MIN_SE" in codes(result)
    with pytest.raises(compat.CompatibilityError,match="API_SHARED_MIN_SE"):
        compat.require_safe_to_install(game,candidate,project=project)

def test_two_copies_of_apishared_share_guid_and_are_rejected(setup):
    project,game,candidate=setup
    put_info(game/"BepInEx/plugins/APIShared_Serp","APIShared_Serp","0.9.2",
             MinimumScriptExtenderVersion="2.14.0")
    put_info(game/"BepInEx/plugins/SomeMod","APIShared_Serp","0.9.2")
    report=compat.check(game,candidate,project=project)
    assert "DUPLICATE_PLUGIN_GUID" in codes(report)

@pytest.mark.parametrize("filename",["SHCDESE.dll","APIShared.dll",
                                      "BepInEx.dll","0Harmony.dll"])
def test_foreign_runtime_dll_must_not_be_bundled(setup,filename):
    project,game,candidate=setup
    (candidate/filename).write_bytes(b"duplicate foreign library")
    result=compat.check(game,candidate,project=project)
    assert "BUNDLED_SHARED_DLL" in codes(result)

def test_wrong_plugin_guid_and_existing_foreign_owner_block_install(setup):
    project,game,candidate=setup
    put_info(candidate,"APIShared_Serp")
    assert "WRONG_CANDIDATE_GUID" in codes(
        compat.check(game,candidate,project=project))
    put_info(candidate,compat.OWN_GUID)
    put_info(game/"BepInEx/plugins/StrongholdEuropeDE","foreign.owner")
    assert "FOREIGN_DESTINATION_OWNERSHIP" in codes(
        compat.check(game,candidate,project=project))

def test_co_installed_fixes_require_joint_runtime_qa(setup):
    project,game,candidate=setup
    put_info(game/"BepInEx/plugins/Fixes","fixes","1.29.0")
    result=compat.check(game,candidate,project=project)
    assert not codes(result)
    with pytest.raises(compat.CompatibilityError,match="IN_GAME_HOOK"):
        compat.require_safe_to_install(game,candidate,project=project)

def test_binary_pin_mismatch_is_blocking_not_warning(setup):
    project,game,candidate=setup
    se=game/compat.SE_DLL
    se.write_bytes(b"not pinned anymore, byte changed")
    assert "RUNTIME_ABI_PIN_MISMATCH" in codes(
        compat.check(game,candidate,project=project))

def test_real_qa_game_reports_abi_mismatch_without_writes():
    game=Path("E:/SSGameQA")
    candidate=ROOT/"dist/europe-production-bc7-v2/StrongholdEuropeDE"
    if not (game/compat.SE_DLL).is_file() or not candidate.is_dir():
        pytest.skip("Local QA game missing")
    old=sha256((game/compat.SE_DLL).read_bytes()).hexdigest()
    result=compat.check(game,candidate)
    assert result["installed_script_extender_version"]=="1.44.0"
    assert "RUNTIME_ABI_PIN_MISMATCH" in codes(result)
    assert "PACKAGE_SE_ATTESTATION_MISMATCH" in codes(result)
    assert result["candidate"]["runtime_guid"]=="strongholdeuropede.runtime.private"
    assert result["candidate"]["runtime_se_version"]=="1.44.0.0"
    assert sha256((game/compat.SE_DLL).read_bytes()).hexdigest()==old

def test_installer_checks_safety_before_backups(setup,monkeypatch):
    project,game,candidate=setup
    put_info(game/"BepInEx/plugins/APIShared_Serp","APIShared_Serp","0.9.2",
             MinimumScriptExtenderVersion="2.14.0")
    monkeypatch.setattr(manager,"PROJECT_ROOT",project)
    monkeypatch.setattr(manager,"safe_target",lambda _name:game)
    monkeypatch.setattr(manager,"resolve",lambda name:(name,game))
    monkeypatch.setattr(manager,"game_running",lambda:False)
    calls=[]
    monkeypatch.setattr(manager,"make_backup",
                        lambda *args: calls.append("BACKUP_STARTED"))
    args=SimpleNamespace(name="qa",quelle=str(candidate),ordner="StrongholdEuropeDE")
    with pytest.raises(SystemExit,match="API_SHARED_MIN_SE"):
        manager.cmd_mod_installieren(args)
    assert calls==[]

def test_installer_never_replaces_known_community_plugin_dirs(setup,monkeypatch):
    project,game,candidate=setup
    monkeypatch.setattr(manager,"PROJECT_ROOT",project)
    monkeypatch.setattr(manager,"safe_target",lambda _name:game)
    monkeypatch.setattr(manager,"resolve",lambda name:(name,game))
    monkeypatch.setattr(manager,"game_running",lambda:False)
    monkeypatch.setattr(manager,"make_backup",
                        lambda *_:pytest.fail("Backup should never start"))
    for name in ("000shcdese","APIShared_Serp","fixes",
                 "CrusaderDETweaker","SerpsMods"):
        with pytest.raises(SystemExit,match="Fremdprojekt"):
            manager.cmd_mod_installieren(
                SimpleNamespace(name="qa",quelle=str(candidate),ordner=name))

def test_outdated_se211_auto_install_is_blocked_without_backup(setup,monkeypatch):
    project,game,_=setup
    monkeypatch.setattr(manager,"PROJECT_ROOT",project)
    monkeypatch.setattr(manager,"safe_target",lambda _name:game)
    monkeypatch.setattr(manager,"resolve",lambda name:(name,game))
    monkeypatch.setattr(manager,"game_running",lambda:False)
    # The generated dummy DLL has no real PE version; supply the matching
    # historical metadata so the community minimum-version gate is reached.
    monkeypatch.setattr(manager,"file_version",lambda _path:"2.11.0.0")
    monkeypatch.setattr(manager,"make_backup",
                        lambda *_:pytest.fail("Do not start a backup/write"))
    with pytest.raises(SystemExit,match="zu alt"):
        manager.cmd_se_installieren(SimpleNamespace(name="qa",zip=None))

def test_tool_formats_are_not_silently_interchangeable():
    contract=compat.load_json(ROOT/"config/shcde-community-compat-20261022.json")
    formats={x["name"]:x["format"] for x in contract["tool_formats"]}
    assert formats["AI-Toolkit"]==".aiv"
    assert formats["Serpens AIVParser"]==".aivjson"
    assert ".sav" not in formats["Serpens MapParser"]
    assert formats["Serpens SaveExtractor"]==".sav"
    assert formats["Serpens TrailEditor"]==".trail"
    assert formats["Serpens AtlasBuilder"].startswith("Override/Atlas/")
    assert len(set(formats.values()))==len(formats)


def test_removal_of_any_community_owned_plugin_refused_before_backup(setup,monkeypatch):
    project,game,candidate=setup
    monkeypatch.setattr(manager,"PROJECT_ROOT",project)
    monkeypatch.setattr(manager,"safe_target",lambda _name:game)
    monkeypatch.setattr(manager,"resolve",lambda name:(name,game))
    monkeypatch.setattr(manager,"game_running",lambda:False)
    monkeypatch.setattr(manager,"make_backup",
                        lambda *_:pytest.fail("Must refuse before any filesystem change"))
    for name in ("000shcdese","APIShared_Serp","fixes",
                 "CrusaderDETweaker","SerpsModsHost"):
        marker=game/"BepInEx"/"plugins"/name
        marker.mkdir(parents=True,exist_ok=True)
        important=marker/"preserve.bin"
        important.write_bytes(b"thirdparty original")
        with pytest.raises(SystemExit,match="Fremdprojekt"):
            manager.cmd_mod_entfernen(SimpleNamespace(name="qa",ordner=name))
        assert important.read_bytes()==b"thirdparty original"
    assert not (game/"_suite-sicherungen").exists()


@pytest.mark.parametrize("relative",[
    "BepInEx/plugins/APIShared_Serp",
    "BepInEx/plugins/000shcdese/SHCDESE.dll",
    "BepInEx/plugins/fixes",
    r"BepInEx\plugins\CrusaderDETweaker",
])
def test_backup_restore_cannot_touch_community_plugin_tree(setup,relative):
    project,game,candidate=setup
    with pytest.raises(SystemExit,match="Fremdplugin"):
        manager.assert_safe_restore_paths(game,[relative])
    assert not (game/"_suite-sicherungen").exists()


def test_historic_restore_index_cannot_write_foreign_plugin(setup,monkeypatch):
    project,game,candidate=setup
    backup=game/"_suite-sicherungen"
    backup.mkdir(parents=True)
    (backup/"sicherungen.json").write_text(json.dumps({
        "eintraege":[{
            "id":"old-copy","pfade":["BepInEx/plugins/APIShared_Serp"],
            "gesichert":["BepInEx/plugins/APIShared_Serp"]
        }]}),encoding="utf-8")
    monkeypatch.setattr(manager,"PROJECT_ROOT",project)
    monkeypatch.setattr(manager,"safe_target",lambda _:game)
    monkeypatch.setattr(manager,"resolve",lambda name:(name,game))
    monkeypatch.setattr(manager,"make_backup",lambda *_:pytest.fail(
        "Rollback must refuse before backup or game mutation"))
    with pytest.raises(SystemExit,match="Fremdplugin"):
        manager.cmd_zurueckspielen(
            SimpleNamespace(name="qa",sicherung="old-copy"))
    assert (backup/"sicherungen.json").is_file()
    assert not (game/"BepInEx/plugins/APIShared_Serp").exists()


def test_unknown_nested_plugin_without_manifest_blocks_unverified_hooks(setup):
    project,game,candidate=setup
    unknown=game/"BepInEx/plugins/UnknownProvider/lib"
    unknown.mkdir(parents=True)
    (unknown/"UnknownProvider.dll").write_bytes(b"unknown hooks")
    result=compat.check(game,candidate,project=project)
    assert "PLUGIN_WITHOUT_MANIFEST" in {x["code"] for x in result["issues"]}
    with pytest.raises(compat.CompatibilityError,match="PLUGIN_WITHOUT_MANIFEST"):
        compat.require_safe_to_install(game,candidate,project=project)


def test_package_id_and_runtime_plugin_id_are_two_distinct_contracts(setup):
    project,game,candidate=setup
    snapshot=compat.load_json(project/"config/shcde-community-compat-20261022.json")
    contracts=snapshot["plugin_contracts"]
    assert contracts["private_suite_guid"]=="strongholdeuropede.private"
    assert contracts["suite_runtime_plugin_guid"]=="strongholdeuropede.runtime.private"
    assert contracts["private_suite_guid"]!=contracts["suite_runtime_plugin_guid"]
    from stronghold_europe_de import runtime_build
    assert runtime_build._PLUGIN_ID==contracts["suite_runtime_plugin_guid"]
    audit=compat.check(game,candidate,project=project)
    assert not codes(audit)
    assert audit["candidate"]["guid"]==contracts["private_suite_guid"]
    assert audit["candidate"]["runtime_guid"]==contracts["suite_runtime_plugin_guid"]


def test_runtime_identity_mismatch_never_reaches_plugin_install(setup):
    project,game,candidate=setup
    file=candidate/"Runtime/audio-profile.tsv"
    before=file.read_text(encoding="utf-8")
    file.write_text(before.replace(
        "strongholdeuropede.runtime.private", "APIShared_Serp"
    ),encoding="utf-8")
    result=compat.check(game,candidate,project=project)
    assert "PACKAGE_RUNTIME_GUID_MISMATCH" in codes(result)
    with pytest.raises(compat.CompatibilityError,match="PACKAGE_RUNTIME_GUID_MISMATCH"):
        compat.require_safe_to_install(game,candidate,project=project)


def test_packaged_se_144_vs_tested_source_211_is_blocking(setup):
    project,game,candidate=setup
    file=candidate/"Runtime/audio-profile.tsv"
    file.write_text(file.read_text(encoding="utf-8").replace(
        "2.11.0.0", "1.44.0.0"
    ),encoding="utf-8")
    result=compat.check(game,candidate,project=project)
    assert "PACKAGE_SE_ATTESTATION_MISMATCH" in codes(result)
    assert "PACKAGE_INSTALLED_SE_MISMATCH" in codes(result)
    with pytest.raises(compat.CompatibilityError,match="PACKAGE_SE_ATTESTATION_MISMATCH"):
        compat.require_safe_to_install(game,candidate,project=project)


def test_missing_or_duplicate_runtime_identity_is_blocked(setup):
    project,game,candidate=setup
    file=candidate/"Runtime/audio-profile.tsv"
    original=file.read_bytes()
    file.unlink()
    assert "INVALID_PACKAGE_RUNTIME_ATTESTATION" in codes(
        compat.check(game,candidate,project=project))
    file.write_bytes(original+bytes("\nplugin_id\tsecond.runtime.guid\n","utf-8"))
    assert "INVALID_PACKAGE_RUNTIME_ATTESTATION" in codes(
        compat.check(game,candidate,project=project))

"""Read-only native menu candidate build against installed game's real DLLs."""
from __future__ import annotations

from pathlib import Path
from hashlib import sha256
import json
import os
import sys
import tkinter as tk

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/"tools"),str(ROOT/"src")]
import hud_menu_workspace as work
import origins_runtime_authoring as author
import origins_native_menu_compiler as native
import origins_native_abi_probe as abi
import suite_origins_runtime_workshop as workshop

REAL_GAME=Path(r"D:\Games\Stronghold Crusader Definitive Edition")


@pytest.fixture
def project(tmp_path,monkeypatch):
    suite=tmp_path/"suite";(suite/"work").mkdir(parents=True)
    monkeypatch.setattr(work,"ROOT",suite)
    monkeypatch.setattr(work,"WORK",suite/"work")
    return suite/"work"/"my-origins-menu"


def _available():
    if os.name!="nt" or not native.CSC.is_file() or not REAL_GAME.is_dir():
        pytest.skip("Windows installed SHCDE, compiler and references required")


def _campaign(project,name="native-campaign"):
    saved=author.write_campaign_draft(project,{
        "name":name,"title":"Eigene Kampagne",
        "missions":[{"number":1,"title":"Demo Mission",
                     "map":"Demo 1.map","act":"Act One"}],
    })
    return Path(saved["output"])


def test_native_candidate_compiles_with_exact_unity_references_without_game_install(project):
    _available()
    _campaign(project)
    game_source=REAL_GAME/"Stronghold Crusader Definitive Edition_Data"/"Managed"/"Assembly-CSharp.dll"
    checksum=sha256(game_source.read_bytes()).hexdigest()
    proof=native.compile_menu_candidate(project,"native-campaign",REAL_GAME)
    dll=Path(proof["dll"])
    assert dll.is_file()
    assert dll.read_bytes().startswith(b"MZ")
    assert proof["compiled_managed_dll_sha256"]==sha256(dll.read_bytes()).hexdigest()
    assert Path(proof["report"]).is_file()
    assert proof["native_game_hook_registered"] is False
    assert proof["compiled_candidate_metadata_attested"] is True
    assert all(proof["compiled_candidate_metadata_signatures"].values())
    assert not list(Path(proof["output"]).glob("Mono.Cecil.dll"))
    assert "CANDIDATE_HAS_HARMONY_PREFIX=1" in (
        Path(proof["output"])/"candidate-metadata.log").read_text("utf8")
    assert proof["game_abi_fully_attested"] is False
    assert proof["map_launch_implemented"] is False
    assert proof["automatic_install_performed"] is False
    assert proof["game_installation_modified"] is False
    assert not (project/"BepInEx").exists()
    assert not (project/"Patches").exists()
    assert sha256(game_source.read_bytes()).hexdigest()==checksum
    record=json.loads(Path(proof["report"]).read_text("utf8"))
    assert record["compiled_managed_dll_sha256"]==proof["compiled_managed_dll_sha256"]
    assert "noesis" in proof["referenced_game_assembly_hashes"]


def test_native_compiler_refuses_reuse_and_modified_generated_source(project):
    _available()
    _campaign(project)
    native.compile_menu_candidate(project,"native-campaign",REAL_GAME)
    with pytest.raises(work.WorkshopError,match="already exists"):
        native.compile_menu_candidate(project,"native-campaign",REAL_GAME)
    source=project.parent/".origins-runtime-candidates"/"native-campaign"/"OriginsCampaignData.g.cs"
    source.write_bytes(source.read_bytes()+b"\n// modified by owner")
    with pytest.raises(work.WorkshopError,match="changed"):
        native.compile_menu_candidate(project,"native-campaign",REAL_GAME)


def test_missing_or_unrelated_game_fails_before_candidate_publication(project,tmp_path):
    _campaign(project)
    with pytest.raises(ValueError,match="game directory"):
        native.compile_menu_candidate(project,"native-campaign",tmp_path/"does-not-exist")
    assert not (project.parent/".origins-native-menu-candidates").exists()


def test_campaign_draft_has_real_named_selected_mission_control(project):
    folder=_campaign(project)
    patch=(folder/"FrontendMenus.draft.xaml").read_bytes()
    assert b'Name="SpriteSuiteSelectedMission"' in patch
    assert b'Name="SpriteSuiteOriginsMission1"' in patch
    assert b'CommandParameter="LegacyStart"' in patch


def test_real_game_metadata_probe_reports_structure_but_not_gameplay_attestation(project):
    _available()
    output=project.parent/"native-metadata-reader-output"
    proof=abi.probe_installed_game(REAL_GAME,output)
    assert all(proof["structural_signatures"].values()),proof["missing_signatures"]
    assert proof["csharp_metadata_probe_compiled"] is True
    assert proof["game_abi_fully_attested"] is False
    assert proof["native_game_command_handler_registered"] is False
    assert proof["game_installation_modified"] is False


@pytest.mark.skipif(os.name!="nt",reason="Tk native menu on Windows")
def test_runtime_workshop_compiles_selected_native_candidate_in_private_folder(project,monkeypatch):
    _available()
    _campaign(project)
    from suite_tcl_runtime import create_tk_root
    root=create_tk_root();root.withdraw()
    view=None
    try:
        view=workshop.OriginsRuntimeWorkshop(root,project=project)
        view.saved_campaign_slug="native-campaign"
        monkeypatch.setattr(workshop.filedialog,"askdirectory",lambda **_kw:str(REAL_GAME))
        result=view.compile_native_menu()
        assert result is not None
        assert Path(result["dll"]).is_file()
        assert "KEINE Installation" in view.status.get()
    finally:
        if view is not None:view.destroy()
        root.destroy()

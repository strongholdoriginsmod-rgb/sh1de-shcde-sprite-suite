"""Compile and actually execute managed Origins authoring logic offline."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

from PIL import Image
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"tools"))

import origins_runtime_compiler as compiler
import origins_runtime_authoring as author
import hud_menu_workspace as work


@pytest.fixture
def private_project(tmp_path,monkeypatch):
    suite=tmp_path/"suite"
    (suite/"work").mkdir(parents=True)
    monkeypatch.setattr(work,"ROOT",suite)
    monkeypatch.setattr(work,"WORK",suite/"work")
    project=suite/"work"/"my-origins"
    return project


def _check_native_compiler():
    if os.name!="nt" or not any(p.is_file() for p in compiler.CS_COMPILERS):
        pytest.skip("A Windows .NET Framework C# compiler is not available")


def test_windows_csharp_campaign_data_builds_and_runs_as_real_managed_library(
    private_project,
):
    _check_native_compiler()
    project=private_project
    plan={
        "name":"my-legacy-campaign","title":"A New Legacy",
        "missions":[
            {"number":1,"title":"Mission 1","map":"Antioch.map","act":"Act 1"},
            {"number":2,"title":"Mission 2","map":"Demo.map","act":"Act 1"},
        ],
    }
    drafted=author.write_campaign_draft(project,plan)
    candidate=Path(drafted["output"])
    raw=(candidate/"OriginsCampaignData.g.cs").read_bytes()
    assert raw==author.campaign_csharp_source(plan)
    assert b"namespace SpriteSuite.Origins.Authoring" in raw
    result=compiler.compile_offline(
        project=project,candidate=candidate,kind="campaign")
    dll=candidate/"OriginsAuthoredCore.dll"
    assert dll.is_file() and dll.read_bytes().startswith(b"MZ")
    assert result["offline_runtime_data_selftest_passed"]
    assert result["compiled_dll_sha256"]==compiler._digest(dll.read_bytes())
    assert result["game_plugin_compiled"] is False
    assert result["ingame_menu_commands_connected"] is False
    assert not (project/"Patches").exists()
    with pytest.raises(work.WorkshopError,match="already exists"):
        compiler.compile_offline(project=project,candidate=candidate,kind="campaign")


def test_season_generated_routes_compile_and_revert_on_map_unload(
    private_project,tmp_path,
):
    _check_native_compiler()
    project=private_project
    project.mkdir()
    group=project/"atlas-sources"/"tree_pine"
    group.mkdir(parents=True)
    Image.new("RGBA",(16,16),(10,20,30,255)).save(group/"atlas.png")
    (group/"atlas.json").write_text(json.dumps({"frames":[]}),encoding="utf8")
    original=(group/"atlas.png").read_bytes()
    drafted=author.write_season_draft(
        project,pack_id="winterpack",groups={"tree_pine":group},
        map_routes=["Antioch.map","Demo.map"])
    candidate=Path(drafted["output"])
    data=(candidate/"OriginsSeasonData.g.cs").read_bytes()
    assert data==author.season_csharp_source("winterpack",["Antioch.map","Demo.map"])
    result=compiler.compile_offline(
        project=project,candidate=candidate,kind="season")
    assert (candidate/"OriginsAuthoredCore.dll").is_file()
    assert result["offline_runtime_data_selftest_passed"]
    assert result["native_game_dll_loaded"] is False
    assert result["public_mod_release_approved"] is False
    assert (group/"atlas.png").read_bytes()==original
    assert not (project/"Seasons").exists()


def test_changed_csharp_data_never_compiles_or_replaces_existing_artifacts(
    private_project,
):
    project=private_project
    drafted=author.write_campaign_draft(project,{
       "name":"campaign-check",
       "title":"Campaign",
       "missions":[{"number":1,"title":"One","map":"Antioch.map","act":""}],
    })
    candidate=Path(drafted["output"])
    data=candidate/"OriginsCampaignData.g.cs"
    data.write_bytes(data.read_bytes()+b"\n// poisoned by external edit")
    with pytest.raises(work.WorkshopError,match="changed"):
        compiler.compile_offline(
            project=project,candidate=candidate,kind="campaign")
    assert not (candidate/"OriginsAuthoredCore.dll").exists()
    assert not (candidate/"offline-compile-evidence.json").exists()


def test_game_install_directory_never_accepted_as_compiler_candidate(
    private_project,tmp_path,
):
    external=tmp_path/"games"/"StrongholdCrusader"
    external.mkdir(parents=True)
    with pytest.raises(work.WorkshopError,match="private Origins candidate"):
        compiler.compile_offline(
            project=private_project,candidate=external,kind="campaign")
    assert not list(external.iterdir())


def test_duplicate_or_unsafe_season_routes_rejected_before_publication():
    with pytest.raises(work.WorkshopError):
        author.season_csharp_source("winterpack",["Antioch.map","antioch.map"])
    with pytest.raises(work.WorkshopError):
        author.season_csharp_source("winterpack",["../evil.map"])
    with pytest.raises(work.WorkshopError):
        author.season_csharp_source("winterpack",[])


def test_combined_campaign_and_season_runtime_qa_uses_generated_verified_sources(
    private_project,
):
    _check_native_compiler()
    from origins_runtime_offline_qa import run_offline_qa
    project=private_project
    campaign={
       "name":"simulated-campaign","title":"My Combined Origins Campaign",
       "missions":[
           {"number":1,"title":"First","map":"Antioch.map","act":"Part A"},
           {"number":2,"title":"Second","map":"Demo.map","act":"Part A"},
       ],
    }
    author.write_campaign_draft(project,campaign)
    group=project/"atlas-sources"/"tree_pine"
    group.mkdir(parents=True)
    Image.new("RGBA",(16,16),(40,70,80,255)).save(group/"atlas.png")
    (group/"atlas.json").write_text(
        json.dumps({"schema":1,"frames":[]}),encoding="utf8")
    author.write_season_draft(
        project,pack_id="winter2026",
        groups={"tree_pine":group},
        map_routes=["Antioch.map"])
    result=run_offline_qa(project,"simulated-campaign","winter2026")
    assert result["managed_core_and_authored_data_compiled"] is True
    assert result["offline_behavior_tests_passed"] is True
    assert result["mission_count"]==2
    assert result["season_pack_id"]=="winter2026"
    assert result["native_game_handler_present"] is False
    assert result["steam_game_modified"] is False
    evidence=Path(result["output"])/"qa-report.json"
    assert json.loads(evidence.read_text("utf8"))==result
    assert not (project/"Patches").exists()
    assert not (project/"Seasons").exists()

"""Execute the unchanged REAL C# menu adapter with an isolated fake UI host."""
from __future__ import annotations
from pathlib import Path
import json
import os
import sys
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/"tools"),str(ROOT/"src")]
import hud_menu_workspace as work
import origins_runtime_authoring as author
import origins_menu_mock_qa as mock
from origins_native_menu_compiler import compile_menu_candidate,CSC

GAME=Path(r"D:\Games\Stronghold Crusader Definitive Edition")


@pytest.fixture
def workspace(tmp_path,monkeypatch):
    root=tmp_path/"suite";(root/"work").mkdir(parents=True)
    monkeypatch.setattr(work,"ROOT",root)
    monkeypatch.setattr(work,"WORK",root/"work")
    return root/"work"/"native-menu-mock-test"


def prepare(project,n):
    plan={"name":"mock-campaign","title":"Test Campaign",
          "missions":[{"number":i,"title":"Test "+str(i),
                       "map":"Test "+str(i)+".map","act":"Part One"}
                      for i in range(1,n+1)]}
    result=author.write_campaign_draft(project,plan)
    return Path(result["output"])


@pytest.mark.parametrize("missions",[1,2,5])
def test_actual_game_bridge_executes_all_mock_menu_behaviors(workspace,missions):
    if os.name!="nt" or not CSC.is_file():
        pytest.skip("Windows C# compiler missing")
    source=prepare(workspace,missions)
    authored=source/"OriginsCampaignData.g.cs"
    prior=authored.read_bytes()
    proof=mock.run_menu_mock_qa(workspace,"mock-campaign")
    assert proof["behavior_assertions_executed"]>=29
    assert proof["harmony_mock_patch_calls"]==1
    assert proof["harmony_mock_unpatch_calls"]==1
    assert proof["real_menu_bridge_csharp_compiled"] is True
    assert proof["mock_host_executable_executed"] is True
    assert proof["native_game_hook_registered"] is False
    assert proof["game_binaries_loaded"] is False
    assert authored.read_bytes()==prior
    assert Path(proof["exe"]).is_file()
    assert "SPRITESUITE_MOCK_MENU_ASSERTIONS=29" in Path(proof["log"]).read_text("utf8")
    assert json.loads(Path(proof["report"]).read_text("utf8"))["game_installation_modified"] is False
    assert not list(workspace.rglob("BepInEx"))
    with pytest.raises(work.WorkshopError,match="already exists"):
        mock.run_menu_mock_qa(workspace,"mock-campaign")


def test_faulty_adapter_mock_source_does_not_produce_success(workspace,tmp_path,monkeypatch):
    if os.name!="nt" or not CSC.is_file():
        pytest.skip("Windows C# compiler missing")
    prepare(workspace,2)
    invalid=tmp_path/"broken_mock_host.cs"
    invalid.write_text("THIS IS NOT VALID C# CODE",encoding="utf8")
    monkeypatch.setattr(mock,"HARNESS",invalid)
    with pytest.raises(work.WorkshopError,match="failed"):
        mock.run_menu_mock_qa(workspace,"mock-campaign")
    assert not (workspace.parent/".origins-menu-behavior-qa"/"mock-campaign").exists()


def test_native_candidate_requires_successful_mock_behavior_not_just_metadata(
    workspace,monkeypatch
):
    if os.name!="nt" or not CSC.is_file() or not GAME.is_dir():
        pytest.skip("Installed game and Windows C# compiler are required")
    prepare(workspace,2)
    proof=compile_menu_candidate(workspace,"mock-campaign",GAME)
    assert proof["compiled_candidate_metadata_attested"]
    assert proof["offline_fake_game_host_executed"]
    assert proof["offline_fake_host_assertions"]>=29
    assert proof["mock_game_commands_preserved"]
    output=Path(proof["output"])
    assert (output/"menu-mock-behavior.log").is_file()
    assert (output/"menu-mock-report.json").is_file()
    assert not (output/"MenuBehaviorMock.exe").exists()
    assert not (output/"Mono.Cecil.dll").exists()
    assert proof["native_game_hook_registered"] is False
    assert proof["map_launch_implemented"] is False


def test_broken_mock_test_fails_native_candidate_without_publishing(
    workspace,tmp_path,monkeypatch
):
    if os.name!="nt" or not CSC.is_file() or not GAME.is_dir():
        pytest.skip("Installed game and Windows compiler required")
    prepare(workspace,1)
    damaged=tmp_path/"broken.cs"
    damaged.write_text("not even valid C#!",encoding="utf8")
    monkeypatch.setattr(mock,"HARNESS",damaged)
    with pytest.raises(work.WorkshopError,match="failed"):
        compile_menu_candidate(workspace,"mock-campaign",GAME)
    assert not (workspace.parent/".origins-native-menu-candidates"/"mock-campaign").exists()

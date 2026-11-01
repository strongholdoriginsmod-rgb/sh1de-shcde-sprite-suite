"""End-to-end offline C# build tests for authored Origins campaigns/seasons."""
from __future__ import annotations

from pathlib import Path
import json
import sys

from PIL import Image
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import hud_menu_workspace as work
import origins_runtime_authoring as author
import origins_runtime_offline_qa as qa


@pytest.fixture
def project(tmp_path, monkeypatch):
    suite = tmp_path / "suite"
    (suite / "work").mkdir(parents=True)
    monkeypatch.setattr(work, "ROOT", suite)
    monkeypatch.setattr(work, "WORK", suite / "work")
    return suite / "work" / "my-origins-project"


def campaign():
    return {"name": "test-kampagne", "title": 'Test "Origins" & C#',
            "missions": [
                {"number": n, "title": 'Mission "Nr. ' + str(n) + '"',
                 "map": "Stage " + str(n) + ".map", "act": "Akt A"}
                for n in (1, 2, 3)]}


def test_generated_campaign_compiles_and_behaves_without_loading_game(project):
    author.write_campaign_draft(project, campaign())
    plan, code = qa.verify_campaign(project, "test-kampagne")
    assert len(plan["missions"]) == 3
    assert b'Mission \\"Nr. 1\\"' in code
    if not qa.COMPILER.is_file():
        pytest.skip("Windows .NET 4 compiler not available here")
    report = qa.run_offline_qa(project, "test-kampagne")
    folder = Path(report["output"])
    assert report["managed_core_and_authored_data_compiled"] is True
    assert report["offline_behavior_tests_passed"] is True
    assert report["steam_build_abi_attested"] is False
    assert report["installable_mod_produced"] is False
    assert report["steam_game_modified"] is False
    assert "ORIGINS_AUTHORED_QA_ASSERTIONS=7" in (
        folder / "behavior.log").read_text("utf8")
    assert not (project / "Patches").exists()
    assert not (project / "Override").exists()


def test_edited_candidate_csharp_is_not_compiled(project):
    saved = author.write_campaign_draft(project, campaign())
    source = Path(saved["output"]) / "OriginsCampaignData.g.cs"
    source.write_bytes(source.read_bytes() + b"\n// changed")
    with pytest.raises(work.WorkshopError, match="changed"):
        qa.run_offline_qa(project, "test-kampagne")
    assert not (project.parent / ".origins-offline-qa").exists()


def test_edited_campaign_metadata_and_xaml_blocked(project):
    saved = author.write_campaign_draft(project, campaign())
    folder = Path(saved["output"])
    xaml = folder / "FrontendMenus.draft.xaml"
    xaml.write_bytes(xaml.read_bytes().replace(b"LegacyBack", b"OtherAction"))
    with pytest.raises(work.WorkshopError, match="changed"):
        qa.verify_campaign(project, "test-kampagne")
    assert not (project.parent / ".origins-offline-qa").exists()


def test_season_atlas_and_map_compiled_together_with_campaign(project):
    author.write_campaign_draft(project, campaign())
    source = project / "my-atlas" / "tree_pine"
    source.mkdir(parents=True)
    Image.new("RGBA", (16, 16), "white").save(source / "atlas.png")
    (source / "atlas.json").write_text('{"schema": 1, "frames": []}', "utf8")
    season = author.write_season_draft(project, pack_id="test-winter",
        groups={"tree_pine": source}, map_routes=["Stage 1.map"])
    maps, code = qa.verify_season(project, "test-winter")
    assert maps == ["Stage 1.map"]
    assert b"new SeasonRoute" in code
    if not qa.COMPILER.is_file():
        pytest.skip("Windows .NET 4 compiler not available here")
    report = qa.run_offline_qa(project, "test-kampagne", "test-winter")
    assert report["season_pack_id"] == "test-winter"
    assert report["offline_behavior_tests_passed"] is True
    assert "ORIGINS_AUTHORED_QA_ASSERTIONS=9" in (
        Path(report["output"]) / "behavior.log").read_text("utf8")
    copied_atlas = Path(season["output"]) / "tree_pine" / "atlas.json"
    copied_atlas.write_text('{"schema":2}', "utf8")
    with pytest.raises(work.WorkshopError, match="provenance"):
        qa.verify_season(project, "test-winter")


def test_unapproved_and_nonexistent_candidates_rejected(project):
    project.mkdir()
    with pytest.raises(work.WorkshopError, match="Unsafe campaign"):
        qa.run_offline_qa(project, "../bad")
    with pytest.raises(work.WorkshopError, match="Missing"):
        qa.run_offline_qa(project, "missing-campaign")

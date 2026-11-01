"""Manual Origins Campaign/Season authoring produces honest private drafts."""
from __future__ import annotations
from pathlib import Path
import json
import sys

from PIL import Image
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"tools"))
import origins_runtime_authoring as origins
import hud_menu_workspace as work
from se_asset_package import _check_xml


@pytest.fixture
def project(tmp_path,monkeypatch):
    suite=tmp_path/"suite"
    (suite/"work").mkdir(parents=True)
    monkeypatch.setattr(work,"ROOT",suite)
    monkeypatch.setattr(work,"WORK",suite/"work")
    return suite/"work"/"my-private-origins"


def make_campaign(missions=3):
    return {
       "name":"winter-reich",
       "title":"Meine Origins Kampagne",
       "missions":[
          {"number":i,"title":"Mission "+str(i),"map":"Map "+str(i)+".map",
           "act":"Akt 1"} for i in range(1,missions+1)],
    }


def test_campaign_21_missions_and_noninstallable_xaml_draft(project):
    data=make_campaign(21)
    saved=origins.write_campaign_draft(project,data)
    folder=Path(saved["output"])
    assert folder.is_dir()
    plan=json.loads((folder/"campaign-plan.json").read_text("utf8"))
    assert len(plan["missions"])==21
    assert plan["profile_progress_schema"]["unlocked_mission"]==1
    assert plan["handler_contract"]["new_route_parameters"][-1]=="LegacyBack"
    draft=folder/"FrontendMenus.draft.xaml"
    assert _check_xml(draft,patch=True) is None
    assert b"LegacyM21" in draft.read_bytes()
    assert b'Name="SpriteSuiteOriginsStart"' in draft.read_bytes()
    assert b'CommandParameter="LegacyStart"' in draft.read_bytes()
    assert b'CommandParameter="LegacyBack"' in draft.read_bytes()
    assert b'Visibility="Collapsed"' in draft.read_bytes()
    assert saved["legacy_campaign_handlers_compiled"] is False
    assert saved["installable_mod_produced"] is False
    assert not list(project.glob("Patches/**/*"))
    assert not list(project.glob("Override/**/*"))
    with pytest.raises(work.WorkshopError,match="already exists"):
        origins.write_campaign_draft(project,data)


@pytest.mark.parametrize("tamper",[
    {"name":"../../escape"},
    {"title":""},
    {"missions":[]},
    {"missions":[{"number":0,"title":"Wrong","map":"a.map","act":"a"}]},
    {"missions":[{"number":1,"title":"Wrong","map":"../a.map","act":"a"}]},
    {"missions":[{"number":2,"title":"Wrong","map":"a.map","act":"a"}]},
    {"missions":[{"number":1,"title":"A","map":"a.map","act":"a"},
                 {"number":1,"title":"B","map":"b.map","act":"a"}]},
])
def test_invalid_campaign_never_creates_draft(project,tamper):
    data=make_campaign(2)
    data.update(tamper)
    with pytest.raises(work.WorkshopError):
        origins.write_campaign_draft(project,data)
    assert not (project.parent/".origins-runtime-candidates").exists()


def test_season_pack_manifest_validates_atlas_and_gm_identity(project):
    project.mkdir()
    own=project/"custom-season"/"tree_pine"
    own.mkdir(parents=True)
    Image.new("RGBA",(16,16),(255,255,255,255)).save(own/"atlas.png")
    (own/"atlas.json").write_text(
        json.dumps({"schema":1,"frames":[]}),encoding="utf8")
    prev=(own/"atlas.png").read_bytes()
    output=origins.write_season_draft(project,pack_id="meine-weihnacht",
                                    groups={"tree_pine":own},
                                    map_routes=["Antioch.map"])
    package=Path(output["output"])
    assert package.is_dir()
    info=json.loads((package/"pack.json").read_text("utf8"))
    assert info["groups"]==[{"gm":"tree_pine","gmId":30,"tag":"vegetation"}]
    assert (package/"tree_pine"/"atlas.png").read_bytes()==prev
    assert output["runtime_needs_map_load_save_state_handlers"] is True
    assert output["seasonpack_loader_binary_attested"] is False
    assert not (project/"Seasons").exists()
    with pytest.raises(work.WorkshopError,match="Existing"):
        origins.write_season_draft(project,pack_id="meine-weihnacht",
                                  groups={"tree_pine":own})


def test_unsafe_season_group_never_writes(project,tmp_path):
    project.mkdir()
    fake=tmp_path/"incomplete"
    fake.mkdir()
    (fake/"atlas.json").write_text("{}")
    with pytest.raises(work.WorkshopError,match="real atlas"):
        origins.write_season_draft(project,pack_id="winter-test",
                                  groups={"tree_pine":fake})
    with pytest.raises(work.WorkshopError,match="historical GM"):
        origins.write_season_draft(project,pack_id="winter-test",
                                  groups={"evil_engine":fake})
    assert not (project.parent/".origins-runtime-candidates"/"season-winter-test").exists()

"""Synthetic tests: no game install, media, network, Unity or private DLLs."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from stronghold_europe_de.modding_studio.catalog import (
    MODULES, API_RELEASE, NATIVE_BASELINE_SHA256,
    search, minimum_api, version_tuple,
)
from stronghold_europe_de.modding_studio.design import (
    simulate_mission, _analyze_xaml,
)
from stronghold_europe_de.modding_studio.engine import analyze, analyze_suite_ui
from stronghold_europe_de.modding_studio.exporter import (
    export_project, mission_data_lua,
)
from stronghold_europe_de.modding_studio.model import (
    SCHEMA, project_template, validate_project, new_project,
    load_project, next_revision,
)
from stronghold_europe_de.modding_studio.safety import (
    StudioError, create_file, create_json, json_bytes, read_json,
    file_sha, read_file, child_path, relative_path,
)


@pytest.fixture()
def area(tmp_path: Path) -> tuple[Path, dict]:
    root = tmp_path / "studio"
    root.mkdir()
    return root, project_template("test_studio", "Offline Test")


def _codes(module: dict) -> set[str]:
    return {finding["code"] for finding in module["findings"]}


def test_all_twelve_modules_have_strict_project_structure(area):
    root, project = area
    assert len(MODULES) == 12
    assert set(project["modules"]) == {name for name, _, _ in MODULES}
    assert project["schema"] == SCHEMA
    assert project["target"]["mode"] == "offline"
    assert project["target"]["native_sha256"] == NATIVE_BASELINE_SHA256
    assert validate_project(project) == project
    result = analyze(root, project)
    assert result["status"] == "SOURCE_PASS"
    assert len(result["modules"]) == 12
    assert all(value["release_status"] == "never_in_game_verified"
               for value in result["modules"].values())


def test_json_duplicate_keys_and_traversal_fail_closed(area):
    root, _ = area
    create_file(root, "bad.json", b'{"x":1,"x":2}')
    with pytest.raises(StudioError, match="duplicate JSON key"):
        read_json(root, "bad.json")
    for relative in ("../escape", "/absolute", "C:/drive", "a//b",
                     "a/../b", r"a\b", "a/./b"):
        with pytest.raises(StudioError):
            relative_path(relative)
    with pytest.raises(StudioError):
        child_path(root, "../escape")


def test_no_clobber_atomic_publication(area):
    root, _ = area
    file = create_file(root, "sub/generated.json", b"first")
    assert file.read_bytes() == b"first"
    with pytest.raises(StudioError, match="overwrite"):
        create_file(root, "sub/generated.json", b"other")
    assert file.read_bytes() == b"first"


def test_project_source_revisions_preserve_original(tmp_path: Path):
    directory = tmp_path / "demo"
    source = new_project(directory, "demo_test", "My Mod")
    original, digest = load_project(directory)
    revised = deepcopy(original)
    revised["title"] = "My New Mod"
    revised["revision"] += 1
    new = next_revision(directory, original, revised, digest)
    assert new.is_file()
    assert source.read_bytes() == json_bytes(original)
    later, later_sha = load_project(directory, new.relative_to(directory).as_posix())
    assert later["revision"] == 2
    assert later_sha == sha256(new.read_bytes()).hexdigest()
    with pytest.raises(StudioError, match="revision"):
        next_revision(directory, original, original, digest)
    with pytest.raises(StudioError, match="changed"):
        next_revision(directory, original, revised, "a" * 64)


def test_project_structure_validated_and_older_targets_remain_editable(area):
    _, project = area
    changed = deepcopy(project)
    changed["future"] = {}
    with pytest.raises(StudioError, match="exactly"):
        validate_project(changed)
    changed = deepcopy(project)
    changed["target"]["mode"] = "deploy"
    with pytest.raises(StudioError, match="offline"):
        validate_project(changed)
    changed = deepcopy(project)
    changed["target"]["script_extender"] = "1.44.0"
    assert validate_project(changed) == changed
    report = analyze(area[0], changed)
    assert report["status"] == "REVIEW"
    assert "SCRIPT_EXTENDER_VERSION_DIFFERS" in _codes(report["modules"]["sdk"])
    changed = deepcopy(project)
    changed["modules"]["hud"]["new_magic"] = True
    with pytest.raises(StudioError, match="exactly"):
        validate_project(changed)


def test_catalog_has_documented_capabilities_and_versions():
    assert API_RELEASE == "0.27.0"
    assert search("route", module="units")
    assert search("sound", module="audio")
    assert search("versioned", module="saves")
    assert not search("definitely_nonexistent_feature")
    assert version_tuple("2.14.0") > version_tuple("1.44.0")
    assert minimum_api(["ui_deferred", "mapper_camera"]) == "0.27.0"
    with pytest.raises(StudioError):
        minimum_api(["not_real"])
    with pytest.raises(StudioError):
        version_tuple("v1.2.3")


def test_sdk_minimum_is_diagnostic_and_source_export_stays_available(area):
    _, project = area
    project["modules"]["sdk"]["requires"] = ["mapper_camera", "versioned_save"]
    assert validate_project(project)["project_id"] == "test_studio"
    project["target"]["api_shared"] = "0.26.0"
    assert validate_project(project) == project
    report = analyze(area[0], project)
    assert report["status"] == "REVIEW"
    assert {"API_RELEASE_DIFFERS", "API_VERSION_TOO_OLD"} <= _codes(report["modules"]["sdk"])
    destination, manifest = export_project(area[0], project, "older_target")
    assert destination.is_dir()
    assert manifest["status"] == "REVIEW"


def test_mission_trigger_plan_and_native_tick_dry_run(area):
    root, project = area
    project["modules"]["mission"]["triggers"] = [
        {
            "id": "first_tick", "event": "tick_at",
            "when": {"tick": 10}, "once": True,
            "actions": [{"kind": "message", "text": "Start"}],
        },
        {
            "id": "gold_earned", "event": "resources_at_least",
            "when": {"player": 1, "good": "gold", "amount": 100},
            "once": True,
            "actions": [{"kind": "objective", "text": "Gold", "state": "complete"}],
        },
    ]
    report = analyze(root, project)
    assert report["status"] == "REVIEW"
    assert "MISSION_RUNTIME_NOT_CONNECTED" in _codes(report["modules"]["mission"])
    simulation = simulate_mission(
        project["modules"]["mission"],
        [
            {"event": "mission_start", "tick": 0},
            {"event": "simulation_tick", "tick": 9},
            {"event": "simulation_tick", "tick": 10},
            {"event": "simulation_tick", "tick": 15},
            {"event": "resource_snapshot", "tick": 20,
             "player": 1, "good": "gold", "amount": 101},
        ],
    )
    assert simulation["fired"] == 2
    assert [row["tick"] for row in simulation["trace"]] == [10, 20]
    assert simulation["status"] == "offline_simulation_only"
    lua = mission_data_lua(project).decode("utf8")
    assert "return {" in lua and "first_tick" in lua
    assert "hooks are registered" in lua
    with pytest.raises(StudioError, match="ordered"):
        simulate_mission(
            project["modules"]["mission"],
            [{"tick": 12}, {"tick": 11}],
        )


@pytest.mark.parametrize("bad", ("event", "missing_cue", "unknown_key", "bad_player"))
def test_mission_unsupported_actions_block_export(area, bad):
    root, project = area
    trigger = {
        "id": "trigger", "event": "mission_start",
        "when": {}, "once": True,
        "actions": [{"kind": "message", "text": "Hi"}],
    }
    if bad == "event":
        trigger["event"] = "secret_native_detour"
    if bad == "missing_cue":
        trigger["actions"] = [{"kind": "cue", "cue_id": "not_present"}]
    if bad == "unknown_key":
        trigger["actions"] = [{"kind": "message", "text": "Hi", "exec": "run"}]
    if bad == "bad_player":
        trigger["actions"] = [
            {"kind": "spawn", "player": 99, "unit": "archer",
             "count": 1, "x": 0, "y": 0}
        ]
    project["modules"]["mission"]["triggers"] = [trigger]
    assert analyze(root, project)["status"] == "BLOCKED"
    with pytest.raises(StudioError):
        export_project(root, project, "bad_export")


def test_castle_rotation_footprint_and_collision(area):
    root, project = area
    project["modules"]["castle"]["buildings"] = [
        {"id": "keep", "kind": "keep", "x": 2, "y": 3, "width": 2, "height": 4,
         "rotation": 90, "step": 0},
    ]
    result = analyze(root, project)["modules"]["castle"]
    assert result["facts"]["elements"][0]["width"] == 4
    assert result["facts"]["elements"][0]["height"] == 2
    assert result["facts"]["occupied_tiles"] == 8
    assert result["status"] == "REVIEW"
    project["modules"]["castle"]["buildings"].append(
        {"id": "wall", "kind": "wall", "x": 3, "y": 4,
         "width": 2, "height": 1, "rotation": 0, "step": 1}
    )
    issues = _codes(analyze(root, project)["modules"]["castle"])
    assert "CASTLE_OVERLAP" in issues
    project["modules"]["castle"]["buildings"][1]["x"] = 99
    assert "INVALID_ENTRY" in _codes(analyze(root, project)["modules"]["castle"])


def test_xaml_patch_namespace_normalization_and_unsafe_image(area):
    root, project = area
    xaml = (
        '<Patch><Operation><BitmapImage x:Key="wall" '
        'UriSource="../Images/sede-wall-stone-low.png"/></Operation></Patch>'
    )
    create_file(root, "hud/menu.xaml", xaml.encode("utf8"))
    project["modules"]["hud"]["xaml_files"] = ["hud/menu.xaml"]
    project["modules"]["hud"]["expected_images"] = [
        "Assets/GUI/Images/sede-wall-stone-low.png",
        "Assets/GUI/Images/sede-wall-spikes.png",
    ]
    h = analyze(root, project)["modules"]["hud"]
    assert h["facts"]["referenced_count"] == 1
    assert len(h["facts"]["unreferenced_expected"]) == 1
    assert h["status"] == "REVIEW"
    with pytest.raises(StudioError, match="unsafe"):
        _analyze_xaml(
            '<Patch><BitmapImage x:Key="w" UriSource="../Images/../../evil.png"/></Patch>',
            "injection",
        )


def test_suite_ui_audit_keeps_all_14_even_if_four_unreferenced():
    findings = analyze_suite_ui(REPO)
    assert findings["source_count"] == 128
    assert findings["wall_source_count"] == 14
    assert findings["wall_referenced_count"] == 10
    assert set(findings["missing_wall_refs"]) == {
        "Assets/GUI/Images/sede-wall-palisade-battlements.png",
        "Assets/GUI/Images/sede-wall-palisade-battlements-hover.png",
        "Assets/GUI/Images/sede-wall-stone-spikes.png",
        "Assets/GUI/Images/sede-wall-stone-spikes-hover.png",
    }


def test_balance_rounded_integer_costs_preview_only(area):
    root, project = area
    project["modules"]["balance"]["cost_rules"] = [
        {
            "id": "archer_price", "category": "unit", "subject": "archer",
            "base": {"gold": 13, "wood": 1},
            "numerator": 3, "denominator": 2,
        },
    ]
    result = analyze(root, project)["modules"]["balance"]
    assert result["facts"]["cost_previews"][0]["projected_costs"] == {
        "gold": 20, "wood": 2,
    }
    assert result["status"] == "REVIEW"


def test_offline_export_all_twelve_and_no_overwrite(area):
    root, project = area
    path, index = export_project(root, project, "export_one")
    assert len(index["files"]) >= 22
    assert (path / "index.html").read_text(encoding="utf8").startswith("<!doctype html>")
    assert (path / "castle/layout.svg").is_file()
    assert "BepInDependency" in (path / "plugin/Plugin.cs").read_text(encoding="utf8")
    assert "APIShared_Serp" in (path / "plugin/info.json").read_text(encoding="utf8")
    assert list(path.rglob("*.dll")) == []
    assert index["in_game_compatibility"] == "not_established"
    for item in index["files"]:
        blob = (path / item["path"]).read_bytes()
        assert sha256(blob).hexdigest() == item["sha256"]
    with pytest.raises(StudioError, match="overwrite"):
        export_project(root, project, "export_one")


def test_saved_current_revision_reopens_by_exact_path_and_hash(tmp_path):
    from stronghold_europe_de.modding_studio.model import load_current_project
    directory = tmp_path / "revision-pointer"
    new_project(directory, "pointer_studio", "Original")
    original, digest = load_project(directory)
    revised = deepcopy(original)
    revised["title"] = "Saved revision title"
    revised["revision"] = 2
    saved = next_revision(directory, original, revised, digest)
    loaded, actual, source = load_current_project(directory)
    assert loaded == revised
    assert source == saved.relative_to(directory).as_posix()
    assert actual == sha256(saved.read_bytes()).hexdigest()
    assert load_project(directory)[0]["title"] == "Original"
    # An interrupted pointer write can be retried against the immutable bytes.
    assert next_revision(directory, original, revised, digest) == saved


@pytest.mark.parametrize("source,expected", [
    ("../project.json", "a" * 64),
    ("project.json", "a" * 64),
    ("exports/arbitrary.json", "a" * 64),
])
def test_saved_current_revision_rejects_unsafe_path_or_wrong_hash(tmp_path, source, expected):
    from stronghold_europe_de.modding_studio.model import load_current_project
    directory = tmp_path / "bad-pointer"
    new_project(directory, "pointer_studio", "Original")
    (directory / "current.json").write_text(json.dumps({
        "schema":"spritesuite.studio-current.v1", "source":source, "sha256":expected
    }), encoding="utf-8")
    with pytest.raises(StudioError):
        load_current_project(directory)

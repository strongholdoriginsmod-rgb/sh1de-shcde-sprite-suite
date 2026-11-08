"""Offline engine rules, Save/MP fingerprints, native hook spans and CLI guards."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from stronghold_europe_de.modding_studio.cli import main
from stronghold_europe_de.modding_studio.catalog import NATIVE_BASELINE_SHA256
from stronghold_europe_de.modding_studio.engine import analyze
from stronghold_europe_de.modding_studio.integrations import run_helper
from stronghold_europe_de.modding_studio.model import project_template
from stronghold_europe_de.modding_studio.safety import (
    StudioError, create_file, json_bytes,
)


@pytest.fixture
def area(tmp_path: Path) -> tuple[Path, dict]:
    root = tmp_path / "studio"
    root.mkdir()
    return root, project_template("runtime_studio", "Simulation")


def codes(result, module):
    return {row["code"] for row in result["modules"][module]["findings"]}


def test_route_finds_lowest_weighted_grid_path(area):
    root, p = area
    p["modules"]["units"]["grid"] = {
        "width": 5, "height": 3,
        "blocked": [[2, 1]],
        "penalties": [{"x": 1, "y": 1, "cost": 255}],
    }
    p["modules"]["units"]["routes"] = [{
        "id": "route_one", "player": 1,
        "start": [0, 1], "goal": [4, 1],
    }]
    details = analyze(root, p)["modules"]["units"]["facts"]["routes"][0]
    assert details["state"] == "FOUND"
    assert details["path"][0] == [0, 1] and details["path"][-1] == [4, 1]
    assert [1, 1] not in details["path"]
    assert [2, 1] not in details["path"]
    assert details["cost"] == 6
    assert details["visited"] > 0


def test_route_endpoint_and_penalty_conflict_fail_closed(area):
    root, p = area
    p["modules"]["units"]["grid"] = {
        "width": 4, "height": 4, "blocked": [[0, 0]], "penalties": [],
    }
    p["modules"]["units"]["routes"] = [{
        "id": "route_one", "player": 1, "start": [0, 0], "goal": [2, 2],
    }]
    report = analyze(root, p)
    assert "OFFLINE_ROUTE_ENDPOINT_BLOCKED" in codes(report, "units")
    p["modules"]["units"]["grid"]["penalties"].append(
        {"x": 0, "y": 0, "cost": 20}
    )
    assert "ROUTE_PENALTY_INVALID" in codes(analyze(root, p), "units")


def test_save_deterministic_hash_and_peer_mismatch(area):
    root, p = area
    record = {
        "id": "castle_state",
        "version": 2, "minimum_reader": 1,
        "known_entries": ["gold"],
        "values": {"gold": 123, "future_value": {"foo": [1, 2]}},
        "simulation_relevant": True,
    }
    p["modules"]["saves"]["records"] = [record]
    digest = sha256(json_bytes({
        "version": record["version"], "values": record["values"],
    })).hexdigest()
    p["modules"]["saves"]["peers"] = [
        {"player": 1, "record_id": "castle_state", "sha256": digest}
    ]
    result = analyze(root, p)
    assert "UNKNOWN_SAVE_ENTRY_PRESERVED" in codes(result, "saves")
    assert result["modules"]["saves"]["facts"]["peers"][0]["matches"]
    p["modules"]["saves"]["peers"].append({
        "player": 2, "record_id": "castle_state", "sha256": "a" * 64,
    })
    assert "MULTIPLAYER_STATE_MISMATCH" in codes(analyze(root, p), "saves")


def test_native_requires_exact_hash_and_rejects_overlap(area):
    root, p = area
    sites = [
        {
            "id": "entry_one", "rva": 100, "span": 12,
            "owner": "feature_a", "confidence": "confirmed",
            "image_sha256": NATIVE_BASELINE_SHA256,
        },
        {
            "id": "entry_two", "rva": 108, "span": 8,
            "owner": "feature_b", "confidence": "probable",
            "image_sha256": NATIVE_BASELINE_SHA256,
        },
    ]
    p["modules"]["native"]["sites"] = sites
    result = analyze(root, p)
    assert "NATIVE_HOOK_OVERLAP" in codes(result, "native")
    sites[1]["rva"] = 200
    assert "NATIVE_SITE_UNCERTAIN" in codes(analyze(root, p), "native")
    sites[0]["image_sha256"] = "b" * 64
    assert "NATIVE_SITE_INVALID" in codes(analyze(root, p), "native")


def test_helper_does_not_execute_unverified_binary(area):
    root, _ = area
    create_file(root, "maps/scene.map", b"synthetic-game-map-placeholder")
    fake_exe = root / "unverified.exe"
    fake_exe.write_bytes(b"not-a-program")
    with pytest.raises(StudioError, match="executable SHA-256"):
        run_helper(
            root, "mapparser", "info", "maps/scene.map",
            sha256(b"synthetic-game-map-placeholder").hexdigest(),
            fake_exe, "a" * 64,
        )
    with pytest.raises(StudioError, match="source SHA-256"):
        run_helper(
            root, "mapparser", "info", "maps/scene.map",
            "a" * 64, fake_exe, sha256(fake_exe.read_bytes()).hexdigest(),
        )


def test_helper_rejects_writer_without_explicit_new_output(area):
    root, _ = area
    create_file(root, "aiv/a.aivjson", b'{"frames":[]}')
    executable = root / "fake.exe"
    executable.write_bytes(b"dummy")
    with pytest.raises(StudioError, match="explicit output ID"):
        run_helper(
            root, "aivparser", "inspect", "aiv/a.aivjson",
            sha256(b'{"frames":[]}').hexdigest(),
            executable, sha256(b"dummy").hexdigest(),
        )


def test_cli_catalog_and_main_source_audit(capsys):
    assert main(["modules"]) == 0
    assert "12." in capsys.readouterr().out
    assert main(["catalog", "--query", "route", "--module", "units"]) == 0
    assert "RouteTileRules" in capsys.readouterr().out
    assert main(["audit-suite-ui", "--suite-root", str(REPO)]) == 0
    output = capsys.readouterr().out
    assert "wall 14" in output
    assert "explicit XAML refs 10" in output


def test_cli_export_requires_no_previous_output(area, capsys):
    root, p = area
    from stronghold_europe_de.modding_studio.safety import create_json
    create_json(root, "project.json", p)
    assert main(["check", str(root)]) == 0
    assert main(["export", str(root), "--export-id", "export_one"]) == 0
    assert main(["export", str(root), "--export-id", "export_one"]) == 2
    assert "overwrite" in capsys.readouterr().err


@pytest.mark.parametrize(
    "scenario",
    [
        {"units": {"route_grid": {"width": 1000}}},
        {"saves": {"record-version": 0}},
    ],
)
def test_source_model_does_not_silently_accept_unknown_sections(area, scenario):
    from stronghold_europe_de.modding_studio.model import validate_project
    _, p = area
    key, unknown = next(iter(scenario.items()))
    p["modules"][key].update(unknown)
    with pytest.raises(StudioError):
        validate_project(p)


def test_native_baseline_search_has_provenance_and_bounded_jsonl(tmp_path: Path):
    from stronghold_europe_de.modding_studio.knowledge import (
        SERP_KNOWLEDGE, search_native_baseline,
    )
    root = tmp_path / "baseline"
    root.mkdir()
    create_file(
        root, "CURRENT.md",
        ("Current canonical DLL SHA-256: " + NATIVE_BASELINE_SHA256).encode(),
    )
    for i, relative in enumerate(SERP_KNOWLEDGE):
        create_file(
            root, relative,
            (json.dumps({"id": "claim_a", "name": "market_price", "site": i})
             + "\n").encode("utf-8"),
        )
    result = search_native_baseline(root, "market_price", 5)
    assert len(result["matches"]) == 3
    assert all(item["record"].find("market_price") >= 0 for item in result["matches"])
    assert result["in_game_compatibility"] == "not_established"
    (root / "CURRENT.md").write_text("wrong baseline")
    with pytest.raises(StudioError, match="different native image"):
        search_native_baseline(root, "market_price")


def test_api_source_surface_search_is_read_only(tmp_path: Path):
    from stronghold_europe_de.modding_studio.knowledge import search_api_surface
    root = tmp_path / "APIShared"
    root.mkdir()
    create_file(
        root, "tests/ApiBaseline/PublicApi.txt",
        b"APIShared.Demo\nAPIShared.SimulationTickEvents\n",
    )
    result = search_api_surface(root, "SimulationTick")
    assert result["total_matches"] == 1
    assert result["matches"][0]["line"] == 2
    assert result["source_status"] == "local_source_copy_not_compiled_binary_attestation"


def test_installed_native_dll_attestation_is_not_hook_approval(tmp_path: Path):
    from stronghold_europe_de.modding_studio.knowledge import attest_native_image
    path = tmp_path / "CrusaderDE.dll"
    path.write_bytes(b"synthetic-no-game-binary")
    result = attest_native_image(path)
    assert not result["matches_published_baseline"]
    assert not result["hooks_installed"]
    assert result["in_game_compatibility"] == "not_established"

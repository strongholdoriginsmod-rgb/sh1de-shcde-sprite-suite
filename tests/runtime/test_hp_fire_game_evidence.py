"""Ordered evidence contract for the QA-only real-game canary."""
from __future__ import annotations

import base64
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import qa_hp_fire_game_evidence as evidence

SAVE_SHA = "a" * 64
RUN = "hp-fire-" + "1" * 32
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a2ioAAAAASUVORK5CYII="
)


def synthetic_log(root: Path) -> str:
    directory = root / RUN
    directory.mkdir()
    lines = []

    def qa(event, phase, **fields):
        lines.append(evidence.HEALTH_PREFIX + "|".join(
            f"{key}={value}" for key, value in dict(event=event, phase=phase, **fields).items()))

    def runtime(event, **fields):
        lines.append(evidence.RUNTIME_PREFIX + "|".join(
            f"{key}={value}" for key, value in dict(event=event, **fields).items()))

    qa("started", "Ready", save_sha256=SAVE_SHA, evidence=RUN, mode="in_memory_api_values")
    for phase, hp, burning, stage, image in evidence.PHASES:
        building_id = 77
        global_id = 700005 if phase.startswith("New") else 661027
        if phase in ("Baseline", "ReloadBaseline", "Cleanup"):
            qa("load_requested", phase, save_sha256=SAVE_SHA)
            if phase == "ReloadBaseline":
                runtime("map_reset", reason="new_map_loaded", tracked=64, restored=64)
            qa("save_post", phase, save_sha256=SAVE_SHA)
        if phase == "NewBaseline":
            qa("removed", "Removed", building_id=77, global_id=661027, tile_owner=0)
            qa("create_requested", phase, previous_id=77, previous_global_id=661027)
        fire_ticks = 1500 if burning else 0
        if stage != "original" and phase != "Extinguished":
            runtime("stage_applied", building_id=building_id, global_id=global_id,
                    x=315, y=133, stage=stage.split(":")[1],
                    sprite_field_written="true", renderer_modified="false",
                    preview="False", live_hp=hp, live_max=100, live_fire_ticks=fire_ticks)
            runtime("stage_tilemap_verified", building_id=building_id,
                    global_id=global_id, x=315, y=133, stage=stage.split(":")[1],
                    tilemap_readback_matches="true", renderer_modified="true",
                    preview="False", live_hp=hp, live_max=100, live_fire_ticks=fire_ticks)
        qa("observed", phase, type=104, building_id=building_id, global_id=global_id,
           hp=hp, max=100, fire_ticks=fire_ticks, baseline_tiles=64,
           field_matches=64, rendered_matches=64, stage=stage)
        if image:
            qa("screenshot_requested", phase, file=f"{phase}.png", width=1, height=1)
            (directory / f"{phase}.png").write_bytes(PNG)
    qa("completed", "Cleanup", unchanged_save_sha256=SAVE_SHA)
    return "\n".join(lines)


def test_valid_sequence_checks_real_values_tilemap_and_screenshot_receipts(tmp_path):
    result = evidence.evaluate(synthetic_log(tmp_path), tmp_path, SAVE_SHA)
    assert result["canarySequenceProved"], result["errors"]
    assert len(result["screenshots"]) == 9
    assert result["screenshots"]["Extinguished"]["width"] == 1
    assert result["visualReviewPerformed"] is False


@pytest.mark.parametrize("before,after,reason", [
    ("preview=False", "preview=True", "non-preview"),
    ("rendered_matches=64", "rendered_matches=63", "renderer match"),
    ("global_id=700005", "global_id=661027", "rebuilt identities"),
    ("event=map_reset", "event=unrelated", "map-state reset"),
    ("unchanged_save_sha256=", "unverified_save_sha256=", "unchanged QA save"),
])
def test_partial_or_inconsistent_evidence_cannot_be_reported_as_proof(
        tmp_path, before, after, reason):
    log = synthetic_log(tmp_path).replace(before, after)
    result = evidence.evaluate(log, tmp_path, SAVE_SHA)
    assert not result["canarySequenceProved"]
    assert any(reason in error for error in result["errors"])


def test_truncated_screenshot_prevents_completed_proof(tmp_path):
    log = synthetic_log(tmp_path)
    (tmp_path / RUN / "Mechanical.png").write_bytes(PNG[:-1])
    result = evidence.evaluate(log, tmp_path, SAVE_SHA)
    assert not result["canarySequenceProved"]
    assert "Mechanical: Screenshot is not a complete PNG" in result["errors"]


def test_report_refuses_legacy_field_writes_without_native_tilemap_readback(tmp_path):
    log = synthetic_log(tmp_path)
    legacy = "\n".join(
        line for line in log.splitlines()
        if "event=stage_tilemap_verified" not in line
    ).replace("sprite_field_written=true|renderer_modified=false",
              "renderer_modified=true")
    result = evidence.evaluate(legacy, tmp_path, SAVE_SHA)
    assert not result["canarySequenceProved"]
    assert any("field write and native tilemap readback" in e for e in result["errors"])


@pytest.mark.parametrize("mutation", [
    "tilemap_readback_matches=false",
    "x=999",
    "renderer_modified=false",
])
def test_report_rejects_falsified_tilemap_readback_events(tmp_path, mutation):
    log = synthetic_log(tmp_path)
    lines = log.splitlines()
    target = next(i for i, line in enumerate(lines)
                  if "event=stage_tilemap_verified" in line)
    lines[target] = lines[target].replace(
        "tilemap_readback_matches=true", "tilemap_readback_matches=false"
    ) if mutation.endswith("false") and mutation.startswith("tilemap") else (
        lines[target].replace("x=315", "x=999")
        if mutation == "x=999" else
        lines[target].replace("renderer_modified=true", "renderer_modified=false")
    )
    result = evidence.evaluate("\n".join(lines), tmp_path, SAVE_SHA)
    assert not result["canarySequenceProved"]
    assert any("Mechanical: no matching non-preview field write and native tilemap readback" in e
               for e in result["errors"])



def test_readback_without_coordinates_cannot_confirm_the_field_write(tmp_path):
    log = synthetic_log(tmp_path).replace("|x=315|y=133", "")
    result = evidence.evaluate(log, tmp_path, SAVE_SHA)
    assert not result["canarySequenceProved"]
    assert any("field write and native tilemap readback" in e for e in result["errors"])

"""Offline regression for real per-tile SHCDE observations, no game needed."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from building_damage_render_evidence import correlate_events  # noqa: E402
from qa_building_damage_live import evaluate_log  # noqa: E402


def start() -> dict[str, str]:
    return {"event": "start", "status": "read_only"}


def graphic(tile_id="301", *, building="9", global_id="111", x="10", y="20"):
    return {"event": "tile_graphic", "building_id": building,
            "global_id": global_id, "type": "26", "tile_id": tile_id,
            "x": x, "y": y, "gm": "6", "image": "503",
            "sprite": "tile_buildings1 503", "renderer_modified": "false"}


def footprint(*, building="9", global_id="111", tiles="301:10,20;302:11,20"):
    return {"event": "building_footprint", "building_id": building,
            "global_id": global_id, "type": "26", "tiles": tiles}


def rendered(*, building="9", global_id="111", name="tile_buildings1 503",
             x="10", y="20", actual=None):
    if actual is None:
        actual = name
    return {"event": "building_render_tiles", "building_id": building,
            "global_id": global_id, "type": "26",
            "renderer_modified": "false",
            "samples": f"301:{x},{y}:{name}~64x64~100:{actual}~64x64~100;"
                       "302:11,20:none:none"}


def test_real_id_position_and_original_sprite_all_agree():
    report = correlate_events([start(), graphic(), footprint(), rendered()])
    assert report["renderTileEventCount"] == 1
    assert report["renderTileSampleCount"] == 2
    assert report["graphicFootprintIdentityCount"] == 1
    assert report["graphicFootprintSpatialTileCount"] == 1
    assert report["renderFootprintSpatialTileCount"] == 2
    assert report["renderGraphicSpriteTileCount"] == 1
    assert report["renderCombinedTileCount"] == 1
    assert report["renderCombinedBuildingCount"] == 1
    assert report["renderCombinedTilemapSpriteCount"] == 1
    assert report["readOnlyTilemapCandidateObserved"] is True
    assert report["visualReplacementVerified"] is False
    assert report["hpDamageSwitchVerified"] is False
    row = report["renderTileExamples"][0]
    assert row["tileId"] == "301"
    assert row["graphicImage"] == "503"
    assert row["tilemapSprite"].startswith("tile_buildings1 503")


def test_renderer_names_can_differ_without_suppressing_observation():
    report = correlate_events([start(), graphic(), footprint(),
                               rendered(actual="replacement_test_77")])
    assert report["renderCombinedTilemapSpriteCount"] == 1
    assert report["renderTilemapSpriteNameDisagreements"] == 1
    assert report["visualReplacementVerified"] is False


def test_distinct_buildings_and_incompatible_coordinates_do_not_correlate():
    mismatch = correlate_events([start(), graphic(), footprint(building="10"),
                                 rendered(x="100")])
    assert mismatch["graphicFootprintIdentityCount"] == 0
    assert mismatch["renderFootprintSpatialTileCount"] == 0
    assert mismatch["renderCombinedTileCount"] == 0
    assert mismatch["readOnlyTilemapCandidateObserved"] is False


def test_explicit_map_load_separates_reused_building_ids():
    events = [start(), graphic(),
              {"event": "qa_save_load", "status": "requested"},
              footprint(), rendered()]
    report = correlate_events(events)
    assert report["mapSegments"] == 2
    assert report["graphicFootprintIdentityCount"] == 0
    assert report["renderFootprintSpatialTileCount"] == 2
    assert report["renderGraphicSpriteTileCount"] == 0
    assert report["readOnlyTilemapCandidateObserved"] is False


def test_malformed_or_missing_tile_samples_are_ignored():
    e = rendered()
    e["samples"] = "bad entry;?:7,8:x:y;301:nan,20:abc:def;301:10,20:abc"
    report = correlate_events([start(), graphic(), footprint(), e])
    assert report["renderTileEventCount"] == 1
    assert report["renderTileSampleCount"] == 0
    assert report["readOnlyTilemapCandidateObserved"] is False


def test_qa_log_evaluation_preserves_original_report_and_stays_read_only(tmp_path):
    entries = [start(), graphic(), footprint(), rendered()]
    path = tmp_path / "LogOutput.log"
    original = "\n".join(
        "[Info] SHCDE_DAMAGE_QA|" + "|".join(f"{k}={v}" for k, v in e.items())
        for e in entries
    )
    path.write_text(original + "\n", encoding="utf-8")
    result = evaluate_log(path)
    assert result["readOnlyProbeStarted"] is True
    assert result["tileGraphicObservations"] == 1
    assert result["buildingFootprintObservations"] == 1
    assert result["correlatedTiles"] == 1
    assert result["readOnlyTilemapCandidateObserved"] is True
    assert result["liveGraphicMappingProved"] is False
    assert result["rendererReplacementProved"] is False
    assert result["inGameFullDamageSwitchingProved"] is False
    assert path.read_text(encoding="utf-8") == original + "\n"


def test_disabled_probe_never_reports_live_candidate(tmp_path):
    path = tmp_path / "LogOutput.log"
    entries = [start(), graphic(), footprint(), rendered(),
               {"event": "start", "status": "disabled"}]
    path.write_text("\n".join(
        "SHCDE_DAMAGE_QA|" + "|".join(f"{k}={v}" for k, v in e.items())
        for e in entries), encoding="utf-8")
    result = evaluate_log(path)
    assert result["renderCombinedTileCount"] == 1
    assert result["probeDisabled"] is True
    assert result["readOnlyTilemapCandidateObserved"] is False


def test_direct_tile_graphic_includes_actual_unity_tilemap_without_footprint():
    row = graphic()
    row["tilemap_sprite"] = "tile_buildings1 503~64x64~100"
    report = correlate_events([start(), row])
    assert report["directTilemapSpriteSamples"] == 1
    assert report["directTilemapOriginalSpriteNameMatches"] == 1
    assert report["directTilemapBuildingCount"] == 1
    assert report["graphicFootprintIdentityCount"] == 0
    assert report["readOnlyTilemapCandidateObserved"] is True
    assert "remain unproven" in report["renderEvidenceNote"]
    assert report["visualReplacementVerified"] is False


def test_direct_tilemap_can_differ_from_render_target_and_remains_diagnostic():
    row = graphic()
    row["tilemap_sprite"] = "other_asset~96x128~120"
    report = correlate_events([start(), row])
    assert report["directTilemapSpriteSamples"] == 1
    assert report["directTilemapSpriteNameDifferences"] == 1
    assert report["directTilemapOriginalSpriteNameMatches"] == 0
    assert report["hpDamageSwitchVerified"] is False


def test_null_tilemap_sprite_is_not_counted_as_renderer_evidence():
    row = graphic()
    row["tilemap_sprite"] = "none"
    report = correlate_events([start(), row])
    assert report["directTilemapSpriteSamples"] == 0
    assert report["readOnlyTilemapCandidateObserved"] is False

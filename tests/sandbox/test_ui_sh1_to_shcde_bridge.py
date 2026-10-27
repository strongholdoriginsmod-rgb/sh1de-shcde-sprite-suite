"""All test outputs stay in pytest tmp_path; no game, production or shared work writes."""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from hashlib import sha256
from pathlib import Path

import pytest
from PIL import Image

PROJECT = Path(__file__).resolve().parents[2]
QA = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT / "tools"))
sys.path.insert(0, str(PROJECT / "tests" / "sandbox"))
import ui_sh1_hud
from ui_sh1_hud import digest_file, pixel_digest
from suite_ui_atlas_preview import read_ui_preview_index
from test_sh1_hud_edit_roundtrip import make as source_fixture

import ui_sh1_to_shcde_bridge as bridge


def synthetic_target(tmp_path):
    target = tmp_path / "work" / "crusader"
    target.mkdir(parents=True)
    specs = [
        ("UI-TrailAtlas", [
            ("UI-HUD 007", (6, 5), (56, 23, 67, 255)),
            ("CrusaderOnly", (4, 4), (111, 222, 33, 255)),
        ]),
        ("UI-Colour1Atlas", [
            ("ROL-A001", (8, 8), (213, 50, 25, 140)),
        ]),
    ]
    atlases = []
    for sheet, keys in specs:
        folder = target / sheet
        folder.mkdir()
        crops = []
        for key, size, fill in keys:
            image = Image.new("RGBA", size, fill)
            path = folder / (key + ".png")
            image.save(path)
            crops.append({
                "key": key, "file": path.name,
                "x": 3, "y": 2, "width": size[0], "height": size[1],
                "baseline_pixels_sha256": pixel_digest(image),
            })
        atlases.append({
            "dictionary": sheet + ".xaml",
            "dictionary_sha256": "a" * 64,
            "sheet": sheet + ".png", "sheet_width": 32, "sheet_height": 32,
            "directory": sheet, "crops": crops,
        })
    (target / "index.json").write_text(json.dumps({
        "schema_version": 1, "target_build_id": "shcde-synthetic-test-only",
        "texture_asset_name": "globalgamemanagers.assets",
        "texture_asset_sha256": "b" * 64, "atlases": atlases,
    }), encoding="utf-8")
    return target


@pytest.fixture
def projects(tmp_path, monkeypatch):
    monkeypatch.setattr(bridge, "ROOT", tmp_path)
    monkeypatch.setattr(ui_sh1_hud, "ROOT", tmp_path)
    source = source_fixture(tmp_path)
    meta = json.loads((source / "sh1_hud_source.json").read_text("utf-8"))
    meta["source"] = "Stronghold 1 Definitive Edition"
    (source / "sh1_hud_source.json").write_text(json.dumps(meta), encoding="utf-8")
    target = synthetic_target(tmp_path)
    assert len(read_ui_preview_index(target)) == 3
    return source, target, tmp_path


def create_plan(projects):
    src, tgt, tmp_path = projects
    plan = tmp_path / "work" / "my-plan.json"
    document = bridge.create_plan(src, tgt)
    bridge._save_plan(plan, document)
    return plan, document


def test_plan_preserves_both_game_boundaries_and_requires_approval(projects):
    plan, obj = create_plan(projects)
    assert obj["coverage"]["matching_keys"] == 2
    assert obj["coverage"]["same_size"] == 1
    assert obj["coverage"]["different_size"] == 1
    assert obj["coverage"]["source_without_target_key"] == 1
    assert obj["coverage"]["target_without_source_key"] == 1
    assert obj["target_build_id"] == "shcde-synthetic-test-only"
    assert all(not row["approved"] for row in obj["mapping"])
    assert len(read_ui_preview_index(projects[1])) == 3


def test_apply_without_human_approval_fails_closed(projects):
    plan, _ = create_plan(projects)
    output = projects[2] / "work" / "not-created"
    with pytest.raises(bridge.BridgeError, match="Kein Element"):
        bridge.apply_plan(plan, output, allow_offline=True)
    assert not output.exists()


def test_no_silent_pixel_geometry_transfer(projects):
    plan, _ = create_plan(projects)
    with pytest.raises(bridge.BridgeError, match="Ungleiche Größen"):
        bridge.approve_mapping(plan, "ROL-A001", "ROL-A001", fit="exact",
                               state_note="Manueller Grafikzustand geprüft")
    data = bridge._read_json(plan)
    assert all(not item["approved"] for item in data["mapping"])


def test_approved_transfer_keeps_crusader_index_and_other_pixels(projects):
    source, target, tmp_path = projects
    plan, _ = create_plan(projects)
    src_key = "UI-HUD 007"
    bridge.approve_mapping(plan, src_key, src_key, fit="exact",
                           state_note="HUD Hintergrund manuell semantisch geprüft")
    original_index = (target / "index.json").read_bytes()
    untouched = {
        key: (target / atlas / (key + ".png")).read_bytes()
        for atlas, key in (
            ("UI-TrailAtlas", "CrusaderOnly"),
            ("UI-Colour1Atlas", "ROL-A001")
        )
    }
    out = tmp_path / "work" / "my-crossgame-candidate"
    result = bridge.apply_plan(plan, out, allow_offline=True)
    assert result["total_target_sprites"] == 3
    assert result["untouched_target_sprites"] == 2
    assert result["native_provenance"]["offline_only_not_release_approved"]
    assert (out / "index.json").read_bytes() == original_index
    assert (out / "UI-TrailAtlas" / (src_key + ".png")).read_bytes() != (
        target / "UI-TrailAtlas" / (src_key + ".png")).read_bytes()
    with Image.open(out / "UI-TrailAtlas" / (src_key + ".png")) as converted:
        with Image.open(source / "UI-MasterAtlas" / (src_key + ".png")) as original:
            assert converted.convert("RGBA").tobytes() == original.convert("RGBA").tobytes()
    for key, original_bytes in untouched.items():
        atlas = "UI-Colour1Atlas" if key == "ROL-A001" else "UI-TrailAtlas"
        assert (out / atlas / (key + ".png")).read_bytes() == original_bytes
    assert len(read_ui_preview_index(out)) == 3
    assert bridge.verify_candidate(out)["transferred_crops_further_edited"] == []
    with pytest.raises(bridge.BridgeError, match="bereits"):
        bridge.apply_plan(plan, out, allow_offline=True)


@pytest.mark.parametrize("fit", ["contain", "stretch"])
def test_explicit_size_policy_preserves_target_dimensions(projects, fit):
    source, target, tmp_path = projects
    plan, _ = create_plan(projects)
    bridge.approve_mapping(plan, "ROL-A001", "ROL-A001", fit=fit,
                           state_note="Größenabweichung und HUD-Zustand manuell überprüft")
    out = tmp_path / "work" / ("approved-" + fit)
    report = bridge.apply_plan(plan, out, allow_offline=True)
    path = out / "UI-Colour1Atlas" / "ROL-A001.png"
    assert len(report["approved_transfers"]) == 1
    with Image.open(path) as image:
        assert image.mode == "RGBA"
        assert image.size == (8, 8)
        if fit == "contain":
            assert image.getpixel((0, 0))[3] == 0 or image.getpixel((0, 7))[3] == 0
    assert (target / "UI-Colour1Atlas" / "ROL-A001.png").read_bytes() != path.read_bytes()


def test_manual_alias_is_possible_but_not_automatic(projects):
    src, target, tmp = projects
    plan, doc = create_plan(projects)
    assert all(row["target_key"] != "CrusaderOnly" for row in doc["mapping"])
    row = bridge.approve_mapping(
        plan, "Candle01", "CrusaderOnly", fit="contain",
        state_note="Crusader-Zielzustand absichtlich anders benannt; visuell geprüft",
    )
    assert row["explicit_alias"] is True
    out = tmp / "work" / "aliased-crusader"
    report = bridge.apply_plan(plan, out, allow_offline=True)
    assert report["approved_transfers"][0]["target_key"] == "CrusaderOnly"
    assert len(read_ui_preview_index(out)) == 3


def test_continue_editing_after_transfer_without_losing_other_crops(projects):
    src, tgt, tmp = projects
    plan, _ = create_plan(projects)
    bridge.approve_mapping(plan, "UI-HUD 007", "UI-HUD 007", fit="exact",
                           state_note="HUD-Hintergrund und Normalzustand geprüft")
    dest = tmp / "work" / "reedit"
    bridge.apply_plan(plan, dest, allow_offline=True)
    file = dest / "UI-TrailAtlas" / "UI-HUD 007.png"
    with Image.open(file) as source:
        edited = source.convert("RGBA")
    edited.putpixel((1, 2), (255, 0, 0, 10))
    edited.save(file)
    verified = bridge.verify_candidate(dest)
    assert verified["transferred_crops_further_edited"] == ["UI-HUD 007"]
    assert verified["target_geometry_unchanged"]
    assert len(read_ui_preview_index(dest)) == 3
    assert (tgt / "UI-TrailAtlas" / "UI-HUD 007.png").read_bytes() != file.read_bytes()


def test_unexpected_source_edit_after_plan_is_refused(projects):
    src, tgt, tmp = projects
    plan, _ = create_plan(projects)
    bridge.approve_mapping(plan, "UI-HUD 007", "UI-HUD 007", fit="exact",
                           state_note="SH1-HUD-Bild absichtlich übernommen")
    image = src / "UI-MasterAtlas" / "UI-HUD 007.png"
    with Image.open(image) as stream:
        changed = stream.convert("RGBA")
    changed.putpixel((0, 0), (12, 43, 91, 77))
    changed.save(image)
    dest = tmp / "work" / "must-remain-absent"
    with pytest.raises(bridge.BridgeError, match="Herkunft|Bearbeitungsstand"):
        bridge.apply_plan(plan, dest, allow_offline=True)
    assert not dest.exists()


def test_unexpected_target_edit_after_plan_is_refused(projects):
    src, tgt, tmp = projects
    plan, _ = create_plan(projects)
    bridge.approve_mapping(plan, "UI-HUD 007", "UI-HUD 007", fit="exact",
                           state_note="SH1 und SHCDE Bildbedeutung bestätigt")
    image = tgt / "UI-TrailAtlas" / "UI-HUD 007.png"
    Image.new("RGBA", (6, 5), (10, 90, 30, 255)).save(image)
    dest = tmp / "work" / "must-remain-absent"
    with pytest.raises(bridge.BridgeError, match="Herkunft|Bearbeitungsstand"):
        bridge.apply_plan(plan, dest, allow_offline=True)
    assert not dest.exists()


def test_release_requires_both_real_games_and_native_xaml(projects):
    plan, _ = create_plan(projects)
    bridge.approve_mapping(plan, "UI-HUD 007", "UI-HUD 007", fit="exact",
                           state_note="Geprüfte SH1- und SHCDE-HUD-Bedeutung")
    dest = projects[2] / "work" / "not-released"
    with pytest.raises(bridge.BridgeError, match="SH1-Asset"):
        bridge.apply_plan(plan, dest)
    assert not dest.exists()


@pytest.mark.parametrize("out", ["work", ".", "../evil"])
def test_rejects_unsafe_output_roots(projects, out):
    with pytest.raises(bridge.BridgeError):
        bridge.under_work(out)


def test_revoke_resets_approval(projects):
    plan, _ = create_plan(projects)
    bridge.approve_mapping(plan, "UI-HUD 007", "UI-HUD 007", fit="exact",
                           state_note="HUD-Zustand geprüft und bestätigt")
    bridge.revoke_mapping(plan, "UI-HUD 007")
    assert not bridge._read_json(plan)["mapping"][0]["approved"]

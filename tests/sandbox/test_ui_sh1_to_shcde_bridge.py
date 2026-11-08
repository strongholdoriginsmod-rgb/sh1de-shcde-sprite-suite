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


def test_plan_preserves_source_provenance_and_free_selection(projects):
    plan, obj = create_plan(projects)
    assert obj["coverage"]["matching_keys"] == 2
    assert obj["coverage"]["same_size"] == 1
    assert obj["coverage"]["different_size"] == 1
    assert obj["coverage"]["source_without_target_key"] == 1
    assert obj["coverage"]["target_without_source_key"] == 1
    assert obj["target_build_id"] == "shcde-synthetic-test-only"
    assert all(not row["selected"] for row in obj["mapping"])
    assert all("approved" not in row and "semantic_reviewed" not in row for row in obj["mapping"])
    assert len(read_ui_preview_index(projects[1])) == 3


def test_direct_multi_selection_transfers_without_approval_note_or_game(projects):
    plan, _ = create_plan(projects)
    output = projects[2] / "work" / "direct-multi-transfer"
    result = bridge.apply_plan(plan, output, target_keys=["UI-HUD 007", "ROL-A001"], fit="contain")
    assert len(result["transfers"]) == 2
    assert result["untouched_target_sprites"] == 1
    assert result["native_provenance"]["native_provenance_checked"] is False
    assert output.is_dir()


def test_no_silent_pixel_geometry_transfer(projects):
    plan, _ = create_plan(projects)
    with pytest.raises(bridge.BridgeError, match="Ungleiche Größen"):
        bridge.select_mapping(plan, "ROL-A001", "ROL-A001", fit="exact")
    data = bridge._read_json(plan)
    assert all(not item["selected"] for item in data["mapping"])


def test_selected_transfer_keeps_crusader_index_and_other_pixels(projects):
    source, target, tmp_path = projects
    plan, _ = create_plan(projects)
    src_key = "UI-HUD 007"
    bridge.select_mapping(plan, src_key, src_key, fit="exact")
    original_index = (target / "index.json").read_bytes()
    untouched = {
        key: (target / atlas / (key + ".png")).read_bytes()
        for atlas, key in (
            ("UI-TrailAtlas", "CrusaderOnly"),
            ("UI-Colour1Atlas", "ROL-A001")
        )
    }
    out = tmp_path / "work" / "my-crossgame-candidate"
    result = bridge.apply_plan(plan, out)
    assert result["total_target_sprites"] == 3
    assert result["untouched_target_sprites"] == 2
    assert not result["native_provenance"]["native_provenance_checked"]
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
        bridge.apply_plan(plan, out)


@pytest.mark.parametrize("fit", ["contain", "stretch"])
def test_explicit_size_policy_preserves_target_dimensions(projects, fit):
    source, target, tmp_path = projects
    plan, _ = create_plan(projects)
    bridge.select_mapping(plan, "ROL-A001", "ROL-A001", fit=fit)
    out = tmp_path / "work" / ("selected-" + fit)
    report = bridge.apply_plan(plan, out)
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
    row = bridge.select_mapping(plan, "Candle01", "CrusaderOnly", fit="contain")
    assert row["explicit_alias"] is True
    out = tmp / "work" / "aliased-crusader"
    report = bridge.apply_plan(plan, out)
    assert report["approved_transfers"][0]["target_key"] == "CrusaderOnly"
    assert len(read_ui_preview_index(out)) == 3


def test_continue_editing_after_transfer_without_losing_other_crops(projects):
    src, tgt, tmp = projects
    plan, _ = create_plan(projects)
    bridge.select_mapping(plan, "UI-HUD 007", "UI-HUD 007", fit="exact")
    dest = tmp / "work" / "reedit"
    bridge.apply_plan(plan, dest)
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
    bridge.select_mapping(plan, "UI-HUD 007", "UI-HUD 007", fit="exact")
    image = src / "UI-MasterAtlas" / "UI-HUD 007.png"
    with Image.open(image) as stream:
        changed = stream.convert("RGBA")
    changed.putpixel((0, 0), (12, 43, 91, 77))
    changed.save(image)
    dest = tmp / "work" / "must-remain-absent"
    with pytest.raises(bridge.BridgeError, match="Herkunft|Bearbeitungsstand"):
        bridge.apply_plan(plan, dest)
    assert not dest.exists()


def test_unexpected_target_edit_after_plan_is_refused(projects):
    src, tgt, tmp = projects
    plan, _ = create_plan(projects)
    bridge.select_mapping(plan, "UI-HUD 007", "UI-HUD 007", fit="exact")
    image = tgt / "UI-TrailAtlas" / "UI-HUD 007.png"
    Image.new("RGBA", (6, 5), (10, 90, 30, 255)).save(image)
    dest = tmp / "work" / "must-remain-absent"
    with pytest.raises(bridge.BridgeError, match="Herkunft|Bearbeitungsstand"):
        bridge.apply_plan(plan, dest)
    assert not dest.exists()


def test_native_provenance_checks_are_only_optional_and_require_complete_inputs(projects):
    plan, _ = create_plan(projects)
    bridge.select_mapping(plan, "UI-HUD 007", "UI-HUD 007", fit="exact")
    dest = projects[2] / "work" / "optional-native"
    with pytest.raises(bridge.BridgeError, match="optionale native Herkunftsprüfung"):
        bridge.apply_plan(plan, dest, source_game=Path("explicit-native-source.assets"))
    assert not dest.exists()
    assert bridge.apply_plan(plan, dest)["transfers"]


@pytest.mark.parametrize("out", ["work", ".", "../evil"])
def test_rejects_unsafe_output_roots(projects, out):
    with pytest.raises(bridge.BridgeError):
        bridge.under_work(out)


def test_revoke_removes_selection(projects):
    plan, _ = create_plan(projects)
    bridge.select_mapping(plan, "UI-HUD 007", "UI-HUD 007", fit="exact")
    bridge.revoke_mapping(plan, "UI-HUD 007")
    row = next(row for row in bridge._read_json(plan)["mapping"] if row["target_key"] == "UI-HUD 007")
    assert not row["selected"]


@pytest.mark.parametrize("note", ["", "x"])
def test_old_approve_spelling_has_no_note_or_semantic_gate(projects, note):
    plan, _ = create_plan(projects)
    row = bridge.approve_mapping(plan, "ROL-A001", "ROL-A001", fit="contain", state_note=note)
    assert row["selected"] and row["state_note"] == note
    assert bridge.apply_plan(plan, projects[2] / "work" / ("note-" + (note or "empty")))["transfers"]


def test_batch_selection_is_one_atomic_edit_and_can_remap_existing_target(projects):
    plan, _ = create_plan(projects)
    before = plan.read_bytes()
    with pytest.raises(bridge.BridgeError, match="Ungleiche Größen"):
        bridge.select_mappings(plan, [dict(source_key="UI-HUD 007", target_key="UI-HUD 007", fit="exact"),
                                    dict(source_key="ROL-A001", target_key="ROL-A001", fit="exact")])
    assert plan.read_bytes() == before
    rows = bridge.select_mappings(plan, [dict(source_key="Candle01", target_key="UI-HUD 007", fit="contain"),
                                        dict(source_key="ROL-A001", target_key="ROL-A001", fit="stretch")])
    assert [row["source_key"] for row in rows] == ["Candle01", "ROL-A001"]
    result = bridge.apply_plan(plan, projects[2] / "work" / "batch-remap")
    assert len(result["transfers"]) == 2


def test_legacy_approval_fields_do_not_block_direct_selection(projects):
    plan, obj = create_plan(projects)
    for row in obj["mapping"]:
        row.pop("selected")
        row.update(approved=False, semantic_reviewed=False, geometry_reviewed=False, explicit_alias=False)
    bridge._save_plan(plan, obj)
    result = bridge.apply_plan(plan, projects[2] / "work" / "legacy-free", target_keys=["ROL-A001"], fit="contain")
    assert len(result["transfers"]) == 1


def test_cli_direct_multi_transfer_requires_neither_approve_nor_offline_flag(projects, capsys):
    plan, _ = create_plan(projects)
    destination = projects[2] / "work" / "cli-direct"
    assert bridge.main(["apply", "--plan", str(plan), "--out", str(destination),
                        "--target-key", "UI-HUD 007", "--target-key", "ROL-A001", "--fit", "contain"]) == 0
    assert json.loads(capsys.readouterr().out)["transfers"] == 2


def test_nearest_fit_preserves_hidden_rgba_instead_of_alpha_blending():
    with Image.new("RGBA", (1, 1), (201, 39, 89, 0)) as source:
        for fit in ("exact", "contain", "stretch"):
            size = (1, 1) if fit == "exact" else (3, 2)
            with bridge._fit_image(source, size, fit) as fitted:
                assert fitted.getpixel((0, 0)) == (201, 39, 89, 0)


def test_cli_batch_select_has_optional_note_and_no_approval_steps(projects, capsys):
    plan, _ = create_plan(projects)
    assert bridge.main(["select", "--plan", str(plan), "--source-key", "UI-HUD 007", "--target-key", "UI-HUD 007",
                        "--source-key", "ROL-A001", "--target-key", "ROL-A001", "--fit", "contain"]) == 0
    selected = json.loads(capsys.readouterr().out)
    assert len(selected) == 2 and all(row["selected"] for row in selected)
    assert all(row["state_note"] == "" for row in selected)
    output = projects[2] / "work" / "cli-selected"
    assert bridge.main(["apply", "--plan", str(plan), "--out", str(output)]) == 0
    assert json.loads(capsys.readouterr().out)["transfers"] == 2


def test_normal_candidate_never_requests_native_game_checks(projects, monkeypatch):
    plan, _ = create_plan(projects)
    def forbidden(*_args):
        raise AssertionError("Normal image transfer must not inspect native game installations")
    monkeypatch.setattr(bridge, "_native_sh1_check", forbidden)
    monkeypatch.setattr(bridge, "_native_shcde_check", forbidden)
    output = projects[2] / "work" / "no-games-needed"
    report = bridge.apply_plan(plan, output, target_keys=["UI-HUD 007"])
    assert report["output_is_editable_crusader_export"]
    assert not report["native_provenance"]["native_provenance_checked"]


def test_only_current_multi_selection_is_transferred_not_prior_saved_choices(projects):
    plan, _ = create_plan(projects)
    bridge.select_mapping(plan, "UI-HUD 007", "UI-HUD 007")
    bridge.select_mappings(plan, [dict(source_key="ROL-A001", target_key="ROL-A001", fit="contain")])
    output = projects[2] / "work" / "selection-replaced"
    result = bridge.apply_plan(plan, output)
    assert [entry["target_key"] for entry in result["transfers"]] == ["ROL-A001"]


def test_output_appearing_during_transfer_is_preserved(projects, monkeypatch):
    plan, _ = create_plan(projects)
    destination = projects[2] / "work" / "user-created-output"
    read_index = bridge.read_ui_preview_index
    def inspect(folder):
        result = read_index(folder)
        if "-stage-" in Path(folder).name:
            destination.mkdir()
        return result
    monkeypatch.setattr(bridge, "read_ui_preview_index", inspect)
    with pytest.raises(bridge.BridgeError, match="inzwischen erstellt"):
        bridge.apply_plan(plan, destination, target_keys=["UI-HUD 007"])
    assert destination.is_dir() and list(destination.iterdir()) == []

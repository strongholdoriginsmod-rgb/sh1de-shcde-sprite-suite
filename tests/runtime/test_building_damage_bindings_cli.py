"""Editable mapping CLI accepts original-art grids independently of stage archives."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from zipfile import ZipFile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import building_damage_bindings as bindings


def source_log(tmp_path):
    path = tmp_path / "graphics.log"
    path.write_text(
        "SHCDE_DAMAGE_QA|event=tile_graphic|type=99999|global_id=8|"
        "x=10|y=20|gm=7|image=278|sprite=tile_buildings2 278|occupied_index=-1\n",
        encoding="utf-8",
    )
    return path


def test_explicit_grid_preserves_partial_mapping_with_own_game_type(tmp_path):
    log = source_log(tmp_path)
    output = tmp_path / "proposal.json"
    assert bindings.main([
        "--log", str(log), "--grid-a", "2", "--grid-b", "2",
        "--building-group", "custom.variant", "--building-type", "99999",
        "--output", str(output),
    ]) == 0
    result = json.loads(output.read_text("utf-8"))
    assert result["enabled"] is False
    assert len(result["bindings"]) == 1
    assert result["bindings"][0]["buildingType"] == 99999
    assert result["provenance"]["unresolvedOverhangOwnerOffsets"] == 1
    assert result["provenance"]["graphicsLogSHA256"] == hashlib.sha256(log.read_bytes()).hexdigest()


def test_archive_geometry_remains_supported_and_hash_mismatch_publishes_nothing(tmp_path):
    log = source_log(tmp_path)
    archive = tmp_path / "damage.zip"
    manifest = {"buildings": [{
        "id": "g", "stages": [{"settings": {"a": 1, "b": 1}}],
    }]}
    with ZipFile(archive, "w") as zipped:
        zipped.writestr("damage-manifest.json", json.dumps(manifest))
    output = tmp_path / "proposal.json"
    command = ["--log", str(log), "--archive", str(archive),
               "--building-group", "g", "--building-type", "99999", "--output", str(output)]
    with pytest.raises(SystemExit) as stopped:
        bindings.main([*command, "--expected-log-sha256", "0" * 64])
    assert stopped.value.code == 2
    assert not output.exists()
    assert bindings.main(command) == 0
    assert json.loads(output.read_text("utf-8"))["provenance"]["spriteGridSlots"] == 1

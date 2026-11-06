"""Real-asset-free tests for conservative read-only Noesis session evidence."""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import json
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import suite_live_noesis_log_audit as audit  # noqa: E402


def make_qa(tmp: Path) -> tuple[Path, Path, Path]:
    game = tmp / "qa-game"
    game.mkdir()
    (game / ".sprite-suite-qa-copy.marker").write_text("isolated test\n")
    mod = game / "BepInEx" / "plugins" / "testsuite"
    patch = mod / "Patches" / "Assets" / "GUI" / "XAML" / "HUD_Main.xaml"
    patch.parent.mkdir(parents=True)
    patch.write_text(
        '<Patch><Operation Type="Add" XPath="/Root" /></Patch>', encoding="utf-8"
    )
    (mod / "info.json").write_text(
        json.dumps({"GUID": "testsuite", "Manifest": 0}), encoding="utf-8"
    )
    log = game / "BepInEx" / "LogOutput.log"
    return game, patch, log


def test_noesis_log_audit_distinguishes_runtime_invocation_from_visual_proof():
    with TemporaryDirectory() as directory:
        game, patch, log = make_qa(Path(directory))
        log.write_text(
            "Indexed 1 files for [testsuite]\n"
            "Loading Asset Mod: [C:/qa/tests/testsuite]\n"
            "Found patch for [Assets/GUI/XAML/HUD_Main.xaml] in mod [testsuite]\n"
            "Applying 1 patch files to Assets/GUI/XAML/HUD_Main.xaml\n",
            encoding="utf-8"
        )
        result = audit.analyze(game_root=game, guid="testsuite", document="HUD_Main.xaml")
        assert result["runtime_patch_call_seen"] is True
        assert result["status"] == "patch_invoked_visual_unverified"
        assert result["native_rendered_pixels_attested"] is False
        assert result["native_game_abi_approved"] is False
        assert result["game_originals_modified"] is False
        assert result["installed_patch_sha256"] == audit.sha(patch)


def test_noesis_log_audit_does_not_confuse_indexing_with_patch_application():
    with TemporaryDirectory() as directory:
        game, _, log = make_qa(Path(directory))
        log.write_text(
            "Indexed 1 files for [testsuite]\n"
            "Loading Asset Mod: [C:/qa/tests/testsuite]\n",
            encoding="utf-8"
        )
        result = audit.analyze(game_root=game, guid="testsuite", document="HUD_Main.xaml")
        assert result["status"] == "registered_not_requested"
        assert result["runtime_patch_call_seen"] is False


def test_noesis_log_audit_rejects_unmarked_copy_and_xml_dtd():
    with TemporaryDirectory() as directory:
        game, patch, log = make_qa(Path(directory))
        log.write_text("nothing\n", encoding="utf-8")
        (game / ".sprite-suite-qa-copy.marker").unlink()
        with pytest.raises(ValueError, match="QA copy"):
            audit.analyze(game_root=game, guid="testsuite", document="HUD_Main.xaml")
        (game / ".sprite-suite-qa-copy.marker").write_text("QA")
        patch.write_text('<!DOCTYPE foo [<!ENTITY x "x">]><Patch />', encoding="utf-8")
        with pytest.raises(ValueError, match="entities|DTDs"):
            audit.analyze(game_root=game, guid="testsuite", document="HUD_Main.xaml")

"""HUD XAML diagnostic CLI must stay import-safe, bounded and read-only."""
from __future__ import annotations

import importlib
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import hud_buildings
import hud_tree

XML = """<Grid xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml">
    <Button x:Name="WheatFarm" HorizontalAlignment="Right" Margin="1,2,3,4"/>
    <Button Name="Granary" HorizontalAlignment="Left"/>
    <Border Name="Preview" />
    <TextBlock Text="{StaticResource UI-Buttons L123}" />
</Grid>"""


@pytest.fixture
def xaml(tmp_path):
    file = tmp_path / "HUD_Main.xaml"
    file.write_text(XML, encoding="utf8")
    return file


def test_both_modules_import_without_accessing_game_files(monkeypatch):
    # Before the fix, import itself crashed when the game XAML was absent.
    def forbidden(*a, **kw):
        raise AssertionError("Import unexpectedly read private game data")
    with monkeypatch.context() as patch:
        patch.setattr(Path, "read_text", forbidden)
        patch.setattr(Path, "read_bytes", forbidden)
        importlib.reload(hud_buildings)
        importlib.reload(hud_tree)


def test_both_diagnostics_detect_exact_original_element_names(xaml):
    original = xaml.read_bytes()
    text, tree = hud_buildings.read_xaml(xaml)
    buildings = hud_buildings.inspect_xaml(text,tree)
    assert {n[0] for n in buildings["named"]} >= {"WheatFarm","Granary","Preview"}
    assert buildings["banks"]["UI-Buttons"] == 1
    assert "WheatFarm" in hud_buildings.report(buildings,xaml)
    tree_data = hud_tree.inspect_xaml(text,tree)
    assert len(tree_data["right"]) == 1
    assert tree_data["right"][0]["name"] == "WheatFarm"
    assert "UI-Buttons L123" in tree_data["sprites"]
    assert "WheatFarm" in hud_tree.report(tree_data)
    assert xaml.read_bytes() == original


@pytest.mark.parametrize("data", [
    b"<!DOCTYPE Grid [ <!ENTITY ext 'bad'> ]><Grid>&ext;</Grid>",
    b"<Grid><Button>",
    b"Not an XML document",
])
def test_untrusted_xaml_is_refused(tmp_path,data):
    candidate = tmp_path / "input.xaml"
    candidate.write_bytes(data)
    with pytest.raises(ValueError):
        hud_buildings.read_xaml(candidate)
    assert candidate.read_bytes() == data


def test_huge_xaml_and_invalid_type_are_rejected_without_parsing(tmp_path):
    huge = tmp_path / "huge.xaml"
    huge.write_bytes(b"x" * (hud_buildings.MAX_XAML_BYTES + 1))
    with pytest.raises(ValueError, match="2 MiB"):
        hud_buildings.read_xaml(huge)
    wrong = tmp_path / "pretend.json"
    wrong.write_text("<Grid/>", encoding="utf8")
    with pytest.raises(ValueError):
        hud_buildings.read_xaml(wrong)


@pytest.mark.parametrize("module", ["hud_buildings.py","hud_tree.py"])
def test_cli_reads_explicit_file_and_exits_cleanly(xaml,module):
    before=xaml.read_bytes()
    result=subprocess.run([sys.executable,str(ROOT/"tools"/module),
                           "--xaml",str(xaml)],
                          cwd=ROOT,capture_output=True,
                          text=True,encoding="utf8",errors="replace",timeout=12)
    assert result.returncode == 0, result.stderr
    assert "WheatFarm" in result.stdout
    assert xaml.read_bytes() == before
    missing=subprocess.run([sys.executable,str(ROOT/"tools"/module),
                            "--xaml",str(xaml.with_name("missing.xaml"))],
                           cwd=ROOT,capture_output=True,
                           text=True,encoding="utf8",errors="replace",timeout=12)
    assert missing.returncode == 2
    assert "Traceback" not in missing.stderr
    assert "--xaml" in missing.stderr

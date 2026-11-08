"""A bounded inspection warning must not invalidate an authored large atlas."""
from pathlib import Path
from zipfile import ZipFile

import pytest

import hud_menu_workspace as hud
import se_asset_package as package
import suite_unified_project as flow
from suite_asset_inspector import MAX_XML, inspect_assets


def test_large_authored_dictionary_warns_without_claiming_parse_and_builds_exact_zip(tmp_path, monkeypatch):
    root = tmp_path / "suite"
    work = root / "work"
    project = work / "projects" / "large-atlas"
    folder = project / "Override/Assets/GUI/Sprites"
    folder.mkdir(parents=True)
    monkeypatch.setattr(hud, "ROOT", root)
    monkeypatch.setattr(hud, "WORK", work)
    monkeypatch.setattr(hud, "DEFAULT", project)
    monkeypatch.setattr(package, "ROOT", root)
    monkeypatch.setattr(package, "WORK", work)
    monkeypatch.setattr(package, "OUT", work / "se-asset-mods")
    xaml = folder / "UI-MasterAtlas.xaml"
    original = (b'<ResourceDictionary xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation">'
                b'<!--' + b' owned atlas description ' * (MAX_XML // 24 + 1) +
                b'--><BitmapImage UriSource="UI-MasterAtlas.png"/></ResourceDictionary>')
    assert len(original) > MAX_XML
    xaml.write_bytes(original)
    result = inspect_assets(project)
    assert result["summary"]["status"] == {"warning": 1}
    row = result["assets"][0]
    assert row["inspection"]["xml_parsed"] is False
    assert "Inspektionsbudget" in row["inspection"]["warning"]
    assert result["game_compatibility_verified"] is False
    # The normal unrestricted project archive preserves authored bytes. It
    # does not pretend the optional structural XML inspection has succeeded.
    built = flow.ProjectPipeline(project).build(guid="spritesuite.large-atlas", name="Large authored atlas")
    assert built["zip_verified_against_project"] is True
    assert built["installed_into_game"] is False
    with ZipFile(built["zip"]) as archive:
        assert archive.testzip() is None
        assert archive.read("BepInEx/plugins/spritesuite.large-atlas/Override/Assets/GUI/Sprites/UI-MasterAtlas.xaml") == original
    assert xaml.read_bytes() == original


@pytest.mark.parametrize("content", [b"<ResourceDictionary>", b'<!DOCTYPE a [<!ENTITY x "unsafe">]><a>&x;</a>'])
def test_small_invalid_or_entity_xml_still_reports_invalid(tmp_path, content):
    project = tmp_path / "assets"
    project.mkdir()
    (project / "bad.xaml").write_bytes(content)
    result = inspect_assets(project)
    assert result["summary"]["status"] == {"invalid": 1}
    assert "error" in result["assets"][0]["inspection"]

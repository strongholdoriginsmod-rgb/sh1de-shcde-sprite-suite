"""Preserve the distinction between skipped large PNGs and corrupt input."""
from hashlib import sha256

from PIL import Image
import pytest

import hud_menu_workspace as hud
import suite_unified_project as flow
from stronghold_europe_de.asset_inspector import AssetInspectionError, inspect_asset


def test_valid_png_above_budget_is_not_relabelled_as_corrupt(tmp_path, monkeypatch):
    work = tmp_path / "work"
    project = work / "project"
    folder = project / "Override/Assets/GUI/Sprites"
    folder.mkdir(parents=True)
    monkeypatch.setattr(hud, "WORK", work)
    monkeypatch.setattr(hud, "ROOT", tmp_path)
    png = folder / "large.png"
    # This is a complete valid PNG, not a fake oversized header. Its grayscale
    # source needs little fixture memory; the shared inspector rejects before
    # conversion to a full RGBA image.
    with Image.new("L", (4097, 4096), 42) as image:
        image.save(png)
    before = sha256(png.read_bytes()).hexdigest()
    with pytest.raises(AssetInspectionError, match="Pixelbudget"):
        inspect_asset(png)
    result = flow.ProjectPipeline(project).audit()
    assert result["assets"] == 1
    assert any("Pixelbudget" in warning for warning in result["warnings"])
    assert result["asset_inspections"] == []
    assert sha256(png.read_bytes()).hexdigest() == before


def test_small_corrupt_png_remains_a_blocking_project_error(tmp_path, monkeypatch):
    work = tmp_path / "work"
    project = work / "project"
    folder = project / "Override/Assets/GUI/Sprites"
    folder.mkdir(parents=True)
    monkeypatch.setattr(hud, "WORK", work)
    monkeypatch.setattr(hud, "ROOT", tmp_path)
    png = folder / "corrupt.png"
    with Image.new("RGBA", (4, 3), (10, 20, 30, 255)) as image:
        image.save(png)
    raw = png.read_bytes()
    png.write_bytes(raw[:raw.index(b"IDAT") + 7])
    with pytest.raises(AssetInspectionError, match="beschädigt"):
        inspect_asset(png)
    with pytest.raises(flow.UnifiedFlowError, match="beschädigt"):
        flow.ProjectPipeline(project).audit()

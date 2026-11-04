"""Fail closed on damaged local export metadata; keep existing ZIP files untouched."""
from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest
from PIL import Image

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/"tools"),str(ROOT/"src")]

import hud_menu_workspace as hud
import se_asset_package as assets
from suite_unified_project import ProjectPipeline,UnifiedFlowError,new_project,RECEIPT_SCHEMA


@pytest.fixture
def valid_export(tmp_path,monkeypatch):
    suite=tmp_path/"suite"
    work=suite/"work"
    work.mkdir(parents=True)
    monkeypatch.setattr(hud,"ROOT",suite)
    monkeypatch.setattr(hud,"WORK",work)
    monkeypatch.setattr(hud,"DEFAULT",work/"hud-menu-werkstatt")
    monkeypatch.setattr(assets,"ROOT",suite)
    monkeypatch.setattr(assets,"WORK",work)
    monkeypatch.setattr(assets,"OUT",work/"se-asset-mods")
    project=ProjectPipeline(new_project("receipt-check"))
    image=tmp_path/"asset.png"
    Image.new("RGBA",(32,16),(20,90,140,255)).save(image)
    project.import_image(image)
    proof=project.build(guid="spritesuite.receipt",name="Receipt Test")
    assert project.latest_export()["project_current"] is True
    return project,proof


@pytest.mark.parametrize("field,value",[
    ("receipt",None),
    ("receipt",[]),
    ("receipt",123),
    ("receipt",""),
])
def test_invalid_export_pointer_is_a_controlled_failure(
    valid_export,field,value,
):
    project,proof=valid_export
    pointer=project._last_export_file()
    record=json.loads(pointer.read_text("utf8"))
    record[field]=value
    pointer.write_text(json.dumps(record),encoding="utf8")
    with pytest.raises(UnifiedFlowError,match="Export|Beleg|verweis"):
        project.latest_export()
    assert Path(proof["zip"]).is_file()


@pytest.mark.parametrize("change",[
    "receipt-not-object",
    "zip-not-path",
    "assets-digest-missing",
    "verified-string",
])
def test_invalid_export_receipt_is_a_controlled_failure(valid_export,change):
    project,proof=valid_export
    receipt=Path(proof["receipt"])
    content=json.loads(receipt.read_text("utf8"))
    if change=="receipt-not-object":
        content=[]
    elif change=="zip-not-path":
        content["zip"]=[]
    elif change=="assets-digest-missing":
        content.pop("assets_sha256")
    elif change=="verified-string":
        content["zip_verified_against_project"]="yes"
    receipt.write_text(json.dumps(content),encoding="utf8")
    with pytest.raises(UnifiedFlowError,match="Export|Beleg|verweis"):
        project.latest_export()
    assert Path(proof["zip"]).is_file()

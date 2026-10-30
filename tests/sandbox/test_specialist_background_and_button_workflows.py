"""Headless, synthetic end-to-end tests for previously untested visual tools."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"tools"))

import background_v2_pipeline as backgrounds
import ui_button_catalogue as buttons


def pixels_sha(image: Image.Image) -> str:
    return hashlib.sha256(image.tobytes()).hexdigest()


def test_button_signatures_ignore_flat_color_but_preserve_shape():
    solid1=Image.new("RGBA",(20,20),(240,35,10,255))
    solid2=Image.new("RGBA",(20,20),(15,30,245,255))
    same=buttons.dist(buttons.signature(solid1),buttons.signature(solid2))
    assert same < 1e-8
    altered=solid2.copy()
    for x in range(5,15):
        altered.putpixel((x,10),(15,30,245,0))
    different=buttons.dist(buttons.signature(solid1),buttons.signature(altered))
    assert different > same
    assert pixels_sha(solid1)==pixels_sha(Image.new("RGBA",(20,20),(240,35,10,255)))


def test_button_catalogue_groups_only_adjacent_matching_family(mock_button_dirs):
    # The default catalogue contains no embedded game or user artwork.
    atlas,output=mock_button_dirs
    colors={"S001":(230,20,10,255),"S002":(20,20,230,255),
            "S004":(230,20,10,255),"S005":(70,70,70,255),
            "A001":(20,120,200,255)}
    for key,color in colors.items():
        shape=(20,20) if key!="S005" else (21,20)
        Image.new("RGBA",shape,color).save(atlas/("UI-Buttons "+key+".png"))
    # A non-UI button must not be included in the family matching.
    Image.new("RGBA",(20,20),(1,2,3,255)).save(atlas/"unrelated.png")
    assert buttons.main()==0
    catalogue=json.loads((output/"katalog.json").read_text("utf8"))
    members=[row["mitglieder"] for row in catalogue["familien"]]
    assert members==[["A001"],["S001","S002"],["S004"],["S005"]]
    with Image.open(output/"kontaktbogen_familien.png") as preview:
        assert preview.width==10*132
        assert preview.height>0
    before=(output/"katalog.json").read_bytes()
    assert buttons.main()==0
    assert (output/"katalog.json").read_bytes()==before


@pytest.fixture
def mock_button_dirs(tmp_path,monkeypatch):
    atlas=tmp_path/"fake-game"/"UI-MasterAtlas"
    output=tmp_path/"private-output"
    atlas.mkdir(parents=True)
    monkeypatch.setattr(buttons,"ATLAS",atlas)
    monkeypatch.setattr(buttons,"OUT",output)
    monkeypatch.setattr(buttons,"THRESHOLD",0.2)
    return atlas,output


def test_button_catalogue_bad_image_does_not_publish_partial_report(mock_button_dirs):
    atlas,output=mock_button_dirs
    Image.new("RGBA",(20,20),(255,255,255,255)).save(atlas/"UI-Buttons S001.png")
    (atlas/"UI-Buttons S002.png").write_bytes(b"corrupt PNG")
    with pytest.raises(OSError):
        buttons.main()
    assert not output.exists()


def test_background_mission_overlay_includes_first_flag_and_changed_pixels():
    base=Image.new("RGBA",(64,64),(85,90,85,255))
    for y in range(20,28):
        for x in range(20,28):
            base.putpixel((x,y),(190,20,20,255))
    changed=base.copy()
    for y in range(45,50):
        for x in range(45,50):
            changed.putpixel((x,y),(50,200,30,255))
    before=pixels_sha(base)
    first=backgrounds.mission_overlay_mask(base,base,first=True)
    later=backgrounds.mission_overlay_mask(base,changed,first=False)
    assert first.shape==(64,64)
    assert first.dtype==np.bool_
    assert first[23,23]
    assert later[46,46]
    assert later[23,23]
    assert pixels_sha(base)==before


def test_background_mission_dimension_mismatch_fails_closed():
    a=Image.new("RGBA",(64,64))
    b=Image.new("RGBA",(62,64))
    with pytest.raises(RuntimeError,match="dimensions differ"):
        backgrounds.mission_overlay_mask(a,b,first=False)


def test_skirmish_route_audit_outputs_all_13_files_when_detector_is_supplied(
    tmp_path,monkeypatch,
):
    source=tmp_path/"local-fake-skirmish-source"
    output=tmp_path/"local-skirmish-output"
    source.mkdir()
    for name in backgrounds.SKIRMISH_NAMES:
        Image.new("RGBA",(48,40),(220,200,185,255)).save(source/name)
    def minimal_detector(original):
        mask=np.zeros((original.height,original.width),dtype=bool)
        mask[10:20,10:25]=True
        return mask,mask
    monkeypatch.setattr(backgrounds,"skirmish_route_mask",minimal_detector)
    records=backgrounds.audit_skirmish(source,output)
    assert len(records)==len(backgrounds.SKIRMISH_NAMES)==13
    assert all(row["seed_pixels"]==150 and row["locked_pixels"]==150
               for row in records)
    for name in backgrounds.SKIRMISH_NAMES:
        stem=Path(name).stem
        with Image.open(output/(stem+"-route-lock.png")) as mask:
            assert mask.getpixel((15,15))==255
            assert mask.getpixel((1,1))==0
        with Image.open(output/(stem+"-route-overlay.jpg")) as image:
            assert image.size==(48,40)


def test_mission_audit_handles_all_49_synthetic_files_without_game_install(
    tmp_path,
):
    source=tmp_path/"mission-input"
    output=tmp_path/"mission-output"
    source.mkdir()
    for number in range(1,50):
        family=(number-1)//7
        rgba=Image.new("RGBA",(32,32),(60+family*5,70,80,255))
        for y in range(10,15):
            for x in range(10,15):
                rgba.putpixel((x,y),(210,20,20,255))
        if number % 7 == 2:
            rgba.putpixel((23,23),(255,255,255,255))
        rgba.save(source/f"HistoricalCampaign-Map-{number:02d}.png")
    records=backgrounds.audit_missions(source,output)
    assert len(records)==49
    assert {row["family"] for row in records}==set(range(1,8))
    with Image.open(output/"HistoricalCampaign-Map-01-overlay-lock.png") as mask:
        assert mask.getpixel((12,12))==255
    with Image.open(output/"HistoricalCampaign-Map-02-overlay-preview.jpg") as preview:
        assert preview.size==(32,32)
    assert len(tuple(output.glob("*-overlay-lock.png")))==49
    assert len(tuple(output.glob("*-overlay-preview.jpg")))==49


def test_mission_audit_missing_final_source_must_not_leave_partial_output(tmp_path):
    source=tmp_path/"mission-input"
    output=tmp_path/"mission-output"
    source.mkdir()
    for number in range(1,49):
        Image.new("RGBA",(16,16),(110,115,120,255)).save(
            source/f"HistoricalCampaign-Map-{number:02d}.png")
    with pytest.raises((FileNotFoundError,RuntimeError)):
        backgrounds.audit_missions(source,output)
    assert not output.exists(), "Preflight must validate every mission source before writing"


def test_skirmish_audit_missing_last_source_must_not_leave_partial_output(
    tmp_path,monkeypatch,
):
    source=tmp_path/"skirmish-input"
    output=tmp_path/"skirmish-output"
    source.mkdir()
    for filename in backgrounds.SKIRMISH_NAMES[:-1]:
        Image.new("RGBA",(48,40),(100,110,120,255)).save(source/filename)

    def deterministic_mask(original):
        mask=np.zeros((original.height,original.width),bool)
        mask[12:17,12:20]=True
        return mask,mask
    monkeypatch.setattr(backgrounds,"skirmish_route_mask",deterministic_mask)
    with pytest.raises((FileNotFoundError,RuntimeError)):
        backgrounds.audit_skirmish(source,output)
    assert not output.exists(), "Preflight must validate all skirmish originals first"


def test_preflight_rejects_corrupt_source_before_any_output(tmp_path):
    source=tmp_path/"invalid-sources"
    output=tmp_path/"output"
    source.mkdir()
    for number in range(1,50):
        path=source/f"HistoricalCampaign-Map-{number:02d}.png"
        if number==47:
            path.write_bytes(b"not a real PNG")
        else:
            Image.new("RGBA",(16,16),(100,100,100,255)).save(path)
    with pytest.raises((OSError,ValueError,RuntimeError)):
        backgrounds.audit_missions(source,output)
    assert not output.exists()

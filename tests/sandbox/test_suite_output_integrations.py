"""Late output failures cannot publish mixed atlas/catalogue generations."""
from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image
import numpy as np

import background_v2_pipeline as backgrounds
import ui_button_catalogue as buttons


def _state(folder):
    return {file.name:file.read_bytes() for file in folder.iterdir()
            if file.is_file()} if folder.exists() else {}


def test_catalogue_contact_sheet_failure_preserves_previous_outputs(
    tmp_path,monkeypatch,
):
    source=tmp_path/"source"
    source.mkdir()
    Image.new("RGBA",(32,32),(220,70,30,255)).save(
        source/"UI-Buttons S001.png")
    Image.new("RGBA",(32,32),(30,70,220,255)).save(
        source/"UI-Buttons S002.png")
    destination=tmp_path/"destination"
    destination.mkdir()
    (destination/"katalog.json").write_bytes(b"previous report")
    (destination/"kontaktbogen_familien.png").write_bytes(b"previous sheet")
    (destination/"custom.txt").write_bytes(b"foreign")
    before=_state(destination)
    monkeypatch.setattr(buttons,"ATLAS",source)
    monkeypatch.setattr(buttons,"OUT",destination)
    original=Image.Image.save

    def late_failure(image,path,*args,**kw):
        if Path(path).name=="kontaktbogen_familien.png":
            raise OSError("contact sheet write failed")
        return original(image,path,*args,**kw)

    monkeypatch.setattr(Image.Image,"save",late_failure)
    with pytest.raises(OSError,match="contact sheet"):
        buttons.main()
    assert _state(destination)==before


def test_mission_last_image_failure_preserves_previous_generation(
    tmp_path,monkeypatch,
):
    source=tmp_path/"originals"
    source.mkdir()
    for n in range(1,50):
        Image.new("RGBA",(28,28),(50,80,90,255)).save(
            source/f"HistoricalCampaign-Map-{n:02d}.png")
    target=tmp_path/"generated"
    target.mkdir()
    (target/"report.json").write_bytes(b"old provenance")
    (target/"HistoricalCampaign-Map-01-overlay-lock.png").write_bytes(b"old mask")
    (target/"custom-user-note.txt").write_bytes(b"protected")
    before=_state(target)
    original=backgrounds._overlay_preview

    def late_failure(image,mask,path,*args,**kw):
        if Path(path).name=="HistoricalCampaign-Map-49-overlay-preview.jpg":
            raise OSError("last preview failed")
        return original(image,mask,path,*args,**kw)

    monkeypatch.setattr(backgrounds,"_overlay_preview",late_failure)
    with pytest.raises(OSError,match="last preview"):
        backgrounds.audit_missions(source,target)
    assert _state(target)==before


def test_skirmish_failure_does_not_create_final_folder(tmp_path,monkeypatch):
    source=tmp_path/"originals"
    source.mkdir()
    for name in backgrounds.SKIRMISH_NAMES:
        Image.new("RGBA",(32,32),(150,100,75,255)).save(source/name)
    target=tmp_path/"new-output"
    def deterministic(image):
        mask=np.zeros((image.height,image.width),dtype=bool)
        mask[4:10,4:10]=True
        return mask,mask
    monkeypatch.setattr(backgrounds,"skirmish_route_mask",deterministic)
    original=backgrounds._overlay_preview
    def break_last(image,mask,path,*a,**kw):
        if Path(path).name=="SkirmishTrailMap3-route-overlay.jpg":
            raise OSError("last skirmish preview failed")
        return original(image,mask,path,*a,**kw)
    monkeypatch.setattr(backgrounds,"_overlay_preview",break_last)
    with pytest.raises(OSError,match="last skirmish"):
        backgrounds.audit_skirmish(source,target)
    assert not target.exists()

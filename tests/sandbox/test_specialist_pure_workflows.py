"""Real synthetic image workflows for specialist tools without private game data."""
from __future__ import annotations

from pathlib import Path
import sys

import pytest
from PIL import Image

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"tools"))

import ui_einpflegen as import_art
import ui_pair as pair
import vegetation_gen as vegetation


def small_art() -> Image.Image:
    result=Image.new("RGBA",(10,10),(0,0,0,0))
    for y in range(3,7):
        for x in range(2,6):
            result.putpixel((x,y),(210,40,80,255))
    return result


def test_generated_image_only_downscales_and_keeps_transparent_border():
    source=small_art()
    before=source.tobytes()
    output, details=import_art.einpassen(source,(20,12),"mitte",8)
    assert output.size==(20,12)
    assert details["motiv"]==[2,3,6,7]
    assert details["skaliert"]==[4,4]  # no upscale of a 4x4 symbol
    assert details["faktor"]==1.0
    assert output.getpixel((0,0))[3]==0
    assert sum(p[3]>0 for p in output.get_flattened_data())==16
    assert source.tobytes()==before


@pytest.mark.parametrize("shape,anchor", [
    ((0,10),"mitte"), ((10,0),"unten-mitte"),((-1,4),"links-oben"),
    ((5,5),"wrong-anchor"), ((True,5),"mitte"),
])
def test_generated_image_rejects_invalid_geometry(shape,anchor):
    with pytest.raises(import_art.EinpflegeError):
        import_art.einpassen(small_art(),shape,anchor,8)


def test_slot_import_dry_run_and_explicit_write_only(tmp_path):
    roh=tmp_path/"new-art"
    roh.mkdir()
    source=small_art()
    source.save(roh/"Icon.png")
    baum=tmp_path/"export-tree"
    (baum/"UI-Sprites").mkdir(parents=True)
    (baum/"index.json").write_text("{}",encoding="utf8")
    old=baum/"UI-Sprites"/"Icon.png"
    Image.new("RGBA",(20,12),(3,8,13,255)).save(old)
    before=old.read_bytes()
    order=[{"schluessel":"Icon","slot":"UI-Sprites/Icon.png",
            "zielgroesse":[20,12]}]
    result=import_art.einpflegen(roh,baum,order,anker="mitte",schwelle=8,
                                schreiben=False,ohne_alpha_erlauben=False)
    assert result["geschrieben"] is False
    assert len(result["eingepflegt"])==1
    assert old.read_bytes()==before
    written=import_art.einpflegen(roh,baum,order,anker="mitte",schwelle=8,
                                 schreiben=True,ohne_alpha_erlauben=False)
    assert written["geschrieben"] is True
    with Image.open(old) as image:
        assert image.size==(20,12)
        assert image.getpixel((0,0))[3]==0
    assert source.tobytes()==small_art().tobytes()


@pytest.mark.parametrize("bad", [
    "../outside.png", "UI-Sprites/../../outside.png",
    "UI-Sprites//Icon.png", "UI-Sprites/CON.png",
    "/outside.png", "UI-Sprites/evil.exe",
    "UI-Sprites/C:/absolute.png",
])
def test_untrusted_assignment_cannot_escape_export_tree(tmp_path,bad):
    roh=tmp_path/"source"
    roh.mkdir()
    small_art().save(roh/"Icon.png")
    baum=tmp_path/"export"
    baum.mkdir()
    (baum/"index.json").write_text("{}",encoding="utf8")
    outside=tmp_path/"outside.png"
    outside.write_bytes(b"do not overwrite")
    old=outside.read_bytes()
    order=[{"schluessel":"Icon","slot":bad,"zielgroesse":[20,12]}]
    with pytest.raises(import_art.EinpflegeError):
        import_art.einpflegen(roh,baum,order,anker="mitte",schwelle=8,
                              schreiben=True,ohne_alpha_erlauben=False)
    assert outside.read_bytes()==old


def test_vegetation_measurements_are_stable_without_game_sources():
    source=small_art()
    bbox=vegetation.opaque_bbox(source)
    assert bbox==(2,3,6,7)
    assert vegetation.baseline_anchor(bbox,10)==(4,3)
    assert vegetation.scaled_size(20,12,0.5)==(10,6)
    assert vegetation.min_fit_scale((20,12),(10,8))==0.5
    assert vegetation.frame_index("tree_cactii-010")==10
    assert vegetation.cactii_table_check()==[]
    bad=dict(vegetation.CACTII_COMPOSITION)
    bad.pop(16)
    assert vegetation.cactii_table_check(bad)
    assert source.tobytes()==small_art().tobytes()


@pytest.mark.parametrize("invalid", [0,-0.3,1.3])
def test_vegetation_rejects_upscale_and_negative_scale(invalid):
    with pytest.raises(vegetation.VegetationError):
        vegetation.scaled_size(10,10,invalid)


def test_vegetation_pixel_composition_and_out_of_bounds_refusal():
    donor=Image.new("RGBA",(4,4),(255,255,255,255))
    placements=[(vegetation.Placement("tree_shrub-0",1.0,0,0),
                 donor,(2.0,0.0))]
    output,placed=vegetation.compose_on_canvas((20,20),(10,3),placements)
    assert output.size==(20,20)
    assert (placed[0].left,placed[0].top)==(8,13)
    assert output.getpixel((8,13))==(255,255,255,255)
    assert output.getpixel((0,0))[3]==0
    with pytest.raises(vegetation.VegetationError):
        vegetation.compose_on_canvas((20,20),(0,0),placements)


@pytest.mark.parametrize("value,expected", [
    ("UI-Buildings O023 Light Blue.png",("UI-Buildings O023","Light Blue")),
    ("UI-Buildings O023 Blue.png",("UI-Buildings O023","Blue")),
    ("UI-Buildings O023.png",("UI-Buildings O023",None)),
])
def test_pairing_keeps_player_colour_families_distinct(value,expected):
    assert pair.familie(value)==expected


def test_direct_pair_application_dry_run_before_explicit_write(tmp_path):
    import ui_apply
    baum=tmp_path/"export"
    (baum/"UI-Buildings").mkdir(parents=True)
    (baum/"index.json").write_text("{}",encoding="utf8")
    slot=baum/"UI-Buildings"/"Icon.png"
    Image.new("RGBA",(16,16),(210,40,20,255)).save(slot)
    before=slot.read_bytes()
    sh1=tmp_path/"sh1"
    sh1.mkdir()
    Image.new("RGBA",(4,4),(25,45,210,255)).save(sh1/"SH1.png")
    data={"candidates":[{"slot":"UI-Buildings/Icon.png","sh1":"SH1.png"}]}
    options=dict(toepfe=["candidates"],gruppen=None,liste=None,
                 anker="unten-mitte",mehrfach_erlauben=False,
                 einpassen=0,mindestdeckung=0.0)
    proposal=ui_apply.anwenden(data,sh1,baum,schreiben=False,**options)
    assert proposal["geschrieben"] is False
    assert slot.read_bytes()==before
    applied=ui_apply.anwenden(data,sh1,baum,schreiben=True,**options)
    assert applied["geschrieben"] is True
    assert slot.read_bytes()!=before


@pytest.mark.parametrize("slot,sh1_name",[
    ("../outside.png","SH1.png"),
    ("UI-Buildings/Icon.png","../outside.png"),
    ("UI-Buildings/../../outside.png","SH1.png"),
    ("UI-Buildings/CON.png","SH1.png"),
])
def test_pair_application_rejects_escaping_assignment(tmp_path,slot,sh1_name):
    import ui_apply
    baum=tmp_path/"export"
    (baum/"UI-Buildings").mkdir(parents=True)
    (baum/"index.json").write_text("{}",encoding="utf8")
    Image.new("RGBA",(16,16),(210,40,20,255)).save(
        baum/"UI-Buildings"/"Icon.png")
    sh1=tmp_path/"sh1"
    sh1.mkdir()
    Image.new("RGBA",(4,4),(25,45,210,255)).save(sh1/"SH1.png")
    outside=tmp_path/"outside.png"
    outside.write_bytes(b"protected")
    original=outside.read_bytes()
    data={"candidates":[{"slot":slot,"sh1":sh1_name}]}
    with pytest.raises(ui_apply.ApplyError,match="Unsicherer"):
        ui_apply.anwenden(data,sh1,baum,toepfe=["candidates"],
                          gruppen=None,liste=None,anker="unten-mitte",
                          schreiben=True)
    assert outside.read_bytes()==original

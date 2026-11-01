"""Exact pixel difference with explicit non-native attestations."""
from pathlib import Path
import json
import sys

from PIL import Image
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/"tools"),str(ROOT/"src")]
from origins_noesis_pixel_compare import (
    PixelCompareError,compare_captured_frames
)


def test_exact_pixel_differences_create_heatmap_and_native_false(tmp_path):
    original=tmp_path/"reference.png"
    modified=tmp_path/"captured.png"
    a=Image.new("RGBA",(64,40),(10,20,30,255))
    a.save(original)
    b=a.copy()
    for x in range(6,16):
        for y in range(9,14):
            b.putpixel((x,y),(250,21,30,255))
    b.save(modified)
    before=original.read_bytes();after=modified.read_bytes()
    report=compare_captured_frames(original,modified,tmp_path/"proof")
    assert report["changed_pixels"]==50
    assert report["total_pixels"]==2560
    assert report["pixel_identical"] is False
    assert report["native_noesis_renderer_invoked"] is False
    assert report["game_render_parity_attested"] is False
    assert report["maximum_channel_difference"]==240
    assert original.read_bytes()==before and modified.read_bytes()==after
    with Image.open(report["heatmap"]) as image:
        assert image.convert("RGBA").getpixel((10,11))[3]==255
        assert image.convert("RGBA").getpixel((30,31))[3]==0
    saved=json.loads(Path(report["report"]).read_text("utf8"))
    assert saved["changed_pixels"]==report["changed_pixels"]


def test_identical_pixels_report_zero_even_for_separate_pngs(tmp_path):
    a=tmp_path/"a.png";b=tmp_path/"b.png"
    Image.new("RGBA",(40,20),(15,20,30,255)).save(a)
    b.write_bytes(a.read_bytes())
    proof=compare_captured_frames(a,b,tmp_path/"result")
    assert proof["pixel_identical"]
    assert proof["changed_pixels"]==0
    assert proof["mean_absolute_channel_difference"]==0


def test_different_resolutions_must_not_be_scaled_to_fake_parity(tmp_path):
    first=tmp_path/"first.png";second=tmp_path/"second.png"
    Image.new("RGBA",(40,20)).save(first)
    Image.new("RGBA",(41,20)).save(second)
    with pytest.raises(PixelCompareError,match="Auflösung"):
        compare_captured_frames(first,second,tmp_path/"result")
    assert not (tmp_path/"result").exists()


def test_rejects_non_png_and_existing_reports(tmp_path):
    a=tmp_path/"a.png";b=tmp_path/"b.png"
    Image.new("RGBA",(20,20)).save(a);b.write_bytes(a.read_bytes())
    compare_captured_frames(a,b,tmp_path/"result")
    with pytest.raises(PixelCompareError,match="existiert"):
        compare_captured_frames(a,b,tmp_path/"result")
    fake=tmp_path/"fake.png";fake.write_bytes(b"not a screenshot")
    with pytest.raises(PixelCompareError,match="lesbare"):
        compare_captured_frames(fake,b,tmp_path/"different")
    assert not (tmp_path/"different").exists()

"""GUI preview is bounded, cached, and uses one checkerboard bitmap."""
from __future__ import annotations
import importlib.machinery
import importlib.util
from pathlib import Path
import sys
import tkinter as tk

from PIL import Image
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from suite_preview_render import preview_dimensions,checkerboard,MAX_PREVIEW_PIXELS


def _module():
    loader=importlib.machinery.SourceFileLoader("suite_preview_test",str(ROOT/"tools"/"suite.pyw"))
    spec=importlib.util.spec_from_loader(loader.name,loader)
    module=importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.mark.parametrize("size,zoom",[
    ((16,16),4.0),((2048,2048),4.0),((4096,4096),4.0),
    ((5000,4000),1.0),((1,1),1.0),
])
def test_preview_pixel_budget(size,zoom):
    actual,capped=preview_dimensions(size,zoom)
    assert 0<actual[0]<=2048 and 0<actual[1]<=2048
    assert actual[0]*actual[1]<=MAX_PREVIEW_PIXELS+4096
    if size==(16,16):
        assert actual==(64,64) and capped is False
    if size[0]>=2048:
        assert capped is True


def test_transparency_checker_is_bitmap_not_canvas_shapes():
    rgba=Image.new("RGBA",(64,64),(0,0,0,0))
    rgba.putpixel((0,0),(255,10,10,255))
    result=checkerboard(rgba,(64,64))
    assert result.mode=="RGB"
    assert result.getpixel((0,0))==(255,10,10)
    assert result.getpixel((2,2))==(210,210,210)
    assert result.getpixel((20,2))==(168,168,168)
    assert rgba.getpixel((2,2))[3]==0


def test_resize_without_file_change_does_not_open_png_again(tmp_path,monkeypatch):
    suite=_module()
    root=tk.Tk()
    root.withdraw()
    try:
        preview=suite.ImagePreview(root)
        preview.pack()
        pic=tmp_path/"small.png"
        Image.new("RGBA",(80,64),(255,0,90,122)).save(pic)
        preview.show(pic,detail="Ein Testbild")
        root.update_idletasks()
        assert len(preview.canvas.find_all())==1
        photo=preview._photo
        opened=Image.open

        def unexpected_open(*args,**kw):
            raise AssertionError("unchanged preview must be cached")

        monkeypatch.setattr(Image,"open",unexpected_open)
        preview.redraw(force=False)
        assert preview._photo is photo
        assert len(preview.canvas.find_all())==1
        monkeypatch.setattr(Image,"open",opened)
        preview.zoom.set("400 %")
        preview.redraw(force=True)
        assert len(preview.canvas.find_all())==1
        assert preview._photo.width()==320
    finally:
        root.destroy()


def test_large_png_displays_at_bounded_size_with_notice(tmp_path):
    suite=_module()
    root=tk.Tk()
    root.withdraw()
    try:
        preview=suite.ImagePreview(root)
        preview.pack()
        source=tmp_path/"large.png"
        Image.new("RGBA",(3200,2400),(120,30,55,80)).save(source)
        preview.zoom.set("400 %")
        preview.show(source)
        assert preview._photo is not None
        assert preview._photo.width()*preview._photo.height()<=MAX_PREVIEW_PIXELS+4096
        assert len(preview.canvas.find_all())==1
        assert "begrenzt" in preview.detail.cget("text")
    finally:
        root.destroy()

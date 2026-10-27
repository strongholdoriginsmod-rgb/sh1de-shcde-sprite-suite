"""ORIGINS preset must match the user's historical blue/silver implementation."""
from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from suite_sh1_origins_palette import historical_flags, recolour


def test_legacy_origins_routes_only_known_original_keys():
    assert historical_flags("UI-Buildings H007","UI-Buildings H007.png") == (False,True)
    assert historical_flags("btn_shield_bar_01","btn_shield_bar_01.png") == (True,False)
    assert historical_flags("unrelated stone","unrelated-stone.png") == (False,False)


def test_palette_transformation_preserves_canvas_and_alpha():
    pixels=np.array([
        [(240,10,13,255),(220,162,29,255),(15,56,190,255)],
        [(18,210,180,255),(240,14,30,0),(14,16,22,255)],
    ],dtype=np.uint8)
    image=Image.fromarray(pixels,"RGBA")
    result,count=recolour(image,themed=True,dark_blue=True)
    assert result.size==image.size
    assert result.mode=="RGBA"
    assert np.array_equal(np.asarray(result)[:,:,3],pixels[:,:,3])
    assert result.getpixel((1,1))==image.getpixel((1,1))
    assert count>0


@pytest.mark.parametrize("themed,dark_blue",[(False,False),(True,False),(False,True),(True,True)])
def test_origins_palette_matches_historical_tool_when_supplied(themed,dark_blue):
    """Compare against the real old source only if it was supplied by the owner.

    Public tests ship synthetic pixels, not original Firefly art or a copy of
    the old proprietary workshop tree.
    """
    old=os.environ.get("STRONGHOLD_ORIGINS_PALETTE_REFERENCE")
    if not old or not Path(old).is_file():
        pytest.skip("Historical user-owned palette tool not linked")
    old_module=runpy.run_path(old)
    pixels=np.zeros((20,32,4),dtype=np.uint8)
    pixels[:,:,0]=np.arange(32,dtype=np.uint8)[None,:]*8
    pixels[:,:,1]=np.arange(20,dtype=np.uint8)[:,None]*10
    pixels[:,:,2]=((pixels[:,:,0].astype(int)*3+pixels[:,:,1].astype(int))%256).astype(np.uint8)
    pixels[:,:,3]=255
    pixels[2:5,4:9,3]=0
    image=Image.fromarray(pixels,"RGBA")
    wanted,count_old=old_module["recolour"](
        image, themed=themed, dark_blue=dark_blue)
    actual,count_new=recolour(
        image, themed=themed, dark_blue=dark_blue)
    assert count_new==count_old
    assert actual.tobytes()==wanted.tobytes()

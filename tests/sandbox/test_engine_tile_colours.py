"""Unity gameTile/TilemapManager colour rules, extracted from the locked build.

Tests ensure separate floatColour overrides and exact per-channel RGB
coefficients instead of the old grayscale-only approximation.
"""
from pathlib import Path
from types import SimpleNamespace
import sys

import numpy as np
import pytest
from PIL import Image

from stronghold_europe_de.sandbox.runtime_graphics import (
    RuntimeSprite, RuntimeSpriteResolver,
    tile_tint_components, light_multiplier, TILE_FLOAT_COLOURS,
)
from stronghold_europe_de.sandbox.native_runtime import RuntimeSnapshot

TOOLS=str(Path(__file__).resolve().parents[2]/"tools")
if TOOLS not in sys.path:
    sys.path.insert(0,TOOLS)
pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication
from sandbox_runtime_renderer import NativeCommandRenderer

MAPS=Path("E:/SSGameQA/Stronghold Crusader Definitive Edition_Data/StreamingAssets/Maps")


@pytest.mark.parametrize("light,expected",[
    (0,1),(1,.9),(2,.8),(3,.7),(4,.6),(5,.5),(6,.4),(7,.3),
    (11,.94),(12,.88),(13,.82),(14,.76),(15,.7),(16,.64),(17,.58),
    (50,1),(51,.95),(52,.9),(53,.85),(54,.8),(55,.85),
])
def test_original_game_shading_table_exact(light,expected):
    assert tile_tint_components(light,0)==pytest.approx((expected,)*3)
    assert light_multiplier(light)==pytest.approx(expected)


@pytest.mark.parametrize("colour,expected",[
    (55,(83/85,.3019608,.003921569)),
    (56,(.23137255,.64705884,1/15)),
    (57,(29/85,28/85,.8784314)),
    (58,(.8980392,.85490197,.49803922)),
    (59,(.5019608,)*3),
    (60,(56/85,23/85,2/15)),
    (61,(.2509804,)*3),
    (62,(.5019608,)*3),
    (63,(.8235294,.8235294,1.0)),
])
def test_float_colour_overrides_any_tile_shadow(colour,expected):
    assert tile_tint_components(3,colour)==pytest.approx(expected)
    assert tile_tint_components(0,colour)==pytest.approx(expected)


def test_unknown_or_unset_colour_preserves_white():
    assert tile_tint_components(0,0)==(1,1,1)
    assert tile_tint_components(4,88)==(1,1,1)


def _mock_renderer(monkeypatch):
    app=QApplication.instance() or QApplication([])
    from sandbox_engine_assets import EngineSpriteAssets
    rows=np.zeros((2,21),dtype="<i2")
    rows[0,:8]=[0,400,400,55,305,8,3,56]
    rows[1,:8]=[0,401,400,55,305,8,3,0]
    owner=SimpleNamespace(
        _map_path=MAPS/"Antioch.map",
        _channels=SimpleNamespace(at=lambda *args:{3005:8}),
        terrain_tests=None,surface_tests=None,
        _texture_signatures={},_signature=lambda g,n:(None,),
        message=SimpleNamespace(emit=lambda *args:None),
        _source=None,
    )
    r=NativeCommandRenderer(owner,RuntimeSnapshot(rows,{}))
    class Frame:
        image=Image.new("RGBA",(8,8),(100,150,200,77))
        foot=(4,7)
    monkeypatch.setattr(r.assets,"frame",lambda *args:Frame())
    return r


def test_rgb_tint_preserves_alpha_and_is_cached_per_colour(monkeypatch):
    r=_mock_renderer(monkeypatch)
    a=r._tile_reference(r.snapshot.tile(400,400))
    b=r._tile_reference(r.snapshot.tile(401,400))
    assert (a.light,a.float_colour)==(0,56)
    assert (b.light,b.float_colour)==(0,0)
    pix=r._pixmap(a)[0].toImage()
    color=pix.pixelColor(1,1)
    # Qt premultiplies alpha in QPixmap storage; an RGBA->QPixmap->QImage
    # round-trip can differ by one RGB unit even when the source PIL tint
    # is exact. Require unchanged alpha and tolerance for that quantization.
    expected=(round(100*.23137255),round(150*.64705884),round(200/15))
    assert color.alpha()==77
    assert all(abs(a-b)<=2 for a,b in zip(color.getRgb()[:3],expected))
    raw=r._pixmap(b)[0].toImage().pixelColor(1,1).getRgb()
    assert raw[3]==77 and all(abs(a-b)<=2 for a,b in zip(raw[:3],(100,150,200)))
    assert len(r.images)==2
    assert a!=b


def test_engine_tile_float_colour_propagates_to_cliff_side(monkeypatch):
    app=QApplication.instance() or QApplication([])
    r=_mock_renderer(monkeypatch)
    record=r.snapshot.tile(400,400).copy()
    record[11:13]=[9,14]
    r.snapshot.records[r.snapshot.tile_lookup[400,400],11:13]=[9,14]
    # A single raised tile has exposed side because its neighbors are empty.
    calls=[]
    r._draw=lambda _p,ref,*args: calls.append(ref)
    r._floor(None,record)
    assert len(calls)==2
    assert (calls[0].float_colour,calls[1].float_colour)==(56,56)
    assert calls[0].light==calls[1].light

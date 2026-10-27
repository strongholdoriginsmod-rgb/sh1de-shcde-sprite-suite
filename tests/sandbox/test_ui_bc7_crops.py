"""Decoder parity against Pillow full BC7 mip decode on a tiny fixture.

No installed-game assets or exported UI images required.
"""
from pathlib import Path
import sys
import pytest

root=Path(__file__).resolve().parents[2]
if str(root/"src") not in sys.path:
    sys.path.insert(0,str(root/"src"))

from stronghold_europe_de.sandbox.ui_bc7_crops import bc7_region,BC7CropError


@pytest.fixture(scope="module")
def bc7_fixture():
    import etcpak
    from PIL import Image
    image=Image.new("RGBA",(32,24))
    image.putdata([
        ((x*23+y*11)%256,(x*3+y*19)%256,(x*7+y*5)%256,255)
        for y in range(24) for x in range(32)
    ])
    packed=etcpak.compress_bc7(image.tobytes(),32,24,None)
    full=Image.frombytes("RGBA",(32,24),packed,"bcn",7)
    return packed,full


@pytest.mark.parametrize("rect",[
    (0,0,1,1), (1,2,9,7), (6,1,21,18),
    (27,19,5,5), (0,0,32,24), (29,0,3,24),
])
@pytest.mark.parametrize("flip",[False,True])
def test_partial_block_decode_matches_full_at_all_offsets(bc7_fixture,rect,flip):
    from PIL import Image
    packed,full=bc7_fixture
    whole=(full.transpose(Image.Transpose.FLIP_TOP_BOTTOM) if flip else full)
    expected=whole.crop((rect[0],rect[1],rect[0]+rect[2],rect[1]+rect[3]))
    crop=bc7_region(packed,32,24,rect,flip_vertical=flip)
    assert crop.size==(rect[2],rect[3])
    assert crop.tobytes()==expected.tobytes()


@pytest.mark.parametrize("rect",[
    (-1,0,1,1),(0,-1,2,2),(0,0,0,1),(32,0,1,1),
    (0,23,1,2),(0,0,8192,8192),("0",0,1,1),(True,0,1,1),
])
def test_invalid_untrusted_region_fails_closed(bc7_fixture,rect):
    packed,_=bc7_fixture
    with pytest.raises(BC7CropError):
        bc7_region(packed,32,24,rect)


def test_short_mip_or_bad_dimensions_fail_closed():
    with pytest.raises(BC7CropError):
        bc7_region(b"",8192,8192,(3,4,64,64))
    with pytest.raises(BC7CropError):
        bc7_region(b"",31,24,(0,0,1,1))

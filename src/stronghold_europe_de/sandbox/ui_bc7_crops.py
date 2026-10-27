"""Memory-bounded BC7 region decoder for original SHCDE UI atlas references.

The Texture2D is 8192x8192 BC7 with 14 mip levels. This routine decodes
ONLY the blocks intersecting one XAML CroppedBitmap rectangle, not the
entire ~256 MiB RGBA texture. The data must be the original top mip level,
and UnityPy's default image orientation is vertically flipped.
No I/O or Unity asset mutation is performed by this module.
"""
from __future__ import annotations

from math import ceil
from PIL import Image

BC7_BLOCK_BYTES=16
BC7_BLOCK_PIXELS=4
MAX_CROP_PIXELS=4_000_000


class BC7CropError(ValueError):
    pass


def bc7_region(data: bytes, width: int, height: int,
               rect: tuple[int, int, int, int], *,
               flip_vertical: bool=True) -> Image.Image:
    """RGBA crop from packed BC7 mip zero in matching XAML coordinates."""
    if (type(width) is not int or type(height) is not int or
            width<=0 or height<=0 or width%4 or height%4):
        raise BC7CropError("Invalid BC7 atlas dimensions")
    if not isinstance(rect,(list,tuple)) or len(rect)!=4 or not all(
        type(v) is int for v in rect
    ):
        raise BC7CropError("Invalid four-integer XAML rectangle")
    x,y,w,h=rect
    if (x<0 or y<0 or w<=0 or h<=0 or x+w>width or y+h>height or
            w*h>MAX_CROP_PIXELS):
        raise BC7CropError("XAML region outside atlas or too large")
    if len(data) < (width//4)*(height//4)*BC7_BLOCK_BYTES:
        raise BC7CropError("BC7 mip zero is truncated")

    raw_y0,raw_y1=(height-y-h,height-y) if flip_vertical else (y,y+h)
    ax0=(x//4)*4
    ax1=ceil((x+w)/4)*4
    ay0=(raw_y0//4)*4
    ay1=ceil(raw_y1/4)*4
    stride=width//4*BC7_BLOCK_BYTES
    row_len=(ax1-ax0)//4*BC7_BLOCK_BYTES
    begin=ay0//4
    rows=(ay1-ay0)//4
    off=ax0//4*BC7_BLOCK_BYTES
    packed=b"".join(data[row*stride+off:row*stride+off+row_len]
                    for row in range(begin,begin+rows))
    image=Image.frombytes("RGBA",(ax1-ax0,ay1-ay0),packed,"bcn",7)
    if flip_vertical:
        image=image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        local_y=ay1-raw_y1
    else:
        local_y=y-ay0
    return image.crop((x-ax0,local_y,x-ax0+w,local_y+h))

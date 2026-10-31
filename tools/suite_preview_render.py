"""Bounded bitmap previews; no Tk objects or project writes."""
from __future__ import annotations

from math import sqrt

from PIL import Image, ImageDraw


MAX_PREVIEW_SIDE = 2048
MAX_PREVIEW_PIXELS = 4_000_000


def preview_dimensions(source: tuple[int,int], scale: float) -> tuple[tuple[int,int], bool]:
    width, height = source
    if width <= 0 or height <= 0 or scale <= 0:
        raise ValueError("Invalid source dimensions or zoom")
    allowed = min(
        scale,
        MAX_PREVIEW_SIDE / width,
        MAX_PREVIEW_SIDE / height,
        sqrt(MAX_PREVIEW_PIXELS / (width * height)),
    )
    result = max(1,round(width * allowed)), max(1,round(height * allowed))
    return result, allowed + 1e-9 < scale


def checkerboard(image: Image.Image, size: tuple[int,int]) -> Image.Image:
    """Blend only the bounded displayed RGBA bitmap onto a 16px checker.

    A single RGB bitmap replaces hundreds of thousands of Tk rectangles.
    The source PNG remains unchanged; this is display-only.
    """
    width,height=size
    if width<=0 or height<=0 or width>MAX_PREVIEW_SIDE or height>MAX_PREVIEW_SIDE:
        raise ValueError("Preview exceeds bounded size")
    if width*height>MAX_PREVIEW_PIXELS+4096:
        raise ValueError("Preview exceeds bounded pixel budget")
    tile = Image.new("RGB",(32,32),(210,210,210))
    ImageDraw.Draw(tile).rectangle((16,0,31,15),fill=(168,168,168))
    ImageDraw.Draw(tile).rectangle((0,16,15,31),fill=(168,168,168))
    background = Image.new("RGB",size)
    for y in range(0,height,32):
        for x in range(0,width,32):
            background.paste(tile,(x,y))
    rgba=image.convert("RGBA")
    if rgba.size != size:
        rgba=rgba.resize(size,Image.Resampling.NEAREST)
    background.paste(rgba,(0,0),rgba.getchannel("A"))
    return background

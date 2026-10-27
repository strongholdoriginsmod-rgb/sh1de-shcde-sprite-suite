"""Historical StrongholdOrigins blue/silver UI palette, now previewed in HUD Studio.

Preserves the thresholds and HSV formulas from the user's earlier
StrongholdOrigins project (tools/build-ui-palette.py). Transforms ONLY an
explicitly selected RGBA working copy; no atlas, layout, XAML or game writes.
"""
from __future__ import annotations

import re

import numpy as np
from PIL import Image

THEME_NAMES = re.compile(
    r"ui-buttons|button|btn_|border|panel|frame|scroll|bar|shield|tab|popup|menu",
    re.IGNORECASE,
)
DARK_BLUE_NAMES = re.compile(r"(?:^| )Blue(?:\.png)?$|H00[789]", re.IGNORECASE)


def historical_flags(key: str, filename: str) -> tuple[bool, bool]:
    """Origins' original filename/key routing, never a guess by pixel hue."""
    return bool(THEME_NAMES.search(key)), bool(DARK_BLUE_NAMES.search(filename))


def recolour(image: Image.Image, *, themed: bool, dark_blue: bool) -> tuple[Image.Image, int]:
    """Pixel-identical HSV selection and transforms to earlier Origins tooling."""
    rgba = np.asarray(image.convert("RGBA")).copy()
    hsv = np.asarray(image.convert("RGB").convert("HSV"))
    alpha = rgba[:, :, 3]
    changed = np.zeros(alpha.shape, dtype=bool)

    if themed:
        hue, saturation, value = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
        red = (
            (alpha > 0)
            & ((hue <= 15) | (hue >= 244))
            & (saturation >= 72)
            & (value >= 34)
        )
        if np.any(red):
            red_hsv = hsv.copy()
            red_hsv[:, :, 0][red] = 151
            red_hsv[:, :, 1][red] = np.maximum(saturation[red], 176)
            red_hsv[:, :, 2][red] = np.clip(
                value[red].astype(np.float32) * 0.60 + 18.0,
                32,
                150,
            ).astype(np.uint8)
            recoloured_red = np.asarray(Image.fromarray(red_hsv, "HSV").convert("RGB"))
            rgba[:, :, :3][red] = recoloured_red[red]
            changed |= red

        gold = (
            (alpha > 0)
            & (hue >= 14)
            & (hue <= 49)
            & (saturation >= 58)
            & (value >= 45)
        )
        if np.any(gold):
            rgb = rgba[:, :, :3].astype(np.float32)
            luminance = (
                rgb[:, :, 0] * 0.2126
                + rgb[:, :, 1] * 0.7152
                + rgb[:, :, 2] * 0.0722
            )
            silver = np.stack(
                (
                    luminance * 0.91,
                    luminance * 0.96,
                    luminance * 1.04,
                ),
                axis=2,
            )
            rgba[:, :, :3][gold] = np.clip(silver[gold], 0, 255).astype(np.uint8)
            changed |= gold

    if dark_blue:
        updated_hsv = np.asarray(
            Image.fromarray(rgba, "RGBA").convert("RGB").convert("HSV")
        ).copy()
        hue, saturation, value = (
            updated_hsv[:, :, 0], updated_hsv[:, :, 1], updated_hsv[:, :, 2]
        )
        blue = (
            (alpha > 0)
            & (hue >= 125)
            & (hue <= 180)
            & (saturation >= 55)
            & (value >= 35)
        )
        if np.any(blue):
            updated_hsv[:, :, 0][blue] = 151
            updated_hsv[:, :, 1][blue] = np.maximum(saturation[blue], 180)
            updated_hsv[:, :, 2][blue] = np.clip(
                value[blue].astype(np.float32) * 0.52 + 10.0,
                26,
                118,
            ).astype(np.uint8)
            recoloured_blue = np.asarray(
                Image.fromarray(updated_hsv, "HSV").convert("RGB")
            )
            rgba[:, :, :3][blue] = recoloured_blue[blue]
            changed |= blue

    return Image.fromarray(rgba, "RGBA"), int(changed.sum())

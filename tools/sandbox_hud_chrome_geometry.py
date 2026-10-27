"""Measured decorative HUD chrome geometry from four 2560x1440 screenshots.

The visual source is E:/SU/projekt/sandbox/hud/hud.json and hud.png.
This is *approximate geometry* for original Stronghold HUD zones, not a
Unity shader, live gameplay simulation, or a redistributed screenshot.
The dynamic Qt radar/build controls remain live and independently sourced.
"""
from __future__ import annotations

ORIGINAL_SCREEN = (2560, 1440)
ORIGINAL_HUD = (1060, 1123, 1500, 317)
# Measured in the existing 1500px reference HUD crop around y=235/275:
# paper ends near x=957, dark green command spine ends near x=1015.
# The screenshots carry no authoritative command-state mappings.
COMMAND_SPINE = (957, 1015)


def hud_backplate_source_rect(
    source_size: tuple[int, int],
    viewport_size: tuple[int, int],
) -> tuple[float, float, float, float]:
    """Centered source crop for uniform (non-distorted) HUD parchment painting.

    The game atlas UI-HUD 007 is a very wide strip. Painting its full
    1752x206 crop into each smaller Qt panel used nonuniform x/y scaling,
    corrupting the original source geometry. A center source crop fills the
    target with one uniform factor without changing actual icon positions or
    claiming the parent XAML's game-state animation was reconstructed.

    Coordinates are source *pixels*, not Tk/Qt device-independent dimensions.
    """
    source_w, source_h = source_size
    viewport_w, viewport_h = viewport_size
    if min(source_w, source_h, viewport_w, viewport_h) <= 0:
        raise ValueError("HUD-Hintergrund hat ungültige Quell-/Zielfläche")
    src_aspect = source_w / source_h
    target_aspect = viewport_w / viewport_h
    if target_aspect >= src_aspect:
        visible_h = source_w / target_aspect
        return (0.0, (source_h - visible_h) / 2.0, float(source_w), visible_h)
    visible_w = source_h * target_aspect
    return ((source_w - visible_w) / 2.0, 0.0, visible_w, float(source_h))


def spine_width(hud_width: int) -> int:
    """Keep genuine interactive controls reachable at compact notebook sizes."""
    width = max(1, int(hud_width))
    return max(26, min(52, round(
        width * (COMMAND_SPINE[1] - COMMAND_SPINE[0]) / ORIGINAL_HUD[2]
    )))


def spine_start_ratio() -> float:
    return COMMAND_SPINE[0] / ORIGINAL_HUD[2]


def chrome_alignment_error(hud_width: int, spine_x: int) -> float:
    """Normalized position mismatch: evidence, not a UI-parity acceptance."""
    width = max(1, int(hud_width))
    return spine_x / width - spine_start_ratio()

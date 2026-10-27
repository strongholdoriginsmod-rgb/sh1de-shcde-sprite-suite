"""Source-labelled, screenshot-measured HUD chrome geometry checks.

A measured QFrame is not proof of original Unity XAML/runtime UI parity.
"""
from pathlib import Path
import sys
import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT/"tools") not in sys.path:
    sys.path.insert(0, str(ROOT/"tools"))

from sandbox_hud_chrome_geometry import (
    COMMAND_SPINE, ORIGINAL_HUD, ORIGINAL_SCREEN,
    spine_width, spine_start_ratio, chrome_alignment_error,
)


@pytest.mark.parametrize("width", [1, 320, 684, 784, 960, 1500, 4000])
def test_green_command_ribbon_scales_safely(width):
    result=spine_width(width)
    assert 26 <= result <= 52
    if 684<=width<=1500:
        assert abs(result/width - (
            COMMAND_SPINE[1]-COMMAND_SPINE[0]
        )/ORIGINAL_HUD[2]) < .03


def test_reference_is_a_subregion_not_a_full_game_screenshot():
    assert ORIGINAL_SCREEN==(2560,1440)
    assert ORIGINAL_HUD==(1060,1123,1500,317)
    assert 0 < COMMAND_SPINE[0] < COMMAND_SPINE[1] < ORIGINAL_HUD[2]
    assert .62 < spine_start_ratio() < .66
    assert abs(chrome_alignment_error(1500,COMMAND_SPINE[0]))<1e-9

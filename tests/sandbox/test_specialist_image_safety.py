"""Specialist image tools must never disable Pillow decompression-bomb protection."""
from __future__ import annotations

import importlib
from pathlib import Path
import sys
import warnings

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"tools"))

MODULES = (
    "ui_apply", "ui_einpflegen", "ui_pair", "ui_rahmen",
    "ui_sh1_extract", "ui_sh1_umstellung", "ui_vorlage",
)


def test_specialist_imports_preserve_pillow_safety_limit():
    # A 100 MP input is already hundreds of megabytes once decoded; the
    # previous "None" setting silently removed all decompression protection.
    before = Image.MAX_IMAGE_PIXELS
    assert before is not None and before > 0
    for module in MODULES:
        importlib.import_module(module)
        assert Image.MAX_IMAGE_PIXELS == before, module


def test_image_size_guard_can_reject_extreme_input_without_allocating_pixels():
    before = Image.MAX_IMAGE_PIXELS
    assert before is not None
    # Pillow's own protection is what these tools must retain.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", Image.DecompressionBombWarning)
        try:
            Image._decompression_bomb_check((int(before*2)+1, 1))
        except Image.DecompressionBombError:
            pass
        else:
            raise AssertionError("Pillow decompression guard was disabled")

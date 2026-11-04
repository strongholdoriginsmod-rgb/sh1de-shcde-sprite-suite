"""Shipped PDF and captured UI screenshots remain printable and game-free."""
from __future__ import annotations
from pathlib import Path
import struct

ROOT=Path(__file__).resolve().parents[2]
PDF=ROOT/"docs"/"SPRITESUITE_ILLUSTRIERTES_HANDBUCH.pdf"
SCREEN=ROOT/"docs"/"guide-screens"
CAPTURES=(
    "ux-workflow-current.png",
    "ux-tutorial-quickstart-DE.png",
    "ux-tutorial-layout-DE.png",
    "ux-tutorial-layout-EN.png",
    "ux-compatibility-readonly.png",
    "ux-demo-26-modules.png",
)


def test_bundled_illustrated_manual_is_real_bounded_unencrypted_pdf():
    assert PDF.is_file() and not PDF.is_symlink()
    blob=PDF.read_bytes()
    assert blob.startswith(b"%PDF-1.")
    assert b"%%EOF" in blob[-1024:]
    assert 50_000 < len(blob) < 4_000_000
    assert b"/Encrypt" not in blob
    assert blob.count(b"/Subtype /Image") >= 6
    # Every new Page object is unique; /Pages is not a leaf page.
    assert blob.count(b"/Type /Page\n") == 9
    assert b"matth" not in blob and b"C:\\Users\\" not in blob


def test_manual_images_are_small_real_program_captures():
    assert {x.name for x in SCREEN.glob("*.png")} == set(CAPTURES)
    for file in SCREEN.glob("*.png"):
        assert file.is_file() and not file.is_symlink()
        header=file.read_bytes()[:24]
        assert header[:8]==b"\x89PNG\r\n\x1a\n"
        assert header[12:16]==b"IHDR"
        width,height=struct.unpack(">II",header[16:24])
        assert 300<=width<=3200
        assert 250<=height<=2200
        assert 5000<=file.stat().st_size<=1_500_000

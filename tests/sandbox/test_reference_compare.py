"""Exact-resolution pixel comparison metrics and reference-crop semantics."""
import sys
from pathlib import Path
import pytest
from PIL import Image

pytest.importorskip("PySide6")
TOOLS = str(Path(__file__).resolve().parents[2] / "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)
from sandbox_reference_compare import compare_pixels


def test_identical_reference_is_zero_error():
    image = Image.new("RGB", (8, 9), (40, 100, 200))
    mae, mismatch, diff = compare_pixels(image, image)
    assert mae == 0.0
    assert mismatch == 0.0
    assert diff.getbbox() is None


def test_offset_crop_compares_unscaled_game_pixels():
    reference = Image.new("RGB", (20, 20), (0, 0, 0))
    sprite = Image.new("RGB", (5, 4), (23, 66, 90))
    reference.paste(sprite, (7, 8))
    mae, mismatch, diff = compare_pixels(reference, sprite, 7, 8)
    assert mae == 0.0 and mismatch == 0.0
    wrong, pixels, _ = compare_pixels(reference, sprite, 0, 0)
    assert wrong > 0.0 and pixels == 100.0
    with pytest.raises(ValueError):
        compare_pixels(reference, sprite, 18, 18)
    with pytest.raises(ValueError):
        compare_pixels(reference, sprite, -1, 0)


def test_tolerance_and_numeric_difference_are_explicit():
    a=Image.new("RGB",(2,1),(20,30,40))
    b=Image.new("RGB",(2,1),(20,30,40))
    b.putpixel((1,0),(30,30,40))
    mae,pct,diff=compare_pixels(a,b,tolerance=8)
    assert mae==pytest.approx(10/6)
    assert pct==50.0
    assert diff.getpixel((1,0))==(10,0,0)
    assert compare_pixels(a,b,tolerance=10)[1]==0.0


def test_comparison_dialog_uses_actual_viewport_pixels(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QGraphicsView, QGraphicsScene
    from sandbox_reference_compare import ReferenceComparisonDialog
    app = QApplication.instance() or QApplication([])
    view = QGraphicsView()
    scene = QGraphicsScene()
    scene.setSceneRect(0, 0, 110, 90)
    view.setScene(scene)
    view.resize(140, 120)
    view.show()
    app.processEvents()
    dialog = ReferenceComparisonDialog(view)
    try:
        assert dialog.candidate is not None
        dialog.reference = dialog.candidate.copy()
        dialog.update_comparison()
        assert dialog.last_difference is not None
        assert dialog.last_difference.getbbox() is None
        assert "MAE 0.000" in dialog.status.text()
    finally:
        dialog.close()
        view.close()

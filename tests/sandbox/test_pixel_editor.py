"""Integrated pixel editor: only the isolated working copy is ever written."""
import json
import sys
from pathlib import Path
from PIL import Image
import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPointF
TOOLS=str(Path(__file__).resolve().parents[2]/"tools")
if TOOLS not in sys.path:
    sys.path.insert(0,TOOLS)
import sandbox_pixel_editor as editor


@pytest.fixture
def fake_assets(tmp_path,monkeypatch):
    original=tmp_path/"geliefert"/"tile_land8"
    work=tmp_path/"arbeit"/"tile_land8"
    original.mkdir(parents=True)
    img=Image.new("RGBA",(8,8),(70,100,120,255))
    img.save(original/"tile_land8-1.png")
    source={"frames":[{"name":"tile_land8-1","file":"tile_land8-1.png",
                       "width":8,"height":8,"pivot_x":0.5,"pivot_y":0.5}]}
    (original/"index.json").write_text(json.dumps(source),encoding="utf-8")
    monkeypatch.setattr(editor.katalog,"work_dir",lambda g:work)
    monkeypatch.setattr(editor.katalog,"side_dir",lambda side,g: original if side=="geliefert" else tmp_path/"crusader"/g)
    monkeypatch.setattr(editor.katalog,"native_name",lambda group,n:f"{group}-{n}")
    return original,work,img


def test_workcopy_created_atomically_without_changing_delivered(fake_assets):
    original,work,img=fake_assets
    path,name=editor.editable_frame("tile_land8",1)
    assert name=="tile_land8-1"
    assert path == work/"tile_land8-1.png"
    assert Image.open(path).getpixel((0,0))==(70,100,120,255)
    assert (original/"tile_land8-1.png").read_bytes()==path.read_bytes()
    assert len(json.loads((work/"index.json").read_text())["frames"])==1
    again,_=editor.editable_frame("tile_land8",1)
    assert again==path


def test_live_pixel_edit_save_and_undo(fake_assets, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM","offscreen")
    app=QApplication.instance() or QApplication([])
    original,work,img=fake_assets
    class FakeFrame:
        image=img
    class FakeSource:
        def __init__(self,*a,**kw):pass
        def frame(self,g,n):return FakeFrame()
    monkeypatch.setattr(editor,"FrameSource",FakeSource)
    dialog=editor.SpritePixelEditor("tile_land8",1)
    try:
        before=dialog.pixel.image.getpixel((0,0))
        signals=[]
        dialog.saved_frame.connect(lambda g,n: signals.append((g,n)))
        dialog.pixel.color=(255,0,77,255)
        dialog.pixel._apply(QPointF(1.0,1.0))
        dialog.pixel.stroke_completed.emit()
        assert dialog.pixel.image.getpixel((0,0)) != before
        dialog.undo()
        assert dialog.pixel.image.getpixel((0,0)) == before
        dialog.redo()
        assert dialog.pixel.image.getpixel((0,0))==(255,0,77,255)
        assert dialog.save()
        assert signals==[("tile_land8",1)]
        assert Image.open(work/"tile_land8-1.png").getpixel((0,0))==(255,0,77,255)
        assert Image.open(original/"tile_land8-1.png").getpixel((0,0))==before
        assert dialog._saved.tobytes()==dialog.pixel.image.tobytes()
    finally:
        dialog.close()


def test_bucket_fill_and_eyedropper(fake_assets,monkeypatch):
    from PySide6.QtWidgets import QApplication
    app=QApplication.instance() or QApplication([])
    w=editor.PixelImage()
    w.set_image(Image.new("RGBA",(3,3),(10,20,30,255)))
    picked=[]
    w.picked.connect(picked.append)
    w.mode="Pipette"
    w._apply(QPointF(1,1))
    assert picked==[(10,20,30,255)]
    w.mode="Füllen"
    w.color=(120,130,140,255)
    w._apply(QPointF(1,1))
    assert w.image.getpixel((2,2))==(120,130,140,255)


def test_mouse_stroke_is_continuous_and_has_one_undo_step(fake_assets, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt, QPoint
    app = QApplication.instance() or QApplication([])
    _, _, image = fake_assets
    class Frame:
        image = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    class Source:
        def __init__(self, *args, **kwargs): pass
        def frame(self, *args): return Frame()
    monkeypatch.setattr(editor, "FrameSource", Source)
    dialog = editor.SpritePixelEditor("tile_land8", 1)
    widget = dialog.pixel
    dialog.show()
    app.processEvents()
    try:
        widget.mode = "Stift"
        widget.color = (255, 70, 23, 255)
        QTest.mousePress(widget, Qt.MouseButton.LeftButton, pos=QPoint(2, 2))
        QTest.mouseMove(widget, QPoint(6 * widget.zoom + 2, 2))
        QTest.mouseRelease(widget, Qt.MouseButton.LeftButton,
                           pos=QPoint(6 * widget.zoom + 2, 2))
        app.processEvents()
        assert [widget.image.getpixel((x, 0)) for x in range(7)] == [
            widget.color for _ in range(7)
        ]
        assert len(dialog._history) == 2
        dialog.undo()
        assert widget.image.getpixel((3, 0)) == (0, 0, 0, 0)
        dialog.redo()
        assert widget.image.getpixel((3, 0)) == widget.color

        widget.mode = "Füllen"
        widget.color = (0, 170, 255, 255)
        QTest.mouseClick(widget, Qt.MouseButton.LeftButton,
                         pos=QPoint(widget.zoom + 1, widget.zoom + 1))
        app.processEvents()
        assert len(dialog._history) == 3  # one flood fill, not two
        assert widget.image.getpixel((7, 7)) == widget.color
    finally:
        # Deliberately close without letting the unsaved-change prompt block CI.
        dialog._saved = widget.image.copy()
        dialog.close()


def test_even_brush_size_paints_correct_square(fake_assets, monkeypatch):
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    pixel = editor.PixelImage()
    pixel.set_image(Image.new("RGBA", (8, 8), (0, 0, 0, 0)))
    pixel.brush = 2
    pixel.mode = "Stift"
    pixel.color = (10, 20, 30, 255)
    pixel._paint_pixel(3, 3)
    assert sum(1 for alpha in pixel.image.tobytes()[3::4] if alpha) == 4

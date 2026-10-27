"""Integrated Sandbox Pixeleditor: actual mouse strokes, undo/save, discard guard.

All inputs and outputs are TEST TEMPORARY files. The installed game,
project catalogue, sprites and active original-map assets are never written.
"""
from pathlib import Path
import hashlib,sys
from PIL import Image
import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import Qt,QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QMessageBox

ROOT=Path(__file__).resolve().parents[2]
if str(ROOT/"tools") not in sys.path:sys.path.insert(0,str(ROOT/"tools"))

from sandbox_studio import SandboxStudio
import sandbox_pixel_editor as editor


@pytest.fixture
def studio_pixel(tmp_path,monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM","offscreen")
    monkeypatch.setenv("SEDE_SPRACHE","de")
    app=QApplication.instance() or QApplication([])
    studio=SandboxStudio(tmp_path)
    studio.resize(1168,542)
    studio.show()
    studio.show_test_field()
    app.processEvents()
    source=tmp_path/"immutable-source.png"
    Image.new("RGBA",(12,12),(60,90,120,255)).save(source)
    original=hashlib.sha256(source.read_bytes()).hexdigest()
    working=tmp_path/"only-working-frame.png"
    class Frame:
        def __init__(self):
            self.image=Image.open(source).copy()
    class Source:
        def __init__(self,*args,**kwargs):pass
        def frame(self,*args):return Frame()
    monkeypatch.setattr(editor,"FrameSource",Source)
    monkeypatch.setattr(
        editor,"editable_frame",
        lambda group,number:(working,f"{group}-{number}")
    )
    updated=[]
    monkeypatch.setattr(studio,"_pixel_changed",
                        lambda group,number:updated.append((group,number)))
    studio.asset_preview.group.setCurrentText("tile_land8")
    studio.asset_preview.frame.setValue(15)
    try:
        yield app,studio,source,working,original,updated
    finally:
        for dialog in list(studio._pixel_dialogs):
            dialog._saved=dialog.pixel.image.copy()
            dialog.close()
        studio.native_canvas._poll.stop()
        studio.board._asset_poll.stop()
        studio.asset_preview.timer.stop()
        studio._saved_scene=studio.board.history.scene.serialize()
        studio.close()
        app.processEvents()


def test_pixel_dialog_from_live_testfield_only_saves_working_copy(studio_pixel,monkeypatch):
    app,studio,source,working,original,updated=studio_pixel
    current_scene=studio.board.history.scene.serialize()
    assert studio.open_pixel_editor()
    app.processEvents()
    assert len(studio._pixel_dialogs)==1
    dialog=studio._pixel_dialogs[0]
    assert dialog.isVisible()
    assert (dialog.group,dialog.number)==("tile_land8",15)
    old=dialog.pixel.image.tobytes()

    # The user changes a REAL Qt pixel, not calling the data helper.
    dialog.pixel.color=(243,40,100,255)
    QTest.mouseClick(dialog.pixel,Qt.MouseButton.LeftButton,pos=QPoint(2,2))
    app.processEvents()
    assert dialog.pixel.image.tobytes()!=old
    assert dialog.pixel.image.getpixel((0,0))==dialog.pixel.color
    dialog.undo_button.click()
    assert dialog.pixel.image.tobytes()==old
    dialog.redo_button.click()
    assert dialog.pixel.image.getpixel((0,0))==dialog.pixel.color
    dialog.save_button.click()
    app.processEvents()
    assert working.is_file()
    assert Image.open(working).getpixel((0,0))==dialog.pixel.color
    assert updated==[("tile_land8",15)]
    assert hashlib.sha256(source.read_bytes()).hexdigest()==original
    assert studio.board.history.scene.serialize()==current_scene
    assert dialog._saved.tobytes()==dialog.pixel.image.tobytes()

    # New unsaved change => close MUST be cancellable without touching file.
    bytes_saved=working.read_bytes()
    dialog.pixel.color=(10,222,10,255)
    QTest.mouseClick(dialog.pixel,Qt.MouseButton.LeftButton,pos=QPoint(
        dialog.pixel.zoom*3+2,dialog.pixel.zoom*3+2
    ))
    assert dialog.pixel.image.tobytes()!=dialog._saved.tobytes()
    asked=[]
    def decline(*args,**kwargs):
        asked.append("Cancel")
        return QMessageBox.StandardButton.Cancel
    monkeypatch.setattr(QMessageBox,"question",decline)
    assert not dialog.close()
    assert asked==["Cancel"]
    assert dialog in studio._pixel_dialogs
    assert working.read_bytes()==bytes_saved

    monkeypatch.setattr(QMessageBox,"question",
                        lambda *args,**kwargs:QMessageBox.StandardButton.Yes)
    assert dialog.close()
    app.processEvents()
    assert dialog not in studio._pixel_dialogs
    assert working.read_bytes()==bytes_saved
    assert hashlib.sha256(source.read_bytes()).hexdigest()==original


def test_pixel_dialog_is_not_implicitly_saved_when_switching_from_testfield(
    studio_pixel,monkeypatch
):
    app,studio,source,working,original,updated=studio_pixel
    assert studio.open_pixel_editor()
    dialog=studio._pixel_dialogs[0]
    assert dialog.isVisible()
    dialog.pixel.color=(255,40,90,255)
    QTest.mouseClick(dialog.pixel,Qt.MouseButton.LeftButton,pos=QPoint(2,2))
    studio.tabs.setCurrentIndex(0)
    app.processEvents()
    assert dialog.pixel.image.tobytes()!=dialog._saved.tobytes()
    assert not working.exists()
    assert hashlib.sha256(source.read_bytes()).hexdigest()==original
    monkeypatch.setattr(QMessageBox,"question",
                        lambda *args,**kwargs:QMessageBox.StandardButton.Yes)
    assert dialog.close()
    assert not working.exists()

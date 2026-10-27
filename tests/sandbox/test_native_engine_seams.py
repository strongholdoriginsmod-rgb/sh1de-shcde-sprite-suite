"""Engine map sprite composition is continuous across former 512x256 boundaries.

Regression against the actual native Antigua/Antioch read-only map, not a
mocked terrain texture. The approximate mode intentionally retains chunk cache.
"""
from __future__ import annotations
from pathlib import Path
import sys

import numpy as np
import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPixmap, QPainter
from PySide6.QtWidgets import QApplication

ROOT=Path(__file__).resolve().parents[2]
TOOLS=str(ROOT/"tools")
if TOOLS not in sys.path:sys.path.insert(0,TOOLS)
from sandbox_native_canvas import NativeMapCanvas, CHUNK_W,CHUNK_H
from sandbox_studio import SandboxStudio

MAP=Path(
    "E:/SSGameQA/Stronghold Crusader Definitive Edition_Data/"
    "StreamingAssets/Maps/Antioch.map"
)


def _image(pixmap):
    image=pixmap.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    return np.frombuffer(bytes(image.bits()),dtype=np.uint8).copy().reshape(
        image.height(),image.width(),4
    )


@pytest.mark.skipif(not MAP.is_file(),reason="Installed SHCDE map unavailable")
def test_512x256_seam_is_absent_when_original_engine_drawing_is_continuous(monkeypatch,tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM","offscreen")
    app=QApplication.instance() or QApplication([])
    studio=SandboxStudio(tmp_path)
    try:
        assert studio.open_map(MAP)
        canvas=studio.native_canvas
        canvas.use_engine_commands=True
        canvas.use_original_runtime_assets=True
        canvas.runtime_renderer.assets.original_only=True
        assert canvas.engine_active()
        canvas.resetTransform()
        x,y,W,H=12800,6400,CHUNK_W*2,CHUNK_H*2
        rect=QRectF(x,y,W,H)
        def paint(style):
            result=QPixmap(W,H)
            result.fill(Qt.GlobalColor.transparent)
            painter=QPainter(result)
            painter.translate(-x,-y)
            painter.fillRect(rect,QColor("#122019"))
            if style=="canvas":
                canvas.drawBackground(painter,rect)
            else:
                canvas.runtime_renderer.draw_area(painter,rect)
            painter.end()
            return _image(result)
        original_cache=set(canvas._terrain_chunks)
        direct=paint("direct")
        view=paint("canvas")
        assert np.array_equal(view,direct),int(np.any(view!=direct,axis=2).sum())
        assert set(canvas._terrain_chunks)==original_cache
        # The old precomposited 512x256 tile path had 1,954 visually
        # different pixels at the y=256 boundary in this exact area.
    finally:
        studio.native_canvas._poll.stop()
        studio._saved_scene=studio.board.history.scene.serialize()
        if studio.native_canvas.has_map():
            studio._saved_overlay=studio.native_canvas.history.overlay.serialize()
        studio.close()


def test_approximation_mode_still_has_bounded_cache(monkeypatch,tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM","offscreen")
    app=QApplication.instance() or QApplication([])
    canvas=NativeMapCanvas()
    from types import SimpleNamespace
    try:
        canvas.history=SimpleNamespace(overlay=SimpleNamespace(objects=[]))
        canvas._channels=SimpleNamespace(channels={3005:bytes(320800)},at=lambda x,y:{3005:8})
        canvas._base=QPixmap(800,800)
        canvas.use_engine_commands=False
        canvas.runtime_renderer=None
        canvas.resetTransform()
        calls=[]
        canvas._terrain_chunk=lambda x,y:calls.append((x,y)) or QPixmap(CHUNK_W,CHUNK_H)
        pic=QPixmap(1024,512);pic.fill(Qt.GlobalColor.transparent)
        painter=QPainter(pic)
        painter.translate(-12800,-6400)
        canvas.drawBackground(painter,QRectF(12800,6400,1024,512))
        painter.end()
        assert calls==[(25,25),(26,25),(25,26),(26,26)]
    finally:
        canvas._poll.stop()
        canvas.close()

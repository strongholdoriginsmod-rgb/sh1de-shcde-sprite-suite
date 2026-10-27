"""Integrated per-frame pixel editor for Sprite Suite working copies.

Edits ONLY work/katalog/arbeit, never original game files or delivered bundles.
Available controls: paint, erase, eyedropper, bucket fill, brush size, zoom,
undo/redo, save and immediate in-map reload.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import os
from PIL import Image
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QImage, QPixmap, QPainter, QBrush
from PySide6.QtWidgets import (
    QDialog, QWidget, QLabel, QPushButton, QScrollArea, QHBoxLayout, QVBoxLayout,
    QComboBox, QColorDialog, QSpinBox, QMessageBox,
)
import asset_katalog as katalog
from sandkasten import FrameSource

MAX_PIXEL_AREA = 2048 * 2048


def editable_frame(group: str, number: int) -> tuple[Path, str]:
    """Create a minimal editable work-copy entry from a known local export."""
    if not group.replace("_", "").replace("-", "").isalnum() or not 0 <= number <= 999999:
        raise ValueError("Ungültige Gruppe oder Framenummer")
    name = katalog.native_name(group, number)
    dest = katalog.work_dir(group)
    index_file = dest / "index.json"
    if index_file.is_file():
        meta = katalog.index_of(dest)
        existing = next((x for x in meta.get("frames", []) if x.get("name") == name), None)
        if existing and (dest / existing["file"]).is_file():
            return dest / existing["file"], name
    else:
        meta = {"schema_version": 1, "group": group, "game": "arbeit",
                "quelle": "lokale Sprite-Suite-Extraktion", "frames": []}
    original = None
    original_dir = None
    for side in ("crusader", "geliefert"):
        location = katalog.side_dir(side, group)
        if not (location / "index.json").exists():
            try:
                katalog.ensure_side(group, side)
            except (SystemExit, OSError, Exception):
                pass
        if not (location / "index.json").is_file():
            continue
        found = katalog.frame_entry(location, name)
        if found is not None and (location / found["file"]).is_file():
            original, original_dir = dict(found), location
            break
    if original is None:
        raise FileNotFoundError(f"Kein Quellbild für {group}/{name} im Atlas")
    dest.mkdir(parents=True, exist_ok=True)
    # Copy only selected source files; keep every unrelated work frame intact.
    for key in ("file", "mask_file"):
        if original.get(key):
            shutil.copy2(original_dir / original[key], dest / original[key])
    original["name"] = name
    meta["frames"] = [f for f in meta.get("frames", []) if f.get("name") != name] + [original]
    # Atomic index replacement: a process crash cannot truncate index.json.
    data = json.dumps(meta, indent=2, ensure_ascii=False) + "\n"
    fd, tmp = tempfile.mkstemp(dir=dest, suffix=".tmp", prefix=".index-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, index_file)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return dest / original["file"], name


class PixelImage(QWidget):
    stroke_completed = Signal()
    picked = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.image = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
        self.zoom = 6
        self.mode = "Stift"
        self.color = (245, 152, 77, 255)
        self.brush = 1
        self._drawing = False
        self._changed = False
        self._last_pixel = None
        # A tiled brush avoids painting tens of thousands of tiny rectangles
        # on every redraw of a zoomed sprite (especially at 24x zoom).
        checker = QPixmap(16, 16)
        checker.fill(QColor("#2c3035"))
        pen = QPainter(checker)
        pen.fillRect(8, 0, 8, 8, QColor("#454a50"))
        pen.fillRect(0, 8, 8, 8, QColor("#454a50"))
        pen.end()
        self._checker = QBrush(checker)
        self.setMouseTracking(True)

    def set_image(self, image):
        self.image = image.copy().convert("RGBA")
        self._size()
        self.update()

    def _size(self):
        self.setFixedSize(self.image.width * self.zoom, self.image.height * self.zoom)

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), self._checker)
        rgba = self.image.tobytes()
        qt = QImage(rgba, self.image.width, self.image.height,
                    self.image.width * 4, QImage.Format.Format_RGBA8888).copy()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        p.drawImage(self.rect(), qt)

    def _pixel(self, pos):
        x, y = int(pos.x() / self.zoom), int(pos.y() / self.zoom)
        return x, y

    def _paint_pixel(self, x, y):
        if not (0 <= x < self.image.width and 0 <= y < self.image.height):
            return
        from PIL import ImageDraw
        color = (0, 0, 0, 0) if self.mode == "Radierer" else self.color
        left = (self.brush - 1) // 2
        right = self.brush // 2
        box = (x - left, y - left, x + right, y + right)
        ImageDraw.Draw(self.image).rectangle(box, fill=color)
        self._changed = True

    def _apply(self, pos):
        """Single-point operation, also exposed to programmatic editor tests."""
        x, y = self._pixel(pos)
        if not 0 <= x < self.image.width or not 0 <= y < self.image.height:
            return
        if self.mode == "Pipette":
            self.picked.emit(self.image.getpixel((x, y)))
            return
        if self.mode == "Füllen":
            previous = self.image.getpixel((x, y))
            if previous != self.color:
                from PIL import ImageDraw
                ImageDraw.floodfill(self.image, (x, y), self.color, thresh=0)
                self._changed = True
                self.update()
            return
        self._paint_pixel(x, y)
        self.update()

    def _stroke_between(self, start, end):
        """Rasterize a full continuous stroke, even across sparse mouse events."""
        x0, y0 = start
        x1, y1 = end
        dx, dy = abs(x1-x0), abs(y1-y0)
        sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
        err = dx - dy
        while True:
            self._paint_pixel(x0, y0)
            if x0 == x1 and y0 == y1:
                break
            double_error = 2 * err
            if double_error > -dy:
                err -= dy
                x0 += sx
            if double_error < dx:
                err += dx
                y0 += sy
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drawing = True
            self._changed = False
            self._last_pixel = self._pixel(event.position())
            self._apply(event.position())
            if self.mode in ("Füllen", "Pipette"):
                self._drawing = False
                self._last_pixel = None
                self._finish_stroke()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drawing and self.mode in ("Stift", "Radierer"):
            current = self._pixel(event.position())
            if self._last_pixel is not None:
                self._stroke_between(self._last_pixel, current)
            self._last_pixel = current
            event.accept()
            return
        super().mouseMoveEvent(event)

    def _finish_stroke(self):
        if self._changed:
            self._changed = False
            self.stroke_completed.emit()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # Flood fill commits on mousePressEvent; do not add it twice
            # when the matching release event eventually arrives.
            if self._drawing:
                self._drawing = False
                self._last_pixel = None
                self._finish_stroke()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class SpritePixelEditor(QDialog):
    saved_frame = Signal(str, int)
    closed = Signal()
    def __init__(self, group: str, number: int, parent=None):
        super().__init__(parent)
        self.group, self.number = group, number
        self.setWindowTitle(f"Sprite-Pixeleditor – {group} / Frame {number}")
        self.resize(950, 680)
        self.path = None
        self._history = []
        self._future = []
        self._initial = None
        self._saved = None

        outer = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        self.mode = QComboBox()
        self.mode.addItems(("Stift", "Radierer", "Pipette", "Füllen"))
        toolbar.addWidget(self.mode)
        self.color_button = QPushButton("Farbe …")
        toolbar.addWidget(self.color_button)
        toolbar.addWidget(QLabel("Pinsel"))
        self.brush = QSpinBox()
        self.brush.setRange(1, 16)
        toolbar.addWidget(self.brush)
        toolbar.addWidget(QLabel("Zoom"))
        self.zoom = QSpinBox()
        self.zoom.setRange(1, 24)
        self.zoom.setValue(8)
        toolbar.addWidget(self.zoom)
        self.undo_button = QPushButton("↶ Undo")
        self.redo_button = QPushButton("↷ Redo")
        toolbar.addWidget(self.undo_button)
        toolbar.addWidget(self.redo_button)
        outer.addLayout(toolbar)
        self.pixel = PixelImage(self)
        scroller = QScrollArea(self)
        scroller.setWidget(self.pixel)
        scroller.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(scroller, 1)
        footer = QHBoxLayout()
        self.status = QLabel("Änderungen werden nur in Sprite Suite gespeichert.")
        footer.addWidget(self.status, 1)
        self.save_button = QPushButton("PNG speichern + Karte aktualisieren")
        self.cancel_button = QPushButton("Schließen")
        footer.addWidget(self.save_button)
        footer.addWidget(self.cancel_button)
        outer.addLayout(footer)
        self.mode.currentTextChanged.connect(lambda m: setattr(self.pixel, "mode", m))
        self.brush.valueChanged.connect(lambda n: setattr(self.pixel, "brush", n))
        self.zoom.valueChanged.connect(self._zoom)
        self.color_button.clicked.connect(self._color)
        self.pixel.picked.connect(self._picked)
        self.pixel.stroke_completed.connect(self._changed)
        self.undo_button.clicked.connect(self.undo)
        self.redo_button.clicked.connect(self.redo)
        self.save_button.clicked.connect(self.save)
        self.cancel_button.clicked.connect(self.close)
        self._load()

    def _load(self):
        # Opening an image starts in memory. Work-copy initialization happens
        # only on save, so cancellation doesn't create unrelated project files.
        frame = FrameSource("arbeit", log=lambda _: None).frame(
            self.group, katalog.native_name(self.group, self.number)
        )
        if frame is None:
            raise FileNotFoundError(f"Frame {self.group}/{self.number} fehlt")
        if frame.image.width * frame.image.height > MAX_PIXEL_AREA:
            raise ValueError("Bild zu groß für den interaktiven Pixeleditor")
        self.pixel.set_image(frame.image)
        self._initial = frame.image.copy()
        self._saved = frame.image.copy()
        self.pixel.zoom = self.zoom.value()
        self.pixel._size()
        self._history = [frame.image.copy()]

    def _zoom(self, value):
        self.pixel.zoom = value
        self.pixel._size()
        self.pixel.update()

    def _color(self):
        base = self.pixel.color
        color = QColorDialog.getColor(QColor(*base), self, "Pixelfarbe auswählen",
                                       QColorDialog.ColorDialogOption.ShowAlphaChannel)
        if color.isValid():
            self._picked((color.red(), color.green(), color.blue(), color.alpha()))

    def _picked(self, rgba):
        self.pixel.color = tuple(rgba)
        self.color_button.setText("#%02X%02X%02X · α%d" % tuple(rgba))

    def _changed(self):
        self._history.append(self.pixel.image.copy())
        self._history = self._history[-40:]
        self._future.clear()
        self.status.setText("Ungespeicherte Pixeländerungen.")

    def undo(self):
        if len(self._history) > 1:
            self._future.append(self._history.pop())
            self.pixel.set_image(self._history[-1])

    def redo(self):
        if self._future:
            restored = self._future.pop()
            self._history.append(restored)
            self.pixel.set_image(restored)

    def save(self):
        try:
            path, _name = editable_frame(self.group, self.number)
            image = self.pixel.image
            fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".sprite-", suffix=".png")
            os.close(fd)
            try:
                image.save(temp, format="PNG")
                os.replace(temp, path)
            finally:
                if os.path.exists(temp):
                    os.unlink(temp)
        except (ValueError, FileNotFoundError, OSError, SystemExit) as exc:
            QMessageBox.warning(self, "PNG konnte nicht gespeichert werden", str(exc))
            return False
        self.path = path
        self._saved = self.pixel.image.copy()
        self.saved_frame.emit(self.group, self.number)
        self.status.setText(f"Gespeichert: {path}")
        return True

    def closeEvent(self, event):
        if self._saved is not None and self.pixel.image.tobytes() != self._saved.tobytes():
            decision = QMessageBox.question(
                self, "Ungespeicherte Pixel",
                "Die Pixeländerungen wurden noch nicht gespeichert. Verwerfen?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel
            )
            if decision != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        event.accept()
        self.closed.emit()

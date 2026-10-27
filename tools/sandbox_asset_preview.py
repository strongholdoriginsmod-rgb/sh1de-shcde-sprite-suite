"""Sprite preview: delivered/original versus editable work copy.

This dock uses Sprite Suite's existing FrameSource and never writes original
game data. Refresh reacts to saved work-copy PNG and index modifications.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel,
    QPushButton, QSpinBox, QVBoxLayout, QWidget, QSizePolicy,
)

import asset_katalog as katalog
from sandkasten import FrameSource


def to_pixmap(frame, checkerboard=True):
    if frame is None:
        return QPixmap()
    from PIL import Image, ImageDraw
    image = frame.image.convert("RGBA")
    if not checkerboard:
        qimage = QImage(image.tobytes(), image.width, image.height, image.width * 4,
                        QImage.Format.Format_RGBA8888).copy()
        return QPixmap.fromImage(qimage)
    base = Image.new("RGBA", image.size, (54, 57, 59, 255))
    draw = ImageDraw.Draw(base)
    for y in range(0, image.height, 12):
        for x in range(0, image.width, 12):
            if ((x // 12) + (y // 12)) % 2:
                draw.rectangle((x, y, x + 11, y + 11), fill=(86, 87, 88, 255))
    base.alpha_composite(image)
    rgb = base.convert("RGB")
    qt = QImage(rgb.tobytes(), rgb.width, rgb.height, rgb.width * 3,
                QImage.Format.Format_RGB888).copy()
    return QPixmap.fromImage(qt)


class AssetPreview(QWidget):
    asset_updated = Signal(str, str)
    def __init__(self, parent=None):
        super().__init__(parent)
        self._signature = None
        self._last_selection = None
        self.setMaximumWidth(420)
        outer = QVBoxLayout(self)
        outer.addWidget(QLabel("Original / Arbeitskopie – direkter Grafiktest"))
        fields = QFormLayout()
        self.group = QComboBox()
        self.group.setObjectName("sandbox_asset_group")
        self.group.setEditable(True)
        self.group.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        groups = katalog.known_groups()
        self.group.addItems(groups)
        if "body_archer" in groups:
            self.group.setCurrentText("body_archer")
        self.frame = QSpinBox()
        self.frame.setObjectName("sandbox_asset_frame")
        self.frame.setRange(0, 999999)
        self.bc7 = QCheckBox("BC7-Verlust simulieren")
        fields.addRow("Gruppe:", self.group)
        fields.addRow("Frame:", self.frame)
        fields.addRow(self.bc7)
        outer.addLayout(fields)
        self.reload = QPushButton("Grafik laden / aktualisieren")
        self.reload.clicked.connect(self.refresh)
        outer.addWidget(self.reload)

        sides = QHBoxLayout()
        self.original = QLabel("Crusader")
        self.work = QLabel("Bearbeitet")
        self.original_caption = QLabel("Original (Quelle wird ermittelt)")
        self.work_caption = QLabel("Arbeitskopie (Quelle wird ermittelt)")
        for caption, label in [(self.original_caption, self.original), (self.work_caption, self.work)]:
            panel = QVBoxLayout()
            caption.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            caption.setWordWrap(True)
            caption.setMaximumWidth(164)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setMinimumSize(96, 164)
            label.setMaximumWidth(164)
            label.setStyleSheet("background:#1b1e21;border:1px solid #626666")
            panel.addWidget(caption)
            panel.addWidget(label, 1)
            sides.addLayout(panel, 1)
        outer.addLayout(sides, 1)
        self.status = QLabel(
            "Zum Laden bitte eine Gruppe und einen Frame wählen. "
            "Automatische Aktualisierung bei geänderten Arbeitskopie-Dateien."
        )
        self.status.setWordWrap(True)
        outer.addWidget(self.status)
        self.timer = QTimer(self)
        self.timer.setInterval(1200)
        self.timer.timeout.connect(self._watch)
        self.timer.start()
        self.group.currentTextChanged.connect(self._selection_changed)
        self.frame.valueChanged.connect(self._selection_changed)
        self.bc7.toggled.connect(self._selection_changed)
        # The historical Sandkasten recomputed the visible pixels as soon
        # as the BC7 checkbox changed; don't leave a stale thumbnail here.
        self.bc7.toggled.connect(self.refresh)

    def _selection_changed(self, *args):
        self._signature = None
        self._last_selection = None
        self.original.setPixmap(QPixmap())
        self.work.setPixmap(QPixmap())
        self.original.setText("Laden …")
        self.work.setText("Laden …")

    def _signature_of(self, group, name):
        base = katalog.work_dir(group)
        result = []
        for path in (base / "index.json", base / f"{name}.png", base / f"{name}_m.png"):
            try:
                stat = path.stat()
                result.append((str(path), stat.st_mtime_ns, stat.st_size))
            except OSError:
                result.append((str(path), None, None))
        return tuple(result)

    def _watch(self):
        if self._last_selection is None:
            return
        group, name = self._last_selection
        if group != self.group.currentText().strip():
            return
        current = self._signature_of(group, name)
        if current != self._signature:
            self.refresh()

    def refresh(self):
        group = self.group.currentText().strip()
        if not group:
            self.status.setText("Bitte eine Asset-Gruppe auswählen.")
            return
        name = katalog.native_name(group, self.frame.value())
        self.status.setText(f"Lade {name} aus der Sprite-Suite-Pipeline …")
        def try_sources(modes):
            errors = []
            for mode in modes:
                if (mode == "crusader" and katalog.target_game_dir() is None
                        and not (katalog.side_dir(mode, group) / "index.json").is_file()):
                    continue
                try:
                    result = FrameSource(mode, bc7=(mode == "arbeit" and self.bc7.isChecked()),
                                         log=lambda _: None).frame(group, name)
                except (Exception, SystemExit) as exc:
                    errors.append(f"{mode}: {exc}")
                    continue
                if result is not None:
                    return result, errors
            return None, errors

        original, original_errors = try_sources(("crusader", "geliefert"))
        edited, work_errors = try_sources(("arbeit", "geliefert"))
        if original is None and edited is None:
            details = "; ".join((original_errors + work_errors)[-3:])
            self.status.setText(f"{name} konnte nicht geladen werden. {details}")
            self._last_selection = None
            return
        for label, sprite in ((self.original, original), (self.work, edited)):
            if sprite is None:
                label.setPixmap(QPixmap())
                label.setText("Kein Frame")
                continue
            pix = to_pixmap(sprite)
            if not pix.isNull():
                label.setPixmap(pix.scaled(152, 160, Qt.AspectRatioMode.KeepAspectRatio,
                                          Qt.TransformationMode.FastTransformation))
        original_state = original.side if original is not None else "fehlt"
        work_state = edited.side if edited is not None else "fehlt"
        self.original_caption.setText(f"Referenz: {original_state}")
        self.work_caption.setText(f"Aktuell: {work_state}")
        self.status.setText(
            f"{name} · Referenz {original_state} → Vorschau {work_state} · "
            f"Änderungen der Arbeitskopie werden automatisch übernommen."
        )
        self._last_selection = (group, name)
        self._signature = self._signature_of(group, name)
        self.asset_updated.emit(group, name)

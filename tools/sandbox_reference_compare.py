"""Reproducible pixel comparisons against user-supplied real-game screenshots.

No resizing or hidden interpolation: image differences are computed in matching
pixel coordinates, and the screenshot remains read-only.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)


def compare_pixels(reference: Image.Image, candidate: Image.Image,
                   offset_x: int = 0, offset_y: int = 0,
                   tolerance: int = 8):
    """Return (MAE, mismatch %, absolute difference image) at native resolution."""
    if not 0 <= tolerance <= 255:
        raise ValueError("Ungültiger Pixeltoleranzwert")
    if offset_x < 0 or offset_y < 0:
        raise ValueError("Negative Bildkoordinaten sind nicht erlaubt")
    if (offset_x + candidate.width > reference.width
            or offset_y + candidate.height > reference.height):
        raise ValueError("Der gewählte Spielbild-Ausschnitt ist zu klein")
    source = np.asarray(
        reference.convert("RGB").crop(
            (offset_x, offset_y, offset_x + candidate.width,
             offset_y + candidate.height)), dtype=np.int16
    )
    sample = np.asarray(candidate.convert("RGB"), dtype=np.int16)
    difference = np.abs(source - sample)
    mae = float(difference.mean())
    mismatch = float(np.any(difference > tolerance, axis=2).mean() * 100.0)
    # Save exact absolute differences in the three original colour channels.
    output = Image.frombytes(
        "RGB", (candidate.width, candidate.height),
        difference.astype(np.uint8).tobytes()
    )
    return mae, mismatch, output


def qt_pixmap_from_pil(image: Image.Image):
    rgba = image.convert("RGBA")
    qimg = QImage(rgba.tobytes(), rgba.width, rgba.height, 4 * rgba.width,
                  QImage.Format.Format_RGBA8888).copy()
    return QPixmap.fromImage(qimg)


def capture_native_view(view):
    pix = view.viewport().grab().toImage().convertToFormat(
        QImage.Format.Format_RGBA8888)
    return Image.frombytes("RGBA", (pix.width(), pix.height()),
                           bytes(pix.bits())).convert("RGB")


class ReferenceComparisonDialog(QDialog):
    def __init__(self, view, parent=None):
        super().__init__(parent)
        self.view = view
        self.reference = None
        self.candidate = None
        self.last_difference = None
        self.setWindowTitle("Spielbild-Abgleich: Pixelgenauigkeit messen")
        self.resize(1030, 760)
        outer = QVBoxLayout(self)
        description = QLabel(
            "Originalen Spiel-Screenshot als PNG/JPG laden. Das Studio vergleicht "
            "Pixel 1:1 mit der aktuellen Kartenansicht – ohne Skalierung. "
            "X/Y wählen den Bildausschnitt innerhalb des Originals."
        )
        description.setWordWrap(True)
        outer.addWidget(description)
        buttons = QHBoxLayout()
        self.load = QPushButton("Spielbild öffnen …")
        self.capture = QPushButton("Kartenansicht neu aufnehmen")
        self.save = QPushButton("Differenzbild als PNG speichern …")
        buttons.addWidget(self.load)
        buttons.addWidget(self.capture)
        buttons.addWidget(self.save)
        outer.addLayout(buttons)
        form = QFormLayout()
        self.x = QSpinBox()
        self.y = QSpinBox()
        self.x.setRange(0, 99999)
        self.y.setRange(0, 99999)
        self.tolerance = QSpinBox()
        self.tolerance.setRange(0, 255)
        self.tolerance.setValue(8)
        form.addRow("Spielbild-Ausschnitt X:", self.x)
        form.addRow("Spielbild-Ausschnitt Y:", self.y)
        form.addRow("Abweichungstoleranz:", self.tolerance)
        outer.addLayout(form)
        images = QHBoxLayout()
        self.reference_label = QLabel("Kein Referenzbild")
        self.diff_label = QLabel("Keine Differenz")
        for label in (self.reference_label, self.diff_label):
            label.setMinimumHeight(300)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet("background:#101418;border:1px solid #777")
            images.addWidget(label, 1)
        outer.addLayout(images, 1)
        self.status = QLabel("Originalkarte und Spiel-Screenshot müssen identische Pixelauflösung besitzen.")
        self.status.setWordWrap(True)
        outer.addWidget(self.status)
        self.load.clicked.connect(self.load_reference)
        self.capture.clicked.connect(self.take_capture)
        self.save.clicked.connect(self.save_difference)
        self.x.valueChanged.connect(self.update_comparison)
        self.y.valueChanged.connect(self.update_comparison)
        self.tolerance.valueChanged.connect(self.update_comparison)
        self.take_capture()

    def take_capture(self):
        self.candidate = capture_native_view(self.view)
        self.update_comparison()

    def load_reference(self):
        file, _ = QFileDialog.getOpenFileName(
            self, "Original-Spielbild laden", str(Path.home()),
            "Bilder (*.png *.jpg *.jpeg *.bmp)"
        )
        if file:
            try:
                with Image.open(file) as image:
                    self.reference = image.convert("RGB")
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, "Spielbild konnte nicht geöffnet werden", str(exc))
                return
            self.x.setValue(0)
            self.y.setValue(0)
            self.update_comparison()

    def update_comparison(self):
        if self.reference is None or self.candidate is None:
            return
        try:
            mae, mismatch, image = compare_pixels(
                self.reference, self.candidate,
                self.x.value(), self.y.value(), self.tolerance.value()
            )
        except ValueError as exc:
            self.status.setText(str(exc))
            self.last_difference = None
            return
        self.last_difference = image
        crop = self.reference.crop(
            (self.x.value(), self.y.value(),
             self.x.value() + self.candidate.width,
             self.y.value() + self.candidate.height)
        )
        for label, picture in [(self.reference_label, crop), (self.diff_label, image)]:
            label.setPixmap(qt_pixmap_from_pil(picture).scaled(
                480, 430, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation
            ))
        self.status.setText(
            f"Abgleich {self.candidate.width}×{self.candidate.height} px; "
            f"MAE {mae:.3f}/255; {mismatch:.2f}% Pixel außerhalb ±{self.tolerance.value()}."
        )

    def save_difference(self):
        if self.last_difference is None:
            QMessageBox.information(self, "Differenzbild", "Zuerst ein passendes Spielbild öffnen.")
            return
        dest, _ = QFileDialog.getSaveFileName(
            self, "Pixel-Differenz exportieren",
            str(Path.home() / "sandbox-differenz.png"), "PNG (*.png)"
        )
        if dest:
            try:
                self.last_difference.save(dest, format="PNG")
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, "Export fehlgeschlagen", str(exc))

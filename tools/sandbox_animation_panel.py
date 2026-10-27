"""Deterministic animation playback of an existing local sprite instance.

Only the QGraphicsPixmapItem preview is changed; project data and Undo history
remain untouched. Animation frame numbers are actual Sprite Suite frame IDs.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QSpinBox, QSlider,
    QVBoxLayout, QWidget,
)


class SpriteAnimationPanel(QWidget):
    def __init__(self, board, parent=None):
        super().__init__(parent)
        self.board = board
        self._ident = None
        self._last_frame = None
        self._playing = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.step_forward)
        outer = QVBoxLayout(self)
        controls = QHBoxLayout()

        self.play = QPushButton("Abspielen")
        self.play.setToolTip("Ausgewähltes Sprite in der Karte animieren")
        self.play.clicked.connect(self.toggle)
        controls.addWidget(self.play)

        self.back = QPushButton("◀")
        self.back.setObjectName("sandbox_animation_previous")
        self.back.clicked.connect(self.step_backward)
        controls.addWidget(self.back)
        self.forward = QPushButton("▶")
        self.forward.setObjectName("sandbox_animation_next")
        self.forward.clicked.connect(self.step_forward)
        controls.addWidget(self.forward)

        controls.addWidget(QLabel("Von"))
        self.start_frame = QSpinBox()
        self.start_frame.setRange(0, 999999)
        controls.addWidget(self.start_frame)
        controls.addWidget(QLabel("Bis"))
        self.end_frame = QSpinBox()
        self.end_frame.setRange(0, 999999)
        self.end_frame.setValue(15)
        controls.addWidget(self.end_frame)

        controls.addWidget(QLabel("FPS"))
        self.fps = QSpinBox()
        self.fps.setRange(1, 30)
        self.fps.setValue(10)
        self.fps.valueChanged.connect(self._update_interval)
        controls.addWidget(self.fps)

        self.reset = QPushButton("Originalframe")
        self.reset.clicked.connect(self.stop)
        controls.addWidget(self.reset)
        outer.addLayout(controls)

        row = QHBoxLayout()
        self.position = QSlider(Qt.Orientation.Horizontal)
        self.position.setRange(0, 15)
        self.position.valueChanged.connect(self._scrub)
        row.addWidget(self.position, 1)
        self.label = QLabel("Kein Testobjekt ausgewählt")
        row.addWidget(self.label)
        outer.addLayout(row)

        self.start_frame.valueChanged.connect(self._range_changed)
        self.end_frame.valueChanged.connect(self._range_changed)
        self.board.selected_id_changed.connect(self._selected)
        self.board.scene_changed.connect(self._scene_rebuilt)
        self._selected(self.board.selected_id() or "")

    def _record(self):
        return next((o for o in self.board.history.scene.objects if o.id == self._ident), None)

    def _selected(self, ident):
        self.stop()
        self._ident = ident or None
        obj = self._record()
        self.play.setEnabled(obj is not None)
        self.back.setEnabled(obj is not None)
        self.forward.setEnabled(obj is not None)
        self.position.setEnabled(obj is not None)
        if obj:
            self.start_frame.blockSignals(True)
            self.end_frame.blockSignals(True)
            self.start_frame.setValue(obj.frame)
            self.end_frame.setValue(min(obj.frame + 15, 999999))
            self.start_frame.blockSignals(False)
            self.end_frame.blockSignals(False)
            # Selecting an object is NOT an animation scrub. Emitting slider
            # valueChanged here would synchronously rebuild the legacy V1
            # graphics scene inside QGraphicsScene.selectionChanged, deleting
            # the active Qt item and causing a native access violation.
            blocked=self.position.blockSignals(True)
            try:
                self.position.setRange(self.start_frame.value(), self.end_frame.value())
                self.position.setValue(obj.frame)
            finally:
                self.position.blockSignals(blocked)
            self.label.setText(f"{obj.group} · Frame {obj.frame}")
        else:
            self.label.setText("Für Animation ein Testobjekt auswählen")

    def _scene_rebuilt(self):
        # Rebuilding the scene destroys sprite QGraphicsItems. Stop playback
        # and avoid dispatching a callback against a stale object identity.
        self._timer.stop()
        self._playing = False
        self.play.setText("Abspielen")
        if self._ident and self._record() is None:
            self._ident = None

    def _range_changed(self):
        lo, hi = self.start_frame.value(), self.end_frame.value()
        if hi < lo:
            self.label.setText("Ungültiger Bereich (Bis < Von)")
            self._timer.stop()
            self._playing = False
            self.play.setText("Abspielen")
            return
        self.position.setRange(lo, hi)
        self.position.setValue(lo)

    def _scrub(self, frame):
        if self._ident is None or not self._record():
            return
        if self.board.preview_object_frame(self._ident, frame):
            self._last_frame = frame
            self.label.setText(f"Frame {frame} · visuelle Vorschau")
        else:
            self.label.setText(f"Frame {frame} nicht verfügbar – keine Änderung")

    def _update_interval(self):
        if self._playing:
            self._timer.setInterval(max(33, round(1000 / self.fps.value())))

    def toggle(self):
        if self._playing:
            self.pause()
        elif self._ident and self._record() and self.end_frame.value() >= self.start_frame.value():
            self._playing = True
            self.play.setText("Pause")
            self._timer.start(max(33, round(1000 / self.fps.value())))

    def pause(self):
        self._playing = False
        self._timer.stop()
        self.play.setText("Abspielen")

    def stop(self):
        self.pause()
        if self._ident:
            self.board.restore_object_frame(self._ident)
        self._last_frame = None

    def step_forward(self):
        if not self._record():
            self.pause()
            return
        lo, hi = self.start_frame.value(), self.end_frame.value()
        if hi < lo:
            self.pause()
            return
        nxt = lo if self.position.value() >= hi else self.position.value() + 1
        self.position.setValue(nxt)

    def step_backward(self):
        if not self._record():
            self.pause()
            return
        lo, hi = self.start_frame.value(), self.end_frame.value()
        if hi < lo:
            return
        previous = hi if self.position.value() <= lo else self.position.value() - 1
        self.position.setValue(previous)

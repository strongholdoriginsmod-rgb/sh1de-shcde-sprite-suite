"""Interactive inspector for the sprite test field, no game-map mutation."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFormLayout, QHBoxLayout, QLabel, QPushButton, QSpinBox,
    QComboBox, QVBoxLayout, QWidget,
)

from stronghold_europe_de.sandbox.scene_model import SceneError, TEAM_COLOURS


class ObjectInspector(QWidget):
    operation_requested = Signal(str)

    def __init__(self, test_board, parent=None):
        super().__init__(parent)
        self.board = test_board
        self._ident = None
        outer = QVBoxLayout(self)
        outer.addWidget(QLabel("Szenenobjekt – Sprite und Position"))
        form = QFormLayout()
        self.group = QLabel("Kein Objekt ausgewählt")
        self.sprite_id = QLabel("–")
        self.x = QSpinBox()
        self.y = QSpinBox()
        self.frame = QSpinBox()
        self.frame.setRange(0, 999999)
        self.team = QComboBox()
        self.team.setObjectName("sandbox_scene_inspector_team")
        # All eight names are inherited from the old Sandkasten renderer.
        # Include "keine" to disable its original TEAM_COLOURS tint.
        for code in (
            "rot", "blau", "gelb", "gruen",
            "orange", "lila", "tuerkis", "grau", "keine",
        ):
            assert code in TEAM_COLOURS
            self.team.addItem(code, code)
        for name, control in [
            ("ID:", self.sprite_id),
            ("Gruppe:", self.group),
            ("X:", self.x), ("Y:", self.y),
            ("Frame:", self.frame),
            ("Team:", self.team),
        ]:
            form.addRow(name, control)
        outer.addLayout(form)
        self.apply = QPushButton("Änderungen übernehmen")
        self.apply.clicked.connect(self.apply_changes)
        outer.addWidget(self.apply)
        self.remove = QPushButton("Ausgewähltes Objekt entfernen")
        self.remove.clicked.connect(self.board.delete_selected)
        outer.addWidget(self.remove)
        self.message = QLabel("Objekte in der isometrischen Testszene anklicken.")
        self.message.setWordWrap(True)
        outer.addWidget(self.message)
        outer.addStretch(1)
        self.board.selected_id_changed.connect(self.show_selection)
        self.board.scene_changed.connect(self.refresh_selection)
        self.show_selection("")

    def refresh_selection(self):
        self.show_selection(self.board.selected_id() or "")

    def show_selection(self, ident):
        obj = next((o for o in self.board.history.scene.objects if o.id == ident), None)
        self._ident = obj.id if obj else None
        self.apply.setEnabled(obj is not None)
        self.remove.setEnabled(obj is not None)
        for field in (self.x, self.y, self.frame, self.team):
            field.setEnabled(obj is not None)
        if obj is None:
            self.group.setText("Kein Objekt ausgewählt")
            self.sprite_id.setText("–")
            return
        self.sprite_id.setText(obj.id[:12])
        self.group.setText(obj.group)
        self.x.setRange(0, self.board.history.scene.width - 1)
        self.y.setRange(0, self.board.history.scene.height - 1)
        self.x.setValue(obj.x)
        self.y.setValue(obj.y)
        self.frame.setValue(obj.frame)
        index = self.team.findData(obj.team)
        if index >= 0:
            self.team.setCurrentIndex(index)

    def apply_changes(self):
        if self._ident is None:
            return
        try:
            self.board.history.update(
                self._ident, x=self.x.value(), y=self.y.value(),
                frame=self.frame.value(), team=self.team.currentData(),
            )
        except SceneError as exc:
            self.message.setText(str(exc))
            return
        self.board.rebuild(focus_id=self._ident)
        self.message.setText("Eigenschaften aktualisiert; Rückgängig ist möglich.")

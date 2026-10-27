"""Navigable real-frame sprite palette for the Sandbox Studio test field."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QSize, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QSpinBox, QVBoxLayout, QWidget,
)
import asset_katalog as katalog
from sandkasten import FrameSource
from sandbox_asset_preview import to_pixmap


class SpritePalette(QWidget):
    frame_selected = Signal(str, int)
    placement_requested = Signal(str, int)
    PAGE_SIZE = 32

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.addWidget(QLabel("Sprite-Palette · echte lokale Atlasframes"))
        self.group = QComboBox()
        self.group.setObjectName("sandbox_palette_group")
        self.group.setEditable(True)
        groups = katalog.known_groups()
        self.group.addItems(groups)
        if "anim_armourer" in groups:
            self.group.setCurrentText("anim_armourer")
        outer.addWidget(self.group)
        paging = QHBoxLayout()
        self.previous = QPushButton("◀ Zurück")
        self.next = QPushButton("Weiter ▶")
        self.page = QSpinBox()
        self.page.setObjectName("sandbox_palette_page")
        self.page.setRange(0, 31249)
        paging.addWidget(self.previous)
        paging.addWidget(self.page)
        paging.addWidget(self.next)
        outer.addLayout(paging)
        self.tiles = QListWidget()
        self.tiles.setViewMode(QListWidget.ViewMode.IconMode)
        self.tiles.setIconSize(QSize(65, 65))
        self.tiles.setGridSize(QSize(90, 92))
        self.tiles.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.tiles.setMovement(QListWidget.Movement.Static)
        self.tiles.setWordWrap(True)
        outer.addWidget(self.tiles, 1)
        self.info = QLabel("Frame anklicken: anzeigen. Doppelklick: platzieren.")
        self.info.setWordWrap(True)
        outer.addWidget(self.info)
        self._source = FrameSource("arbeit", log=lambda _: None)
        self.group.currentTextChanged.connect(self._on_group_changed)
        self.page.valueChanged.connect(self.reload)
        self.previous.clicked.connect(lambda: self.page.setValue(max(0, self.page.value() - 1)))
        self.next.clicked.connect(lambda: self.page.setValue(self.page.value() + 1))
        self.tiles.itemClicked.connect(self._selected)
        self.tiles.itemDoubleClicked.connect(self._place)
        QTimer.singleShot(0, self.reload)

    def _on_group_changed(self):
        if self.page.value():
            self.page.setValue(0)
        else:
            self.reload()

    def reload(self):
        self.tiles.clear()
        group = self.group.currentText().strip()
        if not group:
            return
        self._source = FrameSource("arbeit", log=lambda _: None)
        # Avoid requesting missing frames from FrameSource: its final Crusader
        # fallback may launch a costly export for *each* missing frame when the
        # user's game-mapping configuration has not been installed.
        available = set()
        for side in ("arbeit", "geliefert", "crusader"):
            folder = katalog.work_dir(group) if side == "arbeit" else katalog.side_dir(side, group)
            if (folder / "index.json").is_file():
                available.update(str(entry.get("name")) for entry in
                                 katalog.index_of(folder).get("frames", []))
        if not available:
            try:
                katalog.ensure_side(group, "geliefert")
            except (OSError, Exception, SystemExit):
                pass
            folder = katalog.side_dir("geliefert", group)
            if (folder / "index.json").is_file():
                available.update(str(entry.get("name")) for entry in
                                 katalog.index_of(folder).get("frames", []))
        first = self.page.value() * self.PAGE_SIZE
        shown, missing = 0, 0
        for number in range(first, first + self.PAGE_SIZE):
            try:
                name = katalog.native_name(group, number)
                frame = self._source.frame(group, name) if name in available else None
            except (Exception, SystemExit):
                frame = None
            if frame is None:
                missing += 1
                continue
            shown += 1
            icon = QIcon(to_pixmap(frame))
            entry = QListWidgetItem(icon, str(number))
            entry.setData(Qt.ItemDataRole.UserRole, number)
            entry.setToolTip(f"{group} · {name} · {frame.side}")
            self.tiles.addItem(entry)
        self.info.setText(
            f"{group}: Frames {first}–{first+self.PAGE_SIZE-1}, {shown} vorhanden, "
            f"{missing} nicht vorhanden. Doppelklick platziert."
        )

    def _selected(self, item):
        self.frame_selected.emit(self.group.currentText().strip(),
                                 int(item.data(Qt.ItemDataRole.UserRole)))

    def _place(self, item):
        self.placement_requested.emit(self.group.currentText().strip(),
                                      int(item.data(Qt.ItemDataRole.UserRole)))

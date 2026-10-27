"""Functional in-map HUD for Sprite Suite, backed by real editor actions.

This is a sandbox testing HUD, not a claim of exact Noesis/Unity gameplay UI.
Every displayed action has a real implementation.
"""
from __future__ import annotations
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QWidget, QLabel, QPushButton, QCheckBox, QComboBox, QHBoxLayout,
    QSpinBox, QVBoxLayout, QFrame, QFormLayout, QTabWidget,
)
import asset_katalog as katalog
from stronghold_europe_de.sandbox.scene_model import TEAM_COLOURS


class NativeGameHUD(QWidget):
    save_requested = Signal()
    edit_sprite_requested = Signal(str, int)

    def __init__(self, canvas, parent=None):
        super().__init__(parent)
        self.canvas = canvas
        self._selected = None
        self._playing = False
        self._clock = QTimer(self)
        self._clock.timeout.connect(self._advance)

        self.setStyleSheet("""
            NativeGameHUD { background:#27271f; }
            QPushButton { background:#504938; color:#f8edce; border:1px solid #897958;
                          padding:6px; border-radius:3px; }
            QPushButton:hover { background:#716443; }
            QPushButton:disabled { color:#9d958a; }
            QLabel { color:#efe4ce; }
            QComboBox,QSpinBox { background:#242722; color:#eee3c7; padding:5px; }
        """)
        outer = QVBoxLayout(self)
        top = QHBoxLayout()
        self.map_title = QLabel("Keine Originalkarte geladen")
        self.map_title.setWordWrap(True)
        top.addWidget(self.map_title, 1)
        self.values = QLabel("Kachelwerte: –")
        self.values.setWordWrap(True)
        top.addWidget(self.values, 1)
        self.overlay_count = QLabel("Objekte: 0")
        top.addWidget(self.overlay_count)
        self.engine_mode = QComboBox()
        self.engine_mode.setObjectName("sandbox_hud_engine_mode")
        self.engine_mode.addItems(("Engine + Arbeitsgrafiken", "Engine + Originalgrafiken", "Näherungs-/Testansicht"))
        self.engine_mode.setToolTip(
            "Original-Engine bestimmt Terrain, Höhen und Objektframes. "
            "Arbeitsgrafiken verwendet Sprite-Suite-Änderungen; Originalgrafiken die lokalen Spielsprites."
        )
        self.engine_mode.currentIndexChanged.connect(self.canvas.set_engine_view_mode)
        top.addWidget(self.engine_mode)
        self.show_occupancy = QCheckBox("Objektbelegung 3004")
        self.show_occupancy.setToolTip(
            "Gelbe Diagnose-Markierung für original belegte Kacheln aus Map-Sektion 3004, "
            "keine erfundenen Objektsprites"
        )
        self.show_occupancy.toggled.connect(self.canvas.set_occupancy_overlay)
        top.addWidget(self.show_occupancy)
        outer.addLayout(top)

        actions = QHBoxLayout()
        self.category = QComboBox()
        self.category.setObjectName("sandbox_hud_category")
        for original in ("Gebäude", "Einheiten", "Natur", "Gelände", "Effekte", "Alle"):
            self.category.addItem(original, original)
        actions.addWidget(self.category)
        self.group = QComboBox()
        self.group.setObjectName("sandbox_hud_group")
        self.group.setEditable(True)
        self.group.setMinimumWidth(145)
        actions.addWidget(self.group)
        self.frame = QSpinBox()
        self.frame.setObjectName("sandbox_hud_frame")
        self.frame.setRange(0, 999999)
        actions.addWidget(self.frame)
        self.team = QComboBox()
        self.team.setObjectName("sandbox_native_team_color")
        for colour in (
            "rot", "blau", "gelb", "gruen",
            "orange", "lila", "tuerkis", "grau", "keine"
        ):
            assert colour in TEAM_COLOURS
            self.team.addItem(colour, colour)
        self.team.setAccessibleName("Historische Teamfarbe für Arbeitssprites")
        self.team.setToolTip(
            "Original-Sandkasten: Teamfarbe wird bei maskierten Einheiten/Flaggen "
            "getönt; keine Originalspiel-Wirtschaft."
        )
        self.team.currentIndexChanged.connect(
            lambda _index: self.canvas.set_placement_team(self.team.currentData())
        )
        actions.addWidget(self.team)
        self.place = QPushButton("Auf Karte platzieren")
        self.place.clicked.connect(self._place)
        actions.addWidget(self.place)
        self.delete = QPushButton("Entfernen")
        self.delete.clicked.connect(self.canvas.delete_selected)
        actions.addWidget(self.delete)
        self.undo = QPushButton("↶")
        self.undo.setObjectName("sandbox_game_hud_undo")
        self.undo.setToolTip("Rückgängig")
        self.undo.clicked.connect(self.canvas.undo)
        actions.addWidget(self.undo)
        self.redo = QPushButton("↷")
        self.redo.setObjectName("sandbox_game_hud_redo")
        self.redo.setToolTip("Wiederholen")
        self.redo.clicked.connect(self.canvas.redo)
        actions.addWidget(self.redo)
        self.save = QPushButton("Karte sichern")
        self.save.setToolTip("Eigene Sprite-Ebene als Overlay speichern")
        self.save.clicked.connect(self.save_requested.emit)
        actions.addWidget(self.save)
        outer.addLayout(actions)

        bottom = QHBoxLayout()
        self.show_tiles = QCheckBox("Original-Rohwerte")
        self.show_tiles.toggled.connect(self.canvas.set_diagnostic_only)
        bottom.addWidget(self.show_tiles)
        self.show_buildings = QCheckBox("Originalgebäude")
        self.show_buildings.setChecked(True)
        self.show_buildings.toggled.connect(self.canvas.set_original_buildings_visible)
        bottom.addWidget(self.show_buildings)
        self.show_trees = QCheckBox("Originalvegetation")
        self.show_trees.setChecked(True)
        self.show_trees.toggled.connect(self.canvas.set_original_trees_visible)
        bottom.addWidget(self.show_trees)
        self.open_edit = QPushButton("Sprite-Pixel bearbeiten")
        self.open_edit.clicked.connect(self._edit_sprite)
        bottom.addWidget(self.open_edit)
        self.play = QPushButton("▶ Animieren")
        self.play.clicked.connect(self._toggle)
        bottom.addWidget(self.play)
        self.first = QSpinBox()
        self.first.setRange(0, 999999)
        bottom.addWidget(QLabel("Von"))
        bottom.addWidget(self.first)
        self.last = QSpinBox()
        self.last.setRange(0, 999999)
        self.last.setValue(15)
        bottom.addWidget(QLabel("Bis"))
        bottom.addWidget(self.last)
        self.fps = QSpinBox()
        self.fps.setRange(1, 30)
        self.fps.setValue(10)
        bottom.addWidget(QLabel("FPS"))
        bottom.addWidget(self.fps)
        self.step = QPushButton("Einzelbild")
        self.step.clicked.connect(self._advance)
        bottom.addWidget(self.step)
        self.reset = QPushButton("Reset")
        self.reset.clicked.connect(self._stop)
        bottom.addWidget(self.reset)
        outer.addLayout(bottom)

        self._frame_pointer = 0
        self.category.currentTextChanged.connect(self._populate)
        self.canvas.picked.connect(self._picked)
        self.canvas.original_building_selected.connect(self._original_selected)
        self.canvas.original_tree_selected.connect(self._tree_selected)
        self.canvas.object_selected.connect(self._select)
        self.canvas.modified.connect(self._modified)
        self._populate()

    def configure_compact(self):
        """Reflow every existing functional HUD control for a 275px sidebar.

        The old native HUD used three >1000px HBox layouts. Reparenting
        that unchanged QWidget into a QScrollArea made almost all buttons
        invisible horizontally in the integrated Suite. Preserve widget
        identity and signal wiring while rebuilding just the layout.
        Standalone windows retain the original wide HUD.
        """
        if getattr(self,"_compact",False):
            return
        self._compact=True
        outer=self.layout()
        names=(
            "map_title","values","overlay_count","engine_mode",
            "show_occupancy","category","group","frame","team","place","delete",
            "undo","redo","save","show_tiles","show_buildings","show_trees",
            "open_edit","play","first","last","fps","step","reset",
        )
        retained={getattr(self,name) for name in names}
        while outer.count():
            row=outer.takeAt(0)
            sub=row.layout()
            if sub is None:
                widget=row.widget()
                if widget and widget not in retained:
                    widget.deleteLater()
                continue
            while sub.count():
                item=sub.takeAt(0)
                widget=item.widget()
                if widget is not None:
                    if widget in retained:
                        widget.setParent(None)
                    else:
                        widget.deleteLater()
            sub.deleteLater()

        self.group.setMinimumWidth(0)
        # Text-only buttons had a 254px minimum for "Auf Karte platzieren";
        # a pair of them in one horizontal row forced a 405px HUD inside
        # a 275px inspector. Compact labels keep their long tooltips.
        for control,short in (
            (self.place,"Platzieren"),(self.delete,"Entfernen"),
            (self.save,"Speichern"),(self.open_edit,"Pixel-Editor"),
            (self.play,"Abspielen"),
            (self.show_occupancy,"Objekte 3004"),
            (self.show_tiles,"Rohwerte"),
            (self.show_buildings,"Gebäude"),
            (self.show_trees,"Vegetation"),
        ):
            if not control.toolTip():
                control.setToolTip(control.text())
            control.setText(short)
        self.engine_mode.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.engine_mode.setMinimumContentsLength(9)
        self.engine_mode.setMinimumWidth(0)
        outer.setContentsMargins(5,5,5,5)
        outer.setSpacing(5)
        self.map_title.setMinimumWidth(0)
        self.values.setMinimumWidth(0)
        outer.addWidget(self.map_title)
        outer.addWidget(self.values)
        outer.addWidget(self.overlay_count)
        self.compact_tabs=QTabWidget(self)
        self.compact_tabs.setObjectName("sandbox_hud_compact_tabs")
        self.compact_tabs.setDocumentMode(True)
        outer.addWidget(self.compact_tabs)

        place=QWidget()
        form=QFormLayout(place)
        form.setContentsMargins(5,5,5,5)
        form.setSpacing(5)
        # Labels are above their controls (one column). A two-column
        # QFormLayout still demanded 144 + 210 px for the group selector.
        for label,control in (
            ("Kategorie",self.category),("Grafikgruppe",self.group),
            ("Frame",self.frame),("Teamfarbe",self.team),
        ):
            form.addRow(QLabel(label))
            form.addRow(control)
        form.addRow(self.place)
        form.addRow(self.delete)
        edits=QHBoxLayout()
        edits.addWidget(self.undo)
        edits.addWidget(self.redo)
        edits.addWidget(self.save)
        form.addRow(edits)
        self.compact_tabs.addTab(place,"Platzieren")

        display=QWidget()
        surface=QVBoxLayout(display)
        surface.setContentsMargins(5,5,5,5)
        surface.addWidget(QLabel("Anzeige"))
        surface.addWidget(self.engine_mode)
        surface.addWidget(self.show_occupancy)
        surface.addWidget(self.show_tiles)
        surface.addWidget(self.show_buildings)
        surface.addWidget(self.show_trees)
        surface.addWidget(self.open_edit)
        self.compact_tabs.addTab(display,"Darstellung")

        animation=QWidget()
        anim=QFormLayout(animation)
        anim.setContentsMargins(5,5,5,5)
        anim.addRow("Von",self.first)
        anim.addRow("Bis",self.last)
        anim.addRow("FPS",self.fps)
        anim.addRow(self.play)
        anim.addRow(self.step)
        anim.addRow(self.reset)
        self.compact_tabs.addTab(animation,"Animation")
        self.setMinimumWidth(0)

    def display_map(self, path):
        self.map_title.setText(self._ui_text(
            f"{path.stem}: {len(self.canvas.original_buildings)} Gebäude, "
            f"{len(self.canvas.original_trees)} Bäume, "
            f"{self.canvas.native_geometry.nonpadding_tiles if self.canvas.native_geometry else 0:,} "
            "Kacheln"
        ))
        active = self.canvas.runtime_snapshot is not None
        for index in (0,1):
            item = self.engine_mode.model().item(index)
            if item is not None:
                item.setEnabled(active)
        self.engine_mode.blockSignals(True)
        self.engine_mode.setCurrentIndex(
            1 if active and self.canvas.use_original_runtime_assets else 0 if active else 2)
        self.engine_mode.blockSignals(False)
        self.engine_mode.setToolTip(self.canvas.runtime_description())
        self._modified()

    def _populate(self):
        previous = self.group.currentText()
        names = katalog.known_groups()
        key = self.category.currentData() or self.category.currentText()
        def category(name):
            if key == "Gebäude":
                return name.startswith("tile_") and any(w in name for w in
                       ("buildings", "castle", "walls", "workshops", "churches"))
            if key == "Einheiten":
                return name.startswith(("body_", "anim_"))
            if key == "Natur":
                return name.startswith("tile_") and any(w in name for w in
                       ("land", "rocks", "cliffs", "sea", "farmland"))
            if key == "Gelände":
                return name.startswith("tile_")
            if key == "Effekte":
                return any(w in name for w in ("effect", "flag", "fire", "smoke"))
            return True
        self.group.clear()
        self.group.addItems([name for name in names if category(name)])
        if previous in [self.group.itemText(i) for i in range(self.group.count())]:
            self.group.setCurrentText(previous)

    def _tree_selected(self, tree):
        self.values.setText(
            f"Originalvegetation · Rohgruppe {tree.raw_group} · "
            f"Kachel ({tree.x},{tree.y}) · nur lesen"
        )

    def _original_selected(self, entry):
        self.values.setText(
            f"Originalbauwerk · ID {entry.type_id} · Besitzer {entry.owner} · "
            f"Kachel ({entry.x},{entry.y}) · nur lesen"
        )

    def _picked(self, x, y, values):
        code = values.get(3005)
        self.values.setText(
            f"({x},{y}) · 3003={values.get(3003)} · "
            f"3004={values.get(3004)} · 3005={code}"
        )

    def _ui_text(self, german):
        """Live messages use the selected Qt locale even without a signal.

        The HUD can be reparented into a right-hand QScrollArea in the
        embedded Suite. Its original QWidget.parent() is therefore not the
        Studio; the map canvas .window() still resolves to the editor.
        """
        studio=self.canvas.window()
        translator=getattr(studio,"ui_language",None)
        return translator.translate(german) if translator else german

    def _modified(self):
        n = len(self.canvas.history.overlay.objects) if self.canvas.history else 0
        self.overlay_count.setText(self._ui_text(f"Eigene Objekte: {n}"))
        self._stop()

    def _select(self, ident):
        self._stop()
        self._selected = ident or None
        if self._selected and self.canvas.has_map():
            obj = next((o for o in self.canvas.history.overlay.objects if o.id == ident), None)
            if obj is not None:
                self.group.setCurrentText(obj.group)
                self.frame.setValue(obj.frame)
                colour_index = self.team.findData(obj.team)
                if colour_index >= 0:
                    self.team.setCurrentIndex(colour_index)
                self.first.setValue(obj.frame)
                self.last.setValue(min(obj.frame + 15, 999999))
                self._frame_pointer = obj.frame

    def _place(self):
        return self.canvas.arm_placement(
            self.group.currentText().strip(), self.frame.value(),
            team=self.team.currentData()
        )

    def _edit_sprite(self):
        # The pixel-editor button belongs to this HUD selector, not to the
        # independent last focused inspector or palette widget.
        self.edit_sprite_requested.emit(self.group.currentText().strip(), self.frame.value())

    def _toggle(self):
        if self._playing:
            self._stop(restore=False)
        elif self._selected and self.canvas.has_map() and self.last.value() >= self.first.value():
            self._playing = True
            self.play.setText("❚❚ Pause")
            self._clock.start(max(33, round(1000 / self.fps.value())))

    def _advance(self):
        if not self._selected or not self.canvas.has_map():
            self._stop()
            return
        lo, hi = self.first.value(), self.last.value()
        if hi < lo:
            self._stop()
            return
        self._frame_pointer = lo if self._frame_pointer >= hi else self._frame_pointer + 1
        if not self.canvas.preview_object_frame(self._selected, self._frame_pointer):
            self._stop()

    def _stop(self, restore=True):
        self._playing = False
        self._clock.stop()
        self.play.setText("▶ Animieren")
        if restore and self._selected:
            self.canvas.restore_object_frame(self._selected)

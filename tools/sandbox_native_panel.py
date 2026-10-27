"""Minimap, editing properties, and visible state for the authentic map canvas."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QGraphicsScene, QGraphicsView, QHBoxLayout,
    QLabel, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)
from stronghold_europe_de.sandbox.map_sections import tile_index
from stronghold_europe_de.sandbox.scene_model import SceneError


class NativeMiniMap(QGraphicsView):
    """Original game radar with a live projected camera box and click-to-center."""
    def __init__(self, map_canvas, parent=None):
        super().__init__(parent)
        self.map_canvas = map_canvas
        self.setScene(QGraphicsScene(self))
        self.setMinimumHeight(210)
        self.setMaximumHeight(270)
        self._radar_projection = None
        self._camera_outline = None
        self._radar_pixmap = None
        # PySide may emit camera_changed during QGraphicsView teardown after
        # Qt has deleted this dock. A weak, guarded trampoline prevents calling
        # a deleted QWidget's Python slot (native access violation).
        import weakref
        from shiboken6 import isValid
        target = weakref.ref(self)
        def update_camera():
            view = target()
            if view is not None and isValid(view):
                view.refresh_camera_outline()
        self._camera_callback = update_camera
        self.map_canvas.camera_changed.connect(self._camera_callback)

    def use_map(self, original_radar=None, native_geometry=None):
        self._camera_outline = None
        self._radar_projection = None
        self.scene().clear()
        if original_radar is not None:
            from PySide6.QtGui import QImage
            from stronghold_europe_de.sandbox.radar_projection import RadarProjection
            image = original_radar.convert("RGB")
            self._radar_projection = RadarProjection.from_original_geometry(image, native_geometry)
            qimage = QImage(
                image.tobytes(), image.width, image.height, image.width * 3,
                QImage.Format.Format_RGB888
            ).copy()
            self._radar_pixmap = QPixmap.fromImage(qimage)
        elif self.map_canvas._base is not None:
            self._radar_pixmap = self.map_canvas._base
        else:
            self._radar_pixmap = None
        if self._radar_pixmap:
            self.scene().addPixmap(self._radar_pixmap)
            self.scene().setSceneRect(
                0, 0, self._radar_pixmap.width(), self._radar_pixmap.height()
            )
            self.fitInView(self.scene().sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
            self.refresh_camera_outline()

    @Slot()
    def refresh_camera_outline(self):
        if self._radar_projection is None or not self.map_canvas.has_map():
            return
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QPen, QColor, QPolygonF, QPainterPath
        from PySide6.QtCore import QPointF, QRectF
        from sandbox_native_canvas import TILE_X, TILE_Y
        view = self.map_canvas
        bounds = [
            QPoint(0, 0), QPoint(view.viewport().width(), 0),
            QPoint(view.viewport().width(), view.viewport().height()),
            QPoint(0, view.viewport().height()),
        ]
        points = []
        for corner in bounds:
            pos = view.mapToScene(corner)
            rx, ry = self._radar_projection.native_to_radar(
                pos.x() / TILE_X, pos.y() / TILE_Y
            )
            points.append(QPointF(rx, ry))
        if self._camera_outline is not None:
            self.scene().removeItem(self._camera_outline)
            self._camera_outline = None
        # The camera may see past the playable map (notably Fit Map).
        # Clip its outline against the real radar pixels, otherwise giant
        # off-map diagonals obscure the miniature game map.
        perimeter = QPainterPath()
        perimeter.addPolygon(QPolygonF(points))
        perimeter.closeSubpath()
        visible_radar = QPainterPath()
        bounds = self._radar_projection
        visible_radar.addRect(QRectF(
            bounds.left, bounds.top, bounds.width-1, bounds.height-1
        ))
        clipping = perimeter.intersected(visible_radar)
        if clipping.isEmpty():
            return
        self._camera_outline = self.scene().addPath(
            clipping, QPen(QColor("#fbd06d"), 1.5),
            Qt.BrushStyle.NoBrush
        )
        self._camera_outline.setZValue(100)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._radar_pixmap is not None:
            self.fitInView(self.scene().sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def go_to_radar(self, rx, ry):
        if self._radar_projection is None or not self.map_canvas.has_map():
            return False
        if not self._radar_projection.contains_radar(rx, ry):
            return False
        x, y = self._radar_projection.radar_to_native(rx, ry)
        from stronghold_europe_de.sandbox.map_sections import tile_index
        xi, yi = round(x), round(y)
        if not self.map_canvas.is_editable_native(xi, yi):
            return False
        self.map_canvas.center_native(xi, yi)
        return True

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.map_canvas.has_map():
            pt = self.mapToScene(event.position().toPoint())
            if self._radar_projection is not None:
                self.go_to_radar(pt.x(), pt.y())
            else:
                self.map_canvas.center_native(int(pt.x()), int(pt.y()))
            event.accept()
            return
        super().mousePressEvent(event)


class NativeObjectInspector(QWidget):
    assign_native_visual = Signal()
    clear_native_visual = Signal()
    assign_terrain_test = Signal()
    clear_terrain_test = Signal()
    assign_surface_test = Signal()
    clear_surface_test = Signal()
    edit_engine_tile = Signal(int, int)
    """Selection controls for user-added sprites on a native .map overlay."""
    def __init__(self, canvas, parent=None):
        super().__init__(parent)
        self.canvas = canvas
        self._ident = None
        self._original = None
        self._terrain_code = None
        outer = QVBoxLayout(self)
        intro = QLabel("Echte Originalkarte – Bearbeitung nur im sicheren Overlay")
        intro.setWordWrap(True)
        outer.addWidget(intro)
        fields = QFormLayout()
        self.group = QLabel("Kein Objekt ausgewählt")
        self.x = QSpinBox()
        self.x.setObjectName("sandbox_original_inspector_x")
        self.y = QSpinBox()
        self.y.setObjectName("sandbox_original_inspector_y")
        self.x.setRange(0, 799)
        self.y.setRange(0, 799)
        self.frame = QSpinBox()
        self.frame.setObjectName("sandbox_original_inspector_frame")
        self.frame.setRange(0, 999999)
        self.team = QComboBox()
        self.team.setObjectName("sandbox_original_inspector_team")
        for code in ("rot", "blau", "gruen", "gelb", "keine"):
            self.team.addItem(code, code)
        fields.addRow("Sprite-Gruppe:", self.group)
        fields.addRow("Kachel X:", self.x)
        fields.addRow("Kachel Y:", self.y)
        fields.addRow("Frame:", self.frame)
        fields.addRow("Team:", self.team)
        outer.addLayout(fields)
        self.apply = QPushButton("Position / Grafik übernehmen")
        self.apply.clicked.connect(self.apply_changes)
        self.remove = QPushButton("Sprite entfernen")
        self.remove.clicked.connect(self.canvas.delete_selected)
        outer.addWidget(self.apply)
        outer.addWidget(self.remove)
        self.detail = QLabel("Gelände anklicken: originale Kachelwerte erscheinen hier.")
        self.detail.setWordWrap(True)
        outer.addWidget(self.detail)
        self.engine_detail = QLabel("Original-Engine: Kachel anklicken, um die tatsächlichen Grafikbefehle zu sehen.")
        self.engine_detail.setWordWrap(True)
        outer.addWidget(self.engine_detail)
        self.engine_edit = QPushButton("Grafik dieser Engine-Kachel direkt bearbeiten")
        self.engine_edit.setEnabled(False)
        self.engine_edit.clicked.connect(self._edit_engine_tile)
        outer.addWidget(self.engine_edit)
        self.map_visual = QPushButton("Aktuelle Spritegrafik dem Originaltyp zuordnen")
        self.map_visual.setToolTip(
            "Verwendet die aktuell gewählte Spritegruppe/Framenummer der Palette "
            "für alle Originalobjekte dieses numerischen Typs.")
        self.map_visual.clicked.connect(self.assign_native_visual.emit)
        outer.addWidget(self.map_visual)
        self.clear_visual = QPushButton("Grafik-Zuordnung für diesen Typ aufheben")
        self.clear_visual.clicked.connect(self.clear_native_visual.emit)
        outer.addWidget(self.clear_visual)
        self.surface_info = QLabel(
            "Bodenart 3037: Kachel anklicken und den getrennten Texturkanal prüfen."
        )
        self.surface_info.setWordWrap(True)
        outer.addWidget(self.surface_info)
        self.assign_surface = QPushButton("Palette-Sprite für Bodenart 3037 testen")
        self.assign_surface.setToolTip(
            "Weist ein Sprite allen Kacheln mit demselben echten 3037-Bodencode "
            "zu, ohne Höhenwerte in 3005 zu verändern."
        )
        self.assign_surface.clicked.connect(self.assign_surface_test.emit)
        outer.addWidget(self.assign_surface)
        self.clear_surface = QPushButton("Bodenart-3037-Test zurücksetzen")
        self.clear_surface.clicked.connect(self.clear_surface_test.emit)
        outer.addWidget(self.clear_surface)
        self.terrain_info = QLabel(
            "Höhenwert 3005: ältere manuelle Frame-Tests bleiben unterstützt."
        )
        self.terrain_info.setWordWrap(True)
        outer.addWidget(self.terrain_info)
        self.assign_terrain = QPushButton("Palette-Sprite als Terrain-Test für Rohwert 3005")
        self.assign_terrain.setToolTip(
            "Ordnet die gewählte Spritegruppe und Framenummer allen Kacheln mit "
            "demselben Original-Bytewert der aktuellen Karte zu (nur Sandbox)."
        )
        self.assign_terrain.clicked.connect(self.assign_terrain_test.emit)
        outer.addWidget(self.assign_terrain)
        self.clear_terrain = QPushButton("Terrain-Test für diesen Rohwert zurücksetzen")
        self.clear_terrain.clicked.connect(self.clear_terrain_test.emit)
        outer.addWidget(self.clear_terrain)
        self.reset_terrain_pick()
        self.map_visual.setEnabled(False)
        self.clear_visual.setEnabled(False)
        outer.addStretch(1)
        self.canvas.engine_sprite_picked.connect(self.show_engine_sprite)
        self.canvas.picked.connect(self.show_tile)
        self.canvas.original_building_selected.connect(self.show_original_building)
        self.canvas.original_tree_selected.connect(self.show_original_tree)
        self.canvas.object_selected.connect(self.select)
        self.canvas.modified.connect(self._refresh)
        self.select("")

    def _current(self):
        if self._ident is None or not self.canvas.has_map():
            return None
        return next((o for o in self.canvas.history.overlay.objects if o.id == self._ident), None)

    def _refresh(self):
        self.select(self.canvas.select_id() or "")

    def select(self, ident):
        self._ident = ident or None
        self._original = None
        self.map_visual.setEnabled(False)
        self.clear_visual.setEnabled(False)
        obj = self._current()
        self.apply.setEnabled(obj is not None)
        self.remove.setEnabled(obj is not None)
        for field in (self.x, self.y, self.frame, self.team):
            field.setEnabled(obj is not None)
        if obj:
            self.group.setText(obj.group)
            self.x.setValue(obj.x)
            self.y.setValue(obj.y)
            self.frame.setValue(obj.frame)
            index = self.team.findData(obj.team)
            if index >= 0:
                self.team.setCurrentIndex(index)
            self.detail.setText(f"ID {obj.id[:12]} · Overlay-Sprite, nicht Originalkartenobjekt")
        else:
            self.group.setText("Kein Overlay-Sprite ausgewählt")

    def show_original_tree(self, tree):
        self._original = ("tree", tree.raw_group)
        self.map_visual.setEnabled(True)
        self.clear_visual.setEnabled(True)
        self.detail.setText(
            f"Originalvegetation: Datensatz {tree.record_number}; "
            f"Rohcodes {tree.raw_variant}, {tree.raw_group}, {tree.raw_state}; "
            f"Kachel ({tree.x},{tree.y}). Read-only, Animationszuordnung offen."
        )

    def show_original_building(self, entry):
        self._original = ("building", entry.type_id)
        self.map_visual.setEnabled(True)
        self.clear_visual.setEnabled(True)
        self.detail.setText(
            f"Originalgebäude: Typ-ID {entry.type_id} · Besitzer {entry.owner} · "
            f"UID {entry.uid} · Kachel ({entry.x},{entry.y}) · "
            f"Footprint {entry.footprint}. Read-only, Sprite-Zuordnung unbestätigt."
        )

    def reset_terrain_pick(self):
        self._terrain_code = None
        self._surface_code = None
        self._terrain_xy = None
        self.engine_edit.setEnabled(False)
        self.assign_surface.setEnabled(False)
        self.clear_surface.setEnabled(False)
        self.surface_info.setText(
            "Bodenart 3037: Kachel anklicken, um die Boden-Texturklasse zu wählen."
        )
        self.assign_terrain.setEnabled(False)
        self.clear_terrain.setEnabled(False)
        self.terrain_info.setText(
            "Höhenwert 3005: Kachel anklicken, um ältere Testzuordnungen zu bearbeiten."
        )

    def refresh_terrain_summary(self):
        if self._terrain_code is None or not self.canvas.has_map():
            return
        code = self._terrain_code
        x, y = self._terrain_xy
        amount = self.canvas._channels.channels[3005].count(code)
        candidate = self.canvas.terrain_tests.get(code) if self.canvas.terrain_tests else None
        description = (
            f"TEST: {candidate.group}/{candidate.frame}"
            if candidate is not None else "Näherungsdarstellung (keine Testzuordnung)"
        )
        self.terrain_info.setText(
            f"Kachel ({x},{y}) · Höhe 3005: {code} · "
            f"{amount:,} Kacheln mit diesem Wert. {description}. "
            "Originalmaterial noch unbestätigt."
        )

    def show_engine_sprite(self, hit):
        source={
            "actor":"Einheit / Originalobjekt",
            "floor":"Boden- / Gebäude-Kachel",
            "height-side":"Höhen- / Klippenseite",
        }.get(hit.kind,hit.kind)
        self.engine_detail.setText(
            f"Angeklickte Original-Engine-Grafik ({source}): "
            f"{hit.ref.group}/{hit.ref.frame} (GM {hit.source_file}, "
            f"Quellbild {hit.source_frame}, Licht {hit.ref.light}, "
            f"Farbkanal {getattr(hit.ref, 'float_colour', 0)}), "
            f"Position ({hit.x}, {hit.y}), "
            f"Deckkraft {hit.opacity*100:.0f} %. "
            "Das Original bleibt unverändert; Bearbeiten erstellt nur eine Arbeitskopie."
        )
        self.engine_edit.setEnabled(True)

    def _edit_engine_tile(self):
        if self._terrain_xy is not None:
            self.edit_engine_tile.emit(*self._terrain_xy)

    def show_tile(self, x, y, data):
        self.engine_detail.setText(self.canvas.engine_tile_description(x,y))
        self.engine_edit.setEnabled(self.canvas.runtime_snapshot is not None)
        parsed = ", ".join(f"{key}={value}" for key, value in sorted(data.items()))
        occupied = data.get(3004, 0)
        occupation = ""
        if occupied and self.canvas.native_geometry is not None:
            footprint = next((p for p in self.canvas.native_geometry.footprints
                              if p.raw_id == occupied), None)
            if footprint is not None:
                size_x = footprint.max_x-footprint.min_x+1
                size_y = footprint.max_y-footprint.min_y+1
                occupation = (
                    f"\nEchte 3004-Belegung #{occupied}: {footprint.cells} Kacheln, "
                    f"Bounds ({footprint.min_x},{footprint.min_y})–"
                    f"({footprint.max_x},{footprint.max_y}), "
                    f"{size_x}×{size_y}."
                )
        self.detail.setText(
            f"Original-Kachel ({x},{y}) · {parsed}{occupation}\n"
            "Sprite- und Materialzuordnung noch nicht vollständig nachgewiesen."
        )
        code = data.get(3005)
        self._terrain_code = code if type(code) is int and 0 <= code <= 255 else None
        surface = data.get(3037)
        self._surface_code = (
            surface if type(surface) is int and 0 <= surface <= 255 else None
        )
        self._terrain_xy = (x, y)
        self.assign_surface.setEnabled(self._surface_code is not None)
        self.clear_surface.setEnabled(self._surface_code is not None)
        self.assign_terrain.setEnabled(self._terrain_code is not None)
        self.clear_terrain.setEnabled(self._terrain_code is not None)
        self.refresh_terrain_summary()
        self.refresh_surface_summary()

    def refresh_surface_summary(self):
        if self._surface_code is None or not self.canvas.has_map():
            return
        from stronghold_europe_de.sandbox.native_surface_mapping import provisional_surface_material
        code = self._surface_code
        values = self.canvas._channels.channels.get(3037, b"")
        candidate = (self.canvas.surface_tests.get(code)
                     if self.canvas.surface_tests is not None else None)
        description = (
            f"TEST {candidate.group}/{candidate.frame}" if candidate else
            f"Näherung: {provisional_surface_material(code)}"
        )
        self.surface_info.setText(
            f"Bodentextur 3037={code}, {values.count(code):,} Originalzellen "
            f"({description}). Höhe separat: 3005={self._terrain_code}."
        )

    def apply_changes(self):
        obj = self._current()
        if obj is None:
            return
        try:
            if not self.canvas.is_editable_native(self.x.value(), self.y.value()):
                raise SceneError("Objekt darf nicht in unspielbare Originalkarten-Randbereiche verschoben werden")
            self.canvas.history.move(obj.id, self.x.value(), self.y.value())
            self.canvas.history.set_properties(obj.id, frame=self.frame.value(),
                                               team=self.team.currentData())
        except (IndexError, SceneError) as exc:
            self.detail.setText(f"Fehler: {exc}")
            return
        self.canvas.rebuild(focus=obj.id)

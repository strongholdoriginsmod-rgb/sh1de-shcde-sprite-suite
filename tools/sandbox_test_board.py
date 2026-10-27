"""Isometric Sprite Suite test field, editable independently of original .map files.

Ground diamonds are editor aids, NOT imported game terrain. Sprites, pivots,
asset sources, placements and edits use Sprite Suite's existing toolchain.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

from PySide6.QtCore import Qt, Signal, QPointF, QTimer
from PySide6.QtGui import QColor, QBrush, QPen, QPolygonF, QPixmap
from PySide6.QtWidgets import (
    QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsScene, QGraphicsView,
)

import asset_katalog as katalog
from sandkasten import FrameSource, TEAM_COLOURS, tint
from sandbox_asset_preview import to_pixmap
from stronghold_europe_de.sandbox.scene_model import (
    EditableScene, SceneError, SceneHistory, tile_anchor, tile_at,
)


class SpriteObjectItem(QGraphicsPixmapItem):
    def __init__(self, owner, record, frame):
        super().__init__()
        self.owner = owner
        self.object_id = record.id
        self.setFlag(QGraphicsPixmapItem.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(QGraphicsPixmapItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsPixmapItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.configure(frame, record.team, record.group)
        self.set_grid_position(record.x, record.y)

    def configure(self, frame, team="keine", group=""):
        if frame is not None:
            image = frame.image
            mask = getattr(frame, "mask", None)
            if mask is not None and (group.startswith("body_") or "flag" in group):
                image = tint(image, mask, TEAM_COLOURS.get(team))
            pixels = type("PreviewPixels", (), {"image": image})()
            self.setPixmap(to_pixmap(pixels, checkerboard=False))
            self.setOffset(-frame.foot[0], -frame.foot[1])
            self.setToolTip(f"{frame.side}: {self.object_id[:8]} · Team: {team}")
        else:
            missing = Image.new("RGBA", (32, 32), (180, 44, 44, 255))
            self.setPixmap(to_pixmap(type("MissingSprite", (), {"image": missing})(), checkerboard=False))
            self.setOffset(-16, -16)
            self.setToolTip("Sprite nicht vorhanden")

    def set_grid_position(self, x, y):
        px, py = tile_anchor(x, y, self.owner.history.scene.height)
        self.setPos(QPointF(px, py))
        self.setZValue(x + y + 0.5)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        # A rebuild destroys QGraphicsItems; defer it until the Qt mouse event
        # has returned to avoid deleting the active receiver mid-dispatch.
        ident, pos = self.object_id, self.pos()
        QTimer.singleShot(0, lambda: self.owner.finish_move_id(ident, pos.x(), pos.y()))


class LegacyObjectItem(QGraphicsRectItem):
    """Drag/select the WHOLE historic object, never an individual GM1 part.

    Historical final pixels are drawn as one exact legacy-renderer image
    behind this transparent interaction box. Dragging moves only the
    corresponding original V1 record, not a flattened visual fragment.
    """
    def __init__(self, owner, record, bounds):
        super().__init__(*bounds)
        self.owner=owner
        self.object_id=record.id
        self.setFlag(self.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(self.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(self.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        self.setPen(QPen(QColor(251,207,75,150),1))
        self.setZValue(100000 + record.y)
        self.setToolTip(
            f"V1: {record.group}/{record.frame} · {record.x},{record.y}. "
            "Ganzes historisches Objekt verschieben; GM1/Animation bleiben erhalten."
        )

    def mouseReleaseEvent(self,event):
        super().mouseReleaseEvent(event)
        ident=self.object_id
        delta=self.pos()
        QTimer.singleShot(0,lambda:self.owner.finish_legacy_move(
            ident,delta.x(),delta.y()))


class SpriteTestBoard(QGraphicsView):
    """Editable isometric development canvas with native sprite references."""

    selected_id_changed = Signal(str)
    scene_changed = Signal()
    status_message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.history = SceneHistory()
        self._items = {}
        self.legacy_tick = 0.0
        self._legacy_frame_overrides = {}
        self._legacy_rebuilding = False
        self._placing = None
        self._drag_origin = None
        self.setScene(QGraphicsScene(self))
        self.setBackgroundBrush(QColor("#19231e"))
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.BoundingRectViewportUpdate)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.bc7_simulation = False
        self._source = FrameSource("arbeit", bc7=self.bc7_simulation, log=lambda _: None)
        self._known_signatures = {}
        self.show_ground_sprites = False
        self._asset_poll = QTimer(self)
        self._asset_poll.setInterval(1200)
        self._asset_poll.timeout.connect(self.poll_changed_assets)
        self._asset_poll.start()
        self.scene().selectionChanged.connect(self._selection_changed)
        self.rebuild()
        self.fit_map()

    @staticmethod
    def _signature_for(group, name):
        folder = katalog.work_dir(group)
        candidates = [folder / "index.json", folder / f"{name}.png", folder / f"{name}_m.png"]
        values = []
        for path in candidates:
            try:
                stat = path.stat()
                values.append((stat.st_mtime_ns, stat.st_size))
            except OSError:
                values.append(None)
        return tuple(values)

    def _asset_for(self, group, number):
        name = katalog.native_name(group, number)
        key = (group, name)
        self._known_signatures[key] = self._signature_for(group, name)
        try:
            return self._source.frame(group, name)
        except (Exception, SystemExit) as exc:
            self.status_message.emit(f"Asset konnte nicht geladen werden: {group}/{name}: {exc}")
            return None

    def poll_changed_assets(self):
        for group, name in tuple(self._known_signatures):
            key = (group, name)
            previous = self._known_signatures.get(key)
            if previous is None:
                continue
            new_signature = self._signature_for(group, name)
            if new_signature != previous:
                self._known_signatures[key] = new_signature
                self.refresh_assets(group, name)

    def rebuild(self, focus_id=None):
        if self.history.scene.is_legacy_v1:
            self._rebuild_legacy(focus_id)
            return
        self._items.clear()
        self._known_signatures.clear()
        self.scene().clear()
        width, height = self.history.scene.width, self.history.scene.height
        tile_options = [1, 2, 5, 12, 30, 52]
        ground_frames = {}
        if self.show_ground_sprites:
            for number in tile_options:
                frame = self._asset_for("tile_land8", number)
                if frame is not None:
                    ground_frames[number] = (
                        to_pixmap(frame, checkerboard=False), frame.foot
                    )
        tile_order = sorted(((x, y) for x in range(width) for y in range(height)),
                            key=lambda pos: (pos[0] + pos[1], pos[0]))
        for x, y in tile_order:
            cx, cy = tile_anchor(x, y, height)
            # Keep test-field ground strictly below test sprites. Interleaving
            # grass by depth can fully hide a tall sprite and invalidate previews.
            z = -10.0
            if ground_frames:
                frame_number = tile_options[(x * 17 + y * 23) % len(tile_options)]
                pix, pivot = ground_frames.get(frame_number, next(iter(ground_frames.values())))
                item = self.scene().addPixmap(pix)
                item.setOffset(-pivot[0], -pivot[1])
                item.setPos(cx, cy)
                item.setZValue(z)
            else:
                points = [
                    QPointF(cx, cy - 16), QPointF(cx + 32, cy),
                    QPointF(cx, cy + 16), QPointF(cx - 32, cy),
                ]
                polygon = self.scene().addPolygon(
                    QPolygonF(points), QPen(QColor("#54634a"), 0.4),
                    QBrush(QColor("#354a33") if (x + y) % 2 else QColor("#39503a")),
                )
                polygon.setZValue(z)
        for obj in self.history.scene.objects:
            item = SpriteObjectItem(self, obj, self._asset_for(obj.group, obj.frame))
            self.scene().addItem(item)
            self._items[obj.id] = item
            if obj.id == focus_id:
                item.setSelected(True)
        w = (width + height) * 32 + 256
        h = (width + height) * 16 + 256
        self.scene().setSceneRect(0, 0, w, h)
        self.scene_changed.emit()

    def _rebuild_legacy(self, focus_id=None):
        """Rebuild the legacy scene without reentering its Qt selection signals."""
        self._legacy_rebuilding=True
        completed=False
        try:
            self._render_legacy_items(focus_id)
            completed=True
        finally:
            self._legacy_rebuilding=False
            if completed:
                self.selected_id_changed.emit(self.selected_id() or "")

    def _render_legacy_items(self, focus_id=None):
        """Use the unchanged original render function, no V2 flattening."""
        from sandkasten import render
        raw=self.history.scene.serialize()
        if self._legacy_frame_overrides:
            from copy import deepcopy
            raw=deepcopy(raw)
            for i,obj in enumerate(self.history.scene.objects):
                if obj.id in self._legacy_frame_overrides:
                    source=raw["objekte"][i]
                    source["frame"]=self._legacy_frame_overrides[obj.id]
                    source.pop("animation",None)
        self._items.clear()
        self._known_signatures.clear()
        self.scene().clear()
        picture,parts,missing=render(raw,self._source,self.legacy_tick)
        background=self.scene().addPixmap(to_pixmap(
            type("LegacyFrame",(),{"image":picture})(),checkerboard=False))
        background.setZValue(-200000)
        by_object={}
        for part in parts:
            if part.layer!=1 or part.box is None:
                continue
            by_object.setdefault(part.order,[]).append(part.box)
        from sandkasten import HALF_W,HALF_H
        for i,record in enumerate(self.history.scene.objects):
            found=by_object.get(i,[])
            if found:
                left=min(box[0] for box in found)
                top=min(box[1] for box in found)
                right=max(box[2] for box in found)
                bottom=max(box[3] for box in found)
                bounds=(left,top,max(1,right-left),max(1,bottom-top))
            else:
                # The record still exists even when an atlas source is missing.
                cx=(self.history.scene.height+1+record.x-record.y)*HALF_W
                cy=420+(record.x+record.y)*HALF_H
                bounds=(cx-16,cy-16,32,32)
            item=LegacyObjectItem(self,record,bounds)
            self.scene().addItem(item)
            self._items[record.id]=item
            if record.id==focus_id:
                item.setSelected(True)
        self.scene().setSceneRect(0,0,picture.width,picture.height)
        if missing:
            self.status_message.emit(
                "Historische V1-Szene geladen, Bildquellen fehlen: "+
                ", ".join(missing[:8]))
        self.scene_changed.emit()

    def set_legacy_tick(self, tick):
        if not self.history.scene.is_legacy_v1:
            return False
        if not 0<=float(tick)<=3600:
            raise SceneError("V1-Animationszeit muss zwischen 0 und 3600 Sekunden liegen")
        focus=self.selected_id()
        self.legacy_tick=float(tick)
        self._legacy_frame_overrides.clear()
        self.rebuild(focus_id=focus)
        return True

    def finish_legacy_move(self,ident,dx,dy):
        record=next((obj for obj in self.history.scene.objects if obj.id==ident),None)
        if record is None:
            return
        from sandkasten import HALF_W,HALF_H
        anchor_x=(self.history.scene.height+1+record.x-record.y)*HALF_W
        anchor_y=420+(record.x+record.y)*HALF_H
        x,y=tile_at(anchor_x+dx,anchor_y+dy-(420-128),
                    self.history.scene.height)
        try:
            self.history.move(ident,x,y)
        except SceneError as exc:
            self.status_message.emit(str(exc))
        self.rebuild(focus_id=ident)

    def set_bc7_simulation(self, enabled):
        """Original Sandkasten's BC7 checkbox affects the ACTUAL scene.

        Previously it affected only the right-hand thumbnail, so the
        Testfeld displayed different pixels from its claimed preview.
        This is a transient visual simulation, not a saved scene change.
        """
        enabled = bool(enabled)
        if self.bc7_simulation == enabled:
            return
        self.bc7_simulation = enabled
        self.reload_source()

    def reload_source(self):
        """F5 in Testfeld: rebuild its frame source, never reload a .map.

        The camera, selection, undo/history and original input files remain.
        """
        self._source = FrameSource(
            "arbeit", bc7=self.bc7_simulation, log=lambda _: None
        )
        self.rebuild(focus_id=self.selected_id())
        return True

    def set_ground_sprites(self, enabled):
        enabled = bool(enabled)
        if self.show_ground_sprites == enabled:
            return
        self.show_ground_sprites = enabled
        focus = self.selected_id()
        self.rebuild(focus_id=focus)

    def fit_map(self):
        self.fitInView(self.scene().sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def selected_id(self):
        for item in self.scene().selectedItems():
            if isinstance(item, (SpriteObjectItem, LegacyObjectItem)):
                return item.object_id
        return None

    def _selection_changed(self):
        if self._legacy_rebuilding:
            return
        self.selected_id_changed.emit(self.selected_id() or "")

    def arm_placement(self, group, frame):
        if not group:
            self.status_message.emit("Bitte zuerst eine Sprite-Gruppe wählen.")
            return
        if not isinstance(frame, int) or frame < 0:
            self.status_message.emit("Ungültiger Sprite-Frame.")
            return
        self._placing = (group, frame)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.status_message.emit(f"Platzieren: {group} / Frame {frame} · ESC bricht ab.")

    def cancel_placement(self):
        self._placing = None
        self.unsetCursor()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._drag_origin = event.position().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if self._placing and event.button() == Qt.MouseButton.LeftButton:
            pt = self.mapToScene(event.position().toPoint())
            legacy_offset=420-128 if self.history.scene.is_legacy_v1 else 0
            x, y = tile_at(pt.x(), pt.y()-legacy_offset,self.history.scene.height)
            group, frame = self._placing
            if 0 <= x < self.history.scene.width and 0 <= y < self.history.scene.height:
                try:
                    ident = self.history.place(group, frame, x, y)
                    self.rebuild(focus_id=ident)
                    self.status_message.emit(f"Sprite {group}/{frame} auf Kachel {x},{y} platziert")
                except SceneError as exc:
                    self.status_message.emit(str(exc))
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_origin is not None:
            delta = event.position().toPoint() - self._drag_origin
            self._drag_origin = event.position().toPoint()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._drag_origin = None
            self.unsetCursor()
            if self._placing:
                self.setCursor(Qt.CursorShape.CrossCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        if event.angleDelta().y():
            scale = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            new_zoom = self.transform().m11() * scale
            if 0.08 <= new_zoom <= 16:
                self.scale(scale, scale)
        event.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.cancel_placement()
            self.status_message.emit("Platzieren abgebrochen.")
            event.accept()
            return
        if event.key() == Qt.Key.Key_Delete:
            self.delete_selected()
            event.accept()
            return
        super().keyPressEvent(event)

    def finish_move_id(self, ident, px, py):
        record = next((o for o in self.history.scene.objects if o.id == ident), None)
        if record is None:
            return
        x, y = tile_at(px, py, self.history.scene.height)
        if (x, y) == (record.x, record.y):
            current = self._items.get(ident)
            if current:
                current.set_grid_position(record.x, record.y)
            return
        try:
            self.history.move(ident, x, y)
        except SceneError as exc:
            current = self._items.get(ident)
            if current:
                current.set_grid_position(record.x, record.y)
            self.status_message.emit(str(exc))
            return
        self.rebuild(focus_id=ident)
        self.status_message.emit(f"Objekt auf Kachel {x},{y} verschoben.")

    def delete_selected(self):
        ident = self.selected_id()
        if ident is None:
            return
        self.history.delete(ident)
        self.rebuild()
        self.status_message.emit("Objekt entfernt – Rückgängig ist möglich.")

    def undo(self):
        focus = self.selected_id()
        self.history.undo()
        self.rebuild(focus_id=focus)

    def redo(self):
        focus = self.selected_id()
        self.history.redo()
        self.rebuild(focus_id=focus)

    def replace_scene(self, scene: EditableScene):
        self.history = SceneHistory(scene)
        self.legacy_tick=0.0
        self._legacy_frame_overrides.clear()
        self._source = FrameSource(
            "arbeit", bc7=self.bc7_simulation, log=lambda _: None
        )
        self.cancel_placement()
        self.rebuild()
        self.fit_map()

    def preview_object_frame(self, ident: str, frame_number: int) -> bool:
        """Show one frame without modifying undo history or the saved scene."""
        record = next((o for o in self.history.scene.objects if o.id == ident), None)
        item = self._items.get(ident)
        if record is None or item is None:
            return False
        if not isinstance(frame_number, int) or not 0 <= frame_number <= 999999:
            return False
        if self.history.scene.is_legacy_v1:
            self._legacy_frame_overrides[ident]=frame_number
            self.rebuild(focus_id=ident)
            return True
        frame = self._asset_for(record.group, frame_number)
        if frame is None:
            return False
        item.configure(frame, record.team, record.group)
        return True

    def restore_object_frame(self, ident: str):
        record = next((o for o in self.history.scene.objects if o.id == ident), None)
        if record is not None:
            if self.history.scene.is_legacy_v1:
                # SelectionChanged occurs DURING QGraphicsScene.clear()/rebuild;
                # do not recursively rebuild or delete an active Qt receiver.
                if ident in self._legacy_frame_overrides:
                    self._legacy_frame_overrides.pop(ident,None)
                    QTimer.singleShot(0,lambda:self.rebuild(focus_id=ident))
            else:
                self.preview_object_frame(ident, record.frame)

    def refresh_assets(self, group: str, name: str):
        # Source indices and sprite bitmaps must both be invalidated on disk changes.
        # Preserve the model, camera and selected object when re-rendering.
        self._source = FrameSource(
            "arbeit", bc7=self.bc7_simulation, log=lambda _: None
        )
        if self.history.scene.is_legacy_v1:
            self.rebuild(focus_id=self.selected_id())
            return
        if group == "tile_land8" and self.show_ground_sprites:
            self.rebuild(focus_id=self.selected_id())
            return
        for obj in self.history.scene.objects:
            if obj.group == group and katalog.native_name(obj.group, obj.frame) == name:
                item = self._items.get(obj.id)
                if item:
                    item.configure(self._asset_for(obj.group, obj.frame), obj.team, obj.group)

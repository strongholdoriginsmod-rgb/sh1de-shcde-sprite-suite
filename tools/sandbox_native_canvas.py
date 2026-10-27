"""Navigable, interactive original-map terrain inspector with live sprite overlays.

Real native map values supply tile positions. Material sprite mappings are
explicitly provisional until independently verified against the game runtime.
Visible tiles alone are drawn at detailed zoom; distant terrain uses a complete
read-only original-data overview rather than 320k QGraphicsItems.
"""
from __future__ import annotations

from pathlib import Path
import re
from collections import OrderedDict
from math import floor
from PIL import Image
import asset_katalog as katalog
from sandkasten import FrameSource, TEAM_COLOURS, tint
from sandbox_asset_preview import to_pixmap
from stronghold_europe_de.sandbox.map_sections import (
    NATIVE_DIAMOND, NATIVE_TILES, tile_index,
    render_native_tile_values, load_native_tile_channels, load_original_buildings,
    load_original_trees,
)
from stronghold_europe_de.sandbox.native_overlay import (
    OverlayHistory, NativeOverlay, new_overlay,
)
from stronghold_europe_de.sandbox.scene_model import SceneError
from stronghold_europe_de.sandbox.native_runtime import capture_snapshot, NativeRuntimeError
from stronghold_europe_de.sandbox.native_visual_mapping import OriginalVisualMappings
from stronghold_europe_de.sandbox.native_terrain_mapping import TerrainTestMappings, TerrainMappingError
from stronghold_europe_de.sandbox.native_surface_mapping import SurfaceTestMappings, provisional_surface_material
from stronghold_europe_de.sandbox.native_layers import (
    native_geometry, render_native_masked_overview
)
from PySide6.QtCore import Qt, QPointF, QRectF, QTimer, Signal
from PySide6.QtGui import QColor, QBrush, QPen, QPolygonF, QPixmap, QPainter
from PySide6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsPixmapItem

TILE_X = 32
TILE_Y = 16
CHUNK_W = 512
CHUNK_H = 256
CHUNK_CACHE_LIMIT = 72
WORLD_WIDTH = NATIVE_DIAMOND * TILE_X
WORLD_HEIGHT = NATIVE_DIAMOND * TILE_Y
TEXTURES = {
    "grass": ("tile_land8", (1, 5, 12, 30)),
    "water": ("tile_sea8", (1, 2, 3)),
    "rock": ("tile_rocks8", (1, 4)),
    "shore": ("tile_land_and_stones", (1, 2)),
}


def native_tile_material(code: int) -> str:
    """Provisional material mapping for display only; never modify map IDs."""
    if code == 8:
        return "grass"
    if code == 0 or 1 <= code <= 3:
        return "water"
    if code >= 128:
        return "rock"
    return "shore"


class NativePlacedSprite(QGraphicsPixmapItem):
    def __init__(self, owner, record, frame):
        super().__init__()
        self.owner = owner
        self.object_id = record.id
        self.setFlag(self.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(self.GraphicsItemFlag.ItemIsMovable)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.update_frame(frame, record)
        self.set_native_pos(record.x, record.y)

    def update_frame(self, frame, record):
        # A magenta missing-frame placeholder is never proof of a sprite
        # available for HUD artwork preview. Retain this per displayed item.
        self.source_loaded = frame is not None
        if frame is not None:
            image = frame.image
            if frame.mask is not None and (record.group.startswith("body_") or "flag" in record.group):
                image = tint(image, frame.mask, TEAM_COLOURS.get(record.team))
            self.setPixmap(to_pixmap(type("Pixels", (), {"image": image})(), checkerboard=False))
            self.setOffset(-frame.foot[0], -frame.foot[1])
        else:
            self.setPixmap(to_pixmap(type("Pixels", (), {
                "image": Image.new("RGBA", (32, 32), "#cb4b57")
            })(), checkerboard=False))
            self.setOffset(-16, -16)
        self.setToolTip(f"{record.group}/{record.frame} · {record.team} · {record.x},{record.y}")

    def set_native_pos(self, x, y):
        self.setPos(QPointF(x * TILE_X + TILE_X / 2,
                           y * TILE_Y + TILE_Y / 2 - self.owner.native_height(x,y)*2))
        self.setZValue(100000 + y + x * 0.00001)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        pos, ident = self.pos(), self.object_id
        QTimer.singleShot(0, lambda: self.owner.finish_move(ident, pos.x(), pos.y()))


class NativeMapCanvas(QGraphicsView):
    picked = Signal(int, int, object)
    object_selected = Signal(str)
    original_building_selected = Signal(object)
    original_tree_selected = Signal(object)
    modified = Signal()
    message = Signal(str)
    camera_changed = Signal()
    engine_sprite_picked = Signal(object)
    engine_mode_changed = Signal()
    placement_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setBackgroundBrush(QColor("#122019"))
        self.setTransformationAnchor(self.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(self.ViewportAnchor.AnchorViewCenter)
        self.setViewportUpdateMode(self.ViewportUpdateMode.BoundingRectViewportUpdate)
        self.setDragMode(self.DragMode.RubberBandDrag)
        self.setMouseTracking(True)
        self.setToolTip(
            "Tastatur: Pfeiltasten bewegen den Kachelcursor, Enter wählt oder "
            "platziert im Overlay, Esc beendet; Maus: Rad zoomt, Mitteltaste schwenkt."
        )
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._keyboard_tile = None
        self._keyboard_marker = None
        self._channels = None
        self._base = None
        self.runtime_snapshot = None
        self.runtime_renderer = None
        self.runtime_error = None
        self.last_engine_pick = None
        self.use_engine_commands = True
        self.use_original_runtime_assets = False
        self._source = FrameSource("arbeit", log=lambda _: None)
        self._textures = {}
        self._texture_signatures = {}
        self._terrain_chunks = OrderedDict()
        self._sprite_signatures = {}
        self._native_visual_cache = {}
        self._mapped_asset_signatures = {}
        self.visual_mappings = OriginalVisualMappings()
        self.terrain_tests = None
        self.surface_tests = None
        self.native_geometry = None
        self.show_occupancy = False
        self._items = {}
        self._map_path = None
        self.original_buildings = []
        self.original_trees = []
        self.show_original_buildings = True
        self.show_original_trees = True
        self.history = None
        self._placing = None
        self._placement_team = "rot"
        self.diagnostic_only = False
        self._pan_origin = None
        self.scene().setSceneRect(0, 0, WORLD_WIDTH, WORLD_HEIGHT)
        self.scene().selectionChanged.connect(self._selection_changed)
        self._poll = QTimer(self)
        self._poll.setInterval(1800)
        self._poll.timeout.connect(self.refresh_changed)
        self._poll.start()
        self.horizontalScrollBar().valueChanged.connect(
            lambda _value: self.camera_changed.emit())
        self.verticalScrollBar().valueChanged.connect(
            lambda _value: self.camera_changed.emit())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.camera_changed.emit()

    def clear_map(self):
        """Forget the previous map without writing an overlay or game file.

        Used when a user switches the map folder, including to an empty one.
        An old selectable/editable map must never remain under a new root.
        """
        self.cancel_placement()
        self._channels = None
        self._base = None
        self._map_path = None
        self.native_geometry = None
        self.original_buildings.clear()
        self.original_trees.clear()
        self.history = None
        self.terrain_tests = None
        self.surface_tests = None
        self.runtime_snapshot = None
        self.runtime_renderer = None
        self.runtime_error = None
        self.last_engine_pick = None
        self._keyboard_tile = None
        self._keyboard_marker = None
        self._pan_origin = None
        self._items.clear()
        self._textures.clear()
        self._texture_signatures.clear()
        self._terrain_chunks.clear()
        self._sprite_signatures.clear()
        self._native_visual_cache.clear()
        self._mapped_asset_signatures.clear()
        self.scene().clear()
        self.scene().setSceneRect(0, 0, WORLD_WIDTH, WORLD_HEIGHT)
        self.resetTransform()
        self.unsetCursor()
        self.placement_changed.emit()
        self.modified.emit()
        self.camera_changed.emit()

    def open_map(self, path: str | Path, channels=None, overlay=None):
        self._map_path = Path(path)
        self._channels = channels if channels is not None else load_native_tile_channels(path)
        self.original_buildings = load_original_buildings(path)
        self.original_trees = load_original_trees(path)
        data = self._channels.channels[3005]
        if len(data) != NATIVE_TILES:
            raise SceneError("Native Kachelanzahl stimmt nicht")
        self.native_geometry = native_geometry(self._channels.channels)
        self._base = to_pixmap(
            type("MapPixels", (), {
                "image": render_native_masked_overview(
                    data, self.native_geometry, self._channels.channels.get(3037)
                )
            })(), checkerboard=False
        )
        # Visible original world bounds, not the 320,800-cell padded container.
        native = self.native_geometry
        margin_x, margin_y = 160, 96
        self.scene().setSceneRect(
            max(0, native.min_x * TILE_X - margin_x),
            max(0, native.min_y * TILE_Y - margin_y),
            min(WORLD_WIDTH, (native.max_x + 1) * TILE_X + margin_x)
                - max(0, native.min_x * TILE_X - margin_x),
            min(WORLD_HEIGHT, (native.max_y + 1) * TILE_Y + margin_y)
                - max(0, native.min_y * TILE_Y - margin_y)
        )
        self.history = OverlayHistory(overlay or new_overlay(path))
        # Prevent a mapping for another original .map being used even briefly.
        self.terrain_tests = TerrainTestMappings(self.history.overlay.source_sha256)
        self.surface_tests = SurfaceTestMappings(self.history.overlay.source_sha256)
        self._placing = None
        self._keyboard_tile = None
        self._keyboard_marker = None
        self.placement_changed.emit()
        self._source = FrameSource("arbeit", log=lambda _: None)
        self._textures.clear()
        self._texture_signatures.clear()
        self._terrain_chunks.clear()
        self.runtime_snapshot = None
        self.runtime_renderer = None
        self.runtime_error = None
        self.last_engine_pick = None
        try:
            from sandbox_runtime_renderer import NativeCommandRenderer
            self.runtime_snapshot = capture_snapshot(path)
            self.runtime_renderer = NativeCommandRenderer(self, self.runtime_snapshot)
            self.runtime_renderer.assets.original_only = self.use_original_runtime_assets
        except (NativeRuntimeError, OSError, ValueError, IndexError) as exc:
            self.runtime_error = str(exc)
        self.rebuild()
        # Open on a useful, sprite-textured working camera rather than on the
        # tiny whole-map diagnostic thumbnail. Home always restores full extent.
        self.resetTransform()
        self.scale(0.60, 0.60)
        if self.original_buildings:
            mx = round(sum(obj.x for obj in self.original_buildings) / len(self.original_buildings))
            my = round(sum(obj.y for obj in self.original_buildings) / len(self.original_buildings))
        else:
            mx, my = 400, 400
        self.center_native(mx, my)
        self.message.emit(
            f"Originaldaten: {self.native_geometry.nonpadding_tiles:,} nicht-randmarkierte "
            f"Kacheln, {self.native_geometry.padding_tiles:,} Randzellen ausgeblendet; "
            + self.runtime_description()
        )

    def engine_active(self):
        return (self.runtime_renderer is not None and self.use_engine_commands
                and not self.diagnostic_only)

    def runtime_description(self):
        if self.runtime_snapshot is not None:
            snap = self.runtime_snapshot
            return (f"Engine-Snapshot: {snap.visible_tile_count:,} echte Tile-Frames, "
                    f"{snap.object_count:,} Objektbefehle; Shaderabgleich noch offen")
        return "Näherungsrenderer: " + (self.runtime_error or "Engine nicht verfügbar")

    def set_runtime_enabled(self, enabled):
        self.use_engine_commands = bool(enabled)
        self.last_engine_pick = None
        self.refresh_terrain_assets()
        self.rebuild(focus=self.select_id())
        self.message.emit(self.runtime_description() if enabled else
                          "Manuelle Diagnose-/Näherungsansicht aktiviert")
        self.engine_mode_changed.emit()

    def set_engine_view_mode(self, mode):
        if mode not in (0,1,2):
            raise ValueError("Unbekannter Engine-Anzeigemodus")
        self.use_engine_commands = mode != 2
        self.use_original_runtime_assets = mode == 1
        self.last_engine_pick = None
        if self.runtime_renderer:
            self.runtime_renderer.assets.original_only = self.use_original_runtime_assets
        self.refresh_terrain_assets()
        self.rebuild(focus=self.select_id())
        self.engine_mode_changed.emit()

    def engine_tile_description(self, x, y):
        if self.runtime_snapshot is None:
            return "Original-Engine nicht verfügbar; diese Darstellung verwendet Näherungen."
        r = self.runtime_snapshot.tile(x, y)
        if r is None:
            return "Kein originaler Grafikbefehl für diese Kachel"
        ref = self.runtime_renderer._tile_reference(r)
        sprite = f"{ref.group}/{ref.frame}" if ref else "Leere/Debug-Kachel"
        return (f"Engine: GM {int(r[3])}, Bild {int(r[4])} → {sprite}; "
                f"Höhe {int(r[5])} ({int(r[5])*2} Pixel), Licht {int(r[6])}, "
                f"Farbkanal {int(r[7])}; "
                f"Seitenfläche GM {int(r[11])}/{int(r[12])}. "
                "Unveränderte Spielbefehle; Qt-Shader-Nachbildung noch nicht vollständig.")

    def native_height(self, x, y):
        return self.runtime_renderer.native_height(x,y) if self.engine_active() else 0

    def has_map(self):
        return self._channels is not None and self.history is not None

    def current_overlay(self):
        return self.history.overlay if self.history else None

    def fit_map(self):
        if self.has_map():
            self.fitInView(self.scene().sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
            self.camera_changed.emit()

    def zoom(self, factor):
        old = self.transform().m11()
        if 0.035 <= old * factor <= 4:
            self.scale(factor, factor)
            self.camera_changed.emit()

    def is_editable_native(self, x: int, y: int) -> bool:
        try:
            idx = tile_index(x, y)
        except (IndexError, TypeError):
            return False
        return self.native_geometry is None or not self.native_geometry.is_padding_index(idx)

    def center_native(self, x: int, y: int):
        if not self.is_editable_native(x, y):
            return
        self.centerOn(x * TILE_X, y * TILE_Y)
        self.camera_changed.emit()

    @staticmethod
    def _signature(group, number):
        folder = katalog.work_dir(group)
        name = katalog.native_name(group, number)
        values = []
        for file in (folder / "index.json", folder / (name + ".png")):
            try:
                info = file.stat()
                values.append((info.st_mtime_ns, info.st_size))
            except OSError:
                values.append(None)
        return tuple(values)

    @staticmethod
    def _sprite_signature(group, frame):
        directory = katalog.work_dir(group)
        name = katalog.native_name(group, frame)
        return tuple(
            (p.stat().st_mtime_ns, p.stat().st_size) if p.is_file() else None
            for p in (directory / "index.json", directory / f"{name}.png",
                      directory / f"{name}_m.png")
        )

    def _load_texture(self, group, number):
        key = (group, number)
        if key not in self._textures:
            try:
                name = katalog.native_name(group, number)
                frame = self._source.frame(group, name)
                self._textures[key] = (
                    (to_pixmap(frame, checkerboard=False), frame.foot)
                    if frame is not None else None
                )
            except (OSError, ValueError, SystemExit, Exception) as exc:
                self._textures[key] = None
                self.message.emit(f"Textur nicht verfügbar: {group}/{number}: {exc}")
            self._texture_signatures[key] = self._signature(group, number)
        return self._textures[key]

    def _get_texture(self, material, x, y):
        group, options = TEXTURES[material]
        number = options[(x * 7 + y * 13) % len(options)]
        return self._load_texture(group, number)

    def _terrain_material(self, height_code, original_flags=0, surface_code=None):
        """Use real texture BYTE 3037, not guessed material by height 3005.

        Fallback only for old test fixtures/maps missing source section 3037.
        """
        if original_flags & 0x100000:
            return "water"
        if surface_code is not None:
            return provisional_surface_material(surface_code)
        return native_tile_material(height_code)

    def _get_terrain_texture(self, code, x, y, original_flags=0, surface_code=None):
        # Original per-height/3005 user mappings from prior studio releases
        # remain supported; they have the highest precedence.
        legacy = self.terrain_tests.get(code) if self.terrain_tests else None
        if legacy is not None:
            return self._load_texture(legacy.group, legacy.frame)
        # New texture-channel mapping: all cells with the chosen 3037 byte,
        # independent of their height values. It remains an atlas experiment.
        surface = (self.surface_tests.get(surface_code)
                   if surface_code is not None and self.surface_tests else None)
        if surface is not None:
            return self._load_texture(surface.group, surface.frame)
        return self._get_texture(
            self._terrain_material(code, original_flags, surface_code), x, y
        )

    def set_surface_tests(self, mappings):
        mappings.validate()
        if self.history and mappings.source_sha256 != self.history.overlay.source_sha256:
            raise TerrainMappingError("Texturtest gehört zu einer anderen Originalkarte")
        self.surface_tests = mappings
        self.refresh_terrain_assets()

    def set_terrain_tests(self, mappings):
        mappings.validate()
        if self.history and mappings.source_sha256 != self.history.overlay.source_sha256:
            raise TerrainMappingError("Zuordnung passt nicht zur geöffneten Originalkarte")
        self.terrain_tests = mappings
        self.refresh_terrain_assets()


    def _draw_terrain_area(self, painter: QPainter, rect: QRectF):
        if self.engine_active():
            self.runtime_renderer.draw_area(painter, rect)
            return
        # Overdraw neighboring cells into the chunk before cropping it: real
        # sprite pivots can extend beyond nominal tile cells. This prevents
        # seams at 512x256 chunk boundaries on both pan and zoom.
        expanded = rect.adjusted(-128, -144, 128, 144)
        data = self._channels.channels[3005]
        surface = self._channels.channels.get(3037)
        left = max(0, int(expanded.left() // TILE_X) - 2)
        right = min(NATIVE_DIAMOND - 1, int(expanded.right() // TILE_X) + 2)
        top = max(0, int(expanded.top() // TILE_Y) - 2)
        bottom = min(NATIVE_DIAMOND - 1, int(expanded.bottom() // TILE_Y) + 2)
        for y in range(top, bottom + 1):
            width = 2 * (y + 1 if y < 400 else NATIVE_DIAMOND - y)
            offset = (NATIVE_DIAMOND - width) // 2
            first = y * (y + 1) if y < 400 else (
                160400 + 800 * (y - 400) - (y - 400) * (y - 401))
            for x in range(max(left, offset), min(right + 1, offset + width)):
                raw_index = first + x - offset
                if (self.native_geometry is not None and
                        self.native_geometry.is_padding_index(raw_index)):
                    continue
                code = data[raw_index]
                raw_flags = (self.native_geometry.original_flags_at(raw_index)
                             if self.native_geometry is not None else 0)
                surface_code = surface[raw_index] if surface is not None else None
                texture = self._get_terrain_texture(
                    code, x, y, raw_flags, surface_code
                )
                cx, cy = x * TILE_X + 16, y * TILE_Y + 16
                if texture is None:
                    material = self._terrain_material(code, raw_flags, surface_code)
                    fallback = {"water": "#345e80", "grass": "#566c45",
                                "rock": "#928365", "shore": "#ac9770"}[material]
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor(fallback))
                    painter.drawPolygon(QPolygonF([
                        QPointF(cx, cy - 16), QPointF(cx + 32, cy),
                        QPointF(cx, cy + 16), QPointF(cx - 32, cy),
                    ]))
                else:
                    pix, foot = texture
                    painter.drawPixmap(QPointF(cx - foot[0], cy - foot[1]), pix)

    def _terrain_chunk(self, column: int, row: int) -> QPixmap:
        key = (column, row)
        cached = self._terrain_chunks.get(key)
        if cached is not None:
            self._terrain_chunks.move_to_end(key)
            return cached
        chunk = QPixmap(CHUNK_W, CHUNK_H)
        chunk.fill(Qt.GlobalColor.transparent)
        painter = QPainter(chunk)
        world_x, world_y = column * CHUNK_W, row * CHUNK_H
        painter.translate(-world_x, -world_y)
        self._draw_terrain_area(
            painter, QRectF(world_x, world_y, CHUNK_W, CHUNK_H))
        painter.end()
        self._terrain_chunks[key] = chunk
        if len(self._terrain_chunks) > CHUNK_CACHE_LIMIT:
            self._terrain_chunks.popitem(last=False)
        return chunk

    def drawBackground(self, painter: QPainter, rect: QRectF):
        painter.fillRect(rect, QColor("#122019"))
        if not self.has_map():
            return
        if self.diagnostic_only or self.transform().m11() < 0.26 or rect.width() > 9000:
            if self.engine_active():
                self.runtime_renderer.draw_overview(painter, rect)
                return
            if self._base:
                painter.drawPixmap(QRectF(0, 0, WORLD_WIDTH, WORLD_HEIGHT), self._base,
                                   QRectF(0, 0, NATIVE_DIAMOND, NATIVE_DIAMOND))
            return

        if self.engine_active():
            # IMPORTANT: cached RGBA QPixmaps composed independently into
            # 512x256 pieces change partially transparent tile/blend pixels
            # along the chunk seam. On actual Antioch.map, a 1024x512
            # viewport differed by 1,954 pixels in a 24px strip at y=256.
            # Rendering the same native commands straight onto one QPainter
            # surface preserves their order and per-pixel blending. Keep
            # chunk caching for the approximate renderer only.
            self.runtime_renderer.draw_area(painter, rect)
            return

        left = max(0, int(rect.left() // CHUNK_W))
        # QRectF right/bottom are exclusive paint boundaries. Including the
        # chunk starting exactly at them needlessly decoded a third row/column
        # for an exact 1024x512 viewport (nine chunks instead of four).
        right = min((WORLD_WIDTH-1)//CHUNK_W,
                    int((rect.right()-1e-6) // CHUNK_W))
        top = max(0, int(rect.top() // CHUNK_H))
        bottom = min((WORLD_HEIGHT-1)//CHUNK_H,
                     int((rect.bottom()-1e-6) // CHUNK_H))
        # Small bounded, reusable pixmaps. Panning within a chunk does not
        # recompose thousands of grass/stone/shore tiles on every paint event.
        for row in range(top, bottom + 1):
            for column in range(left, right + 1):
                chunk = self._terrain_chunk(column, row)
                painter.drawPixmap(QPointF(column * CHUNK_W, row * CHUNK_H), chunk)

    def _frame(self, group, number):
        try:
            name = katalog.native_name(group, number)
            return self._source.frame(group, name)
        except (Exception, SystemExit) as exc:
            self.message.emit(f"Sprite fehlt: {group}/{number}: {exc}")
            return None

    def set_visual_mappings(self, mappings: OriginalVisualMappings):
        mappings.validate()
        selected = self.selected_original()
        self.visual_mappings = mappings
        self._native_visual_cache.clear()
        self._mapped_asset_signatures = {
            (v.group, v.frame): self._sprite_signature(v.group, v.frame)
            for v in mappings.assignments.values()
        }
        if self.has_map():
            self.rebuild()
            if selected:
                kind, code, record = selected
                for item in self.scene().items():
                    current = item.data(1 if kind == "tree" else 0)
                    if current is not None and current.record_number == record.record_number:
                        item.setSelected(True)
                        break

    def selected_original(self):
        for item in self.scene().selectedItems():
            tree = item.data(1)
            if tree is not None:
                return ("tree", tree.raw_group, tree)
            building = item.data(0)
            if building is not None:
                return ("building", building.type_id, building)
        return None

    def _original_visual(self, kind, raw_code):
        visual = self.visual_mappings.get(kind, raw_code)
        if visual is None:
            return None
        key = (visual.group, visual.frame)
        if key not in self._native_visual_cache:
            frame = self._frame(*key)
            if frame is None:
                self._native_visual_cache[key] = None
            else:
                self._native_visual_cache[key] = (
                    to_pixmap(frame, checkerboard=False), frame.foot
                )
        return self._native_visual_cache[key]

    def _original_graphic_item(self, kind, raw_code, entry, x, y,
                               color, fallback_radius, z):
        center = QPointF(x * TILE_X + 16, y * TILE_Y + 16)
        visual = (None if self.engine_active() and self.use_original_runtime_assets
                  else self._original_visual(kind, raw_code))
        if visual is not None:
            pix, foot = visual
            item = self.scene().addPixmap(pix)
            item.setOffset(-foot[0], -foot[1])
            item.setPos(center)
        else:
            item = self.scene().addEllipse(
                center.x() - fallback_radius, center.y() - fallback_radius,
                fallback_radius * 2, fallback_radius * 2,
                QPen(QColor("#19331c"), 0.6), QBrush(QColor(color))
            )
            if self.engine_active():
                # Native engine paints actual tree/structure sprites in depth
                # order; transparent handles remain for original-data selection.
                item.setPen(QPen(Qt.PenStyle.NoPen))
                item.setBrush(QBrush(Qt.GlobalColor.transparent))
        item.setZValue(z)
        item.setFlag(item.GraphicsItemFlag.ItemIsSelectable)
        item.setData(1 if kind == "tree" else 0, entry)
        return item

    def rebuild(self, focus=None):
        self._items.clear()
        self._sprite_signatures.clear()
        self.scene().clear()
        self._keyboard_marker = None
        if self.show_original_trees:
            for tree in self.original_trees:
                marker = self._original_graphic_item(
                    "tree", tree.raw_group, tree, tree.x, tree.y,
                    "#639c4d", 4, 50000 + tree.y
                )
                marker.setToolTip(
                    f"Originalvegetation #{tree.record_number}: Rohcodes "
                    f"{tree.raw_variant}/{tree.raw_group}/{tree.raw_state}, "
                    f"Kachel {tree.x},{tree.y}; Grafikzuordnung benutzerdefiniert."
                )
        if self.show_original_buildings:
            for entry in self.original_buildings:
                color = ["#c7a462", "#e6b65e", "#75a7e8", "#d18e65", "#83c68d"][
                    (entry.owner or 0) % 5
                ]
                marker = self._original_graphic_item(
                    "building", entry.type_id, entry, entry.x, entry.y,
                    color, 9, 60000 + entry.y
                )
                marker.setToolTip(
                    f"Originalgebäude – Typ-ID {entry.type_id}, Besitzer {entry.owner}, "
                    f"Position {entry.x},{entry.y}, UID {entry.uid}, Rastergröße {entry.footprint}. "
                    "Read-only: exakte Gebäude-Grafikzuordnung noch unbestätigt."
                )
        if self.history:
            for placement in self.history.overlay.objects:
                item = NativePlacedSprite(self, placement, self._frame(placement.group, placement.frame))
                self.scene().addItem(item)
                self._items[placement.id] = item
                self._sprite_signatures[(placement.group, placement.frame)] = (
                    self._sprite_signature(placement.group, placement.frame)
                )
                if placement.id == focus:
                    item.setSelected(True)
        self._update_keyboard_marker()
        self.modified.emit()
        self.viewport().update()

    def _update_keyboard_marker(self):
        """Draw a non-editable keyboard cursor, never saved to the .map/overlay."""
        if self._keyboard_marker is not None:
            self.scene().removeItem(self._keyboard_marker)
            self._keyboard_marker = None
        if self._keyboard_tile is None or not self.has_map():
            return
        x,y = self._keyboard_tile
        if not self.is_editable_native(x,y):
            return
        from PySide6.QtGui import QPen
        self._keyboard_marker = self.scene().addRect(
            QRectF(x*TILE_X+1.0,y*TILE_Y+1.0,TILE_X-2.0,TILE_Y-2.0),
            QPen(QColor("#ffda66"),1.4),QBrush(Qt.BrushStyle.NoBrush)
        )
        self._keyboard_marker.setZValue(250000)
        self._keyboard_marker.setFlag(
            self._keyboard_marker.GraphicsItemFlag.ItemIsSelectable,False
        )

    def _keyboard_anchor(self):
        if self._keyboard_tile is not None:
            return self._keyboard_tile
        # Prefer the currently visible camera rather than a hardcoded
        # fictional world centre; fall back to a real map building/cell.
        pos=self.mapToScene(self.viewport().rect().center())
        candidates=[(floor(pos.x()/TILE_X),floor(pos.y()/TILE_Y)),
                    (400,400)]
        if self.original_buildings:
            first=self.original_buildings[0]
            candidates.append((first.x,first.y))
        for x,y in candidates:
            if self.is_editable_native(x,y):
                return x,y
        return None

    def _select_keyboard_tile(self, x, y):
        if not self.is_editable_native(x,y):
            self.message.emit("Tastaturcursor: unspielbarer Kartenrand.")
            return False
        self._keyboard_tile=x,y
        self._update_keyboard_marker()
        self.center_native(x,y)
        self.select_native(x,y)
        self.message.emit(
            f"Tastaturkachel ({x},{y}) – Pfeiltasten bewegen; "
            "Enter wählt aus oder platziert; Esc beendet."
        )
        return True

    def _place_native(self,x,y):
        if not self.history or not self._placing:
            return None
        index=tile_index(x,y)
        if (self.native_geometry is not None and
                self.native_geometry.is_padding_index(index)):
            raise SceneError("Platzierung im Originalkarten-Rand nicht erlaubt")
        group,frame=self._placing
        ident=self.history.place(group,frame,x,y,team=self._placement_team)
        self.rebuild(focus=ident)
        return ident

    def _selection_changed(self):
        selected = next((item.object_id for item in self.scene().selectedItems()
                         if isinstance(item, NativePlacedSprite)), "")
        self.object_selected.emit(selected)
        if not selected:
            marker = next((item.data(0) for item in self.scene().selectedItems()
                           if item.data(0) is not None), None)
            if marker is not None:
                self.original_building_selected.emit(marker)
                self.message.emit(f"Originalgebäude: Typ-ID {marker.type_id}, Besitzer {marker.owner}, "
                                  f"Kachel ({marker.x},{marker.y}), UID {marker.uid} (nur lesen)")
            tree = next((item.data(1) for item in self.scene().selectedItems()
                         if item.data(1) is not None), None)
            if tree is not None:
                self.original_tree_selected.emit(tree)
                self.message.emit(
                    f"Original-Vegetation: Kachel ({tree.x},{tree.y}), "
                    f"Rohcode {tree.raw_group} (nur lesen)"
                )

    def set_original_trees_visible(self, visible):
        self.show_original_trees = bool(visible)
        self.refresh_terrain_assets()
        self.rebuild(focus=self.select_id())

    def set_original_buildings_visible(self, visible):
        self.show_original_buildings = bool(visible)
        self.rebuild(focus=self.select_id())

    def select_id(self):
        return next((item.object_id for item in self.scene().selectedItems()
                     if isinstance(item, NativePlacedSprite)), None)

    def set_placement_team(self, colour):
        """Keep the original Sandkasten's team-mask choice until next change."""
        if colour not in TEAM_COLOURS:
            self.message.emit(f"Ungültige Teamfarbe: {colour!r}")
            return False
        if self._placement_team != colour:
            self._placement_team = colour
            self.placement_changed.emit()
        return True

    def arm_placement(self, group, frame, team=None):
        if not self.has_map():
            self.message.emit("Zuerst eine Originalkarte mit nativem Tile-Layout öffnen.")
            return False
        if (not isinstance(group, str) or not 1 <= len(group) <= 256 or
                re.fullmatch(r"[A-Za-z0-9_-]+", group) is None or
                type(frame) is not int or not 0 <= frame <= 999999):
            self.message.emit("Ungültige Sprite-Gruppe oder Framenummer; keine Platzierung.")
            return False
        if team is not None and not self.set_placement_team(team):
            return False
        self._placing = (group, frame)
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.message.emit(
            f"Platzieren auf Originalkarte: {group}/{frame}, Team {self._placement_team}; "
            "Esc beendet."
        )
        self.placement_changed.emit()
        return True

    def cancel_placement(self):
        """Stop test placement without discarding, saving or undoing the overlay."""
        was_placing = self._placing is not None
        self._placing = None
        self._keyboard_tile = None
        self._update_keyboard_marker()
        self.unsetCursor()
        if was_placing:
            self.message.emit("Platzierung beendet; vorhandene Overlays bleiben erhalten.")
        self.placement_changed.emit()

    def _from_scene(self, point):
        if self.engine_active():
            return self.runtime_renderer.pick_tile(point.x(), point.y())
        return floor(point.x() / TILE_X), floor(point.y() / TILE_Y)

    def select_native(self, x, y):
        self.last_engine_pick = None
        try:
            index = tile_index(x, y)
        except (IndexError, TypeError):
            return False
        if self.native_geometry is not None and self.native_geometry.is_padding_index(index):
            self.message.emit("Unspielbarer Originalkarten-Rand: Abschnitt 3003 = 16")
            return False
        values = self._channels.at(x, y)
        self.picked.emit(x, y, values)
        return True

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_origin = event.position().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self.has_map():
            point = self.mapToScene(event.position().toPoint())
            graphic = (self.runtime_renderer.pick_graphic(point.x(), point.y())
                       if self.engine_active() and not self._placing else None)
            x, y = (graphic.x, graphic.y) if graphic is not None else self._from_scene(point)
            if self._placing:
                try:
                    self._place_native(x,y)
                except (IndexError, SceneError) as exc:
                    self.message.emit(f"Ungültige Position: {exc}")
                event.accept()
                return
            checked = self.select_native(x, y)
            super().mousePressEvent(event)
            if checked and graphic is not None:
                self.last_engine_pick = graphic
                self.engine_sprite_picked.emit(graphic)
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._pan_origin is not None:
            now = event.position().toPoint()
            delta = now - self._pan_origin
            self._pan_origin = now
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_origin = None
            self.unsetCursor()
            if self._placing:
                self.setCursor(Qt.CursorShape.CrossCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        self.zoom(1.18 if event.angleDelta().y() > 0 else 1 / 1.18)
        event.accept()

    def keyPressEvent(self, event):
        key=event.key()
        if key == Qt.Key.Key_Escape:
            self.cancel_placement()
            event.accept()
            return
        if key in (
            Qt.Key.Key_Left, Qt.Key.Key_Right,
            Qt.Key.Key_Up, Qt.Key.Key_Down,
        ) and self.has_map():
            anchor=self._keyboard_anchor()
            if anchor is not None:
                dx,dy={
                    Qt.Key.Key_Left:(-1,0),Qt.Key.Key_Right:(1,0),
                    Qt.Key.Key_Up:(0,-1),Qt.Key.Key_Down:(0,1),
                }[key]
                self._select_keyboard_tile(anchor[0]+dx,anchor[1]+dy)
            event.accept()
            return
        if key in (Qt.Key.Key_Return,Qt.Key.Key_Enter,Qt.Key.Key_Space) and self.has_map():
            anchor=self._keyboard_anchor()
            if anchor is not None:
                x,y=anchor
                if self._placing:
                    try:
                        self._place_native(x,y)
                    except (IndexError,SceneError) as exc:
                        self.message.emit(f"Ungültige Position: {exc}")
                else:
                    self._select_keyboard_tile(x,y)
            event.accept()
            return
        if key == Qt.Key.Key_Delete and self.select_id():
            self.delete_selected()
            event.accept()
            return
        super().keyPressEvent(event)

    def finish_move(self, ident, px, py):
        if not self.history:
            return
        x, y = self._from_scene(QPointF(px, py))
        try:
            index = tile_index(x, y)
            if (self.native_geometry is not None and
                    self.native_geometry.is_padding_index(index)):
                raise SceneError("Verschieben in den Originalkarten-Rand ist nicht erlaubt")
            self.history.move(ident, x, y)
            self.rebuild(focus=ident)
        except SceneError as exc:
            self.message.emit(str(exc))
            self.rebuild(focus=ident)

    def delete_selected(self):
        ident = self.select_id()
        if self.history and ident:
            self.history.delete(ident)
            self.rebuild()

    def undo(self):
        if self.history:
            focus = self.select_id()
            self.history.undo()
            self.rebuild(focus)

    def redo(self):
        if self.history:
            focus = self.select_id()
            self.history.redo()
            self.rebuild(focus)

    def refresh_changed(self):
        if not self.has_map():
            return
        changes = [key for key, old in self._texture_signatures.items()
                   if self._signature(*key) != old]
        if changes:
            self.refresh_terrain_assets()
        for key, previous in tuple(self._sprite_signatures.items()):
            current = self._sprite_signature(*key)
            if current != previous:
                self._sprite_signatures[key] = current
                self.refresh_asset(*key)
        for key, previous in tuple(self._mapped_asset_signatures.items()):
            current = self._sprite_signature(*key)
            if current != previous:
                self._mapped_asset_signatures[key] = current
                self.refresh_asset(*key)
        # Source-index changes are propagated without reloading the .map.

    def preview_object_frame(self, ident: str, number: int) -> bool:
        if not self.has_map():
            return False
        obj = next((o for o in self.history.overlay.objects if o.id == ident), None)
        item = self._items.get(ident)
        if obj is None or item is None or not isinstance(number, int) or number < 0:
            return False
        frame = self._frame(obj.group, number)
        if frame is None:
            return False
        item.update_frame(frame, obj)
        return True

    def restore_object_frame(self, ident: str):
        if self.has_map():
            obj = next((o for o in self.history.overlay.objects if o.id == ident), None)
            if obj is not None:
                self.preview_object_frame(ident, obj.frame)

    def set_occupancy_overlay(self, enabled: bool):
        self.show_occupancy = bool(enabled)
        self.viewport().update()

    def drawForeground(self, painter: QPainter, rect: QRectF):
        """3004 overlay: native occupancy diagnostics, not a fabricated sprite."""
        if (not self.show_occupancy or self.native_geometry is None or
                self.native_geometry.occupancy is None or self.transform().m11() < 0.22):
            return
        from PySide6.QtGui import QFont
        painter.save()
        painter.setPen(QPen(QColor("#f4d54f"), 0.9))
        painter.setBrush(QBrush(QColor(240, 160, 50, 65)))
        x0 = max(0, int(rect.left() / TILE_X) - 1)
        x1 = min(799, int(rect.right() / TILE_X) + 1)
        y0 = max(0, int(rect.top() / TILE_Y) - 1)
        y1 = min(799, int(rect.bottom() / TILE_Y) + 1)
        for y in range(y0, y1+1):
            width = 2 * (y+1 if y<400 else 800-y)
            left = (800-width)//2
            first = y*(y+1) if y<400 else (
                160400 + 800*(y-400) - (y-400)*(y-401))
            for x in range(max(x0,left), min(x1+1,left+width)):
                raw_id = self.native_geometry.occupancy_id(first+x-left)
                if raw_id:
                    painter.drawRect(QRectF(x*TILE_X+2, y*TILE_Y+2,
                                            TILE_X-4, TILE_Y-4))
        painter.restore()

    def set_diagnostic_only(self, enabled: bool):
        self.diagnostic_only = bool(enabled)
        self._terrain_chunks.clear()
        self.rebuild(focus=self.select_id())
        self.viewport().update()

    def refresh_terrain_assets(self):
        """Invalidate cached terrain immediately after a graphic-editor save."""
        if not self.has_map():
            return
        self._source = FrameSource("arbeit", log=lambda _: None)
        self._textures.clear()
        self._texture_signatures.clear()
        self._terrain_chunks.clear()
        if self.runtime_renderer is not None:
            self.runtime_renderer.invalidate()
        self.viewport().update()

    def refresh_asset(self, group, number):
        if not self.has_map():
            return
        self._sprite_signatures[(group, number)] = self._sprite_signature(group, number)
        self._source = FrameSource("arbeit", log=lambda _: None)
        if self.runtime_renderer is not None:
            self.runtime_renderer.invalidate()
            self._terrain_chunks.clear()
        if any(v.group == group and v.frame == number
               for v in self.visual_mappings.assignments.values()):
            self._native_visual_cache.pop((group, number), None)
            self._mapped_asset_signatures[(group, number)] = (
                self._sprite_signature(group, number))
            self.set_visual_mappings(self.visual_mappings)
        name = katalog.native_name(group, number)
        for obj in self.history.overlay.objects:
            if obj.group == group and obj.frame == number:
                item = self._items.get(obj.id)
                if item:
                    item.update_frame(self._frame(group, number), obj)
        for material, (texture_group, _) in TEXTURES.items():
            if texture_group == group:
                self._textures.clear()
                self._texture_signatures.clear()
                self._terrain_chunks.clear()
                self.viewport().update()
                break

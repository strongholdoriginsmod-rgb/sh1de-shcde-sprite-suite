"""Sandbox Studio: interactive read-only explorer for authentic SHCDE radar maps.

Milestone 1: original map selection, decompression, camera, minimap, inspection,
preview export. Full sprite/terrain decoding is deliberately NOT represented
as implemented in this milestone.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from stronghold_europe_de.sandbox.map_importer import (  # noqa: E402
    MapFormatError, MapDecoderUnavailable, find_maps, load_radar_preview,
    PREVIEW_SIZE,
)
from stronghold_europe_de.sandbox.scene_model import (
    SceneError, EditableScene, load_scene, save_scene,
)
from stronghold_europe_de.sandbox.map_sections import (
    discover_sections, load_native_tile_values, render_native_tile_values,
    tile_index, NATIVE_DIAMOND,
)
from stronghold_europe_de.sandbox.native_overlay import load_overlay, save_overlay
from stronghold_europe_de.sandbox.native_terrain_mapping import (
    TerrainTestMappings, TerrainMappingError, load_terrain_tests, save_terrain_tests,
)
from stronghold_europe_de.sandbox.native_surface_mapping import (
    SurfaceTestMappings, load_surface_tests, save_surface_tests,
)
from stronghold_europe_de.sandbox.native_visual_mapping import (
    OriginalVisualMappings, VisualMappingError, load_mappings, save_mappings,
)

from PySide6.QtCore import Qt, Signal, QTimer, QSignalBlocker
from PySide6.QtGui import QAction, QColor, QImage, QPen, QPixmap, QFontDatabase, QFont
from PySide6.QtWidgets import (
    QApplication, QDockWidget, QFileDialog, QGraphicsScene, QGraphicsView,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMainWindow, QMessageBox, QPushButton, QToolBar, QTreeWidget, QTabWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget, QScrollArea,
)

# The Standalone Studio and the Suite tab both respect user configuration.
# Never silently point a normal user's installation at a local QA disk.
from stronghold_europe_de.sandbox.maps_configuration import configured_map_root
DEFAULT_GAME = configured_map_root(ROOT)


class MapView(QGraphicsView):
    picked = Signal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setBackgroundBrush(QColor("#20262a"))
        self.setMouseTracking(True)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self._map_pix = None
        self._marker = None
        self._pan_origin = None
        self._zoom = 1.0

    def display(self, pil_image):
        image = pil_image.convert("RGB")
        qimage = QImage(image.tobytes(), image.width, image.height,
                        image.width * 3, QImage.Format.Format_RGB888).copy()
        self.scene().clear()
        self._map_pix = self.scene().addPixmap(QPixmap.fromImage(qimage))
        self._map_pix.setTransformationMode(Qt.TransformationMode.FastTransformation)
        self.scene().setSceneRect(0, 0, image.width, image.height)
        self._marker = None
        self.fit_map()

    def fit_map(self):
        if self._map_pix:
            self.resetTransform()
            self.fitInView(self._map_pix, Qt.AspectRatioMode.KeepAspectRatio)
            self._zoom = 1.0

    def zoom(self, ratio):
        if not self._map_pix:
            return
        target = self._zoom * ratio
        if 0.25 <= target <= 20:
            self.scale(ratio, ratio)
            self._zoom = target

    def select_pixel(self, x, y):
        if not self._map_pix:
            return
        if self._marker:
            self.scene().removeItem(self._marker)
        self._marker = self.scene().addRect(
            x, y, 1, 1, QPen(QColor("#ffbd4b"), 0.15))
        self._marker.setZValue(100)
        self.picked.emit(x, y)

    def wheelEvent(self, event):
        self.zoom(1.2 if event.angleDelta().y() > 0 else 1 / 1.2)
        event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_origin = event.position().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._map_pix:
            pos = self.mapToScene(event.position().toPoint())
            x, y = int(pos.x()), int(pos.y())
            rect = self.scene().sceneRect()
            if 0 <= x < rect.width() and 0 <= y < rect.height():
                self.select_pixel(x, y)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._pan_origin is not None:
            delta = event.position().toPoint() - self._pan_origin
            self._pan_origin = event.position().toPoint()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_origin = None
            self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class MiniMapView(QGraphicsView):
    def __init__(self, main_view, parent=None):
        super().__init__(parent)
        self.map_view = main_view
        self.setScene(main_view.scene())
        self.setMinimumHeight(190)
        self.setMaximumHeight(260)
        self.setBackgroundBrush(QColor("#222a23"))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fitInView(self.scene().sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.map_view.centerOn(self.mapToScene(event.position().toPoint()))
            event.accept()
            return
        super().mousePressEvent(event)


class SandboxStudio(QMainWindow):
    # This is a working-overlay baseline signal, not a game save or release.
    overlay_state_changed = Signal()

    def __init__(self, maps_root=DEFAULT_GAME):
        super().__init__()
        # Windows-local system font. The Qt offscreen plugin otherwise reports
        # no font families and renders boxes instead of glyphs; no fonts are bundled.
        if not QFontDatabase.families():
            font_path = Path("C:/Windows/Fonts/segoeui.ttf")
            if font_path.is_file():
                font_id = QFontDatabase.addApplicationFont(str(font_path))
                loaded = QFontDatabase.applicationFontFamilies(font_id)
                if loaded:
                    QApplication.instance().setFont(QFont(loaded[0], 10))
        self.setWindowTitle("Sprite Suite – Sandbox Studio (Originalkarten)")
        self.resize(1520, 960)
        self._infos = []
        self._image = None
        self._height_image = None
        self._native_values = None
        self._current = None
        self._root = Path(maps_root)
        self._scene_path = None
        self._legacy_original_source = None
        self._legacy_dialog = None
        self._saved_scene = None
        self._syncing_asset_selection = False
        self._saved_overlay = None
        self._overlay_path = None
        self._terrain_test_path = None
        self._surface_test_path = None
        self._pixel_dialogs = []
        self._compare_dialog = None
        self.original_hud = None
        self._hud_bindings = None
        self._hud_bindings_path = ROOT / 'sandbox' / 'mappings' / 'hud-original-commands.json'
        self._mapping_path = ROOT / "sandbox" / "mappings" / "native-original-visuals.json"
        self._native_visuals = OriginalVisualMappings()
        self._init_ui()
        from sandbox_qt_locale import QtStudioLanguage, preferred_language
        self.ui_language = QtStudioLanguage(self, language=preferred_language(ROOT))
        # Runtime engine/map labels are recomputed after user actions. Queue
        # the localisation pass *after* other signal handlers have set text.
        # No translation modifies actual map metadata or saved object IDs.
        def refresh_language_after_signal(*_):
            QTimer.singleShot(0, self.ui_language.refresh)
        self.native_canvas.modified.connect(refresh_language_after_signal)
        self.native_canvas.picked.connect(refresh_language_after_signal)
        self.native_canvas.engine_sprite_picked.connect(refresh_language_after_signal)
        self.board.scene_changed.connect(refresh_language_after_signal)
        try:
            self._native_visuals = load_mappings(self._mapping_path)
        except VisualMappingError as exc:
            broken = self._mapping_path
            self._mapping_path = broken.with_name(
                broken.name.removesuffix(".json") + ".recovery.json")
            self.statusBar().showMessage(
                f"Ungültige Originalgrafik-Zuordnungen bleiben erhalten: {exc}; "
                f"neue Zuordnungen unter {self._mapping_path}"
            )
        self.native_canvas.set_visual_mappings(self._native_visuals)
        self.scan(self._root)
        # The first map is scanned after the initial static translation.
        # Translate its actual counts/status once those values exist.
        self.ui_language.refresh()
        self._update_action_context()

    def set_ui_language(self, code):
        # QtStudioLanguage translates the EXISTING user status in place.
        # Never replace an arbitrary status message merely because the
        # language changed while the radar tab happened to be selected.
        self.ui_language.set_language(code)
        self._update_action_context()

    def _update_action_context(self, *_):
        """One truth source for File/Edit QAction labels, status and safety.

        Menus/shortcuts must represent the ACTUAL visible editing surface,
        not a hidden Testfeld when Radar/Raw Data are displayed. Historical
        Sandkasten tools are only claimed on views where they really work.
        """
        actions = getattr(self, "_workspace_actions", {})
        if not actions:
            return
        from re import fullmatch

        page = self.tabs.currentIndex()
        board = page == 1
        native = page == 3 and self.native_canvas.has_map()
        readonly = not (board or native)
        en = getattr(getattr(self, "ui_language", None), "language", "de") == "en"
        history = self.native_canvas.history if native else None
        overlay_dirty = bool(
            history is not None and self._saved_overlay is not None and
            history.overlay.serialize() != self._saved_overlay
        )
        group = self.asset_preview.group.currentText().strip()
        valid_group = bool(
            1 <= len(group) <= 256 and fullmatch(r"[A-Za-z0-9_-]+", group)
        )
        selected = (
            bool(self.board.selected_id()) if board else
            bool(self.native_canvas.select_id()) if native else False
        )
        can_undo = (
            self.board.history.can_undo if board else
            bool(history and history.undo_stack)
        )
        can_redo = (
            self.board.history.can_redo if board else
            bool(history and history.redo_stack)
        )

        def configure(key, enabled, tooltip, label=None):
            action = actions.get(key)
            if action is None:
                return
            action.setEnabled(bool(enabled))
            action.setToolTip(tooltip)
            action.setStatusTip(tooltip)
            if label is not None:
                action.setText(label)

        save_label = (
            ("Save test scene" if en else "Testszene speichern") if board else
            ("Save working overlay" if en else "Arbeits-Overlay speichern") if native else
            ("Save current scene" if en else "Aktuelle Szene speichern")
        )
        configure("save", not readonly,
                  ("Save only the visible editable workspace" if en else
                   "Nur die sichtbare bearbeitbare Arbeitsfläche speichern; "
                   "Radar und Rohdaten sind schreibgeschützt"),
                  save_label)
        configure("overlay", native and overlay_dirty,
                  ("Only unsaved changes to this original map's working overlay"
                   if en else
                   "Nur ungespeicherte Änderungen des Arbeits-Overlays; "
                   "Originalkarte bleibt unangetastet"))
        configure("original_radar_export", self._image is not None,
                  ("Export the source radar image, never the test scene" if en
                   else "Nur das originale Radarbild exportieren; nicht das Testfeld"))
        configure("reload", board or self._current is not None,
                  ("Reload this Testfeld's visible working frames" if en and board
                   else "Arbeitsgrafiken des Testfelds neu laden" if board else
                   "Reload the original map" if en else "Originalkarte neu laden"),
                  ("Reload test sprites" if en else "Sprite-Grafiken neu laden")
                  if board else ("Reload original map" if en else
                                 "Kartenansicht neu laden"))
        configure("place", (board or native) and valid_group,
                  ("Arm a sprite for the visible editable surface" if en else
                   "Sprite nur in der sichtbaren Arbeitsfläche vormerken"))
        configure("delete", selected,
                  ("Remove only a selected editable sprite" if en else
                   "Nur ausgewähltes bearbeitbares Sprite entfernen"))
        configure("undo", can_undo,
                  ("Undo only this workspace's working history" if en else
                   "Nur den Bearbeitungsverlauf dieser Arbeitsfläche rückgängig"))
        configure("redo", can_redo,
                  ("Redo only this workspace's working history" if en else
                   "Nur den Bearbeitungsverlauf dieser Arbeitsfläche wiederholen"))
        configure("legacy", board and self.board.history.scene.is_legacy_v1,
                  ("Edit original V1 ground seed, GM1 composites and animation"
                   if en else
                   "Original-V1-Boden, GM1-Komposite und Animationsdaten bearbeiten"))
        configure("ground", board,
                  ("Editor-only ground graphics; NOT an original map" if en else
                   "Bodensprites nur im isometrischen Testfeld; "
                   "keine Originalkartentextur"))
        configure("pixel_edit", board or native,
                  ("Edit a working-copy sprite for this active view" if en else
                   "Arbeitskopie eines Sprites für die aktive Ansicht bearbeiten"))

    def _init_ui(self):
        from sandbox_test_board import SpriteTestBoard
        from sandbox_native_canvas import NativeMapCanvas
        self.native_canvas = NativeMapCanvas()
        self.native_canvas.setObjectName("sandbox_game_map")
        self.native_canvas.picked.connect(self._native_tile_picked)
        self.native_canvas.message.connect(self.statusBar().showMessage)
        self.native_canvas.modified.connect(self._overlay_changed)
        self.viewer = MapView()
        self.viewer.setObjectName("sandbox_original_radar")
        self.viewer.picked.connect(self._pixel_picked)
        self.board = SpriteTestBoard()
        self.board.setObjectName("sandbox_test_board")
        self.height_view = MapView()
        self.height_view.setObjectName("sandbox_native_tiles")
        self.height_view.picked.connect(self._raw_pixel_picked)
        self.board.status_message.connect(self.statusBar().showMessage)
        self.board.scene_changed.connect(self._editor_changed)
        self.tabs = QTabWidget(self)
        self.tabs.addTab(self.viewer, "Originalkarte: Radar")
        self.tabs.addTab(self.board, "Interaktives Sprite-Testfeld")
        self.tabs.addTab(self.height_view, "Native Kacheldaten 3005 (Diagnose)")
        self.tabs.addTab(self.native_canvas, "Spielkarte (Original-Tiles + Sprites)")
        self._last_workspace_tab = self.tabs.currentIndex()
        self.tabs.currentChanged.connect(self._tab_changed)
        self.setCentralWidget(self.tabs)
        self._saved_scene = self.board.history.scene.serialize()

        toolbar = QToolBar("Schnellzugriff", self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        file_menu = self.menuBar().addMenu("Datei")
        view_menu = self.menuBar().addMenu("Ansicht")
        edit_menu = self.menuBar().addMenu("Bearbeiten")

        self._workspace_actions = {}
        def menu_action(menu, label, shortcut, callback, quick=False, tip=None,
                        context_key=None):
            action = QAction(label, self)
            if shortcut:
                action.setShortcut(shortcut)
            if tip:
                action.setToolTip(tip)
            action.triggered.connect(callback)
            if context_key:
                action.setObjectName("sandbox_command_" + context_key)
                self._workspace_actions[context_key] = action
            menu.addAction(action)
            if quick:
                toolbar.addAction(action)
            return action

        menu_action(file_menu, "Originalkarte öffnen", "Ctrl+O", self.choose_map, quick=True)
        menu_action(file_menu, "Originalkartenordner auswählen", "Ctrl+Shift+O", self.choose_folder)
        menu_action(file_menu, "Neues Sprite-Testfeld", "Ctrl+N", self.new_scene)
        menu_action(file_menu, "Sprite-Testszene öffnen", "Ctrl+Alt+O", self.open_test_scene)
        menu_action(file_menu, "Aktuelle Szene speichern", "Ctrl+S",
                    self.save_active, quick=True, context_key="save")
        menu_action(file_menu, "Karten-Overlay speichern", "Ctrl+Shift+M",
                    self.save_map_overlay, context_key="overlay")
        menu_action(file_menu, "Original-Radarbild als PNG exportieren",
                    "Ctrl+Shift+S", self.save_preview,
                    context_key="original_radar_export")
        menu_action(file_menu, "Aktuelle Kartenansicht als PNG exportieren",
                    "Ctrl+Shift+P", self.export_viewport)
        menu_action(file_menu, "Pixelabgleich mit originalem Spielbild",
                    "Ctrl+Shift+C", self.open_reference_comparison)

        toolbar.addSeparator()
        menu_action(view_menu, "Original-Radar", "F1",
                    lambda: self.tabs.setCurrentIndex(0), quick=True)
        menu_action(view_menu, "Spielkarte mit Sprites", "F4",
                    self.show_native_map, quick=True)
        menu_action(view_menu, "Interaktives Testfeld", "F2",
                    self.show_test_field, quick=True)
        menu_action(view_menu, "Native Kachel-Rohdaten (Diagnose)", "F3",
                    self.show_height_section, quick=True,
                    tip="Echte originale 800-Reihen-Kacheldaten als Diamant, nicht vollständig texturiertes Terrain")
        menu_action(view_menu, "Kartenansicht neu laden", "F5",
                    self.reload_current, context_key="reload")
        menu_action(edit_menu, "Historische V1-Szene verlustfrei bearbeiten",
                    "Ctrl+Alt+V", self.open_legacy_scene_editor, context_key="legacy")
        menu_action(view_menu, "Gesamtansicht", "Home",
                    lambda: self._active_view().fit_map())
        menu_action(view_menu, "Vergrößern", "Ctrl++", lambda: self.zoom_active(1.2))
        menu_action(view_menu, "Verkleinern", "Ctrl+-", lambda: self.zoom_active(1 / 1.2))

        ground = QAction("Echte Bodensprites (Testfeld)", self)
        ground.setCheckable(True)
        ground.setToolTip(
            "Verwendet lokale tile_land8-Sprites als Testboden; keine Originalmap-Extraktion"
        )
        ground.toggled.connect(self.board.set_ground_sprites)
        view_menu.addAction(ground)
        self._workspace_actions["ground"] = ground
        ground.setObjectName("sandbox_command_ground")
        toolbar.addSeparator()
        menu_action(edit_menu, "Sprite platzieren", "P",
                    self.arm_asset_placement, quick=True, context_key="place")
        menu_action(edit_menu, "Sprite-Pixel direkt bearbeiten", "Ctrl+E",
                    self.open_pixel_editor, context_key="pixel_edit")
        menu_action(edit_menu, "Originalobjekt-Spritegrafik zuordnen",
                    "Ctrl+Shift+G", self.assign_original_visual)
        menu_action(edit_menu, "Originalobjekt-Spritegrafik zurücksetzen",
                    "Ctrl+Alt+G", self.clear_original_visual)
        menu_action(edit_menu, "Objekt löschen", "Del",
                    self.delete_test_object, context_key="delete")
        menu_action(edit_menu, "Rückgängig", "Ctrl+Z",
                    self.undo_test, quick=True, context_key="undo")
        menu_action(edit_menu, "Wiederholen", "Ctrl+Y",
                    self.redo_test, quick=True, context_key="redo")
        toolbar.addAction(ground)

        sidebar = QWidget()
        side_layout = QVBoxLayout(sidebar)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Originalkarten durchsuchen …")
        self.filter.textChanged.connect(self._update_list)
        self.maplist = QListWidget()
        self.maplist.itemActivated.connect(self._open_from_list)
        self.maplist.itemClicked.connect(self._open_from_list)
        side_layout.addWidget(self.filter)
        side_layout.addWidget(self.maplist, 1)
        self.mapcount = QLabel()
        side_layout.addWidget(self.mapcount)
        maps_dock = self._dock("Originalkarten", sidebar, Qt.DockWidgetArea.LeftDockWidgetArea, 260)
        from sandbox_sprite_palette import SpritePalette
        self.sprite_palette = SpritePalette(self)
        palette_dock = self._dock("Sprite-Palette", self.sprite_palette,
                                  Qt.DockWidgetArea.LeftDockWidgetArea, 260)
        self.tabifyDockWidget(maps_dock, palette_dock)
        palette_dock.raise_()
        self.sprite_palette.frame_selected.connect(self._palette_select)
        self.sprite_palette.placement_requested.connect(self._palette_place)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        self.minimap = MiniMapView(self.viewer)
        right_layout.addWidget(QLabel("Echte Radarvorschau der Originalkarte"))
        right_layout.addWidget(self.minimap)
        self.info = QTreeWidget()
        self.info.setColumnCount(2)
        self.info.setHeaderLabels(["Eigenschaft", "Wert"])
        right_layout.addWidget(self.info, 1)
        radar_dock = self._dock("Karte & Minikarte", right, Qt.DockWidgetArea.RightDockWidgetArea, 280)

        from sandbox_asset_preview import AssetPreview
        from sandbox_editor_panel import ObjectInspector
        self.asset_preview = AssetPreview(self)
        asset_dock = self._dock("Grafikvorschau / Live-Reload", self.asset_preview,
                                Qt.DockWidgetArea.RightDockWidgetArea, 300)
        self.inspector = ObjectInspector(self.board)
        self.inspector_dock = self._dock("Objekt-Inspector", self.inspector,
                                         Qt.DockWidgetArea.RightDockWidgetArea, 290)
        self.tabifyDockWidget(radar_dock, asset_dock)
        self.tabifyDockWidget(asset_dock, self.inspector_dock)
        asset_dock.raise_()
        self.asset_preview.asset_updated.connect(self.board.refresh_assets)
        self.asset_preview.asset_updated.connect(self._update_map_asset)
        # One BC7 mode for the preview AND the live isometric test field,
        # matching sandkasten.FrameSource(bc7=...) in the original tool.
        self.asset_preview.bc7.toggled.connect(self.board.set_bc7_simulation)
        self.board.selected_id_changed.connect(self._asset_from_selection)
        self.native_canvas.object_selected.connect(self._map_sprite_selected)

        from sandbox_native_panel import NativeMiniMap, NativeObjectInspector
        self.native_minimap = NativeMiniMap(self.native_canvas)
        self.native_inspector = NativeObjectInspector(self.native_canvas)
        self.native_inspector.assign_native_visual.connect(self.assign_original_visual)
        self.native_inspector.clear_native_visual.connect(self.clear_original_visual)
        self.native_inspector.assign_terrain_test.connect(self.assign_terrain_test)
        self.native_inspector.clear_terrain_test.connect(self.clear_terrain_test)
        self.native_inspector.assign_surface_test.connect(self.assign_surface_test)
        self.native_inspector.clear_surface_test.connect(self.clear_surface_test)
        self.native_inspector.edit_engine_tile.connect(self.edit_runtime_tile)
        self.native_canvas.engine_sprite_picked.connect(self._show_engine_sprite_selection)
        native_tools = QWidget()
        native_layout = QVBoxLayout(native_tools)
        self._native_mode_info = QLabel("Original-Engine wird für unterstützte Spielversionen geprüft.")
        self._native_mode_info.setWordWrap(True)
        native_layout.addWidget(self._native_mode_info)
        native_layout.addWidget(self.native_minimap)
        inspector_scroll = QScrollArea()
        inspector_scroll.setWidgetResizable(True)
        inspector_scroll.setWidget(self.native_inspector)
        self._native_inspector_scroll = inspector_scroll
        inspector_scroll.setMinimumHeight(180)
        native_layout.addWidget(inspector_scroll, 1)
        native_dock = self._dock("Originalkarte / Werkzeug-Inspector", native_tools,
                                 Qt.DockWidgetArea.RightDockWidgetArea, 300)
        self.tabifyDockWidget(self.inspector_dock, native_dock)
        self._native_dock = native_dock

        label = QLabel(
            "Spielkarte: Original-Engine berechnet Sprite-IDs, Höhen, Vegetation und "
            "Gebäudeteile in einem isolierten pausierten Snapshot. Qt zeichnet lokale "
            "Spiel- oder Arbeitsgrafiken; vollständige Unity-Shaderparität ist noch offen. "
            "Originaldateien werden nur gelesen. Mausrad: Zoom · Mittlere Maustaste: "
            "Karte verschieben · Linksklick: Radarposition wählen · Minikarte: Kamera bewegen."
        )
        label.setWordWrap(True)
        label.setContentsMargins(14, 9, 14, 9)
        notice = self._dock("Darstellungsstatus", label, Qt.DockWidgetArea.BottomDockWidgetArea, 100)
        notice.setMaximumHeight(150)
        from sandbox_animation_panel import SpriteAnimationPanel
        self.animation_panel = SpriteAnimationPanel(self.board)
        animation_dock = self._dock("Animation / Frame-Test", self.animation_panel,
                                    Qt.DockWidgetArea.BottomDockWidgetArea, 100)
        animation_dock.setMaximumHeight(150)
        self._animation_dock = animation_dock
        self.tabifyDockWidget(notice, animation_dock)
        from sandbox_game_hud import NativeGameHUD
        self.native_hud = NativeGameHUD(self.native_canvas, self)
        hud_dock = self._dock("Sandbox-Spiel-HUD / Live-Test", self.native_hud,
                              Qt.DockWidgetArea.BottomDockWidgetArea, 160)
        hud_dock.setMaximumHeight(190)
        self.tabifyDockWidget(animation_dock, hud_dock)
        self._hud_dock = hud_dock
        self.native_hud.save_requested.connect(self.save_map_overlay)
        self.native_hud.edit_sprite_requested.connect(self.open_hud_pixel_editor)
        # Keep every visible selector on the same group/frame. A HUD click
        # must not later edit the stale palette or inspector selection.
        self.native_hud.group.currentTextChanged.connect(self._sync_preview_from_hud)
        self.native_hud.frame.valueChanged.connect(self._sync_preview_from_hud)
        self.asset_preview.group.currentTextChanged.connect(self._sync_hud_from_preview)
        self.asset_preview.frame.valueChanged.connect(self._sync_hud_from_preview)
        self._sync_hud_from_preview()
        # An opt-in XAML-resource view: original element positions and local
        # atlas icon pixels, but not a claimed game-engine GUI replica.
        from sandbox_hud_original_art import OriginalHudArtPanel, HudContractError
        from stronghold_europe_de.sandbox.hud_command_bindings import (
            HudCommandBindings, load_bindings
        )
        try:
            self.original_hud = OriginalHudArtPanel(self)
            allowed = {
                obj["command"] for obj in self.original_hud.contract["commands"]
                if obj["command"]
            }
            try:
                self._hud_bindings = load_bindings(self._hud_bindings_path, allowed)
            except (ValueError, OSError, KeyError) as exc:
                self._hud_bindings_path = self._hud_bindings_path.with_name(
                    "hud-original-commands.recovery.json"
                )
                self._hud_bindings = HudCommandBindings(allowed=allowed)
                self.statusBar().showMessage(
                    f"HUD-Zuordnung beschädigt, originale Datei bleibt erhalten: {exc}"
                )
            self.original_hud.command_selected.connect(self._hud_art_selected)
            self.original_hud.bind_requested.connect(self._hud_art_bind)
            self.original_hud.clear_requested.connect(self._hud_art_clear)
            art_dock = self._dock(
                "Original-XAML-Grafiken / HUD-Test",
                self.original_hud, Qt.DockWidgetArea.BottomDockWidgetArea, 200
            )
            art_dock.setMaximumHeight(250)
            self.tabifyDockWidget(hud_dock, art_dock)
            self._original_hud_dock = art_dock
        except (HudContractError, OSError, ValueError, KeyError) as exc:
            self.statusBar().showMessage(
                f"Der Original-XAML-HUD-Test konnte nicht geladen werden: {exc}"
            )
        animation_dock.raise_()
        self.statusBar().showMessage("Kartenverzeichnis wird gelesen …")

        self.setStyleSheet("""
            QMainWindow, QWidget { background-color: #22272a; color: #eee8df; }
            QTreeWidget, QListWidget, QLineEdit {
              background-color: #171b1e; border: 1px solid #48504b;
              selection-background-color: #46634b; padding: 4px;
            }
            QToolBar { background-color: #303530; spacing: 5px; }
            QToolButton { padding: 7px; }
            QDockWidget::title { background-color: #343b36; padding: 5px; }
        """)
        # QAction truth follows the model and current tab. These connections
        # are installed only after all controls, canvases and menus exist.
        self.tabs.currentChanged.connect(self._update_action_context)
        self.board.scene_changed.connect(self._update_action_context)
        self.board.selected_id_changed.connect(self._update_action_context)
        self.native_canvas.modified.connect(self._update_action_context)
        self.native_canvas.object_selected.connect(self._update_action_context)
        self.native_canvas.placement_changed.connect(self._update_action_context)
        self.overlay_state_changed.connect(self._update_action_context)
        self.asset_preview.group.currentTextChanged.connect(self._update_action_context)
        self.asset_preview.frame.valueChanged.connect(self._update_action_context)
        self._update_action_context()

    def _active_view(self):
        index = self.tabs.currentIndex()
        return self.board if index == 1 else self.height_view if index == 2 else (
            self.native_canvas if index == 3 else self.viewer)

    def zoom_active(self, scale):
        current = self._active_view()
        if isinstance(current, MapView):
            current.zoom(scale)
        elif current is self.native_canvas:
            current.zoom(scale)
        else:
            value = current.transform().m11() * scale
            if 0.08 <= value <= 16:
                current.scale(scale, scale)

    def _tab_changed(self, index):
        previous = getattr(self, "_last_workspace_tab", index)
        self._last_workspace_tab = index
        if previous != index and previous == 1:
            # The isometric Testfeld is a DIFFERENT editing surface.
            # Leaving it must not preserve a hidden armed click or a timer
            # that continues changing sprite previews in the background.
            self.board.cancel_placement()
            animation = getattr(self, "animation_panel", None)
            if animation is not None:
                animation.stop()
        elif previous != index and previous == 3:
            # A native-map placement belongs to that visible viewport only.
            # Editor/Game toggles within the same tab keep it intentionally.
            self.native_canvas.cancel_placement()
        if index == 0:
            en = getattr(getattr(self,"ui_language",None),"language","de") == "en"
            if self._current is not None and self._image is not None:
                width, height = self._image.size
                detail = (
                    "read-only map preview, not gameplay" if en
                    else "nur lesende Kartenvorschau, keine spielbare Karte"
                )
                title = "Original radar" if en else "Originalradar"
                self.statusBar().showMessage(
                    f"{title}: {self._current.name} · {width}×{height} px · {detail}."
                )
            else:
                self.statusBar().showMessage(
                    ("Original radar: No map loaded. "
                     "Open an original map via File → Open."
                     if en else
                     "Originalradar: Keine Karte geladen. "
                     "Eine Originalkarte über Datei → Öffnen auswählen.")
                )
        elif index == 1:
            self.statusBar().showMessage(
                "Isometrisches Testfeld mit echten Sprite-Frames; "
                "die Bodenkacheln sind nur Editorhilfen, KEINE Originalterrain-Karte."
            )
        elif index == 3:
            self.statusBar().showMessage(
                "Echte Kachelkoordinaten aus .map mit Sprite-Texturvorschau. "
                "Overlay-Bearbeitungen ändern niemals die Originalkarte."
            )
            if self.native_canvas.has_map():
                self._native_dock.raise_()
                # Make the original-XAML graphic test visible by default.
                # The functional editor HUD remains accessible as a sibling tab.
                if self.original_hud is not None:
                    self._original_hud_dock.raise_()
                else:
                    self._hud_dock.raise_()
        elif index == 2:
            if self._height_image is None:
                self.show_height_section()
            else:
                self.statusBar().showMessage(
                    "SHCDE-Sektion 3005: 800-reihige native Diamantkacheln, "
                    "numerische Fehlfarben; Materialzuordnung noch nicht abschließend bewiesen."
                )

    def show_height_section(self):
        if self._current is None:
            return False
        if self._height_image is None:
            try:
                self._native_values = load_native_tile_values(self._current)
                self._height_image = render_native_tile_values(
                    self._native_values, false_color=True
                )
            except (MapFormatError, MapDecoderUnavailable, KeyError, OSError) as exc:
                QMessageBox.information(
                    self, "Rohdaten nicht verfügbar",
                    f"Diese .map-Variante kann noch nicht vollständig gelesen werden: {exc}"
                )
                self.tabs.setCurrentIndex(0)
                return False
            self.height_view.display(self._height_image)
        self.tabs.setCurrentIndex(2)
        self.statusBar().showMessage(
            f"{self._current.stem} · Native Kacheldaten 3005 · 800×800-Diamant · "
            "echte native Daten, Farbzuordnung vorläufig."
        )
        return True

    def _raw_pixel_picked(self, x, y):
        if self._native_values is None:
            return
        try:
            index = tile_index(x, y)
        except (IndexError, TypeError):
            return
        value = self._native_values[index]
        self.statusBar().showMessage(
            f"Kachel-Datenkanal 3005 · Raster ({x}, {y}) · Index {index} · "
            f"Originalwert {value} · Materialzuordnung noch unbestätigt."
        )

    def show_test_field(self):
        self.tabs.setCurrentIndex(1)

    def show_native_map(self):
        if self.native_canvas.has_map():
            self.tabs.setCurrentIndex(3)
            self._native_dock.raise_()
            self._native_mode_info.setText(self.native_canvas.runtime_description())
            return True
        self.statusBar().showMessage("Diese Originalkarte besitzt noch keine vollständig dekodierten Kacheldaten.")
        return False

    def _native_tile_picked(self, x, y, data):
        values = ", ".join(f"{key}={value}" for key, value in sorted(data.items()))
        self.statusBar().showMessage(f"Originalkachel ({x},{y}): {values}")

    def _map_sprite_selected(self, ident):
        if ident:
            QTimer.singleShot(0, lambda: self._sync_map_selection(ident))

    def _sync_map_selection(self, ident):
        if self.native_canvas.select_id() != ident:
            return
        obj = next((o for o in self.native_canvas.history.overlay.objects
                    if o.id == ident), None)
        if obj:
            self._palette_select(obj.group, obj.frame)

    def _update_map_asset(self, group, name):
        if not self.native_canvas.has_map():
            return
        import asset_katalog as katalog
        affected = {
            obj.frame for obj in self.native_canvas.history.overlay.objects
            if obj.group == group and katalog.native_name(group, obj.frame) == name
        }
        affected.update(
            visual.frame for visual in self.native_canvas.visual_mappings.assignments.values()
            if visual.group == group and katalog.native_name(group, visual.frame) == name
        )
        for number in sorted(affected):
            self.native_canvas.refresh_asset(group, number)
        from sandbox_native_canvas import TEXTURES
        if (group in {spec[0] for spec in TEXTURES.values()} or
                (self.native_canvas.terrain_tests is not None and any(
                    sprite.group == group
                    for sprite in self.native_canvas.terrain_tests.assignments.values()
                )) or
                (self.native_canvas.surface_tests is not None and any(
                    sprite.group == group
                    for sprite in self.native_canvas.surface_tests.assignments.values()
                ))):
            self.native_canvas.refresh_terrain_assets()

    def _surface_test_default_path(self, sha):
        return (ROOT / "sandbox" / "surface-mappings" /
                f"{self._current.stem}-{sha[:12]}.surface-3037.json")

    def _load_surface_tests_for_map(self, sha):
        target = self._surface_test_default_path(sha)
        try:
            tests = load_surface_tests(target, sha)
        except TerrainMappingError as exc:
            original = target
            stem = target.name.removesuffix(".json")
            candidate = target.with_name(stem + ".recovery.json")
            try:
                tests = load_surface_tests(candidate, sha) if candidate.is_file() else SurfaceTestMappings(sha)
            except TerrainMappingError:
                index = 1
                while candidate.exists():
                    candidate = target.with_name(f"{stem}.recovery-{index}.json")
                    index += 1
                tests = SurfaceTestMappings(sha)
            target = candidate
            QMessageBox.warning(
                self, "3037-Geländegrafiken konnten nicht geladen werden",
                f"{exc}\nOriginaldatei bleibt erhalten: {original}\n"
                f"Neue Zuordnungen: {target}",
            )
        self._surface_test_path = target
        self.native_canvas.set_surface_tests(tests)

    def assign_surface_test(self):
        code = self.native_inspector._surface_code
        if code is None or not self.native_canvas.has_map():
            self.statusBar().showMessage("Zuerst eine Kachel mit Boden-Byte 3037 anklicken.")
            return False
        import copy
        tests = copy.deepcopy(self.native_canvas.surface_tests)
        group = self.asset_preview.group.currentText().strip()
        frame = self.asset_preview.frame.value()
        try:
            tests.assign(code, group, frame)
            save_surface_tests(self._surface_test_path, tests)
            self.native_canvas.set_surface_tests(tests)
            self.native_inspector.refresh_surface_summary()
        except (TerrainMappingError, OSError) as exc:
            QMessageBox.warning(self, "Boden-Spritezuordnung fehlgeschlagen", str(exc))
            return False
        self.statusBar().showMessage(
            f"Bodenkanal 3037={code} → {group}/{frame}. Experiment, "
            "exakter Engine-Atlasframe noch nicht nachgewiesen."
        )
        return True

    def clear_surface_test(self):
        code = self.native_inspector._surface_code
        if code is None or not self.native_canvas.has_map():
            return False
        import copy
        tests = copy.deepcopy(self.native_canvas.surface_tests)
        tests.unassign(code)
        try:
            save_surface_tests(self._surface_test_path, tests)
            self.native_canvas.set_surface_tests(tests)
            self.native_inspector.refresh_surface_summary()
        except (TerrainMappingError, OSError) as exc:
            QMessageBox.warning(self, "Boden-Spritezuordnung zurücksetzen", str(exc))
            return False
        self.statusBar().showMessage(
            f"Bodenkanal 3037={code}: wieder vorläufige Materialansicht."
        )
        return True

    def _terrain_test_default_path(self, sha):
        return (ROOT / "sandbox" / "terrain-mappings" /
                f"{self._current.stem}-{sha[:12]}.terrain.json")

    def _load_terrain_tests_for_map(self, sha):
        target = self._terrain_test_default_path(sha)
        try:
            mappings = load_terrain_tests(target, sha)
        except TerrainMappingError as exc:
            original = target
            stem = target.name.removesuffix(".json")
            candidate = target.with_name(stem + ".recovery.json")
            try:
                mappings = load_terrain_tests(candidate, sha) if candidate.exists() else TerrainTestMappings(sha)
            except TerrainMappingError:
                # Never overwrite either damaged version. Choose a free file.
                count = 1
                while candidate.exists():
                    candidate = target.with_name(f"{stem}.recovery-{count}.json")
                    count += 1
                mappings = TerrainTestMappings(sha)
            target = candidate
            QMessageBox.warning(
                self, "Terrain-Testzuordnung konnte nicht geladen werden",
                f"{exc}\nDie beschädigte Originaldatei bleibt erhalten: {original}\n"
                f"Neue Testzuordnungen speichern unter: {target}"
            )
        self._terrain_test_path = target
        self.native_canvas.set_terrain_tests(mappings)

    def assign_terrain_test(self):
        if not self.native_canvas.has_map() or self.native_inspector._terrain_code is None:
            self.statusBar().showMessage("Bitte zuerst eine Geländekachel der Originalkarte anklicken.")
            return False
        code = self.native_inspector._terrain_code
        group = self.asset_preview.group.currentText().strip()
        frame = self.asset_preview.frame.value()
        import copy
        before = copy.deepcopy(self.native_canvas.terrain_tests)
        try:
            updated = copy.deepcopy(before)
            updated.assign(code, group, frame)
            save_terrain_tests(self._terrain_test_path, updated)
            self.native_canvas.set_terrain_tests(updated)
            self.native_inspector.refresh_terrain_summary()
        except (TerrainMappingError, OSError) as exc:
            QMessageBox.warning(self, "Terrain-Grafiktest konnte nicht gespeichert werden", str(exc))
            return False
        self.statusBar().showMessage(
            f"Testzuordnung für Rohwert 3005={code}: {group}/{frame}. "
            "Kein verifiziertes Engine-Materialmapping."
        )
        return True

    def clear_terrain_test(self):
        if not self.native_canvas.has_map() or self.native_inspector._terrain_code is None:
            return False
        code = self.native_inspector._terrain_code
        import copy
        updated = copy.deepcopy(self.native_canvas.terrain_tests)
        updated.unassign(code)
        try:
            save_terrain_tests(self._terrain_test_path, updated)
            self.native_canvas.set_terrain_tests(updated)
            self.native_inspector.refresh_terrain_summary()
        except (TerrainMappingError, OSError) as exc:
            QMessageBox.warning(self, "Terrain-Grafiktest konnte nicht zurückgesetzt werden", str(exc))
            return False
        self.statusBar().showMessage(
            f"Terrain-Test für Rohwert 3005={code} zurückgesetzt; heuristische Anzeige aktiv."
        )
        return True

    def _overlay_default_path(self):
        if self._current is None or self.native_canvas.history is None:
            return None
        checksum = self.native_canvas.history.overlay.source_sha256[:12]
        return ROOT / "sandbox" / "overlays" / f"{self._current.stem}-{checksum}.overlay.json"

    def _overlay_changed(self):
        if self._saved_overlay is None or not self.native_canvas.has_map():
            return
        dirty = self.native_canvas.history.overlay.serialize() != self._saved_overlay
        self.tabs.setTabText(3, ("* " if dirty else "") + "Spielkarte – Originaldaten / eigene Sprites")

    def _confirm_overlay_discard(self):
        if self._saved_overlay is None or not self.native_canvas.has_map():
            return True
        if self.native_canvas.history.overlay.serialize() == self._saved_overlay:
            return True
        choice = QMessageBox.question(
            self, "Ungespeicherte Kartenbearbeitung",
            "Die hinzugefügten Sprites auf der Originalkarte wurden verändert. Overlay speichern?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard |
            QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if choice == QMessageBox.StandardButton.Cancel:
            return False
        if choice == QMessageBox.StandardButton.Save:
            return self.save_map_overlay()
        return True

    def save_map_overlay(self, path=None):
        if not self.native_canvas.has_map():
            return False
        target = Path(path) if path else self._overlay_path or self._overlay_default_path()
        try:
            save_overlay(target, self.native_canvas.history.overlay)
        except (OSError, SceneError) as exc:
            QMessageBox.warning(self, "Kartenbearbeitung konnte nicht gespeichert werden", str(exc))
            return False
        self._overlay_path = target
        self._saved_overlay = self.native_canvas.history.overlay.serialize()
        self._overlay_changed()
        self.overlay_state_changed.emit()
        self.statusBar().showMessage(f"Karten-Overlay gespeichert: {target}")
        return True

    def open_reference_comparison(self):
        from sandbox_reference_compare import ReferenceComparisonDialog
        self._compare_dialog = ReferenceComparisonDialog(self._active_view(), self)
        self._compare_dialog.show()
        return True

    def export_viewport(self):
        view = self._active_view()
        output, _ = QFileDialog.getSaveFileName(
            self, "Ansicht als PNG speichern",
            str(ROOT / "work" / "sandbox-screenshot.png"),
            "PNG-Bild (*.png)",
        )
        if not output:
            return False
        from sandbox_png_export import atomic_export_png, ExportTargetError
        try:
            atomic_export_png(
                output, lambda target: view.grab().save(str(target), "PNG"),
                project_root=ROOT, map_root=self._root, map_file=self._current,
            )
        except (ExportTargetError, OSError, ValueError) as exc:
            QMessageBox.warning(self, "Screenshot konnte nicht gespeichert werden", str(exc))
            return False
        self.statusBar().showMessage(f"Screenshot gespeichert: {output}")
        return True

    def save_active(self):
        """Save ONLY the editable working view, never an unrelated hidden scene.

        F1 Radar and F3 raw/height diagnostics are read-only; previously
        Ctrl+S there silently saved the *separate* isometric test scene.
        """
        index = self.tabs.currentIndex()
        if index == 3:
            return self.save_map_overlay()
        if index == 1:
            return self.save_test_scene()
        self.statusBar().showMessage(
            "Radar und Kacheldiagnose sind nur lesbar. "
            "Zum Speichern zuerst Spielkarte oder Testfeld auswählen."
        )
        return False


    def _asset_from_selection(self, ident):
        if ident:
            QTimer.singleShot(0, lambda: self._show_selected_asset(ident))

    def _show_selected_asset(self, ident):
        if self.board.selected_id() != ident:
            return
        obj = next((entry for entry in self.board.history.scene.objects
                    if entry.id == ident), None)
        if obj is None:
            return
        self.asset_preview.group.blockSignals(True)
        self.asset_preview.frame.blockSignals(True)
        self.asset_preview.group.setCurrentText(obj.group)
        self.asset_preview.frame.setValue(obj.frame)
        self.asset_preview.group.blockSignals(False)
        self.asset_preview.frame.blockSignals(False)
        self._sync_hud_from_preview()
        self.asset_preview.refresh()

    def _show_engine_sprite_selection(self, hit):
        # The native engine owns the sprite identity. Make the clicked frame
        # immediately visible to the editor rather than leaving a stale
        # manually selected group, and preserve the underlying original map.
        self._native_mode_info.setText(
            f"Angeklickte Originalgrafik: {hit.ref.group}/{hit.ref.frame} · "
            f"GM {hit.source_file}, Engine-Bild {hit.source_frame} · "
            f"Kachel ({hit.x},{hit.y}) · {hit.kind}. "
            "Original nur lesbar, Grafikbearbeitung in separater Arbeitskopie."
        )
        self.asset_preview.group.blockSignals(True)
        self.asset_preview.frame.blockSignals(True)
        self.asset_preview.group.setCurrentText(hit.ref.group)
        self.asset_preview.frame.setValue(hit.ref.frame)
        self.asset_preview.group.blockSignals(False)
        self.asset_preview.frame.blockSignals(False)
        self._sync_hud_from_preview()
        self.asset_preview.refresh()
        self._native_dock.raise_()
        self._native_inspector_scroll.ensureWidgetVisible(
            self.native_inspector.engine_detail, 0, 12
        )
        self.statusBar().showMessage(
            f"Originalgrafik {hit.ref.group}/{hit.ref.frame} "
            f"(GM {hit.source_file}/{hit.source_frame}) angeklickt. "
            "Ctrl+E öffnet den Pixeleditor für genau diesen Frame."
        )

    def edit_runtime_tile(self, x, y):
        canvas = self.native_canvas
        if canvas.runtime_renderer is None:
            return False
        record = canvas.runtime_snapshot.tile(x,y)
        hit = canvas.last_engine_pick
        if hit is not None and (hit.x,hit.y)==(x,y) and canvas.engine_active():
            # The artwork actually clicked can be a tree, troop, animated
            # building or raised cliff, not just its underlying terrain.
            ref = hit.ref
        elif record is not None:
            ref = canvas.runtime_renderer._tile_reference(record)
        else:
            ref = None
        if ref is None:
            self.statusBar().showMessage("Diese Kachel besitzt keine sichtbare Engine-Grafik")
            return False
        # Ensure vanilla fallbacks are available to the established pixel
        # editor without touching the original archives or overriding work art.
        canvas.runtime_renderer._pixmap(ref)
        self.asset_preview.group.setCurrentText(ref.group)
        self.asset_preview.frame.setValue(ref.frame)
        # Select the *known runtime frame*, not a stale manually selected object.
        from sandbox_pixel_editor import SpritePixelEditor
        try:
            dialog = SpritePixelEditor(ref.group, ref.frame, self)
        except (OSError, ValueError, SystemExit) as exc:
            QMessageBox.warning(self, "Engine-Sprite konnte nicht geöffnet werden", str(exc))
            return False
        dialog.saved_frame.connect(self._pixel_changed)
        dialog.closed.connect(lambda ref=dialog: self._pixel_dialogs.remove(ref)
                              if ref in self._pixel_dialogs else None)
        self._pixel_dialogs.append(dialog)
        dialog.show()
        return True

    def open_hud_pixel_editor(self, group, number):
        """Edit the frame *shown on the HUD*, not a stale inspector selection."""
        group = group.strip()
        if not group or type(number) is not int or not 0 <= number <= 999999:
            self.statusBar().showMessage("HUD: Bitte eine gültige Sprite-Gruppe und einen Frame wählen.")
            return False
        hit = self.native_canvas.last_engine_pick
        if (self.tabs.currentIndex() == 3 and self.native_canvas.engine_active()
                and hit is not None and
                (hit.ref.group, hit.ref.frame) == (group, number)):
            return self.edit_runtime_tile(hit.x, hit.y)
        from sandbox_pixel_editor import SpritePixelEditor
        try:
            dialog = SpritePixelEditor(group, number, self)
        except (OSError, ValueError, SystemExit, FileNotFoundError) as exc:
            QMessageBox.warning(self, "HUD-Sprite nicht bearbeitbar", str(exc))
            return False
        dialog.saved_frame.connect(self._pixel_changed)
        dialog.closed.connect(lambda ref=dialog: self._pixel_dialogs.remove(ref)
                              if ref in self._pixel_dialogs else None)
        self._pixel_dialogs.append(dialog)
        dialog.show()
        self.statusBar().showMessage(f"HUD-Pixeleditor geöffnet: {group}/{number}")
        return True

    def open_pixel_editor(self):
        picked = self.native_canvas.last_engine_pick
        if (self.tabs.currentIndex() == 3 and self.native_canvas.engine_active()
                and picked is not None):
            return self.edit_runtime_tile(picked.x,picked.y)
        if self.tabs.currentIndex() == 3 and self.native_canvas.select_id():
            obj = next((o for o in self.native_canvas.history.overlay.objects
                        if o.id == self.native_canvas.select_id()), None)
            group, number = (obj.group, obj.frame) if obj else (
                self.asset_preview.group.currentText(), self.asset_preview.frame.value())
        elif self.tabs.currentIndex() == 1 and self.board.selected_id():
            obj = next((o for o in self.board.history.scene.objects
                        if o.id == self.board.selected_id()), None)
            group, number = (obj.group, obj.frame) if obj else (
                self.asset_preview.group.currentText(), self.asset_preview.frame.value())
        else:
            group, number = self.asset_preview.group.currentText(), self.asset_preview.frame.value()
        from sandbox_pixel_editor import SpritePixelEditor
        try:
            dialog = SpritePixelEditor(group, number, self)
        except (OSError, ValueError, SystemExit, FileNotFoundError) as exc:
            QMessageBox.warning(self, "Sprite nicht bearbeitbar", str(exc))
            return False
        dialog.saved_frame.connect(self._pixel_changed)
        dialog.closed.connect(lambda ref=dialog: self._pixel_dialogs.remove(ref)
                              if ref in self._pixel_dialogs else None)
        self._pixel_dialogs.append(dialog)
        dialog.show()
        self.statusBar().showMessage(f"Sprite-Pixeleditor geöffnet: {group}/{number}")
        return True

    def assign_original_visual(self):
        selected = self.native_canvas.selected_original()
        if not selected:
            self.statusBar().showMessage("Zuerst ein Originalgebäude oder Vegetationsobjekt anklicken.")
            return False
        kind, code, record = selected
        group = self.asset_preview.group.currentText().strip()
        frame_number = self.asset_preview.frame.value()
        if not group:
            QMessageBox.information(self, "Originalgrafik", "Bitte eine Spritegruppe auswählen.")
            return False
        import copy
        before = copy.deepcopy(self._native_visuals)
        try:
            self._native_visuals.assign(kind, code, group, frame_number)
            save_mappings(self._mapping_path, self._native_visuals)
        except (VisualMappingError, OSError) as exc:
            self._native_visuals = before
            QMessageBox.warning(self, "Grafik-Zuordnung fehlgeschlagen", str(exc))
            return False
        self.native_canvas.set_visual_mappings(self._native_visuals)
        self.statusBar().showMessage(
            f"Originaltyp {kind}:{code} → {group}/{frame_number}. "
            "Vom Nutzer festgelegte Grafik, noch kein nachgewiesenes Engine-Mapping."
        )
        return True

    def clear_original_visual(self):
        selected = self.native_canvas.selected_original()
        if not selected:
            self.statusBar().showMessage("Bitte ein Originalobjekt auswählen.")
            return False
        kind, code, record = selected
        import copy
        before = copy.deepcopy(self._native_visuals)
        try:
            self._native_visuals.unassign(kind, code)
            save_mappings(self._mapping_path, self._native_visuals)
        except (VisualMappingError, OSError) as exc:
            self._native_visuals = before
            QMessageBox.warning(self, "Zuordnung zurücksetzen", str(exc))
            return False
        self.native_canvas.set_visual_mappings(self._native_visuals)
        self.statusBar().showMessage(f"Originaltyp {kind}:{code}: Sprite-Zuordnung entfernt.")
        return True

    def _pixel_changed(self, group, number):
        import asset_katalog as katalog
        if self.native_canvas.engine_active() and self.native_canvas.use_original_runtime_assets:
            # Saving an edited frame intentionally returns to working-art mode,
            # otherwise a correct original-only comparison would hide the edit.
            self.native_hud.engine_mode.setCurrentIndex(0)
        self.native_canvas.refresh_asset(group, number)
        self.board.refresh_assets(group, katalog.native_name(group, number))
        self.asset_preview.group.setCurrentText(group)
        self.asset_preview.frame.setValue(number)
        self.asset_preview.refresh()
        if self.sprite_palette.group.currentText() == group:
            self.sprite_palette.reload()
        self.statusBar().showMessage(
            f"Live aktualisiert: {group}/{number} – neue Arbeitskopie aktiv."
        )

    def _hud_art_selected(self, command):
        if not command or self._hud_bindings is None:
            return
        binding = self._hud_bindings.get(command)
        if binding is None:
            self.statusBar().showMessage(
                f"XAML-Befehl {command} erkannt. Noch keine verifizierte "
                "Struktur-zu-Atlas-Zuordnung: Palette-Sprite wählen und verbinden."
            )
            return
        if not self.show_native_map():
            self.statusBar().showMessage(
                f"{command}: Testzuordnung vorhanden, aber keine dekodierte "
                "Originalkarte geladen. Bitte zuerst eine Originalkarte öffnen."
            )
            return False
        self.native_canvas.arm_placement(binding.group, binding.frame)
        self.statusBar().showMessage(
            f"{command} → {binding.group}/{binding.frame}. "
            "Benutzerdefinierte Testzuordnung, NICHT die originale Engine-Logik."
        )
        return True

    def _hud_art_bind(self, command):
        if not command or self._hud_bindings is None:
            return False
        from stronghold_europe_de.sandbox.hud_command_bindings import save_bindings
        import copy
        original = copy.deepcopy(self._hud_bindings)
        group = self.asset_preview.group.currentText().strip()
        frame = self.asset_preview.frame.value()
        try:
            self._hud_bindings.bind(command, group, frame)
            save_bindings(self._hud_bindings_path, self._hud_bindings)
        except (ValueError, OSError) as exc:
            self._hud_bindings = original
            QMessageBox.warning(self, "HUD-Verknüpfung", str(exc))
            return False
        self.statusBar().showMessage(
            f"{command} → {group}/{frame} als benutzerdefinierter Test gespeichert."
        )
        return True

    def _hud_art_clear(self, command):
        if not command or self._hud_bindings is None:
            return False
        from stronghold_europe_de.sandbox.hud_command_bindings import save_bindings
        import copy
        original = copy.deepcopy(self._hud_bindings)
        try:
            self._hud_bindings.clear(command)
            save_bindings(self._hud_bindings_path, self._hud_bindings)
        except (ValueError, OSError) as exc:
            self._hud_bindings = original
            QMessageBox.warning(self, "HUD-Verknüpfung", str(exc))
            return False
        self.statusBar().showMessage(f"Testzuordnung für {command} aufgehoben.")
        return True

    def _sync_hud_from_preview(self, *_):
        if self._syncing_asset_selection:
            return
        self._syncing_asset_selection = True
        try:
            with QSignalBlocker(self.native_hud.group), QSignalBlocker(self.native_hud.frame):
                self.native_hud.group.setCurrentText(self.asset_preview.group.currentText())
                self.native_hud.frame.setValue(self.asset_preview.frame.value())
        finally:
            self._syncing_asset_selection = False

    def _sync_preview_from_hud(self, *_):
        if self._syncing_asset_selection:
            return
        self._syncing_asset_selection = True
        try:
            group, frame = self.native_hud.group.currentText(), self.native_hud.frame.value()
            changed = (self.asset_preview.group.currentText() != group or
                       self.asset_preview.frame.value() != frame)
            if changed:
                with QSignalBlocker(self.asset_preview.group), QSignalBlocker(self.asset_preview.frame):
                    self.asset_preview.group.setCurrentText(group)
                    self.asset_preview.frame.setValue(frame)
                # No expensive archive lookup while typing into the HUD;
                # discard any preview that belongs to the previous frame.
                self.asset_preview._selection_changed()
        finally:
            self._syncing_asset_selection = False

    def _palette_select(self, group, number):
        self.asset_preview.group.setCurrentText(group)
        self.asset_preview.frame.setValue(number)
        self.asset_preview.refresh()

    def _palette_place(self, group, number):
        self._palette_select(group, number)
        if self.tabs.currentIndex() == 3 and self.native_canvas.has_map():
            self.native_canvas.arm_placement(group, number)
        else:
            self.show_test_field()
            self.board.arm_placement(group, number)

    def arm_asset_placement(self):
        group = self.asset_preview.group.currentText().strip()
        frame = self.asset_preview.frame.value()
        if self.tabs.currentIndex() == 3 and self.native_canvas.has_map():
            self.native_canvas.arm_placement(group, frame)
        else:
            self.show_test_field()
            self.board.arm_placement(group, frame)

    def delete_test_object(self):
        if self.tabs.currentIndex() == 1:
            self.board.delete_selected()
        elif self.tabs.currentIndex() == 3:
            self.native_canvas.delete_selected()

    def undo_test(self):
        if self.tabs.currentIndex() == 1:
            self.board.undo()
        elif self.tabs.currentIndex() == 3:
            self.native_canvas.undo()

    def redo_test(self):
        if self.tabs.currentIndex() == 1:
            self.board.redo()
        elif self.tabs.currentIndex() == 3:
            self.native_canvas.redo()

    def _editor_changed(self):
        if self._saved_scene is not None:
            dirty = self.board.history.scene.serialize() != self._saved_scene
            filename = self._scene_path.name if self._scene_path else "Neue Testszene"
            self.tabs.setTabText(1, ("* " if dirty else "") + f"Sprite-Testfeld: {filename}")

    def _confirm_discard(self):
        if self._saved_scene is None or self.board.history.scene.serialize() == self._saved_scene:
            return True
        response = QMessageBox.question(
            self, "Ungespeicherte Testszene",
            "Die Szene wurde verändert. Vor dem Fortfahren speichern?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard |
            QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if response == QMessageBox.StandardButton.Cancel:
            return False
        if response == QMessageBox.StandardButton.Save:
            return self.save_test_scene()
        return True

    def new_scene(self):
        if not self._confirm_discard():
            return False
        if self._legacy_dialog is not None:
            self._legacy_dialog.close()
            self._legacy_dialog = None
        self.board.replace_scene(EditableScene())
        self._legacy_original_source = None
        self._scene_path = None
        self._saved_scene = self.board.history.scene.serialize()
        self._editor_changed()
        self.show_test_field()
        return True

    def load_test_scene(self, path):
        if not self._confirm_discard():
            return False
        try:
            scene = load_scene(path)
        except (OSError, SceneError) as exc:
            QMessageBox.warning(self, "Szene kann nicht gelesen werden", str(exc))
            return False
        if self._legacy_dialog is not None:
            self._legacy_dialog.close()
            self._legacy_dialog = None
        self.board.replace_scene(scene)
        self._legacy_original_source = Path(path).resolve() if scene.is_legacy_v1 else None
        # V1 original scenes must NEVER be silently overwritten via Ctrl+S.
        # User-owned V1 copies under this project's work/ are editable again.
        within_work = Path(path).resolve().is_relative_to((ROOT / "work").resolve())
        self._scene_path = Path(path) if not scene.is_legacy_v1 or within_work else None
        self._saved_scene = scene.serialize()
        self._editor_changed()
        self.show_test_field()
        return True

    def open_test_scene(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Sprite-Testszene öffnen", str(ROOT / "sandbox"),
            "Sandbox-Szenen (*.json)"
        )
        if path:
            return self.load_test_scene(path)
        return False

    def open_legacy_scene_editor(self):
        if not self.board.history.scene.is_legacy_v1:
            self.statusBar().showMessage(
                "Zuerst eine originale Sandkasten-V1-Szene öffnen.")
            return False
        from sandbox_legacy_v1_dialog import LegacyV1SceneDialog
        if self._legacy_dialog is None or not self._legacy_dialog.isVisible():
            self._legacy_dialog = LegacyV1SceneDialog(self.board,self)
        self._legacy_dialog.show()
        self._legacy_dialog.raise_()
        return True

    def save_test_scene(self, path=None):
        if not path:
            path = self._scene_path
        if not path:
            path, _ = QFileDialog.getSaveFileName(
                self, "Sprite-Testszene speichern",
                str(ROOT / "work" / "szenen" / "historische-v1-arbeitskopie.json"
                    if self.board.history.scene.is_legacy_v1 else
                    ROOT / "sandbox" / "szenen" / "sprite-testfeld.json"),
                "Sandbox-Szenen (*.json)"
            )
        if not path:
            return False
        if (self.board.history.scene.is_legacy_v1 and
                self._legacy_original_source is not None and
                Path(path).resolve()==self._legacy_original_source):
            QMessageBox.warning(
                self, "Original-V1-Quelle geschützt",
                "Die originale historische Szene darf nicht überschrieben werden. "
                "Bitte eine eigene Arbeitskopie unter work/szenen auswählen."
            )
            return False
        if (self.board.history.scene.is_legacy_v1 and
                not Path(path).resolve().is_relative_to((ROOT / "work").resolve())):
            QMessageBox.warning(
                self, "Historisches V1-Ziel geschützt",
                "V1-Szenen dürfen nur unter dem SpriteSuite-Arbeitsordner work/ "
                "gespeichert werden. Bitte dort eine eigene Arbeitskopie wählen.")
            return False
        try:
            save_scene(path, self.board.history.scene,
                       allow_legacy_replace=self.board.history.scene.is_legacy_v1)
        except (OSError, SceneError) as exc:
            QMessageBox.warning(self, "Szene konnte nicht gespeichert werden", str(exc))
            return False
        self._scene_path = Path(path)
        self._saved_scene = self.board.history.scene.serialize()
        self._editor_changed()
        self.statusBar().showMessage(f"Testszene gespeichert: {path}")
        return True

    def showEvent(self, event):
        super().showEvent(event)
        adapter=getattr(self,"ui_language",None)
        if adapter is not None:
            adapter.attach()

    def closeEvent(self, event):
        # When this QMainWindow is an actual HWND child of the Tk Universal
        # Suite, letting Alt+F4 close only Qt leaves an empty Sandbox tab.
        # Ask the owning Suite to exit instead. The Suite will subsequently
        # call the normal close path with _embedded_allow_close=True, which
        # retains the existing unsaved-scene/overlay confirmation dialogs.
        request = getattr(self, "_embedded_close_request", None)
        if request is not None and not getattr(self, "_embedded_allow_close", False):
            event.ignore()
            request()
            return
        if self._confirm_discard() and self._confirm_overlay_discard():
            event.accept()
            adapter=getattr(self,"ui_language",None)
            if adapter is not None:
                adapter.detach()
        else:
            event.ignore()

    def _dock(self, title, widget, area, width):
        dock = QDockWidget(title, self)
        dock.setWidget(widget)
        dock.setObjectName(title)
        self.addDockWidget(area, dock)
        if area != Qt.DockWidgetArea.BottomDockWidgetArea:
            dock.setMinimumWidth(width)
        return dock

    def scan(self, root):
        self._root = Path(root)
        self._infos = find_maps(self._root)
        self._update_list()
        self.statusBar().showMessage(
            f"{len(self._infos)} gültige Originalkarten in {self._root}")
        if self._infos and self._current is None:
            preferred = next((i for i in self._infos if i.name == "Antioch"), self._infos[0])
            self.open_map(preferred.path)

    def _update_list(self):
        needle = self.filter.text().casefold().strip()
        self.maplist.clear()
        candidates = [i for i in self._infos if needle in i.name.casefold()]
        for info in candidates:
            world = f"{info.world_size}²" if info.world_size else "?"
            item = QListWidgetItem(f"{info.name}   [{world}]")
            item.setData(Qt.ItemDataRole.UserRole, str(info.path))
            self.maplist.addItem(item)
        self.mapcount.setText(f"{len(candidates)} von {len(self._infos)} Karten")

    def _open_from_list(self, item):
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            self.open_map(Path(path))

    def open_map(self, path):
        if not self._confirm_overlay_discard():
            return False
        try:
            header, pil_image = load_radar_preview(path)
        except (OSError, MapFormatError, MapDecoderUnavailable) as exc:
            QMessageBox.warning(self, "Karte kann nicht geöffnet werden", str(exc))
            return False
        self._current = header.path
        self._image = pil_image
        self._height_image = None
        self._native_values = None
        self.height_view.scene().clear()
        # Keep a currently active integrated game map active while its
        # source is replaced. An intermediate Radar tab change would now
        # (correctly) exit game mode, even when the new native map succeeds.
        workspace = getattr(self, "_compact_workspace", None)
        keep_game_view = bool(workspace and workspace.game_mode)
        if not keep_game_view:
            self.tabs.setCurrentIndex(0)
        self.viewer.display(pil_image)
        self.minimap.fitInView(self.viewer.scene().sceneRect(),
                               Qt.AspectRatioMode.KeepAspectRatio)
        self.info.clear()
        values = [
            ("Karte", header.name),
            ("Quelle", str(header.path)),
            ("Format-Header", str(header.header_id)),
            ("Kartengröße", f"{header.world_size} × {header.world_size}" if header.world_size else "unbekannt"),
            ("Max. Spieler", str(header.max_players) if header.max_players is not None else "unbekannt"),
            ("Editierbar im Spiel", "Ja" if header.editable else "Nein"),
            ("Radar-Vorschau", "200 × 200 Pixel, original"),
            ("Decoder", "PKWare DCL, MIT-Lizenz"),
            ("Bekannte Burgpositionen",
             ", ".join(f"{x},{y}" for x, y in header.keeps if x >= 0 and y >= 0) or "keine"),
        ]
        try:
            sections = discover_sections(header.path)
            values.append(("Sektionsverzeichnis", f"{len(sections.sections)} Abschnitte, verifiziert"))
            values.append(("Rohkanal 3005", "320800 native Diamantkacheln"
                           if 3005 in sections.section_ids else "fehlt"))
            from stronghold_europe_de.sandbox.start_keep_audit import audit_start_keeps
            audit=audit_start_keeps(header.path)
            state={"passend":"Passend", "warnung":"WARNUNG",
                   "kein_skirmish":"Nicht Skirmish",
                   "unverifiziert":"Unverifiziert"}[audit.state]
            values.append(("Original-Startburgen", f"{state}: {audit.message}"))
            if audit.starts:
                values.append(("Burgstarts (Eigentümer / X / Y)",
                               "; ".join(f"{owner}: {x},{y}"
                                         for owner,x,y in audit.starts)))
        except (MapFormatError, OSError):
            values.append(("Sektionsverzeichnis", "Variante noch nicht unterstützt"))
        for key, value in values:
            self.info.addTopLevelItem(QTreeWidgetItem([key, value]))
        self.info.resizeColumnToContents(0)
        self.setWindowTitle(f"Sprite Suite – Sandbox Studio – {header.name}")
        self.statusBar().showMessage(f"{header.name} · Original-Radarkarte · {header.world_size or '?'}²")
        try:
            from stronghold_europe_de.sandbox.native_overlay import new_overlay
            from stronghold_europe_de.sandbox.map_sections import load_native_tile_channels
            channels = load_native_tile_channels(header.path)
            candidate = new_overlay(header.path)
            destination = ROOT / "sandbox" / "overlays" / (
                f"{header.path.stem}-{candidate.source_sha256[:12]}.overlay.json")
            if destination.is_file():
                try:
                    candidate = load_overlay(destination, header.path)
                except (SceneError, OSError) as exc:
                    # Do not disable the real-map renderer because of a damaged
                    # user overlay. Never overwrite it on the next Ctrl+S.
                    original_overlay = destination
                    recovery = destination.with_name(
                        destination.name.removesuffix(".overlay.json")
                        + ".recovery.overlay.json"
                    )
                    if recovery.is_file():
                        try:
                            candidate = load_overlay(recovery, header.path)
                            destination = recovery
                        except (SceneError, OSError):
                            destination = recovery.with_name(
                                recovery.name.removesuffix(".overlay.json")
                                + ".new.overlay.json"
                            )
                    else:
                        destination = recovery
                    QMessageBox.warning(
                        self, "Gespeicherte Kartenbearbeitung beschädigt",
                        f"Die bestehende Overlay-Datei konnte nicht geöffnet werden: {exc}\n"
                        f"Sie bleibt unangetastet: {original_overlay}\n"
                        f"Neue Bearbeitungen verwenden: {destination}",
                    )
            self._saved_overlay = None
            self.native_canvas.open_map(header.path, channels, overlay=candidate)
            self.native_inspector.reset_terrain_pick()
            self._load_terrain_tests_for_map(candidate.source_sha256)
            self._load_surface_tests_for_map(candidate.source_sha256)
            self._overlay_path = destination
            self._saved_overlay = candidate.serialize()
            self._overlay_changed()
            self.overlay_state_changed.emit()
            self.native_minimap.use_map(pil_image, self.native_canvas.native_geometry)
            self.native_hud.display_map(header.path)
            self._native_mode_info.setText(self.native_canvas.runtime_description())
            self.show_native_map()
        except (MapFormatError, SceneError, OSError, MapDecoderUnavailable) as exc:
            # A native decode error has *only* a Radar preview. A failed map
            # is not a playable game view, so reveal the real editor Radar.
            if keep_game_view:
                self.tabs.setCurrentIndex(0)
            # Radar is still a valid read-only preview, but a previous map's
            # engine, selections, minimap and saved baseline are NOT valid
            # for this source. Never leave old game-HUD actions enabled.
            canvas = self.native_canvas
            canvas._channels = None
            canvas._base = None
            canvas._map_path = None
            canvas.original_buildings.clear()
            canvas.original_trees.clear()
            canvas.scene().clear()
            canvas.history = None
            canvas.runtime_snapshot = None
            canvas.runtime_renderer = None
            canvas.runtime_error = str(exc)
            canvas.last_engine_pick = None
            canvas._placing = None
            canvas._keyboard_tile = None
            canvas._keyboard_marker = None
            canvas.unsetCursor()
            self.native_minimap.use_map(None, None)
            self._saved_overlay = None
            self._overlay_path = None
            self._native_mode_info.setText(
                f"Originalkarten-Engine für {header.name} nicht verfügbar: {exc}"
            )
            canvas.placement_changed.emit()
            canvas.modified.emit()
            self.overlay_state_changed.emit()
            self.statusBar().showMessage(
                f"{header.name}: Radar geladen; vollständiger nativer Kartenmodus nicht verfügbar: {exc}"
            )
        return True

    def _pixel_picked(self, x, y):
        if self._image:
            self.statusBar().showMessage(
                f"Radarposition ({x}, {y}) · RGB {self._image.getpixel((x,y))} · "
                f"{self._current.name} · keine erfundenen Spielkoordinaten")

    def reload_current(self):
        """F5 does what its visible action promises for the active view.

        In the original Sandkasten, 'Neu laden' rebuilt current sprite
        pixels/BC7 output, NOT a different .map in the background.
        """
        if self.tabs.currentIndex() == 1:
            self.board.reload_source()
            self.statusBar().showMessage(
                "Sprite-Testfeld: Arbeitsgrafiken neu gelesen; "
                "Kamera, Auswahl und Undo-Verlauf erhalten."
            )
            return True
        if self._current is not None:
            return self.open_map(self._current)
        self.statusBar().showMessage(
            "Keine Originalkarte zum Neuladen vorhanden."
        )
        return False

    def choose_map(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Originalkarte öffnen", str(self._root), "Stronghold-Karten (*.map)")
        if path and self.open_map(path):
            # Reopen a deliberately selected folder on the next Suite start.
            from stronghold_europe_de.sandbox.maps_configuration import save_maps_root
            try:
                save_maps_root(ROOT, Path(path).parent)
            except (OSError, ValueError) as exc:
                self.statusBar().showMessage(
                    f"Originalkarte geöffnet, Kartenordner konnte nicht gespeichert werden: {exc}"
                )

    def _clear_open_map_views(self):
        """Drop every map-bound viewport after a successful folder change."""
        self._current = None
        self._image = None
        self._height_image = None
        self._native_values = None
        self._saved_overlay = None
        self._overlay_path = None
        self._terrain_test_path = None
        self._surface_test_path = None
        self.viewer.scene().clear()
        self.viewer.scene().setSceneRect(0, 0, 0, 0)
        self.viewer._map_pix = None
        self.viewer._marker = None
        self.height_view.scene().clear()
        self.height_view.scene().setSceneRect(0, 0, 0, 0)
        self.height_view._map_pix = None
        self.height_view._marker = None
        self.info.clear()
        self.native_canvas.clear_map()
        self.native_minimap.use_map(None, None)
        self.native_inspector.reset_terrain_pick()
        self.native_hud._select("")
        self.native_hud._modified()
        self.native_hud.map_title.setText(
            self.native_hud._ui_text("Keine Originalkarte geladen"))
        self.native_hud.values.setText(self.native_hud._ui_text("Kachelwerte: –"))
        self._native_mode_info.setText(
            "Keine Originalkarte geladen. Bitte eine Karte im neuen Ordner wählen.")
        self.tabs.setTabText(3, "Spielkarte – Originaldaten / eigene Sprites")
        self.tabs.setCurrentIndex(0)
        self.overlay_state_changed.emit()

    def choose_folder(self):
        path = QFileDialog.getExistingDirectory(
            self, "Originalkartenordner wählen", str(self._root))
        if not path:
            return
        if not self._confirm_overlay_discard():
            return
        from stronghold_europe_de.sandbox.maps_configuration import save_maps_root
        try:
            selected=save_maps_root(ROOT, path)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Kartenordner", str(exc))
            return
        self._clear_open_map_views()
        self.scan(selected)

    def save_preview(self):
        if self._image is None:
            return False
        target, _ = QFileDialog.getSaveFileName(
            self, "Original-Radarbild speichern", str(ROOT / "work" / "radar-preview.png"),
            "PNG-Bild (*.png)")
        if not target:
            return False
        from sandbox_png_export import atomic_export_png, ExportTargetError
        try:
            atomic_export_png(
                target, lambda destination: self._image.save(destination, "PNG"),
                project_root=ROOT, map_root=self._root, map_file=self._current,
            )
        except (ExportTargetError, OSError, ValueError) as exc:
            QMessageBox.warning(self, "Radarbild konnte nicht gespeichert werden", str(exc))
            return False
        self.statusBar().showMessage(f"Radarbild exportiert: {target}")
        return True


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--maps", type=Path, default=DEFAULT_GAME,
                        help="Game root or StreamingAssets/Maps directory")
    args = parser.parse_args(argv)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    window = SandboxStudio(args.maps)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

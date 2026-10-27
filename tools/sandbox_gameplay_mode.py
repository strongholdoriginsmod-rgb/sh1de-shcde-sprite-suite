"""Integrated, interactive game-view HUD for the embedded Sprite Suite.

A *partial reconstruction*, deliberately not a claim of Unity HUD parity.
This panel is attached under the SAME NativeMapCanvas used by the editor.
Original-XAML command icons are clickable, but placements require an explicit
user-authored command-to-sprite binding. No game resources are fabricated.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QSize, Signal, QPoint, QTimer, QRectF
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QFrame, QSizePolicy, QStackedWidget, QToolButton, QVBoxLayout, QWidget,
)

from sandbox_hud_original_art import GROUPS, OriginalHudArtPanel
from sandbox_gameplay_context import describe_hud_context, gameplay_action_state
from sandbox_gameplay_artwork import selection_artwork
from sandbox_native_hud_crop_provider import find_original_game_crops
from sandbox_scribe_reference import (
    find_scribe_reference, reference_key, ScribeReferenceError
)
from sandbox_hud_chrome_geometry import spine_width, hud_backplate_source_rect


class OriginalSourceCommandShelf(QWidget):
    """Interactive Qt command shelf with optional source-bound original art."""

    def __init__(self, source, parent=None):
        super().__init__(parent)
        self.original_backplate = None
        if source is not None:
            try:
                self.original_backplate = source.crop("UI-HUD 007")
            except (OSError, ValueError, KeyError):
                pass
        self.original_background_loaded = self.original_backplate is not None
        self.setToolTip(
            "Original-Crusader-HUD-Pergament: lokale SHA-geprüfte Quellpixel; "
            "Befehle/Spielzustände bleiben Qt-Testfunktionen."
            if self.original_background_loaded else
            "Abgeleitete UI-Farbe; Original-HUD-Textur nicht freigegeben."
        )

    def paintEvent(self,event):
        painter=QPainter(self)
        painter.fillRect(self.rect(),QColor("#d5bb89"))
        if self.original_backplate is not None and not self.original_backplate.isNull():
            # This is an original XAML atlas crop, not a scalable vector.
            # Stretching the entire 1752x206 parchment independently along
            # x/y distorted the source by 2x+ in the narrow Qt command shelf.
            # Fill without changing pixel aspect, cropping only the surplus
            # source region (the XAML also clips its long scroll visually).
            rect = hud_backplate_source_rect(
                (self.original_backplate.width(), self.original_backplate.height()),
                (self.width(), self.height()),
            )
            painter.drawPixmap(
                QRectF(self.rect()), self.original_backplate, QRectF(*rect)
            )
        painter.end()


class EmbeddedGameplayHUD(QWidget):
    editor_requested = Signal()

    def __init__(self, studio, parent=None):
        super().__init__(parent)
        self.studio = studio
        self._current_name = None
        self._visible_buttons = []
        self._minimap_attached = False
        self._minimap_limits = None
        self._last_tile = None
        self._map_identity = studio.native_canvas._map_path
        self._context_key = None
        self._context_override = False
        self._artwork = None
        self.native_icons = (
            find_original_game_crops(studio.original_hud.contract)
            if studio.original_hud is not None else None
        )
        self.scribe_reference = find_scribe_reference(self.native_icons)
        self._scribe_family = "B"
        self._scribe_frame = 1
        self.setObjectName("sandbox_integrated_game_hud")
        # Overlay HWND/QGraphicsView backgrounds cannot be assumed opaque.
        # The painter below must block the map inside the interactive HUD.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumHeight(116)
        self.setMaximumHeight(184)
        self.setStyleSheet("""
            QWidget#sandbox_integrated_game_hud {
                background: #292820; border-top: 2px solid #a48750;
            }
            QWidget#sandbox_integrated_game_hud QLabel { color: #f1e5c6; }
            QWidget#sandbox_integrated_game_hud QPushButton,
            QWidget#sandbox_integrated_game_hud QToolButton {
                background: #4c4532; color: #f3e6c4;
                border: 1px solid #877552; border-radius: 3px; padding: 2px;
            }
            QWidget#sandbox_integrated_game_hud QPushButton:hover,
            QWidget#sandbox_integrated_game_hud QToolButton:hover {
                background: #746241;
            }
            QWidget#sandbox_integrated_game_hud
            QToolButton#sandbox_gameplay_build_command {
                color:#322818; background:#d5bb89;
                border:1px solid #a78a56; padding:1px;
            }
            QWidget#sandbox_integrated_game_hud
            QToolButton#sandbox_gameplay_build_command:hover {
                background:#eddaa9;
            }
            QWidget#sandbox_integrated_game_hud
            QToolButton#sandbox_gameplay_build_command:checked {
                border:2px solid #557436; background:#f1deb4;
            }
            QWidget#sandbox_integrated_game_hud QComboBox {
                background: #3b382e; color: #f3e6c4; padding: 2px;
            }
            QWidget#sandbox_integrated_game_hud QScrollArea {
                border: 0; background: #292820;
            }
            QFrame#sandbox_gameplay_control_spine {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #b99753, stop:.12 #567b2c,
                    stop:.55 #244915, stop:.86 #466b26, stop:1 #9a743d);
                border-left: 2px solid #c8a662;
                border-right: 2px solid #79552b;
            }
            QToolButton#sandbox_gameplay_spine_action {
                color: #fae9ad; background: #31531e;
                border: 1px solid #c0a65a;
                padding: 0px; border-radius: 2px;
                font-weight: bold;
            }
            QToolButton#sandbox_gameplay_spine_action:hover {
                background: #557d33;
            }
            QFrame#sandbox_gameplay_radar_frame {
                background: #5b462c;
                border: 3px ridge #c5a66b;
            }
            QFrame#sandbox_gameplay_selection_frame {
                background: #292b25;
                border: 2px solid #aa8955;
            }
            QFrame#sandbox_gameplay_rendered_art_frame {
                background: #252a25;
                border: 2px solid #aa8955;
            }
            QLabel#sandbox_gameplay_art_thumbnail {
                background: #1c251e;
                border: 1px solid #625b3f;
            }
        """)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(7, 4, 7, 4)
        outer.setSpacing(8)

        left = QVBoxLayout()
        left.setSpacing(3)
        heading = QLabel("Spielmodus · HUD-Teilrekonstruktion")
        heading.setObjectName("sandbox_gameplay_heading")
        heading.setWordWrap(True)
        heading.setToolTip(
            "Noch keine pixelidentische oder simulierte Original-Spieloberfläche."
        )
        left.addWidget(heading)
        self.category = QComboBox(self)
        self.category.setObjectName("sandbox_gameplay_category")
        self.category.setAccessibleName("Original-Baugruppe auswählen")
        self.category.setToolTip(
            ("Gepinnte Original-Crusader-UI-Pixel aus lokalem Spiel, "
             "XAML-Bauseiten; keine originalen Bauzustände."
             if self.native_icons is not None else
             "Original-Iconquelle fehlt: Nur Kommandonamen im Spielmodus. "
             "Europa-Override bleibt ausschließlich im Editor.")
        )
        if studio.original_hud is not None:
            for code, title in GROUPS.items():
                self.category.addItem(f"{code} – {title}", code)
        else:
            self.category.addItem("XAML-Art nicht verfügbar", None)
        left.addWidget(self.category)
        self.map_label = QLabel("Keine Originalkarte geladen")
        self.map_label.setObjectName("sandbox_gameplay_map_state")
        self.map_label.setWordWrap(True)
        left.addWidget(self.map_label, 1)
        outer.addLayout(left, 9)

        center = QVBoxLayout()
        center.setSpacing(3)
        self.commands = QScrollArea(self)
        self.commands.setObjectName("sandbox_gameplay_command_strip")
        self.commands.setWidgetResizable(True)
        self.commands.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.commands.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.command_widget = OriginalSourceCommandShelf(self.native_icons)
        self.command_widget.setObjectName("sandbox_gameplay_command_content")
        self.command_row = QHBoxLayout(self.command_widget)
        self.command_row.setContentsMargins(2, 0, 2, 0)
        self.command_row.setSpacing(4)
        self.commands.setWidget(self.command_widget)
        # The native map now renders underneath the HUD. The parchment-like
        # command shelf must be opaque, even in a layered Qt/Win32 child.
        self.commands.viewport().setStyleSheet("background:#d5bb89;")
        # OriginalSourceCommandShelf paints a verified original backplate.
        # Never override that painter with an opaque QWidget stylesheet.
        center.addWidget(self.commands, 1)

        action_row = QHBoxLayout()
        action_row.setSpacing(3)
        action_buttons = QHBoxLayout()
        action_buttons.setSpacing(3)
        self.command_choice = QComboBox(self)
        self.command_choice.setObjectName("sandbox_gameplay_command_choice")
        self.command_choice.setMinimumWidth(90)
        self.command_choice.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.command_choice.setMinimumContentsLength(10)
        self.command_choice.setToolTip(
            "Auch bedingt sichtbare XAML-Alternativen; ohne "
            "Sprite-Testbindung wird nichts auf der Karte platziert."
        )
        action_row.addWidget(self.command_choice, 2)
        self.team_choice = QComboBox(self)
        self.team_choice.setObjectName("sandbox_gameplay_team_choice")
        self.team_choice.setFixedWidth(69)
        for i in range(studio.native_hud.team.count()):
            code = studio.native_hud.team.itemData(i)
            self.team_choice.addItem(code, code)
        self.team_choice.setCurrentIndex(studio.native_hud.team.currentIndex())
        self.team_choice.setAccessibleName("Historische Teamfarbe auswählen")
        self.team_choice.setToolTip(
            "Original-Sandkasten-Teamfarben; nur markierte Figuren/Flaggen "
            "werden eingefärbt, keine Originalspielsimulation."
        )
        self.team_choice.currentIndexChanged.connect(
            studio.native_hud.team.setCurrentIndex
        )
        studio.native_hud.team.currentIndexChanged.connect(
            self.team_choice.setCurrentIndex
        )
        action_row.addWidget(self.team_choice)
        self.place = QPushButton("Platzieren")
        self.place.setToolTip(
            "Aktuellen Sprite-Frame des funktionalen HUD als sichere "
            "Overlay-Platzierung vormerken, dann auf die Karte klicken."
        )
        self.place.clicked.connect(self._toggle_placement)
        action_row.addWidget(self.place)
        self.undo = QPushButton("↶")
        self.undo.setObjectName("sandbox_gameplay_undo")
        self.undo.setToolTip("Overlay rückgängig")
        self.undo.clicked.connect(studio.native_canvas.undo)
        action_buttons.addWidget(self.undo)
        self.redo = QPushButton("↷")
        self.redo.setObjectName("sandbox_gameplay_redo")
        self.redo.setToolTip("Overlay wiederholen")
        self.redo.clicked.connect(studio.native_canvas.redo)
        action_buttons.addWidget(self.redo)
        self.save = QPushButton("Sichern")
        self.save.setObjectName("sandbox_gameplay_save")
        self.save.setToolTip("Nur das eigene Overlay sichern, niemals die originale .map.")
        self.save.clicked.connect(studio.save_map_overlay)
        action_buttons.addWidget(self.save)
        self.edit = QPushButton("Editor")
        self.edit.setObjectName("sandbox_gameplay_open_editor")
        self.edit.clicked.connect(self.editor_requested.emit)
        action_buttons.addWidget(self.edit)
        center.addLayout(action_row)
        # The selector, team, placement and all four actions in one row
        # forced a >450px minimum and displaced the measured right-hand
        # control spine. Two narrow, fully functional rows leave room for
        # the interactive minimap and selection inspector at 1168px.
        center.addLayout(action_buttons)
        outer.addLayout(center, 22)

        # Measured original screen zone: a narrow green spine separates
        # parchment build controls from the radar/advisor side of the HUD.
        # The *actions* below are Sprite Suite functions, not asserted
        # original game commands.
        self.spine = QFrame(self)
        self.spine.setObjectName("sandbox_gameplay_control_spine")
        self.spine.setFixedWidth(spine_width(684))
        self.spine.setToolTip(
            "An den vier Spielbildern angenäherte Leistenform; "
            "nur Sprite-Suite-Bedienbefehle."
        )
        spine_layout = QVBoxLayout(self.spine)
        spine_layout.setContentsMargins(3, 4, 3, 4)
        spine_layout.setSpacing(2)
        self.spine_radar = QToolButton(self.spine)
        self.spine_radar.setObjectName("sandbox_gameplay_spine_action")
        self.spine_radar.setText("M")
        self.spine_radar.setAccessibleName("Originalradar anzeigen")
        self.spine_radar.setToolTip("Die echte Karten-Minimap anzeigen")
        self.spine_radar.clicked.connect(
            lambda: self._manual_context_page(0)
        )
        spine_layout.addWidget(self.spine_radar)
        self.context_toggle = QToolButton(self.spine)
        self.context_toggle.setObjectName("sandbox_gameplay_spine_action")
        self.context_toggle.setText("i")
        self.context_toggle.setAccessibleName("Auswahl oder Minikarte anzeigen")
        self.context_toggle.setToolTip("Auswahl anzeigen")
        self.context_toggle.clicked.connect(self.toggle_context)
        spine_layout.addWidget(self.context_toggle)
        self.spine_art = QToolButton(self.spine)
        self.spine_art.setObjectName("sandbox_gameplay_spine_action")
        self.spine_art.setText("G")
        self.spine_art.setAccessibleName("Angezeigte Spritegrafik prüfen")
        self.spine_art.setToolTip(
            "Nur tatsächlich gerenderte und ausgewählte Grafik anzeigen"
        )
        self.spine_art.setEnabled(False)
        self.spine_art.clicked.connect(lambda: self._manual_context_page(2))
        spine_layout.addWidget(self.spine_art)
        self.spine_inspect = QToolButton(self.spine)
        self.spine_inspect.setObjectName("sandbox_gameplay_spine_action")
        self.spine_inspect.setText("›")
        self.spine_inspect.setAccessibleName("Originalkarten-Inspector öffnen")
        self.spine_inspect.setToolTip(
            "Auswahl im bestehenden Originalkarten-Inspector prüfen"
        )
        spine_layout.addWidget(self.spine_inspect)
        for control in (self.spine_radar, self.context_toggle,
                        self.spine_art, self.spine_inspect):
            control.setFixedHeight(21)
        spine_layout.addStretch(1)
        outer.addWidget(self.spine, 0)

        right = QVBoxLayout()
        right.setSpacing(1)
        header = QHBoxLayout()
        header.setSpacing(2)
        self.radar_title = QLabel("Originalradar · Kamera")
        self.radar_title.setMinimumWidth(0)
        header.addWidget(self.radar_title, 1)
        self.scribe_button = QToolButton(self)
        self.scribe_button.setObjectName("sandbox_scribe_manual_button")
        self.scribe_button.setText("S")
        self.scribe_button.setFixedWidth(21)
        self.scribe_button.setAccessibleName(
            "Original-Schreiberframes als manuelle Referenz prüfen"
        )
        self.scribe_button.setToolTip(
            "89 originale Bildausschnitte, KEINE automatische Spielanimation"
        )
        self.scribe_button.setEnabled(self.scribe_reference is not None)
        self.scribe_button.clicked.connect(lambda: self._manual_context_page(3))
        header.addWidget(self.scribe_button)
        right.addLayout(header)

        self.context_stack = QStackedWidget(self)
        self.context_stack.setObjectName("sandbox_gameplay_context_stack")
        self.context_stack.setMinimumSize(0, 0)
        radar_page = QFrame(self.context_stack)
        radar_page.setObjectName("sandbox_gameplay_radar_frame")
        radar_layout = QVBoxLayout(radar_page)
        radar_layout.setContentsMargins(3, 3, 3, 3)
        radar_layout.setSpacing(1)
        self.radar_slot = QVBoxLayout()
        self.radar_slot.setContentsMargins(0, 0, 0, 0)
        self.radar_fallback = QLabel("Karte laden für Minikarte")
        self.radar_fallback.setWordWrap(True)
        self.radar_slot.addWidget(self.radar_fallback)
        radar_layout.addLayout(self.radar_slot, 1)
        self.provenance = QLabel("Ressourcen: nicht verfügbar")
        self.provenance.setWordWrap(True)
        self.provenance.setToolTip(
            "Weder Wirtschaftssimulation noch vollständige Shader-/"
            "Animationsparität nachgewiesen."
        )
        radar_layout.addWidget(self.provenance)
        self.context_stack.addWidget(radar_page)
        self.radar_page = radar_page

        detail_page = QFrame(self.context_stack)
        detail_page.setObjectName("sandbox_gameplay_selection_frame")
        detail_layout = QVBoxLayout(detail_page)
        detail_layout.setContentsMargins(1, 0, 1, 0)
        detail_layout.setSpacing(1)
        self.context_title = QLabel("Auswahl: keine")
        self.context_title.setObjectName("sandbox_gameplay_context_title")
        # In compact gameplay the header itself presents this title. Keep
        # the full model label for accessible text and provenance tooltips.
        # A duplicate second heading stole the space needed for raw IDs.
        detail_layout.addWidget(self.context_title)
        self.context_title.hide()
        self.context_brief = QLabel("Kachel oder Sprite auswählen")
        self.context_brief.setObjectName("sandbox_gameplay_context_brief")
        self.context_brief.setWordWrap(True)
        detail_layout.addWidget(self.context_brief, 1)
        self.context_detail = QLabel("")
        self.context_detail.setObjectName("sandbox_gameplay_context_detail")
        self.context_detail.setWordWrap(True)
        detail_layout.addWidget(self.context_detail, 1)
        self.inspect = QPushButton("Prüfen")
        self.inspect.setObjectName("sandbox_gameplay_inspect")
        self.inspect.setToolTip("Auswahl im vorhandenen Karten-Inspector prüfen")
        self.inspect.setFixedHeight(23)
        detail_layout.addWidget(self.inspect)
        self.context_stack.addWidget(detail_page)

        # Third page: an actually-rendered sprite thumbnail, never an
        # advisor portrait cropped from a frozen gameplay screenshot.
        self.art_page = QFrame(self.context_stack)
        self.art_page.setObjectName("sandbox_gameplay_rendered_art_frame")
        art_layout = QVBoxLayout(self.art_page)
        art_layout.setContentsMargins(3, 2, 3, 2)
        art_layout.setSpacing(1)
        self.art_thumbnail = QLabel(self.art_page)
        self.art_thumbnail.setObjectName("sandbox_gameplay_art_thumbnail")
        self.art_thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.art_thumbnail.setFixedHeight(52)
        self.art_thumbnail.setMinimumWidth(30)
        self.art_thumbnail.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        art_layout.addWidget(self.art_thumbnail, 1)
        self.art_source = QLabel(self.art_page)
        self.art_source.setObjectName("sandbox_gameplay_art_source")
        self.art_source.setWordWrap(True)
        art_layout.addWidget(self.art_source)
        self.context_stack.addWidget(self.art_page)

        # Fourth page: strictly user-stepped ORIGINAL Scribe reference art.
        # XAML frame numbering is NOT an engine event, animation, or adviser.
        self.scribe_page = QFrame(self.context_stack)
        self.scribe_page.setObjectName("sandbox_scribe_reference_page")
        scribe_layout = QVBoxLayout(self.scribe_page)
        scribe_layout.setContentsMargins(2, 1, 2, 1)
        scribe_layout.setSpacing(1)
        self.scribe_picture = QLabel(self.scribe_page)
        self.scribe_picture.setObjectName("sandbox_scribe_reference_picture")
        self.scribe_picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scribe_picture.setFixedHeight(57)
        scribe_layout.addWidget(self.scribe_picture)
        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(2)
        self.scribe_previous = QToolButton(self.scribe_page)
        self.scribe_previous.setObjectName("sandbox_scribe_previous")
        self.scribe_previous.setText("‹")
        self.scribe_previous.setFixedSize(19, 20)
        self.scribe_previous.clicked.connect(lambda: self.step_scribe(-1))
        controls.addWidget(self.scribe_previous)
        self.scribe_family = QComboBox(self.scribe_page)
        self.scribe_family.setObjectName("sandbox_scribe_family")
        self.scribe_family.addItem("B", "B")
        self.scribe_family.addItem("C", "C")
        self.scribe_family.setFixedWidth(41)
        self.scribe_family.setFixedHeight(20)
        self.scribe_family.currentIndexChanged.connect(self._set_scribe_family)
        controls.addWidget(self.scribe_family)
        self.scribe_source = QLabel(self.scribe_page)
        self.scribe_source.setObjectName("sandbox_scribe_frame_name")
        self.scribe_source.setAlignment(Qt.AlignmentFlag.AlignCenter)
        controls.addWidget(self.scribe_source, 1)
        self.scribe_next = QToolButton(self.scribe_page)
        self.scribe_next.setObjectName("sandbox_scribe_next")
        self.scribe_next.setText("›")
        self.scribe_next.setFixedSize(19, 20)
        self.scribe_next.clicked.connect(lambda: self.step_scribe(1))
        controls.addWidget(self.scribe_next)
        scribe_layout.addLayout(controls)
        self.context_stack.addWidget(self.scribe_page)
        self.refresh_scribe()

        right.addWidget(self.context_stack, 1)
        outer.addLayout(right, 15)
        self.spine_inspect.clicked.connect(self.inspect.click)

        self.category.currentIndexChanged.connect(self.refresh_commands)
        self.command_choice.currentIndexChanged.connect(self._choice_changed)
        studio.native_canvas.modified.connect(self.refresh_map_state)
        studio.native_canvas.modified.connect(self.refresh_actions)
        studio.native_canvas.placement_changed.connect(self.refresh_actions)
        studio.native_hud.group.currentTextChanged.connect(self.refresh_actions)
        studio.native_hud.frame.valueChanged.connect(self.refresh_actions)
        studio.overlay_state_changed.connect(self.refresh_actions)
        studio.ui_language.language_changed.connect(self.refresh_map_state)
        studio.ui_language.language_changed.connect(self._language_changed)
        studio.native_canvas.picked.connect(self._tile_picked)
        studio.native_canvas.object_selected.connect(self._queue_context)
        studio.native_canvas.original_building_selected.connect(self._queue_context)
        studio.native_canvas.original_tree_selected.connect(self._queue_context)
        studio.native_canvas.engine_sprite_picked.connect(self._queue_context)
        studio.native_canvas.engine_mode_changed.connect(self._queue_context)
        studio.native_canvas.modified.connect(self._queue_context)
        self._context_pending = False
        self.refresh_commands()
        self.refresh_map_state()
        self.refresh_context()
        self.refresh_actions()

    def _toggle_placement(self):
        """One visible button arms/cancels placement; no overlay is discarded."""
        canvas = self.studio.native_canvas
        if canvas._placing is not None:
            canvas.cancel_placement()
            return
        state = gameplay_action_state(self.studio)
        if state.can_place:
            self.studio.native_hud._place()

    def refresh_actions(self, *_):
        """Mirror actual Undo/Redo/save history; never claim a save was made."""
        state = gameplay_action_state(self.studio)
        canvas = self.studio.native_canvas
        # Commands arrive from BOTH the game HUD and the Suite catalogue.
        # Always mirror the exact armed group/frame into the functional HUD;
        # otherwise clicking "Place" after Esc could arm a different sprite.
        if state.placing:
            group, frame = canvas._placing
            selector = self.studio.native_hud.group
            number = self.studio.native_hud.frame
            previous = selector.blockSignals(True)
            try:
                selector.setCurrentText(group)
            finally:
                selector.blockSignals(previous)
            previous = number.blockSignals(True)
            try:
                number.setValue(frame)
            finally:
                number.blockSignals(previous)
            state = gameplay_action_state(self.studio)
        en = self.studio.ui_language.language == "en"
        placing = state.placing
        self.place.setEnabled(placing or state.can_place)
        self.place.setText(
            ("Cancel" if en else "Abbrechen") if placing
            else ("Place" if en else "Platzieren")
        )
        selected_sprite = (
            canvas._placing if placing else
            (self.studio.native_hud.group.currentText().strip(),
             self.studio.native_hud.frame.value())
        )
        self.place.setToolTip(
            f"{selected_sprite[0]}/{selected_sprite[1]} · " + (
                ("Stop placing; keep existing working objects (Esc)"
                 if en else "Platzierung beenden, Overlay-Objekte erhalten (Esc)")
                if placing else
                ("Arm this working sprite for a map click"
                 if en else "Diese Arbeitsgrafik für Kartenklick vormerken")
            )
        )
        self.place.setAccessibleName(self.place.text())
        self.undo.setEnabled(state.can_undo)
        self.redo.setEnabled(state.can_redo)
        self.save.setEnabled(state.can_save)
        self.undo.setToolTip(
            ("Undo working-overlay change" if en else "Overlay-Änderung rückgängig")
            if state.can_undo else
            ("Nothing to undo" if en else "Nichts rückgängig zu machen")
        )
        self.redo.setToolTip(
            ("Redo working-overlay change" if en else "Overlay-Änderung wiederholen")
            if state.can_redo else
            ("Nothing to redo" if en else "Nichts zu wiederholen")
        )
        self.save.setToolTip(
            ("Save only changed working overlay; original .map is read-only"
             if en else "Nur geändertes Arbeits-Overlay sichern; Original-.map bleibt geschützt")
            if state.can_save else
            ("No unsaved working-overlay changes"
             if en else "Keine ungespeicherten Overlay-Änderungen")
        )

    def _tile_picked(self, x, y, values):
        self._last_tile = (x, y, dict(values))
        self._queue_context()

    def _queue_context(self, *_):
        """Selection is finalized AFTER scene/item signals and Qt redraws."""
        # A genuinely new selection can reveal its details. A later manual
        # radar/art click takes priority over this already-queued event.
        self._context_override = False
        if not self._context_pending:
            self._context_pending = True
            QTimer.singleShot(0, self.refresh_context)

    def _language_changed(self, *_):
        # Neither language switch nor manual frame examination may arm
        # a gameplay sequence or change the selected map.
        self.refresh_actions()
        self.refresh_scribe()
        self.refresh_context(locale_only=True)
        self._set_context_page(self.context_stack.currentIndex())

    def _set_scribe_family(self, *_):
        if self.scribe_reference is None:
            return
        family = self.scribe_family.currentData()
        if family not in ("B", "C"):
            return
        self._scribe_family = family
        self._scribe_frame = 1
        self.refresh_scribe()

    def step_scribe(self, delta: int):
        """One explicit manual reference step; no auto-loop or game changes."""
        if self.scribe_reference is None or delta not in (-1, 1):
            return
        from sandbox_scribe_reference import FAMILIES
        self._scribe_frame = max(1, min(
            FAMILIES[self._scribe_family], self._scribe_frame + delta
        ))
        self.refresh_scribe()

    def refresh_scribe(self):
        en = self.studio.ui_language.language == "en"
        source = self.scribe_reference
        if source is None:
            self.scribe_picture.clear()
            self.scribe_source.setText(
                "No verified original" if en else "Keine Originalquelle"
            )
            self.scribe_source.setToolTip(self.scribe_source.text())
            self.scribe_picture.setAccessibleName(self.scribe_source.text())
            for button in (self.scribe_previous, self.scribe_next):
                button.setEnabled(False)
            self.scribe_family.setEnabled(False)
            self.scribe_button.setEnabled(False)
            return

        from sandbox_scribe_reference import FAMILIES
        total = FAMILIES[self._scribe_family]
        frame = self._scribe_frame
        description = source.description(
            self._scribe_family, frame,
            language=self.studio.ui_language.language
        )
        try:
            pixmap = source.pixmap(self._scribe_family, frame)
        except ScribeReferenceError:
            # A damaged private crop cannot be replaced with the European
            # override or any invented/cached prior frame.
            self.scribe_picture.clear()
            self.scribe_picture.setAccessibleName(
                "Source invalid" if en else "Originalquelle ungültig"
            )
            self.scribe_source.setText(
                "Source invalid" if en else "Quelle ungültig"
            )
            self.scribe_source.setToolTip(description)
            self.scribe_button.setEnabled(False)
            self.scribe_previous.setEnabled(False)
            self.scribe_next.setEnabled(False)
            return

        scaled = pixmap.scaled(
            88, 55, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        self.scribe_picture.setPixmap(scaled)
        self.scribe_picture.setToolTip(description)
        self.scribe_picture.setAccessibleName(description)
        self.scribe_source.setText(f"{self._scribe_family}{frame:03d}/{total:02d}")
        self.scribe_source.setToolTip(description)
        self.scribe_family.setToolTip(
            "Manual B/C original-image groups; NOT a game skin switch"
            if en else
            "Original-B/C-Bildreihen manuell prüfen; KEIN Skinwechsel im Spiel"
        )
        self.scribe_family.setAccessibleName(self.scribe_family.toolTip())
        self.scribe_button.setToolTip(
            "Manual original pixels; no automatic playback or adviser event"
            if en else
            "Originalpixel manuell prüfen; keine automatische Animation/Spielberatung"
        )
        self.scribe_button.setAccessibleName(self.scribe_button.toolTip())
        self.scribe_previous.setToolTip(
            "Previous reference frame" if en else "Vorheriges Referenzbild"
        )
        self.scribe_previous.setAccessibleName(self.scribe_previous.toolTip())
        self.scribe_next.setToolTip(
            "Next reference frame" if en else "Nächstes Referenzbild"
        )
        self.scribe_next.setAccessibleName(self.scribe_next.toolTip())
        self.scribe_button.setEnabled(True)
        self.scribe_family.setEnabled(True)
        self.scribe_previous.setEnabled(frame > 1)
        self.scribe_next.setEnabled(frame < total)

    def _set_context_page(self, details: bool | int):
        page = (details if type(details) is int and 0 <= details <= 3
                else 1 if details else 0)
        if page == 2 and self._artwork is None:
            page = 1 if self.studio.native_canvas.has_map() else 0
        if page == 3 and self.scribe_reference is None:
            page = 0
        self.context_stack.setCurrentIndex(page)
        en = self.studio.ui_language.language == "en"
        radar_name = "Show live minimap" if en else "Echte Minikarte anzeigen"
        inspector_name = ("Open original map inspector" if en
                          else "Originalkarten-Inspector öffnen")
        self.spine_radar.setToolTip(radar_name)
        self.spine_radar.setAccessibleName(radar_name)
        self.spine_inspect.setToolTip(inspector_name)
        self.spine_inspect.setAccessibleName(inspector_name)
        if page == 3:
            self.radar_title.setText(
                "Scribe reference" if en else "Schreiber-Referenz"
            )
            self.radar_title.setToolTip(self.scribe_source.toolTip())
            self.context_toggle.setText("↩")
            self.context_toggle.setToolTip(radar_name)
        elif page == 2:
            artwork = self._artwork
            self.radar_title.setText(
                "Rendered graphic" if en else "Gerenderte Grafik"
            )
            self.radar_title.setToolTip(
                f"{artwork.identity} · {artwork.source}"
            )
            self.context_toggle.setText("↩")
            self.context_toggle.setToolTip(radar_name)
        elif page == 1:
            self.radar_title.setText(self.context_title.text())
            self.radar_title.setToolTip(self.context_title.toolTip())
            self.context_toggle.setText("↩")
            self.context_toggle.setToolTip(radar_name)
        else:
            self.radar_title.setText(
                "Original radar · camera" if en else "Originalradar · Kamera"
            )
            self.radar_title.setToolTip(
                "Live original map radar; no economy simulation" if en
                else "Echtes Kartenradar; keine Wirtschaftssimulation"
            )
            self.context_toggle.setText("i")
            self.context_toggle.setToolTip(
                "Show selection" if en else "Auswahl anzeigen"
            )
        self.context_toggle.setAccessibleName(self.context_toggle.toolTip())

    def _manual_context_page(self, page):
        self._context_override = True
        self._set_context_page(page)

    def toggle_context(self, *_):
        """Allow reopening the real minimap without discarding selection."""
        self._manual_context_page(1 if self.context_stack.currentIndex() == 0 else 0)

    def _refresh_artwork(self, kind):
        """Reuse *displayed* sprite pixels; never perform disk/Unity export."""
        en = self.studio.ui_language.language == "en"
        artwork = selection_artwork(
            self.studio.native_canvas, kind, language=self.studio.ui_language.language
        )
        self._artwork = artwork
        self.spine_art.setEnabled(artwork is not None)
        if artwork is None:
            self.art_thumbnail.clear()
            self.art_thumbnail.setAccessibleName(
                "No verified rendered sprite" if en
                else "Keine belegte gerenderte Spritegrafik"
            )
            self.art_thumbnail.setToolTip(self.art_thumbnail.accessibleName())
            self.art_source.setText(
                "No source-bound image" if en
                else "Kein zugeordnetes Bild"
            )
            self.art_source.setToolTip(
                "Raw original building/vegetation IDs do not prove a sprite mapping"
                if en else "Rohe Original-Typ-IDs belegen keine Spritezuordnung"
            )
            self.spine_art.setToolTip(self.art_source.toolTip())
            self.spine_art.setAccessibleName(
                "No rendered graphic available" if en
                else "Keine gerenderte Grafik verfügbar"
            )
            return
        # The source QPixmap is already in the active renderer. Scaling only
        # produces a tiny UI thumbnail; it does not mutate/export its pixels.
        pixmap = artwork.pixmap.scaled(
            140, 50, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        self.art_thumbnail.setPixmap(pixmap)
        label = f"{artwork.identity} · {artwork.source}"
        self.art_thumbnail.setAccessibleName(label)
        self.art_thumbnail.setToolTip(label)
        self.art_source.setText(artwork.identity)
        self.art_source.setToolTip(artwork.source)
        self.spine_art.setToolTip(label)
        self.spine_art.setAccessibleName(
            ("Show displayed graphic " if en else "Angezeigte Grafik prüfen ")
            + artwork.identity
        )

    def _refresh_engine_artwork_after_paint(self):
        """One late cache check after the async Qt/engine viewport repaint."""
        canvas = self.studio.native_canvas
        if not canvas.has_map() or canvas._map_path != self._map_identity:
            return
        facts = describe_hud_context(canvas, tile=self._last_tile,
                                     language=self.studio.ui_language.language)
        if facts.kind == "engine":
            self._refresh_artwork("engine")

    def refresh_context(self, *, locale_only=False):
        self._context_pending = False
        canvas = self.studio.native_canvas
        if self._map_identity != canvas._map_path:
            # Never display raw tile coordinates from the previous .map.
            self._map_identity = canvas._map_path
            self._last_tile = None
            self._context_key = None
        facts = describe_hud_context(
            canvas, tile=self._last_tile,
            language=self.studio.ui_language.language
        )
        key = (facts.kind, facts.brief, facts.detail)
        changed = key != self._context_key
        self._context_key = key
        read_only = not facts.editable_overlay
        self.context_title.setText(facts.title)
        self.context_brief.setText(facts.brief)
        self.context_detail.setText(facts.detail)
        for label in (self.context_title,self.context_brief,self.context_detail):
            label.setToolTip(facts.tooltip)
        self.inspect.setEnabled(canvas.has_map())
        self.spine_inspect.setEnabled(canvas.has_map())
        self.inspect.setToolTip(facts.tooltip)
        self.context_title.setAccessibleName(
            facts.title + (" (read-only)" if read_only else " (working overlay)")
        )
        self._refresh_artwork(facts.kind)
        # The studio's asset preview may invalidate the map renderer just
        # after its engine-pick signal. Recheck the cache ONCE after repaint;
        # never decode an asset or poll repeatedly for a missing frame.
        if facts.kind == "engine" and self._artwork is None and not locale_only:
            QTimer.singleShot(75, self._refresh_engine_artwork_after_paint)
        # A restored/cleared map or invalidated engine cache must not keep
        # an old thumbnail page open with an unrelated/empty image.
        if self.context_stack.currentIndex() == 2 and self._artwork is None:
            self._set_context_page(facts.kind not in ("idle", "none"))
        if changed and not locale_only and not self._context_override:
            # A selected real record is worth surfacing immediately.
            # Never force the details panel on an untouched map.
            self._set_context_page(facts.kind not in ("idle", "none"))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Keep the decorative green band close to its measured fraction while
        # retaining a practical minimum touch width in a 784px Qt notebook.
        target = spine_width(self.width())
        if self.spine.width() != target:
            self.spine.setFixedWidth(target)

    def paintEvent(self, event):
        """Opaque HUD panel with a parchment command band.

        This is explicitly a neutral *derived* UI material, not a screenshot
        of a running game or an assertion of original atlas authenticity.
        """
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#29261e"))
        if self.commands.width() > 5 and self.radar_title.width() > 5:
            left = self.commands.mapTo(self,QPoint(0,0)).x()-5
            right = self.radar_title.mapTo(self,QPoint(0,0)).x()-5
            if right > left:
                grad = QLinearGradient(left,0,right,self.height())
                grad.setColorAt(0,QColor("#ddc497"))
                grad.setColorAt(.5,QColor("#cbb181"))
                grad.setColorAt(1,QColor("#b89a64"))
                painter.fillRect(left,0,right-left,self.height(),grad)
        painter.fillRect(0,0,self.width(),2,QColor("#9b7640"))
        painter.end()

    def attach_minimap(self):
        """Move the existing live radar; never clone/fake its camera state."""
        if self._minimap_attached:
            return
        minimap = self.studio.native_minimap
        self._minimap_limits = (
            minimap.minimumHeight(), minimap.maximumHeight(),
            minimap.minimumWidth(), minimap.maximumWidth(),
        )
        minimap.setParent(self)
        minimap.setMinimumHeight(50)
        minimap.setMaximumHeight(160)
        minimap.setMinimumWidth(95)
        minimap.setMaximumWidth(240)
        self.radar_slot.addWidget(minimap)
        self.radar_fallback.hide()
        self._minimap_attached = True
        minimap.refresh_camera_outline()

    def detach_minimap(self):
        """Restore the very same radar to its editor dock and original layout."""
        if not self._minimap_attached:
            return
        minimap = self.studio.native_minimap
        self.radar_slot.removeWidget(minimap)
        native_tools = self.studio._native_dock.widget()
        minimap.setParent(native_tools)
        native_tools.layout().insertWidget(1, minimap)
        minimum, maximum, min_width, max_width = self._minimap_limits
        minimap.setMinimumHeight(minimum)
        minimap.setMaximumHeight(maximum)
        minimap.setMinimumWidth(min_width)
        minimap.setMaximumWidth(max_width)
        minimap.show()
        self.radar_fallback.show()
        self._minimap_attached = False

    def refresh_map_state(self, *_):
        canvas = self.studio.native_canvas
        if canvas.has_map():
            title = self.studio.native_hud.map_title.text()
            count = len(canvas.history.overlay.objects) if canvas.history else 0
            name = self.studio._current.stem if self.studio._current else "Originalkarte"
            noun = ("custom overlay objects"
                    if self.studio.ui_language.language == "en"
                    else "eigene Overlay-Objekte")
            self.map_label.setText(f"{name} · {count} {noun}")
            self.map_label.setToolTip(title)
        else:
            message = ("Load an original map via File → Open"
                       if self.studio.ui_language.language == "en"
                       else "Originalkarte über Datei → Öffnen laden")
            self.map_label.setText(message)

    def refresh_commands(self, *_):
        while self.command_row.count():
            item = self.command_row.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self._visible_buttons.clear()
        self._spec_for_slot = {}
        self.command_choice.blockSignals(True)
        self.command_choice.clear()
        self.command_choice.addItem("Befehl auswählen …", None)
        art_panel = self.studio.original_hud
        page = self.category.currentData()
        if art_panel is None or page is None:
            label = QLabel("Original-XAML-Kunst nicht verfügbar; Palette bleibt im Editor.")
            self.command_row.addWidget(label)
        else:
            page_specs = [
                item for item in art_panel.contract["commands"]
                if item["page"] == page
            ]
            unique = {}
            for spec in page_specs:
                self.command_choice.addItem(spec["name"], spec["name"])
                # Same XAML pixel = conditional variants, not 21 icons
                # painted on top of each other.
                unique.setdefault(OriginalHudArtPanel.slot(spec), spec)
            self._spec_for_slot = dict(unique)
            for slot, spec in unique.items():
                button = QToolButton(self.command_widget)
                button.setObjectName("sandbox_gameplay_build_command")
                button.setFixedWidth(82)
                button.setCheckable(True)
                self._set_button_spec(button, spec)
                # Bind the *slot*, not the initial command: selecting a
                # conditional variant must change the next real click too.
                button.clicked.connect(
                    lambda _checked=False, key=slot, category=page:
                        self._choose_slot(category,key)
                )
                self.command_row.addWidget(button)
                self._visible_buttons.append((button, spec))
            self.command_row.addStretch(1)
        self.command_choice.blockSignals(False)
        self._current_name = None

    def _set_button_spec(self, button, spec):
        """Display the selected conditional art, not the slot's first variant."""
        art_panel = self.studio.original_hud
        name = spec["name"].removeprefix("ButtonBuild")
        button.setAccessibleName(name)
        button.setText(name)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        source = (
            "ORIGINAL-SHCDE-Pixel | lokal, SHA-geprüft | Spielzustand nicht geprüft"
            if self.native_icons is not None else
            "KEINE ORIGINAL-PIXEL | abweichender Europa-Atlas nicht angezeigt"
        )
        button.setToolTip(
            f"{spec['name']} | XAML: {spec['command']} | {source}"
        )
        button.setIcon(QIcon())
        if self.native_icons is not None and spec["image"]:
            try:
                pixels = self.native_icons.crop(spec["image"])
                button.setIcon(QIcon(pixels))
                button.setIconSize(QSize(42, 42))
            except (OSError, ValueError, KeyError):
                # A corrupt original crop must never become a wrong European
                # picture just because it shares the XAML's numeric rectangle.
                button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
                button.setText(name[:10])
                button.setToolTip(button.toolTip() + " | Quellbild ungültig")
        else:
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            button.setText(name[:10])

    def _choose_slot(self, page, slot):
        # A click queued while changing pages must never dispatch a removed
        # or coincidentally same-position command from ANOTHER XAML page.
        if page != self.category.currentData():
            return
        spec = self._spec_for_slot.get(slot)
        if spec is not None and spec["page"] == page:
            self.choose(spec)

    def _choice_changed(self, index):
        name = self.command_choice.itemData(index)
        if not name or self.studio.original_hud is None:
            return
        page = self.category.currentData()
        spec = next(
            (item for item in self.studio.original_hud.contract["commands"]
             if item["name"] == name and item["page"] == page),
            None,
        )
        if spec is not None:
            self.choose(spec)

    def choose(self, spec):
        """Select a genuine command; only a user binding arms placement."""
        self._current_name = spec["name"]
        target = self.command_choice.findData(self._current_name)
        if target >= 0:
            blocked = self.command_choice.blockSignals(True)
            self.command_choice.setCurrentIndex(target)
            self.command_choice.blockSignals(blocked)
        slot = OriginalHudArtPanel.slot(spec)
        # The XAML allows several conditional commands at the very same
        # (x,y). The selection box exposes them; do not pretend the game
        # supplied a condition that chose a particular variant.
        for index, (button, candidate) in enumerate(self._visible_buttons):
            if OriginalHudArtPanel.slot(candidate) == slot:
                self._spec_for_slot[slot] = spec
                self._visible_buttons[index] = (button, spec)
                self._set_button_spec(button, spec)
                button.setChecked(True)
            else:
                button.setChecked(False)
        command = spec["command"]
        if command:
            art_panel = self.studio.original_hud
            if art_panel is not None:
                page_index = art_panel.page.findData(spec["page"])
                if page_index >= 0:
                    art_panel.page.setCurrentIndex(page_index)
                # Both views must share the command selection as well as
                # the map. The existing panel signal enforces safe bindings.
                art_panel._activate(spec)
            else:
                self.studio._hud_art_selected(command)
        else:
            self.studio.statusBar().showMessage(
                "XAML-Icon ohne ausführbaren CommandParameter; keine Platzierung."
            )

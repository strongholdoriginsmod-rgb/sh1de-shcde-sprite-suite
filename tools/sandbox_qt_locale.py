"""Reversible, data-safe EN/DE localisation of the embedded Qt Sandbox UI.

The legacy Suite is Tkinter; Qt's widgets do not participate in its global
translation pass. This adapter translates Qt control labels, menus, tab names,
tooltips and selected dialogs. Native sprite IDs and persisted team/category
codes are never translated as data.

Dynamic engine reports containing map/asset metadata remain provenance text;
an exact translated message does not imply a fully translated game renderer.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from PySide6.QtCore import QObject, QEvent, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication, QAbstractButton, QComboBox, QDialog,
    QDockWidget, QGroupBox, QLabel, QLineEdit, QMenu, QMessageBox,
    QTabWidget, QWidget,
)

ROOT = Path(__file__).resolve().parents[1]
TRANSLATIONS = ROOT / "config" / "sandbox-qt-sprachen.json"

# Qt control role -> the localized accessibility name. Never use the visible
# mutable frame name as the only accessible label of a numerical input.
ACCESSIBLE_ROLES = {
    "sandbox_original_radar": ("Originalradar", "Original radar"),
    "sandbox_test_board": ("Interaktives Sprite-Testfeld", "Interactive sprite test field"),
    "sandbox_native_tiles": ("Originale Kacheldaten", "Original native tile data"),
    "sandbox_game_map": ("Original-Spielkarte", "Original game map"),
    "sandbox_map_search": ("Originalkarte suchen", "Find original map"),
    "sandbox_map_list": ("Verfügbare Originalkarten", "Available original maps"),
    "sandbox_palette_group": ("Sprite-Gruppe", "Sprite group"),
    "sandbox_palette_page": ("Sprite-Palettenseite", "Sprite palette page"),
    "sandbox_asset_group": ("Sprite-Gruppe der Grafikvorschau", "Preview sprite group"),
    "sandbox_asset_frame": ("Framenummer der Grafikvorschau", "Preview sprite frame"),
    "sandbox_hud_category": ("Spiel-HUD-Kategorie", "Game HUD category"),
    "sandbox_gameplay_category": ("Baugruppe in Spielansicht", "Building category in game view"),
    "sandbox_gameplay_command_choice": ("Baukommando in Spielansicht", "Building command in game view"),
    "sandbox_gameplay_save": ("Karten-Overlay sichern", "Save map overlay"),
    "sandbox_gameplay_undo": ("Karten-Overlay rückgängig", "Undo map overlay"),
    "sandbox_gameplay_redo": ("Karten-Overlay wiederholen", "Redo map overlay"),
    "sandbox_gameplay_open_editor": ("Editor öffnen", "Open editor"),
    "sandbox_gameplay_context_toggle": ("Auswahl oder Minikarte anzeigen", "Show selection or minimap"),
    "sandbox_gameplay_inspect": ("Im Karten-Inspector prüfen", "Inspect in map inspector"),
    "sandbox_gameplay_context_title": ("Spiel-HUD-Auswahl", "Game HUD selection"),
    "sandbox_gameplay_context_brief": ("Auswahldetails", "Selection details"),
    "sandbox_gameplay_context_detail": ("Datenquelle der Auswahl", "Selection data source"),
    "sandbox_hud_engine_mode": ("Grafikquelle der Spielkarte", "Game map sprite source"),
    "sandbox_hud_frame": ("Framenummer zur Platzierung", "Placement frame number"),
    "sandbox_hud_group": ("Sprite-Gruppe zur Platzierung", "Placement sprite group"),
    "sandbox_game_hud_undo": ("Kartenbearbeitung rückgängig", "Undo map edit"),
    "sandbox_game_hud_redo": ("Kartenbearbeitung wiederholen", "Redo map edit"),
    "sandbox_hud_original_page": ("Original-HUD-Bauseite", "Original HUD building page"),
    "sandbox_original_inspector_x": ("Kachel X", "Tile X"),
    "sandbox_original_inspector_y": ("Kachel Y", "Tile Y"),
    "sandbox_original_inspector_frame": ("Framenummer des Overlays", "Overlay frame number"),
    "sandbox_original_inspector_team": ("Team des Overlays", "Overlay team"),
    "sandbox_scene_inspector_team": ("Team des Szenenobjekts", "Scene object team"),
    "sandbox_tool_picker": ("Sandbox-Werkzeug auswählen", "Choose Sandbox tool"),
    "compact_sandbox_tool_picker": ("Sandbox-Werkzeug auswählen", "Choose Sandbox tool"),
    "sandbox_animation_previous": ("Vorheriger Animationsframe", "Previous animation frame"),
    "sandbox_animation_next": ("Nächster Animationsframe", "Next animation frame"),
}


def read_ui_texts(path: Path = TRANSLATIONS) -> dict[str, str]:
    data=json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema")!="sprite-suite.qt-ui-language.v1":
        raise ValueError("Unbekannte Qt-Sprachdatei")
    strings=data.get("en")
    if not isinstance(strings,dict):
        raise ValueError("Fehlende englische Qt-Übersetzung")
    for original, english in strings.items():
        if (not isinstance(original,str) or not isinstance(english,str) or
                not original.strip() or not english.strip()):
            raise ValueError("Ungültiger Eintrag in der Qt-Übersetzungstabelle")
    return strings


def preferred_language(project_root: Path = ROOT) -> str:
    code=os.environ.get("SEDE_SPRACHE","").lower()
    if code in ("de","en"):
        return code
    settings=project_root/"config"/"suite-einstellungen.json"
    try:
        raw=json.loads(settings.read_text(encoding="utf-8"))
    except (OSError,UnicodeError,ValueError):
        return "de"
    return raw.get("sprache") if raw.get("sprache") in ("de","en") else "de"


class QtStudioLanguage(QObject):
    """Translate visible UI strings without altering native group/record IDs."""

    language_changed = Signal(str)

    def __init__(self, studio, *, texts=None, language="de"):
        super().__init__(studio)
        self.studio=studio
        self.en=read_ui_texts() if texts is None else dict(texts)
        # Some English source words legitimately equal the German value
        # (Original, Group IDs, Debug etc). Reverse only distinct strings.
        self.reverse={en:de for de,en in self.en.items() if de!=en}
        self.language="de"
        self._application=QApplication.instance()
        self._filter_attached=False
        self.attach()
        self.studio.statusBar().messageChanged.connect(self._status_changed)
        self.set_language(language)

    def attach(self):
        """Observe newly shown dialogs only while this Studio window exists.

        QApplication is global, and a local Studio can be closed many times
        during a Suite session. Leaving per-Studio event filters installed
        after close leaks QWidget ownership and can translate unrelated Qt
        dialogs in another window.
        """
        if self._application is not None and not self._filter_attached:
            self._application.installEventFilter(self)
            self._filter_attached=True

    def detach(self):
        if self._application is not None and self._filter_attached:
            try:
                self._application.removeEventFilter(self)
            except RuntimeError:
                pass
            self._filter_attached=False

    _DYNAMIC = (
        (
            re.compile(r"^(\d+) von (\d+) Karten$"),
            re.compile(r"^(\d+) of (\d+) maps$"),
            lambda m:f"{m[1]} of {m[2]} maps",
            lambda m:f"{m[1]} von {m[2]} Karten",
        ),
        (
            re.compile(r"^(.+): (\d+) Gebäude, ([\d,]+) Bäume, ([\d,]+) Kacheln$"),
            re.compile(r"^(.+): (\d+) buildings, ([\d,]+) trees, ([\d,]+) tiles$"),
            lambda m:f"{m[1]}: {m[2]} buildings, {m[3]} trees, {m[4]} tiles",
            lambda m:f"{m[1]}: {m[2]} Gebäude, {m[3]} Bäume, {m[4]} Kacheln",
        ),
        (
            re.compile(r"^Eigene Objekte: (\d+)$"),
            re.compile(r"^Custom objects: (\d+)$"),
            lambda m:f"Custom objects: {m[1]}",
            lambda m:f"Eigene Objekte: {m[1]}",
        ),
        (
            re.compile(
                r"^Engine-Snapshot: ([\d,]+) echte Tile-Frames, "
                r"([\d,]+) Objektbefehle; Shaderabgleich noch offen$"
            ),
            re.compile(
                r"^Engine snapshot: ([\d,]+) authentic tile frames, "
                r"([\d,]+) object commands; shader parity pending$"
            ),
            lambda m:(f"Engine snapshot: {m[1]} authentic tile frames, "
                      f"{m[2]} object commands; shader parity pending"),
            lambda m:(f"Engine-Snapshot: {m[1]} echte Tile-Frames, "
                      f"{m[2]} Objektbefehle; Shaderabgleich noch offen"),
        ),
        (
            re.compile(
                r"^Originalradar: (.+) · (\d+)×(\d+) px · "
                r"nur lesende Kartenvorschau, keine spielbare Karte\.$"
            ),
            re.compile(
                r"^Original radar: (.+) · (\d+)×(\d+) px · "
                r"read-only map preview, not gameplay\.$"
            ),
            lambda m:(f"Original radar: {m[1]} · {m[2]}×{m[3]} px · "
                      "read-only map preview, not gameplay."),
            lambda m:(f"Originalradar: {m[1]} · {m[2]}×{m[3]} px · "
                      "nur lesende Kartenvorschau, keine spielbare Karte."),
        ),
        (
            re.compile(
                r"^Originalradar: Keine Karte geladen\. "
                r"Eine Originalkarte über Datei → Öffnen auswählen\.$"
            ),
            re.compile(
                r"^Original radar: No map loaded\. "
                r"Open an original map via File → Open\.$"
            ),
            lambda _m:("Original radar: No map loaded. "
                       "Open an original map via File → Open."),
            lambda _m:("Originalradar: Keine Karte geladen. "
                       "Eine Originalkarte über Datei → Öffnen auswählen."),
        ),
    )

    def translate(self, value: str) -> str:
        if not value:
            return value
        # Real map names, numeric counts and original source IDs are retained;
        # only the natural-language parts of known runtime messages change.
        for german_re, english_re, as_en, as_de in self._DYNAMIC:
            matched=german_re.fullmatch(value) if self.language=="en" else english_re.fullmatch(value)
            if matched:
                return as_en(matched) if self.language=="en" else as_de(matched)
        german=self.reverse.get(value,value)
        return self.en.get(german,german) if self.language=="en" else german

    def _replace(self, current, setter):
        translated=self.translate(current)
        if current != translated:
            setter(translated)

    def _translate_widget(self, obj):
        if isinstance(obj,QDockWidget):
            self._replace(obj.windowTitle(),obj.setWindowTitle)
        elif isinstance(obj,QMenu):
            self._replace(obj.title(),obj.setTitle)
        elif isinstance(obj,QGroupBox):
            self._replace(obj.title(),obj.setTitle)
        if isinstance(obj,QTabWidget):
            for i in range(obj.count()):
                text=obj.tabText(i)
                self._replace(text,lambda translated,i=i:obj.setTabText(i,translated))
                hint=obj.tabToolTip(i)
                self._replace(hint,lambda translated,i=i:obj.setTabToolTip(i,translated))
        if isinstance(obj,QComboBox) and obj.objectName() in {
            "sandbox_hud_category", "sandbox_hud_engine_mode",
            "sandbox_gameplay_category",
            "sandbox_hud_original_page", "sandbox_original_inspector_team",
            "sandbox_scene_inspector_team",
            "compact_sandbox_tool_picker",
        }:
            # Group/source IDs are stored in itemData; changing visible names
            # MUST NOT trigger scene updates, map saves or mode transitions.
            blocked=obj.blockSignals(True)
            try:
                for i in range(obj.count()):
                    current=obj.itemText(i)
                    self._replace(current,lambda translated,i=i:obj.setItemText(i,translated))
            finally:
                obj.blockSignals(blocked)
        if isinstance(obj,QLabel):
            self._replace(obj.text(),obj.setText)
        elif isinstance(obj,QAbstractButton):
            self._replace(obj.text(),obj.setText)
        if isinstance(obj,QLineEdit):
            self._replace(obj.placeholderText(),obj.setPlaceholderText)
        if isinstance(obj,QMessageBox):
            self._replace(obj.text(),obj.setText)
            self._replace(obj.informativeText(),obj.setInformativeText)
            self._replace(obj.detailedText(),obj.setDetailedText)
        if isinstance(obj,QWidget):
            self._replace(obj.windowTitle(),obj.setWindowTitle)
            self._replace(obj.toolTip(),obj.setToolTip)
            role=ACCESSIBLE_ROLES.get(obj.objectName())
            if role:
                name=role[1] if self.language=="en" else role[0]
                if obj.accessibleName()!=name:
                    obj.setAccessibleName(name)
            elif obj.accessibleName():
                self._replace(obj.accessibleName(),obj.setAccessibleName)
        if isinstance(obj,QAction):
            self._replace(obj.text(),obj.setText)
            self._replace(obj.toolTip(),obj.setToolTip)
            self._replace(obj.statusTip(),obj.setStatusTip)

    def _status_changed(self, message: str):
        """Translate Qt statusBar messages at the time they are displayed.

        QStatusBar.currentMessage is not a QLabel in findChildren(); without
        this, the workspace can appear translated while its bottom status
        keeps German (including new messages created after a locale switch).
        """
        translated=self.translate(message)
        if translated!=message:
            self.studio.statusBar().showMessage(translated)

    def refresh(self):
        for obj in (self.studio,*self.studio.findChildren(QWidget),
                    *self.studio.findChildren(QAction)):
            self._translate_widget(obj)
        self._status_changed(self.studio.statusBar().currentMessage())

    def set_language(self, code: str):
        self.language=code if code in ("de","en") else "de"
        self.refresh()
        self.language_changed.emit(self.language)

    def eventFilter(self, obj, event):
        # Message boxes / modeless dialogs created after initial translation
        # should not suddenly revert to German when the Suite is in EN mode.
        if (event.type()==QEvent.Type.Show and isinstance(obj,QDialog)
                and self._owned_dialog(obj)):
            self._translate_widget(obj)
            for child in obj.findChildren(QWidget):
                self._translate_widget(child)
        return False

    def _owned_dialog(self,obj):
        parent=obj.parent()
        while parent is not None:
            if parent is self.studio:
                return True
            parent=parent.parent()
        return False

"""End-to-end Qt Sandbox GUI language, stable keys, and assistive names.

Verifies actual PySide6 widgets. A locale switch may change *only display
text*, never original GM group IDs, teams, HUD categories or scene data.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

pytest.importorskip("PySide6")
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QMessageBox

ROOT=Path(__file__).resolve().parents[2]
for path in (str(ROOT/"src"),str(ROOT/"tools")):
    if path not in sys.path:
        sys.path.insert(0,path)

from sandbox_qt_locale import QtStudioLanguage,read_ui_texts,preferred_language
from sandbox_studio import SandboxStudio


@pytest.fixture
def studio(monkeypatch,tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM","offscreen")
    monkeypatch.setenv("SEDE_SPRACHE","de")
    app=QApplication.instance() or QApplication([])
    window=SandboxStudio(tmp_path)
    try:
        yield window,app
    finally:
        window._saved_scene=window.board.history.scene.serialize()
        if window.native_canvas.has_map():
            window._saved_overlay=window.native_canvas.history.overlay.serialize()
        window.native_canvas._poll.stop()
        window.board._asset_poll.stop()
        window.asset_preview.timer.stop()
        window.close()
        window.deleteLater()
        app.processEvents()


def _action(studio,text):
    match=[a for a in studio.findChildren(QAction) if a.text()==text]
    assert len(match)==1,(text,[(a.text(),a.shortcut().toString()) for a in studio.findChildren(QAction)][:20])
    return match[0]


def test_qt_file_menu_tabs_hud_combo_and_accessible_names_roundtrip(studio):
    w,app=studio
    native_group=w.native_hud.group
    w.native_hud.category.setCurrentIndex(0)
    before=[native_group.itemText(i) for i in range(native_group.count())]
    if before:
        assert all("castle" in g or "buildings" in g or
                   "walls" in g or "workshops" in g or "churches" in g
                   for g in before)
    else:
        # A clean checkout has no private original-game mapping. It must
        # present no made-up native groups, yet still support locale changes.
        assert w.native_hud.group.count() == 0
        assert not (ROOT / "work" / "mapping" / "proposals.json.gz").is_file()
    # Keep QAction identity rather than assuming a fixed label: Save and F5
    # intentionally name the *visible* workspace and change across tabs.
    original_actions={a:(a.text(),a.shortcut().toString())
                      for a in w.findChildren(QAction)
                      if a.text() and a.shortcut().toString()}
    qt_frame=w.asset_preview.frame.value()

    w.set_ui_language("en")
    assert _action(w,"Open original map").shortcut().toString()=="Ctrl+O"
    assert w.tabs.tabText(0)=="Original map: Radar"
    assert w.tabs.tabText(3)=="Game map (original tiles + sprites)"
    assert w.native_hud.category.itemText(0)=="Buildings"
    assert w.native_hud.category.currentData()=="Gebäude"
    w.native_hud._populate()
    assert before==[native_group.itemText(i) for i in range(native_group.count())]
    assert w.native_hud.engine_mode.itemText(0)=="Engine + working sprites"
    assert w.native_canvas.accessibleName()=="Original game map"
    assert w.asset_preview.frame.accessibleName()=="Preview sprite frame"
    assert w.asset_preview.frame.value()==qt_frame
    assert w.native_inspector.team.itemText(0)=="red"
    assert w.native_inspector.team.itemData(0)=="rot"
    assert w.inspector.team.itemText(1)=="blue"
    assert w.inspector.team.itemData(1)=="blau"

    w.set_ui_language("de")
    assert _action(w,"Originalkarte öffnen").shortcut().toString()=="Ctrl+O"
    assert w.tabs.tabText(0)=="Originalkarte: Radar"
    assert w.native_hud.category.itemText(0)=="Gebäude"
    assert w.native_inspector.team.itemText(0)=="rot"
    assert w.native_canvas.accessibleName()=="Original-Spielkarte"
    assert w.native_hud.category.currentData()=="Gebäude"
    assert before==[native_group.itemText(i) for i in range(native_group.count())]

    w.set_ui_language("en")
    assert _action(w,"Open original map").shortcut().toString()=="Ctrl+O"
    # Qt can lazily create internal menu/combo actions. User-defined command
    # shortcuts must stay stable; total QObject action count need not be fixed.
    for action,(label,shortcut) in original_actions.items():
        assert action.shortcut().toString()==shortcut
        if action not in w._workspace_actions.values():
            translated=w.ui_language.en.get(label,label)
            assert action.text()==translated
    reload_action=w._workspace_actions["reload"]
    save_action=w._workspace_actions["save"]
    assert reload_action.text()=="Reload original map"
    assert reload_action.shortcut().toString()=="F5"
    assert save_action.text()=="Save current scene"
    assert not save_action.isEnabled()
    w.show_test_field()
    assert reload_action.text()=="Reload test sprites"
    assert save_action.text()=="Save test scene"
    assert save_action.isEnabled()
    w.set_ui_language("de")
    assert reload_action.text()=="Sprite-Grafiken neu laden"
    assert save_action.text()=="Testszene speichern"
    w.set_ui_language("en")
    assert reload_action.text()=="Reload test sprites"
    assert save_action.text()=="Save test scene"
    assert reload_action.shortcut().toString()=="F5"
    assert save_action.shortcut().toString()=="Ctrl+S"


def test_qt_real_dialogs_translate_on_show(studio):
    w,app=studio
    w.set_ui_language("en")
    box=QMessageBox(w)
    box.setWindowTitle("Originalkarte öffnen")
    box.setText("Originalkarte öffnen")
    box.show()
    app.processEvents()
    try:
        assert box.windowTitle()=="Open original map"
        assert box.text()=="Open original map"
    finally:
        box.close()


def test_game_hud_technical_category_and_team_selection_remain_stable(studio):
    w,app=studio
    w.set_ui_language("en")
    for name in ("Buildings","Units","Nature","Terrain","Effects","All"):
        w.native_hud.category.setCurrentText(name)
        german=w.native_hud.category.currentData()
        assert german in {"Gebäude","Einheiten","Natur","Gelände","Effekte","Alle"}
        groups=[w.native_hud.group.itemText(i) for i in range(w.native_hud.group.count())]
        if not groups:
            # A user-private cache must never be fabricated in a clean clone.
            assert not (ROOT / "work" / "mapping" / "proposals.json.gz").is_file()
            assert w.native_hud.group.count() == 0
        elif german=="Einheiten":
            assert all(g.startswith(("body_","anim_")) for g in groups)
        elif german=="Gelände":
            assert all(g.startswith("tile_") for g in groups)
    for combo in (w.native_inspector.team,w.inspector.team):
        combo.setCurrentText("green")
        assert combo.currentData()=="gruen"
        combo.setCurrentText("none")
        assert combo.currentData()=="keine"


def test_widget_labels_remain_user_facing_and_native_ids_unchanged(studio):
    w,app=studio
    for obj in (w.sprite_palette.group,w.asset_preview.group):
        first=[obj.itemText(i) for i in range(min(obj.count(),12))]
        w.set_ui_language("en")
        assert [obj.itemText(i) for i in range(min(obj.count(),12))]==first
        w.set_ui_language("de")
        assert [obj.itemText(i) for i in range(min(obj.count(),12))]==first
    w.set_ui_language("en")
    assert w.native_inspector.assign_surface.text()=="Test palette sprite for surface 3037"
    assert w.native_inspector.engine_edit.text()=="Edit this engine tile graphic"


def test_language_config_is_valid_and_invalid_user_preference_defaults(tmp_path,monkeypatch):
    strings=read_ui_texts()
    assert len(strings)>135
    assert strings["Originalkarte öffnen"]=="Open original map"
    monkeypatch.delenv("SEDE_SPRACHE",raising=False)
    assert preferred_language(tmp_path)=="de"
    cfg=tmp_path/"config"/"suite-einstellungen.json"
    cfg.parent.mkdir()
    cfg.write_text(json.dumps({"sprache":"en"}),encoding="utf-8")
    assert preferred_language(tmp_path)=="en"
    cfg.write_text("corrupt",encoding="utf-8")
    assert preferred_language(tmp_path)=="de"
    monkeypatch.setenv("SEDE_SPRACHE","en")
    assert preferred_language(tmp_path)=="en"


def test_dynamic_counts_are_translated_without_touching_map_metadata(studio):
    w,app=studio
    w.set_ui_language("en")
    assert w.mapcount.text()=="0 of 0 maps"
    w.native_hud.map_title.setText(
        "Antioch: 27 Gebäude, 1,139 Bäume, 44,121 Kacheln"
    )
    w.native_hud.overlay_count.setText("Eigene Objekte: 12")
    w.native_hud.values.setText("Engine-Snapshot: 44,104 echte Tile-Frames, 1,040 Objektbefehle; Shaderabgleich noch offen")
    w.ui_language.refresh()
    assert w.native_hud.map_title.text()=="Antioch: 27 buildings, 1,139 trees, 44,121 tiles"
    assert w.native_hud.overlay_count.text()=="Custom objects: 12"
    assert w.native_hud.values.text()==(
        "Engine snapshot: 44,104 authentic tile frames, "
        "1,040 object commands; shader parity pending"
    )

    w.native_hud._modified()  # source logic still sets German text
    app.processEvents()
    app.processEvents()
    assert w.native_hud.overlay_count.text()=="Custom objects: 0"

    w.set_ui_language("de")
    assert w.native_hud.map_title.text()=="Antioch: 27 Gebäude, 1,139 Bäume, 44,121 Kacheln"
    assert w.native_hud.overlay_count.text()=="Eigene Objekte: 0"


def test_accessible_navigation_keyboard_tooltips_are_in_selected_language(studio):
    w,app=studio
    w.set_ui_language("en")
    assert w.animation_panel.back.accessibleName()=="Previous animation frame"
    assert w.animation_panel.forward.accessibleName()=="Next animation frame"
    assert w.native_canvas.accessibleName()=="Original game map"
    assert "arrow keys" in w.native_canvas.toolTip().lower()
    assert w.native_hud.undo.accessibleName()=="Undo map edit"
    assert w.native_hud.redo.accessibleName()=="Redo map edit"
    w.set_ui_language("de")
    assert w.animation_panel.back.accessibleName()=="Vorheriger Animationsframe"
    assert "Pfeiltasten" in w.native_canvas.toolTip()


def test_qt_global_dialog_filter_is_detached_on_close_and_reused_after_show(studio):
    """Closed Studio must not globally own or translate another Qt window."""
    w,app=studio
    language=w.ui_language
    assert language._filter_attached is True
    w.set_ui_language("en")
    # Closing a Studio is not necessarily object destruction. QApplication's
    # global event filter must be removed immediately, even if the same
    # QWidget is retained and reopened later by a test or host.
    w._saved_scene=w.board.history.scene.serialize()
    assert w.close()
    assert not language._filter_attached
    w.show()
    app.processEvents()
    assert language._filter_attached
    notice=QMessageBox(w)
    notice.setWindowTitle("Originalkarte öffnen")
    notice.show()
    app.processEvents()
    try:
        assert notice.windowTitle()=="Open original map"
    finally:
        notice.close()

def test_status_bar_and_compact_tab_labels_are_truly_bilingual(studio):
    w,app=studio
    message=(
        "Echte Kachelkoordinaten aus .map mit Sprite-Texturvorschau. "
        "Overlay-Bearbeitungen ändern niemals die Originalkarte."
    )
    english=(
        "Real .map tile coordinates with sprite preview. "
        "Overlay edits never change the original game map."
    )
    w.set_ui_language("en")
    w.statusBar().showMessage(message)
    assert w.statusBar().currentMessage()==english
    # Both a language switch and an English message emitted while already
    # translated are handled; no recursive messageChanged loop.
    w.set_ui_language("de")
    assert w.statusBar().currentMessage()==message
    w.set_ui_language("en")
    assert w.statusBar().currentMessage()==english
    w.statusBar().showMessage(message)
    assert w.statusBar().currentMessage()==english
    w.set_ui_language("de")
    assert w.statusBar().currentMessage()==message

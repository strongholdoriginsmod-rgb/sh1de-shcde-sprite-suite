"""Proof tests for the embedded game/editor separation (HUD-01/HUD-02).

These do NOT assert pixel identity to the historic game or simulated economy.
The native scene and HUD bindings stay in memory; no installed files written.
"""
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication, QDockWidget

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))


@pytest.fixture
def session(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("SEDE_SPRACHE", "de")
    from sandbox_studio import SandboxStudio
    from sandbox_suite_embed import EmbeddedSandboxStudio

    app = QApplication.instance() or QApplication([])
    studio = SandboxStudio(tmp_path)
    host = SimpleNamespace(_window=studio)
    EmbeddedSandboxStudio._compact_for_suite(host)
    studio.show()
    app.processEvents()
    try:
        yield app, studio, host.workspace
    finally:
        if host.workspace.game_mode:
            host.workspace.set_mode("editor")
        studio.native_canvas._poll.stop()
        studio.board._asset_poll.stop()
        studio.asset_preview.timer.stop()
        studio._saved_scene = studio.board.history.scene.serialize()
        studio.close()
        app.processEvents()



@pytest.fixture
def real_map_session(monkeypatch):
    """Optional on-disk, read-only original-game QA; never mock a live map."""
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("SEDE_SPRACHE", "de")
    maps=Path(
        "E:/SSGameQA/Stronghold Crusader Definitive Edition_Data/"
        "StreamingAssets/Maps"
    )
    if not maps.is_dir():
        pytest.skip("Local read-only original-game QA maps unavailable")
    from sandbox_studio import SandboxStudio
    from sandbox_suite_embed import EmbeddedSandboxStudio
    app=QApplication.instance() or QApplication([])
    studio=SandboxStudio(maps)
    host=SimpleNamespace(_window=studio)
    EmbeddedSandboxStudio._compact_for_suite(host)
    studio.show()
    app.processEvents()
    if not studio.native_canvas.has_map():
        studio.native_canvas._poll.stop()
        studio.board._asset_poll.stop()
        studio.asset_preview.timer.stop()
        studio._saved_scene=studio.board.history.scene.serialize()
        studio.close()
        pytest.skip("No native original map can be loaded")
    try:
        yield app,studio,host.workspace
    finally:
        if host.workspace.game_mode:
            host.workspace.set_mode("editor")
        studio.native_canvas._poll.stop()
        studio.board._asset_poll.stop()
        studio.asset_preview.timer.stop()
        studio._saved_scene=studio.board.history.scene.serialize()
        # A failing QA test can leave temporary in-memory overlay edits.
        # Avoid a modal save prompt during teardown; never write an overlay.
        studio._saved_overlay=(
            studio.native_canvas.history.overlay.serialize()
            if studio.native_canvas.history is not None else None
        )
        studio.close()
        app.processEvents()


def test_game_mode_is_attached_to_exact_editor_canvas_and_live_minimap(session):
    app, studio, layout = session
    native = studio.native_canvas
    scene = native.scene()
    history = native.history
    minimap = studio.native_minimap
    original_parent = minimap.parentWidget()

    assert not layout.game_mode
    layout.set_mode("game")
    app.processEvents()

    assert layout.game_mode
    assert studio.tabs.currentIndex() == 3
    assert studio.tabs.widget(3) is native
    assert native.scene() is scene
    assert native.history is history
    assert layout.game_hud.isVisible()
    assert minimap.parentWidget() is layout.game_hud.radar_page
    assert minimap.map_canvas is native
    assert not studio.tabs.tabBar().isVisible()
    assert not layout._toolbar.isVisible()
    assert not layout.left_open and not layout.right_open
    assert not any(dock.isVisible() for dock in (
        *layout._left_docks, *layout._right_docks
    ))

    layout.game_hud.edit.click()
    app.processEvents()
    assert not layout.game_mode
    assert studio.tabs.widget(3) is native
    assert native.history is history
    assert native.scene() is scene
    assert minimap.parentWidget() is original_parent
    assert studio.tabs.tabBar().isVisible()
    assert layout._toolbar.isVisible()
    assert studio._native_dock.isVisible()


@pytest.mark.parametrize("width,height", [(1168, 550), (784, 350)])
def test_small_game_mode_keeps_map_and_hud_visible(session, width, height):
    app, studio, layout = session
    studio.resize(width, height)
    layout.set_mode("game")
    layout.refresh_size()
    app.processEvents()
    layout.refresh_size()
    app.processEvents()
    assert layout.game_hud.height() <= max(116, min(175, round(height * .29)))
    assert layout.game_hud.width() > 0
    assert studio.native_canvas.height() >= 100
    assert studio.tabs.width() >= studio.width() * .85
    assert layout.game_hud.command_choice.isVisible()
    assert layout.game_hud.edit.isVisible()
    assert layout.game_hud.save.isVisible()
    assert layout.game_hud.commands.isVisible()


def test_editor_dock_focus_and_selection_restore_without_cloning_scene(session):
    app, studio, layout = session
    layout.toggle_palette()
    layout.show_tool(studio._hud_dock)
    studio.tabs.setCurrentIndex(1)
    selection = layout._selected_right
    assert selection is studio.inspector_dock
    assert layout.left_open and layout.right_open
    layout.set_mode("game")
    layout.set_mode("editor")
    app.processEvents()
    assert layout.left_open and layout.right_open
    assert layout._selected_right is selection
    assert studio.inspector_dock.isVisible()
    assert studio.tabs.widget(1) is studio.board
    assert studio.tabs.widget(3) is studio.native_canvas
    # Selecting an expert tool explicitly exits the game view.
    layout.set_mode("game")
    layout.show_tool(studio._native_dock)
    assert not layout.game_mode
    assert studio._native_dock.isVisible()


def test_original_xaml_command_only_arms_when_user_test_binding_exists(session, monkeypatch):
    app, studio, layout = session
    if studio.original_hud is None:
        pytest.skip("Optional local original-XAML art not present")
    hud = layout.game_hud
    assert hud.category.count() == 14
    assert hud.command_choice.count() > 1
    assert len(hud._visible_buttons) > 0
    spec = next(
        (candidate for _,candidate in hud._visible_buttons if candidate["command"]),
        None,
    )
    assert spec is not None
    called = []
    monkeypatch.setattr(
        studio.native_canvas, "arm_placement",
        lambda group, frame: called.append((group, frame)),
    )
    monkeypatch.setattr(
        studio, "_hud_bindings", SimpleNamespace(get=lambda _command: None)
    )
    layout.set_mode("game")
    # Trigger the actual rendered button, not merely the helper behind it.
    icon_button=next(button for button,item in hud._visible_buttons if item is spec)
    icon_button.click()
    assert not called  # An XAML icon alone does not prove an engine binding.
    assert hud.command_choice.currentData() == spec["name"]
    binding = SimpleNamespace(group="tile_castle", frame=1193)
    monkeypatch.setattr(
        studio, "_hud_bindings",
        SimpleNamespace(get=lambda command: binding
                        if command == spec["command"] else None),
    )
    icon_button.click()
    # A recognized XAML command is not enough: placement requires an actual
    # successfully decoded native map. Do not silently arm a hidden target.
    assert called == []
    assert "Originalkarte" in studio.statusBar().currentMessage()
    monkeypatch.setattr(studio, "show_native_map", lambda: True)
    icon_button.click()
    assert called == [("tile_castle", 1193)]
    assert studio.original_hud.active_name == spec["name"]
    assert studio.tabs.currentIndex() == 3


def test_game_mode_is_reversible_across_language_change(session):
    app, studio, layout = session
    layout.set_mode("game")
    studio.set_ui_language("en")
    app.processEvents()
    assert layout.game_hud.map_label.text() == "Load an original map via File → Open"
    assert layout.game_hud.provenance.text() == "Resources: not available"
    # A fresh checkout has no private native Noesis cache. In that case the
    # GUI must stay explicitly unavailable instead of fabricating categories.
    native_pages = studio.original_hud is not None
    if native_pages:
        layout.game_hud.category.setCurrentIndex(1)
        assert "Keeps" in layout.game_hud.category.currentText()
    else:
        assert layout.game_hud.category.count() == 1
        assert layout.game_hud.category.currentData() is None
        assert "XAML" in layout.game_hud.category.currentText()
    assert layout.game_mode
    assert studio.tabs.widget(3) is studio.native_canvas
    layout.game_hud.edit.click()
    app.processEvents()
    assert not layout.game_mode
    layout.set_mode("game")
    studio.set_ui_language("de")
    app.processEvents()
    assert layout.game_hud.isVisible()
    if native_pages:
        assert layout.game_hud.category.currentData() == "B"
        assert "Bergfriede" in layout.game_hud.category.currentText()
    else:
        assert layout.game_hud.category.currentData() is None
        assert "XAML" in layout.game_hud.category.currentText()
    assert layout.game_hud.provenance.text() == "Ressourcen: nicht verfügbar"


@pytest.mark.parametrize("width,height", [
    (1168, 499), (1280, 720), (1500, 800), (784, 299), (960, 427),
])
def test_reference_anchor_is_right_bottom_and_small_size_falls_back(width,height):
    from sandbox_compact_layout import gameplay_hud_bounds, REFERENCE_HUD, REFERENCE_SCREEN
    x,y,w,h=gameplay_hud_bounds(width,height)
    assert x+w==width and y+h==height
    assert 0<h<=height and 0<w<=width
    if width>=1050 and height>=400:
        assert abs(x/width - REFERENCE_HUD[0]/REFERENCE_SCREEN[0])<.005
    else:
        assert x==0  # Keep critical controls accessible at notebook width.


def test_game_hud_overlaps_map_instead_of_shrinking_map(session):
    app,studio,layout=session
    studio.resize(1168,542)
    layout.set_mode("game")
    app.processEvents()
    layout.refresh_size()
    app.processEvents()
    host=layout.game_host
    canvas=studio.native_canvas
    hud=layout.game_hud
    assert canvas.height()>hud.height()+160
    assert studio.tabs.height()>=host.height()-2
    assert hud.x()>host.width()*.40  # historic lower-right anchor
    assert hud.x()+hud.width()==host.width()
    assert hud.y()+hud.height()==host.height()
    assert hud.parentWidget() is host
    # A left-bottom point is a true map input surface, not obscured by HUD.
    from PySide6.QtCore import QPoint
    point=canvas.viewport().mapTo(host,QPoint(20,canvas.viewport().height()-20))
    assert not hud.geometry().contains(point)
    assert layout.game_hud.commands.viewport().isVisible()
    layout.set_mode("editor")
    app.processEvents()
    assert not hud.isVisible()
    assert studio.tabs.height()>=host.height()-2


def test_selection_panel_shows_real_original_building_and_opens_inspector(
    real_map_session
):
    app,studio,layout=real_map_session
    canvas=studio.native_canvas
    layout.set_mode("game")
    # Select the real section-1013 QGraphicsItem: do not spoof has_map()
    # on an uninitialized renderer (that can crash Qt during paint).
    marker=next((item for item in canvas.scene().items()
                 if item.data(0) is not None),None)
    assert marker is not None
    building=marker.data(0)
    marker.setSelected(True)
    app.processEvents()
    hud=layout.game_hud
    assert hud.context_stack.currentIndex()==1
    assert hud.context_title.text()=="Originalbauwerk"
    assert f"Typ-ID {building.type_id}" in hud.context_brief.text()
    assert "nur lesen" in hud.context_title.toolTip()
    assert str(building.uid) in hud.inspect.toolTip()
    assert not hud.radar_page.isVisible()
    hud.context_toggle.click()
    app.processEvents()
    assert hud.context_stack.currentIndex()==0
    assert studio.native_minimap.isVisible()
    hud.context_toggle.click()
    app.processEvents()
    assert hud.context_stack.currentIndex()==1
    hud.inspect.click()
    app.processEvents()
    assert not layout.game_mode
    assert layout._selected_right is studio._native_dock
    assert studio._native_dock.isVisible()


def test_live_selection_uses_real_tree_tile_and_reversible_locale(
    real_map_session
):
    app,studio,layout=real_map_session
    canvas=studio.native_canvas
    layout.set_mode("game")
    hud=layout.game_hud
    marker=next((item for item in canvas.scene().items()
                 if item.data(1) is not None),None)
    assert marker is not None
    tree=marker.data(1)
    actual=canvas._channels.at(tree.x,tree.y)
    assert canvas.select_native(tree.x,tree.y)
    app.processEvents()
    assert hud.context_stack.currentIndex()==1
    assert hud.context_title.text()=="Originalkachel"
    assert f"3005={actual[3005]}" in hud.context_brief.text()
    marker.setSelected(True)
    app.processEvents()
    assert hud.context_title.text()=="Originalvegetation"
    assert f"Rohgruppe {tree.raw_group}" in hud.context_brief.text()
    assert "1014" in hud.context_title.toolTip()
    studio.set_ui_language("en")
    app.processEvents()
    assert hud.context_title.text()=="Original vegetation"
    assert f"Raw group {tree.raw_group}" in hud.context_brief.text()
    assert hud.context_stack.currentIndex()==1
    studio.set_ui_language("de")
    app.processEvents()
    assert hud.context_title.text()=="Originalvegetation"
    marker.setSelected(False)
    # Simulate the identity invalidation normally performed on loading
    # another source, without modifying either .map on disk.
    hud._map_identity=Path("previous-map-key.map")
    hud._queue_context()
    app.processEvents()
    assert hud._last_tile is None
    assert hud.context_stack.currentIndex()==0
    assert hud.context_title.text()=="Originalkarte"


def test_conditional_xaml_variant_changes_visible_icon_and_click_target(
    session, monkeypatch
):
    from collections import defaultdict
    from sandbox_hud_original_art import OriginalHudArtPanel
    app,studio,layout=session
    art=studio.original_hud
    if art is None:
        pytest.skip("No local verified XAML crops")
    pairs=defaultdict(list)
    for item in art.contract["commands"]:
        pairs[(item["page"],OriginalHudArtPanel.slot(item))].append(item)
    group=next(
        variants for variants in pairs.values()
        if len(variants)>1 and variants[0]["image"]!=variants[1]["image"]
    )
    original,variant=group[:2]
    hud=layout.game_hud
    hud.category.setCurrentIndex(hud.category.findData(variant["page"]))
    matching=next(
        (button,selected) for button,selected in hud._visible_buttons
        if OriginalHudArtPanel.slot(selected)==OriginalHudArtPanel.slot(variant)
    )
    button,original_slot=matching
    assert original_slot["name"]==original["name"]
    original_icon=button.icon().cacheKey()
    called=[]
    monkeypatch.setattr(studio.native_canvas,"arm_placement",
                        lambda group,frame:called.append((group,frame)))
    wanted=SimpleNamespace(group="tile_castle",frame=1193)
    monkeypatch.setattr(
        studio,"_hud_bindings",
        SimpleNamespace(get=lambda command:wanted
                        if command==variant["command"] else None),
    )
    layout.set_mode("game")
    option=hud.command_choice.findData(variant["name"])
    assert option>0
    hud.command_choice.setCurrentIndex(option)
    assert hud._spec_for_slot[OriginalHudArtPanel.slot(variant)] is variant
    assert variant["name"] in button.toolTip()
    assert button.accessibleName()==variant["name"].removeprefix("ButtonBuild")
    assert button.icon().cacheKey()!=original_icon
    called.clear()
    button.click()
    assert not called  # A variant may be selected without a native map.
    assert "Originalkarte" in studio.statusBar().currentMessage()
    monkeypatch.setattr(studio, "show_native_map", lambda: True)
    button.click()
    assert called==[("tile_castle",1193)]
    assert art.active_name==variant["name"]
    assert hud.command_choice.currentData()==variant["name"]
    # A queued click from a now-removed page must never place a different
    # command, even if its XAML slot coordinates happen to be identical.
    previous_page=variant["page"]
    previous_slot=OriginalHudArtPanel.slot(variant)
    hud.category.setCurrentIndex((hud.category.currentIndex()+1)
                                 % hud.category.count())
    called.clear()
    hud._choose_slot(previous_page,previous_slot)
    assert not called



def test_actions_expose_no_fake_undo_save_or_placement_without_map(session):
    app,studio,layout=session
    hud=layout.game_hud
    layout.set_mode("game")
    app.processEvents()
    assert not studio.native_canvas.has_map()
    assert not hud.place.isEnabled()
    assert not hud.undo.isEnabled()
    assert not hud.redo.isEnabled()
    assert not hud.save.isEnabled()
    studio.set_ui_language("en")
    app.processEvents()
    assert hud.place.text()=="Place"
    assert "No unsaved" in hud.save.toolTip()
    studio.set_ui_language("de")
    app.processEvents()
    assert hud.place.text()=="Platzieren"


def test_real_map_undo_redo_cancel_and_safe_overlay_save(
    real_map_session, tmp_path
):
    import hashlib
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    app,studio,layout=real_map_session
    hud=layout.game_hud
    canvas=studio.native_canvas
    assert layout.game_mode and canvas.has_map()
    src=Path(studio._current)
    original_hash=hashlib.sha256(src.read_bytes()).hexdigest()
    initial=canvas.history.overlay.serialize()
    assert studio._saved_overlay==initial
    assert not hud.undo.isEnabled() and not hud.redo.isEnabled()
    assert not hud.save.isEnabled()
    studio.native_hud.group.setCurrentText("tree_pine")
    studio.native_hud.frame.setValue(20)
    assert hud.place.isEnabled()

    # A second click is a visible cancellation, not a second placement.
    hud.place.click()
    app.processEvents()
    assert canvas._placing==("tree_pine",20)
    assert hud.place.text()=="Abbrechen"
    hud.place.click()
    app.processEvents()
    assert canvas._placing is None
    assert hud.place.text()=="Platzieren"
    assert canvas.history.overlay.serialize()==initial
    assert not hud.undo.isEnabled() and not hud.save.isEnabled()

    # The native keyboard Escape is the exact same safe cancellation.
    hud.place.click()
    QTest.keyClick(canvas,Qt.Key.Key_Escape)
    app.processEvents()
    assert canvas._placing is None and hud.place.text()=="Platzieren"
    assert not hud.save.isEnabled()

    hud.place.click()
    x,y=canvas._keyboard_anchor()
    assert canvas.is_editable_native(x,y)
    ident=canvas._place_native(x,y)
    app.processEvents()
    assert ident
    assert len(canvas.history.overlay.objects)==len(initial["objects"])+1
    assert hud.undo.isEnabled() and hud.save.isEnabled()
    assert not hud.redo.isEnabled()

    hud.undo.click()
    app.processEvents()
    assert canvas.history.overlay.serialize()==initial
    assert not hud.undo.isEnabled()
    assert hud.redo.isEnabled()
    assert not hud.save.isEnabled()

    hud.redo.click()
    app.processEvents()
    assert hud.undo.isEnabled() and hud.save.isEnabled()
    assert not hud.redo.isEnabled()

    # Redirect only the working overlay save to a test-specific path.
    # Never click Save when it still points to the user's project overlay.
    output=tmp_path/"hud-working.overlay.json"
    studio._overlay_path=output
    hud.save.click()
    app.processEvents()
    assert output.is_file()
    assert not hud.save.isEnabled()
    assert studio._saved_overlay==canvas.history.overlay.serialize()

    hud.undo.click()
    app.processEvents()
    assert hud.redo.isEnabled() and hud.save.isEnabled()
    hud.redo.click()
    app.processEvents()
    assert not hud.redo.isEnabled() and not hud.save.isEnabled()
    canvas.cancel_placement()
    assert canvas._placing is None
    assert hashlib.sha256(src.read_bytes()).hexdigest()==original_hash



def test_catalogue_armed_sprite_rearms_identically_after_cancellation(
    real_map_session
):
    app,studio,layout=real_map_session
    canvas=studio.native_canvas
    hud=layout.game_hud
    initial=canvas.history.overlay.serialize()
    studio.native_hud.group.setCurrentText("tile_castle")
    studio.native_hud.frame.setValue(1193)
    # This is the exact Canvas API called by Tk Catalogue -> Qt bridge.
    canvas.arm_placement("tree_pine",20)
    app.processEvents()
    assert canvas._placing==("tree_pine",20)
    assert studio.native_hud.group.currentText()=="tree_pine"
    assert studio.native_hud.frame.value()==20
    assert "tree_pine/20" in hud.place.toolTip()
    assert hud.place.text()=="Abbrechen"

    hud.place.click()
    app.processEvents()
    assert canvas._placing is None
    assert "tree_pine/20" in hud.place.toolTip()
    hud.place.click()
    app.processEvents()
    assert canvas._placing==("tree_pine",20)
    assert studio.native_hud.group.currentText()=="tree_pine"
    assert studio.native_hud.frame.value()==20
    canvas.cancel_placement()
    assert canvas.history.overlay.serialize()==initial



def test_unsupported_native_map_fail_closed_without_stale_hud_actions(
    real_map_session, monkeypatch
):
    """A readable radar with failed tile decoding cannot inherit map A state."""
    import hashlib
    from stronghold_europe_de.sandbox import map_sections

    app,studio,layout=real_map_session
    canvas=studio.native_canvas
    hud=layout.game_hud
    source_a=Path(studio._current)
    source_b=source_a.with_name("Crusader Demo.map")
    if not source_b.is_file():
        pytest.skip("Second read-only original QA map absent")
    digests={
        source_a:hashlib.sha256(source_a.read_bytes()).hexdigest(),
        source_b:hashlib.sha256(source_b.read_bytes()).hexdigest(),
    }
    marker=next(
        (item for item in canvas.scene().items() if item.data(1) is not None),
        None,
    )
    assert marker is not None
    tree=marker.data(1)
    assert canvas.select_native(tree.x,tree.y)
    marker.setSelected(True)
    canvas.arm_placement("tree_pine",20)
    app.processEvents()
    assert hud.place.text()=="Abbrechen"
    assert hud.context_title.text()=="Originalvegetation"
    assert studio.native_minimap._radar_pixmap is not None

    native_decoder = map_sections.load_native_tile_channels
    def reject_native(_source):
        raise map_sections.MapFormatError("QA: unsupported native tiles")
    monkeypatch.setattr(map_sections,"load_native_tile_channels",reject_native)
    assert studio.open_map(source_b)  # Radar can open, engine cannot.
    app.processEvents()
    assert studio._current==source_b
    assert not canvas.has_map()
    assert canvas._map_path is None
    assert canvas.runtime_renderer is None
    assert canvas.runtime_snapshot is None
    assert canvas.last_engine_pick is None
    assert canvas._placing is None and canvas.history is None
    assert not hud.place.isEnabled()
    assert not hud.undo.isEnabled() and not hud.redo.isEnabled()
    assert not hud.save.isEnabled()
    assert hud._last_tile is None
    assert hud.context_title.text()=="Keine Originalkarte"
    assert hud.context_stack.currentIndex()==0
    assert studio.native_minimap._radar_pixmap is None
    assert not studio.native_minimap.scene().items()
    assert "unsupported native tiles" in studio.statusBar().currentMessage()
    # Recovery after a failed native load must not require restarting Qt.
    monkeypatch.setattr(map_sections,"load_native_tile_channels",native_decoder)
    assert studio.open_map(source_a)
    app.processEvents()
    assert canvas.has_map() and canvas._map_path==source_a
    assert canvas.history is not None
    assert studio.native_minimap._radar_pixmap is not None
    assert hud.context_stack.currentIndex()==0
    assert hud._last_tile is None
    assert hud.place.isEnabled()
    assert not hud.undo.isEnabled() and not hud.redo.isEnabled()
    assert not hud.save.isEnabled()
    for source, old_digest in digests.items():
        assert hashlib.sha256(source.read_bytes()).hexdigest()==old_digest



@pytest.mark.parametrize("width,height", [(1168,542),(784,342)])
def test_historic_green_spine_is_measured_accessible_and_live(
    real_map_session, width, height
):
    from PySide6.QtCore import QPoint
    from sandbox_hud_chrome_geometry import spine_width,chrome_alignment_error
    app,studio,layout=real_map_session
    studio.resize(width,height)
    app.processEvents()
    layout.refresh_size()
    app.processEvents()
    hud=layout.game_hud
    canvas=studio.native_canvas
    assert layout.game_mode and hud.isVisible()
    assert hud.spine.isVisible()
    assert hud.spine.width()==spine_width(hud.width())
    assert abs(chrome_alignment_error(hud.width(),hud.spine.x()))<.055
    assert hud.radar_page.objectName()=="sandbox_gameplay_radar_frame"
    assert hud.spine.objectName()=="sandbox_gameplay_control_spine"
    for control in (hud.spine_radar,hud.context_toggle,hud.spine_inspect):
        assert control.isVisible()
        assert control.isEnabled()
        assert control.accessibleName()
        assert control.toolTip()
        rect=control.geometry()
        assert rect.left()>=0 and rect.right()<=hud.spine.width()
        assert rect.top()>=0 and rect.bottom()<=hud.spine.height()
    original_scene=canvas.scene()
    original_history=canvas.history
    original_radar=studio.native_minimap
    assert original_radar.parentWidget() is hud.radar_page

    marker=next((i for i in canvas.scene().items() if i.data(0) is not None),None)
    assert marker is not None
    marker.setSelected(True)
    app.processEvents()
    assert hud.context_stack.currentIndex()==1
    assert hud.radar_title.text()=="Originalbauwerk"
    hud.spine_radar.click()
    app.processEvents()
    assert hud.context_stack.currentIndex()==0
    assert original_radar.isVisible()
    assert "Originalradar" in hud.radar_title.text()
    hud.context_toggle.click()
    app.processEvents()
    assert hud.context_stack.currentIndex()==1
    assert hud.radar_title.text()=="Originalbauwerk"
    hud.spine_inspect.click()
    app.processEvents()
    assert not layout.game_mode
    assert layout._selected_right is studio._native_dock
    assert original_scene is canvas.scene()
    assert original_history is canvas.history
    assert original_radar is studio.native_minimap


def test_green_spine_fails_closed_without_native_map_and_translates(session):
    app,studio,layout=session
    layout.set_mode("game")
    app.processEvents()
    hud=layout.game_hud
    assert not hud.spine_inspect.isEnabled()
    assert not hud.inspect.isEnabled()
    assert hud.spine_radar.isEnabled()
    assert hud.context_stack.currentIndex()==0
    hud.context_toggle.click()
    app.processEvents()
    assert hud.context_stack.currentIndex()==1
    assert not hud.spine_inspect.isEnabled()
    hud.spine_radar.click()
    app.processEvents()
    assert hud.context_stack.currentIndex()==0
    studio.set_ui_language("en")
    app.processEvents()
    assert hud.spine_radar.accessibleName()=="Show live minimap"
    assert hud.spine_inspect.accessibleName()=="Open original map inspector"
    assert "no economy simulation" in hud.radar_title.toolTip()
    studio.set_ui_language("de")
    app.processEvents()
    assert hud.spine_radar.accessibleName()=="Echte Minikarte anzeigen"



def test_cached_runtime_image_is_only_available_for_a_real_engine_hit(
    real_map_session
):
    """Never use screenshot portraits or infer a raw map type -> sprite."""
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest
    from sandbox_gameplay_artwork import selection_artwork

    app,studio,layout=real_map_session
    canvas=studio.native_canvas
    hud=layout.game_hud
    renderer=canvas.runtime_renderer
    assert renderer is not None
    assert len(renderer.images)>50
    assert not hud.spine_art.isEnabled()
    hit=None
    for fx,fy in ((.25,.35),(.55,.55),(.67,.62),(.36,.43)):
        p=QPoint(round(canvas.viewport().width()*fx),
                 round(canvas.viewport().height()*fy))
        pos=canvas.mapToScene(p)
        candidate=renderer.pick_graphic(pos.x(),pos.y())
        if candidate is None:
            continue
        ref=candidate.ref
        key=(ref.group,ref.frame,ref.light,ref.float_colour)
        if renderer.images.get(key) is not None:
            hit=candidate
            break
    assert hit is not None, "Visible engine image must be cached"
    canvas.scene().clearSelection()
    canvas.last_engine_pick=hit
    canvas.engine_sprite_picked.emit(hit)
    app.processEvents()
    assert hud.context_title.text()=="Engine-Snapshot-Grafik"
    assert hud.context_stack.currentIndex()==1
    art=selection_artwork(canvas,"engine")
    assert art is not None
    assert art.pixmap is renderer.images[
        (hit.ref.group,hit.ref.frame,hit.ref.light,hit.ref.float_colour)
    ][0]
    # The existing asset-preview side panel can invalidate the renderer
    # once before the next Qt repaint. The UI must resolve that race itself.
    QTest.qWait(110)
    app.processEvents()
    assert hud.spine_art.isEnabled()
    assert art.identity in hud.spine_art.toolTip()
    hud.spine_art.click()
    app.processEvents()
    assert hud.context_stack.currentIndex()==2
    assert hud.radar_title.text()=="Gerenderte Grafik"
    assert not hud.art_thumbnail.pixmap().isNull()
    assert art.identity==hud.art_source.text()
    assert "Renderer-Frame" in hud.art_source.toolTip()

    # This is still the same live map and minimap, not a second asset view.
    assert canvas is studio.tabs.widget(3)
    assert studio.native_minimap.map_canvas is canvas
    studio.set_ui_language("en")
    app.processEvents()
    assert hud.context_stack.currentIndex()==2
    assert "Rendered graphic"==hud.radar_title.text()
    assert "local work/catalog art" in hud.art_source.toolTip()
    studio.set_ui_language("de")
    app.processEvents()

    # A raw original section-1013 building has NO verified type->sprite.
    marker=next((item for item in canvas.scene().items()
                 if item.data(0) is not None),None)
    assert marker is not None
    marker.setSelected(True)
    app.processEvents()
    assert hud.context_title.text()=="Originalbauwerk"
    assert hud.context_stack.currentIndex()==1
    assert not hud.spine_art.isEnabled()
    assert hud.art_thumbnail.pixmap().isNull()
    assert "Spritezuordnung" in hud.spine_art.toolTip()
    marker.setSelected(False)
    # The manual M click follows an already queued deselection event.
    # The older event must not overwrite the explicit radar request.
    hud.spine_radar.click()
    app.processEvents()
    assert hud.context_stack.currentIndex()==0
    assert studio.native_minimap.isVisible()


def test_working_overlay_visual_uses_loaded_scene_sprite_only(
    real_map_session
):
    from sandbox_gameplay_artwork import selection_artwork

    app,studio,layout=real_map_session
    canvas=studio.native_canvas
    hud=layout.game_hud
    initial=canvas.history.overlay.serialize()
    x,y=canvas._keyboard_anchor()
    assert canvas.is_editable_native(x,y)
    ident=canvas.history.place("tree_pine",20,x,y)
    canvas.last_engine_pick=None
    canvas.rebuild(focus=ident)
    app.processEvents()
    item=canvas._items[ident]
    assert item.source_loaded
    art=selection_artwork(canvas,"overlay")
    assert art is not None
    # PySide wraps the same native QPixmap in a new Python object each time.
    assert art.pixmap.cacheKey()==item.pixmap().cacheKey()
    assert "KEIN Originalspiel" in art.source
    assert hud.spine_art.isEnabled()
    hud.spine_art.click()
    app.processEvents()
    assert hud.context_stack.currentIndex()==2
    assert hud.art_source.text()=="tree_pine/20"
    assert not hud.art_thumbnail.pixmap().isNull()

    # An undo removes the selected item: no ghost image or stale source.
    hud.undo.click()
    app.processEvents()
    assert canvas.history.overlay.serialize()==initial
    assert not hud.spine_art.isEnabled()
    assert hud.art_thumbnail.pixmap().isNull()
    assert hud.context_stack.currentIndex()==0



def test_gameplay_uses_real_unmodified_source_pixels_not_european_crop(
    real_map_session, monkeypatch
):
    """Game mode and experimental Europe Editor share a map but NOT icon art."""
    from PySide6.QtCore import QSize
    app,studio,layout=real_map_session
    hud=layout.game_hud
    if hud.native_icons is None:
        pytest.skip("Private original SHCDE UI reference not present")
    assert "Gepinnte Original-Crusader-UI-Pixel" in hud.category.toolTip()
    assert hud.command_widget.original_background_loaded
    assert hud.command_widget.original_backplate.size()==hud.native_icons.crop("UI-HUD 007").size()
    assert "Qt-Testfunktionen" in hud.command_widget.toolTip()
    sample=next((b,s) for b,s in hud._visible_buttons
                if s["image"].startswith("UI-Buildings"))
    button,spec=sample
    src=hud.native_icons.crop(spec["image"])
    assert button.icon().isNull() is False
    assert "ORIGINAL-SHCDE-Pixel" in button.toolTip()
    actual=button.icon().pixmap(src.size())
    assert actual.toImage()==src.toImage()  # full RGBA pixels, not just names
    old_europe=studio.original_hud.art.crop(spec["image"])
    # Two sources intentionally differ: don't replace the editor's
    # independently authored/derived European work art.
    assert old_europe.toImage()!=src.toImage()

    hud.category.setCurrentIndex(1)
    app.processEvents()
    assert any("ORIGINAL-SHCDE-Pixel" in b.toolTip()
               for b,_ in hud._visible_buttons)
    assert studio.tabs.widget(3) is studio.native_canvas


def test_missing_original_icon_cache_is_explicitly_unverified(session):
    from PySide6.QtCore import Qt
    app,studio,layout=session
    hud=layout.game_hud
    candidates=[(b,s) for b,s in hud._visible_buttons if s["image"]]
    if candidates:
        button,spec=candidates[0]
    else:
        # No private XAML graphics in an ordinary checkout: probe the exact
        # fail-closed icon renderer with a synthetic UI-only command.
        from PySide6.QtWidgets import QToolButton
        button=QToolButton(hud)
        spec={"name":"ButtonBuildQA", "command":"QA_NOT_DISPATCHED",
              "image":"UI-Buildings A001"}
    saved=hud.native_icons
    try:
        hud.native_icons=None
        hud._set_button_spec(button,spec)
        assert "KEINE ORIGINAL-PIXEL" in button.toolTip()
        assert "nicht angezeigt" in button.toolTip()
        assert button.icon().isNull()
        assert button.toolButtonStyle()==Qt.ToolButtonStyle.ToolButtonTextOnly
    finally:
        hud.native_icons=saved
        hud._set_button_spec(button,spec)



@pytest.mark.parametrize("width,height",[(1168,542),(784,342)])
def test_verified_scribe_reference_is_manual_and_never_changes_game(
    real_map_session,width,height
):
    """Actual original Scribe pixels, but no fake adviser/skin animation."""
    from sandbox_scribe_reference import FAMILIES
    app,studio,layout=real_map_session
    studio.resize(width,height)
    app.processEvents()
    layout.refresh_size()
    app.processEvents()
    hud=layout.game_hud
    if hud.scribe_reference is None:
        pytest.skip("Private original Scribe resource cache not present")
    canvas=studio.native_canvas
    initial_history=canvas.history
    original_state=initial_history.overlay.serialize()
    current_map=canvas._map_path
    assert layout.game_mode
    assert hud.scribe_button.isVisible() and hud.scribe_button.isEnabled()
    assert hud.scribe_button.width()==21
    assert hud.scribe_button.toolTip()
    assert hud.scribe_button.accessibleName()

    hud.scribe_button.click()
    app.processEvents()
    assert hud.context_stack.currentIndex()==3
    assert hud.radar_title.text()=="Schreiber-Referenz"
    assert hud.scribe_source.text()=="B001/45"
    assert not hud.scribe_previous.isEnabled()
    assert hud.scribe_next.isEnabled()
    assert not hud.scribe_picture.pixmap().isNull()
    assert "MANUELLE Referenz" in hud.scribe_picture.toolTip()
    assert "Abspielzeit" in hud.scribe_picture.toolTip()
    start_key=hud.scribe_picture.pixmap().cacheKey()
    hud.scribe_next.click()
    app.processEvents()
    assert hud.scribe_source.text()=="B002/45"
    assert hud.scribe_picture.pixmap().cacheKey()!=start_key
    hud.scribe_family.setCurrentIndex(1)
    app.processEvents()
    assert hud.scribe_family.currentData()=="C"
    assert hud.scribe_source.text()=="C001/44"
    assert "KEIN Skinwechsel" in hud.scribe_family.toolTip()
    hud.scribe_previous.click()  # already disabled: no implicit wrap
    app.processEvents()
    assert hud.scribe_source.text()=="C001/44"
    # The same picture remains for every idle Qt event, no animation clock.
    frame=hud.scribe_source.text()
    for _ in range(4):
        app.processEvents()
    assert hud.scribe_source.text()==frame
    hud._scribe_frame=FAMILIES["C"]
    hud.refresh_scribe()
    assert hud.scribe_source.text()=="C044/44"
    assert not hud.scribe_next.isEnabled()
    studio.set_ui_language("en")
    app.processEvents()
    assert hud.context_stack.currentIndex()==3
    assert hud.radar_title.text()=="Scribe reference"
    assert "MANUAL reference" in hud.scribe_picture.toolTip()
    studio.set_ui_language("de")
    app.processEvents()
    hud.scribe_family.setCurrentIndex(0)
    hud._scribe_frame=45
    hud.refresh_scribe()
    assert hud.scribe_source.text()=="B045/45"
    assert "Sonderformat 178×164" in hud.scribe_picture.toolTip()
    assert "KEIN nachgewiesenes Animationsende" in hud.scribe_picture.toolTip()
    assert not hud.scribe_next.isEnabled()
    hud.spine_radar.click()
    app.processEvents()
    assert hud.context_stack.currentIndex()==0
    assert studio.native_minimap.isVisible()
    assert canvas.history is initial_history
    assert canvas.history.overlay.serialize()==original_state
    assert canvas._map_path==current_map
    assert canvas._placing is None


def test_scribe_reference_button_missing_original_source_fail_closed(session):
    app,studio,layout=session
    hud=layout.game_hud
    old=hud.scribe_reference
    try:
        hud.scribe_reference=None
        hud.refresh_scribe()
        assert not hud.scribe_button.isEnabled()
        assert hud.scribe_picture.pixmap().isNull()
        assert "Keine Originalquelle" in hud.scribe_source.text()
        hud._manual_context_page(3)
        app.processEvents()
        assert hud.context_stack.currentIndex()==0
    finally:
        hud.scribe_reference=old
        hud.refresh_scribe()



def test_live_game_team_selector_is_wired_to_saved_overlay_and_expert_hud(
    real_map_session
):
    """Original team's eight choices must reach the same native map record."""
    import hashlib
    from sandkasten import TEAM_COLOURS

    app,studio,layout=real_map_session
    hud=layout.game_hud
    canvas=studio.native_canvas
    assert layout.game_mode and canvas.has_map()
    assert set(TEAM_COLOURS)=={
        hud.team_choice.itemData(i) for i in range(hud.team_choice.count())
    }
    assert set(TEAM_COLOURS)=={
        studio.native_hud.team.itemData(i)
        for i in range(studio.native_hud.team.count())
    }
    src=Path(studio._current)
    original_digest=hashlib.sha256(src.read_bytes()).hexdigest()
    before=canvas.history.overlay.serialize()
    hid=studio.native_hud
    hid.group.setCurrentText("tree_pine")
    hid.frame.setValue(20)
    color_index=hud.team_choice.findData("tuerkis")
    assert color_index>=0
    hud.team_choice.setCurrentIndex(color_index)
    app.processEvents()
    assert hid.team.currentData()=="tuerkis"
    assert canvas._placement_team=="tuerkis"

    # A real user presses the actual Game HUD placement button.
    hud.place.click()
    app.processEvents()
    assert canvas._placing==("tree_pine",20)
    x,y=canvas._keyboard_anchor()
    assert canvas.is_editable_native(x,y)
    ident=canvas._place_native(x,y)
    app.processEvents()
    obj=next(o for o in canvas.history.overlay.objects if o.id==ident)
    assert (obj.group,obj.frame,obj.team)==("tree_pine",20,"tuerkis")
    assert hud.team_choice.currentData()=="tuerkis"

    hud.undo.click()
    app.processEvents()
    assert canvas.history.overlay.serialize()==before
    assert not hud.save.isEnabled()
    canvas.cancel_placement()

    # The functional expert mode preserves the same team for further edits.
    layout.set_mode("editor")
    app.processEvents()
    assert hid.team.currentData()=="tuerkis"
    hid.team.setCurrentIndex(hid.team.findData("orange"))
    assert canvas._placement_team=="orange"
    layout.set_mode("game")
    app.processEvents()
    assert hud.team_choice.currentData()=="orange"
    assert hashlib.sha256(src.read_bytes()).hexdigest()==original_digest


def test_native_arm_placement_rejects_untrusted_ids_and_frames(
    real_map_session
):
    canvas=real_map_session[1].native_canvas
    before=canvas.history.overlay.serialize()
    assert canvas._placing is None
    for group,frame in (
        ("../escape",2),("",2),("tree_pine",True),
        ("tree_pine",-1),("tree_pine",1000000),
        ("escape/bad",4),
    ):
        assert canvas.arm_placement(group,frame) is False
        assert canvas._placing is None
    assert canvas.history.overlay.serialize()==before
    assert canvas.arm_placement("body_archer",2,team="not-real") is False
    assert canvas._placing is None
    assert canvas.arm_placement("body_archer",2,team="grau") is True
    assert canvas._placement_team=="grau"
    canvas.cancel_placement()

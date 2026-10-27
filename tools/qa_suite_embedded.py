"""Acceptance test: real Sandbox Studio *inside* the normal Sprite Suite window.

Run on a Windows desktop with:
    .venv\\Scripts\\python.exe tools\\qa_suite_embedded.py

No original .map or game asset is written. The only generated file is a
diagnostic window capture in work/ (not distributed with the application).
"""
from __future__ import annotations

import ctypes
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import sys
import time
import traceback

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/"tools"),str(ROOT/"src")]
if os.name!="nt":
    raise SystemExit("Nur Windows unterstützt native Tk/Qt-Einbettung")
# The child HWND needs the real Win32 QPA; an offscreen Qt simulation cannot
# verify true native containment or focus/resize behavior.
if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
    os.environ.pop("QT_QPA_PLATFORM")
loader=importlib.machinery.SourceFileLoader(
    "suite_universal_embedded_qa",str(ROOT/"tools"/"suite_universal.pyw")
)
spec=importlib.util.spec_from_loader(loader.name,loader)
suite=importlib.util.module_from_spec(spec)
loader.exec_module(suite)


def main():
    # This integration script checks several canonical German report strings.
    # The separate command-search/locale QA covers English. Never inherit
    # whatever language the previous QA left in the user's saved settings,
    # and never change that saved preference while running this test.
    suite.LANG.code="de"
    suite.LANG.save=lambda:None
    os.environ["SEDE_SPRACHE"]="de"
    win=suite.Universal()
    win.geometry("1500x930+55+55")
    # Acceptance machine may have original game maps in the QA fixture
    # directory. The *normal app* never uses this developer-only path.
    fixture = Path("E:/SSGameQA")
    if (fixture/"Stronghold Crusader Definitive Edition_Data"/
            "StreamingAssets"/"Maps").is_dir():
        win.sandbox_tab._game_root = lambda: fixture
    failed=[]
    def start():
        print("MAIN_SUITE_STARTED",flush=True)
        win.open_sandbox_studio()
        tab=win.sandbox_tab
        print("SANDBOX_INITIAL_OPEN_STATE",
              "selected",win.notebook.select()==str(tab),
              "tab_mapped",tab.winfo_ismapped(),
              "host_mapped",tab.host.winfo_ismapped(),
              "starting",tab._starting,
              "bridge",tab.bridge is not None,
              "status",tab.message.get(),flush=True)

    def verify():
        try:
            tab=win.sandbox_tab
            bridge=tab.bridge
            if bridge is None:
                print("SANDBOX_START_FAILURE_DIAGNOSTIC",
                      "selected",win.notebook.select()==str(tab),
                      "tab_mapped",tab.winfo_ismapped(),
                      "host_mapped",tab.host.winfo_ismapped(),
                      "starting",tab._starting,
                      "status",tab.message.get(),flush=True)
                raise AssertionError(tab.message.get())
            from PySide6.QtCore import Qt
            studio=bridge.window
            assert bridge.is_embedded()
            assert win.notebook.select()==str(tab)
            assert bridge.host_hwnd == int(tab.host.winfo_id())
            # This is not a separate Qt top-level GUI window; its *native*
            # OS parent is the Tk frame belonging to the existing notebook.
            user=ctypes.WinDLL("user32")
            user.GetParent.argtypes=[ctypes.c_void_p]
            user.GetParent.restype=ctypes.c_void_p
            user.IsWindowVisible.argtypes=[ctypes.c_void_p]
            user.IsWindowVisible.restype=ctypes.c_int
            assert int(user.GetParent(bridge.native_hwnd) or 0)==bridge.host_hwnd
            assert user.IsWindowVisible(bridge.native_hwnd)
            class WinRect(ctypes.Structure):
                _fields_=[('left',ctypes.c_long),('top',ctypes.c_long),
                          ('right',ctypes.c_long),('bottom',ctypes.c_long)]
            user.GetClientRect.argtypes=[ctypes.c_void_p,ctypes.POINTER(WinRect)]
            user.GetClientRect.restype=ctypes.c_int
            def child_size(hwnd):
                rect=WinRect()
                assert user.GetClientRect(hwnd,ctypes.byref(rect))
                return rect.right-rect.left,rect.bottom-rect.top
            assert child_size(bridge.native_hwnd)==child_size(bridge.host_hwnd)
            workspace=bridge.workspace
            # A real map now starts in the integrated game view. Verify it
            # before returning to the traditional editor QA workflow.
            assert workspace.game_mode == studio.native_canvas.has_map()
            if workspace.game_mode:
                assert workspace.game_hud.isVisible()
                assert studio.tabs.widget(3) is studio.native_canvas
                assert studio.native_minimap.parentWidget() is workspace.game_hud.radar_page
                assert not workspace.right_open
                print("INTEGRATED_GAME_MODE_REUSED_NATIVE_CANVAS", flush=True)
                # Whole-Sandbox routing: F2 / test board and F1 / radar
                # must restore the editor's real tabs and never leave the
                # overlaid game HUD obscuring a different working surface.
                studio.show_test_field()
                bridge._qt_app.processEvents()
                assert not workspace.game_mode
                assert studio.tabs.currentIndex()==1
                assert studio.tabs.tabBar().isVisible()
                assert not workspace.game_hud.isVisible()
                workspace.set_mode("game")
                bridge._qt_app.processEvents()
                studio.tabs.setCurrentIndex(0)
                bridge._qt_app.processEvents()
                assert not workspace.game_mode
                assert studio.tabs.currentIndex()==0
                assert studio.tabs.tabBar().isVisible()
                workspace.set_mode("game")
                bridge._qt_app.processEvents()
                assert workspace.game_mode and studio.tabs.currentIndex()==3
                print("NATIVE_CROSS_VIEW_GAME_EDITOR_ROUTING_PASS",flush=True)
                workspace.set_mode("editor")
                bridge._qt_app.processEvents()
            assert not workspace.left_open
            assert workspace.right_open
            assert not workspace.focused
            assert studio.tabs.width() >= studio.width() * .60, (
                studio.tabs.width(), studio.width()
            )
            from PySide6.QtWidgets import QToolBar
            bar=studio.findChildren(QToolBar)[0]
            assert bar.width() <= studio.width()
            assert workspace.tool_picker.count() >= 7
            for dock in (studio._hud_dock,studio._animation_dock,
                         getattr(studio, "_original_hud_dock", None)):
                if dock is None:
                    continue
                assert studio.dockWidgetArea(dock)==Qt.DockWidgetArea.RightDockWidgetArea
                assert dock in workspace._right_docks
            tab.show_animation()
            win.update()
            assert studio.tabs.currentIndex()==1
            assert workspace._selected_right is studio._animation_dock
            assert studio._animation_dock.isVisible()
            tab.show_game_hud()
            win.update()
            assert studio.tabs.currentIndex()==3
            assert workspace._selected_right is studio._hud_dock
            assert studio._hud_dock.isVisible()
            print("ANIMATION_AND_HUD_REACHABLE",flush=True)
            workspace.show_tool(studio._native_dock)
            win.update()
            for viewport in ((1500,930),(1320,800),(1020,680)):
                win.geometry(f"{viewport[0]}x{viewport[1]}+55+55")
                win.update()
                bridge._qt_app.processEvents()
                bridge.resize()
                bridge._qt_app.processEvents()
                workspace.refresh_size()
                bridge._qt_app.processEvents()
                for control in (*tab.quick_buttons.values(),tab.more_button):
                    assert control.winfo_ismapped()
                    assert control.winfo_rootx()+control.winfo_width() <= (
                        tab.winfo_rootx()+tab.winfo_width()+2
                    ), (viewport,control.cget("text"))
                print("SANDBOX_GEOMETRY_DEBUG",viewport,
                      "host",(tab.host.winfo_width(),tab.host.winfo_height()),
                      "Qt",(studio.width(),studio.height()),
                      "minimumHint",(studio.minimumSizeHint().width(),
                                     studio.minimumSizeHint().height()),
                      "scene",(studio.tabs.width(),studio.tabs.height()),
                      flush=True)
                assert child_size(bridge.native_hwnd)==child_size(bridge.host_hwnd), (
                    viewport,child_size(bridge.native_hwnd),
                    child_size(bridge.host_hwnd)
                )
                assert abs(studio.width()*studio.devicePixelRatioF()
                           -child_size(bridge.native_hwnd)[0]) <= 3
                assert studio.tabs.width() >= studio.width() * .55, (
                    viewport,studio.tabs.width(),studio.width()
                )
                assert studio.tabs.height() >= studio.height() * .50, (
                    viewport,studio.tabs.height(),studio.height()
                )
                assert bar.widgetForAction(workspace.focus_action).isVisible()
                assert bar.widgetForAction(workspace.reset_action).isVisible()
                print("SANDBOX_USABLE_SCENE",viewport,
                      studio.tabs.width(),studio.tabs.height(),
                      "/",studio.width(),studio.height(),flush=True)
                detail_scroll=studio._native_inspector_scroll
                inspector=studio.native_inspector
                print("SANDBOX_INSPECTOR_GEOMETRY",viewport,
                      "dock",studio._native_dock.width(),
                      "scroll",detail_scroll.width(),
                      "content",inspector.width(),
                      "hint",inspector.minimumSizeHint().width(),
                      "horizontalOverflow",detail_scroll.horizontalScrollBar().maximum(),
                      flush=True)
                assert detail_scroll.horizontalScrollBar().maximum()==0, (
                    "Inspector darf nicht horizontal abgeschnitten sein",
                    viewport,detail_scroll.width(),
                    inspector.minimumSizeHint().width()
                )
                # WHOLE-SANDBOX surface check, not just a Gameplay HUD:
                # visit Testfeld, Radar, raw data and NativeMap inside the
                # same Tk/Win32 child at EACH practical window size.
                board_history=studio.board.history
                canvas=studio.native_canvas
                scene_before=(board_history.scene.serialize(),
                              canvas.history.overlay.serialize()
                              if canvas.history is not None else None)
                surfaces=(
                    ("testfeld",lambda:studio.show_test_field(),1),
                    ("radar",lambda:studio.tabs.setCurrentIndex(0),0),
                    ("kacheldaten",lambda:studio.show_height_section(),2),
                    ("spielkarte",lambda:studio.show_native_map(),3),
                )
                for surface,open_surface,index in surfaces:
                    assert open_surface() is not False,(surface,viewport)
                    bridge._qt_app.processEvents()
                    assert studio.tabs.currentIndex()==index,(surface,viewport)
                    assert not workspace.game_mode,(surface,viewport)
                    expected_dock=(studio.inspector_dock if surface=="testfeld"
                                   else studio._native_dock)
                    assert workspace._selected_right is expected_dock, (
                        "Wrong inspector for actual active surface",surface,viewport
                    )
                    assert expected_dock.isVisible(),(surface,viewport)
                    assert studio.tabs.tabBar().isVisible(),(surface,viewport)
                    assert not workspace.game_hud.isVisible(),(surface,viewport)
                    view=studio.tabs.currentWidget()
                    assert view.isVisible(),(surface,viewport)
                    assert view.viewport().width()>100,(surface,viewport)
                    assert view.viewport().height()>100,(surface,viewport)
                    assert view.scene().sceneRect().width()>0,(surface,viewport)
                    evidence=ROOT/"work"/"reports"/"ui-audit"
                    evidence.mkdir(parents=True,exist_ok=True)
                    assert studio.grab().save(str(
                        evidence/f"sandbox-all-surfaces-{surface}-{viewport[0]}x{viewport[1]}.png"
                    ))
                    assert board_history is studio.board.history
                    assert board_history.scene.serialize()==scene_before[0]
                    if canvas.history is not None:
                        assert canvas.history.overlay.serialize()==scene_before[1]
                print("NATIVE_FOUR_WORKSPACES_PASS",viewport,flush=True)
                # These are the controls users actually need, not merely
                # a dock widget that exists but cannot be brought forward.
                base_width=studio.tabs.width()
                tab.quick_buttons['Fokus'].invoke()
                win.update()
                bridge._qt_app.processEvents()
                assert workspace.focused
                assert all(not dock.isVisible() for dock in workspace._left_docks)
                assert all(not dock.isVisible() for dock in workspace._right_docks)
                assert studio.tabs.width() >= base_width
                tab.quick_buttons['Palette'].invoke()
                win.update()
                bridge._qt_app.processEvents()
                assert not workspace.focused and workspace.left_open
                assert workspace._selected_left.isVisible()
                assert workspace._selected_right.isVisible()
                tab.quick_buttons['Inspector'].invoke()
                win.update()
                bridge._qt_app.processEvents()
                assert not workspace.right_open
                assert all(not dock.isVisible() for dock in workspace._right_docks)
                # Selecting a tool from the visible combo reopens the panel.
                # The previous QA assumed the German label "Spiel-HUD".
                # The real Suite can be in English after the command-search
                # acceptance test. Qt itemData is the stable dock identity.
                hud_index=workspace.tool_picker.findData(studio._hud_dock)
                assert hud_index > 0, [
                    workspace.tool_picker.itemText(i)
                    for i in range(workspace.tool_picker.count())
                ]
                workspace.tool_picker.setCurrentIndex(hud_index)
                win.update()
                bridge._qt_app.processEvents()
                assert workspace.right_open
                assert workspace._selected_right is studio._hud_dock
                assert studio._hud_dock.isVisible()
                tab.quick_buttons['Layout zurück'].invoke()
                win.update()
                bridge._qt_app.processEvents()
                assert not workspace.focused
                assert not workspace.left_open and workspace.right_open
                assert workspace._selected_right is studio._native_dock
                assert studio._native_dock.isVisible()
                if studio.native_canvas.has_map():
                    # Real Win32 placement, not a synthetic offscreen widget:
                    # the map fills the central host beneath the HUD.
                    workspace.set_mode("game")
                    bridge._qt_app.processEvents()
                    workspace.refresh_size()
                    bridge._qt_app.processEvents()
                    hud=workspace.game_hud
                    from sandbox_hud_chrome_geometry import (
                        spine_width, chrome_alignment_error
                    )
                    assert hud.isVisible() and studio.native_minimap.isVisible()
                    assert hud.spine.width()==spine_width(hud.width())
                    assert abs(chrome_alignment_error(
                        hud.width(), hud.spine.x()
                    ))<.055
                    assert hud.radar_page.objectName()=="sandbox_gameplay_radar_frame"
                    assert all(button.isVisible() and button.accessibleName()
                               for button in (
                                   hud.spine_radar, hud.context_toggle,
                                   hud.spine_inspect
                               ))
                    assert studio.tabs.height()>=workspace.game_host.height()-2
                    assert hud.x()+hud.width()==workspace.game_host.width()
                    assert hud.y()+hud.height()==workspace.game_host.height()
                    assert studio.native_canvas.height()>hud.height()
                    if viewport[0] == 1500:
                        assert hud.x()>workspace.game_host.width()*.40
                    else:
                        assert hud.x()==0  # small-screen fallback, not parity
                    evidence=ROOT/"work"/"reports"/"ui-audit"
                    evidence.mkdir(parents=True,exist_ok=True)
                    assert studio.grab().save(str(
                        evidence/f"suite-embedded-gameplay-{viewport[0]}x{viewport[1]}.png"
                    ))
                    print("GAMEPLAY_NATIVE_LAYOUT_PASS",viewport,
                          hud.geometry().getRect(),flush=True)
                    if viewport[0] == 1500:
                        # The new original-pixel source is optional for
                        # installed clients, but this QA machine has a
                        # separate, SHA-pinned cache extracted from its game.
                        if hud.native_icons is not None:
                            from PySide6.QtGui import QPixmap
                            assert hud.command_widget.original_background_loaded
                            assert "Gepinnte Original-Crusader-UI-Pixel" in hud.category.toolTip()
                            icon,spec=next(
                                (b,s) for b,s in hud._visible_buttons
                                if s["image"].startswith("UI-Buildings")
                            )
                            source_pix=hud.native_icons.crop(spec["image"])
                            assert icon.icon().pixmap(source_pix.size()).toImage()==source_pix.toImage()
                            assert "ORIGINAL-SHCDE-Pixel" in icon.toolTip()
                            assert studio.grab().save(str(
                                evidence/"suite-embedded-original-ui-crops-1500x930.png"
                            ))
                            print("NATIVE_SHA_PINNED_ORIGINAL_UI_ICONS_PASS",flush=True)
                        building=next((
                            item for item in studio.native_canvas.scene().items()
                            if item.data(0) is not None
                        ),None)
                        assert building is not None
                        actual=building.data(0)
                        building.setSelected(True)
                        bridge._qt_app.processEvents()
                        assert hud.context_stack.currentIndex()==1
                        assert hud.context_title.text()=="Originalbauwerk"
                        assert str(actual.type_id) in hud.context_brief.text()
                        assert "nur lesen" in hud.context_title.toolTip()
                        assert studio.native_canvas.has_map()
                        assert studio.grab().save(str(
                            evidence/"suite-embedded-gameplay-selection-1500x930.png"
                        ))
                        hud.spine_radar.click()
                        bridge._qt_app.processEvents()
                        assert hud.context_stack.currentIndex()==0
                        assert studio.native_minimap.isVisible()
                        hud.context_toggle.click()
                        bridge._qt_app.processEvents()
                        assert hud.context_stack.currentIndex()==1
                        hud.spine_inspect.click()
                        bridge._qt_app.processEvents()
                        assert not workspace.game_mode
                        assert workspace._selected_right is studio._native_dock
                        building.setSelected(False)
                        print("NATIVE_ORIGINAL_SELECTION_READONLY_PASS",flush=True)
                        print("NATIVE_GREEN_SPINE_ACTIONS_PASS",flush=True)
                        # Reenter the same game map and inspect one actually
                        # rendered, already-cached EngineSpriteHit. No
                        # Unity/atlas loader is invoked by the HUD preview.
                        workspace.set_mode("game")
                        bridge._qt_app.processEvents()
                        from PySide6.QtCore import QPoint
                        from PySide6.QtTest import QTest
                        canvas=studio.native_canvas
                        renderer=canvas.runtime_renderer
                        assert renderer is not None
                        hit=None
                        for fx,fy in ((.25,.35),(.55,.55),(.67,.62),(.36,.43)):
                            point=QPoint(
                                round(canvas.viewport().width()*fx),
                                round(canvas.viewport().height()*fy),
                            )
                            scene=canvas.mapToScene(point)
                            candidate=renderer.pick_graphic(scene.x(),scene.y())
                            if candidate is None:
                                continue
                            ref=candidate.ref
                            key=(ref.group,ref.frame,ref.light,ref.float_colour)
                            if renderer.images.get(key) is not None:
                                hit=candidate
                                break
                        assert hit is not None
                        canvas.last_engine_pick=hit
                        canvas.engine_sprite_picked.emit(hit)
                        bridge._qt_app.processEvents()
                        QTest.qWait(110)
                        bridge._qt_app.processEvents()
                        assert hud.context_title.text()=="Engine-Snapshot-Grafik"
                        assert hud.spine_art.isEnabled()
                        hud.spine_art.click()
                        bridge._qt_app.processEvents()
                        assert hud.context_stack.currentIndex()==2
                        assert not hud.art_thumbnail.pixmap().isNull()
                        assert f"{hit.ref.group}/{hit.ref.frame}"==hud.art_source.text()
                        assert "Renderer-Frame" in hud.art_source.toolTip()
                        assert studio.grab().save(str(
                            evidence/"suite-embedded-cached-artwork-1500x930.png"
                        ))
                        hud.spine_radar.click()
                        bridge._qt_app.processEvents()
                        assert studio.native_minimap.isVisible()
                        print("NATIVE_CACHED_ARTWORK_HUD_PASS",flush=True)
                        # Manual Scribe inspection never reads/modifies
                        # ConfigSettings.Settings_Scribe or drives game Binks.
                        if hud.scribe_reference is not None:
                            original_history=canvas.history
                            overlay_before=canvas.history.overlay.serialize()
                            hud.scribe_button.click()
                            bridge._qt_app.processEvents()
                            assert hud.context_stack.currentIndex()==3
                            assert hud.scribe_source.text()=="B001/45"
                            assert "MANUELLE" in hud.scribe_picture.toolTip()
                            assert hud.scribe_picture.pixmap() is not None
                            assert studio.grab().save(str(
                                evidence/"suite-embedded-manual-scribe-1500x930.png"
                            ))
                            hud.scribe_next.click()
                            bridge._qt_app.processEvents()
                            assert hud.scribe_source.text()=="B002/45"
                            hud.scribe_family.setCurrentIndex(1)
                            bridge._qt_app.processEvents()
                            assert hud.scribe_source.text()=="C001/44"
                            assert studio.grab().save(str(
                                evidence/"suite-embedded-manual-scribe-C-1500x930.png"
                            ))
                            hud.scribe_family.setCurrentIndex(0)
                            hud._scribe_frame=45
                            hud.refresh_scribe()
                            assert "Sonderformat 178×164" in hud.scribe_picture.toolTip()
                            hud.spine_radar.click()
                            bridge._qt_app.processEvents()
                            assert hud.context_stack.currentIndex()==0
                            assert studio.native_minimap.isVisible()
                            assert canvas.history is original_history
                            assert canvas.history.overlay.serialize()==overlay_before
                            print("NATIVE_MANUAL_SCRIBE_REFERENCE_PASS",flush=True)
                        else:
                            assert not hud.scribe_button.isEnabled()
                            print("NATIVE_SCRIBE_SOURCE_UNAVAILABLE_TEXT_ONLY",flush=True)
                    workspace.set_mode("editor")
                    bridge._qt_app.processEvents()
            win.geometry("1500x930+55+55")
            win.update()
            bridge._qt_app.processEvents()
            print("SANDBOX_FOCUS_PALETTE_TOOL_PICKER_AND_RESET_PASS",flush=True)
            if studio._current is not None:
                assert studio.native_canvas.has_map()
            print("CHILD_WINDOW_OK",bridge.native_hwnd,bridge.host_hwnd,
                  "size",studio.width(),studio.height(),"map",
                  studio._current.name if studio._current else "no local map",flush=True)
            bridge.select_sprite("tree_pine",20)
            assert studio.asset_preview.group.currentText()=="tree_pine"
            assert studio.asset_preview.frame.value()==20
            assert studio.native_canvas._placing==("tree_pine",20) if studio.native_canvas.has_map() else (
                studio.board._placing==("tree_pine",20)
            )
            print("ASSET_CATALOG_BRIDGE_OK",flush=True)
            work=ROOT/"work"
            work.mkdir(exist_ok=True)
            # Capture the game-view HUD under the actual Win32 Tk parent,
            # not only an offscreen standalone Qt editor.
            if studio.native_canvas.has_map():
                workspace.set_mode("game")
                bridge._qt_app.processEvents()
                # The SAME catalogue selection in game mode must not
                # reopen the expert dock and hide the integrated game HUD.
                bridge.select_sprite("tree_pine",20)
                bridge._qt_app.processEvents()
                assert workspace.game_mode
                assert studio.tabs.currentIndex()==3
                assert workspace.game_hud.isVisible()
                assert not workspace.right_open
                assert studio.native_canvas._placing==("tree_pine",20)
                print("NATIVE_CATALOGUE_PRESERVES_GAME_VIEW_PASS",flush=True)
                workspace.refresh_size()
                bridge._qt_app.processEvents()
                # The Suite catalogue can arm a sprite directly, bypassing
                # the hidden functional HUD. A subsequent HUD placement must
                # use exactly that chosen group/frame, never an old default.
                assert workspace.game_hud.place.text()=="Abbrechen"
                assert studio.native_hud.group.currentText()=="tree_pine"
                assert studio.native_hud.frame.value()==20
                assert "tree_pine/20" in workspace.game_hud.place.toolTip()
                assert not workspace.game_hud.save.isEnabled()
                print("CATALOGUE_GAME_HUD_PLACEMENT_SYNC_PASS",flush=True)
                assert studio.native_canvas.height() >= 100
                assert studio.native_minimap.isVisible()
                assert studio.tabs.widget(3) is studio.native_canvas
                evidence=work/"reports"/"ui-audit"
                evidence.mkdir(parents=True,exist_ok=True)
                assert studio.grab().save(str(evidence/"suite-embedded-gameplay-1500x930.png"))
                workspace.set_mode("editor")
                bridge._qt_app.processEvents()
            assert studio.grab().save(str(work/"suite_embedded_sandbox_qa.png"))
            tab.show_in_catalog()
            win.update()  # dispatch <<NotebookTabChanged>>, not only idle geometry
            assert win.notebook.select()==str(win.catalog_tab)
            assert win.catalog_tab.group=="tree_pine"
            assert win.console.master.winfo_manager()==""
            win.log("SYNTHETIC_GLOBAL_LOG_PERSISTENCE", "muted")
            win.console_toggle.invoke()
            win.update()
            assert win.console.master.winfo_manager()=="pack"
            assert "SYNTHETIC_GLOBAL_LOG_PERSISTENCE" in win.console.get("1.0","end")
            assert not user.IsWindowVisible(bridge.native_hwnd)
            # This invokes the *real* Asset Catalogue button implementation,
            # rather than bypassing it with a direct Qt operation.
            win.catalog_tab.to_sandbox()
            win.update()
            assert win.notebook.select()==str(tab)
            assert bridge.is_embedded()
            assert user.IsWindowVisible(bridge.native_hwnd)
            assert bridge.window.native_canvas._placing==("tree_pine",20)
            assert win.console.master.winfo_manager()=="pack"
            assert "SYNTHETIC_GLOBAL_LOG_PERSISTENCE" in win.console.get("1.0","end")
            win.console_toggle.invoke()
            win.update()
            assert win.console.master.winfo_manager()==""
            print("GLOBAL_WORKSPACE_LOG_PERSISTENCE_PASS",flush=True)
            print("CATALOG_TO_STUDIO_TO_CATALOG_OK",flush=True)
            print("TK_TABS_AND_QT_HUDS_OK",flush=True)
            # Exercise both new tools from the *real*, running Sprite Suite.
            # The measurement is synthetic and never installed in the game.
            import json
            sample=work/"pivot-review-test-echt"/"qa-integriert.json"
            sample.parent.mkdir(parents=True,exist_ok=True)
            sample.write_text(json.dumps({
                "schema":"zinnenlineal.versatz.v1",
                "frames":[{
                    "name":"anim_castle 002","gruppe":"anim_castle","nummer":2,
                    "rechts":0,"hoch":18,"breite":333,"hoehe":165,
                    "pivot_x":0.0,"pivot_y":1.10909091,
                    "neu_pivot_x":0.0,"neu_pivot_y":1.0
                }]
            }),encoding="utf-8")
            win.notebook.select(win.exchange_tab)
            win.update()
            popup=win.exchange_tab.open_pivot_review()
            assert popup.load(sample)
            assert popup.current() is not None
            assert popup.current().status=="bereits_passend"
            assert str(popup.approve["state"])=="disabled"
            assert str(popup.export_decision["state"])=="disabled"
            assert str(popup.bc7_check["state"])=="normal"
            popup.inspect_bc7()
            deadline=time.monotonic()+15
            while popup._bc7_pending is not None and time.monotonic()<deadline:
                win.update()
                time.sleep(.04)
            assert popup._bc7_pending is None
            assert popup._bc7_results["anim_castle 002"]["status"]=="bereits_im_bc7"
            assert popup._bc7_results["anim_castle 002"]["bc7_pivot"]==[0.0,1.0]
            assert str(popup.approve["state"])=="disabled"
            print("PUBLISHED_BC7_PIVOT_MATCHES",flush=True)
            from stronghold_europe_de.pivot_measurements import save_review_report
            pivot_report=save_review_report(popup.measurement_file,popup.reviews,ROOT)
            assert pivot_report.is_file()
            popup.destroy()
            print("PIVOT_REVIEW_INTEGRATED",flush=True)
            win.notebook.select(win.diagnose_tab)
            win.update()
            assert str(win.diagnose_tab.preflight_button["state"])=="normal"
            assert str(win.diagnose_tab.pivot_stage_button["state"])=="normal"
            assert win.diagnose_tab.pivot_stage_button.winfo_ismapped()
            assert win.diagnose_tab.pivot_stage_button.winfo_width() > 75
            assert "sprite-suite-world-bc7-v2" in win.diagnose_tab.release_options["values"]
            print("RELEASE_PREFLIGHT_ACCESSIBLE",flush=True)
            print("PIVOT_BC7_STAGE_ACCESSIBLE",flush=True)
            assert str(win.diagnose_tab.rehearsal_button["state"])=="normal"
            assert win.diagnose_tab.rehearsal_button.winfo_ismapped()
            win.diagnose_tab.run_synthetic_bc7_rehearsal()
            deadline=time.monotonic()+15
            while (
                win.diagnose_tab._rehearsal_pending is not None
                and time.monotonic()<deadline
            ):
                win.update()
                time.sleep(.04)
            assert win.diagnose_tab._rehearsal_pending is None
            assert win.diagnose_tab.findings[0]["pruefung"]=="BC7-Probe"
            assert win.diagnose_tab.findings[0]["schwere"]=="info"
            print("SYNTHETIC_BC7_V2_PREPARED",flush=True)
            assert str(win.diagnose_tab.native_button["state"])=="normal"
            assert win.diagnose_tab.native_button.winfo_ismapped()
            win.diagnose_tab.inspect_native_geometry()
            deadline=time.monotonic()+45
            while (
                win.diagnose_tab._native_pending is not None
                and time.monotonic()<deadline
            ):
                win.update()
                time.sleep(.04)
            assert win.diagnose_tab._native_pending is None
            assert win.diagnose_tab.findings[0]["pruefung"]=="Nativ-Proof"
            assert win.diagnose_tab.findings[0]["schwere"]=="info"
            assert "95" in win.diagnose_tab.findings[0]["text"]
            print("PUBLISHED_NATIVE_GEOMETRY_RECONSTRUCTED",flush=True)
            native_rows=[
                (index, finding)
                for index, finding in enumerate(win.diagnose_tab.findings)
                if finding.get("pruefung") == "Nativ-Frame"
            ]
            assert len(native_rows)==106, len(native_rows)
            selected_id, selected_finding=next(
                (index, finding) for index, finding in native_rows
                if finding.get("frames")==["anim_castle 002"]
            )
            assert selected_finding["daten"]["pivot"]==[0.0,1.0]
            win.diagnose_tab.table.selection_set(str(selected_id))
            win.diagnose_tab.open_in_catalog()
            win.update()
            assert win.notebook.select()==str(win.catalog_tab)
            assert win.catalog_tab.group=="anim_castle"
            assert win.catalog_tab.selected=="anim_castle 002"
            print("NATIVE_PIVOT_FRAME_TO_CATALOG_OK",flush=True)
            assert win.quick_picker.winfo_ismapped()
            assert win.quick_section.get()=="Asset-Katalog"
            assert win.catalog_tab.apply_button.winfo_ismapped()
            assert win.catalog_tab.actions_scroll.scrollbar.winfo_ismapped()
            win.quick_section.set("Diagnose & Reparatur")
            win._quick_navigation_selected()
            win.update()
            assert win.notebook.select()==str(win.diagnose_tab)
            assert win.quick_section.get()=="Diagnose & Reparatur"
            print("FULL_SUITE_QUICK_NAV_ACCESSIBLE",flush=True)
            # Exercise actual empty states without reading/writing a user's
            # target registry or invoking any installation/build command.
            import ziel_se211
            actual_targets=ziel_se211.targets
            try:
                ziel_se211.targets=lambda:{"ziele":{},"aktiv":None}
                win.open_tab(win.target_tab)
                win.target_tab.load()
                win.update()
                assert "Noch kein Zielspiel registriert" in (
                    win.target_tab.target_status.get()
                )
                assert not win.target_tab.table.get_children()
            finally:
                ziel_se211.targets=actual_targets
            win.open_tab(win.diagnose_tab)
            win.diagnose_tab.show_release_report({
                "summary":{"state":"offline_warnings"},
                "findings":[{
                    "schwere":"warnung","pruefung":"synthetic QA only",
                    "gruppe":"-","text":"No file/build action performed",
                }],
            })
            win.update()
            assert "1 Eintrag" in win.diagnose_tab.findings_status.get()
            assert win.diagnose_tab.table.get_children()
            print("EMPTY_TARGET_AND_DIAG_STATUS_VISIBLE",flush=True)
            # Exercise the actual Tk setup handler without invoking a
            # tool or writing any local configuration/game files.
            original_setup_values=(
                win.source.get(),win.target.get(),win.unity.get(),win.dotnet.get()
            )
            original_setup_tool=win.tool
            tool_only_requests=[]
            try:
                win.open_tab(win.setup_page)
                win.source.set("")
                win.target.set("")
                win.unity.set("")
                win.dotnet.set("C:/synthetic-not-executed-sdk")
                win.tool=lambda name,args=():tool_only_requests.append(
                    (name,list(args))
                )
                win.save_config()
                assert tool_only_requests==[
                    ("suite_bridge.py",[
                        "configure","--dotnet","C:/synthetic-not-executed-sdk"
                    ])
                ]
                assert "Speicherauftrag gestartet" in (
                    win.setup_save_status.get()
                )
                print("SETUP_TOOL_ONLY_SUBMISSION_NO_DISK_WRITE",flush=True)
            finally:
                win.tool=original_setup_tool
                for var,value in zip(
                    (win.source,win.target,win.unity,win.dotnet),
                    original_setup_values
                ):
                    var.set(value)
            from tkinter import messagebox
            actual_showinfo=messagebox.showinfo
            setup_messages=[]
            try:
                messagebox.showinfo=lambda title,detail,**kw:setup_messages.append(
                    (title,detail)
                )
                win.show_setup_diagnostics()
            finally:
                messagebox.showinfo=actual_showinfo
            assert len(setup_messages)==1
            assert "nur lesend" in setup_messages[0][0].lower()
            assert "Werkzeug-Einstellungen" in setup_messages[0][1]
            print("SETUP_READ_ONLY_DIAGNOSTICS_ACCESSIBLE",flush=True)
            readiness_reports=[]
            original_present=win._present_build_readiness
            try:
                win._present_build_readiness=lambda record:readiness_reports.append(record)
                win.open_tab(win.bc7_page)
                win.bc7_profile.set("sprite-suite-world-bc7-v2")
                win.update()
                assert win.readiness_button.winfo_ismapped()
                win.check_build_readiness()
                deadline=time.monotonic()+30
                while (win._readiness_pending is not None
                       and time.monotonic()<deadline):
                    win.update()
                    time.sleep(.04)
                assert win._readiness_pending is None
                assert len(readiness_reports)==1
                readiness=readiness_reports[0]
                assert readiness["profile_id"]=="sprite-suite-world-bc7-v2"
                assert readiness["build_executed"] is False
                assert readiness["release_certified"] is False
                assert readiness["blocker_count"]>=1
                assert "Blockaden" in win.readiness_status.get()
                print("BC7_BUILD_READINESS_BLOCKERS_VISIBLE",flush=True)
                # The actual build button must use the SAME readiness gate.
                # Replacing tool makes any accidental real build fatal here.
                original_tool=win.tool
                def forbidden_build(*args,**kwargs):
                    raise AssertionError(
                        "Blocked BC7 build must not start a real CLI"
                    )
                try:
                    win.tool=forbidden_build
                    win.build_profile()
                    deadline=time.monotonic()+30
                    while (win._readiness_pending is not None
                           and time.monotonic()<deadline):
                        win.update()
                        time.sleep(.04)
                    assert win._readiness_pending is None
                    assert len(readiness_reports)==2
                    assert readiness_reports[1]["blocker_count"]>=1
                    assert "Bauversuch noch nicht möglich" in (
                        win.readiness_status.get()
                    )
                    print("BC7_BUILD_BUTTON_GATED",flush=True)
                finally:
                    win.tool=original_tool
            finally:
                win._present_build_readiness=original_present
            # Presentation-only synthetic completion: QA never invokes
            # Unity, a package builder, or an installer.
            assert win.build_result_button.winfo_ismapped()
            win._set_build_completion({
                "profile_id":"sprite-suite-world-bc7-v2",
                "state":"tool_failed",
                "detail":"Synthetic failure of the tracked CLI job",
                "exit_code":17,
                "verified_files":0,"verified_bytes":0,
                "errors":1,"warnings":0,
                "manifest_sha256":None,
                "same_manifest_as_before":None,
                "issues":["Synthetic CLI failure"],
                "offline_integrity_ok":False,
                "release_approved":False,"ingame_approved":False,
                "installation_performed":False,
            })
            assert str(win.build_result_button["state"])=="normal"
            assert "FEHLGESCHLAGEN" in win.build_result_status.get()
            assert "Ingame-Abnahme AUSSTEHEND" in win.build_result_status.get()
            print("SYNTHETIC_BUILD_COMPLETION_STATUS_VISIBLE",flush=True)
            # The actual build history view reads only local journal evidence.
            # No event may be fabricated by this QA smoke test.
            import tkinter as tk
            assert win.build_history_button.winfo_ismapped()
            win.show_build_history()
            deadline=time.monotonic()+20
            while (
                win._history_pending is not None
                and time.monotonic()<deadline
            ):
                win.update()
                time.sleep(.04)
            assert win._history_pending is None
            windows=[
                w for w in win.winfo_children()
                if isinstance(w,tk.Toplevel) and "Bauverlauf" in w.title()
            ]
            assert windows
            windows[-1].destroy()
            print("PERSISTENT_BUILD_HISTORY_VIEW_ACCESSIBLE",flush=True)
            historic=Path("E:/SS QA")
            if (historic/"tools").is_dir():
                from tkinter import filedialog
                original_ask=filedialog.askdirectory
                filedialog.askdirectory=lambda **kw:str(historic)
                try:
                    win.notebook.select(win.diagnose_tab)
                    win.update()
                    win.diagnose_tab.inventory_qa()
                finally:
                    filedialog.askdirectory=original_ask
                assert any(
                    row["gruppe"]=="ram_acceptance.py" and
                    row["pruefung"]=="Altwerkzeug"
                    for row in win.diagnose_tab.findings
                )
                print("LEGACY_QA_INVENTORY_INTEGRATED",flush=True)
            win.notebook.select(tab)
            win.update()
            assert bridge.is_embedded()
        except Exception as exc:
            traceback.print_exc()
            failed.append(str(exc))
        finally:
            win.after(120,finish)

    def finish():
        # Mimic Qt Alt+F4 / File Close. The application must not leave the
        # user stranded with a blank Tk notebook tab. The close is ignored by
        # embedded Qt and forwarded to the owning Tk Suite, which runs the
        # ordinary unsaved-change confirmation.
        bridge=win.sandbox_tab.bridge
        if bridge is None:
            failed.append("Sandbox bridge disappeared before shutdown")
            win.destroy()
            return
        if bridge.window.close():
            failed.append("Qt child closed independently of Tk Suite")
            win.destroy()
            return
        print("QT_CLOSE_REQUEST_FORWARDED_TO_SUITE",flush=True)
        def timeout():
            failed.append("Qt Close did not destroy the owning Suite")
            print("QT_CLOSE_TIMEOUT",flush=True)
            win.destroy()
        win.after(5000,timeout)

    win.after(150,start)
    win.after(10000,verify)
    win.mainloop()
    try:
        root_alive=bool(win.winfo_exists())
    except Exception:  # Tk raises TclError after its interpreter is destroyed.
        root_alive=False
    if root_alive:
        failed.append("Tk root unexpectedly survived mainloop exit")
    print("QA_PASS" if not failed else "QA_FAILED",flush=True)
    if failed:
        raise SystemExit(1)


if __name__=="__main__":
    main()

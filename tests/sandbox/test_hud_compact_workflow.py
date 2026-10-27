"""The *embedded* functional HUD must be usable at 275px, not 1100px.

The original standalone HUD remains a wide layout. Embedded mode reflows
the exact same button/signal objects into responsive native Qt form tabs.
"""
from pathlib import Path
import sys
import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication, QScrollArea
from PySide6.QtCore import Qt

ROOT=Path(__file__).resolve().parents[2]
TOOLS=str(ROOT/"tools")
if TOOLS not in sys.path:
    sys.path.insert(0,TOOLS)

from sandbox_game_hud import NativeGameHUD
from sandbox_native_canvas import NativeMapCanvas


def test_game_hud_compact_reflows_original_functional_buttons(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM","offscreen")
    app=QApplication.instance() or QApplication([])
    canvas=NativeMapCanvas()
    hud=NativeGameHUD(canvas)
    calls=[]
    monkeypatch.setattr(canvas,"arm_placement",
                        lambda group,frame,team=None:calls.append((group,frame,team)))
    try:
        original_place=hud.place
        original_mode=hud.engine_mode
        assert not hasattr(hud,"compact_tabs")
        hud.configure_compact()
        hud.configure_compact()  # idempotent; no duplicate signals
        assert hud.compact_tabs.count()==3
        assert [hud.compact_tabs.tabText(i) for i in range(3)]==[
            "Platzieren","Darstellung","Animation"
        ]
        assert hud.place is original_place
        assert hud.engine_mode is original_mode
        scroller=QScrollArea()
        scroller.setWidgetResizable(True)
        scroller.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroller.setWidget(hud)
        scroller.resize(285,320)
        scroller.show()
        app.processEvents()
        assert hud.width()<=285
        assert scroller.horizontalScrollBar().maximum()==0
        hud.group.setCurrentText("tile_castle")
        hud.frame.setValue(1193)
        hud.place.click()
        assert calls==[("tile_castle",1193,"rot")]
        hud.compact_tabs.setCurrentIndex(1)
        assert hud.engine_mode.isVisible()
        assert hud.show_buildings.isVisible()
        hud.compact_tabs.setCurrentIndex(2)
        assert hud.play.isVisible()
        assert hud.fps.isVisible()
        hud.compact_tabs.setCurrentIndex(0)
        hud.place.click()
        assert calls==[("tile_castle",1193,"rot")]*2
        scroller.close()
    finally:
        canvas._poll.stop()
        canvas.close()


def test_integrated_studio_can_switch_to_compact_game_hud(monkeypatch,tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM","offscreen")
    monkeypatch.setenv("SEDE_SPRACHE","de")
    from sandbox_studio import SandboxStudio
    from sandbox_suite_embed import EmbeddedSandboxStudio
    from types import SimpleNamespace
    app=QApplication.instance() or QApplication([])
    studio=SandboxStudio(tmp_path)
    try:
        fake=SimpleNamespace(_window=studio)
        EmbeddedSandboxStudio._compact_for_suite(fake)
        studio.resize(784,350)
        studio.show()
        app.processEvents()
        fake.workspace.show_tool(studio._hud_dock)
        app.processEvents()
        assert studio._hud_dock.isVisible()
        assert studio.native_hud.compact_tabs.count()==3
        scroll=studio._hud_dock.widget()
        assert isinstance(scroll,QScrollArea)
        assert scroll.widgetResizable()
        assert scroll.horizontalScrollBar().maximum()==0
        assert studio.tabs.width() >= 784*.55
        if hasattr(studio,"_original_hud_dock"):
            fake.workspace.show_tool(studio._original_hud_dock)
            app.processEvents()
            panel=studio.original_hud
            assert panel.display_mode.currentData()=="gallery"
            assert panel.page.count()==14
            assert panel.command_choice.count()>0
    finally:
        studio.native_canvas._poll.stop()
        studio.board._asset_poll.stop()
        studio.asset_preview.timer.stop()
        studio._saved_scene=studio.board.history.scene.serialize()
        studio.close()

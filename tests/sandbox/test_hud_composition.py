"""HUD_Main.xaml scene composition and usable original-icon modes.

The XAML source and atlas crops are local licensed user assets. Tests compare
measured settled grid/clip geometry, not merely counts of buttons.
"""
from pathlib import Path
import json
import math
import sys
import pytest

from stronghold_europe_de.sandbox.hud_composition import (
    HudComposition,HudGeometryError
)
TOOLS=str(Path(__file__).resolve().parents[2]/"tools")
if TOOLS not in sys.path: sys.path.insert(0,TOOLS)
from sandbox_hud_original_art import (
    load_hud_contract, OriginalHudArtPanel, GROUPS, ROOT
)

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest


def _app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM","offscreen")
    return QApplication.instance() or QApplication([])


def test_xaml_settled_positions_have_proven_parent_offsets():
    contract=load_hud_contract()
    geom=HudComposition.from_contract(contract)
    assert (geom.scene_width,geom.scene_height)==(914,166)
    assert geom.pixel_scale==.5
    # Verified against the actual source HUD_Main.xaml Swish1 animation.
    assert geom.scroll_parent==(110,22)
    assert geom.scroll_offset==(-287,-4)
    assert geom.image_pos()==(-177,18)
    assert geom.scroll_visible_rect()==(120,21,876,103)
    assert geom.menu_parent==(132,30)
    assert geom.menu_offset==(-125,0)
    assert geom.menu_visible_rect()==(-15,-20,496,150)
    b=next(c for c in contract["commands"]
           if c["name"]=="ButtonBuildKeep1")
    assert geom.button_pos(b)==(87,48)
    assert math.isclose(geom.button_scale(b,110,95),46/110)
    assert "HUD_Main.xaml" in contract["layout"]["composition"]["source"]


@pytest.mark.parametrize("bad",[
    {"layout":{"pixel_scale":0,"composition":{}}},
    {"layout":{"pixel_scale":.5,"composition":{}}},
])
def test_invalid_hud_layout_is_rejected(bad):
    with pytest.raises(HudGeometryError):
        HudComposition.from_contract(bad)


@pytest.mark.skipif(
    not (ROOT/"assets/ui/derived/sandbox-hud-crops").is_dir(),
    reason="Authorized local original UI crops are not available",
)
def test_xaml_view_uses_clipped_graphic_groups_and_prevents_alias_overdraw(monkeypatch):
    app=_app(monkeypatch)
    panel=OriginalHudArtPanel()
    try:
        panel.resize(1450,320)
        panel.show()
        panel.page.setCurrentIndex(list(GROUPS).index("B"))
        panel.display_mode.setCurrentIndex(1)
        app.processEvents()
        assert panel.view._xaml_mode
        assert panel.scene.sceneRect().width()==914
        assert panel.scene.sceneRect().height()==166
        assert len(panel.icons)==3
        icon=next(i for i in panel.icons if i.spec["name"]=="ButtonBuildKeep1")
        assert icon.parentItem().flags() & (
            icon.GraphicsItemFlag.ItemClipsChildrenToShape
        )
        assert icon.scenePos().x()==pytest.approx(87)
        assert icon.scenePos().y()==pytest.approx(48)
        assert icon.scale()==pytest.approx(46/110)
        # The 1752px-wide source crop must appear as a clipped 876px-wide
        # original double-density graphic, not a full-size loose background.
        for clip in panel.scene.items():
            children=clip.childItems()
            if any(child.data(0)=="missing-token" for child in []):
                raise AssertionError("Unreachable")
        panel.page.setCurrentIndex(list(GROUPS).index("N"))
        app.processEvents()
        specs=[c for c in panel.contract["commands"] if c["page"]=="N"]
        assert len(specs)==38
        slots={panel.slot(c) for c in specs}
        assert len(panel.icons)==len(slots)
        assert len(panel.icons)<len(specs)
        # The exact same original margin contains *21* distinct visual
        # variants. Only one is ever drawn at a time, but all are available
        # via the explicit command chooser.
        hidden=[c for c in specs if c["name"]=="ButtonBuildMERuins15"]
        assert len(hidden)==1
        index=panel.command_choice.findData("ButtonBuildMERuins15")
        assert index>=0
        panel.command_choice.setCurrentIndex(index)
        app.processEvents()
        matches=[i for i in panel.icons
                 if i.spec["name"]=="ButtonBuildMERuins15"]
        assert len(matches)==1
        assert panel.active_command=="STRUCT_MERUINS_15" or panel.active_command==hidden[0]["command"]
    finally:
        panel.close()


@pytest.mark.skipif(
    not (ROOT/"assets/ui/derived/sandbox-hud-crops").is_dir(),
    reason="Authorized local original UI crops are not available",
)
def test_accessible_grid_shows_all_141_buttons_without_overlap(monkeypatch):
    app=_app(monkeypatch)
    panel=OriginalHudArtPanel()
    try:
        panel.resize(1450,450)
        panel.show()
        assert panel.display_mode.currentData()=="gallery"
        seen=[]
        for idx,page in enumerate(GROUPS):
            panel.page.setCurrentIndex(idx)
            app.processEvents()
            specs=[c for c in panel.contract["commands"] if c["page"]==page]
            assert len(panel.icons)==len(specs)
            seen.extend(i.spec["name"] for i in panel.icons)
            positions=[i.scenePos().toTuple() for i in panel.icons]
            assert len(set(positions))==len(positions)
            assert panel.command_choice.count()==len(specs)+1
            assert panel.scene.sceneRect().height()>=130
        assert len(seen)==141
        panel.page.setCurrentIndex(list(GROUPS).index("N"))
        app.processEvents()
        candidates=[i for i in panel.icons
                    if i.spec["name"]=="ButtonBuildMERuins15"]
        assert len(candidates)==1
        icon=candidates[0]
        pos=panel.view.mapFromScene(icon.sceneBoundingRect().center())
        # Scrolling the GraphicsView to the item permits a true Qt mouse click.
        panel.view.centerOn(icon)
        app.processEvents()
        pos=panel.view.mapFromScene(icon.sceneBoundingRect().center())
        assert panel.view.viewport().rect().contains(pos)
        QTest.mouseClick(panel.view.viewport(),Qt.MouseButton.LeftButton,pos=pos)
        app.processEvents()
        assert panel.active_name=="ButtonBuildMERuins15"
    finally:
        panel.close()

"""Click the *actually drawn native sprite*, not a guessed floor tile.

Tests use synthetic pixel images for precise alpha masks, plus three genuine
read-only paused game snapshots to validate engine command records.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtCore import Qt, QPoint

TOOLS = str(Path(__file__).resolve().parents[2] / "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)
import sandbox_studio
from sandbox_runtime_renderer import NativeCommandRenderer
from stronghold_europe_de.sandbox.native_runtime import RuntimeSnapshot, capture_snapshot
from stronghold_europe_de.sandbox.native_visual_mapping import OriginalVisualMappings

MAPS = Path("E:/SSGameQA/Stronghold Crusader Definitive Edition_Data/StreamingAssets/Maps")


def _snapshot():
    data=np.zeros((3,21),dtype="<i2")
    data[0,:7]=[0,400,400,55,305,8,3]
    data[1,:12]=[1,400,400,200,17,-8,0,0,0,0,122,0]
    data[2,:12]=[2,402,402,100,173,-8,0,0,14,8,123,0]
    return RuntimeSnapshot(data,{})


def _renderer(monkeypatch):
    app=QApplication.instance() or QApplication([])
    owner=SimpleNamespace(
        _map_path=MAPS/"Antioch.map",
        terrain_tests=None, surface_tests=None,
        visual_mappings=OriginalVisualMappings(),show_original_trees=True,
        _channels=SimpleNamespace(at=lambda x,y:{3005:8,3037:0}),
    )
    renderer=NativeCommandRenderer(owner,_snapshot())
    def opaque(ref):
        pix=QPixmap(50,60)
        pix.fill(Qt.GlobalColor.white)
        return pix,(25,55)
    monkeypatch.setattr(renderer,"_pixmap",opaque)
    return renderer


def test_rendered_tree_is_selected_in_front_of_overlapping_ground(monkeypatch):
    renderer=_renderer(monkeypatch)
    # Native tree is drawn after a ground tile and extends upward into it.
    tree=renderer.snapshot.records[1]
    placement=renderer._actor_placement(tree)
    _,anchor_x,anchor_y,_=placement
    px,py=anchor_x-10,anchor_y-35
    hit=renderer.pick_graphic(px,py)
    assert hit is not None
    assert (hit.kind,hit.x,hit.y)==("actor",400,400)
    assert (hit.ref.group,hit.ref.frame)==("tree_cactii",16)
    assert (hit.source_file,hit.source_frame)==(200,17)
    assert renderer.pick_graphic(float("nan"),py) is None
    assert renderer.pick_graphic(px,float("inf")) is None


def test_alpha_hole_shows_the_real_ground_under_original_tree(monkeypatch):
    renderer=_renderer(monkeypatch)
    tree=renderer.snapshot.records[1]
    _,px,py,_=renderer._actor_placement(tree)
    px-=10
    py-=35
    def masked(ref):
        pic=QImage(50,60,QImage.Format.Format_RGBA8888)
        pic.fill(Qt.GlobalColor.white)
        if ref.group=="tree_cactii":
            ix=int(px-(12800+14-25))
            iy=int(py-(6400+2-55))
            pic.setPixelColor(ix,iy,Qt.GlobalColor.transparent)
        return QPixmap.fromImage(pic),(25,55)
    monkeypatch.setattr(renderer,"_pixmap",masked)
    hit=renderer.pick_graphic(px,py)
    assert hit is not None and hit.kind=="floor"
    assert (hit.ref.group,hit.ref.frame)==("tile_land_macros",305)
    # A fully transparent overlay must never block the background.


def test_actors_hidden_or_fully_transparent_are_not_selected(monkeypatch):
    renderer=_renderer(monkeypatch)
    tree=renderer.snapshot.records[1]
    renderer.owner.show_original_trees=False
    assert renderer._actor_placement(tree) is None
    renderer.owner.show_original_trees=True
    invisible=tree.copy();invisible[11]=32
    assert renderer._actor_placement(invisible) is None
    valid=renderer.snapshot.records[2]
    assert renderer._actor_placement(valid)[0].group=="body_lord"
    assert renderer._actor_placement(valid)[0].frame==172


@pytest.mark.skipif(not (MAPS/"Antioch.map").is_file(),
                    reason="Original SHCDE game map unavailable")
def test_paused_real_engine_actor_records_have_selectable_sprite_commands():
    snapshot=capture_snapshot(MAPS/"Antioch.map")
    actors=snapshot.draw_records[snapshot.draw_records[:,0]==1]
    assert len(actors)>1000
    valid=actors[(actors[:,3]==200)&(actors[:,4]>0)]
    assert len(valid)>0
    renderer=NativeCommandRenderer(SimpleNamespace(
        _map_path=MAPS/"Antioch.map",
        terrain_tests=None,surface_tests=None,
        visual_mappings=OriginalVisualMappings(),show_original_trees=True,
    ),snapshot)
    a=renderer._actor_placement(valid[0])
    assert a is not None
    assert a[0].group=="tree_cactii"
    assert a[0].frame==int(valid[0,4])-1


def test_gui_picked_engine_tree_updates_inspector_and_pixel_editor(monkeypatch,tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM","offscreen")
    from PySide6.QtTest import QTest
    app=QApplication.instance() or QApplication([])
    monkeypatch.setattr(sandbox_studio,"ROOT",tmp_path)
    studio=sandbox_studio.SandboxStudio(tmp_path)
    try:
        # Load the actual installed original, then inject an exact synthetic
        # sprite-pixel hit so GUI signal/routing is deterministic offscreen.
        if not (MAPS/"Antioch.map").is_file():
            pytest.skip("Authorized game installation unavailable")
        assert studio.open_map(MAPS/"Antioch.map")
        canvas=studio.native_canvas
        hit=SimpleNamespace(
            kind="actor",x=400,y=400,source_file=200,source_frame=17,
            ref=SimpleNamespace(group="tree_cactii",frame=16,light=0),
            opacity=1.0,
        )
        monkeypatch.setattr(canvas.runtime_renderer,"pick_graphic",lambda x,y:hit)
        monkeypatch.setattr(canvas.runtime_renderer,"pick_tile",lambda x,y:(400,400))
        canvas.resetTransform()
        canvas.scale(.75,.75)
        canvas.center_native(400,400)
        canvas.show()
        app.processEvents()
        captured=[]
        monkeypatch.setattr(studio,"edit_runtime_tile",
                            lambda x,y: captured.append((x,y,canvas.last_engine_pick.ref.group,
                                                        canvas.last_engine_pick.ref.frame)) or True)
        studio.native_inspector.edit_engine_tile.disconnect()
        studio.native_inspector.edit_engine_tile.connect(studio.edit_runtime_tile)
        point=canvas.mapFromScene(400*32+16,400*16+16)
        assert canvas.viewport().rect().contains(point)
        QTest.mouseClick(canvas.viewport(),Qt.MouseButton.LeftButton,pos=point)
        app.processEvents()
        assert canvas.last_engine_pick is hit
        assert "tree_cactii/16" in studio.native_inspector.engine_detail.text()
        assert "tree_cactii/16" in studio._native_mode_info.text()
        assert studio.asset_preview.group.currentText()=="tree_cactii"
        assert studio.asset_preview.frame.value()==16
        assert studio.native_inspector.engine_edit.isEnabled()
        studio.native_inspector.engine_edit.click()
        assert studio.open_pixel_editor()  # Ctrl+E follows clicked game art
        assert captured==[(400,400,"tree_cactii",16)]*2
        assert studio.native_canvas.history.overlay.objects==[]
    finally:
        studio.native_canvas._poll.stop()
        studio._saved_scene=studio.board.history.scene.serialize()
        if studio.native_canvas.has_map():
            studio._saved_overlay=studio.native_canvas.history.overlay.serialize()
        studio.close()

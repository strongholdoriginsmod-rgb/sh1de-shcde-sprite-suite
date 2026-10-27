"""Native-engine graphics replace heuristic terrain while keeping the editor."""
from pathlib import Path
from types import SimpleNamespace
import sys
import os
import numpy as np
from PIL import Image
import pytest

pytest.importorskip('PySide6')
from PySide6.QtCore import Qt, QRectF
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtGui import QPixmap, QPainter
TOOLS=str(Path(__file__).resolve().parents[2]/'tools')
if TOOLS not in sys.path:sys.path.insert(0,TOOLS)
from sandbox_runtime_renderer import NativeCommandRenderer
from stronghold_europe_de.sandbox.native_runtime import RuntimeSnapshot, capture_snapshot
from stronghold_europe_de.sandbox.native_overlay import NativeOverlay,OverlayHistory
from stronghold_europe_de.sandbox.native_visual_mapping import OriginalVisualMappings
from stronghold_europe_de.sandbox.native_terrain_mapping import TerrainTestMappings
from stronghold_europe_de.sandbox.native_surface_mapping import SurfaceTestMappings
from stronghold_europe_de.sandbox.runtime_graphics import RuntimeSprite
import sandbox_studio

MAPS=Path('E:/SSGameQA/Stronghold Crusader Definitive Edition_Data/StreamingAssets/Maps')
HAS_ENGINE=os.name=='nt' and (MAPS.parents[1]/'Plugins/x86_64/CrusaderDE.dll').is_file()


def test_renderer_uses_exact_native_height_and_one_based_tree(monkeypatch,tmp_path):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    app=QApplication.instance() or QApplication([])
    rows=np.zeros((3,21),dtype='<i2')
    rows[0,:7]=[0,400,400,55,305,8,3]
    rows[1,:7]=[0,401,400,9,1,100,0]
    rows[2,:12]=[1,400,401,200,17,-8,0,0,0,0,12,0]
    snapshot=RuntimeSnapshot(rows,{})
    owner=SimpleNamespace(
        _map_path=MAPS/'Antioch.map',
        terrain_tests=TerrainTestMappings('a'*64),surface_tests=SurfaceTestMappings('a'*64),
        visual_mappings=OriginalVisualMappings(),show_original_trees=True,
        _channels=SimpleNamespace(at=lambda x,y:{3005:8,3037:0}),
    )
    renderer=NativeCommandRenderer(owner,snapshot)
    calls=[]
    renderer._draw=lambda painter,ref,x,y,opacity=1.0: calls.append((ref,x,y))
    renderer._floor(None,rows[0])
    assert calls[-1][0].group=='tile_land_macros'
    assert calls[-1][0].frame==305
    assert calls[-1][1:]==(400*32+16,400*16+16-16)
    renderer._floor(None,rows[1])
    assert calls[-1][2]==400*16+16-200
    renderer._actor(None,rows[2])
    assert calls[-1][0].group=='tree_cactii'
    assert calls[-1][0].frame==16
    assert renderer.native_height(401,400)==100
    owner.terrain_tests.assign(8,'tile_land8',1)
    assert renderer._tile_reference(rows[0]).frame==1
    renderer.assets.original_only=True
    assert renderer._tile_reference(rows[0]).frame==305


def test_floor_sides_use_direct_gm_index_not_body_index(monkeypatch):
    rows=np.zeros((1,21),dtype='<i2')
    rows[0,:7]=[0,400,400,56,120,130,0]
    rows[0,11:13]=[9,14]
    owner=SimpleNamespace(_map_path=MAPS/'Antioch.map',terrain_tests=None,
                          surface_tests=None,visual_mappings=OriginalVisualMappings(),
                          _channels=SimpleNamespace(at=lambda x,y:{3005:130}),
                          show_original_trees=True)
    renderer=NativeCommandRenderer(owner,RuntimeSnapshot(rows,{}))
    calls=[]
    renderer._draw=lambda p,ref,x,y,opacity=1.0:calls.append((ref,x,y))
    renderer._floor(None,rows[0])
    assert len(calls)==2
    assert calls[0][0].group=='tile_cliffs' and calls[0][0].frame==14
    assert calls[1][0].group=='tile_rocks8'
    assert calls[0][2]==400*16+16-260


@pytest.mark.skipif(not HAS_ENGINE,reason='Authorized game engine unavailable')
def test_real_native_scene_toggle_and_exact_tile_pixel_editor(monkeypatch,tmp_path):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    monkeypatch.setattr(sandbox_studio,'ROOT',tmp_path)
    app=QApplication.instance() or QApplication([])
    studio=sandbox_studio.SandboxStudio(tmp_path)
    try:
        assert studio.open_map(MAPS/'Antioch.map')
        canvas=studio.native_canvas
        assert canvas.runtime_snapshot.visible_tile_count==44104
        assert canvas.runtime_snapshot.object_count==1040
        assert canvas.engine_active()
        canvas.select_native(400,400)
        assert 'tile_land_macros/305' in studio.native_inspector.engine_detail.text()
        assert studio.native_inspector.engine_edit.isEnabled()
        assert canvas.native_height(400,400)==8
        studio.native_hud.engine_mode.setCurrentIndex(2)
        assert not canvas.engine_active()
        studio.native_hud.engine_mode.setCurrentIndex(1)
        assert canvas.engine_active() and canvas.runtime_renderer.assets.original_only
        studio.native_hud.engine_mode.setCurrentIndex(0)
        assert canvas.engine_active() and not canvas.runtime_renderer.assets.original_only
        selected=[]
        class Signal:
            def connect(self,*args):pass
        class PixelDialog:
            def __init__(self,group,frame,parent):
                selected.append((group,frame));self.saved_frame=Signal();self.closed=Signal()
            def show(self):pass
        import sandbox_pixel_editor
        monkeypatch.setattr(sandbox_pixel_editor,'SpritePixelEditor',PixelDialog)
        assert studio.edit_runtime_tile(400,400)
        assert selected==[('tile_land_macros',305)]
        # Remove the test dialog stub before the real window's close handling.
        studio._pixel_dialogs.clear()
        canvas._terrain_chunks[(0,0)]=QPixmap(512,256)
        canvas.runtime_renderer.images[('tile_land_macros',305,0)]=None
        canvas.runtime_renderer.overview=QPixmap(8,8)
        canvas.refresh_asset('tile_land_macros',305)
        assert not canvas._terrain_chunks
        assert not canvas.runtime_renderer.images
        assert canvas.runtime_renderer.overview is None
        studio.native_hud.engine_mode.setCurrentIndex(1)
        assert canvas.use_original_runtime_assets
        studio.asset_preview.refresh = lambda: None
        studio.sprite_palette.reload = lambda: None
        studio._pixel_changed('tile_land_macros',305)
        assert not canvas.use_original_runtime_assets
        assert studio.native_hud.engine_mode.currentIndex()==0
    finally:
        studio.native_canvas._poll.stop()
        studio._saved_scene=studio.board.history.scene.serialize()
        if studio.native_canvas.has_map():studio._saved_overlay=studio.native_canvas.history.overlay.serialize()
        studio.close()


@pytest.mark.skipif(not HAS_ENGINE,reason='Authorized game engine unavailable')
def test_real_native_original_cactus_frame_has_actual_pixels(monkeypatch):
    from sandbox_engine_assets import EngineSpriteAssets
    asset=EngineSpriteAssets(MAPS/'Antioch.map')
    frame=asset.original('tree_cactii',16)
    assert frame is not None
    assert frame.side=='crusader-original'
    assert frame.image.width>30 and frame.image.height>30
    assert frame.image.getchannel('A').getextrema()==(0,255)

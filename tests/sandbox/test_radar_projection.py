"""Original 200x200 radar and native diamond viewport navigation."""
from pathlib import Path
import math
import pytest
from PIL import Image

from stronghold_europe_de.sandbox.radar_projection import RadarProjection
from stronghold_europe_de.sandbox.map_sections import tile_index

MAP = Path("E:/SSGameQA/Stronghold Crusader Definitive Edition_Data/StreamingAssets/Maps/Antioch.map")


@pytest.mark.parametrize("x,y", [
    (399, 0), (400, 0), (399, 399), (400, 400), (0, 399),
    (799, 399), (399, 799), (400, 799), (501, 382), (380, 420),
])
def test_radar_diamond_roundtrip(x,y):
    projection = RadarProjection(25,25,150,150)
    assert 0<=tile_index(x,y)<320800
    rx,ry = projection.native_to_radar(x,y)
    xr,yr = projection.radar_to_native(rx,ry)
    assert math.isclose(xr,x,abs_tol=1e-10)
    assert math.isclose(yr,y,abs_tol=1e-10)


def test_original_radar_bounds_from_pixel_content():
    image=Image.new("RGB",(200,200),(0,0,0))
    from PIL import ImageDraw
    ImageDraw.Draw(image).rectangle((25,25,174,174),fill=(40,90,30))
    proj=RadarProjection.from_image(image)
    assert (proj.left,proj.top,proj.width,proj.height)==(25,25,150,150)
    assert proj.contains_radar(100,100)
    assert not proj.contains_radar(20,20)


@pytest.mark.skipif(not MAP.is_file(),reason="Original map not available")
def test_verified_original_radar_bounds():
    from stronghold_europe_de.sandbox.map_importer import load_radar_preview
    header,image=load_radar_preview(MAP)
    projection=RadarProjection.from_image(image)
    assert image.size==(200,200)
    assert 20 <= projection.left <= 30
    assert 20 <= projection.top <= 30
    assert 140 <= projection.width <= 160
    assert 140 <= projection.height <= 160


def test_native_minimap_uses_real_radar_and_moves_camera(monkeypatch):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM","offscreen")
    import sys
    TOOLS=str(Path(__file__).resolve().parents[2]/"tools")
    if TOOLS not in sys.path:
        sys.path.insert(0,TOOLS)
    from PySide6.QtWidgets import QApplication
    from sandbox_native_canvas import NativeMapCanvas
    import sandbox_native_canvas as mod
    from sandbox_native_panel import NativeMiniMap
    from stronghold_europe_de.sandbox.map_sections import NATIVE_TILES

    class Channels:
        channels={3005:bytes([8])*NATIVE_TILES}
        def at(self,x,y):return {3005:8}
    class FrameSource:
        def __init__(self,*a,**kw):pass
        def frame(self,*a):return None

    monkeypatch.setattr(mod,"load_original_buildings",lambda _: [])
    monkeypatch.setattr(mod,"load_original_trees",lambda _: [])
    monkeypatch.setattr(mod,"FrameSource",FrameSource)
    app=QApplication.instance() or QApplication([])
    canvas=NativeMapCanvas()
    canvas._get_texture=lambda *args: None
    base=Path(__file__).resolve()
    from tempfile import TemporaryDirectory
    try:
        with TemporaryDirectory() as folder:
            source=Path(folder)/"test.map"
            source.write_bytes(b"fake native fixture; loaded via supplied channels")
            canvas.open_map(source,channels=Channels())
            canvas.resize(800,600)
            canvas.show()
            minimap=NativeMiniMap(canvas)
            radar=Image.new("RGB",(200,200),(0,0,0))
            from PIL import ImageDraw
            ImageDraw.Draw(radar).rectangle((25,25,174,174),fill=(50,120,60))
            minimap.use_map(radar)
            app.processEvents()
            assert minimap.scene().sceneRect().width()==200
            assert minimap._camera_outline is not None
            assert minimap.go_to_radar(100,100)
            centered=canvas.mapToScene(canvas.viewport().rect().center())
            assert abs(centered.x()/32-399)<2
            assert abs(centered.y()/16-400)<2
            assert not minimap.go_to_radar(0,0)
            assert minimap._camera_outline is not None
            minimap.close()
    finally:
        canvas._poll.stop()
        canvas.close()

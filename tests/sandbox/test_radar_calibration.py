"""Grounded minimap calibration against real native map padding and radar water."""
from pathlib import Path
import math
import sys
import struct
import pytest

from stronghold_europe_de.sandbox.map_sections import (
    load_native_tile_channels, tile_row_length
)
from stronghold_europe_de.sandbox.map_importer import load_radar_preview
from stronghold_europe_de.sandbox.native_layers import native_geometry
from stronghold_europe_de.sandbox.radar_projection import RadarProjection

MAPS = Path("E:/SSGameQA/Stronghold Crusader Definitive Edition_Data/StreamingAssets/Maps")


@pytest.mark.skipif(not MAPS.is_dir(), reason="SHCDE reference maps not installed")
@pytest.mark.parametrize("name,umin,umax,vmin,vmax", [
    ("Antioch.map",125.0,275.0,124.5,274.5),
    ("Crusader Demo.map",125.0,275.0,124.5,274.5),
    ("A Mighty Oasis.map",100.0,300.0,99.5,299.5),
])
def test_radar_aligns_verified_playable_bounds_and_water(
    name, umin, umax, vmin, vmax
):
    original = MAPS/name
    old_bytes = (original.stat().st_size, original.stat().st_mtime_ns)
    channels = load_native_tile_channels(original).channels
    geometry = native_geometry(channels)
    _, radar = load_radar_preview(original)
    radar_rgb = radar.convert("RGB")
    projection = RadarProjection.from_original_geometry(radar, geometry)
    assert projection.playable_bounds == (umin,umax,vmin,vmax)
    assert (geometry.u_min,geometry.u_max,geometry.v_min,geometry.v_max)==(
        umin,umax,vmin,vmax
    )
    water_on_radar = []
    land_on_radar = []
    code = channels[3003]
    idx = 0
    for y in range(800):
        width = tile_row_length(y)
        start = (800-width)//2
        for x in range(start, start+width):
            flags = struct.unpack_from("<I", code, idx*4)[0]
            # Not all 3003 flags have known terrain meaning. These two samples
            # were chosen solely for observable water-vs-land alignment.
            if flags & 0x100000 or (flags == 0x8000 and idx%21==0):
                rx, ry = projection.native_to_radar(x, y)
                ix, iy = round(rx), round(ry)
                if (0<=ix<radar.width and 0<=iy<radar.height
                        and projection.contains_radar(rx,ry)):
                    r,g,b=radar_rgb.getpixel((ix,iy))
                    is_blue=b>r*1.03 and b>g*0.96
                    (water_on_radar if flags & 0x100000 else land_on_radar).append(is_blue)
            idx+=1
    assert len(water_on_radar)>600 and len(land_on_radar)>800
    assert sum(water_on_radar)/len(water_on_radar)>0.74
    assert sum(land_on_radar)/len(land_on_radar)<0.16
    for x,y in [(400,400),(401,398),(430,370)]:
        rx,ry=projection.native_to_radar(x,y)
        xx,yy=projection.radar_to_native(rx,ry)
        assert math.isclose(xx,x,abs_tol=1e-8)
        assert math.isclose(yy,y,abs_tol=1e-8)
    assert (original.stat().st_size, original.stat().st_mtime_ns)==old_bytes


@pytest.mark.skipif(not MAPS.is_dir(), reason="SHCDE reference maps not installed")
def test_minimap_click_uses_calibrated_coordinates_in_studio(monkeypatch,tmp_path):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]/"tools"))
    from PySide6.QtWidgets import QApplication
    import sandbox_studio
    monkeypatch.setattr(sandbox_studio, "ROOT", tmp_path)
    app=QApplication.instance() or QApplication([])
    studio=sandbox_studio.SandboxStudio(tmp_path)
    try:
        path=MAPS/"Antioch.map"
        assert studio.open_map(path)
        minimap=studio.native_minimap
        assert minimap._radar_projection.playable_bounds == (
            125.0, 275.0, 124.5, 274.5
        )
        # Click the true center of the playable logical map in the radar.
        px,py=minimap._radar_projection.native_to_radar(400,400)
        assert minimap.go_to_radar(px,py)
        view=studio.native_canvas
        scene=view.mapToScene(view.viewport().rect().center())
        assert abs(scene.x()/32-400)<2
        assert abs(scene.y()/16-400)<2
        # Out-of-bounds radar navigation must be rejected, not claim success.
        assert not minimap.go_to_radar(-30,-30)
        # A full-map camera extends beyond the game's logical world.
        # The yellow radar camera marker must not cover the HUD/dock.
        view.fit_map()
        app.processEvents()
        camera_frame = minimap._camera_outline.sceneBoundingRect()
        bounds = minimap._radar_projection
        assert camera_frame.left() >= bounds.left - 2
        assert camera_frame.top() >= bounds.top - 2
        assert camera_frame.right() <= bounds.left + bounds.width + 2
        assert camera_frame.bottom() <= bounds.top + bounds.height + 2
    finally:
        studio.native_canvas._poll.stop()
        studio._saved_scene=studio.board.history.scene.serialize()
        if studio.native_canvas.has_map():
            studio._saved_overlay=studio.native_canvas.history.overlay.serialize()
        studio.close()

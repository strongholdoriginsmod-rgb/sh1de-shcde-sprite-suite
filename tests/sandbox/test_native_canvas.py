"""Native-map HUD, click-to-place, sprite animations and read-only sources."""
from pathlib import Path
import sys
import pytest
from PIL import Image

pytest.importorskip("PySide6")
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from stronghold_europe_de.sandbox.map_sections import NATIVE_TILES
from stronghold_europe_de.sandbox.native_overlay import save_overlay,load_overlay

TOOLS=str(Path(__file__).resolve().parents[2]/"tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)
import sandbox_native_canvas as canvasmod
from sandbox_game_hud import NativeGameHUD


@pytest.fixture
def native_gui(tmp_path,monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM","offscreen")
    app=QApplication.instance() or QApplication([])
    class Frame:
        image=Image.new("RGBA",(44,54),(80,180,100,255))
        mask=None
        side="arbeit"
        foot=(22,48)
    class Source:
        def __init__(self,*args,**kwargs): pass
        def frame(self,group,name):return Frame()
    class Channels:
        channels={3005:bytes([8])*NATIVE_TILES}
        def at(self,x,y):return {3005:8,3003:16}
    monkeypatch.setattr(canvasmod,"FrameSource",Source)
    monkeypatch.setattr(canvasmod,"load_original_buildings",lambda path: [])
    monkeypatch.setattr(canvasmod,"load_original_trees",lambda path: [])
    monkeypatch.setattr(canvasmod.katalog,"native_name",lambda g,n:f"{g}-{n}")
    canvas=canvasmod.NativeMapCanvas()
    canvas._get_texture=lambda *args: None
    source=tmp_path/"test.map"
    source.write_bytes(b"real unchanged map bytes")
    canvas.open_map(source,channels=Channels())
    canvas.resize(900,700)
    canvas.show()
    hud=NativeGameHUD(canvas)
    app.processEvents()
    yield app,canvas,hud,source
    hud._stop()
    canvas._poll.stop()
    hud.close()
    canvas.close()


def test_native_map_place_save_reload_and_animation(native_gui,tmp_path):
    app,canvas,hud,source=native_gui
    assert canvas.has_map()
    assert canvas.original_buildings==[]
    canvas.resetTransform()
    canvas.scale(.9,.9)
    canvas.center_native(400,400)
    app.processEvents()
    clicks=[]
    canvas.picked.connect(lambda x,y,vals: clicks.append((x,y,vals[3005])))
    canvas.arm_placement("unit_test",2)
    point=canvas.mapFromScene(400*32+16,400*16+16)
    QTest.mouseClick(canvas.viewport(),Qt.MouseButton.LeftButton,pos=point)
    app.processEvents()
    assert len(canvas.history.overlay.objects)==1
    obj=canvas.history.overlay.objects[0]
    assert abs(obj.x-400)<=1 and abs(obj.y-400)<=1
    uid=obj.id
    canvas._placing=None
    canvas._items[uid].setSelected(True)
    app.processEvents()
    hud.display_map(source)
    assert hud._selected==uid
    before=canvas.history.overlay.serialize()
    hud.first.setValue(2)
    hud.last.setValue(5)
    hud._toggle()
    assert hud._playing
    hud._advance()
    hud._stop()
    assert canvas.history.overlay.serialize()==before
    target=tmp_path/"overlay.json"
    save_overlay(target,canvas.history.overlay)
    assert load_overlay(target,source).objects[0].id==uid
    canvas.history.move(uid,401,401)
    canvas.rebuild(focus=uid)
    canvas.undo()
    assert canvas.history.overlay.objects[0].x==obj.x
    canvas.redo()
    assert canvas.history.overlay.objects[0].x==401
    canvas._items[uid].setSelected(True)
    canvas.delete_selected()
    assert not canvas.history.overlay.objects
    canvas.undo()
    assert len(canvas.history.overlay.objects)==1
    assert source.read_bytes()==b"real unchanged map bytes"


def test_native_display_modes_do_not_change_original_map(native_gui):
    app,canvas,hud,source=native_gui
    before=source.read_bytes()
    hud.show_tiles.setChecked(True)
    assert canvas.diagnostic_only
    hud.show_tiles.setChecked(False)
    assert not canvas.diagnostic_only
    hud.show_buildings.setChecked(False)
    assert not canvas.show_original_buildings
    assert source.read_bytes()==before


def test_external_work_png_change_updates_only_affected_sprite(native_gui, tmp_path, monkeypatch):
    app,canvas,hud,source = native_gui
    work=tmp_path/"work"/"unit_test"
    work.mkdir(parents=True)
    monkeypatch.setattr(canvasmod.katalog,"work_dir",lambda group:work)
    ident=canvas.history.place("unit_test",1,400,400)
    canvas.rebuild(focus=ident)
    before=canvas.history.overlay.serialize()
    old = canvas._items[ident]
    key=("unit_test",1)
    assert key in canvas._sprite_signatures
    changes=[]
    original=canvas.refresh_asset
    def spy(group,frame):
        changes.append((group,frame))
        return original(group,frame)
    monkeypatch.setattr(canvas,"refresh_asset",spy)
    (work/"unit_test-1.png").write_bytes(b"external graphics editor saved this file")
    canvas.refresh_changed()
    assert changes==[("unit_test",1)]
    assert canvas._items[ident] is old
    assert canvas.history.overlay.serialize()==before
    canvas.refresh_changed()
    assert changes==[("unit_test",1)]

def test_chunk_cache_reuses_pixmaps_and_bounds_memory(native_gui, monkeypatch):
    app, canvas, hud, source = native_gui
    from PySide6.QtGui import QPixmap
    import sandbox_native_canvas as mod
    painted = []
    def draw_area(painter, rect):
        painted.append((int(rect.x()), int(rect.y())))
    monkeypatch.setattr(canvas, "_draw_terrain_area", draw_area)
    first = canvas._terrain_chunk(15, 12)
    second = canvas._terrain_chunk(15, 12)
    assert first is second
    assert painted == [(15 * mod.CHUNK_W, 12 * mod.CHUNK_H)]
    for i in range(mod.CHUNK_CACHE_LIMIT + 5):
        canvas._terrain_chunk(i, 13)
    assert len(canvas._terrain_chunks) == mod.CHUNK_CACHE_LIMIT
    assert (15, 12) not in canvas._terrain_chunks


def test_external_ground_asset_change_invalidates_chunks(native_gui, monkeypatch, tmp_path):
    app, canvas, hud, source = native_gui
    from PySide6.QtGui import QPixmap
    work = tmp_path / "tile_land8"
    work.mkdir()
    monkeypatch.setattr(canvasmod.katalog, "work_dir", lambda group: work)
    key = ("tile_land8", 1)
    canvas._texture_signatures[key] = canvas._signature(*key)
    canvas._terrain_chunks[(0, 0)] = QPixmap(512, 256)
    (work / "tile_land8-1.png").write_bytes(b"changed")
    canvas.refresh_changed()
    assert not canvas._terrain_chunks
    assert not canvas._texture_signatures


def test_adjacent_chunks_match_uncropped_direct_render(native_gui, monkeypatch):
    app, canvas, hud, source = native_gui
    from PySide6.QtCore import Qt, QPointF, QRectF
    from PySide6.QtGui import QPixmap, QColor, QPainter
    source_pixmap = QPixmap(72, 60)
    source_pixmap.fill(QColor(50, 160, 90, 180))
    monkeypatch.setattr(canvas, "_get_texture", lambda *args: (source_pixmap, (35, 34)))
    canvas._terrain_chunks.clear()
    # Compare two independently rasterized and cropped chunks with a direct,
    # full-world render along the boundary. Off-tile sprites must not create seams.
    direct = QPixmap(1024, 256)
    direct.fill(Qt.GlobalColor.transparent)
    painter = QPainter(direct)
    painter.translate(0, -(24 * 256))
    canvas._draw_terrain_area(painter, QRectF(0, 24 * 256, 1024, 256))
    painter.end()
    joined = QPixmap(1024, 256)
    joined.fill(Qt.GlobalColor.transparent)
    painter = QPainter(joined)
    painter.drawPixmap(QPointF(0, 0), canvas._terrain_chunk(0, 24))
    painter.drawPixmap(QPointF(512, 0), canvas._terrain_chunk(1, 24))
    painter.end()
    for x in [0, 16, 210, 500, 510, 511, 512, 513, 530, 799, 1023]:
        for y in [0, 8, 64, 127, 200, 255]:
            assert joined.toImage().pixel(x, y) == direct.toImage().pixel(x, y), (x, y)


def test_correlated_water_bit_precedes_unverified_height_material(native_gui,monkeypatch):
    app,canvas,hud,source=native_gui
    selected=[]
    monkeypatch.setattr(canvas,"_get_texture",
                        lambda material,x,y:selected.append(material) or None)
    assert canvas._get_terrain_texture(122,400,400,0x100000) is None
    assert selected[-1]=="water"
    assert canvas._get_terrain_texture(122,400,400,0) is None
    assert selected[-1]=="shore"
    from stronghold_europe_de.sandbox.native_terrain_mapping import TerrainTestMappings
    manual=TerrainTestMappings(canvas.history.overlay.source_sha256)
    manual.assign(122,"tile_land8",37)
    canvas.set_terrain_tests(manual)
    arbitrary=[]
    monkeypatch.setattr(canvas,"_load_texture",
                        lambda group,frame: arbitrary.append((group,frame)) or None)
    assert canvas._get_terrain_texture(122,400,400,0x100000) is None
    assert arbitrary[-1]==("tile_land8",37)

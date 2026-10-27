"""Zero-I/O HUD artwork resolver: no portrait/mapping guessed from raw IDs."""
from pathlib import Path
from types import SimpleNamespace
import sys

ROOT=Path(__file__).resolve().parents[2]
if str(ROOT/"tools") not in sys.path:
    sys.path.insert(0,str(ROOT/"tools"))

from sandbox_gameplay_artwork import selection_artwork


class Pix:
    def __init__(self, empty=False):
        self.empty=empty
    def isNull(self):
        return self.empty


class Item:
    def __init__(self, ident, scene, pix, loaded=True):
        self.object_id=ident
        self._scene=scene
        self._pix=pix
        self.source_loaded=loaded
    def scene(self): return self._scene
    def pixmap(self): return self._pix


def canvas_stub():
    scene=object()
    obj=SimpleNamespace(id="id-1",group="tree_pine",frame=20)
    item=Item("id-1",scene,Pix())
    history=SimpleNamespace(overlay=SimpleNamespace(objects=[obj]))
    cache={}
    owner=SimpleNamespace()
    renderer=SimpleNamespace(owner=owner,snapshot=None,images=cache,
        assets=SimpleNamespace(original_only=False))
    owner.has_map=lambda:True
    owner.scene=lambda:scene
    owner.history=history
    owner.select_id=lambda:"id-1"
    owner._items={"id-1":item}
    owner.selected_original=lambda:None
    owner.engine_active=lambda:True
    owner.runtime_renderer=renderer
    snap=object()
    owner.runtime_snapshot=snap
    renderer.snapshot=snap
    renderer.owner=owner
    owner.last_engine_pick=None
    return owner,item,obj,renderer


def test_authored_overlay_preview_is_existing_live_pixmap_only():
    c,item,obj,_=canvas_stub()
    found=selection_artwork(c,"overlay")
    assert found.kind=="overlay"
    assert found.identity=="tree_pine/20"
    assert found.pixmap is item.pixmap()
    assert "Arbeitsgrafik" in found.source
    item.source_loaded=False
    assert selection_artwork(c,"overlay") is None
    item.source_loaded=True
    item._pix=Pix(empty=True)
    assert selection_artwork(c,"overlay") is None
    item._pix=Pix()
    item._scene=object()
    assert selection_artwork(c,"overlay") is None


def test_raw_map_type_ids_and_tile_codes_never_invent_a_preview():
    c,_,_,_=canvas_stub()
    for kind in ("building","tree","tile","idle","none","economy"):
        assert selection_artwork(c,kind) is None
    c.has_map=lambda:False
    assert selection_artwork(c,"overlay") is None


def test_engine_picture_requires_matching_live_renderer_frame_cache():
    c,_,_,renderer=canvas_stub()
    ref=SimpleNamespace(group="tile_land8",frame=42,light=0,float_colour=3)
    c.last_engine_pick=SimpleNamespace(ref=ref,kind="floor")
    pix=Pix()
    key=("tile_land8",42,0,3)
    assert selection_artwork(c,"engine") is None
    renderer.images[key]=(pix,(10,10))
    art=selection_artwork(c,"engine",language="en")
    assert art.pixmap is pix
    assert art.identity=="tile_land8/42"
    assert "local work/catalog" in art.source
    renderer.assets.original_only=True
    assert "Original Unity" in selection_artwork(c,"engine",language="en").source
    renderer.snapshot=object()
    assert selection_artwork(c,"engine") is None
    renderer.snapshot=c.runtime_snapshot
    c.engine_active=lambda:False
    assert selection_artwork(c,"engine") is None


def test_missing_cached_image_or_wrong_owner_is_not_implicitly_exported():
    c,_,_,renderer=canvas_stub()
    ref=SimpleNamespace(group="tree_cactii",frame=1,light=0,float_colour=0)
    c.last_engine_pick=SimpleNamespace(ref=ref,kind="actor")
    key=("tree_cactii",1,0,0)
    renderer.images[key]=None
    assert selection_artwork(c,"engine") is None
    renderer.images[key]=(Pix(empty=True),(0,0))
    assert selection_artwork(c,"engine") is None
    renderer.images[key]=(Pix(),(0,0))
    renderer.owner=object()
    assert selection_artwork(c,"engine") is None

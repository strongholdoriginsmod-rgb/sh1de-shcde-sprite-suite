"""Historical SU Sandkasten v1 is compared by REAL source and lossless semantics.

The new editable-v2 model does not support v1 ground seed, GM1 composites
and per-object animation. Incompatibility must be explicit and non-writing.
The retained legacy renderer itself MUST stay pixel-identical given identical
scene/frame inputs; old and current modules are independently executed.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
import json,os,runpy,sys
import pytest
from PIL import Image

ROOT=Path(__file__).resolve().parents[2]
ORIGINAL=Path("E:/SU/projekt")
sys.path.insert(0,str(ROOT/"src"))
sys.path.insert(0,str(ROOT/"tools"))
from stronghold_europe_de.sandbox.scene_model import (
    SceneError,EditableScene,load_scene
)


@pytest.fixture
def old_and_current():
    if not (ORIGINAL/"tools/sandkasten.py").is_file():
        pytest.skip("Historical SU/projekt source is not available here")
    old=runpy.run_path(str(ORIGINAL/"tools/sandkasten.py"),run_name="legacy_original_readonly")
    current=runpy.run_path(str(ROOT/"tools/sandkasten.py"),run_name="legacy_current_readonly")
    return old,current


@pytest.mark.parametrize("name",["beispieldorf.json","katalog-vorschau.json"])
def test_original_sandbox_scene_is_not_silently_flattened(name,tmp_path):
    source=ORIGINAL/"sandbox/szenen"/name
    if not source.is_file():
        pytest.skip("Private historical test fixture absent")
    raw=source.read_bytes()
    original_hash=sha256(raw).hexdigest()
    assert json.loads(raw.decode("utf-8-sig"))["schema"]==(
        "stronghold-europe.sandkasten.v1"
    )
    scene=load_scene(source)
    assert scene.is_legacy_v1
    assert scene.serialize()==json.loads(raw.decode("utf-8-sig"))
    assert sha256(source.read_bytes()).hexdigest()==original_hash

    # Even a copied historical scene may NOT be overwritten by a newly
    # saved v2 scene, irrespective of matching .json file extension.
    from stronghold_europe_de.sandbox.scene_model import save_scene
    copy=tmp_path/name
    copy.write_bytes(raw)
    with pytest.raises(SceneError):
        save_scene(copy,EditableScene())
    assert copy.read_bytes()==raw
    assert sha256(source.read_bytes()).hexdigest()==original_hash


def test_original_sandbox_source_file_is_exactly_preserved(old_and_current):
    source=ORIGINAL/"tools/sandkasten.py"
    assert sha256(source.read_bytes()).hexdigest()==sha256(
        (ROOT/"tools/sandkasten.py").read_bytes()
    ).hexdigest()


@pytest.mark.parametrize("name",["beispieldorf.json","katalog-vorschau.json"])
def test_original_render_semantics_are_identical_in_retained_legacy_renderer(
    old_and_current,name
):
    src=ORIGINAL/"sandbox/szenen"/name
    if not src.is_file():
        pytest.skip("Private original legacy scene unavailable")
    raw=json.loads(src.read_text(encoding="utf-8-sig"))
    old,current=old_and_current

    class Source:
        def __init__(self):
            self.cache={}
        def frame(self,group,native_name):
            key=(group,native_name)
            if key not in self.cache:
                seed=sha256((group+"/"+native_name).encode()).digest()
                pixels=Image.new("RGBA",(17,19),(*seed[:3],255))
                self.cache[key]=SimpleNamespace(
                    image=pixels,foot=(8.5,17.5),mask=None,side="reference"
                )
            return self.cache[key]

    for tick in (0.0,1.37):
        original_image,original_items,original_missing=old["render"](
            raw,Source(),tick,grid=False,pivots=False
        )
        current_image,current_items,current_missing=current["render"](
            raw,Source(),tick,grid=False,pivots=False
        )
        assert original_image.size==current_image.size
        assert original_image.tobytes()==current_image.tobytes()
        assert original_missing==current_missing==[]
        assert [
            (it.group,it.name,it.x,it.y,it.layer,it.order,it.box)
            for it in original_items
        ]==[
            (it.group,it.name,it.x,it.y,it.layer,it.order,it.box)
            for it in current_items
        ]


def test_new_v2_is_independent_of_original_v1_fields():
    editable=EditableScene()
    record=editable.serialize()
    assert record["schema"]=="stronghold-europe.sandbox.scene.v2"
    assert "boden" not in record and "objekte" not in record

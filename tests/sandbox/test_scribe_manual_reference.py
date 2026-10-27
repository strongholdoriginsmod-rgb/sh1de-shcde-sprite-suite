"""Original-SHCDЕ Scribe B/C references are MANUAL: not live adviser states."""
from hashlib import sha256
from pathlib import Path
import json, sys

import pytest
from PIL import Image

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication

ROOT=Path(__file__).resolve().parents[2]
if str(ROOT/"tools") not in sys.path:
    sys.path.insert(0,str(ROOT/"tools"))
from sandbox_native_hud_crop_provider import OriginalGameUICrops
from sandbox_scribe_reference import (
    ManualScribeReference, ScribeReferenceError,
    FAMILIES, reference_key, reference_dimensions
)


def digest(value):
    return sha256(value).hexdigest()


@pytest.fixture
def reference_source(tmp_path):
    """Synthetic installed XAML and SHA-valid crop cache, no game required."""
    game=tmp_path/"game"
    cache=tmp_path/"work"
    game.mkdir()
    cache.mkdir()
    original=game/"globalgamemanagers.assets"
    dictionary=game/"UI-MasterAtlas.xaml"
    hud=game/"HUD_Main.xaml"
    original.write_bytes(b"synthetic-game-source-NOT-actual-game")
    hud.write_text("<Grid/>",encoding="utf8")
    prefix='<ResourceDictionary xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml">'
    rows=[]
    entries={}
    for family,count in FAMILIES.items():
        for frame in range(1,count+1):
            key=reference_key(family,frame)
            w,h=reference_dimensions(family,frame)
            rect=[20+frame,50,w,h]
            rows.append(f'<CroppedBitmap x:Key="{key}" SourceRect="{",".join(map(str,rect))}"/>')
            name=digest(key.encode())[:24]+".png"
            entries[key]={"name":name,"rect":rect,"png_sha256":None}
    dictionary.write_text(prefix+"\n".join(rows)+"</ResourceDictionary>",encoding="utf8")
    # Generate just a few small test images; all other entries remain lazy.
    for family,frame in (("B",1),("B",45),("C",1),("C",44)):
        key=reference_key(family,frame)
        size=reference_dimensions(family,frame)
        path=cache/entries[key]["name"]
        Image.new("RGBA",size,(120,40,33,255)).save(path)
        entries[key]["png_sha256"]=digest(path.read_bytes())
    manifest={
        "schema":"sprite-suite.shcde-native-ui-crops.v1",
        "source_kind":"UNMODIFIED_LOCAL_GAME_UNITY_UI_TEXTURE",
        "source":str(original),"source_sha256":digest(original.read_bytes()),
        "texture_name":"UI-MasterAtlas","texture_format":25,
        "dictionary_xaml":str(dictionary),
        "dictionary_sha256":digest(dictionary.read_bytes()),
        "hud_main_xaml":str(hud),
        "hud_main_sha256":digest(hud.read_bytes()),
        "scribe_state_mapping":"UNVERIFIED_MANUAL_REFERENCE_ONLY",
        "entries":entries
    }
    p=cache/"manifest.json"
    p.write_text(json.dumps(manifest),encoding="utf8")
    contract={"source":{
        "dictionary_sha256":manifest["dictionary_sha256"],
        "xaml_sha256":manifest["hud_main_sha256"]
    },"rectangles":{}}
    app=QApplication.instance() or QApplication([])
    return OriginalGameUICrops(contract,p),dictionary,manifest,p


@pytest.mark.parametrize("family,count",[("B",45),("C",44)])
def test_both_original_families_are_contiguous_reference_ids(family,count):
    keys=[reference_key(family,n) for n in range(1,count+1)]
    assert len(set(keys))==count
    assert keys[0]==f"UI-Scribe {family}001"
    assert keys[-1]==f"UI-Scribe {family}{count:03d}"


@pytest.mark.parametrize("family,n",[
    ("A",1),("B",0),("B",46),("C",45),("B",1.0),("C",True),("",2)
])
def test_arbitrary_frames_cannot_be_requested(family,n):
    with pytest.raises(ScribeReferenceError):
        reference_key(family,n)


def test_b045_is_an_exception_not_proven_animation_end():
    assert reference_dimensions("B",44)==(374,414)
    assert reference_dimensions("B",45)==(178,164)
    assert reference_dimensions("C",44)==(374,414)


def test_source_bound_reference_loads_only_requested_verified_frame(reference_source):
    source,_,_,_=reference_source
    viewer=ManualScribeReference(source)
    assert viewer.pixmap("B",1).size().width()==374
    assert viewer.pixmap("B",45).size().width()==178
    assert viewer.pixmap("C",44).size().height()==414
    assert "MANUELLE" in viewer.description("B",1)
    assert "KEIN nachgewiesenes Animationsende" in viewer.description("B",45)
    assert "No playback timing" in viewer.description("C",1,"en")


def test_missing_or_changed_xaml_reference_fails_closed(reference_source):
    source,dictionary,manifest,path=reference_source
    dictionary.write_text(dictionary.read_text(encoding="utf8").replace(
        'SourceRect="21,50,374,414"', 'SourceRect="21,50,369,414"'
    ),encoding="utf8")
    with pytest.raises(ScribeReferenceError):
        ManualScribeReference(source)


def test_matching_xaml_but_wrong_cache_rectangle_fails_closed(reference_source):
    source,_,_,_=reference_source
    source.entries["UI-Scribe C001"]["rect"]=[1,2,3,4]
    with pytest.raises(ScribeReferenceError):
        ManualScribeReference(source)


def test_damaged_private_reference_image_is_not_replaced(reference_source):
    source,_,_,_=reference_source
    viewer=ManualScribeReference(source)
    key="UI-Scribe B001"
    path=source.directory/source.entries[key]["name"]
    Image.new("RGBA",(374,414),(1,2,3,255)).save(path)
    with pytest.raises(ScribeReferenceError):
        viewer.pixmap("B",1)


def test_installed_original_reference_catalog_has_89_frames():
    from sandbox_hud_original_art import load_hud_contract
    from sandbox_native_hud_crop_provider import DEFAULT_CROPS
    if not DEFAULT_CROPS.is_file():
        pytest.skip("Original private game reference not available")
    original=OriginalGameUICrops(load_hud_contract(),DEFAULT_CROPS)
    viewer=ManualScribeReference(original)
    assert sum(FAMILIES.values())==89
    assert viewer.pixmap("B",1).size().height()==414
    assert viewer.pixmap("B",45).size().height()==164
    assert viewer.pixmap("C",44).size().width()==374

"""Source-bound original Crusader HUD image provider; no Unity export in UI.

Synthetic contracts test corrupt sources and path traversal; local original
test skips cleanly when private game asset cache is unavailable.
"""
from pathlib import Path
import hashlib,json,sys
import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication
from PIL import Image

root=Path(__file__).resolve().parents[2]
if str(root/"tools") not in sys.path:
    sys.path.insert(0,str(root/"tools"))
from sandbox_native_hud_crop_provider import (
    OriginalGameUICrops,OriginalUICropError,DEFAULT_CROPS,
)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def source_fixture(tmp_path):
    directory=tmp_path/"work"/"native-crops"
    directory.mkdir(parents=True)
    sources=tmp_path/"game"
    sources.mkdir()
    original=sources/"globalgamemanagers.assets"
    dictionary=sources/"UI-MasterAtlas.xaml"
    hud=sources/"HUD_Main.xaml"
    original.write_bytes(b"dummy-original-asset-test-only")
    dictionary.write_text("<ResourceDictionary/>",encoding="utf8")
    hud.write_text("<Grid/>",encoding="utf8")
    key="UI-Buildings A001"
    png_name=digest(key.encode())[:24]+".png"
    image=directory/png_name
    Image.new("RGBA",(8,8),(123,63,22,255)).save(image)
    contract={
        "source":{
            "dictionary_sha256":digest(dictionary.read_bytes()),
            "xaml_sha256":digest(hud.read_bytes()),
        },
        "rectangles":{key:[0,0,8,8]},
    }
    manifest={
        "schema":"sprite-suite.shcde-native-ui-crops.v1",
        "source_kind":"UNMODIFIED_LOCAL_GAME_UNITY_UI_TEXTURE",
        "source":str(original),"source_sha256":digest(original.read_bytes()),
        "texture_name":"UI-MasterAtlas","texture_format":25,
        "dictionary_xaml":str(dictionary),
        "dictionary_sha256":contract["source"]["dictionary_sha256"],
        "hud_main_xaml":str(hud),
        "hud_main_sha256":contract["source"]["xaml_sha256"],
        "scribe_state_mapping":"UNVERIFIED_MANUAL_REFERENCE_ONLY",
        "entries":{
            key:{"name":png_name,"rect":[0,0,8,8],
                 "png_sha256":digest(image.read_bytes())},
        },
    }
    path=directory/"manifest.json"
    path.write_text(json.dumps(manifest),encoding="utf8")
    return contract,manifest,path,image,original


def test_verified_local_original_icon_source_is_loaded_without_reexport(
    source_fixture
):
    contract,manifest,path,image,_=source_fixture
    app=QApplication.instance() or QApplication([])
    reader=OriginalGameUICrops(contract,path)
    pix=reader.crop("UI-Buildings A001")
    assert pix.width()==8 and pix.height()==8 and not pix.isNull()
    assert reader.crop("UI-Buildings A001") is pix
    assert reader.source_sha256==manifest["source_sha256"]


def test_original_icon_invalid_hash_never_falls_back_to_derived(source_fixture):
    contract,manifest,path,image,_=source_fixture
    app=QApplication.instance() or QApplication([])
    reader=OriginalGameUICrops(contract,path)
    Image.new("RGBA",(8,8),(4,5,6,255)).save(image)
    with pytest.raises(OriginalUICropError,match="SHA mismatch"):
        reader.crop("UI-Buildings A001")


def test_bad_original_source_fails_closed(source_fixture):
    contract,manifest,path,image,original=source_fixture
    original.write_bytes(b"fake-replaced-asset")
    with pytest.raises(OriginalUICropError,match="SHA mismatch"):
        OriginalGameUICrops(contract,path)


@pytest.mark.parametrize("change",["filename","rectangle","schema","unverified_role"])
def test_original_asset_manifest_never_trusts_file_paths_or_roles(
    source_fixture,change
):
    contract,manifest,path,image,_=source_fixture
    if change=="filename":
        manifest["entries"]["UI-Buildings A001"]["name"]="../escape.png"
    if change=="rectangle":
        manifest["entries"]["UI-Buildings A001"]["rect"]=[0,1,8,8]
    if change=="schema":
        manifest["schema"]="invented"
    if change=="unverified_role":
        manifest["scribe_state_mapping"]="LIVE_STATE_PROVEN"
    path.write_text(json.dumps(manifest),encoding="utf8")
    if change=="filename":
        reader=OriginalGameUICrops(contract,path)
        with pytest.raises(OriginalUICropError,match="Unsafe"):
            reader.crop("UI-Buildings A001")
    else:
        with pytest.raises(OriginalUICropError):
            OriginalGameUICrops(contract,path)


def test_installed_original_crusader_ui_pixels_are_digest_pinned():
    if not DEFAULT_CROPS.is_file():
        pytest.skip("Private local original crop cache unavailable")
    from sandbox_hud_original_art import load_hud_contract
    reader=OriginalGameUICrops(load_hud_contract(),DEFAULT_CROPS)
    app=QApplication.instance() or QApplication([])
    icon=reader.crop("UI-Buildings A001")
    assert icon.size().width()==68 and icon.size().height()==68
    assert not icon.isNull()
    assert "UI-Scribe B001" in reader.entries
    assert "UI-Scribe C001" in reader.entries
    assert reader.entries["UI-Scribe B001"]["rect"][2:]==[374,414]

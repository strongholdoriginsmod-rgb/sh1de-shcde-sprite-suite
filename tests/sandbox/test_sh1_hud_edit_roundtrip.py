"""Synthetic Stronghold-1 GUI contract regression; contains NO game pixels."""
import json,sys
from pathlib import Path
import pytest
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"tools"))
from ui_sh1_hud import SCHEMA,BUILD_ID,HudError,digest_file,pixel_digest,check_workspace,build_workspace

def make(tmp_path):
 p=tmp_path/"work"/"project"
 (p/"baseline").mkdir(parents=True)
 atlases=[];baseline=[]
 for name,key in [("UI-MasterAtlas","UI-HUD 007"),("UI-ROL","ROL-A001"),("UI-CandleAtlas","Candle01")]:
  image=Image.new("RGBA",(16,16),(181,126,77,255))
  png=p/"baseline"/(name+".png")
  xaml=p/"baseline"/(name+".xaml")
  image.save(png)
  xaml.write_text('<ResourceDictionary xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml">\n'
      f'<BitmapImage x:Key="{name}" UriSource="{name}.png"/>\n'
      f'<CroppedBitmap x:Key="{key}" Source="{{StaticResource {name}}}" SourceRect="2,3,6,5"/>\n'
      '</ResourceDictionary>\n',encoding="utf8")
  (p/name).mkdir()
  part=image.crop((2,3,8,8))
  part.save(p/name/(key+".png"))
  atlases.append({"dictionary":xaml.name,"dictionary_sha256":digest_file(xaml),
    "sheet":png.name,"sheet_width":16,"sheet_height":16,"directory":name,
    "crops":[{"key":key,"file":key+".png","x":2,"y":3,"width":6,"height":5,
              "baseline_pixels_sha256":pixel_digest(part)}]})
  baseline.append({"sheet":png.name,"sha256":digest_file(png),"dictionary":xaml.name,
                   "dictionary_sha256":digest_file(xaml)})
 (p/"index.json").write_text(json.dumps({"schema_version":1,"target_build_id":BUILD_ID,
    "texture_asset_name":"globalgamemanagers.assets","texture_asset_sha256":"f"*64,
    "atlases":atlases}),encoding="utf8")
 (p/"sh1_hud_source.json").write_text(json.dumps({"schema":SCHEMA,
    "source_globalgamemanagers_sha256":"f"*64,"baseline_files":baseline,
    "editable_images":3}),encoding="utf8")
 return p

def test_sh1_original_mapping_synthetic(tmp_path):
 p=make(tmp_path)
 d,outputs=check_workspace(p)
 assert d["checked"]==3 and d["changed"]==[] and outputs==[]

def test_sh1_edit_rebuild_roundtrip(tmp_path,monkeypatch):
 import ui_sh1_hud
 monkeypatch.setattr(ui_sh1_hud,"ROOT",tmp_path)
 p=make(tmp_path)
 png=p/"UI-MasterAtlas"/"UI-HUD 007.png"
 with Image.open(png) as raw:img=raw.convert("RGBA")
 img.putpixel((1,1),(1,2,3,255))
 img.save(png)
 d,_=check_workspace(p)
 assert [x["key"] for x in d["changed"]]==["UI-HUD 007"]
 out=tmp_path/"dist"/"candidate"
 build_workspace(p,out,False)
 manifest=json.loads((out/"sh1_hud_build_manifest.json").read_text("utf8"))
 assert manifest["validated_named_crops"]==3 and len(manifest["edited_crops"])==1
 with Image.open(out/"UI-MasterAtlas.png") as result:
  assert result.convert("RGBA").getpixel((3,4))==(1,2,3,255)
 for name in ("UI-ROL","UI-CandleAtlas"):
  assert digest_file(out/(name+".png"))==digest_file(p/"baseline"/(name+".png"))
 with pytest.raises(HudError):build_workspace(p,out,False)

def test_wrong_size_is_rejected(tmp_path):
 p=make(tmp_path)
 Image.new("RGBA",(7,5)).save(p/"UI-ROL"/"ROL-A001.png")
 with pytest.raises(HudError,match="statt"):check_workspace(p)

def test_changed_original_xaml_rejected(tmp_path):
 p=make(tmp_path)
 xaml=p/"baseline"/"UI-CandleAtlas.xaml"
 xaml.write_text(xaml.read_text("utf8")+" ",encoding="utf8")
 with pytest.raises(HudError,match="XAML"):check_workspace(p)

def test_missing_image_rejected(tmp_path):
 p=make(tmp_path)
 (p/"UI-MasterAtlas"/"UI-HUD 007.png").unlink()
 with pytest.raises(HudError,match="fehlt"):check_workspace(p)

@pytest.mark.parametrize("which", [
    "missing_baseline_list",
    "malformed_baseline_entry",
    "missing_editable_count",
    "invalid_atlas_entry",
    "missing_crop_geometry",
    "invalid_sheet_size",
])
def test_corrupt_manifests_rejected_without_crashing(tmp_path, which):
    # Damaged or third-party edit projects must fail with a readable HUD
    # validation error, not leak raw KeyError/TypeError/AttributeError traces.
    p=make(tmp_path)
    meta=p/"sh1_hud_source.json"
    idx=p/"index.json"
    metadata=json.loads(meta.read_text(encoding="utf8"))
    index=json.loads(idx.read_text(encoding="utf8"))
    if which=="missing_baseline_list":
        metadata["baseline_files"]=None
    elif which=="malformed_baseline_entry":
        metadata["baseline_files"][0]=None
    elif which=="missing_editable_count":
        metadata.pop("editable_images")
    elif which=="invalid_atlas_entry":
        index["atlases"][0]=None
    elif which=="missing_crop_geometry":
        index["atlases"][0]["crops"][0].pop("width")
    elif which=="invalid_sheet_size":
        index["atlases"][0]["sheet_width"]=["16"]
    meta.write_text(json.dumps(metadata),encoding="utf8")
    idx.write_text(json.dumps(index),encoding="utf8")
    with pytest.raises(HudError):
        check_workspace(p)


def test_pillow_decompression_guard_is_not_disabled():
    # Standard 8192x4096 SH1 atlas is smaller than Pillow's safety bound.
    assert Image.MAX_IMAGE_PIXELS is not None

def test_stage_refuses_replacing_a_file_instead_of_a_directory(tmp_path, monkeypatch):
    import ui_sh1_hud
    monkeypatch.setattr(ui_sh1_hud, "ROOT", tmp_path)
    folder=tmp_path/"dist"
    folder.mkdir()
    innocent=folder/"not-a-directory"
    innocent.write_text("keep me", encoding="utf8")
    with pytest.raises(HudError):
        ui_sh1_hud.stage_for(innocent, replace=True)
    assert innocent.read_text(encoding="utf8")=="keep me"


def test_build_refuses_replacing_its_own_editable_source(tmp_path, monkeypatch):
    """--replace must never delete the original 1391 editable PNGs if source=out."""
    import shutil
    import ui_sh1_hud
    monkeypatch.setattr(ui_sh1_hud, "ROOT", tmp_path)
    source=make(tmp_path)
    destination=tmp_path/"dist"/"named-hud-project"
    destination.parent.mkdir()
    shutil.copytree(source,destination)
    old=(destination/"index.json").read_bytes()
    with pytest.raises(HudError, match="Quelle|identisch|überschneid"):
        build_workspace(destination,destination,replace=True)
    assert (destination/"index.json").read_bytes()==old
    assert (destination/"UI-MasterAtlas"/"UI-HUD 007.png").is_file()


def test_export_refuses_source_in_its_own_output(tmp_path,monkeypatch):
    """Export must refuse to replace the directory holding the source .assets."""
    import ui_sh1_hud
    monkeypatch.setattr(ui_sh1_hud,"ROOT",tmp_path)
    target=tmp_path/"work"/"hud-working"
    target.mkdir(parents=True)
    src=target/"globalgamemanagers.assets"
    src.write_bytes(b"user-original-source-must-survive")
    with pytest.raises(HudError, match="Quelle|überschneid"):
        ui_sh1_hud.export_workspace(src,target,replace=True)
    assert src.read_bytes()==b"user-original-source-must-survive"


def test_atomic_directory_commit_rolls_back_after_failed_publish(tmp_path, monkeypatch):
    """An os.replace interruption restores the previous worktree unmodified."""
    import os
    import ui_sh1_hud
    monkeypatch.setattr(ui_sh1_hud, "ROOT", tmp_path)
    root=tmp_path/"dist"
    root.mkdir()
    target=root/"versioned"
    target.mkdir()
    (target/"old_png.txt").write_text("precious user data",encoding="utf8")
    stage=ui_sh1_hud.stage_for(target,replace=True)
    (stage/"new_png.txt").write_text("new",encoding="utf8")
    original_replace=ui_sh1_hud.os.replace
    def fail_on_new_stage(src,dst):
        if Path(src)==stage and Path(dst)==target:
            raise OSError("injected interruption")
        return original_replace(src,dst)
    monkeypatch.setattr(ui_sh1_hud.os, "replace", fail_on_new_stage)
    with pytest.raises(OSError,match="injected"):
        ui_sh1_hud.commit(stage,target,replace=True)
    assert (target/"old_png.txt").read_text(encoding="utf8")=="precious user data"
    assert not (target/"new_png.txt").exists()
    assert not target.with_name(target.name+".sh1-hud-sicherung").exists()

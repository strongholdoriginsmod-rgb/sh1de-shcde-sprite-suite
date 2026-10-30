"""Transactional UI atlas transfer: no partial target after an interrupted write."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

from PIL import Image
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"tools"))
import ui_atlas_layout_port as port

SHEET="UI-MasterAtlas.png"
SOURCE_KEY_A="UI-Buttons S001"
SOURCE_KEY_B="UI-Buttons S002"
TARGET_ONLY="UI-Buttons S003"


def digest(image: Image.Image) -> str:
    return hashlib.sha256(image.convert("RGBA").tobytes()).hexdigest()


def write_image(path: Path, size: tuple[int,int], color: tuple[int,int,int,int]) -> Image.Image:
    result=Image.new("RGBA",size,color)
    path.parent.mkdir(parents=True,exist_ok=True)
    result.save(path)
    return result


def make_export(root: Path, *, source: bool, target_only: bool) -> tuple[Path, Image.Image]:
    root.mkdir(parents=True)
    atlas=root/"UI-MasterAtlas"
    atlas.mkdir()
    canvas=Image.new("RGBA",(32,32),(0,0,0,0))
    crops=[]
    a=(2,2) if source else (10,10)
    b=(12,2) if source else (20,10)
    entries=[(SOURCE_KEY_A,a,(140,30,15,255)),
             (SOURCE_KEY_B,b,(25,70,135,255))]
    if target_only:
        entries.append((TARGET_ONLY,(2,20),(65,170,60,255)))
    for name,(x,y),color in entries:
        img=write_image(atlas/(name+".png"),(4,4),color)
        canvas.paste(img,(x,y))
        crops.append({"key":name,"file":name+".png","x":x,"y":y,
                      "width":4,"height":4,"baseline_pixels_sha256":digest(img)})
    index={"schema_version":1,"target_build_id":"source-test" if source else "target-test",
           "atlases":[{"sheet":SHEET,"sheet_width":32,"sheet_height":32,
                       "directory":atlas.name,"crops":crops}]}
    (root/"index.json").write_text(json.dumps(index),encoding="utf8")
    return root,canvas


@pytest.fixture
def case(tmp_path):
    source, sheet=make_export(tmp_path/"source-export",source=True,target_only=False)
    target,_=make_export(tmp_path/"target-export",source=False,target_only=True)
    store=tmp_path/"source-store"
    store.mkdir()
    for name,crop in [(SOURCE_KEY_A,(2,2,4,4)),(SOURCE_KEY_B,(12,2,4,4))]:
        xy,size=crop[:2],crop[2:]
        edited=Image.new("RGBA",size,(250,220,50,255) if name==SOURCE_KEY_A
                         else (80,240,245,255))
        sheet.paste(edited,xy)
    sheet_file=store/SHEET
    sheet.save(sheet_file)
    manifest={"schema_version":1,"origin":"derived",
              "source_export_index_sha256":port._sha256_file(source/"index.json"),
              "sheets":[{"file":SHEET,"width":32,"height":32,
                         "sha256":port._sha256_file(sheet_file)}]}
    (store/"store-manifest.json").write_text(json.dumps(manifest),encoding="utf8")
    return source,store,target


def target_bytes(target: Path) -> dict[str,bytes]:
    return {p.relative_to(target).as_posix():p.read_bytes()
            for p in target.rglob("*") if p.is_file()}


def test_successful_port_moves_only_changed_named_crops(case):
    source,store,target=case
    before=target_bytes(target)
    report=port.port_layout(source,store,target)
    after=target_bytes(target)
    assert report["ported_crop_count"]==2
    assert report["ported_crops_with_moved_geometry"]==2
    assert report["target_only_crop_count"]==1
    assert after["UI-MasterAtlas/"+TARGET_ONLY+".png"]==before[
        "UI-MasterAtlas/"+TARGET_ONLY+".png"]
    assert after["index.json"]==before["index.json"]
    assert after["UI-MasterAtlas/"+SOURCE_KEY_A+".png"]!=before[
        "UI-MasterAtlas/"+SOURCE_KEY_A+".png"]
    with Image.open(target/"UI-MasterAtlas"/(SOURCE_KEY_B+".png")) as b:
        assert b.getpixel((0,0))==(80,240,245,255)


def test_second_write_failure_must_restore_prior_target_crops(case,monkeypatch):
    source,store,target=case
    before=target_bytes(target)
    write=port._write_png_atomic
    calls=[]

    def fail_after_one(image,destination):
        calls.append(destination)
        if len(calls)==2:
            raise OSError("simulated second-file failure")
        write(image,destination)

    monkeypatch.setattr(port,"_write_png_atomic",fail_after_one)
    with pytest.raises(OSError,match="second-file"):
        port.port_layout(source,store,target)
    assert target_bytes(target)==before, (
        "A failed multi-crop port must never leave one crop from a newer layout")
    assert not (target/"layout-port-report.json").exists()


def test_report_failure_must_restore_previous_crops_and_report(case,monkeypatch):
    source,store,target=case
    report=target/"layout-port-report.json"
    report.write_bytes(b"previous audit report\n")
    before=target_bytes(target)
    real=port._write_png_atomic

    def selective_failure(image,destination):
        return real(image,destination)

    monkeypatch.setattr(port,"_write_png_atomic",selective_failure)
    original_write_text=Path.write_text

    def error_on_report(self,text,*a,**kw):
        if self.name=="layout-port-report.json":
            raise OSError("simulated report write failure")
        return original_write_text(self,text,*a,**kw)

    monkeypatch.setattr(Path,"write_text",error_on_report)
    with pytest.raises(OSError,match="report write"):
        port.port_layout(source,store,target)
    assert target_bytes(target)==before


@pytest.mark.parametrize("name",[
    "CON.png","NUL.txt","AUX.png","LPT1.txt","bad.","bad ","COM1.png",
    "x:y.png","foo\\bar.png","a/b.png"
])
def test_flat_name_rejects_reserved_and_nonportable_names(name):
    with pytest.raises(port.LayoutPortError,match="Unsicher"):
        port._flat_name(name,"Datei")


@pytest.mark.parametrize("bad",[True,False,1.6,0.5,"2.3"])
def test_metadata_dimensions_must_be_actual_integers(bad):
    with pytest.raises(port.LayoutPortError):
        port._positive_int(bad,"Testbreite")


def test_publication_failure_after_first_replace_rolls_back_bytes(case,monkeypatch):
    source,store,target=case
    before=target_bytes(target)
    publish=port.os.replace
    count=[0]

    def fail_second_publish(src,dst):
        if Path(dst).parent == target/"UI-MasterAtlas":
            count[0]+=1
            if count[0]==2:
                raise OSError("simulated second publication failure")
        return publish(src,dst)

    monkeypatch.setattr(port.os,"replace",fail_second_publish)
    with pytest.raises(OSError,match="second publication"):
        port.port_layout(source,store,target)
    assert target_bytes(target)==before


def test_publication_failure_at_report_rolls_back_all_crops(case,monkeypatch):
    source,store,target=case
    (target/"layout-port-report.json").write_text("prior record",encoding="utf8")
    before=target_bytes(target)
    publish=port.os.replace

    def fail_report_publish(src,dst):
        if Path(dst)==target/"layout-port-report.json":
            raise OSError("report publication failure")
        return publish(src,dst)

    monkeypatch.setattr(port.os,"replace",fail_report_publish)
    with pytest.raises(OSError,match="report publication"):
        port.port_layout(source,store,target)
    assert target_bytes(target)==before


def test_changed_target_during_staging_is_not_overwritten(case,monkeypatch):
    source,store,target=case
    other=target/"UI-MasterAtlas"/(SOURCE_KEY_A+".png")
    real_write=port._write_png_atomic
    count=[0]

    def concurrent_edit(image,destination):
        real_write(image,destination)
        count[0]+=1
        if count[0]==2:
            other.write_bytes(b"another user's later edit")

    monkeypatch.setattr(port,"_write_png_atomic",concurrent_edit)
    with pytest.raises(port.LayoutPortError,match="änderte"):
        port.port_layout(source,store,target)
    assert other.read_bytes()==b"another user's later edit"
    assert not (target/"layout-port-report.json").exists()


def test_preflight_bad_source_baseline_never_writes_target(case):
    source,store,target=case
    before=target_bytes(target)
    src=source/"UI-MasterAtlas"/(SOURCE_KEY_A+".png")
    write_image(src,(4,4),(1,2,3,4))
    with pytest.raises(port.LayoutPortError,match="Pin"):
        port.port_layout(source,store,target)
    assert target_bytes(target)==before


def test_duplicate_atlas_directory_rejected_even_if_sheet_differs(case):
    source,store,target=case
    before=target_bytes(target)
    doc=json.loads((source/"index.json").read_text("utf8"))
    second=dict(doc["atlases"][0])
    second["sheet"]="UI-Colour1Atlas.png"
    doc["atlases"].append(second)
    (source/"index.json").write_text(json.dumps(doc),encoding="utf8")
    with pytest.raises(port.LayoutPortError,match="doppelt"):
        port.port_layout(source,store,target)
    assert target_bytes(target)==before


def test_manipulated_target_index_reserved_names_rejected(case):
    source,store,target=case
    before=target_bytes(target)
    doc=json.loads((target/"index.json").read_text("utf8"))
    doc["atlases"][0]["crops"][0]["file"]="CON.png"
    (target/"index.json").write_text(json.dumps(doc),encoding="utf8")
    with pytest.raises(port.LayoutPortError,match="Unsicher"):
        port.port_layout(source,store,target)
    assert target_bytes(target)==before | {
        "index.json":(target/"index.json").read_bytes()
    }


def test_source_export_must_never_be_used_as_target(case):
    source,store,_target=case
    before=target_bytes(source)
    with pytest.raises(port.LayoutPortError,match="verschiedene Ordner"):
        port.port_layout(source,store,source)
    assert target_bytes(source)==before

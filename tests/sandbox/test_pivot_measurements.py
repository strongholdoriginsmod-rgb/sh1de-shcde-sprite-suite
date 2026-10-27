"""Zinnenlineal read-only pivot inspection and approval reports."""
from pathlib import Path
import json
import sys

import pytest
from PIL import Image

from stronghold_europe_de.pivot_measurements import (
    Measurement, PivotMeasurementError, load_measurements,
    review_measurements, render_comparison, save_review_report,
)


def _entry(name="anim_castle 002",old_y=1.10909091,up=18):
    return {
        "name":name,"gruppe":"anim_castle","nummer":2,
        "rechts":0,"hoch":up,"breite":333,"hoehe":165,
        "pivot_x":0.0,"pivot_y":old_y,
        "neu_pivot_x":0.0,"neu_pivot_y":old_y-up/165,
        "pixel_je_einheit":64.0,
    }


def _measurement(tmp_path,entries):
    original=tmp_path/"Zinnenlineal"/"zinnen-versatz.json"
    original.parent.mkdir(parents=True,exist_ok=True)
    original.write_text(json.dumps({
        "schema":"zinnenlineal.versatz.v1","erzeugt":"2026-09-04 11:18:01",
        "frames":entries,
    }),encoding="utf-8")
    return original


def _frame(tmp_path,source_side="geliefert",pivot_y=1.0,width=333):
    folder=tmp_path/"work"/"katalog"/source_side/"anim_castle"
    folder.mkdir(parents=True,exist_ok=True)
    pixels=Image.new("RGBA",(width,165),(74,130,160,255))
    Image.Image.save(pixels,folder/"anim_castle 002.png")
    (folder/"index.json").write_text(json.dumps({
        "group":"anim_castle",
        "frames":[{"name":"anim_castle 002",
                   "file":"anim_castle 002.png",
                   "width":width,"height":165,
                   "pivot_x":0.0,"pivot_y":pivot_y}],
    }),encoding="utf-8")
    return folder


def test_verified_csharp_measurement_is_already_in_delivered_index(tmp_path):
    input_path=_measurement(tmp_path,[_entry()])
    m=load_measurements(input_path)
    _frame(tmp_path,pivot_y=1.0)
    raw=input_path.read_bytes()
    reviews=review_measurements(m,tmp_path)
    assert len(reviews)==1
    assert reviews[0].status=="bereits_passend"
    assert reviews[0].side=="geliefert"
    assert reviews[0].measurement.up==18
    assert reviews[0].actual_pivot==(0.0,1.0)
    assert input_path.read_bytes()==raw
    image=render_comparison(reviews[0])
    assert image.size==(900,360)
    out=save_review_report(m,reviews,tmp_path)
    assert out.is_relative_to(tmp_path/"work"/"reports"/"pivot-review")
    result=json.loads(out.read_text(encoding="utf-8"))
    assert result["rows"][0]["status"]=="bereits_passend"
    assert "Nur Freigabevorschlag" in result["disclaimer"]
    assert save_review_report(m,reviews,tmp_path)==out
    assert not list(out.parent.glob("*.tmp"))


def test_current_pivot_needs_review_if_old_geometry_matches(tmp_path):
    original=_measurement(tmp_path,[_entry()])
    folder=_frame(tmp_path,pivot_y=1.10909091)
    before=(folder/"index.json").read_bytes()
    records=review_measurements(load_measurements(original),tmp_path)
    assert records[0].status=="pruefen"
    assert "Korrektur" in records[0].reason
    assert (folder/"index.json").read_bytes()==before


def test_unmatched_pivot_and_bad_size_issues_are_explicit(tmp_path):
    source=_measurement(tmp_path,[_entry()])
    _frame(tmp_path,pivot_y=.8)
    result=review_measurements(load_measurements(source),tmp_path)
    assert result[0].status=="referenz_abweichend"
    _frame(tmp_path,pivot_y=1.10909091,width=280)
    result=review_measurements(load_measurements(source),tmp_path)
    assert result[0].status=="geometrie_abweichend"


def test_missing_or_malicious_index_file_is_not_loaded(tmp_path):
    source=_measurement(tmp_path,[_entry()])
    result=review_measurements(load_measurements(source),tmp_path)
    assert result[0].status=="nicht_gefunden"
    folder=_frame(tmp_path)
    entry=json.loads((folder/"index.json").read_text(encoding="utf-8"))
    entry["frames"][0]["file"]="../../secret.png"
    (folder/"index.json").write_text(json.dumps(entry),encoding="utf-8")
    assert review_measurements(load_measurements(source),tmp_path)[0].status=="nicht_gefunden"


@pytest.mark.parametrize("field,value",[
    ("nummer",999),("gruppe","../hack"),("breite",0),("hoch",12.5),
    ("pivot_y","1.0"),("neu_pivot_y",1.9),("rechts",True),
    ("pixel_je_einheit",-1),("name","../../etc/file"),
])
def test_malformed_measurement_rejected(tmp_path,field,value):
    rec=_entry()
    rec[field]=value
    p=_measurement(tmp_path,[rec])
    with pytest.raises(PivotMeasurementError):
        load_measurements(p)


def test_duplicate_rows_wrong_schema_and_size_limit(tmp_path):
    p=_measurement(tmp_path,[_entry(),_entry()])
    with pytest.raises(PivotMeasurementError):
        load_measurements(p)
    p.write_text('{"schema":"unknown","frames":[]}',encoding="utf-8")
    with pytest.raises(PivotMeasurementError):
        load_measurements(p)
    p.write_bytes(b"x"*(2*1024*1024+1))
    with pytest.raises(PivotMeasurementError):
        load_measurements(p)


def test_comparison_renders_distinct_sprite_positions_at_shared_anchor(tmp_path):
    p=_measurement(tmp_path,[_entry()])
    _frame(tmp_path,pivot_y=1.10909091)
    row=review_measurements(load_measurements(p),tmp_path)[0]
    # Without the shift, the actual sprite starts 18px below the proposed one.
    image=render_comparison(row,width=1000,height=420)
    assert image.size==(1000,420)
    assert image.getpixel((260,230)) != image.getpixel((760,230))


def test_tk_pivot_review_load_and_navigation(tmp_path,monkeypatch):
    import tkinter as tk
    import pytest
    from tkinter import messagebox
    from pathlib import Path
    import sys
    tools_path=str(Path(__file__).resolve().parents[2]/"tools")
    if tools_path not in sys.path:
        sys.path.insert(0,tools_path)
    from pivot_review_gui import PivotReviewWindow

    measured=_measurement(tmp_path,[_entry()])
    _frame(tmp_path,pivot_y=1.0)
    try:
        root=tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"No Tk desktop: {exc}")
    root.withdraw()
    catalog=[]
    sandbox=[]
    root.show_in_catalog=lambda group,name:catalog.append((group,name))
    root.show_in_sandbox=lambda group,number:sandbox.append((group,number))
    monkeypatch.setattr(messagebox,"showinfo",lambda *args,**kwargs:None)
    try:
        window=PivotReviewWindow(root,tmp_path)
        assert window.load(measured)
        assert window.measurement_file is not None
        assert len(window.reviews)==1
        assert window.current().status=="bereits_passend"
        assert window._preview_image is not None
        window.show_in_catalog()
        window.show_in_sandbox()
        assert catalog==[("anim_castle","anim_castle 002")]
        assert sandbox==[("anim_castle",2)]
        window.export_report()
        assert (tmp_path/"work"/"reports"/"pivot-review").is_dir()
        assert "Prüfbericht gespeichert" in window.status.get()
        window.destroy()
    finally:
        root.destroy()

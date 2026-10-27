"""Human pivot decisions: source-bound reports, never automatic writes."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import pytest
from PIL import Image

from stronghold_europe_de.pivot_measurements import (
    PivotMeasurementError, load_measurements, review_measurements,
)
from stronghold_europe_de.pivot_approvals import (
    APPROVAL_SCHEMA, PivotDecision, can_approve, save_approval_report,
)


def _measure(tmp_path):
    path=tmp_path/"Zinnenlineal"/"zinnen-versatz.json"
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps({"schema":"zinnenlineal.versatz.v1","frames":[{
        "name":"anim_castle 002","gruppe":"anim_castle","nummer":2,
        "breite":333,"hoehe":165,"rechts":0,"hoch":18,
        "pivot_x":0.0,"pivot_y":1.10909091,
        "neu_pivot_x":0.0,"neu_pivot_y":1.0,
    }]}),encoding="utf-8")
    return path


def _source(tmp_path,side="geliefert",pivot=1.10909091):
    folder=tmp_path/"work"/"katalog"/side/"anim_castle"
    folder.mkdir(parents=True,exist_ok=True)
    picture=folder/"anim_castle 002.png"
    Image.new("RGBA",(333,165),(45,91,180,240)).save(picture)
    index=folder/"index.json"
    index.write_text(json.dumps({"group":"anim_castle","frames":[{
        "name":"anim_castle 002","file":"anim_castle 002.png",
        "width":333,"height":165,"pivot_x":0,"pivot_y":pivot,
    }]}),encoding="utf-8")
    return index,picture


def _decision(action="freigegeben"):
    return PivotDecision(action,recorded_at="2026-10-11T18:00:00+00:00")


def _view(tmp_path):
    measure=load_measurements(tmp_path/"Zinnenlineal"/"zinnen-versatz.json")
    return measure,review_measurements(measure,tmp_path)


def test_explicit_approval_creates_only_provenance_bound_report(tmp_path):
    measured=_measure(tmp_path)
    index,picture=_source(tmp_path)
    mf,reviews=_view(tmp_path)
    assert reviews[0].status=="pruefen"
    assert can_approve(reviews[0])
    assert reviews[0].index_sha256 and reviews[0].pixel_sha256
    before={p:p.read_bytes() for p in (measured,index,picture)}
    decisions={"anim_castle 002":_decision()}
    target=save_approval_report(mf,reviews,tmp_path,decisions)
    assert target.parent==tmp_path/"work"/"reports"/"pivot-approval"
    payload=json.loads(target.read_text(encoding="utf-8"))
    assert payload["schema"]==APPROVAL_SCHEMA
    assert payload["approved_count"]==1 and payload["rejected_count"]==0
    row=payload["rows"][0]
    assert row["decision"]=="freigegeben"
    assert row["source"]=="geliefert"
    assert row["source_image_sha256"]==reviews[0].pixel_sha256
    assert row["source_index_sha256"]==reviews[0].index_sha256
    assert row["measured_new"]==[0.0,1.0]
    assert "keine Freigabe zum direkten" in payload["disclaimer"]
    assert save_approval_report(mf,reviews,tmp_path,decisions)==target
    assert sorted(target.parent.iterdir())==[target]
    assert all(p.read_bytes()==content for p,content in before.items())


def test_already_correct_or_non_shipped_sprite_cannot_be_approved(tmp_path):
    _measure(tmp_path)
    _source(tmp_path,pivot=1.0)
    mf,rows=_view(tmp_path)
    assert rows[0].status=="bereits_passend"
    assert not can_approve(rows[0])
    with pytest.raises(PivotMeasurementError,match="keine Freigabe"):
        save_approval_report(mf,rows,tmp_path,{"anim_castle 002":_decision()})
    assert not (tmp_path/"work"/"reports"/"pivot-approval").exists()

    (tmp_path/"work"/"katalog"/"geliefert"/"anim_castle"/"index.json").unlink()
    _source(tmp_path,"crusader")
    mf,rows=_view(tmp_path)
    assert rows[0].side=="crusader"
    assert rows[0].status=="pruefen"
    assert not can_approve(rows[0])
    with pytest.raises(PivotMeasurementError,match="ausgelieferten"):
        save_approval_report(mf,rows,tmp_path,{"anim_castle 002":_decision()})


@pytest.mark.parametrize("change",["index","png","measure"])
def test_export_detects_changed_source_without_writing(tmp_path,change):
    measured=_measure(tmp_path)
    index,picture=_source(tmp_path)
    mf,rows=_view(tmp_path)
    if change=="index":
        original=index.read_text(encoding="utf-8")
        index.write_text(original+"\n",encoding="utf-8")
    elif change=="png":
        Image.new("RGBA",(333,165),(60,91,180,240)).save(picture)
    else:
        measured.write_bytes(measured.read_bytes()+b" ")
    with pytest.raises(PivotMeasurementError,match="geändert"):
        save_approval_report(mf,rows,tmp_path,{"anim_castle 002":_decision()})
    assert not (tmp_path/"work"/"reports"/"pivot-approval").exists()


def test_rejected_decisions_and_unreviewed_sprites_are_not_approved(tmp_path):
    _measure(tmp_path)
    _source(tmp_path)
    mf,rows=_view(tmp_path)
    target=save_approval_report(
        mf,rows,tmp_path,{"anim_castle 002":_decision("abgelehnt")}
    )
    content=json.loads(target.read_text(encoding="utf-8"))
    assert content["rows"][0]["decision"]=="abgelehnt"
    assert content["approved_count"]==0 and content["rejected_count"]==1


@pytest.mark.parametrize("decision",[
    PivotDecision("freigegeben",recorded_at="2026-10-11"),
    PivotDecision("unknown",recorded_at="2026-10-11T18:00:00+00:00"),
    PivotDecision("freigegeben",note="x"*401,recorded_at="2026-10-11T18:00:00+00:00"),
])
def test_invalid_decision_is_rejected(tmp_path,decision):
    _measure(tmp_path)
    _source(tmp_path)
    mf,rows=_view(tmp_path)
    with pytest.raises(PivotMeasurementError):
        save_approval_report(mf,rows,tmp_path,{"anim_castle 002":decision})


def test_duplicate_frame_index_is_not_ambiguous_approval_source(tmp_path):
    _measure(tmp_path)
    index,_=_source(tmp_path)
    document=json.loads(index.read_text(encoding="utf-8"))
    document["frames"].append(document["frames"][0].copy())
    index.write_text(json.dumps(document),encoding="utf-8")
    _,rows=_view(tmp_path)
    assert rows[0].status=="nicht_gefunden"
    assert not can_approve(rows[0])


def test_gui_requires_confirmation_and_resets_decisions_on_reload(tmp_path,monkeypatch):
    import tkinter as tk
    from tkinter import messagebox
    tools=str(Path(__file__).resolve().parents[2]/"tools")
    if tools not in sys.path:
        sys.path.insert(0,tools)
    from pivot_review_gui import PivotReviewWindow
    path=_measure(tmp_path)
    _source(tmp_path)
    try:
        root=tk.Tk()
    except tk.TclError as exc:
        pytest.skip(str(exc))
    root.withdraw()
    root.show_in_catalog=lambda *args:None
    root.show_in_sandbox=lambda *args:None
    confirmations=[]
    infos=[]
    monkeypatch.setattr(messagebox,"askyesno",lambda *args,**kwargs:confirmations.append(kwargs) or True)
    monkeypatch.setattr(messagebox,"showinfo",lambda *args,**kwargs:infos.append(args))
    try:
        window=PivotReviewWindow(root,tmp_path)
        assert window.load(path)
        assert str(window.approve["state"])=="normal"
        assert str(window.export_decision["state"])=="disabled"
        window.mark_approved()
        assert len(confirmations)==1 and confirmations[0]["default"]=="no"
        assert window.decisions["anim_castle 002"].action=="freigegeben"
        assert window.table.set("0","decision")=="Freigegeben"
        window.export_decisions()
        reports=list((tmp_path/"work"/"reports"/"pivot-approval").glob("*.json"))
        assert len(reports)==1
        assert infos
        window.clear_decision()
        assert not window.decisions
        assert str(window.export_decision["state"])=="disabled"
        window.mark_rejected()
        assert window.decisions["anim_castle 002"].action=="abgelehnt"
        assert window.load(path)
        assert not window.decisions
        window.destroy()
    finally:
        root.destroy()

def test_mixed_batch_never_reapproves_already_correct_frame(tmp_path):
    measured=_measure(tmp_path)
    index,_=_source(tmp_path,pivot=1.0)
    measurement=json.loads(measured.read_text(encoding="utf-8"))
    second=dict(measurement["frames"][0],name="anim_castle 003",nummer=3)
    measurement["frames"].append(second)
    measured.write_text(json.dumps(measurement),encoding="utf-8")
    source=json.loads(index.read_text(encoding="utf-8"))
    frame=dict(source["frames"][0],name="anim_castle 003",
               file="anim_castle 003.png",pivot_y=1.10909091)
    source["frames"].append(frame)
    index.write_text(json.dumps(source),encoding="utf-8")
    Image.new("RGBA",(333,165),(83,44,112,255)).save(index.parent/"anim_castle 003.png")

    mf,rows=_view(tmp_path)
    assert [r.status for r in rows]==["bereits_passend","pruefen"]
    assert not can_approve(rows[0]) and can_approve(rows[1])
    report=save_approval_report(mf,rows,tmp_path,{"anim_castle 003":_decision()})
    result=json.loads(report.read_text(encoding="utf-8"))
    assert [r["decision"] for r in result["rows"]]==["keine_aenderung","freigegeben"]
    assert result["approved_count"]==1
    assert result["rows"][0]["current_pivot"]==[0.0,1.0]

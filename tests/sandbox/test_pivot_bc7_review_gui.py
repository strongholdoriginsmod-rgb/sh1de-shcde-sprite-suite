"""The Zinnenlineal review window checks published BC7, without writes."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import time
import tkinter as tk
from tkinter import messagebox

from PIL import Image
import pytest

PROJECT=Path(__file__).resolve().parents[2]
if str(PROJECT/"tools") not in sys.path:
    sys.path.insert(0,str(PROJECT/"tools"))


def _sources(root,old_y=1.10909091):
    path=root/"Zinnenlineal"/"zinnen-versatz.json"
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps({
        "schema":"zinnenlineal.versatz.v1",
        "frames":[{
            "name":"anim_castle 002","gruppe":"anim_castle","nummer":2,
            "breite":333,"hoehe":165,"rechts":0,"hoch":18,
            "pivot_x":0.0,"pivot_y":1.10909091,
            "neu_pivot_x":0.0,"neu_pivot_y":1.0,
        }],
    }),encoding="utf-8")
    folder=root/"work"/"katalog"/"geliefert"/"anim_castle"
    folder.mkdir(parents=True,exist_ok=True)
    image=folder/"anim_castle 002.png"
    Image.new("RGBA",(333,165),(50,70,100,255)).save(image)
    index=folder/"index.json"
    index.write_text(json.dumps({"group":"anim_castle","frames":[{
        "name":"anim_castle 002","file":image.name,
        "width":333,"height":165,"pivot_x":0.0,"pivot_y":old_y,
    }]}),encoding="utf-8")
    return path,index,image


def _pump(root,window):
    # A full Tk/Qt regression may leave substantial event-loop and decoding
    # work queued. This is a real background worker, not a fixed 4s operation.
    deadline=time.monotonic()+15
    while window._bc7_pending is not None and time.monotonic()<deadline:
        root.update()
        time.sleep(.02)
    assert window._bc7_pending is None


@pytest.mark.parametrize("status,expected_approval",[
    ("bereits_im_bc7","disabled"),
    ("bc7_neubau_erforderlich","normal"),
])
def test_review_bc7_check_is_async_and_protects_approved_actions(
    tmp_path,monkeypatch,status,expected_approval
):
    import stronghold_europe_de.pivot_bc7_cache as api
    from pivot_review_gui import PivotReviewWindow
    measured,index,image=_sources(tmp_path)
    initial={path:path.read_bytes() for path in (measured,index,image)}
    try:
        root=tk.Tk()
    except tk.TclError as exc:
        pytest.skip(str(exc))
    root.withdraw()
    root.show_in_catalog=lambda *args:None
    root.show_in_sandbox=lambda *args:None
    warnings=[]
    monkeypatch.setattr(messagebox,"showwarning",lambda *args,**kwargs:warnings.append(args))
    calls=[]
    def fake_audit(root_path,profile,measurement):
        calls.append((root_path,profile,measurement.name))
        time.sleep(.03)
        return {
            "status":status,
            "bc7_pivot":[0.,1.] if status=="bereits_im_bc7" else [0.,1.10909091],
            "cache_key":"f"*64,
            "cache_verified":True,
        }
    monkeypatch.setattr(api,"audit_published_measurement",fake_audit)
    try:
        window=PivotReviewWindow(root,tmp_path)
        assert window.load(measured)
        assert window.current().status=="pruefen"
        assert str(window.bc7_check["state"])=="normal"
        assert str(window.approve["state"])=="normal"
        window.inspect_bc7()
        assert str(window.bc7_check["state"])=="disabled"
        window.inspect_bc7()  # never start a second simultaneous audit
        _pump(root,window)
        assert len(calls)==1
        assert calls[0][1:] == ("sprite-suite-world-bc7-v2","anim_castle 002")
        assert str(window.approve["state"])==expected_approval
        assert window._bc7_results["anim_castle 002"]["status"]==status
        assert "Publizierter BC7-Atlas" in window.detail.get()
        assert not warnings
        if status=="bereits_im_bc7":
            monkeypatch.setattr(
                messagebox,"askyesno",
                lambda *a,**kw:pytest.fail("Bereits im BC7 darf nie erneut freigegeben werden")
            )
            window.mark_approved()  # programmatic bypass must also be blocked
            assert not window.decisions
            assert warnings and warnings[0][0]=="Bereits im BC7 korrigiert"
        assert all(path.read_bytes()==payload for path,payload in initial.items())
        assert window.load(measured)
        assert not window._bc7_results  # new preview invalidates old evidence
        assert str(window.approve["state"])=="normal"
        window.destroy()
    finally:
        root.destroy()


def test_changed_sprite_during_gui_audit_is_rejected(tmp_path,monkeypatch):
    import stronghold_europe_de.pivot_bc7_cache as api
    from pivot_review_gui import PivotReviewWindow
    measured,index,image=_sources(tmp_path)
    try:
        root=tk.Tk()
    except tk.TclError as exc:
        pytest.skip(str(exc))
    root.withdraw()
    root.show_in_catalog=lambda *args:None
    root.show_in_sandbox=lambda *args:None
    warnings=[]
    monkeypatch.setattr(messagebox,"showwarning",lambda *args,**kwargs:warnings.append(args))
    def changed_audit(*args):
        # Stand is altered between first and second original source checks.
        index.write_bytes(index.read_bytes()+b"\n ")
        return {"status":"bereits_im_bc7","bc7_pivot":[0.,1.],"cache_key":"a"*64}
    monkeypatch.setattr(api,"audit_published_measurement",changed_audit)
    try:
        window=PivotReviewWindow(root,tmp_path)
        assert window.load(measured)
        window.inspect_bc7()
        _pump(root,window)
        assert warnings
        assert not window._bc7_results
        assert str(window.approve["state"])=="normal"
        window.destroy()
    finally:
        root.destroy()

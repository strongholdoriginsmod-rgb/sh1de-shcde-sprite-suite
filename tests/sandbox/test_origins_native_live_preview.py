"""Native game-pixel viewer: provenance, stale PID and real Tk frame handling."""
from __future__ import annotations
from pathlib import Path
import json
import sys

from PIL import Image
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/"tools"),str(ROOT/"src")]
import suite_noesis_native_live_preview as live


def _write_status(folder:Path,filename:Path|None,kind:str|None,**changes):
    default={
        "schema":"sprite-suite.origins-native-live.v1",
        "game_process_pid":314159,
        "native_plugin_awake":True,
        "runtime_game_abi_verified":True,
        "native_menu_hook_registered":True,
        "native_map_hooks_registered":True,
        "native_noesis_views_observed":1,
        "native_frame_count":1,
        "native_last_frame":str(filename) if filename else None,
        "frame_source":kind,
        "pixel_exact_native_noesis_texture":kind=="native-noesis-rendertexture",
        "pixel_exact_composited_game_screenshot":kind=="unity-game-composited-screen",
        "active_map":"Antioch.map",
        "map_load_event_count":1,
        "map_unload_event_count":0,
        "active_season_route":"spritesuite-winter",
        "last_error":"",
    }
    default.update(changes)
    folder.mkdir(parents=True,exist_ok=True)
    (folder/"live-status.json").write_text(json.dumps(default),encoding="utf8")
    return default


def test_no_live_telemetry_is_not_pretended(tmp_path):
    frame,status=live.read_live_frame(tmp_path/"doesnotexist")
    assert frame is None
    assert status["state"]=="not_running"


@pytest.mark.parametrize("kind,isolated",[
    ("native-noesis-rendertexture",True),
    ("unity-game-composited-screen",False),
])
def test_real_pixels_are_read_without_fake_noesis_claim(tmp_path,monkeypatch,kind,isolated):
    folder=tmp_path/"private"
    folder.mkdir()
    path=folder/"native-frame-00000001.png"
    Image.new("RGBA",(180,110),(20,120,90,255)).save(path)
    _write_status(folder,path,kind)
    monkeypatch.setattr(live,"game_process_is_live",lambda pid:False)
    proof,status=live.read_live_frame(folder)
    assert proof is not None
    assert proof.size==(180,110)
    assert proof.pixel_exact_native_noesis is isolated
    assert proof.pixel_exact_composited_game is not isolated
    assert proof.menu_hook is True and proof.map_hook is True
    assert status["source_game_process_alive"] is False
    assert status["state"]=="captured"
    assert proof.path.read_bytes()==path.read_bytes()


def test_telemetry_cannot_inject_arbitrary_image_path(tmp_path):
    folder=tmp_path/"private";folder.mkdir()
    outside=tmp_path/"other.png"
    Image.new("RGBA",(40,30)).save(outside)
    _write_status(folder,outside,"native-noesis-rendertexture")
    with pytest.raises(live.LiveFrameError,match="unchanged local PNG"):
        live.read_live_frame(folder)


def test_image_source_provenance_must_match_flags(tmp_path):
    folder=tmp_path/"private";folder.mkdir()
    file=folder/"native-frame-1.png"
    Image.new("RGBA",(80,50)).save(file)
    _write_status(folder,file,"unity-game-composited-screen",
                   pixel_exact_native_noesis_texture=True)
    with pytest.raises(live.LiveFrameError,match="provenance"):
        live.read_live_frame(folder)


def test_absent_png_does_not_claim_native_pixels(tmp_path):
    folder=tmp_path/"private";folder.mkdir()
    _write_status(folder,None,None,
                  native_frame_count=0,native_noesis_views_observed=0)
    frame,status=live.read_live_frame(folder)
    assert frame is None and status["state"]=="waiting"


def test_native_viewer_gui_shows_verified_bitmap_and_reference(tmp_path,monkeypatch):
    monkeypatch.setattr(live,"game_process_is_live",lambda _pid:True)
    import tkinter as tk
    from suite_tcl_runtime import create_tk_root
    folder=tmp_path/"private";folder.mkdir()
    source=folder/"native-frame-7.png"
    Image.new("RGBA",(320,180),(40,90,140,255)).save(source)
    _write_status(folder,source,"native-noesis-rendertexture")
    references=[]
    root=create_tk_root()
    root.withdraw()
    view=None
    try:
        view=live.NativeNoesisLivePreview(
            root,status_dir=folder,auto_poll=False,
            on_reference=lambda path:references.append(path))
        root.update_idletasks()
        assert "Noesis" in view.native_info.get()
        assert view.fit.get() is False
        assert view._frame is not None
        assert view._frame.size==(320,180)
        assert view.use_reference()==source
        assert references==[source]
        assert view._photo is not None
    finally:
        if view is not None:view.close()
        root.destroy()


def test_viewer_does_not_create_fake_frame_when_game_not_running(tmp_path):
    from suite_tcl_runtime import create_tk_root
    root=create_tk_root();root.withdraw()
    viewer=None
    try:
        viewer=live.NativeNoesisLivePreview(
            root,status_dir=tmp_path/"empty",auto_poll=False)
        assert viewer._frame is None
        assert viewer._photo is None
        assert viewer.use_reference() is None
    finally:
        if viewer is not None:viewer.close()
        root.destroy()



def test_stale_native_png_never_appears_as_an_active_live_preview(
    tmp_path,monkeypatch
):
    from suite_tcl_runtime import create_tk_root
    monkeypatch.setattr(live,"game_process_is_live",lambda _pid:False)
    folder=tmp_path/"private";folder.mkdir()
    source=folder/"native-frame-00000015.png"
    Image.new("RGBA",(192,108),(39,79,128,255)).save(source)
    _write_status(folder,source,"native-noesis-rendertexture")
    root=create_tk_root();root.withdraw()
    window=None
    try:
        window=live.NativeNoesisLivePreview(root,status_dir=folder,
                                            auto_poll=False)
        assert window._frame is None
        assert window._photo is None
        assert "historisch" in window.native_info.get()
        assert window.use_reference() is None
    finally:
        if window is not None:window.close()
        root.destroy()

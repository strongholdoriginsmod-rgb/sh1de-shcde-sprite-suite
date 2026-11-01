"""Real Tk UI integrates screenshot comparison without claiming native render."""
from pathlib import Path
import sys
import tkinter as tk

import pytest
from PIL import Image

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/"tools"),str(ROOT/"src")]
import hud_menu_workspace as work
import suite_origins_visual_editor as gui
from suite_origins_visual_editor import OriginsVisualEditor


@pytest.fixture
def app(tmp_path,monkeypatch):
    suite=tmp_path/"suite";(suite/"work").mkdir(parents=True)
    monkeypatch.setattr(work,"ROOT",suite)
    monkeypatch.setattr(work,"WORK",suite/"work")
    original=tmp_path/"FrontendMenus.xaml"
    original.write_text('''<UserControl
      xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation">
      <Grid Name="Main"><Button Name="RunButton" Content="Play"/></Grid>
      </UserControl>''',encoding="utf8")
    from suite_tcl_runtime import create_tk_root
    root=create_tk_root()
    root.withdraw()
    window=OriginsVisualEditor(root,project=suite/"work"/"visual",source=original)
    root.update_idletasks()
    try:yield window,root,monkeypatch,tmp_path
    finally:
        root.destroy()


def test_exact_pixel_diff_display_and_report_in_original_visual_editor(app):
    view,root,monkeypatch,tmp=app
    first=tmp/"game-before.png";second=tmp/"game-after.png"
    image=Image.new("RGBA",(160,100),(30,70,90,255))
    image.save(first)
    image.putpixel((4,5),(242,10,10,255))
    image.save(second)
    values=iter([str(first),str(second)])
    monkeypatch.setattr(gui.filedialog,"askopenfilename",lambda **k: next(values))
    result=view.compare_game_frames()
    assert result is not None
    assert result["changed_pixels"]==1
    assert not result["game_render_parity_attested"]
    assert Path(result["heatmap"]).is_file()
    assert Path(result["report"]).is_file()
    assert "Pixelvergleich" in view.status.get()
    assert first.read_bytes()!=second.read_bytes()


def test_pixel_compare_rejects_different_resolutions_without_false_success(app):
    view,root,monkeypatch,tmp=app
    a=tmp/"one.png";b=tmp/"two.png"
    Image.new("RGBA",(160,90)).save(a)
    Image.new("RGBA",(164,90)).save(b)
    monkeypatch.setattr(gui.filedialog,"askopenfilename",
                        lambda **_k: str(a) if "Originaler" in _k.get("title","") else str(b))
    errors=[]
    monkeypatch.setattr(gui.messagebox,"showerror",
                        lambda title,msg,**kw: errors.append((title,msg)))
    assert view.compare_game_frames() is None
    assert errors

"""Real Windows/Tk original-menu design, drag and patch packaging regression."""
from pathlib import Path
import json
import sys
import tkinter as tk
from types import SimpleNamespace
from zipfile import ZipFile

from PIL import Image
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/"tools"),str(ROOT/"src")]
import hud_menu_workspace as work
import se_asset_package as pack
from origins_visual_geometry import projected_geometry
from origins_visual_document import VisualXamlDocument, PRES
from suite_origins_visual_editor import OriginsVisualEditor


@pytest.fixture(scope="module")
def tk_root():
    try:
        from suite_tcl_runtime import create_tk_root
        app=create_tk_root()
        app.withdraw()
    except tk.TclError as error:
        pytest.skip("Windows Tk unavailable: "+str(error))
    yield app
    app.destroy()


@pytest.fixture
def original(tmp_path,monkeypatch):
    suite=tmp_path/"suite";(suite/"work").mkdir(parents=True)
    monkeypatch.setattr(work,"ROOT",suite)
    monkeypatch.setattr(work,"WORK",suite/"work")
    monkeypatch.setattr(pack,"ROOT",suite)
    monkeypatch.setattr(pack,"WORK",suite/"work")
    monkeypatch.setattr(pack,"OUT",suite/"work"/"se-asset-mods")
    xaml=suite/"source/Assets/GUI/XAML/FrontendMenus.xaml"
    xaml.parent.mkdir(parents=True)
    images=xaml.parent.parent/"Images";images.mkdir()
    Image.new("RGBA",(96,52),(90,160,210,255)).save(images/"background.png")
    xaml.write_text('''<?xml version="1.0"?>
<UserControl xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
 xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
 xmlns:local="clr-namespace:CrusaderDE">
 <Grid Name="MenuRoot" Width="1920" Height="1080">
  <Grid.RowDefinitions><RowDefinition Height="200"/>
    <RowDefinition Height="*"/></Grid.RowDefinitions>
  <Image Name="BG" Source="../Images/background.png"
    Width="380" Height="180" Grid.Row="0" />
  <Canvas Name="MenuCanvas" Grid.Row="1">
   <Button Name="MenuBtn" Canvas.Left="180" Canvas.Top="90"
    Width="290" Height="80" Content="Kampagne"
    local:PropEx.TextCentre="Kampagne"
    Command="{Binding ButtonMainMenuCommand}"
    CommandParameter="Multiplayer"/>
  </Canvas>
 </Grid>
</UserControl>''',encoding="utf8")
    return xaml,suite/"work"/"mein-menu"


def test_nested_original_grid_canvas_geometries(original):
    source,project=original
    doc=VisualXamlDocument(source)
    layout={b.name:b for b in projected_geometry(doc)}
    assert layout["MenuCanvas"].y>=190
    assert layout["MenuBtn"].x>=180
    assert layout["MenuBtn"].y>=290
    assert layout["BG"].w==380
    assert len(doc.outline())>7


def test_original_layout_gui_can_edit_controls_and_package_mod(
    tk_root,original,monkeypatch,
):
    source,project=original
    before=source.read_bytes()
    gui=OriginsVisualEditor(tk_root,project=project,source=source)
    try:
        tk_root.update()
        item=next(e for e in gui.doc.outline() if e.label=="MenuBtn")
        assert gui.tree.exists("p"+"_".join(map(str,item.path)))
        gui.select_path(item.path)
        gui.attribute.set("CommandParameter")
        gui.attr_value.set("MeineFreiEinstellbareAktion")
        gui.apply_attribute()
        assert gui.doc.attributes(item.path)["CommandParameter"]=="MeineFreiEinstellbareAktion"
        gui.tag_value.set("TextBlock")
        gui.name_value.set("MeinTitel")
        canvas=next(e for e in gui.doc.outline() if e.label=="MenuCanvas")
        gui.select_path(canvas.path)
        gui.add_element()
        assert any(e.label=="MeinTitel" for e in gui.doc.outline())
        gui.undo();gui.redo()
        gui.redraw()
        assert gui._image_refs, "Original bitmap should be shown on design canvas"
        assert item.path in gui._boxes
        # Drag the selected button in XAML units using a real Tk Canvas path.
        gui.select_path(item.path)
        box=gui._boxes[item.path]
        x,y,w,h=box
        scale=gui._world_scale
        gui.canvas_press(SimpleNamespace(x=int(x+15),y=int(y+10)))
        gui.canvas_release(SimpleNamespace(x=int(x+15+40*scale),
                                            y=int(y+10+20*scale)))
        after=gui.doc.attributes(item.path)
        assert "Canvas.Left" in after
        assert float(after["Canvas.Left"])>=180
        gui.save()
        target=project/"Patches/Assets/GUI/XAML/FrontendMenus.xaml"
        assert target.is_file()
        assert pack._check_xml(target,patch=True) is None
        first=target.read_bytes()
        assert b"MeineFreiEinstellbareAktion" in first
        assert source.read_bytes()==before
        from origins_visual_document import VisualXamlDocument
        roots=list((project.parent/".origins-visual-revisions").rglob(
                    "rev-0001/edited.xaml"))
        assert len(roots)==1
        reloaded=VisualXamlDocument.reopen(roots[0].parent)
        reloaded.edit(item.path,"Content","Zweiter Entwurf")
        output=reloaded.save_revision(project,overwrite_existing=True)
        assert output["published"]
        assert target.read_bytes()!=first
        artifact=pack.build(project,"meinfreiesmenu",name="Meine freien Seiten",
                            author="QA")
        with ZipFile(artifact["zip"]) as z:
            asset="BepInEx/plugins/meinfreiesmenu/Patches/Assets/GUI/XAML/FrontendMenus.xaml"
            assert asset in z.namelist()
            assert b"Zweiter Entwurf" in z.read(asset)
        assert artifact["runtime_dll"] is False
        assert source.read_bytes()==before
    finally:
        gui.destroy()

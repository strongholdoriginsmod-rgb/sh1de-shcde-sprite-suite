"""Real Windows Tk UI tests: editing original Noesis layout and packaging."""
from pathlib import Path
from types import SimpleNamespace
import sys
import tkinter as tk

import pytest
from PIL import Image

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"tools"))
import hud_menu_workspace as work
import se_asset_package as package
from origins_visual_document import VisualXamlDocument,PRES
from suite_origins_visual_editor import OriginsVisualEditor


@pytest.fixture(scope="module")
def ui_root():
    try:
        from suite_tcl_runtime import create_tk_root
        root=create_tk_root()
        root.withdraw()
    except tk.TclError as err:
        pytest.skip("Native Tk unavailable: "+str(err))
    try:yield root
    finally:root.destroy()


@pytest.fixture
def gui(tmp_path,monkeypatch,ui_root):
    suite=tmp_path/"suite"
    (suite/"work").mkdir(parents=True)
    monkeypatch.setattr(work,"ROOT",suite)
    monkeypatch.setattr(work,"WORK",suite/"work")
    monkeypatch.setattr(package,"ROOT",suite)
    monkeypatch.setattr(package,"WORK",suite/"work")
    monkeypatch.setattr(package,"OUT",suite/"work"/"se-asset-mods")
    resource=tmp_path/"Assets"/"GUI"
    (resource/"XAML").mkdir(parents=True)
    (resource/"Images").mkdir()
    Image.new("RGB",(150,70),"#3b7fa5").save(resource/"Images"/"MenuBack.png")
    source=resource/"XAML"/"FrontendMenus.xaml"
    source.write_text('''<UserControl xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml">
  <Grid Name="OriginalWindow" Width="1920" Height="1080">
   <Image Name="Background" Source="../Images/MenuBack.png" Width="300"
          Height="140" HorizontalAlignment="Left" VerticalAlignment="Top" />
   <Button Name="OriginalButton" Width="300" Height="90"
     Margin="450,450,0,0" HorizontalAlignment="Left" VerticalAlignment="Top"
     Content="Ursprungsaktion" Command="{Binding ButtonMainMenuCommand}"
     CommandParameter="Multiplayer" />
   <Grid Name="DialogPage" Margin="700,200,0,0" Width="500" Height="350"
         HorizontalAlignment="Left" VerticalAlignment="Top">
     <TextBlock Text="Wählbare Menüs" Margin="40,40,0,0" />
   </Grid>
  </Grid>
</UserControl>''',encoding="utf8")
    window=OriginsVisualEditor(ui_root,project=suite/"work"/"meine-menues",
                               source=source)
    window.update_idletasks()
    try:yield window,source,suite/"work"/"meine-menues",monkeypatch
    finally:window.destroy()


def get_path(window,name):
    return next(x.path for x in window.doc.outline() if x.label==name)


def test_complete_original_hierarchy_image_background_and_free_properties(gui):
    win,source,project,monkeypatch=gui
    assert win.tree.exists("root")
    assert win.tree.exists("p0_1")
    assert win._image_refs, "actual source image should be previewed"
    assert "DialogPage" in win.scope_combo.cget("values")
    button=get_path(win,"OriginalButton")
    win.select_path(button)
    win.attribute.set("CommandParameter")
    win.attr_value.set("MeinKomplettNeuerBefehl")
    win.apply_attribute()
    assert win.doc.attributes(button)["CommandParameter"]=="MeinKomplettNeuerBefehl"
    win.attribute.set("MouseEnter")
    win.attr_value.set("MeineHoverAction")
    win.apply_attribute()
    win.attribute.set("Background")
    win.attr_value.set("#FF663399")
    win.apply_attribute()
    assert win.doc.attributes(button)["Background"]=="#FF663399"
    assert "MeinKomplettNeuerBefehl" not in source.read_text("utf8")
    win.undo()
    assert "Background" not in win.doc.attributes(button)
    win.redo()
    assert "Background" in win.doc.attributes(button)


def test_visual_drag_resize_copy_and_unrestricted_addition(gui):
    win,source,project,monkeypatch=gui
    button=get_path(win,"OriginalButton")
    win.select_path(button)
    win.redraw()
    box=win._boxes[button]
    x=int(box[0]+box[2]/2);y=int(box[1]+box[3]/2)
    win.canvas_press(SimpleNamespace(x=x,y=y))
    assert win._drag is not None
    win.canvas_release(SimpleNamespace(x=x+40,y=y+20))
    assert win.doc.attributes(button)["Margin"]!="450,450,0,0"
    win.select_path(button)
    box=win._boxes[button]
    win.canvas_press(SimpleNamespace(x=int(box[0]+box[2]),y=int(box[1]+box[3])))
    win.canvas_release(SimpleNamespace(x=int(box[0]+box[2]+20),
                                            y=int(box[1]+box[3]+15)))
    assert float(win.doc.attributes(button)["Width"])>300
    win.select_path(button)
    win.angle.set("24")
    win.rotate()
    from suite_origins_visual_editor import _path_id
    assert any(win.canvas.type(item)=="polygon"
               for item in win.canvas.find_withtag(_path_id(button)))
    win.select_path(button)
    win.duplicate()
    assert any(row.label=="OriginalButton_Copy" for row in win.doc.outline())
    win.select_path(get_path(win,"DialogPage"))
    win.tag_value.set("Button")
    win.name_value.set("EigenerNeuerButton")
    win.add_element()
    new=get_path(win,"EigenerNeuerButton")
    win.select_path(new)
    win.attribute.set("CommandParameter")
    win.attr_value.set("OhneFreigegebenenHandler")
    win.apply_attribute()
    assert win.doc.attributes(new)["CommandParameter"]=="OhneFreigegebenenHandler"
    assert win.doc._target(new).tag=="{"+PRES+"}Button"


def test_revisions_are_editable_and_mod_patch_is_packaged(gui):
    win,source,project,monkeypatch=gui
    old=source.read_bytes()
    button=get_path(win,"OriginalButton")
    win.doc.edit(button,"Content","Mein eigener Menüpunkt")
    win.save()
    exported=project/"Patches/Assets/GUI/XAML/FrontendMenus.xaml"
    assert exported.is_file()
    first=exported.read_bytes()
    win.doc.edit(button,"Content","Menüpunkt 2")
    win.save()
    assert exported.read_bytes()!=first
    history=win.doc.save_revision(project,overwrite_existing=True)
    assert (Path(history["revision_dir"])/"previous-package-patch.xaml").is_file()
    edited=Path(history["revision_dir"])/"edited.xaml"
    edited.write_bytes(edited.read_bytes().replace(b"Men\xc3\xbcpunkt 2",
                                                  b"Extern angepasst"))
    doc=VisualXamlDocument.reopen(Path(history["revision_dir"]))
    assert "Extern angepasst" in doc.edited_bytes().decode("utf8")
    assert source.read_bytes()==old
    monkeypatch.setattr("suite_origins_visual_editor.simpledialog.askstring",
            lambda title,*a,**kw: "eigenefenster" if title=="Asset-Mod-ID" else "Meine Menüseiten")
    win.build_mod()
    from zipfile import ZipFile
    archives=list((project.parent/"se-asset-mods").rglob("*.zip"))
    assert archives
    with ZipFile(archives[-1]) as archive:
        member="BepInEx/plugins/eigenefenster/Patches/Assets/GUI/XAML/FrontendMenus.xaml"
        assert member in archive.namelist()
        assert "Menüpunkt 2" in archive.read(member).decode("utf8")



def test_reference_screenshot_is_kept_with_editable_revision_not_in_mod(gui,tmp_path,
                                                                  monkeypatch):
    win,source,project,_=gui
    reference=tmp_path/"original-menu-screen.png"
    Image.new("RGB",(320,180),"#334455").save(reference)
    monkeypatch.setattr(
        "suite_origins_visual_editor.filedialog.askopenfilename",
        lambda **kw:str(reference))
    win.choose_reference()
    assert win.reference_image_path==reference
    assert len(win._image_refs)>=1
    win.doc.edit(get_path(win,"OriginalButton"),"Content","Auf Screenshot ausgerichtet")
    win.save()
    import json
    import se_asset_package as package
    root=Path(project.parent)/".origins-visual-revisions"
    recorded=list(root.glob("**/rev-0001/reference.png"))
    assert len(recorded)==1
    with Image.open(recorded[0]) as saved:
        assert saved.size==(320,180)
    stored_patch=project/"Patches/Assets/GUI/XAML/FrontendMenus.xaml"
    assert stored_patch.is_file()
    assert not (project/"Override/Assets/GUI/Images/original-menu-screen.png").exists()

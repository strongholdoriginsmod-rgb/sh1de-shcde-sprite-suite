"""Existing Origins patch + original screenshot are editable, not locked."""
from pathlib import Path
import sys
import tkinter as tk
from zipfile import ZipFile

import pytest
from PIL import Image

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/"tools"),str(ROOT/"src")]
import hud_menu_workspace as work
import se_asset_package as package
from origins_visual_document import VisualXamlDocument, apply_existing_patch
from suite_origins_visual_editor import OriginsVisualEditor


@pytest.fixture
def layout(tmp_path,monkeypatch):
    suite=tmp_path/"suite";(suite/"work").mkdir(parents=True)
    monkeypatch.setattr(work,"ROOT",suite)
    monkeypatch.setattr(work,"WORK",suite/"work")
    monkeypatch.setattr(package,"ROOT",suite)
    monkeypatch.setattr(package,"WORK",suite/"work")
    monkeypatch.setattr(package,"OUT",suite/"work"/"se-asset-mods")
    original=tmp_path/"FrontendMenus.xaml"
    original.write_text(
      '<UserControl xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" '
      'xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml" '
      'xmlns:local="clr-namespace:CrusaderDE">'
      '<Grid Name="Root"><Button Name="OldButton" Content="Old" '
      'Command="{Binding ButtonMainMenuCommand}" CommandParameter="Roadmap"/>'
      '<Image Name="OldImage" Width="200" Height="100"/>'
      '</Grid></UserControl>',encoding="utf8")
    patch=tmp_path/"ExistingOrigins.xaml"
    # This mirrors the original patcher's namespace inheritance behavior.
    patch.write_text('''<Patch>
      <Operation Type="SetAttribute" XPath="//n:Button[@Name='OldButton']"
                 AttributeName="Margin" Value="60,70,0,0"/>
      <Operation Type="Replace" XPath="//n:Button[@Name='OldButton']">
        <Content><Button Name="OldButton" Content="My Origins"
          local:PropEx.TextCentre="New Label" Command="{Binding ButtonMainMenuCommand}"
          CommandParameter="OriginsCustomHandler"/></Content>
      </Operation>
      <Operation Type="InsertAfter" XPath="//n:Image[@Name='OldImage']">
        <Content><Image Name="LogoNew" Width="350" Height="120"/></Content>
      </Operation>
      <Operation Type="Add" XPath="//n:Grid[@Name='Root']">
        <Content><Grid Name="CustomPage" Visibility="Collapsed">
          <Button Name="CustomButton" CommandParameter="MySpecialAction"/>
        </Grid></Content>
      </Operation>
    </Patch>''',encoding="utf8")
    reference=tmp_path/"menu-reference.png"
    Image.new("RGB",(500,270),(11,40,70)).save(reference)
    return original,patch,reference,suite/"work"/"project"


def test_old_origins_patch_merges_into_free_editable_document(layout):
    original,patch,reference,project=layout
    before=original.read_bytes()
    doc=VisualXamlDocument(original)
    result=apply_existing_patch(doc,patch)
    assert result["applied_operations"]==4
    assert result["skipped_operations"]==0
    names={row.label for row in doc.outline()}
    assert {"CustomPage","CustomButton","LogoNew"}<=names
    button=next(row for row in doc.outline() if row.label=="OldButton")
    assert doc.attributes(button.path)["CommandParameter"]=="OriginsCustomHandler"
    doc.edit(button.path,"CommandParameter","AnythingTheDesignerWants")
    assert doc.undo_edit()
    assert doc.redo_edit()
    saved=doc.save_revision(project)
    assert saved["published"]
    assert b"AnythingTheDesignerWants" in Path(saved["patch"]).read_bytes()
    assert original.read_bytes()==before


def test_gui_import_old_patch_and_save_reference_outside_mod(layout,monkeypatch):
    original,patch,reference,project=layout
    try:
        root=tk.Tk();root.withdraw()
    except tk.TclError as error:
        pytest.skip("Native Tk unavailable: "+str(error))
    try:
        gui=OriginsVisualEditor(root,project=project,source=original)
        root.update()
        monkeypatch.setattr(
            "suite_origins_visual_editor.filedialog.askopenfilename",
            lambda *a,**k: str(reference) if "Bildreferenz" in str(k.get("filetypes")) else str(patch))
        gui.import_patch()
        assert any(e.label=="CustomPage" for e in gui.doc.outline())
        gui.choose_reference()
        assert gui.reference_image_path==reference
        gui.save()
        revision=list((project.parent/".origins-visual-revisions").rglob("reference.png"))
        assert len(revision)==1
        assert revision[0].is_file()
        output=package.build(project,"overlaydemo",name="Origins Overlay",author="QA")
        with ZipFile(output["zip"]) as files:
            assert files.testzip() is None
            assert not any(name.endswith("reference.png") for name in files.namelist())
            assert any(name.endswith("Patches/Assets/GUI/XAML/FrontendMenus.xaml")
                       for name in files.namelist())
        gui.destroy()
    finally:
        root.destroy()

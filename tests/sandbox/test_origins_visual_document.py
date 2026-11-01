"""Freedom-first XAML document editing, patching, revision and roundtrip tests."""
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"tools"))
import hud_menu_workspace as work
import se_asset_package as package
from origins_visual_document import VisualXamlDocument, PRES, XNS


@pytest.fixture
def project(tmp_path,monkeypatch):
    suite=tmp_path/"suite"
    (suite/"work").mkdir(parents=True)
    monkeypatch.setattr(work,"ROOT",suite)
    monkeypatch.setattr(work,"WORK",suite/"work")
    monkeypatch.setattr(package,"ROOT",suite)
    monkeypatch.setattr(package,"WORK",suite/"work")
    monkeypatch.setattr(package,"OUT",suite/"work"/"se-asset-mods")
    return suite/"work"/"my-project"


@pytest.fixture
def original(tmp_path):
    source=tmp_path/"FrontendMenus.xaml"
    source.write_text('''<?xml version="1.0"?>
<UserControl xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
 xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
 xmlns:local="clr-namespace:CrusaderDE">
 <Grid Name="MenuRoot" Width="1920" Height="1080">
  <!-- An unchanged original comment -->
  <Button Name="Multiplayer" Margin="0,450,0,0" Width="250"
     Content="Multiplayer" Command="{Binding ButtonMainMenuCommand}"
     CommandParameter="Multiplayer"
     local:PropEx.TextCentre="Mehrspieler">
    <Button.RenderTransform><ScaleTransform x:Name="MultiplayerScale"
       ScaleX="1" ScaleY="1"/></Button.RenderTransform>
  </Button>
  <Image Name="LogoMain" Source="../Images/MenusBackground.png"
         Width="900" Height="200"/>
  <StackPanel Name="OriginalMenu">
     <TextBlock Text="Text unterhalb" />
  </StackPanel>
 </Grid>
</UserControl>''',encoding="utf8")
    return source


def node_path(doc, name):
    return next(row.path for row in doc.outline() if row.label==name)


def test_full_tree_arbitrary_attributes_and_custom_commands(original):
    before=original.read_bytes()
    doc=VisualXamlDocument(original)
    paths=doc.outline()
    assert any(row.tag=="TextBlock" for row in paths)
    assert any(row.tag=="ScaleTransform" for row in paths)
    button=node_path(doc,"Multiplayer")
    doc.edit(button,"CommandParameter","MyCustomOriginsCommand")
    doc.edit(button,"local:PropEx.TextCentre","Ein ganz neues Menü")
    doc.edit(button,"MouseEnter","CustomHoverHandler")
    doc.edit(button,"ToolTip","Eigener Tooltip")
    doc.edit(button,"Visibility","{Binding CustomVisibility}")
    assert doc.attributes(button)["CommandParameter"]=="MyCustomOriginsCommand"
    assert doc.undo_edit()
    assert "Visibility" not in doc.attributes(button)
    assert doc.redo_edit()
    patch,proof=doc.patch_bytes()
    root=ET.fromstring(patch)
    op=root.find("Operation")
    assert op.get("Type")=="Replace"
    assert op.get("XPath")=="//n:Grid[@Name='MenuRoot']"
    assert b'MyCustomOriginsCommand' in patch
    assert b'MultiplayerScale' in patch
    assert b'An unchanged original comment' in patch
    assert proof["native_action_handlers_attested"] is False
    assert original.read_bytes()==before


def test_children_insert_delete_copy_reorder_and_transform(original):
    doc=VisualXamlDocument(original)
    grid=node_path(doc,"MenuRoot")
    button=node_path(doc,"Multiplayer")
    clone=doc.duplicate(button)
    assert doc.attributes(clone)["Name"]=="Multiplayer_Copy"
    doc.edit(clone,"Content","Mein neuer Button")
    doc.move(clone,55,30)
    doc.resize(clone,390,90)
    doc.rotate(clone,22.5)
    assert doc.attributes(clone)["Width"]=="390"
    assert doc.attributes(clone)["Height"]=="90"
    assert "55" in doc.attributes(clone)["Margin"]
    assert any(row.tag=="RotateTransform" for row in doc.outline())
    inserted=doc.insert(grid,"Button",{"Name":"MeinButton",
        "Content":"Neu","CommandParameter":"AllowAnyValue"})
    assert doc.attributes(inserted)["CommandParameter"]=="AllowAnyValue"
    doc.remove(inserted)
    doc.reorder(clone,1)
    patch,_=doc.patch_bytes()
    assert b'Multiplayer_Copy' in patch
    assert b'AllowAnyValue' not in patch
    assert b'Angle="22.5"' in patch


def test_revision_can_be_reopened_and_modified_without_hash_locks(
    original,project,
):
    doc=VisualXamlDocument(original)
    button=node_path(doc,"Multiplayer")
    doc.edit(button,"Content","Erster Entwurf")
    result=doc.save_revision(project)
    assert result["published"] is True
    target=project/"Patches/Assets/GUI/XAML/FrontendMenus.xaml"
    assert target.is_file()
    assert package._check_xml(target,patch=True) is None
    first=target.read_bytes()
    # User edits their own revision directly in a text editor.
    edited=Path(result["revision_dir"])/"edited.xaml"
    edited.write_bytes(edited.read_bytes().replace(
        b'Erster Entwurf',b'Frei manuell bearbeitet'))
    reopened=VisualXamlDocument.reopen(Path(result["revision_dir"]))
    assert "Frei manuell bearbeitet" in reopened.edited_bytes().decode("utf8")
    second=reopened.save_revision(project,publish=True,overwrite_existing=True,
                                document_name="FrontendMenus.xaml")
    assert second["published"] is True
    assert target.read_bytes()!=first
    assert (Path(second["revision_dir"])/"previous-package-patch.xaml").read_bytes()==first
    assert original.read_bytes().find(b'Erster Entwurf')<0


def test_originals_patch_packs_into_static_asset_zip(original,project):
    doc=VisualXamlDocument(original)
    doc.insert(node_path(doc,"MenuRoot"),"Button",
       {"Name":"ButtonEinzel","Content":"Eigenes Fenster",
        "Command":"{Binding ButtonMainMenuCommand}",
        "CommandParameter":"MeinNeuerBefehl"})
    result=doc.save_revision(project)
    assert result["published"]
    archive=package.build(project,"originsvisual",
                          name="Freies Menü",author="Manuell")
    from zipfile import ZipFile
    with ZipFile(archive["zip"]) as zipped:
        name="BepInEx/plugins/originsvisual/Patches/Assets/GUI/XAML/FrontendMenus.xaml"
        assert name in zipped.namelist()
        assert b'MeinNeuerBefehl' in zipped.read(name)
    assert archive["runtime_dll"] is False


def test_pending_conflict_creates_revision_without_overwriting_existing_patch(
    original,project,
):
    project.mkdir(parents=True)
    doc=VisualXamlDocument(original)
    doc.edit(node_path(doc,"Multiplayer"),"Content","Neuer Text")
    existing=project/"Patches/Assets/GUI/XAML/FrontendMenus.xaml"
    existing.parent.mkdir(parents=True)
    existing.write_text('<Patch><Operation Type="Remove" XPath="//n:Button"/></Patch>')
    proof=doc.save_revision(project,publish=True,overwrite_existing=False)
    assert not proof["published"]
    assert existing.read_text().startswith("<Patch>")
    assert (Path(proof["revision_dir"])/"patch.xaml").is_file()


def test_invalid_xml_is_rejected_but_valid_unbounded_user_values_allowed(original):
    doc=VisualXamlDocument(original)
    path=node_path(doc,"Multiplayer")
    doc.edit(path,"CommandParameter","Hallo Welt und Externe Bindung")
    assert doc.attributes(path)["CommandParameter"].startswith("Hallo Welt")
    with pytest.raises(work.WorkshopError):
        doc.edit(path,"Content","Null\x00Zeichen")
    assert doc.attributes(path)["CommandParameter"].startswith("Hallo Welt")



def test_existing_origins_patch_is_reconstructed_as_editable_original_layout(
    original,project,tmp_path
):
    from origins_visual_document import apply_existing_patch
    before=original.read_bytes()
    historic=tmp_path/"old-Origins-FrontendMenus.xaml"
    # Historical Noesis patches may depend on the game's xmlns:local context.
    historic.write_text("""<Patch>
        <Operation Type="SetAttribute" XPath="//n:Button[@Name='Multiplayer']"
          AttributeName="Content" Value="Origins Kampagne" />
        <Operation Type="InsertAfter" XPath="//n:Button[@Name='Multiplayer']">
          <Content><Button Name="OriginsCustom" Content="Freie Seite"
            local:PropEx.TextCentre="Mein eigener Knopf"
            Command="{Binding ButtonMainMenuCommand}"
            CommandParameter="UnbeschraenkterEigenerCommand"/></Content>
        </Operation>
        <Operation Type="Add" XPath="//n:Grid[@Name='MenuRoot']">
          <Content><Grid Name="EigeneKompletteMenuseite" Width="950" Height="600">
            <TextBlock Name="Titel" Text="Von Originalpatch importiert" />
          </Grid></Content>
        </Operation>
        <Operation Type="Remove" XPath="//n:Image[@Name='LogoMain']"/>
    </Patch>""",encoding="utf8")
    doc=VisualXamlDocument(original)
    applied=apply_existing_patch(doc,historic)
    assert applied["operations_found"]==4
    assert applied["applied_operations"]==4
    labels=[x.label for x in doc.outline()]
    assert "OriginsCustom" in labels
    assert "EigeneKompletteMenuseite" in labels
    assert "LogoMain" not in labels
    assert doc._target(node_path(doc,"OriginsCustom")).tag=="{"+PRES+"}Button"
    assert doc.attributes(node_path(doc,"OriginsCustom"))[
        "local:PropEx.TextCentre"]=="Mein eigener Knopf"
    doc.edit(node_path(doc,"OriginsCustom"),"CommandParameter",
             "WeiterhinFreiBearbeitet")
    result=doc.save_revision(project)
    saved=project/"Patches/Assets/GUI/XAML/FrontendMenus.xaml"
    assert b"WeiterhinFreiBearbeitet" in saved.read_bytes()
    assert b"EigeneKompletteMenuseite" in saved.read_bytes()
    reopened=VisualXamlDocument.reopen(Path(result["revision_dir"]))
    assert "OriginsCustom" in [x.label for x in reopened.outline()]
    assert original.read_bytes()==before


def test_imported_patch_missing_xpath_can_be_skipped_without_old_hash_lock(
    original,tmp_path
):
    from origins_visual_document import apply_existing_patch
    file=tmp_path/"changed-version.xaml"
    file.write_text("""<Patch>
      <Operation Type="SetAttribute" XPath="//n:Button[@Name='AbsentButton']"
        AttributeName="Content" Value="Not here" />
      <Operation Type="SetAttribute" XPath="//n:Button[@Name='Multiplayer']"
        AttributeName="Content" Value="Applied anyway" />
    </Patch>""",encoding="utf8")
    doc=VisualXamlDocument(original)
    result=apply_existing_patch(doc,file,strict=False)
    assert result["applied_operations"]==1
    assert result["skipped_operations"]==1
    assert result["warnings"]
    assert doc.attributes(node_path(doc,"Multiplayer"))["Content"]=="Applied anyway"
    assert doc.undo_edit()
    assert doc.attributes(node_path(doc,"Multiplayer"))["Content"]=="Multiplayer"
    with pytest.raises(work.WorkshopError,match="XPath trifft"):
        apply_existing_patch(doc,file,strict=True)
    assert doc.attributes(node_path(doc,"Multiplayer"))["Content"]=="Multiplayer"

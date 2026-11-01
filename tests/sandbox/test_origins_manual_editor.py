"""Origins historical XAML, static media and manual real-button editing."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import json
import sys
import xml.etree.ElementTree as ET

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"tools"))
import hud_menu_workspace as work
import se_asset_package as package
import origins_xaml_designer as designer
from suite_origins_theme_editor import read_palette,save_palette


@pytest.fixture
def project(tmp_path,monkeypatch):
    suite=tmp_path/"suite"
    base=suite/"work"
    base.mkdir(parents=True)
    monkeypatch.setattr(work,"ROOT",suite)
    monkeypatch.setattr(work,"WORK",base)
    monkeypatch.setattr(package,"ROOT",suite)
    monkeypatch.setattr(package,"WORK",base)
    monkeypatch.setattr(package,"OUT",base/"se-asset-mods")
    return base/"manual-origins"


@pytest.fixture
def game_xaml(tmp_path):
    game=tmp_path/"FrontendMenus.xaml"
    game.write_text("""<?xml version="1.0"?>
<UserControl xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
 xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
 xmlns:local="clr-namespace:CrusaderDE">
 <Grid Name="MenuRoot">
   <Button Name="MainMenu_MultiplayerButton" Width="250" Height="70"
     Margin="0,450,0,0" HorizontalAlignment="Center"
     local:PropEx.TextCentre="Multiplayer"
     Command="{Binding ButtonMainMenuCommand}" CommandParameter="Multiplayer">
     <Button.RenderTransform>
       <ScaleTransform x:Name="MainMenu_MultiplayerButtonScale" />
     </Button.RenderTransform>
   </Button>
   <Button Name="MainMenu_RoadmapButton" Command="{Binding ButtonMainMenuCommand}"
    CommandParameter="Roadmap" Margin="0,750,0,0"/>
   <Image Name="LogoMain" Source="../Images/MenusBackground.png" Width="900"/>
 </Grid>
</UserControl>
""",encoding="utf8")
    return game


def test_originals_control_collection_and_existing_command_semantics(game_xaml):
    found=designer.controls(game_xaml)
    assert any(x.name=="MainMenu_MultiplayerButton" for x in found)
    node=next(x for x in found if x.name=="MainMenu_MultiplayerButton")
    assert node.bound_command=="{Binding ButtonMainMenuCommand}"
    assert node.command_parameter=="Multiplayer"
    assert "[@Name='MainMenu_MultiplayerButton']" in node.xpath


def test_noesis_attribute_patch_preserves_actual_source_and_unique_xpath(game_xaml,project):
    before=game_xaml.read_bytes()
    node=next(x for x in designer.controls(game_xaml) if x.tag=="Button")
    blob,report=designer.create_patch(game_xaml,xpath=node.xpath,
                   operation="SetAttribute",property_name="Margin",value="0,500,0,0")
    assert ET.fromstring(blob).find("Operation").get("XPath")==node.xpath
    path,receipt=designer.save_patch(
        game_xaml,xpath=node.xpath,operation="SetAttribute",
        property_name="Margin",value="0,500,0,0",project=project)
    assert path.relative_to(project).as_posix()=="Patches/Assets/GUI/XAML/FrontendMenus.xaml"
    assert package._check_xml(path,patch=True) is None
    assert receipt["patch_sha256"]==sha256(path.read_bytes()).hexdigest()
    assert game_xaml.read_bytes()==before


def test_command_parameter_requires_real_existing_handler(game_xaml):
    x=next(c for c in designer.controls(game_xaml) if c.name=="MainMenu_MultiplayerButton")
    with pytest.raises(work.WorkshopError,match="Unverified new command handler"):
        designer.create_patch(game_xaml,xpath=x.xpath,operation="SetAttribute",
                              property_name="CommandParameter",value="OriginsLegacyCampaign")
    blob,proof=designer.create_patch(game_xaml,xpath=x.xpath,operation="Replace",
                              property_name="CommandParameter",value="Roadmap")
    assert b'Roadmap' in blob
    assert proof["new_runtime_callback_created"] is False
    assert "local:PropEx" in blob.decode("utf8") or "ns" in blob.decode("utf8")


def test_add_new_menu_control_uses_only_proven_existing_command(game_xaml,project):
    x=next(c for c in designer.controls(game_xaml) if c.name=="MainMenu_MultiplayerButton")
    blob,proof=designer.create_structural_patch(
        game_xaml,xpath=x.xpath,operation="InsertAfter",
        new_name="SpriteSuite_ExistingRoadmap",
        command_parameter="Roadmap",text="Meine Einstellungen")
    assert b'InsertAfter' in blob
    assert b'SpriteSuite_ExistingRoadmap' in blob
    assert b'CommandParameter="Roadmap"' in blob
    assert proof["reuses_verified_existing_command"] is True
    assert b'MainMenu_MultiplayerButtonScale' not in blob
    saved,report=designer.save_structural_patch(
        game_xaml,project=project,xpath=x.xpath,
        operation="InsertAfter",new_name="SpriteSuite_ExistingRoadmap",
        command_parameter="Roadmap",text="Einstellungen")
    assert saved.is_file()
    assert report["creates_new_runtime_handler"] is False
    with pytest.raises(work.WorkshopError,match="handler"):
        designer.create_structural_patch(
           game_xaml,xpath=x.xpath,operation="InsertAfter",
           new_name="SpriteSuite_UnavailableAction",
           command_parameter="OriginsNewGameplayHandler")


def test_can_insert_static_xaml_label_in_named_grid(game_xaml):
    grid=next(c for c in designer.controls(game_xaml) if c.name=="MenuRoot")
    blob,proof=designer.create_structural_patch(game_xaml,xpath=grid.xpath,
        operation="Add",new_name="SpriteSuite_MyTitle",text="Mein Menü")
    assert b'IsHitTestVisible="False"' in blob
    assert ET.fromstring(blob).find("Operation").get("XPath")==grid.xpath
    assert proof["creates_new_runtime_handler"] is False


def test_xaml_import_preserves_required_origins_runtime_folder(project,tmp_path):
    source=tmp_path/"IntroSequence.xaml"
    source.write_text('<Patch><Operation Type="SetAttribute" XPath="//n:Image" '
                      'AttributeName="Opacity" Value="0" /></Patch>',encoding="utf8")
    before=source.read_bytes()
    new=work.import_patch(source,project=project,target_document="XAML/IntroSequence.xaml")
    assert new.relative_to(project).as_posix()=="Patches/Assets/GUI/XAML/IntroSequence.xaml"
    assert source.read_bytes()==before
    with pytest.raises(work.WorkshopError):
        work.import_patch(source,project=project,target_document="../escape.xaml")
    with pytest.raises(work.WorkshopError):
        work.import_patch(source,project=project,target_document="XAML/IntroSequence.xaml")


@pytest.mark.parametrize("resource,data,allowed",[
    ("Override/Assets/GUI/Video/front_end_background.webm",
     b"\x1a\x45\xdf\xa3\x88\x42\x82\x84webm"+b"x"*80,True),
    ("Override/Assets/GUI/Video/front_end_background.webm",
     b"version https://git-lfs.github.com/spec/v1"+b"x"*80,False),
    ("Locales/de-DE/crusader.txt",
     b"deDE\n>>TEXTSTART\n>>6-----\nEigene Menuseite\n",True),
    ("Locales/de-DE/crusader.txt",b"not a valid locale",False),
    ("Override/Assets/GUI/Video/evil.exe",b"MZ"+b"x"*80,False),
])
def test_origins_media_and_locale_static_packaging(project,tmp_path,
                                                    resource,data,allowed):
    src=tmp_path/("external"+Path(resource).suffix)
    src.write_bytes(data)
    before=src.read_bytes()
    if not allowed:
        with pytest.raises((work.WorkshopError,package.AssetModError)):
            work.import_media(src,resource=resource,project=project)
        assert src.read_bytes()==before
        return
    result=work.import_media(src,resource=resource,project=project)
    assert result.relative_to(project).as_posix()==resource
    assert result.read_bytes()==data
    assert src.read_bytes()==before
    assert resource in [x.relative_path for x in work.list_assets(project)]
    out=package.build(project,"originsstatic",name="Origins Assets",author="QA")
    from zipfile import ZipFile
    with ZipFile(out["zip"]) as z:
        assert z.testzip() is None
        assert "BepInEx/plugins/originsstatic/"+resource in z.namelist()
        assert z.read("BepInEx/plugins/originsstatic/"+resource)==data
    assert out["runtime_dll"] is False


def test_origins_theme_palette_roundtrip_keeps_color_keys_and_brush_binding(
    project,tmp_path
):
    src=tmp_path/"Theme.Brushes.DarkRed.xaml"
    src.write_text("""<ResourceDictionary xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
 xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml">
 <Color x:Key="Color.Accent">#FF111122</Color>
 <Color x:Key="Color.Accent1">#FF223344</Color>
 <SolidColorBrush x:Key="Brush.Accent1" Color="{StaticResource Color.Accent1}"/>
</ResourceDictionary>""",encoding="utf8")
    before=src.read_bytes()
    raw,root,colors=read_palette(src)
    assert colors["Color.Accent1"]=="#FF223344"
    file,receipt=save_palette(src,project,{"Color.Accent1":"#FF44BBFF"})
    assert "Color.Accent1" in file.read_text("utf8")
    assert "Brush.Accent1" in file.read_text("utf8")
    assert "Color.Accent1}" in file.read_text("utf8")
    assert "#FF44BBFF" in file.read_text("utf8")
    assert package._check_xml(file,patch=False) is None
    assert receipt["brush_resource_bindings_preserved"] is True
    assert before==src.read_bytes()
    with pytest.raises(work.WorkshopError):
        save_palette(src,project,{"Color.Accent1":"#FF112233"})


def test_multiple_real_controls_in_one_origin_frontend_patch(game_xaml,project):
    original=game_xaml.read_bytes()
    items={node.name:node for node in designer.controls(game_xaml)}
    button=items["MainMenu_MultiplayerButton"]
    logo=items["LogoMain"]
    changes=[
      designer.create_patch(game_xaml,xpath=button.xpath,
                            operation="SetAttribute",
                            property_name="Visibility",value="Collapsed"),
      designer.create_patch(game_xaml,xpath=logo.xpath,
                            operation="SetAttribute",
                            property_name="Opacity",value="0.5"),
    ]
    merged,report=designer.combine_control_patches(game_xaml,changes)
    assert report["operations"]==2
    xml=ET.fromstring(merged)
    assert xml.tag=="Patch"
    assert len(xml.findall("Operation"))==2
    saved,receipt=designer.save_combined_patch(
        game_xaml,project=project,patches=changes)
    assert saved.relative_to(project).as_posix()=="Patches/Assets/GUI/XAML/FrontendMenus.xaml"
    assert package._check_xml(saved,patch=True) is None
    assert game_xaml.read_bytes()==original
    assert receipt["operations"]==2
    with pytest.raises(work.WorkshopError,match="revision"):
        designer.save_combined_patch(game_xaml,project=project,patches=changes)


def test_conflicting_queued_edits_cannot_produce_ambiguous_xaml(game_xaml):
    node=next(c for c in designer.controls(game_xaml)
              if c.name=="MainMenu_MultiplayerButton")
    single=designer.create_patch(game_xaml,xpath=node.xpath,
               operation="SetAttribute",property_name="Margin",value="0,555,0,0")
    with pytest.raises(work.WorkshopError,match="twice"):
        designer.combine_control_patches(game_xaml,[single,single])
    replaced=designer.create_patch(game_xaml,xpath=node.xpath,
               operation="Replace",property_name="Margin",value="0,600,0,0")
    with pytest.raises(work.WorkshopError,match="Conflicting"):
        designer.combine_control_patches(game_xaml,[single,replaced])


def test_real_origins_namespaced_propex_text_can_be_edited_by_replace(game_xaml):
    target=next(x for x in designer.controls(game_xaml)
                if x.name=="MainMenu_MultiplayerButton")
    assert target.properties["local:PropEx.TextCentre"]=="Multiplayer"
    with pytest.raises(work.WorkshopError,match="Namespaced"):
        designer.create_patch(game_xaml,xpath=target.xpath,
            operation="SetAttribute",
            property_name="local:PropEx.TextCentre",value="Origins Kampagne")
    blob,proof=designer.create_patch(game_xaml,xpath=target.xpath,
            operation="Replace",
            property_name="local:PropEx.TextCentre",value="Origins Kampagne")
    node=ET.fromstring(blob).find(".//{http://schemas.microsoft.com/winfx/2006/xaml/presentation}Button")
    assert node.get("{clr-namespace:CrusaderDE}PropEx.TextCentre")=="Origins Kampagne"
    assert node.get("Command")=="{Binding ButtonMainMenuCommand}"
    assert node.get("CommandParameter")=="Multiplayer"
    assert b"MainMenu_MultiplayerButtonScale" in blob


def test_insert_before_reuses_still_existing_game_command(game_xaml):
    item=next(x for x in designer.controls(game_xaml)
              if x.name=="MainMenu_RoadmapButton")
    blob,proof=designer.create_structural_patch(
        game_xaml,xpath=item.xpath,operation="InsertBefore",
        new_name="SpriteSuite_MyRoadmap",
        command_parameter="Roadmap",text="Origins-Funktionen")
    assert ET.fromstring(blob).find("Operation").get("Type")=="InsertBefore"
    assert b"CommandParameter=\"Roadmap\"" in blob
    assert proof["creates_new_runtime_handler"] is False

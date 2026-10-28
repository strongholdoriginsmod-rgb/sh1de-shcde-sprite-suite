"""SHCDESE XAML integration: exact real Grid binding and safe asset mods."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sys
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from PIL import Image
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/"tools"),str(ROOT/"src")]
import hud_menu_noesis_integration as noesis
import hud_menu_workspace as images
import hud_menu_layout as layout
import se_asset_package as pack

PRES=noesis.PRES
XNS=noesis.XNS


@pytest.fixture
def context(tmp_path,monkeypatch):
    suite=tmp_path/"SpriteSuite"
    (suite/"work").mkdir(parents=True)
    work=suite/"work"
    for mod in (images,layout,pack,noesis):
        monkeypatch.setattr(mod,"WORK",work)
    monkeypatch.setattr(images,"ROOT",suite)
    monkeypatch.setattr(pack,"ROOT",suite)
    monkeypatch.setattr(pack,"OUT",work/"se-asset-mods")
    project=work/"menu-layout"
    original=tmp_path/"owned-logo.png"
    Image.new("RGBA",(8,8),(170,65,220,200)).save(original)
    content=original.read_bytes()
    png=images.import_image(original,project=project)
    scene=layout.Scene(name="MenuOverlay",width=240,height=120)
    layer=layout.add_layer(scene,project,png.relative_to(project).as_posix(),
                           x=30,y=17)
    layout.set_geometry(scene,layer.id,rotation=22,width=28,height=18)
    scene.target_resource="Override/Assets/GUI/Images/MenuOverlay.png"
    _,etag=layout.save_scene(scene,project)
    layout.export_composition(scene,project,resource_name="MenuOverlay",
                              scene_sha256=etag)

    game=tmp_path/"GameQA"
    plugin=game/"BepInEx/plugins/000shcdese"
    gui=plugin/"Override/Assets/GUI"
    xaml=gui/"XAML"
    xaml.mkdir(parents=True)
    (plugin/"info.json").write_text(
        json.dumps({"GUID":"000shcdese","Version":"9.123.999",
                    "Manifest":1}),encoding="utf8")
    source=xaml/"FrontendMenus.xaml"
    source.write_text(
        f'<UserControl xmlns="{PRES}" xmlns:x="{XNS}">'
        '<Grid x:Name="MenuRoot" HorizontalAlignment="Center">'
        '<Image x:Name="ExistingButton" Source="/Assets/GUI/Images/Logo.png"/>'
        '</Grid>'
        '<Grid Name="SecondaryMenu"/>'
        '</UserControl>',encoding="utf8")
    original_xaml=source.read_bytes()
    return project,scene,etag,gui,source,original_xaml,original,content


def targets_of(ctx):
    project,scene,etag,gui,source,original,owned,owned_before=ctx
    return noesis.discover_grid_targets(gui)


def test_identifies_real_named_grids_independent_of_version(context):
    project,scene,etag,gui,source,original,owned,owned_before=context
    targets=targets_of(context)
    assert {x.grid_name for x in targets}=={"MenuRoot","SecondaryMenu"}
    assert all(x.extender_version=="9.123.999" for x in targets)
    assert targets[0].source_sha256==sha256(original).hexdigest()
    assert noesis.installed_gui(gui)[0]==gui.resolve()
    assert noesis.verify_grid_target(gui,targets[0])[1].tag==noesis.GRID
    assert owned.read_bytes()==owned_before


def test_generated_add_patch_references_correct_png_and_real_xpath(context):
    project,scene,etag,gui,source,original,owned,owned_before=context
    target=next(t for t in targets_of(context) if t.grid_name=="MenuRoot")
    patch,report=noesis.generate_patch(
        scene,project,game_gui=gui,target=target,
        alignment="Mitte",scene_sha256=etag)
    assert report["target_xpath"]=="//n:Grid[@x:Name='MenuRoot']"
    assert report["patch_path"]=="Patches/Assets/GUI/XAML/FrontendMenus.xaml"
    assert report["operation"]=="Add"
    assert report["ingame_rendering_verified"] is False
    assert report["installed_extender_version"]=="9.123.999"
    xml=ET.fromstring(patch)
    operation=xml.find("Operation")
    assert operation.get("Type")=="Add"
    canvas=operation.find("Content")[0]
    assert canvas.tag==noesis._CANVAS
    assert canvas.get("HorizontalAlignment")=="Center"
    assert canvas.get("IsHitTestVisible")=="False"
    assert canvas[0].get("Source")=="/Assets/GUI/Images/MenuOverlay.png"
    assert canvas[0].get("Width")=="240"
    assert canvas[0].get("Height")=="120"
    assert source.read_bytes()==original
    assert owned.read_bytes()==owned_before


def test_package_contains_exactly_composite_and_matching_xaml_patch(context):
    project,scene,etag,gui,source,original,owned,owned_before=context
    target=next(t for t in targets_of(context) if t.grid_name=="MenuRoot")
    source_folder,report=noesis.stage_binding(
        scene,project,scene_sha256=etag,game_gui=gui,target=target,
        alignment="Unten rechts")
    files=sorted(p.relative_to(source_folder).as_posix()
                 for p in source_folder.rglob("*") if p.is_file())
    assert files==["Override/Assets/GUI/Images/MenuOverlay.png",
                   "Patches/Assets/GUI/XAML/FrontendMenus.xaml"]
    xaml=source_folder/files[1]
    noesis._check_xml(xaml,patch=True)
    assert xaml.read_bytes().startswith(b'<?xml version=')
    assert source.read_bytes()==original
    assert owned.read_bytes()==owned_before
    result=noesis.build_bound_mod(scene,project,scene_sha256=etag,
        game_gui=gui,target=target,alignment="Unten rechts",
        guid="hudmenuscreen",name="Visible HUD menu")
    assert result["runtime_dll"] is False
    assert result["se_version_required"] is None
    assert result["manifest"]["Manifest"]==0
    assert result["source_files"]==2
    assert Path(result["binding_report"]).is_file()
    with ZipFile(result["zip"]) as archive:
        names=archive.namelist()
        assert len(names)==3
        assert any(p.endswith("Patches/Assets/GUI/XAML/FrontendMenus.xaml")
                   for p in names)
        assert any(p.endswith("Override/Assets/GUI/Images/MenuOverlay.png")
                   for p in names)
        assert not any("owned-logo.png" in p for p in names)


def test_rejects_xaml_sha_change_after_selection(context):
    project,scene,etag,gui,source,original,owned,owned_before=context
    target=targets_of(context)[0]
    source.write_bytes(original+b' ')
    with pytest.raises(images.WorkshopError,match="changed"):
        noesis.generate_patch(scene,project,game_gui=gui,
                              target=target,scene_sha256=etag)


def test_rejects_nonexistent_grid_and_unknown_xaml_document(context):
    project,scene,etag,gui,source,original,owned,owned_before=context
    target=targets_of(context)[0]
    from dataclasses import replace
    with pytest.raises(images.WorkshopError,match="missing|renamed|ambiguous"):
        noesis.generate_patch(scene,project,game_gui=gui,
            target=replace(target,grid_name="DoesNotExist"),scene_sha256=etag)
    with pytest.raises(images.WorkshopError):
        noesis.generate_patch(scene,project,game_gui=gui,
            target=replace(target,xaml_document="../wrong.xaml"),
            scene_sha256=etag)


def test_duplicate_target_name_is_not_implicitly_selected(context):
    project,scene,etag,gui,source,original,owned,owned_before=context
    source.write_text(
        f'<UserControl xmlns="{PRES}" xmlns:x="{XNS}">'
        '<Grid Name="Same"/><Grid x:Name="Same"/>'
        '<Grid x:Name="Unambiguous"/>'
        '</UserControl>',encoding="utf8")
    choices=targets_of(context)
    assert [r.grid_name for r in choices]==["Unambiguous"]


def test_binding_package_fails_on_stale_scene_or_png(context):
    project,scene,etag,gui,source,original,owned,owned_before=context
    target=targets_of(context)[0]
    layer=scene.layers[0]
    layer.x+=18
    with pytest.raises(images.WorkshopError,match="saved|stale|differs"):
        noesis.stage_binding(scene,project,scene_sha256=etag,
                             game_gui=gui,target=target)
    layer.x-=18
    Image.new("RGBA",(8,8),(1,2,3,255)).save(project/layer.asset)
    with pytest.raises(images.WorkshopError,match="input PNG changed"):
        noesis.stage_binding(scene,project,scene_sha256=etag,
                             game_gui=gui,target=target)


@pytest.mark.parametrize("version",["1.44.0","2.14.3","3.0.0","unknown"])
def test_no_game_or_extender_version_whitelist(context,version):
    project,scene,etag,gui,source,original,owned,owned_before=context
    info=gui.parents[2]/"info.json"
    doc=json.loads(info.read_text("utf8"))
    doc["Version"]=version
    info.write_text(json.dumps(doc),encoding="utf8")
    targets=targets_of(context)
    assert len(targets)==2
    _,report=noesis.generate_patch(scene,project,game_gui=gui,
                                   target=targets[0],scene_sha256=etag)
    assert report["installed_extender_version"]==version


def test_qa_game_existing_noesis_targets_are_read_only():
    gui=Path(r"E:\SSGameQA\BepInEx\plugins\000shcdese\Override\Assets\GUI")
    if not gui.is_dir():
        pytest.skip("Private QA game not mounted")
    for name in ("MainHUD.xaml","FrontendMenus.xaml","IngameUIScreens.xaml"):
        if not (gui/"XAML"/name).is_file():
            pytest.skip("Private installed SE XAML snapshot missing")
    originals={p.name:sha256(p.read_bytes()).hexdigest()
               for p in (gui/"XAML").glob("*.xaml")}
    targets=noesis.discover_grid_targets(gui)
    names={(t.xaml_document,t.grid_name) for t in targets}
    assert ("MainHUD.xaml","HUD_Main") in names
    assert ("FrontendMenus.xaml","Standalone") in names
    assert ("IngameUIScreens.xaml","HUD_IngameMenu") in names
    for t in targets:
        noesis.verify_grid_target(gui,t)
    assert originals=={p.name:sha256(p.read_bytes()).hexdigest()
                       for p in (gui/"XAML").glob("*.xaml")}


@pytest.mark.parametrize("document,grid",[
    ("MainHUD.xaml","HUD_Main"),
    ("FrontendMenus.xaml","Standalone"),
    ("IngameUIScreens.xaml","HUD_IngameMenu"),
])
def test_real_qa_xaml_accepts_a_generated_static_overlay_without_changes(
    context,document,grid
):
    real_gui=Path(r"E:\SSGameQA\BepInEx\plugins\000shcdese\Override\Assets\GUI")
    if not real_gui.is_dir():
        pytest.skip("Private QA Noesis XAML not installed on this device")
    project,scene,etag,synthetic,source,original,owned,owned_before=context
    originals={p.name:sha256(p.read_bytes()).hexdigest()
               for p in (real_gui/"XAML").glob("*.xaml")}
    candidates=[t for t in noesis.discover_grid_targets(real_gui)
                if t.xaml_document==document and t.grid_name==grid]
    assert len(candidates)==1
    binding=candidates[0]
    prepared,report=noesis.stage_binding(
        scene,project,scene_sha256=etag,
        game_gui=real_gui,target=binding,
        alignment="Oben links")
    assert (prepared/binding.relative_patch).is_file()
    assert report["source_xaml_sha256"]==originals[document]
    assert report["offline_patched_xml_sha256"]!=report["source_xaml_sha256"]
    assert report["ingame_rendering_verified"] is False
    assert originals=={p.name:sha256(p.read_bytes()).hexdigest()
                       for p in (real_gui/"XAML").glob("*.xaml")}
    assert owned.read_bytes()==owned_before


def test_anonymous_unique_root_grid_allows_real_front_menu_injection(context):
    project,scene,etag,gui,source,original,owned,owned_before=context
    source.write_text(
        f'<UserControl xmlns="{PRES}" xmlns:x="{XNS}">'
        '<UserControl.Resources><ResourceDictionary/></UserControl.Resources>'
        '<Grid><TextBlock Text="A menu always starts here"/></Grid>'
        '</UserControl>',encoding="utf8")
    targets=targets_of(context)
    roots=[row for row in targets if row.name_kind=="root"]
    assert len(roots)==1
    assert roots[0].xpath=="/n:UserControl/n:Grid"
    assert "Gesamte Oberfläche" in roots[0].label
    raw,report=noesis.generate_patch(
        scene,project,game_gui=gui,target=roots[0],
        alignment="Oben links",scene_sha256=etag)
    assert b'XPath="/n:UserControl/n:Grid"' in raw
    assert report["target_grid"]=="__ROOT_GRID__"
    assert report["render_only"] is True
    assert owned.read_bytes()==owned_before


def test_guarded_qa_install_rollback_preserves_original_game(context,monkeypatch):
    import hud_menu_noesis_qa as qa
    monkeypatch.setattr(qa,"_game_running",lambda:False)
    project,scene,etag,gui,source,original,owned,owned_before=context
    game=gui.parents[5]
    (game/qa.MARKER).write_text(
        "Synthetic QA game copy, not an original installation",encoding="utf8"
    )
    target=next(r for r in targets_of(context) if r.grid_name=="MenuRoot")
    result=noesis.build_bound_mod(
        scene,project,scene_sha256=etag,game_gui=gui,target=target,
        alignment="Oben links",guid="qa_menu_once",
        name="Synthetic QA menu test")
    dest=game/"BepInEx/plugins/qa_menu_once"
    assert not dest.exists()
    receipt=qa.qa_install(project,gui,result["asset_mod_folder"])
    assert receipt["guid"]=="qa_menu_once"
    assert qa.qa_status(project,gui,"qa_menu_once")["files"]==receipt["files"]
    assert dest.is_dir()
    assert (dest/"Patches/Assets/GUI/XAML/FrontendMenus.xaml").is_file()
    assert (dest/"Override/Assets/GUI/Images/MenuOverlay.png").is_file()
    with pytest.raises(images.WorkshopError,match="already exists"):
        qa.qa_install(project,gui,result["asset_mod_folder"])
    assert source.read_bytes()==original
    assert owned.read_bytes()==owned_before
    deleted=qa.qa_remove(project,gui,"qa_menu_once")
    assert deleted["removed_files"]==3
    assert deleted["game_originals_unchanged"]
    assert not dest.exists()
    assert source.read_bytes()==original


def test_qa_rollback_refuses_any_manually_edited_installed_mod(context,monkeypatch):
    import hud_menu_noesis_qa as qa
    monkeypatch.setattr(qa,"_game_running",lambda:False)
    project,scene,etag,gui,source,original,owned,owned_before=context
    game=gui.parents[5]
    (game/qa.MARKER).write_text("QA only",encoding="utf8")
    target=next(r for r in targets_of(context) if r.grid_name=="MenuRoot")
    built=noesis.build_bound_mod(
        scene,project,scene_sha256=etag,game_gui=gui,target=target,
        alignment="Oben links",guid="qa_untouched",
        name="QA protected")
    qa.qa_install(project,gui,built["asset_mod_folder"])
    installed=game/"BepInEx/plugins/qa_untouched/Override/Assets/GUI/Images/MenuOverlay.png"
    originally=installed.read_bytes()
    installed.write_bytes(b"user overwrote QA image after install")
    with pytest.raises(images.WorkshopError,match="changed"):
        qa.qa_remove(project,gui,"qa_untouched")
    assert installed.read_bytes()==b"user overwrote QA image after install"
    installed.write_bytes(originally)
    qa.qa_remove(project,gui,"qa_untouched")
    assert not (game/"BepInEx/plugins/qa_untouched").exists()


def test_real_game_cannot_be_modified_without_a_qa_marker(context):
    import hud_menu_noesis_qa as qa
    project,scene,etag,gui,source,original,owned,owned_before=context
    game=gui.parents[5]
    assert not (game/qa.MARKER).exists()
    with pytest.raises(images.WorkshopError,match="QA game copy"):
        qa.qa_game_root(gui)
    assert source.read_bytes()==original

def test_grid_overlay_spans_all_explicit_rows_and_columns(context):
    project,scene,etag,gui,source,original,owned,owned_before=context
    source.write_text(
        f'<UserControl xmlns="{PRES}" xmlns:x="{XNS}">'
        '<Grid x:Name="HudGrid">'
        '<Grid.RowDefinitions><RowDefinition/><RowDefinition/></Grid.RowDefinitions>'
        '<Grid.ColumnDefinitions><ColumnDefinition/><ColumnDefinition/>'
        '<ColumnDefinition/></Grid.ColumnDefinitions>'
        '<Button x:Name="ExistingCommand" Content="Click me"/>'
        '</Grid></UserControl>',encoding="utf8")
    before=source.read_bytes()
    target=next(t for t in targets_of(context) if t.grid_name=="HudGrid")
    patch,report=noesis.generate_patch(
        scene,project,game_gui=gui,target=target,
        alignment="Mitte",scene_sha256=etag)
    canvas=ET.fromstring(patch).find("Operation").find("Content")[0]
    assert canvas.get("Grid.RowSpan")=="2"
    assert canvas.get("Grid.ColumnSpan")=="3"
    assert report["target_grid_rows"]==2
    assert report["target_grid_columns"]==3
    assert canvas.get("IsHitTestVisible")=="False"
    assert source.read_bytes()==before


def test_noesis_overlay_refuses_existing_game_image_name(context):
    project,scene,etag,gui,source,original,owned,owned_before=context
    image_path=gui/"Images"/"MenuOverlay.png"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"game asset must not be silently overridden")
    target=next(t for t in targets_of(context) if t.grid_name=="MenuRoot")
    with pytest.raises(images.WorkshopError,match="already exists"):
        noesis.generate_patch(scene,project,game_gui=gui,
                              target=target,scene_sha256=etag)
    assert image_path.read_bytes()==b"game asset must not be silently overridden"
    assert source.read_bytes()==original

def test_running_game_blocks_even_marked_qa_copy(context,monkeypatch):
    import hud_menu_noesis_qa as qa
    project,scene,etag,gui,source,original,owned,owned_before=context
    game=gui.parents[5]
    (game/qa.MARKER).write_text("QA copy",encoding="utf8")
    target=next(t for t in targets_of(context) if t.grid_name=="MenuRoot")
    built=noesis.build_bound_mod(scene,project,scene_sha256=etag,
        game_gui=gui,target=target,alignment="Oben links",
        guid="qa_running_guard",name="Running game guard")
    monkeypatch.setattr(qa,"_game_running",lambda:True)
    with pytest.raises(images.WorkshopError,match="Close Stronghold"):
        qa.qa_install(project,gui,built["asset_mod_folder"])
    assert not (game/"BepInEx/plugins/qa_running_guard").exists()
    assert source.read_bytes()==original

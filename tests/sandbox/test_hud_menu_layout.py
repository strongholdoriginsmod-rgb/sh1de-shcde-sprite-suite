"""Executable synthetic layout, geometry, provenance and export tests."""
from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import json
import sys

from PIL import Image
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/"tools"),str(ROOT/"src")]
import hud_menu_layout as layout
import hud_menu_workspace as assets
import se_asset_package as pack


@pytest.fixture
def scene_project(tmp_path,monkeypatch):
    root=tmp_path/"private-suite"
    work=root/"work"
    work.mkdir(parents=True)
    monkeypatch.setattr(assets,"ROOT",root)
    monkeypatch.setattr(assets,"WORK",work)
    monkeypatch.setattr(layout,"WORK",work)
    monkeypatch.setattr(pack,"WORK",work)
    monkeypatch.setattr(pack,"OUT",work/"se-asset-mods")
    project=work/"hud-menu-demo"
    images=tmp_path/"origin-files"
    images.mkdir()
    first=images/"button.png"
    second=images/"icon.png"
    Image.new("RGBA",(10,6),(210,20,25,255)).save(first)
    Image.new("RGBA",(8,9),(50,100,240,128)).save(second)
    asset1=assets.import_image(first,project=project,folder="Menüs / UI-Bilder")
    asset2=assets.import_image(second,project=project,folder="HUD / UI-Sprites")
    return project,first,second,asset1,asset2


def setup_scene(scene_project):
    project,first,second,asset1,asset2=scene_project
    scene=layout.Scene(name="MyMenu",width=64,height=48,
                       background=(0,0,0,0))
    a=layout.add_layer(scene,project,asset1.relative_to(project).as_posix(),x=3,y=4)
    b=layout.add_layer(scene,project,asset2.relative_to(project).as_posix(),x=12,y=11)
    return project,scene,a,b


def test_new_scene_round_trip_persists_geometry_and_original_references(scene_project):
    project,scene,a,b=setup_scene(scene_project)
    layout.set_geometry(scene,b.id,x=31.5,y=16.25,
                        width=24,height=18,rotation=33.0,
                        opacity=170,anchor="center",pivot_x=.1,pivot_y=.9,
                        locked=True,visible=False)
    scene.target_resource="Override/Assets/GUI/Images/TargetMenu.png"
    path,token=layout.save_scene(scene,project)
    assert path.is_file() and path.is_relative_to(project.parent)
    assert not path.is_relative_to(project)
    assert sha256(path.read_bytes()).hexdigest()==token
    loaded,expected=layout.load_scene(project,"MyMenu")
    assert expected==token
    assert loaded.as_json()==scene.as_json()
    assert loaded.layers[1].rotation==33.0
    assert loaded.layers[1].x==31.5
    assert loaded.layers[1].pivot_y==.9
    assert loaded.layers[1].asset==b.asset
    assert not list(project.rglob("*.scene.json"))
    with pytest.raises(assets.WorkshopError,match="externally"):
        layout.save_scene(scene,project,expected_hash=None)
    _,new_token=layout.save_scene(scene,project,expected_hash=token)
    assert new_token==token


def test_move_rotate_and_hit_test_use_persistent_geometry(scene_project):
    project,scene,a,b=setup_scene(scene_project)
    assert layout.hit_test(scene,4,5)==a.id
    assert layout.hit_test(scene,13,12)==b.id
    before=scene.clone()
    layout.move_layer(scene,a.id,dx=6,dy=10,snap=1)
    assert a.x==9 and a.y==14
    assert layout.hit_test(scene,4,5) is None
    layout.set_geometry(scene,b.id,rotation=90.0,anchor="center",
                        width=20,height=8,pivot_x=.5,pivot_y=.5)
    px,py=layout.pivot_of(layout.layer_by_id(scene,b.id))
    assert layout.hit_test(scene,px,py)==b.id
    assert layout.History(scene).scene.as_json()==scene.as_json()
    assert scene.as_json()!=before.as_json()


def test_layer_stacking_opacity_and_rotated_rendering(scene_project):
    project,scene,a,b=setup_scene(scene_project)
    layout.set_geometry(scene,b.id,x=3,y=4,width=10,height=6,
                        opacity=255)
    image=layout.render_scene(scene,project)
    assert image.size==(64,48)
    assert image.getpixel((4,5))==(129,60,132,255)  # correct RGBA alpha composite
    layout.reorder(scene,b.id,-1)
    next_image=layout.render_scene(scene,project)
    assert next_image.getpixel((4,5))==(210,20,25,255)
    layout.set_geometry(scene,a.id,rotation=45)
    out=layout.render_scene(scene,project)
    assert out.size==(64,48)
    assert any(px[3] for px in out.get_flattened_data())


def test_drawn_preview_uses_same_model_at_scaled_size(scene_project):
    project,scene,a,b=setup_scene(scene_project)
    preview,ratio=layout.render_preview(scene,project,max_width=32,max_height=24)
    assert ratio==.5
    assert preview.size==(32,24)
    assert any(pixel[3] for pixel in preview.get_flattened_data())
    full=layout.render_scene(scene,project)
    expected=full.resize((32,24),Image.Resampling.LANCZOS)
    assert preview.tobytes()==expected.tobytes()


def test_undo_redo_group_drags_and_duplicates(scene_project):
    project,scene,a,b=setup_scene(scene_project)
    history=layout.History(scene)
    before=history.scene.clone()
    layout.move_layer(history.scene,a.id,2,4)
    layout.move_layer(history.scene,b.id,-2,1)
    assert history.commit(before)
    assert history.undo()
    assert history.scene.as_json()==before.as_json()
    assert history.redo()
    assert history.scene.layers[0].x==5
    old=history.scene.clone()
    new=layout.duplicate_layer(history.scene,a.id,dx=3,dy=5)
    assert new.id!=a.id
    assert len(history.scene.layers)==3
    assert history.commit(old)
    assert history.undo()
    assert len(history.scene.layers)==2
    assert history.redo()
    assert len(history.scene.layers)==3


def test_locked_and_invalid_layer_operations_refused(scene_project):
    project,scene,a,b=setup_scene(scene_project)
    layout.set_geometry(scene,a.id,locked=True)
    with pytest.raises(assets.WorkshopError,match="locked"):
        layout.move_layer(scene,a.id,2,5)
    with pytest.raises(assets.WorkshopError,match="Locked"):
        layout.set_geometry(scene,a.id,width=999)
    with pytest.raises(assets.WorkshopError,match="locked"):
        layout.remove_layers(scene,{a.id})
    with pytest.raises(assets.WorkshopError):
        layout.set_geometry(scene,b.id,x=float("nan"))
    with pytest.raises(assets.WorkshopError):
        layout.set_geometry(scene,b.id,pivot_x=11)
    with pytest.raises(assets.WorkshopError):
        layout.Scene(name="../evil").validate(project)


def test_export_bakes_positions_and_is_real_asset_package_input(scene_project):
    project,scene,a,b=setup_scene(scene_project)
    scene.target_resource="Override/Assets/GUI/Images/CompositeA.png"
    path,scene_digest=layout.save_scene(scene,project)
    before_one=(project/a.asset).read_bytes()
    before_two=(project/b.asset).read_bytes()
    exported=layout.export_composition(
        scene,project,resource_name="CompositeA",scene_sha256=scene_digest
    )
    composite=Path(exported["png"])
    with Image.open(composite) as picture:
        assert picture.size==(64,48)
        assert picture.getpixel((4,5))==(210,20,25,255)
        assert picture.getpixel((13,12))[3]>0
    export_meta=json.loads(Path(exported["manifest"]).read_text("utf8"))
    assert export_meta["schema"]==layout.EXPORT_SCHEMA
    assert export_meta["layers"][0]["x"]==3
    assert export_meta["layers"][1]["y"]==11
    assert export_meta["scene_sha256"]==scene_digest
    assert len(export_meta["assets"])==2
    assert layout.export_composition(
        scene,project,resource_name="CompositeA",scene_sha256=scene_digest
    )["sha256"]==exported["sha256"]
    assert (project/a.asset).read_bytes()==before_one
    assert (project/b.asset).read_bytes()==before_two
    report=assets.audit_assets(project)
    assert report["assets"]==3
    result=pack.build(project,"menu_layout_test",name="Layout Test",author="QA")
    assert result["runtime_dll"] is False
    assert result["se_version_required"] is None
    assert result["manifest"]["Manifest"]==0
    assert "CompositeA.png" in Path(result["zip"]).read_bytes().decode("latin1")
    assert not list(project.rglob("*.scene.json"))
    assert not list(project.rglob("*.scene-manifest.json"))


def test_export_conflicts_protect_existing_user_graphic_and_manual_edits(scene_project):
    project,scene,a,b=setup_scene(scene_project)
    _,digest=layout.save_scene(scene,project)
    with pytest.raises(assets.WorkshopError,match="input layer|user image already"):
        layout.export_composition(scene,project,resource_name="button",
                                  scene_sha256=digest)
    result=layout.export_composition(scene,project,
        resource_name="MenuMerge",scene_sha256=digest)
    output=Path(result["png"])
    output.write_bytes(b"USER MANUALLY CHANGED FILE")
    with pytest.raises(assets.WorkshopError,match="modified externally"):
        layout.export_composition(scene,project,resource_name="MenuMerge",
                                  scene_sha256=digest)


def test_saved_scene_external_conflict_is_detected(scene_project):
    project,scene,a,b=setup_scene(scene_project)
    path,etag=layout.save_scene(scene,project)
    payload=path.read_text("utf8")
    path.write_text(payload+" \n",encoding="utf8")
    with pytest.raises(assets.WorkshopError,match="externally"):
        layout.save_scene(scene,project,expected_hash=etag)


def test_saved_layout_cannot_escape_to_foreign_files(scene_project):
    project,scene,a,b=setup_scene(scene_project)
    path,etag=layout.save_scene(scene,project)
    doc=json.loads(path.read_text("utf8"))
    doc["layers"][0]["asset"]="../Stronghold Crusader Definitive Edition_Data/globalgamemanagers"
    path.write_text(json.dumps(doc),encoding="utf8")
    with pytest.raises(assets.WorkshopError):
        layout.load_scene(project,scene.name)
    assert not (project.parent.parent/"Stronghold Crusader Definitive Edition_Data").exists()


def test_scene_rejects_duplicate_ids_large_layers_and_invalid_layout_names(scene_project):
    project,scene,a,b=setup_scene(scene_project)
    scene.layers.append(replace(a))
    with pytest.raises(assets.WorkshopError,match="Duplicate"):
        scene.validate(project)
    scene.layers.pop()
    scene.width=5000
    with pytest.raises(assets.WorkshopError):
        scene.validate(project)
    with pytest.raises(assets.WorkshopError):
        layout.scene_file(project,"../../evil")


def test_isolated_package_source_includes_only_baked_png_by_default(scene_project):
    project,scene,a,b=setup_scene(scene_project)
    scene.target_resource="Override/Assets/GUI/Images/ReadyMenu.png"
    _,token=layout.save_scene(scene,project)
    layout.export_composition(scene,project,resource_name="ReadyMenu",
                              scene_sha256=token)
    output=layout.prepare_package_source(scene,project,scene_sha256=token)
    filelist=[p.relative_to(output).as_posix() for p in output.rglob("*") if p.is_file()]
    assert filelist==["Override/Assets/GUI/Images/ReadyMenu.png"]
    assert output.is_relative_to(project.parent)
    assert not output.is_relative_to(project)
    exported=pack.build(output,"only_baked",name="One composed GUI",author="Tests")
    assert exported["source_files"]==1
    assert exported["manifest"]["Manifest"]==0
    assert layout.prepare_package_source(scene,project,scene_sha256=token)==output


def test_patches_are_optional_and_checked_as_separate_asset_input(scene_project):
    project,scene,a,b=setup_scene(scene_project)
    scene.target_resource="Override/Assets/GUI/Images/MainComposite.png"
    _,token=layout.save_scene(scene,project)
    layout.export_composition(scene,project,resource_name="MainComposite",
                              scene_sha256=token)
    patches=project/"Patches/Assets/GUI"
    patches.mkdir(parents=True)
    patch=patches/"ButtonOpacity.xaml"
    patch.write_text(
        '<Patch><Operation Type="SetAttribute" XPath="/ResourceDictionary" '
        'Name="Opacity" Value="0.8"/></Patch>',encoding="utf8")
    only_png=layout.prepare_package_source(scene,project,
                                           scene_sha256=token,include_patches=False)
    with_xaml=layout.prepare_package_source(scene,project,
                                            scene_sha256=token,include_patches=True)
    assert len([p for p in only_png.rglob("*") if p.is_file()])==1
    assert len([p for p in with_xaml.rglob("*") if p.is_file()])==2
    built=pack.build(with_xaml,"baked_with_xaml",name="With menu patch",author="")
    assert built["source_files"]==2
    assert patch.read_text("utf8").startswith("<Patch>")


def test_old_export_not_packaged_when_positions_or_png_change(scene_project):
    project,scene,a,b=setup_scene(scene_project)
    scene.target_resource="Override/Assets/GUI/Images/LiveMenu.png"
    _,first=layout.save_scene(scene,project)
    layout.export_composition(scene,project,resource_name="LiveMenu",
                              scene_sha256=first)
    layout.set_geometry(scene,a.id,x=a.x+15)
    _,second=layout.save_scene(scene,project,expected_hash=first)
    with pytest.raises(assets.WorkshopError,match="stale"):
        layout.prepare_package_source(scene,project,scene_sha256=second)
    layout.export_composition(scene,project,resource_name="LiveMenu",
                              scene_sha256=second)
    # A pixel edit after export must be re-rendered before building the mod.
    Image.new("RGBA",(10,6),(0,120,240,255)).save(project/a.asset)
    with pytest.raises(assets.WorkshopError,match="input PNG changed"):
        layout.prepare_package_source(scene,project,scene_sha256=second)


def test_new_canvas_geometry_resize_handles_obey_anchor_and_ratio(scene_project):
    project,scene,a,b=setup_scene(scene_project)
    left=a.x
    result=layout.resize_handle(scene,a.id,"se",15,6,snap=1)
    assert result.width==25 and result.height==12
    assert result.x==left
    result=layout.resize_handle(scene,a.id,"nw",5,2,snap=1)
    assert result.width==20 and result.height==10
    assert result.x==left+5
    assert result.y==6
    result=layout.resize_handle(scene,b.id,"se",8,2,
                                keep_ratio=True,snap=1)
    assert abs(result.width/result.height - 8/9)<.2


def test_prepared_output_refuses_unexpected_manual_edits(scene_project):
    project,scene,a,b=setup_scene(scene_project)
    scene.target_resource="Override/Assets/GUI/Images/Trusted.png"
    _,token=layout.save_scene(scene,project)
    layout.export_composition(scene,project,resource_name="Trusted",
                              scene_sha256=token)
    source=layout.prepare_package_source(scene,project,scene_sha256=token)
    (source/"Override/Assets/GUI/Images/Trusted.png").write_bytes(b"modified")
    with pytest.raises(assets.WorkshopError,match="differs"):
        layout.prepare_package_source(scene,project,scene_sha256=token)


def test_layout_save_preserves_previous_positions_as_recoverable_revision(scene_project):
    project,scene,a,b=setup_scene(scene_project)
    original_path,first=layout.save_scene(scene,project)
    prior=original_path.read_bytes()
    layout.set_geometry(scene,a.id,x=97.25,y=-12.5,rotation=11)
    path,new=layout.save_scene(scene,project,expected_hash=first)
    assert path==original_path and new!=first
    revisions=list((path.parent/"revisions").glob("*.scene.json"))
    assert len(revisions)==1
    assert revisions[0].read_bytes()==prior
    loaded,_=layout.load_scene(project,scene.name)
    assert loaded.layers[0].x==97.25
    assert loaded.layers[0].y==-12.5
    assert loaded.layers[0].rotation==11
    assert not any("revisions" in str(p) for p in project.rglob("*"))


def test_updated_xaml_patch_stages_a_fresh_immutable_package(scene_project):
    project,scene,a,b=setup_scene(scene_project)
    scene.target_resource="Override/Assets/GUI/Images/MenuComposite.png"
    _,etag=layout.save_scene(scene,project)
    layout.export_composition(scene,project,resource_name="MenuComposite",
                              scene_sha256=etag)
    patch_dir=project/"Patches/Assets/GUI"
    patch_dir.mkdir(parents=True)
    xaml=patch_dir/"TextColor.xaml"
    xaml.write_text(
        '<Patch><Operation Type="SetAttribute" XPath="/ResourceDictionary" '
        'Name="Opacity" Value="0.2"/></Patch>',encoding="utf8")
    first=layout.prepare_package_source(scene,project,scene_sha256=etag,
                                         include_patches=True)
    original=(first/"Patches/Assets/GUI/TextColor.xaml").read_bytes()
    xaml.write_text(
        '<Patch><Operation Type="SetAttribute" XPath="/ResourceDictionary" '
        'Name="Opacity" Value="0.9"/></Patch>',encoding="utf8")
    second=layout.prepare_package_source(scene,project,scene_sha256=etag,
                                          include_patches=True)
    assert first!=second
    assert first.is_dir() and second.is_dir()
    assert (first/"Patches/Assets/GUI/TextColor.xaml").read_bytes()==original
    assert (second/"Patches/Assets/GUI/TextColor.xaml").read_bytes()!=original
    assert layout.prepare_package_source(scene,project,scene_sha256=etag,
                                         include_patches=True)==second


def test_locked_layer_cannot_be_reordered(scene_project):
    project,scene,a,b=setup_scene(scene_project)
    layout.set_geometry(scene,a.id,locked=True)
    with pytest.raises(assets.WorkshopError,match="Locked"):
        layout.reorder(scene,a.id,1)
    assert scene.layers[0].id==a.id


def test_scene_metadata_stale_refuses_export_even_if_png_would_render(scene_project):
    project,scene,a,b=setup_scene(scene_project)
    scene.target_resource="Override/Assets/GUI/Images/SceneA.png"
    _,etag=layout.save_scene(scene,project)
    layout.set_geometry(scene,a.id,x=19)
    with pytest.raises(assets.WorkshopError,match="Saved layout differs"):
        layout.export_composition(scene,project,resource_name="SceneA",
                                  scene_sha256=etag)
    assert not (project/"Override/Assets/GUI/Images/SceneA.png").exists()


def test_external_scene_edit_disables_baked_mod_even_if_ui_unchanged(scene_project):
    project,scene,a,b=setup_scene(scene_project)
    scene.target_resource="Override/Assets/GUI/Images/SceneB.png"
    path,etag=layout.save_scene(scene,project)
    layout.export_composition(scene,project,resource_name="SceneB",
                              scene_sha256=etag)
    path.write_bytes(path.read_bytes()+b"\n")
    with pytest.raises(assets.WorkshopError,match="Saved layout differs"):
        layout.prepare_package_source(scene,project,scene_sha256=etag)


def test_simple_selection_without_movement_preserves_exact_offgrid_positions(scene_project):
    project,scene,a,b=setup_scene(scene_project)
    x,y=a.x,a.y
    layout.move_layer(scene,a.id,0,0,snap=8)
    assert (a.x,a.y)==(x,y)
    layout.move_layer(scene,a.id,0,8,snap=8)
    assert a.x==x

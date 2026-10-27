"""Independent synthetic contracts for additional Noesis UI atlas pages."""
from __future__ import annotations

import json
import hashlib
import re
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from PIL import Image

import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import ui_extra_atlas as atlas

ORIGINALS = ("UI-MasterAtlas", "UI-TrailAtlas", "UI-Colour1Atlas", "UI-Colour2Atlas")
XAML_HEADER = (
    '<ResourceDictionary xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" '
    'xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml">'
)


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(atlas, "ROOT", tmp_path)
    work = tmp_path / "work" / "my-new-sprites"
    work.mkdir(parents=True)
    (tmp_path / "dist").mkdir()
    reference = tmp_path / "original-gui"
    sprites = reference / "Sprites"
    resource = reference / "XAMLResources"
    sprites.mkdir(parents=True)
    resource.mkdir(parents=True)

    for index, name in enumerate(ORIGINALS):
        content = (
            XAML_HEADER + f'\n <BitmapImage x:Key="{name}" UriSource="{name}.png" />\n'
            + (' <BitmapImage x:Key="Extra.reserved" UriSource="existing.png" />\n' if index == 0 else "")
            + '</ResourceDictionary>\n'
        )
        (sprites / f"{name}.xaml").write_text(content, encoding="utf-8")
    lines = [
        XAML_HEADER,
        " <ResourceDictionary.MergedDictionaries>",
        *[f'        <ResourceDictionary Source="../Sprites/{name}.xaml" />'
          for name in ORIGINALS],
        '        <ResourceDictionary Source="Theme.DarkRed.xaml" />',
        " </ResourceDictionary.MergedDictionaries>",
        "</ResourceDictionary>",
    ]
    (resource / "ApplicationResources.xaml").write_text("\n".join(lines)+"\n", encoding="utf-8")
    # The real SHCDE source contains malformed binary after FRONT_Story.xaml.
    # Our collision scanner must not try to rewrite or parse this unrelated file.
    (resource / "FRONT_Story.xaml").write_bytes(
        (XAML_HEADER + '\n<Button x:Key="Extra.FromHistory"/>\n'
         '</ResourceDictionary>\n').encode("utf-8") + b"\x02\xa0binary\\x0012"
    )
    names = (("alpha", (64, 45)), ("beta", (80, 49)), ("gamma", (50, 78)))
    for i, (name, size) in enumerate(names):
        image = Image.new("RGBA", size)
        image.putdata([
            ((x * 11 + i) % 256, (y * 13 + i) % 256,
             (x*y + i*41) % 256, (x*37 + y*5 + i*23) % 256)
            for y in range(size[1]) for x in range(size[0])
        ])
        image.save(work / f"{name}.png")
    return work, reference, tmp_path / "dist" / "fresh-extra"


def test_build_verify_and_original_reference_preservation(project):
    source, gui, dest = project
    original = (gui / "XAMLResources" / "ApplicationResources.xaml").read_bytes()
    report = atlas.build(source, gui, dest, stem="MyExtra", prefix="MyName",
                         size=256, gutter=3)
    assert report["source_images_count"] == 3
    assert report["pages"][0]["name"] == "MyExtra-001"
    assert report["runtime_game_tested"] is False
    assert atlas.verify(dest) == {
        "pages_verified": 1, "images_verified": 3,
        "original_gui_checked": True, "source_pngs_checked": True,
        "runtime_game_tested": False,
        "native_shcde_source_pinned": False,
    }
    assert (gui / "XAMLResources" / "ApplicationResources.xaml").read_bytes() == original
    xaml = (dest / atlas.REL_RESOURCES / "ApplicationResources.xaml").read_text("utf-8")
    assert "../Sprites/MyExtra-001.xaml" in xaml
    assert xaml.count("../Sprites/UI-MasterAtlas.xaml") == 1
    doc = ET.fromstring((dest / atlas.REL_SPRITES / "MyExtra-001.xaml").read_bytes())
    assert len(list(doc)) == 4
    assert "x:Key=\"MyName.beta\"" in (dest / atlas.REL_SPRITES / "MyExtra-001.xaml").read_text("utf-8")


def test_outputs_are_really_png_and_xaml(project):
    source, gui, dest = project
    report = atlas.build(source, gui, dest, size=256)
    page = report["pages"][0]
    with Image.open(dest / page["png"]) as im:
        assert im.format == "PNG"
        assert im.mode == "RGBA"
        assert im.size == (256, 256)
    assert page["xaml_sha256"] == atlas._sha(dest / page["xaml"])


def test_multiple_pages_pack_no_overlap(project):
    source, gui, dest = project
    for file in source.glob("*.png"):
        file.unlink()
    for i in range(6):
        Image.new("RGBA", (198, 156), (i*30, 80, 90, 255)).save(
            source / f"new-{i:02d}.png"
        )
    report = atlas.build(source, gui, dest, size=256, gutter=4, max_pages=6)
    assert len(report["pages"]) == 6
    assert sum(len(p["sprites"]) for p in report["pages"]) == 6
    assert atlas.verify(dest)["images_verified"] == 6


def test_page_budget_rejects_without_any_persistent_output(project):
    source, gui, dest = project
    for file in source.glob("*.png"):
        file.unlink()
    for i in range(4):
        Image.new("RGBA", (200, 200), (12, 34, 56, 78)).save(source / f"a{i}.png")
    with pytest.raises(atlas.ExtraAtlasError, match="Seitenbegrenzung"):
        atlas.build(source, gui, dest, size=256, max_pages=2)
    assert not dest.exists()


@pytest.mark.parametrize("source_name", ["reserved", "FromHistory"])
def test_existing_native_xaml_resource_key_collision_is_rejected(project, source_name):
    source, gui, dest = project
    path = source / (source_name + ".png")
    Image.new("RGBA", (9, 9), (0, 0, 0, 0)).save(path)
    with pytest.raises(atlas.ExtraAtlasError, match="bereits bestehender"):
        atlas.build(source, gui, dest, prefix="Extra", size=256)
    assert not dest.exists()


def test_invalid_page_stem_rejected(project):
    source, gui, dest = project
    with pytest.raises(atlas.ExtraAtlasError):
        atlas.build(source, gui, dest, stem="../Bad/Path")
    assert not dest.exists()


def test_no_implicit_replace(project):
    source, gui, dest = project
    atlas.build(source, gui, dest)
    a = atlas._sha(dest / atlas.MANIFEST)
    with pytest.raises(atlas.ExtraAtlasError, match="bereits"):
        atlas.build(source, gui, dest)
    assert a == atlas._sha(dest / atlas.MANIFEST)


def test_changed_png_invalidates_candidate_without_touching_package(project):
    source, gui, dest = project
    atlas.build(source, gui, dest, size=256)
    original = atlas._sha(dest / atlas.MANIFEST)
    Image.new("RGBA", (64, 45), (0, 0, 0, 255)).save(source / "alpha.png")
    with pytest.raises(atlas.ExtraAtlasError, match="verändert"):
        atlas.verify(dest)
    assert atlas._sha(dest / atlas.MANIFEST) == original


@pytest.mark.parametrize("suffix", [".png", ".xaml"])
def test_tampered_generated_resource_fails_closed(project, suffix):
    source, gui, dest = project
    atlas.build(source, gui, dest, size=256)
    path = dest / atlas.REL_SPRITES / ("SpriteSuiteExtra-001" + suffix)
    with path.open("ab") as stream:
        stream.write(b"not original!")
    with pytest.raises(atlas.ExtraAtlasError):
        atlas.verify(dest)


def test_changed_applicationresources_is_rejected(project):
    source, gui, dest = project
    atlas.build(source, gui, dest)
    p = dest / atlas.REL_RESOURCES / "ApplicationResources.xaml"
    p.write_bytes(p.read_bytes() + b" ")
    with pytest.raises(atlas.ExtraAtlasError, match="SHA-256"):
        atlas.verify(dest)


def test_original_resource_modified_after_build_refuses_verification(project):
    source, gui, dest = project
    atlas.build(source, gui, dest)
    app = gui / "XAMLResources" / "ApplicationResources.xaml"
    app.write_text(app.read_text(encoding="utf8") + "<!-- edit -->", encoding="utf8")
    with pytest.raises(atlas.ExtraAtlasError, match="Native"):
        atlas.verify(dest)


def test_replace_is_explicit_and_source_pixels_rechecked(project):
    source, gui, dest = project
    first = atlas.build(source, gui, dest, size=256)
    first_hash = first["pages"][0]["png_sha256"]
    with Image.open(source / "beta.png") as opened:
        im = opened.convert("RGBA")
    im.putpixel((0, 0), (213, 37, 111, 91))
    im.save(source / "beta.png")
    second = atlas.build(source, gui, dest, size=256, replace=True)
    assert second["pages"][0]["png_sha256"] != first_hash
    assert atlas.verify(dest)["images_verified"] == 3
    assert not dest.with_name(dest.name + ".extra-atlas-old").exists()


def test_all_crossgame_inputs_do_not_modify_game_data(project):
    source, gui, dest = project
    before = {
        p: hashlib.sha256(p.read_bytes()).hexdigest()
        for folder in (gui / "Sprites", gui / "XAMLResources")
        for p in folder.rglob("*") if p.is_file()
    }
    atlas.build(source, gui, dest)
    assert all(hashlib.sha256(p.read_bytes()).hexdigest() == digest
               for p, digest in before.items())



def test_noesis_xaml_images_have_exact_original_coordinates(project):
    source, gui, dest = project
    report = atlas.build(source, gui, dest, size=256, gutter=5)
    for page in report["pages"]:
        parsed = ET.fromstring((dest / page["xaml"]).read_bytes())
        elements = {x.attrib.get(atlas.NS_X + "Key"): x for x in parsed}
        for sprite in page["sprites"]:
            x, y, w, h = sprite["rect"]
            element = elements[sprite["key"]]
            assert element.attrib["Source"] == "{StaticResource " + page["name"] + "}"
            assert element.attrib["SourceRect"] == f"{x},{y},{w},{h}"
            assert x >= 5 and y >= 5 and x+w <= 256-5 and y+h <= 256-5


def test_alpha_and_hidden_rgb_pixel_content_remain_exact(project):
    source, gui, dest = project
    report = atlas.build(source, gui, dest, size=256, gutter=2)
    for page in report["pages"]:
        with Image.open(dest / page["png"]) as sheet:
            image = sheet.convert("RGBA")
        for item in page["sprites"]:
            x,y,w,h = item["rect"]
            with Image.open(source / item["source_file"]) as im:
                raw = im.convert("RGBA")
            assert image.crop((x,y,x+w,y+h)).tobytes() == raw.tobytes()
    assert atlas.verify(dest)["images_verified"] == 3


def test_same_namespaced_key_case_collision_on_original_reference(project):
    source, gui, dest = project
    # The original contains Extra.reserved; collision is case-insensitive.
    Image.new("RGBA", (12,12)).save(source / "RESERVED.png")
    with pytest.raises(atlas.ExtraAtlasError, match="bestehender"):
        atlas.build(source, gui, dest, prefix="Extra", size=256)
    assert not dest.exists()


def test_no_directory_escape_source_or_output(project):
    source, gui, dest = project
    with pytest.raises(atlas.ExtraAtlasError, match="Unterordner"):
        atlas.build(source.parent.parent.parent, gui, dest)
    with pytest.raises(atlas.ExtraAtlasError, match="Unterordner"):
        atlas.build(source, gui, source / "some-invalid-nested-dist")


def test_fake_source_file_extension_fails_closed(project):
    source, gui, dest = project
    (source / "private-script.py").write_text("print('not an image')", encoding="utf-8")
    with pytest.raises(atlas.ExtraAtlasError, match="PNG"):
        atlas.build(source, gui, dest)
    assert not dest.exists()


def test_corrupt_new_xaml_key_but_reshash_manifest_still_fails(project):
    source, gui, dest = project
    atlas.build(source, gui, dest)
    manifest_path = dest / atlas.MANIFEST
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    page = manifest["pages"][0]
    xaml = dest / page["xaml"]
    txt = xaml.read_text("utf8")
    xaml.write_text(txt.replace("Extra.alpha", "Extra.rogue"), encoding="utf8")
    page["xaml_sha256"] = atlas._sha(xaml)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(atlas.ExtraAtlasError, match="XAML|Ressourcen"):
        atlas.verify(dest)


def test_forged_png_sha_still_fails_pixels(project):
    source, gui, dest = project
    atlas.build(source, gui, dest)
    manifest_path = dest / atlas.MANIFEST
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    page = manifest["pages"][0]
    path = dest / page["png"]
    with Image.open(path) as stream:
        image = stream.convert("RGBA")
    image.putpixel((0, 0), (255, 255, 255, 255)) # Unmapped padding region
    image.save(path)
    page["png_sha256"] = atlas._sha(path)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(atlas.ExtraAtlasError, match="gefälschte|deklarierte"):
        atlas.verify(dest)


def test_crops_cannot_overlap_even_with_adjusted_manifest(project):
    source, gui, dest = project
    atlas.build(source, gui, dest)
    manifest_path = dest / atlas.MANIFEST
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    page = manifest["pages"][0]
    page["sprites"][1]["rect"] = page["sprites"][0]["rect"][:]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(atlas.ExtraAtlasError, match="überlappen"):
        atlas.verify(dest)


def test_no_more_than_maximum_pages(project):
    source, gui, dest = project
    with pytest.raises(atlas.ExtraAtlasError, match="32 Atlasblätter"):
        atlas.build(source, gui, dest, max_pages=1000)


def test_missing_native_atlas_dictionary_rejected(project):
    source, gui, dest = project
    (gui / "Sprites" / "UI-TrailAtlas.xaml").unlink()
    with pytest.raises(atlas.ExtraAtlasError, match="vier"):
        atlas.build(source, gui, dest)


def test_original_native_resource_dictionary_must_be_xml(project):
    source, gui, dest = project
    (gui / "Sprites" / "UI-TrailAtlas.xaml").write_bytes(b"<not-xml")
    with pytest.raises(atlas.ExtraAtlasError, match="Atlas-XAML"):
        atlas.build(source, gui, dest)


def test_new_pages_must_be_regular_paths(project):
    source, gui, dest = project
    with pytest.raises(atlas.ExtraAtlasError):
        atlas.build(source, gui, dest, stem="Bad:Name")


@pytest.mark.parametrize("gutter", [0, 1, 65, -1, True])
def test_invalid_padding_sizes_rejected(project, gutter):
    source, gui, dest = project
    with pytest.raises(atlas.ExtraAtlasError, match="Atlasabstand"):
        atlas.build(source, gui, dest, gutter=gutter)



def test_wrong_native_game_asset_is_rejected_before_writing(project):
    source, gui, dest = project
    alien = dest.parent.parent / "other-installation" / "SHCDE_Data"
    alien.mkdir(parents=True)
    fake = alien / "globalgamemanagers.assets"
    fake.write_bytes(b"not a valid source")
    with pytest.raises(atlas.ExtraAtlasError, match="selben SHCDE-Installation"):
        atlas.build(source, gui, dest, target_game=fake)
    assert not dest.exists()


def test_native_reference_pin_cannot_be_forged_by_only_updating_manifest(project, monkeypatch):
    source, gui, dest = project
    from types import SimpleNamespace
    mock = {
        "asset": str(gui.parent / "Stronghold Crusader Definitive Edition_Data" / "globalgamemanagers.assets"),
        "sha256": "b"*64,
        "native_unity_textures": {
            name: {"path_id": str(i), "width": 8, "height": 8, "texture_format": 25}
            for i, name in enumerate(ORIGINALS)
        },
        "offline_only_no_gameplay_certification": True,
    }
    monkeypatch.setattr(atlas, "_native_target_asset", lambda *a: mock)
    result = atlas.build(source, gui, dest, target_game=mock["asset"])
    assert result["native_shcde_source"] == mock
    assert atlas.verify(dest)["native_shcde_source_pinned"] is True
    original = dest / atlas.MANIFEST
    doc = json.loads(original.read_text("utf-8"))
    doc["native_shcde_source"]["sha256"] = "a"*64
    original.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(atlas.ExtraAtlasError, match="Native SHCDE"):
        atlas.verify(dest)

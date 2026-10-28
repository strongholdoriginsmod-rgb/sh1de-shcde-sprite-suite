"""C#-free Script Extender asset-mod packaging works without version pins.

These tests cover static packaging contracts, not game hooks or ABI.
"""
from __future__ import annotations

from pathlib import Path
import json
import sys
from zipfile import ZipFile

from PIL import Image
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import se_asset_package as package


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    project = tmp_path / "suite"
    work = project / "work"
    work.mkdir(parents=True)
    monkeypatch.setattr(package, "ROOT", project)
    monkeypatch.setattr(package, "WORK", work)
    monkeypatch.setattr(package, "OUT", work / "se-asset-mods")
    source = work / "hud-edits"
    source.mkdir()
    return project, source


def png(path: Path, color=(10, 20, 40, 255)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (8, 9), color).save(path, "PNG")


def patch(path: Path, *, source=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source or """<Patch>
    <Operation Type="SetAttribute" XPath="//n:Button[@Name='ButtonBuildGranary']" AttributeName="Height" Value="20" />
</Patch>""", encoding="utf8")


def test_packs_png_xaml_static_without_csharp_dll_version_pins(workspace):
    project, source = workspace
    image = source / "Override/Assets/GUI/Images/MyHud.png"
    png(image)
    target = source / "Patches/Assets/GUI/XAMLResources/HUD_Main.xaml"
    patch(target)
    before_image = image.read_bytes()
    before_xaml = target.read_bytes()
    result = package.build(source, "myhud", name="Meine GUI", author="Tester")
    assert result["runtime_dll"] is False
    assert result["se_version_required"] is None
    assert result["source_files"] == 2
    assert result["manifest"]["Manifest"] == 0
    assert result["manifest"]["AssetMode"] == "Global"
    assert "Dependencies" not in result["manifest"]
    assert "SupportedGameVersions" not in result["manifest"]
    folder = Path(result["asset_mod_folder"])
    info = json.loads((folder/"info.json").read_text("utf8"))
    assert info == result["manifest"]
    assert not tuple(folder.rglob("*.dll"))
    archive = Path(result["zip"])
    with ZipFile(archive) as z:
        assert z.testzip() is None
        contents = sorted(z.namelist())
        assert contents == sorted([
            "BepInEx/plugins/myhud/info.json",
            "BepInEx/plugins/myhud/Override/Assets/GUI/Images/MyHud.png",
            "BepInEx/plugins/myhud/Patches/Assets/GUI/XAMLResources/HUD_Main.xaml",
        ])
        assert z.read(contents[1] if contents[1].endswith(".png") else contents[2])
    assert image.read_bytes() == before_image
    assert target.read_bytes() == before_xaml
    with pytest.raises(package.AssetModError, match="existiert"):
        package.build(source, "myhud", name="Meine GUI", author="Tester")


def test_png_sprite_override_no_custom_runtime(workspace):
    _, source = workspace
    png(source/"Override/Sprites/body_archer-169.png")
    png(source/"Override/Sprites/body_archer-169_m.png")
    result = package.build(source, "demoarcher", name="Einheiten", author="")
    assert result["source_files"] == 2
    assert result["manifest"]["Manifest"] == 0
    assert result["se_version_required"] is None


@pytest.mark.parametrize("relative",[
    "Override/Assets/GUI/x.exe",
    "Override/Sprites/something.dll",
    "Override/Assets/GUI/Scripts/init.lua",
    "Override/Secret/config.ini",
    "Patches/Assets/GUI/evil.exe",
])
def test_rejects_executable_nonstatic_and_non_gui_payload(workspace, relative):
    _,source=workspace
    bad=source/relative
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_bytes(b"unsafe")
    with pytest.raises(package.AssetModError):
        package.build(source,"safeasset",name="Safe",author="QA")
    assert not (package.WORK/"se-asset-mods/safeasset").exists()


@pytest.mark.parametrize("xaml",[
    "<Patch><Operation Type='Unrecognized' XPath='//*'/></Patch>",
    "<Patch><Operation Type='Replace' /></Patch>",
    "<Patch><Operation Type='Remove' XPath='//*'></Patch>",
    "<!DOCTYPE doc><Patch><Operation Type='Remove' XPath='//*'/></Patch>",
    "<Patch/>",
])
def test_rejects_invalid_or_unsafe_patches(workspace,xaml):
    _, source=workspace
    target=source/"Patches/Assets/GUI/XAMLResources/HUD_Main.xaml"
    patch(target,source=xaml)
    with pytest.raises(package.AssetModError):
        package.build(source,"safeasset",name="Safe",author="QA")


def test_xaml_patch_accepts_unbound_noesis_prefixes(workspace):
    _, source=workspace
    target=source/"Patches/Assets/GUI/XAMLResources/HUD_Main.xaml"
    patch(target,source='<XamlPatch><Operation Type="Replace" XPath="//n:Image"><Content><Image x:Key="custom" /></Content></Operation></XamlPatch>')
    output=package.build(source,"noesisui",name="Static UI",author="QA")
    assert output["runtime_dll"] is False


def test_cannot_copy_outside_work_or_overwrite_existing(workspace,tmp_path):
    _, source=workspace
    png(source/"Override/Sprites/tree_birch-42.png")
    with pytest.raises(package.AssetModError,match="work"):
        package.build(source,"safemod",name="Safe",author="QA",target=tmp_path/"outside")
    with pytest.raises(package.AssetModError,match="überschneiden"):
        package.build(source,"safemod",name="Safe",author="QA",target=source/"out")
    with pytest.raises(package.AssetModError,match="work"):
        package.build(source,"safemod",name="Safe",author="QA",target=package.WORK)


def test_rejects_symlink_payload(workspace,tmp_path):
    _,source=workspace
    outside=tmp_path/"outside.png"
    png(outside)
    folder=source/"Override/Sprites"
    folder.mkdir(parents=True)
    try:
        (folder/"linked.png").symlink_to(outside)
    except (NotImplementedError,OSError):
        pytest.skip("This test account cannot create symlinks")
    with pytest.raises(package.AssetModError,match="Symbolische"):
        package.build(source,"myhud",name="No symlink",author="QA")


def test_version_is_never_a_build_constraint(workspace):
    _,source=workspace
    png(source/"Override/Assets/GUI/Sprites/logo.png")
    for name in ("modold", "modnew"):
        result=package.build(source,name,name="Same assets",author="QA")
        assert result["se_version_required"] is None
    assert not (source/"BepInEx").exists()


def test_rejects_bad_guids_and_empty_source(workspace):
    _,source=workspace
    for bad in ("..","CON", "a/b", "SE", ""):
        with pytest.raises(package.AssetModError):
            package.build(source,bad,name="Bad",author="QA")
    with pytest.raises(package.AssetModError,match="Keine"):
        package.build(source,"emptyfixture",name="Empty",author="QA")

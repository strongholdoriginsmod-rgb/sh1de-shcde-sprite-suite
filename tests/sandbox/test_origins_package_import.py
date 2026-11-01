"""Safe import of complete static Origins resources without native plugins."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sys

from PIL import Image
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/"tools"),str(ROOT/"src")]
import origins_package_import as importer
import hud_menu_workspace as work
import se_asset_package as package


@pytest.fixture
def originals(tmp_path,monkeypatch):
    suite=tmp_path/"SpriteSuite"
    base=suite/"work"
    base.mkdir(parents=True)
    monkeypatch.setattr(importer,"ROOT",suite)
    monkeypatch.setattr(importer,"WORK",base)
    monkeypatch.setattr(work,"ROOT",suite)
    monkeypatch.setattr(work,"WORK",base)
    monkeypatch.setattr(package,"ROOT",suite)
    monkeypatch.setattr(package,"WORK",base)
    monkeypatch.setattr(package,"OUT",base/"se-asset-mods")
    plugin=tmp_path/"StrongholdOrigins"
    plugin.mkdir()
    (plugin/"info.json").write_text(json.dumps({
        "GUID":"com.strongholdorigins.core",
        "Name":"Stronghold Origins",
        "Version":"0.1.0",
        "SupportedGameVersions":["2.7.0"],
    }),encoding="utf8")
    images=plugin/"Override/Assets/GUI/Images"
    images.mkdir(parents=True)
    Image.new("RGBA",(23,17),(42,65,99,255)).save(images/"logo.png")
    video=plugin/"Override/Assets/GUI/Video"
    video.mkdir(parents=True)
    (video/"background.webm").write_bytes(
        b"\x1a\x45\xdf\xa3\x91\x42\x82\x84webm"+b"x"*80)
    patches=plugin/"Patches/Assets/GUI/XAML"
    patches.mkdir(parents=True)
    (patches/"FrontendMenus.xaml").write_text(
        '<Patch><Operation Type="SetAttribute" XPath="//n:Grid" '
        'AttributeName="Visibility" Value="Visible"/></Patch>',
        encoding="utf8")
    locale=plugin/"Locales/de-DE"
    locale.mkdir(parents=True)
    (locale/"crusader.txt").write_bytes(
        b"deDE\n>>TEXTSTART\n>>6-----\nHauptmenu\n")
    (plugin/"StrongholdOrigins.Core.dll").write_bytes(b"MZ synthetic native module")
    season=plugin/"Seasons/winterpack"
    season.mkdir(parents=True)
    (season/"pack.json").write_text(
        '{"schema":1,"groups":[]}',encoding="utf8")
    return plugin,base


def _sha(path):
    return sha256(path.read_bytes()).hexdigest()


def test_origins_static_plugin_import_preserves_hierarchy_and_omits_runtime(originals):
    plugin,workdir=originals
    original={
        f.relative_to(plugin).as_posix():_sha(f)
        for f in plugin.rglob("*") if f.is_file()
    }
    result=importer.import_static_origins(
        plugin=plugin,project_slug="origins-manual-copy")
    target=Path(result["project"])
    assert result["file_count"]==4
    assert result["original_supported_game_versions"]==["2.7.0"]
    assert result["native_runtime_dll_imported"] is False
    assert result["season_runtime_imported"] is False
    assert result["in_game_behaviour_attested"] is False
    assert (target/"Patches/Assets/GUI/XAML/FrontendMenus.xaml").is_file()
    assert (target/"Override/Assets/GUI/Video/background.webm").is_file()
    assert (target/"Locales/de-DE/crusader.txt").is_file()
    assert not (target/"Seasons").exists()
    assert not (target/"StrongholdOrigins.Core.dll").exists()
    receipt=workdir/".origins-import-receipts"/"origins-manual-copy.json"
    assert receipt.is_file()
    assert json.loads(receipt.read_text("utf8"))["resource_sha256"]==result[
        "resource_sha256"]
    assert {
        f.relative_to(plugin).as_posix():_sha(f)
        for f in plugin.rglob("*") if f.is_file()
    }==original
    built=package.build(target,"originsassetsonly",
                       name="Origins static-only",author="local QA")
    assert built["runtime_dll"] is False
    assert built["source_files"]==4
    assert not (workdir/"origins-manual-copy"/"BepInEx").exists()
    with pytest.raises(work.WorkshopError,match="already exists"):
        importer.import_static_origins(
            plugin=plugin,project_slug="origins-manual-copy")


def test_user_can_import_customized_origins_assets_despite_old_manifest(originals):
    plugin,workdir=originals
    name="Override/Assets/GUI/Images/logo.png"
    path=plugin/name
    manifest={
        "schema":"stronghold-origins-branding-v1",
        "files":[{"path":name,"bytes":path.stat().st_size,
                  "sha256":_sha(path)}],
    }
    (plugin/"branding-manifest.json").write_text(
        json.dumps(manifest),encoding="utf8")
    first=importer.import_static_origins(plugin=plugin,project_slug="origins-checked")
    assert first["user_modified_resources_accepted"]==[]
    # A valid user-edited image is allowed; the historical manifest describes
    # its old original, not a restriction on further manual editing.
    Image.new("RGBA",(23,17),(90,130,200,255)).save(path)
    second=importer.import_static_origins(plugin=plugin,project_slug="origins-custom")
    assert second["user_modified_resources_accepted"]==[name]
    assert (workdir/"origins-custom"/name).read_bytes()==path.read_bytes()
    assert second["baseline_hashes_are_editable_references_not_write_locks"]


@pytest.mark.parametrize("unsafe",["","a","../escape","CON","a\\b","x"*54])
def test_invalid_project_slug_never_creates_output(originals,unsafe):
    plugin,workdir=originals
    with pytest.raises(work.WorkshopError):
        importer.import_static_origins(plugin=plugin,project_slug=unsafe)
    assert not (workdir/"origins-manual-copy").exists()


def test_plugin_executable_in_static_override_is_not_silently_accepted(originals):
    plugin,workdir=originals
    malicious=plugin/"Override/Assets/GUI/Scripts/hook.exe"
    malicious.parent.mkdir(parents=True)
    malicious.write_bytes(b"MZ")
    with pytest.raises(work.WorkshopError,match="Unsafe/static unsupported"):
        importer.import_static_origins(plugin=plugin,project_slug="origins-refused")
    assert not (workdir/"origins-refused").exists()


def test_game_root_cannot_be_mistaken_for_origin_plugin(originals,tmp_path):
    plugin,workdir=originals
    game=tmp_path/"Stronghold Crusader Definitive Edition"
    game.mkdir()
    (game/"Game.exe").write_bytes(b"MZ")
    with pytest.raises(work.WorkshopError,match="plugin info|source"):
        importer.import_static_origins(plugin=game,project_slug="origins-not-game")
    assert not (workdir/"origins-not-game").exists()

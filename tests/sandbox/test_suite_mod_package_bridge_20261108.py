"""Cross-workflow regression: free mod files coexist with strict static exporter.

No game installation, SE startup, DLL load or arbitrary script execution.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from zipfile import ZipFile

from PIL import Image
import pytest

import se_asset_package as pkg


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    root = tmp_path / "private-suite"
    work = root / "work"
    work.mkdir(parents=True)
    monkeypatch.setattr(pkg, "ROOT", root)
    monkeypatch.setattr(pkg, "WORK", work)
    monkeypatch.setattr(pkg, "OUT", work / "se-asset-mods")
    source = work / "projects" / "my-project"
    source.mkdir(parents=True)
    return source, work


def test_dotted_name_zip_keeps_full_name_and_detects_existing_output(sandbox):
    source, work = sandbox
    file = source / "Override" / "Sprites" / "safe.png"
    file.parent.mkdir(parents=True)
    Image.new("RGBA", (2, 3), (1, 2, 3, 255)).save(file)
    target = work / "se-asset-mods" / "my.mod-export-abcdef"
    assert pkg.package_zip_path(target).name == "my.mod-export-abcdef.zip"
    output = pkg.build(source, "my.mod", name="Safe", author="QA", target=target)
    assert Path(output["zip"]) == pkg.package_zip_path(target)
    assert Path(output["zip"]).is_file()
    with pytest.raises(pkg.AssetModError, match="existiert"):
        pkg.build(source, "my.mod", name="Safe", author="QA", target=target)


def test_unrestricted_custom_manifest_is_byte_exact_and_never_runs_code(sandbox):
    source, work = sandbox
    items = {
        "Plugins/Custom.dll": b"MZ\x01\x00",
        "Scripts/init.lua": b"this function is never executed",
        "Override/Audio/Air.ogg": b"OggS\x00",
        "Override/Sprites/custom.dds.extra": b"strange bytes\x00",
        "info.json": b'{"GUID":"user.authored","Manifest":4}\n',
    }
    for rel, blob in items.items():
        target = source.joinpath(*rel.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob)
    assert pkg.mod_relative_path("Plugins/Custom.dll").as_posix() == "Plugins/Custom.dll"
    result = pkg.build(source, "custom.mod", name="Private", author="QA",
                       target=work/"se-asset-mods"/"custom.mod-export-001",
                       unrestricted=True)
    assert result["user_manifest_preserved"] is True
    assert result["runtime_dll"] is True
    assert result["native_game_runtime_verified"] is False
    assert result["schema"] == "sprite-suite.unrestricted-mod-bundle.v1"
    assert Path(result["zip"]).name == "custom.mod-export-001.zip"
    with ZipFile(result["zip"]) as z:
        assert z.testzip() is None
        assert len(z.namelist()) == len(items)
        for rel, blob in items.items():
            assert z.read(f"BepInEx/plugins/custom.mod/{rel}") == blob
    for rel, blob in items.items():
        assert source.joinpath(*rel.split("/")).read_bytes() == blob


def test_default_static_mode_never_accepts_custom_plugin_dll(sandbox):
    source, work = sandbox
    file = source/"Plugins"/"Custom.dll"
    file.parent.mkdir()
    file.write_bytes(b"MZ")
    (source/"info.json").write_text('{"GUID":"custom.mod","Manifest":4}\n')
    with pytest.raises(pkg.AssetModError):
        pkg.build(source, "custom.mod", name="Static", author="QA", strict_static=True)
    assert not (work/"se-asset-mods"/"custom.mod").exists()


def test_custom_runtime_without_manifest_remains_exportable(sandbox):
    source, work = sandbox
    path = source/"Plugins"/"Custom.dll"
    path.parent.mkdir()
    path.write_bytes(b"MZ")
    result = pkg.build(source, "custom.mod", name="No manifest", author="QA",
                       unrestricted=True)
    assert result["runtime_dll"] is True
    assert result["native_game_runtime_verified"] is False
    with ZipFile(result["zip"]) as archive:
        assert archive.read("BepInEx/plugins/custom.mod/Plugins/Custom.dll") == b"MZ"


@pytest.mark.parametrize("relative", [
    "../traversal.txt", "x/../hack.lua", "/absolute.ini", "C:/absolute",
    "Plugins\\Hack.dll", "Plugins/CON",
    "Plugins/a:b", "Plugins//broken", "info.json/", "Plugins/ ",
])
def test_invalid_paths_fail_closed_for_custom_mods(relative):
    with pytest.raises(pkg.AssetModError, match="Unsicherer"):
        pkg.mod_relative_path(relative)


def test_explicit_custom_output_can_use_selected_directory(sandbox, tmp_path):
    source, work = sandbox
    (source/"info.json").write_text('{"GUID":"custom.mod","Manifest":4}')
    (source/"Scripts").mkdir()
    (source/"Scripts"/"safe.lua").write_bytes(b"return 1")
    result = pkg.build(source, "custom.mod", name="Private", author="QA",
                       unrestricted=True, target=tmp_path/"outside")
    assert Path(result["asset_mod_folder"]) == tmp_path/"outside"
    assert result["installed_into_game"] is False


def test_custom_metadata_bytes_are_not_rewritten(sandbox):
    source, work = sandbox
    (source/"info.json").write_bytes(b"not valid json")
    result = pkg.build(source, "custom.mod", name="Metadata", author="QA",
                       unrestricted=True)
    assert result["manifest"] is None
    with ZipFile(result["zip"]) as archive:
        assert archive.read("BepInEx/plugins/custom.mod/info.json") == b"not valid json"


def test_explicit_draft_mode_preserves_dll_but_never_claims_abi(sandbox):
    source, work = sandbox
    dll = source/"Plugins"/"Modular.dll"
    dll.parent.mkdir()
    dll.write_bytes(b"MZ\x00\xff")
    out = pkg.build(
        source, "local.mod.draft", name="Local", author="QA",
        version="preview 2", unrestricted=True,
        allow_unverified_runtime_archive=True,
        target=work/"se-asset-mods"/"local.mod-draft")
    assert out["unverified_runtime_archive"] is True
    assert out["runtime_dll"] is True
    assert out["native_game_runtime_verified"] is False
    assert out["runtime_plugin_abi_verified"] is False
    assert out["installed_into_game"] is False
    assert "DRAFT offline archive" in out["manifest"]["Description"]
    assert out["manifest"]["Version"] == "preview 2"
    with ZipFile(out["zip"]) as archive:
        assert archive.read(
            "BepInEx/plugins/local.mod.draft/Plugins/Modular.dll") == b"MZ\x00\xff"
    assert dll.read_bytes() == b"MZ\x00\xff"


def test_publish_save_as_zip_is_atomic_and_never_overwrites(tmp_path):
    from suite_unified_project import _publish_selected_zip, UnifiedFlowError
    root = tmp_path/"work"
    root.mkdir()
    source = root/"internal.zip"
    source.write_bytes(b"\x50\x4b\x03\x04FAKE BINARY TEST")
    user = tmp_path/"chosen"
    user.mkdir()
    destination = user/"Meine.Mod.zip"
    assert _publish_selected_zip(source, destination) == destination
    assert destination.read_bytes() == source.read_bytes()
    with pytest.raises(UnifiedFlowError, match="nicht neu"):
        _publish_selected_zip(source, destination)
    assert destination.read_bytes() == source.read_bytes()
    assert len(list(user.iterdir())) == 1


def test_save_as_zip_never_writes_into_game_mod_or_data_path(tmp_path):
    from suite_unified_project import _publish_selected_zip, UnifiedFlowError
    source = tmp_path/"internal.zip"
    source.write_bytes(b"not installable")
    bepinex = tmp_path/"BepInEx"
    bepinex.mkdir()
    with pytest.raises(UnifiedFlowError):
        _publish_selected_zip(source, bepinex/"danger.zip")
    data = tmp_path/"Crusader_Data"
    data.mkdir()
    with pytest.raises(UnifiedFlowError):
        _publish_selected_zip(source, data/"danger.zip")
    assert not list(bepinex.iterdir()) and not list(data.iterdir())

"""Untrusted synthetic installer trees: precise hashes and no game mutation."""
from __future__ import annotations

import hashlib
from pathlib import Path
import os

import pytest
from stronghold_europe_de import installer as install


def test_tree_proof_is_read_only_and_detects_byte_changes(tmp_path):
    package=tmp_path/"synthetic-mod"
    (package/"BepInEx").mkdir(parents=True)
    owned=package/"BepInEx"/"info.json"
    owned.write_bytes(b'{"id":"fake"}')
    before=owned.read_bytes()
    proof=install._scan_tree(package,"synthetic")
    assert proof.file_hashes()["BepInEx/info.json"]==hashlib.sha256(before).hexdigest()
    install._assert_tree_proof(package,proof,"synthetic")
    assert owned.read_bytes()==before
    owned.write_bytes(b'{"id":"changed"}')
    with pytest.raises(install.InstallError,match="changed"):
        install._assert_tree_proof(package,proof,"synthetic")
    assert owned.read_bytes()==b'{"id":"changed"}'


def test_installer_tree_proof_detects_added_file_and_removed_file(tmp_path):
    package=tmp_path/"synthetic"
    package.mkdir()
    first=package/"a.png"
    first.write_bytes(b"the first image")
    proof=install._scan_tree(package,"synthetic")
    second=package/"b.png"
    second.write_bytes(b"new image")
    with pytest.raises(install.InstallError,match="changed"):
        install._assert_tree_proof(package,proof,"synthetic")
    second.unlink()
    first.unlink()
    with pytest.raises(install.InstallError,match="changed"):
        install._assert_tree_proof(package,proof,"synthetic")


@pytest.mark.parametrize("bad",[
    "CON", "CON.png","NUL.ini","AUX.dat","PRN",
    "COM1","COM9.png","LPT9.txt","COM¹.png","COM².dat","LPT³.ini",
    "CONIN$","CONOUT$","bad.", "bad ", "has:colon", "../escape",
    "has\\slash", "has?query", "a\x00b",
])
def test_installer_rejects_reserved_windows_file_components(bad):
    with pytest.raises(install.InstallError,match="Unsafe"):
        install._safe_component(bad,"test component")


def test_installer_refuses_case_colliding_proof_paths():
    with pytest.raises(install.InstallError,match="colliding"):
        install._expected_directories({
            "Images/Crop.png":"a"*64, "images/crop.PNG":"b"*64,
        },"synthetic paths")


def test_installer_refuses_invalid_owned_paths():
    for value in ("../escape","a//b","a/../b","C:/windows/file.txt",
                  "/abs","a\\b"):
        with pytest.raises(install.InstallError):
            install._safe_owned_relative(value,"synthetic")


def test_installer_refuses_linked_artwork_without_following_it(tmp_path):
    package=tmp_path/"synthetic-mod"
    package.mkdir()
    outside=tmp_path/"private-source.txt"
    outside.write_bytes(b"protected source")
    linked=package/"linked.txt"
    try:
        linked.symlink_to(outside)
    except (OSError,NotImplementedError):
        pytest.skip("This Windows account cannot create a test symlink")
    with pytest.raises(install.InstallError,match="link"):
        install._scan_tree(package,"synthetic")
    assert outside.read_bytes()==b"protected source"


def test_game_running_guard_uses_executable_full_path_only(tmp_path,monkeypatch):
    from types import SimpleNamespace
    configured=tmp_path/"game-x"
    configured.mkdir()
    config=SimpleNamespace(target=SimpleNamespace(game_dir=configured))
    expected=configured/install._TARGET_GAME_EXECUTABLE
    different=tmp_path/"game-y"/install._TARGET_GAME_EXECUTABLE
    monkeypatch.setattr(install,"_enumerate_windows_process_images",
                        lambda name:(install._ProcessImage(37,str(different)),))
    install._assert_target_game_not_running(config,"synthetic preflight")
    monkeypatch.setattr(install,"_enumerate_windows_process_images",
                        lambda name:(install._ProcessImage(42,str(expected)),))
    with pytest.raises(install.InstallError,match="PID 42"):
        install._assert_target_game_not_running(config,"synthetic preflight")

"""Regression tests: legacy SHCDE-SE 2.11 must never downgrade v2.14.3."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import ziel_se211 as old


def test_newest_extender_is_kept_without_any_downgrade_or_backup(tmp_path, monkeypatch):
    game = tmp_path / "Stronghold Crusader Definitive Edition"
    dll = game / "BepInEx/plugins/000shcdese/SHCDESE.dll"
    dll.parent.mkdir(parents=True)
    dll.write_bytes(b"keep-installed-v2.14.3")
    monkeypatch.setattr(old, "resolve", lambda _: ("synthetic", game))
    monkeypatch.setattr(old, "safe_target", lambda _: game)
    monkeypatch.setattr(old, "file_version", lambda _: "2.14.3.0")
    monkeypatch.setattr(old, "game_running", lambda: False)
    monkeypatch.setattr(old, "make_backup", lambda *a: pytest.fail("Must not back up or write"))
    monkeypatch.setattr(old, "se_zip", lambda *_: pytest.fail("No ZIP inspection needed"))
    assert old.cmd_se_installieren(SimpleNamespace(name="synthetic", zip=None))==0
    assert dll.read_bytes() == b"keep-installed-v2.14.3"
    assert not (game/"_suite-sicherungen").exists()


def test_unknown_extender_label_is_kept_and_not_overwritten(tmp_path, monkeypatch):
    game = tmp_path / "game"
    dll = game / "BepInEx/plugins/000shcdese/SHCDESE.dll"
    dll.parent.mkdir(parents=True)
    dll.write_bytes(b"cannot-read-dll-metadata")
    monkeypatch.setattr(old, "resolve", lambda _: ("target", game))
    monkeypatch.setattr(old, "safe_target", lambda _: game)
    monkeypatch.setattr(old, "file_version", lambda _: None)
    monkeypatch.setattr(old, "game_running", lambda: False)
    monkeypatch.setattr(old, "make_backup", lambda *args: pytest.fail("No writes"))
    assert old.cmd_se_installieren(SimpleNamespace(name="target", zip=None)) == 0
    assert dll.read_bytes() == b"cannot-read-dll-metadata"



def test_apishared_newer_requirement_preserves_installed_game(tmp_path,monkeypatch):
    game=tmp_path/"Crusader"
    plugin=game/"BepInEx/plugins/APIShared_Serp"
    plugin.mkdir(parents=True)
    (plugin/"info.json").write_text(
        json.dumps({"Version":"0.9.2","MinimumScriptExtenderVersion":"2.14.0"}),
        encoding="utf8"
    )
    monkeypatch.setattr(old,"resolve",lambda _:("test",game))
    monkeypatch.setattr(old,"safe_target",lambda _:game)
    monkeypatch.setattr(old,"game_running",lambda:False)
    monkeypatch.setattr(old,"make_backup",lambda *args:pytest.fail("No game writes"))
    monkeypatch.setattr(old,"se_zip",lambda *_:pytest.fail("No archive needed"))
    assert old.cmd_se_installieren(SimpleNamespace(name="test",zip=None))==0
    assert not (game/"_suite-sicherungen").exists()

def test_unrecognized_legacy_zip_hash_is_rejected(tmp_path, monkeypatch):
    archive=tmp_path/"SHCDESE-2.14.3.zip"
    archive.write_bytes(b"fake-release-not-official")
    with pytest.raises(SystemExit,match="SHA-256"):
        old.se_zip(str(archive))
    assert archive.read_bytes() == b"fake-release-not-official"


@pytest.mark.parametrize("name,running",[
    ("Stronghold Crusader Definitive Edition.exe",True),
    ("Stronghold Crusader.exe",True),
    ("notepad.exe",False),
])
def test_real_process_names_used_for_install_lock(monkeypatch,name,running):
    output=f'"{name}","18300","Console","1","10,000 K"\n'
    def run(*_a, **_kw):
        return SimpleNamespace(stdout=output,returncode=0)
    monkeypatch.setattr(old.subprocess, "run", run)
    assert old.game_running() is running


def test_failed_tasklist_blocks_legacy_installer(monkeypatch):
    monkeypatch.setattr(
        old.subprocess,"run",lambda *_a, **_kw:
        SimpleNamespace(stdout="error",returncode=1),
    )
    assert old.game_running() is True

"""Tests for HUD/menu session persistence: only safe relative metadata."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"tools"))
import hud_menu_workspace as model
import suite_hud_menu_session as session


@pytest.fixture
def workspace_root(tmp_path,monkeypatch):
    suite=tmp_path/"suite"
    work=suite/"work"
    work.mkdir(parents=True)
    monkeypatch.setattr(model,"ROOT",suite)
    monkeypatch.setattr(model,"WORK",work)
    project=model.workspace(work/"menu-project",create=True)
    return suite,work,project


def test_remembers_project_and_resource_without_absolute_machine_paths(workspace_root):
    suite,work,project=workspace_root
    key="Override/Assets/GUI/Images/MeinBild.png"
    session.save_session(project,key)
    state=session.read_session()
    assert state=={"project":project,"asset":key,"scene":""}
    serialized=(work/session.NAME).read_text("utf8")
    assert "menu-project" in serialized
    assert str(suite) not in serialized
    assert "C:\\" not in serialized
    assert "MeinBild.png" in serialized


def test_relocated_portable_workspace_finds_same_project(workspace_root,tmp_path,monkeypatch):
    suite,work,project=workspace_root
    session.save_session(project,"Override/Assets/GUI/Images/Button.png",
                         scene="MeinLayout-2")
    moved=tmp_path/"portable newer folder"
    shutil.copytree(suite,moved)
    monkeypatch.setattr(model,"ROOT",moved)
    monkeypatch.setattr(model,"WORK",moved/"work")
    result=session.read_session()
    assert result["project"]==moved/"work"/"menu-project"
    assert result["asset"].endswith("Button.png")
    assert result["scene"]=="MeinLayout-2"


def test_missing_deleted_or_corrupt_session_never_blocks_opening(workspace_root):
    suite,work,project=workspace_root
    assert session.read_session()=={}
    session.save_session(project)
    shutil.rmtree(project)
    assert session.read_session()=={}
    path=work/session.NAME
    path.write_text("not valid json",encoding="utf8")
    assert session.read_session()=={}
    path.write_bytes(b"x"*(session.MAX_BYTES+1))
    assert session.read_session()=={}


def test_path_traversal_and_outside_paths_are_refused(workspace_root):
    suite,work,project=workspace_root
    path=work/session.NAME
    for relative in ("../outside", "../menu-project", "C:/Windows/System32",
                     "/absolute/path", "missing/project"):
        path.write_text(json.dumps({"schema":session.SCHEMA,
                                    "workspace":relative, "asset":""}),
                        encoding="utf8")
        assert session.read_session()=={}
    with pytest.raises(model.WorkshopError):
        session.save_session(project,"../../outside.png")
    assert session.read_session()=={}


def test_symlinked_preference_file_is_not_followed(workspace_root,tmp_path):
    suite,work,project=workspace_root
    state=work/session.NAME
    target=tmp_path/"external-sensitive.txt"
    target.write_text("do not overwrite",encoding="utf8")
    try:
        state.symlink_to(target)
    except (OSError,NotImplementedError):
        pytest.skip("This Windows configuration cannot create symlinks")
    assert session.read_session()=={}
    with pytest.raises(model.WorkshopError):
        session.save_session(project)
    assert target.read_text("utf8")=="do not overwrite"


def test_unwritable_session_metadata_does_not_escape_work(workspace_root):
    suite,work,project=workspace_root
    state=work/session.NAME
    state.mkdir()
    with pytest.raises(model.WorkshopError):
        session.save_session(project)
    assert not list(suite.glob("*.json"))


def test_last_scene_and_last_image_preserve_each_other(workspace_root):
    suite,work,project=workspace_root
    session.save_session(project,"Override/Assets/GUI/Images/Original.png")
    session.save_session(project,scene="Persoenliches-Layout")
    assert session.read_session()["asset"].endswith("Original.png")
    assert session.read_session()["scene"]=="Persoenliches-Layout"
    session.save_session(project,"Override/Assets/GUI/Images/Second.png")
    assert session.read_session()["scene"]=="Persoenliches-Layout"
    assert session.read_session()["asset"].endswith("Second.png")
    different=model.workspace(work/"another-project",create=True)
    session.save_session(different)
    assert session.read_session()=={"project":different,"asset":"","scene":""}


def test_untrusted_scene_names_are_dropped_or_rejected(workspace_root):
    suite,work,project=workspace_root
    state=work/session.NAME
    for name in ("../stolen","C:Absolute","bad name","über 1", "x"*49):
        state.write_text(json.dumps({
            "schema":session.SCHEMA,"workspace":"menu-project",
            "asset":"","scene":name,
        }),encoding="utf8")
        assert session.read_session()["scene"]==""
        with pytest.raises(model.WorkshopError):
            session.save_session(project,scene=name)

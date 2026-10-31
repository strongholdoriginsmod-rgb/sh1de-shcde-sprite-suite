"""Synthetic fail-injection contracts for guarded multi-file output publication."""
from __future__ import annotations
import hashlib
import os
from pathlib import Path

import pytest
from suite_output_transaction import OutputBatch, OutputConflictError


def tree(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix():p.read_bytes()
            for p in root.rglob("*") if p.is_file()} if root.exists() else {}


def test_publish_creates_two_files_but_keeps_foreign_file(tmp_path):
    dest=tmp_path/"results"
    dest.mkdir()
    (dest/"other-user-notes.txt").write_bytes(b"do not remove me")
    with OutputBatch(dest) as batch:
        batch.stage("a.png").write_bytes(b"one")
        batch.stage("b.png").write_bytes(b"two")
        batch.publish()
    assert tree(dest)=={"a.png":b"one","b.png":b"two",
                        "other-user-notes.txt":b"do not remove me"}


def test_prep_failure_never_creates_output(tmp_path):
    dest=tmp_path/"new-output"
    with pytest.raises(OSError, match="before publishing"):
        with OutputBatch(dest) as batch:
            batch.stage("a.png").write_bytes(b"prepared")
            raise OSError("before publishing")
    assert not dest.exists()
    assert not list(tmp_path.glob(".spritesuite-output-*"))


@pytest.mark.parametrize("present",[False,True])
@pytest.mark.parametrize("fail_at",[1,2])
def test_publish_failure_recovers_previous_files(tmp_path,monkeypatch,present,fail_at):
    dest=tmp_path/"results"
    if present:
        dest.mkdir()
        (dest/"a.png").write_bytes(b"old a")
        (dest/"b.png").write_bytes(b"old b")
    previous=tree(dest)
    old_replace=os.replace
    called=[]

    def interrupted_replace(src,dst):
        if Path(dst).parent==dest:
            called.append(Path(dst).name)
            if len(called)==fail_at:
                raise OSError("injected disk failure")
        return old_replace(src,dst)

    monkeypatch.setattr(os,"replace",interrupted_replace)
    with pytest.raises(OSError,match="injected disk"):
        with OutputBatch(dest) as batch:
            batch.stage("a.png").write_bytes(b"new a")
            batch.stage("b.png").write_bytes(b"new b")
            batch.publish()
    assert tree(dest)==previous
    assert not list(tmp_path.glob(".spritesuite-output-*"))


def test_external_change_while_generating_is_preserved(tmp_path):
    dest=tmp_path/"results"
    dest.mkdir()
    (dest/"a.png").write_bytes(b"original a")
    with pytest.raises(OutputConflictError,match="während der Vorbereitung"):
        with OutputBatch(dest) as batch:
            batch.stage("a.png").write_bytes(b"new")
            (dest/"a.png").write_bytes(b"user updated outside program")
            batch.publish()
    assert (dest/"a.png").read_bytes()==b"user updated outside program"


def test_external_change_during_backup_aborts_without_any_write(tmp_path,monkeypatch):
    import suite_output_transaction as module
    dest=tmp_path/"results"
    dest.mkdir()
    a=dest/"a.png"
    a.write_bytes(b"old")
    baseline=module.shutil.copyfile

    def changed_mid_backup(src,dst,*args,**kwargs):
        result=baseline(src,dst,*args,**kwargs)
        if Path(src)==a:
            a.write_bytes(b"externally edited")
        return result

    monkeypatch.setattr(module.shutil,"copyfile",changed_mid_backup)
    with pytest.raises(OutputConflictError,match="änderte"):
        with OutputBatch(dest) as batch:
            batch.stage("a.png").write_bytes(b"new")
            batch.publish()
    assert a.read_bytes()==b"externally edited"


@pytest.mark.parametrize("name",["CON.png","LPT1.txt","a/b.png",
                                  "sub\\file.png","hi?.png","README.",
                                  "a.png","a.png"])
def test_output_names_validate_portable_windows_rules(tmp_path,name):
    if name=="a.png":
        with OutputBatch(tmp_path/"out") as batch:
            batch.stage("a.png").write_bytes(b"a")
            with pytest.raises(OutputConflictError):
                batch.stage("A.PNG")
        return
    with OutputBatch(tmp_path/"out") as batch:
        with pytest.raises(OutputConflictError):
            batch.stage(name)


def test_rollback_does_not_overwrite_external_replacement(tmp_path,monkeypatch):
    import suite_output_transaction as module
    dest=tmp_path/"results"
    dest.mkdir()
    a=dest/"a.png"
    b=dest/"b.png"
    a.write_bytes(b"old a")
    b.write_bytes(b"old b")
    actual=module.os.replace
    stage_calls=[0]

    def replace_with_intervening_write(src,dst):
        if Path(dst).parent==dest:
            stage_calls[0]+=1
            if stage_calls[0]==2:
                a.write_bytes(b"user modified after our first write")
                raise OSError("simulated publication failure")
        return actual(src,dst)

    monkeypatch.setattr(module.os,"replace",replace_with_intervening_write)
    with pytest.raises(OutputConflictError,match="nicht vollständig"):
        with OutputBatch(dest) as batch:
            batch.stage("a.png").write_bytes(b"new a")
            batch.stage("b.png").write_bytes(b"new b")
            batch.publish()
    assert a.read_bytes()==b"user modified after our first write"
    assert b.read_bytes()==b"old b"
    # An unrecoverable external edit must not erase the only old backups.
    assert batch.recovery_directory is not None
    assert batch.recovery_directory.is_dir()
    assert (batch.recovery_directory/"original"/"file-00000.backup").read_bytes()==b"old a"
    assert (batch.recovery_directory/"original"/"file-00001.backup").read_bytes()==b"old b"

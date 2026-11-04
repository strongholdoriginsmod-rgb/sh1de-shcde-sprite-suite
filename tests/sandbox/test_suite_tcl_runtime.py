"""Windows Tcl/Tk cache race, corruption, env isolation and real interpreter QA."""
from __future__ import annotations
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"tools"))
from suite_tcl_runtime import (
    TclRuntimeError, SENTINELS, prepare_tcl_env, locate_bundled_tcl
)


@pytest.fixture
def source(tmp_path):
    root=tmp_path/"bundled"/"tcl"
    for i,name in enumerate(SENTINELS):
        p=root/name;p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text("Tcl library marker "+str(i),encoding="utf8")
    (root/"tcl8.6"/"some-extra-script.tcl").write_text(
        "puts demo",encoding="utf8")
    return root


def test_copy_verified_private_cache_and_reuse_identical_bytes(tmp_path,source):
    project=tmp_path/"project";project.mkdir()
    env=prepare_tcl_env(project,source=source,cache_root=tmp_path/"cache")
    assert Path(env["TCL_LIBRARY"]).is_dir()
    assert Path(env["TK_LIBRARY"]).is_dir()
    assert env["SPRITESUITE_TCL_RUNTIME_SOURCE"]=="private-verified-cache"
    cached=Path(env["SPRITESUITE_TCL_RUNTIME_ROOT"])
    for name in SENTINELS:
        assert (cached/name).read_bytes()==(source/name).read_bytes()
    assert (cached/"tcl8.6"/"some-extra-script.tcl").is_file()
    again=prepare_tcl_env(project,source=source,cache_root=tmp_path/"cache")
    assert again==env
    assert (cached/"cache-receipt.json").is_file()


def test_cache_corruption_is_reported_and_never_overwritten(tmp_path,source):
    project=tmp_path/"project";project.mkdir()
    env=prepare_tcl_env(project,source=source,cache_root=tmp_path/"cache")
    p=Path(env["SPRITESUITE_TCL_RUNTIME_ROOT"])/"tcl8.6"/"init.tcl"
    p.write_bytes(b"BAD INTENTIONAL CONTENT")
    with pytest.raises(TclRuntimeError,match="beschädigt"):
        prepare_tcl_env(project,source=source,cache_root=tmp_path/"cache")
    assert p.read_bytes()==b"BAD INTENTIONAL CONTENT"


def test_missing_script_rejected_before_launcher_creates_state(tmp_path,source):
    (source/"tk8.6"/"tk.tcl").unlink()
    project=tmp_path/"project";project.mkdir()
    with pytest.raises(TclRuntimeError):
        locate_bundled_tcl(project,explicit=source)
    assert not (tmp_path/"cache").exists()


@pytest.mark.skipif(sys.platform!="win32",reason="native Tcl/Tk is Windows-specific")
def test_native_tk_stress_with_untrusted_environment_and_verified_cache(tmp_path):
    try:
        base=locate_bundled_tcl(ROOT)
    except TclRuntimeError as exc:
        pytest.skip("No real local Tk runtime available: "+str(exc))
    env=prepare_tcl_env(ROOT,source=base,cache_root=tmp_path/"private")
    program=(
        "from suite_tcl_runtime import create_tk_root;"
        "[(lambda r:(r.withdraw(),r.update_idletasks(),r.destroy()))(create_tk_root()) "
        "for _ in range(16)];"
        "print('VERIFIED_TCL_TK_RECREATIONS=16')"
    )
    run=subprocess.run([sys.executable,"-c",program],
        capture_output=True,text=True,
        timeout=35,env={**os.environ,
                "TCL_LIBRARY":"C:/invalid/nonexistent/tcl8.6",
                "TK_LIBRARY":"C:/invalid/nonexistent/tk8.6",
                "PYTHONPATH":str(ROOT/"tools")+os.pathsep+str(ROOT/"src"),**env})
    assert run.returncode==0,run.stderr
    assert "VERIFIED_TCL_TK_RECREATIONS=16" in run.stdout


def _synthetic_zipfs9(tmp_path):
    from zipfile import ZipFile
    folder=tmp_path/"python-tcl9"
    folder.mkdir()
    with ZipFile(folder/"libtcl9.0.4.zip","w") as archive:
        archive.writestr("tcl_library/init.tcl","puts {Tcl 9 private sample}")
        archive.writestr("tcl_library/auto.tcl","puts {"+("x"*1500)+"}")
    with ZipFile(folder/"libtk9.0.4.zip","w") as archive:
        archive.writestr("tk_library/extra.tcl","puts {"+("x"*1500)+"}")
        for name in ("tk_library/tk.tcl", "tk_library/ttk/ttk.tcl",
                     "tk_library/ttk/panedwindow.tcl"):
            archive.writestr(name,"puts {Tk 9 private sample}")
    return folder


def test_zipfs9_source_validation_uses_native_archive_without_unpacking(tmp_path):
    folder=_synthetic_zipfs9(tmp_path)
    project=tmp_path/"project";project.mkdir()
    destination=tmp_path/"new-cache"
    values=prepare_tcl_env(project,source=folder,cache_root=destination)
    assert values["SPRITESUITE_TCL_RUNTIME_SOURCE"]=="native-verified-zipfs9"
    assert values["SPRITESUITE_TCL_RUNTIME_ROOT"]==str(folder.resolve())
    assert "TCL_LIBRARY" not in values and "TK_LIBRARY" not in values
    assert not destination.exists()
    assert (folder/"libtcl9.0.4.zip").is_file()


@pytest.mark.parametrize("damage",["missing","corrupt","required-member","traversal"])
def test_zipfs9_rejects_missing_corrupt_or_unsafe_scripts(tmp_path,damage):
    from zipfile import ZipFile
    folder=_synthetic_zipfs9(tmp_path)
    archive=folder/"libtk9.0.4.zip"
    if damage=="missing":
        archive.unlink()
    elif damage=="corrupt":
        archive.write_bytes(b"bad-not-zip")
    elif damage=="required-member":
        with ZipFile(archive,"w") as writer:
            writer.writestr("tk_library/tk.tcl","not enough scripts")
    else:
        with ZipFile(archive,"a") as writer:
            writer.writestr("../unsafe.tcl","not allowed")
    project=tmp_path/"project";project.mkdir()
    with pytest.raises(TclRuntimeError,match="Tcl"):
        prepare_tcl_env(project,source=folder,cache_root=tmp_path/"cache")
    assert not (tmp_path/"cache").exists()


@pytest.mark.skipif(sys.platform!="win32",reason="native Windows zipfs probe")
def test_native_tcl9_installed_zipfs_ignores_poisoned_library_paths(monkeypatch):
    import tkinter as tk
    from suite_tcl_runtime import install_tcl_env
    if tk.TclVersion<9 or tk.TkVersion<9:
        pytest.skip("Python uses the existing Tcl/Tk 8.6 script cache")
    monkeypatch.setenv("TCL_LIBRARY","C:/invalid/tcl9")
    monkeypatch.setenv("TK_LIBRARY","C:/invalid/tk9")
    env=install_tcl_env(ROOT)
    assert env["SPRITESUITE_TCL_RUNTIME_SOURCE"]=="native-verified-zipfs9"
    assert os.environ.get("TCL_LIBRARY") is None
    assert os.environ.get("TK_LIBRARY") is None
    root=tk.Tk();root.withdraw();root.update_idletasks();root.destroy()


def test_explicit_foreign_zipfs9_cannot_attest_the_active_python(tmp_path):
    import tkinter as tk
    from suite_tcl_runtime import install_tcl_env
    if tk.TclVersion<9 or tk.TkVersion<9:
        pytest.skip("Only the native Tcl/Tk 9 interpreter can mount zipfs9")
    source=_synthetic_zipfs9(tmp_path)
    project=tmp_path/"project";project.mkdir()
    with pytest.raises(TclRuntimeError,match="Python|native|Interpreter"):
        install_tcl_env(project,source=source,cache_root=tmp_path/"cache")
    assert not (tmp_path/"cache").exists()

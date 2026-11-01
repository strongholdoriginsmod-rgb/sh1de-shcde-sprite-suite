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

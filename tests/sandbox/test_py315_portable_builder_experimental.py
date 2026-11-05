"""Reproducible source contracts for isolated CPython 3.15 experimental portable."""
from __future__ import annotations

from pathlib import Path
import sys

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"tools"))
import build_portable_windows as builder


def test_default_package_name_and_tested_runtime_unchanged():
    assert builder.OUT_NAME.endswith("-py313-x64.zip")
    assert "EXPERIMENTAL" in builder.EXPERIMENTAL_PY315_NAME
    assert "py315-x64" in builder.EXPERIMENTAL_PY315_NAME
    assert builder.OUT_NAME!=builder.EXPERIMENTAL_PY315_NAME


def test_py315_builder_cannot_run_without_explicit_experimental_approval(tmp_path):
    runtime=tmp_path/"runtime"
    venv=tmp_path/"venv"
    for path in (runtime,venv):path.mkdir()
    with pytest.raises(RuntimeError,match="Only tested"):
        builder.build(runtime,venv,tmp_path/"artifact",python_minor=15)
    assert not (tmp_path/"artifact").exists()


def test_py315_runtime_files_require_native_tcl_dlls():
    assert {"python315.dll","python3t.dll"}.issubset(
        builder.PY315_FILES)
    assert "tcl" not in builder.PY315_DIRS
    assert "DLLs" in builder.PY315_DIRS


def test_315_runtime_and_venv_real_source_validation_when_available():
    base=Path(r"E:\SpriteSuite_LiveGameQA_20261105\COMPAT_20261105")
    runtime=base/"cpython315-full-isolated"
    venv=base/"venv-cp315-test"
    if not runtime.is_dir() or not venv.is_dir():
        pytest.skip("Isolated CPython 3.15 test runtime not attached")
    builder._check_binary_sources_315(runtime,venv)
    version=builder._python_executable_runtime_version(runtime)
    assert version==(3,15,2)


def test_default_313_builder_source_contract_still_exposes_tcl_scripts():
    assert "python313.dll" in builder.PYTHON_FILES
    assert builder.PYTHON_DIRS==("DLLs","Lib","tcl")


def test_tested_portable_version_string_generated_from_real_executable():
    base=Path(r"E:\SpriteSuite_GuideCompatibility_FinalReview_Portable_20261104\SpriteSuite\python")
    if not base.is_dir():
        pytest.skip("Original audited bundled 3.13 Python absent")
    version=builder._python_executable_runtime_version(base)
    assert version[:2]==(3,13)



def test_real_hash_locked_python315_wheelhouse_when_available():
    q=Path(r"E:\SpriteSuite_LiveGameQA_20261105\COMPAT_20261105\py315-wheelhouse")
    if not q.is_dir():
        pytest.skip("Locally audited CPython 3.15 wheelhouse not available")
    result=builder._verify_cp315_hashed_wheelhouse(q)
    assert result["hash_locked_wheels"]==27
    assert result["wheel_bytes"]>100_000_000
    assert len(result["requirements_sha256"])==64


def test_incomplete_wheelhouse_refused_without_writing_anything(tmp_path):
    missing=tmp_path/"not-all-wheels"
    missing.mkdir()
    with pytest.raises(RuntimeError,match="Missing CPython 3.15 locked wheels"):
        builder._verify_cp315_hashed_wheelhouse(missing)

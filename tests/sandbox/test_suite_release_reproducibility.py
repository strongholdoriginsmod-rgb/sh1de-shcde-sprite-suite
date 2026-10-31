"""Portable package reproducibility, failure cleanup and version contracts."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sys
import tomllib
from zipfile import ZipFile

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"tools"))
import build_portable_windows as builder


def test_release_version_consistent_with_package_metadata():
    version=(ROOT/"VERSION").read_text("utf8").strip()
    meta=tomllib.loads((ROOT/"pyproject.toml").read_text("utf8"))
    assert version==builder.VERSION==meta["project"]["version"]
    assert builder.OUT_NAME.startswith(f"SpriteSuite-Windows-Portable-v{version}-")
    assert meta["project"]["requires-python"]==">=3.13,<3.15"
    assets=meta["project"]["optional-dependencies"]["assets"]
    assert any(row.startswith("numpy==") for row in assets)
    assert any(row.startswith("scipy==") for row in assets)


def test_zip_contents_are_reproducible_across_timestamp_changes(tmp_path):
    package=tmp_path/"source"/"SpriteSuite"
    (package/"tools").mkdir(parents=True)
    (package/"tools"/"one.py").write_bytes(b"print('hello')\n")
    (package/"README.txt").write_text("Some text\n",encoding="utf8")
    z1=tmp_path/"a.zip"
    z2=tmp_path/"b.zip"
    assert builder._write_reproducible_zip(package,z1)==2
    for file in package.rglob("*"):
        if file.is_file():
            os.utime(file,(800000000,1200000000))
    assert builder._write_reproducible_zip(package,z2)==2
    assert z1.read_bytes()==z2.read_bytes()
    with ZipFile(z1) as archive:
        assert archive.testzip() is None
        assert archive.namelist()==["SpriteSuite/README.txt","SpriteSuite/tools/one.py"]
        assert all(entry.date_time==(2026,1,1,0,0,0) for entry in archive.infolist())


def test_failed_git_source_step_cleans_entire_staging_and_published_dir(
    tmp_path, monkeypatch,
):
    fake=tmp_path/"fake-runtime"
    fake.mkdir()
    output=tmp_path/"proposed-release"
    monkeypatch.setattr(builder,"_check_binary_sources",lambda *_:None)
    # This synthetic test targets the later git-archive rollback, not the
    # protected-system-TEMP preflight tested separately below.
    monkeypatch.setattr(builder,"_is_protected_windows_temp",lambda _:False)

    def abort(*args,**kwargs):
        raise RuntimeError("synthetic git failure")

    monkeypatch.setattr(builder,"_subprocess",abort)
    with pytest.raises(RuntimeError,match="synthetic git failure"):
        builder.build(fake,fake,output)
    assert not output.exists()
    assert not list(tmp_path.glob(".spritesuite-portable-stage-*"))


def test_never_replace_existing_release_directory(tmp_path, monkeypatch):
    fake=tmp_path/"runtime"
    fake.mkdir()
    output=tmp_path/"release"
    output.mkdir()
    (output/"user-file.txt").write_bytes(b"must remain")
    monkeypatch.setattr(builder,"_check_binary_sources",lambda *_:None)
    with pytest.raises(RuntimeError,match="already exists"):
        builder.build(fake,fake,output)
    assert (output/"user-file.txt").read_bytes()==b"must remain"


def test_base_python_site_packages_are_not_bundled(tmp_path):
    """The source Python may contain private packages absent from the lock."""
    base = tmp_path / "python-base"
    (base / "Lib" / "site-packages" / "private-package").mkdir(parents=True)
    (base / "Lib" / "site-packages" / "private-package" / "secret.txt").write_bytes(
        b"must-not-be-packaged"
    )
    (base / "Lib" / "hello_stdlib.py").write_text("VALUE = 42\n", encoding="utf8")
    (base / "DLLs").mkdir()
    (base / "tcl").mkdir()
    runtime = tmp_path / "runtime"
    builder._copy_whitelist(
        base, runtime, ("Lib", "DLLs", "tcl"), exclude_base_site_packages=True
    )
    assert (runtime / "Lib" / "hello_stdlib.py").is_file()
    assert not (runtime / "Lib" / "site-packages").exists()


def test_private_venv_site_packages_are_kept_for_hash_checked_dependencies(tmp_path):
    src = tmp_path / "verified-venv"
    (src / "Lib" / "site-packages" / "PIL").mkdir(parents=True)
    (src / "Lib" / "site-packages" / "PIL" / "__init__.py").write_bytes(
        b"version = 'synthetic'"
    )
    dst = tmp_path / "private-package"
    builder._copy_whitelist(src, dst, ("Lib",))
    assert (dst / "Lib" / "site-packages" / "PIL" / "__init__.py").read_bytes() == (
        b"version = 'synthetic'"
    )


def test_portable_venv_excludes_developer_specific_launchers(tmp_path):
    venv = tmp_path / "builder-venv"
    scripts = venv / "Scripts"
    scripts.mkdir(parents=True)
    for filename in ("python.exe", "pythonw.exe"):
        (scripts / filename).write_bytes(b"the synthetic interpreter")
    (scripts / "pip.exe").write_bytes(b"C:/Users/Builder/venv/python.exe")
    (scripts / "activate.bat").write_text(
        "set VIRTUAL_ENV=C:/Users/Builder/venv\n", encoding="utf8"
    )
    (scripts / "some-other.exe").write_bytes(b"not a shipped runtime executable")

    output = tmp_path / "portable-venv"
    builder._copy_whitelist(
        venv, output, ("Scripts",), venv_python_executables_only=True
    )
    assert sorted(x.name for x in (output / "Scripts").iterdir()) == [
        "python.exe", "pythonw.exe"
    ]
    assert not (output / "Scripts" / "pip.exe").exists()


def test_portable_rejects_protected_windows_temp_before_creating_release(
    tmp_path, monkeypatch,
):
    system_root = tmp_path / "FakeWindows"
    protected_temp = system_root / "Temp"
    protected_temp.mkdir(parents=True)
    monkeypatch.setenv("SystemRoot", str(system_root))
    restricted_output = protected_temp / "new-qa-release"
    assert builder._is_protected_windows_temp(restricted_output)
    assert builder._is_protected_windows_temp(restricted_output / "nested")
    assert not builder._is_protected_windows_temp(tmp_path / "normal" / "release")
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    monkeypatch.setattr(builder, "_check_binary_sources", lambda *_args: None)
    with pytest.raises(RuntimeError, match="Windows system Temp"):
        builder.build(runtime, runtime, restricted_output)
    assert not restricted_output.exists()

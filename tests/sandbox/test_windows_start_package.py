"""Public bootstrap package boundaries and real first launch without system Python."""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile

import pytest

import build_windows_start_package as builder


ROOT = Path(__file__).resolve().parents[2]


def test_runtime_selection_excludes_installed_and_unrecognized_packages(tmp_path):
    home = tmp_path / "python"
    names = [
        *builder.RUNTIME_FILES, "python313.dll",
        "Lib/ensurepip/__init__.py",
        "Lib/ensurepip/_bundled/pip-25.2-py3-none-any.whl",
        "Lib/venv/__init__.py", "Lib/venv/scripts/nt/python.exe",
        "Lib/json/__init__.py", "DLLs/_ssl.pyd", "DLLs/libssl-3.dll",
        "Lib/site-packages/fmod_toolkit/fmod.dll",
        "Lib/site-packages/PySide6/Qt6Core.dll",
        "Lib/fmod_toolkit/__init__.py", "DLLs/Qt6Core.dll",
        "DLLs/unrecognized.pyd", "Lib/json/__pycache__/old.pyc",
        "Lib/ensurepip/_bundled/unrecognized.whl",
    ]
    for name in names:
        path = home / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic runtime source")
    selected = builder._runtime_sources(home.resolve(), {
        "version": [3, 13, 15],
        "modules": ["ensurepip", "venv", "json", "_ssl"],
        "pip": "25.2",
    })
    assert "Lib/ensurepip/_bundled/pip-25.2-py3-none-any.whl" in selected
    assert "Lib/venv/scripts/nt/python.exe" in selected
    assert "DLLs/_ssl.pyd" in selected
    assert all("site-packages" not in name for name in selected)
    assert all("fmod" not in name.lower() and "qt6" not in name.lower() for name in selected)
    assert "DLLs/unrecognized.pyd" not in selected
    assert "Lib/json/__pycache__/old.pyc" not in selected
    assert "Lib/ensurepip/_bundled/unrecognized.whl" not in selected


@pytest.mark.parametrize("name", [
    "../outside.py", "/absolute.py", "tools/escape:stream",
    ".venv/Lib/site-packages/package.py", "work/private.json",
    "config/installations.local.toml", "runtime/SHCDESE.dll",
])
def test_committed_private_or_runtime_payloads_are_rejected(name):
    with pytest.raises(ValueError):
        builder._source_name(name)


def _git(directory: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(directory), *args], capture_output=True, text=True,
        encoding="utf-8", check=True, timeout=30,
    )
    return result.stdout.strip()


@pytest.fixture(scope="module")
def start_archive(tmp_path_factory):
    configured = os.environ.get("SPRITESUITE_BOOTSTRAP_TEST_PYTHON_HOME")
    if sys.platform != "win32" or not configured:
        pytest.skip("Set SPRITESUITE_BOOTSTRAP_TEST_PYTHON_HOME to a full Windows CPython for the launch test.")
    runtime = Path(configured)
    area = tmp_path_factory.mktemp("windows-start-package")
    repo = area / "source"
    repo.mkdir()
    (repo / "tools").mkdir()
    (repo / "VERSION").write_text("2.0.0\n", encoding="utf-8")
    (repo / "Suite starten.cmd").write_bytes((ROOT / "Suite starten.cmd").read_bytes())
    (repo / "requirements-py313-win_amd64.lock").write_text(
        "synthetic==1.0 --hash=sha256:" + "0" * 64 + "\n", encoding="utf-8",
    )
    (repo / "setup.ps1").write_text(r'''
param([string]$Python)
$ErrorActionPreference = 'Stop'
# Production setup uses --require-hashes. This fixture only builds a venv.
$bundled = Join-Path $PSScriptRoot 'python\python.exe'
if ([IO.Path]::GetFullPath($Python) -ne [IO.Path]::GetFullPath($bundled)) {
    throw 'The launcher did not select the bundled interpreter.'
}
$counter = Join-Path $PSScriptRoot 'setup-attempts.txt'
$attempts = 0
if (Test-Path -LiteralPath $counter) { $attempts = [int](Get-Content -LiteralPath $counter) }
Set-Content -LiteralPath $counter -Value ($attempts + 1)
$venv = Join-Path $PSScriptRoot '.venv'
if (-not (Test-Path -LiteralPath (Join-Path $venv 'Scripts\python.exe'))) {
    & $Python -m venv --without-pip $venv
    if ($LASTEXITCODE -ne 0) { throw 'Isolated venv creation failed.' }
}
if ((Test-Path -LiteralPath (Join-Path $PSScriptRoot '.fail-setup-once')) -and $attempts -eq 0) {
    throw 'Synthetic interruption after venv creation.'
}
''', encoding="utf-8")
    (repo / "tools/suite_start.py").write_text(
        "from pathlib import Path\nimport subprocess,sys\n"
        "root=Path(__file__).resolve().parents[1]\n"
        "raise SystemExit(subprocess.run([str(root/'.venv/Scripts/python.exe'),"
        "str(root/'suite.py'),*sys.argv[1:]]).returncode)\n",
        encoding="utf-8",
    )
    (repo / "suite.py").write_text(
        "from pathlib import Path\nimport json,sys\n"
        "Path(__file__).with_name('launch-result.json').write_text(json.dumps({"
        "'executable':sys.executable,'base_prefix':sys.base_prefix,'args':sys.argv[1:]"
        "}),encoding='utf-8')\n",
        encoding="utf-8",
    )
    _git(repo, "init", "--initial-branch=main")
    _git(repo, "add", ".")
    _git(repo, "-c", "user.name=SpriteSuite Test", "-c", "user.email=test@example.invalid",
         "commit", "-m", "Synthetic bootstrap fixture")
    commit = _git(repo, "rev-parse", "HEAD")
    (repo / "uncommitted-user-file.txt").write_text("private", encoding="utf-8")
    (repo / ".venv/Lib/site-packages").mkdir(parents=True)
    (repo / ".venv/Lib/site-packages/private.py").write_text("private", encoding="utf-8")
    output = area / "release"
    result = builder.build_start_package(repo, commit, runtime, output)
    with pytest.raises(FileExistsError):
        builder.build_start_package(repo, commit, runtime, output)
    return result, repo, runtime


def test_built_start_archive_has_committed_source_bare_python_and_path_free_provenance(start_archive):
    result, source, runtime = start_archive
    with ZipFile(result.archive) as archive:
        assert archive.testzip() is None
        names = archive.namelist()
        assert "SpriteSuite/python/LICENSE.txt" in names
        assert "SpriteSuite/python/Lib/ensurepip/__init__.py" in names
        assert any(name in names for name in (
            "SpriteSuite/python/Lib/venv/scripts/nt/python.exe",
            "SpriteSuite/python/Lib/venv/scripts/nt/venvlauncher.exe",
        ))
        assert "SpriteSuite/FIRST-RUN.txt" in names
        assert not any(".venv/" in name or "site-packages/" in name for name in names)
        assert not any("fmod" in name.lower() or "pyside" in name.lower() for name in names)
        assert "SpriteSuite/uncommitted-user-file.txt" not in names
        manifest_raw = archive.read("SpriteSuite/START-PACKAGE.json").decode("utf-8")
        manifest = json.loads(manifest_raw)
        assert manifest["source_commit"] == result.source_commit
        assert manifest["first_start_requires_internet"] is True
        assert manifest["preinstalled_third_party_packages"] is False
        assert str(source) not in manifest_raw
        assert str(runtime) not in manifest_raw
    assert sha256(result.archive.read_bytes()).hexdigest() == result.sha256


def _launch(archive: Path, directory: Path, fail_first=False):
    with ZipFile(archive) as package:
        package.extractall(directory)
    root = directory / "SpriteSuite"
    if fail_first:
        (root / ".fail-setup-once").touch()
    return root


def _run_launcher(root: Path):
    environment = dict(os.environ)
    environment["PATH"] = ""
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    for name in ("PYTHONHOME", "PYTHONPATH"):
        environment.pop(name, None)
    command = Path(os.environ["SystemRoot"]) / "System32/cmd.exe"
    return subprocess.run(
        [str(command), "/d", "/c", "call", str(root / "Suite starten.cmd"), "--synthetic-test"],
        cwd=root, env=environment, input="", capture_output=True, text=True,
        errors="replace", timeout=120,
    )


def test_first_start_creates_venv_with_no_system_python_and_skips_setup_after_success(start_archive, tmp_path):
    result, _, _ = start_archive
    root = _launch(result.archive, tmp_path / "Startpaket äöü")
    first = _run_launcher(root)
    assert first.returncode == 0, first.stdout + first.stderr
    marker = json.loads((root / "launch-result.json").read_text("utf-8"))
    assert Path(marker["executable"]) == root / ".venv/Scripts/python.exe"
    assert Path(marker["base_prefix"]) == root / "python"
    assert marker["args"] == ["--synthetic-test"]
    assert (root / ".venv/spritesuite-start-ready.txt").is_file()
    assert (root / "setup-attempts.txt").read_text().strip() == "1"
    later = _run_launcher(root)
    assert later.returncode == 0, later.stdout + later.stderr
    assert (root / "setup-attempts.txt").read_text().strip() == "1"


def test_first_setup_retries_after_partial_venv_creation(start_archive, tmp_path):
    result, _, _ = start_archive
    root = _launch(result.archive, tmp_path / "retry", fail_first=True)
    first = _run_launcher(root)
    assert first.returncode != 0
    assert (root / ".venv/Scripts/python.exe").is_file()
    assert not (root / ".venv/spritesuite-start-ready.txt").exists()
    assert not (root / "launch-result.json").exists()
    later = _run_launcher(root)
    assert later.returncode == 0, later.stdout + later.stderr
    assert (root / "setup-attempts.txt").read_text().strip() == "2"
    assert (root / "launch-result.json").is_file()

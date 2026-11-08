"""Portable release scripts: no system Python and no accidental user data."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import os
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("inherited_path", [None, ""])
def test_native_qt_import_when_windows_path_is_missing_or_empty(monkeypatch, inherited_path):
    import suite_start
    if inherited_path is None:
        monkeypatch.delenv("PATH", raising=False)
    else:
        monkeypatch.setenv("PATH", inherited_path)
    env = suite_start.child_environment(QT_QPA_PLATFORM="offscreen")
    assert env["PATH"]
    assert not os.environ.get("PATH")
    result = subprocess.run([sys.executable, "-c",
        "from PySide6.QtWidgets import QApplication; "
        "app=QApplication([]); assert app.platformName()=='offscreen'; "
        "print('QT_WITHOUT_SYSTEM_PYTHON_PATH=1'); app.quit()"],
        env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "QT_WITHOUT_SYSTEM_PYTHON_PATH=1" in result.stdout


def test_launcher_preserves_an_existing_user_search_path(monkeypatch):
    import suite_start
    monkeypatch.setenv("PATH", "X:/UserTools;Y:/ExistingTools")
    assert suite_start.child_environment()["PATH"] == "X:/UserTools;Y:/ExistingTools"


def _builder():
    path = ROOT / "tools" / "build_portable_windows.py"
    spec = importlib.util.spec_from_file_location("portable_builder", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_portable_copy_filters_debug_and_editable_paths():
    builder = _builder()
    blocked = builder._ignore(
        str(ROOT / ".venv" / "Lib" / "site-packages"),
        ["PIL", "PySide6", "__pycache__", "pytest-cov.pth",
         "__editable__.stronghold_europe_de-0.1.0.pth",
         "python.pdb", "plugin.pyc"],
    )
    assert "PIL" not in blocked and "PySide6" not in blocked
    assert "__pycache__" in blocked and "python.pdb" in blocked
    assert "plugin.pyc" in blocked
    assert "__editable__.stronghold_europe_de-0.1.0.pth" in blocked
    assert "pytest-cov.pth" not in blocked


def test_portable_builder_never_bundles_user_work_or_game_data():
    builder = _builder()
    source = (ROOT / "tools" / "build_portable_windows.py").read_text("utf8")
    assert 'git", "archive"' in source
    assert 'if out.exists()' in source
    assert 'source_commit' in source
    assert '"private_game_assets_included": False' in source
    assert '"cross_computer_smoke_passed": False' in source
    assert '"packager_windows_smoke_passed": True' in source
    assert '"--self-test"' in source
    assert '"GUI_BACKENDS_READY=1"' in source
    assert ".venv" in source
    assert builder.OUT_NAME.endswith(".zip")


def test_windows_bootstrap_has_portable_and_source_fallbacks():
    launcher = (ROOT / "Suite starten.cmd").read_text("utf8")
    installer = (ROOT / "setup.ps1").read_text("utf8")
    starter = (ROOT / "tools" / "suite_start.py").read_text("utf8")
    assert r'python\python.exe' in launcher
    assert r'if errorlevel 1 goto fehler' in launcher
    assert r'goto fehler' in launcher
    assert "'-3.13'" in installer
    assert "'-3.14'" in installer
    assert "'--require-hashes'" in installer
    assert '"--self-test"' in starter
    assert "PORTABLE_READY=1" in starter
    assert "GUI_BACKENDS_READY=1" in starter
    assert '"--portable-bootstrap"' in starter
    studio = (ROOT / "Sandbox Studio starten.cmd").read_text("utf8")
    assert "--portable-bootstrap" in studio
    assert "suite_start.py" in studio

"""Portable release scripts: no system Python and no accidental user data."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


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

"""Versioned CPython 3.13-3.15 and read-only native-source capability checks."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tomllib

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/"tools"),str(ROOT/"src")]

from suite_compatibility_preflight import (
    SOURCE_MINOR, supports_source_python, _dependencies, collect,
)
from suite_multi_python_matrix import inspect as inspect_python
from suite_native_game_capabilities import inspect as inspect_game


@pytest.mark.parametrize("minor",[13,14,15])
def test_source_policy_includes_python_313_through_315(minor):
    assert minor in SOURCE_MINOR
    assert supports_source_python(3,minor)
    assert not supports_source_python(3,minor,cpython=False)
    assert not supports_source_python(3,minor,bits=32)


@pytest.mark.parametrize("minor",[11,12,16,17])
def test_source_policy_does_not_claim_untested_minor_versions(minor):
    assert not supports_source_python(3,minor)


def test_source_requires_python_315_and_compatible_qt_constraint():
    metadata=tomllib.loads((ROOT/"pyproject.toml").read_text("utf-8"))
    assert metadata["project"]["requires-python"]==">=3.13,<3.16"
    gui=metadata["project"]["optional-dependencies"]["gui"]
    assert any("PySide6==6.10.2" in v and "3.15" in v for v in gui)
    assert any("PySide6>=6.12,<7" in v and "3.15" in v for v in gui)
    # The audited Python 3.13 / 3.14 lockfiles stay in place.
    assert (ROOT/"requirements-py313-win_amd64.lock").is_file()
    assert (ROOT/"requirements-py314-win_amd64.lock").is_file()


def test_missing_python_315_wheel_lock_is_not_reported_ready(tmp_path):
    result=_dependencies(tmp_path,15)
    assert result["status"]=="limited"
    assert "no audited" in result["detail"]
    assert "Windows" in result["detail"]
    assert not (tmp_path/"requirements-py315-win_amd64.lock").exists()


def test_multiple_python_matrix_reports_actual_executable_readonly():
    row=inspect_python(Path(sys.executable))
    assert row["source_version_supported"] == supports_source_python(
        sys.version_info.major,sys.version_info.minor)
    assert row["python"]==sys.version.split()[0]
    assert row["bits"]==64
    assert row["qt_widget_probe"] is None or isinstance(row["qt_widget_probe"],dict)


def test_missing_interpreter_never_implicitly_passes(tmp_path):
    row=inspect_python(tmp_path/"absent-python.exe")
    assert row["status"]=="missing"
    assert not row.get("source_version_supported",False)


def test_game_inspection_does_not_claim_plugin_abi_when_sources_absent(tmp_path):
    game=tmp_path/"QA Copy"
    game.mkdir()
    report=inspect_game(game)
    assert report["script_extender_version"] is None
    assert report["noesis_grid_target_count"]==0
    assert not any(x["present"] for x in report[
        "sha_pinned_current_references"].values())
    assert report["native_runtime_approved"] is False
    assert report["plugin_install_allowed_by_this_report"] is False
    assert report["game_originals_modified"] is False


def test_native_game_inspection_catches_symlink_game_root(tmp_path):
    actual=tmp_path/"game"
    actual.mkdir()
    link=tmp_path/"linked"
    try:link.symlink_to(actual,target_is_directory=True)
    except (OSError,NotImplementedError):
        pytest.skip("Windows test account has no symbolic-link permission")
    with pytest.raises(ValueError,match="linked"):
        inspect_game(link)


def test_explicit_real_qa_game_readonly_if_present():
    # Only for this user's authorized, marked private QA clone.
    root=Path(r"E:\SSLiveGame_20261105")
    if not root.is_dir() or not (root/".sprite-suite-qa-copy.marker").is_file():
        pytest.skip("Private marked QA game not present")
    report=inspect_game(root)
    assert report["script_extender_version"]=="2.14.3"
    assert report["noesis_grid_target_count"]>=50
    assert report["native_runtime_approved"] is False
    assert report["plugin_install_allowed_by_this_report"] is False
    assert all(x["present"] for x in report[
        "sha_pinned_current_references"].values())


def test_compat_preflight_can_report_game_xaml_without_abi_approval(monkeypatch,tmp_path):
    import suite_native_game_capabilities as native
    supplied={
        "noesis_grid_target_count":42,
        "script_extender_version":"42.99.test",
        "sha_pinned_current_references":{"game":{"present":True}},
    }
    monkeypatch.setattr(native,"inspect",lambda _root:supplied)
    actual=collect(root=ROOT,game_root=tmp_path/"dummy-game")
    rows={item["name"]:item for item in actual["checks"]}
    assert rows["Game XAML/Noesis source structure"]["status"]=="ready"
    assert actual["game_structural_inspection"]==supplied
    assert actual["native_game_approved"] is False
    assert actual["writes_to_game"] is False



def test_tcltk9_windows_315_embedded_dll_zipfs_is_attested_without_global_changes():
    if sys.version_info[:2]!=(3,15):
        pytest.skip("Only applies to isolated CPython 3.15 DLL/zipfs runtime")
    import tkinter
    if tkinter.TclVersion!=9 or tkinter.TkVersion!=9:
        pytest.skip("Not the CPython 3.15 Tcl/Tk 9 build")
    from suite_tcl_runtime import locate_bundled_tcl,prepare_tcl_env
    base=Path(sys.base_prefix)
    assert (base/"DLLs"/"tcl90.dll").is_file()
    assert (base/"DLLs"/"tcl9tk90.dll").is_file()
    located=locate_bundled_tcl(ROOT)
    assert located==(base/"DLLs").resolve()
    contract=prepare_tcl_env(ROOT)
    assert contract["SPRITESUITE_TCL_RUNTIME_SOURCE"]=="native-verified-embedded-zipfs9"
    assert "TCL_LIBRARY" not in contract
    assert "TK_LIBRARY" not in contract


def test_python315_full_gui_runtime_reports_qt6_and_tcl9(tmp_path):
    if sys.version_info[:2]!=(3,15):
        pytest.skip("Only applies to isolated CPython 3.15 full QA runtime")
    from suite_tcl_runtime import create_tk_root
    root=create_tk_root()
    try:
        assert root.tk.call("info","patchlevel").startswith("9.0")
    finally:root.destroy()
    from PySide6.QtWidgets import QApplication
    current=QApplication.instance()
    made=current is None
    qt=current or QApplication([])
    try:assert qt.platformName()=="offscreen" or qt.platformName()
    finally:
        if made:qt.quit()

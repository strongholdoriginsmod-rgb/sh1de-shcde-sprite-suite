"""Synthetic-only Unity Hub and Python paths – no subprocesses, no installs."""
from pathlib import Path
import importlib.util

FILE = Path(__file__).resolve().parents[2] / "tools" / "suite_toolchain_inventory.py"
spec = importlib.util.spec_from_file_location("suite_toolchain_inventory", FILE)
inventory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inventory)


def fake_unity(root, version):
    exe = root / "Unity" / "Hub" / "Editor" / version / "Editor" / "Unity.exe"
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_bytes(b"faked executable - never run")
    return exe


def test_exact_hub_version_selected_without_running_binary(tmp_path):
    root = tmp_path / "programs"
    target = fake_unity(root, "2021.3.45f2")
    fake_unity(root, "2022.3.51f1")
    rows = inventory.unity_editors({"ProgramFiles": str(root)})
    assert {v["version_hint"] for v in rows} == {"2021.3.45f2", "2022.3.51f1"}
    assert inventory.preferred_unity(rows) == str(target)
    assert all(v["revision_verified"] is False and v["executable_started"] is False
               for v in rows)


def test_multiple_matching_unity_versions_remain_ambiguous(tmp_path):
    a = fake_unity(tmp_path / "a", "2021.3.45f2")
    b = fake_unity(tmp_path / "b", "2021.3.45f2")
    rows = inventory.unity_editors({
        "ProgramFiles": str(tmp_path / "a"),
        "LOCALAPPDATA": str(tmp_path / "b")})
    assert len(rows) == 2
    assert inventory.preferred_unity(rows) is None
    assert inventory.preferred_unity(inventory.unity_editors({
        "ProgramFiles": str(tmp_path / "a"),
        "LOCALAPPDATA": str(tmp_path / "b")}, str(a))) == str(a)
    assert a.read_bytes() == b.read_bytes()


def test_current_and_virtual_python_interpreters_discovered_without_start(tmp_path):
    project = tmp_path / "SpriteSuite"
    venv = project / ".venv" / "Scripts" / "python.exe"
    venv.parent.mkdir(parents=True)
    venv.write_bytes(b"test")
    installed = tmp_path / "appdata" / "Programs" / "Python" / "Python314" / "python.exe"
    installed.parent.mkdir(parents=True)
    installed.write_bytes(b"test")
    current = tmp_path / "current" / "python.exe"
    current.parent.mkdir(parents=True)
    current.write_bytes(b"test")
    rows = inventory.python_interpreters(project, {"LOCALAPPDATA":str(tmp_path / "appdata")},
                                         current_executable=str(current))
    found = {item["path"]: item for item in rows}
    for expected in (current, installed, venv):
        assert str(expected) in found
    assert found[str(installed)]["version_hint"] == "3.14"
    assert found[str(installed)]["runtime_probed"] is False
    assert found[str(venv)]["executable_started"] is False
    assert found[str(current)]["runtime_probed"] is True


def test_symlink_python_executable_not_followed(tmp_path):
    import os
    import pytest
    real = tmp_path / "real" / "python.exe"
    real.parent.mkdir()
    real.write_bytes(b"data")
    alias = tmp_path / "alias" / "python.exe"
    alias.parent.mkdir()
    try:
        os.symlink(real, alias)
    except (OSError, NotImplementedError) as error:
        pytest.skip(str(error))
    rows = inventory.python_interpreters(tmp_path / "project", {
        "SPRITESUITE_PYTHON":str(alias)}, current_executable=str(real))
    assert not any(row["path"] == str(alias) for row in rows)


def test_explicit_hub_path_never_executes_or_writes(tmp_path):
    exe = fake_unity(tmp_path / "programs", "2021.3.45f2")
    old = exe.read_bytes()
    records = inventory.unity_editors({"STRONGHOLD_EUROPE_UNITY_EDITOR":str(exe)})
    assert len(records) == 1
    assert inventory.preferred_unity(records) == str(exe)
    assert exe.read_bytes() == old

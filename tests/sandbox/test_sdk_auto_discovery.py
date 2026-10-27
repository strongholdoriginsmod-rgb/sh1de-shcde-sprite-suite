"""SDK discovery and portable Suite startup: compatibility without build bypass."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from stronghold_europe_de import runtime_build
from stronghold_europe_de import sdk_toolchain as sdk
from stronghold_europe_de import suite_build_readiness as ready

ROOT = Path(__file__).resolve().parents[2]


def _install(path: Path, version: str | None) -> Path:
    path.mkdir(parents=True)
    (path / ("dotnet.exe" if os.name == "nt" else "dotnet")).write_bytes(b"fixture, never execute")
    if version is not None:
        (path / "sdk" / version).mkdir(parents=True)
    return path


def _isolated(tmp_path, monkeypatch):
    (tmp_path / "global.json").write_text(
        '{"sdk":{"version":"8.0.100"}}', encoding="utf-8"
    )
    monkeypatch.setattr(sdk, "ROOT", tmp_path)
    monkeypatch.setattr(sdk.shutil, "which", lambda _: None)
    monkeypatch.setenv("PATH", "")
    monkeypatch.delenv("DOTNET_ROOT_X64", raising=False)
    monkeypatch.delenv("DOTNET_ROOT", raising=False)
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "system-empty"))
    monkeypatch.setenv("ProgramW6432", str(tmp_path / "system-empty"))


def test_runtime_only_path_falls_back_to_portable_supported_sdk(tmp_path, monkeypatch):
    _isolated(tmp_path, monkeypatch)
    old = _install(tmp_path / "runtime-only", None)
    newer = _install(tmp_path / "work/toolchains/dotnet-10.0.401", "10.0.401")
    monkeypatch.setenv("PATH", str(old))
    monkeypatch.setattr(sdk.shutil, "which", lambda _: str(old / "dotnet.exe"))
    assert sdk.find_dotnet_sdk(tmp_path) == newer.resolve()
    assert sdk.installed_sdk_versions(old) == ()
    assert sdk.installed_sdk_versions(newer) == ("10.0.401",)


def test_unsupported_path_uses_second_path_sdk(tmp_path, monkeypatch):
    _isolated(tmp_path, monkeypatch)
    old = _install(tmp_path / "old", "7.0.400")
    good = _install(tmp_path / "good", "8.0.100")
    monkeypatch.setenv("PATH", os.pathsep.join((str(old), str(good))))
    monkeypatch.setattr(sdk.shutil, "which", lambda _: str(old / "dotnet.exe"))
    assert sdk.find_dotnet_sdk(tmp_path) == good.resolve()


def test_dotnet_root_is_valid_portable_fallback(tmp_path, monkeypatch):
    _isolated(tmp_path, monkeypatch)
    good = _install(tmp_path / "custom-sdk", "9.0.300")
    monkeypatch.setenv("DOTNET_ROOT", str(good))
    assert sdk.find_dotnet_sdk(tmp_path) == good.resolve()
    assert ready._sdk_directory(None) == good.resolve()
    assert ready._sdk_on_disk(None)[0] is True


def test_runtime_only_sdk_does_not_become_fake_green(tmp_path, monkeypatch):
    _isolated(tmp_path, monkeypatch)
    bad = _install(tmp_path / "no-sdk", None)
    monkeypatch.setenv("DOTNET_ROOT", str(bad))
    assert sdk.find_dotnet_sdk(tmp_path) is None
    assert ready._sdk_on_disk(None)[0] is False


def test_explicit_unsupported_sdk_is_not_silently_replaced(tmp_path, monkeypatch):
    _isolated(tmp_path, monkeypatch)
    bad = _install(tmp_path / "old", "7.0.100")
    _install(tmp_path / "work/toolchains/dotnet-10.0.401", "10.0.401")
    valid, detail = ready._sdk_on_disk(str(bad))
    assert valid is False and "Kein stabiles" in detail


def test_runtime_builder_probes_auto_found_sdk_before_build(tmp_path, monkeypatch):
    _isolated(tmp_path, monkeypatch)
    good = _install(tmp_path / "work/toolchains/dotnet-10.0.401", "10.0.401")
    config = SimpleNamespace(
        project_root=tmp_path, output=SimpleNamespace(cache_dir=tmp_path / "cache")
    )
    calls = []

    def probe(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout="10.0.401\n", stderr="")

    monkeypatch.setattr(runtime_build.subprocess, "run", probe)
    program, environment = runtime_build._resolve_pinned_dotnet_sdk(config)
    assert Path(program) == good / ("dotnet.exe" if os.name == "nt" else "dotnet")
    assert calls[0][0] == [program, "--version"]
    assert environment["DOTNET_CLI_TELEMETRY_OPTOUT"] == "1"

    monkeypatch.setattr(
        runtime_build.subprocess, "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="7.0.100", stderr="")
    )
    with pytest.raises(runtime_build.RuntimeBuildError, match="requires"):
        runtime_build._resolve_pinned_dotnet_sdk(config)


def test_portable_launcher_preserves_valid_sdk_and_fixes_outdated_path(tmp_path, monkeypatch):
    _isolated(tmp_path, monkeypatch)
    fallback = _install(tmp_path / "work/toolchains/dotnet-10.0.401", "10.0.401")
    selected = _install(tmp_path / "custom-selected", "8.0.100")
    (tmp_path / "config").mkdir()
    path = tmp_path / "config/toolchains.local.json"
    path.write_text(json.dumps({"dotnet_directory": str(selected)}), encoding="utf-8")

    spec = importlib.util.spec_from_file_location("suite_start_sdk_test", ROOT / "tools/suite_start.py")
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    monkeypatch.setattr(launcher, "PROJECT", tmp_path)
    launcher.fix_toolchains()
    assert json.loads(path.read_text(encoding="utf-8"))["dotnet_directory"] == str(selected)

    path.write_text(json.dumps({"dotnet_directory": str(tmp_path / "gone")}), encoding="utf-8")
    launcher.fix_toolchains()
    assert json.loads(path.read_text(encoding="utf-8"))["dotnet_directory"] == str(fallback.resolve())


def test_heuristic_long_checkout_warns_without_disabling_tools(
    tmp_path, monkeypatch, capsys
):
    """A guessed Windows path-limit risk must not override verified toolchains."""
    import sys
    from stronghold_europe_de import asset_stream_builder

    spec = importlib.util.spec_from_file_location(
        "suite_bridge_compat_test", ROOT / "tools/suite_bridge.py"
    )
    bridge = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bridge)
    monkeypatch.setattr(bridge, "ROOT", tmp_path / ("deep-path-" * 9))
    monkeypatch.setattr(asset_stream_builder, "_resolve_toolchain", lambda *args: object())
    monkeypatch.setattr(sdk, "find_dotnet_sdk", lambda root: tmp_path)
    monkeypatch.setattr(
        bridge.subprocess, "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="10.0.401", stderr="")
    )
    monkeypatch.setattr(sys, "argv", ["suite_bridge.py", "preflight"])
    assert bridge.main() == 0
    assert "WARNUNG: Langer Arbeitsordner" in capsys.readouterr().out

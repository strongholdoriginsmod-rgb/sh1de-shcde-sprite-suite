"""End-to-end self-contained examples and safe third-party helper boundary."""
from __future__ import annotations
from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from stronghold_europe_de.modding_studio.catalog import API_RELEASE, API_COMMIT, SERP_COMMIT
from stronghold_europe_de.modding_studio.cli import main
from stronghold_europe_de.modding_studio.design import simulate_mission
from stronghold_europe_de.modding_studio.engine import analyze
from stronghold_europe_de.modding_studio.exporter import export_project
from stronghold_europe_de.modding_studio.integrations import run_helper
from stronghold_europe_de.modding_studio.model import load_project, project_template, validate_project
from stronghold_europe_de.modding_studio.safety import StudioError, read_json, create_file

EXAMPLE = ROOT / "examples" / "modding-studio"


def test_example_complete_and_review_not_game_approved():
    project, digest = load_project(EXAMPLE)
    result = analyze(EXAMPLE, project)
    assert result["status"] == "REVIEW"
    assert len(result["modules"]) == 12
    assert result["release_status"] == "not_in_game_verified"
    assert result["modules"]["mission"]["facts"]["triggers"] == 2
    assert result["modules"]["hud"]["facts"]["referenced_count"] == 1
    assert result["modules"]["audio"]["facts"]["clips"]["sample_tone"]["bits"] == 16
    assert digest == sha256((EXAMPLE / "project.json").read_bytes()).hexdigest()


def test_example_dryrun_and_isolated_export(tmp_path):
    project, _ = load_project(EXAMPLE)
    result = simulate_mission(project["modules"]["mission"], read_json(EXAMPLE, "events.json"))
    assert [x["tick"] for x in result["trace"]] == [0, 50]
    target = tmp_path / "workspace"
    shutil.copytree(EXAMPLE, target)
    exported, manifest = export_project(target, project, "export_one")
    assert len(manifest["files"]) >= 22
    assert (exported / "plugin/Plugin.cs").is_file()
    assert (exported / "mission/trigger-plan.lua").is_file()
    assert not list(exported.rglob("*.dll"))
    assert (target / "project.json").read_bytes() == (EXAMPLE / "project.json").read_bytes()
    assert manifest["in_game_compatibility"] == "not_established"


def test_example_cli_dryrun(capsys):
    assert main(["check", str(EXAMPLE)]) == 0
    assert "REVIEW" in capsys.readouterr().out
    assert main(["simulate", str(EXAMPLE), "--events", "events.json"]) == 0
    assert json.loads(capsys.readouterr().out)["fired"] == 2
    assert main(["audit-suite-ui", "--suite-root", str(ROOT)]) == 0
    assert "wall 14" in capsys.readouterr().out


def test_pinned_sdk_and_no_game_dll_scaffold():
    from stronghold_europe_de.modding_studio.scaffold import plugin_scaffold
    assert API_RELEASE == "0.27.0"
    assert API_COMMIT == "ee77e0d267c795cf7375863f6eac243fea8fe72c"
    assert SERP_COMMIT == "e1b61a67fe673e4389c404646ae1e53155a64857"
    p = project_template("example_scaffold", "Demo")
    files = plugin_scaffold(p)
    source = files["plugin/Plugin.cs"].decode("utf8")
    csproj = files["plugin/SpriteSuiteAuthoringPlugin.csproj"].decode("utf8")
    info = json.loads(files["plugin/info.json"])
    assert "ApiShared.ForMod(Guid)" in source
    assert "Api.WhenReady(OnReady)" in source
    assert "no hooks registered" in source
    assert "APIShared.Content.dll" in csproj
    assert "UnityEngine.CoreModule.dll" in csproj
    assert "<Private>false</Private>" in csproj
    assert info["Dependencies"][0]["GUID"] == "APIShared_Serp"
    assert info["MinimumScriptExtenderVersion"] == "2.14.0"
    assert not any(s.endswith(".dll") for s in files)
    p["target"]["api_shared"] = "0.28.0"
    assert validate_project(p) == p
    assert plugin_scaffold(p)["plugin/Plugin.cs"] == files["plugin/Plugin.cs"]


class FakeHelper:
    def __init__(self, command, cwd, shell, stdin, stdout, stderr, env):
        assert shell is False
        assert command[0].endswith(".exe")
        assert stdin == subprocess.DEVNULL
        self.cwd = Path(cwd)
        assert self.cwd.is_dir()
        stdout.write(b"synthetic validation complete")
    def wait(self, timeout):
        return 0


def test_external_helper_runs_in_isolated_cwd(tmp_path, monkeypatch):
    from stronghold_europe_de.modding_studio import integrations
    root = tmp_path / "workspace"
    root.mkdir()
    create_file(root, "maps/a.map", b"source")
    helper = root / "helper.exe"
    helper.write_bytes(b"mock")
    observed = {}
    class Mock(FakeHelper):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            observed["cwd"] = self.cwd
    monkeypatch.setattr(integrations.subprocess, "Popen", Mock)
    result = run_helper(
        root, "mapparser", "info", "maps/a.map",
        sha256(b"source").hexdigest(), helper, sha256(b"mock").hexdigest(),
    )
    assert result["exit_code"] == 0
    assert observed["cwd"] != root
    assert not observed["cwd"].exists()
    assert (root / "maps/a.map").read_bytes() == b"source"


def test_helper_source_mutation_detected_and_output_discarded(tmp_path, monkeypatch):
    from stronghold_europe_de.modding_studio import integrations
    root = tmp_path / "workspace"
    root.mkdir()
    create_file(root, "maps/a.map", b"source")
    helper = root / "helper.exe"
    helper.write_bytes(b"mock")
    class Mutator(FakeHelper):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            (root / "maps/a.map").write_bytes(b"changed")
    monkeypatch.setattr(integrations.subprocess, "Popen", Mutator)
    with pytest.raises(StudioError, match="mutated"):
        run_helper(
            root, "mapparser", "info", "maps/a.map",
            sha256(b"source").hexdigest(), helper, sha256(b"mock").hexdigest(),
        )


def test_universal_suite_exposes_explicit_modding_studio_entrypoint():
    source = (ROOT / "tools/suite_universal.pyw").read_text(encoding="utf-8")
    assert 'text="Modding Studio"' in source
    assert "command=self.open_modding_studio" in source
    assert 'workspace = metadata / "modding-studio"' in source
    assert "StudioWindow(window, workspace, project_bound=True)" in source
    assert "self._build_quick_navigation()" in source

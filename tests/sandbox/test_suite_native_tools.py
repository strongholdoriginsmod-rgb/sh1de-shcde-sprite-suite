"""Real offline project round trips and bounded native tool dispatch contracts."""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "src")]
import hud_menu_workspace as hud
import se_asset_package as package
import suite_native_tools as native


@pytest.fixture
def service(tmp_path, monkeypatch):
    root = tmp_path / "Suite äöü"
    work = root / "work"
    (root / "tools").mkdir(parents=True)
    work.mkdir()
    for module in (hud, package):
        monkeypatch.setattr(module, "ROOT", root)
        monkeypatch.setattr(module, "WORK", work)
    monkeypatch.setattr(hud, "DEFAULT", work / "Primary")
    monkeypatch.setattr(package, "OUT", work / "se-asset-mods")
    project = work / "Primary"
    project.mkdir()
    (root / "tools" / "sprites.py").write_text(
        '"""Fixture CLI for exact argv."""\n'
        'import argparse,json,sys\n'
        'p=argparse.ArgumentParser()\n'
        'p.add_argument("--label", help="A label")\n'
        'print(json.dumps(sys.argv[1:],ensure_ascii=False))\n', encoding="utf-8")
    (root / "tools" / "surprise.py").write_text(
        '"""A statically discoverable tool."""\n'
        'raise RuntimeError("A catalog must never execute this")\n', encoding="utf-8")
    (root / "tools" / "second.pyw").write_text('"""Windowed module."""\n', encoding="utf-8")
    return native.NativeToolService(project, root=root)


def must(result):
    assert result["ok"], result
    return result["result"]


def png(color):
    stream = BytesIO()
    Image.new("RGBA", (48, 30), color).save(stream, "PNG")
    return stream.getvalue()


def test_specs_are_typed_independent_dynamic_function_definitions(service):
    specs = service.specs()
    assert {item["name"] for item in specs} == set(native.SCHEMAS)
    assert all(item["type"] == "function" and item["inputSchema"]["type"] == "object"
               and item["description"] for item in specs)
    specs[0]["inputSchema"]["properties"].clear()
    assert service.specs()[0]["inputSchema"]["properties"]
    json.dumps(specs)


def test_empty_project_context_keeps_inventory_with_nonfatal_no_assets_warning(service):
    context = must(service.call("suite_context", {"include_audit": True}))
    assert context["assets"] == [] and context["total"] == 0
    assert context["audit"]["ok"] is False
    assert context["audit"]["error"]["code"] == "no_assets"
    assert context["warnings"][0]["code"] == "no_assets"


def test_corrupt_existing_asset_audit_is_a_real_error_with_context(service):
    made = must(service.call("suite_project_op", {"operation": "create_image", "name": "Corrupt", "width": 8, "height": 8}))
    Path(made["path"]).write_bytes(b"not-an-image-any-more")
    result = service.call("suite_context", {"include_audit": True})
    assert result["ok"] is False and result["error"]["code"] == "asset_audit_failed"
    assert result["error"]["details"]["context"]["assets"][0]["path"].endswith("Corrupt.png")


def test_catalog_pagination_describe_and_help_never_execute_scripts(service):
    service.runner = lambda *a, **kw: pytest.fail("Static help attempted execution")
    first = must(service.call("suite_tool_catalog", {"limit": 1}))
    assert first["total"] == 3 and first["next_offset"] == 1
    rest = must(service.call("suite_tool_catalog", {"offset": 1, "limit": 2}))
    assert len(rest["items"]) == 2 and rest["next_offset"] is None
    found = must(service.call("suite_tool_catalog", {"query": "Windowed"}))
    assert found["items"][0]["name"] == "second.pyw"
    detail = must(service.call("suite_tool_describe", {"name": "sprites.py"}))
    assert detail["id"] == "tool:sprites.py"
    assert any("--label" in row["names"] for row in detail["metadata"]["fields"])
    helped = must(service.call("suite_tool_run", {"name": "surprise.py", "arguments": ["--help"]}))
    assert helped["executed"] is False and "statisch" in helped["static_help"].casefold()


def test_exact_unicode_argv_and_injection_characters_use_real_no_shell_execution(service):
    value = 'ä ö ü with spaces & echo INJECTED; $(nope) `literal` "quote"'
    result = must(service.call("suite_tool_run", {"name": "sprites.py", "arguments": ["--label", value]}))
    assert json.loads(result["stdout"]) == ["--label", value]
    assert result["executed"] and result["category"] == "workspace"
    assert result["stderr"] == "" and result["returncode"] == 0


def test_injected_runner_receives_safe_argv_and_no_api_key(service, monkeypatch):
    calls = []
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-be-used")
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")
    service.runner = run
    must(service.call("suite_tool_run", {"name": "sprites.py", "arguments": ["--label", "ä x"]}))
    command, kwargs = calls[0]
    assert command == [sys.executable, str(service.root / "tools/sprites.py"), "--label", "ä x"]
    assert kwargs["shell"] is False and kwargs["timeout"] == 120
    assert kwargs["cwd"] == service.root
    assert "OPENAI_API_KEY" not in kwargs["env"]


@pytest.mark.parametrize("name", ["../sprites.py", "sub/sprites.py", r"sub\sprites.py", "C:evil.py", "missing.py", "sprites.ps1"])
def test_tool_paths_cannot_escape_or_become_arbitrary_commands(service, name):
    result = service.call("suite_tool_run", {"name": name, "arguments": []})
    assert not result["ok"] and result["error"]["code"] == "unknown_tool"


@pytest.mark.parametrize("args", [{"name": "sprites.py", "arguments": "--help"},
    {"name": "sprites.py", "arguments": [3]}, {"name": "sprites.py", "arguments": ["bad\0arg"]},
    {"name": "sprites.py", "arguments": [], "timeout_seconds": 0},
    {"name": "sprites.py", "arguments": [], "eval": "print(1)"}])
def test_invalid_inputs_have_stable_errors(service, args):
    result = service.call("suite_tool_run", args)
    assert result["error"]["code"] == "invalid_arguments"
    assert service.call("not_a_native_tool", {})["error"]["code"] == "unknown_tool"


def test_only_game_unknown_and_declared_destructive_effects_need_approval(service):
    ran, approvals = [], []
    service.runner = lambda *a, **kw: (ran.append(a) or SimpleNamespace(returncode=0, stdout="", stderr=""))
    denied = service.call("suite_tool_run", {"name": "surprise.py", "arguments": []})
    assert denied["error"]["code"] == "approval_required" and not ran
    service.approval = lambda request: (approvals.append(request) or False)
    assert service.call("suite_tool_run", {"name": "surprise.py", "arguments": []})["error"]["code"] == "approval_denied"
    service.approval = lambda request: (approvals.append(request) or True)
    must(service.call("suite_tool_run", {"name": "surprise.py", "arguments": []}))
    assert approvals[-1]["category"] == "unknown"
    count = len(approvals)
    must(service.call("suite_tool_run", {"name": "sprites.py", "arguments": []}))
    assert len(approvals) == count  # WORK has no second confirmation.
    must(service.call("suite_tool_run", {"name": "sprites.py", "arguments": [], "destructive": True}))
    assert approvals[-1]["destructive"] is True
    (service.root / "tools/qa_building_damage_live.py").write_text("# fixture", encoding="utf-8")
    must(service.call("suite_tool_run", {"name": "qa_building_damage_live.py", "arguments": ["--install-qa"]}))
    assert approvals[-1]["category"] == "game"


def test_real_project_import_edit_build_zip_backup_and_restore_preserves_original(service, tmp_path):
    source = tmp_path / "Original ä.png"
    original = png((20, 70, 100, 255))
    source.write_bytes(original)
    imported = must(service.call("suite_project_op", {"operation": "import_image", "source": str(source)}))
    relative = Path(imported["path"]).relative_to(service.project).as_posix()
    edited = png((200, 80, 10, 240))
    hud.write_png(relative, edited, project=service.project,
                  expected_sha256=sha256(original).hexdigest())
    context = must(service.call("suite_context", {"include_audit": True}))
    assert context["assets"][0]["id"] == "asset:" + relative
    assert context["assets"][0]["sha256"] == sha256(edited).hexdigest()
    assert context["pipeline"] == "ProjectPipeline"
    inspected = must(service.call("suite_project_op", {"operation": "inspect", "relative_path": relative}))
    assert inspected["sha256"] == sha256(edited).hexdigest()
    exported = service.root / "chosen ä.zip"
    proof = must(service.call("suite_project_op", {"operation": "build", "guid": "org.creator.native",
        "name": "Creator's own", "version": "99-custom", "output": str(exported)}))
    assert proof["zip_verified_against_project"] and exported.is_file()
    with ZipFile(exported) as archive:
        assert archive.read("BepInEx/plugins/org.creator.native/" + relative) == edited
    backup = service.root / "project-backup.zip"
    must(service.call("suite_project_op", {"operation": "backup", "output": str(backup)}))
    restored = must(service.call("suite_project_op", {"operation": "restore", "source": str(backup), "project_name": "Restored native"}))
    assert service.project == Path(restored["project"])
    assert (service.project / relative).read_bytes() == edited
    assert source.read_bytes() == original
    assert must(service.call("suite_project_op", {"operation": "audit"}))["original_game_files_modified"] is False


def test_all_project_operations_use_existing_pipeline_and_refuse_traversal(service, tmp_path):
    made = must(service.call("suite_project_op", {"operation": "create_image", "name": "Blank", "width": 32, "height": 24}))
    assert Image.open(made["path"]).size == (32, 24)
    for extension in (".dll", ".lua", ".arbitrary"):
        file = tmp_path / ("Source" + extension)
        file.write_bytes(b"creator owned arbitrary bytes")
        result = must(service.call("suite_project_op", {"operation": "import_mod_file", "source": str(file),
                      "relative_path": "Custom/asset" + extension}))
        assert Path(result["path"]).read_bytes() == file.read_bytes()
    bad = service.call("suite_project_op", {"operation": "import_mod_file", "source": str(file), "relative_path": "../escape.dll"})
    assert not bad["ok"] and not (service.project.parent / "escape.dll").exists()
    patch = tmp_path / "Own.xaml"
    patch.write_text('<Patch><Operation Type="SetAttribute" XPath="//Button" Name="Content" Value="New" /></Patch>', encoding="utf-8")
    must(service.call("suite_project_op", {"operation": "import_patch", "source": str(patch)}))
    original = service.project
    opened = must(service.call("suite_project_op", {"operation": "new", "name": "new-native"}))
    assert service.project == Path(opened["project"]) and service.project != original
    must(service.call("suite_project_op", {"operation": "open", "project": str(original)}))
    missing = service.root / "work/missing"
    assert not service.call("suite_project_op", {"operation": "open", "project": str(missing)})["ok"]
    assert not missing.exists() and service.project == original


def test_credentials_are_rejected_before_read_or_execution(service, tmp_path):
    secret = tmp_path / ".codex/auth.json"
    for request in [
        {"operation": "import_mod_file", "source": str(secret), "relative_path": "Other/file.json"},
        {"operation": "backup", "output": str(secret)},
    ]:
        assert service.call("suite_project_op", request)["error"]["code"] == "credential_path"
    service.runner = lambda *a, **kw: pytest.fail("Credential path reached a process")
    request = {"name": "sprites.py", "arguments": ["--file=" + str(secret)]}
    assert service.call("suite_tool_run", request)["error"]["code"] == "credential_path"


def test_default_runner_failure_timeout_output_bound_and_cancel_reset(service):
    path = service.root / "tools/sprites.py"
    path.write_text('import sys\nprint("x"*40000)\nprint("bad",file=sys.stderr)\nsys.exit(4)\n', encoding="utf-8")
    result = service.call("suite_tool_run", {"name": path.name, "arguments": []})
    assert result["error"]["code"] == "tool_failed"
    detail = result["error"]["details"]
    assert detail["returncode"] == 4 and detail["output_truncated"]
    assert len(detail["stdout"]) <= native.MAX_TEXT
    path.write_text('import time\ntime.sleep(30)\n', encoding="utf-8")
    result = service.call("suite_tool_run", {"name": path.name, "arguments": [], "timeout_seconds": 1})
    assert result["error"]["code"] == "timeout"
    service.cancel()
    assert service.call("suite_tool_run", {"name": path.name, "arguments": []})["error"]["code"] == "cancelled"
    service.reset_cancel()
    path.write_text('print("ready")\n', encoding="utf-8")
    assert must(service.call("suite_tool_run", {"name": path.name, "arguments": []}))["stdout"].strip() == "ready"


def test_cancel_running_real_process_and_no_secret_exception_text(service):
    ready = service.root / "ready.txt"
    (service.root / "tools/sprites.py").write_text(
        'from pathlib import Path\nimport time\nPath("ready.txt").write_text("ready")\ntime.sleep(30)\n', encoding="utf-8")
    result = []
    worker = threading.Thread(target=lambda: result.append(service.call("suite_tool_run", {"name": "sprites.py", "arguments": []})))
    worker.start()
    deadline = time.monotonic() + 10
    while not ready.is_file() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert ready.is_file()
    assert service.call("suite_context", {})["error"]["code"] == "busy"
    service.cancel()
    worker.join(timeout=10)
    assert not worker.is_alive() and result[0]["error"]["code"] == "cancelled"
    service.reset_cancel()
    def fail(*args, **kwargs):
        raise RuntimeError("a secret exception body must not leave this adapter")
    service.runner = fail
    result = service.call("suite_tool_run", {"name": "sprites.py", "arguments": []})
    assert result["error"]["code"] == "operation_failed"
    assert "secret exception" not in json.dumps(result)


def test_continuous_output_is_stopped_and_truncated_before_return(service):
    (service.root / "tools/sprites.py").write_text(
        'import sys,time\nwhile True:\n sys.stdout.write("x"*65536)\n sys.stdout.flush()\n time.sleep(.001)\n',
        encoding="utf-8")
    result = service.call("suite_tool_run", {"name": "sprites.py", "arguments": [], "timeout_seconds": 5})
    assert result["error"]["code"] == "output_limit"
    assert result["error"]["details"]["output_truncated"]
    assert len(result["error"]["details"]["stdout"]) <= native.MAX_TEXT


def test_context_omits_credential_content_and_audit_rejects_it(service, monkeypatch):
    secret = service.project / ".env"
    secret.write_text("synthetic-private-test-content", encoding="utf-8")
    original = native._sha
    def checked(path):
        assert path != secret, "Credential content was read"
        return original(path)
    monkeypatch.setattr(native, "_sha", checked)
    context = must(service.call("suite_context", {}))
    assert context["assets"][0]["credential_content_omitted"] is True
    assert context["assets"][0]["sha256"] is None
    assert service.call("suite_project_op", {"operation": "audit"})["error"]["code"] == "credential_path"


def test_linked_tools_and_runner_timeouts_have_structured_errors(service, monkeypatch):
    path = service.root / "tools/sprites.py"
    monkeypatch.setattr(native, "is_link_or_reparse", lambda item: item == path)
    assert service.call("suite_tool_describe", {"name": path.name})["error"]["code"] == "unknown_tool"
    monkeypatch.setattr(native, "is_link_or_reparse", lambda item: False)
    def timeout(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"], output="not echoed")
    service.runner = timeout
    result = service.call("suite_tool_run", {"name": path.name, "arguments": []})
    assert result["error"]["code"] == "timeout" and "not echoed" not in json.dumps(result)

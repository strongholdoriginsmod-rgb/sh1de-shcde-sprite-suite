"""Owned temporary projects; no account calls or external execution targets."""
import hashlib
import json
from pathlib import Path
import subprocess
from threading import Thread
import time

import pytest

from suite_assistant_code import NativeCodeTools


@pytest.fixture(autouse=True)
def isolated_suite_work(tmp_path, monkeypatch):
    """Use the real shared metadata API, isolated from the user's work folder."""
    import hud_menu_workspace as hud
    monkeypatch.setattr(hud, "WORK", tmp_path.parent)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def invoke(service, operation, **arguments):
    return service.call("suite_code", dict(operation=operation, **arguments))


def success(service, operation, **arguments):
    result = invoke(service, operation, **arguments)
    assert result["ok"], result
    return result["result"]


def test_specs_typed_default_execution_disabled_and_unknown_tools(tmp_path):
    service = NativeCodeTools(lambda: tmp_path)
    spec, = service.specs()
    assert spec["type"] == "function" and spec["name"] == "suite_code"
    assert NativeCodeTools.requires_gui_thread is False
    assert "not an OS sandbox" in spec["description"]
    assert service.call("os_shell", {})["error"]["code"] == "unknown_tool"
    assert invoke(service, "run", path="helper.py", expected_sha256="0" * 64)["error"]["code"] == "execution_disabled"


@pytest.mark.parametrize("extension", ["cs", "lua", "py", "json", "xaml", "toml", "customformat"])
def test_real_project_create_read_cas_write_and_backup_no_extension_gate(tmp_path, extension):
    service = NativeCodeTools(lambda: tmp_path)
    name = f"Scripts ü/source.{extension}"
    original = "// UTF-8 source ü\n"
    created = success(service, "write", path=name, content=original, expected_sha256="")
    read = success(service, "read", path=name)
    assert read["content"] == original and read["sha256"] == created["sha256"]
    changed = success(service, "write", path=name, content="new source\n", expected_sha256=read["sha256"])
    assert Path(changed["backup"]).read_bytes() == original.encode("utf-8")
    assert (tmp_path / name).read_text(encoding="utf-8") == "new source\n"
    rejected = invoke(service, "write", path=name, content="lost edit", expected_sha256=read["sha256"])
    assert rejected["error"]["code"] == "stale_sha"
    assert (tmp_path / name).read_bytes() == b"new source\n"
    assert success(service, "list")["files"] == [{"path": name, "size": 11}]


@pytest.mark.parametrize("path", ["../outside.py", "/absolute.py", "C:/outside.py", "dir\\file.py", "dir/../file.py", "CON.py", "file.py:secret", ".env", ".codex/auth.json", "credentials.json", ".npmrc", ".git/config", ".SPRITESUITE-CODE-HISTORY/backup.before"])
def test_traversal_devices_credentials_and_history_are_rejected(tmp_path, path):
    service = NativeCodeTools(lambda: tmp_path)
    result = invoke(service, "write", path=path, content="blocked", expected_sha256="")
    assert result["ok"] is False
    assert result["error"]["code"] in {"unsafe_path", "credential_path"}
    assert list(tmp_path.iterdir()) == []


def test_symbolic_links_are_not_followed(tmp_path):
    outside = tmp_path / "outside"
    project = tmp_path / "project"
    outside.mkdir()
    project.mkdir()
    (outside / "secret.py").write_text("private")
    linked = project / "linked"
    try:
        linked.symlink_to(outside, target_is_directory=True)
    except OSError:
        if not hasattr(subprocess, "CREATE_NO_WINDOW"):
            pytest.skip("Host cannot create a temporary link")
        result = subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(linked), str(outside)], capture_output=True, check=False)
        if result.returncode:
            pytest.skip("Host cannot create a temporary junction")
    service = NativeCodeTools(lambda: project)
    assert invoke(service, "read", path="linked/secret.py")["error"]["code"] == "unsafe_path"
    assert success(service, "list")["files"] == []


def test_read_and_list_pagination_bounded_text_and_schema_errors(tmp_path):
    service = NativeCodeTools(lambda: tmp_path)
    for number in range(3):
        (tmp_path / f"{number}.lua").write_text("abcdefghü", encoding="utf-8")
    listed = success(service, "list", offset=1, limit=1)
    assert len(listed["files"]) == 1 and listed["total"] == 3 and listed["next_offset"] == 2
    read = success(service, "read", path="0.lua", offset=3, max_chars=2)
    assert read["content"] == "de" and read["next_offset"] == 5
    for args in ({"operation": "run", "shell": "echo BAD"}, {"operation": "list", "limit": True}, {"operation": "write", "path": "x.py", "content": "x"}):
        assert service.call("suite_code", args)["error"]["code"] == "invalid_arguments"
    assert invoke(service, "write", path="x.py", content="x" * 524289, expected_sha256="")["error"]["code"] == "invalid_arguments"


def test_binary_and_oversize_files_are_explicit_not_text_errors(tmp_path):
    service = NativeCodeTools(lambda: tmp_path)
    (tmp_path / "binary.png").write_bytes(b"\x89PNG\0\xff")
    assert invoke(service, "read", path="binary.png")["error"]["code"] == "not_text"
    (tmp_path / "large.py").write_bytes(b"#" * (2 * 1024 * 1024 + 1))
    assert invoke(service, "read", path="large.py")["error"]["code"] == "file_limit"


def test_python_run_real_unicode_argv_project_access_and_sanitized_environment(tmp_path, monkeypatch):
    enabled = [True]
    service = NativeCodeTools(lambda: tmp_path, execution_enabled=lambda: enabled[0])
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-secret")
    monkeypatch.setenv("CODEX_ACCESS_TOKEN", "test-only-token")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test-only-cloud-key")
    source = 'import json,os,sys\nfrom pathlib import Path\nPath("actual output ü.txt").write_text("actual",encoding="utf-8")\nprint(json.dumps({"argv":sys.argv[1:],"cwd":str(Path.cwd()),"keys":[key for key in os.environ if key in ("OPENAI_API_KEY","CODEX_ACCESS_TOKEN","AWS_ACCESS_KEY_ID")]},ensure_ascii=False))\n'
    written = success(service, "write", path="helpers/my helper ü.py", content=source, expected_sha256="")
    args = ["a b", "ü", "$(not a shell)", "x&echo BAD"]
    result = success(service, "run", path="helpers/my helper ü.py", expected_sha256=written["sha256"], arguments=args)
    data = json.loads(result["stdout"])
    assert data == {"argv": args, "cwd": str(tmp_path), "keys": []}
    assert (tmp_path / "actual output ü.txt").read_text(encoding="utf-8") == "actual"
    assert result["os_sandbox"] is False and result["executed_reviewed_snapshot"] is True
    assert not list((tmp_path / "helpers").glob(".suite-run-*"))
    enabled[0] = False
    assert invoke(service, "run", path="helpers/my helper ü.py", expected_sha256=written["sha256"])["error"]["code"] == "execution_disabled"


def test_python_run_stale_sha_and_non_python_target_never_execute(tmp_path):
    service = NativeCodeTools(lambda: tmp_path, execution_enabled=lambda: True)
    path = tmp_path / "helper.py"
    path.write_text('from pathlib import Path\nPath("should_not_exist").touch()')
    assert invoke(service, "run", path="helper.py", expected_sha256="0" * 64)["error"]["code"] == "stale_sha"
    assert invoke(service, "run", path="helper.py")["error"]["code"] == "invalid_arguments"
    assert invoke(service, "run", path="other.exe", expected_sha256="0" * 64)["error"]["code"] == "invalid_arguments"
    assert not (tmp_path / "should_not_exist").exists()


def test_python_timeout_and_nonzero_exit_report_real_failure(tmp_path):
    service = NativeCodeTools(lambda: tmp_path, execution_enabled=lambda: True)
    source = "import time\ntime.sleep(20)"
    script = success(service, "write", path="wait.py", content=source, expected_sha256="")
    started = time.monotonic()
    result = invoke(service, "run", path="wait.py", expected_sha256=script["sha256"], timeout_seconds=1)
    assert result["error"]["code"] == "timeout" and time.monotonic() - started < 12
    script = success(service, "write", path="fail.py", content='import sys\nprint("actual failure",file=sys.stderr)\nsys.exit(7)', expected_sha256="")
    result = invoke(service, "run", path="fail.py", expected_sha256=script["sha256"])
    assert result["error"]["code"] == "script_failed"
    assert result["error"]["details"]["returncode"] == 7
    assert "actual failure" in result["error"]["details"]["stderr"]


def test_cancel_process_tree_and_reset_resume(tmp_path):
    service = NativeCodeTools(lambda: tmp_path, execution_enabled=lambda: True)
    source = 'import subprocess,sys,time\nfrom pathlib import Path\nchild=subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"])\nPath("child.pid").write_text(str(child.pid))\ntime.sleep(30)'
    script = success(service, "write", path="tree.py", content=source, expected_sha256="")
    results = []
    worker = Thread(target=lambda: results.append(invoke(service, "run", path="tree.py", expected_sha256=script["sha256"])))
    worker.start()
    deadline = time.monotonic() + 5
    while not (tmp_path / "child.pid").exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert (tmp_path / "child.pid").exists()
    service.cancel()
    worker.join(12)
    assert not worker.is_alive() and results[0]["error"]["code"] == "cancelled"
    # A fresh call remains cancelled until the host starts another explicit turn.
    assert invoke(service, "list")["error"]["code"] == "cancelled"
    service.reset_cancel()
    assert invoke(service, "list")["ok"]
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        process_id = (tmp_path / "child.pid").read_text()
        probe = subprocess.run(["tasklist.exe", "/FI", f"PID eq {process_id}", "/FO", "CSV", "/NH"], capture_output=True, text=True, check=False)
        assert f'"{process_id}"' not in probe.stdout


def test_provider_project_changes_rebind_without_old_project_writes(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    current = [first]
    service = NativeCodeTools(lambda: current[0])
    success(service, "write", path="script.py", content="first", expected_sha256="")
    current[0] = second
    success(service, "write", path="script.py", content="second", expected_sha256="")
    assert (first / "script.py").read_text() == "first"
    assert (second / "script.py").read_text() == "second"


def test_write_cancel_and_external_save_race_preserve_actual_file(tmp_path, monkeypatch):
    import suite_assistant_code as module
    service = NativeCodeTools(lambda: tmp_path)
    original = success(service, "write", path="source.cs", content="original", expected_sha256="")
    target = tmp_path / "source.cs"
    calls = 0
    original_cancel = service._check_cancel

    def cancel_at_commit():
        nonlocal calls
        calls += 1
        if calls == 3:
            service.cancel()
        original_cancel()

    monkeypatch.setattr(service, "_check_cancel", cancel_at_commit)
    result = invoke(service, "write", path="source.cs", content="cancelled edit", expected_sha256=original["sha256"])
    assert result["error"]["code"] == "cancelled" and target.read_text() == "original"
    assert not list(tmp_path.glob(".code-write-*"))
    monkeypatch.setattr(service, "_check_cancel", original_cancel)
    service.reset_cancel()
    fsync = module.os.fsync

    def external_save(descriptor):
        fsync(descriptor)
        target.write_text("user's newer edit")

    monkeypatch.setattr(module.os, "fsync", external_save)
    result = invoke(service, "write", path="source.cs", content="must not win", expected_sha256=original["sha256"])
    assert result["error"]["code"] == "stale_sha"
    assert target.read_text() == "user's newer edit"


def test_run_uses_reviewed_snapshot_even_if_original_changes_before_spawn(tmp_path, monkeypatch):
    import suite_assistant_code as module
    service = NativeCodeTools(lambda: tmp_path, execution_enabled=lambda: True)
    script = success(service, "write", path="helper.py", content='print("reviewed")', expected_sha256="")
    execute = module._CodeProcess._execute

    def save_and_execute(process, command, timeout):
        (tmp_path / "helper.py").write_text('print("unreviewed")')
        return execute(process, command, timeout)

    monkeypatch.setattr(module._CodeProcess, "_execute", save_and_execute)
    result = success(service, "run", path="helper.py", expected_sha256=script["sha256"])
    assert result["stdout"].strip() == "reviewed"
    assert (tmp_path / "helper.py").read_text() == 'print("unreviewed")'


def test_run_capture_output_truncation_and_output_budget(tmp_path, monkeypatch):
    import suite_native_tools
    service = NativeCodeTools(lambda: tmp_path, execution_enabled=lambda: True)
    script = success(service, "write", path="output.py", content='print("x"*70000)', expected_sha256="")
    result = success(service, "run", path="output.py", expected_sha256=script["sha256"])
    assert result["output_truncated"] and len(result["stdout"].encode("utf-8")) <= 32768
    monkeypatch.setattr(suite_native_tools, "MAX_CAPTURE", 65536)
    script = success(service, "write", path="overflow.py", content='import sys,time\nsys.stdout.write("x"*1000000)\nsys.stdout.flush()\ntime.sleep(5)', expected_sha256="")
    result = invoke(service, "run", path="overflow.py", expected_sha256=script["sha256"])
    assert result["error"]["code"] == "output_limit"
    assert len(result["error"]["details"]["stdout"].encode("utf-8")) <= 32768


def test_code_revisions_use_shared_private_metadata_not_installable_project(tmp_path):
    import hud_menu_workspace as hud
    from suite_unified_project import ProjectPipeline
    from zipfile import ZipFile
    service = NativeCodeTools(lambda: tmp_path)
    first = success(service, "write", path="Scripts/helper.lua", content="old private revision", expected_sha256="")
    current = success(service, "write", path="Scripts/helper.lua", content="current mod source", expected_sha256=first["sha256"])
    metadata = hud._metadata_dir(tmp_path)
    assert Path(current["backup"]).parent == metadata / "code-revs"
    assert Path(current["backup"]).read_text() == "old private revision"
    assert not (tmp_path / ".spritesuite-code-history").exists()
    assert {asset.relative_path for asset in hud.list_assets(tmp_path, include_mod_files=True)} == {"Scripts/helper.lua"}
    result = ProjectPipeline(tmp_path).build(guid="native.code.history.qa", name="Code source")
    with ZipFile(result["zip"]) as archive:
        assert not any("code-revs" in name or name.endswith((".before", "write.lock")) for name in archive.namelist())
        assert any(name.endswith("Scripts/helper.lua") for name in archive.namelist())

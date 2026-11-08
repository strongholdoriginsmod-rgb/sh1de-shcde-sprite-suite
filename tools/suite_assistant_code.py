"""Project source editing and local Python under user-selected host settings.

Source editing uses project-relative paths, SHA compare-and-swap and immutable
revision backups. Python helpers run with the Suite user's normal OS rights:
this is not an OS sandbox. They can access normal project files. Only the host
user option controls execution; no model argument can change that setting.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from threading import Event
import uuid

from suite_native_tools import NativeToolError, NativeToolService, _credential_path, _validate
from suite_windows_paths import is_link_or_reparse, is_reserved_windows_component

MAX_FILE = 2 * 1024 * 1024
HISTORY = ".spritesuite-code-history"

SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["operation"],
    "properties": {
        "operation": {"type": "string", "enum": ["list", "read", "write", "run"]},
        "path": {"type": "string", "minLength": 1, "maxLength": 240},
        "content": {"type": "string", "maxLength": 524288},
        "expected_sha256": {"type": "string", "pattern": "^(?:[0-9a-f]{64})?$"},
        "arguments": {"type": "array", "maxItems": 64, "items": {"type": "string", "maxLength": 4096}},
        "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 120},
        "offset": {"type": "integer", "minimum": 0},
        "limit": {"type": "integer", "minimum": 1, "maximum": 200},
        "max_chars": {"type": "integer", "minimum": 1, "maximum": 65536},
    },
}


def _error(code, message, **details):
    raise NativeToolError(code, message, details or None)


def _sha(data):
    return hashlib.sha256(data).hexdigest()


class _CodeProcess(NativeToolService):
    """Reuse the existing bounded capture, timeout and process-tree cancellation."""

    def __init__(self, project, cancelled):
        super().__init__(project, root=project)
        self._cancel = cancelled

    def _environment(self):
        environment = super()._environment()
        for name in list(environment):
            upper = name.upper()
            if any(part in upper for part in ("_KEY", "TOKEN", "PASSWORD", "SECRET", "CREDENTIAL", "AUTH")) or upper in {
                "OPENAI_BASE_URL", "OPENAI_API_BASE", "CODEX_CHATGPT_BASE_URL", "CODEX_HOME",
            }:
                environment.pop(name, None)
        environment["PYTHONPATH"] = str(self.project)
        return environment


@contextmanager
def _lock(folder):
    """Kernel-owned lock, released even if a helper/application exits."""
    target = folder / "write.lock"
    if is_link_or_reparse(target):
        _error("unsafe_path", "Linked revision lock")
    with target.open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            _error("project_busy", "Another code write is committing; read current SHA and retry")
        try:
            yield
        finally:
            try:
                stream.seek(0)
                if os.name == "nt":
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass


class NativeCodeTools:
    requires_gui_thread = False

    def __init__(self, project_provider, execution_enabled=None):
        self.project_provider = project_provider
        self.execution_enabled = execution_enabled or (lambda: False)
        self._cancel = Event()

    def specs(self):
        return [{"type": "function", "name": "suite_code", "description": (
            "List/read/write normal source files in the CURRENT project with SHA CAS and revision backups. "
            "Supports C#, Lua, Python, JSON, XAML and other UTF-8 project text without extension gates. "
            "write requires expected_sha256 from read (empty string only for a new file). "
            "run executes an explicit .py project helper with expected SHA only when the HUMAN host option permits. "
            "Python has normal local Suite OS rights and project access; this is not an OS sandbox. "
            "No shell command strings, credential files or model-controlled execution approval."), "inputSchema": SCHEMA}]

    def cancel(self):
        self._cancel.set()

    def reset_cancel(self):
        self._cancel.clear()

    def _check_cancel(self):
        if self._cancel.is_set():
            _error("cancelled", "Code operation was cancelled")

    def _project(self):
        value = self.project_provider()
        if value is None:
            _error("no_project", "Open or create a project first")
        path = Path(value).absolute()
        for node in (path, *path.parents):
            if is_link_or_reparse(node):
                _error("unsafe_path", "Linked project directories are not accepted")
        path = path.resolve()
        if not path.is_dir() or _credential_path(path):
            _error("invalid_project", "Project must be a normal existing project directory")
        return path

    def _path(self, root, relative):
        if not isinstance(relative, str) or not relative or "\\" in relative or "\0" in relative:
            _error("unsafe_path", "Use a project-relative path with / separators")
        parts = relative.split("/")
        if any(part in {"", ".", ".."} or part.casefold() == HISTORY or is_reserved_windows_component(part) for part in parts):
            _error("unsafe_path", "Unsafe project-relative path")
        if _credential_path(relative) or any(part.casefold() in {".git", ".hg", ".svn", ".npmrc", ".pypirc", ".git-credentials", "service-account.json"} for part in parts):
            _error("credential_path", "Credentials and version-control internals are outside code tools")
        path = root.joinpath(*parts)
        for node in (path, *path.parents):
            if node == root.parent:
                break
            if is_link_or_reparse(node):
                _error("unsafe_path", "Linked project paths are not accepted")
        if not path.resolve(strict=False).is_relative_to(root):
            _error("unsafe_path", "Path leaves the project")
        return path

    def _read_bytes(self, path):
        if not path.is_file():
            _error("not_found", "Project file does not exist")
        if path.stat().st_size > MAX_FILE:
            _error("file_limit", "Code file exceeds the 2 MiB editing budget")
        with path.open("rb") as stream:
            raw = stream.read(MAX_FILE + 1)
        if len(raw) > MAX_FILE:
            _error("file_limit", "Code file exceeds the 2 MiB editing budget")
        return raw

    def _text(self, raw):
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            _error("not_text", "Code files must be UTF-8 text")
        if "\0" in text:
            _error("not_text", "Binary project files are handled by native asset tools")
        return text

    def call(self, name, args):
        try:
            if name != "suite_code":
                _error("unknown_tool", "Unknown native code tool")
            _validate(args, SCHEMA)
            for key, value in args.items():
                specification = SCHEMA["properties"][key]
                if isinstance(value, str) and len(value) > specification.get("maxLength", 1000000):
                    _error("invalid_arguments", "Argument is too long", argument=key)
            if any(len(value) > 4096 for value in args.get("arguments", [])):
                _error("invalid_arguments", "Script argument is too long")
            self._check_cancel()
            root = self._project()
            operation = args["operation"]
            allowed = {
                "list": {"operation", "path", "offset", "limit"},
                "read": {"operation", "path", "offset", "max_chars"},
                "write": {"operation", "path", "content", "expected_sha256"},
                "run": {"operation", "path", "expected_sha256", "arguments", "timeout_seconds"},
            }[operation]
            if set(args) - allowed:
                _error("invalid_arguments", "Arguments do not apply to this operation")
            if operation == "list":
                result = self._list(root, args)
            else:
                if "path" not in args:
                    _error("invalid_arguments", "This operation requires path")
                path = self._path(root, args["path"])
                if operation == "read":
                    raw = self._read_bytes(path)
                    text = self._text(raw)
                    offset = args.get("offset", 0)
                    end = offset + args.get("max_chars", 32768)
                    result = dict(path=args["path"], sha256=_sha(raw), content=text[offset:end], total_chars=len(text),
                                  next_offset=end if end < len(text) else None)
                elif operation == "write":
                    result = self._write(root, path, args)
                else:
                    result = self._run(root, path, args)
            return {"ok": True, "result": result}
        except NativeToolError as exc:
            return {"ok": False, "error": {"code": exc.code, "message": str(exc), "details": exc.details}}
        except (OSError, ValueError, TypeError) as exc:
            return {"ok": False, "error": {"code": "operation_failed", "message": str(exc)}}

    def _list(self, root, args):
        directory = self._path(root, args["path"]) if args.get("path") else root
        if not directory.is_dir():
            _error("not_found", "Project directory does not exist")
        files = []
        truncated = False
        for parent, directories, names in os.walk(directory, followlinks=False):
            self._check_cancel()
            directories[:] = sorted(name for name in directories if name.casefold() != HISTORY and not is_link_or_reparse(Path(parent) / name)
                                    and not _credential_path(name) and name.casefold() not in {".git", ".hg", ".svn", ".npmrc", ".pypirc"})
            for name in sorted(names):
                path = Path(parent) / name
                relative = path.relative_to(root).as_posix()
                if is_link_or_reparse(path) or _credential_path(relative) or name.casefold() in {".npmrc", ".pypirc", ".git-credentials", "service-account.json"}:
                    continue
                files.append(dict(path=relative, size=path.stat().st_size))
                if len(files) >= 5000:
                    truncated = True
                    break
            if truncated:
                break
        offset, limit = args.get("offset", 0), args.get("limit", 100)
        return dict(project=str(root), files=files[offset:offset + limit], total=len(files),
                    next_offset=offset + limit if offset + limit < len(files) else None, scan_truncated=truncated)

    def _write(self, root, path, args):
        if "content" not in args or "expected_sha256" not in args:
            _error("invalid_arguments", "write requires content and expected_sha256; use '' only for new files")
        expected = args["expected_sha256"]
        if not re.fullmatch(r"(?:[0-9a-f]{64})?", expected):
            _error("invalid_arguments", "Invalid expected_sha256")
        raw = args["content"].encode("utf-8")
        if len(raw) > MAX_FILE or b"\0" in raw:
            _error("file_limit", "Source must be UTF-8 text within 2 MiB")
        import hud_menu_workspace as hud
        history = hud._metadata_dir(root) / "code-revs"
        if any(is_link_or_reparse(node) for node in (history, *history.parents)):
            _error("unsafe_path", "Linked revision history")
        history.mkdir(parents=True, exist_ok=True)
        with _lock(history):
            self._path(root, args["path"])
            old = self._read_bytes(path) if path.exists() else None
            if ("" if old is None else _sha(old)) != expected:
                _error("stale_sha", "File changed; read its current SHA before writing")
            if old is not None:
                self._text(old)
            self._check_cancel()
            path.parent.mkdir(parents=True, exist_ok=True)
            revision = uuid.uuid4().hex[:12]
            backup = None
            if old is not None:
                backup = history / (revision + ".before")
                with backup.open("xb") as stream:
                    stream.write(old)
            receipt = history / (revision + ".json")
            receipt.write_text(json.dumps(dict(path=args["path"], before_sha256=expected,
                                              after_sha256=_sha(raw), backup=backup.name if backup else None,
                                              state="prepared", verification="Compare current source SHA with after_sha256")), encoding="utf-8")
            descriptor, temporary = tempfile.mkstemp(prefix=".code-write-", dir=path.parent)
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                self._check_cancel()
                self._path(root, args["path"])
                current = self._read_bytes(path) if path.exists() else None
                if ("" if current is None else _sha(current)) != expected:
                    _error("stale_sha", "File changed during write; current file retained")
                if old is None:
                    try:
                        os.link(temporary, path)
                    except FileExistsError:
                        _error("stale_sha", "File was created by another operation")
                else:
                    os.replace(temporary, path)
                return dict(path=args["path"], sha256=_sha(raw), revision=revision,
                            backup=str(backup) if backup else None, receipt=str(receipt), written=True)
            finally:
                Path(temporary).unlink(missing_ok=True)

    def _run(self, root, path, args):
        if self.execution_enabled() is not True:
            _error("execution_disabled", "The human host option 'Run local Python helpers' is disabled")
        if path.suffix.lower() != ".py" or "expected_sha256" not in args:
            _error("invalid_arguments", "run requires an explicit .py project file and expected_sha256")
        raw = self._read_bytes(path)
        self._text(raw)
        if not re.fullmatch(r"[0-9a-f]{64}", args["expected_sha256"]) or _sha(raw) != args["expected_sha256"]:
            _error("stale_sha", "Read and review the current script SHA before running")
        self._check_cancel()
        if self.execution_enabled() is not True:
            _error("execution_disabled", "Local Python execution was disabled before process start")
        import sys
        arguments = args.get("arguments", [])
        if any(_credential_path(value) or _credential_path(value.split("=", 1)[-1]) for value in arguments):
            _error("credential_path", "Credential paths are not script arguments")
        # Execute the reviewed bytes, not a pathname that a GUI save could alter
        # after the hash check. A sibling keeps ordinary local helper imports.
        descriptor, snapshot = tempfile.mkstemp(prefix=".suite-run-", suffix=".py", dir=path.parent)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            self._check_cancel()
            result = _CodeProcess(root, self._cancel)._execute([sys.executable, snapshot, *arguments], args.get("timeout_seconds", 30))
        finally:
            snapshot_path = Path(snapshot)
            try:
                if (snapshot_path.is_file() and not is_link_or_reparse(snapshot_path)
                        and snapshot_path.stat().st_size == len(raw)):
                    with snapshot_path.open("rb") as stream:
                        unchanged = _sha(stream.read(len(raw) + 1)) == _sha(raw)
                    if unchanged:
                        snapshot_path.unlink()
            except OSError:
                pass  # A helper-modified snapshot is never blindly deleted.
        result.update(path=args["path"], sha256=_sha(raw), executed=True, project=str(root), os_sandbox=False)
        result["executed_reviewed_snapshot"] = True
        if result["returncode"]:
            _error("script_failed", "Project Python helper returned a failure exit code", **result)
        return result

"""Native project and CLI tools for the integrated ChatGPT/Codex assistant.

The service uses the existing Suite pipeline and static argparse catalog.
There is no model endpoint, account API, arbitrary Python evaluation or
GUI dependency here. The conversation host owns login and editor UI sync.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
from zipfile import ZipFile

from suite_catalog import describe, format_static_help
from suite_tool_policy import classify
from suite_windows_paths import is_link_or_reparse

ROOT = Path(__file__).resolve().parents[1]
MAX_CAPTURE = 4 * 1024 * 1024
MAX_TEXT = 32768


class NativeToolError(ValueError):
    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code, self.details = code, details


def _json_value(value):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _credential_path(value: str | Path) -> bool:
    parts = str(value).replace("\\", "/").casefold().split("/")
    private = {".codex", ".ssh", ".aws", ".azure", ".gnupg", "gcloud"}
    names = {"auth.json", "credentials", "credentials.json", "credentials.db",
             "id_rsa", "id_ed25519", "login data", "cookies"}
    return any(part in private or part in names or part == ".env" or
               part.startswith(".env.") for part in parts)


def _check_path(value: str | Path) -> Path:
    path = Path(value)
    if _credential_path(path):
        raise NativeToolError("credential_path", "Credential files are outside assistant tool inputs")
    # Check the original path before resolving links to a private profile.
    if _credential_path(path.resolve(strict=False)):
        raise NativeToolError("credential_path", "Input resolves to a credential location")
    return path


def _object(properties: dict, required: tuple[str, ...] = ()) -> dict:
    return {"type": "object", "properties": properties,
            "required": list(required), "additionalProperties": False}


STRING = {"type": "string", "minLength": 1}
PAGING = {"offset": {"type": "integer", "minimum": 0},
          "limit": {"type": "integer", "minimum": 1, "maximum": 500}}
PROJECT_PROPERTIES = {
    "operation": {"type": "string", "enum": ["create_image", "import_image",
        "import_mod_file", "import_patch", "inspect", "audit", "build", "backup",
        "restore", "new", "open", "publish_ui_atlas"]},
    **{name: STRING for name in ("source", "relative_path", "category", "name",
        "guid", "author", "version", "output", "project", "project_name", "game_document",
        "atlas_workspace", "expected_revision")},
    "width": {"type": "integer", "minimum": 1, "maximum": 16384},
    "height": {"type": "integer", "minimum": 1, "maximum": 16384},
}
PROJECT_PROPERTIES["relative_path"] = {**STRING,
    "description": "Required for inspect and import_mod_file: exact project-relative asset path from suite_context."}
PROJECT_PROPERTIES["guid"] = {**STRING,
    "description": "Required for build: creator-owned mod GUID, for example org.creator.my_mod."}
PROJECT_PROPERTIES["name"] = {**STRING,
    "description": "Required for build (display name), create_image (image name), and new (project slug)."}
PROJECT_PROPERTIES["source"] = {**STRING,
    "description": "Required input file for import_image/import_mod_file/import_patch, or backup ZIP for restore."}
SCHEMAS = {
    "suite_context": _object({**PAGING, "include_audit": {"type": "boolean"}}),
    "suite_tool_catalog": _object({**PAGING, "query": {"type": "string"}}),
    "suite_tool_describe": _object({"name": STRING}, ("name",)),
    "suite_tool_run": _object({"name": STRING,
        "arguments": {"type": "array", "items": {"type": "string"}, "maxItems": 1000},
        "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 300},
        "destructive": {"type": "boolean"}}, ("name", "arguments")),
    "suite_project_op": _object(PROJECT_PROPERTIES, ("operation",)),
}
DESCRIPTIONS = {
    "suite_context": "Read the active SpriteSuite project, asset inventory and content hashes. Optional pipeline audit.",
    "suite_tool_catalog": "Discover every local tools/*.py or *.pyw script with static CLI metadata. Paginated, no script execution.",
    "suite_tool_describe": "Describe an existing local tool and all statically declared commands and arguments without executing it.",
    "suite_tool_run": "Run one existing Suite script with an exact argv list. Help stays static. Game/unknown effects require host approval.",
    "suite_project_op": "Use the real project pipeline. inspect REQUIRES relative_path from suite_context; build REQUIRES guid and name. Imports require source; import_mod_file also requires relative_path. Originals stay intact.",
}


def _validate(value, schema: dict, key: str = "arguments") -> None:
    kind = schema.get("type")
    valid = {"object": isinstance(value, dict), "array": isinstance(value, list),
             "string": isinstance(value, str), "integer": isinstance(value, int) and not isinstance(value, bool),
             "boolean": isinstance(value, bool)}.get(kind, False)
    if not valid:
        raise NativeToolError("invalid_arguments", f"{key} must be {kind}")
    if kind == "object":
        if set(value) - set(schema["properties"]):
            raise NativeToolError("invalid_arguments", "Unknown argument fields")
        for required in schema.get("required", ()):
            if required not in value:
                raise NativeToolError("invalid_arguments", "Missing argument: " + required)
        for name, item in value.items():
            _validate(item, schema["properties"][name], name)
    elif kind == "array":
        if len(value) > schema.get("maxItems", 10000):
            raise NativeToolError("invalid_arguments", key + " has too many items")
        for item in value:
            _validate(item, schema["items"], key)
    elif kind == "string":
        if "\0" in value or len(value) < schema.get("minLength", 0):
            raise NativeToolError("invalid_arguments", key + " is empty or contains NUL")
    elif kind == "integer":
        if value < schema.get("minimum", value) or value > schema.get("maximum", value):
            raise NativeToolError("invalid_arguments", key + " is outside the allowed range")
    if "enum" in schema and value not in schema["enum"]:
        raise NativeToolError("invalid_arguments", "Unknown " + key)


class NativeToolService:
    def __init__(self, project: Path, root: Path = ROOT, runner=None, approval=None):
        self.project = Path(project)
        self.root = Path(root).resolve()
        self.runner, self.approval = runner, approval
        self._cancel = threading.Event()
        self._lock = threading.Lock()

    def specs(self) -> list[dict]:
        # Return independent JSON values so a conversation host cannot mutate
        # validation schemas when adding its own GUI tools.
        return json.loads(json.dumps([{"type": "function", "name": name,
            "description": DESCRIPTIONS[name], "inputSchema": schema}
            for name, schema in SCHEMAS.items()]))

    def cancel(self) -> None:
        self._cancel.set()

    def reset_cancel(self) -> None:
        """Begin a new conversation turn before any asynchronous work starts."""
        self._cancel.clear()

    def call(self, name: str, args: dict) -> dict:
        if not self._lock.acquire(blocking=False):
            return {"ok": False, "error": {"code": "busy", "message": "A native tool call is already running"}}
        try:
            if name not in SCHEMAS:
                raise NativeToolError("unknown_tool", "Unknown native tool")
            _validate(args, SCHEMAS[name])
            method = {"suite_context": self._context, "suite_tool_catalog": self._catalog,
                      "suite_tool_describe": self._describe, "suite_tool_run": self._run,
                      "suite_project_op": self._project_op}[name]
            return {"ok": True, "result": _json_value(method(args))}
        except NativeToolError as error:
            result = {"code": error.code, "message": str(error)}
            if error.details is not None:
                result["details"] = _json_value(error.details)
            return {"ok": False, "error": result}
        except Exception as error:
            return {"ok": False, "error": {"code": "operation_failed",
                    "message": "Native operation failed. Check the selected inputs and tool status.",
                    "type": type(error).__name__}}
        finally:
            self._lock.release()

    def _tool(self, name: str) -> Path:
        if (Path(name).name != name or "/" in name or "\\" in name or ":" in name or
                Path(name).suffix not in {".py", ".pyw"}):
            raise NativeToolError("unknown_tool", "Choose an existing tool filename from the catalog")
        path = self.root / "tools" / name
        _check_path(path)
        if (not path.is_file() or is_link_or_reparse(path) or
                is_link_or_reparse(path.parent)):
            raise NativeToolError("unknown_tool", "Local tool is missing or linked")
        return path

    def _metadata(self, path: Path) -> dict:
        try:
            meta = describe(path)
        except (SyntaxError, ValueError, UnicodeError) as error:
            meta = {"description": path.name, "commands": [], "fields": [],
                    "static_parse_error": str(error)}
        return {"id": "tool:" + path.name, "name": path.name,
                "sha256": _sha(path), "metadata": meta,
                "policy": classify(path.name, []).category,
                "executed": False}

    def _catalog(self, args: dict) -> dict:
        query = args.get("query", "").casefold()
        directory = _check_path(self.root / "tools")
        if is_link_or_reparse(directory):
            raise NativeToolError("invalid_arguments", "Linked tool catalog directory")
        paths = sorted((p for p in directory.iterdir()
                        if p.suffix in {".py", ".pyw"} and p.is_file() and
                        not is_link_or_reparse(p)), key=lambda p: p.name.casefold())
        items = []
        for path in paths:
            meta = self._metadata(path)
            if not query or query in (path.name + " " + meta["metadata"]["description"]).casefold():
                items.append(meta)
        offset, limit = args.get("offset", 0), args.get("limit", 100)
        return {"items": items[offset:offset + limit], "total": len(items),
                "offset": offset, "next_offset": offset + limit if offset + limit < len(items) else None,
                "executed": False}

    def _describe(self, args: dict) -> dict:
        result = self._metadata(self._tool(args["name"]))
        result["static_help"] = format_static_help(result["metadata"])
        return result

    def _pipeline(self):
        source = str(Path(__file__).resolve().parents[1] / "src")
        if source not in sys.path:
            sys.path.insert(0, source)
        from suite_unified_project import ProjectPipeline
        _check_path(self.project)
        pipeline = ProjectPipeline(self.project)
        self.project = pipeline.project
        return pipeline

    def _safe_assets(self, pipeline):
        assets = pipeline.assets()
        for asset in assets:
            _check_path(asset.path)
        return assets

    def _context(self, args: dict) -> dict:
        pipeline = self._pipeline()
        assets = pipeline.assets()
        offset, limit = args.get("offset", 0), args.get("limit", 100)
        rows = []
        for asset in assets[offset:offset + limit]:
            private = _credential_path(asset.path)
            if not private:
                _check_path(asset.path)
            rows.append({"id": "asset:" + asset.relative_path,
                         "path": asset.relative_path, "kind": asset.kind,
                         "status": asset.status, "bytes": asset.size,
                         "sha256": None if private else _sha(asset.path),
                         "credential_content_omitted": private})
        result = {"project": str(pipeline.project), "assets": rows, "total": len(assets),
                  "offset": offset, "next_offset": offset + limit if offset + limit < len(assets) else None,
                  "pipeline": "ProjectPipeline", "native_game_runtime_verified": False}
        import hud_menu_workspace
        result["image_categories"] = list(hud_menu_workspace.CATEGORIES)
        result["project_operations"] = PROJECT_PROPERTIES["operation"]["enum"]
        if args.get("include_audit"):
            if not assets:
                warning = {"code": "no_assets", "message": "The project is empty. Create or import an asset before auditing."}
                result["audit"] = {"ok": False, "error": warning}
                result["warnings"] = [warning]
            else:
                self._safe_assets(pipeline)
                from suite_unified_project import UnifiedFlowError
                from se_asset_package import AssetModError
                try:
                    result["audit"] = pipeline.audit()
                except (hud_menu_workspace.WorkshopError, UnifiedFlowError, AssetModError) as error:
                    raise NativeToolError("asset_audit_failed", "Existing project assets failed the pipeline integrity audit.",
                        {"context": result, "type": type(error).__name__}) from error
        return result

    def _authorize(self, name: str, argv: list[str], destructive: bool):
        policy = classify(name, argv)
        if policy.category not in {"game", "unknown"} and not destructive:
            return policy.category
        request = {"tool": name, "arguments": argv, "category": policy.category,
                   "description": policy.de, "project": str(self.project),
                   "destructive": destructive}
        if self.approval is None:
            raise NativeToolError("approval_required", "Host approval is required for this tool effect", request)
        if self.approval(request) is not True:
            raise NativeToolError("approval_denied", "The requested tool effect was declined", request)
        return policy.category

    def _environment(self) -> dict:
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join((str(self.root / "tools"), str(self.root / "src")))
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env["SPRITESUITE_ASSISTANT_PROJECT"] = str(self.project)
        # ChatGPT/Codex account usage is owned by the conversation host.
        for key in ("OPENAI_API_KEY", "AZURE_OPENAI_API_KEY"):
            env.pop(key, None)
        return env

    @staticmethod
    def _stop(process):
        if process.poll() is not None:
            return
        if os.name == "nt":
            taskkill = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "taskkill.exe"
            subprocess.run([str(taskkill), "/PID", str(process.pid), "/T", "/F"],
                           shell=False, capture_output=True, timeout=10, check=False)
        else:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    def _execute(self, command: list[str], timeout: int) -> dict:
        env = self._environment()
        if self._cancel.is_set():
            raise NativeToolError("cancelled", "Tool call was cancelled before process start")
        if self.runner is not None:
            try:
                completed = self.runner(command, cwd=self.root, env=env, shell=False,
                                        capture_output=True, text=True, errors="replace",
                                        timeout=timeout, check=False)
            except subprocess.TimeoutExpired as error:
                raise NativeToolError("timeout", "Tool exceeded its execution time limit") from error
            def tail(value):
                value = value or ""
                if isinstance(value, bytes):
                    value = value.decode("utf-8", errors="replace")
                return value[-MAX_TEXT:]
            return {"returncode": completed.returncode,
                    "stdout": tail(completed.stdout), "stderr": tail(completed.stderr),
                    "output_truncated": len(completed.stdout or "") > MAX_TEXT or len(completed.stderr or "") > MAX_TEXT}
        scratch = self.root / "work" / ".assistant-runs"
        if any(is_link_or_reparse(path) for path in (scratch, scratch.parent)):
            raise NativeToolError("invalid_arguments", "Linked temporary work directory")
        scratch.mkdir(parents=True, exist_ok=True)
        reason = None
        with tempfile.TemporaryDirectory(prefix="native-", dir=scratch) as folder:
            env["TEMP"] = folder
            env["TMP"] = folder
            out, err = Path(folder) / "stdout", Path(folder) / "stderr"
            with out.open("x+b") as stdout, err.open("x+b") as stderr:
                kwargs = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
                          if os.name == "nt" else {"start_new_session": True})
                process = subprocess.Popen(command, cwd=self.root, env=env, shell=False,
                    stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, **kwargs)
                started = time.monotonic()
                try:
                    while process.poll() is None:
                        if self._cancel.is_set():
                            reason = "cancelled"
                        elif time.monotonic() - started >= timeout:
                            reason = "timeout"
                        elif out.stat().st_size + err.stat().st_size > MAX_CAPTURE:
                            reason = "output_limit"
                        if reason:
                            self._stop(process)
                            break
                        self._cancel.wait(0.05)
                finally:
                    if process.poll() is None:
                        self._stop(process)
                if reason is None and out.stat().st_size + err.stat().st_size > MAX_CAPTURE:
                    reason = "output_limit"
                result = {"returncode": process.returncode,
                          "output_truncated": out.stat().st_size > MAX_TEXT or err.stat().st_size > MAX_TEXT}
                for label, stream in (("stdout", stdout), ("stderr", stderr)):
                    stream.seek(0, os.SEEK_END)
                    size = stream.tell()
                    stream.seek(max(0, size - MAX_TEXT))
                    result[label] = stream.read(MAX_TEXT).decode("utf-8", errors="replace")
        if reason:
            raise NativeToolError(reason, "Tool execution ended: " + reason, result)
        return result

    def _run(self, args: dict) -> dict:
        path = self._tool(args["name"])
        argv = args["arguments"]
        for value in argv:
            if _credential_path(value) or _credential_path(value.split("=", 1)[-1]):
                raise NativeToolError("credential_path", "Credential paths are not tool arguments")
        if "--help" in argv or "-h" in argv:
            return self._describe({"name": path.name})
        category = self._authorize(path.name, argv, args.get("destructive", False))
        result = self._execute([sys.executable, str(path), *argv], args.get("timeout_seconds", 120))
        result.update(tool=path.name, category=category, executed=True, project=str(self.project))
        if result["returncode"]:
            raise NativeToolError("tool_failed", "Local tool returned a failure exit code", result)
        return result

    def _project_op(self, args: dict) -> dict:
        source = str(Path(__file__).resolve().parents[1] / "src")
        if source not in sys.path:
            sys.path.insert(0, source)
        operation = args["operation"]
        def required(name):
            if name not in args:
                raise NativeToolError("invalid_arguments", "Missing operation argument: " + name)
            return args[name]
        if operation == "new":
            from suite_unified_project import new_project, ProjectPipeline
            target = new_project(required("name"))
            pipeline = ProjectPipeline(target)
            pipeline.activate()
            self.project = pipeline.project
            return {"project": str(self.project), "created": True}
        if operation == "open":
            target = _check_path(required("project"))
            if not target.is_dir():
                raise NativeToolError("invalid_arguments", "Open requires an existing project directory")
            old = self.project
            self.project = target
            try:
                pipeline = self._pipeline()
                pipeline.activate()
                self.project = pipeline.project
            except Exception:
                self.project = old
                raise
            return {"project": str(self.project), "opened": True}
        if operation == "restore":
            from hud_menu_project_transfer import restore_archive
            source = _check_path(required("source"))
            with ZipFile(source) as archive:
                for name in archive.namelist():
                    _check_path(name)
            result = restore_archive(source, project_name=args.get("project_name"))
            self.project = Path(result["project"])
            return result
        pipeline = self._pipeline()
        self._safe_assets(pipeline)
        category = args.get("category", "Menüs / UI-Bilder")
        if operation == "create_image":
            output = pipeline.create_image(required("name"), required("width"), required("height"), category=category)
        elif operation == "import_image":
            output = pipeline.import_image(_check_path(required("source")), category=category)
        elif operation == "import_mod_file":
            relative = required("relative_path")
            _check_path(relative)
            output = pipeline.import_mod_file(_check_path(required("source")), relative=relative)
        elif operation == "import_patch":
            output = pipeline.import_patch(_check_path(required("source")), game_document=args.get("game_document"))
        elif operation == "publish_ui_atlas":
            return pipeline.publish_ui_atlas(_check_path(required("atlas_workspace")),
                expected_revision=required("expected_revision"), cancel=self._cancel.is_set)
        elif operation == "inspect":
            return pipeline.inspect_asset(required("relative_path"))
        elif operation == "audit":
            return pipeline.audit()
        elif operation == "build":
            options = {key: args[key] for key in ("author", "version") if key in args}
            if "output" in args:
                options["output"] = _check_path(args["output"])
            return pipeline.build(guid=required("guid"), name=required("name"), **options)
        elif operation == "backup":
            from hud_menu_project_transfer import create_archive
            return create_archive(pipeline.project, _check_path(required("output")))
        else:
            raise NativeToolError("invalid_arguments", "Unknown project operation")
        return {"project": str(pipeline.project), "path": str(output), "sha256": _sha(output),
                "original_game_files_modified": False}

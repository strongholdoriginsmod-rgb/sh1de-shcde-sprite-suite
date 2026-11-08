"""Native assistant connection to the explicitly selected local sprite editor.

The per-process local capability is read internally and never returned to the
model. No account credentials, browser cookies or third-party endpoints are used.
"""
from __future__ import annotations

import ctypes
import base64
import http.client
import json
import os
from pathlib import Path
import socket
from threading import Event, Lock
import time
from urllib.parse import urlsplit
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
MAX_RESPONSE = 32 * 1024**2


def _failure(code, message):
    return {"ok": False, "error": {"code": code, "message": message}}


def _running(pid: int) -> bool:
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ValueError):
            return False
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_bool, ctypes.c_uint32]
    kernel.OpenProcess.restype = ctypes.c_void_p
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    try:
        code = ctypes.c_uint32()
        kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
        return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
    finally:
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel.CloseHandle(handle)


class EditorNativeClient:
    requires_gui_thread = False

    def __init__(self, root=ROOT, *, registry=None, process_check=_running):
        self.root = Path(root)
        self.registry = Path(registry) if registry else self.root / "work" / "session-registry.json"
        self.process_check = process_check
        self._cancel = Event()
        self._lock = Lock()
        self._connection = None
        self._command = None
        self._endpoint = None

    def specs(self):
        return [{"type": "function", "name": "suite_editor",
                 "description": "Use the live sprite editor's native actions, forms, imports, geometry and Undo. First read state/discovery; explicitly activate the intended page if none is selected. Never pick an arbitrary old tab. Execute writes with the editor's current expectedRevision token. File contents use native project.open/files.import request schemas returned by discovery.",
                 "inputSchema": {"type": "object", "properties": {
                     "operation": {"type": "string", "enum": ["state", "activate", "execute"]},
                     "page_id": {"type": "string", "minLength": 1},
                     "request": {"type": "object", "description": "Exact native API request from discovery; includes operation and expectedRevision for writes", "properties": {"operation": {"type": "string"}}, "required": ["operation"], "additionalProperties": True},
                     "files": {"type": "array", "items": {"type": "string"}, "minItems": 1, "description": "Explicit local source paths for project.open/files.import/control.files. The client supplies their bytes internally; do not send image Base64 through the model."},
                     "offset": {"type": "integer", "minimum": 0},
                     "limit": {"type": "integer", "minimum": 1, "maximum": 200},
                     "query": {"type": "string", "description": "Optional frame-ID/name filter for large project snapshots."},
                     "timeout_ms": {"type": "integer", "minimum": 100, "maximum": 30000},
                 }, "required": ["operation"], "additionalProperties": False}}]

    def _session(self):
        path = self.registry.absolute()
        for part in (path, *path.parents):
            if part.is_symlink() or part.is_junction():
                raise ValueError("Linked editor registry")
        if not path.is_file() or not 1 <= path.stat().st_size <= 16384:
            raise ValueError("No local editor session")
        data = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(data, dict) or data.get("schema") != "spritesuite.editor.session.v1"
                or type(data.get("serverPid")) is not int or data["serverPid"] < 1
                or not self.process_check(data["serverPid"])
                or not isinstance(data.get("expiresAt"), (int, float))
                or not time.time() < data["expiresAt"] <= time.time() + 2 * 86400
                or not isinstance(data.get("sessionNonce"), str)
                or not isinstance(data.get("origin"), str)
                or not 20 <= len(data["sessionNonce"]) <= 512):
            raise ValueError("Invalid or expired editor session")
        origin = urlsplit(data.get("origin", ""))
        if (origin.scheme != "http" or origin.hostname != "127.0.0.1"
                or origin.username or origin.password or origin.path not in {"", "/"}
                or origin.query or origin.fragment or not origin.port
                or not 1024 <= origin.port <= 65535):
            raise ValueError("Editor endpoint must be the local application")
        return origin.hostname, origin.port, data["sessionNonce"]

    def _post(self, endpoint, route, body, timeout, *, track=True):
        host, port, nonce = endpoint
        connection = http.client.HTTPConnection(host, port, timeout=timeout)
        if track:
            with self._lock:
                if self._cancel.is_set():
                    connection.close()
                    return _failure("cancelled", "Editorauftrag gestoppt.")
                self._connection = connection
        try:
            encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
            connection.request("POST", route, encoded, {
                "Content-Type": "application/json", "X-SpriteSuite-Desktop-Session": nonce,
                "Accept": "application/json",
            })
            response = connection.getresponse()
            payload = response.read(MAX_RESPONSE + 1)
            if len(payload) > MAX_RESPONSE:
                return _failure("output_limit", "Editorantwort ist zu groß; einen kleineren Ausschnitt wählen.")
            result = json.loads(payload)
            if not isinstance(result, dict) or type(result.get("ok")) is not bool:
                return _failure("invalid_response", "Der Editor hat keine gültige native Antwort geliefert.")
            if not 200 <= response.status < 300 and result["ok"]:
                return _failure("invalid_response", "HTTP-Fehler des Editors darf keinen erfolgreichen Auftrag melden.")
            return result
        finally:
            connection.close()
            if track:
                with self._lock:
                    if self._connection is connection:
                        self._connection = None

    def call(self, name, args):
        command_id = None
        if name != "suite_editor":
            return _failure("unknown_tool", "Unbekanntes Editorwerkzeug.")
        if (not isinstance(args, dict) or set(args) - {"operation", "request", "page_id", "timeout_ms", "files", "offset", "limit", "query"}
                or args.get("operation") not in {"state", "activate", "execute"}):
            return _failure("invalid_arguments", "Native Editoraktion ist ungültig.")
        if self._cancel.is_set():
            return _failure("cancelled", "Editorauftrag gestoppt.")
        timeout_ms = args.get("timeout_ms", 30000)
        if type(timeout_ms) is not int or not 100 <= timeout_ms <= 30000:
            return _failure("invalid_arguments", "Ungültiges Editor-Zeitlimit.")
        operation = args["operation"]
        if operation == "activate" and not isinstance(args.get("page_id"), str):
            return _failure("invalid_arguments", "Den gewünschten Editor-Tab ausdrücklich auswählen.")
        if operation == "execute" and not isinstance(args.get("request"), dict):
            return _failure("invalid_arguments", "Eine native Anfrage aus der Editor-Discovery angeben.")
        offset, limit, query = args.get("offset", 0), args.get("limit", 100), args.get("query", "")
        if (type(offset) is not int or offset < 0 or type(limit) is not int
                or not 1 <= limit <= 200 or not isinstance(query, str) or len(query) > 200):
            return _failure("invalid_arguments", "Ungültiger Projekt-Ausschnitt.")
        request = dict(args.get("request", {}))
        if "files" in args:
            if (operation != "execute" or request.get("operation") not in {"project.open", "files.import", "control.files"}
                    or not isinstance(args["files"], list) or not args["files"]
                    or any(not isinstance(path, str) or not path for path in args["files"])):
                return _failure("invalid_arguments", "Dateipfade benötigen eine native Dateiimport-Aktion.")
            try:
                from suite_native_tools import _check_path
                payloads, total = [], 0
                for source in args["files"]:
                    path = _check_path(source)
                    if path.resolve() == self.registry.resolve() or not path.is_file():
                        raise ValueError("Eine reguläre Grafik-/Projektdatei auswählen.")
                    before = path.stat()
                    total += before.st_size
                    if total > 64 * 1024**2:
                        raise ValueError("Dateiimport überschreitet das native Lesebudget.")
                    with path.open("rb") as stream:
                        data = stream.read(before.st_size + 1)
                    after = path.stat()
                    if len(data) != before.st_size or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                        raise ValueError("Quelldatei während des Lesens verändert.")
                    payloads.append({"name": path.name, "base64": base64.b64encode(data).decode("ascii")})
                request["files"] = payloads
            except (OSError, ValueError) as exc:
                return _failure("invalid_arguments", str(exc))

        def project_page(value):
            if not isinstance(value, dict):
                return value
            result = {}
            for key, item in value.items():
                if key in {"frames", "scenes"} and isinstance(item, list):
                    matched = [row for row in item if not query or query.casefold() in json.dumps(row, ensure_ascii=False).casefold()]
                    result[key] = matched[offset:offset + limit]
                    result[key + "_page"] = {"total": len(item), "matched": len(matched), "offset": offset,
                                              "next_offset": offset + limit if offset + limit < len(matched) else None}
                else:
                    result[key] = project_page(item)
            return result
        try:
            endpoint = self._session()
            if operation in {"state", "activate"}:
                body = {"activatePageId": args["page_id"]} if operation == "activate" else {}
                return project_page(self._post(endpoint, "/native/state", body, 5))
            command_id = uuid4().hex
            with self._lock:
                if self._cancel.is_set():
                    return _failure("cancelled", "Editorauftrag gestoppt.")
                self._command = command_id
                self._endpoint = endpoint
            body = {"request": request, "timeoutMs": timeout_ms, "commandId": command_id}
            if "page_id" in args:
                body["pageId"] = args["page_id"]
            return project_page(self._post(endpoint, "/native/execute", body, timeout_ms / 1000 + 2))
        except (OSError, ValueError, http.client.HTTPException):
            return _failure("cancelled" if self._cancel.is_set() else "not_available",
                            "Editorauftrag gestoppt." if self._cancel.is_set() else
                            "Den lokalen Sprite-Editor öffnen und den gewünschten Tab mit dem Assistenten verbinden.")
        finally:
            with self._lock:
                if command_id is not None and self._command == command_id:
                    self._command = None
                    self._endpoint = None

    def reset_cancel(self):
        self._cancel.clear()

    def cancel(self):
        self._cancel.set()
        with self._lock:
            endpoint, command, connection = self._endpoint, self._command, self._connection
        if endpoint and command:
            try:
                self._post(endpoint, "/native/cancel", {"commandId": command}, 2, track=False)
            except (OSError, ValueError, http.client.HTTPException):
                pass
        if connection is not None:
            try:
                if connection.sock is not None:
                    connection.sock.shutdown(socket.SHUT_RDWR)
                connection.close()
            except OSError:
                pass

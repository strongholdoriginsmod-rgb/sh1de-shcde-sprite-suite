"""Leased, expiring commands for the existing browser editor's native UI API."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
from threading import Event, Lock
import time

LEASE_SECONDS = 30
MAX_SNAPSHOT = 4 * 1024 * 1024


class BrokerError(ValueError):
    def __init__(self, code, message, status=409):
        super().__init__(message)
        self.code, self.status = code, status


@dataclass
class Command:
    page: str
    request: dict
    deadline: float
    deadline_unix: float
    id: str = field(default_factory=lambda: secrets.token_hex(16))
    status: str = "queued"
    result: dict | None = None
    done: Event = field(default_factory=Event)


class NativeBroker:
    def __init__(self):
        self.lock = Lock()
        self.pages = {}
        self.active = None
        self.pending: Command | None = None
        self.finished = {}

    @staticmethod
    def _page_id(value):
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{8,160}", value):
            raise BrokerError("invalid", "Invalid editor page identity.", 400)
        return value

    def _cancel(self, code, message):
        if self.pending:
            self.finished[self.pending.id] = {"status": "canceled", "page": self.pending.page,
                                              "at": time.monotonic()}
            self.pending.result = {"ok": False, "error": {"code": code, "message": message}}
            self.pending.status = "canceled"
            self.pending.done.set()
            self.pending = None

    def _expire(self):
        now = time.monotonic()
        self.finished = {key: value for key, value in self.finished.items() if value["at"] + 300 > now}
        if len(self.finished) > 64:
            self.finished = dict(list(self.finished.items())[-64:])
        if self.pending and self.pending.deadline <= now:
            self._cancel("timeout", "The native editor command expired before completion.")
        if self.active and (self.active not in self.pages or
                self.pages[self.active]["seen"] + LEASE_SECONDS <= now):
            self._cancel("lease_lost", "The selected editor page stopped responding.")
            self.active = None
        self.pages = {key: page for key, page in self.pages.items()
                      if page["seen"] + LEASE_SECONDS > now}

    def _activate(self, page):
        if page not in self.pages:
            raise BrokerError("input_required", "The selected editor page is unavailable.")
        if self.active != page:
            self._cancel("stale", "Another editor page was explicitly selected.")
            self.active = page

    def state(self, body):
        with self.lock:
            self._expire()
            if body.get("activatePageId") is not None:
                self._activate(self._page_id(body["activatePageId"]))
            pages = []
            for page_id, page in self.pages.items():
                state = page["snapshot"]["state"]
                pages.append({"pageId": page_id, "title": page["title"],
                              "active": page_id == self.active,
                              "revision": state.get("revision"), "updatedAt": page["updatedAt"]})
            snapshot = self.pages[self.active]["snapshot"] if self.active else {}
            return {"ok": True, "pages": pages, "activePageId": self.active,
                    "state": snapshot.get("state"), "discovery": snapshot.get("discovery")}

    def poll(self, body):
        page_id = self._page_id(body.get("pageId"))
        snapshot = body.get("snapshot")
        if (not isinstance(snapshot, dict) or not isinstance(snapshot.get("state"), dict)
                or not isinstance(snapshot.get("discovery"), dict)
                or len(json.dumps(snapshot, ensure_ascii=False).encode("utf-8")) > MAX_SNAPSHOT):
            raise BrokerError("invalid", "Invalid or oversized editor snapshot.", 400)
        with self.lock:
            self._expire()
            self.pages[page_id] = {"snapshot": snapshot, "seen": time.monotonic(),
                                   "updatedAt": time.time(), "title": str(body.get("title", "Editor"))[:240]}
            if body.get("activate") is True:
                self._activate(page_id)
            commands = []
            if self.active == page_id and self.pending and self.pending.status == "queued":
                command = self.pending
                command.status = "delivered"
                commands.append({"id": command.id, "request": command.request,
                                 "deadline": command.deadline_unix * 1000})
            canceled = [key for key, record in self.finished.items()
                        if record.get("page") == page_id and record["status"] == "canceled"]
            return {"ok": True, "active": self.active == page_id, "commands": commands,
                    "canceledIds": canceled}

    def result(self, body):
        with self.lock:
            self._expire()
            command = self.pending
            if (not command or command.id != body.get("id") or command.page != body.get("pageId")
                    or self.active != command.page):
                return {"ok": False, "execute": False, "error": {"code": "stale", "message": "Command lease expired."}}
            if body.get("phase") == "started":
                if command.status != "delivered":
                    return {"ok": False, "execute": False}
                command.status = "started"
                return {"ok": True, "execute": True, "deadline": command.deadline_unix * 1000}
            result = body.get("result")
            if command.status != "started" or not isinstance(result, dict) or not isinstance(result.get("ok"), bool):
                raise BrokerError("invalid", "Invalid native command result.", 400)
            command.result = result
            command.status = "completed"
            self.finished[command.id] = {"status": "completed", "page": command.page,
                                          "at": time.monotonic()}
            command.done.set()
            self.pending = None
            snapshot = body.get("snapshot")
            if isinstance(snapshot, dict) and set(snapshot) == {"state", "discovery"}:
                # The regular poll path validates and publishes the next state.
                if all(isinstance(snapshot[k], dict) for k in snapshot) and len(json.dumps(snapshot).encode()) <= MAX_SNAPSHOT:
                    self.pages[command.page]["snapshot"] = snapshot
            return {"ok": True}

    def execute(self, body):
        request = body.get("request")
        timeout = body.get("timeoutMs", 30000)
        if (not isinstance(request, dict) or not isinstance(request.get("operation"), str)
                or isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 50 <= timeout <= 60000):
            raise BrokerError("invalid", "Expected a native request and a 50–60000ms timeout.", 400)
        with self.lock:
            self._expire()
            command_id = body.get("commandId")
            if command_id is not None:
                command_id = self._page_id(command_id)
                if command_id in self.finished:
                    raise BrokerError("canceled" if self.finished[command_id]["status"] == "canceled" else "completed",
                                      "This command identity is already finished.")
            if not self.active:
                raise BrokerError("input_required", "Connect or explicitly select the intended editor tab first.")
            if body.get("pageId", self.active) != self.active:
                raise BrokerError("stale", "The requested editor page is not the active lease.")
            if self.pending:
                raise BrokerError("busy", "A native editor command is already pending.")
            state = self.pages[self.active]["snapshot"]["state"]
            if request.get("operation") != "form.read" and request.get("expectedRevision") != state.get("revision"):
                raise BrokerError("stale", "The editor changed; inspect it again.")
            command = Command(self.active, request, time.monotonic() + timeout / 1000,
                              time.time() + timeout / 1000)
            if command_id:
                command.id = command_id
            self.pending = command
        command.done.wait(timeout / 1000)
        with self.lock:
            self._expire()
            if not command.done.is_set():
                if self.pending is command:
                    self._cancel("timeout", "The native editor command expired.")
                else:
                    command.result = {"ok": False, "error": {"code": "timeout", "message": "Native command expired."}}
            return command.result or {"ok": False, "error": {"code": "timeout", "message": "Native command expired."}}

    def cancel(self, body):
        command_id = self._page_id(body.get("commandId"))
        with self.lock:
            self._expire()
            if command_id in self.finished:
                return {"ok": True, "commandId": command_id,
                        "status": self.finished[command_id]["status"], "rolledBack": False}
            if self.pending and self.pending.id == command_id:
                started = self.pending.status == "started"
                self._cancel("canceled", "The desktop client canceled this native command.")
                return {"ok": True, "commandId": command_id,
                        "status": "cancel_requested" if started else "canceled", "rolledBack": False}
            # A stop may overtake the execute HTTP request. Retain a tombstone.
            self.finished[command_id] = {"status": "canceled", "page": None, "at": time.monotonic()}
            return {"ok": True, "commandId": command_id, "status": "canceled", "rolledBack": False}

    def close(self):
        with self.lock:
            self._cancel("lease_lost", "The editor server closed.")
            self.active = None
            self.pages.clear()


def write_registry(path: Path, *, origin: str, nonce: str) -> dict:
    expires = time.time() + 8 * 60 * 60
    registry = {"schema": "spritesuite.editor.session.v1", "serverPid": os.getpid(),
                "origin": origin, "sessionNonce": nonce,
                "createdUtc": datetime.now(timezone.utc).isoformat(),
                "expiresUtc": datetime.fromtimestamp(expires, timezone.utc).isoformat(), "expiresAt": expires}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + secrets.token_hex(6) + ".tmp")
    try:
        temporary.write_text(json.dumps(registry) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return registry

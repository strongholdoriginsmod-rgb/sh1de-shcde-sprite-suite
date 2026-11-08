"""Protocol tests for the native account assistant, with no remote inference."""
from pathlib import Path
from queue import Queue
from threading import Event
from types import SimpleNamespace
import json

import pytest

from suite_ai_session import AssistantSession, CodexError


class Service:
    project = Path.cwd()

    def __init__(self):
        self.calls = []

    def specs(self):
        return [{"type": "function", "name": "suite_context", "description": "Current project", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}}]

    def call(self, name, arguments):
        self.calls.append((name, arguments))
        return {"ok": True, "result": {"project": "synthetic"}}


def client():
    item = AssistantSession.__new__(AssistantSession)
    item.service = Service()
    item.thread_id = "t"
    item.turn_id = "u"
    item._turn_active = True
    item.cancelled = Event()
    item._calls = {}
    item._call_log = []
    item._completed_text = []
    item.messages = Queue()
    item.pending = []
    item.on_event = lambda _event: None
    item.sent = []
    item.send = item.sent.append
    return item


def params(**updates):
    return {"threadId": "t", "turnId": "u", "callId": "c", "tool": "suite_context", "arguments": {}, **updates}


def test_native_protocol_routes_real_result_and_deduplicates_calls():
    c = client()
    request = {"id": 7, "method": "item/tool/call", "params": params()}
    c.route(request)
    c.route({**request, "id": 8})
    assert c.service.calls == [("suite_context", {})]
    result = c.sent[-1]["result"]
    assert result["success"] is True
    assert result["contentItems"][0]["type"] == "inputText"
    assert json.loads(result["contentItems"][0]["text"])["result"]["project"] == "synthetic"


@pytest.mark.parametrize("update", [{"threadId": "other"}, {"turnId": "old"}, {"arguments": "raw code"}])
def test_mismatched_turn_or_invalid_arguments_never_execute(update):
    c = client()
    assert c._native_call(params(**update))["error"]["code"] == "invalid_call"
    assert not c.service.calls


def test_reused_call_id_cannot_run_a_different_mutation():
    c = client()
    c._native_call(params())
    result = c._native_call(params(arguments={"anything": "different"}))
    assert result["error"]["code"] == "call_id_conflict"
    assert len(c.service.calls) == 1


def test_call_ids_are_scoped_to_a_turn_and_closed_turns_cannot_mutate():
    c = client()
    c._native_call(params())
    c.turn_id = "next"
    c._native_call(params(turnId="next"))
    assert len(c.service.calls) == 2
    c._turn_active = False
    assert c._native_call(params(turnId="next", callId="late"))["error"]["code"] == "invalid_call"
    c._turn_active = True
    c.turn_id = None
    assert c._native_call(params(callId="startup"))["error"]["code"] == "invalid_call"
    assert len(c.service.calls) == 2


def test_cancelled_and_failed_native_calls_are_explicit_errors():
    c = client()
    c.cancelled.set()
    assert c._native_call(params())["error"]["code"] == "cancelled"
    assert not c.service.calls
    c.cancelled.clear()
    c.service.call = lambda *_: (_ for _ in ()).throw(ValueError("synthetic failure"))
    result = c._native_call(params())
    assert result["ok"] is False
    assert result["error"]["code"] == "operation_failed"


@pytest.mark.parametrize("native_ok", [True, False])
def test_large_native_result_is_bounded_before_cache_and_ui_event(native_ok):
    c = client()
    emitted = []
    c.on_event = emitted.append
    c.service.call = lambda *_: {"ok": native_ok, "result": {"data": "x" * 600_000}}
    result = c._native_call(params())
    assert result["error"]["code"] == "output_limit"
    assert result["error"]["native_ok"] is native_ok
    assert "operation_completed" not in result["error"]
    assert len(str(c._calls)) < 2000
    assert len(json.dumps(emitted)) < 2000


@pytest.mark.parametrize("status", ["failed", "interrupted", "inProgress"])
def test_noncompleted_turn_never_reports_success(status):
    c = client()
    c.connected = lambda: True
    c.request = lambda method, *_args, **_kwargs: {"turn": {"id": "u"}}
    c.pending = [{"method": "turn/completed", "params": {"threadId": "t", "turn": {"id": "u", "status": status}}}]
    with pytest.raises(CodexError, match="nicht abgeschlossen"):
        c.run("Explain current project", timeout=1)


def test_success_retains_actual_native_call_log_and_final_message():
    c = client()
    c.connected = lambda: True
    c.request = lambda method, *_args, **_kwargs: {"turn": {"id": "u"}}
    c.pending = [
        {"method": "item/completed", "params": {"threadId": "t", "turnId": "u", "item": {"type": "agentMessage", "text": "Die Projektprüfung ist abgeschlossen."}}},
        {"method": "turn/completed", "params": {"threadId": "t", "turn": {"id": "u", "status": "completed"}}},
    ]
    result = c.run("Inspect", timeout=1)
    assert result["status"] == "completed"
    assert result["message"] == "Die Projektprüfung ist abgeschlossen."


def test_thread_registers_native_tools_and_never_requests_a_shell():
    c = client()
    c.thread_id = None
    c.connected = lambda: True
    calls = []

    def request(method, arguments, **_kwargs):
        calls.append((method, arguments))
        return {"thread": {"id": "t"}} if method == "thread/start" else {"turn": {"id": "u"}}

    c.request = request
    c.pending = [{"method": "turn/completed", "params": {"threadId": "t", "turn": {"id": "u", "status": "completed"}}}]
    c.run("Use native project tools", context="synthetic", timeout=1)
    options = calls[0][1]
    assert options["dynamicTools"] == c.service.specs()
    assert options["sandbox"] == "read-only"
    assert "ONLY the supplied suite_*" in options["developerInstructions"]
    assert not any("apiKey" in str(arguments) for _, arguments in calls)

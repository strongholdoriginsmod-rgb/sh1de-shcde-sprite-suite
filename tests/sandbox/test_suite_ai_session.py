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


def advertised(model="account-model-a", *, default=True, efforts=("small", "deliberate")):
    return dict(id="picker-" + model, model=model, displayName="Account " + model,
                description="From the signed-in account", isDefault=default,
                hidden=False, defaultReasoningEffort=efforts[0],
                supportedReasoningEfforts=[dict(reasoningEffort=value, description=value) for value in efforts])


def runnable_client():
    c = client()
    c.thread_id = None
    c.turn_id = None
    c._turn_active = False
    c.connected = lambda: True
    c.requests = []
    c._models_cache = [advertised(), advertised("account-model-b", default=False, efforts=("balanced", "maximal"))]

    def request(method, arguments, **_kwargs):
        c.requests.append((method, arguments))
        if method == "thread/start":
            return {"thread": {"id": "thread-" + str(sum(name == method for name, _ in c.requests))}}
        if method == "turn/start":
            turn_id = "turn-" + str(sum(name == method for name, _ in c.requests))
            c.pending.append({"method": "turn/completed", "params": {
                "threadId": arguments["threadId"], "turn": {"id": turn_id, "status": "completed"}}})
            return {"turn": {"id": turn_id}}
        raise AssertionError(method)

    c.request = request
    return c


def test_models_explicit_paginated_account_metadata_no_hardcoded_efforts():
    c = client()
    c.connected = lambda: True
    calls = []

    def request(method, arguments):
        calls.append((method, arguments))
        return ({"data": [advertised()], "nextCursor": "page-2"} if "cursor" not in arguments else
                {"data": [advertised("brand-new-account-model", default=False, efforts=("custom-new-effort",))], "nextCursor": None})

    c.request = request
    models = c.models()
    assert [entry["model"] for entry in models] == ["account-model-a", "brand-new-account-model"]
    assert models[1]["supportedReasoningEfforts"][0]["reasoningEffort"] == "custom-new-effort"
    assert calls == [("model/list", {"limit": 100, "includeHidden": False}),
                     ("model/list", {"limit": 100, "includeHidden": False, "cursor": "page-2"})]


@pytest.mark.parametrize("response", [{"data": "bad"}, {"data": [{}]}, {"data": [], "nextCursor": ""}])
def test_invalid_model_list_is_explicit_error(response):
    c = client()
    c.connected = lambda: True
    c.request = lambda *_args: response
    with pytest.raises(CodexError):
        c.models()


def test_repeated_model_cursor_cannot_loop_forever():
    c = client()
    c.connected = lambda: True
    calls = []
    c.request = lambda *args: (calls.append(args) or {"data": [advertised()], "nextCursor": "same"})
    with pytest.raises(CodexError, match="pagination"):
        c.models()
    assert len(calls) == 2


def test_model_and_effort_use_official_turn_fields_and_keep_conversation():
    c = runnable_client()
    c.run("First", model="picker-account-model-a", reasoning_effort="deliberate")
    c.run("Next", model="account-model-b", reasoning_effort="maximal")
    starts = [arguments for method, arguments in c.requests if method == "turn/start"]
    assert [(item["model"], item["effort"]) for item in starts] == [("account-model-a", "deliberate"), ("account-model-b", "maximal")]
    assert starts[0]["threadId"] == starts[1]["threadId"]
    assert len([1 for method, _ in c.requests if method == "thread/start"]) == 1
    assert all("reasoning_effort" not in arguments and "reasoningEffort" not in arguments for _, arguments in c.requests)


def test_standard_options_reset_advertised_defaults_after_custom_override():
    c = runnable_client()
    c.run("Custom", model="account-model-b", reasoning_effort="maximal")
    c.run("Standard", model=None, reasoning_effort=None)
    last = c.requests[-1][1]
    assert last["model"] == "account-model-a" and last["effort"] == "small"


def test_default_start_does_not_discover_models_or_force_a_model():
    c = runnable_client()
    c._models_cache = None
    c.models = lambda **_kwargs: (_ for _ in ()).throw(AssertionError("No automatic model discovery"))
    c.run("Default")
    assert all("model" not in arguments and "effort" not in arguments for _, arguments in c.requests)


@pytest.mark.parametrize("options", [dict(model="not-in-account"), dict(model="account-model-a", reasoning_effort="not-advertised"), dict(model="")])
def test_unavailable_model_or_effort_never_starts_turn(options):
    c = runnable_client()
    with pytest.raises((CodexError, ValueError)):
        c.run("Attempt", **options)
    assert c.requests == []


def test_project_change_restarts_only_with_visible_history_context():
    c = runnable_client()
    c.run("First project")
    first_thread = c.thread_id
    c.service.project = Path("second-project")
    with pytest.raises(ValueError, match="Gesprächskontext"):
        c.run("Changed project")
    assert c.thread_id == first_thread
    c.run("Changed project", history_context="User: retain the prior visible conversation")
    assert c.thread_id != first_thread
    text = c.requests[-1][1]["input"][0]["text"]
    assert "User: retain" in text and "Changed project" in text


def test_tool_capability_key_change_rebinds_with_context():
    c = runnable_client()
    c.service.conversation_key = "questions"
    c.run("Explain")
    old = c.thread_id
    c.service.conversation_key = "programming"
    c.run("Program", history_context="Visible prior context")
    assert c.thread_id != old


def test_prepared_host_stop_is_not_reset_by_run_or_models():
    c = runnable_client()
    c.cancelled.set()
    c.connected = lambda: (_ for _ in ()).throw(AssertionError("Stopped before account request"))
    assert c.run("Stopped", reset_cancel=False)["status"] == "cancelled"
    with pytest.raises(CodexError, match="gestoppt"):
        c.models(reset_cancel=False)
    assert not c.requests


@pytest.mark.parametrize("stop_at", ["connected", "models", "thread/start"])
def test_cancel_during_startup_is_not_lost(stop_at):
    c = runnable_client()
    if stop_at == "connected":
        c.connected = lambda: (c.cancelled.set() or True)
    elif stop_at == "models":
        c._models_cache = None
        c.models = lambda **_kwargs: (c.cancelled.set() or [advertised()])
    else:
        original = c.request

        def request(method, arguments, **kwargs):
            result = original(method, arguments, **kwargs)
            if method == "thread/start":
                c.cancelled.set()
            return result

        c.request = request
    result = c.run("Cancelled startup", model="account-model-a" if stop_at == "models" else None)
    assert result["status"] == "cancelled"
    assert not any(method == "turn/start" for method, _ in c.requests)


def test_previous_turn_replay_ledger_is_evicted_without_weakening_dedup():
    c = runnable_client()
    c._calls[("old", "turn", "call")] = ("hash", {"ok": True, "result": "x" * 500000})
    c.run("New turn")
    assert c._calls == {}


def test_old_turn_text_is_ignored_and_current_text_is_bounded():
    c = client()
    emitted = []
    c.on_event = emitted.append
    c.route({"method": "item/agentMessage/delta", "params": {"threadId": "t", "turnId": "old", "delta": "stale text"}})
    assert emitted == []
    for _ in range(3):
        c.route({"method": "item/agentMessage/delta", "params": {"threadId": "t", "turnId": "u", "delta": "ü" * 200000}})
    assert sum(len(event["text"].encode("utf-8")) for event in emitted) == 512000


def test_oversize_context_is_rejected_before_turn_or_account_access():
    c = runnable_client()
    with pytest.raises(ValueError, match="Größenlimit"):
        c.run("Prompt", history_context="ü" * 100000)
    assert c.requests == []

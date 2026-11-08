"""The native assistant uses only its explicitly selected local editor."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
from threading import Thread
import time

import pytest

from suite_editor_client import EditorNativeClient


@pytest.fixture
def local_editor(tmp_path):
    calls = []
    nonce = "synthetic-local-capability-1234567890"

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            assert self.headers["X-SpriteSuite-Desktop-Session"] == nonce
            data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append((self.path, data))
            if self.path == "/native/state":
                result = {"ok": True, "pages": [{"pageId": "chosen", "active": True}], "activePageId": data.get("activatePageId", "chosen")}
            else:
                result = {"ok": True, "revision": "revision-2", "result": {"history": "native"}}
            encoded = json.dumps(result).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    registry = tmp_path / "work" / "session-registry.json"
    registry.parent.mkdir()
    data = {"schema": "spritesuite.editor.session.v1", "serverPid": os.getpid(),
            "origin": f"http://127.0.0.1:{server.server_port}", "sessionNonce": nonce,
            "expiresAt": time.time() + 300}
    registry.write_text(json.dumps(data), encoding="utf-8")
    try:
        yield EditorNativeClient(tmp_path), registry, calls, data
    finally:
        server.shutdown()
        server.server_close()


def test_explicit_native_state_activation_and_revision_preserving_execute(local_editor):
    client, registry, calls, metadata = local_editor
    assert client.call("suite_editor", {"operation": "state"})["ok"] is True
    assert client.call("suite_editor", {"operation": "activate", "page_id": "chosen"})["activePageId"] == "chosen"
    request = {"operation": "field.set", "fieldId": "pivot-x", "value": 7, "expectedRevision": "revision-1"}
    result = client.call("suite_editor", {"operation": "execute", "page_id": "chosen", "request": request})
    assert result["revision"] == "revision-2"
    assert calls[-1][0] == "/native/execute"
    assert calls[-1][1]["request"] == request
    assert calls[-1][1]["pageId"] == "chosen"
    assert calls[-1][1]["commandId"]
    assert metadata["sessionNonce"] not in json.dumps(result)


@pytest.mark.parametrize("change", [
    {"origin": "https://example.com"}, {"origin": "http://localhost:12345"},
    {"origin": "http://user:pass@127.0.0.1:12345"}, {"origin": "http://127.0.0.1:12345/other"},
    {"expiresAt": 1}, {"serverPid": -1}, {"schema": "other"}, {"sessionNonce": "short"},
])
def test_corrupted_or_nonlocal_registry_never_transmits_capability(local_editor, change):
    client, registry, calls, metadata = local_editor
    registry.write_text(json.dumps({**metadata, **change}), encoding="utf-8")
    assert client.call("suite_editor", {"operation": "state"})["error"]["code"] == "not_available"
    assert calls == []


def test_cancel_and_reset_are_explicit_and_do_not_execute_queued_commands(local_editor):
    client, _, calls, _ = local_editor
    client.cancel()
    assert client.call("suite_editor", {"operation": "state"})["error"]["code"] == "cancelled"
    assert not calls
    client.reset_cancel()
    assert client.call("suite_editor", {"operation": "state"})["ok"] is True


def test_missing_registry_and_invalid_requests_have_structured_errors(tmp_path):
    client = EditorNativeClient(tmp_path)
    assert client.call("suite_editor", {"operation": "state"})["error"]["code"] == "not_available"
    for arguments in [{}, {"operation": "execute"}, {"operation": "activate"}, {"operation": "state", "timeout_ms": True}]:
        assert client.call("suite_editor", arguments)["error"]["code"] == "invalid_arguments"
    assert client.requires_gui_thread is False
    assert client.specs()[0]["type"] == "function"


def test_cancel_during_registry_read_cannot_publish_a_late_command(local_editor):
    client, _, calls, _ = local_editor
    read_session = client._session

    def read_and_cancel():
        endpoint = read_session()
        client.cancel()
        return endpoint

    client._session = read_and_cancel
    result = client.call("suite_editor", {"operation": "execute", "request": {"operation": "inspect"}})
    assert result["error"]["code"] == "cancelled"
    assert calls == []


def test_explicit_file_paths_are_loaded_internally_without_model_base64(local_editor, tmp_path):
    client, _, calls, _ = local_editor
    source = tmp_path / "Eigene Grafik ä.png"
    source.write_bytes(b"synthetic-native-image")
    result = client.call("suite_editor", {"operation": "execute",
        "request": {"operation": "files.import", "expectedRevision": "v1"}, "files": [str(source)]})
    assert result["ok"]
    payload = calls[-1][1]["request"]["files"][0]
    import base64
    assert payload["name"] == source.name
    assert base64.b64decode(payload["base64"]) == source.read_bytes()
    assert payload["base64"] not in json.dumps(result)
    calls.clear()
    denied = client.call("suite_editor", {"operation": "execute",
        "request": {"operation": "files.import"}, "files": [str(client.registry)]})
    assert not denied["ok"] and not calls


def test_large_project_state_is_paged_without_changing_revision_or_sources(tmp_path):
    client = EditorNativeClient(tmp_path)
    client._session = lambda: ("127.0.0.1", 12345, "internal")
    frames = [{"id": f"frame-{i}"} for i in range(250)]
    response = {"ok": True, "revision": "project-revision", "state": {"state": {"frames": frames}}}
    client._post = lambda *_: response
    result = client.call("suite_editor", {"operation": "state", "offset": 200, "limit": 25})
    assert result["revision"] == "project-revision"
    assert result["state"]["state"]["frames"] == frames[200:225]
    assert result["state"]["state"]["frames_page"]["next_offset"] == 225
    assert len(response["state"]["state"]["frames"]) == 250

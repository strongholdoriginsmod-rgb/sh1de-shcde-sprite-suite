"""Native browser leases/cancellation with isolated synthetic snapshots and ports."""
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPConnection
import json
import os
from threading import Thread
import time

import pytest

from sprite_editor_native_broker import BrokerError, NativeBroker
from sprite_editor_local import EditorServer


def page(broker, ident="page-one-fixture", *, activate=False, revision="rev-1"):
    return broker.poll({"pageId": ident, "title": "Synthetic editor",
        "activate": activate, "snapshot": {"state": {"revision": revision}, "discovery": {"actions": []}}})


def request(broker, **kwargs):
    return broker.execute({"request": {"operation": "view.set", "viewId": "sprite",
                                        "expectedRevision": "rev-1"}, "timeoutMs": 2000, **kwargs})


def delivered(broker):
    for _ in range(200):
        result = page(broker)
        if result["commands"]:
            return result["commands"][0]
        time.sleep(.005)
    raise AssertionError("No queued native command")


def test_heartbeat_does_not_choose_a_tab_and_explicit_lease_survives_chat_focus():
    broker = NativeBroker()
    page(broker)
    assert broker.state({})["activePageId"] is None
    with pytest.raises(BrokerError, match="select"):
        request(broker)
    broker.state({"activatePageId": "page-one-fixture"})
    page(broker, "page-two-fixture")
    page(broker)
    assert broker.state({})["activePageId"] == "page-one-fixture"


def test_native_roundtrip_requires_start_ack_and_updates_snapshot():
    broker = NativeBroker()
    page(broker, activate=True)
    with ThreadPoolExecutor(1) as pool:
        pending = pool.submit(request, broker, commandId="desktop-command-fixture")
        command = delivered(broker)
        assert command["id"] == "desktop-command-fixture"
        with pytest.raises(BrokerError, match="result"):
            broker.result({"pageId": "page-one-fixture", "id": command["id"], "result": {"ok": True}})
        assert broker.result({"pageId": "page-one-fixture", "id": command["id"], "phase": "started"})["execute"]
        result = {"ok": True, "revision": "rev-2", "result": {"view": "sprite"}}
        broker.result({"pageId": "page-one-fixture", "id": command["id"], "result": result,
                       "snapshot": {"state": {"revision": "rev-2"}, "discovery": {}}})
        assert pending.result(1) == result
    assert broker.state({})["state"]["revision"] == "rev-2"
    assert broker.cancel({"commandId": command["id"]}) == {
        "ok": True, "commandId": command["id"], "status": "completed", "rolledBack": False}


def test_timed_out_queued_command_can_never_be_delivered_later():
    broker = NativeBroker()
    page(broker, activate=True)
    result = request(broker, timeoutMs=50, commandId="expired-command-fixture")
    assert result["error"]["code"] == "timeout"
    assert page(broker)["commands"] == []
    assert not broker.result({"id": "expired-command-fixture", "pageId": "page-one-fixture", "phase": "started"})["execute"]


@pytest.mark.parametrize("deliver", [False, True])
def test_desktop_stop_cancels_before_browser_claim(deliver):
    broker = NativeBroker()
    page(broker, activate=True)
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(request, broker, commandId="cancel-command-fixture")
        for _ in range(200):
            if broker.pending:
                break
            time.sleep(.005)
        if deliver:
            assert delivered(broker)
        assert broker.cancel({"commandId": "cancel-command-fixture"})["status"] == "canceled"
        assert future.result(1)["error"]["code"] == "canceled"
    assert page(broker)["commands"] == []
    assert not broker.result({"id": "cancel-command-fixture", "pageId": "page-one-fixture", "phase": "started"})["execute"]


def test_stop_overtaking_execute_is_remembered():
    broker = NativeBroker()
    page(broker, activate=True)
    broker.cancel({"commandId": "overtaken-command-fixture"})
    with pytest.raises(BrokerError) as failure:
        request(broker, commandId="overtaken-command-fixture")
    assert failure.value.code == "canceled"
    assert page(broker)["commands"] == []


def test_switching_selected_tab_cancels_old_commands_without_rebinding():
    broker = NativeBroker()
    page(broker, activate=True)
    page(broker, "page-two-fixture")
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(request, broker)
        old = delivered(broker)
        broker.state({"activatePageId": "page-two-fixture"})
        assert future.result(1)["error"]["code"] == "stale"
    assert not broker.result({"id": old["id"], "pageId": "page-one-fixture", "phase": "started"})["execute"]
    assert page(broker)["active"] is False
    assert broker.state({})["activePageId"] == "page-two-fixture"


def test_expired_page_lease_never_falls_back_to_another_old_tab():
    broker = NativeBroker()
    page(broker, activate=True)
    page(broker, "page-two-fixture")
    broker.pages["page-one-fixture"]["seen"] -= 40
    assert broker.state({})["activePageId"] is None


def test_http_roles_origin_registry_and_nonce_redaction(tmp_path):
    registry = tmp_path / "work/session-registry.json"
    with EditorServer(port=0, registry_path=registry) as server:
        record = json.loads(registry.read_text("utf-8"))
        assert record["schema"] == "spritesuite.editor.session.v1"
        assert record["serverPid"] == os.getpid()
        assert record["origin"] == server.origin
        assert record["expiresAt"] > time.time()
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        def post(route, body, headers):
            connection = HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            connection.request("POST", route, json.dumps(body), {"Content-Type": "application/json", **headers})
            response = connection.getresponse()
            status, value = response.status, json.loads(response.read())
            connection.close()
            return status, value
        try:
            desktop = {"X-SpriteSuite-Desktop-Session": server.desktop_nonce}
            browser = {"X-SpriteSuite-Session": server.token, "Origin": server.origin}
            assert post("/native/state", {}, desktop)[0] == 200
            assert post("/native/state", {}, browser)[0] == 403
            assert post("/native/poll", {}, desktop)[0] == 403
            assert post("/native/state", {}, {**desktop, "Origin": "https://untrusted.invalid"})[0] == 403
            assert post("/native/state", {}, {**desktop, "Host": "untrusted.invalid"})[0] == 403
            response = post("/native/state", {}, desktop)[1]
            assert server.desktop_nonce not in json.dumps(response)
            assert server.token not in json.dumps(response)
            assert post("/native/cancel", {"commandId": "http-cancel-fixture"}, desktop)[1]["status"] == "canceled"
        finally:
            server.shutdown()
            worker.join(3)
    assert not registry.exists()


def test_bound_port_retains_existing_oserror_fallback_contract():
    with EditorServer(port=0) as occupied:
        with pytest.raises(OSError):
            EditorServer(port=occupied.server_port)

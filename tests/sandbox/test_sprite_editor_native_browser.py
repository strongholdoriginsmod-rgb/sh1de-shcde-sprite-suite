"""Real desktop client -> leased loopback -> built native browser editor."""
from concurrent.futures import ThreadPoolExecutor
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
from threading import Thread
import time

import pytest

from sprite_editor_local import EditorServer
from suite_editor_client import EditorNativeClient

ROOT = Path(__file__).resolve().parents[2]


def until(predicate, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(.05)
    raise AssertionError("Isolated native browser condition timed out")


@pytest.mark.skipif(os.environ.get("SPRITESUITE_RUN_NATIVE_BROWSER") != "1",
                    reason="Set SPRITESUITE_RUN_NATIVE_BROWSER=1 for the isolated real Edge/native-client flow.")
def test_real_editor_client_browser_import_history_and_queued_stop(tmp_path):
    assert shutil.which("node"), "Node with its standard WebSocket client is required"
    registry = tmp_path / "work/session-registry.json"
    (tmp_path / "downloads").mkdir()
    with EditorServer(port=0, registry_path=registry) as server:
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        environment = dict(os.environ, SPRITESUITE_NATIVE_TEST_AREA=str(tmp_path),
                           SPRITESUITE_NATIVE_TEST_ORIGIN=server.origin)
        renderer = subprocess.Popen(["node", str(ROOT / "extras/sprite-editor/tests/native_broker_browser_fixture.cjs")],
            env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        client = EditorNativeClient(root=tmp_path, registry=registry)
        state = lambda: client.call("suite_editor", {"operation": "state"})
        def execute(operation, **fields):
            current = state()
            return client.call("suite_editor", {"operation": "execute", "timeout_ms": 10000,
                "request": {"operation": operation, "expectedRevision": current["state"]["revision"], **fields}})
        def pause(value):
            (tmp_path / "renderer-control.json").write_text(json.dumps({"pause": value}), encoding="utf-8")
            def acknowledged():
                try:
                    return json.loads((tmp_path / "renderer-status.json").read_text())["paused"] is value
                except (OSError, ValueError):
                    return False
            until(acknowledged)
        try:
            pages = until(lambda: state().get("pages"))
            assert len(pages) == 1
            assert state()["activePageId"] is None
            page_id = pages[0]["pageId"]
            assert client.call("suite_editor", {"operation": "activate", "page_id": page_id})["ok"]
            assert state()["state"]["state"]["frames"] == []
            assert execute("action.invoke", actionId="demo")["ok"]
            assert len(state()["state"]["state"]["frames"]) == 25
            assert execute("view.set", viewId="sprite")["ok"]
            before = state()["state"]
            field = next(c for c in before["controls"] if c["label"] == "Versatz X · px")
            assert execute("field.set", fieldId=field["id"], value=field["value"] + 9)["ok"]
            assert execute("action.invoke", actionId="undo")["ok"]
            after = state()["state"]
            assert next(c for c in after["controls"] if c["label"] == field["label"])["value"] == field["value"]
            assert execute("action.invoke", actionId="save")["ok"]
            saved = until(lambda: next((tmp_path / "downloads").glob("*.shsprite"), None))
            payload = base64.b64encode(saved.read_bytes()).decode("ascii")
            assert execute("project.open", files=[{"name": saved.name, "base64": payload}])["ok"]
            source = ROOT / "extras/sprite-editor/tests/fixtures/c6_d8_i0.png"
            png_before = source.read_bytes()
            assert execute("files.import", files=[{"name": "native-synthetic.png",
                "base64": base64.b64encode(png_before).decode("ascii")}])["ok"]
            assert execute("form.submit", formId="modal-form")["ok"]
            assert len(state()["state"]["state"]["frames"]) == 26
            assert execute("action.invoke", actionId="undo")["ok"]
            assert len(state()["state"]["state"]["frames"]) == 25
            assert source.read_bytes() == png_before
            preserved = state()["state"]["state"]
            pause(True)
            with ThreadPoolExecutor(1) as pool:
                pending = pool.submit(execute, "action.invoke", actionId="delete")
                until(lambda: server.native.pending is not None)
                assert server.native.pending.status == "queued"
                client.cancel()
                assert pending.result(5)["ok"] is False
            client.reset_cancel()
            pause(False)
            time.sleep(1)
            assert state()["state"]["state"] == preserved
            assert server.native.pending is None
            assert server.desktop_nonce not in json.dumps(state())
            assert server.token not in json.dumps(state())
            (tmp_path / "native-client-browser-proof.json").write_text(json.dumps({
                "passed": True, "checks": ["explicit page lease", "real client native view and field",
                "existing Undo", "native save/open project", "provided PNG import and Undo",
                "desktop Stop cancels queued delete", "renderer resume leaves source unchanged", "nonce redaction"],
                "source": "built-in synthetic demo and synthetic PNG fixture", "frameCount": 25,
            }, indent=2), encoding="utf-8")
        finally:
            (tmp_path / "renderer-control.json").write_text('{"stop":true}', encoding="utf-8")
            try:
                stdout, stderr = renderer.communicate(timeout=15)
            except subprocess.TimeoutExpired:
                renderer.kill()
                stdout, stderr = renderer.communicate(timeout=5)
            server.shutdown()
            worker.join(3)
            assert renderer.returncode == 0, (stdout + stderr).decode("utf-8", "replace")

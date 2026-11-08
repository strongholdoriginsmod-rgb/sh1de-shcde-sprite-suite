"""Offscreen native Qt callbacks, state tokens, dialogs and real scene history."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import threading

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "src")]
Qt = pytest.importorskip("PySide6")
from PySide6 import QtCore as C, QtGui as G, QtWidgets as W
from suite_native_qt import NativeQtTools


@pytest.fixture(scope="module")
def app():
    return W.QApplication.instance() or W.QApplication([])


@pytest.fixture
def window(app):
    root = W.QMainWindow()
    root.setWindowTitle("Synthetic native callback QA")
    body = W.QWidget(root)
    root.setCentralWidget(body)
    layout = W.QVBoxLayout(body)
    root.entry = W.QLineEdit("Initial", body)
    root.entry.setObjectName("creator_name")
    root.combo = W.QComboBox(body)
    root.combo.setObjectName("material")
    root.combo.addItems(["Stone", "Holz äöü"])
    root.spin = W.QDoubleSpinBox(body)
    root.spin.setObjectName("pivot_x")
    root.spin.setRange(-500, 500)
    root.check = W.QCheckBox("Mask enabled", body)
    root.check.setObjectName("mask_enabled")
    root.label = W.QLabel("0", body)
    root.button = W.QPushButton("Create synthetic object", body)
    root.button.setObjectName("create_object")
    root.action = G.QAction("Zoom image", root)
    root.action.setObjectName("zoom_image")
    root.count = 0
    def count():
        root.count += 1
        root.label.setText(str(root.count))
    root.button.clicked.connect(count)
    root.action.triggered.connect(count)
    root.entry.editingFinished.connect(lambda: root.label.setText(root.entry.text()))
    for widget in (root.entry, root.combo, root.spin, root.check, root.label, root.button):
        layout.addWidget(widget)
    root.resize(650, 430)
    root.show()
    app.processEvents()
    yield root
    root.close()
    root.deleteLater()
    app.processEvents()


def must(result):
    assert result["ok"], result
    return result["result"]


def snapshot(adapter):
    return must(adapter.call("suite_sandbox", {"operation": "snapshot", "limit": 500}))


def control(state, name):
    return next(row for row in state["items"] if row["object_name"] == name)


def write(adapter, operation, object_name=None, **kwargs):
    state = snapshot(adapter)
    args = {"operation": operation, "token": state["token"], **kwargs}
    if object_name is not None:
        args["id"] = control(state, object_name)["id"]
    return adapter.call("suite_sandbox", args)


def test_missing_provider_window_never_creates_a_qt_application():
    original = W.QApplication.instance()
    adapter = NativeQtTools(lambda: None)
    result = must(adapter.call("suite_sandbox", {"operation": "snapshot"}))
    assert result["code"] == "not_available" and not result["available"]
    assert W.QApplication.instance() is original
    spec = adapter.specs()[0]
    assert spec["type"] == "function" and spec["name"] == "suite_sandbox"
    json.dumps(spec)


def test_snapshots_have_stable_ids_fields_selection_and_tokens(window):
    adapter = NativeQtTools(lambda: window)
    state = snapshot(adapter)
    assert state["token"] == snapshot(adapter)["token"]
    assert len({row["id"] for row in state["items"]}) == len(state["items"])
    entry = control(state, "creator_name")
    assert entry["text"] == "Initial" and entry["enabled"] and entry["visible"]
    assert control(state, "material")["options"] == ["Stone", "Holz äöü"]
    assert control(state, "pivot_x")["number"] == 0
    page = must(adapter.call("suite_sandbox", {"operation": "snapshot", "limit": 1}))
    assert page["next_offset"] == 1 and page["token"] == state["token"]


def test_buttons_actions_fields_and_selection_call_actual_native_callbacks(window):
    adapter = NativeQtTools(lambda: window)
    must(write(adapter, "activate", "create_object"))
    assert window.count == 1
    must(write(adapter, "activate", "zoom_image"))
    assert window.count == 2
    must(write(adapter, "set_text", "creator_name", text="Creator äöü"))
    assert window.label.text() == "Creator äöü"  # editingFinished callback ran.
    must(write(adapter, "select", "material", value="Holz äöü"))
    assert window.combo.currentIndex() == 1
    window.combo.setEditable(True)
    must(write(adapter, "select", "material", value="Creator custom material"))
    assert window.combo.currentText() == "Creator custom material"
    must(write(adapter, "set_number", "pivot_x", number=-14.5))
    assert window.spin.value() == -14.5
    must(write(adapter, "set_checked", "mask_enabled", checked=True))
    assert window.check.isChecked()


def test_stale_writes_unknown_ids_disabled_and_untyped_methods_are_rejected(window):
    adapter = NativeQtTools(lambda: window)
    state = snapshot(adapter)
    widget = control(state, "creator_name")
    window.entry.setText("User changed this")
    result = adapter.call("suite_sandbox", {"operation": "set_text", "id": widget["id"],
        "token": state["token"], "text": "must not win"})
    assert result["error"]["code"] == "stale_state" and window.entry.text() == "User changed this"
    assert adapter.call("suite_sandbox", {"operation": "eval", "text": "print(1)"})["error"]["code"] == "invalid_arguments"
    assert adapter.call("suite_sandbox", {"operation": "activate", "token": snapshot(adapter)["token"], "id": "qt:missing"})["error"]["code"] == "unknown_control"
    window.button.setEnabled(False)
    assert write(adapter, "activate", "create_object")["error"]["code"] == "disabled_control"
    assert adapter.call("suite_sandbox", {"operation": "set_text", "id": widget["id"], "text": "missing-token"})["error"]["code"] == "invalid_arguments"


def test_password_fields_are_omitted_and_not_remote_editable(window):
    window.entry.setEchoMode(W.QLineEdit.EchoMode.Password)
    window.entry.setText("synthetic-secret")
    adapter = NativeQtTools(lambda: window)
    state = snapshot(adapter)
    assert "synthetic-secret" not in json.dumps(state)
    assert control(state, "creator_name")["private"] is True
    assert write(adapter, "set_text", "creator_name", text="replacement")["error"]["code"] == "unsupported_operation"


@pytest.mark.parametrize("kind", ["file", "message", "input", "modal"])
def test_dialogs_return_input_required_and_scoped_interceptors_restore(window, kind):
    button = W.QPushButton("Request input", window)
    button.setObjectName("request_input")
    originals = (W.QFileDialog.getOpenFileName, W.QMessageBox.question, W.QDialog.exec)
    callback = {
        "file": lambda: W.QFileDialog.getOpenFileName(window, "Choose source"),
        "message": lambda: W.QMessageBox.question(window, "Proceed?", "Needs confirmation"),
        "input": lambda: W.QInputDialog.getText(window, "Creator", "Name"),
        "modal": lambda: W.QDialog(window).exec(),
    }[kind]
    button.clicked.connect(callback)
    adapter = NativeQtTools(lambda: window)
    result = write(adapter, "activate", "request_input")
    assert result["error"]["code"] == "input_required", result
    assert result["error"]["details"]["dialogs"]
    assert (W.QFileDialog.getOpenFileName, W.QMessageBox.question, W.QDialog.exec) == originals


def test_callback_errors_are_structured_without_exception_text_or_hook_leak(window):
    def fail():
        raise RuntimeError("secret callback exception")
    window.button.clicked.connect(fail)
    previous = sys.excepthook
    result = write(NativeQtTools(lambda: window), "activate", "create_object")
    assert result["error"]["code"] == "callback_failed"
    assert "secret callback" not in json.dumps(result)
    assert sys.excepthook is previous


def test_host_must_dispatch_on_actual_gui_thread(window):
    adapter = NativeQtTools(lambda: window)
    results = []
    thread = threading.Thread(target=lambda: results.append(adapter.call("suite_sandbox", {"operation": "snapshot"})))
    thread.start()
    thread.join(timeout=5)
    assert results[0]["error"]["code"] == "wrong_thread"


def test_native_overlay_history_changes_invalidate_state_token(window):
    from types import SimpleNamespace
    from stronghold_europe_de.sandbox.native_overlay import OverlayHistory, NativeOverlay
    window.native_canvas = SimpleNamespace(history=OverlayHistory(NativeOverlay("synthetic.map", "0" * 64)))
    adapter = NativeQtTools(lambda: window)
    state = snapshot(adapter)
    window.native_canvas.history.place("synthetic_custom", 0, 400, 400)
    current = snapshot(adapter)
    assert current["native_overlay"]["objects"] == 1
    assert current["native_overlay"]["can_undo"] and current["token"] != state["token"]
    result = adapter.call("suite_sandbox", {"operation": "activate", "token": state["token"],
                         "id": control(state, "create_object")["id"]})
    assert result["error"]["code"] == "stale_state" and window.count == 0


def test_real_sandbox_scene_load_save_undo_redo_and_zoom_use_same_model(app, tmp_path, monkeypatch):
    from stronghold_europe_de.sandbox.scene_model import EditableScene, save_scene, load_scene
    import sandbox_studio
    monkeypatch.setattr(sandbox_studio, "ROOT", tmp_path)
    root = sandbox_studio.SandboxStudio(tmp_path)
    root.native_canvas._poll.stop()
    root.board._asset_poll.stop()
    root.asset_preview.timer.stop()
    source = tmp_path / "synthetic-original.json"
    save_scene(source, EditableScene(width=5, height=5))
    before = source.read_bytes()
    adapter = NativeQtTools(lambda: root)
    try:
        must(write(adapter, "scene_load", path=str(source)))
        assert root.tabs.currentIndex() == 1
        before_place = snapshot(adapter)
        placed = must(write(adapter, "scene_place", group="synthetic_custom_group", frame=0, x=2, y=3))
        ident = placed["return_value"]["object_id"]
        assert placed["return_value"]["asset_id"].startswith("synthetic_custom_group")
        state = snapshot(adapter)
        assert state["scene"]["objects"] == 1 and state["scene"]["can_undo"]
        assert state["scene"]["placements"][0]["id"] == ident
        refused = adapter.call("suite_sandbox", {"operation": "scene_move", "token": before_place["token"],
                               "object_id": ident, "x": 4, "y": 3})
        assert refused["error"]["code"] == "stale_state"
        must(write(adapter, "scene_move", object_id=ident, x=4, y=3))
        assert root.board.history.scene.objects[0].x == 4
        must(write(adapter, "scene_select", object_id=ident))
        assert root.board.selected_id() == ident
        must(write(adapter, "scene_delete", object_id=ident))
        assert root.board.history.scene.objects == []
        must(write(adapter, "undo"))
        assert root.board.history.scene.objects[0].id == ident
        assert root.board.history.scene.objects[0].x == 4
        must(write(adapter, "redo"))
        assert root.board.history.scene.objects == []
        must(write(adapter, "undo"))
        assert len(root.board.history.scene.objects) == 1
        old = root.board.transform().m11()
        result = must(write(adapter, "zoom", number=1.2))
        assert root.board.transform().m11() > old and result["changed"]
        output = tmp_path / "saved-scene.json"
        must(write(adapter, "scene_save", path=str(output)))
        assert load_scene(output).serialize() == root.board.history.scene.serialize()
        assert source.read_bytes() == before
        assert write(adapter, "scene_save", path=str(source))["error"]["code"] == "existing_output"
    finally:
        root._saved_scene = root.board.history.scene.serialize()
        root.close()
        root.deleteLater()
        app.processEvents()


@pytest.mark.parametrize("changes", [{"frame": True}, {"frame": -1}, {"x": 1.5},
    {"x": True}, {"x": -1}, {"group": "../../outside"}, {"team": "not-a-team"}])
def test_scene_place_types_and_refs_are_validated_without_modifying_model(app, changes):
    from sandbox_test_board import SpriteTestBoard
    root = W.QMainWindow()
    root.board = SpriteTestBoard(root)
    root.board._asset_poll.stop()
    root.setCentralWidget(root.board)
    adapter = NativeQtTools(lambda: root)
    before = root.board.history.scene.serialize()
    try:
        args = {"group": "synthetic_group", "frame": 0, "x": 1, "y": 1, **changes}
        result = write(adapter, "scene_place", **args)
        assert result["error"]["code"] == "invalid_arguments"
        assert root.board.history.scene.serialize() == before
        assert not root.board.history.can_undo
    finally:
        root.close()
        root.deleteLater()
        app.processEvents()

"""Bound native Qt controls for an existing embedded Sandbox window.

The conversation host dispatches calls on the widget's GUI thread. No Qt
application, editor, game process or worker thread is created by this module.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import sys

from suite_native_tools import NativeToolError, _check_path, _json_value, _object

OPERATIONS = ("snapshot", "activate", "set_text", "select", "set_checked", "set_number",
              "scene_load", "scene_save", "scene_place", "scene_move", "scene_delete", "scene_select",
              "undo", "redo", "zoom")
SCHEMA = _object({
    "operation": {"type": "string", "enum": list(OPERATIONS)},
    "id": {"type": "string", "description": "Exact qt: ID from the current snapshot."},
    "token": {"type": "string", "description": "Required current snapshot SHA token for every write."},
    "text": {"type": "string"}, "value": {"type": "string"},
    "checked": {"type": "boolean"}, "number": {"type": "number"},
    "index": {"type": "integer", "minimum": 0},
    "column": {"type": "integer", "minimum": 0},
    "path": {"type": "string", "description": "Explicit file for scene_load/scene_save. Uses the existing editor APIs."},
    "object_id": {"type": "string", "description": "Existing placement ID from scene.placements; required for scene_move/delete/select."},
    "group": {"type": "string", "description": "Suite asset-catalog group for scene_place. Creator-owned groups follow the same existing resolver."},
    "frame": {"type": "integer", "minimum": 0, "maximum": 999999},
    "x": {"type": "integer", "minimum": 0}, "y": {"type": "integer", "minimum": 0},
    "team": {"type": "string", "description": "Existing Suite team colour name, default rot."},
    "query": {"type": "string"}, "offset": {"type": "integer", "minimum": 0},
    "limit": {"type": "integer", "minimum": 1, "maximum": 500},
}, ("operation",))


class NativeQtTools:
    requires_gui_thread = True

    def __init__(self, provider):
        self.provider = provider

    def specs(self) -> list[dict]:
        return json.loads(json.dumps([{"type": "function", "name": "suite_sandbox",
            "description": "Operate the existing Qt Sandbox through real controls. Start with snapshot. All writes REQUIRE token; control writes also REQUIRE id. scene_load/save REQUIRE path. Isometric test-scene CRUD uses the real SceneHistory: scene_place REQUIRES group/frame/x/y; scene_move REQUIRES object_id/x/y; scene_delete/select REQUIRE object_id from scene.placements. Native original-map data stays intact. zoom REQUIRES number. Dialogs return input_required. No editor is created.",
            "inputSchema": SCHEMA}]))

    @staticmethod
    def _validate(args):
        if not isinstance(args, dict) or set(args) - set(SCHEMA["properties"]):
            raise NativeToolError("invalid_arguments", "Use the declared suite_sandbox arguments")
        if args.get("operation") not in OPERATIONS:
            raise NativeToolError("invalid_arguments", "Choose a declared Sandbox operation")
        for name, value in args.items():
            definition = SCHEMA["properties"][name]
            kind = definition["type"]
            valid = (isinstance(value, str) if kind == "string" else
                isinstance(value, bool) if kind == "boolean" else
                isinstance(value, int) and not isinstance(value, bool) if kind == "integer" else
                isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value))
            if not valid or (isinstance(value, str) and "\0" in value):
                raise NativeToolError("invalid_arguments", "Invalid Sandbox field: " + name)
            if kind == "integer" and (value < definition.get("minimum", value) or value > definition.get("maximum", value)):
                raise NativeToolError("invalid_arguments", "Sandbox field outside range: " + name)

    def call(self, name: str, args: dict) -> dict:
        try:
            if name != "suite_sandbox":
                raise NativeToolError("unknown_tool", "Unknown Qt native tool")
            self._validate(args)
            window = self.provider()
            if window is None:
                return {"ok": True, "result": {"available": False, "code": "not_available",
                        "message": "Open the embedded Sandbox before using its native controls."}}
            try:
                from PySide6 import QtCore, QtGui, QtWidgets
                from shiboken6 import isValid
            except ImportError:
                return {"ok": True, "result": {"available": False, "code": "not_available"}}
            if not isinstance(window, QtWidgets.QWidget) or not isValid(window):
                return {"ok": True, "result": {"available": False, "code": "not_available"}}
            if QtCore.QThread.currentThread() != window.thread():
                raise NativeToolError("wrong_thread", "The host must dispatch Sandbox operations on its Qt GUI thread")
            snapshot, objects = self._snapshot(window, QtCore, QtGui, QtWidgets)
            if args["operation"] == "snapshot":
                return {"ok": True, "result": self._page(snapshot, args)}
            if not args.get("token"):
                raise NativeToolError("invalid_arguments", "A current snapshot token is required for writes")
            if args["token"] != snapshot["token"]:
                raise NativeToolError("stale_state", "The Sandbox changed after the snapshot. Read it again before writing.",
                                      {"token": snapshot["token"]})
            dialogs = []
            callback_errors = []
            original_hook = sys.excepthook
            try:
                sys.excepthook = lambda kind, value, trace: callback_errors.append({"type": kind.__name__})
                with self._dialogs(QtCore, QtWidgets, dialogs):
                    returned = self._operate(window, objects, args, QtCore, QtGui, QtWidgets)
            finally:
                sys.excepthook = original_hook
            after, _ = self._snapshot(window, QtCore, QtGui, QtWidgets)
            result = {"callback_invoked": True, "changed": after["token"] != snapshot["token"],
                      "return_value": returned, "snapshot": self._page(after, args)}
            if callback_errors:
                raise NativeToolError("callback_failed", "A native Qt callback failed.",
                                      {"callbacks": callback_errors, **result})
            if dialogs:
                raise NativeToolError("input_required", "The native action requested dialog input. Use a typed project/file action or request the missing input.",
                                      {"dialogs": dialogs, **result})
            return {"ok": True, "result": _json_value(result)}
        except NativeToolError as error:
            result = {"code": error.code, "message": str(error)}
            if error.details is not None:
                result["details"] = _json_value(error.details)
            return {"ok": False, "error": result}
        except Exception as error:
            return {"ok": False, "error": {"code": "operation_failed",
                    "message": "Native Qt operation failed. Inspect the current Sandbox state.",
                    "type": type(error).__name__}}

    @staticmethod
    def _page(snapshot: dict, args: dict) -> dict:
        query = args.get("query", "").casefold()
        rows = [row for row in snapshot["items"] if not query or
                query in (row.get("label", "") + " " + row["class"] + " " + row.get("object_name", "")).casefold()]
        offset, limit = args.get("offset", 0), args.get("limit", 150)
        result = {**snapshot, "items": rows[offset:offset + limit], "total": len(rows),
                  "offset": offset, "next_offset": offset + limit if offset + limit < len(rows) else None}
        for name in ("scene", "native_overlay"):
            history = snapshot.get(name)
            if history is not None:
                placements = [row for row in history["placements"] if not query or
                              query in (row["id"] + " " + row["group"]).casefold()]
                result[name] = {**history, "placements": placements[offset:offset + limit],
                    "placement_total": len(placements),
                    "next_offset": offset + limit if offset + limit < len(placements) else None}
        return result

    def _snapshot(self, window, C, G, W):
        rows, objects = [], {}
        def visit(obj, path):
            if isinstance(obj, (W.QWidget, G.QAction)):
                key = "qt:" + hashlib.sha256(path.encode("utf-8")).hexdigest()[:24]
                row = self._item(obj, C, G, W)
                row.update(id=key, object_name=obj.objectName(), **{"class": type(obj).__name__})
                row["parent_id"] = ("qt:" + hashlib.sha256(path.rsplit("/", 1)[0].encode("utf-8")).hexdigest()[:24]
                                    if "/" in path else None)
                rows.append(row)
                objects[key] = obj
            counts = {}
            for child in obj.children():
                name = type(child).__name__ + ":" + child.objectName()
                index = counts.get(name, 0)
                counts[name] = index + 1
                visit(child, path + "/" + name + ":" + str(index))
        visit(window, "root")
        state = {"available": True, "window_title": window.windowTitle(), "items": rows,
                 "scene": self._scene(window), "native_overlay": self._overlay(window),
                 "game_process_started": False}
        # Layout requests can settle between host queue turns. Pixel
        # geometry is useful context, while write freshness follows semantic
        # control values, model history, IDs and real view transforms.
        fingerprint = {**state, "items": [{key: value for key, value in row.items()
                                           if key != "geometry"} for row in rows]}
        state["token"] = hashlib.sha256(json.dumps(fingerprint, sort_keys=True,
                                    ensure_ascii=False).encode("utf-8")).hexdigest()
        return state, objects

    @staticmethod
    def _scene(window):
        # Known editor models only. Expose actual history/selection, never
        # synthesize a game scene or call arbitrary provider methods.
        board = getattr(window, "board", None)
        history = getattr(board, "history", None)
        if history is None:
            return None
        from stronghold_europe_de.sandbox.scene_model import SceneHistory
        if not isinstance(history, SceneHistory):
            return None
        source = history.scene.serialize()
        result = {"sha256": hashlib.sha256(json.dumps(source, sort_keys=True,
                  ensure_ascii=False).encode("utf-8")).hexdigest(),
                  "objects": len(history.scene.objects),
                  "width": history.scene.width, "height": history.scene.height,
                  "placements": [asdict(item) for item in history.scene.objects],
                  "can_undo": history.can_undo, "can_redo": history.can_redo}
        return result

    @staticmethod
    def _overlay(window):
        canvas = getattr(window, "native_canvas", None)
        history = getattr(canvas, "history", None)
        if history is None:
            return None
        from stronghold_europe_de.sandbox.native_overlay import OverlayHistory
        if not isinstance(history, OverlayHistory):
            return None
        source = history.overlay.serialize()
        return {"sha256": hashlib.sha256(json.dumps(source, sort_keys=True,
                    ensure_ascii=False).encode("utf-8")).hexdigest(),
                "source_sha256": history.overlay.source_sha256,
                "objects": len(history.overlay.objects),
                "placements": [asdict(item) for item in history.overlay.objects],
                "can_undo": bool(history.undo_stack), "can_redo": bool(history.redo_stack)}

    @staticmethod
    def _item(obj, C, G, W):
        row = {"enabled": obj.isEnabled(), "visible": obj.isVisible(), "label": "", "operations": []}
        if isinstance(obj, G.QAction):
            row.update(label=obj.text(), operations=["activate"], shortcut=obj.shortcut().toString())
            if obj.isCheckable():
                row.update(checked=obj.isChecked())
                row["operations"].append("set_checked")
        elif isinstance(obj, W.QAbstractButton):
            row.update(label=obj.text(), operations=["activate"])
            if obj.isCheckable():
                row.update(checked=obj.isChecked())
                row["operations"].append("set_checked")
        elif isinstance(obj, W.QLineEdit):
            private = obj.echoMode() != W.QLineEdit.EchoMode.Normal
            row.update(text=None if private else obj.text(), private=private, read_only=obj.isReadOnly())
            if not obj.isReadOnly() and not private:
                row["operations"] = ["set_text"]
        elif isinstance(obj, (W.QTextEdit, W.QPlainTextEdit)):
            row.update(text=obj.toPlainText(), read_only=obj.isReadOnly())
            if not obj.isReadOnly():
                row["operations"] = ["set_text"]
        elif isinstance(obj, W.QComboBox):
            row.update(value=obj.currentText(), index=obj.currentIndex(),
                       options=[obj.itemText(i) for i in range(obj.count())], editable=obj.isEditable(), operations=["select"])
        elif isinstance(obj, W.QTabWidget):
            row.update(index=obj.currentIndex(), options=[obj.tabText(i) for i in range(obj.count())], operations=["select"])
        elif isinstance(obj, (W.QSpinBox, W.QDoubleSpinBox, W.QAbstractSlider)):
            row.update(number=obj.value(), minimum=obj.minimum(), maximum=obj.maximum(), operations=["set_number"])
        elif isinstance(obj, W.QAbstractItemView):
            row.update(selection=[{"row": item.row(), "column": item.column(), "text": str(item.data() or "")}
                                  for item in obj.selectedIndexes()], operations=["select"])
        elif isinstance(obj, W.QGraphicsView):
            transform = obj.transform()
            row["view_transform"] = [transform.m11(), transform.m12(), transform.m21(),
                                     transform.m22(), transform.dx(), transform.dy()]
            row["selection"] = ([{"class": type(item).__name__,
                "object_id": getattr(item, "object_id", None), "x": item.pos().x(), "y": item.pos().y()}
                for item in obj.scene().selectedItems()] if obj.scene() is not None else [])
        elif isinstance(obj, W.QLabel):
            row["label"] = obj.text()
        elif isinstance(obj, W.QGroupBox):
            row["label"] = obj.title()
        if isinstance(obj, W.QWidget):
            row["tooltip"] = obj.toolTip()
            accessible = obj.accessibleName()
            if accessible:
                row["label"] = accessible
            if not row["label"]:
                parent = obj.parentWidget()
                layout = parent.layout() if parent is not None else None
                if isinstance(layout, W.QFormLayout):
                    label = layout.labelForField(obj)
                    if isinstance(label, W.QLabel):
                        row["label"] = label.text()
            bounds = W.QWidget.geometry(obj)
            row["geometry"] = [bounds.x(), bounds.y(), bounds.width(), bounds.height()]
        for key in ("label", "text", "tooltip"):
            text = row.get(key)
            if isinstance(text, str) and len(text) > 8192:
                row[key + "_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
                row[key + "_truncated"] = True
                row[key] = text[:8192]
        return row

    @staticmethod
    @contextmanager
    def _dialogs(C, W, records):
        saved = []
        def replace(owner, name, replacement):
            if hasattr(owner, name):
                saved.append((owner, name, name in owner.__dict__, owner.__dict__.get(name)))
                setattr(owner, name, replacement)
        def request(kind, name, answer):
            def invoke(*args, **kwargs):
                title = kwargs.get("caption", kwargs.get("title", args[1] if len(args) > 1 else ""))
                text = kwargs.get("text", kwargs.get("label", args[2] if len(args) > 2 and kind in {"message", "input"} else ""))
                records.append({"kind": kind, "method": name, "title": str(title), "text": str(text)})
                return answer
            return invoke
        try:
            for name, answer in {
                "getOpenFileName": ("", ""), "getSaveFileName": ("", ""),
                "getOpenFileNames": ([], ""), "getExistingDirectory": "",
                "getOpenFileUrl": (C.QUrl(), ""), "getSaveFileUrl": (C.QUrl(), ""),
                "getExistingDirectoryUrl": C.QUrl(), "getOpenFileUrls": ([], ""),
            }.items():
                replace(W.QFileDialog, name, request("file", name, answer))
            for name in ("question", "warning", "critical", "information", "about", "aboutQt"):
                replace(W.QMessageBox, name, request("message", name, W.QMessageBox.StandardButton.Cancel))
            for name, answer in {"getText": ("", False), "getMultiLineText": ("", False),
                                 "getItem": ("", False), "getInt": (0, False), "getDouble": (0.0, False)}.items():
                replace(W.QInputDialog, name, request("input", name, answer))
            def modal(dialog, *args, **kwargs):
                records.append({"kind": "dialog", "method": "exec", "title": dialog.windowTitle()})
                dialog.reject()
                if isinstance(dialog, W.QMessageBox):
                    return W.QMessageBox.StandardButton.Cancel.value
                return W.QDialog.DialogCode.Rejected
            for owner in (W.QDialog, W.QFileDialog, W.QMessageBox, W.QInputDialog):
                for name in ("exec", "exec_"):
                    replace(owner, name, modal)
            yield
        finally:
            for owner, name, owned, original in reversed(saved):
                if owned:
                    setattr(owner, name, original)
                else:
                    delattr(owner, name)

    def _operate(self, window, objects, args, C, G, W):
        operation = args["operation"]
        def required(name):
            if name not in args:
                raise NativeToolError("invalid_arguments", "Sandbox operation requires " + name)
            return args[name]
        if operation in {"scene_place", "scene_move", "scene_delete", "scene_select"}:
            from sandbox_test_board import SpriteTestBoard
            from stronghold_europe_de.sandbox.scene_model import SceneHistory, SceneError
            board = getattr(window, "board", None)
            if not isinstance(board, SpriteTestBoard) or not isinstance(board.history, SceneHistory):
                raise NativeToolError("unsupported_operation", "A real SpriteTestBoard with SceneHistory is required")
            ident = args.get("object_id")
            if operation != "scene_place" and not any(item.id == required("object_id") for item in board.history.scene.objects):
                raise NativeToolError("unknown_object", "Placement ID is absent from the current test scene")
            try:
                if operation == "scene_place":
                    ident = board.history.place(required("group"), required("frame"),
                                                required("x"), required("y"), team=args.get("team", "rot"))
                elif operation == "scene_move":
                    board.history.move(ident, required("x"), required("y"))
                elif operation == "scene_delete":
                    board.history.delete(ident)
            except SceneError as error:
                raise NativeToolError("invalid_arguments", "The existing scene model rejected the asset reference or tile coordinates.") from error
            board.rebuild(focus_id=ident if operation != "scene_delete" else None)
            if operation == "scene_select":
                # Rebuild selects exactly this existing placement through
                # the editor's own selection signals and inspector bindings.
                board.scene().clearSelection()
                board._items[ident].setSelected(True)
            if callable(getattr(window, "show_test_field", None)):
                window.show_test_field()
            result = {"scene_target": "test_scene", "object_id": ident}
            if operation == "scene_place":
                import asset_katalog
                result["asset_id"] = asset_katalog.native_name(args["group"], args["frame"])
            return result
        if operation in {"scene_load", "scene_save", "undo", "redo", "zoom"}:
            # This is a fixed method allowlist matching SandboxStudio's real
            # public callbacks. Input never becomes a Python attribute name.
            if operation == "scene_load":
                method = getattr(window, "load_test_scene", None)
                if not callable(method):
                    raise NativeToolError("unsupported_operation", "This window has no scene load API")
                source = _check_path(required("path"))
                if not source.is_file():
                    raise NativeToolError("invalid_arguments", "Choose an existing scene file")
                return method(source)
            if operation == "scene_save":
                method = getattr(window, "save_test_scene", None)
                if not callable(method):
                    raise NativeToolError("unsupported_operation", "This window has no scene save API")
                output = _check_path(required("path"))
                if output.exists():
                    raise NativeToolError("existing_output", "Choose a new scene output so an existing source stays intact")
                return method(output)
            if operation == "undo":
                if not callable(getattr(window, "undo_test", None)):
                    raise NativeToolError("unsupported_operation", "This window has no native scene undo API")
                window.undo_test()
                return None
            if operation == "redo":
                if not callable(getattr(window, "redo_test", None)):
                    raise NativeToolError("unsupported_operation", "This window has no native scene redo API")
                window.redo_test()
                return None
            if not callable(getattr(window, "zoom_active", None)):
                raise NativeToolError("unsupported_operation", "This window has no active-view zoom API")
            scale = required("number")
            if scale <= 0:
                raise NativeToolError("invalid_arguments", "Zoom factor must be positive")
            window.zoom_active(scale)
            return None
        obj = objects.get(required("id"))
        if obj is None:
            raise NativeToolError("unknown_control", "Control ID is absent from the current Sandbox")
        row = self._item(obj, C, G, W)
        if not obj.isEnabled():
            raise NativeToolError("disabled_control", "The native control is disabled")
        if operation not in row["operations"]:
            raise NativeToolError("unsupported_operation", "This control does not support that native operation")
        if operation == "activate":
            if isinstance(obj, G.QAction):
                obj.trigger()
            else:
                obj.click()
        elif operation == "set_text":
            value = required("text")
            if isinstance(obj, W.QLineEdit):
                if len(value) > obj.maxLength():
                    raise NativeToolError("invalid_arguments", "Text exceeds this native field's maximum length")
                obj.setText(value)
                obj.editingFinished.emit()
            else:
                obj.setPlainText(value)
        elif operation == "set_checked":
            obj.setChecked(required("checked"))
        elif operation == "set_number":
            value = required("number")
            if not obj.minimum() <= value <= obj.maximum():
                raise NativeToolError("invalid_arguments", "Number is outside the native control range")
            if not isinstance(obj, W.QDoubleSpinBox) and int(value) != value:
                raise NativeToolError("invalid_arguments", "This native control accepts integer values")
            obj.setValue(value if isinstance(obj, W.QDoubleSpinBox) else int(value))
        elif operation == "select":
            index = args.get("index")
            if isinstance(obj, W.QComboBox):
                if "value" in args:
                    index = obj.findText(args["value"], C.Qt.MatchFlag.MatchExactly)
                    if index < 0 and obj.isEditable():
                        obj.setCurrentText(args["value"])
                        return None
                if index is None or not 0 <= index < obj.count():
                    raise NativeToolError("invalid_arguments", "Choose an existing combo value/index")
                obj.setCurrentIndex(index)
            elif isinstance(obj, W.QTabWidget):
                if "value" in args:
                    index = next((i for i in range(obj.count()) if obj.tabText(i) == args["value"]), -1)
                if index is None or not 0 <= index < obj.count() or not obj.isTabEnabled(index):
                    raise NativeToolError("invalid_arguments", "Choose an existing enabled tab")
                obj.setCurrentIndex(index)
            else:
                if index is None:
                    raise NativeToolError("invalid_arguments", "Item selection requires index")
                model = obj.model()
                selected = model.index(index, args.get("column", 0), obj.rootIndex())
                if not selected.isValid():
                    raise NativeToolError("invalid_arguments", "Selection index is outside this view")
                obj.setCurrentIndex(selected)
        return None

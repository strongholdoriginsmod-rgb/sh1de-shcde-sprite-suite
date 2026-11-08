"""Threaded ChatGPT assistant over the Suite's existing project and UI tools."""
from __future__ import annotations

from contextlib import ExitStack
from hashlib import sha256
import json
import math
import os
from pathlib import Path
from queue import Empty, Queue
import re
from threading import Event, Lock, Thread, current_thread
from datetime import datetime, timezone
from uuid import uuid4
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, simpledialog, ttk
from tkinter.scrolledtext import ScrolledText
from unittest.mock import patch

from suite_ai_session import AssistantSession
from suite_native_tools import NativeToolService
from suite_workarea import ScrollableWorkarea
from suite_windows_paths import is_link_or_reparse


class InputRequired(ValueError):
    pass


def failure(code, message, **details):
    return {"ok": False, "error": {"code": code, "message": message, **details}}


def history_text(value, limit=6000):
    """Persist conversation text, never raw account/tool envelopes or common secrets."""
    text = str(value)
    text = re.sub(r"\bsk-[A-Za-z0-9_-]{16,}\b", "[redacted]", text)
    text = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*", "Bearer [redacted]", text)
    text = re.sub(r"(?i)(\b(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|passwort|authorization)\b[\"']?\s*[:=]\s*)(?:\"[^\"]*\"|'[^']*'|\S+)",
                  r"\1[redacted]", text)
    return text[:limit]


class ConversationStore:
    """Bounded local project metadata; remote Codex threads are never resumed."""
    SCHEMA = "spritesuite.assistant-conversation.v1"
    MAX_BYTES = 160000
    MAX_MESSAGES = 80
    MAX_CONVERSATIONS = 20

    def __init__(self, project):
        import hud_menu_workspace as hud
        self.folder = hud._metadata_dir(Path(project)) / "assistant-conversations"

    def _safe(self, path):
        if any(is_link_or_reparse(part) for part in (path, *path.parents)):
            raise ValueError("Verknüpfter Gesprächsverlauf ist nicht zulässig.")
        return path

    def load(self, identifier):
        if not isinstance(identifier, str) or not re.fullmatch(r"[a-f0-9]{32}", identifier):
            raise ValueError("Ungültige Gesprächs-ID.")
        path = self._safe(self.folder / (identifier + ".json"))
        if not path.is_file() or not 1 <= path.stat().st_size <= self.MAX_BYTES:
            raise ValueError("Gespräch fehlt oder überschreitet das Größenlimit.")
        data = json.loads(path.read_text(encoding="utf8"))
        if (not isinstance(data, dict) or data.get("schema") != self.SCHEMA or data.get("id") != identifier or
                not isinstance(data.get("messages"), list) or len(data["messages"]) > self.MAX_MESSAGES):
            raise ValueError("Ungültiger Gesprächsverlauf.")
        for message in data["messages"]:
            if (not isinstance(message, dict) or set(message) != {"role", "text"} or
                    message["role"] not in {"user", "assistant", "tool"} or
                    not isinstance(message["text"], str) or len(message["text"]) > 6000):
                raise ValueError("Ungültiger Gesprächseintrag.")
        return {"schema": self.SCHEMA, "id": identifier, "title": history_text(data.get("title", "Gespräch"), 80),
                "updated": history_text(data.get("updated", ""), 40),
                "messages": [{"role": row["role"], "text": history_text(row["text"])} for row in data["messages"]]}

    def list(self):
        self._safe(self.folder)
        if not self.folder.is_dir():
            return []
        result = []
        for path in sorted(self.folder.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:self.MAX_CONVERSATIONS]:
            try:
                result.append(self.load(path.stem))
            except (ValueError, OSError):
                continue
        return result

    @classmethod
    def new(cls):
        return {"schema": cls.SCHEMA, "id": uuid4().hex, "title": "Neues Gespräch", "updated": "", "messages": []}

    def save(self, conversation):
        self._safe(self.folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        messages = [{"role": message["role"], "text": history_text(message["text"])}
                    for message in conversation["messages"][-self.MAX_MESSAGES:]
                    if message["role"] in {"user", "assistant", "tool"}]
        data = {"schema": self.SCHEMA, "id": conversation["id"], "title": history_text(conversation["title"], 80),
                "updated": datetime.now(timezone.utc).isoformat(), "messages": messages}
        if not re.fullmatch(r"[a-f0-9]{32}", data["id"]):
            raise ValueError("Ungültige Gesprächs-ID.")
        while len((json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf8")) > self.MAX_BYTES and data["messages"]:
            data["messages"].pop(0)
        destination = self._safe(self.folder / (data["id"] + ".json"))
        if not destination.exists() and len(list(self.folder.glob("*.json"))) >= self.MAX_CONVERSATIONS:
            raise ValueError("Maximal 20 lokale Gespräche pro Projekt. Bitte ein vorhandenes Gespräch auswählen.")
        temporary = self._safe(self.folder / (".conversation-" + uuid4().hex + ".tmp"))
        try:
            with temporary.open("x", encoding="utf8", newline="\n") as stream:
                json.dump(data, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            # Byte limit includes whitespace in the published representation.
            if temporary.stat().st_size > self.MAX_BYTES:
                raise ValueError("Gespräch überschreitet das Speicherlimit.")
            self._safe(destination)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        return data


UI_SPEC = {
    "type": "function", "name": "suite_ui",
    "description": "Read native Tk controls and menus, invoke callbacks, set text/selections/numbers, or focus. Text set replaces the entire content with one native Undo step. Never treat a truncated snapshot prefix as the complete text. Confirm a full replacement with replace_full_text=true when the current text is truncated. Gesture sends one bounded visible-canvas press/move/release through existing callbacks and Undo. Read canvas model and image hashes first. Mutations need the current snapshot token. Completed changes remain after cancellation. Prefer typed project tools for file operations.",
    "inputSchema": {
        "type": "object", "additionalProperties": False,
        "properties": {
            "operation": {"type": "string", "enum": ["snapshot", "invoke", "set", "focus", "gesture"]},
            "widget_id": {"type": "string"}, "expected_state": {"type": "string"},
            "query": {"type":"string", "maxLength":200},
            "value": {"type": ["string", "number", "boolean", "array", "null"]},
            "replace_full_text": {"type": "boolean"},
            "points": {"type": "array", "minItems": 1, "maxItems": 128,
                       "items": {"type": "array", "minItems": 2, "maxItems": 2,
                                 "items": {"type": "number"}}},
            "modifiers": {"type": "array", "maxItems": 2, "uniqueItems": True,
                          "items": {"type": "string", "enum": ["shift", "control"]}},
            "offset": {"type": "integer", "minimum": 0},
            "limit": {"type": "integer", "minimum": 1, "maximum": 500},
        }, "required": ["operation"],
    },
}


class GuiToolService:
    """Route Tk/Qt work to the UI thread and keep the native project in sync."""

    def __init__(self, app, delegate, dispatch, *, excluded=None, extra_delegates=()):
        self.app, self.delegate, self.dispatch = app, delegate, dispatch
        self.excluded = excluded
        self.extra_delegates = tuple(extra_delegates)
        self._ui_cancel = Event()
        self.mode = "tasks"
        self.code_run_enabled = True

    @property
    def conversation_key(self):
        return (self.mode, self.code_run_enabled)

    def configure_mode(self, mode, execution_enabled=True):
        if mode not in {"questions", "tasks", "code"}:
            raise ValueError("Unbekannter Arbeitsmodus.")
        self.mode, self.code_run_enabled = mode, bool(execution_enabled and mode != "questions")

    def add_delegate(self, service):
        existing = {spec["name"] for spec in self.specs()}
        names = {spec["name"] for spec in service.specs()}
        if names & existing:
            return False
        self.extra_delegates = (*self.extra_delegates, service)
        return True

    def _mode_allows(self, name, args):
        operation = args.get("operation")
        if name == "suite_code":
            if operation in {"list", "read"}:
                return True
            return self.mode != "questions" and (operation != "run" or self.code_run_enabled)
        if self.mode != "questions":
            return True
        if name in {"suite_context", "suite_tool_catalog", "suite_tool_describe"}:
            return True
        if name == "suite_tool_run":
            # NativeToolService renders help statically without running Python.
            # A broad CLI policy label cannot prove every argparse spelling safe.
            return args.get("arguments") in (["--help"], ["-h"]) and not args.get("destructive")
        return operation in {"suite_ui": {"snapshot"}, "suite_sandbox": {"snapshot"},
                             "suite_editor": {"state"}, "suite_project_op": {"inspect", "audit"}}.get(name, set())

    @property
    def project(self):
        return self.delegate.project

    def specs(self):
        result = self.delegate.specs() + [json.loads(json.dumps(UI_SPEC))]
        for service in self.extra_delegates:
            result.extend(service.specs())
        return result

    def cancel(self):
        self._ui_cancel.set()
        self.delegate.cancel()
        for service in self.extra_delegates:
            cancel = getattr(service, "cancel", None)
            if callable(cancel):
                if getattr(service,"requires_gui_thread",True):
                    cancel()
                else:
                    Thread(target=cancel,daemon=True).start()

    def reset_cancel(self):
        self._ui_cancel.clear()
        self.delegate.reset_cancel()
        for service in self.extra_delegates:
            reset = getattr(service, "reset_cancel", None)
            if callable(reset):
                reset()

    def _active_project(self):
        return Path(self.app.workflow_tab.pipeline.project)

    def _save_pending(self):
        view = self.app.workflow_tab
        for editor in view._dirty_windows():
            editor.save()
        if view._dirty_windows():
            raise InputRequired("Ein Editor hat ungespeicherte Änderungen. Bitte den Entwurf im Editor prüfen.")

    def call(self, name, args):
        try:
            if self._ui_cancel.is_set():
                return failure("cancelled", "Der KI-Auftrag wurde gestoppt. Bereits erledigte Änderungen bleiben erhalten.")
            if not isinstance(args, dict) or not self._mode_allows(name, args):
                return failure("mode_restricted", "Der gewählte Lesemodus oder der ausgeschaltete lokale Pythonlauf erlaubt diese Aktion nicht.")
            if name == "suite_ui":
                return self.dispatch(lambda: self._ui_call(args))
            extra = None
            for service in self.extra_delegates:
                if name in {spec["name"] for spec in service.specs()}:
                    if name == "suite_code":
                        extra = service
                        break
                    if getattr(service, "requires_gui_thread", True):
                        return self.dispatch(lambda: service.call(name, args))
                    return service.call(name, args)
            initial = self.dispatch(self._active_project)
            self.delegate.project = initial
            if name == "suite_project_op" and args.get("operation") not in {"inspect", "audit"}:
                self.dispatch(lambda: self._guarded(self._save_pending))
            if name == "suite_code" and args.get("operation") in {"write", "run"}:
                self.dispatch(lambda: self._guarded(self._save_pending))
            result = (extra or self.delegate).call(name, args)
            target = Path(self.delegate.project)

            def synchronize():
                view = self.app.workflow_tab
                if self._active_project() != initial:
                    view.pipeline.activate()
                    self.delegate.project = self._active_project()
                    return failure("gui_project_changed", "Das aktive Projekt wurde während des Auftrags gewechselt.",
                                   native_result=result)
                if target != initial:
                    self._guarded(self._save_pending)
                    if not view.activate_project(target):
                        return failure("input_required", "Projektwechsel wurde im Editor abgebrochen.", native_result=result)
                else:
                    view.refresh()
                return result

            return self.dispatch(synchronize)
        except InputRequired as exc:
            return failure("input_required", str(exc))
        except Exception as exc:
            return failure("ui_operation_failed", str(exc)[:1500], type=type(exc).__name__)

    @staticmethod
    def _text(widget, option, default=""):
        try:
            return str(widget.cget(option))
        except tk.TclError:
            return default

    @staticmethod
    def _canvas_owner(canvas):
        """Only known native editors with an inspectable model own gestures."""
        owner = canvas.winfo_toplevel()
        known = {
            ("suite_hud_menu_editor", "HudMenuPixelEditor"): "_anchor",
            ("suite_hud_menu_layout_editor", "HudMenuLayoutEditor"): "_drag_base",
            ("suite_sh1_hud_editor", "Sh1HudPixelEditor"): "_dragging",
            ("suite_origins_xaml_editor", "OriginsXamlEditor"): "_grab",
            ("suite_origins_visual_editor", "OriginsVisualEditor"): "_drag",
        }
        active = known.get((type(owner).__module__, type(owner).__name__))
        if active is None or getattr(owner, "canvas", None) is not canvas:
            return None, None
        return owner, active

    def _canvas_snapshot(self, canvas):
        owner, active = self._canvas_owner(canvas)
        items = []
        for ident in canvas.find_all():
            item = {"id": ident, "type": canvas.type(ident), "coords": canvas.coords(ident)}
            # Include visible content, not merely transient image handles.
            for name in ("text", "image", "state", "fill", "outline", "width", "tags"):
                try:
                    item[name] = canvas.itemcget(ident, name)
                except tk.TclError:
                    pass
            items.append(item)
        row = {"viewport": [canvas.winfo_width(), canvas.winfo_height()],
               "origin": [canvas.canvasx(0), canvas.canvasy(0)],
               "items": items[:200], "item_count": len(items),
               "items_sha256": sha256(json.dumps(items, sort_keys=True).encode()).hexdigest(),
               "gesture_supported": owner is not None}
        if owner is None:
            return row
        row["gesture_active"] = bool(getattr(owner, active, None) is not None
                                     if active != "_dragging" else owner._dragging)
        model = {}
        image = getattr(owner, "image", None)
        if image is not None:
            model["image"] = {"mode": image.mode, "size": image.size,
                              "sha256": sha256(image.tobytes()).hexdigest()}
            row["working_image"] = model["image"]
        history = getattr(owner, "history", None)
        if history is not None:
            model["scene"] = history.scene.as_json()
            model["history"] = [len(history._before), len(history._after)]
        doc = getattr(owner, "doc", None)
        if doc is not None:
            model["document_sha256"] = sha256(doc.edited_bytes()).hexdigest()
        for key in ("pending", "nodes", "selected", "_selection", "_handles", "_boxes", "_canvas_map"):
            if hasattr(owner, key):
                model[key] = repr(getattr(owner, key))
        for key in ("undo_stack", "redo_stack", "undo_history", "redo_history"):
            if hasattr(owner, key):
                model[key] = len(getattr(owner, key))
        controls = {}
        for key in ("mode", "color", "opacity", "alpha", "brush", "zoom", "snap", "snap_step", "proportional"):
            variable = getattr(owner, key, None)
            if isinstance(variable, tk.Variable):
                controls[key] = variable.get()
        row["controls"] = controls
        model["controls"] = controls
        row["model_sha256"] = sha256(json.dumps(model, sort_keys=True, default=str).encode()).hexdigest()
        return row

    def _canvas_gesture(self, canvas, args, mark_attempted):
        owner, active = self._canvas_owner(canvas)
        if owner is None:
            raise ValueError("Diese Canvas hat keinen freigegebenen nativen Editor mit Modellnachweis.")
        if not canvas.winfo_ismapped() or canvas.winfo_width() < 2 or canvas.winfo_height() < 2:
            raise ValueError("Die Canvas muss sichtbar sein.")
        if self._canvas_snapshot(canvas)["gesture_active"]:
            raise InputRequired("Eine Benutzergeste läuft bereits. Bitte deren Abschluss abwarten.")
        points = args.get("points")
        if not isinstance(points, list) or not 1 <= len(points) <= 128:
            raise ValueError("Eine Geste benötigt 1 bis 128 sichtbare lokale Punkte.")
        checked = []
        width, height = canvas.winfo_width(), canvas.winfo_height()
        for point in points:
            if not isinstance(point, list) or len(point) != 2 or not all(
                    type(n) in (int, float) and math.isfinite(n) for n in point):
                raise ValueError("Gestenpunkte müssen zwei endliche Zahlen enthalten.")
            x, y = (round(n) for n in point)
            if not (0 <= x < width and 0 <= y < height):
                raise ValueError("Alle Gestenpunkte müssen innerhalb der sichtbaren Canvas liegen.")
            checked.append((x, y))
        modifiers = args.get("modifiers", [])
        if not isinstance(modifiers, list) or len(modifiers) > 2 or any(
                not isinstance(item, str) or item not in {"shift", "control"} for item in modifiers) or len(set(modifiers)) != len(modifiers):
            raise ValueError("Nur die Modifikatoren shift und control sind erlaubt.")
        if not all(canvas.bind(sequence) for sequence in
                   ("<ButtonPress-1>", "<B1-Motion>", "<ButtonRelease-1>")):
            raise ValueError("Die Canvas besitzt keine vollständigen nativen Gestenbindungen.")
        if self._ui_cancel.is_set():
            raise InputRequired("Der KI-Auftrag wurde vor der Geste gestoppt.")
        state = (1 if "shift" in modifiers else 0) | (4 if "control" in modifiers else 0)
        errors, applied = [], []
        released = False

        def emit(sequence, point, held=False):
            canvas.event_generate(sequence, x=point[0], y=point[1],
                                  state=state | (0x100 if held else 0), when="now")
            if errors:
                raise errors[0]

        with patch.object(self.app._root(), "report_callback_exception",
                          lambda _kind, error, _trace: errors.append(error)):
            mark_attempted()
            try:
                applied.append(checked[0])
                emit("<ButtonPress-1>", checked[0])
                for point in checked[1:]:
                    if self._ui_cancel.is_set():
                        raise InputRequired("Geste gestoppt. Bereits ausgeführte Änderungen bleiben erhalten.")
                    applied.append(point)
                    emit("<B1-Motion>", point, True)
                if self._ui_cancel.is_set():
                    raise InputRequired("Geste gestoppt. Bereits ausgeführte Änderungen bleiben erhalten.")
                # Native release finalizes exactly one Undo step. No event-loop pumping.
                released = True
                emit("<ButtonRelease-1>", applied[-1])
            finally:
                try:
                    if not released:
                        # Finish at the last attempted point, never at an unexecuted endpoint.
                        # Some editors draw on release. This is completion, not rollback.
                        emit("<ButtonRelease-1>", applied[-1])
                finally:
                    # A failing native release (e.g. invalid line colour) must not
                    # leave our pointer lock active. No model/history is rolled back.
                    setattr(owner, active, False if active == "_dragging" else None)
        return {"points_applied": len(applied), "native_release": True,
                "completed_changes_retained": True}

    def snapshot(self):
        rows, widgets = [], {}
        stack = [self.app]
        while stack and len(rows) < 5000:
            widget = stack.pop()
            if widget is self.excluded or getattr(widget, "_suite_assistant_view", False) or not widget.winfo_exists():
                continue
            stack.extend(reversed(widget.winfo_children()))
            label = self._text(widget, "text")
            row = {"id": str(widget), "class": widget.winfo_class(),
                   "label": label[:500], "visible": bool(widget.winfo_ismapped()),
                   "state": [state for state in widget.state() if state not in {"active", "focus", "hover"}] if isinstance(widget, ttk.Widget) else self._text(widget, "state")}
            if isinstance(widget, (tk.Tk, tk.Toplevel)):
                row["title"] = widget.title()
            if isinstance(widget, (ttk.Entry, tk.Entry, ttk.Combobox)):
                secret = bool(self._text(widget, "show"))
                value = "[redacted]" if secret else str(widget.get())
                row.update(value=value[:4000], secret=secret)
                if isinstance(widget, ttk.Combobox):
                    row["choices"] = list(widget.cget("values"))[:200]
            elif isinstance(widget, tk.Text):
                value = widget.get("1.0", "end-1c")
                row.update(value=value[:4000], value_length=len(value), value_truncated=len(value) > 4000,
                           content_sha256=sha256(value.encode()).hexdigest())
            elif isinstance(widget, tk.Listbox):
                values = list(widget.get(0, tk.END))
                row.update(items=values[:200], item_count=len(values),
                           items_sha256=sha256(json.dumps(values).encode()).hexdigest(),
                           selected=list(widget.curselection()), selectmode=widget.cget("selectmode"))
            elif isinstance(widget, (tk.Scale, ttk.Scale)):
                row.update(value=widget.get(), minimum=widget.cget("from"), maximum=widget.cget("to"))
            elif isinstance(widget, tk.Canvas):
                row.update(self._canvas_snapshot(widget))
            elif isinstance(widget, ttk.Notebook):
                row["selected"] = widget.select()
            elif isinstance(widget, ttk.Treeview):
                row["selected"] = list(widget.selection())
                row["items"] = [{"id": key, "text": str(widget.item(key, "text")),
                                 "values": list(widget.item(key, "values"))}
                                for key in widget.get_children()[:100]]
            widgets[row["id"]] = widget
            rows.append(row)
            if isinstance(widget, tk.Menu):
                last = widget.index("end")
                for index in range(last + 1 if last is not None else 0):
                    if widget.type(index) in {"separator", "tearoff"}:
                        continue
                    menu_id = str(widget) + "#" + str(index)
                    rows.append({"id": menu_id, "class": "MenuItem",
                                 "label": widget.entrycget(index, "label"),
                                 "state": widget.entrycget(index, "state")})
                    widgets[menu_id] = (widget, index)
        content = {"project": str(self._active_project()), "widgets": rows}
        token = sha256(json.dumps(content, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        return {**content, "state_token": token, "total": len(rows), "truncated":bool(stack)}, widgets

    def _guarded(self, callback):
        errors, notifications = [], []

        def need_input(*_args, **_kwargs):
            raise InputRequired("Diese Aktion benötigt eine Dateiauswahl oder Eingabe. Bitte einen typisierten Projektauftrag mit explizitem Pfad verwenden.")

        def notice(kind):
            def record(title="", message="", **_kwargs):
                notifications.append({"kind": kind, "title": str(title), "message": str(message)})
            return record

        with ExitStack() as scope:
            for name in ("askopenfilename", "askopenfilenames", "asksaveasfilename", "askdirectory",
                         "askopenfile", "askopenfiles", "asksaveasfile"):
                scope.enter_context(patch.object(filedialog, name, need_input))
            for cls in (filedialog.Open, filedialog.SaveAs, filedialog.Directory):
                scope.enter_context(patch.object(cls, "show", need_input))
            for name in ("askstring", "askinteger", "askfloat"):
                scope.enter_context(patch.object(simpledialog, name, need_input))
            scope.enter_context(patch.object(colorchooser, "askcolor", need_input))
            for name in ("askyesno", "askokcancel", "askyesnocancel", "askretrycancel", "askquestion"):
                scope.enter_context(patch.object(messagebox, name, need_input))
            for name in ("showinfo", "showwarning", "showerror"):
                scope.enter_context(patch.object(messagebox, name, notice(name)))
            scope.enter_context(patch.object(self.app._root(), "report_callback_exception",
                lambda _kind, error, _trace: errors.append(error)))
            value = callback()
        if errors:
            raise errors[0]
        if any(item["kind"] == "showerror" for item in notifications):
            raise ValueError("; ".join(item["message"] for item in notifications))
        return value, notifications

    def _ui_call(self, args):
        snapshot, widgets = self.snapshot()
        operation = args.get("operation")
        if operation == "snapshot":
            offset, limit = args.get("offset", 0), args.get("limit", 200)
            if type(offset) is not int or type(limit) is not int or offset < 0 or not 1 <= limit <= 500:
                return failure("invalid_arguments", "Ungültiger Widget-Ausschnitt.")
            query = args.get("query", "")
            if not isinstance(query, str) or len(query) > 200:
                return failure("invalid_arguments", "Ungültiger Widget-Suchtext.")
            rows = snapshot["widgets"]
            if query:
                rows = [row for row in rows if query.casefold() in json.dumps(row, ensure_ascii=False).casefold()]
            snapshot["matched"] = len(rows)
            snapshot["widgets"] = rows[offset:offset + limit]
            return {"ok": True, "result": snapshot}
        if args.get("expected_state") != snapshot["state_token"]:
            return failure("stale_state", "Die Oberfläche wurde geändert. Bitte zuerst einen neuen Snapshot lesen.")
        target = widgets.get(args.get("widget_id"))
        if target is None:
            return failure("unknown_widget", "Dieses Steuerelement ist nicht mehr vorhanden.")
        attempted = False

        def mark_attempted():
            nonlocal attempted
            attempted = True

        def apply():
            if isinstance(target, tuple):
                if operation != "invoke":
                    raise ValueError("Menüeinträge unterstützen invoke.")
                if target[0].entrycget(target[1], "state") == "disabled":
                    raise ValueError("Der Menüeintrag ist deaktiviert.")
                return target[0].invoke(target[1])
            if ((isinstance(target, ttk.Widget) and target.instate(["disabled"])) or
                    self._text(target, "state") == "disabled"):
                raise ValueError("Das Steuerelement ist deaktiviert.")
            if operation == "focus":
                target.focus_set()
                target.event_generate("<FocusIn>")
                return None
            if operation == "invoke" and callable(getattr(target, "invoke", None)):
                return target.invoke()
            if operation == "gesture" and isinstance(target, tk.Canvas):
                return self._canvas_gesture(target, args, mark_attempted)
            if operation == "set" and isinstance(target, tk.Text):
                value = args.get("value")
                if not isinstance(value, str) or len(value) > 128000:
                    raise ValueError("Textänderungen benötigen höchstens 128000 Zeichen.")
                if len(target.get("1.0", "end-1c")) > 4000 and args.get("replace_full_text") is not True:
                    raise ValueError("Der Snapshottext ist gekürzt. Ein vollständiger Ersatz benötigt replace_full_text=true.")
                if value == target.get("1.0", "end-1c"):
                    return None
                separators = target.cget("autoseparators")
                target.edit_separator()
                target.configure(autoseparators=False)
                try:
                    target.delete("1.0", "end-1c")
                    target.insert("1.0", value)
                finally:
                    target.configure(autoseparators=separators)
                    target.edit_separator()
                target.edit_modified(True)
                target.event_generate("<<Modified>>")
                return None
            if operation == "set" and isinstance(target, tk.Listbox):
                value = args.get("value")
                keys = [value] if type(value) is int else value
                if (not isinstance(keys, list) or not all(type(key) is int and 0 <= key < target.size() for key in keys)
                        or (target.cget("selectmode") in ("browse", "single") and len(keys) > 1)):
                    raise ValueError("Listen benötigen gültige Auswahlindizes aus dem Snapshot.")
                target.selection_clear(0, tk.END)
                for key in keys:
                    target.selection_set(key)
                if keys:
                    target.activate(keys[0])
                    target.see(keys[0])
                target.event_generate("<<ListboxSelect>>")
                return None
            if operation == "set" and isinstance(target, (tk.Scale, ttk.Scale)):
                value = args.get("value")
                lower, upper = sorted((float(target.cget("from")), float(target.cget("to"))))
                if type(value) not in (int, float) or not math.isfinite(value) or not lower <= value <= upper:
                    raise ValueError("Skalenwerte müssen endlich und innerhalb des nativen Wertebereichs sein.")
                target.set(value)
                return None
            if operation == "set" and isinstance(target, ttk.Treeview):
                value = args.get("value")
                keys = [value] if isinstance(value, str) else value
                if not isinstance(keys, list) or not keys or not all(
                        isinstance(key, str) and target.exists(key) for key in keys):
                    raise ValueError("Auswahl benötigt existierende Eintrags-IDs aus dem Snapshot.")
                target.selection_set(keys)
                target.see(keys[0])
                target.event_generate("<<TreeviewSelect>>")
                return None
            if operation == "set" and isinstance(target, (ttk.Entry, tk.Entry, ttk.Combobox)):
                if self._text(target, "show"):
                    raise ValueError("Geschützte Zugangsdaten werden über die verwaltete Anmeldung bearbeitet.")
                value = args.get("value")
                if not isinstance(value, str) or len(value) > 32000:
                    raise ValueError("Feldwerte müssen begrenzter Text sein.")
                if isinstance(target, ttk.Combobox):
                    if self._text(target, "state") == "readonly" and value not in target.cget("values"):
                        raise ValueError("Wert gehört nicht zur vorhandenen Auswahlliste.")
                    target.set(value)
                    target.event_generate("<<ComboboxSelected>>")
                else:
                    if self._text(target, "state") == "readonly":
                        raise ValueError("Dieses Feld ist schreibgeschützt.")
                    target.delete(0, tk.END)
                    target.insert(0, value)
                    target.event_generate("<FocusOut>")
                return None
            raise ValueError("Diese Aktion wird für das Steuerelement nicht unterstützt.")

        try:
            value, notifications = self._guarded(apply)
        except InputRequired as exc:
            after, _ = self.snapshot()
            return failure("input_required", str(exc), state_token=after["state_token"],
                           state_changed=after["state_token"] != snapshot["state_token"],
                           operation_attempted=attempted,
                           completed_changes_retained=attempted)
        except Exception as exc:
            after, _ = self.snapshot()
            return failure("ui_operation_failed", str(exc)[:1500], operation_attempted=attempted,
                           state_token=after["state_token"],
                           state_changed=after["state_token"] != snapshot["state_token"])
        after, _ = self.snapshot()
        return {"ok": True, "result": {"invoked": operation, "widget_id": args["widget_id"],
                "state_token": after["state_token"], "notifications": notifications,
                "value": value if isinstance(value, (str, bool, int, float, type(None))) or operation == "gesture" else None}}


class AssistantWindow:
    MODES = {"Fragen (nur lesen)": "questions", "Aufträge (alle Werkzeuge)": "tasks",
             "Programmieren (Projektdateien)": "code"}

    def __init__(self, app, *, delegate=None, extra_delegates=(), session_factory=AssistantSession, embedded_host=None):
        self.app = app
        self.embedded_host = embedded_host
        self.root = ttk.Frame(embedded_host) if embedded_host is not None else tk.Toplevel(app)
        self.root._suite_assistant_view = True
        if embedded_host is not None:
            self.root.pack(fill="both", expand=True)
        else:
            self.root.title("SpriteSuite – KI-Assistent")
            self.root.geometry("900x720")
            self.root.minsize(560, 400)
            self.root.protocol("WM_DELETE_WINDOW", self.close)
        self._ui_thread = current_thread()
        self._queue = Queue()
        self._task_epoch = 0
        self._stopped = Event()
        self._worker = None
        self._cleanup_worker = None
        self._cleanup_workers = []
        self._session_lock = Lock()
        self._session = None
        self._streamed = False
        self._session_factory = session_factory
        self._closing = False
        self._on_closed = None
        self._active_epoch = None
        self._history_project = None
        self._store = None
        self._conversation = ConversationStore.new()
        self._history_choices = {}
        self._models = []
        self._stream_parts = []
        self._session_generation = None
        self.busy = False
        native = delegate or NativeToolService(app.workflow_tab.pipeline.project,
            approval=lambda request: self._dispatch(lambda: messagebox.askyesno(
                "KI-Auftrag braucht Bestätigung", json.dumps(request, ensure_ascii=False, indent=2),
                parent=self.root, default="no")))
        self.service = GuiToolService(app, native, self._dispatch, excluded=self.root,
                                      extra_delegates=extra_delegates)
        self._build()
        self._sync_history_project()
        self.root.bind("<Destroy>", self._destroyed, add="+")
        self._pump_job = self.root.after(30, self._pump)

    def _build(self):
        self.area = ScrollableWorkarea(self.root, min_width=440, min_height=280)
        self.area.pack(fill="both", expand=True)
        body = self.area.body
        body.columnconfigure(0, weight=1)
        body.rowconfigure(3, weight=1)
        ttk.Label(body, text="Aufträge im aktiven SpriteSuite-Projekt", font=("Segoe UI", 14, "bold")).grid(
            row=0, column=0, sticky="ew", padx=10, pady=5)
        self.prompt = ScrolledText(body, width=1, height=3, wrap="word")
        self.prompt.grid(row=1, column=0, sticky="ew", padx=10, pady=5)
        controls = ttk.Frame(body)
        controls.grid(row=2, column=0, sticky="ew", padx=10)
        self.send_button = ttk.Button(controls, text="Auftrag senden", command=self.send)
        self.send_button.grid(row=0, column=0, padx=2, pady=2)
        self.cancel_button = ttk.Button(controls, text="Stoppen", command=self.cancel, state="disabled")
        self.cancel_button.grid(row=0, column=1, padx=2, pady=2)
        self.login_button = ttk.Button(controls, text="Mit ChatGPT anmelden", command=self.login)
        self.login_button.grid(row=0, column=2, padx=2, pady=2)
        self.options_toggle = ttk.Button(controls, text="Optionen ▸", command=self.toggle_options)
        self.options_toggle.grid(row=0, column=3, padx=2, pady=2)
        self.details_toggle = ttk.Button(controls, text="Details ▸", command=self.toggle_details)
        self.details_toggle.grid(row=0, column=4, padx=2, pady=2)
        self.log = ScrolledText(body, width=1, height=7, wrap="word", state="disabled")
        self.log.grid(row=3, column=0, sticky="nsew", padx=10, pady=5)
        history = ttk.Frame(body)
        history.grid(row=4, column=0, sticky="ew", padx=10, pady=3)
        history.columnconfigure(1, weight=1)
        ttk.Label(history, text="Lokaler Verlauf").grid(row=0, column=0, padx=3)
        self.conversation_choice = tk.StringVar(master=self.root)
        self.conversation_picker = ttk.Combobox(history, textvariable=self.conversation_choice, state="readonly", width=24)
        self.conversation_picker.grid(row=0, column=1, sticky="ew", padx=3)
        self.conversation_picker.bind("<<ComboboxSelected>>", self.select_conversation)
        self.new_button = ttk.Button(history, text="Gespräch neu", command=self.new_conversation)
        self.new_button.grid(row=0, column=2, padx=3)
        self.options = ttk.LabelFrame(body, text="ChatGPT und Arbeitsmodus", padding=6)
        self.options.grid(row=5, column=0, sticky="ew", padx=10, pady=3)
        self.options.columnconfigure(1, weight=1)
        self.mode_choice = tk.StringVar(master=self.root, value="Aufträge (alle Werkzeuge)")
        self.model_choice = tk.StringVar(master=self.root, value="Kontostandard")
        self.effort_choice = tk.StringVar(master=self.root, value="Standard")
        self.allow_python = tk.BooleanVar(master=self.root, value=True)
        self.mode_picker = ttk.Combobox(self.options, textvariable=self.mode_choice, values=tuple(self.MODES), state="readonly")
        self.model_picker = ttk.Combobox(self.options, textvariable=self.model_choice, values=("Kontostandard",), state="readonly")
        self.effort_picker = ttk.Combobox(self.options, textvariable=self.effort_choice, values=("Standard",), state="readonly")
        for row, (label, widget) in enumerate((("Arbeitsmodus", self.mode_picker), ("Modell aus Konto", self.model_picker),
                                               ("Denkstufe", self.effort_picker))):
            ttk.Label(self.options, text=label).grid(row=row, column=0, sticky="w", padx=3, pady=3)
            widget.grid(row=row, column=1, sticky="ew", padx=3, pady=3)
        self.models_button = ttk.Button(self.options, text="Modelle laden", command=self.load_models)
        self.models_button.grid(row=1, column=2, padx=3)
        self.python_checkbox = ttk.Checkbutton(self.options, text="Lokalen Pythonlauf erlauben", variable=self.allow_python)
        self.python_checkbox.grid(row=3, column=0, columnspan=3, sticky="w", padx=3, pady=3)
        ttk.Label(self.options, text="Lokaler Prozess im Projektverzeichnis; keine Betriebssystem-Sandbox.",
                  wraplength=500).grid(row=4, column=0, columnspan=3, sticky="ew", padx=3)
        self.mode_picker.bind("<<ComboboxSelected>>", self._options_changed)
        self.model_picker.bind("<<ComboboxSelected>>", self._options_changed)
        self._option_controls = (self.mode_picker, self.model_picker, self.effort_picker, self.models_button,
                                 self.python_checkbox, self.conversation_picker, self.new_button)
        self.options.grid_remove()
        self.details = ScrolledText(body, width=1, height=6, wrap="none", state="disabled")
        self.details.grid(row=6, column=0, sticky="nsew", padx=10, pady=5)
        self.details.grid_remove()
        self.status = tk.StringVar(self.root, value="Bereit. Native Werkzeuge und deren Ergebnisse erscheinen im Protokoll.")
        status_view = ttk.Label(body, textvariable=self.status, wraplength=650)
        status_view.grid(row=7, column=0, sticky="ew", padx=10, pady=5)
        body.bind("<Configure>", lambda event: status_view.configure(wraplength=max(180, event.width - 24)))
        self._options_changed()

    def toggle_options(self):
        if self.options.winfo_manager():
            self.options.grid_remove()
            self.options_toggle.configure(text="Optionen ▸")
        else:
            self.options.grid()
            self.options_toggle.configure(text="Optionen ▾")
        self.area.refresh()

    def _options_changed(self, _event=None):
        model = self._chosen_model()
        advertised = (model or {}).get("supportedReasoningEfforts") or []
        efforts = [row.get("reasoningEffort", row.get("effort")) if isinstance(row, dict) else row for row in advertised]
        efforts = [value for value in efforts if isinstance(value, str) and value]
        self.effort_picker.configure(values=["Standard", *efforts])
        if self.effort_choice.get() not in ["Standard", *efforts]:
            self.effort_choice.set("Standard")
        self.python_checkbox.configure(state="normal" if not self.busy and self.MODES.get(self.mode_choice.get()) != "questions" else "disabled")

    def _chosen_model(self):
        return next((model for model in self._models if self._model_label(model) == self.model_choice.get()),
                    next((model for model in self._models if model.get("isDefault")), None))

    @staticmethod
    def _model_label(model):
        ident = str(model.get("model") or model.get("id") or "")
        return str(model.get("displayName") or ident) + " [" + ident + "]"

    def load_models(self):
        self._start("models")

    def add_delegate(self, service):
        if self.busy:
            raise ValueError("Werkzeuge können nur zwischen zwei Aufträgen hinzugefügt werden.")
        return self.service.add_delegate(service)

    def _detach_session(self):
        with self._session_lock:
            session, self._session = self._session, None
            self._session_generation = None
        if session is not None:
            self._cleanup_workers = [worker for worker in self._cleanup_workers if worker.is_alive()]
            worker = Thread(target=session.close, daemon=True)
            self._cleanup_workers.append(worker)
            self._cleanup_worker = worker
            worker.start()

    def _sync_history_project(self):
        project = Path(self.app.workflow_tab.pipeline.project)
        if project == self._history_project:
            return False
        self._history_project = project
        self._task_epoch += 1
        self._detach_session()
        self._store = None
        self._conversation = ConversationStore.new()
        try:
            self._store = ConversationStore(project)
            records = self._store.list()
            if records:
                self._conversation = records[0]
        except (ValueError, OSError) as error:
            self.status.set("Lokaler Verlauf nicht verfügbar: " + str(error)[:400])
        self._render_history()
        self._update_history_choices()
        return True

    def _update_history_choices(self):
        records = []
        if self._store is not None:
            try:
                records = self._store.list()
            except (ValueError, OSError):
                pass
        records = [self._conversation, *[record for record in records if record["id"] != self._conversation["id"]]]
        self._history_choices = {(record["title"] + " · " + record["id"][:6]): record["id"] for record in records}
        self.conversation_picker.configure(values=list(self._history_choices))
        selected = next(label for label, ident in self._history_choices.items() if ident == self._conversation["id"])
        self.conversation_choice.set(selected)

    def _render_history(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        for row in self._conversation["messages"]:
            role = {"user": "Du", "assistant": "ChatGPT", "tool": "Werkzeug"}[row["role"]]
            self.log.insert("end", role + ": " + row["text"] + "\n\n")
        self.log.configure(state="disabled")
        self.log.see("end")

    def _remember(self, role, text):
        self._conversation["messages"].append({"role": role, "text": history_text(text)})
        self._conversation["messages"] = self._conversation["messages"][-ConversationStore.MAX_MESSAGES:]
        if role == "user" and self._conversation["title"] == "Neues Gespräch":
            self._conversation["title"] = history_text(text, 60).replace("\n", " ") or "Gespräch"
        if self._store is not None:
            try:
                self._conversation = self._store.save(self._conversation)
            except (ValueError, OSError) as error:
                self.status.set("Verlauf konnte nicht gespeichert werden: " + str(error)[:400])
        self._update_history_choices()

    def _history_context(self):
        text = "\n".join(row["role"] + ": " + history_text(row["text"], 2500)
                         for row in self._conversation["messages"][-12:])
        return text[-16000:]

    def new_conversation(self):
        if self.busy:
            return False
        self._sync_history_project()
        if self._store is not None and len(self._store.list()) >= ConversationStore.MAX_CONVERSATIONS:
            self.status.set("Maximal 20 lokale Gespräche pro Projekt. Bitte ein vorhandenes Gespräch auswählen.")
            return False
        self._task_epoch += 1
        self._detach_session()
        self._conversation = ConversationStore.new()
        self._render_history()
        self._update_history_choices()
        self.status.set("Neues lokales Gespräch. Die Codex-Sitzung startet erst beim nächsten Auftrag.")
        return True

    def select_conversation(self, _event=None):
        if self.busy or self._store is None:
            return False
        identifier = self._history_choices.get(self.conversation_choice.get())
        if identifier == self._conversation["id"]:
            return True
        try:
            record = self._store.load(identifier)
        except (ValueError, OSError) as error:
            self.status.set(str(error))
            return False
        self._task_epoch += 1
        self._detach_session()
        self._conversation = record
        self._render_history()
        self.status.set("Lokaler Verlauf geöffnet. Beim nächsten Auftrag wird begrenzter Textkontext gesendet; kein Remote-Thread wird fortgesetzt.")
        return True

    def toggle_details(self):
        if self.details.frame.winfo_manager():
            self.details.grid_remove()
            self.details_toggle.configure(text="Details ▸")
        else:
            self.details.grid()
            self.details_toggle.configure(text="Details ▾")
        self.area.refresh()

    def _detail(self, value):
        self.details.configure(state="normal")
        self.details.insert(tk.END, json.dumps(value, ensure_ascii=False, default=str) + "\n")
        if len(self.details.get("1.0", "end-1c")) > 160000:
            self.details.delete("1.0", "end-160001c")
        self.details.see(tk.END)
        self.details.configure(state="disabled")

    def _finish_session(self):
        with self._session_lock:
            session = self._session
            self._session = None
        if session is not None:
            session.close()

    def _destroyed(self, event):
        if event.widget is self.root:
            if self._pump_job is not None:
                try:
                    self.root.after_cancel(self._pump_job)
                except tk.TclError:
                    pass
                self._pump_job = None
            self._closing = True
            self._stopped.set()
            self.service.cancel()
            session = self._session
            if session is not None:
                Thread(target=session.cancel, daemon=True).start()
                Thread(target=self._finish_session, daemon=True).start()

    def _append(self, text):
        self.log.configure(state="normal")
        self.log.insert(tk.END, text)
        if len(self.log.get("1.0", "end-1c")) > 120000:
            self.log.delete("1.0", "end-120001c")
        self.log.see(tk.END)
        self.log.configure(state="disabled")

    def _dispatch(self, callback):
        if self._stopped.is_set():
            raise InputRequired("Der KI-Auftrag wurde gestoppt.")
        if current_thread() is self._ui_thread:
            return callback()
        done, abandoned, result = Event(), Event(), {}
        epoch = self._task_epoch
        self._queue.put(("rpc", (callback, done, result, epoch, abandoned)))
        while not done.wait(.1):
            if self._stopped.is_set() or epoch != self._task_epoch:
                abandoned.set()
                raise InputRequired("Der KI-Auftrag wurde gestoppt.")
        if "error" in result:
            raise result["error"]
        return result.get("value")

    def _pump(self):
        self._pump_job = None
        try:
            if not self.root.winfo_exists():
                return
        except tk.TclError:
            return
        for _ in range(100):
            try:
                kind, value = self._queue.get_nowait()
            except Empty:
                break
            if kind == "rpc":
                callback, done, result, epoch, abandoned = value
                try:
                    if self._stopped.is_set() or abandoned.is_set() or epoch != self._task_epoch:
                        raise InputRequired("Auftrag gestoppt.")
                    result["value"] = callback()
                except Exception as exc:
                    result["error"] = exc
                finally:
                    done.set()
            elif kind == "event":
                epoch, generation, value = value
                if self._active_epoch is None or epoch != self._active_epoch or generation != self._session_generation or self._stopped.is_set():
                    continue
                self._detail(value)
                labels = {"suite_context":"Projekt lesen", "suite_tool_catalog":"Werkzeuge suchen",
                          "suite_tool_describe":"Werkzeug prüfen", "suite_tool_run":"Werkzeug ausführen",
                          "suite_project_op":"Projekt bearbeiten", "suite_ui":"Oberfläche bedienen",
                          "suite_sandbox":"Sandbox bearbeiten", "suite_editor":"Sprite-Editor bearbeiten",
                          "suite_code":"Projektcode bearbeiten"}
                if value["type"] == "text":
                    self._streamed = True
                    self._append(value.get("text", ""))
                    if sum(map(len, self._stream_parts)) < 64000:
                        self._stream_parts.append(str(value.get("text", ""))[:64000])
                elif value["type"] == "tool_started":
                    label = labels.get(value["name"], "Werkzeug ausführen")
                    self.status.set(label + " …")
                    self._append("\n" + label + " …\n")
                elif value["type"] == "tool_completed":
                    result = value.get("result") or {}
                    if result.get("ok"):
                        self._append("Werkzeugantwort erhalten.\n")
                        self._remember("tool", labels.get(value["name"], "Werkzeug") + ": Antwort erhalten.")
                    else:
                        error = result.get("error") or {}
                        self._append("Werkzeug benötigt weitere Bearbeitung: " +
                                     str(error.get("message", "Ausführung fehlgeschlagen"))[:1500] + "\n")
                        self._remember("tool", labels.get(value["name"], "Werkzeug") + ": " +
                                       str(error.get("message", "Ausführung fehlgeschlagen"))[:1500])
                elif value["type"] == "thread_restarted":
                    self._append("\nNeue Codex-Sitzung mit begrenztem lokalem Gesprächskontext.\n")
            elif kind == "done":
                epoch, value = value
                if epoch != self._active_epoch:
                    continue
                self._active_epoch = None
                self.busy = False
                self.send_button.configure(state="normal")
                self.login_button.configure(state="normal")
                self.cancel_button.configure(state="disabled")
                for control in self._option_controls:
                    control.configure(state="readonly" if isinstance(control, ttk.Combobox) else "normal")
                self._options_changed()
                if "models" in value:
                    self._models = value["models"]
                    choices = ["Kontostandard", *[self._model_label(model) for model in self._models]]
                    self.model_picker.configure(values=choices)
                    if self.model_choice.get() not in choices:
                        self.model_choice.set("Kontostandard")
                    self._options_changed()
                status = value.get("status", "Auftrag beendet")
                self.status.set("KI-Antwort abgeschlossen. Werkzeugergebnisse im Protokoll prüfen."
                                if status == "completed" else status)
                if value.get("message") and (not self._streamed or status != "completed"):
                    self._append("\n" + value["message"] + "\n")
                if self._operation == "run":
                    answer = value.get("message") or "".join(self._stream_parts)
                    if answer:
                        self._remember("assistant", answer)
                if not self._closing:
                    self._sync_history_project()
        if (self._closing and (self._worker is None or not self._worker.is_alive()) and
                all(not worker.is_alive() for worker in self._cleanup_workers) and
                (self._cleanup_worker is None or not self._cleanup_worker.is_alive())):
            self.root.destroy()
            if self._on_closed:
                self.app.after_idle(self._on_closed)
            return
        self._pump_job = self.root.after(30, self._pump)

    def _start(self, operation, prompt="", *, history_context=None):
        if self.busy or self._closing:
            return
        self.service.delegate.project = Path(self.app.workflow_tab.pipeline.project)
        self._sync_history_project()
        mode = self.MODES.get(self.mode_choice.get(), "questions")
        self.service.configure_mode(mode, self.allow_python.get())
        context = json.dumps({"active_project": str(self.service.project), "mode": mode,
                              "local_python_enabled": self.service.code_run_enabled}, ensure_ascii=False)
        history_context = self._history_context() if history_context is None else history_context
        selected_model = self._chosen_model() if self.model_choice.get() != "Kontostandard" else None
        model = (selected_model or {}).get("model") or (selected_model or {}).get("id")
        effort = self.effort_choice.get() if self.effort_choice.get() != "Standard" else None
        self._operation = operation
        self._task_epoch += 1
        epoch = self._active_epoch = self._task_epoch
        self.busy = True
        self._streamed = False
        self._stream_parts = []
        self._stopped.clear()
        # Reset before starting the worker. A later Stop must never be undone
        # by Session.run/models between the startup check and its first request.
        if self._session is not None and callable(getattr(self._session, "reset_cancel", None)):
            self._session.reset_cancel()
        else:
            self.service.reset_cancel()
        self.send_button.configure(state="disabled")
        self.login_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        for control in self._option_controls:
            control.configure(state="disabled")
        self.status.set("ChatGPT/Codex arbeitet …")

        def work():
            result = {}
            try:
                if self._session is None:
                    generation = self._session_generation = uuid4().hex
                    self._session = self._session_factory(self.service.project, self.service,
                        on_event=lambda event, generation=generation, epoch=epoch: self._queue.put((
                            "event", (epoch, generation, event))))
                # A retained callback from a prior turn must retain its OLD
                # epoch, even when the persistent Session itself is reused.
                generation = self._session_generation
                self._session.on_event = lambda event, generation=generation, epoch=epoch: self._queue.put((
                    "event", (epoch, generation, event)))
                if self._stopped.is_set():
                    self._session.cancel()
                    result = {"status":"cancelled", "message":"Auftrag gestoppt."}
                elif operation == "login":
                    self._session.login()
                    result = {"status": "Mit ChatGPT verbunden" if self._session.connected() else "Anmeldung erforderlich"}
                elif operation == "models":
                    result = {"status": "Modelle aus dem Konto geladen.",
                              "models": self._session.models(reset_cancel=False)}
                else:
                    result = self._session.run(prompt, context=context, model=model, reasoning_effort=effort,
                                               history_context=history_context, reset_cancel=False)
            except Exception as exc:
                result = ({"status":"cancelled", "message":"Vorgang gestoppt. Bereits abgeschlossene Änderungen bleiben erhalten."}
                          if self._stopped.is_set() else
                          {"status": "Auftrag fehlgeschlagen", "message": str(exc)})
            finally:
                try:
                    if self._closing:
                        self._finish_session()
                finally:
                    self._queue.put(("done", (epoch, result)))

        self._worker = Thread(target=work, daemon=True)
        self._worker.start()

    def send(self):
        prompt = self.prompt.get("1.0", "end-1c").strip()
        if not prompt or self.busy:
            return
        self._sync_history_project()
        history = self._history_context()
        self._remember("user", prompt)
        self._append("\nDu: " + prompt + "\n")
        self.prompt.delete("1.0", tk.END)
        self._start("run", prompt, history_context=history)

    def login(self):
        self._start("login")

    def cancel(self):
        self._task_epoch += 1
        self._stopped.set()
        self.service.cancel()
        session = self._session
        if session is not None:
            Thread(target=session.cancel, daemon=True).start()
            if getattr(self,"_operation",None) == "login":
                self._cleanup_worker = Thread(target=self._finish_session, daemon=True)
                self._cleanup_worker.start()
        self.status.set("Stoppen angefordert. Bereits ausgeführte Änderungen bleiben erhalten.")

    def close(self, on_closed=None):
        if on_closed is not None:
            self._on_closed = on_closed
        if self._closing:
            return False
        self._closing = True
        self.cancel()
        if self._session is None and (self._worker is None or not self._worker.is_alive()):
            if all(not worker.is_alive() for worker in self._cleanup_workers):
                self.root.destroy()
                return True
        self._cleanup_worker = Thread(target=self._finish_session, daemon=True)
        self._cleanup_workers.append(self._cleanup_worker)
        self._cleanup_worker.start()
        self.status.set("Lokale Codex-Sitzung wird beendet …")
        return False


def open_assistant(app, *, delegate=None, extra_delegates=(), session_factory=AssistantSession, embedded_host=None):
    current = getattr(app, "_ai_assistant_window", None)
    if current is not None and current.root.winfo_exists():
        show = getattr(app, "_show_assistant_host", None)
        if callable(show):
            show()
        if not current.busy:
            current._sync_history_project()
        current.root.lift()
        current.prompt.focus_set()
        return current
    embedded_host = embedded_host if embedded_host is not None else getattr(app, "_assistant_embed_host", None)
    window = AssistantWindow(app, delegate=delegate, extra_delegates=extra_delegates,
                             session_factory=session_factory, embedded_host=embedded_host)
    app._ai_assistant_window = window
    return window

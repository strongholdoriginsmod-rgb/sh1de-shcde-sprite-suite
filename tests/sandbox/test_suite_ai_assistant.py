"""Synthetic native GUI tools and worker lifecycle. No account or network."""
from pathlib import Path
import threading
import time
from types import SimpleNamespace
import tkinter as tk
from tkinter import ttk, filedialog

import pytest

from suite_ai_assistant import AssistantWindow, GuiToolService
from suite_tcl_runtime import create_tk_root


def test_production_entrypoint_connects_browser_and_existing_qt_without_initialization(monkeypatch):
    import importlib.machinery
    import importlib.util
    import suite_ai_assistant
    path = Path(__file__).resolve().parents[2] / "tools" / "suite_universal.pyw"
    loader = importlib.machinery.SourceFileLoader("assistant_factory_test", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    class Host:
        def __init__(self, extra):
            self.extra = list(extra)
            self.service = SimpleNamespace(delegate=SimpleNamespace(project=Path("synthetic-project")),
                                           mode="tasks", code_run_enabled=True)
        def add_delegate(self, value):self.extra.append(value)
    monkeypatch.setattr(suite_ai_assistant, "open_assistant", lambda app, **kwargs: Host(kwargs["extra_delegates"]))
    app = SimpleNamespace(sandbox_tab=SimpleNamespace(bridge=None))
    host = module.Universal.open_ai_assistant(app)
    services = host.extra
    assert {s.specs()[0]["name"] for s in services} == {"suite_editor", "suite_sandbox", "suite_code"}
    assert services[0].requires_gui_thread is False
    assert services[1].requires_gui_thread is True
    assert services[1].provider() is None
    app._assistant_extra_delegates = ()
    assert [item.specs()[0]["name"] for item in module.Universal.open_ai_assistant(app).extra] == ["suite_code"]


class Native:
    def __init__(self, project):
        self.project = Path(project)
        self.cancelled = False
    def specs(self):
        return []
    def call(self, name, args):
        return {"ok":True,"result":{"project":str(self.project)}}
    def cancel(self):
        self.cancelled = True
    def reset_cancel(self):
        self.cancelled = False


@pytest.fixture(scope="module")
def tk_runtime():
    root = create_tk_root()
    root.withdraw()
    try:
        yield root
    finally:
        root.destroy()


@pytest.fixture
def app(tmp_path, tk_runtime):
    root = tk.Toplevel(tk_runtime)
    root.geometry("700x500+40+40")
    project = tmp_path / "project"
    project.mkdir()
    pipeline = SimpleNamespace(project=project, activate=lambda:None)
    def activate(path):
        pipeline.project = Path(path)
        return True
    root.workflow_tab = SimpleNamespace(pipeline=pipeline, _dirty_windows=lambda: [],
                                        refresh=lambda: None, activate_project=activate)
    root.entry = ttk.Entry(root)
    root.entry.pack()
    root.entry.insert(0,"original")
    root.password = ttk.Entry(root,show="*")
    root.password.insert(0,"synthetic-test-secret")
    root.password.pack()
    try:
        root.update()
        yield root
    finally:
        if root.winfo_exists():
            root.destroy()


def service(app, **options):
    return GuiToolService(app,Native(app.workflow_tab.pipeline.project),lambda callback:callback(),**options)


def snapshot(native):
    result = native.call("suite_ui",{"operation":"snapshot","limit":500})
    assert result["ok"]
    return result["result"]


def mutate(native, widget, operation="set", **values):
    return native.call("suite_ui", {"operation": operation, "widget_id": str(widget),
        "expected_state": snapshot(native)["state_token"], **values})


@pytest.fixture
def native_assets(app, tmp_path, monkeypatch):
    import hud_menu_workspace as assets
    import hud_menu_layout as layout
    import se_asset_package as package
    import suite_hud_menu_layout_editor as designer
    from PIL import Image
    work = tmp_path / "work"
    work.mkdir()
    for module in (assets, layout, package):
        monkeypatch.setattr(module, "WORK", work)
    monkeypatch.setattr(assets, "ROOT", tmp_path)
    monkeypatch.setattr(package, "OUT", work / "packages")
    monkeypatch.setattr(designer, "read_session", lambda: {})
    monkeypatch.setattr(designer, "save_session", lambda **_kw: None)
    project = work / "native-assistant"
    original = tmp_path / "synthetic-original.png"
    Image.new("RGBA", (120, 80), (31, 70, 120, 255)).save(original)
    working = assets.import_image(original, project=project)
    app.workflow_tab.pipeline.project = project
    return project, working, original


def test_native_text_editor_replacement_is_dirty_and_one_undo_restores_full_text(app, native_assets):
    from suite_hud_menu_editor import HudMenuTextEditor
    project, _working, _original = native_assets
    path = project / "Override/Assets/GUI/Images/synthetic.json"
    before = '{"text":"original"}'
    path.write_text(before, encoding="utf8")
    editor = HudMenuTextEditor(app, path, project=project)
    app.update()
    native = service(app)
    modified = []
    editor.editor.bind("<<Modified>>", lambda _e: modified.append(editor.editor.edit_modified()))
    assert mutate(native, editor.editor, value='{"text":"changed"}')["ok"]
    assert editor.editor.edit_modified()
    assert modified and modified[-1]
    editor.editor.edit_undo()
    assert editor.editor.get("1.0", "end-1c") == before
    assert path.read_text("utf8") == before
    # A readonly log is never mutated, and a truncated prefix needs explicit intent.
    editor.editor.configure(state="disabled")
    assert not mutate(native, editor.editor, value="blocked")["ok"]
    editor.editor.configure(state="normal")
    editor.editor.delete("1.0", tk.END)
    editor.editor.insert("1.0", "x" * 4100)
    row = next(row for row in snapshot(native)["widgets"] if row["id"] == str(editor.editor))
    assert row["value_truncated"] and row["value_length"] == 4100
    assert not mutate(native, editor.editor, value=row["value"])["ok"]
    assert len(editor.editor.get("1.0", "end-1c")) == 4100
    editor.destroy()


def test_listbox_and_scale_set_use_native_callbacks_and_reject_invalid_values(app):
    choices = tk.Listbox(app, selectmode="extended")
    choices.insert(tk.END, "one", "two", "three")
    choices.pack()
    selected, numbers = [], []
    choices.bind("<<ListboxSelect>>", lambda _e: selected.append(choices.curselection()))
    scale = ttk.Scale(app, from_=0, to=10, command=lambda value: numbers.append(float(value)))
    scale.pack()
    app.update()
    native = service(app)
    assert mutate(native, choices, value=[0, 2])["ok"]
    assert selected == [(0, 2)]
    assert not mutate(native, choices, value=[True])["ok"]
    assert choices.curselection() == (0, 2)
    assert mutate(native, scale, value=6)["ok"]
    assert scale.get() == 6 and numbers[-1] == 6
    assert not mutate(native, scale, value=float("inf"))["ok"]
    assert scale.get() == 6


def test_native_pixel_gesture_uses_real_stroke_undo_and_sha_staleness(app, native_assets):
    from suite_hud_menu_editor import HudMenuPixelEditor
    project, working, original = native_assets
    original_bytes = original.read_bytes()
    working_bytes = working.read_bytes()
    editor = HudMenuPixelEditor(app, working, project=project)
    app.update()
    native = service(app)
    pixels = editor.image.tobytes()
    result = mutate(native, editor.canvas, "gesture", points=[[8, 8], [18, 8], [24, 12]])
    assert result["ok"], result
    assert len(editor.undo_stack) == 1 and editor.dirty and editor._anchor is None
    assert editor.image.tobytes() != pixels
    undo_id = next(row["id"] for row in snapshot(native)["widgets"]
                   if row["label"] == "Rückgängig" and row["id"].startswith(str(editor)))
    assert native.call("suite_ui", {"operation": "invoke", "widget_id": undo_id,
        "expected_state": snapshot(native)["state_token"]})["ok"]
    assert editor.image.tobytes() == pixels
    before = snapshot(native)
    # Same PhotoImage handle and Canvas items, genuinely changed working pixels.
    editor.image.putpixel((90, 60), (252, 10, 30, 255))
    assert snapshot(native)["state_token"] != before["state_token"]
    stale = native.call("suite_ui", {"operation": "gesture", "widget_id": str(editor.canvas),
        "expected_state": before["state_token"], "points": [[10, 10]]})
    assert stale["error"]["code"] == "stale_state"
    assert working.read_bytes() == working_bytes and original.read_bytes() == original_bytes
    editor.destroy()


def test_canvas_prevalidates_entire_path_and_respects_user_stroke(app, native_assets):
    from suite_hud_menu_editor import HudMenuPixelEditor
    from types import SimpleNamespace
    project, working, _original = native_assets
    editor = HudMenuPixelEditor(app, working, project=project)
    app.update()
    native = service(app)
    pixels = editor.image.tobytes()
    for points, modifiers in (([[8, 8], [99999, 8]], []), ([[True, 8]], []),
                              ([[8, 8]], ["shift", "shift"]), ([[8, 8]], [True])):
        assert not mutate(native, editor.canvas, "gesture", points=points, modifiers=modifiers)["ok"]
        assert editor.image.tobytes() == pixels and not editor.undo_stack and editor._anchor is None
    editor._down(SimpleNamespace(x=12, y=12))
    anchor, owned_pixels = editor._anchor, editor.image.tobytes()
    result = mutate(native, editor.canvas, "gesture", points=[[30, 30]])
    assert result["error"]["code"] == "input_required"
    assert not result["error"]["operation_attempted"]
    assert editor._anchor == anchor and editor.image.tobytes() == owned_pixels
    editor._up(SimpleNamespace(x=12, y=12))
    editor.destroy()


def test_canvas_cancel_finishes_only_attempted_points_and_retains_native_undo(app, native_assets):
    from suite_hud_menu_editor import HudMenuPixelEditor
    project, working, _original = native_assets
    editor = HudMenuPixelEditor(app, working, project=project)
    app.update()
    native = service(app)
    before = editor.image.tobytes()
    editor.canvas.bind("<B1-Motion>", lambda _e: native._ui_cancel.set(), add="+")
    result = mutate(native, editor.canvas, "gesture", points=[[8, 8], [16, 8], [150, 80]])
    assert result["error"]["code"] == "input_required"
    assert result["error"]["operation_attempted"] and result["error"]["completed_changes_retained"]
    assert editor._anchor is None and len(editor.undo_stack) == 1
    assert editor.image.tobytes() != before
    assert editor.image.getpixel((75, 40)) == (31, 70, 120, 255)
    editor.undo()
    assert editor.image.tobytes() == before
    editor.destroy()


def test_native_release_error_unlocks_owned_gesture_without_claiming_rollback(app, native_assets):
    from suite_hud_menu_editor import HudMenuPixelEditor
    project, working, _original = native_assets
    editor = HudMenuPixelEditor(app, working, project=project)
    app.update()
    native = service(app)
    before = editor.image.tobytes()
    editor.mode.set("Linie")
    editor.color.set("nothex")
    result = mutate(native, editor.canvas, "gesture", points=[[8, 8], [16, 8]])
    assert not result["ok"] and result["error"]["operation_attempted"]
    assert editor._anchor is None and len(editor.undo_stack) == 1
    editor.color.set("#ff0000")
    editor.mode.set("Pinsel")
    assert mutate(native, editor.canvas, "gesture", points=[[8, 8], [16, 8]])["ok"]
    assert editor.image.tobytes() != before
    editor.undo()
    assert editor.image.tobytes() == before
    editor.destroy()


def test_native_layout_gesture_commits_one_move_and_undo_restores_scene(app, native_assets):
    from suite_hud_menu_layout_editor import HudMenuLayoutEditor, _CANVAS_MARGIN
    project, working, original = native_assets
    before_file = original.read_bytes()
    editor = HudMenuLayoutEditor(app, project=project, source_asset=working.relative_to(project).as_posix())
    editor.geometry("1300x820+10+10")
    app.update()
    editor.add_asset()
    editor.snap.set(False)
    editor.fit()
    app.update()
    editor._flush_draw()
    layer = editor.scene.layers[0]
    before = editor.scene.as_json()
    history_size = len(editor.history._before)
    x = round(_CANVAS_MARGIN + (layer.x + layer.width / 2) * editor._scale - editor.canvas.canvasx(0))
    y = round(_CANVAS_MARGIN + (layer.y + layer.height / 2) * editor._scale - editor.canvas.canvasy(0))
    native = service(app)
    result = mutate(native, editor.canvas, "gesture", points=[[x, y], [x + 24, y + 16]])
    assert result["ok"], result
    assert editor.scene.as_json() != before and len(editor.history._before) == history_size + 1
    assert editor._drag_base is None and editor._drag_origin is None
    editor.undo()
    assert editor.scene.as_json() == before
    assert original.read_bytes() == before_file
    editor.destroy()


def test_ui_snapshot_redacts_credentials_and_rejects_stale_mutation(app):
    native = service(app)
    before = snapshot(native)
    secret = next(row for row in before["widgets"] if row["id"] == str(app.password))
    assert secret["value"] == "[redacted]"
    app.entry.insert(tk.END," changed")
    denied = native.call("suite_ui",{"operation":"set","widget_id":str(app.entry),
                        "expected_state":before["state_token"],"value":"replacement"})
    assert denied["error"]["code"] == "stale_state"
    assert app.entry.get() == "original changed"
    fresh = snapshot(native)
    accepted = native.call("suite_ui",{"operation":"set","widget_id":str(app.entry),
                          "expected_state":fresh["state_token"],"value":"replacement"})
    assert accepted["ok"]
    assert app.entry.get() == "replacement"


def test_ui_invokes_real_callback_and_file_dialog_becomes_input_required(app):
    called = []
    button = ttk.Button(app,text="Native action",command=lambda:called.append("invoked"))
    button.pack()
    dialog = ttk.Button(app,text="Choose source",command=filedialog.askopenfilename)
    dialog.pack()
    app.update()
    native = service(app)
    token = snapshot(native)["state_token"]
    assert native.call("suite_ui",{"operation":"invoke","widget_id":str(button),"expected_state":token})["ok"]
    assert called == ["invoked"]
    result = native.call("suite_ui",{"operation":"invoke","widget_id":str(dialog),
                                      "expected_state":snapshot(native)["state_token"]})
    assert result["error"]["code"] == "input_required"


def test_menu_and_combobox_use_native_callbacks(app):
    called = []
    menu = tk.Menu(app,tearoff=False)
    menu.add_command(label="Actual menu callback",command=lambda:called.append("menu"))
    combo = ttk.Combobox(app,values=("first","second"),state="readonly")
    combo.set("first")
    combo.bind("<<ComboboxSelected>>",lambda _event:called.append(combo.get()))
    combo.pack()
    app.update()
    native = service(app)
    for action, widget, value in (("invoke",str(menu)+"#0",None),("set",str(combo),"second")):
        args = {"operation":action,"widget_id":widget,"expected_state":snapshot(native)["state_token"]}
        if value is not None:args["value"] = value
        assert native.call("suite_ui",args)["ok"]
    assert called == ["menu","second"]


def test_extra_service_honors_worker_vs_gui_dispatch(app):
    called = []
    class Extra:
        requires_gui_thread = False
        def specs(self):return [{"name":"suite_editor"}]
        def call(self,*args):called.append("worker");return {"ok":True,"result":{}}
    native = GuiToolService(app,Native(app.workflow_tab.pipeline.project),
        lambda callback: (_ for _ in ()).throw(AssertionError("Browser I/O must stay off Tk")),
        extra_delegates=(Extra(),))
    assert native.call("suite_editor",{})["ok"]
    assert called == ["worker"]


def test_assistant_worker_dispatches_native_tk_and_renders_answer_once(app):
    main_thread = threading.get_ident()
    instances = []
    class Session:
        def __init__(self,cwd,service,on_event):
            assert threading.get_ident() != main_thread
            self.service,self.on_event = service,on_event
            self.closed = False
            instances.append(self)
        def run(self,prompt,**kwargs):
            state = self.service.call("suite_ui",{"operation":"snapshot","limit":500})["result"]
            result = self.service.call("suite_ui",{"operation":"set","widget_id":str(app.entry),
                "expected_state":state["state_token"],"value":"native worker change"})
            assert result["ok"]
            self.on_event({"type":"text","text":"One answer"})
            return {"status":"completed","message":"One answer","tool_calls":[]}
        def cancel(self):pass
        def close(self):self.closed = True
    host = AssistantWindow(app,delegate=Native(app.workflow_tab.pipeline.project),session_factory=Session)
    host.prompt.insert("1.0","Use native fields")
    host.send()
    deadline = time.monotonic()+5
    while host.busy and time.monotonic()<deadline:
        app.update();time.sleep(.01)
    assert not host.busy
    assert app.entry.get() == "native worker change"
    assert host.log.get("1.0",tk.END).count("One answer") == 1
    assert "KI-Antwort abgeschlossen" in host.status.get()
    host.close()
    while host.root.winfo_exists() and time.monotonic()<deadline:
        app.update();time.sleep(.01)
    assert instances[0].closed


def test_ui_confirmation_callback_returns_input_required_without_modal_wait(app):
    from tkinter import messagebox
    button = ttk.Button(app,text="Needs input",command=lambda:messagebox.askyesno("Native","Continue?"))
    button.pack();app.update()
    native = service(app)
    result = native.call("suite_ui",{"operation":"invoke","widget_id":str(button),
        "expected_state":snapshot(native)["state_token"]})
    assert result["error"]["code"] == "input_required"
    assert "state_token" in result["error"]


def test_cancel_during_session_start_never_sends_prompt(app):
    started, release = threading.Event(), threading.Event()
    calls = []
    class Session:
        def __init__(self,*args,**kwargs):
            started.set();release.wait(3)
        def run(self,prompt,**kwargs):calls.append("run");return {"status":"completed"}
        def cancel(self):calls.append("cancel")
        def close(self):calls.append("close")
    host = AssistantWindow(app,delegate=Native(app.workflow_tab.pipeline.project),session_factory=Session)
    host.prompt.insert("1.0","Queued prompt")
    host.send()
    assert started.wait(1)
    host.cancel()
    release.set()
    deadline = time.monotonic()+4
    while host.busy and time.monotonic()<deadline:
        app.update();time.sleep(.01)
    assert "run" not in calls
    assert "cancel" in calls
    host.close()
    while host.root.winfo_exists() and time.monotonic()<deadline:
        app.update();time.sleep(.01)
    assert "close" in calls


def test_native_project_sync_preserves_user_project_changed_during_work(app, tmp_path):
    initial = app.workflow_tab.pipeline.project
    changed = tmp_path / "user-selected"
    changed.mkdir()
    native = service(app)
    def call(_name,_args):
        app.workflow_tab.pipeline.project = changed
        return {"ok":True,"result":{"completed":True}}
    native.delegate.call = call
    result = native.call("suite_project_op",{"operation":"audit"})
    assert result["error"]["code"] == "gui_project_changed"
    assert result["error"]["native_result"]["ok"]
    assert app.workflow_tab.pipeline.project == changed
    assert initial != changed


def test_disabled_native_button_is_never_reported_as_invoked(app):
    calls = []
    button = ttk.Button(app,text="Disabled",command=lambda:calls.append("ran"))
    button.pack();button.state(["disabled"]);app.update()
    native = service(app)
    result = native.call("suite_ui",{"operation":"invoke","widget_id":str(button),
        "expected_state":snapshot(native)["state_token"]})
    assert not result["ok"]
    assert calls == []
    menu = tk.Menu(app, tearoff=False)
    menu.add_command(label="Disabled menu", state="disabled", command=lambda: calls.append("menu"))
    result = native.call("suite_ui", {"operation": "invoke", "widget_id": str(menu) + "#0",
        "expected_state": snapshot(native)["state_token"]})
    assert not result["ok"] and calls == []


def test_cancel_managed_login_releases_worker_without_waiting_for_user(app):
    started, released = threading.Event(), threading.Event()
    class Session:
        def __init__(self,*args,**kwargs):pass
        def login(self):
            started.set();released.wait(3)
            raise ValueError("Local login connection closed")
        def connected(self):return False
        def cancel(self):pass
        def close(self):released.set()
    host = AssistantWindow(app,delegate=Native(app.workflow_tab.pipeline.project),session_factory=Session)
    host.login()
    assert started.wait(1)
    host.cancel()
    deadline = time.monotonic()+3
    while host.busy and time.monotonic()<deadline:
        app.update();time.sleep(.01)
    assert not host.busy
    assert host.status.get() == "cancelled"
    host.close()


def test_browser_cancellation_runs_outside_the_tk_thread(app):
    done = threading.Event()
    threads = []
    class Browser:
        requires_gui_thread = False
        def specs(self):return []
        def cancel(self):
            threads.append(threading.get_ident())
            done.set()
    native = service(app,extra_delegates=(Browser(),))
    ui_thread = threading.get_ident()
    native.cancel()
    assert done.wait(2)
    assert threads and threads[0] != ui_thread


def test_cancelled_queued_ui_rpc_never_reappears_after_new_turn(app):
    from suite_ai_assistant import InputRequired
    changed, errors = [], []
    class Session:
        def __init__(self,*args,**kwargs):pass
        def run(self,*args,**kwargs):return {"status":"completed"}
        def cancel(self):pass
        def close(self):pass
    host = AssistantWindow(app,delegate=Native(app.workflow_tab.pipeline.project),session_factory=Session)
    def old_rpc():
        try:host._dispatch(lambda:changed.append("stale mutation"))
        except InputRequired:errors.append("cancelled")
    waiting = threading.Thread(target=old_rpc)
    waiting.start()
    deadline = time.monotonic()+3
    while host._queue.empty() and time.monotonic()<deadline:time.sleep(.01)
    host.cancel()
    host._start("run","new turn")
    while (host.busy or waiting.is_alive()) and time.monotonic()<deadline:
        app.update();time.sleep(.01)
    waiting.join(timeout=1)
    assert changed == []
    assert errors == ["cancelled"]
    host.close()
    while host.root.winfo_exists() and time.monotonic()<deadline:
        app.update();time.sleep(.01)


def settle(host, app, timeout=5):
    deadline = time.monotonic() + timeout
    while host.busy and time.monotonic() < deadline:
        app.update()
        time.sleep(.01)
    assert not host.busy, host.status.get()


def close_host(host, app):
    host.close()
    deadline = time.monotonic() + 5
    while host.root.winfo_exists() and time.monotonic() < deadline:
        app.update()
        time.sleep(.01)
    assert not host.root.winfo_exists()


def history_project(app, tmp_path, monkeypatch, name="history-project"):
    import hud_menu_workspace as hud
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    monkeypatch.setattr(hud, "ROOT", tmp_path)
    monkeypatch.setattr(hud, "WORK", work)
    project = work / name
    project.mkdir(exist_ok=True)
    app.workflow_tab.pipeline.project = project
    return project


def test_embedded_startup_reuses_home_chat_without_account_or_model_calls(app):
    from suite_ai_assistant import open_assistant
    created, shown = [], []
    class Session:
        def __init__(self,*args,**kwargs):created.append(True)
    holder = ttk.Frame(app, height=345)
    holder.pack(fill="x")
    holder.pack_propagate(False)
    app._assistant_embed_host = holder
    app._show_assistant_host = lambda:shown.append(True)
    before = [w for w in app.winfo_children() if isinstance(w, tk.Toplevel)]
    host = open_assistant(app,delegate=Native(app.workflow_tab.pipeline.project),session_factory=Session)
    app.update()
    assert host.root.master is holder
    assert [w for w in app.winfo_children() if isinstance(w, tk.Toplevel)] == before
    assert open_assistant(app) is host and shown == [True]
    assert not created and host._session is None
    assert host.mode_choice.get()=="Aufträge (alle Werkzeuge)" and host.allow_python.get() is True
    host.prompt.insert("1.0", "private unsent draft")
    state = snapshot(host.service)
    assert "private unsent draft" not in str(state)
    assert not any(row["id"].startswith(str(host.root)) for row in state["widgets"])
    assert host.prompt.winfo_rooty() >= host.root.winfo_rooty()
    assert host.prompt.winfo_rooty() + host.prompt.winfo_height() <= host.root.winfo_rooty() + host.root.winfo_height()
    host.toggle_options()
    app.update()
    host.area.reveal(host.python_checkbox)
    app.update()
    assert host.python_checkbox.winfo_rooty() >= host.area.canvas.winfo_rooty()
    assert host.python_checkbox.winfo_rooty() + host.python_checkbox.winfo_height() <= host.area.canvas.winfo_rooty() + host.area.canvas.winfo_height()
    close_host(host, app)


def test_models_and_efforts_are_loaded_on_request_and_passed_to_real_session_api(app):
    calls, runs = [], []
    class Session:
        def __init__(self,*args,**kwargs):calls.append("created")
        def models(self,**kwargs):
            calls.append(("models",kwargs))
            return [{"model":"account-model","displayName":"Account choice","isDefault":True,
                     "supportedReasoningEfforts":[{"reasoningEffort":"advertised-effort"}]}]
        def reset_cancel(self):calls.append("reset")
        def run(self,prompt,**kwargs):runs.append(kwargs);return {"status":"completed","message":"Answered"}
        def cancel(self):pass
        def close(self):pass
    host = AssistantWindow(app,delegate=Native(app.workflow_tab.pipeline.project),session_factory=Session)
    assert calls == []
    assert host.model_picker.cget("values") == ("Kontostandard",)
    host.load_models()
    settle(host, app)
    assert ("models",{"reset_cancel":False}) in calls
    assert "advertised-effort" in host.effort_picker.cget("values")
    assert "high" not in host.effort_picker.cget("values")
    host.model_choice.set("Account choice [account-model]")
    host.effort_choice.set("advertised-effort")
    host.prompt.insert("1.0","Answer this")
    host.send();settle(host,app)
    assert runs[0]["model"] == "account-model" and runs[0]["reasoning_effort"] == "advertised-effort"
    assert runs[0]["reset_cancel"] is False
    assert len([call for call in calls if isinstance(call,tuple)]) == 1
    close_host(host,app)


def test_question_mode_rejects_all_mutations_and_report_flag_aliases(app):
    native = service(app)
    invoked = []
    native.delegate.call = lambda name,args:invoked.append((name,args)) or {"ok":True,"result":{}}
    native.configure_mode("questions")
    for name,args in (("suite_ui",{"operation":"set","widget_id":str(app.entry),"value":"changed"}),
                      ("suite_project_op",{"operation":"create_image"}),
                      ("suite_editor",{"operation":"execute","request":{"operation":"import"}}),
                      ("suite_tool_run",{"name":"qa_hp_fire_live_log.py","arguments":["--output=would-write.json"]}),
                      ("suite_code",{"operation":"write","path":"file.py"}),
                      ("suite_code",{"operation":"run","path":"file.py"})):
        result = native.call(name,args)
        assert result["error"]["code"] == "mode_restricted"
    assert not invoked and app.entry.get() == "original"
    assert native.call("suite_ui",{"operation":"snapshot"})["ok"]
    assert native.call("suite_tool_run",{"name":"existing.py","arguments":["--help"]})["ok"]


def test_code_delegate_gets_save_guard_captured_project_and_optional_execution_limit(app):
    calls, saved, refreshed = [], [], []
    native = service(app)
    editor = SimpleNamespace(save=lambda:saved.append(True))
    app.workflow_tab._dirty_windows = lambda:[] if saved else [editor]
    app.workflow_tab.refresh = lambda:refreshed.append(True)
    class Code:
        requires_gui_thread=False
        def specs(self):return [{"name":"suite_code"}]
        def call(self,name,args):calls.append((name,args,native.delegate.project));return {"ok":True,"result":{}}
    assert native.add_delegate(Code())
    assert not native.add_delegate(Code())
    assert native.mode=="tasks" and native.code_run_enabled
    assert native.call("suite_code",{"operation":"write"})["ok"]
    assert native.call("suite_code",{"operation":"run"})["ok"]
    native.configure_mode("tasks",False)
    assert native.call("suite_code",{"operation":"run"})["error"]["code"] == "mode_restricted"
    native.configure_mode("code",False)
    assert native.call("suite_code",{"operation":"write"})["ok"]
    assert saved and refreshed and calls[0][2] == app.workflow_tab.pipeline.project
    assert native.call("suite_code",{"operation":"run"})["error"]["code"] == "mode_restricted"
    native.configure_mode("code",True)
    assert native.call("suite_code",{"operation":"run"})["ok"]
    assert len(calls) == 4


def test_turn_options_are_frozen_while_busy_and_stop_cannot_reset_code_gate(app):
    entered, release = threading.Event(), threading.Event()
    mutations, seen = [], []
    class Code:
        requires_gui_thread=False
        def specs(self):return [{"name":"suite_code"}]
        def call(self,*args):mutations.append(True);return {"ok":True,"result":{}}
        def cancel(self):pass
        def reset_cancel(self):pass
    class Session:
        def __init__(self,cwd,service,on_event):self.service=service
        def run(self,prompt,**kwargs):
            seen.append((self.service.mode,self.service.code_run_enabled,kwargs["reset_cancel"]))
            entered.set();assert release.wait(3)
            result=self.service.call("suite_code",{"operation":"run"})
            seen.append(result)
            return {"status":"cancelled","message":"Stopped"}
        def cancel(self):pass
        def close(self):pass
    host=AssistantWindow(app,delegate=Native(app.workflow_tab.pipeline.project),extra_delegates=(Code(),),session_factory=Session)
    host.prompt.insert("1.0","Run explicit synthetic code");host.send()
    assert entered.wait(1)
    assert host.mode_picker.instate(["disabled"]) and host.python_checkbox.instate(["disabled"])
    host.mode_choice.set("Fragen (nur lesen)");host.allow_python.set(False)
    assert host.service.mode == "tasks" and host.service.code_run_enabled
    host.cancel();release.set();settle(host,app)
    assert seen[0] == ("tasks",True,False)
    assert seen[1]["error"]["code"] == "cancelled" and not mutations
    close_host(host,app)


def test_local_history_roundtrip_is_bounded_redacted_and_never_resumes_remote_thread(app,tmp_path,monkeypatch):
    from suite_ai_assistant import ConversationStore
    project=history_project(app,tmp_path,monkeypatch)
    sessions=[]
    class Session:
        def __init__(self,*args,**kwargs):sessions.append(self)
        def run(self,prompt,**kwargs):return {"status":"completed","message":"Saved answer","threadId":"do-not-persist"}
        def cancel(self):pass
        def close(self):pass
    host=AssistantWindow(app,delegate=Native(project),session_factory=Session)
    host.prompt.insert("1.0","Keep note api_key=sk-1234567890abcdefghijk password=synthetic-secret")
    host.send();settle(host,app)
    store=ConversationStore(project)
    files=list(store.folder.glob("*.json"));assert len(files)==1
    raw=files[0].read_text("utf8")
    assert "synthetic-secret" not in raw and "sk-1234567890abcdefghijk" not in raw and "do-not-persist" not in raw
    close_host(host,app)
    restored=AssistantWindow(app,delegate=Native(project),session_factory=Session)
    assert len(sessions)==1 and restored._session is None
    assert "Saved answer" in restored.log.get("1.0","end")
    assert "Saved answer" in restored._history_context()
    conversation=ConversationStore.new()
    conversation["messages"]=[{"role":"user","text":"x"*9000} for _ in range(200)]
    bounded=store.save(conversation)
    path=store.folder/(bounded["id"]+".json")
    assert path.stat().st_size<=store.MAX_BYTES and len(bounded["messages"])<=store.MAX_MESSAGES
    assert all(len(row["text"])<=6000 for row in bounded["messages"])
    with pytest.raises(ValueError):store.load("../auth")
    close_host(restored,app)


def test_project_switch_starts_new_session_and_drops_queued_old_chat_events(app,tmp_path,monkeypatch):
    first=history_project(app,tmp_path,monkeypatch,"first")
    instances,runs=[],[]
    class Session:
        def __init__(self,cwd,service,on_event):self.cwd=Path(cwd);instances.append(self)
        def run(self,prompt,**kwargs):runs.append((self.cwd,kwargs["history_context"]));return {"status":"completed","message":"Project answer"}
        def reset_cancel(self):pass
        def cancel(self):pass
        def close(self):pass
    host=AssistantWindow(app,delegate=Native(first),session_factory=Session)
    host.prompt.insert("1.0","Old project context");host.send();settle(host,app)
    old_generation=host._session_generation
    second=first.parent/"second";second.mkdir();app.workflow_tab.pipeline.project=second
    host.prompt.insert("1.0","New project request");host.send()
    host._queue.put(("event",(host._active_epoch,old_generation,{"type":"text","text":"STALE OLD REPLY"})))
    settle(host,app)
    assert [row.cwd for row in instances]==[first,second]
    assert "Old project context" not in runs[-1][1]
    assert "STALE OLD REPLY" not in host.log.get("1.0","end")
    assert "Old project context" not in host.log.get("1.0","end")
    close_host(host,app)


def test_select_saved_conversation_uses_local_context_with_new_ephemeral_session(app,tmp_path,monkeypatch):
    project=history_project(app,tmp_path,monkeypatch)
    instances,runs=[],[]
    class Session:
        def __init__(self,*args,**kwargs):instances.append(self)
        def run(self,prompt,**kwargs):runs.append(kwargs);return {"status":"completed","message":"Local saved answer"}
        def cancel(self):pass
        def close(self):pass
    host=AssistantWindow(app,delegate=Native(project),session_factory=Session)
    host.prompt.insert("1.0","First local topic");host.send();settle(host,app)
    first_id=host._conversation["id"]
    assert host.new_conversation()
    host.prompt.insert("1.0","Second local topic");host.send();settle(host,app)
    assert len(instances)==2 and first_id!=host._conversation["id"]
    first_label=next(label for label,ident in host._history_choices.items() if ident==first_id)
    host.conversation_choice.set(first_label)
    assert host.select_conversation()
    assert "First local topic" in host.log.get("1.0","end")
    assert "Second local topic" not in host.log.get("1.0","end")
    host.prompt.insert("1.0","Continue first topic");host.send();settle(host,app)
    assert len(instances)==3 and "First local topic" in runs[-1]["history_context"]
    assert "Second local topic" not in runs[-1]["history_context"]
    close_host(host,app)


def test_old_callback_reference_keeps_prior_turn_epoch_on_reused_session(app):
    callbacks=[]
    entered,release=threading.Event(),threading.Event()
    class Session:
        def __init__(self,cwd,service,on_event):self.on_event=on_event;self.runs=0
        def run(self,prompt,**kwargs):
            self.runs+=1;callbacks.append(self.on_event)
            if self.runs==2:
                entered.set();assert release.wait(3)
            return {"status":"completed","message":"Current answer"}
        def reset_cancel(self):pass
        def cancel(self):pass
        def close(self):pass
    host=AssistantWindow(app,delegate=Native(app.workflow_tab.pipeline.project),session_factory=Session)
    host.prompt.insert("1.0","First turn");host.send();settle(host,app)
    host.prompt.insert("1.0","Second turn");host.send();assert entered.wait(1)
    callbacks[0]({"type":"text","text":"OLD CALLBACK LEAK"})
    callbacks[1]({"type":"text","text":"Current streamed reply"})
    release.set();settle(host,app)
    assert "OLD CALLBACK LEAK" not in host.log.get("1.0","end")
    assert "Current streamed reply" in host.log.get("1.0","end")
    close_host(host,app)


def test_embedded_details_toggle_maps_actual_scrolledtext_frame(app):
    holder=ttk.Frame(app,height=345)
    holder.pack(fill="x");holder.pack_propagate(False)
    host=AssistantWindow(app,delegate=Native(app.workflow_tab.pipeline.project),embedded_host=holder)
    app.update()
    assert not host.details.winfo_ismapped()
    host.toggle_details();app.update()
    assert host.details.frame.winfo_manager()=="grid"
    assert host.details.winfo_ismapped()
    host.area.reveal(host.details.frame);app.update()
    assert host.details.frame.winfo_rooty()>=host.area.canvas.winfo_rooty()
    assert host.details.frame.winfo_rooty()+host.details.frame.winfo_height()<=host.area.canvas.winfo_rooty()+host.area.canvas.winfo_height()
    host.toggle_details();app.update()
    assert not host.details.winfo_ismapped()
    close_host(host,app)


def test_default_all_tools_code_routing_without_tk_or_optin(tmp_path):
    calls=[]
    project=tmp_path/"synthetic-project";project.mkdir()
    callback_root=SimpleNamespace(report_callback_exception=lambda *_args:None)
    pipeline=SimpleNamespace(project=project,activate=lambda:None)
    app=SimpleNamespace(_root=lambda:callback_root,workflow_tab=SimpleNamespace(
        pipeline=pipeline,_dirty_windows=lambda:[],refresh=lambda:None))
    native=GuiToolService(app,Native(project),lambda callback:callback())
    class Code:
        requires_gui_thread=False
        def specs(self):return [{"name":"suite_code"}]
        def call(self,name,args):calls.append(args["operation"]);return {"ok":True,"result":{}}
    native.add_delegate(Code())
    # Fresh production defaults allow the requested programming operations.
    assert native.mode=="tasks" and native.code_run_enabled
    assert native.call("suite_code",{"operation":"write"})["ok"]
    assert native.call("suite_code",{"operation":"run"})["ok"]
    for mode in ("tasks","code"):
        native.configure_mode(mode,False)
        assert native.call("suite_code",{"operation":"write"})["ok"]
        assert native.call("suite_code",{"operation":"run"})["error"]["code"]=="mode_restricted"
        native.configure_mode(mode,True)
        assert native.call("suite_code",{"operation":"run"})["ok"]
    native.configure_mode("questions",True)
    assert not native.code_run_enabled
    for operation in ("write","run"):
        assert native.call("suite_code",{"operation":operation})["error"]["code"]=="mode_restricted"
    assert calls==["write","run","write","run","write","run"]


def test_options_preserve_user_execution_choice_without_tk():
    class Value:
        def __init__(self,value):self.value=value
        def get(self):return self.value
        def set(self,value):self.value=value
    class Control:
        def configure(self,**kwargs):self.options=kwargs
    host=SimpleNamespace(_chosen_model=lambda:None,effort_picker=Control(),effort_choice=Value("Standard"),
                         mode_choice=Value("Aufträge (alle Werkzeuge)"),allow_python=Value(True),
                         python_checkbox=Control(),busy=False,MODES=AssistantWindow.MODES)
    for selected in (True,False):
        host.allow_python.set(selected)
        for mode in ("Aufträge (alle Werkzeuge)","Programmieren (Projektdateien)","Fragen (nur lesen)"):
            host.mode_choice.set(mode)
            AssistantWindow._options_changed(host)
            assert host.allow_python.get() is selected
            assert host.python_checkbox.options["state"]==("disabled" if mode=="Fragen (nur lesen)" else "normal")

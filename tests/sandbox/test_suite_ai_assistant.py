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
    monkeypatch.setattr(suite_ai_assistant, "open_assistant", lambda app, **kwargs: kwargs["extra_delegates"])
    app = SimpleNamespace(sandbox_tab=SimpleNamespace(bridge=None))
    services = module.Universal.open_ai_assistant(app)
    assert {s.specs()[0]["name"] for s in services} == {"suite_editor", "suite_sandbox"}
    assert services[0].requires_gui_thread is False
    assert services[1].requires_gui_thread is True
    assert services[1].provider() is None
    app._assistant_extra_delegates = ()
    assert module.Universal.open_ai_assistant(app) == ()


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

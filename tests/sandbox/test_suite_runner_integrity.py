"""Core runner and lock contract for the *whole* Suite.

These tests use the real Tk application with a scoped temporary workspace
lock, but never launch a game, build tool, installer, or write game assets.
"""
from __future__ import annotations

from pathlib import Path
import importlib.machinery
import importlib.util
import sys
from types import SimpleNamespace

import pytest
from tkinter import messagebox

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/"tools"),str(ROOT/"src")]


def _module():
    loader=importlib.machinery.SourceFileLoader(
        "suite_core_contract_test",str(ROOT/"tools"/"suite_universal.pyw"))
    spec=importlib.util.spec_from_loader(loader.name,loader)
    obj=importlib.util.module_from_spec(spec)
    loader.exec_module(obj)
    return obj


def test_core_runner_reports_actual_acceptance_not_ui_intent(monkeypatch):
    suite=_module()
    mock=SimpleNamespace()
    calls=[]
    accepted=SimpleNamespace(start=lambda *args,**kwargs:calls.append(args) or True)
    state=[]
    mock.runner=accepted
    mock.stop_button=SimpleNamespace(state=lambda values:state.append(values))
    assert suite.workshop.Suite.run(mock,["test"],"test") is True
    assert calls==[(["test"],"test")]
    assert state==[["!disabled"]]
    blocked=[]
    mock.runner=SimpleNamespace(start=lambda *a,**k:False)
    monkeypatch.setattr(messagebox,"showinfo",lambda *a,**k:blocked.append(a))
    assert suite.workshop.Suite.run(mock,["test2"],"test2") is False
    assert state==[["!disabled"]]
    assert len(blocked)==1


@pytest.fixture
def app(tmp_path,monkeypatch):
    import stronghold_europe_de.workspace_lock as locks
    monkeypatch.setattr(
        locks,"lock_path",lambda _a,_b:tmp_path/"suite-core.lock")
    suite=_module()
    monkeypatch.setattr(suite,"SETTINGS",tmp_path/"settings.json")
    suite.LANG.code="de"
    try:
        gui=suite.Universal()
    except Exception as exc:
        pytest.skip(str(exc))
    monkeypatch.setattr(gui.sandbox_tab,"ensure_studio",lambda:None)
    try:
        yield gui
    finally:
        try:
            monkeypatch.setattr(gui.sandbox_tab,"close_studio",lambda:True)
            gui.runner.thread=None
            gui.destroy()
        except Exception:
            pass


def test_cancelled_embedded_close_preserves_build_and_single_instance_lock(
    app,monkeypatch
):
    gui=app
    assert gui._instance_lock._stream is not None
    stop_calls=[]
    gui.runner.thread=SimpleNamespace(is_alive=lambda:True)
    monkeypatch.setattr(gui.runner,"stop",lambda:stop_calls.append("kill build"))
    monkeypatch.setattr(messagebox,"askyesno",lambda *a,**kw:True)
    monkeypatch.setattr(gui.sandbox_tab,"close_studio",lambda:False)
    gui._close()
    assert gui.winfo_exists()
    assert stop_calls==[]  # user rejected closing unsaved editor
    assert gui._instance_lock._stream is not None
    monkeypatch.setattr(gui.sandbox_tab,"close_studio",lambda:True)
    gui._close()
    assert stop_calls==["kill build"]
    assert gui._instance_lock._stream is None


def test_core_capture_rejection_does_not_replace_existing_sink(app,monkeypatch):
    gui=app
    gui.runner.thread=SimpleNamespace(is_alive=lambda:True)
    sentinel=lambda *a:None
    gui._capture_sink=sentinel
    seen=[]
    monkeypatch.setattr(messagebox,"showinfo",lambda *a,**k:seen.append(a))
    assert gui.run_captured(["not-started"],"test",lambda *a:None) is False
    assert gui._capture_sink is sentinel
    assert seen
    gui.runner.thread=None


def test_center_run_propagates_accepted_or_rejected_jobs(app,monkeypatch):
    gui=app
    monkeypatch.setattr(gui,"load_environment",lambda:())
    started=[]
    monkeypatch.setattr(gui.runner,"start",
                        lambda *a,**kw:started.append(a) or False)
    monkeypatch.setattr(messagebox,"showinfo",lambda *a,**kw:None)
    assert gui.run(["rejected"],"test") is False
    assert started==[(["rejected"],"test")]


def test_runner_cannot_start_next_job_until_tk_consumes_previous_done(
    monkeypatch
):
    """A completed thread can still have a queued result/hook in Tk.

    Starting an unrelated build at that point used to make its callback
    receive the older job's success exit code. It is a release/data-safety
    race, not merely a cosmetic busy-indicator problem.
    """
    import queue
    suite=_module()
    started=[]
    class FakeProcess:
        def __init__(self,*args,**kwargs):
            started.append(args)
            self.stdout=iter(["ready\n"])
        def wait(self):return 0
    monkeypatch.setattr(suite.workshop.subprocess,"Popen",FakeProcess)
    sink=queue.Queue()
    runner=suite.workshop.Runner(sink)
    assert runner.start(["first"],"first job")
    runner.thread.join(timeout=2)
    assert not runner.thread.is_alive()
    assert runner.busy  # GUI has not consumed first job's final event
    assert runner.start(["second"],"second job") is False
    assert len(started)==1
    events=[]
    while not sink.empty():
        events.append(sink.get_nowait())
    assert events[0]==("start","first job")
    assert events[-1]==("done",0)
    runner.acknowledge_completion()
    assert not runner.busy
    assert runner.start(["second"],"second job")
    runner.thread.join(timeout=2)
    assert len(started)==2
    assert sink.get_nowait()==("start","second job")
    assert sink.get_nowait()==("line","ready")
    assert sink.get_nowait()==("done",0)
    runner.acknowledge_completion()
    assert not runner.busy


def test_one_broken_completion_hook_cannot_stop_all_suite_event_handling():
    """A failed status/diagnostic refresh must not freeze later UI actions."""
    from queue import Queue
    suite=_module()
    q=Queue()
    q.put(("done",0))
    q.put(("line","next notification"))
    shown=[]
    received=[]
    def broken(_code):
        raise ValueError("invalid old report")
    def healthy(code):
        received.append(code)
    hooks=[broken,healthy]
    fake=SimpleNamespace(
        events=q,
        runner=SimpleNamespace(acknowledge_completion=lambda:received.append("ack")),
        done_hooks=hooks,
        log=lambda line,tag=None:shown.append((line,tag)),
        status_label=SimpleNamespace(configure=lambda **kw:None),
        stop_button=SimpleNamespace(state=lambda *a:None),
        refresh_status=lambda:None,
        after=lambda *a:received.append("scheduled"),
        _drain=lambda:None,
    )
    suite.workshop.Suite._drain(fake)
    assert received==["ack",0,"scheduled"]
    assert hooks==[healthy]  # broken handler detached; next run is safe
    assert any("invalid old report" in line for line,_ in shown)
    assert any("next notification" in line for line,_ in shown)


def test_invalid_captured_json_cannot_freeze_ui_or_authorize_success():
    """A zero-exit CLI with malformed JSON is NOT a successful data import."""
    from queue import Queue
    suite=_module()
    q=Queue()
    q.put(("captured",(0,"{broken json")))
    q.put(("done",0))
    q.put(("line","next event was still processed"))
    outcome,logs,ack=[],[],[]
    def parse_json(_code,text):
        import json
        json.loads(text)
    fake=SimpleNamespace(
        events=q,
        runner=SimpleNamespace(acknowledge_completion=lambda:ack.append(True)),
        _capture_sink=parse_json,
        _capture_error=None,
        done_hooks=[lambda code:outcome.append(code)],
        log=lambda msg,tag=None:logs.append((msg,tag)),
        status_label=SimpleNamespace(configure=lambda **kw:None),
        stop_button=SimpleNamespace(state=lambda _state:None),
        refresh_status=lambda:None,
        after=lambda *_args:outcome.append("poll-rescheduled"),
        _drain=lambda:None,
    )
    suite.workshop.Suite._drain(fake)
    assert ack==[True]
    assert outcome==[1,"poll-rescheduled"]
    assert fake._capture_sink is None and fake._capture_error is None
    assert any("Werkzeugantwort nicht auswertbar" in line for line,_ in logs)
    assert any("Datenerwerb fehlgeschlagen" in line for line,_ in logs)
    assert any("next event was still processed" in line for line,_ in logs)


def test_valid_captured_json_preserves_success_exit_code():
    from queue import Queue
    import json
    suite=_module()
    q=Queue()
    q.put(("captured",(0,'{"sprites": 3}')))
    q.put(("done",0))
    parsed,finished=[],[]
    fake=SimpleNamespace(
        events=q,
        runner=SimpleNamespace(acknowledge_completion=lambda:None),
        _capture_sink=lambda code,text:parsed.append((code,json.loads(text))),
        _capture_error=None,
        done_hooks=[finished.append],
        log=lambda *_args:None,
        status_label=SimpleNamespace(configure=lambda **kw:None),
        stop_button=SimpleNamespace(state=lambda _state:None),
        refresh_status=lambda:None,
        after=lambda *_args:None,
        _drain=lambda:None,
    )
    suite.workshop.Suite._drain(fake)
    assert parsed==[(0,{"sprites":3})]
    assert finished==[0]
    assert fake._capture_error is None

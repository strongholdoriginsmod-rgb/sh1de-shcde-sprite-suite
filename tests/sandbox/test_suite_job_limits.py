"""Runner/console limits and correctness under high-volume fake CLI output."""
from __future__ import annotations
import importlib.machinery
import importlib.util
from pathlib import Path
import queue
import sys
import time
import tkinter as tk
from types import SimpleNamespace

import pytest

ROOT=Path(__file__).resolve().parents[2]


def _source():
    loader=importlib.machinery.SourceFileLoader("suite_job_test",str(ROOT/"tools"/"suite.pyw"))
    spec=importlib.util.spec_from_loader(loader.name,loader)
    module=importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_worker_uses_bounded_gui_queue_and_keeps_local_complete_log(
    tmp_path,monkeypatch,
):
    suite=_source()
    sample=[f"result {n}\n" for n in range(5000)]
    class Process:
        def __init__(self,*args,**kw):
            self.stdout=iter(sample)
        def wait(self):
            return 0
    monkeypatch.setattr(suite.subprocess,"Popen",Process)
    events=queue.Queue(maxsize=3)
    logs=tmp_path/"tool-logs"
    runner=suite.Runner(events,log_directory=logs)
    assert runner.start(["synthetic"],"Synthetic job")
    received=[]
    deadline=time.monotonic()+10
    while time.monotonic()<deadline:
        kind,payload=events.get(timeout=2)
        received.append((kind,payload))
        if kind=="done":
            break
    runner.thread.join(1)
    assert not runner.thread.is_alive()
    assert received[-1]==("done",0)
    assert any("ausgelassen" in str(payload) for kind,payload in received if kind=="line")
    assert runner.last_log_path is not None and runner.last_log_path.is_file()
    text=runner.last_log_path.read_text("utf8")
    assert text.startswith("result 0\n")
    assert text.endswith("result 4999\n")
    runner.acknowledge_completion()


def test_capture_size_limit_refuses_success_not_success_callback(monkeypatch):
    suite=_source()
    class Process:
        def __init__(self,*args,**kw):
            self.stdout=iter(["1234567\n"]*200)
        def wait(self):
            return 0
    monkeypatch.setattr(suite.subprocess,"Popen",Process)
    q=queue.Queue()
    runner=suite.Runner(q)
    runner.MAX_CAPTURE_CHARS=120
    assert runner.start(["synthetic"],"Synthetic capture",capture=True)
    runner.thread.join(3)
    events=list(q.queue)
    assert any("8 MiB" in str(value) for kind,value in events if kind=="line")
    assert any(code==1 and result=="" for code,result in
               (payload for kind,payload in events if kind=="captured"))
    assert events[-1]==("done",1)
    runner.acknowledge_completion()


def test_event_drain_is_bounded_and_can_resume_next_cycle():
    suite=_source()
    q=queue.Queue()
    for i in range(500):
        q.put(("line",f"line {i}"))
    calls=[]
    fake=SimpleNamespace(
        events=q,log=lambda text,tag=None:calls.append(("line",text)),
        after=lambda delay,callback:calls.append(("after",delay)),
        _drain=lambda:None
    )
    suite.Suite._drain(fake)
    assert q.qsize()==320
    assert sum(c[0]=="line" for c in calls)==180
    assert sum(c[0]=="after" for c in calls)==1


def test_visible_tk_log_is_trimmed_but_ends_with_latest_message():
    suite=_source()
    root=tk.Tk()
    root.withdraw()
    try:
        console=tk.Text(root)
        fake=SimpleNamespace(console=console,_display_line_count=0)
        for n in range(3500):
            suite.Suite.log(fake,f"Test {n}")
        assert fake._display_line_count<=3000
        body=console.get("1.0","end-1c")
        assert "Test 3499" in body
        assert "Test 0" not in body
    finally:
        root.destroy()

"""Detached Windows GUI launch must prove readiness, not just successful spawn."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import sys
import threading
import time

from suite_launch_status import announce_ready, await_ready


def test_startup_marker_is_bound_to_child_pid_and_correct_schema(tmp_path):
    marker=tmp_path/"ready.json"
    announce_ready(marker,12345)
    data=json.loads(marker.read_text("utf8"))
    assert data=={"schema":1,"ready":True,"pid":12345}
    good=SimpleNamespace(pid=12345,poll=lambda:None)
    bad=SimpleNamespace(pid=9999,poll=lambda:2)
    assert await_ready(good,marker,timeout=0.2)==(True,"GUI_READY=1")
    is_ready,reason=await_ready(bad,marker,timeout=0.2)
    assert not is_ready and "exit=2" in reason


def test_real_async_marker_arrival_is_detected(tmp_path):
    marker=tmp_path/"ready.json"
    process=SimpleNamespace(pid=678,poll=lambda:None)
    worker=threading.Thread(target=lambda:(
        time.sleep(0.03),announce_ready(marker,678)))
    worker.start()
    try:
        assert await_ready(process,marker,timeout=1)[0] is True
    finally:
        worker.join()


def test_early_child_crash_is_not_a_success(tmp_path):
    marker=tmp_path/"ready.json"
    process=SimpleNamespace(pid=100,poll=lambda:21)
    status,detail=await_ready(process,marker,timeout=.1)
    assert status is False
    assert "exit=21" in detail


def test_launcher_requires_real_child_readiness(tmp_path,monkeypatch):
    import suite_start as starter
    from suite_launch_status import announce_ready
    monkeypatch.setattr(starter,"PROJECT",tmp_path)
    monkeypatch.setattr(starter,"PYTHON_HOME",tmp_path/"python")
    monkeypatch.setattr(starter,"VENV",tmp_path/".venv")
    monkeypatch.setattr(starter,"fix_venv",lambda:None)
    monkeypatch.setattr(starter,"fix_toolchains",lambda:None)
    monkeypatch.setattr(starter,"find_dotnet_sdk",lambda _:None)
    monkeypatch.setattr(starter.sys,"argv",["suite_start.py"])
    class FakeProcess:
        pid=4321
        def __init__(self,args,**kwargs):
            assert args[-2]=="--startup-ready-file"
            announce_ready(Path(args[-1]),self.pid)
        def poll(self):
            return None
    monkeypatch.setattr(starter.subprocess,"Popen",FakeProcess)
    assert starter.main()==0


def test_launcher_returns_failure_when_child_crashes(tmp_path,monkeypatch):
    import suite_start as starter
    monkeypatch.setattr(starter,"PROJECT",tmp_path)
    monkeypatch.setattr(starter,"PYTHON_HOME",tmp_path/"python")
    monkeypatch.setattr(starter,"VENV",tmp_path/".venv")
    monkeypatch.setattr(starter,"fix_venv",lambda:None)
    monkeypatch.setattr(starter,"fix_toolchains",lambda:None)
    monkeypatch.setattr(starter,"find_dotnet_sdk",lambda _:None)
    monkeypatch.setattr(starter.sys,"argv",["suite_start.py"])
    class FakeProcess:
        pid=789
        def __init__(self,args,**kwargs):
            marker=Path(args[-1])
            marker.with_suffix(".error.txt").write_text(
                "synthetic safe trace",encoding="utf8")
        def poll(self):
            return 7
    monkeypatch.setattr(starter.subprocess,"Popen",FakeProcess)
    assert starter.main()==5
    logs=list((tmp_path/"work"/"logs"/"startup-errors").glob("*.log"))
    assert len(logs)==1
    assert logs[0].read_text("utf8")=="synthetic safe trace"

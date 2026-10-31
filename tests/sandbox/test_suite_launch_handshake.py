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
        pid=4321  # Windows venv redirector process, not the Tk interpreter.
        def __init__(self,args,**kwargs):
            assert "--startup-ready-file" in args
            assert "--startup-ready-token" in args
            marker=Path(args[args.index("--startup-ready-file")+1])
            token=args[args.index("--startup-ready-token")+1]
            assert len(token)==32
            announce_ready(marker,9876,nonce=token)  # Actual GUI child differs.
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
            marker=Path(args[args.index("--startup-ready-file")+1])
            marker.with_suffix(".error.txt").write_text(
                "synthetic safe trace",encoding="utf8")
        def poll(self):
            return 7
    monkeypatch.setattr(starter.subprocess,"Popen",FakeProcess)
    assert starter.main()==5
    logs=list((tmp_path/"work"/"logs"/"startup-errors").glob("*.log"))
    assert len(logs)==1
    assert logs[0].read_text("utf8")=="synthetic safe trace"


def test_nonce_handshake_accepts_redirected_gui_pid_without_weakening_identity(tmp_path):
    marker=tmp_path/"nonce-ready.json"
    nonce="9"*32
    announce_ready(marker,8088,nonce=nonce)
    parent=SimpleNamespace(pid=1007,poll=lambda:None)
    assert await_ready(parent,marker,nonce=nonce,timeout=.2)==(True,"GUI_READY=1")
    # A stale marker, wrong nonce or absent nonce cannot claim this launch.
    crashed=SimpleNamespace(pid=1007,poll=lambda:4)
    assert await_ready(crashed,marker,nonce="8"*32,timeout=.2)[0] is False
    assert await_ready(crashed,marker,timeout=.2)[0] is False


def test_invalid_or_malformed_startup_tokens_are_rejected(tmp_path):
    marker=tmp_path/"invalid.json"
    for nonce in ("", "not-a-nonce", "q"*32, "1"*31):
        try:
            announce_ready(marker,100,nonce=nonce)
        except ValueError:
            pass
        else:
            raise AssertionError("Invalid nonce was accepted: "+repr(nonce))
    assert not marker.exists()


def test_tampered_marker_nonce_cannot_authorize_gui(tmp_path):
    marker=tmp_path/"ready.json"
    announce_ready(marker,2468,nonce="1"*32)
    result=json.loads(marker.read_text("utf8"))
    result["nonce"]="2"*32
    marker.write_text(json.dumps(result),encoding="utf8")
    child=SimpleNamespace(pid=2468,poll=lambda:22)
    ok,detail=await_ready(child,marker,nonce="1"*32,timeout=.2)
    assert not ok and "exit=22" in detail


def test_real_python_subprocess_nonce_handshake(tmp_path):
    """Proof travels from a real child interpreter, not a mocked function."""
    import os
    import subprocess
    marker=tmp_path/"subprocess-ready.json"
    script=tmp_path/"announce.py"
    script.write_text(
        "from pathlib import Path\n"
        "import os,sys,time\n"
        "from suite_launch_status import announce_ready\n"
        "announce_ready(Path(sys.argv[1]),os.getpid(),nonce=sys.argv[2])\n"
        "time.sleep(1.0)\n",
        encoding="utf8",
    )
    nonce="a"*32
    env=os.environ.copy()
    tools=Path(__file__).resolve().parents[2]/"tools"
    env["PYTHONPATH"]=str(tools)+os.pathsep+env.get("PYTHONPATH","")
    env["PYTHONDONTWRITEBYTECODE"]="1"
    child=subprocess.Popen(
        [sys.executable,str(script),str(marker),nonce],env=env,
        stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,
        creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0),
    )
    try:
        assert await_ready(child,marker,nonce=nonce,timeout=5)==(True,"GUI_READY=1")
        assert json.loads(marker.read_text("utf8"))["nonce"]==nonce
    finally:
        child.wait(timeout=5)

"""Tracked build completion uses real Tk controls, never Unity or installer."""
from __future__ import annotations

import importlib.machinery
import importlib.util
from pathlib import Path
import sys
import time
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT/"tools") not in sys.path:
    sys.path.insert(0, str(ROOT/"tools"))


def _suite():
    loader=importlib.machinery.SourceFileLoader(
        "suite_build_completion_gui",str(ROOT/"tools"/"suite_universal.pyw")
    )
    spec=importlib.util.spec_from_loader(loader.name,loader)
    module=importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture
def gui(tmp_path,monkeypatch):
    import stronghold_europe_de.workspace_lock as locks
    monkeypatch.setattr(
        locks,"lock_path",lambda _root,_name:tmp_path/"build-result-gui.lock"
    )
    suite=_suite()
    monkeypatch.setattr(suite,"SETTINGS",tmp_path/"suite-settings.json")
    import stronghold_europe_de.suite_build_history as journal
    real_actions=(
        journal.append_started, journal.append_completed,
        journal.read_build_history
    )
    # This GUI fixture must never create events in the real project. Journal
    # bytes are exercised independently in tmp_path by unit tests.
    monkeypatch.setattr(journal,"read_build_history",lambda root:[])
    monkeypatch.setattr(
        journal,"append_started",
        lambda root,profile,before,*,replace,source_hashes=None:"a"*32
    )
    monkeypatch.setattr(journal,"append_completed",lambda *args:tmp_path/"fake-event.json")
    monkeypatch.setattr(journal,"append_launch_failed",lambda *args:tmp_path/"fake-event.json")
    monkeypatch.setattr(journal,"append_inspection_failed",lambda *args:tmp_path/"fake-event.json")
    try:
        app=suite.Universal()
    except tk.TclError as exc:
        pytest.skip(str(exc))
    app.sandbox_tab.ensure_studio=lambda:None
    app._real_history_actions=real_actions
    try:
        yield app
    finally:
        app.destroy()


def _fake_before(profile,output):
    from stronghold_europe_de.suite_build_completion import SCHEMA
    return {
        "schema":SCHEMA,"profile_id":profile,"output":str(output),
        "prior_manifest_sha256":None,"prior_output_exists":False,
    }


def _fake_result(profile, *, state="offline_ok",exit_code=0):
    from stronghold_europe_de.suite_build_completion import SCHEMA
    return {
        "schema":SCHEMA,"profile_id":profile,
        "output":str(ROOT/"dist"/profile/"StrongholdEuropeDE"),
        "state":state,"detail":"Separate SHA-256-Prüfung erfolgreich" if state=="offline_ok"
        else "Build or validator failed",
        "exit_code":exit_code,
        "verified_files":154 if state=="offline_ok" else 0,
        "verified_bytes":675908516 if state=="offline_ok" else 0,
        "errors":0 if state=="offline_ok" else 1,
        "warnings":0,"manifest_sha256":"e"*64 if state=="offline_ok" else None,
        "same_manifest_as_before":False,
        "issues":["Build/Validator stopped"] if state!="offline_ok" else [],
        "offline_integrity_ok":state=="offline_ok",
        "release_approved":False,"ingame_approved":False,
        "installation_performed":False,"no_output_written_by_audit":True,
    }


def _spin(app):
    deadline=time.monotonic()+5
    while app._build_completion_pending is not None and time.monotonic()<deadline:
        app.update()
        time.sleep(.02)
    assert app._build_completion_pending is None


def _mock_start(monkeypatch, app):
    import stronghold_europe_de.suite_build_completion as completion
    started=[]
    monkeypatch.setattr(
        completion,"capture_build_before",
        lambda root,profile,output:_fake_before(profile,output)
    )
    monkeypatch.setattr(app,"tool",lambda *args:started.append(args))
    return started


def test_actual_result_ui_is_tied_to_one_cli_completion_and_ingame_stays_open(
    gui,monkeypatch
):
    import stronghold_europe_de.suite_build_completion as completion
    app=gui
    app.open_tab(app.bc7_page)
    app.update()
    calls=[]
    started=_mock_start(monkeypatch,app)
    monkeypatch.setattr(
        completion,"inspect_completed_build",
        lambda root,profile,output,*,exit_code,before:
            calls.append((profile,exit_code,before)) or _fake_result(profile)
    )
    profile="sprite-suite-world-bc7-v2"
    snapshot=(profile,False,None,None,None,None)
    app._launch_tracked_build(snapshot,{"output_target":str(
        ROOT/"dist"/profile/"StrongholdEuropeDE"
    )})
    assert len(started)==1
    assert started[0][0]=="suite_workflow.py"
    assert app._build_session is not None
    assert str(app.build_result_button["state"])=="disabled"
    hooks=list(app.done_hooks)
    hook=hooks[-1]
    hook(0)
    assert hook not in app.done_hooks
    assert app._build_session is None
    _spin(app)
    assert len(calls)==1 and calls[0][0:2]==(profile,0)
    assert "OFFLINE SHA-256 OK" in app.build_result_status.get()
    assert "Ingame-Abnahme AUSSTEHEND" in app.build_result_status.get()
    assert str(app.build_result_button["state"])=="normal"
    assert app._build_last_result["release_approved"] is False
    app.show_build_result()
    dialogs=[w for w in app.winfo_children() if isinstance(w,tk.Toplevel)]
    assert dialogs
    dialog=dialogs[-1]
    app.update()
    # ScrolledText owns an internal Frame; inspect the nested Text instead
    # of assuming one direct child widget from Tk's wrapper implementation.
    nodes=[dialog]
    contents=[]
    while nodes:
        node=nodes.pop()
        nodes.extend(node.winfo_children())
        if isinstance(node,tk.Text):
            contents.append(node.get("1.0","end"))
    assert contents and any(
        "Ingame-Abnahme: AUSSTEHEND" in item for item in contents
    )
    assert "Releasefreigabe: NEIN" in contents[0]
    assert "Automatische Installation: NEIN" in contents[0]
    dialog.destroy()


def test_failure_never_audits_old_output_or_looks_successful(gui,monkeypatch):
    import stronghold_europe_de.suite_build_completion as completion
    app=gui
    started=_mock_start(monkeypatch,app)
    called=[]
    def classify(root,profile,output,*,exit_code,before):
        called.append(exit_code)
        return _fake_result(profile,state="tool_failed",exit_code=exit_code)
    monkeypatch.setattr(completion,"inspect_completed_build",classify)
    profile="sprite-suite-world-bc7-v2"
    app._launch_tracked_build(
        (profile,True,None,None,None,None),
        {"output_target":str(ROOT/"dist"/profile/"StrongholdEuropeDE")},
    )
    app.done_hooks[-1](17)
    _spin(app)
    assert called==[17]
    assert "FEHLGESCHLAGEN" in app.build_result_status.get()
    assert app._build_last_result["verified_files"]==0
    assert "Ingame-Abnahme AUSSTEHEND" in app.build_result_status.get()
    assert started
    assert not app._build_last_result["offline_integrity_ok"]


def test_stale_prior_build_audit_never_overwrites_newer_ui_state(gui,monkeypatch):
    import stronghold_europe_de.suite_build_completion as completion
    app=gui
    _mock_start(monkeypatch,app)
    profile="sprite-suite-world-bc7-v2"
    old_result=_fake_result("first")
    new_result=_fake_result("second")
    # No stale queue can replace the currently active build generation.
    app._build_generation=4
    queue=__import__("queue").Queue()
    queue.put(("ok",3,old_result))
    app._build_completion_pending=queue
    app._poll_build_completion()
    assert app._build_last_result is None
    app._build_generation=5
    app._set_build_completion(new_result)
    assert "second" in app.build_result_status.get()


def test_build_start_exception_unhooks_completion_and_no_success(gui,monkeypatch):
    import stronghold_europe_de.suite_build_completion as completion
    app=gui
    monkeypatch.setattr(
        completion,"capture_build_before",
        lambda root,profile,output:_fake_before(profile,output)
    )
    def bad_launcher(*args):
        raise RuntimeError("Synthetic start failed")
    monkeypatch.setattr(app,"tool",bad_launcher)
    baseline=len(app.done_hooks)
    profile="sprite-suite-canary-bc7-v2"
    with pytest.raises(RuntimeError,match="Synthetic start"):
        app._launch_tracked_build(
            (profile,False,None,None,None,None),
            {"output_target":str(ROOT/"dist"/profile/"StrongholdEuropeDE")},
        )
    assert len(app.done_hooks)==baseline
    assert app._build_session is None
    assert str(app.build_result_button["state"])=="disabled"
    assert "Start des Werkzeugs fehlgeschlagen" in app.build_result_status.get()


def test_completion_label_always_names_actual_build_profile(gui):
    app=gui
    app.bc7_profile.set("sprite-suite-canary-bc7-v2")
    app._set_build_completion(_fake_result("sprite-suite-world-bc7-v2"))
    assert "sprite-suite-world-bc7-v2" in app.build_result_status.get()
    assert app.bc7_profile.get()=="sprite-suite-canary-bc7-v2"



def test_queued_previous_tool_completion_cannot_be_claimed_as_new_build(
    gui, monkeypatch
):
    import stronghold_europe_de.suite_build_completion as completion
    app=gui
    original=completion.capture_build_before
    monkeypatch.setattr(
        completion,"capture_build_before",
        lambda *args:pytest.fail("Must not start while old completion is queued")
    )
    monkeypatch.setattr(
        app,"tool",
        lambda *args:pytest.fail("Previous done event cannot start a new build")
    )
    notices=[]
    from tkinter import messagebox
    monkeypatch.setattr(
        messagebox,"showinfo",lambda *a,**kw:notices.append(a)
    )
    app.events.put(("done", 0))
    profile="sprite-suite-canary-bc7-v2"
    app._launch_tracked_build(
        (profile,False,None,None,None,None),
        {"output_target":str(ROOT/"dist"/profile/"StrongholdEuropeDE")},
    )
    assert notices and "vorherigen Werkzeugs" in notices[0][1]
    assert app._build_session is None
    assert str(app.build_result_button["state"])=="disabled"



def _spin_history(app):
    deadline=time.monotonic()+5
    while app._history_pending is not None and time.monotonic()<deadline:
        app.update()
        time.sleep(.02)
    assert app._history_pending is None


def test_session_completion_is_stored_in_temporary_journal_then_reloaded(
    gui, monkeypatch, tmp_path
):
    import stronghold_europe_de.suite_build_history as journal
    import stronghold_europe_de.suite_build_completion as completion
    app=gui
    app.update()
    _spin_history(app)
    profile="sprite-suite-world-bc7-v2"
    before=_fake_before(profile,ROOT/"dist"/profile/"StrongholdEuropeDE")
    actual_started,actual_completed,actual_reader=app._real_history_actions
    stored=[]
    monkeypatch.setattr(
        journal,"append_started",
        lambda root,profile,before,*,replace,source_hashes=None: (
            stored.append(("start",profile,replace)) or
            actual_started(
                tmp_path,profile,before,replace=replace,
                source_hashes=source_hashes,
            )
        )
    )
    monkeypatch.setattr(
        journal,"append_completed",
        lambda root,run,profile,result: (
            stored.append(("complete",profile,result["exit_code"])) or
            actual_completed(tmp_path,run,profile,result)
        )
    )
    monkeypatch.setattr(
        journal,"read_build_history",
        lambda root:actual_reader(tmp_path)
    )
    started=_mock_start(monkeypatch,app)
    monkeypatch.setattr(
        completion,"inspect_completed_build",
        lambda root,profile,output,*,exit_code,before:
        _fake_result(profile,exit_code=exit_code)
    )
    pinned={
        "profile_sha256": "1" * 64,
        "config_sha256": "2" * 64,
        "mapping_sha256": "3" * 64,
    }
    app._launch_tracked_build(
        (profile,False,None,None,None,None),
        {"output_target":before["output"], "source_hashes":pinned},
    )
    assert len(started)==1
    # The started but unfinished attempt is a persistent unconfirmed event.
    assert actual_reader(tmp_path)[0]["state"]=="unbestaetigt"
    app.done_hooks[-1](0)
    _spin(app)
    _spin_history(app)
    assert [item[0] for item in stored]==["start","complete"]
    persisted=actual_reader(tmp_path)
    assert len(persisted)==1
    assert persisted[0]["state"]=="offline_ok"
    assert persisted[0]["source_hashes"]==pinned
    assert persisted[0]["result"]["ingame_approved"] is False
    assert "1 Bauversuch" in app.build_history_status.get()
    assert "offline_ok" in app.build_history_status.get()
    assert len(list(
        (tmp_path/"work"/"reports"/"suite-build-history").glob("*.json")
    ))==2
    assert not (tmp_path/"dist").exists()


def test_saved_history_dialog_is_read_only_and_show_unconfirmed(
    gui, monkeypatch, tmp_path
):
    import stronghold_europe_de.suite_build_history as journal
    app=gui
    app.update()
    _spin_history(app)
    profile="sprite-suite-world-bc7-v2"
    before=_fake_before(profile,ROOT/"dist"/profile/"StrongholdEuropeDE")
    real_start,_real_complete,real_read=app._real_history_actions
    real_start(tmp_path,profile,before,replace=True)
    monkeypatch.setattr(journal,"read_build_history",lambda root:real_read(tmp_path))
    monkeypatch.setattr(app,"tool",
                        lambda *args:pytest.fail("History must never run a builder"))
    app.geometry("1020x680+20+20")
    app.open_tab(app.bc7_page)
    app.update()
    button=app.build_history_button
    assert button.winfo_ismapped()
    assert button.winfo_rootx()+button.winfo_width()<=(
        app.bc7_page.winfo_rootx()+app.bc7_page.winfo_width()
    )
    app.show_build_history()
    _spin_history(app)
    dialogs=[w for w in app.winfo_children() if isinstance(w,tk.Toplevel)]
    assert dialogs
    dialog=dialogs[-1]
    app.update()
    trees=[]
    texts=[]
    nodes=[dialog]
    while nodes:
        node=nodes.pop()
        nodes.extend(node.winfo_children())
        if isinstance(node,ttk.Treeview):
            trees.append(node)
        if isinstance(node,tk.Text):
            texts.append(node.get("1.0","end"))
    assert trees and len(trees[0].get_children())==1
    assert "unbestaetigt" in trees[0].item("0")["values"]
    assert texts and any(
        "KEIN verifizierter Abschluss gespeichert" in text
        and "HISTORISCHER BAUVERSUCH" in text
        and "Keine SHA-Quellenbindungen" in text
        for text in texts
    )
    assert "Ingame-Abnahme" in dialog.title() or "Releasefreigabe" in dialog.title()
    dialog.destroy()


def test_corrupt_local_history_never_claims_older_release(
    gui, monkeypatch
):
    import stronghold_europe_de.suite_build_history as journal
    app=gui
    app.update()
    _spin_history(app)
    def invalid_history(root):
        raise journal.BuildHistoryError("Record hash chain mismatch")
    monkeypatch.setattr(journal,"read_build_history",invalid_history)
    monkeypatch.setattr(
        app,"tool",
        lambda *args:pytest.fail("Bad history must never launch a tool")
    )
    app.refresh_build_history()
    _spin_history(app)
    assert not app._history_rows
    assert "nicht vertrauenswürdig" in app.build_history_status.get()
    assert "Record hash chain mismatch" in app.build_history_status.get()


def test_unwritable_history_blocks_the_build_before_any_cli(
    gui, monkeypatch
):
    import stronghold_europe_de.suite_build_history as journal
    import stronghold_europe_de.suite_build_completion as completion
    from tkinter import messagebox
    app=gui
    _mock_start(monkeypatch,app)
    monkeypatch.setattr(
        journal,"append_started",
        lambda *args,**kwargs:(_ for _ in ()).throw(
            journal.BuildHistoryError("tampered journal")
        )
    )
    monkeypatch.setattr(
        app,"tool",
        lambda *args:pytest.fail("Cannot build without safe journal write")
    )
    warnings=[]
    monkeypatch.setattr(
        messagebox,"showwarning",
        lambda *args,**kwargs:warnings.append(args)
    )
    profile="sprite-suite-world-bc7-v2"
    app._launch_tracked_build(
        (profile,False,None,None,None,None),
        {"output_target":str(ROOT/"dist"/profile/"StrongholdEuropeDE")},
    )
    assert not app._build_session
    assert warnings
    assert "tampered journal" in warnings[0][1]
    assert "nicht sicher überprüfbar" in app.readiness_status.get()

"""Build-readiness widget: actionable results, no build or game access."""
from __future__ import annotations

import importlib.machinery
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import sys
import time
import tkinter as tk
from tkinter import messagebox, ttk

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT/"tools") not in sys.path:
    sys.path.insert(0,str(ROOT/"tools"))


def _suite():
    loader=importlib.machinery.SourceFileLoader(
        "suite_build_readiness_gui_fixture",
        str(ROOT/"tools"/"suite_universal.pyw")
    )
    spec=importlib.util.spec_from_loader(loader.name,loader)
    module=importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture
def app_fixture(tmp_path,monkeypatch):
    import stronghold_europe_de.workspace_lock as locks
    monkeypatch.setattr(
        locks, "lock_path",
        lambda _root,_name:tmp_path/"readiness-gui-instance.lock",
    )
    suite=_suite()
    monkeypatch.setattr(suite,"SETTINGS",tmp_path/"suite-user-settings.json")
    # Language is initialized at import from the *user's* global settings.
    # This suite intentionally asserts German UI. Never let a previous
    # test/user setting silently change expected labels mid-run.
    monkeypatch.setattr(suite.LANG,"code","de")
    import stronghold_europe_de.suite_build_history as journal
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
        # This UI is shipped for Windows. Missing/corrupted Tk libraries
        # must fail desktop acceptance rather than hide behind a skip.
        if sys.platform == "win32":
            raise
        pytest.skip(str(exc))
    app.sandbox_tab.ensure_studio=lambda:None
    try:
        yield suite,app
    finally:
        app.destroy()


def _result(profile,blockers):
    return {
        "schema":"stronghold-europe.suite-build-readiness.v1",
        "profile_id":profile,"blocker_count":blockers,
        "notice_count":1,"ready_for_attempt":not blockers,
        "checks":[
            {
                "name":"Profil","state":"ok","detail":"gültig",
                "next_step":"Keine Aktion",
            },
            {
                "name":"Unity-BC7","state":"blockiert" if blockers else "ok",
                "detail":"Version fehlt" if blockers else "Pin stimmt",
                "next_step":"Einrichten" if blockers else "Keine Aktion",
            },
        ],
        "build_executed":False,"release_certified":False,
        "output_target":str(ROOT/"dist"/profile/"StrongholdEuropeDE"),
    }


def _pump(app):
    # This executes inside the same process as resource-heavy Qt/map tests
    # on Windows. Five seconds can elapse while the test GUI pumps other
    # pending Tk events, despite a healthy background readiness worker.
    # Keep the test strict about eventual completion and the build gate.
    deadline=time.monotonic()+20
    while app._readiness_pending is not None and time.monotonic()<deadline:
        app.update()
        time.sleep(.02)
    assert app._readiness_pending is None


def test_readiness_is_visible_and_async_and_does_not_build(
    app_fixture,monkeypatch
):
    import stronghold_europe_de.suite_build_readiness as api
    suite,app=app_fixture
    app.geometry("1020x680+30+30")
    app.open_tab(app.bc7_page)
    app.update()
    assert app.readiness_button.winfo_ismapped()
    assert app.readiness_button.winfo_width()>100
    assert app.readiness_button.winfo_rootx() + app.readiness_button.winfo_width() <= (
        app.bc7_page.winfo_rootx()+app.bc7_page.winfo_width()
    )
    called=[]
    created=[]
    monkeypatch.setattr(app,"_present_build_readiness",
                        lambda item:created.append(item))
    monkeypatch.setattr(app,"tool",
                        lambda *args:pytest.fail("Readiness must not run builder or installer"))
    def fake_audit(root,profile,*,replace,unity_hint,dotnet_hint,
                   source_hint,target_hint):
        called.append((root,profile,replace,unity_hint,dotnet_hint))
        time.sleep(.05)
        return _result(profile,3)
    monkeypatch.setattr(api,"audit_build_readiness",fake_audit)
    app.bc7_profile.set("sprite-suite-world-bc7-v2")
    app.check_build_readiness()
    assert str(app.readiness_button["state"])=="disabled"
    app.check_build_readiness()
    _pump(app)
    assert len(called)==1
    assert called[0][0]==suite.ROOT
    assert called[0][1]=="sprite-suite-world-bc7-v2"
    assert len(created)==1
    assert created[0]["blocker_count"]==3
    assert "3 Blockaden" in app.readiness_status.get()
    assert str(app.readiness_button["state"])=="normal"


def test_readiness_selection_change_never_presents_stale_result(
    app_fixture,monkeypatch
):
    import stronghold_europe_de.suite_build_readiness as api
    _,app=app_fixture
    shown=[]
    monkeypatch.setattr(app,"_present_build_readiness",
                        lambda item:shown.append(item))
    def audit(root,profile,*,replace,unity_hint,dotnet_hint,
              source_hint,target_hint):
        time.sleep(.05)
        return _result(profile,0)
    monkeypatch.setattr(api,"audit_build_readiness",audit)
    app.check_build_readiness()
    app.replace.set(True)
    _pump(app)
    assert not shown
    assert "erneut prüfen" in app.readiness_status.get()
    app.check_build_readiness()
    _pump(app)
    assert len(shown)==1
    assert "keine Releasefreigabe" in app.readiness_status.get()


def test_readiness_refuses_to_start_when_runner_is_busy(
    app_fixture,monkeypatch
):
    _,app=app_fixture
    messages=[]
    monkeypatch.setattr(messagebox,"showinfo",
                        lambda *args,**kwargs:messages.append((args,kwargs)))
    runner=app.runner
    app.runner=SimpleNamespace(busy=True)
    try:
        app.check_build_readiness()
    finally:
        app.runner=runner
    assert app._readiness_pending is None
    assert messages and "anderes Werkzeug" in messages[0][0][1]


def test_report_dialog_has_actionable_setup_and_close_buttons(app_fixture):
    _,app=app_fixture
    app._present_build_readiness(_result("sprite-suite-world-bc7-v2",2))
    dialogs=[w for w in app.winfo_children() if isinstance(w,tk.Toplevel)]
    assert dialogs
    dialog=dialogs[-1]
    app.update()
    assert "keine Releasefreigabe" in dialog.title()
    buttons=[]
    stack=[dialog]
    while stack:
        widget=stack.pop()
        stack.extend(widget.winfo_children())
        if isinstance(widget,ttk.Button):
            buttons.append(widget.cget("text"))
    assert "Zu Einrichten" in buttons
    assert "Schließen" in buttons
    dialog.destroy()



def test_build_button_rejects_blockers_without_running_builder(
    app_fixture,monkeypatch
):
    import stronghold_europe_de.suite_build_readiness as api
    _,app=app_fixture
    seen=[]
    warnings=[]
    monkeypatch.setattr(api,"audit_build_readiness",
                        lambda root,profile,**kwargs:_result(profile,3))
    monkeypatch.setattr(app,"tool",
                        lambda *args:pytest.fail("Blocked build must not start"))
    monkeypatch.setattr(
        messagebox,"askyesno",
        lambda *args,**kwargs:pytest.fail("Blocked build must not request launch"),
    )
    monkeypatch.setattr(app,"_present_build_readiness",lambda x:seen.append(x))
    app.build_profile()
    assert app._readiness_intent=="build"
    assert str(app.build_button["state"])=="disabled"
    _pump(app)
    assert str(app.build_button["state"])=="normal"
    assert len(seen)==1
    assert seen[0]["blocker_count"]==3
    assert "Bauversuch noch nicht möglich" in app.readiness_status.get()


def test_ready_build_must_be_confirmed_and_validation_rechecked(
    app_fixture,monkeypatch
):
    import stronghold_europe_de.suite_build_readiness as api
    _,app=app_fixture
    api_calls=[]
    rechecks=[]
    launches=[]
    prompts=[]
    monkeypatch.setattr(api,"audit_build_readiness",
                        lambda root,profile,**kwargs:api_calls.append(
                            (root,profile,kwargs)
                        ) or _result(profile,0))
    monkeypatch.setattr(
        api,"recheck_build_readiness_before_start",
        lambda root,profile,*,replace,report:rechecks.append(
            (root,profile,replace,report)
        ),
    )
    import stronghold_europe_de.suite_build_completion as completion
    monkeypatch.setattr(
        completion, "capture_build_before",
        lambda root,profile,output:{
            "schema":completion.SCHEMA, "profile_id":profile,
            "output":str(output),
            "prior_manifest_sha256":None,
            "prior_output_exists":False,
        }
    )
    monkeypatch.setattr(app,"tool",lambda *args:launches.append(args))
    def confirmed(*args,**kwargs):
        prompts.append((args,kwargs))
        return len(prompts)>1  # first time user cancels
    monkeypatch.setattr(messagebox,"askyesno",confirmed)
    app.bc7_profile.set("sprite-suite-world-bc7-v2")
    app.replace.set(True)

    app.build_profile()
    _pump(app)
    assert prompts[0][1]["default"]=="no"
    assert prompts[0][1]["icon"]=="warning"
    assert "Bestehende Paketausgabe ersetzen: JA" in prompts[0][0][1]
    assert not rechecks and not launches
    assert "abgebrochen" in app.readiness_status.get()

    app.build_profile()
    _pump(app)
    assert len(api_calls)==2 and len(prompts)==2
    assert len(rechecks)==1
    assert rechecks[0][1:3]==("sprite-suite-world-bc7-v2",True)
    assert launches==[
        ("suite_workflow.py",
         ["build","--profile-id","sprite-suite-world-bc7-v2","--replace"])
    ]
    assert "Bauauftrag" in app.readiness_status.get()


def test_ready_build_is_refused_when_selection_changes_in_confirmation(
    app_fixture,monkeypatch
):
    import stronghold_europe_de.suite_build_readiness as api
    _,app=app_fixture
    monkeypatch.setattr(api,"audit_build_readiness",
                        lambda root,profile,**kwargs:_result(profile,0))
    monkeypatch.setattr(api,"recheck_build_readiness_before_start",
                        lambda *a,**kw:pytest.fail("Changed form must not recheck"))
    monkeypatch.setattr(app,"tool",
                        lambda *args:pytest.fail("Changed form must not build"))
    def mutate_form(*args,**kwargs):
        app.replace.set(not app.replace.get())
        return True
    monkeypatch.setattr(messagebox,"askyesno",mutate_form)
    app.build_profile()
    _pump(app)
    assert "Auswahl nach Bestätigung geändert" in app.readiness_status.get()


def test_ready_build_is_blocked_if_inputs_change_during_confirmation(
    app_fixture,monkeypatch
):
    import stronghold_europe_de.suite_build_readiness as api
    _,app=app_fixture
    monkeypatch.setattr(api,"audit_build_readiness",
                        lambda root,profile,**kwargs:_result(profile,0))
    def changed_sources(*args,**kwargs):
        raise api.BuildReadinessError("Mapping seit Prüfung geändert")
    monkeypatch.setattr(api,"recheck_build_readiness_before_start",
                        changed_sources)
    monkeypatch.setattr(messagebox,"askyesno",lambda *args,**kwargs:True)
    warnings=[]
    monkeypatch.setattr(messagebox,"showwarning",
                        lambda *args,**kwargs:warnings.append((args,kwargs)))
    monkeypatch.setattr(app,"tool",
                        lambda *args:pytest.fail("Stale sources must block builder"))
    app.build_profile()
    _pump(app)
    assert warnings
    assert "Mapping seit Prüfung geändert" in warnings[0][0][1]
    assert "blockiert" in app.readiness_status.get()


def test_build_click_while_readiness_active_does_not_start_another_worker(
    app_fixture,monkeypatch
):
    import stronghold_europe_de.suite_build_readiness as api
    _,app=app_fixture
    counts=[]
    def audit(root,profile,**kwargs):
        counts.append(profile)
        time.sleep(.08)
        return _result(profile,0)
    monkeypatch.setattr(api,"audit_build_readiness",audit)
    monkeypatch.setattr(app,"_present_build_readiness",lambda *a:None)
    monkeypatch.setattr(app,"tool",
                        lambda *args:pytest.fail("No builder should start"))
    messages=[]
    monkeypatch.setattr(messagebox,"showinfo",
                        lambda *args,**kwargs:messages.append(args))
    app.check_build_readiness()
    app.build_profile()
    assert messages and "läuft bereits" in messages[0][1]
    _pump(app)
    assert len(counts)==1


def test_ready_build_refuses_runner_started_during_confirmation(
    app_fixture,monkeypatch
):
    import stronghold_europe_de.suite_build_readiness as api
    _,app=app_fixture
    monkeypatch.setattr(api,"audit_build_readiness",
                        lambda root,profile,**kwargs:_result(profile,0))
    monkeypatch.setattr(app,"tool",
                        lambda *args:pytest.fail("Other busy worker must block launch"))
    monkeypatch.setattr(api,"recheck_build_readiness_before_start",
                        lambda *a,**kw:pytest.fail("No recheck while runner busy"))
    messages=[]
    monkeypatch.setattr(messagebox,"showinfo",
                        lambda *args,**kwargs:messages.append(args))
    current=app.runner
    synthetic=SimpleNamespace(busy=False)
    def confirm(*args,**kwargs):
        synthetic.busy=True
        return True
    monkeypatch.setattr(messagebox,"askyesno",confirm)
    app.runner=synthetic
    try:
        app.build_profile()
        _pump(app)
    finally:
        app.runner=current
    assert messages and "anderes Werkzeug" in messages[0][1]



def test_unstored_source_or_target_change_invalidates_background_result(
    app_fixture,monkeypatch
):
    import stronghold_europe_de.suite_build_readiness as api
    _,app=app_fixture
    calls=[]
    shown=[]
    def fake_audit(root,profile,**kwargs):
        calls.append(kwargs)
        time.sleep(.06)
        return _result(profile,0)
    monkeypatch.setattr(api,"audit_build_readiness",fake_audit)
    monkeypatch.setattr(app,"_present_build_readiness",
                        lambda report:shown.append(report))
    monkeypatch.setattr(app,"tool",
                        lambda *args:pytest.fail("Changing a game path cannot launch a build"))
    app.check_build_readiness()
    app.source.set("Z:/not-saved-game-folder")
    _pump(app)
    assert len(calls)==1
    assert not shown
    assert "erneut prüfen" in app.readiness_status.get()
    app.check_build_readiness()
    _pump(app)
    assert len(shown)==1
    assert len(calls)==2
    assert calls[-1]["source_hint"]=="Z:/not-saved-game-folder"


def test_build_button_layout_fits_small_window(app_fixture):
    _,app=app_fixture
    app.geometry("1020x680+20+20")
    app.open_tab(app.bc7_page)
    app.update()
    assert app.build_button.winfo_ismapped()
    assert app.readiness_button.winfo_ismapped()
    bounds=(
        app.bc7_page.winfo_rootx(),
        app.bc7_page.winfo_rootx()+app.bc7_page.winfo_width(),
    )
    for control in (app.build_button,app.readiness_button):
        assert bounds[0]<=control.winfo_rootx()
        assert control.winfo_rootx()+control.winfo_width()<=bounds[1]


def test_report_dialog_english_never_mixes_german_heading_and_actions(
    app_fixture
):
    suite,app=app_fixture
    suite.LANG.code="en"
    app.language.set("EN")
    app._present_build_readiness(_result("sprite-suite-world-bc7-v2",2))
    dialog=[w for w in app.winfo_children() if isinstance(w,tk.Toplevel)][-1]
    app.update()
    try:
        assert dialog.title()=="Build readiness – not a release approval"
        stack=[dialog]
        buttons=[]
        reports=[]
        while stack:
            w=stack.pop()
            stack.extend(w.winfo_children())
            if isinstance(w,ttk.Button):
                buttons.append(w.cget("text"))
            if isinstance(w,tk.Text):
                reports.append(w.get("1.0","end"))
        assert "Go to setup" in buttons
        assert "Close" in buttons
        assert "Schließen" not in buttons
        assert any(
            "This check does not change profiles, game, cache or packages."
            in item for item in reports
        )
    finally:
        dialog.destroy()

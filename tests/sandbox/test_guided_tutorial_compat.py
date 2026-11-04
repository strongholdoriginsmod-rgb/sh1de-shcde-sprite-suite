"""Safe, contextual onboarding and honest Windows compatibility contracts."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/"tools"),str(ROOT/"src")]

from suite_guided_tutorial import (BY_KEY,TRACKS,ProgressStore,
                                   open_guided_tutorial)
from suite_compatibility_preflight import collect,_dependencies


def test_tracks_include_workflows_with_no_automatic_operations():
    assert len(TRACKS)>=5
    assert len(BY_KEY)==len(TRACKS)
    assert all(len(track.steps)>=3 for track in TRACKS)
    assert {t.key for t in TRACKS}>={
       "quickstart","layout","preview","demo","compat"}
    assert all(step.title_en and step.body_en and step.title_de and step.body_de
       for track in TRACKS for step in track.steps)


def test_progress_store_roundtrip_is_atomic_and_confined(tmp_path):
    path=tmp_path/"localized ümlaut"/"guide-progress.json"
    store=ProgressStore(path)
    assert store.load()=={}
    assert store.save({"quickstart":4,"layout":999,"untrusted":400})
    value=json.loads(path.read_text(encoding="utf-8"))
    assert value["schema"]=="sprite-suite.guide-progress.v1"
    assert "untrusted" not in value["steps"]
    assert store.load()=={"quickstart":4,"layout":len(BY_KEY["layout"].steps)-1}
    path.write_text("not valid json",encoding="utf-8")
    assert store.load()=={}


def test_progress_store_does_not_follow_symlink(tmp_path):
    link=tmp_path/"unsafe.json"
    original=tmp_path/"original.json"
    original.write_text("keep",encoding="utf-8")
    try:link.symlink_to(original)
    except (OSError,NotImplementedError):
        pytest.skip("Windows test account cannot create symbolic links")
    store=ProgressStore(link)
    assert not store.save({"quickstart":1})
    assert original.read_text(encoding="utf-8")=="keep"


@pytest.fixture
def app(tmp_path,monkeypatch):
    import stronghold_europe_de.workspace_lock as lock
    import hud_menu_workspace as hud
    import se_asset_package as assets
    monkeypatch.setattr(lock,"lock_path",lambda *_args:tmp_path/"instance.lock")
    monkeypatch.setattr(hud,"ROOT",tmp_path)
    monkeypatch.setattr(hud,"WORK",tmp_path/"work")
    monkeypatch.setattr(hud,"DEFAULT",tmp_path/"work"/"hud-menu-werkstatt")
    monkeypatch.setattr(assets,"ROOT",tmp_path)
    monkeypatch.setattr(assets,"WORK",tmp_path/"work")
    monkeypatch.setattr(assets,"OUT",tmp_path/"work"/"se-asset-mods")
    loader=importlib.machinery.SourceFileLoader(
        "guide_compat_gui_test",str(ROOT/"tools"/"suite_universal.pyw"))
    spec=importlib.util.spec_from_loader(loader.name,loader)
    mod=importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    monkeypatch.setattr(mod,"SETTINGS",tmp_path/"settings.json")
    previous=mod.LANG.code
    mod.LANG.code="de"
    instance=mod.Universal()
    instance.geometry("1140x740+20+20")
    instance.update()
    try:yield instance,tmp_path
    finally:
        window=getattr(instance,"_guided_tutorial",None)
        if window is not None and window.winfo_exists():window.close()
        compatibility=getattr(instance,"_compat_window",None)
        if compatibility is not None and compatibility.winfo_exists():
            compatibility.close()
        mod.LANG.code=previous
        instance.destroy()


def test_tutorial_is_visible_and_steps_highlight_reversibly_without_building(
    app,monkeypatch,
):
    gui,tmp=app
    no_call=lambda *_a,**_k:pytest.fail("Tutorial executed a destructive action")
    monkeypatch.setattr(gui.workflow_tab,"build_package",no_call)
    monkeypatch.setattr(gui.workflow_tab,"add_sources",no_call)
    monkeypatch.setattr(gui,"run",no_call)
    store=ProgressStore(tmp/"progress.json")
    window=open_guided_tutorial(gui,track="quickstart",store=store)
    gui.update()
    assert gui.modern_shell.tutorial_button.winfo_ismapped()
    assert window.index==0
    assert window._focus_widget is gui.modern_shell.buttons["start"]
    window.next()
    gui.update()
    assert window.index==1
    assert window._focus_widget is gui.workflow_tab.source_button
    assert gui.workflow_tab.source_button.cget("style")=="Tutorial.Focus.TButton"
    window.previous()
    gui.update()
    assert gui.workflow_tab.source_button.cget("style")!="Tutorial.Focus.TButton"
    window.close()
    assert store.load()["quickstart"]==0


def test_tutorial_demo_route_and_en_language_keep_actual_project(app,monkeypatch):
    gui,tmp=app
    project=gui.workflow_tab.pipeline.project
    window=open_guided_tutorial(gui,track="demo",
                                 store=ProgressStore(tmp/"progress.json"))
    assert not gui.modern_shell.more_expanded
    window.next()
    gui.update()
    assert gui.modern_shell.more_expanded
    assert gui.modern_shell.demo_button.winfo_ismapped()
    assert window._focus_widget is gui.modern_shell.demo_button
    gui.set_language("en")
    gui.update()
    assert window.track_choice.get()=="Demo modules"
    assert window.step_var.get().startswith("Step")
    assert window.body_var.get().startswith("Open Interactive demo")
    gui.set_language("de")
    window.close()
    assert not gui.modern_shell.more_expanded
    assert gui.workflow_tab.pipeline.project==project


def test_compatibility_report_readonly_never_approves_native_game(tmp_path):
    report=collect(ROOT,check_steam=False)
    assert report["schema"]=="sprite-suite.compatibility-readonly.v1"
    assert report["native_game_approved"] is False
    assert report["writes_to_game"] is False
    assert report["host_ready"]
    assert "Python runtime" in {r["name"] for r in report["checks"]}
    assert next(r for r in report["checks"] if r["name"]=="Native game ABI")["status"]=="unverified"


def test_compatibility_diagnostic_can_open_and_update_without_installing(app):
    gui,_=app
    win=gui.run_compatibility_report()
    gui.update()
    assert win.winfo_exists()
    assert win._job_pending or win.report is not None
    for _ in range(200):
        gui.update()
        if win.report is not None:break
        import time
        time.sleep(.025)
    assert win.report is not None
    assert win.report["native_game_approved"] is False
    assert len(win.table.get_children())>=7
    gui.set_language("en")
    assert "Compatibility check" in win.title()
    win.close()


def test_pdf_action_returns_none_for_missing_file_without_running_shell(app,monkeypatch):
    gui,tmp=app
    # This test is meaningful before and after the PDF is created.
    if (ROOT/"docs"/"SPRITESUITE_ILLUSTRIERTES_HANDBUCH.pdf").exists():
        monkeypatch.setattr("os.startfile",lambda path:None)
        path=gui.open_pdf_manual()
        assert path.name=="SPRITESUITE_ILLUSTRIERTES_HANDBUCH.pdf"
    else:
        from tkinter import messagebox
        monkeypatch.setattr(messagebox,"showwarning",lambda *_a,**_k:None)
        assert gui.open_pdf_manual() is None



def test_guided_tutorial_minimum_window_keeps_controls_accessible(app,tmp_path):
    gui,_=app
    guide=open_guided_tutorial(gui,track="compat",
        store=ProgressStore(tmp_path/"min-progress.json"))
    guide.geometry("425x485+25+25")
    gui.update()
    bottom=guide.winfo_rooty()+guide.winfo_height()
    right=guide.winfo_rootx()+guide.winfo_width()
    assert guide.track_picker.winfo_ismapped()
    for widget in (guide.focus_button,guide.back_button,guide.next_button,
                   guide.pdf_button,guide.demo_button,guide.compat_button):
        assert widget.winfo_ismapped(),repr(widget)
        assert widget.winfo_rooty()+widget.winfo_height()<=bottom+2,repr(widget)
        assert widget.winfo_rootx()+widget.winfo_width()<=right+2,repr(widget)
    guide.close()


def test_manual_embedded_and_safely_labeled(tmp_path):
    file=ROOT/"docs"/"SPRITESUITE_ILLUSTRIERTES_HANDBUCH.pdf"
    assert file.is_file()
    content=file.read_bytes()
    assert content.startswith(b"%PDF-")
    assert b"%%EOF" in content[-1024:]
    assert len(content)>100000
    fitz=pytest.importorskip("fitz")
    doc=fitz.open(str(file))
    assert len(doc)==14
    assert "Geführter Anleitungsmodus" in doc[2].get_text()
    assert sum(len(page.get_images(full=True)) for page in doc)>=9



def test_readonly_compatibility_rejects_incomplete_bundled_tcl(tmp_path):
    """A developer PC's Tcl must never green-light a broken copied bundle."""
    from suite_compatibility_preflight import _tcl
    (tmp_path/"python").mkdir()
    row=_tcl(tmp_path)
    assert row["status"]=="limited"
    assert "Bundled" in row["detail"]


def test_readonly_compatibility_checks_manual_integrity(tmp_path):
    from suite_compatibility_preflight import _manual_pdf
    folder=tmp_path/"docs"
    folder.mkdir()
    manual=folder/"SPRITESUITE_ILLUSTRIERTES_HANDBUCH.pdf"
    manual.write_bytes(b"%PDF-1.7"+(b"A"*15000))
    assert _manual_pdf(tmp_path)["status"]=="limited"
    manual.write_bytes((b"%PDF-1.7"+b"A"*15000)+b"%%EOF")
    assert _manual_pdf(tmp_path)["status"]=="ready"


def test_arm64_cannot_be_marked_as_native_windows_x64(monkeypatch):
    import suite_compatibility_preflight as preflight
    monkeypatch.setattr(preflight.platform,"machine",lambda:"ARM64")
    report=preflight.collect(ROOT)
    host=next(x for x in report["checks"] if x["name"]=="Windows x64 host")
    assert host["status"]=="blocked"
    assert report["host_ready"] is False
    assert report["native_game_approved"] is False


def test_german_compatibility_table_and_diagnostics_translate_without_changes(app):
    gui,_=app
    window=gui.run_compatibility_report()
    gui.update()
    for _ in range(250):
        gui.update_idletasks()
        gui.update()
        if window.report is not None:break
        import time
        time.sleep(.02)
    assert window.report is not None
    assert window.table.item("0","text")=="Windows-x64-System"
    names=[window.table.item(k,"text") for k in window.table.get_children()]
    assert "Qt-Spielvorschau" in names
    idx=next(k for k in window.table.get_children()
             if window.report["checks"][int(k)]["name"]=="Qt Sandbox")
    assert "erfolgreich" in window.table.set(idx,"detail")
    before=window.report["checks"][int(idx)].copy()
    gui.set_language("en")
    gui.update()
    assert window.table.item(idx,"text")=="Qt Sandbox"
    assert window.table.set(idx,"detail")==before["detail"]
    assert window.report["checks"][int(idx)]==before
    gui.set_language("de")
    window.close()


def test_highlighting_export_never_takes_keyboard_focus_to_command(app,monkeypatch):
    gui,dir=app
    widget=gui.workflow_tab.export_button
    monkeypatch.setattr(widget,"focus_set",
                        lambda:pytest.fail("Guide stole focus to export"))
    tutorial=open_guided_tutorial(gui,track="quickstart",
                                  store=ProgressStore(dir/"focus-progression.json"))
    tutorial.index=6
    tutorial._update_labels_and_step()
    gui.update()
    assert tutorial._focus_widget is widget
    assert widget.cget("style")=="Tutorial.Focus.TButton"
    before=tutorial.index
    tutorial.focus_force()
    gui.update()
    tutorial.event_generate("<Alt-Right>",when="tail")
    gui.update()
    assert tutorial.index==before+1
    tutorial.close()
    assert widget.cget("style")!="Tutorial.Focus.TButton"



def test_completed_tutorial_remembers_finish_and_restarts_at_first_step(app,tmp_path):
    gui,_=app
    store=ProgressStore(tmp_path/"finished-track.json")
    tutorial=open_guided_tutorial(gui,track="quickstart",store=store)
    tutorial.index=len(BY_KEY["quickstart"].steps)-1
    tutorial._update_labels_and_step()
    tutorial.next()
    assert store.load_completed()=={"quickstart"}
    assert store.load()["quickstart"]==len(BY_KEY["quickstart"].steps)-1
    again=open_guided_tutorial(gui,track="quickstart",store=store)
    assert again.index==0
    assert "abgeschlossen" in again.note_var.get()
    gui.set_language("en")
    assert "completed" in again.note_var.get()
    again.close()


def test_old_progress_format_remains_compatible(tmp_path):
    p=tmp_path/"old-guide.json"
    p.write_text(json.dumps({
        "schema":"sprite-suite.guide-progress.v1",
        "steps":{"layout":2}},ensure_ascii=False),encoding="utf-8")
    store=ProgressStore(p)
    assert store.load()=={"layout":2}
    assert store.load_completed()==set()
    assert store.save({"layout":3},completed={"layout"})
    assert store.load_completed()=={"layout"}

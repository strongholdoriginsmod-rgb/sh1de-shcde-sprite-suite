"""Tk Universal Suite -> embedded Qt Sandbox routing without a second process."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import os
from pathlib import Path
import sys
import types

import pytest

try:
    import tkinter as tk
    from tkinter import ttk
except ImportError:
    tk = None

pytestmark = pytest.mark.skipif(
    tk is None or sys.platform != "win32",
    reason="The Universal Suite native notebook integration requires Windows Tk.",
)

ROOT = Path(__file__).resolve().parents[2]


def load_suite():
    loader = importlib.machinery.SourceFileLoader(
        "suite_universal_integration_test", str(ROOT/"tools"/"suite_universal.pyw")
    )
    spec = importlib.util.spec_from_loader(loader.name,loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_catalog_sends_selected_frame_to_main_suite_sandbox(monkeypatch):
    suite = load_suite()
    sent = []
    app = types.SimpleNamespace(
        show_in_sandbox=lambda group,frame: sent.append((group,frame))
    )
    catalog = types.SimpleNamespace(
        group="tile_land8",selected="tile_land8 015",app=app
    )
    suite.CatalogTab.to_sandbox(catalog)
    assert sent == [("tile_land8",15)]
    catalog.group=None
    suite.CatalogTab.to_sandbox(catalog)
    assert len(sent)==1
    # No legacy katalog-vorschau.json scene file is generated.


def test_open_sandbox_studio_switches_to_embedded_tab(monkeypatch):
    suite = load_suite()
    calls=[]
    tab = types.SimpleNamespace(
        ensure_studio=lambda: calls.append("embedded")
    )
    main=types.SimpleNamespace(
        notebook=types.SimpleNamespace(select=lambda selected: calls.append(selected)),
        sandbox_tab=tab,
    )
    # This method must never spawn an independent sandbox process.
    import subprocess
    monkeypatch.setattr(subprocess,"Popen",lambda *a,**kw:pytest.fail(
        "An independent sandbox process must never be launched"
    ))
    suite.Universal.open_sandbox_studio(main)
    assert calls == [tab,"embedded"]


def test_tk_notebook_embeds_once_and_catalog_navigation_remains_bidirectional(monkeypatch):
    suite=load_suite()
    try:
        root=tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"No Tk desktop: {exc}")
    root.geometry("1100x780")
    root.title("Test integrated sandbox")
    notebook=ttk.Notebook(root)
    notebook.pack(fill="both",expand=True)
    root.notebook=notebook
    console_frame=ttk.Frame(root)
    console_frame.pack(side="bottom",before=notebook,fill="both")
    root.console=tk.Text(console_frame,height=3)
    root.console.pack()
    logged=[]
    root.log=lambda text,tag=None:logged.append(text)
    focus=[]
    root.show_in_catalog=lambda group,frame:focus.append((group,frame))
    root.update()
    other=ttk.Frame(notebook)
    notebook.add(other,text="Asset-Katalog")
    sandbox=suite.SandboxTab(notebook,root)
    notebook.add(sandbox,text="Sandkasten")
    sandbox._game_root=lambda:None
    fake=types.ModuleType("sandbox_suite_embed")
    instances=[]
    class Backend:
        def __init__(self,host,*,maps_root=None,status=None):
            self.host=host
            self.calls=[]
            self.studio_calls=[]
            self.window=types.SimpleNamespace(
                choose_map=lambda:self.studio_calls.append("map"),
                choose_folder=lambda:self.studio_calls.append("folder"),
                save_active=lambda:self.studio_calls.append("save"),
                open_reference_comparison=lambda:self.studio_calls.append("compare"),
                show_test_field=lambda:self.studio_calls.append("testfield"),
                show_native_map=lambda:self.studio_calls.append("mapview"),
                _animation_dock=types.SimpleNamespace(
                    raise_=lambda:self.studio_calls.append("animationdock")
                ),
                _hud_dock=types.SimpleNamespace(
                    raise_=lambda:self.studio_calls.append("gamehud")
                ),
            )
            self.closed=False
            self.can_close=True
            self.status=status
            instances.append(self)
        def select_sprite(self,group,frame):
            self.calls.append((group,frame))
        def selected_sprite(self):
            return ("tree_pine",20)
        def close(self):
            if not self.can_close:return False
            self.closed=True
            return True
    fake.EmbeddedSandboxStudio=Backend
    monkeypatch.setitem(sys.modules,"sandbox_suite_embed",fake)
    try:
        notebook.select(sandbox)
        root.update()
        assert console_frame.winfo_manager()==""  # log collapsed here only
        embedded=sandbox.ensure_studio()
        assert embedded is not None
        assert len(instances)==1
        sandbox.select_sprite("tree_cactii",17)
        assert embedded.calls==[("tree_cactii",17)]
        sandbox.show_in_catalog()
        assert focus
        assert focus[-1][0]=="tree_pine"
        sandbox.choose_map()
        sandbox.choose_folder()
        sandbox.save_scene()
        sandbox.compare()
        assert embedded.studio_calls==["map","folder","save","compare"]
        sandbox.show_animation()
        sandbox.show_game_hud()
        assert embedded.studio_calls[-4:]==[
            "testfield","animationdock","mapview","gamehud"
        ]
        notebook.select(other)
        root.update()
        assert console_frame.winfo_manager()=="pack"
        notebook.select(sandbox)
        root.update()
        assert sandbox.ensure_studio() is embedded
        assert len(instances)==1
        embedded.can_close=False
        assert sandbox.close_studio() is False
        assert sandbox.bridge is embedded
        embedded.can_close=True
        assert sandbox.close_studio() is True
        assert embedded.closed
    finally:
        root.destroy()


def test_compact_embedded_layout_without_optional_xaml_art(tmp_path, monkeypatch):
    """Fresh installations have no authorized local XAML crop assets.

    The functional HUD and original-map editor must still embed without
    _original_hud_dock; that art dock is intentionally optional.
    """
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QDockWidget
    TOOLS=str(ROOT/"tools")
    if TOOLS not in sys.path:
        sys.path.insert(0,TOOLS)
    from sandbox_studio import SandboxStudio
    from sandbox_suite_embed import EmbeddedSandboxStudio
    app=QApplication.instance() or QApplication([])
    studio=SandboxStudio(tmp_path)
    try:
        art=getattr(studio,"_original_hud_dock",None)
        if art is not None:
            art.hide()
            studio.removeDockWidget(art)
            del studio._original_hud_dock
        fake=types.SimpleNamespace(_window=studio)
        EmbeddedSandboxStudio._compact_for_suite(fake)
        assert studio.dockWidgetArea(studio._hud_dock)==(
            Qt.DockWidgetArea.RightDockWidgetArea
        )
        assert studio.dockWidgetArea(studio._animation_dock)==(
            Qt.DockWidgetArea.RightDockWidgetArea
        )
        assert studio._animation_dock.widget() is not None
        assert studio._hud_dock.isVisible() or not studio.isVisible()
        studio.show_test_field()
        studio._animation_dock.raise_()
        app.processEvents()
        assert studio._animation_dock.isVisible() or not studio.isVisible()
        assert studio.native_minimap.maximumHeight()==120
        assert studio.minimumSize().height()==0
    finally:
        studio.native_canvas._poll.stop()
        studio.board._asset_poll.stop()
        studio.asset_preview.timer.stop()
        studio._saved_scene=studio.board.history.scene.serialize()
        studio.close()
        app.processEvents()


def test_embedded_selected_sprite_uses_current_preview_not_old_engine_hit():
    # Previously last_engine_pick won even after the user changed the
    # selected catalogue/palette frame; returning to the asset catalogue
    # opened the *old* sprite. The preview reflects the user's latest choice.
    TOOLS=str(ROOT/"tools")
    if TOOLS not in sys.path:sys.path.insert(0,TOOLS)
    from sandbox_suite_embed import EmbeddedSandboxStudio
    fake=types.SimpleNamespace(
        _closed=False,
        _window=types.SimpleNamespace(
            native_canvas=types.SimpleNamespace(
                engine_active=lambda:True,
                last_engine_pick=types.SimpleNamespace(
                    ref=types.SimpleNamespace(group="tree_pine",frame=20)
                ),
            ),
            asset_preview=types.SimpleNamespace(
                group=types.SimpleNamespace(currentText=lambda:"tile_castle"),
                frame=types.SimpleNamespace(value=lambda:1193),
            ),
        ),
    )
    assert EmbeddedSandboxStudio.selected_sprite(fake)==("tile_castle",1193)
    fake._window.asset_preview.group.currentText=lambda:"  "
    assert EmbeddedSandboxStudio.selected_sprite(fake) is None

def test_embedded_qt_close_is_routed_and_cancel_is_honoured(tmp_path, monkeypatch):
    """No blank notebook tab after Qt Close/Alt+F4, and cancellation works."""
    monkeypatch.setenv("QT_QPA_PLATFORM","offscreen")
    from PySide6.QtWidgets import QApplication
    tools_path = str(ROOT / "tools")
    if tools_path not in sys.path:
        sys.path.insert(0, tools_path)
    from sandbox_studio import SandboxStudio
    app = QApplication.instance() or QApplication([])
    studio = SandboxStudio(tmp_path)
    calls=[]
    studio._embedded_close_request = lambda:calls.append("host-close")
    studio._embedded_allow_close = False
    try:
        assert studio.close() is False
        assert calls == ["host-close"]
        # The host now asks Qt to close through its ordinary safeguard path.
        studio._embedded_allow_close = True
        monkeypatch.setattr(studio,"_confirm_discard",lambda:False)
        assert studio.close() is False
        monkeypatch.setattr(studio,"_confirm_discard",lambda:True)
        monkeypatch.setattr(studio,"_confirm_overlay_discard",lambda:True)
        assert studio.close() is True
        assert calls == ["host-close"]
    finally:
        studio.native_canvas._poll.stop()
        studio.board._asset_poll.stop()
        studio.asset_preview.timer.stop()
        studio._embedded_close_request = None
        if studio.isVisible():studio.close()
        app.processEvents()


def test_embedded_close_request_is_coalesced():
    TOOLS=str(ROOT / "tools")
    if TOOLS not in sys.path:
        sys.path.insert(0,TOOLS)
    from sandbox_suite_embed import EmbeddedSandboxStudio
    jobs,ended=[],[]
    root=types.SimpleNamespace(
        winfo_exists=lambda:True,
        after_idle=lambda fn:jobs.append(fn),
        destroy=lambda:ended.append("root.destroy"),
    )
    bridge=types.SimpleNamespace(
        _closed=False,_pending_suite_close=False,root=root
    )
    # Binding the class methods to our dummy host is sufficient to assert
    # that two rapid Qt Close events can't queue two Tk destroy() calls.
    bridge._finish_suite_close=lambda:EmbeddedSandboxStudio._finish_suite_close(bridge)
    EmbeddedSandboxStudio._request_suite_close(bridge)
    EmbeddedSandboxStudio._request_suite_close(bridge)
    assert len(jobs)==1
    jobs.pop()()
    assert ended == ["root.destroy"]
    assert bridge._pending_suite_close is False



def test_legacy_sandbox_compatibility_cannot_launch_second_window(monkeypatch):
    """Older Suite call sites must converge on the one embedded Sandbox."""
    suite=load_suite()
    selected=[]
    loaded=[]
    old_imports=[]
    bridge=types.SimpleNamespace(
        window=types.SimpleNamespace(
            load_test_scene=lambda path:loaded.append(path) or True
        )
    )
    tab=types.SimpleNamespace(
        ensure_studio=lambda:selected.append("embedded") or bridge
    )
    main=types.SimpleNamespace(
        notebook=types.SimpleNamespace(select=lambda selected:selected is tab),
        sandbox_tab=tab,
    )
    # There is intentionally no import of the legacy SandboxWindow class.
    sys.modules.pop("sandkasten_nonexistent_compat",None)
    assert suite.Universal.open_sandbox(main,None) is True
    assert selected==["embedded"] and not loaded
    path=ROOT/"work"/"sandbox-test-fixture.json"
    assert suite.Universal.open_sandbox(main,str(path)) is True
    assert loaded==[path]
    assert selected==["embedded","embedded"]
    missing=types.SimpleNamespace(
        notebook=main.notebook,
        sandbox_tab=types.SimpleNamespace(ensure_studio=lambda:None)
    )
    assert suite.Universal.open_sandbox(missing,path) is False
    assert len(loaded)==1



def test_first_studio_open_maps_tk_tab_before_initializing_native_child():
    """Real Notebook.select() is asynchronous until Tk's idle geometry pass."""
    suite=load_suite()
    try:
        root=tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"No Tk desktop: {exc}")
    root.geometry("900x650+95+95")
    try:
        notebook=ttk.Notebook(root)
        notebook.pack(fill="both",expand=True)
        other=ttk.Frame(notebook)
        tab=ttk.Frame(notebook)
        notebook.add(other,text="Katalog")
        notebook.add(tab,text="Sandbox")
        host=ttk.Frame(tab)
        host.pack(fill="both",expand=True)
        root.update()
        assert notebook.select()==str(other)
        assert not host.winfo_ismapped()
        calls=[]
        sentinel=object()
        def ensure():
            calls.append((host.winfo_ismapped(),notebook.select()==str(tab)))
            assert host.winfo_ismapped(), "Native host wasn't mapped before creating Qt child"
            return sentinel
        tab.ensure_studio=ensure
        owner=types.SimpleNamespace(
            notebook=notebook,sandbox_tab=tab,
            update_idletasks=root.update_idletasks,
        )
        assert suite.Universal.open_sandbox_studio(owner) is sentinel
        assert calls==[(1,True)]
        assert notebook.select()==str(tab)
    finally:
        root.destroy()



def test_suite_closes_all_queued_tk_events_before_destruction(
    tmp_path, monkeypatch
):
    """Destroying Tk must not leak _drain/load callbacks into the next root."""
    suite=load_suite()
    import stronghold_europe_de.workspace_lock as lock_module
    monkeypatch.setattr(
        lock_module,"lock_path",
        lambda _root,_name: tmp_path/"after-lifecycle-instance.lock",
    )
    monkeypatch.setattr(suite,"SETTINGS",tmp_path/"suite-test-settings.json")
    monkeypatch.setattr(suite.LANG,"code","de")
    app=suite.Universal()
    app.sandbox_tab.ensure_studio=lambda:None
    closed=False
    try:
        # At least _drain() is armed by the normal Suite initializer.
        initial=tuple(app.tk.call("after","info"))
        assert initial
        scheduled=app.after(60_000,lambda:pytest.fail(
            "Old callback ran after the Suite was destroyed"
        ))
        assert scheduled in app.tk.call("after","info")
        app.destroy()
        closed=True
        assert not tuple(app.tk.call("after","info")), (
            "Tk callbacks survived the committed Suite shutdown"
        )
    finally:
        if not closed:
            app.destroy()

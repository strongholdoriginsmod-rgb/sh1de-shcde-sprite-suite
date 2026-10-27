"""Manual-style Windows QA for the guided Sprite Suite home and navigation.

Uses the *actual* Tk Universal Suite, its 14 workspaces and DE/EN switch.
Does not start Unity, a game, a build, an installer or a Qt engine worker.
Its only output is an optional screenshot under the ignored work/ tree.

Run: .venv\\Scripts\\python.exe tools\\qa_suite_guided_home.py
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
from pathlib import Path
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/"src"),str(ROOT/"tools")]


def _load():
    source=ROOT/"tools"/"suite_universal.pyw"
    loader=importlib.machinery.SourceFileLoader("guided_home_qa",str(source))
    spec=importlib.util.spec_from_loader(loader.name,loader)
    module=importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def main():
    import tkinter as tk
    from tkinter import ttk
    from PIL import ImageGrab
    import stronghold_europe_de.workspace_lock as lock
    if sys.platform != "win32":
        raise SystemExit("Windows Desktop required to verify the actual Tk UI.")
    suite=_load()
    with tempfile.TemporaryDirectory(prefix="sprite-suite-home-qa-") as temporary:
        tmp=Path(temporary)
        lock.lock_path=lambda _root,_name:tmp/"suite-instance.lock"
        suite.SETTINGS=tmp/"settings.json"
        suite.LANG.code="de"
        suite.LANG.save=lambda:None
        app=suite.Universal()
        opened=[]
        original_run=app.run
        def forbid_run(*args,**kwargs):
            raise AssertionError(
                "Navigating from Start must not start CLI/build/installation: "+repr(args)
            )
        app.run=forbid_run
        app.sandbox_tab.ensure_studio=lambda:None
        try:
            home=app.tab_home
            workflow=home.nametowidget(home.guide_sections.tabs()[0])
            buttons=[
                child for row in workflow.winfo_children()
                for child in row.winfo_children()
                if isinstance(child,ttk.Button) and child.cget("text")=="Öffnen"
            ]
            destinations=(
                app.setup_page,app.catalog_tab,app.sandbox_tab,
                app.exchange_tab,app.diagnose_tab,app.bc7_page,app.target_tab
            )
            assert len(buttons)==len(destinations)==7
            for width,height in ((1020,680),(1320,800)):
                app.geometry(f"{width}x{height}+40+40")
                app.update()
                app.open_tab(home)
                app.update()
                assert app.notebook.select()==str(home)
                assert app.notebook.tab(home,"state")=="normal"
                assert app.quick_picker.winfo_ismapped()
                area=home.guide_scroll.canvas
                # At the minimum supported desktop size all seven primary
                # actions must be visible, without initially scrolling.
                assert all(
                    area.winfo_rooty() <= button.winfo_rooty()
                    and button.winfo_rooty()+button.winfo_height()
                        <= area.winfo_rooty()+area.winfo_height()
                    for button in buttons
                ), "At least one Start action is clipped at "+str((width,height))
                for index,(button,target) in enumerate(zip(buttons,destinations),1):
                    button.invoke()
                    app.update()
                    assert app.notebook.select()==str(target),(
                        index,app.notebook.select(),str(target)
                    )
                    opened.append((width,height,index))
                    app.open_tab(home)
                    app.update()
                # Capture the containing Tk window at both resolutions.
                try:
                    file=ROOT/"work"/"reports"/"ui-guided-home"/f"{width}x{height}.png"
                    file.parent.mkdir(parents=True,exist_ok=True)
                    # Capture this specific Tk HWND, not whichever unrelated
                    # app happens to be foreground on the QA desktop.
                    ImageGrab.grab(window=int(app.winfo_id())).save(file)
                    print("SCREENSHOT",file,flush=True)
                except OSError as exc:
                    print("Screenshot unavailable:",exc,flush=True)
            app.set_language("en")
            app.open_tab(home)
            app.update()
            assert all(button.cget("text")=="Open" for button in buttons)
            assert app.notebook.tab(home,"state")=="normal"
            app.set_language("de")
            app.update()
            assert all(button.cget("text")=="Öffnen" for button in buttons)
            assert app.runner.thread is None
            print("HOME_QA_PASS",len(opened),"task routes, 2 window sizes, DE/EN",flush=True)
        finally:
            app.run=original_run
            app.destroy()


if __name__=="__main__":
    main()

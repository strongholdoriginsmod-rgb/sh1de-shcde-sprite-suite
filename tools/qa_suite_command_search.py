"""Real Windows Tk/Qt Ctrl+K command search regression.

Run with .venv/Scripts/python.exe tools/qa_suite_command_search.py.
Uses only navigation, never changes source games or triggers build/install.
"""
from __future__ import annotations
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import sys
import traceback

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/"tools"),str(ROOT/"src")]
if os.name!="nt":
    raise SystemExit("Windows required")
os.environ.pop("QT_QPA_PLATFORM",None)
loader=importlib.machinery.SourceFileLoader(
    "suite_command_palette_qa", str(ROOT/"tools"/"suite_universal.pyw"))
spec=importlib.util.spec_from_loader(loader.name,loader)
suite=importlib.util.module_from_spec(spec)
loader.exec_module(suite)

def main():
    app=suite.Universal()
    app.geometry("1400x860+65+65")
    error=[]
    embedded_bridges=[]
    def opening():
        try:
            app.open_sandbox_studio()
        except Exception as exc:
            error.append(str(exc))
            traceback.print_exc()
    def verify():
        try:
            from PySide6.QtCore import Qt
            from PySide6.QtGui import QShortcut
            from PySide6.QtTest import QTest
            bridge=app.sandbox_tab.bridge
            assert bridge is not None,app.sandbox_tab.message.get()
            embedded_bridges.append(bridge)
            assert bridge._suite_command_filter is not None
            studio=bridge.window
            assert bridge.is_embedded()
            shortcuts=studio.findChildren(QShortcut)
            keys=[short.key().toString() for short in shortcuts]
            assert "Ctrl+K" in keys,keys
            studio.native_canvas.setFocus()
            app.update()
            bridge._qt_app.processEvents()
            QTest.keyClick(
                studio.native_canvas.viewport(),
                Qt.Key.Key_K,
                Qt.KeyboardModifier.ControlModifier
            )
            bridge._qt_app.processEvents()
            app.update()
            search=getattr(app,"_command_search",None)
            assert search is not None and search.winfo_exists(), (
                "Ctrl+K in Qt did not open the Tk command search."
            )
            print("QT_CTRL_K_OPENS_TK_SEARCH",flush=True)
            search.query.set("zinnenlineal")
            app.update()
            assert search.visible and search.visible[0].key=="editor:2"
            search.execute_selected()
            app.update()
            assert app.notebook.select()==str(app.exchange_tab)
            assert "Pivot" in app.exchange_tab.section_choice.get()
            print("PIVOT_NAVIGATION_WITHOUT_TOOL_EXECUTION",flush=True)

            app.set_language("en")
            app.update()
            search=app.show_command_search()
            assert search.language=="en"
            search.query.set("Game HUD")
            app.update()
            matches=[item.key for item in search.visible]
            assert "sandbox:hud" in matches,matches
            search.results.selection_set("sandbox:hud")
            search.execute_selected()
            app.update()
            assert app.notebook.select()==str(app.sandbox_tab)
            assert bridge.workspace._selected_right is studio._hud_dock
            print("ENGLISH_GAME_HUD_NAVIGATION",flush=True)
            finder=app.show_command_search()
            finder.query.set("Game map")
            app.update()
            assert "sandbox:map" in [x.key for x in finder.visible]
            finder.results.selection_set("sandbox:map")
            studio.tabs.setCurrentIndex(1)
            finder.execute_selected()
            app.update()
            assert studio.tabs.currentIndex()==3
            print("SEARCH_REVEALS_ACTUAL_GAME_MAP",flush=True)

            app.geometry("1020x680+65+65")
            app.update()
            button=app.command_search_button
            assert button.winfo_ismapped()
            assert button.winfo_rootx()+button.winfo_width()<=(
                app.winfo_rootx()+app.winfo_width()+2
            ),(button.winfo_rootx(),button.winfo_width())
            print("COMPACT_SEARCH_VISIBLE",flush=True)
            # Do not trigger a destructive workflow while navigating.
            assert bridge.is_embedded()
        except Exception as exc:
            error.append(str(exc))
            traceback.print_exc()
        finally:
            app.after(50,finish)

    def finish():
        try:
            app.destroy()
        except Exception as exc:
            error.append(str(exc))
            traceback.print_exc()

    app.after(150,opening)
    app.after(11000,verify)
    app.mainloop()
    if embedded_bridges and embedded_bridges[0]._suite_command_filter is not None:
        error.append("Ctrl+K Qt event filter survived closing the embedded Suite")
    print("COMMAND_SEARCH_QA_PASS" if not error else "COMMAND_SEARCH_QA_FAILED",
          flush=True)
    if error:
        raise SystemExit(1)

if __name__=="__main__":
    main()

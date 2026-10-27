"""Host Sandbox Studio *inside* the Universal Sprite Suite's Tk notebook.

Windows-specific HWND embedding is necessary because the original suite is
Tkinter and the Studio renderer is Qt/PySide6. Both use the same UI thread:
Tk owns the event loop and pumps Qt (including live asset watchers).

No subprocess, independent desktop window, duplicate app, or game writes.
"""
from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

GWL_STYLE = -16
WS_CHILD = 0x40000000
WS_VISIBLE = 0x10000000
WS_POPUP = 0x80000000
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
WS_SYSMENU = 0x00080000
WS_CLIPCHILDREN = 0x02000000
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020


class SandboxEmbeddingError(RuntimeError):
    pass


class _Win32ChildWindow:
    """Own only window parenting and geometry, not the Qt or Tk lifecycle."""

    def __init__(self):
        if sys.platform != "win32":
            raise SandboxEmbeddingError("Die integrierte Tk/Qt-Einbettung benötigt Windows.")
        user = ctypes.WinDLL("user32", use_last_error=True)
        pointer = ctypes.c_void_p
        user.GetWindowLongPtrW.argtypes = [pointer, ctypes.c_int]
        user.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        user.SetWindowLongPtrW.argtypes = [pointer, ctypes.c_int, ctypes.c_ssize_t]
        user.SetWindowLongPtrW.restype = ctypes.c_ssize_t
        user.SetParent.argtypes = [pointer, pointer]
        user.SetParent.restype = pointer
        user.GetParent.argtypes = [pointer]
        user.GetParent.restype = pointer
        user.SetWindowPos.argtypes = [
            pointer, pointer, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_uint,
        ]
        user.SetWindowPos.restype = ctypes.c_int
        self.user = user

    def embed(self, child: int, parent: int):
        if child <= 0 or parent <= 0 or child == parent:
            raise SandboxEmbeddingError("Ungültiges eingebettetes Fenster.")
        style = int(self.user.GetWindowLongPtrW(child, GWL_STYLE))
        child_style = (
            (style | WS_CHILD | WS_VISIBLE | WS_CLIPCHILDREN)
            & ~(WS_POPUP | WS_CAPTION | WS_THICKFRAME | WS_SYSMENU)
        )
        ctypes.set_last_error(0)
        self.user.SetWindowLongPtrW(child, GWL_STYLE, child_style)
        if ctypes.get_last_error():
            raise SandboxEmbeddingError("Qt-Fensterstil konnte nicht angepasst werden.")
        ctypes.set_last_error(0)
        previous = self.user.SetParent(child, parent)
        if not previous and ctypes.get_last_error():
            raise SandboxEmbeddingError(
                f"Qt-Fenster konnte nicht in den Sandkasten-Reiter eingebettet "
                f"werden (Windows-Fehler {ctypes.get_last_error()})."
            )
        if int(self.user.GetParent(child) or 0) != parent:
            raise SandboxEmbeddingError("Qt-Sandbox ist nicht Teil des Hauptfensters.")

    def resize(self, child: int, width: int, height: int):
        if not self.user.SetWindowPos(
            child, None, 0, 0, max(1, width), max(1, height),
            SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
        ):
            raise SandboxEmbeddingError("Qt-Sandbox konnte nicht mit dem Reiter skaliert werden.")


class EmbeddedSandboxStudio:
    """A single live Studio inside a Tk Frame, with no second application."""

    def __init__(self, host, *, maps_root=None, status=None):
        if not host.winfo_exists() or not host.winfo_ismapped():
            raise SandboxEmbeddingError("Der Sandkasten-Reiter muss sichtbar sein.")
        self.host = host
        self.root = host.winfo_toplevel()
        self.status = status
        self._after_id = None
        self._pending_suite_close = False
        self._pending_panel_fit = False
        self._closed = False
        self._window = None
        self._qt_app = None
        self._win32 = _Win32ChildWindow()
        self._handle = None
        self._host_handle = int(host.winfo_id())
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
        from sandbox_studio import SandboxStudio, DEFAULT_GAME
        self._qt_app = QApplication.instance() or QApplication(sys.argv[:1])
        self._qt_app.setQuitOnLastWindowClosed(False)
        try:
            self._window = SandboxStudio(maps_root or DEFAULT_GAME)
            self._suite_command_filter = None
            # Qt embedded in Tk sometimes does not regard its parented native
            # HWND as the active QWindow. A Qt.WindowShortcut alone is not
            # reliable. An application event filter intercepts *only* keys
            # from this Studio's widgets before they reach Qt shortcut routing.
            if callable(getattr(self.root, "show_command_search", None)):
                from PySide6.QtCore import QObject, QEvent
                from PySide6.QtWidgets import QWidget
                owner = self
                class _EmbeddedCommandSearchFilter(QObject):
                    def eventFilter(self, obj, event):
                        if (event.type() == QEvent.Type.KeyPress
                            and isinstance(obj, QWidget)
                            and (obj is owner._window or
                                 owner._window.isAncestorOf(obj))
                            and event.key() == Qt.Key.Key_K
                            and event.modifiers()
                                  & Qt.KeyboardModifier.ControlModifier):
                            if not owner._closed and owner.root.winfo_exists():
                                owner.root.after(0, owner.root.show_command_search)
                            return True
                        return False
                self._suite_command_filter = _EmbeddedCommandSearchFilter(
                    self._window
                )
                self._qt_app.installEventFilter(self._suite_command_filter)
            # Ctrl+K must work while native Qt holds keyboard focus inside
            # the Tk notebook. Deliver the command to the owning Tk root,
            # never spawn a second command search or a separate process.
            if callable(getattr(self.root, "show_command_search", None)):
                from PySide6.QtGui import QKeySequence, QShortcut
                self._suite_search_shortcut = QShortcut(
                    QKeySequence("Ctrl+K"), self._window
                )
                self._suite_search_shortcut.setContext(
                    Qt.ShortcutContext.WindowShortcut
                )
                self._suite_search_shortcut.activated.connect(
                    lambda: self.root.after(0, self.root.show_command_search)
                )
            # CompactSandboxLayout identifies known docks by their original
            # German titles before replacing them with short names. Build in
            # the canonical language first, then apply the user locale.
            self._window.set_ui_language("de")
            self._window._embedded_close_request = self._request_suite_close
            self._window._embedded_allow_close = False
            self._compact_for_suite()
            # The compact workspace creates additional Qt actions and dock
            # titles after the editor initializes; translate those too.
            from sandbox_qt_locale import preferred_language
            self._window.set_ui_language(preferred_language())
            self._window.setWindowFlags(
                Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
            )
            self._window.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
            self._handle = int(self._window.winId())
            self._win32.embed(self._handle, self._host_handle)
            self._window.show()
            self.resize()
            host.bind("<Configure>", self._resized, add="+")
            self._pump()
        except Exception:
            self._closed = True
            # A failed embedding must not leave a global Qt key filter
            # attached to the application's next editor instance.
            filter_obj = getattr(self, "_suite_command_filter", None)
            if filter_obj is not None and self._qt_app is not None:
                self._qt_app.removeEventFilter(filter_obj)
                self._suite_command_filter = None
            if self._window is not None:
                self._window.hide()
                self._window.deleteLater()
            raise

    def _compact_for_suite(self):
        """Adapt original Qt Studio docks to the Tk notebook's available space.

        The editor, HUD, source palette and inspector remain functional.
        Native Studio's wide bottom game panels become scrollable *Qt tabs on
        the right*; they are never detached into independent windows.
        """
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QDockWidget, QScrollArea
        studio = self._window
        for dock in studio.findChildren(QDockWidget):
            if (studio.dockWidgetArea(dock) ==
                    Qt.DockWidgetArea.BottomDockWidgetArea):
                dock.hide()
        studio.native_minimap.setMinimumHeight(60)
        studio.native_minimap.setMaximumHeight(120)
        studio._native_inspector_scroll.setMinimumHeight(50)
        # Preserve *all* action tools including animation; the previous
        # integration accidentally hid the entire bottom Animation / Frame
        # Test dock. Do not leave controls stranded behind a hidden bottom
        # panel. Horizontal scrolling is preferable to dropping features.
        for dock in (studio._animation_dock, studio._hud_dock,
                     getattr(studio, "_original_hud_dock", None)):
            if dock is None:  # Optional local XAML art has not been extracted.
                continue
            existing = dock.widget()
            if existing is None:
                continue
            existing.setParent(None)
            compact = dock is studio._hud_dock or (
                dock is getattr(studio,"_original_hud_dock",None)
            )
            if compact:
                # Both the functional and the optional XAML art HUD contain
                # historically wide bottom layouts. Reflow them into narrow
                # functional sidebars instead of forcing 1000px scrolling.
                existing.configure_compact()
            scroller = QScrollArea()
            scroller.setWidgetResizable(compact)
            scroller.setHorizontalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff
                if compact else Qt.ScrollBarPolicy.ScrollBarAsNeeded
            )
            scroller.setWidget(existing)
            dock.setWidget(scroller)
            studio.removeDockWidget(dock)
            # The original standalone bottom docks have hard maximum
            # heights of 150/190/250px. Leaving those limits in place after
            # moving them to the right makes their entire functional HUD
            # a 190px-high strip with practically every control cropped.
            dock.setMinimumHeight(0)
            dock.setMaximumHeight(16777215)
            scroller.setMinimumHeight(0)
            studio.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea,dock)
            studio.tabifyDockWidget(studio._native_dock,dock)
            dock.show()
        studio._native_dock.raise_()
        # Small tab labels leave the map selector visible, even at 1020px.
        for index, label, explanation in (
            (0, 'Radar', 'Original-Radarbild der Karte'),
            (1, 'Testfeld', 'Interaktive Sprite-Testszene'),
            (2, 'Kacheldaten', 'Originale rohe Höhen-/Kacheldaten'),
            (3, 'Spielkarte', 'Original-Tiles und Sprite-Objekte'),
        ):
            studio.tabs.setTabText(index,label)
            studio.tabs.setTabToolTip(index,explanation)
        from sandbox_compact_layout import CompactSandboxLayout
        self.workspace=CompactSandboxLayout(studio)
        studio.setMinimumSize(0,0)

    @property
    def window(self):
        return self._window

    @property
    def native_hwnd(self):
        return self._handle

    @property
    def host_hwnd(self):
        return self._host_handle

    def is_embedded(self) -> bool:
        return (
            not self._closed and self._handle is not None
            and int(self._win32.user.GetParent(self._handle) or 0) ==
            self._host_handle
        )

    def _resized(self, _event=None):
        if not self._closed:
            self.resize()

    def resize(self):
        if self._closed or not self.host.winfo_exists():
            return
        width, height = self.host.winfo_width(), self.host.winfo_height()
        if width <= 1 or height <= 1:
            return
        # Tk's HWND geometry is in Win32 pixels. Qt QWidget.resize() expects
        # device-independent coordinates; calling both enlarged/cropped the
        # native Qt child at Windows 125%/150% scaling. Win32 WM_SIZE delivers
        # the correct logical dimensions to Qt after SetWindowPos.
        self._win32.resize(self._handle, width, height)
        self._pending_panel_fit = True

    def _pump(self):
        self._after_id = None
        if self._closed or not self.host.winfo_exists():
            return
        try:
            self._qt_app.processEvents()
            if self._pending_panel_fit:
                self._pending_panel_fit = False
                # WM_SIZE is delivered as a Win32 physical-pixel event;
                # fit docks only after Qt has updated its logical geometry.
                self.workspace.refresh_size()
                self._qt_app.processEvents()
        except RuntimeError as exc:
            self._closed = True
            if self.status:
                self.status(f"Qt-Ereignisverarbeitung unterbrochen: {exc}")
            return
        self._after_id = self.host.after(25, self._pump)

    def _request_suite_close(self):
        """Qt close/Alt+F4 should close *the host Suite*, never blank one tab."""
        if self._closed or self._pending_suite_close:
            return
        self._pending_suite_close = True
        if self.root.winfo_exists():
            self.root.after_idle(self._finish_suite_close)

    def _finish_suite_close(self):
        self._pending_suite_close = False
        if not self._closed and self.root.winfo_exists():
            # Universal.destroy() checks the real Qt unsaved-scene dialogs.
            self.root.destroy()

    def toggle_focus(self):
        self.workspace.toggle_focus()

    def toggle_palette(self):
        self.workspace.toggle_palette()

    def toggle_inspector(self):
        self.workspace.toggle_inspector()

    def restore_layout(self):
        self.workspace.restore()

    def show_tool(self, dock):
        self.workspace.show_tool(dock)

    def select_sprite(self, group: str, frame: int):
        """Asset Catalog -> embedded Studio -> map placement, no files written."""
        if self._closed:
            return
        studio = self._window
        studio.asset_preview.group.setCurrentText(group)
        studio.asset_preview.frame.setValue(frame)
        studio.asset_preview.refresh()
        studio.native_canvas.last_engine_pick = None
        if studio.native_canvas.has_map():
            if studio.native_canvas.use_original_runtime_assets:
                studio.native_hud.engine_mode.setCurrentIndex(0)
            # The original Catalogue->Sandbox bridge always opened an
            # inspector dock, silently switching an already active GAME HUD
            # back into the editor. Preserve the user's current workspace.
            # Only editor users request the expert map inspector here.
            if not self.workspace.game_mode:
                studio.show_native_map()
                self.workspace.show_tool(studio._native_dock)
            studio.native_canvas.arm_placement(group, frame)
            if self.status:
                self.status(
                    f"{group}/{frame}: Auf der Spielkarte eine Kachel zum Platzieren wählen."
                )
        else:
            studio.show_test_field()
            studio.board.arm_placement(group, frame)
            if self.status:
                self.status(f"{group}/{frame}: Im Testfeld eine Kachel anklicken.")

    def selected_sprite(self):
        if self._closed:
            return None
        window = self._window
        # Map clicks synchronize the preview to the hit. Reuse the *current*
        # preview value instead of a cached previous engine hit; otherwise
        # picking a different catalogue/palette frame can return stale data.
        group = window.asset_preview.group.currentText().strip()
        frame = window.asset_preview.frame.value()
        return (group, frame) if group else None

    def close(self) -> bool:
        """Respect Studio's unsaved-scene/overlay warning on main Suite exit."""
        if self._closed:
            return True
        self._window._embedded_allow_close = True
        try:
            accepted = self._window.close()
        finally:
            self._window._embedded_allow_close = False
        if not accepted:
            return False
        self._closed = True
        if self._after_id is not None:
            try:
                self.host.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
        self._qt_app.processEvents()
        if self._suite_command_filter is not None:
            self._qt_app.removeEventFilter(self._suite_command_filter)
            self._suite_command_filter = None
        self._window.deleteLater()
        return True

"""Usable single-window workspace controls for the embedded Sandbox Studio.

The standalone Sandbox Studio keeps its original multi-dock layout. Only
the Qt view embedded in the Tk Sprite Suite gets this compact workspace.
Every tool remains available without floating a second desktop window.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QComboBox, QDockWidget, QMenu, QToolBar, QVBoxLayout, QWidget,
)

# Historical screenshot: HUD from (1060, 1123) to (2560, 1440).
# This is a UI geometry reference, NOT an engine-state or pixel match.
REFERENCE_SCREEN=(2560, 1440)
REFERENCE_HUD=(1060, 1123, 1500, 317)


def gameplay_hud_bounds(width: int, height: int) -> tuple[int, int, int, int]:
    """Proportionally right-anchor the HUD when there is enough room.

    At small notebook sizes the *actual buttons* need a wide accessibility
    fallback. Never crop controls to chase a screenshot's aspect ratio.
    """
    width, height=max(1,int(width)),max(1,int(height))
    if width >= 1050 and height >= 400:
        panel_width=round(width*REFERENCE_HUD[2]/REFERENCE_SCREEN[0])
        panel_height=max(116,min(175,round(height*REFERENCE_HUD[3]/REFERENCE_SCREEN[1])))
    else:
        panel_width=width
        panel_height=max(116,min(175,round(height*.29)))
    panel_height=min(height,panel_height)
    return (width-panel_width,height-panel_height,panel_width,panel_height)


class GameplayMapHost(QWidget):
    """Keep the true map full-size and overlay only the active game HUD."""

    def __init__(self, tabs, parent=None):
        super().__init__(parent)
        self.game_hud=None
        layout=QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        layout.setSpacing(0)
        layout.addWidget(tabs)

    def position_game_hud(self):
        if self.game_hud is not None:
            self.game_hud.setGeometry(*gameplay_hud_bounds(
                self.width(),self.height()
            ))
            self.game_hud.raise_()

    def resizeEvent(self,event):
        super().resizeEvent(event)
        self.position_game_hud()


class CompactSandboxLayout:
    """Manage spacious canvas / explicit tools without modifying map data."""

    def __init__(self, studio):
        self.studio = studio
        self.focused = False
        self.left_open = False
        self.right_open = True
        self._remembered = (False, True)
        self._left_docks = []
        self._right_docks = []
        self._selected_left = None
        self._selected_right = studio._native_dock
        self._actions = []
        self._setting_combo = False
        self.game_mode = False
        self._editor_state = None
        self._configure_docks()
        self._compact_inspector()
        self._configure_toolbar()
        self._install_gameplay_mode()
        # Every File/View action changes the same QTabWidget. Without one
        # transition guard F1/F2/F3 or New Scene left the *game HUD* over an
        # editor surface with its tabs/toolbar still hidden.
        studio._compact_workspace = self
        studio.tabs.currentChanged.connect(self._page_switched)
        self.restore()
        # When a real map was loaded during Studio startup, open on the
        # actual map with the integrated game HUD rather than the Qt gallery.
        if studio.native_canvas.has_map():
            self.set_mode("game")

    def _configure_docks(self):
        studio = self.studio
        docks = studio.findChildren(QDockWidget)
        titles = {
            "Originalkarten": "Karten",
            "Sprite-Palette": "Sprite-Palette",
            "Karte & Minikarte": "Minikarte",
            "Grafikvorschau / Live-Reload": "Grafik",
            "Objekt-Inspector": "Objekt",
            "Originalkarte / Werkzeug-Inspector": "Karten-Inspector",
            "Animation / Frame-Test": "Animation",
            "Sandbox-Spiel-HUD / Live-Test": "Spiel-HUD",
            "Original-XAML-Grafiken / HUD-Test": "Original-HUD",
        }
        for dock in docks:
            area = studio.dockWidgetArea(dock)
            if area == Qt.DockWidgetArea.BottomDockWidgetArea:
                # Bottom notice is already represented by status and tooltips;
                # real bottom tools are reparented in the embedding adapter.
                dock.hide()
                continue
            if area not in (
                Qt.DockWidgetArea.LeftDockWidgetArea,
                Qt.DockWidgetArea.RightDockWidgetArea,
            ):
                continue
            original = dock.windowTitle()
            dock.setWindowTitle(titles.get(original, original))
            dock.setMinimumWidth(0)
            # Hiding is handled by the visible Palette/Inspector buttons.
            # A tiny per-dock X silently hid the selected tool while leaving
            # the dropdown on its old entry, making it hard to recover.
            dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
            dock.setAllowedAreas(
                Qt.DockWidgetArea.LeftDockWidgetArea
                | Qt.DockWidgetArea.RightDockWidgetArea
            )
            if area == Qt.DockWidgetArea.LeftDockWidgetArea:
                self._left_docks.append(dock)
                if "Palette" in original:
                    self._selected_left = dock
            else:
                self._right_docks.append(dock)
        if self._selected_left is None and self._left_docks:
            self._selected_left = self._left_docks[0]
        # A named combo in the toolbar exposes tools whose Qt dock-tabs
        # would otherwise require a tiny, hard-to-find overflow arrow.

    def _compact_inspector(self):
        """Keep right-hand editing controls readable at notebook widths."""
        inspector = self.studio.native_inspector
        for attribute, short_name in (
            ('engine_edit', 'Kachelgrafik bearbeiten'),
            ('map_visual', 'Originaltyp zuordnen'),
            ('clear_visual', 'Zuordnung löschen'),
            ('assign_surface', 'Bodengrafik testen'),
            ('clear_surface', 'Bodentest zurücksetzen'),
            ('assign_terrain', 'Höhengrafik testen'),
            ('clear_terrain', 'Höhentest zurücksetzen'),
        ):
            button = getattr(inspector, attribute)
            original = button.text()
            if not button.toolTip():
                button.setToolTip(original)
            button.setText(short_name)
        inspector.group.setWordWrap(True)

    def _action(self, toolbar, label, callback, *, tooltip="", shortcut=None):
        action = QAction(label, self.studio)
        if shortcut:
            action.setShortcut(shortcut)
        if tooltip:
            action.setToolTip(tooltip)
            action.setStatusTip(tooltip)
        action.triggered.connect(callback)
        toolbar.addAction(action)
        self._actions.append(action)
        return action

    def _configure_toolbar(self):
        studio = self.studio
        bars = studio.findChildren(QToolBar)
        toolbar = bars[0] if bars else QToolBar("Schnellzugriff", studio)
        if not bars:
            studio.addToolBar(toolbar)
        # Do NOT call QToolBar.clear() here. In Qt that may destroy actions
        # installed by the original menu_action helper, which are shared by
        # the File/View menus. The missing "Open original map", "Save" and
        # F1-F4 shortcuts were lost at embed time. removeAction() detaches
        # those shared commands from only this toolbar, preserving menus,
        # shortcut metadata and callback identities.
        for existing in tuple(toolbar.actions()):
            toolbar.removeAction(existing)
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        toolbar.setFloatable(False)
        self._toolbar = toolbar

        self._action(toolbar, "Öffnen", studio.choose_map,
                     tooltip="Originalkarte öffnen (Strg+O)")
        self._action(toolbar, "Karte", studio.show_native_map,
                     tooltip="Originalkarte und echte Spielsprites (F4)")
        self._action(toolbar, "Testfeld", studio.show_test_field,
                     tooltip="Testfeld mit Sprite-Platzierung (F2)")
        self.game_action = self._action(
            toolbar, "Spielmodus", self.toggle_mode,
            tooltip="Originalkarte mit zusammenhängendem unteren Test-HUD",
        )
        self.game_action.setCheckable(True)
        toolbar.addSeparator()
        self.palette_action = self._action(
            toolbar, "Palette", self.toggle_palette,
            tooltip="Linke Sprite-Palette ein-/ausblenden (F6)", shortcut="F6",
        )
        self.inspector_action = self._action(
            toolbar, "Inspector", self.toggle_inspector,
            tooltip="Rechte Werkzeuge ein-/ausblenden (F7)", shortcut="F7",
        )
        self.tool_picker = QComboBox(toolbar)
        self.tool_picker.setObjectName("compact_sandbox_tool_picker")
        self.tool_picker.setAccessibleName("Sandbox-Werkzeug auswählen")
        self.tool_picker.setToolTip(
            "Werkzeug wählen und direkt öffnen; auch Animation, HUD und Originalgrafik"
        )
        self.tool_picker.setMinimumWidth(120)
        self.tool_picker.setMaximumWidth(180)
        self.tool_picker.addItem("Werkzeug wählen …", None)
        for dock in self._right_docks:
            self.tool_picker.addItem(dock.windowTitle(), dock)
        self.tool_picker.currentIndexChanged.connect(self._tool_chosen)
        toolbar.addWidget(self.tool_picker)
        toolbar.addSeparator()
        self.focus_action = self._action(
            toolbar, "Fokus", self.toggle_focus,
            tooltip="Nur die Arbeitsfläche, ohne Seitenleisten (F9)", shortcut="F9",
        )
        self.focus_action.setCheckable(True)
        self.reset_action = self._action(
            toolbar, "Layout", self.restore,
            tooltip="Arbeitsansicht und Werkzeugbereiche zurücksetzen",
        )

        menu = next(
            (item for item in studio.menuBar().findChildren(QMenu)
             if item.title() == "Ansicht"),
            None,
        )
        # No new duplicate menu: the actions are in the toolbar even when
        # embedded Win32 focus routing doesn't dispatch menu shortcuts.
        if menu is not None:
            menu.addSeparator()
            for action in (self.game_action, self.palette_action,
                           self.inspector_action, self.focus_action,
                           self.reset_action):
                menu.addAction(action)

    def _install_gameplay_mode(self):
        """Overlay a live, right-anchored HUD on the original map view.

        takeCentralWidget() is essential: replacing the central widget
        directly would schedule the original tabs/canvas for Qt deletion.
        """
        from sandbox_gameplay_mode import EmbeddedGameplayHUD

        old_central = self.studio.takeCentralWidget()
        if old_central is not self.studio.tabs:
            raise RuntimeError("Der Originalkarten-Canvas wurde unerwartet ersetzt")
        self.game_host = GameplayMapHost(self.studio.tabs,self.studio)
        self.game_hud = EmbeddedGameplayHUD(self.studio,self.game_host)
        self.game_host.game_hud = self.game_hud
        self.game_hud.hide()
        self.game_hud.editor_requested.connect(lambda: self.set_mode("editor"))
        self.game_hud.inspect.clicked.connect(
            lambda: self.show_tool(self.studio._native_dock)
        )
        self.studio.setCentralWidget(self.game_host)

    def _page_switched(self, index):
        """Restore the editor AND the tools for the actual active surface.

        A game map's native inspector is not an isometric Testfeld editor:
        showing it beside the test scene hid the useful object/animation
        controls, particularly at 1020x680.
        """
        if self.game_mode and index != 3:
            self.set_mode("editor")
        if self.game_mode:
            return
        native = self.studio._native_dock
        obj = self.studio.inspector_dock
        # Keep user-selected cross-surface tools (e.g. asset preview) until
        # they explicitly change them; rehome context-dependent tools only.
        original_hud = getattr(self.studio, "_original_hud_dock", None)
        if index == 1:
            if self._selected_right in (
                native, self.studio._hud_dock, original_hud
            ):
                self._selected_right = obj
                self._apply()
        elif self._selected_right in (obj, self.studio._animation_dock):
            self._selected_right = native
            self._apply()

    def toggle_mode(self, _checked=False):
        self.set_mode("editor" if self.game_mode else "game")

    def set_mode(self, mode: str):
        """Switch only UI containers; preserve map, history and sprite state."""
        if mode not in ("game", "editor"):
            raise ValueError(f"Unbekannter Sandbox-Modus: {mode}")
        enable = mode == "game"
        if self.game_mode == enable:
            return
        studio = self.studio
        if enable:
            self._editor_state = (
                self.focused, self.left_open, self.right_open,
            )
            self.game_mode = True
            self.focused = False
            self.left_open = False
            self.right_open = False
            studio.tabs.setCurrentIndex(3)
            studio.tabs.tabBar().hide()
            self._toolbar.hide()
            self.game_hud.attach_minimap()
            self.game_hud.refresh_map_state()
            self.game_hud.show()
            self.game_host.position_game_hud()
        else:
            self.game_mode = False
            self.game_hud.hide()
            self.game_hud.detach_minimap()
            studio.tabs.tabBar().show()
            self._toolbar.show()
            self.focused, self.left_open, self.right_open = (
                self._editor_state or (False, False, True)
            )
            self._editor_state = None
        self.game_action.setChecked(enable)
        self.game_action.setText("Editor" if enable else "Spielmodus")
        self._apply()
        self.refresh_size()

    def _set_group(self, docks, visible, selected, *, show_all=False):
        # Multiple right docks created a row of microscopic, truncated Qt
        # tabs. The explicit dropdown makes every tool accessible while only
        # the selected pane takes space. Leave the two useful left tabs intact.
        for dock in docks:
            if visible and (show_all or dock is selected):
                dock.show()
            else:
                dock.hide()
        if visible and selected is not None:
            selected.raise_()

    def _apply(self):
        self._set_group(self._left_docks, self.left_open, self._selected_left,
                        show_all=True)
        self._set_group(self._right_docks, self.right_open, self._selected_right)
        self.focus_action.setChecked(self.focused)
        # A closed inspector must not leave the dropdown on its previous
        # selection: reselecting the same tool must reopen it reliably.
        selected = (self._selected_right
                    if self.right_open and not self.focused else None)
        idx = self.tool_picker.findData(selected) if selected else 0
        self._setting_combo = True
        try:
            self.tool_picker.setCurrentIndex(max(0, idx))
        finally:
            self._setting_combo = False
        self._fit_panels()

    def _fit_panels(self):
        studio = self.studio
        width = max(1, studio.width())
        if self.right_open and self._selected_right is not None:
            studio.resizeDocks(
                [self._selected_right], [min(310, max(275, width // 4))],
                Qt.Orientation.Horizontal,
            )
        if self.left_open and self._selected_left is not None:
            studio.resizeDocks(
                [self._selected_left], [min(245, max(190, width // 5))],
                Qt.Orientation.Horizontal,
            )

    def refresh_size(self):
        if self.game_mode:
            # Keep the map fullscreen *underneath* the HUD. Only the actual
            # commands intercept clicks; left/beyond the HUD is real canvas.
            self.game_host.position_game_hud()
            from PySide6.QtCore import QSize
            height = self.game_hud.height()
            icon_size = 32 if height < 135 else 42
            for button, _ in self.game_hud._visible_buttons:
                button.setIconSize(QSize(icon_size,icon_size))
        elif not self.focused:
            self._fit_panels()

    def restore(self):
        """Predictable startup: big map, inspector accessible, palette on demand."""
        if self.game_mode:
            self.set_mode("editor")
        self.focused = False
        self.left_open = False
        self.right_open = True
        self._selected_right = self.studio._native_dock
        self._apply()

    def set_focus(self, enabled):
        if self.game_mode:
            self.set_mode("editor")
        enabled = bool(enabled)
        if self.focused == enabled:
            return
        if enabled:
            self._remembered = (self.left_open, self.right_open)
            self.left_open = False
            self.right_open = False
            self.focused = True
        else:
            self.focused = False
            self.left_open, self.right_open = self._remembered
        self._apply()

    def toggle_focus(self, _checked=False):
        self.set_focus(not self.focused)

    def toggle_palette(self, _checked=False):
        if self.game_mode:
            self.set_mode("editor")
        if self.focused:
            self.set_focus(False)
        self.left_open = not self.left_open
        self._apply()

    def toggle_inspector(self, _checked=False):
        if self.game_mode:
            self.set_mode("editor")
        if self.focused:
            self.set_focus(False)
        self.right_open = not self.right_open
        self._apply()

    def show_tool(self, dock):
        """Show the chosen tab even from a focus-only or collapsed state."""
        if dock not in self._right_docks and dock not in self._left_docks:
            return
        if self.game_mode:
            self.set_mode("editor")
        if self.focused:
            self.set_focus(False)
        if dock in self._right_docks:
            self._selected_right = dock
            self.right_open = True
        else:
            self._selected_left = dock
            self.left_open = True
        self._apply()
        self._setting_combo = True
        try:
            idx = self.tool_picker.findData(dock)
            if idx >= 0:
                self.tool_picker.setCurrentIndex(idx)
        finally:
            self._setting_combo = False

    def _tool_chosen(self, index):
        if self._setting_combo or index <= 0:
            return
        dock = self.tool_picker.itemData(index)
        if dock is not None:
            self.show_tool(dock)

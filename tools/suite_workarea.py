"""Local two-axis overflow and focus navigation for existing Tk workspaces."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from weakref import WeakSet
from types import SimpleNamespace

from suite_usability import ScrollableColumn


class ScrollableWorkarea(ScrollableColumn):
    """Keep widget identities and native child scrolling while exposing overflow."""

    def __init__(self, master, *, background="#22252a", style=None,
                 min_width=0, min_height=0, horizontal=True, content=None, hide_unused=False):
        self.hide_unused = hide_unused
        self.horizontal = horizontal
        self.min_width = min_width
        self.min_height = min_height
        self._refresh_job = None
        self._registered = WeakSet()
        super().__init__(master, background=background)
        self.canvas.pack_forget()
        self.scrollbar.pack_forget()
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.ybar = self.scrollbar
        self.xbar = ttk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)
        if horizontal:
            self.xbar.grid(row=1, column=0, sticky="ew")
        self.canvas.configure(xscrollcommand=self.xbar.set, takefocus=True)
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        if content is not None:
            self.set_content(content)
        elif style:
            self.body.configure(style=style)
        self._top = self.winfo_toplevel()
        self._wheel_bindings = []
        for sequence in ("<MouseWheel>", "<Shift-MouseWheel>", "<Button-4>", "<Button-5>"):
            horizontal = sequence == "<Shift-MouseWheel>"
            command = self._top.bind(sequence, lambda event, horizontal=horizontal:
                                     self._route_wheel(event, horizontal), add="+")
            self._wheel_bindings.append((sequence, command))
        self.bind("<Destroy>", self._destroyed, add="+")
        self.refresh()

    def set_content(self, widget):
        """Embed a widget constructed inside this canvas, preserving its identity."""
        if widget.master is not self.canvas:
            raise ValueError("Workarea content must be constructed inside its canvas")
        self.body.destroy()
        self.body = widget
        self.canvas.itemconfigure(self._item, window=widget)
        widget.bind("<Configure>", self._body_changed, add="+")
        widget.bind("<<NotebookTabChanged>>", self._tab_changed, add="+")
        self.refresh()

    def _destroyed(self, event):
        if event.widget is not self:
            return
        if self._refresh_job is not None:
            self.after_cancel(self._refresh_job)
            self._refresh_job = None
        for sequence, command in self._wheel_bindings:
            try:
                self._top.unbind(sequence, command)
            except tk.TclError:
                pass

    def _tab_changed(self, _event=None):
        self._jump_end = None
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)
        self.refresh()

    def _body_changed(self, _event=None):
        self.refresh()

    def _viewport_changed(self, _event=None):
        self.refresh()

    def refresh(self):
        if self._refresh_job is None:
            self._refresh_job = self.after_idle(self._fit)

    def _preferred_size(self):
        if isinstance(self.body, ttk.Notebook) and self.body.select():
            selected = self.body.nametowidget(self.body.select())
            chrome = max(0, self.body.winfo_reqheight() - max(
                self.body.nametowidget(tab).winfo_reqheight() for tab in self.body.tabs()))
            return selected.winfo_reqwidth(), selected.winfo_reqheight() + chrome
        return self.body.winfo_reqwidth(), self.body.winfo_reqheight()

    def _fit(self):
        self._refresh_job = None
        if not self.winfo_exists():
            return
        width, height = self._preferred_size()
        width = max(self.canvas.winfo_width(), self.min_width,
                    width if self.horizontal else 0)
        height = max(self.canvas.winfo_height(), self.min_height, height)
        current_width = int(float(self.canvas.itemcget(self._item, "width")))
        current_height = int(float(self.canvas.itemcget(self._item, "height")))
        if (current_width, current_height) != (width, height):
            self.canvas.itemconfigure(self._item, width=width, height=height)
        self._sync_region()
        if self.hide_unused:
            if self.horizontal and width > self.canvas.winfo_width() + 1:
                self.xbar.grid()
            else:
                self.xbar.grid_remove()
            if height > self.canvas.winfo_height() + 1:
                self.ybar.grid()
            else:
                self.ybar.grid_remove()
        self.bind_mousewheel()

    def bind_mousewheel(self):
        nodes = [self.canvas, self.body]
        while nodes:
            widget = nodes.pop()
            if widget is not self and isinstance(widget, ScrollableColumn):
                continue
            nodes.extend(widget.winfo_children())
            if widget in self._registered:
                continue
            self._registered.add(widget)
            widget._suite_workarea_owner = self
            widget.bind("<MouseWheel>", self._scroll, add="+")
            widget.bind("<Shift-MouseWheel>", self._scroll_horizontal, add="+")
            widget.bind("<Button-4>", self._scroll, add="+")
            widget.bind("<Button-5>", self._scroll, add="+")
            widget.bind("<FocusIn>", lambda event: self.reveal(event.widget), add="+")
            widget.bind("<Next>", lambda event: self._page(event, 1), add="+")
            widget.bind("<Prior>", lambda event: self._page(event, -1), add="+")

    def _route_wheel(self, event, horizontal=False):
        """Windows may target the focused scrollbar or top-level, not the pointer."""
        try:
            hit = self._top.winfo_containing(event.x_root, event.y_root)
        except (tk.TclError, AttributeError):
            return None
        node, owner = hit, None
        while node is not None:
            owner = (getattr(node, "_suite_workarea_owner", None) or
                     getattr(node, "_suite_scroll_owner", None))
            if isinstance(node, ScrollableColumn):
                owner = node
            if owner is not None:
                break
            node = getattr(node, "master", None)
        if owner is not self:
            if isinstance(owner, ScrollableWorkarea) or owner is None or horizontal:
                return None
            # Existing vertical specialist forms retain their own wheel behavior.
            ancestor = getattr(owner, "master", None)
            while ancestor is not None and ancestor is not self.body:
                ancestor = getattr(ancestor, "master", None)
            return owner._scroll(event) if ancestor is self.body else None
        if hit is event.widget and hit.winfo_class() in {"Text", "Treeview", "Listbox", "TCombobox"}:
            return None  # the widget's class binding has already handled it
        routed = SimpleNamespace(widget=hit, delta=getattr(event,"delta",0),
                                 num=getattr(event,"num",None))
        axis = "x" if horizontal else "y"
        amount = self._direction(routed)
        if self._native_scrolls(hit, axis, amount):
            getattr(hit, axis + "view_scroll")(amount, "units")
            return "break"
        return self._move(routed, axis, amount, "units")

    @staticmethod
    def _direction(event):
        delta = getattr(event, "delta", 0)
        if delta:
            return -max(1, abs(int(delta / 120))) if delta > 0 else max(1, abs(int(delta / 120)))
        return -1 if getattr(event, "num", None) == 4 else 1

    def _native_scrolls(self, widget, axis, direction):
        if widget is self.canvas or widget.winfo_class() not in {
                "Text", "Treeview", "Listbox", "TCombobox", "Canvas"}:
            return False
        try:
            low, high = getattr(widget, axis + "view")()
            return low > 0 if direction < 0 else high < 1
        except (AttributeError, tk.TclError, ValueError):
            return False

    def _move(self, event, axis, amount, units):
        if self._native_scrolls(event.widget, axis, amount):
            return None
        view = getattr(self.canvas, axis + "view")
        before = view()
        getattr(self.canvas, axis + "view_scroll")(amount, units)
        return "break" if before != view() else None

    def _scroll(self, event):
        return self._move(event, "y", self._direction(event), "units")

    def _scroll_horizontal(self, event):
        return self._move(event, "x", self._direction(event), "units")

    def _page(self, event, direction):
        return self._move(event, "y", direction, "pages")

    def reveal(self, widget):
        if not widget.winfo_exists() or not widget.winfo_ismapped():
            return
        self.canvas.update_idletasks()
        for axis, start, extent, available in (
            ("x", widget.winfo_rootx() - self.body.winfo_rootx(),
             widget.winfo_width(), self.canvas.winfo_width()),
            ("y", widget.winfo_rooty() - self.body.winfo_rooty(),
             widget.winfo_height(), self.canvas.winfo_height()),
        ):
            visible = getattr(self.canvas, "canvas" + axis)(0)
            wanted = start if start < visible else max(visible, start + extent - available)
            total = self.canvas.bbox(self._item)[2 if axis == "x" else 3]
            if total > available:
                getattr(self.canvas, axis + "view_moveto")(max(0, wanted) / total)

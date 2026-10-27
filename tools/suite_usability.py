"""Small GUI usability primitives for the Universal Sprite Suite.

Only presentation and callback sequencing live here: no sprite, game,
atlas, release or installer changes. An unsuccessful tool step must never
trigger the next step in a workflow.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk


class CompactActionBar(ttk.Frame):
    """Prioritized actions: obvious daily buttons plus a named overflow menu.

    More than one wide row of actions leaves no workspace at 1020x680.
    This is presentation-only: every original callback is retained and
    discoverable without hiding it behind inaccessible clipped widgets.
    """

    def __init__(self, parent, *, primary=(), more=(),
                 overflow_label="Weitere Aktionen ▾", padding=4):
        super().__init__(parent)
        self.buttons = {}
        for name, callback in primary:
            button = ttk.Button(self, text=name, command=callback)
            button.pack(side="left", padx=(0, padding))
            self.buttons[name] = button
        self.more_button = None
        self.menu = None
        if more:
            self.more_button = ttk.Menubutton(self, text=overflow_label)
            self.menu = tk.Menu(self.more_button, tearoff=False)
            for name, callback in more:
                self.menu.add_command(label=name, command=callback)
            self.more_button.configure(menu=self.menu)
            self.more_button.pack(side="left")

    def menu_names(self):
        if self.menu is None:
            return []
        return [self.menu.entrycget(i, "label")
                for i in range(self.menu.index("end") + 1)]


class ScrollableColumn(ttk.Frame):
    """Fill-width vertical form with a persistent usable scrollbar."""

    def __init__(self, parent, *, background="#22252a"):
        super().__init__(parent)
        self.canvas = tk.Canvas(
            self, background=background, bd=0, highlightthickness=0,
            takefocus=False, width=400, height=320,
        )
        self.scrollbar = ttk.Scrollbar(
            self, orient="vertical", command=self.canvas.yview,
        )
        self.scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body = ttk.Frame(self.canvas)
        self._item = self.canvas.create_window(
            0, 0, window=self.body, anchor="nw",
        )
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self._jump_end = None
        self.body.bind("<Configure>", self._body_changed, add="+")
        self.canvas.bind("<Configure>", self._viewport_changed, add="+")

    def _sync_region(self):
        bounds = self.canvas.bbox("all")
        if bounds:
            x0, y0, x1, y1 = bounds
            if self._jump_end is not None:
                y1 = max(y1, self._jump_end)
            self.canvas.configure(scrollregion=(x0, y0, x1, y1))

    def _body_changed(self, _event=None):
        self._sync_region()

    def _viewport_changed(self, event):
        self.canvas.itemconfigure(self._item, width=event.width)
        self._sync_region()

    def _scroll(self, event):
        if getattr(event, "delta", 0):
            turns = -int(event.delta / 120)
            if not turns:
                turns = -1 if event.delta > 0 else 1
            self.canvas.yview_scroll(turns, "units")
        elif getattr(event, "num", None) == 4:
            self.canvas.yview_scroll(-1, "units")
        elif getattr(event, "num", None) == 5:
            self.canvas.yview_scroll(1, "units")
        return "break"

    def bind_mousewheel(self):
        """Bind only this form's descendants (no global wheel interception)."""
        nodes = [self.canvas, self.body]
        while nodes:
            widget = nodes.pop()
            nodes.extend(widget.winfo_children())
            if getattr(widget, "_suite_scroll_owner", None) is self:
                continue
            widget._suite_scroll_owner = self
            widget.bind("<MouseWheel>", self._scroll, add="+")
            widget.bind("<Button-4>", self._scroll, add="+")
            widget.bind("<Button-5>", self._scroll, add="+")
            if isinstance(widget, (ttk.Entry, ttk.Button, ttk.Combobox,
                                   ttk.Checkbutton, ttk.Radiobutton)):
                widget.bind(
                    "<FocusIn>",
                    lambda _event, target=widget: self.reveal(target),
                    add="+",
                )

    def show_at_top(self, widget, *, margin=12):
        """Bring a selected section near the top, exposing its fields below.

        Unlike focus-driven reveal(), a jump action shouldn't count a heading
        barely visible at the viewport's bottom as a successful navigation.
        """
        self.canvas.update_idletasks()
        bounds = self.canvas.bbox("all")
        if not bounds:
            return
        height = self.canvas.winfo_height()
        offset = widget.winfo_rooty() - self.body.winfo_rooty()
        destination = max(bounds[1], offset - max(0, margin))
        # The final section often has only one short row beneath its header.
        # Natural scroll bounds would keep that header stuck at the bottom
        # of the viewport. Extend the canvas scroll region (NOT the file or
        # the form contents) so the requested section can actually sit on top.
        self._jump_end = max(bounds[3], destination + height)
        self._sync_region()
        extent = self._jump_end - bounds[1]
        if extent > 0:
            self.canvas.yview_moveto(
                (destination - bounds[1]) / extent
            )

    def reveal(self, widget):
        """Scroll a control into view for keyboard focus navigation."""
        self.canvas.update_idletasks()
        offset = widget.winfo_rooty() - self.body.winfo_rooty()
        top = self.canvas.canvasy(0)
        height = self.canvas.winfo_height()
        wanted = offset if offset < top else (
            offset + widget.winfo_height() - height
            if offset + widget.winfo_height() > top + height else top
        )
        bounds = self.canvas.bbox("all")
        if bounds and bounds[3] - bounds[1] > height:
            extent = bounds[3] - bounds[1]
            fraction = (wanted - bounds[1]) / extent
            self.canvas.yview_moveto(
                max(0.0, min((extent - height) / extent, fraction))
            )


def run_then_success(app, args: list[str], label: str, after, *,
                     next_step: str) -> bool:
    """Start an action and call after only when its exit status is zero."""
    if app.runner.busy:
        messagebox.showinfo(
            "Vorgang läuft",
            "Bitte zuerst den laufenden Vorgang beenden oder abbrechen.",
            parent=app,
        )
        return False

    def completed(exit_code):
        if completed in app.done_hooks:
            app.done_hooks.remove(completed)
        if exit_code == 0:
            app.after(0, after)
        else:
            app.log(
                f"Nicht ausgeführt: {next_step}. "
                f"Der vorherige Vorgang '{label}' endete mit Code {exit_code}.",
                "bad",
            )

    app.done_hooks.append(completed)
    try:
        started = app.run(args, label)
    except Exception:
        app.done_hooks.remove(completed)
        raise
    # A job can be declined between the early runner.busy check and
    # Runner.start(), e.g. when a workflow callback races a pending action.
    # Leaving the hook here would import ORA files or open an HTML editor
    # after an unrelated later job happened to exit successfully.
    if started is False:
        app.done_hooks.remove(completed)
        app.log(
            f"Nicht gestartet: {label}. Folgeaktion '{next_step}' verworfen.",
            "warn",
        )
        return False
    return True

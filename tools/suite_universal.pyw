"""Stronghold Europe / ORIGINS - Universal-Suite (Grafik SH1DE -> SHCDE, arbeitet mit dem vorhandenen Script Extender).

Baut auf der Suite-Zentrale (tools/suite_center.pyw) und der Werkstatt
(tools/suite.pyw) auf und ergaenzt:

  Asset-Katalog         alle Grafikgruppen thematisch, vier Ansichten je Frame,
                        Ersetzen / Uebernehmen / Richtungen+Schaden (Block) /
                        Umlenken / Erweiterungen / Anwenden
  Diagnose & Reparatur  die bekannten Fehlerklassen mechanisch pruefen
  Sandkasten            Aenderungen auf einer kleinen Karte mit Spielleiste sehen
  Editor & Austausch    HTML-Sprite-Editor, AtlasBuilder (SE-Atlas), ORA-Objekte
  Ziele & Mods          Spielziele, statische Assetpakete, Modinstallation und Sicherungen

Nachsicht ist Standard: Werkzeuge warnen statt zu blockieren. Der Schalter
"Streng" oben rechts stellt das blockierende Verhalten fuer alle Aufrufe her.
Jeder Knopf ruft dasselbe Kommandozeilenwerkzeug auf, das man auch von Hand
starten kann; die Ausgabe erscheint unten im Protokoll.
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import queue
import re
import threading
import sys
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "src"))

_loader = importlib.machinery.SourceFileLoader("suite_center_module", str(ROOT / "tools" / "suite_center.pyw"))
_spec = importlib.util.spec_from_loader(_loader.name, _loader)
center = importlib.util.module_from_spec(_spec)
_loader.exec_module(center)
workshop = center.workshop

import asset_katalog as katalog  # noqa: E402
from suite_usability import CompactActionBar, ScrollableColumn, run_then_success

TOOLS = ROOT / "tools"
BG, PANEL, FG, MUTED, ACCENT = workshop.BG, workshop.PANEL, workshop.FG, workshop.MUTED, workshop.ACCENT
ACTION_COLOURS = {"KEEP_CRUSADER": "#8a8a8a", "REPLACE_EXACT": "#6cbf5a", "REPLACE_DERIVED": "#5a8fd6",
                  "REVIEW_MANUAL": "#d9a14a"}
SIDES = [("geliefert", "Ausgeliefert"), ("crusader", "Crusader-Original"), ("stronghold1", "Stronghold 1"),
         ("arbeit", "Arbeitskopie")]


def tool(name: str) -> str:
    return str(TOOLS / name)


def labelled_entry(parent, label, default="", width=14):
    ttk.Label(parent, text=label, style="Muted.TLabel").pack(side="left", padx=(8, 3))
    var = tk.StringVar(value=default)
    ttk.Entry(parent, textvariable=var, width=width).pack(side="left")
    return var



# ====================================================================== Sprache DE / EN

SETTINGS = ROOT / "config" / "suite-einstellungen.json"


class Language:
    """DE/EN-Umschaltung: deutsche Originaltexte -> config/suite-sprachen.json.

    Umgesetzt werden Beschriftungen, Knoepfe, Reiter, Tabellenkoepfe, Baum-
    eintraege der Kategorien sowie Titel und Text von Meldungs- und
    Eingabefenstern. Fehlt eine Uebersetzung, bleibt der deutsche Text stehen.
    Protokollausgaben der Kommandozeilenwerkzeuge bleiben deutsch.
    """

    def __init__(self):
        data = katalog.load_json(ROOT / "config" / "suite-sprachen.json", {})
        self.table = data.get("en", {})
        self.code = katalog.load_json(SETTINGS, {}).get("sprache", "de")
        self._patched = False

    @staticmethod
    def _dynamic_en(text):
        # The count is real profile data, not a fixed string for one machine.
        match = re.fullmatch(
            r"([\d.,]+) Gruppen im Profil\. ([\d.,]+) Frames", text
        )
        if match:
            return f"{match[1]} groups in profile. {match[2]} frames"
        return text

    @staticmethod
    def _dynamic_de(text):
        match = re.fullmatch(
            r"([\d.,]+) groups in profile\. ([\d.,]+) frames", text
        )
        if match:
            return f"{match[1]} Gruppen im Profil. {match[2]} Frames"
        return text

    def tr(self, text):
        if not isinstance(text, str):
            return text
        if self.code != "en":
            return self._dynamic_de(text)
        if text in self.table:
            return self.table[text]
        for prefix in ("■ ", "● ", "• "):
            if text.startswith(prefix) and text[len(prefix):] in self.table:
                return prefix + self.table[text[len(prefix):]]
        return self._dynamic_en(self.table.get(text.strip(), text))

    def save(self):
        data = katalog.load_json(SETTINGS, {})
        data["sprache"] = self.code
        katalog.save_json(SETTINGS, data)

    def patch_dialogs(self):
        from tkinter import messagebox as mb, simpledialog as sd, filedialog as fd

        # Tk modules are global. Repeated Suite instantiation (tests or
        # reopening a window) must not stack dozens of translating wrappers.
        # Each module keeps a reference to the currently active language.
        for module in (mb, sd, fd):
            module._sprite_suite_language = self
        if self._patched:
            return
        self._patched = True

        def wrap(module, name, positional):
            original = getattr(module, name)
            if getattr(original, "_sprite_suite_translated", False):
                return

            def translated(*args, **kwargs):
                language = module._sprite_suite_language
                args = list(args)
                for i in range(min(positional, len(args))):
                    args[i] = language.tr(args[i])
                for key in ("title", "message", "prompt"):
                    if key in kwargs:
                        kwargs[key] = language.tr(kwargs[key])
                return original(*args, **kwargs)
            translated._sprite_suite_translated = True
            setattr(module, name, translated)

        for name in ("showinfo", "showerror", "showwarning", "askyesno", "askokcancel", "askquestion"):
            wrap(mb, name, 2)
        for name in ("askstring", "askinteger", "askfloat"):
            wrap(sd, name, 2)
        for name in ("askopenfilename", "askopenfilenames", "askdirectory", "asksaveasfilename"):
            wrap(fd, name, 0)

    def apply(self, root):
        """Alle sichtbaren Texte in die gewaehlte Sprache setzen (umkehrbar)."""
        reverse = {v: k for k, v in self.table.items()}
        stack = [root]
        visited = set()
        while stack:
            widget = stack.pop()
            if str(widget) in visited:
                continue
            visited.add(str(widget))
            stack.extend(widget.winfo_children())
            if isinstance(widget, (ttk.Menubutton, tk.Menubutton)):
                # Tk popup menus are not always reported as the children of
                # their menubutton. Follow the actual 'menu' widget path.
                try:
                    menu = widget.nametowidget(widget.cget("menu"))
                    stack.append(menu)
                except (tk.TclError, KeyError):
                    pass
            if isinstance(widget, tk.Menu):
                # Menus are widgets, but individual commands are NOT Tk
                # descendants. Translate them explicitly and remember the
                # original German text for reversible DE <-> EN switching.
                originals = getattr(widget, "_sprache_menu_labels", {})
                end = widget.index("end")
                if end is not None:
                    for entry in range(end + 1):
                        try:
                            if widget.type(entry) not in (
                                "command", "checkbutton", "radiobutton", "cascade"
                            ):
                                continue
                            current = widget.entrycget(entry, "label")
                            original = originals.get(entry)
                            if original is None or current not in (
                                original, self.table.get(original, original)
                            ):
                                original = reverse.get(current, current)
                                originals[entry] = original
                            widget.entryconfigure(entry, label=self.tr(original))
                        except tk.TclError:
                            continue
                widget._sprache_menu_labels = originals
            try:
                if "text" in widget.keys():
                    current = widget.cget("text")
                    original = getattr(widget, "_sprache_de", None)
                    if isinstance(current, str) and current:
                        known = ({original, self.table.get(original),
                                  self._dynamic_en(original)} if original else set())
                        if current not in known:
                            original = self._dynamic_de(reverse.get(current, current))
                            widget._sprache_de = original
                        widget.configure(text=self.tr(original))
            except (tk.TclError, AttributeError):
                pass
            if isinstance(widget, ttk.Notebook):
                store = getattr(widget, "_sprache_tabs", {})
                for tab in widget.tabs():
                    if tab not in store:
                        store[tab] = reverse.get(widget.tab(tab, "text"), widget.tab(tab, "text"))
                    widget.tab(tab, text=self.tr(store[tab]))
                widget._sprache_tabs = store
            if isinstance(widget, ttk.Treeview):
                store = getattr(widget, "_sprache_heads", {})
                for column in ("#0", *widget["columns"]):
                    try:
                        if column not in store:
                            store[column] = widget.heading(column, "text")
                        if store[column]:
                            widget.heading(column, text=self.tr(store[column]))
                    except tk.TclError:
                        pass
                widget._sprache_heads = store


LANG = Language()
tr = LANG.tr


# ====================================================================== Katalog

class CatalogTab(ttk.Frame):
    PAGE = 40
    THUMB = 92

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.group: str | None = None
        self.frames: list[dict] = []
        self.page = 0
        self.selected: str | None = None
        # Tree rebuilds generate queued <<TreeviewSelect>> events; these
        # must never launch stale group loads or clear a deliberate selection.
        self._tree_rebuilding = False
        self.photos: list = []
        self.detail_photos: list = []

        top = ttk.Frame(self)
        top.pack(fill="x", padx=8, pady=(8, 2))
        ttk.Label(top, text="Asset-Katalog", style="Title.TLabel").pack(side="left")
        ttk.Label(top, text="  thematisch geordnet – ansehen, bearbeiten, vergleichen",
                  style="Muted.TLabel").pack(side="left")
        self.catalog_actions = CompactActionBar(
            self,
            primary=(("Neu laden", self.load_tree),),
            more=(
                ("Kategorie anlegen", self.new_category),
                ("Gruppe zuordnen", self.assign_group),
                ("Erweiterung anlegen", self.new_extension),
                ("Erweiterung binden", self.bind_extension),
            ),
            overflow_label="Gruppen & Erweiterungen ▾",
        )
        self.catalog_actions.pack(fill="x", padx=8, pady=(0, 3))

        body = ttk.PanedWindow(self, orient="horizontal")
        body.pack(fill="both", expand=True, padx=8, pady=4)
        left = ttk.Frame(body)
        right = ttk.Frame(body)
        body.add(left, weight=0)
        body.add(right, weight=1)

        search = ttk.Frame(left)
        search.pack(fill="x")
        ttk.Label(search, text="Suche:", style="Muted.TLabel").pack(side="left")
        self.filter = tk.StringVar()
        entry = ttk.Entry(search, textvariable=self.filter, width=24)
        entry.pack(side="left", padx=4)
        entry.bind("<KeyRelease>", lambda _e: self.fill_tree())
        ttk.Button(
            search, text="Leeren", width=6, command=self.clear_search
        ).pack(side="left", padx=(0, 3))
        self.tree = ttk.Treeview(left, show="tree", height=30)
        self.tree.column("#0", width=300)
        self.tree.pack(fill="both", expand=True, pady=4)
        self.tree.bind("<<TreeviewSelect>>", self.tree_selected)
        self.tree_status = ttk.Label(
            left, text="", style="Muted.TLabel", wraplength=290
        )
        self.tree_status.pack(fill="x")

        head = ttk.Frame(right)
        head.pack(fill="x")
        self.head = ttk.Label(
            head, text="Links eine Gruppe wählen.", style="Head.TLabel",
            wraplength=640,
        )
        self.head.pack(side="left", fill="x", expand=True)
        view_row = ttk.Frame(right)
        view_row.pack(fill="x", pady=(2, 1))
        self.side = tk.StringVar(value="geliefert")
        ttk.Label(view_row, text="Ansicht:", style="Muted.TLabel").pack(
            side="left", padx=(0, 4)
        )
        box = ttk.Combobox(
            view_row, values=[s for s, _ in SIDES],
            textvariable=self.side, state="readonly", width=12,
        )
        box.pack(side="left")
        box.bind("<<ComboboxSelected>>", lambda _e: self.show_page())
        ttk.Button(
            view_row, text="Ansichten vorbereiten",
            command=self.prepare,
        ).pack(side="left", padx=6)
        self.details_button = ttk.Button(
            view_row, text="Bearbeiten ausblenden",
            command=self.toggle_edit_panel,
        )
        self.details_button.pack(side="right")
        nav_row = ttk.Frame(right)
        nav_row.pack(fill="x", pady=(0, 2))
        ttk.Button(nav_row, text="◀ Zurück", width=12,
                   command=lambda: self.turn(-1)).pack(side="left")
        self.page_label = ttk.Label(nav_row, text="", style="Muted.TLabel")
        self.page_label.pack(side="left", padx=4)
        ttk.Button(nav_row, text="Weiter ▶", width=12,
                   command=lambda: self.turn(1)).pack(side="left")
        ttk.Label(nav_row, text="Index:", style="Muted.TLabel").pack(
            side="left", padx=(9, 3)
        )
        self.jump = tk.StringVar()
        jump = ttk.Entry(nav_row, textvariable=self.jump, width=7)
        jump.pack(side="left")
        jump.bind("<Return>", lambda _e: self.jump_to())
        legend = ttk.Menubutton(nav_row, text="Statusfarben ▾")
        legend_menu = tk.Menu(legend, tearoff=False)
        for text, colour in (
            ("Crusader behalten", ACTION_COLOURS["KEEP_CRUSADER"]),
            ("SH1 exakt", ACTION_COLOURS["REPLACE_EXACT"]),
            ("SH1 angepasst", ACTION_COLOURS["REPLACE_DERIVED"]),
            ("manuell geprüft", ACTION_COLOURS["REVIEW_MANUAL"]),
            ("umgelenkt", "#b06ad9"),
            ("geändert (Arbeitskopie)", "#e05050"),
        ):
            legend_menu.add_command(
                label=f"■ {text}", foreground=colour,
                command=lambda label=text: messagebox.showinfo(
                    "Statusfarbe", label, parent=self
                ),
            )
        legend.configure(menu=legend_menu)
        legend.pack(side="right")

        split = ttk.PanedWindow(right, orient="vertical")
        split.pack(fill="both", expand=True)
        grid_holder = ttk.Frame(split)
        detail_holder = ttk.Frame(split)
        self.preview_split = split
        self.detail_holder = detail_holder
        split.add(grid_holder, weight=3)
        split.add(detail_holder, weight=2)
        self.grid = tk.Canvas(grid_holder, bg=PANEL, highlightthickness=0, height=330)
        self.grid_scrollbar = ttk.Scrollbar(
            grid_holder, orient="vertical", command=self.grid.yview
        )
        self.grid_scrollbar.pack(side="right", fill="y")
        self.grid.pack(side="left", fill="both", expand=True)
        self.grid.configure(yscrollcommand=self.grid_scrollbar.set)
        self.grid.bind("<Button-1>", self.grid_click)
        self.grid.bind("<MouseWheel>", self._grid_wheel)
        self.grid.bind("<Configure>", lambda _e: self.show_page())

        self.detail = tk.Canvas(detail_holder, bg="#25272b", highlightthickness=0, height=260)
        self.detail_scroll = ttk.Scrollbar(
            detail_holder, orient="horizontal", command=self.detail.xview
        )
        self.detail_scroll.pack(side="bottom", fill="x")
        self.detail.pack(fill="both", expand=True, side="left")
        self.detail.configure(xscrollcommand=self.detail_scroll.set)
        actions_host = ttk.Frame(detail_holder)
        self.actions_host = actions_host
        self._edit_panel_visible = True
        actions_host.pack(side="right", fill="y", padx=6)
        # Keep the final, deliberate profile action visible even at 680px.
        self.apply_button = ttk.Button(
            actions_host, text="Aenderungen anwenden (Profil)",
            command=self.apply,
        )
        self.apply_button.pack(side="bottom", fill="x", pady=(4, 0))
        self.actions_scroll = ScrollableColumn(actions_host, background=BG)
        self.actions_scroll.canvas.configure(width=315)
        self.actions_scroll.pack(side="top", fill="both", expand=True)
        actions = self.actions_scroll.body
        self.info = ttk.Label(actions, text="", style="Muted.TLabel", justify="left", wraplength=300)
        self.info.pack(anchor="w", pady=(0, 6))
        for text, command in (("Ersetzen durch Bild ...", self.replace_image),
                              ("Uebernehmen aus ...", self.take_over),
                              ("Auf Original zuruecksetzen", self.reset_frame),
                              ("Block kopieren (Richtung/Schaden) ...", self.copy_block),
                              ("Objekt umlenken (ganz!) ...", self.redirect),
                              ("Im HTML-Editor bearbeiten", self.to_editor),
                              ("Im Sandkasten zeigen", self.to_sandbox)):
            ttk.Button(actions, text=text, command=command).pack(fill="x", pady=2)
        self.mode = tk.StringVar(value="fusspunkt")
        row = ttk.Frame(actions)
        row.pack(fill="x", pady=(8, 0))
        ttk.Label(row, text="Einpassen:", style="Muted.TLabel").pack(side="left")
        ttk.Combobox(row, values=list(katalog.ANCHORS), textvariable=self.mode, state="readonly",
                     width=12).pack(side="left", padx=4)
        self.mirror = tk.BooleanVar(value=False)
        ttk.Checkbutton(actions, text="spiegeln", variable=self.mirror).pack(anchor="w")
        offs = ttk.Frame(actions)
        offs.pack(fill="x")
        self.dx = labelled_entry(offs, "dx", "0", 4)
        self.dy = labelled_entry(offs, "dy", "0", 4)
        self.actions_scroll.bind_mousewheel()

        # Until a frame is picked, use the full right pane to browse frames.
        # The lower preview/editor automatically opens on a real selection.
        self._set_edit_panel_visible(False)
        self.app.done_hooks.append(self._after_tool)
        self.after(300, self.load_tree)

    def _set_edit_panel_visible(self, visible):
        if self._edit_panel_visible == bool(visible):
            return
        self._edit_panel_visible = bool(visible)
        if self._edit_panel_visible:
            self.preview_split.add(self.detail_holder, weight=2)
            self.details_button.configure(text=LANG.tr("Vorschau schließen"))
        else:
            self.preview_split.forget(self.detail_holder)
            self.details_button.configure(text=LANG.tr("Vorschau / Bearbeiten"))

    def toggle_edit_panel(self):
        """Open or collapse preview and editor without discarding selection."""
        self._set_edit_panel_visible(not self._edit_panel_visible)

    # ------------------------------------------------------------ tree
    def load_tree(self):
        try:
            self.data = katalog.category_tree()
        except Exception as exc:
            self.data = {"kategorien": []}
            self.app.log(f"Katalog nicht lesbar: {exc}", "bad")
        self.fill_tree()

    def clear_search(self):
        self.filter.set("")
        self.fill_tree()

    def fill_tree(self):
        """Rebuild navigation without losing current group or firing stale events.

        Refresh, language switching and delayed category loads all replace the
        Tk Treeview. A plain delete/reinsert emits selection-change events and
        used to leave a valid group selected in the model but *not* in the UI.
        """
        desired = (
            "g:" + self.group if self.group
            else next((item for item in self.tree.selection()
                       if item.startswith("g:")), None)
        )
        self._tree_rebuilding = True
        try:
            needle = self.filter.get().strip().casefold()
            self.tree.delete(*self.tree.get_children())
            matches = 0
            for cat in self.data.get("kategorien", []):
                cat_id = self.tree.insert("", "end", text=tr(cat["name"]), open=bool(needle))
                for sub in cat.get("unterkategorien", []):
                    groups = [g for g in sub["gruppen"] if needle in g["gruppe"].casefold() or needle in sub["name"].casefold()]
                    if not groups:
                        continue
                    matches += len(groups)
                    sub_id = self.tree.insert(cat_id, "end", text=tr(sub["name"]), open=bool(needle))
                    for g in groups:
                        flags = (" ●" if g["benutzerablage"] else "") + (f" ↻{g['umlenkungen']}" if g["umlenkungen"] else "")
                        self.tree.insert(sub_id, "end", iid="g:" + g["gruppe"], text=f"{g['gruppe']}  ({g['frames']}){flags}")
                for ext in cat.get("erweiterungen", []):
                    if needle and needle not in str(ext["name"]).casefold():
                        continue
                    matches += 1
                    self.tree.insert(cat_id, "end", iid="e:" + str(ext["name"]),
                                     text=f"{ext['name']} [{ext['kategorie']}] -> {ext['bindung'] or 'ungebunden'}")
            if matches:
                self.tree_status.configure(
                    text=f"{matches} {'matches' if LANG.code == 'en' else 'Treffer'}"
                )
            else:
                self.tree_status.configure(
                    text=("No matching groups – clear search (✕)." if LANG.code == "en"
                          else "Keine Gruppen gefunden – Suche mit ✕ löschen.")
                )
            if desired and self.tree.exists(desired):
                # Category IDs are generated anew on each rebuild.
                ancestor = self.tree.parent(desired)
                while ancestor:
                    self.tree.item(ancestor, open=True)
                    ancestor = self.tree.parent(ancestor)
                self.tree.selection_set(desired)
                self.tree.see(desired)
        finally:
            self._tree_rebuilding = False

    def tree_selected(self, _event=None):
        if self._tree_rebuilding:
            return
        sel = self.tree.selection()
        if sel and sel[0].startswith("g:"):
            selected_group = sel[0][2:]
            # The emitted event can lag behind programmatic selection_set().
            # Never re-open the same category and reset its frame/page.
            if selected_group != self.group:
                self.open_group(selected_group)

    # ------------------------------------------------------------ group
    def open_group(self, group: str, focus: str | None = None):
        previous_group = self.group
        if group != previous_group:
            # Do not leave a frame from the former group as the action target.
            self.selected = None
        self.group = group
        if self.filter.get() and not self.tree.exists("g:" + group):
            self.clear_search()
        iid = "g:" + group
        if self.tree.exists(iid):
            ancestor = self.tree.parent(iid)
            while ancestor:
                self.tree.item(ancestor, open=True)
                ancestor = self.tree.parent(ancestor)
            if self.tree.selection() != (iid,):
                self.tree.selection_set(iid)
            self.tree.see(iid)
        from stronghold_europe_de.gm_atlas import frame_overrides_for

        overrides = {o.target_name: o.donor_name for o in frame_overrides_for(group)}
        changed = set(katalog.changed_frames(group))
        self.frames = []
        for row in katalog.group_rows(group):
            name = str(row["name"])
            self.frames.append({"name": name, "aktion": row.get("action"), "row": row,
                                "umlenkung": name in overrides, "spender": overrides.get(name),
                                "geaendert": name in changed})
        actions: dict[str, int] = {}
        for f in self.frames:
            actions[f["aktion"]] = actions.get(f["aktion"], 0) + 1
        en = LANG.code == "en"
        self.head.configure(text=f"{group}: {len(self.frames)} {'slots' if en else 'Plaetze'}  " +
                                 "  ".join(f"{k.split('_')[-1].lower()} {v}" for k, v in actions.items()) +
                                 (f"  | {len(overrides)} {'redirected' if en else 'umgelenkt'}" if overrides else "") +
                                 (f"  | {len(changed)} {'changed' if en else 'geaendert'}" if changed else ""))
        names = {f["name"] for f in self.frames}
        if self.selected not in names:
            self.selected = None
        self.page = 0
        if focus:
            for i, f in enumerate(self.frames):
                if f["name"] == focus:
                    self.page = i // self.PAGE
                    self.selected = focus
                    self.jump.set(str(katalog.frame_number(focus)[0]))
                    break
            else:
                self.app.log(f"Frame {focus} ist in {group} nicht vorhanden.", "warn")
        self.show_page()
        if self.selected is not None:
            self.show_detail(self.selected)
        else:
            self._set_edit_panel_visible(False)
            self.detail.delete("all")
            self.info.configure(text="Bitte einen Frame auswählen.")

    def side_directory(self, side: str) -> Path:
        return katalog.work_dir(self.group) if side == "arbeit" else katalog.side_dir(side, self.group)

    def image_for(self, side: str, name: str):
        from PIL import Image

        directory = self.side_directory(side)
        path = directory / f"{name}.png"
        if not path.is_file():
            return None
        try:
            return Image.open(path).convert("RGBA")
        except Exception:
            return None

    def show_page(self):
        from PIL import Image, ImageTk

        self.grid.delete("all")
        self.photos = []
        if not self.group:
            return
        pages = max(1, (len(self.frames) + self.PAGE - 1) // self.PAGE)
        self.page = max(0, min(self.page, pages - 1))
        self.page_label.configure(text=("Page" if LANG.code == "en" else "Seite") + f" {self.page + 1}/{pages}")
        side = self.side.get()
        if not self.side_directory(side).is_dir():
            self.grid.create_text(20, 20, anchor="nw", fill=MUTED, font=("Segoe UI", 11),
                                  text=f"Ansicht '{side}' fuer {self.group} liegt noch nicht vor -> 'Ansichten vorbereiten'.")
            return
        # At a narrow viewport 600px are NOT available; never hide columns
        # without offering a horizontal scrollbar.
        width = self.grid.winfo_width()
        if width < 2:
            width = 250
        cols = max(1, (width - 12) // (self.THUMB + 12))
        cell = self.THUMB + 12
        for n, frame in enumerate(self.frames[self.page * self.PAGE:(self.page + 1) * self.PAGE]):
            x, y = (n % cols) * cell + 6, (n // cols) * (cell + 16) + 6
            colour = "#e05050" if frame["geaendert"] else ("#b06ad9" if frame["umlenkung"] else
                                                          ACTION_COLOURS.get(frame["aktion"], "#666"))
            width_px = 3 if frame["name"] == self.selected else 2
            self.grid.create_rectangle(x, y, x + self.THUMB, y + self.THUMB, outline=colour, width=width_px,
                                       tags=("f:" + frame["name"],))
            image = self.image_for(side, frame["name"])
            if image is not None:
                image.thumbnail((self.THUMB - 6, self.THUMB - 6), Image.Resampling.NEAREST
                                if max(image.size) < self.THUMB else Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(image)
                self.photos.append(photo)
                self.grid.create_image(x + self.THUMB // 2, y + self.THUMB // 2, image=photo,
                                       tags=("f:" + frame["name"],))
            label = frame["name"].replace(self.group, "").strip(" -")
            self.grid.create_text(x + self.THUMB // 2, y + self.THUMB + 8, text=label, fill=FG,
                                  font=("Segoe UI", 8), tags=("f:" + frame["name"],))
        region = self.grid.bbox("all") or (0, 0, 1, 1)
        self.grid.configure(scrollregion=region)
        if self.selected:
            box = self.grid.bbox("f:" + self.selected)
            if box and box[3] > self.grid.winfo_height():
                self.grid.yview_moveto(
                    min(1.0, max(0.0, box[1] / max(region[3], 1)))
                )

    def _grid_wheel(self, event):
        if event.delta:
            self.grid.yview_scroll(-int(event.delta / 120) or
                                  (-1 if event.delta > 0 else 1), "units")
        return "break"

    def turn(self, delta):
        self.page += delta
        self.show_page()

    def jump_to(self):
        if not self.group or not self.frames:
            messagebox.showinfo("Zum Frame springen",
                                "Zuerst eine Spritegruppe auswählen.", parent=self)
            return
        try:
            wanted = int(self.jump.get().strip())
            if wanted < 0:
                raise ValueError("negative")
        except ValueError:
            messagebox.showinfo("Zum Frame springen",
                                "Bitte eine nicht-negative Frame-Nummer eingeben.",
                                parent=self)
            return
        for i, f in enumerate(self.frames):
            if katalog.frame_number(f["name"])[0] == wanted:
                self.page = i // self.PAGE
                self.selected = f["name"]
                self.show_page()
                self.show_detail(f["name"])
                return
        messagebox.showinfo(
            "Zum Frame springen",
            f"Frame {wanted} ist in der Gruppe {self.group} nicht vorhanden.",
            parent=self,
        )

    def grid_click(self, event):
        # Event coordinates are viewport-relative when the grid is scrolled.
        x = self.grid.canvasx(event.x)
        y = self.grid.canvasy(event.y)
        for item in self.grid.find_overlapping(x, y, x, y):
            for tag in self.grid.gettags(item):
                if tag.startswith("f:"):
                    self.selected = tag[2:]
                    self.show_page()
                    self.show_detail(self.selected)
                    return

    def show_detail(self, name: str):
        from PIL import Image, ImageTk

        self.detail.delete("all")
        self.detail_photos = []
        frame = next((f for f in self.frames if f["name"] == name), None)
        if frame is None:
            return
        self._set_edit_panel_visible(True)
        x = 10
        for side, title in SIDES:
            image = self.image_for(side, name)
            self.detail.create_text(x, 6, anchor="nw", text=tr(title), fill=ACCENT, font=("Segoe UI", 9, "bold"))
            if image is None:
                self.detail.create_text(x, 26, anchor="nw", text="-", fill=MUTED)
                x += 120
                continue
            scale = 2 if max(image.size) <= 110 else 1
            if max(image.size) > 230:
                image.thumbnail((230, 230), Image.Resampling.LANCZOS)
                scale = 1
            shown = image.resize((image.width * scale, image.height * scale), Image.Resampling.NEAREST)
            checker = Image.new("RGBA", shown.size, (60, 62, 66, 255))
            checker.alpha_composite(shown)
            photo = ImageTk.PhotoImage(checker)
            self.detail_photos.append(photo)
            self.detail.create_image(x, 26, anchor="nw", image=photo)
            self.detail.create_text(x, 30 + shown.height, anchor="nw", text=f"{image.width}x{image.height}",
                                    fill=MUTED, font=("Segoe UI", 8))
            x += max(shown.width, 110) + 14
        row = frame["row"]
        target, source = row.get("target") or {}, row.get("source") or {}
        en = LANG.code == "en"
        text = (f"{name}\n{'Action' if en else 'Aktion'}: {frame['aktion']}\nCrusader: {target.get('width')}x{target.get('height')} "
                f"Pivot ({target.get('pivot_x', 0):.3f}, {target.get('pivot_y', 0):.3f})")
        if source:
            text += f"\nSH1: {source.get('width')}x{source.get('height')} Pivot ({source.get('pivot_x', 0):.3f}, {source.get('pivot_y', 0):.3f})"
        if frame["umlenkung"]:
            text += (f"\nRedirected to: {frame['spender'] or 'Crusader kept'}" if en else
                     f"\nUmgelenkt auf: {frame['spender'] or 'Crusader behalten'}")
        if frame["geaendert"]:
            text += "\nChanged in the working copy" if en else "\nIn der Arbeitskopie geaendert"
        self.info.configure(text=text)
        # Up to four side-by-side images have to remain reachable in the
        # narrow catalogue pane, not disappear behind the action controls.
        self.detail.configure(
            scrollregion=self.detail.bbox("all") or (0, 0, 1, 1)
        )
        self.detail.xview_moveto(0)

    # ------------------------------------------------------------ actions
    def _need(self) -> bool:
        if not self.group or not self.selected or not any(
            frame["name"] == self.selected for frame in self.frames
        ):
            messagebox.showinfo("Katalog", "Bitte zuerst eine Gruppe und einen Frame waehlen.", parent=self)
            return False
        return True

    def fit_args(self):
        args = ["--modus", self.mode.get(), "--dx", self.dx.get() or "0", "--dy", self.dy.get() or "0"]
        if self.mirror.get():
            args.append("--spiegeln")
        return args

    def prepare(self):
        if self.group:
            self.app.run([tool("asset_katalog.py"), "vorbereiten", self.group, "--seiten",
                          "crusader,stronghold1,geliefert", "--arbeit"], f"Ansichten {self.group}")

    def replace_image(self):
        if not self._need():
            return
        path = filedialog.askopenfilename(parent=self, filetypes=[("PNG", "*.png"), ("Bilder", "*.png;*.webp;*.jpg")])
        if path:
            self.app.run([tool("asset_katalog.py"), "ersetzen", self.group, self.selected, "--bild", path,
                          *self.fit_args()], f"ersetzen {self.selected}")

    def take_over(self):
        if not self._need():
            return
        source = simpledialog.askstring(
            "Uebernehmen aus", "Quelle: stronghold1 | geliefert | crusader | stronghold1:<frame> | "
            "frame:<frame> | gruppe:<gruppe>:<frame>", initialvalue="stronghold1", parent=self)
        if source:
            self.app.run([tool("asset_katalog.py"), "uebernehmen", self.group, self.selected, "--quelle", source,
                          *self.fit_args()], f"uebernehmen {self.selected}")

    def reset_frame(self):
        if self._need():
            self.app.run([tool("asset_katalog.py"), "zuruecksetzen", self.group, self.selected], "zuruecksetzen")

    def copy_block(self):
        if not self.group:
            return
        start = katalog.frame_number(self.selected)[0] if self.selected else 0
        text = simpledialog.askstring(
            "Block kopieren", "von nach anzahl [schritt] - z.B. fuer eine fehlende Blickrichtung aus der Nachbar-"
            "richtung: '0 8 16 16' plus 'spiegeln'", initialvalue=f"{start} {start} 1 1", parent=self)
        if not text:
            return
        parts = text.split()
        try:
            von, nach, anzahl = int(parts[0]), int(parts[1]), int(parts[2])
            schritt = int(parts[3]) if len(parts) > 3 else 1
        except (ValueError, IndexError):
            messagebox.showinfo("Block kopieren", "Bitte vier Zahlen angeben: von nach anzahl schritt", parent=self)
            return
        if von < 0 or nach < 0 or anzahl <= 0 or schritt <= 0 or anzahl > 10000:
            messagebox.showwarning(
                "Block kopieren",
                "Start-/Zielindex müssen ≥ 0 sein, Anzahl/Schritt positiv "
                "(Anzahl höchstens 10.000).", parent=self
            )
            return
        args = [tool("asset_katalog.py"), "block", self.group, "--von", str(von), "--nach", str(nach), "--anzahl",
                str(anzahl), "--schritt", str(schritt), "--quelle", "arbeit", "--modus", self.mode.get()]
        if self.mirror.get():
            args.append("--spiegeln")
        self.app.run(args, "Block kopieren")

    def redirect(self):
        if not self.group:
            return
        text = simpledialog.askstring(
            "Objekt umlenken", "Zielbereich und Spenderbereich gleicher Laenge, z.B. '1192-1207 10-25'.\n"
            "Immer das GANZE Objekt (4/9/16/25 ... Teile)! Nur Ziel ohne Spender = Crusader behalten.",
            parent=self)
        if not text:
            return
        parts = text.split()
        if not 1 <= len(parts) <= 2 or any(not part.strip() for part in parts):
            messagebox.showwarning(
                "Objekt umlenken",
                "Zielbereich und optional genau einen Spenderbereich "
                "angeben, z. B. 1192-1207 10-25.", parent=self
            )
            return
        args = [tool("asset_katalog.py"), "umlenken", self.group, "--ziel", parts[0]]
        if len(parts) > 1:
            args += ["--spender", parts[1]]
        self.app.run(args, "umlenken")

    def to_editor(self):
        if not self._need():
            return
        idx = katalog.frame_number(self.selected)[0]
        args = [tool("editor_bruecke.py"), "export", self.group, "--seite", "arbeit"]
        args += ["--von", str(max(0, idx - 15)), "--bis", str(idx + 15)]
        run_then_success(
            self.app, args, "Export fuer HTML-Editor",
            lambda: self.app.run(
                [tool("editor_bruecke.py"), "oeffnen"], "Editor oeffnen"
            ),
            next_step="HTML-Editor öffnen",
        )

    def to_sandbox(self):
        """Send a selected catalogue frame into the embedded editor."""
        if not self.group or not self.selected or (
            getattr(self, "frames", None) is not None
            and not any(f["name"] == self.selected for f in self.frames)
        ):
            if isinstance(self, tk.Misc):
                messagebox.showinfo(
                    "Katalog",
                    "Bitte zuerst einen gültigen Frame der aktuellen Gruppe auswählen.",
                    parent=self,
                )
            return
        index = katalog.frame_number(self.selected)[0]
        self.app.show_in_sandbox(self.group, index)

    def apply(self):
        if not self.group:
            messagebox.showinfo(
                "Profil aktualisieren",
                "Bitte zuerst eine Gruppe aus dem Katalog auswählen.",
                parent=self,
            )
            return
        changed = katalog.changed_frames(self.group)
        if not changed:
            messagebox.showinfo(
                "Profil aktualisieren",
                "Für diese Gruppe gibt es noch keine geänderten Frames "
                "in der Arbeitskopie.",
                parent=self,
            )
            return
        profile = getattr(self.app, "bc7_profile", None)
        base = f"profiles/{profile.get()}.json" if profile else katalog.DEFAULT_BASE_PROFILE
        if not (ROOT / base).is_file():
            base = katalog.DEFAULT_BASE_PROFILE
        if not messagebox.askyesno(
            "Arbeitskopie ins Profil übernehmen",
            f"{len(changed)} bearbeitete Frames der Gruppe {self.group} "
            f"für das Profil {base} anwenden?\n\n"
            "Der Profilinhalt wird geändert; es wird kein Spiel installiert.",
            icon="warning", default="no", parent=self,
        ):
            return
        self.app.run(
            [tool("asset_katalog.py"), "anwenden", self.group, "--basis", base],
            f"anwenden {self.group}",
        )

    def new_category(self):
        name = simpledialog.askstring("Kategorie", "Name der Kategorie:", parent=self)
        if not name:
            return
        sub = simpledialog.askstring("Kategorie", "Unterkategorie (leer = keine):", parent=self) or ""
        args = [tool("asset_katalog.py"), "kategorie", "neu", "--name", name]
        if sub:
            args += ["--unter", sub]
        self.app.run(args, "Kategorie anlegen")

    def assign_group(self):
        group = self.group or simpledialog.askstring("Zuordnen", "Gruppe:", parent=self)
        if not group:
            return
        name = simpledialog.askstring("Zuordnen", f"{group} in Kategorie:", parent=self)
        if not name:
            return
        sub = simpledialog.askstring("Zuordnen", "Unterkategorie (leer = direkt):", parent=self) or ""
        args = [tool("asset_katalog.py"), "kategorie", "zuordnen", "--name", name, "--gruppe", group]
        if sub:
            args += ["--unter", sub]
        self.app.run(args, "Gruppe zuordnen")

    def new_extension(self):
        folder = filedialog.askdirectory(parent=self, title="Ordner mit den neuen PNG-Bildern (und _m-Masken)")
        if not folder:
            return
        name = simpledialog.askstring("Erweiterung", "Name des neuen Assets:", parent=self)
        if not name:
            return
        category = simpledialog.askstring("Erweiterung", "Kategorie:", initialvalue="Eigene Assets", parent=self)
        self.app.run([tool("asset_katalog.py"), "erweiterung", "neu", "--name", name, "--kategorie",
                      category or "Eigene Assets", "--bilder", folder], "Erweiterung anlegen")

    def bind_extension(self):
        name = simpledialog.askstring("Erweiterung binden", "Name der Erweiterung:", parent=self)
        if not name:
            return
        group = simpledialog.askstring("Erweiterung binden", "Zielgruppe:", initialvalue=self.group or "", parent=self)
        start = simpledialog.askinteger("Erweiterung binden", "ab Index:", parent=self, initialvalue=0)
        if group and start is not None:
            self.app.run([tool("asset_katalog.py"), "erweiterung", "binden", "--name", name, "--gruppe", group,
                          "--ab", str(start)], "Erweiterung binden")

    def _after_tool(self, _code):
        if self.group:
            try:
                self.open_group(self.group, self.selected)
            except Exception:
                pass
        if self.winfo_ismapped():
            self.load_tree()


# ====================================================================== Diagnose

class DiagnoseTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.photo = None
        ttk.Label(self, text="Diagnose & Reparatur", style="Title.TLabel").pack(anchor="w", padx=8, pady=(12, 2))
        ttk.Label(self, text=(
            "Jede Pruefung stammt aus einem echten Fall: Zinnen (Kantenanker), Huetten (teilweise umgelenkte "
            "Objekte), Kornspeicher/Waffenkammer (falscher Spender), Zugbruecke (Frame-Drift zwischen Spielstaenden). "
            "Doppelklick auf einen Befund oeffnet ihn im Katalog."), style="Muted.TLabel", wraplength=1150,
            justify="left").pack(anchor="w", padx=8)
        checks = (
            ("Alles prüfen", "alles"), ("Anker", "anker"), ("Objekte", "objekte"),
            ("Umlenkungen mit Bildern", "umlenkungen"), ("Drift", "drift"),
            ("Leinwand", "leinwand"), ("Bundles", "bundles"),
        )
        actions = [
            (text, lambda c=check: self.run(c)) for text, check in checks
        ]
        self.check_actions = CompactActionBar(
            self, primary=actions[:3], more=actions[3:],
            overflow_label="Weitere Prüfarten ▾",
        )
        self.check_actions.pack(fill="x", padx=8, pady=(5, 3))
        diagnose_actions = ttk.Frame(self)
        diagnose_actions.pack(fill="x", padx=8, pady=(0, 3))
        ttk.Button(
            diagnose_actions, text="Als geprueft markieren", command=self.mark_ok
        ).pack(side="left", padx=3)
        ttk.Button(
            diagnose_actions, text="QA-Altbestand vergleichen …",
            command=self.inventory_qa
        ).pack(side="left", padx=3)
        adopt_menu = ttk.Menubutton(
            diagnose_actions, text="Profiländerungen ▾"
        )
        adopt_options = tk.Menu(adopt_menu, tearoff=False)
        adopt_options.add_command(
            label="Nachweise übernehmen (Profil ändern) …",
            command=self.adopt,
        )
        adopt_menu.configure(menu=adopt_options)
        adopt_menu.pack(side="left", padx=4)
        release_bar = ttk.Frame(self)
        release_bar.pack(fill="x", padx=8, pady=(0, 5))
        ttk.Label(
            release_bar, text="BC7-Releaseprofil:", style="Muted.TLabel"
        ).pack(side="left")
        profile_names = sorted(p.stem for p in (ROOT / "profiles").glob("*.json"))
        initial_profile = (
            "sprite-suite-world-bc7-v2"
            if "sprite-suite-world-bc7-v2" in profile_names
            else (profile_names[0] if profile_names else "")
        )
        self.release_profile = tk.StringVar(value=initial_profile)
        self.release_options = ttk.Combobox(
            release_bar, textvariable=self.release_profile,
            values=profile_names, state="readonly", width=24
        )
        self.release_options.pack(side="left", padx=5)
        self.release_approval = tk.StringVar(value="")
        self.release_approval_label = tk.StringVar(value=LANG.tr("Pivot-Freigabe: keine"))

        self.preflight_button = ttk.Button(
            release_bar, text="Gesamten Build prüfen (SHA-256)",
            command=self.inspect_release
        )
        self.preflight_button.pack(side="right", padx=4)
        self.pivot_stage_button = ttk.Button(
            release_bar, text="Pivot-BC7-Stufenplan",
            command=self.prepare_pivot_stage
        )
        self.pivot_stage_button.pack(side="right", padx=4)

        self._release_pending = None
        self._stage_pending = None
        self._rehearsal_pending = None
        self._native_pending = None
        lab_bar=ttk.Frame(self)
        lab_bar.pack(fill="x",padx=8,pady=(0,5))
        self.pivot_menu_button=ttk.Menubutton(
            lab_bar, text="Pivot-Protokoll ▾"
        )
        self.pivot_menu=tk.Menu(self.pivot_menu_button,tearoff=False)
        self.pivot_menu.add_command(
            label="Pivot-Protokoll wählen …",
            command=self.choose_release_approval,
        )
        self.pivot_menu.add_command(
            label="Ohne Pivot-Protokoll",
            command=lambda:(self.release_approval.set(""),
                            self._refresh_release_approval_label()),
        )
        self.pivot_menu_button.configure(menu=self.pivot_menu)
        self.pivot_menu_button.pack(side="left",padx=(0,5))
        self.rehearsal_button=ttk.Button(
            lab_bar,text="Synthetische BC7-Testprobe",
            command=self.run_synthetic_bc7_rehearsal
        )
        self.rehearsal_button.pack(side="left",padx=(0,5))
        self.native_button=ttk.Button(
            lab_bar,text="Zinnen-Geometriebeweis",
            command=self.inspect_native_geometry
        )
        self.native_button.pack(side="left",padx=(0,5))
        ttk.Label(
            lab_bar, textvariable=self.release_approval_label,
            style="Muted.TLabel", wraplength=235
        ).pack(side="left",fill="x",expand=True,padx=(7,0))
        self.mod = tk.StringVar(value="")
        row = ttk.Frame(self)
        row.pack(fill="x", padx=8)
        ttk.Label(
            row, text="Modordner (leer = Zielspiel/neuester Bau):",
            style="Muted.TLabel",
        ).pack(side="left")
        ttk.Button(
            row, text="…", width=3,
            command=lambda: self.mod.set(
                filedialog.askdirectory(parent=self) or self.mod.get()
            ),
        ).pack(side="right")
        ttk.Entry(row, textvariable=self.mod, width=20).pack(
            side="left", padx=4, fill="x", expand=True
        )
        self._diagnostic_status = ("initial", None)
        self.findings_status = tk.StringVar()
        self.refresh_status()
        ttk.Label(
            self, textvariable=self.findings_status,
            style="Muted.TLabel", wraplength=900,
        ).pack(fill="x", padx=8, pady=(1, 3))
        split = ttk.PanedWindow(self, orient="horizontal")
        split.pack(fill="both", expand=True, padx=8, pady=6)
        self.diagnose_table_area = ttk.Frame(split)
        self.table_scroll_x = ttk.Scrollbar(
            self.diagnose_table_area, orient="horizontal"
        )
        self.table = ttk.Treeview(
            self.diagnose_table_area,
            columns=("schwere", "pruefung", "gruppe", "text"),
            show="headings", height=18,
            xscrollcommand=self.table_scroll_x.set,
        )
        for col, width in (
            ("schwere", 75), ("pruefung", 115),
            ("gruppe", 130), ("text", 500),
        ):
            self.table.heading(col, text=col.capitalize())
            self.table.column(col, width=width, minwidth=60, stretch=False)
        self.table_scroll_x.configure(command=self.table.xview)
        self.table_scroll_x.pack(side="bottom", fill="x")
        self.table.pack(fill="both", expand=True)
        split.add(self.diagnose_table_area, weight=3)
        side = ttk.Frame(split)
        split.add(side, weight=2)
        self.detail = ttk.Label(
            side, text="", style="Muted.TLabel", wraplength=320,
            justify="left",
        )
        self.detail.pack(anchor="w", fill="x")
        side.bind(
            "<Configure>",
            lambda event: self.detail.configure(
                wraplength=max(150, event.width - 20)
            ), add="+",
        )
        self.canvas = tk.Canvas(side, bg="#25272b", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.table.bind("<<TreeviewSelect>>", self.select)
        self.table.bind("<Double-1>", self.open_in_catalog)
        self.findings: list[dict] = []
        self.app.done_hooks.append(lambda _c: self.load())
        self.after(500, self.load)

    def _refresh_release_approval_label(self):
        choice = self.release_approval.get()
        if choice:
            self.release_approval_label.set(
                LANG.tr("Pivot-Freigabe: ") + Path(choice).name[:44]
            )
        else:
            self.release_approval_label.set(LANG.tr("Pivot-Freigabe: keine"))

    def inspect_native_geometry(self):
        """Reconstruct published native geometry hashes; never patch them."""
        if any(pending is not None for pending in (
            self._native_pending, self._rehearsal_pending,
            self._release_pending, self._stage_pending
        )):
            return
        selected_profile=self.release_profile.get()
        replies=queue.Queue(maxsize=1)
        self._native_pending=replies
        for action in (self.native_button, self.rehearsal_button,
                       self.pivot_stage_button, self.preflight_button):
            action.configure(state="disabled")
        self.app.log(
            f"Native BC7-Geometrieprüfung {selected_profile}/anim_castle: "
            "vollständiges Mapping, Cache-Bundle und alle Geometriebeweise "
            "werden nur lesend gegengeprüft.", "muted"
        )

        def worker():
            from stronghold_europe_de.pivot_native_provenance import (
                audit_native_geometry, save_native_geometry_audit
            )
            try:
                report=audit_native_geometry(
                    ROOT, selected_profile, "anim_castle"
                )
                destination=save_native_geometry_audit(report, ROOT)
                replies.put(("ok", report, destination))
            except Exception as exc:
                replies.put(("error", str(exc)))

        threading.Thread(
            target=worker, name="sprite-suite-native-geometry-proof",
            daemon=True
        ).start()
        self.after(100, self._poll_native_geometry)

    def _poll_native_geometry(self):
        if self._native_pending is None:
            return
        try:
            received=self._native_pending.get_nowait()
        except queue.Empty:
            self.after(100, self._poll_native_geometry)
            return
        self._native_pending=None
        for action in (self.native_button, self.rehearsal_button,
                       self.pivot_stage_button, self.preflight_button):
            action.configure(state="normal")
        if received[0] != "ok":
            messagebox.showwarning(
                "Nativer Zinnenbeweis abgelehnt",
                received[1]+"\n\nKein Sprite-/Atlas-/Spielbestand geändert.",
                parent=self
            )
            return
        _, report, destination=received
        result=report["group_proof"]
        native=result["native_proof"]
        reviewed=result["review_partition"]
        rows=[
            {
                "schwere":"info", "pruefung":"Nativ-Proof",
                "gruppe":"anim_castle",
                "text":(
                    f"Veröffentlicht: {result['total_frames']} Frames, "
                    f"{result['native_source_frames']} originale SH1DE-Frames, "
                    f"{result['target_keep_frames']} unveränderte Crusader-Frames. "
                    "Alle Ausgabe-Pivots und die native Geometrie stimmen "
                    "mit dem eingefrorenen Profil überein."
                ),
            },
            {
                "schwere":"info", "pruefung":"Nativ-Proof",
                "gruppe":"Geometrie",
                "text":(
                    f"Rekonstruierter Geometrie-SHA: "
                    f"{native['geometry_proof_sha256']}. "
                    f"Runtime-Anker-Maximalfehler: "
                    f"{native['runtime_anchor_max_error_px']:.8g} px."
                ),
            },
            {
                "schwere":"info", "pruefung":"Nativ-Proof",
                "gruppe":"Herkunft",
                "text":(
                    f"SH1DE-/Crusader-Partition-SHA: "
                    f"{reviewed['provenance_sha256']}; "
                    f"RGBA-Proof: {native['source_rgba_sha256']}."
                ),
            },
            {
                "schwere":"warnung", "pruefung":"Nativ-Proof",
                "gruppe":"Nachweisgrenze",
                "text":(
                    "SHA-256 der originalen Mappingdatei und des "
                    "ausgelieferten BC7-Atlas bestätigt. "
                    "RGBA-Quellbytes stammen aus dem verifizierten "
                    "Cache; originale Game-Assets wurden nicht neu dekodiert. "
                    "Keine Build-/Release-/Ingame-Freigabe."
                ),
            },
        ]
        from pivot_native_proof_rows import native_frame_rows
        try:
            rows.extend(native_frame_rows(report))
        except ValueError as exc:
            # Never turn an incomplete record list into a seemingly verified
            # all-frame report in the user-facing diagnostics.
            rows.append({
                "schwere":"fehler","pruefung":"Nativ-Proof",
                "gruppe":"Frame-Liste",
                "text":f"Einzelbildnachweis unvollständig: {exc}",
            })
        self.findings=rows
        self.table.delete(*self.table.get_children())
        for position,row in enumerate(rows):
            self.table.insert(
                "", "end", iid=str(position),
                values=(row["schwere"],row["pruefung"],row["gruppe"],row["text"])
            )
        self._update_findings_status("Nativer Geometrie-Proof (nur lesend)")
        self.detail.configure(
            text=f"Nur Herkunfts- und Geometrieprüfung: {destination}. "
            "Kein erneuter Unity-Encoderlauf, keine Sprite-/Spieländerung."
        )
        self.canvas.delete("all")
        self.app.log(
            f"Nativer BC7-Geometriebeweis verifiziert: "
            f"{result['native_source_frames']} SH1DE + "
            f"{result['target_keep_frames']} Crusader-Frames; "
            f"Bericht {destination}. Keine Installation.", "muted"
        )

    def run_synthetic_bc7_rehearsal(self):
        """Prepare two tiny V2 Unity inputs, with no encoder or game writes."""
        if (self._rehearsal_pending is not None or self._stage_pending is not None
            or self._release_pending is not None or self._native_pending is not None):
            return
        results=queue.Queue(maxsize=1)
        self._rehearsal_pending=results
        self.rehearsal_button.configure(state="disabled")
        self.native_button.configure(state="disabled")
        self.pivot_stage_button.configure(state="disabled")
        self.preflight_button.configure(state="disabled")
        self.app.log(
            "Synthetische Pivot/BC7-V2-Probe: gleiche Testpixel, "
            "verschiedene Pivots, unveränderte Kontrollgruppe. "
            "Nur vorbereitete Unity-Eingaben unter work/, kein Encoder.",
            "muted",
        )

        def worker():
            from stronghold_europe_de.pivot_bc7_rehearsal import (
                prepare_synthetic_pivot_rehearsal
            )
            try:
                location=prepare_synthetic_pivot_rehearsal(ROOT)
                snapshot=json.loads(location.read_text(encoding="utf-8"))
                if (snapshot.get("schema") !=
                    "stronghold-europe.pivot-bc7-synthetic-rehearsal.v1"
                    or snapshot.get("release_allowed") is not False
                    or snapshot.get("unity_executed") is not False):
                    raise ValueError("Synthetik-Testbericht hat keine gültige Sicherheitsbindung")
                results.put(("ok",snapshot,location))
            except Exception as exc:
                results.put(("error",str(exc)))
        threading.Thread(
            target=worker,name="sprite-suite-synthetic-pivot-v2",
            daemon=True,
        ).start()
        self.after(100,self._poll_synthetic_bc7_rehearsal)

    def _poll_synthetic_bc7_rehearsal(self):
        if self._rehearsal_pending is None:
            return
        try:
            message=self._rehearsal_pending.get_nowait()
        except queue.Empty:
            self.after(100,self._poll_synthetic_bc7_rehearsal)
            return
        self._rehearsal_pending=None
        self.rehearsal_button.configure(state="normal")
        self.native_button.configure(state="normal")
        self.pivot_stage_button.configure(state="normal")
        self.preflight_button.configure(state="normal")
        if message[0]!="ok":
            messagebox.showwarning(
                "Synthetische BC7-Probe abgebrochen",message[1],parent=self
            )
            return
        _,record,output=message
        old=record["tested"]["old"]
        candidate=record["tested"]["proposed"]
        cache_changed=(
            old["groups"]["anim_castle"]["cache_key_projection"] !=
            candidate["groups"]["anim_castle"]["cache_key_projection"]
        )
        cache_control=(
            old["groups"]["anim_drawbridge"]["cache_key_projection"] ==
            candidate["groups"]["anim_drawbridge"]["cache_key_projection"]
        )
        passed=(
            cache_changed and cache_control
            and record["tested"]["pixel_pages_identical"] is True
            and record["asset_bundle_produced"] is False
        )
        rows=[
            {
                "schwere":"info" if passed else "fehler",
                "pruefung":"BC7-Probe",
                "gruppe":"Metadaten",
                "text":(
                    f"Synthetischer Pivot alt {old['groups']['anim_castle']['pivot']} "
                    f"zu neu {candidate['groups']['anim_castle']['pivot']}; "
                    f"geänderter V2-Schlüssel={cache_changed}; "
                    f"Kontrollgruppe gleich={cache_control}; Pixel unverändert. "
                    "Nicht freigabefähig."
                ),
            },
            {
                "schwere":"warnung",
                "pruefung":"BC7-Probe",
                "gruppe":"Unity-Editor",
                "text":(
                    f"Gepinnte Unity-Version {record['pinned_unity_editor']['required_version']} "
                    f"({record['pinned_unity_editor']['discovery_status']}). "
                    "Es wurde kein Unity-Lauf/BC7-Encoder-Neubau ausgeführt."
                ),
            },
        ]
        self.findings=rows
        self.table.delete(*self.table.get_children())
        for i,item in enumerate(rows):
            self.table.insert(
                "","end",iid=str(i),
                values=(item["schwere"],item["pruefung"],
                        item["gruppe"],item["text"])
            )
        self._update_findings_status("Synthetische BC7-Probe")
        self.detail.configure(
            text=f"Nur synthetischer V2-Projekt-Vorbereitungsnachweis: {output}. "
            "Keine Unity-Kompilierung, kein Produktions- oder Spieltest."
        )
        self.canvas.delete("all")
        self.app.log(
            f"Synthetische BC7-Probe {'bestanden' if passed else 'fehlerhaft'}: "
            f"{output}; kein Bundle oder Spiel geändert.",
            "muted" if passed else "warn",
        )

    def choose_release_approval(self):
        """Choose an explicit, source-pinned Pivot approval report."""
        folder = ROOT / "work" / "reports" / "pivot-approval"
        selected = filedialog.askopenfilename(
            parent=self, title="Pivot-Freigabeprotokoll für den Release-Abgleich",
            initialdir=str(folder if folder.is_dir() else ROOT / "work"),
            filetypes=[("JSON-Freigabeprotokoll", "*.json")],
        )
        if selected:
            self.release_approval.set(selected)
            self._refresh_release_approval_label()

    def prepare_pivot_stage(self):
        """Pin approvals to an existing BC7 build; never modify its data."""
        if (self._stage_pending is not None or self._release_pending is not None
            or self._rehearsal_pending is not None or self._native_pending is not None):
            return
        approval = self.release_approval.get().strip()
        if not approval:
            messagebox.showinfo(
                "Pivot-BC7-Stufenplan",
                "Zuerst ein ausdrückliches Pivot-Freigabeprotokoll wählen.",
                parent=self
            )
            return
        chosen = filedialog.askopenfilename(
            parent=self, title="Original-Zinnenlineal-Messdatei zur Gegenprüfung",
            initialdir=str(ROOT / "work"),
            filetypes=[("Zinnenlineal-Messung", "*.json")],
        )
        if not chosen:
            return
        target_profile = self.release_profile.get()
        work_queue = queue.Queue(maxsize=1)
        self._stage_pending = work_queue
        self.preflight_button.configure(state="disabled")
        self.pivot_stage_button.configure(state="disabled")
        self.rehearsal_button.configure(state="disabled")
        self.native_button.configure(state="disabled")
        self.app.log(
            f"BC7-Pivot-Stufenentwurf für {target_profile} gestartet: "
            "Originalmessung, Index, PNG und gesamtes Produktionsmanifest "
            "werden ohne Assetänderung gegen die Freigabe geprüft.", "muted"
        )

        def worker():
            from stronghold_europe_de.pivot_build_stage import (
                prepare_pivot_build_stage, save_pivot_build_stage
            )
            try:
                report = prepare_pivot_build_stage(
                    ROOT, target_profile, approval, chosen
                )
                destination = save_pivot_build_stage(report, ROOT)
                work_queue.put(("ok", report, destination))
            except Exception as exc:
                work_queue.put(("error", str(exc)))

        threading.Thread(
            target=worker, daemon=True, name="sprite-suite-pivot-bc7-stage"
        ).start()
        self.after(100, self._poll_pivot_stage)

    def _poll_pivot_stage(self):
        if self._stage_pending is None:
            return
        try:
            result = self._stage_pending.get_nowait()
        except queue.Empty:
            self.after(100, self._poll_pivot_stage)
            return
        self._stage_pending = None
        self.preflight_button.configure(state="normal")
        self.pivot_stage_button.configure(state="normal")
        self.rehearsal_button.configure(state="normal")
        self.native_button.configure(state="normal")
        if result[0] != "ok":
            messagebox.showwarning(
                "Pivot-BC7-Stufenplan abgelehnt",
                result[1] + "\n\nKeine Build- oder Spieldatei verändert.",
                parent=self
            )
            return
        _, stage, destination = result
        findings = [{
            "schwere": "info", "pruefung": "Pivot-Stufe",
            "gruppe": "Stufenvertrag",
            "text": (
                f"Status {stage['state']}, {stage['change_count']} Vorschläge. "
                "Der Entwurf ist NICHT anwendbar; keine Metadaten, "
                "BC7-Bundles, Profile oder Spiele wurden verändert."
            ),
        }]
        for change in stage["changes"]:
            source_status = change.get("published_bc7_evidence", {})
            cache_status = (
                "Publizierter Cache/Atlas SHA-geprüft"
                if source_status.get("cache_verified")
                else "BC7-Cachezuordnung noch nicht nachgewiesen"
            )
            findings.append({
                "schwere": "warnung", "pruefung": "Pivot-Stufe",
                "gruppe": change["group"],
                "text": (
                    f"{change['name']}: {change['old_pivot']} → "
                    f"{change['proposed_pivot']}. {cache_status}. "
                    "Separater BC7-Neubau, neue Metadaten-/Geometrieprüfsummen "
                    "und erneute Release-/Ingame-Freigabe erforderlich."
                ),
            })
        for item in stage.get("already_in_published_bc7", []):
            findings.append({
                "schwere": "info", "pruefung": "Pivot-Stufe",
                "gruppe": item["group"],
                "text": (
                    f"{item['name']}: bereits im veröffentlichten BC7-Atlas "
                    f"korrekt ({item['bc7_pivot']}); kein Neubau vorgesehen."
                ),
            })
        for impact in stage.get("verified_cache_group_impacts", []):
            findings.append({
                "schwere": "warnung", "pruefung": "Pivot-Stufe",
                "gruppe": impact["group"],
                "text": (
                    "Theoretischer V2-Metadaten-/Cache-Key-Wechsel: "
                    f"{impact['original_cache_key'][:12]} → "
                    f"{impact['projected_cache_key'][:12]}. "
                    "Keine echte Cacheveröffentlichung oder Unity-Neukompilierung."
                ),
            })
        self.findings = findings
        self.table.delete(*self.table.get_children())
        for idx, item in enumerate(findings):
            self.table.insert(
                "", "end", iid=str(idx),
                values=(item["schwere"], item["pruefung"],
                        item["gruppe"], item["text"])
            )
        self._update_findings_status("Pivot-BC7-Stufenentwurf")
        self.detail.configure(
            text="BC7-Pivot-Änderungsentwurf, keine Atlas- oder Spieländerung. "
            f"Bericht: {destination}"
        )
        self.canvas.delete("all")
        self.app.log(
            f"Pivot/BC7-Stufenentwurf geprüft: {stage['change_count']} "
            f"Korrekturen, Bericht {destination}. "
            "Nicht anwendbar, keine automatische Änderung.", "muted"
        )

    def inspect_release(self):
        """Verify the complete local BC7 output in a worker, never on Tk thread."""
        if (self._release_pending is not None or self._stage_pending is not None
            or self._rehearsal_pending is not None or self._native_pending is not None):
            return
        profile_id = self.release_profile.get()
        approval = self.release_approval.get().strip() or None
        result_queue = queue.Queue(maxsize=1)
        self._release_pending = result_queue
        self.preflight_button.configure(state="disabled")
        self.pivot_stage_button.configure(state="disabled")
        self.rehearsal_button.configure(state="disabled")
        self.native_button.configure(state="disabled")
        self.app.log(
            f"Projektweiter SHA-256-Abgleich für {profile_id} gestartet "
            "(nur lesen; keine Spielinstallation).", "muted"
        )

        def work():
            from stronghold_europe_de.release_preflight import (
                audit_release, save_preflight
            )
            try:
                report = audit_release(
                    ROOT, profile_id, approval_file=approval
                )
                destination = save_preflight(report, ROOT)
                result_queue.put(("ok", report, destination))
            except Exception as exc:
                result_queue.put(("error", str(exc)))

        threading.Thread(
            target=work, name="sprite-suite-release-preflight",
            daemon=True
        ).start()
        self.after(100, self._poll_release)

    def _poll_release(self):
        if self._release_pending is None:
            return
        try:
            message = self._release_pending.get_nowait()
        except queue.Empty:
            self.after(100, self._poll_release)
            return
        self._release_pending = None
        self.preflight_button.configure(state="normal")
        self.pivot_stage_button.configure(state="normal")
        self.rehearsal_button.configure(state="normal")
        self.native_button.configure(state="normal")
        if message[0] != "ok":
            messagebox.showwarning(
                "Release-Prüfung fehlgeschlagen", message[1], parent=self
            )
            return
        _, report, destination = message
        self.show_release_report(report)
        summary, stats = report["summary"], report["stats"]
        self.app.log(
            f"Projekt-/Releaseabgleich {report['profile_id']}: "
            f"{stats['verified_outputs']}/{stats['expected_outputs']} Dateien "
            f"SHA-256-verifiziert, {summary['errors']} Fehler, "
            f"{summary['warnings']} Warnungen. "
            f"Bericht: {destination}. Nur Offline-Prüfung, keine Installation.",
            "muted" if not summary["errors"] else "warn",
        )

    def show_release_report(self, report):
        """Show release findings beside existing graphic and legacy QA diagnoses."""
        self.findings = list(report["findings"])
        self.table.delete(*self.table.get_children())
        severity = {"fehler": 0, "warnung": 1, "info": 2}
        for index, item in sorted(
            enumerate(self.findings),
            key=lambda pair: severity.get(pair[1]["schwere"], 3)
        ):
            self.table.insert(
                "", "end", iid=str(index),
                values=(item["schwere"], item["pruefung"],
                        item["gruppe"], item["text"])
            )
        self._update_findings_status("SHA-256-Releasebericht (nur Offline)")
        self.detail.configure(
            text=f"Offline-Status: {report['summary']['state']}. "
            "Kein Spieltest, keine automatische Freigabe oder Installation."
        )
        self.canvas.delete("all")

    def inventory_qa(self):
        """Read-only historical QA tool audit, no script executed/copied."""
        folder = filedialog.askdirectory(
            parent=self,title="Älteren Sprite-Suite-Projektordner für QA-Abgleich wählen",
            initialdir=str(ROOT.parent)
        )
        if not folder:
            return
        from stronghold_europe_de.qa_inventory import (
            InventoryError, inventory_legacy_tools, save_inventory
        )
        try:
            report=inventory_legacy_tools(folder,ROOT)
            destination=save_inventory(report,ROOT)
        except (InventoryError,OSError,ValueError) as exc:
            messagebox.showwarning("QA-Altbestand",str(exc),parent=self)
            return
        status={
            "nur_im_altbestand":("warnung","Im Altbestand gefunden; Kompatibilität prüfen"),
            "abweichende_version":("warnung","Unterschiedliche Version; nicht automatisch kopieren"),
            "bereits_identisch":("info","Bereits im aktuellen Projekt identisch"),
            "nicht_gefunden":("info","In diesem Altprojekt nicht vorhanden"),
        }
        self.findings=[]
        self.table.delete(*self.table.get_children())
        for idx,row in enumerate(report["tools"]):
            severity,info=status[row["status"]]
            detail=(
                f"{info}. Zweck: {row['zweck']}. Risiko: {row['risiko']}. "
                f"{row['hinweis']}"
            )
            finding={
                "schwere":severity,"pruefung":"Altwerkzeug",
                "gruppe":row["name"],"text":detail,
                "daten":{"quelle":row["quelle"],
                         "sha256":row["alte_sha256"],
                         "status":row["status"]},
            }
            self.findings.append(finding)
            self.table.insert("", "end", iid=str(idx),
                              values=(severity,"Altwerkzeug",row["name"],detail))
        self._update_findings_status("QA-Altbestand (nur lesend)")
        self.app.log(
            f"QA-Altbestand gelesen: {len(report['tools'])} bekannte Programme, "
            f"{report['legacy_test_module_count']} historische Testmodule. "
            f"Prüfbericht: {destination} (nur lesend).","muted"
        )

    def _update_findings_status(self, kind: str):
        """Keep the report view intact while its status changes language."""
        self._diagnostic_status = ("report", kind)
        self.refresh_status()

    def refresh_status(self):
        state, value = self._diagnostic_status
        english = LANG.code == "en"
        if state == "initial":
            message = (
                "No diagnostics loaded. »Check everything« starts a new check."
                if english else
                "Noch keine Diagnose geladen. »Alles prüfen« startet eine neue Prüfung."
            )
        elif state == "requested":
            message = (
                f"Requested diagnostic »{value}«. Results appear after the check finishes."
                if english else
                f"Diagnose »{value}« angefordert. "
                "Das Ergebnis erscheint nach Abschluss der Prüfung."
            )
        elif state == "missing":
            message = (
                "No diagnostic report yet. Choose »Check everything« or a "
                "specific check. No game installation is required."
                if english else
                "Noch kein Diagnosebericht vorhanden. Mit »Alles prüfen« "
                "oder einer konkreten Prüfart beginnen. "
                "Die Prüfung läuft ohne Spielinstallation."
            )
        elif state == "error":
            message = (
                f"Cannot read diagnostic report: {value}. "
                "Use »Check everything« to create a new report; "
                "existing files were not changed."
                if english else
                f"Diagnosebericht nicht lesbar: {value}. "
                "Mit »Alles prüfen« einen neuen Bericht erstellen; "
                "vorhandene Dateien wurden nicht verändert."
            )
        elif state == "report":
            kind = LANG.tr(value) if english else value
            count = len(self.table.get_children())
            if count:
                message = (
                    f"{kind}: {count} {'entry' if count == 1 else 'entries'}. "
                    "Select a finding to view details; double-click sprite "
                    "findings to open them in the catalogue."
                    if english else
                    f"{kind}: {count} {'Eintrag' if count == 1 else 'Einträge'}. "
                    "Befund auswählen für Details; Doppelklick springt "
                    "bei Spritebefunden zum Katalog."
                )
            else:
                message = (
                    f"{kind}: No entries. This is not a BC7 or in-game approval."
                    if english else
                    f"{kind}: Keine Einträge. "
                    "Das ist keine BC7- oder Ingame-Freigabe."
                )
        else:
            message = str(value or "")
        self.findings_status.set(message)

    def run(self, check):
        args = [tool("grafik_diagnose.py"), check]
        if self.mod.get().strip():
            args += ["--mod", self.mod.get().strip()]
        if check in ("umlenkungen", "alles"):
            args.append("--bilder")
        self._diagnostic_status = ("requested", check)
        self.refresh_status()
        self.app.run(args, f"Diagnose {check}")

    def load(self):
        report_path = ROOT / "work" / "diagnose" / "bericht.json"
        self.table.delete(*self.table.get_children())
        # A previous SHA-256/Pivot/legacy report is not the current
        # on-disk graphic diagnostic. Do not leave obsolete pictures or
        # details visible when switching back to that report.
        self.detail.configure(text="")
        self.canvas.delete("all")
        self.photo = None
        try:
            if report_path.exists():
                if report_path.is_symlink() or not report_path.is_file():
                    raise ValueError("Bericht ist keine reguläre JSON-Datei")
                # The generic catalogue loader intentionally returns an
                # empty default on malformed JSON. In diagnostics that would
                # wrongly imply zero findings; parsing must report errors.
                report = json.loads(
                    report_path.read_text(encoding="utf-8-sig")
                )
            else:
                report = {"befunde": []}
            if not isinstance(report, dict) or not isinstance(
                report.get("befunde", []), list
            ):
                raise ValueError("Befundbericht hat kein gültiges Format")
            self.findings = report.get("befunde", [])
            order = {"fehler": 0, "warnung": 1, "info": 2}
            for n, item in sorted(
                enumerate(self.findings),
                key=lambda pair: order.get(pair[1]["schwere"], 3),
            ):
                self.table.insert(
                    "", "end", iid=str(n),
                    values=(item["schwere"], item["pruefung"],
                            item["gruppe"], item["text"]),
                )
        except (UnicodeError, ValueError, TypeError, KeyError, OSError) as exc:
            # A partially rendered corrupt report cannot masquerade as a
            # successfully loaded subset of findings.
            self.table.delete(*self.table.get_children())
            self.findings = []
            self._diagnostic_status = ("error", str(exc))
            self.refresh_status()
            return
        if not report_path.is_file():
            self._diagnostic_status = ("missing", None)
            self.refresh_status()
        else:
            self._update_findings_status("Letzter Diagnosebericht")

    def current(self):
        sel = self.table.selection()
        return self.findings[int(sel[0])] if sel else None

    def select(self, _event=None):
        from PIL import Image, ImageTk

        item = self.current()
        if not item:
            return
        text = item["text"]
        if item.get("behebung"):
            text += "\n\nBehebung: " + item["behebung"]
        if item.get("frames"):
            text += "\n\nFrames: " + ", ".join(item["frames"][:20]) + (" ..." if len(item["frames"]) > 20 else "")
        self.detail.configure(text=text)
        self.canvas.delete("all")
        picture = (item.get("daten") or {}).get("bild")
        if picture and Path(picture).is_file():
            image = Image.open(picture).convert("RGBA")
            image.thumbnail((max(self.canvas.winfo_width(), 400), max(self.canvas.winfo_height(), 300)))
            self.photo = ImageTk.PhotoImage(image)
            self.canvas.create_image(0, 0, anchor="nw", image=self.photo)

    def open_in_catalog(self, _event=None):
        item = self.current()
        if item and item.get("pruefung") == "Nativ-Frame":
            from pivot_native_proof_rows import catalog_frame_name
            frame = catalog_frame_name(item)
            if frame is not None:
                self.app.show_in_catalog("anim_castle", frame)
            return
        if item and item.get("pruefung") in ("Altwerkzeug", "Release", "Pivot-Stufe", "BC7-Probe", "Nativ-Proof"):
            # QA tool names and release-check names are not sprite groups.
            # Double-click must never execute scripts or open arbitrary frames.
            return
        if item and item["gruppe"] not in ("-", ""):
            frame = item["frames"][0] if item.get("frames") else None
            self.app.show_in_catalog(item["gruppe"], frame)

    def mark_ok(self):
        item = self.current()
        key = (item or {}).get("daten", {}).get("schluessel")
        if not key:
            messagebox.showinfo("Markieren", "Nur Umlenkungs-Befunde lassen sich als geprueft markieren.", parent=self)
            return
        path = ROOT / "config" / "umlenkungen-pruefung.json"
        data = katalog.load_json(path, {"geprueft": {}})
        data.setdefault("geprueft", {})[key] = "ok"
        katalog.save_json(path, data)
        self.app.log(f"Als geprueft markiert: {key}", "ok")

    def adopt(self):
        profile = getattr(self.app, "bc7_profile", None)
        name = f"profiles/{profile.get()}.json" if profile else "profiles/europe-production-bc7-v2.json"
        if not (ROOT / name).is_file():
            messagebox.showwarning(
                "Nachweise übernehmen",
                f"Das ausgewählte Profil ist nicht vorhanden: {name}",
                parent=self,
            )
            return
        if not messagebox.askyesno(
            "Profil-Nachweise ändern",
            f"Die aus dem Diagnoseprotokoll übernommenen Werte können "
            f"das Profil {name} dauerhaft verändern.\n\n"
            "Das ist KEINE Spielinstallation und KEINE allgemeine "
            "BC7-Releasefreigabe. Nur nach eigener Prüfung fortfahren?",
            default="no", icon="warning", parent=self,
        ):
            return
        self.app.run(
            [tool("pin_digests.py"), "--profile", name, "--aus-protokoll"],
            "Nachweise uebernehmen",
        )


# ====================================================================== Sandkasten

class SandboxTab(ttk.Frame):
    """One integrated Qt Sandbox Studio inside the existing Tk notebook."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.bridge = None
        self._starting = False
        self._pending_sprite = None
        self._console_hidden = False
        header = ttk.Frame(self)
        header.pack(fill="x", padx=6, pady=(3, 0))
        ttk.Label(
            header, text="Sandbox Studio",
            style="Head.TLabel"
        ).pack(side="left")
        self.caption = ttk.Label(
            header, text="F4 Spielkarte · F2 Testfeld · F6 Palette · F9 Fokus",
            style="Muted.TLabel"
        )
        self.caption.pack(side="left", padx=12)
        # Five short, dependable actions fit a narrow notebook. Longer and
        # less common workflows remain discoverable via the labelled menu,
        # rather than silently falling off the right edge of a button strip.
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=6, pady=(0, 2))
        self.quick_buttons = {}
        for title, callback in (
            ("Karte öffnen", self.choose_map),
            ("Palette", self.toggle_palette),
            ("Inspector", self.toggle_inspector),
            ("Fokus", self.toggle_focus),
            ("Layout zurück", self.restore_layout),
        ):
            button = ttk.Button(bar, text=title, command=callback)
            button.pack(side="left", padx=(0, 5))
            self.quick_buttons[title] = button
        self.more_button = ttk.Menubutton(bar, text="Weitere Werkzeuge ▾")
        actions = tk.Menu(self.more_button, tearoff=False)
        for title, callback in (
            ("Kartenordner wählen", self.choose_folder),
            ("Szene speichern", self.save_scene),
            ("Originalgrafik im Katalog", self.show_in_catalog),
            ("Animation / Frames", self.show_animation),
            ("Spiel-HUD", self.show_game_hud),
            ("Pixelvergleich", self.compare),
        ):
            actions.add_command(label=title, command=callback)
        self.more_button.configure(menu=actions)
        self.more_button.pack(side="left")
        self.message = tk.StringVar(
            value=LANG.tr("Beim ersten Öffnen wird der Karteneditor direkt in diesen Reiter geladen.")
        )
        self.label = ttk.Label(
            self, textvariable=self.message, style="Muted.TLabel"
        )
        self.label.pack(anchor="w", padx=7, pady=(0, 3))
        self.host = tk.Frame(self, bg="#151c1b", bd=0, highlightthickness=0)
        self.host.pack(fill="both", expand=True, padx=4, pady=(0, 4))
        app.notebook.bind("<<NotebookTabChanged>>", self._tab_changed, add="+")

    def _status(self, text):
        if self.winfo_exists():
            self.message.set(text)
        try:
            self.app.log(text, "muted")
        except (AttributeError, RuntimeError):
            pass

    def _tab_changed(self, _event=None):
        if hasattr(self.app, "_apply_console_visibility"):
            # The full Universal Suite now owns the log policy on EVERY tab.
            # Preserve the user's toggle choice across sandbox navigation.
            self.app._apply_console_visibility()
            if self.app.notebook.select() == str(self):
                self.after(45, self.ensure_studio)
            return
        # Standalone/older Tk host compatibility without that control.
        if self.app.notebook.select() == str(self):
            if not self._console_hidden:
                self.app.console.master.pack_forget()
                self._console_hidden = True
                self.app.update_idletasks()
            self.after(45, self.ensure_studio)
        elif self._console_hidden:
            self.app.console.master.pack(
                before=self.app.notebook, side="bottom", fill="both",
                padx=14, pady=(0,12)
            )
            self._console_hidden = False

    def _game_root(self):
        # Match the native editor's startup selection. If the target game
        # is missing, show an empty map picker rather than E:/SSGameQA.
        from stronghold_europe_de.sandbox.maps_configuration import configured_map_root
        return configured_map_root(ROOT)

    def ensure_studio(self):
        if self.bridge is not None:
            return self.bridge
        if self._starting:
            return None
        if not self.host.winfo_ismapped():
            # When Notebook.select() just ran, Tk may not have mapped this
            # page yet. Resolve pending geometry before deferring creation.
            self.app.update_idletasks()
            if not self.host.winfo_ismapped():
                self.after(65, self.ensure_studio)
                return None
        self._starting = True
        self.message.set(LANG.tr("Sandbox Studio wird als Bestandteil der Suite geladen …"))
        self.app.update_idletasks()
        try:
            from sandbox_suite_embed import EmbeddedSandboxStudio
            self.bridge = EmbeddedSandboxStudio(
                self.host, maps_root=self._game_root(), status=self._status
            )
        except Exception as exc:
            self.message.set(
                f"Der integrierte Karteneditor konnte nicht geladen werden: {exc}"
            )
            self._status(self.message.get())
            return None
        finally:
            self._starting = False
        self.message.set(LANG.tr(
            "Integriert · F4 Spielkarte · Strg+E Sprite bearbeiten · "
            "Mausrad Zoom · mittlere Taste verschieben"
        ))
        if self._pending_sprite is not None:
            group, frame = self._pending_sprite
            self._pending_sprite = None
            self.bridge.select_sprite(group, frame)
        return self.bridge

    def select_sprite(self, group, frame):
        self._pending_sprite = (group, frame)
        self.app.notebook.select(self)
        bridge = self.ensure_studio()
        if bridge is not None:
            self._pending_sprite = None
            bridge.select_sprite(group, frame)

    def choose_map(self):
        self.app.notebook.select(self)
        bridge = self.ensure_studio()
        if bridge is not None:
            bridge.window.choose_map()

    def choose_folder(self):
        self.app.notebook.select(self)
        bridge = self.ensure_studio()
        if bridge is not None:
            bridge.window.choose_folder()

    def save_scene(self):
        bridge = self.ensure_studio()
        if bridge is not None:
            bridge.window.save_active()

    def compare(self):
        bridge = self.ensure_studio()
        if bridge is not None:
            bridge.window.open_reference_comparison()

    def toggle_palette(self):
        bridge = self.ensure_studio()
        if bridge is not None:
            bridge.toggle_palette()

    def toggle_inspector(self):
        bridge = self.ensure_studio()
        if bridge is not None:
            bridge.toggle_inspector()

    def toggle_focus(self):
        bridge = self.ensure_studio()
        if bridge is not None:
            bridge.toggle_focus()

    def restore_layout(self):
        bridge = self.ensure_studio()
        if bridge is not None:
            bridge.restore_layout()

    def show_animation(self):
        self.app.notebook.select(self)
        bridge = self.ensure_studio()
        if bridge is not None:
            bridge.window.show_test_field()
            if hasattr(bridge, 'show_tool'):
                bridge.show_tool(bridge.window._animation_dock)
            else:
                bridge.window._animation_dock.raise_()

    def show_game_map(self):
        self.app.open_tab(self)
        bridge = self.ensure_studio()
        if bridge is not None:
            bridge.window.show_native_map()

    def show_game_hud(self):
        self.app.notebook.select(self)
        bridge = self.ensure_studio()
        if bridge is not None:
            bridge.window.show_native_map()
            if hasattr(bridge, 'show_tool'):
                bridge.show_tool(bridge.window._hud_dock)
            else:
                bridge.window._hud_dock.raise_()

    def show_in_catalog(self):
        if self.bridge is None:
            self._status("Zuerst ein Sprite in der Sandbox wählen.")
            return
        picked = self.bridge.selected_sprite()
        if picked:
            group, frame = picked
            self.app.show_in_catalog(group, katalog.native_name(group, frame))

    def close_studio(self):
        if self.bridge is None:
            return True
        if not self.bridge.close():
            return False
        self.bridge = None
        return True


# ====================================================================== Editor & Austausch

class ExchangeTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.section_targets = {}
        jump_row = ttk.Frame(self)
        jump_row.pack(fill="x", padx=8, pady=(5, 1))
        ttk.Label(
            jump_row, text="Direkt zu:", style="Muted.TLabel"
        ).pack(side="left", padx=(0, 7))
        self.section_choice = tk.StringVar()
        self.section_picker = ttk.Combobox(
            jump_row, textvariable=self.section_choice,
            state="readonly", width=43
        )
        self.section_picker.pack(side="left")
        self.section_picker.bind(
            "<<ComboboxSelected>>", self.jump_to_section
        )
        self.form_scroll = ScrollableColumn(self, background=BG)
        self.form_scroll.pack(fill="both", expand=True)
        form = self.form_scroll.body
        ttk.Label(form, text="Editor & Austausch", style="Title.TLabel").pack(anchor="w", padx=8, pady=(12, 2))

        def section(title, note):
            heading = ttk.Label(form, text=title, style="Head.TLabel")
            heading.pack(anchor="w", padx=8, pady=(12, 0))
            key = title.split(" (")[0]
            self.section_targets[key] = heading
            self.section_picker.configure(values=list(self.section_targets))
            ttk.Label(form, text=note, style="Muted.TLabel", wraplength=900, justify="left").pack(anchor="w", padx=8)
            frame = ttk.Frame(form)
            frame.pack(fill="x", padx=8, pady=4)
            return frame

        f = section("HTML-Sprite-Editor (Stronghold Sprite Editor 1.0)",
                    "Hin: Gruppe/Bereich als ZIP + Zielreferenzen + Zuordnung verpacken. Zurueck: Modpaket-ZIP, "
                    "Tiles-ZIP, .shsprite oder Ordner - jedes Bild wird auf seinen Crusader-Platz eingepasst.")
        self.group = labelled_entry(f, "Gruppe", "", 22)
        self.side = tk.StringVar(value="arbeit")
        ttk.Combobox(f, values=["arbeit", "geliefert", "crusader", "stronghold1"], textvariable=self.side,
                     state="readonly", width=11).pack(side="left", padx=4)
        self.lo = labelled_entry(f, "von", "", 6)
        self.hi = labelled_entry(f, "bis", "", 6)
        html_actions = ttk.Frame(form)
        html_actions.pack(fill="x", padx=8, pady=(0, 4))
        ttk.Button(html_actions, text="Fuer Editor verpacken", command=self.export).pack(side="left", padx=6)
        ttk.Button(html_actions, text="Editor oeffnen", command=lambda: app.run([tool("editor_bruecke.py"), "oeffnen"], "Editor")).pack(side="left", padx=3)
        ttk.Button(html_actions, text="Ergebnis zurueckholen ...", command=self.import_result).pack(side="left", padx=3)
        ttk.Button(html_actions, text="Ordner work/editor", command=lambda: os.startfile(self._ensure(ROOT / "work" / "editor"))).pack(side="left", padx=3)

        f = section("SE-Atlas mit AtlasBuilder (Override/Atlas, PNG oder BC7-DDS)",
                    "Lieferweg ohne eigene DLL: der Script Extender laedt die Atlanten selbst. Gruppen kommagetrennt.")
        self.atlas_groups = labelled_entry(f, "Gruppen", "", 30)
        self.atlas_source = tk.StringVar(value="arbeit")
        ttk.Combobox(f, values=["arbeit", "geliefert", "stronghold1", "crusader"], textvariable=self.atlas_source,
                     state="readonly", width=11).pack(side="left", padx=4)
        self.atlas_format = tk.StringVar(value="bc7-dds")
        ttk.Combobox(f, values=["bc7-dds", "png"], textvariable=self.atlas_format, state="readonly", width=8).pack(side="left", padx=4)
        atlas_options = ttk.Frame(form)
        atlas_options.pack(fill="x", padx=8, pady=(0, 4))
        self.atlas_name = labelled_entry(atlas_options, "Mod-Name", "EuropaSEAtlas", 16)
        self.only_changed = tk.BooleanVar(value=True)
        ttk.Checkbutton(atlas_options, text="nur geaenderte Frames", variable=self.only_changed).pack(side="left", padx=4)
        asset_row = section(
            "Statisches HUD-/GUI-Assetpaket (ohne SE-Versionsbindung)",
            "Erstellt ein Asset-Mod mit Manifest 0, ohne eigene Runtime-DLL, "
            "ohne SE-Installation und ohne feste Script-Extender-Version. "
            "Die Dateien müssen zuvor unter work/<Ordner>/Override oder "
            "work/<Ordner>/Patches bearbeitet worden sein."
        )
        ttk.Button(
            asset_row, text="DLL-freies Asset-Modpaket bauen ...",
            command=self.asset_mod_build,
        ).pack(side="left", padx=5)
        p = section(
            "Pivot-Vermessung aus dem Spiel (Zinnenlineal)",
            "Messwerte der laufenden Spielprobe mit aktuellen Sprite-Indizes "
            "abgleichen; Vorher/Nachher anzeigen und nur einen sicheren "
            "Prüfbericht erzeugen. Keine automatische Atlas-Änderung."
        )
        ttk.Button(
            p,text="Pivot-Messungen prüfen …",command=self.open_pivot_review
        ).pack(side="left",padx=6)

        f2 = ttk.Frame(form)
        f2.pack(fill="x", padx=8)
        ttk.Button(f2, text="Projekt erzeugen", command=self.atlas_project).pack(side="left", padx=3)
        ttk.Button(f2, text="Bauen", command=self.atlas_build).pack(side="left", padx=3)
        ttk.Button(f2, text="AtlasBuilder-Oberflaeche", command=lambda: app.run([tool("se_atlas.py"), "gui"], "AtlasBuilder")).pack(side="left", padx=3)
        ttk.Button(f2, text="Ausgabe oeffnen", command=lambda: os.startfile(self._ensure(ROOT / "work" / "se-atlas"))).pack(side="left", padx=3)

        f = section("Mehrteilige Gebaeude als Ebenen (OpenRaster, .ora)",
                    "Ein Kachelobjekt als ORA mit einer Ebene je Kachel zusammensetzen (GM1-Teilfolge), in einem "
                    "Malprogramm mit Ebenen (Krita, GIMP) bearbeiten und verlustfrei zurueckzerlegen.")
        self.ora_group = labelled_entry(f, "Gruppe", "tile_buildings2", 18)
        self.ora_from = labelled_entry(f, "ab", "1192", 7)
        self.ora_n = labelled_entry(f, "Raster NxN", "4", 4)
        ttk.Button(f, text="Als ORA zusammensetzen", command=self.ora_compose).pack(side="left", padx=6)
        ttk.Button(f, text="ORA zuruecknehmen ...", command=self.ora_split).pack(side="left", padx=3)
        self.form_scroll.bind_mousewheel()
        if self.section_targets:
            self.section_choice.set(next(iter(self.section_targets)))

    def jump_to_section(self, _event=None):
        """Scroll to a named editor tool without requiring wheel precision."""
        target = self.section_targets.get(self.section_choice.get())
        if target is not None:
            self.form_scroll.show_at_top(target)

    def open_pivot_review(self):
        from pivot_review_gui import PivotReviewWindow
        existing = getattr(self, "_pivot_review_window", None)
        if existing is not None and existing.winfo_exists():
            existing.lift()
            return existing
        window = PivotReviewWindow(self.app,ROOT)
        self._pivot_review_window = window
        return window

    @staticmethod
    def _ensure(path: Path) -> Path:
        path.mkdir(parents=True, exist_ok=True)
        return path

    def export(self):
        group = self.group.get().strip()
        if not group:
            messagebox.showinfo(
                "Editor-Export", "Bitte zuerst eine Spritegruppe eingeben.",
                parent=self,
            )
            return
        args = [tool("editor_bruecke.py"), "export", group, "--seite", self.side.get()]
        if self.lo.get():
            args += ["--von", self.lo.get()]
        if self.hi.get():
            args += ["--bis", self.hi.get()]
        self.app.run(args, "Export fuer Editor")

    def import_result(self):
        path = filedialog.askopenfilename(parent=self, filetypes=[("Editor-Ergebnis", "*.zip;*.semod;*.shsprite;*.png")])
        if path:
            self.app.run([tool("editor_bruecke.py"), "import", path], "Editor-Ergebnis zurueckholen")

    def asset_mod_build(self):
        """Build a static GUI/sprite mod, never install a Script Extender."""
        source = filedialog.askdirectory(
            parent=self, initialdir=str(ROOT / "work"),
            title="Asset-Mod-Ordner mit Override/ und Patches/ unter work/ wählen",
        )
        if not source:
            return
        guid = simpledialog.askstring(
            "Asset-Mod GUID", "Eindeutige Mod-ID (z. B. europe_gui):",
            parent=self,
        )
        if not guid:
            return
        name = simpledialog.askstring(
            "Asset-Mod", "Anzeigename des Modpakets:", parent=self,
            initialvalue=guid,
        )
        if not name:
            return
        if not messagebox.askyesno(
            "Asset-Modpaket ohne Runtime-DLL",
            "Nur PNG/JPG/DDS/JSON und statische XAML-Patches werden "
            "in einen getrennten Ordner und ein ZIP unter work/ verpackt. "
            "Der Script Extender und das Spiel werden nicht geändert. "
            "Paket erzeugen?",
            parent=self,
            default="no",
        ):
            return
        self.app.run(
            [tool("se_asset_package.py"), "--source", source,
             "--guid", guid, "--name", name],
            "DLL-freies HUD-/GUI-Assetpaket für vorhandenen Script Extender",
        )

    def atlas_project(self):
        groups = self.atlas_groups.get().strip()
        if not groups:
            messagebox.showinfo(
                "SE-Atlas-Projekt", "Bitte mindestens einen Gruppennamen eingeben.",
                parent=self,
            )
            return
        args = [tool("se_atlas.py"), "projekt", "--gruppen", groups, "--quelle", self.atlas_source.get(),
                "--name", self.atlas_name.get() or "EuropaSEAtlas", "--format", self.atlas_format.get()]
        if self.only_changed.get() and self.atlas_source.get() == "arbeit":
            args.append("--nur-geaenderte")
        self.app.run(args, "SE-Atlas-Projekt")

    def atlas_build(self):
        name = self.atlas_name.get().strip() or "EuropaSEAtlas"
        if ("/" in name or "\\" in name or ".." in name or len(name) > 100):
            messagebox.showwarning(
                "SE-Atlas bauen", "Ungültiger Modname bzw. Pfad.",
                parent=self,
            )
            return
        path = ROOT / "work" / "se-atlas" / f"{name}.atlas-project.json"
        if not path.is_file():
            messagebox.showinfo(
                "SE-Atlas bauen",
                f"Noch kein Atlasprojekt gefunden: {path.name}. "
                "Zuerst „Projekt erzeugen“ auswählen.",
                parent=self,
            )
            return
        self.app.run([tool("se_atlas.py"), "bauen", str(path)], "SE-Atlas bauen")

    def ora_compose(self):
        group = self.ora_group.get().strip()
        if not group:
            messagebox.showinfo(
                "ORA zusammensetzen", "Bitte eine Spritegruppe eingeben.",
                parent=self,
            )
            return
        try:
            start = int(self.ora_from.get().strip())
            n = int(self.ora_n.get().strip())
        except ValueError:
            messagebox.showwarning(
                "ORA zusammensetzen",
                "Startindex und Raster NxN müssen ganze Zahlen sein.",
                parent=self,
            )
            return
        if start < 0 or not 1 <= n <= 16:
            messagebox.showwarning(
                "ORA zusammensetzen",
                "Startindex muss ≥ 0 sein; das Raster muss zwischen "
                "1×1 und 16×16 liegen.",
                parent=self,
            )
            return
        katalog.ensure_work(group)
        out = f"work/objects/{katalog.slug(group)}-{start}"
        self.app.run([tool("tile_objects.py"), "compose", str(katalog.work_dir(group)), "--from", str(start), "--to",
                      str(start + n * n - 1), "--columns", str(n), "--rows", str(n), "--layout", "gm1", "--out", out,
                      "--replace"], "ORA zusammensetzen")

    def ora_split(self):
        folder = filedialog.askdirectory(parent=self, initialdir=str(ROOT / "work" / "objects"), title="ORA-Paketordner")
        if not folder:
            return
        out = str(ROOT / "work" / "ora-rueck" / Path(folder).name)
        run_then_success(
            self.app,
            [tool("tile_objects.py"), "split", folder, "--out", out,
             "--replace", "--confirm-custom-layout"],
            "ORA zerlegen",
            lambda: self.app.run(
                [tool("editor_bruecke.py"), "import", out],
                "ORA-Ergebnis uebernehmen",
            ),
            next_step="ORA-Ergebnis importieren",
        )


# ====================================================================== Ziel & SE

class TargetTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        ttk.Label(self, text="Ziele & Mods", style="Title.TLabel").pack(anchor="w", padx=8, pady=(12, 2))
        ttk.Label(self, text=(
            "Jede SHCDE-Spielversion kann registriert werden – auch unbekannte Releases. "
            "Dafür werden fünf Originaldateien per SHA-256 identifiziert, nicht "
            "anhand einer Versions-Whitelist. Registrieren aktiviert niemals "
            "automatisch. Erst Aktivieren verlangt ein genau zu dieser Dateiidentität "
            "passendes Sprite-Mapping, eine lesbare SH1DE-Quelle und eine ausdrückliche Bestätigung. "
            "Dadurch wird nichts installiert. Mod-Installation und "
            "Sicherungswiederherstellung bleiben ans ausdrücklich aktivierte "
            "Ziel gebunden. Der vorhandene Script Extender wird nicht getauscht."), style="Muted.TLabel", wraplength=1150,
            justify="left").pack(anchor="w", padx=8)
        self.actions = CompactActionBar(
            self,
            primary=(
                ("Ziel hinzufügen ...", self.add),
                ("Aktivieren", self.activate),
                ("Aktualisieren", self.load),
            ),
            more=(
                ("Mod installieren ... (mit Sicherung)", self.install_mod),
                ("Mod entfernen (mit Sicherung)", self.remove_mod),
                ("Sicherungen anzeigen / zurückspielen", self.backups),
            ),
            overflow_label="Installation & Sicherungen ▾",
        )
        self.actions.pack(fill="x", padx=8, pady=(5, 3))
        self.target_status = tk.StringVar(
            value=LANG.tr("Zielspiele werden eingelesen …")
        )
        ttk.Label(
            self, textvariable=self.target_status,
            style="Muted.TLabel", wraplength=850,
        ).pack(fill="x", padx=8, pady=(1, 3))
        self.target_table_frame = ttk.Frame(self)
        self.target_table_frame.pack(fill="both", expand=True, padx=8, pady=(2, 6))
        self.table_scroll_x = ttk.Scrollbar(
            self.target_table_frame, orient="horizontal"
        )
        self.table = ttk.Treeview(
            self.target_table_frame,
            columns=("aktiv", "spielstand", "se", "mod", "sicherungen", "pfad"),
            show="tree headings", height=10,
            xscrollcommand=self.table_scroll_x.set,
        )
        self.table_scroll_x.configure(command=self.table.xview)
        self.table_scroll_x.pack(side="bottom", fill="x")
        self.table.pack(fill="both", expand=True)
        self.table.heading("#0", text="Ziel")
        self.table.column("#0", width=155, minwidth=110, stretch=False)
        for col, width in (("aktiv", 50), ("spielstand", 110), ("se", 110),
                           ("mod", 220), ("sicherungen", 90), ("pfad", 520)):
            self.table.heading(col, text=col.capitalize())
            self.table.column(col, width=width, minwidth=55, stretch=False)
        self.after(700, self.load)

    def load(self):
        import ziel_se211

        self.table.delete(*self.table.get_children())
        try:
            data = ziel_se211.targets()
            if not isinstance(data, dict) or not isinstance(
                data.get("ziele", {}), dict
            ):
                raise ValueError("Ziel-Registry ist kein gültiges Verzeichnis")
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            self.target_status.set(
                (f"Could not read targets: {exc}. "
                 "Existing settings were not changed."
                 if LANG.code == "en" else
                 f"Ziele konnten nicht gelesen werden: {exc}. "
                 "Die vorhandenen Einstellungen wurden nicht verändert.")
            )
            return
        destinations = data.get("ziele", {})
        if destinations:
            active = data.get("aktiv")
            if LANG.code == "en":
                self.target_status.set(
                    f"{len(destinations)} target(s) registered. "
                    + (f"Active: {active}." if isinstance(active, str) and active in destinations
                       else "No active target selected.")
                    + " Select a row, then choose an action."
                )
            else:
                self.target_status.set(
                    f"{len(destinations)} Zielspiel(e) registriert. "
                    + (f"Aktiv: {active}." if isinstance(active, str) and active in destinations
                       else "Noch kein aktives Ziel gewählt.")
                    + " Ziel in der Tabelle markieren, dann Aktion auswählen."
                )
        else:
            self.target_status.set(
                ("No target game registered yet. Use »Add target ...« "
                 "to select an existing Crusader DE game folder. "
                 "Nothing will be installed by this action."
                 if LANG.code == "en" else
                 "Noch kein Zielspiel registriert. "
                 "Mit »Ziel hinzufügen …« einen vorhandenen "
                 "Crusader-DE-Spielordner auswählen. "
                 "Es wird dadurch noch nichts installiert.")
            )
        invalid_entries = 0
        for name, spec in destinations.items():
            if not isinstance(name, str) or not name or not isinstance(spec, dict):
                invalid_entries += 1
                continue
            try:
                row = ziel_se211.describe(name, spec)
            except Exception as exc:
                row = {"spiel": spec.get("spiel"), "se": f"? ({exc})"}
            se = row.get("se") or "kein SE"
            self.table.insert("", "end", iid=name, text=name, values=(
                "●" if name == data.get("aktiv") else "", row.get("spielstand", "?"), se,
                row.get("europa_mod") or "-", row.get("sicherungen", 0), row.get("spiel")))
        if invalid_entries:
            warning = (
                f" Warning: {invalid_entries} invalid target entries skipped. "
                "Check configuration; original files unchanged."
                if LANG.code == "en" else
                f" Achtung: {invalid_entries} "
                "ungültige Registry-Einträge ausgelassen. "
                "Konfiguration prüfen; Originaldatei bleibt unverändert."
            )
            self.target_status.set(self.target_status.get() + warning)

    def current(self):
        sel = self.table.selection()
        if not sel:
            messagebox.showinfo(
                "Ziel",
                ("Noch kein Ziel vorhanden: Bitte zuerst »Ziel hinzufügen …« "
                 "wählen." if not self.table.get_children()
                 else "Bitte in der Tabelle ein Ziel auswählen."),
                parent=self,
            )
            return None
        return sel[0]

    def add(self):
        folder = filedialog.askdirectory(parent=self, title="Spielordner von Stronghold Crusader DE")
        if not folder:
            return
        name = simpledialog.askstring("Ziel", "Kurzname (z.B. e-27, d-kopie):", parent=self)
        if name:
            if not messagebox.askyesno(
                "Verifiziertes Spielziel registrieren",
                f"Zielname: {name}\nSpielordner: {folder}\n\n"
                "Der Ordner wird nur gelesen und anhand aller fünf SHA-256-Pins "
                "gegen die aktuelle Mappingversion geprüft. "
                "Keine automatische Aktivierung oder Installation. Fortfahren?",
                icon="warning",default="no",parent=self):
                return
            self.app.run([tool("ziel_se211.py"), "hinzufuegen", "--name",
                          name, "--spiel", folder], "Ziel versioniert registrieren")

    def activate(self):
        name=self.current()
        if not name:return
        import ziel_se211
        try:
            target=ziel_se211.targets()["ziele"][name]
        except (KeyError,OSError,ValueError) as exc:
            messagebox.showerror("Ziel",str(exc),parent=self)
            return
        source=""
        try:
            import tomllib
            config=ziel_se211.CONFIG
            if config.is_file():
                source=tomllib.loads(config.read_text(encoding="utf-8")).get(
                    "source",{}).get("data_dir","")
        except (OSError,ValueError):
            source=""
        # At first setup, no source is configured yet; allow explicit selection.
        if not source:
            source=filedialog.askdirectory(
                parent=self,
                title="Stronghold 1 Definitive Edition_Data auswählen (read-only)")
            if not source:return
        if not messagebox.askyesno(
            "Versionsgebundenes Produktionsziel aktivieren",
            f"Ziel: {name}\n{target['spiel']}\n"
            f"Registrierter Build: {target.get('build_id','NICHT GEPRÜFT')}\n"
            f"Stronghold-1-Quelle: {source}\n\n"
            "Es werden zuerst ALLE 10 SHA-256-Quelldateien geprüft. "
            "Nur bei exakter Mapping- und Versionsidentität werden die "
            "Konfigurationsdateien umgestellt. Alte Mappings, Builds und "
            "Spielinstallationen bleiben unangetastet. Ziel wirklich wählen?",
            icon="warning",default="no",parent=self):
            return
        self.app.run([tool("ziel_se211.py"),"aktivieren",name,
                      "--source-data",source],f"Ziel {name} verifiziert aktivieren")

    def install_mod(self):
        name = self.current()
        if not name:
            return
        folder = filedialog.askdirectory(parent=self, initialdir=str(ROOT / "dist"), title="Modordner (z.B. dist/<profil>/StrongholdEuropeDE)")
        if folder and messagebox.askyesno("Mod installieren", f"{Path(folder).name} in '{name}' installieren?\n"
                                          "Ein vorhandener gleichnamiger Ordner wird vorher gesichert.", parent=self):
            self.app.run([tool("ziel_se211.py"), "mod-installieren", name, "--quelle", folder], "Mod installieren")

    def remove_mod(self):
        name = self.current()
        if not name:
            return
        folder = simpledialog.askstring("Mod entfernen", "Ordnername unter BepInEx/plugins:", initialvalue="StrongholdEuropeDE", parent=self)
        if folder and messagebox.askyesno("Mod entfernen", f"{folder} aus '{name}' entfernen (mit Sicherung)?", parent=self):
            self.app.run([tool("ziel_se211.py"), "mod-entfernen", name, "--ordner", folder], "Mod entfernen")

    def backups(self):
        import ziel_se211

        name = self.current()
        if not name:
            return
        _name, game = ziel_se211.resolve(name)
        entries = katalog.load_json(ziel_se211.backup_root(game) / "sicherungen.json", {"eintraege": []})["eintraege"]
        if not entries:
            messagebox.showinfo("Sicherungen", "Keine Sicherungen vorhanden.", parent=self)
            return
        listing = "\n".join(f"{e['id']}  {e['grund']}" for e in entries[-15:])
        wanted = simpledialog.askstring("Zurueckspielen", f"Sicherungen:\n{listing}\n\nID zum Zurueckspielen:", parent=self)
        if wanted and messagebox.askyesno("Zurueckspielen", f"Sicherung {wanted} in '{name}' zurueckspielen?", parent=self):
            self.app.run([tool("ziel_se211.py"), "zurueckspielen", name, "--sicherung", wanted], "Zurueckspielen")


# ====================================================================== Hauptfenster

class Universal(center.Center):
    def show_advanced(self):
        super().show_advanced()
        # The original Suite Center resets this useful mode on every launch.
        if getattr(self, "_save_advanced_preference", False):
            try:
                settings = katalog.load_json(SETTINGS, {})
                settings["erweiterte_werkzeuge"] = bool(self.advanced.get())
                katalog.save_json(SETTINGS, settings)
            except (OSError, ValueError) as exc:
                self.log(f"Ansichtseinstellung konnte nicht gespeichert werden: {exc}", "warn")
        if hasattr(self, "_navigation_entries"):
            self._refresh_tab_strip()

    def __init__(self):
        super().__init__()
        # Preserve the user's explicit choice without changing first-run defaults.
        self.advanced.set(
            katalog.load_json(SETTINGS, {}).get("erweiterte_werkzeuge", False)
            is True
        )
        self._save_advanced_preference = True
        self.show_advanced()
        self.title("Stronghold Europe / ORIGINS - Universal-Suite")
        LANG.patch_dialogs()
        self.language = tk.StringVar(value=LANG.code.upper())
        lang_box = ttk.Combobox(self.command_bar, values=["DE", "EN"], textvariable=self.language, state="readonly", width=4)
        lang_box.pack(side="right", padx=(0, 12))
        lang_box.bind("<<ComboboxSelected>>", lambda _e: self.set_language(self.language.get().lower()))
        ttk.Label(self.command_bar, text="DE / EN:", style="Muted.TLabel").pack(side="right", padx=4)
        ttk.Button(self.command_bar, text="Anleitung / Guide", command=self.open_guide).pack(side="right", padx=8)
        self.strict = tk.BooleanVar(value=os.environ.get("SEDE_STRENG") == "1")
        ttk.Checkbutton(self.command_bar, text="Streng (Warnungen sperren)", variable=self.strict,
                        command=self._strict_changed).pack(side="right", padx=12)
        self._strict_changed()
        self.catalog_tab = CatalogTab(self.notebook, self)
        self.diagnose_tab = DiagnoseTab(self.notebook, self)
        self.sandbox_tab = SandboxTab(self.notebook, self)
        self.exchange_tab = ExchangeTab(self.notebook, self)
        from suite_sh1_hud_studio import Sh1HudStudio
        from suite_origins_grafikdaten import OriginsGraphicsTab
        from suite_hud_menu_workshop import HudMenuWorkshop
        self.hud_tab = Sh1HudStudio(self.notebook, self)
        self.origins_graphics_tab = OriginsGraphicsTab(self.notebook, self)
        self.hud_menu_tab = HudMenuWorkshop(self.notebook, self)
        self.target_tab = TargetTab(self.notebook, self)
        self.notebook.insert(1, self.catalog_tab, text="Asset-Katalog")
        self.notebook.insert(2, self.diagnose_tab, text="Diagnose & Reparatur")
        self.notebook.insert(3, self.sandbox_tab, text="Sandkasten")
        self.notebook.insert(4, self.exchange_tab, text="Editor & Austausch")
        self.notebook.insert(5, self.hud_tab, text="SH1 HUD-Studio")
        self.notebook.insert(6, self.origins_graphics_tab, text="ORIGINS Grafiken")
        self.notebook.insert(7, self.hud_menu_tab, text="HUD & Menüs")
        self.notebook.insert(8, self.target_tab, text="Ziele & Mods")
        ttk.Button(
            self.command_bar, text="HUD & Menüs",
            command=lambda: self.open_tab(self.hud_menu_tab)
        ).pack(side="left", padx=(4, 7))
        ttk.Button(
            self.command_bar, text="SH1 HUD",
            command=lambda: self.open_tab(self.hud_tab)
        ).pack(side="left", padx=(0, 5))
        # An unfamiliar user should not have to know the fourteen historic
        # tabs before finding the first useful task. Start with the existing
        # guided home, now promoted to a primary, always-visible workspace.
        self.notebook.insert(0, self.tab_home)
        self._build_quick_navigation()
        self.open_tab(self.tab_home)
        self._command_search = None
        self.bind_all("<Control-k>", self._command_search_shortcut, add="+")
        self.bind_all("<Control-K>", self._command_search_shortcut, add="+")
        self.log("Nachsicht ist Standard: Abweichungen werden gemeldet, nicht blockiert. "
                 "'Streng' oben rechts schaltet um. / Lenient mode is the default: deviations are "
                 "reported, not blocked. 'Strict' at the top right switches.", "muted")
        os.environ["SEDE_SPRACHE"] = LANG.code
        self.after(200, lambda: LANG.apply(self))

    def _build_quick_navigation(self):
        """One accessible route to every major tab, including legacy tabs."""
        self._navigation_entries = (
            ("Einrichten", "Setup", self.setup_page),
            ("Sprites bearbeiten", "Edit sprites", self.tab_art),
            ("Asset-Katalog", "Asset catalogue", self.catalog_tab),
            ("Diagnose & Reparatur", "Diagnosis and repair", self.diagnose_tab),
            ("Sandkasten", "Sandbox Studio", self.sandbox_tab),
            ("Editor & Austausch", "Editor and exchange", self.exchange_tab),
            ("SH1 HUD-Studio", "SH1 HUD Studio", self.hud_tab),
            ("ORIGINS Grafiken", "ORIGINS graphics", self.origins_graphics_tab),
            ("HUD & Menüs", "HUD & menus", self.hud_menu_tab),
            ("Ziele & Mods", "Targets and mods", self.target_tab),
            ("Paket bauen", "Build packages", self.bc7_page),
            ("Start & Anleitung", "Start and guide", self.tab_home),
            ("Sprite-Gruppen", "Sprite groups", self.tab_groups),
            ("Oberfläche", "Interface", self.tab_ui),
            ("Texte", "Texts", self.tab_text),
            ("Bauen und Installieren", "Build and install", self.tab_build),
            ("Alle Werkzeuge", "All tools", self.catalog_page),
        )
        self._primary_tabs = {
            str(tab): names for tab, names in (
                (self.tab_home, ("Start", "Start")),
                (self.setup_page, ("Einrichten", "Setup")),
                (self.tab_art, ("Sprites", "Sprites")),
                (self.catalog_tab, ("Katalog", "Catalogue")),
                (self.diagnose_tab, ("Diagnose", "Diagnosis")),
                (self.sandbox_tab, ("Sandbox", "Sandbox")),
                (self.exchange_tab, ("Editor", "Editor")),
                (self.hud_tab, ("SH1 HUD", "SH1 HUD")),
                (self.hud_menu_tab, ("Menüs", "Menus")),
                (self.origins_graphics_tab, ("Grafiken", "Graphics")),
                (self.target_tab, ("Ziele", "Targets")),
                (self.bc7_page, ("Bauen", "Build")),
            )
        }
        self._compact_tabs = True
        self._strip_refreshing = False
        row = ttk.Frame(self)
        row.pack(before=self.notebook, side="top", fill="x",
                 padx=18, pady=(0, 5))
        ttk.Label(
            row, text="Bereich öffnen / Go to:", style="Muted.TLabel"
        ).pack(side="left", padx=(0, 8))
        self.quick_section = tk.StringVar()
        self.quick_picker = ttk.Combobox(
            row, textvariable=self.quick_section,
            state="readonly", width=28
        )
        self.quick_picker.pack(side="left")
        self.quick_picker.bind(
            "<<ComboboxSelected>>", self._quick_navigation_selected
        )
        self.command_search_button = ttk.Button(
            row, text="Suche (Strg+K)", command=self.show_command_search
        )
        self.command_search_button.pack(side="left", padx=(7, 0))
        self._console_wanted = False
        self.console_toggle = ttk.Button(
            row, text="Protokoll anzeigen", command=self.toggle_console
        )
        self.console_toggle.pack(side="right", padx=(8, 0))
        self.tab_strip_toggle = ttk.Button(
            row, text="Alle Reiter", command=self.toggle_tab_strip
        )
        self.tab_strip_toggle.pack(side="right", padx=(8, 0))
        self._workspace_hint = ttk.Label(
            row, text="Alle Bereiche direkt erreichbar", style="Muted.TLabel"
        )
        self._workspace_hint.pack(side="left", padx=12)
        self.notebook.bind(
            "<<NotebookTabChanged>>",
            self._quick_navigation_sync, add="+"
        )
        self._refresh_quick_navigation()
        self._apply_console_visibility()

    def _command_search_shortcut(self, _event=None):
        self.show_command_search()
        return "break"

    def show_command_search(self):
        """Ctrl+K: safe, bilingual navigation across all Suite workspaces."""
        from suite_command_search import (
            build_navigation_targets, CommandSearchDialog,
        )
        existing = getattr(self, "_command_search", None)
        if existing is not None and existing.winfo_exists():
            existing.set_language(LANG.code)
            existing.lift()
            existing.entry.focus_set()
            return existing
        self._command_search = CommandSearchDialog(
            self, build_navigation_targets(self), language=LANG.code
        )
        return self._command_search

    def _apply_console_visibility(self):
        """Give every workspace the same compact, reversible log panel."""
        panel = self.console.master
        if getattr(self, "_console_wanted", False):
            if panel.winfo_manager() != "pack":
                panel.pack(before=self.notebook, side="bottom", fill="both",
                           padx=14, pady=(0, 8))
        else:
            if panel.winfo_manager() == "pack":
                panel.pack_forget()
        if hasattr(self, "console_toggle"):
            self.console_toggle.configure(
                text=LANG.tr("Protokoll ausblenden" if self._console_wanted
                             else "Protokoll anzeigen")
            )

    def toggle_console(self):
        self._console_wanted = not self._console_wanted
        self._apply_console_visibility()

    def log(self, text: str, tag: str = ""):
        super().log(text, tag)
        # Completed tools and validation errors must remain discoverable
        # even when the user is enjoying the full-height workspace.
        if tag == "bad" and hasattr(self, "console_toggle") and not getattr(
            self, "_console_wanted", True
        ):
            self.console_toggle.configure(
                text=LANG.tr("Protokoll: Fehler anzeigen")
            )

    def toggle_tab_strip(self):
        """Show named main tabs; opt in explicitly to the full legacy tab strip."""
        self._compact_tabs = not self._compact_tabs
        if not self._compact_tabs and not self.advanced.get():
            # The full strip includes advanced and historical pages.
            self.advanced.set(True)
            self.show_advanced()
        self._refresh_tab_strip()

    def _refresh_tab_strip(self):
        if (not hasattr(self, "_navigation_entries")
                or getattr(self, "_strip_refreshing", False)):
            return
        self._strip_refreshing = True
        try:
            selected = self.notebook.select()
            language = 1 if LANG.code == "en" else 0
            extras = set(self.extra_tabs)
            for de, en, tab in self._navigation_entries:
                name = str(tab)
                if self._compact_tabs:
                    show = name in self._primary_tabs or name == selected
                    label = (self._primary_tabs[name][language]
                             if name in self._primary_tabs
                             else (en if language else de))
                else:
                    show = (
                        name in self._primary_tabs or name == selected
                        or name not in extras or bool(self.advanced.get())
                    )
                    label = en if language else de
                self.notebook.tab(tab, state="normal" if show else "hidden")
                self.notebook.tab(tab, text=label)
            self.tab_strip_toggle.configure(
                text=LANG.tr("Alle Reiter" if self._compact_tabs
                             else "Reiter bündeln")
            )
        finally:
            self._strip_refreshing = False

    def open_tab(self, tab):
        if (str(tab) in getattr(self, "extra_tabs", ())
                and str(tab) not in getattr(self, "_primary_tabs", {})
                and not self.advanced.get()):
            self.advanced.set(True)
            self.show_advanced()
        # The quick picker can activate a tab deliberately hidden from the
        # compact strip. Restore it before selecting; never silently refuse.
        self.notebook.tab(tab, state="normal")
        self.notebook.select(tab)
        self._refresh_tab_strip()

    def _refresh_quick_navigation(self):
        position = 1 if LANG.code == "en" else 0
        self._navigation_by_label = {
            row[position]: row[2] for row in self._navigation_entries
        }
        self.quick_picker.configure(
            values=list(self._navigation_by_label)
        )
        self._quick_navigation_sync()

    def _quick_navigation_selected(self, _event=None):
        tab = self._navigation_by_label.get(self.quick_section.get())
        if tab is not None:
            self.open_tab(tab)

    def _quick_navigation_sync(self, _event=None):
        if not hasattr(self, "_navigation_entries"):
            return
        selected = self.notebook.select()
        position = 1 if LANG.code == "en" else 0
        for row in self._navigation_entries:
            if str(row[2]) == selected:
                self.quick_section.set(row[position])
                break
        self._refresh_tab_strip()

    def set_language(self, code: str):
        LANG.code = code if code in ("de", "en") else "de"
        self.language.set(LANG.code.upper())
        LANG.save()
        os.environ["SEDE_SPRACHE"] = LANG.code
        LANG.apply(self)
        self._refresh_quick_navigation()
        finder=getattr(self,"_command_search",None)
        if finder is not None and finder.winfo_exists():
            finder.set_language(LANG.code)
        self.diagnose_tab._refresh_release_approval_label()
        for window in self.winfo_children():
            if isinstance(window, tk.Toplevel):
                LANG.apply(window)
        self.catalog_tab.fill_tree()
        if self.catalog_tab.group:
            self.catalog_tab.open_group(self.catalog_tab.group, self.catalog_tab.selected)
        # StringVar messages are not ttk labels with a static text option.
        # Update the visible target status without losing its selected row.
        selected_targets = tuple(self.target_tab.table.selection())
        self.target_tab.load()
        self.diagnose_tab.refresh_status()
        # The Qt Sandbox is a child HWND, not a Tk widget. Tk's language pass
        # cannot touch it; update the same live Qt application explicitly.
        embedded = getattr(self.sandbox_tab, "bridge", None)
        if embedded is not None and hasattr(embedded.window, "set_ui_language"):
            embedded.window.set_ui_language(LANG.code)
        retained = [name for name in selected_targets
                    if self.target_tab.table.exists(name)]
        if retained:
            self.target_tab.table.selection_set(retained)
        current_message = self.sandbox_tab.message.get()
        reverse = {en:de for de,en in LANG.table.items()}
        german = reverse.get(current_message, current_message)
        if german in LANG.table:
            self.sandbox_tab.message.set(LANG.tr(german))
        self.log("Sprache: Deutsch" if LANG.code == "de" else "Language: English", "muted")

    def _strict_changed(self):
        if self.strict.get():
            os.environ["SEDE_STRENG"] = "1"
            os.environ.pop("SEDE_NACHSICHT", None)
        else:
            os.environ.pop("SEDE_STRENG", None)

    def open_guide(self):
        name = "UNIVERSAL_SUITE_EN.md" if LANG.code == "en" else "UNIVERSAL_SUITE_DE.md"
        path = ROOT / "docs" / name
        if path.is_file():
            os.startfile(path)

    def show_in_catalog(self, group: str, frame: str | None = None):
        self.notebook.select(self.catalog_tab)
        self.catalog_tab.open_group(group, frame)

    def open_sandbox(self, scene_path):
        """Compatibility entry: open the ONE embedded Sandbox, never legacy Tk.

        A provided working test scene is loaded only through Studio's normal
        unsaved-change confirmation and validation. No second SandboxWindow
        may be created from a Suite action.
        """
        self.notebook.select(self.sandbox_tab)
        bridge = self.sandbox_tab.ensure_studio()
        if bridge is None:
            return False
        if scene_path is not None:
            return bool(bridge.window.load_test_scene(Path(scene_path)))
        return True

    def open_sandbox_studio(self):
        """Select, map and initialize the ONE embedded Sandbox predictably.

        Tk maps a newly selected Notebook page on an idle geometry pass.
        Calling ensure_studio immediately after select() can see an unmapped
        host and defer initialization; under load, the first opening was
        sometimes still uninitialized when the desktop checked it.
        """
        self.notebook.select(self.sandbox_tab)
        update_geometry = getattr(self, "update_idletasks", None)
        if callable(update_geometry):
            update_geometry()
        return self.sandbox_tab.ensure_studio()

    def show_in_sandbox(self, group: str, frame: int):
        self.sandbox_tab.select_sprite(group, frame)

    def destroy(self):
        # Studio may have unsaved sprite overlays. Its closeEvent must accept
        # the close before Tk is allowed to destroy the native Qt child HWND.
        tab = getattr(self, "sandbox_tab", None)
        if tab is not None and not tab.close_studio():
            return
        # Six Center readiness variable traces each register a Python method
        # in the Tcl interpreter. Tcl holds a CallWrapper -> bound Universal,
        # so simply destroying widgets leaves the ENTIRE old Tk root alive
        # across repeated sessions (+3 Windows GDI handles per root).
        # Remove registrations only on an accepted close, before Tk shutdown.
        for name in ("bc7_profile", "replace", "unity", "dotnet",
                     "source", "target"):
            value = getattr(self, name, None)
            if not isinstance(value, tk.Variable):
                continue
            try:
                for modes, command in tuple(value.trace_info()):
                    if "write" in modes:
                        value.trace_remove("write", command)
            except tk.TclError:
                pass
        super().destroy()


if __name__ == "__main__":
    Universal().mainloop()

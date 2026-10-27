"""Browsable ORIGINS graphics inventory: original data remain in user's GitLab LFS.

The list includes all 13,562 source-repo files, with categorization of 4,086
HUD/GUI entries. Only explicit SHA-verified working copies are writeable.
"""
from __future__ import annotations

import os
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import webbrowser

from origins_grafikdaten import (
    ROOT, EDIT_WORK, OFFICIAL_URL, PREVIEW_TYPES, GraphicsDataError,
    checked_source_file, load_inventory, source_repo,
)
from suite_usability import run_then_success


CATEGORIES = {
    "Alle Elemente": None,
    "HUD & GUI": "hud-gui",
    "Sprites & Atlanten": "sprites",
    "Konzeptgrafiken": "concepts",
    "Mod-/Baupakete": "packages",
    "Projektmaterial": "local-project",
    "Weitere Dateien": "other",
}
PAGE_SIZE = 300


class OriginsGraphicsTab(ttk.Frame):
    """Processing workbench for the historical Stronghold Origins graphic data."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.source = tk.StringVar(master=self, value="work/stronghold-europe-grafikdaten")
        self.search = tk.StringVar(master=self)
        self.category = tk.StringVar(master=self, value="HUD & GUI")
        self.summary = tk.StringVar(master=self, value="Lese vollständigen Grafikdaten-Katalog ...")
        self.details = tk.StringVar(master=self, value="Element auswählen.")
        self.entries: list[dict] = []
        self.display_rows: list[int] = []
        self.offset = 0
        self._preview_token = 0
        self._messages: queue.Queue = queue.Queue()
        self._build()
        self._load_catalog()
        self.search.trace_add("write", lambda *_: self._filter(reset=True))
        self.category.trace_add("write", lambda *_: self._filter(reset=True))
        self.after(125, self._poll)

    def _build(self):
        header = ttk.Frame(self)
        header.pack(fill="x", padx=10, pady=(8, 4))
        ttk.Label(header, text="ORIGINS · HUD- und GUI-Grafikdaten",
                  style="Title.TLabel").pack(side="left")
        ttk.Label(header, text="13.562 Quelldateien · Git-/LFS-Pins · Spielinstallation bleibt unverändert",
                  style="Muted.TLabel").pack(side="left", padx=15)

        frm = ttk.Frame(self)
        frm.pack(fill="x", padx=10, pady=(2, 5))
        ttk.Label(frm, text="Lokaler GitLab-Klon:", style="Muted.TLabel").pack(side="left")
        ttk.Entry(frm, textvariable=self.source).pack(side="left", fill="x", expand=True, padx=5)
        ttk.Button(frm, text="Klon wählen ...", command=self._pick_source).pack(side="left", padx=2)
        ttk.Button(frm, text="Git-Stand prüfen", command=self.check_source).pack(side="left", padx=2)
        ttk.Button(frm, text="Original-Repository", command=lambda: webbrowser.open(
            OFFICIAL_URL.removesuffix(".git"))).pack(side="left", padx=2)

        actions = ttk.Frame(self)
        actions.pack(fill="x", padx=10, pady=(0, 5))
        ttk.Button(actions, text="Bearbeitungskopie erstellen", command=self.copy_selected).pack(
            side="left", padx=(0, 5))
        ttk.Button(actions, text="Bearbeitungskopien öffnen", command=self.open_work_copies).pack(
            side="left", padx=3)
        ttk.Button(actions, text="SH1 HUD-Studio", command=self.open_hud_studio).pack(
            side="left", padx=3)
        ttk.Button(actions, text="HTML-Sprite-Editor", command=self.open_sprite_editor).pack(
            side="left", padx=3)
        ttk.Label(actions, text="Keine direkten Änderungen am GitLab-/Spiel-Original",
                  style="Muted.TLabel").pack(side="right")

        panes = ttk.PanedWindow(self, orient="horizontal")
        panes.pack(fill="both", expand=True, padx=10)
        left = ttk.Frame(panes)
        right = ttk.Frame(panes)
        panes.add(left, weight=3)
        panes.add(right, weight=2)

        filters = ttk.Frame(left)
        filters.pack(fill="x", pady=(0, 4))
        ttk.Label(filters, text="Suche:").pack(side="left", padx=(0, 4))
        field = ttk.Entry(filters, textvariable=self.search)
        field.pack(side="left", fill="x", expand=True, padx=(0, 8))
        field.bind("<Escape>", lambda _: self.search.set(""))
        ttk.Combobox(filters, state="readonly", width=21,
                     values=list(CATEGORIES), textvariable=self.category
                     ).pack(side="left")

        table_frame = ttk.Frame(left)
        table_frame.pack(fill="both", expand=True)
        self.table = ttk.Treeview(
            table_frame, show="tree headings",
            columns=("kind", "extension"), selectmode="browse")
        self.table.heading("#0", text="Quelldatei / Originalpfad")
        self.table.column("#0", minwidth=230, width=470, stretch=True)
        self.table.heading("kind", text="Kategorie")
        self.table.column("kind", minwidth=100, width=120, stretch=False)
        self.table.heading("extension", text="Format")
        self.table.column("extension", minwidth=60, width=74, stretch=False)
        scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.table.pack(side="left", fill="both", expand=True)
        self.table.bind("<<TreeviewSelect>>", self._selected)
        self.table.bind("<Double-1>", lambda _: self.copy_selected())

        paging = ttk.Frame(left)
        paging.pack(fill="x", pady=(5, 0))
        ttk.Button(paging, text="◀ Zurück", command=self._prev).pack(side="left")
        self.page_text = ttk.Label(paging, text="—", style="Muted.TLabel")
        self.page_text.pack(side="left", expand=True)
        ttk.Button(paging, text="Weiter ▶", command=self._next).pack(side="right")

        ttk.Label(right, text="Vorschau der unveränderten Quelldatei",
                  style="Head.TLabel").pack(anchor="w", pady=(0, 5))
        preview_cls = self.app.tab_ui.preview.__class__
        self.preview = preview_cls(
            right, empty_text="Eine PNG-/JPG-Datei auswählen und lokalen Git-LFS-Klon angeben."
        )
        self.preview.pack(fill="both", expand=True)
        ttk.Label(right, textvariable=self.details, style="Muted.TLabel",
                  wraplength=560, justify="left").pack(fill="x", pady=(4, 0))
        ttk.Label(self, textvariable=self.summary, style="Muted.TLabel",
                  wraplength=1300, justify="left").pack(fill="x", padx=10, pady=(4, 6))

    def _load_catalog(self):
        try:
            from origins_grafikdaten import load_inventory
            manifest = load_inventory()
            self.entries = manifest["entries"]
            self.summary.set(
                f"{manifest['entry_count']:,} Quelldateien aus GitLab-Stand "
                f"{manifest['source_commit'][:12]} · "
                f"{manifest['categories'].get('hud-gui', 0):,} HUD/GUI · "
                "Katalog verfügbar, Originalbilder nur mit vollständigem Git-LFS-Klon."
            )
        except (GraphicsDataError, OSError, ValueError) as exc:
            self.entries = []
            self.summary.set(f"Grafikdaten-Inventar fehlt oder ist ungültig: {exc}")
        self._filter(reset=True)

    def _filter(self, *, reset=False):
        if reset:
            self.offset = 0
        category = CATEGORIES.get(self.category.get())
        needle = self.search.get().strip().casefold()
        self.display_rows = [
            i for i, asset in enumerate(self.entries)
            if (not category or asset["kind"] == category)
            and (not needle or needle in asset["path"].casefold())
        ]
        self._populate()

    def _populate(self):
        self.table.delete(*self.table.get_children())
        if self.offset >= len(self.display_rows):
            self.offset = max(0, len(self.display_rows) - PAGE_SIZE)
        for ix in self.display_rows[self.offset:self.offset + PAGE_SIZE]:
            item = self.entries[ix]
            self.table.insert("", "end", iid=str(ix), text=item["path"],
                              values=(item["kind"], item["format"]))
        count = len(self.display_rows)
        start = self.offset + 1 if count else 0
        end = min(count, self.offset + PAGE_SIZE)
        self.page_text.configure(text=f"{start}–{end} von {count:,} Elementen")
        self.details.set("Auswahl: Originalpfad, Format und Git-ID. Kein automatisches Überschreiben.")
        self.preview.clear("Element wählen · für Bildvorschau LFS-Datei auschecken")

    def _next(self):
        if self.offset + PAGE_SIZE < len(self.display_rows):
            self.offset += PAGE_SIZE
            self._populate()

    def _prev(self):
        if self.offset:
            self.offset = max(0, self.offset - PAGE_SIZE)
            self._populate()

    def selected_item(self) -> dict | None:
        selected = self.table.selection()
        if not selected:
            return None
        index = int(selected[0])
        if index >= len(self.entries):
            return None
        return self.entries[index]

    def _source_folder(self) -> Path:
        value = self.source.get().strip()
        path = Path(value)
        return (path if path.is_absolute() else ROOT / path).resolve()

    def _pick_source(self):
        chosen = filedialog.askdirectory(
            parent=self, title="Vollständigen lokalen GitLab-Grafikdaten-Klon auswählen",
            initialdir=str(ROOT / "work"))
        if chosen:
            self.source.set(chosen)
            self.check_source()

    def check_source(self):
        try:
            source = source_repo(self._source_folder())
        except (GraphicsDataError, OSError) as exc:
            self.summary.set(
                f"Grafikdaten-Klon nicht bereit: {exc}. Für Bildvorschau und "
                "Bearbeitung zuerst den versionierten GitLab-Klon mit Git LFS auschecken."
            )
            return
        self.summary.set(
            f"Original-Klon verifiziert: {source} · Quelle unverändert. "
            "Für fehlende Binärdaten im Klon 'git lfs pull' ausführen."
        )

    def _selected(self, _event=None):
        entry = self.selected_item()
        if entry is None:
            return
        self.details.set(
            f"Original: {entry['path']}\n"
            f"Gruppe: {entry['kind']} · Format: {entry['format'] or 'ohne Endung'}\n"
            f"Git-Blob: {entry['git_blob_sha1'][:20]}… · "
            f"{'LFS-gepinnt' if entry['requires_lfs'] else 'Git-gepinnt'}\n"
            "Bearbeitung nur als eigene Kopie unter work/."
        )
        self._preview_token += 1
        token = self._preview_token
        if ("." + entry["format"]) not in PREVIEW_TYPES:
            self.preview.clear("Vorschau nur für PNG/JPG · andere Formate mit Originalprogramm bearbeiten")
            return
        self.preview.clear("Prüfe Bild und LFS-SHA-256 im Hintergrund ...")
        source = self._source_folder()
        def worker():
            try:
                file = checked_source_file(source, entry)
                self._messages.put((token, file, None))
            except (GraphicsDataError, OSError, RuntimeError) as exc:
                self._messages.put((token, None, str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def _poll(self):
        try:
            while True:
                token, source, error = self._messages.get_nowait()
                if token != self._preview_token:
                    continue
                if source is not None:
                    self.preview.show(source, title=source.name,
                                      detail="SHA-/Git-LFS-geprüfte Originalgrafik (nur Vorschau)")
                else:
                    self.preview.clear(error or "Originalgrafik fehlt")
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(140, self._poll)

    def copy_selected(self):
        item = self.selected_item()
        if item is None:
            messagebox.showinfo("Grafik wählen", "Bitte zuerst ein Element markieren.", parent=self)
            return
        source = self._source_folder()
        if not messagebox.askyesno(
            "Geprüfte Bearbeitungskopie",
            f"Grafik: {item['path']}\n\n"
            "Die Quelle muss vollständig mit Git LFS ausgecheckt sein. "
            "Der SHA-256-/Git-Nachweis wird geprüft; anschließend wird eine "
            "getrennte Datei unter work/origins-grafikdaten-edits erzeugt. "
            "Existierende Bearbeitungen bleiben unangetastet. Fortfahren?",
            parent=self, default="no",
        ):
            return
        args = [str(ROOT / "tools" / "origins_grafikdaten.py"),
                "copy", "--repo", str(source), "--path", item["path"],
                "--out", str(EDIT_WORK)]
        run_then_success(
            self.app, args, "ORIGINS-Grafik verifiziert in Arbeitskopie übernehmen",
            lambda: self.summary.set(
                f"Bild in {EDIT_WORK} verfügbar. "
                "Bearbeite die Arbeitskopie im eigenen Programm oder im HTML-Sprite-Editor."
            ),
            next_step="Original und Arbeitskopie getrennt behalten",
        )

    def open_work_copies(self):
        try:
            EDIT_WORK.mkdir(parents=True, exist_ok=True)
            os.startfile(str(EDIT_WORK))
        except OSError as exc:
            messagebox.showerror("Arbeitskopien", str(exc), parent=self)

    def open_hud_studio(self):
        if hasattr(self.app, "hud_tab"):
            self.app.open_tab(self.app.hud_tab)

    def open_sprite_editor(self):
        self.app.run([str(ROOT / "tools" / "editor_bruecke.py"), "oeffnen"],
                     "HTML-Sprite-Editor öffnen")

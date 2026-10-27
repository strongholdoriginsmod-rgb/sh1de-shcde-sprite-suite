"""Native, guided Stronghold-1 HUD Studio embedded in the Universal Sprite Suite.

The studio reuses the existing UI export index, pixel editor, preview widget,
Suite runner, Origins HTML-Editor and three validated HUD CLI tools. SH1
texture coordinates never masquerade as Crusader/Origins XAML positions.
"""
from __future__ import annotations

import json
import os
import queue
import tempfile
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image

from ui_sh1_hud import ATLAS_NAMES, ROOT, HudError, digest_file
from suite_sh1_hud_core import (
    WORK, compare_legacy, entry_state, load_project, original_crop,
    restore_original, under_work,
)
from suite_usability import CompactActionBar, run_then_success

TOOLS = ROOT / "tools"
ATLAS_PICKER = ("(alle)",) + ATLAS_NAMES


class Sh1HudStudio(ttk.Frame):
    """Connected SH1 HUD editing and Origins compatibility workbench."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.project_var = tk.StringVar(master=self, value="work/sh1-hud-editierbar")
        self.filter_var = tk.StringVar(master=self)
        self.atlas_var = tk.StringVar(master=self, value="(alle)")
        self.changed_only = tk.BooleanVar(master=self, value=False)
        self.message = tk.StringVar(master=self, value="Projekt laden oder das Original-HUD exportieren.")
        self.selection_summary = tk.StringVar(master=self, value="Bild auswählen; Original und Bearbeitung bleiben getrennt.")
        self.entries: list[dict] = []
        self.status_by_key: dict[str, str] = {}
        self._tasks: queue.Queue = queue.Queue()
        self._generation = 0
        self._preview_generation = 0
        self._project_root = None
        self._index: dict[str, dict] = {}
        self._last_selected = None
        self._last_source_file = None
        self._origins_report = None
        self._build()
        self.filter_var.trace_add("write", lambda *_: self._populate())
        self.atlas_var.trace_add("write", lambda *_: self._populate())
        self.changed_only.trace_add("write", lambda *_: self._populate())
        self.after(110, self._poll_tasks)
        if (ROOT / "work" / "sh1-hud-editierbar" / "index.json").is_file():
            self.after(500, self.load)

    def _build(self):
        heading = ttk.Frame(self)
        heading.pack(fill="x", padx=9, pady=(7, 2))
        ttk.Label(heading, text="Stronghold 1 · HUD Studio",
                  style="Title.TLabel").pack(side="left")
        ttk.Label(heading, text="ORIGINS-kompatible Schlüssel · getrennte Originalkoordinaten",
                  style="Muted.TLabel").pack(side="left", padx=16)

        project = ttk.Frame(self)
        project.pack(fill="x", padx=10, pady=(3, 2))
        ttk.Label(project, text="HUD-Projekt:", style="Muted.TLabel").pack(side="left")
        ttk.Entry(project, textvariable=self.project_var).pack(
            side="left", fill="x", expand=True, padx=6)
        ttk.Button(project, text="Laden", command=self.load).pack(side="left", padx=2)
        ttk.Button(project, text="Ordner ...", command=self.pick_project).pack(side="left", padx=2)
        ttk.Button(project, text="Aus Spiel exportieren ...", command=self.export).pack(side="left", padx=2)

        tools = ttk.Frame(self)
        tools.pack(fill="x", padx=10, pady=(2, 1))
        buttons = CompactActionBar(
            tools,
            primary=[
                ("Bild bearbeiten", self.edit),
                ("Original ansehen", self.compare_original),
                ("Original wiederherstellen", self.reset_selected),
            ],
            more=[
                ("PNG extern bearbeiten", self.open_png_external),
                ("HTML-Sprite-Editor", self.open_html_sprite_editor),
                ("Origins-/Crusader-UI vergleichen", self.compare_origins),
                ("Origins-Werkzeuge öffnen", self.open_origins_tools),
                ("Projektordner öffnen", self.open_project_folder),
            ],
            overflow_label="Weitere Bild- und Origins-Werkzeuge ▾",
        )
        buttons.pack(side="left", fill="x", expand=True)
        ttk.Label(tools, text="Änderungen nur in work/", style="Muted.TLabel").pack(side="right")

        pipeline = ttk.Frame(self)
        pipeline.pack(fill="x", padx=10, pady=(1, 4))
        ttk.Button(pipeline, text="1 · Projekt prüfen", command=self.check).pack(side="left", padx=(0, 4))
        ttk.Button(pipeline, text="2 · Atlanten bauen", command=self.build).pack(side="left", padx=4)
        ttk.Button(pipeline, text="3 · Unity-Testkopie", command=self.unity_copy).pack(side="left", padx=4)
        ttk.Button(pipeline, text="Änderungen neu zählen", command=self.scan_changes).pack(side="left", padx=5)
        ttk.Label(pipeline, text="Keine automatische Spielinstallation",
                  style="Muted.TLabel").pack(side="right")

        panes = ttk.PanedWindow(self, orient="horizontal")
        panes.pack(fill="both", expand=True, padx=10, pady=(1, 4))
        left = ttk.Frame(panes)
        right = ttk.Frame(panes)
        panes.add(left, weight=2)
        panes.add(right, weight=3)

        filters = ttk.Frame(left)
        filters.pack(fill="x", pady=(0, 4))
        ttk.Label(filters, text="Suchen:").pack(side="left", padx=(0, 3))
        search = ttk.Entry(filters, textvariable=self.filter_var, width=19)
        search.pack(side="left", fill="x", expand=True, padx=2)
        search.bind("<Escape>", lambda _event: self.filter_var.set(""))
        self.search_field = search

        filters2 = ttk.Frame(left)
        filters2.pack(fill="x", pady=(0, 3))
        ttk.Combobox(filters2, state="readonly", textvariable=self.atlas_var,
                     values=ATLAS_PICKER, width=21).pack(side="left", padx=(0, 6))
        ttk.Checkbutton(filters2, text="Nur bearbeitet",
                        variable=self.changed_only).pack(side="left")

        treeframe = ttk.Frame(left)
        treeframe.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(
            treeframe, columns=("atlas", "shape", "status"),
            show="tree headings", selectmode="browse", height=10)
        self.tree.heading("#0", text="Originalschlüssel")
        self.tree.column("#0", width=185, minwidth=130, stretch=True)
        for column, label, width in (
            ("atlas", "Atlas", 105), ("shape", "Pixel", 72), ("status", "Stand", 77)
        ):
            self.tree.heading(column, text=label)
            self.tree.column(column, width=width, minwidth=53, anchor="w")
        scroll = ttk.Scrollbar(treeframe, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.tag_configure("edited", foreground="#70c59b")
        self.tree.tag_configure("wrong", foreground="#df916f")
        self.tree.bind("<<TreeviewSelect>>", self._selection)
        self.tree.bind("<Double-1>", lambda _event: self.edit())
        self.tree.bind("<Return>", lambda _event: self.edit())

        preview_factory = self.app.tab_ui.preview.__class__
        self.preview_tabs = ttk.Notebook(right)
        self.preview_tabs.pack(fill="both", expand=True)
        edited_frame = ttk.Frame(self.preview_tabs)
        original_frame = ttk.Frame(self.preview_tabs)
        self.preview_tabs.add(edited_frame, text="Arbeitsbild")
        self.preview_tabs.add(original_frame, text="Original (Quelle)")
        self.preview = preview_factory(
            edited_frame, empty_text="Original-HUD laden und einen Ausschnitt wählen")
        self.preview.pack(fill="both", expand=True)
        self.original = preview_factory(
            original_frame, empty_text="Über »Original ansehen« das unveränderte Bild laden")
        self.original.pack(fill="both", expand=True)

        ttk.Label(right, textvariable=self.selection_summary, style="Muted.TLabel",
                  wraplength=620, justify="left").pack(fill="x", pady=(3, 0))
        ttk.Label(self, textvariable=self.message, style="Muted.TLabel",
                  wraplength=970, justify="left").pack(
                      fill="x", padx=11, pady=(0, 4))

    def _project_path(self) -> Path:
        return under_work(self.project_var.get().strip() or "work/sh1-hud-editierbar")

    def pick_project(self):
        selected = filedialog.askdirectory(
            parent=self, title="Sprite-Suite-HUD-Projekt unter work/ auswählen",
            initialdir=str(WORK))
        if selected:
            try:
                root = under_work(selected)
            except (HudError, OSError) as exc:
                messagebox.showerror("Unsicherer Arbeitsordner", str(exc), parent=self)
                return
            self.project_var.set(str(root))
            self.load()

    def load(self):
        try:
            root = self._project_path()
            entries = load_project(root)
        except (HudError, ValueError, OSError, RuntimeError) as exc:
            self.entries = []
            self._project_root = None
            self._index = {}
            self.status_by_key = {}
            self._generation += 1
            self._populate()
            self.preview.clear("HUD-Projekt nicht geladen")
            self.original.clear()
            self.message.set(f"Projekt konnte nicht geladen werden: {exc}")
            return
        self.entries = entries
        self._project_root = root
        self._index = {e["key"]: e for e in entries}
        self.status_by_key = {}
        self._generation += 1
        self._populate()
        self.message.set(
            f"{len(entries)} SH1-Grafiken aus 3 Originalatlanten geladen. "
            "Bilder werden im Hintergrund auf Bearbeitungen geprüft."
        )
        self.scan_changes()

    def scan_changes(self):
        if not self._project_root or not self.entries:
            self.message.set("Zuerst ein gültiges SH1-Projekt laden.")
            return
        self._generation += 1
        token = self._generation
        entries = list(self.entries)
        self.message.set(f"Prüfe Bearbeitungen in {len(entries)} Einzelbildern ...")
        def work():
            statuses = {}
            for index, entry in enumerate(entries):
                try:
                    statuses[entry["key"]] = entry_state(entry)
                except (OSError, ValueError, RuntimeError) as exc:
                    statuses[entry["key"]] = "Fehler"
                if (index + 1) % 280 == 0:
                    self._tasks.put(("progress", token, index + 1))
            self._tasks.put(("scan", token, statuses))
        threading.Thread(target=work, daemon=True).start()

    def _poll_tasks(self):
        try:
            while True:
                result = self._tasks.get_nowait()
                kind, token, payload = result
                if kind == "scan" and token == self._generation:
                    self.status_by_key = payload
                    count = sum(state == "Geändert" for state in payload.values())
                    bad = sum(state in ("Fehler", "Fehlt", "Größe falsch") for state in payload.values())
                    self.message.set(
                        f"{len(self.entries)} Bilder · {count} bearbeitet · "
                        f"{bad} fehlerhaft. "
                        "Prüfen und Bauen verwenden die bestehende XAML-/SHA-Pipeline."
                    )
                    self._populate()
                elif kind == "progress" and token == self._generation:
                    self.message.set(f"Suche bearbeitete PNGs: {payload} von {len(self.entries)} ...")
                elif kind == "original" and token == self._preview_generation:
                    self.original.show(payload, title="Unveränderte SH1-Bildbasis",
                                       detail="Nur Vorschau; vollständige Herkunftsprüfung über Projekt prüfen")
                    self.preview_tabs.select(1)
                elif kind == "error" and token == self._preview_generation:
                    self.original.clear("Originalvergleich fehlgeschlagen")
                    self.message.set(f"Originalvergleich fehlgeschlagen: {payload}")
                elif kind == "reset" and token == self._preview_generation:
                    self.message.set(f"Ursprungsbild wiederhergestellt. Sicherung: {payload}")
                    self._show_current_preview()
                    self.scan_changes()
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(100, self._poll_tasks)

    def _populate(self):
        if not hasattr(self, "tree"):
            return
        oldkey = self._last_selected
        self.tree.delete(*self.tree.get_children())
        term = self.filter_var.get().strip().casefold()
        atlas = self.atlas_var.get()
        edited_only = self.changed_only.get()
        first = None
        target = None
        row_number = 0
        for entry in self.entries:
            key = entry["key"]
            if atlas != "(alle)" and entry["atlas"] != atlas:
                continue
            if term and term not in (key + " " + entry["atlas"]).casefold():
                continue
            state = self.status_by_key.get(key, "—")
            if edited_only and state != "Geändert":
                continue
            iid = str(row_number)
            row_number += 1
            # Distinct iids are stored by row sequence; lookup by the key.
            self.tree.insert("", "end", iid=iid, text=key,
                             values=(entry["atlas"],
                                     f"{entry['width']}×{entry['height']}", state),
                             tags=("edited",) if state == "Geändert"
                             else ("wrong",) if state in ("Fehlt", "Fehler", "Größe falsch")
                             else ())
            if first is None:
                first = iid
            if key == oldkey:
                target = iid
        if target is not None or first is not None:
            self.tree.selection_set(target or first)
            self.tree.focus(target or first)
            self._selection()
        else:
            self._last_selected = None
            self.selection_summary.set("Keine Treffer. Filter oder Atlaswahl anpassen.")
            self.preview.clear("Keine ausgewählte HUD-Grafik")

    def selected_entry(self) -> dict | None:
        selection = self.tree.selection()
        if not selection:
            return None
        key = self.tree.item(selection[0], "text")
        return self._index.get(key)

    def _selection(self, _event=None):
        entry = self.selected_entry()
        if entry is None:
            return
        if entry["key"] != self._last_selected:
            self.original.clear("Originalvergleich über »Original ansehen« laden")
            self._preview_generation += 1
        self._last_selected = entry["key"]
        self._show_current_preview()

    def _show_current_preview(self):
        entry = self.selected_entry()
        if entry is None:
            return
        key = entry["key"]
        self.selection_summary.set(
            f"{key} · {entry['atlas']} · ({entry['x']}, {entry['y']}) · "
            f"{entry['width']}×{entry['height']} Pixel · "
            f"Status: {self.status_by_key.get(key, 'noch nicht geprüft')}"
        )
        self.preview.show(
            Path(entry["path"]), title=key,
            detail=f"Arbeitskopie • {entry['file']} • Doppelklick zum Bearbeiten",
        )

    def _need_entry(self) -> dict | None:
        entry = self.selected_entry()
        if entry is None or self._project_root is None:
            messagebox.showinfo("HUD-Bild auswählen", "HUD-Projekt laden und Bild auswählen.", parent=self)
        return entry

    def edit(self):
        entry = self._need_entry()
        if entry is None:
            return
        try:
            from suite_sh1_hud_editor import Sh1HudPixelEditor
            editor = Sh1HudPixelEditor(
                self, Path(entry["path"]), workspace=self._project_root,
                after_save=self._on_saved,
            )
            editor.focus_set()
        except (OSError, ValueError, HudError) as exc:
            messagebox.showerror("HUD-Editor", str(exc), parent=self)

    def _on_saved(self):
        self._show_current_preview()
        self.scan_changes()
        self.message.set("Bild gespeichert. Vor der Atlas-Ausgabe »Projekt prüfen« ausführen.")

    def compare_original(self):
        entry = self._need_entry()
        if entry is None:
            return
        self._preview_generation += 1
        token = self._preview_generation
        workspace = self._project_root
        self.message.set(f"Lese Originalausschnitt {entry['key']} aus dem Quellatlas ...")
        def work():
            try:
                base = original_crop(workspace, entry)
                # The existing Suite ImagePreview reads paths. Store a
                # derived comparison thumbnail only under gitignored work/.
                folder = under_work(WORK / "sh1-hud-vergleich")
                folder.mkdir(parents=True, exist_ok=True)
                import hashlib
                identity = hashlib.sha256(
                    f"{workspace}/{entry['atlas']}/{entry['key']}/{entry['baseline_pixels_sha256']}".encode()
                ).hexdigest()[:24]
                path = folder / f"{identity}.png"
                if path.is_file():
                    # An old cached preview is never trusted as original.
                    try:
                        with Image.open(path) as cached:
                            from ui_sh1_hud import pixel_digest
                            valid = pixel_digest(cached) == entry["baseline_pixels_sha256"]
                    except (OSError, ValueError):
                        valid = False
                    if not valid:
                        path.unlink()
                if not path.is_file():
                    fd, name = tempfile.mkstemp(dir=folder, prefix=".hud-preview-", suffix=".png")
                    os.close(fd)
                    temporary = Path(name)
                    try:
                        base.save(temporary, "PNG")
                        os.replace(temporary, path)
                    finally:
                        temporary.unlink(missing_ok=True)
                self._tasks.put(("original", token, path))
            except (OSError, ValueError, HudError, RuntimeError) as exc:
                self._tasks.put(("error", token, str(exc)))
        threading.Thread(target=work, daemon=True).start()

    def reset_selected(self):
        entry = self._need_entry()
        if entry is None:
            return
        if not messagebox.askyesno(
            "Bearbeitung rückgängig machen",
            f"{entry['key']} auf den Originalzustand aus dem Spiel zurücksetzen?\n\n"
            "Die aktuelle Bearbeitung wird vorher in work/sh1-hud-ruecksetzen gesichert. "
            "Es werden keine Spielressourcen verändert.",
            parent=self, default="no",
        ):
            return
        workspace = self._project_root
        try:
            digest = digest_file(Path(entry["path"]))
        except OSError as exc:
            messagebox.showerror("Bild fehlt", str(exc), parent=self)
            return
        self._preview_generation += 1
        token = self._preview_generation
        self.message.set("Original wird geprüft, aktuelle Fassung gesichert und wiederhergestellt ...")
        def work():
            try:
                saved = restore_original(workspace, entry, expected_disk_hash=digest)
                self._tasks.put(("reset", token, str(saved)))
            except (OSError, ValueError, HudError) as exc:
                self._tasks.put(("error", token, str(exc)))
        threading.Thread(target=work, daemon=True).start()

    def open_png_external(self):
        entry = self._need_entry()
        if entry is None:
            return
        try:
            os.startfile(str(Path(entry["path"])))
            self.message.set("Externes PNG geöffnet. Danach »Änderungen neu zählen« verwenden.")
        except OSError as exc:
            messagebox.showerror("Datei öffnen", str(exc), parent=self)

    def open_html_sprite_editor(self):
        self.app.run(
            [str(TOOLS / "editor_bruecke.py"), "oeffnen"],
            "Original Stronghold Sprite Editor öffnen",
        )
        self.message.set(
            "Im HTML-Editor ein HUD-PNG über »Importieren« öffnen. "
            "Das fertige Einzel-PNG mit identischer Größe anschließend "
            "in unseren HUD-Pixeleditor über »PNG einsetzen ...« übernehmen."
        )

    def open_origins_tools(self):
        tab = getattr(self.app, "exchange_tab", getattr(self.app, "tab_ui", None))
        if tab is not None:
            self.app.open_tab(tab)

    def compare_origins(self):
        if not self._project_root:
            messagebox.showinfo("Origins-Vergleich", "Zuerst das SH1-HUD laden.", parent=self)
            return
        folder = filedialog.askdirectory(
            parent=self, title="Früheren ORIGINS-/Crusader-UI-Export auswählen",
            initialdir=str(WORK),
        )
        if not folder:
            return
        try:
            info = compare_legacy(self._project_root, folder)
        except (OSError, ValueError, HudError, RuntimeError) as exc:
            messagebox.showerror("Origins-Vergleich", str(exc), parent=self)
            return
        self._origins_report = info
        messagebox.showinfo(
            "Original ORIGINS ↔ SH1-HUD",
            f"SH1-Original: {info['sh1_count']} Schlüssel\n"
            f"Früherer ORIGINS-/Crusader-Export: {info['origins_count']} Schlüssel\n\n"
            f"Gemeinsame Schlüssel: {info['same_key_count']}\n"
            f"Davon gleich groß: {info['same_dimensions_count']}\n"
            f"Andere Größen (manuell prüfen): {info['different_dimensions_count']}\n"
            f"Nur in SH1: {info['only_sh1_count']}\n"
            f"Nur im Altprojekt: {info['only_origins_count']}\n\n"
            "Der Vergleich ist NUR LESEND. Atlaspositionen, Spiele-IDs und "
            "Modpaketdateien werden niemals blind übernommen.",
            parent=self,
        )
        self.message.set(
            f"ORIGINS-Abgleich: {info['same_key_count']} gemeinsame Schlüssel. "
            "Größenänderungen und andere Packpositionen nicht automatisch zuweisen."
        )

    def open_project_folder(self):
        if not self._project_root:
            return
        try:
            os.startfile(str(self._project_root))
        except OSError as exc:
            messagebox.showerror("Ordner öffnen", str(exc), parent=self)

    def export(self):
        source = filedialog.askopenfilename(
            parent=self, title="Stronghold 1: globalgamemanagers.assets auswählen",
            initialdir=str(WORK),
            filetypes=[("Unity-Assetdatei", "*.assets"), ("Alle Dateien", "*.*")],
        )
        if not source:
            return
        if Path(source).name != "globalgamemanagers.assets":
            messagebox.showwarning("Nicht die Spielquelle",
                                   "Bitte nur globalgamemanagers.assets wählen.", parent=self)
            return
        try:
            root = self._project_path()
        except (HudError, OSError) as exc:
            messagebox.showerror("HUD-Ausgabepfad", str(exc), parent=self)
            return
        overwrite = root.is_dir() and any(root.iterdir())
        if overwrite and not messagebox.askyesno(
            "Original-HUD erneut exportieren",
            "Das vorhandene editierbare HUD-Projekt kann bereits bearbeitete "
            "Bilder enthalten. Diese würden durch Originale ersetzt. "
            "Wirklich überschreiben? Sicherungen vorher anlegen.",
            parent=self, default="no", icon="warning",
        ):
            return
        args = [str(TOOLS / "ui_sh1_hud.py"), "export",
                "--source", source, "--out", str(root)]
        if overwrite:
            args.append("--replace")
        run_then_success(
            self.app, args, "SH1: Original-HUD exportieren", self.load,
            next_step="erst nach erfolgreichem Export das HUD-Projekt laden",
        )

    def _check_before_action(self) -> Path | None:
        if not self._project_root or not self.entries:
            messagebox.showwarning("HUD-Projekt laden",
                                   "Ein geprüfter SH1-HUD-Export fehlt.", parent=self)
            return None
        return self._project_root

    def check(self):
        work = self._check_before_action()
        if work is None:
            return
        run_then_success(
            self.app,
            [str(TOOLS / "ui_sh1_hud.py"), "check", "--from", str(work)],
            "SH1 HUD vollständig prüfen",
            lambda: self.message.set(
                "HUD-Projekt bestätigt: XAML, Quell-PNGs, alle 1.391 Einzelbilder geprüft."),
            next_step="HUD-Prüfstatus aktualisieren",
        )

    def build(self):
        work = self._check_before_action()
        if work is None:
            return
        destination = ROOT / "dist" / "sh1-hud-editierte-atlanten"
        overwrite = destination.is_dir() and any(destination.iterdir())
        if not messagebox.askyesno(
            "SH1-HUD-Atlanten zusammensetzen",
            f"{len(self.entries)} Bilder aus {work} gegen die originalen "
            "XAML-Rechtecke prüfen und drei Atlas-PNGs ausschließlich unter "
            f"{destination} erzeugen? Keine Spielinstallation.",
            parent=self, default="no",
        ):
            return
        if overwrite and not messagebox.askyesno(
            "Frühere SH1-Atlas-Ausgabe ersetzen",
            f"Die frühere Ausgabe unter {destination} wird ersetzt. "
            "Eigene Ergebnisse vorher sichern. Fortfahren?",
            parent=self, default="no", icon="warning",
        ):
            return
        args = [str(TOOLS / "ui_sh1_hud.py"), "build",
                "--from", str(work), "--out", str(destination)]
        if overwrite:
            args.append("--replace")
        run_then_success(
            self.app, args, "SH1 geprüfte Atlanten bauen",
            lambda: self.message.set(
                f"Atlas-Ausgabe geprüft unter {destination}; keine installierte Datei verändert."),
            next_step="SH1-Ausgabestatus aktualisieren",
        )

    def unity_copy(self):
        work = self._check_before_action()
        if work is None:
            return
        source = filedialog.askopenfilename(
            parent=self,
            title="Quelle: originale globalgamemanagers.assets aus eigener SH1DE-Installation",
            initialdir=str(WORK),
            filetypes=[("Unity Asset", "*.assets"), ("Alle Dateien", "*.*")],
        )
        if not source:
            return
        if Path(source).name != "globalgamemanagers.assets":
            messagebox.showwarning("Unpassende Datei",
                                   "Nur globalgamemanagers.assets zulässig.", parent=self)
            return
        target = ROOT / "dist" / "sh1-hud-unity-kandidat"
        overwrite = target.is_dir() and any(target.iterdir())
        if not messagebox.askyesno(
            "Isolierte Unity-Datei erstellen",
            "Die GUI benutzt den bestehenden SHA-geprüften Offline-Patcher. "
            "Er patcht keine Installation und startet kein Spiel.\n\n"
            f"Original: {source}\nProjekt: {work}\nAusgabe: {target}\n\nFortfahren?",
            parent=self, default="no",
        ):
            return
        if overwrite and not messagebox.askyesno(
            "Unity-Kandidaten ersetzen",
            "Der bestehende isolierte Unity-Kandidat wird ersetzt. "
            "Originalinstallation und deren Dateien bleiben unangetastet.",
            parent=self, default="no", icon="warning",
        ):
            return
        args = [str(TOOLS / "ui_sh1_unity_patch.py"),
                "--source", source, "--from", str(work), "--out", str(target)]
        if overwrite:
            args.append("--replace")
        run_then_success(
            self.app, args, "SH1 Unity-HUD-Kandidat erzeugen",
            lambda: self.message.set(
                f"Offline-Unity-Kandidat bereit: {target}. Noch kein Ingame-Test."),
            next_step="Unity-Kandidatenstatus aktualisieren",
        )

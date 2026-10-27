"""Stand-alone Tk front end for creating ADDITIONAL SHCDE Noesis UI atlases.

This form never edits installed games. The core enforces work/ input and
dist/ output containment and validates original XAML, pixels and manifests.
"""
from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from ui_extra_atlas import (
    ROOT, _read_only_gui, _references, _collect_assets, _layout,
    build, verify, _in_project, _identifier, ExtraAtlasError, SHEET_SIZES,
)


class ExtraUiAtlasWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Sprite Suite – Neue SHCDE-UI-Atlasblätter")
        self.geometry("960x620")
        self.minsize(790, 520)
        self._messages: queue.Queue = queue.Queue()
        self._busy = False
        self._generation = 0
        self.vars = {
            "source": tk.StringVar(master=self, value="work/neue-ui-assets"),
            "gui": tk.StringVar(master=self),
            "game": tk.StringVar(master=self),
            "output": tk.StringVar(master=self, value="dist/shcde-neue-ui-atlanten"),
            "stem": tk.StringVar(master=self, value="SpriteSuiteExtra"),
            "prefix": tk.StringVar(master=self, value="Extra"),
            "size": tk.StringVar(master=self, value="1024"),
            "gutter": tk.StringVar(master=self, value="2"),
            "max_pages": tk.StringVar(master=self, value="16"),
        }
        self.status = tk.StringVar(master=self, value="PNG-Eingaben auswählen; kein automatischer Spiel-Einbau.")
        self._controls = []
        self._layout()
        self.after(100, self._poll)

    def _row(self, frame, row, label, key, browse=None):
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=5)
        entry = ttk.Entry(frame, textvariable=self.vars[key])
        entry.grid(row=row, column=1, sticky="ew", pady=5)
        if browse is not None:
            button = ttk.Button(frame, text="…", width=4,
                                command=lambda: self._choose(key, browse))
            button.grid(row=row, column=2, padx=(6, 0))
            self._controls.append(button)
        self._controls.append(entry)

    def _choose(self, key, directory):
        if directory:
            chosen = filedialog.askdirectory(parent=self, initialdir=str(ROOT),
                                            title="Verzeichnis auswählen")
        else:
            chosen = filedialog.askopenfilename(
                parent=self,
                filetypes=[("Unity-Assetdatei", "*.assets"), ("Alle Dateien", "*.*")],
                title="Optional: Original SHCDE globalgamemanagers.assets")
        if chosen:
            self.vars[key].set(chosen)

    def _layout(self):
        outer = ttk.Frame(self, padding=14)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="Zusätzliche Noesis-UI-Atlasblätter",
                  font=("Segoe UI", 15, "bold")).pack(anchor="w")
        ttk.Label(outer, wraplength=890, text=(
            "Neue Bildressourcen ergänzen, ohne bestehende SHCDE-Atlanten zu ersetzen. "
            "Der Builder erzeugt PNG-Atlanten, XAML-Dictionaries, "
            "ApplicationResources-Verweise und SHA-256-Prüfmanifest unter dist/. "
            "Neue Bilder erscheinen erst nach separater UI-/Spielintegration."
        )).pack(anchor="w", pady=(5, 12))
        group = ttk.LabelFrame(outer, text="Quellen und Ziel", padding=10)
        group.pack(fill="x")
        group.columnconfigure(1, weight=1)
        self._row(group, 0, "Eigene PNGs unter work/", "source", browse=True)
        self._row(group, 1, "SHCDE-Referenz: .../Assets/GUI", "gui", browse=True)
        self._row(group, 2, "Passende Unity-Quelldatei (optional)", "game", browse=False)
        self._row(group, 3, "Neues Paket unter dist/", "output", browse=True)
        options = ttk.Frame(outer)
        options.pack(fill="x", pady=(10, 4))
        for title, key, width in (
            ("Atlasname", "stem", 19),
            ("Neuer Schlüsselnamensraum", "prefix", 18),
            ("Blattgröße", "size", 8),
            ("Pixelabstand", "gutter", 7),
            ("Max. Seiten", "max_pages", 7),
        ):
            field = ttk.Frame(options)
            field.pack(side="left", padx=(0, 10))
            ttk.Label(field, text=title).pack(anchor="w")
            if key == "size":
                combo = ttk.Combobox(field, textvariable=self.vars[key], width=width,
                                     state="readonly", values=[str(x) for x in SHEET_SIZES])
                combo.pack(anchor="w")
                self._controls.append(combo)
            else:
                entry = ttk.Entry(field, textvariable=self.vars[key], width=width)
                entry.pack(anchor="w")
                self._controls.append(entry)
        buttons = ttk.Frame(outer)
        buttons.pack(fill="x", pady=(11, 7))
        for label, action in (
            ("1. Planung prüfen", self.preview),
            ("2. Neue Atlanten bauen", self.create),
            ("3. Paket erneut prüfen", self.check),
            ("Ausgabeordner öffnen", self.open_output),
        ):
            button = ttk.Button(buttons, text=label, command=action)
            button.pack(side="left", padx=(0, 8))
            self._controls.append(button)
        ttk.Label(outer, textvariable=self.status, wraplength=890).pack(anchor="w", pady=5)
        self.log = tk.Text(outer, height=10, wrap="word", state="disabled")
        self.log.pack(fill="both", expand=True, pady=(5, 0))

    def _log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", str(text) + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _settings(self):
        # Parse before starting any worker; no writes can occur here.
        return {
            "source": self.vars["source"].get().strip(),
            "gui": self.vars["gui"].get().strip(),
            "game": self.vars["game"].get().strip() or None,
            "output": self.vars["output"].get().strip(),
            "stem": self.vars["stem"].get().strip(),
            "prefix": self.vars["prefix"].get().strip(),
            "size": int(self.vars["size"].get()),
            "gutter": int(self.vars["gutter"].get()),
            "max_pages": int(self.vars["max_pages"].get()),
        }

    def _run(self, label, worker):
        if self._busy:
            return
        self._busy = True
        self._generation += 1
        generation = self._generation
        self.status.set(label + " läuft ...")
        for control in self._controls:
            control.configure(state="disabled")
        def thread():
            try:
                data = worker()
                self._messages.put((generation, True, data))
            except Exception as exc:
                self._messages.put((generation, False, str(exc)))
        threading.Thread(target=thread, daemon=True).start()

    def preview(self):
        try:
            args = self._settings()
        except ValueError as exc:
            messagebox.showerror("Ungültige Eingabe", str(exc), parent=self)
            return
        def work():
            _identifier(args["stem"], "Atlas-Grundname")
            _identifier(args["prefix"], "Namensraum")
            gui = _read_only_gui(Path(args["gui"]))
            keys, _, _ = _references(gui)
            source = _in_project(args["source"], "work", existing=True)
            assets = _collect_assets(source, args["prefix"], keys)
            pages = _layout(assets, args["stem"], args["size"],
                            args["gutter"], args["max_pages"])
            return f"{len(assets)} PNGs für {len(pages)} zusätzliche Atlanten geeignet. Noch nichts geschrieben."
        self._run("Quellenprüfung", work)

    def create(self):
        try:
            args = self._settings()
            dest = _in_project(args["output"], "dist", existing=False)
        except (ValueError, OSError, ExtraAtlasError) as exc:
            messagebox.showerror("Ungültige Eingabe", str(exc), parent=self)
            return
        replace = dest.exists()
        if not messagebox.askyesno(
            "Zusätzliches UI-Paket erzeugen",
            f"{'Vorhandenes Paket ERSETZEN' if replace else 'Neues Paket erstellen'}:\n"
            f"{dest}\n\nBestehende Spielinstallationen werden NICHT verändert.\n"
            "Für sichtbare neue HUD-Funktionen ist weitere Noesis-Integration nötig. Fortfahren?",
            parent=self, default="no", icon="warning" if replace else "question",
        ):
            return
        def work():
            manifest = build(args["source"], args["gui"], args["output"],
                             stem=args["stem"], prefix=args["prefix"],
                             size=args["size"], gutter=args["gutter"],
                             max_pages=args["max_pages"], replace=replace,
                             target_game=args["game"])
            checked = verify(args["output"])
            return (f"{manifest['source_images_count']} neue UI-Bilder auf "
                    f"{len(manifest['pages'])} Atlasblättern – SHA-/XAML-Prüfung erfolgreich. "
                    f"Native Unity-Prüfung: {checked['native_shcde_source_pinned']}")
        self._run("Atlas-Erstellung", work)

    def check(self):
        try:
            args = self._settings()
        except ValueError as exc:
            messagebox.showerror("Ungültige Eingabe", str(exc), parent=self)
            return
        def work():
            report = verify(args["output"])
            return (f"{report['pages_verified']} Atlasblätter und "
                    f"{report['images_verified']} Bilder geprüft. "
                    "Keine Ingame-Freigabe.")
        self._run("Paketprüfung", work)

    def open_output(self):
        try:
            folder = _in_project(self.vars["output"].get(), "dist", existing=True)
            os.startfile(str(folder))
        except (OSError, ExtraAtlasError) as exc:
            messagebox.showerror("Ausgabeordner", str(exc), parent=self)

    def _poll(self):
        try:
            while True:
                generation, okay, text = self._messages.get_nowait()
                if generation != self._generation:
                    continue
                self._busy = False
                for control in self._controls:
                    # Restore combobox readonly and normal widgets appropriately.
                    control.configure(state="readonly" if isinstance(control, ttk.Combobox) else "normal")
                self._log(("OK: " if okay else "ABGELEHNT: ") + text)
                self.status.set(text)
                if not okay:
                    messagebox.showerror("Atlas-Arbeit abgelehnt", text, parent=self)
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(100, self._poll)


if __name__ == "__main__":
    ExtraUiAtlasWindow().mainloop()

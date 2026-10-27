"""Guided SH1 -> SHCDE Noesis crop bridge (never touches installed games).

Each mapping needs human functional approval. The actual native transfer
revalidates game hashes, SH1 Noesis XML and SHCDE coordinates/pixel sources.
The resulting ordinary Crusader export remains editable in the Suite UiTab.
"""
from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from ui_sh1_to_shcde_bridge import (
    ROOT, BridgeError, _read_json, _save_plan, _validate_plan, approve_mapping,
    apply_plan, create_plan, revoke_mapping, under_work, verify_candidate,
)


class CrossGameHudBridge(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Sprite Suite – SH1-HUD in Crusader DE übertragen")
        self.geometry("1220x820")
        self.minsize(980, 700)
        self.vars = {
            "sh1": tk.StringVar(master=self, value="work/sh1-hud-editierbar"),
            "shcde": tk.StringVar(master=self, value="work/ui"),
            "plan": tk.StringVar(master=self, value="work/sh1-zu-shcde-plan.json"),
            "output": tk.StringVar(master=self, value="work/sh1-zu-shcde-editierbar"),
            "source_game": tk.StringVar(master=self),
            "target_game": tk.StringVar(master=self),
            "target_xaml": tk.StringVar(master=self),
            "filter": tk.StringVar(master=self),
            "state_note": tk.StringVar(master=self),
            "fit": tk.StringVar(master=self, value="exact"),
        }
        self._controls = []
        self._queue: queue.Queue = queue.Queue()
        self._generation = 0
        self._busy = False
        self._mapping: list[dict] = []
        self._images = []
        self.status = tk.StringVar(master=self, value=(
            "Erst den nativen SH1- und SHCDE-Export prüfen; keine automatische Freigabe."
        ))
        self._build()
        self.vars["filter"].trace_add("write", lambda *_: self._fill())
        self.after(100, self._poll)

    def _field(self, parent, row, title, name, choose=None):
        ttk.Label(parent, text=title).grid(row=row, column=0, sticky="w", padx=4, pady=3)
        entry = ttk.Entry(parent, textvariable=self.vars[name])
        entry.grid(row=row, column=1, sticky="ew", padx=4, pady=3)
        self._controls.append(entry)
        if choose is not None:
            button = ttk.Button(parent, text="…", width=3, command=lambda: self._pick(name, choose))
            button.grid(row=row, column=2, padx=4)
            self._controls.append(button)

    def _pick(self, name, what):
        if what == "folder":
            value = filedialog.askdirectory(parent=self, initialdir=str(ROOT),
                                            title="Quelldatenordner wählen")
        elif what == "file":
            value = filedialog.askopenfilename(
                parent=self, initialdir=str(ROOT),
                filetypes=[("Assetdatei", "*.assets"), ("Alle Dateien", "*.*")],
                title="Native Unity-Quelldatei wählen")
        else:
            value = filedialog.asksaveasfilename(
                parent=self, initialdir=str(ROOT / "work"),
                defaultextension=".json", filetypes=[("JSON", "*.json")],
                title="Neuen Mappingplan unter work/ speichern")
        if value:
            self.vars[name].set(value)

    def _build(self):
        shell = ttk.Frame(self, padding=10)
        shell.pack(fill="both", expand=True)
        ttk.Label(shell, text="Stronghold 1 HUD → Crusader DE",
                  font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(shell, wraplength=1160, text=(
            "Quellen aus beiden Spielen getrennt halten. Nur manuell bestätigte "
            "SH1-Grafiken auf geprüfte Crusader-Slots übertragen; die resultierenden "
            "Crusader-PNGs können später im bestehenden UI-Editor bearbeitet werden. "
            "Keine neue HUD-Zustandslogik, keine Spielinstallation."
        )).pack(anchor="w", pady=(5, 8))
        fields = ttk.LabelFrame(shell, text="Arbeitsstände und native Nachweise", padding=6)
        fields.pack(fill="x")
        fields.columnconfigure(1, weight=1)
        for i, (label, key, kind) in enumerate((
            ("SH1-HUD-Arbeitsprojekt", "sh1", "folder"),
            ("Crusader-UI-Zielexport", "shcde", "folder"),
            ("Neuer Mapping-Plan", "plan", "save"),
            ("Neuer SHCDE-Kandidat", "output", "folder"),
            ("Original-SH1: globalgamemanagers.assets", "source_game", "file"),
            ("Original-Crusader: globalgamemanagers.assets", "target_game", "file"),
            ("Crusader Original Noesis-Ordner .../GUI/Sprites", "target_xaml", "folder"),
        )):
            self._field(fields, i, label, key, kind)
        actions = ttk.Frame(shell)
        actions.pack(fill="x", pady=(6, 4))
        for label, cb in (
            ("1. Mapping vorschlagen", self.create_plan),
            ("Plan öffnen/neu lesen", self.open_plan),
            ("Freigabe widerrufen", self.revoke),
            ("3. Native Kandidatenübertragung", self.apply),
            ("SHCDE-Arbeitsstand prüfen", self.verify),
            ("Ordner im Explorer", self.open_folder),
        ):
            b = ttk.Button(actions, text=label, command=cb)
            b.pack(side="left", padx=3)
            self._controls.append(b)
        body = ttk.PanedWindow(shell, orient="horizontal")
        body.pack(fill="both", expand=True)
        listing = ttk.Frame(body)
        detail = ttk.Frame(body)
        body.add(listing, weight=3)
        body.add(detail, weight=4)
        ttk.Entry(listing, textvariable=self.vars["filter"]).pack(fill="x", pady=(0, 3))
        self.tree = ttk.Treeview(listing, show="headings", selectmode="browse",
                                 columns=("key", "sh1", "crusader", "status"), height=9)
        for key, title, width in (
            ("key", "Schlüssel", 190), ("sh1", "SH1-Maß", 65),
            ("crusader", "SHCDE-Maß", 75), ("status", "Freigabe", 66),
        ):
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, minwidth=60)
        scrollbar = ttk.Scrollbar(listing, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._selected)
        pv = ttk.Frame(detail)
        pv.pack(fill="both", expand=True)
        self.before_label = ttk.Label(pv, text="SH1-Grafik wählen", anchor="center")
        self.after_label = ttk.Label(pv, text="Crusader-Zielgrafik", anchor="center")
        self.before_label.pack(side="left", fill="both", expand=True, padx=5)
        self.after_label.pack(side="left", fill="both", expand=True, padx=5)
        review = ttk.LabelFrame(detail, text="2. Visuelle und fachliche Freigabe", padding=8)
        review.pack(fill="x", pady=6)
        ttk.Label(review, text="Maßregel:").grid(row=0, column=0)
        combo = ttk.Combobox(
            review, textvariable=self.vars["fit"], state="readonly",
            values=("exact", "contain", "stretch"), width=10)
        combo.grid(row=0, column=1, sticky="w")
        self._controls.append(combo)
        ttk.Label(review, text="Funktions-/Spielzustand manuell begründen:").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(6, 1))
        note = ttk.Entry(review, textvariable=self.vars["state_note"], width=52)
        note.grid(row=2, column=0, columnspan=2, sticky="ew")
        review.columnconfigure(1, weight=1)
        self._controls.append(note)
        button = ttk.Button(review, text="Element ausdrücklich freigeben",
                            command=self.approve)
        button.grid(row=3, column=0, columnspan=2, sticky="ew", pady=6)
        self._controls.append(button)
        ttk.Label(shell, textvariable=self.status, wraplength=1120).pack(
            fill="x", pady=(6, 0))

    def _work(self, label, worker, on_success=None):
        if self._busy:
            return
        self._busy = True
        self._generation += 1
        generation = self._generation
        self.status.set(label + " läuft ...")
        for b in self._controls:
            b.configure(state="disabled")
        def run():
            try:
                result = worker()
                self._queue.put((generation, True, result, on_success))
            except Exception as exc:
                self._queue.put((generation, False, str(exc), None))
        threading.Thread(target=run, daemon=True).start()

    def _poll(self):
        try:
            while True:
                generation, okay, result, callback = self._queue.get_nowait()
                if generation != self._generation:
                    continue
                self._busy = False
                for ctrl in self._controls:
                    ctrl.configure(state="readonly" if isinstance(ctrl, ttk.Combobox)
                                   else "normal")
                if not okay:
                    self.status.set("Abgelehnt: " + str(result))
                    messagebox.showerror("SH1→SHCDE Übertragung", str(result), parent=self)
                elif callback:
                    callback(result)
                else:
                    self.status.set(str(result))
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(100, self._poll)

    def _target(self):
        return under_work(self.vars["plan"].get())

    def create_plan(self):
        plan_file = self.vars["plan"].get()
        source = self.vars["sh1"].get()
        target = self.vars["shcde"].get()
        def work():
            plan = under_work(plan_file, must_exist=False)
            if plan.exists():
                raise BridgeError("Mapping-Plan bereits vorhanden: nicht überschreiben")
            data = create_plan(source, target)
            _save_plan(plan, data)
            return data
        self._work("Quell-/Ziel-Mapping", work, self._show_mapping)

    def open_plan(self):
        plan_path = self.vars["plan"].get()
        def work():
            plan, *_rest = _validate_plan(under_work(plan_path))
            return plan
        self._work("Mappingplan erneut prüfen", work, self._show_mapping)

    def _show_mapping(self, plan):
        self._mapping = list(plan["mapping"])
        coverage = plan["coverage"]
        self.status.set(
            f"SH1 {coverage['sh1_sprites']} · SHCDE {coverage['shcde_sprites']} · "
            f"{coverage['matching_keys']} Schlüsselvorschläge, "
            f"{coverage['approved']} freigegeben. Kein Autoimport."
        )
        self._fill()

    def _fill(self):
        if not hasattr(self, "tree"):
            return
        self.tree.delete(*self.tree.get_children())
        term = self.vars["filter"].get().strip().casefold()
        for i, row in enumerate(self._mapping):
            if term and term not in (row["source_key"] + " " + row["target_key"]).casefold():
                continue
            self.tree.insert("", "end", iid=str(i), values=(
                row["target_key"],
                "×".join(map(str, row["source_size"])),
                "×".join(map(str, row["target_size"])),
                "OK" if row["approved"] else "offen",
            ))

    def _row(self):
        selected = self.tree.selection()
        return self._mapping[int(selected[0])] if selected else None

    def _selected(self, _event=None):
        row = self._row()
        if row is None:
            return
        self.vars["fit"].set(row["fit"] if row["fit"] != "skip" else "contain")
        self.vars["state_note"].set(row["state_note"])
        base = _read_json(under_work(self.vars["plan"].get()))
        def preview(working_dir, atlas, key):
            root = under_work(working_dir)
            index = _read_json(root / "index.json")
            source = next((a for a in index["atlases"] if a["directory"] == atlas), None)
            if source is None:
                raise BridgeError("Der Atlasordner ist nicht mehr im Index")
            crop = next((c for c in source["crops"] if c["key"] == key), None)
            if crop is None:
                raise BridgeError("Originalressource fehlt im Index")
            directory = root / source["directory"] / crop["file"]
            if directory.is_symlink() or not directory.is_file():
                raise BridgeError("Grafik fehlt oder ist verlinkt")
            with Image.open(directory) as stream:
                img = stream.convert("RGBA")
            img.thumbnail((280, 240), Image.Resampling.LANCZOS)
            background = Image.new("RGBA", img.size, (70, 70, 70, 255))
            background.alpha_composite(img)
            return ImageTk.PhotoImage(background.convert("RGB"), master=self)
        try:
            a = preview(base["source_export"], row["source_atlas"], row["source_key"])
            b = preview(base["target_export"], row["target_atlas"], row["target_key"])
            self._images = [a, b]
            self.before_label.configure(image=a, text="SH1")
            self.after_label.configure(image=b, text="Crusader")
        except (OSError, ValueError, BridgeError) as exc:
            self.before_label.configure(image="", text="Bildvergleich nicht lesbar")
            self.after_label.configure(image="", text=str(exc))

    def approve(self):
        row = self._row()
        if row is None:
            messagebox.showwarning("Element wählen", "Erst eine SH1-/SHCDE-Zuordnung auswählen.", parent=self)
            return
        source, target = row["source_key"], row["target_key"]
        plan_path = self.vars["plan"].get()
        fit, note = self.vars["fit"].get(), self.vars["state_note"].get()
        if not messagebox.askyesno(
            "Fachliche Freigabe",
            f"{source} -> {target}\nModus: {fit}\nBegründung: {note}\n\n"
            "Das bestätigt deine manuelle Bedeutungs-/Zustandsprüfung; "
            "Ingame-Funktion ist hiermit NICHT nachgewiesen. Freigeben?",
            parent=self, default="no",
        ):
            return
        def work():
            approve_mapping(plan_path, source, target, fit=fit, state_note=note)
            return _validate_plan(under_work(plan_path))[0]
        self._work("Elementfreigabe", work, self._show_mapping)

    def revoke(self):
        row = self._row()
        if row is None:
            return
        plan_path = self.vars["plan"].get()
        target_key = row["target_key"]
        def work():
            revoke_mapping(plan_path, target_key)
            return _validate_plan(under_work(plan_path))[0]
        self._work("Freigabe zurücknehmen", work, self._show_mapping)

    def apply(self):
        output = self.vars["output"].get()
        plan_path = self.vars["plan"].get()
        source_game = Path(self.vars["source_game"].get())
        target_game = Path(self.vars["target_game"].get())
        target_xaml = Path(self.vars["target_xaml"].get())
        if not messagebox.askyesno(
            "Native SH1→SHCDE-Kandidatendateien",
            "Freigegebene Grafiken werden in einen NEUEN Crusader-Arbeitsstand "
            "kopiert. Alle nicht zugewiesenen Sprites bleiben unverändert. "
            "Spiele/Produktionspakete werden nicht installiert. Fortfahren?",
            parent=self, default="no",
        ):
            return
        def work():
            report = apply_plan(
                plan_path, output,
                source_game=source_game,
                target_game=target_game,
                target_xaml=target_xaml,
            )
            return (
                f"{len(report['approved_transfers'])} bestätigte Bilder in "
                f"{report['total_target_sprites']} Crusader-Slots übertragen. "
                "Nun im Suite-Reiter Oberfläche per Bilder laden öffnen, "
                "weiterbearbeiten und mit dem nativen Crusader-Atlasprüfer prüfen."
            )
        self._work("Native HUD-Übertragung", work)

    def verify(self):
        output = self.vars["output"].get()
        def work():
            report = verify_candidate(output)
            return (
                f"SHCDE-Sprites {report['target_crops_checked']} geprüft; "
                f"übernommen {report['transferred_crops']}; weiterbearbeitet "
                f"{len(report['transferred_crops_further_edited'])}. "
                "Keine Ingame-Freigabe."
            )
        self._work("Crusader-Bearbeitungsstand", work)

    def open_folder(self):
        try:
            folder = under_work(self.vars["output"].get())
            os.startfile(str(folder))
        except (OSError, BridgeError) as exc:
            messagebox.showerror("Arbeitsordner", str(exc), parent=self)


if __name__ == "__main__":
    CrossGameHudBridge().mainloop()

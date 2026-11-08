"""Direct multi-selection transfer between existing SH1 and SHCDE UI exports."""
from __future__ import annotations

import os
from pathlib import Path
from queue import Empty, Queue
from threading import Thread
import tkinter as tk
from tkinter import filedialog, ttk

from PIL import Image, ImageTk
from suite_tcl_runtime import call_with_tcl_bootstrap_retries
from suite_workarea import ScrollableWorkarea
from ui_sh1_to_shcde_bridge import (
    ROOT, BridgeError, _read_json, _save_plan, _validate_plan, apply_plan,
    create_plan, select_mappings, select_mapping, under_work, verify_candidate,
)


class CrossGameHudBridge(tk.Tk):
    def __init__(self):
        call_with_tcl_bootstrap_retries(super().__init__)
        self.title("SpriteSuite – SH1-HUD in Crusader DE übertragen")
        self.geometry("1160x820")
        self.minsize(540, 360)
        self.protocol("WM_DELETE_WINDOW", self.close)
        defaults = dict(sh1="work/sh1-hud-editierbar", shcde="work/ui", plan="work/sh1-zu-shcde-plan.json",
                        output="work/sh1-zu-shcde-editierbar", source_game="", target_game="", target_xaml="",
                        filter="", fit="exact", source_key="", target_key="")
        self.vars = {key: tk.StringVar(master=self, value=value) for key, value in defaults.items()}
        self.check_originals = tk.BooleanVar(master=self, value=False)
        self.status = tk.StringVar(master=self, value="Exportordner laden, Zuordnungen wählen und direkt übertragen.")
        self._controls, self._images, self._mapping = [], [], []
        self._queue, self._generation = Queue(), 0
        self._busy = self._closing = False
        self._plan = self._poll_job = None
        self._build()
        self.vars["filter"].trace_add("write", lambda *_: self._fill())
        self._poll_job = self.after(40, self._poll)

    def _field(self, parent, row, title, name, choose=None):
        ttk.Label(parent, text=title).grid(row=row, column=0, sticky="w", padx=4, pady=3)
        entry = ttk.Entry(parent, textvariable=self.vars[name], width=28)
        entry.grid(row=row, column=1, sticky="ew", padx=4, pady=3)
        self._controls.append(entry)
        if choose:
            button = ttk.Button(parent, text="…", width=3, command=lambda: self._pick(name, choose))
            button.grid(row=row, column=2, padx=4)
            self._controls.append(button)

    def _pick(self, name, kind):
        if kind == "folder":
            value = filedialog.askdirectory(parent=self, initialdir=str(ROOT), title="Arbeitsordner wählen")
        elif kind == "file":
            value = filedialog.askopenfilename(parent=self, initialdir=str(ROOT), filetypes=[("Assetdatei", "*.assets")])
        else:
            value = filedialog.asksaveasfilename(parent=self, initialdir=str(ROOT / "work"),
                defaultextension=".json", filetypes=[("JSON", "*.json")], title="Neuen Mappingplan speichern")
        if value:
            self.vars[name].set(value)

    def _button(self, parent, label, callback, row, column):
        button = ttk.Button(parent, text=label, command=callback)
        button.grid(row=row, column=column, sticky="ew", padx=3, pady=3)
        self._controls.append(button)
        return button

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.area = ScrollableWorkarea(self, min_width=650)
        self.area.grid(row=0, column=0, sticky="nsew")
        shell = ttk.Frame(self.area.body, padding=10)
        shell.pack(fill="both", expand=True)
        shell.columnconfigure(0, weight=1)
        ttk.Label(shell, text="Stronghold 1 HUD → Crusader DE", font=("Segoe UI", 16, "bold")).grid(row=0, column=0, sticky="w")
        intro = ttk.Label(shell, wraplength=700, text=(
            "Vorhandene SH1- und Crusader-Exportordner wählen. Mehrere Zuordnungen lassen sich direkt "
            "in einen neuen Arbeitsstand übertragen. Eine Spielinstallation oder Qualitätsfreigabe ist dafür nicht erforderlich."))
        intro.grid(row=1, column=0, sticky="ew", pady=(5, 8))
        shell.bind("<Configure>", lambda event: intro.configure(wraplength=max(180, event.width - 24)))
        fields = ttk.LabelFrame(shell, text="Arbeitsstände", padding=6)
        fields.grid(row=2, column=0, sticky="ew")
        fields.columnconfigure(1, weight=1)
        for row, (label, key, kind) in enumerate((("SH1-HUD-Exportordner", "sh1", "folder"),
                ("Crusader-UI-Zielexport", "shcde", "folder"), ("Mapping-Plan", "plan", "save"),
                ("Neuer SHCDE-Arbeitsstand", "output", "folder"))):
            self._field(fields, row, label, key, kind)
        actions = ttk.Frame(shell)
        actions.grid(row=3, column=0, sticky="ew", pady=5)
        for column in range(3):
            actions.columnconfigure(column, weight=1)
        for index, (label, callback) in enumerate((("Mapping vorschlagen", self.create_plan),
                ("Plan öffnen/neu lesen", self.open_plan), ("Alle sichtbaren auswählen", self.select_visible),
                ("Auswahl übertragen", self.apply), ("SHCDE-Arbeitsstand prüfen", self.verify),
                ("Ordner im Explorer", self.open_folder))):
            button = self._button(actions, label, callback, index // 3, index % 3)
            if callback == self.apply:
                self.transfer_button = button
        listing = ttk.LabelFrame(shell, text="Zuordnungen – Strg/Shift für Mehrfachauswahl", padding=6)
        listing.grid(row=4, column=0, sticky="ew", pady=4)
        listing.columnconfigure(0, weight=1)
        entry = ttk.Entry(listing, textvariable=self.vars["filter"])
        entry.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 3))
        self._controls.append(entry)
        self.tree = ttk.Treeview(listing, show="headings", selectmode="extended", height=7,
            columns=("source", "target", "sh1", "crusader", "fit"))
        for key, label, width in (("source", "SH1-Schlüssel", 190), ("target", "Crusader-Schlüssel", 190),
                ("sh1", "SH1-Maß", 90), ("crusader", "SHCDE-Maß", 100), ("fit", "Maßregel", 90)):
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, minwidth=70)
        ybar = ttk.Scrollbar(listing, orient="vertical", command=self.tree.yview)
        xbar = ttk.Scrollbar(listing, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
        self.tree.grid(row=1, column=0, sticky="nsew")
        ybar.grid(row=1, column=1, sticky="ns")
        xbar.grid(row=2, column=0, sticky="ew")
        self.tree.bind("<<TreeviewSelect>>", self._selected)
        self.tree.bind("<Control-a>", self.select_visible)
        # Treeview has no configurable state option; busy callbacks still reject edits.
        custom = ttk.LabelFrame(shell, text="Freie Quell-/Zielzuordnung und Größenanpassung", padding=6)
        custom.grid(row=5, column=0, sticky="ew", pady=4)
        custom.columnconfigure(1, weight=1)
        self.source_picker = ttk.Combobox(custom, textvariable=self.vars["source_key"], state="readonly")
        self.target_picker = ttk.Combobox(custom, textvariable=self.vars["target_key"], state="readonly")
        self.fit_picker = ttk.Combobox(custom, textvariable=self.vars["fit"], state="readonly",
                                      values=("exact", "contain", "stretch"), width=12)
        for row, (label, widget) in enumerate((("SH1-Quelle", self.source_picker), ("Crusader-Ziel", self.target_picker),
                                               ("Maßregel für die Auswahl", self.fit_picker))):
            ttk.Label(custom, text=label).grid(row=row, column=0, sticky="w", padx=3, pady=3)
            widget.grid(row=row, column=1, sticky="ew", padx=3, pady=3)
            self._controls.append(widget)
        self.add_mapping_button = self._button(custom, "Zuordnung übernehmen", self.add_mapping, 3, 0)
        self.add_mapping_button.grid_configure(columnspan=2)
        ttk.Label(custom, wraplength=600, text="exact: gleiche Größe · contain: einpassen · stretch: auf Zielgröße strecken").grid(
            row=4, column=0, columnspan=2, sticky="ew", padx=3)
        previews = ttk.Frame(shell)
        previews.grid(row=6, column=0, sticky="ew", pady=6)
        for column in range(2):
            previews.columnconfigure(column, weight=1, uniform="preview")
        self.before_label = ttk.Label(previews, text="SH1-Grafik wählen", anchor="center")
        self.after_label = ttk.Label(previews, text="Crusader-Zielgrafik", anchor="center")
        self.before_label.grid(row=0, column=0, sticky="nsew", padx=4)
        self.after_label.grid(row=0, column=1, sticky="nsew", padx=4)
        native = ttk.LabelFrame(shell, text="Optionale Originalquellenprüfung", padding=6)
        native.grid(row=7, column=0, sticky="ew", pady=5)
        native.columnconfigure(1, weight=1)
        checkbox = ttk.Checkbutton(native, text="Originalquellen zusätzlich prüfen", variable=self.check_originals)
        checkbox.grid(row=0, column=0, columnspan=3, sticky="w")
        self._controls.append(checkbox)
        for row, (label, key, kind) in enumerate((("SH1: globalgamemanagers.assets", "source_game", "file"),
                ("Crusader: globalgamemanagers.assets", "target_game", "file"),
                ("Crusader Noesis-Ordner …/GUI/Sprites", "target_xaml", "folder")), start=1):
            self._field(native, row, label, key, kind)
        footer = ttk.Frame(self, padding=6)
        footer.grid(row=1, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        self.status_view = tk.Text(footer, height=2, width=1, wrap="word", state="disabled")
        self.status_view.grid(row=0, column=0, sticky="ew")
        bar = ttk.Scrollbar(footer, orient="vertical", command=self.status_view.yview)
        bar.grid(row=0, column=1, sticky="ns")
        self.status_view.configure(yscrollcommand=bar.set)
        self.status.trace_add("write", self._update_status)
        self._update_status()

    def _update_status(self, *_args):
        self.status_view.configure(state="normal")
        self.status_view.delete("1.0", "end")
        self.status_view.insert("1.0", self.status.get())
        self.status_view.count("1.0", "end", "update", "ypixels")
        self.status_view.configure(state="disabled")

    def _work(self, label, worker, on_success=None):
        if self._busy or self._closing:
            return False
        self._busy = True
        self._generation += 1
        generation = self._generation
        self.status.set(label + " läuft …")
        for control in self._controls:
            control.configure(state="disabled")
        def run():
            try:
                self._queue.put((generation, True, worker(), on_success))
            except Exception as error:
                self._queue.put((generation, False, str(error), None))
        Thread(target=run, daemon=True).start()
        return True

    def _poll(self):
        self._poll_job = None
        try:
            while True:
                generation, okay, result, callback = self._queue.get_nowait()
                if generation != self._generation:
                    continue
                self._busy = False
                if self._closing:
                    self.destroy()
                    return
                for control in self._controls:
                    control.configure(state="readonly" if isinstance(control, ttk.Combobox) else "normal")
                if not okay:
                    self.status.set("Vorgang nicht ausgeführt: " + str(result))
                elif callback:
                    callback(result)
                else:
                    self.status.set(str(result))
        except Empty:
            pass
        self._poll_job = self.after(40, self._poll)

    def _plan_data(self, plan, path):
        _checked, _source, _target, sources, targets = _validate_plan(under_work(path))
        return plan, list(sources), list(targets)

    def create_plan(self):
        path, source, target = (self.vars[key].get() for key in ("plan", "sh1", "shcde"))
        def work():
            output = under_work(path, must_exist=False)
            if output.exists():
                raise BridgeError("Mapping-Plan vorhanden: neuen Namen wählen oder Plan laden")
            plan = create_plan(source, target)
            _save_plan(output, plan)
            return self._plan_data(plan, path)
        return self._work("Quell-/Ziel-Mapping", work, self._show_mapping)

    def open_plan(self):
        path = self.vars["plan"].get()
        return self._work("Mappingplan lesen", lambda: self._plan_data(_validate_plan(under_work(path))[0], path), self._show_mapping)

    def _show_mapping(self, result):
        plan, sources, targets = result
        self._plan, self._mapping = plan, list(plan["mapping"])
        self.source_picker.configure(values=sources)
        self.target_picker.configure(values=targets)
        for key, values in (("source_key", sources), ("target_key", targets)):
            if self.vars[key].get() not in values:
                self.vars[key].set(values[0] if values else "")
        coverage = plan["coverage"]
        self.status.set(f"SH1 {coverage['sh1_sprites']} · SHCDE {coverage['shcde_sprites']} · "
                        f"{len(self._mapping)} Zuordnungen. Gewünschte Zeilen auswählen und übertragen.")
        self._fill()

    def _fill(self):
        if not hasattr(self, "tree"):
            return
        previous = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        term = self.vars["filter"].get().strip().casefold()
        for index, row in enumerate(self._mapping):
            if term and term not in (row["source_key"] + " " + row["target_key"]).casefold():
                continue
            self.tree.insert("", "end", iid=str(index), values=(row["source_key"], row["target_key"],
                "×".join(map(str, row["source_size"])), "×".join(map(str, row["target_size"])), row["fit"]))
        self.tree.selection_set([key for key in previous if self.tree.exists(key)])

    def select_visible(self, _event=None):
        if not self._busy:
            self.tree.selection_set(self.tree.get_children())
        return "break"

    def _rows(self):
        return [self._mapping[int(key)] for key in self.tree.selection()]

    def _selected(self, _event=None):
        rows = self._rows()
        if not rows or self._busy or self._plan is None:
            return
        row = rows[0]
        self.vars["source_key"].set(row["source_key"])
        self.vars["target_key"].set(row["target_key"])
        def preview(folder, atlas, key):
            root = under_work(folder)
            index = _read_json(root / "index.json")
            sheet = next((item for item in index["atlases"] if item["directory"] == atlas), None)
            crop = next((item for item in sheet["crops"] if item["key"] == key), None) if sheet else None
            if crop is None:
                raise BridgeError("Originalressource fehlt im Exportindex")
            path = root / sheet["directory"] / crop["file"]
            if path.is_symlink() or not path.is_file():
                raise BridgeError("Grafik fehlt oder ist verlinkt")
            with Image.open(path) as opened:
                image = opened.convert("RGBA")
            image.thumbnail((280, 220), Image.Resampling.LANCZOS)
            with Image.new("RGBA", image.size, (70, 70, 70, 255)) as background:
                background.alpha_composite(image)
                photo = ImageTk.PhotoImage(background.convert("RGB"), master=self)
            image.close()
            return photo
        try:
            self._images = [preview(self._plan["source_export"], row["source_atlas"], row["source_key"]),
                            preview(self._plan["target_export"], row["target_atlas"], row["target_key"])]
            self.before_label.configure(image=self._images[0], text="SH1")
            self.after_label.configure(image=self._images[1], text="Crusader")
        except (OSError, ValueError) as error:
            self.before_label.configure(image="", text="Bildvergleich nicht lesbar")
            self.after_label.configure(image="", text=str(error))

    def add_mapping(self):
        if self._plan is None:
            self.status.set("Zuerst einen Mappingplan laden oder erzeugen.")
            return False
        path = self.vars["plan"].get()
        source, target, fit = (self.vars[key].get() for key in ("source_key", "target_key", "fit"))
        def work():
            select_mapping(path, source, target, fit=fit)
            return self._plan_data(_validate_plan(under_work(path))[0], path)
        return self._work("Zuordnung übernehmen", work, self._show_mapping)

    def apply(self):
        rows = self._rows()
        if not rows:
            self.status.set("Eine oder mehrere Zuordnungen auswählen.")
            return False
        path, output, fit = (self.vars[key].get() for key in ("plan", "output", "fit"))
        selections = [dict(source_key=row["source_key"], target_key=row["target_key"], fit=fit) for row in rows]
        native = {}
        if self.check_originals.get():
            values = {key: self.vars[key].get().strip() for key in ("source_game", "target_game", "target_xaml")}
            if not all(values.values()):
                self.status.set("Für die eingeschaltete optionale Quellenprüfung alle drei Originalpfade wählen.")
                return False
            native = {key: Path(value) for key, value in values.items()}
        def work():
            select_mappings(path, selections, replace_selection=True)
            report = apply_plan(path, output, target_keys=[row["target_key"] for row in rows], **native)
            return (f"{len(report['transfers'])} Bilder in {report['total_target_sprites']} Crusader-Slots übertragen. "
                    "Den neuen Ordner unter Oberfläche mit Bilder laden öffnen und weiterbearbeiten.")
        return self._work("Auswahl übertragen", work)

    def verify(self):
        output = self.vars["output"].get()
        def work():
            report = verify_candidate(output)
            return (f"SHCDE-Sprites {report['target_crops_checked']} geprüft; "
                    f"übernommen {report['transferred_crops']}; weiterbearbeitet "
                    f"{len(report['transferred_crops_further_edited'])}.")
        return self._work("Crusader-Bearbeitungsstand", work)

    def open_folder(self):
        try:
            os.startfile(str(under_work(self.vars["output"].get())))
        except (OSError, BridgeError) as error:
            self.status.set(str(error))

    def close(self):
        if self._busy:
            self._closing = True
            self.status.set("Laufende Übertragung wird beendet; das Fenster schließt danach.")
            return False
        if self._poll_job is not None:
            self.after_cancel(self._poll_job)
        self.destroy()
        return True


if __name__ == "__main__":
    CrossGameHudBridge().mainloop()

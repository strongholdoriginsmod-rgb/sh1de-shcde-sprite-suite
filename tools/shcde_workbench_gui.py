"""Bilingual, nonblocking Tk workbench for SpriteSuite's 16 SHCDE domains.

The GUI calls the exact same editor/CLI functions as the standard Suite tool
catalog. It does not duplicate native encoders, runtime hooks or project
writers. Every optional installation command is user-triggered.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import shlex
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from tkinter.scrolledtext import ScrolledText

from shcde_mod_project import DOMAINS, EDITORS, load_project, make_project, edit_domain, add_asset, inspect_project

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
NAMES_DE = {
    "api": "API-Explorer",
    "native": "Native Baseline",
    "modpack": "Mod-Composer",
    "building": "Gebäude, HP und Feuer",
    "aiv": "KI-Burgen und AIV",
    "aic": "KI-Persönlichkeiten",
    "units": "Einheiten und Kampf",
    "economy": "Wirtschaft und Balance",
    "scenario": "Szenarien und Ereignisse",
    "terrain": "Karten und Gelände",
    "hud": "HUD und Noesis",
    "inspector": "In-Game-Inspektor",
    "audio": "Audio und Burgherren",
    "multiplayer": "Multiplayer und Presets",
    "pathing": "Pfadfindung und Leistung",
    "qa": "Automatische QA",
}


class ScrollableFrame(ttk.Frame):
    """Keep the complete form reachable when the window or DPI changes."""

    def __init__(self, master):
        super().__init__(master)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, highlightthickness=0, width=1, height=1)
        self.horizontal = ttk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)
        self.vertical = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=self.horizontal.set,
                              yscrollcommand=self.vertical.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.vertical.grid(row=0, column=1, sticky="ns")
        self.horizontal.grid(row=1, column=0, sticky="ew")
        self.body = ttk.Frame(self.canvas)
        self._window = self.canvas.create_window(0, 0, anchor="nw", window=self.body)
        self.body.bind("<Configure>", self._resize)
        self.canvas.bind("<Configure>", self._resize)

    def _resize(self, _event=None):
        self.canvas.itemconfigure(self._window,
            width=max(self.canvas.winfo_width(), self.body.winfo_reqwidth()),
            height=max(self.canvas.winfo_height(), self.body.winfo_reqheight()))
        self.canvas.configure(scrollregion=self.canvas.bbox(self._window))

    def scroll_wheel(self, event):
        delta = getattr(event, "delta", 0)
        step = (-1 if getattr(event, "num", None) == 4 else
                1 if getattr(event, "num", None) == 5 else
                -max(1, abs(delta) // 120) if delta > 0 else
                max(1, abs(delta) // 120) if delta < 0 else 0)
        if step:
            if event.state & 1:
                self.canvas.xview_scroll(step, "units")
            else:
                self.canvas.yview_scroll(step, "units")
            return "break"

    def reveal(self, widget):
        node = widget
        while node is not None and node is not self.body:
            node = getattr(node, "master", None)
        if node is None or not widget.winfo_ismapped():
            return
        bounds = self.canvas.bbox(self._window)
        if not bounds:
            return
        for axis, position, span, view_span, content_span in (
            ("x", widget.winfo_rootx() - self.body.winfo_rootx(),
             widget.winfo_width(), self.canvas.winfo_width(), bounds[2]),
            ("y", widget.winfo_rooty() - self.body.winfo_rooty(),
             widget.winfo_height(), self.canvas.winfo_height(), bounds[3]),
        ):
            start = getattr(self.canvas, "canvas" + axis)(0)
            size = min(span, view_span)
            target = position if position < start else (
                position + size - view_span if position + size > start + view_span else None)
            if target is not None and content_span > 0:
                getattr(self.canvas, axis + "view_moveto")(max(0, target / content_span))


class WorkbenchWindow(tk.Tk):
    def __init__(self, *, project: Path | None = None):
        from suite_tcl_runtime import install_tcl_env, call_with_tcl_bootstrap_retries
        install_tcl_env(ROOT)
        call_with_tcl_bootstrap_retries(lambda: super(WorkbenchWindow, self).__init__())
        self.title("SpriteSuite – SHCDE Modding Workbench")
        width = min(1150, max(620, self.winfo_screenwidth() - 80))
        height = min(760, max(420, self.winfo_screenheight() - 100))
        self.geometry(f"{width}x{height}")
        self.minsize(620, 420)
        self._queue: queue.Queue = queue.Queue()
        self._busy = False
        self.language = tk.StringVar(master=self, value="de")
        self.project_path = tk.StringVar(master=self, value=str(project or ""))
        self.game_path = tk.StringVar(master=self)
        self.baseline_path = tk.StringVar(master=self)
        self.query = tk.StringVar(master=self)
        self.tool_args = tk.StringVar(master=self)
        self.property_name = tk.StringVar(master=self)
        self.current_domain = tk.StringVar(master=self, value="api")
        self.status = tk.StringVar(master=self, value="Bereit / Ready")
        self._build()
        self._select_domain("api")
        if project is not None:
            self._refresh_project()
        self.after(80, self._consume)

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.form_scroll = ScrollableFrame(self)
        self.form_scroll.grid(row=0, column=0, sticky="nsew")
        form = self.form_scroll.body
        form.columnconfigure(0, weight=1)
        form.rowconfigure(2, weight=1)
        self.bind("<MouseWheel>", self.form_scroll.scroll_wheel, add="+")
        self.bind("<Button-4>", self.form_scroll.scroll_wheel, add="+")
        self.bind("<Button-5>", self.form_scroll.scroll_wheel, add="+")
        self.bind("<FocusIn>", lambda event: self.form_scroll.reveal(event.widget), add="+")
        title = ttk.Frame(form, padding=(12, 10))
        title.grid(row=0, column=0, sticky="ew")
        title.columnconfigure(0, weight=1)
        ttk.Label(title, text="SpriteSuite · SHCDE Workbench",
                  font=("Segoe UI", 15, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Combobox(title, textvariable=self.language, values=("de", "en"),
                     width=5, state="readonly").grid(row=0, column=1, padx=8)
        self.language.trace_add("write", lambda *_: self._redraw_domains())

        paths = ttk.Frame(form, padding=(12, 0))
        paths.grid(row=1, column=0, sticky="ew")
        paths.columnconfigure(1, weight=1)
        ttk.Label(paths, text="Projekt / Project").grid(row=0, column=0, sticky="w")
        ttk.Entry(paths, textvariable=self.project_path).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(paths, text="Öffnen / Open", command=self._open_project).grid(row=0, column=2)
        ttk.Button(paths, text="Neu / New", command=self._new_project).grid(row=0, column=3, padx=5)
        ttk.Button(paths, text="ZIP exportieren", command=self._export).grid(row=0, column=4)
        ttk.Label(paths, text="Spiel / Game").grid(row=1, column=0, sticky="w")
        ttk.Entry(paths, textvariable=self.game_path).grid(row=1, column=1, sticky="ew", padx=6)
        ttk.Button(paths, text="Ordner wählen", command=self._choose_game).grid(row=1, column=2, columnspan=2, sticky="ew")
        ttk.Label(paths, text="Native Baseline").grid(row=2, column=0, sticky="w")
        ttk.Entry(paths, textvariable=self.baseline_path).grid(row=2, column=1, sticky="ew", padx=6)
        ttk.Button(paths, text="Ordner wählen", command=self._choose_baseline).grid(row=2, column=2, columnspan=2, sticky="ew")

        pane = ttk.Panedwindow(form, orient="horizontal")
        pane.grid(row=2, column=0, sticky="nsew", padx=12, pady=8)
        nav = ttk.Frame(pane, padding=(5, 5))
        nav.columnconfigure(0, weight=1)
        nav.rowconfigure(1, weight=1)
        ttk.Label(nav, text="16 Modding-Bereiche", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="w")
        self.domains = tk.Listbox(nav, width=28, height=20, exportselection=False,
                                  activestyle="dotbox", font=("Segoe UI", 10))
        self.domains.grid(row=1, column=0, sticky="nsew", pady=4)
        self.domains.bind("<<ListboxSelect>>", self._on_domain)
        pane.add(nav, weight=1)

        center = ttk.Frame(pane, padding=(5, 5))
        center.columnconfigure(0, weight=1)
        center.rowconfigure(1, weight=1)
        self.domain_title = ttk.Label(center, text="", font=("Segoe UI", 12, "bold"))
        self.domain_title.grid(row=0, column=0, sticky="w", pady=(0, 7))
        notebook = ttk.Notebook(center)
        self.notebook = notebook
        notebook.grid(row=1, column=0, sticky="nsew")
        pane.add(center, weight=4)

        project_tab = ttk.Frame(notebook, padding=10)
        project_tab.columnconfigure(0, weight=1)
        project_tab.rowconfigure(0, weight=1)
        notebook.add(project_tab, text="Projekt & Daten")
        self.details = ScrolledText(project_tab, wrap="word", height=12, font=("Consolas", 9))
        self.details.grid(row=0, column=0, columnspan=3, sticky="nsew")
        ttk.Label(project_tab, text="Eigenschaft / Property (z.B. combat.hp)").grid(row=1, column=0, sticky="w", pady=(8, 1))
        ttk.Entry(project_tab, textvariable=self.property_name).grid(row=2, column=0, sticky="ew")
        ttk.Button(project_tab, text="Asset importieren", command=self._add_asset).grid(row=2, column=1, padx=5)
        ttk.Label(project_tab, text="JSON-Wert / JSON value").grid(row=3, column=0, sticky="w", pady=(5, 1))
        self.value_text = ScrolledText(project_tab, height=4, wrap="word", font=("Consolas", 10))
        self.value_text.grid(row=4, column=0, columnspan=3, sticky="ew")
        self.value_text.insert("1.0", "null")
        ttk.Button(project_tab, text="Im Projekt speichern", command=self._save_domain).grid(row=5, column=0, sticky="w", pady=(6, 2))

        tools_tab = ttk.Frame(notebook, padding=10)
        tools_tab.columnconfigure(0, weight=1)
        notebook.add(tools_tab, text="Werkzeuge & Runtime")
        ttk.Label(tools_tab, text="Werkzeug des ausgewählten Bereichs").grid(row=0, column=0, sticky="w")
        self.tool_selected = tk.StringVar(master=self)
        self.tool_select = ttk.Combobox(tools_tab, textvariable=self.tool_selected, state="readonly")
        self.tool_select.grid(row=1, column=0, columnspan=3, sticky="ew", pady=3)
        ttk.Label(tools_tab, text="Zusätzliche CLI-Argumente (frei wählbar)").grid(row=2, column=0, sticky="w", pady=(8, 2))
        ttk.Entry(tools_tab, textvariable=self.tool_args).grid(row=3, column=0, columnspan=3, sticky="ew")
        ttk.Button(tools_tab, text="Hilfe zum Werkzeug", command=self._tool_help).grid(row=4, column=0, sticky="ew", pady=7)
        ttk.Button(tools_tab, text="Werkzeug ausführen", command=self._tool_run).grid(row=4, column=1, sticky="ew", pady=7, padx=5)
        ttk.Label(tools_tab, text="Schnellaktionen · nur bewusst ausgewählte Operationen werden ausgeführt").grid(row=5, column=0, columnspan=3, sticky="w", pady=(12, 4))
        quick = ttk.Frame(tools_tab)
        quick.grid(row=6, column=0, columnspan=3, sticky="ew")
        for index, (label, callback) in enumerate((
            ("API durchsuchen", self._query_api),
            ("Native Baseline suchen", self._query_native),
            ("Szenario zu Lua", self._scenario),
            ("AIV-Vorschau", self._aiv_preview),
            ("Build: Inspektor", self._build_inspector),
            ("Build: Gameplay", self._build_gameplay),
            ("QA starten", self._qa),
            ("Log-Profiler", self._pathing),
            ("Lord-Mod-Paket", self._lord_pack),
            ("Suite-Projekt verbinden", self._link_suite_project),
        )):
            ttk.Button(quick, text=label, command=callback).grid(row=index // 3,
                column=index % 3, sticky="ew", padx=3, pady=3)
        for column in range(3):
            quick.columnconfigure(column, weight=1)
        ttk.Label(tools_tab, text="Suchbegriff / Search query").grid(row=7, column=0, sticky="w", pady=(12, 2))
        ttk.Entry(tools_tab, textvariable=self.query).grid(row=8, column=0, columnspan=3, sticky="ew")

        output_tab = ttk.Frame(notebook, padding=10)
        output_tab.columnconfigure(0, weight=1)
        output_tab.rowconfigure(0, weight=1)
        notebook.add(output_tab, text="Ergebnisse / Output")
        self.output = ScrolledText(output_tab, wrap="word", font=("Consolas", 9), height=20)
        self.output.grid(row=0, column=0, sticky="nsew")
        self._redraw_domains()

        self.status_label = ttk.Label(form, textvariable=self.status, anchor="w")
        self.status_label.grid(row=3, column=0, sticky="ew", padx=14, pady=(0, 8))

    def _redraw_domains(self):
        previous = self.current_domain.get()
        self.domains.delete(0, "end")
        for key, english in DOMAINS.items():
            self.domains.insert("end", NAMES_DE.get(key, english) if
                                self.language.get() == "de" else english)
        self._select_domain(previous)

    def _select_domain(self, key):
        keys = tuple(DOMAINS)
        if key not in DOMAINS:
            key = "api"
        self.current_domain.set(key)
        self.domains.selection_clear(0, "end")
        self.domains.selection_set(keys.index(key))
        self.domains.see(keys.index(key))
        title = NAMES_DE.get(key, DOMAINS[key]) if self.language.get() == "de" else DOMAINS[key]
        self.domain_title.configure(text=title)
        tools = [item for item in EDITORS.get(key, ()) if (TOOLS / item).is_file()]
        self.tool_select.configure(values=tools)
        self.tool_selected.set(tools[0] if tools else "")
        self._refresh_project()

    def _on_domain(self, _event=None):
        values = self.domains.curselection()
        if values:
            self._select_domain(tuple(DOMAINS)[values[0]])

    def _error(self, error):
        messagebox.showerror("SpriteSuite SHCDE", str(error), parent=self)

    def _require_project(self) -> Path:
        path = Path(self.project_path.get())
        load_project(path)
        return path

    def _refresh_project(self):
        domain = self.current_domain.get()
        try:
            project = self._require_project()
            data = load_project(project)
            details = {"project": str(project), "identity": data.get("identity"),
                       "domain": domain, "editorData": data["domains"].get(domain, {}),
                       "linkedEditors": EDITORS.get(domain, ()),
                       "assetCount": len(data["assets"])}
        except (OSError, ValueError):
            details = {"selectedDomain": domain, "title": DOMAINS[domain],
                       "projectOpen": False, "linkedEditors": EDITORS.get(domain, ())}
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("end", json.dumps(details, indent=2, ensure_ascii=False))
        self.details.configure(state="disabled")

    def _open_project(self):
        path = filedialog.askdirectory(parent=self, title="Vorhandenes SpriteSuite-Projekt öffnen")
        if not path:
            return
        self.project_path.set(path)
        self._refresh_project()

    def _new_project(self):
        parent = filedialog.askdirectory(parent=self, title="Elternordner für neues Projekt")
        if not parent:
            return
        folder = simpledialog.askstring("Projektordner", "Neuer Unterordner:", parent=self)
        if not folder:
            return
        if folder in (".", "..") or any(separator in folder for separator in ("/", "\\")):
            return self._error("Bitte einen einfachen neuen Ordnernamen verwenden.")
        name = simpledialog.askstring("Name", "Anzeigename / Mod name:", initialvalue=folder, parent=self)
        guid = simpledialog.askstring("Mod-GUID", "Eigene eindeutige GUID:", parent=self)
        if not name or not guid:
            return
        try:
            project = Path(parent) / folder
            make_project(project, name=name, guid=guid)
            self.project_path.set(str(project))
            self._refresh_project()
            self.status.set("Neues SpriteSuite-Modprojekt erstellt.")
        except (OSError, ValueError) as err:
            self._error(err)

    def _choose_game(self):
        folder = filedialog.askdirectory(parent=self, title="SHCDE-Spielordner wählen")
        if folder:
            self.game_path.set(folder)

    def _choose_baseline(self):
        folder = filedialog.askdirectory(parent=self, title="Serp Native Baseline wählen")
        if folder:
            self.baseline_path.set(folder)

    def _save_domain(self):
        try:
            project = self._require_project()
            key = self.property_name.get().strip()
            value = json.loads(self.value_text.get("1.0", "end"))
            edit_domain(project, self.current_domain.get(), key, value)
            self._refresh_project()
            self.status.set("Projekteigenschaft aktualisiert.")
        except (OSError, ValueError) as err:
            self._error(err)

    def _add_asset(self):
        try:
            project = self._require_project()
        except (OSError, ValueError) as err:
            return self._error(err)
        file = filedialog.askopenfilename(parent=self, title="Eigene Mod-Datei auswählen")
        if not file:
            return
        target = simpledialog.askstring(
            "Ziel im Mod", "Relativer Assetpfad (beliebiges Format):",
            initialvalue=Path(file).name, parent=self)
        if not target:
            return
        try:
            add_asset(project, Path(file), target)
            self._refresh_project()
            self.status.set("Asset importiert; Quelldatei unverändert.")
        except (OSError, ValueError) as err:
            self._error(err)

    def _output_line(self, value: str):
        self.output.configure(state="normal")
        self.output.insert("end", value + "\n")
        self.output.see("end")
        self.output.configure(state="disabled")

    def _run(self, tool: str, argv: list[str]):
        path = TOOLS / tool
        if self._busy:
            return self._error("Ein Werkzeug läuft bereits.")
        if not path.is_file():
            return self._error("Werkzeug fehlt: " + str(path))
        self._busy = True
        self.status.set("Werkzeug läuft: " + tool)
        self._output_line("$ " + tool + " " + " ".join(argv))
        environment = dict(os.environ)
        environment["PYTHONPATH"] = os.pathsep.join(filter(None, (
            str(TOOLS), str(ROOT / "src"), environment.get("PYTHONPATH", ""))))
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        def worker():
            try:
                result = subprocess.run([sys.executable, str(path), *argv], cwd=ROOT,
                    env=environment,
                    capture_output=True, text=True, errors="replace", timeout=360,
                    check=False)
                result_text = (result.stdout + result.stderr)[-120000:]
                self._queue.put((result.returncode, result_text))
            except (OSError, subprocess.TimeoutExpired) as error:
                self._queue.put((-1, str(error)))
        threading.Thread(target=worker, daemon=True).start()

    def _consume(self):
        try:
            while True:
                code, output = self._queue.get_nowait()
                self._output_line(output)
                self.status.set("Erfolg / Passed" if code == 0 else
                                "Fehler / Failed: Exit " + str(code))
                self._busy = False
                self._refresh_project()
        except queue.Empty:
            pass
        self.after(100, self._consume)

    def _tool_help(self):
        if self.tool_selected.get():
            self._run(self.tool_selected.get(), ["--help"])

    def _tool_run(self):
        if not self.tool_selected.get():
            return self._error("Für den Bereich ist noch kein startfähiges Werkzeug vorhanden.")
        try:
            args = shlex.split(self.tool_args.get(), posix=False)
            args = [item[1:-1] if len(item) > 1 and item[0] == item[-1] and
                    item[0] in ("'", '"') else item for item in args]
        except ValueError as err:
            return self._error(err)
        self._run(self.tool_selected.get(), args)

    def _export(self):
        try:
            project = self._require_project()
        except (OSError, ValueError) as err:
            return self._error(err)
        output = filedialog.asksaveasfilename(parent=self, title="Mod-ZIP",
            defaultextension=".zip", filetypes=(("ZIP", "*.zip"),))
        if output:
            self._run("shcde_mod_project.py",
                      ["export", "--project", str(project), "--output", output])

    def _query_api(self):
        if not self.game_path.get():
            return self._error("Zuerst einen Spielordner wählen.")
        self._run("shcde_api_native_index.py",
                  ["api", "--game", self.game_path.get(),
                   "--query", self.query.get(), "--limit", "60"])

    def _query_native(self):
        if not self.baseline_path.get():
            return self._error("Zuerst den lokalen Native-Baseline-Ordner wählen.")
        self._run("shcde_api_native_index.py",
                  ["native", "--baseline-root", self.baseline_path.get(),
                   "--query", self.query.get(), "--limit", "50"])

    def _scenario(self):
        source = filedialog.askopenfilename(parent=self,
            title="Szenario-Graph JSON", filetypes=(("JSON", "*.json"),))
        if source:
            out = filedialog.asksaveasfilename(parent=self, title="Lua-Modul speichern",
                defaultextension=".lua", filetypes=(("Lua", "*.lua"),))
            if out:
                self._run("shcde_scenario_graph.py", ["--graph", source, "--output", out])

    def _aiv_preview(self):
        source = filedialog.askopenfilename(parent=self, title="AIVJSON/Buildsteps JSON",
            filetypes=(("JSON", "*.aivjson *.json"),))
        if source:
            output = filedialog.asksaveasfilename(parent=self, title="AIV-Vorschau SVG",
                defaultextension=".svg", filetypes=(("SVG", "*.svg"),))
            if output:
                self._run("shcde_aiv_lord_studio.py",
                          ["aiv-preview", "--json", source, "--output", output])

    def _build_inspector(self):
        if not self.game_path.get():
            return self._error("Zuerst das Spielverzeichnis wählen.")
        target = filedialog.askdirectory(parent=self, title="Compiler-Ausgabeordner")
        if target:
            self._run("shcde_game_inspector.py",
                      ["build", "--game", self.game_path.get(), "--output", target])

    def _build_gameplay(self):
        if not self.game_path.get():
            return self._error("Zuerst das Spielverzeichnis wählen.")
        target = filedialog.askdirectory(parent=self, title="Compiler-Ausgabeordner")
        if target:
            self._run("shcde_gameplay_rules.py",
                      ["build", "--game", self.game_path.get(), "--output", target])

    def _qa(self):
        args: list[str] = []
        if self.project_path.get() and (Path(self.project_path.get()) / "SpriteSuite-Project.json").is_file():
            args += ["--project", self.project_path.get()]
        if self.game_path.get():
            args += ["--game", self.game_path.get()]
        self._run("shcde_qa_suite.py", args)

    def _pathing(self):
        source = filedialog.askopenfilename(parent=self, title="Laufzeit-/BepInEx-Log")
        if source:
            self._run("shcde_pathing_report.py", ["--log", source])

    def _link_suite_project(self):
        try:
            project = self._require_project()
        except (OSError, ValueError) as err:
            return self._error(err)
        folder = filedialog.askdirectory(parent=self, title="Bearbeitbares Hauptprojekt verbinden")
        if folder:
            self._run("shcde_mod_project.py",
                      ["link-suite", "--project", str(project), "--suite-project", folder])

    def _lord_pack(self):
        folder = filedialog.askdirectory(parent=self, title="Custom-Lord-Verzeichnis")
        if folder:
            target = filedialog.asksaveasfilename(parent=self, title="Custom-Lord ZIP",
                defaultextension=".zip", filetypes=(("ZIP", "*.zip"),))
            if target:
                self._run("shcde_aiv_lord_studio.py",
                          ["package", "--lord-directory", folder, "--output", target])

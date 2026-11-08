"""Tk editing shell for the *same* twelve source validators as the CLI.

No game installation, ProcessMemory access, hidden background operations or
implicit publishing. An edited module is saved only to a new immutable revision.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
import tkinter.font as tkfont
import webbrowser

from .catalog import MODULES, MODULE_DESCRIPTIONS, search, version_evidence
from .design import simulate_mission
from .engine import analyze, analyze_suite_ui
from .exporter import export_project
from .knowledge import search_native_baseline, search_api_surface
from .model import (
    PROJECT_FILENAME, load_current_project, load_project, new_project, next_revision, validate_project,
)
from .safety import StudioError, canonical_root, file_sha, json_bytes, read_json

PROJECT_REPOSITORY = Path(__file__).resolve().parents[3]
BG = "#161b22"
SURFACE = "#222936"
TEXT = "#eff2f5"
MUTED = "#b3bdc8"
ACCENT = "#9abce0"
BLOCK = "#e58d87"


class StudioWindow:
    def __init__(self, root: tk.Tk, workspace: Path | None, *, project_bound: bool = False):
        self.root = root
        self.project_bound = project_bound
        self._saved_project: dict | None = None
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.workspace: Path | None = None
        self.project: dict | None = None
        self.source_path = PROJECT_FILENAME
        self.source_sha = ""
        self.current_module = ""
        self.last_export: Path | None = None
        self._changing = False
        root.title("SpriteSuite – Modding Studio")
        root.geometry(f"{min(1260, root.winfo_screenwidth() - 80)}x"
                      f"{min(850, root.winfo_screenheight() - 100)}")
        root.minsize(760, 500)
        root.configure(bg=BG)
        self._style()
        self._build()
        if workspace is not None:
            self.open_workspace(workspace)
        else:
            self._show_welcome()

    def _style(self) -> None:
        theme = ttk.Style(self.root)
        # Windows native elements keep light button/entry surfaces even when
        # background is configured. Match their text without switching themes.
        native = theme.theme_use() in {"vista", "xpnative", "winnative"}
        control_text = "#17212f" if native else TEXT
        theme.configure("Studio.TFrame", background=BG)
        theme.configure("Studio.TLabel", background=BG, foreground=TEXT,
                        font=("Segoe UI", 10))
        theme.configure("Studio.Heading.TLabel", background=BG, foreground=TEXT,
                        font=("Segoe UI", 15, "bold"))
        theme.configure("Studio.TButton", padding=5, background=SURFACE,
                        foreground=control_text, font=("Segoe UI", 10))
        theme.map("Studio.TButton", background=[("active", "#36475c")])
        theme.configure("Studio.Treeview", background=SURFACE, fieldbackground=SURFACE,
                        foreground=TEXT, font=("Segoe UI", 10),
                        rowheight=max(27, tkfont.Font(root=self.root,
                            font=("Segoe UI", 10)).metrics("linespace") + 8))
        theme.map("Studio.Treeview", background=[("selected", "#3a536a")])
        theme.configure("Studio.Treeview.Heading", background="#3b4554", foreground=control_text)
        theme.configure("Studio.TPanedwindow", background=BG)
        theme.configure("Studio.TEntry", fieldbackground=SURFACE, foreground=control_text)

    def _schedule_actions(self, _event=None) -> None:
        if getattr(self, "_actions_job", None) is None:
            self._actions_job = self.root.after_idle(self._layout_actions)

    def _layout_actions(self) -> None:
        """Wrap actual measured button widths; retain their keyboard order."""
        self._actions_job = None
        width = self.actions_frame.winfo_width()
        if width < 2:
            return
        x = y = row_height = 0
        for button in self.action_buttons:
            button_width = min(width, button.winfo_reqwidth())
            button_height = button.winfo_reqheight()
            if x and x + button_width > width:
                x = 0
                y += row_height + 6
                row_height = 0
            button.place(x=x, y=y, width=button_width, height=button_height)
            x += button_width + 7
            row_height = max(row_height, button_height)
        height = y + row_height
        if self.actions_frame.winfo_reqheight() != height:
            self.actions_frame.configure(height=height)

    @staticmethod
    def _scrollable_text(parent, **options):
        frame = ttk.Frame(parent, style="Studio.TFrame")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        text = tk.Text(frame, width=1, height=1, **options)
        xbar = ttk.Scrollbar(frame, orient=tk.HORIZONTAL, command=text.xview)
        ybar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=text.yview)
        text.configure(xscrollcommand=xbar.set, yscrollcommand=ybar.set)
        text.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")
        StudioWindow._horizontal_wheel(text)
        return frame, text, xbar, ybar

    @staticmethod
    def _horizontal_wheel(widget):
        def scroll(event):
            widget.xview_scroll(-1 if event.delta > 0 else 1, "units")
            return "break"
        widget.bind("<Shift-MouseWheel>", scroll)

    def _document_window(self, title, content):
        window = tk.Toplevel(self.root)
        window.title(title)
        window.geometry("950x630")
        window.columnconfigure(0, weight=1)
        window.rowconfigure(0, weight=1)
        frame, text, _, _ = self._scrollable_text(
            window, wrap=tk.NONE, font=("Consolas", 10))
        frame.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        text.insert("1.0", content)
        text.configure(state=tk.DISABLED)
        return window

    def _preview_canvas(self, window, width, height):
        from suite_workarea import ScrollableWorkarea
        window.geometry("650x650")
        window.columnconfigure(0, weight=1)
        window.rowconfigure(0, weight=1)
        area = ScrollableWorkarea(window, background=BG, style="Studio.TFrame")
        area.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        canvas = tk.Canvas(area.body, width=width, height=height,
                           background="#182027", highlightthickness=0)
        canvas.grid(row=0, column=0, sticky="nw")
        area.refresh()
        return canvas

    def _build(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(3, weight=1)
        top = ttk.Frame(self.root, style="Studio.TFrame")
        top.grid(row=0, column=0, sticky="ew", padx=14, pady=(8, 5))
        top.columnconfigure(0, weight=1)
        ttk.Label(top, text="Modding Studio", style="Studio.Heading.TLabel").grid(
            row=0, column=0, sticky="w")
        caption = ttk.Label(
            top, text="   12 Offline-Werkzeuge · APIShared 0.27 · keine Spielinstallation",
            foreground=MUTED, style="Studio.TLabel",
        )
        caption.grid(row=1, column=0, sticky="ew")
        top.bind("<Configure>", lambda event: caption.configure(
            wraplength=max(100, event.width)))

        self.actions_frame = ttk.Frame(self.root, style="Studio.TFrame", height=1)
        self.actions_frame.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 5))
        self.action_buttons = []
        for title, callback in (
            ("Projekt öffnen", self.choose_workspace),
            ("Neues Projekt", self.create_workspace),
            ("Prüfen", self.run_check),
            ("Neue Revision", self.save_revision),
            ("Offline exportieren", self.export),
            ("Mission testen", self.simulate),
            ("Vorschau", self.preview),
            ("SDK durchsuchen", self.open_sdk),
            ("Nativewissen", self.open_native),
            ("Suite-XAML-Audit", self.audit_suite),
        ):
            if self.project_bound and title in {"Projekt öffnen", "Neues Projekt"}:
                continue
            self.action_buttons.append(ttk.Button(
                self.actions_frame, text=title, command=callback, style="Studio.TButton"))
        self.actions_frame.bind("<Configure>", self._schedule_actions)
        self.info = tk.StringVar(value="Kein Projekt geladen")
        ttk.Entry(self.root, textvariable=self.info, state="readonly",
                  style="Studio.TEntry").grid(row=2, column=0, sticky="ew",
                                              padx=14, pady=(0, 5))

        self.body_panes = tk.PanedWindow(self.root, orient=tk.VERTICAL, bg=BG,
                                        sashwidth=7, borderwidth=0)
        self.body_panes.grid(row=3, column=0, sticky="nsew", padx=12)
        main = tk.PanedWindow(self.body_panes, orient=tk.HORIZONTAL, bg=BG,
                             sashwidth=7, borderwidth=0)
        self.body_panes.add(main, minsize=170, height=430, stretch="always")
        left = ttk.Frame(main, style="Studio.TFrame")
        right = ttk.Frame(main, style="Studio.TFrame")
        main.add(left, minsize=140, width=250, stretch="never")
        main.add(right, minsize=240, stretch="always")
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(2, weight=1)
        ttk.Label(left, text="Werkzeuge", style="Studio.TLabel").grid(
            row=0, column=0, sticky="w", padx=5)
        self.module_list = tk.Listbox(
            left, bg=SURFACE, fg=TEXT, selectbackground="#45627d",
            selectforeground="#ffffff", highlightthickness=0, borderwidth=0,
            font=("Segoe UI", 10), activestyle="none", exportselection=False,
            width=1, height=1,
        )
        for id_, title, _ in MODULES:
            self.module_list.insert(tk.END, title)
        self.module_ybar = ttk.Scrollbar(left, orient=tk.VERTICAL, command=self.module_list.yview)
        self.module_xbar = ttk.Scrollbar(left, orient=tk.HORIZONTAL, command=self.module_list.xview)
        self.module_list.configure(yscrollcommand=self.module_ybar.set,
                                   xscrollcommand=self.module_xbar.set)
        self.module_list.grid(row=1, column=0, sticky="nsew", padx=(5, 0), pady=(5, 0))
        self.module_ybar.grid(row=1, column=1, sticky="ns", pady=(5, 0))
        self.module_xbar.grid(row=2, column=0, sticky="ew", padx=(5, 0))
        self._horizontal_wheel(self.module_list)
        self.module_list.bind("<<ListboxSelect>>", self._on_module_select)

        self.section_title = tk.StringVar(value="Projekt auswählen")
        heading = ttk.Label(right, textvariable=self.section_title,
                            style="Studio.Heading.TLabel")
        heading.grid(row=0, column=0, sticky="ew", padx=8, pady=(0, 3))
        self.section_summary = tk.StringVar(value="JSON-Entwurf prüfen und als neue Revision speichern.")
        description = ttk.Label(
            right, textvariable=self.section_summary,
            foreground=MUTED, style="Studio.TLabel",
        )
        description.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 3))
        right.bind("<Configure>", lambda event: (
            heading.configure(wraplength=max(100, event.width - 16)),
            description.configure(wraplength=max(100, event.width - 16))))
        editor_frame, self.editor, self.editor_xbar, self.editor_ybar = self._scrollable_text(
            right, wrap=tk.NONE, bg="#10141c", fg="#e6e9ed",
            insertbackground="#ffffff", selectbackground="#344c64",
            font=("Consolas", 10), relief=tk.FLAT, undo=True, padx=12, pady=10,
        )
        editor_frame.grid(row=2, column=0, sticky="nsew", padx=(8, 0))
        self.editor.config(state=tk.DISABLED)

        footer = ttk.Frame(self.body_panes, style="Studio.TFrame")
        footer.rowconfigure(1, weight=1)
        footer.columnconfigure(0, weight=1)
        footer_min = max(95, 3 * tkfont.Font(root=self.root,
            font=("Segoe UI", 10)).metrics("linespace") + 36)
        self.body_panes.add(footer, minsize=footer_min, height=155, stretch="never")
        self._footer_auto_height = None
        def fit_footer(event):
            height = max(footer_min, min(155, event.height // 4))
            if height != self._footer_auto_height:
                self._footer_auto_height = height
                self.body_panes.paneconfigure(footer, height=height)
        self.body_panes.bind("<Configure>", fit_footer)
        ttk.Label(footer, text="Validierungsbefunde – SOURCE_PASS ≠ Ingame-Freigabe",
                  style="Studio.TLabel").grid(row=0, column=0, sticky="w")
        self.results = ttk.Treeview(
            footer, columns=("module", "severity", "code", "message"),
            show="headings", height=5, style="Studio.Treeview",
        )
        for key, title, width in (
            ("module", "Bereich", 120), ("severity", "Status", 95),
            ("code", "Prüfung", 210), ("message", "Beschreibung", 800),
        ):
            self.results.heading(key, text=title)
            self.results.column(key, width=width, stretch=(key == "message"))
        self.results_xbar = ttk.Scrollbar(footer, orient=tk.HORIZONTAL, command=self.results.xview)
        self.results_ybar = ttk.Scrollbar(footer, orient=tk.VERTICAL, command=self.results.yview)
        self.results.configure(xscrollcommand=self.results_xbar.set, yscrollcommand=self.results_ybar.set)
        self.results.grid(row=1, column=0, sticky="nsew")
        self.results_ybar.grid(row=1, column=1, sticky="ns")
        self.results_xbar.grid(row=2, column=0, sticky="ew")
        self._horizontal_wheel(self.results)
        self.status = tk.StringVar(value="Nur Quell-/Vertragsprüfung, kein Unity-Build.")
        status_frame = ttk.Frame(self.root, style="Studio.TFrame")
        status_frame.grid(row=4, column=0, sticky="ew", padx=14, pady=5)
        status_frame.columnconfigure(0, weight=1)
        self.status_view = tk.Text(status_frame, width=1, height=2, wrap=tk.WORD,
                                   bg=BG, fg=MUTED, relief=tk.FLAT,
                                   font=("Segoe UI", 10), takefocus=True)
        self.status_ybar = ttk.Scrollbar(status_frame, orient=tk.VERTICAL,
                                         command=self.status_view.yview)
        self.status_view.configure(yscrollcommand=self.status_ybar.set)
        self.status_view.grid(row=0, column=0, sticky="ew")
        self.status_ybar.grid(row=0, column=1, sticky="ns")
        self.status.trace_add("write", self._update_status)
        self._update_status()
        self._schedule_actions()

    def _update_status(self, *_args):
        self.status_view.configure(state=tk.NORMAL)
        self.status_view.delete("1.0", tk.END)
        self.status_view.insert("1.0", self.status.get())
        self.status_view.configure(state=tk.DISABLED)

    def _show_welcome(self) -> None:
        self._set_editor(
            '{\n  "message": "Projekt öffnen oder neu anlegen",\n'
            '  "safety": "Offline, schreibgeschützte Quellen"\n}\n'
        )

    def _set_editor(self, content: str) -> None:
        self.editor.config(state=tk.NORMAL)
        self.editor.delete("1.0", tk.END)
        self.editor.insert("1.0", content)

    def is_dirty(self) -> bool:
        if self.project is None:
            return False
        candidate = deepcopy(self.project)
        if self.current_module:
            try:
                value = json.loads(self.editor.get("1.0", tk.END))
                if not isinstance(value, dict):
                    return True
                candidate["modules"][self.current_module] = value
            except ValueError:
                return True
        return candidate != self._saved_project

    def save(self) -> bool:
        return self.save_revision() if self.is_dirty() else True

    def lift(self) -> None:
        self.root.lift()

    def confirm_saved(self, action: str) -> bool:
        if not self.is_dirty():
            return True
        answer = messagebox.askyesnocancel(
            "Ungespeicherter Studio-Entwurf",
            "Studio-Änderungen vor " + action + " als neue Revision speichern?",
            parent=self.root, default="cancel")
        if answer is None:
            return False
        return self.save() if answer else True

    def close(self) -> bool:
        if not self.confirm_saved("dem Schließen"):
            return False
        self.root.destroy()
        return True

    def _collect_module(self) -> bool:
        if self.project is None or not self.current_module:
            return True
        try:
            value = json.loads(self.editor.get("1.0", tk.END))
            if not isinstance(value, dict):
                raise StudioError("Das Werkzeug erwartet ein JSON-Objekt")
            amended = deepcopy(self.project)
            amended["modules"][self.current_module] = value
            validate_project(amended)
        except (ValueError, StudioError) as exc:
            messagebox.showerror("Ungültiger Werkzeug-Entwurf", str(exc), parent=self.root)
            return False
        self.project = amended
        return True

    def _on_module_select(self, _event) -> None:
        if self._changing:
            return
        selected = self.module_list.curselection()
        if not selected:
            return
        module_id, title, summary = MODULES[selected[0]]
        if self.project is None:
            return
        if not self._collect_module():
            # Keep the current editor to avoid losing unsaved input.
            self._changing = True
            self.module_list.selection_clear(0, tk.END)
            self.module_list.selection_set(next(
                index for index, row in enumerate(MODULES)
                if row[0] == self.current_module
            ))
            self._changing = False
            return
        self.current_module = module_id
        self.section_title.set(title)
        self.section_summary.set(summary + " · JSON prüfen und als neue Revision speichern.")
        self._set_editor(json.dumps(
            self.project["modules"][module_id], ensure_ascii=False,
            indent=2, sort_keys=True,
        ) + "\n")

    def open_workspace(self, directory: Path, source: str | None = None) -> None:
        if self.workspace is not None and not self.confirm_saved("dem Projektwechsel"):
            return
        try:
            if source is None:
                project, digest, source = load_current_project(directory)
            else:
                project, digest = load_project(directory, source)
        except (StudioError, OSError) as exc:
            messagebox.showerror("Projekt nicht lesbar", str(exc), parent=self.root)
            return
        self.workspace = canonical_root(directory)
        self.project = project
        self._saved_project = deepcopy(project)
        self.source_path = source
        self.source_sha = digest
        self.current_module = ""
        self.info.set(
            f"{self.project['project_id']} | Revision {self.project['revision']} "
            f"| {self.workspace} | Datei {self.source_path}"
        )
        self._changing = True
        self.module_list.selection_clear(0, tk.END)
        self.module_list.selection_set(0)
        self._changing = False
        self._on_module_select(None)
        self.status.set("Projekt validiert. Gameplay-Adapter nicht installiert.")

    def choose_workspace(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.root, title="SpriteSuite-Projektdatei auswählen",
            filetypes=[("Projekt-JSON", "*.json")],
        )
        if not path:
            return
        selected = Path(path).absolute()
        if selected.name == PROJECT_FILENAME:
            self.open_workspace(selected.parent, PROJECT_FILENAME)
        else:
            # Revision documents live below the same workspace.
            root = selected.parent.parent if selected.parent.name == "revisions" else selected.parent
            self.open_workspace(root, selected.relative_to(root).as_posix())

    def create_workspace(self) -> None:
        parent = filedialog.askdirectory(parent=self.root, title="Übergeordneten Arbeitsordner auswählen")
        if not parent:
            return
        ident = simpledialog.askstring("Projekt-ID", "Kleinbuchstaben, Zahlen, _ oder -", parent=self.root)
        if not ident:
            return
        title = simpledialog.askstring("Projekttitel", "Bezeichnung des neuen Modprojekts", parent=self.root)
        if not title:
            return
        folder = Path(parent) / ident
        try:
            new_project(folder, ident, title)
        except (StudioError, OSError) as exc:
            messagebox.showerror("Projekt konnte nicht erstellt werden", str(exc), parent=self.root)
            return
        self.open_workspace(folder)

    def run_check(self) -> None:
        if self.project is None or self.workspace is None or not self._collect_module():
            return
        try:
            result = analyze(self.workspace, self.project)
        except (StudioError, OSError) as exc:
            messagebox.showerror("Analyse nicht möglich", str(exc), parent=self.root)
            return
        self.results.delete(*self.results.get_children())
        for module, block in result["modules"].items():
            if not block["findings"]:
                self.results.insert("", tk.END, values=(module, block["status"], "-", "Keine offenen Befunde"))
            for issue in block["findings"]:
                self.results.insert("", tk.END, values=(
                    module, issue["severity"], issue["code"], issue["message"],
                ))
        self.status.set(
            f"Source review: {result['status']}. Ingame-Kompatibilität nicht nachgewiesen."
        )

    def save_revision(self) -> bool:
        if self.project is None or self.workspace is None or not self._collect_module():
            return False
        try:
            original, actual = load_project(self.workspace, self.source_path)
            amended = deepcopy(self.project)
            amended["revision"] = original["revision"] + 1
            path = next_revision(
                self.workspace, original, amended, self.source_sha,
                self.source_path,
            )
        except (StudioError, OSError) as exc:
            messagebox.showerror("Speichern abgebrochen", str(exc), parent=self.root)
            return False
        self.project = amended
        self._saved_project = deepcopy(amended)
        self.source_path = path.relative_to(self.workspace).as_posix()
        self.source_sha = file_sha(self.workspace, self.source_path)
        self.info.set(
            f"{amended['project_id']} | Revision {amended['revision']} | "
            f"{self.workspace} | Datei {self.source_path}"
        )
        self.status.set("Neue Revision gesichert, ursprüngliches Projekt erhalten.")
        return True

    def export(self) -> None:
        if self.project is None or self.workspace is None or not self._collect_module():
            return
        name = simpledialog.askstring(
            "Offline Export", "Neue eindeutige Export-ID:", parent=self.root
        )
        if not name:
            return
        try:
            path, _ = export_project(self.workspace, self.project, name)
        except (StudioError, OSError) as exc:
            messagebox.showerror("Export nicht möglich", str(exc), parent=self.root)
            return
        self.last_export = path
        self.status.set("Offline-Export erstellt: " + str(path))
        if messagebox.askyesno("Export erstellt", "HTML-Prüfbericht öffnen?", parent=self.root):
            webbrowser.open((path / "index.html").as_uri())

    def simulate(self) -> None:
        if self.project is None or self.workspace is None or not self._collect_module():
            return
        selected = filedialog.askopenfilename(
            parent=self.root, title="Eventlog-JSON aus dem Projekt öffnen",
            initialdir=str(self.workspace), filetypes=[("JSON", "*.json")],
        )
        if not selected:
            return
        try:
            relative = Path(selected).relative_to(self.workspace).as_posix()
            timeline = read_json(self.workspace, relative)
            simulation = simulate_mission(self.project["modules"]["mission"], timeline)
        except (StudioError, OSError, ValueError) as exc:
            messagebox.showerror("Dry-Run abgebrochen", str(exc), parent=self.root)
            return
        self._document_window("Mission-Dry-Run – keine Änderungen am Spiel",
                              json.dumps(simulation, indent=2, ensure_ascii=False))

    def preview(self) -> None:
        """Visual authoring/diagnostic view, not game-quality rendering."""
        if self.project is None or self.workspace is None or not self._collect_module():
            return
        if self.current_module == "castle":
            return self._preview_castle()
        if self.current_module == "units":
            return self._preview_routes()
        result = analyze(self.workspace, self.project, only=self.current_module)
        self._document_window("Offline-Vorschau: " + self.current_module,
                              json.dumps(result, ensure_ascii=False, indent=2))

    def _preview_castle(self) -> None:
        from .design import castle
        win = tk.Toplevel(self.root)
        win.title("KI-Burgen-Entwurf – Raster, kein AIVPlacement-Nachweis")
        canvas = self._preview_canvas(win, 520, 520)
        label = ttk.Label(
            win, text="Doppelklick: neues Gebäude im JSON-Entwurf hinzufügen. "
                      "Verschieben/Rotation über die Werkzeugdaten; "
                      "nicht mit Original-AIV-/Spielkollisionen gleichsetzen.",
            wraplength=540,
        )
        label.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 8))
        win.bind("<Configure>", lambda event: label.configure(
            wraplength=max(100, event.width - 24)) if event.widget == win else None)
        def redraw():
            canvas.delete("all")
            section = self.project["modules"]["castle"]
            size = section["grid_size"]
            scale = 520.0 / size
            canvas.configure(width=round(scale * size), height=round(scale * size))
            for at in range(0, size + 1, max(1, size // 20)):
                position = at * scale
                canvas.create_line(position, 0, position, size * scale,
                                   fill="#394351")
                canvas.create_line(0, position, size * scale, position,
                                   fill="#394351")
            outcome = castle(section)
            for index, item in enumerate(outcome.facts.get("elements", [])):
                color = ("#6b9cb6", "#daa86d", "#91bd8c", "#af87bc")[index % 4]
                x0 = item["x"] * scale
                y0 = item["y"] * scale
                x1 = x0 + item["width"] * scale
                y1 = y0 + item["height"] * scale
                canvas.create_rectangle(x0, y0, x1, y1, fill=color,
                                        outline="#e1e5ed", width=1)
                if (x1 - x0) >= 34:
                    canvas.create_text((x0 + x1) / 2, (y0 + y1) / 2,
                                       text=item["id"][:12], fill="#111821",
                                       font=("Segoe UI", 8, "bold"))
            if outcome.status == "BLOCKED":
                label.configure(text="BLOCK: " + "; ".join(
                    finding.message for finding in outcome.findings
                    if finding.severity == "BLOCK"
                )[:360])
        def add(event):
            from .design import castle as validate_castle
            section = deepcopy(self.project["modules"]["castle"])
            size = section["grid_size"]
            scale = 520.0 / size
            x = min(size - 1, max(0, int(event.x // scale)))
            y = min(size - 1, max(0, int(event.y // scale)))
            ident = simpledialog.askstring("Gebäude-ID", "Neue eindeutige ID:", parent=win)
            if not ident:
                return
            kind = simpledialog.askstring("Gebäudetyp", "Typ-ID:", parent=win)
            if not kind:
                return
            width = simpledialog.askinteger("Breite", "Breite in Rasterzellen:",
                                            minvalue=1, maxvalue=size, parent=win)
            if not width:
                return
            height = simpledialog.askinteger("Höhe", "Höhe in Rasterzellen:",
                                             minvalue=1, maxvalue=size, parent=win)
            if not height:
                return
            section["buildings"].append({
                "id": ident, "kind": kind, "x": x, "y": y,
                "width": width, "height": height,
                "rotation": 0, "step": len(section["buildings"]),
            })
            next_project = deepcopy(self.project)
            next_project["modules"]["castle"] = section
            try:
                validate_project(next_project)
                decision = validate_castle(section)
                if decision.status == "BLOCKED":
                    raise StudioError("; ".join(
                        item.message for item in decision.findings
                        if item.severity == "BLOCK"
                    )[:300])
            except (StudioError, ValueError) as exc:
                messagebox.showerror("Bauplatz abgelehnt", str(exc), parent=win)
                return
            self.project = next_project
            if self.current_module == "castle":
                self._set_editor(json.dumps(
                    section, ensure_ascii=False, sort_keys=True, indent=2
                ) + "\n")
            redraw()
        canvas.bind("<Double-Button-1>", add)
        redraw()

    def _preview_routes(self) -> None:
        from .runtime import units
        report = units(self.project["modules"]["units"])
        win = tk.Toplevel(self.root)
        win.title("Wegfindung – synthetischer A*-Simulator, keine Vanilla-Route")
        grid = self.project["modules"]["units"]["grid"]
        width, height = grid["width"], grid["height"]
        scale = min(520 / width, 520 / height)
        canvas = self._preview_canvas(win, round(width * scale), round(height * scale))
        for entry in grid["blocked"]:
            x, y = entry
            canvas.create_rectangle(
                x * scale, y * scale, (x + 1) * scale, (y + 1) * scale,
                fill="#b35c5c", outline="",
            )
        for entry in grid["penalties"]:
            x, y = entry["x"], entry["y"]
            canvas.create_rectangle(
                x * scale, y * scale, (x + 1) * scale, (y + 1) * scale,
                fill="#c2a063", outline="",
            )
        for index, route in enumerate(report.facts.get("routes", [])):
            coordinates = route["path"]
            if len(coordinates) > 1:
                flattened = [
                    value for x, y in coordinates
                    for value in ((x + 0.5) * scale, (y + 0.5) * scale)
                ]
                canvas.create_line(
                    *flattened, fill=("#83d0d0", "#b9a0e3")[index % 2],
                    width=max(2, scale / 6), arrow=tk.LAST,
                )
        label = ttk.Label(
            win, text="Rot: blockiert · Gold: Zusatzkosten · Linien: "
                      "synthetische A*-Vorschau. Keine Spielgeschwindigkeit "
                      "oder Vanilla-Kollisionsregel.",
            wraplength=540,
        )
        label.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 8))
        win.bind("<Configure>", lambda event: label.configure(
            wraplength=max(100, event.width - 24)) if event.widget == win else None)

    def audit_suite(self) -> None:
        try:
            result = analyze_suite_ui(PROJECT_REPOSITORY)
        except (StudioError, OSError) as exc:
            messagebox.showerror("Suite-XAML-Audit", str(exc), parent=self.root)
            return
        self.status.set(
            "UI BC7: 128 Einträge, 14 Wandbilder, "
            f"{result['wall_referenced_count']} XAML-Referenzen, "
            f"{len(result['missing_wall_refs'])} ohne Beleg"
        )
        messagebox.showinfo(
            "Suite-XAML-Audit (nur Quellstand)",
            "\n".join(result["missing_wall_refs"]) or "Keine fehlende statische Referenz",
            parent=self.root,
        )

    def open_native(self) -> None:
        folder = filedialog.askdirectory(
            parent=self.root, title="Lokale Serp Native-Baseline auswählen"
        )
        if not folder:
            return
        query = simpledialog.askstring(
            "Native-Wissen", "Suchbegriff, RVA, Owner oder Claim-ID:",
            parent=self.root,
        )
        if query is None:
            return
        try:
            result = search_native_baseline(Path(folder), query, 50)
        except (StudioError, OSError) as exc:
            messagebox.showerror("Nativewissenssuche nicht möglich", str(exc), parent=self.root)
            return
        self._document_window("Native Baseline – schreibgeschützte Quellfundstellen",
                              json.dumps(result, ensure_ascii=False, indent=2))

    def open_sdk(self) -> None:
        win = tk.Toplevel(self.root)
        win.title("SpriteSuite – APIShared 0.27.0 SDK Explorer")
        win.geometry("950x650")
        win.columnconfigure(0, weight=1)
        win.rowconfigure(1, weight=1)
        entry = ttk.Entry(win, style="Studio.TEntry")
        entry.grid(row=0, column=0, sticky="ew", padx=12, pady=8)
        frame, display, _, _ = self._scrollable_text(
            win, font=("Consolas", 10), wrap=tk.NONE)
        frame.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 8))
        def refresh(*_args):
            rows = search(entry.get())
            display.config(state=tk.NORMAL)
            display.delete("1.0", tk.END)
            for row in rows:
                display.insert(tk.END, (
                    f"{row['module']} : {row['key']} · API >= {row['minimum_api_shared']}\n"
                    f"Thread: {row['threading']} · Mode: {row['mode']}\n"
                    f"{row['note']}\n{row['source']}\n\n"
                ))
            display.config(state=tk.DISABLED)
        entry.bind("<KeyRelease>", refresh)
        refresh()
        def local_api():
            folder = filedialog.askdirectory(
                parent=win, title="Lokalen APIShared-Quellstand auswählen"
            )
            if not folder:
                return
            try:
                found = search_api_surface(Path(folder), entry.get() or "APIShared", 100)
            except (StudioError, OSError) as exc:
                messagebox.showerror("API-Baseline nicht verfügbar", str(exc), parent=win)
                return
            display.config(state=tk.NORMAL)
            display.delete("1.0", tk.END)
            display.insert("1.0", json.dumps(found, indent=2, ensure_ascii=False))
            display.config(state=tk.DISABLED)
        ttk.Button(
            win, text="Lokale APIShared-PublicApi.txt vergleichen",
            command=local_api,
        ).grid(row=2, column=0, sticky="w", padx=12, pady=(0, 8))

def launch(workspace: Path | None = None) -> int:
    try:
        from suite_tcl_runtime import create_tk_root
        root = create_tk_root()
    except tk.TclError as exc:
        raise StudioError("no usable Tk display is available") from exc
    StudioWindow(root, workspace)
    root.mainloop()
    return 0

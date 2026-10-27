"""Stronghold Europe Modding-Suite — grafische Oberfläche für alle Werkzeuge.

Startet ohne Konsolenfenster (.pyw). Aus dem Projektverzeichnis:

    .venv\\Scripts\\pythonw.exe tools/suite.pyw

Die Suite ist bewusst eine Hülle um die Kommandozeilenwerkzeuge, nicht ein
zweiter Satz Logik. Jede Schaltfläche startet dasselbe Skript, das man auch von
Hand aufrufen würde, und zeigt dessen Ausgabe wörtlich an. Das hat einen Grund:
Die Werkzeuge tragen die Prüfungen, die verhindern, dass ein falsch platzierter
Frame ausgeliefert wird. Eine Oberfläche, die daneben ihre eigenen Wege ginge,
könnte diese Prüfungen umgehen, ohne dass es jemand bemerkt.

Was hier hinzukommt, ist Übersicht: welche Gruppen es gibt, was fehlt, was ein
Handgriff bewirken würde — und die Bildvorschau, die auf der Kommandozeile
naturgemäß fehlt.
"""

from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
PYTHON = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
TOOLS = PROJECT_ROOT / "tools"
FROZEN_APP = bool(getattr(sys, "frozen", False))

# Colours chosen for long sessions in front of the thing, not for novelty.
BG = "#1e1f22"
PANEL = "#2b2d31"
FG = "#e8e6e3"
MUTED = "#9a9a9a"
ACCENT = "#c8a35a"
OK = "#7dbd6a"
WARN = "#d98c4a"
BAD = "#d16a6a"


def runner_command(args: list[str]) -> list[str]:
    """Use the project venv in source mode and this EXE as tool host when frozen."""

    if FROZEN_APP:
        return [sys.executable, "--tool-run", *args]
    return [str(PYTHON), *args]


class Runner:
    """Runs a tool in a thread and streams its output into a queue.

    Nothing in the interface blocks on a build: a full pin run takes half an
    hour, and a frozen window during that time would be indistinguishable from
    a crash.
    """

    def __init__(self, sink: queue.Queue):
        self.sink = sink
        self.process: subprocess.Popen | None = None
        self.thread: threading.Thread | None = None
        # Thread completion and GUI acknowledgement are separate events.
        # Without a pending-completion gate, the next job may start BEFORE
        # _drain() invokes the hooks of the previous job, causing a new
        # build/import callback to receive the older task's exit code.
        self._completion_pending = False

    @property
    def busy(self) -> bool:
        return self._completion_pending or (
            self.thread is not None and self.thread.is_alive()
        )

    def acknowledge_completion(self) -> None:
        """The Tk event loop has consumed the previous job's final result."""
        self._completion_pending = False

    def start(self, args: list[str], label: str, capture: bool = False) -> bool:
        """Startet ein Werkzeug; höchstens eines zur Zeit.

        ``capture`` ist der Datenerwerb-Modus: die Ausgabe wird nicht Zeile
        für Zeile in die Konsole gespiegelt, sondern gesammelt und als ein
        Ereignis ``("captured", (code, text))`` geliefert — für
        ``sprites.py list --json``, dessen JSON in der Konsole nur Rauschen
        wäre. Es bleibt derselbe eine Prozess, dieselbe Sperre und derselbe
        Abbrechen-Knopf; die Aktions-Knöpfe streamen weiterhin wörtlich.
        """
        if self.busy:
            return False
        self._completion_pending = True
        self.sink.put(("start", label))

        def work() -> None:
            collected: list[str] | None = [] if capture else None
            try:
                self.process = subprocess.Popen(
                    runner_command(args),
                    cwd=str(PROJECT_ROOT),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                    creationflags=(
                        getattr(subprocess, "CREATE_NO_WINDOW", 0)
                        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                    ),
                )
                assert self.process.stdout is not None
                for line in self.process.stdout:
                    if collected is not None:
                        collected.append(line)
                    else:
                        self.sink.put(("line", line.rstrip("\n")))
                code = self.process.wait()
                if collected is not None:
                    self.sink.put(("captured", (code, "".join(collected))))
                self.sink.put(("done", code))
            except Exception as exc:  # pragma: no cover - surfaced in the UI
                self.sink.put(("line", f"Fehler beim Start: {exc}"))
                if collected is not None:
                    self.sink.put(("captured", (-1, "")))
                self.sink.put(("done", -1))
            finally:
                self.process = None

        self.thread = threading.Thread(target=work, daemon=True)
        try:
            self.thread.start()
        except BaseException:
            self._completion_pending = False
            raise
        return True

    def stop(self) -> None:
        process = self.process
        if process is not None and process.poll() is None:
            if os.name == "nt":
                try:
                    # The frozen host and several tools spawn their own Python
                    # or build processes. Killing only the immediate child
                    # leaves those writers running after the GUI says
                    # "abgebrochen". taskkill is invoked without a shell and
                    # targets exactly this process tree.
                    subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        check=False,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=10,
                    )
                    return
                except (OSError, subprocess.SubprocessError):
                    pass
            process.terminate()


class ImagePreview(ttk.Frame):
    """Large, zoomable PNG view with a transparency checkerboard.

    This is deliberately a viewer only. It never saves, flattens or changes an
    image; all write paths continue to go through the checked command-line
    tools. Keeping it here makes the visual decision available without hiding
    a second conversion implementation in the GUI.
    """

    ZOOMS = ("Einpassen", "100 %", "200 %", "400 %")

    def __init__(self, parent, *, empty_text: str = "Noch kein Bild geladen.") -> None:
        super().__init__(parent)
        self.path: Path | None = None
        self._photo = None
        self._render_key = None
        self._job = None
        self._empty_text = empty_text

        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(3, 4))
        self.title = ttk.Label(bar, text=empty_text, style="Head.TLabel")
        self.title.pack(side="left", padx=(4, 8))
        self.zoom = ttk.Combobox(
            bar, values=self.ZOOMS, state="readonly", width=11
        )
        self.zoom.current(0)
        self.zoom.pack(side="right", padx=(4, 3))
        self.zoom.bind("<<ComboboxSelected>>", lambda _event: self.redraw(force=True))
        ttk.Label(bar, text="Zoom:", style="Muted.TLabel").pack(side="right")
        ttk.Button(bar, text="Extern öffnen", command=self.open_external).pack(
            side="right", padx=6
        )

        self.detail = ttk.Label(
            self, text="", style="Muted.TLabel", justify="left", wraplength=900
        )
        self.detail.pack(fill="x", padx=4, pady=(0, 4))

        holder = ttk.Frame(self)
        holder.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(
            holder, bg="#25272b", highlightthickness=1, highlightbackground="#3a3d43"
        )
        xbar = ttk.Scrollbar(holder, orient="horizontal", command=self.canvas.xview)
        ybar = ttk.Scrollbar(holder, command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=xbar.set, yscrollcommand=ybar.set)
        ybar.pack(side="right", fill="y")
        xbar.pack(side="bottom", fill="x")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Configure>", self._resized)
        self.canvas.bind("<Double-Button-1>", lambda _event: self.open_external())
        self.clear(empty_text)

    def clear(self, message: str | None = None) -> None:
        self.path = None
        self._photo = None
        self._render_key = None
        self.title.configure(text=message or self._empty_text)
        self.detail.configure(text="")
        self.canvas.delete("all")
        self.canvas.create_text(
            18, 18, anchor="nw", text=message or self._empty_text,
            fill=MUTED, font=("Segoe UI", 10),
        )
        self.canvas.configure(scrollregion=(0, 0, 1, 1))

    def show(self, path: Path, *, title: str = "", detail: str = "") -> None:
        path = path.resolve()
        if not path.is_file():
            self.clear(f"Bild fehlt: {path.name}")
            self.detail.configure(text=str(path))
            return
        self.path = path
        self.title.configure(text=title or path.name)
        self.detail.configure(text=detail)
        self._render_key = None
        self.redraw(force=True)

    def _resized(self, _event=None) -> None:
        if self.zoom.get() != "Einpassen" or self.path is None:
            return
        if self._job is not None:
            self.after_cancel(self._job)
        self._job = self.after(100, self.redraw)

    def _scale(self, source: tuple[int, int], viewport: tuple[int, int]) -> float:
        selected = self.zoom.get()
        if selected != "Einpassen":
            return float(selected.split()[0]) / 100.0
        width, height = source
        available_w = max(32, viewport[0] - 24)
        available_h = max(32, viewport[1] - 24)
        # Small sprites should still be inspectable; large buildings shrink to
        # the viewport. Fourfold enlargement preserves crisp nearest-neighbour
        # pixels without turning one 1px texel into an entire screen.
        return max(0.02, min(4.0, available_w / width, available_h / height))

    def redraw(self, force: bool = False) -> None:
        self._job = None
        path = self.path
        if path is None:
            return
        try:
            from PIL import Image, ImageTk

            with Image.open(path) as opened:
                picture = opened.convert("RGBA")
            # Tk reports 1x1 while a notebook page is not currently selected.
            # Still decode and retain the preview so the image appears on the
            # first visit instead of requiring a resize event to wake it up.
            viewport = (
                max(320, self.canvas.winfo_width()),
                max(240, self.canvas.winfo_height()),
            )
            scale = self._scale(picture.size, viewport)
            rendered_size = (
                max(1, round(picture.width * scale)),
                max(1, round(picture.height * scale)),
            )
            key = (path, path.stat().st_mtime_ns, rendered_size, viewport, self.zoom.get())
            if not force and key == self._render_key and self._photo is not None:
                return
            if rendered_size != picture.size:
                picture = picture.resize(rendered_size, Image.Resampling.NEAREST)
            self._photo = ImageTk.PhotoImage(picture)
        except Exception as exc:
            self.clear(f"Bild nicht lesbar: {path.name}")
            self.detail.configure(text=str(exc))
            return

        fit = self.zoom.get() == "Einpassen"
        x = max(12, (viewport[0] - rendered_size[0]) // 2) if fit else 12
        y = max(12, (viewport[1] - rendered_size[1]) // 2) if fit else 12
        self.canvas.delete("all")
        square = 16
        for top in range(y, y + rendered_size[1], square):
            for left in range(x, x + rendered_size[0], square):
                colour = "#d2d2d2" if ((left - x) // square + (top - y) // square) % 2 == 0 else "#a9a9a9"
                self.canvas.create_rectangle(
                    left, top,
                    min(left + square, x + rendered_size[0]),
                    min(top + square, y + rendered_size[1]),
                    fill=colour, outline=colour,
                )
        self.canvas.create_image(x, y, anchor="nw", image=self._photo)
        extent_w = max(viewport[0], x + rendered_size[0] + 12)
        extent_h = max(viewport[1], y + rendered_size[1] + 12)
        self.canvas.configure(scrollregion=(0, 0, extent_w, extent_h))
        self._render_key = key

    def open_external(self) -> None:
        if self.path is None:
            return
        try:
            os.startfile(str(self.path))  # noqa: S606 - user's selected PNG
        except Exception as exc:
            messagebox.showinfo("Nicht geöffnet", f"{self.path}\n\n{exc}")


class Suite(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        from stronghold_europe_de.workspace_lock import WorkspaceLock, WorkspaceLockError, lock_path

        self._instance_lock = WorkspaceLock(
            lock_path(PROJECT_ROOT / "work", "modding-suite-instance"),
            "Modding-Suite",
        )
        try:
            self._instance_lock.acquire()
        except WorkspaceLockError as exc:
            messagebox.showerror(
                "Modding-Suite läuft bereits",
                f"{exc}.\n\nBitte das bereits geöffnete Fenster verwenden.",
            )
            self.destroy()
            raise SystemExit(2) from exc
        self.title("Stronghold Europe — Modding-Suite")
        self.geometry("1280x860")
        self.minsize(1020, 680)
        self.configure(bg=BG)
        self.protocol("WM_DELETE_WINDOW", self._close)

        self.events: queue.Queue = queue.Queue()
        self.runner = Runner(self.events)
        # Empfänger einer gesammelten Ausgabe (run_captured) und die Reiter,
        # die nach jedem beendeten Vorgang nachladen wollen (die Werkstatt
        # liest den Export-Ordner erst, wenn das Werkzeug fertig ist).
        self._capture_sink = None
        self._capture_error = None
        self.done_hooks: list = []

        self._build_style()
        self._build_layout()
        self.after(80, self._drain)
        self.refresh_status()

    def sprite_profile_path(self) -> str:
        """Profile receiving sprite edits; the suite center supplies its selection."""
        return "profiles/europe-production.json"

    def _close(self) -> None:
        if self.runner.busy and not messagebox.askyesno(
            "Vorgang läuft",
            "Ein Werkzeug läuft noch. Wirklich abbrechen und die Anwendung schließen?",
        ):
            return
        # Do not terminate a running build or release the single-instance
        # lock until the embedded Sandbox has accepted its own unsaved edits.
        # Universal.destroy() can legitimately decline the closing request.
        self.destroy()

    def destroy(self) -> None:
        """Stop jobs, cancel old Tk timers, and release lock on committed close.

        Delayed Tk callbacks are stored in the Tcl event queue separately
        from their Python commands. Destroying widgets deletes the commands,
        but leaving after() events queued caused the NEXT Suite session in
        the same Python interpreter to raise Tcl 'invalid command name'
        (_drain / load / async polls). All pending callbacks belong to this
        closing root, so cancel them before destroying child widgets.
        """
        runner = getattr(self, "runner", None)
        if runner is not None and runner.busy:
            runner.stop()
        try:
            for ident in self.tk.call("after", "info"):
                # Use the Tcl event ID directly. Misc.after_cancel() also
                # deletes Python command registrations, and it may be called
                # here on a child widget's ID not owned by the Tk root.
                self.tk.call("after", "cancel", ident)
        except tk.TclError:
            # A root already destroyed during partially failed startup has
            # no usable Tcl event queue to clean up.
            pass
        instance_lock = getattr(self, "_instance_lock", None)
        if instance_lock is not None:
            instance_lock.release()
        super().destroy()

    # ---------------------------------------------------------------- layout

    def _build_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure(
            "TNotebook.Tab",
            background=PANEL,
            foreground=MUTED,
            padding=(16, 8),
            borderwidth=0,
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", BG)],
            foreground=[("selected", ACCENT)],
        )
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("TPanedwindow", background=BG)
        style.configure("TLabel", background=BG, foreground=FG)
        style.configure("Muted.TLabel", background=BG, foreground=MUTED)
        style.configure("Head.TLabel", background=BG, foreground=ACCENT,
                        font=("Segoe UI", 11, "bold"))
        style.configure("Title.TLabel", background=BG, foreground=FG,
                        font=("Segoe UI", 19, "bold"))
        style.configure("Step.TLabel", background=BG, foreground=ACCENT,
                        font=("Segoe UI", 13, "bold"))
        style.configure("TButton", background=PANEL, foreground=FG,
                        borderwidth=0, padding=(12, 7))
        style.map("TButton", background=[("active", "#3a3d43")])
        style.configure("Treeview", background=PANEL, fieldbackground=PANEL,
                        foreground=FG, borderwidth=0, rowheight=22)
        style.configure("Treeview.Heading", background=BG, foreground=MUTED,
                        borderwidth=0)
        style.map("Treeview", background=[("selected", "#3f4248")])

    def _build_layout(self) -> None:
        header = ttk.Frame(self)
        header.pack(fill="x", padx=14, pady=(12, 6))
        ttk.Label(header, text="Stronghold Europe", style="Head.TLabel").pack(side="left")
        ttk.Label(
            header,
            text="EXE" if FROZEN_APP else "Python-Arbeitsmodus",
            style="Muted.TLabel",
        ).pack(side="left", padx=(12, 0))
        self.status_label = ttk.Label(header, text="", style="Muted.TLabel")
        self.status_label.pack(side="left", padx=16)
        self.stop_button = ttk.Button(header, text="Abbrechen", command=self.runner.stop)
        self.stop_button.pack(side="right")
        self.stop_button.state(["disabled"])

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=14, pady=(0, 6))

        self.tab_groups = GroupsTab(self.notebook, self)
        self.tab_art = ArtTab(self.notebook, self)
        self.tab_ui = UiTab(self.notebook, self)
        self.tab_text = TextTab(self.notebook, self)
        self.tab_build = BuildTab(self.notebook, self)
        self.tab_home = HomeTab(self.notebook, self)
        for tab, name in (
            (self.tab_home, "Start & Anleitung"),
            (self.tab_groups, "Sprite-Gruppen"),
            (self.tab_art, "Grafik-Werkstatt"),
            (self.tab_ui, "Oberfläche"),
            (self.tab_text, "Texte"),
            (self.tab_build, "Bauen und Installieren"),
        ):
            self.notebook.add(tab, text=name)

        console_frame = ttk.Frame(self)
        console_frame.pack(fill="both", padx=14, pady=(0, 12))
        ttk.Label(console_frame, text="Ausgabe", style="Muted.TLabel").pack(anchor="w")
        self.console = tk.Text(
            console_frame, height=11, bg=PANEL, fg=FG, insertbackground=FG,
            relief="flat", wrap="none", font=("Consolas", 9),
        )
        self.console.pack(fill="both", expand=True, side="left")
        scroll = ttk.Scrollbar(console_frame, command=self.console.yview)
        scroll.pack(side="right", fill="y")
        self.console.configure(yscrollcommand=scroll.set)
        for tag, colour in (("ok", OK), ("warn", WARN), ("bad", BAD),
                            ("head", ACCENT), ("muted", MUTED)):
            self.console.tag_configure(tag, foreground=colour)

    def open_tab(self, tab) -> None:
        self.notebook.select(tab)

    # ----------------------------------------------------------------- plumbing

    def run(self, args: list[str], label: str) -> bool:
        """True only after the worker actually accepted this specific job."""
        if not self.runner.start(args, label):
            messagebox.showinfo(
                "Läuft bereits",
                "Es läuft schon ein Vorgang. Bitte abwarten oder abbrechen.",
            )
            return False
        self.stop_button.state(["!disabled"])
        return True

    def run_captured(self, args: list[str], label: str, on_output) -> None:
        """Datenerwerb: die gesammelte Ausgabe geht an on_output(code, text).

        Nur für ``sprites.py list --json``. Alles, was etwas tut oder prüft,
        läuft über ``run`` und erscheint wörtlich in der Konsole — sonst
        könnte eine Ablehnung des Werkzeugs unbemerkt in einem Rückgabewert
        verschwinden. Dieselbe Sperre wie ``run``: eine Aktion zur Zeit.
        """
        if self.runner.busy or not self.runner.start(args, label, capture=True):
            messagebox.showinfo(
                "Läuft bereits",
                "Es läuft schon ein Vorgang. Bitte abwarten oder abbrechen.",
            )
            return False
        self._capture_sink = on_output
        self._capture_error = None
        self.stop_button.state(["!disabled"])
        return True

    def log(self, text: str, tag: str = "") -> None:
        self.console.insert("end", text + "\n", tag)
        self.console.see("end")

    def _drain(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "start":
                    self.log(f"$ {payload}", "head")
                    self.status_label.configure(text=f"läuft: {payload}")
                elif kind == "line":
                    text = str(payload)
                    tag = ""
                    lowered = text.lower()
                    if "fehler" in lowered or "error" in lowered or "FAIL" in text:
                        tag = "bad"
                    elif "erfolgreich" in lowered or "ok" in lowered.split():
                        tag = "ok"
                    elif text.startswith("  ") or text.startswith("==="):
                        tag = "muted"
                    self.log(text, tag)
                elif kind == "captured":
                    sink, self._capture_sink = self._capture_sink, None
                    code, text = payload
                    if sink is not None:
                        try:
                            sink(int(code), str(text))
                        except Exception as exc:
                            # A malformed sprites --json response used to
                            # abort _drain() before scheduling the next poll.
                            # Treat parsing failure as a failed acquisition,
                            # never as authorization for a follow-on task.
                            self._capture_error = (
                                f"{type(exc).__name__}: {exc}"
                            )
                            self.log(
                                f"Werkzeugantwort nicht auswertbar: "
                                f"{self._capture_error}",
                                "bad",
                            )
                elif kind == "done":
                    # Let the completion hooks start the *next* job only
                    # after this specific job's final GUI event is handled.
                    self.runner.acknowledge_completion()
                    code = int(payload)
                    capture_error = getattr(self, "_capture_error", None)
                    self._capture_error = None
                    if capture_error:
                        # The subprocess can exit zero while the captured
                        # JSON is invalid. Downstream success-hooks must see
                        # a failure, not the unparsed program exit status.
                        if code == 0:
                            code = 1
                        self.log(
                            "Datenerwerb fehlgeschlagen; "
                            "Folgeaktion nicht freigegeben: " + capture_error,
                            "bad",
                        )
                    self.log(
                        "fertig" if code == 0 else f"beendet mit Code {code}",
                        "ok" if code == 0 else "bad",
                    )
                    self.status_label.configure(text="")
                    self.stop_button.state(["disabled"])
                    self.refresh_status()
                    for hook in list(self.done_hooks):
                        try:
                            hook(code)
                        except Exception as exc:
                            # A broken GUI refresh or extension callback
                            # must not stop Tk's event drain: otherwise the
                            # entire Suite appears frozen after one tool.
                            if hook in self.done_hooks:
                                self.done_hooks.remove(hook)
                            self.log(
                                f"Abschlussanzeige fehlgeschlagen "
                                f"({type(exc).__name__}): {exc}",
                                "bad",
                            )
        except queue.Empty:
            pass
        self.after(80, self._drain)

    def refresh_status(self) -> None:
        """Read the profile directly. Cheap, and always current."""

        try:
            profile = json.loads(
                (PROJECT_ROOT / "profiles" / "europe-production.json").read_text(
                    encoding="utf-8"
                )
            )
        except Exception:
            return
        atlases = profile.get("gm_atlases", [])
        frames = sum(int(a.get("expected_frame_count", 0)) for a in atlases)
        self.tab_groups.set_summary(len(atlases), frames)
        self.tab_home.refresh(profile, len(atlases), frames)


class HomeTab(ttk.Frame):
    """Guided entry point: status first, then the shortest safe workflow."""

    def __init__(self, parent, app: Suite):
        super().__init__(parent)
        self.app = app
        from suite_usability import ScrollableColumn
        self.guide_scroll = ScrollableColumn(self, background=BG)
        self.guide_scroll.pack(fill="both", expand=True)
        page = self.guide_scroll.body

        ttk.Label(page, text="Was möchtest du mit Sprite Suite machen?", style="Title.TLabel").pack(
            anchor="w", padx=10, pady=(10, 3)
        )
        ttk.Label(
            page,
            text=(
                "Starte mit einem Ziel – die folgenden Wege öffnen die passenden "
                "Werkzeuge, ohne selbst Dateien zu verändern. Alle Spezialfunktionen "
                "bleiben über die Bereichsauswahl oder Strg+K erreichbar. "
                "Eine Installation erfolgt erst nach ausdrücklicher Bestätigung."
            ),
            style="Muted.TLabel",
            wraplength=860,
            justify="left",
        ).pack(anchor="w", padx=10, pady=(0, 8))

        # On a normal 1020px screen two simultaneous columns squeezed the
        # five workflow buttons and truncated the long readiness messages.
        # Give each task the full width, as in the embedded Sandbox Studio.
        self.guide_sections = ttk.Notebook(page)
        self.guide_sections.pack(
            fill="both", expand=True, padx=10, pady=(0, 8)
        )
        workflow = ttk.Frame(self.guide_sections)
        readiness = ttk.Frame(self.guide_sections)
        self.guide_sections.add(workflow, text="Schritt für Schritt")
        self.guide_sections.add(readiness, text="Projektbereitschaft")

        ttk.Label(workflow, text="Wähle deine Aufgabe", style="Head.TLabel").pack(anchor="w")
        # Destination attributes are resolved *on click*: the standalone
        # Workshop constructs HomeTab before Universal creates its modern
        # catalogue/sandbox/build pages. Never trigger actions on display.
        steps = (
            ("1", "Spiele und Werkzeuge einrichten",
             "Ordner prüfen, Originalgrafiken einlesen und vorhandene Quellen wählen.",
             "setup_page"),
            ("2", "Sprite im Asset-Katalog finden",
             "Gruppen, Frames, Arbeitskopien und Spenderbilder vergleichen.",
             "catalog_tab"),
            ("3", "Sprite auf der Spielkarte testen",
             "In der integrierten Sandbox platzieren, animieren und Pixel prüfen.",
             "sandbox_tab"),
            ("4", "Bilder oder mehrteilige Objekte bearbeiten",
             "Pixeleditor, OpenRaster und AtlasBuilder nutzen; Rückweg kontrollieren.",
             "exchange_tab"),
            ("5", "Grafik und Projekt diagnostizieren",
             "Anker, Frame-Drift, Mapping, Abbilder und Sicherheitsnachweise prüfen.",
             "diagnose_tab"),
            ("6", "Paket bauen und unabhängig validieren",
             "BC7-Erstellung und Prüfergebnisse vor jeder Auslieferung ansehen.",
             "bc7_page"),
            ("7", "Freigegebenen Stand installieren",
             "Zielspiel auswählen, Sicherung prüfen und Installation bestätigen.",
             "target_tab"),
        )
        for number, title, detail, destination in steps:
            row = ttk.Frame(workflow)
            # Show all seven essential actions above the fold at the Suite's
            # supported 1020x680 minimum. Long copy remains vertically
            # scrollable in smaller accessibility/high-DPI environments.
            row.pack(fill="x", pady=(5, 1))
            ttk.Label(row, text=number, style="Step.TLabel", width=3).pack(side="left", anchor="n")
            copy = ttk.Frame(row)
            copy.pack(side="left", fill="x", expand=True)
            ttk.Label(copy, text=title, style="Head.TLabel").pack(anchor="w")
            ttk.Label(
                copy, text=detail, style="Muted.TLabel", wraplength=560, justify="left"
            ).pack(anchor="w")
            ttk.Button(
                row, text="Öffnen",
                command=lambda name=destination: self.open_workflow(name)
            ).pack(side="right", padx=6)

        quick = ttk.Frame(workflow)
        quick.pack(fill="x", pady=(9, 4))
        ttk.Button(quick, text="Umgebung vollständig prüfen", command=self.doctor).pack(side="left", padx=(0, 6))
        ttk.Button(quick, text="Anleitung öffnen", command=self.open_manual).pack(side="left", padx=6)

        ttk.Label(readiness, text="Projektbereitschaft", style="Head.TLabel").pack(anchor="w")
        self.readiness = ttk.Treeview(
            readiness, columns=("state", "detail"), show="headings", height=8
        )
        self.readiness.heading("state", text="Status")
        self.readiness.heading("detail", text="Prüfpunkt")
        self.readiness.column("state", width=72, anchor="center", stretch=False)
        self.readiness.column("detail", width=360, anchor="w")
        self.readiness.tag_configure("ok", foreground=OK)
        self.readiness.tag_configure("warn", foreground=WARN)
        self.readiness.pack(fill="x", pady=(7, 10))

        self.profile_summary = ttk.Label(
            readiness, text="Profil wird gelesen …", style="Muted.TLabel",
            wraplength=440, justify="left",
        )
        self.profile_summary.pack(anchor="w", pady=(0, 12))

        ttk.Label(readiness, text="Sicherheitsmodell", style="Head.TLabel").pack(anchor="w")
        ttk.Label(
            readiness,
            text=(
                "• Exporte überschreiben Arbeitsordner nur nach Rückfrage.\n"
                "• Bildgrößen und Tile-Ebenen werden abgelehnt statt skaliert.\n"
                "• Bauen und Validieren verändern die Spielinstallation nicht.\n"
                "• Installieren und Deinstallieren verlangen eine eigene Bestätigung."
            ),
            style="Muted.TLabel",
            wraplength=440,
            justify="left",
        ).pack(anchor="w", pady=(6, 0))
        self.guide_scroll.bind_mousewheel()

    def open_workflow(self, destination: str) -> None:
        """Go to a workspace without accidentally running a build/import."""
        target = getattr(self.app, destination, None)
        if target is None:
            # Old standalone Workshop has no Universal catalogue or sandbox.
            fallback = (
                self.app.tab_build if destination in ("bc7_page", "target_tab")
                else self.app.tab_art
            )
            target = fallback
        self.app.open_tab(target)

    def doctor(self) -> None:
        self.app.run(
            ["-m", "stronghold_europe_de", "doctor", "--config", "config/installations.local.toml"],
            "doctor: Installationen und Projektpfade prüfen",
        )

    def open_manual(self) -> None:
        path = PROJECT_ROOT / "docs" / "MODDING_APP.md"
        try:
            os.startfile(str(path))  # noqa: S606 - own project documentation
        except Exception as exc:
            messagebox.showinfo("Nicht geöffnet", f"{path}\n\n{exc}")

    def refresh(self, profile: dict, atlas_count: int, frame_count: int) -> None:
        from stronghold_europe_de.workspace_lock import stale_transaction_artifacts

        interrupted = stale_transaction_artifacts(PROJECT_ROOT)
        checks = (
            (FROZEN_APP or PYTHON.is_file(), "Laufzeit", "EXE eingebettet" if FROZEN_APP else ".venv verfügbar"),
            ((PROJECT_ROOT / "config" / "installations.local.toml").is_file(), "Installationen", "lokale Konfiguration"),
            ((PROJECT_ROOT / "work" / "mapping" / "proposals.json.gz").is_file(), "Mapping", "Sprite-Zuordnung vorhanden"),
            ((PROJECT_ROOT / "profiles" / "europe-production.json").is_file(), "Profil", "europe-production"),
            ((PROJECT_ROOT / "dist" / "europe-production").is_dir(), "Build", "Ausgabe vorhanden"),
            ((PROJECT_ROOT / "state" / "install-manifest.json").is_file(), "Installation", "Manifest vorhanden"),
            (
                not interrupted,
                "Transaktionen",
                "keine unterbrochene Ablage"
                if not interrupted
                else f"{len(interrupted)} aktive/unterbrochene Spur(en): {interrupted[0]}",
            ),
        )
        self.readiness.delete(*self.readiness.get_children())
        for okay, title, detail in checks:
            self.readiness.insert(
                "", "end", values=("OK" if okay else "offen", f"{title}: {detail}"),
                tags=("ok" if okay else "warn",),
            )
        authored = profile.get("authored_sprites", [])
        authored_ui = profile.get("authored_ui_atlases", [])
        self.profile_summary.configure(
            text=(
                f"Aktives Produktionsprofil: {atlas_count} GM-Atlanten mit "
                f"{frame_count} Ziel-Frames; {len(authored) if isinstance(authored, list) else 0} "
                "Einzelgrafik-Sätze; "
                f"{len(authored_ui) if isinstance(authored_ui, list) else 0} UI-Blätter. "
                "Für verbindliche Aussagen immer „Prüfen“ im "
                "Build-Reiter ausführen."
            )
        )


class GroupsTab(ttk.Frame):
    """Which sprite groups ship, which do not, and what one click would change."""

    def __init__(self, parent, app: Suite):
        super().__init__(parent)
        self.app = app

        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(10, 6))
        self.summary = ttk.Label(bar, text="", style="Muted.TLabel")
        self.summary.pack(side="left", padx=(4, 0))
        ttk.Button(bar, text="Übersicht", command=self.show_status).pack(side="right", padx=3)
        ttk.Button(bar, text="Fehlende auflisten", command=self.list_missing).pack(side="right", padx=3)

        add = ttk.Frame(self)
        add.pack(fill="x", pady=6)
        ttk.Label(add, text="Gruppen aufnehmen:", style="Muted.TLabel").pack(side="left", padx=(4, 8))
        self.entry = tk.Entry(add, bg=PANEL, fg=FG, insertbackground=FG, relief="flat")
        self.entry.pack(side="left", fill="x", expand=True, ipady=4)
        ttk.Button(add, text="Hinzufügen", command=self.add_named).pack(side="left", padx=3)
        ttk.Button(add, text="Alle vollständigen", command=self.add_all).pack(side="left", padx=3)

        note = (
            "Aufrecht ist der Standard: Türme, Bäume und Einheiten behalten ihren eigenen "
            "Fußpunkt. Nur für Bodenkacheln ist die Ausrichtung auf den Crusader-Anker richtig — "
            "bei der Kiefer liegen beide 44 Pixel auseinander."
        )
        ttk.Label(self, text=note, style="Muted.TLabel", wraplength=1080,
                  justify="left").pack(anchor="w", padx=4, pady=(2, 8))

        policy = ttk.Frame(self)
        policy.pack(fill="x", pady=(0, 8))
        ttk.Label(policy, text="Geometrie umstellen:", style="Muted.TLabel").pack(side="left", padx=(4, 8))
        self.policy_entry = tk.Entry(policy, bg=PANEL, fg=FG, insertbackground=FG, relief="flat")
        self.policy_entry.pack(side="left", fill="x", expand=True, ipady=4)
        ttk.Button(policy, text="aufrecht", command=lambda: self.set_policy("--upright")).pack(side="left", padx=3)
        ttk.Button(policy, text="flach", command=lambda: self.set_policy("--flat")).pack(side="left", padx=3)

    def set_summary(self, count: int, frames: int) -> None:
        self.summary.configure(text=f"{count} Gruppen im Profil, {frames:,} Frames".replace(",", "."))

    def show_status(self) -> None:
        self.app.run([str(TOOLS / "groups.py"), "status"], "groups.py status")

    def list_missing(self) -> None:
        self.app.run([str(TOOLS / "groups.py"), "list", "--missing"], "groups.py list --missing")

    def add_named(self) -> None:
        names = self.entry.get().split()
        if not names:
            messagebox.showinfo("Keine Gruppe", "Bitte einen oder mehrere Gruppennamen eingeben.")
            return
        self.app.run([str(TOOLS / "groups.py"), "add", *names], f"groups.py add {' '.join(names)}")

    def add_all(self) -> None:
        if not messagebox.askyesno(
            "Alle vollständigen Gruppen",
            "Nimmt jede Gruppe auf, für die Stronghold 1 einen lückenlosen Spender hat.\n\n"
            "Danach müssen die Platzierungsnachweise vermessen werden — das kann "
            "eine halbe Stunde dauern.\n\nFortfahren?",
        ):
            return
        self.app.run([str(TOOLS / "groups.py"), "add", "--all-complete"], "groups.py add --all-complete")

    def set_policy(self, flag: str) -> None:
        names = self.policy_entry.get().split()
        if not names:
            messagebox.showinfo("Keine Gruppe", "Bitte einen oder mehrere Gruppennamen eingeben.")
            return
        self.app.run(
            [str(TOOLS / "groups.py"), "policy", *names, flag],
            f"groups.py policy {' '.join(names)} {flag}",
        )


class ArtTab(ttk.Frame):
    """Grafik-Werkstatt: Gruppen sichten, exportieren, ansehen, zurückführen.

    Links die Gruppenliste (aus ``sprites.py list --json``), rechts Miniaturen,
    Übersichtstafeln und die Regeln, darunter der Rückweg: prüfen, in eine
    Ablage übernehmen, ins Profil eintragen. Jedes Urteil — Leinwand, Maske,
    Digest, Profil — fällt ``sprites.py``; die Werkstatt zeigt an, ruft auf und
    hält die Bildverweise, die tkinter sonst wegräumt.
    """

    # Wie sprites.py export --game, in derselben Reihenfolge; delivered ist
    # dort der Standard und deshalb auch hier.
    SOURCES = ("delivered", "crusader", "stronghold1")
    PAGE = 96
    # Der Farbcode der Tafeln (sprites.py sheet): grün = Stronghold 1,
    # orange = Crusader. Alles andere (etwa "erzeugt") grau.
    TINT = {
        "stronghold1": "#56964a",
        "crusader": "#c47a34",
        "installed-atlas": "#4c84cd",
        "installed-sprite": "#955dd6",
    }
    TINT_OTHER = "#6e6e6e"

    def __init__(self, parent, app: Suite):
        super().__init__(parent)
        self.app = app
        self._groups: list[dict] = []
        self._stores: list[dict] = []
        self._loaded = False
        self._index: dict | None = None
        self._frames: list[dict] = []
        self._page = 0
        self._preview_index = 0
        self._photos: list = []
        self._cells: list = []
        self._columns = 0
        self._gen = 0
        self._sheets: list[Path] = []
        self._sheet_index = 0
        self._sheet_photo = None
        self._sheet_job = None
        self._sheet_size = (0, 0)
        self._store_rows: list[dict] = []
        self._reload_on_done = False
        self._load_folder_after_run: str | None = None
        self._tile_preview_after_run = False
        try:
            preset_doc = json.loads(
                (PROJECT_ROOT / "config" / "tile-object-presets.json").read_text(
                    encoding="utf-8"
                )
            )
            self._tile_presets = [
                entry for entry in preset_doc.get("presets", []) if isinstance(entry, dict)
            ]
        except Exception:
            self._tile_presets = []

        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(10, 4))
        ttk.Label(bar, text="Gruppe:", style="Muted.TLabel").pack(side="left", padx=(4, 8))
        self.group = tk.Entry(bar, bg=PANEL, fg=FG, insertbackground=FG, relief="flat", width=26)
        self.group.pack(side="left", ipady=4)
        self.source = tk.StringVar(value=self.SOURCES[0])
        for value, text in zip(
            self.SOURCES,
            ("installierte Mod (exakt)", "aus Crusader", "aus Stronghold 1"),
        ):
            ttk.Radiobutton(bar, text=text, variable=self.source, value=value).pack(
                side="left", padx=(10, 0)
            )
        ttk.Button(bar, text="Exportieren", command=self.export).pack(side="left", padx=(12, 3))
        ttk.Button(bar, text="Aktualisieren", command=self.refresh_list).pack(side="right", padx=3)

        # Erzeuger für Plätze ohne Spender: die Knöpfe rufen nur das Werkzeug,
        # die Sichtprüfung des Übersichtsblatts bleibt Handarbeit — deshalb landet
        # der Ordner danach im Ordner-Feld des Rückwegs, nicht in einer Ablage.
        gen = ttk.Frame(self)
        gen.pack(fill="x", pady=(0, 4))
        ttk.Label(gen, text="Aus Stronghold-1-Pflanzen erzeugen:", style="Muted.TLabel").pack(side="left", padx=(4, 8))
        ttk.Button(gen, text="Kakteen → Sträucher (17)", command=self.gen_cactii).pack(side="left", padx=3)
        ttk.Button(gen, text="Birken-Entwurf (148, nicht lieferbar)", command=self.gen_birch).pack(side="left", padx=3)

        body = ttk.PanedWindow(self, orient="horizontal")
        body.pack(fill="both", expand=True, padx=4, pady=(0, 6))
        left = ttk.Frame(body)
        right = ttk.Frame(body)
        body.add(left, weight=0)
        body.add(right, weight=1)

        # ---- links: die Gruppenliste
        filt = ttk.Frame(left)
        filt.pack(fill="x", pady=(0, 4))
        ttk.Label(filt, text="Filter:", style="Muted.TLabel").pack(side="left", padx=(0, 6))
        self.filter = tk.Entry(filt, bg=PANEL, fg=FG, insertbackground=FG, relief="flat")
        self.filter.pack(side="left", fill="x", expand=True, ipady=3)
        self.filter.bind("<KeyRelease>", lambda _e: self._populate_tree())
        columns = ("group", "frames", "mask", "loadable", "store")
        self.tree = ttk.Treeview(left, columns=columns, show="headings", selectmode="browse")
        for key, head, width, anchor in (
            ("group", "Gruppe", 150, "w"),
            ("frames", "Frames", 52, "e"),
            ("mask", "Maske", 46, "center"),
            ("loadable", "ladbar", 52, "center"),
            ("store", "Ablage", 120, "w"),
        ):
            self.tree.heading(key, text=head)
            self.tree.column(key, width=width, minwidth=40, anchor=anchor, stretch=(key == "store"))
        self.tree.tag_configure("shared", foreground=MUTED)
        scroll = ttk.Scrollbar(left, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.insert("", "end", values=("(Aktualisieren drücken)", "", "", "", ""), tags=("shared",))

        # ---- rechts: Ansichten, Objektmontage und darunter der Rückweg
        self.pages = ttk.Notebook(right)
        self.pages.pack(fill="both", expand=True)
        self.page_preview = ttk.Frame(self.pages)
        self.page_thumbs = ttk.Frame(self.pages)
        self.page_sheets = ttk.Frame(self.pages)
        self.page_tiles = ttk.Frame(self.pages)
        self.page_rules = ttk.Frame(self.pages)
        self.page_return = ttk.Frame(self.pages)
        self.pages.add(self.page_preview, text="Bildvorschau")
        self.pages.add(self.page_thumbs, text="Miniaturen")
        self.pages.add(self.page_sheets, text="Tafeln")
        self.pages.add(self.page_tiles, text="Tile-Objekt")
        self.pages.add(self.page_return, text="Rückweg")
        self.pages.add(self.page_rules, text="Regeln")
        self._build_preview(self.page_preview)
        self._build_thumbs(self.page_thumbs)
        self._build_sheets(self.page_sheets)
        self._build_tiles(self.page_tiles)
        self._build_rules(self.page_rules)
        self._build_return(self.page_return)

        app.done_hooks.append(self._after_run)
        # Beim ersten Anzeigen des Reiters die Liste holen — aber nie während
        # ein anderer Vorgang läuft: eine Aktion zur Zeit, das gilt auch hier.
        app.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed, add="+")

    # ------------------------------------------------------------ Seitenbau

    def _build_preview(self, page: ttk.Frame) -> None:
        nav = ttk.Frame(page)
        nav.pack(fill="x", pady=(6, 2))
        ttk.Button(nav, text="◀ Frame", command=lambda: self._turn_preview(-1)).pack(
            side="left", padx=(4, 2)
        )
        ttk.Button(nav, text="Frame ▶", command=lambda: self._turn_preview(1)).pack(
            side="left", padx=2
        )
        self.preview_counter = ttk.Label(nav, text="Kein Frame", style="Muted.TLabel")
        self.preview_counter.pack(side="left", padx=8)
        ttk.Label(nav, text="Ansicht:", style="Muted.TLabel").pack(
            side="right", padx=(6, 3)
        )
        self.preview_kind = ttk.Combobox(
            nav, values=("Farbbild", "Teammaske"), state="readonly", width=13
        )
        self.preview_kind.current(0)
        self.preview_kind.pack(side="right", padx=(3, 4))
        self.preview_kind.bind(
            "<<ComboboxSelected>>", lambda _event: self._show_selected_frame()
        )
        self.sprite_preview = ImagePreview(
            page,
            empty_text="Gruppe exportieren oder vorhandenen Export laden – dann erscheint hier das Bild.",
        )
        self.sprite_preview.pack(fill="both", expand=True, padx=4, pady=(0, 4))

    def _build_thumbs(self, page: ttk.Frame) -> None:
        nav = ttk.Frame(page)
        nav.pack(fill="x", pady=(6, 4))
        ttk.Button(nav, text="◀", width=3, command=lambda: self._turn(-1)).pack(side="left", padx=(4, 2))
        self.page_label = ttk.Label(nav, text="Kein Ordner geladen.", style="Muted.TLabel")
        self.page_label.pack(side="left", padx=6)
        ttk.Button(nav, text="▶", width=3, command=lambda: self._turn(1)).pack(side="left", padx=2)
        ttk.Label(nav, text="Größe:", style="Muted.TLabel").pack(side="left", padx=(16, 4))
        self.cell_size = ttk.Combobox(nav, values=("64", "96", "144"), state="readonly", width=5)
        self.cell_size.current(1)
        self.cell_size.pack(side="left")
        self.cell_size.bind("<<ComboboxSelected>>", lambda _e: self._render_page())
        self.gallery_hint = ttk.Label(nav, text="", style="Muted.TLabel")
        self.gallery_hint.pack(side="right", padx=6)

        holder = ttk.Frame(page)
        holder.pack(fill="both", expand=True)
        self.gallery = tk.Canvas(holder, bg=BG, highlightthickness=0)
        self.gallery.pack(side="left", fill="both", expand=True)
        gscroll = ttk.Scrollbar(holder, command=self.gallery.yview)
        gscroll.pack(side="right", fill="y")
        self.gallery.configure(yscrollcommand=gscroll.set)
        self.gallery_inner = tk.Frame(self.gallery, bg=BG)
        self.gallery.create_window((0, 0), window=self.gallery_inner, anchor="nw")
        self.gallery.bind("<Configure>", self._reflow)
        for widget in (self.gallery, self.gallery_inner):
            widget.bind("<MouseWheel>", self._wheel)

    def _build_sheets(self, page: ttk.Frame) -> None:
        nav = ttk.Frame(page)
        nav.pack(fill="x", pady=(6, 4))
        ttk.Button(nav, text="◀", width=3, command=lambda: self._turn_sheet(-1)).pack(side="left", padx=(4, 2))
        self.sheet_label = ttk.Label(nav, text="Keine Tafel.", style="Muted.TLabel")
        self.sheet_label.pack(side="left", padx=6)
        ttk.Button(nav, text="▶", width=3, command=lambda: self._turn_sheet(1)).pack(side="left", padx=2)
        self.sheet_full = tk.BooleanVar(value=False)
        ttk.Checkbutton(nav, text="1:1", variable=self.sheet_full, command=self._show_sheet).pack(side="left", padx=(12, 2))
        ttk.Button(nav, text="Öffnen", command=self._open_sheet).pack(side="left", padx=2)
        ttk.Button(nav, text="Tafeln bauen", command=self.build_sheets).pack(side="right", padx=(2, 4))
        self.sheet_to = tk.Entry(nav, bg=PANEL, fg=FG, insertbackground=FG, relief="flat", width=6)
        self.sheet_to.pack(side="right", ipady=3)
        ttk.Label(nav, text="bis", style="Muted.TLabel").pack(side="right", padx=4)
        self.sheet_from = tk.Entry(nav, bg=PANEL, fg=FG, insertbackground=FG, relief="flat", width=6)
        self.sheet_from.pack(side="right", ipady=3)
        ttk.Label(nav, text="Frames von", style="Muted.TLabel").pack(side="right", padx=4)

        holder = ttk.Frame(page)
        holder.pack(fill="both", expand=True)
        self.sheet_canvas = tk.Canvas(holder, bg=BG, highlightthickness=0)
        ybar = ttk.Scrollbar(holder, command=self.sheet_canvas.yview)
        xbar = ttk.Scrollbar(holder, orient="horizontal", command=self.sheet_canvas.xview)
        self.sheet_canvas.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
        ybar.pack(side="right", fill="y")
        xbar.pack(side="bottom", fill="x")
        self.sheet_canvas.pack(side="left", fill="both", expand=True)
        self.sheet_canvas.bind("<Configure>", self._sheet_resized)

    def _build_rules(self, page: ttk.Frame) -> None:
        text = tk.Text(
            page, wrap="word", bg=PANEL, fg=FG, relief="flat",
            font=("Segoe UI", 9), padx=10, pady=8,
        )
        text.pack(fill="both", expand=True, padx=4, pady=(6, 4))
        text.insert("1.0", RULES_TEXT)
        text.configure(state="disabled")

    def _build_tiles(self, page: ttk.Frame) -> None:
        intro = (
            "Gebäude liegen als überlappende optische Tiles vor. Dieser Weg setzt "
            "einen zusammenhängenden Frameblock über die nativen 32×16-Anker zu "
            "einer OpenRaster-Datei zusammen: ein benanntes Tile je Ebene. Nur so "
            "kann der Rückweg die Grafik ohne erratenes Zerschneiden wieder aufteilen."
        )
        ttk.Label(
            page, text=intro, style="Muted.TLabel", wraplength=760, justify="left"
        ).pack(anchor="w", padx=8, pady=(10, 8))

        preset_row = ttk.Frame(page)
        preset_row.pack(fill="x", padx=8, pady=3)
        ttk.Label(preset_row, text="Geprüftes Objekt-Raster:", style="Muted.TLabel").pack(
            side="left"
        )
        self.tile_preset = ttk.Combobox(
            preset_row,
            values=["(benutzerdefiniert)"]
            + [str(entry.get("label", entry.get("id", ""))) for entry in self._tile_presets],
            state="readonly",
            width=42,
        )
        self.tile_preset.current(0)
        self.tile_preset.pack(side="left", padx=6)
        self.tile_preset.bind("<<ComboboxSelected>>", self._tile_apply_preset)
        ttk.Label(
            preset_row,
            text="Presets fixieren Frameblock, Raster und Rotation gemeinsam.",
            style="Muted.TLabel",
        ).pack(side="left", padx=6)

        frame_row = ttk.Frame(page)
        frame_row.pack(fill="x", padx=8, pady=3)
        ttk.Label(frame_row, text="Frames von", style="Muted.TLabel").pack(side="left")
        self.tile_from = tk.Entry(
            frame_row, bg=PANEL, fg=FG, insertbackground=FG, relief="flat", width=7
        )
        self.tile_from.pack(side="left", padx=(6, 3), ipady=3)
        ttk.Label(frame_row, text="bis", style="Muted.TLabel").pack(side="left", padx=3)
        self.tile_to = tk.Entry(
            frame_row, bg=PANEL, fg=FG, insertbackground=FG, relief="flat", width=7
        )
        self.tile_to.pack(side="left", padx=3, ipady=3)
        ttk.Label(frame_row, text="Spalten", style="Muted.TLabel").pack(side="left", padx=(14, 3))
        self.tile_columns = tk.Entry(
            frame_row, bg=PANEL, fg=FG, insertbackground=FG, relief="flat", width=5
        )
        self.tile_columns.pack(side="left", padx=3, ipady=3)
        ttk.Label(frame_row, text="Zeilen", style="Muted.TLabel").pack(side="left", padx=(8, 3))
        self.tile_rows = tk.Entry(
            frame_row, bg=PANEL, fg=FG, insertbackground=FG, relief="flat", width=5
        )
        self.tile_rows.pack(side="left", padx=3, ipady=3)
        ttk.Label(frame_row, text="Anordnung", style="Muted.TLabel").pack(side="left", padx=(14, 3))
        self.tile_layout = ttk.Combobox(
            frame_row,
            values=(
                "row-major", "row-major-flip-x", "row-major-flip-y",
                "row-major-rotate-180", "column-major", "column-major-flip-x",
                "column-major-flip-y", "column-major-rotate-180",
            ),
            state="readonly",
            width=24,
        )
        self.tile_layout.current(0)
        self.tile_layout.pack(side="left", padx=3)

        source_row = ttk.Frame(page)
        source_row.pack(fill="x", padx=8, pady=3)
        ttk.Label(source_row, text="Exportwurzel:", style="Muted.TLabel").pack(side="left")
        self.tile_export_root = tk.Entry(
            source_row, bg=PANEL, fg=FG, insertbackground=FG, relief="flat"
        )
        self.tile_export_root.pack(side="left", fill="x", expand=True, padx=6, ipady=3)
        self.tile_export_root.insert(0, "work/tile-source")
        ttk.Button(
            source_row,
            text="1. Crusader-Bereich exportieren",
            command=self._tile_export_range,
        ).pack(side="right", padx=3)

        package_row = ttk.Frame(page)
        package_row.pack(fill="x", padx=8, pady=3)
        ttk.Label(package_row, text="Objektpaket:", style="Muted.TLabel").pack(side="left")
        self.tile_package = tk.Entry(
            package_row, bg=PANEL, fg=FG, insertbackground=FG, relief="flat"
        )
        self.tile_package.pack(side="left", fill="x", expand=True, padx=6, ipady=3)
        self.tile_package.insert(0, "work/objects/mein-gebaeude")
        self.tile_package.bind("<Return>", lambda _event: self._load_tile_preview())
        ttk.Button(package_row, text="…", width=3, command=self._tile_pick_package).pack(side="left", padx=3)
        ttk.Button(package_row, text="Laden", command=self._load_tile_preview).pack(side="left", padx=3)

        split_row = ttk.Frame(page)
        split_row.pack(fill="x", padx=8, pady=3)
        ttk.Label(split_row, text="Tile-PNG-Ausgabe:", style="Muted.TLabel").pack(side="left")
        self.tile_split_folder = tk.Entry(
            split_row, bg=PANEL, fg=FG, insertbackground=FG, relief="flat"
        )
        self.tile_split_folder.pack(side="left", fill="x", expand=True, padx=6, ipady=3)
        self.tile_split_folder.insert(0, "work/art-return/mein-gebaeude")
        self.tile_replace = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            split_row,
            text="vorhandene Ausgabe atomar ersetzen",
            variable=self.tile_replace,
        ).pack(side="right", padx=3)
        self.tile_confirm_custom = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            split_row,
            text="benutzerdefiniertes Raster nach Vorschau ausdrücklich freigeben",
            variable=self.tile_confirm_custom,
        ).pack(side="right", padx=8)

        actions = ttk.Frame(page)
        actions.pack(fill="x", padx=8, pady=(9, 4))
        ttk.Button(actions, text="2. ORA zusammensetzen", command=self._tile_compose).pack(side="left", padx=3)
        ttk.Button(actions, text="Paket prüfen", command=self._tile_check).pack(side="left", padx=3)
        ttk.Button(actions, text="Aktuelle ORA anzeigen", command=self._tile_render_preview).pack(side="left", padx=3)
        ttk.Button(actions, text="ORA öffnen", command=self._tile_open_ora).pack(side="left", padx=3)
        ttk.Button(actions, text="3. Tile-PNGs erzeugen", command=self._tile_split).pack(side="right", padx=3)

        ttk.Label(
            page,
            text=(
                "Bei einem geprüften Preset sind Frameblock, Rasterplatz und Rotation "
                "gemeinsam festgeschrieben. Bei einem freien Raster muss die aktuelle "
                "Vorschau vor dem Split ausdrücklich bestätigt werden. Zusätzliche Ebenen oder sichtbare Pixel "
                "außerhalb der nativen Tile-Leinwand werden beim Prüfen abgelehnt."
            ),
            style="Muted.TLabel",
            wraplength=760,
            justify="left",
        ).pack(anchor="w", padx=8, pady=(8, 4))

        self.tile_preview = ImagePreview(
            page,
            empty_text="Objektpaket zusammensetzen oder auswählen – die montierte Gebäudeansicht erscheint hier.",
        )
        self.tile_preview.pack(fill="both", expand=True, padx=8, pady=(2, 6))

    def _tile_apply_preset(self, _event=None) -> None:
        position = self.tile_preset.current() - 1
        if position < 0 or position >= len(self._tile_presets):
            return
        preset = self._tile_presets[position]
        self.group.delete(0, "end")
        self.group.insert(0, str(preset.get("group", "")))
        for widget, key in (
            (self.tile_from, "from"),
            (self.tile_to, "to"),
            (self.tile_columns, "columns"),
            (self.tile_rows, "rows"),
        ):
            widget.delete(0, "end")
            widget.insert(0, str(preset.get(key, "")))
        self.tile_layout.set(str(preset.get("layout", "row-major")))
        self.tile_confirm_custom.set(False)

    def _build_return(self, parent: ttk.Frame) -> None:
        panel = ttk.Frame(parent)
        panel.pack(fill="x", pady=(6, 0))
        ttk.Label(panel, text="Rückweg", style="Head.TLabel").pack(anchor="w")

        row = ttk.Frame(panel)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="Ordner:", style="Muted.TLabel").pack(side="left", padx=(0, 6))
        self.folder = tk.Entry(row, bg=PANEL, fg=FG, insertbackground=FG, relief="flat")
        self.folder.pack(side="left", fill="x", expand=True, ipady=4)
        self.folder.bind("<Return>", lambda _e: self.load_folder())
        ttk.Button(row, text="…", width=3, command=self.pick_folder).pack(side="left", padx=3)
        ttk.Button(row, text="Laden", command=self.load_folder).pack(side="left", padx=3)
        ttk.Button(row, text="Prüfen", command=self.check).pack(side="left", padx=3)

        row = ttk.Frame(panel)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="Ablage:", style="Muted.TLabel").pack(side="left", padx=(0, 6))
        self.store_box = ttk.Combobox(row, values=[], state="readonly", width=46)
        self.store_box.pack(side="left")
        self.store_box.bind("<<ComboboxSelected>>", lambda _e: self._update_store_hint())
        ttk.Button(row, text="Import prüfen", command=self.import_check).pack(side="left", padx=(8, 3))
        ttk.Button(row, text="In Ablage übernehmen", command=self.import_apply).pack(side="left", padx=3)

        row = ttk.Frame(panel)
        row.pack(fill="x", pady=2)
        self.store_hint = ttk.Label(row, text="", style="Muted.TLabel")
        self.store_hint.pack(side="left", padx=(0, 8))
        self.allow_atlas_shadow = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            row,
            text="Einzel-PNGs dürfen Gruppenatlas überstimmen",
            variable=self.allow_atlas_shadow,
        ).pack(side="left", padx=4)
        self.profile_button = ttk.Button(
            row, text="Ins Profil eintragen", command=self.profile_write
        )
        self.profile_button.pack(side="right", padx=3)
        ttk.Button(row, text="Profilabschnitt zeigen", command=self.profile_show).pack(side="right", padx=3)

        # Reine Anzeige aus index.json: was das Werkzeug beim Import verlangen
        # wird. Das Urteil fällt ausschließlich sprites.py (authored_foot_check);
        # die Spalte "Fußpunkt" rechnet nur pivot·Maß vor, damit man beim
        # Zeichnen weiß, wo das Bild aufsitzen wird — von links und von UNTEN.
        holder = ttk.Frame(panel)
        holder.pack(fill="x", pady=(4, 0))
        columns = ("frame", "canvas", "foot", "mask")
        self.frame_table = ttk.Treeview(holder, columns=columns, show="headings", height=4)
        for key, head, width, anchor in (
            ("frame", "Frame", 200, "w"),
            ("canvas", "Soll-Leinwand", 100, "center"),
            ("foot", "Fußpunkt px (links / unten)", 170, "center"),
            ("mask", "erwartete Maske", 200, "w"),
        ):
            self.frame_table.heading(key, text=head)
            self.frame_table.column(key, width=width, minwidth=60, anchor=anchor)
        tscroll = ttk.Scrollbar(holder, command=self.frame_table.yview)
        self.frame_table.configure(yscrollcommand=tscroll.set)
        self.frame_table.pack(side="left", fill="x", expand=True)
        tscroll.pack(side="right", fill="y")

    # ---------------------------------------------------------- Gruppenliste

    def _on_tab_changed(self, _event=None) -> None:
        if self._loaded or self.app.runner.busy:
            return
        try:
            shown = self.app.notebook.select() == str(self)
        except tk.TclError:
            return
        if shown:
            self.refresh_list()

    def refresh_list(self) -> None:
        self.app.run_captured(
            [str(TOOLS / "sprites.py"), "list", "--json"], "sprites.py list --json", self._on_list
        )

    def _on_list(self, code: int, text: str) -> None:
        try:
            data = json.loads(text)
            groups = list(data["groups"])
            stores = list(data["stores"])
        except Exception:
            for line in text.splitlines():
                self.app.log(line, "bad")
            self.app.log(f"Gruppenliste nicht lesbar (Code {code}).", "bad")
            return
        self._groups = groups
        self._stores = stores
        self._loaded = True
        self._populate_tree()
        self._refresh_store_box()
        self._fill_table()
        self.app.log(f"{len(groups)} Gruppen, {len(stores)} Ablagen gelesen", "muted")

    def _stores_for(self, group: str) -> list[dict]:
        return [s for s in self._stores if s.get("group") == group]

    def _mask_required(self, group: str):
        for entry in self._groups:
            if entry.get("group") == group:
                return entry.get("mask_required")
        return None

    def _populate_tree(self) -> None:
        needle = self.filter.get().strip().casefold()
        self.tree.delete(*self.tree.get_children())
        for entry in self._groups:
            name = str(entry.get("group", ""))
            if needle and needle not in name.casefold():
                continue
            mask = entry.get("mask_required")
            stores = ", ".join(f"{s['origin']}/{s['set']}" for s in self._stores_for(name))
            self.tree.insert(
                "", "end", iid=name,
                values=(
                    name,
                    entry.get("frames", ""),
                    "-" if mask is None else ("ja" if mask else "nein"),
                    entry.get("loadable", ""),
                    stores,
                ),
                tags=() if entry.get("loadable") == "ja" else ("shared",),
            )

    def _on_select(self, _event=None) -> None:
        selected = self.tree.selection()
        if not selected or not self._loaded:
            return
        name = selected[0]
        self.group.delete(0, "end")
        self.group.insert(0, name)
        self.folder.delete(0, "end")
        self.folder.insert(0, f"work/art/{name}")
        self.load_folder(quiet=True)

    # ------------------------------------------------------------ Aktionen

    def export(self) -> None:
        name = self.group.get().strip()
        if not name:
            messagebox.showinfo("Keine Gruppe", "Bitte eine Gruppe wählen oder eingeben.")
            return
        args = [str(TOOLS / "sprites.py"), "export", name, "--game", self.source.get()]
        target = PROJECT_ROOT / "work" / "art" / name
        if target.is_dir() and any(target.iterdir()):
            if not messagebox.askyesno(
                "Export ersetzen",
                f"Der Exportordner ist nicht leer:\n{target}\n\n"
                "Er kann bearbeitete Grafiken enthalten. Wirklich atomar durch "
                "einen frischen Export ersetzen?",
            ):
                return
            args.append("--replace")
        self.app.run(args, f"sprites.py export {name} --game {self.source.get()}")
        self.folder.delete(0, "end")
        self.folder.insert(0, f"work/art/{name}")
        self._reload_on_done = True

    def gen_cactii(self) -> None:
        self.app.run([str(TOOLS / "vegetation_gen.py"), "cactii"], "vegetation_gen.py cactii")
        self.folder.delete(0, "end")
        self.folder.insert(0, "work/art_gen/tree_cactii")
        self._reload_on_done = True

    def gen_birch(self) -> None:
        # Der Entwurf verlangt das Flag ausdrücklich; die Suite gibt es weiter,
        # das Werkzeug erklärt im Protokoll, warum der Satz nicht lieferbar ist.
        self.app.run(
            [str(TOOLS / "vegetation_gen.py"), "birch", "--entwurf"],
            "vegetation_gen.py birch --entwurf",
        )
        self.folder.delete(0, "end")
        self.folder.insert(0, "work/art_gen/tree_birch")
        self._reload_on_done = True

    def pick_folder(self) -> None:
        chosen = filedialog.askdirectory(initialdir=str(PROJECT_ROOT / "work" / "art"))
        if chosen:
            self.folder.delete(0, "end")
            self.folder.insert(0, chosen)
            self.load_folder()

    def _folder_text(self) -> str:
        return self.folder.get().strip()

    def _folder_path(self) -> Path:
        folder = Path(self._folder_text())
        return folder if folder.is_absolute() else PROJECT_ROOT / folder

    def check(self) -> None:
        folder = self._folder_text()
        if not folder:
            messagebox.showinfo("Kein Ordner", "Bitte einen Ordner wählen.")
            return
        self.app.run([str(TOOLS / "sprites.py"), "check", folder], f"sprites.py check {folder}")

    def build_sheets(self) -> None:
        folder = self._folder_text()
        if not folder:
            messagebox.showinfo("Kein Ordner", "Bitte einen Ordner wählen.")
            return
        args = [str(TOOLS / "sprites.py"), "sheet", folder]
        for flag, entry in (("--from", self.sheet_from), ("--to", self.sheet_to)):
            value = entry.get().strip()
            if value:
                args += [flag, value]
        self.app.run(args, "sprites.py " + " ".join(args[1:]))
        self._reload_on_done = True

    def _selected_store(self) -> dict | None:
        index = self.store_box.current()
        if index < 0 or index >= len(self._store_rows):
            messagebox.showinfo(
                "Keine Ablage",
                "Für diese Gruppe ist keine Lieferablage freigegeben.\n\n"
                "Ablagen werden bewusst im Code freigeschaltet "
                "(_PROJECT_AUTHORED_SPRITE_SETS in mod_builder.py) — siehe Regeln.",
            )
            return None
        return self._store_rows[index]

    def _import_inputs(self) -> tuple[str, dict] | None:
        folder = self._folder_text()
        if not folder:
            messagebox.showinfo("Kein Ordner", "Bitte einen Ordner wählen.")
            return None
        store = self._selected_store()
        if store is None:
            return None
        return folder, store

    def import_check(self) -> None:
        inputs = self._import_inputs()
        if inputs is None:
            return
        folder, store = inputs
        args = [
            str(TOOLS / "sprites.py"), "import", folder,
            "--set", store["set"], "--origin", store["origin"], "--check-only",
        ]
        self.app.run(args, "sprites.py " + " ".join(args[1:]))

    def import_apply(self) -> None:
        inputs = self._import_inputs()
        if inputs is None:
            return
        folder, store = inputs
        if not messagebox.askyesno(
            "In Ablage übernehmen",
            f"Bearbeitete PNGs aus\n    {folder}\nnach\n    {store['store']}\nübernehmen?\n\n"
            "Das Werkzeug prüft je Frame Leinwand und Maske und lehnt ab statt zu "
            "skalieren; unverändert exportierte Frames werden nicht geliefert.",
        ):
            return
        args = [
            str(TOOLS / "sprites.py"), "import", folder,
            "--set", store["set"], "--origin", store["origin"],
        ]
        self.app.run(args, "sprites.py " + " ".join(args[1:]))

    def profile_show(self) -> None:
        store = self._selected_store()
        if store is None:
            return
        args = [
            str(TOOLS / "sprites.py"), "profile-add", store["set"],
            "--origin", store["origin"], "--profile", str(self.app.sprite_profile_path()),
        ]
        if self.allow_atlas_shadow.get():
            args.append("--allow-atlas-shadow")
        self.app.run(args, "sprites.py " + " ".join(args[1:]))

    def profile_write(self) -> None:
        # Die Oberfläche wählt das Profil; das Werkzeug schreibt es frisch
        # eingelesen und atomar ersetzt.
        store = self._selected_store()
        if store is None:
            return
        profile_path = str(self.app.sprite_profile_path())
        if not messagebox.askyesno(
            "Ins Profil eintragen",
            f"Ablage:  {store['store']}\nGruppe:  {store['group']}\n"
            f"Profil:  {profile_path}\n\n"
            "Der Abschnitt wird neu aus der Ablage berechnet und eingetragen; "
            "der Bauer rechnet beide Digests beim Build unabhängig nach.\n"
            f"Atlas-Vorrang überstimmen: {'JA' if self.allow_atlas_shadow.get() else 'nein'}\n\n"
            "Fortfahren?",
        ):
            return
        args = [
            str(TOOLS / "sprites.py"), "profile-add", store["set"],
            "--origin", store["origin"], "--profile", profile_path, "--write",
        ]
        if self.allow_atlas_shadow.get():
            args.append("--allow-atlas-shadow")
        self.app.run(args, "sprites.py " + " ".join(args[1:]))

    def _after_run(self, _code: int) -> None:
        if self._tile_preview_after_run:
            self._tile_preview_after_run = False
            if _code == 0:
                self._load_tile_preview()
        if _code == 0 and self._load_folder_after_run is not None:
            folder = self._load_folder_after_run
            self._load_folder_after_run = None
            self.folder.delete(0, "end")
            self.folder.insert(0, folder)
            self.load_folder(quiet=True)
            return
        self._load_folder_after_run = None
        if self._reload_on_done:
            self._reload_on_done = False
            self.load_folder(quiet=True)

    # ------------------------------------------------------- Ordner laden

    def load_folder(self, quiet: bool = False) -> None:
        folder = self._folder_path()
        self._index = None
        self._frames = []
        self._page = 0
        self._preview_index = 0
        index_path = folder / "index.json"
        if index_path.is_file():
            try:
                self._index = json.loads(index_path.read_text(encoding="utf-8"))
                self._frames = sorted(self._index.get("frames", []), key=self._frame_order)
            except Exception as exc:
                self.app.log(f"index.json nicht lesbar: {exc}", "bad")
                self._index = None
        elif not quiet:
            self.app.log(f"Kein index.json in {folder} — erst exportieren.", "warn")
        if self._index is not None and self._index.get("group"):
            self.group.delete(0, "end")
            self.group.insert(0, str(self._index["group"]))
        self._refresh_store_box()
        self._fill_table()
        self._render_page()
        self._show_selected_frame()
        self._list_sheets(folder)

    # ------------------------------------------------------ Tile-Objektweg

    def _tile_package_text(self) -> str:
        return self.tile_package.get().strip()

    def _tile_package_path(self) -> Path:
        package = Path(self._tile_package_text())
        return package if package.is_absolute() else PROJECT_ROOT / package

    def _tile_pick_package(self) -> None:
        chosen = filedialog.askdirectory(initialdir=str(PROJECT_ROOT / "work" / "objects"))
        if chosen:
            self.tile_package.delete(0, "end")
            self.tile_package.insert(0, chosen)
            self._load_tile_preview()

    def _tile_export_range(self) -> None:
        group = self.group.get().strip()
        start = self.tile_from.get().strip()
        end = self.tile_to.get().strip()
        output_root = self.tile_export_root.get().strip()
        if not group or not output_root or not start or not end:
            messagebox.showinfo(
                "Angaben fehlen",
                "Gruppe, Exportwurzel sowie erster und letzter Frame sind nötig.",
            )
            return
        if not group.startswith("tile_"):
            messagebox.showinfo(
                "Keine Tile-Gruppe",
                f"{group!r} ist keine optische tile_*-Gruppe.",
            )
            return
        try:
            first, last = int(start), int(end)
            if first > last:
                raise ValueError
        except ValueError:
            messagebox.showinfo("Ungültiger Bereich", "Der erste Frame muss höchstens der letzte sein.")
            return
        root = Path(output_root)
        root = root if root.is_absolute() else PROJECT_ROOT / root
        destination = root / group
        replace = destination.is_dir() and any(destination.iterdir())
        if replace and not messagebox.askyesno(
            "Tile-Export ersetzen",
            f"Der Exportordner ist nicht leer:\n{destination}\n\n"
            "Nach Bestätigung baut das Werkzeug zuerst einen vollständigen Ersatz "
            "und tauscht den Ordner anschließend atomar aus.",
        ):
            return
        args = [
            str(TOOLS / "sprites.py"), "export", group,
            "--game", "crusader", "--from", str(first), "--to", str(last),
            "--out", output_root,
        ]
        if replace:
            args.append("--replace")
        self._load_folder_after_run = str(destination)
        self.app.run(args, "sprites.py " + " ".join(args[1:]))

    def _tile_compose(self) -> None:
        values = {
            "--from": self.tile_from.get().strip(),
            "--to": self.tile_to.get().strip(),
            "--columns": self.tile_columns.get().strip(),
            "--rows": self.tile_rows.get().strip(),
        }
        folder = self._folder_text()
        package = self._tile_package_text()
        if not folder or not package or any(not value for value in values.values()):
            messagebox.showinfo(
                "Angaben fehlen",
                "Exportordner, Framebereich, Spalten, Zeilen und Objektpaket sind nötig.",
            )
            return
        args = [str(TOOLS / "tile_objects.py"), "compose", folder]
        preset_position = self.tile_preset.current() - 1
        if 0 <= preset_position < len(self._tile_presets):
            args += ["--preset", str(self._tile_presets[preset_position]["id"])]
        for flag, value in values.items():
            args += [flag, value]
        args += ["--layout", self.tile_layout.get(), "--out", package]
        if self.tile_replace.get():
            args.append("--replace")
        self._tile_preview_after_run = True
        self.app.run(args, "tile_objects.py " + " ".join(args[1:]))

    def _tile_check(self) -> None:
        package = self._tile_package_text()
        if not package:
            messagebox.showinfo("Kein Objektpaket", "Bitte einen Objektpaket-Ordner wählen.")
            return
        self.app.run(
            [str(TOOLS / "tile_objects.py"), "check", package],
            f"tile_objects.py check {package}",
        )

    def _tile_render_preview(self) -> None:
        package = self._tile_package_text()
        if not package:
            messagebox.showinfo("Kein Objektpaket", "Bitte einen Objektpaket-Ordner wählen.")
            return
        self._tile_preview_after_run = True
        self.app.run(
            [str(TOOLS / "tile_objects.py"), "preview", package],
            f"tile_objects.py preview {package}",
        )

    def _load_tile_preview(self) -> None:
        package = self._tile_package_path()
        manifest_path = package / "object.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            frame_range = manifest["frame_range"]
            grid = manifest["grid"]
            canvas = manifest["canvas"]
            semantic = manifest.get("semantic", {})
            semantic_text = (
                f"Preset {semantic.get('preset_id')}"
                if semantic.get("status") == "verified-preset"
                else "freies Raster (vor Split bestätigen)"
            )
            current = package / "object-current-preview.png"
            baseline = package / str(manifest["preview"])
            path = current if current.is_file() else baseline
            state = "aktueller ORA-Stand" if path == current else "Ausgang nach dem Zusammensetzen"
            detail = (
                f"{manifest['group']} · Frames {frame_range['from']}–{frame_range['to']} · "
                f"{grid['columns']}×{grid['rows']} Tiles · {grid['layout']} · "
                f"{canvas['width']}×{canvas['height']} px · {semantic_text} · {state}"
            )
        except Exception as exc:
            self.tile_preview.clear("Kein lesbares Tile-Objektpaket.")
            self.tile_preview.detail.configure(text=f"{manifest_path}\n{exc}")
            return
        self.tile_preview.show(path, title=str(manifest.get("name", package.name)), detail=detail)

    def _tile_open_ora(self) -> None:
        package = self._tile_package_path()
        files = sorted(package.glob("*.ora")) if package.is_dir() else []
        if not files:
            messagebox.showinfo("Keine ORA", f"Keine .ora-Datei in\n{package}")
            return
        self._open(files[0])

    def _tile_split(self) -> None:
        package = self._tile_package_text()
        destination = self.tile_split_folder.get().strip()
        if not package or not destination:
            messagebox.showinfo(
                "Angaben fehlen", "Objektpaket und Tile-PNG-Ausgabe sind nötig."
            )
            return
        args = [
            str(TOOLS / "tile_objects.py"), "split", package, "--out", destination
        ]
        if self.tile_confirm_custom.get():
            args.append("--confirm-custom-layout")
        if self.tile_replace.get():
            args.append("--replace")
        self._load_folder_after_run = destination
        self.app.run(args, "tile_objects.py " + " ".join(args[1:]))

    @staticmethod
    def _frame_order(entry: dict) -> tuple:
        # Anzeigereihenfolge wie bei den Tafeln: nach der Endnummer, nicht als Text.
        match = re.search(r"(\d+)\s*$", str(entry.get("name", "")))
        return (0, int(match.group(1))) if match else (1, str(entry.get("name", "")))

    def _refresh_store_box(self) -> None:
        group = self.group.get().strip()
        self._store_rows = self._stores_for(group) if group else []
        self.store_box.configure(values=[row["store"] for row in self._store_rows])
        if self._store_rows:
            self.store_box.current(0)
        else:
            self.store_box.set("")
        self._update_store_hint()

    def _update_store_hint(self) -> None:
        index = self.store_box.current()
        if not self._loaded:
            self.store_hint.configure(text="Freigaben unbekannt — Aktualisieren drücken.")
        elif index < 0 or index >= len(self._store_rows):
            self.store_hint.configure(text="Keine freigegebene Ablage für diese Gruppe.")
        else:
            row = self._store_rows[index]
            self.store_hint.configure(
                text=f"Herkunft: {row['origin']} · Gruppe: {row['group']} · Ablage: {row['set']}"
            )

    def _fill_table(self) -> None:
        self.frame_table.delete(*self.frame_table.get_children())
        if self._index is None:
            return
        group = str(self._index.get("group", ""))
        mask_required = self._mask_required(group)
        for entry in self._frames:
            target = entry.get("crusader")
            name = str(entry.get("name", ""))
            if isinstance(target, dict):
                width, height = int(target["width"]), int(target["height"])
                foot = (
                    f"{float(target['pivot_x']) * width:.2f} / "
                    f"{float(target['pivot_y']) * height:.2f}"
                )
                canvas = f"{width}×{height}"
            else:
                canvas, foot = "-", "-"
            if mask_required is None:
                mask = "? (Liste aktualisieren)"
            elif mask_required:
                mask = f"{name}_m.png"
            else:
                mask = "keine (plain_shader)"
            self.frame_table.insert("", "end", values=(name, canvas, foot, mask))

    # ---------------------------------------------------------- Miniaturen

    def _turn_preview(self, step: int) -> None:
        if not self._frames:
            return
        self._preview_index = max(
            0, min(len(self._frames) - 1, self._preview_index + step)
        )
        self._show_selected_frame()

    def _select_frame(self, entry: dict) -> None:
        try:
            self._preview_index = self._frames.index(entry)
        except ValueError:
            return
        self._show_selected_frame()
        self.pages.select(self.page_preview)

    def _show_selected_frame(self) -> None:
        if not self._frames:
            self.preview_counter.configure(text="Kein Frame")
            self.sprite_preview.clear(
                "Gruppe exportieren oder vorhandenen Export laden – dann erscheint hier das Bild."
            )
            return
        self._preview_index = max(0, min(len(self._frames) - 1, self._preview_index))
        entry = self._frames[self._preview_index]
        folder = self._folder_path()
        main_path = folder / str(entry.get("file", ""))
        mask_name = entry.get("mask_file")
        if not mask_name:
            mask_name = Path(str(entry.get("file", ""))).with_suffix("").name + "_m.png"
        mask_path = folder / str(mask_name)
        wants_mask = self.preview_kind.get() == "Teammaske"
        path = mask_path if wants_mask else main_path
        target = entry.get("crusader") if isinstance(entry.get("crusader"), dict) else {}
        source = str(entry.get("shown_from", "unbekannt"))
        canvas = (
            f"{int(float(target['width']))}×{int(float(target['height']))} px"
            if target else "keine Crusader-Geometrie"
        )
        detail = (
            f"Frame {self._preview_index + 1}/{len(self._frames)} · "
            f"Quelle: {source} · Lieferleinwand: {canvas} · "
            f"Maske: {'vorhanden' if mask_path.is_file() else 'fehlt/nicht erforderlich'}"
        )
        self.preview_counter.configure(
            text=f"{self._preview_index + 1}/{len(self._frames)} · {entry.get('name', '')}"
        )
        self.sprite_preview.show(
            path,
            title=("Teammaske · " if wants_mask else "Farbbild · ") + str(entry.get("name", "")),
            detail=detail,
        )

    def _cell(self) -> int:
        try:
            return int(self.cell_size.get())
        except ValueError:
            return 96

    def _turn(self, step: int) -> None:
        pages = max(1, (len(self._frames) + self.PAGE - 1) // self.PAGE)
        self._page = max(0, min(pages - 1, self._page + step))
        self._render_page()

    def _render_page(self) -> None:
        self._gen += 1
        gen = self._gen
        for widget in self.gallery_inner.winfo_children():
            widget.destroy()
        self._photos = []
        self._cells = []
        self._columns = 0
        self.gallery.yview_moveto(0)
        total = len(self._frames)
        if not total:
            self.page_label.configure(
                text="Kein Ordner geladen." if self._index is None else "Keine Frames im Index."
            )
            self.gallery_hint.configure(text="")
            self.gallery.configure(scrollregion=(0, 0, 1, 1))
            return
        pages = (total + self.PAGE - 1) // self.PAGE
        start = self._page * self.PAGE
        page = self._frames[start : start + self.PAGE]
        self.page_label.configure(
            text=f"Seite {self._page + 1}/{pages} · Frames {start + 1}–{start + len(page)} von {total}"
        )
        self.gallery_hint.configure(
            text="grün = SH1 · orange = Crusader · blau/violett = installierte Mod · Klick öffnet 1:1"
        )
        try:
            from PIL import Image, ImageTk
        except ImportError:
            self.page_label.configure(text="Pillow fehlt im venv — keine Miniaturen.")
            return
        folder = self._folder_path()
        cell = self._cell()
        pending = iter(page)

        # Häppchenweise, damit das Fenster beim Laden bedienbar bleibt: 96
        # Kacheln aus 64x700-Frames brauchen zusammen knapp eine Sekunde
        # (gemessen an tile_churches), und ein eingefrorenes Fenster sähe wie
        # ein Absturz aus. Ein Wechsel der Seite bricht den alten Lauf ab.
        def load_chunk() -> None:
            if gen != self._gen:
                return
            for _ in range(12):
                entry = next(pending, None)
                if entry is None:
                    self._reflow()
                    return
                self._add_cell(folder, entry, cell, Image, ImageTk)
            self._reflow()
            self.after(1, load_chunk)

        load_chunk()

    def _add_cell(self, folder: Path, entry: dict, cell: int, Image, ImageTk) -> None:
        path = folder / str(entry.get("file", ""))
        colour = self.TINT.get(str(entry.get("shown_from", "")), self.TINT_OTHER)
        holder = tk.Frame(self.gallery_inner, bg=BG)
        if path.is_file():
            try:
                with Image.open(path) as picture:
                    picture = picture.convert("RGBA")
                    picture.thumbnail((cell - 4, cell - 4), Image.LANCZOS)
                    photo = ImageTk.PhotoImage(picture)
            except Exception:
                photo = None
        else:
            photo = None
        if photo is not None:
            # Verweis halten: tkinter zeichnet nur, was Python noch kennt.
            self._photos.append(photo)
            image = tk.Label(
                holder, image=photo, width=cell, height=cell, bg=PANEL, anchor="s",
                highlightthickness=2, highlightbackground=colour, cursor="hand2",
            )
            image.bind("<Button-1>", lambda _e, item=entry: self._select_frame(item))
            image.bind("<Double-Button-1>", lambda _e, p=path: self._open(p))
        else:
            image = tk.Label(
                holder, text="fehlt", fg=BAD, bg=PANEL, width=cell, height=cell,
                highlightthickness=2, highlightbackground=colour,
            )
        image.pack()
        image.bind("<MouseWheel>", self._wheel)
        number = re.sub(r"^.*?(\d+)\s*$", r"\1", str(entry.get("name", "")))
        tk.Label(holder, text=number, fg=MUTED, bg=BG, font=("Segoe UI", 8)).pack()
        holder.bind("<MouseWheel>", self._wheel)
        self._cells.append(holder)

    def _reflow(self, _event=None) -> None:
        cell = self._cell()
        pad = 6
        width = max(1, self.gallery.winfo_width())
        columns = max(1, (width - pad) // (cell + 4 + pad))
        if columns != self._columns:
            self._columns = columns
            for position, holder in enumerate(self._cells):
                holder.grid(row=position // columns, column=position % columns, padx=3, pady=3)
        else:
            for position, holder in enumerate(self._cells):
                if not holder.winfo_manager():
                    holder.grid(row=position // columns, column=position % columns, padx=3, pady=3)
        self.gallery_inner.update_idletasks()
        self.gallery.configure(scrollregion=self.gallery.bbox("all") or (0, 0, 1, 1))

    def _wheel(self, event) -> None:
        self.gallery.yview_scroll(-int(event.delta / 120), "units")

    def _open(self, path: Path) -> None:
        try:
            os.startfile(str(path))  # noqa: S606 - öffnet die eigene Datei 1:1
        except Exception as exc:
            messagebox.showinfo("Nicht geöffnet", f"{path}\n\n{exc}")

    # -------------------------------------------------------------- Tafeln

    def _list_sheets(self, folder: Path) -> None:
        self._sheets = sorted(folder.glob("UEBERSICHT-*.png")) if folder.is_dir() else []
        self._sheet_index = 0
        self._sheet_size = (0, 0)
        self._show_sheet()

    def _turn_sheet(self, step: int) -> None:
        if not self._sheets:
            return
        self._sheet_index = max(0, min(len(self._sheets) - 1, self._sheet_index + step))
        self._sheet_size = (0, 0)
        self._show_sheet()

    def _sheet_resized(self, _event=None) -> None:
        if self.sheet_full.get() or not self._sheets:
            return
        if self._sheet_job is not None:
            self.after_cancel(self._sheet_job)
        self._sheet_job = self.after(150, self._show_sheet)

    def _show_sheet(self) -> None:
        self._sheet_job = None
        if not self._sheets:
            self.sheet_canvas.delete("all")
            self.sheet_label.configure(text="Keine Tafel — »Tafeln bauen« erzeugt sie aus dem Ordner.")
            self._sheet_photo = None
            return
        path = self._sheets[self._sheet_index]
        self.sheet_label.configure(text=f"{path.name} ({self._sheet_index + 1}/{len(self._sheets)})")
        try:
            from PIL import Image, ImageTk
        except ImportError:
            return
        width = self.sheet_canvas.winfo_width()
        height = self.sheet_canvas.winfo_height()
        full = bool(self.sheet_full.get())
        # Nur neu rechnen, wenn sich Tafel, Modus oder Maß geändert haben: die
        # 2406x3412-Tafel passend zu skalieren kostet 0,1 s (gemessen), und
        # <Configure> feuert auch beim Seitenwechsel ohne Größenänderung.
        wanted = (path, full, (0, 0) if full else (width, height))
        if wanted == self._sheet_size and self._sheet_photo is not None:
            return
        if not full and (width < 50 or height < 50):
            return
        try:
            with Image.open(path) as picture:
                picture = picture.convert("RGB")
                if not full:
                    picture.thumbnail((width - 4, height - 4), Image.LANCZOS)
                self._sheet_photo = ImageTk.PhotoImage(picture)
                size = picture.size
        except Exception as exc:
            self.sheet_label.configure(text=f"{path.name}: nicht lesbar ({exc})")
            return
        self._sheet_size = wanted
        self.sheet_canvas.delete("all")
        self.sheet_canvas.create_image(0, 0, anchor="nw", image=self._sheet_photo)
        self.sheet_canvas.configure(scrollregion=(0, 0, size[0], size[1]))

    def _open_sheet(self) -> None:
        if self._sheets:
            self._open(self._sheets[self._sheet_index])


RULES_TEXT = """\
Rückweg für eigene Grafik — was das Werkzeug prüft, und warum

1. Leinwand exakt. Ein Frame wird nur in der Crusader-Größe übernommen (Spalte \
„Soll-Leinwand"). Der Lader behält den anteiligen Fußpunkt des Crusader-Platzes: \
ein Bild anderer Größe säße an einer anderen Stelle, sähe fast richtig aus, und \
kein Tor schlüge an. Die Ablehnung nennt deshalb beide Fußpunkte — den, an dem \
das Bild säße, und den, an dem es sitzen soll.

2. Der Fußpunkt zählt von links und von UNTEN. Das ist Unitys Ordnung, nicht die \
von Pillow oder eines Malprogramms: pivot_x · Breite, pivot_y · Höhe. Die Tabelle \
rechnet das nur vor; das Urteil fällt sprites.py.

3. Maskenpflicht je Gruppe. Gruppen mit Teammaske („Maske: ja") brauchen zu jedem \
Farbbild ein <name>_m.png in derselben Größe. export schreibt die tatsächlich \
wirksame Maske als Bearbeitungsvorlage mit aus; Farb- und Maskenänderungen werden \
getrennt erkannt und nur als geprüftes Paar übernommen. Gruppen ohne Maske \
(plain_shader) dürfen KEIN _m.png enthalten.

4. Unverändert wird nicht geliefert. index.json trägt je Frame pixels_sha256; ein \
Export, der nur neu gespeichert wurde, gilt als unbearbeitet und geht nicht in die \
Ablage — sonst läge Firefly-Material im Repository.

5. Herkunft = Ablageort. authored = selbst gezeichnet → assets/sprites/authored/ \
(im Repository). derived = übermaltes, skaliertes oder montiertes Firefly-Bild → \
NUR assets/sprites/derived/ (gitignoriert) oder work/. Der Bauer erzwingt, dass \
eine Ablage mit dieser Herkunft auch dort liegt.

6. Ablagen sind im Code freigegeben. _PROJECT_AUTHORED_SPRITE_SETS in \
mod_builder.py bindet jede Ablage an genau eine Gruppe; ein Kirchensatz kann so \
keinen Einheitenframe überschreiben. Neue Ablagen werden dort bewusst \
eingetragen, nicht hier.

7. Mehrteilige Tile-Objekte. Ein flaches Gesamtbild kann wegen überlappender \
Türme und Dächer nicht eindeutig zurückgeschnitten werden. „Tile-Objekt" baut \
deshalb eine .ora mit genau einer benannten Ebene je Spiel-Tile. Framebereich, \
Raster und Orientierung werden im Objektpaket festgeschrieben. Geprüfte Presets \
fixieren diese drei Werte gemeinsam; ein freies Raster verlangt vor dem Split \
eine ausdrückliche Sichtbestätigung. Der Rückweg \
verweigert zusätzliche Ebenen und sichtbare Pixel außerhalb der jeweiligen \
nativen Tile-Leinwand, anstatt sie unbemerkt abzuschneiden.

8. Profil. „Profilabschnitt zeigen" rechnet den Abschnitt aus der Ablage und zeigt \
ihn nur; „Ins Produktionsprofil eintragen" schreibt ihn über \
sprites.py profile-add --write, frisch gelesen und atomar ersetzt. Liegt die \
Gruppe im selben Profil auch als Atlas, ist der separate Schalter die sichtbare \
Zustimmung für --allow-atlas-shadow; ohne ihn verweigert das Werkzeug. Der Bauer \
rechnet beide Digests beim Build unabhängig nach.
"""


class UiTab(ttk.Frame):
    """Preview, validate and transactionally rebuild the interface atlases."""

    def __init__(self, parent, app: Suite):
        super().__init__(parent)
        self.app = app
        self._entries: list[dict] = []
        self._sh1_mode = False
        self.preview_state = tk.StringVar(
            value="Noch kein UI-Export geladen. Vorschau ist keine Buildprüfung."
        )

        self.intro_message = tk.StringVar(value=(
            "Crusader-DE-Atlanten: vier Originalblätter mit XAML-Rechtecken. "
            "Erst exportieren, bearbeiten und prüfen; anschließend eine "
            "ausdrücklich bestätigte lokale Übernahme."
        ))
        ttk.Label(
            self, textvariable=self.intro_message,
            style="Muted.TLabel", wraplength=850, justify="left"
        ).pack(anchor="w", fill="x", padx=6, pady=(6, 3))
        self.workflow_tabs = ttk.Notebook(self)
        self.workflow_tabs.pack(fill="x", padx=6, pady=(0, 4))
        self.crusader_controls = ttk.Frame(self.workflow_tabs)
        self.sh1_controls = ttk.Frame(self.workflow_tabs)
        self.workflow_tabs.add(
            self.crusader_controls, text="Crusader DE · UI-Atlas"
        )
        self.workflow_tabs.add(
            self.sh1_controls, text="Stronghold 1 DE · HUD"
        )
        self._active_workflow = "crusader"
        self._workflow_folders = {
            "crusader": "work/ui",
            "sh1": "work/sh1-hud-editierbar",
        }
        self.workflow_tabs.bind(
            "<<NotebookTabChanged>>", self._workflow_changed, add="+"
        )

        bar = ttk.Frame(self.crusader_controls)
        bar.pack(fill="x", pady=3)
        ttk.Label(bar, text="Blatt:", style="Muted.TLabel").pack(side="left", padx=(6, 8))
        self.atlas = ttk.Combobox(
            bar,
            values=[
                "(alle)", "UI-MasterAtlas", "UI-TrailAtlas",
                "UI-Colour1Atlas", "UI-Colour2Atlas",
            ],
            state="readonly", width=22,
        )
        self.atlas.current(1)
        self.atlas.pack(side="left")
        ttk.Button(bar, text="Exportieren", command=self.export).pack(side="left", padx=6)
        ttk.Button(bar, text="Blätter auflisten", command=self.list_sheets).pack(side="left", padx=2)

        # Shared export browser: each workflow remembers its own folder.
        # Hiding this row inside the Crusader-only tab made the SH1 file
        # selection invisible even though SH1 check/edit reads it.
        back = ttk.Frame(self)
        back.pack(fill="x", padx=6, pady=3)
        ttk.Label(back, text="Arbeitsordner:", style="Muted.TLabel").pack(
            side="left", padx=(6, 8)
        )
        self.folder = tk.Entry(back, bg=PANEL, fg=FG, insertbackground=FG, relief="flat")
        self.folder.insert(0, "work/ui")
        self.folder.pack(side="left", fill="x", expand=True, ipady=4)
        self.folder.bind("<Return>", lambda _event: self.load_export())
        ttk.Button(back, text="…", width=3, command=self.pick).pack(side="left", padx=3)
        ttk.Button(back, text="Bilder laden", command=self.load_export).pack(side="left", padx=3)
        ttk.Button(back, text="Crusader-PNG extern bearbeiten",
                   command=self.shcde_edit_selected).pack(side="left", padx=2)
        self.preview_check_button = ttk.Button(
            back, text="Alles prüfen", command=self.check
        )
        self.preview_check_button.pack(side="left", padx=3)
        self.preview_import_button = ttk.Button(
            back, text="Lose Testausgabe", command=self.do_import
        )
        self.preview_import_button.pack(side="left", padx=3)

        delivery = ttk.Frame(self.crusader_controls)
        delivery.pack(fill="x", pady=3)
        ttk.Label(delivery, text="Produktionsablage:", style="Muted.TLabel").pack(
            side="left", padx=(6, 8)
        )
        self.store = tk.Entry(
            delivery, bg=PANEL, fg=FG, insertbackground=FG, relief="flat", width=28
        )
        self.store.insert(0, "europe-ui")
        self.store.pack(side="left", ipady=4)
        ttk.Label(
            delivery,
            text="abgeleitet, lokal und gitignoriert",
            style="Muted.TLabel",
        ).pack(side="left", padx=8)
        stages = ttk.Frame(self.crusader_controls)
        stages.pack(fill="x", pady=(0, 3))
        self.stage_import_button = ttk.Button(
            stages, text="1. Geprüft übernehmen", command=self.store_import
        )
        self.stage_import_button.pack(side="left", padx=(6, 5))
        self.stage_profile_button = ttk.Button(
            stages, text="2. Ins Produktionsprofil", command=self.profile_write
        )
        self.stage_profile_button.pack(side="left", padx=5)
        self.stage_preview_button = ttk.Button(
            stages, text="Profilabschnitt nur zeigen", command=self.profile_show
        )
        self.stage_preview_button.pack(side="left", padx=5)

        sh1 = ttk.Frame(self.sh1_controls)
        sh1.pack(fill="x", padx=6, pady=(4, 6))
        sh1bar = ttk.Frame(sh1)
        sh1bar.pack(fill="x", padx=5, pady=3)
        ttk.Button(sh1bar, text="1. Original-HUD exportieren",
                   command=self.sh1_hud_export).pack(side="left", padx=3)
        ttk.Button(sh1bar, text="2. SH1-HUD laden",
                   command=self.sh1_hud_load).pack(side="left", padx=3)
        ttk.Button(sh1bar, text="3. Gewähltes Bild bearbeiten",
                   command=self.sh1_hud_edit).pack(side="left", padx=3)
        sh1bar2 = ttk.Frame(sh1)
        sh1bar2.pack(fill="x", padx=5, pady=(0, 3))
        ttk.Button(sh1bar2, text="4. SH1-HUD prüfen",
                   command=self.sh1_hud_check).pack(side="left", padx=3)
        ttk.Button(sh1bar2, text="5. SH1-HUD-Atlanten bauen",
                   command=self.sh1_hud_build).pack(side="left", padx=3)
        ttk.Label(sh1bar2, text="Nur Arbeitskopien; kein automatischer Unity-Spielpatch.",
                  style="Muted.TLabel").pack(side="left", padx=(12, 0))
        sh1bar3 = ttk.Frame(sh1)
        sh1bar3.pack(fill="x", padx=5, pady=(0, 3))
        ttk.Button(sh1bar3, text="6. Geprüfte Unity-Kopie erzeugen",
                   command=self.sh1_hud_unity_candidate).pack(side="left", padx=3)
        ttk.Label(sh1bar3, text="Format- und SHA-geprüfte Ausgabe nur unter dist/; keine Spielinstallation.",
                  style="Muted.TLabel").pack(side="left", padx=8)

        sh1bar4 = ttk.Frame(sh1)
        sh1bar4.pack(fill="x", padx=5, pady=(0, 3))
        ttk.Button(
            sh1bar4, text="7. SH1 ? Crusader DE ?bertragen ...",
            command=lambda: self.app.run(
                [str(TOOLS / "ui_sh1_to_shcde_gui.py")], "SH1 ? SHCDE-HUD-?bertragung"
            ),
        ).pack(side="left", padx=3)
        ttk.Button(
            sh1bar4, text="8. Zus?tzliche SHCDE-UI-Atlanten ...",
            command=lambda: self.app.run(
                [str(TOOLS / "ui_extra_atlas_gui.py")], "SHCDE zus?tzliche Noesis-UI-Atlanten"
            ),
        ).pack(side="left", padx=3)
        ttk.Label(
            sh1bar4, text="Nur gepr?fte Arbeitskopien ? kein Spiel-Einbau.",
            style="Muted.TLabel",
        ).pack(side="left", padx=10)

        body = ttk.PanedWindow(self, orient="horizontal")
        body.pack(fill="both", expand=True, padx=6, pady=(4, 6))
        left = ttk.Frame(body)
        right = ttk.Frame(body)
        body.add(left, weight=0)
        body.add(right, weight=1)

        filter_row = ttk.Frame(left)
        filter_row.pack(fill="x", pady=(0, 3))
        ttk.Label(filter_row, text="Filter:", style="Muted.TLabel").pack(side="left")
        self.filter = tk.Entry(
            filter_row, bg=PANEL, fg=FG, insertbackground=FG, relief="flat"
        )
        self.filter.pack(side="left", fill="x", expand=True, padx=(5, 0), ipady=3)
        self.filter.bind("<KeyRelease>", lambda _event: self._populate())

        self.tree = ttk.Treeview(
            left, columns=("key", "atlas", "size"), show="headings", selectmode="browse"
        )
        for key, heading, width in (
            ("key", "Ressource", 220), ("atlas", "Blatt", 115), ("size", "Größe", 70)
        ):
            self.tree.heading(key, text=heading)
            self.tree.column(key, width=width, minwidth=55, anchor="w")
        scroll = ttk.Scrollbar(left, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._show_selected)

        self.preview = ImagePreview(
            right, empty_text="UI-Export laden – der ausgewählte Ausschnitt erscheint hier."
        )
        self.preview.pack(fill="both", expand=True)
        ttk.Label(
            self, textvariable=self.preview_state,
            style="Muted.TLabel", wraplength=830, justify="left",
        ).pack(fill="x", padx=6, pady=(0, 4))

    def _workflow_changed(self, _event=None) -> None:
        """Keep the two installed games' UI workflows visibly separate."""
        if not hasattr(self, "folder"):
            return
        mode = (
            "sh1" if self.workflow_tabs.select() == str(self.sh1_controls)
            else "crusader"
        )
        is_sh1 = mode == "sh1"
        self.intro_message.set(
            "Stronghold 1 DE: eigene originale XAML-Atlanten und PNG-Arbeitskopien. "
            "Exportieren → auswählen und bearbeiten → prüfen → lokale SH1-Atlanten "
            "erzeugen. Keine Installation und kein Crusader-Paket."
            if is_sh1 else
            "Crusader DE: vier Atlasblätter mit XAML-Rechtecken. "
            "Nur die separate Crusader-Ausgabe prüfen und bewusst "
            "übernehmen; kein Stronghold-1-Bildindex."
        )
        self.preview_check_button.configure(
            text="SH1-PNGs prüfen" if is_sh1 else "Alles prüfen"
        )
        self.preview_import_button.configure(
            state="disabled" if is_sh1 else "normal"
        )
        if mode == self._active_workflow:
            return
        self._workflow_folders[self._active_workflow] = (
            self.folder.get().strip()
        )
        self._active_workflow = mode
        folder = self._workflow_folders[mode]
        self.folder.delete(0, "end")
        self.folder.insert(0, folder)
        path = self._folder_path() / "index.json"
        if not path.is_file():
            self._entries = []
            self._sh1_mode = False
            self.tree.delete(*self.tree.get_children())
            self.preview.clear(
                "Noch keine SH1-HUD-Bilder." if is_sh1
                else "Noch keine Crusader-UI-Bilder."
            )
            self.preview_state.set(
                ("Noch kein SH1-HUD-Export vorhanden. "
                 "Mit »1. Original-HUD exportieren« beginnen."
                 if is_sh1 else
                 "Noch kein Crusader-UI-Export vorhanden. "
                 "Über »Exportieren« einen Arbeitsordner erzeugen.")
            )
            return
        self.load_export()

    def _folder_path(self) -> Path:
        raw = Path(self.folder.get().strip() or "work/ui")
        return raw.resolve() if raw.is_absolute() else (PROJECT_ROOT / raw).resolve()

    def list_sheets(self) -> None:
        self.app.run([str(TOOLS / "ui_atlas.py"), "list"], "ui_atlas.py list")

    def export(self) -> None:
        destination = PROJECT_ROOT / "work" / "ui"
        replace = destination.is_dir() and any(destination.iterdir())
        if replace and not messagebox.askyesno(
            "UI-Export ersetzen",
            f"Der Arbeitsordner ist nicht leer:\n{destination}\n\n"
            "Er kann bearbeitete UI-Bilder enthalten. Nur fortfahren, wenn sie "
            "gesichert oder bewusst verworfen wurden.",
        ):
            return
        args = [str(TOOLS / "ui_atlas.py"), "export", "--out", "work/ui"]
        chosen = self.atlas.get()
        if chosen != "(alle)":
            args += ["--atlas", chosen]
        if replace:
            args.append("--replace")
        from suite_usability import run_then_success
        run_then_success(
            self.app, args, f"ui_atlas.py export {chosen}",
            self._export_ready,
            next_step="UI-Export nach einem erfolgreichen Export laden",
        )

    def pick(self) -> None:
        chosen = filedialog.askdirectory(initialdir=str(PROJECT_ROOT / "work"))
        if chosen:
            self.folder.delete(0, "end")
            self.folder.insert(0, chosen)
            self.load_export()

    def load_export(self) -> None:
        # A PNG preview is not a verified conversion. The index is user-
        # supplied, so even read-only paths must not escape its export root.
        from suite_ui_atlas_preview import (
            UiPreviewIndexError, read_ui_preview_index,
            validate_sh1_hud_preview, SH1_HUD_BUILD_ID,
        )
        try:
            root = self._folder_path()
            entries = read_ui_preview_index(root)
            with (root / "index.json").open("r", encoding="utf-8-sig") as source:
                is_sh1 = json.load(source).get("target_build_id") == SH1_HUD_BUILD_ID
            if is_sh1:
                # A matching build ID alone is NOT an SH1 export. Require its
                # independent source manifest and all three original atlases
                # before showing SH1 editor/check/build actions.
                validate_sh1_hud_preview(root, entries)
            self._entries = entries
            self._sh1_mode = is_sh1
        except (UiPreviewIndexError, OSError, ValueError) as exc:
            self._entries = []
            self._sh1_mode = False
            self.preview_state.set(
                f"UI-Export nicht als Vorschau ladbar: {exc}. "
                "Den ursprünglichen Export prüfen oder erneut erzeugen."
            )
            self.preview.clear("Kein sicher lesbarer UI-Export.")
            self._populate()
            return
        atlases = len({entry["atlas"] for entry in self._entries})
        self.preview_state.set(
            f"Vorschau: {len(self._entries)} Ausschnitte in {atlases} Blättern. "
            "Nicht freigegeben: »Alles prüfen« vergleicht die Original-XAML-, "
            "Unity- und PNG-Nachweise. Jeder Import validiert vor dem Schreiben erneut."
        )
        if self._sh1_mode:
            self.preview_state.set(
                f"Stronghold 1 DE: {len(self._entries)} original benannte HUD/UI-Sprites "
                f"in {atlases} Atlanten. Mit 'Gewähltes Bild bearbeiten' ändern; "
                "nur die SH1-Prüf- und Bau-Schaltflächen verwenden."
            )
        self._populate()

    def _populate(self) -> None:
        self.tree.delete(*self.tree.get_children())
        needle = self.filter.get().strip().casefold()
        visible = []
        for index, entry in enumerate(self._entries):
            haystack = f"{entry.get('key', '')} {entry.get('atlas', '')}".casefold()
            if needle and needle not in haystack:
                continue
            iid = str(index)
            self.tree.insert(
                "", "end", iid=iid,
                values=(entry.get("key", ""), entry.get("atlas", ""),
                        f"{entry.get('width', '?')}×{entry.get('height', '?')}"),
            )
            visible.append(iid)
        if visible:
            self.tree.selection_set(visible[0])
            self.tree.focus(visible[0])
            self._show_selected()
        elif self._entries:
            self.preview.clear("Kein UI-Ausschnitt entspricht dem Filter.")

    def _show_selected(self, _event=None) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        entry = self._entries[int(selected[0])]
        detail = (
            f"{entry['atlas']} · Rechteck x={entry['x']}, y={entry['y']} · "
            f"{entry['width']}×{entry['height']} px · Datei: {entry['file']}"
        )
        self.preview.show(Path(entry["path"]), title=str(entry["key"]), detail=detail)

    def shcde_edit_selected(self) -> None:
        """Open one indexed SHCDE crop in the system's external PNG editor.

        This does not touch source atlases or native game files. The existing
        Crusader check/import will revalidate pixels, rectangles and build SHA.
        """
        if self._sh1_mode:
            messagebox.showwarning(
                "Stronghold 1 DE",
                "Im SH1-Modus den getrennten SH1-Pixeleditor verwenden.",
                parent=self,
            )
            return
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("UI-Grafik ausw?hlen", "Erst eine Crusader-Grafik ausw?hlen.", parent=self)
            return
        try:
            entry = self._entries[int(selection[0])]
            root = self._folder_path()
            work = (PROJECT_ROOT / "work").resolve()
            if root == work or not root.is_relative_to(work):
                raise ValueError("Crusader-Export muss unter SpriteSuite/work liegen")
            from suite_ui_atlas_preview import read_ui_preview_index
            verified = read_ui_preview_index(root)
            match = [e for e in verified if
                     e["key"] == entry["key"] and e["atlas"] == entry["atlas"]
                     and e["file"] == entry["file"]]
            if len(match) != 1:
                raise ValueError("Ausgew?hltes Crusader-Bild entspricht nicht mehr dem gepr?ften Index")
            path = Path(match[0]["path"])
            if path.is_symlink() or not path.is_file():
                raise ValueError("Crusader-Einzel-PNG fehlt oder ist verlinkt")
            os.startfile(str(path))
            self.preview_state.set(
                f"Crusader-PNG im externen Editor ge?ffnet: {entry['key']}. "
                "Pixelma?e beibehalten. Anschlie?end 'Bilder laden' und 'Alles pr?fen' verwenden."
            )
        except (ValueError, OSError, IndexError) as exc:
            messagebox.showerror("Crusader-UI-Bild bearbeiten", str(exc), parent=self)

    def check(self) -> None:
        if self._sh1_mode:
            self.sh1_hud_check()
            return
        folder = self.folder.get().strip() or "work/ui"
        self.app.run(
            [str(TOOLS / "ui_atlas.py"), "check", "--from", folder],
            f"ui_atlas.py check --from {folder}",
        )

    def do_import(self) -> None:
        if self._sh1_mode:
            messagebox.showwarning(
                "Stronghold 1 DE", "Crusader-Override nicht für SH1 verwenden. "
                "Bitte 'SH1-HUD-Atlanten bauen' auswählen.", parent=self)
            return
        folder = self.folder.get().strip() or "work/ui"
        destination = PROJECT_ROOT / "dist" / "ui-override"
        replace = destination.is_dir() and any(destination.iterdir())
        if not messagebox.askyesno(
            "UI-Atlas zurückbauen",
            f"Quelle: {folder}\nAusgabe: {destination}\n\n"
            "Jeder deklarierte Ausschnitt wird zuerst geprüft. Bei einem einzigen "
            "Fehler wird nichts geschrieben. Fortfahren?",
        ):
            return
        args = [str(TOOLS / "ui_atlas.py"), "import", "--from", folder,
                "--out", "dist/ui-override"]
        if replace:
            args.append("--replace")
        self.app.run(args, f"ui_atlas.py import --from {folder}")

    def _store_name(self) -> str | None:
        """The GUI uses the very same store-name constraint as ui_atlas.py."""
        store = self.store.get().strip()
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", store) is None:
            messagebox.showwarning(
                "UI-Ablagename",
                "Bitte einen einfachen Ablagenamen eingeben: Buchstaben, "
                "Zahlen, Bindestrich, Punkt oder Unterstrich. "
                "Ordnerpfade und '..' sind nicht erlaubt.",
                parent=self,
            )
            return None
        return store

    def store_import(self) -> None:
        if self._sh1_mode:
            messagebox.showwarning(
                "Stronghold 1 DE", "SH1-Atlanten nicht in den Crusader-Store importieren. "
                "Benutze die SH1-HUD-Atlanten-Ausgabe in dist/.", parent=self)
            return
        folder = self.folder.get().strip() or "work/ui"
        store = self._store_name()
        if store is None:
            return
        destination = PROJECT_ROOT / "assets" / "ui" / "derived" / store
        replace = destination.is_dir() and any(destination.iterdir())
        if not messagebox.askyesno(
            "UI in Produktionsablage übernehmen",
            f"Geprüfter Export: {folder}\nLokale Ablage: {destination}\n\n"
            "Das vollständige Atlasblatt enthält weiterhin Firefly-Material und "
            "bleibt deshalb zwingend unter assets/ui/derived (gitignoriert). "
            "Zurückgesetzte Blätter werden aus der Ablage entfernt. Fortfahren?",
        ):
            return
        args = [
            str(TOOLS / "ui_atlas.py"), "import", "--from", folder, "--store", store
        ]
        if replace:
            args.append("--replace")
        self.app.run(args, f"ui_atlas.py import --from {folder} --store {store}")

    def profile_show(self) -> None:
        if self._sh1_mode:
            messagebox.showwarning(
                "Stronghold 1 DE", "Das Produktionsprofil ist für Crusader DE. "
                "SH1-HUD-Ergebnisse separat erzeugen.", parent=self)
            return
        store = self._store_name()
        if store is None:
            return
        self.app.run(
            [str(TOOLS / "ui_atlas.py"), "profile-add", store,
             "--profile", "profiles/europe-production.json"],
            f"ui_atlas.py profile-add {store} (nur zeigen)",
        )

    def profile_write(self) -> None:
        if self._sh1_mode:
            messagebox.showwarning(
                "Stronghold 1 DE", "Keine automatische SH1-Installation über "
                "das Crusader-Produktionsprofil.", parent=self)
            return
        store = self._store_name()
        if store is None:
            return
        if not messagebox.askyesno(
            "UI ins Produktionsprofil eintragen",
            f"Ablage: assets/ui/derived/{store}\n"
            "Profil: europe-production.json\n\n"
            "Jedes Blatt wird erneut dekodiert, auf Originalgröße geprüft und "
            "per SHA-256 gepinnt. Fortfahren?",
        ):
            return
        self.app.run(
            [str(TOOLS / "ui_atlas.py"), "profile-add", store,
             "--profile", "profiles/europe-production.json", "--write"],
            f"ui_atlas.py profile-add {store} --write (europe-production.json)",
        )

    def _export_ready(self) -> None:
        """Only the particular successful UI export reloads its PNG preview."""
        self.folder.delete(0, "end")
        self.folder.insert(0, "work/ui")
        self.load_export()


    # SH1 original HUD is deliberately separate from SHCDE's verified import pipeline.
    def sh1_hud_export(self) -> None:
        guess = Path("D:/Games/Stronghold Definitive Edition/"
                     "Stronghold 1 Definitive Edition_Data/globalgamemanagers.assets")
        source = filedialog.askopenfilename(
            title="Stronghold 1 DE: globalgamemanagers.assets auswählen",
            initialdir=str(guess.parent if guess.is_file() else PROJECT_ROOT),
            filetypes=[("Unity-Assetdatei", "*.assets"), ("Alle Dateien", "*.*")],
            parent=self,
        )
        if not source:
            return
        if Path(source).name != "globalgamemanagers.assets":
            messagebox.showwarning(
                "Falsche Datei", "Bitte die Originaldatei globalgamemanagers.assets "
                "aus Stronghold 1 DE wählen.", parent=self)
            return
        target = PROJECT_ROOT / "work" / "sh1-hud-editierbar"
        replace = target.is_dir() and any(target.iterdir())
        if replace and not messagebox.askyesno(
            "HUD-Arbeitsstand ersetzen?",
            f"ACHTUNG: Alle bisherigen HUD-Bildbearbeitungen unter {target} "
            "würden ersetzt. Fortfahren?", parent=self
        ):
            return
        args = [str(TOOLS / "ui_sh1_hud.py"), "export",
                "--source", source, "--out", str(target)]
        if replace:
            args.append("--replace")
        from suite_usability import run_then_success
        run_then_success(
            self.app, args, "Stronghold 1: HUD-Bilder exportieren",
            self.sh1_hud_load,
            next_step="SH1-HUD-Arbeitsbilder nach diesem erfolgreichen Export laden",
        )

    def sh1_hud_load(self) -> None:
        # This is not a Crusader atlas. Preserve that workflow's selected
        # folder and display the dedicated SH1 controls before loading.
        if self.workflow_tabs.select() != str(self.sh1_controls):
            self.workflow_tabs.select(self.sh1_controls)
            self._workflow_changed()
        self._workflow_folders["sh1"] = "work/sh1-hud-editierbar"
        self.folder.delete(0, "end")
        self.folder.insert(0, self._workflow_folders["sh1"])
        self.load_export()

    def sh1_hud_check(self) -> None:
        if not self._sh1_mode:
            messagebox.showwarning(
                "SH1-HUD auswählen",
                "Zuerst 'SH1-HUD laden' wählen (oder den entpackten "
                "Stronghold-1-Arbeitsordner über 'Bilder laden' öffnen).",
                parent=self)
            return
        folder = str(self._folder_path())
        self.app.run([str(TOOLS / "ui_sh1_hud.py"), "check", "--from", folder],
                     "Stronghold 1: alle HUD-Grafiken prüfen")

    def sh1_hud_build(self) -> None:
        if not self._sh1_mode:
            messagebox.showwarning(
                "SH1-HUD auswählen", "Bitte zuerst SH1-HUD laden.", parent=self)
            return
        folder = str(self._folder_path())
        destination = PROJECT_ROOT / "dist" / "sh1-hud-editierte-atlanten"
        replace = destination.is_dir() and any(destination.iterdir())
        if not messagebox.askyesno(
            "Stronghold 1 HUD-Atlanten zusammensetzen",
            f"Quelle: {folder}\nAusgabe: {destination}\n\n"
            "Alle Spritepositionen und Bildgrößen werden geprüft. "
            "Die Ausgabe ändert KEINE installierte Spieldatei. Fortfahren?",
            default="no", parent=self
        ):
            return
        if replace and not messagebox.askyesno(
            "Vorhandene SH1-HUD-Ausgabe wirklich ersetzen?",
            f"Unter {destination} liegen bereits lokale Atlasdateien.\n"
            "Diese bisherigen Ergebnisse würden ersetzt. "
            "Bitte gegebenenfalls vorher sichern.\n\n"
            "Die Spielinstallation selbst bleibt unverändert. "
            "Vorhandene lokale Ausgabe ersetzen?",
            default="no", icon="warning", parent=self,
        ):
            return
        args = [str(TOOLS / "ui_sh1_hud.py"), "build",
                "--from", folder, "--out", str(destination)]
        if replace:
            args.append("--replace")
        self.app.run(args, "Stronghold 1: bearbeitete HUD-Atlanten bauen")

    def sh1_hud_edit(self) -> None:
        if not self._sh1_mode or not self.tree.selection():
            messagebox.showwarning(
                "SH1-HUD auswählen",
                "Zuerst einen Ausschnitt im Stronghold-1-HUD-Export auswählen.",
                parent=self
            )
            return
        entry = self._entries[int(self.tree.selection()[0])]
        path = Path(entry["path"])
        if not path.is_relative_to(PROJECT_ROOT / "work" / "sh1-hud-editierbar"):
            messagebox.showwarning(
                "Nur Arbeitskopien", "Für das Bearbeiten zuerst den HUD-Arbeitsordner "
                "unter work/sh1-hud-editierbar benutzen.", parent=self)
            return
        try:
            from suite_sh1_hud_editor import Sh1HudPixelEditor
            editor = Sh1HudPixelEditor(self, path, after_save=self._show_selected)
            editor.focus_set()
        except (OSError, ValueError) as exc:
            messagebox.showerror("HUD-Editor", str(exc), parent=self)


    def sh1_hud_unity_candidate(self) -> None:
        """Build a source-hash-checked offline Unity asset copy, never install it."""
        if not self._sh1_mode:
            messagebox.showwarning(
                "Stronghold 1 DE", "Zuerst 'SH1-HUD laden' wählen und die "
                "bearbeitbaren Originalbilder prüfen.", parent=self)
            return
        source = filedialog.askopenfilename(
            title="Stronghold 1 DE: originale globalgamemanagers.assets auswählen",
            initialdir=str(PROJECT_ROOT / "work"),
            filetypes=[("Unity Asset", "*.assets"), ("Alle Dateien", "*.*")],
            parent=self,
        )
        if not source:
            return
        if Path(source).name != "globalgamemanagers.assets":
            messagebox.showwarning(
                "Falsche Datei", "Nur die originale Datei "
                "globalgamemanagers.assets auswählen.", parent=self)
            return
        workdir = self._folder_path()
        destination = PROJECT_ROOT / "dist" / "sh1-hud-unity-kandidat"
        overwrite = destination.is_dir() and any(destination.iterdir())
        if not messagebox.askyesno(
            "Isolierte Stronghold-1-Unity-Kopie erzeugen",
            f"Quelle (nur lesen): {source}\n"
            f"HUD-Arbeitsordner: {workdir}\n"
            f"Neue Ausgabe: {destination}\n\n"
            "Das Tool vergleicht die SHA-256-Quellkennung, prüft alle 1.391 "
            "HUD-Elemente, erhält unveränderte Unity-Bytes und "
            "rekomprimiert nur geänderte BC7-Blöcke. "
            "Es installiert oder startet KEIN Spiel. Fortfahren?",
            default="no", parent=self,
        ):
            return
        if overwrite and not messagebox.askyesno(
            "Vorhandenen Unity-Kandidaten ersetzen?",
            f"Die frühere isolierte Ausgabe unter {destination} wird "
            "ersetzt. Eigene Änderungen daran vorher sichern. "
            "Die Originalinstallation wird nicht verändert.",
            default="no", icon="warning", parent=self,
        ):
            return
        args = [
            str(TOOLS / "ui_sh1_unity_patch.py"),
            "--source", source, "--from", str(workdir),
            "--out", str(destination),
        ]
        if overwrite:
            args.append("--replace")
        self.app.run(args, "Stronghold 1: isolierte Unity-HUD-Kopie prüfen und erzeugen")


class TextTab(ttk.Frame):
    """Find and replace Crusades vocabulary."""

    def __init__(self, parent, app: Suite):
        super().__init__(parent)
        self.app = app

        intro = (
            "Sucht arabisches und Kreuzzugs-Vokabular im Spieltext und ersetzt es nach den "
            "Regeln in assets/locales/entarabisierung.json. Die Ersetzung achtet auf "
            "Wortgrenzen und erhält die Großschreibung."
        )
        ttk.Label(self, text=intro, style="Muted.TLabel", wraplength=850,
                  justify="left").pack(anchor="w", padx=4, pady=(12, 10))

        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=4)
        ttk.Button(bar, text="Vorkommen zählen", command=self.scan).pack(side="left", padx=3)
        ttk.Button(bar, text="Mit Beispielen", command=self.scan_context).pack(side="left", padx=3)
        ttk.Button(bar, text="Regeln bearbeiten", command=self.edit_rules).pack(side="left", padx=3)
        ttk.Button(bar, text="Anwenden", command=self.apply).pack(side="left", padx=3)

        note = (
            "Bewusst nicht ersetzt: reale Ortsnamen, Saladin und der Produktname "
            "„Crusader\" — ein erster Lauf ohne diese Ausnahme machte aus „Crusader "
            "verlassen\" ein „Knight verlassen\". Das Ergebnis ist ein Overlay: nur die "
            "geänderten Einträge, damit ein späterer Spielpatch an unberührten Zeilen "
            "nicht zurückgedreht wird."
        )
        ttk.Label(self, text=note, style="Muted.TLabel", wraplength=850,
                  justify="left").pack(anchor="w", padx=4, pady=(10, 0))

    def scan(self) -> None:
        self.app.run([str(TOOLS / "locale_text.py"), "scan"], "locale_text.py scan")

    def scan_context(self) -> None:
        self.app.run([str(TOOLS / "locale_text.py"), "scan", "--context", "25"],
                     "locale_text.py scan --context")

    def edit_rules(self) -> None:
        path = PROJECT_ROOT / "assets" / "locales" / "entarabisierung.json"
        try:
            import os
            os.startfile(str(path))  # noqa: S606 - opening the user's own file
        except Exception as exc:
            messagebox.showinfo("Nicht geöffnet", f"{path}\n\n{exc}")

    def apply(self) -> None:
        self.app.run([str(TOOLS / "locale_text.py"), "apply"], "locale_text.py apply")


class BuildTab(ttk.Frame):
    """Complete profile-aware build, validation and installation workflow."""

    def __init__(self, parent, app: Suite):
        super().__init__(parent)
        self.app = app
        from suite_usability import ScrollableColumn
        self.workflow_scroll = ScrollableColumn(self, background=BG)
        self.workflow_scroll.pack(fill="both", expand=True)
        page = self.workflow_scroll.body

        ttk.Label(page, text="Bauen, prüfen und installieren", style="Title.TLabel").pack(
            anchor="w", padx=8, pady=(14, 4)
        )
        ttk.Label(
            page,
            text=(
                "Bauen schreibt nur nach dist/. Validieren liest diese Ausgabe. "
                "Erst Installieren verändert den BepInEx-Modordner des Spiels."
            ),
            style="Muted.TLabel",
            wraplength=1080,
            justify="left",
        ).pack(anchor="w", padx=8, pady=(0, 10))

        profile_row = ttk.Frame(page)
        profile_row.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Label(profile_row, text="Profil-ID:", style="Muted.TLabel").pack(side="left")
        self.profile = tk.Entry(
            profile_row, bg=PANEL, fg=FG, insertbackground=FG, relief="flat", width=34
        )
        self.profile.insert(0, "europe-production")
        self.profile.pack(side="left", padx=8, ipady=4)
        ttk.Button(profile_row, text="Umgebung prüfen", command=self.doctor).pack(side="left", padx=4)
        ttk.Button(profile_row, text="Was ist installiert?", command=self.installed).pack(side="right", padx=4)

        groups = (
            (
                "1 · Vorbereitung",
                (
                    ("Nachweise vermessen", self.pin,
                     "Nur nach Atlas-/Geometrieänderungen: baut, bis alle beweisbaren Digests feststehen."),
                    ("XAML-Digests bestätigen", self.pin_xaml,
                     "Nur nach bewusst geprüften Änderungen an assets/xaml/*.xaml."),
                ),
            ),
            (
                "2 · Artefakt",
                (
                    ("Mod bauen", self.build,
                     "Erzeugt das gewählte Profil vollständig unter dist/; die Spielinstallation bleibt unberührt."),
                    ("Statisch prüfen", self.validate,
                     "Vergleicht Dateien, Digests, Geometrie und Laufzeitvertrag mit dem Profil."),
                ),
            ),
            (
                "3 · Spieltest",
                (
                    ("Installieren", self.install,
                     "Ersetzt nach Bestätigung genau den StrongholdEuropeDE-Modordner."),
                    ("Laufzeitbericht prüfen", self.runtime_validate,
                     "Prüft das aktuelle Spielprotokoll gegen das installierte oder gewählte Profil."),
                    ("Mod deinstallieren", self.uninstall,
                     "Entfernt nach Bestätigung nur den verwalteten StrongholdEuropeDE-Modordner."),
                ),
            ),
        )
        for heading, steps in groups:
            ttk.Label(page, text=heading, style="Head.TLabel").pack(
                anchor="w", padx=8, pady=(11, 1)
            )
            for label, command, description in steps:
                row = ttk.Frame(page)
                row.pack(fill="x", padx=8, pady=3)
                ttk.Button(row, text=label, width=26, command=command).pack(side="left")
                ttk.Label(
                    row, text=description, style="Muted.TLabel",
                    wraplength=850, justify="left",
                ).pack(side="left", padx=12)
        self.workflow_scroll.bind_mousewheel()

    def _profile_id(self) -> str:
        return self.profile.get().strip() or "europe-production"

    def doctor(self) -> None:
        self.app.run(
            ["-m", "stronghold_europe_de", "doctor", "--config", "config/installations.local.toml"],
            "doctor: Installationen und Projektpfade prüfen",
        )

    def pin(self) -> None:
        self.app.run([str(TOOLS / "pin_digests.py")], "pin_digests.py")

    def pin_xaml(self) -> None:
        self.app.run([str(TOOLS / "pin_xaml.py"), "--write"], "pin_xaml.py --write")

    def build(self) -> None:
        profile_id = self._profile_id()
        if not messagebox.askyesno(
            "Mod bauen",
            f"Profil: {profile_id}\n\n"
            "Eine vorhandene Ausgabe dieses Profils unter dist/ wird atomar ersetzt. "
            "Die Spielinstallation bleibt unverändert. Fortfahren?",
        ):
            return
        self.app.run(
            [
                "-m", "stronghold_europe_de", "build",
                "--config", "config/installations.local.toml",
                "--profile", f"profiles/{profile_id}.json", "--replace",
            ],
            f"build {profile_id}",
        )

    def validate(self) -> None:
        profile_id = self._profile_id()
        self.app.run(
            ["-m", "stronghold_europe_de", "validate",
             "--config", "config/installations.local.toml",
             "--profile-id", profile_id],
            f"validate {profile_id}",
        )

    def install(self) -> None:
        profile_id = self._profile_id()
        if not messagebox.askyesno(
            "Installieren",
            f"Profil: {profile_id}\n\n"
            "Ersetzt den verwalteten StrongholdEuropeDE-Modordner im Spiel durch "
            "die bereits gebaute Ausgabe. Fortfahren?",
        ):
            return
        self.app.run(
            ["-m", "stronghold_europe_de", "install",
             "--config", "config/installations.local.toml",
             "--profile-id", profile_id, "--replace"],
            f"install {profile_id}",
        )

    def runtime_validate(self) -> None:
        profile_id = self._profile_id()
        self.app.run(
            [
                "-m", "stronghold_europe_de", "runtime-validate",
                "--config", "config/installations.local.toml",
                "--profile-id", profile_id,
            ],
            f"runtime-validate {profile_id}",
        )

    def uninstall(self) -> None:
        if not messagebox.askyesno(
            "Mod deinstallieren",
            "Nur der verwaltete StrongholdEuropeDE-Modordner wird entfernt. Fortfahren?",
        ):
            return
        self.app.run(
            ["-m", "stronghold_europe_de", "uninstall", "--config", "config/installations.local.toml"],
            "uninstall StrongholdEuropeDE",
        )

    def installed(self) -> None:
        self.app.run([str(TOOLS / "show_installed.py")], "show_installed.py")


if __name__ == "__main__":
    if not FROZEN_APP and not PYTHON.exists():
        sys.exit(f"Projekt-venv nicht gefunden: {PYTHON}")
    Suite().mainloop()

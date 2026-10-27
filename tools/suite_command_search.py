"""Safe, bilingual Ctrl+K navigation for the complete Sprite Suite.

Every result only navigates to an already-existing workspace/tool view.
Searching or choosing never builds, installs, modifies sprites, or executes a
CLI. Targets are assembled from the live GUI, so removed tabs stay absent.
"""
from __future__ import annotations

from dataclasses import dataclass
import tkinter as tk
from tkinter import ttk
import unicodedata
from typing import Callable


@dataclass(frozen=True)
class SearchTarget:
    key: str
    title_de: str
    title_en: str
    category_de: str
    category_en: str
    keywords: tuple[str, ...]
    navigate: Callable[[], None]

    def title(self, language: str) -> str:
        return self.title_en if language == "en" else self.title_de

    def category(self, language: str) -> str:
        return self.category_en if language == "en" else self.category_de


def normalize_search(value: str) -> str:
    """German spelling, umlaut transliterations and punctuation tolerant."""
    value = value.casefold().translate(str.maketrans({
        "ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
    }))
    value = unicodedata.normalize("NFKD", value)
    value = "".join(letter for letter in value
                    if not unicodedata.combining(letter))
    return " ".join("".join(char if char.isalnum() else " "
                            for char in value).split())


def find_targets(targets: tuple[SearchTarget, ...], query: str,
                 *, limit: int = 25) -> list[SearchTarget]:
    if limit < 1:
        return []
    words = normalize_search(query).split()
    if not words:
        return list(targets[:limit])
    ranked = []
    for position, target in enumerate(targets):
        text = normalize_search(" ".join((
            target.title_de, target.title_en,
            target.category_de, target.category_en, *target.keywords,
        )))
        parts = text.split()
        if not all(word in text for word in words):
            continue
        title = normalize_search(target.title_de + " " + target.title_en)
        score = (
            0 if title.startswith(" ".join(words)) else
            1 if all(any(part.startswith(word) for part in parts)
                     for word in words) else 2
        )
        ranked.append((score, position, target))
    ranked.sort(key=lambda row: row[:2])
    return [target for _, _, target in ranked[:limit]]


def build_navigation_targets(app) -> tuple[SearchTarget, ...]:
    """Register destinations that exist in this particular Suite instance."""
    targets: list[SearchTarget] = []

    def add(key, de, en, group_de, group_en, synonyms, navigate):
        targets.append(SearchTarget(
            key, de, en, group_de, group_en, tuple(synonyms), navigate,
        ))

    for index, (de, en, widget) in enumerate(app._navigation_entries):
        add(f"workspace:{index}", de, en, "Arbeitsbereich", "Workspace",
            (de, en), lambda tab=widget: app.open_tab(tab))

    editor = app.exchange_tab
    for index, section in enumerate(editor.section_targets):
        en = {
            "HTML-Sprite-Editor": "HTML sprite editor",
            "SE-Atlas mit AtlasBuilder": "SE Atlas / AtlasBuilder",
            "Pivot-Vermessung aus dem Spiel": "In-game pivot measurements",
            "Mehrteilige Gebaeude als Ebenen": "Multi-tile buildings / OpenRaster",
        }.get(section, section)
        aliases = {
            "HTML-Sprite-Editor": ("edit png", "sprite editor", "import zip", "html"),
            "SE-Atlas mit AtlasBuilder": ("atlas", "bc7", "dds", "atlasbuilder"),
            "Pivot-Vermessung aus dem Spiel": (
                "zinnen", "lineal", "zinnenlineal", "pivot", "anker", "pivot review",
            ),
            "Mehrteilige Gebaeude als Ebenen": (
                "ora", "ebenen", "openraster", "multi tile", "building",
            ),
        }.get(section, ())
        def show_section(name=section):
            app.open_tab(editor)
            editor.section_choice.set(name)
            editor.jump_to_section()
        add(f"editor:{index}", f"Editor: {section}", f"Editor: {en}",
            "Editor & Austausch", "Editor and exchange",
            aliases, show_section)

    sandbox = app.sandbox_tab
    add("sandbox:map", "Sandkasten: Spielkarte", "Sandbox: Game map",
        "Sandkasten", "Sandbox",
        ("karte", "map", "terrain", "originalkarte", "original map"),
        sandbox.show_game_map)
    add("sandbox:animation", "Sandkasten: Animation / Frames",
        "Sandbox: Animation / frames", "Sandkasten", "Sandbox",
        ("zeitachse", "timeline", "fps", "frame animation"),
        sandbox.show_animation)
    add("sandbox:hud", "Sandkasten: Spiel-HUD", "Sandbox: Game HUD",
        "Sandkasten", "Sandbox",
        ("original hud", "baumenue", "build menu", "spiel hud"),
        sandbox.show_game_hud)
    add("sandbox:compare", "Sandkasten: Pixelvergleich",
        "Sandbox: Pixel comparison", "Sandkasten", "Sandbox",
        ("pixel", "difference", "compare", "screenshot", "bildvergleich"),
        sandbox.compare)
    def reveal_tool(kind):
        # These are idempotent "show" actions, not toggles. A search for
        # "Inspector" must never accidentally *hide* a visible inspector.
        app.open_tab(sandbox)
        bridge = sandbox.ensure_studio()
        if bridge is None:
            return
        workspace = getattr(bridge, "workspace", None)
        if workspace is not None:
            if kind == "palette":
                dock = next((dock for dock in workspace._left_docks
                             if "Palette" in dock.windowTitle()), None)
            else:
                dock = bridge.window._native_dock
            if dock is not None:
                workspace.show_tool(dock)
        elif kind == "palette":
            sandbox.toggle_palette()
        else:
            sandbox.toggle_inspector()

    add("sandbox:palette", "Sandkasten: Sprite-Palette",
        "Sandbox: Sprite palette", "Sandkasten", "Sandbox",
        ("sprite palette", "bilder", "katalog"),
        lambda: reveal_tool("palette"))
    add("sandbox:inspector", "Sandkasten: Karten-Inspector",
        "Sandbox: Map inspector", "Sandkasten", "Sandbox",
        ("inspector", "objekt", "tile", "raw data"),
        lambda: reveal_tool("inspector"))
    add("sandbox:folder", "Sandkasten: Kartenordner wählen",
        "Sandbox: Choose maps folder", "Sandkasten", "Sandbox",
        ("browse", "ordner", "verzeichnis", "game maps", "map path"),
        sandbox.choose_folder)
    # Read-only status actions are navigation, not a report execution.
    add("diagnose:report", "Diagnose: Prüfberichte",
        "Diagnosis: Check reports", "Diagnose & Reparatur",
        "Diagnosis and repair",
        ("fehler", "report", "protokoll", "prüfen", "proof"),
        lambda: app.open_tab(app.diagnose_tab))
    add("build:overview", "Paketbau: Vorbereitung und Freigabe",
        "Package build: Preparation and approval", "Paket bauen",
        "Build packages",
        ("build", "qa", "release", "freigabe", "checksum"),
        lambda: app.open_tab(app.bc7_page))
    return tuple(targets)


class CommandSearchDialog(tk.Toplevel):
    """Nonmodal launcher; all external actions require a deliberate selection."""

    def __init__(self, app, targets: tuple[SearchTarget, ...], *,
                 language="de"):
        super().__init__(app)
        self.app = app
        self.targets = targets
        self.language = "en" if language == "en" else "de"
        self.visible: list[SearchTarget] = []
        self.title("Bereich oder Werkzeug suchen" if self.language == "de"
                   else "Find a workspace or tool")
        self.transient(app)
        self.geometry("650x420")
        self.minsize(410, 270)
        self.resizable(True, True)
        self.query = tk.StringVar()
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        heading = ("Nur zu Bereichen und Werkzeugen navigieren; "
                   "keine Builds, Installationen oder Dateiveränderungen."
                   if self.language=="de" else
                   "Navigate only; no builds, installs or file modifications.")
        self.description = ttk.Label(self, text=heading, wraplength=600,
                                     justify="left")
        self.description.grid(row=0, column=0, sticky="ew", padx=12,
                              pady=(10, 6))
        entry = ttk.Entry(self, textvariable=self.query, font=("Segoe UI", 12))
        self.entry = entry
        entry.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 8))
        entry.bind("<Return>", self.execute_selected)
        entry.bind("<Down>", self.focus_results)
        grid = ttk.Frame(self)
        grid.grid(row=2, column=0, sticky="nsew", padx=12)
        grid.columnconfigure(0, weight=1)
        grid.rowconfigure(0, weight=1)
        self.results = ttk.Treeview(
            grid, columns=("title", "area"), show="headings",
            selectmode="browse", height=11,
        )
        self.results.heading("title", text="Bereich / Werkzeug"
                             if self.language == "de" else "Workspace / tool")
        self.results.heading("area", text="Bereich" if self.language == "de"
                             else "Area")
        self.results.column("title", minwidth=200, width=390, stretch=True)
        self.results.column("area", minwidth=80, width=165, stretch=False)
        self.results.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(grid, orient="vertical",
                                  command=self.results.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.results.configure(yscrollcommand=scrollbar.set)
        self.results.bind("<Return>", self.execute_selected)
        self.results.bind("<Double-1>", self.execute_selected)
        self.results.bind("<Escape>", lambda _event: self.close())
        self.bind("<Escape>", lambda _event: self.close())
        self.hint = ttk.Label(self, text="")
        self.hint.grid(row=3, column=0, sticky="w", padx=12, pady=7)
        self.query.trace_add("write", lambda *_args: self.refresh())
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.refresh()
        self.after_idle(self.entry.focus_set)

    def set_language(self, code: str):
        """Keep an already-open palette coherent during DE/EN changes."""
        next_language = "en" if code == "en" else "de"
        if next_language == self.language:
            return
        self.language = next_language
        self.title("Find a workspace or tool" if self.language == "en"
                   else "Bereich oder Werkzeug suchen")
        heading = (
            "Navigate only; no builds, installs or file modifications."
            if self.language == "en" else
            "Nur zu Bereichen und Werkzeugen navigieren; "
            "keine Builds, Installationen oder Dateiveränderungen."
        )
        self.description.configure(text=heading)
        self.results.heading(
            "title", text="Workspace / tool" if self.language=="en"
                     else "Bereich / Werkzeug"
        )
        self.results.heading("area", text="Area" if self.language=="en"
                             else "Bereich")
        self.refresh()

    def refresh(self):
        previous = self.selected_key()
        self.visible = find_targets(self.targets, self.query.get())
        for ident in self.results.get_children():
            self.results.delete(ident)
        for item in self.visible:
            self.results.insert("", "end", iid=item.key,
                                values=(item.title(self.language),
                                        item.category(self.language)))
        preferred = previous if previous in self.results.get_children() else (
            self.visible[0].key if self.visible else None)
        if preferred:
            self.results.selection_set(preferred)
            self.results.focus(preferred)
        if self.visible:
            self.hint.configure(text=f"{len(self.visible)} "
                 + ("Treffer · Enter öffnet" if self.language=="de"
                    else "results · Enter opens"))
        else:
            self.hint.configure(text=("Keine passenden Bereiche gefunden."
                        if self.language=="de" else "No matching workspaces."))

    def selected_key(self):
        selected = self.results.selection()
        return selected[0] if selected else None

    def focus_results(self, _event=None):
        self.results.focus_set()
        return "break"

    def execute_selected(self, _event=None):
        key = self.selected_key()
        target = next((t for t in self.visible if t.key==key), None)
        if target is None:
            return "break"
        try:
            target.navigate()
        except Exception as exc:
            self.hint.configure(
                text=("Bereich konnte nicht geöffnet werden: "
                      if self.language=="de" else "Could not open workspace: ")
                      +str(exc))
            return "break"
        self.close()
        return "break"

    def close(self):
        if self.winfo_exists():
            self.destroy()

"""Eine ruhige Hauptnavigation für die bestehende SpriteSuite.

Der Umbau setzt auf der echten Tk-Oberfläche auf und ersetzt keine
Verarbeitungs- oder Speicherlogik. Alte Reiter bleiben über die
Bereichsauswahl und Strg+K erreichbar; die neue Seitenleiste führt zu
den häufigsten Aufgaben und zeigt jederzeit den aktuellen Bereich.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from suite_usability import ScrollableColumn

RAIL = "#252b34"
RAIL_ACTIVE = "#364650"
BORDER = "#414a55"
FG = "#f0f3f5"
MUTED = "#abb8c4"
ACCENT = "#f1bd66"


class ModernShell:
    """Eine dauerhaft sichtbare Navigation ohne neue Programm-Workflows."""

    # Ein Eintrag bezeichnet einen bestehenden, wirklichen Reiter.
    PRIMARY = (
        ("start", "Start", "Home", "tab_home"),
        ("menus", "HUD & Menüs", "HUD & menus", "hud_menu_tab"),
        ("sprites", "Sprites bearbeiten", "Edit sprites", "tab_art"),
        ("hud", "SH1 HUD-Studio", "SH1 HUD Studio", "hud_tab"),
        ("origins", "ORIGINS-Grafiken", "ORIGINS graphics", "origins_graphics_tab"),
        ("sandbox", "Spielvorschau", "Game preview", "sandbox_tab"),
        ("diagnose", "Prüfen", "Check", "diagnose_tab"),
        ("build", "Paket erstellen", "Build package", "bc7_page"),
        ("targets", "Ziele & Mods", "Targets & mods", "target_tab"),
    )
    HINTS = {
        "start": ("Wähle eine Aufgabe. Die übrigen Werkzeuge bleiben erreichbar.",
                  "Choose a task. Every specialist tool remains available."),
        "menus": ("1 Bild wählen  ·  2 bearbeiten  ·  3 anordnen  ·  4 exportieren",
                  "1 Choose image  ·  2 edit  ·  3 arrange  ·  4 export"),
        "sprites": ("Sprites ansehen und bestehende Grafiken bearbeiten.",
                    "Browse sprites and edit existing artwork."),
        "hud": ("Stronghold-1-HUD-Bilder bearbeiten und prüfen.",
                "Edit and inspect Stronghold 1 HUD artwork."),
        "origins": ("Grafikdateien aus einer geprüften Quelle übernehmen.",
                    "Import artwork from a verified graphics source."),
        "sandbox": ("Die Spielansicht öffnen und Bearbeitungen prüfen.",
                    "Open the game preview and inspect edits."),
        "diagnose": ("Dateien und Konfiguration prüfen, bevor etwas gebaut wird.",
                     "Check files and settings before building."),
        "build": ("Pakete erstellen; Voraussetzungen werden vor dem Bau geprüft.",
                  "Build packages; required inputs are checked first."),
        "targets": ("Zielspiel auswählen und fertige Pakete verwalten.",
                    "Choose a target game and manage finished packages."),
    }

    def __init__(self, app):
        self.app = app
        self.buttons = {}
        self._syncing = False
        self._labels = {}
        self._install_theme()
        self._replace_header()
        # Alte Leisten bleiben im Widgetbaum, damit Sprachumschaltung,
        # Suchfunktion und historische Schalter weiter funktionieren.
        # Die überflüssige Sonderwerkzeugleiste ist nicht mehr sichtbar.
        app.command_bar.pack_forget()
        # Beide Funktionen sind in der linken Leiste weiterhin erreichbar.
        # So bleibt die obere Navigation auf schmalen Monitoren frei.
        app.tab_strip_toggle.pack_forget()
        app.console_toggle.pack_forget()
        self._make_sidebar()
        app.notebook.configure(style="Modern.TNotebook")
        app.notebook.bind("<<NotebookTabChanged>>", self.sync, add="+")
        app.bind("<Configure>", self._resize, add="+")
        self.refresh_language()
        self.sync()

    def _install_theme(self):
        style = ttk.Style(self.app)
        style.configure("Modern.TNotebook", borderwidth=0, background="#1e1f22")
        # Der Standard-Reiterstreifen bleibt über "Alle Reiter" erreichbar.
        # Im einfachen Modus steuert die Seitenleiste den selben Notebook.
        style.layout("Modern.TNotebook.Tab", [])
        style.configure("Rail.TFrame", background=RAIL)
        style.configure("Rail.TLabel", background=RAIL, foreground=FG,
                        font=("Segoe UI", 10))
        style.configure("RailMuted.TLabel", background=RAIL, foreground=MUTED,
                        font=("Segoe UI", 9))
        style.configure("RailGroup.TLabel", background=RAIL, foreground=ACCENT,
                        font=("Segoe UI", 9, "bold"))
        style.configure("RailTitle.TLabel", background=RAIL, foreground=FG,
                        font=("Segoe UI", 16, "bold"))
        style.configure("Rail.TButton", background=RAIL, foreground=FG,
                        borderwidth=0, anchor="w", padding=(11, 9),
                        font=("Segoe UI", 10))
        style.map("Rail.TButton",
                  background=[("active", "#3a444f"), ("pressed", "#46545f")],
                  foreground=[("disabled", "#7e8996")])
        style.configure("RailActive.TButton", background=RAIL_ACTIVE,
                        foreground="#ffffff", borderwidth=0,
                        anchor="w", padding=(11, 9),
                        font=("Segoe UI", 10, "bold"))
        style.map("RailActive.TButton",
                  background=[("active", "#475b68"), ("pressed", "#405260")])
        style.configure("GuideStep.TButton", background="#30414c",
                        foreground="#ffffff", padding=(12, 9),
                        font=("Segoe UI", 10, "bold"))
        style.map("GuideStep.TButton", background=[("active", "#425663")])
        style.configure("GuideCard.TFrame", background="#292f38")
        style.configure("GuideCard.TLabel", background="#292f38",
                        foreground=FG)
        style.configure("GuideCardMuted.TLabel", background="#292f38",
                        foreground="#bdc8d2")
        style.configure("SectionTitle.TLabel", background="#1e1f22",
                        foreground="#f1f3f5",
                        font=("Segoe UI", 17, "bold"))
        style.configure("Description.TLabel", background="#1e1f22",
                        foreground="#bac4cf", font=("Segoe UI", 10))
        style.configure("TButton", padding=(12, 8))
        style.configure("Treeview", rowheight=27)

    def _replace_header(self):
        app = self.app
        app.title("SpriteSuite – Grafiken und Modpakete")
        old_header = app.status_label.master
        for widget in old_header.winfo_children():
            if not isinstance(widget, ttk.Label):
                continue
            label = widget.cget("text")
            if label == "Stronghold Europe":
                widget.configure(text="SpriteSuite", style="Title.TLabel")
            elif label in ("Python-Arbeitsmodus", "EXE"):
                widget.configure(text="Grafikwerkstatt für Stronghold",
                                 style="Muted.TLabel")

    def _make_sidebar(self):
        app = self.app
        self.rail = ttk.Frame(app, style="Rail.TFrame", width=204)
        self.rail.pack(before=app.notebook, side="left", fill="y",
                       padx=(14, 7), pady=(0, 6))
        self.rail.pack_propagate(False)
        self.scroll = ScrollableColumn(self.rail, background=RAIL)
        self.scroll.pack(fill="both", expand=True)
        body = self.scroll.body
        body.configure(style="Rail.TFrame")

        ttk.Label(body, text="BEREICHE", style="RailGroup.TLabel").pack(
            anchor="w", padx=11, pady=(14, 8))
        for key in ("start", "menus", "sprites", "hud", "origins"):
            self._button(body, key)

        self._separator(body)
        ttk.Label(body, text="PRÜFEN & AUSGEBEN",
                  style="RailGroup.TLabel").pack(
                      anchor="w", padx=11, pady=(7, 8))
        for key in ("sandbox", "diagnose", "build", "targets"):
            self._button(body, key)

        self._separator(body)
        self.more_title = ttk.Label(body, text="WEITERE BEREICHE",
                                    style="RailGroup.TLabel")
        self.more_title.pack(anchor="w", padx=11, pady=(7, 6))
        self.extra_choice = tk.StringVar(master=body)
        self.extra = ttk.Combobox(body, textvariable=self.extra_choice,
                                  state="readonly")
        self.extra.pack(fill="x", padx=9, pady=(0, 7))
        self.extra.bind("<<ComboboxSelected>>", self._open_more)
        self.search_button = ttk.Button(body, text="Suche (Strg+K)",
                        style="Rail.TButton", command=app.show_command_search)
        self.search_button.pack(fill="x", padx=5, pady=2)
        self.manual_button = ttk.Button(body, text="Anleitung öffnen",
                        style="Rail.TButton", command=app.open_guide)
        self.manual_button.pack(fill="x", padx=5, pady=2)
        self.log_button=ttk.Button(body,text="Protokoll anzeigen",
              style="Rail.TButton",command=self.toggle_log)
        self.log_button.pack(fill="x",padx=5,pady=2)
        self.tabs_button=ttk.Button(body,text="Alle Reiter",
              style="Rail.TButton",command=app.toggle_tab_strip)
        self.tabs_button.pack(fill="x",padx=5,pady=2)
        self._separator(body)
        self.language_label = ttk.Label(body, text="Sprache",
                                        style="RailMuted.TLabel")
        self.language_label.pack(anchor="w", padx=11, pady=(5, 1))
        self.lang = ttk.Combobox(body, textvariable=app.language,
                                  values=("DE", "EN"), state="readonly", width=7)
        self.lang.pack(anchor="w", padx=11, pady=(0, 7))
        self.lang.bind("<<ComboboxSelected>>",
                       lambda _e: app.set_language(app.language.get().lower()))
        self.advanced = ttk.Checkbutton(body, text="Erweiterte Werkzeuge",
                   variable=app.advanced, command=app.show_advanced)
        self.advanced.pack(anchor="w", padx=9, pady=(2, 4))
        self.strict = ttk.Checkbutton(body, text="Strenge Prüfung",
                    variable=app.strict, command=app._strict_changed)
        self.strict.pack(anchor="w", padx=9, pady=(0, 9))
        self.scroll.bind_mousewheel()

    def _button(self, parent, key):
        entry = next(row for row in self.PRIMARY if row[0] == key)
        button = ttk.Button(parent, style="Rail.TButton",
                 command=lambda dest=entry[3]:self.open(dest))
        button.pack(fill="x", padx=5, pady=1)
        self.buttons[key] = button

    def _separator(self, parent):
        ttk.Separator(parent, orient="horizontal").pack(
            fill="x", padx=10, pady=(10, 5))

    def toggle_log(self):
        self.app.toggle_console()
        english=self.app.language.get().upper()=="EN"
        self.log_button.configure(text=(
            ("Hide log" if english else "Protokoll ausblenden")
            if self.app._console_wanted else
            ("Show log" if english else "Protokoll anzeigen")
        ))

    def _open_more(self, _event=None):
        dest = self._more_labels.get(self.extra_choice.get())
        if dest is not None:
            self.app.open_tab(dest)

    def open(self, attribute):
        dest = getattr(self.app, attribute)
        self.app.open_tab(dest)

    def _resize(self, event):
        if event.widget is not self.app:
            return
        width = 174 if event.width < 1200 else 204
        if int(self.rail.cget("width")) != width:
            self.rail.configure(width=width)
        # Der alte, sehr lange Zusatztext darf die Knöpfe rechts oben nicht
        # aus dem Fenster drücken. In schmalen Ansichten erklärt die
        # Werkstatt selbst die nächsten Schritte.
        hint=self.app._workspace_hint
        if event.width < 1280:
            if hint.winfo_manager()=="pack":
                hint.pack_forget()
        elif hint.winfo_manager()!="pack":
            hint.pack(side="left",padx=12)

    def update_tab_style(self):
        english=self.app.language.get().upper()=="EN"
        if self.app._compact_tabs:
            self.app.notebook.configure(style="Modern.TNotebook")
            label="Show all tabs" if english else "Alle Reiter"
        else:
            self.app.notebook.configure(style="TNotebook")
            label="Compact tabs" if english else "Reiter bündeln"
        self.tabs_button.configure(text=label)

    def refresh_language(self):
        english = getattr(self.app.language, "get", lambda:"DE")().upper()=="EN"
        position = 2 if english else 1
        for key, de, en, _ in self.PRIMARY:
            self.buttons[key].configure(text=en if english else de)
        self._more_labels = {
            (en if english else de): tab
            for de, en, tab in self.app._navigation_entries
        }
        self.extra.configure(values=list(self._more_labels))
        self.more_title.configure(text=("MORE WORKSPACES" if english
                                        else "WEITERE BEREICHE"))
        self.search_button.configure(text="Search (Ctrl+K)" if english
                                     else "Suche (Strg+K)")
        self.manual_button.configure(text="Open guide" if english
                                     else "Anleitung öffnen")
        self.log_button.configure(text=(
            ("Hide log" if english else "Protokoll ausblenden")
            if self.app._console_wanted else
            ("Show log" if english else "Protokoll anzeigen")
        ))
        self.update_tab_style()
        self.language_label.configure(text="Language" if english else "Sprache")
        self.advanced.configure(text="Advanced tools" if english
                                else "Erweiterte Werkzeuge")
        self.strict.configure(text="Strict validation" if english
                              else "Strenge Prüfung")
        self.sync()

    def sync(self, _event=None):
        if self._syncing:
            return
        self._syncing = True
        try:
            current = self.app.notebook.select()
            english = self.app.language.get().upper()=="EN"
            index = 1 if english else 0
            key = next((key for key, _de, _en, dest in self.PRIMARY
                        if str(getattr(self.app, dest)) == current), None)
            for name, button in self.buttons.items():
                button.configure(style=("RailActive.TButton" if key == name
                                        else "Rail.TButton"))
            if key is not None:
                hint = self.HINTS[key][index]
            else:
                hint = ("Spezialwerkzeug geöffnet · Weitere Bereiche: links."
                        if not english else
                        "Specialist workspace open · Browse more areas on the left.")
            self.app._workspace_hint.configure(text=hint)
        finally:
            self._syncing = False

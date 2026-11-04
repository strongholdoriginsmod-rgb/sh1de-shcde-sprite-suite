"""Workflow-first desktop layout for SpriteSuite.

Only constructs UI. The proven project, editor, validation and export methods
stay on UnifiedWorkflowTab and retain their existing safety contracts.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

DARK = "#1e1f22"
PANEL = "#252b33"
LIGHT = "#f1f4f8"
MUTED = "#b2c1ce"
ACCENT = "#f0ba68"


def _styles(master):
    style = ttk.Style(master)
    style.configure("Workspace.TFrame", background=DARK)
    style.configure("WorkspacePanel.TFrame", background=PANEL)
    style.configure("WorkspaceBottom.TFrame", background="#202b32")
    style.configure("WorkspaceTitle.TLabel", background=DARK, foreground=LIGHT,
                    font=("Segoe UI", 18, "bold"))
    style.configure("WorkspaceCaption.TLabel", background=DARK, foreground=MUTED,
                    font=("Segoe UI", 10))
    style.configure("WorkspaceSection.TLabel", background=PANEL, foreground=ACCENT,
                    font=("Segoe UI", 10, "bold"))
    style.configure("WorkspaceMuted.TLabel", background=PANEL, foreground=MUTED,
                    font=("Segoe UI", 9))
    style.configure("WorkspaceInfo.TLabel", background=PANEL, foreground=LIGHT,
                    font=("Segoe UI", 10))
    style.configure("WorkspacePreview.TLabel", background="#1b242b",
                    foreground=MUTED, anchor="center",
                    font=("Segoe UI", 11))
    style.configure("WorkspaceBottomLabel.TLabel", background="#202b32",
                    foreground=LIGHT, font=("Segoe UI", 9))
    style.configure("WorkspaceBottomMuted.TLabel", background="#202b32",
                    foreground=MUTED, font=("Segoe UI", 9))
    style.configure("WorkspacePrimary.TButton", font=("Segoe UI", 10, "bold"),
                    padding=(13, 9))
    style.configure("WorkspaceSmall.TButton", padding=(8, 5))
    style.configure("Workspace.TPanedwindow", background=DARK)


def build_workflow(view):
    """Build the one project workspace with preview as main work area."""
    _styles(view)
    root = ttk.Frame(view, style="Workspace.TFrame")
    root.pack(fill="both", expand=True)
    view.workbench = root

    heading = ttk.Frame(root, style="Workspace.TFrame", padding=(14, 8, 14, 5))
    heading.pack(fill="x")
    brand = ttk.Frame(heading, style="Workspace.TFrame")
    brand.pack(side="left", fill="x", expand=True)
    ttk.Label(brand, text="MEIN MOD-PROJEKT", style="WorkspaceTitle.TLabel").pack(
        anchor="w")
    ttk.Label(brand, textvariable=view.project_text,
              style="WorkspaceCaption.TLabel").pack(anchor="w", pady=(1, 0))
    project = ttk.Frame(heading, style="Workspace.TFrame")
    project.pack(side="right", anchor="ne")
    # These four actions must stay visible, including at 1020x680.
    for title, action in (
        ("Projekt-ZIP öffnen", view.restore_project),
        ("Projekt sichern (ZIP)", view.backup_project),
        ("Projekt wechseln", view.choose_project),
        ("Neues Projekt", view.create_project),
    ):
        ttk.Button(project, text=title, command=action,
                   style="WorkspaceSmall.TButton").pack(side="left", padx=(3, 0))

    status = ttk.Frame(root, style="Workspace.TFrame", padding=(14, 0, 14, 5))
    status.pack(fill="x")
    view.stage_text = tk.StringVar(master=view, value="QUELLE  →  BEARBEITEN  →  PRÜFEN  →  EXPORT")
    ttk.Label(status, textvariable=view.stage_text,
              style="WorkspaceCaption.TLabel").pack(side="left")

    main = ttk.Panedwindow(root, orient="horizontal", style="Workspace.TPanedwindow")
    main.pack(fill="both", expand=True, padx=13, pady=(0, 7))
    view.main_split = main
    files = ttk.Frame(main, style="WorkspacePanel.TFrame", padding=11)
    inspector = ttk.Frame(main, style="WorkspacePanel.TFrame", padding=11)
    main.add(files, weight=2)
    main.add(inspector, weight=5)

    ttk.Label(files, text="PROJEKTDATEIEN", style="WorkspaceSection.TLabel").pack(
        anchor="w", pady=(0, 6))
    view.source_button = ttk.Button(
        files, text="+  Dateien hinzufügen", command=view.add_sources,
        style="WorkspacePrimary.TButton")
    view.source_button.pack(fill="x", pady=(0, 5))
    options = ttk.Frame(files, style="WorkspacePanel.TFrame")
    options.pack(fill="x", pady=(0, 5))
    ttk.Button(options, text="+ Neues Bild", command=view.make_blank,
               style="WorkspaceSmall.TButton").pack(side="left")
    ttk.Label(options, text="Typ:", style="WorkspaceMuted.TLabel").pack(
        side="left", padx=(9, 4))
    view.category_box = ttk.Combobox(
        options, textvariable=view.category, state="readonly",
        values=tuple(__import__("hud_menu_workspace").CATEGORIES), width=14)
    view.category_box.pack(side="left", fill="x", expand=True)
    tree_frame = ttk.Frame(files, style="WorkspacePanel.TFrame")
    tree_frame.pack(fill="both", expand=True, pady=(4, 4))
    view.tree = ttk.Treeview(tree_frame, columns=("typ", "state"),
                             show="tree headings", selectmode="browse", height=6)
    view.tree.heading("#0", text="Datei")
    view.tree.heading("typ", text="Typ")
    view.tree.heading("state", text="Stand")
    view.tree.column("#0", width=165, minwidth=100, stretch=True)
    view.tree.column("typ", width=66, minwidth=45, stretch=False)
    view.tree.column("state", width=65, minwidth=45, stretch=False)
    tree_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=view.tree.yview)
    view.tree.configure(yscrollcommand=tree_scroll.set)
    view.tree.pack(side="left", fill="both", expand=True)
    tree_scroll.pack(side="right", fill="y")
    view.tree.bind("<<TreeviewSelect>>", view._select)
    view.tree.bind("<Double-1>", lambda _e: view.edit_selected())
    view.source_label = ttk.Label(files, textvariable=view.source_text,
                                   style="WorkspaceMuted.TLabel", wraplength=235,
                                   justify="left")
    view.source_label.pack(fill="x")

    preview_header = ttk.Frame(inspector, style="WorkspacePanel.TFrame")
    preview_header.pack(fill="x")
    ttk.Label(preview_header, text="VORSCHAU & BEARBEITUNG",
              style="WorkspaceSection.TLabel").pack(side="left")
    ttk.Button(preview_header, text="Aktualisieren", command=view.refresh,
               style="WorkspaceSmall.TButton").pack(side="right")
    canvas = ttk.Frame(inspector, style="WorkspacePanel.TFrame")
    canvas.pack(fill="both", expand=True, pady=(8, 7))
    view.preview = ttk.Label(
        canvas, text="Bild wählen oder hinzufügen",
        style="WorkspacePreview.TLabel", justify="center")
    view.preview.pack(fill="both", expand=True)
    view.empty_import_button = ttk.Button(
        view.preview, text="+  Erste Datei importieren",
        command=view.add_sources, style="WorkspacePrimary.TButton")
    view.preview.bind("<Configure>", view._preview_resized, add="+")
    view.selection_text_label = ttk.Label(
        inspector, textvariable=view.selection_text, style="WorkspaceMuted.TLabel",
        justify="left", wraplength=640)
    view.selection_text_label.pack(fill="x", pady=(0, 7))
    actions = ttk.Frame(inspector, style="WorkspacePanel.TFrame")
    actions.pack(fill="x")
    view.edit_button = ttk.Button(
        actions, text="Datei bearbeiten", command=view.edit_selected,
        style="WorkspacePrimary.TButton")
    view.edit_button.pack(side="left", padx=(0, 6))
    view.layout_button = ttk.Button(
        actions, text="Layout gestalten", command=view.open_layout)
    view.layout_button.pack(side="left", padx=(0, 6))
    view.noesis_button = ttk.Button(
        actions, text="Noesis-XAML bearbeiten", command=view.open_noesis)
    view.noesis_button.pack(side="left", padx=(0, 6))
    more = ttk.Menubutton(actions, text="Weitere Aktionen ▾")
    more.pack(side="right")
    view.actions_menu = tk.Menu(more, tearoff=False)
    view.actions_menu.add_command(label="Bild mit Noesis verknüpfen",
                                  command=view.bind_selected_image)
    view.actions_menu.add_command(label="Echte Noesis-Spielpixel ansehen",
                                  command=view.open_native_preview)
    view.actions_menu.add_command(label="Steam-Version lesen",
                                  command=view.check_steam_compatibility)
    more.configure(menu=view.actions_menu)

    bottom = ttk.Frame(root, style="WorkspaceBottom.TFrame", padding=(14, 10, 14, 8))
    bottom.pack(side="bottom", fill="x")
    view.bottom_bar = bottom
    content = ttk.Frame(bottom, style="WorkspaceBottom.TFrame")
    content.pack(fill="x")
    check = ttk.Frame(content, style="WorkspaceBottom.TFrame")
    check.pack(side="left", fill="x", expand=True)
    ttk.Label(check, text="PRÜFEN", style="WorkspaceBottomMuted.TLabel").pack(
        anchor="w", pady=(0, 3))
    commands = ttk.Frame(check, style="WorkspaceBottom.TFrame")
    commands.pack(fill="x")
    view.check_button = ttk.Button(
        commands, text="Änderungen prüfen", command=view.check_project)
    view.check_button.pack(side="left", padx=(0, 8))
    view.check_label = ttk.Label(
        commands, textvariable=view.check_text,
        style="WorkspaceBottomMuted.TLabel", wraplength=300)
    view.check_label.pack(side="left", fill="x", expand=True)

    export = ttk.Frame(content, style="WorkspaceBottom.TFrame")
    export.pack(side="right", anchor="ne")
    ttk.Label(export, text="EXPORTIEREN (INSTALLIERT NICHTS)",
              style="WorkspaceBottomMuted.TLabel").pack(anchor="e", pady=(0, 3))
    controls = ttk.Frame(export, style="WorkspaceBottom.TFrame")
    controls.pack(anchor="e")
    view.export_button = ttk.Button(
        controls, text="Geprüftes Mod-ZIP bauen",
        command=view.build_package, style="WorkspacePrimary.TButton")
    view.export_button.pack(side="left", padx=(0, 5))
    ttk.Button(controls, text="Ordner öffnen", command=view.open_result).pack(
        side="left")
    detail_row = ttk.Frame(bottom, style="WorkspaceBottom.TFrame")
    detail_row.pack(fill="x", pady=(7, 0))
    view.details_toggle = ttk.Button(detail_row, text="Paketdetails ▸",
                                     style="WorkspaceSmall.TButton")
    view.details_toggle.pack(side="left")
    view.result_label = ttk.Label(
        detail_row, textvariable=view.result_text,
        style="WorkspaceBottomLabel.TLabel", wraplength=750, justify="left")
    view.result_label.pack(side="left", fill="x", expand=True, padx=(8, 0))
    view.export_details = ttk.Frame(bottom, style="WorkspaceBottom.TFrame")
    ttk.Label(view.export_details, text="Mod-ID:",
              style="WorkspaceBottomMuted.TLabel").pack(side="left")
    ttk.Entry(view.export_details, textvariable=view.guid, width=28).pack(
        side="left", padx=(5, 12))
    ttk.Label(view.export_details, text="Paketname:",
              style="WorkspaceBottomMuted.TLabel").pack(side="left")
    ttk.Entry(view.export_details, textvariable=view.mod_name, width=35).pack(
        side="left", padx=(5, 0), fill="x", expand=True)

    def toggle_details():
        if view.export_details.winfo_manager():
            view.export_details.pack_forget()
            view.details_toggle.configure(text="Paketdetails ▸")
        else:
            view.export_details.pack(fill="x", pady=(6, 0))
            view.details_toggle.configure(text="Paketdetails ▾")
    view.details_toggle.configure(command=toggle_details)
    view.message_label = ttk.Label(
        bottom, textvariable=view.message,
        style="WorkspaceBottomMuted.TLabel", wraplength=1050)
    view.message_label.pack(fill="x", pady=(7, 0))
    view.bind("<Configure>", lambda _e: _adapt(view), add="+")


def _adapt(view):
    if not getattr(view, "workbench", None):
        return
    w = view.winfo_width()
    if w < 100:
        return
    if hasattr(view, "source_label"):
        view.source_label.configure(wraplength=max(140, view.tree.winfo_width()-18))
    if hasattr(view, "selection_text_label"):
        view.selection_text_label.configure(
            wraplength=max(280, view.preview.winfo_width()-20))
    if hasattr(view, "message_label"):
        view.message_label.configure(wraplength=max(400, w-35))
    if hasattr(view, "result_label"):
        view.result_label.configure(wraplength=max(250, int(w*0.55)))

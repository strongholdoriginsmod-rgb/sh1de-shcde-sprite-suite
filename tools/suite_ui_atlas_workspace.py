"""Native PNG/XAML atlas replacement over the shared persistent atlas core."""
from __future__ import annotations

from pathlib import Path
from queue import Empty, Queue
from threading import Event, Thread
import time
import tkinter as tk
from tkinter import filedialog, ttk
from uuid import uuid4

from PIL import Image, ImageTk

import hud_menu_workspace as hud
from suite_workarea import ScrollableWorkarea
from ui_atlas_workspace import AtlasProject, AtlasWorkspaceError, preview_png


_LABELS = {
    "title": ("UI-Atlas · PNG + XAML", "UI atlas · PNG + XAML"),
    "target": ("1 · Zielatlas", "1 · Target atlas"),
    "source": ("2 · Quellatlas oder Ersatz-PNG", "2 · Source atlas or replacement PNG"),
    "png": ("Atlas-PNG", "Atlas PNG"), "xaml": ("Atlas-XAML", "Atlas XAML"),
    "atlas_key": ("BitmapImage-Key (optional)", "BitmapImage key (optional)"),
    "browse": ("Auswählen …", "Browse …"),
    "create": ("PNG + XAML als Arbeitsstand öffnen", "Open PNG + XAML as workspace"),
    "load": ("Arbeitsstand laden …", "Load workspace …"),
    "filter": ("Einträge filtern", "Filter entries"),
    "key": ("ResourceKey", "ResourceKey"), "rectangle": ("Rechteck x, y · Breite × Höhe", "Rectangle x, y · width × height"),
    "source_atlas": ("Aus gewähltem Quellatlas-Eintrag", "From selected source atlas entry"),
    "source_png": ("Aus einzelner Ersatz-PNG", "From one replacement PNG"),
    "replacement": ("Ersatz-PNG", "Replacement PNG"),
    "fit": ("Größenanpassung", "Size fitting"),
    "fit_help": ("exact: gleiche Größe · contain: einpassen, transparenter Rand · stretch: auf Zielgröße strecken",
                 "exact: matching size · contain: fit with transparent padding · stretch: resize to target"),
    "replace": ("Auswahl ersetzen", "Replace selection"),
    "restore": ("Original wiederherstellen", "Restore original"),
    "undo": ("Rückgängig", "Undo"), "redo": ("Wiederholen", "Redo"),
    "crop_export": ("Aktuellen Ausschnitt als PNG exportieren …", "Export current crop as PNG …"),
    "atlas_export": ("Aktuellen Atlas als PNG exportieren …", "Export current atlas as PNG …"),
    "publish": ("Ins Mod-Projekt übernehmen", "Add to mod project"),
    "cancel": ("Vorgang abbrechen", "Cancel operation"),
    "before": ("Original des Zieleintrags", "Original target entry"),
    "current": ("Aktueller Zieleintrag", "Current target entry"),
    "source_preview": ("Gewählte Quelle", "Selected source"),
    "empty": ("Eintrag auswählen", "Select an entry"),
    "ready": ("PNG + XAML öffnen oder einen gespeicherten Arbeitsstand laden.", "Open PNG + XAML or load a saved workspace."),
    "persist": ("Jede Änderung wird im Arbeitsstand gespeichert. Originaldateien bleiben erhalten. PNG-Exporte benötigen ein neues Ziel.",
                "Every edit is saved in the workspace. Original files are retained. PNG exports require a new destination."),
    "preview": ("Ausschnittvorschau laden", "Loading crop preview"),
    "done": ("Abgeschlossen", "Completed"), "cancelled": ("Abgebrochen", "Cancelled"),
    "cancel_requested": ("Abbruch angefordert. Bereits gespeicherte Änderungen bleiben erhalten.",
                         "Cancellation requested. Already saved edits are retained."),
    "publish_cancelled": ("Export vorbereitet; Projektübernahme abgebrochen.",
                          "Export prepared; adding it to the project was cancelled."),
    "need_target": ("Bitte einen Zielatlas und einen Zieleintrag wählen.", "Select a target atlas and target entry."),
    "need_source": ("Bitte einen Quellatlas-Eintrag oder eine Ersatz-PNG wählen.", "Select a source atlas entry or replacement PNG."),
    "busy": ("Atlasvorgang läuft. Bitte abwarten oder abbrechen.", "Atlas operation is running. Wait or cancel it."),
    "saved": ("Arbeitsstand ist automatisch gespeichert.", "The workspace is saved automatically."),
}


class AtlasWorkspaceWindow:
    """One persistent atlas target, with a separate source and bounded ROI previews."""

    def __init__(self, parent, *, project=None, on_export=None, on_publish=None):
        self.parent = parent
        self.project = Path(project) if project is not None else None
        self.on_export = on_export
        self.on_publish = on_publish
        self._on_closed = None
        self.root = tk.Toplevel(parent)
        self.root.project = self.project
        self.root._atlas_controller = self
        language = getattr(parent, "language", None)
        self.english = bool(language and str(language.get()).upper().startswith("EN"))
        self.root.title(self.tr("title"))
        self.root.geometry("1120x820")
        self.root.minsize(540, 360)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.atlas_project = self.source_project = None
        self.current_workspace = self.source_workspace = None
        self.target_entries = self.source_entries = []
        self.target_info = {}
        self._queue = Queue()
        self._cancel = Event()
        self._worker = None
        self._closing = False
        self._job_id = 0
        self.busy = False
        self._pending_preview = False
        self._preview_due = 0
        self._preview_images = {}
        self._photos = {}
        self._preview_resize_job = None
        self._pump_job = None
        self._controls = []
        self.target_png = tk.StringVar(master=self.root)
        self.target_xaml = tk.StringVar(master=self.root)
        self.source_png = tk.StringVar(master=self.root)
        self.source_xaml = tk.StringVar(master=self.root)
        self.target_atlas_key = tk.StringVar(master=self.root)
        self.source_atlas_key = tk.StringVar(master=self.root)
        self.replacement_png = tk.StringVar(master=self.root)
        self.target_filter = tk.StringVar(master=self.root)
        self.source_filter = tk.StringVar(master=self.root)
        self.source_kind = tk.StringVar(master=self.root, value="atlas")
        self.fit = tk.StringVar(master=self.root, value="exact")
        self.workspace_label = tk.StringVar(master=self.root, value=self.tr("persist"))
        self.status = tk.StringVar(master=self.root, value=self.tr("ready"))
        self._build()
        self._pump_job = self.root.after(25, self._pump)

    def tr(self, key):
        return _LABELS[key][1 if self.english else 0]

    def _button(self, parent, key, callback, **grid):
        button = ttk.Button(parent, text=self.tr(key), command=callback)
        button.grid(padx=3, pady=3, sticky="ew", **grid)
        self._controls.append(button)
        return button

    def _file_field(self, parent, row, label, variable, kind):
        ttk.Label(parent, text=self.tr(label)).grid(row=row, column=0, sticky="w", padx=3, pady=3)
        entry = ttk.Entry(parent, textvariable=variable, width=24)
        entry.grid(row=row, column=1, sticky="ew", padx=3, pady=3)
        button = ttk.Button(parent, text=self.tr("browse"), command=lambda: self._choose_file(variable, kind))
        button.grid(row=row, column=2, sticky="ew", padx=3, pady=3)
        self._controls.extend((entry, button))

    def _build(self):
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        self.area = ScrollableWorkarea(self.root, min_width=640, background="#20252b")
        self.area.grid(row=0, column=0, sticky="nsew")
        body = self.area.body
        body.columnconfigure(0, weight=1)
        for row, source in ((0, False), (1, True)):
            frame = ttk.LabelFrame(body, text=self.tr("source" if source else "target"), padding=7)
            frame.grid(row=row, column=0, sticky="ew", padx=8, pady=5)
            frame.columnconfigure(1, weight=1)
            self._file_field(frame, 0, "png", self.source_png if source else self.target_png, "png")
            self._file_field(frame, 1, "xaml", self.source_xaml if source else self.target_xaml, "xaml")
            ttk.Label(frame, text=self.tr("atlas_key")).grid(row=2, column=0, sticky="w", padx=3)
            key_entry = ttk.Entry(frame, textvariable=self.source_atlas_key if source else self.target_atlas_key)
            key_entry.grid(row=2, column=1, columnspan=2, sticky="ew", padx=3, pady=3)
            self._controls.append(key_entry)
            actions = ttk.Frame(frame)
            actions.grid(row=3, column=0, columnspan=3, sticky="ew")
            actions.columnconfigure(0, weight=1)
            actions.columnconfigure(1, weight=1)
            self._button(actions, "create", lambda source=source: self.create_atlas(source=source), row=0, column=0)
            self._button(actions, "load", lambda source=source: self.load_dialog(source=source), row=0, column=1)
            filter_var = self.source_filter if source else self.target_filter
            ttk.Label(frame, text=self.tr("filter")).grid(row=4, column=0, sticky="w", padx=3)
            ttk.Entry(frame, textvariable=filter_var).grid(row=4, column=1, columnspan=2, sticky="ew", padx=3, pady=3)
            holder = ttk.Frame(frame)
            holder.grid(row=5, column=0, columnspan=3, sticky="ew")
            holder.columnconfigure(0, weight=1)
            tree = ttk.Treeview(holder, columns=("rect",), show="tree headings", height=5, selectmode="browse")
            tree.heading("#0", text=self.tr("key"))
            tree.column("#0", width=270, minwidth=100, stretch=True)
            tree.heading("rect", text=self.tr("rectangle"))
            tree.column("rect", width=250, minwidth=190, stretch=True)
            ybar = ttk.Scrollbar(holder, orient="vertical", command=tree.yview)
            xbar = ttk.Scrollbar(holder, orient="horizontal", command=tree.xview)
            tree.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
            tree.grid(row=0, column=0, sticky="ew")
            ybar.grid(row=0, column=1, sticky="ns")
            xbar.grid(row=1, column=0, sticky="ew")
            tree.bind("<<TreeviewSelect>>", self._selected)
            if source:
                self.source_tree = tree
            else:
                self.target_tree = tree
            filter_var.trace_add("write", lambda *_args, source=source: self._populate(source))
        replace = ttk.LabelFrame(body, text=self.tr("replace"), padding=7)
        replace.grid(row=2, column=0, sticky="ew", padx=8, pady=5)
        replace.columnconfigure(1, weight=1)
        for row, value in enumerate(("atlas", "png")):
            ttk.Radiobutton(replace, text=self.tr("source_" + value), variable=self.source_kind,
                            value=value, command=self._selected).grid(row=row, column=0, columnspan=3, sticky="w")
        self._file_field(replace, 2, "replacement", self.replacement_png, "png")
        self.replacement_png.trace_add("write", self._selected)
        ttk.Label(replace, text=self.tr("fit")).grid(row=3, column=0, sticky="w", padx=3)
        self.fit_picker = ttk.Combobox(replace, textvariable=self.fit, values=("exact", "contain", "stretch"),
                                       state="readonly", width=12)
        self.fit_picker.grid(row=3, column=1, sticky="w", padx=3)
        fit_help = ttk.Label(replace, text=self.tr("fit_help"), wraplength=560)
        fit_help.grid(row=4, column=0, columnspan=3, sticky="ew", padx=3, pady=3)
        replace.bind("<Configure>", lambda event: fit_help.configure(wraplength=max(160, event.width - 24)))
        actions = ttk.Frame(replace)
        actions.grid(row=5, column=0, columnspan=3, sticky="ew")
        for col in range(2):
            actions.columnconfigure(col, weight=1)
        for index, (key, callback) in enumerate((("replace", self.replace_selected), ("restore", self.restore_selected),
                                               ("undo", self.undo), ("redo", self.redo),
                                               ("crop_export", self.export_crop_dialog), ("atlas_export", self.export_atlas_dialog))):
            self._button(actions, key, callback, row=index // 2, column=index % 2)
        self.publish_button = None
        if self.project is not None:
            self.publish_button = self._button(actions, "publish", self.publish, row=3, column=0, columnspan=2)
            self.publish_button.state(["disabled"])
        previews = ttk.Frame(body)
        previews.grid(row=3, column=0, sticky="ew", padx=8, pady=5)
        self.preview_canvases = {}
        for column, key in enumerate(("before", "current", "source_preview")):
            previews.columnconfigure(column, weight=1, uniform="previews")
            frame = ttk.LabelFrame(previews, text=self.tr(key), padding=3)
            frame.grid(row=0, column=column, sticky="nsew", padx=2)
            frame.columnconfigure(0, weight=1)
            canvas = tk.Canvas(frame, width=1, height=190, background="#30363d", highlightthickness=0)
            canvas.grid(row=0, column=0, sticky="ew")
            canvas.bind("<Configure>", self._preview_resized)
            self.preview_canvases[key] = canvas
        note = ttk.Label(body, textvariable=self.workspace_label, wraplength=600)
        note.grid(row=4, column=0, sticky="ew", padx=12, pady=6)
        body.bind("<Configure>", lambda event: note.configure(wraplength=max(160, event.width - 24)))
        status_frame = ttk.Frame(self.root, padding=7)
        status_frame.grid(row=1, column=0, sticky="ew")
        status_frame.columnconfigure(0, weight=1)
        self.status_view = tk.Text(status_frame, width=1, height=2, wrap="word", font=("Segoe UI", 10),
                                   padx=5, pady=3, relief="flat", state="disabled")
        self.status_view.grid(row=0, column=0, sticky="ew", padx=3)
        self.status_ybar = ttk.Scrollbar(status_frame, orient="vertical", command=self.status_view.yview)
        self.status_ybar.grid(row=0, column=1, sticky="ns")
        self.status_view.configure(yscrollcommand=self.status_ybar.set)
        self.status.trace_add("write", self._update_status)
        self._update_status()
        self.cancel_button = ttk.Button(status_frame, text=self.tr("cancel"), command=self.cancel, state="disabled")
        self.cancel_button.grid(row=0, column=2, padx=4)
        self.progress = ttk.Progressbar(status_frame, mode="indeterminate", length=110)
        self.progress.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(5, 0))
        self._draw_previews()

    def _update_status(self, *_args):
        self.status_view.configure(state="normal")
        self.status_view.delete("1.0", "end")
        self.status_view.insert("1.0", self.status.get())
        self.status_view.count("1.0", "end", "update", "ypixels")
        self.status_view.configure(state="disabled")

    def _choose_file(self, variable, kind):
        path = filedialog.askopenfilename(parent=self.root, filetypes=[(kind.upper(), "*." + kind)])
        if path:
            variable.set(path)

    def _workspace_destination(self):
        base = hud._metadata_dir(self.project) if self.project is not None else hud.WORK
        base = base / "ui-atlas-workspaces"
        base.mkdir(parents=True, exist_ok=True)
        return base / uuid4().hex[:12]

    def create_atlas(self, *, source=False):
        png = (self.source_png if source else self.target_png).get().strip()
        xaml = (self.source_xaml if source else self.target_xaml).get().strip()
        if not png or not xaml:
            self.status.set(self.tr("ready"))
            return False
        workspace = self._workspace_destination()
        atlas_key = (self.source_atlas_key if source else self.target_atlas_key).get().strip()
        def create(cancel):
            options = {"atlas_key": atlas_key} if atlas_key else {}
            project = AtlasProject.create(Path(png), Path(xaml), workspace, cancel=cancel, **options)
            return project, workspace, project.entries, project.info()
        return self._start(self.tr("create"), create, lambda result: self._loaded(result, source))

    def load_dialog(self, *, source=False):
        path = filedialog.askdirectory(parent=self.root, title=self.tr("load"))
        return self.load_workspace(Path(path), source=source) if path else False

    def load_workspace(self, workspace, *, source=False):
        workspace = Path(workspace)
        def load(_cancel):
            project = AtlasProject.open(workspace)
            return project, workspace, project.entries, project.info()
        return self._start(self.tr("load"), load, lambda result: self._loaded(result, source), read_only=True)

    def _loaded(self, result, source):
        project, workspace, entries, info = result
        if source:
            self.source_project, self.source_workspace, self.source_entries = project, workspace, entries
        else:
            self.atlas_project, self.current_workspace, self.target_entries, self.target_info = project, workspace, entries, info
            self.workspace_label.set(str(workspace) + "\n" + self.tr("persist"))
        self._populate(source)
        warnings = info.get("warnings") or []
        if warnings:
            self.status.set(" · ".join(str(item) for item in warnings)[:1500])
        self._pending_preview = True
        self._sync_controls()

    def _populate(self, source=False):
        tree = self.source_tree if source else self.target_tree
        selected = tree.selection()
        query = (self.source_filter if source else self.target_filter).get().casefold()
        tree.delete(*tree.get_children())
        for entry in self.source_entries if source else self.target_entries:
            if query and query not in entry["key"].casefold():
                continue
            tree.insert("", "end", iid=entry["key"], text=entry["key"], values=(
                f"{entry['x']}, {entry['y']} · {entry['width']} × {entry['height']}",))
        available = tree.get_children()
        key = selected[0] if selected and selected[0] in available else available[0] if available else None
        if key:
            tree.selection_set(key)
            tree.see(key)

    @staticmethod
    def _key(tree):
        selection = tree.selection()
        return selection[0] if selection else None

    def _selected(self, *_args):
        self._pending_preview = True
        self._preview_due = time.monotonic() + .15

    @staticmethod
    def _display_roi(image):
        # Display-only downsampling never changes core replacement/export pixels.
        image.thumbnail((512, 384), Image.Resampling.NEAREST)
        return image

    def _load_previews(self):
        target, source = self.atlas_project, self.source_project
        key, source_key = self._key(self.target_tree), self._key(self.source_tree)
        kind, replacement = self.source_kind.get(), self.replacement_png.get().strip()
        token = (target, source, key, source_key, kind, replacement)
        def load(_cancel):
            images = {}
            if target is not None and key:
                images["before"] = self._display_roi(target.original_preview(key))
                images["current"] = self._display_roi(target.preview(key))
            if kind == "atlas" and source is not None and source_key:
                images["source_preview"] = self._display_roi(source.preview(source_key))
            elif kind == "png" and replacement:
                images["source_preview"] = preview_png(Path(replacement), max_size=(512, 384))
            return token, images
        def loaded(result):
            current = (self.atlas_project, self.source_project, self._key(self.target_tree),
                       self._key(self.source_tree), self.source_kind.get(), self.replacement_png.get().strip())
            if result[0] != current:
                for image in result[1].values():
                    image.close()
                self._pending_preview = True
                return
            for image in self._preview_images.values():
                image.close()
            self._preview_images = result[1]
            self._draw_previews()
        self._pending_preview = False
        return self._start(self.tr("preview"), load, loaded, read_only=True, quiet=True)

    def _preview_resized(self, _event=None):
        if self._preview_resize_job is None:
            self._preview_resize_job = self.root.after_idle(self._draw_previews)

    def _draw_previews(self):
        self._preview_resize_job = None
        for key, canvas in self.preview_canvases.items():
            canvas.delete("all")
            image = self._preview_images.get(key)
            width, height = max(1, canvas.winfo_width()), max(1, canvas.winfo_height())
            if image is None:
                canvas.create_text(width / 2, height / 2, text=self.tr("empty"), fill="#eff2f5", width=max(20, width - 12))
                continue
            shown = image.copy()
            shown.thumbnail((max(1, width - 8), max(1, height - 8)), Image.Resampling.NEAREST)
            self._photos[key] = ImageTk.PhotoImage(shown, master=self.root)
            canvas.create_image(width / 2, height / 2, image=self._photos[key], anchor="center")
            shown.close()

    def _mutate(self, label, callback):
        if self.atlas_project is None:
            self.status.set(self.tr("need_target"))
            return False
        def operation(cancel):
            result = callback(cancel)
            return result, self.atlas_project.info()
        def done(result):
            self.target_info = result[1]
            self._pending_preview = True
        return self._start(label, operation, done)

    def replace_selected(self):
        key, fit = self._key(self.target_tree), self.fit.get()
        if self.atlas_project is None or not key:
            self.status.set(self.tr("need_target"))
            return False
        if self.source_kind.get() == "atlas":
            source_key = self._key(self.source_tree)
            if self.source_project is None or not source_key:
                self.status.set(self.tr("need_source"))
                return False
            source = self.source_project
            callback = lambda cancel: self.atlas_project.replace_from(key, source, source_key, fit=fit, cancel=cancel,
                                                                     expected_revision=self.target_info["revision"])
        else:
            path = self.replacement_png.get().strip()
            if not path:
                self.status.set(self.tr("need_source"))
                return False
            callback = lambda cancel: self.atlas_project.replace(key, Path(path), fit=fit, cancel=cancel,
                                                                expected_revision=self.target_info["revision"])
        return self._mutate(self.tr("replace"), callback)

    def restore_selected(self):
        key = self._key(self.target_tree)
        if not key:
            self.status.set(self.tr("need_target"))
            return False
        return self._mutate(self.tr("restore"), lambda cancel: self.atlas_project.restore(
            key, expected_revision=self.target_info["revision"], cancel=cancel))

    def undo(self):
        return self._mutate(self.tr("undo"), lambda cancel: self.atlas_project.undo(
            expected_revision=self.target_info["revision"], cancel=cancel))

    def redo(self):
        return self._mutate(self.tr("redo"), lambda cancel: self.atlas_project.redo(
            expected_revision=self.target_info["revision"], cancel=cancel))

    def publish(self):
        if self.project is None or self.atlas_project is None or self.on_publish is None:
            self.status.set(self.tr("need_target"))
            return False
        project = self.atlas_project
        destination = self.current_workspace / "exports" / uuid4().hex[:12]
        destination.parent.mkdir(parents=True, exist_ok=True)
        return self._start(self.tr("publish"), lambda cancel: project.export_pair(destination, cancel=cancel),
                           self.on_publish, followup_mutation=True)

    def export_crop_dialog(self):
        return self._export_dialog(crop=True)

    def export_atlas_dialog(self):
        return self._export_dialog(crop=False)

    def _export_dialog(self, *, crop):
        if self.atlas_project is None or (crop and not self._key(self.target_tree)):
            self.status.set(self.tr("need_target"))
            return False
        output = filedialog.asksaveasfilename(parent=self.root, defaultextension=".png", filetypes=[("PNG", "*.png")])
        return self.export_png(Path(output), crop=crop) if output else False

    def export_png(self, destination, *, crop=False):
        key = self._key(self.target_tree)
        if self.atlas_project is None or (crop and not key):
            self.status.set(self.tr("need_target"))
            return False
        project, destination = self.atlas_project, Path(destination)
        def export(cancel):
            return (project.export_crop(key, destination, cancel=cancel) if crop else
                    project.export_png(destination, cancel=cancel))
        def done(_result):
            if not crop and self.on_export is not None:
                self.on_export(destination)
        return self._start(self.tr("crop_export" if crop else "atlas_export"), export, done)

    def _start(self, label, callback, on_success, *, read_only=False, quiet=False, followup_mutation=False):
        if self.busy or self._closing:
            if not quiet:
                self.status.set(self.tr("busy"))
            return False
        self.busy = True
        self._cancel = Event()
        cancel = self._cancel
        self._job_id += 1
        job_id = self._job_id
        if not quiet:
            self.status.set(label + " …")
        self.cancel_button.configure(state="normal")
        self.progress.start(15)
        if not quiet:
            for control in self._controls:
                control.state(["disabled"])
        def work():
            try:
                if cancel.is_set():
                    raise AtlasWorkspaceError("cancelled", "Cancelled before start")
                result = callback(cancel.is_set)
                self._queue.put((job_id, result, None, on_success, cancel, read_only, quiet, followup_mutation))
            except Exception as error:
                self._queue.put((job_id, None, error, on_success, cancel, read_only, quiet, followup_mutation))
        self._worker = Thread(target=work, daemon=True)
        self._worker.start()
        return True

    def _pump(self):
        self._pump_job = None
        try:
            while True:
                job_id, result, error, success, cancel, read_only, quiet, followup_mutation = self._queue.get_nowait()
                cancelled = cancel.is_set()
                if job_id != self._job_id:
                    continue
                self.busy = False
                self.progress.stop()
                self.cancel_button.configure(state="disabled")
                for control in self._controls:
                    control.state(["!disabled"])
                self._sync_controls()
                if error is not None:
                    self.status.set(self.tr("cancelled") if getattr(error, "code", None) == "cancelled" else str(error)[:1500])
                elif cancelled and (read_only or followup_mutation):
                    self.status.set(self.tr("publish_cancelled" if followup_mutation else "cancelled"))
                elif not self._closing:
                    if not quiet:
                        self.status.set(self.tr("done") + (" · " + self.tr("saved") if self.atlas_project else ""))
                    try:
                        success(result)
                    except Exception as error:
                        self.status.set(str(error)[:1500])
        except Empty:
            pass
        if self._closing and not self.busy:
            self._destroy()
            return
        if self._pending_preview and not self.busy and time.monotonic() >= self._preview_due:
            self._load_previews()
        self._pump_job = self.root.after(25, self._pump)

    def cancel(self):
        if self.busy:
            self._cancel.set()
            self._pending_preview = False
            self.status.set(self.tr("cancel_requested"))

    def _sync_controls(self):
        if self.publish_button is not None:
            self.publish_button.state(["!disabled"] if self.atlas_project is not None and
                                      self.on_publish is not None and not self.busy else ["disabled"])

    def is_dirty(self):
        return self.busy

    def save(self):
        if self.busy:
            raise ValueError(self.tr("busy"))
        self.status.set(self.tr("saved" if self.atlas_project is not None else "ready"))
        return True

    def close(self, on_closed=None):
        if on_closed is not None:
            self._on_closed = on_closed
        if self.busy:
            self._closing = True
            self.cancel()
            return False
        self._destroy()
        return True

    def _destroy(self):
        if not self.root.winfo_exists():
            return
        for job in (self._pump_job, self._preview_resize_job):
            if job is not None:
                self.root.after_cancel(job)
        for image in self._preview_images.values():
            image.close()
        self._photos.clear()
        self.root.destroy()
        if self._on_closed is not None:
            callback, self._on_closed = self._on_closed, None
            self.parent.after_idle(callback)


def open_workspace(parent, project=None, on_export=None, on_publish=None):
    """Reuse the existing atlas controller for this parent and Suite project."""
    cache = getattr(parent, "_ui_atlas_windows", None)
    if cache is None:
        cache = parent._ui_atlas_windows = {}
    key = str(Path(project).resolve()) if project is not None else None
    existing = cache.get(key)
    if existing is not None and existing.root.winfo_exists():
        existing.root.lift()
        if on_export is not None:
            existing.on_export = on_export
        if on_publish is not None:
            existing.on_publish = on_publish
        existing._sync_controls()
        parent._ui_atlas_workspace = existing
        return existing
    window = AtlasWorkspaceWindow(parent, project=project, on_export=on_export, on_publish=on_publish)
    cache[key] = window
    parent._ui_atlas_workspace = window
    return window

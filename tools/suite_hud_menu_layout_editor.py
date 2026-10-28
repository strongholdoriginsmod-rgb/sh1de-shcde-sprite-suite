"""Photoshop-like direct manipulation of HUD/menu layers in a Tk preview.

The designer edits a saved scene, not original game binaries. Position, size,
rotation, opacity, pivot, anchor and layer order are serialized separately and
also used by the real rendered asset-only export. GUI preview is interactive.
"""
from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from io import BytesIO
import json
import math
import os
import sys
from pathlib import Path
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, simpledialog, ttk
import uuid

from PIL import Image, ImageGrab, ImageTk

from suite_usability import ScrollableColumn
from suite_layout_flow import layout_advice
from suite_hud_menu_session import read_session, save_session
from hud_menu_workspace import (
    CATEGORIES, WorkshopError, import_image, list_assets, workspace,
    _metadata_dir, _write_new, filename,
)
from hud_menu_layout import (
    ANCHORS, History, Layer, Scene, add_layer, duplicate_layer,
    audit_export, export_composition, hit_test, layer_by_id, load_scene,
    move_layer, origin_of, pivot_of, prepare_package_source,
    remove_layers, reorder, render_preview, render_scene,
    resize_handle, rotated_corners, save_scene, scene_file, set_geometry,
)

_CANVAS_MARGIN = 25
_HANDLES = ("nw","n","ne","e","se","s","sw","w")
_COLOURS = {
    "selection": "#ffca53",
    "rotate": "#5fe9d6",
    "grid": "#63707c",
}
_MAX_DISPLAY_PIXELS = 12_000_000


class HudMenuLayoutEditor(tk.Toplevel):
    """Live compositing, handles, nudge, clipboard, layer ordering and export."""

    def __init__(self, parent, *, project: Path, source_asset: str | None = None,
                 after_export=None):
        self.project = workspace(project,create=True)
        self.after_export = after_export
        default = "menu-layout"
        recent = read_session()
        preferred = recent.get("scene") if recent.get("project")==self.project else ""
        if preferred:
            # Only reopen a previously saved, verified scene, never an
            # unsaved name or a path supplied by untrusted preference data.
            candidate = scene_file(self.project,preferred)
            if candidate.is_file() and not candidate.is_symlink():
                default = preferred
        saved = scene_file(self.project,default)
        if saved.is_file():
            scene,self._save_hash = load_scene(self.project,default)
        else:
            scene,self._save_hash = Scene(name=default),None
        self.history = History(scene)
        self._last_saved = self.scene.as_json()
        self._selection: list[str] = []
        self._clipboard: list[dict] = []
        self._drag_base = None
        self._drag_origin = None
        self._drag_mode = None
        self._drag_handle = None
        self._rotate_pointer_angle = 0.
        self._handles = {}
        self._image_tk = None
        self._render_pending = False
        self._render_job = None
        self._syncing_tree = False
        self._busy = False
        self._export_verified = False
        self._export_problem = ""

        super().__init__(parent)
        self.title("Sprite Suite · HUD & Menüs · visueller Layout-Designer")
        self.geometry("1400x860")
        self.minsize(880,570)
        self.scene_name = tk.StringVar(self,value=scene.name)
        self.source_choice = tk.StringVar(self,value=source_asset or "")
        self.source_display = tk.StringVar(self,value="")
        self._asset_choices = {}
        self.zoom = tk.DoubleVar(self,value=0.75)
        self.snap = tk.BooleanVar(self,value=True)
        self.snap_step = tk.IntVar(self,value=8)
        self.proportional = tk.BooleanVar(self,value=False)
        self.include_patches = tk.BooleanVar(self,value=False)
        self.status = tk.StringVar(self,value="Grafik direkt mit der Maus bewegen; Eckgriffe skalieren.")
        self.guide_heading = tk.StringVar(self,value="1 / 4 – Bild öffnen")
        self.guide_detail = tk.StringVar(self,value="Ein Bild importieren und einfügen.")
        self.guide_button_text = tk.StringVar(self,value="PNG importieren")
        self.selection_detail = tk.StringVar(self,value="Eine Ebene auswählen, um ihre Werte zu ändern.")
        self._next_action = "import"
        self._property_vars={}
        self._show_ui()
        self._source_trace=self.source_choice.trace_add(
            "write",self._sync_source_display)
        self._update_scene_names()
        self._refresh_assets()
        self._refresh_layers()
        self._check_export_status()
        self._schedule_draw()
        self._after_fit=self.after(120,self.fit)
        self._after_lang=self.after(140,self._apply_initial_language)
        self._after_guidance=self.after(160,self._update_guidance)
        self.protocol("WM_DELETE_WINDOW",self.close_editor)
        self.bind("<Control-s>",self._shortcut_save)
        self.bind("<Control-z>",self._shortcut_undo)
        self.bind("<Control-y>",self._shortcut_redo)
        self.bind("<Control-c>",self._shortcut_copy)
        self.bind("<Control-v>",self._shortcut_paste)
        self.bind("<Delete>",self._shortcut_delete)
        self.bind("<Escape>",self._shortcut_clear)
        self.bind("<Control-plus>",self._zoom_in)
        self.bind("<Control-minus>",self._zoom_out)
        self.canvas.bind("<Left>",lambda e:self._keyboard_nudge(e,-1,0))
        self.canvas.bind("<Right>",lambda e:self._keyboard_nudge(e,1,0))
        self.canvas.bind("<Up>",lambda e:self._keyboard_nudge(e,0,-1))
        self.canvas.bind("<Down>",lambda e:self._keyboard_nudge(e,0,1))
        self.canvas.focus_set()

    @property
    def scene(self):
        return self.history.scene

    def _show_ui(self):
        intro=ttk.Frame(self,padding=(10,8,10,2))
        intro.pack(fill="x")
        ttk.Label(intro,text="Layout bearbeiten",
                  font=("Segoe UI",16,"bold")).pack(side="left")
        ttk.Button(intro,text="Hilfe",command=self.show_layout_help
                   ).pack(side="right",padx=3)
        ttk.Label(intro,text="Bilder platzieren · Ebenen bearbeiten",
                  ).pack(side="left",padx=14)
        guide=ttk.Frame(self,padding=(10,7,10,7))
        guide.pack(fill="x")
        guide_copy=ttk.Frame(guide)
        self.next_button=ttk.Button(guide,text="PNG importieren",
                     command=self.next_step)
        # Pack the button first so descriptions cannot push it off-screen.
        self.next_button.pack(side="right",padx=(10,0))
        guide_copy.pack(side="left",fill="x",expand=True)
        ttk.Label(guide_copy,textvariable=self.guide_heading,
                  font=("Segoe UI",11,"bold")).pack(anchor="w")
        ttk.Label(guide_copy,textvariable=self.guide_detail,
                  wraplength=460,justify="left").pack(anchor="w",pady=(1,0))
        top=ttk.Frame(self,padding=(7,4,7,1))
        top.pack(fill="x")
        ttk.Label(top,text="Projekt:",font=("Segoe UI",10,"bold")).pack(side="left")
        self.scene_picker = ttk.Combobox(
            top,textvariable=self.scene_name,width=24,state="readonly")
        self.scene_picker.pack(side="left",padx=(6,4))
        ttk.Button(top,text="Neu",command=self.new_scene).pack(side="left",padx=2)
        ttk.Button(top,text="Laden",command=self.reload_scene).pack(side="left",padx=2)
        ttk.Button(top,text="Speichern · Strg+S",command=self.save).pack(side="left",padx=2)
        ttk.Button(top,text="Rückgängig",command=self.undo).pack(side="left",padx=(14,2))
        ttk.Button(top,text="Wiederholen",command=self.redo).pack(side="left",padx=2)
        viewbar=ttk.Frame(self,padding=(7,0,7,2))
        viewbar.pack(fill="x")
        ttk.Button(viewbar,text="Voransicht einpassen",command=self.fit).pack(side="left",padx=(0,2))
        ttk.Button(viewbar,text="−",width=3,command=lambda:self.zoom_step(-1)).pack(side="left")
        ttk.Label(viewbar,text="Zoom").pack(side="left",padx=3)
        self.zoom_spin = ttk.Spinbox(
            viewbar,from_=0.05,to=3.,increment=.1,width=6,
            textvariable=self.zoom,command=self._schedule_draw)
        self.zoom_spin.pack(side="left")
        self.zoom_spin.bind("<Return>",lambda _:self._schedule_draw())
        ttk.Button(viewbar,text="+",width=3,command=lambda:self.zoom_step(1)).pack(side="left")
        ttk.Checkbutton(viewbar,text="Raster / Snap",variable=self.snap,
                        command=self._schedule_draw).pack(side="left",padx=(10,2))
        ttk.Combobox(viewbar,textvariable=self.snap_step,values=(1,2,4,8,16,32),
                     width=3,state="readonly").pack(side="left")
        ttk.Checkbutton(viewbar,text="Proportionen",
                        variable=self.proportional).pack(side="left",padx=5)

        actions=ttk.Frame(self,padding=(7,1,7,4))
        actions.pack(fill="x")
        first_row=ttk.Frame(actions)
        first_row.pack(fill="x")
        second_row=ttk.Frame(actions)
        second_row.pack(fill="x",pady=(3,0))
        for parent,entries in (
            (first_row,(
                ("PNG importieren",self.import_external),
                ("Bild einfügen",self.add_asset),
                ("Original-Pixeleditor",self.open_pixel_editor),
            )),
            (second_row,(
                ("Layout → PNG + Positionsdaten",self.export),
                ("Spieloberfläche anbinden (Noesis)",self.bind_noesis),
            )),
        ):
            for label,callback in entries:
                ttk.Button(parent,text=label,command=callback).pack(
                    side="left",padx=2)
        self.more_menu=tk.Menu(self,tearoff=False)
        for label,callback in (
            ("Kopieren",self.copy),
            ("Einfügen",self.paste),
            ("Duplizieren",self.duplicate),
            ("Löschen",self.delete),
            ("Ebene nach vorne",lambda:self.change_order(1)),
            ("Ebene nach hinten",lambda:self.change_order(-1)),
            ("Asset-Mod-Paket bauen",self.build_mod),
            ("Exportstand prüfen",lambda:self._check_export_status(show_problem=True)),
        ):
            self.more_menu.add_command(label=label,command=callback)
        self.more_button=ttk.Menubutton(first_row,text="Weitere Aktionen ▾",
                                       direction="below",menu=self.more_menu)
        self.more_button.pack(side="left",padx=(8,0))
        ttk.Label(second_row,
                  text="Hinweis: Spielknöpfe bleiben separat.",
                  ).pack(side="left",padx=(8,0))

        host=ttk.PanedWindow(self,orient="horizontal")
        host.pack(fill="both",expand=True,padx=8,pady=2)
        preview=ttk.Frame(host)
        self.inspector_scroll=ScrollableColumn(host,background="#1b222c")
        host.add(preview,weight=5)
        host.add(self.inspector_scroll,weight=2)
        inspector=self.inspector_scroll.body
        preview.rowconfigure(0,weight=1);preview.columnconfigure(0,weight=1)
        self.canvas=tk.Canvas(
            preview,bg="#1a222d",highlightthickness=0,relief="sunken",
            borderwidth=1,cursor="crosshair",takefocus=True)
        self.canvas.grid(row=0,column=0,sticky="nsew")
        sy=ttk.Scrollbar(preview,orient="vertical",command=self.canvas.yview)
        sx=ttk.Scrollbar(preview,orient="horizontal",command=self.canvas.xview)
        sy.grid(row=0,column=1,sticky="ns")
        sx.grid(row=1,column=0,sticky="ew")
        self.canvas.configure(xscrollcommand=sx.set,yscrollcommand=sy.set)
        self.canvas.bind("<ButtonPress-1>",self._down)
        self.canvas.bind("<B1-Motion>",self._move)
        self.canvas.bind("<ButtonRelease-1>",self._up)
        self.canvas.bind("<Double-1>",lambda _:self.open_pixel_editor())
        self.canvas.bind("<Configure>",lambda _:self._schedule_draw())
        self.canvas.bind("<Control-MouseWheel>",self._mouse_zoom)
        self.canvas.bind("<MouseWheel>",self._mouse_scroll)
        self.canvas.bind("<Button-3>",self._show_canvas_menu)

        layer_head=ttk.Frame(inspector)
        layer_head.pack(fill="x",padx=4)
        ttk.Label(layer_head,text="Bildquelle auswählen",
                  font=("Segoe UI",10,"bold")).pack(side="left")
        chooser=ttk.Frame(inspector)
        chooser.pack(fill="x",padx=4,pady=3)
        self.asset_combo=ttk.Combobox(
            chooser,textvariable=self.source_display,state="readonly")
        self.asset_combo.pack(side="left",fill="x",expand=True,padx=(0,4))
        self.asset_combo.bind("<<ComboboxSelected>>",self._picked_source)
        ttk.Button(chooser,text="Einfügen",width=9,
                   command=self.add_asset).pack(side="left")
        ttk.Label(inspector,text="Ebenen (oben = vorne)",
                  font=("Segoe UI",10,"bold")).pack(anchor="w",padx=7,pady=(5,2))
        layers_frame=ttk.Frame(inspector)
        layers_frame.pack(fill="both",expand=True,padx=4,pady=(0,6))
        self.layers=ttk.Treeview(
            layers_frame,columns=("visible","locked","source"),
            show="tree headings",selectmode="extended",height=12)
        self.layers.heading("#0",text="Ebene")
        self.layers.column("#0",width=135,minwidth=75,stretch=True)
        for col,label,width in (("visible","Aug",35),("locked","Schl",35),
                                ("source","PNG",155)):
            self.layers.heading(col,text=label)
            self.layers.column(col,width=width,minwidth=28,stretch=(col=="source"))
        sb=ttk.Scrollbar(layers_frame,orient="vertical",command=self.layers.yview)
        self.layers.configure(yscrollcommand=sb.set)
        sb.pack(side="right",fill="y")
        self.layers.pack(side="left",fill="both",expand=True)
        self.layers.bind("<<TreeviewSelect>>",self._tree_selected)
        self.layers.bind("<Double-1>",self._list_double)
        self.layers.bind("<Button-3>",self._show_layer_menu)

        ttk.Label(inspector,textvariable=self.selection_detail,
                  wraplength=280,justify="left").pack(fill="x",padx=6,pady=(0,4))
        fields=ttk.LabelFrame(inspector,text="Position · Größe · Drehung",padding=6)
        fields.pack(fill="x",padx=4,pady=(0,4))
        mapping=[
            ("x","X"),("y","Y"),("width","Breite"),("height","Höhe"),
            ("rotation","Drehung °"),("opacity","Deckkraft 0–255"),
            ("pivot_x","Pivot X 0–1"),("pivot_y","Pivot Y 0–1"),
        ]
        for idx,(key,label) in enumerate(mapping):
            row=idx//2;col=(idx%2)*2
            ttk.Label(fields,text=label).grid(
                row=row,column=col,sticky="w",padx=(2,3),pady=4)
            var=tk.StringVar(self)
            self._property_vars[key]=var
            ttk.Entry(fields,textvariable=var,width=9).grid(
                row=row,column=col+1,sticky="ew",padx=(0,8))
        fields.columnconfigure(1,weight=1)
        fields.columnconfigure(3,weight=1)
        ttk.Label(fields,text="Anker").grid(
            row=4,column=0,sticky="w")
        self.anchor_var=tk.StringVar(self,value="nw")
        ttk.Combobox(fields,textvariable=self.anchor_var,
                     values=list(ANCHORS),state="readonly",width=10
                     ).grid(row=4,column=1,sticky="ew")
        self.visible_var=tk.BooleanVar(self,value=True)
        self.locked_var=tk.BooleanVar(self,value=False)
        ttk.Checkbutton(fields,text="Sichtbar",variable=self.visible_var).grid(
            row=4,column=2,sticky="w")
        ttk.Checkbutton(fields,text="Sperren",variable=self.locked_var).grid(
            row=4,column=3,sticky="w")
        ttk.Button(fields,text="Werte anwenden",command=self.apply_properties).grid(
            row=5,column=0,columnspan=4,sticky="ew",pady=(5,1))

        align=ttk.LabelFrame(inspector,text="Mehrfachauswahl ausrichten",padding=4)
        align.pack(fill="x",padx=4,pady=(0,4))
        for index,(label,code) in enumerate((
            ("Links","left"),("Mitte X","centerx"),
            ("Rechts","right"),("Oben","top"),
            ("Mitte Y","centery"),("Unten","bottom"),
        )):
            ttk.Button(
                align,text=label,command=lambda c=code:self.align(c),
            ).grid(row=index//3,column=index%3,sticky="ew",padx=2,pady=2)
        for column in range(3):
            align.columnconfigure(column,weight=1)
        ttk.Checkbutton(
            inspector,text="Eigene XAML-Patches in Paket einbeziehen",
            variable=self.include_patches,
        ).pack(fill="x",padx=8,pady=2)
        ttk.Label(inspector,text="Maus: ziehen=verschieben · Griffe=skalieren · "
                  "grüner Griff=drehen · Shift=Mehrfachauswahl/proportional · "
                  "Pfeile=1 px (Shift=10 px) · Strg+C/V/Z/Y/S",
                  wraplength=320,justify="left").pack(
            fill="x",padx=6,pady=5)
        ttk.Label(self,textvariable=self.status,wraplength=1400,
                  justify="left").pack(fill="x",padx=12,pady=7)
        self._sync_properties()
        # On smaller displays the full layer/transform inspector stays
        # scrollable instead of clipping lower controls out of the window.
        self.inspector_scroll.bind_mousewheel()

    def show_layout_help(self):
        messagebox.showinfo(
            "Layout bearbeiten",
            "1. Rechts oben eine vorhandene PNG auswählen und »Bild einfügen« "
            "anklicken. Alternativ »PNG importieren« verwenden.\n\n"
            "2. Auf der Arbeitsfläche ein Bild anklicken und ziehen. "
            "Die gelben Griffe verändern die Größe, der grüne Griff "
            "dreht das Bild. Die rechte Seitenleiste enthält genaue "
            "Positionen und eine Ebenenliste.\n\n"
            "3. »Speichern · Strg+S« bewahrt alle Ebenen, "
            "Positionen und Drehungen für den nächsten Programmstart.\n\n"
            "4. »Layout → PNG + Positionsdaten« berechnet das fertige "
            "Bild für den Export. Bei jeder späteren Änderung muss "
            "dieser Export wiederholt werden.\n\n"
            "5. »Spieloberfläche anbinden (Noesis)« verknüpft "
            "die fertig exportierte Grafik mit einer passenden "
            "XAML-Datei des ausgewählten Spiels. "
            "Das ist keine automatische Verschiebung vorhandener Spielknöpfe.",
            parent=self,
        )

    def _update_guidance(self):
        """A visible next step, distinct from raw export and game installation."""
        advice=layout_advice(
            layer_count=len(self.scene.layers),
            has_source=bool(self.source_choice.get().strip()),
            unsaved=self.is_dirty(),
            export_verified=self._export_verified,
        )
        app=getattr(self.master,"app",None)
        lang=getattr(app,"language",None)
        english=bool(lang is not None and str(lang.get()).upper()=="EN")
        if english:
            translated={
                "image": (
                    "1 / 4 – Place an image" if self.source_choice.get()
                    else "1 / 4 – Open an image",
                    "Select a source PNG on the right, then insert it."
                    if self.source_choice.get() else
                    "Import a PNG, JPEG or WebP file. The original is preserved.",
                    "Insert image" if self.source_choice.get() else "Import PNG",
                ),
                "save": ("2 / 4 – Save layout",
                         "Your layers or positions changed. Save the editable layout first.",
                         "Save layout"),
                "export": ("3 / 4 – Export PNG",
                           "The layout is saved. Export one composited PNG and its positions.",
                           "Export PNG"),
                "ready": ("4 / 4 – PNG ready",
                          "Saved layout and last verified PNG agree. No game was modified.",
                          "Bind game UI"),
            }
            heading,detail,button=translated[advice.stage]
        else:
            heading,detail,button=advice.heading,advice.detail,advice.button
        self.guide_heading.set(heading)
        self.guide_detail.set(detail)
        self.guide_button_text.set(button)
        self.next_button.configure(text=button)
        self._next_action=advice.action
        menu=getattr(self,"more_menu",None)
        if menu is not None and getattr(self,"_translated_menu",None)!=english:
            translations=(
                ("Kopieren","Copy"),
                ("Einfügen","Paste"),
                ("Duplizieren","Duplicate"),
                ("Löschen","Delete"),
                ("Ebene nach vorne","Move layer forward"),
                ("Ebene nach hinten","Move layer backward"),
                ("Asset-Mod-Paket bauen","Build asset mod"),
                ("Exportstand prüfen","Verify export"),
            )
            for index,(de,en) in enumerate(translations):
                menu.entryconfigure(index,label=en if english else de)
            self._translated_menu=english

    def next_step(self):
        """Only a deliberate click can start an import or file write."""
        action=self._next_action
        callback={
            "import":self.import_external,
            "add":self.add_asset,
            "save":self.save,
            "export":self.export,
            "noesis":self.bind_noesis,
        }[action]
        return callback()

    def _check_export_status(self, *, show_problem=False):
        """Re-check export hashes on explicit actions, not every mouse move."""
        self._export_verified=False
        self._export_problem=""
        try:
            if self._save_hash is None or self.is_dirty():
                raise WorkshopError("Layout zuerst speichern.")
            audit_export(self.scene,self.project,scene_sha256=self._save_hash)
        except (ValueError,OSError) as exc:
            self._export_problem=str(exc)
        else:
            self._export_verified=True
        self._update_guidance()
        if show_problem:
            if self._export_verified:
                messagebox.showinfo("Exportstand",
                    "Gespeicherte Positionen, Bilddateien und PNG-Export stimmen überein.",
                    parent=self)
            else:
                messagebox.showwarning("Exportstand",
                    self._export_problem + "\n\n"
                    "Wenn du etwas geändert hast, zuerst speichern "
                    "und dann »Layout → PNG + Positionsdaten« erneut ausführen.",
                    parent=self)
        return self._export_verified

    def _image_saved(self):
        """Pixel edits invalidate a previously baked composite."""
        self._check_export_status()
        self._schedule_draw()

    def _show_layer_menu(self,event):
        uid=self.layers.identify_row(event.y)
        if uid:
            if uid not in self._selection:
                self.select_only(uid)
        try:
            self.more_menu.tk_popup(event.x_root,event.y_root)
        finally:
            self.more_menu.grab_release()
        return "break"

    def _show_canvas_menu(self,event):
        try:
            self.more_menu.tk_popup(event.x_root,event.y_root)
        finally:
            self.more_menu.grab_release()
        return "break"

    def _update_scene_names(self):
        names=sorted(p.name.removesuffix(".scene.json") for p in
                     scene_file(self.project,self.scene.name).parent.glob("*.scene.json"))
        if self.scene.name not in names:
            names.insert(0,self.scene.name)
        self.scene_picker.configure(values=names)

    def _refresh_assets(self):
        assets=[item for item in list_assets(self.project)
                if item.path.suffix.lower()==".png"]
        # The user sees the filename FIRST; the full resource key stays
        # unchanged for rendering and tests and never becomes a display label.
        self._asset_choices={
            f"{item.name} · {item.kind}":item.relative_path for item in assets
        }
        self.asset_combo.configure(values=list(self._asset_choices))
        refs=list(self._asset_choices.values())
        if self.source_choice.get() not in refs:
            self.source_choice.set(refs[0] if refs else "")
        self._sync_source_display()

    def _picked_source(self,_event=None):
        relative=self._asset_choices.get(self.source_display.get())
        if relative is not None:
            self.source_choice.set(relative)

    def _sync_source_display(self,*_args):
        selected=self.source_choice.get()
        label=next((name for name,path in self._asset_choices.items()
                    if path==selected),Path(selected).name if selected else "")
        self.source_display.set(label)
        self._update_guidance()

    def _refresh_layers(self):
        self._syncing_tree=True
        self.layers.delete(*self.layers.get_children())
        for layer in reversed(self.scene.layers):
            self.layers.insert("","end",iid=layer.id,
                               text=layer.name or Path(layer.asset).stem,
                               values=("●" if layer.visible else "○",
                                       "🔒" if layer.locked else "—",
                                       Path(layer.asset).name))
        self.layers.selection_set([
            uid for uid in self._selection if self.layers.exists(uid)
        ])
        self._syncing_tree=False
        self._sync_properties()
        self._update_guidance()

    def _tree_selected(self,_event=None):
        if self._syncing_tree:return
        self._selection=list(self.layers.selection())
        self._sync_properties()
        self._schedule_draw()

    def _list_double(self,event):
        row=self.layers.identify_row(event.y)
        if not row:return
        col=self.layers.identify_column(event.x)
        if col=="#1":self.toggle_visible(row)
        elif col=="#2":self.toggle_locked(row)
        else:self.select_only(row)

    def select_only(self,uid):
        self._selection=[uid] if uid and any(
            item.id==uid for item in self.scene.layers) else []
        self._refresh_layers()
        self._schedule_draw()

    def _sync_properties(self):
        layer=layer_by_id(self.scene,self._selection[0]) if (
            len(self._selection)==1 and any(
                l.id==self._selection[0] for l in self.scene.layers)) else None
        app=getattr(self.master,"app",None)
        language=getattr(app,"language",None)
        english=bool(language and str(language.get()).upper()=="EN")
        if layer is None:
            if english:
                info=("Multiple layers selected – use alignment tools below."
                      if len(self._selection)>1 else
                      "Select one layer to edit its position and size.")
            else:
                info=("Mehrere Ebenen ausgewählt – zum Ausrichten unten die "
                      "entsprechende Funktion verwenden."
                      if len(self._selection)>1 else
                      "Eine Ebene auswählen, um Position und Größe zu ändern.")
            self.selection_detail.set(info)
            for value in self._property_vars.values():value.set("")
            return
        self.selection_detail.set(
            ("Selected: " if english else "Ausgewählt: ")
            +(layer.name or Path(layer.asset).name))
        for key,var in self._property_vars.items():
            val=getattr(layer,key)
            var.set(str(round(val,2)) if type(val) is float else str(val))
        self.anchor_var.set(layer.anchor)
        self.visible_var.set(layer.visible)
        self.locked_var.set(layer.locked)

    def _apply_initial_language(self, window=None):
        """Use the Suite language for this editor or a related child dialog."""
        target=window if window is not None else self
        app=getattr(self.master,"app",None)
        if app is None or not hasattr(app,"language"):
            return
        if str(app.language.get()).upper()!="EN":
            return
        module=sys.modules.get(type(app).__module__)
        language=getattr(module,"LANG",None) if module else None
        if language is not None and hasattr(language,"apply"):
            language.apply(target)
            return
        # Fallback for a test-loaded .pyw module not in sys.modules.
        from pathlib import Path
        root=Path(__file__).resolve().parents[1]
        data=json.loads((root/"config/suite-sprachen.json").read_text("utf8"))
        table=data.get("en",{})
        queue=[target]
        while queue:
            widget=queue.pop()
            queue.extend(widget.winfo_children())
            try:
                if "text" in widget.keys():
                    original=widget.cget("text")
                    if original in table:
                        widget.configure(text=table[original])
                        widget._sprache_de=original
            except (tk.TclError,AttributeError):
                pass
            if isinstance(widget,ttk.Treeview):
                for col in ("#0",*widget["columns"]):
                    original=widget.heading(col,"text")
                    if original in table:
                        widget.heading(col,text=table[original])
            if isinstance(widget,ttk.Notebook):
                for tab in widget.tabs():
                    original=widget.tab(tab,"text")
                    if original in table:
                        widget.tab(tab,text=table[original])

    def _zoom_value(self):
        try:ratio=float(self.zoom.get())
        except (ValueError,tk.TclError):ratio=.5
        return max(.05,min(3.,ratio))

    def zoom_step(self,delta):
        self.zoom.set(round(max(.05,min(3.,self._zoom_value()*(1.2 if delta>0 else 1/1.2))),3))
        self._schedule_draw()

    def fit(self):
        width=max(150,self.canvas.winfo_width()-2*_CANVAS_MARGIN-10)
        height=max(140,self.canvas.winfo_height()-2*_CANVAS_MARGIN-10)
        value=min(2.,width/self.scene.width,height/self.scene.height)
        self.zoom.set(round(max(.05,value),4))
        self._schedule_draw()
        # Fit is a deliberate viewport operation. Refresh geometry now so
        # the next mouse event cannot hit an old coordinate transform.
        self._flush_draw()

    def _mouse_zoom(self,event):
        self.zoom_step(1 if event.delta>0 else -1)
        return "break"

    def _mouse_scroll(self,event):
        self.canvas.yview_scroll(-1 if event.delta>0 else 1,"units")
        return "break"

    def _schedule_draw(self):
        if self._render_pending:return
        self._render_pending=True
        self._render_job=self.after(22,self._redraw)

    def _flush_draw(self):
        """Keep gesture hit-testing in step with the visible selection box."""
        if not self._render_pending:
            return
        if self._render_job is not None:
            try:
                self.after_cancel(self._render_job)
            except tk.TclError:
                pass
        self._redraw()

    def _redraw(self):
        self._render_pending=False
        self._render_job=None
        if not self.canvas.winfo_exists():return
        try:
            ratio=self._zoom_value()
            width=max(1,round(self.scene.width*ratio))
            height=max(1,round(self.scene.height*ratio))
            if width*height>_MAX_DISPLAY_PIXELS:
                ratio=min(ratio,math.sqrt(_MAX_DISPLAY_PIXELS/
                                       (self.scene.width*self.scene.height)))
                width=max(1,round(self.scene.width*ratio))
                height=max(1,round(self.scene.height*ratio))
                self.zoom.set(round(ratio,4))
            if ratio<=1:
                picture,draw_ratio=render_preview(
                    self.scene,self.project,max_width=width,max_height=height)
                width,height=picture.size
            else:
                picture=render_scene(self.scene,self.project).resize(
                    (width,height),Image.Resampling.NEAREST)
                draw_ratio=ratio
            self._scale=draw_ratio
            self._image_tk=ImageTk.PhotoImage(picture)
            self.canvas.delete("all")
            margin=_CANVAS_MARGIN
            self.canvas.create_rectangle(
                margin-1,margin-1,margin+width+1,margin+height+1,
                outline="#87929d",width=1)
            self.canvas.create_image(
                margin,margin,anchor="nw",image=self._image_tk)
            if not self.scene.layers:
                app=getattr(self.master,"app",None)
                lang=getattr(app,"language",None)
                english=bool(lang and str(lang.get()).upper()=="EN")
                if width < 270:
                    guide=("Insert an image above." if english
                           else "Oben ein Bild einfügen.")
                else:
                    guide=(("Your menu or HUD starts here.\n\n"
                            "Import a PNG above, or select a source "
                            "on the right and insert it.") if english else
                           ("Hier entsteht dein Menü oder HUD.\n\n"
                            "Oben »PNG importieren« wählen oder rechts "
                            "ein vorhandenes Bild auswählen und »Bild einfügen« klicken."))
                self.canvas.create_text(
                    margin+max(20,width//2),margin+max(26,height//3),
                    anchor="center",width=max(130,width-45),
                    text=guide,font=("Segoe UI",11,"bold"),fill="#d1dce6",
                    justify="center",
                )
            if self.snap.get() and self.snap_step.get()>1:
                step=self.snap_step.get()*draw_ratio
                if step>=8:
                    for x in range(0,self.scene.width+1,self.snap_step.get()):
                        sx=margin+x*draw_ratio
                        self.canvas.create_line(sx,margin,sx,margin+height,
                                                fill="#3c505c",dash=(2,8))
                    for y in range(0,self.scene.height+1,self.snap_step.get()):
                        sy=margin+y*draw_ratio
                        self.canvas.create_line(margin,sy,margin+width,sy,
                                                fill="#3c505c",dash=(2,8))
            self._handles.clear()
            for layer in self.scene.layers:
                if layer.id not in self._selection or not layer.visible:
                    continue
                corners=rotated_corners(layer)
                coords=[z for point in corners for z in (
                    margin+point[0]*draw_ratio,margin+point[1]*draw_ratio)]
                self.canvas.create_polygon(
                    *coords,outline=_COLOURS["selection"],
                    fill="",width=2,dash=(4,2))
                if len(self._selection)==1:
                    positions=self._corner_grips(corners,draw_ratio)
                    for key,(sx,sy) in positions.items():
                        if key=="rotate":
                            self.canvas.create_oval(
                                sx-6,sy-6,sx+6,sy+6,outline="#163c38",
                                fill=_COLOURS["rotate"],width=2)
                        else:
                            self.canvas.create_rectangle(
                                sx-5,sy-5,sx+5,sy+5,
                                fill="#1b2732",outline=_COLOURS["selection"],width=2)
                        self._handles[key]=(sx,sy)
                    pivot=pivot_of(layer)
                    x=margin+pivot[0]*draw_ratio
                    y=margin+pivot[1]*draw_ratio
                    self.canvas.create_line(x-7,y,x+7,y,fill="#73e3c8")
                    self.canvas.create_line(x,y-7,x,y+7,fill="#73e3c8")
            self.canvas.configure(
                scrollregion=(0,0,max(self.canvas.winfo_width(),
                    width+2*margin),max(self.canvas.winfo_height(),height+2*margin)))
            self._status_coordinates()
        except (OSError,ValueError,tk.TclError) as exc:
            self.status.set("Layout-Vorschau nicht möglich: "+str(exc))

    @staticmethod
    def _corner_grips(corners,scale):
        """Put grips OUTSIDE small sprites so clicking the image always moves it.

        On a zoomed-out 8x8 HUD icon, handles at the literal corners overlap
        the entire source image. Photoshop-like direct manipulation requires
        a separate interactive grip ring around such icons.
        """
        tl,tr,br,bl=corners
        width=math.dist(tl,tr) or 1.
        height=math.dist(tl,bl) or 1.
        ux,uy=(tr[0]-tl[0])/width,(tr[1]-tl[1])/width
        vx,vy=(bl[0]-tl[0])/height,(bl[1]-tl[1])/height
        cx=sum(point[0] for point in corners)/4
        cy=sum(point[1] for point in corners)/4
        # At least 22 screen pixels separate each handle from the image
        # centre, independent of zoom and the source sprite's dimensions.
        half_w=max(22.,width*scale/2)
        half_h=max(22.,height*scale/2)
        slots={
            "nw":(-1,-1),"n":(0,-1),"ne":(1,-1),"e":(1,0),
            "se":(1,1),"s":(0,1),"sw":(-1,1),"w":(-1,0),
            "rotate":(0,-1-27/half_h),
        }
        return {
            key:(
                _CANVAS_MARGIN+cx*scale+ux*half_w*i+vx*half_h*j,
                _CANVAS_MARGIN+cy*scale+uy*half_w*i+vy*half_h*j,
            )
            for key,(i,j) in slots.items()
        }

    def _canvas_xy(self,event):
        ratio=getattr(self,"_scale",self._zoom_value())
        return ((self.canvas.canvasx(event.x)-_CANVAS_MARGIN)/ratio,
                (self.canvas.canvasy(event.y)-_CANVAS_MARGIN)/ratio)

    def _status_coordinates(self):
        n=len(self._selection)
        self.status.set(
            f"{self.scene.name} · {self.scene.width}×{self.scene.height} · "
            f"{len(self.scene.layers)} Ebenen · {n} gewählt · "
            f"Zoom {self._zoom_value():.0%} · "
            f"{'ungespeichert' if self.is_dirty() else 'gespeichert'} · "
            "Drag=verschieben · Griffe=skalieren · grüner Griff=drehen · "
            "Shift=mehrfach oder proportional")

    def _down(self,event):
        # A user can click immediately after adding a layer or resizing the
        # window. Flush delayed rendering so hit-testing uses the SAME zoom,
        # positions and transform handles the canvas is about to display.
        self._flush_draw()
        self.canvas.focus_set()
        x,y=self._canvas_xy(event)
        mx,my=self.canvas.canvasx(event.x),self.canvas.canvasy(event.y)
        ctrl=bool(event.state & 0x0004)
        shift=bool(event.state & 0x0001)
        # Small sprites can place several grips within ten screen pixels.
        # Pick the closest grip, not the first in dictionary order, or a
        # bottom-right resize can accidentally become a top-right resize.
        grips=[((mx-px)**2+(my-py)**2,k)
               for k,(px,py) in self._handles.items()]
        nearest=min(grips,default=(float("inf"),None))
        handle=nearest[1] if nearest[0]<=10**2 else None
        if handle and len(self._selection)==1 and not ctrl:
            item=layer_by_id(self.scene,self._selection[0])
            if not item.locked:
                self._begin_drag("rotate" if handle=="rotate" else "resize",
                                 (x,y),handle)
                return
        item=hit_test(self.scene,x,y)
        if ctrl or shift:
            if item:
                if item in self._selection:self._selection.remove(item)
                else:self._selection.append(item)
        elif item and item in self._selection:
            pass
        else:
            self._selection=[item] if item else []
        self._refresh_layers()
        self._schedule_draw()
        if item and not (shift or ctrl) and not layer_by_id(self.scene,item).locked:
            self._begin_drag("move",(x,y),None)

    def _begin_drag(self,mode,origin,grip):
        self._drag_base=self.scene.clone()
        self._drag_origin=origin
        self._drag_mode=mode
        self._drag_handle=grip
        if mode=="rotate":
            item=layer_by_id(self._drag_base,self._selection[0])
            px,py=pivot_of(item)
            self._rotate_pointer_angle=math.atan2(origin[1]-py,origin[0]-px)

    def _move(self,event):
        if self._drag_base is None or self._drag_origin is None:return
        x,y=self._canvas_xy(event)
        dx,dy=x-self._drag_origin[0],y-self._drag_origin[1]
        self.history.scene=self._drag_base.clone()
        try:
            snap=self.snap_step.get() if self.snap.get() else 1
            if self._drag_mode=="move":
                for uid in self._selection:
                    layer=layer_by_id(self.scene,uid)
                    if not layer.locked:
                        move_layer(self.scene,uid,dx,dy,snap=snap)
            elif self._drag_mode=="resize":
                resize_handle(self.scene,self._selection[0],self._drag_handle,
                              dx,dy,keep_ratio=(
                                  self.proportional.get() or bool(event.state & 1)),
                              snap=snap)
            elif self._drag_mode=="rotate":
                item=layer_by_id(self.scene,self._selection[0])
                px,py=pivot_of(item)
                current=math.atan2(y-py,x-px)
                delta=math.degrees(current-self._rotate_pointer_angle)
                angle=item.rotation+delta
                if self.snap.get() or bool(event.state & 1):
                    angle=round(angle/15)*15
                set_geometry(self.scene,item.id,rotation=round(angle,3))
        except (ValueError,OSError,WorkshopError) as exc:
            self.history.scene=self._drag_base.clone()
            self.status.set(str(exc))
        self._schedule_draw()

    def _up(self,event):
        if self._drag_base is None:return
        old=self._drag_base
        self._drag_base=None
        self._drag_origin=None
        self._drag_mode=None
        self._drag_handle=None
        self.history.commit(old)
        self._refresh_layers()
        self._schedule_draw()
        # The next click must use the just-moved resize grips, even if the
        # user immediately starts another gesture before Tk's 22 ms timer.
        self._flush_draw()

    def _keyboard_nudge(self,event,dx,dy):
        if not self._selection:return None
        factor=10 if event.state & 1 else 1
        old=self.scene.clone()
        try:
            for uid in self._selection:
                layer=layer_by_id(self.scene,uid)
                if not layer.locked:
                    move_layer(self.scene,uid,dx*factor,dy*factor,snap=1)
            self.history.commit(old)
            self._refresh_layers()
            self._schedule_draw()
        except (ValueError,WorkshopError) as exc:
            self.status.set(str(exc))
        return "break"

    def apply_properties(self):
        if len(self._selection)!=1:
            messagebox.showinfo("Layout","Genau eine Ebene wählen.",parent=self)
            return
        uid=self._selection[0]
        old=self.scene.clone()
        try:
            fields=self._property_vars
            changes=dict(x=float(fields["x"].get()),y=float(fields["y"].get()),
                width=int(fields["width"].get()),
                height=int(fields["height"].get()),
                rotation=float(fields["rotation"].get()),
                opacity=int(fields["opacity"].get()),
                pivot_x=float(fields["pivot_x"].get()),
                pivot_y=float(fields["pivot_y"].get()),
                anchor=self.anchor_var.get(),
                visible=bool(self.visible_var.get()),
                locked=bool(self.locked_var.get()))
            current=layer_by_id(self.scene,uid)
            if current.locked and changes["locked"] is False:
                set_geometry(self.scene,uid,locked=False)
            set_geometry(self.scene,uid,**changes)
            self.history.commit(old)
            self._refresh_layers()
            self._schedule_draw()
        except (ValueError,OSError) as exc:
            self.history.scene=old
            messagebox.showerror("Transformationswerte",str(exc),parent=self)

    def _selected_layers(self):
        return [layer_by_id(self.scene,uid) for uid in self._selection
                if any(l.id==uid for l in self.scene.layers)]

    def align(self,where):
        layers=[l for l in self._selected_layers() if not l.locked]
        if len(layers)<2:return
        old=self.scene.clone()
        def interval(layer):
            ox,oy=origin_of(layer)
            return ox,oy,ox+layer.width,oy+layer.height
        spans=[interval(layer) for layer in layers]
        if where in ("left","right","centerx"):
            target=(min(x[0] for x in spans) if where=="left" else
                    max(x[2] for x in spans) if where=="right" else
                    sum((x[0]+x[2])/2 for x in spans)/len(spans))
            for layer,bb in zip(layers,spans):
                current=bb[0] if where=="left" else bb[2] if where=="right" else (bb[0]+bb[2])/2
                move_layer(self.scene,layer.id,target-current,0,snap=1)
        else:
            target=(min(x[1] for x in spans) if where=="top" else
                    max(x[3] for x in spans) if where=="bottom" else
                    sum((x[1]+x[3])/2 for x in spans)/len(spans))
            for layer,bb in zip(layers,spans):
                current=bb[1] if where=="top" else bb[3] if where=="bottom" else (bb[1]+bb[3])/2
                move_layer(self.scene,layer.id,0,target-current,snap=1)
        self.history.commit(old)
        self._refresh_layers()
        self._schedule_draw()

    def _commit_change(self,old):
        self.history.commit(old)
        self._refresh_layers()
        self._schedule_draw()
        self._flush_draw()

    def add_asset(self):
        relative=self.source_choice.get().strip()
        if not relative:
            messagebox.showinfo("Ebene einfügen",
                "Bitte zuerst ein PNG aus dem Werkstattordner wählen.",
                parent=self)
            return
        old=self.scene.clone()
        try:
            layer=add_layer(self.scene,self.project,relative)
            self._selection=[layer.id]
            self._commit_change(old)
            self.status.set("Neue Ebene eingefügt: "+relative+
                            " · mit der Maus ziehen oder mit Griffen skalieren.")
        except (OSError,ValueError) as exc:
            self.history.scene=old
            messagebox.showerror("Ebene einfügen",str(exc),parent=self)

    def import_external(self):
        picked=filedialog.askopenfilename(
            parent=self,title="PNG/JPEG/WebP als neue Ebene importieren",
            filetypes=[("Bilder","*.png *.jpg *.jpeg *.webp")])
        if not picked:return
        try:
            copied=import_image(picked,project=self.project,folder="Menüs / UI-Bilder")
            self._refresh_assets()
            self.source_choice.set(copied.relative_to(self.project).as_posix())
            self.add_asset()
        except (ValueError,OSError) as exc:
            messagebox.showerror("Bildimport",str(exc),parent=self)

    def _image_from_clipboard(self):
        try:
            result=ImageGrab.grabclipboard()
        except (OSError,NotImplementedError):
            return None
        if not isinstance(result,Image.Image):
            return None
        if result.width*result.height>16_777_216:
            raise WorkshopError("Clipboard image exceeds 16.7 million pixels")
        name=simpledialog.askstring(
            "Bild aus Zwischenablage","Neuer PNG-Ressourcenname:",
            parent=self,initialvalue="EingefuegtesBild")
        if not name:return None
        output=_metadata_dir(self.project) / "clipboard-temp"
        output.mkdir(parents=True,exist_ok=True)
        raw=output / (uuid.uuid4().hex+".png")
        try:
            result.convert("RGBA").save(raw,format="PNG")
            return import_image(raw,project=self.project,
                                name=name,folder="Menüs / UI-Bilder")
        finally:
            raw.unlink(missing_ok=True)

    def copy(self):
        self._clipboard=[item.as_json() for item in self._selected_layers()]
        if self._clipboard:
            self.status.set(f"{len(self._clipboard)} Ebene(n) zum Einfügen vorgemerkt.")

    def paste(self):
        if not self._clipboard:
            try:
                copied=self._image_from_clipboard()
                if copied is None:
                    messagebox.showinfo(
                        "Einfügen","Erst eine Ebene kopieren oder eine "
                        "PNG-Grafik in die Windows-Zwischenablage legen.",
                        parent=self)
                    return
                self._refresh_assets()
                self.source_choice.set(copied.relative_to(self.project).as_posix())
                self.add_asset()
                return
            except (OSError,ValueError) as exc:
                messagebox.showerror("Zwischenablage",str(exc),parent=self)
                return
        old=self.scene.clone()
        try:
            copied=[]
            for row in self._clipboard:
                if len(self.scene.layers)>=256:
                    raise WorkshopError("Maximum 256 layers")
                item=Layer(**row)
                # Asset must still exist and be inside this work-only project.
                from hud_menu_workspace import _existing
                _existing(self.project,item.asset)
                item.id=uuid.uuid4().hex
                item.x+=20
                item.y+=20
                item.name=(item.name or "Ebene")+" Kopie"
                item.locked=False
                item.validate(self.project)
                self.scene.layers.append(item)
                copied.append(item.id)
            self._selection=copied
            self._commit_change(old)
        except (ValueError,OSError) as exc:
            self.history.scene=old
            messagebox.showerror("Ebene einfügen",str(exc),parent=self)

    def duplicate(self):
        if not self._selection:return
        old=self.scene.clone()
        try:
            copied=[]
            for item in self._selection:
                layer=duplicate_layer(self.scene,item,dx=18,dy=18)
                copied.append(layer.id)
            self._selection=copied
            self._commit_change(old)
        except (ValueError,OSError) as exc:
            self.history.scene=old
            messagebox.showerror("Duplizieren",str(exc),parent=self)

    def delete(self):
        if not self._selection:return
        old=self.scene.clone()
        try:
            remove_layers(self.scene,set(self._selection))
            self._selection=[]
            self._commit_change(old)
        except (ValueError,OSError) as exc:
            messagebox.showerror("Ebene löschen",str(exc),parent=self)

    def change_order(self,direction):
        if len(self._selection)!=1:return
        old=self.scene.clone()
        try:
            reorder(self.scene,self._selection[0],direction)
            self._commit_change(old)
        except (ValueError,OSError) as exc:
            self.status.set(str(exc))

    def toggle_visible(self,uid=None):
        uid=uid or (self._selection[0] if len(self._selection)==1 else None)
        if not uid:return
        old=self.scene.clone()
        layer=layer_by_id(self.scene,uid)
        set_geometry(self.scene,uid,visible=not layer.visible)
        self._commit_change(old)

    def toggle_locked(self,uid=None):
        uid=uid or (self._selection[0] if len(self._selection)==1 else None)
        if not uid:return
        old=self.scene.clone()
        layer=layer_by_id(self.scene,uid)
        set_geometry(self.scene,uid,locked=not layer.locked)
        self._commit_change(old)

    def open_pixel_editor(self):
        if len(self._selection)!=1:return
        item=layer_by_id(self.scene,self._selection[0])
        try:
            from hud_menu_workspace import _existing
            path=_existing(self.project,item.asset)
            from suite_hud_menu_editor import HudMenuPixelEditor
            editor=HudMenuPixelEditor(
                self,path,project=self.project,after_save=self._image_saved)
            editor.focus_set()
        except (OSError,ValueError) as exc:
            messagebox.showerror("Pixel bearbeiten",str(exc),parent=self)

    def undo(self):
        if self.history.undo():
            self._selection=[uid for uid in self._selection if any(
                item.id==uid for item in self.scene.layers)]
            self._refresh_layers()
            self._schedule_draw()

    def redo(self):
        if self.history.redo():
            self._refresh_layers()
            self._schedule_draw()

    def is_dirty(self):
        # A pristine, empty layout has no file yet, but has no edits to lose.
        # Export and Noesis still explicitly require a saved scene checksum.
        return self._last_saved!=self.scene.as_json()

    def save(self):
        try:
            path,etag=save_scene(
                self.scene,self.project,expected_hash=self._save_hash)
            self._save_hash=etag
            self._last_saved=self.scene.as_json()
            self.scene_name.set(self.scene.name)
            self._update_scene_names()
            try:
                save_session(self.project,scene=self.scene.name)
            except (OSError,ValueError):
                pass  # The editable scene is already safely saved to disk.
            self.status.set("Layout und sämtliche Positionen dauerhaft gespeichert: "+str(path))
            self._check_export_status()
            return True
        except (OSError,ValueError) as exc:
            messagebox.showerror("Layout speichern",str(exc),parent=self)
            return False

    def _can_discard(self):
        if not self.is_dirty():return True
        result=messagebox.askyesnocancel(
            "Layoutänderungen",
            "Das aktuelle Layout enthält ungespeicherte Positionen. "
            "Vorher speichern?",
            parent=self,default="yes")
        if result is None:return False
        return self.save() if result else True

    def new_scene(self):
        if not self._can_discard():return
        name=simpledialog.askstring(
            "Neues Layout","Projektkennung (ASCII, ohne Leerzeichen):",
            parent=self,initialvalue="menu-layout-2")
        if not name:return
        w=simpledialog.askinteger(
            "Layoutbreite","Pixelbreite:",parent=self,
            initialvalue=1280,minvalue=1,maxvalue=4096)
        if w is None:return
        h=simpledialog.askinteger(
            "Layouthöhe","Pixelhöhe:",parent=self,
            initialvalue=720,minvalue=1,maxvalue=4096)
        if h is None:return
        try:
            target=scene_file(self.project,name)
            if target.exists():
                raise WorkshopError("This scene name already exists; choose Load")
            if w*h>16_777_216:
                raise WorkshopError("Scene is too large")
            self.history=History(Scene(name=name,width=w,height=h))
            self._selection=[]
            self._save_hash=None
            self._last_saved=self.scene.as_json()
            self.scene_name.set(name)
            self._update_scene_names()
            self._refresh_layers()
            self.fit()
            self._check_export_status()
        except (ValueError,OSError) as exc:
            messagebox.showerror("Neues Layout",str(exc),parent=self)

    def reload_scene(self):
        if not self._can_discard():return
        selected=self.scene_name.get()
        try:
            scene,etag=load_scene(self.project,selected)
            self.history=History(scene)
            self._save_hash=etag
            self._last_saved=self.scene.as_json()
            self._selection=[]
            self._refresh_layers()
            self.fit()
            self._check_export_status()
            try:
                save_session(self.project,scene=selected)
            except (OSError,ValueError):
                pass
            self.status.set("Positionen und Ebenen geladen: "+str(scene_file(self.project,selected)))
        except (ValueError,OSError) as exc:
            messagebox.showerror("Layout laden",str(exc),parent=self)

    def export(self):
        if not self.scene.layers:
            messagebox.showinfo("Layout-Export",
                "Zuerst mindestens eine Ebene in die Vorschau einfügen.",
                parent=self)
            return
        target=simpledialog.askstring(
            "UI-Ressourcenschlüssel",
            "Ziel-PNG unter Override/Assets/GUI/Images/\n"
            "Bestehende Noesis-XAML-Referenzen werden NICHT automatisch geändert.\n"
            "Name der zusammengesetzten Grafik:",
            parent=self,
            initialvalue=Path(self.scene.target_resource).stem if (
                self.scene.target_resource) else self.scene.name+"-Composite")
        if not target:return
        old=self.scene.clone()
        try:
            from hud_menu_workspace import _relative
            relative="Override/Assets/GUI/Images/"+filename(target)
            _relative(relative)
            self.scene.target_resource=relative
            self.history.commit(old)
            if not self.save():return
            result=export_composition(
                self.scene,self.project,resource_name=target,
                scene_sha256=self._save_hash)
            self._check_export_status()
            self.status.set("Exportiert: "+result["resource"]+
                " · transformierte PNG-Pixel + Positionsmanifest gespeichert. "
                "XAML-/Noesis-Einbau bleibt ein gesonderter Zuordnungsschritt.")
            if self.after_export:self.after_export()
            messagebox.showinfo("Layout erfolgreich exportiert",
                "Composite PNG:\n"+result["png"]+
                "\n\nPositionen und Ebenen:\n"+result["manifest"]+
                "\n\nDiese PNG wird vom DLL-freien Asset-Modpaket verarbeitet. "
                "Ein unbekannter XAML-ResourceKey wird nicht automatisch aktiviert.",
                parent=self)
            return result
        except (OSError,ValueError) as exc:
            messagebox.showerror("Layout-Export",str(exc),parent=self)
            return None

    def bind_noesis(self):
        """Choose an existing game/XAML Grid and package its static overlay.

        No anonymous XPath guess or write to the installed game is allowed.
        """
        try:
            if self.is_dirty() or self._save_hash is None:
                raise WorkshopError(
                    "Layout speichern und die aktuelle PNG zunächst exportieren"
                )
            audit_export(self.scene,self.project,scene_sha256=self._save_hash)
            old=getattr(self,"_noesis_binding_window",None)
            if old is not None and old.winfo_exists():
                old.lift()
                old.focus_set()
                return old
            from suite_hud_menu_noesis_dialog import NoesisBindingDialog
            window=NoesisBindingDialog(self,self)
            self._noesis_binding_window=window
            window.focus_set()
            return window
        except (OSError,ValueError) as exc:
            messagebox.showerror("Spieloberfläche anbinden",str(exc),parent=self)
            return None

    def build_mod(self):
        if self.is_dirty() and not self.save():return
        if not self.scene.target_resource or not (
            self.project/self.scene.target_resource).is_file():
            messagebox.showinfo("Paket bauen",
                "Zuerst »Layout → PNG + Positionsdaten« ausführen; "
                "nur gespeicherte Layouts können exportiert werden.",parent=self)
            return
        try:
            # A stale position or changed input image can never silently reuse
            # a former baked PNG, even when the old file still exists.
            attestation=audit_export(
                self.scene,self.project,scene_sha256=self._save_hash)
        except (OSError,ValueError) as exc:
            messagebox.showerror(
                "Paketprüfung",
                "Gespeichertes Layout und letzter PNG-Export stimmen nicht "
                "mehr überein. Layout erneut exportieren. "+str(exc),
                parent=self,
            )
            return
        guid=simpledialog.askstring(
            "Asset-Mod GUID","GUID des neuen Modpakets:",
            parent=self,initialvalue="hudmenulayout")
        if not guid:return
        display=simpledialog.askstring(
            "Modpaketname","Anzeigename:",
            parent=self,initialvalue="HUD und Menu Layout")
        if not display:return
        if not messagebox.askyesno(
            "DLL-freies Modpaket erstellen",
            f"Die zusammengesetzte Grafik {attestation['resource']} "
            f"als neues Manifest-0-Paket bauen?\n"
            f"Eigene XAML-Patches einschließen: {self.include_patches.get()}\n"
            "Rohbilder werden NICHT automatisch als Spiel-Overrides "
            "ausgeliefert. Keine Spielinstallation und kein SE-Eingriff.",
            parent=self,default="no"):
            return
        try:
            from se_asset_package import build
            source=prepare_package_source(
                self.scene,self.project,scene_sha256=self._save_hash,
                include_patches=self.include_patches.get())
            result=build(source,guid,name=display,author="Sprite Suite")
            self.status.set("Modpaket erstellt: "+result["zip"])
            messagebox.showinfo("Asset-Mod erstellt",
                result["asset_mod_folder"]+"\n"+result["zip"]+
                "\nNicht automatisch installiert.",parent=self)
            return result
        except (OSError,ValueError) as exc:
            messagebox.showerror("Modpaket nicht erstellt",str(exc),parent=self)
            return None

    def _shortcut_save(self,event):
        self.save();return "break"

    def _shortcut_undo(self,event):
        self.undo();return "break"

    def _shortcut_redo(self,event):
        self.redo();return "break"

    def _shortcut_copy(self,event):
        if event.widget is self.canvas or event.widget is self.layers:
            self.copy();return "break"

    def _shortcut_paste(self,event):
        if event.widget is self.canvas or event.widget is self.layers:
            self.paste();return "break"

    def _shortcut_delete(self,event):
        if event.widget is self.canvas or event.widget is self.layers:
            self.delete();return "break"

    def _shortcut_clear(self,event):
        self._selection=[]
        self._refresh_layers()
        self._schedule_draw()
        return "break"

    def _zoom_in(self,event):
        self.zoom_step(1);return "break"

    def _zoom_out(self,event):
        self.zoom_step(-1);return "break"

    def close_editor(self):
        if not self._can_discard():return
        self.destroy()

    def destroy(self):
        """Release Tk callbacks even when the editor is closed very quickly."""
        for name in ("_after_fit","_after_lang","_after_guidance","_render_job"):
            job=getattr(self,name,None)
            if job is not None:
                try:
                    self.after_cancel(job)
                except tk.TclError:
                    pass
                setattr(self,name,None)
        token=getattr(self,"_source_trace",None)
        if token is not None:
            try:
                self.source_choice.trace_remove("write",token)
            except tk.TclError:
                pass
            self._source_trace=None
        super().destroy()

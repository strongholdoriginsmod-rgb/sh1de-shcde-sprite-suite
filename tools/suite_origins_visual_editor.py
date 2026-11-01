"""Free-form graphical Noesis menu/page authoring over ORIGINAL XAML structure.

The complete XML tree stays editable; preview overlays are authoring aids, not
a pixel-identical Noesis renderer. Existing game installation is read-only.
Exports keep editable snapshots and update an asset-only Script Extender patch.
"""
from __future__ import annotations

from math import isfinite
from pathlib import Path
import re
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog, colorchooser

from PIL import Image, ImageTk

from origins_visual_document import (
    VisualXamlDocument, apply_existing_patch, PRES, XNS, WorkshopError,
)
from hud_menu_workspace import import_image

CONTAINERS={"UserControl","Page","Window","Grid","Canvas","StackPanel",
            "DockPanel","WrapPanel","Border","Viewbox","ScrollViewer",
            "UniformGrid","ContentControl","ContentPresenter"}
DRAWABLE=CONTAINERS | {"Image","Button","TextBlock","TextBox","Label","Rectangle",
                       "Ellipse","CheckBox","ComboBox","ProgressBar","Slider",
                       "ListBox","TabControl","TabItem","RadioButton"}
PALETTE={"Grid","Canvas","Border","StackPanel","Button","Image","TextBlock",
         "Rectangle","Ellipse","CheckBox","TextBox","Viewbox"}
HEX=re.compile(r"^#(?:[A-Fa-f0-9]{6}|[A-Fa-f0-9]{8})$")
NUMERIC=re.compile(r"^[0-9]+(?:\.[0-9]+)?$")
VIEW_W=1920
VIEW_H=1080


def _path_id(path:tuple[int,...])->str:
    return "root" if not path else "p"+("_".join(str(i) for i in path))


def _number(value,default=0.,*,low=-100000,high=100000):
    try:
        n=float(value)
        return n if isfinite(n) and low<=n<=high else default
    except (ValueError,TypeError):
        return default


def _margin(text:str)->tuple[float,float,float,float]:
    try:nums=[float(n.strip()) for n in text.split(",")]
    except ValueError:return (0.,0.,0.,0.)
    if len(nums)==1:return (nums[0],)*4
    if len(nums)==2:return (nums[0],nums[1],nums[0],nums[1])
    if len(nums)==4:return tuple(nums)
    return (0.,0.,0.,0.)


def _color(text:str,fallback:str)->str:
    if HEX.fullmatch(text):
        return "#"+text[-6:]
    return fallback


class OriginsVisualEditor(tk.Toplevel):
    """Visual XAML authoring with full element hierarchy, revisions and patch export."""

    def __init__(self,parent,*,project:Path,source:Path|None=None,after_export=None):
        super().__init__(parent)
        self.project=Path(project)
        self.after_export=after_export
        self.doc:VisualXamlDocument|None=None
        self.selected:tuple[int,...]=()
        self._rows={}
        self._boxes={}
        self._image_refs=[]
        self.reference_image_path:Path|None=None
        self.extra_preview_images=tk.StringVar(self,value="")
        self._drag=None
        self._scroll_scheduled=False
        self.title("SpriteSuite · Noesis Originalseiten frei gestalten")
        self.geometry("1470x920")
        self.minsize(980,640)
        self.title_var=tk.StringVar(self,value="Original-XAML laden oder Revision öffnen")
        self.status=tk.StringVar(self,value="XAML-Elemente frei bearbeiten; native Spielbefehle separat verbinden.")
        self.scope=tk.StringVar(self,value="Gesamtes Dokument")
        self.attribute=tk.StringVar(self,value="Margin")
        self.attr_value=tk.StringVar(self)
        self.text_value=tk.StringVar(self)
        self.tag_value=tk.StringVar(self,value="Button")
        self.name_value=tk.StringVar(self,value="MeinNeuesElement")
        self.angle=tk.StringVar(self,value="0")
        self.preview_width=tk.StringVar(self,value=str(VIEW_W))
        self.preview_height=tk.StringVar(self,value=str(VIEW_H))
        self.zoom=tk.DoubleVar(self,value=1.0)
        self._build()
        self.bind("<Control-z>",lambda e:self.undo())
        self.bind("<Control-y>",lambda e:self.redo())
        self.bind("<Control-s>",lambda e:self.save())
        self.bind("<Delete>",lambda e:self.delete_selected())
        if source is not None:self.open_source(Path(source))

    def _build(self):
        toolbar=ttk.Frame(self,padding=8);toolbar.pack(fill="x")
        ttk.Label(toolbar,text="Noesis · Originalseiten-Designer",
                  font=("Segoe UI",15,"bold")).pack(side="left")
        ttk.Button(toolbar,text="Original-XAML öffnen",command=self.choose_source
                   ).pack(side="left",padx=(18,5))
        ttk.Button(toolbar,text="Vorhandenen Mod-Patch einblenden",
                   command=self.import_patch).pack(side="left",padx=5)
        ttk.Button(toolbar,text="Revision weiterbearbeiten",command=self.open_revision
                   ).pack(side="left",padx=5)
        ttk.Button(toolbar,text="Bildreferenz laden",command=self.choose_reference
                   ).pack(side="left",padx=5)
        ttk.Button(toolbar,text="XAML-Quelltext",command=self.edit_source
                   ).pack(side="left",padx=5)
        ttk.Button(toolbar,text="Originalbilder für Vorschau …",
                   command=self.choose_preview_images).pack(side="left",padx=5)
        ttk.Button(toolbar,text="Native Noesis-Live-Pixel (Spiel) …",
                   command=self.open_native_live_preview).pack(side="left",padx=5)
        ttk.Button(toolbar,text="Rückgängig",command=self.undo).pack(side="left",padx=3)
        ttk.Button(toolbar,text="Wiederholen",command=self.redo).pack(side="left",padx=3)
        ttk.Button(toolbar,text="Patch + Revision speichern",command=self.save
                   ).pack(side="right",padx=4)
        ttk.Label(self,textvariable=self.title_var).pack(fill="x",padx=12,pady=(0,3))
        panes=ttk.Panedwindow(self,orient="horizontal")
        panes.pack(fill="both",expand=True,padx=8,pady=4)
        left=ttk.Frame(panes);middle=ttk.Frame(panes);right=ttk.Frame(panes)
        panes.add(left,weight=2);panes.add(middle,weight=5);panes.add(right,weight=3)
        self._make_tree(left)
        self._make_canvas(middle)
        self._make_inspector(right)
        foot=ttk.Frame(self,padding=7);foot.pack(fill="x")
        ttk.Label(foot,textvariable=self.status,wraplength=1200
                  ).pack(side="left",fill="x",expand=True)
        ttk.Button(foot,text="Asset-Mod ZIP erzeugen",command=self.build_mod
                   ).pack(side="right",padx=4)

    def _make_tree(self,parent):
        ttk.Label(parent,text="Ebenen / originale XAML-Hierarchie",
                  font=("Segoe UI",11,"bold")).pack(anchor="w",pady=(2,6))
        frame=ttk.Frame(parent);frame.pack(fill="both",expand=True)
        self.tree=ttk.Treeview(frame,columns=("typ",),show="tree headings",
                               selectmode="browse")
        self.tree.heading("#0",text="Element / Name")
        self.tree.heading("typ",text="Typ")
        self.tree.column("#0",width=230,minwidth=130)
        self.tree.column("typ",width=93,minwidth=65,stretch=False)
        vert=ttk.Scrollbar(frame,orient="vertical",command=self.tree.yview)
        self.tree.configure(yscrollcommand=vert.set)
        self.tree.pack(side="left",fill="both",expand=True)
        vert.pack(side="right",fill="y")
        self.tree.bind("<<TreeviewSelect>>",self.tree_select)
        row=ttk.Frame(parent);row.pack(fill="x",pady=5)
        ttk.Button(row,text="Duplizieren",command=self.duplicate).pack(side="left")
        ttk.Button(row,text="Löschen",command=self.delete_selected).pack(side="left",padx=3)
        ttk.Button(row,text="↑",width=3,command=lambda:self.reorder(-1)).pack(side="left")
        ttk.Button(row,text="↓",width=3,command=lambda:self.reorder(1)).pack(side="left")
        add=ttk.LabelFrame(parent,text="Neues XAML-Element",padding=5)
        add.pack(fill="x",pady=4)
        ttk.Combobox(add,values=sorted(PALETTE),textvariable=self.tag_value
                     ).pack(fill="x",pady=2)
        ttk.Entry(add,textvariable=self.name_value).pack(fill="x",pady=2)
        ttk.Button(add,text="Unter ausgewähltem Element einfügen",
                   command=self.add_element).pack(fill="x",pady=2)

    def _make_canvas(self,parent):
        bar=ttk.Frame(parent);bar.pack(fill="x",pady=3)
        ttk.Label(bar,text="Seite:").pack(side="left")
        self.scope_combo=ttk.Combobox(bar,textvariable=self.scope,
                        values=("Gesamtes Dokument",),state="readonly",width=29)
        self.scope_combo.pack(side="left",padx=5)
        self.scope_combo.bind("<<ComboboxSelected>>",lambda e:self.redraw())
        ttk.Label(bar,text="Zoom").pack(side="left",padx=4)
        ttk.Scale(bar,from_=0.25,to=2.5,variable=self.zoom,
                  command=lambda *_:self.redraw()).pack(side="left",fill="x",expand=True)
        self.info=ttk.Label(parent,
            text="Annähernde Layoutvorschau, kein echter Noesis-Renderer. "
                 "Original-XAML bleibt strukturell erhalten.",wraplength=680)
        self.info.pack(fill="x",pady=(0,3))
        surface=ttk.Frame(parent)
        surface.pack(fill="both",expand=True)
        self.canvas=tk.Canvas(surface,background="#141b27",
                              highlightthickness=0,cursor="crosshair")
        hs=ttk.Scrollbar(surface,orient="horizontal",command=self.canvas.xview)
        vs=ttk.Scrollbar(surface,orient="vertical",command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=hs.set,yscrollcommand=vs.set)
        self.canvas.grid(row=0,column=0,sticky="nsew")
        vs.grid(row=0,column=1,sticky="ns")
        hs.grid(row=1,column=0,sticky="ew")
        surface.rowconfigure(0,weight=1);surface.columnconfigure(0,weight=1)
        self.canvas.bind("<Configure>",lambda e:self._redraw_idle())
        self.canvas.bind("<ButtonPress-1>",self.canvas_press)
        self.canvas.bind("<B1-Motion>",self.canvas_motion)
        self.canvas.bind("<ButtonRelease-1>",self.canvas_release)
        self.canvas.bind("<Control-MouseWheel>",self.zoom_wheel)
        footer=ttk.Frame(parent);footer.pack(fill="x",pady=5)
        ttk.Label(footer,text="Bühne").pack(side="left")
        ttk.Entry(footer,textvariable=self.preview_width,width=6).pack(side="left",padx=2)
        ttk.Label(footer,text="×").pack(side="left")
        ttk.Entry(footer,textvariable=self.preview_height,width=6).pack(side="left",padx=2)
        ttk.Button(footer,text="Ansicht aktualisieren",command=self.redraw).pack(side="left",padx=5)
        ttk.Button(footer,text="Pixelvergleich echter Noesis-Aufnahmen …",
                   command=self.compare_game_frames).pack(side="right",padx=6)
        ttk.Label(footer,text="Ziehen = Position · Eckpunkt = Größe").pack(side="right")

    def _make_inspector(self,parent):
        ttk.Label(parent,text="Eigenschaften (alle XAML-Attribute)",
                  font=("Segoe UI",11,"bold")).pack(anchor="w",pady=(2,6))
        frame=ttk.Frame(parent);frame.pack(fill="both",expand=True)
        self.props=ttk.Treeview(frame,columns=("value",),show="tree headings",height=17)
        self.props.heading("#0",text="Attribut")
        self.props.heading("value",text="Wert")
        self.props.column("#0",width=155,minwidth=90)
        self.props.column("value",width=215,minwidth=90)
        scroll=ttk.Scrollbar(frame,orient="vertical",command=self.props.yview)
        self.props.configure(yscrollcommand=scroll.set)
        self.props.pack(side="left",fill="both",expand=True)
        scroll.pack(side="right",fill="y")
        self.props.bind("<<TreeviewSelect>>",self.choose_attribute)
        row=ttk.LabelFrame(parent,text="Beliebiges Attribut setzen / entfernen",padding=7)
        row.pack(fill="x",pady=3)
        ttk.Entry(row,textvariable=self.attribute).pack(fill="x",pady=2)
        ttk.Entry(row,textvariable=self.attr_value).pack(fill="x",pady=2)
        actions=ttk.Frame(row);actions.pack(fill="x")
        ttk.Button(actions,text="Anwenden",command=self.apply_attribute).pack(side="left")
        ttk.Button(actions,text="Entfernen",command=self.remove_attribute).pack(side="left",padx=4)
        ttk.Button(actions,text="Farbe wählen",command=self.choose_color).pack(side="left")
        ttk.Label(row,text="Auch Styles, Bindings und neue CommandParameter sind "
                  "editierbar. Die Runtime muss solche Befehle separat bereitstellen.",
                  wraplength=350).pack(fill="x",pady=4)
        content=ttk.LabelFrame(parent,text="Elementtext (XAML-Textknoten)",padding=6)
        content.pack(fill="x",pady=3)
        ttk.Entry(content,textvariable=self.text_value).pack(fill="x")
        ttk.Button(content,text="Text übernehmen",command=self.set_text).pack(anchor="e")
        rotation=ttk.Frame(parent);rotation.pack(fill="x",pady=4)
        ttk.Label(rotation,text="Drehwinkel").pack(side="left")
        ttk.Entry(rotation,textvariable=self.angle,width=9).pack(side="left",padx=3)
        ttk.Button(rotation,text="Drehen",command=self.rotate).pack(side="left")
        ttk.Button(rotation,text="Eigenes Bild einsetzen",command=self.import_selected_image
                   ).pack(side="right")

    def open_native_live_preview(self):
        """Show genuine game/Noesis pixels, never the Python geometry proxy."""
        from suite_noesis_native_live_preview import open_native_noesis_live
        def use_capture(reference:Path):
            self.reference_image_path=reference
            if self.doc is not None:self.redraw()
            self.status.set("Echte native Aufnahme als Layoutreferenz übernommen: "+
                            str(reference)+" · Original-XAML unverändert")
        viewer=open_native_noesis_live(self,on_reference=use_capture)
        viewer.focus_set()
        return viewer

    def compare_game_frames(self):
        """Compare two actual user-supplied game/Noesis PNG captures exactly."""
        if self.doc is None:return
        original=filedialog.askopenfilename(parent=self,
            title="Originaler Spiel-/Noesis-Screenshot (PNG) für Vergleich",
            filetypes=[("PNG-Bild","*.png")])
        if not original:return
        changed=filedialog.askopenfilename(parent=self,
            title="Neu aufgenommener Spiel-/Noesis-Screenshot (PNG)",
            filetypes=[("PNG-Bild","*.png")])
        if not changed:return
        try:
            from origins_noesis_pixel_compare import compare_captured_frames
            from secrets import token_hex
            folder=self.project.parent/".origins-render-comparisons"/(
                "screen-"+token_hex(7))
            evidence=compare_captured_frames(Path(original),Path(changed),folder)
            popup=tk.Toplevel(self)
            popup.title("Noesis-Spielaufnahmen · tatsächliche Pixeldifferenz")
            popup.geometry("950x690")
            ttk.Label(popup,text=(
                str(evidence["changed_pixels"])+" von "+str(evidence["total_pixels"])+
                " Pixeln verschieden (Abweichung "+str(evidence["changed_fraction"])+")"),
                font=("Segoe UI",11,"bold")).pack(pady=8)
            ttk.Label(popup,text="Diese zwei Aufnahmen wurden pixelgenau verglichen. "
                      "Ein nativer Renderer wurde NICHT im Editor aufgerufen.",
                      wraplength=900).pack(pady=5)
            with Image.open(evidence["heatmap"]) as file:
                bitmap=file.convert("RGBA")
            bitmap.thumbnail((910,540),Image.Resampling.LANCZOS)
            photo=ImageTk.PhotoImage(bitmap,master=popup)
            popup._photo=photo
            ttk.Label(popup,image=photo).pack(fill="both",expand=True,pady=6)
            ttk.Label(popup,text="Belege: "+evidence["output"],wraplength=920
                      ).pack(fill="x",padx=12,pady=10)
            self.status.set("Echter Screenshot-Pixelvergleich gespeichert: "+
                            evidence["output"])
            return evidence
        except (OSError,ValueError,RuntimeError) as exc:
            self._message("Noesis-Pixelvergleich",exc)
            return None

    def _message(self,title,exc):
        messagebox.showerror(title,str(exc),parent=self)

    def choose_source(self):
        path=filedialog.askopenfilename(parent=self,
             title="Originale Noesis-XAML-Seite oder Fenster auswählen",
             filetypes=[("Noesis / XAML","*.xaml")])
        if path:self.open_source(Path(path))

    def open_source(self,path:Path):
        try:
            self.doc=VisualXamlDocument(path)
            self.selected=()
            self.scope.set("Gesamtes Dokument")
            self.reference_image_path=None
            self.title_var.set("Originaldatei (nur lesen): "+str(path))
            self.refresh_tree()
            self.status.set("Original-XAML geladen. Jede Änderung bleibt als "
                            "editierbare Revision erhalten.")
        except (OSError,ValueError) as exc:self._message("XAML öffnen",exc)

    def import_patch(self):
        if self.doc is None:
            self._message("Mod-Patch öffnen","Bitte zuerst die originale Noesis-XAML laden")
            return
        file=filedialog.askopenfilename(parent=self,
            title="Bestehenden Origins-/Noesis-Menüpatch übernehmen",
            filetypes=[("Noesis-Patch","*.xaml")])
        if not file:return
        try:
            report=apply_existing_patch(self.doc,Path(file),strict=False)
            self.refresh_tree()
            self.status.set(
                f"Bestehender Patch: {report['applied_operations']} von "
                f"{report['operations_found']} Operationen auf die Arbeitskopie "
                "übernommen; Original unverändert.")
            if report["warnings"]:
                messagebox.showwarning("Nicht alle XPath-Ziele vorhanden",
                        "\n".join(report["warnings"][:15]),parent=self)
        except (OSError,ValueError) as exc:self._message("Mod-Patch öffnen",exc)

    def open_revision(self):
        location=filedialog.askdirectory(parent=self,
                title="Vorhandene Menürevision auswählen (rev-0001 usw.)")
        if not location:return
        try:
            self.doc=VisualXamlDocument.reopen(Path(location))
            self.selected=()
            self.scope.set("Gesamtes Dokument")
            reference=Path(location)/"reference.png"
            self.reference_image_path=reference if reference.is_file() else None
            self.title_var.set("Weiterbearbeitete Revision: "+str(location))
            self.refresh_tree()
            self.status.set("Revision frei geladen, auch nach eigener Änderung "
                            "der edited.xaml. Keine Hash-Sperre.")
        except (OSError,ValueError) as exc:self._message("Revision öffnen",exc)

    def choose_reference(self):
        path=filedialog.askopenfilename(parent=self,
            title="Original-Screenshot oder Fensterbild als Layoutreferenz",
            filetypes=[("Bildreferenz","*.png *.jpg *.jpeg *.webp")])
        if not path:return
        try:
            with Image.open(path) as image:
                if image.width*image.height>30_000_000:
                    raise WorkshopError("Bildreferenz zu groß")
                image.verify()
            self.reference_image_path=Path(path)
            self.redraw()
            self.status.set("Bildreferenz sichtbar. Sie wird nicht als "
                            "Spiel-Overlay oder Mod-Asset ausgegeben.")
        except (OSError,ValueError) as exc:self._message("Bildreferenz",exc)

    def _doc(self)->VisualXamlDocument:
        if self.doc is None:raise WorkshopError("Erst Original-XAML laden")
        return self.doc

    def _run(self,title,call,selected=None):
        try:
            result=call()
            if selected is not None:self.selected=selected(result)
            self.refresh_tree()
            self.status.set(title+" · noch nicht als neue Revision gespeichert")
        except (OSError,ValueError,TypeError) as exc:self._message(title,exc)

    def refresh_tree(self):
        doc=self._doc()
        old=self.selected
        self.tree.delete(*self.tree.get_children())
        self._rows={}
        options=["Gesamtes Dokument"]
        for item in doc.outline():
            item_id=_path_id(item.path)
            parent_id=_path_id(item.path[:-1]) if item.path else ""
            name=item.label or "(ohne Namen)"
            self.tree.insert(parent_id,"end",iid=item_id,
                     text=name[:72],values=(item.tag,),open=len(item.path)<2)
            self._rows[item_id]=item.path
            if (item.tag in {"Grid","Canvas","Page","Window","UserControl"}
                    and item.label and len(item.path)>0):
                options.append(item.label)
        self.scope_combo.configure(values=options)
        if self.scope.get() not in options:self.scope.set("Gesamtes Dokument")
        try:doc._target(old)
        except WorkshopError:old=()
        self.selected=old
        self.select_path(old)
        self.redraw()

    def select_path(self,path:tuple[int,...]):
        self.selected=path
        item=_path_id(path)
        if self.tree.exists(item):
            self.tree.selection_set(item)
            self.tree.see(item)
        self.refresh_props()

    def tree_select(self,event=None):
        selected=self.tree.selection()
        if not selected or selected[0] not in self._rows:return
        self.selected=self._rows[selected[0]]
        self.refresh_props()
        self.redraw()

    def refresh_props(self):
        self.props.delete(*self.props.get_children())
        if self.doc is None:return
        try:
            values=self.doc.attributes(self.selected)
            node=self.doc._target(self.selected)
            self.text_value.set(node.text or "")
        except WorkshopError:return
        for idx,(key,value) in enumerate(values.items()):
            self.props.insert("","end",iid="a"+str(idx),text=key,values=(value,))
        focus=self.attribute.get()
        if focus not in values:
            focus=next(iter(values),"Margin")
        self.attribute.set(focus)
        self.attr_value.set(values.get(focus,""))
        self.angle.set("0")

    def choose_attribute(self,event=None):
        selected=self.props.selection()
        if not selected:return
        item=selected[0]
        self.attribute.set(self.props.item(item,"text"))
        self.attr_value.set(self.props.item(item,"values")[0])

    def apply_attribute(self):
        self._run("Attribut geändert",lambda:self._doc().edit(
            self.selected,self.attribute.get(),self.attr_value.get()))

    def remove_attribute(self):
        self._run("Attribut entfernt",lambda:self._doc().edit(
            self.selected,self.attribute.get(),None))

    def set_text(self):
        self._run("Text geändert",lambda:self._doc().edit_text(
            self.selected,self.text_value.get()))

    def choose_color(self):
        choice=colorchooser.askcolor(parent=self,title="Noesis-Farbe wählen")
        if choice and choice[1]:
            self.attr_value.set("#FF"+choice[1][1:].upper())
            self.apply_attribute()

    def add_element(self):
        def action():
            tag=self.tag_value.get()
            attrs={"Name":self.name_value.get()} if self.name_value.get() else {}
            if tag=="Button":
                attrs["Content"]="Neuer Button";attrs["Width"]="230";attrs["Height"]="70"
            elif tag=="TextBlock":attrs["Text"]="Mein neuer Text"
            elif tag=="Image":attrs["Width"]="300";attrs["Height"]="200"
            return self._doc().insert(self.selected,tag,attrs)
        self._run("Neues Control hinzugefügt",action,selected=lambda result:result)

    def duplicate(self):
        self._run("Element dupliziert",
                  lambda:self._doc().duplicate(self.selected),
                  selected=lambda result:result)

    def delete_selected(self):
        if self.doc is None or not self.selected:return
        previous=self.selected[:-1]
        self._run("Element entfernt",lambda:self._doc().remove(self.selected),
                  selected=lambda _result:previous)

    def reorder(self,by:int):
        if self.doc is None or not self.selected:return
        self._run("Reihenfolge geändert",
                  lambda:self._doc().reorder(self.selected,by),
                  selected=lambda result:result)

    def rotate(self):
        self._run("Drehwinkel geändert",lambda:self._doc().rotate(
            self.selected,float(self.angle.get())))

    def undo(self):
        if self.doc and self.doc.undo_edit():
            self.refresh_tree()
            self.status.set("Letzte Änderung rückgängig gemacht")

    def redo(self):
        if self.doc and self.doc.redo_edit():
            self.refresh_tree()
            self.status.set("Änderung wiederhergestellt")

    def zoom_wheel(self,event):
        factor=1.15 if event.delta>0 else 1/1.15
        self.zoom.set(max(.25,min(2.5,self.zoom.get()*factor)))
        self.redraw()

    def _redraw_idle(self):
        if self._scroll_scheduled:return
        self._scroll_scheduled=True
        def do():
            self._scroll_scheduled=False
            self.redraw()
        self.after_idle(do)

    def _preview_scale(self):
        width=_number(self.preview_width.get(),VIEW_W,low=200,high=8192)
        height=_number(self.preview_height.get(),VIEW_H,low=200,high=8192)
        canvas_w=self.canvas.winfo_width()
        canvas_h=self.canvas.winfo_height()
        if canvas_w<=1 or canvas_h<=1:
            # Initial Tk geometry is not allocated during some offscreen tests.
            canvas_w,canvas_h=960,540
        scale=min(max(1,canvas_w-35)/width,
                  max(1,canvas_h-35)/height)
        return width,height,scale*self.zoom.get()

    def _selected_scope(self):
        if self.doc is None:return ()
        name=self.scope.get()
        if name=="Gesamtes Dokument":return ()
        for item in self.doc.outline():
            if item.label==name and item.tag in {
                "Grid","Canvas","Page","Window","UserControl"}:
                return item.path
        return ()

    def choose_preview_images(self):
        folder=filedialog.askdirectory(parent=self,
            title="Zusätzlichen Originalbild-Ordner für Noesis-Vorschau wählen")
        if folder:
            self.extra_preview_images.set(folder)
            self.redraw()
            self.status.set("Originalbilder für die Vorschau: "+folder+
                            " · nur lesend verwendet")

    def _resolve_image(self,uri:str):
        if not uri or uri.startswith(("/", "file:","http:","https:")):
            return None
        if not uri.lower().endswith((".png",".jpg",".jpeg",".webp")):
            return None
        doc=self._doc()
        # Original GUI assets usually reside beside the source XAML in
        # ../Images. Edits imported into the project use Override/Assets/GUI.
        locations=[doc.source.parent/uri,
           self.project/"Override"/"Assets"/"GUI"/"Images"/Path(uri).name]
        if self.extra_preview_images.get():
            locations.append(Path(self.extra_preview_images.get())/Path(uri).name)
        for path in locations:
            if path.is_file() and not path.is_symlink():
                return path
        return None

    def redraw(self):
        """Preview the original hierarchy with nested Grid/Canvas/StackPanel layout.

        This remains a geometric approximation: only the game renderer can
        resolve all Noesis bindings, animation and style triggers exactly.
        """
        from origins_visual_preview_bridge import draw_original_layout
        draw_original_layout(self)

    def _render(self,element,path,rect,scale,depth):
        if depth>50 or not isinstance(element.tag,str):return
        tag=element.tag.rsplit("}",1)[-1]
        if tag.endswith((".RowDefinitions",".ColumnDefinitions",".Resources",
                         ".RenderTransform",".Triggers",".Style",".Template")):
            return
        if tag in {"RowDefinition","ColumnDefinition","TransformGroup",
                   "RotateTransform","ScaleTransform","Setter","Trigger",
                   "Storyboard","DoubleAnimation","ColorAnimation"}:return
        if path:
            px,py,pw,ph=rect
            ml,mt,mr,mb=_margin(element.get("Margin","0"))
            if tag in CONTAINERS:
                default_w=max(40,pw-ml-mr);default_h=max(20,ph-mt-mb)
            elif tag=="TextBlock":
                default_w=360;default_h=48
            elif tag=="Image":
                default_w=350;default_h=180
            else:
                default_w=240;default_h=70
            w=_number(element.get("Width"),default_w,low=0,high=16384)
            h=_number(element.get("Height"),default_h,low=0,high=16384)
            horiz=element.get("HorizontalAlignment","Stretch")
            vert=element.get("VerticalAlignment","Stretch")
            x=px+ml if horiz in ("Left","Stretch") else (
                px+pw-mr-w if horiz=="Right" else px+(pw-w)/2+(ml-mr)/2)
            y=py+mt if vert in ("Top","Stretch") else (
                py+ph-mb-h if vert=="Bottom" else py+(ph-h)/2+(mt-mb)/2)
            # Canvas positions are expressed in parent-local units.
            if element.get("Canvas.Left") is not None:
                x=px+_number(element.get("Canvas.Left"),0)
            if element.get("Canvas.Top") is not None:
                y=py+_number(element.get("Canvas.Top"),0)
            rect=(x,y,w,h)
        x,y,w,h=rect
        if tag in DRAWABLE:
            xx,yy=13+x*scale,13+y*scale
            sw=max(2,w*scale);sh=max(2,h*scale)
            self._boxes[path]=(xx,yy,sw,sh)
            if element.get("Visibility") in ("Collapsed","Hidden"):
                fill="#1d2530";stroke="#485065"
            else:
                fill=_color(element.get("Background",""),
                      "#293d55" if tag in {"Button","Border"} else "")
                stroke="#55718c" if tag in CONTAINERS else "#8da9c3"
            if tag=="Image":
                picture=self._resolve_image(element.get("Source",""))
                if picture is not None and w>0 and h>0 and len(self._image_refs)<70:
                    try:
                        with Image.open(picture) as raw:
                            if raw.width*raw.height > 30_000_000:raise ValueError()
                            image=raw.convert("RGBA")
                            image.thumbnail((max(1,int(sw)),max(1,int(sh))))
                            image=ImageTk.PhotoImage(image,master=self)
                            self._image_refs.append(image)
                            self.canvas.create_image(xx,yy,image=image,anchor="nw")
                    except (OSError,ValueError):pass
            if sw>4 and sh>4:
                self.canvas.create_rectangle(xx,yy,xx+sw,yy+sh,outline=stroke,
                    fill=fill if tag!="Image" else "",width=1,
                    tags=(_path_id(path),))
            label=(element.get("Content") or element.get("Text") or
                   element.get("{clr-namespace:CrusaderDE}PropEx.TextCentre") or
                   element.get("Name") or element.get("{"+XNS+"}Name") or tag)
            if tag not in CONTAINERS and len(label)>0 and sw>35 and sh>18:
                self.canvas.create_text(xx+5,yy+5,text=label[:48],
                    anchor="nw",fill="#f0f4f8",width=max(30,int(sw)-10),
                    tags=(_path_id(path),))
        else:
            xx,yy=13+x*scale,13+y*scale
        children=[child for child in element
                  if isinstance(child.tag,str)]
        stack_position=0
        for i,child in enumerate(children):
            item_path=(*path,i)
            child_rect=rect
            if tag=="StackPanel" and not child.tag.endswith((".Resources",
                                                             ".RenderTransform")):
                # Approximate automatic StackPanel flow; actual Noesis layout
                # still depends on styles, bindings and runtime constraints.
                if element.get("Orientation")=="Horizontal":
                    child_rect=(x+stack_position,y,max(150,w-stack_position),h)
                    stack_position+=_number(child.get("Width"),180,low=0,high=16384)
                else:
                    child_rect=(x,y+stack_position,w,max(80,h-stack_position))
                    stack_position+=_number(child.get("Height"),72,low=0,high=16384)
            self._render(child,item_path,child_rect,scale,depth+1)

    def canvas_press(self,event):
        if self.doc is None:return
        x=self.canvas.canvasx(event.x);y=self.canvas.canvasy(event.y)
        possible=[(len(path),path,box) for path,box in self._boxes.items()
                  if box[0]<=x<=box[0]+box[2] and box[1]<=y<=box[1]+box[3]]
        if not possible:return
        _,path,box=max(possible,key=lambda a:a[0])
        self.select_path(path)
        resize=(abs(x-(box[0]+box[2]))<=11
                and abs(y-(box[1]+box[3]))<=11)
        self._drag=(path,x,y,resize,box[2],box[3])
        self.redraw()

    def canvas_motion(self,event):
        if self._drag is None:return
        path,ox,oy,resize,w,h=self._drag
        px=self.canvas.canvasx(event.x);py=self.canvas.canvasy(event.y)
        dx=(px-ox)/max(.01,self._world_scale)
        dy=(py-oy)/max(.01,self._world_scale)
        self.status.set(("Größe" if resize else "Position")+
                        f": Δx={dx:.0f}, Δy={dy:.0f} (Original-XAML-Einheiten)")

    def canvas_release(self,event):
        if self._drag is None:return
        path,ox,oy,resize,w,h=self._drag
        self._drag=None
        px=self.canvas.canvasx(event.x);py=self.canvas.canvasy(event.y)
        dx=(px-ox)/max(.01,self._world_scale)
        dy=(py-oy)/max(.01,self._world_scale)
        if abs(dx)+abs(dy)<1:return
        if resize:
            self._run("Element skaliert",lambda:self._doc().resize(
                path,max(1,w/self._world_scale+dx),
                max(1,h/self._world_scale+dy)))
        else:
            self._run("Element verschoben",lambda:self._doc().move(path,dx,dy))

    def import_selected_image(self):
        if self.doc is None:return
        source=filedialog.askopenfilename(parent=self,
                     filetypes=[("Grafik","*.png *.jpg *.jpeg *.webp")])
        if not source:return
        try:
            imported=import_image(Path(source),project=self.project,
                                  folder="Menüs / UI-Bilder")
            self.doc.edit(self.selected,"Source","../Images/"+imported.name)
            self.refresh_tree()
            self.status.set("Bild ins Projekt übernommen: "+str(imported))
        except (ValueError,OSError) as exc:self._message("Bild einfügen",exc)

    def edit_source(self):
        if self.doc is None:return
        window=tk.Toplevel(self);window.title("Fortgeschritten: komplette bearbeitete XAML")
        window.geometry("960x710")
        area=tk.Text(window,wrap="none",undo=True,font=("Consolas",10))
        area.pack(fill="both",expand=True,padx=8,pady=8)
        area.insert("1.0",self.doc.edited_bytes().decode("utf8"))
        def accept():
            try:
                self._doc().replace_xml(area.get("1.0","end-1c"))
                self.refresh_tree()
                self.status.set("XAML-Quelltext manuell aktualisiert")
                window.destroy()
            except (OSError,ValueError) as exc:self._message("XAML-Quelltext",exc)
        ttk.Button(window,text="Änderungen ins Dokument übernehmen",
                   command=accept).pack(pady=7)

    def save(self):
        if self.doc is None:return
        try:
            data=self.doc.save_revision(self.project,
                    publish=True,overwrite_existing=True)
            if self.reference_image_path is not None:
                reference=Path(data["revision_dir"])/"reference.png"
                if self.reference_image_path.is_file():
                    with Image.open(self.reference_image_path) as image:
                        if image.width*image.height<=30_000_000:
                            image.convert("RGB").save(reference,format="PNG")
            self.status.set(
                "Version "+str(data["revision"])+" gespeichert · Patch: "+
                str(data["patch"])+" · externe Spiel-Handler nicht automatisch erzeugt.")
            if self.after_export:self.after_export()
        except (OSError,ValueError) as exc:self._message("Patch / Revision speichern",exc)

    def build_mod(self):
        if self.doc is None:return
        guid=simpledialog.askstring("Asset-Mod-ID",
             "Eindeutige Kennung für das neue Paket:",
             initialvalue="originsfreimenu",parent=self)
        if not guid:return
        name=simpledialog.askstring("Modname","Name des Pakets:",
             initialvalue="Meine eigenen Menüseiten",parent=self)
        if not name:return
        try:
            from se_asset_package import build
            output=build(self.project,guid,name=name,author="SpriteSuite Benutzer")
            self.status.set("Asset-Mod gebaut: "+str(output["zip"])+
                            " · installiert wird nichts automatisch.")
        except (OSError,ValueError) as exc:self._message("Asset-Mod bauen",exc)

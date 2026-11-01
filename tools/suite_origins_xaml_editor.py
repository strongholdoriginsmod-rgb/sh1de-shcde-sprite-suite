"""Tk editor for real Noesis view controls, not just a flattened PNG.

Approximate layout preview; true Noesis rendering, event routing and animation
still require the exact installed game and a separate authorized QA copy.
"""
from __future__ import annotations

from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from origins_xaml_designer import (
    controls,create_patch,create_structural_patch,save_patch,
    save_structural_patch,save_combined_patch,PROPERTIES,WorkshopError,
)


class OriginsXamlEditor(tk.Toplevel):
    """Manual actual-XAML node selection, property editing and patch export."""

    def __init__(self,parent,*,project:Path,source:Path|None=None,
                 after_export=None):
        self.project=Path(project)
        self.source:Path|None=None
        self.nodes=[]
        self.after_export=after_export
        super().__init__(parent)
        self.title("Origins · Noesis Menüelemente manuell bearbeiten")
        self.geometry("1210x790")
        self.minsize(790,540)
        self.source_label=tk.StringVar(self,value="Keine Original-XAML gewählt")
        self.node_choice=tk.StringVar(self)
        self.search=tk.StringVar(self)
        self.section=tk.StringVar(self,value="Alle Menüseiten")
        self.visible_indices=[]
        self.prop=tk.StringVar(self,value="Margin")
        self.value=tk.StringVar(self)
        self.op=tk.StringVar(self,value="SetAttribute")
        self.new_name=tk.StringVar(self,value="SpriteSuite_MyButton")
        self.new_text=tk.StringVar(self)
        self.new_parameter=tk.StringVar(self)
        self.status=tk.StringVar(self,value="Originale werden nur gelesen. Kein Spiel wird verändert.")
        self._canvas_map={}
        self._grab=None
        self.pending=[]
        self._build()
        if source is not None:self.open_source(source)

    def _build(self):
        head=ttk.Frame(self,padding=8)
        head.pack(fill="x")
        ttk.Label(head,text="Origins · Noesis-Controls",font=("Segoe UI",15,"bold")
                  ).pack(side="left")
        ttk.Button(head,text="Original-XAML auswählen …",
                   command=self.choose_source).pack(side="right")
        ttk.Label(self,textvariable=self.source_label,wraplength=1120).pack(
            fill="x",padx=12,pady=(0,8))
        wrapper=ttk.Panedwindow(self,orient="horizontal")
        wrapper.pack(fill="both",expand=True,padx=10,pady=5)
        left=ttk.Frame(wrapper);right=ttk.Frame(wrapper)
        wrapper.add(left,weight=2);wrapper.add(right,weight=4)
        ttk.Label(left,text="Echte benannte Spiel-Controls",font=("Segoe UI",11,"bold")
                  ).pack(anchor="w")
        ttk.Label(left,text="Menüseite / Bereich").pack(anchor="w",pady=(8,1))
        self.section_combo=ttk.Combobox(
            left,textvariable=self.section,values=("Alle Menüseiten",),
            state="readonly")
        self.section_combo.pack(fill="x")
        self.section_combo.bind("<<ComboboxSelected>>",lambda _e:self._filter_nodes())
        ttk.Label(left,text="Control-Name suchen").pack(anchor="w",pady=(6,1))
        ttk.Entry(left,textvariable=self.search).pack(fill="x")
        self.search.trace_add("write",lambda *_:self._filter_nodes())
        self.listbox=tk.Listbox(left,exportselection=False)
        self.listbox.pack(fill="both",expand=True)
        self.listbox.bind("<<ListboxSelect>>",self.choose_node)
        ttk.Label(left,text="Die Vorschau ist eine schematische XAML-Positionskarte,\n"
                  "kein vollständiger Noesis-Renderer.",
                  wraplength=340).pack(pady=9,anchor="w")
        ttk.Label(right,text="Layout-Entwurf (ungefähre Positionen; XAML bleibt original)",
                  font=("Segoe UI",10,"bold")).pack(anchor="w")
        self.canvas=tk.Canvas(right,background="#172334",height=325,
                              highlightthickness=0,cursor="hand2")
        self.canvas.pack(fill="both",expand=True,pady=5)
        self.canvas.bind("<Button-1>",self.canvas_press)
        self.canvas.bind("<B1-Motion>",self.canvas_drag)
        self.canvas.bind("<ButtonRelease-1>",self.canvas_release)
        editor=ttk.LabelFrame(right,text="XAML-Änderung (noch nicht im Spiel)",padding=8)
        editor.pack(fill="x",padx=3,pady=4)
        row=ttk.Frame(editor);row.pack(fill="x",pady=3)
        ttk.Label(row,text="Operation",width=15).pack(side="left")
        self.operations=ttk.Combobox(row,values=(
            "SetAttribute","Replace","InsertAfter","InsertBefore","Add","Remove"),
            textvariable=self.op,state="readonly",width=19)
        self.operations.pack(side="left")
        ttk.Label(row,text="Eigenschaft",width=13).pack(side="left",padx=(12,0))
        props=sorted(PROPERTIES)
        ttk.Combobox(row,values=props,textvariable=self.prop,
                     state="readonly",width=22).pack(side="left")
        row=ttk.Frame(editor);row.pack(fill="x",pady=3)
        ttk.Label(row,text="Neuer Wert",width=15).pack(side="left")
        ttk.Entry(row,textvariable=self.value).pack(side="left",fill="x",expand=True)
        row=ttk.Frame(editor);row.pack(fill="x",pady=3)
        ttk.Label(row,text="Neuer Knoten",width=15).pack(side="left")
        ttk.Entry(row,textvariable=self.new_name,width=27).pack(side="left")
        ttk.Label(row,text="Text",width=7).pack(side="left")
        ttk.Entry(row,textvariable=self.new_text).pack(side="left",fill="x",expand=True)
        row=ttk.Frame(editor);row.pack(fill="x",pady=3)
        ttk.Label(row,text="CommandParameter",width=16).pack(side="left")
        ttk.Entry(row,textvariable=self.new_parameter,width=35).pack(side="left")
        ttk.Label(row,text="Nur bereits vorhandene Werte werden als funktional anerkannt!",
                  foreground="#ae8536").pack(side="left",padx=8)
        actions=ttk.Frame(editor);actions.pack(fill="x",pady=5)
        ttk.Button(actions,text="Patch prüfen",command=self.preview).pack(side="left")
        ttk.Button(actions,text="Änderung zur Patchliste hinzufügen",
                   command=self.queue_patch).pack(side="left",padx=6)
        ttk.Button(actions,text="Alle vorgemerkten Änderungen speichern …",
                   command=self.save).pack(side="left",padx=7)
        ttk.Label(self,textvariable=self.status,wraplength=1120).pack(
            fill="x",padx=12,pady=8)

    def choose_source(self):
        filename=filedialog.askopenfilename(
            parent=self,title="Originale Noesis-Spielansicht auswählen (nur lesen)",
            filetypes=[("XAML","*.xaml")])
        if filename:self.open_source(Path(filename))

    def open_source(self,source:Path):
        try:
            self.nodes=controls(Path(source))
            if not self.nodes:
                raise WorkshopError("No unique, named Controls found in source")
        except (OSError,ValueError) as exc:
            messagebox.showerror("Original-XAML",str(exc),parent=self)
            return
        self.source=Path(source)
        self.pending=[]
        self.source_label.set(f"Quelldokument (nur lesend): {self.source}")
        groups=sorted({self._section(node.name) for node in self.nodes})
        self.section_combo.configure(values=("Alle Menüseiten",*groups))
        self.section.set("Alle Menüseiten")
        self.search.set("")
        self._filter_nodes()

    @staticmethod
    def _section(name):
        return name.split("_",1)[0] if "_" in name else "Andere"

    def _filter_nodes(self):
        if not hasattr(self,"listbox"):return
        query=self.search.get().casefold().strip()
        category=self.section.get()
        self.visible_indices=[
            i for i,node in enumerate(self.nodes)
            if (not query or query in node.label.casefold() or
                query in node.xpath.casefold()) and
            (category=="Alle Menüseiten" or
             self._section(node.name)==category)
        ]
        self.listbox.delete(0,"end")
        for i in self.visible_indices:
            self.listbox.insert("end",self.nodes[i].label)
        if self.visible_indices:
            self.listbox.selection_set(0)
            self.choose_node()
        else:
            self.status.set("Keine passenden Controls · Filter ändern.")
            self.redraw()

    def selected_node(self):
        selected=self.listbox.curselection()
        if not selected or not self.nodes:raise WorkshopError("Choose a named XAML node")
        return self.nodes[self.visible_indices[selected[0]]]

    def choose_node(self,_event=None):
        try:
            node=self.selected_node()
        except WorkshopError:return
        self.value.set(node.properties.get(self.prop.get(),""))
        self.new_name.set("SpriteSuite_"+node.name[:64])
        self.new_text.set(node.properties.get("Content",node.properties.get("Text","")))
        self.new_parameter.set(node.command_parameter or "")
        self.status.set(
            "XAML-Element "+node.label+" · XPath: "+node.xpath+
            (" · vorhandener Spielbefehl: "+node.bound_command
             if node.bound_command else " · keine nachgewiesene Spielaktion"))
        self.redraw()

    def _rect(self,node):
        props=node.properties
        try:
            margin=[float(n) for n in props.get("Margin","0,0,0,0").split(",")]
            if len(margin)!=4:raise ValueError()
        except ValueError:margin=[0,0,0,0]
        try:w=float(props.get("Width","260"))
        except ValueError:w=260.
        try:h=float(props.get("Height","75"))
        except ValueError:h=75.
        width=max(1,self.canvas.winfo_width())
        height=max(1,self.canvas.winfo_height())
        mul=min(width/1920,height/1080)
        horiz=props.get("HorizontalAlignment","Left")
        vert=props.get("VerticalAlignment","Top")
        x=margin[0] if horiz=="Left" else 1920-margin[2]-w if horiz=="Right" else (1920-w)/2+margin[0]-margin[2]
        y=margin[1] if vert=="Top" else 1080-margin[3]-h if vert=="Bottom" else (1080-h)/2+margin[1]-margin[3]
        return (x*mul,y*mul,(x+w)*mul,(y+h)*mul)

    def redraw(self):
        self.canvas.delete("all")
        self._canvas_map.clear()
        try:selected=self.selected_node().xpath
        except WorkshopError:selected=None
        w=max(1,self.canvas.winfo_width());h=max(1,self.canvas.winfo_height())
        factor=min(w/1920,h/1080)
        self.canvas.create_rectangle(0,0,1920*factor,1080*factor,
                                     outline="#627894",width=2)
        # Views often contain thousands of controls; rendering a subset is an
        # authoring overview, not a claim of precise WPF layout semantics.
        for idx,original in enumerate(self.visible_indices[:350]):
            node=self.nodes[original]
            rect=self._rect(node)
            is_selected=node.xpath==selected
            if rect[2]<0 or rect[3]<0 or rect[0]>w or rect[1]>h:
                continue
            fill="#364c6c" if is_selected else "#24374c"
            border="#ffd34f" if is_selected else "#526985"
            key=self.canvas.create_rectangle(*rect,fill=fill,
                                             outline=border,width=2 if is_selected else 1)
            self._canvas_map[key]=idx
            if is_selected:self.canvas.create_text(rect[0]+5,rect[1]+5,
                text=node.name,anchor="nw",fill="#f5f3da",width=max(50,int(rect[2]-rect[0])))

    def canvas_press(self,event):
        matches=self.canvas.find_overlapping(event.x,event.y,event.x,event.y)
        for item in reversed(matches):
            if item in self._canvas_map:
                idx=self._canvas_map[item]
                self.listbox.selection_clear(0,"end")
                self.listbox.selection_set(idx)
                self.listbox.see(idx)
                self.choose_node()
                node=self.selected_node()
                self.prop.set("Margin")
                self.value.set(node.properties.get("Margin","0,0,0,0"))
                self.op.set("SetAttribute")
                self._grab=(event.x,event.y,self.value.get())
                return

    def canvas_drag(self,event):
        if self._grab is None:return
        x,y,original=self._grab
        try:
            parts=[float(n) for n in original.split(",")]
            if len(parts)!=4:return
            mul=min(max(1,self.canvas.winfo_width())/1920,
                    max(1,self.canvas.winfo_height())/1080)
            parts[0]+=round((event.x-x)/mul)
            parts[1]+=round((event.y-y)/mul)
            self.value.set(",".join(str(int(n)) for n in parts))
        except (ValueError,ZeroDivisionError):
            return

    def canvas_release(self,_event):
        self._grab=None

    def _patch(self):
        if self.source is None:raise WorkshopError("Select original game XAML first")
        node=self.selected_node()
        op=self.op.get()
        if op in ("SetAttribute","Replace"):
            return create_patch(self.source,xpath=node.xpath,operation=op,
                                property_name=self.prop.get(),value=self.value.get())
        return create_structural_patch(
            self.source,xpath=node.xpath,operation=op,
            new_name=self.new_name.get(),text=self.new_text.get(),
            command_parameter=self.new_parameter.get())

    def preview(self):
        try:
            blob,report=self._patch()
            self.status.set(
                f"Offline gültig: {report['operation']} · {len(blob)} XML-Bytes · "
                "keine neuen Laufzeit-Handler · keine Ingame-Freigabe")
        except (ValueError,OSError) as exc:
            messagebox.showerror("Patch nicht gültig",str(exc),parent=self)

    def queue_patch(self):
        try:
            patch=self._patch()
            from origins_xaml_designer import combine_control_patches
            combine_control_patches(self.source,[*self.pending,patch])
            self.pending.append(patch)
            self.status.set(f"{len(self.pending)} echte XAML-Änderungen vorgemerkt · "
                            "keine Originaldatei geschrieben.")
        except (ValueError,OSError) as exc:
            messagebox.showerror("Nicht zur Liste hinzugefügt",str(exc),parent=self)

    def save(self):
        try:
            if self.pending:
                from origins_xaml_designer import combine_control_patches
                blob,report=combine_control_patches(self.source,self.pending)
            else:
                blob,report=self._patch()
            if not messagebox.askyesno("XAML-Patch exportieren",
                "Einen gesonderten, SHA-geprüften XAML-Patch in die Werkstatt schreiben?\n"
                "Die Originaldatei wird nicht verändert.\n"
                "Neue Origins-Spielaktionen ohne bestehenden Handler sind nicht möglich.",
                parent=self,default="no"):
                return
            node=self.selected_node()
            if self.pending:
                dst,proof=save_combined_patch(self.source,project=self.project,
                                              patches=self.pending)
            elif self.op.get() in ("SetAttribute","Replace"):
                dst,proof=save_patch(self.source,xpath=node.xpath,
                                     operation=self.op.get(),
                                     property_name=self.prop.get(),
                                     value=self.value.get(),project=self.project)
            else:
                dst,proof=save_structural_patch(
                    self.source,project=self.project,xpath=node.xpath,
                    operation=self.op.get(),new_name=self.new_name.get(),
                    text=self.new_text.get(),
                    command_parameter=self.new_parameter.get())
            self.pending.clear()
            self.status.set(
                "Als Arbeitskopie gespeichert: "+str(dst)+
                " · Runtime-/Ingame-Freigabe weiterhin separat.")
            if self.after_export:self.after_export()
        except (OSError,ValueError) as exc:
            messagebox.showerror("Patch nicht gespeichert",str(exc),parent=self)

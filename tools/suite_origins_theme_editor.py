"""Manual Origins-style Noesis Color/Brush editor.

Edits only SHA-pinned private working copies of actual ResourceDictionaries.
The preview is approximate; final in-game styling needs Noesis runtime QA.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re
import tkinter as tk
from tkinter import ttk, filedialog, colorchooser, messagebox
import xml.etree.ElementTree as ET

from hud_menu_workspace import workspace, WorkshopError, _write_new
from se_asset_package import _check_xml

XNS="http://schemas.microsoft.com/winfx/2006/xaml"
PRES="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
ET.register_namespace("",PRES)
ET.register_namespace("x",XNS)
KEY=f"{{{XNS}}}Key"
ARGB=re.compile(r"#[0-9A-Fa-f]{8}\Z")
OUTPUT="Override/Assets/GUI/XAMLResources/Theme.Brushes.DarkRed.xaml"


def read_palette(source:Path)->tuple[bytes,ET.Element,dict[str,str]]:
    src=Path(source)
    if src.is_symlink() or not src.is_file() or src.stat().st_size>2*1024**2:
        raise WorkshopError("Choose a regular XAML theme under 2 MiB")
    blob=src.read_bytes()
    if b"<!DOCTYPE" in blob.upper() or b"<!ENTITY" in blob.upper():
        raise WorkshopError("External XAML entities are forbidden")
    try:root=ET.fromstring(blob)
    except ET.ParseError as exc:raise WorkshopError("Invalid Noesis theme") from exc
    if root.tag!=f"{{{PRES}}}ResourceDictionary":
        raise WorkshopError("Source must be a Color ResourceDictionary")
    colors={}
    seen=set()
    for child in root:
        key=child.get(KEY)
        if key:
            if key in seen:raise WorkshopError("Duplicate theme ResourceKey: "+key)
            seen.add(key)
        if child.tag==f"{{{PRES}}}Color" and key:
            text=(child.text or "").strip()
            if not ARGB.fullmatch(text):
                raise WorkshopError("Palette color must be #AARRGGBB: "+key)
            colors[key]=text.upper()
    if not colors:raise WorkshopError("Theme has no named Color resources")
    return blob,root,colors


def save_palette(source:Path, project:Path,changes:dict[str,str])->tuple[Path,dict]:
    before,xaml_root,known=read_palette(source)
    if not changes:raise WorkshopError("Choose at least one changed color")
    for key,value in changes.items():
        if key not in known or not ARGB.fullmatch(value):
            raise WorkshopError("Unknown color key or invalid #AARRGGBB")
    root=workspace(project,create=True)
    target=root/OUTPUT
    if target.exists() or target.is_symlink():
        raise WorkshopError("Theme already exists; make a new project to avoid overwrite")
    updates=0
    for child in xaml_root:
        key=child.get(KEY)
        if key in changes and child.tag==f"{{{PRES}}}Color":
            child.text=changes[key].upper()
            updates+=1
    if updates!=len(changes):
        raise WorkshopError("Some theme colors were not replaced")
    ET.register_namespace("",PRES)
    blob=ET.tostring(xaml_root,encoding="utf8",xml_declaration=True)
    if sha256(Path(source).read_bytes()).hexdigest()!=sha256(before).hexdigest():
        raise WorkshopError("Source theme changed while editing")
    from tempfile import TemporaryDirectory
    with TemporaryDirectory(prefix="origins-theme-",dir=root) as temp:
        staged=Path(temp)/"theme.xaml"
        staged.write_bytes(blob)
        _check_xml(staged,patch=False)
    from hud_menu_workspace import _metadata_dir
    evidence=_metadata_dir(root)/"origins-theme-receipt.json"
    if evidence.exists() or evidence.is_symlink():
        raise WorkshopError("Existing theme receipt; refuse overwrite")
    _write_new(target,blob)
    proof={
        "schema":"sprite-suite.origins-theme-palette.v1",
        "source_sha256":sha256(before).hexdigest(),
        "output_sha256":sha256(blob).hexdigest(),
        "changed_color_keys":sorted(changes),
        "brush_resource_bindings_preserved":True,
        "native_in_game_qa":False,
        "output":OUTPUT,
    }
    _write_new(evidence,(json.dumps(proof,indent=2,ensure_ascii=False)+"\n").encode("utf8"))
    return target,proof


class OriginsThemeEditor(tk.Toplevel):
    def __init__(self,parent,*,project:Path,source:Path|None=None,after_save=None):
        self.project=Path(project)
        self.source=None
        self.colors={}
        self.changed={}
        self.after_save=after_save
        super().__init__(parent)
        self.title("Origins · Noesis-Farb- und Brush-Editor")
        self.geometry("900x650")
        self.source_label=tk.StringVar(self,value="Theme ResourceDictionary auswählen")
        self.status=tk.StringVar(self,value="Farben ändern nur eine neue Arbeitskopie")
        head=ttk.Frame(self,padding=9);head.pack(fill="x")
        ttk.Label(head,text="Noesis Theme-Farben",font=("Segoe UI",15,"bold")
                  ).pack(side="left")
        ttk.Button(head,text="Theme-XAML öffnen …",
                   command=self.choose_source).pack(side="right")
        ttk.Label(self,textvariable=self.source_label,wraplength=840).pack(anchor="w",padx=9)
        body=ttk.Frame(self,padding=9);body.pack(fill="both",expand=True)
        self.list=tk.Listbox(body,exportselection=False,width=38)
        self.list.pack(side="left",fill="both",expand=True)
        self.list.bind("<<ListboxSelect>>",lambda _:self.select_color())
        inspect=ttk.Frame(body,padding=8);inspect.pack(side="left",fill="both",expand=True)
        self.selected=tk.StringVar(self)
        self.value=tk.StringVar(self)
        ttk.Label(inspect,textvariable=self.selected,wraplength=340).pack(anchor="w")
        ttk.Label(inspect,text="Farbe (#AARRGGBB)").pack(anchor="w",pady=(14,0))
        ttk.Entry(inspect,textvariable=self.value,width=20).pack(anchor="w",pady=6)
        self.preview=tk.Canvas(inspect,width=190,height=110,highlightthickness=0)
        self.preview.pack(anchor="w",pady=9)
        ttk.Button(inspect,text="Farbe wählen …",command=self.choose_color).pack(fill="x")
        ttk.Button(inspect,text="Änderung vormerken",command=self.update_color).pack(fill="x",pady=5)
        ttk.Button(inspect,text="Eigenes Theme als XAML speichern",
                   command=self.save).pack(fill="x",pady=15)
        ttk.Label(inspect,text="Die gebundenen Brushes bleiben erhalten.\n"
                  "Vorschau ist nicht Noesis-Ingame-Rendering.",
                  wraplength=310).pack(anchor="w")
        ttk.Label(self,textvariable=self.status,wraplength=850).pack(fill="x",padx=12,pady=10)
        if source:self.open_source(source)

    def choose_source(self):
        path=filedialog.askopenfilename(parent=self,title="Farbthema-XAML öffnen",
                                         filetypes=[("XAML","*.xaml")])
        if path:self.open_source(Path(path))

    def open_source(self,source):
        try:
            _,_,colors=read_palette(source)
        except (ValueError,OSError) as exc:
            messagebox.showerror("Theme",str(exc),parent=self);return
        self.source=Path(source);self.colors=colors;self.changed={}
        self.source_label.set(str(source));self.list.delete(0,"end")
        for key in colors:self.list.insert("end",key)
        self.list.selection_set(0);self.select_color()
        self.status.set(f"{len(colors)} originale Theme-Farben geladen")

    def select_color(self):
        indexes=self.list.curselection()
        if not indexes:return
        key=self.list.get(indexes[0])
        value=self.changed.get(key,self.colors[key])
        self.selected.set(key);self.value.set(value)
        self.preview.configure(bg="#"+value[3:])

    def choose_color(self):
        key=self.selected.get()
        if not key:return
        chosen=colorchooser.askcolor(color="#"+self.value.get()[3:],parent=self)
        if chosen[1]:
            self.value.set(self.value.get()[:3]+chosen[1][1:].upper())
            self.preview.configure(bg=chosen[1])

    def update_color(self):
        key=self.selected.get()
        val=self.value.get()
        if not key or not ARGB.fullmatch(val):
            messagebox.showerror("Farbe","#AARRGGBB erforderlich",parent=self);return
        self.changed[key]=val.upper()
        self.preview.configure(bg="#"+val[3:])
        self.status.set(f"{len(self.changed)} Farbwerte vorgemerkt – noch nichts geschrieben")

    def save(self):
        try:
            if self.source is None:raise WorkshopError("Choose a source theme first")
            if not messagebox.askyesno("Theme-Arbeitskopie",
                "Neues Noesis-Theme in dein Arbeitsprojekt schreiben?\n"
                "Die Originaldatei und Spielinstallation bleiben unverändert.",
                parent=self,default="no"):
                return
            target,receipt=save_palette(self.source,self.project,self.changed)
            self.status.set("Eigenes Theme gespeichert: "+str(target))
            if self.after_save:self.after_save()
        except (ValueError,OSError) as exc:
            messagebox.showerror("Theme nicht gespeichert",str(exc),parent=self)

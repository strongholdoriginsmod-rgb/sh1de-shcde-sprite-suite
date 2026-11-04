"""One visible SpriteSuite workflow: choose source -> edit -> check -> build.

Reuses the proven HUD pixel, compositing, Noesis visual and asset-package
implementations in a SINGLE persistent workspace. Specialists are no longer
competing start pages and a ZIP is never marked complete before verification.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import tkinter as tk
from tkinter import filedialog,messagebox,simpledialog,ttk
from xml.etree import ElementTree

from PIL import Image,ImageTk

import hud_menu_workspace as hud
from suite_hud_menu_session import read_session,save_session
from suite_unified_project import (
    ProjectPipeline,UnifiedFlowError,project_from_recent,new_project,
)

TITLE = "Ein Projekt. Ein Ablauf. Ein geprüftes Mod-Paket."


class UnifiedWorkflowTab(ttk.Frame):
    """The normal first page and persistent source of truth for manual edits."""

    def __init__(self,parent,app):
        super().__init__(parent)
        self.app=app
        self.pipeline=ProjectPipeline(project_from_recent())
        self._assets=[]
        self._active_editors={}
        self._layout_window=None
        self._visual_window=None
        self._photo=None
        self._selected=None
        self._last_export=None
        self.project_text=tk.StringVar(self,value="")
        self.source_text=tk.StringVar(self,value="")
        self.selection_text=tk.StringVar(self,value="Noch keine Datei ausgewählt.")
        self.check_text=tk.StringVar(self,value="Noch nicht geprüft.")
        self.result_text=tk.StringVar(self,value="Noch kein Mod-ZIP für dieses Projekt erstellt.")
        self.message=tk.StringVar(self,value="Wähle eine Originalgrafik oder eine Noesis-XAML-Seite.")
        self.category=tk.StringVar(self,value="Menüs / UI-Bilder")
        slug=re.sub(r"[^a-z0-9-]","-",self.pipeline.project.name.lower()).strip("-")
        self.guid=tk.StringVar(self,value="spritesuite-"+(slug or "projekt"))
        self.mod_name=tk.StringVar(self,value="SpriteSuite "+self.pipeline.project.name)
        self._build()
        self.refresh()

    def _build(self):
        head=ttk.Frame(self,padding=(15,12,15,5))
        head.pack(fill="x")
        ttk.Label(head,text="Mein Mod-Projekt",
                  style="SectionTitle.TLabel").pack(anchor="w")
        ttk.Label(head,text=TITLE,style="Description.TLabel").pack(anchor="w",pady=(3,5))
        top=ttk.Frame(self,padding=(15,0,15,8));top.pack(fill="x")
        ttk.Label(top,textvariable=self.project_text,
                  font=("Segoe UI",10,"bold")).pack(side="left")
        ttk.Button(top,text="Neues Projekt",command=self.create_project
                   ).pack(side="right",padx=3)
        ttk.Button(top,text="Projekt wechseln",command=self.choose_project
                   ).pack(side="right",padx=3)
        ttk.Button(top,text="Projekt sichern (ZIP)",command=self.backup_project
                   ).pack(side="right",padx=3)
        ttk.Button(top,text="Projekt-ZIP öffnen",command=self.restore_project
                   ).pack(side="right",padx=3)
        steps=ttk.Frame(self,padding=(15,0,15,9));steps.pack(fill="x")
        for number,title in (
            ("1","QUELLE WÄHLEN"),("2","BEARBEITEN"),
            ("3","PRÜFEN"),("4","MOD-ZIP BAUEN")
        ):
            card=ttk.Frame(steps,borderwidth=1,relief="ridge",padding=7)
            card.pack(side="left",fill="x",expand=True,padx=(0,4))
            ttk.Label(card,text=number+"   "+title,
                      font=("Segoe UI",9,"bold")).pack(anchor="center")

        first=ttk.LabelFrame(self,text="1  Original oder eigene Grafik übernehmen",padding=9)
        first.pack(fill="x",padx=15,pady=(0,8))
        row=ttk.Frame(first);row.pack(fill="x")
        self.source_button=ttk.Button(
            row,text="Dateien hinzufügen …",command=self.add_sources)
        self.source_button.pack(side="left",padx=(0,8))
        ttk.Label(row,text="Ziel für PNG-Bilder:").pack(side="left")
        self.category_box=ttk.Combobox(row,textvariable=self.category,
                    values=tuple(hud.CATEGORIES),state="readonly",width=23)
        self.category_box.pack(side="left",padx=5)
        ttk.Button(row,text="Leeres Bild erstellen …",command=self.make_blank
                   ).pack(side="left",padx=8)
        self.source_label=ttk.Label(first,textvariable=self.source_text,
                                  wraplength=1040)
        self.source_label.pack(fill="x",pady=(7,0))

        second=ttk.LabelFrame(self,text="2  Bearbeiten – alle Änderungen bleiben im selben Projekt",padding=9)
        second.pack(fill="both",expand=True,padx=15,pady=(0,8))
        main=ttk.Panedwindow(second,orient="horizontal")
        main.pack(fill="both",expand=True)
        left=ttk.Frame(main);right=ttk.Frame(main)
        main.add(left,weight=5);main.add(right,weight=3)
        self.tree=ttk.Treeview(left,columns=("typ","state"),show="tree headings",
                               selectmode="browse",height=7)
        self.tree.heading("#0",text="Arbeitsdatei")
        self.tree.heading("typ",text="Art")
        self.tree.heading("state",text="Stand")
        self.tree.column("#0",width=250,minwidth=130)
        self.tree.column("typ",width=136,minwidth=85)
        self.tree.column("state",width=95,minwidth=70)
        scrollbar=ttk.Scrollbar(left,orient="vertical",command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left",fill="both",expand=True)
        scrollbar.pack(side="right",fill="y")
        self.tree.bind("<<TreeviewSelect>>",self._select)
        self.tree.bind("<Double-1>",lambda _e:self.edit_selected())
        self.preview=ttk.Label(right,text="Bildvorschau nach Auswahl",
                               anchor="center",justify="center")
        self.preview.pack(fill="both",expand=True,padx=8)
        ttk.Button(right,text="Bild in Noesis-Menü einbinden",
                   command=self.bind_selected_image).pack(fill="x",padx=8,pady=4)
        ttk.Label(right,textvariable=self.selection_text,justify="left",
                  wraplength=330).pack(fill="x",padx=8,pady=5)
        actions=ttk.Frame(second);actions.pack(fill="x",pady=(8,0))
        ttk.Button(actions,text="Ausgewählte Datei bearbeiten",
                   command=self.edit_selected).pack(side="left",padx=(0,6))
        ttk.Button(actions,text="HUD-Layout gestalten",
                   command=self.open_layout).pack(side="left",padx=5)
        ttk.Button(actions,text="Noesis-Menüseite gestalten",
                   command=self.open_noesis).pack(side="left",padx=5)
        ttk.Button(actions,text="Liste aktualisieren",
                   command=self.refresh).pack(side="right")

        third=ttk.LabelFrame(self,text="3  Geprüfte Arbeitsdateien",padding=8)
        third.pack(fill="x",padx=15,pady=(0,8))
        auditbar=ttk.Frame(third);auditbar.pack(fill="x")
        ttk.Button(auditbar,text="Änderungen & XAML prüfen",
                   command=self.check_project).pack(side="left",padx=(0,8))
        ttk.Button(auditbar,text="Echte Noesis-Spielpixel anzeigen",
                   command=self.open_native_preview).pack(side="left",padx=6)
        ttk.Button(auditbar,text="Steam-Version prüfen",
                   command=self.check_steam_compatibility).pack(side="left",padx=6)
        ttk.Label(auditbar,textvariable=self.check_text,
                  wraplength=650).pack(side="left",padx=9,fill="x",expand=True)

        fourth=ttk.LabelFrame(self,text="4  Reproduzierbares Mod-Paket aus genau diesem Projekt",padding=8)
        fourth.pack(fill="x",padx=15,pady=(0,8))
        line=ttk.Frame(fourth);line.pack(fill="x")
        ttk.Label(line,text="Mod-ID:").pack(side="left")
        ttk.Entry(line,textvariable=self.guid,width=27).pack(side="left",padx=5)
        ttk.Label(line,text="Paketname:").pack(side="left",padx=(10,0))
        ttk.Entry(line,textvariable=self.mod_name,width=33).pack(
            side="left",padx=5,fill="x",expand=True)
        ttk.Button(line,text="Geprüftes Mod-ZIP bauen",
                   command=self.build_package).pack(side="right",padx=(9,0))
        result=ttk.Frame(fourth);result.pack(fill="x",pady=(6,0))
        ttk.Label(result,textvariable=self.result_text,
                  wraplength=950).pack(side="left",fill="x",expand=True)
        ttk.Button(result,text="Ergebnisordner öffnen",
                   command=self.open_result).pack(side="right",padx=5)
        footer=ttk.Frame(self,padding=(15,1,15,7))
        footer.pack(fill="x")
        ttk.Label(footer,textvariable=self.message,wraplength=1090,
                  style="Muted.TLabel").pack(side="left",fill="x",expand=True)

    def _set_message(self,text):
        self.message.set(text)

    def _sync_hud(self):
        other=getattr(self.app,"hud_menu_tab",None)
        if other is not None:
            other.project_var.set(str(self.pipeline.project))
            other.refresh()

    def _dirty_windows(self):
        """Include all open editors in both the unified and legacy workspace."""
        from suite_hud_menu_editor import HudMenuPixelEditor,HudMenuTextEditor
        from suite_hud_menu_layout_editor import HudMenuLayoutEditor
        from suite_origins_visual_editor import OriginsVisualEditor
        found=[]
        stack=[self.app]
        while stack:
            widget=stack.pop()
            try:stack.extend(widget.winfo_children())
            except tk.TclError:continue
            if not isinstance(widget,tk.Toplevel) or not widget.winfo_exists():
                continue
            if getattr(widget,"project",None)!=self.pipeline.project:
                continue
            dirty=False
            if isinstance(widget,HudMenuPixelEditor):
                dirty=bool(widget.dirty)
            elif isinstance(widget,HudMenuTextEditor):
                dirty=bool(widget.editor.edit_modified())
            elif isinstance(widget,HudMenuLayoutEditor):
                dirty=widget.is_dirty()
            elif isinstance(widget,OriginsVisualEditor):
                dirty=widget.is_dirty()
            if dirty:found.append(widget)
        found.sort(key=lambda w:isinstance(w,HudMenuLayoutEditor))
        return found

    def _save_pending(self,action):
        pending=self._dirty_windows()
        if not pending:return True
        if not messagebox.askyesno(
            "Bearbeitung noch nicht gespeichert",
            f"{len(pending)} Editor(en) haben ungespeicherte Änderungen.\n\n"
            f"Vor {action} speichern? 'Nein' bricht den Vorgang ab.",
            parent=self,default="no"):
            return False
        for window in pending:
            try:window.save()
            except (ValueError,OSError) as exc:
                messagebox.showerror("Speichern fehlgeschlagen",str(exc),parent=self)
                return False
            if window in self._dirty_windows():
                messagebox.showwarning("Noch nicht gespeichert",
                    "Ein Editor konnte nicht gespeichert werden. Vorgang abgebrochen.",
                    parent=self)
                window.lift()
                return False
        return True

    def _close_saved_project_editors(self,project,only_noesis=False):
        """Dismiss stale windows only after their save checks have passed."""
        from suite_hud_menu_editor import HudMenuPixelEditor,HudMenuTextEditor
        from suite_hud_menu_layout_editor import HudMenuLayoutEditor
        from suite_origins_visual_editor import OriginsVisualEditor
        allowed=(OriginsVisualEditor,) if only_noesis else (
            OriginsVisualEditor,HudMenuPixelEditor,HudMenuTextEditor,
            HudMenuLayoutEditor)
        stack=[self.app]
        to_close=[]
        while stack:
            node=stack.pop()
            try:stack.extend(node.winfo_children())
            except tk.TclError:continue
            if (isinstance(node,allowed) and node.winfo_exists() and
                    getattr(node,"project",None)==project):
                to_close.append(node)
        for node in to_close:
            node.destroy()
        if only_noesis:
            self._visual_window=None
        else:
            self._visual_window=None
            self._layout_window=None
            self._active_editors.clear()

    def activate_project(self,path:Path):
        # A canceled switch must not create a stray project directory.
        # Only the explicit New Project and ZIP Restore flows create folders.
        chosen=hud.workspace(path,create=False)
        if chosen==self.pipeline.project:
            self.refresh()
            return True
        if not self._save_pending("dem Projektwechsel"):
            return False
        if not chosen.is_dir():
            raise UnifiedFlowError("Projektordner existiert nicht")
        candidate=ProjectPipeline(chosen)
        # First prove the new session is writable. If persistence fails, keep
        # the previous project and all of its editor windows intact.
        candidate.activate()
        self._close_saved_project_editors(self.pipeline.project)
        self.pipeline=candidate
        self._selected=None;self._photo=None
        self._last_export=None
        self._active_editors={}
        self._visual_window=None
        self._layout_window=None
        slug=re.sub(r"[^a-z0-9-]","-",chosen.name.lower()).strip("-")
        self.guid.set("spritesuite-"+(slug or "projekt"))
        self.mod_name.set("SpriteSuite "+chosen.name)
        self._sync_hud()
        self.refresh()
        return True

    def create_project(self):
        slug=simpledialog.askstring("Neues Mod-Projekt",
            "Projekt-ID (a-z, 0-9, Bindestrich; mindestens 3 Zeichen):",
            initialvalue="mein-mod-projekt",parent=self)
        if not slug:return
        if not self._save_pending("dem Anlegen eines anderen Projekts"):
            return None
        try:
            location=new_project(slug)
            self.activate_project(location)
        except (ValueError,OSError) as exc:
            messagebox.showerror("Neues Projekt",str(exc),parent=self)

    def choose_project(self):
        selected=filedialog.askdirectory(
            parent=self,title="Vorhandenes SpriteSuite-Projekt unter work/ öffnen",
            initialdir=str(hud.WORK))
        if not selected:return
        try:self.activate_project(Path(selected))
        except (OSError,ValueError) as exc:
            messagebox.showerror("Projektwechsel",str(exc),parent=self)

    def backup_project(self):
        """Portable EDITABLE project ZIP, distinct from installable asset ZIP."""
        if not self._save_pending("der Projektsicherung"):
            return None
        destination=filedialog.asksaveasfilename(
            parent=self,title="Bearbeitbares Projekt samt Noesis-Revisionen sichern",
            initialfile="SpriteSuite-"+self.pipeline.project.name+".zip",
            defaultextension=".zip",
            filetypes=[("SpriteSuite-Projekt-ZIP","*.zip")])
        if not destination:return None
        try:
            from hud_menu_project_transfer import create_archive
            report=create_archive(self.pipeline.project,Path(destination))
            self._set_message(
                "Bearbeitbares Projekt gesichert: "+report["archive"]+
                " · "+str(report["files"])+" Dateien · SHA-256 "+
                report["sha256"][:16]+"… · nicht als Spiel-Mod installieren")
            return report
        except (OSError,ValueError) as exc:
            messagebox.showerror("Projektarchiv fehlgeschlagen",
                                 str(exc),parent=self)
            return None

    def restore_project(self):
        source=filedialog.askopenfilename(
            parent=self,title="Bearbeitbares SpriteSuite-Projekt-ZIP öffnen",
            filetypes=[("SpriteSuite-Projekt-ZIP","*.zip")])
        if not source:return None
        if not self._save_pending("dem Projektwechsel"):
            return None
        try:
            from hud_menu_project_transfer import (
                archive_info,restore_archive,suggest_project_name)
            info=archive_info(Path(source))
            suggested=suggest_project_name(info["project_name"])
            name=simpledialog.askstring("Projektkopie öffnen",
                "Neuer freier Projektname (kein Überschreiben):",
                initialvalue=suggested,parent=self)
            if not name:return None
            restored=restore_archive(Path(source),project_name=name)
            if not self.activate_project(Path(restored["project"])):
                raise UnifiedFlowError("Projekt konnte nicht aktiviert werden")
            self._set_message(
                "Bearbeitbares Projekt und Noesis-Revisionen wiederhergestellt: "+
                restored["project"]+" · Originale getrennt vom Mod-Paket")
            return restored
        except (OSError,ValueError) as exc:
            messagebox.showerror("Projekt-ZIP öffnen",str(exc),parent=self)
            return None

    def add_sources(self):
        paths=filedialog.askopenfilenames(parent=self,
                title="Grafik oder Noesis-XAML-Original wählen (Quelle bleibt unverändert)",
                filetypes=[("Grafik, Noesis & Video","*.png *.jpg *.jpeg *.webp *.xaml *.webm"),
                           ("Alle Dateien","*.*")])
        if not paths:return
        # A new source must not orphan unsaved edits in an already opened
        # original-page editor. No imports occur if the user declines.
        if any(Path(raw).suffix.lower()==".xaml" for raw in paths):
            if not self._save_pending("dem Wechsel der Noesis-Quelle"):
                return None
        imported=[];failed=[];original_registered=False
        for raw in paths:
            source=Path(raw)
            try:
                suffix=source.suffix.lower()
                if suffix in {".png",".jpg",".jpeg",".webp"}:
                    file=self.pipeline.import_image(source,category=self.category.get())
                    imported.append(file)
                elif suffix==".xaml":
                    root=ElementTree.fromstring(source.read_bytes())
                    if root.tag.split("}")[-1] in {"Patch","XamlPatch"}:
                        imported.append(self.pipeline.import_patch(source))
                    else:
                        previous=self.pipeline.original_xaml()
                        self.pipeline.register_original_xaml(source)
                        original_registered=True
                        if (previous is not None and
                            (previous.name!=source.name or
                             previous.read_bytes()!=source.read_bytes())):
                            self._close_saved_project_editors(
                                self.pipeline.project,only_noesis=True)
                elif suffix==".webm":
                    imported.append(hud.import_media(source,
                        resource="Override/Assets/GUI/Video/"+source.name,
                        project=self.pipeline.project))
                else:
                    raise UnifiedFlowError("Nicht unterstützte Eingabe")
            except (OSError,ValueError,ElementTree.ParseError) as exc:
                failed.append(source.name+": "+str(exc))
        self.refresh()
        if imported:
            self.select_asset(imported[-1])
        self._set_message(
            f"{len(imported)} Ressource(n) übernommen"+
            (" · Original-Menüseite als Vorlage gespeichert" if original_registered else "")+
            (" · "+ "; ".join(failed[:2]) if failed else
             " · Alle Änderungen bleiben in diesem Projekt."))
        if original_registered and not failed:
            self.open_noesis()
        if failed:
            messagebox.showwarning("Einige Quellen nicht übernommen",
                "\n".join(failed[:8]),parent=self)

    def make_blank(self):
        answer=simpledialog.askstring("Leeres Bild erstellen",
            "Name und Größe, z. B. Wappen 256x256:",
            initialvalue="Wappen 256x256",parent=self)
        if not answer:return
        match=re.fullmatch(r"(.{1,90}?)\s+(\d{1,4})x(\d{1,4})",answer.strip())
        if not match:
            messagebox.showerror("Bildgröße","Bitte 'Name 256x256' eingeben.",parent=self)
            return
        try:
            result=self.pipeline.create_image(match[1],int(match[2]),int(match[3]),
                                              category=self.category.get())
            self.refresh();self.select_asset(result)
            self._set_message("Transparentes Bild erzeugt: "+str(result))
        except (OSError,ValueError) as exc:
            messagebox.showerror("Bild erstellen",str(exc),parent=self)

    def refresh(self):
        try:
            previous=self._selected
            self._assets=self.pipeline.assets()
            self.project_text.set("Aktives Projekt: "+self.pipeline.project.name)
            source=self.pipeline.original_xaml()
            self.source_text.set(
                "Noesis-Original: "+source.name+" (geprüfte private Kopie)"
                if source else
                "Noch keine originale Noesis-Menüseite zugeordnet. Bilder lassen sich auch allein bearbeiten.")
            self.tree.delete(*self.tree.get_children())
            keep=None
            for i,asset in enumerate(self._assets):
                iid=str(i)
                self.tree.insert("","end",iid=iid,
                    text=asset.name,values=(asset.kind,asset.status))
                if asset.relative_path==previous:keep=iid
            if keep is None and self._assets:keep="0"
            if keep is not None:
                self.tree.selection_set(keep)
                self.tree.see(keep)
                self._select()
            else:
                self._selected=None;self._photo=None
                self.preview.configure(text="Noch kein Bild im Projekt",image="")
                self.selection_text.set("Originale hinzufügen oder ein transparentes PNG erstellen.")
            self.check_text.set(
                str(len(self._assets))+" Arbeitsdatei(en) · "+
                "Paketprüfung vor dem Export erforderlich")
            previous=self.pipeline.latest_export()
            self._last_export=previous
            if previous is not None:
                if previous["project_current"]:
                    self.result_text.set(
                        "Letztes geprüftes ZIP: "+previous["zip"]+
                        " · SHA-256 "+previous["zip_sha256"][:16]+"…")
                else:
                    self.result_text.set(
                        "Projekt wurde seit dem letzten ZIP verändert. "+
                        "Bitte erneut prüfen und exportieren.")
            else:
                self.result_text.set("Noch kein geprüfter Export für dieses Projekt.")
        except (ValueError,OSError) as exc:
            self.check_text.set("Projekt kann nicht gelesen werden: "+str(exc))
            self._set_message("Prüfung der Arbeitsdateien fehlgeschlagen.")

    def on_activate(self):
        """When returning from a legacy editor, follow its saved project."""
        record=read_session()
        candidate=record.get("project")
        if candidate is not None and candidate!=self.pipeline.project:
            self.activate_project(candidate)
        else:self.refresh()

    def select_asset(self,path:Path):
        rel=Path(path).relative_to(self.pipeline.project).as_posix()
        for i,asset in enumerate(self._assets):
            if asset.relative_path==rel:
                self.tree.selection_set(str(i))
                self.tree.see(str(i))
                self._select()
                break

    def selected_asset(self):
        chosen=self.tree.selection()
        if not chosen:return None
        index=int(chosen[0])
        if index<0 or index>=len(self._assets):return None
        return self._assets[index]

    def _select(self,_event=None):
        item=self.selected_asset()
        if item is None:return
        self._selected=item.relative_path
        self.selection_text.set(
            item.relative_path+"\n"+item.status+"\n"+str(item.size)+" Bytes")
        try:save_session(self.pipeline.project,asset=item.relative_path)
        except (OSError,ValueError):pass
        if item.path.suffix.lower() not in (".png",".jpeg",".jpg",".webp"):
            self._photo=None
            self.preview.configure(image="",text="Kein Pixelbild – passenden Editor öffnen")
            return
        try:
            with Image.open(item.path) as img:
                if img.width*img.height>30_000_000:raise ValueError("Bild zu groß")
                bitmap=img.convert("RGBA")
                bitmap.thumbnail((345,215),Image.Resampling.LANCZOS)
            self._photo=ImageTk.PhotoImage(bitmap,master=self.preview)
            self.preview.configure(image=self._photo,text="")
        except (OSError,ValueError) as exc:
            self._photo=None
            self.preview.configure(image="",text="Vorschau ungültig: "+str(exc))

    def edit_selected(self):
        item=self.selected_asset()
        if item is None:
            self._set_message("Zuerst eine Datei in der Projektliste auswählen.")
            return None
        if item.path.suffix.lower() not in (".png",".xaml",".json",".txt"):
            self._set_message("Für diese Datei gibt es keinen integrierten Editor.")
            return None
        existing=self._active_editors.get(item.relative_path)
        if existing is not None and existing.winfo_exists():
            existing.lift();existing.focus_set();return existing
        try:
            from suite_hud_menu_editor import HudMenuPixelEditor,HudMenuTextEditor
            cls=HudMenuPixelEditor if item.path.suffix.lower()==".png" else HudMenuTextEditor
            window=cls(self,item.path,project=self.pipeline.project,after_save=self.refresh)
            self._active_editors[item.relative_path]=window
            window.focus_set()
            self._set_message("Editor geöffnet · Speichern aktualisiert dieselbe Projektdatei.")
            return window
        except (OSError,ValueError) as exc:
            messagebox.showerror("Datei bearbeiten",str(exc),parent=self)
            return None

    def bind_selected_image(self):
        """Bridge the project asset and Noesis Image.Source without reimporting."""
        item=self.selected_asset()
        if item is None or not item.relative_path.startswith(
                "Override/Assets/GUI/Images/") or item.path.suffix.lower()!=".png":
            self._set_message(
                "Bitte zuerst ein PNG unter Menü-/UI-Bilder auswählen.")
            return None
        window=self.open_noesis()
        if window is None:return None
        try:
            source=window.bind_project_image(item.path)
            self._set_message(
                "Bild mit Noesis-Image verbunden: "+source+
                " · Menürevision im Noesis-Editor speichern, danach Paket prüfen.")
            window.lift()
            return source
        except (OSError,ValueError) as exc:
            self._set_message(str(exc))
            window.lift()
            return None

    def open_layout(self):
        existing=self._layout_window
        if existing is not None and existing.winfo_exists():
            existing.lift();existing.focus_set();return existing
        selected=self.selected_asset()
        source=(selected.relative_path if selected and
                selected.path.suffix.lower()==".png" else None)
        try:
            from suite_hud_menu_layout_editor import HudMenuLayoutEditor
            self._layout_window=HudMenuLayoutEditor(
                self,project=self.pipeline.project,source_asset=source,
                after_export=self.refresh)
            self._layout_window.focus_set()
            return self._layout_window
        except (OSError,ValueError) as exc:
            messagebox.showerror("Layout gestalten",str(exc),parent=self)
            return None

    def open_noesis(self):
        existing=self._visual_window
        if existing is not None and existing.winfo_exists():
            existing.lift();existing.focus_set();return existing
        try:
            source=self.pipeline.original_xaml()
            if source is None:
                selected=filedialog.askopenfilename(
                    parent=self,title="Original-Noesis-XAML für den visuellen Editor",
                    filetypes=[("Original-XAML","*.xaml")])
                if not selected:return None
                source=self.pipeline.register_original_xaml(Path(selected))
            from suite_origins_visual_editor import OriginsVisualEditor
            from origins_visual_document import VisualXamlDocument
            window=OriginsVisualEditor(self,project=self.pipeline.project,
                         source=source,after_export=self.refresh)
            revision=self.pipeline.latest_visual_revision()
            if revision is not None:
                window.doc=VisualXamlDocument.reopen(revision)
                window._saved_document_bytes=window.doc.edited_bytes()
                window.title_var.set("Letzte bearbeitete Version: "+revision.name)
                window.refresh_tree()
            self._visual_window=window
            window.focus_set()
            self._set_message("Noesis-Designer geöffnet · Patch und Revision speichern "+
                              "legt die echte XAML-Patchdatei in dasselbe Projekt.")
            self.refresh()
            return window
        except (OSError,ValueError) as exc:
            messagebox.showerror("Noesis-Menüseite",str(exc),parent=self)
            return None

    def open_native_preview(self):
        from suite_noesis_native_live_preview import open_native_noesis_live
        return open_native_noesis_live(self)

    def check_steam_compatibility(self):
        """Run only the read-only Steam capability report via the GUI runner."""
        tool=Path(__file__).resolve().parent/"suite_steam_compatibility.py"
        if not tool.is_file():
            self._set_message("Steam-Kompatibilitätsdiagnose fehlt.")
            return False
        started=self.app.run(
            [str(tool),"--project",str(Path(__file__).resolve().parents[1])],
            "Steam-Spielversion und Sprite-Mapping sicher prüfen")
        if started:
            self._set_message(
                "Lokale Steam-Version wird lesend geprüft. "
                "Keine Modinstallation oder native ABI-Freigabe.")
        return started

    def check_project(self):
        if not self._save_pending("der Prüfung"):
            return None
        try:
            result=self.pipeline.audit()
            if result["warnings"]:
                self.check_text.set(
                    f"{result['assets']} Dateien geprüft · "+
                    f"{len(result['warnings'])} Hinweis(e) zur Spielanbindung")
                self._set_message(result["warnings"][0])
            else:
                self.check_text.set(
                    f"{result['assets']} Dateien geprüft · SHA-256 "+
                    result["bytes_sha256"][:16]+"…")
                self._set_message(
                    "Statische Assets und XAML syntaktisch geprüft. "+
                    "Native Spielbefehle benötigen weiterhin einen Ingame-Test.")
            return result
        except (OSError,ValueError) as exc:
            self.check_text.set("Prüfung fehlgeschlagen: "+str(exc))
            self._set_message("Keine Paketfreigabe: "+str(exc))
            return None

    def build_package(self):
        if not self._save_pending("dem Mod-Paketbau"):
            return None
        # Never leave a previous export as the active result of a failed
        # build attempt. Its files and receipt remain untouched.
        self._last_export=None
        self.result_text.set("Prüfe das Projekt und erstelle das Paket …")
        self.update_idletasks()
        try:
            outcome=self.pipeline.build(
                guid=self.guid.get().strip(),
                name=self.mod_name.get().strip())
            self._last_export=outcome
            self.result_text.set(
                f"FERTIG: {outcome['asset_count']} geprüfte Dateien · "+
                "ZIP "+str(outcome["zip"])+" · SHA-256 "+
                outcome["zip_sha256"][:16]+"…")
            self.check_text.set(
                "Unabhängiger ZIP-/Assetvergleich bestanden · "+
                str(len(outcome["warnings"]))+" Hinweise")
            self._set_message(
                "Ein tatsächlich geprüftes, DLL-freies Mod-ZIP wurde erstellt. "+
                "Keine Spielinstallation vorgenommen; Ingame-Funktion bleibt separat zu prüfen.")
            return outcome
        except (OSError,ValueError,RuntimeError) as exc:
            self.result_text.set("Kein gültiges Paket erstellt: "+str(exc))
            self._set_message("Export gestoppt; keine Erfolgsmeldung: "+str(exc))
            return None

    def open_result(self):
        outcome=self._last_export
        if outcome is None:
            self._set_message("Zuerst ein gültiges Mod-ZIP erstellen.")
            return None
        try:
            verified=self.pipeline.latest_export()
            if (verified is None or not verified["project_current"] or
                    verified["zip"]!=outcome["zip"] or
                    verified["zip_sha256"]!=outcome["zip_sha256"]):
                raise UnifiedFlowError("Letztes Mod-ZIP ist veraltet oder nicht mehr zugeordnet")
            zipfile=Path(verified["zip"])
            if not zipfile.is_file():
                raise UnifiedFlowError("Exportdatei ist nicht mehr vorhanden")
        except (OSError,ValueError,KeyError,TypeError) as exc:
            self._last_export=None
            self._set_message("Geprüftes Mod-ZIP nicht mehr verwendbar: "+str(exc))
            return None
        try:os.startfile(str(zipfile.parent))
        except (OSError,ValueError) as exc:
            messagebox.showerror("Export öffnen",str(exc),parent=self)
            return None
        return zipfile

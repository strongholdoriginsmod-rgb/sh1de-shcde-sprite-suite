"""Integrated HUD/Menu Workshop: discover, paint, inspect and package graphics.

Existing SH1 HUD, Origins LFS, Noesis atlas and HTML editors remain separate
specialists but become reachable from one workspace. All edits are under work/.
"""
from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from hud_menu_workspace import (
    CATEGORIES, DEFAULT, WorkshopError, audit_assets, create_image,
    duplicate_image, import_image, import_patch, list_assets, restore_image, workspace,
)
from suite_usability import CompactActionBar

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"


class HudMenuWorkshop(ttk.Frame):
    """Owns no games or original assets; exposes explicit editing operations."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.project_var = tk.StringVar(self, value="work/hud-menu-werkstatt")
        self.filter_var = tk.StringVar(self)
        self.kind_var = tk.StringVar(self, value="Menüs / UI-Bilder")
        self.edited_only = tk.BooleanVar(self, False)
        self.message = tk.StringVar(
            self,"Eigene Bilder importieren oder eine neue transparente Grafik erstellen.")
        self.detail = tk.StringVar(
            self,"HUD-/Menüschlüssel wählen · Originale und Arbeitskopien getrennt.")
        self._assets = []
        self._index = {}
        self._queue: queue.Queue = queue.Queue()
        self._busy = False
        self._build()
        self.filter_var.trace_add("write",lambda *_:self._fill())
        self.edited_only.trace_add("write",lambda *_:self._fill())
        self.after(120,self._poll)
        self.after(350,self.refresh)

    def _build(self):
        header=ttk.Frame(self)
        header.pack(fill="x",padx=12,pady=(9,2))
        ttk.Label(header,text="HUD & Menüs",style="SectionTitle.TLabel"
                  ).pack(anchor="w")
        ttk.Label(header,
                  text="Grafiken öffnen, bearbeiten und frei auf einer Fläche anordnen.",
                  style="Description.TLabel").pack(anchor="w",pady=(2,5))
        journey=ttk.Frame(self)
        journey.pack(fill="x",padx=12,pady=(3,8))
        for label,callback in (
            ("1  Bild öffnen",self.import_images),
            ("2  Pixel bearbeiten",self.edit_selected),
            ("3  Layout gestalten",self.open_layout),
            ("4  Export vorbereiten",self.export_help),
        ):
            ttk.Button(journey,text=label,style="GuideStep.TButton",
                       command=callback).pack(side="left",padx=(0,5))

        project_toggle_row=ttk.Frame(self)
        project_toggle_row.pack(fill="x",padx=12,pady=(0,2))
        self.project_toggle=ttk.Button(project_toggle_row,
            text="Arbeitsordner anzeigen",command=self.toggle_project)
        self.project_toggle.pack(side="left")
        ttk.Label(project_toggle_row,
            text="Bilder und Projekte werden nur in der SpriteSuite gespeichert.",
            style="Muted.TLabel").pack(side="left",padx=10)
        project=ttk.Frame(self)
        project.pack(fill="x",padx=12,pady=3)
        self.project_row=project
        ttk.Label(project,text="Werkstattordner:").pack(side="left")
        ttk.Entry(project,textvariable=self.project_var).pack(
            side="left",fill="x",expand=True,padx=6)
        ttk.Button(project,text="Laden / Neu",command=self.refresh).pack(side="left",padx=2)
        ttk.Button(project,text="Ordner …",command=self.pick_project).pack(side="left",padx=2)
        ttk.Button(project,text="Ordner öffnen",command=self.open_folder
                  ).pack(side="left",padx=2)
        project.pack_forget()  # Nur auf Wunsch den technischen Pfad einblenden.

        row=ttk.Frame(self)
        row.pack(fill="x",padx=12,pady=(2,1))
        self.import_row=row
        ttk.Label(row,text="Bildkategorie:").pack(side="left")
        ttk.Combobox(row,textvariable=self.kind_var,values=list(CATEGORIES),
                     state="readonly",width=20).pack(side="left",padx=6)
        ttk.Button(row,text="Transparentes PNG erstellen",
                   command=self.new_png).pack(side="left",padx=7)
        actions=CompactActionBar(self,primary=[
            ("Bilder importieren …",self.import_images),
            ("Neues transparentes PNG …",self.new_png),
            ("Ausgewählte Grafik bearbeiten",self.edit_selected),
        ],more=[
            ("XAML-Menüpatch importieren …",self.import_xaml),
            ("Bild mit neuem Resource-Key duplizieren …",self.duplicate),
            ("Aus Origins-Grafikkatalog übernehmen …",self.import_origins),
            ("Original / Bearbeitung vergleichen",self.compare),
            ("Ursprung wiederherstellen …",self.restore),
            ("Resource-Key kopieren",self.copy_key),
            ("PNG extern bearbeiten",self.external_edit),
        ],overflow_label="Bearbeitungswerkzeuge ▾")
        self.actions_row=actions
        actions.pack(fill="x",padx=12,pady=(2,5))
        actions.pack_forget()

        tool_toggle=ttk.Frame(self)
        tool_toggle.pack(fill="x",padx=12,pady=(2,3))
        self.tools_toggle=ttk.Button(tool_toggle,text="Weitere Grafikwerkzeuge anzeigen",
                  command=self.toggle_tools)
        self.tools_toggle.pack(side="left")
        toolstrip=ttk.Frame(self)
        toolstrip.pack(fill="x",padx=12,pady=(0,5))
        self.tools_row=toolstrip
        CompactActionBar(
            toolstrip,
            primary=[
                ("SH1 HUD-Studio",self.goto_sh1),
                ("ORIGINS · Menü- & HUD-Katalog",self.goto_origins),
            ],
            more=[
                ("HTML-Sprite-Editor",self.goto_html),
                ("AtlasBuilder / ORA",self.goto_exchange),
                ("Zusätzliche Noesis-Atlanten",self.goto_noesis),
            ],
            overflow_label="Weitere Grafikwerkzeuge ▾",
        ).pack(fill="x")
        toolstrip.pack_forget()  # SH1 HUD, ORIGINS und Spezialwerkzeuge bleiben erreichbar.

        pipeline=ttk.Frame(self)
        self.pipeline=pipeline
        pipeline.pack(fill="x",padx=12,pady=(1,7))
        ttk.Button(
            pipeline,text="Layout-Designer · direkt ziehen & skalieren",
            command=self.open_layout,
        ).pack(side="left",padx=3)
        ttk.Button(pipeline,text="1 · Assets & XAML prüfen",command=self.audit
                  ).pack(side="left",padx=3)
        ttk.Button(pipeline,text="2 · DLL-freies HUD-/Menüpaket bauen",
                   command=self.build).pack(side="left",padx=4)
        ttk.Label(pipeline,text="Paketbau verändert kein installiertes Spiel.",
                  style="Muted.TLabel").pack(anchor="w",pady=(4,0))
        pipeline.pack_forget()  # Nur in "Weitere Grafikwerkzeuge" anzeigen.

        panes=ttk.PanedWindow(self,orient="horizontal")
        self.panes=panes
        panes.pack(fill="both",expand=True,padx=10,pady=3)
        left=ttk.Frame(panes);right=ttk.Frame(panes)
        panes.add(left,weight=3);panes.add(right,weight=2)
        filters=ttk.Frame(left);filters.pack(fill="x",pady=(0,4))
        ttk.Label(filters,text="Suche:").pack(side="left")
        search=ttk.Entry(filters,textvariable=self.filter_var)
        search.pack(side="left",fill="x",expand=True,padx=5)
        search.bind("<Escape>",lambda _:self.filter_var.set(""))
        ttk.Checkbutton(filters,text="Nur bearbeitet",
                        variable=self.edited_only).pack(side="left")

        listing=ttk.Frame(left);listing.pack(fill="both",expand=True)
        self.tree=ttk.Treeview(
            listing,columns=("kind","status","size"),
            show="tree headings",selectmode="browse",height=13)
        self.tree.heading("#0",text="Menü-/HUD-Resource-Key")
        self.tree.column("#0",width=165,minwidth=115,stretch=True)
        for code,title,width in (
            ("kind","Bereich",84),("status","Stand",65),("size","Bytes",50)):
            self.tree.heading(code,text=title)
            self.tree.column(code,width=width,minwidth=46,stretch=False)
        scroll=ttk.Scrollbar(listing,command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right",fill="y")
        self.tree.pack(side="left",fill="both",expand=True)
        self.tree.tag_configure("edited",foreground="#62bd91")
        self.tree.tag_configure("unknown",foreground="#d6a25a")
        self.tree.bind("<<TreeviewSelect>>",self._show_selected)
        self.tree.bind("<Double-1>",lambda _:self.edit_selected())
        self.tree.bind("<Return>",lambda _:self.edit_selected())

        preview_class=self.app.tab_ui.preview.__class__
        self.tabs=ttk.Notebook(right)
        self.tabs.pack(fill="both",expand=True)
        preview_work=ttk.Frame(self.tabs);preview_original=ttk.Frame(self.tabs)
        self.tabs.add(preview_work,text="Bild")
        self.tabs.add(preview_original,text="Original")
        # Der frühere Reiter "Layout · Live-Vorschau" heißt nun kurz "Layout".
        live_frame=ttk.Frame(self.tabs)
        self.tabs.add(live_frame,text="Layout")
        ttk.Label(
            live_frame,
            text="Elemente direkt auf einer interaktiven Gesamtvorschau "
                 "ziehen, skalieren, drehen und exakt positionieren. "
                 "Die Ebenen, Anker, Pivots und Koordinaten bleiben dauerhaft "
                 "gespeichert; der Export verarbeitet dieselben Werte.",
            wraplength=290,justify="left",
        ).pack(fill="x",padx=12,pady=(20,14))
        ttk.Button(
            live_frame,
            text="Interaktive Vorschau und Ebenen-Designer öffnen …",
            command=self.open_layout,
        ).pack(fill="x",padx=12,pady=6)
        self.preview=preview_class(
            preview_work,empty_text="PNG auswählen oder eigene Menügrafik importieren.")
        self.preview.pack(fill="both",expand=True)
        self.original=preview_class(
            preview_original,empty_text="Geprüfte Importbasis für Vorher/Nachher.")
        self.original.pack(fill="both",expand=True)
        ttk.Label(right,textvariable=self.detail,style="Muted.TLabel",
                  wraplength=285,justify="left").pack(fill="x",pady=(4,2))
        ttk.Label(self,textvariable=self.message,style="Muted.TLabel",
                  wraplength=1400,justify="left").pack(fill="x",padx=12,pady=4)

    def toggle_project(self):
        """Technische Arbeitsordner-Pfade bei Bedarf sichtbar machen."""
        if self.project_row.winfo_manager() == "pack":
            self.project_row.pack_forget()
            self.project_toggle.configure(text="Arbeitsordner anzeigen")
        else:
            self.project_row.pack(before=self.import_row,fill="x",padx=12,pady=3)
            self.project_toggle.configure(text="Arbeitsordner verbergen")

    def toggle_tools(self):
        """Zusätzliche Werkzeugleisten und den Rohbild-Paketbau aufklappen."""
        if self.tools_row.winfo_manager() == "pack":
            for widget in (self.actions_row,self.tools_row,self.pipeline):
                widget.pack_forget()
            self.tools_toggle.configure(text="Weitere Grafikwerkzeuge anzeigen")
        else:
            self.actions_row.pack(before=self.panes,fill="x",
                                  padx=12,pady=(1,4))
            self.tools_row.pack(before=self.panes,fill="x",
                                padx=12,pady=(0,4))
            self.pipeline.pack(before=self.panes,fill="x",
                                padx=12,pady=(0,6))
            self.tools_toggle.configure(text="Weitere Grafikwerkzeuge verbergen")

    def export_help(self):
        """Erklärt die beiden unterschiedlichen Paketarten vor dem Export."""
        window=self.open_layout()
        if window is None:
            return
        messagebox.showinfo(
            "Layout exportieren",
            "Im Layout-Designer zunächst mindestens ein Bild einfügen, "
            "dann Position und Größe einstellen.\n\n"
            "1. »Speichern · Strg+S« sichert alle Ebenen und Positionen.\n"
            "2. »Layout → PNG + Positionsdaten« erstellt das fertige Bild.\n"
            "3. »Spieloberfläche anbinden (Noesis)« verknüpft diese Grafik "
            "mit einem tatsächlich vorhandenen Spielmenü.\n\n"
            "»DLL-freies HUD-/Menüpaket bauen« hier im Hauptfenster ist "
            "dagegen für die vorhandenen einzelnen Werkstattdateien gedacht. "
            "Es verschiebt keine Schaltflächen im Spiel.",
            parent=window,
        )

    def _project(self,create=False):
        return workspace(self.project_var.get().strip() or DEFAULT,create=create)

    def refresh(self):
        try:
            self._assets=list_assets(self._project(create=True))
            self._index={a.relative_path:a for a in self._assets}
            edited=sum(a.status=="Bearbeitet" for a in self._assets)
            unknown=sum(a.status=="Ohne Importbasis" for a in self._assets)
            self.message.set(f"{len(self._assets)} HUD-/Menüressourcen im Arbeitsordner · "
                             f"{edited} bearbeitet · {unknown} ohne Importbasis.")
            self._fill()
        except (OSError,ValueError,WorkshopError) as exc:
            self._assets=[];self._index={}
            self.message.set(f"Werkstatt konnte nicht gelesen werden: {exc}")
            self._fill()

    def _fill(self):
        if not hasattr(self,"tree"):return
        old=self.selected_asset()
        oldpath=old.relative_path if old else None
        self.tree.delete(*self.tree.get_children())
        term=self.filter_var.get().strip().casefold()
        first=None;chosen=None
        for i,asset in enumerate(self._assets):
            if term and term not in (asset.relative_path+" "+asset.kind).casefold():
                continue
            if self.edited_only.get() and asset.status!="Bearbeitet":
                continue
            iid=str(i)
            self.tree.insert("", "end", iid=iid,text=asset.relative_path,
                             values=(asset.kind,asset.status,asset.size),
                             tags=("edited",) if asset.status=="Bearbeitet"
                             else ("unknown",) if asset.baseline_path is None
                             else ())
            if first is None:first=iid
            if asset.relative_path==oldpath:chosen=iid
        if chosen or first:
            self.tree.selection_set(chosen or first)
            self._show_selected()
        else:
            self.preview.clear("Noch keine passenden Bilder vorhanden.")
            self.original.clear("Keine Importbasis geladen.")
            self.detail.set("Importiere PNG/JPEG/WebP oder beginne mit einem transparenten Bild.")

    def selected_asset(self):
        selection=self.tree.selection() if hasattr(self,"tree") else ()
        if not selection:return None
        number=int(selection[0])
        return self._assets[number] if number<len(self._assets) else None

    def _show_selected(self,_event=None):
        asset=self.selected_asset()
        if not asset:return
        self.detail.set(
            f"{asset.relative_path}\n{asset.kind} · {asset.status} · "
            f"{asset.size:,} Bytes\nResource-Key wird nicht automatisch "
            "in bestehenden XAML-/Atlas-Mappings geändert.")
        if asset.path.suffix.lower() in (".png",".jpg",".jpeg"):
            self.preview.show(asset.path,title=asset.name,
                              detail="Lokale Arbeitskopie · Doppelklick zum Bearbeiten")
            if asset.baseline_path:
                self.original.show(asset.baseline_path,title="Ursprünglich importiert",
                                   detail="SHA-256-gebundener Snapshot unter work/")
            else:
                self.original.clear("Kein baselined Original (fremd hinzugefügt).")
        else:
            self.preview.clear("XAML/JSON/DDS: Mit Texteditor oder externem Grafikprogramm bearbeiten.")
            self.original.clear("Kein automatisch geladener Pixelvergleich.")

    def pick_project(self):
        folder=filedialog.askdirectory(
            parent=self,title="Werkstattordner unter SpriteSuite/work/ wählen",
            initialdir=str(ROOT/"work"))
        if folder:
            try:
                selected=workspace(folder,create=True)
                self.project_var.set(str(selected))
                self.refresh()
            except (ValueError,OSError) as exc:
                messagebox.showerror("Arbeitsordner",str(exc),parent=self)

    def open_folder(self):
        try:os.startfile(str(self._project(create=True)))
        except (OSError,ValueError) as exc:
            messagebox.showerror("Arbeitsordner",str(exc),parent=self)

    def import_images(self):
        files=filedialog.askopenfilenames(
            parent=self,title="Eigene PNG/JPEG/WebP für HUD oder Menüs auswählen",
            filetypes=[("Bilddateien","*.png *.jpg *.jpeg *.webp")])
        if not files:return
        folder=self.kind_var.get()
        root=self._project(create=True)
        if not messagebox.askyesno(
            "Grafiken als bearbeitbare Kopien importieren",
            f"{len(files)} Grafiken nach {folder} kopieren?\n"
            "Quelle bleibt unverändert, vorhandene Resource-Keys werden nicht überschrieben.",
            parent=self,default="no"):
            return
        good=[];errors=[]
        for file in files:
            try:
                result=import_image(file,folder=folder,project=root)
                good.append(result.name)
            except (ValueError,OSError) as exc:
                errors.append(f"{Path(file).name}: {exc}")
        self.refresh()
        self.message.set(f"{len(good)} Grafiken importiert, {len(errors)} Fehler."
                         +(" "+ "; ".join(errors[:3]) if errors else ""))

    def new_png(self):
        name=simpledialog.askstring(
            "Transparentes PNG","Resource-Name (ohne Endung):",
            parent=self,initialvalue="NeuesMenuBild")
        if not name:return
        width=simpledialog.askinteger(
            "Breite","Breite in Pixeln:",parent=self,
            initialvalue=256,minvalue=1,maxvalue=4096)
        if width is None:return
        height=simpledialog.askinteger(
            "Höhe","Höhe in Pixeln:",parent=self,
            initialvalue=128,minvalue=1,maxvalue=4096)
        if height is None:return
        try:
            file=create_image(name,width,height,folder=self.kind_var.get(),
                              project=self._project(create=True))
            self.refresh()
            self._select_path(file)
        except (ValueError,OSError) as exc:
            messagebox.showerror("PNG erstellen",str(exc),parent=self)

    def _select_path(self,path):
        rel=Path(path).relative_to(self._project()).as_posix()
        for idx,asset in enumerate(self._assets):
            if asset.relative_path==rel and self.tree.exists(str(idx)):
                self.tree.selection_set(str(idx))
                self.tree.see(str(idx))
                self._show_selected()
                return

    def duplicate(self):
        asset=self.selected_asset()
        if asset is None or asset.path.suffix.lower()!=".png":
            messagebox.showinfo(
                "Duplizieren","Bitte zuerst ein PNG-Bild auswählen.",parent=self)
            return
        name=simpledialog.askstring(
            "Neue Ressource","Neuer Resource-Key / Dateiname ohne .png:",
            parent=self,initialvalue=asset.path.stem+"-Variante")
        if not name:return
        folder=self.kind_var.get()
        try:
            newfile=duplicate_image(
                asset.relative_path,name=name,folder=folder,
                project=self._project())
            self.refresh()
            self._select_path(newfile)
            self.message.set("Neue unabhängige Bildressource erstellt. "
                             "XAML/Atlas-Verweise müssen ausdrücklich angepasst werden.")
        except (ValueError,OSError) as exc:
            messagebox.showerror("Duplizieren",str(exc),parent=self)

    def open_layout(self):
        """Open the real interactive preview; keep the current artwork selected."""
        try:
            root=self._project(create=True)
            selected=self.selected_asset()
            source=(selected.relative_path if selected is not None
                    and selected.path.suffix.lower()==".png" else None)
            existing=getattr(self,"_layout_window",None)
            if existing is not None and existing.winfo_exists():
                if source:existing.source_choice.set(source)
                existing.lift()
                existing.focus_set()
                return existing
            from suite_hud_menu_layout_editor import HudMenuLayoutEditor
            window=HudMenuLayoutEditor(
                self,project=root,source_asset=source,
                after_export=self.refresh)
            self._layout_window=window
            window.focus_set()
            return window
        except (OSError,ValueError) as exc:
            messagebox.showerror("Layout-Designer",str(exc),parent=self)
            return None

    def import_xaml(self):
        file=filedialog.askopenfilename(
            parent=self,title="Eigenen statischen Noesis-XAML-Patch auswählen",
            filetypes=[("Noesis XAML","*.xaml")])
        if not file:return
        try:
            result=import_patch(file,project=self._project(create=True))
            self.refresh()
            self._select_path(result)
        except (ValueError,OSError) as exc:
            messagebox.showerror("XAML-Patch",str(exc),parent=self)

    def edit_selected(self):
        asset=self.selected_asset()
        if asset is None:
            messagebox.showinfo("Grafik", "Erst Bild auswählen oder importieren.",parent=self)
            return
        try:
            if asset.path.suffix.lower()==".png":
                from suite_hud_menu_editor import HudMenuPixelEditor
                window=HudMenuPixelEditor(self,asset.path,
                                         project=self._project(),after_save=self.refresh)
            elif asset.path.suffix.lower() in {".xaml",".json"}:
                from suite_hud_menu_editor import HudMenuTextEditor
                window=HudMenuTextEditor(self,asset.path,
                                        project=self._project(),after_save=self.refresh)
            else:
                self.external_edit()
                return
            window.focus_set()
        except (ValueError,OSError) as exc:
            messagebox.showerror("Bearbeiten",str(exc),parent=self)

    def external_edit(self):
        asset=self.selected_asset()
        if asset is None:return
        try:
            if asset.path.is_symlink() or not asset.path.is_file():
                raise WorkshopError("Ungültige lokale Arbeitsdatei")
            os.startfile(str(asset.path))
            self.message.set("Externe Bearbeitung geöffnet · danach »Laden / Neu« "
                             "für aktuellen Pixelvergleich verwenden.")
        except (ValueError,OSError) as exc:
            messagebox.showerror("Externer Editor",str(exc),parent=self)

    def compare(self):
        self.tabs.select(1)
        self._show_selected()

    def restore(self):
        asset=self.selected_asset()
        if not asset:return
        if asset.baseline_path is None:
            messagebox.showinfo("Ursprung","Keine geprüfte Importbasis vorhanden.",parent=self)
            return
        if not messagebox.askyesno(
            "Ursprung wiederherstellen",
            f"{asset.relative_path}\n\nArbeitsbild auf ursprünglichen Import zurücksetzen?\n"
            "Eine geänderte Fassung wird separat unter work/ gesichert.",
            parent=self,default="no"):
            return
        try:
            restore_image(asset.relative_path,project=self._project())
            self.refresh()
            self.message.set("Originalimport wiederhergestellt; "
                             "voriger Stand unter .hud-menu-revisions gesichert.")
        except (ValueError,OSError) as exc:
            messagebox.showerror("Wiederherstellung",str(exc),parent=self)

    def copy_key(self):
        asset=self.selected_asset()
        if not asset:return
        self.clipboard_clear()
        self.clipboard_append(asset.relative_path)
        self.message.set("Resource-Key kopiert: "+asset.relative_path)

    def import_origins(self):
        origins=getattr(self.app,"origins_graphics_tab",None)
        item=origins.selected_item() if origins is not None else None
        if not item:
            self.goto_origins()
            messagebox.showinfo("ORIGINS Grafik",
                "Im ORIGINS-Katalog ein HUD-/Menübild auswählen und hier "
                "»Aus Origins übernehmen« erneut wählen.",parent=self)
            return
        if item.get("format","").lower() not in ("png","jpg","jpeg"):
            messagebox.showerror("ORIGINS Grafik","Nur PNG/JPG bearbeitbar.",parent=self)
            return
        if not messagebox.askyesno(
            "Originalgrafik als lokale Bearbeitungskopie",
            f"{item['path']}\n\nDie Git-/LFS-Quelle wird erst per SHA geprüft. "
            "Danach wird die Bildkopie im Werkstattordner erzeugt. "
            "Noesis-Ressourcenschlüssel werden nicht automatisch geändert.",
            parent=self,default="no"):
            return
        if self._busy:return
        folder=self.kind_var.get()
        project=self._project(create=True)
        repo=origins._source_folder()
        self._busy=True
        self.message.set("Prüfe ORIGINS/Git-LFS-Bild im Hintergrund ...")

        def task():
            try:
                from origins_grafikdaten import checked_source_file
                file=checked_source_file(repo,item)
                result=import_image(file,folder=folder,project=project)
                self._queue.put((True,str(result)))
            except (ValueError,OSError,RuntimeError) as exc:
                self._queue.put((False,str(exc)))
        threading.Thread(target=task,daemon=True).start()

    def _poll(self):
        try:
            while True:
                ok,detail=self._queue.get_nowait()
                self._busy=False
                if ok:
                    self.refresh()
                    self._select_path(Path(detail))
                    self.message.set("SHA-geprüfte Origins-Grafik als "
                                     "neue bearbeitbare Kopie übernommen.")
                else:
                    self.message.set("ORIGINS-Kopie abgelehnt: "+detail)
                    messagebox.showerror("ORIGINS-Import",detail,parent=self)
        except queue.Empty:pass
        if self.winfo_exists():
            self.after(140,self._poll)

    def audit(self):
        try:
            report=audit_assets(self._project())
            self.message.set(
                f"Geprüft: {report['assets']} Assets, "
                f"{report['total_bytes']:,} Bytes · SHA-Vertrags-ID "
                f"{report['bytes_sha256'][:16]}… · keine Spielinstallation verändert.")
        except (ValueError,OSError) as exc:
            messagebox.showerror("Asset- und XAML-Prüfung",str(exc),parent=self)

    def build(self):
        try:
            report=audit_assets(self._project())
        except (ValueError,OSError) as exc:
            messagebox.showerror("HUD-/Menüpaket","Erst gültige Assets bereitstellen: "+str(exc),
                                 parent=self)
            return
        guid=simpledialog.askstring(
            "Asset-Mod-ID","Eindeutige GUID (nur Buchstaben, Ziffern, . _ -):",
            parent=self,initialvalue="europehudmenu")
        if not guid:return
        name=simpledialog.askstring(
            "Paketname","Name des HUD-/Menüpakets:",
            parent=self,initialvalue="Europe HUD und Menüs")
        if not name:return
        if not messagebox.askyesno(
            "DLL-freies Paket",
            f"{report['assets']} geprüfte Assets als versionneutrales "
            f"Manifest-0-Paket {guid} unter work/se-asset-mods/ bauen?\n"
            "Es erfolgt keine Änderung am Spiel oder Script Extender.",
            parent=self,default="no"):
            return
        self.app.run(
            [str(TOOLS/"se_asset_package.py"),"--source",str(self._project()),
             "--guid",guid,"--name",name],
            "HUD-/Menü-Assetpaket erstellen")

    def goto_sh1(self):
        self.app.open_tab(self.app.hud_tab)

    def goto_origins(self):
        self.app.open_tab(self.app.origins_graphics_tab)

    def goto_exchange(self):
        self.app.open_tab(self.app.exchange_tab)

    def goto_html(self):
        self.app.run([str(TOOLS/"editor_bruecke.py"),"oeffnen"],
                     "HTML-Sprite-Editor öffnen")

    def goto_noesis(self):
        self.app.run([str(TOOLS/"ui_extra_atlas_gui.py")],
                     "Zusätzliche Noesis-UI-Atlasblätter")

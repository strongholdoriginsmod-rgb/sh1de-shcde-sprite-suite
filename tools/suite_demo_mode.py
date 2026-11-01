"""Interactive, executable guided tour of individually selectable SpriteSuite modules.

This is not an animated mockup: every 'execute' calls production backends,
rewrites private bytes, reopens/validates files and logs actual artifacts.
"""
from __future__ import annotations

from difflib import unified_diff
from pathlib import Path
import json
import os
import tkinter as tk
from tkinter import ttk,filedialog,messagebox

from PIL import Image,ImageTk,UnidentifiedImageError

from suite_demo_engine import MODULES,MODULE_BY_KEY,DemoSession
from suite_windows_paths import is_link_or_reparse


class DemoMode(tk.Toplevel):
    """Full tour with module picker, per-step instruction, real files and checks."""

    def __init__(self,parent,*,project=None):
        super().__init__(parent)
        self.title("SpriteSuite · Interaktiver Demo-Modus · echte Verarbeitung")
        self.geometry("1510x900")
        self.minsize(1100,720)
        self.runs:dict[str,DemoSession]={}
        self.source_paths:dict[str,Path]={}
        self.active_key=MODULES[0].key
        self._visible_modules=list(MODULES)
        self.module_search=tk.StringVar(self)
        self._photos=[]
        self._busy=False
        self.progress=tk.StringVar(self,value="Modul wählen und starten.")
        self.current_file=tk.StringVar(self)
        self.source_display=tk.StringVar(self,value="Keine externe Originaldatei gewählt")
        self.step_heading=tk.StringVar(self)
        self.module_details=tk.StringVar(self)
        self.notes=tk.StringVar(self,value=(
            "Demo-Dateien bleiben ausschließlich in SpriteSuite/work/demo-sessions. "
            "Es gibt keine Spielinstallation, keinen nativen Hook und keine automatisch "
            "freigegebenen Spielaktionen."))
        self._build()
        self.module_list.selection_set(0)
        self._select_module()

    def _build(self):
        top=ttk.Frame(self,padding=(12,9))
        top.pack(fill="x")
        ttk.Label(top,text="Interaktiver Modul-Demo-Modus",
                  font=("Segoe UI",18,"bold")).pack(side="left")
        ttk.Label(top,text="Original → echte Bearbeitung → Prüfung → reproduzierbarer Export",
                  foreground="#91a7c0").pack(side="left",padx=18)
        ttk.Label(self,textvariable=self.notes,wraplength=1400,
                  foreground="#b1b9c3").pack(fill="x",padx=13,pady=(0,8))
        panes=ttk.Panedwindow(self,orient="horizontal")
        panes.pack(fill="both",expand=True,padx=9,pady=4)
        left=ttk.Frame(panes);main=ttk.Frame(panes)
        panes.add(left,weight=2);panes.add(main,weight=7)
        ttk.Label(left,text="Module einzeln wählen",
                  font=("Segoe UI",11,"bold")).pack(anchor="w",pady=(0,7))
        ttk.Label(left,text="Spezialwerkzeug suchen:").pack(anchor="w")
        search=ttk.Entry(left,textvariable=self.module_search)
        search.pack(fill="x",pady=(2,6))
        search.bind("<KeyRelease>",self._filter_modules)
        listing=ttk.Frame(left)
        listing.pack(fill="both",expand=True)
        self.module_list=tk.Listbox(listing,exportselection=False,height=16,
                          activestyle="dotbox",font=("Segoe UI",10))
        scroll=ttk.Scrollbar(listing,orient="vertical",command=self.module_list.yview)
        self.module_list.configure(yscrollcommand=scroll.set)
        self.module_list.pack(side="left",fill="both",expand=True)
        scroll.pack(side="right",fill="y")
        for item in MODULES:self.module_list.insert("end",item.title)
        self.module_list.bind("<<ListboxSelect>>",self._select_module)
        ttk.Separator(left).pack(fill="x",pady=8)
        ttk.Label(left,text="Optional: echte Originaldatei",font=("Segoe UI",10,"bold")
                  ).pack(anchor="w")
        ttk.Label(left,textvariable=self.source_display,
                  wraplength=260,foreground="#97a9bb").pack(anchor="w",pady=4)
        self.pick_button=ttk.Button(left,text="Original-XAML / WebM wählen …",
                                    command=self.choose_original)
        self.pick_button.pack(fill="x",pady=3)
        ttk.Label(left,text="Ohne Auswahl nutzen Noesis-Module eine eigene "
                  "mitgelieferte Beispiel-XAML. Der Pixelvergleich kann ein "
                  "eigenes PNG verwenden. Die Video-Demo benötigt ein echtes WebM.",
                  wraplength=265).pack(fill="x",pady=9)
        self.begin=ttk.Button(left,text="Neuen Demolauf starten",command=self.start)
        self.begin.pack(fill="x",pady=(11,4))
        self.all_button=ttk.Button(left,text="Alle Schritte dieses Moduls ausführen",
                                   command=self.run_all)
        self.all_button.pack(fill="x",pady=4)
        self.folder_button=ttk.Button(left,text="Ergebnisordner anzeigen",
                                      command=self.open_folder)
        self.folder_button.pack(fill="x",pady=4)
        self.practice_button=ttk.Button(left,text="Ergebnis im echten Editor öffnen",
                                        command=self.open_editor)
        self.practice_button.pack(fill="x",pady=4)
        self.verify_button=ttk.Button(left,text="Gespeicherte Belege erneut prüfen",
                                      command=self.verify_outputs)
        self.verify_button.pack(fill="x",pady=4)

        ttk.Label(main,textvariable=self.module_details,
                  font=("Segoe UI",11,"bold"),wraplength=1000).pack(
                  fill="x",padx=9,pady=6)
        steps_box=ttk.LabelFrame(main,text="Durch den Ablauf führen",padding=9)
        steps_box.pack(fill="x",padx=5,pady=6)
        self.steps=ttk.Treeview(steps_box,columns=("status",),show="tree headings",
                                height=5,selectmode="browse")
        self.steps.heading("#0",text="Schritt / echte Funktion")
        self.steps.heading("status",text="Stand")
        self.steps.column("#0",width=650)
        self.steps.column("status",width=135,stretch=False)
        self.steps.pack(fill="x")
        self.steps.bind("<<TreeviewSelect>>",self._show_selected_step)
        ttk.Label(steps_box,textvariable=self.step_heading,
                  font=("Segoe UI",11,"bold")).pack(fill="x",pady=(8,3))
        self.instructions=tk.Text(steps_box,height=4,wrap="word",
                                 font=("Segoe UI",10),background="#263341",
                                 foreground="#e2e7ef",borderwidth=0,
                                 padx=8,pady=5)
        self.instructions.pack(fill="x")
        self.instructions.configure(state="disabled")
        buttons=ttk.Frame(steps_box)
        buttons.pack(fill="x",pady=(9,0))
        self.next_button=ttk.Button(buttons,
          text="Ausgewählten nächsten Schritt wirklich ausführen",
          command=self.execute)
        self.next_button.pack(side="left")
        ttk.Label(buttons,textvariable=self.progress,wraplength=420).pack(
           side="right",padx=5)

        outputs=ttk.LabelFrame(main,text="Tatsächliche Ausgabedateien mit SHA-256",padding=8)
        outputs.pack(fill="both",expand=True,padx=5,pady=5)
        self.output_tree=ttk.Treeview(outputs,columns=("size","sha"),show="tree headings",
                                      height=5,selectmode="browse")
        self.output_tree.heading("#0",text="Datei aus dem gerade ausgeführten Schritt")
        self.output_tree.heading("size",text="Bytes")
        self.output_tree.heading("sha",text="SHA-256")
        self.output_tree.column("#0",width=480)
        self.output_tree.column("size",width=80,stretch=False)
        self.output_tree.column("sha",width=260)
        self.output_tree.pack(fill="x",expand=False)
        self.output_tree.bind("<<TreeviewSelect>>",self._output_selected)
        self._file_map={}
        preview_tabs=ttk.Notebook(outputs)
        preview_tabs.pack(fill="both",expand=True,pady=(6,0))
        text_tab=ttk.Frame(preview_tabs);image_tab=ttk.Frame(preview_tabs)
        preview_tabs.add(text_tab,text="Originalcode / echte Dateiinhalte")
        preview_tabs.add(image_tab,text="Bildvorschau")
        self.code=tk.Text(text_tab,wrap="none",font=("Consolas",10),
                          background="#172333",foreground="#e2edfb",
                          state="disabled")
        self.code.pack(fill="both",expand=True)
        self.image_canvas=tk.Canvas(image_tab,background="#162233",
                                    highlightthickness=0,height=190)
        self.image_canvas.pack(fill="both",expand=True)
        self.preview_tabs=preview_tabs
        bottom=ttk.Frame(self)
        bottom.pack(fill="x",padx=13,pady=7)
        ttk.Label(bottom,text="Nur nachweislich ausgeführte Operationen erhalten einen Abschlussvermerk.",
                  foreground="#a1acb9").pack(side="left")
        ttk.Button(bottom,text="Fenster schließen",command=self.destroy).pack(side="right")

    def _put_text(self,content:str):
        self.code.configure(state="normal")
        self.code.delete("1.0","end")
        self.code.insert("1.0",content[:85000])
        self.code.configure(state="disabled")
        self.code.see("1.0")

    def _instructions(self,content:str):
        self.instructions.configure(state="normal")
        self.instructions.delete("1.0","end")
        self.instructions.insert("1.0",content)
        self.instructions.configure(state="disabled")

    def _module(self):
        return MODULE_BY_KEY[self.active_key]

    def _run(self):
        return self.runs.get(self.active_key)

    def _filter_modules(self,_event=None):
        term=self.module_search.get().strip().casefold()
        previous=self.active_key
        self._visible_modules=[m for m in MODULES if term in
            (m.title+" "+m.summary+" "+m.key).casefold()]
        self.module_list.delete(0,"end")
        for module in self._visible_modules:
            self.module_list.insert("end",module.title)
        if self._visible_modules:
            index=next((i for i,m in enumerate(self._visible_modules)
                        if m.key==previous),0)
            self.module_list.selection_set(index)
            self.module_list.see(index)
            self._select_module()
        else:
            self.progress.set("Keine passende Demo. Suchbegriff ändern.")

    def _select_module(self,_event=None):
        choice=self.module_list.curselection()
        if not choice:return
        module=self._visible_modules[choice[0]]
        self.active_key=module.key
        self.module_details.set(module.title+" — "+module.summary)
        original=self.source_paths.get(module.key)
        self.source_display.set(str(original) if original else (
            "Für Video benötigt" if module.input_type=="video"
            else "Installiertes SHCDE-Spielverzeichnis nur lesend wählen" if module.input_type=="game_dir"
            else "Eigenes PNG oder eingebaute Beispielaufnahme" if module.input_type=="png"
            else "Integrierte Originalcode-/XAML-Beispielquelle"))
        self.pick_button.configure(state=("normal" if module.input_type else "disabled"))
        self._refresh_steps()
        self._refresh_outputs()
        self._update_buttons()

    def _update_buttons(self):
        run=self._run()
        enabled=not self._busy
        self.next_button.configure(state="normal" if enabled and run and not run.complete else "disabled")
        self.begin.configure(state="normal" if enabled else "disabled")
        self.all_button.configure(state="normal" if enabled else "disabled")
        self.folder_button.configure(state="normal" if enabled and run else "disabled")
        can_edit=self._can_open_editor(run)
        self.practice_button.configure(state="normal" if enabled and can_edit else "disabled")
        self.verify_button.configure(state="normal" if enabled and run and run.receipts else "disabled")

    def _refresh_steps(self):
        module=self._module()
        run=self._run()
        current=run.next_step if run else 0
        self.steps.delete(*self.steps.get_children())
        for i,step in enumerate(module.steps):
            state="Ausgeführt ✓" if i<current else "Als Nächstes" if i==current else "Offen"
            self.steps.insert("","end",iid="step"+str(i),
                              text=f"{i+1}. {step.title}",values=(state,))
        if run and run.complete:
            self.progress.set(f"{len(module.steps)} von {len(module.steps)} Schritten abgeschlossen · echte Ergebnisse")
            index=len(module.steps)-1
        else:
            self.progress.set(f"{current} von {len(module.steps)} Schritten ausgeführt")
            index=current
        iid="step"+str(index)
        self.steps.selection_set(iid)
        self.steps.see(iid)
        self._show_selected_step()

    def _show_selected_step(self,_event=None):
        selected=self.steps.selection()
        if not selected:return
        i=int(selected[0].removeprefix("step"))
        step=self._module().steps[i]
        self.step_heading.set(step.title)
        text=step.explain+"\n\nTatsächlich verwendete Funktionen: "+step.function
        if self._module().key in ("campaign","season"):
            text+="\nHinweis: C# wird offline kompiliert; kein nativer Spielhandler."
        if self._module().key=="video":
            text+="\nHinweis: Originalvideo-Replacement, kein Neucodieren oder Abspielen."
        self._instructions(text)
        # Selecting a completed step shows its actual historical output,
        # not the files from whichever step happened to execute last.
        self._refresh_outputs(step_index=i)

    def choose_original(self):
        module=self._module()
        if not module.input_type:return
        if module.input_type=="game_dir":
            file=filedialog.askdirectory(parent=self,
                title="SHCDE-Spielordner (BepInEx / Daten) nur lesend wählen")
        else:
            file=filedialog.askopenfilename(
                parent=self,title="Originaldatei ausschließlich lesend wählen",
                filetypes=([("Noesis/XAML","*.xaml")] if module.input_type=="xaml"
                            else [("Spiel-Screenshot (PNG)","*.png")]
                            if module.input_type=="png" else
                            [("WebM Video","*.webm")]))
        if not file:return
        path=Path(file)
        self.source_paths[module.key]=path
        self.source_display.set(str(path))
        self.progress.set("Originaldatei ausgewählt: bei neuem Demolauf als Arbeitskopie geladen.")

    def start(self):
        if self._busy:return None
        try:
            module=self._module()
            run=DemoSession.start(module.key,source=self.source_paths.get(module.key))
            self.runs[module.key]=run
            self._refresh_steps()
            self._refresh_outputs()
            self._update_buttons()
            self.progress.set("Neuer isolierter Demolauf vorbereitet. Schritt 1 ausführen.")
            return run
        except (OSError,ValueError,RuntimeError) as exc:
            messagebox.showerror("Demo konnte nicht gestartet werden",str(exc),parent=self)
            return None

    def execute(self):
        if self._busy:return None
        run=self._run()
        if run is None:
            run=self.start()
        if run is None or run.complete:return None
        self._busy=True
        self._update_buttons()
        try:
            self.progress.set("Führe produktive Operation wirklich aus …")
            self.update_idletasks()
            result=run.execute_next()
            self._refresh_steps()
            self._refresh_outputs()
            self.progress.set(f"✓ {run.next_step}/{len(run.module.steps)}: {result['message']}")
            return result
        except Exception as exc:
            self.progress.set("Demo-Fehler: "+str(exc))
            messagebox.showerror("Schritt nicht bestanden – keine Erfolgsanzeige",
                                 str(exc),parent=self)
            return None
        finally:
            self._busy=False
            self._update_buttons()

    def run_all(self):
        run=self._run() or self.start()
        if run is None:return
        while not run.complete:
            if self.execute() is None:break
        if run.complete:
            self.progress.set(
                f"Alle {len(run.module.steps)} Schritte vollständig ausgeführt. "
                "ZIP/Dateien und SHA-Belege liegen im privaten Demo-Projekt.")

    def _refresh_outputs(self,step_index:int|None=None):
        self.output_tree.delete(*self.output_tree.get_children())
        self._file_map={}
        self._photos=[]
        self.image_canvas.delete("all")
        run=self._run()
        if run is None or not run.receipts:
            self._put_text("Noch keine Verarbeitung ausgeführt.\n"
                           "Schritte enthalten echte Imports, Dateiänderungen, "
                           "Neuladen, Validatoren und Paketbau.")
            return
        which=(len(run.receipts)-1 if step_index is None or
               step_index>=len(run.receipts) else step_index)
        record=run.receipts[which]
        history=which<len(run.receipts)-1
        paths=[]
        if record.get("source"):
            source=Path(record["source"])
            if source.is_file():paths.append(("Original / Quellcode",source))
        for i,item in enumerate(record["outputs"]):
            # A later edit may deliberately supersede this active path.
            # The saved step snapshot preserves the exact earlier bytes.
            original=Path(item["path"])
            saved=Path(item.get("snapshot",item["path"])) if history else original
            paths.append((f"Ergebnis {i+1}"+
                          (" · damaliger Stand" if history else ""),saved))
        for i,(title,path) in enumerate(paths):
            iid="file"+str(i)
            self._file_map[iid]=path
            self.output_tree.insert("","end",iid=iid,
              text=title+" · "+path.name,
              values=(path.stat().st_size,self._file_digest_for(path,record)))
        if paths:
            self.output_tree.selection_set("file"+str(len(paths)-1))
            self._output_selected()

    @staticmethod
    def _file_digest_for(path,record):
        for item in record["outputs"]:
            if Path(item["path"])==path:return item["sha256"]
        from suite_demo_engine import _sha
        return _sha(path)

    def _output_selected(self,_event=None):
        selected=self.output_tree.selection()
        if not selected or selected[0] not in self._file_map:return
        path=self._file_map[selected[0]]
        self.current_file.set(str(path))
        self._display_file(path)

    def _display_file(self,path:Path):
        suffix=path.suffix.lower()
        if suffix in {".png",".jpg",".jpeg",".webp"}:
            self.preview_tabs.select(1)
            try:
                with Image.open(path) as image:
                    pic=image.convert("RGBA")
                pic.thumbnail((800,300),Image.Resampling.LANCZOS)
                obj=ImageTk.PhotoImage(pic,master=self)
                self._photos=[obj]
                self.image_canvas.delete("all")
                self.image_canvas.create_image(16,14,image=obj,anchor="nw")
                self._put_text(f"Echte Bilddatei:\n{path}\nGröße: {image.width} × {image.height}\n"
                              "Dieses Bild wurde durch die Verarbeitung erzeugt oder geändert.")
            except (OSError,UnidentifiedImageError):
                self._put_text("Bild nicht lesbar: "+str(path))
            return
        self.preview_tabs.select(0)
        if suffix in {".zip",".exe",".dll",".webm"}:
            self._put_text("Echte Binärdatei:\n"+str(path)+"\n\n"
                          f"{path.stat().st_size:,} Bytes. "
                          "Inhalt wurde in der Modulprüfung getrennt verarbeitet.")
            return
        try:
            content=path.read_text("utf8")
        except (UnicodeError,OSError):
            content="[Datei nicht als UTF-8-Quelltext darstellbar]"
        if len(content)>80000:
            content=content[:80000]+"\n[Ansicht gekürzt; vollständige Datei liegt auf Datenträger.]"
        self._put_text(f"Datei: {path}\n\n"+content)

    @staticmethod
    def _can_open_editor(run):
        if not run or not run.receipts:return False
        if run.module.key in {"noesis","patch","pixels","package","layout","theme",
                              "campaign","season","native_menu"}:
            return True
        specialty={"stone","boar","historic_palette","team_mask","sandbox_scene",
                   "button_motif","native_tiles","bc7","extra_atlas"}
        if run.module.key not in specialty:return False
        relative=run.data.get("extra_asset")
        if relative and (run.project/relative).is_file():return True
        # The additional Noesis atlas becomes editable only after its real
        # PNG pages have been generated and copied to the mod project.
        return bool(list((run.project/"Override/Assets/GUI/Sprites").glob("*.png")))

    def open_editor(self):
        """Move from the verified exercise into the actual specialist editor."""
        run=self._run()
        if run is None or not run.receipts:return None
        try:
            key=run.module.key
            if key in {"noesis","patch"}:
                from suite_origins_visual_editor import OriginsVisualEditor
                from origins_visual_document import VisualXamlDocument
                source=run.data.get("xaml_source")
                if not source:raise ValueError("Zuerst die originale XAML vorbereiten")
                editor=OriginsVisualEditor(self,project=run.project,source=Path(source))
                revision=run.data.get("revision")
                if revision and Path(revision).is_dir():
                    editor.doc=VisualXamlDocument.reopen(Path(revision))
                    editor.title_var.set("Weiterbearbeitete Original-Revision: "+str(revision))
                    editor.refresh_tree()
            elif key in {"pixels","package","stone","boar","historic_palette",
                          "team_mask","sandbox_scene","button_motif","native_tiles",
                          "bc7","extra_atlas"}:
                from suite_hud_menu_editor import HudMenuPixelEditor
                if key=="pixels":
                    source=run.project/run.data["relative"]
                elif key=="package":
                    source=Path(run.data["plugin_image"])
                elif run.data.get("extra_asset"):
                    source=run.project/run.data["extra_asset"]
                else:
                    matching=sorted((run.project/"Override/Assets/GUI/Sprites").glob("*.png"))
                    if not matching:
                        raise ValueError("Mod-Atlas noch nicht vorbereitet; erst bis Schritt 3 ausführen")
                    source=matching[0]
                editor=HudMenuPixelEditor(self,source,project=run.project)
            elif key=="layout":
                from suite_hud_menu_layout_editor import HudMenuLayoutEditor
                editor=HudMenuLayoutEditor(self,project=run.project,
                     source_asset=run.data.get("relative"))
                if "scene_hash" in run.data:
                    from hud_menu_layout import load_scene,History
                    scene,digest=load_scene(run.project,run.data["scene"].name)
                    editor.history=History(scene)
                    editor._last_saved=editor.scene.as_json()
                    editor._save_hash=digest
                    editor.scene_name.set(scene.name)
                    editor._refresh_layers()
                    editor._check_export_status()
                    editor._schedule_draw()
            elif key=="theme":
                from suite_origins_theme_editor import OriginsThemeEditor
                editor=OriginsThemeEditor(self,project=run.project,
                     source=Path(run.data["theme_source"]))
            elif key in {"campaign","season","native_menu"}:
                from suite_origins_runtime_workshop import OriginsRuntimeWorkshop
                editor=OriginsRuntimeWorkshop(self,project=run.project)
                if key in {"campaign","native_menu"} and "campaign" in run.data:
                    plan=run.data["campaign"]
                    editor.name.set(plan["name"])
                    editor.title_var.set(plan["title"])
                    editor.missions={row["number"]:row for row in plan["missions"]}
                    editor._render_missions()
                    if "campaign_dir" in run.data:
                        editor.saved_campaign_slug=plan["name"]
                if key=="season" and run.data.get("season_folder"):
                    editor.pack_id.set("demo-winter")
                    editor.season_maps.set("Demo 1.map")
                    editor.group.set("tree_pine")
                    editor.atlas_path.set(run.data["season_folder"])
                    editor.season_groups={"tree_pine":Path(run.data["season_folder"])}
                    editor.groups.insert("","end",values=("tree_pine",run.data["season_folder"]))
                    if "season_dir" in run.data:
                        editor.saved_season_pack="demo-winter"
            else:
                self.progress.set("Dieses Modul nutzt den Dateiexport statt eines eigenen GUI-Editors.")
                return None
            editor.focus_set()
            self.progress.set("Echter Fach-Editor geöffnet. Änderungen erfolgen weiter "
                              "im privaten Demo-Projekt.")
            return editor
        except (OSError,ValueError,KeyError,RuntimeError) as error:
            messagebox.showerror("Fach-Editor konnte nicht geöffnet werden",
                                 str(error),parent=self)
            return None

    def _under_workspace(self,path:Path):
        import hud_menu_workspace as work
        return path.resolve().is_relative_to(work.WORK.resolve())

    def open_folder(self):
        run=self._run()
        if run is None:return
        try:
            if not self._under_workspace(run.root):
                raise ValueError("Ordner liegt außerhalb des Demo-Arbeitsbereichs")
            if os.name=="nt":os.startfile(str(run.root))
            else:self.progress.set("Demo-Ordner: "+str(run.root))
        except (OSError,ValueError) as exc:
            messagebox.showerror("Ordner",str(exc),parent=self)

    def verify_outputs(self):
        run=self._run()
        if run is None:return False
        report=run.verify_receipts()
        if not report["valid"]:
            self.progress.set(f"{len(report['problems'])} Änderungen gefunden. "
                "Dies sind Hinweise, keine Sperren auf eigene Bearbeitung.")
            return False
        self.progress.set(
            f"{report['current_files']} aktuelle Ausgaben und "
            f"{report['historical_snapshots']} originale Zwischenstände erneut "
            "auf Datenträger geprüft.")
        return True


def open_demo_mode(parent):
    """Reusable entry point for the main modern shell and specialist workshop."""
    window=DemoMode(parent)
    window.focus_set()
    return window

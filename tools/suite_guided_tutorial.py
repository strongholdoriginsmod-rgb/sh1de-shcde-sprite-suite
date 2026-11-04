"""Non-destructive contextual tutorial for SpriteSuite.

A lesson may navigate and highlight a real widget. It NEVER invokes edit,
build, install, source-import or game operations without an explicit click.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import ttk


@dataclass(frozen=True)
class Lesson:
    title_de: str
    title_en: str
    body_de: str
    body_en: str
    area: str = "workflow"
    target: str = ""


@dataclass(frozen=True)
class Track:
    key: str
    title_de: str
    title_en: str
    steps: tuple[Lesson, ...]


TRACKS = (
    Track("quickstart", "Projekt bis Mod-ZIP", "Project to mod ZIP", (
        Lesson("Projekt öffnen", "Open project",
               "Hier liegt der gemeinsame Arbeitsbereich. Wähle ein vorhandenes Projekt oder lege ein neues an. Ein Projekt-ZIP ist eine bearbeitbare Sicherung – kein installierbares Mod-Paket.",
               "This is your shared workspace. Choose or create a project. A project ZIP is an editable backup, not an installable mod.", target="sidebar-start"),
        Lesson("Eigene Bilder übernehmen", "Import your images",
               "Wähle »Dateien hinzufügen«. Es wird eine private Projektkopie angelegt; Originaldateien werden nicht überschrieben. Die Kategorie legt den Exportordner fest.",
               "Choose Add files. SpriteSuite creates project copies; originals remain unchanged. The category determines the export location.", target="source"),
        Lesson("Auswahl und Vorschau", "Select and preview",
               "Wähle links eine Datei und betrachte sie rechts. Ist noch keine Datei vorhanden, beginnt die importierbare Leervorschau.",
               "Select a file on the left and inspect the preview. If the project is empty, use Import first file.", target="preview"),
        Lesson("Bearbeiten", "Edit",
               "»Datei bearbeiten« öffnet den passenden Editor. Erst nach dem Import ist der Knopf aktiv. Änderungen vor einem Projektwechsel unbedingt speichern.",
               "Edit selected file opens the appropriate editor and is enabled after import. Save changes before switching projects.", target="edit"),
        Lesson("Layout gestalten", "Arrange layout",
               "Mit »Layout gestalten« öffnest du einen echten Ebenen-Designer für Position, Größe, Rotation und Komposition.",
               "Arrange layout opens the real layered editor for positions, sizes, rotation and composites.", target="layout"),
        Lesson("Änderungen prüfen", "Validate changes",
               "Prüfe die Projektdateien. Die statische Prüfung ersetzt KEINEN Ingame- oder Noesis-ABI-Test und verändert keine Spielinstallation.",
               "Validate project files. Static validation does NOT replace in-game/Noesis ABI testing and never installs into the game.", target="validate"),
        Lesson("Geprüftes ZIP ausgeben", "Export verified ZIP",
               "Nur das Ergebnis von »Geprüftes Mod-ZIP bauen« ist ein verifizierter statischer Export. Die letzte Prüfsumme erscheint unterhalb der Aktionen.",
               "Build verified mod ZIP produces a checked static export; its checksum appears underneath. This does not install mods.", target="export"),
        Lesson("Bearbeitbares Projekt sichern", "Back up editable project",
               "Mit »Projekt sichern (ZIP)« behältst du Quellrevisionen und editierbare Projektdaten. Diese Sicherung ist getrennt vom Mod-ZIP.",
               "Back up project (ZIP) retains sources and editable revisions separately from the mod ZIP.", target="backup"),
    )),
    Track("layout", "Pixel und Ebenen", "Pixels and layers", (
        Lesson("Pixelwerkstatt finden", "Find pixel tools",
               "Der Bereich »Pixel & Layout« enthält Bildwerkzeuge. Der Projekt-Editor bleibt mit der Hauptwerkbank verbunden.",
               "Pixels & layout contains image tools linked to the same project.",area="menus",target="sidebar-menus"),
        Lesson("Visuellen Designer öffnen", "Open visual designer",
               "Kehre zur Projekt-Werkbank zurück und wähle »Layout gestalten«. Der Designer öffnet ein separates Fenster.",
               "Return to Project & files and select Arrange layout to open the separate designer.",target="layout"),
        Lesson("Ebenen sicher bearbeiten", "Edit layers safely",
               "Nutze Ebenenliste, Anfasser und die genauen Positionsfelder. Strg+S speichert das editierbare Layout; erst danach einen Export bauen.",
               "Use the layer list, handles and numeric positions. Ctrl+S saves the editable layout before export.",target="layout"),
        Lesson("Ergebnis prüfen", "Validate composition",
               "Prüfe das exportierte PNG und den Dateistand vor der Paketfreigabe. Eine Layoutvorschau belegt keine native Spielanzeige.",
               "Verify the PNG and file state before packaging. A layout preview does not prove native game rendering.",target="validate"),
    )),
    Track("preview", "Spielvorschau", "Game preview", (
        Lesson("Spielvorschau finden", "Open game preview",
               "Die Spielvorschau ist ein eigenständiges, eingebettetes Qt-Studio. Sie übernimmt keine unbestätigten Spielversionen.",
               "Game preview is a separate embedded Qt studio; unknown game versions are not automatically approved.",area="sandbox",target="sidebar-sandbox"),
        Lesson("Karte laden", "Load a map",
               "Wähle »Karte öffnen«. Ohne konfigurierte Karte erscheint ein Hinweis statt einer vorgetäuschten Szene.",
               "Choose Open map. Without a configured map, SpriteSuite shows an empty-state hint rather than a fake scene.",area="sandbox",target="sandbox-open"),
        Lesson("Spielkonfiguration prüfen", "Check game setup",
               "Fehlen Karten, öffne die Spieleinrichtung. Die echte Unity-/Noesis-/Script-Extender-Kompatibilität muss separat nachgewiesen werden.",
               "If no maps are found, configure the game directory. Native Unity/Noesis/Script Extender compatibility still requires separate evidence.",area="sandbox",target="sandbox-setup"),
    )),
    Track("demo", "Demo-Module", "Demo modules", (
        Lesson("Werkzeuge einblenden", "Reveal tools",
               "Öffne »Werkzeuge«, dort liegen die weiterführenden Funktionen einschließlich der 26 interaktiven Demo-Module.",
               "Expand Tools to access specialist features and the 26 interactive demo modules.",target="more-toggle"),
        Lesson("Demo bewusst starten", "Start demo intentionally",
               "Öffne »Interaktiver Demo-Modus«. Wähle ein Modul und einen Schritt. Nur dessen Ausführen-Schaltflächen verarbeiten Daten.",
               "Open Interactive demo mode, select a module and step. Only its explicit Execute controls process data.",target="demo-button"),
        Lesson("Nachweise ansehen", "Inspect evidence",
               "Der Demolauf erstellt eigene Beispieldateien und SHA-256-Belege im Demo-Arbeitsbereich. Private Spielquellen sind optional und werden nie automatisch installiert.",
               "Demo sessions use separate samples and SHA-256 receipts. Private game sources are optional and never automatically installed.",target="demo-button"),
    )),
    Track("compat", "Kompatibilität und Sicherheit", "Compatibility and safety", (
        Lesson("Umgebung diagnostizieren", "Diagnose the environment",
               "»Kompatibilität prüfen« meldet Python, Windows, Tcl/Tk, Qt, Laufzeitabhängigkeiten und die read-only Spielgrenzen. Keine automatische Installation.",
               "Run Compatibility check to inspect Python, Windows, Tcl/Tk, Qt, dependencies and read-only game boundaries. Nothing is installed.",target="compat-button"),
        Lesson("Spielstand nicht erraten", "Never guess game support",
               "Die Steam-Diagnose ermittelt lokale Builddaten lesend. Ein aktueller Build bedeutet NICHT, dass unbekannte ABI- oder Mappingänderungen sicher sind.",
               "Steam version detection is read-only. A newer build does NOT prove native ABI or sprite mappings are compatible.",target="validate"),
        Lesson("Portable weitergeben", "Distribute a portable package",
               "Nutze ein vollständig entpacktes Windows-x64-ZIP. Wähle Test/Export nur nach einer erfolgreichen Dateiprüfung, sichere dein Projekt zusätzlich.",
               "Fully extract the Windows x64 ZIP. Validate files before exporting, and back up the editable project separately.",target="export"),
        Lesson("Handbuch lesen", "Read illustrated manual",
               "»PDF-Handbuch« enthält reale Programmabbildungen mit Schrittfolgen und Grenzen. Für alte Spezialwerkzeuge gibt es weiterhin die erweiterte Bereichsauswahl.",
               "The illustrated PDF contains real screenshots, guided tasks and limitations. Legacy tools remain available in More.",target="pdf-button"),
    )),
)


BY_KEY = {t.key:t for t in TRACKS}


def progress_path() -> Path:
    """Use per-user state, not any game or Git directory."""
    if os.name=="nt" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"])/"SpriteSuite"/"guide-progress-v1.json"
    return Path.home()/".spritesuite"/"guide-progress-v1.json"


class ProgressStore:
    def __init__(self,path:Path|None=None):
        self.path=Path(path) if path else progress_path()

    def load(self) -> dict[str,int]:
        try:
            if self.path.is_symlink() or not self.path.is_file() or self.path.stat().st_size>16384:
                return {}
            data=json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("schema")!="sprite-suite.guide-progress.v1":return {}
            saved=data.get("steps",{})
            return {key:min(max(0,int(saved[key])),len(track.steps)-1)
                    for key,track in BY_KEY.items()
                    if key in saved and type(saved[key]) is int}
        except (OSError,ValueError,TypeError,KeyError):
            return {}

    def save(self,progress:dict[str,int]) -> bool:
        temp=None
        try:
            if self.path.is_symlink() or self.path.parent.is_symlink():return False
            self.path.parent.mkdir(parents=True,exist_ok=True)
            data={"schema":"sprite-suite.guide-progress.v1",
                  "steps":{k:min(max(0,int(v)),len(BY_KEY[k].steps)-1)
                           for k,v in progress.items() if k in BY_KEY}}
            # Atomic write prevents corrupted progress on power loss.
            import tempfile
            with tempfile.NamedTemporaryFile(mode="w",encoding="utf-8",
                     prefix=".guide-",suffix=".tmp",dir=self.path.parent,
                     delete=False) as stream:
                temp=Path(stream.name)
                json.dump(data,stream,ensure_ascii=False,indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp,self.path)
            return True
        except (OSError,ValueError):
            return False
        finally:
            if temp is not None:
                try:temp.unlink(missing_ok=True)
                except OSError:pass


class GuidedTutorial(tk.Toplevel):
    """Context-aware, non-modal, reversible highlights and manual progression."""

    def __init__(self,app,*,track="quickstart",store=None):
        super().__init__(app)
        self.app=app
        self.store=store or ProgressStore()
        self.progress=self.store.load()
        self.track_key=track if track in BY_KEY else "quickstart"
        self.index=min(self.progress.get(self.track_key,0),len(BY_KEY[self.track_key].steps)-1)
        self._focus_widget=None
        self._focus_style=None
        self._expanded_by_guide=False
        self._closed=False
        self.title("SpriteSuite - Gefuehrte Anleitung")
        self.geometry("525x620")
        self.minsize(425,485)
        self._place_near_app()
        self.protocol("WM_DELETE_WINDOW",self.close)
        style=ttk.Style(self)
        style.configure("Tutorial.Focus.TButton",background="#e5b968",
                        foreground="#111820",padding=(10,8),
                        font=("Segoe UI",10,"bold"))
        style.map("Tutorial.Focus.TButton",background=[("active","#ffd68d")])
        style.configure("Tutorial.Focus.TLabel",background="#e5b968",
                        foreground="#111820",padding=5)
        self.title_var=tk.StringVar(master=self)
        self.step_var=tk.StringVar(master=self)
        self.body_var=tk.StringVar(master=self)
        self.tip_var=tk.StringVar(master=self)
        self.note_var=tk.StringVar(master=self)
        self.track_label=tk.StringVar(master=self)
        self.progress_value=tk.DoubleVar(master=self,value=0)
        self._make_widgets()
        self._update_labels_and_step()

    def _place_near_app(self):
        self.app.update_idletasks()
        rootx=self.app.winfo_rootx()
        rooty=self.app.winfo_rooty()
        right=rootx+self.app.winfo_width()
        avail=self.app.winfo_screenwidth()
        x=right+12 if right+540<avail else max(20,avail-550)
        y=max(30,rooty+40)
        self.geometry(f"+{x}+{y}")

    def _en(self):return self.app.language.get().upper()=="EN"
    def _label(self,de,en):return en if self._en() else de

    def _make_widgets(self):
        base=ttk.Frame(self,padding=17)
        base.pack(fill="both",expand=True)
        ttk.Label(base,textvariable=self.title_var,
                  font=("Segoe UI",17,"bold")).pack(anchor="w")
        ttk.Label(base,textvariable=self.note_var,wraplength=475,
                  justify="left").pack(anchor="w",pady=(5,12))
        bar=ttk.Frame(base)
        bar.pack(fill="x",pady=(0,8))
        ttk.Label(bar,textvariable=self.track_label).pack(side="left")
        self.track_choice=tk.StringVar(master=self)
        self.track_picker=ttk.Combobox(bar,textvariable=self.track_choice,
                                      state="readonly",width=30)
        self.track_picker.pack(side="right",fill="x",expand=True,padx=(9,0))
        self.track_picker.bind("<<ComboboxSelected>>",self._choose_track)
        ttk.Label(base,textvariable=self.step_var,
                  font=("Segoe UI",11,"bold")).pack(fill="x",pady=(8,6))
        self.bar=ttk.Progressbar(base,orient="horizontal",maximum=100,
                                 variable=self.progress_value)
        self.bar.pack(fill="x",pady=(0,11))
        ttk.Label(base,textvariable=self.body_var,wraplength=468,
                  justify="left",font=("Segoe UI",11)).pack(
                      fill="x",pady=(5,12),anchor="nw")
        self.tip=ttk.Label(base,textvariable=self.tip_var,wraplength=465,
                           justify="left",foreground="#9eabbe")
        self.tip.pack(fill="x",pady=(0,14))
        self.focus_button=ttk.Button(base,command=self.focus_target)
        self.focus_button.pack(fill="x",pady=(2,7))
        nav=ttk.Frame(base)
        nav.pack(fill="x",pady=(2,8))
        self.back_button=ttk.Button(nav,command=self.previous)
        self.back_button.pack(side="left",fill="x",expand=True,padx=(0,4))
        self.next_button=ttk.Button(nav,command=self.next)
        self.next_button.pack(side="left",fill="x",expand=True,padx=(4,0))
        ttk.Separator(base).pack(fill="x",pady=8)
        shortcuts=ttk.Frame(base)
        shortcuts.pack(fill="x",pady=(6,0))
        self.pdf_button=ttk.Button(shortcuts,command=self.app.open_pdf_manual)
        self.pdf_button.pack(side="left",padx=(0,4))
        self.demo_button=ttk.Button(shortcuts,
                command=self.app.modern_shell.open_demo)
        self.demo_button.pack(side="left",padx=(0,4))
        self.compat_button=ttk.Button(shortcuts,
                command=self.app.run_compatibility_report)
        self.compat_button.pack(side="left")
        self.bind("<Escape>",lambda _e:self.close())
        self.bind("<Alt-Left>",lambda _e:self.previous())
        self.bind("<Alt-Right>",lambda _e:self.next())

    def _resolve_target(self,key):
        shell=self.app.modern_shell
        wf=self.app.workflow_tab
        direct={
            "sidebar-start":lambda:shell.buttons["start"],
            "sidebar-menus":lambda:shell.buttons["menus"],
            "sidebar-sandbox":lambda:shell.buttons["sandbox"],
            "source":lambda:wf.source_button,
            "preview":lambda:wf.preview,
            "edit":lambda:wf.edit_button,
            "layout":lambda:wf.layout_button,
            "validate":lambda:wf.check_button,
            "export":lambda:wf.export_button,
            "backup":lambda:getattr(wf,"project_backup_button",None),
            "sandbox-open":lambda:self.app.sandbox_tab.quick_buttons.get("Karte öffnen"),
            "sandbox-setup":lambda:getattr(self.app.sandbox_tab,"setup_map_button",None),
            "more-toggle":lambda:shell.more_toggle,
            "demo-button":lambda:shell.demo_button,
            "pdf-button":lambda:self.pdf_button,
            "compat-button":lambda:self.compat_button,
        }
        cb=direct.get(key)
        try:return cb() if cb else None
        except (AttributeError,tk.TclError):return None

    def _clear_focus(self):
        widget,self._focus_widget=self._focus_widget,None
        if widget is None:return
        try:
            if widget.winfo_exists() and self._focus_style is not None:
                widget.configure(style=self._focus_style)
        except (tk.TclError,AttributeError):
            pass
        self._focus_style=None

    def _track(self):return BY_KEY[self.track_key]
    def _step(self):return self._track().steps[self.index]

    def _update_labels_and_step(self):
        en=self._en()
        self.title(self._label("SpriteSuite - Geführte Anleitung",
                               "SpriteSuite - Guided tutorial"))
        self.title_var.set(self._label("Geführte Anleitung","Guided tutorial"))
        self.track_label.set(self._label("Lernpfad:","Learning path:"))
        self.note_var.set(self._label(
            "Du navigierst durch die echte Oberfläche. Die Anleitung führt keine "
            "Dateiänderungen, Spielinstallationen oder Exporte selbst aus.",
            "You navigate the real application. The tutorial never runs file "
            "changes, installs, or exports on your behalf."))
        self._choices={self._label(x.title_de,x.title_en):x.key for x in TRACKS}
        self.track_picker.configure(values=tuple(self._choices))
        self.track_choice.set(self._label(self._track().title_de,self._track().title_en))
        step=self._step()
        self.step_var.set(self._label(
            f"Schritt {self.index+1} von {len(self._track().steps)} - {step.title_de}",
            f"Step {self.index+1} of {len(self._track().steps)} - {step.title_en}"))
        self.body_var.set(self._label(step.body_de,step.body_en))
        self.progress_value.set(100*(self.index+1)/len(self._track().steps))
        self.tip_var.set(self._label(
            "Gelb markiert: das aktuelle Bedienelement. Du kannst mit der Maus "
            "weiterarbeiten; Zurück/Weiter verändert keine Projektdateien.",
            "Yellow highlight: the current control. You can keep using the "
            "mouse; Back/Next never modifies project files."))
        self.focus_button.configure(text=self._label("Bedienelement zeigen",
                                                     "Show control"))
        self.back_button.configure(text=self._label("← Zurück","← Back"))
        self.next_button.configure(text=self._label(
            "Abschließen ✓" if self.index==len(self._track().steps)-1 else "Weiter →",
            "Finish ✓" if self.index==len(self._track().steps)-1 else "Next →"))
        self.back_button.configure(state=("disabled" if self.index==0 else "normal"))
        self.pdf_button.configure(text=self._label("PDF-Handbuch","PDF manual"))
        self.demo_button.configure(text=self._label("Demo","Demo"))
        self.compat_button.configure(text=self._label("Kompatibilität","Compatibility"))
        self.focus_target()

    def refresh_language(self):
        if not self._closed and self.winfo_exists():
            self._update_labels_and_step()

    def _choose_track(self,_event=None):
        key=self._choices.get(self.track_choice.get())
        if key in BY_KEY:
            self.track_key=key
            self.index=self.progress.get(key,0)
            self._update_labels_and_step()

    def select_track(self,key):
        if key in BY_KEY:
            self.track_key=key
            self.index=self.progress.get(key,0)
            self._update_labels_and_step()

    def focus_target(self):
        """Navigate and paint a reversible focus, never invoke target.command."""
        if self._closed:return None
        self._clear_focus()
        step=self._step()
        if step.area=="menus":
            tab=self.app.hud_menu_tab
        elif step.area=="sandbox":
            tab=self.app.sandbox_tab
        else:
            tab=self.app.workflow_tab
        if self.app.notebook.select()!=str(tab):
            self.app.open_tab(tab)
        if step.target=="demo-button" and not self.app.modern_shell.more_expanded:
            self.app.modern_shell._toggle_extra()
            self._expanded_by_guide=True
        widget=self._resolve_target(step.target)
        if widget is None:return None
        try:
            self.app.update_idletasks()
            if not widget.winfo_ismapped():
                return widget
            self._focus_style=widget.cget("style")
            if isinstance(widget,ttk.Button):
                widget.configure(style="Tutorial.Focus.TButton")
            elif isinstance(widget,ttk.Label):
                widget.configure(style="Tutorial.Focus.TLabel")
            else:
                self._focus_style=None
            self._focus_widget=widget
            # Focus is visual/keyboard only. Do NOT call invoke().
            if widget is not self.focus_button:
                widget.focus_set()
        except (tk.TclError,AttributeError):
            self._focus_widget=None
        return widget

    def _move(self,direction):
        new=self.index+direction
        if new<0:return
        if new>=len(self._track().steps):
            self.progress[self.track_key]=self.index
            self.store.save(self.progress)
            self.close()
            return
        self.index=new
        self.progress[self.track_key]=new
        self.store.save(self.progress)
        self._update_labels_and_step()

    def previous(self):self._move(-1)
    def next(self):self._move(1)

    def close(self):
        if self._closed:return
        self._closed=True
        self._clear_focus()
        self.progress[self.track_key]=self.index
        self.store.save(self.progress)
        if self._expanded_by_guide and self.app.modern_shell.more_expanded:
            self.app.modern_shell._toggle_extra()
        if getattr(self.app,"_guided_tutorial",None) is self:
            self.app._guided_tutorial=None
        self.destroy()


def open_guided_tutorial(app,*,track=None,store=None):
    existing=getattr(app,"_guided_tutorial",None)
    if existing is not None:
        try:
            if existing.winfo_exists():
                if track:existing.select_track(track)
                existing.lift()
                return existing
        except tk.TclError:pass
    target=track or ("preview" if app.notebook.select()==str(app.sandbox_tab)
              else "layout" if app.notebook.select()==str(app.hud_menu_tab)
              else "quickstart")
    if target=="preview":target="preview"
    guide=GuidedTutorial(app,track=target,store=store)
    app._guided_tutorial=guide
    return guide

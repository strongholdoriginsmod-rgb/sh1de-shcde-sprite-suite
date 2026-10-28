"""Select an installed Noesis XAML screen and build a static game-bound mod.

No game files are changed. Only an independently SHA-pinned, uniquely named
Grid can be used as an XAML Add target. No invented UI event handlers.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from hud_menu_noesis_integration import (
    ALL_ALIGNMENTS, GridTarget, build_bound_mod, discover_grid_targets,
    generate_patch, installed_gui,
)
from hud_menu_workspace import WorkshopError, workspace
from hud_menu_layout import audit_export


class NoesisBindingDialog(tk.Toplevel):
    def __init__(self, parent, editor):
        super().__init__(parent)
        self.editor=editor
        self.project=workspace(editor.project)
        self.source=tk.StringVar(self)
        self.target_choice=tk.StringVar(self)
        self.anchor=tk.StringVar(self,value="Oben links")
        self.guid=tk.StringVar(self,value="spritehudmenu")
        self.name=tk.StringVar(self,value="SpriteSuite HUD & Menus")
        self.include_xaml=tk.BooleanVar(self,value=False)
        self.status=tk.StringVar(self,value="Installiertes Spiel wählen und echte Noesis-Container einlesen.")
        self.targets:dict[str,GridTarget]={}
        self._selected_path=None
        self._built_result=None
        self.title("HUD & Menü · im Spiel verankern (Noesis-XAML)")
        self.geometry("960x695")
        self.minsize(700,490)
        self._build()
        self.protocol("WM_DELETE_WINDOW",self.destroy)
        self.transient(parent)
        self.after(80,lambda:self.editor._apply_initial_language(self))

    def _build(self):
        wrapper=ttk.Frame(self,padding=12)
        wrapper.pack(fill="both",expand=True)
        ttk.Label(wrapper,text="Spielbezogene XAML-Anbindung",
                  font=("Segoe UI",14,"bold")).pack(anchor="w")
        ttk.Label(wrapper,wraplength=870,justify="left",
                  text="Der Script Extender kann statische XAML-Patches beim "
                       "Laden der Spieloberfläche anwenden. Diese Werkstatt "
                       "verwendet nur einen tatsächlich im ausgewählten Spiel "
                       "vorhandenen, einmaligen Grid-Namen und den exakten "
                       "SHA-256-Stand der Quell-XAML. Es werden ausschließlich "
                       "Paketdateien unter work/ erzeugt."
                       ).pack(anchor="w",pady=(7,14))

        game=ttk.LabelFrame(wrapper,text="1 · Installiertes SHCDE-Spiel / Script Extender",padding=9)
        game.pack(fill="x",pady=3)
        row=ttk.Frame(game)
        row.pack(fill="x")
        ttk.Entry(row,textvariable=self.source).pack(
            side="left",fill="x",expand=True,padx=(0,6))
        ttk.Button(row,text="Spielordner …",command=self.choose_game).pack(side="left",padx=2)
        ttk.Button(row,text="XAML durchsuchen",command=self.scan).pack(side="left",padx=2)
        ttk.Label(game,text="Wähle den Spiel-Hauptordner oder direkt den "
                  "Unterordner BepInEx/plugins/000shcdese/Override/Assets/GUI.",
                  wraplength=870).pack(anchor="w",pady=(6,0))

        target=ttk.LabelFrame(wrapper,text="2 · Nachgewiesenen Menü-/HUD-Container wählen",padding=9)
        target.pack(fill="x",pady=5)
        ttk.Combobox(target,textvariable=self.target_choice,
                     state="readonly",width=72).pack(fill="x",padx=2,pady=3)
        self.target_picker=target.winfo_children()[-1]
        option=ttk.Frame(target)
        option.pack(fill="x",pady=5)
        ttk.Label(option,text="Bildposition relativ zum gewählten Container:").pack(side="left")
        ttk.Combobox(option,textvariable=self.anchor,
                     values=list(ALL_ALIGNMENTS),state="readonly",width=19
                     ).pack(side="left",padx=9)
        ttk.Button(option,text="Patch vorprüfen",command=self.preview_patch).pack(
            side="right",padx=3)
        ttk.Label(target,wraplength=850,text=(
            "Wichtig: Das Layout wird als statische Bildüberlagerung "
            "innerhalb des ausgewählten Grid eingeblendet. Die schon "
            "vorhandenen Spiel-Schaltflächen bleiben für die Mausklicks "
            "zuständig (IsHitTestVisible=False). Neue klickbare Buttons "
            "brauchen gesonderte Noesis-ViewModels/Lua/C#."
        )).pack(anchor="w",pady=4)

        mod=ttk.LabelFrame(wrapper,text="3 · Eigenes GUI-Modpaket bauen",padding=9)
        mod.pack(fill="x",pady=4)
        for label,var in (("Mod-GUID",self.guid),("Anzeigename",self.name)):
            line=ttk.Frame(mod);line.pack(fill="x",pady=3)
            ttk.Label(line,text=label,width=13).pack(side="left")
            ttk.Entry(line,textvariable=var).pack(side="left",fill="x",expand=True)
        ttk.Checkbutton(mod,
                text="Eigene zusätzliche XAML-Patches ebenfalls verpacken",
                variable=self.include_xaml).pack(anchor="w",pady=6)
        ttk.Button(mod,
            text="Nachgewiesene Spieloberfläche + PNG als Asset-Mod bauen",
            command=self.build).pack(fill="x",pady=(4,0))
        qa_row=ttk.Frame(mod)
        qa_row.pack(fill="x",pady=(7,2))
        ttk.Button(
            qa_row,text="Nur in QA-Spielkopie installieren",
            command=self.install_qa,
        ).pack(side="left",padx=3)
        ttk.Button(
            qa_row,text="QA-Spiel starten",
            command=self.start_qa_game,
        ).pack(side="left",padx=3)
        ttk.Button(
            qa_row,text="QA-Installation sicher zurücknehmen",
            command=self.remove_qa,
        ).pack(side="left",padx=3)

        ttk.Label(wrapper,textvariable=self.status,
                  wraplength=900,justify="left").pack(fill="x",pady=(10,5))
        report=ttk.Frame(wrapper)
        report.pack(fill="both",expand=True,pady=(2,0))
        self.detail=tk.Text(report,height=9,wrap="word",state="disabled")
        self.detail.pack(side="left",fill="both",expand=True)
        scroll=ttk.Scrollbar(report,orient="vertical",command=self.detail.yview)
        self.detail.config(yscrollcommand=scroll.set)
        scroll.pack(side="right",fill="y")

    def _log(self,text):
        self.detail.config(state="normal")
        self.detail.delete("1.0","end")
        self.detail.insert("end",str(text))
        self.detail.config(state="disabled")

    def choose_game(self):
        pick=filedialog.askdirectory(
            parent=self,title="Installierten Stronghold-Crusader-DE-Spielordner wählen")
        if pick:
            self.source.set(pick)
            self.scan()

    def _gui_path(self):
        selected=Path(self.source.get().strip())
        if not self.source.get().strip():
            raise WorkshopError("Bitte zuerst einen Spielordner wählen.")
        suffix=Path("BepInEx/plugins/000shcdese/Override/Assets/GUI")
        path=selected if selected.name=="GUI" else selected/suffix
        return installed_gui(path)[0]

    def scan(self):
        try:
            folder=self._gui_path()
            found=discover_grid_targets(folder)
            self.targets={item.label:item for item in found}
            self.target_picker.configure(values=list(self.targets))
            self.target_choice.set("")
            self._selected_path=folder
            installed_version=found[0].extender_version
            self.status.set(f"{len(found)} eindeutig benannte UI-Container "
                f"gefunden. Script Extender: {installed_version} "
                "(alle Versionsnummern sind zur Inspektion zulässig). "
                "Bitte einen konkreten Container auswählen.")
            self._log("\n".join(
                f"{t.label} · {t.xpath} · XAML SHA {t.source_sha256[:16]}… "
                for t in found[:25]
            )+"\n\nKeine Spieldateien wurden geändert.")
        except (OSError,ValueError) as exc:
            self.targets={}
            self.target_choice.set("")
            self._selected_path=None
            self.status.set("Spiel-XAML nicht prüfbar: "+str(exc))
            self._log(str(exc))

    def _chosen(self):
        target=self.targets.get(self.target_choice.get())
        if target is None or self._selected_path is None:
            raise WorkshopError("Zuerst Spiel-XAML einlesen und einen Grid-Container auswählen")
        if self.editor.is_dirty() or self.editor._save_hash is None:
            raise WorkshopError("Layout zuerst speichern und als PNG exportieren")
        audit_export(self.editor.scene,self.project,
                     scene_sha256=self.editor._save_hash)
        return target

    def _current_build(self):
        """Reject a cached package after any layout/PNG/XAML/target change."""
        result=self._built_result
        if result is None:
            raise WorkshopError("Bitte zuerst das gebundene Modpaket erstellen")
        target=self._chosen()  # Also verifies saved scene and current PNG hashes.
        if self._gui_path()!=self._selected_path:
            raise WorkshopError("Spielordner geändert: XAML neu einlesen und neu bauen")
        if result["guid"]!=self.guid.get().strip():
            raise WorkshopError("Mod-GUID nach dem Bau geändert: erneut bauen")
        if result["manifest"]["Name"]!=self.name.get().strip():
            raise WorkshopError("Mod-Name nach dem Bau geändert: erneut bauen")
        _,current=generate_patch(
            self.editor.scene,self.project,game_gui=self._selected_path,
            target=target,alignment=self.anchor.get(),
            scene_sha256=self.editor._save_hash,
        )
        if current!=result["target"]:
            raise WorkshopError(
                "Gespeichertes Layout, Bild oder XAML-Bindung seit dem Bau "
                "geändert: erst erneut exportieren und Modpaket neu bauen"
            )
        return result

    def preview_patch(self):
        try:
            chosen=self._chosen()
            raw,report=generate_patch(
                self.editor.scene,self.project,
                game_gui=self._selected_path,target=chosen,
                alignment=self.anchor.get(),
                scene_sha256=self.editor._save_hash,
            )
            self._log(
                "EXAKTER XAML-PFAD: "+report["patch_path"]+"\n"
                "QUELL-SHA: "+report["source_xaml_sha256"]+"\n"
                "BILD: "+report["resource"]+"\n\n"
                +raw.decode("utf8")+"\n"
                "Die statische XML-Simulation ist erfolgreich. "
                "Das laufende Spiel wurde hiermit noch nicht getestet."
            )
            self.status.set("Patch erfolgreich erzeugt und gegen den "
                "gespeicherten Spiel-XAML-Container offline validiert.")
            return report
        except (OSError,ValueError) as exc:
            messagebox.showerror("Noesis-Patch",str(exc),parent=self)
            return None

    def build(self):
        try:
            target=self._chosen()
            if not self.guid.get().strip() or not self.name.get().strip():
                raise WorkshopError("Mod-ID und Anzeigename müssen ausgefüllt sein")
            if not messagebox.askyesno(
                "Statische Spiel-UI-Anbindung erstellen",
                f"XAML: {target.xaml_document}\n"
                f"Grid: {target.grid_name}\n"
                f"SE-Version: {target.extender_version}\n\n"
                "Ein neues Asset-Mod mit zusammengefügter PNG und "
                "nachgewiesenem Add-Patch bauen? Die Originale bleiben "
                "unverändert. Sichtbarkeit im Spiel muss noch praktisch "
                "abgenommen werden.",
                parent=self,default="no",
            ):
                return None
            result=build_bound_mod(
                self.editor.scene,self.project,
                scene_sha256=self.editor._save_hash,
                game_gui=self._selected_path,target=target,
                alignment=self.anchor.get(),
                guid=self.guid.get().strip(),
                name=self.name.get().strip(),
                include_existing_patches=self.include_xaml.get(),
            )
            self._log(json.dumps({
                "asset_mod":result["asset_mod_folder"],
                "zip":result["zip"],
                "patch":result["target"]["patch_path"],
                "game_xaml_sha256":result["target"]["source_xaml_sha256"],
                "binding_report":result["binding_report"],
                "no_game_files_changed":True,
            },ensure_ascii=False,indent=2))
            self._built_result=result
            self.status.set("Spielbezogenes Noesis-Asset-Modpaket gebaut: "
                            +result["zip"])
            messagebox.showinfo(
                "Spiel-XAML-Modpaket erstellt",
                "Die PNG-Ressource und der konkrete XAML-Add-Patch "
                "wurden geprüft und verpackt.\n\n"+result["zip"]+
                "\n\nZum Aktivieren nur in einer bewusst gewählten "
                "Spielkopie installieren, Spiel neu starten und "
                "Sichtbarkeit/Bedienung prüfen. Kein automatischer Eingriff.",
                parent=self,
            )
            return result
        except (OSError,ValueError,RuntimeError) as exc:
            messagebox.showerror("Noesis-Mod nicht erstellt",str(exc),parent=self)
            self.status.set("Keine Veröffentlichung: "+str(exc))
            return None


    def install_qa(self):
        """Install only in a recognized, explicitly chosen QA GAME copy."""
        try:
            built=self._current_build()
            from hud_menu_noesis_qa import qa_game_root, qa_install
            game=qa_game_root(self._gui_path())
            if not messagebox.askyesno(
                "QA-Spielkopie verändern – sicherer Test",
                f"Nur in dieser QA-Spielkopie installieren?\n{game}\n\n"
                f"Mod: {self._built_result['guid']}\n"
                "Es wird ausschließlich ein NEUER eigener Modordner "
                "unter BepInEx/plugins angelegt; vorhandene Dateien "
                "werden nicht überschrieben. Ein SHA-256-Rückbau ist "
                "für unveränderte Testdateien verfügbar.",
                parent=self,default="no",
            ):
                return None
            receipt=qa_install(
                self.project,self._gui_path(),
                built["asset_mod_folder"])
            self.status.set("Geschützte QA-Probeinstallation: "
                            +receipt["folder"])
            self._log(json.dumps(receipt,ensure_ascii=False,indent=2))
            messagebox.showinfo(
                "QA-Mod installiert",
                "Die QA-Kopie wurde erweitert. Du kannst jetzt bewusst "
                "das QA-Spiel starten und im Menü/HUD prüfen, ob der "
                "statische Overlay tatsächlich erscheint. Danach Spiel "
                "schließen und über »sicher zurücknehmen« rückbauen.",
                parent=self,
            )
            return receipt
        except (OSError,ValueError,RuntimeError) as exc:
            messagebox.showerror("QA-Installation abgelehnt",str(exc),parent=self)
            return None

    def remove_qa(self):
        """No removal of untracked/mutated files, never touch real game data."""
        try:
            from hud_menu_noesis_qa import qa_game_root, qa_remove
            game=qa_game_root(self._gui_path())
            guid=self.guid.get().strip()
            if not messagebox.askyesno(
                "QA-Mod sicher zurücknehmen",
                f"Nur den anhand des SpriteSuite-Belegs geprüften "
                f"Mod {guid!r} in der QA-Spielkopie\n{game}\n"
                "löschen? Das Spiel muss geschlossen sein. "
                "Fremde oder nachträglich bearbeitete Dateien "
                "bleiben aus Sicherheitsgründen unangetastet.",
                parent=self,default="no",
            ):
                return None
            result=qa_remove(self.project,self._gui_path(),guid)
            self.status.set("QA-Mod sicher zurückgenommen: "+guid)
            self._log(json.dumps(result,ensure_ascii=False,indent=2))
            return result
        except (OSError,ValueError,RuntimeError) as exc:
            messagebox.showerror("QA-Rückbau abgelehnt",str(exc),parent=self)
            return None

    def start_qa_game(self):
        """Start only a marked QA installation after explicit user approval."""
        try:
            from hud_menu_noesis_qa import qa_status
            receipt=qa_status(self.project,self._gui_path(),
                              self.guid.get().strip())
            game=Path(receipt["qa_game"])
            executable=game/"Stronghold Crusader Definitive Edition.exe"
            if executable.is_symlink() or not executable.is_file():
                raise WorkshopError("QA-Spielstartdatei nicht verfügbar")
            if not messagebox.askyesno(
                "QA-Spiel für Sichtprüfung starten",
                f"{executable}\n\n"
                "Der visuelle und spielmechanische Befund muss im "
                "laufenden Menü geprüft werden. Die statische XAML-"
                "Prüfung allein ist kein vollständiger Ingame-Nachweis. "
                "QA-Spiel starten?",
                parent=self,default="no",
            ):
                return None
            os.startfile(str(executable),cwd=str(game))
            self.status.set(
                "QA-Spiel gestartet. HUD/Menu beobachten, danach schließen "
                "und erst dann den geprüften Mod zurückbauen."
            )
            return executable
        except (OSError,ValueError,RuntimeError) as exc:
            messagebox.showerror("QA-Spielstart abgelehnt",str(exc),parent=self)
            return None

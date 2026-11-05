"""Non-modal, read-only compatibility inspector for the real Windows runtime."""
from __future__ import annotations
import json
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog,ttk,messagebox

from suite_compatibility_preflight import collect


# Localized presentation only: machine-readable report keys remain stable.
COMPONENT_DE={
    "Windows x64 host":"Windows-x64-System",
    "Python runtime":"Python-Laufzeit",
    "Tcl/Tk":"Tcl/Tk",
    "Python dependencies":"Python-Abhängigkeiten",
    "Qt Sandbox":"Qt-Spielvorschau",
    "Illustrated PDF manual":"Bebildertes PDF-Handbuch",
    "Launcher / project files":"Programmstart und Dateien",
    ".NET SDK (optional)":".NET-SDK (optional)",
    "Native game ABI":"Native Spiel-ABI",
    "Local Steam discovery":"Lokale Steam-Erkennung",
    "Game XAML/Noesis source structure":"Spiel-XAML-/Noesis-Quellstruktur",
}


def german_detail(message:str)->str:
    exact={
        "Bundled Tcl/Tk 8.6 scripts present":
           "Die mitgelieferten Tcl/Tk-8.6-Dateien sind vorhanden.",
        "System Tcl/Tk 8.6 scripts present":
           "Die Tcl/Tk-8.6-Dateien des Python-Systems sind vorhanden.",
        "Bundled Tcl/Tk 8.6 scripts missing or invalid":
           "Mitgelieferte Tcl/Tk-8.6-Dateien fehlen oder sind ungültig.",
        "QtWidgets and offscreen platform plugin launched successfully":
           "QtWidgets und das Offscreen-Plugin wurden erfolgreich gestartet.",
        "PySide6 not installed":"PySide6 ist nicht installiert.",
        "Expected application entry points and version file":
           "Startmodule und Versionsdatei sind im Paket enthalten.",
        "No SDK listed":"Kein .NET-SDK registriert.",
        "Not found on PATH":"Nicht im Systempfad gefunden.",
        "Steam BuildID does not attest Unity/Noesis/Script Extender ABI":
           "Steam-Build-ID beweist keine Unity-/Noesis-/Script-Extender-ABI.",
        "14-page illustrated PDF manual found (header/trailer valid)":
           "14-seitiges PDF-Handbuch vorhanden; Dateikopf und Dateiende geprüft.",
    }
    if message in exact:return exact[message]
    if message.endswith(" versions match requirements-py313-win_amd64.lock"):
        return message.replace(" versions match "," Paketversionen stimmen mit ")
    if message.endswith(" versions match requirements-py314-win_amd64.lock"):
        return message.replace(" versions match "," Paketversionen stimmen mit ")
    if message.endswith(" matching game installations (read-only)"):
        return message.replace(" matching game installations (read-only)",
                               " passende Spielinstallation(en) lesend erkannt")
    if "unique XAML Grid targets; Script Extender" in message:
        return (message.replace("unique XAML Grid targets; Script Extender",
                "eindeutige XAML-Grids; Script Extender")
                .replace("source structure only, never proof of native gameplay",
                         "nur Quellstruktur, kein Nachweis nativer Spielfunktionen"))
    return message


class CompatibilityWindow(tk.Toplevel):
    def __init__(self,app):
        super().__init__(app)
        self.app=app
        self.title("SpriteSuite - Kompatibilitätsprüfung")
        self.geometry("790x590")
        self.minsize(595,460)
        self._messages=queue.Queue()
        self._job=None
        self._job_pending=False
        self.report=None
        self._selected_game_root=None
        self.status=tk.StringVar(self)
        self.details=tk.StringVar(self)
        self.summary=tk.StringVar(self)
        self._build()
        self.protocol("WM_DELETE_WINDOW",self.close)
        self.bind("<Escape>",lambda _e:self.close())
        self.refresh_language()
        self.refresh()

    def _en(self):return self.app.language.get().upper()=="EN"
    def _label(self,de,en):return en if self._en() else de

    def _build(self):
        body=ttk.Frame(self,padding=15)
        body.pack(fill="both",expand=True)
        self.head=ttk.Label(body,font=("Segoe UI",17,"bold"))
        self.head.pack(anchor="w")
        self.legal=ttk.Label(body,wraplength=740,justify="left")
        self.legal.pack(fill="x",pady=(5,11))
        self.summary_label=ttk.Label(body,textvariable=self.summary)
        self.summary_label.pack(fill="x",pady=(0,8))
        self.table=ttk.Treeview(body,columns=("status","detail"),
                     show="tree headings",selectmode="browse",height=10)
        self.table.column("#0",width=195,minwidth=145,stretch=False)
        self.table.column("status",width=106,minwidth=90,stretch=False)
        self.table.column("detail",width=425,minwidth=200,stretch=True)
        sc=ttk.Scrollbar(body,orient="vertical",command=self.table.yview)
        self.table.configure(yscrollcommand=sc.set)
        self.table.pack(side="left",fill="both",expand=True)
        sc.pack(side="right",fill="y")
        self.table.bind("<<TreeviewSelect>>",self._selected)
        footer=ttk.Frame(self,padding=(15,6,15,14))
        footer.pack(side="bottom",fill="x")
        self.note=ttk.Label(footer,textvariable=self.details,wraplength=740,
                            justify="left")
        self.note.pack(fill="x",pady=(0,9))
        self.refresh_button=ttk.Button(footer,command=self.refresh)
        self.refresh_button.pack(side="left",padx=(0,6))
        self.steam_button=ttk.Button(footer,command=lambda:self.refresh(steam=True))
        self.steam_button.pack(side="left",padx=(0,6))
        self.game_button=ttk.Button(footer,command=self.choose_game)
        self.game_button.pack(side="left",padx=(0,6))
        self.save_button=ttk.Button(footer,command=self.save_report)
        self.save_button.pack(side="right")

    def refresh_language(self):
        self.title(self._label("SpriteSuite - Kompatibilitätsprüfung",
                               "SpriteSuite - Compatibility check"))
        self.head.configure(text=self._label("Kompatibilität prüfen",
                                             "Check compatibility"))
        self.legal.configure(text=self._label(
            "Nur lesend. Diese Prüfung installiert nichts und gibt keine "
            "unbestätigten Unity-/Noesis-/Spielbuilds frei.",
            "Read-only. This check installs nothing and does not approve "
            "unverified Unity/Noesis/game builds."))
        for col,de,en in (("#0","Komponente","Component"),
                           ("status","Befund","Status"),
                           ("detail","Nachweis","Evidence")):
            self.table.heading(col,text=self._label(de,en))
        self.refresh_button.configure(text=self._label("Erneut prüfen","Recheck"))
        self.steam_button.configure(text=self._label("Steam nur lesen","Read Steam only"))
        self.game_button.configure(text=self._label(
            "Spielstruktur prüfen","Inspect game data"))
        self.save_button.configure(text=self._label("Bericht speichern …","Save report…"))
        if self.report:self._render()

    def choose_game(self):
        """Read-only directory selection; never install or copy game assets."""
        if self._job_pending:return
        root=filedialog.askdirectory(parent=self,title=self._label(
            "Spielordner auswählen (nur lesen)","Select game folder (read only)"))
        if root:
            self.refresh(game_root=Path(root))

    def refresh(self,*,steam=False,game_root:Path|None=None):
        if self._job_pending:return
        if game_root is not None:
            self._selected_game_root=Path(game_root)
        self._job_pending=True
        self.refresh_button.configure(state="disabled")
        self.steam_button.configure(state="disabled")
        self.game_button.configure(state="disabled")
        self.summary.set(self._label("Lokale Umgebung wird geprüft …",
                                     "Checking local environment…"))
        self._messages=queue.Queue()
        def task():
            try:
                data=collect(check_steam=steam,
                             game_root=self._selected_game_root)
                self._messages.put(("result",data))
            except Exception as exc:
                self._messages.put(("error",f"{type(exc).__name__}: {exc}"))
        self._job=threading.Thread(target=task,daemon=True)
        self._job.start()
        self.after(100,self._poll)

    def _poll(self):
        if not self.winfo_exists():return
        try:kind,data=self._messages.get_nowait()
        except queue.Empty:
            if self._job_pending:self.after(100,self._poll)
            return
        self._job_pending=False
        self.refresh_button.configure(state="normal")
        self.steam_button.configure(state="normal")
        self.game_button.configure(state="normal")
        if kind=="result":
            self.report=data
            self._render()
        else:
            self.summary.set(self._label("Prüfung konnte nicht abgeschlossen werden: ",
                "Compatibility check failed: ")+str(data))

    def _render(self):
        if not self.report:return
        entries=self.report.get("checks",[])
        selected=self.table.selection()
        keep=selected[0] if selected else None
        self.table.delete(*self.table.get_children())
        status_names={
           "ready":self._label("Bereit","Ready"),
           "limited":self._label("Eingeschränkt","Limited"),
           "blocked":self._label("Blockiert","Blocked"),
           "unverified":self._label("Nicht bestätigt","Unverified"),
        }
        english=self._en()
        for i,row in enumerate(entries):
            name=row["name"] if english else COMPONENT_DE.get(row["name"],row["name"])
            detail=row["detail"] if english else german_detail(row["detail"])
            self.table.insert("","end",iid=str(i),text=name,
                    values=(status_names.get(row["status"],row["status"]),
                            detail))
        if keep and self.table.exists(keep):
            self.table.selection_set(keep)
            self._selected()
        elif entries:
            self.table.selection_set("0")
            self._selected()
        passed=sum(row["status"]=="ready" for row in entries)
        self.summary.set(self._label(
            f"{passed}/{len(entries)} Komponenten bereit. Native Spiel-ABI niemals automatisch freigegeben.",
            f"{passed}/{len(entries)} components ready. Native game ABI is never auto-approved."))

    def _selected(self,_event=None):
        if not self.report:return
        chosen=self.table.selection()
        if not chosen:return
        try:row=self.report["checks"][int(chosen[0])]
        except (IndexError,KeyError,ValueError):return
        suffix=row.get("recommendation_en" if self._en() else "recommendation_de","")
        detail=row["detail"] if self._en() else german_detail(row["detail"])
        self.details.set(detail+(("\n"+suffix) if suffix else ""))

    def save_report(self):
        if not self.report:
            messagebox.showinfo(self._label("Noch kein Bericht","No report"),
                     self._label("Zuerst prüfen.","Run a check first."),parent=self)
            return
        target=filedialog.asksaveasfilename(
             parent=self,defaultextension=".json",
             initialfile="SpriteSuite-Kompatibilitaet.json",
             filetypes=[("JSON","*.json")])
        if not target:return
        try:
            dest=Path(target)
            if dest.is_symlink():raise ValueError("Symlink destination not allowed")
            dest.write_text(json.dumps(self.report,ensure_ascii=False,indent=2)+"\n",
                            encoding="utf-8")
        except (OSError,ValueError) as exc:
            messagebox.showerror(self._label("Speichern fehlgeschlagen","Save failed"),
                str(exc),parent=self)

    def close(self):
        if getattr(self.app,"_compat_window",None) is self:
            self.app._compat_window=None
        self.destroy()


def open_compatibility_window(app):
    old=getattr(app,"_compat_window",None)
    if old is not None:
        try:
            if old.winfo_exists():
                old.lift()
                return old
        except tk.TclError:pass
    window=CompatibilityWindow(app)
    app._compat_window=window
    return window

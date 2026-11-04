"""Non-modal, read-only compatibility inspector for the real Windows runtime."""
from __future__ import annotations
import json
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog,ttk,messagebox

from suite_compatibility_preflight import collect


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
        self.save_button.configure(text=self._label("Bericht speichern …","Save report…"))
        if self.report:self._render()

    def refresh(self,*,steam=False):
        if self._job_pending:return
        self._job_pending=True
        self.refresh_button.configure(state="disabled")
        self.steam_button.configure(state="disabled")
        self.summary.set(self._label("Lokale Umgebung wird geprüft …",
                                     "Checking local environment…"))
        self._messages=queue.Queue()
        def task():
            try:
                data=collect(check_steam=steam)
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
        for i,row in enumerate(entries):
            self.table.insert("","end",iid=str(i),text=row["name"],
                    values=(status_names.get(row["status"],row["status"]),
                            row["detail"]))
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
        self.details.set(row["detail"]+(("\n"+suffix) if suffix else ""))

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

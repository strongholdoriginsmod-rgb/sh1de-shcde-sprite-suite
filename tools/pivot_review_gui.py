"""Tk tool window for measured, *review-only* pivots from Zinnenlineal.

The window lives inside the already running Sprite Suite process. Its actions
read source images, render grounded before/after previews and export a review
record under work/reports. No atlas or game file is patched implicitly.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import ImageTk

from stronghold_europe_de.pivot_measurements import (
    PivotMeasurementError, load_measurements, review_measurements,
    render_comparison, save_review_report,
)
from stronghold_europe_de.pivot_approvals import (
    PivotDecision, can_approve, save_approval_report,
)

STATUSES = {
    "bereits_passend": "Bereits passend",
    "pruefen": "Korrektur prüfen",
    "geometrie_abweichend": "Bildgröße abweichend",
    "referenz_abweichend": "Pivot/Referenz abweichend",
    "nicht_gefunden": "Frame nicht gefunden",
}


class PivotReviewWindow(tk.Toplevel):
    def __init__(self, app, project_root: str | Path):
        super().__init__(app)
        self.app=app
        self.project_root=Path(project_root)
        self.measurement_file=None
        self.reviews=[]
        self.decisions={}
        self._base_status=""
        self._preview_image=None
        self._bc7_pending=None
        self._bc7_generation=0
        self._bc7_results={}
        self.title("Zinnenlineal – Pivot-Messwerte prüfen")
        self.geometry("1160x810")
        self.minsize(790,590)
        self.status=tk.StringVar(value=(
            "Zinnenlineal-Messdatei wählen. Keine Sprite-, Spiel- "
            "oder Atlaskorrektur erfolgt automatisch."
        ))
        head=ttk.Frame(self)
        head.pack(fill="x",padx=12,pady=8)
        ttk.Button(head,text="Zinnen-Messdatei öffnen …",command=self.choose).pack(side="left",padx=3)
        self.open_catalog=ttk.Button(head,text="Frame im Katalog",command=self.show_in_catalog)
        self.open_catalog.pack(side="left",padx=3)
        self.open_sandbox=ttk.Button(head,text="Im Sandkasten",command=self.show_in_sandbox)
        self.open_sandbox.pack(side="left",padx=3)
        self.bc7_check=ttk.Button(
            head,text="Pivot im BC7-Atlas prüfen",command=self.inspect_bc7
        )
        self.bc7_check.pack(side="left",padx=3)
        self.export=ttk.Button(head,text="Prüfbericht exportieren",command=self.export_report)
        self.export.pack(side="right",padx=3)
        actions=ttk.Frame(self)
        actions.pack(fill="x",padx=12,pady=(0,5))
        self.approve=ttk.Button(
            actions,text="Nach Sichtprüfung freigeben",command=self.mark_approved
        )
        self.approve.pack(side="left",padx=3)
        self.reject=ttk.Button(actions,text="Vorschlag ablehnen",command=self.mark_rejected)
        self.reject.pack(side="left",padx=3)
        self.reset=ttk.Button(actions,text="Entscheidung zurücksetzen",command=self.clear_decision)
        self.reset.pack(side="left",padx=3)
        self.export_decision=ttk.Button(
            actions,text="Freigabeprotokoll exportieren",command=self.export_decisions
        )
        self.export_decision.pack(side="right",padx=3)
        ttk.Label(
            self,text="Original-Zinnenlineal-Messwerte (nur prüfen, nicht installieren)",
            font=("Segoe UI",12,"bold")
        ).pack(anchor="w",padx=15,pady=(0,6))
        ttk.Label(
            self,textvariable=self.status,wraplength=1050
        ).pack(anchor="w",padx=15,pady=(0,6))
        columns=("name","offset","current","proposal","status","source","decision")
        self.table=ttk.Treeview(self,columns=columns,show="headings",height=10,selectmode="browse")
        for key,caption,width in (
            ("name","Sprite",165),("offset","Versatz (rechts/hoch)",155),
            ("current","Aktueller Pivot",156),("proposal","Gemessener Ziel-Pivot",160),
            ("status","Prüfergebnis",145),("source","Quelle",85),
            ("decision","Entscheidung",115)
        ):
            self.table.heading(key,text=caption)
            self.table.column(key,width=width,anchor="w",stretch=key=="name")
        self.table.pack(fill="both",expand=True,padx=12,pady=(0,10))
        self.table.bind("<<TreeviewSelect>>",self._selected)
        self.preview=tk.Label(self,background="#1f2327",anchor="center")
        self.preview.pack(fill="both",expand=False,padx=12,pady=5)
        self.preview.configure(height=320)
        self.detail=tk.StringVar(value="Messungen werden gegen den aktuellen Grafikindex geprüft.")
        ttk.Label(
            self,textvariable=self.detail,wraplength=1080,justify="left"
        ).pack(fill="x",padx=14,pady=(2,10))
        self._update_buttons()

    def _update_buttons(self):
        enabled="normal" if self.measurement_file is not None else "disabled"
        self.export.configure(state=enabled)
        selected="normal" if self.current() is not None else "disabled"
        self.open_catalog.configure(state=selected)
        self.open_sandbox.configure(state=selected)
        row=self.current()
        already_checked = (
            bool(row)
            and self._bc7_results.get(row.measurement.name, {}).get("status")
            == "bereits_im_bc7"
        )
        self.approve.configure(
            state="normal" if row and can_approve(row) and not already_checked
            else "disabled"
        )
        self.bc7_check.configure(
            state="normal" if row and row.side=="geliefert"
            and row.status in ("pruefen","bereits_passend")
            and self._bc7_pending is None else "disabled"
        )
        self.reject.configure(state="normal" if row and row.status=="pruefen" else "disabled")
        self.reset.configure(state="normal" if row and row.measurement.name in self.decisions else "disabled")
        self.export_decision.configure(state="normal" if self.decisions else "disabled")

    def choose(self):
        from asset_katalog import target_game_dir
        game=target_game_dir()
        source=game/"Zinnenlineal" if game else self.project_root/"work"
        path=filedialog.askopenfilename(
            parent=self,title="Zinnenlineal-Messungen (JSON)",
            initialdir=str(source if source.is_dir() else self.project_root/"work"),
            filetypes=[("Zinnenlineal-JSON","*.json"),("Alle Dateien","*.*")]
        )
        if path:
            self.load(path)

    def load(self, filename: str | Path) -> bool:
        try:
            measurement=load_measurements(filename)
            checks=review_measurements(measurement,self.project_root)
        except (OSError,ValueError,PivotMeasurementError) as exc:
            messagebox.showwarning("Messdatei abgelehnt",str(exc),parent=self)
            return False
        self.measurement_file=measurement
        self.reviews=checks
        self.decisions={}
        self._bc7_generation+=1
        self._bc7_results={}
        self.table.delete(*self.table.get_children())
        for idx,row in enumerate(checks):
            item=row.measurement
            current=(
                f"{row.actual_pivot[0]:.6f}, {row.actual_pivot[1]:.6f}"
                if row.actual_pivot else "—"
            )
            self.table.insert("", "end",iid=str(idx),values=(
                item.name,f"{item.right:+d} / {item.up:+d}",
                current,f"{item.new_pivot_x:.6f}, {item.new_pivot_y:.6f}",
                STATUSES[row.status],row.side or "—","—",
            ))
        from collections import Counter
        states=Counter(r.status for r in checks)
        self._base_status=(
            f"{len(checks)} gemessene Frames • "
            f"{states['bereits_passend']} bereits passend • "
            f"{states['pruefen']} prüfbar • "
            f"{len(checks)-states['bereits_passend']-states['pruefen']} mit Warnung. "
            "Keine Spiel- oder Atlasdatei wird durch diesen Prüfer geändert."
        )
        self._show_status()
        if checks:
            self.table.selection_set("0")
            self.table.focus("0")
            self._selected()
        else:
            self.preview.configure(image="",text="Messdatei enthält keine Verschiebungen")
            self.detail.set("Keine Korrekturvorschläge vorhanden.")
        self._update_buttons()
        return True

    def current(self):
        if not self.reviews:
            return None
        selection=self.table.selection()
        if not selection:
            return None
        try:
            index=int(selection[0])
            return self.reviews[index] if 0<=index<len(self.reviews) else None
        except (ValueError,IndexError):
            return None

    def _selected(self,_event=None):
        row=self.current()
        if row is None:
            self._update_buttons()
            return
        picture=render_comparison(row,width=980,height=320)
        self._preview_image=ImageTk.PhotoImage(picture,master=self)
        self.preview.configure(image=self._preview_image,text="")
        self.detail.set(
            f"{row.measurement.name} | {STATUSES[row.status]}: {row.reason}. "
            f"Gemessen: rechts {row.measurement.right:+d} px, "
            f"hoch {row.measurement.up:+d} px. "
            "Gelbe Kreuzmarkierung = gleicher Weltanker vor/nach Korrektur; "
            "das Bild ist unverändert."
        )
        bc7 = self._bc7_results.get(row.measurement.name)
        if bc7:
            if bc7["status"]=="bereits_im_bc7":
                self.detail.set(
                    self.detail.get() +
                    f" Publizierter BC7-Atlas: Pivot {bc7['bc7_pivot']} "
                    f"(Cache {bc7['cache_key'][:12]}), "
                    "bereits passend – kein BC7-Neubau erforderlich."
                )
            else:
                self.detail.set(
                    self.detail.get() +
                    f" Publizierter BC7-Atlas: Pivot {bc7['bc7_pivot']}; "
                    "ein gesonderter BC7-Metadaten-/Geometrieneubau wäre nötig."
                )
        self._update_buttons()

    def inspect_bc7(self):
        """Inspect the real shipped BC7 Atlas in a worker; never write."""
        row=self.current()
        if (row is None or self.measurement_file is None
            or self._bc7_pending is not None
            or row.side!="geliefert"
            or row.status not in ("pruefen","bereits_passend")):
            return
        diag=getattr(self.app,"diagnose_tab",None)
        selected_profile=getattr(diag,"release_profile",None)
        profile_id=(
            selected_profile.get() if selected_profile is not None
            else "sprite-suite-world-bc7-v2"
        )
        source=self.measurement_file
        expected=tuple(self.reviews)
        generation=self._bc7_generation
        result_queue=queue.Queue(maxsize=1)
        self._bc7_pending=result_queue
        self._update_buttons()
        self.detail.set(
            f"{row.measurement.name}: veröffentlichte BC7-Bundles und "
            "Gruppen-Cache-Atlas werden nur lesend überprüft."
        )

        def work():
            from stronghold_europe_de.pivot_bc7_cache import audit_published_measurement
            try:
                # A GUI decision may outlive the original file. Recheck it
                # before AND after the slow complete SHA-256 manifest audit.
                for iteration in range(2):
                    current=load_measurements(source.path)
                    if (
                        current.sha256!=source.sha256
                        or tuple(review_measurements(current,self.project_root))!=expected
                    ):
                        raise PivotMeasurementError(
                            "Zinnen-Messung oder Sprite-Index seit Vorschau geändert – neu laden"
                        )
                    if iteration==0:
                        evidence=audit_published_measurement(
                            self.project_root,profile_id,row.measurement
                        )
                result_queue.put(("ok",generation,row.measurement.name,evidence))
            except Exception as exc:
                result_queue.put(("error",generation,row.measurement.name,str(exc)))

        threading.Thread(
            target=work,name="sprite-suite-bc7-pivot-review",daemon=True
        ).start()
        self.after(100,self._poll_bc7)

    def _poll_bc7(self):
        if self._bc7_pending is None:
            return
        try:
            message=self._bc7_pending.get_nowait()
        except queue.Empty:
            self.after(100,self._poll_bc7)
            return
        self._bc7_pending=None
        status,generation,name,value=message
        if generation!=self._bc7_generation:
            self._update_buttons()
            return
        if status!="ok":
            self._update_buttons()
            messagebox.showwarning(
                "BC7-Pivot nicht nachgewiesen",
                str(value)+"\n\nKeine Atlas-/Spiel-/Profildatei verändert.",
                parent=self,
            )
            self._selected()
            return
        self._bc7_results[name]=value
        self._selected()

    def show_in_catalog(self):
        row=self.current()
        if row is not None:
            self.app.show_in_catalog(row.measurement.group,row.measurement.name)

    def show_in_sandbox(self):
        row=self.current()
        if row is not None:
            self.app.show_in_sandbox(row.measurement.group,row.measurement.number)

    def _show_status(self):
        if not self._base_status:
            return
        approved=sum(d.action=="freigegeben" for d in self.decisions.values())
        rejected=sum(d.action=="abgelehnt" for d in self.decisions.values())
        self.status.set(
            f"{self._base_status} Entscheidungen: {approved} freigegeben, "
            f"{rejected} abgelehnt; übrige zurückgestellt."
        )

    def mark_approved(self):
        row=self.current()
        if row is None:
            return
        if (
            self._bc7_results.get(row.measurement.name, {}).get("status")
            == "bereits_im_bc7"
        ):
            messagebox.showwarning(
                "Bereits im BC7 korrigiert",
                "Der veröffentlichte BC7-Atlas besitzt bereits den gemessenen "
                "Zielpivot. Eine erneute Korrektur darf nicht freigegeben werden.",
                parent=self,
            )
            return
        if not can_approve(row):
            messagebox.showwarning(
                "Keine Freigabe möglich",
                "Nur ein geprüfter, noch unveränderter Ausgangspivot im "
                "ausgelieferten Index darf freigegeben werden.",
                parent=self,
            )
            return
        m=row.measurement
        confirmed=messagebox.askyesno(
            "Sichtprüfung bestätigen",
            f"Frame: {m.name}\n"
            f"Aktueller ausgelieferter Pivot: {row.actual_pivot}\n"
            f"Gemessener Ziel-Pivot: ({m.new_pivot_x:.6f}, {m.new_pivot_y:.6f})\n\n"
            "Nach visueller Prüfung diesen Vorschlag als FREIGEGEBEN "
            "für ein separates Freigabeprotokoll markieren?\n\n"
            "Es werden weder Atlas noch Spiel noch Arbeitskopie geändert.",
            icon="warning",default="no",parent=self,
        )
        if confirmed:
            self._set_decision(row,"freigegeben")

    def mark_rejected(self):
        row=self.current()
        if row and row.status=="pruefen":
            self._set_decision(row,"abgelehnt")

    def _set_decision(self,row,action):
        self.decisions[row.measurement.name]=PivotDecision(
            action,recorded_at=datetime.now(timezone.utc).isoformat(timespec="seconds")
        )
        self.table.set(self.table.selection()[0],"decision",
                       "Freigegeben" if action=="freigegeben" else "Abgelehnt")
        self._show_status()
        self._selected()

    def clear_decision(self):
        row=self.current()
        if row and row.measurement.name in self.decisions:
            self.decisions.pop(row.measurement.name)
            self.table.set(self.table.selection()[0],"decision","—")
            self._show_status()
            self._selected()

    def export_decisions(self):
        if not self.decisions or self.measurement_file is None:
            return
        try:
            output=save_approval_report(
                self.measurement_file,self.reviews,self.project_root,self.decisions
            )
        except (OSError,ValueError,PivotMeasurementError) as exc:
            messagebox.showerror(
                "Freigabeprotokoll nicht erstellt",
                str(exc)+"\n\nFalls die Quelle geändert wurde, Messung erneut öffnen.",
                parent=self,
            )
            return
        self._show_status()
        messagebox.showinfo(
            "Freigabeprotokoll exportiert",
            str(output)+"\n\n"
            "Entscheidungen und SHA-256-Quellen sind dokumentiert. "
            "Keine Sprite-, Index-, Atlas- oder Spieldatei wurde verändert.",
            parent=self,
        )

    def export_report(self):
        if self.measurement_file is None:
            return
        try:
            output=save_review_report(
                self.measurement_file,self.reviews,self.project_root
            )
        except (OSError,ValueError) as exc:
            messagebox.showerror("Prüfbericht",str(exc),parent=self)
            return
        self.status.set(
            f"Prüfbericht gespeichert: {output}. "
            "Das ist ein Vorschlag, keine automatische Atlasänderung."
        )
        messagebox.showinfo(
            "Prüfbericht erstellt",str(output)+
            "\n\nKeine Spieldateien oder Sprite-Atlanten verändert.",
            parent=self,
        )

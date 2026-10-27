"""Small native Tk pixel editor for Stronghold 1 HUD crops inside Sprite Suite.

Works on PNG copies under work/sh1-hud-editierbar, never the installed game.
The canvas dimensions are fixed by the exported original SH1 XAML contract.
"""
from __future__ import annotations

import math
import os
import tempfile
import tkinter as tk
from pathlib import Path
from tkinter import ttk, filedialog, messagebox, colorchooser

from PIL import Image, ImageTk, ImageDraw


class Sh1HudPixelEditor(tk.Toplevel):
    def __init__(self, parent, path: Path, after_save=None, workspace: Path | None = None):
        from ui_sh1_hud import DEFAULT_WORK, ATLAS_NAMES
        from suite_sh1_hud_core import load_project, under_work
        source=Path(path)
        self.root=(under_work(workspace) if workspace is not None
                   else DEFAULT_WORK.resolve(strict=True))
        # Keep the editor on named crops only: no baseline atlas, no link aliases.
        if source.is_symlink():
            raise ValueError("SH1-HUD-Editor darf keine Dateiverknüpfungen bearbeiten")
        self.path=source.resolve(strict=True)
        if (not self.path.is_file() or self.path.parent.parent != self.root
            or self.path.parent.name not in ATLAS_NAMES
            or self.path.suffix.lower()!=".png"):
            raise ValueError("SH1-HUD-Editor darf nur echte PNG-Arbeitskopien unter work/ bearbeiten")
        # The passed filename must occur exactly once in the source-pinned
        # Noesis index; no arbitrary PNG in the work folder is editable.
        self._entry=next(
            (entry for entry in load_project(self.root)
             if entry["path"] == self.path), None)
        if self._entry is None:
            raise ValueError("PNG ist keine benannte SH1-HUD-Arbeitskopie")
        with Image.open(self.path) as opened:
            self.image=opened.convert("RGBA")
        if self.image.width*self.image.height>2_000_000:
            raise ValueError("Zu grosses Einzelelement fuer den Pixeleditor")
        self.initial_size=self.image.size
        self.disk_digest=self._disk_digest()
        self.saved=self.image.copy()
        self.on_saved=after_save
        self.undo_history=[]
        self.redo_history=[]
        self._image_tk=None
        self._refresh_id=None
        self._dragging=False
        self._last=None

        super().__init__(parent)
        # Tk variables must be attached to this actual window, not to an
        # implicit default root (which embedding clients may disable).
        self.mode=tk.StringVar(master=self,value="Pinsel")
        self.color=tk.StringVar(master=self,value="#E2B86A")
        self.brush=tk.IntVar(master=self,value=1)
        self.zoom=tk.IntVar(master=self,value=2 if self.image.width<420 else 1)
        self.alpha=tk.IntVar(master=self,value=255)
        self.grid_on=tk.BooleanVar(master=self,value=False)
        self.checker_on=tk.BooleanVar(master=self,value=True)
        self.title("Stronghold 1 HUD bearbeiten – "+self.path.name)
        self.geometry("1120x810")
        self.minsize(650,440)
        self.protocol("WM_DELETE_WINDOW",self.close_editor)
        self._create_controls()
        self._refresh()
        self.bind("<Control-s>",lambda e:self.save())
        self.bind("<Control-z>",lambda e:self.undo())
        self.bind("<Control-y>",lambda e:self.redo())
        self.focus_set()

    def _create_controls(self):
        top=ttk.Frame(self)
        top.pack(fill="x",padx=9,pady=8)
        ttk.Label(top,text=f"{self.path.parent.name} / {self.path.name}",font=("Segoe UI",10,"bold")).pack(side="left",padx=(0,14))
        ttk.Label(top,text=f"{self.image.width} × {self.image.height} px").pack(side="left")
        bar=ttk.Frame(self)
        bar.pack(fill="x",padx=9,pady=(0,5))
        ttk.Label(bar,text="Werkzeug:").pack(side="left")
        for value in ("Pinsel","Radierer","Fülleimer","Pipette"):
            ttk.Radiobutton(bar,text=value,value=value,variable=self.mode).pack(side="left",padx=3)
        ttk.Button(bar,text="Farbe...",command=self.pick_color).pack(side="left",padx=7)
        self.swatch=tk.Label(bar,text="    ",bg=self.color.get(),relief="sunken")
        self.swatch.pack(side="left")
        ttk.Label(bar,text="Deckkraft").pack(side="left",padx=(8,2))
        tk.Spinbox(bar,from_=0,to=255,width=4,textvariable=self.alpha).pack(side="left")
        ttk.Label(bar,text="Pinsel").pack(side="left",padx=(11,2))
        tk.Spinbox(bar,from_=1,to=25,width=3,textvariable=self.brush).pack(side="left")
        ttk.Label(bar,text="Zoom").pack(side="left",padx=(11,2))
        spin=tk.Spinbox(bar,from_=1,to=8,width=3,textvariable=self.zoom,command=self._refresh)
        spin.pack(side="left")
        spin.bind("<Return>",lambda e:self._refresh())
        ttk.Checkbutton(bar,text="Pixelraster",variable=self.grid_on,
                        command=self._refresh).pack(side="left",padx=(8,0))
        tools=ttk.Frame(self)
        tools.pack(fill="x",padx=9,pady=3)
        ttk.Button(tools,text="Rückgängig",command=self.undo).pack(side="left",padx=2)
        ttk.Button(tools,text="Wiederholen",command=self.redo).pack(side="left",padx=2)
        ttk.Button(tools,text="PNG einsetzen...",command=self.import_png).pack(side="left",padx=8)
        ttk.Button(tools,text="Auf gespeicherten Stand",command=self.restore_saved).pack(side="left",padx=2)
        ttk.Button(tools,text="Original aus XAML laden",command=self.restore_original).pack(side="left",padx=6)
        ttk.Button(tools,text="ORIGINS Blau/Silber",command=self.preview_origins_palette).pack(side="left",padx=3)
        ttk.Button(tools,text="Speichern (Strg+S)",command=self.save).pack(side="right",padx=5)
        ttk.Label(self,text="Änderungen betreffen nur die ausgewählte HUD-PNG im SpriteSuite-Arbeitsordner. Größe bleibt unverändert.").pack(fill="x",padx=12)
        host=ttk.Frame(self)
        host.pack(fill="both",expand=True,padx=9,pady=(6,3))
        host.rowconfigure(0,weight=1)
        host.columnconfigure(0,weight=1)
        self.canvas=tk.Canvas(host,background="#33363b",highlightthickness=0,relief="sunken")
        self.canvas.grid(row=0,column=0,sticky="nsew")
        vertical=ttk.Scrollbar(host,orient="vertical",command=self.canvas.yview)
        horizontal=ttk.Scrollbar(host,orient="horizontal",command=self.canvas.xview)
        vertical.grid(row=0,column=1,sticky="ns")
        horizontal.grid(row=1,column=0,sticky="ew")
        self.canvas.config(xscrollcommand=horizontal.set,yscrollcommand=vertical.set)
        self.canvas.bind("<ButtonPress-1>",self.mouse_down)
        self.canvas.bind("<B1-Motion>",self.mouse_move)
        self.canvas.bind("<ButtonRelease-1>",self.mouse_up)
        self.canvas.bind("<MouseWheel>",self.mouse_wheel)
        self.canvas.bind("<Button-4>",self.mouse_wheel)
        self.canvas.bind("<Button-5>",self.mouse_wheel)
        self.status=tk.StringVar(master=self,value="Bereit")
        ttk.Label(self,textvariable=self.status).pack(fill="x",padx=11,pady=4)

    def _disk_digest(self) -> str:
        import hashlib
        with self.path.open("rb") as f:
            return hashlib.file_digest(f,"sha256").hexdigest()

    def mouse_wheel(self, event):
        """Scroll the cropped pixel canvas without changing original image data."""
        delta=getattr(event,"delta",0)
        if delta:
            step=(-1 if delta>0 else 1)*max(1,round(abs(delta)/120))
        elif getattr(event,"num",None)==4:
            step=-1
        elif getattr(event,"num",None)==5:
            step=1
        else:
            return None
        self.canvas.yview_scroll(step,"units")
        return "break"

    def _zoom_value(self) -> int:
        try:
            z=max(1,min(8,int(self.zoom.get())))
        except (ValueError,tk.TclError):
            z=1
        # Refuse huge pixmaps; otherwise a giant HUD image can freeze Tk/Qt.
        if self.image.width*self.image.height*z*z>24_000_000:
            z=max(1,int(math.sqrt(24_000_000/(self.image.width*self.image.height))))
        self.zoom.set(z)
        return z

    def _refresh(self):
        if self._refresh_id is not None:
            self.after_cancel(self._refresh_id)
            self._refresh_id=None
        zoom=self._zoom_value()
        scaled=self.image.resize((self.image.width*zoom,self.image.height*zoom),Image.Resampling.NEAREST)
        self._image_tk=ImageTk.PhotoImage(scaled,master=self.canvas)
        self.canvas.delete("all")
        self.canvas.create_image(0,0,image=self._image_tk,anchor="nw")
        self.canvas.configure(scrollregion=(0,0,scaled.width,scaled.height))
        if self.grid_on.get() and zoom >= 6 and self.image.width+self.image.height<=1400:
            for x in range(zoom,scaled.width,zoom):
                self.canvas.create_line(x,0,x,scaled.height,fill="#666a70")
            for y in range(zoom,scaled.height,zoom):
                self.canvas.create_line(0,y,scaled.width,y,fill="#666a70")
        dirty=self.image.tobytes()!=self.saved.tobytes()
        self.title(("● " if dirty else "")+"Stronghold 1 HUD bearbeiten – "+self.path.name)
        self.status.set(f"{self.image.width}×{self.image.height} px · Zoom {zoom}× · "
                        f"{self.mode.get()} · "+("Ungespeichert" if dirty else "Gespeichert"))

    def _queue_refresh(self):
        if self._refresh_id is None:
            self._refresh_id=self.after(35,self._refresh)

    def pick_color(self):
        selected=colorchooser.askcolor(self.color.get(),parent=self)
        if selected and selected[1]:
            self.color.set(selected[1])
            self.swatch.configure(bg=selected[1])
            self.mode.set("Pinsel")

    def _coords(self,event):
        scale=self._zoom_value()
        x=int(self.canvas.canvasx(event.x)//scale)
        y=int(self.canvas.canvasy(event.y)//scale)
        if 0<=x<self.image.width and 0<=y<self.image.height:
            return x,y
        return None

    def _remember(self):
        self.undo_history.append(self.image.copy())
        self.undo_history=self.undo_history[-12:]
        self.redo_history.clear()

    def mouse_down(self,event):
        pos=self._coords(event)
        if pos is None:return
        if self.mode.get()=="Pipette":
            rgb=self.image.getpixel(pos)[:3]
            self.color.set("#%02x%02x%02x"%rgb)
            self.swatch.configure(bg=self.color.get())
            self.mode.set("Pinsel")
            return
        if self.mode.get()=="Fülleimer":
            self._remember()
            try:
                ImageDraw.floodfill(self.image, pos, self._chosen_rgba(), thresh=0)
            except Exception:
                self.undo()
                raise
            self._queue_refresh()
            return
        self._remember()
        self._dragging=True
        self._last=None
        self._draw(pos)

    def mouse_move(self,event):
        if self._dragging:
            pos=self._coords(event)
            if pos is not None:self._draw(pos)

    def mouse_up(self,event):
        self._dragging=False
        self._last=None

    def _chosen_rgba(self):
        if self.mode.get()=="Radierer":
            return (0,0,0,0)
        raw=self.color.get().lstrip("#")
        try:
            alpha=max(0,min(255,int(self.alpha.get())))
            rgb=bytes.fromhex(raw)
            if len(rgb)!=3:
                raise ValueError("Farbcode nicht RGB")
            return tuple(rgb)+(alpha,)
        except (ValueError,tk.TclError):
            raise ValueError("Farbe/Deckkraft muss ein gültiger RGB-Wert sein")

    def _draw(self,point):
        try:width=max(1,min(25,int(self.brush.get())))
        except (ValueError,tk.TclError):width=1
        rgba=self._chosen_rgba()
        draw=ImageDraw.Draw(self.image)
        points=[point]
        if self._last:
            x0,y0=self._last
            x1,y1=point
            steps=max(abs(x1-x0),abs(y1-y0),1)
            points=[(round(x0+(x1-x0)*i/steps),round(y0+(y1-y0)*i/steps)) for i in range(steps+1)]
        half=width//2
        for x,y in points:
            draw.rectangle((x-half,y-half,x-half+width-1,y-half+width-1),fill=rgba)
        self._last=point
        self._queue_refresh()

    def undo(self):
        if self.undo_history:
            self.redo_history.append(self.image.copy())
            self.image=self.undo_history.pop()
            self._refresh()

    def redo(self):
        if self.redo_history:
            self.undo_history.append(self.image.copy())
            self.image=self.redo_history.pop()
            self._refresh()

    def restore_saved(self):
        self._remember()
        self.image=self.saved.copy()
        self._refresh()

    def restore_original(self):
        """Load the exact original Noesis crop into Undo; save stays explicit."""
        from suite_sh1_hud_core import original_crop
        try:
            original=original_crop(self.root,self._entry)
        except (OSError,ValueError,RuntimeError) as exc:
            messagebox.showerror("Originalbild unlesbar",str(exc),parent=self)
            return
        if original.size!=self.initial_size:
            messagebox.showerror("Originalgröße abweichend","Nicht übernehmbar",parent=self)
            return
        self._remember()
        self.image=original
        self._refresh()
        self.status.set("Original aus XAML geladen. Vor dem Schließen speichern oder Rückgängig.")

    def preview_origins_palette(self):
        """Apply the earlier Origins color transform only in the Undo buffer."""
        from suite_sh1_origins_palette import historical_flags, recolour
        themed, dark_blue = historical_flags(self._entry["key"], self._entry["file"])
        if not (themed or dark_blue):
            messagebox.showinfo(
                "ORIGINS-Farbschema",
                "Das frühere ORIGINS-Werkzeug wählt diesen Schlüssel nicht für "
                "sein Blau-/Silber-Farbschema aus. Kein Bild wurde verändert.",
                parent=self,
            )
            return
        if not messagebox.askyesno(
            "Historische ORIGINS-Farben übernehmen?",
            "Die ursprünglichen Blau-/Silber-Farbreaktionen aus dem früheren "
            "Stronghold-Origins-Werkzeug auf die aktuelle HUD-Arbeitskopie "
            "anwenden?\n\nDie Änderungen sind vollständig rückgängig zu machen "
            "und werden erst mit »Speichern« in die PNG geschrieben. "
            "Atlaspositionen werden nicht übertragen.",
            parent=self, default="no",
        ):
            return
        try:
            preview, count = recolour(
                self.image, themed=themed, dark_blue=dark_blue
            )
        except (ValueError, RuntimeError) as exc:
            messagebox.showerror("ORIGINS-Farbschema", str(exc), parent=self)
            return
        if count:
            self._remember()
            self.image = preview
            self._refresh()
            self.status.set(
                f"ORIGINS-Palette: {count} Pixel verändert. "
                "Rückgängig oder bewusst speichern."
            )
        else:
            self.status.set("Das Originalbild hatte keine passenden Farbpixel.")


    def import_png(self):
        chosen=filedialog.askopenfilename(parent=self,title="HUD-PNG mit identischen Abmessungen importieren",
                     filetypes=[("PNG","*.png")])
        if not chosen:return
        try:
            with Image.open(chosen) as opened:
                if opened.size!=self.initial_size:
                    raise ValueError(f"PNG ist {opened.size}; erwartet wird {self.initial_size}")
                incoming=opened.convert("RGBA")
            self._remember()
            self.image=incoming
            self._refresh()
        except (OSError,ValueError) as exc:
            messagebox.showerror("Ungültige HUD-PNG",str(exc),parent=self)

    def save(self):
        from ui_sh1_hud import ATLAS_NAMES
        if (self.image.size!=self.initial_size or self.path.is_symlink()
            or not self.path.is_file() or self.path.parent.parent!=self.root
            or self.path.parent.name not in ATLAS_NAMES):
            messagebox.showerror("Speichern verweigert","Dateigröße/Pfad stimmt nicht.",parent=self)
            return
        file=None
        try:
            # Do not silently clobber another editor's newer changes.
            if self._disk_digest()!=self.disk_digest:
                raise ValueError("Diese PNG wurde außerhalb des Editors verändert. "
                                 "Vor erneutem Speichern bitte Arbeitsstand neu laden.")
            handle,filename=tempfile.mkstemp(dir=self.path.parent,prefix=".sh1-hud-save-",suffix=".png")
            os.close(handle)
            file=Path(filename)
            self.image.save(file,"PNG")
            with Image.open(file) as reopened:
                if reopened.size!=self.initial_size or reopened.convert("RGBA").tobytes()!=self.image.tobytes():
                    raise ValueError("PNG-Nachkontrolle fehlgeschlagen")
            if self._disk_digest()!=self.disk_digest:
                raise ValueError("Die PNG wurde während des Speicherns verändert. "
                                 "Die fremde Version bleibt erhalten.")
            os.replace(file,self.path)
            self.disk_digest=self._disk_digest()
            self.saved=self.image.copy()
            self.status.set("HUD-PNG gespeichert: "+str(self.path))
            if self.on_saved:self.on_saved()
        except (OSError,ValueError) as exc:
            messagebox.showerror("HUD konnte nicht gespeichert werden",str(exc),parent=self)
        finally:
            if file is not None and file.exists():file.unlink()

    def close_editor(self):
        if self.image.tobytes()!=self.saved.tobytes():
            if not messagebox.askyesno("Ungespeicherte HUD-Änderungen","Änderungen verwerfen und schließen?",parent=self):
                return
        self.destroy()

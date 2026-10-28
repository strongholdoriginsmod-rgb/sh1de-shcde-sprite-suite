"""Editable local HUD/menu pixel and XAML windows (no original game writes)."""
from __future__ import annotations

from collections import deque
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, simpledialog, ttk

from PIL import Image, ImageDraw, ImageTk

from hud_menu_workspace import (
    WorkshopError, _existing, _relative, workspace, write_png,
)


def _bytes(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def stroke(image: Image.Image, xy: tuple[int, int], *, mode: str,
           rgba: tuple[int, int, int, int], brush: int = 1) -> bool:
    """One pure Pillow operation, useful for synthetic graphics regression."""
    x, y = xy
    if not (0 <= x < image.width and 0 <= y < image.height):
        return False
    color = (0, 0, 0, 0) if mode == "Radierer" else rgba
    if mode == "Füllen":
        # Pillow's floodfill only touches a contiguous same-colour region,
        # not all pixels with the same colour in a large atlas.
        ImageDraw.floodfill(image, (x,y), color, thresh=0)
    elif mode in ("Pinsel", "Radierer"):
        width = max(1, min(64, int(brush)))
        draw = ImageDraw.Draw(image)
        if width == 1:
            draw.point((x,y), fill=color)
        else:
            radius = width // 2
            draw.ellipse((x-radius, y-radius, x+radius, y+radius),
                         fill=color)
    else:
        return False
    return True


class HudMenuPixelEditor(tk.Toplevel):
    """Alpha-aware painting, undo/redo, import/resize, exact-on-disk save guard."""

    def __init__(self, parent, file: Path, *, project: Path, after_save=None):
        root = workspace(project)
        source = Path(file)
        if source.is_symlink():
            raise WorkshopError("Linked image cannot be edited")
        path = source.resolve(strict=True)
        relative = path.relative_to(root).as_posix()
        _existing(root, relative)
        if path.suffix.lower() != ".png":
            raise WorkshopError("The integrated pixel editor requires PNG")
        with Image.open(path) as opened:
            if opened.width * opened.height > 4_000_000:
                raise WorkshopError("Large image: use external editor (over 4 million pixels)")
            self.image = opened.convert("RGBA")
        self.project, self.path, self.relative = root, path, relative
        self.expected = sha256(path.read_bytes()).hexdigest()
        self.after_save = after_save
        self.original = self.image.copy()
        self.undo_stack: list[Image.Image] = []
        self.redo_stack: list[Image.Image] = []
        self.dirty = False
        self._picture = None
        self._anchor = None
        super().__init__(parent)
        self.title("HUD- & Menü-Pixeleditor · " + path.name)
        self.geometry("1040x770")
        self.minsize(680,470)
        self.mode = tk.StringVar(self, "Pinsel")
        self.color = tk.StringVar(self, "#E2B86A")
        self.opacity = tk.IntVar(self, 255)
        self.brush = tk.IntVar(self, 1)
        self.zoom = tk.IntVar(self, 2 if self.image.width < 300 else 1)
        self.show_grid = tk.BooleanVar(self, False)
        self.status = tk.StringVar(self, "Änderungen nur an der PNG-Kopie unter work/")
        self._layout()
        self._refresh()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Control-s>", lambda _: self.save())
        self.bind("<Control-z>", lambda _: self.undo())
        self.bind("<Control-y>", lambda _: self.redo())
        self.focus_set()

    def _layout(self):
        frame = ttk.Frame(self, padding=7)
        frame.pack(fill="x")
        ttk.Label(frame, text=self.relative, font=("Segoe UI",10,"bold")
                  ).pack(side="left")
        ttk.Label(frame, text=f"  {self.image.width} × {self.image.height} px"
                  ).pack(side="left")
        tools = ttk.Frame(self)
        tools.pack(fill="x",padx=8,pady=5)
        for choice in ("Pinsel","Radierer","Füllen","Pipette","Linie","Rechteck"):
            ttk.Radiobutton(tools, text=choice, value=choice,
                            variable=self.mode).pack(side="left",padx=2)
        ttk.Button(tools,text="Farbe …",command=self.choose_color).pack(
            side="left",padx=5)
        self.swatch=tk.Label(tools,text="    ",bg=self.color.get(),relief="sunken")
        self.swatch.pack(side="left")
        ttk.Label(tools,text="Alpha").pack(side="left",padx=(8,2))
        tk.Spinbox(tools,from_=0,to=255,width=4,
                   textvariable=self.opacity).pack(side="left")
        ttk.Label(tools,text="Pinsel").pack(side="left",padx=3)
        tk.Spinbox(tools,from_=1,to=64,width=3,
                   textvariable=self.brush).pack(side="left")
        ttk.Label(tools,text="Zoom").pack(side="left",padx=3)
        tk.Spinbox(tools,from_=1,to=8,width=3,
                   textvariable=self.zoom,command=self._refresh).pack(side="left")
        ttk.Checkbutton(tools,text="Pixelraster",
                        variable=self.show_grid,command=self._refresh).pack(side="left")
        actions=ttk.Frame(self)
        actions.pack(fill="x",padx=8,pady=(2,4))
        for label,command in (
            ("Rückgängig",self.undo),("Wiederholen",self.redo),
            ("PNG als Ebene einsetzen …",self.import_layer),
            ("Größe ändern …",self.resize),
            ("Auf geöffneten Stand",self.reset_opened),
            ("Speichern (Strg+S)",self.save)):
            ttk.Button(actions,text=label,command=command).pack(
                side="left",padx=3)
        holder=ttk.Frame(self)
        holder.pack(fill="both",expand=True,padx=8,pady=6)
        holder.rowconfigure(0,weight=1)
        holder.columnconfigure(0,weight=1)
        self.canvas=tk.Canvas(holder,background="#33383b",
                              highlightthickness=0)
        self.canvas.grid(row=0,column=0,sticky="nsew")
        y=ttk.Scrollbar(holder,orient="vertical",command=self.canvas.yview)
        x=ttk.Scrollbar(holder,orient="horizontal",command=self.canvas.xview)
        y.grid(row=0,column=1,sticky="ns")
        x.grid(row=1,column=0,sticky="ew")
        self.canvas.configure(yscrollcommand=y.set,xscrollcommand=x.set)
        self.canvas.bind("<Button-1>",self._down)
        self.canvas.bind("<B1-Motion>",self._drag)
        self.canvas.bind("<ButtonRelease-1>",self._up)
        ttk.Label(self,textvariable=self.status,
                  wraplength=950).pack(fill="x",padx=11,pady=5)

    def _rgba(self):
        value=self.color.get().lstrip("#")
        return tuple(bytes.fromhex(value))+(max(0,min(255,int(self.opacity.get()))),)

    def choose_color(self):
        selected=colorchooser.askcolor(
            initialcolor=self.color.get(),parent=self)[1]
        if selected:
            self.color.set(selected)
            self.swatch.configure(bg=selected)

    def _push(self):
        self.undo_stack.append(self.image.copy())
        del self.undo_stack[:-15]
        self.redo_stack.clear()

    def _coord(self,event):
        scale=max(1,min(8,int(self.zoom.get())))
        if self.image.width*self.image.height*scale*scale>16_000_000:
            scale=max(1,int((16_000_000/(self.image.width*self.image.height))**0.5))
            self.zoom.set(scale)
        x=int(self.canvas.canvasx(event.x))//scale
        y=int(self.canvas.canvasy(event.y))//scale
        return x,y

    def _down(self,event):
        xy=self._coord(event)
        x,y=xy
        if not(0<=x<self.image.width and 0<=y<self.image.height):
            return
        mode=self.mode.get()
        if mode=="Pipette":
            red,green,blue,alpha=self.image.getpixel(xy)
            self.color.set(f"#{red:02x}{green:02x}{blue:02x}")
            self.opacity.set(alpha)
            self.swatch.configure(bg=self.color.get())
            return
        self._push()
        self._anchor=xy
        if mode not in ("Linie","Rechteck"):
            self._paint(xy)

    def _drag(self,event):
        if self._anchor is None:
            return
        xy=self._coord(event)
        mode=self.mode.get()
        if mode in ("Pinsel","Radierer"):
            old=self._anchor
            ImageDraw.Draw(self.image).line(
                (*old,*xy),fill=(0,0,0,0) if mode=="Radierer"
                else self._rgba(),width=max(1,int(self.brush.get())))
            self._anchor=xy
            self.dirty=True
            self._refresh()

    def _up(self,event):
        if self._anchor is None:
            return
        mode=self.mode.get()
        if mode in ("Linie","Rechteck"):
            end=self._coord(event)
            draw=ImageDraw.Draw(self.image)
            a,b=self._anchor,end
            if mode=="Linie":
                draw.line((*a,*b),fill=self._rgba(),
                          width=max(1,int(self.brush.get())))
            else:
                draw.rectangle((*a,*b),outline=self._rgba(),
                               width=max(1,int(self.brush.get())))
            self.dirty=True
            self._refresh()
        self._anchor=None

    def _paint(self,xy):
        if stroke(self.image,xy,mode=self.mode.get(),
                  rgba=self._rgba(),brush=int(self.brush.get())):
            self.dirty=True
            self._refresh()

    def _refresh(self):
        zoom=max(1,min(8,int(self.zoom.get())))
        if self.image.width*self.image.height*zoom*zoom>16_000_000:
            zoom=max(1,int((16_000_000/(self.image.width*self.image.height))**0.5))
            self.zoom.set(zoom)
        size=(self.image.width*zoom,self.image.height*zoom)
        scaled=self.image.resize(size,Image.Resampling.NEAREST)
        if self.show_grid.get() and zoom>=4:
            draw=ImageDraw.Draw(scaled)
            for x in range(0,size[0],zoom):
                draw.line((x,0,x,size[1]),fill=(88,92,98,160))
            for y in range(0,size[1],zoom):
                draw.line((0,y,size[0],y),fill=(88,92,98,160))
        self._picture=ImageTk.PhotoImage(scaled)
        self.canvas.delete("all")
        self.canvas.create_image(0,0,image=self._picture,anchor="nw")
        self.canvas.configure(scrollregion=(0,0,*size))
        self.status.set(f"{self.image.width}×{self.image.height} px; "
                        f"{'ungespeicherte Änderungen' if self.dirty else 'gespeicherter Stand'}")

    def undo(self):
        if self.undo_stack:
            self.redo_stack.append(self.image.copy())
            self.image=self.undo_stack.pop()
            self.dirty=True
            self._refresh()

    def redo(self):
        if self.redo_stack:
            self.undo_stack.append(self.image.copy())
            self.image=self.redo_stack.pop()
            self.dirty=True
            self._refresh()

    def reset_opened(self):
        self._push()
        self.image=self.original.copy()
        self.dirty=True
        self._refresh()

    def import_layer(self):
        file=filedialog.askopenfilename(
            parent=self,filetypes=[("Grafik", "*.png *.jpg *.jpeg *.webp")])
        if not file:
            return
        try:
            with Image.open(file) as picture:
                if picture.width*picture.height>30_000_000:
                    raise WorkshopError("Layer too large")
                overlay=picture.convert("RGBA")
            if overlay.size!=self.image.size:
                if not messagebox.askyesno(
                    "Bild einpassen",
                    f"Neue Ebene {overlay.width}×{overlay.height} auf "
                    f"{self.image.width}×{self.image.height} skalieren?",
                    parent=self,default="no"):
                    return
                overlay=overlay.resize(self.image.size,Image.Resampling.LANCZOS)
            self._push()
            self.image.alpha_composite(overlay)
            self.dirty=True
            self._refresh()
        except (OSError,ValueError,WorkshopError) as exc:
            messagebox.showerror("Ebene",str(exc),parent=self)

    def resize(self):
        w=simpledialog.askinteger(
            "Bildbreite","Neue Breite in Pixeln (1–4096):",
            parent=self,initialvalue=self.image.width,minvalue=1,maxvalue=4096)
        if w is None:return
        h=simpledialog.askinteger(
            "Bildhöhe","Neue Höhe in Pixeln (1–4096):",
            parent=self,initialvalue=self.image.height,minvalue=1,maxvalue=4096)
        if h is None:return
        if w*h>4_000_000:
            messagebox.showerror("Pixelgrenze","Maximal 4 Mio Pixel im integrierten Editor.",parent=self)
            return
        if not messagebox.askyesno("Bildgeometrie",
            "Die XAML-/Atlas-Zuordnung wird NICHT automatisch geändert. "
            "Die Zielressource muss die neue Bildgröße unterstützen. Fortfahren?",
            parent=self,default="no"):
            return
        self._push()
        self.image=self.image.resize((w,h),Image.Resampling.NEAREST)
        self.dirty=True
        self._refresh()

    def save(self):
        try:
            blob=_bytes(self.image)
            write_png(self.relative,blob,project=self.project,
                      expected_sha256=self.expected)
            self.expected=sha256(blob).hexdigest()
            self.original=self.image.copy()
            self.dirty=False
            if self.after_save:self.after_save()
            self._refresh()
        except (OSError,ValueError,WorkshopError) as exc:
            messagebox.showerror("Nicht gespeichert",str(exc),parent=self)

    def close(self):
        if self.dirty and not messagebox.askyesno(
            "Änderungen verwerfen","Ungespeicherte Bearbeitung verwerfen?",
            parent=self,default="no"):
            return
        self.destroy()


class HudMenuTextEditor(tk.Toplevel):
    """Safe work-only XAML/JSON editor with syntax checks and atomic save."""

    def __init__(self,parent,file:Path,*,project:Path,after_save=None):
        self.project=workspace(project)
        path=Path(file)
        if path.is_symlink():raise WorkshopError("Linked text asset")
        self.path=path.resolve(strict=True)
        self.relative=self.path.relative_to(self.project).as_posix()
        _existing(self.project,self.relative,patch=self.relative.startswith("Patches/"))
        if self.path.suffix.lower() not in (".xaml",".json"):
            raise WorkshopError("Only XAML or JSON can be edited as text")
        if self.path.stat().st_size>2_000_000:raise WorkshopError("Text file too large")
        initial=self.path.read_text("utf8-sig")
        self.expected=sha256(self.path.read_bytes()).hexdigest()
        self.after_save=after_save
        super().__init__(parent)
        self.title("HUD- & Menü-XAML/JSON · "+self.path.name)
        self.geometry("1000x760")
        self.minsize(600,430)
        label=ttk.Label(self,text="Arbeitskopie: "+self.relative)
        label.pack(fill="x",padx=10,pady=8)
        self.editor=tk.Text(self,wrap="none",undo=True,font=("Consolas",11))
        self.editor.insert("1.0",initial)
        self.editor.edit_modified(False)
        self.editor.pack(fill="both",expand=True,padx=8)
        bar=ttk.Frame(self);bar.pack(fill="x",padx=8,pady=8)
        ttk.Button(bar,text="Prüfen",command=self.validate).pack(side="left")
        ttk.Button(bar,text="Speichern (Strg+S)",command=self.save).pack(side="left",padx=7)
        ttk.Label(bar,text="XAML: Syntax, XPath und Patch-Typen werden geprüft"
                  ).pack(side="left",padx=12)
        self.bind("<Control-s>",lambda _:self.save())
        self.protocol("WM_DELETE_WINDOW",self.close)

    def _validated(self, data:bytes) -> None:
        if len(data)>2_000_000:raise WorkshopError("Text exceeds 2 MiB")
        if self.path.suffix.lower()==".json":
            if not isinstance(json.loads(data.decode("utf8")),dict):
                raise WorkshopError("JSON resource must be an object")
        else:
            from se_asset_package import _check_xml
            fd,name=tempfile.mkstemp(suffix=".xaml",dir=self.path.parent)
            try:
                with os.fdopen(fd,"wb") as stream:stream.write(data)
                _check_xml(Path(name),patch=self.relative.startswith("Patches/"))
            finally:Path(name).unlink(missing_ok=True)

    def validate(self):
        try:
            self._validated(self.editor.get("1.0","end-1c").encode("utf8"))
            messagebox.showinfo("Prüfung","Syntax und Format sind gültig.",parent=self)
        except (OSError,ValueError) as exc:
            messagebox.showerror("Ungültige Ressource",str(exc),parent=self)

    def save(self):
        data=self.editor.get("1.0","end-1c").encode("utf8")
        try:
            self._validated(data)
            if self.path.is_symlink() or sha256(self.path.read_bytes()).hexdigest()!=self.expected:
                raise WorkshopError("File changed externally; reload instead of overwriting")
            fd,name=tempfile.mkstemp(prefix=".hud-text-",dir=self.path.parent)
            try:
                with os.fdopen(fd,"wb") as stream:
                    stream.write(data);stream.flush();os.fsync(stream.fileno())
                if sha256(self.path.read_bytes()).hexdigest()!=self.expected:
                    raise WorkshopError("File changed before save")
                os.replace(name,self.path)
            finally:Path(name).unlink(missing_ok=True)
            self.expected=sha256(data).hexdigest()
            self.editor.edit_modified(False)
            if self.after_save:self.after_save()
        except (OSError,ValueError) as exc:
            messagebox.showerror("Nicht gespeichert",str(exc),parent=self)

    def close(self):
        if self.editor.edit_modified() and not messagebox.askyesno(
            "Ungespeicherte Änderungen","Textänderungen verwerfen?",
            parent=self,default="no"):return
        self.destroy()

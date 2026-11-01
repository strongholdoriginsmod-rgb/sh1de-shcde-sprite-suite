"""SpriteSuite live-native Noesis/Unity pixel viewer with verified provenance.

The image pixels shown here are only from the *actual* game's NoesisView
RenderTexture or captured Unity screen. Python does not rerender XAML, move
pixels, fake a game renderer or substitute a synthetic screenshot.

The producer is the explicit BepInEx plugin installed by
origins_native_live_install.py. No image is displayed as 'native Noesis'
unless the plugin reported a completed native-noesis-rendertexture frame.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import os
import shutil
import tkinter as tk
from tkinter import filedialog,ttk
from secrets import token_hex
from typing import Callable

from PIL import Image,ImageTk,UnidentifiedImageError


class LiveFrameError(ValueError): pass


def live_directory()->Path:
    """Per-user telemetry folder, not a game-mod installation directory."""
    if os.name!="nt":
        return Path.home()/".local"/"share"/"SpriteSuite"/"NoesisNativeLive"
    appdata=os.environ.get("LOCALAPPDATA")
    if not appdata:
        raise LiveFrameError("LOCALAPPDATA missing: native game telemetry unavailable")
    return Path(appdata)/"SpriteSuite"/"NoesisNativeLive"


def game_process_is_live(pid:int)->bool:
    """Read-only Windows process check; a stale JSON file is not a live game."""
    if os.name!="nt" or type(pid) is not int or pid<=0:return False
    try:
        import ctypes
        from ctypes import wintypes
        kernel=ctypes.WinDLL("kernel32",use_last_error=True)
        kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        kernel.OpenProcess.restype=wintypes.HANDLE
        kernel.QueryFullProcessImageNameW.argtypes=[
            wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD)]
        kernel.QueryFullProcessImageNameW.restype=wintypes.BOOL
        kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        kernel.CloseHandle.restype=wintypes.BOOL
        handle=kernel.OpenProcess(0x1000,False,pid)
        if not handle:return False
        try:
            buffer=ctypes.create_unicode_buffer(32768)
            length=wintypes.DWORD(len(buffer))
            if not kernel.QueryFullProcessImageNameW(
                    handle,0,buffer,ctypes.byref(length)):return False
            program=Path(buffer.value)
            return program.name.casefold()==(
                  "Stronghold Crusader Definitive Edition.exe".casefold())
        finally:
            kernel.CloseHandle(handle)
    except (OSError,ValueError,AttributeError,OverflowError):
        return False


@dataclass(frozen=True)
class LiveFrame:
    path:Path
    source:str
    pixel_exact_native_noesis:bool
    pixel_exact_composited_game:bool
    size:tuple[int,int]
    game_pid:int
    abi_verified:bool
    menu_hook:bool
    map_hook:bool
    map_name:str|None
    map_loads:int
    map_unloads:int
    season_route:str|None
    native_views_seen:int
    completed_frames:int
    error:str


def read_live_frame(folder:Path|None=None)->tuple[LiveFrame|None,dict]:
    """Read strictly locally produced, bounded PNG frames, never arbitrary paths."""
    base=Path(folder) if folder is not None else live_directory()
    if not base.is_dir() or base.is_symlink():
        return None,{"state":"not_running","message":"Keine native Spiel-Telemetrie vorhanden"}
    report=base/"live-status.json"
    if not report.is_file() or report.is_symlink():
        return None,{"state":"not_running","message":"Das native Plugin hat keinen Status erzeugt"}
    if report.stat().st_size>32768:
        raise LiveFrameError("Native status report exceeds 32 KiB")
    try: value=json.loads(report.read_text("utf8"))
    except (UnicodeError,ValueError,OSError) as exc:
        raise LiveFrameError("Native status JSON not readable") from exc
    if not isinstance(value,dict) or value.get("schema")!="sprite-suite.origins-native-live.v1":
        raise LiveFrameError("Unrecognized native renderer telemetry schema")
    pid=value.get("game_process_pid")
    if type(pid) is not int or pid<=0:
        raise LiveFrameError("Game PID missing from native status")
    value["source_game_process_alive"]=game_process_is_live(pid)
    source=value.get("frame_source")
    filename=value.get("native_last_frame")
    if not isinstance(filename,str) or not filename:
        return None,{"state":"waiting",**value}
    if source not in {"native-noesis-rendertexture","unity-game-composited-screen"}:
        raise LiveFrameError("Unrecognized native frame source")
    image=Path(filename)
    if (image.is_symlink() or not image.is_file() or
        image.stat().st_size<60 or image.stat().st_size>64*1024*1024 or
        not image.resolve().is_relative_to(base.resolve()) or
        not image.name.startswith("native-frame-") or image.suffix.lower()!=".png"):
        raise LiveFrameError("Native frame must be an unchanged local PNG")
    try:
        with Image.open(image) as preview:
            if (preview.format!="PNG" or preview.width<2 or preview.height<2 or
                preview.width>8192 or preview.height>8192 or
                preview.width*preview.height>32_000_000):
                raise LiveFrameError("Invalid native frame dimensions")
            preview.verify()
            size=(preview.width,preview.height)
    except (OSError,UnidentifiedImageError,Image.DecompressionBombError) as exc:
        raise LiveFrameError("Native game PNG is corrupt or incomplete") from exc
    original=(source=="native-noesis-rendertexture")
    if (value.get("pixel_exact_native_noesis_texture") is not original or
        value.get("pixel_exact_composited_game_screenshot") is original):
        raise LiveFrameError("Native capture's provenance flags conflict with source")
    frame=LiveFrame(
        image,source,original,not original,size,pid,
        value.get("runtime_game_abi_verified") is True,
        value.get("native_menu_hook_registered") is True,
        value.get("native_map_hooks_registered") is True,
        value.get("active_map"),int(value.get("map_load_event_count",0)),
        int(value.get("map_unload_event_count",0)),
        value.get("active_season_route"),
        int(value.get("native_noesis_views_observed",0)),
        int(value.get("native_frame_count",0)),
        str(value.get("last_error") or ""))
    return frame,{"state":"captured",**value}


class NativeNoesisLivePreview(tk.Toplevel):
    """Native 1:1 pixel output, with optional deliberate scaling for comparison."""

    def __init__(self,parent,*,status_dir:Path|None=None,
                 on_reference:Callable[[Path],None]|None=None,
                 auto_poll:bool=True):
        super().__init__(parent)
        self.title("SpriteSuite · Native Noesis / Spiel-Renderausgabe")
        self.geometry("1280x840")
        self.minsize(820,540)
        self.source_dir=Path(status_dir) if status_dir is not None else live_directory()
        self.on_reference=on_reference
        self._poll_job=None
        self._polling=auto_poll
        self._photo=None
        self._frame=None
        self._stamp=None
        self.native_info=tk.StringVar(self,value="Noch keine native Noesis-Aufnahme")
        self.game_state=tk.StringVar(self,value="Live-Plugin nicht verbunden")
        self.pixel_state=tk.StringVar(self,value=(
            "Originaltreue: Die Suite zeigt unveränderte Spiel-Pixel, "
            "kein eigenständiger Python-Noesis-Renderer."))
        self.fit=tk.BooleanVar(self,value=False)
        self._build()
        self.protocol("WM_DELETE_WINDOW",self.close)
        self.refresh_once()
        if auto_poll:self._schedule()

    def _build(self):
        header=ttk.Frame(self,padding=9);header.pack(fill="x")
        ttk.Label(header,text="Native Noesis-/Unity-Pixelvorschau",
                  font=("Segoe UI",15,"bold")).pack(side="left")
        ttk.Button(header,text="Jetzt prüfen",command=self.refresh_once
                   ).pack(side="right",padx=6)
        ttk.Checkbutton(header,text="Fenster einpassen (nicht 1:1)",
                        variable=self.fit,command=lambda:self._show_image(True)
                        ).pack(side="right",padx=6)
        ttk.Button(header,text="Bild als Referenz in Editor",
                   command=self.use_reference).pack(side="right",padx=6)
        ttk.Button(header,text="Originalaufnahme kopieren …",
                   command=self.save_copy).pack(side="right",padx=6)
        ttk.Label(self,textvariable=self.native_info,
                  wraplength=1180,font=("Segoe UI",10,"bold")
                  ).pack(fill="x",padx=13,pady=(4,2))
        ttk.Label(self,textvariable=self.game_state,
                  wraplength=1180).pack(fill="x",padx=13,pady=2)
        ttk.Label(self,textvariable=self.pixel_state,wraplength=1180,
                  foreground="#9eacb8").pack(fill="x",padx=13,pady=(3,8))
        frame=ttk.Frame(self);frame.pack(fill="both",expand=True,padx=9,pady=9)
        self.canvas=tk.Canvas(frame,background="#121820",highlightthickness=0)
        horizontal=ttk.Scrollbar(frame,orient="horizontal",command=self.canvas.xview)
        vertical=ttk.Scrollbar(frame,orient="vertical",command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=horizontal.set,
                              yscrollcommand=vertical.set)
        self.canvas.grid(row=0,column=0,sticky="nsew")
        vertical.grid(row=0,column=1,sticky="ns")
        horizontal.grid(row=1,column=0,sticky="ew")
        frame.columnconfigure(0,weight=1);frame.rowconfigure(0,weight=1)
        self.canvas.bind("<Configure>",lambda _event:self._show_image(True))

    def refresh_once(self):
        try:
            frame,status=read_live_frame(self.source_dir)
            # A frame may remain on disk after the Unity process exits;
            # do not represent that archived bitmap as live pixels.
            is_live=status.get("source_game_process_alive") is True
            self._frame=frame if is_live else None
            self.game_state.set(
                "Plugin: "+("Spielprozess aktiv" if status.get("source_game_process_alive")
                            else "nicht verbunden / letzter Status")+
                " · ABI: "+str(status.get("runtime_game_abi_verified",False))+
                " · Menü-Hook: "+str(status.get("native_menu_hook_registered",False))+
                " · Map-Hooks: "+str(status.get("native_map_hooks_registered",False))+
                " · Spiel-PID: "+str(status.get("game_process_pid","–"))+
                " · Kartenevents: "+str(status.get("map_load_event_count",0))+
                "/"+str(status.get("map_unload_event_count",0))+
                " · Saisonroute (Atlas nicht freigegeben): "+
                str(status.get("active_season_route","–")))
            if self._frame is None:
                self._stamp=None
                self._photo=None
                self.canvas.delete("all")
                self.native_info.set(
                    ("Letzter nativer Frame ist historisch – kein laufender Spielprozess"
                     if frame is not None and not is_live else
                     "Noch kein echtes Bild: "+
                     str(status.get("message") or status.get("last_error") or
                         "Spiel muss eine Noesis-Ansicht darstellen")))
                self.pixel_state.set(
                    "Keine bestätigten Spielpixel. Die Tk-Layoutvorschau "
                    "ersetzt den nativen Renderer nicht.")
                return None
            label=("Isolierte native Noesis-RenderTexture" if
                   frame.pixel_exact_native_noesis else
                   "Natives, fertig zusammengesetztes Unity-Spielbild")
            self.native_info.set(
                label+" · "+str(frame.size[0])+"×"+str(frame.size[1])+
                " · "+str(frame.completed_frames)+" abgeschlossene Bildaufnahmen")
            self.pixel_state.set(
                "Pixeldaten wurden vom laufenden Spiel erzeugt. "+
                ("Kein eigenes Layout-Resampling; 1:1-Modus." if
                 not self.fit.get() else
                 "Zur Anzeige skaliert; Original-PNG bleibt unverändert.")+
                (" · "+frame.error if frame.error else ""))
            self._show_image()
            return frame
        except (OSError,ValueError,RuntimeError) as exc:
            self.native_info.set("Native Ausgabe nicht verifizierbar: "+str(exc))
            self._frame=None
            self._photo=None;self.canvas.delete("all")
            return None

    def _show_image(self,force:bool=False):
        frame=self._frame
        if frame is None:return
        try:
            metadata=(frame.path,frame.path.stat().st_mtime_ns,
                      frame.path.stat().st_size,frame.size,self.fit.get(),
                      (max(1,self.canvas.winfo_width()),
                       max(1,self.canvas.winfo_height())))
            if metadata==self._stamp and not force:return
            with Image.open(frame.path) as opened:
                image=opened.convert("RGBA")
            if self.fit.get():
                bounds=metadata[-1]
                image.thumbnail((max(2,bounds[0]-10),
                                 max(2,bounds[1]-10)),Image.Resampling.LANCZOS)
            self._photo=ImageTk.PhotoImage(image,master=self.canvas)
            self.canvas.delete("all")
            self.canvas.create_image(3,3,anchor="nw",image=self._photo)
            self.canvas.configure(scrollregion=(0,0,image.width+6,image.height+6))
            self._stamp=metadata
        except (OSError,ValueError,RuntimeError) as exc:
            self.native_info.set("Bild konnte nicht gezeigt werden: "+str(exc))

    def use_reference(self):
        if self._frame is None or self.on_reference is None:
            self.native_info.set("Kein aktuelles Bild oder kein verbundener XAML-Editor")
            return None
        self.on_reference(self._frame.path)
        return self._frame.path

    def save_copy(self):
        if self._frame is None:return None
        target=filedialog.asksaveasfilename(parent=self,
              title="Echte native Noesis-/Unity-PNG-Aufnahme kopieren",
              defaultextension=".png",filetypes=[("PNG","*.png")])
        if not target:return None
        path=Path(target)
        if path.exists() or path.is_symlink():
            self.native_info.set("Vorhandenes Bild wird nicht automatisch überschrieben")
            return None
        try:
            shutil.copyfile(self._frame.path,path)
            if path.read_bytes()!=self._frame.path.read_bytes():
                path.unlink(missing_ok=True)
                raise LiveFrameError("Kopierte Pixeldatei unterscheidet sich")
            return path
        except (OSError,ValueError) as exc:
            self.native_info.set("Kopie fehlgeschlagen: "+str(exc))
            return None

    def _schedule(self):
        if not self.winfo_exists() or not self._polling:return
        self._poll_job=self.after(650,self._poll_once)

    def _poll_once(self):
        self._poll_job=None
        self.refresh_once()
        self._schedule()

    def close(self):
        self._polling=False
        if self._poll_job is not None:
            self.after_cancel(self._poll_job)
            self._poll_job=None
        self.destroy()


def open_native_noesis_live(parent,*,on_reference=None,status_dir=None):
    return NativeNoesisLivePreview(parent,on_reference=on_reference,
                                   status_dir=status_dir)

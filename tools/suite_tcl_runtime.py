"""Reliable private Tcl/Tk runtime resolution and relocation for Windows.

Some portable Python installations intermittently fail to source init.tcl /
tk.tcl directly from developer toolchain paths despite files being present.
Load the shipped Tcl scripts from a verified, short, user-local cache instead
of relying on cwd, PATH, registry lookups or system-wide installations.

No game directories, system Python directories or global environment are
modified. The cache is fully derived from the bundled Python's own tcl/.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import json
import os
import shutil
import sys
import tempfile

SENTINELS=("tcl8.6/init.tcl","tk8.6/tk.tcl",
           "tk8.6/ttk/ttk.tcl","tk8.6/ttk/panedwindow.tcl")
CACHE_SCHEMA="sprite-suite.private-tcl-cache.v1"


class TclRuntimeError(RuntimeError):
    """The Tcl/Tk installation could not be prepared safely."""


def _fingerprint(folder:Path)->dict:
    result={}
    for name in SENTINELS:
        file=folder/name
        if not file.is_file() or file.is_symlink():
            raise TclRuntimeError("Tcl/Tk script missing: "+str(file))
        data=file.read_bytes()
        if not data or len(data)>1024*1024:
            raise TclRuntimeError("Tcl/Tk script unreadable or oversized: "+name)
        result[name]=sha256(data).hexdigest()
    return result


def locate_bundled_tcl(project:Path,*,explicit:Path|None=None)->Path:
    if explicit is not None:
        candidates=[Path(explicit)]
    else:
        candidates=[project/"python"/"tcl",
                    Path(sys.base_prefix)/"tcl",
                    Path(sys.executable).resolve().parent/"tcl"]
        library=os.environ.get("TCL_LIBRARY")
        if library:
            candidates.append(Path(library).parent)
    for candidate in candidates:
        try:
            if candidate.is_dir():
                _fingerprint(candidate)
                return candidate.resolve(strict=True)
        except (OSError,TclRuntimeError):
            continue
    raise TclRuntimeError(
        "Keine vollständige lokale Tcl/Tk-Laufzeit gefunden; "
        "Portable-Paket vollständig entpacken")


def _user_cache_root(project:Path)->Path:
    # System-wide Windows Temp may allow pathlib but deny Tcl's native source
    # operation. Prefer the user's own profile; fall back to project work/.
    if os.name=="nt":
        local=os.environ.get("LOCALAPPDATA")
        if local:
            folder=Path(local)/"SpriteSuite"/"Runtime"/"Tcl"
            if folder.drive and folder.drive.upper()!=os.environ.get(
                "SystemDrive","C:").upper():
                # A redirected profile on a network share is not a robust
                # native Tcl script root; prefer the local project workspace.
                return project/"work"/".private-tcl"
            return folder
    return project/"work"/".private-tcl"


def prepare_tcl_env(project:Path,*,source:Path|None=None,
                    cache_root:Path|None=None)->dict[str,str]:
    """Return verified process-local TCL_LIBRARY and TK_LIBRARY locations.

    First call creates one atomic, content-addressed user-local cache;
    follow-up calls merely validate critical .tcl bytes. Concurrent
    processes sharing a cache never modify an existing final directory.
    """
    root=Path(project).resolve()
    shipped=locate_bundled_tcl(root,explicit=source)
    fingerprints=_fingerprint(shipped)
    identity=sha256(json.dumps(fingerprints,sort_keys=True).encode()).hexdigest()[:16]
    base=Path(cache_root) if cache_root is not None else _user_cache_root(root)
    target=base/("py-tcl-"+identity)
    if target.is_symlink() or base.is_symlink():
        raise TclRuntimeError("Verknüpfter Tcl-Laufzeitcache ist nicht sicher")
    base.mkdir(parents=True,exist_ok=True)
    valid=False
    if target.is_dir():
        try:
            valid=_fingerprint(target)==fingerprints
        except (OSError,TclRuntimeError):
            valid=False
        if not valid:
            # User-owned existing cache is NEVER deleted or replaced. A new
            # cache identity is required; report corruption clearly.
            raise TclRuntimeError(
                "Lokaler Tcl-Cache beschädigt; Cacheverzeichnis manuell "
                "prüfen, bevor eine andere Version angelegt wird: "+str(target))
    if not valid:
        staged=Path(tempfile.mkdtemp(prefix=".tcl-staging-",dir=base))
        try:
            for entry in shipped.iterdir():
                dest=staged/entry.name
                if entry.is_symlink():
                    raise TclRuntimeError("Symbolischer Link in gebündelter Tcl-Laufzeit")
                if entry.is_dir():
                    shutil.copytree(entry,dest,symlinks=True)
                elif entry.is_file():
                    shutil.copy2(entry,dest)
            if _fingerprint(staged)!=fingerprints:
                raise TclRuntimeError("Tcl-Laufzeit beim Kopieren verändert")
            (staged/"cache-receipt.json").write_text(json.dumps({
                "schema":CACHE_SCHEMA,"source_fingerprints":fingerprints,
                "redistributable_python_runtime_only":True,
                "system_tcl_modified":False,
                "game_files_modified":False,
            },indent=2)+"\n",encoding="utf8")
            try:
                os.rename(staged,target)
            except FileExistsError:
                # Parallel launcher won the race. Check its immutable bytes.
                if _fingerprint(target)!=fingerprints:
                    raise TclRuntimeError("Tcl-Cache wurde parallel verändert")
        finally:
            if staged.exists() and not staged.is_symlink():
                shutil.rmtree(staged)
    return {"TCL_LIBRARY":str(target/"tcl8.6"),
            "TK_LIBRARY":str(target/"tk8.6"),
            "SPRITESUITE_TCL_RUNTIME_SOURCE":"private-verified-cache",
            "SPRITESUITE_TCL_RUNTIME_ROOT":str(target)}


def install_tcl_env(project:Path,*,source:Path|None=None,
                    cache_root:Path|None=None)->dict[str,str]:
    values=prepare_tcl_env(project,source=source,cache_root=cache_root)
    os.environ.update(values)
    return values


def call_with_tcl_bootstrap_retries(operation, *, attempts:int=5):
    """Retry only native Tcl library bootstrap reads, not ordinary GUI errors.

    Windows/Tcl can sporadically report native I/O failures while sourcing
    intact init.tcl/tk.tcl. No widgets or application state are published
    before this constructor returns successfully. The upper bound prevents
    concealing a permanently broken runtime installation.
    """
    import gc
    import time
    import tkinter as tk
    if type(attempts) is not int or attempts<1 or attempts>5:
        raise ValueError("Tk bootstrap attempts must be 1..5")
    for trial in range(attempts):
        try:
            return operation()
        except tk.TclError as exc:
            detail=str(exc).casefold()
            missing_tcl=("usable init.tcl" in detail or
                         "usable tk.tcl" in detail or
                         ("init.tcl" in detail and "couldn't read" in detail) or
                         ("invalid command name" in detail and
                          "tcl_findlibrary" in detail))
            if not missing_tcl or trial+1==attempts:
                raise
            gc.collect()
            time.sleep(0.10*(trial+1))


def create_tk_root(*, project:Path|None=None):
    """The same guarded native Tk root factory used by the suite launcher.

    Specialists and GUI smoke tests can use this rather than creating an
    unprotected standalone tkinter.Tk interpreter. No global Tk monkeypatch.
    """
    if project is not None:
        install_tcl_env(project)
    import tkinter as tk
    return call_with_tcl_bootstrap_retries(tk.Tk)

"""Reliable private Tcl/Tk runtime resolution and relocation for Windows.

Some portable Python installations intermittently fail to source init.tcl /
tk.tcl directly from developer toolchain paths despite files being present.
For Tcl/Tk 8.6, load the shipped scripts from a verified user-local cache.
For Python 3.14+ with native Tcl/Tk 9 zipfs, validate the official library
archives OR the official Python 3.15 Tcl/Tk DLL-embedded zipfs and keep the
interpreter's native mounting. Never use another Python installation's Tcl.

No game directories, system Python directories or global environment are
modified. The Tcl 8.6 cache is derived from bundled Python's own tcl/.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import json
import os
import shutil
import sys
import tempfile
import re
from zipfile import ZipFile, BadZipFile

SENTINELS=("tcl8.6/init.tcl","tk8.6/tk.tcl",
           "tk8.6/ttk/ttk.tcl","tk8.6/ttk/panedwindow.tcl")
CACHE_SCHEMA="sprite-suite.private-tcl-cache.v1"
ZIPFS9_REQUIRED = {
    "libtcl": ("tcl_library/init.tcl",),
    "libtk": ("tk_library/tk.tcl", "tk_library/ttk/ttk.tcl",
              "tk_library/ttk/panedwindow.tcl"),
}


class TclRuntimeError(RuntimeError):
    """The Tcl/Tk installation could not be prepared safely."""


def _zipfs9_fingerprint(folder:Path)->dict[str,str]:
    """Verify the real Python 3.14 Tcl/Tk 9 zipfs libraries, without unpacking.

    Tcl 9 mounts its library ZIPs natively at //zipfs:/lib/... rather than
    exposing an on-disk tcl9.0/init.tcl or tk9.0/tk.tcl tree.
    """
    if folder.is_symlink():
        raise TclRuntimeError("Verknüpfte Tcl-9-Laufzeit ist nicht zugelassen")
    result={}
    for prefix,required in ZIPFS9_REQUIRED.items():
        candidates=list(folder.glob(prefix+"9.0.*.zip"))
        if len(candidates)!=1:
            raise TclRuntimeError("Tcl-9-ZIP fehlt oder ist nicht eindeutig: "+prefix)
        archive=candidates[0]
        if (not re.fullmatch(prefix+r"9\.0\.[0-9]+\.zip",archive.name) or
                archive.is_symlink() or not archive.is_file() or
                not 1024<=archive.stat().st_size<=32*1024*1024):
            raise TclRuntimeError("Tcl-9-ZIP ist ungültig: "+archive.name)
        try:
            with ZipFile(archive) as zipped:
                infos=zipped.infolist()
                if len(infos)>10000 or sum(x.file_size for x in infos)>128*1024*1024:
                    raise TclRuntimeError("Tcl-9-ZIP überschreitet die Größenbegrenzung")
                for info in infos:
                    name=info.filename
                    if (name.startswith("/") or "\\" in name or
                            ".." in name.split("/") or info.file_size>4*1024*1024):
                        raise TclRuntimeError("Unsicherer Tcl-9-ZIP-Eintrag")
                for member in required:
                    info=zipped.getinfo(member)
                    if not 0<info.file_size<=1024*1024:
                        raise TclRuntimeError("Tcl-9-Startdatei ungültig: "+member)
                if zipped.testzip() is not None:
                    raise TclRuntimeError("Tcl-9-ZIP-Prüfsumme ist ungültig")
        except (BadZipFile,KeyError,OSError,ValueError) as exc:
            raise TclRuntimeError("Tcl-9-ZIP fehlerhaft: "+archive.name) from exc
        result[archive.name]=sha256(archive.read_bytes()).hexdigest()
    return result


def _embedded_zipfs9_fingerprint(folder:Path)->dict[str,str]:
    """Python 3.15 full Windows ZIP embeds Tcl/Tk 9 in signed binary DLLs.

    Validate only the CURRENT interpreter's DLLs and confirm Tcl+Tk actually
    mount the embedded startup scripts. An arbitrary external DLL folder may
    never attest a different interpreter.
    """
    current=(Path(sys.base_prefix)/"DLLs").resolve(strict=False)
    if (folder.is_symlink() or folder.resolve(strict=False)!=current
            or not folder.is_dir()):
        raise TclRuntimeError("Tcl-9 DLL-Ordner ist nicht die native Laufzeit")
    required=("tcl90.dll","tcl9tk90.dll")
    result={}
    for name in required:
        binary=folder/name
        if (not binary.is_file() or binary.is_symlink()
                or not 1000000<=binary.stat().st_size<=40*1024*1024):
            raise TclRuntimeError("Tcl-9 DLL fehlt oder ist ungültig: "+name)
        result["embedded_"+name]=sha256(binary.read_bytes()).hexdigest()
    import tkinter as tk
    if tk.TclVersion!=9.0 or tk.TkVersion!=9.0:
        raise TclRuntimeError("Eingebettetes Tcl/Tk passt nicht zum Interpreter")
    interpreter=tk.Tcl()
    if (interpreter.eval("file exists {//zipfs:/lib/tcl/tcl_library/init.tcl}")
            !="1"):
        raise TclRuntimeError("Tcl-9 embedded init.tcl ist nicht gemountet")
    # Confirm the real Tk library is usable, not merely an existing DLL.
    window=None
    try:
        window=tk.Tk()
        window.withdraw()
        if (window.eval("file exists {//zipfs:/lib/tk/tk_library/tk.tcl}")!="1"):
            raise TclRuntimeError("Tk-9 embedded tk.tcl ist nicht gemountet")
    except tk.TclError as exc:
        raise TclRuntimeError("Tk-9 embedded GUI nicht startbar") from exc
    finally:
        if window is not None:
            window.destroy()
    return result


def _fingerprint(folder:Path)->dict:
    if not (folder/"tcl8.6").is_dir():
        if folder.name.casefold()=="dlls":
            return _embedded_zipfs9_fingerprint(folder)
        return _zipfs9_fingerprint(folder)
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
    import tkinter as tk
    native_zipfs9=(tk.TclVersion>=9 and tk.TkVersion>=9)
    if explicit is not None:
        candidates=[Path(explicit)]
    else:
        candidates=[project/"python"/"tcl",
                    Path(sys.base_prefix)/"tcl",
                    Path(sys.executable).resolve().parent/"tcl"]
        if native_zipfs9:
            # Tcl 9 may be shipped in separate Tcl ZIPs (3.14) or directly
            # embedded into the interpreter's Tcl/Tk DLLs (3.15).
            # Both MUST belong to sys.base_prefix, never another project.
            candidates=[Path(sys.base_prefix)/"tcl",
                        Path(sys.base_prefix)/"DLLs"]
        library=os.environ.get("TCL_LIBRARY")
        if library:
            candidates.append(Path(library).parent)
    for candidate in candidates:
        try:
            if candidate.is_dir():
                fingerprints=_fingerprint(candidate)
                bundled_zipfs9=any(
                    k.startswith("libtcl9.0.") or k=="embedded_tcl90.dll"
                    for k in fingerprints)
                if explicit is None and bundled_zipfs9!=native_zipfs9:
                    continue
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
    """Return the verified process-local Tcl/Tk bootstrap contract.

    Tcl/Tk 8.6 uses an atomic, content-addressed user-local script cache.
    Tcl/Tk 9 keeps Python's built-in zipfs mounting after validating its
    archives, without creating a second cache or overriding library paths.
    """
    root=Path(project).resolve()
    shipped=locate_bundled_tcl(root,explicit=source)
    fingerprints=_fingerprint(shipped)
    if any(name.startswith("libtcl9.0.") or
           name=="embedded_tcl90.dll" for name in fingerprints):
        # Tcl/Tk 9 is backed by the current Python's own ZIP or native DLL
        # resources; do not override those mounts with a foreign folder.
        is_embedded="embedded_tcl90.dll" in fingerprints
        return {"SPRITESUITE_TCL_RUNTIME_SOURCE":(
                    "native-verified-embedded-zipfs9" if is_embedded
                    else "native-verified-zipfs9"),
                "SPRITESUITE_TCL_RUNTIME_ROOT":str(shipped)}
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
    import tkinter as tk
    native_zipfs9=(tk.TclVersion>=9 and tk.TkVersion>=9)
    mode=values.get("SPRITESUITE_TCL_RUNTIME_SOURCE")
    verified_zipfs9=mode in ("native-verified-zipfs9",
                             "native-verified-embedded-zipfs9")
    if native_zipfs9!=verified_zipfs9:
        raise TclRuntimeError("Tcl/Tk-Laufzeit passt nicht zur Python-Version")
    if verified_zipfs9:
        rel="DLLs" if mode=="native-verified-embedded-zipfs9" else "tcl"
        expected=(Path(sys.base_prefix)/rel).resolve(strict=False)
        if Path(values["SPRITESUITE_TCL_RUNTIME_ROOT"]).resolve()!=expected:
            raise TclRuntimeError("Tcl/Tk 9-Quelle ist nicht die native Python-Laufzeit")
    if verified_zipfs9:
        # Only this process's environment is touched, never the host or
        # existing Tcl/Tk library archives; Tcl 9 uses native zipfs mounts.
        os.environ.pop("TCL_LIBRARY",None)
        os.environ.pop("TK_LIBRARY",None)
    os.environ.update(values)
    return values


def call_with_tcl_bootstrap_retries(operation, *, attempts:int=5):
    """Retry only native Tcl library bootstrap reads, not ordinary GUI errors.

    Windows/Tcl can sporadically report native I/O failures while sourcing
    intact bootstrap scripts. No widgets or application state are published
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
                         ("couldn't read" in detail and
                          any(name in detail for name in ("init.tcl", "auto.tcl", "tk.tcl"))) or
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

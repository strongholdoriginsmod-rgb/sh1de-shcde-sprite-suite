"""Read-only host/runtime compatibility report.

Do not infer in-game/Noesis/Unity native ABI support from a Steam BuildID.
No installer, file modification, SDK download or target game writes.
"""
from __future__ import annotations

import argparse
from importlib import metadata, util
import json
import os
from pathlib import Path
import platform
import re
import shutil
import struct
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
# Python 3.15 is supported at *source/API* level. The redistributable
# Windows-x64 CPython 3.13 runtime remains the production-tested target.
SOURCE_MINOR=(13,14,15)
LOCK_PATTERN=re.compile(r"(?m)^([a-zA-Z][a-zA-Z0-9._-]*)==([0-9][a-zA-Z0-9._-]*)")


def _result(name,status,detail,de="",en=""):
    assert status in ("ready","limited","blocked","unverified")
    return {"name":name,"status":status,"detail":str(detail),
            "recommendation_de":de,"recommendation_en":en}


def _dependencies(root:Path,py_minor:int):
    lock=root/f"requirements-py3{py_minor}-win_amd64.lock"
    if not lock.is_file():
        suffix=("Source-level Python 3.15 is supported, but no audited "
                "Windows-x64 dependency wheel lock exists yet"
                if py_minor==15 else "No matching lock file: "+lock.name)
        return _result("Python dependencies","limited",suffix,
             "Kein ungeprüftes Paket als vollständig kompatibel freigeben. "
             "Benötigte Wheels und Tcl/Qt unter der Zielversion getrennt prüfen.",
             "Do not certify unverified packages. Validate wheels and Tcl/Qt "
             "against this Python version separately.")
    try:
        pins=LOCK_PATTERN.findall(lock.read_text("utf-8"))
        if not pins:raise ValueError("Lock file has no version pins")
        mismatches=[]
        for package,version in pins:
            try:found=metadata.version(package)
            except metadata.PackageNotFoundError:found="not installed"
            if found!=version:mismatches.append(f"{package}: expected {version}, found {found}")
        if mismatches:
            return _result("Python dependencies","limited",
                    f"{len(mismatches)}/{len(pins)} mismatch: "+"; ".join(mismatches[:5]),
                    "Die im Paket enthaltene Laufzeit vollständig entpacken; keine Teilinstallation mischen.",
                    "Fully extract the bundled runtime; do not mix partial installations.")
        return _result("Python dependencies","ready",
                       f"{len(pins)}/{len(pins)} versions match {lock.name}")
    except (OSError,UnicodeError,ValueError) as exc:
        return _result("Python dependencies","limited",str(exc))


def _tcl(root:Path):
    try:
        import tkinter
        major=float(tkinter.TclVersion)
        version=float(tkinter.TkVersion)
        if major!=version or major not in (8.6,9.0):
            return _result("Tcl/Tk","limited",
                    f"Tcl {major} and Tk {version} are not a supported pair")
        if major==8.6:
            bundled_home=root/"python"
            script=bundled_home/"tcl"/"tcl8.6"/"init.tcl"
            tk_script=bundled_home/"tcl"/"tk8.6"/"tk.tcl"
            if (script.is_file() and tk_script.is_file()
                    and not script.is_symlink() and not tk_script.is_symlink()):
                return _result("Tcl/Tk","ready","Bundled Tcl/Tk 8.6 scripts present")
            # When a bundled Python directory exists, falling back to the
            # inspecting PC's global Tcl/Tk would falsely approve a broken
            # portable extraction that will fail on a different Windows PC.
            if bundled_home.exists() or bundled_home.is_symlink():
                return _result("Tcl/Tk","limited",
                    "Bundled Tcl/Tk 8.6 scripts missing or invalid",
                    "Portable-Archiv vollständig neu entpacken.",
                    "Re-extract the complete portable archive.")
            # Source-only Python can legitimately use its own Tcl scripts.
            if (Path(sys.base_prefix)/"tcl"/"tcl8.6"/"init.tcl").is_file():
                return _result("Tcl/Tk","ready","System Tcl/Tk 8.6 scripts present")
            return _result("Tcl/Tk","limited","Tcl/Tk scripts not found",
                "Den Portable-Ordner vollständig entpacken.",
                "Fully extract the portable directory.")
        # Tcl 9 can use separate ZIP libraries (3.14) or DLL-embedded
        # ZIPFS (3.15). A damaged bundled Python must never be certified
        # using the examiner PC\u0027s unrelated system interpreter.
        bundled=root/"python"
        if bundled.exists() or bundled.is_symlink():
            if bundled.resolve(strict=False)!=Path(sys.base_prefix).resolve(strict=False):
                return _result("Tcl/Tk","limited",
                    "Bundled Python Tcl/Tk not running under the inspected interpreter",
                    "Mitgeliefertes Python statt System-Python verwenden.",
                    "Use the bundled Python interpreter, not a system Python.")
        from suite_tcl_runtime import locate_bundled_tcl
        path=locate_bundled_tcl(root)
        return _result("Tcl/Tk","ready","Tcl/Tk 9 zipfs: "+str(path))
    except (ImportError,RuntimeError,OSError,ValueError) as exc:
        return _result("Tcl/Tk","limited",str(exc),
            "Die Laufzeit- und Tcl-ZIP-Dateien prüfen.",
            "Check bundled runtime and Tcl ZIPs.")


def _qt():
    if not util.find_spec("PySide6"):
        return _result("Qt Sandbox","limited","PySide6 not installed",
            "Für die eingebettete 3D-/Spielvorschau die vollständige Portable-Ausgabe verwenden.",
            "Use the complete portable build for the embedded game preview.")
    # A module lookup alone cannot detect broken DLL/plugin dependencies.
    # A child process isolates Qt startup from the Tk application and never
    # opens a real window or touches the original game.
    env=os.environ.copy()
    env["QT_QPA_PLATFORM"]="offscreen"
    command=[sys.executable,"-c",
        "from PySide6.QtWidgets import QApplication; "
        "a=QApplication([]); print(\u0027QT_WIDGETS_READY\u0027); a.quit()"]
    try:
        result=subprocess.run(command,capture_output=True,text=True,
            encoding="utf-8",errors="replace",timeout=12,env=env)
    except (OSError,subprocess.TimeoutExpired) as exc:
        return _result("Qt Sandbox","limited",str(exc))
    if result.returncode==0 and "QT_WIDGETS_READY" in result.stdout:
        return _result("Qt Sandbox","ready",
            "QtWidgets and offscreen platform plugin launched successfully")
    return _result("Qt Sandbox","limited",
        "Qt child process failed: "+(result.stderr.strip() or result.stdout.strip())[:180],
        "Qt- und VC-Laufzeitdateien aus dem verifizierten Portable-Paket verwenden.",
        "Use the verified portable Qt and VC runtime files.")


def _manual_pdf(root:Path):
    path=root/"docs"/"SPRITESUITE_ILLUSTRIERTES_HANDBUCH.pdf"
    try:
        if (path.is_symlink() or not path.is_file()
                or not 10000 <= path.stat().st_size <= 30*1024*1024):
            raise ValueError("missing, linked, or implausible PDF")
        with path.open("rb") as stream:
            header=stream.read(8)
            stream.seek(-1024,os.SEEK_END)
            end=stream.read()
        if not header.startswith(b"%PDF-") or b"%%EOF" not in end:
            raise ValueError("PDF header or trailer is invalid")
        return _result("Illustrated PDF manual","ready",
            "14-page illustrated PDF manual found (header/trailer valid)")
    except (OSError,ValueError) as exc:
        return _result("Illustrated PDF manual","limited",str(exc),
            "Das vollständige Portable-Paket einschließlich PDF neu entpacken.",
            "Re-extract the complete portable package, including the PDF.")


def _dotnet():
    executable=shutil.which("dotnet")
    if not executable:
        return _result(".NET SDK (optional)","limited","Not found on PATH",
          "Nur für bestimmte native C#-Entwicklungswerkzeuge nötig; nicht für den normalen GUI-Start.",
          "Required by some native C# development tools, not normal GUI startup.")
    try:
        result=subprocess.run([executable,"--list-sdks"],capture_output=True,
              text=True,encoding="utf-8",errors="replace",timeout=8)
        versions=re.findall(r"(?m)^([0-9]+)\.[0-9]+\.[0-9]+",result.stdout)
        ok=result.returncode==0 and any(int(n)>=8 for n in versions)
        return _result(".NET SDK (optional)","ready" if ok else "limited",
            result.stdout.strip()[:350] if result.stdout.strip() else "No SDK listed")
    except (OSError,subprocess.TimeoutExpired) as exc:
        return _result(".NET SDK (optional)","limited",str(exc))


def supports_source_python(major:int,minor:int,*,cpython:bool=True,bits:int=64)->bool:
    """Version policy only; wheel/runtime tests are required separately."""
    return bool(cpython and major==3 and minor in SOURCE_MINOR and bits==64)


def collect(root:Path=ROOT,*,check_steam:bool=False,
            game_root:Path|None=None) -> dict:
    root=Path(root)
    bits=struct.calcsize("P")*8
    windows=sys.platform=="win32"
    cpython=platform.python_implementation()=="CPython"
    minor=sys.version_info.minor
    machine=platform.machine().lower()
    host_x64=windows and bits==64 and machine in ("amd64","x86_64")
    pyok=supports_source_python(
        sys.version_info.major,minor,cpython=cpython,bits=bits)
    entries=[
       _result("Windows x64 host","ready" if host_x64 else "blocked",
               platform.system()+" / "+platform.machine()+f" / {bits}-bit",
               "SpriteSuite Portable ist für Windows x64 gebaut.",
               "SpriteSuite Portable targets Windows x64."),
       _result("Python runtime","ready" if pyok else "blocked",
               f"{platform.python_implementation()} {sys.version.split()[0]} / {bits}-bit",
               "CPython 3.13–3.15 x64 wird auf Quellcodeebene berücksichtigt. "
               "Nur eine passend geprüfte Tcl/Qt-/Wheel-Umgebung gilt als einsatzbereit.",
               "CPython 3.13–3.15 x64 has source-level support. A matching "
               "tested Tcl/Qt/wheel environment is required for readiness."),
       _tcl(root),
       _dependencies(root,minor),
       _qt(),
       _manual_pdf(root),
       _result("Launcher / project files","ready" if all(
              (root/name).is_file() for name in
              ("tools/suite_universal.pyw","tools/suite_tcl_runtime.py",
               "tools/suite_demo_mode.py","VERSION")) else "limited",
               "Expected application entry points and version file"),
       _dotnet(),
       _result("Native game ABI","unverified",
               "Steam BuildID does not attest Unity/Noesis/Script Extender ABI",
               "Keinen unbekannten Spielstand automatisch freigeben. Echte Ingame- und Rollback-Abnahme erforderlich.",
               "Never approve an unknown game build automatically. Native in-game and rollback tests are required."),
    ]
    if check_steam:
        try:
            from suite_steam_compatibility import discover_steam_games
            matches=discover_steam_games()
            entries.append(_result("Local Steam discovery","ready" if matches else "limited",
                f"{len(matches)} matching game installations (read-only)",
                "Ein gefundenes Spiel ist noch keine bestätigte ABI-Kompatibilität.",
                "A discovered installation is not proof of native ABI compatibility."))
        except (OSError,ValueError,ImportError) as exc:
            entries.append(_result("Local Steam discovery","limited",
                                   f"Read-only discovery error: {exc}"))
    game_structure=None
    if game_root is not None:
        try:
            from suite_native_game_capabilities import inspect
            game_structure=inspect(Path(game_root))
            count=game_structure["noesis_grid_target_count"]
            found=all(item["present"] for item in game_structure[
                "sha_pinned_current_references"].values())
            entries.append(_result("Game XAML/Noesis source structure",
                "ready" if count>0 and found else "limited",
                f"{count} unique XAML Grid targets; Script Extender "
                f"{game_structure['script_extender_version'] or 'not installed'}; "
                "source structure only, never proof of native gameplay",
                "Die XAML-Quelle wurde lesend geprüft; native Hooks und Pixel "
                "sind weiterhin gesondert im laufenden Spiel nachzuweisen.",
                "XAML source structure was inspected read-only. Native hooks "
                "and actual game pixels still require in-game proof."))
        except (OSError,ValueError,RuntimeError,ImportError) as exc:
            entries.append(_result("Game XAML/Noesis source structure",
                "limited","Read-only source inspection failed: "+str(exc)[:240],
                "Spiel- und Script-Extender-Daten auf Vollständigkeit prüfen.",
                "Verify the installed game and Script Extender files."))
    readiness={e["name"]:e["status"] for e in entries}
    host_ready=readiness.get("Windows x64 host")=="ready" and readiness.get("Python runtime")=="ready"
    core_ready=host_ready and readiness.get("Tcl/Tk")=="ready" and readiness.get("Python dependencies")=="ready"
    qt_ready=core_ready and readiness.get("Qt Sandbox")=="ready"
    return {"schema":"sprite-suite.compatibility-readonly.v1",
            "suite_version":(root/"VERSION").read_text("utf8").strip() if
                   (root/"VERSION").is_file() else "unknown",
            "python_executable":str(Path(sys.executable)),
            "root":str(root),
            "checks":entries,
            "host_ready":host_ready,
            "core_ui_ready":core_ready,
            "qt_sandbox_ready":qt_ready,
            "python_source_supported":pyok,
            "python_distribution_tier":(
                 ("experimental_local_hash_locked"
                  if readiness.get("Python dependencies")=="ready"
                  else "experimental_source_needs_wheel_lock") if minor==15
                 else "tested_with_version_specific_lock" if
                       readiness.get("Python dependencies")=="ready"
                 else "unverified_source_dependencies"),
            "game_structural_inspection":game_structure,
            "native_game_approved":False,
            "writes_to_game":False}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,default=ROOT)
    parser.add_argument("--steam",action="store_true",
                       help="Discover Steam installations read-only")
    parser.add_argument("--game-root",type=Path,
                       help="Inspect a chosen installed game/SE XAML read-only")
    parser.add_argument("--json",action="store_true")
    opts=parser.parse_args(argv)
    result=collect(opts.root,check_steam=opts.steam,
                   game_root=opts.game_root)
    if opts.json:
        print(json.dumps(result,ensure_ascii=False,indent=2))
    else:
        print("SpriteSuite - read-only compatibility report")
        for entry in result["checks"]:
            print(f"{entry['name']}: {entry['status']} - {entry['detail']}")
        print("Native game support is NOT approved by this report.")
    return 0 if result["host_ready"] else 2


if __name__=="__main__":
    raise SystemExit(main())

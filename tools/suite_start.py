"""Portabler Start der Universal-Suite / Portable start of the universal suite.

Wird von ``Suite starten.cmd`` mit dem mitgelieferten Python aufgerufen:

1. ``.venv/pyvenv.cfg`` auf das mitgelieferte Python am aktuellen Ablageort
   zeigen lassen (die Umgebung ist damit verschiebbar).
2. Mitgelieferte Werkzeuge eintragen, sofern noch nichts Gueltiges eingetragen
   ist: Unity 2021.3.45f2 und ein kompatibles stabiles .NET SDK
   (config/toolchains.local.json).
3. Die Suite ohne Konsole starten (``--konsole`` zeigt die Ausgabe).

Nichts davon veraendert ein Spiel; es werden nur Dateien im Paket angepasst.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
from stronghold_europe_de.sdk_toolchain import (
    find_dotnet_sdk, installed_sdk_versions, resolve_dotnet_directory,
)
from stronghold_europe_de.suite_setup import (
    inspect_toolchain_hints, save_local_setup,
)
PACKAGE = PROJECT.parent
# Mitgeliefertes Python: im Repository-Aufbau (Zweig "komplett") liegt es im
# Projektordner, im entpackten Komplettpaket daneben.
PYTHON_HOME = next((p for p in (PROJECT / "python", PACKAGE / "python") if (p / "python.exe").is_file()),
                   PROJECT / "python")
VENV = PROJECT / ".venv"


def fix_venv() -> None:
    cfg = VENV / "pyvenv.cfg"
    if not PYTHON_HOME.joinpath("python.exe").is_file():
        return
    lines = [
        f"home = {PYTHON_HOME}",
        "include-system-site-packages = false",
        "version = 3.13.15",
        f"executable = {PYTHON_HOME / 'python.exe'}",
        f"command = {PYTHON_HOME / 'python.exe'} -m venv {VENV}",
    ]
    wanted = "\n".join(lines) + "\n"
    if not cfg.is_file() or cfg.read_text(encoding="utf-8") != wanted:
        cfg.write_text(wanted, encoding="utf-8")
    site = VENV / "Lib" / "site-packages"
    pth = site / "stronghold_europe_universal.pth"
    if site.is_dir() and not pth.is_file():
        pth.write_text("../../../src\n", encoding="utf-8")


def fix_toolchains() -> None:
    """Supplement missing portable hints without deleting user configurations."""
    settings, warnings = inspect_toolchain_hints(PROJECT)
    if warnings:
        for warning in warnings:
            print("WARNUNG: " + warning, file=sys.stderr)
        return

    unity = PROJECT / "work" / "toolchains" / "unity-2021.3.45f2" / "Editor" / "Unity.exe"
    dotnet = find_dotnet_sdk(PROJECT)
    additions = {}
    current_unity=settings.get("unity_editor") or ""
    if unity.is_file() and (not current_unity or not Path(current_unity).is_file()):
        additions["unity"] = unity
    current_dotnet=settings.get("dotnet_directory") or ""
    sdk_valid=False
    if current_dotnet:
        try:
            sdk_valid=bool(installed_sdk_versions(
                resolve_dotnet_directory(Path(current_dotnet))
            ))
        except (OSError, ValueError, RuntimeError):
            pass
    if dotnet is not None and not sdk_valid:
        additions["dotnet"] = dotnet
    if additions:
        try:
            result = save_local_setup(PROJECT, **additions)
            for path in result["backup_files"]:
                print("Portable Werkzeuge aktualisiert; alte Einstellungen gesichert:", path)
        except (OSError, ValueError) as exc:
            print("WARNUNG: Portable Werkzeugpfade nicht gespeichert: " + str(exc),
                  file=sys.stderr)


def portable_self_test() -> int:
    """Validate the bundled interpreter without opening the GUI or a game."""
    import subprocess
    fix_venv()
    executable = VENV / "Scripts" / "python.exe"
    if not executable.is_file():
        print("PORTABLE_ERROR: Bundled .venv/Scripts/python.exe is missing", file=sys.stderr)
        return 3
    code = (
        "import sys, tkinter, PIL, UnityPy, PySide6; "
        "from stronghold_europe_de.sdk_toolchain import find_dotnet_sdk; "
        "assert sys.version_info[:2] == (3, 13); "
        "print('PORTABLE_READY=1'); "
        "print('PYTHON='+sys.version.split()[0]); "
        "print('PIL='+PIL.__version__)"
    )
    env = dict(os.environ, PYTHONPATH=str(PROJECT / "src"),
               PYTHONDONTWRITEBYTECODE="1")
    try:
        return subprocess.run(
            [str(executable), "-c", code], cwd=PROJECT, env=env,
            timeout=45, check=False,
        ).returncode
    except (OSError, subprocess.TimeoutExpired) as exc:
        print("PORTABLE_ERROR:", exc, file=sys.stderr)
        return 4


def main() -> int:
    if "--self-test" in sys.argv:
        return portable_self_test()
    if "--help" in sys.argv or "-h" in sys.argv:
        print(__doc__)
        return 0
    fix_venv()
    fix_toolchains()
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PROJECT / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    dotnet = find_dotnet_sdk(PROJECT)
    if dotnet is not None:
        env["PATH"] = str(dotnet) + os.pathsep + env.get("PATH", "")
        env.setdefault("DOTNET_CLI_TELEMETRY_OPTOUT", "1")
    unity = PROJECT / "work" / "toolchains" / "unity-2021.3.45f2" / "Editor" / "Unity.exe"
    if unity.is_file():
        env.setdefault("STRONGHOLD_EUROPE_UNITY_EDITOR", str(unity))
    console = "--konsole" in sys.argv
    interpreter = VENV / "Scripts" / ("python.exe" if console else "pythonw.exe")
    if not interpreter.is_file():
        interpreter = Path(sys.executable)
    args = [str(interpreter), str(PROJECT / "tools" / "suite_universal.pyw")]
    if console:
        return subprocess.call(args, cwd=PROJECT, env=env)
    subprocess.Popen(args, cwd=PROJECT, env=env,
                     creationflags=getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

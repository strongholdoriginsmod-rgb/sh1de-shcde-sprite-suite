"""Frozen-capable entry point for the Stronghold Europe modding application.

The graphical application is deliberately only an orchestrator.  In source
mode it starts every existing tool through the project virtual environment. In
the packaged application it starts this executable again with ``--tool-run``;
this module then executes the same checked script or package CLI in an isolated
process.  No validation rule is reimplemented in the GUI or in this host.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import runpy
import sys
from typing import Iterable


APP_NAME = "StrongholdEuropeModding"
ROOT_ENV = "STRONGHOLD_EUROPE_PROJECT_ROOT"
ALLOWED_TOOLS = frozenset(
    {
        "groups.py",
        "locale_text.py",
        "pin_digests.py",
        "pin_xaml.py",
        "show_installed.py",
        "sprites.py",
        "tile_objects.py",
        "ui_atlas.py",
        "vegetation_gen.py",
    }
)
ALLOWED_MODULES = frozenset({"stronghold_europe_de"})


class ModdingHostError(RuntimeError):
    """The executable cannot safely resolve or dispatch the local project."""


def _is_project_root(path: Path) -> bool:
    return all(
        marker.is_file()
        for marker in (
            path / "tools" / "suite.pyw",
            path / "profiles" / "europe-production.json",
            path / "src" / "stronghold_europe_de" / "__init__.py",
        )
    )


def _ancestors(candidate: Path) -> Iterable[Path]:
    resolved = candidate.resolve()
    if resolved.is_file():
        resolved = resolved.parent
    yield resolved
    yield from resolved.parents


def find_project_root(candidates: Iterable[Path] | None = None) -> Path:
    """Find the checked-out project without trusting the temporary bundle path."""

    configured = os.environ.get(ROOT_ENV)
    if configured:
        selected = Path(configured).resolve()
        if not _is_project_root(selected):
            raise ModdingHostError(
                f"{ROOT_ENV} zeigt nicht auf ein StrongholdEuropeDE-Projekt: {selected}"
            )
        return selected

    if candidates is None:
        candidates = (
            Path(sys.executable),
            Path.cwd(),
            Path(__file__),
        )
    seen: set[Path] = set()
    for candidate in candidates:
        for path in _ancestors(candidate):
            if path in seen:
                continue
            seen.add(path)
            if _is_project_root(path):
                return path
    raise ModdingHostError(
        "StrongholdEuropeDE-Projekt nicht gefunden. Die EXE muss innerhalb des "
        "Projektordners liegen oder STRONGHOLD_EUROPE_PROJECT_ROOT muss gesetzt sein."
    )


def _exit_code(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    print(str(value), file=sys.stderr)
    return 1


def run_tool(project_root: Path, tokens: list[str]) -> int:
    """Run one allow-listed project tool with its original ``__main__`` path."""

    if not tokens:
        raise ModdingHostError("--tool-run benötigt einen Werkzeugaufruf")
    project_root = project_root.resolve()
    source_root = project_root / "src"
    sys.path.insert(0, str(source_root))
    os.environ[ROOT_ENV] = str(project_root)
    os.chdir(project_root)

    try:
        if tokens[0] == "-m":
            if len(tokens) < 2 or tokens[1] not in ALLOWED_MODULES:
                raise ModdingHostError(
                    f"Modul ist für die Modding-App nicht freigegeben: {tokens[1:2]}"
                )
            module = tokens[1]
            sys.argv = [module, *tokens[2:]]
            try:
                runpy.run_module(module, run_name="__main__", alter_sys=True)
            except SystemExit as exc:
                return _exit_code(exc.code)
            return 0

        requested = Path(tokens[0])
        name = requested.name
        if name not in ALLOWED_TOOLS:
            raise ModdingHostError(f"Werkzeug ist nicht freigegeben: {name}")
        expected = (project_root / "tools" / name).resolve()
        actual = requested.resolve() if requested.is_absolute() else expected
        if actual != expected or not expected.is_file():
            raise ModdingHostError(
                f"Werkzeugpfad liegt nicht im Projekt: {actual} (erwartet {expected})"
            )
        sys.argv = [str(expected), *tokens[1:]]
        try:
            runpy.run_path(str(expected), run_name="__main__")
        except SystemExit as exc:
            return _exit_code(exc.code)
        return 0
    finally:
        try:
            sys.path.remove(str(source_root))
        except ValueError:
            pass


def self_test(project_root: Path) -> int:
    """Prove the frozen runtime contains every dependency needed by the GUI."""

    import tkinter  # noqa: F401
    import PIL  # noqa: F401
    import UnityPy  # noqa: F401
    import UnityPy.classes  # noqa: F401 - exercises dynamic class/fmod imports
    import archspec.cpu
    import fmod_toolkit  # noqa: F401 - imports pyfmodex and loads the bundled DLL
    from fmod_toolkit.importer import get_fmod_path_for_system
    import stronghold_europe_de  # noqa: F401

    # UnityPy asks archspec for the current CPU when it loads native codecs.
    # Merely importing archspec does not read its package JSON files, so make
    # the frozen self-test exercise that data path explicitly.
    cpu = archspec.cpu.host()
    if not cpu.name:
        raise RuntimeError("archspec konnte die lokale CPU nicht bestimmen")
    fmod_path = Path(get_fmod_path_for_system()).resolve()
    if not fmod_path.is_file():
        raise RuntimeError(f"Gebündelte FMOD-Laufzeit fehlt: {fmod_path}")

    result = {
        "app": APP_NAME,
        "project_root": str(project_root),
        "frozen": bool(getattr(sys, "frozen", False)),
        "python": sys.version.split()[0],
        "cpu": cpu.name,
        "fmod": str(fmod_path),
        "tools": sorted(ALLOWED_TOOLS),
        "status": "ok",
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0


def _hide_console() -> None:
    """Hide the console only for the interactive GUI, never for tool children."""

    if os.name != "nt":
        return
    try:
        import ctypes

        handle = ctypes.windll.kernel32.GetConsoleWindow()
        if handle:
            ctypes.windll.user32.ShowWindow(handle, 0)
    except Exception:
        pass


def _show_startup_error(message: str) -> None:
    if os.name == "nt":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(
                0, message, "Stronghold Europe – Modding-App", 0x10
            )
            return
        except Exception:
            pass
    print(message, file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        project_root = find_project_root()
        os.environ[ROOT_ENV] = str(project_root)
        if args[:1] == ["--self-test"]:
            return self_test(project_root)
        if args[:1] == ["--tool-run"]:
            return run_tool(project_root, args[1:])
        if args:
            raise ModdingHostError(f"Unbekannte App-Argumente: {args}")

        _hide_console()
        suite = project_root / "tools" / "suite_center.pyw"
        sys.argv = [str(suite)]
        runpy.run_path(str(suite), run_name="__main__")
        return 0
    except ModdingHostError as exc:
        _show_startup_error(str(exc))
        return 2
    except SystemExit as exc:
        return _exit_code(exc.code)
    except Exception as exc:
        # A frozen GUI otherwise disappears without context. Keep the full
        # traceback on stderr for redirected diagnostics and show a concise
        # Windows dialog to a user who started the EXE by double-clicking.
        import traceback

        traceback.print_exc()
        _show_startup_error(f"Die Modding-App konnte nicht gestartet werden:\n\n{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

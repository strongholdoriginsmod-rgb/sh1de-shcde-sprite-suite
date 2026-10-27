"""Safe, atomic PNG exports from Sandbox Studio; never touch game sources."""
from __future__ import annotations

import os
from pathlib import Path
import tempfile

PNG_SIGNATURE = bytes((137, 80, 78, 71, 13, 10, 26, 10))


class ExportTargetError(ValueError):
    """The chosen path is unsafe or is not a PNG export destination."""


def _protected_roots(map_root, map_file):
    """Protect the map directory and the containing Unity *_Data folder."""
    for source in (map_root, map_file):
        if source is None:
            continue
        source = Path(source).resolve(strict=False)
        folder = source.parent if source.suffix.lower() == ".map" else source
        yield folder
        for parent in (folder, *folder.parents):
            if parent.name.lower().endswith("_data"):
                yield parent
                break


def validate_png_destination(target, *, project_root, map_root=None, map_file=None):
    path = Path(target)
    if path.suffix.lower() != ".png":
        raise ExportTargetError("Nur .png-Exportdateien sind erlaubt; Spiel- und JSON-Dateien bleiben geschützt.")
    if path.is_symlink():
        raise ExportTargetError("Verknüpfte Zieldateien dürfen nicht überschrieben werden.")
    resolved = path.resolve(strict=False)
    if (map_root is not None and Path(map_root).resolve(strict=False) ==
            Path(project_root).resolve(strict=False)):
        map_root = None  # A test/workspace root is not a game installation.
    if any(resolved.is_relative_to(protected) for protected in
           _protected_roots(map_root, map_file)):
        raise ExportTargetError("Dieser Pfad liegt im Originalspiel/Kartenordner; Export abgebrochen.")
    if resolved.exists():
        if not resolved.is_file():
            raise ExportTargetError("Das ausgewählte PNG-Ziel ist keine reguläre Datei.")
        safe_work = (Path(project_root) / "work").resolve(strict=False)
        if not resolved.is_relative_to(safe_work):
            raise ExportTargetError(
                "Vorhandene Dateien außerhalb von work/ werden nicht überschrieben. "
                "Bitte einen neuen PNG-Dateinamen wählen."
            )
        try:
            with resolved.open("rb") as source:
                if source.read(8) != PNG_SIGNATURE:
                    raise ExportTargetError("Bestehende Datei ist kein gültiger PNG-Export.")
        except OSError as exc:
            raise ExportTargetError(str(exc)) from exc
    return path


def atomic_export_png(target, writer, *, project_root, map_root=None, map_file=None):
    """Writer gets a temporary .png path; replace only after success."""
    path = validate_png_destination(
        target, project_root=project_root, map_root=map_root, map_file=map_file
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix="." + path.stem + "-", suffix=".png", dir=path.parent
    )
    os.close(fd)
    try:
        result = writer(Path(temporary))
        if result is False:
            raise ExportTargetError("Die Ansicht konnte nicht als PNG geschrieben werden.")
        with open(temporary, "rb") as output:
            if output.read(8) != PNG_SIGNATURE:
                raise ExportTargetError("Der Export lieferte keine gültigen PNG-Bilddaten.")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return path

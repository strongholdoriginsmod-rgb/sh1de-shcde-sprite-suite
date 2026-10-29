"""Relocatable paths for HUD/menu metadata with conservative legacy migration.

The project itself lives under work/<name>. Layouts, export manifests,
snapshots, revisions, and QA receipts remain OUTSIDE the package source.
Their directory identifier must not depend on the absolute Suite location.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import os
import shutil
import tempfile
from typing import Callable


MAX_FILES = 25000
MAX_BYTES = 2 * 1024 ** 3


def _linked(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()


def _digest_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _legacy_copy(base: Path, legacy: Path, portable: Path,
                 error: type[Exception]) -> None:
    """Copy and verify legacy bytes before atomic directory rename.

    Never remove or edit the legacy folder. Refuse linked/reparse entries,
    unbounded archives and changes to any source file during migration.
    """
    if _linked(base) or _linked(legacy) or _linked(portable):
        raise error("Verknüpfte Metadatenordner werden nicht übernommen.")
    if portable.exists():
        raise error("Portabler Metadatenordner wurde zwischenzeitlich erstellt.")
    base.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".metadata-migration-", dir=base))
    total = 0
    count = 0
    try:
        for entry in sorted(legacy.rglob("*")):
            if _linked(entry):
                raise error("Alte Metadaten enthalten eine Dateiverknüpfung.")
            relative = entry.relative_to(legacy)
            output = staging / relative
            if entry.is_dir():
                output.mkdir(parents=True, exist_ok=True)
                continue
            if not entry.is_file():
                raise error("Unbekannter Dateityp in alten Projektmetadaten.")
            count += 1
            before = entry.stat()
            total += before.st_size
            if count > MAX_FILES or total > MAX_BYTES:
                raise error("Zu viele oder zu große Metadaten für automatische Übernahme.")
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(entry, output, follow_symlinks=False)
            after = entry.stat()
            if ((before.st_size, before.st_mtime_ns) !=
                    (after.st_size, after.st_mtime_ns)):
                raise error("Alte Metadatendatei wurde beim Kopieren verändert.")
            if _digest_file(entry) != _digest_file(output):
                raise error("Prüfsumme beim Übernehmen alter Metadaten falsch.")
        if portable.exists() or _linked(portable):
            raise error("Neuer Metadatenordner wurde zwischenzeitlich erstellt.")
        staging.rename(portable)
    except OSError as exc:
        raise error("Übernahme alter Projektmetadaten fehlgeschlagen: " + str(exc)) from exc
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def metadata_dir(root: Path, *, work: Path, folder: str,
                 sha: Callable[[bytes], str],
                 error: type[Exception]) -> Path:
    """Return stable project metadata path; migrate old data safely if present.

    A project transferred AFTER relocating its old absolute metadata hash may
    need an explicit restore; this function never guesses legacy ownership.
    """
    work = Path(work)
    root = Path(root)
    if _linked(work):
        raise error("Verknüpfter Arbeitsordner ist nicht zugelassen.")
    work = work.resolve()
    if _linked(root):
        raise error("Verknüpfter Projektordner ist nicht zugelassen.")
    resolved = root.resolve()
    if (not resolved.is_dir() or resolved == work
            or not resolved.is_relative_to(work)):
        raise error("Projekt muss innerhalb SpriteSuite/work/ liegen.")
    node = root
    while node != work and node != node.parent:
        if _linked(node):
            raise error("Projektpfad enthält eine unzulässige Verknüpfung.")
        node = node.parent

    base = work / folder
    if _linked(base) or (base.exists() and not base.is_dir()):
        raise error("Ungültiger Metadaten-Speicherort.")
    relative = resolved.relative_to(work).as_posix().casefold()
    portable = base / ("portable-" + sha(relative.encode("utf8"))[:24])
    legacy = base / sha(str(resolved).casefold().encode("utf8"))[:24]
    if _linked(portable) or _linked(legacy):
        raise error("Verknüpfte Projektmetadaten sind nicht zugelassen.")
    if portable.exists():
        if not portable.is_dir():
            raise error("Portabler Metadatenordner ist keine gültige Ablage.")
        return portable
    if legacy.is_dir():
        _legacy_copy(base, legacy, portable, error)
    return portable

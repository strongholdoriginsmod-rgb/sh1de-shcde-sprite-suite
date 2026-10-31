"""Publish a related set of generated files without leaving mixed outputs.

All generation happens outside the destination. Publication snapshots existing
files and re-checks their hashes. A regular Python or disk-write failure rolls
back only byte-exact writes owned by this transaction. This cannot make a
multi-file commit power-loss atomic; do not call it a database transaction.
"""
from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path
import shutil
import tempfile

from suite_windows_paths import is_link_or_reparse, is_reserved_windows_component


class OutputConflictError(RuntimeError):
    """A user file changed or a publication was only partly recoverable."""


def _sha(path: Path) -> str:
    h = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _state(path: Path) -> str | None:
    if is_link_or_reparse(path):
        raise OutputConflictError(f"Verknüpfte Ausgabedatei: {path}")
    if not path.exists():
        return None
    if not path.is_file():
        raise OutputConflictError(f"Kein regulärer Ausgabepfad: {path}")
    return _sha(path)


class OutputBatch:
    """Prepare in a private directory, then publish with guarded rollback.

    Use stage(name) only for flat filenames owned by this tool; foreign files in
    an already existing destination are never removed. The output directory
    itself is created only after preparation finishes successfully.
    """

    def __init__(self, destination: Path):
        self.destination = Path(destination)
        self._stage: Path | None = None
        self.recovery_directory: Path | None = None
        self._names: list[str] = []
        self._folded: set[str] = set()
        self._initial: dict[str, str | None] = {}
        self._published = False

    def __enter__(self) -> "OutputBatch":
        parent = self.destination.parent
        if any(is_link_or_reparse(item) for item in (parent, *parent.parents)) or is_link_or_reparse(self.destination):
            raise OutputConflictError("Verknüpfter Ausgabeordner")
        if self.destination.exists() and not self.destination.is_dir():
            raise OutputConflictError("Ausgabeziel ist keine Verzeichnis")
        parent.mkdir(parents=True, exist_ok=True)
        self._stage = Path(tempfile.mkdtemp(
            prefix=".spritesuite-output-", dir=parent
        ))
        (self._stage / "proposed").mkdir()
        (self._stage / "original").mkdir()
        return self

    def stage(self, filename: str) -> Path:
        if self._stage is None or self._published:
            raise OutputConflictError("Ausgabetransaktion nicht mehr offen")
        if (not isinstance(filename, str) or not filename
                or len(filename) > 180 or is_reserved_windows_component(filename)
                or filename in {".", ".."}
                or Path(filename).name != filename):
            raise OutputConflictError("Unsicherer Ausgabedateiname")
        folded = filename.casefold()
        if folded in self._folded:
            raise OutputConflictError("Ausgabedatei ist doppelt: " + filename)
        # Detect changes that occur *while* we generate a full atlas or report.
        self._initial[filename] = _state(self.destination / filename)
        self._names.append(filename)
        self._folded.add(folded)
        return self._stage / "proposed" / filename

    def publish(self) -> None:
        if self._stage is None or self._published:
            raise OutputConflictError("Ausgabetransaktion nicht offen")
        target = self.destination
        if (any(is_link_or_reparse(item) for item in
                (target.parent, *target.parent.parents)) or
                is_link_or_reparse(target) or
                (target.exists() and not target.is_dir())):
            raise OutputConflictError("Ausgabeziel ist verknüpft oder keine Ordner")
        proposed = []
        for idx, name in enumerate(self._names):
            new = self._stage / "proposed" / name
            if not new.is_file() or is_link_or_reparse(new):
                raise OutputConflictError("Gestagte Ausgabedatei fehlt: " + name)
            dest = target / name
            old_hash = _state(dest)
            if old_hash != self._initial[name]:
                raise OutputConflictError("Zieldatei änderte sich während der Vorbereitung: " + str(dest))
            backup = None
            if old_hash is not None:
                backup = self._stage / "original" / f"file-{idx:05d}.backup"
                shutil.copyfile(dest, backup)
                if _state(backup) != old_hash or _state(dest) != old_hash:
                    raise OutputConflictError("Zieldatei änderte sich beim Sichern")
            proposed.append((dest, new, backup, old_hash, _sha(new)))
        # Inspect all outputs before any destination file is replaced.
        for dest, _new, _backup, before, _after in proposed:
            if _state(dest) != before:
                raise OutputConflictError("Zieldatei wurde extern geändert: " + str(dest))
        created = False
        done = []
        try:
            if not target.exists():
                target.mkdir()
                created = True
            for record in proposed:
                dest, new, _backup, before, _after = record
                if is_link_or_reparse(target) or _state(dest) != before:
                    raise OutputConflictError("Ausgabepfad wurde extern geändert: " + str(dest))
                # Include the attempted destination in rollback inspection even
                # if the filesystem raises after a successful rename.
                done.append(record)
                os.replace(new, dest)
            self._published = True
        except Exception:
            conflicts = []
            for dest, _new, backup, old_hash, published_hash in reversed(done):
                try:
                    actual = _state(dest)
                    if actual == old_hash:
                        continue
                    if actual != published_hash:
                        conflicts.append(str(dest))  # Foreign change: preserve it.
                        continue
                    if backup is None:
                        dest.unlink()
                    else:
                        os.replace(backup, dest)
                except (OSError, OutputConflictError):
                    conflicts.append(str(dest))
            if created:
                try:
                    target.rmdir()  # Only if no user file appeared meanwhile.
                except OSError:
                    pass
            if conflicts:
                # Keep the exact backup files for supervised manual recovery;
                # deleting the stage now would destroy the user's only copy.
                self.recovery_directory = self._stage
                raise OutputConflictError(
                    "Ausgabe nicht vollständig zurückgesetzt. Fremde Änderungen "
                    "bewahrt; alte Dateien zur manuellen Wiederherstellung: "
                    + str(self._stage) + "; Konflikte: " + ", ".join(conflicts)
                )
            raise

    def __exit__(self, *_unused):
        if self._stage is None:
            return
        if self.recovery_directory is None:
            # This is our unique temporary directory, not a user project.
            # If it was replaced by a linked path, do not follow the link.
            if self._stage.is_dir() and not is_link_or_reparse(self._stage):
                shutil.rmtree(self._stage)
        self._stage = None

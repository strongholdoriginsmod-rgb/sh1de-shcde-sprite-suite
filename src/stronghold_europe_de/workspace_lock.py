from __future__ import annotations

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
from typing import Iterator


class WorkspaceLockError(RuntimeError):
    """A second process is already mutating the same logical resource."""


_BACKUP_SUFFIXES = (
    ".sprites-export-backup",
    ".sprites-import-backup",
    ".ui-atlas-backup",
    ".tile-roundtrip-backup",
    ".modding-app-backup",
    ".build-lock",
)
_STAGING_MARKERS = (
    ".sprites-export-",
    ".sprites-import-",
    ".ui-atlas-",
    ".tile-roundtrip-",
    ".build-staging-",
    ".modding-app.build-",
)


def stale_transaction_artifacts(project_root: Path) -> tuple[Path, ...]:
    """List known project-local active or interrupted transaction directories."""

    roots = (
        project_root / "work",
        project_root / "dist",
        project_root / "assets" / "sprites" / "derived",
        project_root / "assets" / "ui" / "derived",
    )
    found: set[Path] = set()
    for root in roots:
        root = root.resolve()
        if not root.is_dir():
            continue
        for parent, directories, _files in os.walk(root, followlinks=False):
            parent_path = Path(parent)
            for name in list(directories):
                path = parent_path / name
                if path.is_symlink():
                    directories.remove(name)
                    continue
                is_backup = name.endswith(_BACKUP_SUFFIXES)
                is_staging = name.startswith(".") and any(
                    marker in name for marker in _STAGING_MARKERS
                )
                if is_backup or is_staging:
                    resolved = path.resolve()
                    if resolved.is_relative_to(root):
                        found.add(resolved)
                    # Never descend into a potentially huge abandoned payload.
                    directories.remove(name)
    return tuple(sorted(found, key=lambda path: str(path).casefold()))


class WorkspaceLock:
    """Small cross-process, crash-releasing advisory lock.

    The OS owns the lock, not the contents of the file. A crashed process
    therefore cannot leave a false permanent lock behind; the file itself is
    retained only as a stable inode/Windows file target and diagnostic marker.
    """

    def __init__(self, path: Path, label: str) -> None:
        self.path = path
        self.label = label
        self._stream = None

    def acquire(self) -> "WorkspaceLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.path.open("a+b")
        try:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt

                # Locking zero bytes is a no-op. Ensure a stable byte exists,
                # flush it, then lock exactly that byte without waiting.
                if stream.read(1) == b"":
                    stream.seek(0)
                    stream.write(b"\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:  # pragma: no cover - production is Windows
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError) as exc:
            stream.close()
            raise WorkspaceLockError(
                f"{self.label} wird bereits von einem anderen Prozess benutzt"
            ) from exc
        self._stream = stream
        return self

    def release(self) -> None:
        stream, self._stream = self._stream, None
        if stream is None:
            return
        try:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:  # pragma: no cover - production is Windows
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        finally:
            stream.close()

    def __enter__(self) -> "WorkspaceLock":
        return self.acquire()

    def __exit__(self, _type, _value, _traceback) -> None:
        self.release()


def lock_path(work_dir: Path, resource: str) -> Path:
    digest = hashlib.sha256(resource.encode("utf-8")).hexdigest()[:20]
    return work_dir.resolve() / ".locks" / f"{digest}.lock"


@contextmanager
def exclusive_workspace_lock(
    work_dir: Path, resource: str, label: str
) -> Iterator[WorkspaceLock]:
    lock = WorkspaceLock(lock_path(work_dir, resource), label)
    with lock:
        yield lock

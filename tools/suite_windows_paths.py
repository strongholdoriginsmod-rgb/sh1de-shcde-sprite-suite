"""Windows-reserved path components, independent of host OS / Python version."""
from __future__ import annotations

import os
from pathlib import Path
import re
import stat


def is_link_or_reparse(path: Path) -> bool:
    """Reject symlinks and Windows junctions even with Python 3.11."""
    if path.is_symlink():
        return True
    junction = getattr(path, "is_junction", None)
    if junction is not None and junction():
        return True
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def is_reserved_windows_component(part: str) -> bool:
    """Apply Windows filename rules even on Python 3.11 and POSIX hosts.

    os.path.isreserved is only available on recent Windows Python builds;
    an archive created elsewhere must be checked before reaching NTFS.
    """
    native = getattr(os.path, "isreserved", None)
    if native is not None and native(part):
        return True
    if (not part or part[-1] in " ." or
            any(character in '<>:"/\\|?*' or ord(character) < 32
                for character in part)):
        return True
    stem = part.split(".", 1)[0].rstrip(" ").upper()
    return (stem in {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} or
            re.fullmatch(r"(?:COM|LPT)[1-9¹²³]", stem) is not None)


def safe_relative_file(
    root: Path, relative: str, *, allowed_suffixes: frozenset[str] | None = None
) -> Path:
    """Keep generated atlas/sprite paths inside an explicitly chosen source.

    No filesystem writes; reject traversal, DOS devices, alternate data streams,
    linked parents, malformed separators and wrong file formats before opening.
    """
    if (not isinstance(relative, str) or not relative
            or len(relative) > 230 or "\\" in relative
            or relative.startswith("/") or "\x00" in relative):
        raise ValueError("Unsicherer Dateipfad")
    parts = relative.split("/")
    if any(part in {"", ".", ".."} or part.startswith(".")
           or is_reserved_windows_component(part) for part in parts):
        raise ValueError("Unsicherer Dateipfad")
    destination = Path(root).joinpath(*parts)
    suffix = destination.suffix.lower()
    if allowed_suffixes is not None and suffix not in allowed_suffixes:
        raise ValueError("Unsicherer Dateityp")
    base = Path(root).resolve(strict=False)
    resolved = destination.resolve(strict=False)
    if resolved == base or not resolved.is_relative_to(base):
        raise ValueError("Unsicherer Exportpfad")
    node = destination
    while node != root and node != node.parent:
        if is_link_or_reparse(node):
            raise ValueError("Unsicherer verknüpfter Exportpfad")
        node = node.parent
    return destination

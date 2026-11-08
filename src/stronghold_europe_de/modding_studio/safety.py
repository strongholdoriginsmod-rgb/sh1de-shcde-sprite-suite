"""Fail-closed source handling shared by the SpriteSuite 3 offline modding tools.

No functions in this module read a game process, install files, or loosen source
identity contracts. Resource I/O is rooted in an explicit author-owned workspace.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import tempfile
import unicodedata
from typing import Any

MAX_PROJECT_BYTES = 2 * 1024 * 1024
MAX_SOURCE_BYTES = 128 * 1024 * 1024
MAX_JSON_BYTES = 8 * 1024 * 1024
_ID = re.compile(r"[a-z][a-z0-9_-]{1,63}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")


class StudioError(ValueError):
    """A required source, identity, safety, or schema proof did not hold."""


def require_id(value: object, label: str = "id") -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise StudioError(f"{label} must be lowercase ASCII [a-z][a-z0-9_-] (2..64)")
    return value


def require_sha(value: object, label: str = "sha256") -> str:
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise StudioError(f"{label} must be an exact lowercase SHA-256 digest")
    return value


def nfc(value: object, label: str, maximum: int = 512) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > maximum
        or unicodedata.normalize("NFC", value) != value
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
    ):
        raise StudioError(f"{label} must be a nonempty bounded NFC text")
    return value


def relative_path(value: object, label: str = "path") -> str:
    value = nfc(value, label, 512)
    if (
        "\\" in value or ":" in value
        or value.startswith("/") or value.endswith("/")
        or "//" in value
        or PurePosixPath(value).is_absolute()
        or PureWindowsPath(value).is_absolute()
        or any(part in ("", ".", "..") for part in value.split("/"))
    ):
        raise StudioError(f"{label} is not a safe POSIX-relative path")
    return value


def is_link(path: Path) -> bool:
    try:
        if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
            return True
        return bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400)
    except FileNotFoundError:
        return False


def canonical_root(path: Path) -> Path:
    candidate = Path(path).absolute()
    if not candidate.is_dir() or is_link(candidate):
        raise StudioError(f"workspace is missing, linked or not a directory: {candidate}")
    resolved = candidate.resolve(strict=True)
    if resolved != candidate:
        raise StudioError(f"workspace is not canonical: {candidate}")
    return resolved


def child_path(root: Path, relative: str, *, require_file: bool = False) -> Path:
    root = canonical_root(root)
    parts = relative_path(relative).split("/")
    current = root
    for part in parts:
        current = current / part
        if is_link(current):
            raise StudioError(f"linked or reparse-point resource is forbidden: {relative}")
    if current.resolve(strict=False) != current:
        raise StudioError(f"resource escaped the workspace: {relative}")
    if require_file and not current.is_file():
        raise StudioError(f"regular resource does not exist: {relative}")
    return current


def read_file(root: Path, relative: str, maximum: int = MAX_SOURCE_BYTES) -> bytes:
    file = child_path(root, relative, require_file=True)
    before = file.stat()
    if not 1 <= before.st_size <= maximum:
        raise StudioError(f"resource has unsupported byte size: {relative}")
    chunks = []
    count = 0
    with file.open("rb") as stream:
        while part := stream.read(1024 * 1024):
            count += len(part)
            if count > maximum:
                raise StudioError(f"resource exceeded its byte limit: {relative}")
            chunks.append(part)
    after = file.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise StudioError(f"resource changed while being read: {relative}")
    if count != before.st_size:
        raise StudioError(f"resource changed length during read: {relative}")
    return b"".join(chunks)


def file_sha(root: Path, relative: str) -> str:
    return sha256(read_file(root, relative)).hexdigest()


def _strict_pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise StudioError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def json_bytes(data: object) -> bytes:
    return (
        json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
        .encode("utf-8") + b"\n"
    )


def read_json(root: Path, relative: str, maximum: int = MAX_JSON_BYTES) -> Any:
    payload = read_file(root, relative, maximum=maximum)
    if payload.startswith(b"\xef\xbb\xbf"):
        raise StudioError(f"JSON must be BOM-free: {relative}")
    try:
        return json.loads(
            payload.decode("utf-8", errors="strict"),
            object_pairs_hook=_strict_pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(
                StudioError(f"nonfinite JSON number: {value}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StudioError(f"invalid UTF-8 JSON at {relative}: {exc}") from exc


def _ensure_parent(root: Path, relative: str) -> Path:
    relative_path(relative)
    destination = child_path(root, relative)
    current = canonical_root(root)
    for component in relative.split("/")[:-1]:
        current = current / component
        if is_link(current):
            raise StudioError(f"output parent is linked: {relative}")
        if not current.exists():
            current.mkdir()
        if not current.is_dir():
            raise StudioError(f"output parent is not a directory: {relative}")
    return destination


def create_file(root: Path, relative: str, payload: bytes) -> Path:
    """Atomic no-clobber output: publish only after bytes are flushed.

    The hard-link publication is exclusive on Windows and POSIX and never
    replaces a user file. A temporary file is removed even after an error.
    """
    if not isinstance(payload, bytes) or not payload:
        raise StudioError("output payload must be nonempty bytes")
    destination = _ensure_parent(root, relative)
    if destination.exists() or is_link(destination):
        raise StudioError(f"refusing to overwrite existing output: {relative}")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=destination.parent, prefix=".spritesuite-new-", delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, destination)
    except FileExistsError as exc:
        raise StudioError(f"refusing to overwrite existing output: {relative}") from exc
    except OSError as exc:
        raise StudioError(f"cannot safely publish output {relative}: {exc}") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return destination


def create_json(root: Path, relative: str, data: object) -> Path:
    return create_file(root, relative, json_bytes(data))


def read_text(root: Path, relative: str, maximum: int = MAX_SOURCE_BYTES) -> str:
    try:
        return read_file(root, relative, maximum).decode("utf-8", "strict")
    except UnicodeDecodeError as exc:
        raise StudioError(f"resource is not UTF-8: {relative}") from exc

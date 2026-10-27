"""Read the installed Unity editor identity without starting the editor."""
from __future__ import annotations

from dataclasses import dataclass
import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path
import stat


class UnityToolchainError(ValueError):
    pass


@dataclass(frozen=True)
class UnityEditorIdentity:
    executable: Path
    version: str
    revision: str
    size_bytes: int
    sha256: str


def standard_unity_editor_paths(version: str) -> tuple[Path, ...]:
    """Known Unity Hub locations, without scanning drives or starting Unity."""
    return tuple(dict.fromkeys(
        Path(directory) / "Unity" / "Hub" / "Editor" / version / "Editor" / "Unity.exe"
        for variable in ("ProgramFiles", "ProgramW6432")
        if (directory := os.environ.get(variable))
    ))


def _read_product_version(path: Path) -> str:
    if os.name != "nt":
        raise UnityToolchainError("The Unity Windows editor requires Windows.")
    library = ctypes.WinDLL("version", use_last_error=True)
    size_function = library.GetFileVersionInfoSizeW
    size_function.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
    size_function.restype = wintypes.DWORD
    read_function = library.GetFileVersionInfoW
    read_function.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID]
    read_function.restype = wintypes.BOOL
    query_function = library.VerQueryValueW
    query_function.argtypes = [wintypes.LPCVOID, wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT)]
    query_function.restype = wintypes.BOOL
    size = size_function(str(path), None)
    if not size:
        raise UnityToolchainError("Unity editor has no readable Windows version information.")
    data = ctypes.create_string_buffer(size)
    if not read_function(str(path), 0, size, data):
        raise UnityToolchainError("Cannot read Unity editor version information.")
    pointer = ctypes.c_void_p()
    length = wintypes.UINT()
    if not query_function(data, r"\VarFileInfo\Translation", ctypes.byref(pointer), ctypes.byref(length)):
        raise UnityToolchainError("Unity editor product version is missing.")
    if length.value < 4 or length.value % 4:
        raise UnityToolchainError("Unity editor version translations are malformed.")
    translations = (ctypes.c_ushort * (length.value // 2)).from_address(pointer.value)
    for position in range(0, len(translations), 2):
        key = rf"\StringFileInfo\{translations[position]:04x}{translations[position + 1]:04x}\ProductVersion"
        if query_function(data, key, ctypes.byref(pointer), ctypes.byref(length)) and length.value:
            return ctypes.wstring_at(pointer, length.value).rstrip("\0").strip()
    raise UnityToolchainError("Unity editor product version is missing.")


def _file_identity(value: os.stat_result) -> tuple[int, int, int, int]:
    return (value.st_size, value.st_mtime_ns, value.st_dev, value.st_ino)


def inspect_unity_editor(path: Path, version: str, revision: str) -> UnityEditorIdentity:
    """Validate encoder version/revision and record this executable's actual hash."""
    try:
        resolved = path.expanduser().resolve(strict=True)
        before = resolved.stat()
        if not stat.S_ISREG(before.st_mode):
            raise UnityToolchainError("Unity editor path is not a file.")
        with resolved.open("rb") as stream:
            if _file_identity(os.fstat(stream.fileno())) != _file_identity(before):
                raise UnityToolchainError("Unity editor changed while reading its identity.")
            actual_version = _read_product_version(resolved)
            if actual_version not in {f"{version}_{revision}", f"{version} ({revision})"}:
                raise UnityToolchainError(
                    f"Unity Editor {version} ({revision}) is required; actual: {actual_version}"
                )
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if (
                _file_identity(os.fstat(stream.fileno())) != _file_identity(before)
                or _file_identity(resolved.stat()) != _file_identity(before)
            ):
                raise UnityToolchainError("Unity editor changed while reading its identity.")
        return UnityEditorIdentity(resolved, version, revision, before.st_size, digest)
    except OSError as exc:
        raise UnityToolchainError(f"Cannot read Unity editor: {path}") from exc

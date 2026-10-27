from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import ntpath
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import stat
from typing import Any
from uuid import uuid4

from .asset_stream_contract import (
    BC7_INDEX_SCHEMA,
    BC7_ATLAS_BACKEND_KIND,
    INDEX_OUTPUT_PATH,
    AssetStreamContractError,
    parse_atlas_backend,
    parse_quality_policy,
)
from .config import BuilderConfig
from .validation import validate_mod


class InstallError(RuntimeError):
    """Raised when a private install cannot be completed transactionally."""


_WINDOWS_RESERVED_COMPONENTS = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_TARGET_GAME_EXECUTABLE = "Stronghold Crusader Definitive Edition.exe"
_MANIFEST_STAGING_PREFIX = ".install-manifest-"
_PRIOR_MANIFEST_PREFIX = ".prior-install-manifest-"
_FAILED_MANIFEST_PREFIX = ".failed-install-manifest-"
_UNINSTALL_MANIFEST_PREFIX = ".uninstall-manifest-"


@dataclass(frozen=True)
class _ProcessImage:
    pid: int
    path: str


def _windows_path_identity(path: str | Path) -> str:
    """Return a case-insensitive lexical identity for a Win32 image path."""

    value = os.fspath(path)
    if value.startswith("\\\\?\\UNC\\"):
        value = "\\\\" + value[8:]
    elif value.startswith("\\\\?\\"):
        value = value[4:]
    return ntpath.normcase(ntpath.normpath(value))


def _enumerate_windows_process_images(executable_name: str) -> tuple[_ProcessImage, ...]:
    """Read full image paths for live same-name processes via Win32 only.

    Name matching is merely an enumeration filter.  The caller still compares
    the full image path, so an identically named executable outside the exact
    configured game directory is not treated as the target game.
    """

    if os.name != "nt":
        return ()

    # Keep the installer dependency-free.  Toolhelp identifies the small set
    # of same-name candidates; QueryFullProcessImageNameW then provides the
    # path identity without loading or modifying either process.
    import ctypes
    from ctypes import wintypes

    class _ProcessEntry32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_ProcessEntry32W),
    ]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_ProcessEntry32W),
    ]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    invalid_handle = ctypes.c_void_p(-1).value
    if snapshot == invalid_handle:
        error = ctypes.get_last_error()
        raise InstallError(
            "Cannot enumerate Windows processes before install mutation: "
            f"WinError {error}: {ctypes.FormatError(error)}"
        )

    images: list[_ProcessImage] = []
    try:
        entry = _ProcessEntry32W()
        entry.dwSize = ctypes.sizeof(entry)
        found = bool(kernel32.Process32FirstW(snapshot, ctypes.byref(entry)))
        if not found:
            error = ctypes.get_last_error()
            if error != 18:  # ERROR_NO_MORE_FILES
                raise InstallError(
                    "Cannot read the Windows process list before install mutation: "
                    f"WinError {error}: {ctypes.FormatError(error)}"
                )
            return ()

        expected_name = executable_name.casefold()
        while found:
            if entry.szExeFile.casefold() == expected_name:
                process = kernel32.OpenProcess(0x1000, False, entry.th32ProcessID)
                if not process:
                    error = ctypes.get_last_error()
                    if error != 87:  # ERROR_INVALID_PARAMETER: process exited
                        raise InstallError(
                            "Cannot prove the path identity of same-name process "
                            f"PID {entry.th32ProcessID}: WinError {error}: "
                            f"{ctypes.FormatError(error)}"
                        )
                else:
                    try:
                        capacity = 32768
                        buffer = ctypes.create_unicode_buffer(capacity)
                        length = wintypes.DWORD(capacity)
                        if not kernel32.QueryFullProcessImageNameW(
                            process,
                            0,
                            buffer,
                            ctypes.byref(length),
                        ):
                            error = ctypes.get_last_error()
                            if error != 87:  # process exited between enumeration/query
                                raise InstallError(
                                    "Cannot prove the path identity of same-name "
                                    f"process PID {entry.th32ProcessID}: WinError "
                                    f"{error}: {ctypes.FormatError(error)}"
                                )
                        else:
                            images.append(
                                _ProcessImage(
                                    pid=int(entry.th32ProcessID),
                                    path=buffer.value,
                                )
                            )
                    finally:
                        kernel32.CloseHandle(process)
            found = bool(kernel32.Process32NextW(snapshot, ctypes.byref(entry)))
        error = ctypes.get_last_error()
        if error != 18:  # ERROR_NO_MORE_FILES
            raise InstallError(
                "Windows process enumeration changed or failed before installer "
                f"mutation: WinError {error}: {ctypes.FormatError(error)}"
            )
    finally:
        kernel32.CloseHandle(snapshot)
    return tuple(sorted(images, key=lambda item: item.pid))


def _assert_target_game_not_running(config: BuilderConfig, phase: str) -> None:
    """Fail closed only for the configured target executable's full path."""

    if config.target.game_dir is None:
        raise InstallError("Target game directory is not configured")
    expected = _lexical_absolute(
        config.target.game_dir / _TARGET_GAME_EXECUTABLE
    )
    expected_identity = _windows_path_identity(expected)
    matches = [
        image
        for image in _enumerate_windows_process_images(_TARGET_GAME_EXECUTABLE)
        if _windows_path_identity(image.path) == expected_identity
    ]
    if matches:
        pids = ", ".join(str(image.pid) for image in matches)
        raise InstallError(
            "Stronghold Crusader Definitive Edition is running from the "
            f"configured target directory during {phase} (PID {pids}): "
            f"{expected}. Close the game and retry."
        )


@dataclass(frozen=True)
class _TreeProof:
    root_identity: tuple[int, int]
    files: tuple[tuple[str, str], ...]
    directories: tuple[str, ...]
    file_identities: tuple[tuple[str, int, int], ...]
    directory_identities: tuple[tuple[str, int, int], ...]

    def file_hashes(self) -> dict[str, str]:
        return dict(self.files)

    def same_content(self, other: "_TreeProof") -> bool:
        return self.files == other.files and self.directories == other.directories

    def file_identity_map(self) -> dict[str, tuple[int, int]]:
        return {
            relative: (device, inode)
            for relative, device, inode in self.file_identities
        }

    def directory_identity_map(self) -> dict[str, tuple[int, int]]:
        return {
            relative: (device, inode)
            for relative, device, inode in self.directory_identities
        }


@dataclass(frozen=True)
class _OwnedInstallProof:
    manifest_bytes: bytes
    manifest_identity: tuple[int, int]
    tree: _TreeProof


@dataclass(frozen=True)
class _DirectFileProof:
    content: bytes
    identity: tuple[int, int]


def _lexical_absolute(path: Path) -> Path:
    """Make a path absolute without resolving a link or junction."""

    return Path(os.path.abspath(path))


def _path_lexists(path: Path) -> bool:
    return os.path.lexists(path)


def _is_link_or_junction(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if is_junction is not None and is_junction():
        return True
    try:
        attributes = path.lstat().st_file_attributes
    except (AttributeError, OSError):
        return False
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse_flag)


def _stable_stat_identity(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_mode,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
        info.st_dev,
        info.st_ino,
        int(getattr(info, "st_file_attributes", 0)),
    )


def _require_direct_directory(path: Path, label: str) -> os.stat_result:
    if not _path_lexists(path) or _is_link_or_junction(path):
        raise InstallError(f"{label} is missing, linked, junctioned, or reparsed: {path}")
    try:
        info = path.lstat()
    except OSError as exc:
        raise InstallError(f"Cannot inspect {label}: {path}: {exc}") from exc
    if not stat.S_ISDIR(info.st_mode):
        raise InstallError(f"{label} is not a direct directory: {path}")
    return info


def _safe_component(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value in {".", ".."}
        or value.endswith((" ", "."))
        or any(character in value for character in '<>:"/\\|?*')
        or any(ord(character) < 32 for character in value)
        or value.split(".", 1)[0].upper() in _WINDOWS_RESERVED_COMPONENTS
    ):
        raise InstallError(f"Unsafe {label}: {value!r}")
    return value


def _safe_owned_relative(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise InstallError(f"Unsafe {label}: {value!r}")
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if (
        posix.is_absolute()
        or windows.is_absolute()
        or bool(windows.drive)
        or posix.as_posix() != value
        or any(part in {"", ".", ".."} for part in posix.parts)
    ):
        raise InstallError(f"Unsafe {label}: {value!r}")
    for component in posix.parts:
        _safe_component(component, label)
    return value


def _assert_exact_child(path: Path, parent: Path, name: str, label: str) -> None:
    if path != _lexical_absolute(path) or path.parent != parent or path.name != name:
        raise InstallError(f"Unsafe {label} path: {path}")


def _assert_generated_child(
    path: Path,
    parent: Path,
    prefix: str,
    label: str,
) -> None:
    if (
        path != _lexical_absolute(path)
        or path.parent != parent
        or re.fullmatch(re.escape(prefix) + r"[0-9a-f]{32}", path.name) is None
    ):
        raise InstallError(f"Unsafe generated {label} path: {path}")


def _hash_direct_regular_file(path: Path, before: os.stat_result, label: str) -> str:
    flags = os.O_RDONLY | int(getattr(os, "O_BINARY", 0))
    flags |= int(getattr(os, "O_NOFOLLOW", 0))
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise InstallError(f"Cannot open direct file in {label}: {path}: {exc}") from exc
    digest = hashlib.sha256()
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
        ):
            raise InstallError(f"File changed to a link or different object in {label}: {path}")
        while chunk := os.read(descriptor, 8 * 1024 * 1024):
            digest.update(chunk)
        after_open = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    try:
        after_path = path.lstat()
    except OSError as exc:
        raise InstallError(f"File disappeared while scanning {label}: {path}") from exc
    if (
        _is_link_or_junction(path)
        or _stable_stat_identity(before) != _stable_stat_identity(after_path)
        or _stable_stat_identity(opened) != _stable_stat_identity(after_open)
    ):
        raise InstallError(f"File changed while scanning {label}: {path}")
    return digest.hexdigest()


def _scan_tree(root: Path, label: str) -> _TreeProof:
    """Hash an exact tree without following any link, junction, or reparse."""

    root = _lexical_absolute(root)
    root_info = _require_direct_directory(root, label)
    pending: list[tuple[Path, str]] = [(root, "")]
    directory_states: dict[Path, tuple[int, ...]] = {
        root: _stable_stat_identity(root_info)
    }
    files: dict[str, str] = {}
    file_identities: dict[str, tuple[int, int]] = {}
    directories: set[str] = set()
    directory_identities: dict[str, tuple[int, int]] = {
        "": (root_info.st_dev, root_info.st_ino)
    }
    folded: dict[str, str] = {}
    while pending:
        directory, prefix = pending.pop()
        if _is_link_or_junction(directory):
            raise InstallError(f"{label} contains a linked directory: {directory}")
        try:
            entries = sorted(os.scandir(directory), key=lambda item: item.name.casefold())
        except OSError as exc:
            raise InstallError(f"Cannot scan {label}: {directory}: {exc}") from exc
        for entry in entries:
            path = Path(entry.path)
            relative = entry.name if not prefix else f"{prefix}/{entry.name}"
            relative = _safe_owned_relative(relative, f"{label} entry")
            prior = folded.get(relative.casefold())
            if prior is not None:
                raise InstallError(
                    f"{label} contains a Windows path collision: {prior!r}, {relative!r}"
                )
            folded[relative.casefold()] = relative
            if entry.is_symlink() or _is_link_or_junction(path):
                raise InstallError(f"{label} contains a link, junction, or reparse: {relative}")
            try:
                info = path.lstat()
            except OSError as exc:
                raise InstallError(f"Cannot inspect {label} entry {relative}: {exc}") from exc
            if stat.S_ISREG(info.st_mode) and entry.is_file(follow_symlinks=False):
                files[relative] = _hash_direct_regular_file(path, info, label)
                file_identities[relative] = (info.st_dev, info.st_ino)
            elif stat.S_ISDIR(info.st_mode) and entry.is_dir(follow_symlinks=False):
                directories.add(relative)
                directory_identities[relative] = (info.st_dev, info.st_ino)
                directory_states[path] = _stable_stat_identity(info)
                pending.append((path, relative))
            else:
                raise InstallError(f"{label} contains an unsupported entry: {relative}")
    for directory, expected in directory_states.items():
        try:
            current = directory.lstat()
        except OSError as exc:
            raise InstallError(f"Directory changed while scanning {label}: {directory}") from exc
        if _is_link_or_junction(directory) or _stable_stat_identity(current) != expected:
            raise InstallError(f"Directory changed while scanning {label}: {directory}")
    return _TreeProof(
        root_identity=(root_info.st_dev, root_info.st_ino),
        files=tuple(sorted(files.items())),
        directories=tuple(sorted(directories)),
        file_identities=tuple(
            (relative, *identity)
            for relative, identity in sorted(file_identities.items())
        ),
        directory_identities=tuple(
            (relative, *identity)
            for relative, identity in sorted(directory_identities.items())
        ),
    )


def _expected_directories(files: dict[str, str], label: str) -> tuple[str, ...]:
    directories: set[str] = set()
    folded: set[str] = set()
    for relative, digest in files.items():
        relative = _safe_owned_relative(relative, f"{label} file")
        if relative.casefold() in folded or _SHA256_RE.fullmatch(digest) is None:
            raise InstallError(f"{label} contains invalid or colliding file ownership")
        folded.add(relative.casefold())
        parent = PurePosixPath(relative).parent
        while parent.parts:
            directories.add(parent.as_posix())
            parent = parent.parent
    return tuple(sorted(directories))


def _assert_exact_tree_content(proof: _TreeProof, files: dict[str, str], label: str) -> None:
    expected_directories = _expected_directories(files, label)
    if proof.files != tuple(sorted(files.items())):
        raise InstallError(f"{label} file set or hashes changed")
    if proof.directories != expected_directories:
        raise InstallError(
            f"{label} directory set changed; expected={list(expected_directories)} "
            f"actual={list(proof.directories)}"
        )


def _assert_tree_proof(root: Path, expected: _TreeProof, label: str) -> None:
    actual = _scan_tree(root, label)
    if actual != expected:
        raise InstallError(f"{label} changed after ownership verification")


def _destination(config: BuilderConfig) -> Path:
    if config.target.game_dir is None:
        raise InstallError("Target game directory is not configured")
    mod_folder_name = _safe_component(config.output.mod_folder_name, "mod folder name")
    game_dir = _lexical_absolute(config.target.game_dir)
    plugins = game_dir / "BepInEx" / "plugins"
    destination = plugins / mod_folder_name
    _assert_exact_child(destination, plugins, mod_folder_name, "install destination")
    if _path_lexists(plugins):
        _require_direct_directory(plugins, "BepInEx plugins directory")
        try:
            resolved_plugins = plugins.resolve(strict=True)
            resolved_destination = destination.resolve(strict=False)
        except (OSError, RuntimeError) as exc:
            raise InstallError("Cannot prove BepInEx/plugins containment") from exc
        if resolved_destination.parent != resolved_plugins:
            raise InstallError(
                f"Install destination escaped BepInEx/plugins: {destination}"
            )
    if _path_lexists(destination) and _is_link_or_junction(destination):
        raise InstallError(
            f"Install destination is linked, junctioned, or reparsed: {destination}"
        )
    return destination


def _file_hashes(root: Path) -> dict[str, str]:
    return _scan_tree(root, "install tree").file_hashes()


def _state_dir(config: BuilderConfig) -> Path:
    project_root = _lexical_absolute(config.project_root)
    state_dir = _lexical_absolute(config.output.state_dir)
    if state_dir == project_root or project_root not in state_dir.parents:
        raise InstallError(f"Installer state directory escaped the project: {state_dir}")
    return state_dir


def _require_state_dir(config: BuilderConfig, *, create: bool) -> tuple[Path, bool]:
    """Verify every existing state path component without following reparses."""

    project_root = _lexical_absolute(config.project_root)
    state_dir = _state_dir(config)
    _require_direct_directory(project_root, "project root")
    try:
        resolved_project_root = project_root.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise InstallError(f"Cannot resolve project root: {project_root}") from exc
    if resolved_project_root != project_root:
        raise InstallError(
            f"Project root has a linked/reparsed ancestor: {project_root}"
        )

    current = project_root
    for component in state_dir.relative_to(project_root).parts:
        child = current / component
        _assert_exact_child(child, current, component, "installer state component")
        if not _path_lexists(child):
            if not create:
                return state_dir, False
            try:
                child.mkdir()
            except OSError as exc:
                raise InstallError(
                    f"Cannot create installer state directory: {child}: {exc}"
                ) from exc
        _require_direct_directory(child, "installer state directory")
        try:
            resolved_child = child.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise InstallError(f"Cannot resolve installer state directory: {child}") from exc
        if resolved_child != child:
            raise InstallError(
                f"Installer state directory resolves through a reparse: {child}"
            )
        current = child
    return state_dir, True


def _manifest_path(config: BuilderConfig) -> Path:
    state_dir = _state_dir(config)
    manifest_path = state_dir / "install-manifest.json"
    _assert_exact_child(
        manifest_path,
        state_dir,
        "install-manifest.json",
        "install ownership manifest",
    )
    return manifest_path


def _require_direct_regular_file(path: Path, label: str) -> os.stat_result:
    if not _path_lexists(path) or _is_link_or_junction(path):
        raise InstallError(f"{label} is missing, linked, junctioned, or reparsed: {path}")
    try:
        info = path.lstat()
    except OSError as exc:
        raise InstallError(f"Cannot inspect {label}: {path}: {exc}") from exc
    if not stat.S_ISREG(info.st_mode):
        raise InstallError(f"{label} is not a direct regular file: {path}")
    return info


def _read_direct_file(path: Path, label: str) -> _DirectFileProof:
    before = _require_direct_regular_file(path, label)
    flags = os.O_RDONLY | int(getattr(os, "O_BINARY", 0))
    flags |= int(getattr(os, "O_NOFOLLOW", 0))
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise InstallError(f"Cannot open direct {label}: {path}: {exc}") from exc
    chunks: list[bytes] = []
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
        ):
            raise InstallError(f"{label} changed to a different object: {path}")
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        after_open = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    try:
        after_path = path.lstat()
    except OSError as exc:
        raise InstallError(f"{label} disappeared while being read: {path}") from exc
    if (
        _is_link_or_junction(path)
        or _stable_stat_identity(before) != _stable_stat_identity(after_path)
        or _stable_stat_identity(opened) != _stable_stat_identity(after_open)
    ):
        raise InstallError(f"{label} changed while being read: {path}")
    return _DirectFileProof(
        content=b"".join(chunks),
        identity=(opened.st_dev, opened.st_ino),
    )


def _assert_direct_file_proof(
    path: Path, expected: _DirectFileProof, label: str
) -> None:
    if _read_direct_file(path, label) != expected:
        raise InstallError(f"{label} changed after verification: {path}")


def _manifest_target_exists(config: BuilderConfig) -> bool:
    _state, state_exists = _require_state_dir(config, create=False)
    manifest_path = _manifest_path(config)
    if not state_exists:
        if _path_lexists(manifest_path):
            raise InstallError(f"Manifest exists below a missing state directory: {manifest_path}")
        return False
    if not _path_lexists(manifest_path):
        return False
    _require_direct_regular_file(manifest_path, "install ownership manifest")
    return True


def _assert_manifest_target_absent(config: BuilderConfig) -> Path:
    state_dir, _state_exists = _require_state_dir(config, create=True)
    manifest_path = _manifest_path(config)
    _assert_exact_child(
        manifest_path,
        state_dir,
        "install-manifest.json",
        "install ownership manifest",
    )
    if _path_lexists(manifest_path):
        raise InstallError(
            f"Install ownership manifest unexpectedly exists: {manifest_path}"
        )
    return manifest_path


def _read_install_manifest(
    config: BuilderConfig,
) -> tuple[Path, _DirectFileProof, dict[str, Any]]:
    _state_dir_path, state_exists = _require_state_dir(config, create=False)
    manifest_path = _manifest_path(config)
    if not state_exists or not _path_lexists(manifest_path):
        raise InstallError("Existing install has no direct ownership manifest")
    try:
        manifest_proof = _read_direct_file(
            manifest_path, "install ownership manifest"
        )
        manifest = json.loads(manifest_proof.content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InstallError("Existing install manifest is unreadable") from exc
    if not isinstance(manifest, dict):
        raise InstallError("Existing install manifest is not a JSON object")
    return manifest_path, manifest_proof, manifest


def _verified_prior_install(
    config: BuilderConfig, destination: Path
) -> _OwnedInstallProof:
    """Return proof only for an unchanged, exactly owned install tree."""

    _assert_exact_child(
        destination,
        destination.parent,
        _safe_component(config.output.mod_folder_name, "mod folder name"),
        "installed mod",
    )
    _require_direct_directory(destination, "installed mod directory")
    _manifest_path_value, manifest_proof, manifest = _read_install_manifest(config)
    if manifest.get("schema_version") != 1:
        raise InstallError("Existing install manifest has unsupported schema")
    manifest_destination = manifest.get("destination")
    if (
        not isinstance(manifest_destination, str)
        or not Path(manifest_destination).is_absolute()
        or Path(manifest_destination) != destination
    ):
        raise InstallError(
            "Existing install manifest destination does not match configured destination"
        )
    expected = manifest.get("files")
    if not isinstance(expected, dict) or not expected:
        raise InstallError("Existing install manifest has no owned file set")
    if any(not isinstance(key, str) or not isinstance(value, str) for key, value in expected.items()):
        raise InstallError("Existing install manifest contains invalid file hashes")
    expected_files = dict(expected)
    tree = _scan_tree(destination, "existing installed tree")
    try:
        _assert_exact_tree_content(tree, expected_files, "Existing installed tree")
    except InstallError as exc:
        raise InstallError(
            f"Existing installed tree changed; refusing replacement: {exc}"
        ) from exc
    return _OwnedInstallProof(
        manifest_bytes=manifest_proof.content,
        manifest_identity=manifest_proof.identity,
        tree=tree,
    )


def _assert_owner_manifest_unchanged(
    config: BuilderConfig, expected: _OwnedInstallProof
) -> None:
    _path, current, _manifest = _read_install_manifest(config)
    if (
        current.content != expected.manifest_bytes
        or current.identity != expected.manifest_identity
    ):
        raise InstallError("Install ownership manifest changed before mutation")


def _require_install_roots(
    plugins: Path,
    state_dir: Path | None = None,
) -> None:
    plugins = _lexical_absolute(plugins)
    _require_direct_directory(plugins, "BepInEx plugins directory")
    try:
        resolved_plugins = plugins.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise InstallError("Cannot resolve BepInEx plugins directory") from exc
    if resolved_plugins != plugins:
        raise InstallError(
            f"BepInEx plugins directory has a linked/reparsed ancestor: {plugins}"
        )
    if state_dir is None:
        return
    state_dir = _lexical_absolute(state_dir)
    state_info = _require_direct_directory(state_dir, "installer state directory")
    try:
        resolved_state = state_dir.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise InstallError("Cannot resolve installer state directory") from exc
    if resolved_state != state_dir:
        raise InstallError(
            f"Installer state directory resolves through a reparse: {state_dir}"
        )
    plugins_info = plugins.lstat()
    if plugins_info.st_dev != state_info.st_dev:
        raise InstallError(
            "Installer state directory and BepInEx/plugins are on different "
            "volumes; refusing a non-atomic live-tree transaction"
        )


def _reserved_transaction_entries(
    location: Path,
    prefix: str,
) -> list[Path]:
    """List reserved orphan directories/reparses without following them."""

    _require_direct_directory(location, "installer transaction location")
    result: list[Path] = []
    try:
        entries = list(os.scandir(location))
    except OSError as exc:
        raise InstallError(f"Cannot inspect installer transaction location: {location}") from exc
    generated = re.compile(re.escape(prefix) + r"[0-9a-f]{32}\Z")
    for entry in entries:
        if not entry.name.startswith(prefix):
            continue
        path = Path(entry.path)
        if (
            entry.is_symlink()
            or _is_link_or_junction(path)
            or entry.is_dir(follow_symlinks=False)
            or generated.fullmatch(entry.name) is not None
        ):
            result.append(path)
    return result


def _reserved_manifest_entries(
    config: BuilderConfig,
    prefixes: tuple[str, ...],
) -> list[Path]:
    """Return every reserved transaction-manifest entry without following it."""

    state_dir, state_exists = _require_state_dir(config, create=False)
    if not state_exists:
        return []
    try:
        entries = list(os.scandir(state_dir))
    except OSError as exc:
        raise InstallError(
            f"Cannot inspect installer state directory: {state_dir}: {exc}"
        ) from exc
    return [
        Path(entry.path)
        for entry in entries
        if any(entry.name.startswith(prefix) for prefix in prefixes)
    ]


def _reserved_uninstall_manifest_entries(config: BuilderConfig) -> list[Path]:
    return _reserved_manifest_entries(config, (_UNINSTALL_MANIFEST_PREFIX,))


def _assert_destination_guard(
    destination: Path,
    plugins: Path,
    mod_folder_name: str,
    *,
    must_exist: bool,
) -> None:
    _assert_exact_child(destination, plugins, mod_folder_name, "install destination")
    if must_exist:
        _require_direct_directory(destination, "install destination")
    elif _path_lexists(destination):
        raise InstallError(f"Install destination unexpectedly exists: {destination}")


def _assert_generated_guard(
    path: Path,
    parent: Path,
    prefix: str,
    label: str,
    *,
    must_exist: bool,
) -> None:
    _assert_generated_child(path, parent, prefix, label)
    if must_exist:
        _require_direct_directory(path, label)
    elif _path_lexists(path):
        raise InstallError(f"Generated {label} unexpectedly exists: {path}")


def _rename_proven_tree(
    source: Path,
    destination: Path,
    proof: _TreeProof,
    *,
    source_guard: Any,
    destination_guard: Any,
    label: str,
    pre_rename_guard: Any | None = None,
) -> None:
    source_guard()
    destination_guard()
    _assert_tree_proof(source, proof, label)
    if pre_rename_guard is not None:
        pre_rename_guard()
    _atomic_rename_no_replace(source, destination, label)
    if _path_lexists(source):
        raise InstallError(f"{label} source still exists after rename: {source}")
    _assert_tree_proof(destination, proof, f"promoted {label}")


def _rename_proven_file(
    source: Path,
    destination: Path,
    proof: _DirectFileProof,
    *,
    source_guard: Any,
    destination_guard: Any,
    label: str,
    pre_rename_guard: Any | None = None,
) -> None:
    source_guard()
    destination_guard()
    _assert_direct_file_proof(source, proof, label)
    if pre_rename_guard is not None:
        pre_rename_guard()
    _atomic_rename_no_replace(source, destination, label)
    if _path_lexists(source):
        raise InstallError(f"{label} source still exists after rename: {source}")
    _assert_direct_file_proof(destination, proof, f"quarantined {label}")


def _atomic_rename_no_replace(source: Path, destination: Path, label: str) -> None:
    """Atomically rename without ever replacing an occupied destination."""

    source = _lexical_absolute(source)
    destination = _lexical_absolute(destination)
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.MoveFileW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        kernel32.MoveFileW.restype = wintypes.BOOL
        if not kernel32.MoveFileW(str(source), str(destination)):
            error = ctypes.get_last_error()
            raise InstallError(
                f"Cannot atomically rename {label} without replacement: "
                f"{source} -> {destination}: WinError {error}: "
                f"{ctypes.FormatError(error)}"
            )
        return

    # Linux exposes the same no-replace contract through renameat2.  Other
    # platforms fail closed rather than silently falling back to os.rename,
    # whose POSIX contract may overwrite an occupied destination.
    import ctypes

    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise InstallError(
            f"Atomic no-replace rename is unavailable for {label} on this platform"
        )
    renameat2.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    renameat2.restype = ctypes.c_int
    if renameat2(
        -100,
        os.fsencode(source),
        -100,
        os.fsencode(destination),
        1,
    ) != 0:
        error = ctypes.get_errno()
        raise InstallError(
            f"Cannot atomically rename {label} without replacement: "
            f"{source} -> {destination}: {os.strerror(error)}"
        )


def _windows_open_frozen_delete_handle(path: Path, *, directory: bool) -> Any:
    """Open an exact object for deletion while denying rename/delete sharing."""

    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    flags = 0x00200000  # FILE_FLAG_OPEN_REPARSE_POINT
    if directory:
        flags |= 0x02000000  # FILE_FLAG_BACKUP_SEMANTICS
    handle = kernel32.CreateFileW(
        str(path),
        0x00010000 | 0x00000080,  # DELETE | FILE_READ_ATTRIBUTES
        0x00000001 | 0x00000002,  # share read/write, deliberately not delete
        None,
        3,  # OPEN_EXISTING
        flags,
        None,
    )
    if handle == ctypes.c_void_p(-1).value:
        error = ctypes.get_last_error()
        raise InstallError(
            f"Cannot freeze proof-bearing cleanup object: {path}: "
            f"WinError {error}: {ctypes.FormatError(error)}"
        )
    return handle


def _windows_mark_handle_for_delete(handle: Any, path: Path) -> None:
    import ctypes
    from ctypes import wintypes

    class _FileDispositionInfo(ctypes.Structure):
        _fields_ = [("DeleteFile", wintypes.BOOL)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.SetFileInformationByHandle.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    kernel32.SetFileInformationByHandle.restype = wintypes.BOOL
    disposition = _FileDispositionInfo(True)
    if not kernel32.SetFileInformationByHandle(
        handle,
        4,  # FileDispositionInfo
        ctypes.byref(disposition),
        ctypes.sizeof(disposition),
    ):
        error = ctypes.get_last_error()
        raise InstallError(
            f"Cannot mark proof-bearing cleanup object for deletion: {path}: "
            f"WinError {error}: {ctypes.FormatError(error)}"
        )


def _windows_close_handle(handle: Any) -> None:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CloseHandle(handle)


def _delete_windows_proven_tree(root: Path, proof: _TreeProof, label: str) -> None:
    """Delete the proved Windows tree by identities and frozen handles."""

    _assert_tree_proof(root, proof, f"final {label}")
    root_handle = _windows_open_frozen_delete_handle(root, directory=True)
    try:
        # Opening without FILE_SHARE_DELETE freezes the root name/object pair.
        # A swap between the tombstone proof and CreateFileW is caught by the
        # identity check. Reopening the tree would conflict with the deliberate
        # deny-delete share mode of the frozen handle.
        frozen_root = _require_direct_directory(root, label)
        if (frozen_root.st_dev, frozen_root.st_ino) != proof.root_identity:
            raise InstallError(f"{label} root changed while freezing cleanup: {root}")
        file_identities = proof.file_identity_map()
        for relative in sorted(file_identities, key=lambda value: value.count("/"), reverse=True):
            path = root / Path(PurePosixPath(relative))
            before = _require_direct_regular_file(path, label)
            if (before.st_dev, before.st_ino) != file_identities[relative]:
                raise InstallError(f"{label} file identity changed before cleanup: {path}")
            handle = _windows_open_frozen_delete_handle(path, directory=False)
            try:
                after = _require_direct_regular_file(path, label)
                if (after.st_dev, after.st_ino) != file_identities[relative]:
                    raise InstallError(
                        f"{label} file identity changed while freezing cleanup: {path}"
                    )
                _windows_mark_handle_for_delete(handle, path)
            finally:
                _windows_close_handle(handle)
            if _path_lexists(path):
                raise InstallError(f"{label} file remained after handle deletion: {path}")

        directory_identities = proof.directory_identity_map()
        child_directories = sorted(
            (relative for relative in directory_identities if relative),
            key=lambda value: value.count("/"),
            reverse=True,
        )
        for relative in child_directories:
            path = root / Path(PurePosixPath(relative))
            before = _require_direct_directory(path, label)
            if (before.st_dev, before.st_ino) != directory_identities[relative]:
                raise InstallError(
                    f"{label} directory identity changed before cleanup: {path}"
                )
            handle = _windows_open_frozen_delete_handle(path, directory=True)
            try:
                after = _require_direct_directory(path, label)
                if (after.st_dev, after.st_ino) != directory_identities[relative]:
                    raise InstallError(
                        f"{label} directory identity changed while freezing cleanup: {path}"
                    )
                try:
                    if any(os.scandir(path)):
                        raise InstallError(
                            f"{label} directory gained an entry during cleanup: {path}"
                        )
                except OSError as exc:
                    raise InstallError(
                        f"Cannot prove {label} directory empty: {path}: {exc}"
                    ) from exc
                _windows_mark_handle_for_delete(handle, path)
            finally:
                _windows_close_handle(handle)
            if _path_lexists(path):
                raise InstallError(
                    f"{label} directory remained after handle deletion: {path}"
                )

        try:
            if any(os.scandir(root)):
                raise InstallError(f"{label} root gained an entry during cleanup: {root}")
        except OSError as exc:
            raise InstallError(f"Cannot prove {label} root empty: {root}: {exc}") from exc
        root_info = _require_direct_directory(root, label)
        if (root_info.st_dev, root_info.st_ino) != proof.root_identity:
            raise InstallError(f"{label} root identity changed during cleanup: {root}")
        _windows_mark_handle_for_delete(root_handle, root)
    finally:
        _windows_close_handle(root_handle)
    if _path_lexists(root):
        raise InstallError(f"{label} still exists after handle-bound cleanup: {root}")


def _delete_proven_tombstone(root: Path, proof: _TreeProof, label: str) -> None:
    if os.name == "nt":
        _delete_windows_proven_tree(root, proof, label)
        return
    # The product target is Windows.  Linux test/development hosts still use
    # Python's fd-hardened rmtree implementation after an identity reproof.
    _assert_tree_proof(root, proof, f"final {label}")
    if not getattr(shutil.rmtree, "avoids_symlink_attacks", False):
        raise InstallError(
            f"Handle-safe tombstone cleanup is unavailable for {label}"
        )
    shutil.rmtree(root)
    if _path_lexists(root):
        raise InstallError(f"{label} still exists after tombstone cleanup: {root}")


def _remove_proven_tree(
    root: Path,
    proof: _TreeProof,
    *,
    root_guard: Any,
    label: str,
    pre_remove_guard: Any | None = None,
    tombstone_parent: Path | None = None,
    tombstone_prefix: str = ".remove-tombstone-",
    tombstone_guard: Any | None = None,
    defer_cleanup_errors: bool = False,
) -> bool:
    """Logically remove by proof-bound rename, then delete the bound object.

    The first irreversible step is an atomic no-replace rename to a fresh
    tombstone.  If the source was swapped after its proof, the post-rename proof
    fails and the replacement is preserved in quarantine, never passed to a
    recursive deleter.
    """

    parent = _lexical_absolute(tombstone_parent or root.parent)
    tombstone = parent / f"{tombstone_prefix}{uuid4().hex}"
    def destination_guard() -> None:
        _assert_generated_guard(
            tombstone,
            parent,
            tombstone_prefix,
            f"{label} tombstone",
            must_exist=False,
        )
        if tombstone_guard is not None:
            tombstone_guard()
    _rename_proven_tree(
        root,
        tombstone,
        proof,
        source_guard=root_guard,
        destination_guard=destination_guard,
        label=label,
        pre_rename_guard=pre_remove_guard,
    )
    try:
        _delete_proven_tombstone(tombstone, proof, f"{label} tombstone")
    except Exception:
        if defer_cleanup_errors:
            return False
        raise
    return True


def _assert_generated_manifest_path(
    path: Path,
    state_dir: Path,
    prefix: str,
    label: str,
) -> None:
    if (
        path != _lexical_absolute(path)
        or path.parent != state_dir
        or re.fullmatch(re.escape(prefix) + r"[0-9a-f]{32}\.json", path.name)
        is None
    ):
        raise InstallError(f"Unsafe {label} path: {path}")


def _assert_manifest_staging_path(path: Path, state_dir: Path) -> None:
    _assert_generated_manifest_path(
        path,
        state_dir,
        _MANIFEST_STAGING_PREFIX,
        "staged install manifest",
    )


def _assert_uninstall_manifest_quarantine_path(path: Path, state_dir: Path) -> None:
    _assert_generated_manifest_path(
        path,
        state_dir,
        _UNINSTALL_MANIFEST_PREFIX,
        "uninstall manifest quarantine",
    )


def _assert_state_manifest_absent(
    config: BuilderConfig,
    path: Path,
    prefix: str,
    label: str,
) -> None:
    state_dir, state_exists = _require_state_dir(config, create=False)
    if not state_exists:
        raise InstallError("Installer state directory disappeared")
    _assert_generated_manifest_path(path, state_dir, prefix, label)
    if _path_lexists(path):
        raise InstallError(f"{label} unexpectedly exists: {path}")


def _assert_state_manifest_proof(
    config: BuilderConfig,
    path: Path,
    prefix: str,
    label: str,
    expected: _DirectFileProof,
) -> None:
    state_dir, state_exists = _require_state_dir(config, create=False)
    if not state_exists:
        raise InstallError("Installer state directory disappeared")
    _assert_generated_manifest_path(path, state_dir, prefix, label)
    _assert_direct_file_proof(path, expected, label)


def _assert_uninstall_manifest_quarantine_absent(
    config: BuilderConfig,
    path: Path,
) -> None:
    _assert_state_manifest_absent(
        config,
        path,
        _UNINSTALL_MANIFEST_PREFIX,
        "uninstall manifest quarantine",
    )


def _assert_uninstall_manifest_quarantine_proof(
    config: BuilderConfig,
    path: Path,
    expected: _DirectFileProof,
) -> None:
    _assert_state_manifest_proof(
        config,
        path,
        _UNINSTALL_MANIFEST_PREFIX,
        "uninstall manifest quarantine",
        expected,
    )


def _unlink_uninstall_manifest_quarantine(
    config: BuilderConfig,
    path: Path,
    proof: _DirectFileProof,
) -> None:
    _delete_proven_file(
        path,
        proof,
        guard=lambda: _assert_uninstall_manifest_quarantine_proof(
            config, path, proof
        ),
        label="uninstall manifest quarantine",
    )


def _assert_manifest_staging_proof(
    config: BuilderConfig,
    path: Path,
    expected: _DirectFileProof,
) -> None:
    state_dir, state_exists = _require_state_dir(config, create=False)
    if not state_exists:
        raise InstallError("Installer state directory disappeared")
    _assert_manifest_staging_path(path, state_dir)
    _assert_direct_file_proof(path, expected, "staged install manifest")


def _assert_manifest_target_proof(
    config: BuilderConfig,
    expected: _DirectFileProof,
) -> Path:
    state_dir, state_exists = _require_state_dir(config, create=False)
    if not state_exists:
        raise InstallError("Installer state directory disappeared")
    manifest_path = _manifest_path(config)
    _assert_exact_child(
        manifest_path,
        state_dir,
        "install-manifest.json",
        "install ownership manifest",
    )
    _assert_direct_file_proof(
        manifest_path, expected, "install ownership manifest"
    )
    return manifest_path


def _stage_manifest_bytes(
    config: BuilderConfig, payload: bytes
) -> tuple[Path, _DirectFileProof]:
    """Create a new, exclusive sibling manifest without following reparses."""

    state_dir, _state_exists = _require_state_dir(config, create=True)
    staged = state_dir / f"{_MANIFEST_STAGING_PREFIX}{uuid4().hex}.json"
    _assert_manifest_staging_path(staged, state_dir)
    if _path_lexists(staged):
        raise InstallError(f"Unexpected staged manifest collision: {staged}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | int(getattr(os, "O_BINARY", 0))
    flags |= int(getattr(os, "O_NOFOLLOW", 0))
    try:
        descriptor = os.open(staged, flags, 0o600)
    except OSError as exc:
        raise InstallError(f"Cannot create staged install manifest: {staged}: {exc}") from exc
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise InstallError(f"Short write while staging install manifest: {staged}")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    proof = _read_direct_file(staged, "staged install manifest")
    if proof.content != payload:
        raise InstallError("Staged install manifest failed its reread check")
    return staged, proof


def _stage_manifest(
    config: BuilderConfig, manifest: dict[str, Any]
) -> tuple[Path, _DirectFileProof]:
    payload = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    return _stage_manifest_bytes(config, payload)


def _delete_proven_file(
    path: Path,
    proof: _DirectFileProof,
    *,
    guard: Any,
    label: str,
) -> None:
    guard()
    _assert_direct_file_proof(path, proof, label)
    if os.name == "nt":
        handle = _windows_open_frozen_delete_handle(path, directory=False)
        try:
            frozen = _require_direct_regular_file(path, f"frozen {label}")
            if (frozen.st_dev, frozen.st_ino) != proof.identity:
                raise InstallError(f"{label} changed while freezing cleanup: {path}")
            _windows_mark_handle_for_delete(handle, path)
        finally:
            _windows_close_handle(handle)
    else:
        # The production target is Win32.  On POSIX, unlink is already a
        # handle-independent removal of the named directory entry; the second
        # proof narrows the remaining name race for development/test hosts.
        _assert_direct_file_proof(path, proof, f"final {label}")
        path.unlink()
    if _path_lexists(path):
        raise InstallError(f"{label} still exists after removal: {path}")


def _unlink_staged_manifest(
    config: BuilderConfig, path: Path, proof: _DirectFileProof
) -> None:
    _delete_proven_file(
        path,
        proof,
        guard=lambda: _assert_manifest_staging_proof(config, path, proof),
        label="staged install manifest",
    )


def _unlink_manifest_target(
    config: BuilderConfig, proof: _DirectFileProof
) -> None:
    manifest_path = _manifest_path(config)
    _delete_proven_file(
        manifest_path,
        proof,
        guard=lambda: _assert_manifest_target_proof(config, proof),
        label="install ownership manifest",
    )


def _restore_manifest_target(
    config: BuilderConfig,
    current: _DirectFileProof,
    prior_bytes: bytes,
) -> _DirectFileProof:
    state_dir, state_exists = _require_state_dir(config, create=False)
    if not state_exists:
        raise InstallError("Installer state directory disappeared")
    restore, restore_proof = _stage_manifest_bytes(config, prior_bytes)
    quarantine = state_dir / f"{_FAILED_MANIFEST_PREFIX}{uuid4().hex}.json"
    _assert_state_manifest_absent(
        config,
        quarantine,
        _FAILED_MANIFEST_PREFIX,
        "failed install manifest quarantine",
    )
    current_quarantined = False
    try:
        manifest_path = _assert_manifest_target_proof(config, current)
        _assert_manifest_staging_proof(config, restore, restore_proof)
        _rename_proven_file(
            manifest_path,
            quarantine,
            current,
            source_guard=lambda: _assert_manifest_target_proof(config, current),
            destination_guard=lambda: _assert_state_manifest_absent(
                config,
                quarantine,
                _FAILED_MANIFEST_PREFIX,
                "failed install manifest quarantine",
            ),
            label="current install ownership manifest",
        )
        current_quarantined = True
        _rename_proven_file(
            restore,
            manifest_path,
            restore_proof,
            source_guard=lambda: _assert_manifest_staging_proof(
                config, restore, restore_proof
            ),
            destination_guard=lambda: _assert_manifest_target_absent(config),
            label="restored install ownership manifest",
        )
        _assert_manifest_target_proof(config, restore_proof)
        try:
            _delete_proven_file(
                quarantine,
                current,
                guard=lambda: _assert_state_manifest_proof(
                    config,
                    quarantine,
                    _FAILED_MANIFEST_PREFIX,
                    "failed install manifest quarantine",
                    current,
                ),
                label="failed install manifest quarantine",
            )
        except Exception:
            pass
        return restore_proof
    except Exception as original_error:
        rollback_errors: list[str] = []
        if (
            not current_quarantined
            and not _path_lexists(_manifest_path(config))
            and _path_lexists(quarantine)
        ):
            current_quarantined = True
        if current_quarantined and not _path_lexists(_manifest_path(config)):
            try:
                _rename_proven_file(
                    quarantine,
                    _manifest_path(config),
                    current,
                    source_guard=lambda: _assert_state_manifest_proof(
                        config,
                        quarantine,
                        _FAILED_MANIFEST_PREFIX,
                        "failed install manifest quarantine",
                        current,
                    ),
                    destination_guard=lambda: _assert_manifest_target_absent(config),
                    label="current install manifest rollback",
                )
            except Exception as rollback_error:
                rollback_errors.append(str(rollback_error))
        if _path_lexists(restore):
            try:
                _unlink_staged_manifest(config, restore, restore_proof)
            except Exception as rollback_error:
                rollback_errors.append(str(rollback_error))
        if rollback_errors:
            raise InstallError(
                "Manifest restore failed and no-overwrite rollback was incomplete: "
                + "; ".join(rollback_errors)
            ) from original_error
        raise


def _assert_state_generated_tree(
    config: BuilderConfig,
    path: Path,
    prefix: str,
    label: str,
    *,
    must_exist: bool,
) -> None:
    state_dir, state_exists = _require_state_dir(config, create=False)
    if not state_exists:
        raise InstallError("Installer state directory disappeared")
    _assert_generated_guard(
        path,
        state_dir,
        prefix,
        label,
        must_exist=must_exist,
    )


def _assert_artifact_promotable(root: Path, source_proof: _TreeProof) -> None:
    """Derive BC7 promotability from the immutable artifact itself.

    A caller that bypasses the CLI still cannot promote a measurement build.
    Legacy V1 artifacts have no BC7 signal and retain their existing API path.
    """

    source_hashes = source_proof.file_hashes()
    relative = "build-manifest.json"
    expected_hash = source_hashes.get(relative)
    if expected_hash is None:
        outputs: object = []
    else:
        manifest_path = root / relative
        manifest_proof = _read_direct_file(manifest_path, "built mod manifest")
        if hashlib.sha256(manifest_proof.content).hexdigest() != expected_hash:
            raise InstallError("Built mod manifest changed after source proof")
        try:
            manifest = json.loads(manifest_proof.content)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            if BC7_ATLAS_BACKEND_KIND.encode("utf-8") in manifest_proof.content:
                raise InstallError(
                    "Cannot derive BC7 artifact promotability from an invalid "
                    "build manifest"
                ) from exc
            manifest = None
        outputs = manifest.get("outputs") if isinstance(manifest, dict) else []

    saw_bc7 = False
    runtime_bindings: list[dict[str, Any]] = []
    for output in outputs if isinstance(outputs, list) else []:
        if not isinstance(output, dict):
            continue
        metadata = output.get("metadata")
        if not isinstance(metadata, dict):
            continue
        if metadata.get("kind") == BC7_ATLAS_BACKEND_KIND:
            saw_bc7 = True
        if metadata.get("asset_stream_backend_kind") == BC7_ATLAS_BACKEND_KIND:
            saw_bc7 = True
            runtime_bindings.append(metadata)
    if saw_bc7 and len(runtime_bindings) != 1:
        raise InstallError(
            "BC7 artifact promotability is ambiguous in build-manifest runtime metadata"
        )
    binding = runtime_bindings[0] if runtime_bindings else None
    if binding is not None:
        if (
            binding.get("asset_stream_quality_state") != "frozen"
            or binding.get("asset_stream_promotable") is not True
        ):
            raise InstallError(
                "BC7 measurement artifacts are non-promotable and cannot be installed"
            )

    # The V2 index is the authoritative artifact-side quality state. Runtime
    # metadata is deliberately checked as a second, independent binding so a
    # direct caller cannot flip one JSON boolean to promote a measurement build.
    index_hash = source_hashes.get(INDEX_OUTPUT_PATH)
    if index_hash is None:
        if saw_bc7:
            raise InstallError(
                "BC7 artifact is missing its proof-bearing V2 stream index"
            )
        return
    index_path = root.joinpath(*INDEX_OUTPUT_PATH.split("/"))
    index_proof = _read_direct_file(index_path, "asset stream index")
    if hashlib.sha256(index_proof.content).hexdigest() != index_hash:
        raise InstallError("Asset stream index changed after source proof")
    try:
        raw_index = json.loads(index_proof.content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InstallError(
            "Cannot derive artifact promotability from an invalid stream index"
        ) from exc
    if not isinstance(raw_index, dict):
        raise InstallError("Asset stream index is not a JSON object")
    if raw_index.get("schema") != BC7_INDEX_SCHEMA:
        if saw_bc7:
            raise InstallError(
                "BC7 build metadata disagrees with the artifact stream index schema"
            )
        return
    try:
        quality_policy = parse_quality_policy(raw_index.get("quality_policy"))
    except AssetStreamContractError as exc:
        raise InstallError(
            "BC7 artifact has an invalid quality-policy binding"
        ) from exc
    if not quality_policy.promotable:
        raise InstallError(
            "BC7 measurement artifacts are non-promotable and cannot be installed"
        )
    if (
        binding is None
        or binding.get("asset_stream_quality_state") != quality_policy.state
        or binding.get("asset_stream_promotable") is not quality_policy.promotable
    ):
        raise InstallError(
            "BC7 artifact quality state disagrees with runtime build metadata"
        )


def _transaction_orphans(
    config: BuilderConfig,
    plugins: Path,
    state_dir: Path,
    *,
    mod_folder_name: str,
) -> list[Path]:
    staging_prefix = f".{mod_folder_name}.install-"
    state_prefixes = (
        f".{mod_folder_name}.replace-backup-",
        f".{mod_folder_name}.uninstall-quarantine-",
        f".{mod_folder_name}.remove-tombstone-",
    )
    result = list(_reserved_transaction_entries(plugins, staging_prefix))
    for prefix in state_prefixes:
        # Read-only compatibility gate for forbidden leftovers created by an
        # older installer. Never load, rename, or delete them implicitly.
        result.extend(_reserved_transaction_entries(plugins, prefix))
        result.extend(_reserved_transaction_entries(state_dir, prefix))
    legacy_workarea = plugins.parent / f".{mod_folder_name}.install-workarea"
    _assert_exact_child(
        legacy_workarea,
        plugins.parent,
        legacy_workarea.name,
        "legacy installer workarea",
    )
    if _path_lexists(legacy_workarea):
        result.append(legacy_workarea)
    result.extend(
        _reserved_manifest_entries(
            config,
            (
                _MANIFEST_STAGING_PREFIX,
                _PRIOR_MANIFEST_PREFIX,
                _FAILED_MANIFEST_PREFIX,
                _UNINSTALL_MANIFEST_PREFIX,
            ),
        )
    )
    return sorted(result)


def install_mod(
    config: BuilderConfig,
    mod_root: Path,
    *,
    expected_profile_id: str | None = None,
    expected_source_build_id: str | None = None,
    expected_target_build_id: str | None = None,
    expected_profile: dict[str, Any] | None = None,
    replace_existing: bool = False,
) -> Path:
    if expected_profile_id is not None and expected_profile is None:
        raise InstallError(
            "An explicit expected_profile_id requires the matching expected "
            "profile document; refusing to install without its output contract"
        )

    # Bind the exact source object before validation. Validation is read-only,
    # but another process can atomically replace mod_root while it runs.
    source_root = _lexical_absolute(mod_root)
    source_proof = _scan_tree(source_root, "built mod source")
    _assert_artifact_promotable(source_root, source_proof)

    if expected_profile is not None:
        try:
            backend = parse_atlas_backend(expected_profile)
        except AssetStreamContractError as exc:
            raise InstallError(
                "Expected profile has an invalid atlas backend contract"
            ) from exc
        if (
            backend is not None
            and backend.kind == BC7_ATLAS_BACKEND_KIND
            and not backend.promotable
        ):
            raise InstallError(
                "BC7 measurement artifacts are non-promotable and cannot be "
                "installed; freeze and pass the visual-quality policy first"
            )

    checks = validate_mod(
        source_root,
        expected_profile_id=(
            expected_profile_id
            if expected_profile_id is not None
            else source_root.parent.name
        ),
        expected_source_build_id=expected_source_build_id,
        expected_target_build_id=expected_target_build_id,
        expected_profile=expected_profile,
    )
    # This must be the very next source operation after validation.
    _assert_tree_proof(
        source_root, source_proof, "built mod source after validation"
    )
    failed = [check for check in checks if not check.ok]
    if failed:
        raise InstallError(
            f"Built mod failed validation: {failed[0].name}: {failed[0].detail}"
        )

    # Before the first state mkdir, staging copy, or live rename.
    _assert_target_game_not_running(config, "install preflight")

    destination = _destination(config)
    plugins = destination.parent
    mod_folder_name = _safe_component(
        config.output.mod_folder_name, "mod folder name"
    )
    _require_install_roots(plugins)

    destination_exists = _path_lexists(destination)
    manifest_exists = _manifest_target_exists(config)
    if destination_exists != manifest_exists:
        raise InstallError(
            "Install destination and direct ownership manifest must either both "
            "exist or both be absent; refusing an orphaned ownership state"
        )
    if destination_exists and _is_link_or_junction(destination):
        raise InstallError(f"Install destination is linked or reparsed: {destination}")
    if destination_exists and not replace_existing:
        raise InstallError(f"Install destination already exists: {destination}")
    if destination_exists:
        _require_direct_directory(destination, "install destination")

    prior_proof: _OwnedInstallProof | None = None
    if destination_exists:
        prior_proof = _verified_prior_install(config, destination)

    state_dir, _state_exists = _require_state_dir(config, create=True)
    # st_dev equality is checked here before any path can cross the live/state
    # boundary. A cross-volume fallback copy is deliberately forbidden.
    _require_install_roots(plugins, state_dir)
    orphans = _transaction_orphans(
        config,
        plugins,
        state_dir,
        mod_folder_name=mod_folder_name,
    )
    if orphans:
        raise InstallError(
            "Orphaned install staging or other installer transaction entries "
            "must be recovered first: "
            f"{[str(path) for path in orphans]}"
        )

    staging_prefix = f".{mod_folder_name}.install-"
    backup_prefix = f".{mod_folder_name}.replace-backup-"
    tombstone_prefix = f".{mod_folder_name}.remove-tombstone-"
    staging = plugins / f"{staging_prefix}{uuid4().hex}"
    _assert_generated_guard(
        staging,
        plugins,
        staging_prefix,
        "install staging",
        must_exist=False,
    )

    manifest_staging: Path | None = None
    manifest_staging_proof: _DirectFileProof | None = None
    prior_manifest_quarantine: Path | None = None
    prior_manifest_proof: _DirectFileProof | None = None
    failed_manifest_quarantine: Path | None = None
    backup: Path | None = None
    staged_proof: _TreeProof | None = None
    backup_moved = False
    promoted = False
    prior_manifest_moved = False
    manifest_promoted = False

    try:
        # Reprove immediately before and after copy. The staged content is also
        # compared with the original content proof, not a post-validation scan.
        _assert_tree_proof(
            source_root, source_proof, "built mod source before staging copy"
        )
        shutil.copytree(source_root, staging, symlinks=True)
        staged_proof = _scan_tree(staging, "staged install tree")
        _assert_tree_proof(
            source_root, source_proof, "built mod source after staging copy"
        )
        if not source_proof.same_content(staged_proof):
            raise InstallError("Staged install hash set differs from validated built mod")
        staged_files = staged_proof.file_hashes()
        _assert_exact_tree_content(staged_proof, staged_files, "Staged install tree")

        install_manifest = {
            "schema_version": 1,
            "installed_at_utc": datetime.now(timezone.utc).isoformat(),
            "destination": str(destination),
            "files": staged_files,
        }
        if prior_proof is None:
            _assert_manifest_target_absent(config)
        else:
            _assert_owner_manifest_unchanged(config, prior_proof)
        manifest_staging, manifest_staging_proof = _stage_manifest(
            config, install_manifest
        )

        if prior_proof is not None:
            backup = state_dir / f"{backup_prefix}{uuid4().hex}"
            _assert_state_generated_tree(
                config,
                backup,
                backup_prefix,
                "replacement backup",
                must_exist=False,
            )
            _rename_proven_tree(
                destination,
                backup,
                prior_proof.tree,
                source_guard=lambda: (
                    _require_install_roots(plugins, state_dir),
                    _assert_destination_guard(
                        destination, plugins, mod_folder_name, must_exist=True
                    ),
                    _assert_owner_manifest_unchanged(config, prior_proof),
                ),
                destination_guard=lambda: _assert_state_generated_tree(
                    config,
                    backup,
                    backup_prefix,
                    "replacement backup",
                    must_exist=False,
                ),
                label="existing installed tree",
                pre_rename_guard=lambda: _assert_target_game_not_running(
                    config, "replacement backup rename"
                ),
            )
            backup_moved = True

        assert staged_proof is not None
        _rename_proven_tree(
            staging,
            destination,
            staged_proof,
            source_guard=lambda: (
                _require_install_roots(plugins, state_dir),
                _assert_generated_guard(
                    staging,
                    plugins,
                    staging_prefix,
                    "install staging",
                    must_exist=True,
                ),
            ),
            destination_guard=lambda: _assert_destination_guard(
                destination, plugins, mod_folder_name, must_exist=False
            ),
            label="staged install tree",
            pre_rename_guard=lambda: _assert_target_game_not_running(
                config, "install promotion"
            ),
        )
        promoted = True

        _require_install_roots(plugins, state_dir)
        _assert_destination_guard(
            destination, plugins, mod_folder_name, must_exist=True
        )
        _assert_tree_proof(
            destination, staged_proof, "manifest promotion install target"
        )
        assert manifest_staging is not None
        assert manifest_staging_proof is not None
        _assert_manifest_staging_proof(
            config, manifest_staging, manifest_staging_proof
        )

        manifest_path = _manifest_path(config)
        if prior_proof is not None:
            assert backup is not None
            _assert_state_generated_tree(
                config,
                backup,
                backup_prefix,
                "replacement backup",
                must_exist=True,
            )
            _assert_tree_proof(
                backup, prior_proof.tree, "manifest promotion prior owner tree"
            )
            _assert_owner_manifest_unchanged(config, prior_proof)
            prior_manifest_proof = _DirectFileProof(
                content=prior_proof.manifest_bytes,
                identity=prior_proof.manifest_identity,
            )
            prior_manifest_quarantine = (
                state_dir / f"{_PRIOR_MANIFEST_PREFIX}{uuid4().hex}.json"
            )
            _assert_state_manifest_absent(
                config,
                prior_manifest_quarantine,
                _PRIOR_MANIFEST_PREFIX,
                "prior install manifest quarantine",
            )
            _rename_proven_file(
                manifest_path,
                prior_manifest_quarantine,
                prior_manifest_proof,
                source_guard=lambda: _assert_owner_manifest_unchanged(
                    config, prior_proof
                ),
                destination_guard=lambda: _assert_state_manifest_absent(
                    config,
                    prior_manifest_quarantine,
                    _PRIOR_MANIFEST_PREFIX,
                    "prior install manifest quarantine",
                ),
                label="prior install ownership manifest",
            )
            prior_manifest_moved = True
        else:
            _assert_manifest_target_absent(config)

        _rename_proven_file(
            manifest_staging,
            manifest_path,
            manifest_staging_proof,
            source_guard=lambda: _assert_manifest_staging_proof(
                config, manifest_staging, manifest_staging_proof
            ),
            destination_guard=lambda: _assert_manifest_target_absent(config),
            label="new install ownership manifest",
        )
        manifest_promoted = True
        manifest_staging = None
        _assert_manifest_target_proof(config, manifest_staging_proof)
    except Exception as original_error:
        rollback_errors: list[str] = []

        # Reconstruct flags when a rename completed and its post-proof raised.
        if (
            not promoted
            and staged_proof is not None
            and not _path_lexists(staging)
            and _path_lexists(destination)
        ):
            promoted = True
        if (
            backup is not None
            and not backup_moved
            and not _path_lexists(destination)
            and _path_lexists(backup)
        ):
            backup_moved = True
        if (
            prior_manifest_quarantine is not None
            and not prior_manifest_moved
            and not _path_lexists(_manifest_path(config))
            and _path_lexists(prior_manifest_quarantine)
        ):
            prior_manifest_moved = True
        if (
            manifest_staging is not None
            and manifest_staging_proof is not None
            and not _path_lexists(manifest_staging)
            and _path_lexists(_manifest_path(config))
        ):
            try:
                _assert_manifest_target_proof(config, manifest_staging_proof)
                manifest_promoted = True
                manifest_staging = None
            except Exception:
                pass

        # Never modify manifests while an unremoved promoted live tree remains.
        live_slot_clear = not _path_lexists(destination)
        if promoted and _path_lexists(destination) and staged_proof is not None:
            try:
                _remove_proven_tree(
                    destination,
                    staged_proof,
                    root_guard=lambda: (
                        _require_install_roots(plugins, state_dir),
                        _assert_destination_guard(
                            destination,
                            plugins,
                            mod_folder_name,
                            must_exist=True,
                        ),
                    ),
                    label="promoted install rollback target",
                    pre_remove_guard=lambda: _assert_target_game_not_running(
                        config, "promoted install rollback removal"
                    ),
                    tombstone_parent=state_dir,
                    tombstone_prefix=tombstone_prefix,
                    tombstone_guard=lambda: _require_install_roots(
                        plugins, state_dir
                    ),
                    defer_cleanup_errors=True,
                )
                live_slot_clear = not _path_lexists(destination)
                promoted = not live_slot_clear
            except Exception as rollback_error:
                rollback_errors.append(str(rollback_error))
                live_slot_clear = not _path_lexists(destination)

        owner_ready = prior_proof is None
        if live_slot_clear:
            if manifest_promoted and manifest_staging_proof is not None:
                failed_manifest_quarantine = (
                    state_dir / f"{_FAILED_MANIFEST_PREFIX}{uuid4().hex}.json"
                )
                try:
                    _rename_proven_file(
                        _manifest_path(config),
                        failed_manifest_quarantine,
                        manifest_staging_proof,
                        source_guard=lambda: _assert_manifest_target_proof(
                            config, manifest_staging_proof
                        ),
                        destination_guard=lambda: _assert_state_manifest_absent(
                            config,
                            failed_manifest_quarantine,
                            _FAILED_MANIFEST_PREFIX,
                            "failed install manifest quarantine",
                        ),
                        label="failed new install manifest",
                    )
                    manifest_promoted = False
                except Exception as rollback_error:
                    rollback_errors.append(str(rollback_error))

            if prior_proof is not None:
                if prior_manifest_moved:
                    assert prior_manifest_quarantine is not None
                    assert prior_manifest_proof is not None
                    try:
                        _rename_proven_file(
                            prior_manifest_quarantine,
                            _manifest_path(config),
                            prior_manifest_proof,
                            source_guard=lambda: _assert_state_manifest_proof(
                                config,
                                prior_manifest_quarantine,
                                _PRIOR_MANIFEST_PREFIX,
                                "prior install manifest quarantine",
                                prior_manifest_proof,
                            ),
                            destination_guard=lambda: _assert_manifest_target_absent(
                                config
                            ),
                            label="prior install manifest rollback",
                        )
                        prior_manifest_moved = False
                        owner_ready = True
                    except Exception as rollback_error:
                        rollback_errors.append(str(rollback_error))
                        owner_ready = False
                else:
                    try:
                        _assert_owner_manifest_unchanged(config, prior_proof)
                        owner_ready = True
                    except Exception as rollback_error:
                        rollback_errors.append(str(rollback_error))
                        owner_ready = False
            else:
                owner_ready = not _path_lexists(_manifest_path(config))
        else:
            owner_ready = False

        if (
            backup is not None
            and backup_moved
            and _path_lexists(backup)
            and owner_ready
            and not _path_lexists(destination)
        ):
            assert prior_proof is not None
            try:
                _rename_proven_tree(
                    backup,
                    destination,
                    prior_proof.tree,
                    source_guard=lambda: (
                        _require_install_roots(plugins, state_dir),
                        _assert_state_generated_tree(
                            config,
                            backup,
                            backup_prefix,
                            "replacement backup",
                            must_exist=True,
                        ),
                    ),
                    destination_guard=lambda: _assert_destination_guard(
                        destination,
                        plugins,
                        mod_folder_name,
                        must_exist=False,
                    ),
                    label="replacement backup rollback",
                    pre_rename_guard=lambda: _assert_target_game_not_running(
                        config, "replacement backup rollback"
                    ),
                )
                backup_moved = False
            except Exception as rollback_error:
                rollback_errors.append(str(rollback_error))

        if _path_lexists(staging):
            if staged_proof is None:
                try:
                    staged_proof = _scan_tree(
                        staging, "partial failed install staging"
                    )
                except Exception as cleanup_error:
                    rollback_errors.append(str(cleanup_error))
            if staged_proof is not None:
                try:
                    _remove_proven_tree(
                        staging,
                        staged_proof,
                        root_guard=lambda: (
                            _require_install_roots(plugins, state_dir),
                            _assert_generated_guard(
                                staging,
                                plugins,
                                staging_prefix,
                                "failed install staging",
                                must_exist=True,
                            ),
                        ),
                        label="failed install staging",
                        tombstone_parent=state_dir,
                        tombstone_prefix=tombstone_prefix,
                        tombstone_guard=lambda: _require_install_roots(
                            plugins, state_dir
                        ),
                        defer_cleanup_errors=True,
                    )
                except Exception as cleanup_error:
                    rollback_errors.append(str(cleanup_error))

        if manifest_staging is not None and manifest_staging_proof is not None:
            try:
                _unlink_staged_manifest(
                    config, manifest_staging, manifest_staging_proof
                )
            except Exception as cleanup_error:
                rollback_errors.append(str(cleanup_error))

        if (
            failed_manifest_quarantine is not None
            and _path_lexists(failed_manifest_quarantine)
            and manifest_staging_proof is not None
        ):
            try:
                _delete_proven_file(
                    failed_manifest_quarantine,
                    manifest_staging_proof,
                    guard=lambda: _assert_state_manifest_proof(
                        config,
                        failed_manifest_quarantine,
                        _FAILED_MANIFEST_PREFIX,
                        "failed install manifest quarantine",
                        manifest_staging_proof,
                    ),
                    label="failed install manifest quarantine",
                )
            except Exception:
                # Non-active cleanup residue is reserved and blocks the next
                # mutation; it does not justify touching an unproved path.
                pass

        if rollback_errors:
            raise InstallError(
                "Install failed and safe rollback was incomplete; preserved all "
                "unproven paths for manual recovery: " + "; ".join(rollback_errors)
            ) from original_error
        raise

    # Commit is the exact new live tree plus its exact active manifest.
    assert staged_proof is not None
    assert manifest_staging_proof is not None
    _assert_tree_proof(destination, staged_proof, "committed install tree")
    _assert_manifest_target_proof(config, manifest_staging_proof)

    if backup is not None and backup_moved:
        assert prior_proof is not None
        backup_removed = False
        try:
            backup_removed = _remove_proven_tree(
                backup,
                prior_proof.tree,
                root_guard=lambda: (
                    _require_install_roots(plugins, state_dir),
                    _assert_state_generated_tree(
                        config,
                        backup,
                        backup_prefix,
                        "replacement backup",
                        must_exist=True,
                    ),
                ),
                label="committed replacement backup",
                tombstone_parent=state_dir,
                tombstone_prefix=tombstone_prefix,
                tombstone_guard=lambda: _require_install_roots(
                    plugins, state_dir
                ),
                defer_cleanup_errors=True,
            )
        except Exception:
            pass
        if (
            backup_removed
            and prior_manifest_quarantine is not None
            and prior_manifest_proof is not None
        ):
            try:
                _delete_proven_file(
                    prior_manifest_quarantine,
                    prior_manifest_proof,
                    guard=lambda: _assert_state_manifest_proof(
                        config,
                        prior_manifest_quarantine,
                        _PRIOR_MANIFEST_PREFIX,
                        "prior install manifest quarantine",
                        prior_manifest_proof,
                    ),
                    label="prior install manifest quarantine",
                )
            except Exception:
                pass
    return destination


def uninstall_mod(config: BuilderConfig) -> Path:
    # The first query precedes every mutation; the live rename has its own
    # immediate recheck after all ownership proofs.
    _assert_target_game_not_running(config, "uninstall preflight")
    destination = _destination(config)
    plugins = destination.parent
    mod_folder_name = _safe_component(
        config.output.mod_folder_name, "mod folder name"
    )
    _require_install_roots(plugins)
    _assert_destination_guard(
        destination, plugins, mod_folder_name, must_exist=True
    )
    proof = _verified_prior_install(config, destination)
    _assert_owner_manifest_unchanged(config, proof)

    state_dir, state_exists = _require_state_dir(config, create=False)
    if not state_exists:
        raise InstallError("Installer state directory disappeared")
    _require_install_roots(plugins, state_dir)
    orphans = _transaction_orphans(
        config,
        plugins,
        state_dir,
        mod_folder_name=mod_folder_name,
    )
    if orphans:
        raise InstallError(
            "Orphaned installer transaction entries must be recovered first: "
            f"{[str(path) for path in orphans]}"
        )

    quarantine_prefix = f".{mod_folder_name}.uninstall-quarantine-"
    tombstone_prefix = f".{mod_folder_name}.remove-tombstone-"
    quarantine = state_dir / f"{quarantine_prefix}{uuid4().hex}"
    _assert_state_generated_tree(
        config,
        quarantine,
        quarantine_prefix,
        "uninstall quarantine",
        must_exist=False,
    )
    manifest_quarantine = (
        state_dir / f"{_UNINSTALL_MANIFEST_PREFIX}{uuid4().hex}.json"
    )
    _assert_uninstall_manifest_quarantine_absent(config, manifest_quarantine)
    manifest_proof = _DirectFileProof(
        content=proof.manifest_bytes,
        identity=proof.manifest_identity,
    )
    tree_quarantined = False
    manifest_quarantined = False

    try:
        _rename_proven_tree(
            destination,
            quarantine,
            proof.tree,
            source_guard=lambda: (
                _require_install_roots(plugins, state_dir),
                _assert_destination_guard(
                    destination, plugins, mod_folder_name, must_exist=True
                ),
                _assert_owner_manifest_unchanged(config, proof),
            ),
            destination_guard=lambda: _assert_state_generated_tree(
                config,
                quarantine,
                quarantine_prefix,
                "uninstall quarantine",
                must_exist=False,
            ),
            label="owned uninstall tree",
            pre_rename_guard=lambda: _assert_target_game_not_running(
                config, "uninstall quarantine rename"
            ),
        )
        tree_quarantined = True
        _rename_proven_file(
            _manifest_path(config),
            manifest_quarantine,
            manifest_proof,
            source_guard=lambda: _assert_owner_manifest_unchanged(config, proof),
            destination_guard=lambda: _assert_uninstall_manifest_quarantine_absent(
                config, manifest_quarantine
            ),
            label="install ownership manifest",
        )
        manifest_quarantined = True
    except Exception as original_error:
        if (
            not tree_quarantined
            and not _path_lexists(destination)
            and _path_lexists(quarantine)
        ):
            tree_quarantined = True
        if (
            not manifest_quarantined
            and not _path_lexists(_manifest_path(config))
            and _path_lexists(manifest_quarantine)
        ):
            manifest_quarantined = True

        rollback_errors: list[str] = []
        owner_ready = not manifest_quarantined
        if manifest_quarantined:
            try:
                _rename_proven_file(
                    manifest_quarantine,
                    _manifest_path(config),
                    manifest_proof,
                    source_guard=lambda: _assert_uninstall_manifest_quarantine_proof(
                        config, manifest_quarantine, manifest_proof
                    ),
                    destination_guard=lambda: _assert_manifest_target_absent(config),
                    label="uninstall manifest rollback",
                )
                manifest_quarantined = False
                owner_ready = True
            except Exception as rollback_error:
                rollback_errors.append(str(rollback_error))
                owner_ready = False
        else:
            try:
                _assert_owner_manifest_unchanged(config, proof)
                owner_ready = True
            except Exception as rollback_error:
                rollback_errors.append(str(rollback_error))
                owner_ready = False

        if tree_quarantined and owner_ready and not _path_lexists(destination):
            try:
                _rename_proven_tree(
                    quarantine,
                    destination,
                    proof.tree,
                    source_guard=lambda: (
                        _require_install_roots(plugins, state_dir),
                        _assert_state_generated_tree(
                            config,
                            quarantine,
                            quarantine_prefix,
                            "uninstall quarantine",
                            must_exist=True,
                        ),
                    ),
                    destination_guard=lambda: _assert_destination_guard(
                        destination, plugins, mod_folder_name, must_exist=False
                    ),
                    label="uninstall quarantine rollback",
                    pre_rename_guard=lambda: _assert_target_game_not_running(
                        config, "uninstall quarantine rollback"
                    ),
                )
                tree_quarantined = False
            except Exception as rollback_error:
                rollback_errors.append(str(rollback_error))

        if rollback_errors:
            raise InstallError(
                "Uninstall failed and safe rollback was incomplete; preserved "
                "all unproven paths for manual recovery: "
                + "; ".join(rollback_errors)
            ) from original_error
        raise

    # Both active names are absent: uninstall is committed. Cleanup happens only
    # in the non-loadable repository state namespace.
    quarantine_removed = False
    try:
        quarantine_removed = _remove_proven_tree(
            quarantine,
            proof.tree,
            root_guard=lambda: (
                _require_install_roots(plugins, state_dir),
                _assert_state_generated_tree(
                    config,
                    quarantine,
                    quarantine_prefix,
                    "uninstall quarantine",
                    must_exist=True,
                ),
            ),
            label="committed uninstall quarantine",
            tombstone_parent=state_dir,
            tombstone_prefix=tombstone_prefix,
            tombstone_guard=lambda: _require_install_roots(plugins, state_dir),
            defer_cleanup_errors=True,
        )
    except Exception:
        pass
    if quarantine_removed:
        try:
            _unlink_uninstall_manifest_quarantine(
                config,
                manifest_quarantine,
                manifest_proof,
            )
        except Exception:
            pass
    return destination

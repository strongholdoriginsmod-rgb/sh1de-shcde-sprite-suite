"""Shared SDK selection policy for CLI, runtime builder and setup UI."""
from pathlib import Path
import json
import os
import re
import shutil

ROOT = Path(__file__).resolve().parents[2]


def sdk_minimum() -> str:
    return json.loads((ROOT / "global.json").read_text(encoding="utf-8"))["sdk"]["version"]


def sdk_supported(version: str) -> bool:
    """Match global.json latestMajor: any stable SDK at or above the minimum."""
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        return False
    actual = tuple(map(int, version.split(".")))
    minimum = tuple(map(int, sdk_minimum().split(".")))
    return actual >= minimum


def sdk_requirement() -> str:
    minimum = sdk_minimum()
    return f".NET SDK >= {minimum} (stable)"


def resolve_dotnet_directory(selection: Path) -> Path:
    """Accept the host folder, dotnet executable, or its sdk/version subfolder."""
    selected = selection.expanduser().resolve(strict=True)
    if selected.is_file():
        if selected.name.casefold() not in {"dotnet.exe", "dotnet"}:
            raise ValueError("Bitte dotnet.exe oder den .NET-Installationsordner auswählen.")
        return selected.parent
    candidates = [selected]
    if selected.name.casefold() == "sdk":
        candidates.append(selected.parent)
    elif selected.parent.name.casefold() == "sdk":
        candidates.append(selected.parent.parent)
    for candidate in candidates:
        if any((candidate / name).is_file() for name in ("dotnet.exe", "dotnet")):
            return candidate
    raise ValueError("Im gewählten SDK-Pfad fehlt dotnet.exe. Bitte den .NET-Installationsordner auswählen.")


def _redirected(path: Path) -> bool:
    """Do not auto-select SDK files behind a symbolic link or junction."""
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


def installed_sdk_versions(directory: Path) -> tuple[str, ...]:
    """Read stable installed SDKs without executing dotnet (a runtime is not an SDK)."""
    try:
        if not directory.is_dir() or _redirected(directory):
            return ()
        executable = directory / ("dotnet.exe" if os.name == "nt" else "dotnet")
        if not executable.is_file() or _redirected(executable):
            return ()
        sdk = directory / "sdk"
        if not sdk.is_dir() or _redirected(sdk):
            return ()
        return tuple(sorted(
            entry.name for entry in sdk.iterdir()
            if entry.is_dir() and not _redirected(entry) and sdk_supported(entry.name)
        ))
    except (OSError, ValueError):
        return ()


def find_dotnet_sdk(project_root: Path | None = None) -> Path | None:
    """Find an installed stable SDK: PATH, portable bundle, DOTNET_ROOT, system.

    Only detect executables on disk; the actual builder still probes
    dotnet --version before writing build output. No settings are changed.
    """
    root = project_root if project_root is not None else ROOT
    candidates: list[Path] = []
    executable = shutil.which("dotnet")
    if executable:
        candidates.append(Path(executable).parent)
    for value in os.environ.get("PATH", "").split(os.pathsep):
        if value.strip().strip('"'):
            candidates.append(Path(os.path.expandvars(value.strip().strip('"'))))
    packaged = root / "work" / "toolchains"
    if packaged.is_dir():
        candidates.extend(sorted(packaged.glob("dotnet-*"), reverse=True))
    for key in ("DOTNET_ROOT_X64", "DOTNET_ROOT"):
        if os.environ.get(key):
            candidates.append(Path(os.environ[key]))
    if os.name == "nt":
        for key in ("ProgramW6432", "ProgramFiles"):
            if os.environ.get(key):
                candidates.append(Path(os.environ[key]) / "dotnet")
    else:
        candidates.extend([Path("/usr/share/dotnet"), Path("/usr/local/share/dotnet")])
    inspected: set[Path] = set()
    for candidate in candidates:
        try:
            if _redirected(candidate):
                continue
            resolved = candidate.expanduser().resolve(strict=True)
            if resolved not in inspected:
                inspected.add(resolved)
                if installed_sdk_versions(resolved):
                    return resolved
        except (OSError, ValueError, RuntimeError):
            continue
    return None

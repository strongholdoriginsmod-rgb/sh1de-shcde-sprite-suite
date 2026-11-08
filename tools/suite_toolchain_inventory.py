"""Read-only, bounded Unity/Python environment inventory for SpriteSuite.

File presence is a candidate only; no candidate executable is started.
Actual Unity revision and Python interpreter compatibility are separate gates.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import stat
import sys


def safe(value: str | Path) -> Path | None:
    try:
        path = Path(value).expanduser().absolute()
        for node in (path, *path.parents):
            if not node.exists():
                continue
            if node.is_symlink() or (
                    getattr(node.lstat(), "st_file_attributes", 0)
                    & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
                return None
        return path
    except (ValueError, OSError, RuntimeError):
        return None


def unity_editors(environment: dict[str, str], explicit: str | None = None) -> list[dict]:
    """Only Unity Hub editor folders and explicitly named Unity.exe candidates."""
    root_list = []
    for variable in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)", "LOCALAPPDATA"):
        if (value := environment.get(variable)):
            parent = Path(value)
            root_list.extend((parent / "Unity" / "Hub" / "Editor",
                              parent / "Unity Hub" / "Editor"))
    if environment.get("SPRITESUITE_UNITY_HUB"):
        root_list.append(Path(environment["SPRITESUITE_UNITY_HUB"]))
    results = []
    def add(executable: Path, source: str):
        path = safe(executable)
        if not path or not path.is_file() or path.name.casefold() != "unity.exe":
            return
        version = path.parent.parent.name if path.parent.name.casefold() == "editor" else None
        if version and not re.fullmatch(r"[0-9]{4}\.[0-9]+\.[0-9]+[abfp][0-9]+", version):
            version = None
        results.append({"path": str(path), "source": source,
                        "version_hint": version,
                        "revision_verified": False, "executable_started": False})
    for name, value in (("saved_config", explicit),
                        ("environment", environment.get("STRONGHOLD_EUROPE_UNITY_EDITOR"))):
        if value:
            candidate = Path(value)
            if candidate.name.casefold() != "unity.exe":
                candidate /= "Editor" if candidate.name.casefold() != "editor" else ""
                candidate /= "Unity.exe"
            add(candidate, name)
    for source in root_list[:12]:
        root = safe(source)
        if not root or not root.is_dir():
            continue
        try:
            for child in sorted(root.iterdir(), key=lambda x: x.name.casefold())[:64]:
                if child.is_dir() and safe(child) is not None:
                    add(child / "Editor" / "Unity.exe", "unity_hub")
        except OSError:
            continue
    dedup: dict[str, dict] = {}
    for item in results:
        dedup.setdefault(os.path.normcase(item["path"]), item)
    return list(dedup.values())[:100]


def preferred_unity(candidates: list[dict], required: str = "2021.3.45f2") -> str | None:
    """A selection hint, not an attestation of the product version or revision."""
    for source in ("saved_config", "environment"):
        manual = [row for row in candidates if row["source"] == source]
        if manual:
            return manual[0]["path"] if len(manual) == 1 else None
    matching = [row for row in candidates if row["version_hint"] == required]
    if len(matching) == 1:
        return matching[0]["path"]
    if len(candidates) == 1:
        return candidates[0]["path"]
    return None


def python_interpreters(project: Path, environment: dict[str, str],
                        current_executable: str | None = None) -> list[dict]:
    """Enumerate known directories; never spawn python or modify PATH."""
    records = []
    def add(executable: str | Path, source: str):
        path = safe(executable)
        if path is None or not path.is_file() or path.name.casefold() not in (
                "python.exe", "pythonw.exe", "python"):
            return
        # Folder naming is an unverified hint, not the interpreter version.
        hint = None
        m = re.search(r"python(?:-|_)?(3)(1[3-5])\b", str(path), re.I)
        if m:
            hint = m[1] + "." + m[2]
        records.append({"path": str(path), "source": source,
                        "version_hint": hint,
                        "runtime_probed": source == "running_process",
                        "executable_started": False})
    add(current_executable or sys.executable, "running_process")
    for key in ("SPRITESUITE_PYTHON", "PYTHONHOME"):
        if environment.get(key):
            value = Path(environment[key])
            add(value if value.suffix.lower() == ".exe" else value / "python.exe", key)
    for root in (project, project.parent):
        for folder in (".venv", "venv"):
            add(root / folder / "Scripts" / "python.exe", "project_venv")
    if environment.get("VIRTUAL_ENV"):
        add(Path(environment["VIRTUAL_ENV"]) / "Scripts" / "python.exe", "active_venv")
    if environment.get("LOCALAPPDATA"):
        base = Path(environment["LOCALAPPDATA"]) / "Programs" / "Python"
        for version in ("313", "314", "315"):
            add(base / ("Python" + version) / "python.exe", "python_installer")
    if environment.get("ProgramFiles"):
        for version in ("313", "314", "315"):
            add(Path(environment["ProgramFiles"]) / ("Python" + version) / "python.exe",
                "python_installer")
    if environment.get("SYSTEMDRIVE"):
        for version in ("313", "314", "315"):
            add(Path(environment["SYSTEMDRIVE"] + os.sep) /
                ("Python" + version) / "python.exe", "portable_python")
    # PATH lookups are static filesystem hints; do not execute the results.
    for cmd in ("python", "python3"):
        if (found := shutil.which(cmd)):
            add(found, "path")
    unique = {}
    for row in records:
        unique.setdefault(os.path.normcase(row["path"]), row)
    return list(unique.values())[:30]

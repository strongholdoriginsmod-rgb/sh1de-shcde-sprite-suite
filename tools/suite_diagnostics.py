"""Export a minimal, opt-in local SpriteSuite diagnostic without private paths.

No network calls, credentials, filenames, game assets or raw tool output.
"""
from __future__ import annotations

from datetime import datetime,timezone
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import sys

from suite_windows_paths import is_link_or_reparse


SCHEMA="spritesuite.local-diagnostic.v1"
DEPENDENCIES=("Pillow","UnityPy","PySide6","numpy","scipy")
MAX_EXPORT_BYTES=64*1024


def _safe_present(path: Path) -> bool:
    return not is_link_or_reparse(path) and path.is_file()


def read_only_summary(root: Path) -> dict:
    root=Path(root)
    release=root/"PORTABLE-BUILD.json"
    version_file=root/"VERSION"
    version="unknown"
    if _safe_present(version_file) and version_file.stat().st_size<=100:
        version=version_file.read_text("utf8").strip()
    packages={}
    for pkg in DEPENDENCIES:
        try:
            packages[pkg]=metadata.version(pkg)
        except metadata.PackageNotFoundError:
            packages[pkg]="not-installed"
    return {
        "schema":SCHEMA,
        "created_utc":datetime.now(timezone.utc).isoformat(),
        "application_version":version,
        "runtime":{
            "python":f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "os_family":platform.system(),
            "architecture":platform.machine(),
            "dependencies":packages,
        },
        "configuration":{
            "game_paths_configured":_safe_present(root/"config"/"installations.local.toml"),
            "portable_build_manifest_present":_safe_present(release),
            "workspace_present":(
                (root/"work").is_dir() and not is_link_or_reparse(root/"work")
            ),
            "mapping_file_present":_safe_present(root/"work"/"mapping"/"proposals.json.gz"),
        },
        "provenance":{
            "privacy":"No raw logs, game file contents, user names or absolute paths",
            "in_game_approval":"not-proven-by-diagnostic",
            "release_approval":"not-proven-by-diagnostic",
        },
    }


def save_diagnostic(root: Path, destination: Path) -> dict:
    """Exclusive create; a diagnostic can never replace an existing file."""
    destination=Path(destination)
    if (destination.suffix.lower()!=".json"
            or is_link_or_reparse(destination)
            or is_link_or_reparse(destination.parent)
            or not destination.parent.is_dir()):
        raise ValueError("Diagnoseziel muss eine reguläre neue JSON-Datei sein")
    report=read_only_summary(root)
    encoded=(json.dumps(report,ensure_ascii=False,indent=2)+"\n").encode("utf8")
    if len(encoded)>MAX_EXPORT_BYTES:
        raise ValueError("Diagnosebericht ist unerwartet groß")
    with destination.open("xb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    return report

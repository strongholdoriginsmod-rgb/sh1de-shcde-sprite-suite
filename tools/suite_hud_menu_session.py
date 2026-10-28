"""Keep the last HUD/menu workspace and image across portable restarts.

Only a short, relative reference is stored inside SpriteSuite/work.
This is UI state, not an export manifest, and cannot change game files.
Untrusted or malformed state is ignored, never followed outside work.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path, PurePosixPath
import tempfile

import hud_menu_workspace as source

SCHEMA = "sprite-suite.hud-menu-last-session.v1"
NAME = ".hud-menu-last-session.json"
MAX_BYTES = 8192


def _location() -> Path:
    work = source.WORK
    if work.is_symlink():
        raise source.WorkshopError("Linked work directory cannot hold UI state")
    return work / NAME


def _project_part(path: str) -> str:
    if (not isinstance(path, str) or not path or "\\" in path
            or "\x00" in path or ":" in path or "//" in path):
        raise source.WorkshopError("Invalid recent-workspace path")
    pure = PurePosixPath(path)
    if pure.is_absolute() or not pure.parts or any(
        part in (".", "..") for part in path.split("/")
    ):
        raise source.WorkshopError("Recent workspace must be relative to work/")
    if len(path) > 512:
        raise source.WorkshopError("Recent workspace path too long")
    return path


def read_session() -> dict:
    """Fail closed: return an empty result if persisted data is untrusted."""
    try:
        location = _location()
        if location.is_symlink() or not location.is_file():
            return {}
        if location.stat().st_size > MAX_BYTES:
            return {}
        record = json.loads(location.read_text("utf8"))
        if not isinstance(record, dict) or record.get("schema") != SCHEMA:
            return {}
        relative = _project_part(record.get("workspace"))
        project = source.workspace(source.WORK / relative)
        if not project.is_dir():  # Deleted or moved workspace: use default.
            return {}
        asset = record.get("asset", "")
        if not isinstance(asset, str) or len(asset) > 1024:
            asset = ""
        if asset:
            try:
                source._relative(asset, patch=asset.startswith("Patches/"))
            except (ValueError, OSError):
                asset = ""
        scene = record.get("scene", "")
        if not isinstance(scene,str) or not (
            scene == "" or re.fullmatch(r"[A-Za-z0-9_-]{1,48}",scene)
        ):
            scene = ""
        return {"project": project, "asset": asset, "scene": scene}
    except (ValueError, OSError, UnicodeError, TypeError):
        return {}


def save_session(project: Path | str, asset: str | None = None,
                 scene: str | None = None) -> None:
    """Write checked relative references without discarding unrelated choices."""
    project = source.workspace(project)
    if not project.is_dir():
        raise source.WorkshopError("Cannot remember a missing workspace")
    rel = project.relative_to(source.WORK.resolve()).as_posix()
    _project_part(rel)
    previous = read_session()
    same = previous.get("project") == project
    if asset is None:
        asset = previous.get("asset", "") if same else ""
    if scene is None:
        scene = previous.get("scene", "") if same else ""
    if not isinstance(asset, str) or len(asset) > 1024:
        raise source.WorkshopError("Invalid selected asset")
    if asset:
        source._relative(asset, patch=asset.startswith("Patches/"))
    if not isinstance(scene,str) or not (
        scene == "" or re.fullmatch(r"[A-Za-z0-9_-]{1,48}",scene)
    ):
        raise source.WorkshopError("Invalid saved layout name")
    location = _location()
    if location.is_symlink():
        raise source.WorkshopError("Refusing linked UI state")
    if location.exists() and not location.is_file():
        raise source.WorkshopError("UI state destination is not a file")
    data = json.dumps(
        {"schema": SCHEMA, "workspace": rel, "asset": asset, "scene": scene},
        ensure_ascii=False, indent=2,
    ).encode("utf8") + b"\n"
    if len(data) > MAX_BYTES:
        raise source.WorkshopError("UI state too large")
    work = source.WORK
    work.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".hud-menu-session-", suffix=".tmp",
                                     dir=work)
    try:
        with os.fdopen(fd, "wb") as opened:
            opened.write(data)
            opened.flush()
            os.fsync(opened.fileno())
        # Windows and POSIX both atomically replace a regular destination.
        if location.is_symlink():
            raise source.WorkshopError("UI state became a link")
        os.replace(temporary, location)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

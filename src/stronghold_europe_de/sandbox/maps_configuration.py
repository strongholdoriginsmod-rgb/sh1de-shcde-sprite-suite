"""Persist the user's last deliberately selected original-map folder.

Priority: explicit Sandbox Studio selection -> configured target installation ->
project root (empty map catalogue, never a developer-only disk path).
Only the private config/sandbox-maps.local.json file is ever written.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import tomllib

SCHEMA = "stronghold-europe.sandbox.maps-root.v1"


def usable_maps_root(value: str | Path) -> bool:
    """Accept installed SHCDE root or a directory directly holding .map files."""
    root=Path(value)
    if not root.is_dir():
        return False
    native=(root/"Stronghold Crusader Definitive Edition_Data"/
            "StreamingAssets"/"Maps")
    return native.is_dir() or root.name.lower()=="maps" or any(root.glob("*.map"))


def _manual_maps_root(root: Path) -> Path | None:
    settings=root/"config"/"sandbox-maps.local.json"
    try:
        raw=json.loads(settings.read_text(encoding="utf-8"))
    except (OSError,ValueError,UnicodeError):
        return None
    if not isinstance(raw,dict) or raw.get("schema") != SCHEMA:
        return None
    location=raw.get("maps_root")
    if not isinstance(location,str) or not location.strip():
        return None
    candidate=Path(location).expanduser()
    if not candidate.is_absolute():
        candidate=root/candidate
    return candidate if usable_maps_root(candidate) else None


def configured_map_root(project_root: str | Path) -> Path:
    root=Path(project_root)
    chosen=_manual_maps_root(root)
    if chosen is not None:
        return chosen
    settings_path=root/"config"/"installations.local.toml"
    try:
        settings=tomllib.loads(settings_path.read_text(encoding="utf-8"))
        target=settings.get("target",{}).get("game_dir")
        if isinstance(target,str) and target.strip():
            game=Path(target).expanduser()
            if not game.is_absolute():
                game=root/game
            if usable_maps_root(game):
                return game
    except (OSError,ValueError,UnicodeError,TypeError,KeyError):
        pass
    return root


def save_maps_root(project_root: str | Path, chosen: str | Path) -> Path:
    root=Path(project_root)
    desired=Path(chosen).expanduser()
    if not desired.is_absolute():
        desired=root/desired
    desired=desired.resolve()
    if not usable_maps_root(desired):
        raise ValueError(
            "Hier wurden keine SHCDE-Originalkarten gefunden. "
            "Bitte den Spielordner oder einen Ordner mit .map-Dateien wählen."
        )
    settings_file=root/"config"/"sandbox-maps.local.json"
    settings_file.parent.mkdir(parents=True,exist_ok=True)
    payload=json.dumps(
        {"schema":SCHEMA,"maps_root":str(desired)},ensure_ascii=False,indent=2
    )+"\n"
    fd,temporary=tempfile.mkstemp(
        dir=settings_file.parent,prefix=".sandbox-maps-",suffix=".tmp"
    )
    try:
        with os.fdopen(fd,"w",encoding="utf-8",newline="\n") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary,settings_file)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return desired

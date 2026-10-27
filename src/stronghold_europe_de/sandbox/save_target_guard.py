"""Fail-closed guard for existing Sandbox sidecar JSON save destinations.

Only a schema-valid, compatible existing document may be atomically
replaced by a Sandbox writer. An existing malformed, foreign, future-schema
or symlink destination must NEVER be silently overwritten.

Validation is read-only. Writers still own serialization and atomic I/O.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Any
import json

MAX_EXISTING_SIDECAR_BYTES=64*1024*1024


def guard_existing_json(
    path: str | Path,
    validator: Callable[[dict], Any],
    error_type: type[ValueError],
    label: str,
) -> None:
    dest=Path(path)
    if dest.is_symlink():
        raise error_type(
            f"{label}: verknüpfte Speicherdateien werden nicht überschrieben"
        )
    if not dest.exists():
        return
    if not dest.is_file():
        raise error_type(f"{label}: Ziel ist keine normale Datei")
    if dest.stat().st_size > MAX_EXISTING_SIDECAR_BYTES:
        raise error_type(f"{label}: vorhandene Datei ist zu groß")
    try:
        with dest.open(encoding="utf-8") as stream:
            parsed=json.load(stream)
        validator(parsed)
    except (OSError,UnicodeError,ValueError,TypeError,KeyError) as exc:
        raise error_type(
            f"{label}: bestehende Datei ist nicht kompatibel oder beschädigt; "
            "sie bleibt unverändert. Ein anderes Speicherziel wählen."
        ) from exc

"""Read-only frame detail rows from a verified native BC7 proof.

The project-level proof is authoritative for the published group, but its
106 frame identities are much more useful when users can inspect individual
geometry/pivots and jump to the matching Asset Catalog frame.

This presentation module does *not* authorize build, install, or any writes.
"""
from __future__ import annotations

import math
import re

SCHEMA = "stronghold-europe.pivot-native-provenance.v1"
_GROUP = "anim_castle"
_FRAME_NAME = re.compile(r"anim_castle ([0-9]{3})\Z")
_ALLOWED = {
    ("REVIEW_MANUAL", "SOURCE_SH1DE"),
    ("KEEP_CRUSADER", "TARGET_SHCDE"),
}


class NativeProofRowsError(ValueError):
    pass


def catalog_frame_name(item: object) -> str | None:
    """Allow a double-click to open only a verified-looking native frame.

    An arbitrary diagnostic row (or an external report) must never launch a
    command or be interpreted as a file path. This helper only returns a
    bounded canonical Sprite Catalog name.
    """
    if not isinstance(item, dict) or item.get("pruefung") != "Nativ-Frame":
        return None
    if item.get("gruppe") != _GROUP:
        return None
    frames = item.get("frames")
    if not isinstance(frames, list) or len(frames) != 1:
        return None
    name = frames[0]
    if not isinstance(name, str):
        return None
    if _FRAME_NAME.fullmatch(name) is None:
        return None
    return name


def native_frame_rows(report: object) -> list[dict]:
    """Return individually navigable but read-only proven native frames.

    Reject incomplete/misordered/mixed-provenance outputs rather than
    displaying them as apparently legitimate original geometry.
    """
    if not isinstance(report, dict) or report.get("schema") != SCHEMA:
        raise NativeProofRowsError("Unbekannter nativer BC7-Beweis")
    group = report.get("group_proof")
    if not isinstance(group, dict) or group.get("group") != _GROUP:
        raise NativeProofRowsError("Nur anim_castle-Proof als Frame-Tabelle zugelassen")
    frames = group.get("frames")
    # Some synthetic tests inject summary-only proof fixtures. Real audit
    # results always include their entire frame list.
    if frames is None:
        return []
    if not isinstance(frames, list) or len(frames) != group.get("total_frames"):
        raise NativeProofRowsError("Native-Frame-Liste unvollständig")
    if not 0 < len(frames) <= 4096:
        raise NativeProofRowsError("Native-Frame-Anzahl außerhalb des Vertrags")
    rows, seen = [], set()
    source_count = keep_count = 0
    for value in frames:
        if not isinstance(value, dict):
            raise NativeProofRowsError("Ungültiger Originalframe")
        name = value.get("name")
        if not isinstance(name, str) or _FRAME_NAME.fullmatch(name) is None:
            raise NativeProofRowsError("Ungültiger Original-Frame-Name")
        if name in seen:
            raise NativeProofRowsError(f"Doppelter Originalframe: {name}")
        seen.add(name)
        action, origin = value.get("action"), value.get("origin")
        if (action, origin) not in _ALLOWED:
            raise NativeProofRowsError(f"Falsche Frameherkunft: {name}")
        size, pivot = value.get("geometry"), value.get("pivot")
        if (not isinstance(size, list) or len(size) != 2
            or any(type(v) is not int or not 0 < v <= 16384 for v in size)):
            raise NativeProofRowsError(f"Ungültige Frameabmessungen: {name}")
        if (not isinstance(pivot, list) or len(pivot) != 2
            or any(type(v) not in (int, float) or not math.isfinite(v)
                   or not -16 <= v <= 16 for v in pivot)):
            raise NativeProofRowsError(f"Ungültiger Framepivot: {name}")
        source_count += action == "REVIEW_MANUAL"
        keep_count += action == "KEEP_CRUSADER"
        source = ("SH1DE-Quellgrafik" if action == "REVIEW_MANUAL"
                  else "Original-Crusader-Fallback")
        detail = (
            f"{name}: {size[0]}×{size[1]} px, "
            f"Pivot ({pivot[0]:.8g}; {pivot[1]:.8g}); {source}. "
            f"Ausgelieferte Atlas-Geometrie geprüft. Doppelklick öffnet "
            f"den Frame im Katalog; es erfolgt keine Pivot-Änderung."
        )
        rows.append({
            "schwere": "info",
            "pruefung": "Nativ-Frame",
            "gruppe": _GROUP,
            "text": detail,
            "frames": [name],
            "daten": {
                "pivot": list(pivot),
                "groesse": list(size),
                "herkunft": origin,
                "source_path_id": value.get("source_path_id"),
                "target_path_id": value.get("target_path_id"),
            },
        })
    if (source_count != group.get("native_source_frames")
        or keep_count != group.get("target_keep_frames")):
        raise NativeProofRowsError("Frame-Provenienz stimmt nicht mit dem Gruppenbeweis")
    return rows

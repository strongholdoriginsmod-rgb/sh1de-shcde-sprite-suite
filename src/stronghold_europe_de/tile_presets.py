from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

from .tile_roundtrip import LAYOUTS


class TilePresetError(RuntimeError):
    """The semantic tile-layout catalog is malformed or ambiguous."""


@dataclass(frozen=True)
class TilePreset:
    id: str
    label: str
    group: str
    start: int
    end: int
    columns: int
    rows: int
    layout: str
    verification: str
    contract_sha256: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "group": self.group,
            "from": self.start,
            "to": self.end,
            "columns": self.columns,
            "rows": self.rows,
            "layout": self.layout,
            "verification": self.verification,
            "contract_sha256": self.contract_sha256,
        }


def _digest(entry: dict[str, Any]) -> str:
    payload = json.dumps(
        entry, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_tile_presets(path: Path) -> tuple[TilePreset, ...]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise TilePresetError(f"Tile-Presetkatalog ist nicht lesbar: {path}") from exc
    if not isinstance(document, dict) or set(document) != {"schema_version", "presets"}:
        raise TilePresetError("Tile-Presetkatalog hat unbekannte Felder")
    if document["schema_version"] != 1 or not isinstance(document["presets"], list):
        raise TilePresetError("Tile-Presetkatalog hat nicht Schema 1")
    required = {
        "id", "label", "group", "from", "to", "columns", "rows",
        "layout", "verification",
    }
    result: list[TilePreset] = []
    ids: set[str] = set()
    for position, entry in enumerate(document["presets"]):
        if not isinstance(entry, dict) or set(entry) != required:
            raise TilePresetError(f"Preset[{position}] ist unvollständig oder erweitert")
        try:
            start = int(entry["from"])
            end = int(entry["to"])
            columns = int(entry["columns"])
            rows = int(entry["rows"])
        except (TypeError, ValueError) as exc:
            raise TilePresetError(f"Preset[{position}] hat ungültige Zahlen") from exc
        preset_id = str(entry["id"])
        if not preset_id or preset_id in ids:
            raise TilePresetError(f"Preset-ID ist leer oder doppelt: {preset_id!r}")
        if start < 0 or end < start or columns <= 0 or rows <= 0:
            raise TilePresetError(f"Preset {preset_id} hat ungültigen Bereich/Raster")
        if end - start + 1 != columns * rows:
            raise TilePresetError(f"Preset {preset_id} füllt sein Raster nicht exakt")
        layout = str(entry["layout"])
        if layout not in LAYOUTS:
            raise TilePresetError(f"Preset {preset_id} hat unbekanntes Layout")
        verification = str(entry["verification"])
        if verification != "pixel-roundtrip-and-isometric-layout-verified":
            raise TilePresetError(f"Preset {preset_id} ist nicht zur Produktion freigegeben")
        ids.add(preset_id)
        result.append(
            TilePreset(
                id=preset_id,
                label=str(entry["label"]),
                group=str(entry["group"]),
                start=start,
                end=end,
                columns=columns,
                rows=rows,
                layout=layout,
                verification=verification,
                contract_sha256=_digest(entry),
            )
        )
    return tuple(result)

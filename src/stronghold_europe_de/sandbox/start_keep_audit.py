"""Read-only skirmish-start suitability based on real section-1013 keeps.

Only a verified type-41 keep is counted. Header hints or any castle model
are not substitutes for actual playable starts. Never write a map.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path

from .map_importer import inspect_map, MapFormatError
from .map_sections import load_original_buildings

START_KEEP_TYPE = 41


@dataclass(frozen=True)
class StartKeepAudit:
    map_name: str
    players: int | None
    map_type: int | None
    state: str
    starts: tuple[tuple[int, int, int], ...]
    message: str


def audit_start_keeps(path: str | Path) -> StartKeepAudit:
    """Report only what sections and headers prove; no guessed game fixes."""
    header = inspect_map(path)
    try:
        buildings=load_original_buildings(path)
    except (OSError, MapFormatError, ValueError) as exc:
        return StartKeepAudit(
            header.name,header.max_players,header.map_type,
            "unverifiziert",(),f"Sektion 1013 konnte nicht bestätigt werden: {exc}"
        )
    starts=tuple(sorted(
        (b.owner,b.x,b.y) for b in buildings if b.type_id==START_KEEP_TYPE
    ))
    players=header.max_players
    if header.map_type != 1:
        return StartKeepAudit(
            header.name,players,header.map_type,"kein_skirmish",starts,
            "Kein Skirmish-Kartentyp: Burgstarts nicht als Startbedingung bewerten."
        )
    if players is None or players <= 0:
        return StartKeepAudit(
            header.name,players,header.map_type,"unverifiziert",starts,
            "Spielerzahl im Kartenheader unbekannt oder ungültig."
        )
    owners=[owner for owner,_,_ in starts]
    expected=set(range(1,players+1))
    if len(starts)==players and set(owners)==expected:
        return StartKeepAudit(
            header.name,players,header.map_type,"passend",starts,
            f"{players} Spielerslots und exakt je eine Typ-41-Startburg."
        )
    return StartKeepAudit(
        header.name,players,header.map_type,"warnung",starts,
        f"{players} Spieler erwartet, aber {len(starts)} Typ-41-Burgstarts "
        f"mit Eigentümern {owners} gefunden. Keine automatische Reparatur."
    )

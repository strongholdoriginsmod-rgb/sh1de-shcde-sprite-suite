"""Read-only, provenance-labelled game HUD selection facts.

No Unity simulation or inferred asset-to-type mapping is performed here.
Each line comes from the currently loaded original map, selected work overlay,
or paused engine snapshot. Kept independent of Qt for precise unit tests.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HudContext:
    kind: str
    title: str
    brief: str
    detail: str
    source: str
    editable_overlay: bool = False

    @property
    def tooltip(self) -> str:
        return f"{self.title}\n{self.brief}\n{self.detail}\n{self.source}"


def describe_hud_context(canvas, *, tile=None, language="de") -> HudContext:
    """Resolve the *current* selection, never a cached and possibly stale ID."""
    en = language == "en"
    if not canvas.has_map():
        return HudContext(
            "none", "No original map" if en else "Keine Originalkarte",
            "Open a map in the editor" if en else "Originalkarte im Editor öffnen",
            "No simulation data" if en else "Keine Simulationsdaten",
            "No map source" if en else "Keine Kartenquelle",
        )
    selected = canvas.select_id()
    if selected:
        record = next(
            (obj for obj in canvas.history.overlay.objects if obj.id == selected),
            None,
        )
        if record is not None:
            return HudContext(
                "overlay", "Working overlay sprite" if en else "Arbeits-Overlay-Sprite",
                f"{record.group}/{record.frame} · ({record.x},{record.y})",
                (f"Team: {record.team} · ID: {record.id[:12]}" if en
                 else f"Team: {record.team} · ID: {record.id[:12]}"),
                "Editable copy; original map read-only"
                if en else "Arbeitskopie; Originalkarte nur lesen",
                editable_overlay=True,
            )
    original = canvas.selected_original()
    if original:
        kind, _code, record = original
        if kind == "building":
            return HudContext(
                "building", "Original building" if en else "Originalbauwerk",
                (f"Type ID {record.type_id} · Owner {record.owner}" if en
                 else f"Typ-ID {record.type_id} · Besitzer {record.owner}"),
                f"({record.x},{record.y}) · UID {record.uid} · "
                f"{'Record' if en else 'Datensatz'} {record.record_number}",
                "Original map section 1013 · read-only · sprite mapping unverified"
                if en else "Originalkarte Sektion 1013 · nur lesen · Grafikzuordnung offen",
            )
        if kind == "tree":
            return HudContext(
                "tree", "Original vegetation" if en else "Originalvegetation",
                (f"Raw group {record.raw_group} · ({record.x},{record.y})"
                 if en else f"Rohgruppe {record.raw_group} · ({record.x},{record.y})"),
                f"{'Record' if en else 'Datensatz'} {record.record_number} · "
                f"{'Variant' if en else 'Variante'} {record.raw_variant} · "
                f"{'State' if en else 'Zustand'} {record.raw_state}",
                "Original map section 1014 · read-only · sprite type unclassified"
                if en else "Originalkarte Sektion 1014 · nur lesen · Spriteart unbestätigt",
            )
    hit = canvas.last_engine_pick
    if hit is not None:
        return HudContext(
            "engine", "Engine snapshot graphic" if en else "Engine-Snapshot-Grafik",
            f"{hit.ref.group}/{hit.ref.frame} · ({hit.x},{hit.y})",
            f"{'Kind' if en else 'Art'}: {hit.kind} · GM {hit.source_file}/"
            f"{hit.source_frame}",
            "Paused original-engine command · shaders not verified"
            if en else "Pausierter Original-Engine-Befehl · Shader offen",
        )
    if tile is not None:
        x, y, values = tile
        # Only the raw channels actually returned by the current map.
        def value(channel):
            return str(values[channel]) if channel in values else "–"
        return HudContext(
            "tile", "Original tile" if en else "Originalkachel",
            f"({x},{y}) · 3005={value(3005)}",
            f"3004={value(3004)} · 3037={value(3037)}",
            "Original map raw tile channels · no inferred material"
            if en else "Originale Kachel-Rohkanäle · kein Material geraten",
        )
    return HudContext(
        "idle", "Original map" if en else "Originalkarte",
        "Click a tile or sprite" if en else "Kachel oder Sprite auswählen",
        "Camera follows the real minimap" if en
        else "Kamera folgt der echten Minikarte",
        "Paused engine snapshot; no economy simulation"
        if en else "Pausierter Engine-Snapshot; keine Wirtschaftssimulation",
    )



@dataclass(frozen=True)
class GameplayActionState:
    """Only enable actions backed by a real map, editor history and saved state."""
    loaded: bool
    placing: bool
    can_place: bool
    can_undo: bool
    can_redo: bool
    can_save: bool


def gameplay_action_state(studio) -> GameplayActionState:
    """Pure state projection; no mutation, disk writes or reconstructed economy."""
    canvas = studio.native_canvas
    if not canvas.has_map() or canvas.history is None:
        return GameplayActionState(False, False, False, False, False, False)
    group = studio.native_hud.group.currentText().strip()
    # A free-editable combo may temporarily contain an empty/invalid group.
    # Never offer to arm a placement which overlay validation would reject.
    import re
    valid_group = bool(re.fullmatch(r"[A-Za-z0-9_-]+", group))
    history = canvas.history
    saved = getattr(studio, "_saved_overlay", None)
    return GameplayActionState(
        loaded=True,
        placing=canvas._placing is not None,
        can_place=valid_group,
        can_undo=bool(history.undo_stack),
        can_redo=bool(history.redo_stack),
        can_save=(saved is not None and history.overlay.serialize() != saved),
    )

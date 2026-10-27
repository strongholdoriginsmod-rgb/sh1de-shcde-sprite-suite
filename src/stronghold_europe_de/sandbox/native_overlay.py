"""Persistent, undoable user-authored sprites over an authentic SHCDE map.

Overlay JSON deliberately contains no original map payloads and never writes
to the original .map. Tile positions are native 800-row isometric coordinates.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from pathlib import Path
import copy
import hashlib
import json
import os
import re
import tempfile
from uuid import uuid4

from .map_sections import tile_index
from .scene_model import SpritePlacement, SceneError, TEAM_COLOURS

OVERLAY_SCHEMA = "stronghold-europe.sandbox.map-overlay.v1"


@dataclass
class NativeOverlay:
    source_name: str
    source_sha256: str
    objects: list[SpritePlacement] = field(default_factory=list)

    def validate(self):
        if (not isinstance(self.source_name, str) or
                not self.source_name.lower().endswith(".map") or
                "/" in self.source_name or "\\" in self.source_name or
                self.source_name in (".", "..")):
            raise SceneError("Ungültiger Originalkartenname")
        if not re.fullmatch("[0-9a-f]{64}", self.source_sha256):
            raise SceneError("Ungültige Originalkarten-Prüfsumme")
        if len(self.objects) > 10_000:
            raise SceneError("Zu viele Kartenobjekte")
        ids = set()
        for item in self.objects:
            # Common reference checks, but no rectangular 64-tile editor limit.
            if (not isinstance(item.id, str) or
                    not re.fullmatch("[0-9a-f]{32}", item.id) or
                    not isinstance(item.group, str) or
                    len(item.group) > 256 or
                    not re.fullmatch("[A-Za-z0-9_-]+", item.group)):
                raise SceneError("Ungültige Sprite-ID oder -Gruppe")
            if type(item.frame) is not int or not 0 <= item.frame <= 999999:
                raise SceneError("Ungültiger Frame")
            if item.team not in TEAM_COLOURS:
                raise SceneError("Ungültige Teamfarbe")
            if type(item.x) is not int or type(item.y) is not int:
                raise SceneError("Kachelkoordinaten müssen Ganzzahlen sein")
            try:
                tile_index(item.x, item.y)
            except (IndexError, TypeError) as exc:
                raise SceneError(f"Objekt außerhalb der Originalkarte: {item.x},{item.y}") from exc
            if item.id in ids:
                raise SceneError("Doppelte Objekt-ID")
            ids.add(item.id)

    def serialize(self) -> dict:
        self.validate()
        return {"schema": OVERLAY_SCHEMA, "source_name": self.source_name,
                "source_sha256": self.source_sha256,
                "objects": [asdict(obj) for obj in self.objects]}

    @classmethod
    def deserialize(cls, payload: dict):
        if not isinstance(payload, dict) or payload.get("schema") != OVERLAY_SCHEMA:
            raise SceneError("Unbekanntes Originalkarten-Overlay")
        if set(payload) - {"schema", "source_name", "source_sha256", "objects"}:
            raise SceneError("Unbekannte Overlay-Kopffelder")
        entries = payload.get("objects")
        if not isinstance(entries, list):
            raise SceneError("Overlay-Objektliste ist ungültig")
        if len(entries) > 10_000:
            raise SceneError("Zu viele Kartenobjekte")
        fields = {"id", "group", "frame", "x", "y", "team"}
        try:
            objects = []
            for entry in entries:
                if not isinstance(entry, dict) or set(entry) - fields:
                    raise SceneError("Unbekannte Overlay-Objektfelder")
                objects.append(SpritePlacement(**entry))
            overlay = cls(payload["source_name"], payload["source_sha256"], objects)
            overlay.validate()
            return overlay
        except (KeyError, TypeError) as exc:
            raise SceneError(f"Ungültiges Overlay-Format: {exc}") from exc


def map_fingerprint(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(512 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def new_overlay(path: str | Path):
    path = Path(path)
    return NativeOverlay(path.name, map_fingerprint(path))


def save_overlay(path: str | Path, overlay: NativeOverlay):
    path = Path(path)
    if path.suffix.lower() != ".json":
        raise SceneError("Overlay wird ausschließlich als .json gespeichert")
    # Never erase a damaged map sidecar, another map's overlay or any other
    # settings/index JSON just because the user supplied the same extension.
    if path.is_symlink():
        raise SceneError("Verknüpfte Zieldateien werden nicht überschrieben")
    if path.exists():
        if not path.is_file():
            raise SceneError("Overlayziel ist keine normale Datei")
        try:
            with path.open(encoding="utf-8") as stream:
                previous = NativeOverlay.deserialize(json.load(stream))
        except (OSError, UnicodeError, ValueError, KeyError) as exc:
            raise SceneError(
                "Vorhandene Datei ist kein gültiges Karten-Overlay; "
                "sie bleibt unverändert. Bitte ein anderes Ziel wählen."
            ) from exc
        if (previous.source_name != overlay.source_name or
                previous.source_sha256 != overlay.source_sha256):
            raise SceneError(
                "Vorhandenes Overlay gehört zu einer anderen Kartenversion; "
                "es bleibt unverändert."
            )
    content = json.dumps(overlay.serialize(), ensure_ascii=False, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".overlay-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def load_overlay(path: str | Path, original_map: str | Path):
    with Path(path).open(encoding="utf-8") as stream:
        try:
            overlay = NativeOverlay.deserialize(json.load(stream))
        except (ValueError, UnicodeError, KeyError) as exc:
            raise SceneError(str(exc)) from exc
    original = Path(original_map)
    if overlay.source_name != original.name or overlay.source_sha256 != map_fingerprint(original):
        raise SceneError("Overlay gehört zu einer anderen Kartenversion")
    return overlay


class OverlayHistory:
    def __init__(self, overlay: NativeOverlay):
        overlay.validate()
        self.overlay = copy.deepcopy(overlay)
        self.undo_stack: list[NativeOverlay] = []
        self.redo_stack: list[NativeOverlay] = []

    def _update(self, fn):
        changed = copy.deepcopy(self.overlay)
        fn(changed)
        changed.validate()
        if changed.serialize() == self.overlay.serialize():
            return
        self.undo_stack.append(self.overlay)
        self.undo_stack = self.undo_stack[-100:]
        self.overlay = changed
        self.redo_stack.clear()

    def place(self, group: str, frame: int, x: int, y: int, team="rot"):
        ident = uuid4().hex
        self._update(lambda o: o.objects.append(SpritePlacement(ident, group, frame, x, y, team)))
        return ident

    def move(self, ident: str, x: int, y: int):
        def update(overlay):
            obj = next((o for o in overlay.objects if o.id == ident), None)
            if obj is None:
                raise SceneError("Unbekanntes Kartenobjekt")
            obj.x, obj.y = x, y
        self._update(update)

    def delete(self, ident: str):
        def update(overlay):
            previous = len(overlay.objects)
            overlay.objects = [o for o in overlay.objects if o.id != ident]
            if len(overlay.objects) == previous:
                raise SceneError("Unbekanntes Kartenobjekt")
        self._update(update)

    def set_properties(self, ident, *, frame=None, team=None):
        def update(overlay):
            obj = next((o for o in overlay.objects if o.id == ident), None)
            if obj is None:
                raise SceneError("Unbekanntes Kartenobjekt")
            if frame is not None:
                obj.frame = frame
            if team is not None:
                obj.team = team
        self._update(update)

    def undo(self):
        if self.undo_stack:
            self.redo_stack.append(self.overlay)
            self.overlay = self.undo_stack.pop()

    def redo(self):
        if self.redo_stack:
            self.undo_stack.append(self.overlay)
            self.overlay = self.redo_stack.pop()

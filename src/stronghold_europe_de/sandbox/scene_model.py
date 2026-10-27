"""Versioned, editable, isolated Sprite Suite sandbox scene.

Only sprite references and editor positions are stored; no copyrighted game
graphics or proprietary .map payloads are copied to this format.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
import copy
import json
import math
import os
import re
import tempfile
from uuid import uuid4

SCHEMA = "stronghold-europe.sandbox.scene.v2"
_GROUP = re.compile(r"^[A-Za-z0-9_\-]+$")
GRID_HALF_W = 32
GRID_HALF_H = 16
TOP_MARGIN = 128
MAX_DIMENSION = 64  # Test-field limit until chunk rendering is available
# Exact historical Sandkasten v1 TEAM_COLOURS keys, with the editable
# "keine" (no tint) option. Do not silently drop user-authored colours.
TEAM_COLOURS = frozenset((
    "keine", "rot", "blau", "gelb", "gruen",
    "orange", "lila", "tuerkis", "grau",
))


class SceneError(ValueError):
    """Invalid or unsupported editable sandbox data."""


def tile_anchor(x: int, y: int, height: int = 26) -> tuple[int, int]:
    return (height + x - y) * GRID_HALF_W + GRID_HALF_W, (
        TOP_MARGIN + (x + y) * GRID_HALF_H
    )


def tile_at(px: float, py: float, height: int = 26) -> tuple[int, int]:
    ox, oy = tile_anchor(0, 0, height)
    u = (px - ox) / GRID_HALF_W
    v = (py - oy) / GRID_HALF_H
    return math.floor((u + v) / 2 + 0.5), math.floor((v - u) / 2 + 0.5)


@dataclass
class SpritePlacement:
    id: str
    group: str
    frame: int
    x: int
    y: int
    team: str = "rot"

    def validate(self, width: int, height: int) -> None:
        if not isinstance(self.id, str) or not re.fullmatch(r"[0-9a-f]{32}", self.id):
            raise SceneError("Ungültige Objekt-ID")
        if (not isinstance(self.group, str) or len(self.group) > 256 or
                not _GROUP.fullmatch(self.group)):
            raise SceneError(f"Ungültige Sprite-Gruppe: {self.group!r}")
        # JSON true/false are Python bool, a subclass of int. They must
        # NEVER silently become a frame number or native tile position.
        if type(self.frame) is not int or not (0 <= self.frame <= 999_999):
            raise SceneError("Frame außerhalb des zulässigen Bereichs")
        if type(self.x) is not int or type(self.y) is not int:
            raise SceneError("Kachelpositionen müssen Ganzzahlen sein")
        if not (0 <= self.x < width and 0 <= self.y < height):
            raise SceneError(f"Objekt außerhalb des Rasters: {self.x},{self.y}")
        if self.team not in TEAM_COLOURS:
            raise SceneError(f"Unbekannte Teamfarbe {self.team}")


@dataclass
class EditableScene:
    name: str = "Grafik-Testfeld"
    width: int = 26
    height: int = 26
    objects: list[SpritePlacement] = field(default_factory=list)
    # Historical v1 payload is retained as-is, including seeded ground,
    # GM1 composite layout, per-object animation, titles and HUD state.
    legacy_payload: dict | None = field(default=None, repr=False)
    legacy_entries: dict[str, dict] = field(default_factory=dict, repr=False)

    @property
    def is_legacy_v1(self) -> bool:
        return self.legacy_payload is not None

    def _serialize_legacy(self) -> dict:
        from .legacy_v1_scene import validate_v1, replace_fields
        if self.legacy_payload is None:
            raise SceneError("Keine V1-Szene")
        raw=copy.deepcopy(self.legacy_payload)
        raw["name"]=self.name
        raw["karte"]=[self.width,self.height]
        try:
            raw["objekte"]=[
                replace_fields(self.legacy_entries[obj.id], obj)
                for obj in self.objects
            ]
            validate_v1(raw)
        except (KeyError, ValueError) as exc:
            raise SceneError(f"Historische V1-Szene ist ungültig: {exc}") from exc
        return raw

    def validate(self) -> None:
        if not isinstance(self.name, str) or not 1 <= len(self.name) <= 200:
            raise SceneError("Fehlender oder zu langer Szenenname")
        if type(self.width) is not int or not 1 <= self.width <= MAX_DIMENSION:
            raise SceneError("Ungültige Kartenbreite")
        if type(self.height) is not int or not 1 <= self.height <= MAX_DIMENSION:
            raise SceneError("Ungültige Kartenhöhe")
        if len(self.objects) > 10_000:
            raise SceneError("Zu viele Szenenobjekte")
        seen: set[str] = set()
        for sprite in self.objects:
            sprite.validate(self.width, self.height)
            if sprite.id in seen:
                raise SceneError("Doppelte Objekt-ID")
            seen.add(sprite.id)
        if self.is_legacy_v1:
            self._serialize_legacy()

    def serialize(self) -> dict:
        self.validate()
        if self.is_legacy_v1:
            return self._serialize_legacy()
        return {
            "schema": SCHEMA,
            "name": self.name,
            "width": self.width,
            "height": self.height,
            "objects": [asdict(obj) for obj in self.objects],
        }

    @classmethod
    def deserialize(cls, raw: dict) -> "EditableScene":
        if isinstance(raw,dict) and raw.get("schema")=="stronghold-europe.sandkasten.v1":
            from .legacy_v1_scene import validate_v1,copy_entries,legacy_id
            try:
                validate_v1(raw)
            except ValueError as exc:
                raise SceneError(f"Historische V1-Szene ungültig: {exc}") from exc
            entries=copy_entries(raw)
            objects=[
                SpritePlacement(
                    legacy_id(i),item["gruppe"],
                    item.get("von",0) if item["art"]=="kachelobjekt"
                    else item.get("frame",0),
                    item["x"],item["y"],item.get("team","rot")
                ) for i,item in enumerate(raw["objekte"])
            ]
            result=cls(raw["name"],*raw["karte"],objects,copy.deepcopy(raw),entries)
            result.validate()
            return result
        if not isinstance(raw, dict) or raw.get("schema") != SCHEMA:
            raise SceneError("Unbekanntes Szenenformat")
        # Future-schema/foreign metadata must not disappear when the user
        # opens and saves the file. Reject it until a migration can preserve
        # every field, rather than discarding it silently.
        if set(raw) - {"schema", "name", "width", "height", "objects"}:
            raise SceneError("Unbekannte Szenen-Kopffelder")
        allowed = {"id", "group", "frame", "x", "y", "team"}
        entries = raw.get("objects", [])
        if not isinstance(entries, list):
            raise SceneError("Objektliste ist ungültig")
        if len(entries) > 10_000:
            raise SceneError("Zu viele Szenenobjekte")
        try:
            objects = []
            for entry in entries:
                if not isinstance(entry, dict) or set(entry) - allowed:
                    raise SceneError("Objektdaten enthalten unbekannte Felder")
                objects.append(SpritePlacement(**entry))
            obj = cls(raw["name"], raw["width"], raw["height"], objects)
            obj.validate()
            return obj
        except (KeyError, TypeError) as exc:
            raise SceneError(f"Ungültiges Szenenschema: {exc}") from exc


def load_scene(path: str | Path) -> EditableScene:
    try:
        with Path(path).open(encoding="utf-8-sig") as source:
            return EditableScene.deserialize(json.load(source))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SceneError(str(exc)) from exc


def save_scene(path: str | Path, scene: EditableScene, *,
               allow_legacy_replace: bool = False) -> None:
    """Atomically save a scene; NEVER overwrite unrelated or damaged JSON."""
    path = Path(path)
    if path.suffix.lower() != ".json":
        raise SceneError("Szenen müssen als .json gespeichert werden")
    # Extension alone is NOT a type check: a user could select settings.json,
    # a catalogue index or an unrelated tool's output in Save As.
    # Protect those files *before* creating a temp file or directory.
    if path.is_symlink():
        raise SceneError("Verknüpfte Zieldateien werden nicht überschrieben")
    if path.exists():
        if not path.is_file():
            raise SceneError("Szenenziel ist keine normale Datei")
        try:
            existing=load_scene(path)  # full schema and record validation
            if existing.is_legacy_v1 != scene.is_legacy_v1:
                raise SceneError("V1- und V2-Szenen dürfen nicht gegenseitig überschrieben werden")
            if existing.is_legacy_v1 and not allow_legacy_replace:
                raise SceneError("V1-Original geschützt; nur explizit freigegebene Arbeitskopie ersetzen")
        except SceneError as exc:
            raise SceneError(
                "Vorhandene Datei ist keine gültige Testszene; "
                "sie bleibt unverändert. Bitte ein anderes Ziel wählen."
            ) from exc
    data = json.dumps(scene.serialize(), indent=2, ensure_ascii=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + path.name + "-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class SceneHistory:
    """Undo/redo with a maximum of 100 complete scene snapshots."""

    def __init__(self, scene: EditableScene | None = None):
        self.scene = scene or EditableScene()
        self.scene.validate()
        self._undo: list[EditableScene] = []
        self._redo: list[EditableScene] = []

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def _change(self, update) -> None:
        previous = copy.deepcopy(self.scene)
        candidate = copy.deepcopy(previous)
        update(candidate)
        candidate.validate()
        if candidate.serialize() == previous.serialize():
            return  # No undo entry for an unchanged inspector submission.
        self._undo.append(previous)
        self._undo = self._undo[-100:]
        self._redo.clear()
        self.scene = candidate

    def place(self, group: str, frame: int, x: int, y: int, team: str = "rot") -> str:
        ident = uuid4().hex
        def mutate(scene):
            scene.objects.append(SpritePlacement(ident, group, frame, x, y, team))
            if scene.is_legacy_v1:
                scene.legacy_entries[ident]=dict(
                    art="sprite",gruppe=group,frame=frame,x=x,y=y,team=team)
        self._change(mutate)
        return ident

    def move(self, ident: str, x: int, y: int) -> None:
        def mutate(scene):
            found = next((item for item in scene.objects if item.id == ident), None)
            if found is None:
                raise SceneError("Objekt ist nicht vorhanden")
            found.x, found.y = x, y
        self._change(mutate)

    def update(self, ident: str, *, x: int | None = None, y: int | None = None,
               frame: int | None = None, team: str | None = None) -> None:
        def mutate(scene):
            obj = next((entry for entry in scene.objects if entry.id == ident), None)
            if obj is None:
                raise SceneError("Objekt ist nicht vorhanden")
            for attr, value in (("x", x), ("y", y), ("frame", frame), ("team", team)):
                if value is not None:
                    setattr(obj, attr, value)
        self._change(mutate)

    def delete(self, ident: str) -> None:
        def mutate(scene):
            before = len(scene.objects)
            scene.objects = [p for p in scene.objects if p.id != ident]
            if before == len(scene.objects):
                raise SceneError("Objekt ist nicht vorhanden")
            if scene.is_legacy_v1:
                scene.legacy_entries.pop(ident,None)
        self._change(mutate)

    def legacy_set_scene_details(self, *, name: str | None = None,
                                 ground_group: str | None = None,
                                 ground_frames: list[int] | None = None,
                                 ground_seed: int | None = None,
                                 hud_visible: bool | None = None) -> None:
        def mutate(scene):
            if not scene.is_legacy_v1:
                raise SceneError("Nur historische V1-Szenen haben diese Daten.")
            if name is not None:
                scene.name=name
            if ground_group is not None or ground_frames is not None or ground_seed is not None:
                ground=scene.legacy_payload.setdefault("boden",
                    {"gruppe":"tile_land8","frames":[1],"saat":1})
                if ground_group is not None: ground["gruppe"]=ground_group
                if ground_frames is not None: ground["frames"]=list(ground_frames)
                if ground_seed is not None: ground["saat"]=ground_seed
            if hud_visible is not None:
                scene.legacy_payload.setdefault("hud",{})["sichtbar"]=hud_visible
        self._change(mutate)

    def legacy_update_object_details(self, ident: str, *, title: str | None = None,
                                     frame: int | None = None,
                                     columns: int | None = None, rows: int | None = None,
                                     layout: str | None = None, animation: dict | None = None,
                                     remove_animation: bool = False,
                                     alternate: bool | None = None) -> None:
        def mutate(scene):
            if not scene.is_legacy_v1 or ident not in scene.legacy_entries:
                raise SceneError("Historisches V1-Objekt nicht vorhanden")
            obj=scene.legacy_entries[ident]
            if frame is not None:
                record=next((o for o in scene.objects if o.id==ident),None)
                if record is None:raise SceneError("Objekt-ID nicht vorhanden")
                record.frame=frame
            if title is not None: obj["titel"]=title
            if obj["art"]=="kachelobjekt":
                if columns is not None: obj["spalten"]=columns
                if rows is not None: obj["zeilen"]=rows
                if layout is not None: obj["layout"]=layout
                if animation is not None or remove_animation or alternate is not None:
                    raise SceneError("GM1-Komposite unterstützen keine Sprite-Animation")
            else:
                if columns is not None or rows is not None or layout is not None:
                    raise SceneError("Sprite ist kein GM1-Komposit")
                if remove_animation: obj.pop("animation",None)
                elif animation is not None: obj["animation"]=copy.deepcopy(animation)
                if alternate is not None: obj["alt"]=alternate
        self._change(mutate)

    def undo(self) -> None:
        if self._undo:
            self._redo.append(self.scene)
            self.scene = self._undo.pop()

    def redo(self) -> None:
        if self._redo:
            self._undo.append(self.scene)
            self.scene = self._redo.pop()

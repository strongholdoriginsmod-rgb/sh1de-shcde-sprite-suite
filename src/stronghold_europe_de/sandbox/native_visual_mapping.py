"""User-confirmed visual mappings for native Stronghold objects.

Source record positions and numeric IDs are authoritative; sprite assignments
are not automatically guessed. They stay in an isolated versioned JSON file.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import json
import os
import re
import tempfile

from .save_target_guard import guard_existing_json

SCHEMA = "stronghold-europe.sandbox.original-visuals.v1"
VALID_KEY = re.compile(r"^(tree|building):([0-9]{1,5})$")
VALID_GROUP = re.compile(r"^[A-Za-z0-9_-]+$")


class VisualMappingError(ValueError):
    pass


@dataclass(frozen=True)
class SpriteVisual:
    group: str
    frame: int

    def validate(self):
        if (not isinstance(self.group, str) or len(self.group)>256 or
                not VALID_GROUP.fullmatch(self.group)):
            raise VisualMappingError("Ungültige Spritegruppe")
        if type(self.frame) is not int or not 0 <= self.frame <= 999999:
            raise VisualMappingError("Ungültige Framezahl")


@dataclass
class OriginalVisualMappings:
    assignments: dict[str, SpriteVisual] = field(default_factory=dict)

    @staticmethod
    def key(kind: str, code: int) -> str:
        if kind not in ("tree", "building") or type(code) is not int or not 0 <= code <= 65535:
            raise VisualMappingError("Ungültige Originalobjekt-ID")
        return f"{kind}:{code}"

    def validate(self):
        if not isinstance(self.assignments, dict) or len(self.assignments) > 500:
            raise VisualMappingError("Zu viele Spritezuordnungen")
        for key, value in self.assignments.items():
            match = VALID_KEY.fullmatch(key) if isinstance(key, str) else None
            if match is None:
                raise VisualMappingError(f"Unbekannter Originaltyp: {key}")
            if self.key(match.group(1), int(match.group(2))) != key:
                raise VisualMappingError(f"Nicht kanonische Originaltyp-ID: {key}")
            if not isinstance(value, SpriteVisual):
                raise VisualMappingError("Ungültige Zuordnung")
            value.validate()

    def assign(self, kind: str, code: int, group: str, frame: int):
        key = self.key(kind, code)
        visual = SpriteVisual(group, frame)
        visual.validate()
        self.assignments[key] = visual

    def unassign(self, kind: str, code: int):
        self.assignments.pop(self.key(kind, code), None)

    def get(self, kind: str, code: int) -> SpriteVisual | None:
        return self.assignments.get(self.key(kind, code))

    def serialize(self):
        self.validate()
        return {
            "schema": SCHEMA,
            "verification": "user-confirmed, not engine-guaranteed",
            "assignments": {
                key: {"group": v.group, "frame": v.frame}
                for key, v in sorted(self.assignments.items())
            },
        }

    @classmethod
    def deserialize(cls, raw):
        if not isinstance(raw, dict) or raw.get("schema") != SCHEMA:
            raise VisualMappingError("Unbekanntes Visual-Mapping-Format")
        if set(raw)-{"schema","verification","assignments"}:
            raise VisualMappingError("Unbekannte Visual-Mapping-Kopffelder")
        if (raw.get("verification",
                "user-confirmed, not engine-guaranteed") !=
                "user-confirmed, not engine-guaranteed"):
            raise VisualMappingError("Nicht unterstützte Original-Zuordnungsart")
        assignments = raw.get("assignments")
        if not isinstance(assignments, dict):
            raise VisualMappingError("Zuordnungen müssen ein Objekt sein")
        values = {}
        for key, record in assignments.items():
            if not isinstance(record, dict) or set(record) != {"group", "frame"}:
                raise VisualMappingError("Ungültige Eintragsfelder")
            values[key] = SpriteVisual(record["group"], record["frame"])
        mapped = cls(values)
        mapped.validate()
        return mapped


def load_mappings(path: str | Path):
    path = Path(path)
    if not path.is_file():
        return OriginalVisualMappings()
    try:
        return OriginalVisualMappings.deserialize(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise VisualMappingError(f"Originalgrafik-Zuordnungen konnten nicht gelesen werden: {exc}") from exc


def save_mappings(path: str | Path, mappings: OriginalVisualMappings):
    dest = Path(path)
    if dest.suffix.lower() != ".json":
        raise VisualMappingError("Zuordnungen nur als JSON speichern")
    raw = json.dumps(mappings.serialize(), ensure_ascii=False, indent=2) + "\n"
    guard_existing_json(
        dest, OriginalVisualMappings.deserialize, VisualMappingError,
        "Originalgrafik-Zuordnung"
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=dest.parent, prefix=".visuals-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, dest)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)

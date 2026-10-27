"""Explicit sandbox-only sprite assignments to *raw* SHCDE section-3005 bytes.

The numeric code is known; its actual material semantics remain unverified.
Overrides are bound to a specific SHA-256 original map and written atomically.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import tempfile

from .native_visual_mapping import SpriteVisual, VisualMappingError
from .save_target_guard import guard_existing_json

SCHEMA = "stronghold-europe.sandbox.native-terrain-test.v1"
_SHA = re.compile(r"[0-9a-f]{64}")


class TerrainMappingError(ValueError):
    pass


@dataclass
class TerrainTestMappings:
    source_sha256: str
    assignments: dict[int, SpriteVisual] = field(default_factory=dict)

    def validate(self):
        if not isinstance(self.source_sha256, str) or not _SHA.fullmatch(self.source_sha256):
            raise TerrainMappingError("Die Originalkarten-Prüfsumme fehlt oder ist ungültig")
        if not isinstance(self.assignments, dict) or len(self.assignments) > 256:
            raise TerrainMappingError("Zu viele Geländecode-Zuordnungen")
        for code, sprite in self.assignments.items():
            self._code(code)
            if not isinstance(sprite, SpriteVisual):
                raise TerrainMappingError("Ungültige Terrain-Grafik")
            try:
                sprite.validate()
            except VisualMappingError as exc:
                raise TerrainMappingError(str(exc)) from exc

    @staticmethod
    def _code(code):
        if type(code) is not int or not 0 <= code <= 255:
            raise TerrainMappingError("Original-Kanal 3005 hat nur Bytewerte von 0 bis 255")
        return code

    def assign(self, code, group, frame):
        self._code(code)
        candidate = SpriteVisual(group, frame)
        try:
            candidate.validate()
        except VisualMappingError as exc:
            raise TerrainMappingError(str(exc)) from exc
        self.assignments[code] = candidate

    def unassign(self, code):
        self.assignments.pop(self._code(code), None)

    def get(self, code):
        return self.assignments.get(self._code(code))

    def serialize(self):
        self.validate()
        return {
            "schema": SCHEMA,
            "source_sha256": self.source_sha256,
            "disclaimer": "Manual visual test of byte channel 3005, not a verified material mapping",
            "assignments": {
                str(code): {"group": sprite.group, "frame": sprite.frame}
                for code, sprite in sorted(self.assignments.items())
            },
        }

    @classmethod
    def deserialize(cls, raw, expected_sha256):
        if not isinstance(raw, dict) or raw.get("schema") != SCHEMA:
            raise TerrainMappingError("Unbekanntes Gelände-Testformat")
        if set(raw)-{"schema","source_sha256","disclaimer","assignments"}:
            raise TerrainMappingError("Unbekannte Terrain-Mapping-Kopffelder")
        if (raw.get("disclaimer",
                "Manual visual test of byte channel 3005, not a verified material mapping") !=
                "Manual visual test of byte channel 3005, not a verified material mapping"):
            raise TerrainMappingError("Nicht unterstützte Terrain-Testsemantik")
        if raw.get("source_sha256") != expected_sha256:
            raise TerrainMappingError("Geländezuordnung gehört zu einer anderen Kartenversion")
        values = raw.get("assignments")
        if not isinstance(values, dict) or len(values) > 256:
            raise TerrainMappingError("Ungültige Terrain-Zuordnungen")
        parsed = {}
        for key, record in values.items():
            if (not isinstance(key, str) or not key.isascii() or
                    not key.isdecimal() or str(int(key)) != key):
                raise TerrainMappingError("Ungültiger Bytecode-Schlüssel")
            code = cls._code(int(key))
            if not isinstance(record, dict) or set(record) != {"group", "frame"}:
                raise TerrainMappingError("Ungültiger Geländeframe-Eintrag")
            parsed[code] = SpriteVisual(record["group"], record["frame"])
        result = cls(expected_sha256, parsed)
        result.validate()
        return result


def load_terrain_tests(path, sha256):
    path = Path(path)
    if not path.is_file():
        return TerrainTestMappings(sha256)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise TerrainMappingError(f"Terrain-Testdatei nicht lesbar: {exc}") from exc
    return TerrainTestMappings.deserialize(data, sha256)


def save_terrain_tests(path, mappings):
    target = Path(path)
    if target.suffix.lower() != ".json":
        raise TerrainMappingError("Gelände-Testzuordnung nur als JSON speichern")
    text = json.dumps(mappings.serialize(), indent=2, ensure_ascii=False) + "\n"
    guard_existing_json(
        target,
        lambda raw: type(mappings).deserialize(raw, mappings.source_sha256),
        TerrainMappingError, "Originalkarten-Terrain-/Oberflächen-Test"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=target.parent, prefix=".terrain-test-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as output:
            output.write(text)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp, target)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)

"""Per-map *surface* sprite experiments for channel 3037, separate from
legacy section-3005 height experiments.

The native values (0, 1, 2, 8, 16, 64, 128) are verified on three SHCDE maps.
Which actual atlas frame each value draws in Unity remains unconfirmed.
"""
from .native_terrain_mapping import (
    TerrainTestMappings, TerrainMappingError, load_terrain_tests,
    save_terrain_tests, SCHEMA as LEGACY_SCHEMA
)

SURFACE_SCHEMA = "stronghold-europe.sandbox.native-surface-3037.v1"


class SurfaceTestMappings(TerrainTestMappings):
    def serialize(self):
        data = super().serialize()
        data["schema"] = SURFACE_SCHEMA
        data["section"] = 3037
        data["disclaimer"] = (
            "Experimental sprite choice for original 3037 texture bytes; "
            "not a verified Unity atlas/frame identity"
        )
        return data

    @classmethod
    def deserialize(cls, raw, expected_sha256):
        if (not isinstance(raw, dict) or raw.get("schema") != SURFACE_SCHEMA
                or raw.get("section") != 3037):
            raise TerrainMappingError("Unbekanntes Texturkanal-3037-Format")
        if set(raw)-{"schema","section","source_sha256","disclaimer","assignments"}:
            raise TerrainMappingError("Unbekannte Oberflächen-Mapping-Kopffelder")
        expected_disclaimer=(
            "Experimental sprite choice for original 3037 texture bytes; "
            "not a verified Unity atlas/frame identity"
        )
        if raw.get("disclaimer",expected_disclaimer)!=expected_disclaimer:
            raise TerrainMappingError("Nicht unterstützte Oberflächen-Testsemantik")
        # The parent validator deliberately knows ONLY section 3005 and
        # rejects unknown header fields. Remove section=3037 solely after
        # verifying the dedicated SURFACE_SCHEMA and its exact numeric code.
        legacy={k:v for k,v in raw.items() if k not in ("section","disclaimer")}
        legacy["schema"]=LEGACY_SCHEMA
        return super().deserialize(legacy, expected_sha256)


def load_surface_tests(path, source_sha256):
    # Legacy loader validates checksum and canonical code keys. Rewrite the
    # schema in memory only, never change existing JSON on disk.
    from pathlib import Path
    import json
    target = Path(path)
    if not target.is_file():
        return SurfaceTestMappings(source_sha256)
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise TerrainMappingError(f"3037-Texturtestdatei nicht lesbar: {exc}") from exc
    return SurfaceTestMappings.deserialize(raw, source_sha256)


def save_surface_tests(path, tests):
    if not isinstance(tests, SurfaceTestMappings):
        raise TerrainMappingError("Kein Texturexperiment der Originalsektion 3037")
    return save_terrain_tests(path, tests)


def provisional_surface_material(value: int) -> str:
    """Diagnostic-only classification supported by real radar colour regions.

    Ground-texture code 16 typically aligns with green/grass radar areas;
    1/128 are greener than 0/2; 8 and 64 coincide with tall rock/hill areas.
    The atlas group mapping itself is NOT yet reverse engineered.
    """
    if value in (1, 16, 128):
        return "grass"
    if value in (8, 64):
        return "rock"
    return "shore"

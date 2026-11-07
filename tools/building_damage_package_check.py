#!/usr/bin/env python3
"""Read-only compatibility and artwork check for the SpriteSuite live-damage runtime.

No arbitrary release gates: draft, rejected, custom versions and paths remain
usable. The report distinguishes actual image/binding faults from artistic
choices. C# runtime behavior must additionally be tested in the real game.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile, BadZipFile


def select_stage(stages: list[dict], hp: int, maximum: int, fire_history: bool):
    if maximum <= 0 or hp < 0:
        return None
    percent = 100 * min(hp, maximum) // maximum
    valid = [s for s in stages if type(s.get("hpAtOrBelow")) is int and
             0 <= s["hpAtOrBelow"] <= 99]
    kind = "fire" if fire_history and any(s.get("damageKind") == "fire" for s in valid) else "mechanical"
    candidates = [s for s in valid if s.get("damageKind") == kind]
    if kind == "fire" and percent >= 100:
        percent = max(s["hpAtOrBelow"] for s in candidates)
    options = [s for s in candidates if percent <= s["hpAtOrBelow"]]
    return min(options, key=lambda s: s["hpAtOrBelow"]) if options else None


class FireHistory:
    def __init__(self):
        self.burned = set()

    def update(self, global_id: int, hp: int, maximum: int, fire_ticks: int):
        if maximum <= 0 or global_id <= 0:
            return False
        if fire_ticks > 0:
            self.burned.add(global_id)
        elif hp >= maximum:
            self.burned.discard(global_id)
        return global_id in self.burned

    def clear(self):
        self.burned.clear()


def inspect_archive(archive_path: Path, runtime_settings: dict) -> dict:
    with ZipFile(archive_path) as archive:
        manifest = json.loads(archive.read("damage-manifest.json"))
        if not isinstance(manifest, dict) or not isinstance(manifest.get("buildings"), list):
            raise ValueError("No building library in damage-manifest.json")
        findings = []
        expected = 0
        stage_count = 0
        validated = 0
        groups = {}
        for building in manifest["buildings"]:
            group = building.get("id", "")
            groups[group] = building
            for stage in building.get("stages", []):
                stage_count += 1
                for tile in stage.get("tiles", []):
                    expected += 1
                    name = tile.get("image", "")
                    try:
                        raw = archive.read(name)
                    except KeyError:
                        findings.append({"type": "missing_art", "stage": stage.get("id"), "slot": tile.get("slot"), "image": name})
                        continue
                    if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
                        findings.append({"type": "invalid_png_signature", "image": name})
                        continue
                    digest = tile.get("sha256")
                    if digest and hashlib.sha256(raw).hexdigest().lower() != digest.lower():
                        findings.append({"type": "sha256_mismatch", "image": name})
                        continue
                    validated += 1
        matches = 0
        for binding in runtime_settings.get("bindings", []):
            group_id = binding.get("buildingGroupId")
            matching = [groups[group_id]] if group_id in groups else [
                b for b in groups.values() if not group_id and
                b.get("gameBuildingType") == binding.get("buildingType")]
            if not matching:
                findings.append({"type": "missing_building_group", "group": group_id})
                continue
            slots = [s.get("slot") for b in matching for stage in b.get("stages", [])
                     for s in stage.get("tiles", [])]
            if binding.get("slot") not in slots:
                findings.append({"type": "missing_damage_slot", "group": group_id,
                                 "slot": binding.get("slot")})
            else:
                matches += 1
            if (binding.get("sourceSprite", "").startswith("REPLACE_") or
                    group_id == "REPLACE_WITH_SHSPRITE_BUILDING_GROUP_ID"):
                findings.append({"type": "example_binding_not_configured", "group": group_id})
        return {
            "format": manifest.get("format"),
            "profiles": len(manifest["buildings"]),
            "stages": stage_count,
            "artEntries": expected,
            "validPngEntries": validated,
            "bindingsConfigured": len(runtime_settings.get("bindings", [])),
            "bindingsWithStageArt": matches,
            "findings": findings,
            "visualHpAndFireRuntimeTested": False,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--runtime-json", type=Path, required=True)
    args = parser.parse_args()
    try:
        settings = json.loads(args.runtime_json.read_text(encoding="utf-8"))
        report = inspect_archive(args.archive, settings)
    except (OSError, ValueError, BadZipFile, KeyError, TypeError) as exc:
        print("ERROR: " + str(exc))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

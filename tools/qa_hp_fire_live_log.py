#!/usr/bin/env python3
"""Analyze actual SHCDE HP/fire sprite application and Vanilla rollback logs.

Only reports witnessed events. Synthetic previews do not claim that gameplay
HP was damaged or that a visual screenshot has been examined.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys


PREFIX = "SPRITESUITE_DAMAGE|"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_events(log: str) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    for line in log.splitlines():
        if PREFIX not in line:
            continue
        payload = line.split(PREFIX, 1)[1]
        fields: dict[str, str] = {}
        for token in payload.split("|"):
            if "=" not in token:
                continue
            key, value = token.split("=", 1)
            if key in fields:
                raise ValueError("Duplicate runtime event field: " + key)
            fields[key] = value
        if fields.get("event"):
            events.append(fields)
    return events


def report(events: list[dict[str, str]]) -> dict:
    mechanical = set()
    fire = set()
    restored = set()
    stages = Counter()
    errors = []
    pending: dict[tuple[str, str, str, str], str] = {}
    full_cycles = 0
    configs = []
    applied = 0
    applied_slots = set()
    verified_slots = set()
    current_application = {}
    legacy_claims = 0
    previews = set()
    health_values = set()
    for index, event in enumerate(events):
        kind = event.get("event")
        if kind == "map_reset" or (kind == "host_awake" and event.get("phase") == "entered"):
            current_application.clear()
            pending.clear()
        if kind == "controls_reloaded":
            configs.append({k: event.get(k) for k in
                            ("enabled", "preview", "hp", "fire")})
        if kind == "host_awake" and event.get("phase") == "exception":
            errors.append("host_awake_exception")
        if kind not in ("stage_applied", "restored", "stage_tilemap_verified"):
            continue
        key = tuple(event.get(k, "") for k in
                    ("global_id", "building_id", "x", "y"))
        if any(not v for v in key):
            continue
        signature = tuple(event.get(name, "") for name in
                          ("stage", "live_hp", "live_max", "live_fire_ticks", "preview"))
        if kind == "stage_tilemap_verified":
            previous = current_application.get(key)
            if (event.get("tilemap_readback_matches") == "true" and
                    event.get("renderer_modified") == "true" and
                    previous is not None and previous[1] == signature):
                verified_slots.add(previous[0])
            else:
                errors.append("tilemap_readback_not_confirmed")
            continue
        if kind == "restored":
            current_application.pop(key, None)
            restored.add(key)
            if pending.pop(key, None) == "fire":
                full_cycles += 1
            continue
        applied += 1
        applied_slots.add(index)
        current_application[key] = (index, signature)
        stages[event.get("kind", "")] += 1
        previews.add(event.get("preview", ""))
        health_values.add((event.get("live_hp"), event.get("live_max"),
                           event.get("live_fire_ticks")))
        if event.get("sprite_field_written") != "true":
            if ("sprite_field_written" not in event and
                    event.get("renderer_modified") == "true"):
                legacy_claims += 1  # old format reports a field write as a render
            else:
                errors.append("non_write_applied_event")
        if event.get("kind") == "mechanical":
            mechanical.add(key)
            pending[key] = "mechanical"
        elif event.get("kind") == "fire":
            fire.add(key)
            if key in pending:
                pending[key] = "fire"
    common = mechanical & fire & restored
    preview_only = applied > 0 and previews == {"True"}
    return {
        "mechanicalApplyEvents": stages.get("mechanical", 0),
        "fireApplyEvents": stages.get("fire", 0),
        "otherApplyEvents": sum(value for key, value in stages.items()
                                if key not in ("mechanical", "fire")),
        "totalSpriteApplyEvents": applied,
        "vanillaRestoreEvents": sum(e.get("event") == "restored" for e in events),
        "uniqueMechanicalTiles": len(mechanical),
        "uniqueFireTiles": len(fire),
        "uniqueRestoredTiles": len(restored),
        "commonMechanicalFireRestoreTiles": len(common),
        "orderedCompletedTileCycles": full_cycles,
        "liveSettingsChanges": configs,
        "gameHpAndFireSamples": [{"hp": hp, "maximum": max_hp, "fireTicks": ticks}
                                 for hp, max_hp, ticks in sorted(health_values,
                                    key=lambda t: tuple(v or "" for v in t))],
        "appliedEventsArePreviewOnly": preview_only,
        "actualGameplayHpChangeProved": False,
        "screenPixelsVisuallyReviewed": False,
        "gameValueWritesByThisMod": False,
        "nativeSpriteFieldWritesObserved": applied > 0 and not errors,
        "legacyRendererClaimsWithoutTilemapReadback": legacy_claims,
        "tilemapReadbackVerifiedStageSlots": len(applied_slots & verified_slots),
        "nativeTilemapReadbackProved": (bool(applied_slots) and
                                     applied_slots <= verified_slots and not errors),
        "completePreviewCycleObserved": (preview_only and bool(common) and
                                          full_cycles == len(common) and
                                          mechanical == fire == restored and
                                          not errors),
        "auditErrors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--expected-sha256", help="Optional exact log provenance")
    parser.add_argument("--output", type=Path, help="Optional report JSON")
    args = parser.parse_args(argv)
    try:
        sha = sha256_file(args.log)
        if args.expected_sha256 and sha != args.expected_sha256.lower():
            raise ValueError("QA log SHA-256 does not match")
        result = report(parse_events(
            args.log.read_text(encoding="utf-8", errors="replace")))
        result["logSHA256"] = sha
        result["sourceLog"] = str(args.log)
        encoded = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            args.output.write_text(encoded, encoding="utf-8")
        print(encoded, end="")
        return 0
    except (OSError, ValueError, UnicodeError) as e:
        print("Runtime log audit: " + str(e), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

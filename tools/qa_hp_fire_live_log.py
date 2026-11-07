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
    previews = set()
    health_values = set()
    for event in events:
        kind = event.get("event")
        if kind == "controls_reloaded":
            configs.append({k: event.get(k) for k in
                            ("enabled", "preview", "hp", "fire")})
        if kind == "host_awake" and event.get("phase") == "exception":
            errors.append("host_awake_exception")
        if kind not in ("stage_applied", "restored"):
            continue
        key = tuple(event.get(k, "") for k in
                    ("global_id", "building_id", "x", "y"))
        if any(not v for v in key):
            continue
        if kind == "restored":
            restored.add(key)
            if pending.pop(key, None) == "fire":
                full_cycles += 1
            continue
        applied += 1
        stages[event.get("kind", "")] += 1
        previews.add(event.get("preview", ""))
        health_values.add((event.get("live_hp"), event.get("live_max"),
                           event.get("live_fire_ticks")))
        if event.get("renderer_modified") != "true":
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

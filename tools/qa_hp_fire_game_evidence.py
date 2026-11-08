#!/usr/bin/env python3
"""Check a single opt-in SHCDE health canary run against its native renderer evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct

from qa_hp_fire_live_log import PREFIX as RUNTIME_PREFIX, sha256_file

HEALTH_PREFIX = "SPRITESUITE_HEALTH_QA|"
MECHANICAL = "SpriteSuite:qa_mechanical75:"
FIRE = "SpriteSuite:qa_fire40:"
ORIGINAL = "original"
# Phase, percentage of maximum HP, active fire, expected sprite, screenshot.
PHASES = (
    ("Baseline", 100, False, ORIGINAL, True),
    ("Mechanical", 60, False, MECHANICAL, True),
    ("Burning", 30, True, FIRE, True),
    ("Extinguished", 35, False, FIRE, True),
    ("Repaired", 100, False, ORIGINAL, True),
    ("BeforeReload", 30, True, FIRE, False),
    ("ReloadBaseline", 100, False, ORIGINAL, True),
    ("ReloadMechanical", 60, False, MECHANICAL, True),
    ("ReloadRepaired", 100, False, ORIGINAL, False),
    ("NewBaseline", 100, False, ORIGINAL, True),
    ("NewMechanical", 60, False, MECHANICAL, True),
    ("NewRepaired", 100, False, ORIGINAL, False),
    ("Cleanup", 100, False, ORIGINAL, False),
)


def parse(log: str) -> tuple[list[dict], list[dict]]:
    health, runtime = [], []
    for index, line in enumerate(log.splitlines()):
        for prefix, target in ((HEALTH_PREFIX, health), (RUNTIME_PREFIX, runtime)):
            if prefix not in line:
                continue
            entry = {"logLine": index + 1}
            for token in line.split(prefix, 1)[1].split("|"):
                if "=" not in token:
                    continue
                name, value = token.split("=", 1)
                if name in entry:
                    raise ValueError(f"Duplicate event field {name!r} on line {index + 1}")
                entry[name] = value
            target.append(entry)
            break
    return health, runtime


def png_receipt(path: Path, declared_width: int, declared_height: int) -> dict:
    raw = path.read_bytes()
    if (len(raw) < 45 or raw[:16] != b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR" or
            raw[-12:] != b"\0\0\0\0IEND\xaeB`\x82"):
        raise ValueError("Screenshot is not a complete PNG")
    width, height = struct.unpack(">II", raw[16:24])
    if (width, height) != (declared_width, declared_height) or width < 1 or height < 1:
        raise ValueError("Screenshot dimensions do not match the render request")
    return {"file": path.name, "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw), "width": width, "height": height}


def evaluate(log: str, evidence_root: Path, save_sha256: str) -> dict:
    save_sha256 = save_sha256.lower()
    if not re.fullmatch(r"[a-f0-9]{64}", save_sha256):
        raise ValueError("An exact QA save SHA-256 is required")
    health, runtime = parse(log)
    errors = []
    screenshots = {}
    start = [e for e in health if e.get("event") == "started"]
    end = [e for e in health if e.get("event") == "completed"]
    failed = [e for e in health if e.get("event") in
              {"failed", "disabled", "restore_failed", "discard_session_required"}]
    if failed:
        errors.append("Health canary reported an unsuccessful phase")
    if (len(start) != 1 or start[0].get("save_sha256") != save_sha256 or
            start[0].get("mode") != "in_memory_api_values"):
        errors.append("Expected one run using the pinned QA save and actual in-memory API values")
    if len(end) != 1 or end[0].get("unchanged_save_sha256") != save_sha256:
        errors.append("No completion with the unchanged QA save")
    folder = start[0].get("evidence", "") if len(start) == 1 else ""
    evidence = None
    if re.fullmatch(r"hp-fire-[a-f0-9]{32}", folder):
        candidate = evidence_root / folder
        if candidate.resolve().parent == evidence_root.resolve() and not candidate.is_symlink():
            evidence = candidate
    if evidence is None:
        errors.append("Missing safe run-specific evidence directory")

    observations = [e for e in health if e.get("event") == "observed"]
    phase_order = [e.get("phase") for e in observations]
    if phase_order != [phase[0] for phase in PHASES]:
        errors.append("Missing, repeated or out-of-order health/render observations")
    by_phase = {e.get("phase"): e for e in observations}
    requested = [e for e in health if e.get("event") == "screenshot_requested"]
    previous_line = start[0]["logLine"] if len(start) == 1 else 0
    for phase, percent, burning, stage, require_image in PHASES:
        sample = by_phase.get(phase)
        if not sample:
            continue
        line = sample["logLine"]
        try:
            maximum, hp, fire, baseline, field_count, rendered = (int(sample[key]) for key in
                ("max", "hp", "fire_ticks", "baseline_tiles", "field_matches", "rendered_matches"))
            if (sample["type"] != "104" or hp != maximum * percent // 100 or
                    maximum <= 0 or fire < 0 or (fire > 0) != burning or
                    baseline < 1 or rendered != baseline or field_count != baseline or
                    sample["stage"] != stage):
                raise ValueError("incorrect gameplay values or renderer match")
            # Fire retention after extinguishing is a continuing render state.
            # All phases that newly apply a replacement need corroboration from
            # the production runtime, using the same actual native values.
            if stage != ORIGINAL and phase != "Extinguished":
                matching = [e for e in runtime if previous_line < e["logLine"] < line and
                    e.get("event") == "stage_applied" and e.get("preview") == "False" and
                    e.get("sprite_field_written") == "true" and
                    e.get("global_id") == sample["global_id"] and
                    e.get("building_id") == sample["building_id"] and
                    e.get("live_hp") == str(hp) and e.get("live_max") == str(maximum) and
                    (int(e.get("live_fire_ticks", "-1")) > 0 if burning else
                     e.get("live_fire_ticks") == "0") and
                    stage == "SpriteSuite:" + e.get("stage", "") + ":"]
                # A logged GameMapTile field assignment does not establish
                # that Unity's Tilemap actually returned the new Sprite.
                readbacks = [e for e in runtime if previous_line < e["logLine"] < line and
                    e.get("event") == "stage_tilemap_verified" and
                    e.get("preview") == "False" and
                    e.get("tilemap_readback_matches") == "true" and
                    e.get("renderer_modified") == "true" and
                    e.get("global_id") == sample["global_id"] and
                    e.get("building_id") == sample["building_id"] and
                    e.get("live_hp") == str(hp) and e.get("live_max") == str(maximum) and
                    (int(e.get("live_fire_ticks", "-1")) > 0 if burning else
                     e.get("live_fire_ticks") == "0") and
                    stage == "SpriteSuite:" + e.get("stage", "") + ":"]
                if not matching or not any(
                    a["logLine"] < r["logLine"] and
                    a.get("x") not in (None, "") and a.get("y") not in (None, "") and
                    a.get("x") == r.get("x") and a.get("y") == r.get("y")
                    for a in matching for r in readbacks
                ):
                    raise ValueError("no matching non-preview field write and native tilemap readback")
            if require_image:
                captures = [e for e in requested if e.get("phase") == phase]
                if (evidence is None or len(captures) != 1 or captures[0]["logLine"] <= line or
                        captures[0].get("file") != phase + ".png"):
                    raise ValueError("screenshot request missing or inconsistent")
                path = evidence / (phase + ".png")
                if path.is_symlink() or path.resolve().parent != evidence.resolve():
                    raise ValueError("screenshot leaves the run directory")
                screenshots[phase] = png_receipt(path, int(captures[0]["width"]),
                                                 int(captures[0]["height"]))
        except (KeyError, ValueError, OSError) as exc:
            errors.append(f"{phase}: {exc}")
        previous_line = line

    if phase_order == [phase[0] for phase in PHASES]:
        def identity(phase: str) -> tuple[str | None, str | None]:
            sample = by_phase[phase]
            return sample.get("building_id"), sample.get("global_id")

        first = identity("Baseline")
        reloaded = identity("ReloadBaseline")
        new = identity("NewBaseline")
        cleanup = identity("Cleanup")
        if (first[1] != "661027" or reloaded[1] != first[1] or cleanup[1] != first[1] or
                not all(first) or not all(reloaded) or not all(cleanup) or not all(new) or
                new[1] in {first[1], "0"} or
                any(identity(phase) != first for phase in
                    ("Mechanical", "Burning", "Extinguished", "Repaired", "BeforeReload")) or
                any(identity(phase) != reloaded for phase in ("ReloadMechanical", "ReloadRepaired")) or
                any(identity(phase) != new for phase in ("NewMechanical", "NewRepaired"))):
            errors.append("The recorded observations do not prove distinct original and rebuilt identities")
        for phase in ("Baseline", "ReloadBaseline", "Cleanup"):
            loads = [e for e in health if e.get("event") == "load_requested" and
                     e.get("phase") == phase and e.get("save_sha256") == save_sha256]
            posts = [e for e in health if e.get("event") == "save_post" and
                     e.get("phase") == phase and e.get("save_sha256") == save_sha256]
            if len(loads) != 1 or not any(loads[0]["logLine"] < e["logLine"] <
                                         by_phase[phase]["logLine"] for e in posts):
                errors.append(f"{phase}: no matching native save-load completion")
        deleted = [e for e in health if e.get("event") == "removed" and
                   e.get("global_id") == reloaded[1] and e.get("building_id") == reloaded[0] and
                   e.get("tile_owner") == "0"]
        spawned = [e for e in health if e.get("event") == "create_requested" and
                   e.get("previous_global_id") == reloaded[1] and e.get("previous_id") == reloaded[0]]
        if (len(deleted) != 1 or len(spawned) != 1 or not
                by_phase["ReloadRepaired"]["logLine"] < deleted[0]["logLine"] <
                spawned[0]["logLine"] < by_phase["NewBaseline"]["logLine"]):
            errors.append("Native removal and creation evidence is missing or out of order")
        if not any(e.get("event") == "map_reset" and
                   by_phase["BeforeReload"]["logLine"] < e["logLine"] <
                   by_phase["ReloadBaseline"]["logLine"] for e in runtime):
            errors.append("Production runtime did not report a map-state reset during reload")
    if len(start) == len(end) == 1 and observations:
        if not start[0]["logLine"] < observations[0]["logLine"] <= observations[-1]["logLine"] < end[0]["logLine"]:
            errors.append("Phase observations fall outside the completed run")

    return {
        "canarySequenceProved": not errors,
        "healthChangesSource": "controlled SHCDE-SE writes to real gameplay fields",
        "visualReviewPerformed": False,
        "saveSHA256": save_sha256,
        "phasesObserved": observations,
        "screenshots": screenshots,
        "failures": failed,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--save-sha256", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = evaluate(args.log.read_text(encoding="utf-8", errors="replace"),
                          args.evidence_root, args.save_sha256)
        report["logSHA256"] = sha256_file(args.log)
        output = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
        if args.output:
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(output)
        print(output, end="")
        return 0 if report["canarySequenceProved"] else 1
    except (OSError, ValueError) as error:
        parser.exit(2, f"{error}\n")


if __name__ == "__main__":
    raise SystemExit(main())

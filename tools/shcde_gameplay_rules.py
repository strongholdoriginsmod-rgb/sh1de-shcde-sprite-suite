#!/usr/bin/env python3
"""Build and configure real SHCDE unit health, building health and combat range.

The selected installed Script Extender actually exposes:
GameUnitManagerAPI.SetDefaultHealth(eChimps,uint),
GameBuildingManagerAPI.SetDefaultHealth(eStructs,uint), and
GameUnitManagerAPI.SetUnitAttackRange(eChimps,int).

The runtime only changes values after the mod author explicitly installs it
and supplies rules.tsv. Gameplay changes in multiplayer require all peers to
run compatible rule sets; this command does not invent network synchronization.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from shcde_managed_builder import compile_managed, install_managed, remove_managed

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "runtime" / "SpriteSuite.ShcdeGameplay" / "GameplayRules.cs"
PLUGIN = "SpriteSuiteGameplayRules"
DLL = "SpriteSuite.ShcdeGameplay.dll"
SCHEMA = "spritesuite.shcde.gameplay-rules.v1"
TEMPLATE = (
    "# kind\tunit-or-building-type-ID\tvalue\n"
    "# unit-hp\t12\t1000\n"
    "# building-hp\t44\t5000\n"
    "# unit-range\t12\t12\n"
)


def parse_rules(source: str) -> list[dict]:
    results = []
    for number, raw in enumerate(source.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) != 3 or fields[0] not in ("unit-hp", "building-hp", "unit-range"):
            raise ValueError("Expected kind, type and value in TSV on line " + str(number))
        try:
            type_id, value = int(fields[1]), int(fields[2])
        except ValueError as exc:
            raise ValueError("Non-integer ID/value at line " + str(number)) from exc
        if not (-2**31 <= type_id < 2**31) or not (0 <= value < 2**32):
            raise ValueError("Value outside actual .NET API integer width")
        if fields[0] == "unit-range" and value > 2**31 - 1:
            raise ValueError("Unit range must fit engine Int32")
        results.append({"kind": fields[0], "type": type_id, "value": value})
    return results


def manifest(spec: dict) -> str:
    if not isinstance(spec, dict) or not isinstance(spec.get("rules"), list):
        raise ValueError("Rules JSON must have a rules array")
    rows = ["# SpriteSuite editable runtime gameplay rules", "# kind\\ttype\\tvalue"]
    for item in spec["rules"]:
        row = [str(item.get(k, "")) for k in ("kind", "type", "value")]
        # Exact TSV grammar, no user value may introduce a new rule.
        if any(any(ch in cell for ch in "\t\r\n") for cell in row):
            raise ValueError("A rule field contains control characters")
        rows.append("\t".join(row))
    output = "\n".join(rows) + "\n"
    parse_rules(output)
    return output


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    subs = p.add_subparsers(dest="action", required=True)
    build = subs.add_parser("build")
    build.add_argument("--game", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--rules", type=Path)
    build.add_argument("--install", action="store_true")
    remove = subs.add_parser("remove")
    remove.add_argument("--game", type=Path, required=True)
    check = subs.add_parser("inspect")
    check.add_argument("--rules", type=Path, required=True)
    new = subs.add_parser("create")
    new.add_argument("--spec", type=Path, required=True)
    new.add_argument("--output", type=Path, required=True)
    args = p.parse_args(argv)
    try:
        if args.action == "remove":
            result = remove_managed(args.game, PLUGIN)
        elif args.action == "inspect":
            rows = parse_rules(args.rules.read_text(encoding="utf-8-sig"))
            result = {"schema": SCHEMA, "rules": rows,
                      "gameNotModified": True, "networkSynchronizationImplemented": False}
        elif args.action == "create":
            contents = manifest(json.loads(args.spec.read_text(encoding="utf-8-sig")))
            with args.output.open("x", encoding="utf-8", newline="\n") as file:
                file.write(contents)
            result = {"output": str(args.output), "rules": len(parse_rules(contents))}
        else:
            target = args.output / DLL
            result = compile_managed(args.game, SOURCE, target)
            if args.install:
                own = args.rules.read_bytes() if args.rules else TEMPLATE.encode("utf-8")
                parse_rules(own.decode("utf-8-sig"))
                metadata = {
                    "GUID": "org.spritesuite.shcde.gameplay",
                    "Author": "SpriteSuite",
                    "Name": "SpriteSuite Gameplay Rules",
                    "Description": "Creator-defined unit, building and combat rules",
                    "Version": "0.1.0", "Manifest": 1, "NetworkMode": 1,
                }
                result.update(install_managed(args.game, PLUGIN, target, metadata,
                                              files={"rules.tsv": own}))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print("SHCDE gameplay rules: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

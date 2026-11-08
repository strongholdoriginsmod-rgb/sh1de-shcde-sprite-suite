#!/usr/bin/env python3
"""Aggregate actual SHCDE/Script Extender timing logs, including pathing stalls.

This does not manufacture per-function durations from native baselines.
Native flow names can be joined through the separate hash-bound baseline tool.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import csv
import json
import math
from pathlib import Path
import re
import statistics
import sys

NUM = r"(?:[0-9]+(?:\.[0-9]+)?)"
VALUE = re.compile(r"\b(?:duration_ms|elapsed_ms|elapsedMs|timeMs|latency_ms|spent_ms)=" + r"(" + NUM + r")", re.I)
HUMAN = re.compile(r"\b(?:in|took|elapsed)\s+(" + NUM + r")\s*ms\b", re.I)
MEASURE_NAME = re.compile(r"\b(?:operation|context|stage|event|function|function_name)=([^\s|]+)", re.I)
CATEGORIES = {
    "pathing": ("path", "route", "pcl", "component", "chore", "move", "assassin", "pathfind"),
    "ai": ("aiv", "ai ", "castleplan", "chore", "hunter", "woodcutter", "trade_ai"),
    "render": ("tile", "sprite", "render", "noesis", "graphics", "atlas", "texture"),
    "economy": ("market", "price", "resource", "farm", "stock", "trade", "cost"),
    "network": ("steam", "network", "sync", "packet", "multiplayer"),
}


def classify(line: str) -> str:
    value = line.casefold()
    for kind, terms in CATEGORIES.items():
        if any(term in value for term in terms):
            return kind
    return "other"


def quantile(sorted_values: list[float], proportion: float) -> float:
    if not sorted_values:
        return 0.0
    index = max(0, math.ceil(proportion * len(sorted_values)) - 1)
    return sorted_values[index]


def parse_measurements(text: str, *, category: str | None = None) -> list[dict]:
    entries: list[dict] = []
    for number, line in enumerate(text.splitlines(), 1):
        value = VALUE.search(line)
        if value is None:
            value = HUMAN.search(line)
        if value is None:
            continue
        try:
            ms = float(value.group(1))
        except ValueError:
            continue
        if not math.isfinite(ms) or ms < 0:
            continue
        kind = classify(line)
        if category is not None and kind != category:
            continue
        name = MEASURE_NAME.search(line)
        origin = name.group(1) if name else line[:65].strip()
        entries.append({
            "line": number, "category": kind, "operation": origin,
            "elapsedMs": ms, "sourceText": line[:350],
        })
    return entries


def summarize(entries: list[dict], threshold: float = 20.0) -> dict:
    by_group: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for item in entries:
        by_group[(item["category"], item["operation"])].append(item)
    groups = []
    for (category, operation), values in by_group.items():
        timings = sorted(item["elapsedMs"] for item in values)
        groups.append({
            "category": category, "operation": operation, "count": len(values),
            "totalMs": round(sum(timings), 3),
            "meanMs": round(statistics.mean(timings), 3),
            "p50Ms": quantile(timings, 0.5),
            "p95Ms": quantile(timings, 0.95),
            "p99Ms": quantile(timings, 0.99),
            "maxMs": max(timings),
            "slowCalls": sum(ms >= threshold for ms in timings),
        })
    groups.sort(key=lambda item: (-item["totalMs"], -item["p95Ms"],
                                  item["category"], item["operation"]))
    spikes = sorted((item for item in entries if item["elapsedMs"] >= threshold),
                    key=lambda item: (-item["elapsedMs"], item["line"]))
    return {
        "schema": "spritesuite.shcde.runtime-timings.v1",
        "totalTimingRecords": len(entries),
        "distinctOperations": len(groups),
        "operations": groups,
        "topSpikes": spikes[:50],
        "thresholdMs": threshold,
        "readOnly": True,
        "missingMeasurementsAreNotInferred": True,
        "nativeFunctionHookWasInstalled": False,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--log", type=Path, required=True)
    p.add_argument("--category", choices=tuple(CATEGORIES) + ("other",))
    p.add_argument("--slow-ms", type=float, default=20.0)
    p.add_argument("--report", type=Path)
    p.add_argument("--csv", type=Path)
    args = p.parse_args(argv)
    try:
        if args.slow_ms < 0 or not math.isfinite(args.slow_ms):
            raise ValueError("Timing threshold must be a nonnegative finite number")
        readings = parse_measurements(args.log.read_text(encoding="utf-8", errors="replace"),
                                      category=args.category)
        result = summarize(readings, threshold=args.slow_ms)
        result["source"] = str(args.log)
        if args.report:
            with args.report.open("x", encoding="utf-8") as target:
                json.dump(result, target, indent=2, ensure_ascii=False)
        if args.csv:
            with args.csv.open("x", encoding="utf-8", newline="") as target:
                writer = csv.DictWriter(target,
                    fieldnames=["category", "operation", "count", "totalMs",
                                "meanMs", "p50Ms", "p95Ms", "p99Ms", "maxMs", "slowCalls"])
                writer.writeheader()
                writer.writerows(result["operations"])
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError) as error:
        print("SHCDE runtime timings: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

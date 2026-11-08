"""Offline SDK, route, save-data and native hook-contract diagnostics."""
from __future__ import annotations

from hashlib import sha256
import heapq
import json
from pathlib import Path
from typing import Any

from .catalog import (
    API_RELEASE, CAPABILITY_BY_KEY, MIN_SCRIPT_EXTENDER, NATIVE_BASELINE_SHA256,
    minimum_api, version_evidence, version_tuple,
)
from .report import (
    Report, analyze_items, boolean, exact_object, integer,
    one_of, text, vector,
)
from .safety import StudioError, json_bytes, relative_path, require_id, require_sha


def sdk(section: dict, target: dict) -> Report:
    report = Report("sdk")
    names = section["requires"]
    version = version_tuple(target["api_shared"])
    rows = []
    if target["api_shared"] != API_RELEASE:
        report.add(
            "REVIEW", "API_RELEASE_DIFFERS",
            f"The declared APIShared version differs from the catalog source {API_RELEASE}.",
        )
    if version_tuple(target["script_extender"]) < version_tuple(MIN_SCRIPT_EXTENDER):
        report.add(
            "REVIEW", "SCRIPT_EXTENDER_VERSION_DIFFERS",
            f"The catalog was reviewed with Script Extender {MIN_SCRIPT_EXTENDER} or newer.",
        )
    for key in names:
        cap = CAPABILITY_BY_KEY[key]  # validated by project.model
        if version < version_tuple(cap.min_api):
            report.add(
                "REVIEW", "API_VERSION_TOO_OLD",
                f"{cap.key} needs APIShared >= {cap.min_api}",
            )
        rows.append({
            "key": key, "minimum_api_shared": cap.min_api,
            "threading": cap.threading, "mode": cap.mode,
        })
    report.facts = {
        "requested_capabilities": rows, "needed_api_shared": minimum_api(names),
        "declared_api_shared": target["api_shared"],
        "references": version_evidence(),
    }
    if names:
        report.add(
            "REVIEW", "SDK_RELEASE_NOT_ATTESTED",
            "A declared API release is not a proof of the locally installed DLL. "
            "Before publishing a plugin verify exact APIShared, Script Extender "
            "and game assembly hashes; reference these dependencies with "
            "Private=false and never redistribute their DLLs.",
        )
    return report


def _route(
    width: int, height: int,
    blocked: set[tuple[int, int]],
    penalties: dict[tuple[int, int], int],
    start: tuple[int, int], finish: tuple[int, int],
) -> dict[str, Any]:
    if start in blocked or finish in blocked:
        return {"state": "BLOCKED_ENDPOINT", "path": [], "cost": None, "visited": 0}
    search = [(0, 0, start[1], start[0])]
    dist = {start: 0}
    previous: dict[tuple[int, int], tuple[int, int]] = {}
    visits = 0
    while search:
        _, score, y, x = heapq.heappop(search)
        node = (x, y)
        if score != dist.get(node):
            continue
        visits += 1
        if node == finish:
            steps = [node]
            while node != start:
                node = previous[node]
                steps.append(node)
            steps.reverse()
            return {
                "state": "FOUND", "path": [[a, b] for a, b in steps],
                "cost": score, "visited": visits,
            }
        for dx, dy in ((-1, 0), (0, -1), (0, 1), (1, 0)):
            nx, ny = x + dx, y + dy
            next_ = (nx, ny)
            if (
                nx < 0 or ny < 0 or nx >= width or ny >= height
                or next_ in blocked
            ):
                continue
            new = score + 1 + penalties.get(next_, 0)
            if new < dist.get(next_, 1_000_000_000):
                dist[next_] = new
                previous[next_] = (x, y)
                heuristic = abs(nx - finish[0]) + abs(ny - finish[1])
                heapq.heappush(search, (new + heuristic, new, ny, nx))
    return {"state": "UNREACHABLE", "path": [], "cost": None, "visited": visits}


def units(section: dict) -> Report:
    report = Report("units")
    grid = section["grid"]
    width, height = grid["width"], grid["height"]
    blocked = set()
    for index, item in enumerate(grid["blocked"]):
        try:
            loc = vector(item, f"units.grid.blocked[{index}]", width, height)
            if loc in blocked:
                raise StudioError("duplicate blocked tile")
            blocked.add(loc)
        except StudioError as exc:
            report.add("BLOCK", "BLOCKED_TILE_INVALID", str(exc))
    penalties = {}
    for index, item in enumerate(grid["penalties"]):
        label = f"units.grid.penalties[{index}]"
        try:
            item = exact_object(item, {"x", "y", "cost"}, label)
            x = integer(item["x"], label + ".x", 0, width - 1)
            y = integer(item["y"], label + ".y", 0, height - 1)
            cost = integer(item["cost"], label + ".cost", 1, 255)
            if (x, y) in penalties or (x, y) in blocked:
                raise StudioError(label + " is repeated or collides with blocked tile")
            penalties[(x, y)] = cost
        except StudioError as exc:
            report.add("BLOCK", "ROUTE_PENALTY_INVALID", str(exc))
    results = []
    def check(raw: dict, index: int) -> None:
        label = f"units.routes[{index}]"
        exact_object(raw, {"id", "player", "start", "goal"}, label)
        player = integer(raw["player"], label + ".player", 1, 8)
        start = vector(raw["start"], label + ".start", width, height)
        goal = vector(raw["goal"], label + ".goal", width, height)
        outcome = _route(width, height, blocked, penalties, start, goal)
        if outcome["state"] == "UNREACHABLE":
            report.add("REVIEW", "OFFLINE_ROUTE_UNREACHABLE",
                       "Route cannot cross the declared synthetic grid", raw["id"])
        elif outcome["state"] == "BLOCKED_ENDPOINT":
            report.add("BLOCK", "OFFLINE_ROUTE_ENDPOINT_BLOCKED",
                       "Route start or destination is blocked", raw["id"])
        outcome.update({"id": raw["id"], "player": player})
        results.append(outcome)
    if not report.findings:
        analyze_items(report, section["routes"], "routes", check)
    report.facts = {
        "grid": {"width": width, "height": height},
        "blocked_count": len(blocked), "penalized_count": len(penalties),
        "routes": results,
        "route_semantics": "synthetic_4_neighbor_a_star_not_vanilla",
    }
    if section["routes"]:
        report.add(
            "REVIEW", "ROUTE_PROVIDER_NOT_ACTIVE",
            "RouteSearchEvents and RouteTileRules are not general Vanilla "
            "pathfinding overrides. This A* preview is not a native engine "
            "route, obstacle rule, or multiplayer movement authorization.",
        )
    return report


def saves(section: dict) -> Report:
    report = Report("saves")
    records = {}
    def check(raw: dict, index: int) -> None:
        label = f"saves.records[{index}]"
        exact_object(raw, {
            "id", "version", "minimum_reader", "known_entries",
            "values", "simulation_relevant",
        }, label)
        version = integer(raw["version"], label + ".version", 1, 65535)
        minimum = integer(
            raw["minimum_reader"], label + ".minimum_reader", 1, version
        )
        boolean(raw["simulation_relevant"], label + ".simulation_relevant")
        names = raw["known_entries"]
        if not isinstance(names, list) or len(names) > 512:
            raise StudioError(label + ".known_entries exceeds allowed size")
        seen = set()
        for key in names:
            name = require_id(key, label + ".known_entries")
            if name in seen:
                raise StudioError(label + " repeated known entry")
            seen.add(name)
        values = raw["values"]
        if type(values) is not dict or len(values) > 512:
            raise StudioError(label + ".values must be a JSON key/value map")
        for key in values:
            require_id(key, label + ".values")
            if key not in seen:
                report.add(
                    "REVIEW", "UNKNOWN_SAVE_ENTRY_PRESERVED",
                    "Unknown entries are included in the digest; never drop them "
                    "on downgrade or migration", str(key),
                )
        document = {"version": version, "values": values}
        payload = json_bytes(document)
        if len(payload) > 1024 * 1024:
            raise StudioError(label + " record exceeds 1 MiB")
        records[raw["id"]] = {
            "sha256": sha256(payload).hexdigest(),
            "bytes": len(payload), "version": version,
            "minimum_reader": minimum,
            "simulation_relevant": raw["simulation_relevant"],
        }
    analyze_items(report, section["records"], "records", check)
    peers = []
    seen_peers = set()
    for index, raw in enumerate(section["peers"]):
        label = f"saves.peers[{index}]"
        try:
            exact_object(raw, {"player", "record_id", "sha256"}, label)
            player = integer(raw["player"], label + ".player", 1, 8)
            record_id = require_id(raw["record_id"], label + ".record_id")
            digest = require_sha(raw["sha256"], label + ".sha256")
            identity = (player, record_id)
            if identity in seen_peers:
                raise StudioError(label + " duplicate player/record identity")
            seen_peers.add(identity)
            record = records.get(record_id)
            if record is None:
                raise StudioError(label + " references an absent record")
            if record["simulation_relevant"] and digest != record["sha256"]:
                report.add(
                    "BLOCK", "MULTIPLAYER_STATE_MISMATCH",
                    "Simulation-relevant record digest differs between peers",
                    f"{player}:{record_id}",
                )
            peers.append({"player": player, "record_id": record_id,
                          "matches": digest == record["sha256"]})
        except StudioError as exc:
            report.add("BLOCK", "SAVE_PEER_INVALID", str(exc), label)
    report.facts = {
        "record_fingerprints": records, "peers": peers,
        "game_save_files_written": False,
    }
    if records:
        report.add(
            "REVIEW", "SAVE_RUNTIME_UNVERIFIED",
            "Offline record checks do not register VersionedSaveData or "
            "test its real save/load/migration callbacks. Keep too-new records "
            "and unknown entries intact; test host/client reload separately.",
        )
    return report


def native(section: dict, target: dict) -> Report:
    report = Report("native")
    sites = []
    for index, raw in enumerate(section["sites"]):
        label = f"native.sites[{index}]"
        try:
            exact_object(
                raw, {"id", "rva", "span", "owner", "confidence", "image_sha256"},
                label,
            )
            ident = require_id(raw["id"], label + ".id")
            rva = integer(raw["rva"], label + ".rva", 0, 2**32 - 257)
            span = integer(raw["span"], label + ".span", 1, 256)
            owner = require_id(raw["owner"], label + ".owner")
            confidence = one_of(
                raw["confidence"],
                {"confirmed", "probable", "incomplete"},
                label + ".confidence",
            )
            image_sha = require_sha(raw["image_sha256"], label + ".image_sha256")
            if image_sha != target["native_sha256"]:
                raise StudioError(label + " native image differs from target pin")
            if image_sha != NATIVE_BASELINE_SHA256:
                report.add(
                    "REVIEW", "NATIVE_BASELINE_NOT_RESEARCHED",
                    "This native DLL hash has no reviewed SpriteSuite native contract",
                    label,
                )
            if any(site["id"] == ident for site in sites):
                raise StudioError(label + " duplicate site id")
            sites.append({
                "id": ident, "rva": rva, "end_rva": rva + span,
                "owner": owner, "confidence": confidence,
            })
            if confidence != "confirmed":
                report.add(
                    "REVIEW", "NATIVE_SITE_UNCERTAIN",
                    "Uncertain baseline semantics cannot justify a native hook",
                    ident,
                )
        except StudioError as exc:
            report.add("BLOCK", "NATIVE_SITE_INVALID", str(exc), label)
    for i, first in enumerate(sites):
        for second in sites[i + 1:]:
            if first["rva"] < second["end_rva"] and second["rva"] < first["end_rva"]:
                report.add(
                    "BLOCK", "NATIVE_HOOK_OVERLAP",
                    "Two proposed native sites overlap, regardless of ownership",
                    f"{first['id']}:{second['id']}",
                )
    report.facts = {
        "baseline_sha256": target["native_sha256"],
        "sites": sorted(sites, key=lambda row: row["rva"]),
        "hook_installation": "disabled",
        "game_binary_verified": False,
    }
    if sites:
        report.add(
            "REVIEW", "NATIVE_SOURCE_ONLY",
            "A SHA pin in project JSON does not verify the installed DLL, "
            "actual machine bytes, backend ownership, live trampoline ABI, "
            "or coexistence with other mods; no hook will be installed.",
        )
    return report

"""Mission, AIV-layout, Noesis and gameplay-balance design analyzers."""
from __future__ import annotations

from pathlib import Path
import re
import xml.etree.ElementTree as ET
from typing import Any

from .report import (
    Report, analyze_items, boolean, cost_map, exact_object, integer,
    one_of, text, vector,
)
from .safety import StudioError, nfc, relative_path, read_text, require_id

TRIGGER_EVENTS = {
    "mission_start", "tick_at", "resources_at_least",
    "unit_settled", "building_built", "player_defeated",
}
ACTION_KINDS = {"message", "objective", "resource_delta", "spawn", "cue"}
WALL_PREFIX = "Assets/GUI/Images/sede-wall-"

def _event_when(event: str, when: Any, label: str) -> None:
    requirements = {
        "mission_start": set(),
        "tick_at": {"tick"},
        "resources_at_least": {"player", "good", "amount"},
        "unit_settled": {"player", "unit"},
        "building_built": {"player", "building"},
        "player_defeated": {"player"},
    }
    value = exact_object(when, requirements[event], label)
    if "player" in value:
        integer(value["player"], label + ".player", 1, 8)
    if "tick" in value:
        integer(value["tick"], label + ".tick", 0, 2_147_483_647)
    if "good" in value:
        require_id(value["good"], label + ".good")
    if "amount" in value:
        integer(value["amount"], label + ".amount", 0, 10_000_000)
    for key in ("unit", "building"):
        if key in value:
            require_id(value[key], label + "." + key)


def _action(value: Any, label: str, cue_ids: set[str]) -> None:
    if type(value) is not dict:
        raise StudioError(f"{label} is not an action object")
    kind = one_of(value.get("kind"), ACTION_KINDS, label + ".kind")
    required = {
        "message": {"kind", "text"},
        "objective": {"kind", "text", "state"},
        "resource_delta": {"kind", "player", "good", "delta"},
        "spawn": {"kind", "player", "unit", "count", "x", "y"},
        "cue": {"kind", "cue_id"},
    }
    exact_object(value, required[kind], label)
    if kind in {"message", "objective"}:
        text(value["text"], label + ".text", 400)
    if kind == "objective":
        one_of(value["state"], {"show", "complete", "fail"}, label + ".state")
    if kind in {"resource_delta", "spawn"}:
        integer(value["player"], label + ".player", 1, 8)
    if kind == "resource_delta":
        require_id(value["good"], label + ".good")
        integer(value["delta"], label + ".delta", -1_000_000, 1_000_000)
    if kind == "spawn":
        require_id(value["unit"], label + ".unit")
        integer(value["count"], label + ".count", 1, 1000)
        integer(value["x"], label + ".x", 0, 1024)
        integer(value["y"], label + ".y", 0, 1024)
    if kind == "cue":
        require_id(value["cue_id"], label + ".cue_id")
        if value["cue_id"] not in cue_ids:
            raise StudioError(f"{label} references absent audio cue {value['cue_id']}")


def mission(section: dict, cue_ids: set[str]) -> Report:
    report = Report("mission")
    triggers = section["triggers"]
    def check(raw: dict, index: int) -> None:
        label = f"mission.triggers[{index}]"
        exact_object(raw, {"id", "event", "when", "actions", "once"}, label)
        event = one_of(raw["event"], TRIGGER_EVENTS, label + ".event")
        _event_when(event, raw["when"], label + ".when")
        boolean(raw["once"], label + ".once")
        actions = raw["actions"]
        if not isinstance(actions, list) or not 1 <= len(actions) <= 16:
            raise StudioError(label + ".actions must contain 1..16 actions")
        for i, action in enumerate(actions):
            _action(action, f"{label}.actions[{i}]", cue_ids)
    analyze_items(report, triggers, "triggers", check)
    report.facts["triggers"] = len(triggers)
    report.facts["supported_events"] = sorted(TRIGGER_EVENTS)
    report.facts["publication"] = "declarative_rule_plan_only"
    if triggers:
        report.add(
            "REVIEW", "MISSION_RUNTIME_NOT_CONNECTED",
            "This is a deterministic offline trigger plan; the Script Extender event "
            "registration, game actions, save-state and multiplayer transport "
            "require a separately verified runtime adapter.",
        )
    return report


def match_event(rule: dict, event: dict) -> bool:
    name = rule["event"]
    when = rule["when"]
    if name == "tick_at":
        return (
            event.get("event") == "simulation_tick"
            and event.get("tick", -1) == when["tick"]
        )
    if name == "resources_at_least":
        return (
            event.get("event") == "resource_snapshot"
            and event.get("player") == when["player"]
            and event.get("good") == when["good"]
            and event.get("amount", -1) >= when["amount"]
        )
    if event.get("event") != name:
        return False
    return all(event.get(key) == value for key, value in when.items())


def simulate_mission(section: dict, input_events: list[dict]) -> dict:
    if not isinstance(input_events, list) or len(input_events) > 2000:
        raise StudioError("mission simulation requires 0..2000 events")
    if mission(section, set(
        a["cue_id"] for t in section["triggers"]
        for a in t.get("actions", []) if isinstance(a, dict) and a.get("kind") == "cue"
    )).status == "BLOCKED":
        raise StudioError("mission plan is invalid")
    previous = -1
    fired: set[str] = set()
    traces = []
    for i, row in enumerate(input_events):
        if type(row) is not dict:
            raise StudioError("simulation event must be an object")
        tick = integer(row.get("tick"), f"events[{i}].tick", 0, 2_147_483_647)
        if tick < previous:
            raise StudioError("simulation events are not ordered by native map tick")
        previous = tick
        for trigger in section["triggers"]:
            if trigger["once"] and trigger["id"] in fired:
                continue
            if match_event(trigger, row):
                fired.add(trigger["id"])
                traces.append({
                    "tick": tick,
                    "trigger_id": trigger["id"],
                    "actions": trigger["actions"],
                })
    return {
        "status": "offline_simulation_only",
        "events": len(input_events),
        "fired": len(traces),
        "trace": traces,
        "warning": "No in-game effects, save persistence or multiplayer authority proved",
    }


def castle(section: dict) -> Report:
    report = Report("castle")
    size = section["grid_size"]
    occupied: dict[tuple[int, int], str] = {}
    layout = []
    def check(raw: dict, index: int) -> None:
        label = f"castle.buildings[{index}]"
        exact_object(
            raw, {"id", "kind", "x", "y", "width", "height", "rotation", "step"},
            label,
        )
        name = require_id(raw["kind"], label + ".kind")
        x = integer(raw["x"], label + ".x", 0, size - 1)
        y = integer(raw["y"], label + ".y", 0, size - 1)
        w = integer(raw["width"], label + ".width", 1, size)
        h = integer(raw["height"], label + ".height", 1, size)
        rotation = integer(raw["rotation"], label + ".rotation", 0, 270)
        if rotation not in {0, 90, 180, 270}:
            raise StudioError(label + ".rotation must be 0, 90, 180 or 270")
        step = integer(raw["step"], label + ".step", 0, 10_000)
        if rotation in {90, 270}:
            w, h = h, w
        if x + w > size or y + h > size:
            raise StudioError(label + " extends beyond the declared AIV grid")
        for xx in range(x, x + w):
            for yy in range(y, y + h):
                prior = occupied.get((xx, yy))
                if prior:
                    report.add("BLOCK", "CASTLE_OVERLAP",
                               f"{raw['id']} overlaps {prior} at ({xx}, {yy})", label)
                occupied[(xx, yy)] = raw["id"]
        layout.append({
            "id": raw["id"], "kind": name, "x": x, "y": y,
            "width": w, "height": h, "step": step,
            "rotation": rotation,
        })
    analyze_items(report, section["buildings"], "buildings", check)
    report.facts = {
        "grid_size": size,
        "elements": sorted(layout, key=lambda row: (row["step"], row["id"])),
        "occupied_tiles": len(occupied),
        "evaluation": "rectangular_sketch_not_native_aivplacement",
    }
    if layout:
        report.add(
            "REVIEW", "NATIVE_AIV_FIT_NOT_VERIFIED",
            "The footprint preview is not Serp AIVPlacement: terrain, keep "
            "anchors, mapper-specific footprints and placement order must be "
            "validated against the exact DE map and aivjson.",
        )
    return report


def _analyze_xaml(text_value: str, label: str) -> tuple[set[str], list[str]]:
    if "<!DOCTYPE" in text_value.upper() or "<!ENTITY" in text_value.upper():
        raise StudioError(label + " contains unsupported XML entity declarations")
    warnings: list[str] = []
    try:
        root = ET.fromstring(text_value)
    except ET.ParseError as exc:
        # SHCDE XamlPatcher supports an intentionally unbound x: prefix
        # on the outer <Patch> element and resolves it when applying patches.
        # Add its standard namespace for OFFLINE structure parsing only.
        # Do not change the original source or treat this as game validation.
        if (
            "unbound prefix" not in str(exc)
            or text_value.count("<Patch>") != 1
            or "xmlns:x=" in text_value
            or "x:Key=" not in text_value
        ):
            raise StudioError(f"{label} is not well-formed XAML/XML: {exc}") from exc
        normalized = text_value.replace(
            "<Patch>",
            '<Patch xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml" '
            'xmlns:local="urn:SpriteSuite:OfflineNoesisPropertyOwner">',
            1,
        )
        try:
            root = ET.fromstring(normalized)
        except ET.ParseError as nested:
            raise StudioError(f"{label} patch is not parseable: {nested}") from nested
        warnings.append("Patch-only x: namespace synthesized for offline parsing")
    images: set[str] = set()
    keys: set[str] = set()
    for element in root.iter():
        for key, value in element.attrib.items():
            if key.rsplit("}", 1)[-1] == "Key":
                if value.casefold() in keys:
                    warnings.append("duplicate XAML resource key: " + value)
                keys.add(value.casefold())
            if key.rsplit("}", 1)[-1] != "UriSource":
                continue
            # The actual Noesis owner is an Assets/GUI/XAMLResources/*.xaml.
            # Only the exact relative GUI image path can count as provenance.
            if value.startswith("../Images/") and value.endswith(".png"):
                subpath = value[len("../Images/"):]
                if "/" in subpath or "\\" in subpath or subpath in {"", ".", ".."}:
                    raise StudioError(label + " has unsafe GUI image UriSource")
                images.add("Assets/GUI/Images/" + subpath)
            elif value.endswith(".png") and "sede-wall-" in value:
                warnings.append("unresolved wall image UriSource: " + value)
    return images, warnings


def hud(section: dict, workspace: Path) -> Report:
    report = Report("hud")
    listed: set[str] = set()
    for index, path in enumerate(section["xaml_files"]):
        try:
            path = relative_path(path, f"hud.xaml_files[{index}]")
            if not path.endswith(".xaml"):
                raise StudioError("Noesis input must end in .xaml")
            if path in listed:
                raise StudioError("duplicate XAML source")
            listed.add(path)
            images, notes = _analyze_xaml(
                read_text(workspace, path, 2 * 1024 * 1024), path
            )
            for note in notes:
                report.add("REVIEW", "XAML_RESOURCE_WARNING", note, path)
            report.facts.setdefault("files", {})[path] = {
                "owned_image_uris": sorted(images),
                "count": len(images),
            }
        except (StudioError, OSError) as exc:
            report.add("BLOCK", "XAML_SOURCE_INVALID", str(exc), str(path))
    expected: set[str] = set()
    for index, uri in enumerate(section["expected_images"]):
        try:
            uri = relative_path(uri, f"hud.expected_images[{index}]")
            if not uri.startswith("Assets/GUI/") or not uri.endswith(".png"):
                raise StudioError("expected image must be an Assets/GUI/*.png URI")
            if uri in expected:
                raise StudioError("duplicate expected Noesis URI")
            expected.add(uri)
        except StudioError as exc:
            report.add("BLOCK", "HUD_EXPECTED_INVALID", str(exc))
    found = {
        uri for item in report.facts.get("files", {}).values()
        for uri in item["owned_image_uris"]
    }
    missing = sorted(expected - found)
    report.facts["expected_count"] = len(expected)
    report.facts["referenced_count"] = len(found)
    report.facts["unreferenced_expected"] = missing
    for uri in missing:
        report.add(
            "REVIEW", "NOESIS_URI_NOT_REFERENCED",
            "No explicit BitmapImage.UriSource in supplied XAML; "
            "do not infer a runtime request or remove this source",
            uri,
        )
    if found:
        report.add(
            "REVIEW", "XAML_RUNTIME_UNVERIFIED",
            "XML parsing and UriSource references do not prove the game loaded "
            "the XAML, raised a Noesis request or rendered the image.",
        )
    return report


def balance(section: dict) -> Report:
    report = Report("balance")
    computed = []
    def check(raw: dict, index: int) -> None:
        label = f"balance.cost_rules[{index}]"
        exact_object(
            raw, {"id", "category", "subject", "base", "numerator", "denominator"},
            label,
        )
        category = one_of(
            raw["category"], {"building", "unit", "market"}, label + ".category"
        )
        subject = require_id(raw["subject"], label + ".subject")
        base = cost_map(raw["base"], label + ".base")
        numerator = integer(raw["numerator"], label + ".numerator", 0, 1000)
        denominator = integer(raw["denominator"], label + ".denominator", 1, 1000)
        projected = {
            good: (amount * numerator * 2 + denominator) // (2 * denominator)
            for good, amount in base.items()
        }
        if any(value > 10_000_000 for value in projected.values()):
            raise StudioError(label + " projected cost exceeds the safe preview bound")
        computed.append({
            "id": raw["id"], "category": category, "subject": subject,
            "projected_costs": projected, "original_costs": base,
            "multiplier": [numerator, denominator],
        })
    analyze_items(report, section["cost_rules"], "cost_rules", check)
    report.facts["cost_previews"] = computed
    if computed:
        report.add(
            "REVIEW", "BALANCE_PREVIEW_NOT_PATCHED",
            "These integer calculations do not patch recruitment, market query, "
            "building costs, AI affordability, or multiplayer resource accounting. "
            "APIShared subscriptions need a separately validated runtime consumer.",
        )
    return report

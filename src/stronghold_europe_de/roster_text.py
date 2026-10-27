from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import unicodedata
from typing import Any
import xml.etree.ElementTree as ET

class RosterTextError(RuntimeError):
    """Raised when the roster recipe cannot bind to the installed game files."""


@dataclass(frozen=True)
class RosterTextEntry:
    kind: str
    logical_id: str
    section: str
    raw_index: int
    internal_key: str
    de: str
    en: str


@dataclass(frozen=True)
class RosterHudBinding:
    logical_id: str
    control: str
    internal_key: str


@dataclass(frozen=True)
class RosterTextSpec:
    source_path: Path
    source_sha256: str
    target_text_path: Path
    target_text_sha256: str
    target_text_size: int
    target_locale: str
    target_originals_sha256: str
    hud_xaml_path: Path
    hud_xaml_sha256: str
    hud_xaml_size: int
    hud_buildings_xaml_path: Path
    hud_buildings_xaml_sha256: str
    hud_buildings_xaml_size: int
    entries_sha256: str
    unit_names_sha256: str
    entries: tuple[RosterTextEntry, ...]
    hud_bindings: tuple[RosterHudBinding, ...]


_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_ID_RE = re.compile(r"[a-z][a-z0-9_]*\Z")
_CONTROL_RE = re.compile(r"Button[A-Za-z0-9]+\Z")

_SPEC_KEYS = frozenset(
    {
        "schema_version",
        "plugin_id",
        "source_build_id",
        "target_build_id",
        "target_text",
        "hud_xaml",
        "hud_buildings_xaml",
        "templates",
        "units",
        "buildings",
    }
)
_FILE_PIN_KEYS = frozenset({"relative_path", "size", "sha256"})
_TARGET_TEXT_KEYS = _FILE_PIN_KEYS | {"locale"}
_TEMPLATE_KEYS = frozenset({"rally_de", "rally_en", "select_de", "select_en"})
_UNIT_KEYS = frozenset(
    {
        "id",
        "chimp_raw",
        "bubble_raw",
        "rally_raw",
        "select_raw",
        "hud_control",
        "de",
        "en",
    }
)
_BUILDING_KEYS = frozenset(
    {
        "id",
        "title_raw",
        "description_raw",
        "hud_control",
        "de",
        "en",
        "description_de",
        "description_en",
    }
)

_PLUGIN_ID = "strongholdeuropede.runtime.private"
_SOURCE_BUILD_ID = "local-sh1de-unity-2021.3.27f1-2025-01-20"
_TARGET_BUILD_ID = "local-shcde-2.80-unity-2021.3.45f2"
_TARGET_TEXT_RELATIVE = "Assets/Text/crusader.txt"
_HUD_XAML_RELATIVE = (
    "BepInEx/plugins/000shcdese/Override/Assets/GUI/XAMLResources/HUD_Main.xaml"
)
_HUD_BUILDINGS_XAML_RELATIVE = (
    "BepInEx/plugins/000shcdese/Override/Assets/GUI/XAMLResources/"
    "HUD_Buildings.xaml"
)
_XAML_PRESENTATION_NS = "http://schemas.microsoft.com/winfx/2006/xaml/presentation"
_XAML_LANGUAGE_NS = "http://schemas.microsoft.com/winfx/2006/xaml"
_XAML_BEHAVIORS_NS = "http://schemas.microsoft.com/xaml/behaviors"

_EXPECTED_TEMPLATES = {
    "rally_de": "Sammelpunkt setzen: {name}",
    "rally_en": "Set rally point: {name}",
    "select_de": "Alle auswählen/abwählen: {name}",
    "select_en": "Select/deselect all: {name}",
}

_EXPECTED_UNITS = (
    ("arabian_bowman", 70, 315, 0, 7, "ButtonBuildMEArabBow"),
    ("slave", 71, 316, 1, 8, "ButtonBuildMEArabSlave"),
    ("slinger", 72, 317, 2, 9, "ButtonBuildMEArabSlinger"),
    ("assassin", 73, 318, 3, 10, "ButtonBuildMEArabAssassin"),
    ("horse_archer", 74, 319, 4, 11, "ButtonBuildMEArabHorseArcher"),
    ("arabian_swordsman", 75, 320, 5, 12, "ButtonBuildMEArabSwordsman"),
    ("fire_thrower", 76, 321, 6, 13, "ButtonBuildMEArabGrenadier"),
    ("camel_lancer", 78, 349, 178, 186, "ButtonBuildMECamelLancer"),
    ("healer", 79, 350, 179, 187, "ButtonBuildMEHealer"),
    ("eunuch", 80, 351, 180, 188, "ButtonBuildMEEunuch"),
    ("ambusher", 81, 352, 181, 189, "ButtonBuildMEAmbusher"),
    ("skirmisher", 82, 353, 182, 190, "ButtonBuildMESkirmisher"),
    ("heavy_camel", 83, 354, 183, 191, "ButtonBuildMEHeavyCamel"),
    ("sapper", 84, 355, 184, 192, "ButtonBuildMESapper"),
    ("demolisher", 85, 356, 185, 193, "ButtonBuildMEDemolisher"),
)
_EXPECTED_BUILDINGS = (
    (
        "mercenary_post",
        10,
        57,
        "ButtonBuildWoodenBarracks",
        "Söldnerlager",
        "Mercenary Camp",
        "Rekrutiert europäische Söldner gegen Gold.",
        "Recruits European mercenaries for gold.",
    ),
    (
        "bedouin_stockade",
        348,
        58,
        "ButtonBuildWoodenBedouinStockade",
        "Heerlager",
        "War Camp",
        "Rekrutiert spezialisierte europäische Truppen gegen Gold.",
        "Recruits specialized European troops for gold.",
    ),
)

_EXPECTED_HUD_BUILDING_ROUTES = (
    ("AssemblyM1", "Show_MercPostArabBow", "MAPPER_PLACE_ASSEMBLY_POINTM1"),
    ("AssemblyM2", "Show_MercPostArabSlave", "MAPPER_PLACE_ASSEMBLY_POINTM3"),
    ("AssemblyM3", "Show_MercPostArabSlinger", "MAPPER_PLACE_ASSEMBLY_POINTM5"),
    ("AssemblyM4", "Show_MercPostArabAssassin", "MAPPER_PLACE_ASSEMBLY_POINTM4"),
    ("AssemblyM5", "Show_MercPostArabHorseArcher", "MAPPER_PLACE_ASSEMBLY_POINTM2"),
    ("AssemblyM6", "Show_MercPostArabSwordsman", "MAPPER_PLACE_ASSEMBLY_POINTM7"),
    ("AssemblyM7", "Show_MercPostArabGrenadier", "MAPPER_PLACE_ASSEMBLY_POINTM6"),
    ("AssemblyBS1", "Show_BedouinCamelLancer", "MAPPER_PLACE_ASSEMBLY_POINTBS1"),
    ("AssemblyBS2", "Show_BedouinHealer", "MAPPER_PLACE_ASSEMBLY_POINTBS2"),
    ("AssemblyBS3", "Show_BedouinEunuch", "MAPPER_PLACE_ASSEMBLY_POINTBS3"),
    ("AssemblyBS4", "Show_BedouinAmbusher", "MAPPER_PLACE_ASSEMBLY_POINTBS4"),
    ("AssemblyBS5", "Show_BedouinSkirmisher", "MAPPER_PLACE_ASSEMBLY_POINTBS5"),
    ("AssemblyBS6", "Show_BedouinHeavyCamel", "MAPPER_PLACE_ASSEMBLY_POINTBS6"),
    ("AssemblyBS7", "Show_BedouinSapper", "MAPPER_PLACE_ASSEMBLY_POINTBS7"),
    ("AssemblyBS8", "Show_BedouinDemolisher", "MAPPER_PLACE_ASSEMBLY_POINTBS8"),
)

# Translate.LoadTextFileNew counts sections in file order, ignoring the numeric
# marker text. These are the four relevant positions in the target's
# SectionNames array, including the copyright section.
_TARGET_SECTION_NAMES = {
    9: "TEXT_BUBBLE_HELP_TEXT",
    89: "TEXT_CHIMP_NAMES",
    229: "TEXT_NEW_CTEXT",
    236: "TEXT_BUILDING_DESCRIPTIONS",
}


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RosterTextError(f"Duplicate JSON key in roster text spec: {key}")
        result[key] = value
    return result


def _exact_keys(value: Mapping[str, Any], expected: frozenset[str], label: str) -> None:
    missing = sorted(expected - set(value))
    extra = sorted(set(value) - expected)
    if missing or extra:
        raise RosterTextError(
            f"Invalid {label} keys: missing={missing}, extra={extra}"
        )


def _strict_positive_int(value: object, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise RosterTextError(f"{label} must be a positive JSON integer")
    return value


def _strict_nonnegative_int(value: object, label: str) -> int:
    if type(value) is not int or value < 0:
        raise RosterTextError(f"{label} must be a nonnegative JSON integer")
    return value


def _text(value: object, label: str, *, pattern: re.Pattern[str] | None = None) -> str:
    if not isinstance(value, str) or not value:
        raise RosterTextError(f"{label} must be a non-empty string")
    if value != value.strip() or any(character in value for character in "\t\r\n\x00"):
        raise RosterTextError(f"{label} is not a canonical single-line string")
    if unicodedata.normalize("NFC", value) != value:
        raise RosterTextError(f"{label} must use Unicode NFC")
    if pattern is not None and pattern.fullmatch(value) is None:
        raise RosterTextError(f"{label} is not canonical: {value!r}")
    return value


def _sha256(value: object, label: str) -> str:
    text = _text(value, label)
    if _SHA256_RE.fullmatch(text) is None:
        raise RosterTextError(f"{label} must be lowercase SHA-256")
    return text


def _read_stable_file(path: Path, *, label: str) -> bytes:
    """Snapshot an installed input; its build-time identity is bound into the runtime."""
    try:
        before = path.stat()
        if not path.is_file() or path.is_symlink():
            raise RosterTextError(f"{label} is not a regular non-link file: {path}")
        payload = path.read_bytes()
        after = path.stat()
    except OSError as exc:
        raise RosterTextError(f"Cannot read {label}: {path}") from exc
    if (
        not payload
        or len(payload) != before.st_size
        or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns)
    ):
        raise RosterTextError(f"{label} size/stability mismatch: {path}")
    return payload


def _parse_target_game_text(payload: bytes) -> tuple[str, dict[str, str]]:
    try:
        text = payload.decode("utf-8-sig", errors="strict")
    except UnicodeError as exc:
        raise RosterTextError("Target crusader.txt is not strict UTF-8") from exc
    lines = text.splitlines()
    if not lines or re.fullmatch(r"[A-Za-z]{4}", lines[0]) is None:
        raise RosterTextError("Target crusader.txt locale is malformed")
    start = next((index for index, line in enumerate(lines) if line.lower() == ">>textstart"), None)
    if start is None:
        raise RosterTextError("Target crusader.txt header is malformed")

    result: dict[str, str] = {}
    section_ordinal = 0
    index = 0
    current_name: str | None = None
    for line in lines[start + 1:]:
        if line == "":
            # This intentionally mirrors Translate.LoadTextFileNew: blank lines
            # do not consume an index in the original game dictionary.
            continue
        # Translate.LoadTextFileNew identifies sections by order, not marker text.
        if line.startswith(">>") and len(line) >= 3:
            section_ordinal += 1
            index = 0
            current_name = _TARGET_SECTION_NAMES.get(section_ordinal)
            continue
        if section_ordinal == 0:
            raise RosterTextError("Target crusader.txt has text before its first section")
        index += 1
        if current_name is not None:
            width = 4 if index >= 1000 else 3
            key = f"{current_name}_{index:0{width}d}"
            if key in result:
                raise RosterTextError(f"Duplicate target text key: {key}")
            result[key] = line.replace("\\n", "\n")
    if section_ordinal < max(_TARGET_SECTION_NAMES):
        raise RosterTextError("Target crusader.txt is truncated before required sections")
    return lines[0].lower(), result


def _entry_digest(entries: tuple[RosterTextEntry, ...]) -> str:
    payload = "".join(
        f"{entry.kind}\t{entry.logical_id}\t{entry.section}\t{entry.raw_index}"
        f"\t{entry.internal_key}\t{entry.de}\t{entry.en}\n"
        for entry in entries
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _originals_digest(
    entries: tuple[RosterTextEntry, ...], target: Mapping[str, str]
) -> str:
    rows: list[str] = []
    for entry in entries:
        if entry.internal_key not in target:
            raise RosterTextError(
                f"Target text is missing roster key: {entry.internal_key}"
            )
        value_digest = hashlib.sha256(target[entry.internal_key].encode("utf-8")).hexdigest()
        rows.append(f"{entry.internal_key}\t{value_digest}\n")
    return hashlib.sha256("".join(rows).encode("ascii")).hexdigest()


def _unit_name_digest(units: list[Mapping[str, Any]]) -> str:
    payload = "".join(
        f"{unit['chimp_raw']}\tTEXT_CHIMP_NAMES_{unit['chimp_raw']:03d}"
        f"\t{unit['de']}\t{unit['en']}\n"
        for unit in units
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _validate_hud_bindings(
    payload: bytes,
    bindings: tuple[RosterHudBinding, ...],
) -> None:
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise RosterTextError("Pinned HUD_Main.xaml is not well-formed XML") from exc
    if (
        root.tag != f"{{{_XAML_PRESENTATION_NS}}}UserControl"
        or root.attrib.get(f"{{{_XAML_LANGUAGE_NS}}}Class")
        != "CrusaderDE.HUD_Main"
    ):
        raise RosterTextError("Pinned HUD_Main.xaml root/class is not exact")

    expected = {binding.control: binding.internal_key for binding in bindings}
    observed: dict[str, list[str | None]] = {control: [] for control in expected}
    for element in root.iter():
        control = element.attrib.get("Name")
        if control in observed:
            observed[control].append(element.attrib.get("Tag"))

    for control, internal_key in expected.items():
        expected_tag = (
            "{Binding Source={x:Static local:Translate.Instance}, "
            f"Path=GameTexts[{internal_key}]}}"
        )
        if observed[control] != [expected_tag]:
            raise RosterTextError(
                "Pinned HUD_Main.xaml roster binding is not exact: "
                f"control={control!r} expected={expected_tag!r} "
                f"actual={observed[control]!r}"
            )


def _validate_hud_building_routes(payload: bytes) -> None:
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise RosterTextError(
            "Pinned HUD_Buildings.xaml is not well-formed XML"
        ) from exc
    if (
        root.tag != f"{{{_XAML_PRESENTATION_NS}}}UserControl"
        or root.attrib.get(f"{{{_XAML_LANGUAGE_NS}}}Class")
        != "CrusaderDE.HUD_Buildings"
    ):
        raise RosterTextError("Pinned HUD_Buildings.xaml root/class is not exact")

    expected = {
        route: (visibility, mapper)
        for route, visibility, mapper in _EXPECTED_HUD_BUILDING_ROUTES
    }
    observed: dict[
        str,
        list[
            tuple[
                str | None,
                str | None,
                str | None,
                tuple[tuple[str | None, str | None], ...],
            ]
        ],
    ] = {route: [] for route in expected}
    action_tag = f"{{{_XAML_BEHAVIORS_NS}}}InvokeCommandAction"
    button_tag = f"{{{_XAML_PRESENTATION_NS}}}Button"
    event_tag = f"{{{_XAML_BEHAVIORS_NS}}}EventTrigger"
    triggers_tag = f"{{{_XAML_BEHAVIORS_NS}}}Interaction.Triggers"
    global_action_counts = {route: 0 for route in expected}
    expected_mappers = {mapper for _, mapper in expected.values()}
    global_mapper_counts = {mapper: 0 for mapper in expected_mappers}
    for element in root.iter():
        command_parameter = element.attrib.get("CommandParameter")
        if command_parameter is None:
            continue
        if command_parameter.startswith(("AssemblyM", "AssemblyBS")):
            if element.tag != action_tag or command_parameter not in expected:
                raise RosterTextError(
                    "Pinned HUD_Buildings.xaml contains an unexpected global "
                    f"roster action: {command_parameter!r}"
                )
            global_action_counts[command_parameter] += 1
        if command_parameter.startswith(
            (
                "MAPPER_PLACE_ASSEMBLY_POINTM",
                "MAPPER_PLACE_ASSEMBLY_POINTBS",
            )
        ):
            if element.tag != button_tag or command_parameter not in expected_mappers:
                raise RosterTextError(
                    "Pinned HUD_Buildings.xaml contains an unexpected global "
                    f"roster mapper: {command_parameter!r}"
                )
            global_mapper_counts[command_parameter] += 1
    if global_action_counts != {route: 2 for route in expected}:
        raise RosterTextError(
            "Pinned HUD_Buildings.xaml global roster action counts are not exact: "
            f"{global_action_counts!r}"
        )
    if global_mapper_counts != {mapper: 1 for mapper in expected_mappers}:
        raise RosterTextError(
            "Pinned HUD_Buildings.xaml global roster mapper counts are not exact: "
            f"{global_mapper_counts!r}"
        )

    for button in root.iter(button_tag):
        parent = {
            child: element
            for element in button.iter()
            for child in element
        }
        actions: list[tuple[str | None, str | None, str]] = []
        for element in button.iter(action_tag):
            route = element.attrib.get("CommandParameter")
            if route is None or not route.startswith(("AssemblyM", "AssemblyBS")):
                continue
            if route not in expected:
                raise RosterTextError(
                    "Pinned HUD_Buildings.xaml contains an unexpected roster route: "
                    f"{route!r}"
                )
            event = parent.get(element)
            trigger_collection = parent.get(event) if event is not None else None
            if (
                event is None
                or event.tag != event_tag
                or trigger_collection is None
                or trigger_collection.tag != triggers_tag
                or parent.get(trigger_collection) is not button
            ):
                raise RosterTextError(
                    "Pinned HUD_Buildings.xaml roster action has an unexpected "
                    f"trigger hierarchy: route={route!r}"
                )
            actions.append(
                (
                    event.attrib.get("EventName"),
                    element.attrib.get("Command"),
                    route,
                )
            )
        if not actions:
            continue
        routes = {route for _, _, route in actions}
        if len(routes) != 1:
            raise RosterTextError(
                "Pinned HUD_Buildings.xaml mixes roster routes in one button: "
                f"{sorted(routes)!r}"
            )
        route = next(iter(routes))
        observed[route].append(
            (
                button.attrib.get("Visibility"),
                button.attrib.get("Command"),
                button.attrib.get("CommandParameter"),
                tuple((event, command) for event, command, _ in actions),
            )
        )

    for route, (visibility_path, mapper) in expected.items():
        expected_binding = (
            "{Binding Path="
            f"{visibility_path}, Converter={{StaticResource booleanToVisibilityConverter}}}}",
            "{Binding ButtonCreateTroopCommand}",
            mapper,
            (
                ("MouseEnter", "{Binding ButtonTroopCreateEnterCommand}"),
                ("MouseLeave", "{Binding ButtonTroopCreateLeaveCommand}"),
            ),
        )
        if observed[route] != [expected_binding]:
            raise RosterTextError(
                "Pinned HUD_Buildings.xaml roster route is not exact: "
                f"route={route!r} expected={expected_binding!r} "
                f"actual={observed[route]!r}"
            )


def load_roster_text_spec(project_root: Path, target_game_root: Path) -> RosterTextSpec:
    source_path = project_root / "config" / "unit-roster-text.json"
    try:
        payload = source_path.read_bytes()
        raw = json.loads(payload.decode("utf-8", errors="strict"), object_pairs_hook=_reject_duplicate_pairs)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RosterTextError(f"Cannot read roster text spec: {source_path}") from exc
    if not isinstance(raw, Mapping):
        raise RosterTextError("Roster text spec must be an object")
    _exact_keys(raw, _SPEC_KEYS, "roster text spec")
    if raw["schema_version"] != 1:
        raise RosterTextError("Unsupported roster text schema")
    if raw["plugin_id"] != _PLUGIN_ID:
        raise RosterTextError("Roster text plugin ID is not pinned")
    for key in ("source_build_id", "target_build_id"):
        _text(raw[key], key, pattern=re.compile(r"[A-Za-z0-9_.-]+\Z"))

    target_pin = raw["target_text"]
    hud_pin = raw["hud_xaml"]
    hud_buildings_pin = raw["hud_buildings_xaml"]
    templates = raw["templates"]
    if (
        not isinstance(target_pin, Mapping)
        or not isinstance(hud_pin, Mapping)
        or not isinstance(hud_buildings_pin, Mapping)
    ):
        raise RosterTextError("Roster target file pins must be objects")
    if not isinstance(templates, Mapping):
        raise RosterTextError("Roster templates must be an object")
    _exact_keys(target_pin, _TARGET_TEXT_KEYS, "target_text")
    _exact_keys(hud_pin, _FILE_PIN_KEYS, "hud_xaml")
    _exact_keys(
        hud_buildings_pin,
        _FILE_PIN_KEYS,
        "hud_buildings_xaml",
    )
    _exact_keys(templates, _TEMPLATE_KEYS, "templates")
    if dict(templates) != _EXPECTED_TEMPLATES:
        raise RosterTextError("Roster tooltip templates are not the pinned bilingual copy")
    if target_pin["relative_path"] != _TARGET_TEXT_RELATIVE:
        raise RosterTextError("Roster target text path is not pinned")
    if hud_pin["relative_path"] != _HUD_XAML_RELATIVE:
        raise RosterTextError("Roster HUD XAML path is not pinned")
    if hud_buildings_pin["relative_path"] != _HUD_BUILDINGS_XAML_RELATIVE:
        raise RosterTextError("Roster HUD Buildings XAML path is not pinned")

    raw_units = raw["units"]
    raw_buildings = raw["buildings"]
    if not isinstance(raw_units, list) or len(raw_units) != len(_EXPECTED_UNITS):
        raise RosterTextError("Roster text spec must contain exactly 15 units")
    if not isinstance(raw_buildings, list) or len(raw_buildings) != 2:
        raise RosterTextError("Roster text spec must contain exactly two buildings")

    units: list[Mapping[str, Any]] = []
    entries: list[RosterTextEntry] = []
    bindings: list[RosterHudBinding] = []
    for position, (item, expected) in enumerate(zip(raw_units, _EXPECTED_UNITS, strict=True)):
        if not isinstance(item, Mapping):
            raise RosterTextError(f"units[{position}] must be an object")
        _exact_keys(item, _UNIT_KEYS, f"units[{position}]")
        unit_id = _text(item["id"], f"units[{position}].id", pattern=_SAFE_ID_RE)
        values = (
            unit_id,
            _strict_nonnegative_int(item["chimp_raw"], f"units[{position}].chimp_raw"),
            _strict_nonnegative_int(item["bubble_raw"], f"units[{position}].bubble_raw"),
            _strict_nonnegative_int(item["rally_raw"], f"units[{position}].rally_raw"),
            _strict_nonnegative_int(item["select_raw"], f"units[{position}].select_raw"),
            _text(item["hud_control"], f"units[{position}].hud_control", pattern=_CONTROL_RE),
        )
        if values != expected:
            raise RosterTextError(f"Pinned unit route/order mismatch at units[{position}]")
        de = _text(item["de"], f"units[{position}].de")
        en = _text(item["en"], f"units[{position}].en")
        unit = dict(item)
        units.append(unit)
        routed = (
            ("unit_name", "TEXT_CHIMP_NAMES", values[1], de, en),
            ("unit_bubble", "TEXT_BUBBLE_HELP_TEXT", values[2], de, en),
            (
                "unit_rally",
                "TEXT_NEW_CTEXT",
                values[3],
                templates["rally_de"].format(name=de),
                templates["rally_en"].format(name=en),
            ),
            (
                "unit_select",
                "TEXT_NEW_CTEXT",
                values[4],
                templates["select_de"].format(name=de),
                templates["select_en"].format(name=en),
            ),
        )
        for kind, section, raw_index, de_value, en_value in routed:
            entries.append(
                RosterTextEntry(
                    kind=kind,
                    logical_id=unit_id,
                    section=section,
                    raw_index=raw_index,
                    internal_key=f"{section}_{raw_index + 1:03d}",
                    de=de_value,
                    en=en_value,
                )
            )
        bindings.append(
            RosterHudBinding(
                logical_id=unit_id,
                control=values[5],
                internal_key=f"TEXT_BUBBLE_HELP_TEXT_{values[2] + 1:03d}",
            )
        )

    for position, (item, expected) in enumerate(
        zip(raw_buildings, _EXPECTED_BUILDINGS, strict=True)
    ):
        if not isinstance(item, Mapping):
            raise RosterTextError(f"buildings[{position}] must be an object")
        _exact_keys(item, _BUILDING_KEYS, f"buildings[{position}]")
        actual = (
            _text(item["id"], f"buildings[{position}].id", pattern=_SAFE_ID_RE),
            _strict_nonnegative_int(item["title_raw"], f"buildings[{position}].title_raw"),
            _strict_nonnegative_int(item["description_raw"], f"buildings[{position}].description_raw"),
            _text(item["hud_control"], f"buildings[{position}].hud_control", pattern=_CONTROL_RE),
            _text(item["de"], f"buildings[{position}].de"),
            _text(item["en"], f"buildings[{position}].en"),
            _text(item["description_de"], f"buildings[{position}].description_de"),
            _text(item["description_en"], f"buildings[{position}].description_en"),
        )
        if actual != expected:
            raise RosterTextError(f"Pinned building route/copy mismatch at buildings[{position}]")
        building_id, title_raw, description_raw, control, de, en, description_de, description_en = actual
        title_key = f"TEXT_BUBBLE_HELP_TEXT_{title_raw + 1:03d}"
        entries.extend(
            (
                RosterTextEntry(
                    kind="building_name",
                    logical_id=building_id,
                    section="TEXT_BUBBLE_HELP_TEXT",
                    raw_index=title_raw,
                    internal_key=title_key,
                    de=de,
                    en=en,
                ),
                RosterTextEntry(
                    kind="building_description",
                    logical_id=building_id,
                    section="TEXT_BUILDING_DESCRIPTIONS",
                    raw_index=description_raw,
                    internal_key=f"TEXT_BUILDING_DESCRIPTIONS_{description_raw + 1:03d}",
                    de=description_de,
                    en=description_en,
                ),
            )
        )
        bindings.append(
            RosterHudBinding(
                logical_id=building_id,
                control=control,
                internal_key=title_key,
            )
        )

    frozen_entries = tuple(entries)
    frozen_bindings = tuple(bindings)
    if len(frozen_entries) != 64 or len({entry.internal_key for entry in frozen_entries}) != 64:
        raise RosterTextError("Roster expansion must yield exactly 64 unique internal keys")
    if len(frozen_bindings) != 17 or len({item.control.casefold() for item in frozen_bindings}) != 17:
        raise RosterTextError("Roster expansion must yield exactly 17 unique HUD controls")
    forbidden = {
        "TEXT_CHIMP_NAMES_078",
        "TEXT_BUBBLE_HELP_TEXT_323",
        "TEXT_NEW_CTEXT_015",
        "TEXT_BUBBLE_HELP_TEXT_315",
        "TEXT_BUBBLE_HELP_TEXT_010",
    }
    if forbidden & {entry.internal_key for entry in frozen_entries}:
        raise RosterTextError("Roster expansion touches a pinned negative-control key")

    # The recorded recipe pins document the original inputs. Admission uses the
    # installed files' required keys/routes; the generated contract keeps their
    # actual hashes and sizes for integrity checks when the runtime starts.
    for label, pin in (("target_text", target_pin), ("hud_xaml", hud_pin),
                       ("hud_buildings_xaml", hud_buildings_pin)):
        _strict_positive_int(pin["size"], f"{label}.size")
        _sha256(pin["sha256"], f"{label}.sha256")
    _text(target_pin["locale"], "target_text.locale")

    target_text_path = target_game_root / Path(_TARGET_TEXT_RELATIVE)
    target_payload = _read_stable_file(target_text_path, label="target crusader.txt")
    target_locale, target_values = _parse_target_game_text(target_payload)
    target_text_size = len(target_payload)
    target_text_sha = hashlib.sha256(target_payload).hexdigest()

    hud_path = target_game_root / Path(_HUD_XAML_RELATIVE)
    hud_payload = _read_stable_file(hud_path, label="SHCDE-SE HUD_Main.xaml")
    _validate_hud_bindings(hud_payload, frozen_bindings)
    hud_size = len(hud_payload)
    hud_sha = hashlib.sha256(hud_payload).hexdigest()

    hud_buildings_path = target_game_root / Path(_HUD_BUILDINGS_XAML_RELATIVE)
    hud_buildings_payload = _read_stable_file(
        hud_buildings_path, label="SHCDE-SE HUD_Buildings.xaml"
    )
    _validate_hud_building_routes(hud_buildings_payload)
    hud_buildings_size = len(hud_buildings_payload)
    hud_buildings_sha = hashlib.sha256(hud_buildings_payload).hexdigest()

    return RosterTextSpec(
        source_path=source_path,
        source_sha256=hashlib.sha256(payload).hexdigest(),
        target_text_path=target_text_path,
        target_text_sha256=target_text_sha,
        target_text_size=target_text_size,
        target_locale=target_locale,
        target_originals_sha256=_originals_digest(frozen_entries, target_values),
        hud_xaml_path=hud_path,
        hud_xaml_sha256=hud_sha,
        hud_xaml_size=hud_size,
        hud_buildings_xaml_path=hud_buildings_path,
        hud_buildings_xaml_sha256=hud_buildings_sha,
        hud_buildings_xaml_size=hud_buildings_size,
        entries_sha256=_entry_digest(frozen_entries),
        unit_names_sha256=_unit_name_digest(units),
        entries=frozen_entries,
        hud_bindings=frozen_bindings,
    )


def render_roster_tsv(spec: RosterTextSpec) -> str:
    lines = [
        "stronghold-europe-unit-roster\t1",
        f"roster_source_sha256\t{spec.source_sha256}",
        f"target_text_relative_path\t{_TARGET_TEXT_RELATIVE}",
        f"target_text_size\t{spec.target_text_size}",
        f"target_text_sha256\t{spec.target_text_sha256}",
        f"target_locale\t{spec.target_locale}",
        f"target_originals_sha256\t{spec.target_originals_sha256}",
        f"hud_xaml_relative_path\t{_HUD_XAML_RELATIVE}",
        f"hud_xaml_size\t{spec.hud_xaml_size}",
        f"hud_xaml_sha256\t{spec.hud_xaml_sha256}",
        f"hud_buildings_xaml_relative_path\t{_HUD_BUILDINGS_XAML_RELATIVE}",
        f"hud_buildings_xaml_size\t{spec.hud_buildings_xaml_size}",
        f"hud_buildings_xaml_sha256\t{spec.hud_buildings_xaml_sha256}",
        f"entries_sha256\t{spec.entries_sha256}",
        f"unit_names_sha256\t{spec.unit_names_sha256}",
        f"entry_count\t{len(spec.entries)}",
        f"hud_control_count\t{len(spec.hud_bindings)}",
        "entry\tkind\tlogical_id\tsection\traw_index\tinternal_key\tde\ten",
    ]
    lines.extend(
        "\t".join(
            (
                "entry",
                entry.kind,
                entry.logical_id,
                entry.section,
                str(entry.raw_index),
                entry.internal_key,
                entry.de,
                entry.en,
            )
        )
        for entry in spec.entries
    )
    lines.append("hud\tlogical_id\tcontrol\tinternal_key")
    lines.extend(
        "\t".join(("hud", binding.logical_id, binding.control, binding.internal_key))
        for binding in spec.hud_bindings
    )
    return "\n".join(lines) + "\n"

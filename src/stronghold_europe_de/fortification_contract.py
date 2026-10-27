"""Strict loader for the authored fortification-variant contract.

The contract records design intent only.  It deliberately does not expose or
guess a game API: mapper ids are data, and runtime-unverified mechanics retain
an explicit fail-closed fallback.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from math import gcd
from pathlib import Path
import re
from typing import Any


SCHEMA_V1 = "stronghold-europe-de.fortification-variants.v1"
DEFAULT_CONTRACT_RELATIVE_PATH = Path("config/fortification-variants-v1.json")
MAX_CONTRACT_BYTES = 64 * 1024

EXPECTED_VARIANT_IDS = (
    "pointed_palisade",
    "platform_palisade",
    "low_stone_wall",
    "normal_stone_wall",
    "extra_high_stone_wall",
    "stone_wall_wood_spikes",
    "palisade_battlements",
    "wooden_stairs",
    "wooden_platform",
)

_EXPECTED_VARIANT_MAPPERS = {
    "pointed_palisade": (46,),
    "platform_palisade": (25,),
    "low_stone_wall": (46,),
    "normal_stone_wall": (25,),
    "extra_high_stone_wall": (25,),
    "stone_wall_wood_spikes": (25,),
    "palisade_battlements": (25, 26),
    "wooden_stairs": (25,),
    "wooden_platform": (110,),
}
_EXPECTED_VARIANT_KINDS = {
    "pointed_palisade": "linear_wall",
    "platform_palisade": "linear_wall",
    "low_stone_wall": "linear_wall",
    "normal_stone_wall": "linear_wall",
    "extra_high_stone_wall": "linear_wall",
    "stone_wall_wood_spikes": "composite_wall",
    "palisade_battlements": "composite_wall",
    "wooden_stairs": "linear_wall",
    "wooden_platform": "tower_variant",
}
_ROOT_KEYS = frozenset(
    {"schema", "recipe_version", "variants", "native_battlements", "wooden_gatehouse"}
)
_VARIANT_KEYS = frozenset(
    {
        "id",
        "kind",
        "base_mappers",
        "menu_order",
        "save_code",
        "cost_quarters",
        "durability",
        "walk_profile",
        "height_profile",
        "visual_profile",
        "battlement_policy",
        "recipe_version",
        "mechanics_status",
        "fallback",
        "enabled_by_default",
    }
)
_NATIVE_KEYS = frozenset(
    {
        "id",
        "kind",
        "base_mappers",
        "menu_order",
        "save_code",
        "invariant",
        "battlement_policy",
        "recipe_version",
        "mechanics_status",
        "fallback",
        "enabled_by_default",
    }
)
_ID_PATTERN = re.compile(r"[a-z][a-z0-9_]*\Z")
_PROFILE_PATTERN = re.compile(r"[a-z][a-z0-9_]*\Z")
_TSV_HEADER = (
    "record_type",
    "id",
    "kind",
    "menu_order",
    "save_code",
    "base_mappers",
    "wood_quarters",
    "stone_quarters",
    "durability_numerator",
    "durability_denominator",
    "walk_profile",
    "height_profile",
    "visual_profile",
    "battlement_policy",
    "recipe_version",
    "mechanics_status",
    "fallback",
    "enabled_by_default",
    "invariant",
)


class FortificationContractError(ValueError):
    """Raised when the authored contract is unknown, incomplete, or ambiguous."""


@dataclass(frozen=True, slots=True)
class QuarterGoods:
    wood: int
    stone: int


@dataclass(frozen=True, slots=True)
class DurabilityRatio:
    numerator: int
    denominator: int


@dataclass(frozen=True, slots=True)
class FortificationVariant:
    id: str
    kind: str
    base_mappers: tuple[int, ...]
    menu_order: int
    save_code: int
    cost_quarters: QuarterGoods
    durability: DurabilityRatio
    walk_profile: str
    height_profile: str
    visual_profile: str
    battlement_policy: str
    recipe_version: int
    mechanics_status: str
    fallback: str
    enabled_by_default: bool


@dataclass(frozen=True, slots=True)
class NativeBattlementsInvariant:
    id: str
    kind: str
    base_mappers: tuple[int, ...]
    menu_order: int
    save_code: int
    invariant: str
    battlement_policy: str
    recipe_version: int
    mechanics_status: str
    fallback: str
    enabled_by_default: bool


@dataclass(frozen=True, slots=True)
class FortificationContract:
    schema: str
    recipe_version: int
    variants: tuple[FortificationVariant, ...]
    native_battlements: NativeBattlementsInvariant
    wooden_gatehouse: FortificationVariant
    source_size_bytes: int
    source_sha256: str

    @property
    def variant_count(self) -> int:
        return len(self.variants)

    @property
    def record_count(self) -> int:
        return len(self.variants) + 2

    def canonical_tsv(self) -> str:
        records: list[tuple[int, tuple[str, ...]]] = []
        for variant in self.variants:
            records.append(
                (variant.menu_order, _variant_tsv_row("variant", variant))
            )
        records.append(
            (
                self.native_battlements.menu_order,
                _native_tsv_row(self.native_battlements),
            )
        )
        records.append(
            (
                self.wooden_gatehouse.menu_order,
                _variant_tsv_row("wooden_gatehouse", self.wooden_gatehouse),
            )
        )
        rows = [_TSV_HEADER]
        rows.extend(row for _, row in sorted(records, key=lambda item: item[0]))
        return "".join("\t".join(row) + "\n" for row in rows)

    def canonical_tsv_bytes(self) -> bytes:
        return self.canonical_tsv().encode("utf-8")

    @property
    def canonical_tsv_sha256(self) -> str:
        return sha256(self.canonical_tsv_bytes()).hexdigest()


def _variant_tsv_row(
    record_type: str, variant: FortificationVariant
) -> tuple[str, ...]:
    return (
        record_type,
        variant.id,
        variant.kind,
        str(variant.menu_order),
        str(variant.save_code),
        ",".join(str(value) for value in variant.base_mappers),
        str(variant.cost_quarters.wood),
        str(variant.cost_quarters.stone),
        str(variant.durability.numerator),
        str(variant.durability.denominator),
        variant.walk_profile,
        variant.height_profile,
        variant.visual_profile,
        variant.battlement_policy,
        str(variant.recipe_version),
        variant.mechanics_status,
        variant.fallback,
        str(variant.enabled_by_default).lower(),
        "",
    )


def _native_tsv_row(native: NativeBattlementsInvariant) -> tuple[str, ...]:
    return (
        "native_invariant",
        native.id,
        native.kind,
        str(native.menu_order),
        str(native.save_code),
        ",".join(str(value) for value in native.base_mappers),
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        native.battlement_policy,
        str(native.recipe_version),
        native.mechanics_status,
        native.fallback,
        str(native.enabled_by_default).lower(),
        native.invariant,
    )


def _fail_constant(value: str) -> None:
    raise FortificationContractError(f"Non-finite JSON number is forbidden: {value}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise FortificationContractError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _object(value: object, label: str, keys: frozenset[str]) -> dict[str, Any]:
    if type(value) is not dict:
        raise FortificationContractError(f"{label} must be an object")
    result = value
    actual = set(result)
    if actual != keys:
        missing = ", ".join(sorted(keys - actual)) or "none"
        extra = ", ".join(sorted(actual - keys)) or "none"
        raise FortificationContractError(
            f"{label} keys differ (missing: {missing}; extra: {extra})"
        )
    return result


def _integer(value: object, label: str, *, minimum: int, maximum: int) -> int:
    if type(value) is not int or value < minimum or value > maximum:
        raise FortificationContractError(
            f"{label} must be an integer in [{minimum}, {maximum}]"
        )
    return value


def _boolean(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise FortificationContractError(f"{label} must be a boolean")
    return value


def _token(value: object, label: str, pattern: re.Pattern[str]) -> str:
    if type(value) is not str or pattern.fullmatch(value) is None:
        raise FortificationContractError(f"{label} is not a canonical token")
    return value


def _enum(value: object, label: str, allowed: frozenset[str]) -> str:
    token = _token(value, label, _PROFILE_PATTERN)
    if token not in allowed:
        raise FortificationContractError(
            f"{label} must be one of: {', '.join(sorted(allowed))}"
        )
    return token


def _mappers(value: object, label: str) -> tuple[int, ...]:
    if type(value) is not list or not value:
        raise FortificationContractError(f"{label} must be a non-empty array")
    result = tuple(
        _integer(item, f"{label}[{index}]", minimum=0, maximum=459)
        for index, item in enumerate(value)
    )
    if len(result) != len(set(result)):
        raise FortificationContractError(f"{label} contains duplicate mapper ids")
    if 35 in result:
        raise FortificationContractError(
            f"{label} uses mapper 35, which is probe-only and not a catalogue base"
        )
    return result


def _cost(value: object, label: str) -> QuarterGoods:
    raw = _object(value, label, frozenset({"wood", "stone"}))
    cost = QuarterGoods(
        wood=_integer(raw["wood"], f"{label}.wood", minimum=0, maximum=100_000),
        stone=_integer(
            raw["stone"], f"{label}.stone", minimum=0, maximum=100_000
        ),
    )
    if cost.wood == 0 and cost.stone == 0:
        raise FortificationContractError(f"{label} may not be free")
    return cost


def _durability(value: object, label: str) -> DurabilityRatio:
    raw = _object(value, label, frozenset({"numerator", "denominator"}))
    ratio = DurabilityRatio(
        numerator=_integer(
            raw["numerator"], f"{label}.numerator", minimum=1, maximum=10_000
        ),
        denominator=_integer(
            raw["denominator"], f"{label}.denominator", minimum=1, maximum=10_000
        ),
    )
    if gcd(ratio.numerator, ratio.denominator) != 1:
        raise FortificationContractError(f"{label} must be a reduced fraction")
    return ratio


def _parse_variant(
    value: object, label: str, *, contract_recipe_version: int
) -> FortificationVariant:
    raw = _object(value, label, _VARIANT_KEYS)
    recipe_version = _integer(
        raw["recipe_version"], f"{label}.recipe_version", minimum=1, maximum=1
    )
    if recipe_version != contract_recipe_version:
        raise FortificationContractError(
            f"{label}.recipe_version differs from the contract recipe_version"
        )
    return FortificationVariant(
        id=_token(raw["id"], f"{label}.id", _ID_PATTERN),
        kind=_enum(
            raw["kind"],
            f"{label}.kind",
            frozenset(
                {
                    "linear_wall",
                    "composite_wall",
                    "gatehouse",
                    "stair_variant",
                    "tower_variant",
                }
            ),
        ),
        base_mappers=_mappers(raw["base_mappers"], f"{label}.base_mappers"),
        menu_order=_integer(
            raw["menu_order"], f"{label}.menu_order", minimum=0, maximum=10_000
        ),
        save_code=_integer(
            raw["save_code"], f"{label}.save_code", minimum=1, maximum=255
        ),
        cost_quarters=_cost(raw["cost_quarters"], f"{label}.cost_quarters"),
        durability=_durability(raw["durability"], f"{label}.durability"),
        walk_profile=_token(
            raw["walk_profile"], f"{label}.walk_profile", _PROFILE_PATTERN
        ),
        height_profile=_token(
            raw["height_profile"], f"{label}.height_profile", _PROFILE_PATTERN
        ),
        visual_profile=_token(
            raw["visual_profile"], f"{label}.visual_profile", _PROFILE_PATTERN
        ),
        battlement_policy=_enum(
            raw["battlement_policy"],
            f"{label}.battlement_policy",
            frozenset(
                {
                    "preserve_separate_native_action",
                    "requires_native_battlement_overlay",
                    "not_applicable",
                }
            ),
        ),
        recipe_version=recipe_version,
        mechanics_status=_enum(
            raw["mechanics_status"],
            f"{label}.mechanics_status",
            frozenset({"runtime_unverified", "measurement_required"}),
        ),
        fallback=_enum(
            raw["fallback"],
            f"{label}.fallback",
            frozenset({"visual_beta_native_base", "disable_variant"}),
        ),
        enabled_by_default=_boolean(
            raw["enabled_by_default"], f"{label}.enabled_by_default"
        ),
    )


def _parse_native(
    value: object, *, contract_recipe_version: int
) -> NativeBattlementsInvariant:
    label = "native_battlements"
    raw = _object(value, label, _NATIVE_KEYS)
    recipe_version = _integer(
        raw["recipe_version"], f"{label}.recipe_version", minimum=1, maximum=1
    )
    native = NativeBattlementsInvariant(
        id=_token(raw["id"], f"{label}.id", _ID_PATTERN),
        kind=_enum(raw["kind"], f"{label}.kind", frozenset({"native_action"})),
        base_mappers=_mappers(raw["base_mappers"], f"{label}.base_mappers"),
        menu_order=_integer(
            raw["menu_order"], f"{label}.menu_order", minimum=0, maximum=10_000
        ),
        save_code=_integer(
            raw["save_code"], f"{label}.save_code", minimum=0, maximum=0
        ),
        invariant=_enum(
            raw["invariant"],
            f"{label}.invariant",
            frozenset({"must_remain_available"}),
        ),
        battlement_policy=_enum(
            raw["battlement_policy"],
            f"{label}.battlement_policy",
            frozenset({"must_remain_available"}),
        ),
        recipe_version=recipe_version,
        mechanics_status=_enum(
            raw["mechanics_status"],
            f"{label}.mechanics_status",
            frozenset({"native_preserved"}),
        ),
        fallback=_enum(
            raw["fallback"],
            f"{label}.fallback",
            frozenset({"preserve_native_action"}),
        ),
        enabled_by_default=_boolean(
            raw["enabled_by_default"], f"{label}.enabled_by_default"
        ),
    )
    if recipe_version != contract_recipe_version:
        raise FortificationContractError(
            "native_battlements.recipe_version differs from the contract"
        )
    if (
        native.id != "native_battlements"
        or native.base_mappers != (26,)
        or native.save_code != 0
        or not native.enabled_by_default
    ):
        raise FortificationContractError(
            "The native battlement action must remain enabled on mapper 26"
        )
    return native


def _validate_authored_semantics(
    variants: tuple[FortificationVariant, ...],
    native: NativeBattlementsInvariant,
    gate: FortificationVariant,
) -> None:
    ids = tuple(variant.id for variant in variants)
    if ids != EXPECTED_VARIANT_IDS:
        raise FortificationContractError(
            "variants must contain the nine authored ids in canonical order"
        )
    for variant in variants:
        if variant.base_mappers != _EXPECTED_VARIANT_MAPPERS[variant.id]:
            raise FortificationContractError(
                f"variants.{variant.id}.base_mappers changed"
            )
        if variant.kind != _EXPECTED_VARIANT_KINDS[variant.id]:
            raise FortificationContractError(f"variants.{variant.id}.kind changed")
        # 2026-09-04: the wooden stairs are a wall kind; only the
        # platform still waits behind its measurement gate.
        wall_variant = variant.id != "wooden_platform"
        expected_fallback = (
            "visual_beta_native_base" if wall_variant else "disable_variant"
        )
        expected_enabled = wall_variant
        if (
            variant.mechanics_status != "runtime_unverified"
            or variant.fallback != expected_fallback
            or variant.enabled_by_default != expected_enabled
        ):
            raise FortificationContractError(
                f"variants.{variant.id} lost its explicit beta/fallback contract"
            )
    expected_save_codes = {
        "pointed_palisade": 1,
        "platform_palisade": 2,
        "low_stone_wall": 3,
        "normal_stone_wall": 4,
        "extra_high_stone_wall": 5,
        "stone_wall_wood_spikes": 6,
        "palisade_battlements": 7,
        "wooden_stairs": 9,
        "wooden_platform": 10,
    }
    for variant in variants:
        if variant.save_code != expected_save_codes[variant.id]:
            raise FortificationContractError(
                f"variants.{variant.id}.save_code changed"
            )
    if (
        variants[-2].cost_quarters != QuarterGoods(wood=4, stone=0)
        or variants[-2].durability != DurabilityRatio(1, 1)
        or variants[-1].cost_quarters != QuarterGoods(wood=40, stone=0)
        or variants[-1].durability != DurabilityRatio(1, 1)
    ):
        raise FortificationContractError(
            "unverified wooden stair/platform placeholders changed"
        )
    if (
        gate.id != "wooden_gatehouse"
        or gate.kind != "gatehouse"
        or gate.base_mappers != (140, 141, 142, 143)
        or gate.save_code != 8
        or gate.durability != DurabilityRatio(numerator=13, denominator=20)
        or gate.mechanics_status != "measurement_required"
        or gate.fallback != "disable_variant"
        or gate.enabled_by_default
    ):
        raise FortificationContractError(
            "wooden_gatehouse must stay disabled until its four mappers are measured"
        )
    menu_orders = [variant.menu_order for variant in variants]
    menu_orders.extend((native.menu_order, gate.menu_order))
    if len(menu_orders) != len(set(menu_orders)):
        raise FortificationContractError("menu_order values must be unique")
    if menu_orders != sorted(menu_orders):
        raise FortificationContractError(
            "records must be stored in increasing menu_order"
        )
    save_codes = [variant.save_code for variant in variants]
    save_codes.extend((native.save_code, gate.save_code))
    if len(save_codes) != len(set(save_codes)):
        raise FortificationContractError("save_code values must be unique")


def load_fortification_contract(path: str | Path) -> FortificationContract:
    """Load schema v1, rejecting unknown fields and unmeasured enablement."""

    source_path = Path(path)
    try:
        payload = source_path.read_bytes()
    except OSError as exc:
        raise FortificationContractError(
            f"Cannot read fortification contract {source_path}: {exc}"
        ) from exc
    if not payload or len(payload) > MAX_CONTRACT_BYTES:
        raise FortificationContractError(
            f"Contract size must be in [1, {MAX_CONTRACT_BYTES}] bytes"
        )
    if payload.startswith(b"\xef\xbb\xbf"):
        raise FortificationContractError("UTF-8 BOM is forbidden")
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise FortificationContractError("Contract is not strict UTF-8") from exc
    try:
        value = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_fail_constant,
        )
    except json.JSONDecodeError as exc:
        raise FortificationContractError(
            f"Contract is not valid JSON at line {exc.lineno}, column {exc.colno}"
        ) from exc

    raw = _object(value, "contract", _ROOT_KEYS)
    if raw["schema"] != SCHEMA_V1:
        raise FortificationContractError(f"Unsupported schema: {raw['schema']!r}")
    recipe_version = _integer(
        raw["recipe_version"], "recipe_version", minimum=1, maximum=1
    )
    if type(raw["variants"]) is not list or len(raw["variants"]) != 9:
        raise FortificationContractError("variants must contain exactly nine rows")
    variants = tuple(
        _parse_variant(
            item,
            f"variants[{index}]",
            contract_recipe_version=recipe_version,
        )
        for index, item in enumerate(raw["variants"])
    )
    native = _parse_native(
        raw["native_battlements"], contract_recipe_version=recipe_version
    )
    gate = _parse_variant(
        raw["wooden_gatehouse"],
        "wooden_gatehouse",
        contract_recipe_version=recipe_version,
    )
    _validate_authored_semantics(variants, native, gate)
    return FortificationContract(
        schema=SCHEMA_V1,
        recipe_version=recipe_version,
        variants=variants,
        native_battlements=native,
        wooden_gatehouse=gate,
        source_size_bytes=len(payload),
        source_sha256=sha256(payload).hexdigest(),
    )


__all__ = [
    "DEFAULT_CONTRACT_RELATIVE_PATH",
    "DurabilityRatio",
    "EXPECTED_VARIANT_IDS",
    "FortificationContract",
    "FortificationContractError",
    "FortificationVariant",
    "MAX_CONTRACT_BYTES",
    "NativeBattlementsInvariant",
    "QuarterGoods",
    "SCHEMA_V1",
    "load_fortification_contract",
]

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
import hashlib
import json
from math import isfinite
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import struct
import subprocess
from typing import Any
import unicodedata
import zlib

from PIL import Image, UnidentifiedImageError

from .asset_stream_contract import (
    BC7_ATLAS_BACKEND_KIND,
    BC7_BUILD_REPORT_SCHEMA,
    BC7_INDEX_SCHEMA,
    BC7_MAX_PAGES_PER_GROUP,
    BUILD_REPORT_SCHEMA as ASSET_STREAM_BUILD_REPORT_SCHEMA,
    BUILD_TARGET as ASSET_STREAM_BUILD_TARGET,
    INDEX_OUTPUT_PATH as ASSET_STREAM_INDEX_PATH,
    MAX_FRAMES_PER_GROUP as ASSET_STREAM_MAX_FRAMES,
    MAX_GROUPS as ASSET_STREAM_MAX_GROUPS,
    MAX_INDEX_BYTES as ASSET_STREAM_MAX_INDEX_BYTES,
    MAX_PAGES_PER_GROUP as ASSET_STREAM_MAX_PAGES,
    MAX_PREFLIGHT_FRAMES_PER_GROUP as ASSET_STREAM_MAX_PREFLIGHT_FRAMES,
    OMISSION_FRAME_COUNT as ASSET_STREAM_OMISSION_FRAME_COUNT,
    OMISSION_SLOT_COUNT as ASSET_STREAM_OMISSION_SLOT_COUNT,
    VANILLA_OMISSION_REASONS as ASSET_STREAM_OMISSION_REASONS,
    AssetBundleBuildReport,
    AssetBundleBuildReportV2,
    AssetBundleIndex,
    AssetBundleIndexV2,
    AssetStreamContractError,
    BundleArtifact as ContractBundleArtifact,
    UnityIdentity as AssetStreamUnityIdentity,
    canonical_group_slug,
    canonical_json_bytes,
    find_legacy_atlas_outputs,
    parse_asset_bundle_index,
    parse_asset_bundle_index_v2,
    parse_atlas_backend,
    require_safe_relative_path,
    validate_backend_output_exclusivity,
    validate_bundle_output_records,
    validate_bundle_output_records_v2,
)

from .derived_feasibility import PLACEMENT_PROOF_ALGORITHM
from .gm_atlas import (
    AtlasGroupSpec,
    DERIVED_FRAME_POLICY_MODE,
    DERIVED_POLICY_139_CONTRACTS,
    DERIVED_POLICY_139_GROUPS,
    GEOMETRY_POLICY_NATIVE_AUTHORED_PIVOT,
    GEOMETRY_POLICY_NATIVE_REANCHORED,
    GEOMETRY_POLICY_TARGET_CANVAS,
    GMAtlasError,
    KEEP_CRUSADER_PROOF_STATUS,
    LOADER_139_GROUPS,
    NATIVE_SOURCE_AUTHORED_PIVOT_PROOF_ALGORITHM,
    NATIVE_SOURCE_GEOMETRY_PROOF_ALGORITHM,
    NATIVE_SOURCE_PROOF_STATUS,
    NATIVE_SOURCE_REANCHORED_139_CONTRACTS,
    REVIEW_INDIVIDUAL_CONTRACT_KIND,
    REVIEW_INDIVIDUAL_CONTRACT_PREFIX,
    REVIEW_INDIVIDUAL_MAIN_CATEGORY,
    REVIEW_INDIVIDUAL_MASK_CATEGORY,
    REVIEW_INDIVIDUAL_SOURCE_ONLY_MODE,
    REVIEW_139_GROUP_TEXTURES,
    REVIEW_NATIVE_GEOMETRY_139_GROUPS,
    REVIEW_FRAME_POLICY_MODE,
    REVIEW_FRAME_POLICY_MODE_V2,
    REVIEW_FRAME_POLICY_MODE_V3,
    SHARED_GM_ATLAS_139_CONTRACTS,
    SHARED_GM_ATLAS_KIND,
    SHARED_GM_ATLAS_MODE,
    SHARED_GM_ATLAS_PROFILE_KEY,
    SharedGMAtlasMemberSpec,
    SharedGMAtlasSpec,
    SOURCE_FRAME_ORIGIN,
    SOURCE_REMAP_139_CONTRACTS,
    SOURCE_REMAP_POLICY_MODE,
    SOURCE_REMAP_PROOF_ALGORITHM,
    SPARSE_KEEP_POLICY_MODE,
    SPARSE_KEEP_PROOF_ALGORITHM,
    TARGET_FRAME_ORIGIN,
    derived_frame_proof_digest,
    native_source_authored_pivot_proof,
    native_source_geometry_contract,
    native_source_geometry_proof,
    parse_loader_frame_name,
    review_individual_payload_digest,
    shared_gm_atlas_proof,
    source_remap_proof,
    source_remap_reference_proof,
    sparse_keep_frame_proof,
    required_native_source_geometry_contract,
    visible_blue_pixel_count,
)
from .hashing import sha256_file
from .fortification_contract import (
    DEFAULT_CONTRACT_RELATIVE_PATH as FORTIFICATION_CONTRACT_SOURCE,
    FortificationContractError,
    load_fortification_contract,
)
from .locale_overlay import (
    LocaleOverlay,
    LocaleOverlayError,
    locale_manifest_metadata,
    parse_locale_overlay,
    roster_text_sha256,
)
from .profile_contract import profile_output_contract_checks
from .runtime_build import (
    RuntimeBuildError,
    UiTextureRuntimeManifest,
    _DIPLOMACY_RULES_V1,
    _FORTIFICATION_V1_SOURCE_SHA256,
    _FORTIFICATION_V1_SOURCE_SIZE,
    _FORTIFICATION_V1_TSV_SHA256,
    _FORTIFICATION_V1_TSV_SIZE,
    _pcm_stream_manifest_text,
    parse_ui_texture_runtime_manifest_v2,
    parse_runtime_contract,
    runtime_source_set_sha256,
    validate_wav,
)
from .ui_asset_bundle import (
    UI_BACKEND_KIND,
    UiAssetBundleError,
    load_ui_quality_policy,
    load_ui_texture_source_manifest,
)
from .unity_asset_bundle import (
    BUILD_OPTIONS as ASSET_STREAM_BUILD_OPTIONS,
    UnityAssetBundleError,
    _validate_asset_bundle_payload,
    validate_asset_bundle_payload_v2_external,
)


@dataclass(frozen=True)
class ValidationCheck:
    name: str
    ok: bool
    detail: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


FORBIDDEN_SUFFIXES = {".exe", ".dll", ".rne", ".assets", ".ress"}
RUNTIME_DLL_PATH = "StrongholdEuropeDE.Runtime.dll"
RUNTIME_CONTRACT_PATH = "Runtime/audio-profile.tsv"
RUNTIME_DLL_CATEGORY = "runtime_companion"
RUNTIME_DLL_SOURCE_REFERENCE = (
    "runtime/StrongholdEuropeDE.Runtime/StrongholdEuropeDE.Runtime.csproj"
)
RUNTIME_CONTRACT_SOURCE_REFERENCE = (
    "runtime/StrongholdEuropeDE.Runtime/audio-profile.json"
)
UI_TEXTURE_V1_MANIFEST_PATH = "Runtime/ui-textures-v1.tsv"
UI_TEXTURE_V2_MANIFEST_PATH = "Runtime/ui-textures-v2.tsv"
UI_TEXTURE_BUNDLE_PREFIX = "Runtime/UiAssetBundles/win64/"
UI_TEXTURE_SOURCE_CONFIG_PATH = "config/ui-textures-bc7-v1.json"
UI_TEXTURE_QUALITY_POLICY_PATH = "config/ui-bc7-quality-v1.json"
UI_TEXTURE_EDITOR_SOURCE_PATH = (
    "tools/unity_asset_bundle/StrongholdEuropeUiTextureBundleBuilder.cs"
)
UI_TEXTURE_MANIFEST_SOURCE_REFERENCE = (
    "generated:config/ui-textures-bc7-v1.json"
)
UI_TEXTURE_EXPECTED_ENTRY_COUNT = 128
UI_TEXTURE_MAX_RESIDENT_BYTES = 1024**3
RUNTIME_ASSEMBLY_NAME = "StrongholdEuropeDE.Runtime"
RUNTIME_ASSEMBLY_VERSION = "0.2.0.0"
RUNTIME_PLUGIN_ID = "strongholdeuropede.runtime.private"
RUNTIME_ROSTER_CONTRACT_PATH = "Runtime/unit-roster.tsv"
RUNTIME_ROSTER_CONTRACT_CATEGORY = "runtime_roster_contract"
RUNTIME_ROSTER_CONTRACT_KIND = "stronghold_europe_unit_roster_runtime_v1"
RUNTIME_ROSTER_SOURCE_REFERENCE = "config/unit-roster-text.json"
RUNTIME_ROSTER_SOURCE_SHA256 = (
    "93c0cd8a386617f72b81d773cfff16e4281ff836ff905a5df28e61bfc1c7a2cf"
)
RUNTIME_ROSTER_MANIFEST_SHA256 = (
    "c3a31527ffbc5ae654bc4bcd68ee3a40f62fc62dbf002168d17853e57f24a33c"
)
RUNTIME_ROSTER_ENTRIES_SHA256 = (
    "ad32134663e592e3275b4968b7acf5047e168006ec8228f1d76cd8bc6796d7c2"
)
RUNTIME_ROSTER_UNIT_NAMES_SHA256 = (
    "18ee1e6d1e1f5acca43cc778b0b8566ba8a97b3702bf52cdf547dc41ab8f10c9"
)
RUNTIME_ROSTER_ORIGINALS_SHA256 = (
    "182c2839a2f27b28b8ddd1a8c439478ea88ed0accdb4acfda231703d8509cbdb"
)
RUNTIME_ROSTER_TARGET_TEXT_PATH = "Assets/Text/crusader.txt"
RUNTIME_ROSTER_TARGET_TEXT_SIZE = 317902
RUNTIME_ROSTER_TARGET_TEXT_SHA256 = (
    "41e44ee6a00b5ea1a5965b3a1dc9807ab7f45e665484cc214e9920109d326451"
)
RUNTIME_ROSTER_TARGET_LOCALE = "dede"
RUNTIME_ROSTER_HUD_XAML_PATH = (
    "BepInEx/plugins/000shcdese/Override/Assets/GUI/XAMLResources/HUD_Main.xaml"
)
RUNTIME_ROSTER_HUD_XAML_SIZE = 332899
RUNTIME_ROSTER_HUD_XAML_SHA256 = (
    "b84c40b60ac4b790f9ecb5ae712234664ddedb3c73a69988dd5a8b8187a4ab74"
)
RUNTIME_ROSTER_HUD_BUILDINGS_XAML_PATH = (
    "BepInEx/plugins/000shcdese/Override/Assets/GUI/XAMLResources/HUD_Buildings.xaml"
)
RUNTIME_ROSTER_HUD_BUILDINGS_XAML_SIZE = 395704
RUNTIME_ROSTER_HUD_BUILDINGS_XAML_SHA256 = (
    "2fc64ba15eed1db69aeae846379c0d2dff24b1df4dd1c070ab0c24cbd34a90c2"
)
RUNTIME_ROSTER_ENTRY_COUNT = 64
RUNTIME_ROSTER_HUD_CONTROL_COUNT = 17
RUNTIME_FORTIFICATION_CONTRACT_PATH = "Runtime/fortifications-v1.tsv"
RUNTIME_FORTIFICATION_CONTRACT_CATEGORY = "runtime_fortification_contract"
RUNTIME_FORTIFICATION_CONTRACT_KIND = (
    "stronghold_europe_fortification_runtime_v1"
)
RUNTIME_FORTIFICATION_SOURCE_REFERENCE = FORTIFICATION_CONTRACT_SOURCE.as_posix()
RUNTIME_PREREQUISITE_MVIDS = {
    "shcdese": "4b17e151-08fd-463f-9596-415bf3435ca1",
    "nlua": "401e1007-417b-4366-a608-f6b8ffe5ca2e",
    "keralua": "4ab3a0be-7da2-4255-8556-dcab69a7adc4",
    "redbird_core": "0ca8fc0a-fb1d-4661-b68d-51f2000bad45",
    "system_memory": "27c7dfb4-b639-4500-8914-8d6e6caca8cb",
    "bepinex_core": "d1b92069-86c2-41dc-ad96-bb21eee55a97",
    "harmony": "474744d6-5d8e-460f-a08c-d5fd82b5d65f",
    # The extender publishes its native detours as R3 observables, so the farm
    # placement rule links against R3 and it is pinned like every other one.
    "r3": "b58e2dc8-2e7f-419e-bf7d-bc9786b1bf15",
    "assembly_csharp": "1ad0eaf4-bb64-4eb8-9126-ff328de7f68c",
    "noesis_gui": "7383317c-d471-469f-ac85-2aafde4cb013",
    "unity_engine": "2098d95a-268b-46a0-9676-e36d11d685a5",
    "unity_engine_core_module": "806021f9-55ec-43bb-97cd-1adca41e00da",
    "unity_engine_asset_bundle_module": "90538353-7aa0-4a16-ad89-f45382d0c777",
    "unity_engine_audio_module": "54f216ae-0646-4f4f-aa73-c4817fcfcede",
    "unity_engine_image_conversion_module": (
        "ee44ec0b-022d-49ac-b713-628f3e55be93"
    ),
}

_RUNTIME_ROSTER_METADATA_KEYS = frozenset(
    {
        "kind",
        "plugin_id",
        "manifest_sha256",
        "roster_source_sha256",
        "entries_sha256",
        "target_originals_sha256",
        "target_text_sha256",
        "target_text_size",
        "hud_xaml_sha256",
        "hud_xaml_size",
        "hud_buildings_xaml_sha256",
        "hud_buildings_xaml_size",
        "entry_count",
        "hud_control_count",
    }
)
_RUNTIME_FORTIFICATION_METADATA_KEYS = frozenset(
    {
        "kind",
        "plugin_id",
        "schema",
        "recipe_version",
        "variant_count",
        "record_count",
        "source_size_bytes",
        "source_sha256",
        "catalog_tsv_size",
        "catalog_tsv_sha256",
    }
)
_RUNTIME_DLL_METADATA_KEYS = frozenset(
    {
        "kind",
        "plugin_id",
        "assembly_name",
        "assembly_version",
        "target_framework",
        "runtime_prerequisite_config_id",
        "runtime_prerequisite_mvids",
        "manifest_sha256",
        "unit_roster_names",
        "farm_placement",
        "worker_militia",
        "diplomacy",
        "diplomacy_rules",
        "fortifications",
        "fortification_catalog_sha256",
        "dock_placement",
        "dock_placement_rules",
        "runtime_source_set_sha256",
        "asset_stream_enabled",
        "asset_stream_index_sha256",
        "asset_stream_backend_kind",
        "asset_stream_index_schema",
        "asset_stream_quality_state",
        "asset_stream_promotable",
        "ui_texture_streaming_enabled",
        "ui_texture_manifest_sha256",
        "pcm_streaming_enabled",
        "pcm_stream_manifest_sha256",
    }
)
_RUNTIME_CONTRACT_METADATA_KEYS = frozenset(
    {
        "kind",
        "plugin_id",
        "manifest_sha256",
        "audio_payload",
        "foliage_tree_apple",
        "track_count",
    }
)
_RUNTIME_ROSTER_LOGO_PATH = (
    "Override/Assets/GUI/Sprites/strongholdeuropede.private.png"
)
_RUNTIME_ROSTER_ISOLATED_OUTPUTS = frozenset(
    {
        "info.json",
        RUNTIME_DLL_PATH,
        RUNTIME_CONTRACT_PATH,
        RUNTIME_ROSTER_CONTRACT_PATH,
        _RUNTIME_ROSTER_LOGO_PATH,
    }
)
_RUNTIME_ROSTER_CANARY_OUTPUT_ENVELOPES = {
    "info.json": {
        "category": "mod_metadata",
        "source_reference": None,
        "metadata": None,
        "width": None,
        "height": None,
        "lost_alpha": None,
    },
    RUNTIME_DLL_PATH: {
        "category": RUNTIME_DLL_CATEGORY,
        "source_reference": RUNTIME_DLL_SOURCE_REFERENCE,
        "width": None,
        "height": None,
        "lost_alpha": None,
    },
    RUNTIME_CONTRACT_PATH: {
        "category": "runtime_contract",
        "source_reference": RUNTIME_CONTRACT_SOURCE_REFERENCE,
        "width": None,
        "height": None,
        "lost_alpha": None,
    },
    RUNTIME_ROSTER_CONTRACT_PATH: {
        "category": RUNTIME_ROSTER_CONTRACT_CATEGORY,
        "source_reference": RUNTIME_ROSTER_SOURCE_REFERENCE,
        "width": None,
        "height": None,
        "lost_alpha": None,
    },
    _RUNTIME_ROSTER_LOGO_PATH: {
        "category": "mod_logo",
        "source_reference": "resources.assets:Texture2D:23:icon",
        "metadata": None,
        "width": 256,
        "height": 256,
        "lost_alpha": 0,
    },
}
_STATIC_BUILD_MANIFEST_KEYS = frozenset(
    {
        "schema_version",
        "profile_id",
        "profile_description",
        "source_build_id",
        "target_build_id",
        "mod_info",
        "outputs",
    }
)
_STATIC_OUTPUT_ENTRY_KEYS = frozenset(
    {
        "relative_path",
        "category",
        "size",
        "sha256",
        "width",
        "height",
        "source_reference",
        "lost_alpha",
        "metadata",
    }
)


def _runtime_roster_canary_output_contract(
    output_by_path: dict[str, dict[str, Any]],
) -> tuple[bool, str]:
    errors: list[str] = []
    if set(output_by_path) != _RUNTIME_ROSTER_ISOLATED_OUTPUTS:
        errors.append(
            "path set differs: "
            f"actual={sorted(output_by_path)!r}"
        )
    for relative, expected in _RUNTIME_ROSTER_CANARY_OUTPUT_ENVELOPES.items():
        entry = output_by_path.get(relative)
        if not isinstance(entry, dict):
            errors.append(f"missing output envelope: {relative}")
            continue
        mismatches = {
            field: {"expected": value, "actual": entry.get(field)}
            for field, value in expected.items()
            if entry.get(field) != value
        }
        if mismatches:
            errors.append(f"{relative}: {json.dumps(mismatches, sort_keys=True)}")
    return not errors, json.dumps({"errors": errors}, sort_keys=True)
_RUNTIME_ROSTER_KIND_SECTIONS = {
    "unit_name": "TEXT_CHIMP_NAMES",
    "unit_bubble": "TEXT_BUBBLE_HELP_TEXT",
    "unit_rally": "TEXT_NEW_CTEXT",
    "unit_select": "TEXT_NEW_CTEXT",
    "building_name": "TEXT_BUBBLE_HELP_TEXT",
    "building_description": "TEXT_BUILDING_DESCRIPTIONS",
}
_RUNTIME_ROSTER_KIND_COUNTS = {
    "unit_name": 15,
    "unit_bubble": 15,
    "unit_rally": 15,
    "unit_select": 15,
    "building_name": 2,
    "building_description": 2,
}
_RUNTIME_ROSTER_HUD_BINDINGS = (
    ("arabian_bowman", "ButtonBuildMEArabBow", "TEXT_BUBBLE_HELP_TEXT_316"),
    ("slave", "ButtonBuildMEArabSlave", "TEXT_BUBBLE_HELP_TEXT_317"),
    ("slinger", "ButtonBuildMEArabSlinger", "TEXT_BUBBLE_HELP_TEXT_318"),
    ("assassin", "ButtonBuildMEArabAssassin", "TEXT_BUBBLE_HELP_TEXT_319"),
    ("horse_archer", "ButtonBuildMEArabHorseArcher", "TEXT_BUBBLE_HELP_TEXT_320"),
    ("arabian_swordsman", "ButtonBuildMEArabSwordsman", "TEXT_BUBBLE_HELP_TEXT_321"),
    ("fire_thrower", "ButtonBuildMEArabGrenadier", "TEXT_BUBBLE_HELP_TEXT_322"),
    ("camel_lancer", "ButtonBuildMECamelLancer", "TEXT_BUBBLE_HELP_TEXT_350"),
    ("healer", "ButtonBuildMEHealer", "TEXT_BUBBLE_HELP_TEXT_351"),
    ("eunuch", "ButtonBuildMEEunuch", "TEXT_BUBBLE_HELP_TEXT_352"),
    ("ambusher", "ButtonBuildMEAmbusher", "TEXT_BUBBLE_HELP_TEXT_353"),
    ("skirmisher", "ButtonBuildMESkirmisher", "TEXT_BUBBLE_HELP_TEXT_354"),
    ("heavy_camel", "ButtonBuildMEHeavyCamel", "TEXT_BUBBLE_HELP_TEXT_355"),
    ("sapper", "ButtonBuildMESapper", "TEXT_BUBBLE_HELP_TEXT_356"),
    ("demolisher", "ButtonBuildMEDemolisher", "TEXT_BUBBLE_HELP_TEXT_357"),
    ("mercenary_post", "ButtonBuildWoodenBarracks", "TEXT_BUBBLE_HELP_TEXT_011"),
    (
        "bedouin_stockade",
        "ButtonBuildWoodenBedouinStockade",
        "TEXT_BUBBLE_HELP_TEXT_349",
    ),
)
_RUNTIME_ROSTER_FORBIDDEN_KEYS = frozenset(
    {
        "TEXT_CHIMP_NAMES_078",
        "TEXT_BUBBLE_HELP_TEXT_323",
        "TEXT_NEW_CTEXT_015",
        "TEXT_BUBBLE_HELP_TEXT_315",
        "TEXT_BUBBLE_HELP_TEXT_010",
    }
)
ROSTER_LOCALE_FILES = {
    "Locales/de-DE/crusader.txt": {
        "locale": "de-DE",
        "source_reference": "project-file:assets/locales/de-DE/crusader.txt",
        "sha256": "4532803116899dafcd392042177660fa7cddcd72cc3d289cb3c54622af0c43e9",
    },
    "Locales/en-US/crusader.txt": {
        "locale": "en-US",
        "source_reference": "project-file:assets/locales/en-US/crusader.txt",
        "sha256": "b612b220e3ab2a6ec06b1bc91a26d3c0743eb858cdc3c0d2c58ae6c13397983f",
    },
}


class _DuplicateJsonKeyError(ValueError):
    pass


class _InvalidJsonConstantError(ValueError):
    pass


def _reject_json_constant(value: str) -> object:
    raise _InvalidJsonConstantError(f"non-finite JSON constant: {value}")


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKeyError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _read_json_object(path: Path) -> tuple[dict[str, Any] | None, str]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        _DuplicateJsonKeyError,
        _InvalidJsonConstantError,
        RecursionError,
        ValueError,
    ) as exc:
        return None, f"cannot decode JSON object: {exc}"
    if not isinstance(value, dict):
        return None, (
            "top-level JSON value must be an object, got "
            f"{type(value).__name__}"
        )
    pending: list[object] = [value]
    while pending:
        candidate = pending.pop()
        if isinstance(candidate, float) and not isfinite(candidate):
            return None, "cannot decode JSON object: non-finite numeric value"
        if isinstance(candidate, dict):
            pending.extend(candidate.values())
        elif isinstance(candidate, list):
            pending.extend(candidate)
    return value, "decoded JSON object"


def _static_manifest_shape(manifest: dict[str, Any]) -> tuple[bool, str]:
    errors: list[str] = []
    if set(manifest) != _STATIC_BUILD_MANIFEST_KEYS:
        errors.append(
            "build manifest keys are not exact: "
            f"missing={sorted(_STATIC_BUILD_MANIFEST_KEYS-set(manifest))!r} "
            f"extra={sorted(set(manifest)-_STATIC_BUILD_MANIFEST_KEYS)!r}"
        )
    if type(manifest.get("schema_version")) is not int:
        errors.append("schema_version must be an integer")
    elif manifest["schema_version"] != 1:
        errors.append(f"unsupported schema_version={manifest['schema_version']!r}")
    for field_name in ("profile_id", "source_build_id", "target_build_id"):
        value = manifest.get(field_name)
        if not isinstance(value, str) or not value:
            errors.append(f"{field_name} must be a non-empty string")
    if not isinstance(manifest.get("profile_description"), str):
        errors.append("profile_description must be a string")
    if not isinstance(manifest.get("mod_info"), dict):
        errors.append("mod_info must be an object")
    outputs = manifest.get("outputs")
    if not isinstance(outputs, list):
        errors.append("outputs must be a list")
    else:
        for index, entry in enumerate(outputs):
            if not isinstance(entry, dict):
                errors.append(f"outputs[{index}] must be an object")
                continue
            if set(entry) != _STATIC_OUTPUT_ENTRY_KEYS:
                errors.append(
                    f"outputs[{index}] keys are not exact: "
                    f"missing={sorted(_STATIC_OUTPUT_ENTRY_KEYS-set(entry))!r} "
                    f"extra={sorted(set(entry)-_STATIC_OUTPUT_ENTRY_KEYS)!r}"
                )
            relative = entry.get("relative_path")
            if not isinstance(relative, str) or not relative:
                errors.append(
                    f"outputs[{index}].relative_path must be a non-empty string"
                )
            category = entry.get("category")
            if not isinstance(category, str) or not category:
                errors.append(
                    f"outputs[{index}].category must be a non-empty string"
                )
            size = entry.get("size")
            if type(size) is not int or size < 0:
                errors.append(
                    f"outputs[{index}].size must be a non-negative integer"
                )
            digest = entry.get("sha256")
            if (
                not isinstance(digest, str)
                or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            ):
                errors.append(f"outputs[{index}].sha256 must be lowercase SHA-256")
            width = entry.get("width")
            height = entry.get("height")
            geometry_valid = (
                (width is None and height is None)
                or (
                    type(width) is int
                    and width > 0
                    and type(height) is int
                    and height > 0
                )
            )
            if not geometry_valid:
                errors.append(
                    f"outputs[{index}].width/height must be null or positive integers"
                )
            if (
                isinstance(relative, str)
                and PurePosixPath(relative).suffix.casefold() == ".png"
                and not (
                    type(width) is int
                    and width > 0
                    and type(height) is int
                    and height > 0
                )
            ):
                errors.append(
                    f"outputs[{index}] PNG width/height must be positive integers"
                )
            lost_alpha = entry.get("lost_alpha")
            if lost_alpha is not None and (
                type(lost_alpha) is not int or lost_alpha < 0
            ):
                errors.append(
                    f"outputs[{index}].lost_alpha must be null or non-negative integer"
                )
            source_reference = entry.get("source_reference")
            if source_reference is not None and not isinstance(
                source_reference, str
            ):
                errors.append(
                    f"outputs[{index}].source_reference must be null or a string"
                )
            metadata = entry.get("metadata")
            if metadata is not None and not isinstance(metadata, dict):
                errors.append(
                    f"outputs[{index}].metadata must be null or an object"
                )
    return not errors, json.dumps({"errors": errors}, sort_keys=True)

_WINDOWS_RESERVED_COMPONENTS = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


def _check(name: str, condition: bool, detail: str) -> ValidationCheck:
    return ValidationCheck(name, bool(condition), detail)


class RosterRuntimeContractError(RuntimeError):
    """Raised when a built roster TSV differs from the independent pins."""


def _canonical_roster_field(value: str, label: str) -> str:
    if (
        not value
        or value != value.strip()
        or any(ord(character) < 32 for character in value)
        or unicodedata.normalize("NFC", value) != value
    ):
        raise RosterRuntimeContractError(
            f"Roster contract field is not canonical: {label}"
        )
    return value


def _parse_roster_runtime_contract(path: Path) -> dict[str, Any]:
    """Validate recipe semantics and read the installed-file identities bound by the DLL."""

    try:
        before = path.stat()
        if not path.is_file() or path.is_symlink():
            raise RosterRuntimeContractError(
                f"Roster contract is not a regular non-link file: {path}"
            )
        if before.st_size <= 0 or before.st_size > 32_768:
            raise RosterRuntimeContractError(
                f"Roster contract size is outside the fixed bound: {before.st_size}"
            )
        payload = path.read_bytes()
        after = path.stat()
    except OSError as exc:
        raise RosterRuntimeContractError(
            f"Cannot read roster runtime contract: {path}"
        ) from exc
    if (
        len(payload) != before.st_size
        or (before.st_size, before.st_mtime_ns)
        != (after.st_size, after.st_mtime_ns)
    ):
        raise RosterRuntimeContractError("Roster contract changed while being read")
    manifest_digest = hashlib.sha256(payload).hexdigest()
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise RosterRuntimeContractError(
            "Roster contract is not strict UTF-8"
        ) from exc
    if (
        not text.endswith("\n")
        or "\r" in text
        or "\x00" in text
        or text.startswith("\ufeff")
    ):
        raise RosterRuntimeContractError(
            "Roster contract is not canonical BOM-free LF text"
        )
    lines = text[:-1].split("\n")
    expected_line_count = (
        19 + RUNTIME_ROSTER_ENTRY_COUNT + RUNTIME_ROSTER_HUD_CONTROL_COUNT
    )
    if len(lines) != expected_line_count:
        raise RosterRuntimeContractError(
            f"Roster contract line count is not exact: {len(lines)}"
        )
    metadata_names = (
        "roster_source_sha256", "target_text_relative_path", "target_text_size",
        "target_text_sha256", "target_locale", "target_originals_sha256",
        "hud_xaml_relative_path", "hud_xaml_size", "hud_xaml_sha256",
        "hud_buildings_xaml_relative_path", "hud_buildings_xaml_size",
        "hud_buildings_xaml_sha256", "entries_sha256", "unit_names_sha256",
        "entry_count", "hud_control_count",
    )
    if (lines[0] != "stronghold-europe-unit-roster\t1"
            or lines[17] != "entry\tkind\tlogical_id\tsection\traw_index\tinternal_key\tde\ten"):
        raise RosterRuntimeContractError("Roster contract signature/header is not exact")
    metadata: dict[str, Any] = {}
    for name, line in zip(metadata_names, lines[1:17], strict=True):
        fields = line.split("\t")
        if len(fields) != 2 or fields[0] != name:
            raise RosterRuntimeContractError(f"Malformed roster metadata: {name}")
        value = _canonical_roster_field(fields[1], name)
        if name.endswith("sha256") and re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise RosterRuntimeContractError(f"Invalid roster digest: {name}")
        if name.endswith("_size") or name.endswith("_count"):
            if re.fullmatch(r"[1-9][0-9]{0,18}", value) is None or int(value) > 9223372036854775807:
                raise RosterRuntimeContractError(f"Invalid roster size/count: {name}")
            metadata[name] = int(value)
        else:
            metadata[name] = value
    required_metadata = {
        "target_text_relative_path": RUNTIME_ROSTER_TARGET_TEXT_PATH,
        "hud_xaml_relative_path": RUNTIME_ROSTER_HUD_XAML_PATH,
        "hud_buildings_xaml_relative_path": RUNTIME_ROSTER_HUD_BUILDINGS_XAML_PATH,
        "entries_sha256": RUNTIME_ROSTER_ENTRIES_SHA256,
        "unit_names_sha256": RUNTIME_ROSTER_UNIT_NAMES_SHA256,
        "entry_count": RUNTIME_ROSTER_ENTRY_COUNT,
        "hud_control_count": RUNTIME_ROSTER_HUD_CONTROL_COUNT,
    }
    if (any(metadata[name] != value for name, value in required_metadata.items())
            or re.fullmatch(r"[a-z]{4}", metadata["target_locale"]) is None):
        raise RosterRuntimeContractError("Roster recipe metadata is not exact")

    kind_counts = {kind: 0 for kind in _RUNTIME_ROSTER_KIND_COUNTS}
    internal_keys: set[str] = set()
    route_keys: set[tuple[str, int]] = set()
    entry_digest_rows: list[str] = []
    unit_name_digest_rows: list[str] = []
    for index, line in enumerate(
        lines[18 : 18 + RUNTIME_ROSTER_ENTRY_COUNT]
    ):
        fields = line.split("\t")
        if len(fields) != 8 or fields[0] != "entry":
            raise RosterRuntimeContractError(
                f"Malformed roster entry row at index {index}"
            )
        kind = _canonical_roster_field(fields[1], f"entry[{index}].kind")
        logical_id = _canonical_roster_field(
            fields[2], f"entry[{index}].logical_id"
        )
        section = _canonical_roster_field(fields[3], f"entry[{index}].section")
        raw_text = _canonical_roster_field(
            fields[4], f"entry[{index}].raw_index"
        )
        internal_key = _canonical_roster_field(
            fields[5], f"entry[{index}].internal_key"
        )
        _canonical_roster_field(fields[6], f"entry[{index}].de")
        _canonical_roster_field(fields[7], f"entry[{index}].en")
        if re.fullmatch(r"[a-z][a-z0-9_]*", logical_id) is None:
            raise RosterRuntimeContractError(
                f"Roster logical ID is not canonical at index {index}"
            )
        if re.fullmatch(r"(?:0|[1-9][0-9]{0,3})", raw_text) is None:
            raise RosterRuntimeContractError(
                f"Roster raw index is not canonical at index {index}"
            )
        raw_index = int(raw_text)
        expected_section = _RUNTIME_ROSTER_KIND_SECTIONS.get(kind)
        expected_key = f"{section}_{raw_index + 1:03d}"
        if (
            expected_section != section
            or re.fullmatch(r"[A-Z0-9_]+_[0-9]{3}", internal_key) is None
            or internal_key != expected_key
            or internal_key in internal_keys
            or (section, raw_index) in route_keys
        ):
            raise RosterRuntimeContractError(
                f"Roster route/key is not exact at entry {index}"
            )
        internal_keys.add(internal_key)
        route_keys.add((section, raw_index))
        kind_counts[kind] += 1
        entry_digest_rows.append("\t".join(fields[1:]) + "\n")
        if kind == "unit_name":
            unit_name_digest_rows.append(
                f"{raw_index}\tTEXT_CHIMP_NAMES_{raw_index:03d}"
                f"\t{fields[6]}\t{fields[7]}\n"
            )
    if kind_counts != _RUNTIME_ROSTER_KIND_COUNTS:
        raise RosterRuntimeContractError(
            f"Roster kind counts are not exact: {kind_counts}"
        )
    if internal_keys & _RUNTIME_ROSTER_FORBIDDEN_KEYS:
        raise RosterRuntimeContractError("Roster contract touches a negative key")
    actual_entries_digest = hashlib.sha256(
        "".join(entry_digest_rows).encode("utf-8")
    ).hexdigest()
    actual_unit_names_digest = hashlib.sha256(
        "".join(unit_name_digest_rows).encode("utf-8")
    ).hexdigest()
    if (
        actual_entries_digest != RUNTIME_ROSTER_ENTRIES_SHA256
        or actual_unit_names_digest != RUNTIME_ROSTER_UNIT_NAMES_SHA256
    ):
        raise RosterRuntimeContractError(
            "Roster entry/name semantic digest is not exact"
        )

    hud_header_index = 18 + RUNTIME_ROSTER_ENTRY_COUNT
    if lines[hud_header_index] != "hud\tlogical_id\tcontrol\tinternal_key":
        raise RosterRuntimeContractError("Roster HUD header is not exact")
    actual_hud: list[tuple[str, str, str]] = []
    for index, line in enumerate(lines[hud_header_index + 1 :]):
        fields = line.split("\t")
        if len(fields) != 4 or fields[0] != "hud":
            raise RosterRuntimeContractError(
                f"Malformed roster HUD row at index {index}"
            )
        logical_id, control, internal_key = (
            _canonical_roster_field(fields[1], f"hud[{index}].logical_id"),
            _canonical_roster_field(fields[2], f"hud[{index}].control"),
            _canonical_roster_field(fields[3], f"hud[{index}].internal_key"),
        )
        if (
            re.fullmatch(r"Button[A-Za-z0-9]+", control) is None
            or internal_key not in internal_keys
        ):
            raise RosterRuntimeContractError(
                f"Roster HUD route is not exact at index {index}"
            )
        actual_hud.append((logical_id, control, internal_key))
    if tuple(actual_hud) != _RUNTIME_ROSTER_HUD_BINDINGS:
        raise RosterRuntimeContractError(
            "Roster HUD control order/bindings are not the pinned set"
        )

    return {**metadata, "manifest_sha256": manifest_digest}


def _runtime_roster_metadata_matches(
    metadata: object,
    parsed: dict[str, Any] | None,
) -> bool:
    return (
        isinstance(metadata, dict)
        and set(metadata) == _RUNTIME_ROSTER_METADATA_KEYS
        and parsed is not None
        and metadata
        == {
            "kind": RUNTIME_ROSTER_CONTRACT_KIND,
            "plugin_id": RUNTIME_PLUGIN_ID,
            "manifest_sha256": parsed["manifest_sha256"],
            "roster_source_sha256": parsed["roster_source_sha256"],
            "entries_sha256": parsed["entries_sha256"],
            "target_originals_sha256": parsed["target_originals_sha256"],
            "target_text_sha256": parsed["target_text_sha256"],
            "target_text_size": parsed["target_text_size"],
            "hud_xaml_sha256": parsed["hud_xaml_sha256"],
            "hud_xaml_size": parsed["hud_xaml_size"],
            "hud_buildings_xaml_sha256": parsed[
                "hud_buildings_xaml_sha256"
            ],
            "hud_buildings_xaml_size": parsed[
                "hud_buildings_xaml_size"
            ],
            "entry_count": parsed["entry_count"],
            "hud_control_count": parsed["hud_control_count"],
        }
    )


def _dock_placement_rules_metadata_ok(
    rules: object,
    dock_placement: object,
) -> bool:
    """Mirror of runtime_build._validate_dock_placement_rules for manifests.

    None means the dock lane is a pure measurement; a dict means the lane
    enforces the water rule and writes cost/health, which additionally
    requires the lane selection itself to be on.  Rejects instead of
    ignoring: a manifest that smuggles rule values past this check would
    disguise a writing build as a measuring one.
    """

    if rules is None:
        return True
    if not isinstance(rules, dict) or set(rules) != {
        "wood_cost",
        "gold_cost",
        "health",
    }:
        return False
    for key in ("wood_cost", "gold_cost"):
        value = rules.get(key)
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not 0 <= value <= 1000
        ):
            return False
    health = rules.get("health")
    if (
        isinstance(health, bool)
        or not isinstance(health, int)
        or not 1 <= health <= 100000
    ):
        return False
    return dock_placement is True


def _diplomacy_rules_metadata_ok(
    rules: object,
    diplomacy: object,
) -> bool:
    if diplomacy is False:
        return rules is None
    return (
        diplomacy is True
        and isinstance(rules, dict)
        and rules == _DIPLOMACY_RULES_V1
        and all(
            isinstance(value, int) and not isinstance(value, bool)
            for value in rules.values()
        )
    )


def _runtime_streaming_metadata_ok(metadata: Mapping[str, object]) -> bool:
    lanes = (
        ("asset_stream_enabled", "asset_stream_index_sha256"),
        ("ui_texture_streaming_enabled", "ui_texture_manifest_sha256"),
        ("pcm_streaming_enabled", "pcm_stream_manifest_sha256"),
    )
    for enabled_key, digest_key in lanes:
        enabled = metadata.get(enabled_key)
        digest = metadata.get(digest_key)
        if type(enabled) is not bool or not isinstance(digest, str):
            return False
        if enabled != (re.fullmatch(r"[0-9a-f]{64}", digest) is not None):
            return False
    if metadata.get("asset_stream_enabled") is not True and (
        metadata.get("ui_texture_streaming_enabled") is True
        or metadata.get("pcm_streaming_enabled") is True
    ):
        return False
    return True


def _runtime_fortification_selection_metadata_ok(
    metadata: Mapping[str, object],
) -> bool:
    enabled = metadata.get("fortifications")
    digest = metadata.get("fortification_catalog_sha256")
    if type(enabled) is not bool or not isinstance(digest, str):
        return False
    return enabled == (re.fullmatch(r"[0-9a-f]{64}", digest) is not None)


def _runtime_fortification_contract_expected(
) -> tuple[bytes | None, dict[str, object] | None, str]:
    """Load the authored catalogue only when it still matches every v1 pin."""

    source_path = (
        Path(__file__).resolve().parents[2] / FORTIFICATION_CONTRACT_SOURCE
    )
    try:
        contract = load_fortification_contract(source_path)
        payload = contract.canonical_tsv_bytes()
    except (FortificationContractError, OSError, ValueError) as exc:
        return None, None, str(exc)

    payload_sha256 = hashlib.sha256(payload).hexdigest()
    pins_ok = (
        contract.source_size_bytes == _FORTIFICATION_V1_SOURCE_SIZE
        and contract.source_sha256 == _FORTIFICATION_V1_SOURCE_SHA256
        and len(payload) == _FORTIFICATION_V1_TSV_SIZE
        and payload_sha256 == _FORTIFICATION_V1_TSV_SHA256
    )
    if not pins_ok:
        return (
            None,
            None,
            "fortification v1 source/catalogue differs from the pinned identity "
            f"source_size={contract.source_size_bytes} "
            f"source_sha256={contract.source_sha256} "
            f"tsv_size={len(payload)} tsv_sha256={payload_sha256}",
        )

    metadata: dict[str, object] = {
        "kind": RUNTIME_FORTIFICATION_CONTRACT_KIND,
        "plugin_id": RUNTIME_PLUGIN_ID,
        "schema": contract.schema,
        "recipe_version": contract.recipe_version,
        "variant_count": contract.variant_count,
        "record_count": contract.record_count,
        "source_size_bytes": contract.source_size_bytes,
        "source_sha256": contract.source_sha256,
        "catalog_tsv_size": len(payload),
        "catalog_tsv_sha256": payload_sha256,
    }
    return (
        payload,
        metadata,
        f"records={contract.record_count} size={len(payload)} "
        f"sha256={payload_sha256}",
    )


def _runtime_fortification_metadata_matches(
    metadata: object,
    expected: dict[str, object] | None,
) -> bool:
    return (
        isinstance(metadata, dict)
        and set(metadata) == _RUNTIME_FORTIFICATION_METADATA_KEYS
        and expected is not None
        and metadata == expected
    )


def _runtime_prerequisite_mvids_valid(value: object) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == set(RUNTIME_PREREQUISITE_MVIDS)
        and all(isinstance(mvid, str) and re.fullmatch(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", mvid
        ) is not None for mvid in value.values())
    )


def _runtime_assembly_attestation_expected(
    *,
    manifest_sha256: str | None,
    source_build_id: str,
    target_build_id: str,
    roster_enabled: bool,
    prerequisite_mvids: dict[str, str] | None = None,
    roster_contract: dict[str, Any] | None = None,
    runtime_source_sha256: str | None,
    worker_militia_enabled: bool = False,
    fortifications_enabled: bool = False,
    fortification_catalog_sha256: str = "",
    asset_stream_enabled: bool = False,
    asset_stream_index_sha256: str = "",
    ui_texture_streaming_enabled: bool = False,
    ui_texture_manifest_sha256: str = "",
    pcm_streaming_enabled: bool = False,
    pcm_stream_manifest_sha256: str = "",
) -> dict[str, str | None]:
    return {
        "StrongholdEurope.PluginId": RUNTIME_PLUGIN_ID,
        "StrongholdEurope.ManifestSha256": manifest_sha256,
        "StrongholdEurope.SourceBuildId": source_build_id,
        "StrongholdEurope.TargetBuildId": target_build_id,
        "StrongholdEurope.RuntimePrerequisiteConfigId": (
            "local-shcde-2.80-shcdese-2.11-net481-win-x64"
        ),
        "StrongholdEurope.RuntimeSourceSetSha256": runtime_source_sha256,
        "StrongholdEurope.UnitRosterEnabled": str(roster_enabled).lower(),
        "StrongholdEurope.UnitRosterManifestSha256": (
            (roster_contract or {}).get("manifest_sha256", RUNTIME_ROSTER_MANIFEST_SHA256) if roster_enabled else ""
        ),
        "StrongholdEurope.UnitRosterSourceSha256": (
            (roster_contract or {}).get("roster_source_sha256", RUNTIME_ROSTER_SOURCE_SHA256) if roster_enabled else ""
        ),
        "StrongholdEurope.UnitRosterEntriesSha256": (
            (roster_contract or {}).get("entries_sha256", RUNTIME_ROSTER_ENTRIES_SHA256) if roster_enabled else ""
        ),
        "StrongholdEurope.UnitRosterOriginalsSha256": (
            (roster_contract or {}).get("target_originals_sha256", RUNTIME_ROSTER_ORIGINALS_SHA256) if roster_enabled else ""
        ),
        "StrongholdEurope.UnitRosterTargetTextSha256": (
            (roster_contract or {}).get("target_text_sha256", RUNTIME_ROSTER_TARGET_TEXT_SHA256) if roster_enabled else ""
        ),
        "StrongholdEurope.UnitRosterHudXamlSha256": (
            (roster_contract or {}).get("hud_xaml_sha256", RUNTIME_ROSTER_HUD_XAML_SHA256) if roster_enabled else ""
        ),
        "StrongholdEurope.UnitRosterHudBuildingsXamlSha256": (
            (roster_contract or {}).get("hud_buildings_xaml_sha256", RUNTIME_ROSTER_HUD_BUILDINGS_XAML_SHA256)
            if roster_enabled
            else ""
        ),
        "StrongholdEurope.WorkerMilitiaEnabled": str(
            worker_militia_enabled
        ).lower(),
        "StrongholdEurope.FortificationsEnabled": str(
            fortifications_enabled
        ).lower(),
        "StrongholdEurope.FortificationCatalogSha256": (
            fortification_catalog_sha256
        ),
        "StrongholdEurope.AssetStreamEnabled": str(
            asset_stream_enabled
        ).lower(),
        "StrongholdEurope.AssetStreamIndexSha256": asset_stream_index_sha256,
        "StrongholdEurope.UiTextureStreamingEnabled": str(
            ui_texture_streaming_enabled
        ).lower(),
        "StrongholdEurope.UiTextureManifestSha256": ui_texture_manifest_sha256,
        "StrongholdEurope.PcmStreamingEnabled": str(
            pcm_streaming_enabled
        ).lower(),
        "StrongholdEurope.PcmStreamManifestSha256": pcm_stream_manifest_sha256,
        "StrongholdEurope.TargetFramework": "net481",
        **{
            "StrongholdEurope.PrerequisiteMvid." + dependency_id: mvid
            for dependency_id, mvid in (RUNTIME_PREREQUISITE_MVIDS if prerequisite_mvids is None else prerequisite_mvids).items()
        },
    }


def _runtime_source_set_identity() -> tuple[str | None, str]:
    project_root = Path(__file__).resolve().parents[2]
    try:
        digest = runtime_source_set_sha256(project_root)
    except (OSError, RuntimeBuildError, ValueError) as exc:
        return None, str(exc)
    return digest, digest


def _portable_manifest_path(value: object) -> bool:
    if not isinstance(value, str) or not value or "\\" in value:
        return False
    pure = PurePosixPath(value)
    if (
        pure.is_absolute()
        or not pure.parts
        or pure.as_posix() != value
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        return False
    return all(
        not component.endswith((" ", "."))
        and not any(character in component for character in '<>:"|?*')
        and not any(ord(character) < 32 for character in component)
        and component.split(".", 1)[0].upper()
        not in _WINDOWS_RESERVED_COMPONENTS
        for component in pure.parts
    )


def _locale_validation_checks(
    root: Path,
    declared: dict[str, dict[str, Any]],
    actual: set[str],
) -> list[ValidationCheck]:
    expected = set(ROSTER_LOCALE_FILES)
    declared_locale_paths = {
        relative
        for relative, entry in declared.items()
        if relative.casefold().startswith("locales/")
        or entry.get("category") == "locale_override"
    }
    actual_locale_paths = {
        relative
        for relative in actual
        if relative.casefold().startswith("locales/")
    }
    if not declared_locale_paths and not actual_locale_paths:
        return []

    checks = [
        _check(
            "locale.exact_pair",
            declared_locale_paths == expected and actual_locale_paths == expected,
            f"declared={sorted(declared_locale_paths)} actual={sorted(actual_locale_paths)}",
        )
    ]
    overlays: dict[str, LocaleOverlay] = {}
    for relative, contract in ROSTER_LOCALE_FILES.items():
        entry = declared.get(relative)
        path = root.joinpath(*PurePosixPath(relative).parts)
        entry_metadata = (
            entry.get("metadata")
            if isinstance(entry, dict) and isinstance(entry.get("metadata"), dict)
            else {}
        )
        manifest_contract_ok = (
            isinstance(entry, dict)
            and entry.get("category") == "locale_override"
            and entry.get("source_reference") == contract["source_reference"]
            and entry.get("sha256") == contract["sha256"]
        )
        checks.append(
            _check(
                f"locale.manifest_contract.{contract['locale']}",
                manifest_contract_ok,
                relative,
            )
        )
        overlay: LocaleOverlay | None = None
        parse_detail = relative
        if path.is_file():
            try:
                overlay = parse_locale_overlay(path.read_bytes(), contract["locale"])
                overlays[contract["locale"]] = overlay
                parse_detail = f"overrides={len(overlay.entries)}"
            except (OSError, LocaleOverlayError) as exc:
                parse_detail = str(exc)
        checks.append(
            _check(
                f"locale.canonical.{contract['locale']}",
                overlay is not None,
                parse_detail,
            )
        )
        # Cross-locale roster_text_sha256 is checked below once both files parse.
        checks.append(
            _check(
                f"locale.metadata_shape.{contract['locale']}",
                isinstance(entry_metadata, dict)
                and set(entry_metadata)
                == {
                    "kind",
                    "locale",
                    "section",
                    "section_number",
                    "override_count",
                    "keys_sha256",
                    "values_sha256",
                    "roster_text_sha256",
                },
                json.dumps(entry_metadata, sort_keys=True),
            )
        )

    roster_digest: str | None = None
    if set(overlays) == {"de-DE", "en-US"}:
        try:
            roster_digest = roster_text_sha256(
                overlays["de-DE"], overlays["en-US"]
            )
        except LocaleOverlayError:
            roster_digest = None
    checks.append(
        _check(
            "locale.roster_pair_digest",
            roster_digest is not None,
            roster_digest or "unavailable",
        )
    )
    for relative, contract in ROSTER_LOCALE_FILES.items():
        entry = declared.get(relative)
        metadata = (
            entry.get("metadata")
            if isinstance(entry, dict) and isinstance(entry.get("metadata"), dict)
            else {}
        )
        overlay = overlays.get(contract["locale"])
        expected_metadata = (
            locale_manifest_metadata(overlay, roster_digest)
            if overlay is not None and roster_digest is not None
            else None
        )
        checks.append(
            _check(
                f"locale.metadata_digest.{contract['locale']}",
                expected_metadata is not None and metadata == expected_metadata,
                json.dumps(metadata, sort_keys=True),
            )
        )
    return checks


def _power_of_two(value: int) -> bool:
    return value > 0 and value & (value - 1) == 0


def _pe_clr_header(path: Path) -> tuple[bool, str]:
    """Check PE bounds and the CLR data directory without executing the DLL."""

    try:
        data = path.read_bytes()
        if len(data) < 0x40 or data[:2] != b"MZ":
            return False, "missing MZ header"
        pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
        if pe_offset + 24 > len(data) or data[pe_offset : pe_offset + 4] != b"PE\0\0":
            return False, "missing PE signature"
        section_count = struct.unpack_from("<H", data, pe_offset + 6)[0]
        optional_size = struct.unpack_from("<H", data, pe_offset + 20)[0]
        optional = pe_offset + 24
        if optional + optional_size > len(data):
            return False, "optional header exceeds file"
        magic = struct.unpack_from("<H", data, optional)[0]
        if magic == 0x10B:
            directory_count_offset = optional + 92
            directories = optional + 96
        elif magic == 0x20B:
            directory_count_offset = optional + 108
            directories = optional + 112
        else:
            return False, f"unsupported PE optional-header magic 0x{magic:04x}"
        directory_count = struct.unpack_from("<I", data, directory_count_offset)[0]
        if directory_count <= 14 or directories + 15 * 8 > optional + optional_size:
            return False, "CLR data directory is absent"
        cli_rva, cli_size = struct.unpack_from("<II", data, directories + 14 * 8)
        if cli_rva == 0 or cli_size < 0x48:
            return False, "CLR header is absent/short"

        section_table = optional + optional_size
        sections: list[tuple[int, int, int, int]] = []
        for index in range(section_count):
            offset = section_table + index * 40
            if offset + 40 > len(data):
                return False, "section table exceeds file"
            virtual_size, virtual_address, raw_size, raw_offset = struct.unpack_from(
                "<IIII", data, offset + 8
            )
            sections.append((virtual_address, virtual_size, raw_offset, raw_size))

        def rva_offset(rva: int, required: int) -> int | None:
            for virtual_address, virtual_size, raw_offset, raw_size in sections:
                span = max(virtual_size, raw_size)
                if virtual_address <= rva < virtual_address + span:
                    delta = rva - virtual_address
                    if delta + required <= raw_size and raw_offset + delta + required <= len(data):
                        return raw_offset + delta
            return None

        cli_offset = rva_offset(cli_rva, 16)
        if cli_offset is None:
            return False, "CLR header RVA is outside raw sections"
        metadata_rva, metadata_size = struct.unpack_from("<II", data, cli_offset + 8)
        if metadata_rva == 0 or metadata_size < 20:
            return False, "CLR metadata directory is absent/short"
        metadata_offset = rva_offset(metadata_rva, min(metadata_size, 20))
        if metadata_offset is None or data[metadata_offset : metadata_offset + 4] != b"BSJB":
            return False, "CLR metadata root signature is missing"
        return True, f"PE/CLR metadata size={metadata_size}"
    except (OSError, OverflowError, struct.error, ValueError) as exc:
        return False, f"PE/CLR parse failed: {exc}"


def _managed_assembly_identity(path: Path) -> tuple[str, str] | None:
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if powershell is None:
        return None
    environment = os.environ.copy()
    environment["SEDE_ASSEMBLY_PATH"] = str(path)
    script = (
        "$identity=[Reflection.AssemblyName]::GetAssemblyName($env:SEDE_ASSEMBLY_PATH);"
        "[Console]::Out.Write($identity.Name + \"`t\" + $identity.Version.ToString())"
    )
    try:
        completed = subprocess.run(
            [powershell, "-NoProfile", "-NonInteractive", "-Command", script],
            env=environment,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0 or "\t" not in completed.stdout:
        return None
    name, version = completed.stdout.strip().split("\t", 1)
    return name, version


def _managed_assembly_attestation(path: Path) -> dict[str, str] | None:
    """Read only built-in AssemblyMetadata attributes without loading plugin code."""

    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if powershell is None:
        return None
    environment = os.environ.copy()
    environment["SEDE_ASSEMBLY_PATH"] = str(path)
    script = (
        "$assembly=[Reflection.Assembly]::ReflectionOnlyLoadFrom($env:SEDE_ASSEMBLY_PATH);"
        "$assembly.GetCustomAttributesData() | ForEach-Object {"
        "if ($_.AttributeType.FullName -eq 'System.Reflection.AssemblyMetadataAttribute') {"
        "[Console]::Out.WriteLine(([string]$_.ConstructorArguments[0].Value) + \"`t\" + "
        "([string]$_.ConstructorArguments[1].Value))}}"
    )
    try:
        completed = subprocess.run(
            [powershell, "-NoProfile", "-NonInteractive", "-Command", script],
            env=environment,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    output: dict[str, str] = {}
    for line in completed.stdout.splitlines():
        if "\t" not in line:
            continue
        key, value = line.split("\t", 1)
        if not key or key in output:
            return None
        output[key] = value
    return output


def _atlas_validation_checks(
    root: Path,
    declared: dict[str, dict[str, Any]],
    image_sizes: dict[str, tuple[int, int]],
) -> list[ValidationCheck]:
    checks: list[ValidationCheck] = []
    atlas_namespace_paths: list[str] = []
    atlas_namespace_errors: list[str] = []
    atlas_groups: dict[str, str] = {}
    atlas_components: dict[str, set[str]] = {}
    for relative in declared:
        parts = relative.split("/")
        if len(parts) < 2 or [part.casefold() for part in parts[:2]] != [
            "override",
            "atlas",
        ]:
            continue
        atlas_namespace_paths.append(relative)
        if len(parts) != 4 or parts[:2] != ["Override", "Atlas"] or not parts[2]:
            atlas_namespace_errors.append(
                f"noncanonical/nested atlas path: {relative}"
            )
            continue
        group = parts[2]
        group_key = group.casefold()
        prior_group = atlas_groups.setdefault(group_key, group)
        if prior_group != group:
            atlas_namespace_errors.append(
                f"case-colliding atlas group: {prior_group!r}/{group!r}"
            )
        component = parts[3]
        if component not in {"atlas.json", "atlas.png", "atlas_m.png"}:
            atlas_namespace_errors.append(
                f"unexpected atlas component: {relative}"
            )
        atlas_components.setdefault(group_key, set()).add(component)
    for group_key, components in atlas_components.items():
        if not {"atlas.json", "atlas.png"} <= components:
            atlas_namespace_errors.append(
                f"orphan atlas group {atlas_groups[group_key]!r}: "
                f"components={sorted(components)!r}"
            )
    checks.append(
        _check(
            "atlas.namespace_shape",
            not atlas_namespace_errors,
            json.dumps(
                {
                    "paths": sorted(atlas_namespace_paths),
                    "errors": atlas_namespace_errors,
                },
                sort_keys=True,
            ),
        )
    )
    atlas_json_paths = sorted(
        relative
        for relative in atlas_namespace_paths
        if len(relative.split("/")) == 4
        and relative.split("/")[-1].casefold() == "atlas.json"
    )
    source_texture_group_counts: dict[str, int] = {}
    for atlas_json_path in atlas_json_paths:
        candidate = declared[atlas_json_path].get("metadata")
        if not isinstance(candidate, dict):
            continue
        source_texture = candidate.get("source_texture")
        if isinstance(source_texture, str) and source_texture:
            source_texture_group_counts[source_texture] = (
                source_texture_group_counts.get(source_texture, 0) + 1
            )
    for relative in atlas_json_paths:
        parts = relative.split("/")
        group = parts[2] if len(parts) == 4 else ""
        label = group or relative
        checks.append(
            _check(
                f"atlas.path.{label}",
                len(parts) == 4 and parts[:2] == ["Override", "Atlas"],
                relative,
            )
        )
        entry_metadata = declared[relative].get("metadata")
        metadata = entry_metadata if isinstance(entry_metadata, dict) else {}
        shared_contract = SHARED_GM_ATLAS_139_CONTRACTS.get(group)
        shared_selected = (
            shared_contract is not None
            and metadata.get("kind") == SHARED_GM_ATLAS_KIND
        )
        loader_entry = LOADER_139_GROUPS.get(group)
        if loader_entry is None and shared_selected:
            loader_entry = (False, "forbidden", True)
        checks.append(
            _check(
                f"atlas.loader_group.{label}",
                loader_entry is not None,
                group,
            )
        )
        if loader_entry is None:
            continue
        dash_format, mask_policy, material_compatible = loader_entry
        atlas_relative = f"Override/Atlas/{group}/atlas.png"
        mask_relative = f"Override/Atlas/{group}/atlas_m.png"
        checks.append(
            _check(
                f"atlas.texture_exists.{label}",
                atlas_relative in declared and atlas_relative in image_sizes,
                atlas_relative,
            )
        )
        mask_expected = mask_policy == "required"
        checks.append(
            _check(
                f"atlas.mask_policy.{label}",
                (mask_relative in declared) == mask_expected,
                f"policy={mask_policy} present={mask_relative in declared}",
            )
        )
        if atlas_relative not in image_sizes:
            continue
        atlas_size = image_sizes[atlas_relative]
        checks.append(
            _check(
                f"atlas.power_of_two.{label}",
                all(_power_of_two(value) and value <= 8192 for value in atlas_size),
                str(atlas_size),
            )
        )
        if mask_expected and mask_relative in image_sizes:
            checks.append(
                _check(
                    f"atlas.mask_geometry.{label}",
                    image_sizes[mask_relative] == atlas_size,
                    f"atlas={atlas_size} mask={image_sizes[mask_relative]}",
                )
            )

        checks.append(
            _check(
                f"atlas.manifest_metadata.{label}",
                metadata.get("kind")
                == (
                    SHARED_GM_ATLAS_KIND
                    if shared_selected
                    else "shcdese_gm_atlas_1_39"
                )
                and metadata.get("gm_file_name") == group
                and metadata.get("dash_format") is dash_format
                and metadata.get("mask_policy") == mask_policy,
                json.dumps(metadata, sort_keys=True),
            )
        )
        source_texture = metadata.get("source_texture")
        shared_count = metadata.get("shared_source_texture_group_count")
        if source_texture is None and shared_count is None:
            # Compatibility for already-built development slices created
            # before batch instrumentation was introduced.
            shared_batch_ok = True
            shared_batch_detail = "legacy manifest: batch instrumentation absent"
        else:
            expected_shared_count = source_texture_group_counts.get(
                str(source_texture), 0
            )
            shared_batch_ok = (
                isinstance(source_texture, str)
                and bool(source_texture)
                and isinstance(shared_count, int)
                and not isinstance(shared_count, bool)
                and shared_count == expected_shared_count
            )
            shared_batch_detail = (
                f"source={source_texture} declared={shared_count} "
                f"manifest_groups={expected_shared_count}"
            )
        checks.append(
            _check(
                f"atlas.shared_source_batch.{label}",
                shared_batch_ok,
                shared_batch_detail,
            )
        )

        data, atlas_json_detail = _read_json_object(root / relative)
        checks.append(
            _check(
                f"atlas.json_object.{label}",
                data is not None,
                atlas_json_detail,
            )
        )
        if data is None:
            continue
        frames = data.get("frames")
        if not isinstance(frames, list):
            checks.append(_check(f"atlas.frames.{label}", False, "frames is not a list"))
            continue
        names: list[str] = []
        slots: list[tuple[int, bool]] = []
        rects: list[tuple[int, int, int, int, str]] = []
        frame_ok = True
        for frame in frames:
            if not isinstance(frame, dict):
                frame_ok = False
                continue
            raw_name = frame.get("name")
            name = raw_name if isinstance(raw_name, str) else ""
            parsed = parse_loader_frame_name(name, group, dash_format)
            raw_rect = frame.get("rect")
            rect = raw_rect if isinstance(raw_rect, dict) else {}
            values = [rect.get(field) for field in ("x", "y", "w", "h")]
            integral = all(
                not isinstance(value, bool) and isinstance(value, int)
                for value in values
            )
            if parsed is None or not integral:
                frame_ok = False
                continue
            x, y, width, height = values
            inside = (
                x >= 0
                and y >= 0
                and width > 0
                and height > 0
                and x + width <= atlas_size[0]
                and y + height <= atlas_size[1]
            )
            raw_pivot = frame.get("pivot")
            pivot = raw_pivot if isinstance(raw_pivot, dict) else {}
            try:
                finite_meta = (
                    isinstance(raw_name, str)
                    and isinstance(raw_rect, dict)
                    and isinstance(raw_pivot, dict)
                    and isfinite(float(pivot.get("x")))
                    and isfinite(float(pivot.get("y")))
                    and isfinite(float(frame.get("pixelsPerUnit", data.get("pixelsPerUnit"))))
                    and float(frame.get("pixelsPerUnit", data.get("pixelsPerUnit"))) > 0
                )
            except (TypeError, ValueError):
                finite_meta = False
            frame_ok = frame_ok and inside and finite_meta
            names.append(name)
            slots.append((parsed.index, parsed.is_alt))
            rects.append((x, y, width, height, name))

        checks.append(
            _check(
                f"atlas.frame_schema.{label}",
                frame_ok and len(names) == len(frames),
                f"valid={len(names)} total={len(frames)}",
            )
        )
        checks.append(
            _check(
                f"atlas.unique_names.{label}",
                len(names) == len(set(names)),
                f"names={len(names)} unique={len(set(names))}",
            )
        )
        checks.append(
            _check(
                f"atlas.unique_loader_slots.{label}",
                len(slots) == len(set(slots)),
                f"slots={len(slots)} unique={len(set(slots))}",
            )
        )
        ordered = sorted(
            zip(slots, names, strict=True),
            key=lambda item: (item[0][0], item[0][1], item[1]),
        )
        ordered_names = [name for _, name in ordered]
        digest = hashlib.sha256(
            "".join(name + "\n" for name in ordered_names).encode("utf-8")
        ).hexdigest()
        max_index = max((slot[0] for slot in slots), default=-1)
        main_count = sum(not slot[1] for slot in slots)
        alt_count = len(slots) - main_count
        unique_rects = {(x, y, width, height) for x, y, width, height, _ in rects}
        metadata_matches = (
            metadata.get("frame_count") == len(names)
            and metadata.get("main_count") == main_count
            and metadata.get("alt_count") == alt_count
            and metadata.get("array_size") == max_index + 1
            and metadata.get("names_sha256") == digest
            and metadata.get("unique_region_count") == len(unique_rects)
            and metadata.get("atlas_width") == atlas_size[0]
            and metadata.get("atlas_height") == atlas_size[1]
        )
        checks.append(
            _check(
                f"atlas.manifest_matches_frames.{label}",
                metadata_matches,
                f"frames={len(names)} main={main_count} alt={alt_count} "
                f"array={max_index + 1} regions={len(unique_rects)} digest={digest}",
            )
        )
        roundtrip_metadata = metadata.get("roundtrip")
        roundtrip_ok = (
            isinstance(roundtrip_metadata, dict)
            and roundtrip_metadata.get("verified") is True
            and roundtrip_metadata.get("frames_checked") == len(names)
        )
        checks.append(
            _check(
                f"atlas.build_roundtrip.{label}",
                roundtrip_ok,
                json.dumps(roundtrip_metadata, sort_keys=True),
            )
        )

        shared_policy = metadata.get("shared_gm_atlas_policy")
        shared_ok = not shared_selected and shared_policy is None
        shared_detail = "not a fused shared-GM atlas"
        if shared_selected and isinstance(shared_policy, dict):
            assert shared_contract is not None
            expected_policy_keys = {
                "mode",
                "gm_enum",
                "host_gm_file_name",
                "member_gm_file_names",
                "geometry_policy",
                "proof_algorithm",
                "frame_count",
                "array_size",
                "null_slot_count",
                "combined_names_sha256",
                "output_names_sha256",
                "slot_logical_output_sha256",
                "slot_logical_source_rgba_sha256",
                "member_frame_counts",
                "member_names_sha256",
                "member_source_rgba_sha256",
                "native_rgba_exact",
                "target_canvas_used",
                "target_fallback_count",
                "clipping",
                "resampling",
                "frame_proofs",
                "member_native_proofs",
            }
            expected_spec = SharedGMAtlasSpec(
                mode=SHARED_GM_ATLAS_MODE,
                host_gm_file_name=shared_contract.host_gm_file_name,
                gm_enum=shared_contract.gm_enum,
                dash_format=False,
                mask_policy="forbidden",
                source_texture=shared_contract.source_texture,
                target_texture=shared_contract.target_texture,
                expected_frame_count=shared_contract.expected_frame_count,
                expected_main_count=shared_contract.expected_frame_count,
                expected_alt_count=0,
                expected_max_index=shared_contract.expected_max_index,
                expected_array_size=shared_contract.expected_max_index + 1,
                expected_null_slot_count=(
                    shared_contract.expected_null_slot_count
                ),
                expected_combined_names_sha256=(
                    shared_contract.expected_combined_names_sha256
                ),
                expected_output_names_sha256=(
                    shared_contract.expected_output_names_sha256
                ),
                expected_slot_logical_output_sha256=(
                    shared_contract.expected_slot_logical_output_sha256
                ),
                expected_slot_logical_source_rgba_sha256=(
                    shared_contract.expected_slot_logical_source_rgba_sha256
                ),
                geometry_policy=GEOMETRY_POLICY_NATIVE_REANCHORED,
                proof_algorithm=NATIVE_SOURCE_GEOMETRY_PROOF_ALGORITHM,
                members=tuple(
                    SharedGMAtlasMemberSpec(**member.__dict__)
                    for member in shared_contract.members
                ),
                padding=(
                    metadata["padding"]
                    if type(metadata.get("padding")) is int
                    else 0
                ),
                max_dimension=(
                    metadata["max_dimension"]
                    if type(metadata.get("max_dimension")) is int
                    else 0
                ),
                category=str(metadata.get("category", "")),
            )
            proof_rows = shared_policy.get("frame_proofs")
            shared_proof_ok = isinstance(proof_rows, list)
            shared_proof: dict[str, Any] = {}
            if isinstance(proof_rows, list):
                try:
                    shared_proof = shared_gm_atlas_proof(
                        proof_rows, expected_spec
                    )
                except (GMAtlasError, TypeError, ValueError):
                    shared_proof_ok = False

            member_proofs = shared_policy.get("member_native_proofs")
            member_proofs_ok = isinstance(member_proofs, list)
            member_rows_by_name: dict[str, list[dict[str, Any]]] = {}
            if isinstance(member_proofs, list):
                if len(member_proofs) != len(expected_spec.members):
                    member_proofs_ok = False
                for member, raw_member in zip(
                    expected_spec.members, member_proofs, strict=False
                ):
                    if not isinstance(raw_member, dict):
                        member_proofs_ok = False
                        continue
                    expected_member_keys = {
                        "gm_file_name",
                        "slot_offset",
                        "mode",
                        "proof_algorithm",
                        "frame_count",
                        "geometry_proof_sha256",
                        "origin_proof_sha256",
                        "source_rgba_sha256",
                        "target_origin_count",
                        "source_anchor_max_error_px",
                        "runtime_anchor_max_error_px",
                        "frame_proofs",
                    }
                    native_rows = raw_member.get("frame_proofs")
                    native_proof: dict[str, Any] = {}
                    if isinstance(native_rows, list):
                        try:
                            native_proof = native_source_geometry_proof(
                                native_rows
                            )
                        except (GMAtlasError, TypeError, ValueError):
                            member_proofs_ok = False
                    else:
                        member_proofs_ok = False
                    expected_native = {
                        "frame_count": member.expected_frame_count,
                        "geometry_proof_sha256": (
                            member.expected_geometry_proof_sha256
                        ),
                        "origin_proof_sha256": (
                            member.expected_origin_proof_sha256
                        ),
                        "source_rgba_sha256": (
                            member.expected_source_rgba_sha256
                        ),
                        "target_origin_count": 0,
                        "source_anchor_max_error_px": (
                            member.expected_source_anchor_max_error_px
                        ),
                        "runtime_anchor_max_error_px": (
                            member.expected_runtime_anchor_max_error_px
                        ),
                    }
                    member_proofs_ok = member_proofs_ok and (
                        set(raw_member) == expected_member_keys
                        and raw_member.get("gm_file_name")
                        == member.gm_file_name
                        and raw_member.get("slot_offset") == member.slot_offset
                        and raw_member.get("mode")
                        == GEOMETRY_POLICY_NATIVE_REANCHORED
                        and raw_member.get("proof_algorithm")
                        == NATIVE_SOURCE_GEOMETRY_PROOF_ALGORITHM
                        and native_proof == expected_native
                        and all(
                            raw_member.get(key) == value
                            for key, value in native_proof.items()
                        )
                    )
                    if isinstance(native_rows, list):
                        member_rows_by_name[member.gm_file_name] = native_rows

            serialized_shared_ok = (
                isinstance(proof_rows, list)
                and [row.get("output_name") for row in proof_rows]
                == ordered_names
            )
            descriptor_by_name = {
                str(frame.get("name", "")): frame
                for frame in frames
                if isinstance(frame, dict)
            }
            try:
                with Image.open(root / atlas_relative) as opened:
                    opened.load()
                    atlas_pixels = (
                        opened.copy() if opened.mode == "RGBA" else None
                    )
            except (OSError, UnidentifiedImageError, ValueError):
                atlas_pixels = None
            if atlas_pixels is None:
                serialized_shared_ok = False
            if isinstance(proof_rows, list) and atlas_pixels is not None:
                for row in proof_rows:
                    if not isinstance(row, dict):
                        serialized_shared_ok = False
                        continue
                    descriptor = descriptor_by_name.get(
                        str(row.get("output_name", ""))
                    )
                    rect = (
                        descriptor.get("rect")
                        if isinstance(descriptor, dict)
                        else None
                    )
                    if not isinstance(rect, dict):
                        serialized_shared_ok = False
                        continue
                    try:
                        x = int(rect["x"])
                        y = int(rect["y"])
                        width = int(rect["w"])
                        height = int(rect["h"])
                        top = atlas_pixels.height - y - height
                        crop = atlas_pixels.crop(
                            (x, top, x + width, top + height)
                        )
                        crop_ok = hashlib.sha256(
                            crop.tobytes()
                        ).hexdigest() == row.get("source_rgba_sha256")
                    except (KeyError, TypeError, ValueError):
                        crop_ok = False
                    serialized_shared_ok = serialized_shared_ok and crop_ok

            shared_ok = (
                set(shared_policy) == expected_policy_keys
                and shared_policy.get("mode") == SHARED_GM_ATLAS_MODE
                and shared_policy.get("gm_enum") == shared_contract.gm_enum
                and shared_policy.get("host_gm_file_name") == group
                and shared_policy.get("member_gm_file_names")
                == [member.gm_file_name for member in expected_spec.members]
                and shared_policy.get("geometry_policy")
                == GEOMETRY_POLICY_NATIVE_REANCHORED
                and shared_policy.get("proof_algorithm")
                == NATIVE_SOURCE_GEOMETRY_PROOF_ALGORITHM
                and shared_proof_ok
                and all(
                    shared_policy.get(key) == value
                    for key, value in shared_proof.items()
                )
                and member_proofs_ok
                and serialized_shared_ok
                and shared_policy.get("native_rgba_exact") is True
                and shared_policy.get("target_canvas_used") is False
                and shared_policy.get("target_fallback_count") == 0
                and shared_policy.get("clipping") is False
                and shared_policy.get("resampling") == "none"
                and metadata.get("geometry_policy")
                == GEOMETRY_POLICY_NATIVE_REANCHORED
                and isinstance(roundtrip_metadata, dict)
                and roundtrip_metadata.get("serialized_files") is True
            )
            shared_detail = json.dumps(
                {
                    "proof": shared_proof,
                    "member_proofs": member_proofs_ok,
                    "serialized_frames": serialized_shared_ok,
                },
                sort_keys=True,
            )
        elif shared_selected:
            shared_detail = "required shared_gm_atlas_policy is absent"
        checks.append(
            _check(
                f"atlas.shared_gm_atlas_policy.{label}",
                shared_ok,
                shared_detail,
            )
        )

        derived_policy = metadata.get("derived_frame_policy")
        derived_contract = DERIVED_POLICY_139_CONTRACTS.get(group)
        derived_required = derived_contract is not None
        derived_ok = not derived_required and derived_policy is None
        derived_detail = "not a frozen derived-frame atlas"
        if isinstance(derived_policy, dict):
            expected_policy_keys = {
                "mode",
                "proof_algorithm",
                "frame_count",
                "discarded_mask_alpha",
                "frame_proof_sha256",
                "frame_proofs",
            }
            rows = derived_policy.get("frame_proofs")
            rows_ok = isinstance(rows, list)
            proof_digest = ""
            proof_names: list[str] = []
            discarded_total = 0
            if isinstance(rows, list):
                try:
                    proof_digest = derived_frame_proof_digest(rows)
                except (GMAtlasError, TypeError, ValueError):
                    rows_ok = False
                for row in rows:
                    if not isinstance(row, dict):
                        rows_ok = False
                        continue
                    name = row.get("name")
                    discarded = row.get("discarded_mask_alpha")
                    proof_names.append(name if isinstance(name, str) else "")
                    if type(discarded) is int:
                        discarded_total += discarded
            ordered_name_positions = {
                name: index for index, name in enumerate(ordered_names)
            }
            proof_positions = [
                ordered_name_positions.get(name, -1) for name in proof_names
            ]
            proof_partition_ok = (
                len(proof_names) == len(set(proof_names))
                and all(position >= 0 for position in proof_positions)
                and proof_positions == sorted(proof_positions)
            )
            derived_ok = (
                derived_required
                and set(derived_policy) == expected_policy_keys
                and derived_policy.get("mode") == DERIVED_FRAME_POLICY_MODE
                and derived_policy.get("proof_algorithm")
                == PLACEMENT_PROOF_ALGORITHM
                and rows_ok
                and proof_partition_ok
                and type(derived_policy.get("frame_count")) is int
                and derived_policy.get("frame_count") == len(rows or [])
                and type(derived_policy.get("discarded_mask_alpha")) is int
                and derived_policy.get("discarded_mask_alpha")
                == discarded_total
                and derived_policy.get("frame_proof_sha256") == proof_digest
                and derived_contract is not None
                and derived_policy.get("frame_count")
                == derived_contract.expected_frame_count
                and derived_policy.get("discarded_mask_alpha")
                == derived_contract.expected_discarded_mask_alpha
                and derived_policy.get("frame_proof_sha256")
                == derived_contract.expected_frame_proof_sha256
            )
            derived_detail = json.dumps(
                {
                    "required": derived_required,
                    "rows": len(rows) if isinstance(rows, list) else None,
                    "discarded": discarded_total,
                    "digest": proof_digest,
                },
                sort_keys=True,
            )
        elif derived_required:
            derived_detail = "required derived_frame_policy is absent"
        checks.append(
            _check(
                f"atlas.derived_frame_policy.{label}",
                derived_ok,
                derived_detail,
            )
        )

        descriptor_by_name = {
            str(frame.get("name", "")): frame
            for frame in frames
            if isinstance(frame, dict)
        }
        atlas_pixels: Image.Image | None = None
        try:
            with Image.open(root / atlas_relative) as opened:
                opened.load()
                if opened.mode == "RGBA":
                    atlas_pixels = opened.copy()
        except (OSError, UnidentifiedImageError):
            atlas_pixels = None

        def _serialized_frame_matches(
            row: dict[str, Any],
            width_field: str,
            height_field: str,
            rgba_field: str,
        ) -> bool:
            """Re-verify one proof row against the serialized atlas region."""

            if atlas_pixels is None:
                return False
            descriptor = descriptor_by_name.get(str(row.get("name")))
            if not isinstance(descriptor, dict):
                return False
            rect = descriptor.get("rect")
            pivot = descriptor.get("pivot")
            if not isinstance(rect, dict) or not isinstance(pivot, dict):
                return False
            try:
                x = rect["x"]
                y = rect["y"]
                width = rect["w"]
                height = rect["h"]
                if not (
                    type(x) is int
                    and type(y) is int
                    and type(width) is int
                    and type(height) is int
                    and width == row.get(width_field)
                    and height == row.get(height_field)
                    and float(pivot["x"]) == float(row["output_pivot_x"])
                    and float(pivot["y"]) == float(row["output_pivot_y"])
                    and float(
                        descriptor.get("pixelsPerUnit", data.get("pixelsPerUnit"))
                    )
                    == float(row["output_pixels_per_unit"])
                ):
                    return False
            except (KeyError, TypeError, ValueError):
                return False
            top = atlas_pixels.height - y - height
            crop = atlas_pixels.crop((x, top, x + width, top + height))
            return hashlib.sha256(crop.tobytes()).hexdigest() == row.get(rgba_field)

        # Crusader slots without a European donor are copied byte for byte so
        # ApplySingle keeps the full GM array length.  They are deliberately
        # absent from the conversion proofs, so the geometry validator below
        # has to know which names they cover.
        sparse_keep_policy = metadata.get("sparse_keep_policy")
        declared_keep_count = metadata.get("sparse_keep_frame_count")
        sparse_keep_names: list[str] = []
        sparse_keep_ok = sparse_keep_policy is None and declared_keep_count is None
        sparse_keep_detail = "not a sparse Crusader-keep atlas"
        if isinstance(sparse_keep_policy, dict):
            expected_keep_keys = {
                "mode",
                "proof_algorithm",
                "frame_count",
                "names_sha256",
                "geometry_proof_sha256",
                "target_rgba_sha256",
                "target_rgba_exact",
                "source_pixels_used",
                "clipping",
                "resampling",
                "frame_proofs",
            }
            keep_rows = sparse_keep_policy.get("frame_proofs")
            keep_proof: dict[str, Any] = {}
            keep_proof_ok = isinstance(keep_rows, list)
            if isinstance(keep_rows, list):
                try:
                    keep_proof = sparse_keep_frame_proof(keep_rows)
                except (GMAtlasError, TypeError, ValueError):
                    keep_proof_ok = False
            sparse_keep_names = [
                str(row.get("name", "")) if isinstance(row, dict) else ""
                for row in (keep_rows if isinstance(keep_rows, list) else [])
            ]
            keep_name_set = set(sparse_keep_names)
            keep_frames_ok = (
                len(keep_name_set) == len(sparse_keep_names)
                and keep_name_set <= set(ordered_names)
                and sparse_keep_names
                == [name for name in ordered_names if name in keep_name_set]
            )
            if isinstance(keep_rows, list):
                for row in keep_rows:
                    if not isinstance(row, dict):
                        keep_frames_ok = False
                        continue
                    keep_frames_ok = keep_frames_ok and _serialized_frame_matches(
                        row,
                        "target_width",
                        "target_height",
                        "target_rgba_sha256",
                    )
            else:
                keep_frames_ok = False
            sparse_keep_ok = (
                set(sparse_keep_policy) == expected_keep_keys
                and sparse_keep_policy.get("mode") == SPARSE_KEEP_POLICY_MODE
                and sparse_keep_policy.get("proof_algorithm")
                == SPARSE_KEEP_PROOF_ALGORITHM
                and keep_proof_ok
                and all(
                    sparse_keep_policy.get(key) == value
                    for key, value in keep_proof.items()
                )
                and declared_keep_count == keep_proof.get("frame_count")
                and sparse_keep_policy.get("target_rgba_exact") is True
                and sparse_keep_policy.get("source_pixels_used") is False
                and sparse_keep_policy.get("clipping") is False
                and sparse_keep_policy.get("resampling") == "none"
                and keep_frames_ok
            )
            sparse_keep_detail = json.dumps(
                {
                    "declared": declared_keep_count,
                    "proof": keep_proof,
                    "serialized_frames": keep_frames_ok,
                },
                sort_keys=True,
            )
        elif declared_keep_count is not None:
            sparse_keep_detail = (
                "sparse keep count declared without copy provenance"
            )
        checks.append(
            _check(
                f"atlas.sparse_keep_policy.{label}",
                sparse_keep_ok,
                sparse_keep_detail,
            )
        )
        european_names = [
            name for name in ordered_names if name not in set(sparse_keep_names)
        ]
        review_policy_metadata = metadata.get("review_frame_policy")
        review_renders_native = (
            isinstance(review_policy_metadata, dict)
            and review_policy_metadata.get("mode") == REVIEW_FRAME_POLICY_MODE_V3
            and group in REVIEW_NATIVE_GEOMETRY_139_GROUPS
        )
        if review_renders_native:
            # Eine V3-Gruppe fuehrt ihre Crusader-Kopien in der
            # review_frame_policy, nicht in sparse_keep_frame_count. Der native
            # Beweis deckt deshalb nur die REVIEW_MANUAL-Frames ab, und der
            # Namensvergleich weiter unten muss dieselbe Teilmenge erwarten.
            rows_metadata = review_policy_metadata.get("frame_origins")
            keep_only = {
                str(row.get("name", ""))
                for row in (rows_metadata if isinstance(rows_metadata, list) else [])
                if isinstance(row, dict) and row.get("action") == "KEEP_CRUSADER"
            }
            european_names = [
                name for name in european_names if name not in keep_only
            ]

        native_policy = metadata.get("native_source_geometry_policy")
        required_native = required_native_source_geometry_contract(group)
        # Eine V3-Gruppe steht mit Absicht nicht in der Pflicht-Tabelle - dort
        # zu stehen wuerde die native Geometrie fuer jedes Profil der Gruppe
        # erzwingen und die bestehenden V2-Profile ungueltig machen. Traegt der
        # Atlas aber eine V3-Partition, dann MUSS er auch den nativen Beweis
        # fuehren; deshalb wird die Pflicht hier aus der Partition abgeleitet.
        native_required = required_native is not None or review_renders_native
        expected_native_mode = (
            required_native[0]
            if required_native is not None
            else (
                GEOMETRY_POLICY_NATIVE_AUTHORED_PIVOT
                if review_renders_native
                else None
            )
        )
        native_ok = not native_required and native_policy is None
        native_detail = "not a frozen native-source atlas"
        if isinstance(native_policy, dict):
            native_mode = native_policy.get("mode")
            native_contract = (
                native_source_geometry_contract(group, native_mode)
                if isinstance(native_mode, str)
                else None
            )
            expected_policy_keys = {
                "mode",
                "proof_algorithm",
                "frame_count",
                "geometry_proof_sha256",
                "origin_proof_sha256",
                "source_rgba_sha256",
                "target_origin_count",
                "native_rgba_exact",
                "target_canvas_used",
                "clipping",
                "resampling",
                "frame_proofs",
            }
            if native_mode == GEOMETRY_POLICY_NATIVE_REANCHORED:
                expected_policy_keys.update(
                    {
                        "source_anchor_max_error_px",
                        "runtime_anchor_max_error_px",
                    }
                )
            proof_rows = native_policy.get("frame_proofs")
            proof_ok = isinstance(proof_rows, list)
            proof: dict[str, Any] = {}
            if isinstance(proof_rows, list):
                try:
                    proof = (
                        native_source_authored_pivot_proof(proof_rows)
                        if native_mode
                        == GEOMETRY_POLICY_NATIVE_AUTHORED_PIVOT
                        else native_source_geometry_proof(
                            proof_rows,
                            source_anchor_tolerance_px=(
                                native_contract.source_anchor_tolerance_px
                                if native_contract is not None
                                else 0.0
                            ),
                        )
                    )
                except (GMAtlasError, TypeError, ValueError):
                    proof_ok = False

            proof_names = [
                str(row.get("name", "")) if isinstance(row, dict) else ""
                for row in (proof_rows if isinstance(proof_rows, list) else [])
            ]
            # A sparse group proves only its European frames here; the copied
            # Crusader slots carry their own provenance block above.
            serialized_frames_ok = proof_names == european_names
            if atlas_pixels is None:
                serialized_frames_ok = False
            if isinstance(proof_rows, list):
                for row in proof_rows:
                    if not isinstance(row, dict):
                        serialized_frames_ok = False
                        continue
                    serialized_frames_ok = (
                        serialized_frames_ok
                        and _serialized_frame_matches(
                            row,
                            "source_width",
                            "source_height",
                            "source_rgba_sha256",
                        )
                    )

            expected_proof = {
                "frame_count": native_contract.expected_frame_count,
                "geometry_proof_sha256": (
                    native_contract.expected_geometry_proof_sha256
                ),
                "origin_proof_sha256": native_contract.expected_origin_proof_sha256,
                "source_rgba_sha256": native_contract.expected_source_rgba_sha256,
                "target_origin_count": 0,
            } if native_contract is not None else {}
            if native_mode == GEOMETRY_POLICY_NATIVE_REANCHORED:
                expected_proof.update(
                    {
                        "source_anchor_max_error_px": proof.get(
                            "source_anchor_max_error_px"
                        ),
                        "runtime_anchor_max_error_px": proof.get(
                            "runtime_anchor_max_error_px"
                        ),
                    }
                )
            contract_ok = native_contract is not None and proof == expected_proof
            if (
                contract_ok
                and native_contract.expected_source_anchor_max_error_px
                is not None
            ):
                contract_ok = (
                    proof.get("source_anchor_max_error_px")
                    == native_contract.expected_source_anchor_max_error_px
                )
            proof_metadata_ok = all(
                native_policy.get(key) == value for key, value in proof.items()
            )
            native_ok = (
                native_required
                and expected_native_mode is not None
                and native_mode == expected_native_mode
                and native_contract is not None
                and set(native_policy) == expected_policy_keys
                and native_policy.get("proof_algorithm")
                == (
                    NATIVE_SOURCE_AUTHORED_PIVOT_PROOF_ALGORITHM
                    if native_mode == GEOMETRY_POLICY_NATIVE_AUTHORED_PIVOT
                    else NATIVE_SOURCE_GEOMETRY_PROOF_ALGORITHM
                )
                and metadata.get("geometry_policy") == native_mode
                and proof_ok
                and contract_ok
                and proof_metadata_ok
                and serialized_frames_ok
                and native_policy.get("target_origin_count") == 0
                and native_policy.get("native_rgba_exact") is True
                and native_policy.get("target_canvas_used") is False
                and native_policy.get("clipping") is False
                and native_policy.get("resampling") == "none"
                and isinstance(roundtrip_metadata, dict)
                and roundtrip_metadata.get("serialized_files") is True
            )
            native_detail = json.dumps(
                {
                    "required": native_required,
                    "rows": len(proof_rows)
                    if isinstance(proof_rows, list)
                    else None,
                    "proof": proof,
                    "serialized_frames": serialized_frames_ok,
                },
                sort_keys=True,
            )
        elif native_required:
            native_detail = "required native_source_geometry_policy is absent"
        checks.append(
            _check(
                f"atlas.native_source_geometry_policy.{label}",
                native_ok,
                native_detail,
            )
        )

        source_remap_policy = metadata.get("source_remap_policy")
        source_remap_contract = SOURCE_REMAP_139_CONTRACTS.get(group)
        source_remap_required = source_remap_contract is not None
        source_remap_ok = (
            not source_remap_required and source_remap_policy is None
        )
        source_remap_detail = "not a frozen cross-index source-remap atlas"
        if isinstance(source_remap_policy, dict):
            expected_policy_keys = {
                "mode",
                "proof_algorithm",
                "frame_count",
                "mapping_sha256",
                "proof_sha256",
                "source_rgba_sha256",
                "output_rgba_sha256",
                "visible_blue_pixel_count",
                "source_only",
                "target_fallback_count",
                "exact_canvas",
                "clipping",
                "resampling",
                "frame_proofs",
            }
            proof_rows = source_remap_policy.get("frame_proofs")
            proof_ok = isinstance(proof_rows, list)
            proof: dict[str, Any] = {}
            if isinstance(proof_rows, list):
                try:
                    proof = source_remap_proof(proof_rows)
                except (GMAtlasError, TypeError, ValueError):
                    proof_ok = False

            contract_ok = False
            if source_remap_contract is not None:
                try:
                    reference_proof = source_remap_reference_proof(proof_rows, source_remap_contract)
                except (GMAtlasError, TypeError, ValueError):
                    reference_proof = {}
                expected_contract = (
                    len(source_remap_contract.frames),
                    source_remap_contract.expected_mapping_sha256,
                    source_remap_contract.expected_proof_sha256,
                    source_remap_contract.expected_source_rgba_sha256,
                    source_remap_contract.expected_output_rgba_sha256,
                    source_remap_contract.expected_visible_blue_pixel_count,
                )
                actual_contract = (
                    reference_proof.get("frame_count"),
                    reference_proof.get("mapping_sha256"),
                    reference_proof.get("proof_sha256"),
                    reference_proof.get("source_rgba_sha256"),
                    reference_proof.get("output_rgba_sha256"),
                    reference_proof.get("visible_blue_pixel_count"),
                )
                contract_ok = actual_contract == expected_contract

            serialized_frames_ok = isinstance(proof_rows, list)
            descriptor_by_name = {
                str(frame.get("name", "")): frame
                for frame in frames
                if isinstance(frame, dict)
            }
            atlas_pixels: Image.Image | None = None
            try:
                with Image.open(root / atlas_relative) as opened:
                    opened.load()
                    if opened.mode == "RGBA":
                        atlas_pixels = opened.copy()
            except (OSError, UnidentifiedImageError):
                atlas_pixels = None
            if atlas_pixels is None:
                serialized_frames_ok = False

            contract_frames = (
                source_remap_contract.frames
                if source_remap_contract is not None
                else ()
            )
            if isinstance(proof_rows, list):
                if len(proof_rows) != len(contract_frames):
                    serialized_frames_ok = False
                for row, contract_frame in zip(
                    proof_rows, contract_frames, strict=False
                ):
                    if not isinstance(row, dict):
                        serialized_frames_ok = False
                        continue
                    row_contract_ok = (
                        row.get("target_name") == contract_frame.target_name
                        and row.get("source_name") == contract_frame.source_name
                        # IDs are validated in the actual proof and recorded
                        # there; the source file may renumber identical art.
                        and row.get("source_rgba_sha256")
                        == contract_frame.expected_source_rgba_sha256
                        and row.get("output_rgba_sha256")
                        == contract_frame.expected_output_rgba_sha256
                        and row.get("visible_blue_pixel_count")
                        == contract_frame.expected_visible_blue_pixel_count
                    )
                    serialized_frames_ok = (
                        serialized_frames_ok and row_contract_ok
                    )
                    descriptor = descriptor_by_name.get(
                        str(row.get("target_name", ""))
                    )
                    if (
                        atlas_pixels is None
                        or not isinstance(descriptor, dict)
                    ):
                        serialized_frames_ok = False
                        continue
                    rect = descriptor.get("rect")
                    pivot = descriptor.get("pivot")
                    if not isinstance(rect, dict) or not isinstance(pivot, dict):
                        serialized_frames_ok = False
                        continue
                    try:
                        x = rect["x"]
                        y = rect["y"]
                        width = rect["w"]
                        height = rect["h"]
                        geometry_ok = (
                            type(x) is int
                            and type(y) is int
                            and type(width) is int
                            and type(height) is int
                            and width == row.get("target_width")
                            and height == row.get("target_height")
                            and float(pivot["x"])
                            == float(row["target_pivot_x"])
                            and float(pivot["y"])
                            == float(row["target_pivot_y"])
                            and float(
                                descriptor.get(
                                    "pixelsPerUnit", data.get("pixelsPerUnit")
                                )
                            )
                            == float(row["target_pixels_per_unit"])
                        )
                    except (KeyError, TypeError, ValueError):
                        geometry_ok = False
                    serialized_frames_ok = (
                        serialized_frames_ok and geometry_ok
                    )
                    if not geometry_ok:
                        continue
                    top = atlas_pixels.height - y - height
                    crop = atlas_pixels.crop(
                        (x, top, x + width, top + height)
                    )
                    serialized_frames_ok = serialized_frames_ok and (
                        hashlib.sha256(crop.tobytes()).hexdigest()
                        == row.get("output_rgba_sha256")
                        and visible_blue_pixel_count(crop)
                        == row.get("visible_blue_pixel_count")
                    )

            proof_metadata_ok = all(
                source_remap_policy.get(key) == value
                for key, value in proof.items()
            )
            source_remap_ok = (
                source_remap_required
                and set(source_remap_policy) == expected_policy_keys
                and source_remap_policy.get("mode")
                == SOURCE_REMAP_POLICY_MODE
                and source_remap_policy.get("proof_algorithm")
                == SOURCE_REMAP_PROOF_ALGORITHM
                and proof_ok
                and contract_ok
                and proof_metadata_ok
                and serialized_frames_ok
                and source_remap_policy.get("source_only") is True
                and source_remap_policy.get("target_fallback_count") == 0
                and source_remap_policy.get("exact_canvas") is True
                and source_remap_policy.get("clipping") is False
                and source_remap_policy.get("resampling") == "none"
                and source_remap_policy.get("visible_blue_pixel_count") == 0
                and isinstance(roundtrip_metadata, dict)
                and roundtrip_metadata.get("serialized_files") is True
            )
            source_remap_detail = json.dumps(
                {
                    "required": source_remap_required,
                    "rows": len(proof_rows)
                    if isinstance(proof_rows, list)
                    else None,
                    "proof": proof,
                    "serialized_frames": serialized_frames_ok,
                },
                sort_keys=True,
            )
        elif source_remap_required:
            source_remap_detail = "required source_remap_policy is absent"
        checks.append(
            _check(
                f"atlas.source_remap_policy.{label}",
                source_remap_ok,
                source_remap_detail,
            )
        )

        review_policy = metadata.get("review_frame_policy")
        review_required = group in REVIEW_139_GROUP_TEXTURES
        review_ok = not review_required and review_policy is None
        review_detail = "not a mixed-review atlas"
        if isinstance(review_policy, dict):
            mode = review_policy.get("mode")
            rows = review_policy.get("frame_origins")
            row_names: list[str] = []
            row_origins: list[str] = []
            row_statuses: list[str] = []
            row_actions: list[str] = []
            rows_ok = isinstance(rows, list)
            discarded_total = 0
            if isinstance(rows, list):
                for row in rows:
                    if not isinstance(row, dict):
                        rows_ok = False
                        continue
                    name = row.get("name")
                    origin = row.get("origin")
                    proof_status = row.get("proof_status")
                    action = row.get("action")
                    discarded = row.get("discarded_mask_alpha")
                    if mode == REVIEW_FRAME_POLICY_MODE_V3:
                        # Kein BLOCKED_ALPHA_CLIP: unter V3 gibt es keine
                        # Zielleinwand, an der etwas abgewiesen werden koennte.
                        relation_ok = (action, origin, proof_status) in {
                            (
                                "REVIEW_MANUAL",
                                SOURCE_FRAME_ORIGIN,
                                NATIVE_SOURCE_PROOF_STATUS,
                            ),
                            (
                                "KEEP_CRUSADER",
                                TARGET_FRAME_ORIGIN,
                                KEEP_CRUSADER_PROOF_STATUS,
                            ),
                        }
                    elif mode == REVIEW_FRAME_POLICY_MODE_V2:
                        relation_ok = (action, origin, proof_status) in {
                            (
                                "REVIEW_MANUAL",
                                SOURCE_FRAME_ORIGIN,
                                "AUTO_LOSSLESS_INTEGRAL",
                            ),
                            (
                                "REVIEW_MANUAL",
                                TARGET_FRAME_ORIGIN,
                                "BLOCKED_ALPHA_CLIP",
                            ),
                            (
                                "KEEP_CRUSADER",
                                TARGET_FRAME_ORIGIN,
                                KEEP_CRUSADER_PROOF_STATUS,
                            ),
                        }
                    else:
                        relation_ok = proof_status == {
                            SOURCE_FRAME_ORIGIN: "AUTO_LOSSLESS_INTEGRAL",
                            TARGET_FRAME_ORIGIN: "BLOCKED_ALPHA_CLIP",
                        }.get(origin)
                    row_valid = (
                        isinstance(name, str)
                        and origin in {SOURCE_FRAME_ORIGIN, TARGET_FRAME_ORIGIN}
                        and isinstance(proof_status, str)
                        and relation_ok
                        and isinstance(discarded, int)
                        and not isinstance(discarded, bool)
                        and discarded >= 0
                        and (origin == SOURCE_FRAME_ORIGIN or discarded == 0)
                    )
                    rows_ok = rows_ok and row_valid
                    row_names.append(name if isinstance(name, str) else "")
                    row_origins.append(origin if isinstance(origin, str) else "")
                    row_statuses.append(
                        proof_status if isinstance(proof_status, str) else ""
                    )
                    row_actions.append(action if isinstance(action, str) else "")
                    if isinstance(discarded, int) and not isinstance(discarded, bool):
                        discarded_total += discarded
            source_names = [
                name
                for name, origin in zip(row_names, row_origins, strict=False)
                if origin == SOURCE_FRAME_ORIGIN
            ]
            target_names = [
                name
                for name, origin in zip(row_names, row_origins, strict=False)
                if origin == TARGET_FRAME_ORIGIN
            ]
            source_digest = hashlib.sha256(
                "".join(name + "\n" for name in source_names).encode("utf-8")
            ).hexdigest()
            target_digest = hashlib.sha256(
                "".join(name + "\n" for name in target_names).encode("utf-8")
            ).hexdigest()
            provenance_digest = hashlib.sha256(
                "".join(
                    f"{name}\t{origin}\n"
                    for name, origin in zip(row_names, row_origins, strict=False)
                ).encode("utf-8")
            ).hexdigest()
            keep_names = [
                name
                for name, action in zip(row_names, row_actions, strict=False)
                if action == "KEEP_CRUSADER"
            ]
            blocked_review_names = [
                name
                for name, action, origin in zip(
                    row_names, row_actions, row_origins, strict=False
                )
                if action == "REVIEW_MANUAL" and origin == TARGET_FRAME_ORIGIN
            ]
            fractional_names = [
                name
                for name, status in zip(row_names, row_statuses, strict=False)
                if status == "REVIEW_LOSSLESS_FRACTIONAL"
            ]
            keep_digest = hashlib.sha256(
                "".join(name + "\n" for name in keep_names).encode("utf-8")
            ).hexdigest()
            blocked_review_digest = hashlib.sha256(
                "".join(name + "\n" for name in blocked_review_names).encode(
                    "utf-8"
                )
            ).hexdigest()
            fractional_digest = hashlib.sha256(
                "".join(name + "\n" for name in fractional_names).encode("utf-8")
            ).hexdigest()
            action_origin_status_digest = hashlib.sha256(
                "".join(
                    f"{name}\t{action}\t{origin}\t{status}\n"
                    for name, action, origin, status in zip(
                        row_names,
                        row_actions,
                        row_origins,
                        row_statuses,
                        strict=False,
                    )
                ).encode("utf-8")
            ).hexdigest()
            expected_textures = REVIEW_139_GROUP_TEXTURES.get(group)
            status_counts = review_policy.get("status_counts")
            texture_contract_ok = (
                expected_textures is not None
                and metadata.get("source_texture") == expected_textures[0]
                and metadata.get("target_texture") == expected_textures[1]
            )
            # Als benannte Einzelbedingungen statt als eine lange
            # Und-Verkettung. Der Unterschied ist nicht Geschmack: Diese
            # Pruefung hat am 16.08.2026 eine Installation gestoppt und dabei
            # nur ihre Messwerte gemeldet - die alle stimmten. Welche der
            # zwanzig Bedingungen fiel, war aus der Meldung nicht zu erkennen
            # und musste von Hand nachgerechnet werden. Jetzt nennt sie sich.
            review_conditions = {
                "required": review_required,
                "rows": rows_ok,
                "row_names": row_names == ordered_names,
                "row_origin_count": len(row_origins) == len(ordered_names),
                "proof_algorithm": review_policy.get("proof_algorithm")
                == PLACEMENT_PROOF_ALGORITHM,
                "source_frame_count": review_policy.get("source_frame_count")
                == len(source_names),
                "target_frame_count": review_policy.get("target_frame_count")
                == len(target_names),
                "source_not_empty": len(source_names) > 0,
                # V1/V2 describe a genuinely mixed atlas. V3 additionally
                # permits a cryptographically proven empty keep/target set.
                "target_not_empty_unless_v3": (
                    len(target_names) > 0
                    or mode == REVIEW_FRAME_POLICY_MODE_V3
                ),
                "source_names_sha256": review_policy.get("source_names_sha256")
                == source_digest,
                "target_names_sha256": review_policy.get("target_names_sha256")
                == target_digest,
                "provenance_sha256": review_policy.get("provenance_sha256")
                == provenance_digest,
                "target_passthrough_exact": review_policy.get(
                    "target_passthrough_exact"
                )
                is True,
                "discarded_source_mask_alpha": review_policy.get(
                    "discarded_source_mask_alpha"
                )
                == discarded_total,
                "textures": texture_contract_ok,
                "roundtrip_metadata": isinstance(roundtrip_metadata, dict),
                "roundtrip_serialized": isinstance(roundtrip_metadata, dict)
                and roundtrip_metadata.get("serialized_files") is True,
            }
            common_review_ok = all(review_conditions.values())
            if mode == REVIEW_FRAME_POLICY_MODE:
                mode_review_ok = status_counts == {
                    "AUTO_LOSSLESS_INTEGRAL": len(source_names),
                    "BLOCKED_ALPHA_CLIP": len(target_names),
                }
            elif mode == REVIEW_FRAME_POLICY_MODE_V2:
                mode_review_ok = (
                    len(keep_names) > 0
                    and review_policy.get("keep_frame_count") == len(keep_names)
                    and review_policy.get("keep_names_sha256") == keep_digest
                    and review_policy.get("blocked_review_frame_count")
                    == len(blocked_review_names)
                    and review_policy.get("blocked_review_names_sha256")
                    == blocked_review_digest
                    and review_policy.get("fractional_frame_count")
                    == len(fractional_names)
                    == 0
                    and review_policy.get("fractional_names_sha256")
                    == fractional_digest
                    and review_policy.get("action_origin_status_sha256")
                    == action_origin_status_digest
                    and review_policy.get("action_counts")
                    == {
                        "REVIEW_MANUAL": len(source_names)
                        + len(blocked_review_names),
                        "KEEP_CRUSADER": len(keep_names),
                    }
                    and len(target_names)
                    == len(blocked_review_names) + len(keep_names)
                    and status_counts
                    == {
                        "AUTO_LOSSLESS_INTEGRAL": len(source_names),
                        "BLOCKED_ALPHA_CLIP": len(blocked_review_names),
                        KEEP_CRUSADER_PROOF_STATUS: len(keep_names),
                    }
                )
            elif mode == REVIEW_FRAME_POLICY_MODE_V3:
                # Wie V2, zusaetzlich die drei Aussagen, die unter V3
                # strukturell gelten muessen: nichts abgewiesen, die
                # Crusader-Herkunft deckt sich genau mit den Keep-Frames, und
                # es gibt nur die beiden nativen Statuswerte. Die Freigabeliste
                # wird hier noch einmal gefordert: fertige Metadaten duerfen
                # sich den nativen Modus nicht selbst erteilen.
                review_conditions.update(
                    {
                        "v3_group_approved": group
                        in REVIEW_NATIVE_GEOMETRY_139_GROUPS,
                        "v3_keep_frame_count": review_policy.get(
                            "keep_frame_count"
                        )
                        == len(keep_names),
                        "v3_keep_names_sha256": review_policy.get(
                            "keep_names_sha256"
                        )
                        == keep_digest,
                        "v3_blocked_empty": review_policy.get(
                            "blocked_review_frame_count"
                        )
                        == len(blocked_review_names)
                        == 0,
                        "v3_blocked_names_sha256": review_policy.get(
                            "blocked_review_names_sha256"
                        )
                        == blocked_review_digest,
                        "v3_fractional_empty": review_policy.get(
                            "fractional_frame_count"
                        )
                        == len(fractional_names)
                        == 0,
                        "v3_fractional_names_sha256": review_policy.get(
                            "fractional_names_sha256"
                        )
                        == fractional_digest,
                        "v3_action_origin_status_sha256": review_policy.get(
                            "action_origin_status_sha256"
                        )
                        == action_origin_status_digest,
                        "v3_action_counts": review_policy.get("action_counts")
                        == {
                            "REVIEW_MANUAL": len(source_names),
                            "KEEP_CRUSADER": len(keep_names),
                        },
                        "v3_target_is_keep": target_names == keep_names,
                        "v3_status_counts": status_counts
                        == {
                            NATIVE_SOURCE_PROOF_STATUS: len(source_names),
                            KEEP_CRUSADER_PROOF_STATUS: len(keep_names),
                        },
                    }
                )
                mode_review_ok = (
                    group in REVIEW_NATIVE_GEOMETRY_139_GROUPS
                    # A V3 group may intentionally be entirely European.  In
                    # that case the KEEP_CRUSADER partition is the proven empty
                    # set (body_swordsman is 1184/1184 source frames).  Requiring
                    # a non-empty keep set rejected the builder's own valid
                    # output.  What must be non-empty is the native source set.
                    and len(source_names) > 0
                    and review_policy.get("keep_frame_count") == len(keep_names)
                    and review_policy.get("keep_names_sha256") == keep_digest
                    and review_policy.get("blocked_review_frame_count")
                    == len(blocked_review_names)
                    == 0
                    and review_policy.get("blocked_review_names_sha256")
                    == blocked_review_digest
                    and review_policy.get("fractional_frame_count")
                    == len(fractional_names)
                    == 0
                    and review_policy.get("fractional_names_sha256")
                    == fractional_digest
                    and review_policy.get("action_origin_status_sha256")
                    == action_origin_status_digest
                    and review_policy.get("action_counts")
                    == {
                        "REVIEW_MANUAL": len(source_names),
                        "KEEP_CRUSADER": len(keep_names),
                    }
                    and target_names == keep_names
                    and status_counts
                    == {
                        NATIVE_SOURCE_PROOF_STATUS: len(source_names),
                        KEEP_CRUSADER_PROOF_STATUS: len(keep_names),
                    }
                )
            else:
                mode_review_ok = False
            review_ok = (
                common_review_ok and mode_review_ok
            )
            review_detail = (
                f"mode={mode} rows={len(row_names)}/{len(ordered_names)} "
                f"source={len(source_names)} target={len(target_names)} "
                f"blocked={len(blocked_review_names)} keep={len(keep_names)} "
                f"source_digest={source_digest} target_digest={target_digest} "
                f"provenance={provenance_digest} "
                f"action_provenance={action_origin_status_digest} "
                f"textures={texture_contract_ok}"
            )
            if not review_ok:
                # Die gefallenen Bedingungen namentlich, sonst steht in der
                # Meldung nur, dass etwas nicht stimmt - und alle Messwerte
                # sehen richtig aus.
                failed = sorted(
                    name for name, held in review_conditions.items() if not held
                )
                review_detail = (
                    "gescheitert: " + ", ".join(failed) + " | " + review_detail
                    if failed
                    else review_detail
                )
        elif review_required:
            review_detail = "required review_frame_policy metadata is missing"
        checks.append(
            _check(
                f"atlas.review_frame_policy.{label}",
                review_ok,
                review_detail,
            )
        )

        padding = metadata.get("padding")
        padding_ok = isinstance(padding, int) and not isinstance(padding, bool) and padding >= 1
        distinct_rects = sorted(unique_rects)
        if padding_ok:
            for x, y, width, height in distinct_rects:
                if (
                    x < padding
                    or y < padding
                    or x + width + padding > atlas_size[0]
                    or y + height + padding > atlas_size[1]
                ):
                    padding_ok = False
                    break
        if padding_ok:
            for index, left in enumerate(distinct_rects):
                lx, ly, lw, lh = left
                for right in distinct_rects[index + 1 :]:
                    rx, ry, rw, rh = right
                    expanded_overlap = not (
                        lx + lw + padding <= rx - padding
                        or rx + rw + padding <= lx - padding
                        or ly + lh + padding <= ry - padding
                        or ry + rh + padding <= ly - padding
                    )
                    if expanded_overlap:
                        padding_ok = False
                        break
                if not padding_ok:
                    break
        checks.append(
            _check(
                f"atlas.padding_and_overlap.{label}",
                padding_ok,
                f"padding={padding} unique_regions={len(distinct_rects)}",
            )
        )
        visual_gate = not material_compatible
        checks.append(
            _check(
                f"atlas.loader_material_gate.{label}",
                metadata.get("loader_material_compatible") is material_compatible,
                (
                    "runtime visual foliage-material gate required"
                    if visual_gate
                    else "loader material path matches vanilla group"
                ),
            )
        )
    return checks


def _profile_atlas_contract_checks(
    expected_profile: dict[str, Any],
    declared: dict[str, dict[str, Any]],
) -> list[ValidationCheck]:
    """Bind a built atlas namespace to the externally selected profile.

    The ordinary atlas validator deliberately validates what an artifact
    declares.  Installation additionally needs the inverse proof: every atlas
    selected by the profile is present, and no undeclared atlas was added.
    """

    checks: list[ValidationCheck] = []
    raw_specs = expected_profile.get("gm_atlases", [])
    specs: list[AtlasGroupSpec] = []
    shared_specs: list[SharedGMAtlasSpec] = []
    spec_error = ""
    if not isinstance(raw_specs, list):
        spec_error = "profile gm_atlases must be a list"
    else:
        try:
            specs = [AtlasGroupSpec.from_profile(raw) for raw in raw_specs]
        except (GMAtlasError, AttributeError, OverflowError, TypeError, ValueError) as exc:
            spec_error = str(exc)
    raw_shared_specs = expected_profile.get(SHARED_GM_ATLAS_PROFILE_KEY, [])
    if not spec_error and not isinstance(raw_shared_specs, list):
        spec_error = f"profile {SHARED_GM_ATLAS_PROFILE_KEY} must be a list"
    elif not spec_error:
        try:
            shared_specs = [
                SharedGMAtlasSpec.from_profile(raw) for raw in raw_shared_specs
            ]
        except (GMAtlasError, AttributeError, OverflowError, TypeError, ValueError) as exc:
            spec_error = str(exc)
    group_keys = [spec.gm_file_name.casefold() for spec in specs] + [
        name.casefold() for spec in shared_specs for name in spec.member_names
    ]
    if not spec_error and len(group_keys) != len(set(group_keys)):
        spec_error = "profile selects a GM atlas group more than once"
    checks.append(
        _check(
            "profile.atlas_spec_shape",
            not spec_error,
            spec_error or f"groups={len(specs)} shared={len(shared_specs)}",
        )
    )
    if spec_error:
        return checks

    expected_paths: set[str] = set()
    source_counts: dict[str, int] = {}
    for spec in specs:
        prefix = f"Override/Atlas/{spec.gm_file_name}/"
        expected_paths.update({prefix + "atlas.json", prefix + "atlas.png"})
        if spec.require_mask:
            expected_paths.add(prefix + "atlas_m.png")
        source_counts[spec.source_texture] = (
            source_counts.get(spec.source_texture, 0) + 1
        )
    for spec in shared_specs:
        prefix = f"Override/Atlas/{spec.host_gm_file_name}/"
        expected_paths.update({prefix + "atlas.json", prefix + "atlas.png"})
        source_counts[spec.source_texture] = (
            source_counts.get(spec.source_texture, 0) + 1
        )
    actual_paths = {
        relative
        for relative in declared
        if relative.casefold().startswith("override/atlas/")
    }
    checks.append(
        _check(
            "profile.atlas_output_set",
            actual_paths == expected_paths,
            f"expected={sorted(expected_paths)} actual={sorted(actual_paths)}",
        )
    )

    for spec in specs:
        relative = f"Override/Atlas/{spec.gm_file_name}/atlas.json"
        entry = declared.get(relative)
        metadata = (
            entry.get("metadata")
            if isinstance(entry, dict) and isinstance(entry.get("metadata"), dict)
            else None
        )
        expected_metadata = {
            "gm_file_name": spec.gm_file_name,
            "source_texture": spec.source_texture,
            "target_texture": spec.target_texture,
            "dash_format": spec.dash_format,
            "mask_policy": spec.mask_policy,
            "frame_count": spec.expected_frame_count,
            "main_count": spec.expected_main_count,
            "alt_count": spec.expected_alt_count,
            "array_size": spec.expected_max_index + 1,
            "names_sha256": spec.expected_names_sha256,
            "padding": spec.padding,
            "max_dimension": spec.max_dimension,
            "category": spec.category,
            "geometry_policy": spec.geometry_policy,
            "loader_material_compatible": spec.loader_material_compatible,
            "shared_source_texture_group_count": source_counts[
                spec.source_texture
            ],
            "sparse_keep_frame_count": spec.sparse_keep_frame_count,
        }
        mismatches = {
            key: {"expected": value, "actual": metadata.get(key) if metadata else None}
            for key, value in expected_metadata.items()
            if metadata is None or metadata.get(key) != value
        }
        def bind_policy(
            field: str, expected_policy: dict[str, object] | None
        ) -> None:
            actual_policy = metadata.get(field) if metadata is not None else None
            if expected_policy is None:
                if actual_policy is not None:
                    mismatches[field] = {
                        "expected": None,
                        "actual": actual_policy,
                    }
                return
            if not isinstance(actual_policy, dict):
                mismatches[field] = {
                    "expected": expected_policy,
                    "actual": actual_policy,
                }
                return
            remap_reference: dict[str, Any] = {}
            if field == "source_remap_policy":
                try:
                    remap_reference = source_remap_reference_proof(
                        actual_policy.get("frame_proofs"),
                        SOURCE_REMAP_139_CONTRACTS[spec.gm_file_name],
                    )
                except (GMAtlasError, KeyError, TypeError, ValueError):
                    pass
            for key, value in expected_policy.items():
                actual = (
                    remap_reference.get(key)
                    if field == "source_remap_policy" and key in {"mapping_sha256", "proof_sha256"}
                    else actual_policy.get(key)
                )
                if actual != value:
                    mismatches[f"{field}.{key}"] = {
                        "expected": value,
                        "actual": actual,
                    }

        derived_policy = spec.derived_frame_policy
        bind_policy(
            "derived_frame_policy",
            None
            if derived_policy is None
            else {
                "mode": derived_policy.mode,
                "proof_algorithm": derived_policy.proof_algorithm,
                "frame_count": derived_policy.expected_frame_count,
                "discarded_mask_alpha": (
                    derived_policy.expected_discarded_mask_alpha
                ),
                "frame_proof_sha256": derived_policy.expected_frame_proof_sha256,
            },
        )

        review_policy = spec.review_frame_policy
        expected_review: dict[str, object] | None = None
        if review_policy is not None:
            expected_review = {
                "mode": review_policy.mode,
                "proof_algorithm": review_policy.proof_algorithm,
                "source_frame_count": review_policy.expected_source_frame_count,
                "target_frame_count": review_policy.expected_target_frame_count,
                "source_names_sha256": review_policy.expected_source_names_sha256,
                "target_names_sha256": review_policy.expected_target_names_sha256,
                "provenance_sha256": review_policy.expected_provenance_sha256,
                "target_passthrough_exact": True,
                "status_counts": {
                    "AUTO_LOSSLESS_INTEGRAL": (
                        review_policy.expected_source_frame_count
                    ),
                    "BLOCKED_ALPHA_CLIP": (
                        review_policy.expected_target_frame_count
                    ),
                },
            }
            if review_policy.includes_keep:
                expected_review.update(
                    {
                        "keep_frame_count": review_policy.expected_keep_frame_count,
                        "keep_names_sha256": review_policy.expected_keep_names_sha256,
                        "blocked_review_frame_count": (
                            review_policy.expected_blocked_review_frame_count
                        ),
                        "blocked_review_names_sha256": (
                            review_policy.expected_blocked_review_names_sha256
                        ),
                        "fractional_frame_count": (
                            review_policy.expected_fractional_frame_count
                        ),
                        "fractional_names_sha256": (
                            review_policy.expected_fractional_names_sha256
                        ),
                        "action_origin_status_sha256": (
                            review_policy.expected_action_origin_status_sha256
                        ),
                        "action_counts": {
                            "REVIEW_MANUAL": (
                                review_policy.expected_source_frame_count
                                + review_policy.expected_blocked_review_frame_count
                            ),
                            "KEEP_CRUSADER": review_policy.expected_keep_frame_count,
                        },
                        "status_counts": {
                            "AUTO_LOSSLESS_INTEGRAL": (
                                review_policy.expected_source_frame_count
                            ),
                            "BLOCKED_ALPHA_CLIP": (
                                review_policy.expected_blocked_review_frame_count
                            ),
                            KEEP_CRUSADER_PROOF_STATUS: (
                                review_policy.expected_keep_frame_count
                            ),
                        },
                    }
                )
            if review_policy.renders_native_source:
                # Unter V3 gibt es weder AUTO_LOSSLESS_INTEGRAL noch
                # BLOCKED_ALPHA_CLIP: die Zielleinwand, an der abgewiesen wird,
                # existiert dort nicht. `expected_blocked_review_frame_count`
                # ist schon beim Parsen auf 0 festgenagelt, deshalb tragen
                # action_counts und blocked_* oben bereits die richtigen Werte.
                expected_review["status_counts"] = {
                    NATIVE_SOURCE_PROOF_STATUS: (
                        review_policy.expected_source_frame_count
                    ),
                    KEEP_CRUSADER_PROOF_STATUS: (
                        review_policy.expected_keep_frame_count
                    ),
                }
        bind_policy("review_frame_policy", expected_review)

        native_policy = spec.native_source_geometry_policy
        bind_policy(
            "native_source_geometry_policy",
            None
            if native_policy is None
            else {
                "mode": native_policy.mode,
                "proof_algorithm": native_policy.proof_algorithm,
                "frame_count": native_policy.expected_frame_count,
                "geometry_proof_sha256": (
                    native_policy.expected_geometry_proof_sha256
                ),
                "origin_proof_sha256": native_policy.expected_origin_proof_sha256,
                "source_rgba_sha256": native_policy.expected_source_rgba_sha256,
                "target_origin_count": 0,
                "native_rgba_exact": True,
                "target_canvas_used": False,
                "clipping": False,
                "resampling": "none",
            },
        )
        bind_policy(
            "sparse_keep_policy",
            None
            if spec.sparse_keep_frame_count is None
            else {
                "mode": SPARSE_KEEP_POLICY_MODE,
                "proof_algorithm": SPARSE_KEEP_PROOF_ALGORITHM,
                "frame_count": spec.sparse_keep_frame_count,
                "target_rgba_exact": True,
                "source_pixels_used": False,
                "clipping": False,
                "resampling": "none",
            },
        )

        source_remap_policy = spec.source_remap_policy
        bind_policy(
            "source_remap_policy",
            None
            if source_remap_policy is None
            else {
                "mode": source_remap_policy.mode,
                "proof_algorithm": source_remap_policy.proof_algorithm,
                "frame_count": source_remap_policy.expected_frame_count,
                "mapping_sha256": (
                    source_remap_policy.expected_mapping_sha256
                ),
                "proof_sha256": source_remap_policy.expected_proof_sha256,
                "source_rgba_sha256": (
                    source_remap_policy.expected_source_rgba_sha256
                ),
                "output_rgba_sha256": (
                    source_remap_policy.expected_output_rgba_sha256
                ),
                "visible_blue_pixel_count": (
                    source_remap_policy.expected_visible_blue_pixel_count
                ),
                "source_only": True,
                "target_fallback_count": 0,
                "exact_canvas": True,
                "clipping": False,
                "resampling": "none",
            },
        )
        checks.append(
            _check(
                f"profile.atlas_metadata.{spec.gm_file_name}",
                metadata is not None and not mismatches,
                json.dumps(mismatches, sort_keys=True),
            )
        )
    for spec in shared_specs:
        relative = f"Override/Atlas/{spec.host_gm_file_name}/atlas.json"
        entry = declared.get(relative)
        metadata = (
            entry.get("metadata")
            if isinstance(entry, dict) and isinstance(entry.get("metadata"), dict)
            else None
        )
        policy = (
            metadata.get("shared_gm_atlas_policy")
            if isinstance(metadata, dict)
            else None
        )
        expected_metadata = {
            "kind": SHARED_GM_ATLAS_KIND,
            "gm_file_name": spec.host_gm_file_name,
            "source_texture": spec.source_texture,
            "target_texture": spec.target_texture,
            "dash_format": spec.dash_format,
            "mask_policy": spec.mask_policy,
            "frame_count": spec.expected_frame_count,
            "main_count": spec.expected_main_count,
            "alt_count": spec.expected_alt_count,
            "array_size": spec.expected_array_size,
            "names_sha256": spec.expected_output_names_sha256,
            "padding": spec.padding,
            "max_dimension": spec.max_dimension,
            "category": spec.category,
            "geometry_policy": spec.geometry_policy,
            "loader_material_compatible": True,
            "shared_source_texture_group_count": source_counts[
                spec.source_texture
            ],
        }
        expected_policy = {
            "mode": spec.mode,
            "gm_enum": spec.gm_enum,
            "host_gm_file_name": spec.host_gm_file_name,
            "member_gm_file_names": list(spec.member_names),
            "geometry_policy": spec.geometry_policy,
            "proof_algorithm": spec.proof_algorithm,
            "frame_count": spec.expected_frame_count,
            "array_size": spec.expected_array_size,
            "null_slot_count": spec.expected_null_slot_count,
            "combined_names_sha256": spec.expected_combined_names_sha256,
            "output_names_sha256": spec.expected_output_names_sha256,
            "slot_logical_output_sha256": (
                spec.expected_slot_logical_output_sha256
            ),
            "slot_logical_source_rgba_sha256": (
                spec.expected_slot_logical_source_rgba_sha256
            ),
            "member_frame_counts": {
                member.gm_file_name: member.expected_frame_count
                for member in spec.members
            },
            "member_names_sha256": {
                member.gm_file_name: member.expected_names_sha256
                for member in spec.members
            },
            "member_source_rgba_sha256": {
                member.gm_file_name: member.expected_source_rgba_sha256
                for member in spec.members
            },
            "native_rgba_exact": True,
            "target_canvas_used": False,
            "target_fallback_count": 0,
            "clipping": False,
            "resampling": "none",
        }
        mismatches = {
            key: {
                "expected": value,
                "actual": metadata.get(key) if isinstance(metadata, dict) else None,
            }
            for key, value in expected_metadata.items()
            if not isinstance(metadata, dict) or metadata.get(key) != value
        }
        mismatches.update(
            {
                f"shared_gm_atlas_policy.{key}": {
                    "expected": value,
                    "actual": policy.get(key) if isinstance(policy, dict) else None,
                }
                for key, value in expected_policy.items()
                if not isinstance(policy, dict) or policy.get(key) != value
            }
        )
        checks.append(
            _check(
                f"profile.atlas_metadata.{spec.host_gm_file_name}",
                metadata is not None and not mismatches,
                json.dumps(mismatches, sort_keys=True),
            )
        )
    return checks


def _review_individual_validation_checks(
    root: Path,
    declared: dict[str, dict[str, Any]],
    image_sizes: dict[str, tuple[int, int]],
    *,
    streaming: bool = False,
) -> list[ValidationCheck]:
    """Validate compact source-only review contracts and their exact PNG sets."""

    checks: list[ValidationCheck] = []
    contract_namespace = sorted(
        relative
        for relative in declared
        if relative.startswith(REVIEW_INDIVIDUAL_CONTRACT_PREFIX)
    )
    contract_paths = [
        relative
        for relative in contract_namespace
        if relative.endswith(".json")
        and "/" not in relative[len(REVIEW_INDIVIDUAL_CONTRACT_PREFIX) :]
    ]
    contract_record_paths = sorted(
        relative
        for relative, entry in declared.items()
        if entry.get("category") == "review_individual_source_contract"
        or (
            isinstance(entry.get("metadata"), dict)
            and entry["metadata"].get("kind")
            == REVIEW_INDIVIDUAL_CONTRACT_KIND
        )
    )
    checks.append(
        _check(
            "review_individual.contract_namespace",
            contract_namespace == contract_paths == contract_record_paths,
            f"contracts={contract_paths} unexpected="
            f"{sorted(set(contract_namespace) - set(contract_paths))} "
            f"records={contract_record_paths}",
        )
    )

    parsed_contracts: list[tuple[str, str, dict[str, Any]]] = []
    parse_errors: list[str] = []
    for relative in contract_paths:
        group_from_path = relative[
            len(REVIEW_INDIVIDUAL_CONTRACT_PREFIX) : -len(".json")
        ]
        try:
            raw = json.loads((root / relative).read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("contract root is not an object")
            parsed_contracts.append((relative, group_from_path, raw))
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            parse_errors.append(f"{relative}: {exc}")
    checks.append(
        _check(
            "review_individual.contract_json",
            len(parsed_contracts) == len(contract_paths) and not parse_errors,
            json.dumps(parse_errors, sort_keys=True),
        )
    )
    group_keys = [group.casefold() for _, group, _ in parsed_contracts]
    checks.append(
        _check(
            "review_individual.unique_groups",
            len(group_keys) == len(set(group_keys)),
            str(group_keys),
        )
    )

    def is_int(value: object, *, minimum: int = 0) -> bool:
        return type(value) is int and value >= minimum

    def is_sha256(value: object) -> bool:
        return (
            isinstance(value, str)
            and len(value) == 64
            and all(character in "0123456789abcdef" for character in value)
        )

    empty_names_sha256 = hashlib.sha256(b"").hexdigest()
    sprite_prefix = "Override/Sprites/"
    claimed_sparse_files: set[str] = set()
    for relative, group_from_path, contract in parsed_contracts:
        group = contract.get("gm_file_name")
        label = group_from_path or "invalid"
        loader = contract.get("loader_manifest")
        frame_rows = contract.get("frame_provenance")
        partition = contract.get("review_partition")
        source_output = contract.get("source_output")
        roundtrip = (
            source_output.get("serialized_png_roundtrip")
            if isinstance(source_output, dict)
            else None
        )
        root_keys_ok = set(contract) == {
            "schema_version",
            "kind",
            "mode",
            "gm_file_name",
            "loader_manifest",
            "frame_provenance",
            "review_partition",
            "source_output",
        }
        loader_keys_ok = isinstance(loader, dict) and set(loader) == {
            "dash_format",
            "mask_policy",
            "source_texture",
            "target_texture",
            "frame_count",
            "main_count",
            "alt_count",
            "max_index",
            "array_size",
            "names_sha256",
            "padding",
            "max_dimension",
            "category",
            "geometry_policy",
            "loader_material_compatible",
        }
        partition_keys_ok = isinstance(partition, dict) and set(partition) == {
            "mode",
            "proof_algorithm",
            "source_frame_count",
            "target_frame_count",
            "source_names_sha256",
            "target_names_sha256",
            "provenance_sha256",
            "keep_frame_count",
            "keep_names_sha256",
            "blocked_review_frame_count",
            "blocked_review_names_sha256",
            "fractional_frame_count",
            "fractional_names_sha256",
            "action_origin_status_sha256",
            "action_counts",
            "status_counts",
            "discarded_source_mask_alpha",
        }
        source_keys_ok = isinstance(source_output, dict) and set(source_output) == {
            "frame_count",
            "main_count",
            "alt_count",
            "names_sha256",
            "main_file_count",
            "mask_file_count",
            "blocked_and_keep_file_count",
            "serialized_png_roundtrip",
        }
        roundtrip_keys_ok = isinstance(roundtrip, dict) and set(roundtrip) == {
            "verified",
            "frames_checked",
            "payload_sha256",
        }
        frame_rows_shape_ok = (
            isinstance(frame_rows, list)
            and bool(frame_rows)
            and all(
                isinstance(row, dict)
                and set(row)
                == {
                    "name",
                    "action",
                    "origin",
                    "proof_status",
                    "discarded_mask_alpha",
                }
                for row in frame_rows
            )
        )
        shape_ok = (
            root_keys_ok
            and isinstance(group, str)
            and bool(group)
            and loader_keys_ok
            and frame_rows_shape_ok
            and partition_keys_ok
            and source_keys_ok
            and roundtrip_keys_ok
        )
        checks.append(
            _check(
                f"review_individual.schema.{label}",
                shape_ok,
                f"root={root_keys_ok} loader={loader_keys_ok} "
                f"rows={frame_rows_shape_ok} "
                f"partition={partition_keys_ok} source={source_keys_ok} "
                f"roundtrip={roundtrip_keys_ok}",
            )
        )
        if not shape_ok:
            continue
        assert isinstance(group, str)
        assert isinstance(loader, dict)
        assert isinstance(frame_rows, list)
        assert isinstance(partition, dict)
        assert isinstance(source_output, dict)
        assert isinstance(roundtrip, dict)

        entry = declared.get(relative, {})
        entry_metadata = (
            entry.get("metadata")
            if isinstance(entry.get("metadata"), dict)
            else {}
        )
        metadata_ok = (
            group == group_from_path
            and contract.get("schema_version") == 1
            and contract.get("kind") == REVIEW_INDIVIDUAL_CONTRACT_KIND
            and contract.get("mode") == REVIEW_INDIVIDUAL_SOURCE_ONLY_MODE
            and entry.get("category") == "review_individual_source_contract"
            and entry_metadata
            == {
                "kind": REVIEW_INDIVIDUAL_CONTRACT_KIND,
                "mode": REVIEW_INDIVIDUAL_SOURCE_ONLY_MODE,
                "gm_file_name": group,
                "contract_sha256": entry.get("sha256"),
            }
        )
        checks.append(
            _check(
                f"review_individual.metadata.{label}",
                metadata_ok,
                json.dumps(entry_metadata, sort_keys=True),
            )
        )

        loader_review = LOADER_139_GROUPS.get(group)
        texture_contract = REVIEW_139_GROUP_TEXTURES.get(group)
        loader_contract_ok = (
            loader_review is not None
            and texture_contract is not None
            and loader_review[0] is loader.get("dash_format")
            and loader_review[1] == loader.get("mask_policy") == "required"
            and loader_review[2] is True
            and tuple(texture_contract)
            == (loader.get("source_texture"), loader.get("target_texture"))
            and is_int(loader.get("frame_count"), minimum=1)
            and is_int(loader.get("main_count"), minimum=1)
            and is_int(loader.get("alt_count"))
            and loader["main_count"] + loader["alt_count"]
            == loader["frame_count"]
            and is_int(loader.get("max_index"))
            and loader.get("array_size") == loader["max_index"] + 1
            and is_sha256(loader.get("names_sha256"))
            and is_int(loader.get("padding"), minimum=1)
            and loader["padding"] <= 16
            and is_int(loader.get("max_dimension"), minimum=256)
            and loader["max_dimension"] <= 8192
            and loader["max_dimension"] & (loader["max_dimension"] - 1) == 0
            and isinstance(loader.get("category"), str)
            and bool(loader["category"])
            and loader.get("geometry_policy") == GEOMETRY_POLICY_TARGET_CANVAS
            and loader.get("loader_material_compatible") is True
        )
        checks.append(
            _check(
                f"review_individual.loader_manifest.{label}",
                loader_contract_ok,
                json.dumps(loader, sort_keys=True),
            )
        )

        row_names: list[str] = []
        row_slots = []
        rows_valid = True
        allowed_relations = {
            ("REVIEW_MANUAL", SOURCE_FRAME_ORIGIN, "AUTO_LOSSLESS_INTEGRAL"),
            ("REVIEW_MANUAL", TARGET_FRAME_ORIGIN, "BLOCKED_ALPHA_CLIP"),
            (
                "KEEP_CRUSADER",
                TARGET_FRAME_ORIGIN,
                KEEP_CRUSADER_PROOF_STATUS,
            ),
        }
        for row in frame_rows:
            name = row.get("name")
            action = row.get("action")
            origin = row.get("origin")
            proof_status = row.get("proof_status")
            discarded = row.get("discarded_mask_alpha")
            slot = (
                parse_loader_frame_name(name, group, bool(loader.get("dash_format")))
                if isinstance(name, str)
                else None
            )
            row_ok = (
                isinstance(name, str)
                and slot is not None
                and (action, origin, proof_status) in allowed_relations
                and is_int(discarded)
                and (origin == SOURCE_FRAME_ORIGIN or discarded == 0)
            )
            rows_valid = rows_valid and row_ok
            row_names.append(name if isinstance(name, str) else "")
            row_slots.append(slot)

        sorted_row_names = [
            name
            for _, name in sorted(
                zip(row_slots, row_names, strict=True),
                key=lambda item: (
                    item[0].index if item[0] is not None else -1,
                    item[0].is_alt if item[0] is not None else False,
                    item[1],
                ),
            )
        ]
        row_names_sha256 = hashlib.sha256(
            "".join(name + "\n" for name in row_names).encode("utf-8")
        ).hexdigest()
        row_main_count = sum(
            slot is not None and not slot.is_alt for slot in row_slots
        )
        row_alt_count = len(row_slots) - row_main_count
        row_max_index = max(
            (slot.index for slot in row_slots if slot is not None), default=-1
        )
        complete_rows_ok = (
            rows_valid
            and row_names == sorted_row_names
            and len(row_names) == len(set(row_names))
            and len(row_slots) == len(set(row_slots))
            and len(row_names) == loader.get("frame_count")
            and row_main_count == loader.get("main_count")
            and row_alt_count == loader.get("alt_count")
            and row_max_index == loader.get("max_index")
            and row_names_sha256 == loader.get("names_sha256")
        )
        row_source_names = [
            str(row["name"])
            for row in frame_rows
            if row.get("origin") == SOURCE_FRAME_ORIGIN
        ]
        row_target_names = [
            str(row["name"])
            for row in frame_rows
            if row.get("origin") == TARGET_FRAME_ORIGIN
        ]
        row_keep_names = [
            str(row["name"])
            for row in frame_rows
            if row.get("action") == "KEEP_CRUSADER"
        ]
        row_blocked_names = [
            str(row["name"])
            for row in frame_rows
            if row.get("action") == "REVIEW_MANUAL"
            and row.get("origin") == TARGET_FRAME_ORIGIN
        ]
        row_fractional_names = [
            str(row["name"])
            for row in frame_rows
            if row.get("proof_status") == "REVIEW_LOSSLESS_FRACTIONAL"
        ]

        def names_digest(names: list[str]) -> str:
            return hashlib.sha256(
                "".join(name + "\n" for name in names).encode("utf-8")
            ).hexdigest()

        provenance_sha256 = hashlib.sha256(
            "".join(
                f"{row.get('name', '')}\t{row.get('origin', '')}\n"
                for row in frame_rows
            ).encode("utf-8")
        ).hexdigest()
        action_origin_status_sha256 = hashlib.sha256(
            "".join(
                f"{row.get('name', '')}\t{row.get('action', '')}\t"
                f"{row.get('origin', '')}\t{row.get('proof_status', '')}\n"
                for row in frame_rows
            ).encode("utf-8")
        ).hexdigest()
        actual_action_counts = {
            action: sum(row.get("action") == action for row in frame_rows)
            for action in ("REVIEW_MANUAL", "KEEP_CRUSADER")
        }
        actual_status_counts = {
            status: sum(row.get("proof_status") == status for row in frame_rows)
            for status in (
                "AUTO_LOSSLESS_INTEGRAL",
                "BLOCKED_ALPHA_CLIP",
                KEEP_CRUSADER_PROOF_STATUS,
            )
        }
        discarded_total = sum(
            int(row.get("discarded_mask_alpha", 0))
            for row in frame_rows
            if is_int(row.get("discarded_mask_alpha"))
        )

        source_count = len(row_source_names)
        target_count = len(row_target_names)
        keep_count = len(row_keep_names)
        blocked_count = len(row_blocked_names)
        fractional_count = len(row_fractional_names)
        partition_contract_ok = (
            loader_contract_ok
            and complete_rows_ok
            and partition.get("mode") == REVIEW_FRAME_POLICY_MODE_V2
            and partition.get("proof_algorithm") == PLACEMENT_PROOF_ALGORITHM
            and source_count > 0
            and target_count > 0
            and source_count + target_count == loader["frame_count"]
            and keep_count > 0
            and keep_count + blocked_count == target_count
            and fractional_count == 0
            and partition.get("source_frame_count") == source_count
            and partition.get("target_frame_count") == target_count
            and partition.get("keep_frame_count") == keep_count
            and partition.get("blocked_review_frame_count") == blocked_count
            and partition.get("fractional_frame_count") == fractional_count
            and partition.get("source_names_sha256")
            == names_digest(row_source_names)
            and partition.get("target_names_sha256")
            == names_digest(row_target_names)
            and partition.get("keep_names_sha256")
            == names_digest(row_keep_names)
            and partition.get("blocked_review_names_sha256")
            == names_digest(row_blocked_names)
            and partition.get("fractional_names_sha256")
            == names_digest(row_fractional_names)
            == empty_names_sha256
            and partition.get("provenance_sha256") == provenance_sha256
            and partition.get("action_origin_status_sha256")
            == action_origin_status_sha256
            and partition.get("action_counts") == actual_action_counts
            and partition.get("status_counts") == actual_status_counts
            and partition.get("discarded_source_mask_alpha") == discarded_total
        )
        checks.append(
            _check(
                f"review_individual.full_partition.{label}",
                partition_contract_ok,
                json.dumps(partition, sort_keys=True),
            )
        )

        if streaming:
            streamed_legacy = sorted(
                path
                for path in declared
                if path.casefold().startswith(
                    ("override/sprites/", f"override/atlas/{group}/".casefold())
                )
            )
            checks.append(
                _check(
                    f"review_individual.streamed_payload.{label}",
                    not streamed_legacy,
                    f"legacy={streamed_legacy}",
                )
            )
            continue

        separator = "-" if loader.get("dash_format") is True else " "
        group_file_prefix = (sprite_prefix + group + separator).casefold()
        group_sprite_files = sorted(
            path
            for path in declared
            if path.casefold().startswith(group_file_prefix)
        )
        claimed_sparse_files.update(group_sprite_files)
        main_by_name: dict[str, str] = {}
        mask_by_name: dict[str, str] = {}
        invalid_group_files: list[str] = []
        for path in group_sprite_files:
            flat_name = path[len(sprite_prefix) :]
            if path.endswith("_m.png"):
                name = flat_name[:-6]
                destination = mask_by_name
            elif path.endswith(".png"):
                name = flat_name[:-4]
                destination = main_by_name
            else:
                invalid_group_files.append(path)
                continue
            if parse_loader_frame_name(
                name, group, bool(loader.get("dash_format"))
            ) is None or name in destination:
                invalid_group_files.append(path)
                continue
            destination[name] = path

        source_names = sorted(
            main_by_name,
            key=lambda name: (
                parse_loader_frame_name(
                    name, group, bool(loader.get("dash_format"))
                ).index,
                parse_loader_frame_name(
                    name, group, bool(loader.get("dash_format"))
                ).is_alt,
                name,
            ),
        )
        slots = [
            parse_loader_frame_name(
                name, group, bool(loader.get("dash_format"))
            )
            for name in source_names
        ]
        actual_names_sha256 = hashlib.sha256(
            "".join(name + "\n" for name in source_names).encode("utf-8")
        ).hexdigest()
        actual_main_count = sum(slot is not None and not slot.is_alt for slot in slots)
        actual_alt_count = len(slots) - actual_main_count
        source_file_set_ok = (
            not invalid_group_files
            and set(main_by_name) == set(mask_by_name)
            and source_names == row_source_names
            and len(source_names) == source_count
            and source_output.get("frame_count") == len(source_names)
            and source_output.get("main_count") == actual_main_count
            and source_output.get("alt_count") == actual_alt_count
            and source_output.get("main_file_count") == len(main_by_name)
            and source_output.get("mask_file_count") == len(mask_by_name)
            and source_output.get("blocked_and_keep_file_count") == 0
            and source_output.get("names_sha256") == actual_names_sha256
            == partition.get("source_names_sha256")
        )
        checks.append(
            _check(
                f"review_individual.file_set.{label}",
                source_file_set_ok,
                f"main={len(main_by_name)} alt={actual_alt_count} "
                f"masks={len(mask_by_name)} invalid={invalid_group_files} "
                f"digest={actual_names_sha256}",
            )
        )

        payload_rows: list[dict[str, Any]] = []
        payload_shape_ok = source_file_set_ok
        for name in source_names:
            main_path = main_by_name[name]
            mask_path = mask_by_name.get(name, "")
            main_entry = declared.get(main_path, {})
            mask_entry = declared.get(mask_path, {})
            main_size = image_sizes.get(main_path)
            mask_size = image_sizes.get(mask_path)
            row_ok = (
                main_entry.get("category") == REVIEW_INDIVIDUAL_MAIN_CATEGORY
                and mask_entry.get("category") == REVIEW_INDIVIDUAL_MASK_CATEGORY
                and main_size is not None
                and main_size == mask_size
                and is_sha256(main_entry.get("sha256"))
                and is_sha256(mask_entry.get("sha256"))
            )
            payload_shape_ok = payload_shape_ok and row_ok
            if row_ok:
                assert main_size is not None
                payload_rows.append(
                    {
                        "name": name,
                        "main_sha256": main_entry["sha256"],
                        "mask_sha256": mask_entry["sha256"],
                        "width": main_size[0],
                        "height": main_size[1],
                    }
                )
        try:
            payload_sha256 = review_individual_payload_digest(payload_rows)
        except (TypeError, ValueError):
            payload_sha256 = "invalid"
            payload_shape_ok = False
        roundtrip_ok = (
            payload_shape_ok
            and roundtrip.get("verified") is True
            and roundtrip.get("frames_checked") == len(source_names)
            and roundtrip.get("payload_sha256") == payload_sha256
        )
        checks.append(
            _check(
                f"review_individual.png_roundtrip.{label}",
                roundtrip_ok,
                f"rows={len(payload_rows)} payload_sha256={payload_sha256}",
            )
        )

        atlas_prefix = f"Override/Atlas/{group}/".casefold()
        atlas_files = sorted(
            path for path in declared if path.casefold().startswith(atlas_prefix)
        )
        checks.append(
            _check(
                f"review_individual.no_atlas_or_fallback.{label}",
                not atlas_files and not invalid_group_files,
                f"atlas={atlas_files} fallback={invalid_group_files}",
            )
        )
    sparse_record_files = {
        relative
        for relative, entry in declared.items()
        if entry.get("category")
        in {REVIEW_INDIVIDUAL_MAIN_CATEGORY, REVIEW_INDIVIDUAL_MASK_CATEGORY}
    }
    checks.append(
        _check(
            "review_individual.no_orphan_payload",
            sparse_record_files == claimed_sparse_files,
            f"records={sorted(sparse_record_files)} "
            f"claimed={sorted(claimed_sparse_files)}",
        )
    )
    return checks


def _strict_stream_index_shape(
    index_path: Path,
) -> tuple[
    bytes,
    dict[str, object],
    list[dict[str, object]],
    list[dict[str, object]],
]:
    try:
        before = index_path.stat()
        if (
            not index_path.is_file()
            or index_path.is_symlink()
            or not 1 <= before.st_size <= ASSET_STREAM_MAX_INDEX_BYTES
        ):
            raise AssetStreamContractError(
                "index.json is missing, linked, empty, or oversized"
            )
        payload = index_path.read_bytes()
        after = index_path.stat()
    except OSError as exc:
        raise AssetStreamContractError("index.json could not be read") from exc
    if (
        len(payload) != before.st_size
        or (before.st_size, before.st_mtime_ns)
        != (after.st_size, after.st_mtime_ns)
    ):
        raise AssetStreamContractError("index.json changed while being read")
    if payload.startswith(b"\xef\xbb\xbf"):
        raise AssetStreamContractError("index.json has a UTF-8 BOM")

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise AssetStreamContractError(
                    f"index.json repeats key {key!r}"
                )
            result[key] = value
        return result

    try:
        value = json.loads(
            payload.decode("utf-8", errors="strict"),
            object_pairs_hook=pairs,
            parse_constant=lambda token: (_ for _ in ()).throw(
                AssetStreamContractError(
                    f"index.json contains non-finite number {token!r}"
                )
            ),
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise AssetStreamContractError("index.json is not strict JSON") from exc
    if not isinstance(value, dict):
        raise AssetStreamContractError("index.json root is not an object")
    if payload != canonical_json_bytes(value) + b"\n":
        raise AssetStreamContractError("index.json is not canonical UTF-8/LF")
    schema = value.get("schema")
    is_v2 = schema == BC7_INDEX_SCHEMA
    expected_root_keys = (
        {
            "backend_kind",
            "build_id",
            "build_target",
            "encoder_id",
            "groups",
            "max_page_dimension",
            "packer_id",
            "quality_policy",
            "quality_report_sha256",
            "schema",
            "texture_policy",
            "total_gpu_bytes",
            "total_resident_charge_bytes",
            "total_source_rgba_bytes",
            "unity",
            "vanilla_omitted_groups",
        }
        if is_v2
        else {
            "schema",
            "build_id",
            "unity",
            "build_target",
            "max_page_dimension",
            "groups",
            "vanilla_omitted_groups",
        }
    )
    if set(value) != expected_root_keys:
        raise AssetStreamContractError("index.json root key set changed")
    raw_groups = value.get("groups")
    raw_omitted = value.get("vanilla_omitted_groups")
    if (
        not isinstance(raw_groups, list)
        or not isinstance(raw_omitted, list)
        or not 1 <= len(raw_groups) + len(raw_omitted) <= ASSET_STREAM_MAX_GROUPS
        or any(not isinstance(group, dict) for group in raw_groups)
        or any(not isinstance(group, dict) for group in raw_omitted)
    ):
        raise AssetStreamContractError(
            "index.json group count/shape exceeds the v1 bound"
        )
    groups = [group for group in raw_groups if isinstance(group, dict)]
    omitted_groups = [
        group for group in raw_omitted if isinstance(group, dict)
    ]
    seen_paths: set[str] = set()
    seen_ids: set[int] = set()
    seen_groups: set[str] = set()
    for ordinal, group in enumerate(groups):
        label = f"index.json.groups[{ordinal}]"
        gm_id = group.get("gm_id")
        array_size = group.get("array_size")
        page_count = group.get("page_count")
        frame_count = group.get("frame_count")
        pages = group.get("pages")
        if (
            isinstance(gm_id, bool)
            or not isinstance(gm_id, int)
            or not 0 <= gm_id < ASSET_STREAM_MAX_GROUPS
            or gm_id in seen_ids
            or isinstance(array_size, bool)
            or not isinstance(array_size, int)
            or not 1 <= array_size <= ASSET_STREAM_MAX_FRAMES
            or isinstance(page_count, bool)
            or not isinstance(page_count, int)
            or not 1
            <= page_count
            <= (BC7_MAX_PAGES_PER_GROUP if is_v2 else ASSET_STREAM_MAX_PAGES)
            or isinstance(frame_count, bool)
            or not isinstance(frame_count, int)
            or not 1 <= frame_count <= ASSET_STREAM_MAX_FRAMES
            or not isinstance(pages, list)
            or len(pages) != page_count
        ):
            raise AssetStreamContractError(f"{label} exceeds v1 bounds")
        seen_ids.add(gm_id)
        group_name = group.get("group")
        try:
            canonical_group_slug(group_name, f"{label}.group")
        except AssetStreamContractError as exc:
            raise AssetStreamContractError(f"{label}.group is invalid") from exc
        if group_name.casefold() in seen_groups:
            raise AssetStreamContractError(f"{label}.group is invalid")
        seen_groups.add(group_name.casefold())
        for page in pages:
            if not isinstance(page, dict):
                raise AssetStreamContractError(f"{label}.pages is malformed")
            width = page.get("width")
            height = page.get("height")
            if (
                isinstance(width, bool)
                or not isinstance(width, int)
                or isinstance(height, bool)
                or not isinstance(height, int)
                or not 256 <= width <= 4096
                or not 256 <= height <= 4096
                or width & (width - 1)
                or height & (height - 1)
            ):
                raise AssetStreamContractError(
                    f"{label}.pages geometry exceeds v1 bounds"
                )
        bundle_path = require_safe_relative_path(
            group.get("bundle_path"), f"{label}.bundle_path"
        )
        atlas_path = require_safe_relative_path(
            group.get("atlas_asset_path"), f"{label}.atlas_asset_path"
        )
        expected_bundle_suffix = ".bc7.v2" if is_v2 else ".v2"
        expected_atlas_suffix = "/atlas.v3.json" if is_v2 else "/atlas.v2.json"
        if (
            not bundle_path.startswith("Runtime/AssetBundles/win64/sede.gm.")
            or not bundle_path.endswith(expected_bundle_suffix)
            or bundle_path.casefold() in seen_paths
        ):
            raise AssetStreamContractError(f"{label}.bundle_path is invalid")
        seen_paths.add(bundle_path.casefold())
        if (
            not atlas_path.startswith("Assets/Generated/Groups/")
            or not atlas_path.endswith(expected_atlas_suffix)
        ):
            raise AssetStreamContractError(f"{label}.atlas_asset_path is invalid")
    omitted_keys = {
        "group",
        "gm_id",
        "reason",
        "array_size",
        "frame_count",
        "names_sha256",
        "frames_sha256",
    }
    previous_omitted: str | None = None
    for ordinal, omitted in enumerate(omitted_groups):
        label = f"index.json.vanilla_omitted_groups[{ordinal}]"
        group_name = omitted.get("group")
        gm_id = omitted.get("gm_id")
        reason = omitted.get("reason")
        array_size = omitted.get("array_size")
        frame_count = omitted.get("frame_count")
        try:
            canonical_group_slug(group_name, f"{label}.group")
        except AssetStreamContractError as exc:
            raise AssetStreamContractError(f"{label} is malformed") from exc
        if (
            set(omitted) != omitted_keys
            or group_name.casefold() in seen_groups
            or previous_omitted is not None
            and previous_omitted >= group_name
            or isinstance(gm_id, bool)
            or not isinstance(gm_id, int)
            or not 0 <= gm_id < ASSET_STREAM_MAX_GROUPS
            or gm_id in seen_ids
            or reason not in ASSET_STREAM_OMISSION_REASONS
            or isinstance(array_size, bool)
            or not isinstance(array_size, int)
            or not 1 <= array_size <= 2_147_483_647
            or isinstance(frame_count, bool)
            or not isinstance(frame_count, int)
            or not 1 <= frame_count <= ASSET_STREAM_MAX_PREFLIGHT_FRAMES
            or re.fullmatch(r"[0-9a-f]{64}", str(omitted.get("names_sha256")))
            is None
            or re.fullmatch(r"[0-9a-f]{64}", str(omitted.get("frames_sha256")))
            is None
        ):
            raise AssetStreamContractError(f"{label} is malformed")
        if reason == ASSET_STREAM_OMISSION_FRAME_COUNT:
            justified = frame_count > ASSET_STREAM_MAX_FRAMES
        elif reason == ASSET_STREAM_OMISSION_SLOT_COUNT:
            justified = (
                frame_count <= ASSET_STREAM_MAX_FRAMES
                and array_size > ASSET_STREAM_MAX_FRAMES
            )
        else:
            justified = (
                frame_count <= ASSET_STREAM_MAX_FRAMES
                and array_size <= ASSET_STREAM_MAX_FRAMES
            )
        if not justified:
            raise AssetStreamContractError(
                f"{label}.reason contradicts bound precedence"
            )
        previous_omitted = group_name
        seen_groups.add(group_name.casefold())
        seen_ids.add(gm_id)
    return payload, value, groups, omitted_groups


def _crc32_path(path: Path) -> str:
    checksum = 0
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            checksum = zlib.crc32(chunk, checksum)
    return f"{checksum & 0xFFFFFFFF:08x}"


def _asset_stream_validation_checks(
    root: Path,
    declared: dict[str, dict[str, Any]],
    expected_profile: dict[str, Any] | None,
) -> tuple[
    list[ValidationCheck], AssetBundleIndex | AssetBundleIndexV2 | None
]:
    checks: list[ValidationCheck] = []
    stream_paths = {
        path
        for path in declared
        if path.casefold().startswith("runtime/assetbundles/")
    }
    legacy_paths = find_legacy_atlas_outputs(declared)
    try:
        expected_backend = (
            parse_atlas_backend(expected_profile)
            if expected_profile is not None
            else None
        )
        profile_mode_ok = (
            expected_profile is None
            or bool(stream_paths) == (expected_backend is not None)
        )
        profile_detail = (
            "unbound profile"
            if expected_profile is None
            else f"selected={expected_backend is not None} files={len(stream_paths)}"
        )
    except AssetStreamContractError as exc:
        expected_backend = None
        profile_mode_ok = False
        profile_detail = str(exc)
    checks.append(_check("asset_stream.profile_mode", profile_mode_ok, profile_detail))
    checks.append(
        _check(
            "asset_stream.legacy_exclusive",
            not (stream_paths and legacy_paths),
            f"stream={sorted(stream_paths)} legacy={list(legacy_paths)}",
        )
    )
    if not stream_paths:
        return checks, None

    parsed_index: AssetBundleIndex | AssetBundleIndexV2 | None = None
    detail = ASSET_STREAM_INDEX_PATH
    try:
        index_payload, raw_index, raw_groups, _raw_omitted = _strict_stream_index_shape(
            root / ASSET_STREAM_INDEX_PATH
        )
        is_v2 = raw_index.get("schema") == BC7_INDEX_SCHEMA
        atlas_documents: dict[str, bytes] = {}
        for raw_group in raw_groups:
            bundle_relative = require_safe_relative_path(
                raw_group.get("bundle_path"), "index group bundle_path"
            )
            bundle_path = root.joinpath(*bundle_relative.split("/"))
            atlas_path = require_safe_relative_path(
                raw_group.get("atlas_asset_path"),
                "index group atlas_asset_path",
            )
            atlas_documents[atlas_path] = (
                validate_asset_bundle_payload_v2_external(bundle_path, raw_group)
                if is_v2
                else _validate_asset_bundle_payload(bundle_path, raw_group)
            )
        parsed_index = (
            parse_asset_bundle_index_v2(
                index_payload,
                atlas_documents=atlas_documents,
            )
            if is_v2
            else parse_asset_bundle_index(
                index_payload,
                atlas_documents=atlas_documents,
            )
        )
        if expected_profile is not None:
            validate_backend_output_exclusivity(
                expected_backend,
                declared,
                index=parsed_index,
            )
        artifacts: list[ContractBundleArtifact] = []
        for group in parsed_index.groups:
            bundle_path = root.joinpath(*group.bundle_path.split("/"))
            if (
                not bundle_path.is_file()
                or bundle_path.is_symlink()
                or bundle_path.stat().st_size != group.bundle_size_bytes
                or sha256_file(bundle_path) != group.bundle_sha256
                or _crc32_path(bundle_path) != group.bundle_crc32
            ):
                raise AssetStreamContractError(
                    f"bundle bytes differ from index: {group.bundle}"
                )
            artifacts.append(
                ContractBundleArtifact(
                    group.bundle,
                    group.bundle_path,
                    group.bundle_size_bytes,
                    group.bundle_sha256,
                    group.unity_hash128,
                )
            )
        if isinstance(parsed_index, AssetBundleIndexV2):
            report_v2 = AssetBundleBuildReportV2(
                schema=BC7_BUILD_REPORT_SCHEMA,
                success=True,
                verified=True,
                error="",
                build_id=parsed_index.build_id,
                build_input_sha256="0" * 64,
                unity=AssetStreamUnityIdentity(
                    parsed_index.unity.version,
                    parsed_index.unity.revision,
                ),
                build_target=ASSET_STREAM_BUILD_TARGET,
                build_options=tuple(ASSET_STREAM_BUILD_OPTIONS),
                textures=(),
                bundles=tuple(artifacts),
                index_sha256=parsed_index.file_sha256,
                quality_report_sha256=parsed_index.quality_report_sha256,
                file_sha256="0" * 64,
            )
            validate_bundle_output_records_v2(
                parsed_index, report_v2, declared.values()
            )
        else:
            report = AssetBundleBuildReport(
                schema=ASSET_STREAM_BUILD_REPORT_SCHEMA,
                success=True,
                error="",
                build_id=parsed_index.build_id,
                build_input_sha256="0" * 64,
                unity=AssetStreamUnityIdentity(
                    parsed_index.unity.version,
                    parsed_index.unity.revision,
                ),
                build_target=ASSET_STREAM_BUILD_TARGET,
                build_options=tuple(ASSET_STREAM_BUILD_OPTIONS),
                textures=(),
                bundles=tuple(artifacts),
                file_sha256="0" * 64,
            )
            validate_bundle_output_records(
                parsed_index, report, declared.values()
            )
        detail = (
            f"build_id={parsed_index.build_id} "
            f"groups={len(parsed_index.groups)} "
            f"omitted={len(parsed_index.vanilla_omitted_groups)}"
        )
    except (
        AssetStreamContractError,
        UnityAssetBundleError,
        KeyError,
        OSError,
        TypeError,
        ValueError,
    ) as exc:
        parsed_index = None
        detail = str(exc)
    checks.append(
        _check("asset_stream.contract", parsed_index is not None, detail)
    )
    return checks, parsed_index


def _ui_texture_v2_output_record_errors(
    parsed: UiTextureRuntimeManifest,
    declared: Mapping[str, Mapping[str, object]],
) -> list[str]:
    """Bind the parsed BC7 payload to the exact build-manifest records."""

    errors: list[str] = []
    expected_manifest_metadata = {
        "kind": "stronghold_europe_ui_textures_v2",
        "manifest_sha256": parsed.sha256,
        "entry_count": parsed.entry_count,
        "bundle_count": len(parsed.bundles),
        "declared_gpu_bytes": parsed.declared_gpu_bytes,
        "declared_resident_charge_bytes": (
            parsed.declared_resident_charge_bytes
        ),
        "source_manifest_sha256": parsed.source_manifest_sha256,
        "source_entry_set_sha256": parsed.source_entry_set_sha256,
        "quality_policy_sha256": parsed.quality_policy_sha256,
        "editor_source_sha256": parsed.editor_source_sha256,
    }
    expected_manifest_record: dict[str, object] = {
        "relative_path": UI_TEXTURE_V2_MANIFEST_PATH,
        "category": "runtime_ui_texture_contract",
        "size": parsed.size_bytes,
        "sha256": parsed.sha256,
        "width": None,
        "height": None,
        "source_reference": UI_TEXTURE_MANIFEST_SOURCE_REFERENCE,
        "lost_alpha": None,
        "metadata": expected_manifest_metadata,
    }
    if declared.get(UI_TEXTURE_V2_MANIFEST_PATH) != expected_manifest_record:
        errors.append("UI v2 manifest OutputRecord changed")

    manifest_category_paths = {
        relative
        for relative, record in declared.items()
        if record.get("category") == "runtime_ui_texture_contract"
    }
    if manifest_category_paths != {UI_TEXTURE_V2_MANIFEST_PATH}:
        errors.append("UI v2 manifest OutputRecord path/category set changed")

    expected_bundle_records: dict[str, dict[str, object]] = {}
    for bundle in parsed.bundles:
        bundle_name = PurePosixPath(bundle.relative_path).name
        expected_bundle_records[bundle.relative_path] = {
            "relative_path": bundle.relative_path,
            "category": "ui_texture_asset_bundle",
            "size": bundle.size_bytes,
            "sha256": bundle.sha256,
            "width": None,
            "height": None,
            "source_reference": (
                f"unity-ui-assetbundle:{bundle.entry_id}:{bundle_name}"
            ),
            "lost_alpha": None,
            "metadata": {
                "kind": UI_BACKEND_KIND,
                "entry_id": bundle.entry_id,
                "bundle": bundle_name,
                "unity_hash128": bundle.unity_hash128,
                "crc32": bundle.crc32,
            },
        }

    declared_bundle_paths = {
        relative
        for relative, record in declared.items()
        if relative.casefold().startswith(UI_TEXTURE_BUNDLE_PREFIX.casefold())
        or record.get("category") == "ui_texture_asset_bundle"
    }
    if declared_bundle_paths != set(expected_bundle_records):
        errors.append("UI v2 bundle OutputRecord path set changed")
    for relative, expected in expected_bundle_records.items():
        if declared.get(relative) != expected:
            errors.append(f"UI v2 bundle OutputRecord changed: {relative}")
    return errors


def _active_ui_png_paths(
    root: Path,
    declared: Mapping[str, Mapping[str, object]],
) -> list[str]:
    active = {
        relative
        for relative in declared
        if relative.casefold().startswith("override/assets/gui/")
        and relative.casefold().endswith(".png")
    }
    gui_root = root / "Override" / "Assets" / "GUI"
    if gui_root.is_dir() and not gui_root.is_symlink():
        active.update(
            path.relative_to(root).as_posix()
            for path in gui_root.rglob("*")
            if path.suffix.casefold() == ".png"
            and (path.is_file() or path.is_symlink())
        )
    return sorted(active, key=str.casefold)


def _mod_logo_validation_check(
    guid: str,
    declared: Mapping[str, Mapping[str, object]],
    *,
    ui_v2_active_and_valid: bool,
) -> ValidationCheck:
    """Require exactly one direct-PNG or verified UI-v2 owner for the logo."""

    relative = f"Override/Assets/GUI/Sprites/{guid}.png"
    direct = relative in declared
    streamed = False
    stream_detail = "inactive"
    if ui_v2_active_and_valid:
        try:
            project_root = Path(__file__).resolve().parents[2]
            source_manifest = load_ui_texture_source_manifest(
                project_root / UI_TEXTURE_SOURCE_CONFIG_PATH
            )
            matches = [
                entry
                for entry in source_manifest.entries
                if entry.source_kind == "profile_output"
                and entry.source == relative
                and entry.noesis_path == relative.removeprefix("Override/")
            ]
            streamed = len(matches) == 1
            stream_detail = f"matches={len(matches)}"
        except (OSError, UiAssetBundleError, ValueError) as exc:
            stream_detail = str(exc)
    return _check(
        "mod.logo",
        direct != streamed,
        f"path={relative} direct={direct} streamed={streamed} "
        f"stream_detail={stream_detail}",
    )


def _ui_texture_stream_validation_check(
    root: Path,
    declared: dict[str, dict[str, Any]],
    runtime_metadata: Mapping[str, object],
) -> ValidationCheck:
    raw_enabled = runtime_metadata.get("ui_texture_streaming_enabled")
    expected_digest = runtime_metadata.get("ui_texture_manifest_sha256")
    enabled_shape_ok = raw_enabled is None or type(raw_enabled) is bool
    enabled = raw_enabled is True

    legacy_declared = any(
        relative.casefold() == UI_TEXTURE_V1_MANIFEST_PATH.casefold()
        for relative in declared
    )
    legacy_path = root.joinpath(*PurePosixPath(UI_TEXTURE_V1_MANIFEST_PATH).parts)
    legacy_present = legacy_declared or os.path.lexists(legacy_path)
    v2_declared = any(
        relative.casefold() == UI_TEXTURE_V2_MANIFEST_PATH.casefold()
        for relative in declared
    )
    v2_path = root.joinpath(*PurePosixPath(UI_TEXTURE_V2_MANIFEST_PATH).parts)
    bundle_root = root.joinpath(
        *PurePosixPath(UI_TEXTURE_BUNDLE_PREFIX.rstrip("/")).parts
    )
    declared_bundles = {
        relative
        for relative, entry in declared.items()
        if relative.casefold().startswith(UI_TEXTURE_BUNDLE_PREFIX.casefold())
        or entry.get("category") == "ui_texture_asset_bundle"
    }

    if not enabled:
        payload_present = (
            legacy_present
            or v2_declared
            or os.path.lexists(v2_path)
            or bool(declared_bundles)
            or os.path.lexists(bundle_root)
        )
        ok = (
            enabled_shape_ok
            and expected_digest in {None, ""}
            and not payload_present
        )
        return _check(
            "runtime.ui_texture_stream_manifest",
            ok,
            "enabled=false "
            f"legacy={legacy_present} v2={v2_declared or os.path.lexists(v2_path)} "
            f"bundles={len(declared_bundles)} digest={expected_digest!r}",
        )

    if (
        not enabled_shape_ok
        or not isinstance(expected_digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", expected_digest) is None
    ):
        return _check(
            "runtime.ui_texture_stream_manifest",
            False,
            "enabled UI v2 runtime metadata is invalid",
        )
    if legacy_present:
        return _check(
            "runtime.ui_texture_stream_manifest",
            False,
            "removed Runtime/ui-textures-v1.tsv is still active",
        )
    active_pngs = _active_ui_png_paths(root, declared)
    if active_pngs:
        return _check(
            "runtime.ui_texture_stream_manifest",
            False,
            f"UI v2 backend forbids active GUI PNGs: {active_pngs}",
        )

    try:
        project_root = Path(__file__).resolve().parents[2]
        source_manifest = load_ui_texture_source_manifest(
            project_root / UI_TEXTURE_SOURCE_CONFIG_PATH
        )
        quality_policy = load_ui_quality_policy(
            project_root / UI_TEXTURE_QUALITY_POLICY_PATH
        )
        editor_source = project_root / UI_TEXTURE_EDITOR_SOURCE_PATH
        if (
            len(source_manifest.entries) != UI_TEXTURE_EXPECTED_ENTRY_COUNT
            or not editor_source.is_file()
            or editor_source.is_symlink()
        ):
            raise ValueError("canonical UI v2 project inputs changed")
        editor_source_sha256 = sha256_file(editor_source)
        parsed = parse_ui_texture_runtime_manifest_v2(
            root,
            expected_source_manifest_sha256=source_manifest.sha256,
            expected_quality_policy_sha256=quality_policy.sha256,
            expected_editor_source_sha256=editor_source_sha256,
            expected_entry_count=UI_TEXTURE_EXPECTED_ENTRY_COUNT,
            max_resident_bytes=UI_TEXTURE_MAX_RESIDENT_BYTES,
        )
        if (
            parsed.entry_count != UI_TEXTURE_EXPECTED_ENTRY_COUNT
            or len(parsed.entries) != UI_TEXTURE_EXPECTED_ENTRY_COUNT
            or len(parsed.bundles) != UI_TEXTURE_EXPECTED_ENTRY_COUNT
            or parsed.source_entry_set_sha256
            != source_manifest.entry_set_sha256
        ):
            raise ValueError("UI v2 entry count or entry-set provenance changed")
        if parsed.sha256 != expected_digest:
            raise ValueError("UI v2 manifest is not bound to the runtime DLL")
        record_errors = _ui_texture_v2_output_record_errors(parsed, declared)
        if record_errors:
            raise ValueError("; ".join(record_errors))
        ok = True
        detail = (
            f"entries={parsed.entry_count} bundles={len(parsed.bundles)} "
            f"gpu={parsed.declared_gpu_bytes} "
            f"resident={parsed.declared_resident_charge_bytes} "
            f"sha256={parsed.sha256}"
        )
    except (
        OSError,
        RuntimeBuildError,
        UiAssetBundleError,
        ValueError,
    ) as exc:
        ok = False
        detail = str(exc)
    return _check("runtime.ui_texture_stream_manifest", ok, detail)


def validate_mod(
    mod_root: Path,
    *,
    expected_profile_id: str | None = None,
    expected_source_build_id: str | None = None,
    expected_target_build_id: str | None = None,
    expected_profile: dict[str, Any] | None = None,
) -> list[ValidationCheck]:
    root = mod_root.resolve()
    checks: list[ValidationCheck] = []
    manifest_path = root / "build-manifest.json"
    info_path = root / "info.json"
    checks.append(_check("mod.root", root.is_dir(), str(root)))
    checks.append(_check("mod.build_manifest", manifest_path.is_file(), str(manifest_path)))
    checks.append(_check("mod.info", info_path.is_file(), str(info_path)))
    if not manifest_path.is_file() or not info_path.is_file():
        return checks

    manifest, manifest_json_detail = _read_json_object(manifest_path)
    info, info_json_detail = _read_json_object(info_path)
    checks.append(
        _check(
            "manifest.json_object",
            manifest is not None,
            manifest_json_detail,
        )
    )
    checks.append(
        _check("info.json_object", info is not None, info_json_detail)
    )
    if manifest is None or info is None:
        return checks
    manifest_shape_ok, manifest_shape_detail = _static_manifest_shape(manifest)
    checks.append(
        _check(
            "manifest.input_shape",
            manifest_shape_ok,
            manifest_shape_detail,
        )
    )
    if not manifest_shape_ok:
        return checks
    actual_profile_id = manifest["profile_id"]
    validation_profile_id = (
        expected_profile_id
        if expected_profile_id is not None
        else actual_profile_id
    )
    if expected_profile is not None:
        expected_document_id = expected_profile.get("id")
        checks.append(
            _check(
                "profile.document_identity",
                isinstance(expected_document_id, str)
                and expected_document_id == validation_profile_id,
                f"expected={validation_profile_id!r} "
                f"document={expected_document_id!r}",
            )
        )
    for check_name, field_name, expected in (
        ("manifest.profile_identity", "profile_id", expected_profile_id),
        (
            "manifest.source_build_identity",
            "source_build_id",
            expected_source_build_id,
        ),
        (
            "manifest.target_build_identity",
            "target_build_id",
            expected_target_build_id,
        ),
    ):
        actual = manifest[field_name]
        checks.append(
            _check(
                check_name,
                expected is None or actual == expected,
                f"expected={expected!r} actual={actual!r}",
            )
        )
    checks.append(_check("manifest.schema", manifest.get("schema_version") == 1, str(manifest.get("schema_version"))))
    checks.append(_check("info.manifest_type", type(info.get("Manifest")) is int and info.get("Manifest") == 0, str(info.get("Manifest"))))
    checks.append(_check("info.guid", isinstance(info.get("GUID"), str) and bool(info.get("GUID")), str(info.get("GUID"))))
    checks.append(_check("info.version", isinstance(info.get("Version"), str) and bool(info.get("Version")), str(info.get("Version"))))
    checks.append(_check("info.matches_manifest", info == manifest.get("mod_info"), "info.json equals embedded manifest metadata"))

    raw_outputs = manifest.get("outputs", [])
    outputs_are_list = isinstance(raw_outputs, list)
    checks.append(
        _check("manifest.outputs_list", outputs_are_list, type(raw_outputs).__name__)
    )
    output_entries = (
        [
            entry
            for entry in raw_outputs
            if isinstance(entry, dict) and isinstance(entry.get("relative_path"), str)
        ]
        if outputs_are_list
        else []
    )
    output_paths = [entry["relative_path"] for entry in output_entries]
    portable_paths = all(_portable_manifest_path(path) for path in output_paths)
    exact_unique = len(output_paths) == len(set(output_paths))
    casefold_unique = len(output_paths) == len(
        {path.casefold() for path in output_paths}
    )
    checks.append(
        _check(
            "manifest.output_paths_portable",
            outputs_are_list
            and portable_paths
            and len(output_entries) == len(raw_outputs),
            f"valid={len(output_entries)} total={len(raw_outputs) if outputs_are_list else 0}",
        )
    )
    checks.append(
        _check(
            "manifest.output_paths_exact_unique",
            exact_unique,
            f"paths={len(output_paths)} unique={len(set(output_paths))}",
        )
    )
    checks.append(
        _check(
            "manifest.output_paths_windows_unique",
            casefold_unique,
            f"paths={len(output_paths)} unique={len({path.casefold() for path in output_paths})}",
        )
    )
    declared: dict[str, dict[str, Any]] = {}
    for entry in output_entries:
        declared.setdefault(entry["relative_path"], entry)
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name != "build-manifest.json"
    }
    actual_casefold_unique = len(actual) == len(
        {relative.casefold() for relative in actual}
    )
    checks.append(
        _check(
            "output.file_set_windows_unique",
            actual_casefold_unique,
            f"paths={len(actual)} unique={len({relative.casefold() for relative in actual})}",
        )
    )
    checks.append(
        _check(
            "manifest.complete_file_set",
            set(declared) == actual,
            f"declared={len(declared)} actual={len(actual)} missing={sorted(set(declared)-actual)} extra={sorted(actual-set(declared))}",
        )
    )
    expected_directories: set[str] = set()
    for relative in set(declared) | {"build-manifest.json"}:
        parent = PurePosixPath(relative).parent
        while parent.parts:
            expected_directories.add(parent.as_posix())
            parent = parent.parent
    actual_directories = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_dir()
    }
    checks.append(
        _check(
            "manifest.complete_directory_set",
            expected_directories == actual_directories,
            "expected="
            f"{len(expected_directories)} actual={len(actual_directories)} "
            f"missing={sorted(expected_directories - actual_directories)} "
            f"extra={sorted(actual_directories - expected_directories)}",
        )
    )

    runtime_dll_entry = declared.get(RUNTIME_DLL_PATH)
    runtime_contract_entry = declared.get(RUNTIME_CONTRACT_PATH)
    runtime_roster_entry = declared.get(RUNTIME_ROSTER_CONTRACT_PATH)
    runtime_fortification_entry = declared.get(
        RUNTIME_FORTIFICATION_CONTRACT_PATH
    )
    runtime_contract_path = root / RUNTIME_CONTRACT_PATH
    runtime_contract_digest = (
        sha256_file(runtime_contract_path)
        if runtime_contract_path.is_file()
        else None
    )
    checks.append(
        _check(
            "runtime.companion_contract_pair",
            (runtime_dll_entry is None) == (runtime_contract_entry is None),
            f"dll={runtime_dll_entry is not None} contract={runtime_contract_entry is not None}",
        )
    )
    checks.append(
        _check(
            "runtime.companion_dll_source",
            runtime_dll_entry is None
            or runtime_dll_entry.get("source_reference")
            == RUNTIME_DLL_SOURCE_REFERENCE,
            str(
                runtime_dll_entry.get("source_reference")
                if runtime_dll_entry is not None
                else None
            ),
        )
    )
    checks.append(
        _check(
            "runtime.companion_contract_source",
            runtime_contract_entry is None
            or runtime_contract_entry.get("source_reference")
            == RUNTIME_CONTRACT_SOURCE_REFERENCE,
            str(
                runtime_contract_entry.get("source_reference")
                if runtime_contract_entry is not None
                else None
            ),
        )
    )
    runtime_dll_metadata = (
        runtime_dll_entry.get("metadata")
        if isinstance(runtime_dll_entry, dict)
        and isinstance(runtime_dll_entry.get("metadata"), dict)
        else {}
    )
    asset_stream_checks, parsed_asset_stream_index = (
        _asset_stream_validation_checks(root, declared, expected_profile)
    )
    checks.extend(asset_stream_checks)
    ui_texture_check = _ui_texture_stream_validation_check(
        root, declared, runtime_dll_metadata
    )
    checks.append(ui_texture_check)
    asset_stream_declared = any(
        relative.casefold().startswith("runtime/assetbundles/")
        for relative in declared
    )
    runtime_source_digest, runtime_source_detail = _runtime_source_set_identity()
    checks.append(
        _check(
            "runtime.source_set_inputs",
            runtime_dll_entry is None or runtime_source_digest is not None,
            runtime_source_detail,
        )
    )
    raw_roster_selection = runtime_dll_metadata.get("unit_roster_names")
    runtime_roster_enabled = (
        raw_roster_selection if isinstance(raw_roster_selection, bool) else None
    )
    raw_fortification_selection = runtime_dll_metadata.get("fortifications")
    runtime_fortifications_enabled = (
        raw_fortification_selection
        if isinstance(raw_fortification_selection, bool)
        else None
    )
    fortification_present = runtime_fortification_entry is not None
    checks.append(
        _check(
            "runtime.fortifications_selection_shape",
            runtime_dll_entry is None
            or _runtime_fortification_selection_metadata_ok(
                runtime_dll_metadata
            ),
            "selected=" + repr(runtime_fortifications_enabled)
            + " catalog="
            + repr(
                runtime_dll_metadata.get("fortification_catalog_sha256")
            ),
        )
    )
    checks.append(
        _check(
            "runtime.fortification_artifact_presence",
            fortification_present
            == (runtime_fortifications_enabled is True),
            f"selected={runtime_fortifications_enabled} "
            f"present={fortification_present}",
        )
    )
    roster_present = runtime_roster_entry is not None
    checks.append(
        _check(
            "runtime.roster_selection_shape",
            runtime_dll_entry is None or runtime_roster_enabled is not None,
            repr(raw_roster_selection),
        )
    )
    checks.append(
        _check(
            "runtime.roster_artifact_presence",
            roster_present == (runtime_roster_enabled is True),
            f"selected={runtime_roster_enabled} present={roster_present}",
        )
    )
    locale_paths_present = {
        relative
        for relative, entry in declared.items()
        if relative.casefold().startswith("locales/")
        or entry.get("category") == "locale_override"
    }
    checks.append(
        _check(
            "runtime.roster_locale_exclusive",
            not (runtime_roster_enabled is True and locale_paths_present),
            f"selected={runtime_roster_enabled} locales={sorted(locale_paths_present)}",
        )
    )
    checks.append(
        _check(
            "runtime.roster_profile_identity_bound",
            expected_profile_id is not None
            or runtime_roster_enabled is not True
            or actual_profile_id == "europe-roster-runtime-canary",
            f"expected={expected_profile_id!r} actual={actual_profile_id!r} "
            f"selected={runtime_roster_enabled!r}",
        )
    )
    roster_canary = validation_profile_id == "europe-roster-runtime-canary"
    if roster_canary:
        roster_output_contract_ok, roster_output_contract_detail = (
            _runtime_roster_canary_output_contract(declared)
        )
        checks.append(
            _check(
                "runtime.roster_canary_selection",
                runtime_roster_enabled is True,
                f"selected={runtime_roster_enabled}",
            )
        )
        checks.append(
            _check(
                "runtime.roster_isolated_output_set",
                set(declared) == _RUNTIME_ROSTER_ISOLATED_OUTPUTS,
                f"actual={sorted(declared)}",
            )
        )
        checks.append(
            _check(
                "runtime.roster_isolated_output_contract",
                roster_output_contract_ok,
                roster_output_contract_detail,
            )
        )

    parsed_runtime_roster: dict[str, Any] | None = None
    if roster_present:
        roster_path = root / RUNTIME_ROSTER_CONTRACT_PATH
        roster_parse_detail = RUNTIME_ROSTER_CONTRACT_PATH
        try:
            parsed_runtime_roster = _parse_roster_runtime_contract(roster_path)
            roster_parse_detail = (
                f"entries={parsed_runtime_roster['entry_count']} "
                f"hud={parsed_runtime_roster['hud_control_count']} "
                f"sha256={parsed_runtime_roster['manifest_sha256']}"
            )
        except (OSError, ValueError, RosterRuntimeContractError) as exc:
            roster_parse_detail = str(exc)
        checks.append(
            _check(
                "runtime.roster_contract_schema",
                parsed_runtime_roster is not None,
                roster_parse_detail,
            )
        )
        checks.append(
            _check(
                "runtime.roster_contract_category",
                runtime_roster_entry.get("category")
                == RUNTIME_ROSTER_CONTRACT_CATEGORY,
                str(runtime_roster_entry.get("category")),
            )
        )
        checks.append(
            _check(
                "runtime.roster_contract_source",
                runtime_roster_entry.get("source_reference")
                == RUNTIME_ROSTER_SOURCE_REFERENCE,
                str(runtime_roster_entry.get("source_reference")),
            )
        )
        checks.append(
            _check(
                "runtime.roster_contract_metadata",
                _runtime_roster_metadata_matches(
                    runtime_roster_entry.get("metadata"),
                    parsed_runtime_roster,
                ),
                json.dumps(runtime_roster_entry.get("metadata"), sort_keys=True),
            )
        )

    if fortification_present:
        fortification_path = root / RUNTIME_FORTIFICATION_CONTRACT_PATH
        expected_payload, expected_metadata, expected_detail = (
            _runtime_fortification_contract_expected()
        )
        try:
            actual_payload = fortification_path.read_bytes()
        except OSError as exc:
            actual_payload = None
            payload_detail = str(exc)
        else:
            payload_detail = (
                f"size={len(actual_payload)} "
                f"sha256={hashlib.sha256(actual_payload).hexdigest()}"
            )
        checks.append(
            _check(
                "runtime.fortification_contract_source_pins",
                expected_payload is not None and expected_metadata is not None,
                expected_detail,
            )
        )
        checks.append(
            _check(
                "runtime.fortification_contract_schema",
                actual_payload is not None
                and expected_payload is not None
                and actual_payload == expected_payload,
                payload_detail,
            )
        )
        checks.append(
            _check(
                "runtime.fortification_contract_category",
                runtime_fortification_entry.get("category")
                == RUNTIME_FORTIFICATION_CONTRACT_CATEGORY,
                str(runtime_fortification_entry.get("category")),
            )
        )
        checks.append(
            _check(
                "runtime.fortification_contract_source",
                runtime_fortification_entry.get("source_reference")
                == RUNTIME_FORTIFICATION_SOURCE_REFERENCE,
                str(runtime_fortification_entry.get("source_reference")),
            )
        )
        checks.append(
            _check(
                "runtime.fortification_contract_metadata",
                _runtime_fortification_metadata_matches(
                    runtime_fortification_entry.get("metadata"),
                    expected_metadata,
                ),
                json.dumps(
                    runtime_fortification_entry.get("metadata"),
                    sort_keys=True,
                ),
            )
        )
        actual_catalog_digest = (
            hashlib.sha256(actual_payload).hexdigest()
            if actual_payload is not None
            else None
        )
        checks.append(
            _check(
                "runtime.fortification_contract_dll_binding",
                actual_catalog_digest is not None
                and runtime_dll_metadata.get(
                    "fortification_catalog_sha256"
                )
                == actual_catalog_digest,
                f"dll={runtime_dll_metadata.get('fortification_catalog_sha256')!r} "
                f"catalog={actual_catalog_digest!r}",
            )
        )

    image_sizes: dict[str, tuple[int, int]] = {}
    for relative, entry in sorted(declared.items()):
        portable = _portable_manifest_path(relative)
        checks.append(
            _check(f"path.portable.{relative}", portable, relative)
        )
        if not portable:
            continue
        path = (root / Path(relative)).resolve()
        inside = root in path.parents
        checks.append(_check(f"path.inside.{relative}", inside, str(path)))
        if not inside or not path.is_file():
            checks.append(_check(f"file.exists.{relative}", False, str(path)))
            continue
        suffix = path.suffix.lower()
        runtime_dll_allowed = (
            relative == RUNTIME_DLL_PATH
            and entry.get("category") == RUNTIME_DLL_CATEGORY
        )
        checks.append(
            _check(
                f"file.safe_suffix.{relative}",
                suffix not in FORBIDDEN_SUFFIXES or runtime_dll_allowed,
                (
                    "exact allowlisted net481 runtime companion"
                    if runtime_dll_allowed
                    else suffix
                ),
            )
        )
        checks.append(
            _check(
                f"file.size.{relative}",
                path.stat().st_size == int(entry["size"]),
                f"expected={entry['size']} actual={path.stat().st_size}",
            )
        )
        digest = sha256_file(path)
        checks.append(
            _check(
                f"file.sha256.{relative}",
                digest == entry["sha256"],
                digest,
            )
        )
        if entry.get("lost_alpha") is not None:
            checks.append(
                _check(
                    f"image.no_alpha_loss.{relative}",
                    int(entry["lost_alpha"]) == 0,
                    str(entry["lost_alpha"]),
                )
            )
        if suffix == ".png":
            try:
                with Image.open(path) as image:
                    image.load()
                    size = image.size
                    mode = image.mode
                    image_format = image.format
            except (
                OSError,
                UnidentifiedImageError,
                Image.DecompressionBombError,
                ValueError,
            ) as exc:
                checks.append(
                    _check(f"image.decode.{relative}", False, str(exc))
                )
            else:
                image_sizes[relative] = size
                expected = (int(entry["width"]), int(entry["height"]))
                checks.append(
                    _check(
                        f"image.decode.{relative}",
                        image_format == "PNG",
                        str(image_format),
                    )
                )
                checks.append(_check(f"image.geometry.{relative}", size == expected, f"expected={expected} actual={size}"))
                checks.append(_check(f"image.mode.{relative}", mode == "RGBA", mode))
        if suffix == ".webm":
            signature = path.read_bytes()[:4]
            checks.append(_check(f"video.ebml.{relative}", signature == b"\x1aE\xdf\xa3", signature.hex()))
        if suffix == ".dll" and runtime_dll_allowed:
            metadata = entry.get("metadata")
            runtime_metadata = metadata if isinstance(metadata, dict) else {}
            metadata_ok = (
                set(runtime_metadata) == _RUNTIME_DLL_METADATA_KEYS
                and entry.get("source_reference")
                == RUNTIME_DLL_SOURCE_REFERENCE
                and runtime_metadata.get("kind") == "net481_bepinex_runtime_companion"
                and runtime_metadata.get("plugin_id") == RUNTIME_PLUGIN_ID
                and runtime_metadata.get("assembly_name") == RUNTIME_ASSEMBLY_NAME
                and runtime_metadata.get("assembly_version") == RUNTIME_ASSEMBLY_VERSION
                and runtime_metadata.get("target_framework") == "net481"
                and runtime_metadata.get("runtime_prerequisite_config_id")
                == "local-shcde-2.80-shcdese-2.11-net481-win-x64"
                and runtime_metadata.get("runtime_prerequisite_mvids")
                == RUNTIME_PREREQUISITE_MVIDS
                and runtime_metadata.get("manifest_sha256")
                == runtime_contract_digest
                and isinstance(runtime_metadata.get("unit_roster_names"), bool)
                and isinstance(runtime_metadata.get("farm_placement"), bool)
                and isinstance(runtime_metadata.get("worker_militia"), bool)
                and isinstance(runtime_metadata.get("diplomacy"), bool)
                and _diplomacy_rules_metadata_ok(
                    runtime_metadata.get("diplomacy_rules"),
                    runtime_metadata.get("diplomacy"),
                )
                and _runtime_fortification_selection_metadata_ok(
                    runtime_metadata
                )
                and isinstance(runtime_metadata.get("dock_placement"), bool)
                and _dock_placement_rules_metadata_ok(
                    runtime_metadata.get("dock_placement_rules"),
                    runtime_metadata.get("dock_placement"),
                )
                and runtime_metadata.get("runtime_source_set_sha256")
                == runtime_source_digest
                and _runtime_streaming_metadata_ok(runtime_metadata)
            )
            checks.append(
                _check(
                    "runtime.dll_manifest_contract",
                    metadata_ok,
                    json.dumps(runtime_metadata, sort_keys=True),
                )
            )
            pe_clr_ok, pe_clr_detail = _pe_clr_header(path)
            checks.append(
                _check("runtime.dll_pe_clr", pe_clr_ok, pe_clr_detail)
            )
            identity = _managed_assembly_identity(path) if pe_clr_ok else None
            checks.append(
                _check(
                    "runtime.dll_assembly_identity",
                    identity == (RUNTIME_ASSEMBLY_NAME, RUNTIME_ASSEMBLY_VERSION),
                    str(identity),
                )
            )
            attestation = (
                _managed_assembly_attestation(path) if pe_clr_ok else None
            )
            expected_attestation = _runtime_assembly_attestation_expected(
                manifest_sha256=runtime_contract_digest,
                source_build_id=(
                    "local-sh1de-unity-2021.3.27f1-2025-01-20"
                ),
                target_build_id="local-shcde-2.80-unity-2021.3.45f2",
                roster_enabled=runtime_roster_enabled is True,
                runtime_source_sha256=runtime_source_digest,
                worker_militia_enabled=(
                    runtime_metadata.get("worker_militia") is True
                ),
                fortifications_enabled=(
                    runtime_metadata.get("fortifications") is True
                ),
                fortification_catalog_sha256=str(
                    runtime_metadata.get(
                        "fortification_catalog_sha256", ""
                    )
                ),
                asset_stream_enabled=(
                    runtime_metadata.get("asset_stream_enabled") is True
                ),
                asset_stream_index_sha256=str(
                    runtime_metadata.get("asset_stream_index_sha256", "")
                ),
                ui_texture_streaming_enabled=(
                    runtime_metadata.get("ui_texture_streaming_enabled") is True
                ),
                ui_texture_manifest_sha256=str(
                    runtime_metadata.get("ui_texture_manifest_sha256", "")
                ),
                pcm_streaming_enabled=(
                    runtime_metadata.get("pcm_streaming_enabled") is True
                ),
                pcm_stream_manifest_sha256=str(
                    runtime_metadata.get("pcm_stream_manifest_sha256", "")
                ),
            )
            attestation_ok = attestation == expected_attestation
            checks.append(
                _check(
                    "runtime.dll_embedded_attestation",
                    attestation_ok,
                    json.dumps(attestation or {}, sort_keys=True),
                )
            )

    sprite_prefix = "Override/Sprites/"
    sprite_files = [relative for relative in declared if relative.startswith(sprite_prefix)]
    checks.append(
        _check(
            "sprites.flat_directory",
            all("/" not in relative[len(sprite_prefix):] for relative in sprite_files),
            f"count={len(sprite_files)}",
        )
    )
    for relative in sprite_files:
        if not relative.endswith("_m.png"):
            continue
        main = relative[:-6] + ".png"
        checks.append(_check(f"mask.main_exists.{relative}", main in declared, main))
        if main in image_sizes and relative in image_sizes:
            checks.append(
                _check(
                    f"mask.geometry.{relative}",
                    image_sizes[main] == image_sizes[relative],
                    f"main={image_sizes[main]} mask={image_sizes[relative]}",
                )
            )

    checks.extend(
        _review_individual_validation_checks(
            root,
            declared,
            image_sizes,
            streaming=asset_stream_declared,
        )
    )
    if not asset_stream_declared:
        checks.extend(_atlas_validation_checks(root, declared, image_sizes))
    if expected_profile is not None:
        if not asset_stream_declared:
            checks.extend(
                _profile_atlas_contract_checks(expected_profile, declared)
            )
        checks.extend(
            _check(item.name, item.ok, item.detail)
            for item in profile_output_contract_checks(
                root, expected_profile, manifest, declared
            )
        )
    checks.extend(_locale_validation_checks(root, declared, actual))

    parsed_runtime_contract: dict[str, Any] | None = None
    if runtime_contract_entry is not None:
        metadata = runtime_contract_entry.get("metadata")
        contract_metadata = metadata if isinstance(metadata, dict) else {}
        contract_digest = runtime_contract_digest or "missing"
        dll_metadata = (
            runtime_dll_entry.get("metadata")
            if isinstance(runtime_dll_entry, dict)
            and isinstance(runtime_dll_entry.get("metadata"), dict)
            else {}
        )
        contract_ok = (
            runtime_contract_entry.get("category") == "runtime_contract"
            and runtime_contract_entry.get("source_reference")
            == RUNTIME_CONTRACT_SOURCE_REFERENCE
            and set(contract_metadata) == _RUNTIME_CONTRACT_METADATA_KEYS
            and contract_metadata.get("kind") == "stronghold_europe_runtime_contract_v1"
            and contract_metadata.get("plugin_id") == RUNTIME_PLUGIN_ID
            and contract_metadata.get("track_count") == 17
            and contract_metadata.get("manifest_sha256") == contract_digest
            and dll_metadata.get("manifest_sha256") == contract_digest
        )
        checks.append(
            _check(
                "runtime.contract_binding",
                contract_ok,
                f"sha256={contract_digest}",
            )
        )
        try:
            parsed_runtime_contract = parse_runtime_contract(runtime_contract_path)
            parse_detail = (
                f"tracks={len(parsed_runtime_contract['tracks'])} "
                f"audio={parsed_runtime_contract['audio_payload']} "
                f"foliage={parsed_runtime_contract['foliage_tree_apple']}"
            )
        except (RuntimeBuildError, OSError, ValueError) as exc:
            parsed_runtime_contract = None
            parse_detail = str(exc)
        checks.append(
            _check(
                "runtime.contract_schema",
                parsed_runtime_contract is not None,
                parse_detail,
            )
        )

        if parsed_runtime_contract is not None:
            checks.append(_check(
                "runtime.contract_build_identity",
                parsed_runtime_contract["source_build_id"] == manifest["source_build_id"]
                and parsed_runtime_contract["target_build_id"] == manifest["target_build_id"],
                "Runtime contract must match this build's recorded inputs",
            ))
            feature_metadata_ok = (
                contract_metadata.get("audio_payload")
                is parsed_runtime_contract["audio_payload"]
                and contract_metadata.get("foliage_tree_apple")
                is parsed_runtime_contract["foliage_tree_apple"]
                and contract_metadata.get("track_count")
                == len(parsed_runtime_contract["tracks"])
            )
            checks.append(
                _check(
                    "runtime.contract_feature_metadata",
                    feature_metadata_ok,
                    json.dumps(contract_metadata, sort_keys=True),
                )
            )
            if roster_canary:
                checks.append(
                    _check(
                        "runtime.roster_canary_features",
                        parsed_runtime_contract["audio_payload"] is False
                        and parsed_runtime_contract["foliage_tree_apple"] is False,
                        f"audio={parsed_runtime_contract['audio_payload']} "
                        f"foliage={parsed_runtime_contract['foliage_tree_apple']}",
                    )
                )
            pcm_streaming = (
                runtime_dll_metadata.get("pcm_streaming_enabled") is True
            )
            expected_music = (
                {
                    f"Override/Sounds/Music/{track['output_file']}"
                    for track in parsed_runtime_contract["tracks"]
                }
                if parsed_runtime_contract["audio_payload"] and not pcm_streaming
                else set()
            )
            actual_music = {
                relative
                for relative in declared
                if relative.startswith("Override/Sounds/Music/")
            }
            checks.append(
                _check(
                    "runtime.audio_payload_file_set",
                    actual_music == expected_music,
                    f"expected={len(expected_music)} actual={len(actual_music)} "
                    f"missing={sorted(expected_music - actual_music)} "
                    f"extra={sorted(actual_music - expected_music)}",
                )
            )
            expected_pcm = (
                {
                    f"Runtime/Audio/{track['output_file']}"
                    for track in parsed_runtime_contract["tracks"]
                }
                | {"Runtime/Audio/pcm-stream-manifest.tsv"}
                if parsed_runtime_contract["audio_payload"] and pcm_streaming
                else set()
            )
            actual_pcm = {
                relative
                for relative in declared
                if relative.startswith("Runtime/Audio/")
            }
            checks.append(
                _check(
                    "runtime.pcm_stream_file_set",
                    actual_pcm == expected_pcm,
                    f"expected={len(expected_pcm)} actual={len(actual_pcm)} "
                    f"missing={sorted(expected_pcm-actual_pcm)} "
                    f"extra={sorted(actual_pcm-expected_pcm)}",
                )
            )
            pcm_manifest_relative = "Runtime/Audio/pcm-stream-manifest.tsv"
            pcm_manifest_entry = declared.get(pcm_manifest_relative)
            expected_pcm_manifest = _pcm_stream_manifest_text(
                parsed_runtime_contract["tracks"]
            ).encode("utf-8")
            pcm_manifest_path = root / pcm_manifest_relative
            pcm_manifest_digest = (
                hashlib.sha256(expected_pcm_manifest).hexdigest()
                if expected_pcm
                else ""
            )
            pcm_manifest_metadata = (
                pcm_manifest_entry.get("metadata")
                if isinstance(pcm_manifest_entry, dict)
                and isinstance(pcm_manifest_entry.get("metadata"), dict)
                else None
            )
            pcm_manifest_ok = (
                not expected_pcm
                and pcm_manifest_entry is None
                and runtime_dll_metadata.get("pcm_stream_manifest_sha256") == ""
            ) or (
                bool(expected_pcm)
                and isinstance(pcm_manifest_entry, dict)
                and pcm_manifest_path.is_file()
                and pcm_manifest_path.read_bytes() == expected_pcm_manifest
                and pcm_manifest_entry.get("sha256") == pcm_manifest_digest
                and pcm_manifest_entry.get("category")
                == "runtime_pcm_stream_contract"
                and pcm_manifest_metadata
                == {
                    "kind": "stronghold_europe_pcm_stream_v1",
                    "manifest_sha256": pcm_manifest_digest,
                    "track_count": len(parsed_runtime_contract["tracks"]),
                    "max_active_streams": 2,
                    "buffer_budget_bytes": 16 * 1024 * 1024,
                    "buffer_bytes_per_stream": 1024 * 1024,
                }
                and runtime_dll_metadata.get("pcm_stream_manifest_sha256")
                == pcm_manifest_digest
            )
            checks.append(
                _check(
                    "runtime.pcm_stream_manifest",
                    pcm_manifest_ok,
                    f"sha256={pcm_manifest_digest} metadata="
                    f"{json.dumps(pcm_manifest_metadata, sort_keys=True)}",
                )
            )
            if parsed_runtime_contract["audio_payload"]:
                for track in parsed_runtime_contract["tracks"]:
                    relative = (
                        f"Runtime/Audio/{track['output_file']}"
                        if pcm_streaming
                        else f"Override/Sounds/Music/{track['output_file']}"
                    )
                    entry = declared.get(relative)
                    entry_metadata = (
                        entry.get("metadata")
                        if isinstance(entry, dict)
                        and isinstance(entry.get("metadata"), dict)
                        else {}
                    )
                    legacy_metadata_matches = (
                        isinstance(entry, dict)
                        and entry.get("category") == "europe_music"
                        and entry.get("source_reference")
                        == f"StreamingAssets/Music/{track['source_file']}"
                        and entry_metadata.get("kind") == "validated_pcm_wav"
                        and entry_metadata.get("music_id") == track["id"]
                        and entry_metadata.get("expected_original")
                        == track["expected_original"]
                        and entry_metadata.get("replacement") == track["replacement"]
                        and entry_metadata.get("volume_raw") == track["volume_raw"]
                        and entry_metadata.get("audio_format") == track["audio_format"]
                        and entry_metadata.get("channels") == track["channels"]
                        and entry_metadata.get("sample_rate") == track["sample_rate"]
                        and entry_metadata.get("bits_per_sample")
                        == track["bits_per_sample"]
                        and entry_metadata.get("block_align") == track["block_align"]
                        and entry_metadata.get("data_size") == track["data_size"]
                    )
                    pcm_metadata_matches = (
                        isinstance(entry, dict)
                        and entry.get("category") == "europe_music_pcm_stream"
                        and entry.get("source_reference")
                        == f"StreamingAssets/Music/{track['source_file']}"
                        and entry_metadata
                        == {
                            "kind": "validated_streamed_pcm_wav",
                            "music_id": track["id"],
                            "request": track["output_file"],
                            "file_size": track["file_size"],
                            "sha256": track["sha256"],
                            "audio_format": track["audio_format"],
                            "channels": track["channels"],
                            "sample_rate": track["sample_rate"],
                            "bits_per_sample": track["bits_per_sample"],
                            "block_align": track["block_align"],
                            "data_size": track["data_size"],
                        }
                    )
                    metadata_matches = (
                        pcm_metadata_matches
                        if pcm_streaming
                        else legacy_metadata_matches
                    )
                    checks.append(
                        _check(
                            f"runtime.audio_manifest.{track['id']}",
                            metadata_matches,
                            relative,
                        )
                    )
                    wav_ok = False
                    wav_detail = relative
                    try:
                        if entry is not None:
                            validate_wav(root / relative, track)
                            wav_ok = True
                    except (RuntimeBuildError, OSError, ValueError) as exc:
                        wav_detail = str(exc)
                    checks.append(
                        _check(
                            f"runtime.audio_pcm.{track['id']}",
                            wav_ok,
                            wav_detail,
                        )
                    )

    tree_apple_components = {
        "Override/Atlas/tree_apple/atlas.json",
        "Override/Atlas/tree_apple/atlas.png",
        "Override/Atlas/tree_apple/atlas_m.png",
    }
    declared_casefold = {relative.casefold() for relative in declared}
    tree_apple_atlas = {
        component.casefold() for component in tree_apple_components
    } <= declared_casefold
    tree_apple_stream = (
        parsed_asset_stream_index is not None
        and any(
            group.group.casefold() == "tree_apple"
            for group in parsed_asset_stream_index.groups
        )
    )
    foliage_requested = (
        parsed_runtime_contract is not None
        and parsed_runtime_contract.get("foliage_tree_apple") is True
    )
    checks.append(
        _check(
            "runtime.foliage_payload_presence",
            foliage_requested == (tree_apple_atlas or tree_apple_stream)
            and not (tree_apple_atlas and tree_apple_stream),
            f"requested={foliage_requested} atlas={tree_apple_atlas} "
            f"stream={tree_apple_stream}",
        )
    )
    if tree_apple_atlas or tree_apple_stream:
        contract_metadata = (
            runtime_contract_entry.get("metadata")
            if isinstance(runtime_contract_entry, dict)
            and isinstance(runtime_contract_entry.get("metadata"), dict)
            else {}
        )
        checks.append(
            _check(
                "runtime.tree_apple_foliage_gate",
                runtime_dll_entry is not None
                and runtime_contract_entry is not None
                and parsed_runtime_contract is not None
                and parsed_runtime_contract.get("foliage_tree_apple") is True,
                "tree_apple requires the exact runtime foliage companion",
            )
        )

    guid = str(info.get("GUID", ""))
    checks.append(
        _mod_logo_validation_check(
            guid,
            declared,
            ui_v2_active_and_valid=(
                runtime_dll_metadata.get("ui_texture_streaming_enabled") is True
                and ui_texture_check.ok
            ),
        )
    )
    return checks


def write_validation_report(
    checks: list[ValidationCheck],
    output_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "schema_version": 1,
        "ok": all(check.ok for check in checks),
        "passed": sum(check.ok for check in checks),
        "failed": sum(not check.ok for check in checks),
        "checks": [check.to_dict() for check in checks],
    }
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

from __future__ import annotations

from .sdk_toolchain import find_dotnet_sdk, sdk_supported, sdk_requirement

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import struct
import subprocess
from typing import Any
import zlib

from .asset_stream_contract import (
    AtlasBackend,
    BC7_ATLAS_BACKEND_KIND,
    BC7_INDEX_SCHEMA,
    INDEX_SCHEMA,
    MAX_GROUPS,
    MAX_INDEX_BYTES,
    canonical_json_bytes,
)
from .builds import BuildMatch
from .config import BuilderConfig
from .fortification_contract import (
    DEFAULT_CONTRACT_RELATIVE_PATH as FORTIFICATION_CONTRACT_RELATIVE_PATH,
    FortificationContract,
    FortificationContractError,
    load_fortification_contract,
)
from .hashing import sha256_file
from .runtime_prerequisites import (
    RuntimePrerequisiteError,
    RuntimePrerequisiteVerification,
    verify_runtime_prerequisites,
)
from .roster_text import (
    RosterTextError,
    RosterTextSpec,
    load_roster_text_spec,
    render_roster_tsv,
)
from .ui_asset_bundle import (
    ALPHA_MODE as UI_ALPHA_MODE,
    BLOCK_PADDING_MODE as UI_BLOCK_PADDING_MODE,
    ENCODER_ID as UI_ENCODER_ID,
    MAX_MANIFEST_BYTES as UI_MAX_MANIFEST_BYTES,
    QUALITY_POLICY_ID as UI_QUALITY_POLICY_ID,
    QUALITY_POLICY_SCHEMA as UI_QUALITY_POLICY_SCHEMA,
    QUALITY_VERIFIER_ID as UI_QUALITY_VERIFIER_ID,
    RUNTIME_MANIFEST_SCHEMA as UI_RUNTIME_MANIFEST_SCHEMA,
    SOURCE_SCHEMA as UI_SOURCE_SCHEMA,
    TEXTURE_CONTRACT_ID_BILINEAR,
    TEXTURE_CONTRACT_ID_POINT,
    UI_BACKEND_KIND,
    UNITY_REVISION as UI_UNITY_REVISION,
    UNITY_VERSION as UI_UNITY_VERSION,
    UiAssetBundleError,
    UiTextureBackendSelection,
    bc7_gpu_bytes,
    resident_charge_bytes,
    runtime_manifest_relative_path,
    transient_peak_bytes,
)


class RuntimeBuildError(RuntimeError):
    """Raised before an unverified or incomplete runtime companion is emitted."""


@dataclass(frozen=True)
class RuntimeArtifact:
    path: Path
    category: str
    source_reference: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class _CompiledPayloadAnchor:
    enabled: bool
    sha256: str = ""
    size: int = 0
    count: int = 0
    omitted_count: int = 0
    schema: str = ""
    backend_kind: str = ""
    quality_state: str = ""
    promotable: bool = False


@dataclass(frozen=True)
class _FortificationContractAnchor:
    enabled: bool
    schema: str = ""
    recipe_version: int = 0
    variant_count: int = 0
    record_count: int = 0
    source_size: int = 0
    source_sha256: str = ""
    tsv_size: int = 0
    tsv_sha256: str = ""
    hud_patch_size: int = 0
    hud_patch_sha256: str = ""
    sprite_catalog_size: int = 0
    sprite_catalog_sha256: str = ""


@dataclass(frozen=True)
class UiTextureRuntimeBundle:
    entry_id: str
    relative_path: str
    sha256: str
    size_bytes: int
    crc32: str
    unity_hash128: str


@dataclass(frozen=True)
class UiTextureRuntimeEntry:
    noesis_path: str
    bundle_id: str


@dataclass(frozen=True)
class UiTextureRuntimeManifest:
    path: Path
    sha256: str
    size_bytes: int
    entry_count: int
    source_manifest_sha256: str
    source_entry_set_sha256: str
    quality_policy_sha256: str
    editor_source_sha256: str
    declared_gpu_bytes: int
    declared_resident_charge_bytes: int
    bundles: tuple[UiTextureRuntimeBundle, ...]
    entries: tuple[UiTextureRuntimeEntry, ...]


_DISABLED_PAYLOAD_ANCHOR = _CompiledPayloadAnchor(False)
_DISABLED_FORTIFICATION_ANCHOR = _FortificationContractAnchor(False)

_UI_V1_MANIFEST_PATH = "Runtime/ui-textures-v1.tsv"
_UI_V2_MANIFEST_PATH = runtime_manifest_relative_path()
_UI_BUNDLE_PREFIX = "Runtime/UiAssetBundles/win64/"
_UI_BUNDLE_MAX_BYTES = 512 * 1024 * 1024
_UI_ENTRY_MAX = 512
_UI_DIMENSION_MAX = 8192
_UI_TOTAL_GPU_MAX = 2 * 1024 * 1024 * 1024
_UI_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_UI_HASH128_RE = re.compile(r"[0-9a-f]{32}\Z")
_UI_CRC32_RE = re.compile(r"[0-9a-f]{8}\Z")
_UI_ID_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,95}\Z")
_UI_BUNDLE_RE = re.compile(r"sede\.ui\.[0-9a-f]{16}\.bc7\.v1\Z")


_PLUGIN_ID = "strongholdeuropede.runtime.private"
_SOURCE_BUILD_ID = "local-sh1de-unity-2021.3.27f1-2025-01-20"
_TARGET_BUILD_ID = "local-shcde-2.80-unity-2021.3.45f2"
_ASSEMBLY_NAME = "StrongholdEuropeDE.Runtime"
_ASSEMBLY_VERSION = "0.2.0.0"
_TARGET_ASSEMBLY_SHA256 = "01da4c57f8a0e04a77804e78f79bacb1ae63d934d6d391f0dcaf3742bcca5de3"
_SCRIPT_EXTENDER_VERSION = "2.11.0.0"
_SCRIPT_EXTENDER_SHA256 = "3b944cab94e1a2d389e3cd81aa241131c9d708e7c4f227eeed41439432caee99"
_FORTIFICATION_CANARY_PROFILE_IDS = frozenset(
    {
        "fortifications-v1-canary",
        "fortifications-v1-bc7-canary",
    }
)
_FORTIFICATION_SAVE_DATA_ID = "StrongholdEuropeDE.Fortifications.v1"
_FORTIFICATION_ARTIFACT_KIND = "stronghold_europe_fortification_runtime_v1"
_FORTIFICATION_RUNTIME_PATH = "Runtime/fortifications-v1.tsv"
_FORTIFICATION_SOURCE_PATH = FORTIFICATION_CONTRACT_RELATIVE_PATH.as_posix()
_FORTIFICATION_V1_SOURCE_SIZE = 6398
_FORTIFICATION_V1_SOURCE_SHA256 = (
    "80e7a9adbd8be63a5f5e8512705663805cabee9561c0080ba750ff32becb5de4"
)
_FORTIFICATION_V1_TSV_SIZE = 2229
_FORTIFICATION_V1_TSV_SHA256 = (
    "5ced0eff268808b75f1627bfc0bdd56694d13d47257db604e91c8cb05c2393b5"
)
_FORTIFICATION_HUD_LOGICAL_PATH = "Assets/GUI/XAMLResources/HUD_Main.xaml"
_FORTIFICATION_HUD_BASE_RELATIVE_PATH = (
    "BepInEx/plugins/000shcdese/Override/Assets/GUI/XAMLResources/HUD_Main.xaml"
)
_FORTIFICATION_HUD_BASE_SIZE = 332899
_FORTIFICATION_HUD_BASE_SHA256 = (
    "b84c40b60ac4b790f9ecb5ae712234664ddedb3c73a69988dd5a8b8187a4ab74"
)
_FORTIFICATION_HUD_PATCH_SOURCE_PATH = (
    "assets/xaml/HUD_Main.fortifications.xaml"
)
_FORTIFICATION_HUD_COMBINED_PATCH_SOURCE_PATH = "assets/xaml/HUD_Main.xaml"
_FORTIFICATION_HUD_PATCH_RELATIVE_PATH = (
    "Patches/Assets/GUI/XAMLResources/HUD_Main.xaml"
)
_FORTIFICATION_HUD_PATCH_MAX_BYTES = 1024 * 1024
_FORTIFICATION_SPRITE_CATALOG_RELATIVE_PATH = "Runtime/fortification-sprites-v1.tsv"
_FORTIFICATION_SPRITE_CATALOG_MAX_BYTES = 4 * 1024 * 1024
_FORTIFICATION_SPRITE_CATALOG_SCHEMA_LINE = (
    b"# stronghold-europe-de.fortification-sprites.v3\n"
)
_TRACK_KEYS = frozenset(
    {
        "id",
        "source_file",
        "output_file",
        "expected_original",
        "replacement",
        "volume_raw",
        "file_size",
        "sha256",
        "audio_format",
        "channels",
        "sample_rate",
        "bits_per_sample",
        "block_align",
        "data_size",
    }
)
_PROFILE_KEYS = frozenset(
    {"schema_version", "plugin_id", "source_build_id", "target_build_id", "tracks"}
)
_SELECTION_KEYS = frozenset(
    {
        "enabled",
        "audio_payload",
        "foliage_tree_apple",
        "unit_roster_names",
        "farm_placement",
        "worker_militia",
        "diplomacy",
        "fortifications",
        # dock_placement is a read-only measurement lane: it subscribes to the
        # placement validation event for the four dock mappers and logs what it
        # sees, without ever answering.  It is a separate key from
        # farm_placement on purpose - the two lanes share a detour and must stay
        # separately switchable.
        "dock_placement",
    }
)
# Die Hafen-Regelwerte (Wasserregel-Werteanzeige, Baukosten, Trefferpunkte)
# reisen als EIGENER Top-Level-Block im Profil, nicht im runtime-Block:
# profile.runtime ist per Vertrag eine exakte Menge boolescher Schluessel
# (_validate_runtime_selection), und der Praezedenzfall fuer einen eigenen
# Top-Level-Block ist authored_sprites. Abwesenheit = aus. Ein vorhandener
# Block verlangt runtime.enabled UND runtime.dock_placement, sonst wird der
# Build abgelehnt - fail-closed, niemals stillschweigend ignoriert.
_DOCK_RULES_KEYS = frozenset({"wood_cost", "gold_cost", "health"})
_DIPLOMACY_RULES_V1 = {
    "economy_building_material_percent": 25,
    "lord_military_value": 250,
    "unknown_unit_health_divisor": 4,
    "unknown_unit_value_minimum": 25,
    "unknown_unit_value_maximum": 250,
    "target_base_value": 350,
    "economy_weight_basis_points": 800,
    "military_weight_basis_points": 1400,
    "personality_base_basis_points": 8000,
    "personality_margin_basis_points": 80,
    "target_minimum": 500,
    "target_maximum": 7500,
    "target_round_step": 50,
    "goodwill_grace_days": 5,
    "goodwill_decay_percent": 2,
    "offer_base_percent": 85,
    "offer_margin_tenths_percent": 6,
    "offer_minimum_percent": 25,
    "offer_maximum_percent": 85,
    "offer_additional_gift_percent": 5,
    "offer_rejection_lock_days": 5,
    "demand_lifetime_days": 10,
    "maximum_demand_goods": 3,
    "new_alliance_grace_days": 10,
    "starting_alliance_grace_days": 20,
    "loyalty_base_decay_basis_points": 50,
    "loyalty_margin_decay_basis_points": 1,
    "ultimatum_threshold_percent": 35,
    "ultimatum_restore_percent": 60,
    "ultimatum_lifetime_days": 10,
    "break_lock_days": 10,
}
_DIPLOMACY_RULES_KEYS = frozenset(_DIPLOMACY_RULES_V1)
_DIPLOMACY_ROLLOUT_PROFILE_IDS = frozenset(
    {
        "diplomacy-v1-canary",
        "europe-bc7-fort-diplomacy-canary",
        "europe-production-bc7-v2",
    }
)
# Schranken sind SETZUNG, keine Messung: Kosten in der Groessenordnung der
# teuersten regulaeren Bauwerke, Trefferpunkte weit ueber dem gemessenen
# Bestand (hovel=100, Struktur 108=300, Protokoll 14.08.2026) und weit unter
# jedem Ueberlauf der nativen uint-Tabelle.
_DOCK_RULES_COST_MAX = 1000
_DOCK_RULES_HEALTH_MAX = 100000
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_OUTPUT_WAV = re.compile(r"eu_[a-z0-9_]+\.wav\Z")
_MUSIC_RAW = re.compile(r"fx\\music\\[^\\/\t\r\n]+\.raw\Z")
_PREREQUISITE_ORDER = (
    "shcdese",
    "nlua",
    "keralua",
    "redbird_core",
    "system_memory",
    "bepinex_core",
    "harmony",
    "r3",
    "assembly_csharp",
    "noesis_gui",
    "unity_engine",
    "unity_engine_core_module",
    "unity_engine_asset_bundle_module",
    "unity_engine_audio_module",
    "unity_engine_image_conversion_module",
    "unsafe",
)
_RUNTIME_SOURCE_SUPPORT_FILES = (
    "assets/xaml/HUD_Main.dock.xaml",
    "assets/xaml/HUD_Main.fortifications.xaml",
    "assets/xaml/HUD_Main.xaml",
    "config/fortification-variants-v1.json",
    "config/runtime-prerequisites.json",
    "config/unit-roster-text.json",
    "global.json",
    "src/stronghold_europe_de/fortification_contract.py",
    "src/stronghold_europe_de/hashing.py",
    "src/stronghold_europe_de/roster_text.py",
    "src/stronghold_europe_de/runtime_build.py",
    "src/stronghold_europe_de/runtime_prerequisites.py",
    "src/stronghold_europe_de/runtime_reference_capture.py",
)
_MSBUILD_ANCESTOR_INPUT_NAMES = (
    "Directory.Build.props",
    "Directory.Build.targets",
    "Directory.Packages.props",
    "NuGet.Config",
)


def runtime_source_set_sha256(project_root: Path) -> str:
    """Hash every author-owned input that can change the managed DLL."""

    root = project_root.resolve()
    project_directory = root / "runtime" / "StrongholdEuropeDE.Runtime"
    relative_paths = list(_RUNTIME_SOURCE_SUPPORT_FILES)
    try:
        relative_paths.extend(
            path.relative_to(root).as_posix()
            for path in sorted(project_directory.rglob("*"))
            if path.is_file()
            and not {
                part.casefold()
                for part in path.relative_to(project_directory).parts[:-1]
            }
            & {"bin", "obj"}
        )
    except OSError as exc:
        raise RuntimeBuildError(
            "Runtime source project cannot be enumerated"
        ) from exc
    for ancestor in (project_directory.parent, root):
        for name in _MSBUILD_ANCESTOR_INPUT_NAMES:
            candidate = ancestor / name
            if candidate.is_file():
                relative_paths.append(candidate.relative_to(root).as_posix())
    if len(relative_paths) != len(set(relative_paths)):
        raise RuntimeBuildError("Runtime source-set paths are not unique")
    digest = hashlib.sha256()
    for relative in sorted(relative_paths):
        path = root / Path(relative)
        if not path.is_file():
            raise RuntimeBuildError(
                f"Runtime source-set input is missing: {relative}"
            )
        before = path.stat()
        payload = path.read_bytes()
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (
            after.st_size,
            after.st_mtime_ns,
        ):
            raise RuntimeBuildError(
                f"Runtime source-set input changed while hashing: {relative}"
            )
        file_digest = hashlib.sha256(payload).hexdigest()
        digest.update(
            f"{relative}\t{len(payload)}\t{file_digest}\n".encode("utf-8")
        )
    return digest.hexdigest()

# The semantic ID mapping is code-pinned as well as reviewable in JSON.  File
# fingerprints remain in audio-profile.json because they describe local game
# payloads, while these values guard against silently repurposing a music ID.
_TRACK_CONTRACT: dict[int, tuple[str, str, str, int]] = {
    3: ("chantloop1.wav", "eu_chantloop1.wav", "fx\\music\\astrongspice.raw", 80),
    4: ("mandloop1.wav", "eu_mandloop1.wav", "fx\\music\\null.raw", 70),
    5: ("mandloop2.wav", "eu_mandloop2.wav", "fx\\music\\null.raw", 70),
    6: ("monks1.wav", "eu_monks1.wav", "fx\\music\\monks1.raw", 60),
    7: ("stainedglass1.wav", "eu_stainedglass1.wav", "fx\\music\\stainedglass1.raw", 80),
    9: ("Mattsjig.wav", "eu_mattsjig.wav", "fx\\music\\caravan_ambient.raw", 99),
    10: ("the maidenA.wav", "eu_the_maiden_a.wav", "fx\\music\\trancefusion.raw", 75),
    11: ("the maidenB.wav", "eu_the_maiden_b.wav", "fx\\music\\crusader_solo.raw", 75),
    12: ("journeys.wav", "eu_journeys.wav", "fx\\music\\thelastdrop.raw", 90),
    13: ("exploration.wav", "eu_exploration.wav", "fx\\music\\astrongspice.raw", 90),
    14: ("underanoldtree.wav", "eu_underanoldtree.wav", "fx\\music\\caravan.raw", 80),
    15: ("castlejam.wav", "eu_castlejam.wav", "fx\\music\\sandalmaker.raw", 75),
    16: ("appytimes.wav", "eu_appytimes.wav", "fx\\music\\dar meshq.raw", 90),
    17: ("darktime.wav", "eu_darktime.wav", "fx\\music\\thelastdrop.raw", 90),
    18: ("paranoia.wav", "eu_paranoia.wav", "fx\\music\\trancefusion.raw", 100),
    19: ("sadtimesa.wav", "eu_sadtimesa.wav", "fx\\music\\crusader_solo.raw", 80),
    20: ("sadtimesb.wav", "eu_sadtimesb.wav", "fx\\music\\cameltoe.raw", 80),
}

# Route B.  The gameplay music path never reads music_filenames: GameMap hands
# SFXManager.playMusic(string) a path taken from the native display-list state,
# so rewriting the table cannot reach it.  The companion therefore rewrites the
# requested name in flight, one Harmony prefix on playMusic(string, ...).
#
# Keys are the bare file names the engine produces (playMusic lowercases the
# path and splits on '\'), values are stems of tracks the payload already
# ships, so this mapping costs no extra bytes on disk.  It also covers the
# ~111 music_filenames entries the ID table leaves untouched, because
# playMusic(int) funnels into playMusic(string) as well.
#
# "null.raw" is deliberately absent: it is the engine's stop-music signal, not
# a track.  So are the 22 same-named Crusader re-recordings (suspense*,
# drumloop*, percloop1, honor_*, Glory_0[1235], bigwin*, bigloss*) — Stronghold 1
# has its own versions of those under identical names, and mapping them onto an
# unrelated ballad would be worse than leaving them.  They need a payload
# extension, not a rename.
_MUSIC_ROUTE_MAP: tuple[tuple[str, str], ...] = (
    # Long-form ambient and melodic material heard during ordinary play.
    ("caravan_ambient", "eu_exploration"),
    ("thelastdrop", "eu_journeys"),
    ("crusader", "eu_the_maiden_a"),
    ("caravan", "eu_underanoldtree"),
    ("sand wedgie", "eu_castlejam"),
    ("astrongspice", "eu_appytimes"),
    ("sandalmaker", "eu_mattsjig"),
    ("dar meshq", "eu_mandloop2"),
    ("cameltoe", "eu_sadtimesb"),
    ("trancefusion", "eu_paranoia"),
    ("crusader_solo", "eu_sadtimesa"),
    ("apaneintheglass", "eu_stainedglass1"),
    ("solovln_01", "eu_the_maiden_b"),
    ("end_music", "eu_darktime"),
    ("detrailer", "eu_castlejam"),
    # The Arabic lute set answers to the European plucked-string material.
    ("oud_01", "eu_mandloop1"),
    ("oud_02", "eu_mandloop2"),
    ("oud_03", "eu_the_maiden_b"),
    ("oud_04", "eu_mattsjig"),
    ("oud_05", "eu_mandloop1"),
    ("oud_06", "eu_mandloop2"),
    ("oud_07", "eu_the_maiden_b"),
    ("oud_08", "eu_mattsjig"),
    ("oud_09", "eu_mandloop1"),
    ("oud_10", "eu_mandloop2"),
    ("oud_11", "eu_the_maiden_b"),
    ("oud_12", "eu_mattsjig"),
    ("oud_13", "eu_mandloop1"),
    ("oud_14", "eu_mandloop2"),
    ("oud_15", "eu_the_maiden_b"),
    ("oud_16", "eu_mattsjig"),
    ("oud_17", "eu_mandloop1"),
    ("oud_18", "eu_mandloop2"),
    ("oud_19", "eu_the_maiden_b"),
    ("oud_20", "eu_mattsjig"),
    ("oud_21", "eu_mandloop1"),
    ("oud_22", "eu_mandloop2"),
    ("oud_23", "eu_the_maiden_b"),
    ("oud_24", "eu_mattsjig"),
    # The ney flute set answers to the European chant and solo material.
    ("flt_01", "eu_chantloop1"),
    ("flt_02", "eu_monks1"),
    ("flt_03", "eu_stainedglass1"),
    ("flt_04", "eu_sadtimesa"),
    ("flt_05", "eu_chantloop1"),
    ("flt_06", "eu_monks1"),
    ("flt_07", "eu_stainedglass1"),
    ("flt_08", "eu_sadtimesa"),
    ("flt_09", "eu_chantloop1"),
    ("flt_10", "eu_monks1"),
    ("flt_11", "eu_stainedglass1"),
    ("flt_12", "eu_sadtimesa"),
    ("flt_13", "eu_chantloop1"),
    ("flt_14", "eu_monks1"),
    ("flt_15", "eu_stainedglass1"),
    ("flt_16", "eu_sadtimesa"),
    ("flt_17", "eu_chantloop1"),
    ("flt_18", "eu_monks1"),
    ("flt_19", "eu_stainedglass1"),
    ("flt_narr1", "eu_monks1"),
    # Campaign themes.
    ("campaign 6_01", "eu_the_maiden_a"),
    ("campaign 6_02", "eu_journeys"),
    ("campaign 6_03", "eu_underanoldtree"),
    ("campaign 6_04", "eu_castlejam"),
    ("campaign 6_05", "eu_appytimes"),
    ("campaign 7_01", "eu_journeys"),
    ("campaign 7_02", "eu_darktime"),
    ("campaign 7_03", "eu_paranoia"),
    ("campaign 7_04", "eu_sadtimesa"),
    ("campaign 7_05", "eu_exploration"),
    ("campaign 8_01", "eu_castlejam"),
    ("campaign 8_02", "eu_mattsjig"),
    ("campaign 8_03", "eu_the_maiden_b"),
    ("campaign 8_04", "eu_sadtimesb"),
    ("campaign 8_05", "eu_underanoldtree"),
)

# Vanilla draws these groups with Unlit/Foliage, but the 1.39 atlas loader
# hard-codes Unlit/TeamColour for every group it overrides. The companion
# restores the foliage material for exactly these names - and only when the GM
# slot really carries our atlas, so a group that is not shipped stays untouched.
# Code-pinned rather than derived from the profile: which groups are foliage is
# a property of the game, not of what we happen to build today.
_FOLIAGE_GROUPS: tuple[str, ...] = (
    "tree_apple",
    "tree_pine",
    "tree_birch",
    "Tree_Oak",
    "Tree_Chestnut",
    "tree_shrub1",
    "tree_shrub2",
)

_MUSIC_STEM = re.compile(r"[a-z0-9_ ]+\Z")


def music_route_entries() -> tuple[tuple[str, str], ...]:
    """Return the validated (requested file, replacement path) route pairs.

    Requested names carry the ``.raw`` extension the engine asks for; the
    replacement is a full ``fx\\music\\*.raw`` path so that the rewritten value
    also matches the volume entry the companion registers for that track.
    """

    shipped = {
        Path(output_file).stem
        for _source, output_file, _original, _volume in _TRACK_CONTRACT.values()
    }
    seen: set[str] = set()
    entries: list[tuple[str, str]] = []
    for requested, replacement in _MUSIC_ROUTE_MAP:
        if _MUSIC_STEM.fullmatch(requested) is None:
            raise RuntimeBuildError(
                f"Music route key is not a bare lowercase stem: {requested!r}"
            )
        if requested == "null":
            raise RuntimeBuildError("Music route must not rewrite the stop signal")
        if requested.startswith("eu_"):
            raise RuntimeBuildError(
                f"Music route must not rewrite our own payload: {requested}"
            )
        if replacement not in shipped:
            raise RuntimeBuildError(
                f"Music route target is not a shipped track: {replacement}"
            )
        if requested in seen:
            raise RuntimeBuildError(f"Duplicate music route key: {requested}")
        seen.add(requested)
        entries.append((f"{requested}.raw", f"fx\\music\\{replacement}.raw"))
    if not entries:
        raise RuntimeBuildError("Music route map is empty")
    return tuple(entries)


def music_route_sha256() -> str:
    digest = hashlib.sha256()
    for requested, replacement in music_route_entries():
        digest.update(f"{requested}\t{replacement}\n".encode("utf-8"))
    return digest.hexdigest()


def _exact_keys(value: Mapping[str, Any], expected: frozenset[str], label: str) -> None:
    missing = sorted(expected - set(value))
    extra = sorted(set(value) - expected)
    if missing or extra:
        raise RuntimeBuildError(
            f"Invalid {label} keys: missing={missing}, extra={extra}"
        )


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise RuntimeBuildError(f"{label} must be a positive integer")
    return value


def _flat_filename(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise RuntimeBuildError(f"{label} must be a non-empty string")
    windows = PureWindowsPath(value)
    if (
        windows.name != value
        or windows.is_absolute()
        or windows.drive
        or any(character in value for character in '<>:"/\\|?*\t\r\n\x00')
    ):
        raise RuntimeBuildError(f"{label} is not a safe flat filename: {value!r}")
    return value


def load_audio_profile(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeBuildError(f"Cannot read runtime audio profile: {path}") from exc
    return _validate_audio_profile_data(raw)


def _validate_audio_profile_data(raw: object) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise RuntimeBuildError("Runtime audio profile must be an object")
    _exact_keys(raw, _PROFILE_KEYS, "runtime audio profile")
    if raw["schema_version"] != 1:
        raise RuntimeBuildError("Unsupported runtime audio profile schema")
    if raw["plugin_id"] != _PLUGIN_ID:
        raise RuntimeBuildError("Runtime plugin ID is not the private pinned ID")
    for field in ("source_build_id", "target_build_id"):
        if not isinstance(raw[field], str) or re.fullmatch(r"[A-Za-z0-9_.-]+", raw[field]) is None:
            raise RuntimeBuildError(f"Invalid runtime profile {field}")

    raw_tracks = raw["tracks"]
    if not isinstance(raw_tracks, list) or len(raw_tracks) != len(_TRACK_CONTRACT):
        raise RuntimeBuildError("Runtime audio profile must contain exactly 17 tracks")
    expected_ids = tuple(_TRACK_CONTRACT)
    seen_outputs: set[str] = set()
    seen_replacements: set[str] = set()
    for index, track in enumerate(raw_tracks):
        label = f"tracks[{index}]"
        if not isinstance(track, Mapping):
            raise RuntimeBuildError(f"{label} must be an object")
        _exact_keys(track, _TRACK_KEYS, label)
        track_id = _positive_int(track["id"], f"{label}.id")
        if track_id != expected_ids[index]:
            raise RuntimeBuildError(
                f"Runtime track ID/order mismatch: expected={expected_ids[index]} actual={track_id}"
            )
        source_file = _flat_filename(track["source_file"], f"{label}.source_file")
        output_file = _flat_filename(track["output_file"], f"{label}.output_file")
        if _OUTPUT_WAV.fullmatch(output_file) is None:
            raise RuntimeBuildError(f"Noncanonical runtime output WAV: {output_file}")
        expected_original = track["expected_original"]
        replacement = track["replacement"]
        if not isinstance(expected_original, str) or _MUSIC_RAW.fullmatch(expected_original) is None:
            raise RuntimeBuildError(f"Invalid expected original music path for ID {track_id}")
        if not isinstance(replacement, str) or _MUSIC_RAW.fullmatch(replacement) is None:
            raise RuntimeBuildError(f"Invalid replacement music path for ID {track_id}")
        derived = f"fx\\music\\{Path(output_file).stem}.raw"
        volume = _positive_int(track["volume_raw"], f"{label}.volume_raw")
        if volume > 127:
            raise RuntimeBuildError(f"Volume exceeds 127 for ID {track_id}")
        semantic = (source_file, output_file, expected_original, volume)
        if semantic != _TRACK_CONTRACT[track_id] or replacement != derived:
            raise RuntimeBuildError(
                f"Pinned semantic music contract mismatch for ID {track_id}"
            )
        digest = track["sha256"]
        if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
            raise RuntimeBuildError(f"Invalid lowercase SHA-256 for ID {track_id}")
        file_size = _positive_int(track["file_size"], f"{label}.file_size")
        data_size = _positive_int(track["data_size"], f"{label}.data_size")
        if data_size >= file_size:
            raise RuntimeBuildError(f"Invalid WAV data size for ID {track_id}")
        pcm = (
            track["audio_format"],
            track["channels"],
            track["sample_rate"],
            track["bits_per_sample"],
            track["block_align"],
        )
        if pcm != (1, 2, 44100, 16, 4):
            raise RuntimeBuildError(f"Unsupported WAV PCM contract for ID {track_id}: {pcm}")
        if output_file in seen_outputs or replacement in seen_replacements:
            raise RuntimeBuildError("Duplicate runtime output or replacement path")
        seen_outputs.add(output_file)
        seen_replacements.add(replacement)
    return dict(raw)


def _tsv_pair(line: str, expected_key: str) -> str:
    fields = line.split("\t")
    if len(fields) != 2 or fields[0] != expected_key or not fields[1]:
        raise RuntimeBuildError(f"Malformed runtime contract field: {expected_key}")
    return fields[1]


def _tsv_int(value: str, label: str) -> int:
    if not value.isascii() or not value.isdecimal():
        raise RuntimeBuildError(f"Malformed runtime contract integer: {label}")
    return int(value)


def parse_runtime_contract(path: Path) -> dict[str, Any]:
    """Parse the deployed canonical TSV and reapply the semantic 17-ID gate."""

    try:
        payload = path.read_bytes()
        text = payload.decode("utf-8", errors="strict")
    except (OSError, UnicodeError) as exc:
        raise RuntimeBuildError(f"Cannot read runtime contract: {path}") from exc
    if "\r" in text or not text.endswith("\n"):
        raise RuntimeBuildError("Runtime contract must use canonical UTF-8/LF")
    lines = text[:-1].split("\n")
    if len(lines) != 11 + len(_TRACK_CONTRACT):
        raise RuntimeBuildError("Runtime contract line count is not exact")
    if lines[0] != "stronghold-europe-audio-profile\t1":
        raise RuntimeBuildError("Runtime contract signature is not exact")

    plugin_id = _tsv_pair(lines[1], "plugin_id")
    source_build_id = _tsv_pair(lines[2], "source_build_id")
    target_build_id = _tsv_pair(lines[3], "target_build_id")
    target_sha256 = _tsv_pair(lines[4], "target_assembly_sha256")
    extender_version = _tsv_pair(lines[5], "script_extender_version")
    extender_sha256 = _tsv_pair(lines[6], "script_extender_sha256")
    audio_payload_value = _tsv_pair(lines[7], "audio_payload")
    foliage_value = _tsv_pair(lines[8], "foliage_tree_apple")
    track_count = _tsv_int(_tsv_pair(lines[9], "track_count"), "track_count")
    expected_header = (
        "track\tid\tsource_file\toutput_file\texpected_original\treplacement"
        "\tvolume_raw\tfile_size\tsha256\taudio_format\tchannels\tsample_rate"
        "\tbits_per_sample\tblock_align\tdata_size"
    )
    if lines[10] != expected_header:
        raise RuntimeBuildError("Runtime contract track header is not exact")
    if (
        plugin_id != _PLUGIN_ID
        or re.fullmatch(r"[A-Za-z0-9_.-]+", source_build_id) is None
        or re.fullmatch(r"[A-Za-z0-9_.-]+", target_build_id) is None
        or re.fullmatch(r"[0-9a-f]{64}", target_sha256) is None
        or re.fullmatch(r"[0-9]+(?:\.[0-9]+){2,3}", extender_version) is None
        or re.fullmatch(r"[0-9a-f]{64}", extender_sha256) is None
        or audio_payload_value not in {"0", "1"}
        or foliage_value not in {"0", "1"}
        or track_count != len(_TRACK_CONTRACT)
    ):
        raise RuntimeBuildError("Runtime contract build/feature metadata is not exact")

    tracks: list[dict[str, Any]] = []
    for index, line in enumerate(lines[11:]):
        fields = line.split("\t")
        if len(fields) != 15 or fields[0] != "track":
            raise RuntimeBuildError(f"Malformed runtime contract track row: {index}")
        tracks.append(
            {
                "id": _tsv_int(fields[1], "id"),
                "source_file": fields[2],
                "output_file": fields[3],
                "expected_original": fields[4],
                "replacement": fields[5],
                "volume_raw": _tsv_int(fields[6], "volume_raw"),
                "file_size": _tsv_int(fields[7], "file_size"),
                "sha256": fields[8],
                "audio_format": _tsv_int(fields[9], "audio_format"),
                "channels": _tsv_int(fields[10], "channels"),
                "sample_rate": _tsv_int(fields[11], "sample_rate"),
                "bits_per_sample": _tsv_int(fields[12], "bits_per_sample"),
                "block_align": _tsv_int(fields[13], "block_align"),
                "data_size": _tsv_int(fields[14], "data_size"),
            }
        )
    _validate_audio_profile_data(
        {
            "schema_version": 1,
            "plugin_id": plugin_id,
            "source_build_id": source_build_id,
            "target_build_id": target_build_id,
            "tracks": tracks,
        }
    )
    return {
        "plugin_id": plugin_id,
        "source_build_id": source_build_id,
        "target_build_id": target_build_id,
        "target_assembly_sha256": target_sha256,
        "script_extender_version": extender_version,
        "script_extender_sha256": extender_sha256,
        "audio_payload": audio_payload_value == "1",
        "foliage_tree_apple": foliage_value == "1",
        "tracks": tracks,
    }


def _validate_runtime_selection(selection: object) -> dict[str, bool]:
    if not isinstance(selection, Mapping):
        raise RuntimeBuildError("profile.runtime must be an object")
    # diplomacy and fortifications were introduced after the original runtime
    # object.  Their absence remains a canonical false value so old profiles
    # continue to build byte-for-byte equivalent feature selections.
    required = _SELECTION_KEYS - {"diplomacy", "fortifications"}
    missing = sorted(required - set(selection))
    extra = sorted(set(selection) - _SELECTION_KEYS)
    if missing or extra:
        raise RuntimeBuildError(
            f"Invalid profile.runtime keys: missing={missing}, extra={extra}"
        )
    parsed: dict[str, bool] = {}
    for key in _SELECTION_KEYS:
        value = selection.get(key, False)
        if not isinstance(value, bool):
            raise RuntimeBuildError(f"profile.runtime.{key} must be boolean")
        parsed[key] = value
    if not parsed["enabled"] and (
        parsed["audio_payload"]
        or parsed["foliage_tree_apple"]
        or parsed["unit_roster_names"]
        or parsed["farm_placement"]
        or parsed["worker_militia"]
        or parsed["diplomacy"]
        or parsed["fortifications"]
        or parsed["dock_placement"]
    ):
        raise RuntimeBuildError("Disabled runtime cannot enable a runtime feature")
    return parsed


def _validate_dock_placement_rules(
    block: object,
    runtime: Mapping[str, bool] | None,
) -> dict[str, int] | None:
    """Parse the top-level ``dock_placement_rules`` block, fail-closed.

    ``None`` (absent block) means the dock lane stays in pure measurement
    mode.  A present block turns the lane into a rule and therefore demands
    that the lane itself is switched on; a rules block on a build that never
    subscribes the lane would be a silent no-op, and silent no-ops are how
    this project has been burned before.
    """

    if block is None:
        return None
    if not isinstance(block, Mapping):
        raise RuntimeBuildError("profile.dock_placement_rules must be an object")
    _exact_keys(block, _DOCK_RULES_KEYS, "profile.dock_placement_rules")
    parsed: dict[str, int] = {}
    for key in sorted(_DOCK_RULES_KEYS):
        value = block[key]
        if isinstance(value, bool) or not isinstance(value, int):
            raise RuntimeBuildError(
                f"profile.dock_placement_rules.{key} must be an integer"
            )
        parsed[key] = value
    for key in ("wood_cost", "gold_cost"):
        if not 0 <= parsed[key] <= _DOCK_RULES_COST_MAX:
            raise RuntimeBuildError(
                f"profile.dock_placement_rules.{key} must be within "
                f"0..{_DOCK_RULES_COST_MAX}"
            )
    if not 1 <= parsed["health"] <= _DOCK_RULES_HEALTH_MAX:
        raise RuntimeBuildError(
            "profile.dock_placement_rules.health must be within "
            f"1..{_DOCK_RULES_HEALTH_MAX}"
        )
    if runtime is None or not runtime.get("enabled") or not runtime.get(
        "dock_placement"
    ):
        raise RuntimeBuildError(
            "dock_placement_rules requires runtime.enabled and "
            "runtime.dock_placement"
        )
    return parsed


def _manifest_text(
    spec: dict[str, Any],
    selection: dict[str, bool],
    prerequisites: RuntimePrerequisiteVerification,
) -> str:
    pins = {entry.id: entry for entry in prerequisites.files}
    target = pins["assembly_csharp"]
    extender = pins["shcdese"]
    lines = [
        "stronghold-europe-audio-profile\t1",
        f"plugin_id\t{spec['plugin_id']}",
        f"source_build_id\t{spec['source_build_id']}",
        f"target_build_id\t{spec['target_build_id']}",
        f"target_assembly_sha256\t{target.sha256}",
        f"script_extender_version\t{extender.assembly_version}",
        f"script_extender_sha256\t{extender.sha256}",
        f"audio_payload\t{int(selection['audio_payload'])}",
        f"foliage_tree_apple\t{int(selection['foliage_tree_apple'])}",
        f"track_count\t{len(spec['tracks'])}",
        "track\tid\tsource_file\toutput_file\texpected_original\treplacement"
        "\tvolume_raw\tfile_size\tsha256\taudio_format\tchannels\tsample_rate"
        "\tbits_per_sample\tblock_align\tdata_size",
    ]
    for track in spec["tracks"]:
        fields = [
            "track",
            track["id"],
            track["source_file"],
            track["output_file"],
            track["expected_original"],
            track["replacement"],
            track["volume_raw"],
            track["file_size"],
            track["sha256"],
            track["audio_format"],
            track["channels"],
            track["sample_rate"],
            track["bits_per_sample"],
            track["block_align"],
            track["data_size"],
        ]
        lines.append("\t".join(str(value) for value in fields))
    return "\n".join(lines) + "\n"


def _read_stable_payload(path: Path, *, maximum_bytes: int, label: str) -> bytes:
    try:
        before = path.stat()
        if (
            not path.is_file()
            or path.is_symlink()
            or before.st_size < 1
            or before.st_size > maximum_bytes
        ):
            raise RuntimeBuildError(f"{label} is missing, linked, empty, or oversized")
        payload = path.read_bytes()
        after = path.stat()
    except OSError as exc:
        raise RuntimeBuildError(f"Cannot read {label}: {path}") from exc
    if (
        len(payload) != before.st_size
        or (before.st_size, before.st_mtime_ns)
        != (after.st_size, after.st_mtime_ns)
    ):
        raise RuntimeBuildError(f"{label} changed while it was being read")
    return payload


def _load_fortification_build_contract(
    config: BuilderConfig,
    mod_root: Path,
    *,
    include_dock_contributor: bool,
) -> tuple[_FortificationContractAnchor, bytes]:
    """Load and pin the V1 catalogue plus the one HUD patch it owns."""

    source_path = config.project_root / FORTIFICATION_CONTRACT_RELATIVE_PATH
    try:
        contract: FortificationContract = load_fortification_contract(source_path)
    except FortificationContractError as exc:
        raise RuntimeBuildError(
            "Pinned fortification variant contract was rejected"
        ) from exc
    tsv_payload = contract.canonical_tsv_bytes()
    tsv_sha256 = hashlib.sha256(tsv_payload).hexdigest()
    if (
        contract.source_size_bytes != _FORTIFICATION_V1_SOURCE_SIZE
        or contract.source_sha256 != _FORTIFICATION_V1_SOURCE_SHA256
        or len(tsv_payload) != _FORTIFICATION_V1_TSV_SIZE
        or tsv_sha256 != _FORTIFICATION_V1_TSV_SHA256
    ):
        raise RuntimeBuildError(
            "Fortification V1 source or canonical TSV differs from its pin"
        )

    hud_source_path = (
        _FORTIFICATION_HUD_COMBINED_PATCH_SOURCE_PATH
        if include_dock_contributor
        else _FORTIFICATION_HUD_PATCH_SOURCE_PATH
    )
    patch_payload = _read_stable_payload(
        config.project_root / hud_source_path,
        maximum_bytes=_FORTIFICATION_HUD_PATCH_MAX_BYTES,
        label="fortification HUD_Main patch source",
    )
    staged_patch_payload = _read_stable_payload(
        mod_root / Path(_FORTIFICATION_HUD_PATCH_RELATIVE_PATH),
        maximum_bytes=_FORTIFICATION_HUD_PATCH_MAX_BYTES,
        label="staged fortification HUD_Main patch",
    )
    if staged_patch_payload != patch_payload:
        raise RuntimeBuildError(
            "Staged fortification HUD_Main patch differs from its project source"
        )
    # Sichtrezept-Katalog (2026-09-02): wenn der Builder ihn nach Runtime/
    # gestellt hat, wird sein Digest in den Vertrag kompiliert; die Runtime
    # laedt ihn nur bei exakter Uebereinstimmung. Ohne Katalog bleibt der
    # Vertrag bei 0/"" und die Mauerarten behalten das native Bild.
    sprite_catalog_size = 0
    sprite_catalog_sha256 = ""
    sprite_catalog_path = mod_root / Path(_FORTIFICATION_SPRITE_CATALOG_RELATIVE_PATH)
    if sprite_catalog_path.exists():
        sprite_catalog_payload = _read_stable_payload(
            sprite_catalog_path,
            maximum_bytes=_FORTIFICATION_SPRITE_CATALOG_MAX_BYTES,
            label="staged fortification sprite catalogue",
        )
        if not sprite_catalog_payload.startswith(
            _FORTIFICATION_SPRITE_CATALOG_SCHEMA_LINE
        ):
            raise RuntimeBuildError(
                "Staged fortification sprite catalogue has an unexpected schema"
            )
        sprite_catalog_size = len(sprite_catalog_payload)
        sprite_catalog_sha256 = hashlib.sha256(sprite_catalog_payload).hexdigest()
    return (
        _FortificationContractAnchor(
            enabled=True,
            schema=contract.schema,
            recipe_version=contract.recipe_version,
            variant_count=contract.variant_count,
            record_count=contract.record_count,
            source_size=contract.source_size_bytes,
            source_sha256=contract.source_sha256,
            tsv_size=len(tsv_payload),
            tsv_sha256=tsv_sha256,
            hud_patch_size=len(patch_payload),
            hud_patch_sha256=hashlib.sha256(patch_payload).hexdigest(),
            sprite_catalog_size=sprite_catalog_size,
            sprite_catalog_sha256=sprite_catalog_sha256,
        ),
        tsv_payload,
    )


def _json_without_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise RuntimeBuildError(f"Asset-stream index repeats JSON key {key!r}")
        result[key] = value
    return result


def _asset_stream_anchor(
    mod_root: Path,
    backend: AtlasBackend | None,
) -> _CompiledPayloadAnchor:
    index_path = mod_root / "Runtime" / "AssetBundles" / "index.json"
    if backend is None:
        if index_path.exists():
            raise RuntimeBuildError(
                "Legacy runtime unexpectedly contains an AssetBundle index"
            )
        return _DISABLED_PAYLOAD_ANCHOR

    payload = _read_stable_payload(
        index_path,
        maximum_bytes=MAX_INDEX_BYTES,
        label="AssetBundle index",
    )
    if (
        payload.startswith(b"\xef\xbb\xbf")
        or not payload.endswith(b"\n")
        or payload.endswith(b"\n\n")
        or b"\r" in payload
    ):
        raise RuntimeBuildError(
            "AssetBundle index must be BOM-free canonical UTF-8/LF"
        )
    try:
        value = json.loads(
            payload[:-1].decode("utf-8", errors="strict"),
            object_pairs_hook=_json_without_duplicates,
            parse_constant=lambda token: (_ for _ in ()).throw(
                RuntimeBuildError(
                    f"Asset-stream index contains non-finite number {token!r}"
                )
            ),
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeBuildError("AssetBundle index is not strict JSON") from exc
    try:
        canonical = canonical_json_bytes(value) + b"\n"
    except Exception as exc:
        raise RuntimeBuildError("AssetBundle index is not canonical JSON") from exc
    if canonical != payload or not isinstance(value, dict):
        raise RuntimeBuildError("AssetBundle index bytes are not canonical")
    schema = value.get("schema")
    if backend.kind == BC7_ATLAS_BACKEND_KIND:
        expected_keys = {
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
        quality_policy = value.get("quality_policy")
        quality_state = (
            quality_policy.get("state")
            if isinstance(quality_policy, dict)
            else None
        )
        if (
            schema != BC7_INDEX_SCHEMA
            or value.get("backend_kind") != backend.kind
            or not isinstance(quality_policy, dict)
            or backend.quality_policy is None
            or quality_policy
            != {
                "state": backend.quality_policy.state,
                "id": backend.quality_policy.id,
                "sha256": backend.quality_policy.sha256,
                "verifier_id": backend.quality_policy.verifier_id,
            }
        ):
            raise RuntimeBuildError(
                "BC7 AssetBundle index identity/quality policy changed"
            )
        promotable = backend.promotable and quality_state == "frozen"
    else:
        expected_keys = {
            "schema",
            "build_id",
            "unity",
            "build_target",
            "max_page_dimension",
            "groups",
            "vanilla_omitted_groups",
        }
        quality_state = "v1"
        promotable = True
        if schema != INDEX_SCHEMA:
            raise RuntimeBuildError("AssetBundle index schema changed")
    if set(value) != expected_keys:
        raise RuntimeBuildError("AssetBundle index root key set changed")
    groups = value.get("groups")
    omitted = value.get("vanilla_omitted_groups")
    if (
        not isinstance(groups, list)
        or not isinstance(omitted, list)
        or not 1 <= len(groups) + len(omitted) <= MAX_GROUPS
    ):
        raise RuntimeBuildError("AssetBundle index identity/group count changed")
    return _CompiledPayloadAnchor(
        True,
        hashlib.sha256(payload).hexdigest(),
        len(payload),
        len(groups),
        len(omitted),
        str(schema),
        backend.kind,
        str(quality_state),
        promotable,
    )


def _canonical_ui_integer(
    value: str,
    label: str,
    minimum: int,
    maximum: int,
) -> int:
    if (
        not value
        or not value.isascii()
        or not value.isdecimal()
        or (len(value) > 1 and value.startswith("0"))
    ):
        raise RuntimeBuildError(f"{label} is not a canonical decimal integer")
    parsed = int(value)
    if not minimum <= parsed <= maximum:
        raise RuntimeBuildError(f"{label} is outside its exact range")
    return parsed


def _validate_diplomacy_rollout(
    profile_id: str,
    runtime: Mapping[str, bool],
) -> None:
    if (
        runtime.get("diplomacy")
        and profile_id not in _DIPLOMACY_ROLLOUT_PROFILE_IDS
    ):
        raise RuntimeBuildError(
            "Diplomacy V1 remains fail-closed outside its pinned rollout "
            "profiles"
        )


def _validate_diplomacy_rules(
    block: object,
    runtime: Mapping[str, bool] | None,
) -> dict[str, int] | None:
    """Validate the complete, pinned V1 diplomacy balance contract."""

    enabled = bool(runtime and runtime.get("enabled") and runtime.get("diplomacy"))
    if block is None:
        if enabled:
            raise RuntimeBuildError(
                "runtime.diplomacy requires profile.diplomacy_rules"
            )
        return None
    if not enabled:
        raise RuntimeBuildError(
            "diplomacy_rules requires runtime.enabled and runtime.diplomacy"
        )
    if not isinstance(block, Mapping):
        raise RuntimeBuildError("profile.diplomacy_rules must be an object")
    _exact_keys(block, _DIPLOMACY_RULES_KEYS, "profile.diplomacy_rules")
    parsed: dict[str, int] = {}
    for key in sorted(_DIPLOMACY_RULES_KEYS):
        value = block[key]
        if isinstance(value, bool) or not isinstance(value, int):
            raise RuntimeBuildError(
                f"profile.diplomacy_rules.{key} must be an integer"
            )
        if value != _DIPLOMACY_RULES_V1[key]:
            raise RuntimeBuildError(
                f"profile.diplomacy_rules.{key} must equal the pinned V1 "
                f"value {_DIPLOMACY_RULES_V1[key]}"
            )
        parsed[key] = value
    return parsed


def _canonical_ui_relative(value: str, label: str) -> str:
    if not value or "\\" in value or "\x00" in value:
        raise RuntimeBuildError(f"{label} is not a canonical relative path")
    pure = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if (
        pure.is_absolute()
        or windows.is_absolute()
        or bool(windows.drive)
        or pure.as_posix() != value
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise RuntimeBuildError(f"{label} is not a safe relative path")
    return value


def _crc32_file(path: Path) -> str:
    checksum = 0
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            checksum = zlib.crc32(chunk, checksum)
    return f"{checksum & 0xFFFFFFFF:08x}"


def _ui_header(lines: list[str], index: int, key: str) -> str:
    fields = lines[index].split("\t")
    if len(fields) != 2 or fields[0] != key or not fields[1]:
        raise RuntimeBuildError(f"UI v2 header {key!r} changed")
    return fields[1]


def parse_ui_texture_runtime_manifest_v2(
    mod_root: Path,
    *,
    expected_source_manifest_sha256: str,
    expected_quality_policy_sha256: str,
    expected_editor_source_sha256: str,
    expected_entry_count: int,
    max_resident_bytes: int,
) -> UiTextureRuntimeManifest:
    """Validate the final direct-BC7 UI manifest and every referenced bundle."""

    pins = (
        expected_source_manifest_sha256,
        expected_quality_policy_sha256,
        expected_editor_source_sha256,
    )
    if any(_UI_SHA256_RE.fullmatch(value) is None for value in pins):
        raise RuntimeBuildError("UI v2 expected provenance pins are invalid")
    if (
        isinstance(expected_entry_count, bool)
        or not isinstance(expected_entry_count, int)
        or not 1 <= expected_entry_count <= _UI_ENTRY_MAX
        or isinstance(max_resident_bytes, bool)
        or not isinstance(max_resident_bytes, int)
        or max_resident_bytes < 1
    ):
        raise RuntimeBuildError("UI v2 expected count or resident budget is invalid")

    root = Path(mod_root).resolve(strict=True)
    manifest_path = root.joinpath(*PurePosixPath(_UI_V2_MANIFEST_PATH).parts)
    payload = _read_stable_payload(
        manifest_path,
        maximum_bytes=UI_MAX_MANIFEST_BYTES,
        label="UI texture v2 manifest",
    )
    if (
        payload.startswith(b"\xef\xbb\xbf")
        or not payload.endswith(b"\n")
        or payload.endswith(b"\n\n")
        or b"\r" in payload
    ):
        raise RuntimeBuildError("UI texture v2 manifest is not BOM-free UTF-8/LF")
    try:
        lines = payload[:-1].decode("utf-8", errors="strict").split("\n")
    except UnicodeError as exc:
        raise RuntimeBuildError("UI texture v2 manifest is not strict UTF-8") from exc
    if len(lines) < 22 or lines[0] != UI_RUNTIME_MANIFEST_SCHEMA:
        raise RuntimeBuildError("UI texture v2 manifest schema or shape changed")

    exact_headers = {
        1: ("source_schema", UI_SOURCE_SCHEMA),
        4: ("quality_policy_schema", UI_QUALITY_POLICY_SCHEMA),
        5: ("quality_policy_id", UI_QUALITY_POLICY_ID),
        7: ("quality_verifier_id", UI_QUALITY_VERIFIER_ID),
        8: ("encoder_id", UI_ENCODER_ID),
        10: ("unity_version", UI_UNITY_VERSION),
        11: ("unity_revision", UI_UNITY_REVISION),
        12: ("alpha_mode", UI_ALPHA_MODE),
        13: ("bc_block_padding", UI_BLOCK_PADDING_MODE),
    }
    for index, (key, value) in exact_headers.items():
        if lines[index] != f"{key}\t{value}":
            raise RuntimeBuildError(f"UI texture v2 header {key!r} changed")

    source_manifest_sha256 = _ui_header(
        lines, 2, "source_manifest_sha256"
    )
    source_entry_set_sha256 = _ui_header(
        lines, 3, "source_entry_set_sha256"
    )
    quality_policy_sha256 = _ui_header(lines, 6, "quality_policy_sha256")
    editor_source_sha256 = _ui_header(lines, 9, "editor_source_sha256")
    if (
        source_manifest_sha256 != expected_source_manifest_sha256
        or quality_policy_sha256 != expected_quality_policy_sha256
        or editor_source_sha256 != expected_editor_source_sha256
        or _UI_SHA256_RE.fullmatch(source_entry_set_sha256) is None
    ):
        raise RuntimeBuildError("UI texture v2 manifest provenance changed")

    entry_count = _canonical_ui_integer(
        _ui_header(lines, 14, "entry_count"),
        "UI v2 entry_count",
        1,
        _UI_ENTRY_MAX,
    )
    bundle_count = _canonical_ui_integer(
        _ui_header(lines, 15, "bundle_count"),
        "UI v2 bundle_count",
        1,
        _UI_ENTRY_MAX,
    )
    declared_gpu_bytes = _canonical_ui_integer(
        _ui_header(lines, 16, "declared_gpu_bytes"),
        "UI v2 declared_gpu_bytes",
        1,
        _UI_TOTAL_GPU_MAX,
    )
    declared_resident_bytes = _canonical_ui_integer(
        _ui_header(lines, 17, "declared_resident_charge_bytes"),
        "UI v2 declared_resident_charge_bytes",
        1,
        max_resident_bytes,
    )
    if entry_count != expected_entry_count or bundle_count != entry_count:
        raise RuntimeBuildError("UI v2 one-bundle-per-entry count changed")
    bundle_columns = (
        "bundle\tid\tplugin_relative_path\tsha256\tsize_bytes\tcrc32"
        "\tunity_hash128"
    )
    texture_columns = (
        "texture\tnoesis_path\tvirtual_relative_path\tbundle_id\taddress"
        "\tsource_png_sha256\tpremultiplied_rgba_sha256"
        "\tlogical_width\tlogical_height\tstorage_width\tstorage_height"
        "\tgpu_bytes\tresident_charge_bytes\ttransient_peak_bytes"
        "\ttexture_contract_id\tbc_block_padding"
    )
    if lines[18] != bundle_columns or len(lines) != 20 + 2 * entry_count:
        raise RuntimeBuildError("UI v2 bundle columns or row count changed")

    bundles: list[UiTextureRuntimeBundle] = []
    by_id: dict[str, UiTextureRuntimeBundle] = {}
    prior_id: str | None = None
    for ordinal in range(bundle_count):
        fields = lines[19 + ordinal].split("\t")
        if len(fields) != 7 or fields[0] != "bundle":
            raise RuntimeBuildError(f"UI v2 bundle row {ordinal} shape changed")
        entry_id, relative, digest, size_text, crc32, unity_hash128 = fields[1:]
        relative = _canonical_ui_relative(relative, "UI v2 bundle path")
        name = PurePosixPath(relative).name
        if (
            _UI_ID_RE.fullmatch(entry_id) is None
            or (prior_id is not None and prior_id >= entry_id)
            or entry_id in by_id
            or not relative.startswith(_UI_BUNDLE_PREFIX)
            or "/" in relative[len(_UI_BUNDLE_PREFIX) :]
            or _UI_BUNDLE_RE.fullmatch(name) is None
            or _UI_SHA256_RE.fullmatch(digest) is None
            or _UI_CRC32_RE.fullmatch(crc32) is None
            or _UI_HASH128_RE.fullmatch(unity_hash128) is None
        ):
            raise RuntimeBuildError(f"UI v2 bundle row {ordinal} identity changed")
        size_bytes = _canonical_ui_integer(
            size_text,
            f"UI v2 bundle row {ordinal} size_bytes",
            1,
            _UI_BUNDLE_MAX_BYTES,
        )
        bundle = UiTextureRuntimeBundle(
            entry_id=entry_id,
            relative_path=relative,
            sha256=digest,
            size_bytes=size_bytes,
            crc32=crc32,
            unity_hash128=unity_hash128,
        )
        bundles.append(bundle)
        by_id[entry_id] = bundle
        prior_id = entry_id

    texture_columns_index = 19 + bundle_count
    if lines[texture_columns_index] != texture_columns:
        raise RuntimeBuildError("UI v2 texture columns changed")
    entries: list[UiTextureRuntimeEntry] = []
    used_bundles: set[str] = set()
    seen_noesis: set[str] = set()
    seen_virtual: set[str] = set()
    prior_noesis: str | None = None
    actual_gpu = 0
    actual_resident = 0
    for ordinal in range(entry_count):
        fields = lines[texture_columns_index + 1 + ordinal].split("\t")
        if len(fields) != 16 or fields[0] != "texture":
            raise RuntimeBuildError(f"UI v2 texture row {ordinal} shape changed")
        (
            noesis,
            virtual,
            bundle_id,
            address,
            source_png_sha256,
            premultiplied_rgba_sha256,
            logical_width_text,
            logical_height_text,
            storage_width_text,
            storage_height_text,
            gpu_text,
            resident_text,
            transient_text,
            texture_contract_id,
            padding,
        ) = fields[1:]
        noesis = _canonical_ui_relative(noesis, "UI v2 Noesis path")
        virtual = _canonical_ui_relative(virtual, "UI v2 virtual path")
        folded_noesis = noesis.casefold()
        folded_virtual = virtual.casefold()
        bundle = by_id.get(bundle_id)
        if (
            not noesis.startswith("Assets/GUI/")
            or (prior_noesis is not None and prior_noesis >= noesis)
            or folded_noesis in seen_noesis
            or folded_virtual in seen_virtual
            or bundle is None
            or bundle_id in used_bundles
            or _UI_SHA256_RE.fullmatch(source_png_sha256) is None
            or _UI_SHA256_RE.fullmatch(premultiplied_rgba_sha256) is None
            or texture_contract_id
            not in {TEXTURE_CONTRACT_ID_POINT, TEXTURE_CONTRACT_ID_BILINEAR}
            or padding != UI_BLOCK_PADDING_MODE
        ):
            raise RuntimeBuildError(f"UI v2 texture row {ordinal} identity changed")
        path_hash16 = hashlib.sha256(noesis.encode("utf-8")).hexdigest()[:16]
        expected_bundle_path = (
            f"{_UI_BUNDLE_PREFIX}sede.ui.{path_hash16}.bc7.v1"
        )
        if (
            bundle.relative_path != expected_bundle_path
            or virtual != f"Runtime/UiTextures/virtual/{path_hash16}.png"
            or address != f"sede/ui/{path_hash16}/texture"
        ):
            raise RuntimeBuildError(f"UI v2 texture row {ordinal} path binding changed")
        logical_width = _canonical_ui_integer(
            logical_width_text, "UI v2 logical_width", 1, _UI_DIMENSION_MAX
        )
        logical_height = _canonical_ui_integer(
            logical_height_text, "UI v2 logical_height", 1, _UI_DIMENSION_MAX
        )
        storage_width = _canonical_ui_integer(
            storage_width_text, "UI v2 storage_width", 1, _UI_DIMENSION_MAX
        )
        storage_height = _canonical_ui_integer(
            storage_height_text, "UI v2 storage_height", 1, _UI_DIMENSION_MAX
        )
        gpu_bytes = _canonical_ui_integer(
            gpu_text, "UI v2 gpu_bytes", 1, _UI_TOTAL_GPU_MAX
        )
        resident_bytes = _canonical_ui_integer(
            resident_text, "UI v2 resident_charge_bytes", 1, max_resident_bytes
        )
        transient_bytes = _canonical_ui_integer(
            transient_text, "UI v2 transient_peak_bytes", 1, 2 * 1024 * 1024 * 1024
        )
        expected_storage_width = (logical_width + 3) // 4 * 4
        expected_storage_height = (logical_height + 3) // 4 * 4
        try:
            expected_gpu = bc7_gpu_bytes(storage_width, storage_height)
            expected_resident = resident_charge_bytes(expected_gpu)
            expected_transient = transient_peak_bytes(
                expected_gpu, bundle.size_bytes
            )
        except UiAssetBundleError as exc:
            raise RuntimeBuildError("UI v2 footprint formula rejected a row") from exc
        if (
            storage_width != expected_storage_width
            or storage_height != expected_storage_height
            or gpu_bytes != expected_gpu
            or resident_bytes != expected_resident
            or transient_bytes != expected_transient
        ):
            raise RuntimeBuildError(f"UI v2 texture row {ordinal} byte formula changed")
        actual_gpu += gpu_bytes
        actual_resident += resident_bytes
        entries.append(UiTextureRuntimeEntry(noesis, bundle_id))
        used_bundles.add(bundle_id)
        seen_noesis.add(folded_noesis)
        seen_virtual.add(folded_virtual)
        prior_noesis = noesis
    if (
        used_bundles != set(by_id)
        or actual_gpu != declared_gpu_bytes
        or actual_resident != declared_resident_bytes
    ):
        raise RuntimeBuildError("UI v2 declared totals or bundle use changed")

    expected_bundle_paths = {bundle.relative_path for bundle in bundles}
    bundle_root = root.joinpath(*PurePosixPath(_UI_BUNDLE_PREFIX.rstrip("/")).parts)
    if not bundle_root.is_dir() or bundle_root.is_symlink():
        raise RuntimeBuildError("UI v2 bundle root is missing or linked")
    actual_bundle_paths: set[str] = set()
    for candidate in bundle_root.rglob("*"):
        relative = candidate.relative_to(root).as_posix()
        if candidate.is_symlink() or not candidate.is_file():
            raise RuntimeBuildError(f"UI v2 bundle root contains an unsafe entry: {relative}")
        actual_bundle_paths.add(relative)
    if actual_bundle_paths != expected_bundle_paths:
        raise RuntimeBuildError("UI v2 bundle file set differs from its manifest")
    for bundle in bundles:
        path = root.joinpath(*PurePosixPath(bundle.relative_path).parts)
        before = path.stat()
        if (
            before.st_size != bundle.size_bytes
            or sha256_file(path) != bundle.sha256
            or _crc32_file(path) != bundle.crc32
        ):
            raise RuntimeBuildError(f"UI v2 bundle payload changed: {bundle.relative_path}")
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise RuntimeBuildError(f"UI v2 bundle changed while hashing: {bundle.relative_path}")

    return UiTextureRuntimeManifest(
        path=manifest_path,
        sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
        entry_count=entry_count,
        source_manifest_sha256=source_manifest_sha256,
        source_entry_set_sha256=source_entry_set_sha256,
        quality_policy_sha256=quality_policy_sha256,
        editor_source_sha256=editor_source_sha256,
        declared_gpu_bytes=declared_gpu_bytes,
        declared_resident_charge_bytes=declared_resident_bytes,
        bundles=tuple(bundles),
        entries=tuple(entries),
    )


def _ui_texture_manifest(
    mod_root: Path,
    selection: UiTextureBackendSelection | None,
    *,
    max_resident_bytes: int,
) -> tuple[_CompiledPayloadAnchor, RuntimeArtifact | None]:
    root = Path(mod_root).resolve(strict=True)
    legacy_path = root.joinpath(*PurePosixPath(_UI_V1_MANIFEST_PATH).parts)
    v2_path = root.joinpath(*PurePosixPath(_UI_V2_MANIFEST_PATH).parts)
    bundle_root = root.joinpath(*PurePosixPath(_UI_BUNDLE_PREFIX.rstrip("/")).parts)
    if legacy_path.exists():
        raise RuntimeBuildError("The removed UI PNG/RGBA v1 manifest is still active")
    if selection is None:
        if v2_path.exists() or bundle_root.exists():
            raise RuntimeBuildError("UI v2 payload exists without an explicit profile backend")
        return _DISABLED_PAYLOAD_ANCHOR, None

    gui_root = root / "Override" / "Assets" / "GUI"
    active_pngs = (
        sorted(
            path.relative_to(root).as_posix()
            for path in gui_root.rglob("*")
            if path.is_file() and path.suffix.casefold() == ".png"
        )
        if gui_root.is_dir()
        else []
    )
    if active_pngs:
        raise RuntimeBuildError(
            f"UI v2 backend forbids active GUI PNGs: {active_pngs}"
        )
    parsed = parse_ui_texture_runtime_manifest_v2(
        root,
        expected_source_manifest_sha256=selection.source_manifest_sha256,
        expected_quality_policy_sha256=selection.quality_policy_sha256,
        expected_editor_source_sha256=selection.editor_source_sha256,
        expected_entry_count=selection.expected_entry_count,
        max_resident_bytes=max_resident_bytes,
    )
    anchor = _CompiledPayloadAnchor(
        True,
        parsed.sha256,
        parsed.size_bytes,
        parsed.entry_count,
        schema="stronghold-europe-ui-textures-v2",
        backend_kind=UI_BACKEND_KIND,
        quality_state="frozen",
        promotable=True,
    )
    artifact = RuntimeArtifact(
        parsed.path,
        "runtime_ui_texture_contract",
        "generated:config/ui-textures-bc7-v1.json",
        {
            "kind": "stronghold_europe_ui_textures_v2",
            "manifest_sha256": parsed.sha256,
            "entry_count": parsed.entry_count,
            "bundle_count": len(parsed.bundles),
            "declared_gpu_bytes": parsed.declared_gpu_bytes,
            "declared_resident_charge_bytes": parsed.declared_resident_charge_bytes,
            "source_manifest_sha256": parsed.source_manifest_sha256,
            "source_entry_set_sha256": parsed.source_entry_set_sha256,
            "quality_policy_sha256": parsed.quality_policy_sha256,
            "editor_source_sha256": parsed.editor_source_sha256,
        },
    )
    return anchor, artifact


def _pcm_stream_manifest_text(tracks: list[dict[str, Any]]) -> str:
    lines = [
        "stronghold-europe-pcm-stream\t1",
        "payload_root\tRuntime/Audio",
        "max_active_streams\t2",
        "buffer_budget_bytes\t16777216",
        "buffer_bytes_per_stream\t1048576",
        f"track_count\t{len(tracks)}",
        "track\trequest\tfile\tfile_size\tsha256\taudio_format\tchannels"
        "\tsample_rate\tbits_per_sample\tblock_align\tdata_size",
    ]
    for track in tracks:
        request = str(track["output_file"])
        lines.append(
            "\t".join(
                str(value)
                for value in (
                    "track",
                    request,
                    request,
                    track["file_size"],
                    track["sha256"],
                    track["audio_format"],
                    track["channels"],
                    track["sample_rate"],
                    track["bits_per_sample"],
                    track["block_align"],
                    track["data_size"],
                )
            )
        )
    return "\n".join(lines) + "\n"


def _csharp_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _csharp_string_array(values: list[str]) -> str:
    return ", ".join(_csharp_string(value) for value in values)


def _generated_contract_text(
    spec: dict[str, Any],
    manifest_sha256: str,
    prerequisites: RuntimePrerequisiteVerification,
    selection: Mapping[str, bool],
    profile_id: str,
    roster_spec: RosterTextSpec | None,
    roster_manifest_sha256: str,
    runtime_source_sha256: str,
    asset_stream: _CompiledPayloadAnchor,
    ui_textures: _CompiledPayloadAnchor,
    pcm_stream: _CompiledPayloadAnchor,
    fortifications: _FortificationContractAnchor,
    dock_rules: Mapping[str, int] | None = None,
    diplomacy_rules: Mapping[str, int] | None = None,
) -> str:
    pins = {entry.id: entry for entry in prerequisites.files}
    ordered = [pins[dependency_id] for dependency_id in _PREREQUISITE_ORDER]
    track_ids = ", ".join(str(track["id"]) for track in spec["tracks"])
    mvid_attestation = "".join(
        "[assembly: System.Reflection.AssemblyMetadata("
        + _csharp_string("StrongholdEurope.PrerequisiteMvid." + entry.id)
        + ", "
        + _csharp_string(entry.mvid)
        + ")]\n"
        for entry in ordered
    )
    roster_enabled = roster_spec is not None
    if roster_enabled != selection["unit_roster_names"]:
        raise RuntimeBuildError("Generated roster selection/spec state is inconsistent")
    roster_source_sha256 = roster_spec.source_sha256 if roster_spec else ""
    roster_entries_sha256 = roster_spec.entries_sha256 if roster_spec else ""
    roster_originals_sha256 = (
        roster_spec.target_originals_sha256 if roster_spec else ""
    )
    roster_hud_sha256 = roster_spec.hud_xaml_sha256 if roster_spec else ""
    roster_hud_buildings_sha256 = (
        roster_spec.hud_buildings_xaml_sha256 if roster_spec else ""
    )
    roster_target_text_sha256 = roster_spec.target_text_sha256 if roster_spec else ""
    roster_target_text_size = roster_spec.target_text_size if roster_spec else 0
    roster_hud_size = roster_spec.hud_xaml_size if roster_spec else 0
    roster_hud_buildings_size = (
        roster_spec.hud_buildings_xaml_size if roster_spec else 0
    )
    roster_entry_count = len(roster_spec.entries) if roster_spec else 0
    roster_hud_count = len(roster_spec.hud_bindings) if roster_spec else 0
    route_entries = music_route_entries()
    return (
        "// Generated by stronghold_europe_de.runtime_build; do not edit.\n"
        + mvid_attestation
        + "namespace StrongholdEuropeDE.Runtime\n"
        "{\n"
        "    internal static class GeneratedAudioContract\n"
        "    {\n"
        f"        internal const string PluginId = {_csharp_string(_PLUGIN_ID)};\n"
        f"        internal const string SourceBuildId = {_csharp_string(spec['source_build_id'])};\n"
        f"        internal const string TargetBuildId = {_csharp_string(spec['target_build_id'])};\n"
        f"        internal const string ManifestSha256 = {_csharp_string(manifest_sha256)};\n"
        f"        internal const string TargetAssemblySha256 = {_csharp_string(pins['assembly_csharp'].sha256)};\n"
        f"        internal const string ScriptExtenderVersion = {_csharp_string(pins['shcdese'].assembly_version)};\n"
        f"        internal const string ScriptExtenderSha256 = {_csharp_string(pins['shcdese'].sha256)};\n"
        f"        internal const string RuntimePrerequisiteConfigId = {_csharp_string(prerequisites.config_id)};\n"
        f"        internal const string RuntimeSourceSetSha256 = {_csharp_string(runtime_source_sha256)};\n"
        f"        internal static readonly int[] TrackIds = new[] {{ {track_ids} }};\n"
        f"        internal const int PrerequisiteCount = {len(ordered)};\n"
        "        internal static readonly string[] PrerequisiteIds = new[] { "
        + _csharp_string_array([entry.id for entry in ordered])
        + " };\n"
        "        internal static readonly string[] PrerequisiteRelativePaths = new[] { "
        + _csharp_string_array([entry.relative_path for entry in ordered])
        + " };\n"
        "        internal static readonly long[] PrerequisiteSizes = new long[] { "
        + ", ".join(str(entry.size) + "L" for entry in ordered)
        + " };\n"
        "        internal static readonly string[] PrerequisiteSha256 = new[] { "
        + _csharp_string_array([entry.sha256 for entry in ordered])
        + " };\n"
        "        internal static readonly string[] PrerequisiteAssemblyNames = new[] { "
        + _csharp_string_array([entry.assembly_name for entry in ordered])
        + " };\n"
        "        internal static readonly string[] PrerequisiteAssemblyVersions = new[] { "
        + _csharp_string_array([entry.assembly_version for entry in ordered])
        + " };\n"
        "        internal static readonly string[] PrerequisiteMvids = new[] { "
        + _csharp_string_array([entry.mvid for entry in ordered])
        + " };\n"
        "    }\n"
        "\n"
        "    internal static class GeneratedRosterContract\n"
        "    {\n"
        f"        internal static readonly bool Enabled = {str(roster_enabled).lower()};\n"
        f"        internal const string EnabledText = {_csharp_string(str(roster_enabled).lower())};\n"
        f"        internal const string ManifestSha256 = {_csharp_string(roster_manifest_sha256)};\n"
        f"        internal const string SourceSha256 = {_csharp_string(roster_source_sha256)};\n"
        f"        internal const string EntriesSha256 = {_csharp_string(roster_entries_sha256)};\n"
        f"        internal const string TargetOriginalsSha256 = {_csharp_string(roster_originals_sha256)};\n"
        f"        internal const string TargetTextSha256 = {_csharp_string(roster_target_text_sha256)};\n"
        f"        internal const long TargetTextSize = {roster_target_text_size}L;\n"
        f"        internal const string HudXamlSha256 = {_csharp_string(roster_hud_sha256)};\n"
        f"        internal const long HudXamlSize = {roster_hud_size}L;\n"
        f"        internal const string HudBuildingsXamlSha256 = {_csharp_string(roster_hud_buildings_sha256)};\n"
        f"        internal const long HudBuildingsXamlSize = {roster_hud_buildings_size}L;\n"
        f"        internal const int EntryCount = {roster_entry_count};\n"
        f"        internal const int HudControlCount = {roster_hud_count};\n"
        "    }\n"
        "\n"
        "    internal static class GeneratedFoliageContract\n"
        "    {\n"
        f"        internal const int GroupCount = {len(_FOLIAGE_GROUPS)};\n"
        "        internal static readonly string[] GroupNames = new[] { "
        + _csharp_string_array(list(_FOLIAGE_GROUPS))
        + " };\n"
        "    }\n"
        "\n"
        "    internal static class GeneratedFarmPlacementContract\n"
        "    {\n"
        f"        internal static readonly bool Enabled = {str(bool(selection['farm_placement'])).lower()};\n"
        f"        internal const string EnabledText = {_csharp_string(str(bool(selection['farm_placement'])).lower())};\n"
        "    }\n"
        "\n"
        "    internal static class GeneratedWorkerMilitiaContract\n"
        "    {\n"
        f"        internal static readonly bool Enabled = {str(bool(selection['worker_militia'])).lower()};\n"
        f"        internal const string EnabledText = {_csharp_string(str(bool(selection['worker_militia'])).lower())};\n"
        f"        internal static readonly bool IsolatedCanary = {str(profile_id == 'worker-militia-canary').lower()};\n"
        "        internal const int DamageDivisor = 2;\n"
        # Calibrated 2026-08-29 from the live worker-militia-canary run, both
        # against reviewed runtime evidence (docs/MILIZ_KALIBRIERUNG_2026-08-29.md):
        #   - Hunter range: 20 vanilla-archer projectile samples, every shot
        #     inside configured_range=54 (euclidean-squared-inclusive metric,
        #     8 world tiles = 1 local tile). The mod gives the hunter the
        #     vanilla archer's own measured range, so the metric is identical.
        #   - Worker animation is NOT calibrated. The former majority-learned
        #     sprite-base theory was refuted on 2026-08-30: values changed by
        #     game and state, and an early five-sample value could remain wrong
        #     for the whole command. The false write stays gated off below.
        "        internal const bool HunterRangeCalibrated = true;\n"
        "        internal const string HunterRangeEvidence = "
        "\"canary-2026-08-29:20-archer-samples:range54:euclidean_squared_inclusive\";\n"
        # DRITTER FEHLSCHLAG, 30.08.2026 14:22. Der Schreibzugriff ist wieder
        # aus, und diesmal mit der Messung, die ihn begraebt.
        #
        # Was der Lauf zeigte: die Schreibung fand statt und HIELT - der
        # befohlene Jaeger trug ueber alle 90 Spurzeilen sprite=13, die Engine
        # setzte sie nicht zurueck. Das Feld ist also beschreibbar und wirksam.
        # Nur war der Wert falsch: geschrieben wurde bei
        # WalkStateEvidenceFloor = 5, also nach FUENF Beobachtungen.
        #
        # Lernkurve desselben Laufs, in zeitlicher Reihenfolge:
        #     Holzfaeller base=7  aus   5   <- geschrieben
        #     Jaeger      base=13 aus   5   <- geschrieben
        #     Holzfaeller base=0  aus 176
        #     Holzfaeller base=1  aus 391   <- Endstand
        #     Jaeger      base=0  aus 568   <- Endstand
        #
        # Und der Lauf davor endete beim Holzfaeller bei base=0 (115
        # Beobachtungen). Derselbe Typ, zwei Partien, zwei verschiedene
        # "Mehrheiten" - waehrend das kontrollierte Paar vom 30.08. 13:57 den
        # freien Holzfaeller ueber 90 Takte konstant auf sprite=0 zeigte.
        #
        # SCHLUSS: r_CurrentSpriteAnimationFrame ist KEINE Konstante je
        # Einheitentyp. Der Wert haengt an einem Zustand, den wir nicht
        # kennen (Traglast? Richtung? Wegabschnitt?). Eine Bevoelkerungs-
        # mehrheit darueber ist Raten mit Statistik obendrauf. Ein hoeherer
        # Boden repariert das nicht - er waehlt nur eine andere falsche Zahl.
        #
        # Der naechste Versuch darf kein vierter Anlauf auf dieses Feld sein.
        # Der aktuelle Quellstand fuegt dem Jaeger-FSM stattdessen den nativen
        # Bewegungszustand 0x65 hinzu. Das ist statisch und mechanisch geprueft,
        # aber noch nicht im Spiel bestaetigt. Die Schussanimation bleibt davon
        # getrennt und weiterhin offen; sie darf nicht als Nebenwirkung des
        # Bodenbefehls behauptet werden.
        "        internal const bool WorkerAnimationCalibrated = false;\n"
        "        internal const string WorkerAnimationEvidence = \"none\";\n"
        "        internal const bool WorkerWalkStateCalibrated = false;\n"
        "        internal const string NativeRangeMetric = \"euclidean_squared_inclusive\";\n"
        "        internal const int WorldTilesPerLocalTile = 8;\n"
        "        internal const int VanillaArcherAttackRange = 54;\n"
        "        internal const int HunterGuardRadius = 54;\n"
        "        internal const int WoodcutterGuardRadius = 6;\n"
        "        internal const int HunterAttackRange = 54;\n"
        "        internal const int WoodcutterAttackRange = 1;\n"
        "        internal const int HunterPursuitRadius = 57;\n"
        "        internal const int WoodcutterPursuitRadius = 9;\n"
        "        internal const int HunterAttackCooldownMilliseconds = 1400;\n"
        "        internal const int WoodcutterAttackCooldownMilliseconds = 900;\n"
        "        internal const int MoveRefreshMilliseconds = 750;\n"
        "        internal const int ReturnArrivalRadius = 1;\n"
        "        internal const int ScanIntervalMilliseconds = 250;\n"
        "        internal const int HoldDurationMilliseconds = 10000;\n"
        "    }\n"
        "\n"
        "    internal static class GeneratedFortificationContract\n"
        "    {\n"
        f"        internal static readonly bool Enabled = {str(fortifications.enabled).lower()};\n"
        f"        internal const string EnabledText = {_csharp_string(str(fortifications.enabled).lower())};\n"
        f"        internal static readonly bool IsolatedCanary = {str(profile_id in _FORTIFICATION_CANARY_PROFILE_IDS).lower()};\n"
        f"        internal const string Schema = {_csharp_string(fortifications.schema)};\n"
        f"        internal const int CatalogVersion = {fortifications.recipe_version};\n"
        f"        internal const int RecipeVersion = {fortifications.recipe_version};\n"
        f"        internal const int VariantCount = {fortifications.variant_count};\n"
        f"        internal const int CatalogRecordCount = {fortifications.record_count};\n"
        f"        internal const int RecordCount = {fortifications.record_count};\n"
        f"        internal const string CatalogSourceRelativePath = {_csharp_string(_FORTIFICATION_SOURCE_PATH)};\n"
        f"        internal const long CatalogSourceSize = {fortifications.source_size}L;\n"
        f"        internal const string CatalogSourceSha256 = {_csharp_string(fortifications.source_sha256)};\n"
        f"        internal const string CatalogTsvRelativePath = {_csharp_string(_FORTIFICATION_RUNTIME_PATH)};\n"
        f"        internal const long CatalogTsvSize = {fortifications.tsv_size}L;\n"
        f"        internal const string CatalogTsvSha256 = {_csharp_string(fortifications.tsv_sha256)};\n"
        f"        internal const string SaveDataIdentifier = {_csharp_string(_FORTIFICATION_SAVE_DATA_ID)};\n"
        f"        internal const string HudLogicalPath = {_csharp_string(_FORTIFICATION_HUD_LOGICAL_PATH)};\n"
        f"        internal const string HudBaseRelativePath = {_csharp_string(_FORTIFICATION_HUD_BASE_RELATIVE_PATH)};\n"
        f"        internal const long HudBaseSize = {_FORTIFICATION_HUD_BASE_SIZE}L;\n"
        f"        internal const string HudBaseSha256 = {_csharp_string(_FORTIFICATION_HUD_BASE_SHA256)};\n"
        f"        internal const string HudPatchRelativePath = {_csharp_string(_FORTIFICATION_HUD_PATCH_RELATIVE_PATH)};\n"
        f"        internal const long HudPatchSize = {fortifications.hud_patch_size}L;\n"
        f"        internal const string HudPatchSha256 = {_csharp_string(fortifications.hud_patch_sha256)};\n"
        f"        internal static readonly bool HudIncludesDockContributor = {str(bool(selection['dock_placement']) and fortifications.enabled).lower()};\n"
        f"        internal static readonly bool HudIncludesFortificationContributor = {str(fortifications.enabled).lower()};\n"
        "        internal const bool GameplayCostTransactionsMeasured = false;\n"
        "        internal const bool ManagedPlacementMeasured = false;\n"
        "        internal const bool CompleteDamageCoverageMeasured = false;\n"
        "        internal const bool VisualRecipesMeasured = false;\n"
        "        internal const bool WoodenGateMeasured = false;\n"
        "        internal const bool WoodenStairsMeasured = false;\n"
        "        internal const bool WoodenPlatformMeasured = false;\n"
        "        internal const bool SaveRoundTripMeasured = false;\n"
        f"        internal const long SpriteCatalogSize = {fortifications.sprite_catalog_size}L;\n"
        f"        internal const string SpriteCatalogSha256 = {_csharp_string(fortifications.sprite_catalog_sha256)};\n"
        "    }\n"
        "\n"
        "    internal static class GeneratedDiplomacyContract\n"
        "    {\n"
        f"        internal static readonly bool Enabled = {str(bool(selection['diplomacy'])).lower()};\n"
        f"        internal const string EnabledText = {_csharp_string(str(bool(selection['diplomacy'])).lower())};\n"
        f"        internal static readonly bool IsolatedCanary = {str(profile_id == 'diplomacy-v1-canary').lower()};\n"
        "        internal const string SaveDataIdentifier = \"StrongholdEuropeDE.Diplomacy.v1\";\n"
        f"        internal const int EconomyBuildingMaterialPercent = {(diplomacy_rules or _DIPLOMACY_RULES_V1)['economy_building_material_percent']};\n"
        f"        internal const int LordMilitaryValue = {(diplomacy_rules or _DIPLOMACY_RULES_V1)['lord_military_value']};\n"
        f"        internal const int UnknownUnitHealthDivisor = {(diplomacy_rules or _DIPLOMACY_RULES_V1)['unknown_unit_health_divisor']};\n"
        f"        internal const int UnknownUnitValueMinimum = {(diplomacy_rules or _DIPLOMACY_RULES_V1)['unknown_unit_value_minimum']};\n"
        f"        internal const int UnknownUnitValueMaximum = {(diplomacy_rules or _DIPLOMACY_RULES_V1)['unknown_unit_value_maximum']};\n"
        f"        internal const int TargetBaseValue = {(diplomacy_rules or _DIPLOMACY_RULES_V1)['target_base_value']};\n"
        f"        internal const int EconomyWeightBasisPoints = {(diplomacy_rules or _DIPLOMACY_RULES_V1)['economy_weight_basis_points']};\n"
        f"        internal const int MilitaryWeightBasisPoints = {(diplomacy_rules or _DIPLOMACY_RULES_V1)['military_weight_basis_points']};\n"
        f"        internal const int PersonalityBaseBasisPoints = {(diplomacy_rules or _DIPLOMACY_RULES_V1)['personality_base_basis_points']};\n"
        f"        internal const int PersonalityMarginBasisPoints = {(diplomacy_rules or _DIPLOMACY_RULES_V1)['personality_margin_basis_points']};\n"
        f"        internal const int TargetMinimum = {(diplomacy_rules or _DIPLOMACY_RULES_V1)['target_minimum']};\n"
        f"        internal const int TargetMaximum = {(diplomacy_rules or _DIPLOMACY_RULES_V1)['target_maximum']};\n"
        f"        internal const int TargetRoundStep = {(diplomacy_rules or _DIPLOMACY_RULES_V1)['target_round_step']};\n"
        f"        internal const int GoodwillGraceDays = {(diplomacy_rules or _DIPLOMACY_RULES_V1)['goodwill_grace_days']};\n"
        f"        internal const int GoodwillDecayPercent = {(diplomacy_rules or _DIPLOMACY_RULES_V1)['goodwill_decay_percent']};\n"
        f"        internal const int OfferBasePercent = {(diplomacy_rules or _DIPLOMACY_RULES_V1)['offer_base_percent']};\n"
        f"        internal const int OfferMarginTenthsPercent = {(diplomacy_rules or _DIPLOMACY_RULES_V1)['offer_margin_tenths_percent']};\n"
        f"        internal const int OfferMinimumPercent = {(diplomacy_rules or _DIPLOMACY_RULES_V1)['offer_minimum_percent']};\n"
        f"        internal const int OfferMaximumPercent = {(diplomacy_rules or _DIPLOMACY_RULES_V1)['offer_maximum_percent']};\n"
        f"        internal const int OfferAdditionalGiftPercent = {(diplomacy_rules or _DIPLOMACY_RULES_V1)['offer_additional_gift_percent']};\n"
        f"        internal const int OfferRejectionLockDays = {(diplomacy_rules or _DIPLOMACY_RULES_V1)['offer_rejection_lock_days']};\n"
        f"        internal const int DemandLifetimeDays = {(diplomacy_rules or _DIPLOMACY_RULES_V1)['demand_lifetime_days']};\n"
        f"        internal const int MaximumDemandGoods = {(diplomacy_rules or _DIPLOMACY_RULES_V1)['maximum_demand_goods']};\n"
        f"        internal const int NewAllianceGraceDays = {(diplomacy_rules or _DIPLOMACY_RULES_V1)['new_alliance_grace_days']};\n"
        f"        internal const int StartingAllianceGraceDays = {(diplomacy_rules or _DIPLOMACY_RULES_V1)['starting_alliance_grace_days']};\n"
        f"        internal const int LoyaltyBaseDecayBasisPoints = {(diplomacy_rules or _DIPLOMACY_RULES_V1)['loyalty_base_decay_basis_points']};\n"
        f"        internal const int LoyaltyMarginDecayBasisPoints = {(diplomacy_rules or _DIPLOMACY_RULES_V1)['loyalty_margin_decay_basis_points']};\n"
        f"        internal const int UltimatumThresholdPercent = {(diplomacy_rules or _DIPLOMACY_RULES_V1)['ultimatum_threshold_percent']};\n"
        f"        internal const int UltimatumRestorePercent = {(diplomacy_rules or _DIPLOMACY_RULES_V1)['ultimatum_restore_percent']};\n"
        f"        internal const int UltimatumLifetimeDays = {(diplomacy_rules or _DIPLOMACY_RULES_V1)['ultimatum_lifetime_days']};\n"
        f"        internal const int BreakLockDays = {(diplomacy_rules or _DIPLOMACY_RULES_V1)['break_lock_days']};\n"
        "    }\n"
        "\n"
        "    internal static class GeneratedDockPlacementContract\n"
        "    {\n"
        f"        internal static readonly bool Enabled = {str(bool(selection['dock_placement'])).lower()};\n"
        f"        internal const string EnabledText = {_csharp_string(str(bool(selection['dock_placement'])).lower())};\n"
        "    }\n"
        "\n"
        # Die Regelwerte sind SETZUNG des Profils, keine Messung; ohne Block
        # bleibt Enabled=false und die Bahn misst nur. Health als uint, weil
        # SetDefaultHealth(eStructs, uint) die native Tabelle so schreibt.
        "    internal static class GeneratedDockRulesContract\n"
        "    {\n"
        f"        internal static readonly bool Enabled = {str(dock_rules is not None).lower()};\n"
        f"        internal const string EnabledText = {_csharp_string(str(dock_rules is not None).lower())};\n"
        f"        internal const int WoodCost = {dock_rules['wood_cost'] if dock_rules is not None else 0};\n"
        f"        internal const int GoldCost = {dock_rules['gold_cost'] if dock_rules is not None else 0};\n"
        f"        internal const uint Health = {dock_rules['health'] if dock_rules is not None else 0}u;\n"
        "    }\n"
        "\n"
        "    internal static class GeneratedMusicRouteContract\n"
        "    {\n"
        f"        internal const string MapSha256 = {_csharp_string(music_route_sha256())};\n"
        f"        internal const int EntryCount = {len(route_entries)};\n"
        "        internal static readonly string[] RequestedFiles = new[] { "
        + _csharp_string_array([requested for requested, _ in route_entries])
        + " };\n"
        "        internal static readonly string[] ReplacementPaths = new[] { "
        + _csharp_string_array([replacement for _, replacement in route_entries])
        + " };\n"
        "    }\n"
        "\n"
        "    internal static class GeneratedAssetStreamContract\n"
        "    {\n"
        f"        internal static readonly bool Enabled = {str(asset_stream.enabled).lower()};\n"
        f"        internal const string EnabledText = {_csharp_string(str(asset_stream.enabled).lower())};\n"
        f"        internal const string IndexSha256 = {_csharp_string(asset_stream.sha256)};\n"
        f"        internal const long IndexSize = {asset_stream.size}L;\n"
        f"        internal const int GroupCount = {asset_stream.count};\n"
        f"        internal const int VanillaOmittedGroupCount = {asset_stream.omitted_count};\n"
        f"        internal const string BackendKind = {_csharp_string(asset_stream.backend_kind)};\n"
        f"        internal const string IndexSchema = {_csharp_string(asset_stream.schema)};\n"
        f"        internal const string QualityState = {_csharp_string(asset_stream.quality_state)};\n"
        f"        internal static readonly bool Promotable = {str(asset_stream.promotable).lower()};\n"
        "    }\n"
        "\n"
        "    internal static class GeneratedUiTextureContract\n"
        "    {\n"
        f"        internal static readonly bool Enabled = {str(ui_textures.enabled).lower()};\n"
        f"        internal const string EnabledText = {_csharp_string(str(ui_textures.enabled).lower())};\n"
        f"        internal const string ManifestSha256 = {_csharp_string(ui_textures.sha256)};\n"
        f"        internal const long ManifestSize = {ui_textures.size}L;\n"
        f"        internal const int EntryCount = {ui_textures.count};\n"
        "    }\n"
        "\n"
        "    internal static class GeneratedPcmStreamContract\n"
        "    {\n"
        f"        internal static readonly bool Enabled = {str(pcm_stream.enabled).lower()};\n"
        f"        internal const string EnabledText = {_csharp_string(str(pcm_stream.enabled).lower())};\n"
        f"        internal const string ManifestSha256 = {_csharp_string(pcm_stream.sha256)};\n"
        f"        internal const long ManifestSize = {pcm_stream.size}L;\n"
        f"        internal const int TrackCount = {pcm_stream.count};\n"
        "    }\n"
        "}\n"
    )


def _read_fourcc(stream: Any) -> bytes:
    value = stream.read(4)
    if len(value) != 4:
        raise RuntimeBuildError("Truncated WAV FourCC")
    return value


def validate_wav(path: Path, track: Mapping[str, Any]) -> None:
    before = path.stat()
    if before.st_size != track["file_size"]:
        raise RuntimeBuildError(
            f"WAV size mismatch for {path.name}: expected={track['file_size']} actual={before.st_size}"
        )
    digest = sha256_file(path)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise RuntimeBuildError(f"WAV changed while hashing: {path}")
    if digest != track["sha256"]:
        raise RuntimeBuildError(
            f"WAV SHA-256 mismatch for {path.name}: expected={track['sha256']} actual={digest}"
        )

    with path.open("rb") as stream:
        if _read_fourcc(stream) != b"RIFF":
            raise RuntimeBuildError(f"Not a RIFF WAV: {path}")
        riff_size = struct.unpack("<I", stream.read(4))[0]
        if riff_size != before.st_size - 8 or _read_fourcc(stream) != b"WAVE":
            raise RuntimeBuildError(f"Noncanonical RIFF/WAVE size/header: {path}")
        fmt: tuple[int, int, int, int, int, int] | None = None
        data_size: int | None = None
        while stream.tell() < before.st_size:
            if before.st_size - stream.tell() < 8:
                raise RuntimeBuildError(f"Truncated WAV chunk header: {path}")
            chunk_id = _read_fourcc(stream)
            chunk_size = struct.unpack("<I", stream.read(4))[0]
            start = stream.tell()
            end = start + chunk_size
            if end > before.st_size:
                raise RuntimeBuildError(f"WAV chunk exceeds file: {path}")
            if chunk_id == b"fmt ":
                if fmt is not None or chunk_size < 16:
                    raise RuntimeBuildError(f"Duplicate/short WAV fmt chunk: {path}")
                payload = stream.read(16)
                if len(payload) != 16:
                    raise RuntimeBuildError(f"Truncated WAV fmt chunk: {path}")
                fmt = struct.unpack("<HHIIHH", payload)
            elif chunk_id == b"data":
                if data_size is not None:
                    raise RuntimeBuildError(f"Duplicate WAV data chunk: {path}")
                data_size = chunk_size
            stream.seek(end + (chunk_size & 1))
            if stream.tell() > before.st_size:
                raise RuntimeBuildError(f"Missing WAV padding byte: {path}")
        expected_fmt = (
            track["audio_format"],
            track["channels"],
            track["sample_rate"],
            track["sample_rate"] * track["block_align"],
            track["block_align"],
            track["bits_per_sample"],
        )
        if fmt != expected_fmt or data_size != track["data_size"]:
            raise RuntimeBuildError(
                f"WAV PCM metadata mismatch for {path.name}: fmt={fmt} data={data_size}"
            )


def _verify_prerequisites(config: BuilderConfig) -> RuntimePrerequisiteVerification:
    if config.target.game_dir is None:
        raise RuntimeBuildError("Target game root is required for the runtime companion")
    config_path = config.project_root / "config" / "runtime-prerequisites.json"
    try:
        prerequisite_config = json.loads(config_path.read_text(encoding="utf-8"))
        # The historical v2 file defines only approved dependency paths and
        # roles. Its old 2.11 byte pins must not block or falsely certify newer
        # local game/SE combinations. Capture and enforce exact v3 byte+MVID
        # evidence for the *selected* reference root instead.
        from .runtime_reference_capture import capture_runtime_references
        reference_root = config.target.reference_root or config.target.game_dir
        measured, abi_layout = capture_runtime_references(
            prerequisite_config, reference_root
        )
        verification = verify_runtime_prerequisites(measured, reference_root)
        print(
            "[runtime] Exact source-assembly proof: SE "
            + verification.script_extender_version
            + ", native layout=" + abi_layout
            + ", SHA256/MVID checked for "
            + str(len(verification.files)) + " DLLs"
        )
    except (OSError, UnicodeError, json.JSONDecodeError, RuntimePrerequisiteError) as exc:
        raise RuntimeBuildError(
            "Runtime prerequisite gate rejected the local companion references"
        ) from exc
    by_id = {entry.id: entry for entry in verification.files}
    if any(dependency_id not in by_id for dependency_id in _PREREQUISITE_ORDER):
        raise RuntimeBuildError("Runtime prerequisite verification is incomplete")
    return verification


def _dotnet_environment(config: BuilderConfig) -> dict[str, str]:
    environment = os.environ.copy()
    environment["DOTNET_ADD_GLOBAL_TOOLS_TO_PATH"] = "0"
    environment["DOTNET_CLI_TELEMETRY_OPTOUT"] = "1"
    environment["DOTNET_NOLOGO"] = "1"
    environment["DOTNET_CLI_HOME"] = str(
        (config.output.cache_dir / "dotnet-home").resolve()
    )
    return environment


def _resolve_pinned_dotnet_sdk(config: BuilderConfig) -> tuple[str, dict[str, str]]:
    sdk_directory = find_dotnet_sdk(config.project_root)
    if sdk_directory is None:
        raise RuntimeBuildError(
            "A stable " + sdk_requirement()
            + " is needed to build the net481 companion; "
            "check PATH, DOTNET_ROOT or a portable SDK"
        )
    dotnet = str(sdk_directory / (
        "dotnet.exe" if (sdk_directory / "dotnet.exe").is_file() else "dotnet"
    ))
    environment = _dotnet_environment(config)
    try:
        sdk_probe = subprocess.run(
            [dotnet, "--version"],
            cwd=config.project_root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeBuildError("dotnet SDK probe could not run") from exc
    if sdk_probe.returncode != 0 or not sdk_supported(sdk_probe.stdout.strip()):
        raise RuntimeBuildError(
            "Runtime companion requires " + sdk_requirement() + "; actual="
            + repr(sdk_probe.stdout.strip())
        )
    print(f"[runtime] .NET SDK {sdk_probe.stdout.strip()} (net481)")
    return dotnet, environment


def preflight_runtime_toolchain(config: BuilderConfig, selection: object) -> None:
    """Reject a missing/wrong SDK before the image build opens its transaction."""

    runtime = _validate_runtime_selection(selection)
    if runtime["enabled"]:
        _resolve_pinned_dotnet_sdk(config)


def _build_companion(
    config: BuilderConfig,
    profile_id: str,
    generated_contract: Path,
    prerequisites: RuntimePrerequisiteVerification,
) -> Path:
    dotnet, environment = _resolve_pinned_dotnet_sdk(config)
    project = (
        config.project_root
        / "runtime"
        / "StrongholdEuropeDE.Runtime"
        / "StrongholdEuropeDE.Runtime.csproj"
    )
    if not project.is_file():
        raise RuntimeBuildError(f"Runtime companion project is missing: {project}")
    runtime_work = (config.output.work_dir / "runtime" / profile_id).resolve()
    obj = runtime_work / "obj"
    packages = (config.output.cache_dir / "dotnet-packages").resolve()
    by_id = {entry.id: entry for entry in prerequisites.files}
    # The byref-safe native-struct field adapter uses Unsafe.As/Add, which
    # ships alongside the installed Script Extender's System.Memory.dll.
    # Never fetch or substitute an assembly from another game installation.
    unsafe_reference = by_id["unsafe"].path
    if not unsafe_reference.is_file() or unsafe_reference.is_symlink():
        raise RuntimeBuildError(
            "Pinned extender's System.Runtime.CompilerServices.Unsafe.dll "
            "is required for native-interoperability adapters"
        )
    command = [
        dotnet,
        "build",
        str(project),
        "--configuration",
        "Release",
        "--nologo",
        f"-p:RuntimeWorkRoot={runtime_work}",
        f"-p:GeneratedContractPath={generated_contract}",
        f"-p:BaseIntermediateOutputPath={obj}{os.sep}",
        f"-p:MSBuildProjectExtensionsPath={obj}{os.sep}",
        f"-p:RestorePackagesPath={packages}",
        f"-p:BepInExReference={by_id['bepinex_core'].path}",
        f"-p:HarmonyReference={by_id['harmony'].path}",
        f"-p:SHCDESEReference={by_id['shcdese'].path}",
        f"-p:RedBirdCoreReference={by_id['redbird_core'].path}",
        f"-p:SystemMemoryReference={by_id['system_memory'].path}",
        f"-p:UnsafeReference={unsafe_reference}",
        f"-p:R3Reference={by_id['r3'].path}",
        f"-p:AssemblyCSharpReference={by_id['assembly_csharp'].path}",
        f"-p:NoesisReference={by_id['noesis_gui'].path}",
        f"-p:UnityEngineReference={by_id['unity_engine'].path}",
        f"-p:UnityEngineCoreModuleReference={by_id['unity_engine_core_module'].path}",
        f"-p:UnityEngineAssetBundleModuleReference={by_id['unity_engine_asset_bundle_module'].path}",
        f"-p:UnityEngineAudioModuleReference={by_id['unity_engine_audio_module'].path}",
        f"-p:UnityEngineImageConversionModuleReference={by_id['unity_engine_image_conversion_module'].path}",
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=config.project_root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeBuildError("net481 companion build could not run") from exc
    if completed.returncode != 0:
        diagnostic = "\n".join(
            (completed.stdout + "\n" + completed.stderr).splitlines()[-40:]
        )
        raise RuntimeBuildError(f"net481 companion build failed:\n{diagnostic}")
    output = runtime_work / "bin" / "Release" / f"{_ASSEMBLY_NAME}.dll"
    if not output.is_file():
        raise RuntimeBuildError(f"net481 build reported success without output: {output}")
    return output


def build_runtime_artifacts(
    config: BuilderConfig,
    build_match: BuildMatch,
    mod_root: Path,
    profile_id: str,
    selection: object,
    dock_rules: object = None,
    diplomacy_rules: object = None,
    atlas_backend: AtlasBackend | None = None,
    ui_texture_backend: UiTextureBackendSelection | None = None,
    reuse_existing_pcm_stream: bool = False,
) -> list[RuntimeArtifact]:
    runtime = _validate_runtime_selection(selection)
    _validate_diplomacy_rollout(profile_id, runtime)
    # Vor dem Fruehausstieg pruefen: ein Regelblock auf einem abgeschalteten
    # Runtime muss den Build ablehnen, nicht leise nichts bauen.
    parsed_dock_rules = _validate_dock_placement_rules(dock_rules, runtime)
    parsed_diplomacy_rules = _validate_diplomacy_rules(
        diplomacy_rules,
        runtime,
    )
    if atlas_backend is not None and not isinstance(atlas_backend, AtlasBackend):
        raise RuntimeBuildError("atlas_backend must be a validated AtlasBackend")
    if ui_texture_backend is not None and not isinstance(
        ui_texture_backend, UiTextureBackendSelection
    ):
        raise RuntimeBuildError(
            "ui_texture_backend must be a validated UiTextureBackendSelection"
        )
    if ui_texture_backend is not None and atlas_backend is None:
        raise RuntimeBuildError("ui_texture_backend requires atlas_backend resource policy")
    if not runtime["enabled"]:
        if atlas_backend is not None or ui_texture_backend is not None:
            raise RuntimeBuildError(
                "atlas_backend and ui_texture_backend require runtime.enabled"
            )
        return []

    fortification_anchor = _DISABLED_FORTIFICATION_ANCHOR
    fortification_tsv = b""
    if runtime["fortifications"]:
        fortification_anchor, fortification_tsv = (
            _load_fortification_build_contract(
                config,
                mod_root,
                include_dock_contributor=runtime["dock_placement"],
            )
        )

    spec_path = (
        config.project_root
        / "runtime"
        / "StrongholdEuropeDE.Runtime"
        / "audio-profile.json"
    )
    spec = load_audio_profile(spec_path)
    spec["source_build_id"] = build_match.source_id
    spec["target_build_id"] = build_match.target_id
    prerequisites = _verify_prerequisites(config)

    roster_spec: RosterTextSpec | None = None
    roster_text = ""
    roster_digest = ""
    if runtime["unit_roster_names"]:
        if config.target.game_dir is None:
            raise RuntimeBuildError(
                "Target game root is required for the roster runtime contract"
            )
        try:
            roster_spec = load_roster_text_spec(
                config.project_root,
                config.target.game_dir,
            )
            roster_text = render_roster_tsv(roster_spec)
        except RosterTextError as exc:
            raise RuntimeBuildError(
                "Pinned unit-roster runtime contract was rejected"
            ) from exc
        roster_digest = hashlib.sha256(roster_text.encode("utf-8")).hexdigest()

    # Validate the complete 393 MiB source set before emitting even the small
    # TSV/DLL pair. A missing or changed WAV must not leave a profile root that
    # looks deployable but has no final build manifest.
    validated_sources: list[tuple[dict[str, Any], Path]] = []
    if runtime["audio_payload"]:
        source_music = config.source.data_dir / "StreamingAssets" / "Music"
        for track in spec["tracks"]:
            source = source_music / track["source_file"]
            if not source.is_file():
                raise RuntimeBuildError(f"Pinned SH1DE music source is missing: {source}")
            validate_wav(source, track)
            validated_sources.append((track, source))

    asset_stream_anchor = _asset_stream_anchor(mod_root, atlas_backend)
    ui_texture_anchor, ui_texture_artifact = _ui_texture_manifest(
        mod_root,
        ui_texture_backend,
        max_resident_bytes=(
            atlas_backend.resource_policy.ui_resident_bytes
            if atlas_backend is not None
            else 1
        ),
    )
    pcm_stream_anchor = _DISABLED_PAYLOAD_ANCHOR
    streaming_artifacts: list[RuntimeArtifact] = []
    if ui_texture_artifact is not None:
        streaming_artifacts.append(ui_texture_artifact)
    if atlas_backend is not None and runtime["audio_payload"]:
        audio_directory = mod_root / "Runtime" / "Audio"
        if audio_directory.exists() and not reuse_existing_pcm_stream:
            raise RuntimeBuildError(
                "Runtime/Audio already exists before PCM streaming staging"
            )
        if not audio_directory.exists():
            audio_directory.mkdir(parents=True)
        for track, source in validated_sources:
            destination = audio_directory / track["output_file"]
            if reuse_existing_pcm_stream:
                if not destination.is_file():
                    raise RuntimeBuildError(
                        "Reusable PCM stream is incomplete: " + str(destination)
                    )
            else:
                shutil.copyfile(source, destination)
            validate_wav(destination, track)
            streaming_artifacts.append(
                RuntimeArtifact(
                    destination,
                    "europe_music_pcm_stream",
                    f"StreamingAssets/Music/{track['source_file']}",
                    {
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
                    },
                )
            )
        pcm_manifest_path = audio_directory / "pcm-stream-manifest.tsv"
        pcm_manifest_text = _pcm_stream_manifest_text(spec["tracks"])
        if reuse_existing_pcm_stream:
            expected_names = {
                track["output_file"] for track in spec["tracks"]
            } | {"pcm-stream-manifest.tsv"}
            actual_names = {
                path.name for path in audio_directory.iterdir() if path.is_file()
            }
            if actual_names != expected_names or any(
                path.is_dir() for path in audio_directory.iterdir()
            ):
                raise RuntimeBuildError(
                    "Reusable PCM stream contains an unexpected file set"
                )
            try:
                existing_manifest_text = pcm_manifest_path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                raise RuntimeBuildError(
                    "Reusable PCM stream manifest is unreadable"
                ) from exc
            if existing_manifest_text != pcm_manifest_text:
                raise RuntimeBuildError(
                    "Reusable PCM stream manifest differs from the pinned contract"
                )
        else:
            pcm_manifest_path.write_text(
                pcm_manifest_text,
                encoding="utf-8",
                newline="\n",
            )
        pcm_payload = _read_stable_payload(
            pcm_manifest_path,
            maximum_bytes=1024 * 1024,
            label="PCM stream manifest",
        )
        pcm_digest = hashlib.sha256(pcm_payload).hexdigest()
        pcm_stream_anchor = _CompiledPayloadAnchor(
            True,
            pcm_digest,
            len(pcm_payload),
            len(spec["tracks"]),
        )
        streaming_artifacts.append(
            RuntimeArtifact(
                pcm_manifest_path,
                "runtime_pcm_stream_contract",
                "runtime/StrongholdEuropeDE.Runtime/audio-profile.json",
                {
                    "kind": "stronghold_europe_pcm_stream_v1",
                    "manifest_sha256": pcm_digest,
                    "track_count": len(spec["tracks"]),
                    "max_active_streams": 2,
                    "buffer_budget_bytes": 16 * 1024 * 1024,
                    "buffer_bytes_per_stream": 1024 * 1024,
                },
            )
        )

    manifest_text = _manifest_text(spec, runtime, prerequisites)
    manifest_path = mod_root / "Runtime" / "audio-profile.tsv"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(manifest_text, encoding="utf-8", newline="\n")
    manifest_digest = sha256_file(manifest_path)

    fortification_path: Path | None = None
    if fortification_anchor.enabled:
        fortification_path = mod_root / Path(_FORTIFICATION_RUNTIME_PATH)
        fortification_path.write_bytes(fortification_tsv)
        emitted_payload = _read_stable_payload(
            fortification_path,
            maximum_bytes=_FORTIFICATION_V1_TSV_SIZE,
            label="emitted fortification runtime catalogue",
        )
        if (
            emitted_payload != fortification_tsv
            or hashlib.sha256(emitted_payload).hexdigest()
            != fortification_anchor.tsv_sha256
        ):
            raise RuntimeBuildError(
                "Fortification runtime catalogue changed while being emitted"
            )
    runtime_source_digest = runtime_source_set_sha256(config.project_root)

    roster_path: Path | None = None
    if roster_spec is not None:
        roster_path = mod_root / "Runtime" / "unit-roster.tsv"
        roster_path.write_text(roster_text, encoding="utf-8", newline="\n")
        if sha256_file(roster_path) != roster_digest:
            raise RuntimeBuildError("Roster runtime contract changed while being emitted")

    runtime_work = (config.output.work_dir / "runtime" / profile_id).resolve()
    runtime_work.mkdir(parents=True, exist_ok=True)
    generated_contract = runtime_work / "GeneratedAudioContract.g.cs"
    generated_contract.write_text(
        _generated_contract_text(
            spec,
            manifest_digest,
            prerequisites,
            runtime,
            profile_id,
            roster_spec,
            roster_digest,
            runtime_source_digest,
            asset_stream_anchor,
            ui_texture_anchor,
            pcm_stream_anchor,
            fortification_anchor,
            parsed_dock_rules,
            parsed_diplomacy_rules,
        ),
        encoding="utf-8",
        newline="\n",
    )
    built_dll = _build_companion(
        config,
        profile_id,
        generated_contract,
        prerequisites,
    )
    dll_path = mod_root / f"{_ASSEMBLY_NAME}.dll"
    shutil.copyfile(built_dll, dll_path)

    artifacts = [
        RuntimeArtifact(
            manifest_path,
            "runtime_contract",
            "runtime/StrongholdEuropeDE.Runtime/audio-profile.json",
            {
                "kind": "stronghold_europe_runtime_contract_v1",
                "plugin_id": _PLUGIN_ID,
                "manifest_sha256": manifest_digest,
                "audio_payload": runtime["audio_payload"],
                "foliage_tree_apple": runtime["foliage_tree_apple"],
                "track_count": len(spec["tracks"]),
            },
        ),
        RuntimeArtifact(
            dll_path,
            "runtime_companion",
            "runtime/StrongholdEuropeDE.Runtime/StrongholdEuropeDE.Runtime.csproj",
            {
                "kind": "net481_bepinex_runtime_companion",
                "plugin_id": _PLUGIN_ID,
                "assembly_name": _ASSEMBLY_NAME,
                "assembly_version": _ASSEMBLY_VERSION,
                "target_framework": prerequisites.target_framework,
                "runtime_prerequisite_config_id": prerequisites.config_id,
                "runtime_prerequisite_mvids": {
                    entry.id: entry.mvid
                    for entry in prerequisites.files
                },
                "manifest_sha256": manifest_digest,
                "unit_roster_names": runtime["unit_roster_names"],
                "farm_placement": runtime["farm_placement"],
                "worker_militia": runtime["worker_militia"],
                "diplomacy": runtime["diplomacy"],
                "diplomacy_rules": parsed_diplomacy_rules,
                "fortifications": runtime["fortifications"],
                "fortification_catalog_sha256": fortification_anchor.tsv_sha256,
                "dock_placement": runtime["dock_placement"],
                # Immer vorhanden, damit die Schluesselmenge der Metadaten
                # exakt bleibt: None = reine Messbahn, Objekt = Regelwerte.
                "dock_placement_rules": parsed_dock_rules,
                "runtime_source_set_sha256": runtime_source_digest,
                "asset_stream_enabled": asset_stream_anchor.enabled,
                "asset_stream_index_sha256": asset_stream_anchor.sha256,
                "asset_stream_backend_kind": asset_stream_anchor.backend_kind,
                "asset_stream_index_schema": asset_stream_anchor.schema,
                "asset_stream_quality_state": asset_stream_anchor.quality_state,
                "asset_stream_promotable": asset_stream_anchor.promotable,
                "ui_texture_streaming_enabled": ui_texture_anchor.enabled,
                "ui_texture_manifest_sha256": ui_texture_anchor.sha256,
                "pcm_streaming_enabled": pcm_stream_anchor.enabled,
                "pcm_stream_manifest_sha256": pcm_stream_anchor.sha256,
            },
        ),
    ]
    if fortification_path is not None:
        artifacts.append(
            RuntimeArtifact(
                fortification_path,
                "runtime_fortification_contract",
                _FORTIFICATION_SOURCE_PATH,
                {
                    "kind": _FORTIFICATION_ARTIFACT_KIND,
                    "plugin_id": _PLUGIN_ID,
                    "schema": fortification_anchor.schema,
                    "recipe_version": fortification_anchor.recipe_version,
                    "variant_count": fortification_anchor.variant_count,
                    "record_count": fortification_anchor.record_count,
                    "source_size_bytes": fortification_anchor.source_size,
                    "source_sha256": fortification_anchor.source_sha256,
                    "catalog_tsv_size": fortification_anchor.tsv_size,
                    "catalog_tsv_sha256": fortification_anchor.tsv_sha256,
                },
            )
        )
    artifacts.extend(streaming_artifacts)

    if roster_spec is not None and roster_path is not None:
        artifacts.insert(
            1,
            RuntimeArtifact(
                roster_path,
                "runtime_roster_contract",
                "config/unit-roster-text.json",
                {
                    "kind": "stronghold_europe_unit_roster_runtime_v1",
                    "plugin_id": _PLUGIN_ID,
                    "manifest_sha256": roster_digest,
                    "roster_source_sha256": roster_spec.source_sha256,
                    "entries_sha256": roster_spec.entries_sha256,
                    "target_originals_sha256": roster_spec.target_originals_sha256,
                    "target_text_sha256": roster_spec.target_text_sha256,
                    "target_text_size": roster_spec.target_text_size,
                    "hud_xaml_sha256": roster_spec.hud_xaml_sha256,
                    "hud_xaml_size": roster_spec.hud_xaml_size,
                    "hud_buildings_xaml_sha256": roster_spec.hud_buildings_xaml_sha256,
                    "hud_buildings_xaml_size": roster_spec.hud_buildings_xaml_size,
                    "entry_count": len(roster_spec.entries),
                    "hud_control_count": len(roster_spec.hud_bindings),
                },
            ),
        )

    if runtime["audio_payload"] and atlas_backend is None:
        audio_directory = mod_root / "Override" / "Sounds" / "Music"
        audio_directory.mkdir(parents=True, exist_ok=True)
        for track, source in validated_sources:
            destination = audio_directory / track["output_file"]
            shutil.copyfile(source, destination)
            validate_wav(destination, track)
            artifacts.append(
                RuntimeArtifact(
                    destination,
                    "europe_music",
                    f"StreamingAssets/Music/{track['source_file']}",
                    {
                        "kind": "validated_pcm_wav",
                        "music_id": track["id"],
                        "expected_original": track["expected_original"],
                        "replacement": track["replacement"],
                        "volume_raw": track["volume_raw"],
                        "audio_format": track["audio_format"],
                        "channels": track["channels"],
                        "sample_rate": track["sample_rate"],
                        "bits_per_sample": track["bits_per_sample"],
                        "block_align": track["block_align"],
                        "data_size": track["data_size"],
                    },
                )
            )
    return artifacts

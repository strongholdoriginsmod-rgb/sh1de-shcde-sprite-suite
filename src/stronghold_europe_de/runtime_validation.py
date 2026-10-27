from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import json
from math import isfinite
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import stat

from PIL import Image, UnidentifiedImageError

from .asset_stream_contract import (
    ATLAS_BACKEND_KIND as ASSET_STREAM_BACKEND_KIND,
    BC7_ATLAS_BACKEND_KIND as ASSET_STREAM_BC7_BACKEND_KIND,
    BC7_INDEX_SCHEMA as ASSET_STREAM_BC7_INDEX_SCHEMA,
    BC7_RESOURCE_POLICY_KIND as ASSET_STREAM_BC7_RESOURCE_POLICY_KIND,
    INDEX_OUTPUT_PATH as ASSET_STREAM_INDEX_PATH,
    INDEX_SCHEMA as ASSET_STREAM_INDEX_SCHEMA,
    RESOURCE_POLICY_KIND as ASSET_STREAM_RESOURCE_POLICY_KIND,
)
from .gm_atlas import LOADER_139_GROUPS, parse_loader_frame_name
from .hashing import sha256_file
from .loader_groups import LOADER_GROUP_TABLE
from .runtime_build import (
    _DIPLOMACY_ROLLOUT_PROFILE_IDS,
    RuntimeBuildError,
    _pcm_stream_manifest_text,
    music_route_entries,
    music_route_sha256,
    parse_ui_texture_runtime_manifest_v2,
    parse_runtime_contract,
    validate_wav,
)
from .ui_asset_bundle import (
    UiAssetBundleError,
    load_ui_quality_policy,
    load_ui_texture_source_manifest,
)
from .validation import (
    RUNTIME_ASSEMBLY_NAME,
    RUNTIME_ASSEMBLY_VERSION,
    RUNTIME_CONTRACT_SOURCE_REFERENCE,
    RUNTIME_CONTRACT_PATH,
    RUNTIME_DLL_CATEGORY,
    RUNTIME_DLL_PATH,
    RUNTIME_DLL_SOURCE_REFERENCE,
    RUNTIME_FORTIFICATION_CONTRACT_CATEGORY,
    RUNTIME_FORTIFICATION_CONTRACT_PATH,
    RUNTIME_FORTIFICATION_SOURCE_REFERENCE,
    RUNTIME_PLUGIN_ID,
    RUNTIME_PREREQUISITE_MVIDS,
    RUNTIME_ROSTER_CONTRACT_CATEGORY,
    RUNTIME_ROSTER_CONTRACT_PATH,
    RUNTIME_ROSTER_ENTRIES_SHA256,
    RUNTIME_ROSTER_HUD_BUILDINGS_XAML_SHA256,
    RUNTIME_ROSTER_HUD_XAML_SHA256,
    RUNTIME_ROSTER_MANIFEST_SHA256,
    RUNTIME_ROSTER_ORIGINALS_SHA256,
    RUNTIME_ROSTER_SOURCE_REFERENCE,
    RUNTIME_ROSTER_SOURCE_SHA256,
    RUNTIME_ROSTER_TARGET_TEXT_SHA256,
    RUNTIME_ROSTER_UNIT_NAMES_SHA256,
    UI_TEXTURE_BUNDLE_PREFIX,
    UI_TEXTURE_EDITOR_SOURCE_PATH,
    UI_TEXTURE_EXPECTED_ENTRY_COUNT,
    UI_TEXTURE_MAX_RESIDENT_BYTES,
    UI_TEXTURE_QUALITY_POLICY_PATH,
    UI_TEXTURE_SOURCE_CONFIG_PATH,
    UI_TEXTURE_V1_MANIFEST_PATH,
    UI_TEXTURE_V2_MANIFEST_PATH,
    ValidationCheck,
    RosterRuntimeContractError,
    _RUNTIME_CONTRACT_METADATA_KEYS,
    _RUNTIME_DLL_METADATA_KEYS,
    _RUNTIME_ROSTER_ISOLATED_OUTPUTS,
    _RUNTIME_ROSTER_LOGO_PATH,
    _active_ui_png_paths,
    _diplomacy_rules_metadata_ok,
    _dock_placement_rules_metadata_ok,
    _runtime_roster_canary_output_contract,
    _managed_assembly_attestation,
    _managed_assembly_identity,
    _parse_roster_runtime_contract,
    _pe_clr_header,
    _runtime_assembly_attestation_expected,
    _runtime_prerequisite_mvids_valid,
    _runtime_fortification_contract_expected,
    _runtime_fortification_metadata_matches,
    _runtime_streaming_metadata_ok,
    _runtime_fortification_selection_metadata_ok,
    _runtime_roster_metadata_matches,
    _runtime_source_set_identity,
    _strict_stream_index_shape,
    _ui_texture_v2_output_record_errors,
)


_SHCDE_SE_INFO_PREFIX = r"\[Info   :  SHCDE-SE\]"
_MOD_LOAD_RE = re.compile(
    rf"^{_SHCDE_SE_INFO_PREFIX} \[GameAssetModManager\] \[RegisterAll\] "
    r"Loading Asset Mod: \[([^]\r\n]+)]\Z"
)
_PROVIDER_RE = re.compile(
    rf"^{_SHCDE_SE_INFO_PREFIX} \[GameAssetManagerAPI\] "
    r"\[RegisterAssetProvider\] Indexing assets for \[([^]\r\n]+)] "
    r"from \[([^\r\n]+)]\Z"
)
_INDEX_RE = re.compile(
    rf"^{_SHCDE_SE_INFO_PREFIX} \[GameAssetManagerAPI\] "
    r"\[RegisterAssetProvider\] Indexing: \[([^]\r\n]+)]\Z"
)
_XAML_PATCH_RE = re.compile(
    rf"^{_SHCDE_SE_INFO_PREFIX} \[GameXAMLManagerAPI\] "
    r"\[GetPatchesForPath\] Found patch for \[([^]\r\n]+)] -> "
    r"\[([^\r\n]+)]\Z"
)
_PROVIDER_EVENT_PREFIX = (
    "[Info   :  SHCDE-SE] [GameAssetManagerAPI] "
    "[RegisterAssetProvider] Indexing assets for "
)
_INDEX_EVENT_PREFIX = (
    "[Info   :  SHCDE-SE] [GameAssetManagerAPI] "
    "[RegisterAssetProvider] Indexing: "
)
_XAML_PATCH_EVENT_PREFIX = (
    "[Info   :  SHCDE-SE] [GameXAMLManagerAPI] "
    "[GetPatchesForPath] Found patch for "
)
_REPLACED_RE = re.compile(
    rf"^{_SHCDE_SE_INFO_PREFIX} \[GameSpriteManagerAPI\] "
    r"\[ApplyRuntimeOverrides\] Replaced ([0-9]{1,10}) sprites and generated materials\.\Z"
)
_APPLY_ALL_RE = re.compile(
    rf"^{_SHCDE_SE_INFO_PREFIX} \[GameAtlasManagerAPI\] \[ApplyAll\] "
    r"Applying ([0-9]{1,10}) atlas override\(s\)\.\.\.\Z"
)
_APPLIED_RE = re.compile(
    rf"^{_SHCDE_SE_INFO_PREFIX} \[GameAtlasManagerAPI\] \[ApplySingle\] "
    r"Applied \[([^]\r\n]+)]: ([0-9]{1,10}) frames sliced, mask=(yes|no), "
    r"arraySize=([0-9]{1,10})\Z"
)
_ATLAS_REGISTER_RE = re.compile(
    rf"^{_SHCDE_SE_INFO_PREFIX} \[GameAtlasManagerAPI\] "
    r"\[RegisterAtlasOverride\] Registered atlas override for "
    r"\[([^]\r\n]+)] \(([^()\r\n]+)\)\Z"
)
_ATLAS_DISCOVERY_RE = re.compile(
    rf"^{_SHCDE_SE_INFO_PREFIX} \[GameAssetManagerAPI\] "
    r"\[DiscoverAtlasOverrides\] Auto-registered atlas override for "
    r"\[([^]\r\n]+)] from \[([^]\r\n]+)]\Z"
)
_AUDIO_LOAD_RE = re.compile(
    rf"^{_SHCDE_SE_INFO_PREFIX} \[MyAudioManager_Hooks\] "
    r"\[MyAudioManager_LoadClip_Hook\] LoadClip using custom audio: "
    r"\[([^]\r\n]+)]\Z"
)
_RUNTIME_AUDIO_PROVIDER_ID = "strongholdeuropede.runtime.private.audio"
_FRONTEND_AUDIO_CANARY = "eu_chantloop1.wav"
_RUNTIME_FORBIDDEN_SUFFIXES = frozenset(
    {".exe", ".dll", ".rne", ".assets", ".ress"}
)
RUNTIME_EVENT_PREFIX = "SEDE_RUNTIME_V1|"
_FORTIFICATION_HUD_PATCH_RELATIVE = (
    "Patches/Assets/GUI/XAMLResources/HUD_Main.xaml"
)
RUNTIME_CAPABILITIES_OK = (
    "SEDE_RUNTIME_V1|event=capabilities|core=ok|r3=ok"
    "|farm_placement=ok|worker_militia=ok"
)
RUNTIME_INITIALIZED = "SEDE_RUNTIME_V1|event=runtime|status=initialized"
RUNTIME_INITIALIZATION_FAILED = (
    "SEDE_RUNTIME_V1|event=runtime|status=failed_closed"
)
RUNTIME_AUDIO_INACTIVE = "SEDE_RUNTIME_V1|event=audio|status=inactive"
RUNTIME_AUDIO_ACTIVE = "SEDE_RUNTIME_V1|event=audio|status=active|tracks=17"
RUNTIME_AUDIO_FAILED = "SEDE_RUNTIME_V1|event=audio|status=failed_closed"
RUNTIME_FOLIAGE_INACTIVE = "SEDE_RUNTIME_V1|event=foliage|status=inactive"
RUNTIME_FOLIAGE_SUCCEEDED = (
    "SEDE_RUNTIME_V1|event=foliage|status=success|gm=tree_apple|materials=7"
    "|main_cpu_readable=false|mask_cpu_readable=false"
)
RUNTIME_FOLIAGE_FAILED = (
    "SEDE_RUNTIME_V1|event=foliage|status=failed_closed|gm=tree_apple"
)
# The route is intentionally not profile-selectable.  The one exception is the
# isolated worker-militia canary: runtime_build.py emits
# GeneratedWorkerMilitiaContract.IsolatedCanary for exactly this profile and
# StrongholdEuropeRuntimePlugin skips the unrelated visual patch there.
_WOLF_SPRITE_ROUTE_ISOLATED_PROFILE_ID = "worker-militia-canary"
RUNTIME_WOLF_SPRITE_ROUTE_ACTIVE = (
    "SEDE_RUNTIME_V1|event=wolf_sprite_route|status=active"
    "|group=body_lion|replaced_by=body_wolf|gm=92"
)
_RUNTIME_WOLF_SPRITE_ROUTE_FAILED_RE = re.compile(
    r"SEDE_RUNTIME_V1\|event=wolf_sprite_route\|status=failed_open"
    r"\|reason=([A-Za-z_][A-Za-z0-9_.+`]{0,127})"
    r" - lions stay lions: ([^|\r\n]{1,200})\Z"
)
RUNTIME_ROSTER_INACTIVE = (
    "SEDE_RUNTIME_V1|event=roster_names|status=inactive"
)
RUNTIME_MUSIC_ROUTE_INACTIVE = (
    "SEDE_RUNTIME_V1|event=music_route|status=inactive"
)
RUNTIME_FARM_PLACEMENT_INACTIVE = (
    "SEDE_RUNTIME_V1|event=farm_placement|status=inactive"
)
# unsuitable is the TileType mask the rule rejects (BeachOrWaves | CoarseSand);
# pinning it here makes a silent widening of the rule - farms on sand, say -
# fail the gate instead of passing unnoticed.
#
# The rule is stated as an exclusion because it has to be. Ordinary buildable
# ground is TileType.NoneOrDirt = 0, and no bit test can match zero, so the
# earlier allow-list (arable=145) rejected every plain tile and admitted only
# the oasis - the one fertile texture with a bit set.
RUNTIME_FARM_PLACEMENT_ACTIVE = (
    "SEDE_RUNTIME_V1|event=farm_placement|status=active|farms=4|unsuitable=32"
)
RUNTIME_FARM_PLACEMENT_FAILED = (
    "SEDE_RUNTIME_V1|event=farm_placement|status=failed_closed"
)
RUNTIME_WORKER_MILITIA_INACTIVE = (
    "SEDE_RUNTIME_V1|event=worker_militia|status=inactive"
)
RUNTIME_WORKER_MILITIA_ACTIVE = (
    "SEDE_RUNTIME_V1|event=worker_militia|status=active"
    "|hunter=ranged|woodcutter=melee|divisor=2|hunter_guard=54"
    "|woodcutter_guard=6|hunter_pursuit=57|woodcutter_pursuit=9"
    "|selection=native_selected_state_single|combat=per_unit"
)
RUNTIME_WORKER_MILITIA_FAILED = (
    "SEDE_RUNTIME_V1|event=worker_militia|status=failed_closed"
)
RUNTIME_WORKER_MILITIA_MULTIPLAYER_SUPPRESSED = (
    "SEDE_RUNTIME_V1|event=worker_militia|status=suppressed|reason=networked"
)
_RUNTIME_DIPLOMACY_EVENT_RE = re.compile(
    r"SEDE_RUNTIME_V1\|lane=diplomacy\|event="
    r"(activation|transfer|value|offer|demand|alliance|ultimatum|"
    r"team_transaction|break|saving|fail_closed|feature|session_scope)"
    r"(?:\|[a-z_][a-z0-9_]{0,31}=[^|\r\n]{0,512})+\Z"
)
_RUNTIME_DIPLOMACY_FEATURE_RE = re.compile(
    r"SEDE_RUNTIME_V1\|lane=diplomacy\|event=feature\|status="
    r"(active|inactive|failed|failed_closed)(?:\|reason=[^|\r\n]{1,512})?\Z"
)
_RUNTIME_DIPLOMACY_FAILURE_RE = re.compile(
    r"SEDE_RUNTIME_V1\|lane=diplomacy\|event="
    r"(?:fail_closed\|status=aborted|feature\|status=(?:failed|failed_closed)|"
    r"team_transaction\|status=rollback_failed)"
    r"(?:\|[a-z_][a-z0-9_]{0,31}=[^|\r\n]{0,512})*\Z"
)
RUNTIME_FORTIFICATIONS_INACTIVE = (
    "SEDE_RUNTIME_V1|lane=fortifications|event=feature|status=inactive"
)
RUNTIME_FORTIFICATIONS_ACTIVE = (
    "SEDE_RUNTIME_V1|lane=fortifications|event=feature|status=active"
)
RUNTIME_FORTIFICATIONS_CORE_ACTIVE = (
    "SEDE_RUNTIME_V1|event=fortifications|status=active|catalog=v1|walls=7"
    "|native_battlements=preserved|native_stairs=preserved"
    "|native_watchtower=preserved|gameplay_costs_measured=false"
    "|visual_recipes_measured=false|wooden_gate_measured=false"
    "|wooden_stairs_measured=false|wooden_platform_measured=false"
    "|save_roundtrip_measured=false"
)
_RUNTIME_FORTIFICATIONS_FAILURE_RE = re.compile(
    r"SEDE_RUNTIME_V1\|(?:lane=fortifications\|event=feature"
    r"\|status=(?:failed|failed_closed)\|reason=[^|\r\n]{1,512}"
    r"|event=fortifications\|status=failed\|stage=[a-z_]{1,64}"
    r"\|detail=[^|\r\n]{1,512})\Z"
)
_RUNTIME_FORTIFICATION_SCOPE_RE = re.compile(
    r"SEDE_RUNTIME_V1\|event=fortification_map_scope"
    r"\|status=(?:active|suppressed)\|editor=(?:true|false)\Z"
)
_RUNTIME_FORTIFICATION_SELECTION_RE = re.compile(
    r"SEDE_RUNTIME_V1\|event=fortification_selection"
    r"\|variant=[a-z][a-z0-9_]{0,63}\|mapper=[0-9]{1,3}"
    r"\|editor=(?:true|false)\|visual_beta=(?:true|false)\Z"
)
_RUNTIME_FORTIFICATION_PLACED_RE = re.compile(
    r"SEDE_RUNTIME_V1\|event=fortification_placed"
    r"\|variant=[a-z][a-z0-9_]{0,63}\|changed_tiles=[1-9][0-9]{0,3}"
    r"\|editor=(?:true|false)\Z"
)
_RUNTIME_WORKER_MILITIA_SELECTION_RE = re.compile(
    r"SEDE_RUNTIME_V1\|event=worker_militia_evidence\|status=selected"
    r"\|unit=(hunter|woodcutter)\Z"
)
_RUNTIME_WORKER_MILITIA_SCOPE_RE = re.compile(
    r"SEDE_RUNTIME_V1\|event=worker_militia_scope\|status="
    r"(offline|solo_host|network_client|multiplayer|indeterminate)"
    r"\|networked=(true|false)\|local_host=(true|false)"
    r"\|active_players=-?[0-9]{1,9}\|other_humans=-?[0-9]{1,9}\Z"
)
_RUNTIME_WORKER_MILITIA_UI_READY_RE = re.compile(
    r"SEDE_RUNTIME_V1\|event=worker_militia_evidence\|status=ui_ready"
    r"\|unit=(hunter|woodcutter)"
    r"\|route=(initial_opening|selection_update)"
    r"\|thread_match=true\|native_singleton=true"
    r"\|info_source=unit_fields\|information_bound=true"
    r"\|building=true\|troops=false"
    r"\|control_groups=false\|panel_visible=true"
    r"\|image_bound=true\|name=true\|type=true\|comment=true"
    r"\|stable_tick=true\Z"
)
_RUNTIME_WORKER_MILITIA_COMMAND_RE = re.compile(
    r"SEDE_RUNTIME_V1\|event=worker_militia_evidence\|status=command"
    r"\|unit=(hunter|woodcutter)\|mode=(autonomous|manual)\Z"
)
_RUNTIME_WORKER_MILITIA_NATIVE_MOVE_RE = re.compile(
    r"SEDE_RUNTIME_V1\|event=worker_militia_evidence\|status=native_move"
    r"\|unit=(hunter|woodcutter)\Z"
)
_RUNTIME_WORKER_MILITIA_NATIVE_WORK_MOVE_SUPPRESSED_RE = re.compile(
    r"SEDE_RUNTIME_V1\|event=worker_militia_evidence"
    r"\|status=native_work_move_suppressed\|unit=(hunter|woodcutter)"
    r"\|phase=(outbound|fighting|holding|direct_work_pending)"
    r"\|occupancy=true\Z"
)
_RUNTIME_WORKER_MILITIA_FLAG_RESTORED_RE = re.compile(
    r"SEDE_RUNTIME_V1\|event=worker_militia_evidence"
    r"\|status=native_state_restored\|unit=(hunter|woodcutter)\Z"
)
_RUNTIME_WORKER_MILITIA_HUNTER_DAMAGE_RE = re.compile(
    r"SEDE_RUNTIME_V1\|event=worker_militia_evidence\|status=hunter_damage"
    r"\|mode=(autonomous|manual)"
    r"\|archer=([0-9]{1,9})\|weak=([0-9]{1,9})\Z"
)
_RUNTIME_WORKER_MILITIA_WOODCUTTER_DAMAGE_RE = re.compile(
    r"SEDE_RUNTIME_V1\|event=worker_militia_evidence\|status=woodcutter_damage"
    r"\|mode=(autonomous|manual)\|damage=([0-9]{1,9})\Z"
)
_RUNTIME_WORKER_MILITIA_HOLD_STARTED_RE = re.compile(
    r"SEDE_RUNTIME_V1\|event=worker_militia_evidence\|status=hold_started"
    r"\|unit=(hunter|woodcutter)\|deadline_ms=10000\Z"
)
_RUNTIME_WORKER_MILITIA_HOLD_COMPLETED_RE = re.compile(
    r"SEDE_RUNTIME_V1\|event=worker_militia_evidence\|status=hold_completed"
    r"\|unit=(hunter|woodcutter)\|reason=no_contact\Z"
)
_RUNTIME_WORKER_MILITIA_COMBAT_DIRECT_WORK_RE = re.compile(
    r"SEDE_RUNTIME_V1\|event=worker_militia_evidence"
    r"\|status=combat_to_direct_work\|unit=(hunter|woodcutter)"
    r"\|mode=(autonomous|manual)\|guard_clear=true\Z"
)
_RUNTIME_WORKER_MILITIA_HANDOFF_RESTORED_RE = re.compile(
    r"SEDE_RUNTIME_V1\|event=worker_militia_evidence"
    r"\|status=handoff_restored\|unit=(hunter|woodcutter)"
    r"\|mode=(autonomous|manual)\|reason=([a-z][a-z0-9_]{0,63})"
    r"\|command_mode=([0-9]{1,5})\|original_command_mode=([0-9]{1,5})"
    r"\|occupancy=true\|work_link=([0-9]{1,5})"
    r"\|original_work_link=([0-9]{1,5})"
    r"\|tribe=([0-9]{1,5})\|original_tribe=([0-9]{1,5})"
    r"\|return_move=false\Z"
)
_RUNTIME_WORKER_MILITIA_DIRECT_WORK_RE = re.compile(
    r"SEDE_RUNTIME_V1\|event=worker_militia_evidence"
    r"\|status=direct_work_resumed\|unit=(hunter|woodcutter)"
    r"\|mode=(autonomous|manual)\|reason=([a-z][a-z0-9_]{0,63})"
    r"\|proof=native_worker_move\|occupancy=true\Z"
)
_RUNTIME_WORKER_MILITIA_QUARANTINE_RECOVERED_RE = re.compile(
    r"SEDE_RUNTIME_V1\|event=worker_militia_evidence"
    r"\|status=selection_quarantine_recovered\|scope=same_map"
    r"\|reason=authoritative_clean_window\Z"
)
_RUNTIME_WORKER_MILITIA_PERFORMANCE_RE = re.compile(
    r"SEDE_RUNTIME_V1\|event=worker_militia_evidence\|status=performance"
    r"\|samples=240\|mean_us=([0-9]{1,12})"
    r"\|p99_us=([0-9]{1,12})\|budget_ok=(true|false)\Z"
)
_RUNTIME_FARM_SUMMARY_RE = re.compile(
    r"SEDE_RUNTIME_V1\|event=farm_placement\|status=summary"
    r"\|allowed=([0-9]{1,9})\|blocked=([0-9]{1,9})\Z"
)
RUNTIME_DOCK_PLACEMENT_INACTIVE = (
    "SEDE_RUNTIME_V1|event=dock_placement|status=inactive"
)
# mode=measure is pinned here for the same reason unsuitable=96 is: the dock
# lane in measurement mode only watches the placement validator and logs what
# it sees.  It answers nothing.  A build that starts refusing dock tiles has
# to say mode=enforce with its three rule values instead - it cannot start
# blocking quietly.  Which of the two lines is expected is decided by the DLL
# metadata (dock_placement_rules present or not).
RUNTIME_DOCK_PLACEMENT_ACTIVE = (
    "SEDE_RUNTIME_V1|event=dock_placement|status=active|mappers=4|mode=measure"
)
RUNTIME_DOCK_PLACEMENT_FAILED = (
    "SEDE_RUNTIME_V1|event=dock_placement|status=failed_closed"
)
_RUNTIME_DOCK_ENFORCE_ACTIVE_RE = re.compile(
    r"SEDE_RUNTIME_V1\|event=dock_placement\|status=active\|mappers=4"
    r"\|mode=enforce\|wood=([0-9]{1,4})\|gold=([0-9]{1,4})"
    r"\|health=([0-9]{1,6})\Z"
)


def runtime_dock_enforce_active_line(wood: int, gold: int, health: int) -> str:
    """The exact enforce-mode active line for the given rule values."""

    return (
        "SEDE_RUNTIME_V1|event=dock_placement|status=active|mappers=4"
        f"|mode=enforce|wood={wood}|gold={gold}|health={health}"
    )


# blocked is always present: 0 in measurement mode, the count of refused
# land tiles once the water rule enforces.
_RUNTIME_DOCK_SUMMARY_RE = re.compile(
    r"SEDE_RUNTIME_V1\|event=dock_placement\|status=summary"
    r"\|tiles=([0-9]{1,9})\|water=([0-9]{1,9})\|blocked=([0-9]{1,9})\Z"
)
# The gameplay music path asks by native filename and never reads the ID table,
# so the companion rewrites the requested name in flight.  Entry count and map
# digest are logged so a silently shrunk map cannot pass as a working one.
_RUNTIME_MUSIC_ROUTE_ACTIVE_RE = re.compile(
    r"SEDE_RUNTIME_V1\|event=music_route\|status=active"
    r"\|entries=([1-9][0-9]{0,3})\|digest=([0-9a-f]{64})\Z"
)
RUNTIME_ROSTER_MONITOR_HEALTHY = (
    "SEDE_RUNTIME_V1|event=roster_monitor|status=healthy|entries=64"
    "|hud_controls=17"
)
_RUNTIME_ROSTER_ACTIVE_RE = re.compile(
    r"SEDE_RUNTIME_V1\|event=roster_names\|status=active\|locale=de-DE"
    r"\|entries=64\|hud_controls=17\|digest=([0-9a-f]{64})\Z"
)
_RUNTIME_ROSTER_UI_RE = re.compile(
    r"SEDE_RUNTIME_V1\|event=roster_ui\|status=verified\|controls=17"
    r"\|generation=([1-9][0-9]{0,5})\Z"
)
_RUNTIME_ROSTER_FAILURE_REASONS = frozenset(
    {
        "preparation_failed",
        "activation_failed",
        "locale_changed",
        "dictionary_changed",
        "extender_dictionary_changed",
        "translation_conflict",
        "ownership_lost",
        "hud_ownership_lost",
        "hud_verification_failed",
        "monitor_failed",
    }
)
_RUNTIME_ROSTER_FAILURE_RE = re.compile(
    r"SEDE_RUNTIME_V1\|event=roster_names"
    r"\|status=(failed_closed|restart_required)\|reason=([a-z_]+)\Z"
)
_RUNTIME_ROSTER_CLEANUP_RE = re.compile(
    r"SEDE_RUNTIME_V1\|event=roster_cleanup\|status=restored"
    r"\|entries=([0-9]{1,3})\|hud_controls=([0-9]{1,3})"
    r"\|trigger=(application_quit|unexpected_shutdown)\Z"
)

# The three lazy streaming lanes deliberately share the stable companion
# event prefix with the older runtime features, but their terminal records are
# repeatable (per group, UI path, or PCM request).  Keep the grammar here
# closed and independently bounded instead of accepting arbitrary key/value
# tails merely because the event name starts with a known word.
_RUNTIME_ASSET_STREAM_INACTIVE = (
    "SEDE_RUNTIME_V1|event=asset_stream|status=inactive"
)
_RUNTIME_ASSET_STREAM_INITIALIZED_RE = re.compile(
    r"SEDE_RUNTIME_V1\|event=asset_stream\|status=initialized"
    r"\|groups=([1-9][0-9]{0,2})"
    r"\|backend=([a-z0-9_]{1,64})"
    r"\|policy=([a-z0-9_]{1,64})\Z"
)
_RUNTIME_ASSET_STREAM_STATE_RE = re.compile(
    r"SEDE_RUNTIME_V1\|event=asset_stream\|status=(inactive|vanilla)"
    r"\|reason=([^|\r\n]{1,200})\Z"
)
_RUNTIME_ASSET_STREAM_SCENE_RESET_RE = re.compile(
    r"SEDE_RUNTIME_V1\|event=asset_stream\|status=scene_reset"
    r"\|epoch=([1-9][0-9]{0,18})"
    r"\|reason=(map_to_map|map_unload|shutdown)\Z"
)
_RUNTIME_ASSET_STREAM_BASELINE_CAPTURED_RE = re.compile(
    r"SEDE_RUNTIME_V1\|event=asset_stream_baseline\|status=captured"
    r"\|groups=([0-9]{1,3})\Z"
)
_RUNTIME_ASSET_GROUP_CAPTURE = r"([A-Za-z0-9][A-Za-z0-9._ -]{0,95})"
_RUNTIME_ASSET_STREAM_BASELINE_VANILLA_RE = re.compile(
    r"SEDE_RUNTIME_V1\|event=asset_stream_baseline\|status=vanilla"
    r"\|group=" + _RUNTIME_ASSET_GROUP_CAPTURE
    + r"\|reason=([^|\r\n]{1,200})\Z"
)
_RUNTIME_ASSET_STREAM_PENDING_RE = re.compile(
    r"SEDE_RUNTIME_V1\|event=asset_stream_group"
    r"\|status=pending"
    r"\|group=" + _RUNTIME_ASSET_GROUP_CAPTURE
    + r"\|epoch=([1-9][0-9]{0,18})"
    + r"\|reason=([a-z0-9_]{1,64})\Z"
)
_RUNTIME_ASSET_STREAM_TERMINAL_RE = re.compile(
    r"SEDE_RUNTIME_V1\|event=(group_loaded|group_fallback)"
    r"\|group=" + _RUNTIME_ASSET_GROUP_CAPTURE
    + r"\|epoch=([1-9][0-9]{0,18})"
    + r"\|reason=([a-z0-9_]{1,64})"
    + r"\|resident_charge_bytes=([1-9][0-9]{0,18})"
    + r"\|predicted_load_peak_bytes=([1-9][0-9]{0,18})"
    + r"\|gm_resident_bytes=(0|[1-9][0-9]{0,18})"
    + r"\|ui_resident_bytes=(-1|0|[1-9][0-9]{0,18})"
    + r"\|audio_stream_bytes=(-1|0|[1-9][0-9]{0,18})"
    + r"\|process_private_bytes=(-1|[1-9][0-9]{0,18})"
    + r"\|available_commit_bytes=(-1|0|[1-9][0-9]{0,18})"
    + r"\|available_physical_bytes=(-1|0|[1-9][0-9]{0,18})"
    + r"\|memory_status=(complete|unavailable)\Z"
)
_RUNTIME_ASSET_STREAM_SUMMARY_RE = re.compile(
    r"SEDE_RUNTIME_V1\|event=asset_stream_summary\|status=complete"
    r"\|epoch=(?P<epoch>[1-9][0-9]{0,18})"
    r"\|requested=(?P<requested>[0-9]{1,3})"
    r"\|loaded=(?P<loaded>[0-9]{1,3})"
    r"\|fallback=(?P<fallback>[0-9]{1,3})"
    r"\|budget_denied=(?P<budget_denied>[0-9]{1,3})"
    r"\|memory_samples=(?P<memory_samples>[0-9]{1,3})"
    r"\|max_private_bytes=(?P<max_private_bytes>-1|[1-9][0-9]{0,18})"
    r"\|min_available_commit_bytes="
    r"(?P<min_available_commit_bytes>-1|0|[1-9][0-9]{0,18})"
    r"(?:"
    r"\|page_mask_runs=(?P<page_mask_runs>[0-9]{1,10})"
    r"\|page_mask_tracked=(?P<page_mask_tracked>[0-9]{1,10})"
    r"\|page_mask_neutralized=(?P<page_mask_neutralized>[0-9]{1,10})"
    r"\|page_mask_blocked=(?P<page_mask_blocked>[0-9]{1,10})"
    r"\|page_mask_failures=(?P<page_mask_failures>[0-9]{1,10})"
    r"\|route_conflicts=(?P<route_conflicts>[0-9]{1,10})"
    r"(?:"
    r"\|archer_probe_events=(?P<archer_probe_events>[0-9]{1,10})"
    r"\|archer_probe_anomalies=(?P<archer_probe_anomalies>[0-9]{1,10})"
    r"\|archer_probe_dropped=(?P<archer_probe_dropped>[0-9]{1,10})"
    r"|"
    r"\|mask_route_events=(?P<mask_route_events>[0-9]{1,10})"
    r"\|mask_route_corrections=(?P<mask_route_corrections>[0-9]{1,10})"
    r"\|mask_route_postfix_mismatches="
    r"(?P<mask_route_postfix_mismatches>[0-9]{1,10})"
    r"\|mask_route_logs_dropped="
    r"(?P<mask_route_logs_dropped>[0-9]{1,10})"
    r")?"
    r")?"
    r"\|min_available_physical_bytes="
    r"(?P<min_available_physical_bytes>-1|0|[1-9][0-9]{0,18})"
    r"\|max_gm_resident_bytes="
    r"(?P<max_gm_resident_bytes>-1|0|[1-9][0-9]{0,18})"
    r"\|max_ui_resident_bytes="
    r"(?P<max_ui_resident_bytes>-1|0|[1-9][0-9]{0,18})"
    r"\|max_audio_stream_bytes="
    r"(?P<max_audio_stream_bytes>-1|0|[1-9][0-9]{0,18})\Z"
)
_RUNTIME_ASSET_MASK_ROUTE_RE = re.compile(
    r"SEDE_RUNTIME_V1\|event=asset_stream_mask_route\|status=observed"
    r"\|epoch=[1-9][0-9]{0,18}"
    r"\|reason=(?:route_exception|postfix_mismatch|external_drift_between_calls|"
    r"group_change|renderer_id_reused|group_first_observed|mask_corrected)"
    r"\|anomaly=(?P<anomaly>[01])\|correction=[01]"
    r"\|renderer_id=-?[0-9]{1,11}\|renderer_id_reused=[01]"
    r"\|renderer_unity_null=[01]\|file=-?[0-9]{1,11}"
    r"\|file_group=[^|=\r\n]{1,96}\|mask_required=[01]"
    r"\|route_group=[^|=\r\n]{1,96}\|image=-?[0-9]{1,11}"
    r"\|colour=-?[0-9]{1,11}\|alt_frame=[01]"
    r"\|chop_feet=-?[0-9]{1,11}\|transparency=-?[0-9]{1,11}"
    r"\|sprite_before=[^|=\r\n]{1,128}"
    r"\|sprite_after=[^|=\r\n]{1,128}"
    r"\|material_before=[^|=\r\n]{1,128}"
    r"\|material_after=[^|=\r\n]{1,128}"
    r"\|shader_before=[^|=\r\n]{1,128}"
    r"\|shader_after=[^|=\r\n]{1,128}"
    r"\|expected_mask_before=[^|=\r\n]{1,128}"
    r"\|expected_mask_after=[^|=\r\n]{1,128}"
    r"\|block_mask_before=[^|=\r\n]{1,128}"
    r"\|block_mask_after=[^|=\r\n]{1,128}"
    r"\|material_mask_before=[^|=\r\n]{1,128}"
    r"\|material_mask_after=[^|=\r\n]{1,128}"
    r"\|exception=[^|=\r\n]{1,96}\Z"
)
_UI_TEXTURE_RUNTIME_BACKEND = "assetbundle_bc7_v2"
# OFFEN (Universal-Suite 29.09.2026): config/ui-textures-bc7-v1.json fuehrt inzwischen
# 128 Eintraege (105 externe + 23 Profilausgaben, darunter 14 Mauer-/Festungsbilder),
# diese Pruefung und ihre Test-Vorlagen noch 114 (105 + 9). Im Upstream (SE144) zu
# vereinheitlichen; im Nachsichtmodus meldet 'validate' es nur als Warnung.
_UI_TEXTURE_RUNTIME_ENTRY_COUNT = 114
_UI_TEXTURE_EXTERNAL_ENTRY_COUNT = 105
_UI_TEXTURE_PROFILE_ENTRY_COUNT = 9
_RUNTIME_UI_STREAM_READY_RE = re.compile(
    r"SEDE_RUNTIME_V1\|event=ui_texture_stream\|status=ready"
    r"\|backend=assetbundle_bc7_v2"
    r"\|entries=([1-9][0-9]{0,5})"
    r"\|resident_charge_bytes=([1-9][0-9]{0,18})\Z"
)
_RUNTIME_UI_STREAM_UNAVAILABLE_RE = re.compile(
    r"SEDE_RUNTIME_V1\|event=ui_texture_stream"
    r"\|status=unavailable\|backend=assetbundle_bc7_v2"
    r"\|reason=([A-Za-z_][A-Za-z0-9_.+`]{0,127})\Z"
)
_RUNTIME_UI_STREAM_FAILED_CLOSED_RE = re.compile(
    r"SEDE_RUNTIME_V1\|event=ui_texture_stream"
    r"\|status=failed_closed"
    r"\|reason=([A-Za-z_][A-Za-z0-9_.+`]{0,127})\Z"
)
_RUNTIME_UI_STREAM_TERMINAL_RE = re.compile(
    r"SEDE_RUNTIME_V1\|event=ui_texture_stream"
    r"\|status=(lazy_loaded|rejected_fail_closed)"
    r"\|backend=assetbundle_bc7_v2"
    r"\|path=(Assets/GUI/[^|\r\n]{1,512}\.png)\Z"
)
_RUNTIME_UI_STREAM_SUMMARY_RE = re.compile(
    r"SEDE_RUNTIME_V1\|event=ui_texture_summary\|status=complete"
    r"\|backend=assetbundle_bc7_v2"
    r"\|requested=([0-9]{1,6})\|loaded=([0-9]{1,6})"
    r"\|rejected=([0-9]{1,6})\Z"
)
_RUNTIME_PCM_STREAM_INACTIVE = (
    "SEDE_RUNTIME_V1|event=pcm_stream|status=inactive"
)
_RUNTIME_PCM_STREAM_READY_RE = re.compile(
    r"SEDE_RUNTIME_V1\|event=pcm_stream\|status=ready"
    r"\|tracks=([1-9][0-9]{0,2})\|max_streams=2"
    r"\|buffer_budget=16777216\Z"
)
_RUNTIME_PCM_STREAM_LANE_FALLBACK_RE = re.compile(
    r"SEDE_RUNTIME_V1\|event=pcm_stream\|status=fallback"
    r"\|scope=lane\|reason=(already_attempted|harmony_missing|prepare_failed)"
    r"(?:\|detail=([A-Za-z_][A-Za-z0-9_.+`]{0,127}))?\Z"
)
_RUNTIME_PCM_STREAM_TRACK_FALLBACK_RE = re.compile(
    r"SEDE_RUNTIME_V1\|event=pcm_stream\|status=fallback"
    r"\|scope=track\|request=([A-Za-z0-9_.-]{1,96}\.wav)"
    r"\|reason=(reader_fault|cache_request|wrong_thread|permanent_failure|runtime_fault|budget_denied|clip_create_failed)\Z"
)
_RUNTIME_PCM_STREAM_SUMMARY_RE = re.compile(
    r"SEDE_RUNTIME_V1\|event=pcm_stream_summary\|status=complete"
    r"\|requested=([0-9]{1,10})\|served=([0-9]{1,10})"
    r"\|fallback=([0-9]{1,10})\|budget_denied=([0-9]{1,10})\Z"
)
_RUNTIME_EVENTS = frozenset(
    {
        RUNTIME_CAPABILITIES_OK,
        RUNTIME_INITIALIZED,
        RUNTIME_INITIALIZATION_FAILED,
        RUNTIME_AUDIO_INACTIVE,
        RUNTIME_AUDIO_ACTIVE,
        RUNTIME_AUDIO_FAILED,
        RUNTIME_FOLIAGE_INACTIVE,
        RUNTIME_FOLIAGE_SUCCEEDED,
        RUNTIME_FOLIAGE_FAILED,
        RUNTIME_WOLF_SPRITE_ROUTE_ACTIVE,
        RUNTIME_ROSTER_INACTIVE,
        RUNTIME_ROSTER_MONITOR_HEALTHY,
        RUNTIME_MUSIC_ROUTE_INACTIVE,
        RUNTIME_FARM_PLACEMENT_INACTIVE,
        RUNTIME_FARM_PLACEMENT_ACTIVE,
        RUNTIME_FARM_PLACEMENT_FAILED,
        RUNTIME_WORKER_MILITIA_INACTIVE,
        RUNTIME_WORKER_MILITIA_ACTIVE,
        RUNTIME_WORKER_MILITIA_FAILED,
        RUNTIME_WORKER_MILITIA_MULTIPLAYER_SUPPRESSED,
        RUNTIME_FORTIFICATIONS_INACTIVE,
        RUNTIME_FORTIFICATIONS_ACTIVE,
        RUNTIME_FORTIFICATIONS_CORE_ACTIVE,
        RUNTIME_DOCK_PLACEMENT_INACTIVE,
        RUNTIME_DOCK_PLACEMENT_ACTIVE,
        RUNTIME_DOCK_PLACEMENT_FAILED,
    }
)
_RUNTIME_FAILED_EVENTS = frozenset(
    {
        RUNTIME_INITIALIZATION_FAILED,
        RUNTIME_AUDIO_FAILED,
        RUNTIME_FOLIAGE_FAILED,
        RUNTIME_FARM_PLACEMENT_FAILED,
        RUNTIME_WORKER_MILITIA_FAILED,
        RUNTIME_DOCK_PLACEMENT_FAILED,
    }
)
_RUNTIME_LOGGER_NAME = "Stronghold Europe DE Runtime (Private)"
_RUNTIME_INFO_EVENT_RE = re.compile(
    rf"^\[Info   :{re.escape(_RUNTIME_LOGGER_NAME)}\] "
    rf"({re.escape(RUNTIME_EVENT_PREFIX)}[^\r\n]*)\Z"
)
_RUNTIME_ERROR_EVENT_RE = re.compile(
    rf"^\[Error  :{re.escape(_RUNTIME_LOGGER_NAME)}\] "
    rf"({re.escape(RUNTIME_EVENT_PREFIX)}[^\r\n]*)\Z"
)
_ROSTER_XAML_LOGICAL_PATHS = (
    "Assets/GUI/XAMLResources/HUD_Main.xaml",
    "Assets/GUI/XAMLResources/HUD_Buildings.xaml",
)
_RUNTIME_ANY_EVENT_RE = re.compile(
    rf"^\[(?P<level>[A-Za-z]+)\s*:{re.escape(_RUNTIME_LOGGER_NAME)}\] "
    rf"(?P<event>{re.escape(RUNTIME_EVENT_PREFIX)}[^\r\n]*)\Z"
)


def _runtime_roster_failure_match(event: str) -> re.Match[str] | None:
    match = _RUNTIME_ROSTER_FAILURE_RE.fullmatch(event)
    if match is None or match.group(2) not in _RUNTIME_ROSTER_FAILURE_REASONS:
        return None
    return match


def _recognized_runtime_event(event: str) -> bool:
    return (
        event in _RUNTIME_EVENTS
        or event == _RUNTIME_ASSET_STREAM_INACTIVE
        or event == _RUNTIME_PCM_STREAM_INACTIVE
        or _RUNTIME_ROSTER_ACTIVE_RE.fullmatch(event) is not None
        or _RUNTIME_ROSTER_UI_RE.fullmatch(event) is not None
        or _runtime_roster_failure_match(event) is not None
        or _RUNTIME_ROSTER_CLEANUP_RE.fullmatch(event) is not None
        or _RUNTIME_WOLF_SPRITE_ROUTE_FAILED_RE.fullmatch(event) is not None
        or _RUNTIME_MUSIC_ROUTE_ACTIVE_RE.fullmatch(event) is not None
        or _RUNTIME_FARM_SUMMARY_RE.fullmatch(event) is not None
        or _RUNTIME_WORKER_MILITIA_SELECTION_RE.fullmatch(event) is not None
        or _RUNTIME_WORKER_MILITIA_SCOPE_RE.fullmatch(event) is not None
        or _RUNTIME_WORKER_MILITIA_UI_READY_RE.fullmatch(event) is not None
        or _RUNTIME_WORKER_MILITIA_COMMAND_RE.fullmatch(event) is not None
        or _RUNTIME_WORKER_MILITIA_NATIVE_MOVE_RE.fullmatch(event) is not None
        or (
            _RUNTIME_WORKER_MILITIA_NATIVE_WORK_MOVE_SUPPRESSED_RE.fullmatch(
                event
            )
            is not None
        )
        or _RUNTIME_WORKER_MILITIA_FLAG_RESTORED_RE.fullmatch(event) is not None
        or _RUNTIME_WORKER_MILITIA_HUNTER_DAMAGE_RE.fullmatch(event) is not None
        or _RUNTIME_WORKER_MILITIA_WOODCUTTER_DAMAGE_RE.fullmatch(event) is not None
        or _RUNTIME_WORKER_MILITIA_HOLD_STARTED_RE.fullmatch(event) is not None
        or _RUNTIME_WORKER_MILITIA_HOLD_COMPLETED_RE.fullmatch(event) is not None
        or (
            _RUNTIME_WORKER_MILITIA_COMBAT_DIRECT_WORK_RE.fullmatch(event)
            is not None
        )
        or (
            _RUNTIME_WORKER_MILITIA_HANDOFF_RESTORED_RE.fullmatch(event)
            is not None
        )
        or _RUNTIME_WORKER_MILITIA_DIRECT_WORK_RE.fullmatch(event) is not None
        or (
            _RUNTIME_WORKER_MILITIA_QUARANTINE_RECOVERED_RE.fullmatch(event)
            is not None
        )
        or _RUNTIME_WORKER_MILITIA_PERFORMANCE_RE.fullmatch(event) is not None
        or _RUNTIME_DIPLOMACY_EVENT_RE.fullmatch(event) is not None
        or _RUNTIME_FORTIFICATIONS_FAILURE_RE.fullmatch(event) is not None
        or _RUNTIME_FORTIFICATION_SCOPE_RE.fullmatch(event) is not None
        or _RUNTIME_FORTIFICATION_SELECTION_RE.fullmatch(event) is not None
        or _RUNTIME_FORTIFICATION_PLACED_RE.fullmatch(event) is not None
        or _RUNTIME_DOCK_SUMMARY_RE.fullmatch(event) is not None
        or _RUNTIME_DOCK_ENFORCE_ACTIVE_RE.fullmatch(event) is not None
        or _RUNTIME_ASSET_STREAM_INITIALIZED_RE.fullmatch(event) is not None
        or _RUNTIME_ASSET_STREAM_STATE_RE.fullmatch(event) is not None
        or _RUNTIME_ASSET_STREAM_SCENE_RESET_RE.fullmatch(event) is not None
        or _RUNTIME_ASSET_STREAM_BASELINE_CAPTURED_RE.fullmatch(event) is not None
        or _RUNTIME_ASSET_STREAM_BASELINE_VANILLA_RE.fullmatch(event) is not None
        or _RUNTIME_ASSET_STREAM_PENDING_RE.fullmatch(event) is not None
        or _RUNTIME_ASSET_STREAM_TERMINAL_RE.fullmatch(event) is not None
        or _RUNTIME_ASSET_STREAM_SUMMARY_RE.fullmatch(event) is not None
        or _RUNTIME_ASSET_MASK_ROUTE_RE.fullmatch(event) is not None
        or _RUNTIME_UI_STREAM_READY_RE.fullmatch(event) is not None
        or _RUNTIME_UI_STREAM_UNAVAILABLE_RE.fullmatch(event) is not None
        or _RUNTIME_UI_STREAM_FAILED_CLOSED_RE.fullmatch(event) is not None
        or _RUNTIME_UI_STREAM_TERMINAL_RE.fullmatch(event) is not None
        or _RUNTIME_UI_STREAM_SUMMARY_RE.fullmatch(event) is not None
        or _RUNTIME_PCM_STREAM_READY_RE.fullmatch(event) is not None
        or _RUNTIME_PCM_STREAM_LANE_FALLBACK_RE.fullmatch(event) is not None
        or _RUNTIME_PCM_STREAM_TRACK_FALLBACK_RE.fullmatch(event) is not None
        or _RUNTIME_PCM_STREAM_SUMMARY_RE.fullmatch(event) is not None
    )


def _runtime_event_requires_error(event: str) -> bool:
    return (
        event in _RUNTIME_FAILED_EVENTS
        or _runtime_roster_failure_match(event) is not None
        or _RUNTIME_WOLF_SPRITE_ROUTE_FAILED_RE.fullmatch(event) is not None
        or _RUNTIME_UI_STREAM_FAILED_CLOSED_RE.fullmatch(event) is not None
        or _RUNTIME_DIPLOMACY_FAILURE_RE.fullmatch(event) is not None
        or _RUNTIME_FORTIFICATIONS_FAILURE_RE.fullmatch(event) is not None
    )


def _runtime_event_expected_level(event: str) -> str:
    """Return the one BepInEx severity allowed by the stable event schema."""

    if _runtime_event_requires_error(event):
        return "error"
    asset_state = _RUNTIME_ASSET_STREAM_STATE_RE.fullmatch(event)
    asset_terminal = _RUNTIME_ASSET_STREAM_TERMINAL_RE.fullmatch(event)
    ui_unavailable = _RUNTIME_UI_STREAM_UNAVAILABLE_RE.fullmatch(event)
    ui_terminal = _RUNTIME_UI_STREAM_TERMINAL_RE.fullmatch(event)
    mask_route = _RUNTIME_ASSET_MASK_ROUTE_RE.fullmatch(event)
    if (
        (asset_state is not None and asset_state.group(1) == "vanilla")
        or _RUNTIME_ASSET_STREAM_BASELINE_VANILLA_RE.fullmatch(event) is not None
        or (
            asset_terminal is not None
            and asset_terminal.group(1) == "group_fallback"
        )
        or ui_unavailable is not None
        or (
            ui_terminal is not None
            and ui_terminal.group(1) == "rejected_fail_closed"
        )
        or _RUNTIME_PCM_STREAM_LANE_FALLBACK_RE.fullmatch(event) is not None
        or _RUNTIME_PCM_STREAM_TRACK_FALLBACK_RE.fullmatch(event) is not None
        or (mask_route is not None and mask_route.group("anomaly") == "1")
    ):
        return "warning"
    return "info"


def _check(name: str, condition: bool, detail: str) -> ValidationCheck:
    return ValidationCheck(name=name, ok=bool(condition), detail=detail)


class _DuplicateJsonKeyError(ValueError):
    pass


class _InvalidJsonConstantError(ValueError):
    pass


_WINDOWS_DEVICE_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)
_PROFILE_ID_RE = re.compile(
    r"[a-z0-9](?:[a-z0-9._-]{0,62}[a-z0-9])?\Z"
)
_BUILD_MANIFEST_KEYS = frozenset(
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
_INSTALL_MANIFEST_KEYS = frozenset(
    {"schema_version", "installed_at_utc", "destination", "files"}
)
_OUTPUT_ENTRY_KEYS = frozenset(
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


def _reject_json_constant(value: str) -> object:
    raise _InvalidJsonConstantError(f"non-finite JSON constant: {value}")


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKeyError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _read_json_object(path: Path) -> tuple[dict[str, object] | None, str]:
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
        return None, f"top-level JSON value must be an object, got {type(value).__name__}"
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


def _canonical_relative_path(value: object) -> bool:
    if not isinstance(value, str) or not value or "\\" in value or "\0" in value:
        return False
    pure = PurePosixPath(value)
    return (
        not pure.is_absolute()
        and pure.as_posix() == value
        and all(part not in {"", ".", ".."} for part in pure.parts)
        and all(":" not in part for part in pure.parts)
    )


def _safe_profile_identifier(value: object) -> bool:
    return (
        isinstance(value, str)
        and _PROFILE_ID_RE.fullmatch(value) is not None
        and ".." not in value
        and value.split(".", 1)[0].upper() not in _WINDOWS_DEVICE_NAMES
    )


def _safe_absolute_windows_path(value: object) -> tuple[bool, str]:
    if not isinstance(value, str) or not value or "\0" in value:
        return False, "path must be a non-empty NUL-free string"
    windows = PureWindowsPath(value)
    if not windows.is_absolute() or (windows.drive and not windows.root):
        return False, "path must be absolute, not drive-relative"
    if windows.drive.casefold().startswith(("\\\\?\\", "\\\\.\\")):
        return False, "Windows device namespaces are forbidden"
    if str(windows) != value:
        return False, "path must use canonical Windows separators"
    for part in windows.parts[1:]:
        if not part or part.endswith((".", " ")):
            return False, f"unsafe trailing dot/space component: {part!r}"
        if ":" in part:
            return False, f"alternate-data-stream component is forbidden: {part!r}"
        device_stem = part.split(".", 1)[0].upper()
        if device_stem in _WINDOWS_DEVICE_NAMES:
            return False, f"Windows device component is forbidden: {part!r}"
    return True, str(windows)


def _lexical_windows_path_key(value: str | Path) -> str:
    return str(PureWindowsPath(str(value))).casefold()


def _non_reparse_chain(base: Path, target: Path) -> tuple[bool, str]:
    base_absolute = base.absolute()
    target_absolute = target.absolute()
    try:
        relative = target_absolute.relative_to(base_absolute)
    except ValueError:
        return False, f"target={target_absolute} is outside base={base_absolute}"
    paths = [base_absolute]
    current = base_absolute
    for part in relative.parts:
        current = current / part
        paths.append(current)
    unsafe = [str(path) for path in paths if _is_link_or_reparse(path)]
    return not unsafe, json.dumps({"checked": [str(path) for path in paths], "unsafe": unsafe})


def _bounded_log_int(value: str, maximum: int, *, minimum: int = 0) -> int | None:
    if not value.isascii() or not value.isdecimal() or len(value) > 10:
        return None
    parsed = int(value)
    return parsed if minimum <= parsed <= maximum else None


def _install_manifest_schema(manifest: dict[str, object]) -> tuple[bool, str]:
    errors: list[str] = []
    if set(manifest) != _INSTALL_MANIFEST_KEYS:
        errors.append(
            "install manifest keys are not exact: "
            f"missing={sorted(_INSTALL_MANIFEST_KEYS-set(manifest))!r} "
            f"extra={sorted(set(manifest)-_INSTALL_MANIFEST_KEYS)!r}"
        )
    if type(manifest.get("schema_version")) is not int:
        errors.append("schema_version must be an integer")
    elif manifest["schema_version"] != 1:
        errors.append(f"unsupported schema_version={manifest['schema_version']!r}")

    installed_at = manifest.get("installed_at_utc")
    if not isinstance(installed_at, str) or not installed_at:
        errors.append("installed_at_utc must be a non-empty string")
    else:
        try:
            parsed_installed_at = datetime.fromisoformat(installed_at)
            if parsed_installed_at.utcoffset() is None:
                errors.append("installed_at_utc must include a UTC offset")
        except ValueError:
            errors.append("installed_at_utc must be an ISO-8601 timestamp")

    raw_destination = manifest.get("destination")
    destination_ok, destination_detail = _safe_absolute_windows_path(raw_destination)
    if not destination_ok:
        errors.append(f"destination is unsafe: {destination_detail}")

    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        errors.append("files must be a non-empty object")

    return not errors, json.dumps({"errors": errors}, sort_keys=True)


def _build_manifest_schema(
    manifest: dict[str, object],
    installed_files: dict[str, str],
    destination: Path,
) -> tuple[bool, str]:
    errors: list[str] = []
    if set(manifest) != _BUILD_MANIFEST_KEYS:
        errors.append(
            "build manifest keys are not exact: "
            f"missing={sorted(_BUILD_MANIFEST_KEYS-set(manifest))!r} "
            f"extra={sorted(set(manifest)-_BUILD_MANIFEST_KEYS)!r}"
        )
    if type(manifest.get("schema_version")) is not int:
        errors.append("schema_version must be an integer")
    elif manifest["schema_version"] != 1:
        errors.append(f"unsupported schema_version={manifest['schema_version']!r}")

    if not _safe_profile_identifier(manifest.get("profile_id")):
        errors.append("profile_id must be a safe lowercase identifier")

    for field_name in ("source_build_id", "target_build_id"):
        value = manifest.get(field_name)
        if not isinstance(value, str) or not value:
            errors.append(f"{field_name} must be a non-empty string")

    if not isinstance(manifest.get("profile_description"), str):
        errors.append("profile_description must be a string")

    if not isinstance(manifest.get("mod_info"), dict):
        errors.append("mod_info must be an object")

    outputs = manifest.get("outputs")
    declared_paths: set[str] = set()
    folded_paths: set[str] = set()
    if not isinstance(outputs, list):
        errors.append("outputs must be a list")
    else:
        for index, raw_entry in enumerate(outputs):
            if not isinstance(raw_entry, dict):
                errors.append(f"outputs[{index}] must be an object")
                continue
            if set(raw_entry) != _OUTPUT_ENTRY_KEYS:
                errors.append(
                    f"outputs[{index}] keys are not exact: "
                    f"missing={sorted(_OUTPUT_ENTRY_KEYS-set(raw_entry))!r} "
                    f"extra={sorted(set(raw_entry)-_OUTPUT_ENTRY_KEYS)!r}"
                )
            relative = raw_entry.get("relative_path")
            if not _canonical_relative_path(relative):
                errors.append(f"outputs[{index}].relative_path is not canonical")
                continue
            assert isinstance(relative, str)
            folded = relative.casefold()
            if folded in folded_paths:
                errors.append(
                    f"outputs[{index}].relative_path is a case-insensitive duplicate: "
                    f"{relative!r}"
                )
            folded_paths.add(folded)
            declared_paths.add(relative)

            category = raw_entry.get("category")
            if not isinstance(category, str) or not category:
                errors.append(f"outputs[{index}].category must be a non-empty string")
            raw_size = raw_entry.get("size")
            if type(raw_size) is not int or raw_size < 0:
                errors.append(f"outputs[{index}].size must be a non-negative integer")
            width = raw_entry.get("width")
            height = raw_entry.get("height")
            geometry_ok = (
                (width is None and height is None)
                or (
                    type(width) is int
                    and width > 0
                    and type(height) is int
                    and height > 0
                )
            )
            if not geometry_ok:
                errors.append(f"outputs[{index}] width/height shape is invalid")
            source_reference = raw_entry.get("source_reference")
            if source_reference is not None and (
                not isinstance(source_reference, str) or not source_reference
            ):
                errors.append(
                    f"outputs[{index}].source_reference must be null or non-empty string"
                )
            lost_alpha = raw_entry.get("lost_alpha")
            if lost_alpha is not None and (
                type(lost_alpha) is not int or lost_alpha < 0
            ):
                errors.append(
                    f"outputs[{index}].lost_alpha must be null or non-negative integer"
                )
            if raw_entry.get("metadata") is not None and not isinstance(
                raw_entry.get("metadata"), dict
            ):
                errors.append(f"outputs[{index}].metadata must be null or object")
            raw_digest = raw_entry.get("sha256")
            if (
                not isinstance(raw_digest, str)
                or re.fullmatch(r"[0-9a-f]{64}", raw_digest) is None
            ):
                errors.append(f"outputs[{index}].sha256 must be lowercase SHA-256")

            snapshot_digest = installed_files.get(relative)
            if snapshot_digest is None:
                errors.append(f"outputs[{index}] is absent from the install snapshot")
                continue
            if raw_digest != snapshot_digest:
                errors.append(f"outputs[{index}].sha256 differs from install snapshot")
            try:
                actual_size = (destination / PurePosixPath(relative)).stat().st_size
            except OSError as exc:
                errors.append(f"outputs[{index}] cannot be inspected: {exc}")
            else:
                if raw_size != actual_size:
                    errors.append(f"outputs[{index}].size differs from installed file")

    expected_paths = set(installed_files) - {"build-manifest.json"}
    if "build-manifest.json" not in installed_files:
        errors.append("install snapshot does not contain build-manifest.json")
    if declared_paths != expected_paths:
        errors.append(
            "output path set differs from install snapshot: "
            f"missing={sorted(expected_paths-declared_paths)!r} "
            f"extra={sorted(declared_paths-expected_paths)!r}"
        )

    return not errors, json.dumps(
        {
            "declared": len(declared_paths),
            "expected": len(expected_paths),
            "errors": errors,
        },
        sort_keys=True,
    )


def _info_schema(
    info: dict[str, object],
    embedded_mod_info: object,
) -> tuple[bool, str]:
    errors: list[str] = []
    guid = info.get("GUID")
    if not isinstance(guid, str) or not guid:
        errors.append("GUID must be a non-empty string")
    version = info.get("Version")
    if not isinstance(version, str) or not version:
        errors.append("Version must be a non-empty string")
    if type(info.get("Manifest")) is not int or info.get("Manifest") != 0:
        errors.append("Manifest must be integer 0")
    if info != embedded_mod_info:
        errors.append("info.json must exactly equal build-manifest mod_info")
    return not errors, json.dumps({"errors": errors}, sort_keys=True)


def _runtime_artifact_checks(
    destination: Path,
    output_by_path: dict[str, dict[str, object]],
    source_build_id: str,
    target_build_id: str,
    profile_id: str,
) -> tuple[
    list[ValidationCheck],
    bool,
    dict[str, object] | None,
    set[str],
    bool | None,
    dict[str, object] | None,
    bool | None,
    bool | None,
    bool | None,
    bool | None,
    bool | None,
    dict[str, object] | None,
]:
    checks: list[ValidationCheck] = []
    dll_entry = output_by_path.get(RUNTIME_DLL_PATH)
    contract_entry = output_by_path.get(RUNTIME_CONTRACT_PATH)
    roster_entry = output_by_path.get(RUNTIME_ROSTER_CONTRACT_PATH)
    fortification_entry = output_by_path.get(
        RUNTIME_FORTIFICATION_CONTRACT_PATH
    )
    dll_present = dll_entry is not None
    contract_present = contract_entry is not None
    roster_present = roster_entry is not None
    fortification_present = fortification_entry is not None
    runtime_path_present = dll_present or contract_present
    runtime_source_digest, runtime_source_detail = _runtime_source_set_identity()
    unsafe_outputs = sorted(
        relative
        for relative, entry in output_by_path.items()
        if PurePosixPath(relative).suffix.casefold()
        in _RUNTIME_FORBIDDEN_SUFFIXES
        and not (
            relative == RUNTIME_DLL_PATH
            and entry.get("category") == RUNTIME_DLL_CATEGORY
        )
    )
    checks.append(
        _check(
            "runtime.installed_safe_suffixes",
            not unsafe_outputs,
            json.dumps(unsafe_outputs),
        )
    )
    checks.append(
        _check(
            "runtime.companion_path_pair",
            dll_present == contract_present,
            f"dll={dll_present} contract={contract_present}",
        )
    )
    checks.append(
        _check(
            "runtime.companion_source_set_inputs",
            not dll_present or runtime_source_digest is not None,
            runtime_source_detail,
        )
    )
    checks.append(
        _check(
            "runtime.companion_dll_category",
            not dll_present or dll_entry.get("category") == RUNTIME_DLL_CATEGORY,
            str(dll_entry.get("category") if dll_entry is not None else None),
        )
    )
    checks.append(
        _check(
            "runtime.companion_contract_category",
            not contract_present
            or contract_entry.get("category") == "runtime_contract",
            str(contract_entry.get("category") if contract_entry is not None else None),
        )
    )
    checks.append(
        _check(
            "runtime.companion_dll_source",
            not dll_present
            or dll_entry.get("source_reference")
            == RUNTIME_DLL_SOURCE_REFERENCE,
            str(dll_entry.get("source_reference") if dll_entry else None),
        )
    )
    checks.append(
        _check(
            "runtime.companion_contract_source",
            not contract_present
            or contract_entry.get("source_reference")
            == RUNTIME_CONTRACT_SOURCE_REFERENCE,
            str(
                contract_entry.get("source_reference")
                if contract_entry
                else None
            ),
        )
    )
    dll_metadata_value = dll_entry.get("metadata") if dll_entry is not None else None
    dll_metadata = dll_metadata_value if isinstance(dll_metadata_value, dict) else {}
    raw_roster_selection = dll_metadata.get("unit_roster_names")
    roster_enabled = (
        raw_roster_selection if isinstance(raw_roster_selection, bool) else None
    )
    raw_farm_selection = dll_metadata.get("farm_placement")
    farm_enabled = raw_farm_selection if isinstance(raw_farm_selection, bool) else None
    raw_worker_militia_selection = dll_metadata.get("worker_militia")
    worker_militia_enabled = (
        raw_worker_militia_selection
        if isinstance(raw_worker_militia_selection, bool)
        else None
    )
    raw_diplomacy_selection = dll_metadata.get("diplomacy")
    diplomacy_enabled = (
        raw_diplomacy_selection
        if isinstance(raw_diplomacy_selection, bool)
        else None
    )
    raw_diplomacy_rules = dll_metadata.get("diplomacy_rules")
    raw_fortifications_selection = dll_metadata.get("fortifications")
    fortifications_enabled = (
        raw_fortifications_selection
        if isinstance(raw_fortifications_selection, bool)
        else None
    )
    raw_fortification_catalog_sha256 = dll_metadata.get(
        "fortification_catalog_sha256"
    )
    raw_dock_selection = dll_metadata.get("dock_placement")
    dock_enabled = raw_dock_selection if isinstance(raw_dock_selection, bool) else None
    # None = reine Messbahn; ein Objekt sind die drei Regelwerte, gegen die
    # die enforce-Aktivzeile des Protokolls abgeglichen wird.
    raw_dock_rules = dll_metadata.get("dock_placement_rules")
    dock_rules = raw_dock_rules if isinstance(raw_dock_rules, dict) else None
    checks.append(
        _check(
            "runtime.companion_roster_selection_shape",
            not dll_present or roster_enabled is not None,
            repr(raw_roster_selection),
        )
    )
    checks.append(
        _check(
            "runtime.companion_diplomacy_selection_shape",
            not dll_present
            or (
                diplomacy_enabled is not None
                and _diplomacy_rules_metadata_ok(
                    raw_diplomacy_rules,
                    diplomacy_enabled,
                )
                and (
                    diplomacy_enabled is not True
                    or profile_id in _DIPLOMACY_ROLLOUT_PROFILE_IDS
                )
            ),
            f"selected={diplomacy_enabled!r} rules={raw_diplomacy_rules!r} "
            f"profile={profile_id!r}",
        )
    )
    checks.append(
        _check(
            "runtime.companion_fortifications_selection_shape",
            not dll_present
            or _runtime_fortification_selection_metadata_ok(dll_metadata),
            "selected=" + repr(fortifications_enabled)
            + " catalog=" + repr(raw_fortification_catalog_sha256),
        )
    )
    checks.append(
        _check(
            "runtime.companion_roster_artifact_presence",
            roster_present == (roster_enabled is True),
            f"selected={roster_enabled} present={roster_present}",
        )
    )
    checks.append(
        _check(
            "runtime.companion_fortification_artifact_presence",
            fortification_present == (fortifications_enabled is True),
            f"selected={fortifications_enabled} "
            f"present={fortification_present}",
        )
    )
    locale_paths = {
        relative
        for relative, entry in output_by_path.items()
        if relative.casefold().startswith("locales/")
        or entry.get("category") == "locale_override"
    }
    checks.append(
        _check(
            "runtime.companion_roster_locale_exclusive",
            not (roster_enabled is True and locale_paths),
            f"selected={roster_enabled} locales={sorted(locale_paths)}",
        )
    )
    roster_canary = profile_id == "europe-roster-runtime-canary"
    if roster_canary:
        roster_output_contract_ok, roster_output_contract_detail = (
            _runtime_roster_canary_output_contract(output_by_path)
        )
        logo_entry = output_by_path.get(_RUNTIME_ROSTER_LOGO_PATH)
        logo_ok, logo_size, logo_detail = _png_contract(
            destination / _RUNTIME_ROSTER_LOGO_PATH,
            logo_entry,
        )
        checks.append(
            _check(
                "runtime.companion_roster_canary_selection",
                roster_enabled is True,
                f"selected={roster_enabled}",
            )
        )
        checks.append(
            _check(
                "runtime.companion_roster_isolated_output_set",
                set(output_by_path) == _RUNTIME_ROSTER_ISOLATED_OUTPUTS,
                f"actual={sorted(output_by_path)}",
            )
        )
        checks.append(
            _check(
                "runtime.companion_roster_isolated_output_contract",
                roster_output_contract_ok,
                roster_output_contract_detail,
            )
        )
        checks.append(
            _check(
                "runtime.companion_roster_logo_png",
                logo_ok and logo_size == (256, 256),
                logo_detail,
            )
        )

    parsed_roster: dict[str, object] | None = None
    if roster_present:
        roster_path = destination / RUNTIME_ROSTER_CONTRACT_PATH
        roster_parse_detail = RUNTIME_ROSTER_CONTRACT_PATH
        try:
            parsed_roster = _parse_roster_runtime_contract(roster_path)
            roster_parse_detail = (
                f"entries={parsed_roster['entry_count']} "
                f"hud={parsed_roster['hud_control_count']} "
                f"sha256={parsed_roster['manifest_sha256']}"
            )
        except (OSError, ValueError, RosterRuntimeContractError) as exc:
            roster_parse_detail = str(exc)
        checks.append(
            _check(
                "runtime.companion_roster_contract_schema",
                parsed_roster is not None,
                roster_parse_detail,
            )
        )
        checks.append(
            _check(
                "runtime.companion_roster_contract_category",
                roster_entry.get("category")
                == RUNTIME_ROSTER_CONTRACT_CATEGORY,
                str(roster_entry.get("category")),
            )
        )
        checks.append(
            _check(
                "runtime.companion_roster_contract_source",
                roster_entry.get("source_reference")
                == RUNTIME_ROSTER_SOURCE_REFERENCE,
                str(roster_entry.get("source_reference")),
            )
        )
        checks.append(
            _check(
                "runtime.companion_roster_contract_metadata",
                _runtime_roster_metadata_matches(
                    roster_entry.get("metadata"), parsed_roster
                ),
                json.dumps(roster_entry.get("metadata"), sort_keys=True),
            )
        )

    if fortification_present:
        fortification_path = destination / RUNTIME_FORTIFICATION_CONTRACT_PATH
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
                "runtime.companion_fortification_contract_source_pins",
                expected_payload is not None and expected_metadata is not None,
                expected_detail,
            )
        )
        checks.append(
            _check(
                "runtime.companion_fortification_contract_schema",
                actual_payload is not None
                and expected_payload is not None
                and actual_payload == expected_payload,
                payload_detail,
            )
        )
        checks.append(
            _check(
                "runtime.companion_fortification_contract_category",
                fortification_entry.get("category")
                == RUNTIME_FORTIFICATION_CONTRACT_CATEGORY,
                str(fortification_entry.get("category")),
            )
        )
        checks.append(
            _check(
                "runtime.companion_fortification_contract_source",
                fortification_entry.get("source_reference")
                == RUNTIME_FORTIFICATION_SOURCE_REFERENCE,
                str(fortification_entry.get("source_reference")),
            )
        )
        checks.append(
            _check(
                "runtime.companion_fortification_contract_metadata",
                _runtime_fortification_metadata_matches(
                    fortification_entry.get("metadata"), expected_metadata
                ),
                json.dumps(
                    fortification_entry.get("metadata"), sort_keys=True
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
                "runtime.companion_fortification_contract_dll_binding",
                actual_catalog_digest is not None
                and raw_fortification_catalog_sha256
                == actual_catalog_digest,
                f"dll={raw_fortification_catalog_sha256!r} "
                f"catalog={actual_catalog_digest!r}",
            )
        )

    parsed_contract: dict[str, object] | None = None
    expected_audio_files: set[str] = set()
    contract_digest: str | None = None
    if contract_present:
        contract_path = destination / RUNTIME_CONTRACT_PATH
        contract_digest = sha256_file(contract_path)
        try:
            parsed_contract = parse_runtime_contract(contract_path)
            parse_detail = (
                f"tracks={len(parsed_contract['tracks'])} "
                f"audio={parsed_contract['audio_payload']} "
                f"foliage={parsed_contract['foliage_tree_apple']}"
            )
        except (RuntimeBuildError, OSError, ValueError) as exc:
            parse_detail = str(exc)
        checks.append(
            _check(
                "runtime.companion_contract_schema",
                parsed_contract is not None,
                parse_detail,
            )
        )

        metadata_value = contract_entry.get("metadata")
        contract_metadata = metadata_value if isinstance(metadata_value, dict) else {}
        parsed_tracks = (
            parsed_contract.get("tracks")
            if parsed_contract is not None
            else None
        )
        parsed_audio = (
            parsed_contract.get("audio_payload")
            if parsed_contract is not None
            else None
        )
        parsed_foliage = (
            parsed_contract.get("foliage_tree_apple")
            if parsed_contract is not None
            else None
        )
        contract_binding_ok = (
            parsed_contract is not None
            and isinstance(parsed_tracks, list)
            and contract_entry.get("source_reference")
            == RUNTIME_CONTRACT_SOURCE_REFERENCE
            and set(contract_metadata) == _RUNTIME_CONTRACT_METADATA_KEYS
            and contract_metadata.get("kind")
            == "stronghold_europe_runtime_contract_v1"
            and contract_metadata.get("plugin_id") == RUNTIME_PLUGIN_ID
            and type(contract_metadata.get("track_count")) is int
            and contract_metadata.get("track_count") == len(parsed_tracks)
            and contract_metadata.get("manifest_sha256") == contract_digest
            and contract_metadata.get("audio_payload") is parsed_audio
            and contract_metadata.get("foliage_tree_apple") is parsed_foliage
            and parsed_contract.get("plugin_id") == RUNTIME_PLUGIN_ID
            and parsed_contract.get("source_build_id") == source_build_id
            and parsed_contract.get("target_build_id") == target_build_id
        )
        checks.append(
            _check(
                "runtime.companion_contract_binding",
                contract_binding_ok,
                json.dumps(contract_metadata, sort_keys=True),
            )
        )

        if parsed_contract is not None and isinstance(parsed_tracks, list):
            pcm_streaming = dll_metadata.get("pcm_streaming_enabled") is True
            expected_music_paths = (
                {
                    f"Override/Sounds/Music/{track['output_file']}"
                    for track in parsed_tracks
                    if isinstance(track, dict)
                }
                if parsed_audio is True and not pcm_streaming
                else set()
            )
            actual_music_paths = {
                relative
                for relative in output_by_path
                if relative.startswith("Override/Sounds/Music/")
            }
            checks.append(
                _check(
                    "runtime.companion_audio_file_set",
                    actual_music_paths == expected_music_paths,
                    f"missing={sorted(expected_music_paths-actual_music_paths)} "
                    f"extra={sorted(actual_music_paths-expected_music_paths)}",
                )
            )
            expected_pcm_paths = (
                {
                    f"Runtime/Audio/{track['output_file']}"
                    for track in parsed_tracks
                    if isinstance(track, dict)
                }
                | {"Runtime/Audio/pcm-stream-manifest.tsv"}
                if parsed_audio is True and pcm_streaming
                else set()
            )
            actual_pcm_paths = {
                relative
                for relative in output_by_path
                if relative.startswith("Runtime/Audio/")
            }
            checks.append(
                _check(
                    "runtime.companion_pcm_file_set",
                    actual_pcm_paths == expected_pcm_paths,
                    f"missing={sorted(expected_pcm_paths-actual_pcm_paths)} "
                    f"extra={sorted(actual_pcm_paths-expected_pcm_paths)}",
                )
            )
            expected_audio_files = {
                str(track["output_file"])
                for track in parsed_tracks
                if isinstance(track, dict) and parsed_audio is True
            }
            pcm_manifest_relative = "Runtime/Audio/pcm-stream-manifest.tsv"
            pcm_manifest_entry = output_by_path.get(pcm_manifest_relative)
            expected_pcm_manifest = _pcm_stream_manifest_text(
                [track for track in parsed_tracks if isinstance(track, dict)]
            ).encode("utf-8")
            pcm_manifest_digest = hashlib.sha256(expected_pcm_manifest).hexdigest()
            pcm_manifest_metadata = (
                pcm_manifest_entry.get("metadata")
                if isinstance(pcm_manifest_entry, dict)
                and isinstance(pcm_manifest_entry.get("metadata"), dict)
                else None
            )
            pcm_manifest_ok = (
                not pcm_streaming
                and pcm_manifest_entry is None
                and dll_metadata.get("pcm_stream_manifest_sha256") == ""
            ) or (
                pcm_streaming
                and parsed_audio is True
                and isinstance(pcm_manifest_entry, dict)
                and (destination / pcm_manifest_relative).is_file()
                and (destination / pcm_manifest_relative).read_bytes()
                == expected_pcm_manifest
                and pcm_manifest_entry.get("category")
                == "runtime_pcm_stream_contract"
                and pcm_manifest_entry.get("source_reference")
                == "runtime/StrongholdEuropeDE.Runtime/audio-profile.json"
                and pcm_manifest_metadata
                == {
                    "kind": "stronghold_europe_pcm_stream_v1",
                    "manifest_sha256": pcm_manifest_digest,
                    "track_count": len(parsed_tracks),
                    "max_active_streams": 2,
                    "buffer_budget_bytes": 16 * 1024 * 1024,
                    "buffer_bytes_per_stream": 1024 * 1024,
                }
                and dll_metadata.get("pcm_stream_manifest_sha256")
                == pcm_manifest_digest
            )
            checks.append(
                _check(
                    "runtime.companion_pcm_manifest",
                    pcm_manifest_ok,
                    f"enabled={pcm_streaming} sha256={pcm_manifest_digest} "
                    f"metadata={json.dumps(pcm_manifest_metadata, sort_keys=True)}",
                )
            )
            if parsed_audio is True:
                for track in parsed_tracks:
                    if not isinstance(track, dict):
                        continue
                    relative = (
                        f"Runtime/Audio/{track['output_file']}"
                        if pcm_streaming
                        else f"Override/Sounds/Music/{track['output_file']}"
                    )
                    entry = output_by_path.get(relative)
                    entry_metadata_value = (
                        entry.get("metadata") if entry is not None else None
                    )
                    entry_metadata = (
                        entry_metadata_value
                        if isinstance(entry_metadata_value, dict)
                        else {}
                    )
                    legacy_metadata_ok = (
                        entry is not None
                        and entry.get("category") == "europe_music"
                        and entry.get("source_reference")
                        == f"StreamingAssets/Music/{track['source_file']}"
                        and entry_metadata.get("kind") == "validated_pcm_wav"
                        and entry_metadata.get("music_id") == track["id"]
                        and all(
                            entry_metadata.get(field_name) == track[field_name]
                            for field_name in (
                                "expected_original",
                                "replacement",
                                "volume_raw",
                                "audio_format",
                                "channels",
                                "sample_rate",
                                "bits_per_sample",
                                "block_align",
                                "data_size",
                            )
                        )
                    )
                    pcm_metadata_ok = (
                        entry is not None
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
                    metadata_ok = (
                        pcm_metadata_ok if pcm_streaming else legacy_metadata_ok
                    )
                    checks.append(
                        _check(
                            f"runtime.companion_audio_manifest.{track['id']}",
                            metadata_ok,
                            relative,
                        )
                    )
                    wav_ok = False
                    wav_detail = relative
                    try:
                        if entry is not None:
                            validate_wav(destination / relative, track)
                            wav_ok = True
                    except (RuntimeBuildError, OSError, ValueError) as exc:
                        wav_detail = str(exc)
                    checks.append(
                        _check(
                            f"runtime.companion_audio_pcm.{track['id']}",
                            wav_ok,
                            wav_detail,
                        )
                    )

        if roster_canary:
            checks.append(
                _check(
                    "runtime.companion_roster_canary_features",
                    parsed_contract is not None
                    and parsed_audio is False
                    and parsed_foliage is False,
                    f"audio={parsed_audio} foliage={parsed_foliage}",
                )
            )

    if dll_present:
        dll_path = destination / RUNTIME_DLL_PATH
        metadata_ok = (
            dll_entry.get("category") == RUNTIME_DLL_CATEGORY
            and dll_entry.get("source_reference")
            == RUNTIME_DLL_SOURCE_REFERENCE
            and set(dll_metadata) == _RUNTIME_DLL_METADATA_KEYS
            and dll_metadata.get("kind") == "net481_bepinex_runtime_companion"
            and dll_metadata.get("plugin_id") == RUNTIME_PLUGIN_ID
            and dll_metadata.get("assembly_name") == RUNTIME_ASSEMBLY_NAME
            and dll_metadata.get("assembly_version") == RUNTIME_ASSEMBLY_VERSION
            and dll_metadata.get("target_framework") == "net481"
            and dll_metadata.get("runtime_prerequisite_config_id")
            == "local-shcde-2.80-shcdese-2.11-net481-win-x64"
            and dll_metadata.get("runtime_prerequisite_mvids")
            == RUNTIME_PREREQUISITE_MVIDS
            and dll_metadata.get("manifest_sha256") == contract_digest
            and isinstance(dll_metadata.get("unit_roster_names"), bool)
            and isinstance(dll_metadata.get("farm_placement"), bool)
            and isinstance(dll_metadata.get("worker_militia"), bool)
            and isinstance(dll_metadata.get("diplomacy"), bool)
            and _diplomacy_rules_metadata_ok(
                dll_metadata.get("diplomacy_rules"),
                dll_metadata.get("diplomacy"),
            )
            and _runtime_fortification_selection_metadata_ok(dll_metadata)
            and isinstance(dll_metadata.get("dock_placement"), bool)
            and _dock_placement_rules_metadata_ok(
                dll_metadata.get("dock_placement_rules"),
                dll_metadata.get("dock_placement"),
            )
            and dll_metadata.get("runtime_source_set_sha256")
            == runtime_source_digest
            and _runtime_streaming_metadata_ok(dll_metadata)
        )
        checks.append(
            _check(
                "runtime.companion_dll_manifest",
                metadata_ok,
                json.dumps(dll_metadata, sort_keys=True),
            )
        )
        pe_clr_ok, pe_clr_detail = _pe_clr_header(dll_path)
        checks.append(
            _check("runtime.companion_dll_pe_clr", pe_clr_ok, pe_clr_detail)
        )
        identity = _managed_assembly_identity(dll_path) if pe_clr_ok else None
        checks.append(
            _check(
                "runtime.companion_dll_identity",
                identity == (RUNTIME_ASSEMBLY_NAME, RUNTIME_ASSEMBLY_VERSION),
                str(identity),
            )
        )
        attestation = _managed_assembly_attestation(dll_path) if pe_clr_ok else None
        expected_attestation = _runtime_assembly_attestation_expected(
            manifest_sha256=contract_digest,
            source_build_id=source_build_id,
            target_build_id=target_build_id,
            prerequisite_mvids=dll_metadata.get("runtime_prerequisite_mvids"),
            roster_contract=parsed_roster,
            roster_enabled=roster_enabled is True,
            runtime_source_sha256=runtime_source_digest,
            worker_militia_enabled=worker_militia_enabled is True,
            fortifications_enabled=fortifications_enabled is True,
            fortification_catalog_sha256=str(
                raw_fortification_catalog_sha256 or ""
            ),
            asset_stream_enabled=(
                dll_metadata.get("asset_stream_enabled") is True
            ),
            asset_stream_index_sha256=str(
                dll_metadata.get("asset_stream_index_sha256", "")
            ),
            ui_texture_streaming_enabled=(
                dll_metadata.get("ui_texture_streaming_enabled") is True
            ),
            ui_texture_manifest_sha256=str(
                dll_metadata.get("ui_texture_manifest_sha256", "")
            ),
            pcm_streaming_enabled=(
                dll_metadata.get("pcm_streaming_enabled") is True
            ),
            pcm_stream_manifest_sha256=str(
                dll_metadata.get("pcm_stream_manifest_sha256", "")
            ),
        )
        attestation_ok = attestation == expected_attestation
        checks.append(
            _check(
                "runtime.companion_dll_attestation",
                attestation_ok,
                json.dumps(attestation or {}, sort_keys=True),
            )
        )

    return (
        checks,
        runtime_path_present,
        parsed_contract,
        expected_audio_files,
        roster_enabled,
        parsed_roster,
        farm_enabled,
        worker_militia_enabled,
        diplomacy_enabled,
        fortifications_enabled,
        dock_enabled,
        dock_rules,
    )


def _worker_militia_evidence_status(
    runtime_event_lines: dict[str, list[int]],
) -> tuple[bool, dict[str, object]]:
    selection_events = [
        (line_number, match.group(1))
        for event, line_numbers in runtime_event_lines.items()
        for match in [_RUNTIME_WORKER_MILITIA_SELECTION_RE.fullmatch(event)]
        if match is not None
        for line_number in line_numbers
    ]
    ui_ready_events = [
        (line_number, match.group(1), match.group(2))
        for event, line_numbers in runtime_event_lines.items()
        for match in [_RUNTIME_WORKER_MILITIA_UI_READY_RE.fullmatch(event)]
        if match is not None
        for line_number in line_numbers
    ]
    command_events = [
        (line_number, match.group(1), match.group(2))
        for event, line_numbers in runtime_event_lines.items()
        for match in [_RUNTIME_WORKER_MILITIA_COMMAND_RE.fullmatch(event)]
        if match is not None
        for line_number in line_numbers
    ]
    native_move_events = [
        (line_number, match.group(1))
        for event, line_numbers in runtime_event_lines.items()
        for match in [_RUNTIME_WORKER_MILITIA_NATIVE_MOVE_RE.fullmatch(event)]
        if match is not None
        for line_number in line_numbers
    ]
    native_work_move_suppressed_events = [
        (line_number, match.group(1), match.group(2))
        for event, line_numbers in runtime_event_lines.items()
        for match in [
            _RUNTIME_WORKER_MILITIA_NATIVE_WORK_MOVE_SUPPRESSED_RE.fullmatch(
                event
            )
        ]
        if match is not None
        for line_number in line_numbers
    ]
    hunter_damage_events = [
        (
            line_number,
            match.group(1),
            int(match.group(2)),
            int(match.group(3)),
        )
        for event, line_numbers in runtime_event_lines.items()
        for match in [_RUNTIME_WORKER_MILITIA_HUNTER_DAMAGE_RE.fullmatch(event)]
        if match is not None
        for line_number in line_numbers
    ]
    woodcutter_damage_events = [
        (line_number, match.group(1), int(match.group(2)))
        for event, line_numbers in runtime_event_lines.items()
        for match in [
            _RUNTIME_WORKER_MILITIA_WOODCUTTER_DAMAGE_RE.fullmatch(event)
        ]
        if match is not None
        for line_number in line_numbers
    ]
    hold_started_events = [
        (line_number, match.group(1))
        for event, line_numbers in runtime_event_lines.items()
        for match in [_RUNTIME_WORKER_MILITIA_HOLD_STARTED_RE.fullmatch(event)]
        if match is not None
        for line_number in line_numbers
    ]
    hold_completed_events = [
        (line_number, match.group(1))
        for event, line_numbers in runtime_event_lines.items()
        for match in [_RUNTIME_WORKER_MILITIA_HOLD_COMPLETED_RE.fullmatch(event)]
        if match is not None
        for line_number in line_numbers
    ]
    combat_direct_work_events = [
        (line_number, match.group(1), match.group(2))
        for event, line_numbers in runtime_event_lines.items()
        for match in [
            _RUNTIME_WORKER_MILITIA_COMBAT_DIRECT_WORK_RE.fullmatch(event)
        ]
        if match is not None
        for line_number in line_numbers
    ]
    handoff_restored_events = [
        (
            line_number,
            match.group(1),
            match.group(2),
            match.group(3),
            int(match.group(4)),
            int(match.group(5)),
            int(match.group(6)),
            int(match.group(7)),
            int(match.group(8)),
            int(match.group(9)),
        )
        for event, line_numbers in runtime_event_lines.items()
        for match in [
            _RUNTIME_WORKER_MILITIA_HANDOFF_RESTORED_RE.fullmatch(event)
        ]
        if match is not None
        for line_number in line_numbers
    ]
    direct_work_events = [
        (
            line_number,
            match.group(1),
            match.group(2),
            match.group(3),
        )
        for event, line_numbers in runtime_event_lines.items()
        for match in [_RUNTIME_WORKER_MILITIA_DIRECT_WORK_RE.fullmatch(event)]
        if match is not None
        for line_number in line_numbers
    ]
    evidence: dict[str, object] = {
        "selected": selection_events,
        "ui_ready": ui_ready_events,
        "command": command_events,
        "native_move": native_move_events,
        "native_work_move_suppressed": native_work_move_suppressed_events,
        "hunter_damage": hunter_damage_events,
        "woodcutter_damage": woodcutter_damage_events,
        "hold_started": hold_started_events,
        "hold_completed": hold_completed_events,
        "combat_to_direct_work": combat_direct_work_events,
        "handoff_restored": handoff_restored_events,
        "direct_work_resumed": direct_work_events,
    }
    selections_by_unit = {
        unit: [event for event in selection_events if event[1] == unit]
        for unit in ("hunter", "woodcutter")
    }
    ui_ready_by_unit = {
        unit: [event for event in ui_ready_events if event[1] == unit]
        for unit in ("hunter", "woodcutter")
    }
    commands_by_path = {
        (unit, mode): [
            event
            for event in command_events
            if event[1] == unit and event[2] == mode
        ]
        for unit in ("hunter", "woodcutter")
        for mode in ("autonomous", "manual")
    }
    native_moves_by_unit = {
        unit: [event for event in native_move_events if event[1] == unit]
        for unit in ("hunter", "woodcutter")
    }
    hunter_by_mode = {
        mode: [event for event in hunter_damage_events if event[1] == mode]
        for mode in ("autonomous", "manual")
    }
    woodcutter_by_mode = {
        mode: [event for event in woodcutter_damage_events if event[1] == mode]
        for mode in ("autonomous", "manual")
    }
    hold_started_by_unit = {
        unit: [event for event in hold_started_events if event[1] == unit]
        for unit in ("hunter", "woodcutter")
    }
    hold_completed_by_unit = {
        unit: [event for event in hold_completed_events if event[1] == unit]
        for unit in ("hunter", "woodcutter")
    }
    combat_direct_by_path = {
        (unit, mode): [
            event
            for event in combat_direct_work_events
            if event[1] == unit and event[2] == mode
        ]
        for unit in ("hunter", "woodcutter")
        for mode in ("autonomous", "manual")
    }
    suppressions_by_unit = {
        unit: [
            event
            for event in native_work_move_suppressed_events
            if event[1] == unit
        ]
        for unit in ("hunter", "woodcutter")
    }
    handoffs_by_path = {
        (unit, mode): [
            event
            for event in handoff_restored_events
            if event[1] == unit and event[2] == mode
        ]
        for unit in ("hunter", "woodcutter")
        for mode in ("autonomous", "manual")
    }
    resumes_by_path = {
        (unit, mode): [
            event
            for event in direct_work_events
            if event[1] == unit and event[2] == mode
        ]
        for unit in ("hunter", "woodcutter")
        for mode in ("autonomous", "manual")
    }
    handoff_keys = {(event[1], event[2], event[3]) for event in handoff_restored_events}
    resume_keys = {(event[1], event[2], event[3]) for event in direct_work_events}
    handoffs_by_key = {
        key: [
            event
            for event in handoff_restored_events
            if (event[1], event[2], event[3]) == key
        ]
        for key in handoff_keys
    }
    resumes_by_key = {
        key: [
            event
            for event in direct_work_events
            if (event[1], event[2], event[3]) == key
        ]
        for key in resume_keys
    }
    selection_ok = len(selection_events) == 2 and all(
        len(events_for_unit) == 1
        for events_for_unit in selections_by_unit.values()
    )
    ui_ready_ok = len(ui_ready_events) == 2 and all(
        len(events_for_unit) == 1
        for events_for_unit in ui_ready_by_unit.values()
    )
    command_ok = len(command_events) == 4 and all(
        len(events_for_path) == 1
        for events_for_path in commands_by_path.values()
    )
    native_move_ok = len(native_move_events) == 2 and all(
        len(events_for_unit) == 1
        for events_for_unit in native_moves_by_unit.values()
    )
    hunter_damage_ok = (
        len(hunter_damage_events) == 2
        and all(
            len(events_for_mode) == 1
            for events_for_mode in hunter_by_mode.values()
        )
        and all(
            event[2] > 0 and event[3] == max(1, event[2] // 2)
            for event in hunter_damage_events
        )
    )
    woodcutter_damage_ok = (
        len(woodcutter_damage_events) == 2
        and all(
            len(events_for_mode) == 1
            for events_for_mode in woodcutter_by_mode.values()
        )
        and all(event[2] > 0 for event in woodcutter_damage_events)
    )
    hold_ok = (
        len(hold_started_events) == 2
        and len(hold_completed_events) == 2
        and all(
            len(hold_started_by_unit[unit]) == 1
            and len(hold_completed_by_unit[unit]) == 1
            for unit in ("hunter", "woodcutter")
        )
    )
    combat_direct_ok = (
        len(combat_direct_work_events) == 4
        and all(
            len(events_for_path) == 1
            for events_for_path in combat_direct_by_path.values()
        )
    )
    suppression_ok = (
        2 <= len(native_work_move_suppressed_events) <= 8
        and all(suppressions_by_unit[unit] for unit in ("hunter", "woodcutter"))
        and len(
            {
                (event[1], event[2])
                for event in native_work_move_suppressed_events
            }
        )
        == len(native_work_move_suppressed_events)
    )
    handoff_ok = (
        len(handoff_restored_events) == 6
        and all(
            len(handoffs_by_path[(unit, "autonomous")]) == 1
            and len(handoffs_by_path[(unit, "manual")]) == 2
            for unit in ("hunter", "woodcutter")
        )
        and all(
            event[4] == event[5] == 0
            and event[6] == event[7]
            and event[8] == event[9]
            and event[6] <= 65535
            and event[8] <= 65535
            for event in handoff_restored_events
        )
        and all(
            len(
                {
                    event[3]
                    for event in handoffs_by_path[(unit, "manual")]
                }
            )
            == 2
            for unit in ("hunter", "woodcutter")
        )
    )
    resume_ok = (
        len(direct_work_events) == 6
        and all(
            len(resumes_by_path[(unit, "autonomous")]) == 1
            and len(resumes_by_path[(unit, "manual")]) == 2
            for unit in ("hunter", "woodcutter")
        )
    )
    pair_ok = (
        handoff_keys == resume_keys
        and len(handoff_keys) == 6
        and all(
            len(handoffs_by_key[key]) == 1
            and len(resumes_by_key[key]) == 1
            and handoffs_by_key[key][0][0] < resumes_by_key[key][0][0]
            for key in handoff_keys
        )
    )
    sorted_handoffs = {
        path: sorted(events)
        for path, events in handoffs_by_path.items()
    }
    sorted_resumes = {
        path: sorted(events)
        for path, events in resumes_by_path.items()
    }

    def manual_path_order_ok(
        unit: str,
        damage_event: tuple[int, object, object] | tuple[int, object, object, object],
    ) -> bool:
        handoffs = sorted_handoffs[(unit, "manual")]
        if (
            len(handoffs) != 2
            or len(native_moves_by_unit[unit]) != 1
            or len(hold_started_by_unit[unit]) != 1
            or len(hold_completed_by_unit[unit]) != 1
            or len(combat_direct_by_path[(unit, "manual")]) != 1
        ):
            return False
        for hold_index in (0, 1):
            hold_handoff = handoffs[hold_index]
            combat_handoff = handoffs[1 - hold_index]
            hold_key = (
                hold_handoff[1],
                hold_handoff[2],
                hold_handoff[3],
            )
            combat_key = (
                combat_handoff[1],
                combat_handoff[2],
                combat_handoff[3],
            )
            hold_resumes = resumes_by_key.get(hold_key, [])
            combat_resumes = resumes_by_key.get(combat_key, [])
            if (
                len(hold_resumes) == 1
                and len(combat_resumes) == 1
                and native_moves_by_unit[unit][0][0]
                < hold_started_by_unit[unit][0][0]
                < hold_completed_by_unit[unit][0][0]
                < hold_handoff[0]
                < hold_resumes[0][0]
                and commands_by_path[(unit, "manual")][0][0]
                < damage_event[0]
                < combat_direct_by_path[(unit, "manual")][0][0]
                < combat_handoff[0]
                < combat_resumes[0][0]
            ):
                return True
        return False

    order_ok = (
        selection_ok
        and ui_ready_ok
        and command_ok
        and native_move_ok
        and hunter_damage_ok
        and woodcutter_damage_ok
        and hold_ok
        and combat_direct_ok
        and suppression_ok
        and handoff_ok
        and resume_ok
        and pair_ok
        and commands_by_path[("hunter", "autonomous")][0][0]
        < hunter_by_mode["autonomous"][0][0]
        < combat_direct_by_path[("hunter", "autonomous")][0][0]
        < sorted_handoffs[("hunter", "autonomous")][0][0]
        < sorted_resumes[("hunter", "autonomous")][0][0]
        and selections_by_unit["hunter"][0][0]
        < ui_ready_by_unit["hunter"][0][0]
        < commands_by_path[("hunter", "manual")][0][0]
        < native_moves_by_unit["hunter"][0][0]
        and manual_path_order_ok(
            "hunter",
            hunter_by_mode["manual"][0],
        )
        and commands_by_path[("woodcutter", "autonomous")][0][0]
        < woodcutter_by_mode["autonomous"][0][0]
        < combat_direct_by_path[("woodcutter", "autonomous")][0][0]
        < sorted_handoffs[("woodcutter", "autonomous")][0][0]
        < sorted_resumes[("woodcutter", "autonomous")][0][0]
        and selections_by_unit["woodcutter"][0][0]
        < ui_ready_by_unit["woodcutter"][0][0]
        < commands_by_path[("woodcutter", "manual")][0][0]
        < native_moves_by_unit["woodcutter"][0][0]
        and manual_path_order_ok(
            "woodcutter",
            woodcutter_by_mode["manual"][0],
        )
        and all(
            any(
                any(
                    command[0] < suppression[0]
                    for command in command_events
                    if command[1] == unit
                )
                and any(
                    suppression[0] < handoff[0]
                    for handoff in handoff_restored_events
                    if handoff[1] == unit
                )
                for suppression in suppressions_by_unit[unit]
            )
            for unit in ("hunter", "woodcutter")
        )
    )
    return order_ok, evidence


def _atlas_layout(
    installed_files: dict[str, str],
) -> tuple[ValidationCheck, list[str]]:
    namespace: list[str] = []
    errors: list[str] = []
    groups_by_key: dict[str, str] = {}
    components_by_group: dict[str, set[str]] = {}
    for relative in installed_files:
        parts = relative.split("/")
        if len(parts) < 2 or [part.casefold() for part in parts[:2]] != [
            "override",
            "atlas",
        ]:
            continue
        namespace.append(relative)
        if parts[:2] != ["Override", "Atlas"] or len(parts) != 4 or not parts[2]:
            errors.append(f"noncanonical/nested atlas path: {relative}")
            continue
        group = parts[2]
        group_key = group.casefold()
        prior_group = groups_by_key.setdefault(group_key, group)
        if prior_group != group:
            errors.append(f"case-colliding atlas group: {prior_group!r}/{group!r}")
        component = parts[3]
        if component not in {"atlas.json", "atlas.png", "atlas_m.png"}:
            errors.append(f"unexpected atlas component: {relative}")
        components_by_group.setdefault(group_key, set()).add(component)

    for group_key, components in components_by_group.items():
        if not {"atlas.json", "atlas.png"} <= components:
            errors.append(
                f"orphan atlas group {groups_by_key[group_key]!r}: "
                f"components={sorted(components)!r}"
            )
        if not components <= {"atlas.json", "atlas.png", "atlas_m.png"}:
            errors.append(
                f"invalid atlas shape {groups_by_key[group_key]!r}: "
                f"components={sorted(components)!r}"
            )

    groups = sorted(groups_by_key.values(), key=str.casefold)
    return _check(
        "runtime.atlas_layout",
        not errors,
        json.dumps(
            {"namespace_count": len(namespace), "groups": groups, "errors": errors},
            sort_keys=True,
        ),
    ), groups


def _png_contract(
    path: Path,
    entry: dict[str, object] | None,
) -> tuple[bool, tuple[int, int] | None, str]:
    errors: list[str] = []
    size: tuple[int, int] | None = None
    try:
        with path.open("rb") as stream:
            signature = stream.read(8)
        if signature != b"\x89PNG\r\n\x1a\n":
            errors.append("PNG signature is not exact")
        with Image.open(path) as image:
            image.load()
            size = image.size
            if image.format != "PNG":
                errors.append(f"format={image.format!r}")
            if image.mode != "RGBA":
                errors.append(f"mode={image.mode!r}")
    except (
        OSError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
        ValueError,
    ) as exc:
        errors.append(f"cannot decode PNG: {exc}")
    if entry is None:
        errors.append("build-manifest output entry is missing")
    elif size is not None:
        if (
            type(entry.get("width")) is not int
            or type(entry.get("height")) is not int
            or (entry.get("width"), entry.get("height")) != size
        ):
            errors.append(
                f"manifest geometry={(entry.get('width'), entry.get('height'))!r} "
                f"actual={size!r}"
            )
    return not errors, size, json.dumps({"errors": errors}, sort_keys=True)


def _installed_atlas_contract(
    destination: Path,
    group: str,
    installed_files: dict[str, str],
    output_by_path: dict[str, dict[str, object]],
) -> tuple[list[ValidationCheck], int | None, str, int | None]:
    checks: list[ValidationCheck] = []
    base = f"Override/Atlas/{group}"
    descriptor_relative = f"{base}/atlas.json"
    main_relative = f"{base}/atlas.png"
    mask_relative = f"{base}/atlas_m.png"
    main_present = main_relative in installed_files
    mask_present = mask_relative in installed_files
    descriptor_present = descriptor_relative in installed_files
    loader_contract = LOADER_139_GROUPS.get(group)
    loader_ok = loader_contract is not None
    checks.append(
        _check(
            f"runtime.atlas_loader_group.{group}",
            loader_ok,
            group,
        )
    )
    dash_format, mask_policy, material_compatible = (
        loader_contract if loader_contract is not None else (False, "invalid", False)
    )
    mask_policy_ok = (
        mask_present if mask_policy == "required" else not mask_present
    )
    checks.append(
        _check(
            f"runtime.atlas_mask_policy.{group}",
            loader_ok and descriptor_present and main_present and mask_policy_ok,
            f"policy={mask_policy} present={mask_present}",
        )
    )

    main_ok = False
    main_size: tuple[int, int] | None = None
    main_detail = "main PNG is missing"
    if main_present:
        main_ok, main_size, main_detail = _png_contract(
            destination / main_relative,
            output_by_path.get(main_relative),
        )
    power_of_two_ok = (
        main_size is not None
        and all(value > 0 and value & (value - 1) == 0 and value <= 8192 for value in main_size)
    )
    checks.append(
        _check(
            f"runtime.atlas_png.{group}",
            main_ok and power_of_two_ok,
            f"size={main_size!r} detail={main_detail}",
        )
    )

    mask_ok = not mask_present
    mask_size: tuple[int, int] | None = None
    mask_detail = "absent"
    if mask_present:
        decoded_mask_ok, mask_size, mask_detail = _png_contract(
            destination / mask_relative,
            output_by_path.get(mask_relative),
        )
        mask_ok = decoded_mask_ok and mask_size == main_size
    checks.append(
        _check(
            f"runtime.atlas_mask_png.{group}",
            mask_ok,
            f"main={main_size!r} mask={mask_size!r} detail={mask_detail}",
        )
    )

    descriptor, descriptor_detail = _read_json_object(destination / descriptor_relative)
    frames_value = descriptor.get("frames") if descriptor is not None else None
    frames = frames_value if isinstance(frames_value, list) else []
    names: list[str] = []
    slots: list[tuple[int, bool]] = []
    rects: list[tuple[int, int, int, int]] = []
    frames_ok = descriptor is not None and isinstance(frames_value, list) and bool(frames)
    for frame in frames:
        if not isinstance(frame, dict) or main_size is None:
            frames_ok = False
            continue
        name = frame.get("name")
        parsed_name = (
            parse_loader_frame_name(name, group, dash_format)
            if isinstance(name, str)
            else None
        )
        rect = frame.get("rect")
        rect_values = (
            [rect.get(field) for field in ("x", "y", "w", "h")]
            if isinstance(rect, dict)
            else []
        )
        integral_rect = len(rect_values) == 4 and all(
            type(value) is int for value in rect_values
        )
        pivot = frame.get("pivot")
        try:
            ppu = frame.get("pixelsPerUnit", descriptor.get("pixelsPerUnit"))
            finite_metadata = (
                isinstance(pivot, dict)
                and isfinite(float(pivot.get("x")))
                and isfinite(float(pivot.get("y")))
                and isfinite(float(ppu))
                and float(ppu) > 0
            )
        except (TypeError, ValueError, OverflowError):
            finite_metadata = False
        if parsed_name is None or not integral_rect or not finite_metadata:
            frames_ok = False
            continue
        x, y, width, height = rect_values
        inside = (
            x >= 0
            and y >= 0
            and width > 0
            and height > 0
            and x + width <= main_size[0]
            and y + height <= main_size[1]
        )
        frames_ok = frames_ok and inside
        names.append(name)
        slots.append((parsed_name.index, parsed_name.is_alt))
        rects.append((x, y, width, height))
    frames_ok = (
        frames_ok
        and len(names) == len(frames)
        and len(names) == len(set(names))
        and len(slots) == len(set(slots))
    )
    checks.append(
        _check(
            f"runtime.atlas_descriptor.{group}",
            frames_ok,
            f"json={descriptor_detail!r} valid={len(names)} total={len(frames)}",
        )
    )

    ordered_names = [
        name
        for _, name in sorted(
            zip(slots, names, strict=True),
            key=lambda item: (item[0][0], item[0][1], item[1]),
        )
    ] if len(slots) == len(names) else []
    names_digest = hashlib.sha256(
        "".join(name + "\n" for name in ordered_names).encode("utf-8")
    ).hexdigest()
    max_index = max((slot[0] for slot in slots), default=-1)
    main_count = sum(not slot[1] for slot in slots)
    alt_count = len(slots) - main_count
    unique_rects = set(rects)
    descriptor_entry = output_by_path.get(descriptor_relative)
    metadata_value = (
        descriptor_entry.get("metadata") if descriptor_entry is not None else None
    )
    metadata = metadata_value if isinstance(metadata_value, dict) else {}
    roundtrip = metadata.get("roundtrip")
    metadata_ok = (
        frames_ok
        and main_size is not None
        and metadata.get("kind") == "shcdese_gm_atlas_1_39"
        and metadata.get("gm_file_name") == group
        and metadata.get("dash_format") is dash_format
        and metadata.get("mask_policy") == mask_policy
        and type(metadata.get("frame_count")) is int
        and metadata.get("frame_count") == len(names)
        and type(metadata.get("main_count")) is int
        and metadata.get("main_count") == main_count
        and type(metadata.get("alt_count")) is int
        and metadata.get("alt_count") == alt_count
        and type(metadata.get("array_size")) is int
        and metadata.get("array_size") == max_index + 1
        and metadata.get("names_sha256") == names_digest
        and metadata.get("unique_region_count") == len(unique_rects)
        and metadata.get("atlas_width") == main_size[0]
        and metadata.get("atlas_height") == main_size[1]
        and metadata.get("loader_material_compatible") is material_compatible
        and isinstance(roundtrip, dict)
        and roundtrip.get("verified") is True
        and roundtrip.get("frames_checked") == len(names)
    )
    padding = metadata.get("padding")
    padding_ok = type(padding) is int and padding >= 1 and main_size is not None
    if padding_ok and main_size is not None:
        for x, y, width, height in unique_rects:
            if (
                x < padding
                or y < padding
                or x + width + padding > main_size[0]
                or y + height + padding > main_size[1]
            ):
                padding_ok = False
                break
    if padding_ok:
        regions = sorted(unique_rects)
        for index, (lx, ly, lw, lh) in enumerate(regions):
            for rx, ry, rw, rh in regions[index + 1 :]:
                if not (
                    lx + lw + padding <= rx - padding
                    or rx + rw + padding <= lx - padding
                    or ly + lh + padding <= ry - padding
                    or ry + rh + padding <= ly - padding
                ):
                    padding_ok = False
                    break
            if not padding_ok:
                break
    checks.append(
        _check(
            f"runtime.atlas_manifest_metadata.{group}",
            metadata_ok and padding_ok,
            json.dumps(metadata, sort_keys=True),
        )
    )
    expected_frames = len(names) if frames_ok else None
    expected_array_size = max_index + 1 if frames_ok else None
    return (
        checks,
        expected_frames,
        "yes" if mask_present else "no",
        expected_array_size,
    )


def _asset_key(value: str) -> str:
    """Mirror SHCDE-SE's slash-normalized, case-insensitive file index."""

    return value.replace("\\", "/").casefold()


def _root_key(value: str | Path) -> str:
    return str(Path(value).resolve()).replace("\\", "/").casefold()


def _is_link_or_reparse(path: Path) -> bool:
    """Reject indirection inside the immutable installed snapshot.

    ``Path.is_symlink`` covers POSIX links and Windows symbolic links. Windows
    directory junctions and other name-surrogate reparse points also need the
    file-attribute check because they can otherwise escape the install root
    while a recursive verifier is walking it.
    """

    try:
        if path.is_symlink():
            return True
        is_junction = getattr(path, "is_junction", None)
        if callable(is_junction) and is_junction():
            return True
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError:
        return True
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _installed_snapshot_integrity(
    destination_path: Path,
    raw_expected_files: object,
) -> tuple[bool, str]:
    """Verify the exact installed file set and hashes without following links."""

    schema_errors: list[str] = []
    expected_files: dict[str, str] = {}
    if not isinstance(raw_expected_files, dict) or not raw_expected_files:
        schema_errors.append("files must be a non-empty object")
    else:
        folded_paths: set[str] = set()
        for raw_relative, raw_digest in raw_expected_files.items():
            if not isinstance(raw_relative, str) or not raw_relative:
                schema_errors.append(f"invalid relative path: {raw_relative!r}")
                continue
            normalized = Path(raw_relative.replace("/", os.sep))
            normalized_posix = normalized.as_posix()
            path_ok = (
                "\\" not in raw_relative
                and not normalized.is_absolute()
                and normalized_posix == raw_relative
                and all(part not in {"", ".", ".."} for part in normalized.parts)
            )
            if not path_ok:
                schema_errors.append(f"non-canonical relative path: {raw_relative!r}")
                continue
            folded = raw_relative.casefold()
            if folded in folded_paths:
                schema_errors.append(
                    f"case-insensitive duplicate path: {raw_relative!r}"
                )
                continue
            folded_paths.add(folded)
            if (
                not isinstance(raw_digest, str)
                or re.fullmatch(r"[0-9a-f]{64}", raw_digest) is None
            ):
                schema_errors.append(f"invalid SHA-256 for {raw_relative!r}")
                continue
            expected_files[raw_relative] = raw_digest

    destination_absolute = destination_path.absolute()
    links: list[str] = []
    unsupported: list[str] = []
    actual_paths: dict[str, Path] = {}
    scan_errors: list[str] = []
    if (
        not destination_path.is_absolute()
        or _is_link_or_reparse(destination_absolute)
        or not destination_absolute.is_dir()
    ):
        scan_errors.append("destination is missing, relative, or link/reparse-backed")
    else:
        pending = [destination_absolute]
        while pending:
            directory = pending.pop()
            try:
                with os.scandir(directory) as entries:
                    ordered_entries = sorted(entries, key=lambda item: item.name.casefold())
            except OSError as exc:
                scan_errors.append(f"cannot scan {directory}: {exc}")
                continue
            for entry in ordered_entries:
                path = Path(entry.path)
                relative = path.relative_to(destination_absolute).as_posix()
                if _is_link_or_reparse(path):
                    links.append(relative)
                    continue
                try:
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(path)
                    elif entry.is_file(follow_symlinks=False):
                        actual_paths[relative] = path
                    else:
                        unsupported.append(relative)
                except OSError as exc:
                    scan_errors.append(f"cannot inspect {relative}: {exc}")

    expected_paths = set(expected_files)
    actual_names = set(actual_paths)
    missing = sorted(expected_paths - actual_names)
    extra = sorted(actual_names - expected_paths)
    mismatched: list[str] = []
    if not schema_errors and not links and not unsupported and not scan_errors:
        for relative in sorted(expected_paths & actual_names):
            try:
                if sha256_file(actual_paths[relative]) != expected_files[relative]:
                    mismatched.append(relative)
            except OSError as exc:
                scan_errors.append(f"cannot hash {relative}: {exc}")

    ok = not any(
        (schema_errors, links, unsupported, scan_errors, missing, extra, mismatched)
    )
    detail = json.dumps(
        {
            "expected": len(expected_paths),
            "actual": len(actual_names),
            "schema_errors": schema_errors,
            "links_or_reparse_points": sorted(links),
            "unsupported_entries": sorted(unsupported),
            "scan_errors": scan_errors,
            "missing": missing,
            "extra": extra,
            "hash_mismatches": mismatched,
        },
        sort_keys=True,
    )
    return ok, detail


@dataclass
class _ProviderSession:
    guid: str
    root: str
    line_number: int
    assets: dict[str, str] = field(default_factory=dict)
    asset_lines: dict[str, int] = field(default_factory=dict)

    @property
    def guid_key(self) -> str:
        return self.guid.casefold()

    @property
    def root_key(self) -> str:
        return _root_key(self.root)

    @property
    def label(self) -> str:
        return f"{self.guid}@{self.root}"


@dataclass(frozen=True)
class _AtlasRegistration:
    group: str
    group_key: str
    gm_enum: str
    line_number: int


@dataclass(frozen=True)
class _AtlasDiscovery:
    group: str
    group_key: str
    trigger_root: str
    trigger_session: int | None
    line_number: int
    component_owners: dict[str, int | None]
    paired_registration: int | None


@dataclass(frozen=True)
class _ProviderTrace:
    sessions: tuple[_ProviderSession, ...]
    final_file_index: dict[str, int]
    registrations: tuple[_AtlasRegistration, ...]
    discoveries: tuple[_AtlasDiscovery, ...]
    errors: tuple[str, ...]


def _atlas_component_keys(group: str) -> dict[str, str]:
    prefix = f"Atlas/{group}/"
    return {
        "json": _asset_key(prefix + "atlas.json"),
        "main": _asset_key(prefix + "atlas.png"),
        "mask": _asset_key(prefix + "atlas_m.png"),
    }


def _provider_trace(lines: list[str]) -> _ProviderTrace:
    """Reconstruct the pinned loader's global Last-Write-Wins index.

    SHCDE-SE 1.39 calls ``DiscoverAtlasOverrides`` after every provider, but
    that method scans the complete global file index. Its logged ``from`` path
    is only the provider that triggered the rescan, not the owner of an atlas.
    Capturing component owners at each discovery preserves that distinction.
    """

    sessions: list[_ProviderSession] = []
    current_session: int | None = None
    file_index: dict[str, int] = {}
    registrations: list[_AtlasRegistration] = []
    discoveries: list[_AtlasDiscovery] = []
    errors: list[str] = []
    pending_registration: tuple[str, int, int] | None = None

    for line_number, line in enumerate(lines, start=1):
        provider_match = _PROVIDER_RE.fullmatch(line)
        if provider_match:
            pending_registration = None
            sessions.append(
                _ProviderSession(
                    guid=provider_match.group(1),
                    root=provider_match.group(2),
                    line_number=line_number,
                )
            )
            current_session = len(sessions) - 1
            continue
        if line.startswith(_PROVIDER_EVENT_PREFIX):
            pending_registration = None
            current_session = None
            errors.append(f"line {line_number}: malformed provider session")
            continue
        index_match = _INDEX_RE.fullmatch(line)
        if current_session is not None and index_match:
            pending_registration = None
            display_path = index_match.group(1).replace("\\", "/")
            key = _asset_key(display_path)
            sessions[current_session].assets[key] = display_path
            sessions[current_session].asset_lines[key] = line_number
            file_index[key] = current_session
            continue
        if line.startswith(_INDEX_EVENT_PREFIX):
            pending_registration = None
            errors.append(
                f"line {line_number}: provider index without an exact session"
            )
            continue

        register_match = _ATLAS_REGISTER_RE.fullmatch(line)
        if register_match:
            group = register_match.group(1)
            registration = _AtlasRegistration(
                group=group,
                group_key=group.casefold(),
                gm_enum=register_match.group(2),
                line_number=line_number,
            )
            registrations.append(registration)
            pending_registration = (
                registration.group_key,
                len(registrations) - 1,
                line_number,
            )
            continue

        discovery_match = _ATLAS_DISCOVERY_RE.fullmatch(line)
        if discovery_match:
            group = discovery_match.group(1)
            group_key = group.casefold()
            paired_registration = None
            if (
                pending_registration is not None
                and pending_registration[0] == group_key
                and pending_registration[2] == line_number - 1
            ):
                paired_registration = pending_registration[1]
            component_owners = {
                component: file_index.get(key)
                for component, key in _atlas_component_keys(group).items()
            }
            discoveries.append(
                _AtlasDiscovery(
                    group=group,
                    group_key=group_key,
                    trigger_root=discovery_match.group(2),
                    trigger_session=current_session,
                    line_number=line_number,
                    component_owners=component_owners,
                    paired_registration=paired_registration,
                )
            )
            pending_registration = None
            continue

        pending_registration = None

    return _ProviderTrace(
        sessions=tuple(sessions),
        final_file_index=dict(file_index),
        registrations=tuple(registrations),
        discoveries=tuple(discoveries),
        errors=tuple(errors),
    )


def _runtime_contract_events(
    lines: list[str],
) -> tuple[list[str], list[str], dict[str, list[int]]]:
    events: list[str] = []
    severity_errors: list[str] = []
    event_lines: dict[str, list[int]] = {}
    for line_number, line in enumerate(lines, start=1):
        any_match = _RUNTIME_ANY_EVENT_RE.fullmatch(line)
        if any_match is None:
            continue
        event = any_match.group("event")
        events.append(event)
        event_lines.setdefault(event, []).append(line_number)
        if (
            _recognized_runtime_event(event)
            and any_match.group("level").casefold()
            != _runtime_event_expected_level(event)
        ):
            severity_errors.append(line)
    return events, severity_errors, event_lines


@dataclass(frozen=True)
class _AssetStreamRuntimeGroupEvent:
    line: int
    status: str
    group: str
    epoch: int
    reason: str
    resident_charge_bytes: int | None = None
    predicted_load_peak_bytes: int | None = None
    gm_resident_bytes: int | None = None
    ui_resident_bytes: int | None = None
    audio_stream_bytes: int | None = None
    process_private_bytes: int | None = None
    available_commit_bytes: int | None = None
    available_physical_bytes: int | None = None
    memory_status: str | None = None

    @property
    def terminal(self) -> bool:
        return self.status in {"loaded", "fallback"}


@dataclass(frozen=True)
class _AssetStreamRuntimeSummary:
    line: int
    epoch: int
    requested: int
    loaded: int
    fallback: int
    budget_denied: int
    memory_samples: int
    max_private_bytes: int
    min_available_commit_bytes: int
    min_available_physical_bytes: int
    max_gm_resident_bytes: int
    max_ui_resident_bytes: int
    max_audio_stream_bytes: int
    page_mask_blocked: int | None = None
    page_mask_failures: int | None = None
    mask_route_events: int | None = None
    mask_route_corrections: int | None = None
    mask_route_postfix_mismatches: int | None = None


@dataclass(frozen=True)
class _RuntimeUiTextureExpectation:
    paths: frozenset[str]
    external_paths: frozenset[str]
    profile_paths: frozenset[str]
    resident_charge_bytes: int | None


_EMPTY_UI_TEXTURE_EXPECTATION = _RuntimeUiTextureExpectation(
    paths=frozenset(),
    external_paths=frozenset(),
    profile_paths=frozenset(),
    resident_charge_bytes=None,
)


def _asset_stream_summary_maximum(values: list[int]) -> int:
    present = [value for value in values if value >= 0]
    if not present:
        return -1
    maximum = max(present)
    return maximum if maximum > 0 else -1


def _asset_stream_summary_minimum(values: list[int]) -> int:
    present = [value for value in values if value >= 0]
    return min(present) if present else -1


def _asset_stream_runtime_identity(
    index: dict[str, object],
    index_metadata: dict[str, object],
) -> tuple[str, str]:
    """Bind the runtime event identity to the parsed index and OutputRecord."""

    schema = index.get("schema")
    if schema == ASSET_STREAM_INDEX_SCHEMA:
        backend = ASSET_STREAM_BACKEND_KIND
        policy = ASSET_STREAM_RESOURCE_POLICY_KIND
    elif schema == ASSET_STREAM_BC7_INDEX_SCHEMA:
        if index.get("backend_kind") != ASSET_STREAM_BC7_BACKEND_KIND:
            raise ValueError("BC7 index backend identity changed")
        backend = ASSET_STREAM_BC7_BACKEND_KIND
        policy = ASSET_STREAM_BC7_RESOURCE_POLICY_KIND
    else:
        raise ValueError("asset-stream index schema is not approved")
    if (
        index_metadata.get("kind") != backend
        or index_metadata.get("schema") != schema
    ):
        raise ValueError("asset-stream OutputRecord identity disagrees with index")
    return backend, policy


def _runtime_ui_texture_output_contract(
    root: Path,
    output_by_path: dict[str, dict[str, object]],
    runtime_metadata: dict[str, object],
) -> tuple[ValidationCheck, _RuntimeUiTextureExpectation]:
    """Bind runtime acceptance to the exclusive 114-entry UI BC7 payload."""

    enabled = runtime_metadata.get("ui_texture_streaming_enabled") is True
    expected_digest = runtime_metadata.get("ui_texture_manifest_sha256")
    legacy_declared = any(
        relative.casefold() == UI_TEXTURE_V1_MANIFEST_PATH.casefold()
        for relative in output_by_path
    )
    legacy_path = root.joinpath(
        *PurePosixPath(UI_TEXTURE_V1_MANIFEST_PATH).parts
    )
    legacy_present = legacy_declared or os.path.lexists(legacy_path)
    v2_declared = UI_TEXTURE_V2_MANIFEST_PATH in output_by_path
    v2_path = root.joinpath(*PurePosixPath(UI_TEXTURE_V2_MANIFEST_PATH).parts)
    declared_bundles = {
        relative
        for relative, record in output_by_path.items()
        if relative.casefold().startswith(UI_TEXTURE_BUNDLE_PREFIX.casefold())
        or record.get("category") == "ui_texture_asset_bundle"
    }
    bundle_root = root.joinpath(
        *PurePosixPath(UI_TEXTURE_BUNDLE_PREFIX.rstrip("/")).parts
    )

    if not enabled:
        payload_present = (
            legacy_present
            or v2_declared
            or os.path.lexists(v2_path)
            or bool(declared_bundles)
            or os.path.lexists(bundle_root)
        )
        check = _check(
            "runtime.ui_texture_stream_output_contract",
            expected_digest in {None, ""} and not payload_present,
            "enabled=false "
            f"legacy={legacy_present} v2={v2_declared or os.path.lexists(v2_path)} "
            f"bundles={len(declared_bundles)} digest={expected_digest!r}",
        )
        return check, _EMPTY_UI_TEXTURE_EXPECTATION

    active_pngs = _active_ui_png_paths(root, output_by_path)
    try:
        if (
            not isinstance(expected_digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", expected_digest) is None
        ):
            raise ValueError("enabled UI v2 runtime digest is invalid")
        if legacy_present:
            raise ValueError("removed Runtime/ui-textures-v1.tsv is still active")
        if active_pngs:
            raise ValueError(f"UI v2 backend forbids active GUI PNGs: {active_pngs}")
        if not v2_declared:
            raise ValueError("Runtime/ui-textures-v2.tsv is not manifest-owned")

        project_root = Path(__file__).resolve().parents[2]
        source_manifest = load_ui_texture_source_manifest(
            project_root / UI_TEXTURE_SOURCE_CONFIG_PATH
        )
        quality_policy = load_ui_quality_policy(
            project_root / UI_TEXTURE_QUALITY_POLICY_PATH
        )
        editor_source = project_root / UI_TEXTURE_EDITOR_SOURCE_PATH
        if not editor_source.is_file() or editor_source.is_symlink():
            raise ValueError("canonical UI v2 editor source changed")

        external_paths = frozenset(
            entry.noesis_path
            for entry in source_manifest.entries
            if entry.source_kind == "private_work_file"
        )
        profile_paths = frozenset(
            entry.noesis_path
            for entry in source_manifest.entries
            if entry.source_kind == "profile_output"
        )
        source_paths = external_paths | profile_paths
        if (
            UI_TEXTURE_EXPECTED_ENTRY_COUNT != _UI_TEXTURE_RUNTIME_ENTRY_COUNT
            or len(source_manifest.entries) != _UI_TEXTURE_RUNTIME_ENTRY_COUNT
            or len(external_paths) != _UI_TEXTURE_EXTERNAL_ENTRY_COUNT
            or len(profile_paths) != _UI_TEXTURE_PROFILE_ENTRY_COUNT
            or len(source_paths) != _UI_TEXTURE_RUNTIME_ENTRY_COUNT
        ):
            raise ValueError(
                f"canonical UI v2 ownership is not {_UI_TEXTURE_EXTERNAL_ENTRY_COUNT} external plus "
                f"{_UI_TEXTURE_PROFILE_ENTRY_COUNT} profile paths"
            )

        parsed = parse_ui_texture_runtime_manifest_v2(
            root,
            expected_source_manifest_sha256=source_manifest.sha256,
            expected_quality_policy_sha256=quality_policy.sha256,
            expected_editor_source_sha256=sha256_file(editor_source),
            expected_entry_count=_UI_TEXTURE_RUNTIME_ENTRY_COUNT,
            max_resident_bytes=UI_TEXTURE_MAX_RESIDENT_BYTES,
        )
        parsed_paths = frozenset(entry.noesis_path for entry in parsed.entries)
        if (
            parsed.entry_count != _UI_TEXTURE_RUNTIME_ENTRY_COUNT
            or len(parsed.entries) != _UI_TEXTURE_RUNTIME_ENTRY_COUNT
            or len(parsed.bundles) != _UI_TEXTURE_RUNTIME_ENTRY_COUNT
            or parsed_paths != source_paths
            or parsed.source_entry_set_sha256
            != source_manifest.entry_set_sha256
            or parsed.sha256 != expected_digest
        ):
            raise ValueError("UI v2 manifest ownership or runtime binding changed")
        record_errors = _ui_texture_v2_output_record_errors(
            parsed,
            output_by_path,
        )
        if record_errors:
            raise ValueError("; ".join(record_errors))

        expectation = _RuntimeUiTextureExpectation(
            paths=parsed_paths,
            external_paths=external_paths,
            profile_paths=profile_paths,
            resident_charge_bytes=parsed.declared_resident_charge_bytes,
        )
        check = _check(
            "runtime.ui_texture_stream_output_contract",
            True,
            f"backend={_UI_TEXTURE_RUNTIME_BACKEND} entries={len(parsed_paths)} "
            f"external={len(external_paths)} profile={len(profile_paths)} "
            f"resident_charge_bytes={parsed.declared_resident_charge_bytes} "
            f"sha256={parsed.sha256}",
        )
        return check, expectation
    except (
        KeyError,
        OSError,
        RuntimeBuildError,
        TypeError,
        UiAssetBundleError,
        ValueError,
    ) as exc:
        return (
            _check(
                "runtime.ui_texture_stream_output_contract",
                False,
                str(exc),
            ),
            _EMPTY_UI_TEXTURE_EXPECTATION,
        )


def _streaming_runtime_event_checks(
    runtime_event_lines: dict[str, list[int]],
    *,
    asset_stream_enabled: bool,
    expected_asset_stream_backend_kind: str | None,
    expected_asset_stream_resource_policy_kind: str | None,
    stream_groups: set[str],
    ui_texture_streaming_enabled: bool,
    expected_ui_paths: set[str],
    expected_ui_resident_charge_bytes: int | None,
    pcm_streaming_enabled: bool,
    expected_audio_files: set[str],
    stream_group_resources: dict[str, tuple[int, int]] | None = None,
) -> list[ValidationCheck]:
    """Validate all repeatable lazy-lane events against shipped contracts."""

    checks: list[ValidationCheck] = []

    initialized: list[tuple[int, int, str, str]] = []
    asset_states: list[tuple[int, str, str]] = []
    scene_resets: list[tuple[int, int, str]] = []
    baselines: list[tuple[int, int]] = []
    baseline_vanilla: list[tuple[int, str, str]] = []
    group_events: list[_AssetStreamRuntimeGroupEvent] = []
    asset_summaries: list[_AssetStreamRuntimeSummary] = []
    plain_asset_inactive = runtime_event_lines.get(
        _RUNTIME_ASSET_STREAM_INACTIVE, []
    )
    for event, line_numbers in runtime_event_lines.items():
        match = _RUNTIME_ASSET_STREAM_INITIALIZED_RE.fullmatch(event)
        if match is not None:
            initialized.extend(
                (
                    line,
                    int(match.group(1)),
                    match.group(2),
                    match.group(3),
                )
                for line in line_numbers
            )
            continue
        match = _RUNTIME_ASSET_STREAM_STATE_RE.fullmatch(event)
        if match is not None:
            asset_states.extend(
                (line, match.group(1), match.group(2)) for line in line_numbers
            )
            continue
        match = _RUNTIME_ASSET_STREAM_SCENE_RESET_RE.fullmatch(event)
        if match is not None:
            scene_resets.extend(
                (line, int(match.group(1)), match.group(2))
                for line in line_numbers
            )
            continue
        match = _RUNTIME_ASSET_STREAM_BASELINE_CAPTURED_RE.fullmatch(event)
        if match is not None:
            baselines.extend(
                (line, int(match.group(1))) for line in line_numbers
            )
            continue
        match = _RUNTIME_ASSET_STREAM_BASELINE_VANILLA_RE.fullmatch(event)
        if match is not None:
            baseline_vanilla.extend(
                (line, match.group(1), match.group(2)) for line in line_numbers
            )
            continue
        match = _RUNTIME_ASSET_STREAM_PENDING_RE.fullmatch(event)
        if match is not None:
            group_events.extend(
                _AssetStreamRuntimeGroupEvent(
                    line=line,
                    status="pending",
                    group=match.group(1),
                    epoch=int(match.group(2)),
                    reason=match.group(3),
                )
                for line in line_numbers
            )
            continue
        match = _RUNTIME_ASSET_STREAM_TERMINAL_RE.fullmatch(event)
        if match is not None:
            group_events.extend(
                _AssetStreamRuntimeGroupEvent(
                    line=line,
                    status=(
                        "loaded"
                        if match.group(1) == "group_loaded"
                        else "fallback"
                    ),
                    group=match.group(2),
                    epoch=int(match.group(3)),
                    reason=match.group(4),
                    resident_charge_bytes=int(match.group(5)),
                    predicted_load_peak_bytes=int(match.group(6)),
                    gm_resident_bytes=int(match.group(7)),
                    ui_resident_bytes=int(match.group(8)),
                    audio_stream_bytes=int(match.group(9)),
                    process_private_bytes=int(match.group(10)),
                    available_commit_bytes=int(match.group(11)),
                    available_physical_bytes=int(match.group(12)),
                    memory_status=match.group(13),
                )
                for line in line_numbers
            )
            continue
        match = _RUNTIME_ASSET_STREAM_SUMMARY_RE.fullmatch(event)
        if match is not None:
            asset_summaries.extend(
                _AssetStreamRuntimeSummary(
                    line=line,
                    epoch=int(match.group("epoch")),
                    requested=int(match.group("requested")),
                    loaded=int(match.group("loaded")),
                    fallback=int(match.group("fallback")),
                    budget_denied=int(match.group("budget_denied")),
                    memory_samples=int(match.group("memory_samples")),
                    max_private_bytes=int(match.group("max_private_bytes")),
                    min_available_commit_bytes=int(
                        match.group("min_available_commit_bytes")
                    ),
                    min_available_physical_bytes=int(
                        match.group("min_available_physical_bytes")
                    ),
                    max_gm_resident_bytes=int(
                        match.group("max_gm_resident_bytes")
                    ),
                    max_ui_resident_bytes=int(
                        match.group("max_ui_resident_bytes")
                    ),
                    max_audio_stream_bytes=int(
                        match.group("max_audio_stream_bytes")
                    ),
                    page_mask_blocked=(
                        int(match.group("page_mask_blocked"))
                        if match.group("page_mask_blocked") is not None
                        else None
                    ),
                    page_mask_failures=(
                        int(match.group("page_mask_failures"))
                        if match.group("page_mask_failures") is not None
                        else None
                    ),
                    mask_route_events=(
                        int(match.group("mask_route_events"))
                        if match.group("mask_route_events") is not None
                        else None
                    ),
                    mask_route_corrections=(
                        int(match.group("mask_route_corrections"))
                        if match.group("mask_route_corrections") is not None
                        else None
                    ),
                    mask_route_postfix_mismatches=(
                        int(match.group("mask_route_postfix_mismatches"))
                        if match.group("mask_route_postfix_mismatches") is not None
                        else None
                    ),
                )
                for line in line_numbers
            )

    asset_dynamic_count = (
        len(initialized)
        + len(asset_states)
        + len(scene_resets)
        + len(baselines)
        + len(baseline_vanilla)
        + len(group_events)
        + len(asset_summaries)
    )
    runtime_initialized_lines = runtime_event_lines.get(RUNTIME_INITIALIZED, [])
    if asset_stream_enabled:
        init_ok = (
            len(initialized) == 1
            and initialized[0][1] == len(stream_groups)
            and initialized[0][2] == expected_asset_stream_backend_kind
            and initialized[0][3] == expected_asset_stream_resource_policy_kind
            and not plain_asset_inactive
            and not [state for state in asset_states if state[1] == "vanilla"]
            and [state[2] for state in asset_states if state[1] == "inactive"]
            == ["application_quit"]
            and len([state for state in asset_states if state[1] == "inactive"])
            == 1
            and all(
                summary.line
                < [state for state in asset_states if state[1] == "inactive"][0][0]
                for summary in asset_summaries
            )
        )
        baseline_ok = (
            len(baselines) == 1
            and baselines[0][1] == len(stream_groups)
            and not baseline_vanilla
            and len(initialized) == 1
            and initialized[0][0] < baselines[0][0]
            and len(runtime_initialized_lines) == 1
            and initialized[0][0] < runtime_initialized_lines[0]
            < baselines[0][0]
        )
        pending = [event for event in group_events if not event.terminal]
        terminals = [event for event in group_events if event.terminal]
        pending_keys = [(event.group, event.epoch) for event in pending]
        terminal_keys = [(event.group, event.epoch) for event in terminals]
        reason_ok = all(
            (
                event.status == "pending"
                and event.reason
                in {"queued", "load_in_progress", "release_pending", "vanilla"}
            )
            or (event.status == "loaded" and event.reason == "loaded")
            or (
                event.status == "fallback"
                and event.reason
                in {
                    "queued",
                    "baseline_unavailable",
                    "load_in_progress",
                    "release_pending",
                    "budget_denied",
                    "load_failed",
                    "unknown_group",
                    "shutdown",
                    "no_map",
                    "vanilla",
                }
            )
            for event in group_events
        )
        telemetry_ok = all(
            event.resident_charge_bytes is not None
            and event.predicted_load_peak_bytes is not None
            and event.gm_resident_bytes is not None
            and event.ui_resident_bytes is not None
            and event.audio_stream_bytes is not None
            and event.process_private_bytes is not None
            and event.available_commit_bytes is not None
            and event.available_physical_bytes is not None
            and event.memory_status is not None
            and event.predicted_load_peak_bytes >= event.resident_charge_bytes
            and all(
                value <= 2**63 - 1
                for value in (
                    event.resident_charge_bytes,
                    event.predicted_load_peak_bytes,
                    event.gm_resident_bytes,
                    event.ui_resident_bytes,
                    event.audio_stream_bytes,
                    event.process_private_bytes,
                    event.available_commit_bytes,
                    event.available_physical_bytes,
                )
            )
            and (
                (
                    event.memory_status == "complete"
                    and event.process_private_bytes > 0
                    and min(
                        event.ui_resident_bytes,
                        event.audio_stream_bytes,
                        event.available_commit_bytes,
                        event.available_physical_bytes,
                    )
                    >= 0
                )
                or (
                    event.memory_status == "unavailable"
                    and min(
                        event.ui_resident_bytes,
                        event.audio_stream_bytes,
                        event.process_private_bytes,
                        event.available_commit_bytes,
                        event.available_physical_bytes,
                    )
                    == -1
                )
            )
            and (
                stream_group_resources is None
                or stream_group_resources.get(event.group)
                == (
                    event.resident_charge_bytes,
                    event.predicted_load_peak_bytes,
                )
            )
            and (
                event.status != "loaded"
                or event.gm_resident_bytes >= event.resident_charge_bytes
            )
            for event in terminals
        )
        terminal_shape_ok = (
            bool(terminals)
            and any(event.status == "loaded" for event in terminals)
            and len(pending_keys) == len(set(pending_keys))
            and len(terminal_keys) == len(set(terminal_keys))
            and set(pending_keys) <= set(terminal_keys)
            and all(
                next(
                    terminal.line
                    for terminal in terminals
                    if (terminal.group, terminal.epoch)
                    == (pending_event.group, pending_event.epoch)
                )
                > pending_event.line
                for pending_event in pending
            )
            and all(event.group in stream_groups for event in group_events)
            and len(baselines) == 1
            and all(event.line > baselines[0][0] for event in group_events)
            and reason_ok
            and telemetry_ok
        )
        resets_by_epoch: dict[int, list[tuple[int, int, str]]] = {}
        for event in scene_resets:
            resets_by_epoch.setdefault(event[1], []).append(event)
        summaries_by_epoch: dict[int, list[_AssetStreamRuntimeSummary]] = {}
        for event in asset_summaries:
            summaries_by_epoch.setdefault(event.epoch, []).append(event)
        baseline_line = baselines[0][0] if len(baselines) == 1 else None
        summary_ok = (
            bool(resets_by_epoch)
            and set(resets_by_epoch) == set(summaries_by_epoch)
            and len(baselines) == 1
            and all(len(events) == 1 for events in resets_by_epoch.values())
            and all(len(events) == 1 for events in summaries_by_epoch.values())
            and sorted(resets_by_epoch)
            == list(range(2, 2 + len(resets_by_epoch)))
            and [event[1] for event in sorted(scene_resets)]
            == list(range(2, 2 + len(scene_resets)))
            and all(event[0] > baseline_line for event in scene_resets)
            and all(
                reason != "map_to_map" or epoch + 1 in resets_by_epoch
                for _, epoch, reason in scene_resets
            )
            and all(
                reason != "shutdown" or epoch == max(resets_by_epoch)
                for _, epoch, reason in scene_resets
            )
        )
        previous_summary_line: int | None = None
        for epoch in sorted(set(resets_by_epoch) | set(summaries_by_epoch)):
            epoch_terminals = [event for event in terminals if event.epoch == epoch]
            epoch_events = [event for event in group_events if event.epoch == epoch]
            resets = resets_by_epoch.get(epoch, [])
            summaries = summaries_by_epoch.get(epoch, [])
            if len(resets) != 1 or len(summaries) != 1:
                summary_ok = False
                continue
            summary = summaries[0]
            requested = len(epoch_terminals)
            loaded = sum(event.status == "loaded" for event in epoch_terminals)
            fallback = sum(event.status == "fallback" for event in epoch_terminals)
            budget = sum(
                event.status == "fallback" and event.reason == "budget_denied"
                for event in epoch_terminals
            )
            expected_resource_summary = (
                _asset_stream_summary_maximum(
                    [event.process_private_bytes for event in epoch_terminals]
                ),
                _asset_stream_summary_minimum(
                    [event.available_commit_bytes for event in epoch_terminals]
                ),
                _asset_stream_summary_minimum(
                    [event.available_physical_bytes for event in epoch_terminals]
                ),
                _asset_stream_summary_maximum(
                    [event.gm_resident_bytes for event in epoch_terminals]
                ),
                _asset_stream_summary_maximum(
                    [event.ui_resident_bytes for event in epoch_terminals]
                ),
                _asset_stream_summary_maximum(
                    [event.audio_stream_bytes for event in epoch_terminals]
                ),
            )
            if (
                (
                    summary.requested,
                    summary.loaded,
                    summary.fallback,
                    summary.budget_denied,
                    summary.memory_samples,
                )
                != (requested, loaded, fallback, budget, requested)
                or (
                    summary.max_private_bytes,
                    summary.min_available_commit_bytes,
                    summary.min_available_physical_bytes,
                    summary.max_gm_resident_bytes,
                    summary.max_ui_resident_bytes,
                    summary.max_audio_stream_bytes,
                )
                != expected_resource_summary
                or any(
                    value > 2**63 - 1
                    for value in (
                        summary.max_private_bytes,
                        summary.min_available_commit_bytes,
                        summary.min_available_physical_bytes,
                        summary.max_gm_resident_bytes,
                        summary.max_ui_resident_bytes,
                        summary.max_audio_stream_bytes,
                    )
                )
                or (
                    summary.page_mask_blocked is not None
                    and summary.page_mask_blocked != 0
                )
                or (
                    summary.page_mask_failures is not None
                    and summary.page_mask_failures != 0
                )
                or (
                    summary.mask_route_postfix_mismatches is not None
                    and summary.mask_route_postfix_mismatches != 0
                )
                or requested > len(stream_groups)
                or baseline_line is None
                or resets[0][0] <= baseline_line
                or not all(
                    baseline_line < event.line < resets[0][0]
                    for event in epoch_events
                )
                or (
                    previous_summary_line is not None
                    and (
                        resets[0][0] <= previous_summary_line
                        or any(
                            event.line <= previous_summary_line
                            for event in epoch_events
                        )
                    )
                )
                or resets[0][0] >= summary.line
            ):
                summary_ok = False
            previous_summary_line = summary.line
        if any(event.epoch not in summaries_by_epoch for event in group_events):
            summary_ok = False
    else:
        init_ok = (
            len(plain_asset_inactive) == 1
            and asset_dynamic_count == 0
            and not stream_groups
            and len(runtime_initialized_lines) == 1
            and plain_asset_inactive[0] < runtime_initialized_lines[0]
        )
        baseline_ok = not baselines and not baseline_vanilla
        terminal_shape_ok = not group_events
        summary_ok = not scene_resets and not asset_summaries
    checks.extend(
        (
            _check(
                "runtime.asset_stream_state",
                init_ok,
                f"enabled={asset_stream_enabled} initialized={initialized} "
                f"states={asset_states} inactive={plain_asset_inactive}",
            ),
            _check(
                "runtime.asset_stream_baseline",
                baseline_ok,
                f"captured={baselines} vanilla={baseline_vanilla}",
            ),
            _check(
                "runtime.asset_stream_group_terminals",
                terminal_shape_ok,
                json.dumps(
                    [event.__dict__ for event in group_events],
                    sort_keys=True,
                ),
            ),
            _check(
                "runtime.asset_stream_summaries",
                summary_ok,
                f"resets={scene_resets} summaries="
                f"{[summary.__dict__ for summary in asset_summaries]}",
            ),
        )
    )

    ui_ready: list[tuple[int, int, int]] = []
    ui_failures: list[tuple[int, str, str]] = []
    ui_terminals: list[tuple[int, str, str]] = []
    ui_summaries: list[tuple[int, int, int, int]] = []
    ui_legacy_fallbacks: list[tuple[int, str]] = []
    for event, line_numbers in runtime_event_lines.items():
        if (
            event.startswith("SEDE_RUNTIME_V1|event=ui_texture_")
            and ("|status=fallback" in event or "|fallback=" in event)
        ):
            ui_legacy_fallbacks.extend((line, event) for line in line_numbers)
        match = _RUNTIME_UI_STREAM_READY_RE.fullmatch(event)
        if match is not None:
            ui_ready.extend(
                (line, int(match.group(1)), int(match.group(2)))
                for line in line_numbers
            )
            continue
        match = _RUNTIME_UI_STREAM_UNAVAILABLE_RE.fullmatch(event)
        if match is not None:
            ui_failures.extend(
                (line, "unavailable", match.group(1)) for line in line_numbers
            )
            continue
        match = _RUNTIME_UI_STREAM_FAILED_CLOSED_RE.fullmatch(event)
        if match is not None:
            ui_failures.extend(
                (line, "failed_closed", match.group(1))
                for line in line_numbers
            )
            continue
        match = _RUNTIME_UI_STREAM_TERMINAL_RE.fullmatch(event)
        if match is not None:
            ui_terminals.extend(
                (line, match.group(1), match.group(2)) for line in line_numbers
            )
            continue
        match = _RUNTIME_UI_STREAM_SUMMARY_RE.fullmatch(event)
        if match is not None:
            ui_summaries.extend(
                (
                    line,
                    int(match.group(1)),
                    int(match.group(2)),
                    int(match.group(3)),
                )
                for line in line_numbers
            )
    if ui_texture_streaming_enabled:
        expected_folded_paths = {
            path.casefold() for path in expected_ui_paths
        }
        terminal_folded_paths = {
            event[2].casefold() for event in ui_terminals
        }
        ui_ok = (
            len(expected_ui_paths) == _UI_TEXTURE_RUNTIME_ENTRY_COUNT
            and expected_ui_resident_charge_bytes is not None
            and expected_ui_resident_charge_bytes > 0
            and len(ui_ready) == 1
            and ui_ready[0][1] == _UI_TEXTURE_RUNTIME_ENTRY_COUNT
            and ui_ready[0][1] == len(expected_ui_paths)
            and ui_ready[0][2] == expected_ui_resident_charge_bytes
            and not ui_failures
            and not ui_legacy_fallbacks
            and len(ui_summaries) == 1
            and bool(ui_terminals)
            and all(event[1] == "lazy_loaded" for event in ui_terminals)
            and len(terminal_folded_paths) == len(ui_terminals)
            and terminal_folded_paths <= expected_folded_paths
            and ui_summaries[0][1] == len(ui_terminals)
            and ui_summaries[0][2] == len(ui_terminals)
            and ui_summaries[0][3] == 0
            and ui_summaries[0][2] >= 1
            and len(runtime_initialized_lines) == 1
            and ui_ready[0][0] < runtime_initialized_lines[0]
            and ui_ready[0][0] < min(event[0] for event in ui_terminals)
            and max(event[0] for event in ui_terminals) < ui_summaries[0][0]
        )
    else:
        ui_ok = not (
            ui_ready
            or ui_failures
            or ui_terminals
            or ui_summaries
            or ui_legacy_fallbacks
        )
    checks.append(
        _check(
            "runtime.ui_texture_stream_events",
            ui_ok,
            f"enabled={ui_texture_streaming_enabled} ready={ui_ready} "
            f"terminals={ui_terminals} summaries={ui_summaries} "
            f"failures={ui_failures} legacy_fallbacks={ui_legacy_fallbacks} "
            f"expected_entries={len(expected_ui_paths)} "
            f"expected_resident_charge_bytes={expected_ui_resident_charge_bytes}",
        )
    )

    pcm_ready: list[tuple[int, int]] = []
    pcm_lane_fallback: list[tuple[int, str]] = []
    pcm_track_fallback: list[tuple[int, str, str]] = []
    pcm_summaries: list[tuple[int, int, int, int, int]] = []
    pcm_inactive = runtime_event_lines.get(_RUNTIME_PCM_STREAM_INACTIVE, [])
    for event, line_numbers in runtime_event_lines.items():
        match = _RUNTIME_PCM_STREAM_READY_RE.fullmatch(event)
        if match is not None:
            pcm_ready.extend((line, int(match.group(1))) for line in line_numbers)
            continue
        match = _RUNTIME_PCM_STREAM_LANE_FALLBACK_RE.fullmatch(event)
        if match is not None:
            pcm_lane_fallback.extend(
                (line, match.group(1)) for line in line_numbers
            )
            continue
        match = _RUNTIME_PCM_STREAM_TRACK_FALLBACK_RE.fullmatch(event)
        if match is not None:
            pcm_track_fallback.extend(
                (line, match.group(1), match.group(2)) for line in line_numbers
            )
            continue
        match = _RUNTIME_PCM_STREAM_SUMMARY_RE.fullmatch(event)
        if match is not None:
            pcm_summaries.extend(
                (
                    line,
                    int(match.group(1)),
                    int(match.group(2)),
                    int(match.group(3)),
                    int(match.group(4)),
                )
                for line in line_numbers
            )
    if pcm_streaming_enabled:
        summary = pcm_summaries[0] if len(pcm_summaries) == 1 else None
        pcm_ok = (
            len(pcm_ready) == 1
            and pcm_ready[0][1] == len(expected_audio_files)
            and not pcm_lane_fallback
            and len(pcm_inactive) == 1
            and summary is not None
            and summary[1] >= 1
            and summary[2] >= 1
            # A reader can fault after its procedural clip was served.  The
            # request and served counters then stay paired while the unique
            # (request, reason) fallback counter also advances.
            and summary[2] <= summary[1]
            and summary[3] == len(pcm_track_fallback)
            and summary[4]
            == sum(event[2] == "budget_denied" for event in pcm_track_fallback)
            and summary[4] <= summary[3]
            and len({(event[1].casefold(), event[2]) for event in pcm_track_fallback})
            == len(pcm_track_fallback)
            and all(
                event[1].casefold()
                in {name.casefold() for name in expected_audio_files}
                for event in pcm_track_fallback
            )
            and len(runtime_initialized_lines) == 1
            and pcm_ready[0][0] < runtime_initialized_lines[0]
            and pcm_ready[0][0] < pcm_inactive[0] < summary[0]
        )
    else:
        pcm_ok = not (
            pcm_ready
            or pcm_lane_fallback
            or pcm_track_fallback
            or pcm_summaries
            or pcm_inactive
        )
    checks.append(
        _check(
            "runtime.pcm_stream_events",
            pcm_ok,
            f"enabled={pcm_streaming_enabled} ready={pcm_ready} "
            f"inactive={pcm_inactive} fallback={pcm_track_fallback} "
            f"lane_fallback={pcm_lane_fallback} summaries={pcm_summaries}",
        )
    )
    asset_inactive = [event for event in asset_states if event[1] == "inactive"]
    lane_order_ok = True
    if ui_texture_streaming_enabled and pcm_streaming_enabled:
        lane_order_ok = lane_order_ok and (
            len(ui_ready) == 1
            and len(pcm_ready) == 1
            and ui_ready[0][0] < pcm_ready[0][0]
            and len(pcm_summaries) == 1
            and len(ui_summaries) == 1
            and pcm_summaries[0][0] < ui_summaries[0][0]
        )
    if ui_texture_streaming_enabled and asset_stream_enabled:
        lane_order_ok = lane_order_ok and (
            len(ui_ready) == 1
            and len(initialized) == 1
            and ui_ready[0][0] < initialized[0][0]
            and len(asset_inactive) == 1
            and len(ui_summaries) == 1
            and asset_inactive[0][0] < ui_summaries[0][0]
        )
    if pcm_streaming_enabled and asset_stream_enabled:
        lane_order_ok = lane_order_ok and (
            len(pcm_ready) == 1
            and len(initialized) == 1
            and pcm_ready[0][0] < initialized[0][0]
            and len(asset_inactive) == 1
            and len(pcm_inactive) == 1
            and asset_inactive[0][0] < pcm_inactive[0]
        )
    checks.append(
        _check(
            "runtime.streaming_lane_order",
            lane_order_ok,
            f"ui_ready={ui_ready} pcm_ready={pcm_ready} "
            f"asset_initialized={initialized} runtime={runtime_initialized_lines} "
            f"asset_states={asset_states} pcm_inactive={pcm_inactive} "
            f"pcm_summaries={pcm_summaries} ui_summaries={ui_summaries}",
        )
    )
    return checks


def _normalized_log_text(value: str) -> str:
    return value.replace("\\", "/").casefold()


def _is_error_line(value: str) -> bool:
    normalized = value.casefold()
    return (
        "[error" in normalized
        or "exception" in normalized
        or "failed" in normalized
    )


def _is_exception_context_line(value: str) -> bool:
    """Recognize only the bounded, conventional continuation of an error.

    This deliberately does not treat arbitrary nearby log lines as related:
    an unrelated plugin error immediately after an Europe status line must not
    poison the result.  Stack frames and the standard exception separators are
    the only lines allowed to extend a candidate block.
    """

    stripped = value.lstrip()
    folded = stripped.casefold()
    return (
        value[:1].isspace()
        or folded.startswith(("at ", "--- ", "caused by:", "inner exception:"))
        or "stack trace" in folded
    )


def _related_mod_errors(lines: list[str], ownership_tokens: set[str]) -> list[str]:
    normalized_lines = [_normalized_log_text(line) for line in lines]
    related_indexes: set[int] = set()
    for index, line in enumerate(lines):
        if not _is_error_line(line):
            continue
        if any(token in normalized_lines[index] for token in ownership_tokens):
            related_indexes.add(index)
            continue

        # Attribute an otherwise generic exception only when its immediate,
        # bounded stack continuation proves an Europe namespace/path/asset.
        block_indexes = [index]
        for candidate in range(index + 1, min(len(lines), index + 9)):
            if not _is_exception_context_line(lines[candidate]):
                break
            block_indexes.append(candidate)
        if any(
            any(token in normalized_lines[candidate] for token in ownership_tokens)
            for candidate in block_indexes
        ):
            related_indexes.update(block_indexes)

    return [
        lines[index][:512]
        for index in sorted(related_indexes)[:10]
    ]


def validate_runtime_log(
    log_path: Path,
    install_manifest_path: Path,
    *,
    expected_destination: Path | None = None,
    expected_source_build_id: str | None = None,
    expected_target_build_id: str | None = None,
    expected_profile_id: str | None = None,
    expected_guid: str | None = None,
) -> list[ValidationCheck]:
    checks: list[ValidationCheck] = []
    checks.append(_check("runtime.log_exists", log_path.is_file(), str(log_path)))
    checks.append(
        _check(
            "runtime.install_manifest_exists",
            install_manifest_path.is_file(),
            str(install_manifest_path),
        )
    )
    if not log_path.is_file() or not install_manifest_path.is_file():
        return checks

    install, install_read_detail = _read_json_object(install_manifest_path)
    if install is None:
        checks.append(
            _check("runtime.install_manifest_schema", False, install_read_detail)
        )
        return checks
    install_schema_ok, install_schema_detail = _install_manifest_schema(install)
    checks.append(
        _check(
            "runtime.install_manifest_schema",
            install_schema_ok,
            install_schema_detail,
        )
    )
    if not install_schema_ok:
        return checks

    raw_destination = install["destination"]
    assert isinstance(raw_destination, str)
    destination_path = Path(raw_destination)
    destination_identity_ok = (
        expected_destination is None
        or _lexical_windows_path_key(raw_destination)
        == _lexical_windows_path_key(expected_destination)
    )
    checks.append(
        _check(
            "runtime.install_destination_identity",
            destination_identity_ok,
            f"expected={expected_destination} actual={raw_destination}",
        )
    )
    if not destination_identity_ok:
        return checks

    chain_base = (
        expected_destination.parent
        if expected_destination is not None
        else destination_path.parent
    )
    chain_ok, chain_detail = _non_reparse_chain(chain_base, destination_path)
    checks.append(
        _check("runtime.install_destination_chain", chain_ok, chain_detail)
    )
    if not chain_ok:
        return checks
    destination = destination_path.absolute()

    snapshot_ok, snapshot_detail = _installed_snapshot_integrity(
        destination_path,
        install.get("files"),
    )
    checks.append(
        _check(
            "runtime.installed_snapshot_integrity",
            snapshot_ok,
            snapshot_detail,
        )
    )
    if not snapshot_ok:
        return checks

    build_manifest_path = destination / "build-manifest.json"
    info_path = destination / "info.json"
    checks.append(
        _check("runtime.installed_build_manifest", build_manifest_path.is_file(), str(build_manifest_path))
    )
    checks.append(_check("runtime.installed_info", info_path.is_file(), str(info_path)))
    if not build_manifest_path.is_file() or not info_path.is_file():
        return checks

    build_manifest, build_read_detail = _read_json_object(build_manifest_path)
    info, info_read_detail = _read_json_object(info_path)
    installed_files = install["files"]
    assert isinstance(installed_files, dict)
    if build_manifest is None:
        build_schema_ok = False
        build_schema_detail = build_read_detail
    else:
        build_schema_ok, build_schema_detail = _build_manifest_schema(
            build_manifest,
            installed_files,
            destination,
        )
    checks.append(
        _check(
            "runtime.build_manifest_schema",
            build_schema_ok,
            build_schema_detail,
        )
    )

    if info is None:
        info_schema_ok = False
        info_schema_detail = info_read_detail
    else:
        info_schema_ok, info_schema_detail = _info_schema(
            info,
            build_manifest.get("mod_info") if build_manifest is not None else None,
        )
    checks.append(
        _check("runtime.info_schema", info_schema_ok, info_schema_detail)
    )
    if not build_schema_ok or not info_schema_ok:
        return checks
    assert build_manifest is not None
    assert info is not None

    identity_expectations = (
        (
            "runtime.source_build_identity",
            "source_build_id",
            expected_source_build_id,
        ),
        (
            "runtime.target_build_identity",
            "target_build_id",
            expected_target_build_id,
        ),
        ("runtime.profile_identity", "profile_id", expected_profile_id),
    )
    identity_ok = True
    for check_name, field_name, expected in identity_expectations:
        actual = build_manifest[field_name]
        matched = expected is None or actual == expected
        identity_ok = identity_ok and matched
        checks.append(
            _check(
                check_name,
                matched,
                f"expected={expected!r} actual={actual!r}",
            )
        )
    if not identity_ok:
        return checks

    guid = info["GUID"]
    assert isinstance(guid, str)
    guid_identity_ok = expected_guid is None or guid == expected_guid
    checks.append(
        _check(
            "runtime.guid_identity",
            guid_identity_ok,
            f"expected={expected_guid!r} actual={guid!r}",
        )
    )
    if not guid_identity_ok:
        return checks
    log_mtime = datetime.fromtimestamp(log_path.stat().st_mtime).astimezone()
    installed_at = datetime.fromisoformat(install["installed_at_utc"])
    checks.append(
        _check(
            "runtime.log_after_install",
            log_mtime >= installed_at,
            f"log={log_mtime.isoformat()} installed={installed_at.isoformat()}",
        )
    )

    text = log_path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    outputs = build_manifest.get("outputs", [])
    output_entries = outputs if isinstance(outputs, list) else []
    output_by_path = {
        str(entry["relative_path"]): entry
        for entry in output_entries
        if isinstance(entry, dict) and isinstance(entry.get("relative_path"), str)
    }
    (
        artifact_checks,
        runtime_declared,
        parsed_runtime_contract,
        expected_audio_files,
        roster_enabled,
        parsed_roster_contract,
        farm_enabled,
        worker_militia_enabled,
        diplomacy_enabled,
        fortifications_enabled,
        dock_enabled,
        dock_rules,
    ) = _runtime_artifact_checks(
        destination,
        output_by_path,
        str(build_manifest["source_build_id"]),
        str(build_manifest["target_build_id"]),
        (
            expected_profile_id
            if expected_profile_id is not None
            else str(build_manifest["profile_id"])
        ),
    )
    checks.extend(artifact_checks)
    checks.append(
        _check(
            "runtime.roster_profile_identity_bound",
            expected_profile_id is not None
            or roster_enabled is not True
            or build_manifest["profile_id"]
            == "europe-roster-runtime-canary",
            f"expected={expected_profile_id!r} "
            f"actual={build_manifest['profile_id']!r} "
            f"selected={roster_enabled!r}",
        )
    )
    audio_payload = (
        parsed_runtime_contract.get("audio_payload")
        if parsed_runtime_contract is not None
        else None
    )
    foliage_requested = (
        parsed_runtime_contract.get("foliage_tree_apple")
        if parsed_runtime_contract is not None
        else None
    )
    runtime_dll_entry = output_by_path.get(RUNTIME_DLL_PATH)
    runtime_dll_metadata = (
        runtime_dll_entry.get("metadata")
        if isinstance(runtime_dll_entry, dict)
        and isinstance(runtime_dll_entry.get("metadata"), dict)
        else {}
    )
    asset_stream_enabled = (
        runtime_dll_metadata.get("asset_stream_enabled") is True
    )
    ui_texture_streaming_enabled = (
        runtime_dll_metadata.get("ui_texture_streaming_enabled") is True
    )
    pcm_streaming_enabled = (
        runtime_dll_metadata.get("pcm_streaming_enabled") is True
    )

    stream_output_paths = {
        relative
        for relative in output_by_path
        if relative.casefold().startswith("runtime/assetbundles/")
    }
    legacy_gm_paths = {
        relative
        for relative in output_by_path
        if relative.casefold().startswith(
            ("override/atlas/", "override/sprites/")
        )
    }
    stream_groups: set[str] = set()
    stream_group_resources: dict[str, tuple[int, int]] = {}
    stream_backend_kind: str | None = None
    stream_resource_policy_kind: str | None = None
    stream_index_detail = "disabled"
    stream_index_ok = not asset_stream_enabled
    if asset_stream_enabled:
        try:
            (
                _,
                stream_index,
                raw_stream_groups,
                raw_omitted_groups,
            ) = _strict_stream_index_shape(destination / ASSET_STREAM_INDEX_PATH)
            stream_groups = {
                str(group["group"])
                for group in raw_stream_groups
                if isinstance(group.get("group"), str)
            }
            stream_group_resources = {
                str(group["group"]): (
                    int(group["resident_charge_bytes"]),
                    int(group["predicted_load_peak_bytes"]),
                )
                for group in raw_stream_groups
                if isinstance(group.get("group"), str)
                and type(group.get("resident_charge_bytes")) is int
                and type(group.get("predicted_load_peak_bytes")) is int
            }
            index_entry = output_by_path.get(ASSET_STREAM_INDEX_PATH)
            index_metadata = (
                index_entry.get("metadata")
                if isinstance(index_entry, dict)
                and isinstance(index_entry.get("metadata"), dict)
                else {}
            )
            stream_backend_kind, stream_resource_policy_kind = (
                _asset_stream_runtime_identity(stream_index, index_metadata)
            )
            stream_index_ok = (
                len(stream_groups) == len(raw_stream_groups)
                and len(stream_group_resources) == len(raw_stream_groups)
                and index_metadata.get("group_count") == len(raw_stream_groups)
                and index_metadata.get("vanilla_omitted_group_count")
                == len(raw_omitted_groups)
                and index_metadata.get("selected_group_count")
                == len(raw_stream_groups) + len(raw_omitted_groups)
            )
            stream_index_detail = (
                f"groups={len(stream_groups)} metadata="
                f"{index_metadata.get('group_count')!r} "
                f"omitted={len(raw_omitted_groups)}"
            )
        except (OSError, ValueError, KeyError) as exc:
            stream_index_ok = False
            stream_index_detail = str(exc)
    checks.append(
        _check(
            "runtime.asset_stream_index_contract",
            stream_index_ok,
            stream_index_detail,
        )
    )
    checks.append(
        _check(
            "runtime.asset_stream_output_exclusive",
            (
                bool(stream_output_paths) == asset_stream_enabled
                and not (asset_stream_enabled and legacy_gm_paths)
            ),
            f"enabled={asset_stream_enabled} "
            f"stream={sorted(stream_output_paths)} legacy={sorted(legacy_gm_paths)}",
        )
    )

    ui_output_check, ui_expectation = _runtime_ui_texture_output_contract(
        destination,
        output_by_path,
        runtime_dll_metadata,
    )
    checks.append(ui_output_check)
    expected_ui_paths = set(ui_expectation.paths)
    runtime_audio_paths = {
        relative
        for relative in output_by_path
        if relative.startswith("Runtime/Audio/")
    }
    legacy_music_paths = {
        relative
        for relative in output_by_path
        if relative.startswith("Override/Sounds/Music/")
    }
    checks.append(
        _check(
            "runtime.pcm_stream_output_exclusive",
            (
                (bool(runtime_audio_paths) == pcm_streaming_enabled)
                and not (pcm_streaming_enabled and legacy_music_paths)
                and not ((not pcm_streaming_enabled) and runtime_audio_paths)
            ),
            f"enabled={pcm_streaming_enabled} runtime={sorted(runtime_audio_paths)} "
            f"legacy={sorted(legacy_music_paths)}",
        )
    )
    tree_atlas_installed = {
        "Override/Atlas/tree_apple/atlas.json",
        "Override/Atlas/tree_apple/atlas.png",
        "Override/Atlas/tree_apple/atlas_m.png",
    } <= set(installed_files)
    tree_streamed = "tree_apple" in stream_groups
    expected_tree_artifact = (
        tree_streamed if asset_stream_enabled else tree_atlas_installed
    )
    checks.append(
        _check(
            "runtime.companion_foliage_artifact_presence",
            (foliage_requested is True) == expected_tree_artifact
            and not (tree_atlas_installed and tree_streamed),
            f"requested={foliage_requested} atlas={tree_atlas_installed} "
            f"streamed={tree_streamed}",
        )
    )

    events, severity_errors, runtime_event_lines = _runtime_contract_events(lines)
    event_counts = {event: events.count(event) for event in _RUNTIME_EVENTS}
    unknown_events = [event for event in events if not _recognized_runtime_event(event)]
    duplicate_events = {
        event: len(line_numbers)
        for event, line_numbers in runtime_event_lines.items()
        if len(line_numbers) > 1
    }
    roster_active_events: list[tuple[int, str]] = []
    roster_ui_events: list[tuple[int, int]] = []
    roster_failure_events: list[tuple[int, str, str]] = []
    roster_cleanup_events: list[tuple[int, int, int, str]] = []
    for event, line_numbers in runtime_event_lines.items():
        active_match = _RUNTIME_ROSTER_ACTIVE_RE.fullmatch(event)
        ui_match = _RUNTIME_ROSTER_UI_RE.fullmatch(event)
        failure_match = _runtime_roster_failure_match(event)
        cleanup_match = _RUNTIME_ROSTER_CLEANUP_RE.fullmatch(event)
        if active_match is not None:
            roster_active_events.extend(
                (line_number, active_match.group(1))
                for line_number in line_numbers
            )
        elif ui_match is not None:
            roster_ui_events.extend(
                (line_number, int(ui_match.group(1)))
                for line_number in line_numbers
            )
        elif failure_match is not None:
            roster_failure_events.extend(
                (line_number, failure_match.group(1), failure_match.group(2))
                for line_number in line_numbers
            )
        elif cleanup_match is not None:
            roster_cleanup_events.extend(
                (
                    line_number,
                    int(cleanup_match.group(1)),
                    int(cleanup_match.group(2)),
                    cleanup_match.group(3),
                )
                for line_number in line_numbers
            )
    music_route_events: list[tuple[int, int, str]] = []
    for event, line_numbers in runtime_event_lines.items():
        route_match = _RUNTIME_MUSIC_ROUTE_ACTIVE_RE.fullmatch(event)
        if route_match is not None:
            music_route_events.extend(
                (line_number, int(route_match.group(1)), route_match.group(2))
                for line_number in line_numbers
            )
    roster_active_events.sort()
    roster_ui_events.sort()
    roster_failure_events.sort()
    roster_cleanup_events.sort()
    music_route_events.sort()
    checks.append(
        _check(
            "runtime.companion_event_presence",
            runtime_declared == bool(events),
            f"runtime_paths={runtime_declared} events={len(events)}",
        )
    )
    checks.append(
        _check(
            "runtime.companion_event_schema",
            not unknown_events and not severity_errors,
            json.dumps(
                {
                    "unknown_events": unknown_events,
                    "severity_errors": severity_errors,
                },
                sort_keys=True,
            ),
        )
    )
    checks.append(
        _check(
            "runtime.companion_event_unique",
            not duplicate_events,
            json.dumps(duplicate_events, sort_keys=True),
        )
    )
    if runtime_declared:
        checks.extend(
            _streaming_runtime_event_checks(
                runtime_event_lines,
                asset_stream_enabled=asset_stream_enabled,
                expected_asset_stream_backend_kind=stream_backend_kind,
                expected_asset_stream_resource_policy_kind=(
                    stream_resource_policy_kind
                ),
                stream_groups=stream_groups,
                stream_group_resources=stream_group_resources,
                ui_texture_streaming_enabled=ui_texture_streaming_enabled,
                expected_ui_paths=expected_ui_paths,
                expected_ui_resident_charge_bytes=(
                    ui_expectation.resident_charge_bytes
                ),
                pcm_streaming_enabled=pcm_streaming_enabled,
                expected_audio_files=expected_audio_files,
            )
        )
        checks.append(
            _check(
                "runtime.companion_initialized",
                event_counts[RUNTIME_INITIALIZED] == 1
                and event_counts[RUNTIME_INITIALIZATION_FAILED] == 0,
                f"initialized={event_counts[RUNTIME_INITIALIZED]} "
                f"failed_closed={event_counts[RUNTIME_INITIALIZATION_FAILED]}",
            )
        )
        wolf_route_expected = (
            build_manifest["profile_id"]
            != _WOLF_SPRITE_ROUTE_ISOLATED_PROFILE_ID
        )
        initialized_lines = runtime_event_lines.get(RUNTIME_INITIALIZED, [])
        wolf_active_lines = runtime_event_lines.get(
            RUNTIME_WOLF_SPRITE_ROUTE_ACTIVE,
            [],
        )
        wolf_failed_events = sorted(
            (
                line_number,
                match.group(1),
            )
            for event, line_numbers in runtime_event_lines.items()
            for match in [_RUNTIME_WOLF_SPRITE_ROUTE_FAILED_RE.fullmatch(event)]
            if match is not None
            for line_number in line_numbers
        )
        if wolf_route_expected:
            wolf_route_ok = (
                len(wolf_active_lines) == 1
                and not wolf_failed_events
                and len(initialized_lines) == 1
                and wolf_active_lines[0] < initialized_lines[0]
            )
        else:
            wolf_route_ok = not wolf_active_lines and not wolf_failed_events
        checks.append(
            _check(
                "runtime.companion_wolf_sprite_route",
                wolf_route_ok,
                f"profile={build_manifest['profile_id']!r} "
                f"expected={wolf_route_expected} active={wolf_active_lines} "
                f"failed_open={wolf_failed_events} "
                f"initialized={initialized_lines}",
            )
        )
        expected_audio_event = (
            RUNTIME_AUDIO_ACTIVE if audio_payload is True else RUNTIME_AUDIO_INACTIVE
        )
        unexpected_audio_event = (
            RUNTIME_AUDIO_INACTIVE if audio_payload is True else RUNTIME_AUDIO_ACTIVE
        )
        checks.append(
            _check(
                "runtime.companion_audio_state",
                isinstance(audio_payload, bool)
                and event_counts[expected_audio_event] == 1
                and event_counts[unexpected_audio_event] == 0
                and event_counts[RUNTIME_AUDIO_FAILED] == 0,
                f"expected={expected_audio_event} counts="
                + json.dumps(
                    {
                        "active": event_counts[RUNTIME_AUDIO_ACTIVE],
                        "inactive": event_counts[RUNTIME_AUDIO_INACTIVE],
                        "failed": event_counts[RUNTIME_AUDIO_FAILED],
                    },
                    sort_keys=True,
                ),
            )
        )
        # The route map is what carries the music into gameplay; the table
        # override alone only reaches the menus.  Pin entry count and digest so
        # a shrunk or reordered map cannot pass as a working one.
        expected_route_entries = len(music_route_entries())
        expected_route_digest = music_route_sha256()
        if audio_payload is True:
            music_route_ok = (
                len(music_route_events) == 1
                and music_route_events[0][1] == expected_route_entries
                and music_route_events[0][2] == expected_route_digest
                and event_counts[RUNTIME_MUSIC_ROUTE_INACTIVE] == 0
            )
        else:
            music_route_ok = (
                not music_route_events
                and event_counts[RUNTIME_MUSIC_ROUTE_INACTIVE] == 1
            )
        checks.append(
            _check(
                "runtime.companion_music_route",
                isinstance(audio_payload, bool) and music_route_ok,
                f"audio_payload={audio_payload} "
                f"expected_entries={expected_route_entries} "
                f"expected_digest={expected_route_digest} "
                f"observed={music_route_events} "
                f"inactive={event_counts[RUNTIME_MUSIC_ROUTE_INACTIVE]}",
            )
        )
        farm_summary_events = [
            (line_number, int(match.group(1)), int(match.group(2)))
            for event, line_numbers in runtime_event_lines.items()
            for match in [_RUNTIME_FARM_SUMMARY_RE.fullmatch(event)]
            if match is not None
            for line_number in line_numbers
        ]
        if farm_enabled is True:
            farm_ok = (
                event_counts[RUNTIME_FARM_PLACEMENT_ACTIVE] == 1
                and event_counts[RUNTIME_FARM_PLACEMENT_INACTIVE] == 0
                and event_counts[RUNTIME_FARM_PLACEMENT_FAILED] == 0
            )
        else:
            farm_ok = (
                event_counts[RUNTIME_FARM_PLACEMENT_INACTIVE] == 1
                and event_counts[RUNTIME_FARM_PLACEMENT_ACTIVE] == 0
                and event_counts[RUNTIME_FARM_PLACEMENT_FAILED] == 0
                and not farm_summary_events
            )
        checks.append(
            _check(
                "runtime.companion_farm_placement",
                isinstance(farm_enabled, bool) and farm_ok,
                f"selected={farm_enabled} "
                + json.dumps(
                    {
                        "active": event_counts[RUNTIME_FARM_PLACEMENT_ACTIVE],
                        "inactive": event_counts[RUNTIME_FARM_PLACEMENT_INACTIVE],
                        "failed": event_counts[RUNTIME_FARM_PLACEMENT_FAILED],
                        "summary": farm_summary_events,
                    },
                    sort_keys=True,
                ),
            )
        )
        evidence_order_ok, militia_evidence = _worker_militia_evidence_status(
            runtime_event_lines
        )
        if worker_militia_enabled is True:
            multiplayer_suppressed = event_counts[
                RUNTIME_WORKER_MILITIA_MULTIPLAYER_SUPPRESSED
            ]
            worker_militia_ok = (
                event_counts[RUNTIME_WORKER_MILITIA_ACTIVE] == 1
                and event_counts[RUNTIME_WORKER_MILITIA_INACTIVE] == 0
                and event_counts[RUNTIME_WORKER_MILITIA_FAILED] == 0
                and (
                    (multiplayer_suppressed == 0 and evidence_order_ok)
                    or (
                        multiplayer_suppressed == 1
                        and not any(militia_evidence.values())
                    )
                )
            )
        else:
            worker_militia_ok = (
                event_counts[RUNTIME_WORKER_MILITIA_INACTIVE] == 1
                and event_counts[RUNTIME_WORKER_MILITIA_ACTIVE] == 0
                and event_counts[RUNTIME_WORKER_MILITIA_FAILED] == 0
                and event_counts[
                    RUNTIME_WORKER_MILITIA_MULTIPLAYER_SUPPRESSED
                ] == 0
                and not any(militia_evidence.values())
            )
        checks.append(
            _check(
                "runtime.companion_worker_militia",
                isinstance(worker_militia_enabled, bool) and worker_militia_ok,
                f"selected={worker_militia_enabled} "
                + json.dumps(
                    {
                        "active": event_counts[RUNTIME_WORKER_MILITIA_ACTIVE],
                        "inactive": event_counts[RUNTIME_WORKER_MILITIA_INACTIVE],
                        "failed": event_counts[RUNTIME_WORKER_MILITIA_FAILED],
                        "network_suppressed": event_counts[
                            RUNTIME_WORKER_MILITIA_MULTIPLAYER_SUPPRESSED
                        ],
                        "evidence": militia_evidence,
                    },
                    sort_keys=True,
                ),
            )
        )
        diplomacy_feature_events = sorted(
            (line_number, match.group(1))
            for event, line_numbers in runtime_event_lines.items()
            for match in [_RUNTIME_DIPLOMACY_FEATURE_RE.fullmatch(event)]
            if match is not None
            for line_number in line_numbers
        )
        diplomacy_runtime_events = sorted(
            (line_number, event)
            for event, line_numbers in runtime_event_lines.items()
            if _RUNTIME_DIPLOMACY_EVENT_RE.fullmatch(event) is not None
            and _RUNTIME_DIPLOMACY_FEATURE_RE.fullmatch(event) is None
            for line_number in line_numbers
        )
        diplomacy_activation_events = [
            entry
            for entry in diplomacy_runtime_events
            if entry[1].startswith(
                "SEDE_RUNTIME_V1|lane=diplomacy|event=activation"
                "|status=active|canary=true|"
            )
        ]
        diplomacy_failure_events = [
            entry
            for entry in diplomacy_feature_events
            if entry[1] in {"failed", "failed_closed"}
        ] + [
            entry
            for entry in diplomacy_runtime_events
            if _RUNTIME_DIPLOMACY_FAILURE_RE.fullmatch(entry[1]) is not None
        ]
        if diplomacy_enabled is True:
            diplomacy_ok = (
                diplomacy_feature_events == [
                    (diplomacy_feature_events[0][0], "active")
                ]
                if diplomacy_feature_events
                else False
            )
            diplomacy_ok = (
                diplomacy_ok
                and len(diplomacy_activation_events) == 1
                and not diplomacy_failure_events
            )
        else:
            diplomacy_ok = (
                len(diplomacy_feature_events) == 1
                and diplomacy_feature_events[0][1] == "inactive"
                and not diplomacy_runtime_events
            )
        checks.append(
            _check(
                "runtime.companion_diplomacy",
                isinstance(diplomacy_enabled, bool) and diplomacy_ok,
                f"selected={diplomacy_enabled!r} "
                + json.dumps(
                    {
                        "feature": diplomacy_feature_events,
                        "activation": diplomacy_activation_events,
                        "failures": diplomacy_failure_events,
                        "runtime_event_count": len(diplomacy_runtime_events),
                    },
                    sort_keys=True,
                ),
            )
        )
        fortification_failure_events = sorted(
            (line_number, event)
            for event, line_numbers in runtime_event_lines.items()
            if _RUNTIME_FORTIFICATIONS_FAILURE_RE.fullmatch(event) is not None
            for line_number in line_numbers
        )
        fortification_activity_events = sorted(
            (line_number, event)
            for event, line_numbers in runtime_event_lines.items()
            if (
                _RUNTIME_FORTIFICATION_SCOPE_RE.fullmatch(event) is not None
                or _RUNTIME_FORTIFICATION_SELECTION_RE.fullmatch(event)
                is not None
                or _RUNTIME_FORTIFICATION_PLACED_RE.fullmatch(event)
                is not None
            )
            for line_number in line_numbers
        )
        if fortifications_enabled is True:
            fortifications_ok = (
                event_counts[RUNTIME_FORTIFICATIONS_ACTIVE] == 1
                and event_counts[RUNTIME_FORTIFICATIONS_CORE_ACTIVE] == 1
                and event_counts[RUNTIME_FORTIFICATIONS_INACTIVE] == 0
                and not fortification_failure_events
            )
        else:
            fortifications_ok = (
                event_counts[RUNTIME_FORTIFICATIONS_INACTIVE] == 1
                and event_counts[RUNTIME_FORTIFICATIONS_ACTIVE] == 0
                and event_counts[RUNTIME_FORTIFICATIONS_CORE_ACTIVE] == 0
                and not fortification_failure_events
                and not fortification_activity_events
            )
        checks.append(
            _check(
                "runtime.companion_fortifications",
                isinstance(fortifications_enabled, bool)
                and fortifications_ok,
                f"selected={fortifications_enabled!r} "
                + json.dumps(
                    {
                        "active": event_counts[
                            RUNTIME_FORTIFICATIONS_ACTIVE
                        ],
                        "core_active": event_counts[
                            RUNTIME_FORTIFICATIONS_CORE_ACTIVE
                        ],
                        "inactive": event_counts[
                            RUNTIME_FORTIFICATIONS_INACTIVE
                        ],
                        "failures": fortification_failure_events,
                        "activity": fortification_activity_events,
                    },
                    sort_keys=True,
                ),
            )
        )
        dock_summary_events = [
            (
                line_number,
                int(match.group(1)),
                int(match.group(2)),
                int(match.group(3)),
            )
            for event, line_numbers in runtime_event_lines.items()
            for match in [_RUNTIME_DOCK_SUMMARY_RE.fullmatch(event)]
            if match is not None
            for line_number in line_numbers
        ]
        dock_enforce_events = [
            (
                line_number,
                int(match.group(1)),
                int(match.group(2)),
                int(match.group(3)),
            )
            for event, line_numbers in runtime_event_lines.items()
            for match in [_RUNTIME_DOCK_ENFORCE_ACTIVE_RE.fullmatch(event)]
            if match is not None
            for line_number in line_numbers
        ]
        dock_rule_values = (
            tuple(
                dock_rules.get(key)
                for key in ("wood_cost", "gold_cost", "health")
            )
            if dock_rules is not None
            else None
        )
        dock_rule_values_ok = dock_rule_values is not None and all(
            isinstance(value, int) and not isinstance(value, bool)
            for value in dock_rule_values
        )
        if dock_enabled is True and dock_rules is not None:
            # Rule mode: the one active line must say mode=enforce and carry
            # exactly the three values the DLL metadata promised.  A measure
            # line here would mean the shipped rules never armed.
            dock_ok = (
                dock_rule_values_ok
                and len(dock_enforce_events) == 1
                and dock_enforce_events[0][1:] == dock_rule_values
                and event_counts[RUNTIME_DOCK_PLACEMENT_ACTIVE] == 0
                and event_counts[RUNTIME_DOCK_PLACEMENT_INACTIVE] == 0
                and event_counts[RUNTIME_DOCK_PLACEMENT_FAILED] == 0
            )
        elif dock_enabled is True:
            # Measurement mode: mode=measure, no enforce line, and every
            # summary must report blocked=0 - a measuring build that blocked
            # a tile would be lying about itself.
            dock_ok = (
                event_counts[RUNTIME_DOCK_PLACEMENT_ACTIVE] == 1
                and not dock_enforce_events
                and event_counts[RUNTIME_DOCK_PLACEMENT_INACTIVE] == 0
                and event_counts[RUNTIME_DOCK_PLACEMENT_FAILED] == 0
                and all(entry[3] == 0 for entry in dock_summary_events)
            )
        else:
            # A lane that was not selected must leave no trace beyond its one
            # inactive line - a summary without a selection would mean the
            # measurement ran in a build that never asked for it.
            dock_ok = (
                event_counts[RUNTIME_DOCK_PLACEMENT_INACTIVE] == 1
                and event_counts[RUNTIME_DOCK_PLACEMENT_ACTIVE] == 0
                and not dock_enforce_events
                and event_counts[RUNTIME_DOCK_PLACEMENT_FAILED] == 0
                and not dock_summary_events
            )
        checks.append(
            _check(
                "runtime.companion_dock_placement",
                isinstance(dock_enabled, bool) and dock_ok,
                f"selected={dock_enabled} "
                + json.dumps(
                    {
                        "active": event_counts[RUNTIME_DOCK_PLACEMENT_ACTIVE],
                        "enforce": dock_enforce_events,
                        "rules": dock_rules,
                        "inactive": event_counts[RUNTIME_DOCK_PLACEMENT_INACTIVE],
                        "failed": event_counts[RUNTIME_DOCK_PLACEMENT_FAILED],
                        "summary": dock_summary_events,
                    },
                    sort_keys=True,
                ),
            )
        )
        # The streamed group owns its Foliage material directly.  The legacy
        # eager tree_apple mutation is intentionally inactive in that mode.
        expect_foliage_success = (
            foliage_requested is True and not asset_stream_enabled
        )
        expected_foliage_event = (
            RUNTIME_FOLIAGE_SUCCEEDED
            if expect_foliage_success
            else RUNTIME_FOLIAGE_INACTIVE
        )
        unexpected_foliage_event = (
            RUNTIME_FOLIAGE_INACTIVE
            if expect_foliage_success
            else RUNTIME_FOLIAGE_SUCCEEDED
        )
        checks.append(
            _check(
                "runtime.companion_foliage_state",
                isinstance(foliage_requested, bool)
                and event_counts[expected_foliage_event] == 1
                and event_counts[unexpected_foliage_event] == 0
                and event_counts[RUNTIME_FOLIAGE_FAILED] == 0,
                f"expected={expected_foliage_event} counts="
                + json.dumps(
                    {
                        "success": event_counts[RUNTIME_FOLIAGE_SUCCEEDED],
                        "inactive": event_counts[RUNTIME_FOLIAGE_INACTIVE],
                        "failed": event_counts[RUNTIME_FOLIAGE_FAILED],
                    },
                    sort_keys=True,
                ),
            )
        )
        initialized_lines = runtime_event_lines.get(RUNTIME_INITIALIZED, [])
        audio_terminal_lines = runtime_event_lines.get(expected_audio_event, [])
        foliage_terminal_lines = runtime_event_lines.get(
            expected_foliage_event,
            [],
        )
        event_order_ok = (
            isinstance(audio_payload, bool)
            and isinstance(foliage_requested, bool)
            and len(initialized_lines) == 1
            and len(audio_terminal_lines) == 1
            and len(foliage_terminal_lines) == 1
            and audio_terminal_lines[0] < initialized_lines[0]
            and (
                initialized_lines[0] < foliage_terminal_lines[0]
                if expect_foliage_success
                else foliage_terminal_lines[0] < initialized_lines[0]
            )
        )
        checks.append(
            _check(
                "runtime.companion_event_order",
                event_order_ok,
                f"audio={audio_terminal_lines} initialized={initialized_lines} "
                f"foliage={foliage_terminal_lines} "
                f"foliage_async={expect_foliage_success}",
            )
        )
        failed_contract_events = {
            event: events.count(event)
            for event in set(events)
            if _runtime_event_requires_error(event)
        }
        checks.append(
            _check(
                "runtime.companion_no_failed_closed",
                not failed_contract_events,
                json.dumps(failed_contract_events, sort_keys=True),
            )
        )

        roster_inactive_lines = runtime_event_lines.get(
            RUNTIME_ROSTER_INACTIVE, []
        )
        roster_monitor_lines = runtime_event_lines.get(
            RUNTIME_ROSTER_MONITOR_HEALTHY, []
        )
        active_digest = (
            parsed_roster_contract.get("entries_sha256")
            if parsed_roster_contract is not None
            else None
        )
        ui_generations = [generation for _, generation in roster_ui_events]
        if roster_enabled is True:
            roster_state_ok = (
                parsed_roster_contract is not None
                and len(roster_active_events) == 1
                and roster_active_events[0][1] == active_digest
                and not roster_inactive_lines
            )
            roster_hud_ok = (
                bool(roster_ui_events)
                and ui_generations
                == list(range(1, len(roster_ui_events) + 1))
            )
            roster_monitor_ok = len(roster_monitor_lines) == 1
            roster_cleanup_ok = (
                len(roster_cleanup_events) == 1
                and roster_cleanup_events[0][1:]
                == (64, 17, "application_quit")
            )
            roster_no_failures_ok = not roster_failure_events
            active_line = (
                roster_active_events[0][0]
                if len(roster_active_events) == 1
                else None
            )
            monitor_line = (
                roster_monitor_lines[0]
                if len(roster_monitor_lines) == 1
                else None
            )
            cleanup_line = (
                roster_cleanup_events[0][0]
                if len(roster_cleanup_events) == 1
                else None
            )
            initialized_line = (
                initialized_lines[0]
                if len(initialized_lines) == 1
                else None
            )
            roster_ready_line = (
                max(active_line, initialized_line)
                if active_line is not None and initialized_line is not None
                else None
            )
            roster_order_ok = (
                roster_ready_line is not None
                and monitor_line is not None
                and cleanup_line is not None
                and bool(roster_ui_events)
                and roster_ready_line < roster_ui_events[0][0] < monitor_line
                and all(
                    roster_ready_line < line_number < cleanup_line
                    for line_number, _ in roster_ui_events
                )
                and monitor_line < cleanup_line
                and not roster_failure_events
            )
        elif roster_enabled is False:
            roster_state_ok = (
                len(roster_inactive_lines) == 1
                and not roster_active_events
            )
            roster_hud_ok = not roster_ui_events
            roster_monitor_ok = not roster_monitor_lines
            roster_cleanup_ok = not roster_cleanup_events
            roster_no_failures_ok = not roster_failure_events
            roster_order_ok = (
                len(roster_inactive_lines) == 1
                and len(initialized_lines) == 1
                and roster_inactive_lines[0] < initialized_lines[0]
            )
        else:
            roster_state_ok = False
            roster_hud_ok = False
            roster_monitor_ok = False
            roster_cleanup_ok = False
            roster_no_failures_ok = False
            roster_order_ok = False

        checks.extend(
            (
                _check(
                    "runtime.companion_roster_state",
                    roster_state_ok,
                    f"selected={roster_enabled} inactive={roster_inactive_lines} "
                    f"active={roster_active_events} digest={active_digest}",
                ),
                _check(
                    "runtime.companion_roster_hud",
                    roster_hud_ok,
                    f"selected={roster_enabled} ui={roster_ui_events}",
                ),
                _check(
                    "runtime.companion_roster_monitor",
                    roster_monitor_ok,
                    f"selected={roster_enabled} healthy={roster_monitor_lines}",
                ),
                _check(
                    "runtime.companion_roster_cleanup",
                    roster_cleanup_ok,
                    f"selected={roster_enabled} cleanup={roster_cleanup_events}",
                ),
                _check(
                    "runtime.companion_roster_no_failures",
                    roster_no_failures_ok,
                    json.dumps(roster_failure_events),
                ),
                _check(
                    "runtime.companion_roster_order",
                    roster_order_ok,
                    f"active={roster_active_events} ui={roster_ui_events} "
                    f"healthy={roster_monitor_lines} cleanup={roster_cleanup_events} "
                    f"initialized={initialized_lines}",
                ),
            )
        )

    normalized_destination = str(destination).replace("\\", "/").casefold()
    replaced_events: list[tuple[int, int]] = []
    malformed_replaced_lines: list[int] = []
    for line_number, line in enumerate(lines, start=1):
        match = _REPLACED_RE.fullmatch(line)
        if match is not None:
            count = _bounded_log_int(match.group(1), 1_000_000)
            if count is None:
                malformed_replaced_lines.append(line_number)
            else:
                replaced_events.append((line_number, count))
        elif (
            "[GameSpriteManagerAPI] [ApplyRuntimeOverrides] Replaced " in line
            and line.startswith("[Info   :  SHCDE-SE]")
        ):
            malformed_replaced_lines.append(line_number)
    replacement_event_ok = (
        len(replaced_events) == 1 and not malformed_replaced_lines
    )
    replacement_line = replaced_events[0][0] if len(replaced_events) == 1 else None
    actual_replaced = replaced_events[0][1] if len(replaced_events) == 1 else None
    pre_replacement_lines = (
        lines[: replacement_line - 1] if replacement_line is not None else []
    )
    trace = _provider_trace(pre_replacement_lines)
    future_index_lines = [
        line_number
        for line_number, line in enumerate(lines, start=1)
        if replacement_line is not None
        and line_number > replacement_line
        and (
            _PROVIDER_RE.fullmatch(line) is not None
            or _INDEX_RE.fullmatch(line) is not None
            or line.startswith(_PROVIDER_EVENT_PREFIX)
            or line.startswith(_INDEX_EVENT_PREFIX)
        )
    ]
    checks.append(
        _check(
            "runtime.no_provider_index_after_replaced",
            replacement_event_ok and not future_index_lines,
            f"replaced={replaced_events} malformed={malformed_replaced_lines} "
            f"future={future_index_lines}",
        )
    )
    checks.append(
        _check(
            "runtime.provider_trace_schema",
            not trace.errors,
            json.dumps(trace.errors),
        )
    )

    loaded_mod_events = [
        (line_number, match.group(1))
        for line_number, line in enumerate(lines, start=1)
        if (match := _MOD_LOAD_RE.fullmatch(line)) is not None
    ]

    def owner_label(owner: int | None) -> str | None:
        return trace.sessions[owner].label if owner is not None else None

    guid_key = guid.casefold()
    expected_provider_root = _root_key(destination / "Override")
    guid_sessions = [
        index
        for index, session in enumerate(trace.sessions)
        if session.guid_key == guid_key
    ]
    exact_provider_sessions = [
        index
        for index in guid_sessions
        if trace.sessions[index].root_key == expected_provider_root
    ]
    provider_instance_ok = (
        len(guid_sessions) == 1 and len(exact_provider_sessions) == 1
    )
    europe_session = (
        exact_provider_sessions[0]
        if len(exact_provider_sessions) == 1
        else None
    )
    matching_load_events = [
        (line_number, root)
        for line_number, root in loaded_mod_events
        if _root_key(root) == _root_key(destination)
    ]
    own_provider_line = (
        trace.sessions[europe_session].line_number
        if europe_session is not None
        else None
    )
    mod_load_ok = (
        len(matching_load_events) == 1
        and own_provider_line is not None
        and matching_load_events[0][0] < own_provider_line
    )
    checks.append(
        _check(
            "runtime.mod_loaded",
            mod_load_ok,
            f"expected={destination} loads={matching_load_events} "
            f"provider_line={own_provider_line}",
        )
    )
    checks.append(
        _check(
            "runtime.provider_registered",
            provider_instance_ok,
            f"expected={guid}@{destination / 'Override'} actual="
            + json.dumps(
                [trace.sessions[index].label for index in guid_sessions],
                sort_keys=True,
            ),
        )
    )
    expected_assets = {
        relative.removeprefix("Override/")
        for relative in install.get("files", {})
        if relative.startswith("Override/")
    }
    expected_asset_by_key = {
        _asset_key(asset): asset for asset in expected_assets
    }
    expected_asset_keys = set(expected_asset_by_key)
    indexed_assets = (
        set(trace.sessions[europe_session].assets)
        if europe_session is not None
        else set()
    )
    missing_asset_keys = expected_asset_keys - indexed_assets
    extra_asset_keys = indexed_assets - expected_asset_keys
    checks.append(
        _check(
            "runtime.provider_complete_index",
            provider_instance_ok
            and len(expected_asset_by_key) == len(expected_assets)
            and indexed_assets == expected_asset_keys,
            f"expected={len(expected_assets)} indexed={len(indexed_assets)} "
            f"missing={sorted(expected_asset_by_key[key] for key in missing_asset_keys)} "
            f"extra={sorted(extra_asset_keys)}",
        )
    )

    conflicts: dict[str, list[str]] = {}
    for asset_key, asset in expected_asset_by_key.items():
        owner_indexes = [
            index
            for index, session in enumerate(trace.sessions)
            if asset_key in session.assets
        ]
        if europe_session is None or owner_indexes != [europe_session]:
            conflicts[asset] = [
                trace.sessions[index].label for index in owner_indexes
            ]
    checks.append(
        _check(
            "runtime.no_provider_conflicts",
            not conflicts,
            json.dumps(conflicts, sort_keys=True),
        )
    )

    if roster_enabled is True:
        xaml_conflicts: dict[str, dict[str, object]] = {}
        expected_owner_root = _root_key(
            destination.parent / "000shcdese" / "Override"
        )
        for logical_path in _ROSTER_XAML_LOGICAL_PATHS:
            asset_key = _asset_key(logical_path)
            owners = [
                index
                for index, session in enumerate(trace.sessions)
                if asset_key in session.assets
            ]
            final_owner = trace.final_file_index.get(asset_key)
            exact_display = (
                len(owners) == 1
                and trace.sessions[owners[0]].assets.get(asset_key)
                == logical_path
            )
            exact_root = (
                len(owners) == 1
                and trace.sessions[owners[0]].root_key == expected_owner_root
            )
            exact_guid = (
                len(owners) == 1
                and trace.sessions[owners[0]].guid == "000shcdese"
            )
            if (
                len(owners) != 1
                or final_owner != owners[0]
                or not exact_display
                or not exact_root
                or not exact_guid
            ):
                xaml_conflicts[logical_path] = {
                    "owners": [owner_label(owner) for owner in owners],
                    "final": owner_label(final_owner),
                    "exact_display": exact_display,
                    "exact_root": exact_root,
                    "exact_guid": exact_guid,
                }
        checks.append(
            _check(
                "runtime.companion_roster_xaml_provider",
                not xaml_conflicts,
                json.dumps(xaml_conflicts, sort_keys=True),
            )
        )
        xaml_patch_events = [
            {
                "line": line_number,
                "logical_path": match.group(1),
                "patch_path": match.group(2),
            }
            for line_number, line in enumerate(lines, start=1)
            if (match := _XAML_PATCH_RE.fullmatch(line)) is not None
            and _asset_key(match.group(1))
            in {_asset_key(path) for path in _ROSTER_XAML_LOGICAL_PATHS}
        ]
        xaml_logical_keys = {
            _asset_key(path) for path in _ROSTER_XAML_LOGICAL_PATHS
        }
        malformed_xaml_patch_events = [
            {"line": line_number, "text": line[:512]}
            for line_number, line in enumerate(lines, start=1)
            if line.startswith(_XAML_PATCH_EVENT_PREFIX)
            and _XAML_PATCH_RE.fullmatch(line) is None
            and any(key in _asset_key(line) for key in xaml_logical_keys)
        ]
        checks.append(
            _check(
                "runtime.companion_roster_xaml_unpatched",
                fortifications_enabled is True
                or (not xaml_patch_events and not malformed_xaml_patch_events),
                json.dumps(
                    {
                        "parsed": xaml_patch_events,
                        "malformed": malformed_xaml_patch_events,
                    },
                    sort_keys=True,
                ),
            )
        )

    if fortifications_enabled is True:
        roster_xaml_keys = {
            _asset_key(path) for path in _ROSTER_XAML_LOGICAL_PATHS
        }
        fortification_patch_events = [
            {
                "line": line_number,
                "logical_path": match.group(1),
                "patch_path": match.group(2),
            }
            for line_number, line in enumerate(lines, start=1)
            if (match := _XAML_PATCH_RE.fullmatch(line)) is not None
            and _asset_key(match.group(1)) in roster_xaml_keys
        ]
        malformed_fortification_patch_events = [
            {"line": line_number, "text": line[:512]}
            for line_number, line in enumerate(lines, start=1)
            if line.startswith(_XAML_PATCH_EVENT_PREFIX)
            and _XAML_PATCH_RE.fullmatch(line) is None
            and any(key in _asset_key(line) for key in roster_xaml_keys)
        ]
        expected_logical = "Assets/GUI/XAMLResources/HUD_Main.xaml"
        expected_patch = _root_key(
            destination / Path(_FORTIFICATION_HUD_PATCH_RELATIVE)
        )
        exact_owned_event = (
            len(fortification_patch_events) == 1
            and _asset_key(
                str(fortification_patch_events[0]["logical_path"])
            )
            == _asset_key(expected_logical)
            and _root_key(
                Path(str(fortification_patch_events[0]["patch_path"]))
            )
            == expected_patch
        )
        patch_manifest_entry = output_by_path.get(
            _FORTIFICATION_HUD_PATCH_RELATIVE
        )
        exact_manifest_entry = (
            isinstance(patch_manifest_entry, dict)
            and patch_manifest_entry.get("category") == "xaml_patch"
            and patch_manifest_entry.get("source_reference")
            == (
                "project-file:assets/xaml/HUD_Main.xaml"
                if dock_enabled is True
                else (
                    "project-file:assets/xaml/"
                    "HUD_Main.fortifications.xaml"
                )
            )
        )
        checks.append(
            _check(
                "runtime.companion_fortifications_xaml_owned",
                exact_owned_event
                and not malformed_fortification_patch_events
                and exact_manifest_entry,
                json.dumps(
                    {
                        "parsed": fortification_patch_events,
                        "malformed": malformed_fortification_patch_events,
                        "manifest": patch_manifest_entry,
                    },
                    sort_keys=True,
                ),
            )
        )

    if runtime_declared and isinstance(audio_payload, bool):
        legacy_audio_payload = audio_payload and not pcm_streaming_enabled
        audio_provider_key = _RUNTIME_AUDIO_PROVIDER_ID.casefold()
        audio_session_indexes = [
            index
            for index, session in enumerate(trace.sessions)
            if session.guid_key == audio_provider_key
        ]
        expected_audio_root = _root_key(
            destination / "Override" / "Sounds" / "Music"
        )
        exact_audio_session_indexes = [
            index
            for index in audio_session_indexes
            if trace.sessions[index].root_key == expected_audio_root
        ]
        audio_provider_registered = (
            len(audio_session_indexes) == 1
            and len(exact_audio_session_indexes) == 1
        )
        audio_session = (
            exact_audio_session_indexes[0]
            if len(exact_audio_session_indexes) == 1
            else None
        )
        audio_provider_assets = (
            set(trace.sessions[audio_session].assets)
            if audio_session is not None
            else set()
        )
        expected_audio_keys = {_asset_key(name) for name in expected_audio_files}
        audio_conflicts: dict[str, dict[str, object]] = {}
        for key in sorted(expected_audio_keys):
            owners = [
                index
                for index, session in enumerate(trace.sessions)
                if key in session.assets
            ]
            final_owner = trace.final_file_index.get(key)
            if (
                audio_session is None
                or owners != [audio_session]
                or final_owner != audio_session
            ):
                audio_conflicts[key] = {
                    "owners": [owner_label(owner) for owner in owners],
                    "final": owner_label(final_owner),
                }
        audio_provider_ok = (
            audio_provider_registered
            and audio_provider_assets == expected_audio_keys
            and not audio_conflicts
            if legacy_audio_payload
            else not audio_session_indexes
        )
        checks.append(
            _check(
                "runtime.companion_audio_provider",
                audio_provider_ok,
                f"requested={legacy_audio_payload} pcm={pcm_streaming_enabled} "
                f"registered={audio_provider_registered} "
                f"expected_root={destination / 'Override' / 'Sounds' / 'Music'} "
                "actual_sessions="
                + json.dumps(
                    [trace.sessions[index].label for index in audio_session_indexes],
                    sort_keys=True,
                )
                + " "
                f"expected={len(expected_audio_files)} indexed={len(audio_provider_assets)} "
                f"missing={sorted(expected_audio_keys-audio_provider_assets)} "
                f"extra={sorted(audio_provider_assets-expected_audio_keys)} "
                f"conflicts={json.dumps(audio_conflicts, sort_keys=True)}",
            )
        )
        if legacy_audio_payload:
            loaded_audio_events = [
                (line_number, match.group(1))
                for line_number, line in enumerate(lines, start=1)
                if (match := _AUDIO_LOAD_RE.fullmatch(line)) is not None
            ]
            loaded_audio = {name for _, name in loaded_audio_events}
            loaded_audio_keys = {_asset_key(name) for name in loaded_audio}
            unexpected_europe_audio = {
                name
                for name in loaded_audio
                if _asset_key(name).startswith("eu_")
                and _asset_key(name) not in expected_audio_keys
            }
            checks.append(
                _check(
                    "runtime.companion_audio_frontend_decode",
                    _asset_key(_FRONTEND_AUDIO_CANARY) in loaded_audio_keys
                    and not unexpected_europe_audio,
                    f"required={_FRONTEND_AUDIO_CANARY} "
                    f"loaded={sorted(loaded_audio)} "
                    f"unexpected_europe={sorted(unexpected_europe_audio)}",
                )
            )
            aux_complete_line = (
                max(
                    [trace.sessions[audio_session].line_number]
                    + list(trace.sessions[audio_session].asset_lines.values())
                )
                if audio_session is not None
                else None
            )
            active_lines = runtime_event_lines.get(RUNTIME_AUDIO_ACTIVE, [])
            europe_decode_lines = [
                line_number
                for line_number, name in loaded_audio_events
                if _asset_key(name) in expected_audio_keys
            ]
            audio_order_ok = (
                audio_provider_ok
                and aux_complete_line is not None
                and len(active_lines) == 1
                and aux_complete_line < active_lines[0]
                and bool(europe_decode_lines)
                and all(
                    aux_complete_line < line_number
                    for line_number in europe_decode_lines
                )
            )
            checks.append(
                _check(
                    "runtime.companion_audio_order",
                    audio_order_ok,
                    f"aux_complete={aux_complete_line} active={active_lines} "
                    f"decode={europe_decode_lines}",
                )
            )
        elif pcm_streaming_enabled:
            legacy_audio_loads = [
                (line_number, match.group(1))
                for line_number, line in enumerate(lines, start=1)
                if (match := _AUDIO_LOAD_RE.fullmatch(line)) is not None
            ]
            checks.append(
                _check(
                    "runtime.pcm_no_legacy_audio_load",
                    not legacy_audio_loads,
                    json.dumps(legacy_audio_loads),
                )
            )

    europe_individual_sprites = {
        asset_key
        for asset_key in expected_asset_keys
        if asset_key.startswith("sprites/")
        and asset_key.endswith(".png")
        and not asset_key.endswith("_m.png")
    }
    global_final_individual_sprites = {
        asset_key
        for asset_key in trace.final_file_index
        if asset_key.startswith("sprites/")
        and asset_key.endswith(".png")
        and not asset_key.endswith("_m.png")
    }
    europe_final_ownership_ok = (
        europe_session is not None
        and all(
            trace.final_file_index.get(asset_key) == europe_session
            for asset_key in europe_individual_sprites
        )
    )
    sprite_count_ok = (
        replacement_event_ok
        and not future_index_lines
        and europe_final_ownership_ok
        and actual_replaced == len(global_final_individual_sprites)
    )
    checks.append(
        _check(
            "runtime.individual_sprite_count",
            sprite_count_ok,
            f"europe={len(europe_individual_sprites)} "
            f"global_final={len(global_final_individual_sprites)} "
            f"europe_final_owner={europe_final_ownership_ok} "
            f"events={replaced_events} malformed={malformed_replaced_lines} "
            f"actual={actual_replaced}",
        )
    )

    atlas_layout_check, atlas_groups = _atlas_layout(installed_files)
    checks.append(atlas_layout_check)
    applied: dict[str, list[dict[str, object]]] = {}
    apply_all_events: list[dict[str, int]] = []
    malformed_atlas_log_lines: list[int] = []
    for line_number, line in enumerate(lines, start=1):
        apply_all_match = _APPLY_ALL_RE.fullmatch(line)
        if apply_all_match is not None:
            count = _bounded_log_int(apply_all_match.group(1), 10_000)
            if count is None:
                malformed_atlas_log_lines.append(line_number)
            else:
                apply_all_events.append(
                    {
                        "count": count,
                        "line_number": line_number,
                    }
                )
        match = _APPLIED_RE.fullmatch(line)
        if match is None:
            if (
                line.startswith("[Info   :  SHCDE-SE]")
                and (
                    "[GameAtlasManagerAPI] [ApplyAll] Applying " in line
                    or "[GameAtlasManagerAPI] [ApplySingle] Applied " in line
                )
                and apply_all_match is None
            ):
                malformed_atlas_log_lines.append(line_number)
            continue
        frames = _bounded_log_int(match.group(2), 1_000_000, minimum=1)
        array_size = _bounded_log_int(match.group(4), 1_000_000, minimum=1)
        if (
            frames is None
            or array_size is None
            or not match.group(1)
            or len(match.group(1)) > 128
        ):
            malformed_atlas_log_lines.append(line_number)
            continue
        applied.setdefault(match.group(1).casefold(), []).append(
            {
                "group": match.group(1),
                "frames": frames,
                "mask": match.group(3),
                "array_size": array_size,
                "line_number": line_number,
            }
        )

    expected_group_keys = {group.casefold() for group in atlas_groups}
    registered_group_keys = {
        registration.group_key for registration in trace.registrations
    }
    discovered_group_keys = {
        discovery.group_key for discovery in trace.discoveries
    }
    applied_group_keys = set(applied)
    apply_event_lines = sorted(
        int(event["line_number"])
        for events in applied.values()
        for event in events
    )
    latest_discovery_line = max(
        (discovery.line_number for discovery in trace.discoveries),
        default=None,
    )
    apply_all = apply_all_events[0] if len(apply_all_events) == 1 else None
    apply_all_line = int(apply_all["line_number"]) if apply_all is not None else None
    apply_all_order_ok = (
        apply_all_line is not None
        and replacement_line is not None
        and (
            latest_discovery_line is None
            or apply_all_line > latest_discovery_line
        )
        and all(apply_all_line < line_number for line_number in apply_event_lines)
        and apply_all_line < replacement_line
        and all(line_number < replacement_line for line_number in apply_event_lines)
    )
    global_group_sets_ok = (
        registered_group_keys == discovered_group_keys == applied_group_keys
    )
    paired_registration_indexes = [
        discovery.paired_registration for discovery in trace.discoveries
    ]
    registration_discovery_pairing_ok = (
        len(trace.registrations) == len(trace.discoveries)
        and all(index is not None for index in paired_registration_indexes)
        and set(paired_registration_indexes) == set(range(len(trace.registrations)))
    )
    discovery_trigger_mismatches = [
        {
            "group": discovery.group,
            "line_number": discovery.line_number,
            "trigger_root": discovery.trigger_root,
            "trigger_session": discovery.trigger_session,
            "session_root": (
                trace.sessions[discovery.trigger_session].root
                if discovery.trigger_session is not None
                else None
            ),
        }
        for discovery in trace.discoveries
        if discovery.trigger_session is None
        or _root_key(discovery.trigger_root)
        != trace.sessions[discovery.trigger_session].root_key
    ]
    each_group_applied_once = all(
        len(events) == 1 for events in applied.values()
    )
    global_atlas_activity = bool(
        trace.registrations or trace.discoveries or apply_event_lines
    )
    if global_atlas_activity:
        apply_all_ok = (
            apply_all is not None
            and int(apply_all["count"]) == len(applied_group_keys)
            and global_group_sets_ok
            and registration_discovery_pairing_ok
            and not discovery_trigger_mismatches
            and each_group_applied_once
            and expected_group_keys <= applied_group_keys
            and apply_all_order_ok
            and not malformed_atlas_log_lines
        )
    else:
        apply_all_ok = not apply_all_events and not malformed_atlas_log_lines
    checks.append(
        _check(
            "runtime.atlas_apply_all",
            apply_all_ok,
            f"global_activity={global_atlas_activity} "
            f"events={apply_all_events} "
            f"europe_groups={sorted(expected_group_keys)} "
            f"registered_groups={sorted(registered_group_keys)} "
            f"discovered_groups={sorted(discovered_group_keys)} "
            f"applied_groups={sorted(applied_group_keys)} "
            f"paired_registrations={paired_registration_indexes} "
            f"registration_count={len(trace.registrations)} "
            f"discovery_count={len(trace.discoveries)} "
            "trigger_mismatches="
            f"{json.dumps(discovery_trigger_mismatches, sort_keys=True)} "
            f"latest_discovery_line={latest_discovery_line} "
            f"apply_lines={apply_event_lines} replacement_line={replacement_line} "
            f"malformed={malformed_atlas_log_lines}",
        )
    )

    foliage_success_lines = runtime_event_lines.get(RUNTIME_FOLIAGE_SUCCEEDED, [])
    tree_apply_lines = [
        int(event["line_number"])
        for event in applied.get("tree_apple", [])
    ]
    foliage_order_ok = (
        not foliage_success_lines
        or (
            len(foliage_success_lines) == 1
            and len(tree_apply_lines) == 1
            and tree_apply_lines[0] < foliage_success_lines[0]
        )
    )
    checks.append(
        _check(
            "runtime.companion_foliage_order",
            foliage_order_ok,
            f"tree_apply={tree_apply_lines} success={foliage_success_lines}",
        )
    )

    for group in atlas_groups:
        group_key = group.casefold()
        (
            atlas_file_checks,
            expected_frames,
            expected_mask,
            expected_array_size,
        ) = _installed_atlas_contract(
            destination,
            group,
            installed_files,
            output_by_path,
        )
        checks.extend(atlas_file_checks)
        manifest_contract_ok = (
            all(check.ok for check in atlas_file_checks)
            and expected_frames is not None
            and expected_array_size is not None
        )

        registrations = [
            (index, registration)
            for index, registration in enumerate(trace.registrations)
            if registration.group_key == group_key
        ]
        discoveries = [
            discovery
            for discovery in trace.discoveries
            if discovery.group_key == group_key
        ]
        paired_registrations = {
            discovery.paired_registration
            for discovery in discoveries
            if discovery.paired_registration is not None
        }
        registration_indexes = {index for index, _ in registrations}
        loader_group = LOADER_GROUP_TABLE.get(group)
        expected_gm_enum = loader_group.gm_enum if loader_group is not None else None
        registered_gm_enums = [
            registration.gm_enum for _, registration in registrations
        ]
        registration_contract_ok = (
            bool(discoveries)
            and expected_gm_enum is not None
            and len(registrations) == len(discoveries)
            and all(
                discovery.paired_registration is not None
                for discovery in discoveries
            )
            and paired_registrations == registration_indexes
            and all(
                registration.gm_enum == expected_gm_enum
                for _, registration in registrations
            )
            and all(
                discovery.trigger_session is not None
                and trace.sessions[discovery.trigger_session].root_key
                == _root_key(discovery.trigger_root)
                for discovery in discoveries
            )
        )
        checks.append(
            _check(
                f"runtime.atlas_registration.{group}",
                registration_contract_ok,
                f"registrations={[item.line_number for _, item in registrations]} "
                f"expected_gm_enum={expected_gm_enum!r} "
                f"registered_gm_enums={registered_gm_enums!r} "
                f"discoveries={[item.line_number for item in discoveries]} "
                f"paired={sorted(paired_registrations)}",
            )
        )

        component_keys = _atlas_component_keys(group)
        required_owners = {
            "json": europe_session,
            "main": europe_session,
            "mask": europe_session if expected_mask == "yes" else None,
        }
        discovery_details: list[dict[str, object]] = []
        discovery_owners_ok = True
        for discovery in discoveries:
            actual_owners = {
                component: discovery.component_owners.get(component)
                for component in component_keys
            }
            if actual_owners != required_owners:
                discovery_owners_ok = False
            discovery_details.append(
                {
                    "line": discovery.line_number,
                    # This is deliberately diagnostic only. In SHCDE-SE 1.39
                    # it names the provider that triggered the global rescan.
                    "trigger_root": discovery.trigger_root,
                    "trigger_provider": owner_label(discovery.trigger_session),
                    "owners": {
                        component: owner_label(owner)
                        for component, owner in actual_owners.items()
                    },
                }
            )
        final_owners = {
            component: trace.final_file_index.get(asset_key)
            for component, asset_key in component_keys.items()
        }
        provenance_ok = (
            provider_instance_ok
            and europe_session is not None
            and bool(discoveries)
            and discovery_owners_ok
            and final_owners == required_owners
        )
        checks.append(
            _check(
                f"runtime.atlas_provider_provenance.{group}",
                provenance_ok,
                json.dumps(
                    {
                        "expected": {
                            component: owner_label(owner)
                            for component, owner in required_owners.items()
                        },
                        "discoveries": discovery_details,
                        "final": {
                            component: owner_label(owner)
                            for component, owner in final_owners.items()
                        },
                    },
                    sort_keys=True,
                ),
            )
        )

        actual_events = applied.get(group_key, [])
        actual = actual_events[0] if len(actual_events) == 1 else None
        latest_discovery_line = max(
            (discovery.line_number for discovery in discoveries),
            default=None,
        )
        apply_order_ok = (
            actual is not None
            and latest_discovery_line is not None
            and int(actual["line_number"]) > latest_discovery_line
        )
        checks.append(
            _check(
                f"runtime.atlas_applied.{group}",
                manifest_contract_ok
                and len(actual_events) == 1
                and actual is not None
                and actual["frames"] == expected_frames
                and actual["mask"] == expected_mask
                and actual["array_size"] == expected_array_size
                and apply_order_ok,
                f"expected_frames={expected_frames} expected_mask={expected_mask} "
                f"expected_array_size={expected_array_size} "
                f"latest_discovery_line={latest_discovery_line} "
                f"actual={actual_events}",
            )
        )

    ownership_tokens = {
        _normalized_log_text(guid),
        normalized_destination,
        "stronghold europe de runtime (private)",
        "strongholdeuropede.runtime",
        _normalized_log_text(RUNTIME_EVENT_PREFIX),
        *{
            _normalized_log_text(asset)
            for asset in expected_assets
        },
        *{
            _normalized_log_text(
                f"failed to apply atlas for [{group}]"
            )
            for group in atlas_groups
        },
    }
    ownership_tokens.discard("")
    related_errors = _related_mod_errors(lines, ownership_tokens)
    checks.append(
        _check(
            "runtime.no_mod_errors",
            not related_errors,
            " | ".join(related_errors[:10]),
        )
    )
    checks.append(
        _check(
            "runtime.build_profile",
            bool(build_manifest.get("profile_id")),
            str(build_manifest.get("profile_id")),
        )
    )
    return checks

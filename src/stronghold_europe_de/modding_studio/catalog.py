"""Versioned, descriptive (not executable) API/engine capability catalog."""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

from .safety import StudioError, require_id

API_RELEASE = "0.27.0"
API_COMMIT = "ee77e0d267c795cf7375863f6eac243fea8fe72c"
SERP_COMMIT = "e1b61a67fe673e4389c404646ae1e53155a64857"
MIN_SCRIPT_EXTENDER = "2.14.0"
NATIVE_BASELINE_SHA256 = (
    "fbcb93195fc7efca9bdac5204852efdd76f9818f59a6711750d77c9cef2831e2"
)
API_DOC_ROOT = "https://github.com/SHCDE-APIShared/APIShared/blob/" + API_COMMIT
BASELINE_DOC_ROOT = (
    "https://github.com/Serpens66/Stronghold-Crusader-DE-Mods/blob/"
    + SERP_COMMIT
)

# Each area is a usable offline tool. None implies an installed game hook.
MODULES: tuple[tuple[str, str, str], ...] = (
    ("sdk", "SDK- & Kompatibilitäts-Explorer", "API-Verträge, Versionsgates und Hook-Besitz"),
    ("mission", "Mission- & Trigger-Studio", "Deterministische Ereignispläne und Dry-Runs"),
    ("castle", "KI-Burgen-Designer", "100x100-AIV-Bauplätze und Kollisionsprüfung"),
    ("hud", "Noesis- & HUD-Designer", "XAML-Verweise, Ressourcen und Inventur"),
    ("balance", "Balancing-Studio", "Kosten, Limits und Preisregeln als Vorschau"),
    ("maps", "Karten- & Trail-Werkstatt", "Dateihashes, sichere externe Parser"),
    ("lords", "Custom-Lord-Studio", "Lord-Medien- und AIV-Abhängigkeiten"),
    ("units", "Einheiten- & Wegfindungslabor", "Offline-Route/Tile-Penalty-Simulator"),
    ("audio", "Audio- & Effekt-Studio", "WAV-Inspektion und Cue-Regeln"),
    ("saves", "Savegame- & Multiplayer-Labor", "Versionsstände und Peer-Digests"),
    ("workshop", "Modpack- & Workshop-Center", "GUID-/Dependency- und Paketrisiken"),
    ("native", "Native Engine Lab", "Hashgebundene RVA- und Hook-Konfliktprüfung"),
)
MODULE_IDS = tuple(module[0] for module in MODULES)
MODULE_DESCRIPTIONS = {id_: (title, description) for id_, title, description in MODULES}

@dataclass(frozen=True)
class Capability:
    key: str
    module: str
    name: str
    min_api: str
    threading: str
    mode: str
    source: str
    note: str

def _cap(
    key: str, module: str, name: str, min_api: str, threading: str,
    mode: str, source: str, note: str,
) -> Capability:
    return Capability(key, module, name, min_api, threading, mode, source, note)

CAPABILITIES: tuple[Capability, ...] = (
    _cap("mission_lifecycle", "mission", "Mission lifecycle and immutable launch context",
        "0.12.0", "publisher", "observer", "docs/THIRD_PARTY_GUIDE.md#initialization-and-ownership",
        "Register after initialization; native readiness is independent."),
    _cap("simulation_ticks", "mission", "SimulationTickEvents",
        "0.22.0", "simulation", "host_sync", "docs/API_CATALOG.md#native-simulation-ticks",
        "Use native save-preserved map ticks, not local SE on-tick frame counts."),
    _cap("mission_settings", "mission", "MissionModSettingsPreparation",
        "0.21.0", "unity", "host_sync", "docs/MOD_SETTINGS.md",
        "Respect host, player and fixed creator scopes."),
    _cap("mod_data", "mission", "ModDataAccess",
        "0.12.2", "unity", "observer", "docs/MOD_DATA.md",
        "GUID-scoped current archive/local data, not arbitrary native memory."),
    _cap("aiv_build", "castle", "AivBuildStepCapability",
        "0.14.0", "simulation", "observer", "docs/API_CATALOG.md#aiv-build-observation",
        "Native build-step diagnostics require a validated image."),
    _cap("mapper_camera", "castle", "MapperSelectionCameraEvents",
        "0.27.0", "unity", "presentation", "docs/THIRD_PARTY_GUIDE.md#mapper-selection-camera",
        "Suppresses automatic centering only; does not override native selection."),
    _cap("hud_extras", "hud", "HudExtrasButtonsCapability",
        "0.16.0", "unity", "presentation", "docs/API_CATALOG.md#side-hud-buttons",
        "Owner-bound button registration with process lifetime."),
    _cap("hud_units", "hud", "UnitHudActionButtonsCapability",
        "0.16.0", "unity", "presentation", "docs/API_CATALOG.md#own-troop-action-buttons",
        "Visibility is contingent on local own-unit selection."),
    _cap("tooltips", "hud", "TooltipPresentation",
        "0.13.0", "unity", "presentation", "docs/TOOLTIPS.md",
        "Literal content, not XAML or game-rule authorization."),
    _cap("ui_deferred", "hud", "ModApiClient.Ui.TryPost",
        "0.26.0", "unity", "presentation", "docs/THIRD_PARTY_GUIDE.md#deferred-unity-work-and-refresh-demand",
        "Deferred presentation; never use as a simulation timer."),
    _cap("game_actions", "balance", "GameActionEvents",
        "0.15.0", "unity", "host_sync", "docs/API_CATALOG.md#managed-actions-and-hud-interception",
        "Shared GameAction interception; command payload semantics vary."),
    _cap("recruit_availability", "balance", "RecruitmentAvailability",
        "0.16.0", "unity", "presentation", "docs/API_CATALOG.md#managed-actions-and-hud-interception",
        "Never re-enable a Vanilla-disabled recruit control."),
    _cap("market_prices", "balance", "MarketPriceEvents",
        "0.16.0", "native", "host_sync", "docs/API_CATALOG.md#native-market-price-queries",
        "Native query hooks owned by APIShared, must match pinned executable."),
    _cap("building_repair", "balance", "BuildingRepairCapability",
        "0.16.0", "unity", "host_sync", "docs/API_CATALOG.md#source-map",
        "Validate actual resources and ownership before repairing."),
    _cap("map_lookup", "maps", "MultiplayerMapLookup",
        "0.16.3", "unity", "host_sync", "docs/API_CATALOG.md#multiplayer-map-lookup-and-lobby-system-hints",
        "Owner-bound lookup of verified content, not an arbitrary map parser."),
    _cap("lord_presentation", "lords", "Packaged Lord presentation",
        "0.20.0", "unity", "presentation", "docs/API_CATALOG.md#packaged-lord-presentation",
        "Presentation assets are separate from Lord game-type changes."),
    _cap("lord_stats", "lords", "Lord statistics column broker",
        "0.19.0", "unity", "presentation", "docs/API_CATALOG.md#lord-statistic-columns",
        "Permission-checked observer columns."),
    _cap("unit_settled", "units", "UnitSettledEvents",
        "0.16.0", "simulation", "observer", "docs/API_CATALOG.md#unit-settlement-events",
        "Observed creation/transition can be later than a submitted order."),
    _cap("unit_access", "units", "UnitAccess",
        "0.14.0", "simulation", "observer", "docs/API_CATALOG.md#direct-helpers-and-advanced-integration",
        "Pointer views must not outlive the current game context."),
    _cap("route_search", "units", "RouteSearchEvents",
        "0.16.0", "simulation", "host_sync", "docs/API_CATALOG.md#additional-weighted-route-events",
        "Only route providers that publish these events are affected."),
    _cap("route_tile", "units", "RouteTileRules",
        "0.18.0", "simulation", "host_sync", "docs/API_CATALOG.md#route-tile-rules",
        "Passive registry; does not alter Vanilla pathfinding by itself."),
    _cap("sound_events", "audio", "SoundEvents",
        "0.8.0", "audio", "presentation", "docs/AUDIO.md",
        "Post reports submission, never audible playback."),
    _cap("sound_sources", "audio", "SoundSourceEvents",
        "0.16.0", "audio", "presentation", "docs/AUDIO.md#native-source-events",
        "Native source attribution requires a supported binary image."),
    _cap("sound_clips", "audio", "SoundClips",
        "0.8.0", "unity", "presentation", "docs/AUDIO.md#preloaded-custom-clips",
        "Preload exact clips, keep sound source IDs distinct from handles."),
    _cap("versioned_save", "saves", "VersionedSaveData",
        "0.15.0", "save", "host_sync", "docs/SAVE_DATA.md",
        "Unknown newer entries survive byte-for-byte; migrate deliberately."),
    _cap("authenticated_chore", "saves", "RegisterAuthenticatedChore",
        "0.23.0", "simulation", "host_sync", "docs/API_CATALOG.md#multiplayer-packets",
        "1200-byte Chore bound and sender checks; submit != execution."),
    _cap("messages", "saves", "RegisterMessage",
        "0.7.0", "unity", "presentation", "docs/API_CATALOG.md#multiplayer-packets",
        "Control-plane only: no simulation mutation."),
    _cap("workshop_client", "workshop", "WorkshopClient",
        "0.16.0", "unity", "deployment", "docs/WORKSHOP.md",
        "Preparation is not deployment; require consent and post-exit application."),
    _cap("native_registry", "native", "NativeSiteRegistry",
        "0.14.0", "initialization", "observer", "docs/NATIVE_SITES.md",
        "Coordination metadata only; not a hook-install authorization."),
    _cap("native_knowledge", "native", "NativeKnowledge",
        "0.25.0", "native", "observer", "docs/THIRD_PARTY_GUIDE.md#native-field-knowledge",
        "Bounded raw reads require exact DLL hash and consumer-owned views."),
)
CAPABILITY_BY_KEY = {cap.key: cap for cap in CAPABILITIES}
assert len(CAPABILITIES) == len(CAPABILITY_BY_KEY)

_VERSION = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")

def version_tuple(value: str) -> tuple[int, int, int]:
    match = _VERSION.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        raise StudioError(f"version must be canonical major.minor.patch: {value!r}")
    return tuple(int(group) for group in match.groups())  # type: ignore[return-value]


def search(query: str = "", *, module: str = "") -> list[dict[str, str]]:
    if module and module not in MODULE_IDS:
        raise StudioError(f"unknown studio module: {module}")
    terms = str(query).casefold().split()
    rows = []
    for cap in CAPABILITIES:
        if module and cap.module != module:
            continue
        haystack = " ".join((cap.key, cap.module, cap.name, cap.note, cap.threading)).casefold()
        if not all(term in haystack for term in terms):
            continue
        rows.append({
            "key": cap.key,
            "module": cap.module,
            "name": cap.name,
            "minimum_api_shared": cap.min_api,
            "threading": cap.threading,
            "mode": cap.mode,
            "source": API_DOC_ROOT + "/" + cap.source,
            "note": cap.note,
        })
    return sorted(rows, key=lambda item: (item["module"], item["key"]))


def minimum_api(capabilities: Iterable[str]) -> str:
    minimum = (0, 0, 0)
    for key in capabilities:
        key = require_id(key, "required capability")
        item = CAPABILITY_BY_KEY.get(key)
        if item is None:
            raise StudioError(f"unknown APIShared capability: {key}")
        minimum = max(minimum, version_tuple(item.min_api))
    return ".".join(map(str, minimum))


def version_evidence() -> dict[str, str]:
    return {
        "api_shared_release": API_RELEASE,
        "api_shared_source_commit": API_COMMIT,
        "script_extender_minimum": MIN_SCRIPT_EXTENDER,
        "serp_baseline_source_commit": SERP_COMMIT,
        "serp_baseline_native_sha256": NATIVE_BASELINE_SHA256,
        "api_catalog": API_DOC_ROOT + "/docs/API_CATALOG.md",
        "native_baseline": BASELINE_DOC_ROOT +
            "/_inspect/CrusaderDE-Native-Baseline/CURRENT.md",
        "status": "research_pins_only_not_installed_game_acceptance",
    }

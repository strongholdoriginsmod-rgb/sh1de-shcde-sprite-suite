from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any

from .asset_stream_contract import (
    ASSET_BUNDLE_CATEGORY,
    ASSET_BUNDLE_INDEX_CATEGORY,
    ATLAS_BACKEND_KIND,
    BC7_ATLAS_BACKEND_KIND,
    BC7_BUNDLE_SUFFIX,
    BC7_ENCODER_ID,
    BC7_INDEX_SCHEMA,
    BC7_PACKER_ID,
    BUILD_TARGET,
    INDEX_OUTPUT_PATH,
    INDEX_SCHEMA,
    UNITY_REVISION,
    UNITY_VERSION,
    MAX_INDEX_BYTES,
    AssetStreamContractError,
    canonical_group_slug,
    canonical_json_bytes,
    parse_atlas_backend,
)

from .gm_atlas import (
    AUTHORED_SPRITE_CATEGORY,
    AUTHORED_SPRITE_KIND,
    AUTHORED_SPRITE_MASK_CATEGORY,
    AtlasGroupSpec,
    GMAtlasError,
    authored_sprite_names_digest,
    authored_sprite_payload_digest,
    KEEP_CRUSADER_PROOF_STATUS,
    REVIEW_INDIVIDUAL_CONTRACT_KIND,
    REVIEW_INDIVIDUAL_CONTRACT_PREFIX,
    REVIEW_INDIVIDUAL_MAIN_CATEGORY,
    REVIEW_INDIVIDUAL_MASK_CATEGORY,
    REVIEW_INDIVIDUAL_SOURCE_ONLY_MODE,
    ReviewIndividualSourceOnlySpec,
    SHARED_GM_ATLAS_PROFILE_KEY,
    SharedGMAtlasSpec,
    parse_loader_frame_name,
)
from .loader_groups import LOADER_GROUP_TABLE
from .runtime_build import (
    _DIPLOMACY_ROLLOUT_PROFILE_IDS,
    _FORTIFICATION_ARTIFACT_KIND,
    _FORTIFICATION_RUNTIME_PATH,
    _FORTIFICATION_SOURCE_PATH,
    _FORTIFICATION_V1_SOURCE_SHA256,
    _FORTIFICATION_V1_SOURCE_SIZE,
    _FORTIFICATION_V1_TSV_SHA256,
    _FORTIFICATION_V1_TSV_SIZE,
    RuntimeBuildError,
    UiTextureRuntimeManifest,
    parse_ui_texture_runtime_manifest_v2,
)
from .ui_asset_bundle import UI_BACKEND_KIND


@dataclass(frozen=True)
class ProfileContractCheck:
    name: str
    ok: bool
    detail: str


_RUNTIME_SELECTION_KEYS = frozenset(
    {
        "enabled",
        "audio_payload",
        "foliage_tree_apple",
        "unit_roster_names",
        "farm_placement",
        "worker_militia",
        "diplomacy",
        "fortifications",
        "dock_placement",
    }
)
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
_RUNTIME_DLL_PATH = "StrongholdEuropeDE.Runtime.dll"
_RUNTIME_CONTRACT_PATH = "Runtime/audio-profile.tsv"
_RUNTIME_ROSTER_PATH = "Runtime/unit-roster.tsv"
_RUNTIME_MUSIC_PREFIX = "Override/Sounds/Music/"
_RUNTIME_MUSIC_COUNT = 17
_RUNTIME_AUDIO_STREAM_PREFIX = "Runtime/Audio/"
_RUNTIME_PCM_MANIFEST_PATH = "Runtime/Audio/pcm-stream-manifest.tsv"
_RUNTIME_UI_TEXTURE_MANIFEST_PATH = "Runtime/ui-textures-v2.tsv"
_RUNTIME_UI_TEXTURE_V1_MANIFEST_PATH = "Runtime/ui-textures-v1.tsv"
_RUNTIME_UI_BUNDLE_PREFIX = "Runtime/UiAssetBundles/win64/"
_UI_TEXTURE_BACKEND_KEYS = frozenset(
    {
        "editor_source_path",
        "editor_source_sha256",
        "expected_entry_count",
        "kind",
        "quality_policy_path",
        "quality_policy_sha256",
        "source_manifest_path",
        "source_manifest_sha256",
    }
)
_UI_SOURCE_MANIFEST_PATH = "config/ui-textures-bc7-v1.json"
_UI_QUALITY_POLICY_PATH = "config/ui-bc7-quality-v1.json"
_UI_EDITOR_SOURCE_PATH = (
    "tools/unity_asset_bundle/StrongholdEuropeUiTextureBundleBuilder.cs"
)
_SPRITE_SELECTION_KEYS = frozenset(
    {"name", "category", "require_mask", "allow_nontransparent_clip"}
)
_AUTHORED_SPRITE_SELECTION_KEYS = frozenset(
    {
        "source_dir",
        "group",
        "category",
        "origin",
        "frame_count",
        "mask_count",
        "expected_names_sha256",
        "expected_payload_sha256",
        "allow_atlas_shadow",
    }
)
_AUTHORED_UI_SELECTION_KEYS = frozenset(
    {
        "source", "output", "category", "origin", "width", "height",
        "expected_sha256",
    }
)
_AUTHORED_BACKGROUND_SELECTION_KEYS = frozenset(
    {"source", "output", "category", "width", "height", "expected_sha256"}
)
_AUTHORED_BACKGROUND_SOURCE_ROOT = "work/hintergruende/europa-generiert/fertig"
_AUTHORED_BACKGROUND_OUTPUT_PREFIX = "Override/Assets/GUI/Images/"
_MAX_AUTHORED_BACKGROUND_PIXELS = 32 * 1024 * 1024
_AUTHORED_MENU_VIDEO_SELECTION_KEYS = frozenset(
    {"source", "output", "category", "expected_sha256"}
)
_AUTHORED_MENU_VIDEO_SOURCE_ROOT = "work/hintergruende/europa-generiert/video"
_AUTHORED_MENU_VIDEO_OUTPUT_PREFIX = "Override/Assets/GUI/Video/"
_TEXTURE_SELECTION_KEYS = frozenset(
    {"name", "source_asset", "target_asset", "output", "category"}
)
_FILE_SELECTION_KEYS = frozenset({"source", "output", "category"})
_PROJECT_FILE_SELECTION_KEYS = frozenset(
    {"source", "output", "category", "expected_sha256"}
)
_LOGO_SELECTION_KEYS = frozenset(
    {"name", "source_asset", "canvas_width", "canvas_height", "output"}
)
_WINDOWS_RESERVED_COMPONENTS = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)


def _check(name: str, ok: bool, detail: str) -> ProfileContractCheck:
    return ProfileContractCheck(name=name, ok=ok, detail=detail)


def _portable_relative_path(value: object) -> str | None:
    if not isinstance(value, str) or not value or "\\" in value:
        return None
    pure = PurePosixPath(value)
    if (
        pure.is_absolute()
        or not pure.parts
        or any(part in {"", ".", ".."} for part in pure.parts)
        or pure.as_posix() != value
    ):
        return None
    for component in pure.parts:
        if (
            component.endswith((" ", "."))
            or any(character in component for character in '<>:"|?*')
            or any(ord(character) < 32 for character in component)
            or component.split(".", 1)[0].upper() in _WINDOWS_RESERVED_COMPONENTS
        ):
            return None
    return value


def _selection_list(
    profile: dict[str, Any],
    key: str,
    errors: list[str],
    expected_keys: frozenset[str],
) -> list[dict[str, Any]]:
    raw = profile.get(key, [])
    if not isinstance(raw, list):
        errors.append(f"{key} must be a list")
        return []
    selections: list[dict[str, Any]] = []
    for index, selection in enumerate(raw):
        if not isinstance(selection, dict):
            errors.append(f"{key}[{index}] must be an object")
            continue
        if set(selection) != expected_keys:
            actual = sorted(repr(field) for field in selection)
            errors.append(
                f"{key}[{index}] fields changed: actual={actual} "
                f"expected={sorted(expected_keys)}"
            )
        selections.append(selection)
    return selections


def _string_field(
    selection: dict[str, Any], field: str, label: str, errors: list[str]
) -> str:
    value = selection.get(field)
    if not isinstance(value, str) or not value:
        errors.append(f"{label}.{field} must be a non-empty string")
        return ""
    return value


def _portable_string_field(
    selection: dict[str, Any], field: str, label: str, errors: list[str]
) -> str:
    value = _string_field(selection, field, label, errors)
    if value and _portable_relative_path(value) is None:
        errors.append(f"{label}.{field} must be a portable relative path")
        return ""
    return value


def _nested_value(document: object, path: str) -> object:
    value = document
    for component in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(component)
    return value


def profile_output_contract_checks(
    mod_root: Path,
    expected_profile: dict[str, Any],
    manifest: dict[str, Any],
    declared: dict[str, dict[str, Any]],
) -> list[ProfileContractCheck]:
    """Bind every builder-owned output family to an external profile.

    Static validation normally proves that the files an artifact declares are
    internally coherent.  This inverse contract proves that the externally
    selected profile actually requested those files.  Sparse sprite and music
    paths are the only dynamic sets; their exact payloads remain guarded by the
    existing sparse/runtime validators, while this layer binds their selection,
    namespace, categories and profile-pinned counts.
    """

    checks: list[ProfileContractCheck] = []
    errors: list[str] = []
    expected_paths: set[str] = set()
    path_owners: dict[str, tuple[str, str]] = {}
    envelopes: list[tuple[str, str, dict[str, object]]] = []
    try:
        atlas_backend = parse_atlas_backend(expected_profile)
    except AssetStreamContractError as exc:
        atlas_backend = None
        errors.append(f"atlas_backend: {exc}")
    streaming = atlas_backend is not None
    bc7_streaming = (
        atlas_backend is not None
        and atlas_backend.kind == BC7_ATLAS_BACKEND_KIND
    )
    streamed_group_names: set[str] = set()
    raw_ui_backend = expected_profile.get("ui_texture_backend")
    ui_backend_selected = raw_ui_backend is not None
    ui_backend_shape_ok = False
    parsed_ui_manifest: UiTextureRuntimeManifest | None = None
    ui_manifest_detail = "not selected"
    if raw_ui_backend is not None:
        ui_backend_shape_ok = (
            isinstance(raw_ui_backend, dict)
            and set(raw_ui_backend) == _UI_TEXTURE_BACKEND_KEYS
            and raw_ui_backend.get("kind") == UI_BACKEND_KIND
            and raw_ui_backend.get("source_manifest_path")
            == _UI_SOURCE_MANIFEST_PATH
            and raw_ui_backend.get("quality_policy_path")
            == _UI_QUALITY_POLICY_PATH
            and raw_ui_backend.get("editor_source_path")
            == _UI_EDITOR_SOURCE_PATH
            and type(raw_ui_backend.get("expected_entry_count")) is int
            and 1 <= raw_ui_backend.get("expected_entry_count", 0) <= 512
            and all(
                isinstance(raw_ui_backend.get(field), str)
                and re.fullmatch(
                    r"[0-9a-f]{64}", str(raw_ui_backend.get(field))
                )
                is not None
                for field in (
                    "source_manifest_sha256",
                    "quality_policy_sha256",
                    "editor_source_sha256",
                )
            )
        )
        if not streaming:
            errors.append("ui_texture_backend requires atlas_backend")
        if ui_backend_shape_ok and atlas_backend is not None:
            try:
                parsed_ui_manifest = parse_ui_texture_runtime_manifest_v2(
                    mod_root,
                    expected_source_manifest_sha256=raw_ui_backend[
                        "source_manifest_sha256"
                    ],
                    expected_quality_policy_sha256=raw_ui_backend[
                        "quality_policy_sha256"
                    ],
                    expected_editor_source_sha256=raw_ui_backend[
                        "editor_source_sha256"
                    ],
                    expected_entry_count=raw_ui_backend[
                        "expected_entry_count"
                    ],
                    max_resident_bytes=(
                        atlas_backend.resource_policy.ui_resident_bytes
                    ),
                )
                ui_manifest_detail = (
                    f"entries={parsed_ui_manifest.entry_count} "
                    f"resident={parsed_ui_manifest.declared_resident_charge_bytes} "
                    f"sha256={parsed_ui_manifest.sha256}"
                )
            except (OSError, RuntimeBuildError) as exc:
                ui_manifest_detail = str(exc)
    checks.append(
        _check(
            "profile.ui_texture_backend_shape",
            raw_ui_backend is None or ui_backend_shape_ok,
            json.dumps(raw_ui_backend, sort_keys=True),
        )
    )
    checks.append(
        _check(
            "profile.ui_texture_manifest_binding",
            not ui_backend_selected or parsed_ui_manifest is not None,
            ui_manifest_detail,
        )
    )
    compacted_ui_paths = (
        {
            "Override/" + entry.noesis_path
            for entry in parsed_ui_manifest.entries
        }
        if parsed_ui_manifest is not None
        else set()
    )

    def compacted_ui_output(relative: object) -> bool:
        return isinstance(relative, str) and relative in compacted_ui_paths

    checks.append(
        _check(
            "profile.schema_version",
            type(expected_profile.get("schema_version")) is int
            and expected_profile.get("schema_version") == 1,
            repr(expected_profile.get("schema_version")),
        )
    )
    description = expected_profile.get("description", "")
    checks.append(
        _check(
            "profile.description",
            isinstance(description, str)
            and manifest.get("profile_description") == description,
            f"expected={description!r} actual={manifest.get('profile_description')!r}",
        )
    )
    mod_info = expected_profile.get("mod_info")
    checks.append(
        _check(
            "profile.mod_info",
            isinstance(mod_info, dict) and manifest.get("mod_info") == mod_info,
            json.dumps(
                {"expected": mod_info, "actual": manifest.get("mod_info")},
                sort_keys=True,
            ),
        )
    )

    def add_output(
        relative: object,
        owner: str,
        expected_fields: dict[str, object],
    ) -> None:
        path = _portable_relative_path(relative)
        if path is None:
            errors.append(f"{owner} has an unsafe output path: {relative!r}")
            return
        folded = path.casefold()
        prior = path_owners.get(folded)
        if prior is not None:
            errors.append(
                f"output collision: {prior[0]} ({prior[1]!r}) and {owner} ({path!r})"
            )
        else:
            path_owners[folded] = (owner, path)
        expected_paths.add(path)
        envelopes.append((owner, path, expected_fields))

    add_output(
        "info.json",
        "info",
        {
            "category": "mod_metadata",
            "source_reference": None,
            "width": None,
            "height": None,
            "lost_alpha": None,
            "metadata": None,
        },
    )

    raw_atlases = expected_profile.get("gm_atlases", [])
    atlas_specs: list[AtlasGroupSpec] = []
    if not isinstance(raw_atlases, list):
        errors.append("gm_atlases must be a list")
    else:
        try:
            atlas_specs = [AtlasGroupSpec.from_profile(raw) for raw in raw_atlases]
        except (GMAtlasError, AttributeError, OverflowError, TypeError, ValueError) as exc:
            errors.append(f"gm_atlases: {exc}")
    atlas_groups = [spec.gm_file_name.casefold() for spec in atlas_specs]
    if len(atlas_groups) != len(set(atlas_groups)):
        errors.append("gm_atlases selects a group more than once")
    for spec in atlas_specs:
        if streaming:
            streamed_group_names.add(spec.gm_file_name)
            continue
        prefix = f"Override/Atlas/{spec.gm_file_name}/"
        add_output(
            prefix + "atlas.png",
            f"gm_atlases.{spec.gm_file_name}.texture",
            {
                "category": spec.category,
                "lost_alpha": 0,
                "metadata": None,
            },
        )
        add_output(
            prefix + "atlas.json",
            f"gm_atlases.{spec.gm_file_name}.frames",
            {
                "category": spec.category + "_frames",
                "width": None,
                "height": None,
                "lost_alpha": None,
            },
        )
        if spec.require_mask:
            add_output(
                prefix + "atlas_m.png",
                f"gm_atlases.{spec.gm_file_name}.mask",
                {
                    "category": spec.category + "_team_mask",
                    "lost_alpha": 0,
                    "metadata": None,
                },
            )

    raw_shared_atlases = expected_profile.get(SHARED_GM_ATLAS_PROFILE_KEY, [])
    shared_specs: list[SharedGMAtlasSpec] = []
    if not isinstance(raw_shared_atlases, list):
        errors.append(f"{SHARED_GM_ATLAS_PROFILE_KEY} must be a list")
    else:
        try:
            shared_specs = [
                SharedGMAtlasSpec.from_profile(raw)
                for raw in raw_shared_atlases
            ]
        except (GMAtlasError, AttributeError, OverflowError, TypeError, ValueError) as exc:
            errors.append(f"{SHARED_GM_ATLAS_PROFILE_KEY}: {exc}")
    shared_groups = [
        name.casefold() for spec in shared_specs for name in spec.member_names
    ]
    if len(shared_groups) != len(set(shared_groups)):
        errors.append(f"{SHARED_GM_ATLAS_PROFILE_KEY} repeats a member")
    overlap = sorted(set(atlas_groups) & set(shared_groups))
    if overlap:
        errors.append(f"atlas/shared backend overlap: {overlap}")
    atlas_groups.extend(shared_groups)
    for spec in shared_specs:
        if streaming:
            streamed_group_names.add(spec.host_gm_file_name)
            continue
        prefix = f"Override/Atlas/{spec.host_gm_file_name}/"
        add_output(
            prefix + "atlas.png",
            f"{SHARED_GM_ATLAS_PROFILE_KEY}.{spec.host_gm_file_name}.texture",
            {
                "category": spec.category,
                "lost_alpha": 0,
                "metadata": None,
            },
        )
        add_output(
            prefix + "atlas.json",
            f"{SHARED_GM_ATLAS_PROFILE_KEY}.{spec.host_gm_file_name}.frames",
            {
                "category": spec.category + "_frames",
                "width": None,
                "height": None,
                "lost_alpha": None,
            },
        )

    explicit_sprite_paths: set[str] = set()
    for index, selection in enumerate(
        _selection_list(
            expected_profile, "sprites", errors, _SPRITE_SELECTION_KEYS
        )
    ):
        label = f"sprites[{index}]"
        name = _string_field(selection, "name", label, errors)
        category = _string_field(selection, "category", label, errors)
        require_mask = selection.get("require_mask")
        if not isinstance(require_mask, bool):
            errors.append(f"{label}.require_mask must be a boolean")
        allow_clip = selection.get("allow_nontransparent_clip")
        if not isinstance(allow_clip, bool):
            errors.append(f"{label}.allow_nontransparent_clip must be a boolean")
        if not name or not category:
            continue
        if streaming:
            matches = [
                group
                for group, loader in LOADER_GROUP_TABLE.items()
                if parse_loader_frame_name(name, group, loader.dash_format)
                is not None
            ]
            if len(matches) != 1:
                errors.append(
                    f"{label}.name has no unique streamed GM group: {matches}"
                )
            else:
                streamed_group_names.add(matches[0])
            continue
        main_path = f"Override/Sprites/{name}.png"
        add_output(
            main_path,
            label,
            {"category": category, "lost_alpha": 0, "metadata": None},
        )
        explicit_sprite_paths.add(main_path)
        if require_mask is True:
            mask_path = f"Override/Sprites/{name}_m.png"
            add_output(
                mask_path,
                label + ".mask",
                {
                    "category": category + "_team_mask",
                    "lost_alpha": 0,
                    "metadata": None,
                },
            )
            explicit_sprite_paths.add(mask_path)

    # Hand-drawn sprite deliveries. The paths are NOT enumerated from the
    # profile - the profile never lists 111 file names - but derived from the
    # manifest exactly like the sparse payload, and then held against the two
    # pinned digests. Both digests are recomputed here from the manifest alone,
    # so this is a second, independent computation of what the builder claimed.
    authored_sprite_paths: set[str] = set()
    for index, selection in enumerate(
        _selection_list(
            expected_profile,
            "authored_sprites",
            errors,
            _AUTHORED_SPRITE_SELECTION_KEYS,
        )
    ):
        label = f"authored_sprites[{index}]"
        source_dir = _portable_string_field(selection, "source_dir", label, errors)
        group = _string_field(selection, "group", label, errors)
        category = _string_field(selection, "category", label, errors)
        origin = _string_field(selection, "origin", label, errors)
        frame_count = selection.get("frame_count")
        mask_count = selection.get("mask_count")
        names_pin = selection.get("expected_names_sha256")
        payload_pin = selection.get("expected_payload_sha256")
        if category and category != AUTHORED_SPRITE_CATEGORY:
            errors.append(
                f"{label}.category must be {AUTHORED_SPRITE_CATEGORY!r}"
            )
        if not isinstance(selection.get("allow_atlas_shadow"), bool):
            errors.append(f"{label}.allow_atlas_shadow must be a boolean")
        for field, value in (
            ("frame_count", frame_count),
            ("mask_count", mask_count),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                errors.append(f"{label}.{field} must be a non-negative integer")
        for field, value in (
            ("expected_names_sha256", names_pin),
            ("expected_payload_sha256", payload_pin),
        ):
            if (
                not isinstance(value, str)
                or re.fullmatch(r"[0-9a-f]{64}", value) is None
            ):
                errors.append(f"{label}.{field} must be lowercase SHA-256")
        if not source_dir or not group or not origin:
            continue
        if streaming:
            if group not in LOADER_GROUP_TABLE:
                errors.append(f"{label}.group is not a pinned loader group")
            else:
                streamed_group_names.add(group)
            checks.append(
                _check(
                    f"profile.authored_payload.{source_dir}",
                    group in LOADER_GROUP_TABLE,
                    f"streamed_group={group!r}; source pins were validated pre-pack",
                )
            )
            continue

        rows: list[dict[str, object]] = []
        mains: dict[str, dict[str, Any]] = {}
        masks: dict[str, dict[str, Any]] = {}
        invalid: list[str] = []
        for relative, entry in declared.items():
            metadata = entry.get("metadata")
            if not isinstance(metadata, dict) or metadata.get("set") != source_dir:
                continue
            authored_sprite_paths.add(relative)
            flat = (
                relative[len("Override/Sprites/") :]
                if relative.startswith("Override/Sprites/")
                else ""
            )
            frame = metadata.get("frame")
            destination = (
                masks if entry.get("category") == AUTHORED_SPRITE_MASK_CATEGORY else mains
            )
            expected_flat = (
                f"{frame}_m.png"
                if entry.get("category") == AUTHORED_SPRITE_MASK_CATEGORY
                else f"{frame}.png"
            )
            if (
                metadata.get("kind") != AUTHORED_SPRITE_KIND
                or metadata.get("group") != group
                or metadata.get("origin") != origin
                or entry.get("category")
                not in {AUTHORED_SPRITE_CATEGORY, AUTHORED_SPRITE_MASK_CATEGORY}
                or entry.get("lost_alpha") != 0
                or not isinstance(frame, str)
                or flat != expected_flat
                or frame in destination
            ):
                invalid.append(relative)
                continue
            destination[frame] = entry

        for frame in sorted(mains):
            entry = mains[frame]
            metadata = entry["metadata"]
            mask_entry = masks.get(frame)
            rows.append(
                {
                    "name": frame,
                    "width": entry.get("width"),
                    "height": entry.get("height"),
                    "foot_px_x": metadata.get("foot_px_x"),
                    "foot_px_y": metadata.get("foot_px_y"),
                    "main_sha256": entry.get("sha256"),
                    "mask_sha256": (
                        "-" if mask_entry is None else mask_entry.get("sha256")
                    ),
                }
            )
        orphan_masks = sorted(set(masks) - set(mains))
        try:
            actual_names = authored_sprite_names_digest(sorted(mains))
            actual_payload = authored_sprite_payload_digest(rows)
        except (GMAtlasError, TypeError, ValueError) as exc:
            actual_names = f"unusable: {exc}"
            actual_payload = f"unusable: {exc}"
        payload_ok = (
            not invalid
            and not orphan_masks
            and bool(mains)
            and len(mains) == frame_count
            and len(masks) == mask_count
            and actual_names == names_pin
            and actual_payload == payload_pin
        )
        checks.append(
            _check(
                f"profile.authored_payload.{source_dir}",
                payload_ok,
                f"frames={len(mains)} masks={len(masks)} "
                f"names={actual_names} payload={actual_payload} "
                f"invalid={sorted(invalid)} orphan_masks={orphan_masks}",
            )
        )

    for index, selection in enumerate(
        _selection_list(
            expected_profile,
            "texture_overrides",
            errors,
            _TEXTURE_SELECTION_KEYS,
        )
    ):
        label = f"texture_overrides[{index}]"
        name = _string_field(selection, "name", label, errors)
        source_asset = _portable_string_field(
            selection, "source_asset", label, errors
        )
        target_asset = _portable_string_field(
            selection, "target_asset", label, errors
        )
        category = _string_field(selection, "category", label, errors)
        output = _string_field(selection, "output", label, errors)
        if (
            output
            and category
            and name
            and source_asset
            and target_asset
            and not compacted_ui_output(output)
        ):
            add_output(
                output,
                label,
                {
                    "category": category,
                    "lost_alpha": 0,
                    "metadata": {
                        "kind": "unity_texture_override_v1",
                        "name": name,
                        "source_asset": source_asset,
                        "target_asset": target_asset,
                    },
                },
            )
            entry = declared.get(output)
            reference = (
                entry.get("source_reference") if isinstance(entry, dict) else None
            )
            reference_ok = isinstance(reference, str) and re.fullmatch(
                rf"{re.escape(source_asset)}:Texture2D:-?\d+:{re.escape(name)}",
                reference,
            ) is not None
            checks.append(
                _check(
                    f"profile.texture_source_reference.{index}",
                    reference_ok,
                    f"expected_asset={source_asset!r} expected_name={name!r} "
                    f"actual={reference!r}",
                )
            )

    for index, selection in enumerate(
        _selection_list(
            expected_profile,
            "authored_backgrounds",
            errors,
            _AUTHORED_BACKGROUND_SELECTION_KEYS,
        )
    ):
        label = f"authored_backgrounds[{index}]"
        source = _portable_string_field(selection, "source", label, errors)
        output = _portable_string_field(selection, "output", label, errors)
        category = _string_field(selection, "category", label, errors)
        width = selection.get("width")
        height = selection.get("height")
        digest = selection.get("expected_sha256")
        source_path = PurePosixPath(source) if source else None
        if source_path is not None and (
            source_path.parent.as_posix() != _AUTHORED_BACKGROUND_SOURCE_ROOT
            or source_path.suffix != ".png"
        ):
            errors.append(f"{label}.source is not allowlisted")
        if source_path is not None and output != (
            _AUTHORED_BACKGROUND_OUTPUT_PREFIX + source_path.name
        ):
            errors.append(f"{label}.output must match its source filename")
        if category and category != "authored_background":
            errors.append(f"{label}.category must be 'authored_background'")
        dimensions_ok = True
        for field, value in (("width", width), ("height", height)):
            if type(value) is not int or value <= 0:
                dimensions_ok = False
                errors.append(f"{label}.{field} must be a positive integer")
        if dimensions_ok and width * height > _MAX_AUTHORED_BACKGROUND_PIXELS:
            errors.append(f"{label} dimensions exceed the pixel limit")
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            errors.append(f"{label}.expected_sha256 must be lowercase SHA-256")
        if source and output and category and not compacted_ui_output(output):
            add_output(
                output,
                label,
                {
                    "category": "authored_background",
                    "source_reference": f"authored-background:{source}",
                    "sha256": digest,
                    "width": width,
                    "height": height,
                    "lost_alpha": None,
                    "metadata": {
                        "kind": "authored_background_v1",
                        "format": "png",
                    },
                },
            )

    for index, selection in enumerate(
        _selection_list(
            expected_profile,
            "authored_menu_videos",
            errors,
            _AUTHORED_MENU_VIDEO_SELECTION_KEYS,
        )
    ):
        label = f"authored_menu_videos[{index}]"
        source = _portable_string_field(selection, "source", label, errors)
        output = _portable_string_field(selection, "output", label, errors)
        category = _string_field(selection, "category", label, errors)
        digest = selection.get("expected_sha256")
        source_path = PurePosixPath(source) if source else None
        if source_path is not None and (
            source_path.parent.as_posix() != _AUTHORED_MENU_VIDEO_SOURCE_ROOT
            or source_path.suffix != ".webm"
        ):
            errors.append(f"{label}.source is not allowlisted")
        if source_path is not None and output != (
            _AUTHORED_MENU_VIDEO_OUTPUT_PREFIX + source_path.name
        ):
            errors.append(f"{label}.output must match its source filename")
        if category and category != "menu_video":
            errors.append(f"{label}.category must be 'menu_video'")
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            errors.append(f"{label}.expected_sha256 must be lowercase SHA-256")
        if source and output and category:
            add_output(
                output,
                label,
                {
                    "category": "menu_video",
                    "source_reference": f"authored-menu-video:{source}",
                    "sha256": digest,
                    "width": None,
                    "height": None,
                    "lost_alpha": None,
                    "metadata": {
                        "kind": "authored_menu_video_v1",
                        "container": "webm",
                    },
                },
            )

    for index, selection in enumerate(
        _selection_list(
            expected_profile,
            "authored_ui_atlases",
            errors,
            _AUTHORED_UI_SELECTION_KEYS,
        )
    ):
        label = f"authored_ui_atlases[{index}]"
        source = _portable_string_field(selection, "source", label, errors)
        output = _portable_string_field(selection, "output", label, errors)
        category = _string_field(selection, "category", label, errors)
        origin = _string_field(selection, "origin", label, errors)
        width = selection.get("width")
        height = selection.get("height")
        digest = selection.get("expected_sha256")
        if category and category != "authored_ui_atlas":
            errors.append(f"{label}.category must be 'authored_ui_atlas'")
        if origin not in {"authored", "derived"}:
            errors.append(f"{label}.origin must be authored or derived")
        for field, value in (("width", width), ("height", height)):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                errors.append(f"{label}.{field} must be a positive integer")
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            errors.append(f"{label}.expected_sha256 must be lowercase SHA-256")
        if (
            source
            and output
            and category
            and origin
            and not compacted_ui_output(output)
        ):
            add_output(
                output,
                label,
                {
                    "category": "authored_ui_atlas",
                    "source_reference": f"authored-ui:{source}",
                    "sha256": digest,
                    "width": width,
                    "height": height,
                    "lost_alpha": None,
                    "metadata": {"kind": "authored_ui_atlas_v1", "origin": origin},
                },
            )

    for index, selection in enumerate(
        _selection_list(
            expected_profile, "file_overrides", errors, _FILE_SELECTION_KEYS
        )
    ):
        label = f"file_overrides[{index}]"
        source = _portable_string_field(selection, "source", label, errors)
        output = _string_field(selection, "output", label, errors)
        category = _string_field(selection, "category", label, errors)
        if source and output and category and not compacted_ui_output(output):
            add_output(
                output,
                label,
                {
                    "category": category,
                    "source_reference": f"data-file:{PurePosixPath(source).as_posix()}",
                    "width": None,
                    "height": None,
                    "lost_alpha": None,
                    "metadata": None,
                },
            )

    project_file_selections = _selection_list(
        expected_profile,
        "project_files",
        errors,
        _PROJECT_FILE_SELECTION_KEYS,
    )
    for index, selection in enumerate(project_file_selections):
        label = f"project_files[{index}]"
        source = _portable_string_field(selection, "source", label, errors)
        output = _string_field(selection, "output", label, errors)
        category = _string_field(selection, "category", label, errors)
        digest = selection.get("expected_sha256")
        if not isinstance(digest, str) or len(digest) != 64 or any(
            character not in "0123456789abcdef" for character in digest
        ):
            errors.append(f"{label}.expected_sha256 must be lowercase SHA-256")
        if source and output and category:
            add_output(
                output,
                label,
                {
                    "category": category,
                    "source_reference": f"project-file:{source}",
                    "sha256": digest,
                    "width": None,
                    "height": None,
                    "lost_alpha": None,
                },
            )

    # Authored Noesis patches travel the same way as the locale pair: an
    # allow-listed project file with a pinned digest, declared in its own
    # profile array so a patch can never be mistaken for a locale overlay.
    xaml_patch_selections = _selection_list(
        expected_profile,
        "xaml_patches",
        errors,
        _PROJECT_FILE_SELECTION_KEYS,
    )
    for index, selection in enumerate(xaml_patch_selections):
        label = f"xaml_patches[{index}]"
        source = _portable_string_field(selection, "source", label, errors)
        output = _string_field(selection, "output", label, errors)
        category = _string_field(selection, "category", label, errors)
        digest = selection.get("expected_sha256")
        if not isinstance(digest, str) or len(digest) != 64 or any(
            character not in "0123456789abcdef" for character in digest
        ):
            errors.append(f"{label}.expected_sha256 must be lowercase SHA-256")
        if category and category != "xaml_patch":
            errors.append(f"{label}.category must be 'xaml_patch'")
        if source and output and category:
            add_output(
                output,
                label,
                {
                    "category": category,
                    "source_reference": f"project-file:{source}",
                    "sha256": digest,
                    "width": None,
                    "height": None,
                    "lost_alpha": None,
                },
            )

    # Sichtrezepte der Mauerarten (2026-09-02) reisen wie die XAML-Patches:
    # allow-listete Projektdatei mit gepinntem Digest, eigene Kategorie.
    for index, selection in enumerate(
        _selection_list(
            expected_profile,
            "fortification_visuals",
            errors,
            _PROJECT_FILE_SELECTION_KEYS,
        )
    ):
        label = f"fortification_visuals[{index}]"
        source = _portable_string_field(selection, "source", label, errors)
        output = _string_field(selection, "output", label, errors)
        category = _string_field(selection, "category", label, errors)
        digest = selection.get("expected_sha256")
        if not isinstance(digest, str) or len(digest) != 64 or any(
            character not in "0123456789abcdef" for character in digest
        ):
            errors.append(f"{label}.expected_sha256 must be lowercase SHA-256")
        if category and category != "fortification_visual":
            errors.append(f"{label}.category must be 'fortification_visual'")
        if source and output and category:
            add_output(
                output,
                label,
                {
                    "category": category,
                    "source_reference": f"project-file:{source}",
                    "sha256": digest,
                    "width": None,
                    "height": None,
                    "lost_alpha": None,
                },
            )

    logo = expected_profile.get("mod_logo")
    if logo is not None:
        if not isinstance(logo, dict):
            errors.append("mod_logo must be an object")
        else:
            if set(logo) != _LOGO_SELECTION_KEYS:
                actual = sorted(repr(field) for field in logo)
                errors.append(
                    f"mod_logo fields changed: actual={actual} "
                    f"expected={sorted(_LOGO_SELECTION_KEYS)}"
                )
            name = _string_field(logo, "name", "mod_logo", errors)
            source_asset = _portable_string_field(
                logo, "source_asset", "mod_logo", errors
            )
            output = _string_field(logo, "output", "mod_logo", errors)
            width = logo.get("canvas_width")
            height = logo.get("canvas_height")
            if type(width) is not int or width <= 0:
                errors.append("mod_logo.canvas_width must be a positive integer")
            if type(height) is not int or height <= 0:
                errors.append("mod_logo.canvas_height must be a positive integer")
            if (
                output
                and name
                and source_asset
                and not compacted_ui_output(output)
            ):
                add_output(
                    output,
                    "mod_logo",
                    {
                        "category": "mod_logo",
                        "width": width,
                        "height": height,
                        "lost_alpha": 0,
                        "metadata": {
                            "kind": "mod_logo_v1",
                            "name": name,
                            "source_asset": source_asset,
                        },
                    },
                )
                entry = declared.get(output)
                reference = (
                    entry.get("source_reference")
                    if isinstance(entry, dict)
                    else None
                )
                reference_ok = isinstance(reference, str) and re.fullmatch(
                    rf"{re.escape(source_asset)}:Texture2D:-?\d+:{re.escape(name)}",
                    reference,
                ) is not None
                checks.append(
                    _check(
                        "profile.logo_source_reference",
                        reference_ok,
                        f"expected_asset={source_asset!r} expected_name={name!r} "
                        f"actual={reference!r}",
                    )
                )

    raw_sparse = expected_profile.get(REVIEW_INDIVIDUAL_SOURCE_ONLY_MODE, [])
    sparse_specs: list[ReviewIndividualSourceOnlySpec] = []
    if not isinstance(raw_sparse, list):
        errors.append(f"{REVIEW_INDIVIDUAL_SOURCE_ONLY_MODE} must be a list")
    else:
        try:
            sparse_specs = [
                ReviewIndividualSourceOnlySpec.from_profile(raw)
                for raw in raw_sparse
            ]
        except (GMAtlasError, AttributeError, OverflowError, TypeError, ValueError) as exc:
            errors.append(f"{REVIEW_INDIVIDUAL_SOURCE_ONLY_MODE}: {exc}")
    sparse_groups = [spec.group.gm_file_name.casefold() for spec in sparse_specs]
    if len(sparse_groups) != len(set(sparse_groups)):
        errors.append(f"{REVIEW_INDIVIDUAL_SOURCE_ONLY_MODE} repeats a group")
    if not streaming and set(sparse_groups) & set(atlas_groups):
        errors.append("a GM group selects both atlas and sparse backends")

    expected_sparse_contracts: set[str] = set()
    dynamic_sparse_paths: set[str] = set()
    for sparse in sparse_specs:
        spec = sparse.group
        policy = spec.review_frame_policy
        assert policy is not None
        group = spec.gm_file_name
        contract_path = f"{REVIEW_INDIVIDUAL_CONTRACT_PREFIX}{group}.json"
        expected_sparse_contracts.add(contract_path)
        add_output(
            contract_path,
            f"sparse.{group}.contract",
            {
                "category": "review_individual_source_contract",
                "source_reference": (
                    f"resources.assets:GM:{group}:"
                    f"full_frames={spec.expected_frame_count}:"
                    f"source_frames={policy.expected_source_frame_count}"
                ),
                "width": None,
                "height": None,
                "lost_alpha": None,
            },
        )

        contract_entry = declared.get(contract_path)
        contract_metadata = (
            contract_entry.get("metadata")
            if isinstance(contract_entry, dict)
            and isinstance(contract_entry.get("metadata"), dict)
            else None
        )
        expected_metadata = {
            "kind": REVIEW_INDIVIDUAL_CONTRACT_KIND,
            "mode": REVIEW_INDIVIDUAL_SOURCE_ONLY_MODE,
            "gm_file_name": group,
            "contract_sha256": (
                contract_entry.get("sha256")
                if isinstance(contract_entry, dict)
                else None
            ),
        }
        checks.append(
            _check(
                f"profile.sparse_contract_metadata.{group}",
                contract_metadata == expected_metadata,
                json.dumps(
                    {"expected": expected_metadata, "actual": contract_metadata},
                    sort_keys=True,
                ),
            )
        )

        contract_document: dict[str, Any] | None = None
        contract_detail = contract_path
        try:
            candidate = json.loads(
                (mod_root / Path(contract_path)).read_text(encoding="utf-8")
            )
            if isinstance(candidate, dict):
                contract_document = candidate
            else:
                contract_detail = "contract root is not an object"
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            contract_detail = str(exc)

        expected_contract_values: dict[str, object] = {
            "schema_version": 1,
            "kind": REVIEW_INDIVIDUAL_CONTRACT_KIND,
            "mode": REVIEW_INDIVIDUAL_SOURCE_ONLY_MODE,
            "gm_file_name": group,
            "loader_manifest.dash_format": spec.dash_format,
            "loader_manifest.mask_policy": spec.mask_policy,
            "loader_manifest.source_texture": spec.source_texture,
            "loader_manifest.target_texture": spec.target_texture,
            "loader_manifest.frame_count": spec.expected_frame_count,
            "loader_manifest.main_count": spec.expected_main_count,
            "loader_manifest.alt_count": spec.expected_alt_count,
            "loader_manifest.max_index": spec.expected_max_index,
            "loader_manifest.array_size": spec.expected_max_index + 1,
            "loader_manifest.names_sha256": spec.expected_names_sha256,
            "loader_manifest.padding": spec.padding,
            "loader_manifest.max_dimension": spec.max_dimension,
            "loader_manifest.category": spec.category,
            "loader_manifest.geometry_policy": spec.geometry_policy,
            "loader_manifest.loader_material_compatible": (
                spec.loader_material_compatible
            ),
            "review_partition.mode": policy.mode,
            "review_partition.proof_algorithm": policy.proof_algorithm,
            "review_partition.source_frame_count": policy.expected_source_frame_count,
            "review_partition.target_frame_count": policy.expected_target_frame_count,
            "review_partition.source_names_sha256": policy.expected_source_names_sha256,
            "review_partition.target_names_sha256": policy.expected_target_names_sha256,
            "review_partition.provenance_sha256": policy.expected_provenance_sha256,
            "review_partition.keep_frame_count": policy.expected_keep_frame_count,
            "review_partition.keep_names_sha256": policy.expected_keep_names_sha256,
            "review_partition.blocked_review_frame_count": (
                policy.expected_blocked_review_frame_count
            ),
            "review_partition.blocked_review_names_sha256": (
                policy.expected_blocked_review_names_sha256
            ),
            "review_partition.fractional_frame_count": (
                policy.expected_fractional_frame_count
            ),
            "review_partition.fractional_names_sha256": (
                policy.expected_fractional_names_sha256
            ),
            "review_partition.action_origin_status_sha256": (
                policy.expected_action_origin_status_sha256
            ),
            "review_partition.action_counts": {
                "REVIEW_MANUAL": policy.expected_source_frame_count
                + policy.expected_blocked_review_frame_count,
                "KEEP_CRUSADER": policy.expected_keep_frame_count,
            },
            "review_partition.status_counts": {
                "AUTO_LOSSLESS_INTEGRAL": policy.expected_source_frame_count,
                "BLOCKED_ALPHA_CLIP": policy.expected_blocked_review_frame_count,
                KEEP_CRUSADER_PROOF_STATUS: policy.expected_keep_frame_count,
            },
            "source_output.frame_count": policy.expected_source_frame_count,
            "source_output.main_count": sparse.expected_source_main_count,
            "source_output.alt_count": sparse.expected_source_alt_count,
            "source_output.names_sha256": policy.expected_source_names_sha256,
            "source_output.main_file_count": policy.expected_source_frame_count,
            "source_output.mask_file_count": policy.expected_source_frame_count,
            "source_output.blocked_and_keep_file_count": 0,
        }
        contract_mismatches = {
            path: {
                "expected": expected,
                "actual": _nested_value(contract_document, path),
            }
            for path, expected in expected_contract_values.items()
            if _nested_value(contract_document, path) != expected
        }
        checks.append(
            _check(
                f"profile.sparse_contract_binding.{group}",
                contract_document is not None and not contract_mismatches,
                json.dumps(contract_mismatches, sort_keys=True)
                if contract_document is not None
                else contract_detail,
            )
        )

        if streaming:
            streamed_group_names.add(group)
            checks.append(
                _check(
                    f"profile.sparse_payload.{group}",
                    True,
                    "payload merged into the exact streamed GM group before Unity",
                )
            )
            continue

        separator = "-" if spec.dash_format else " "
        group_prefix = f"Override/Sprites/{group}{separator}"
        group_paths = {
            relative
            for relative in declared
            if relative.casefold().startswith(group_prefix.casefold())
        }
        main_names: set[str] = set()
        mask_names: set[str] = set()
        invalid_paths: list[str] = []
        for relative in group_paths:
            entry = declared[relative]
            flat = relative[len("Override/Sprites/") :]
            if (
                entry.get("category") == REVIEW_INDIVIDUAL_MAIN_CATEGORY
                and flat.endswith(".png")
                and not flat.endswith("_m.png")
            ):
                name = flat[:-4]
                main_names.add(name)
                dynamic_sparse_paths.add(relative)
            elif (
                entry.get("category") == REVIEW_INDIVIDUAL_MASK_CATEGORY
                and flat.endswith("_m.png")
            ):
                name = flat[:-6]
                mask_names.add(name)
                dynamic_sparse_paths.add(relative)
            else:
                invalid_paths.append(relative)
        slots = [
            parse_loader_frame_name(name, group, spec.dash_format)
            for name in main_names
        ]
        main_count = sum(slot is not None and not slot.is_alt for slot in slots)
        alt_count = sum(slot is not None and slot.is_alt for slot in slots)
        sparse_payload_ok = (
            not invalid_paths
            and main_names == mask_names
            and len(main_names) == policy.expected_source_frame_count
            and all(slot is not None for slot in slots)
            and main_count == sparse.expected_source_main_count
            and alt_count == sparse.expected_source_alt_count
        )
        checks.append(
            _check(
                f"profile.sparse_payload.{group}",
                sparse_payload_ok,
                f"main={len(main_names)} mask={len(mask_names)} "
                f"main_slots={main_count} alt_slots={alt_count} "
                f"invalid={sorted(invalid_paths)}",
            )
        )

    actual_sparse_contracts = {
        relative
        for relative in declared
        if relative.startswith(REVIEW_INDIVIDUAL_CONTRACT_PREFIX)
    }
    checks.append(
        _check(
            "profile.sparse_contract_output_set",
            actual_sparse_contracts == expected_sparse_contracts,
            f"expected={sorted(expected_sparse_contracts)} "
            f"actual={sorted(actual_sparse_contracts)}",
        )
    )

    expected_stream_paths: set[str] = set()
    if streaming:
        if not streamed_group_names:
            errors.append("atlas_backend selects no GM groups")
        built_group_names = set(streamed_group_names)
        omitted_group_names: set[str] = set()
        index_value: dict[str, Any] = {}
        index_group_records: dict[str, dict[str, Any]] = {}
        index_selection_ok = False
        index_selection_detail = "index unavailable"
        try:
            raw_index = (mod_root / INDEX_OUTPUT_PATH).read_bytes()
            if (
                not 1 <= len(raw_index) <= MAX_INDEX_BYTES
                or not raw_index.endswith(b"\n")
                or raw_index.endswith(b"\n\n")
                or raw_index.startswith(b"\xef\xbb\xbf")
                or b"\r" in raw_index
            ):
                raise ValueError("index byte envelope is invalid")
            candidate_index = json.loads(raw_index[:-1].decode("utf-8"))
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
                if bc7_streaming
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
            if (
                not isinstance(candidate_index, dict)
                or raw_index != canonical_json_bytes(candidate_index) + b"\n"
                or set(candidate_index) != expected_root_keys
            ):
                raise ValueError("index root/canonical form is invalid")
            index_value = candidate_index
            if bc7_streaming:
                if atlas_backend is None:
                    raise ValueError("V2 backend disappeared during validation")
                expected_texture_policy = {
                    "id": atlas_backend.texture_policy.id,
                    "main_format": atlas_backend.texture_policy.main_format,
                    "mask_format": atlas_backend.texture_policy.mask_format,
                }
                expected_quality_policy = {
                    "state": atlas_backend.quality_policy.state,
                    "id": atlas_backend.quality_policy.id,
                    "sha256": atlas_backend.quality_policy.sha256,
                    "verifier_id": atlas_backend.quality_policy.verifier_id,
                }
                if (
                    index_value.get("schema") != BC7_INDEX_SCHEMA
                    or index_value.get("backend_kind") != BC7_ATLAS_BACKEND_KIND
                    or index_value.get("build_target") != BUILD_TARGET
                    or index_value.get("packer_id") != BC7_PACKER_ID
                    or index_value.get("encoder_id") != BC7_ENCODER_ID
                    or index_value.get("texture_policy") != expected_texture_policy
                    or index_value.get("quality_policy") != expected_quality_policy
                    or re.fullmatch(
                        r"[0-9a-f]{64}",
                        str(index_value.get("quality_report_sha256", "")),
                    )
                    is None
                ):
                    raise ValueError("V2 index profile/toolchain binding changed")
            raw_built = index_value["groups"]
            raw_omitted = index_value["vanilla_omitted_groups"]
            if (
                not isinstance(raw_built, list)
                or not isinstance(raw_omitted, list)
                or any(not isinstance(item, dict) for item in (*raw_built, *raw_omitted))
            ):
                raise ValueError("index selected group lists are malformed")
            built_order = [item.get("group") for item in raw_built]
            omitted_order = [item.get("group") for item in raw_omitted]
            if (
                any(not isinstance(item, str) for item in (*built_order, *omitted_order))
                or built_order != sorted(built_order)
                or omitted_order != sorted(omitted_order)
            ):
                raise ValueError("index selected group lists are unsorted")
            built_group_names = {str(item) for item in built_order}
            omitted_group_names = {str(item) for item in omitted_order}
            index_group_records = {
                str(item["group"]): item for item in raw_built
            }
            selected = built_group_names | omitted_group_names
            index_selection_ok = (
                not (built_group_names & omitted_group_names)
                and len(selected) == len(built_order) + len(omitted_order)
                and selected == streamed_group_names
            )
            index_selection_detail = (
                f"selected={len(streamed_group_names)} built={len(built_group_names)} "
                f"omitted={len(omitted_group_names)}"
            )
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
            index_selection_detail = str(exc)
        checks.append(
            _check(
                "profile.asset_stream_selected_groups",
                index_selection_ok,
                index_selection_detail,
            )
        )
        expected_stream_paths.add(INDEX_OUTPUT_PATH)
        add_output(
            INDEX_OUTPUT_PATH,
            "atlas_backend.index",
            {
                "category": ASSET_BUNDLE_INDEX_CATEGORY,
                "width": None,
                "height": None,
                "lost_alpha": None,
            },
        )
        for group in sorted(built_group_names):
            slug = canonical_group_slug(group)
            bundle_suffix = BC7_BUNDLE_SUFFIX if bc7_streaming else ".v2"
            relative = f"Runtime/AssetBundles/win64/sede.gm.{slug}{bundle_suffix}"
            expected_stream_paths.add(relative)
            add_output(
                relative,
                f"atlas_backend.bundle.{group}",
                {
                    "category": ASSET_BUNDLE_CATEGORY,
                    "width": None,
                    "height": None,
                    "lost_alpha": None,
                },
            )

        actual_stream_paths = {
            relative
            for relative in declared
            if relative.casefold().startswith("runtime/assetbundles/")
        }
        checks.append(
            _check(
                "profile.asset_stream_output_set",
                actual_stream_paths == expected_stream_paths,
                f"expected={sorted(expected_stream_paths)} "
                f"actual={sorted(actual_stream_paths)}",
            )
        )
        index_entry = declared.get(INDEX_OUTPUT_PATH)
        index_metadata = (
            index_entry.get("metadata")
            if isinstance(index_entry, dict)
            and isinstance(index_entry.get("metadata"), dict)
            else None
        )
        build_id = index_value.get("build_id")
        if bc7_streaming:
            quality_policy = index_value.get("quality_policy")
            texture_policy = index_value.get("texture_policy")
            expected_index_metadata = {
                "kind": BC7_ATLAS_BACKEND_KIND,
                "schema": BC7_INDEX_SCHEMA,
                "build_id": build_id,
                "group_count": len(built_group_names),
                "vanilla_omitted_group_count": len(omitted_group_names),
                "selected_group_count": len(streamed_group_names),
                "index_sha256": (
                    index_entry.get("sha256")
                    if isinstance(index_entry, dict)
                    else None
                ),
                "quality_report_sha256": index_value.get(
                    "quality_report_sha256"
                ),
                "quality_policy_id": (
                    quality_policy.get("id")
                    if isinstance(quality_policy, dict)
                    else None
                ),
                "quality_policy_sha256": (
                    quality_policy.get("sha256")
                    if isinstance(quality_policy, dict)
                    else None
                ),
                "texture_policy_id": (
                    texture_policy.get("id")
                    if isinstance(texture_policy, dict)
                    else None
                ),
                "total_gpu_bytes": index_value.get("total_gpu_bytes"),
                "total_resident_charge_bytes": index_value.get(
                    "total_resident_charge_bytes"
                ),
                "total_source_rgba_bytes": index_value.get(
                    "total_source_rgba_bytes"
                ),
                "packer_id": BC7_PACKER_ID,
                "encoder_id": BC7_ENCODER_ID,
                "unity_version": UNITY_VERSION,
                "unity_revision": UNITY_REVISION,
                "build_target": BUILD_TARGET,
            }
        else:
            expected_index_metadata = {
                "kind": ATLAS_BACKEND_KIND,
                "schema": INDEX_SCHEMA,
                "build_id": build_id,
                "group_count": len(built_group_names),
                "vanilla_omitted_group_count": len(omitted_group_names),
                "selected_group_count": len(streamed_group_names),
                "index_sha256": (
                    index_entry.get("sha256")
                    if isinstance(index_entry, dict)
                    else None
                ),
                "unity_version": UNITY_VERSION,
                "unity_revision": UNITY_REVISION,
                "build_target": BUILD_TARGET,
            }
        index_ok = (
            isinstance(index_entry, dict)
            and isinstance(build_id, str)
            and re.fullmatch(r"[0-9a-f]{64}", build_id) is not None
            and index_metadata == expected_index_metadata
            and index_entry.get("source_reference")
            == f"unity-assetbundle:{build_id}:external-index"
        )
        checks.append(
            _check(
                "profile.asset_stream_index_binding",
                index_ok,
                json.dumps(index_metadata, sort_keys=True),
            )
        )

        seen_gm_ids: set[int] = set()
        invalid_bundles: list[str] = []
        for group in sorted(built_group_names):
            bundle_suffix = BC7_BUNDLE_SUFFIX if bc7_streaming else ".v2"
            bundle = f"sede.gm.{canonical_group_slug(group)}{bundle_suffix}"
            relative = f"Runtime/AssetBundles/win64/{bundle}"
            entry = declared.get(relative)
            metadata = (
                entry.get("metadata")
                if isinstance(entry, dict)
                and isinstance(entry.get("metadata"), dict)
                else None
            )
            gm_id = metadata.get("gm_id") if isinstance(metadata, dict) else None
            raw_group = index_group_records.get(group, {})
            if bc7_streaming:
                texture_policy = index_value.get("texture_policy")
                expected_metadata = {
                    "kind": BC7_ATLAS_BACKEND_KIND,
                    "bundle": bundle,
                    "group": group,
                    "gm_id": raw_group.get("gm_id"),
                    "unity_hash128": raw_group.get("unity_hash128"),
                    "crc32": raw_group.get("bundle_crc32"),
                    "gpu_bytes": raw_group.get("gpu_bytes"),
                    "source_rgba_bytes": raw_group.get("source_rgba_bytes"),
                    "resident_charge_bytes": raw_group.get(
                        "resident_charge_bytes"
                    ),
                    "predicted_load_peak_bytes": raw_group.get(
                        "predicted_load_peak_bytes"
                    ),
                    "texture_policy_id": (
                        texture_policy.get("id")
                        if isinstance(texture_policy, dict)
                        else None
                    ),
                }
                alignment = 4 * 1024 * 1024
            else:
                expected_metadata = {
                    "kind": ATLAS_BACKEND_KIND,
                    "bundle": bundle,
                    "group": group,
                    "gm_id": gm_id,
                    "unity_hash128": (
                        metadata.get("unity_hash128")
                        if isinstance(metadata, dict)
                        else None
                    ),
                    "crc32": (
                        metadata.get("crc32")
                        if isinstance(metadata, dict)
                        else None
                    ),
                    "resident_charge_bytes": (
                        metadata.get("resident_charge_bytes")
                        if isinstance(metadata, dict)
                        else None
                    ),
                }
                alignment = 64 * 1024 * 1024
            if (
                not isinstance(entry, dict)
                or not isinstance(metadata, dict)
                or metadata != expected_metadata
                or isinstance(gm_id, bool)
                or not isinstance(gm_id, int)
                or not 0 <= gm_id <= 233
                or gm_id in seen_gm_ids
                or re.fullmatch(
                    r"[0-9a-f]{32}", str(metadata.get("unity_hash128", ""))
                )
                is None
                or re.fullmatch(
                    r"[0-9a-f]{8}", str(metadata.get("crc32", ""))
                )
                is None
                or isinstance(metadata.get("resident_charge_bytes"), bool)
                or not isinstance(metadata.get("resident_charge_bytes"), int)
                or metadata["resident_charge_bytes"] <= 0
                or metadata["resident_charge_bytes"] % alignment
                or (
                    bc7_streaming
                    and (
                        any(
                            isinstance(metadata.get(field), bool)
                            or not isinstance(metadata.get(field), int)
                            or metadata[field] <= 0
                            for field in (
                                "gpu_bytes",
                                "source_rgba_bytes",
                                "predicted_load_peak_bytes",
                            )
                        )
                    )
                )
                or entry.get("source_reference")
                != f"unity-assetbundle:{build_id}:{bundle}"
            ):
                invalid_bundles.append(relative)
            elif isinstance(gm_id, int):
                seen_gm_ids.add(gm_id)
        checks.append(
            _check(
                "profile.asset_stream_bundle_bindings",
                not invalid_bundles,
                json.dumps(invalid_bundles),
            )
        )
    else:
        unexpected_stream_paths = sorted(
            relative
            for relative in declared
            if relative.casefold().startswith("runtime/assetbundles/")
        )
        checks.append(
            _check(
                "profile.asset_stream_output_set",
                not unexpected_stream_paths,
                json.dumps(unexpected_stream_paths),
            )
        )

    raw_runtime = expected_profile.get("runtime")
    runtime = {
        "enabled": False,
        "audio_payload": False,
        "foliage_tree_apple": False,
        "unit_roster_names": False,
        "farm_placement": False,
        "worker_militia": False,
        "diplomacy": False,
        "fortifications": False,
        "dock_placement": False,
    }
    runtime_shape_ok = raw_runtime is None
    if raw_runtime is not None:
        raw_runtime_keys = set(raw_runtime) if isinstance(raw_runtime, dict) else set()
        optional_runtime_keys = {"diplomacy", "fortifications"}
        required_runtime_keys = _RUNTIME_SELECTION_KEYS - optional_runtime_keys
        runtime_shape_ok = (
            isinstance(raw_runtime, dict)
            and required_runtime_keys <= raw_runtime_keys <= _RUNTIME_SELECTION_KEYS
            and all(isinstance(value, bool) for value in raw_runtime.values())
        )
        if runtime_shape_ok:
            runtime.update(raw_runtime)
            if (
                runtime["diplomacy"]
                and expected_profile.get("id")
                not in _DIPLOMACY_ROLLOUT_PROFILE_IDS
            ):
                runtime_shape_ok = False
            if not runtime["enabled"] and any(
                runtime[key]
                for key in (
                    "audio_payload",
                    "foliage_tree_apple",
                    "unit_roster_names",
                    # Seit 14.08.2026 auch hier gesperrt: runtime_build.py
                    # lehnte enabled=false mit Farm-/Hafenbahn schon immer ab,
                    # dieser Parser liess es durch - die Querregel muss in
                    # beiden Parsern identisch sein.
                    "farm_placement",
                    "worker_militia",
                    "diplomacy",
                    "fortifications",
                    "dock_placement",
                )
            ):
                runtime_shape_ok = False
    if runtime["unit_roster_names"] and project_file_selections:
        runtime_shape_ok = False
    if ui_backend_selected and not runtime["enabled"]:
        runtime_shape_ok = False
    checks.append(
        _check(
            "profile.runtime_selection_shape",
            runtime_shape_ok,
            json.dumps(raw_runtime, sort_keys=True),
        )
    )

    fortification_hud_output = (
        "Patches/Assets/GUI/XAMLResources/HUD_Main.xaml"
    )
    fortification_hud_matches = [
        selection
        for selection in xaml_patch_selections
        if isinstance(selection, dict)
        and selection.get("output") == fortification_hud_output
    ]
    if runtime["fortifications"]:
        expected_fortification_hud_source = (
            "assets/xaml/HUD_Main.xaml"
            if runtime["dock_placement"]
            else "assets/xaml/HUD_Main.fortifications.xaml"
        )
        expected_fortification_hud_sha256 = (
            "2995fd4113e1473259c7020eedccedc2c30b183f032534302b48251834498995"
            if runtime["dock_placement"]
            else "92cb91d42702dba71d3b837eb16fbea2a20bdff71b00f54ca71c122ae389472b"
        )
        fortification_hud_selection_ok = fortification_hud_matches == [
            {
                "source": expected_fortification_hud_source,
                "output": fortification_hud_output,
                "category": "xaml_patch",
                "expected_sha256": expected_fortification_hud_sha256,
            }
        ]
    else:
        fortification_hud_selection_ok = not any(
            selection.get("source")
            in {
                "assets/xaml/HUD_Main.xaml",
                "assets/xaml/HUD_Main.fortifications.xaml",
            }
            for selection in fortification_hud_matches
        )
    checks.append(
        _check(
            "profile.fortification_hud_contributors",
            fortification_hud_selection_ok,
            json.dumps(
                {
                    "fortifications": runtime["fortifications"],
                    "dock": runtime["dock_placement"],
                    "matches": fortification_hud_matches,
                },
                sort_keys=True,
            ),
        )
    )

    # Der Hafen-Regelblock ist Top-Level (Praezedenz: authored_sprites), weil
    # profile.runtime per Vertrag bool-only ist. Abwesenheit = aus. Ein
    # vorhandener Block verlangt runtime.enabled UND runtime.dock_placement
    # und traegt exakt drei ganzzahlige Werte in gesetzten Schranken -
    # dieselbe Pruefung, die runtime_build._validate_dock_placement_rules
    # beim Bauen fail-closed erzwingt.
    raw_dock_rules = expected_profile.get("dock_placement_rules")
    dock_rules_shape_ok = raw_dock_rules is None
    if raw_dock_rules is not None:
        dock_rules_shape_ok = (
            isinstance(raw_dock_rules, dict)
            and set(raw_dock_rules) == {"wood_cost", "gold_cost", "health"}
            and all(
                not isinstance(raw_dock_rules[key], bool)
                and isinstance(raw_dock_rules[key], int)
                for key in ("wood_cost", "gold_cost", "health")
            )
            and 0 <= raw_dock_rules["wood_cost"] <= 1000
            and 0 <= raw_dock_rules["gold_cost"] <= 1000
            and 1 <= raw_dock_rules["health"] <= 100000
            and runtime_shape_ok
            and runtime["enabled"] is True
            and runtime["dock_placement"] is True
        )
    checks.append(
        _check(
            "profile.dock_placement_rules_shape",
            dock_rules_shape_ok,
            json.dumps(raw_dock_rules, sort_keys=True),
        )
    )

    raw_diplomacy_rules = expected_profile.get("diplomacy_rules")
    diplomacy_rules_shape_ok = (
        raw_diplomacy_rules is None
        and not runtime["diplomacy"]
    ) or (
        runtime_shape_ok
        and runtime["enabled"] is True
        and runtime["diplomacy"] is True
        and isinstance(raw_diplomacy_rules, dict)
        and raw_diplomacy_rules == _DIPLOMACY_RULES_V1
        and all(
            not isinstance(value, bool) and isinstance(value, int)
            for value in raw_diplomacy_rules.values()
        )
    )
    checks.append(
        _check(
            "profile.diplomacy_rules_shape",
            diplomacy_rules_shape_ok,
            json.dumps(raw_diplomacy_rules, sort_keys=True),
        )
    )

    expected_runtime_fixed: set[str] = set()
    if runtime["enabled"]:
        expected_runtime_fixed.update(
            {_RUNTIME_DLL_PATH, _RUNTIME_CONTRACT_PATH}
        )
        add_output(
            _RUNTIME_DLL_PATH,
            "runtime.dll",
            {
                "category": "runtime_companion",
                "source_reference": (
                    "runtime/StrongholdEuropeDE.Runtime/"
                    "StrongholdEuropeDE.Runtime.csproj"
                ),
                "width": None,
                "height": None,
                "lost_alpha": None,
            },
        )
        add_output(
            _RUNTIME_CONTRACT_PATH,
            "runtime.contract",
            {
                "category": "runtime_contract",
                "source_reference": (
                    "runtime/StrongholdEuropeDE.Runtime/audio-profile.json"
                ),
                "width": None,
                "height": None,
                "lost_alpha": None,
            },
        )
        if runtime["unit_roster_names"]:
            expected_runtime_fixed.add(_RUNTIME_ROSTER_PATH)
            add_output(
                _RUNTIME_ROSTER_PATH,
                "runtime.roster",
                {
                    "category": "runtime_roster_contract",
                    "source_reference": "config/unit-roster-text.json",
                    "width": None,
                    "height": None,
                    "lost_alpha": None,
                },
            )
        if runtime["fortifications"]:
            expected_runtime_fixed.add(_FORTIFICATION_RUNTIME_PATH)
            add_output(
                _FORTIFICATION_RUNTIME_PATH,
                "runtime.fortifications",
                {
                    "category": "runtime_fortification_contract",
                    "source_reference": _FORTIFICATION_SOURCE_PATH,
                    "size": _FORTIFICATION_V1_TSV_SIZE,
                    "sha256": _FORTIFICATION_V1_TSV_SHA256,
                    "width": None,
                    "height": None,
                    "lost_alpha": None,
                    "metadata": {
                        "kind": _FORTIFICATION_ARTIFACT_KIND,
                        "plugin_id": "strongholdeuropede.runtime.private",
                        "schema": (
                            "stronghold-europe-de.fortification-variants.v1"
                        ),
                        "recipe_version": 1,
                        "variant_count": 9,
                        "record_count": 11,
                        "source_size_bytes": _FORTIFICATION_V1_SOURCE_SIZE,
                        "source_sha256": _FORTIFICATION_V1_SOURCE_SHA256,
                        "catalog_tsv_size": _FORTIFICATION_V1_TSV_SIZE,
                        "catalog_tsv_sha256": _FORTIFICATION_V1_TSV_SHA256,
                    },
                },
            )

    expected_ui_paths: set[str] = set()
    if parsed_ui_manifest is not None:
        expected_ui_paths.add(_RUNTIME_UI_TEXTURE_MANIFEST_PATH)
        add_output(
            _RUNTIME_UI_TEXTURE_MANIFEST_PATH,
            "runtime.ui_texture_manifest",
            {
                "category": "runtime_ui_texture_contract",
                "source_reference": "generated:config/ui-textures-bc7-v1.json",
                "sha256": parsed_ui_manifest.sha256,
                "width": None,
                "height": None,
                "lost_alpha": None,
                "metadata": {
                    "kind": "stronghold_europe_ui_textures_v2",
                    "manifest_sha256": parsed_ui_manifest.sha256,
                    "entry_count": parsed_ui_manifest.entry_count,
                    "bundle_count": len(parsed_ui_manifest.bundles),
                    "declared_gpu_bytes": (
                        parsed_ui_manifest.declared_gpu_bytes
                    ),
                    "declared_resident_charge_bytes": (
                        parsed_ui_manifest.declared_resident_charge_bytes
                    ),
                    "source_manifest_sha256": (
                        parsed_ui_manifest.source_manifest_sha256
                    ),
                    "source_entry_set_sha256": (
                        parsed_ui_manifest.source_entry_set_sha256
                    ),
                    "quality_policy_sha256": (
                        parsed_ui_manifest.quality_policy_sha256
                    ),
                    "editor_source_sha256": (
                        parsed_ui_manifest.editor_source_sha256
                    ),
                },
            },
        )
        for bundle in parsed_ui_manifest.bundles:
            expected_ui_paths.add(bundle.relative_path)
            bundle_name = PurePosixPath(bundle.relative_path).name
            add_output(
                bundle.relative_path,
                f"runtime.ui_texture_bundle.{bundle.entry_id}",
                {
                    "category": "ui_texture_asset_bundle",
                    "source_reference": (
                        "unity-ui-assetbundle:"
                        f"{bundle.entry_id}:{bundle_name}"
                    ),
                    "size": bundle.size_bytes,
                    "sha256": bundle.sha256,
                    "width": None,
                    "height": None,
                    "lost_alpha": None,
                    "metadata": {
                        "kind": UI_BACKEND_KIND,
                        "entry_id": bundle.entry_id,
                        "bundle": bundle_name,
                        "unity_hash128": bundle.unity_hash128,
                        "crc32": bundle.crc32,
                    },
                },
            )
    actual_ui_paths = {
        relative
        for relative in declared
        if relative.casefold()
        in {
            _RUNTIME_UI_TEXTURE_MANIFEST_PATH.casefold(),
            _RUNTIME_UI_TEXTURE_V1_MANIFEST_PATH.casefold(),
        }
        or relative.casefold().startswith(_RUNTIME_UI_BUNDLE_PREFIX.casefold())
    }
    declared_gui_pngs = sorted(
        relative
        for relative in declared
        if relative.casefold().startswith("override/assets/gui/")
        and relative.casefold().endswith(".png")
    )
    gui_root = mod_root / "Override" / "Assets" / "GUI"
    filesystem_gui_pngs = (
        sorted(
            path.relative_to(mod_root).as_posix()
            for path in gui_root.rglob("*")
            if path.is_file() and path.suffix.casefold() == ".png"
        )
        if gui_root.is_dir()
        else []
    )
    checks.append(
        _check(
            "profile.runtime_ui_active_png_set",
            not ui_backend_selected
            or (not declared_gui_pngs and not filesystem_gui_pngs),
            json.dumps(
                {
                    "declared": declared_gui_pngs,
                    "filesystem": filesystem_gui_pngs,
                },
                sort_keys=True,
            ),
        )
    )
    checks.append(
        _check(
            "profile.runtime_ui_stream_output_set",
            actual_ui_paths == expected_ui_paths,
            f"expected={sorted(expected_ui_paths)} actual={sorted(actual_ui_paths)}",
        )
    )

    actual_pcm_paths = {
        relative
        for relative in declared
        if relative.casefold().startswith(_RUNTIME_AUDIO_STREAM_PREFIX.casefold())
    }
    valid_pcm_wavs = {
        relative
        for relative in actual_pcm_paths
        if relative.startswith(_RUNTIME_AUDIO_STREAM_PREFIX)
        and "/" not in relative[len(_RUNTIME_AUDIO_STREAM_PREFIX) :]
        and relative.endswith(".wav")
        and declared[relative].get("category") == "europe_music_pcm_stream"
    }
    expected_pcm_paths: set[str] = set()
    if streaming and runtime["audio_payload"]:
        expected_pcm_paths = valid_pcm_wavs | {_RUNTIME_PCM_MANIFEST_PATH}
        for relative in sorted(valid_pcm_wavs):
            add_output(
                relative,
                f"runtime.pcm.{relative}",
                {
                    "category": "europe_music_pcm_stream",
                    "width": None,
                    "height": None,
                    "lost_alpha": None,
                },
            )
        add_output(
            _RUNTIME_PCM_MANIFEST_PATH,
            "runtime.pcm_manifest",
            {
                "category": "runtime_pcm_stream_contract",
                "source_reference": (
                    "runtime/StrongholdEuropeDE.Runtime/audio-profile.json"
                ),
                "width": None,
                "height": None,
                "lost_alpha": None,
            },
        )
    pcm_ok = (
        actual_pcm_paths == expected_pcm_paths
        and (
            len(valid_pcm_wavs) == _RUNTIME_MUSIC_COUNT
            if streaming and runtime["audio_payload"]
            else not valid_pcm_wavs
        )
    )
    checks.append(
        _check(
            "profile.runtime_pcm_stream_output_set",
            pcm_ok,
            f"selected={streaming and runtime['audio_payload']} "
            f"actual={sorted(actual_pcm_paths)} valid={sorted(valid_pcm_wavs)}",
        )
    )

    actual_music_paths = {
        relative
        for relative in declared
        if relative.casefold().startswith(_RUNTIME_MUSIC_PREFIX.casefold())
    }
    valid_music_paths = {
        relative
        for relative in actual_music_paths
        if relative.startswith(_RUNTIME_MUSIC_PREFIX)
        and "/" not in relative[len(_RUNTIME_MUSIC_PREFIX) :]
        and relative.endswith(".wav")
        and declared[relative].get("category") == "europe_music"
    }
    dynamic_music_paths = (
        valid_music_paths
        if runtime["audio_payload"] and not streaming
        else set()
    )
    music_ok = (
        actual_music_paths == dynamic_music_paths
        and len(dynamic_music_paths)
        == (
            _RUNTIME_MUSIC_COUNT
            if runtime["audio_payload"] and not streaming
            else 0
        )
    )
    checks.append(
        _check(
            "profile.runtime_music_output_set",
            music_ok,
            f"selected={runtime['audio_payload'] and not streaming} "
            f"actual={sorted(actual_music_paths)} valid={sorted(valid_music_paths)}",
        )
    )

    actual_runtime_paths = (
        set(declared)
        & {
            _RUNTIME_DLL_PATH,
            _RUNTIME_CONTRACT_PATH,
            _RUNTIME_ROSTER_PATH,
            _FORTIFICATION_RUNTIME_PATH,
        }
    ) | actual_music_paths | actual_pcm_paths | actual_ui_paths
    expected_runtime_paths = (
        expected_runtime_fixed
        | dynamic_music_paths
        | expected_pcm_paths
        | expected_ui_paths
    )
    checks.append(
        _check(
            "profile.runtime_output_set",
            actual_runtime_paths == expected_runtime_paths,
            f"expected={sorted(expected_runtime_paths)} "
            f"actual={sorted(actual_runtime_paths)}",
        )
    )

    runtime_contract_entry = declared.get(_RUNTIME_CONTRACT_PATH)
    runtime_contract_metadata = (
        runtime_contract_entry.get("metadata")
        if isinstance(runtime_contract_entry, dict)
        and isinstance(runtime_contract_entry.get("metadata"), dict)
        else None
    )
    runtime_dll_entry = declared.get(_RUNTIME_DLL_PATH)
    runtime_dll_metadata = (
        runtime_dll_entry.get("metadata")
        if isinstance(runtime_dll_entry, dict)
        and isinstance(runtime_dll_entry.get("metadata"), dict)
        else None
    )
    legacy_fortification_selection = (
        isinstance(raw_runtime, dict) and "fortifications" not in raw_runtime
    )
    fortification_dll_flags_ok = runtime_dll_metadata is not None and (
        (
            legacy_fortification_selection
            and "fortifications" not in runtime_dll_metadata
            and "fortification_catalog_sha256" not in runtime_dll_metadata
        )
        or (
            runtime_dll_metadata.get("fortifications")
            is runtime["fortifications"]
            and runtime_dll_metadata.get("fortification_catalog_sha256")
            == (
                _FORTIFICATION_V1_TSV_SHA256
                if runtime["fortifications"]
                else ""
            )
        )
    )
    runtime_flags_ok = (
        not runtime["enabled"]
        and runtime_contract_metadata is None
        and runtime_dll_metadata is None
    ) or (
        runtime["enabled"]
        and runtime_contract_metadata is not None
        and runtime_contract_metadata.get("audio_payload")
        is runtime["audio_payload"]
        and runtime_contract_metadata.get("foliage_tree_apple")
        is runtime["foliage_tree_apple"]
        and runtime_dll_metadata is not None
        and runtime_dll_metadata.get("unit_roster_names")
        is runtime["unit_roster_names"]
        and runtime_dll_metadata.get("worker_militia")
        is runtime["worker_militia"]
        and runtime_dll_metadata.get("diplomacy")
        is runtime["diplomacy"]
        and fortification_dll_flags_ok
        and runtime_dll_metadata.get("asset_stream_enabled") is streaming
        and runtime_dll_metadata.get("asset_stream_index_sha256")
        == (
            declared.get(INDEX_OUTPUT_PATH, {}).get("sha256", "")
            if streaming
            else ""
        )
        and runtime_dll_metadata.get("ui_texture_streaming_enabled")
        is ui_backend_selected
        and runtime_dll_metadata.get("ui_texture_manifest_sha256")
        == (
            declared.get(_RUNTIME_UI_TEXTURE_MANIFEST_PATH, {}).get(
                "sha256", ""
            )
            if ui_backend_selected
            else ""
        )
        and runtime_dll_metadata.get("pcm_streaming_enabled")
        is (streaming and runtime["audio_payload"])
        and runtime_dll_metadata.get("pcm_stream_manifest_sha256")
        == (
            declared.get(_RUNTIME_PCM_MANIFEST_PATH, {}).get("sha256", "")
            if streaming and runtime["audio_payload"]
            else ""
        )
    )
    checks.append(
        _check(
            "profile.runtime_flags",
            runtime_flags_ok,
            json.dumps(
                {
                    "expected": runtime,
                    "contract": runtime_contract_metadata,
                    "dll": runtime_dll_metadata,
                },
                sort_keys=True,
            ),
        )
    )

    fortification_entry = declared.get(_FORTIFICATION_RUNTIME_PATH)
    fortification_metadata = (
        fortification_entry.get("metadata")
        if isinstance(fortification_entry, dict)
        and isinstance(fortification_entry.get("metadata"), dict)
        else None
    )
    fortification_catalog_ok = (
        not runtime["fortifications"]
        and fortification_entry is None
    ) or (
        runtime["fortifications"]
        and isinstance(fortification_entry, dict)
        and fortification_metadata is not None
        and fortification_entry.get("size") == _FORTIFICATION_V1_TSV_SIZE
        and fortification_entry.get("sha256") == _FORTIFICATION_V1_TSV_SHA256
        and fortification_metadata.get("catalog_tsv_size")
        == fortification_entry.get("size")
        and fortification_metadata.get("catalog_tsv_sha256")
        == fortification_entry.get("sha256")
        and runtime_dll_metadata is not None
        and runtime_dll_metadata.get("fortification_catalog_sha256")
        == fortification_entry.get("sha256")
    )
    checks.append(
        _check(
            "profile.fortification_catalog_binding",
            fortification_catalog_ok,
            json.dumps(
                {
                    "selected": runtime["fortifications"],
                    "catalog": fortification_entry,
                    "dll_sha256": (
                        runtime_dll_metadata.get(
                            "fortification_catalog_sha256"
                        )
                        if runtime_dll_metadata is not None
                        else None
                    ),
                },
                sort_keys=True,
            ),
        )
    )

    # Was die DLL-Metadaten als Hafen-Regelwerte fuehren, muss woertlich der
    # Profilblock sein - None fuer die reine Messbahn. Ablehnen statt
    # ignorieren: sonst koennte ein Manifest schreibende Regelwerte an einem
    # Profil vorbeitragen, das keine bestellt hat.
    dll_dock_rules = (
        runtime_dll_metadata.get("dock_placement_rules")
        if runtime_dll_metadata is not None
        else None
    )
    checks.append(
        _check(
            "profile.dock_placement_rules_binding",
            dll_dock_rules == raw_dock_rules,
            json.dumps(
                {"profile": raw_dock_rules, "dll": dll_dock_rules},
                sort_keys=True,
            ),
        )
    )
    dll_diplomacy_rules = (
        runtime_dll_metadata.get("diplomacy_rules")
        if runtime_dll_metadata is not None
        else None
    )
    checks.append(
        _check(
            "profile.diplomacy_rules_binding",
            dll_diplomacy_rules == raw_diplomacy_rules,
            json.dumps(
                {
                    "profile": raw_diplomacy_rules,
                    "dll": dll_diplomacy_rules,
                },
                sort_keys=True,
            ),
        )
    )

    if explicit_sprite_paths & dynamic_sparse_paths:
        errors.append("explicit and sparse sprite outputs overlap")
    if explicit_sprite_paths & authored_sprite_paths:
        errors.append("explicit and authored sprite outputs overlap")
    if dynamic_sparse_paths & authored_sprite_paths:
        errors.append("sparse and authored sprite outputs overlap")
    if expected_paths & dynamic_sparse_paths:
        overlap = expected_paths & dynamic_sparse_paths
        if overlap:
            errors.append(f"sparse payload collides with fixed outputs: {sorted(overlap)}")
    if expected_paths & authored_sprite_paths:
        overlap = expected_paths & authored_sprite_paths
        if overlap:
            errors.append(
                f"authored payload collides with fixed outputs: {sorted(overlap)}"
            )
    if expected_paths & dynamic_music_paths:
        overlap = expected_paths & dynamic_music_paths
        if overlap:
            errors.append(f"runtime music collides with fixed outputs: {sorted(overlap)}")

    sprite_expected = (
        explicit_sprite_paths | dynamic_sparse_paths | authored_sprite_paths
    )
    sprite_actual = {
        relative
        for relative in declared
        if relative.casefold().startswith("override/sprites/")
    }
    checks.append(
        _check(
            "profile.sprite_output_set",
            sprite_actual == sprite_expected,
            f"expected={sorted(sprite_expected)} actual={sorted(sprite_actual)}",
        )
    )

    checks.append(
        _check(
            "profile.output_spec_shape",
            not errors,
            json.dumps(errors, sort_keys=True),
        )
    )

    expected_paths.update(dynamic_sparse_paths)
    expected_paths.update(authored_sprite_paths)
    expected_paths.update(dynamic_music_paths)
    checks.append(
        _check(
            "profile.complete_output_set",
            set(declared) == expected_paths,
            f"expected={sorted(expected_paths)} actual={sorted(declared)}",
        )
    )

    for owner, relative, expected_fields in envelopes:
        entry = declared.get(relative)
        mismatches = {
            field: {
                "expected": expected,
                "actual": entry.get(field) if isinstance(entry, dict) else None,
            }
            for field, expected in expected_fields.items()
            if not isinstance(entry, dict) or entry.get(field) != expected
        }
        checks.append(
            _check(
                f"profile.output_envelope.{owner}",
                isinstance(entry, dict) and not mismatches,
                json.dumps(mismatches, sort_keys=True),
            )
        )

    return checks

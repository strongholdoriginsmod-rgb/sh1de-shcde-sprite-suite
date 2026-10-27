from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import asdict, dataclass
import gc
import hashlib
import io
import json
from math import isfinite
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import time
from typing import Any
from xml.etree import ElementTree
from uuid import uuid4

from PIL import Image

from .asset_stream_contract import AssetStreamContractError, parse_atlas_backend
from .asset_stream_builder import (
    AssetStreamBuildError,
    AssetStreamBuildResult,
    _resolve_toolchain,
    build_asset_stream_backend,
)
from .builds import BuildMatch
from .config import BuilderConfig
from .gm_atlas import (
    AUTHORED_SPRITE_CATEGORY,
    AUTHORED_SPRITE_KIND,
    AUTHORED_SPRITE_MASK_CATEGORY,
    AtlasFrame,
    AtlasGroupSpec,
    BuiltAtlas,
    DERIVED_FRAME_POLICY_MODE,
    proof_mismatch as _proof_mismatch,
    raise_collected_proof_mismatches as _raise_collected_proof_mismatches,
    FrameSlot,
    KEEP_CRUSADER_PROOF_STATUS,
    NATIVE_SOURCE_PROOF_STATUS,
    REVIEW_INDIVIDUAL_CONTRACT_KIND,
    REVIEW_INDIVIDUAL_CONTRACT_PREFIX,
    REVIEW_INDIVIDUAL_MAIN_CATEGORY,
    REVIEW_INDIVIDUAL_MASK_CATEGORY,
    REVIEW_INDIVIDUAL_SOURCE_ONLY_MODE,
    REVIEW_FRAME_POLICY_MODE_V2,
    ReviewIndividualSourceOnlySpec,
    SHARED_GM_ATLAS_KIND,
    SHARED_GM_ATLAS_MODE,
    SHARED_GM_ATLAS_PROFILE_KEY,
    SharedGMAtlasSpec,
    SOURCE_FRAME_ORIGIN,
    SOURCE_REMAP_139_CONTRACTS,
    SPARSE_KEEP_POLICY_MODE,
    SPARSE_KEEP_PROOF_ALGORITHM,
    TARGET_FRAME_ORIGIN,
    ValidatedGroup,
    authored_sprite_foot_point,
    authored_sprite_names_digest,
    authored_sprite_payload_digest,
    build_atlas,
    derived_frame_proof_digest,
    frame_overrides_for_spec,
    native_authored_pixels_per_unit,
    native_authored_pivot,
    native_reanchored_pivot,
    native_source_authored_pivot_proof,
    native_source_geometry_contract,
    native_source_geometry_proof,
    parse_loader_frame_name,
    review_individual_payload_digest,
    shared_gm_atlas_proof,
    source_remap_proof,
    source_remap_reference_proof,
    sparse_keep_frame_proof,
    validate_complete_group,
    validate_review_frame_partition,
    validate_shared_gm_atlas,
    write_atlas_json,
    visible_blue_pixel_count,
)
from .atlas_roundtrip import (
    AtlasRoundtripError,
    verify_atlas_roundtrip,
    verify_atlas_roundtrip_files,
)
from .derived_feasibility import DerivedFeasibilityError, assess_derived_sprite
from .hashing import sha256_file
from .loader_groups import LOADER_GROUP_TABLE
from .locale_overlay import (
    MAX_LOCALE_BYTES,
    LocaleOverlay,
    LocaleOverlayError,
    locale_manifest_metadata,
    parse_locale_overlay,
    roster_text_sha256,
)
from .mapping import read_mapping
from .runtime_build import (
    RuntimeBuildError,
    build_runtime_artifacts,
    preflight_runtime_toolchain,
)
from .ui_asset_bundle import (
    UI_BACKEND_KIND,
    UiAssetBundleError,
    UiTextureBackendSelection,
    UiTextureBuildResult,
    UiTextureSourceManifest,
    build_ui_texture_backend,
    load_ui_texture_backend_selection,
    load_ui_texture_source_manifest,
)
from .unity_inventory import _import_unitypy, load_unity_asset


class ModBuildError(RuntimeError):
    """Raised when a profile cannot be rendered without violating invariants."""


@dataclass(frozen=True)
class OutputRecord:
    relative_path: str
    category: str
    size: int
    sha256: str
    width: int | None = None
    height: int | None = None
    source_reference: str | None = None
    lost_alpha: int | None = None
    metadata: dict[str, Any] | None = None


def load_profile(path: Path) -> dict[str, Any]:
    profile = json.loads(path.read_text(encoding="utf-8"))
    if profile.get("schema_version") != 1:
        raise ModBuildError(f"Unsupported profile schema: {profile.get('schema_version')}")
    if not profile.get("id"):
        raise ModBuildError("Profile has no id")
    try:
        parse_atlas_backend(profile)
    except AssetStreamContractError as exc:
        raise ModBuildError(f"Invalid atlas_backend contract: {exc}") from exc
    return profile


def _review_individual_specs(
    profile: dict[str, Any],
) -> list[ReviewIndividualSourceOnlySpec]:
    raw_specs = profile.get(REVIEW_INDIVIDUAL_SOURCE_ONLY_MODE, [])
    if not isinstance(raw_specs, list):
        raise ModBuildError(
            f"Profile key {REVIEW_INDIVIDUAL_SOURCE_ONLY_MODE!r} must be a list"
        )
    specs = [ReviewIndividualSourceOnlySpec.from_profile(raw) for raw in raw_specs]
    names = [spec.group.gm_file_name.casefold() for spec in specs]
    if len(names) != len(set(names)):
        raise ModBuildError(
            "A review individual source-only group is selected more than once"
        )
    return specs


def _shared_gm_specs(profile: dict[str, Any]) -> list[SharedGMAtlasSpec]:
    raw_specs = profile.get(SHARED_GM_ATLAS_PROFILE_KEY, [])
    if not isinstance(raw_specs, list):
        raise ModBuildError(
            f"Profile key {SHARED_GM_ATLAS_PROFILE_KEY!r} must be a list"
        )
    specs = [SharedGMAtlasSpec.from_profile(raw) for raw in raw_specs]
    hosts = [spec.host_gm_file_name.casefold() for spec in specs]
    if len(hosts) != len(set(hosts)):
        raise ModBuildError("A shared GM atlas host is selected more than once")
    claimed = [name.casefold() for spec in specs for name in spec.member_names]
    if len(claimed) != len(set(claimed)):
        raise ModBuildError("A shared GM member is selected more than once")
    return specs


def _validate_group_backend_selection(profile: dict[str, Any]) -> None:
    """Reject ambiguous group ownership before a build transaction is opened."""

    raw_atlases = profile.get("gm_atlases", [])
    if not isinstance(raw_atlases, list):
        raise ModBuildError("Profile key 'gm_atlases' must be a list")
    raw_sparse = profile.get(REVIEW_INDIVIDUAL_SOURCE_ONLY_MODE, [])
    if isinstance(raw_sparse, list):
        atlas_claims = {
            name.casefold()
            for raw in raw_atlases
            if isinstance(raw, dict)
            and isinstance(name := raw.get("gm_file_name"), str)
            and name
        }
        sparse_claims = {
            name.casefold()
            for raw in raw_sparse
            if isinstance(raw, dict)
            and isinstance(name := raw.get("gm_file_name"), str)
            and name
        }
        raw_overlap = sorted(atlas_claims & sparse_claims)
        if raw_overlap:
            # Backend ambiguity outranks backend-specific schema details.  In
            # particular, sparse count pins are intentionally not atlas fields.
            raise ModBuildError(
                "A GM group cannot select atlas and review individual backends "
                f"together: {raw_overlap}"
            )
    atlas_specs = [AtlasGroupSpec.from_profile(raw) for raw in raw_atlases]
    shared_specs = _shared_gm_specs(profile)
    sparse_specs = _review_individual_specs(profile)
    atlas_names = [spec.gm_file_name.casefold() for spec in atlas_specs]
    if len(atlas_names) != len(set(atlas_names)):
        raise ModBuildError("A GM atlas group is selected more than once")
    sparse_names = {spec.group.gm_file_name.casefold() for spec in sparse_specs}
    shared_names = {
        name.casefold() for spec in shared_specs for name in spec.member_names
    }
    overlap = sorted(
        (set(atlas_names) & sparse_names)
        | (set(atlas_names) & shared_names)
        | (sparse_names & shared_names)
    )
    if overlap:
        raise ModBuildError(
            "A GM group cannot select multiple atlas/sparse backends "
            f"together: {overlap}"
        )

    raw_sprites = profile.get("sprites", [])
    if not isinstance(raw_sprites, list):
        raise ModBuildError("Profile key 'sprites' must be a list")
    for selection in raw_sprites:
        if not isinstance(selection, dict):
            raise ModBuildError("Profile sprite selections must be objects")
        selected_name = str(selection.get("name", ""))
        for sparse in sparse_specs:
            group = sparse.group
            if parse_loader_frame_name(
                selected_name, group.gm_file_name, group.dash_format
            ) is not None:
                raise ModBuildError(
                    f"Sparse group {group.gm_file_name} also selects an explicit "
                    f"sprite: {selected_name}"
                )
        for shared in shared_specs:
            for member_name in shared.member_names:
                if parse_loader_frame_name(
                    selected_name, member_name, shared.dash_format
                ) is not None:
                    raise ModBuildError(
                        f"Shared GM member {member_name} also selects an explicit "
                        f"sprite: {selected_name}"
                    )


def _safe_output(root: Path, relative: str) -> Path:
    pure = _canonical_portable_relative_path(relative, "output")
    path = root.joinpath(*pure.parts).resolve()
    resolved_root = root.resolve()
    if path != resolved_root and resolved_root not in path.parents:
        raise ModBuildError(f"Output escapes mod root: {relative}")
    return path


def _safe_sprite_filename(name: str) -> str:
    if not name or any(character in name for character in '<>:"/\\|?*'):
        raise ModBuildError(f"Sprite name is not a safe flat Windows filename: {name!r}")
    return name + ".png"


def _integer_dimension(value: Any, label: str) -> int:
    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ModBuildError(f"Invalid non-integral {label}: {value!r}") from exc
    if not isfinite(number):
        raise ModBuildError(f"Invalid non-integral {label}: {value!r}")
    rounded = round(number)
    if abs(number - rounded) > 1e-3 or rounded <= 0:
        raise ModBuildError(f"Invalid non-integral {label}: {value}")
    return int(rounded)


def _alpha_sum(image: Image.Image) -> int:
    return sum(image.getchannel("A").get_flattened_data())


def adapt_to_target_canvas(
    source_image: Image.Image,
    source_meta: dict[str, Any],
    target_meta: dict[str, Any],
    allow_nontransparent_clip: bool,
) -> tuple[Image.Image, int]:
    source_width = _integer_dimension(source_meta["width"], "source width")
    source_height = _integer_dimension(source_meta["height"], "source height")
    target_width = _integer_dimension(target_meta["width"], "target width")
    target_height = _integer_dimension(target_meta["height"], "target height")
    source_pivot_x = float(source_meta["pivot_x"]) * source_width
    source_pivot_y = float(source_meta["pivot_y"]) * source_height
    target_pivot_x = float(target_meta["pivot_x"]) * target_width
    target_pivot_y = float(target_meta["pivot_y"]) * target_height
    paste_left_float = target_pivot_x - source_pivot_x
    paste_bottom_float = target_pivot_y - source_pivot_y
    paste_left = round(paste_left_float)
    paste_bottom = round(paste_bottom_float)
    if abs(paste_left_float - paste_left) > 1e-3 or abs(paste_bottom_float - paste_bottom) > 1e-3:
        raise ModBuildError(
            "Pivot alignment is not integral: "
            f"left={paste_left_float}, bottom={paste_bottom_float}"
        )

    return adapt_to_target_canvas_at_offset(
        source_image,
        source_meta,
        target_meta,
        paste_left,
        paste_bottom,
        allow_nontransparent_clip,
    )


def keep_native_source_frame(
    source_image: Image.Image,
    source_meta: dict[str, Any],
) -> Image.Image:
    """Return the source frame unchanged, at its own size.

    Used by the `native_source_reanchored_v1` geometry policy. No target canvas is
    involved, so no pixel can be clipped; the caller compensates by writing a
    re-anchored pivot instead. The size check is kept because a decoded frame
    that disagrees with its inventory geometry means the mapping is stale.
    """

    if source_image.mode != "RGBA":
        raise ModBuildError(
            f"Native source frame must already be RGBA: {source_image.mode}"
        )
    source = source_image
    source_width = _integer_dimension(source_meta["width"], "source width")
    source_height = _integer_dimension(source_meta["height"], "source height")
    if source.size != (source_width, source_height):
        raise ModBuildError(
            f"UnityPy sprite image {source.size} differs from logical source rect "
            f"{(source_width, source_height)}"
        )
    return source


def adapt_to_target_canvas_at_offset(
    source_image: Image.Image,
    source_meta: dict[str, Any],
    target_meta: dict[str, Any],
    paste_left: int,
    paste_bottom: int,
    allow_nontransparent_clip: bool,
) -> tuple[Image.Image, int]:
    """Place RGBA pixels at a previously proven integral bottom-left offset."""

    if isinstance(paste_left, bool) or not isinstance(paste_left, int):
        raise ModBuildError(f"paste_left must be integral: {paste_left!r}")
    if isinstance(paste_bottom, bool) or not isinstance(paste_bottom, int):
        raise ModBuildError(f"paste_bottom must be integral: {paste_bottom!r}")
    source = source_image.convert("RGBA")
    source_width = _integer_dimension(source_meta["width"], "source width")
    source_height = _integer_dimension(source_meta["height"], "source height")
    target_width = _integer_dimension(target_meta["width"], "target width")
    target_height = _integer_dimension(target_meta["height"], "target height")
    if source.size != (source_width, source_height):
        raise ModBuildError(
            f"UnityPy sprite image {source.size} differs from logical source rect "
            f"{(source_width, source_height)}"
        )

    source_left = max(0, -paste_left)
    source_bottom = max(0, -paste_bottom)
    source_right = min(source_width, target_width - paste_left)
    source_top = min(source_height, target_height - paste_bottom)
    visible_alpha = 0
    if source_right > source_left and source_top > source_bottom:
        pil_top = source_height - source_top
        pil_bottom = source_height - source_bottom
        visible_alpha = _alpha_sum(source.crop((source_left, pil_top, source_right, pil_bottom)))
    lost_alpha = _alpha_sum(source) - visible_alpha
    if lost_alpha and not allow_nontransparent_clip:
        # Universal-Suite (29.09.2026): im Nachsichtmodus (Standard) wird der
        # Beschnitt gemeldet und vorgenommen; streng (SEDE_STRENG=1) bleibt es
        # eine Ablehnung.
        from .gm_atlas import nachsicht_aktiv

        if not nachsicht_aktiv():
            raise ModBuildError(f"Target canvas would clip alpha sum {lost_alpha}")
        print(
            f"WARNUNG (Nachsicht): Ziel-Leinwand {target_width}x{target_height} beschneidet "
            f"Alpha-Summe {lost_alpha} von {source_meta.get('name', 'Frame')}",
            flush=True,
        )

    canvas = Image.new("RGBA", (target_width, target_height), (0, 0, 0, 0))
    paste_top = target_height - paste_bottom - source_height
    # Raw paste preserves RGB bytes under zero alpha as well as every visible
    # source texel. Pillow clips negative/out-of-bounds destinations to the
    # canvas, and the alpha-loss gate above decides whether that clipping is
    # permitted for this surface.
    canvas.paste(source, (paste_left, paste_top))
    return canvas, lost_alpha


def _texture_objects(environment: Any) -> tuple[dict[int, Any], dict[str, Any], dict[str, dict[str, Any]]]:
    by_id = {obj.path_id: obj for obj in environment.objects}
    by_name: dict[str, Any] = {}
    trees: dict[str, dict[str, Any]] = {}
    for obj in environment.objects:
        if obj.type.name != "Texture2D":
            continue
        tree = obj.read_typetree()
        name = str(tree.get("m_Name", ""))
        by_name[name] = obj
        trees[name] = tree
    return by_id, by_name, trees


def _crop_mask_for_sprite(
    mask_image: Image.Image,
    main_texture_tree: dict[str, Any],
    sprite_tree: dict[str, Any],
    logical_size: tuple[int, int],
    *,
    require_native_size: bool = False,
) -> Image.Image:
    main_width = int(main_texture_tree["m_Width"])
    main_height = int(main_texture_tree["m_Height"])
    scale_x = mask_image.width / main_width
    scale_y = mask_image.height / main_height
    rect = sprite_tree["m_Rect"]
    left = round(float(rect["x"]) * scale_x)
    right = round((float(rect["x"]) + float(rect["width"])) * scale_x)
    bottom = round(float(rect["y"]) * scale_y)
    top_from_bottom = round((float(rect["y"]) + float(rect["height"])) * scale_y)
    top = mask_image.height - top_from_bottom
    bottom_from_top = mask_image.height - bottom
    # Callers decode the atlas once as RGBA.  Converting an 8192x8192 mask for
    # every frame would copy hundreds of gigabytes over a complete GM group.
    rgba_mask = mask_image if mask_image.mode == "RGBA" else mask_image.convert("RGBA")
    crop = rgba_mask.crop((left, top, right, bottom_from_top))
    if crop.size != logical_size:
        if require_native_size:
            raise ModBuildError(
                f"Target mask crop geometry {crop.size} differs from its native "
                f"sprite geometry {logical_size}"
            )
        crop = crop.resize(logical_size, Image.Resampling.NEAREST)
    return crop


def _save_png(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG", optimize=False, compress_level=9)


def _record(
    mod_root: Path,
    path: Path,
    category: str,
    source_reference: str | None = None,
    image: Image.Image | None = None,
    lost_alpha: int | None = None,
    metadata: dict[str, Any] | None = None,
    *,
    # For payloads that are copied byte for byte: the geometry is known but the
    # decoded image is not kept, because a hundred frames of it would be held in
    # memory for nothing.
    width: int | None = None,
    height: int | None = None,
) -> OutputRecord:
    relative = path.relative_to(mod_root).as_posix()
    return OutputRecord(
        relative_path=relative,
        category=category,
        size=path.stat().st_size,
        sha256=sha256_file(path),
        width=image.width if image is not None else width,
        height=image.height if image is not None else height,
        source_reference=source_reference,
        lost_alpha=lost_alpha,
        metadata=metadata,
    )


def _build_sprites(
    config: BuilderConfig,
    mod_root: Path,
    profile: dict[str, Any],
    mapping: dict[str, Any],
) -> list[OutputRecord]:
    proposals = {entry["name"]: entry for entry in mapping["sprites"]}
    grouped: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    for selection in profile.get("sprites", []):
        name = selection["name"]
        proposal = proposals.get(name)
        if proposal is None or proposal["source"] is None:
            raise ModBuildError(f"No source mapping for selected sprite: {name}")
        if proposal["action"] not in {"REPLACE_EXACT", "REPLACE_DERIVED"}:
            raise ModBuildError(f"Selected sprite is not approved for build: {name} ({proposal['action']})")
        grouped[proposal["source"]["texture_name"]].append((selection, proposal))

    UnityPy = _import_unitypy()
    output: list[OutputRecord] = []
    source_asset = config.source.data_dir / "resources.assets"
    for atlas_name, entries in grouped.items():
        environment = load_unity_asset(source_asset, unitypy=UnityPy)
        by_id, texture_by_name, texture_trees = _texture_objects(environment)
        if atlas_name not in texture_by_name:
            raise ModBuildError(f"Source atlas is missing: {atlas_name}")
        mask_needed = any(bool(selection.get("require_mask")) for selection, _ in entries)
        mask_image = None
        if mask_needed:
            mask_name = atlas_name + "_m"
            mask_obj = texture_by_name.get(mask_name)
            if mask_obj is None:
                raise ModBuildError(f"Required source mask atlas is missing: {mask_name}")
            mask_image = mask_obj.read().image.convert("RGBA")

        for selection, proposal in entries:
            source_obj = by_id.get(int(proposal["source"]["path_id"]))
            if source_obj is None or source_obj.type.name != "Sprite":
                raise ModBuildError(f"Source Sprite PathID is missing: {proposal['source']['path_id']}")
            sprite_data = source_obj.read()
            if sprite_data.m_Name != proposal["name"]:
                raise ModBuildError(
                    f"Source PathID/name mismatch: {sprite_data.m_Name} != {proposal['name']}"
                )
            source_image = sprite_data.image.convert("RGBA")
            adapted, lost_alpha = adapt_to_target_canvas(
                source_image,
                proposal["source"],
                proposal["target"],
                bool(selection.get("allow_nontransparent_clip", False)),
            )
            filename = _safe_sprite_filename(proposal["name"])
            sprite_path = _safe_output(mod_root, f"Override/Sprites/{filename}")
            _save_png(adapted, sprite_path)
            output.append(
                _record(
                    mod_root,
                    sprite_path,
                    str(selection["category"]),
                    f"resources.assets:Sprite:{proposal['source']['path_id']}:{proposal['name']}",
                    adapted,
                    lost_alpha,
                )
            )

            if selection.get("require_mask"):
                if mask_image is None:
                    raise ModBuildError(f"No decoded mask for {proposal['name']}")
                sprite_tree = source_obj.read_typetree()
                logical_size = (
                    _integer_dimension(proposal["source"]["width"], "source mask width"),
                    _integer_dimension(proposal["source"]["height"], "source mask height"),
                )
                source_mask = _crop_mask_for_sprite(
                    mask_image,
                    texture_trees[atlas_name],
                    sprite_tree,
                    logical_size,
                )
                adapted_mask, mask_lost_alpha = adapt_to_target_canvas(
                    source_mask,
                    proposal["source"],
                    proposal["target"],
                    bool(selection.get("allow_nontransparent_clip", False)),
                )
                mask_path = _safe_output(
                    mod_root,
                    f"Override/Sprites/{proposal['name']}_m.png",
                )
                _save_png(adapted_mask, mask_path)
                output.append(
                    _record(
                        mod_root,
                        mask_path,
                        str(selection["category"]) + "_team_mask",
                        f"resources.assets:Texture2D:{atlas_name}_m",
                        adapted_mask,
                        mask_lost_alpha,
                    )
                )
        del environment
        del by_id
        del texture_by_name
        del texture_trees
        del mask_image
        gc.collect()
    return output


@dataclass(frozen=True)
class ReviewFrameResult:
    frame: AtlasFrame | None
    origin: str
    proof_status: str
    discarded_mask_alpha: int = 0


def _render_derived_source_candidate(
    proposal: dict[str, Any],
    source_image: Image.Image,
    source_mask: Image.Image | None,
    *,
    require_mask: bool,
    allow_invisible_mask_clip: bool,
) -> tuple[Image.Image, Image.Image | None, dict[str, Any]]:
    """Render one derived frame only after the complete pixel-support proof."""

    if str(proposal.get("action", "")) != "REPLACE_DERIVED":
        raise ModBuildError(
            f"Expected REPLACE_DERIVED source frame: {proposal.get('name')}"
        )
    if require_mask and source_mask is None:
        raise ModBuildError(
            f"Required derived source mask is missing: {proposal.get('name')}"
        )
    try:
        assessment = assess_derived_sprite(
            source_image, proposal, source_mask if require_mask else None
        )
    except DerivedFeasibilityError as exc:
        raise ModBuildError(
            f"Derived geometry proof failed for {proposal.get('name')}: {exc}"
        ) from exc
    status = str(assessment.get("status", ""))
    if status != "AUTO_LOSSLESS_INTEGRAL":
        raise ModBuildError(
            f"Derived frame has no lossless integral render decision: "
            f"{proposal.get('name')} ({status})"
        )
    chosen = assessment.get("chosen_offset")
    if not isinstance(chosen, dict):
        raise ModBuildError(
            f"Derived proof omitted its chosen offset: {proposal.get('name')}"
        )
    main_lost = chosen.get("main_lost_alpha")
    mask_lost = chosen.get("mask_lost_alpha")
    left = chosen.get("paste_left")
    bottom = chosen.get("paste_bottom")
    if main_lost != 0 or mask_lost != 0:
        raise ModBuildError(
            f"Derived proof selected a lossy offset: {proposal.get('name')}"
        )
    if type(left) is not int or type(bottom) is not int:
        raise ModBuildError(
            f"Derived proof selected a non-integral offset: {proposal.get('name')}"
        )

    source_meta = proposal["source"]
    target_meta = proposal["target"]
    adapted, actual_main_lost = adapt_to_target_canvas_at_offset(
        source_image,
        source_meta,
        target_meta,
        left,
        bottom,
        False,
    )
    if actual_main_lost != 0:
        raise ModBuildError(
            f"Derived source frame unexpectedly lost alpha: {proposal.get('name')}"
        )
    adapted_mask = None
    discarded_mask_alpha = 0
    if require_mask:
        assert source_mask is not None
        # ``assess_derived_sprite`` proved that no mask texel sampled by a
        # visible main-sprite texel is clipped. Raw mask padding outside that
        # support is irrelevant to TeamColour rendering, but remains explicitly
        # measured and bound by the derived-frame policy.
        adapted_mask, discarded_mask_alpha = adapt_to_target_canvas_at_offset(
            source_mask,
            source_meta,
            target_meta,
            left,
            bottom,
            allow_invisible_mask_clip,
        )
    proof_row: dict[str, Any] = {
        "name": str(proposal["name"]),
        "status": status,
        "left": left,
        "bottom": bottom,
        "main_lost_alpha": main_lost,
        "mask_lost_alpha": mask_lost,
        "discarded_mask_alpha": discarded_mask_alpha,
    }
    # Apply the same strict row schema used by the manifest and static
    # validator before the rendered pixels can enter an atlas.
    derived_frame_proof_digest([proof_row])
    return adapted, adapted_mask, proof_row


def _read_mapped_sprite(
    objects_by_id: dict[int, Any],
    proposal: dict[str, Any],
    side: str,
    expected_name: str | None = None,
) -> tuple[Any, Image.Image]:
    """Read one mapped Sprite and prove it is the one the mapping names.

    `expected_name` exists for erklaerte Umlenkungen (FRAME_OVERRIDES_139):
    dort liefert ein Frame ANDEREN Namens den Platz, und nur der Aufrufer
    weiss, welcher das laut Tabelle sein muss. Ohne Angabe bleibt es bei der
    Namensgleichheit, die fuer jeden gewoehnlichen Platz gilt.
    """

    metadata = proposal.get(side)
    if not isinstance(metadata, dict):
        raise ModBuildError(
            f"{side.capitalize()} metadata is missing for {proposal.get('name')}"
        )
    path_id = int(metadata["path_id"])
    sprite_object = objects_by_id.get(path_id)
    if sprite_object is None or sprite_object.type.name != "Sprite":
        raise ModBuildError(
            f"{side.capitalize()} Sprite PathID is missing for "
            f"{proposal.get('name')}: {path_id}"
        )
    sprite_data = sprite_object.read()
    wanted = (
        str(expected_name)
        if expected_name is not None
        else str(proposal.get("name", ""))
    )
    if str(sprite_data.m_Name) != wanted:
        raise ModBuildError(
            f"{side.capitalize()} PathID/name mismatch: {sprite_data.m_Name} != "
            f"{wanted}"
        )
    image = sprite_data.image.convert("RGBA")
    expected_size = (
        _integer_dimension(metadata["width"], f"{side} width"),
        _integer_dimension(metadata["height"], f"{side} height"),
    )
    if image.size != expected_size:
        raise ModBuildError(
            f"Decoded {side} sprite geometry differs for {proposal.get('name')}: "
            f"{image.size} != {expected_size}"
        )
    return sprite_object, image


def _render_review_source_candidate(
    proposal: dict[str, Any],
    slot: FrameSlot,
    source_image: Image.Image,
    source_mask: Image.Image | None,
    *,
    require_mask: bool,
) -> ReviewFrameResult:
    """Render only a dynamically proven, integral, lossless SH1DE candidate."""

    if str(proposal.get("action", "")) != "REVIEW_MANUAL":
        raise ModBuildError(
            f"Only REVIEW_MANUAL may use SH1DE review pixels: "
            f"{proposal.get('name')} ({proposal.get('action')})"
        )
    if require_mask and source_mask is None:
        raise ModBuildError(f"Required source mask is missing: {proposal.get('name')}")
    proof_proposal = {**proposal, "action": "REPLACE_DERIVED"}
    try:
        assessment = assess_derived_sprite(
            source_image, proof_proposal, source_mask if require_mask else None
        )
    except DerivedFeasibilityError as exc:
        raise ModBuildError(
            f"Review geometry proof failed for {proposal.get('name')}: {exc}"
        ) from exc
    status = str(assessment.get("status", ""))
    if status == "BLOCKED_ALPHA_CLIP":
        return ReviewFrameResult(
            frame=None,
            origin=TARGET_FRAME_ORIGIN,
            proof_status=status,
        )
    if status != "AUTO_LOSSLESS_INTEGRAL":
        raise ModBuildError(
            f"Review frame has no fail-closed render decision: "
            f"{proposal.get('name')} ({status})"
        )
    chosen = assessment.get("chosen_offset")
    if not isinstance(chosen, dict):
        raise ModBuildError(
            f"Review proof omitted its chosen offset: {proposal.get('name')}"
        )
    if chosen.get("main_lost_alpha") != 0 or chosen.get("mask_lost_alpha") != 0:
        raise ModBuildError(
            f"Review proof reported a lossy selected offset: {proposal.get('name')}"
        )
    left = chosen.get("paste_left")
    bottom = chosen.get("paste_bottom")
    if (
        isinstance(left, bool)
        or not isinstance(left, int)
        or isinstance(bottom, bool)
        or not isinstance(bottom, int)
    ):
        raise ModBuildError(
            f"Review proof selected a non-integral offset: {proposal.get('name')}"
        )
    source_meta = proposal["source"]
    target_meta = proposal["target"]
    adapted, lost_alpha = adapt_to_target_canvas_at_offset(
        source_image,
        source_meta,
        target_meta,
        left,
        bottom,
        False,
    )
    if lost_alpha:
        raise ModBuildError(
            f"Review source frame unexpectedly lost alpha: {proposal.get('name')}"
        )
    adapted_mask = None
    discarded_mask_alpha = 0
    if require_mask:
        assert source_mask is not None
        # The proof already established zero mask loss on every main-alpha
        # texel. Raw mask padding outside that visible support is irrelevant to
        # rendering and may safely fall outside the target canvas.
        adapted_mask, discarded_mask_alpha = adapt_to_target_canvas_at_offset(
            source_mask,
            source_meta,
            target_meta,
            left,
            bottom,
            True,
        )
    return ReviewFrameResult(
        frame=AtlasFrame(
            name=str(proposal["name"]),
            slot=slot,
            image=adapted,
            mask=adapted_mask,
            pivot_x=float(target_meta["pivot_x"]),
            pivot_y=float(target_meta["pivot_y"]),
            pixels_per_unit=float(target_meta["pixels_per_unit"]),
        ),
        origin=SOURCE_FRAME_ORIGIN,
        proof_status=status,
        discarded_mask_alpha=discarded_mask_alpha,
    )


def _render_review_native_source_frame(
    proposal: dict[str, Any],
    slot: FrameSlot,
    source_image: Image.Image,
    source_mask: Image.Image | None,
    *,
    require_mask: bool,
    reanchor: bool = False,
) -> ReviewFrameResult:
    """Render a reviewed SH1DE frame auf seiner eigenen Leinwand.

    Hier gibt es keine Zielleinwand, also auch keine Beschneidung und keine
    Platzierungspruefung, die etwas zu entscheiden haette - dieselbe Begruendung
    wie im Standardpfad bei ``spec.uses_native_geometry``. Pivot und PPU
    stammen unveraendert aus der Quelle. Gemessen am Mapping ist das fuer die
    heute schon ausgelieferten Frames dieselbe Lage wie bisher: die
    Zielleinwand-Platzierung setzt einen Quellpixel u auf ``u - source_pivot``
    relativ zum Anker, der authored Pivot ebenso.

    Diese Funktion kann nie ``frame=None`` liefern; ein Rueckfall auf die
    Crusader-Pixel ist unter V3 ausgeschlossen.
    """

    if str(proposal.get("action", "")) != "REVIEW_MANUAL":
        raise ModBuildError(
            f"Only REVIEW_MANUAL may use native SH1DE review pixels: "
            f"{proposal.get('name')} ({proposal.get('action')})"
        )
    if require_mask and source_mask is None:
        raise ModBuildError(
            f"Required native source mask is missing: {proposal.get('name')}"
        )
    if not require_mask and source_mask is not None:
        raise ModBuildError(
            f"Plain native review frame unexpectedly has a mask: "
            f"{proposal.get('name')}"
        )
    source_meta = proposal.get("source")
    if not isinstance(source_meta, dict):
        raise ModBuildError(
            f"Native review frame is missing source metadata: "
            f"{proposal.get('name')}"
        )
    adapted = keep_native_source_frame(source_image, source_meta)
    adapted_mask = (
        keep_native_source_frame(source_mask, source_meta)
        if source_mask is not None
        else None
    )
    if reanchor:
        # Bauwerke haengen an ihrem Kachelanker, nicht am gezeichneten Pivot.
        # Gemessen an anim_castle: 32 der 95 Spenderframes tragen beidseitig
        # verschiedene Pivots, 28 davon (die Mauerschaefte 094-121) liegen in
        # Crusader bei (0,0) und in Stronghold 1 bei (0,1) - bei gleicher
        # Leinwand von 64x199. Der uebernommene Pivot verschoebe sie um ihre
        # volle Hoehe. Der umgerechnete Anker haelt sie an derselben Stelle,
        # genau wie im Standardpfad bei spec.uses_native_geometry.
        target_meta = proposal.get("target")
        if not isinstance(target_meta, dict):
            raise ModBuildError(
                f"Native review frame is missing target metadata: "
                f"{proposal.get('name')}"
            )
        pivot_x, pivot_y = native_reanchored_pivot(
            source_meta, target_meta, str(proposal["name"])
        )
        output_ppu = float(target_meta["pixels_per_unit"])
    else:
        pivot_x, pivot_y = native_authored_pivot(source_meta)
        output_ppu = native_authored_pixels_per_unit(source_meta)
    return ReviewFrameResult(
        frame=AtlasFrame(
            name=str(proposal["name"]),
            slot=slot,
            image=adapted,
            mask=adapted_mask,
            pivot_x=pivot_x,
            pivot_y=pivot_y,
            pixels_per_unit=output_ppu,
        ),
        origin=SOURCE_FRAME_ORIGIN,
        proof_status=NATIVE_SOURCE_PROOF_STATUS,
        discarded_mask_alpha=0,
    )


def _render_review_target_passthrough(
    proposal: dict[str, Any],
    slot: FrameSlot,
    target_image: Image.Image,
    target_mask: Image.Image | None,
    *,
    require_mask: bool,
    proof_status: str,
) -> ReviewFrameResult:
    """Keep an approved target frame byte-identical to its SHCDE sprite."""

    if proof_status not in {"BLOCKED_ALPHA_CLIP", KEEP_CRUSADER_PROOF_STATUS}:
        raise ModBuildError(
            f"Unsupported target passthrough status for {proposal.get('name')}: "
            f"{proof_status!r}"
        )

    target_meta = proposal["target"]
    target_size = (
        _integer_dimension(target_meta["width"], "target width"),
        _integer_dimension(target_meta["height"], "target height"),
    )
    rgba = target_image.convert("RGBA")
    if rgba.size != target_size:
        raise ModBuildError(
            f"Target passthrough geometry differs for {proposal.get('name')}: "
            f"{rgba.size} != {target_size}"
        )
    mask_rgba = target_mask.convert("RGBA") if target_mask is not None else None
    if require_mask and (mask_rgba is None or mask_rgba.size != target_size):
        raise ModBuildError(
            f"Target passthrough mask differs for {proposal.get('name')}"
        )
    if not require_mask and mask_rgba is not None:
        raise ModBuildError(
            f"Plain target passthrough unexpectedly has a mask: {proposal.get('name')}"
        )
    return ReviewFrameResult(
        frame=AtlasFrame(
            name=str(proposal["name"]),
            slot=slot,
            image=rgba,
            mask=mask_rgba,
            pivot_x=float(target_meta["pivot_x"]),
            pivot_y=float(target_meta["pivot_y"]),
            pixels_per_unit=float(target_meta["pixels_per_unit"]),
        ),
        origin=TARGET_FRAME_ORIGIN,
        proof_status=proof_status,
    )


def _native_source_geometry_metadata(
    spec: AtlasGroupSpec,
    native_proof_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Halte den nativen Beweis gegen den eingefrorenen Vertrag.

    Bewusst genau eine Stelle: der Standardpfad und der Review-Pfad (V3)
    vergleichen denselben Vertrag. Zwei Kopien dieses Vergleichs waren in
    diesem Projekt schon zweimal die Fehlerquelle.
    """

    policy = spec.native_source_geometry_policy
    if policy is None:
        raise ModBuildError(
            f"Native frames have no frozen policy: {spec.gm_file_name}"
        )
    native_contract = native_source_geometry_contract(
        spec.gm_file_name, policy.mode
    )
    if native_contract is None:
        raise ModBuildError(
            f"No native source contract for {spec.gm_file_name} "
            f"under {policy.mode}"
        )
    proof = (
        native_source_authored_pivot_proof(native_proof_rows)
        if spec.uses_authored_source_geometry
        else native_source_geometry_proof(
            native_proof_rows,
            source_anchor_tolerance_px=(
                native_contract.source_anchor_tolerance_px
            ),
        )
    )
    actual_contract = (
        proof["frame_count"],
        proof["geometry_proof_sha256"],
        proof["origin_proof_sha256"],
        proof["source_rgba_sha256"],
        proof["target_origin_count"],
    )
    expected_contract = (
        policy.expected_frame_count,
        policy.expected_geometry_proof_sha256,
        policy.expected_origin_proof_sha256,
        policy.expected_source_rgba_sha256,
        0,
    )
    if actual_contract != expected_contract:
        _proof_mismatch(
            f"Native source geometry proof changed for "
            f"{spec.gm_file_name}: actual={actual_contract} "
            f"expected={expected_contract}"
        )
    expected_source_error = native_contract.expected_source_anchor_max_error_px
    if (
        expected_source_error is not None
        and proof.get("source_anchor_max_error_px") != expected_source_error
    ):
        raise ModBuildError(
            f"Native source anchor maximum changed for "
            f"{spec.gm_file_name}: actual="
            f"{proof['source_anchor_max_error_px']} expected="
            f"{expected_source_error}"
        )
    return {
        "mode": policy.mode,
        "proof_algorithm": policy.proof_algorithm,
        **proof,
        "native_rgba_exact": True,
        "target_canvas_used": False,
        "clipping": False,
        "resampling": "none",
        "frame_proofs": native_proof_rows,
    }


def _emit_gm_atlas(
    mod_root: Path,
    validated: ValidatedGroup,
    frames: list[AtlasFrame],
    *,
    shared_source_texture_group_count: int,
    review_frame_policy: dict[str, Any] | None = None,
    derived_frame_policy: dict[str, Any] | None = None,
    native_source_geometry_policy: dict[str, Any] | None = None,
    source_remap_policy: dict[str, Any] | None = None,
    shared_gm_atlas_policy: dict[str, Any] | None = None,
    sparse_keep_policy: dict[str, Any] | None = None,
) -> list[OutputRecord]:
    # sparse_keep_policy is deliberately absent from this set: it does not
    # describe how European art was converted, it records which Crusader slots
    # were copied byte for byte so the GM array keeps its full length.  It
    # therefore coexists with whichever conversion policy the group uses.
    selected_policies = {
        name
        for name, policy in (
            ("review", review_frame_policy),
            ("derived", derived_frame_policy),
            ("native", native_source_geometry_policy),
            ("source_remap", source_remap_policy),
            ("shared_gm", shared_gm_atlas_policy),
        )
        if policy is not None
    }
    # {"review", "native"} ist die V3-Kombination: der Review-Block sagt, WELCHER
    # Slot aus Europa kommt, der native Block sagt, WIE gerendert wurde. Die
    # beiden treffen verschiedene Aussagen und schliessen sich deshalb nicht
    # aus. Der zweite Waechter dazu steht in AtlasGroupSpec.from_profile
    # (gm_atlas.py) und laesst diese Kombination nur fuer eine freigegebene
    # Gruppe unter Modus V3 mit authored Pivot zu; beide gehoeren zusammen.
    if len(selected_policies) > 1 and selected_policies not in (
        {"derived", "source_remap"},
        {"review", "native"},
    ):
        raise ModBuildError(
            f"Atlas cannot combine geometry/provenance policies: "
            f"{validated.spec.gm_file_name}"
        )
    spec = validated.spec
    if (spec.sparse_keep_frame_count is None) != (sparse_keep_policy is None):
        raise ModBuildError(
            f"Sparse keep declaration and provenance disagree for "
            f"{spec.gm_file_name}: declared="
            f"{spec.sparse_keep_frame_count} provenance="
            f"{None if sparse_keep_policy is None else sparse_keep_policy.get('frame_count')}"
        )
    built = build_atlas(validated, frames)
    _verify_built_gm_atlas_roundtrip(built, frames)
    atlas_dir = _safe_output(mod_root, f"Override/Atlas/{spec.gm_file_name}")
    atlas_path = atlas_dir / "atlas.png"
    json_path = atlas_dir / "atlas.json"
    mask_path = atlas_dir / "atlas_m.png"
    _save_png(built.image, atlas_path)
    write_atlas_json(built.atlas_json, json_path)
    if built.mask is not None:
        _save_png(built.mask, mask_path)

    roundtrip_metadata = _verify_serialized_gm_atlas_roundtrip(
        built,
        frames,
        atlas_path,
        json_path,
        mask_path if built.mask is not None else None,
    )
    source_reference = (
        f"resources.assets:GM:{spec.gm_file_name}:"
        f"frames={len(built.placements)}:regions={built.unique_region_count}:"
        f"names_sha256={built.names_sha256}"
    )
    metadata: dict[str, Any] = {
        "kind": (
            SHARED_GM_ATLAS_KIND
            if shared_gm_atlas_policy is not None
            else "shcdese_gm_atlas_1_39"
        ),
        "gm_file_name": spec.gm_file_name,
        "source_texture": spec.source_texture,
        "target_texture": spec.target_texture,
        "dash_format": spec.dash_format,
        "mask_policy": spec.mask_policy,
        "geometry_policy": spec.geometry_policy,
        "frame_count": len(built.placements),
        "main_count": sum(not item.slot.is_alt for item in built.placements),
        "alt_count": sum(item.slot.is_alt for item in built.placements),
        "array_size": built.array_size,
        "names_sha256": built.names_sha256,
        "unique_region_count": built.unique_region_count,
        "padding": spec.padding,
        "max_dimension": spec.max_dimension,
        "category": spec.category,
        "atlas_width": built.image.width,
        "atlas_height": built.image.height,
        "loader_material_compatible": spec.loader_material_compatible,
        "shared_source_texture_group_count": shared_source_texture_group_count,
        "roundtrip": roundtrip_metadata,
    }
    if spec.sparse_keep_frame_count is not None:
        metadata["sparse_keep_frame_count"] = spec.sparse_keep_frame_count
    if sparse_keep_policy is not None:
        metadata["sparse_keep_policy"] = sparse_keep_policy
    if review_frame_policy is not None:
        metadata["review_frame_policy"] = review_frame_policy
    if derived_frame_policy is not None:
        metadata["derived_frame_policy"] = derived_frame_policy
    if native_source_geometry_policy is not None:
        metadata["native_source_geometry_policy"] = native_source_geometry_policy
    if source_remap_policy is not None:
        metadata["source_remap_policy"] = source_remap_policy
    if shared_gm_atlas_policy is not None:
        metadata["shared_gm_atlas_policy"] = shared_gm_atlas_policy

    records = [
        _record(
            mod_root,
            atlas_path,
            spec.category,
            source_reference,
            built.image,
            0,
        ),
        _record(
            mod_root,
            json_path,
            spec.category + "_frames",
            source_reference,
            metadata=metadata,
        ),
    ]
    if built.mask is not None:
        records.append(
            _record(
                mod_root,
                mask_path,
                spec.category + "_team_mask",
                (
                    f"resources.assets:Texture2D:{spec.source_texture}_m"
                    if review_frame_policy is None
                    else (
                        "resources.assets:Texture2D:mixed:"
                        f"{spec.source_texture}_m+{spec.target_texture}_m"
                    )
                ),
                built.mask,
                0,
            )
        )
    return records


def _build_gm_atlases(
    config: BuilderConfig,
    mod_root: Path,
    profile: dict[str, Any],
    mapping: dict[str, Any],
) -> list[OutputRecord]:
    raw_specs = profile.get("gm_atlases", [])
    if not raw_specs:
        return []

    specs = [AtlasGroupSpec.from_profile(raw) for raw in raw_specs]
    names = [spec.gm_file_name.casefold() for spec in specs]
    if len(names) != len(set(names)):
        raise ModBuildError("A GM atlas group is selected more than once")

    UnityPy = _import_unitypy()
    source_asset = config.source.data_dir / "resources.assets"
    output: list[OutputRecord] = []
    standard_specs = [spec for spec in specs if spec.review_frame_policy is None]
    review_specs = [spec for spec in specs if spec.review_frame_policy is not None]
    shared_specs = _shared_gm_specs(profile)
    all_source_textures = {
        spec.source_texture for spec in [*specs, *shared_specs]
    }
    source_group_counts = {
        source_texture: sum(
            spec.source_texture == source_texture
            for spec in [*specs, *shared_specs]
        )
        for source_texture in all_source_textures
    }
    grouped_specs = _group_gm_specs_by_source_texture(
        standard_specs, mapping["sprites"]
    )
    deferred_keep_groups: list[
        tuple[
            ValidatedGroup,
            list[AtlasFrame],
            list[tuple[dict[str, Any], FrameSlot]],
            dict[str, Any],
        ]
    ] = []
    mapping_by_name = {
        str(proposal.get("name", "")): proposal
        for proposal in mapping["sprites"]
    }

    # Loading one 8192x8192 atlas and its mask can consume hundreds of MB.
    # Keep that UnityPy environment/cache alive for every GM group backed by
    # the same source texture, then release it once.  The complete body8 profile
    # therefore decodes body8Sprites/body8Sprites_m exactly once, not 12 times.
    for source_texture, shared_specs, environment in _load_atlas_environment_batches(
        UnityPy, source_asset, grouped_specs
    ):
        by_id, texture_by_name, texture_trees = _texture_objects(environment)
        if source_texture not in texture_by_name:
            raise ModBuildError(
                f"Shared source atlas is missing: {source_texture}"
            )

        mask_image = None
        mask_name = source_texture + "_m"
        if any(spec.require_mask for spec, _ in shared_specs):
            mask_obj = texture_by_name.get(mask_name)
            if mask_obj is None:
                raise ModBuildError(
                    f"Required shared source mask atlas is missing: {mask_name}"
                )
            mask_image = mask_obj.read().image.convert("RGBA")

        main_texture_tree = texture_trees[source_texture]
        for spec, validated in shared_specs:
            frames: list[AtlasFrame] = []
            derived_proof_rows: list[dict[str, Any]] = []
            native_proof_rows: list[dict[str, Any]] = []
            source_remap_proof_rows: list[dict[str, Any]] = []
            remap_contract = SOURCE_REMAP_139_CONTRACTS.get(
                spec.gm_file_name
            )
            remap_by_target = (
                {frame.target_name: frame for frame in remap_contract.frames}
                if spec.source_remap_policy is not None
                and remap_contract is not None
                else {}
            )
            # Erklaerte Umlenkungen der Gruppe (FRAME_OVERRIDES_139). Sie
            # kommen bereits umgelenkt hier an - gm_atlas hat den Vorschlag vor
            # jeder Pruefung gegen den anderen Spender neu gebaut. Der Bauer
            # muss davon nur eines wissen: dass das gelesene Sprite dann nicht
            # mehr so heisst wie sein Zielplatz. Ohne diese Tabelle bricht er
            # mit "Source PathID/name mismatch" ab, und genau daran ist der
            # Umlenk-Zweig bis zum 20.08.2026 gescheitert.
            override_donors = {
                override.target_name: override.donor_name
                for override in frame_overrides_for_spec(spec)
                if override.donor_name is not None
            }
            validated_names = {
                str(proposal["name"]) for proposal in validated.proposals
            }
            if set(override_donors) - validated_names:
                raise ModBuildError(
                    f"Frame-override targets are outside {spec.gm_file_name}: "
                    f"{sorted(set(override_donors) - validated_names)}"
                )
            if set(remap_by_target) - validated_names:
                raise ModBuildError(
                    f"Source remap targets are outside {spec.gm_file_name}: "
                    f"{sorted(set(remap_by_target) - validated_names)}"
                )
            keep_pending: list[tuple[dict[str, Any], FrameSlot]] = []
            for proposal, slot in zip(
                validated.proposals, validated.slots, strict=True
            ):
                if str(proposal.get("action", "")) == "KEEP_CRUSADER":
                    # Europe has no counterpart for this slot. It still has to
                    # appear in the atlas: ApplySingle sizes the GM array from
                    # our highest index, so leaving the tail out would truncate
                    # the array and delete those sprites. Rendered from the
                    # target game after the source atlas is released.
                    keep_pending.append((proposal, slot))
                    continue
                remap_frame = remap_by_target.get(str(proposal["name"]))
                source_proposal = proposal
                if remap_frame is not None:
                    source_proposal = mapping_by_name.get(
                        remap_frame.source_name
                    )
                    if (
                        not isinstance(source_proposal, dict)
                        or source_proposal.get("group") != spec.gm_file_name
                        or not isinstance(source_proposal.get("source"), dict)
                    ):
                        raise ModBuildError(
                            f"Reviewed source-remap donor is unavailable: "
                            f"{remap_frame.source_name}"
                        )
                    # PathIDs belong to this installed asset file. The reviewed
                    # target/donor names select the art; current IDs stay in the
                    # per-build proof and may change after a game repack.
                source_meta = source_proposal["source"]
                source_id = int(source_meta["path_id"])
                source_obj = by_id.get(source_id)
                if source_obj is None or source_obj.type.name != "Sprite":
                    raise ModBuildError(
                        f"Source Sprite PathID is missing for {proposal['name']}: "
                        f"{source_id}"
                    )
                sprite_data = source_obj.read()
                override_donor = override_donors.get(str(proposal["name"]))
                expected_source_name = (
                    remap_frame.source_name
                    if remap_frame is not None
                    else override_donor
                    if override_donor is not None
                    else str(proposal["name"])
                )
                if sprite_data.m_Name != expected_source_name:
                    raise ModBuildError(
                        f"Source PathID/name mismatch: {sprite_data.m_Name} != "
                        f"{expected_source_name}"
                    )
                parsed = parse_loader_frame_name(
                    sprite_data.m_Name, spec.gm_file_name, spec.dash_format
                )
                if (
                    remap_frame is None
                    and override_donor is None
                    and parsed != slot
                ):
                    raise ModBuildError(
                        f"Source frame would reach a different loader slot: "
                        f"{sprite_data.m_Name}"
                    )

                source_image = sprite_data.image.convert("RGBA")
                source_mask = None
                if spec.require_mask:
                    if mask_image is None:
                        raise ModBuildError(f"No decoded mask for {proposal['name']}")
                    logical_size = (
                        _integer_dimension(
                            source_meta["width"], "source mask width"
                        ),
                        _integer_dimension(
                            source_meta["height"], "source mask height"
                        ),
                    )
                    source_mask = _crop_mask_for_sprite(
                        mask_image,
                        main_texture_tree,
                        source_obj.read_typetree(),
                        logical_size,
                        require_native_size=spec.uses_native_geometry,
                    )

                if spec.uses_native_geometry:
                    # Checked before the derived branch on purpose: under this
                    # policy there is no target canvas, so the integral-placement
                    # proof that branch performs has nothing to decide. The canvas
                    # is the art, clipping is impossible, and the caller
                    # compensates with a re-anchored pivot.
                    adapted = keep_native_source_frame(
                        source_image, source_meta
                    )
                    adapted_mask = (
                        keep_native_source_frame(source_mask, source_meta)
                        if source_mask is not None
                        else None
                    )
                elif remap_frame is not None:
                    remapped_proposal = {
                        **proposal,
                        "action": "REPLACE_DERIVED",
                        "source": source_meta,
                    }
                    adapted, adapted_mask, proof_row = (
                        _render_derived_source_candidate(
                            remapped_proposal,
                            source_image,
                            source_mask,
                            require_mask=spec.require_mask,
                            allow_invisible_mask_clip=False,
                        )
                    )
                    derived_proof_rows.append(proof_row)
                    source_sha256 = hashlib.sha256(
                        source_image.tobytes()
                    ).hexdigest()
                    output_sha256 = hashlib.sha256(
                        adapted.tobytes()
                    ).hexdigest()
                    target_meta = proposal["target"]
                    source_remap_proof_rows.append(
                        {
                            "target_name": str(proposal["name"]),
                            "source_name": remap_frame.source_name,
                            "target_path_id": int(target_meta["path_id"]),
                            "source_path_id": source_id,
                            "source_texture": str(
                                source_meta["texture_name"]
                            ),
                            "target_texture": str(
                                target_meta["texture_name"]
                            ),
                            "source_width": _integer_dimension(
                                source_meta["width"], "remap source width"
                            ),
                            "source_height": _integer_dimension(
                                source_meta["height"], "remap source height"
                            ),
                            "target_width": _integer_dimension(
                                target_meta["width"], "remap target width"
                            ),
                            "target_height": _integer_dimension(
                                target_meta["height"], "remap target height"
                            ),
                            "source_pivot_x": float(source_meta["pivot_x"]),
                            "source_pivot_y": float(source_meta["pivot_y"]),
                            "target_pivot_x": float(target_meta["pivot_x"]),
                            "target_pivot_y": float(target_meta["pivot_y"]),
                            "source_pixels_per_unit": float(
                                source_meta["pixels_per_unit"]
                            ),
                            "target_pixels_per_unit": float(
                                target_meta["pixels_per_unit"]
                            ),
                            "source_rgba_sha256": source_sha256,
                            "output_rgba_sha256": output_sha256,
                            "visible_blue_pixel_count": (
                                visible_blue_pixel_count(adapted)
                            ),
                        }
                    )
                elif proposal.get("action") == "REPLACE_DERIVED":
                    adapted, adapted_mask, proof_row = (
                        _render_derived_source_candidate(
                            proposal,
                            source_image,
                            source_mask,
                            require_mask=spec.require_mask,
                            allow_invisible_mask_clip=(
                                spec.derived_frame_policy is not None
                            ),
                        )
                    )
                    derived_proof_rows.append(proof_row)
                else:
                    adapted, lost_alpha = adapt_to_target_canvas(
                        source_image,
                        source_meta,
                        proposal["target"],
                        allow_nontransparent_clip=False,
                    )
                    if lost_alpha:
                        raise ModBuildError(
                            f"GM atlas frame unexpectedly lost alpha: "
                            f"{proposal['name']}"
                        )
                    adapted_mask = None
                    if source_mask is not None:
                        adapted_mask, mask_lost_alpha = adapt_to_target_canvas(
                            source_mask,
                            source_meta,
                            proposal["target"],
                            allow_nontransparent_clip=False,
                        )
                        if mask_lost_alpha:
                            raise ModBuildError(
                                f"GM atlas team mask unexpectedly lost alpha: "
                                f"{proposal['name']}"
                            )

                if spec.require_mask and adapted_mask is None:
                    raise ModBuildError(
                        f"GM atlas team mask was not rendered: {proposal['name']}"
                    )

                target = proposal["target"]
                source = source_meta
                if spec.uses_authored_source_geometry:
                    pivot_x, pivot_y = native_authored_pivot(source)
                    output_ppu = native_authored_pixels_per_unit(source)
                elif spec.uses_native_geometry:
                    pivot_x, pivot_y = native_reanchored_pivot(
                        source, target, str(proposal["name"])
                    )
                    output_ppu = float(target["pixels_per_unit"])
                else:
                    pivot_x = float(target["pivot_x"])
                    pivot_y = float(target["pivot_y"])
                    output_ppu = float(target["pixels_per_unit"])
                frames.append(
                    AtlasFrame(
                        name=str(proposal["name"]),
                        slot=slot,
                        image=adapted,
                        mask=adapted_mask,
                        pivot_x=pivot_x,
                        pivot_y=pivot_y,
                        pixels_per_unit=output_ppu,
                    )
                )
                if spec.uses_authored_source_geometry:
                    native_proof_rows.append(
                        {
                            "name": str(proposal["name"]),
                            "origin": SOURCE_FRAME_ORIGIN,
                            "source_width": _integer_dimension(
                                source["width"], "native source width"
                            ),
                            "source_height": _integer_dimension(
                                source["height"], "native source height"
                            ),
                            "source_pivot_x": float(source["pivot_x"]),
                            "source_pivot_y": float(source["pivot_y"]),
                            "output_pivot_x": pivot_x,
                            "output_pivot_y": pivot_y,
                            "source_pixels_per_unit": float(
                                source["pixels_per_unit"]
                            ),
                            "output_pixels_per_unit": output_ppu,
                            "source_rgba_sha256": hashlib.sha256(
                                adapted.tobytes()
                            ).hexdigest(),
                        }
                    )
                elif spec.uses_native_geometry:
                    native_proof_rows.append(
                        {
                            "name": str(proposal["name"]),
                            "origin": SOURCE_FRAME_ORIGIN,
                            "source_width": _integer_dimension(
                                source["width"], "native source width"
                            ),
                            "source_height": _integer_dimension(
                                source["height"], "native source height"
                            ),
                            "target_width": _integer_dimension(
                                target["width"], "native target width"
                            ),
                            "target_height": _integer_dimension(
                                target["height"], "native target height"
                            ),
                            "source_pivot_x": float(source["pivot_x"]),
                            "source_pivot_y": float(source["pivot_y"]),
                            "target_pivot_x": float(target["pivot_x"]),
                            "target_pivot_y": float(target["pivot_y"]),
                            "output_pivot_x": pivot_x,
                            "output_pivot_y": pivot_y,
                            "source_pixels_per_unit": float(
                                source["pixels_per_unit"]
                            ),
                            "target_pixels_per_unit": output_ppu,
                            "output_pixels_per_unit": output_ppu,
                            "source_rgba_sha256": hashlib.sha256(
                                adapted.tobytes()
                            ).hexdigest(),
                        }
                    )

            derived_metadata = None
            if spec.derived_frame_policy is not None:
                policy = spec.derived_frame_policy
                proof_digest = derived_frame_proof_digest(derived_proof_rows)
                discarded_total = sum(
                    row["discarded_mask_alpha"] for row in derived_proof_rows
                )
                actual_contract = (
                    len(derived_proof_rows),
                    discarded_total,
                    proof_digest,
                )
                expected_contract = (
                    policy.expected_frame_count,
                    policy.expected_discarded_mask_alpha,
                    policy.expected_frame_proof_sha256,
                )
                if actual_contract != expected_contract:
                    _proof_mismatch(
                        f"Derived frame proof changed for {spec.gm_file_name}: "
                        f"actual={actual_contract} expected={expected_contract}"
                    )
                derived_metadata = {
                    "mode": DERIVED_FRAME_POLICY_MODE,
                    "proof_algorithm": policy.proof_algorithm,
                    "frame_count": len(derived_proof_rows),
                    "discarded_mask_alpha": discarded_total,
                    "frame_proof_sha256": proof_digest,
                    "frame_proofs": derived_proof_rows,
                }
            elif derived_proof_rows:
                # Existing derived groups remain dynamically fail-closed even
                # before they receive an independently frozen proof contract.
                derived_frame_proof_digest(derived_proof_rows)

            native_metadata = None
            if spec.native_source_geometry_policy is not None:
                native_metadata = _native_source_geometry_metadata(
                    spec, native_proof_rows
                )
            elif native_proof_rows:
                raise ModBuildError(
                    f"Native frames have no frozen policy: {spec.gm_file_name}"
                )

            source_remap_metadata = None
            if spec.source_remap_policy is not None:
                policy = spec.source_remap_policy
                proof = source_remap_proof(source_remap_proof_rows)
                if proof["frame_count"] != policy.expected_frame_count or proof["visible_blue_pixel_count"] != 0:
                    raise ModBuildError(f"Incomplete or mapper-blue source remap for {spec.gm_file_name}")
                reference_proof = source_remap_reference_proof(
                    source_remap_proof_rows, SOURCE_REMAP_139_CONTRACTS[spec.gm_file_name]
                )
                actual_contract = (
                    reference_proof["frame_count"],
                    reference_proof["mapping_sha256"],
                    reference_proof["proof_sha256"],
                    reference_proof["source_rgba_sha256"],
                    reference_proof["output_rgba_sha256"],
                    reference_proof["visible_blue_pixel_count"],
                )
                expected_contract = (
                    policy.expected_frame_count,
                    policy.expected_mapping_sha256,
                    policy.expected_proof_sha256,
                    policy.expected_source_rgba_sha256,
                    policy.expected_output_rgba_sha256,
                    policy.expected_visible_blue_pixel_count,
                )
                if actual_contract != expected_contract:
                    raise ModBuildError(
                        f"Source remap proof changed for {spec.gm_file_name}: "
                        f"actual={actual_contract} expected={expected_contract}"
                    )
                source_remap_metadata = {
                    "mode": policy.mode,
                    "proof_algorithm": policy.proof_algorithm,
                    **proof,
                    "source_only": True,
                    "target_fallback_count": 0,
                    "exact_canvas": True,
                    "clipping": False,
                    "resampling": "none",
                    "frame_proofs": source_remap_proof_rows,
                }
            elif source_remap_proof_rows:
                raise ModBuildError(
                    f"Source-remapped frames have no frozen policy: "
                    f"{spec.gm_file_name}"
                )

            emit_options: dict[str, Any] = {
                "shared_source_texture_group_count": source_group_counts[
                    spec.source_texture
                ],
                "derived_frame_policy": derived_metadata,
                "native_source_geometry_policy": native_metadata,
                "source_remap_policy": source_remap_metadata,
            }
            if keep_pending:
                # The Crusader copies still have to be read from the target
                # game.  Hold this group back until every source atlas is
                # released, so the two 8192x8192 textures never coexist.
                deferred_keep_groups.append(
                    (validated, frames, keep_pending, emit_options)
                )
            else:
                output.extend(
                    _emit_gm_atlas(mod_root, validated, frames, **emit_options)
                )
                del frames
            del derived_proof_rows
            del native_proof_rows
            del source_remap_proof_rows
            gc.collect()

        del environment
        del by_id
        del texture_by_name
        del texture_trees
        del mask_image
        gc.collect()

    if deferred_keep_groups:
        output.extend(
            _emit_sparse_keep_gm_atlases(
                config, mod_root, deferred_keep_groups, UnityPy
            )
        )
        del deferred_keep_groups
        gc.collect()

    if review_specs:
        output.extend(
            _build_review_gm_atlases(
                config,
                mod_root,
                review_specs,
                mapping["sprites"],
                UnityPy,
                source_group_counts,
            )
        )
    return output


def _emit_sparse_keep_gm_atlases(
    config: BuilderConfig,
    mod_root: Path,
    deferred: list[
        tuple[
            ValidatedGroup,
            list[AtlasFrame],
            list[tuple[dict[str, Any], FrameSlot]],
            dict[str, Any],
        ]
    ],
    UnityPy: Any,
) -> list[OutputRecord]:
    """Copy the donor-less Crusader slots and finish those sparse atlases.

    ``GameAtlasManagerAPI.ApplySingle`` sizes the GM array from the highest
    index present in our atlas.json.  A group whose European coverage stops
    below its highest slot must therefore still ship every remaining slot, or
    the array is truncated and those tiles disappear from the game.  The pixels
    come from the target installation, byte for byte, on the target canvas.
    """

    target_asset = config.target.data_dir / "resources.assets"
    environment = load_unity_asset(target_asset, unitypy=UnityPy)
    by_id, texture_by_name, texture_trees = _texture_objects(environment)
    # A group carrying a team mask needs its kept slots to travel with the
    # matching mask crop, exactly as the reviewed passthrough does.  Decode each
    # mask atlas once and share it across every group that names it: these are
    # multi-thousand-pixel textures and there are only a handful of them.
    mask_images: dict[str, Image.Image] = {}
    output: list[OutputRecord] = []
    for validated, frames, keep_pending, emit_options in deferred:
        spec = validated.spec
        if spec.sparse_keep_frame_count is None:
            raise ModBuildError(
                f"Crusader keeps appeared without a declaration: "
                f"{spec.gm_file_name}"
            )
        if spec.target_texture not in texture_by_name:
            raise ModBuildError(
                f"Sparse keep target atlas is missing: {spec.target_texture}"
            )
        mask_image: Image.Image | None = None
        if spec.require_mask:
            mask_name = spec.target_texture + "_m"
            mask_image = mask_images.get(mask_name)
            if mask_image is None:
                mask_object = texture_by_name.get(mask_name)
                if mask_object is None:
                    raise ModBuildError(
                        f"Required sparse keep mask atlas is missing: {mask_name}"
                    )
                mask_image = mask_object.read().image.convert("RGBA")
                mask_images[mask_name] = mask_image
        main_tree = texture_trees[spec.target_texture]
        keep_rows: list[dict[str, Any]] = []
        for proposal, slot in keep_pending:
            name = str(proposal["name"])
            if str(proposal.get("action", "")) != "KEEP_CRUSADER":
                raise ModBuildError(f"Sparse keep queue changed for {name}")
            if proposal.get("source") is not None:
                raise ModBuildError(
                    f"Kept Crusader frame unexpectedly has a donor: {name}"
                )
            target_meta = proposal["target"]
            if str(target_meta.get("texture_name")) != spec.target_texture:
                raise ModBuildError(
                    f"Kept Crusader frame leaves the target atlas: {name}"
                )
            if (
                parse_loader_frame_name(name, spec.gm_file_name, spec.dash_format)
                != slot
            ):
                raise ModBuildError(
                    f"Kept Crusader frame would reach a different loader slot: "
                    f"{name}"
                )
            target_object, target_image = _read_mapped_sprite(
                by_id, proposal, "target"
            )
            target_mask = None
            if spec.require_mask:
                if mask_image is None:
                    raise ModBuildError(
                        f"No decoded sparse keep mask for {name}"
                    )
                logical_size = (
                    _integer_dimension(
                        target_meta["width"], "kept target mask width"
                    ),
                    _integer_dimension(
                        target_meta["height"], "kept target mask height"
                    ),
                )
                target_mask = _crop_mask_for_sprite(
                    mask_image,
                    main_tree,
                    target_object.read_typetree(),
                    logical_size,
                    # Not require_native_size.  Team masks are not always stored
                    # at the main atlas's resolution - treeSprites keeps its mask
                    # at a quarter, so a 145x182 sprite crops to a 36x45 mask.
                    # The European frames in the same group are upsampled the
                    # same way by the ordinary path, so demanding native size
                    # here would hold the kept Crusader copies to a stricter rule
                    # than the frames they sit next to.
                    require_native_size=False,
                )
            result = _render_review_target_passthrough(
                proposal,
                slot,
                target_image,
                target_mask,
                require_mask=spec.require_mask,
                proof_status=KEEP_CRUSADER_PROOF_STATUS,
            )
            frame = result.frame
            if frame is None or result.origin != TARGET_FRAME_ORIGIN:
                raise ModBuildError(f"Kept Crusader frame was not copied: {name}")
            frames.append(frame)
            keep_rows.append(
                {
                    "name": name,
                    "origin": result.origin,
                    "proof_status": result.proof_status,
                    "target_path_id": int(target_meta["path_id"]),
                    "target_width": _integer_dimension(
                        target_meta["width"], "kept target width"
                    ),
                    "target_height": _integer_dimension(
                        target_meta["height"], "kept target height"
                    ),
                    "target_pivot_x": float(target_meta["pivot_x"]),
                    "target_pivot_y": float(target_meta["pivot_y"]),
                    "output_pivot_x": frame.pivot_x,
                    "output_pivot_y": frame.pivot_y,
                    "target_pixels_per_unit": float(
                        target_meta["pixels_per_unit"]
                    ),
                    "output_pixels_per_unit": frame.pixels_per_unit,
                    "target_rgba_sha256": hashlib.sha256(
                        frame.image.tobytes()
                    ).hexdigest(),
                }
            )
        proof = sparse_keep_frame_proof(keep_rows)
        if proof["frame_count"] != spec.sparse_keep_frame_count:
            raise ModBuildError(
                f"Crusader keep count changed for {spec.gm_file_name}: "
                f"actual={proof['frame_count']} "
                f"expected={spec.sparse_keep_frame_count}"
            )
        sparse_keep_metadata = {
            "mode": SPARSE_KEEP_POLICY_MODE,
            "proof_algorithm": SPARSE_KEEP_PROOF_ALGORITHM,
            **proof,
            "target_rgba_exact": True,
            "source_pixels_used": False,
            "clipping": False,
            "resampling": "none",
            "frame_proofs": keep_rows,
        }
        output.extend(
            _emit_gm_atlas(
                mod_root,
                validated,
                frames,
                sparse_keep_policy=sparse_keep_metadata,
                **emit_options,
            )
        )
        del keep_rows
        gc.collect()
    del environment
    del by_id
    del texture_by_name
    del texture_trees
    mask_images.clear()
    gc.collect()
    return output


def _build_shared_gm_atlases(
    config: BuilderConfig,
    mod_root: Path,
    profile: dict[str, Any],
    mapping: dict[str, Any],
) -> list[OutputRecord]:
    """Build one physical host atlas for each reviewed shared GM array."""

    specs = _shared_gm_specs(profile)
    if not specs:
        return []
    standard_raw = profile.get("gm_atlases", [])
    if not isinstance(standard_raw, list):
        raise ModBuildError("Profile key 'gm_atlases' must be a list")
    standard_specs = [AtlasGroupSpec.from_profile(raw) for raw in standard_raw]
    all_specs = [*standard_specs, *specs]
    source_counts = {
        texture: sum(spec.source_texture == texture for spec in all_specs)
        for texture in {spec.source_texture for spec in all_specs}
    }
    UnityPy = _import_unitypy()
    source_asset = config.source.data_dir / "resources.assets"
    output: list[OutputRecord] = []
    for spec in specs:
        validated = validate_shared_gm_atlas(mapping["sprites"], spec)
        environment = load_unity_asset(source_asset, unitypy=UnityPy)
        by_id, texture_by_name, _texture_trees = _texture_objects(environment)
        if spec.source_texture not in texture_by_name:
            raise ModBuildError(
                f"Shared GM source atlas is missing: {spec.source_texture}"
            )

        frames: list[AtlasFrame] = []
        shared_proof_rows: list[dict[str, Any]] = []
        native_rows_by_member: dict[str, list[dict[str, Any]]] = {
            member.gm_file_name: [] for member in spec.members
        }
        for plan in validated.frames:
            proposal = plan.proposal
            source = proposal["source"]
            target = proposal["target"]
            source_id = int(source["path_id"])
            source_obj = by_id.get(source_id)
            if source_obj is None or source_obj.type.name != "Sprite":
                raise ModBuildError(
                    f"Shared GM source Sprite PathID is missing for "
                    f"{plan.logical_name}: {source_id}"
                )
            sprite_data = source_obj.read()
            if sprite_data.m_Name != plan.logical_name:
                raise ModBuildError(
                    f"Shared GM source PathID/name mismatch: "
                    f"{sprite_data.m_Name} != {plan.logical_name}"
                )
            source_image = sprite_data.image.convert("RGBA")
            adapted = keep_native_source_frame(source_image, source)
            pivot_x, pivot_y = native_reanchored_pivot(
                source, target, plan.output_name
            )
            output_ppu = float(target["pixels_per_unit"])
            frames.append(
                AtlasFrame(
                    name=plan.output_name,
                    slot=plan.output_slot,
                    image=adapted,
                    mask=None,
                    pivot_x=pivot_x,
                    pivot_y=pivot_y,
                    pixels_per_unit=output_ppu,
                )
            )
            rgba_sha256 = hashlib.sha256(adapted.tobytes()).hexdigest()
            shared_proof_rows.append(
                {
                    "slot": plan.output_slot.index,
                    "member_gm_file_name": plan.member_gm_file_name,
                    "logical_name": plan.logical_name,
                    "output_name": plan.output_name,
                    "source_rgba_sha256": rgba_sha256,
                }
            )
            native_rows_by_member[plan.member_gm_file_name].append(
                {
                    "name": plan.logical_name,
                    "origin": SOURCE_FRAME_ORIGIN,
                    "source_width": _integer_dimension(
                        source["width"], "shared native source width"
                    ),
                    "source_height": _integer_dimension(
                        source["height"], "shared native source height"
                    ),
                    "target_width": _integer_dimension(
                        target["width"], "shared native target width"
                    ),
                    "target_height": _integer_dimension(
                        target["height"], "shared native target height"
                    ),
                    "source_pivot_x": float(source["pivot_x"]),
                    "source_pivot_y": float(source["pivot_y"]),
                    "target_pivot_x": float(target["pivot_x"]),
                    "target_pivot_y": float(target["pivot_y"]),
                    "output_pivot_x": pivot_x,
                    "output_pivot_y": pivot_y,
                    "source_pixels_per_unit": float(
                        source["pixels_per_unit"]
                    ),
                    "target_pixels_per_unit": output_ppu,
                    "output_pixels_per_unit": output_ppu,
                    "source_rgba_sha256": rgba_sha256,
                }
            )

        shared_proof = shared_gm_atlas_proof(shared_proof_rows, spec)
        member_native_proofs: list[dict[str, Any]] = []
        for member in spec.members:
            rows = native_rows_by_member[member.gm_file_name]
            proof = native_source_geometry_proof(rows)
            actual = (
                proof["frame_count"],
                proof["geometry_proof_sha256"],
                proof["origin_proof_sha256"],
                proof["source_rgba_sha256"],
                proof["target_origin_count"],
                proof["source_anchor_max_error_px"],
                proof["runtime_anchor_max_error_px"],
            )
            expected = (
                member.expected_frame_count,
                member.expected_geometry_proof_sha256,
                member.expected_origin_proof_sha256,
                member.expected_source_rgba_sha256,
                0,
                member.expected_source_anchor_max_error_px,
                member.expected_runtime_anchor_max_error_px,
            )
            if actual != expected:
                raise ModBuildError(
                    f"Shared GM native proof changed for {member.gm_file_name}: "
                    f"actual={actual} expected={expected}"
                )
            member_native_proofs.append(
                {
                    "gm_file_name": member.gm_file_name,
                    "slot_offset": member.slot_offset,
                    "mode": spec.geometry_policy,
                    "proof_algorithm": spec.proof_algorithm,
                    **proof,
                    "frame_proofs": rows,
                }
            )

        shared_metadata = {
            "mode": SHARED_GM_ATLAS_MODE,
            "gm_enum": spec.gm_enum,
            "host_gm_file_name": spec.host_gm_file_name,
            "member_gm_file_names": list(spec.member_names),
            "geometry_policy": spec.geometry_policy,
            "proof_algorithm": spec.proof_algorithm,
            **shared_proof,
            "native_rgba_exact": True,
            "target_canvas_used": False,
            "target_fallback_count": 0,
            "clipping": False,
            "resampling": "none",
            "frame_proofs": shared_proof_rows,
            "member_native_proofs": member_native_proofs,
        }
        output.extend(
            _emit_gm_atlas(
                mod_root,
                validated.output_group(),
                frames,
                shared_source_texture_group_count=source_counts[
                    spec.source_texture
                ],
                shared_gm_atlas_policy=shared_metadata,
            )
        )
        del environment
        del by_id
        del texture_by_name
        del frames
        del shared_proof_rows
        del native_rows_by_member
        gc.collect()
    return output


def _build_review_gm_atlases(
    config: BuilderConfig,
    mod_root: Path,
    specs: list[AtlasGroupSpec],
    mapping_sprites: list[dict[str, Any]],
    UnityPy: Any,
    source_group_counts: dict[str, int],
) -> list[OutputRecord]:
    """Build proven SH1DE/SHCDE frame partitions without co-decoding atlases."""

    grouped: dict[
        tuple[str, str], list[tuple[AtlasGroupSpec, ValidatedGroup]]
    ] = defaultdict(list)
    for spec in specs:
        if spec.review_frame_policy is None:
            raise ModBuildError(
                f"Internal review batch received a standard group: {spec.gm_file_name}"
            )
        grouped[(spec.source_texture, spec.target_texture)].append(
            (spec, validate_complete_group(mapping_sprites, spec))
        )

    source_asset = config.source.data_dir / "resources.assets"
    target_asset = config.target.data_dir / "resources.assets"
    output: list[OutputRecord] = []
    for (source_texture, target_texture), shared_specs in grouped.items():
        rendered: dict[str, dict[str, ReviewFrameResult]] = {
            spec.gm_file_name: {} for spec, _ in shared_specs
        }
        pending_target: dict[
            str, list[tuple[dict[str, Any], FrameSlot, str]]
        ] = {
            spec.gm_file_name: [] for spec, _ in shared_specs
        }

        # Decode the SH1 atlas first and retain only the small logical sprites.
        # Releasing this environment before loading SHCDE avoids holding both
        # full 8192x8192 main/mask pairs at the same time.
        source_environment = load_unity_asset(source_asset, unitypy=UnityPy)
        source_by_id, source_textures, source_trees = _texture_objects(
            source_environment
        )
        if source_texture not in source_textures:
            raise ModBuildError(f"Review source atlas is missing: {source_texture}")
        source_mask_image = None
        source_mask_object = None
        source_mask_name = source_texture + "_m"
        if any(spec.require_mask for spec, _ in shared_specs):
            source_mask_object = source_textures.get(source_mask_name)
            if source_mask_object is None:
                raise ModBuildError(
                    f"Required review source mask atlas is missing: {source_mask_name}"
                )
            source_mask_image = source_mask_object.read().image.convert("RGBA")
        source_main_tree = source_trees[source_texture]

        source_object = None
        source_image = None
        source_mask = None
        result = None
        for spec, validated in shared_specs:
            review_policy = spec.review_frame_policy
            renders_native_source = (
                review_policy is not None and review_policy.renders_native_source
            )
            # Erklaerte Umlenkungen der Gruppe: der Platz wird vom Frame
            # ANDEREN Namens beliefert, und nur diese Tabelle sagt, von
            # welchem. Alles andere bleibt bei der Namensgleichheit.
            override_donors = {
                override.target_name: override.donor_name
                for override in frame_overrides_for_spec(spec)
                if override.donor_name is not None
            }
            for proposal, slot in zip(
                validated.proposals, validated.slots, strict=True
            ):
                if str(proposal.get("action", "")) == "KEEP_CRUSADER":
                    pending_target[spec.gm_file_name].append(
                        (proposal, slot, KEEP_CRUSADER_PROOF_STATUS)
                    )
                    continue
                override_donor = override_donors.get(str(proposal["name"]))
                source_object, source_image = _read_mapped_sprite(
                    source_by_id, proposal, "source", override_donor
                )
                parsed = parse_loader_frame_name(
                    str(proposal["name"]), spec.gm_file_name, spec.dash_format
                )
                if parsed != slot:
                    raise ModBuildError(
                        f"Review source frame would reach a different loader slot: "
                        f"{proposal['name']}"
                    )
                source_mask = None
                if spec.require_mask:
                    if source_mask_image is None:
                        raise ModBuildError(
                            f"No decoded review source mask for {proposal['name']}"
                        )
                    logical_size = (
                        _integer_dimension(
                            proposal["source"]["width"], "source mask width"
                        ),
                        _integer_dimension(
                            proposal["source"]["height"], "source mask height"
                        ),
                    )
                    source_mask = _crop_mask_for_sprite(
                        source_mask_image,
                        source_main_tree,
                        source_object.read_typetree(),
                        logical_size,
                        # Spiegelbildlich zum Standardpfad: unter nativer
                        # Geometrie darf eine abweichende Maskenaufloesung nicht
                        # still per NEAREST hochskaliert werden, sie muss den
                        # Build anhalten.
                        require_native_size=renders_native_source,
                    )
                if renders_native_source:
                    result = _render_review_native_source_frame(
                        proposal,
                        slot,
                        source_image,
                        source_mask,
                        require_mask=spec.require_mask,
                        reanchor=spec.uses_native_geometry
                        and not spec.uses_authored_source_geometry,
                    )
                else:
                    result = _render_review_source_candidate(
                        proposal,
                        slot,
                        source_image,
                        source_mask,
                        require_mask=spec.require_mask,
                    )
                if result.frame is None:
                    pending_target[spec.gm_file_name].append(
                        (proposal, slot, result.proof_status)
                    )
                else:
                    rendered[spec.gm_file_name][str(proposal["name"])] = result

        del source_environment
        del source_object
        del source_image
        del source_mask
        del source_mask_object
        del source_main_tree
        del result
        del source_by_id
        del source_textures
        del source_trees
        del source_mask_image
        gc.collect()

        target_pending_count = sum(len(items) for items in pending_target.values())
        if target_pending_count:
            target_environment = load_unity_asset(target_asset, unitypy=UnityPy)
            target_by_id, target_textures, target_trees = _texture_objects(
                target_environment
            )
            if target_texture not in target_textures:
                raise ModBuildError(
                    f"Review target atlas is missing: {target_texture}"
                )
            target_mask_image = None
            target_mask_object = None
            target_mask_name = target_texture + "_m"
            if any(spec.require_mask for spec, _ in shared_specs):
                target_mask_object = target_textures.get(target_mask_name)
                if target_mask_object is None:
                    raise ModBuildError(
                        f"Required review target mask atlas is missing: "
                        f"{target_mask_name}"
                    )
                target_mask_image = target_mask_object.read().image.convert("RGBA")
            target_main_tree = target_trees[target_texture]

            for spec, _ in shared_specs:
                for proposal, slot, proof_status in pending_target[spec.gm_file_name]:
                    target_object, target_image = _read_mapped_sprite(
                        target_by_id, proposal, "target"
                    )
                    target_mask = None
                    if spec.require_mask:
                        if target_mask_image is None:
                            raise ModBuildError(
                                f"No decoded review target mask for "
                                f"{proposal['name']}"
                            )
                        logical_size = (
                            _integer_dimension(
                                proposal["target"]["width"], "target mask width"
                            ),
                            _integer_dimension(
                                proposal["target"]["height"], "target mask height"
                            ),
                        )
                        target_mask = _crop_mask_for_sprite(
                            target_mask_image,
                            target_main_tree,
                            target_object.read_typetree(),
                            logical_size,
                            require_native_size=True,
                        )
                    result = _render_review_target_passthrough(
                        proposal,
                        slot,
                        target_image,
                        target_mask,
                        require_mask=spec.require_mask,
                        proof_status=proof_status,
                    )
                    rendered[spec.gm_file_name][str(proposal["name"])] = result

            del target_environment
            del target_object
            del target_image
            del target_mask
            del target_mask_object
            del target_main_tree
            del result
            del target_by_id
            del target_textures
            del target_trees
            del target_mask_image
            gc.collect()

        for spec, validated in shared_specs:
            review_policy = spec.review_frame_policy
            renders_native_source = (
                review_policy is not None and review_policy.renders_native_source
            )
            ordered_results: list[ReviewFrameResult] = []
            for proposal in validated.proposals:
                name = str(proposal["name"])
                result = rendered[spec.gm_file_name].get(name)
                if result is None or result.frame is None:
                    raise ModBuildError(f"Review frame was not rendered: {name}")
                ordered_results.append(result)
            provenance_rows: list[dict[str, Any]] = []
            native_proof_rows: list[dict[str, Any]] = []
            for proposal, result in zip(
                validated.proposals, ordered_results, strict=True
            ):
                if result.frame is None:
                    continue
                row: dict[str, Any] = {
                    "name": result.frame.name,
                    "origin": result.origin,
                    "proof_status": result.proof_status,
                    "discarded_mask_alpha": result.discarded_mask_alpha,
                }
                if review_policy and review_policy.includes_keep:
                    row["action"] = str(proposal.get("action", ""))
                provenance_rows.append(row)
                if renders_native_source and result.origin == SOURCE_FRAME_ORIGIN:
                    # Genau die elf Felder, die
                    # native_source_authored_pivot_proof verlangt. Der
                    # RGBA-Digest deckt den ausgegebenen Frame ab, nicht die
                    # Sprite-Rohdaten - unter nativer Geometrie sind das
                    # dieselben Bytes, und der statische Validator vergleicht
                    # sie spaeter gegen den serialisierten Atlas.
                    source_meta = proposal["source"]
                    native_row: dict[str, Any] = {
                        "name": result.frame.name,
                        "origin": result.origin,
                        "source_width": _integer_dimension(
                            source_meta["width"], "native source width"
                        ),
                        "source_height": _integer_dimension(
                            source_meta["height"], "native source height"
                        ),
                        "source_pivot_x": float(source_meta["pivot_x"]),
                        "source_pivot_y": float(source_meta["pivot_y"]),
                        "output_pivot_x": result.frame.pivot_x,
                        "output_pivot_y": result.frame.pivot_y,
                        "source_pixels_per_unit": float(
                            source_meta["pixels_per_unit"]
                        ),
                        "output_pixels_per_unit": (
                            result.frame.pixels_per_unit
                        ),
                        "source_rgba_sha256": hashlib.sha256(
                            result.frame.image.tobytes()
                        ).hexdigest(),
                    }
                    if (
                        spec.uses_native_geometry
                        and not spec.uses_authored_source_geometry
                    ):
                        # Der umgerechnete Anker wird gegen die Zielgeometrie
                        # bewiesen, nicht gegen die Quelle: genau die fuenf
                        # Felder mehr, die native_source_geometry_proof
                        # verlangt und aus denen es die Ankerabweichung in
                        # Pixeln nachrechnet.
                        target_meta = proposal["target"]
                        native_row.update(
                            {
                                "target_width": _integer_dimension(
                                    target_meta["width"], "native target width"
                                ),
                                "target_height": _integer_dimension(
                                    target_meta["height"],
                                    "native target height",
                                ),
                                "target_pivot_x": float(
                                    target_meta["pivot_x"]
                                ),
                                "target_pivot_y": float(
                                    target_meta["pivot_y"]
                                ),
                                "target_pixels_per_unit": float(
                                    target_meta["pixels_per_unit"]
                                ),
                            }
                        )
                    native_proof_rows.append(native_row)
            review_metadata = validate_review_frame_partition(
                validated, provenance_rows
            )
            review_metadata["discarded_source_mask_alpha"] = sum(
                result.discarded_mask_alpha for result in ordered_results
            )
            statuses = (
                [NATIVE_SOURCE_PROOF_STATUS]
                if renders_native_source
                else ["AUTO_LOSSLESS_INTEGRAL", "BLOCKED_ALPHA_CLIP"]
            )
            if review_policy and review_policy.includes_keep:
                statuses.append(KEEP_CRUSADER_PROOF_STATUS)
            review_metadata["status_counts"] = {
                status: sum(
                    result.proof_status == status for result in ordered_results
                )
                for status in statuses
            }
            native_metadata = None
            if renders_native_source:
                native_metadata = _native_source_geometry_metadata(
                    spec, native_proof_rows
                )
            elif native_proof_rows:  # pragma: no cover - defensiv
                raise ModBuildError(
                    f"Native review frames have no frozen policy: "
                    f"{spec.gm_file_name}"
                )
            frames = [
                result.frame
                for result in ordered_results
                if result.frame is not None
            ]
            output.extend(
                _emit_gm_atlas(
                    mod_root,
                    validated,
                    frames,
                    shared_source_texture_group_count=source_group_counts[
                        spec.source_texture
                    ],
                    review_frame_policy=review_metadata,
                    native_source_geometry_policy=native_metadata,
                )
            )
            del frames
            del ordered_results
            gc.collect()
    return output


def _verify_individual_png_roundtrip(
    path: Path,
    expected: Image.Image,
    *,
    label: str,
) -> None:
    """Reopen a serialized PNG and byte-compare it with the rendered RGBA frame."""

    expected_rgba = expected.convert("RGBA")
    try:
        with Image.open(path) as serialized:
            serialized.load()
            if serialized.mode != "RGBA":
                raise ModBuildError(
                    f"Serialized sparse PNG is not RGBA for {label}: "
                    f"{serialized.mode}"
                )
            if serialized.size != expected_rgba.size:
                raise ModBuildError(
                    f"Serialized sparse PNG geometry changed for {label}: "
                    f"{serialized.size} != {expected_rgba.size}"
                )
            if serialized.tobytes() != expected_rgba.tobytes():
                raise ModBuildError(
                    f"Serialized sparse PNG pixels changed for {label}"
                )
    except (OSError, ValueError) as exc:
        raise ModBuildError(
            f"Serialized sparse PNG cannot be decoded for {label}: {exc}"
        ) from exc


def _emit_review_individual_source_group(
    mod_root: Path,
    sparse: ReviewIndividualSourceOnlySpec,
    validated: ValidatedGroup,
    results: list[ReviewFrameResult],
) -> list[OutputRecord]:
    """Emit only proven SH1DE frames plus one compact full-group contract."""

    spec = sparse.group
    if validated.spec != spec or len(results) != len(validated.proposals):
        raise ModBuildError(
            f"Sparse review result set changed for {spec.gm_file_name}"
        )

    provenance_rows: list[dict[str, Any]] = []
    source_results: list[tuple[dict[str, Any], FrameSlot, ReviewFrameResult]] = []
    for proposal, slot, result in zip(
        validated.proposals, validated.slots, results, strict=True
    ):
        name = str(proposal["name"])
        if (
            isinstance(result.discarded_mask_alpha, bool)
            or not isinstance(result.discarded_mask_alpha, int)
            or result.discarded_mask_alpha < 0
            or (
                result.origin == TARGET_FRAME_ORIGIN
                and result.discarded_mask_alpha != 0
            )
        ):
            raise ModBuildError(
                f"Sparse review discarded-mask provenance changed for {name}"
            )
        provenance_rows.append(
            {
                "name": name,
                "action": str(proposal.get("action", "")),
                "origin": result.origin,
                "proof_status": result.proof_status,
                "discarded_mask_alpha": result.discarded_mask_alpha,
            }
        )
        if result.origin == SOURCE_FRAME_ORIGIN:
            frame = result.frame
            if (
                frame is None
                or frame.name != name
                or frame.slot != slot
                or frame.mask is None
                or frame.image.size != frame.mask.size
            ):
                raise ModBuildError(
                    f"Sparse source frame/mask contract changed for {name}"
                )
            source_results.append((proposal, slot, result))
        elif result.frame is not None:
            raise ModBuildError(
                f"Sparse backend must not emit target/fallback pixels: {name}"
            )

    review_metadata = validate_review_frame_partition(
        validated, provenance_rows
    )
    policy = spec.review_frame_policy
    if policy is None or policy.mode != REVIEW_FRAME_POLICY_MODE_V2:
        raise ModBuildError(
            f"Sparse group lost its v2 review policy: {spec.gm_file_name}"
        )
    source_names = [str(proposal["name"]) for proposal, _, _ in source_results]
    source_main_count = sum(not slot.is_alt for _, slot, _ in source_results)
    source_alt_count = len(source_results) - source_main_count
    source_names_sha256 = hashlib.sha256(
        "".join(name + "\n" for name in source_names).encode("utf-8")
    ).hexdigest()
    actual_source_contract = (
        len(source_results),
        source_main_count,
        source_alt_count,
        source_names_sha256,
    )
    expected_source_contract = (
        policy.expected_source_frame_count,
        sparse.expected_source_main_count,
        sparse.expected_source_alt_count,
        policy.expected_source_names_sha256,
    )
    if actual_source_contract != expected_source_contract:
        raise ModBuildError(
            f"Sparse source output partition changed for {spec.gm_file_name}: "
            f"actual={actual_source_contract} expected={expected_source_contract}"
        )

    review_metadata["discarded_source_mask_alpha"] = sum(
        result.discarded_mask_alpha for _, _, result in source_results
    )
    review_metadata["status_counts"] = {
        "AUTO_LOSSLESS_INTEGRAL": len(source_results),
        "BLOCKED_ALPHA_CLIP": policy.expected_blocked_review_frame_count,
        KEEP_CRUSADER_PROOF_STATUS: policy.expected_keep_frame_count,
    }

    output: list[OutputRecord] = []
    payload_rows: list[dict[str, Any]] = []
    for proposal, _, result in source_results:
        frame = result.frame
        assert frame is not None and frame.mask is not None
        name = frame.name
        main_path = _safe_output(mod_root, f"Override/Sprites/{name}.png")
        mask_path = _safe_output(mod_root, f"Override/Sprites/{name}_m.png")
        _save_png(frame.image, main_path)
        _save_png(frame.mask, mask_path)
        _verify_individual_png_roundtrip(main_path, frame.image, label=name)
        _verify_individual_png_roundtrip(
            mask_path, frame.mask, label=f"{name}_m"
        )
        source_id = int(proposal["source"]["path_id"])
        main_record = _record(
            mod_root,
            main_path,
            REVIEW_INDIVIDUAL_MAIN_CATEGORY,
            f"resources.assets:Sprite:{source_id}:{name}",
            frame.image,
            0,
        )
        mask_record = _record(
            mod_root,
            mask_path,
            REVIEW_INDIVIDUAL_MASK_CATEGORY,
            f"resources.assets:Texture2D:{spec.source_texture}_m:{name}",
            frame.mask,
        )
        output.extend((main_record, mask_record))
        payload_rows.append(
            {
                "name": name,
                "main_sha256": main_record.sha256,
                "mask_sha256": mask_record.sha256,
                "width": frame.image.width,
                "height": frame.image.height,
            }
        )

    compact_partition_keys = (
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
    )
    compact_partition = {
        key: review_metadata[key] for key in compact_partition_keys
    }
    contract = {
        "schema_version": 1,
        "kind": REVIEW_INDIVIDUAL_CONTRACT_KIND,
        "mode": REVIEW_INDIVIDUAL_SOURCE_ONLY_MODE,
        "gm_file_name": spec.gm_file_name,
        "loader_manifest": {
            "dash_format": spec.dash_format,
            "mask_policy": spec.mask_policy,
            "source_texture": spec.source_texture,
            "target_texture": spec.target_texture,
            "frame_count": spec.expected_frame_count,
            "main_count": spec.expected_main_count,
            "alt_count": spec.expected_alt_count,
            "max_index": spec.expected_max_index,
            "array_size": validated.array_size,
            "names_sha256": validated.names_sha256,
            "padding": spec.padding,
            "max_dimension": spec.max_dimension,
            "category": spec.category,
            "geometry_policy": spec.geometry_policy,
            "loader_material_compatible": spec.loader_material_compatible,
        },
        "frame_provenance": provenance_rows,
        "review_partition": compact_partition,
        "source_output": {
            "frame_count": len(source_results),
            "main_count": source_main_count,
            "alt_count": source_alt_count,
            "names_sha256": source_names_sha256,
            "main_file_count": len(source_results),
            "mask_file_count": len(source_results),
            "blocked_and_keep_file_count": 0,
            "serialized_png_roundtrip": {
                "verified": True,
                "frames_checked": len(source_results),
                "payload_sha256": review_individual_payload_digest(payload_rows),
            },
        },
    }
    contract_path = _safe_output(
        mod_root,
        f"{REVIEW_INDIVIDUAL_CONTRACT_PREFIX}{spec.gm_file_name}.json",
    )
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    contract_path.write_text(
        json.dumps(contract, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    contract_sha256 = sha256_file(contract_path)
    output.append(
        _record(
            mod_root,
            contract_path,
            "review_individual_source_contract",
            (
                f"resources.assets:GM:{spec.gm_file_name}:"
                f"full_frames={spec.expected_frame_count}:"
                f"source_frames={len(source_results)}"
            ),
            metadata={
                "kind": REVIEW_INDIVIDUAL_CONTRACT_KIND,
                "mode": REVIEW_INDIVIDUAL_SOURCE_ONLY_MODE,
                "gm_file_name": spec.gm_file_name,
                "contract_sha256": contract_sha256,
            },
        )
    )
    return output


def _build_review_individual_source_only(
    config: BuilderConfig,
    mod_root: Path,
    profile: dict[str, Any],
    mapping: dict[str, Any],
) -> list[OutputRecord]:
    """Build sparse, source-only individual overrides without decoding SHCDE."""

    sparse_specs = _review_individual_specs(profile)
    if not sparse_specs:
        return []
    grouped: dict[str, list[ReviewIndividualSourceOnlySpec]] = defaultdict(list)
    for sparse in sparse_specs:
        grouped[sparse.group.source_texture].append(sparse)

    UnityPy = _import_unitypy()
    source_asset = config.source.data_dir / "resources.assets"
    output: list[OutputRecord] = []
    for source_texture, shared_specs in grouped.items():
        source_environment = load_unity_asset(source_asset, unitypy=UnityPy)
        source_by_id, source_textures, source_trees = _texture_objects(
            source_environment
        )
        if source_texture not in source_textures:
            raise ModBuildError(
                f"Sparse review source atlas is missing: {source_texture}"
            )
        source_mask_name = source_texture + "_m"
        source_mask_object = source_textures.get(source_mask_name)
        if source_mask_object is None:
            raise ModBuildError(
                f"Sparse review source mask atlas is missing: {source_mask_name}"
            )
        source_mask_image = source_mask_object.read().image.convert("RGBA")
        source_main_tree = source_trees[source_texture]

        source_object = None
        source_image = None
        source_mask = None
        result = None
        for sparse in shared_specs:
            spec = sparse.group
            validated = validate_complete_group(mapping["sprites"], spec)
            results: list[ReviewFrameResult] = []
            for proposal, slot in zip(
                validated.proposals, validated.slots, strict=True
            ):
                if str(proposal.get("action", "")) == "KEEP_CRUSADER":
                    results.append(
                        ReviewFrameResult(
                            frame=None,
                            origin=TARGET_FRAME_ORIGIN,
                            proof_status=KEEP_CRUSADER_PROOF_STATUS,
                        )
                    )
                    continue
                source_object, source_image = _read_mapped_sprite(
                    source_by_id, proposal, "source"
                )
                parsed = parse_loader_frame_name(
                    str(proposal["name"]), spec.gm_file_name, spec.dash_format
                )
                if parsed != slot:
                    raise ModBuildError(
                        f"Sparse review source frame would reach a different "
                        f"loader slot: {proposal['name']}"
                    )
                logical_size = (
                    _integer_dimension(
                        proposal["source"]["width"], "source mask width"
                    ),
                    _integer_dimension(
                        proposal["source"]["height"], "source mask height"
                    ),
                )
                source_mask = _crop_mask_for_sprite(
                    source_mask_image,
                    source_main_tree,
                    source_object.read_typetree(),
                    logical_size,
                )
                result = _render_review_source_candidate(
                    proposal,
                    slot,
                    source_image,
                    source_mask,
                    require_mask=True,
                )
                results.append(result)

            output.extend(
                _emit_review_individual_source_group(
                    mod_root, sparse, validated, results
                )
            )
            del results
            gc.collect()

        del source_environment
        del source_object
        del source_image
        del source_mask
        del source_mask_object
        del source_main_tree
        del result
        del source_by_id
        del source_textures
        del source_trees
        del source_mask_image
        gc.collect()
    return output


def _verify_built_gm_atlas_roundtrip(
    built: BuiltAtlas,
    expected_frames: list[AtlasFrame],
) -> dict[str, Any]:
    """Fail closed unless every logical frame survives in-memory serialization."""

    try:
        result = verify_atlas_roundtrip(
            built.atlas_json,
            built.image,
            built.mask,
            expected_frames,
            gm_file_name=built.spec.gm_file_name,
            dash_format=built.spec.dash_format,
        )
    except AtlasRoundtripError as exc:
        raise ModBuildError(
            f"GM atlas in-memory roundtrip failed for "
            f"{built.spec.gm_file_name}: {exc}"
        ) from exc
    if len(result.frames) != len(expected_frames):
        raise ModBuildError(
            f"GM atlas in-memory roundtrip returned an incomplete result for "
            f"{built.spec.gm_file_name}: checked={len(result.frames)} "
            f"expected={len(expected_frames)}"
        )
    return {
        "verified": True,
        "frames_checked": len(result.frames),
    }


def _verify_serialized_gm_atlas_roundtrip(
    built: BuiltAtlas,
    expected_frames: list[AtlasFrame],
    atlas_path: Path,
    json_path: Path,
    mask_path: Path | None,
) -> dict[str, Any]:
    """Re-open the exact output files and prove every logical RGBA frame."""

    try:
        result = verify_atlas_roundtrip_files(
            json_path,
            atlas_path,
            mask_path,
            expected_frames,
            gm_file_name=built.spec.gm_file_name,
            dash_format=built.spec.dash_format,
        )
    except AtlasRoundtripError as exc:
        raise ModBuildError(
            f"GM atlas serialized-file roundtrip failed for "
            f"{built.spec.gm_file_name}: {exc}"
        ) from exc
    if len(result.frames) != len(expected_frames):
        raise ModBuildError(
            f"GM atlas serialized-file roundtrip returned an incomplete result "
            f"for {built.spec.gm_file_name}: checked={len(result.frames)} "
            f"expected={len(expected_frames)}"
        )
    return {
        "verified": True,
        "serialized_files": True,
        "frames_checked": len(result.frames),
    }


def _group_gm_specs_by_source_texture(
    specs: list[AtlasGroupSpec],
    mapping_sprites: list[dict[str, Any]],
) -> dict[str, list[tuple[AtlasGroupSpec, Any]]]:
    """Validate GM specs and batch every group sharing one source texture."""

    grouped: dict[str, list[tuple[AtlasGroupSpec, Any]]] = defaultdict(list)
    for spec in specs:
        grouped[spec.source_texture].append(
            (spec, validate_complete_group(mapping_sprites, spec))
        )
    return grouped


def _load_atlas_environment_batches(
    UnityPy: Any,
    source_asset: Path,
    grouped_specs: dict[str, list[tuple[AtlasGroupSpec, Any]]],
):
    """Yield exactly one UnityPy environment per distinct source texture.

    Keeping this boundary small makes the high-memory batching invariant
    directly testable without decoding proprietary game assets in the suite.
    """

    for source_texture, shared_specs in grouped_specs.items():
        yield (
            source_texture,
            shared_specs,
            load_unity_asset(source_asset, unitypy=UnityPy),
        )


def _find_texture(environment: Any, name: str) -> tuple[Any, dict[str, Any]]:
    for obj in environment.objects:
        if obj.type.name != "Texture2D":
            continue
        tree = obj.read_typetree()
        if tree.get("m_Name") == name:
            return obj, tree
    raise ModBuildError(f"Texture2D not found: {name}")


def _build_texture_overrides(
    config: BuilderConfig,
    mod_root: Path,
    profile: dict[str, Any],
) -> list[OutputRecord]:
    prepared = [
        (
            selection,
            _game_data_source_path(
                config.source.data_dir,
                selection.get("source_asset"),
                f"texture_overrides[{index}].source_asset",
            ),
            _game_data_source_path(
                config.target.data_dir,
                selection.get("target_asset"),
                f"texture_overrides[{index}].target_asset",
            ),
        )
        for index, selection in enumerate(profile.get("texture_overrides", []))
    ]
    if not prepared:
        return []
    UnityPy = _import_unitypy()
    output: list[OutputRecord] = []
    for selection, source_path, target_path in prepared:
        source_environment = load_unity_asset(source_path, unitypy=UnityPy)
        target_environment = load_unity_asset(target_path, unitypy=UnityPy)
        source_obj, source_tree = _find_texture(source_environment, selection["name"])
        _, target_tree = _find_texture(target_environment, selection["name"])
        source_size = (int(source_tree["m_Width"]), int(source_tree["m_Height"]))
        target_size = (int(target_tree["m_Width"]), int(target_tree["m_Height"]))
        if source_size != target_size:
            raise ModBuildError(
                f"Texture target geometry differs for {selection['name']}: "
                f"source={source_size}, target={target_size}"
            )
        image = source_obj.read().image.convert("RGBA")
        if image.size != target_size:
            raise ModBuildError(
                f"Decoded texture geometry differs for {selection['name']}: {image.size}"
            )
        path = _safe_output(mod_root, selection["output"])
        _save_png(image, path)
        output.append(
            _record(
                mod_root,
                path,
                str(selection["category"]),
                f"{selection['source_asset']}:Texture2D:{source_obj.path_id}:{selection['name']}",
                image,
                0,
                metadata={
                    "kind": "unity_texture_override_v1",
                    "name": selection["name"],
                    "source_asset": selection["source_asset"],
                    "target_asset": selection["target_asset"],
                },
            )
        )
        del source_environment
        del target_environment
        gc.collect()
    return output


def _build_logo(
    config: BuilderConfig,
    mod_root: Path,
    selection: dict[str, Any] | None,
) -> list[OutputRecord]:
    if not selection:
        return []
    source_path = _game_data_source_path(
        config.source.data_dir,
        selection.get("source_asset"),
        "mod_logo.source_asset",
    )
    UnityPy = _import_unitypy()
    environment = load_unity_asset(source_path, unitypy=UnityPy)
    source_obj, _ = _find_texture(environment, selection["name"])
    image = source_obj.read().image.convert("RGBA")
    canvas_size = (
        _integer_dimension(selection.get("canvas_width"), "mod logo canvas width"),
        _integer_dimension(selection.get("canvas_height"), "mod logo canvas height"),
    )
    if image.width > canvas_size[0] or image.height > canvas_size[1]:
        raise ModBuildError(f"Logo source {image.size} does not fit canvas {canvas_size}")
    canvas = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    canvas.alpha_composite(
        image,
        dest=((canvas.width - image.width) // 2, (canvas.height - image.height) // 2),
    )
    path = _safe_output(mod_root, selection["output"])
    _save_png(canvas, path)
    del environment
    return [
        _record(
            mod_root,
            path,
            "mod_logo",
            f"{selection['source_asset']}:Texture2D:{source_obj.path_id}:{selection['name']}",
            canvas,
            0,
            metadata={
                "kind": "mod_logo_v1",
                "name": selection["name"],
                "source_asset": selection["source_asset"],
            },
        )
    ]


def _copy_file_overrides(
    config: BuilderConfig,
    mod_root: Path,
    profile: dict[str, Any],
) -> list[OutputRecord]:
    output: list[OutputRecord] = []
    for index, selection in enumerate(profile.get("file_overrides", [])):
        source = _game_data_source_path(
            config.source.data_dir,
            selection.get("source"),
            f"file_overrides[{index}].source",
        )
        target = _safe_output(mod_root, selection["output"])
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        output.append(
            _record(
                mod_root,
                target,
                str(selection["category"]),
                f"data-file:{Path(selection['source']).as_posix()}",
            )
        )
    return output


def _prune_empty_removed_output_parents(
    mod_root: Path,
    removed_relative_paths: set[str],
) -> None:
    """Remove only directories emptied by exact, manifest-owned removals.

    Deliberately use ``rmdir`` rather than recursive deletion.  A directory
    containing any expected or unexpected entry is retained so the final exact
    manifest scan can either account for it or reject it fail-closed.
    """

    root = mod_root.resolve(strict=True)
    parents = {
        root.joinpath(
            *_canonical_portable_relative_path(relative, "removed UI output").parts
        ).parent
        for relative in removed_relative_paths
    }
    for initial in sorted(parents, key=lambda path: (-len(path.parts), str(path))):
        parent = initial
        while parent != root:
            if _path_lexists(parent) and _is_link_or_junction(parent):
                break
            try:
                parent.rmdir()
            except FileNotFoundError:
                pass
            except OSError:
                # Non-empty/locked directories are not cleanup candidates.  In
                # particular, never hide an unmanifested entry by deleting it.
                break
            parent = parent.parent


def _integrate_ui_texture_build(
    mod_root: Path,
    records: list[OutputRecord],
    result: UiTextureBuildResult,
    source_manifest: UiTextureSourceManifest,
    *,
    max_resident_bytes: int,
) -> list[OutputRecord]:
    if not isinstance(result, UiTextureBuildResult):
        raise ModBuildError("UI texture backend returned an invalid result type")
    runtime = result.runtime
    expected_removed = {
        entry.source
        for entry in source_manifest.entries
        if entry.source_kind == "profile_output"
    }
    removed = set(runtime.removed_png_paths)
    expected_artifacts = {entry.id: entry for entry in source_manifest.entries}
    artifacts = {artifact.entry_id: artifact for artifact in runtime.bundles}
    if (
        removed != expected_removed
        or len(runtime.removed_png_paths) != len(removed)
        or set(artifacts) != set(expected_artifacts)
        or len(runtime.bundles) != len(artifacts)
        or runtime.declared_resident_charge_bytes > max_resident_bytes
        or runtime.declared_gpu_bytes < 1
        or runtime.declared_resident_charge_bytes < 1
        or runtime.manifest_path
        != mod_root / "Runtime" / "ui-textures-v2.tsv"
    ):
        raise ModBuildError("UI texture backend result differs from its pinned profile")

    records_by_path = {record.relative_path: record for record in records}
    if not removed <= set(records_by_path):
        missing = sorted(removed - set(records_by_path))
        raise ModBuildError(
            f"UI texture backend removed unrecorded profile PNGs: {missing}"
        )
    integrated = [
        record for record in records if record.relative_path not in removed
    ]
    for entry_id in sorted(artifacts):
        artifact = artifacts[entry_id]
        expected = expected_artifacts[entry_id]
        expected_relative = (
            f"Runtime/UiAssetBundles/win64/{expected.bundle_name}"
        )
        if (
            artifact.bundle_name != expected.bundle_name
            or artifact.mod_relative_path != expected_relative
            or not re.fullmatch(r"[0-9a-f]{64}", artifact.sha256)
            or not re.fullmatch(r"[0-9a-f]{8}", artifact.crc32)
            or not re.fullmatch(r"[0-9a-f]{32}", artifact.unity_hash128)
            or not re.fullmatch(r"[0-9a-f]{64}", artifact.package_key)
            or artifact.size_bytes < 1
        ):
            raise ModBuildError(
                f"UI texture bundle result identity changed: {entry_id}"
            )
        path = _safe_output(mod_root, artifact.mod_relative_path)
        record = _record(
            mod_root,
            path,
            "ui_texture_asset_bundle",
            f"unity-ui-assetbundle:{entry_id}:{artifact.bundle_name}",
            metadata={
                "kind": UI_BACKEND_KIND,
                "entry_id": entry_id,
                "bundle": artifact.bundle_name,
                "unity_hash128": artifact.unity_hash128,
                "crc32": artifact.crc32,
            },
        )
        if (
            record.size != artifact.size_bytes
            or record.sha256 != artifact.sha256
        ):
            raise ModBuildError(
                f"UI texture bundle changed after backend validation: {entry_id}"
            )
        integrated.append(record)
    _prune_empty_removed_output_parents(mod_root, removed)
    return integrated


def _build_runtime_companion(
    config: BuilderConfig,
    build_match: BuildMatch,
    mod_root: Path,
    profile: dict[str, Any],
    ui_texture_backend: UiTextureBackendSelection | None = None,
) -> list[OutputRecord]:
    selection = profile.get("runtime")
    dock_rules = profile.get("dock_placement_rules")
    diplomacy_rules = profile.get("diplomacy_rules")
    if selection is None:
        # Fail-closed: ein Regelblock ohne Runtime-Block waere ein leiser
        # No-Op - die Bahn, die die Werte schreiben soll, existiert nicht.
        if (
            dock_rules is not None
            or diplomacy_rules is not None
            or ui_texture_backend is not None
        ):
            raise ModBuildError(
                "Runtime companion build failed: selected runtime payloads "
                "require an enabled runtime contract"
            )
        return []
    try:
        atlas_backend = parse_atlas_backend(profile)
        artifacts = build_runtime_artifacts(
            config,
            build_match,
            mod_root,
            str(profile["id"]),
            selection,
            dock_rules,
            diplomacy_rules,
            atlas_backend,
            ui_texture_backend,
        )
    except (AssetStreamContractError, RuntimeBuildError) as exc:
        raise ModBuildError(f"Runtime companion build failed: {exc}") from exc
    return [
        _record(
            mod_root,
            artifact.path,
            artifact.category,
            artifact.source_reference,
            metadata=artifact.metadata,
        )
        for artifact in artifacts
    ]


_WINDOWS_RESERVED_COMPONENTS = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}

_PROJECT_FILE_KEYS = frozenset(
    {"source", "output", "category", "expected_sha256"}
)
_PROJECT_LOCALE_FILES = {
    "assets/locales/de-DE/crusader.txt": (
        "Locales/de-DE/crusader.txt",
        "de-DE",
    ),
    "assets/locales/en-US/crusader.txt": (
        "Locales/en-US/crusader.txt",
        "en-US",
    ),
}

# Authored Noesis patch files. The script extender applies any XML found under
# Patches/<logical asset path>; a broken patch takes the whole interface down,
# so the transport is an allow-list with a pinned digest, exactly like the
# locale pair above - nothing arbitrary can reach the game through it.
_PROJECT_XAML_PATCHES = {
    "assets/xaml/HUD_Main.dock.xaml": (
        "Patches/Assets/GUI/XAMLResources/HUD_Main.xaml"
    ),
    "assets/xaml/HUD_Main.xaml": (
        "Patches/Assets/GUI/XAMLResources/HUD_Main.xaml"
    ),
    "assets/xaml/HUD_Main.fortifications.xaml": (
        "Patches/Assets/GUI/XAMLResources/HUD_Main.xaml"
    ),
    # Beide logischen Dateien sind patchbar. Der alte HUD_Main-Fehlschlag lag
    # nicht am Extender-Override: der Patch wurde gefunden, seine Operationen
    # wurden wegen einer eigenen Namespace-Deklaration aber nicht eingelesen.
    # MainHUD bleibt zusaetzlich erlaubt, weil der aktuelle Root-Grid-Patch dort
    # im Spiel nachweislich angewandt wird.
    "assets/xaml/MainHUD.xaml": "Patches/Assets/GUI/XAML/MainHUD.xaml",
    "assets/xaml/HUD_AlliesPanel.xaml": (
        "Patches/Assets/GUI/XAMLResources/HUD_AlliesPanel.xaml"
    ),
}

# Hand-drawn sprite deliveries. Unlike the locale pair and the XAML patches the
# allow-list names the DIRECTORY, not the single file: one mosque is 111 frames
# and a per-file list would be unmaintainable. The protection lies elsewhere and
# is stronger - the entry binds a store to exactly one GM group, so a set filed
# under `tile_churches` cannot reach a `body_lord` frame no matter what is
# dropped into the folder, and the profile pins two digests over the delivered
# names and pixels.
#
# `origin` separates self-drawn art from repainted game art. It decides nothing
# in the build; it is recorded in the manifest so that the question "does this
# still carry Firefly pixels" stays answerable later. `assets/sprites/derived/`
# is excluded from Git for that reason.
_PROJECT_AUTHORED_SPRITE_SETS: dict[str, tuple[str, str]] = {
    # tree_cactii is the first store on purpose: plain_shader, all 17 frames
    # KEEP_CRUSADER, and no profile ships the group today - nothing existing can
    # be displaced by it.
    #
    # Gemessen, weil es sonst wie ein Widerspruch aussieht: LOADER_GROUP_TABLE
    # meldet declared_image_count=16, das Mapping fuehrt 17 Frames. Kein
    # Widerspruch - declared_image_count ist die Scangrenze, das Feld ist
    # declared + additional_storage + 1 = 17 lang (vgl. gm_atlas.py:4845), und
    # die Mapping-Indizes laufen luecklos 0..16. Alle 17 sind adressierbar, es
    # wird also kein Bild umsonst gezeichnet.
    "assets/sprites/authored/tree-cactii-europe": ("tree_cactii", "authored"),
    # Dieselbe Gruppe, andere Herkunft: tools/vegetation_gen.py malt die 17
    # Kakteenplaetze aus skalierten und montierten Stronghold-1-Straeuchern
    # (tree_shrub1/tree_shrub2). Das ist abgeleitetes Firefly-Material und muss
    # deshalb unter assets/sprites/derived/ liegen (gitignoriert) - der
    # authored-Eintrag darueber bleibt fuer selbst gezeichnete Frames und als
    # Testfixture. Zwei Ablagen fuer eine Gruppe sind erlaubt, solange ein
    # Profil nur eine davon waehlt; waehlt es beide, schrieben beide
    # Override/Sprites/<name>.png, und _copy_authored_sprites bricht beim
    # zweiten Schreiben ab ("collides with another output").
    "assets/sprites/derived/tree-cactii-europe": ("tree_cactii", "derived"),
    # Der europaeische Schleuderer ist am 17.08.2026 auf Anweisung des
    # Eigentuemers herausgenommen worden - der Versuch hat nicht funktioniert.
    # Die Ablage assets/sprites/derived/european-slinger-v1 liegt samt Werkzeug,
    # Modul und Test unter work/quarantine/slinger-versuch/. Der Eintrag ist
    # hier entfernt, weil er sonst auf ein Verzeichnis zeigt, das es nicht mehr
    # gibt. Die Einheit selbst bleibt: `body_arab_slinger` in loader_groups,
    # der Rostertext und die Locales sind unangetastet.
    # Das europaeische Wildschwein auf dem Hyaenenplatz: tools/boar_recolour.py
    # faerbt Crusaders eigene Hyaenenframes nach gemessenen Zielwerten um
    # (Farbton auf den Ochsenwert, Saettigung und Helligkeit halber Weg zum
    # Tanzbaeren). Leinwand, Fusspunkt und Teammasken bleiben unveraendert -
    # umgefaerbt wird ausschliesslich der Farbanteil sichtbarer Fellpixel.
    # `derived`, weil das uebermalte Firefly-Pixel sind. Siehe docs/WILDTIERE.md.
    "assets/sprites/derived/boar-europe": ("body_hyena", "derived"),
    # Der Kamelplatz, unsichtbar gemacht: 944 vollstaendig transparente Frames
    # auf den unveraenderten Crusader-Leinwaenden, erzeugt von
    # tools/slot_blank.py. `authored` ist hier richtig und nicht `derived` -
    # die Bilder tragen keinen einzigen Firefly-Pixel, nur die Abmessung des
    # Platzes, und die Ablage misst zusammen 234 KiB.
    #
    # Die Neubelegung bleibt damit ausdruecklich offen: GM 94 ist in Stronghold 1
    # `GM_BODY_BEAR` (docs/KAMELE.md). Eine spaetere Baerenablage tritt als
    # zweiter Eintrag fuer dieselbe Gruppe daneben - erlaubt, solange ein Profil
    # genau eine der beiden waehlt - und wird im Profil getauscht, nicht hier
    # ueberschrieben.
    "assets/sprites/authored/camel-slot-blank": ("body_camel", "authored"),
    # Rueckweg fuer mehrteilige Gebaeude: tools/tile_objects.py setzt einen
    # zusammenhaengenden Frameblock als geschichtete OpenRaster-Datei zusammen
    # und zerlegt ausschliesslich die gepinnten Tile-Ebenen wieder in diese
    # Ablagen. `authored` ist fuer vollstaendig neu gezeichnete Bilder;
    # `derived` bleibt der richtige Ort, sobald exportierte Firefly-Pixel als
    # Grundlage dienten. Die meisten Produktionsprofile liefern dieselben
    # Gruppen zugleich als GM-Atlas; profile-add verlangt dafuer die sichtbare
    # Zustimmung --allow-atlas-shadow.
    "assets/sprites/authored/tile-buildings1-europe": ("tile_buildings1", "authored"),
    "assets/sprites/derived/tile-buildings1-europe": ("tile_buildings1", "derived"),
    "assets/sprites/authored/tile-buildings2-europe": ("tile_buildings2", "authored"),
    "assets/sprites/derived/tile-buildings2-europe": ("tile_buildings2", "derived"),
    "assets/sprites/authored/tile-castle-europe": ("tile_castle", "authored"),
    "assets/sprites/derived/tile-castle-europe": ("tile_castle", "derived"),
    "assets/sprites/authored/tile-churches-europe": ("tile_churches", "authored"),
    "assets/sprites/derived/tile-churches-europe": ("tile_churches", "derived"),
    "assets/sprites/authored/tile-goods-europe": ("tile_goods", "authored"),
    "assets/sprites/derived/tile-goods-europe": ("tile_goods", "derived"),
    "assets/sprites/authored/tile-walls-europe": ("tile_walls", "authored"),
    "assets/sprites/derived/tile-walls-europe": ("tile_walls", "derived"),
    "assets/sprites/authored/tile-workshops-europe": ("tile_workshops", "authored"),
    "assets/sprites/derived/tile-workshops-europe": ("tile_workshops", "derived"),
    # Die elf Bauteile, die es NUR in Crusader gibt: anim_castle 128-138, weil
    # Stronghold 1 an keinem Index einen Spender fuehrt
    # (docs/TUERME_UND_TORHAEUSER.md, Ursache 3). Sie bleiben transparent.
    # `derived`, weil das keine gezeichneten, sondern bewusst geleerte
    # Firefly-Pixel sind. Das Produktionsprofil liefert denselben Atlas, die
    # Ablage braucht dort also --allow-atlas-shadow.
    "assets/sprites/derived/anim-castle-europe": ("anim_castle", "derived"),
}


def _register_user_sprite_sets() -> None:
    """Eigene Lieferablagen der Universal-Suite (config/benutzer-ablagen.json).

    Die Tabelle oben bleibt die Freigabe fuer die Projektablagen. Die Suite
    legt Ablagen je Gruppe unter assets/sprites/<herkunft>/benutzer-*/ an und
    traegt sie in diese Datei ein; hier werden sie mit derselben Bindung
    "eine Ablage = genau eine GM-Gruppe" freigegeben. Fehlt die Datei, bleibt
    alles wie bisher.
    """

    registry = Path(__file__).resolve().parents[2] / "config" / "benutzer-ablagen.json"
    try:
        entries = json.loads(registry.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    for store, spec in (entries.get("ablagen", {}) if isinstance(entries, dict) else {}).items():
        try:
            group, origin = str(spec["gruppe"]), str(spec["herkunft"])
        except (KeyError, TypeError):
            continue
        if origin in ("authored", "derived") and store == f"assets/sprites/{origin}/{store.rsplit('/', 1)[-1]}":
            _PROJECT_AUTHORED_SPRITE_SETS.setdefault(store, (group, origin))


_register_user_sprite_sets()
_AUTHORED_SPRITE_OUTPUT_PREFIX = "Override/Sprites/"
# Herkunft und Ablageort sind dasselbe: `.gitignore` schliesst
# `assets/sprites/derived/` aus, und diese Zeile ist der einzige Schutz davor,
# dass uebermalte Firefly-Frames in die Historie geraten. Sie wirkt nur, wenn
# eine Ablage mit dieser Herkunft auch dort liegt, deshalb steht die Zuordnung
# hier und wird in _prepare_authored_sprites gegen jeden Eintrag geprueft.
_AUTHORED_SPRITE_ORIGIN_ROOTS = {
    "authored": "assets/sprites/authored/",
    "derived": "assets/sprites/derived/",
}
_AUTHORED_SPRITE_ORIGINS = frozenset(_AUTHORED_SPRITE_ORIGIN_ROOTS)
MAX_AUTHORED_SPRITE_BYTES = 1024 * 1024
# A decision, not a measurement: the largest real target frame in the whole
# mapping is tile_churches 655 at 64x732, so 2048 leaves generous room while
# still bounding what a stray file can hand to the loader.
MAX_AUTHORED_SPRITE_EDGE = 2048
_AUTHORED_SPRITE_KEYS = frozenset(
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

_AUTHORED_UI_KEYS = frozenset(
    {
        "source",
        "output",
        "category",
        "origin",
        "width",
        "height",
        "expected_sha256",
    }
)
_AUTHORED_UI_ORIGIN_ROOTS = {
    "authored": "assets/ui/authored/",
    "derived": "assets/ui/derived/",
}
_AUTHORED_UI_OUTPUTS = {
    "UI-MasterAtlas.png": (8192, 8192),
    "UI-TrailAtlas.png": (8192, 8192),
    "UI-Colour1Atlas.png": (4096, 4096),
    "UI-Colour2Atlas.png": (4096, 4096),
}
_AUTHORED_UI_OUTPUT_PREFIX = "Override/Assets/GUI/Sprites/"
MAX_AUTHORED_UI_BYTES = 128 * 1024 * 1024

_AUTHORED_BACKGROUND_KEYS = frozenset(
    {"source", "output", "category", "width", "height", "expected_sha256"}
)
_AUTHORED_BACKGROUND_SOURCE_ROOT = "work/hintergruende/europa-generiert/fertig"
_AUTHORED_BACKGROUND_OUTPUT_PREFIX = "Override/Assets/GUI/Images/"
MAX_AUTHORED_BACKGROUND_BYTES = 64 * 1024 * 1024
# Large enough for an 8K frame, while preventing a small compressed PNG from
# expanding into an unbounded image during validation.
MAX_AUTHORED_BACKGROUND_PIXELS = 32 * 1024 * 1024

_AUTHORED_MENU_VIDEO_KEYS = frozenset(
    {"source", "output", "category", "expected_sha256"}
)
_AUTHORED_MENU_VIDEO_SOURCE_ROOT = "work/hintergruende/europa-generiert/video"
_AUTHORED_MENU_VIDEO_OUTPUT_PREFIX = "Override/Assets/GUI/Video/"
MAX_AUTHORED_MENU_VIDEO_BYTES = 128 * 1024 * 1024
_WEBM_EBML_MAGIC = b"\x1a\x45\xdf\xa3"
_WEBM_DOCTYPE_SIGNATURE = b"\x42\x82\x84webm"


@dataclass(frozen=True)
class _PreparedAuthoredSprite:
    source_dir: str
    group: str
    origin: str
    name: str
    output: str
    category: str
    data: bytes
    width: int
    height: int
    is_mask: bool
    target_width: int
    target_height: int
    target_pivot_x: float
    target_pivot_y: float
    foot_px_x: float
    foot_px_y: float


@dataclass(frozen=True)
class _PreparedProjectFile:
    source: str
    output: str
    category: str
    data: bytes
    metadata: dict[str, object]


@dataclass(frozen=True)
class _PreparedAuthoredUiAtlas:
    source: str
    output: str
    origin: str
    data: bytes
    width: int
    height: int


@dataclass(frozen=True)
class _PreparedAuthoredBackground:
    source: str
    output: str
    data: bytes
    width: int
    height: int


@dataclass(frozen=True)
class _PreparedAuthoredMenuVideo:
    source: str
    output: str
    data: bytes


def _canonical_portable_relative_path(value: object, label: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ModBuildError(f"Unsafe {label} path: {value!r}")
    pure = PurePosixPath(value)
    if (
        pure.is_absolute()
        or not pure.parts
        or any(part in {"", ".", ".."} for part in pure.parts)
        or pure.as_posix() != value
    ):
        raise ModBuildError(f"Unsafe {label} path: {value!r}")
    for component in pure.parts:
        if (
            component.endswith((" ", "."))
            or any(character in component for character in '<>:"|?*')
            or any(ord(character) < 32 for character in component)
            or component.split(".", 1)[0].upper() in _WINDOWS_RESERVED_COMPONENTS
        ):
            raise ModBuildError(f"Unsafe {label} path: {value!r}")
    return pure


def _safe_directory_component(value: str, label: str) -> str:
    """Validate a single portable Windows directory component.

    Profiles are local inputs, but allowing their ID to introduce another path
    level would defeat the exact per-profile transaction boundary.  Rechecking
    the configured mod folder here also protects direct ``BuilderConfig`` users
    that did not call ``validate_config`` first.
    """

    if (
        not value
        or value in {".", ".."}
        or value.endswith((" ", "."))
        or any(character in value for character in '<>:"/\\|?*')
        or any(ord(character) < 32 for character in value)
    ):
        raise ModBuildError(f"Unsafe {label} directory component: {value!r}")
    device_name = value.split(".", 1)[0].upper()
    if device_name in _WINDOWS_RESERVED_COMPONENTS:
        raise ModBuildError(f"Unsafe {label} Windows device name: {value!r}")
    return value


def _is_link_or_junction(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if is_junction is not None and is_junction():
        return True
    try:
        attributes = path.lstat().st_file_attributes
    except (AttributeError, OSError):
        return False
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse_flag)


def _path_lexists(path: Path) -> bool:
    return os.path.lexists(path)


def _game_data_source_path(
    configured_data_dir: Path,
    relative: object,
    label: str,
) -> Path:
    """Resolve one direct, portable game-data input without following reparses."""

    pure = _canonical_portable_relative_path(relative, label)
    configured_root = Path(os.path.abspath(configured_data_dir))
    if configured_root.name not in {
        "Stronghold 1 Definitive Edition_Data",
        "Stronghold Crusader Definitive Edition_Data",
    }:
        raise ModBuildError(
            f"Configured game-data root is not canonical for {label}: {configured_root}"
        )
    source = configured_root.joinpath(*pure.parts)
    current = configured_root
    candidates = [current]
    for component in pure.parts:
        current = current / component
        candidates.append(current)
    for candidate in candidates:
        if _path_lexists(candidate) and _is_link_or_junction(candidate):
            raise ModBuildError(
                f"Game-data source has a link, junction, or reparse ancestor: "
                f"{candidate}"
            )
    try:
        root_info = configured_root.lstat()
        source_info = source.lstat()
        resolved_root = configured_root.resolve(strict=True)
        resolved_source = source.resolve(strict=True)
    except OSError as exc:
        raise ModBuildError(f"Game-data source is missing: {source}: {exc}") from exc
    if resolved_root != configured_root:
        raise ModBuildError(
            "Configured game-data root resolves through a link, junction, or "
            f"reparse ancestor: {configured_root} -> {resolved_root}"
        )
    if not stat.S_ISDIR(root_info.st_mode):
        raise ModBuildError(
            f"Configured game-data root is not a directory: {configured_root}"
        )
    if not stat.S_ISREG(source_info.st_mode):
        raise ModBuildError(f"Game-data source is not a direct regular file: {source}")
    if resolved_source == resolved_root or resolved_root not in resolved_source.parents:
        raise ModBuildError(
            f"Game-data source escapes configured data root: {relative!r}"
        )
    return resolved_source


def _stable_stat_identity(info: os.stat_result) -> tuple[int, ...]:
    # Windows reports creation time as ``st_ctime`` for a path stat but may
    # report last-write time for the same field through ``fstat``.  Device,
    # inode, file type, size and nanosecond mtime are consistent across both
    # handles and still detect replacement or content mutation.
    return (
        int(info.st_dev),
        int(info.st_ino),
        int(stat.S_IFMT(info.st_mode)),
        int(info.st_size),
        int(info.st_mtime_ns),
    )


def _read_stable_file(path: Path, limit: int) -> bytes:
    """Read one project input atomically enough to hash it afterwards.

    Extracted so that a second transport can reuse the tear-proof read without
    inheriting the locale byte limit.  The limit stays a literal at each call
    site: it is a per-transport contract, not a global one.
    """

    try:
        path_before = path.lstat()
        if _is_link_or_junction(path) or not stat.S_ISREG(path_before.st_mode):
            raise ModBuildError(f"Project file is not a direct regular file: {path}")
        with path.open("rb") as stream:
            handle_before = os.fstat(stream.fileno())
            chunks: list[bytes] = []
            size = 0
            while True:
                chunk = stream.read(min(64 * 1024, limit + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > limit:
                    raise ModBuildError(
                        f"Project file exceeds {limit} bytes: {path}"
                    )
            handle_after = os.fstat(stream.fileno())
        path_after = path.lstat()
    except ModBuildError:
        raise
    except OSError as exc:
        raise ModBuildError(f"Cannot read project file safely: {path}: {exc}") from exc

    identities = {
        _stable_stat_identity(path_before),
        _stable_stat_identity(handle_before),
        _stable_stat_identity(handle_after),
        _stable_stat_identity(path_after),
    }
    if len(identities) != 1:
        raise ModBuildError(f"Project file changed while it was read: {path}")
    return b"".join(chunks)


def _read_stable_project_file(path: Path) -> bytes:
    return _read_stable_file(path, MAX_LOCALE_BYTES)


def _read_stable_authored_sprite(path: Path) -> bytes:
    # Deliberately its own limit. The 64 KiB locale ceiling is a separate,
    # tested contract and must not be widened just because a drawn PNG is
    # larger; the biggest single sprite shipped today is 63,919 bytes and would
    # sit right under it.
    return _read_stable_file(path, MAX_AUTHORED_SPRITE_BYTES)


def _read_stable_authored_ui(path: Path) -> bytes:
    # Ebenfalls ein eigener Vertrag. Ein UI-Blatt ist 8192x8192 und damit drei
    # Groessenordnungen ueber der Locale-Schranke: die beiden ausgelieferten
    # Blaetter messen 85 MB, MAX_AUTHORED_UI_BYTES laesst 128 MB zu.
    return _read_stable_file(path, MAX_AUTHORED_UI_BYTES)


def _read_stable_authored_background(path: Path) -> bytes:
    return _read_stable_file(path, MAX_AUTHORED_BACKGROUND_BYTES)


def _read_stable_authored_menu_video(path: Path) -> bytes:
    return _read_stable_file(path, MAX_AUTHORED_MENU_VIDEO_BYTES)


def _project_source_path(
    config: BuilderConfig,
    relative: str,
    *,
    allowed_root: str = "assets",
) -> Path:
    pure = _canonical_portable_relative_path(relative, "project source")
    allowed = _canonical_portable_relative_path(
        allowed_root, "project source allowed root"
    )
    if pure == allowed or allowed not in pure.parents:
        raise ModBuildError(
            f"Project source escapes project {allowed.as_posix()}: {relative}"
        )
    configured_root = Path(os.path.abspath(config.project_root))
    source = configured_root.joinpath(*pure.parts)
    current = configured_root
    for component in pure.parts:
        if _path_lexists(current) and _is_link_or_junction(current):
            raise ModBuildError(
                f"Project source has a link, junction, or reparse ancestor: {current}"
            )
        current = current / component
    if _path_lexists(current) and _is_link_or_junction(current):
        raise ModBuildError(
            f"Project source has a link, junction, or reparse ancestor: {current}"
        )
    try:
        resolved_root = configured_root.resolve(strict=True)
        resolved_allowed = configured_root.joinpath(*allowed.parts).resolve(strict=True)
        resolved_source = source.resolve(strict=True)
    except OSError as exc:
        raise ModBuildError(f"Project source is missing: {source}: {exc}") from exc
    if (
        resolved_allowed == resolved_root
        or resolved_root not in resolved_allowed.parents
        or resolved_source == resolved_allowed
        or resolved_allowed not in resolved_source.parents
    ):
        raise ModBuildError(
            f"Project source escapes project {allowed.as_posix()}: {relative}"
        )
    return source


# The prefixes the extender's XamlPatcher registers before reading a patch
# (XamlPatcher.CreateNamespaceManager). A patch file uses them without
# declaring them, which is what every working patch in this installation does -
# SHCDEAutoRecruit and UniversalSiegeAI both write bare <Patch> roots and
# local:PropEx attributes.
#
# Declaring them in the file instead looks tidier and is wrong: a patch that
# carried xmlns:local was found and opened by the extender and then produced no
# "Applying patch:" line at all, while other mods logged every operation. So the
# well-formedness check has to supply the prefixes the way the patcher does,
# rather than demand the file bring its own.
_PATCH_NAMESPACE_DECLARATIONS = (
    ' xmlns:local="clr-namespace:CrusaderDE"'
    ' xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"'
    ' xmlns:sys="clr-namespace:System;assembly=mscorlib"'
)


def _parse_patch_document(data: bytes) -> ElementTree.Element:
    """Parse a patch file in the namespace context the extender provides.

    The file itself is not standalone XML - it uses prefixes the patcher
    registers - so parsing it verbatim would reject exactly the shape that
    works in game. Bind the prefixes on the root, parse that, and hand back the
    result for structural checking.
    """

    text = data.decode("utf-8")
    match = re.search(r"<Patch(\s|>)", text)
    if match is None:
        # Let the plain parse produce the error; the caller reports it.
        return ElementTree.fromstring(text)
    insert_at = match.start() + len("<Patch")
    bound = text[:insert_at] + _PATCH_NAMESPACE_DECLARATIONS + text[insert_at:]
    return ElementTree.fromstring(bound)


# Sichtrezepte der Festungs-Mauerarten (2026-09-02): ein TSV-Katalog plus
# RGBA-Boegen aus tools/fortification_visual_recipes.py. Sie sind aus Firefly-
# Pixeln abgeleitet (gitignoriertes derived-Verzeichnis) und werden wie die
# XAML-Patches per Allow-List und gepinntem Digest transportiert. Der Katalog
# landet unter Runtime/, die Boegen daneben; runtime_build pinnt Groesse und
# Digest des Katalogs in den Festungsvertrag.
_FORTIFICATION_VISUAL_SOURCE_ROOT = "assets/sprites/derived/fortification-recipes-v1"
_FORTIFICATION_VISUAL_CATALOG_NAME = "fortification-sprites-v1.tsv"
_FORTIFICATION_VISUAL_CATALOG_OUTPUT = "Runtime/fortification-sprites-v1.tsv"
_FORTIFICATION_VISUAL_SHEET_OUTPUT_PREFIX = "Runtime/fortification-sprites-v1/"
_FORTIFICATION_VISUAL_CATALOG_SCHEMA = (
    "# stronghold-europe-de.fortification-sprites.v3"
)
MAX_FORTIFICATION_VISUAL_SHEET_BYTES = 64 * 1024 * 1024
MAX_FORTIFICATION_VISUAL_SHEET_EDGE = 2048


def _prepare_fortification_visuals(
    config: BuilderConfig,
    profile: dict[str, Any],
) -> tuple[_PreparedProjectFile, ...]:
    """Stage the wall visual recipe catalogue and its sheets."""

    selections = profile.get("fortification_visuals", [])
    if not isinstance(selections, list):
        raise ModBuildError("Profile key 'fortification_visuals' must be a list")
    if not selections:
        return ()
    runtime = profile.get("runtime", {})
    if not isinstance(runtime, dict) or not runtime.get("fortifications"):
        raise ModBuildError(
            "fortification_visuals require runtime.fortifications"
        )
    prepared: list[_PreparedProjectFile] = []
    seen_outputs: set[str] = set()
    catalog_seen = False
    for index, selection in enumerate(selections):
        if not isinstance(selection, dict) or set(selection) != _PROJECT_FILE_KEYS:
            raise ModBuildError(
                f"fortification_visuals[{index}] must contain exactly "
                f"{sorted(_PROJECT_FILE_KEYS)}"
            )
        source = selection["source"]
        output = selection["output"]
        source_path = _canonical_portable_relative_path(
            source, "fortification visual source"
        )
        _canonical_portable_relative_path(output, "fortification visual output")
        if source_path.parent.as_posix() != _FORTIFICATION_VISUAL_SOURCE_ROOT:
            raise ModBuildError(
                f"fortification visual source is not allowlisted: {source!r}"
            )
        if source_path.name == _FORTIFICATION_VISUAL_CATALOG_NAME:
            expected_output = _FORTIFICATION_VISUAL_CATALOG_OUTPUT
            catalog_seen = True
        elif source_path.suffix == ".png":
            expected_output = (
                _FORTIFICATION_VISUAL_SHEET_OUTPUT_PREFIX + source_path.name
            )
        else:
            raise ModBuildError(
                f"fortification visual source has an unexpected kind: {source!r}"
            )
        if output != expected_output:
            raise ModBuildError(
                f"fortification visual output does not match its source: {source!r}"
            )
        if selection["category"] != "fortification_visual":
            raise ModBuildError(
                "fortification visual category must be 'fortification_visual'"
            )
        if output.casefold() in seen_outputs:
            raise ModBuildError(f"fortification visual selected twice: {source!r}")
        seen_outputs.add(output.casefold())
        path = _project_source_path(config, source)
        data = _read_stable_file(path, MAX_FORTIFICATION_VISUAL_SHEET_BYTES)
        digest = hashlib.sha256(data).hexdigest()
        if digest != selection["expected_sha256"]:
            raise ModBuildError(
                f"fortification visual digest changed for {source}: "
                f"actual={digest} expected={selection['expected_sha256']}"
            )
        metadata: dict[str, object] = {
            "kind": "fortification_visual_v1",
            "sha256": digest,
        }
        if source_path.suffix == ".png":
            try:
                with Image.open(io.BytesIO(data)) as opened:
                    opened.load()
                    image_format = opened.format
                    image_mode = opened.mode
                    image_size = opened.size
            except Exception as exc:
                raise ModBuildError(
                    f"fortification visual sheet is not a readable PNG: {source}"
                ) from exc
            if (
                image_format != "PNG"
                or image_mode != "RGBA"
                or max(image_size) > MAX_FORTIFICATION_VISUAL_SHEET_EDGE
                or min(image_size) < 1
            ):
                raise ModBuildError(
                    f"fortification visual sheet must be RGBA PNG up to "
                    f"{MAX_FORTIFICATION_VISUAL_SHEET_EDGE} px: {source}"
                )
            metadata["width"], metadata["height"] = image_size
        else:
            first_line = data.split(b"\n", 1)[0].decode("utf-8", "replace")
            if first_line != _FORTIFICATION_VISUAL_CATALOG_SCHEMA:
                raise ModBuildError(
                    f"fortification visual catalogue schema changed: {source}"
                )
            metadata["rows"] = sum(
                1
                for line in data.decode("utf-8", "replace").splitlines()
                if line and not line.startswith("#")
            ) - 1
        prepared.append(
            _PreparedProjectFile(
                source=source,
                output=output,
                category="fortification_visual",
                data=data,
                metadata=metadata,
            )
        )
    if not catalog_seen:
        raise ModBuildError(
            "fortification_visuals must include the fortification-sprites-v1.tsv catalogue"
        )
    return tuple(sorted(prepared, key=lambda item: item.output))


def _prepare_xaml_patches(
    config: BuilderConfig,
    profile: dict[str, Any],
) -> tuple[_PreparedProjectFile, ...]:
    """Stage authored XAML patches, each one allow-listed and digest-pinned."""

    selections = profile.get("xaml_patches", [])
    if not isinstance(selections, list):
        raise ModBuildError("Profile key 'xaml_patches' must be a list")
    if not selections:
        return ()
    prepared: list[_PreparedProjectFile] = []
    seen: set[str] = set()
    for index, selection in enumerate(selections):
        if not isinstance(selection, dict) or set(selection) != _PROJECT_FILE_KEYS:
            raise ModBuildError(
                f"XAML patch {index} must contain exactly {sorted(_PROJECT_FILE_KEYS)}"
            )
        source = selection["source"]
        output = selection["output"]
        _canonical_portable_relative_path(source, "xaml patch source")
        _canonical_portable_relative_path(output, "xaml patch output")
        if source not in _PROJECT_XAML_PATCHES:
            raise ModBuildError(f"XAML patch source is not allowlisted: {source!r}")
        if output != _PROJECT_XAML_PATCHES[source]:
            raise ModBuildError(
                f"XAML patch output does not match its source: {source!r}"
            )
        if selection["category"] != "xaml_patch":
            raise ModBuildError("XAML patch category must be 'xaml_patch'")
        if source in seen:
            raise ModBuildError(f"XAML patch selected twice: {source!r}")
        seen.add(source)
        path = _project_source_path(config, source)
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != selection["expected_sha256"]:
            raise ModBuildError(
                f"XAML patch digest changed for {source}: "
                f"actual={digest} expected={selection['expected_sha256']}"
            )
        try:
            parsed = _parse_patch_document(data)
        except (ElementTree.ParseError, UnicodeDecodeError) as exc:
            # A malformed patch reaches Noesis and blanks the interface. Refuse
            # it here, where the failure is a build error instead of a black
            # screen with the music still playing.
            raise ModBuildError(f"XAML patch is not well-formed XML: {source}") from exc
        if parsed.tag != "Patch" or not list(parsed):
            raise ModBuildError(
                f"XAML patch has no <Patch> root with operations: {source}"
            )
        for operation in parsed:
            if operation.tag != "Operation" or not operation.get("XPath"):
                raise ModBuildError(
                    f"XAML patch operation lacks a type or XPath: {source}"
                )
        prepared.append(
            _PreparedProjectFile(
                source=source,
                output=output,
                category="xaml_patch",
                data=data,
                metadata={
                    "kind": "noesis_xaml_patch_v1",
                    "sha256": digest,
                    "operations": len(list(parsed)),
                },
            )
        )
    return tuple(sorted(prepared, key=lambda item: item.output))


def _authored_sprite_group_claims(
    profile: dict[str, Any],
) -> tuple[set[str], set[str]]:
    """Return the group names already claimed by an atlas / by a sparse backend.

    Read from the raw profile the same way ``_validate_group_backend_selection``
    reads it, because this runs before the specs are parsed and a malformed
    entry must not turn into a *missing* claim.
    """

    def raw_names(key: str, field: str) -> set[str]:
        raw = profile.get(key, [])
        if not isinstance(raw, list):
            return set()
        names: set[str] = set()
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            value = entry.get(field)
            if isinstance(value, str) and value:
                names.add(value.casefold())
            elif isinstance(value, list):
                names.update(
                    item.casefold()
                    for item in value
                    if isinstance(item, str) and item
                )
        return names

    atlas_claims = raw_names("gm_atlases", "gm_file_name")
    sparse_claims = raw_names(REVIEW_INDIVIDUAL_SOURCE_ONLY_MODE, "gm_file_name")
    sparse_claims |= raw_names(SHARED_GM_ATLAS_PROFILE_KEY, "member_names")
    return atlas_claims, sparse_claims


def _prepare_authored_sprites(
    config: BuilderConfig,
    profile: dict[str, Any],
    mapping: dict[str, Any],
) -> tuple[_PreparedAuthoredSprite, ...]:
    """Stage hand-drawn sprite PNGs for the individual override route.

    This is the one build path that needs no donor in Stronghold 1: it ships
    pixels that were drawn, not converted. It therefore must NOT inherit the
    gate of ``_build_sprites``, which demands REPLACE_EXACT/REPLACE_DERIVED -
    drawn art is wanted exactly where no donor exists, i.e. on KEEP_CRUSADER
    slots. All it takes from the mapping is the Crusader ``target`` block.

    The delivered canvas must equal the Crusader slot exactly. That is not
    tidiness: the loader forces the slot's normalised pivot onto whatever canvas
    arrives (see ``authored_sprite_foot_point``), so a different canvas moves
    the frame on its tile while every other gate stays green. Equal canvas makes
    the deviation provably zero. Whether a different canvas lands where the
    formula predicts has never been measured in a running game; until it has,
    this refuses it.
    """

    selections = profile.get("authored_sprites", [])
    if not isinstance(selections, list):
        raise ModBuildError("Profile key 'authored_sprites' must be a list")
    if not selections:
        return ()

    proposals = {str(entry["name"]): entry for entry in mapping["sprites"]}
    atlas_claims, sparse_claims = _authored_sprite_group_claims(profile)
    prepared: list[_PreparedAuthoredSprite] = []
    seen_dirs: set[str] = set()
    for index, selection in enumerate(selections):
        if not isinstance(selection, dict) or set(selection) != _AUTHORED_SPRITE_KEYS:
            raise ModBuildError(
                f"Authored sprite set {index} must contain exactly "
                f"{sorted(_AUTHORED_SPRITE_KEYS)}"
            )
        source_dir = selection["source_dir"]
        _canonical_portable_relative_path(source_dir, "authored sprite source")
        if source_dir not in _PROJECT_AUTHORED_SPRITE_SETS:
            raise ModBuildError(
                f"Authored sprite store is not allowlisted: {source_dir!r}"
            )
        if source_dir in seen_dirs:
            raise ModBuildError(f"Authored sprite store selected twice: {source_dir!r}")
        seen_dirs.add(source_dir)
        allowed_group, allowed_origin = _PROJECT_AUTHORED_SPRITE_SETS[source_dir]
        group = selection["group"]
        if group != allowed_group:
            raise ModBuildError(
                f"Authored sprite store {source_dir} is bound to group "
                f"{allowed_group!r}, not {group!r}"
            )
        if selection["origin"] != allowed_origin:
            raise ModBuildError(
                f"Authored sprite store {source_dir} is bound to origin "
                f"{allowed_origin!r}, not {selection['origin']!r}"
            )
        if allowed_origin not in _AUTHORED_SPRITE_ORIGINS:  # pragma: no cover
            raise ModBuildError(f"Unknown authored sprite origin: {allowed_origin!r}")
        if selection["category"] != AUTHORED_SPRITE_CATEGORY:
            raise ModBuildError(
                f"Authored sprite category must be {AUTHORED_SPRITE_CATEGORY!r}"
            )
        shadow = selection["allow_atlas_shadow"]
        if not isinstance(shadow, bool):
            raise ModBuildError("Authored sprite allow_atlas_shadow must be a boolean")
        folded = group.casefold()
        if folded in sparse_claims:
            raise ModBuildError(
                "A GM group cannot be delivered as authored sprites and by a "
                f"sparse/shared backend at once: {group}"
            )
        if folded in atlas_claims and not shadow:
            # The loader lets an individual PNG win over an atlas frame by name,
            # and the output paths do not collide, so no uniqueness check can
            # see it. Only the profile can say that shadowing is intended.
            raise ModBuildError(
                f"Authored sprites for {group} would silently shadow the atlas "
                "the same profile ships; set allow_atlas_shadow if intended"
            )
        loader = LOADER_GROUP_TABLE.get(group)
        if loader is None:
            raise ModBuildError(f"Authored sprite group is not a loader group: {group}")

        directory = _project_source_path(config, source_dir)
        # Nach der Pfadaufloesung, damit die schaerfere Diagnose "escapes
        # project assets" die erste bleibt. Hier geht es nur noch um die
        # Zuordnung innerhalb von assets/: `.gitignore` schliesst
        # `assets/sprites/derived/` aus, und das schuetzt nur, wenn eine
        # Ablage mit Herkunft `derived` auch wirklich dort liegt. Ein
        # Eintragsfehler in _PROJECT_AUTHORED_SPRITE_SETS wuerde sonst
        # uebermalte Firefly-Frames in ein von Git verfolgtes Verzeichnis
        # legen - und Historie laesst sich nicht sauber zuruecknehmen.
        origin_root = _AUTHORED_SPRITE_ORIGIN_ROOTS.get(allowed_origin)
        if origin_root is None or not source_dir.startswith(origin_root):
            raise ModBuildError(
                f"Authored sprite store {source_dir} has origin "
                f"{allowed_origin!r} but does not live below "
                f"{origin_root or '<unknown origin>'}"
            )
        if not directory.is_dir():
            raise ModBuildError(f"Authored sprite store is not a directory: {directory}")
        try:
            entries = sorted(os.scandir(directory), key=lambda item: item.name)
        except OSError as exc:
            raise ModBuildError(
                f"Cannot read authored sprite store {directory}: {exc}"
            ) from exc

        rows: list[dict[str, Any]] = []
        by_name: dict[str, dict[str, Any]] = {}
        for entry in entries:
            path = Path(entry.path)
            if _is_link_or_junction(path) or not entry.is_file(follow_symlinks=False):
                raise ModBuildError(
                    f"Authored sprite store holds a non-file entry: {path}"
                )
            if not entry.name.endswith(".png"):
                # Nothing but the delivery itself may live here, so that "what
                # is in the folder" and "what is shipped" cannot drift apart.
                raise ModBuildError(
                    f"Authored sprite store holds a non-PNG entry: {path}"
                )
            flat = entry.name[: -len(".png")]
            is_mask = flat.endswith("_m")
            name = flat[: -len("_m")] if is_mask else flat
            if _safe_sprite_filename(name) != name + ".png":  # pragma: no cover
                raise ModBuildError(f"Unsafe authored sprite name: {name!r}")
            proposal = proposals.get(name)
            if proposal is None or proposal.get("target") is None:
                raise ModBuildError(
                    f"Authored sprite has no Crusader target slot: {name}"
                )
            if str(proposal.get("group", "")) != group:
                raise ModBuildError(
                    f"Authored sprite {name} belongs to group "
                    f"{proposal.get('group')!r}, not {group!r}"
                )
            if parse_loader_frame_name(name, group, loader.dash_format) is None:
                raise ModBuildError(
                    f"Authored sprite name is not a loader frame of {group}: {name}"
                )
            data = _read_stable_authored_sprite(path)
            try:
                # Aus den gelesenen Bytes, nicht noch einmal vom Pfad: genau
                # diese Bytes werden ausgeliefert und digestiert. Ein zweites
                # Oeffnen der Datei koennte eine andere Fassung erwischen, und
                # dann waere die Leinwandpruefung - der Kern dieses Weges -
                # gegen ein Bild gelaufen, das nie im Spiel landet.
                with Image.open(io.BytesIO(data)) as image:
                    image.load()
                    image_format = image.format
                    image_mode = image.mode
                    image_size = image.size
            except (OSError, ValueError, Image.DecompressionBombError) as exc:
                raise ModBuildError(f"Authored sprite is not readable: {path}: {exc}") from exc
            if image_format != "PNG":
                raise ModBuildError(
                    f"Authored sprite is not a PNG: {path}: {image_format}"
                )
            if image_mode != "RGBA":
                raise ModBuildError(
                    f"Authored sprite must be RGBA, not {image_mode}: {path}"
                )
            if not all(1 <= edge <= MAX_AUTHORED_SPRITE_EDGE for edge in image_size):
                raise ModBuildError(
                    f"Authored sprite edge outside 1..{MAX_AUTHORED_SPRITE_EDGE}: "
                    f"{image_size} in {path}"
                )
            target = proposal["target"]
            target_width = _integer_dimension(target["width"], "target width")
            target_height = _integer_dimension(target["height"], "target height")
            if image_size != (target_width, target_height):
                foot_x, foot_y = authored_sprite_foot_point(
                    image_size[0], image_size[1], target
                )
                slot_x, slot_y = authored_sprite_foot_point(
                    target_width, target_height, target
                )
                raise ModBuildError(
                    f"Authored sprite {name} is {image_size[0]}x{image_size[1]}, "
                    f"its Crusader slot is {target_width}x{target_height}. The "
                    "loader would keep the slot's relative anchor, so the frame "
                    f"would sit at ({foot_x:.2f}, {foot_y:.2f}) px instead of "
                    f"({slot_x:.2f}, {slot_y:.2f}) px."
                )
            foot_x, foot_y = authored_sprite_foot_point(
                image_size[0], image_size[1], target
            )
            record = {
                "name": name,
                "is_mask": is_mask,
                "data": data,
                "width": image_size[0],
                "height": image_size[1],
                "target_width": target_width,
                "target_height": target_height,
                "target_pivot_x": float(target["pivot_x"]),
                "target_pivot_y": float(target["pivot_y"]),
                "foot_px_x": foot_x,
                "foot_px_y": foot_y,
            }
            slot = by_name.setdefault(name, {})
            if ("mask" if is_mask else "main") in slot:  # pragma: no cover
                raise ModBuildError(f"Authored sprite delivered twice: {entry.name}")
            slot["mask" if is_mask else "main"] = record

        for name, slot in sorted(by_name.items()):
            main = slot.get("main")
            mask = slot.get("mask")
            if main is None:
                raise ModBuildError(
                    f"Authored sprite mask without its colour frame: {name}_m.png"
                )
            if loader.plain_shader and mask is not None:
                raise ModBuildError(
                    f"Group {group} carries no team mask, but {name}_m.png was "
                    "delivered"
                )
            if not loader.plain_shader and mask is None:
                # Without a mask the loader substitutes a transparent 4x4 one
                # (GameSpriteManagerAPI.cs:26,74) and the frame loses its player
                # colour. Enforced here and not only in the tool, so that a file
                # copied into the store by hand cannot slip past it.
                raise ModBuildError(
                    f"Group {group} requires a team mask, but {name}_m.png is "
                    "missing"
                )
            if mask is not None and (mask["width"], mask["height"]) != (
                main["width"],
                main["height"],
            ):
                raise ModBuildError(
                    f"Authored mask geometry differs from its colour frame: {name}"
                )
            rows.append(
                {
                    "name": name,
                    "width": main["width"],
                    "height": main["height"],
                    "foot_px_x": main["foot_px_x"],
                    "foot_px_y": main["foot_px_y"],
                    "main_sha256": hashlib.sha256(main["data"]).hexdigest(),
                    "mask_sha256": (
                        "-" if mask is None else hashlib.sha256(mask["data"]).hexdigest()
                    ),
                }
            )
            for record, category in (
                (main, AUTHORED_SPRITE_CATEGORY),
                (mask, AUTHORED_SPRITE_MASK_CATEGORY),
            ):
                if record is None:
                    continue
                filename = _safe_sprite_filename(
                    name + "_m" if record["is_mask"] else name
                )
                prepared.append(
                    _PreparedAuthoredSprite(
                        source_dir=source_dir,
                        group=group,
                        origin=allowed_origin,
                        name=name,
                        output=_AUTHORED_SPRITE_OUTPUT_PREFIX + filename,
                        category=category,
                        data=record["data"],
                        width=record["width"],
                        height=record["height"],
                        is_mask=record["is_mask"],
                        target_width=record["target_width"],
                        target_height=record["target_height"],
                        target_pivot_x=record["target_pivot_x"],
                        target_pivot_y=record["target_pivot_y"],
                        foot_px_x=record["foot_px_x"],
                        foot_px_y=record["foot_px_y"],
                    )
                )

        frame_count = selection["frame_count"]
        mask_count = selection["mask_count"]
        for label, value in (("frame_count", frame_count), ("mask_count", mask_count)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ModBuildError(
                    f"Authored sprite {label} must be a non-negative integer: "
                    f"{value!r}"
                )
        actual_masks = sum(1 for slot in by_name.values() if "mask" in slot)
        if len(rows) != frame_count or actual_masks != mask_count:
            raise ModBuildError(
                f"Authored sprite store {source_dir} delivers {len(rows)} frames "
                f"and {actual_masks} masks, the profile pins {frame_count} and "
                f"{mask_count}"
            )
        if not rows:
            raise ModBuildError(f"Authored sprite store is empty: {source_dir}")
        names_digest = authored_sprite_names_digest(row["name"] for row in rows)
        if names_digest != selection["expected_names_sha256"]:
            raise ModBuildError(
                f"Authored sprite names changed for {source_dir}: "
                f"actual={names_digest} expected={selection['expected_names_sha256']}"
            )
        payload_digest = authored_sprite_payload_digest(rows)
        if payload_digest != selection["expected_payload_sha256"]:
            raise ModBuildError(
                f"Authored sprite payload changed for {source_dir}: "
                f"actual={payload_digest} "
                f"expected={selection['expected_payload_sha256']}"
            )

    return tuple(sorted(prepared, key=lambda item: item.output))


def _copy_authored_sprites(
    mod_root: Path,
    prepared: tuple[_PreparedAuthoredSprite, ...],
) -> list[OutputRecord]:
    records: list[OutputRecord] = []
    for item in prepared:
        target = _safe_output(mod_root, item.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with target.open("xb") as stream:
                stream.write(item.data)
        except FileExistsError as exc:
            raise ModBuildError(
                f"Authored sprite output collides with another output: {item.output}"
            ) from exc
        records.append(
            _record(
                mod_root,
                target,
                item.category,
                f"authored-sprite:{item.source_dir}",
                lost_alpha=0,
                metadata={
                    # These numbers are the reason the decision stays traceable:
                    # they record where the loader will seat this frame.
                    "kind": AUTHORED_SPRITE_KIND,
                    "set": item.source_dir,
                    "group": item.group,
                    "origin": item.origin,
                    "frame": item.name,
                    "mask": item.is_mask,
                    "target_width": item.target_width,
                    "target_height": item.target_height,
                    "target_pivot_x": item.target_pivot_x,
                    "target_pivot_y": item.target_pivot_y,
                    "foot_px_x": item.foot_px_x,
                    "foot_px_y": item.foot_px_y,
                },
                width=item.width,
                height=item.height,
            )
        )
    return records


def _prepare_project_files(
    config: BuilderConfig,
    profile: dict[str, Any],
) -> tuple[_PreparedProjectFile, ...]:
    selections = profile.get("project_files", [])
    if not isinstance(selections, list):
        raise ModBuildError("Profile key 'project_files' must be a list")
    if not selections:
        return ()
    runtime = profile.get("runtime")
    if (
        isinstance(runtime, dict)
        and runtime.get("unit_roster_names") is True
    ):
        raise ModBuildError(
            "Roster locale overlays and the transactional roster runtime "
            "cannot coexist in one build"
        )
    if len(selections) != len(_PROJECT_LOCALE_FILES):
        raise ModBuildError(
            "Roster project files must contain the exact de-DE/en-US pair"
        )

    selected: dict[str, tuple[str, str, bytes]] = {}
    output_names: set[str] = set()
    output_casefolds: set[str] = set()
    for index, selection in enumerate(selections):
        if not isinstance(selection, dict) or set(selection) != _PROJECT_FILE_KEYS:
            raise ModBuildError(
                f"Project file {index} must contain exactly "
                f"{sorted(_PROJECT_FILE_KEYS)}"
            )
        source = selection["source"]
        output = selection["output"]
        _canonical_portable_relative_path(source, "project source")
        _canonical_portable_relative_path(output, "project output")
        if source not in _PROJECT_LOCALE_FILES:
            raise ModBuildError(f"Project file source is not allowlisted: {source!r}")
        expected_output, locale = _PROJECT_LOCALE_FILES[source]
        if output != expected_output:
            raise ModBuildError(
                f"Project file output does not match its source: {source!r}"
            )
        if selection["category"] != "locale_override":
            raise ModBuildError("Project file category must be 'locale_override'")
        digest_pin = selection["expected_sha256"]
        if (
            not isinstance(digest_pin, str)
            or len(digest_pin) != 64
            or any(character not in "0123456789abcdef" for character in digest_pin)
        ):
            raise ModBuildError(
                f"Project file expected_sha256 must be lowercase SHA-256: {source}"
            )
        if source in selected:
            raise ModBuildError(f"Project file source is selected twice: {source}")
        if output in output_names or output.casefold() in output_casefolds:
            raise ModBuildError(f"Project file output collides on Windows: {output}")
        path = _project_source_path(config, source)
        data = _read_stable_project_file(path)
        actual_digest = hashlib.sha256(data).hexdigest()
        if actual_digest != digest_pin:
            raise ModBuildError(
                "Project file digest differs from its profile pin: "
                f"{source}: expected={digest_pin} actual={actual_digest}"
            )
        selected[source] = (output, locale, data)
        output_names.add(output)
        output_casefolds.add(output.casefold())

    if set(selected) != set(_PROJECT_LOCALE_FILES):
        raise ModBuildError(
            "Roster project files must contain the exact de-DE/en-US pair"
        )
    try:
        overlays: dict[str, LocaleOverlay] = {}
        for _source, (_output, locale, data) in selected.items():
            overlays[locale] = parse_locale_overlay(data, locale)
        roster_digest = roster_text_sha256(overlays["de-DE"], overlays["en-US"])
    except LocaleOverlayError as exc:
        raise ModBuildError(f"Project locale contract is invalid: {exc}") from exc

    prepared = [
        _PreparedProjectFile(
            source=source,
            output=output,
            category="locale_override",
            data=data,
            metadata=locale_manifest_metadata(overlays[locale], roster_digest),
        )
        for source, (output, locale, data) in selected.items()
    ]
    return tuple(sorted(prepared, key=lambda item: item.output))


def _copy_project_files(
    mod_root: Path,
    prepared: tuple[_PreparedProjectFile, ...],
) -> list[OutputRecord]:
    records: list[OutputRecord] = []
    for item in prepared:
        target = _safe_output(mod_root, item.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with target.open("xb") as stream:
                stream.write(item.data)
        except FileExistsError as exc:
            raise ModBuildError(
                f"Project file output collides with another output: {item.output}"
            ) from exc
        records.append(
            _record(
                mod_root,
                target,
                item.category,
                f"project-file:{item.source}",
                metadata=item.metadata,
            )
        )
    return records


def _prepare_authored_ui_atlases(
    config: BuilderConfig, profile: dict[str, Any]
) -> tuple[_PreparedAuthoredUiAtlas, ...]:
    selections = profile.get("authored_ui_atlases", [])
    if not isinstance(selections, list):
        raise ModBuildError("Profile key 'authored_ui_atlases' must be a list")
    prepared: list[_PreparedAuthoredUiAtlas] = []
    outputs: set[str] = set()
    sources: set[str] = set()
    for index, selection in enumerate(selections):
        if not isinstance(selection, dict) or set(selection) != _AUTHORED_UI_KEYS:
            raise ModBuildError(
                f"Authored UI atlas {index} must contain exactly "
                f"{sorted(_AUTHORED_UI_KEYS)}"
            )
        source = str(selection["source"])
        output = str(selection["output"])
        origin = str(selection["origin"])
        _canonical_portable_relative_path(source, "authored UI source")
        _canonical_portable_relative_path(output, "authored UI output")
        root = _AUTHORED_UI_ORIGIN_ROOTS.get(origin)
        if root is None or not source.startswith(root):
            raise ModBuildError(
                f"Authored UI origin/path disagree: origin={origin!r} source={source!r}"
            )
        if selection["category"] != "authored_ui_atlas":
            raise ModBuildError("Authored UI category must be 'authored_ui_atlas'")
        filename = PurePosixPath(output).name
        expected_dimensions = _AUTHORED_UI_OUTPUTS.get(filename)
        expected_output = _AUTHORED_UI_OUTPUT_PREFIX + filename
        if expected_dimensions is None or output != expected_output:
            raise ModBuildError(f"Authored UI output is not allowlisted: {output!r}")
        width = _integer_dimension(selection["width"], f"{source} width")
        height = _integer_dimension(selection["height"], f"{source} height")
        if (width, height) != expected_dimensions:
            raise ModBuildError(
                f"Authored UI dimensions differ for {filename}: "
                f"{width}x{height} != {expected_dimensions[0]}x{expected_dimensions[1]}"
            )
        digest = selection["expected_sha256"]
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ModBuildError(f"Authored UI digest is invalid: {source}")
        if source in sources or output.casefold() in outputs:
            raise ModBuildError("Authored UI source/output is selected twice")
        path = _project_source_path(config, source)
        # Frueher stand hier _read_stable_project_file, also der Leser mit der
        # 64-KiB-Locale-Schranke. Damit brach jeder Bau mit einem UI-Blatt schon
        # beim Lesen ab ("Project file exceeds 65536 bytes"), und die Zeile
        # darunter war unerreichbar - MAX_AUTHORED_UI_BYTES wurde nie geprueft.
        data = _read_stable_authored_ui(path)
        if len(data) > MAX_AUTHORED_UI_BYTES:
            raise ModBuildError(f"Authored UI atlas exceeds byte limit: {source}")
        if hashlib.sha256(data).hexdigest() != digest:
            raise ModBuildError(f"Authored UI digest differs from profile pin: {source}")
        try:
            with Image.open(io.BytesIO(data)) as opened:
                opened.load()
                actual_size = opened.size
                opened.convert("RGBA")
        except Exception as exc:
            raise ModBuildError(f"Authored UI atlas is not a readable PNG: {source}") from exc
        if actual_size != (width, height):
            raise ModBuildError(
                f"Authored UI PNG dimensions differ for {source}: {actual_size}"
            )
        sources.add(source)
        outputs.add(output.casefold())
        prepared.append(
            _PreparedAuthoredUiAtlas(source, output, origin, data, width, height)
        )
    return tuple(sorted(prepared, key=lambda item: item.output))


def _copy_authored_ui_atlases(
    mod_root: Path, prepared: tuple[_PreparedAuthoredUiAtlas, ...]
) -> list[OutputRecord]:
    records: list[OutputRecord] = []
    for item in prepared:
        target = _safe_output(mod_root, item.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with target.open("xb") as stream:
                stream.write(item.data)
        except FileExistsError as exc:
            raise ModBuildError(
                f"Authored UI output collides with another output: {item.output}"
            ) from exc
        records.append(
            _record(
                mod_root,
                target,
                "authored_ui_atlas",
                f"authored-ui:{item.source}",
                metadata={"kind": "authored_ui_atlas_v1", "origin": item.origin},
                width=item.width,
                height=item.height,
            )
        )
    return records


def _prepare_authored_backgrounds(
    config: BuilderConfig, profile: dict[str, Any]
) -> tuple[_PreparedAuthoredBackground, ...]:
    selections = profile.get("authored_backgrounds", [])
    if not isinstance(selections, list):
        raise ModBuildError("Profile key 'authored_backgrounds' must be a list")
    prepared: list[_PreparedAuthoredBackground] = []
    sources: set[str] = set()
    outputs: set[str] = set()
    for index, selection in enumerate(selections):
        if (
            not isinstance(selection, dict)
            or set(selection) != _AUTHORED_BACKGROUND_KEYS
        ):
            raise ModBuildError(
                f"Authored background {index} must contain exactly "
                f"{sorted(_AUTHORED_BACKGROUND_KEYS)}"
            )
        source = selection["source"]
        output = selection["output"]
        source_path = _canonical_portable_relative_path(
            source, "authored background source"
        )
        _canonical_portable_relative_path(output, "authored background output")
        if (
            source_path.parent.as_posix() != _AUTHORED_BACKGROUND_SOURCE_ROOT
            or source_path.suffix != ".png"
        ):
            raise ModBuildError(
                f"Authored background source is not allowlisted: {source!r}"
            )
        expected_output = _AUTHORED_BACKGROUND_OUTPUT_PREFIX + source_path.name
        if output != expected_output:
            raise ModBuildError(
                f"Authored background output does not match its source: {source!r}"
            )
        if selection["category"] != "authored_background":
            raise ModBuildError(
                "Authored background category must be 'authored_background'"
            )
        width = selection["width"]
        height = selection["height"]
        if type(width) is not int or width <= 0:
            raise ModBuildError(f"Authored background width is invalid: {source}")
        if type(height) is not int or height <= 0:
            raise ModBuildError(f"Authored background height is invalid: {source}")
        if width * height > MAX_AUTHORED_BACKGROUND_PIXELS:
            raise ModBuildError(
                f"Authored background dimensions exceed pixel limit: "
                f"{source}: {width}x{height}"
            )
        digest = selection["expected_sha256"]
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ModBuildError(f"Authored background digest is invalid: {source}")
        source_key = source.casefold()
        output_key = output.casefold()
        if source_key in sources or output_key in outputs:
            raise ModBuildError("Authored background source/output is selected twice")

        path = _project_source_path(
            config,
            source,
            allowed_root=_AUTHORED_BACKGROUND_SOURCE_ROOT,
        )
        data = _read_stable_authored_background(path)
        actual_digest = hashlib.sha256(data).hexdigest()
        if actual_digest != digest:
            raise ModBuildError(
                "Authored background digest differs from profile pin: "
                f"{source}: expected={digest} actual={actual_digest}"
            )
        try:
            with Image.open(io.BytesIO(data)) as opened:
                actual_format = opened.format
                actual_mode = opened.mode
                actual_size = opened.size
                if (
                    actual_format == "PNG"
                    and actual_mode == "RGBA"
                    and actual_size == (width, height)
                ):
                    opened.load()
        except Exception as exc:
            raise ModBuildError(
                f"Authored background is not a readable PNG: {source}"
            ) from exc
        if actual_format != "PNG":
            raise ModBuildError(f"Authored background must be PNG: {source}")
        if actual_mode != "RGBA":
            raise ModBuildError(
                f"Authored background must be RGBA, not {actual_mode}: {source}"
            )
        if actual_size != (width, height):
            raise ModBuildError(
                f"Authored background PNG dimensions differ for {source}: "
                f"actual={actual_size} expected={(width, height)}"
            )

        sources.add(source_key)
        outputs.add(output_key)
        prepared.append(
            _PreparedAuthoredBackground(source, output, data, width, height)
        )
    return tuple(sorted(prepared, key=lambda item: item.output))


def _copy_authored_backgrounds(
    mod_root: Path, prepared: tuple[_PreparedAuthoredBackground, ...]
) -> list[OutputRecord]:
    records: list[OutputRecord] = []
    for item in prepared:
        target = _safe_output(mod_root, item.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with target.open("xb") as stream:
                stream.write(item.data)
        except FileExistsError as exc:
            raise ModBuildError(
                f"Authored background output collides with another output: {item.output}"
            ) from exc
        records.append(
            _record(
                mod_root,
                target,
                "authored_background",
                f"authored-background:{item.source}",
                metadata={"kind": "authored_background_v1", "format": "png"},
                width=item.width,
                height=item.height,
            )
        )
    return records


def _prepare_authored_menu_videos(
    config: BuilderConfig, profile: dict[str, Any]
) -> tuple[_PreparedAuthoredMenuVideo, ...]:
    selections = profile.get("authored_menu_videos", [])
    if not isinstance(selections, list):
        raise ModBuildError("Profile key 'authored_menu_videos' must be a list")
    prepared: list[_PreparedAuthoredMenuVideo] = []
    sources: set[str] = set()
    outputs: set[str] = set()
    for index, selection in enumerate(selections):
        if (
            not isinstance(selection, dict)
            or set(selection) != _AUTHORED_MENU_VIDEO_KEYS
        ):
            raise ModBuildError(
                f"Authored menu video {index} must contain exactly "
                f"{sorted(_AUTHORED_MENU_VIDEO_KEYS)}"
            )
        source = selection["source"]
        output = selection["output"]
        source_path = _canonical_portable_relative_path(
            source, "authored menu video source"
        )
        _canonical_portable_relative_path(output, "authored menu video output")
        if (
            source_path.parent.as_posix() != _AUTHORED_MENU_VIDEO_SOURCE_ROOT
            or source_path.suffix != ".webm"
        ):
            raise ModBuildError(
                f"Authored menu video source is not allowlisted: {source!r}"
            )
        expected_output = _AUTHORED_MENU_VIDEO_OUTPUT_PREFIX + source_path.name
        if output != expected_output:
            raise ModBuildError(
                f"Authored menu video output does not match its source: {source!r}"
            )
        if selection["category"] != "menu_video":
            raise ModBuildError("Authored menu video category must be 'menu_video'")
        digest = selection["expected_sha256"]
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ModBuildError(f"Authored menu video digest is invalid: {source}")
        source_key = source.casefold()
        output_key = output.casefold()
        if source_key in sources or output_key in outputs:
            raise ModBuildError("Authored menu video source/output is selected twice")

        path = _project_source_path(
            config,
            source,
            allowed_root=_AUTHORED_MENU_VIDEO_SOURCE_ROOT,
        )
        data = _read_stable_authored_menu_video(path)
        actual_digest = hashlib.sha256(data).hexdigest()
        if actual_digest != digest:
            raise ModBuildError(
                "Authored menu video digest differs from profile pin: "
                f"{source}: expected={digest} actual={actual_digest}"
            )
        header = data[:4096]
        if not data.startswith(_WEBM_EBML_MAGIC) or _WEBM_DOCTYPE_SIGNATURE not in header:
            raise ModBuildError(
                f"Authored menu video has no WebM/EBML signature: {source}"
            )

        sources.add(source_key)
        outputs.add(output_key)
        prepared.append(_PreparedAuthoredMenuVideo(source, output, data))
    return tuple(sorted(prepared, key=lambda item: item.output))


def _copy_authored_menu_videos(
    mod_root: Path, prepared: tuple[_PreparedAuthoredMenuVideo, ...]
) -> list[OutputRecord]:
    records: list[OutputRecord] = []
    for item in prepared:
        target = _safe_output(mod_root, item.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with target.open("xb") as stream:
                stream.write(item.data)
        except FileExistsError as exc:
            raise ModBuildError(
                f"Authored menu video output collides with another output: {item.output}"
            ) from exc
        records.append(
            _record(
                mod_root,
                target,
                "menu_video",
                f"authored-menu-video:{item.source}",
                metadata={"kind": "authored_menu_video_v1", "container": "webm"},
            )
        )
    return records


def _validate_output_records_unique(records: list[OutputRecord]) -> None:
    exact: dict[str, str] = {}
    folded: dict[str, str] = {}
    for record in records:
        relative = record.relative_path
        _canonical_portable_relative_path(relative, "manifest output")
        if relative in exact:
            raise ModBuildError(f"Duplicate builder output record: {relative}")
        prior = folded.get(relative.casefold())
        if prior is not None:
            raise ModBuildError(
                "Builder outputs collide on Windows: "
                f"{prior!r} and {relative!r}"
            )
        exact[relative] = relative
        folded[relative.casefold()] = relative


def _assert_exact_child(path: Path, parent: Path, expected_name: str, label: str) -> None:
    if path.parent != parent or path.name != expected_name:
        raise ModBuildError(f"Unsafe {label} path: {path}")


def _scan_output_tree(root: Path) -> tuple[set[str], set[str]]:
    """Return exact file/directory sets without following links or junctions."""

    files: set[str] = set()
    directories: set[str] = set()
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            entries = list(os.scandir(directory))
        except OSError as exc:
            raise ModBuildError(f"Cannot inspect builder output {directory}: {exc}") from exc
        for entry in entries:
            path = Path(entry.path)
            relative = path.relative_to(root).as_posix()
            if entry.is_symlink() or _is_link_or_junction(path):
                raise ModBuildError(
                    f"Builder output contains a link or junction: {relative}"
                )
            if entry.is_file(follow_symlinks=False):
                files.add(relative)
            elif entry.is_dir(follow_symlinks=False):
                directories.add(relative)
                pending.append(path)
            else:
                raise ModBuildError(f"Builder output contains an unsupported entry: {relative}")
    return files, directories


def _validate_manifest_owned_output(root: Path, profile_id: str) -> str:
    """Fail closed unless ``root`` is exactly the output declared by its manifest.

    The returned digest binds the ownership check to the manifest bytes.  Extra
    files, empty directories, links, changed payloads, and cross-profile
    manifests all prevent replacement, so a recursive cleanup never consumes
    user additions merely because a manifest happens to be present.
    """

    if not root.is_dir() or _is_link_or_junction(root):
        raise ModBuildError(f"Builder output is not a safe directory: {root}")
    manifest_path = root / "build-manifest.json"
    if not manifest_path.is_file() or _is_link_or_junction(manifest_path):
        raise ModBuildError(
            f"Refusing to replace output without builder manifest: {root}"
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ModBuildError(f"Builder manifest is unreadable: {manifest_path}: {exc}") from exc
    if manifest.get("schema_version") != 1:
        raise ModBuildError(
            f"Builder manifest has unsupported schema: {manifest.get('schema_version')}"
        )
    if manifest.get("profile_id") != profile_id:
        raise ModBuildError(
            "Builder manifest profile does not own this output: "
            f"expected={profile_id!r} actual={manifest.get('profile_id')!r}"
        )
    outputs = manifest.get("outputs")
    if not isinstance(outputs, list):
        raise ModBuildError("Builder manifest outputs is not a list")

    expected_files = {"build-manifest.json"}
    expected_casefolds = {"build-manifest.json".casefold()}
    expected_directories: set[str] = set()
    for index, record in enumerate(outputs):
        if not isinstance(record, dict) or not isinstance(record.get("relative_path"), str):
            raise ModBuildError(f"Builder manifest output {index} has no relative path")
        relative = record["relative_path"]
        if relative == "build-manifest.json" or relative in expected_files:
            raise ModBuildError(f"Builder manifest has duplicate/reserved output: {relative}")
        if relative.casefold() in expected_casefolds:
            raise ModBuildError(
                f"Builder manifest output collides on Windows: {relative}"
            )
        path = _safe_output(root, relative)
        if not path.is_file() or _is_link_or_junction(path):
            raise ModBuildError(f"Manifest-owned output is missing or unsafe: {relative}")
        try:
            expected_size = int(record["size"])
            expected_digest = str(record["sha256"]).lower()
        except (KeyError, TypeError, ValueError) as exc:
            raise ModBuildError(f"Manifest-owned output metadata is invalid: {relative}") from exc
        if expected_size < 0 or len(expected_digest) != 64 or any(
            character not in "0123456789abcdef" for character in expected_digest
        ):
            raise ModBuildError(f"Manifest-owned output metadata is invalid: {relative}")
        if path.stat().st_size != expected_size or sha256_file(path) != expected_digest:
            raise ModBuildError(f"Manifest-owned output changed since build: {relative}")
        expected_files.add(relative)
        expected_casefolds.add(relative.casefold())
        parent = PurePosixPath(relative).parent
        while parent.parts:
            expected_directories.add(parent.as_posix())
            parent = parent.parent

    actual_files, actual_directories = _scan_output_tree(root)
    if actual_files != expected_files:
        raise ModBuildError(
            "Builder output file set differs from its manifest: "
            f"missing={sorted(expected_files - actual_files)} "
            f"extra={sorted(actual_files - expected_files)}"
        )
    if actual_directories != expected_directories:
        raise ModBuildError(
            "Builder output directory set differs from its manifest: "
            f"missing={sorted(expected_directories - actual_directories)} "
            f"extra={sorted(actual_directories - expected_directories)}"
        )
    return sha256_file(manifest_path)


def _rename_directory(source: Path, destination: Path) -> None:
    """Small seam for testing Windows rename failure and rollback behavior."""

    source.rename(destination)


class _BuildOutputTransaction:
    """Per-profile staging and promotion transaction.

    A stable, atomically-created lock directory serializes cooperating builder
    processes.  Staging and backup names are unique to this run, while every
    reserved artifact from any earlier run causes a fail-closed refusal.
    """

    def __init__(self, config: BuilderConfig, profile_id: str, replace: bool) -> None:
        self.config = config
        self.profile_id = _safe_directory_component(profile_id, "profile id")
        self.mod_folder_name = _safe_directory_component(
            config.output.mod_folder_name, "mod folder"
        )
        self.replace = replace
        self.project_root = config.project_root.resolve()
        self.dist = config.output.dist_dir.resolve()
        if self.project_root not in self.dist.parents:
            raise ModBuildError(
                f"Dist output is not below the project root: {self.dist}"
            )
        for data_dir in (
            config.source.data_dir.resolve(),
            config.target.data_dir.resolve(),
        ):
            if self.dist == data_dir or data_dir in self.dist.parents:
                raise ModBuildError(
                    f"Dist output is inside a read-only game data tree: {self.dist}"
                )
        configured_dist = config.output.dist_dir
        if _path_lexists(configured_dist) and _is_link_or_junction(configured_dist):
            raise ModBuildError(
                f"Configured dist output is a link or junction: {configured_dist}"
            )

        self.profile_dir = self.dist / self.profile_id
        self.final_root = self.profile_dir / self.mod_folder_name
        if self.profile_dir.parent != self.dist or self.final_root.parent != self.profile_dir:
            raise ModBuildError(f"Dist output escaped configured root: {self.final_root}")

        token = uuid4().hex
        self.lock_name = f".{self.mod_folder_name}.build-lock"
        self.staging_prefix = f".{self.mod_folder_name}.build-staging"
        self.backup_prefix = f".{self.mod_folder_name}.build-backup"
        self.lock_root = self.profile_dir / self.lock_name
        self.staging_name = f"{self.staging_prefix}-{token}"
        self.backup_name = f"{self.backup_prefix}-{token}"
        self.staging_root = self.profile_dir / self.staging_name
        self.backup_root = self.profile_dir / self.backup_name
        self._dist_dir_created = False
        self._profile_dir_created = False
        self._lock_acquired = False
        self._staging_created = False
        self._expected_existing = False
        self._prior_manifest_sha256: str | None = None
        self._committed = False

    # Eine verwaiste Sperre darf erst nach dieser Frist eingezogen werden. Sie
    # ist keine Feinheit: Prozesskennungen werden vom Betriebssystem wieder
    # vergeben, und eine Sperre, die vor Sekunden entstand, gehoert mit hoher
    # Wahrscheinlichkeit einem lebenden Bau, dessen Kennung nur noch nicht
    # sichtbar ist. Ein Bau dauert hier rund achtzehn Minuten; eine Minute
    # Wartefrist kostet also nichts und schliesst das Fenster.
    _STALE_LOCK_MIN_AGE_SECONDS = 60.0
    _LOCK_OWNER_NAME = "owner.json"
    _LOCK_OWNER_SCHEMA = "stronghold-europe-de.build-lock-owner.v1"

    def _write_lock_owner(self) -> None:
        """Die Sperre kennzeichnen, damit Verwaistheit entscheidbar wird.

        Bis zum 16.08.2026 war die Sperre ein leeres Verzeichnis. Wer sie
        vorfand, konnte nicht wissen, ob gerade ein Bau laeuft oder ob vor
        Stunden einer abgebrochen ist - und musste sie von Hand ansehen. Genau
        das ist an einem Tag dreimal passiert.
        """

        payload = {
            "schema": self._LOCK_OWNER_SCHEMA,
            "pid": os.getpid(),
            "created_epoch": time.time(),
            "staging_name": self.staging_name,
            "backup_name": self.backup_name,
            "profile_id": self.profile_id,
            "mod_folder_name": self.mod_folder_name,
        }
        try:
            (self.lock_root / self._LOCK_OWNER_NAME).write_text(
                json.dumps(payload, indent=2) + "\n", encoding="utf-8"
            )
        except OSError:
            # Kein Grund, den Bau anzuhalten: Ohne Kennzeichen faellt die
            # Sperre spaeter eben wieder in die Handpruefung zurueck.
            pass

    @staticmethod
    def _process_is_alive(pid: int) -> bool | None:
        """True, False, oder None wenn es sich nicht feststellen laesst."""

        if pid <= 0:
            return False
        if os.name == "nt":
            try:
                import ctypes

                kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
                # SYNCHRONIZE genuegt und verlangt die geringsten Rechte.
                handle = kernel32.OpenProcess(0x00100000, False, pid)
                if handle:
                    kernel32.CloseHandle(handle)
                    return True
                error = ctypes.get_last_error()
                if error == 87:
                    # ERROR_INVALID_PARAMETER - diese Kennung gibt es nicht.
                    return False
                if error == 5:
                    # ERROR_ACCESS_DENIED - es gibt ihn, er gehoert uns nur nicht.
                    return True
                return None
            except Exception:
                return None
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return None
        return True

    def _reclaim_stale_lock(self) -> str | None:
        """Eine nachweislich verwaiste Sperre einziehen; sonst None.

        Fail-closed in jedem Zweifelsfall: fehlendes oder unlesbares
        Kennzeichen, noch lebender Prozess, unbestimmbare Lebendigkeit oder zu
        junge Sperre fuehren zu None - dann bleibt es bei der Handpruefung.
        Eingezogen wird nur, was beweisbar tot ist.
        """

        try:
            _assert_exact_child(
                self.lock_root,
                self.profile_dir,
                self.lock_name,
                "build lock",
            )
        except ModBuildError:
            return None
        if (
            not _path_lexists(self.lock_root)
            or not self.lock_root.is_dir()
            or _is_link_or_junction(self.lock_root)
        ):
            return None
        owner_path = self.lock_root / self._LOCK_OWNER_NAME
        try:
            entries = list(os.scandir(self.lock_root))
        except OSError:
            return None
        if (
            len(entries) != 1
            or entries[0].name != self._LOCK_OWNER_NAME
            or entries[0].is_symlink()
            or not entries[0].is_file(follow_symlinks=False)
            or _is_link_or_junction(owner_path)
        ):
            return None
        try:
            owner = json.loads(owner_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(owner, dict) or set(owner) != {
            "schema",
            "pid",
            "created_epoch",
            "staging_name",
            "backup_name",
            "profile_id",
            "mod_folder_name",
        }:
            return None
        pid = owner.get("pid")
        created = owner.get("created_epoch")
        if (
            owner.get("schema") != self._LOCK_OWNER_SCHEMA
            or owner.get("profile_id") != self.profile_id
            or owner.get("mod_folder_name") != self.mod_folder_name
            or not isinstance(pid, int)
            or isinstance(pid, bool)
            or not isinstance(created, (int, float))
            or isinstance(created, bool)
        ):
            return None
        age = time.time() - float(created)
        if age < self._STALE_LOCK_MIN_AGE_SECONDS:
            return None
        alive = self._process_is_alive(pid)
        if alive is not False:
            return None

        # Der Bauer dieses Prozesses ist tot. Sein Staging und sein Backup sind
        # damit ebenfalls Muell - aber nur SEINE: entfernt wird ausschliesslich,
        # was im Kennzeichen steht, nie ein fremder Ordner.
        candidate_specs = (
            (owner.get("staging_name"), self.staging_prefix, "stale staging"),
            (owner.get("backup_name"), self.backup_prefix, "stale backup"),
        )
        candidates: list[tuple[str, Path]] = []
        for name, prefix, label in candidate_specs:
            if (
                not isinstance(name, str)
                or re.fullmatch(re.escape(prefix) + r"-[0-9a-f]{32}", name)
                is None
            ):
                return None
            candidate = self.profile_dir / name
            try:
                _assert_exact_child(candidate, self.profile_dir, name, label)
            except ModBuildError:
                return None
            if _path_lexists(candidate):
                if not candidate.is_dir() or _is_link_or_junction(candidate):
                    return None
                try:
                    if candidate.resolve().parent != self.profile_dir.resolve():
                        return None
                    _scan_output_tree(candidate)
                except (ModBuildError, OSError, RuntimeError):
                    return None
            candidates.append((name, candidate))

        removed = []
        for name, candidate in candidates:
            if _path_lexists(candidate):
                if not candidate.is_dir() or _is_link_or_junction(candidate):
                    return None
                try:
                    shutil.rmtree(candidate)
                    removed.append(name)
                except OSError:
                    return None
        if _is_link_or_junction(self.lock_root):
            return None
        try:
            final_entries = list(os.scandir(self.lock_root))
        except OSError:
            return None
        if (
            len(final_entries) != 1
            or final_entries[0].name != self._LOCK_OWNER_NAME
            or final_entries[0].is_symlink()
            or not final_entries[0].is_file(follow_symlinks=False)
            or _is_link_or_junction(owner_path)
        ):
            return None
        try:
            shutil.rmtree(self.lock_root)
        except OSError:
            return None
        note = (
            f"Verwaiste Bausperre eingezogen: Prozess {pid} lebt nicht mehr, "
            f"Sperre {age / 60.0:.0f} Minuten alt"
        )
        if removed:
            note += "; mitentfernt: " + ", ".join(removed)
        print(note, file=sys.stderr)
        return note

    def begin(self) -> _BuildOutputTransaction:
        try:
            dist_existed = _path_lexists(self.dist)
            try:
                self.dist.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise ModBuildError(
                    f"Cannot prepare configured dist output {self.dist}: {exc}"
                ) from exc
            self._dist_dir_created = not dist_existed
            if not self.dist.is_dir() or _is_link_or_junction(self.dist):
                raise ModBuildError(f"Dist output is not a safe directory: {self.dist}")

            profile_existed = _path_lexists(self.profile_dir)
            try:
                self.profile_dir.mkdir(exist_ok=True)
            except OSError as exc:
                raise ModBuildError(
                    f"Cannot prepare profile output {self.profile_dir}: {exc}"
                ) from exc
            self._profile_dir_created = not profile_existed
            if not self.profile_dir.is_dir() or _is_link_or_junction(self.profile_dir):
                raise ModBuildError(
                    f"Profile output is not a safe directory: {self.profile_dir}"
                )
            if self.profile_dir.resolve().parent != self.dist:
                raise ModBuildError(
                    f"Profile output escaped configured dist: {self.profile_dir}"
                )

            try:
                self.lock_root.mkdir()
            except FileExistsError as exc:
                reclaimed = self._reclaim_stale_lock()
                if reclaimed is None:
                    raise ModBuildError(
                        "A concurrent or interrupted build lock exists; review it "
                        f"manually: {self.lock_root}"
                    ) from exc
                try:
                    self.lock_root.mkdir()
                except OSError as retry_exc:
                    raise ModBuildError(
                        f"Cannot acquire build lock {self.lock_root}: {retry_exc}"
                    ) from retry_exc
            except OSError as exc:
                raise ModBuildError(
                    f"Cannot acquire build lock {self.lock_root}: {exc}"
                ) from exc
            self._lock_acquired = True
            self._write_lock_owner()

            reserved = [
                entry
                for entry in self.profile_dir.iterdir()
                if entry.name.casefold().startswith(self.staging_prefix.casefold())
                or entry.name.casefold().startswith(self.backup_prefix.casefold())
            ]
            if reserved:
                raise ModBuildError(
                    "Stale builder staging/backup state requires manual review: "
                    + ", ".join(
                        str(path)
                        for path in sorted(
                            reserved, key=lambda item: item.name.casefold()
                        )
                    )
                )

            if _path_lexists(self.final_root):
                if not self.replace:
                    raise ModBuildError(
                        "Output already exists; pass --replace after review: "
                        f"{self.final_root}"
                    )
                self._prior_manifest_sha256 = _validate_manifest_owned_output(
                    self.final_root, self.profile_id
                )
                self._expected_existing = True

            self.staging_root.mkdir()
            self._staging_created = True
            return self
        except BaseException:
            self.close()
            raise

    def _remove_staging_created_by_run(self) -> None:
        if not self._staging_created or not _path_lexists(self.staging_root):
            return
        _assert_exact_child(
            self.staging_root,
            self.profile_dir,
            self.staging_name,
            "staging cleanup",
        )
        if _is_link_or_junction(self.staging_root):
            raise ModBuildError(
                f"Refusing to recurse into changed staging path: {self.staging_root}"
            )
        try:
            shutil.rmtree(self.staging_root)
        except OSError as exc:
            raise ModBuildError(
                f"Could not remove this run's staging tree {self.staging_root}: {exc}"
            ) from exc
        self._staging_created = False

    def abort(self) -> None:
        if not self._committed:
            self._remove_staging_created_by_run()

    def commit(self) -> Path:
        if not self._staging_created or self._committed:
            raise ModBuildError("Build output transaction is not active")
        _validate_manifest_owned_output(self.staging_root, self.profile_id)

        final_exists = _path_lexists(self.final_root)
        if final_exists != self._expected_existing:
            raise ModBuildError(
                "Final output changed while the staged build was running; refusing promotion"
            )
        if self._expected_existing:
            current_manifest = _validate_manifest_owned_output(
                self.final_root, self.profile_id
            )
            if current_manifest != self._prior_manifest_sha256:
                raise ModBuildError(
                    "Prior output manifest changed while the staged build was running"
                )
            if _path_lexists(self.backup_root):
                raise ModBuildError(f"Unexpected backup collision: {self.backup_root}")
            try:
                _rename_directory(self.final_root, self.backup_root)
            except OSError as exc:
                raise ModBuildError(
                    f"Could not move prior output into transaction backup: {exc}"
                ) from exc
            try:
                _rename_directory(self.staging_root, self.final_root)
            except OSError as promotion_error:
                try:
                    _rename_directory(self.backup_root, self.final_root)
                except OSError as rollback_error:
                    raise ModBuildError(
                        "Staged output promotion and rollback both failed; prior output "
                        f"remains at {self.backup_root}: promotion={promotion_error}; "
                        f"rollback={rollback_error}"
                    ) from rollback_error
                raise ModBuildError(
                    f"Staged output promotion failed; prior output was restored: {promotion_error}"
                ) from promotion_error
            self._staging_created = False
            _assert_exact_child(
                self.backup_root,
                self.profile_dir,
                self.backup_name,
                "backup cleanup",
            )
            if _is_link_or_junction(self.backup_root):
                raise ModBuildError(
                    f"Refusing to recurse into changed backup path: {self.backup_root}"
                )
            # The exact tree was fully ownership-validated immediately before
            # its same-volume rename.  It is now safe to remove this run's
            # uniquely named transaction backup.
            try:
                shutil.rmtree(self.backup_root)
            except OSError as exc:
                raise ModBuildError(
                    "New output was promoted, but its transaction backup could not "
                    f"be removed safely: {self.backup_root}: {exc}"
                ) from exc
        else:
            try:
                _rename_directory(self.staging_root, self.final_root)
            except OSError as exc:
                raise ModBuildError(f"Could not promote staged output: {exc}") from exc
            self._staging_created = False

        self._committed = True
        return self.final_root

    def close(self) -> None:
        lock_error: OSError | None = None
        if self._lock_acquired:
            try:
                # Das Kennzeichen zuerst - die Sperre wird bewusst mit rmdir
                # freigegeben, nicht mit rmtree: Bleibt darin etwas anderes
                # liegen als unser owner.json, soll das auffallen und nicht
                # stillschweigend mitgeloescht werden.
                owner_path = self.lock_root / self._LOCK_OWNER_NAME
                if owner_path.is_file():
                    owner_path.unlink()
                self.lock_root.rmdir()
            except OSError as exc:
                lock_error = exc
            else:
                self._lock_acquired = False
        if self._profile_dir_created and self.profile_dir.exists():
            try:
                self.profile_dir.rmdir()
            except OSError:
                pass
        if self._dist_dir_created and self.dist.exists():
            try:
                self.dist.rmdir()
            except OSError:
                pass
        if lock_error is not None:
            raise ModBuildError(
                f"Could not release build lock {self.lock_root}: {lock_error}"
            ) from lock_error


def _prepare_mod_root(
    config: BuilderConfig, profile_id: str, replace: bool
) -> _BuildOutputTransaction:
    return _BuildOutputTransaction(config, profile_id, replace).begin()


def build_mod(
    config: BuilderConfig,
    build_match: BuildMatch,
    profile_path: Path,
    mapping_path: Path,
    replace: bool = False,
    *,
    asset_stream_backend_fn: (
        Callable[..., AssetStreamBuildResult | None] | None
    ) = None,
    ui_texture_backend_fn: (
        Callable[..., UiTextureBuildResult] | None
    ) = None,
    precommit_validator_fn: Callable[[Path], None] | None = None,
) -> Path:
    stream_backend = (
        build_asset_stream_backend
        if asset_stream_backend_fn is None
        else asset_stream_backend_fn
    )
    profile = load_profile(profile_path)
    _validate_group_backend_selection(profile)
    try:
        ui_texture_selection = load_ui_texture_backend_selection(
            config.project_root,
            profile,
        )
        ui_source_manifest = (
            load_ui_texture_source_manifest(
                ui_texture_selection.source_manifest_path
            )
            if ui_texture_selection is not None
            else None
        )
        atlas_backend = parse_atlas_backend(profile)
    except (AssetStreamContractError, UiAssetBundleError) as exc:
        raise ModBuildError(f"Invalid UI texture backend contract: {exc}") from exc
    if ui_texture_selection is not None and atlas_backend is None:
        raise ModBuildError("UI texture backend requires atlas_backend resource policy")
    runtime_selection = profile.get("runtime")
    if runtime_selection is not None:
        try:
            preflight_runtime_toolchain(config, runtime_selection)
        except RuntimeBuildError as exc:
            raise ModBuildError(f"Runtime companion build failed: {exc}") from exc
    mapping = read_mapping(mapping_path)
    if mapping["source_build_id"] != build_match.source_id:
        raise ModBuildError("Mapping source build does not match verified source")
    if mapping["target_build_id"] != build_match.target_id:
        raise ModBuildError("Mapping target build does not match verified target")
    prepared_project_files = _prepare_project_files(config, profile)
    prepared_xaml_patches = _prepare_xaml_patches(config, profile)
    prepared_fortification_visuals = _prepare_fortification_visuals(config, profile)
    prepared_authored_ui = _prepare_authored_ui_atlases(config, profile)
    prepared_authored_backgrounds = _prepare_authored_backgrounds(config, profile)
    prepared_authored_menu_videos = _prepare_authored_menu_videos(config, profile)
    # Before the transaction on purpose: a bad drawing must fail while nothing
    # has been staged yet, and the mapping it needs has just been read.
    prepared_authored_sprites = _prepare_authored_sprites(config, profile, mapping)
    transaction = _prepare_mod_root(config, str(profile["id"]), replace)
    mod_root = transaction.staging_root
    try:
        info_path = mod_root / "info.json"
        info_path.write_text(
            json.dumps(profile["mod_info"], indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        records: list[OutputRecord] = [_record(mod_root, info_path, "mod_metadata")]
        records.extend(_build_gm_atlases(config, mod_root, profile, mapping))
        records.extend(
            _build_shared_gm_atlases(config, mod_root, profile, mapping)
        )
        records.extend(
            _build_review_individual_source_only(
                config, mod_root, profile, mapping
            )
        )
        records.extend(_build_sprites(config, mod_root, profile, mapping))
        records.extend(_build_texture_overrides(config, mod_root, profile))
        records.extend(_build_logo(config, mod_root, profile.get("mod_logo")))
        records.extend(_copy_file_overrides(config, mod_root, profile))
        records.extend(
            _copy_authored_backgrounds(mod_root, prepared_authored_backgrounds)
        )
        records.extend(
            _copy_authored_menu_videos(mod_root, prepared_authored_menu_videos)
        )
        records.extend(_copy_project_files(mod_root, prepared_project_files))
        records.extend(_copy_project_files(mod_root, prepared_xaml_patches))
        records.extend(
            _copy_project_files(mod_root, prepared_fortification_visuals)
        )
        records.extend(_copy_authored_ui_atlases(mod_root, prepared_authored_ui))
        records.extend(
            _copy_authored_sprites(mod_root, prepared_authored_sprites)
        )
        # All proof-producing image stages are complete.  Abort before the
        # expensive Unity/runtime work when a collected atlas proof already
        # failed; the later call remains as a final no-op guard.
        _raise_collected_proof_mismatches()
        try:
            streamed = stream_backend(
                config,
                mod_root,
                profile,
                mapping,
                [asdict(record) for record in records],
            )
        except AssetStreamBuildError as exc:
            raise ModBuildError(
                f"AssetBundle streaming backend failed closed: {exc}"
            ) from exc
        if streamed is not None:
            removed = set(streamed.removed_relative_paths)
            records = [
                record for record in records if record.relative_path not in removed
            ]
            records.extend(
                OutputRecord(**asdict(record)) for record in streamed.outputs
            )
        if ui_texture_selection is not None:
            assert ui_source_manifest is not None
            assert atlas_backend is not None
            ui_builder = (
                build_ui_texture_backend
                if ui_texture_backend_fn is None
                else ui_texture_backend_fn
            )
            unity_editor: Path | None = None
            timeout_seconds = 7200
            if ui_texture_backend_fn is None:
                try:
                    toolchain = _resolve_toolchain(config.project_root, None)
                except AssetStreamBuildError as exc:
                    raise ModBuildError(
                        f"UI AssetBundle toolchain failed closed: {exc}"
                    ) from exc
                unity_editor = toolchain.executable
                timeout_seconds = toolchain.timeout_seconds
            try:
                ui_result = ui_builder(
                    workspace_root=config.project_root,
                    mod_root=mod_root,
                    source_manifest_path=(
                        ui_texture_selection.source_manifest_path
                    ),
                    quality_policy_path=(
                        ui_texture_selection.quality_policy_path
                    ),
                    unity_editor=unity_editor,
                    max_resident_bytes=(
                        atlas_backend.resource_policy.ui_resident_bytes
                    ),
                    timeout_seconds=timeout_seconds,
                )
            except UiAssetBundleError as exc:
                raise ModBuildError(
                    f"UI AssetBundle backend failed closed: {exc}"
                ) from exc
            records = _integrate_ui_texture_build(
                mod_root,
                records,
                ui_result,
                ui_source_manifest,
                max_resident_bytes=(
                    atlas_backend.resource_policy.ui_resident_bytes
                ),
            )
        records.extend(
            _build_runtime_companion(
                config,
                build_match,
                mod_root,
                profile,
                ui_texture_selection,
            )
        )
        # Every group has now been built and measured. If proof mismatches were
        # being collected rather than raised, this is where the build fails -
        # before anything is promoted, so the staged output is discarded exactly
        # as it would have been on the first mismatch.
        _raise_collected_proof_mismatches()
        _validate_output_records_unique(records)

        manifest = {
            "schema_version": 1,
            "profile_id": transaction.profile_id,
            "profile_description": profile.get("description", ""),
            "source_build_id": build_match.source_id,
            "target_build_id": build_match.target_id,
            "mod_info": profile["mod_info"],
            "outputs": [
                asdict(record)
                for record in sorted(records, key=lambda item: item.relative_path)
            ],
        }
        manifest_path = mod_root / "build-manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        if precommit_validator_fn is not None:
            precommit_validator_fn(mod_root)
        return transaction.commit()
    except BaseException:
        transaction.abort()
        raise
    finally:
        transaction.close()

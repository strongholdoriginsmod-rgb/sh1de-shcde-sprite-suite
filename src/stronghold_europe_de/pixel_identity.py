from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from math import isclose
import os
from pathlib import Path
from typing import Any, Iterable

from PIL import Image

from .mapping import _group_name
from .unity_inventory import _import_unitypy, load_unity_asset


STATUS_KEEP_IDENTICAL = "KEEP_IDENTICAL"
STATUS_MAIN_DIFFERENT = "MAIN_DIFFERENT"
STATUS_MASK_DIFFERENT = "MASK_DIFFERENT"
STATUS_MISSING = "MISSING"
STATUSES = (
    STATUS_KEEP_IDENTICAL,
    STATUS_MAIN_DIFFERENT,
    STATUS_MASK_DIFFERENT,
    STATUS_MISSING,
)

# Run `map texture-audit` first: it proves stored-payload equality for whole
# atlases in seconds. Only an atlas it reports as PAYLOAD_DIFFERENT is worth the
# per-frame render below, so the default selection names the two smallest
# convertible world atlases rather than the body families whose stored bytes are
# already known to be identical in both Definitive Editions.
DEFAULT_PIXEL_AUDIT_TEXTURES = (
    "treeSprites",
    "anims1Sprites",
)

_METADATA_TOLERANCE = 1e-4
_HASH_CHUNK_SIZE = 4 * 1024 * 1024

# Unity packs `Sprite.m_RD.settingsRaw` as
# packed:1 | packingMode:1 | packingRotation:4 | meshType:1.
# A companion mask has no Sprite objects of its own, so its crop is projected
# from the main rect.  That projection is only sound while the atlas rect is
# axis-aligned and unrotated.
_SETTINGS_PACKED_BIT = 0b1
_SETTINGS_PACKING_ROTATION_MASK = 0b111100


class PixelIdentityError(RuntimeError):
    """Raised when an identity audit cannot prove it used stable inputs."""


@dataclass(frozen=True)
class FileState:
    size: int
    mtime_ns: int
    ctime_ns: int


@dataclass(frozen=True)
class RenderedSignature:
    width: int
    height: int
    rgba_sha256: str
    alpha_covered_pixels: int
    effective_mask_sha256: str | None
    mask_present: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "width": self.width,
            "height": self.height,
            "rgba_sha256": self.rgba_sha256,
            "alpha_covered_pixels": self.alpha_covered_pixels,
            "effective_mask_sha256": self.effective_mask_sha256,
            "mask_present": self.mask_present,
        }


def _file_state(path: Path) -> FileState:
    if not path.is_file():
        raise PixelIdentityError(f"Expected a regular input file: {path}")
    stat = path.stat()
    return FileState(
        size=int(stat.st_size),
        mtime_ns=int(stat.st_mtime_ns),
        ctime_ns=int(stat.st_ctime_ns),
    )


def _assert_file_state(path: Path, expected: FileState) -> None:
    actual = _file_state(path)
    if actual != expected:
        raise PixelIdentityError(f"Input file changed during pixel audit: {path}")


def _resolve_stream_path(asset_path: Path, stream_path: str) -> Path:
    if not stream_path:
        raise PixelIdentityError(
            f"Selected Texture2D has no external stream path in {asset_path}"
        )
    if stream_path.startswith("archive:/"):
        raise PixelIdentityError(
            f"Archive stream paths are not approved for this audit: {stream_path}"
        )
    candidate = (asset_path.parent / stream_path).resolve()
    data_dir = asset_path.parent.resolve()
    if candidate.parent != data_dir:
        raise PixelIdentityError(
            f"Texture stream escapes the canonical data directory: {stream_path}"
        )
    return candidate


def hash_stream_payload(
    stream_file: Path,
    offset: int,
    size: int,
    expected_state: FileState | None = None,
) -> str:
    """Hash exactly one Texture2D stream range and prove the file stayed stable."""

    if offset < 0 or size <= 0:
        raise PixelIdentityError(
            f"Invalid Texture2D stream range: offset={offset}, size={size}"
        )
    initial = expected_state or _file_state(stream_file)
    if offset + size > initial.size:
        raise PixelIdentityError(
            f"Texture2D stream range exceeds {stream_file}: "
            f"offset={offset}, size={size}, file_size={initial.size}"
        )

    digest = hashlib.sha256()
    remaining = size
    with stream_file.open("rb") as stream:
        stream.seek(offset)
        while remaining:
            chunk = stream.read(min(remaining, _HASH_CHUNK_SIZE))
            if not chunk:
                raise PixelIdentityError(
                    f"Short read in Texture2D stream {stream_file}: {remaining} bytes missing"
                )
            digest.update(chunk)
            remaining -= len(chunk)
    _assert_file_state(stream_file, initial)
    return digest.hexdigest()


def _integer_dimension(value: Any, label: str) -> int:
    numeric = float(value)
    rounded = round(numeric)
    if rounded <= 0 or not isclose(numeric, rounded, abs_tol=_METADATA_TOLERANCE):
        raise PixelIdentityError(f"{label} is not a positive integral dimension: {value}")
    return int(rounded)


def _sha256_rgba(image: Image.Image) -> str:
    rgba = image if image.mode == "RGBA" else image.convert("RGBA")
    return hashlib.sha256(rgba.tobytes()).hexdigest()


def assert_mask_projectable(settings_raw: int, name: str) -> None:
    """Reject a sprite whose atlas rect cannot carry a straight mask projection."""

    value = int(settings_raw)
    if value & _SETTINGS_PACKED_BIT or value & _SETTINGS_PACKING_ROTATION_MASK:
        raise PixelIdentityError(
            f"Sprite {name} is atlas-packed or rotated (settingsRaw={value}); "
            "its companion mask cannot be projected from the plain rect"
        )


def crop_mask_for_sprite(
    mask_atlas: Image.Image,
    *,
    rect_x: float,
    rect_y: float,
    logical_size: tuple[int, int],
    main_atlas_size: tuple[int, int],
) -> Image.Image:
    """Crop a companion mask using Unity's bottom-left sprite coordinates.

    Main sprites themselves are always rendered through ``Sprite.image``.  A
    companion ``*_m`` Texture2D has no Sprite objects, so its crop is projected
    from the validated main rect.  Nearest-neighbour expansion is intentional:
    SHCDE stores several masks at a lower resolution than their main atlases.
    """

    main_width, main_height = main_atlas_size
    if main_width <= 0 or main_height <= 0:
        raise PixelIdentityError(f"Invalid main atlas size: {main_atlas_size}")
    logical_width, logical_height = logical_size
    scale_x = mask_atlas.width / main_width
    scale_y = mask_atlas.height / main_height
    left = round(rect_x * scale_x)
    bottom = round(rect_y * scale_y)
    right = round((rect_x + logical_width) * scale_x)
    top_from_bottom = round((rect_y + logical_height) * scale_y)
    box = (left, mask_atlas.height - top_from_bottom, right, mask_atlas.height - bottom)
    if (
        box[0] < 0
        or box[1] < 0
        or box[2] > mask_atlas.width
        or box[3] > mask_atlas.height
        or box[0] >= box[2]
        or box[1] >= box[3]
    ):
        raise PixelIdentityError(
            f"Projected mask crop is outside the mask atlas: box={box}, "
            f"mask={mask_atlas.size}"
        )
    rgba = mask_atlas if mask_atlas.mode == "RGBA" else mask_atlas.convert("RGBA")
    crop = rgba.crop(box)
    if crop.size != logical_size:
        crop = crop.resize(logical_size, Image.Resampling.NEAREST)
    return crop


def rendered_signature(
    main_image: Image.Image,
    mask_image: Image.Image | None,
) -> RenderedSignature:
    """Return hashes only; mask pixels outside visible main alpha are ignored."""

    main = main_image if main_image.mode == "RGBA" else main_image.convert("RGBA")
    alpha = main.getchannel("A")
    histogram = alpha.histogram()
    covered_pixels = main.width * main.height - histogram[0]
    effective_mask_sha256: str | None = None
    if mask_image is not None:
        mask = mask_image if mask_image.mode == "RGBA" else mask_image.convert("RGBA")
        if mask.size != main.size:
            raise PixelIdentityError(
                f"Rendered mask size {mask.size} differs from main size {main.size}"
            )
        coverage = alpha.point(lambda value: 255 if value else 0)
        empty = Image.new("RGBA", main.size, (0, 0, 0, 0))
        effective = Image.composite(mask, empty, coverage)
        effective_mask_sha256 = _sha256_rgba(effective)
    return RenderedSignature(
        width=main.width,
        height=main.height,
        rgba_sha256=_sha256_rgba(main),
        alpha_covered_pixels=covered_pixels,
        effective_mask_sha256=effective_mask_sha256,
        mask_present=mask_image is not None,
    )


def classify_signatures(
    source: RenderedSignature | None,
    target: RenderedSignature | None,
) -> tuple[str, str]:
    if source is None or target is None:
        missing = "source" if source is None else "target"
        return STATUS_MISSING, f"{missing.upper()}_SPRITE_MISSING"
    if (
        source.width != target.width
        or source.height != target.height
        or source.rgba_sha256 != target.rgba_sha256
    ):
        return STATUS_MAIN_DIFFERENT, "RENDERED_MAIN_RGBA_DIFFERS"
    if (
        source.mask_present != target.mask_present
        or source.effective_mask_sha256 != target.effective_mask_sha256
    ):
        return STATUS_MASK_DIFFERENT, "EFFECTIVE_MASK_DIFFERS_UNDER_MAIN_ALPHA"
    return STATUS_KEEP_IDENTICAL, "RENDERED_MAIN_AND_EFFECTIVE_MASK_IDENTICAL"


def _texture_by_name(inventory: dict[str, Any], role: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for texture in inventory.get("textures", []):
        name = str(texture.get("name", ""))
        if not name or name in result:
            raise PixelIdentityError(f"Duplicate or empty {role} Texture2D name: {name!r}")
        result[name] = texture
    return result


def _sprite_by_name(inventory: dict[str, Any], role: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for sprite in inventory.get("sprites", []):
        name = str(sprite.get("name", ""))
        if not name or name in result:
            raise PixelIdentityError(f"Duplicate or empty {role} Sprite name: {name!r}")
        result[name] = sprite
    return result


def _validate_inventory(
    inventory: dict[str, Any],
    *,
    role: str,
    asset_path: Path,
) -> None:
    if inventory.get("schema_version") != 1:
        raise PixelIdentityError(f"Unsupported {role} inventory schema")
    if inventory.get("role") != role:
        raise PixelIdentityError(
            f"Inventory role mismatch: expected {role}, got {inventory.get('role')}"
        )
    recorded_path = Path(str(inventory.get("asset_path", ""))).resolve()
    if recorded_path != asset_path.resolve():
        raise PixelIdentityError(
            f"{role} inventory belongs to a different resources.assets: {recorded_path}"
        )


def _validate_mapping_builds(
    mapping: dict[str, Any], source_build_id: str, target_build_id: str
) -> None:
    if mapping.get("source_build_id") != source_build_id:
        raise PixelIdentityError(
            "Mapping/source build ID mismatch: "
            f"{mapping.get('source_build_id')} != {source_build_id}"
        )
    if mapping.get("target_build_id") != target_build_id:
        raise PixelIdentityError(
            "Mapping/target build ID mismatch: "
            f"{mapping.get('target_build_id')} != {target_build_id}"
        )


def _selected_names(
    source_sprites: dict[str, dict[str, Any]],
    target_sprites: dict[str, dict[str, Any]],
    textures: set[str],
    groups: set[str],
) -> set[str]:
    names: set[str] = set()
    for name, sprite in source_sprites.items():
        if str(sprite["texture_name"]) in textures or _group_name(name) in groups:
            names.add(name)
    for name, sprite in target_sprites.items():
        if str(sprite["texture_name"]) in textures or _group_name(name) in groups:
            names.add(name)
    if not names:
        raise PixelIdentityError("Pixel audit selection matched no sprites")
    return names


def _texture_metadata(texture: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": str(texture["name"]),
        "path_id": int(texture["path_id"]),
        "width": int(texture["width"]),
        "height": int(texture["height"]),
        "texture_format": int(texture["texture_format"]),
        "stream_path": str(texture["stream_path"]),
        "stream_offset": int(texture["stream_offset"]),
        "stream_size": int(texture["stream_size"]),
    }


def _payload_signature(
    asset_path: Path,
    texture: dict[str, Any],
    file_states: dict[Path, FileState],
) -> dict[str, Any]:
    """Describe one Texture2D payload; an inline texture stays explicitly unhashed.

    A handful of Unity textures (fonts, cursors) keep their pixels inside the
    serialized file instead of an external ``.resS`` stream.  Those are never
    conversion candidates, so the audit records them as not hashable rather
    than aborting a whole selection.  ``_same_payload`` treats a missing digest
    as "cannot prove equality", so the fail-closed contract is preserved.
    """

    metadata = _texture_metadata(texture)
    if not metadata["stream_path"]:
        return {
            **metadata,
            "stream_file": None,
            "stream_sha256": None,
            "payload_hashable": False,
            "payload_source": "inline",
        }
    stream_file = _resolve_stream_path(asset_path, metadata["stream_path"])
    state = file_states.setdefault(stream_file, _file_state(stream_file))
    return {
        **metadata,
        "stream_file": stream_file.name,
        "stream_sha256": hash_stream_payload(
            stream_file,
            metadata["stream_offset"],
            metadata["stream_size"],
            state,
        ),
        "payload_hashable": True,
        "payload_source": "stream",
    }


def _same_payload(source: dict[str, Any] | None, target: dict[str, Any] | None) -> bool:
    if source is None or target is None:
        return False
    if not (source.get("stream_sha256") and target.get("stream_sha256")):
        return False
    return all(
        source[key] == target[key]
        for key in (
            "width",
            "height",
            "texture_format",
            "stream_size",
            "stream_sha256",
        )
    )


def _validate_texture_object(actual: Any, expected: dict[str, Any], role: str) -> None:
    stream = actual.m_StreamData
    actual_metadata = {
        "name": str(actual.m_Name),
        "width": int(actual.m_Width),
        "height": int(actual.m_Height),
        "texture_format": int(actual.m_TextureFormat),
        "stream_path": str(stream.path),
        "stream_offset": int(stream.offset),
        "stream_size": int(stream.size),
    }
    for key, actual_value in actual_metadata.items():
        expected_value = _texture_metadata(expected)[key]
        if actual_value != expected_value:
            raise PixelIdentityError(
                f"{role} Texture2D metadata changed for {expected['name']}: "
                f"{key}={actual_value!r}, inventory={expected_value!r}"
            )


def _validate_sprite_object(actual: Any, expected: dict[str, Any], role: str) -> None:
    comparisons = {
        "name": (str(actual.m_Name), str(expected["name"])),
        "rect_x": (float(actual.m_Rect.x), float(expected["rect_x"])),
        "rect_y": (float(actual.m_Rect.y), float(expected["rect_y"])),
        "width": (float(actual.m_Rect.width), float(expected["width"])),
        "height": (float(actual.m_Rect.height), float(expected["height"])),
        "texture_path_id": (
            int(actual.m_RD.texture.path_id),
            int(expected["texture_path_id"]),
        ),
        "settings_raw": (int(actual.m_RD.settingsRaw), int(expected["settings_raw"])),
    }
    for key, (actual_value, expected_value) in comparisons.items():
        if isinstance(actual_value, float):
            equal = isclose(actual_value, float(expected_value), abs_tol=_METADATA_TOLERANCE)
        else:
            equal = actual_value == expected_value
        if not equal:
            raise PixelIdentityError(
                f"{role} Sprite metadata changed for {expected['name']}: "
                f"{key}={actual_value!r}, inventory={expected_value!r}"
            )


def _clear_unity_caches(environment: Any) -> None:
    for file in environment.files.values():
        cache = getattr(file, "_cache", None)
        if cache is not None:
            cache.clear()


def _render_side(
    asset_path: Path,
    inventory: dict[str, Any],
    role: str,
    selected_common_names: set[str],
) -> dict[str, RenderedSignature]:
    UnityPy = _import_unitypy()
    environment = load_unity_asset(asset_path, unitypy=UnityPy)
    objects = {int(obj.path_id): obj for obj in environment.objects}
    textures = _texture_by_name(inventory, role)
    sprites = _sprite_by_name(inventory, role)
    by_atlas: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for name in sorted(selected_common_names):
        sprite = sprites[name]
        by_atlas[str(sprite["texture_name"])].append(sprite)

    signatures: dict[str, RenderedSignature] = {}
    for atlas_name in sorted(by_atlas):
        main_record = textures.get(atlas_name)
        if main_record is None:
            raise PixelIdentityError(f"{role} main Texture2D is missing: {atlas_name}")
        main_reader = objects.get(int(main_record["path_id"]))
        if main_reader is None or main_reader.type.name != "Texture2D":
            raise PixelIdentityError(
                f"{role} Texture2D path ID changed for {atlas_name}: {main_record['path_id']}"
            )
        main_texture = main_reader.read()
        _validate_texture_object(main_texture, main_record, role)

        mask_record = textures.get(atlas_name + "_m")
        mask_image: Image.Image | None = None
        if mask_record is not None:
            mask_reader = objects.get(int(mask_record["path_id"]))
            if mask_reader is None or mask_reader.type.name != "Texture2D":
                raise PixelIdentityError(
                    f"{role} mask Texture2D path ID changed for {atlas_name}_m"
                )
            mask_texture = mask_reader.read()
            _validate_texture_object(mask_texture, mask_record, role)
            mask_image = mask_texture.image.convert("RGBA")

        for expected in by_atlas[atlas_name]:
            reader = objects.get(int(expected["path_id"]))
            if reader is None or reader.type.name != "Sprite":
                raise PixelIdentityError(
                    f"{role} Sprite path ID changed for {expected['name']}: "
                    f"{expected['path_id']}"
                )
            sprite = reader.read()
            _validate_sprite_object(sprite, expected, role)
            logical_size = (
                _integer_dimension(expected["width"], f"{role} sprite width"),
                _integer_dimension(expected["height"], f"{role} sprite height"),
            )
            # UnityPy's Sprite.image handles tight meshes, UV meshes, packing,
            # rotation and the engine's bottom-left coordinate convention.
            main_image = sprite.image.convert("RGBA")
            if main_image.size != logical_size:
                raise PixelIdentityError(
                    f"Decoded {role} Sprite dimensions changed for {expected['name']}: "
                    f"{main_image.size} != {logical_size}"
                )
            mask_crop = None
            if mask_image is not None:
                assert_mask_projectable(int(expected["settings_raw"]), str(expected["name"]))
                mask_crop = crop_mask_for_sprite(
                    mask_image,
                    rect_x=float(expected["rect_x"]),
                    rect_y=float(expected["rect_y"]),
                    logical_size=logical_size,
                    main_atlas_size=(int(main_texture.m_Width), int(main_texture.m_Height)),
                )
            signatures[str(expected["name"])] = rendered_signature(main_image, mask_crop)
            del main_image, mask_crop, sprite

        del main_texture, mask_image
        _clear_unity_caches(environment)
    return signatures


def _summary_counts(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(str(row["status"]) for row in rows)
    return {status: counts.get(status, 0) for status in STATUSES}


def _recommendation(
    status_counts: dict[str, int], *, main_payload_equal: bool | None
) -> tuple[str, str]:
    if status_counts[STATUS_MISSING]:
        return (
            "KEEP_CRUSADER",
            "Selection has source/target gaps; target coverage must remain authoritative",
        )
    if status_counts[STATUS_MAIN_DIFFERENT]:
        return (
            "REVIEW_REQUIRED",
            "Rendered main pixels differ; identity alone cannot approve an override",
        )
    if status_counts[STATUS_MASK_DIFFERENT]:
        reason = (
            "Main atlas payload is byte-identical, but effective team masks differ; "
            "keep the complete Crusader family and never replace only its mask"
            if main_payload_equal
            else "Effective team masks differ; Crusader's target mask remains authoritative"
        )
        return "KEEP_CRUSADER", reason
    return (
        "KEEP_CRUSADER",
        "Rendered output is already identical; an override would be visually redundant",
    )


def _aggregate_rows(
    rows: list[dict[str, Any]],
    key: str,
    texture_payloads: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row[key])].append(row)
    aggregates: list[dict[str, Any]] = []
    for name in sorted(grouped):
        members = grouped[name]
        counts = _summary_counts(members)
        payload_equal: bool | None = None
        if texture_payloads is not None:
            payload_equal = bool(texture_payloads.get(name, {}).get("main_payload_equal"))
        recommendation, reason = _recommendation(
            counts, main_payload_equal=payload_equal
        )
        aggregates.append(
            {
                key: name,
                "sprite_count": len(members),
                "status_counts": counts,
                "recommended_action": recommendation,
                "reason": reason,
            }
        )
    return aggregates


TEXTURE_TARGET_EXCLUSIVE = "TARGET_EXCLUSIVE"
TEXTURE_SOURCE_EXCLUSIVE = "SOURCE_EXCLUSIVE"
TEXTURE_PAYLOAD_IDENTICAL = "PAYLOAD_IDENTICAL"
TEXTURE_PAYLOAD_DIFFERENT = "PAYLOAD_DIFFERENT"
TEXTURE_NOT_HASHABLE = "NOT_HASHABLE"
TEXTURE_VERDICTS = (
    TEXTURE_PAYLOAD_DIFFERENT,
    TEXTURE_PAYLOAD_IDENTICAL,
    TEXTURE_TARGET_EXCLUSIVE,
    TEXTURE_SOURCE_EXCLUSIVE,
    TEXTURE_NOT_HASHABLE,
)

_TEXTURE_RECOMMENDATION = {
    TEXTURE_PAYLOAD_DIFFERENT: (
        "CONVERSION_CANDIDATE",
        "Stored pixels differ; a group from this atlas can carry visible Europe art",
    ),
    TEXTURE_PAYLOAD_IDENTICAL: (
        "KEEP_CRUSADER",
        "Both games ship the identical stored atlas; an override cannot change a pixel",
    ),
    TEXTURE_TARGET_EXCLUSIVE: (
        "KEEP_CRUSADER",
        "Crusader-only atlas; Stronghold 1 DE has no counterpart to convert",
    ),
    TEXTURE_SOURCE_EXCLUSIVE: (
        "SOURCE_REFERENCE_ONLY",
        "Stronghold 1 DE-only atlas; no target slot exists to override",
    ),
    TEXTURE_NOT_HASHABLE: (
        "REVIEW_REQUIRED",
        "Pixels are stored inline instead of an external stream; equality is unproven",
    ),
}


def _texture_recommendation(verdict: str, *, is_mask: bool) -> tuple[str, str]:
    """A companion mask is never promoted on its own.

    Crusader re-encodes every team-colour mask (BC7 in Stronghold 1 DE, DXT1
    here) and downscales some of them, so a `*_m` payload practically always
    differs.  That says nothing about the artwork: the mask is target-
    authoritative and is only ever regenerated together with the main atlas of
    an approved group.
    """

    if is_mask:
        return (
            "KEEP_CRUSADER",
            "Companion team-colour mask; target-authoritative and only ever "
            "regenerated together with an approved main atlas",
        )
    return _TEXTURE_RECOMMENDATION[verdict]


def _sprite_counts_by_texture(inventory: dict[str, Any]) -> Counter[str]:
    return Counter(str(sprite["texture_name"]) for sprite in inventory.get("sprites", []))


def audit_texture_payloads(
    source_asset_path: Path,
    target_asset_path: Path,
    source_inventory: dict[str, Any],
    target_inventory: dict[str, Any],
    *,
    source_build_id: str,
    target_build_id: str,
) -> dict[str, Any]:
    """Compare every stored atlas payload without decoding a single pixel.

    This is the cheap upstream gate for :func:`audit_pixel_identity`.  Firefly
    reuses whole atlases between the two Definitive Editions, so an atlas whose
    stored bytes are equal cannot produce a visible conversion no matter which
    of its groups is promoted.  Rendering thousands of frames to rediscover that
    would be wasted work, and shipping such a group would be pure risk: the
    loader still resizes GM arrays and swaps materials.
    """

    source_asset = source_asset_path.resolve()
    target_asset = target_asset_path.resolve()
    _validate_inventory(source_inventory, role="source", asset_path=source_asset)
    _validate_inventory(target_inventory, role="target", asset_path=target_asset)
    source_textures = _texture_by_name(source_inventory, "source")
    target_textures = _texture_by_name(target_inventory, "target")
    source_sprite_counts = _sprite_counts_by_texture(source_inventory)
    target_sprite_counts = _sprite_counts_by_texture(target_inventory)

    file_states: dict[Path, FileState] = {
        source_asset: _file_state(source_asset),
        target_asset: _file_state(target_asset),
    }

    rows: list[dict[str, Any]] = []
    for name in sorted(set(source_textures) | set(target_textures)):
        source_record = source_textures.get(name)
        target_record = target_textures.get(name)
        source_payload = (
            _payload_signature(source_asset, source_record, file_states)
            if source_record is not None
            else None
        )
        target_payload = (
            _payload_signature(target_asset, target_record, file_states)
            if target_record is not None
            else None
        )
        if target_payload is None:
            verdict = TEXTURE_SOURCE_EXCLUSIVE
        elif source_payload is None:
            verdict = TEXTURE_TARGET_EXCLUSIVE
        elif not (source_payload["payload_hashable"] and target_payload["payload_hashable"]):
            verdict = TEXTURE_NOT_HASHABLE
        elif _same_payload(source_payload, target_payload):
            verdict = TEXTURE_PAYLOAD_IDENTICAL
        else:
            verdict = TEXTURE_PAYLOAD_DIFFERENT
        is_mask = name.endswith("_m")
        recommendation, reason = _texture_recommendation(verdict, is_mask=is_mask)
        rows.append(
            {
                "texture": name,
                "verdict": verdict,
                "recommended_action": recommendation,
                "reason": reason,
                "is_mask_texture": is_mask,
                "geometry_equal": (
                    source_payload is not None
                    and target_payload is not None
                    and (source_payload["width"], source_payload["height"])
                    == (target_payload["width"], target_payload["height"])
                ),
                "format_equal": (
                    source_payload is not None
                    and target_payload is not None
                    and source_payload["texture_format"] == target_payload["texture_format"]
                ),
                "source_sprite_count": int(source_sprite_counts.get(name, 0)),
                "target_sprite_count": int(target_sprite_counts.get(name, 0)),
                "source": source_payload,
                "target": target_payload,
            }
        )

    for path, state in file_states.items():
        _assert_file_state(path, state)

    verdict_counts = Counter(str(row["verdict"]) for row in rows)
    convertible = [
        row
        for row in rows
        if row["verdict"] == TEXTURE_PAYLOAD_DIFFERENT and not row["is_mask_texture"]
    ]
    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_build_id": source_build_id,
        "target_build_id": target_build_id,
        "method": {
            "comparison": "SHA-256 of the exact stored m_StreamData byte range",
            "decoded": False,
            "pixel_payload_persisted": False,
        },
        "summary": {
            "texture_count": len(rows),
            "verdict_counts": {
                verdict: verdict_counts.get(verdict, 0) for verdict in TEXTURE_VERDICTS
            },
            "convertible_main_texture_count": len(convertible),
            "convertible_main_textures": [row["texture"] for row in convertible],
            "convertible_target_sprite_count": sum(
                row["target_sprite_count"] for row in convertible
            ),
        },
        "textures": rows,
    }


def write_texture_payload_report(
    audit: dict[str, Any], json_path: Path, markdown_path: Path
) -> None:
    _write_json(audit, json_path)
    lines = [
        "# Stored atlas payload audit",
        "",
        f"- Source build: `{audit['source_build_id']}`",
        f"- Target build: `{audit['target_build_id']}`",
        f"- Textures in union: {audit['summary']['texture_count']:,}",
        "- Decoded pixel payload persisted: no",
        "",
        "## Verdicts",
        "",
        "| Verdict | Textures |",
        "|---|---:|",
    ]
    for verdict in TEXTURE_VERDICTS:
        lines.append(f"| `{verdict}` | {audit['summary']['verdict_counts'][verdict]:,} |")
    lines.extend(
        [
            "",
            "## Textures",
            "",
            "| Texture | Verdict | Source sprites | Target sprites | Same size | Same format | Recommendation |",
            "|---|---|---:|---:|---|---|---|",
        ]
    )
    for row in audit["textures"]:
        lines.append(
            f"| `{row['texture']}` | `{row['verdict']}` | "
            f"{row['source_sprite_count']:,} | {row['target_sprite_count']:,} | "
            f"{'yes' if row['geometry_equal'] else 'no'} | "
            f"{'yes' if row['format_equal'] else 'no'} | `{row['recommended_action']}` |"
        )
    lines.extend(
        [
            "",
            "`PAYLOAD_IDENTICAL` is the strongest possible KEEP argument: the two",
            "installations ship the same stored bytes, so every group drawn from that",
            "atlas already looks European in Crusader. Overriding it cannot change a",
            "pixel while still resizing GM arrays and replacing materials.",
            "",
            "A differing companion `*_m` mask does not weaken that verdict. Crusader",
            "re-encodes team-colour masks; the mask is target-authoritative and must",
            "not be replaced on its own.",
            "",
        ]
    )
    _write_text("\n".join(lines), markdown_path)


def audit_pixel_identity(
    source_asset_path: Path,
    target_asset_path: Path,
    source_inventory: dict[str, Any],
    target_inventory: dict[str, Any],
    mapping: dict[str, Any],
    *,
    source_build_id: str,
    target_build_id: str,
    selected_textures: Iterable[str] = DEFAULT_PIXEL_AUDIT_TEXTURES,
    selected_groups: Iterable[str] = (),
) -> dict[str, Any]:
    """Audit rendered equality without writing any decoded game pixels."""

    source_asset = source_asset_path.resolve()
    target_asset = target_asset_path.resolve()
    _validate_inventory(source_inventory, role="source", asset_path=source_asset)
    _validate_inventory(target_inventory, role="target", asset_path=target_asset)
    _validate_mapping_builds(mapping, source_build_id, target_build_id)
    source_sprites = _sprite_by_name(source_inventory, "source")
    target_sprites = _sprite_by_name(target_inventory, "target")
    source_textures = _texture_by_name(source_inventory, "source")
    target_textures = _texture_by_name(target_inventory, "target")
    textures = {str(item) for item in selected_textures if str(item)}
    groups = {str(item) for item in selected_groups if str(item)}
    names = _selected_names(source_sprites, target_sprites, textures, groups)
    common_names = names & source_sprites.keys() & target_sprites.keys()

    source_asset_state = _file_state(source_asset)
    target_asset_state = _file_state(target_asset)
    file_states: dict[Path, FileState] = {
        source_asset: source_asset_state,
        target_asset: target_asset_state,
    }

    involved_atlases = sorted(
        {
            str(sprite["texture_name"])
            for name in names
            for sprite in (source_sprites.get(name), target_sprites.get(name))
            if sprite is not None
        }
    )
    texture_payloads: dict[str, dict[str, Any]] = {}
    for atlas_name in involved_atlases:
        source_main = (
            _payload_signature(source_asset, source_textures[atlas_name], file_states)
            if atlas_name in source_textures
            else None
        )
        target_main = (
            _payload_signature(target_asset, target_textures[atlas_name], file_states)
            if atlas_name in target_textures
            else None
        )
        source_mask_record = source_textures.get(atlas_name + "_m")
        target_mask_record = target_textures.get(atlas_name + "_m")
        source_mask = (
            _payload_signature(source_asset, source_mask_record, file_states)
            if source_mask_record is not None
            else None
        )
        target_mask = (
            _payload_signature(target_asset, target_mask_record, file_states)
            if target_mask_record is not None
            else None
        )
        texture_payloads[atlas_name] = {
            "texture": atlas_name,
            "source_main": source_main,
            "target_main": target_main,
            "main_payload_equal": _same_payload(source_main, target_main),
            "source_mask": source_mask,
            "target_mask": target_mask,
            "mask_payload_equal": _same_payload(source_mask, target_mask),
        }

    source_signatures = _render_side(
        source_asset, source_inventory, "source", set(common_names)
    )
    target_signatures = _render_side(
        target_asset, target_inventory, "target", set(common_names)
    )

    rows: list[dict[str, Any]] = []
    for name in sorted(names):
        source_sprite = source_sprites.get(name)
        target_sprite = target_sprites.get(name)
        source_signature = source_signatures.get(name)
        target_signature = target_signatures.get(name)
        status, reason = classify_signatures(source_signature, target_signature)
        reference = target_sprite or source_sprite
        assert reference is not None
        source_atlas = str(source_sprite["texture_name"]) if source_sprite else None
        target_atlas = str(target_sprite["texture_name"]) if target_sprite else None
        texture = target_atlas or source_atlas
        if source_atlas is not None and target_atlas is not None and source_atlas != target_atlas:
            status = STATUS_MAIN_DIFFERENT
            reason = "MAIN_TEXTURE_NAME_DIFFERS"
        rows.append(
            {
                "name": name,
                "group": _group_name(name),
                "texture": texture,
                "status": status,
                "reason": reason,
                "source_texture": source_atlas,
                "target_texture": target_atlas,
                "source": source_signature.to_dict() if source_signature else None,
                "target": target_signature.to_dict() if target_signature else None,
            }
        )

    for path, state in file_states.items():
        _assert_file_state(path, state)

    texture_rows = _aggregate_rows(rows, "texture", texture_payloads)
    texture_by_name = {item["texture"]: item for item in texture_rows}
    for name, payload in texture_payloads.items():
        if name in texture_by_name:
            texture_by_name[name]["payloads"] = payload
    group_rows = _aggregate_rows(rows, "group")
    summary_counts = _summary_counts(rows)
    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_build_id": source_build_id,
        "target_build_id": target_build_id,
        "selection": {
            "textures": sorted(textures),
            "groups": sorted(groups),
        },
        "method": {
            "main_renderer": "UnityPy Sprite.image (tight mesh/packing aware)",
            "main_comparison": "SHA-256 of complete rendered RGBA bytes",
            "mask_comparison": (
                "SHA-256 of RGBA companion-mask crop after nearest logical-size "
                "projection, zeroed outside rendered main alpha"
            ),
            "texture_payload_hash": "SHA-256 of exact m_StreamData byte range",
            "input_stability_verified": True,
            "pixel_payload_persisted": False,
        },
        "summary": {
            "sprite_count": len(rows),
            "common_sprite_count": len(common_names),
            "status_counts": summary_counts,
            "texture_count": len(texture_rows),
            "group_count": len(group_rows),
        },
        "textures": texture_rows,
        "groups": group_rows,
        "sprites": rows,
    }


def _write_text(content: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def _write_json(payload: dict[str, Any], path: Path) -> None:
    _write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n", path
    )


def write_pixel_identity_report(
    audit: dict[str, Any], json_path: Path, markdown_path: Path
) -> None:
    _write_json(audit, json_path)

    lines = [
        "# Rendered pixel identity audit",
        "",
        f"- Source build: `{audit['source_build_id']}`",
        f"- Target build: `{audit['target_build_id']}`",
        f"- Selected sprites: {audit['summary']['sprite_count']:,}",
        f"- Common rendered sprites: {audit['summary']['common_sprite_count']:,}",
        "- Decoded pixel payload persisted: no",
        "",
        "## Classifications",
        "",
        "| Status | Sprites |",
        "|---|---:|",
    ]
    for status in STATUSES:
        lines.append(f"| `{status}` | {audit['summary']['status_counts'][status]:,} |")
    lines.extend(
        [
            "",
            "## Texture families",
            "",
            "| Texture | Sprites | Identical | Main different | Mask different | Missing | Raw main | Recommendation |",
            "|---|---:|---:|---:|---:|---:|---|---|",
        ]
    )
    for item in audit["textures"]:
        counts = item["status_counts"]
        payload = item.get("payloads", {})
        raw_main = "identical" if payload.get("main_payload_equal") else "different/missing"
        lines.append(
            f"| `{item['texture']}` | {item['sprite_count']:,} | "
            f"{counts[STATUS_KEEP_IDENTICAL]:,} | {counts[STATUS_MAIN_DIFFERENT]:,} | "
            f"{counts[STATUS_MASK_DIFFERENT]:,} | {counts[STATUS_MISSING]:,} | "
            f"{raw_main} | `{item['recommended_action']}` |"
        )
    lines.extend(
        [
            "",
            "## Groups",
            "",
            "| Group | Sprites | Identical | Main different | Mask different | Missing | Recommendation |",
            "|---|---:|---:|---:|---:|---:|---|",
        ]
    )
    for item in audit["groups"]:
        counts = item["status_counts"]
        lines.append(
            f"| `{item['group']}` | {item['sprite_count']:,} | "
            f"{counts[STATUS_KEEP_IDENTICAL]:,} | {counts[STATUS_MAIN_DIFFERENT]:,} | "
            f"{counts[STATUS_MASK_DIFFERENT]:,} | {counts[STATUS_MISSING]:,} | "
            f"`{item['recommended_action']}` |"
        )
    lines.extend(
        [
            "",
            "`MASK_DIFFERENT` means the rendered main RGBA pixels are identical but",
            "the target-authoritative team mask differs on at least one visible main",
            "pixel. Such a family must remain `KEEP_CRUSADER`; copying only the SH1DE",
            "mask would change the target rendering even when the main atlas is already",
            "byte-identical.",
            "",
        ]
    )
    _write_text("\n".join(lines), markdown_path)

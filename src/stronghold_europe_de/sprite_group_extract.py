from __future__ import annotations

import argparse
from dataclasses import asdict
import gc
import hashlib
from io import BytesIO
from importlib.metadata import version
import json
from math import isfinite
import os
import platform
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import tempfile
from typing import Any, Iterable, Sequence
import zlib

from PIL import Image

from .builds import BuildMatch, verify_supported_builds
from .config import BuilderConfig, load_config
from .gm_atlas import FrameSlot, parse_loader_frame_name
from .hashing import sha256_file
from .loader_groups import LOADER_GROUP_TABLE, LoaderGroup
from .runtime_prerequisites import RuntimePrerequisiteError, verify_runtime_prerequisites
from .pixel_identity import (
    assert_mask_projectable,
    crop_mask_for_sprite,
    hash_stream_payload,
)
from .unity_inventory import (
    _import_unitypy,
    load_unity_asset,
    sprite_from_tree,
    texture_from_tree,
)


class SpriteGroupExtractionError(RuntimeError):
    """Raised when a private sprite-group extraction cannot be proven safe."""


_SAFE_GROUP_RE = re.compile(r"[A-Za-z0-9_ -]+")
_SAFE_ASSET_NAME_RE = re.compile(r"[A-Za-z0-9_ -]+")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_WINDOWS_RESERVED_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}
_DEFAULT_COLOURS = (
    (0.69, 0.59, 0.17, 1.0),
    (0.8, 0.109, 0.219, 1.0),
    (0.058, 0.572, 0.831, 1.0),
    (0.945, 0.478, 0.121, 1.0),
    (1.0, 0.823, 0.137, 1.0),
    (0.654, 0.156, 0.764, 1.0),
    (0.435, 0.435, 0.435, 1.0),
    (0.274, 0.992, 0.984, 1.0),
    (0.301, 0.831, 0.129, 1.0),
    (0.435, 0.435, 0.435, 1.0),
)
_KNIGHT_COLOURS = (
    (0.8962, 0.5055, 0.1817, 1.0),
    (0.6698, 0.6698, 0.6698, 1.0),
    (0.8867, 0.8867, 0.8867, 1.0),
    (0.7264, 0.3316, 0.161, 1.0),
    (1.0, 0.964, 0.964, 1.0),
    (1.0, 1.0, 1.0, 1.0),
    (0.3207, 0.3207, 0.3207, 1.0),
    (0.89, 0.607, 0.423, 1.0),
    (1.0, 0.5063, 0.2877, 1.0),
    (0.3207, 0.3207, 0.3207, 1.0),
)
_CUSTOM_PALETTES: dict[str, tuple[str, tuple[tuple[float, ...], ...]]] = {
    "body_horse_archer": ("knightColours", _KNIGHT_COLOURS),
}
_PINNED_GROUP_CONTRACTS: dict[str, dict[str, object]] = {
    "body_horse_archer": {
        "frame_count": 1552,
        "main_count": 1296,
        "alt_count": 256,
        "max_index": 1455,
        "array_size": 1456,
        "names_sha256": (
            "e8f7abe8b09a83d66a24848a559fd52e"
            "9e196d17a047ecc2b33cea4a3f6c79a8"
        ),
        "main_slot_runs": [[0, 399], [560, 1455]],
        "alt_slot_runs": [[0, 127], [272, 399]],
        "texture_names": ["body12Sprites"],
        "texture_path_ids": [41],
        "mask_texture_name": "body12Sprites_m",
        "mask_texture_path_id": 40,
        "mapping_relation": "TARGET_EXCLUSIVE",
    },
    "body_horse_archer_top": {
        "frame_count": 1296,
        "main_count": 1168,
        "alt_count": 128,
        "max_index": 1455,
        "array_size": 1456,
        "names_sha256": (
            "28ba9b375de487b8fadbb6358a3217daa"
            "08158b6dd9ff5764b37faa5043debcf"
        ),
        "main_slot_runs": [[0, 527], [560, 943], [1200, 1455]],
        "alt_slot_runs": [[0, 127]],
        "texture_names": ["body12Sprites"],
        "texture_path_ids": [41],
        "mask_texture_name": "body12Sprites_m",
        "mask_texture_path_id": 40,
        "mapping_relation": "TARGET_EXCLUSIVE",
    },
}
_HORSE_ARCHER_GROUPS = ("body_horse_archer", "body_horse_archer_top")
_HORSE_ARCHER_FRAME_COUNT = sum(
    int(_PINNED_GROUP_CONTRACTS[group]["frame_count"])
    for group in _HORSE_ARCHER_GROUPS
)
_EXPECTED_PAYLOAD_FILE_COUNT = _HORSE_ARCHER_FRAME_COUNT * 4 + 7
_PINNED_TEXTURE_RECORDS = {
    "main": {
        "path_id": 41,
        "name": "body12Sprites",
        "width": 8192,
        "height": 8192,
        "texture_format": 25,
        "stream_path": "resources.assets.resS",
        "stream_offset": 876334608,
        "stream_size": 67108864,
    },
    "mask": {
        "path_id": 40,
        "name": "body12Sprites_m",
        "width": 8192,
        "height": 8192,
        "texture_format": 10,
        "stream_path": "resources.assets.resS",
        "stream_offset": 842780176,
        "stream_size": 33554432,
    },
}
_EXTRACTOR_SOURCE_FILES = (
    "src/stronghold_europe_de/sprite_group_extract.py",
    "src/stronghold_europe_de/unity_inventory.py",
    "src/stronghold_europe_de/pixel_identity.py",
    "src/stronghold_europe_de/loader_groups.py",
    "src/stronghold_europe_de/gm_atlas.py",
    "config/supported-builds.json",
    "config/runtime-prerequisites.json",
)
_MANIFEST_KEYS = {
    "schema_version",
    "kind",
    "side",
    "build_id",
    "asset_path",
    "toolchain",
    "loader_contract",
    "input_fingerprints",
    "source_absence_proof",
    "unity_object_counts",
    "unity_object_scope",
    "sprite_atlas_object_count",
    "animation_clip_object_count",
    "mask_export_contract",
    "groups",
    "textures",
    "sprite_index",
    "payload_file_count",
    "payload_files_sha256",
    "files_index",
}
_GROUP_SUMMARY_KEYS = {
    "group",
    "loader",
    "frame_count",
    "main_count",
    "alt_count",
    "max_index",
    "array_size",
    "names_sha256",
    "main_slot_runs",
    "alt_slot_runs",
    "texture_names",
    "texture_path_ids",
    "pinned_contract",
}
_TEXTURE_RECORD_KEYS = {
    "path_id",
    "name",
    "width",
    "height",
    "texture_format",
    "stream_path",
    "stream_offset",
    "stream_size",
}
_IMAGE_KEYS = {
    "path",
    "size",
    "sha256",
    "rgba_sha256",
    "width",
    "height",
    "alpha_bbox",
    "alpha_sum",
}
_SERIALIZED_KEYS = {"path", "size", "sha256"}
_STREAM_KEYS = {
    "source_file",
    "source_offset",
    "path",
    "size",
    "sha256",
}
_TEXTURE_SUMMARY_KEYS = {
    "main",
    "mask",
    "main_serialized_object",
    "mask_serialized_object",
    "main_stream",
    "mask_stream",
    "main_decoded",
    "mask_decoded",
}
_SPRITE_ROW_KEYS = {
    "path_id",
    "name",
    "rect_x",
    "rect_y",
    "width",
    "height",
    "offset_x",
    "offset_y",
    "pivot_x",
    "pivot_y",
    "pixels_per_unit",
    "texture_path_id",
    "texture_name",
    "alpha_texture_path_id",
    "settings_raw",
    "downscale_multiplier",
    "group",
    "slot_index",
    "is_alt",
    "render_data",
    "serialized_object",
    "main_image",
    "projected_mask_image",
    "effective_mask_image",
}
_RENDER_DATA_KEYS = {
    "render_data_key",
    "texture_rect",
    "texture_rect_offset",
    "atlas_rect_offset",
    "uv_transform",
    "texture_pointer",
    "alpha_texture_pointer",
    "sprite_atlas_pointer",
    "settings_raw",
    "downscale_multiplier",
    "is_polygon",
    "extrude",
    "vertex_count",
    "vertex_bytes",
    "index_bytes",
    "channels",
    "sub_meshes",
}
_MASK_EXPORT_CONTRACT = {
    "projected": (
        "companion atlas rect projected at native main-atlas coordinates; "
        "may contain pixels outside a tight Sprite mesh"
    ),
    "effective": (
        "projected mask retained only where reconstructed Sprite.image "
        "has nonzero alpha"
    ),
}
_UNITY_OBJECT_SCOPE = (
    "counts apply only to canonical target resources.assets; they do not claim "
    "absence from sharedassets1.assets, managed assemblies, or native engine code"
)


class _DuplicateJsonKeyError(ValueError):
    pass


class _InvalidJsonConstantError(ValueError):
    pass


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _reject_json_constant(value: str) -> object:
    raise _InvalidJsonConstantError(f"non-finite JSON constant: {value}")


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKeyError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _strict_json_value(payload: str, *, label: str) -> object:
    try:
        value = json.loads(
            payload,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except (
        json.JSONDecodeError,
        _DuplicateJsonKeyError,
        _InvalidJsonConstantError,
        RecursionError,
        ValueError,
    ) as exc:
        raise SpriteGroupExtractionError(f"Cannot decode {label}: {exc}") from exc
    pending: list[object] = [value]
    while pending:
        candidate = pending.pop()
        if isinstance(candidate, float) and not isfinite(candidate):
            raise SpriteGroupExtractionError(
                f"Cannot decode {label}: non-finite numeric value"
            )
        if isinstance(candidate, dict):
            pending.extend(candidate.values())
        elif isinstance(candidate, list):
            pending.extend(candidate)
    return value


def _strict_json_object(path: Path) -> dict[str, object]:
    try:
        payload = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise SpriteGroupExtractionError(f"Cannot read JSON object {path}: {exc}") from exc
    value = _strict_json_value(payload, label=str(path))
    if not isinstance(value, dict):
        raise SpriteGroupExtractionError(
            f"Top-level JSON value must be an object in {path}"
        )
    return value


def _strict_jsonl(path: Path) -> list[dict[str, object]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise SpriteGroupExtractionError(f"Cannot read JSONL {path}: {exc}") from exc
    if not lines:
        raise SpriteGroupExtractionError(f"JSONL file is empty: {path}")
    records: list[dict[str, object]] = []
    for line_number, line in enumerate(lines, 1):
        if not line:
            raise SpriteGroupExtractionError(
                f"Blank JSONL record in {path} at line {line_number}"
            )
        value = _strict_json_value(
            line,
            label=f"{path} line {line_number}",
        )
        if not isinstance(value, dict):
            raise SpriteGroupExtractionError(
                f"JSONL record must be an object in {path} at line {line_number}"
            )
        records.append(value)
    return records


def _safe_relative_path(raw: object, *, label: str) -> Path:
    if (
        not isinstance(raw, str)
        or not raw
        or "\\" in raw
        or any(ord(character) < 32 for character in raw)
        or ":" in raw
    ):
        raise SpriteGroupExtractionError(f"Unsafe {label}: {raw!r}")
    portable = PurePosixPath(raw)
    path = Path(*portable.parts)
    if portable.is_absolute() or portable.as_posix() != raw or any(
        part in {"", ".", ".."}
        or part.endswith((".", " "))
        or part.split(".", 1)[0].casefold() in _WINDOWS_RESERVED_NAMES
        for part in portable.parts
    ):
        raise SpriteGroupExtractionError(f"Unsafe {label}: {raw!r}")
    return path


def _source_set(config: BuilderConfig) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for relative in _EXTRACTOR_SOURCE_FILES:
        path = (config.project_root / Path(relative)).resolve(strict=True)
        if config.project_root.resolve() not in path.parents or not path.is_file():
            raise SpriteGroupExtractionError(
                f"Extractor source input escaped the project: {relative}"
            )
        records.append(
            {
                "path": relative,
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return records


def _toolchain_metadata(config: BuilderConfig) -> dict[str, object]:
    return {
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "python_byteorder": sys.byteorder,
        "platform_system": platform.system(),
        "platform_machine": platform.machine(),
        "pillow_version": version("Pillow"),
        "unitypy_version": version("UnityPy"),
        "zlib_compile_version": zlib.ZLIB_VERSION,
        "zlib_runtime_version": zlib.ZLIB_RUNTIME_VERSION,
        "extractor_source_files": _source_set(config),
    }


def _loader_contract_metadata(config: BuilderConfig) -> dict[str, object]:
    prerequisite_path = (
        config.project_root / "config" / "runtime-prerequisites.json"
    ).resolve(strict=True)
    data = _strict_json_object(prerequisite_path)
    if config.target.game_dir is None:
        raise SpriteGroupExtractionError("SHCDE-SE loader installation is unavailable")
    try:
        proof = verify_runtime_prerequisites(data, config.target.game_dir)
        entry = next(item for item in proof.files if item.id == "shcdese")
    except (RuntimePrerequisiteError, StopIteration) as exc:
        raise SpriteGroupExtractionError(f"Installed SHCDE-SE loader is incompatible: {exc}") from exc
    return {
        "config_id": proof.config_id,
        "script_extender_version": proof.script_extender_version,
        "config_sha256": sha256_file(prerequisite_path),
        "binary": {
            key: getattr(entry, key)
            for key in (
                "relative_path", "size", "sha256", "assembly_name",
                "assembly_version", "mvid",
            )
        },
    }


def _source_absence_proof(
    config: BuilderConfig,
    match: BuildMatch,
) -> dict[str, object]:
    asset_path = (config.source.data_dir / "resources.assets").resolve(strict=True)
    if asset_path.parent != config.source.data_dir.resolve():
        raise SpriteGroupExtractionError("Canonical source resources.assets moved")
    _assert_input_file(
        asset_path,
        relative_path="resources.assets",
        match=match,
        side="source",
    )
    environment = load_unity_asset(asset_path, unitypy=_import_unitypy())
    sprite_count = 0
    matches: list[str] = []
    for obj in environment.objects:
        if obj.type.name != "Sprite":
            continue
        sprite_count += 1
        tree = obj.read_typetree()
        name = str(tree.get("m_Name", ""))
        for group in _HORSE_ARCHER_GROUPS:
            if parse_loader_frame_name(
                name,
                group,
                LOADER_GROUP_TABLE[group].dash_format,
            ) is not None:
                matches.append(name)
    del environment
    gc.collect()
    _assert_input_file(
        asset_path,
        relative_path="resources.assets",
        match=match,
        side="source",
    )
    if matches:
        raise SpriteGroupExtractionError(
            f"Pinned target-exclusive mapping changed; SH1DE contains {matches[:5]!r}"
        )
    source_entry = _fingerprint_entries(match, "source")["resources.assets"]
    return {
        "build_id": match.source_id,
        "asset_path": "resources.assets",
        "asset_size": source_entry.size,
        "asset_sha256": source_entry.sha256,
        "groups": list(_HORSE_ARCHER_GROUPS),
        "sprite_object_count_scanned": sprite_count,
        "matching_frame_count": 0,
    }


def _write_bytes(path: Path, payload: bytes) -> dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return {
        "size": len(payload),
        "sha256": _sha256_bytes(payload),
    }


def _canonical_png_bytes(image: Image.Image) -> bytes:
    rgba = image if image.mode == "RGBA" else image.convert("RGBA")
    stream = BytesIO()
    rgba.save(stream, format="PNG", optimize=False, compress_level=9)
    return stream.getvalue()


def _save_png(path: Path, image: Image.Image) -> dict[str, object]:
    rgba = image if image.mode == "RGBA" else image.convert("RGBA")
    file_metadata = _write_bytes(path, _canonical_png_bytes(rgba))
    alpha = rgba.getchannel("A")
    alpha_bbox = alpha.getbbox()
    return {
        **file_metadata,
        "rgba_sha256": _sha256_bytes(rgba.tobytes()),
        "width": rgba.width,
        "height": rgba.height,
        "alpha_bbox": list(alpha_bbox) if alpha_bbox is not None else None,
        "alpha_sum": sum(alpha.get_flattened_data()),
    }


def _effective_mask(main_image: Image.Image, projected_mask: Image.Image) -> Image.Image:
    main = main_image if main_image.mode == "RGBA" else main_image.convert("RGBA")
    mask = (
        projected_mask
        if projected_mask.mode == "RGBA"
        else projected_mask.convert("RGBA")
    )
    if main.size != mask.size:
        raise SpriteGroupExtractionError(
            f"Projected mask geometry differs from Sprite.image: "
            f"{mask.size} != {main.size}"
        )
    coverage = main.getchannel("A").point(lambda value: 255 if value else 0)
    empty = Image.new("RGBA", main.size, (0, 0, 0, 0))
    return Image.composite(mask, empty, coverage)


def _raw_bytes(value: object, *, label: str) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, list) and all(type(item) is int and 0 <= item <= 255 for item in value):
        return bytes(value)
    raise SpriteGroupExtractionError(f"Expected byte payload for {label}")


def _vector(value: object, fields: Sequence[str], *, label: str) -> dict[str, float]:
    if not isinstance(value, dict) or set(value) != set(fields):
        raise SpriteGroupExtractionError(f"Unexpected vector shape for {label}")
    result = {field: float(value[field]) for field in fields}
    if not all(isfinite(item) for item in result.values()):
        raise SpriteGroupExtractionError(f"Non-finite vector value for {label}")
    return result


def _sprite_render_metadata(tree: dict[str, object], *, name: str) -> dict[str, object]:
    render_data = tree.get("m_RD")
    if not isinstance(render_data, dict):
        raise SpriteGroupExtractionError(f"Sprite has no render data: {name}")
    vertex_data = render_data.get("m_VertexData")
    if not isinstance(vertex_data, dict):
        raise SpriteGroupExtractionError(f"Sprite has no vertex data: {name}")
    vertex_payload = _raw_bytes(
        vertex_data.get("m_DataSize"),
        label=f"{name}.m_VertexData.m_DataSize",
    )
    index_payload = _raw_bytes(
        render_data.get("m_IndexBuffer"),
        label=f"{name}.m_IndexBuffer",
    )
    render_key = tree.get("m_RenderDataKey")
    if (
        not isinstance(render_key, (list, tuple))
        or len(render_key) != 2
        or not isinstance(render_key[0], dict)
        or set(render_key[0]) != {f"data[{index}]" for index in range(4)}
        or type(render_key[1]) is not int
    ):
        raise SpriteGroupExtractionError(f"Unexpected render-data key: {name}")
    guid = [int(render_key[0][f"data[{index}]"]) for index in range(4)]
    texture_pointer = render_data.get("texture")
    alpha_pointer = render_data.get("alphaTexture")
    sprite_atlas = tree.get("m_SpriteAtlas")
    for label, pointer in (
        ("texture", texture_pointer),
        ("alphaTexture", alpha_pointer),
        ("spriteAtlas", sprite_atlas),
    ):
        if not isinstance(pointer, dict) or set(pointer) != {"m_FileID", "m_PathID"}:
            raise SpriteGroupExtractionError(
                f"Unexpected {label} pointer for sprite {name}"
            )
    sub_meshes = render_data.get("m_SubMeshes")
    channels = vertex_data.get("m_Channels")
    if not isinstance(sub_meshes, list) or not isinstance(channels, list):
        raise SpriteGroupExtractionError(f"Unexpected mesh arrays for sprite {name}")
    return {
        "render_data_key": {"guid_words": guid, "secondary": render_key[1]},
        "texture_rect": _vector(
            render_data.get("textureRect"),
            ("x", "y", "width", "height"),
            label=f"{name}.textureRect",
        ),
        "texture_rect_offset": _vector(
            render_data.get("textureRectOffset"),
            ("x", "y"),
            label=f"{name}.textureRectOffset",
        ),
        "atlas_rect_offset": _vector(
            render_data.get("atlasRectOffset"),
            ("x", "y"),
            label=f"{name}.atlasRectOffset",
        ),
        "uv_transform": _vector(
            render_data.get("uvTransform"),
            ("x", "y", "z", "w"),
            label=f"{name}.uvTransform",
        ),
        "texture_pointer": {
            "file_id": int(texture_pointer["m_FileID"]),
            "path_id": int(texture_pointer["m_PathID"]),
        },
        "alpha_texture_pointer": {
            "file_id": int(alpha_pointer["m_FileID"]),
            "path_id": int(alpha_pointer["m_PathID"]),
        },
        "sprite_atlas_pointer": {
            "file_id": int(sprite_atlas["m_FileID"]),
            "path_id": int(sprite_atlas["m_PathID"]),
        },
        "settings_raw": int(render_data.get("settingsRaw", -1)),
        "downscale_multiplier": float(render_data.get("downscaleMultiplier", 0.0)),
        "is_polygon": bool(tree.get("m_IsPolygon")),
        "extrude": int(tree.get("m_Extrude", -1)),
        "vertex_count": int(vertex_data.get("m_VertexCount", -1)),
        "vertex_bytes": {
            "size": len(vertex_payload),
            "sha256": _sha256_bytes(vertex_payload),
        },
        "index_bytes": {
            "size": len(index_payload),
            "sha256": _sha256_bytes(index_payload),
        },
        "channels": channels,
        "sub_meshes": sub_meshes,
    }


def _decode_sprite_image(sprite_object: object, *, name: str, size: tuple[int, int]) -> Image.Image:
    try:
        image = sprite_object.read().image.convert("RGBA")
    except Exception as exc:
        raise SpriteGroupExtractionError(
            f"Unity Sprite.image decoding failed for {name}: {exc}"
        ) from exc
    if image.size != size:
        raise SpriteGroupExtractionError(
            f"Unity Sprite.image geometry changed for {name}: {image.size} != {size}"
        )
    return image


def _fingerprint_entries(match: BuildMatch, side: str) -> dict[str, object]:
    fingerprint = (
        match.source_fingerprint if side == "source" else match.target_fingerprint
    )
    return {item.relative_path.replace("\\", "/"): item for item in fingerprint.files}


def _assert_input_file(
    path: Path,
    *,
    relative_path: str,
    match: BuildMatch,
    side: str,
) -> None:
    expected = _fingerprint_entries(match, side).get(relative_path)
    if expected is None:
        raise SpriteGroupExtractionError(
            f"Input is absent from the exact build fingerprint: {relative_path}"
        )
    try:
        stat_result = path.stat()
    except OSError as exc:
        raise SpriteGroupExtractionError(f"Cannot stat extraction input: {path}") from exc
    if not path.is_file() or stat_result.st_size != expected.size:
        raise SpriteGroupExtractionError(
            f"Extraction input size changed for {relative_path}"
        )
    actual_hash = sha256_file(path)
    if actual_hash != expected.sha256.lower():
        raise SpriteGroupExtractionError(
            f"Extraction input hash changed for {relative_path}: {actual_hash}"
        )


def _safe_output_path(config: BuilderConfig, raw_output: Path) -> Path:
    candidate = (
        raw_output.resolve()
        if raw_output.is_absolute()
        else (config.project_root / raw_output).resolve()
    )
    work_root = config.output.work_dir.resolve()
    if candidate == work_root or work_root not in candidate.parents:
        raise SpriteGroupExtractionError(
            f"Extraction output must be a child of the private work directory: "
            f"{candidate}"
        )
    if candidate.exists():
        raise SpriteGroupExtractionError(
            f"Extraction output already exists; refusing to overwrite it: {candidate}"
        )
    return candidate


def _validate_groups(groups: Sequence[str]) -> tuple[str, ...]:
    if not groups:
        raise SpriteGroupExtractionError("At least one sprite group is required")
    normalized = tuple(str(group) for group in groups)
    if len(set(name.casefold() for name in normalized)) != len(normalized):
        raise SpriteGroupExtractionError("Sprite groups must be case-insensitively unique")
    for group in normalized:
        if _SAFE_GROUP_RE.fullmatch(group) is None:
            raise SpriteGroupExtractionError(f"Unsafe sprite group name: {group!r}")
        if group not in LOADER_GROUP_TABLE:
            raise SpriteGroupExtractionError(
                f"Sprite group is absent from the pinned loader table: {group}"
            )
        if group not in _PINNED_GROUP_CONTRACTS:
            raise SpriteGroupExtractionError(
                f"Sprite group has no pinned extraction contract: {group}"
            )
    if normalized != _HORSE_ARCHER_GROUPS:
        raise SpriteGroupExtractionError(
            "A complete Horse Archer extraction requires both pinned groups in "
            f"loader order: {_HORSE_ARCHER_GROUPS!r}"
        )
    return normalized


def _slot_runs(indices: Iterable[int]) -> list[list[int]]:
    ordered = sorted(set(indices))
    if not ordered:
        return []
    runs: list[list[int]] = []
    start = previous = ordered[0]
    for value in ordered[1:]:
        if value != previous + 1:
            runs.append([start, previous])
            start = value
        previous = value
    runs.append([start, previous])
    return runs


def _copy_stream_slice(
    source: Path,
    output: Path,
    offset: int,
    size: int,
) -> dict[str, object]:
    if offset < 0 or size <= 0:
        raise SpriteGroupExtractionError(
            f"Invalid Unity stream slice: offset={offset} size={size}"
        )
    initial_stat = source.stat()
    source_size = initial_stat.st_size
    if offset + size > source_size:
        raise SpriteGroupExtractionError(
            f"Unity stream slice escapes {source.name}: "
            f"offset={offset} size={size} file={source_size}"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    remaining = size
    with source.open("rb") as source_stream, output.open("wb") as target_stream:
        source_stream.seek(offset)
        while remaining:
            block = source_stream.read(min(1024 * 1024, remaining))
            if not block:
                raise SpriteGroupExtractionError(
                    f"Unexpected EOF in Unity stream slice: {source}"
                )
            target_stream.write(block)
            digest.update(block)
            remaining -= len(block)
    final_stat = source.stat()
    if (
        final_stat.st_size != initial_stat.st_size
        or final_stat.st_mtime_ns != initial_stat.st_mtime_ns
        or final_stat.st_ctime_ns != initial_stat.st_ctime_ns
    ):
        raise SpriteGroupExtractionError(
            f"Unity stream changed while copying its payload: {source}"
        )
    return {"size": size, "sha256": digest.hexdigest()}


def _input_fingerprints(
    match: BuildMatch,
    side: str,
) -> list[dict[str, object]]:
    fingerprint = (
        match.source_fingerprint if side == "source" else match.target_fingerprint
    )
    relevant = {
        "resources.assets",
        "resources.assets.resS",
        "resources.resource",
        "Managed/Assembly-CSharp.dll",
        "globalgamemanagers",
    }
    return [
        {
            "relative_path": item.relative_path,
            "size": item.size,
            "sha256": item.sha256,
        }
        for item in fingerprint.files
        if item.relative_path.replace("\\", "/") in relevant
    ]


def _payload_file_index(root: Path) -> tuple[list[dict[str, object]], str]:
    records: list[dict[str, object]] = []
    digest = hashlib.sha256()
    for path in sorted(
        (
            item
            for item in root.rglob("*")
            if item.is_file() and item.name not in {"manifest.json", "files.jsonl"}
        ),
        key=lambda item: item.relative_to(root).as_posix(),
    ):
        relative = path.relative_to(root).as_posix()
        size = path.stat().st_size
        file_hash = sha256_file(path)
        record = {"path": relative, "size": size, "sha256": file_hash}
        records.append(record)
        digest.update(f"{relative}\t{size}\t{file_hash}\n".encode("utf-8"))
    return records, digest.hexdigest()


def _write_jsonl(path: Path, records: Sequence[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(
                json.dumps(
                    record,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
            stream.write("\n")


def _canonical_jsonl_text(records: Sequence[dict[str, object]]) -> str:
    return "".join(
        json.dumps(
            record,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
        for record in records
    )


def _loader_metadata(group: str, loader: LoaderGroup) -> dict[str, object]:
    palette_name = "defaultColours"
    palette = _DEFAULT_COLOURS
    if loader.custom_palette:
        custom = _CUSTOM_PALETTES.get(group)
        if custom is None:
            raise SpriteGroupExtractionError(
                f"Custom gmColors palette is not frozen for extraction: {group}"
            )
        palette_name, palette = custom
    return {
        "gm_enum": loader.gm_enum,
        "dash_format": loader.dash_format,
        "plain_shader": loader.plain_shader,
        "declared_image_count": loader.declared_image_count,
        "custom_palette": loader.custom_palette,
        "id_offset": loader.id_offset,
        "additional_storage": loader.additional_storage,
        "owns_its_gm_arrays": loader.owns_its_gm_arrays,
        "mask_policy": "forbidden" if loader.plain_shader else "required",
        "gm_colors": {
            "field": palette_name,
            "rgba": [list(colour) for colour in palette],
        },
    }


def _exact_keys(value: object, expected: set[str], *, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != expected:
        actual = sorted(value) if isinstance(value, dict) else type(value).__name__
        raise SpriteGroupExtractionError(
            f"Unexpected {label} shape: {actual!r}; expected {sorted(expected)!r}"
        )
    return value


def _strict_int(value: object, *, label: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise SpriteGroupExtractionError(
            f"Expected integer {label} >= {minimum}: {value!r}"
        )
    return value


def _strict_sha256(value: object, *, label: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise SpriteGroupExtractionError(f"Expected lowercase SHA-256 for {label}")
    return value


def _is_link_or_reparse(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise SpriteGroupExtractionError(f"Cannot inspect extraction path: {path}") from exc
    attributes = int(getattr(metadata, "st_file_attributes", 0))
    return path.is_symlink() or bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _existing_extraction_root(config: BuilderConfig, raw_root: Path) -> Path:
    unresolved = raw_root if raw_root.is_absolute() else config.project_root / raw_root
    try:
        absolute = unresolved.absolute()
        resolved = unresolved.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise SpriteGroupExtractionError(
            f"Extraction root cannot be resolved: {unresolved}"
        ) from exc
    work_root = config.output.work_dir.resolve(strict=True)
    if resolved == work_root or work_root not in resolved.parents or not resolved.is_dir():
        raise SpriteGroupExtractionError(
            f"Extraction root must be an existing child of private work: {resolved}"
        )
    if absolute != resolved:
        raise SpriteGroupExtractionError(
            f"Extraction root contains a link or reparse ancestor: {unresolved}"
        )
    current = work_root
    for part in resolved.relative_to(work_root).parts:
        current /= part
        if _is_link_or_reparse(current):
            raise SpriteGroupExtractionError(
                f"Extraction root contains a link or reparse point: {current}"
            )
    return resolved


def _scan_extraction_tree(root: Path) -> tuple[dict[str, Path], set[str]]:
    files: dict[str, Path] = {}
    directories: set[str] = set()
    casefold_paths: dict[str, str] = {}
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            entries = sorted(os.scandir(directory), key=lambda item: item.name)
        except OSError as exc:
            raise SpriteGroupExtractionError(
                f"Cannot enumerate extraction directory: {directory}"
            ) from exc
        for entry in entries:
            path = Path(entry.path)
            relative = path.relative_to(root).as_posix()
            _safe_relative_path(relative, label="extraction tree path")
            key = relative.casefold()
            prior = casefold_paths.get(key)
            if prior is not None:
                raise SpriteGroupExtractionError(
                    f"Case-insensitive extraction path collision: {prior!r}, {relative!r}"
                )
            casefold_paths[key] = relative
            try:
                metadata = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise SpriteGroupExtractionError(
                    f"Cannot inspect extraction entry: {path}"
                ) from exc
            if entry.is_symlink() or bool(
                int(getattr(metadata, "st_file_attributes", 0))
                & stat.FILE_ATTRIBUTE_REPARSE_POINT
            ):
                raise SpriteGroupExtractionError(
                    f"Extraction tree contains a link or reparse point: {relative}"
                )
            if entry.is_dir(follow_symlinks=False):
                directories.add(relative)
                pending.append(path)
            elif entry.is_file(follow_symlinks=False):
                if path.name in {"manifest.json", "files.jsonl"} and path.parent != root:
                    raise SpriteGroupExtractionError(
                        f"Reserved extraction metadata name is nested: {relative}"
                    )
                files[relative] = path
            else:
                raise SpriteGroupExtractionError(
                    f"Unsupported extraction tree entry: {relative}"
                )
    return files, directories


def _file_entry(
    root: Path,
    metadata: object,
    *,
    expected_path: str,
    expected_keys: set[str],
    label: str,
) -> tuple[Path, dict[str, object]]:
    entry = _exact_keys(metadata, expected_keys, label=label)
    relative = _safe_relative_path(entry.get("path"), label=f"{label} path")
    if relative.as_posix() != expected_path:
        raise SpriteGroupExtractionError(
            f"Unexpected {label} path: {relative.as_posix()} != {expected_path}"
        )
    path = root / relative
    expected_size = _strict_int(entry.get("size"), label=f"{label} size")
    expected_hash = _strict_sha256(entry.get("sha256"), label=f"{label} hash")
    if not path.is_file() or path.stat().st_size != expected_size:
        raise SpriteGroupExtractionError(f"{label} size differs from metadata")
    if sha256_file(path) != expected_hash:
        raise SpriteGroupExtractionError(f"{label} hash differs from metadata")
    return path, entry


def _verify_png(
    root: Path,
    metadata: object,
    *,
    expected_path: str,
    expected_size: tuple[int, int],
    label: str,
) -> Image.Image:
    path, entry = _file_entry(
        root,
        metadata,
        expected_path=expected_path,
        expected_keys=_IMAGE_KEYS,
        label=label,
    )
    if (
        _strict_int(entry.get("width"), label=f"{label} width", minimum=1),
        _strict_int(entry.get("height"), label=f"{label} height", minimum=1),
    ) != expected_size:
        raise SpriteGroupExtractionError(f"{label} geometry differs from sprite")
    try:
        with Image.open(path) as opened:
            if (
                opened.format != "PNG"
                or opened.mode != "RGBA"
                or int(getattr(opened, "n_frames", 1)) != 1
            ):
                raise SpriteGroupExtractionError(
                    f"{label} must be a single-frame RGBA PNG"
                )
            opened.load()
            image = opened.copy()
    except (OSError, ValueError) as exc:
        raise SpriteGroupExtractionError(f"Cannot decode {label}: {exc}") from exc
    if path.read_bytes() != _canonical_png_bytes(image):
        raise SpriteGroupExtractionError(f"{label} is not a canonical extraction PNG")
    rgba_hash = _sha256_bytes(image.tobytes())
    if rgba_hash != _strict_sha256(
        entry.get("rgba_sha256"),
        label=f"{label} RGBA hash",
    ):
        raise SpriteGroupExtractionError(f"{label} RGBA hash differs from metadata")
    alpha = image.getchannel("A")
    bbox = alpha.getbbox()
    actual_bbox = list(bbox) if bbox is not None else None
    raw_bbox = entry.get("alpha_bbox")
    if raw_bbox is not None and (
        not isinstance(raw_bbox, list)
        or len(raw_bbox) != 4
        or any(type(value) is not int for value in raw_bbox)
    ):
        raise SpriteGroupExtractionError(f"Invalid {label} alpha bounding box")
    if raw_bbox != actual_bbox:
        raise SpriteGroupExtractionError(f"{label} alpha bounding box differs")
    if _strict_int(entry.get("alpha_sum"), label=f"{label} alpha sum") != sum(
        alpha.get_flattened_data()
    ):
        raise SpriteGroupExtractionError(f"{label} alpha sum differs")
    return image


def _verify_payload_ledger(
    root: Path,
    files: dict[str, Path],
    directories: set[str],
    manifest: dict[str, object],
) -> dict[str, dict[str, object]]:
    files_index_path, files_index_metadata = _file_entry(
        root,
        manifest.get("files_index"),
        expected_path="files.jsonl",
        expected_keys={"path", "record_count", "size", "sha256"},
        label="files index",
    )
    records = _strict_jsonl(files_index_path)
    if files_index_path.read_text(encoding="utf-8") != _canonical_jsonl_text(records):
        raise SpriteGroupExtractionError("Files index is not canonically serialized")
    if _strict_int(
        files_index_metadata.get("record_count"),
        label="files index record count",
    ) != len(records):
        raise SpriteGroupExtractionError("Files-index record count differs")
    sprite_index = manifest.get("sprite_index")
    sprite_count = _strict_int(
        sprite_index.get("record_count") if isinstance(sprite_index, dict) else None,
        label="sprite record count", minimum=1,
    )
    if len(records) != sprite_count * 4 + 7:
        raise SpriteGroupExtractionError(
            f"Incomplete Horse Archer payload ledger: {len(records)}"
        )
    ledger: dict[str, dict[str, object]] = {}
    casefold_paths: dict[str, str] = {}
    ordered_paths: list[str] = []
    aggregate = hashlib.sha256()
    for index, raw_record in enumerate(records):
        record = _exact_keys(
            raw_record,
            {"path", "size", "sha256"},
            label=f"files-index record {index}",
        )
        relative = _safe_relative_path(
            record.get("path"),
            label=f"files-index path {index}",
        ).as_posix()
        if Path(relative).name in {"manifest.json", "files.jsonl"}:
            raise SpriteGroupExtractionError(
                f"Reserved metadata file appears in payload ledger: {relative}"
            )
        if relative in ledger:
            raise SpriteGroupExtractionError(f"Duplicate payload path: {relative}")
        key = relative.casefold()
        prior = casefold_paths.get(key)
        if prior is not None:
            raise SpriteGroupExtractionError(
                f"Case-insensitive payload collision: {prior!r}, {relative!r}"
            )
        casefold_paths[key] = relative
        size = _strict_int(record.get("size"), label=f"payload size {relative}")
        digest = _strict_sha256(
            record.get("sha256"),
            label=f"payload hash {relative}",
        )
        actual = files.get(relative)
        if actual is None or actual.stat().st_size != size:
            raise SpriteGroupExtractionError(
                f"Payload file is missing or has wrong size: {relative}"
            )
        if sha256_file(actual) != digest:
            raise SpriteGroupExtractionError(f"Payload hash differs: {relative}")
        ledger[relative] = record
        ordered_paths.append(relative)
        aggregate.update(f"{relative}\t{size}\t{digest}\n".encode("utf-8"))
    if ordered_paths != sorted(ordered_paths):
        raise SpriteGroupExtractionError("Payload ledger is not canonically sorted")
    expected_files = set(ledger) | {"files.jsonl", "manifest.json"}
    if set(files) != expected_files:
        raise SpriteGroupExtractionError(
            "Extraction file set differs from the exact payload ledger: "
            f"missing={sorted(expected_files-set(files))!r} "
            f"extra={sorted(set(files)-expected_files)!r}"
        )
    expected_directories = {
        parent.as_posix()
        for relative in expected_files
        for parent in PurePosixPath(relative).parents
        if parent.as_posix() != "."
    }
    if directories != expected_directories:
        raise SpriteGroupExtractionError(
            "Extraction directory set is not exact: "
            f"missing={sorted(expected_directories-directories)!r} "
            f"extra={sorted(directories-expected_directories)!r}"
        )
    if _strict_int(
        manifest.get("payload_file_count"),
        label="payload file count",
    ) != len(ledger):
        raise SpriteGroupExtractionError("Manifest payload count differs")
    if _strict_sha256(
        manifest.get("payload_files_sha256"),
        label="payload ledger digest",
    ) != aggregate.hexdigest():
        raise SpriteGroupExtractionError("Manifest payload ledger digest differs")
    return ledger


def _number_value(value: object, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SpriteGroupExtractionError(f"Expected finite number for {label}")
    numeric = float(value)
    if not isfinite(numeric):
        raise SpriteGroupExtractionError(f"Expected finite number for {label}")
    return numeric


def _integral_dimension(value: object, *, label: str) -> int:
    numeric = _number_value(value, label=label)
    rounded = round(numeric)
    if rounded <= 0 or numeric != rounded:
        raise SpriteGroupExtractionError(
            f"Expected positive integral dimension for {label}: {value!r}"
        )
    return int(rounded)


def _verify_binary_reference(
    root: Path,
    metadata: object,
    *,
    expected_path: str,
    label: str,
) -> Path:
    path, _ = _file_entry(
        root,
        metadata,
        expected_path=expected_path,
        expected_keys=_SERIALIZED_KEYS,
        label=label,
    )
    return path


def _verify_manifest_header(
    config: BuilderConfig,
    match: BuildMatch,
    manifest: dict[str, object],
) -> None:
    _exact_keys(manifest, _MANIFEST_KEYS, label="extraction manifest")
    if manifest.get("schema_version") != 2 or type(manifest.get("schema_version")) is not int:
        raise SpriteGroupExtractionError("Extraction manifest must use schema version 2")
    if manifest.get("kind") != "stronghold_europe_private_sprite_group_extraction_v2":
        raise SpriteGroupExtractionError("Extraction manifest kind is not V2")
    if (
        manifest.get("side") != "target"
        or manifest.get("build_id") != match.target_id
        or manifest.get("asset_path") != "resources.assets"
    ):
        raise SpriteGroupExtractionError("Extraction manifest target identity differs")
    if manifest.get("toolchain") != _toolchain_metadata(config):
        raise SpriteGroupExtractionError(
            "Extraction toolchain/source set differs from the current verifier"
        )
    if manifest.get("loader_contract") != _loader_contract_metadata(config):
        raise SpriteGroupExtractionError("Extraction loader contract differs")
    if manifest.get("input_fingerprints") != _input_fingerprints(match, "target"):
        raise SpriteGroupExtractionError("Extraction input fingerprints differ")
    source_proof = _exact_keys(
        manifest.get("source_absence_proof"),
        {
            "build_id",
            "asset_path",
            "asset_size",
            "asset_sha256",
            "groups",
            "sprite_object_count_scanned",
            "matching_frame_count",
        },
        label="SH1DE source-absence proof",
    )
    source_entry = _fingerprint_entries(match, "source").get("resources.assets")
    if (
        source_entry is None
        or source_proof.get("build_id") != match.source_id
        or source_proof.get("asset_path") != "resources.assets"
        or source_proof.get("asset_size") != source_entry.size
        or source_proof.get("asset_sha256") != source_entry.sha256
        or source_proof.get("groups") != list(_HORSE_ARCHER_GROUPS)
        or _strict_int(
            source_proof.get("sprite_object_count_scanned"),
            label="source Sprite count",
            minimum=1,
        )
        <= 0
        or source_proof.get("matching_frame_count") != 0
        or type(source_proof.get("matching_frame_count")) is not int
    ):
        raise SpriteGroupExtractionError("SH1DE source-absence proof shape differs")
    object_counts = manifest.get("unity_object_counts")
    if (
        not isinstance(object_counts, dict)
        or not object_counts
        or any(
            not isinstance(key, str)
            or not key
            or type(value) is not int
            or value <= 0
            for key, value in object_counts.items()
        )
    ):
        raise SpriteGroupExtractionError("Unity object-count map is malformed")
    if (
        _strict_int(
            manifest.get("sprite_atlas_object_count"),
            label="resources.assets SpriteAtlas count",
        )
        != 0
        or _strict_int(
            manifest.get("animation_clip_object_count"),
            label="resources.assets AnimationClip count",
        )
        != 0
    ):
        raise SpriteGroupExtractionError(
            "Pinned resources.assets unexpectedly contains SpriteAtlas/AnimationClip objects"
        )
    if manifest.get("mask_export_contract") != _MASK_EXPORT_CONTRACT:
        raise SpriteGroupExtractionError("Mask export contract differs")
    if manifest.get("unity_object_scope") != _UNITY_OBJECT_SCOPE:
        raise SpriteGroupExtractionError("Unity object-count scope differs")


def _verify_sprite_rows(
    root: Path,
    manifest: dict[str, object],
) -> tuple[list[dict[str, object]], set[str]]:
    sprite_index_path, sprite_index_metadata = _file_entry(
        root,
        manifest.get("sprite_index"),
        expected_path="sprites.jsonl",
        expected_keys={"path", "record_count", "size", "sha256"},
        label="sprite index",
    )
    rows = _strict_jsonl(sprite_index_path)
    if sprite_index_path.read_text(encoding="utf-8") != _canonical_jsonl_text(rows):
        raise SpriteGroupExtractionError("Sprite index is not canonically serialized")
    if (
        _strict_int(
            sprite_index_metadata.get("record_count"),
            label="sprite index record count",
        )
        != len(rows)
        or not rows
    ):
        raise SpriteGroupExtractionError("Sprite index is not the complete pinned cohort")

    references = {"sprites.jsonl"}
    names_seen: set[str] = set()
    casefold_names: set[str] = set()
    path_ids_seen: set[int] = set()
    slots_seen: dict[str, set[FrameSlot]] = {
        group: set() for group in _HORSE_ARCHER_GROUPS
    }
    actual_order: list[tuple[int, int, bool, str]] = []

    for row_index, raw_row in enumerate(rows):
        row = _exact_keys(raw_row, _SPRITE_ROW_KEYS, label=f"sprite row {row_index}")
        name = row.get("name")
        group = row.get("group")
        if not isinstance(name, str) or not isinstance(group, str):
            raise SpriteGroupExtractionError(f"Sprite row {row_index} has invalid names")
        if group not in _HORSE_ARCHER_GROUPS:
            raise SpriteGroupExtractionError(f"Unexpected sprite group: {group}")
        loader = LOADER_GROUP_TABLE[group]
        parsed_slot = parse_loader_frame_name(name, group, loader.dash_format)
        if parsed_slot is None:
            raise SpriteGroupExtractionError(f"Sprite name does not encode its slot: {name}")
        slot_index = _strict_int(row.get("slot_index"), label=f"{name} slot")
        is_alt = row.get("is_alt")
        if type(is_alt) is not bool or parsed_slot != FrameSlot(slot_index, is_alt):
            raise SpriteGroupExtractionError(f"Sprite slot fields disagree with name: {name}")
        path_id = _strict_int(row.get("path_id"), label=f"{name} PathID", minimum=1)
        if (
            name in names_seen
            or name.casefold() in casefold_names
            or path_id in path_ids_seen
            or parsed_slot in slots_seen[group]
        ):
            raise SpriteGroupExtractionError(f"Duplicate sprite identity: {name}")
        names_seen.add(name)
        casefold_names.add(name.casefold())
        path_ids_seen.add(path_id)
        slots_seen[group].add(parsed_slot)
        actual_order.append(
            (_HORSE_ARCHER_GROUPS.index(group), slot_index, is_alt, name)
        )

        width = _integral_dimension(row.get("width"), label=f"{name} width")
        height = _integral_dimension(row.get("height"), label=f"{name} height")
        for field in (
            "rect_x",
            "rect_y",
            "offset_x",
            "offset_y",
            "pivot_x",
            "pivot_y",
            "pixels_per_unit",
        ):
            _number_value(row.get(field), label=f"{name} {field}")
        if (
            _strict_int(
                row.get("texture_path_id"),
                label=f"{name} texture PathID",
                minimum=1,
            )
            != int(manifest["textures"][0]["main"]["path_id"])
            or row.get("texture_name") != "body12Sprites"
            or _strict_int(
                row.get("alpha_texture_path_id"),
                label=f"{name} alpha texture PathID",
            )
            != 0
            or _strict_int(row.get("settings_raw"), label=f"{name} settingsRaw")
            != 64
            or _number_value(
                row.get("downscale_multiplier"),
                label=f"{name} downscale multiplier",
            )
            != 1.0
        ):
            raise SpriteGroupExtractionError(f"Sprite packing contract differs: {name}")
        render_data = _exact_keys(
            row.get("render_data"),
            _RENDER_DATA_KEYS,
            label=f"{name} render data",
        )
        if (
            render_data.get("settings_raw") != 64
            or render_data.get("downscale_multiplier") != 1.0
        ):
            raise SpriteGroupExtractionError(f"Render-data packing differs: {name}")

        raw_relative = f"objects/{group}/{path_id}_{name}.sprite.bin"
        _verify_binary_reference(
            root,
            row.get("serialized_object"),
            expected_path=raw_relative,
            label=f"{name} serialized Sprite",
        )
        references.add(raw_relative)
        main_relative = f"sprites/{group}/main/{name}.png"
        projected_relative = (
            f"sprites/{group}/mask_projected/{name}_m_projected.png"
        )
        effective_relative = f"sprites/{group}/mask_effective/{name}_m.png"
        main_image = _verify_png(
            root,
            row.get("main_image"),
            expected_path=main_relative,
            expected_size=(width, height),
            label=f"{name} main image",
        )
        projected_image = _verify_png(
            root,
            row.get("projected_mask_image"),
            expected_path=projected_relative,
            expected_size=(width, height),
            label=f"{name} projected mask",
        )
        effective_image = _verify_png(
            root,
            row.get("effective_mask_image"),
            expected_path=effective_relative,
            expected_size=(width, height),
            label=f"{name} effective mask",
        )
        expected_effective = _effective_mask(main_image, projected_image)
        if effective_image.tobytes() != expected_effective.tobytes():
            raise SpriteGroupExtractionError(
                f"Effective mask leaks outside Sprite.image alpha or differs: {name}"
            )
        main_image.close()
        projected_image.close()
        effective_image.close()
        expected_effective.close()
        references.update((main_relative, projected_relative, effective_relative))

    if actual_order != sorted(actual_order):
        raise SpriteGroupExtractionError("Sprite rows are not in canonical loader order")

    manifest_groups = manifest.get("groups")
    if not isinstance(manifest_groups, list) or len(manifest_groups) != 2:
        raise SpriteGroupExtractionError("Manifest does not contain exactly two groups")
    for group_index, group in enumerate(_HORSE_ARCHER_GROUPS):
        summary = _exact_keys(
            manifest_groups[group_index],
            _GROUP_SUMMARY_KEYS,
            label=f"{group} summary",
        )
        if summary.get("group") != group:
            raise SpriteGroupExtractionError("Manifest group order differs")
        group_rows = [row for row in rows if row["group"] == group]
        names = [str(row["name"]) for row in group_rows]
        main_indices = [
            int(row["slot_index"])
            for row in group_rows
            if row["is_alt"] is False
        ]
        alt_indices = [
            int(row["slot_index"])
            for row in group_rows
            if row["is_alt"] is True
        ]
        actual = {
            "frame_count": len(group_rows),
            "main_count": len(main_indices),
            "alt_count": len(alt_indices),
            "max_index": max((*main_indices, *alt_indices)),
            "array_size": max((*main_indices, *alt_indices)) + 1,
            "names_sha256": hashlib.sha256(
                "".join(name + "\n" for name in names).encode("utf-8")
            ).hexdigest(),
            "main_slot_runs": _slot_runs(main_indices),
            "alt_slot_runs": _slot_runs(alt_indices),
            "texture_names": sorted({str(row["texture_name"]) for row in group_rows}),
            "texture_path_ids": sorted(
                {int(row["texture_path_id"]) for row in group_rows}
            ),
        }
        contract = _PINNED_GROUP_CONTRACTS[group]
        if actual["texture_names"] != contract["texture_names"]:
            raise SpriteGroupExtractionError(f"Unexpected texture names for {group}")
        if any(summary.get(key) != value for key, value in actual.items()):
            raise SpriteGroupExtractionError(f"Manifest group summary differs: {group}")
        if summary.get("loader") != _loader_metadata(group, LOADER_GROUP_TABLE[group]):
            raise SpriteGroupExtractionError(f"Loader metadata differs: {group}")
        if summary.get("pinned_contract") != contract:
            raise SpriteGroupExtractionError(f"Pinned contract copy differs: {group}")
    return rows, references


def _validate_current_texture_record(record: dict[str, object], role: str) -> None:
    if record.get("name") != _PINNED_TEXTURE_RECORDS[role]["name"]:
        raise SpriteGroupExtractionError(f"Unexpected Horse Archer {role} texture name")
    for field in ("path_id", "width", "height", "stream_size"):
        _strict_int(record.get(field), label=f"{role} texture {field}", minimum=1)
    _strict_int(record.get("stream_offset"), label=f"{role} stream offset", minimum=0)
    _strict_int(record.get("texture_format"), label=f"{role} texture format", minimum=0)
    if record.get("stream_path") != "resources.assets.resS":
        raise SpriteGroupExtractionError(f"Unsupported {role} resource stream")


def _verify_texture_summary(
    root: Path,
    manifest: dict[str, object],
) -> tuple[dict[str, object], set[str]]:
    summaries = manifest.get("textures")
    if not isinstance(summaries, list) or len(summaries) != 1:
        raise SpriteGroupExtractionError(
            "Complete Horse Archer extraction must contain one shared texture pair"
        )
    summary = _exact_keys(
        summaries[0],
        _TEXTURE_SUMMARY_KEYS,
        label="shared Horse Archer texture summary",
    )
    references: set[str] = set()
    for role in ("main", "mask"):
        record = _exact_keys(
            summary.get(role),
            _TEXTURE_RECORD_KEYS,
            label=f"{role} texture record",
        )
        _validate_current_texture_record(record, role)
        path_id = int(record["path_id"])
        name = str(record["name"])
        object_relative = f"objects/textures/{path_id}_{name}.texture2d.bin"
        _verify_binary_reference(
            root,
            summary.get(f"{role}_serialized_object"),
            expected_path=object_relative,
            label=f"{role} serialized Texture2D",
        )
        references.add(object_relative)
        stream_relative = f"streams/{path_id}_{name}.stream.bin"
        stream_path, stream_metadata = _file_entry(
            root,
            summary.get(f"{role}_stream"),
            expected_path=stream_relative,
            expected_keys=_STREAM_KEYS,
            label=f"{role} Texture2D stream",
        )
        if (
            stream_metadata.get("source_file") != record["stream_path"]
            or stream_metadata.get("source_offset") != record["stream_offset"]
            or stream_path.stat().st_size != record["stream_size"]
        ):
            raise SpriteGroupExtractionError(f"{role} stream provenance differs")
        references.add(stream_relative)
        atlas_relative = f"atlases/{name}.png"
        decoded = _verify_png(
            root,
            summary.get(f"{role}_decoded"),
            expected_path=atlas_relative,
            expected_size=(int(record["width"]), int(record["height"])),
            label=f"decoded {role} atlas",
        )
        decoded.close()
        references.add(atlas_relative)
    return summary, references


def _verify_canonical_identity(
    config: BuilderConfig,
    match: BuildMatch,
    root: Path,
    manifest: dict[str, object],
    rows: list[dict[str, object]],
    texture_summary: dict[str, object],
) -> None:
    asset_path = (config.target.data_dir / "resources.assets").resolve(strict=True)
    if asset_path.parent != config.target.data_dir.resolve():
        raise SpriteGroupExtractionError("Canonical target resources.assets moved")
    stream_path = (asset_path.parent / "resources.assets.resS").resolve(strict=True)
    if stream_path.parent != asset_path.parent:
        raise SpriteGroupExtractionError("Canonical target resource stream moved")
    _assert_input_file(
        asset_path,
        relative_path="resources.assets",
        match=match,
        side="target",
    )
    _assert_input_file(
        stream_path,
        relative_path="resources.assets.resS",
        match=match,
        side="target",
    )

    UnityPy = _import_unitypy()
    environment = load_unity_asset(asset_path, unitypy=UnityPy)
    objects = tuple(environment.objects)
    object_counts = {
        type_name: sum(obj.type.name == type_name for obj in objects)
        for type_name in sorted({obj.type.name for obj in objects})
    }
    if object_counts != manifest.get("unity_object_counts"):
        raise SpriteGroupExtractionError("Canonical Unity object counts differ")
    if (
        sum(obj.type.name == "SpriteAtlas" for obj in objects)
        != manifest.get("sprite_atlas_object_count")
        or sum(obj.type.name == "AnimationClip" for obj in objects)
        != manifest.get("animation_clip_object_count")
    ):
        raise SpriteGroupExtractionError(
            "Canonical resources.assets animation-object counts differ"
        )
    by_id: dict[int, object] = {}
    for obj in objects:
        if obj.path_id in by_id:
            raise SpriteGroupExtractionError(
                f"Duplicate canonical Unity PathID: {obj.path_id}"
            )
        by_id[obj.path_id] = obj
    role_ids: dict[str, int] = {}
    for role in ("main", "mask"):
        expected_name = _PINNED_TEXTURE_RECORDS[role]["name"]
        candidates = [obj for obj in objects if obj.type.name == "Texture2D"
                      and obj.read_typetree().get("m_Name") == expected_name]
        if len(candidates) != 1:
            raise SpriteGroupExtractionError(f"Missing/ambiguous current texture: {expected_name}")
        role_ids[role] = candidates[0].path_id
    texture_objects = {path_id: by_id[path_id] for path_id in role_ids.values()}
    if any(
        obj is None or obj.type.name != "Texture2D"
        for obj in texture_objects.values()
    ):
        raise SpriteGroupExtractionError("Canonical Horse Archer Texture2D is missing")
    texture_trees = {
        path_id: obj.read_typetree() for path_id, obj in texture_objects.items()
    }
    texture_records = {
        path_id: texture_from_tree(path_id, tree)
        for path_id, tree in texture_trees.items()
    }
    texture_names = {
        path_id: record.name for path_id, record in texture_records.items()
    }

    decoded_images: dict[str, Image.Image] = {}
    for role, path_id in role_ids.items():
        obj = texture_objects[path_id]
        record = texture_records[path_id]
        if asdict(record) != texture_summary.get(role):
            raise SpriteGroupExtractionError(
                f"Canonical {role} Texture2D metadata differs"
            )
        raw_metadata = _exact_keys(
            texture_summary.get(f"{role}_serialized_object"),
            _SERIALIZED_KEYS,
            label=f"canonical {role} Texture2D object metadata",
        )
        if _sha256_bytes(obj.get_raw_data()) != raw_metadata.get("sha256"):
            raise SpriteGroupExtractionError(
                f"Extracted {role} Texture2D object differs from canonical bytes"
            )
        stream_metadata = _exact_keys(
            texture_summary.get(f"{role}_stream"),
            _STREAM_KEYS,
            label=f"canonical {role} stream metadata",
        )
        canonical_stream_hash = hash_stream_payload(
            stream_path,
            record.stream_offset,
            record.stream_size,
        )
        if canonical_stream_hash != stream_metadata.get("sha256"):
            raise SpriteGroupExtractionError(
                f"Extracted {role} stream slice differs from canonical bytes"
            )
        image = obj.read().image.convert("RGBA")
        decoded_metadata = _exact_keys(
            texture_summary.get(f"{role}_decoded"),
            _IMAGE_KEYS,
            label=f"canonical decoded {role} atlas metadata",
        )
        if (
            image.size != (record.width, record.height)
            or _sha256_bytes(image.tobytes()) != decoded_metadata.get("rgba_sha256")
        ):
            raise SpriteGroupExtractionError(
                f"Decoded {role} atlas differs from canonical Texture2D"
            )
        decoded_images[role] = image

    # Prove the complete selected cohort against the current asset file, not
    # against the frame count or names of one historical game release.
    canonical_sprites: set[tuple[int, str]] = set()
    for obj in objects:
        if obj.type.name != "Sprite":
            continue
        name = str(obj.read_typetree().get("m_Name", ""))
        if any(parse_loader_frame_name(name, group, LOADER_GROUP_TABLE[group].dash_format)
               is not None for group in _HORSE_ARCHER_GROUPS):
            canonical_sprites.add((obj.path_id, name))
    if canonical_sprites != {(int(row["path_id"]), str(row["name"])) for row in rows}:
        raise SpriteGroupExtractionError("Extracted cohort differs from current complete sprite groups")
    mask_image = decoded_images["mask"]
    for row_number, row in enumerate(rows):
        name = str(row["name"])
        path_id = int(row["path_id"])
        obj = by_id.get(path_id)
        if obj is None or obj.type.name != "Sprite":
            raise SpriteGroupExtractionError(
                f"Canonical Sprite PathID is missing for {name}: {path_id}"
            )
        tree = obj.read_typetree()
        record = sprite_from_tree(path_id, tree, texture_names)
        flattened = asdict(record)
        if any(row.get(key) != value for key, value in flattened.items()):
            raise SpriteGroupExtractionError(
                f"Flattened canonical Sprite metadata differs for {name}"
            )
        if row.get("render_data") != _sprite_render_metadata(tree, name=name):
            raise SpriteGroupExtractionError(
                f"Canonical tight-mesh render metadata differs for {name}"
            )
        raw_metadata = _exact_keys(
            row.get("serialized_object"),
            _SERIALIZED_KEYS,
            label=f"canonical {name} serialized metadata",
        )
        if _sha256_bytes(obj.get_raw_data()) != raw_metadata.get("sha256"):
            raise SpriteGroupExtractionError(
                f"Extracted raw Sprite differs from canonical bytes: {name}"
            )
        size = (
            _integral_dimension(row.get("width"), label=f"{name} width"),
            _integral_dimension(row.get("height"), label=f"{name} height"),
        )
        canonical_main = _decode_sprite_image(obj, name=name, size=size)
        main_metadata = _exact_keys(
            row.get("main_image"),
            _IMAGE_KEYS,
            label=f"canonical {name} main image metadata",
        )
        if _sha256_bytes(canonical_main.tobytes()) != main_metadata.get("rgba_sha256"):
            raise SpriteGroupExtractionError(
                f"Exported main PNG differs from canonical Sprite.image: {name}"
            )
        assert_mask_projectable(record.settings_raw, record.name)
        canonical_projected = crop_mask_for_sprite(
            mask_image,
            rect_x=record.rect_x,
            rect_y=record.rect_y,
            logical_size=size,
            main_atlas_size=(
                texture_records[role_ids["main"]].width,
                texture_records[role_ids["main"]].height,
            ),
        )
        projected_metadata = _exact_keys(
            row.get("projected_mask_image"),
            _IMAGE_KEYS,
            label=f"canonical {name} projected-mask metadata",
        )
        if (
            _sha256_bytes(canonical_projected.tobytes())
            != projected_metadata.get("rgba_sha256")
        ):
            raise SpriteGroupExtractionError(
                f"Projected mask differs from canonical atlas: {name}"
            )
        canonical_effective = _effective_mask(canonical_main, canonical_projected)
        effective_metadata = _exact_keys(
            row.get("effective_mask_image"),
            _IMAGE_KEYS,
            label=f"canonical {name} effective-mask metadata",
        )
        if (
            _sha256_bytes(canonical_effective.tobytes())
            != effective_metadata.get("rgba_sha256")
        ):
            raise SpriteGroupExtractionError(
                f"Effective mask differs from canonical main/mask pair: {name}"
            )
        canonical_main.close()
        canonical_projected.close()
        canonical_effective.close()
        if row_number and row_number % 256 == 0:
            gc.collect()

    for image in decoded_images.values():
        image.close()
    del environment
    del objects
    gc.collect()
    _assert_input_file(
        asset_path,
        relative_path="resources.assets",
        match=match,
        side="target",
    )
    _assert_input_file(
        stream_path,
        relative_path="resources.assets.resS",
        match=match,
        side="target",
    )
    if manifest.get("toolchain") != _toolchain_metadata(config):
        raise SpriteGroupExtractionError(
            "Extractor source or toolchain changed during verification"
        )
    if manifest.get("source_absence_proof") != _source_absence_proof(config, match):
        raise SpriteGroupExtractionError(
            "Canonical SH1DE source-absence proof differs"
        )


def verify_sprite_group_extraction(
    config: BuilderConfig,
    match: BuildMatch,
    *,
    root: Path,
) -> dict[str, object]:
    extraction_root = _existing_extraction_root(config, root)
    files, directories = _scan_extraction_tree(extraction_root)
    manifest_path = files.get("manifest.json")
    files_index_path = files.get("files.jsonl")
    if manifest_path is None or files_index_path is None:
        raise SpriteGroupExtractionError(
            "Extraction root lacks manifest.json or files.jsonl"
        )
    manifest = _strict_json_object(manifest_path)
    canonical_manifest = (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    if manifest_path.read_text(encoding="utf-8") != canonical_manifest:
        raise SpriteGroupExtractionError("Extraction manifest is not canonical JSON")
    _verify_manifest_header(config, match, manifest)
    ledger = _verify_payload_ledger(
        extraction_root,
        files,
        directories,
        manifest,
    )
    texture_summary, texture_references = _verify_texture_summary(
        extraction_root,
        manifest,
    )
    rows, sprite_references = _verify_sprite_rows(extraction_root, manifest)
    references = sprite_references | texture_references
    if references != set(ledger):
        raise SpriteGroupExtractionError(
            "Payload references are not bijective with the exact ledger: "
            f"orphan={sorted(set(ledger)-references)!r} "
            f"unindexed={sorted(references-set(ledger))!r}"
        )
    _verify_canonical_identity(
        config,
        match,
        extraction_root,
        manifest,
        rows,
        texture_summary,
    )
    return {
        "schema_version": 1,
        "kind": "stronghold_europe_private_sprite_group_verification_v1",
        "ok": True,
        "verification_stages": {
            "self_consistency": "VERIFIED",
            "canonical_identity": "VERIFIED",
        },
        "source_build_id": match.source_id,
        "target_build_id": match.target_id,
        "groups": list(_HORSE_ARCHER_GROUPS),
        "sprite_count": len(rows),
        "payload_file_count": len(ledger),
        "total_file_count": len(files),
        "payload_files_sha256": manifest["payload_files_sha256"],
        "sprite_index_sha256": manifest["sprite_index"]["sha256"],
        "files_index_sha256": manifest["files_index"]["sha256"],
        "toolchain": manifest["toolchain"],
        "loader_contract": manifest["loader_contract"],
        "source_absence_proof": manifest["source_absence_proof"],
    }


def extract_sprite_groups(
    config: BuilderConfig,
    match: BuildMatch,
    *,
    side: str,
    groups: Sequence[str],
    output: Path,
) -> Path:
    selected_groups = _validate_groups(groups)
    if side not in {"source", "target"}:
        raise SpriteGroupExtractionError(f"Unsupported extraction side: {side!r}")
    if side != "target" or any(
        _PINNED_GROUP_CONTRACTS[group]["mapping_relation"] != "TARGET_EXCLUSIVE"
        for group in selected_groups
    ):
        raise SpriteGroupExtractionError(
            "The pinned Horse Archer groups are target-exclusive and must be "
            "extracted from SHCDE"
        )
    if any(LOADER_GROUP_TABLE[group].plain_shader for group in selected_groups):
        raise SpriteGroupExtractionError(
            "The pinned Horse Archer extraction requires team-mask loader groups"
        )
    output_path = _safe_output_path(config, output)
    installation = config.source if side == "source" else config.target
    asset_path = (installation.data_dir / "resources.assets").resolve(strict=True)
    if asset_path.parent != installation.data_dir.resolve():
        raise SpriteGroupExtractionError(
            f"Canonical resources.assets path changed: {asset_path}"
        )
    _assert_input_file(
        asset_path,
        relative_path="resources.assets",
        match=match,
        side=side,
    )
    toolchain_before = _toolchain_metadata(config)
    loader_contract = _loader_contract_metadata(config)
    source_absence = _source_absence_proof(config, match)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{output_path.name}.extract-", dir=output_path.parent)
    ).resolve()
    if temporary.parent != output_path.parent.resolve():
        raise SpriteGroupExtractionError("Temporary extraction path escaped its parent")

    try:
        UnityPy = _import_unitypy()
        environment = load_unity_asset(asset_path, unitypy=UnityPy)
        objects = tuple(environment.objects)
        by_id = {obj.path_id: obj for obj in objects}
        texture_objects = {
            obj.path_id: obj for obj in objects if obj.type.name == "Texture2D"
        }
        texture_trees = {
            path_id: obj.read_typetree() for path_id, obj in texture_objects.items()
        }
        texture_records = {
            path_id: texture_from_tree(path_id, tree)
            for path_id, tree in texture_trees.items()
        }
        texture_names = {
            path_id: record.name for path_id, record in texture_records.items()
        }
        textures_by_name: dict[str, object] = {}
        texture_name_keys: dict[str, str] = {}
        for path_id, record in texture_records.items():
            key = record.name.casefold()
            prior = texture_name_keys.get(key)
            if prior is not None:
                raise SpriteGroupExtractionError(
                    f"Case-insensitive Texture2D name collision: "
                    f"{prior!r} and {record.name!r}"
                )
            texture_name_keys[key] = record.name
            textures_by_name[record.name] = texture_objects[path_id]

        selected: list[dict[str, Any]] = []
        names_seen: set[str] = set()
        slots_seen: dict[str, set[FrameSlot]] = {
            group: set() for group in selected_groups
        }
        for obj in objects:
            if obj.type.name != "Sprite":
                continue
            tree = obj.read_typetree()
            name = str(tree.get("m_Name", ""))
            matches: list[tuple[str, FrameSlot]] = []
            for group in selected_groups:
                loader = LOADER_GROUP_TABLE[group]
                slot = parse_loader_frame_name(name, group, loader.dash_format)
                if slot is not None:
                    matches.append((group, slot))
            if not matches:
                continue
            if len(matches) != 1:
                raise SpriteGroupExtractionError(
                    f"Sprite matches multiple selected loader groups: {name}"
                )
            group, slot = matches[0]
            if name in names_seen or slot in slots_seen[group]:
                raise SpriteGroupExtractionError(
                    f"Duplicate selected sprite name or loader slot: {name}"
                )
            names_seen.add(name)
            slots_seen[group].add(slot)
            record = sprite_from_tree(obj.path_id, tree, texture_names)
            if record.downscale_multiplier != 1.0 or record.alpha_texture_path_id != 0:
                raise SpriteGroupExtractionError(
                    f"Selected sprite packing contract changed: {name}"
                )
            selected.append(
                {
                    "object": obj,
                    "tree": tree,
                    "record": record,
                    "group": group,
                    "slot": slot,
                }
            )

        selected.sort(
            key=lambda item: (
                selected_groups.index(item["group"]),
                item["slot"].index,
                item["slot"].is_alt,
                item["record"].name,
            )
        )
        if not selected:
            raise SpriteGroupExtractionError("No selected sprites were found")
        if any(not slots_seen[group] for group in selected_groups):
            missing = [group for group in selected_groups if not slots_seen[group]]
            raise SpriteGroupExtractionError(
                f"Selected loader groups have no sprites: {missing}"
            )

        sprite_rows: dict[str, dict[str, object]] = {}
        for item in selected:
            record = item["record"]
            group = item["group"]
            raw_path = (
                temporary
                / "objects"
                / group
                / f"{record.path_id}_{record.name}.sprite.bin"
            )
            raw_meta = _write_bytes(raw_path, item["object"].get_raw_data())
            sprite_rows[record.name] = {
                **asdict(record),
                "group": group,
                "slot_index": item["slot"].index,
                "is_alt": item["slot"].is_alt,
                "render_data": _sprite_render_metadata(
                    item["tree"],
                    name=record.name,
                ),
                "serialized_object": {
                    "path": raw_path.relative_to(temporary).as_posix(),
                    **raw_meta,
                },
            }

        referenced_textures = sorted(
            {item["record"].texture_path_id for item in selected}
        )
        texture_summaries: list[dict[str, object]] = []
        referenced_streams: dict[str, Path] = {}
        for texture_path_id in referenced_textures:
            texture_obj = texture_objects.get(texture_path_id)
            main_tree = texture_trees.get(texture_path_id)
            main_record = texture_records.get(texture_path_id)
            if texture_obj is None or main_tree is None or main_record is None:
                raise SpriteGroupExtractionError(
                    f"Selected sprite texture is missing: PathID {texture_path_id}"
                )
            mask_name = main_record.name + "_m"
            mask_obj = textures_by_name.get(mask_name)
            if mask_obj is None:
                raise SpriteGroupExtractionError(
                    f"Required team-mask texture is missing: {mask_name}"
                )
            mask_tree = mask_obj.read_typetree()
            mask_record = texture_from_tree(mask_obj.path_id, mask_tree)
            for record in (main_record, mask_record):
                if _SAFE_ASSET_NAME_RE.fullmatch(record.name) is None:
                    raise SpriteGroupExtractionError(
                        f"Unsafe selected Texture2D name: {record.name!r}"
                    )

            texture_summary: dict[str, object] = {
                "main": asdict(main_record),
                "mask": asdict(mask_record),
            }
            for role, obj, tree, record in (
                ("main", texture_obj, main_tree, main_record),
                ("mask", mask_obj, mask_tree, mask_record),
            ):
                raw_object_path = (
                    temporary
                    / "objects"
                    / "textures"
                    / f"{record.path_id}_{record.name}.texture2d.bin"
                )
                raw_object_meta = _write_bytes(raw_object_path, obj.get_raw_data())
                stream_name = Path(record.stream_path.replace("\\", "/")).name
                stream_source = (asset_path.parent / stream_name).resolve(strict=True)
                if stream_source.parent != asset_path.parent:
                    raise SpriteGroupExtractionError(
                        f"Texture stream escaped canonical asset directory: {stream_name}"
                    )
                prior_stream = referenced_streams.get(stream_name.casefold())
                if prior_stream is not None and prior_stream != stream_source:
                    raise SpriteGroupExtractionError(
                        f"Case-insensitive texture-stream collision: {stream_name}"
                    )
                referenced_streams[stream_name.casefold()] = stream_source
                stream_path = (
                    temporary
                    / "streams"
                    / f"{record.path_id}_{record.name}.stream.bin"
                )
                stream_meta = _copy_stream_slice(
                    stream_source,
                    stream_path,
                    record.stream_offset,
                    record.stream_size,
                )
                texture_summary[f"{role}_serialized_object"] = {
                    "path": raw_object_path.relative_to(temporary).as_posix(),
                    **raw_object_meta,
                }
                texture_summary[f"{role}_stream"] = {
                    "source_file": stream_name,
                    "source_offset": record.stream_offset,
                    "path": stream_path.relative_to(temporary).as_posix(),
                    **stream_meta,
                }

            main_texture = texture_obj.read()
            main_image = main_texture.image.convert("RGBA")
            main_atlas_path = temporary / "atlases" / f"{main_record.name}.png"
            texture_summary["main_decoded"] = {
                "path": main_atlas_path.relative_to(temporary).as_posix(),
                **_save_png(main_atlas_path, main_image),
            }
            del main_image
            gc.collect()
            texture_items = [
                item
                for item in selected
                if item["record"].texture_path_id == texture_path_id
            ]
            for item in texture_items:
                record = item["record"]
                logical_size = (round(record.width), round(record.height))
                main_crop = _decode_sprite_image(
                    item["object"],
                    name=record.name,
                    size=logical_size,
                )
                main_path = (
                    temporary
                    / "sprites"
                    / item["group"]
                    / "main"
                    / f"{record.name}.png"
                )
                sprite_rows[record.name]["main_image"] = {
                    "path": main_path.relative_to(temporary).as_posix(),
                    **_save_png(main_path, main_crop),
                }
            del main_texture
            gc.collect()

            mask_image = mask_obj.read().image.convert("RGBA")
            mask_atlas_path = temporary / "atlases" / f"{mask_record.name}.png"
            texture_summary["mask_decoded"] = {
                "path": mask_atlas_path.relative_to(temporary).as_posix(),
                **_save_png(mask_atlas_path, mask_image),
            }
            for item in texture_items:
                record = item["record"]
                logical_size = (round(record.width), round(record.height))
                assert_mask_projectable(record.settings_raw, record.name)
                projected_mask = crop_mask_for_sprite(
                    mask_image,
                    rect_x=record.rect_x,
                    rect_y=record.rect_y,
                    logical_size=logical_size,
                    main_atlas_size=(main_record.width, main_record.height),
                )
                projected_path = (
                    temporary
                    / "sprites"
                    / item["group"]
                    / "mask_projected"
                    / f"{record.name}_m_projected.png"
                )
                main_relative = str(
                    sprite_rows[record.name]["main_image"]["path"]
                )
                with Image.open(temporary / main_relative) as serialized_main:
                    effective_mask = _effective_mask(
                        serialized_main.convert("RGBA"), projected_mask
                    )
                effective_path = (
                    temporary
                    / "sprites"
                    / item["group"]
                    / "mask_effective"
                    / f"{record.name}_m.png"
                )
                sprite_rows[record.name]["projected_mask_image"] = {
                    "path": projected_path.relative_to(temporary).as_posix(),
                    **_save_png(projected_path, projected_mask),
                }
                sprite_rows[record.name]["effective_mask_image"] = {
                    "path": effective_path.relative_to(temporary).as_posix(),
                    **_save_png(effective_path, effective_mask),
                }
            del mask_image
            gc.collect()
            texture_summaries.append(texture_summary)

        ordered_rows = [sprite_rows[item["record"].name] for item in selected]
        sprite_index = temporary / "sprites.jsonl"
        _write_jsonl(sprite_index, ordered_rows)

        group_summaries: list[dict[str, object]] = []
        for group in selected_groups:
            rows = [row for row in ordered_rows if row["group"] == group]
            names = [str(row["name"]) for row in rows]
            main_indices = [
                int(row["slot_index"]) for row in rows if row["is_alt"] is False
            ]
            alt_indices = [
                int(row["slot_index"]) for row in rows if row["is_alt"] is True
            ]
            max_index = max((*main_indices, *alt_indices))
            summary: dict[str, object] = {
                "group": group,
                "loader": _loader_metadata(group, LOADER_GROUP_TABLE[group]),
                "frame_count": len(rows),
                "main_count": len(main_indices),
                "alt_count": len(alt_indices),
                "max_index": max_index,
                "array_size": max_index + 1,
                "names_sha256": hashlib.sha256(
                    "".join(name + "\n" for name in names).encode("utf-8")
                ).hexdigest(),
                "main_slot_runs": _slot_runs(main_indices),
                "alt_slot_runs": _slot_runs(alt_indices),
                "texture_names": sorted(
                    {str(row["texture_name"]) for row in rows}
                ),
                "texture_path_ids": sorted(
                    {int(row["texture_path_id"]) for row in rows}
                ),
            }
            contract = _PINNED_GROUP_CONTRACTS[group]
            if summary["texture_names"] != contract["texture_names"]:
                raise SpriteGroupExtractionError(f"Unexpected extraction textures for {group}")
            expected_mask = textures_by_name.get(str(contract["mask_texture_name"]))
            if expected_mask is None:
                raise SpriteGroupExtractionError(f"Required team-mask texture is missing for {group}")
            summary["pinned_contract"] = contract
            group_summaries.append(summary)

        payload_files, payload_digest = _payload_file_index(temporary)
        files_index = temporary / "files.jsonl"
        _write_jsonl(files_index, payload_files)
        if _toolchain_metadata(config) != toolchain_before:
            raise SpriteGroupExtractionError(
                "Extractor source or toolchain changed during extraction"
            )
        _assert_input_file(
            asset_path,
            relative_path="resources.assets",
            match=match,
            side=side,
        )
        for stream_path in referenced_streams.values():
            _assert_input_file(
                stream_path,
                relative_path=stream_path.name,
                match=match,
                side=side,
            )
        manifest = {
            "schema_version": 2,
            "kind": "stronghold_europe_private_sprite_group_extraction_v2",
            "side": side,
            "build_id": match.source_id if side == "source" else match.target_id,
            "asset_path": "resources.assets",
            "toolchain": toolchain_before,
            "loader_contract": loader_contract,
            "input_fingerprints": _input_fingerprints(match, side),
            "source_absence_proof": source_absence,
            "unity_object_counts": {
                type_name: sum(obj.type.name == type_name for obj in objects)
                for type_name in sorted({obj.type.name for obj in objects})
            },
            "sprite_atlas_object_count": sum(
                obj.type.name == "SpriteAtlas" for obj in objects
            ),
            "animation_clip_object_count": sum(
                obj.type.name == "AnimationClip" for obj in objects
            ),
            "unity_object_scope": _UNITY_OBJECT_SCOPE,
            "mask_export_contract": _MASK_EXPORT_CONTRACT,
            "groups": group_summaries,
            "textures": texture_summaries,
            "sprite_index": {
                "path": sprite_index.relative_to(temporary).as_posix(),
                "record_count": len(ordered_rows),
                "size": sprite_index.stat().st_size,
                "sha256": sha256_file(sprite_index),
            },
            "payload_file_count": len(payload_files),
            "payload_files_sha256": payload_digest,
            "files_index": {
                "path": files_index.relative_to(temporary).as_posix(),
                "record_count": len(payload_files),
                "size": files_index.stat().st_size,
                "sha256": sha256_file(files_index),
            },
        }
        manifest_path = temporary / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )

        del environment
        del objects
        gc.collect()
        if output_path.exists():
            raise SpriteGroupExtractionError(
                f"Extraction output appeared during publication: {output_path}"
            )
        temporary.replace(output_path)
        return output_path
    except BaseException:
        if temporary.is_dir() and temporary.parent == output_path.parent.resolve():
            try:
                shutil.rmtree(temporary)
            except OSError:
                pass
        raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Privately extract complete loader sprite groups from one pinned "
            "Stronghold DE resources.assets file"
        )
    )
    commands = parser.add_subparsers(dest="command", required=True)
    extract = commands.add_parser("extract", help="create a new private V2 extraction")
    extract.add_argument(
        "--config",
        type=Path,
        default=Path("config/installations.local.toml"),
    )
    extract.add_argument("--side", choices=("source", "target"), required=True)
    extract.add_argument("--groups", nargs="+", required=True)
    extract.add_argument("--out", type=Path, required=True)
    verify = commands.add_parser(
        "verify",
        help="prove V2 self-consistency and canonical Unity identity",
    )
    verify.add_argument(
        "--config",
        type=Path,
        default=Path("config/installations.local.toml"),
    )
    verify.add_argument("--root", type=Path, required=True)
    verify.add_argument("--report", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    config = load_config(arguments.config)
    match = verify_supported_builds(
        config, config.project_root / "config" / "supported-builds.json"
    )
    if arguments.command == "extract":
        output = extract_sprite_groups(
            config,
            match,
            side=arguments.side,
            groups=arguments.groups,
            output=arguments.out,
        )
        print(output)
        return 0
    if arguments.command != "verify":
        raise SpriteGroupExtractionError(
            f"Unsupported extraction command: {arguments.command!r}"
        )
    report = verify_sprite_group_extraction(
        config,
        match,
        root=arguments.root,
    )
    if arguments.report is not None:
        report_path = _safe_output_path(config, arguments.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        print(report_path)
    else:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

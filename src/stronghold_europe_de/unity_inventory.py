from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import gzip
from importlib.metadata import version
import json
import ntpath
from pathlib import Path
from typing import Any, Iterable


class AssetDependencyError(RuntimeError):
    """Raised when the optional Unity asset toolchain is unavailable."""


class UnityAssetLoadError(AssetDependencyError):
    """Raised when a Unity asset or one of its streams is not provenance-safe."""


@dataclass(frozen=True)
class TextureRecord:
    path_id: int
    name: str
    width: int
    height: int
    texture_format: int
    stream_path: str
    stream_offset: int
    stream_size: int


@dataclass(frozen=True)
class SpriteRecord:
    path_id: int
    name: str
    rect_x: float
    rect_y: float
    width: float
    height: float
    offset_x: float
    offset_y: float
    pivot_x: float
    pivot_y: float
    pixels_per_unit: float
    texture_path_id: int
    texture_name: str
    alpha_texture_path_id: int
    settings_raw: int
    downscale_multiplier: float


@dataclass(frozen=True)
class AudioRecord:
    path_id: int
    name: str
    channels: int
    frequency: int
    bits_per_sample: int
    length_seconds: float
    compression_format: int
    resource_path: str
    resource_offset: int
    resource_size: int


def _number(mapping: dict[str, Any], key: str, default: float = 0.0) -> float:
    value = mapping.get(key, default)
    return float(value if value is not None else default)


def texture_from_tree(path_id: int, tree: dict[str, Any]) -> TextureRecord:
    stream = tree.get("m_StreamData") or {}
    return TextureRecord(
        path_id=path_id,
        name=str(tree.get("m_Name", "")),
        width=int(tree.get("m_Width", 0)),
        height=int(tree.get("m_Height", 0)),
        texture_format=int(tree.get("m_TextureFormat", -1)),
        stream_path=str(stream.get("path", "")),
        stream_offset=int(stream.get("offset", 0)),
        stream_size=int(stream.get("size", 0)),
    )


def sprite_from_tree(
    path_id: int,
    tree: dict[str, Any],
    texture_names: dict[int, str],
) -> SpriteRecord:
    rect = tree.get("m_Rect") or {}
    offset = tree.get("m_Offset") or {}
    pivot = tree.get("m_Pivot") or {}
    render_data = tree.get("m_RD") or {}
    texture_pointer = render_data.get("texture") or {}
    alpha_pointer = render_data.get("alphaTexture") or {}
    texture_path_id = int(texture_pointer.get("m_PathID", 0))
    return SpriteRecord(
        path_id=path_id,
        name=str(tree.get("m_Name", "")),
        rect_x=_number(rect, "x"),
        rect_y=_number(rect, "y"),
        width=_number(rect, "width"),
        height=_number(rect, "height"),
        offset_x=_number(offset, "x"),
        offset_y=_number(offset, "y"),
        pivot_x=_number(pivot, "x"),
        pivot_y=_number(pivot, "y"),
        pixels_per_unit=float(tree.get("m_PixelsToUnits", 0.0)),
        texture_path_id=texture_path_id,
        texture_name=texture_names.get(texture_path_id, ""),
        alpha_texture_path_id=int(alpha_pointer.get("m_PathID", 0)),
        settings_raw=int(render_data.get("settingsRaw", 0)),
        downscale_multiplier=float(render_data.get("downscaleMultiplier", 1.0)),
    )


def audio_from_tree(path_id: int, tree: dict[str, Any]) -> AudioRecord:
    resource = tree.get("m_Resource") or {}
    return AudioRecord(
        path_id=path_id,
        name=str(tree.get("m_Name", "")),
        channels=int(tree.get("m_Channels", 0)),
        frequency=int(tree.get("m_Frequency", 0)),
        bits_per_sample=int(tree.get("m_BitsPerSample", 0)),
        length_seconds=float(tree.get("m_Length", 0.0)),
        compression_format=int(tree.get("m_CompressionFormat", -1)),
        resource_path=str(resource.get("m_Source", "")),
        resource_offset=int(resource.get("m_Offset", 0)),
        resource_size=int(resource.get("m_Size", 0)),
    )


def _import_unitypy():
    try:
        import UnityPy
    except ImportError as exc:
        raise AssetDependencyError(
            "UnityPy is required; install the project with the 'assets' extra"
        ) from exc
    return UnityPy


def _resolved_asset_file(asset_path: Path) -> Path:
    """Require a caller-supplied canonical absolute path to one asset file."""

    candidate = Path(asset_path)
    if not candidate.is_absolute():
        raise UnityAssetLoadError(
            f"Unity asset path must be absolute and resolved: {candidate}"
        )
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise UnityAssetLoadError(f"Unity asset does not exist: {candidate}") from exc
    if candidate != resolved:
        raise UnityAssetLoadError(
            f"Unity asset path must already be resolved: {candidate} != {resolved}"
        )
    if not resolved.is_file():
        raise UnityAssetLoadError(f"Unity asset is not a regular file: {resolved}")
    return resolved


def _casefold_unique_paths(paths: Iterable[Path], kind: str) -> dict[str, Path]:
    """Index paths like Unity does, but reject ambiguous case-insensitive names."""

    indexed: dict[str, Path] = {}
    for path in paths:
        key = path.name.casefold()
        prior = indexed.get(key)
        if prior is not None:
            raise UnityAssetLoadError(
                f"Case-insensitive {kind} name collision: {prior.name!r} and "
                f"{path.name!r}"
            )
        indexed[key] = path
    return indexed


_RESOURCE_STREAM_SUFFIXES = (".ress", ".resource")


def _resource_stream_basename(raw_name: str, *, flat: bool) -> str:
    """Return one supported external-resource basename without aliasing it."""

    if not isinstance(raw_name, str) or not raw_name or "\x00" in raw_name:
        raise UnityAssetLoadError(
            f"Invalid Unity resource-stream path: {raw_name!r}"
        )
    normalized = raw_name.replace("\\", "/")
    parts = tuple(part for part in normalized.split("/") if part not in ("", "."))
    has_unsafe_location = (
        any(part == ".." for part in parts)
        or normalized.startswith("/")
        or ntpath.isabs(raw_name)
        or (":" in normalized and not normalized.casefold().startswith("archive:/"))
    )
    basename = ntpath.basename(raw_name)
    if (
        not basename
        or has_unsafe_location
        or (flat and basename != raw_name)
        or ":" in basename
        or not basename.casefold().endswith(_RESOURCE_STREAM_SUFFIXES)
    ):
        expected = "flat " if flat else ""
        raise UnityAssetLoadError(
            f"Expected Unity resource stream must be a {expected}*.resS or "
            f"*.resource name: {raw_name!r}"
        )
    return basename


def _resolve_direct_resource_sibling(asset_path: Path, requested: str) -> Path:
    """Resolve exactly one direct resource sibling, rejecting aliases/links."""

    basename = _resource_stream_basename(requested, flat=True)
    directory = asset_path.parent
    try:
        entries = tuple(directory.iterdir())
    except OSError as exc:
        raise UnityAssetLoadError(
            f"Could not enumerate Unity asset directory: {directory}"
        ) from exc
    matches = [entry for entry in entries if entry.name.casefold() == basename.casefold()]
    if len(matches) > 1:
        raise UnityAssetLoadError(
            f"Case-insensitive Unity resource-stream collision for {basename!r}"
        )
    if not matches:
        raise UnityAssetLoadError(
            f"Expected Unity resource stream is missing beside {asset_path.name}: "
            f"{basename}"
        )

    entry = matches[0]
    try:
        resolved = entry.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise UnityAssetLoadError(
            f"Unity resource stream disappeared during resolution: {entry}"
        ) from exc
    if resolved != entry.absolute() or resolved.parent != directory or not resolved.is_file():
        raise UnityAssetLoadError(
            f"Unity resource stream is not a direct non-reparse regular-file sibling: "
            f"{entry}"
        )
    return resolved


def _resolve_local_dependency(asset_directory: Path, requested: str) -> Path:
    """Resolve a Unity dependency below the asset directory without consulting CWD."""

    normalized = requested.replace("\\", "/")
    parts = tuple(part for part in normalized.split("/") if part not in ("", "."))
    if (
        not parts
        or ntpath.isabs(requested)
        or any(part == ".." for part in parts)
        or any(":" in part or "\x00" in part for part in parts)
    ):
        raise UnityAssetLoadError(
            f"Unsafe relative Unity dependency path: {requested!r}"
        )

    current = asset_directory
    for part in parts:
        try:
            children = tuple(current.iterdir())
        except OSError as exc:
            raise UnityAssetLoadError(
                f"Could not enumerate Unity dependency directory: {current}"
            ) from exc
        matches = [child for child in children if child.name.casefold() == part.casefold()]
        if len(matches) > 1:
            raise UnityAssetLoadError(
                f"Case-insensitive Unity dependency collision for {requested!r}"
            )
        if not matches:
            raise UnityAssetLoadError(
                f"Unity dependency is missing beside the selected asset: {requested!r}"
            )
        entry = matches[0]
        try:
            resolved_entry = entry.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise UnityAssetLoadError(
                f"Unity dependency disappeared during resolution: {requested!r}"
            ) from exc
        if resolved_entry != entry.absolute():
            raise UnityAssetLoadError(
                f"Unity dependency crosses a reparse point: {requested!r}"
            )
        current = resolved_entry

    try:
        resolved = current.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise UnityAssetLoadError(
            f"Unity dependency disappeared during resolution: {requested!r}"
        ) from exc
    if asset_directory != resolved.parent and asset_directory not in resolved.parents:
        raise UnityAssetLoadError(
            f"Unity dependency escapes the selected asset directory: {requested!r}"
        )
    if not resolved.is_file():
        raise UnityAssetLoadError(
            f"Unity dependency is not a regular file: {resolved}"
        )
    return resolved


def _guarded_environment_type(environment_type: Any, asset_path: Path) -> Any:
    """Subclass an Environment so lazy dependencies never consult process CWD.

    Installing a bound method on the instance would add an Environment/self
    reference cycle and delay closure of the large ``*.resS`` file handles.
    A tiny per-load subclass adds no such cycle and leaves teardown to UnityPy's
    existing ownership/garbage-collection model.
    """

    asset_directory = asset_path.parent
    try:
        class CwdIndependentEnvironment(environment_type):
            def load_file(
                self,
                file: Any,
                parent: Any = None,
                name: str | None = None,
                is_dependency: bool = False,
            ) -> Any:
                if isinstance(file, str) and not ntpath.isabs(file):
                    file = str(_resolve_local_dependency(asset_directory, file))
                return super().load_file(file, parent, name, is_dependency)

    except TypeError as exc:
        raise UnityAssetLoadError(
            "UnityPy Environment type cannot enforce a CWD-independent dependency guard"
        ) from exc
    return CwdIndependentEnvironment


def _cab_identity(environment: Any, name: str, loaded: Any, path: Path) -> None:
    """Prove that a requested absolute file owns its expected Environment CAB key."""

    if loaded is None:
        raise UnityAssetLoadError(f"UnityPy did not load the requested file: {path}")
    files = getattr(environment, "files", None)
    if not isinstance(files, dict) or files.get(str(path)) is not loaded:
        raise UnityAssetLoadError(
            f"UnityPy file identity does not match the requested absolute path: {path}"
        )
    try:
        registered = environment.get_cab(name)
    except Exception as exc:
        raise UnityAssetLoadError("UnityPy environment exposes no CAB identity lookup") from exc
    if registered is not loaded:
        raise UnityAssetLoadError(
            f"UnityPy CAB identity mismatch for {name!r}: {path}"
        )


def _serialized_resource_references(asset_cab: Any) -> tuple[str, ...]:
    """Discover exact external ``*.resS``/``*.resource`` CAB basenames."""

    objects = getattr(asset_cab, "objects", None)
    if isinstance(objects, dict):
        readers = objects.values()
    elif objects is None:
        readers = ()
    else:
        readers = objects

    references: dict[str, str] = {}
    for reader in readers:
        type_name = getattr(getattr(reader, "type", None), "name", None)
        if type_name not in {"Texture2D", "Mesh", "AudioClip", "VideoClip"}:
            continue
        try:
            tree = reader.read_typetree()
            if type_name in {"Texture2D", "Mesh"}:
                stream = tree.get("m_StreamData") or {}
                raw_size = stream.get("size", 0)
                raw_path = stream.get("path", "")
            elif type_name == "AudioClip":
                stream = tree.get("m_Resource") or {}
                raw_size = stream.get("m_Size", 0)
                raw_path = stream.get("m_Source", "")
            else:
                stream = tree.get("m_ExternalResources") or {}
                raw_size = stream.get("m_Size", 0)
                raw_path = stream.get("m_Source", "")
            if type(raw_size) is not int or raw_size < 0:
                raise ValueError(f"invalid stream size: {raw_size!r}")
            size = raw_size
            if not isinstance(raw_path, str):
                raise TypeError(f"invalid stream path: {raw_path!r}")
        except Exception as exc:
            raise UnityAssetLoadError(
                f"Could not prove {type_name} stream metadata in the selected asset"
            ) from exc
        if size <= 0:
            continue
        basename = _resource_stream_basename(raw_path, flat=False)
        key = basename.casefold()
        prior = references.get(key)
        if prior is not None and prior != basename:
            raise UnityAssetLoadError(
                f"Case-insensitive serialized stream collision: {prior!r} and "
                f"{basename!r}"
            )
        references[key] = basename
    return tuple(references[key] for key in sorted(references))


def load_unity_asset(
    asset_path: Path,
    *,
    unitypy: Any | None = None,
    expected_stream_names: Iterable[str] = (),
) -> Any:
    """Load one serialized Unity asset without CWD-dependent stream provenance.

    UnityPy 1.25.3 checks ``os.getcwd()`` before ``Environment.path`` when a
    lazy relative dependency is loaded and tries several fallback resource
    names.  This loader first opens only the serialized asset, discovers its
    exact external-resource basenames from object metadata, and then registers
    only those direct siblings.  Later relative dependency reads remain under
    a CWD-independent, non-reparse guard.
    """

    asset = _resolved_asset_file(asset_path)
    if unitypy is None:
        unitypy = _import_unitypy()
    environment_type = getattr(unitypy, "Environment", None)
    if environment_type is None:
        raise UnityAssetLoadError("UnityPy exposes no Environment constructor")
    guarded_environment_type = _guarded_environment_type(environment_type, asset)
    try:
        environment = guarded_environment_type(path=str(asset.parent))
    except Exception as exc:
        raise UnityAssetLoadError(
            f"Could not create UnityPy environment for {asset}"
        ) from exc

    try:
        asset_cab = environment.load_file(str(asset), name=str(asset))
    except Exception as exc:
        raise UnityAssetLoadError(f"Could not load Unity asset: {asset}") from exc
    _cab_identity(environment, asset.name, asset_cab, asset)
    cab_name = getattr(asset_cab, "name", None)
    if not isinstance(cab_name, str) or cab_name.casefold() != asset.name.casefold():
        raise UnityAssetLoadError(
            f"Loaded CAB name does not identify the requested asset: "
            f"{cab_name!r} != {asset.name!r}"
        )
    try:
        assets = list(environment.assets)
    except Exception as exc:
        raise UnityAssetLoadError("UnityPy environment exposes no serialized assets") from exc
    if assets != [asset_cab]:
        raise UnityAssetLoadError(
            f"Loaded serialized CAB identity is ambiguous for {asset}: "
            f"count={len(assets)}"
        )

    required: dict[str, str] = {}
    for raw_name in (
        *tuple(expected_stream_names),
        *_serialized_resource_references(asset_cab),
    ):
        name = str(raw_name)
        basename = _resource_stream_basename(name, flat=True)
        key = basename.casefold()
        prior = required.get(key)
        if prior is not None and prior != basename:
            raise UnityAssetLoadError(
                f"Case-insensitive expected stream collision: {prior!r} and "
                f"{basename!r}"
            )
        required[key] = basename

    for key in sorted(required):
        name = required[key]
        stream = _resolve_direct_resource_sibling(asset, name)
        try:
            loaded = environment.load_file(str(stream), name=str(stream))
        except Exception as exc:
            raise UnityAssetLoadError(
                f"Could not load exact Unity resource stream: {stream}"
            ) from exc
        _cab_identity(environment, name, loaded, stream)

    try:
        assets = list(environment.assets)
    except Exception as exc:
        raise UnityAssetLoadError("UnityPy environment exposes no serialized assets") from exc
    if assets != [asset_cab]:
        raise UnityAssetLoadError(
            f"Loaded resource CAB identity is ambiguous for {asset}: "
            f"serialized_count={len(assets)}"
        )
    return environment


def scan_resources_assets(asset_path: Path, role: str) -> dict[str, Any]:
    UnityPy = _import_unitypy()
    environment = load_unity_asset(asset_path, unitypy=UnityPy)
    objects_by_type = Counter(obj.type.name for obj in environment.objects)

    textures: list[TextureRecord] = []
    for obj in environment.objects:
        if obj.type.name == "Texture2D":
            textures.append(texture_from_tree(obj.path_id, obj.read_typetree()))
    textures.sort(key=lambda item: item.path_id)
    texture_names = {item.path_id: item.name for item in textures}

    sprites: list[SpriteRecord] = []
    audio: list[AudioRecord] = []
    for obj in environment.objects:
        if obj.type.name == "Sprite":
            sprites.append(sprite_from_tree(obj.path_id, obj.read_typetree(), texture_names))
        elif obj.type.name == "AudioClip":
            audio.append(audio_from_tree(obj.path_id, obj.read_typetree()))
    sprites.sort(key=lambda item: item.path_id)
    audio.sort(key=lambda item: item.path_id)

    duplicate_names = [
        name for name, count in Counter(item.name for item in sprites).items() if count > 1
    ]
    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "role": role,
        "asset_path": str(asset_path.resolve()),
        "unitypy_version": version("UnityPy"),
        "object_counts": dict(sorted(objects_by_type.items())),
        "duplicate_sprite_names": sorted(duplicate_names),
        "textures": [asdict(item) for item in textures],
        "sprites": [asdict(item) for item in sprites],
        "audio_clips": [asdict(item) for item in audio],
    }


def write_inventory(inventory: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    with gzip.open(temporary, "wt", encoding="utf-8", newline="\n") as stream:
        json.dump(inventory, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        stream.write("\n")
    temporary.replace(output_path)


def read_inventory(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        data = json.load(stream)
    if data.get("schema_version") != 1:
        raise ValueError(f"Unsupported inventory schema: {data.get('schema_version')}")
    return data


def inventory_summary(inventory: dict[str, Any]) -> str:
    return (
        f"role={inventory['role']} "
        f"textures={len(inventory['textures'])} "
        f"sprites={len(inventory['sprites'])} "
        f"audio={len(inventory['audio_clips'])} "
        f"duplicate_sprite_names={len(inventory['duplicate_sprite_names'])}"
    )

"""Verify the *published* BC7 atlas against immutable V2 group cache objects.

The delivered Sprite Catalogue PNG is often decoded/re-encoded relative to the
BC7 atlas source. Do not compare its PNG hash or RGBA digest to an atlas frame.
Use the independently verified shipped bundle/index + immutable group cache
binding, then compare geometry and the Unity pivot metadata.

This module only reads the cache; it neither selects the newest cache object
nor changes a ref, bundle, atlas, or output file.
"""
from __future__ import annotations

from dataclasses import replace
import math
from pathlib import Path
import re
import struct
from typing import Mapping

from .asset_stream_contract import (
    AssetStreamContractError, canonical_group_slug,
)
from .asset_stream_group_cache import (
    CachedAssetStreamGroup, GroupCacheError, frame_bindings_from_atlas,
    load_group_cache_object, parse_group_cache_input,
)
from .release_preflight import (
    ReleasePreflightError, _is_link, _read_json, _sha256_file,
)

SHA = re.compile(r"[0-9a-f]{64}\Z")
REF = re.compile(r"([0-9a-f]{64})\.v1\.json\Z")
MAX_CACHE_REFS = 64
MAX_OBJECT_MANIFEST_BYTES = 512 * 1024
MAX_REF_BYTES = 64 * 1024
EPSILON = 2e-5


class PivotCacheEvidenceError(ValueError):
    """An allegedly published cache artifact cannot be safely verified."""


def _sha(value: object, label: str) -> str:
    if not isinstance(value, str) or SHA.fullmatch(value) is None:
        raise PivotCacheEvidenceError(f"{label} ist kein gültiger SHA-256")
    return value


def _direct_directory(path: Path, root: Path) -> bool:
    """Do not follow a symlink/reparse in any directory below the root."""
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise PivotCacheEvidenceError("Cacheverzeichnis verlässt die Projektwurzel") from exc
    parent = path
    while parent != root:
        if _is_link(parent):
            raise PivotCacheEvidenceError("Cache enthält einen Link/Junction")
        parent = parent.parent
    return path.is_dir()


def locate_published_group(
    project_root: str | Path,
    index_group: Mapping[str, object],
) -> CachedAssetStreamGroup | None:
    """Find exactly the cache object bound to a SHA-256 verified shipped bundle.

    A cache miss is *unknown provenance*, not permission to accept a measured
    pivot. An invalid reference, ambiguous match, or changed artifact fails
    closed rather than falling back to the newest object.
    """
    root = Path(project_root).resolve(strict=True)
    if not isinstance(index_group, Mapping):
        raise PivotCacheEvidenceError("BC7-Bundlegruppe muss ein Objekt sein")
    group = index_group.get("group")
    if not isinstance(group, str) or not group:
        raise PivotCacheEvidenceError("Bundlegruppenname fehlt")
    try:
        slug = canonical_group_slug(group, "bundle group")
    except AssetStreamContractError as exc:
        raise PivotCacheEvidenceError(str(exc)) from exc
    if index_group.get("slug") != slug:
        raise PivotCacheEvidenceError("Bundle-Slug passt nicht zur Gruppe")
    bundle_sha = _sha(index_group.get("bundle_sha256"), "Bundle-SHA-256")
    atlas_sha = _sha(index_group.get("atlas_sha256"), "Atlas-SHA-256")
    frames_sha = _sha(index_group.get("frames_sha256"), "Frame-SHA-256")
    gm_id = index_group.get("gm_id")
    if type(gm_id) is not int or not 0 <= gm_id <= 255:
        raise PivotCacheEvidenceError("Bundle-GM-ID ist ungültig")

    base = root / "cache" / "asset-stream-group-cache-v1"
    refs_root = base / "refs"
    folder = refs_root / slug
    objects = base / "objects"
    for candidate in (root / "cache", base, refs_root, folder, objects):
        if not _direct_directory(candidate, root):
            # A never-created cache is a miss, *not* a successful check.
            return None
    try:
        children = sorted(folder.iterdir())
    except OSError as exc:
        raise PivotCacheEvidenceError("Cachegruppen-Referenzen nicht lesbar") from exc
    if len(children) > MAX_CACHE_REFS:
        raise PivotCacheEvidenceError("Zu viele Cachegruppen-Referenzen")
    matches: list[CachedAssetStreamGroup] = []
    for ref_path in children:
        if _is_link(ref_path) or not ref_path.is_file():
            raise PivotCacheEvidenceError(f"Unsichere Cachegruppen-Referenz: {ref_path.name}")
        parsed_name = REF.fullmatch(ref_path.name)
        if parsed_name is None:
            raise PivotCacheEvidenceError(f"Nicht kanonischer Cache-Refname: {ref_path.name}")
        key = parsed_name.group(1)
        try:
            ref, _ = _read_json(ref_path, MAX_REF_BYTES)
        except ReleasePreflightError as exc:
            raise PivotCacheEvidenceError(f"Cache-Ref ist nicht lesbar: {exc}") from exc
        if (
            ref.get("cache_key") != key
            or ref.get("group") != group
            or ref.get("gm_id") != gm_id
            or ref.get("object_relative_path") != f"objects/{key[:2]}/{key}"
        ):
            raise PivotCacheEvidenceError("Cache-Ref zeigt auf andere Gruppe oder fremden Pfad")
        shard = objects / key[:2]
        object_dir = shard / key
        if not _direct_directory(shard, root) or not _direct_directory(object_dir, root):
            raise PivotCacheEvidenceError("Cache-Ref verweist auf fehlendes Objekt")
        manifest_path = object_dir / "object.v1.json"
        if _is_link(manifest_path):
            raise PivotCacheEvidenceError("Verlinktes Cache-Objektmanifest")
        try:
            manifest, _ = _read_json(manifest_path, MAX_OBJECT_MANIFEST_BYTES)
        except ReleasePreflightError as exc:
            raise PivotCacheEvidenceError(f"Cache-Objektmanifest ungültig: {exc}") from exc
        artifacts = manifest.get("artifacts", {})
        if (
            manifest.get("cache_key") != key or
            not isinstance(artifacts, dict) or
            not isinstance(artifacts.get("bundle"), dict) or
            not isinstance(artifacts.get("atlas"), dict)
        ):
            raise PivotCacheEvidenceError("Cache-Objektidentität ist ungültig")
        if artifacts["bundle"].get("sha256") != bundle_sha:
            continue
        if artifacts["atlas"].get("sha256") != atlas_sha:
            raise PivotCacheEvidenceError(
                "Bundle-SHA passt, aber Atlas-SHA widerspricht dem Produktionsindex"
            )
        try:
            desc = parse_group_cache_input(manifest["input"])
            cached = load_group_cache_object(workspace_root=root, descriptor=desc)
        except (KeyError, GroupCacheError, OSError, ValueError) as exc:
            raise PivotCacheEvidenceError(f"Publiziertes Cacheobjekt beschädigt: {exc}") from exc
        if cached is None:
            raise PivotCacheEvidenceError("Trefferobjekt hat keine gültige Cache-Referenz")
        if (
            desc.cache_key != key
            or cached.index_group_record != dict(index_group)
            or _sha256_file(cached.atlas_path) != atlas_sha
            or cached.atlas.frames_sha256 != frames_sha
        ):
            raise PivotCacheEvidenceError(
                "Cachegruppe ist nicht exakt der veröffentlichten BC7-Gruppe zugeordnet"
            )
        matches.append(cached)
    if len(matches) > 1:
        raise PivotCacheEvidenceError("Mehrdeutige publizierte Cachegruppenobjekte")
    return matches[0] if matches else None


def _finite_f32(value: object) -> float:
    if type(value) not in (float, int) or not math.isfinite(value):
        raise PivotCacheEvidenceError("Pivot ist keine endliche Zahl")
    if not -4 <= value <= 4:
        raise PivotCacheEvidenceError("Pivot liegt außerhalb des Messbereichs")
    try:
        number = struct.unpack("<f", struct.pack("<f", value))[0]
    except (OverflowError, ValueError, struct.error) as exc:
        raise PivotCacheEvidenceError("Pivot nicht als float32 darstellbar") from exc
    return 0.0 if number == 0 else number


def project_group_cache_metadata(
    cached: CachedAssetStreamGroup,
    pivots: Mapping[str, tuple[float, float]],
) -> dict:
    """Project exact V2 *metadata-only* cache-key change, without publishing.

    Only source metadata may change; page pixels, masks, names, page packing
    and codec parameters remain frozen in the projection. A real build might
    change other inputs; the projected digest is therefore not a release key.
    """
    if not pivots:
        raise PivotCacheEvidenceError("Keine betroffenen Pivots")
    if not isinstance(pivots, Mapping):
        raise PivotCacheEvidenceError("Pivotänderungen müssen gruppiert sein")
    metadata_before = frame_bindings_from_atlas(cached.atlas)
    descriptor_before = cached.descriptor.as_dict()
    if metadata_before != descriptor_before["frames"]:
        raise PivotCacheEvidenceError("Atlas-Metadaten stimmen nicht mit dem Cachevertrag überein")
    if set(pivots) - {f.name for f in cached.atlas.frames}:
        raise PivotCacheEvidenceError("Pivotänderung für unbekannten BC7-Frame")
    revisions = []
    changed_names: set[str] = set()
    for frame in cached.atlas.frames:
        if frame.name not in pivots:
            revisions.append(frame)
            continue
        candidate = pivots[frame.name]
        if (
            not isinstance(candidate, (tuple, list)) or len(candidate) != 2
        ):
            raise PivotCacheEvidenceError("Kandidat muss genau zwei Pivotkoordinaten enthalten")
        x, y = map(_finite_f32, candidate)
        if abs(x-frame.pivot.x) <= EPSILON and abs(y-frame.pivot.y) <= EPSILON:
            raise PivotCacheEvidenceError(f"{frame.name}: bereits im Bundle korrekt")
        revisions.append(replace(frame, pivot=replace(frame.pivot, x=x, y=y)))
        changed_names.add(frame.name)
    if changed_names != set(pivots):
        raise PivotCacheEvidenceError("Mehrdeutiger Pivotframe im Atlas")
    after_atlas = replace(cached.atlas, frames=tuple(revisions))
    metadata_after = frame_bindings_from_atlas(after_atlas)
    for field in ("count", "main_rgba_sha256", "mask_rgba_sha256", "names_sha256"):
        if metadata_after[field] != metadata_before[field]:
            raise PivotCacheEvidenceError("Ein Pivotentwurf veränderte Pixel-/Masken- oder Namensbindung")
    clone = cached.descriptor.as_dict()
    clone["frames"] = metadata_after
    try:
        descriptor_after = parse_group_cache_input(clone)
    except GroupCacheError as exc:
        raise PivotCacheEvidenceError(f"Neuer Cache-Vertrag ist ungültig: {exc}") from exc
    if descriptor_after.cache_key == cached.descriptor.cache_key:
        raise PivotCacheEvidenceError("Pivotänderung ließ den Cache-Key unverändert")
    return {
        "group": cached.descriptor.group,
        "changed_frames": sorted(changed_names),
        "original_cache_key": cached.descriptor.cache_key,
        "projected_cache_key": descriptor_after.cache_key,
        "original_metadata_sha256": metadata_before["metadata_sha256"],
        "projected_metadata_sha256": metadata_after["metadata_sha256"],
        "main_rgba_sha256": metadata_before["main_rgba_sha256"],
        "mask_rgba_sha256": metadata_before["mask_rgba_sha256"],
        "exact_source_metadata_projection_only": True,
        "actual_builder_rebuild_verified": False,
        "runtime_bundle_unchanged": True,
    }


def inspect_published_pivot(
    cached: CachedAssetStreamGroup,
    frame_name: str,
    *,
    measured_size: tuple[int, int],
    measured_old: tuple[float, float],
    measured_new: tuple[float, float],
) -> dict:
    """Classify a measured pivot using the exact published atlas, not PNG."""
    if not isinstance(frame_name, str):
        raise PivotCacheEvidenceError("Ungültiger Frame")
    matches = [f for f in cached.atlas.frames if f.name == frame_name]
    if len(matches) != 1:
        raise PivotCacheEvidenceError(
            f"{frame_name}: Frame fehlt oder mehrfach im publizierten BC7-Atlas"
        )
    frame = matches[0]
    if (
        frame.rect.width != measured_size[0]
        or frame.rect.height != measured_size[1]
    ):
        raise PivotCacheEvidenceError(
            f"{frame_name}: Mess-/BC7-Geometrie verschieden; keine sichere Übertragung"
        )
    present = (frame.pivot.x, frame.pivot.y)
    new = tuple(map(_finite_f32, measured_new))
    old = tuple(map(_finite_f32, measured_old))
    if all(abs(a-b) <= EPSILON for a, b in zip(present, new)):
        status = "bereits_im_bc7"
    elif all(abs(a-b) <= EPSILON for a, b in zip(present, old)):
        status = "bc7_neubau_erforderlich"
    else:
        raise PivotCacheEvidenceError(
            f"{frame_name}: tatsächlicher BC7-Pivot ist weder Mess-Ausgang "
            "noch Mess-Ziel; manuelle Geometrieabklärung nötig"
        )
    return {
        "name": frame.name,
        "status": status,
        "bc7_pivot": list(present),
        "measured_new": list(new),
        "size": [frame.rect.width, frame.rect.height],
        "source_main_rgba_sha256": frame.main_source_rgba_sha256,
        "cache_key": cached.descriptor.cache_key,
        "cache_verified": True,
        "comparison_basis": "published-bc7-atlas-v3",
    }


def audit_published_measurement(
    project_root: str | Path, profile_id: str, measurement,
) -> dict:
    """Check one measured frame against the currently published BC7 build.

    This convenience reader is suitable for a Tk background thread. It
    verifies the entire delivered manifest first; it does NOT approve,
    import or modify the measurement or any game/build/cache artifact.
    """
    from .pivot_measurements import Measurement
    from .release_preflight import ID, audit_release

    if not isinstance(profile_id, str) or not ID.fullmatch(profile_id):
        raise PivotCacheEvidenceError("Ungültige BC7-Profil-ID")
    if not isinstance(measurement, Measurement):
        raise PivotCacheEvidenceError("Kein verifizierter Mess-Eintrag")
    root = Path(project_root).resolve(strict=True)
    preflight = audit_release(root, profile_id)
    if preflight["summary"]["errors"]:
        raise PivotCacheEvidenceError(
            "Publizierter Build hat Integritätsfehler; BC7-Pivot nicht verifizierbar"
        )
    bundle_index = (
        root / "dist" / profile_id / "StrongholdEuropeDE"
        / "Runtime" / "AssetBundles" / "index.json"
    )
    try:
        data, digest = _read_json(bundle_index)
    except ReleasePreflightError as exc:
        raise PivotCacheEvidenceError(f"BC7-Bundleindex nicht lesbar: {exc}") from exc
    if digest != preflight["source_hashes"]["index_sha256"]:
        raise PivotCacheEvidenceError("Bundleindex seit vollständiger Prüfung verändert")
    records = data.get("groups")
    if not isinstance(records, list):
        raise PivotCacheEvidenceError("BC7-Index besitzt keine Gruppenliste")
    selected = [
        item for item in records
        if isinstance(item, dict) and item.get("group") == measurement.group
    ]
    if len(selected) != 1:
        raise PivotCacheEvidenceError(
            f"{measurement.group}: nicht eindeutig im publizierten BC7-Index"
        )
    cached = locate_published_group(root, selected[0])
    if cached is None:
        raise PivotCacheEvidenceError(
            f"{measurement.group}: kein zum aktuellen Bundle passendes "
            "vollständig verifiziertes Atlas-Cacheobjekt vorhanden"
        )
    evidence = inspect_published_pivot(
        cached, measurement.name,
        measured_size=(measurement.width, measurement.height),
        measured_old=(measurement.pivot_x, measurement.pivot_y),
        measured_new=(measurement.new_pivot_x, measurement.new_pivot_y),
    )
    if (
        _sha256_file(bundle_index) != digest
        or _sha256_file(root / "dist" / profile_id / "StrongholdEuropeDE"
                        / "build-manifest.json") != preflight[
                            "source_hashes"]["manifest_sha256"]
    ):
        raise PivotCacheEvidenceError("Bundleindex oder Manifest während der Prüfung geändert")
    evidence["profile_id"] = profile_id
    evidence["bundle_sha256"] = selected[0]["bundle_sha256"]
    evidence["atlas_sha256"] = selected[0]["atlas_sha256"]
    evidence["manifest_sha256"] = preflight["source_hashes"]["manifest_sha256"]
    return evidence

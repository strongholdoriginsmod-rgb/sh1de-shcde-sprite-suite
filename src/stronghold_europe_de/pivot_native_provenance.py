"""Reconstruct a pinned native geometry proof from real mapping and shipped BC7.

This is a *read-only audit* of published art provenance, not a new
geometry policy, pivot installer, or authority to update frozen proof hashes.

For native-reanchored review groups with target-keep frames, it binds:
mapping gzip -> validated group -> native pivot formula -> shipped BC7 index
-> exact immutable group cache atlas -> complete frozen native/review proofs.

Source RGBA hashes are the pre-BC7 digests recorded and verified in the
published immutable atlas object, NOT re-decoded original game resources.
Recomputing them from original game assets is still a separate build gate.
"""
from __future__ import annotations

from hashlib import sha256
import gzip
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping

from .gm_atlas import (
    AtlasGroupSpec,
    GMAtlasError,
    KEEP_CRUSADER_PROOF_STATUS,
    NATIVE_SOURCE_PROOF_STATUS,
    SOURCE_FRAME_ORIGIN,
    TARGET_FRAME_ORIGIN,
    native_reanchored_pivot,
    native_source_geometry_contract,
    native_source_geometry_proof,
    validate_complete_group,
    validate_review_frame_partition,
)
from .pivot_bc7_cache import (
    PivotCacheEvidenceError, locate_published_group,
)
from .release_preflight import (
    ID, ReleasePreflightError, _bad_constant, _is_link, _read_json,
    _safe_child, _sha256_file, _strict_pairs, audit_release,
)

SCHEMA = "stronghold-europe.pivot-native-provenance.v1"
DEFAULT_GROUP = "anim_castle"
MAX_MAPPING_COMPRESSED = 64 * 1024 * 1024
MAX_MAPPING_DECOMPRESSED = 512 * 1024 * 1024
MAX_PROOF_FRAMES = 4096


class PivotNativeProvenanceError(ValueError):
    """Missing, changed or conflicting native pivot provenance."""


def _mapping_source(root: Path) -> Path:
    try:
        file = _safe_child(root, "work/mapping/proposals.json.gz")
    except ReleasePreflightError as exc:
        raise PivotNativeProvenanceError(str(exc)) from exc
    if not file.is_file() or _is_link(file):
        raise PivotNativeProvenanceError("Originäres Mapping fehlt oder ist verlinkt")
    return file


def _read_pinned_mapping(path: Path) -> tuple[dict[str, Any], str]:
    """Bound decompression and reject duplicate keys / special JSON values."""
    try:
        before = path.stat()
        if before.st_size <= 0 or before.st_size > MAX_MAPPING_COMPRESSED:
            raise PivotNativeProvenanceError("Mapping-GZIP ist außerhalb der Größenbegrenzung")
        digest = _sha256_file(path)
        with gzip.open(path, "rb") as stream:
            contents = stream.read(MAX_MAPPING_DECOMPRESSED + 1)
        if len(contents) > MAX_MAPPING_DECOMPRESSED:
            raise PivotNativeProvenanceError("Mapping-GZIP dekomprimiert zu viele Bytes")
        document = json.loads(
            contents.decode("utf-8"),
            object_pairs_hook=_strict_pairs,
            parse_constant=_bad_constant,
        )
        after = path.stat()
    except (OSError, UnicodeError, json.JSONDecodeError, EOFError,
            ReleasePreflightError) as exc:
        raise PivotNativeProvenanceError(f"Mapping nicht vertrauenswürdig: {exc}") from exc
    if (
        before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or _sha256_file(path) != digest
    ):
        raise PivotNativeProvenanceError("Mapping hat sich während der Einlesung verändert")
    if (
        not isinstance(document, dict)
        or document.get("schema_version") != 2
        or not isinstance(document.get("sprites"), list)
        or len(document["sprites"]) > 300_000
    ):
        raise PivotNativeProvenanceError("Mapping hat kein unterstütztes Proposals-Schema")
    return document, digest


def _positive_dimension(value: object, label: str) -> int:
    if type(value) not in (int, float) or value <= 0 or value != int(value):
        raise PivotNativeProvenanceError(f"Ungültige Mappinggröße: {label}")
    return int(value)


def _pivot(source: Mapping[str, object]) -> list[float]:
    return [float(source["pivot_x"]), float(source["pivot_y"])]


def reconstruct_group_proof(
    validated,
    cached,
    group: str,
) -> dict:
    """Reconstruct *every* frame, not merely one measured pivot.

    All expected digests come from the pinned group profile; all actual
    pixel hashes come from the fully verified, shipped cache atlas.
    """
    spec = validated.spec
    if (
        spec.gm_file_name != group
        or not spec.uses_native_geometry
        or spec.uses_authored_source_geometry
        or spec.review_frame_policy is None
        or not spec.review_frame_policy.renders_native_source
        or not spec.review_frame_policy.includes_keep
        or spec.native_source_geometry_policy is None
    ):
        raise PivotNativeProvenanceError(
            f"{group}: kein freigegebener Native-Review/Keep-Vertrag"
        )
    if not 0 < len(validated.proposals) <= MAX_PROOF_FRAMES:
        raise PivotNativeProvenanceError("Gruppe überschreitet den Beweisrahmen")
    if (
        cached.descriptor.group != group
        or cached.atlas.group != group
        or cached.atlas.frames_sha256 != cached.index_group_record.get("frames_sha256")
        or len(cached.atlas.frames) != len(validated.proposals)
    ):
        raise PivotNativeProvenanceError("Cache-Atlas/Mapping/Index-Gruppenidentität widerspricht sich")

    mapping_names = [str(p.get("name", "")) for p in validated.proposals]
    atlas_names = [f.name for f in cached.atlas.frames]
    if mapping_names != atlas_names or len(set(atlas_names)) != len(atlas_names):
        raise PivotNativeProvenanceError("Loader-Reihenfolge oder Frame-Namen stimmen nicht überein")
    geometry_contract = native_source_geometry_contract(group, spec.geometry_policy)
    if geometry_contract is None:
        raise PivotNativeProvenanceError(f"{group}: eingefrorener nativer Geometrievertrag fehlt")

    native_rows: list[dict[str, Any]] = []
    provenance_rows: list[dict[str, Any]] = []
    frame_findings: list[dict[str, Any]] = []
    source_count = target_count = 0
    for proposal, frame in zip(validated.proposals, cached.atlas.frames, strict=True):
        name = str(proposal["name"])
        action = proposal.get("action")
        target = proposal.get("target")
        if not isinstance(target, dict):
            raise PivotNativeProvenanceError(f"{name}: Crusader-Zielmetadaten fehlen")
        output_pivot = [frame.pivot.x, frame.pivot.y]
        if action == "KEEP_CRUSADER":
            target_count += 1
            origin = TARGET_FRAME_ORIGIN
            status = KEEP_CRUSADER_PROOF_STATUS
            expected_size = [
                _positive_dimension(target["width"], f"{name}.target.width"),
                _positive_dimension(target["height"], f"{name}.target.height"),
            ]
            # Actual target pivot is loaded as Unity float32. Exact equality
            # prevents float/digest proof drift hidden by display rounding.
            from .gm_atlas import _float32
            expected_pivot = [_float32(target["pivot_x"]), _float32(target["pivot_y"])]
            expected_ppu = _float32(target["pixels_per_unit"])
        elif action == "REVIEW_MANUAL":
            source_count += 1
            origin = SOURCE_FRAME_ORIGIN
            status = NATIVE_SOURCE_PROOF_STATUS
            source = proposal.get("source")
            if not isinstance(source, dict):
                raise PivotNativeProvenanceError(f"{name}: SH1DE-Quellmetadaten fehlen")
            expected_size = [
                _positive_dimension(source["width"], f"{name}.source.width"),
                _positive_dimension(source["height"], f"{name}.source.height"),
            ]
            expected_pivot = list(native_reanchored_pivot(source, target, name))
            expected_ppu = float(target["pixels_per_unit"])
            native_rows.append({
                "name": name,
                "origin": SOURCE_FRAME_ORIGIN,
                "source_width": expected_size[0],
                "source_height": expected_size[1],
                "target_width": _positive_dimension(target["width"], f"{name}.target.width"),
                "target_height": _positive_dimension(target["height"], f"{name}.target.height"),
                "source_pivot_x": float(source["pivot_x"]),
                "source_pivot_y": float(source["pivot_y"]),
                "target_pivot_x": float(target["pivot_x"]),
                "target_pivot_y": float(target["pivot_y"]),
                "output_pivot_x": frame.pivot.x,
                "output_pivot_y": frame.pivot.y,
                "source_pixels_per_unit": float(source["pixels_per_unit"]),
                "target_pixels_per_unit": float(target["pixels_per_unit"]),
                "output_pixels_per_unit": frame.pixels_per_unit,
                "source_rgba_sha256": frame.main_source_rgba_sha256,
            })
        else:
            raise PivotNativeProvenanceError(
                f"{name}: unbekannte Native-Review-Aktion: {action}"
            )
        if (
            [frame.rect.width, frame.rect.height] != expected_size
            or output_pivot != expected_pivot
            or frame.pixels_per_unit != expected_ppu
        ):
            raise PivotNativeProvenanceError(
                f"{name}: realer BC7-Pivot/Geometrie/PPU weicht vom "
                f"unveränderten nativen Mapping ab: "
                f"actual={output_pivot} expected={expected_pivot}"
            )
        provenance_rows.append({
            "name": name, "origin": origin,
            "proof_status": status, "discarded_mask_alpha": 0,
            "action": action,
        })
        frame_findings.append({
            "name": name, "action": action, "origin": origin,
            "pivot": output_pivot, "geometry": expected_size,
            "source_path_id": (
                proposal.get("source", {}).get("path_id")
                if action == "REVIEW_MANUAL" else None
            ),
            "target_path_id": target.get("path_id"),
        })
    try:
        actual_native = native_source_geometry_proof(
            native_rows,
            source_anchor_tolerance_px=geometry_contract.source_anchor_tolerance_px,
        )
        actual_partition = validate_review_frame_partition(
            validated, provenance_rows
        )
    except GMAtlasError as exc:
        raise PivotNativeProvenanceError(
            f"{group}: ursprüngliche Proof-Formel abgelehnt: {exc}"
        ) from exc

    policy = spec.native_source_geometry_policy
    if (
        actual_native["frame_count"] != policy.expected_frame_count
        or actual_native["geometry_proof_sha256"] != policy.expected_geometry_proof_sha256
        or actual_native["origin_proof_sha256"] != policy.expected_origin_proof_sha256
        or actual_native["source_rgba_sha256"] != policy.expected_source_rgba_sha256
        or actual_native["target_origin_count"] != 0
        or source_count != policy.expected_frame_count
        or source_count + target_count != spec.expected_frame_count
    ):
        raise PivotNativeProvenanceError(
            f"{group}: eingefrorener Native-Pivot-/Herkunfts-/RGBA-Proof wurde verändert"
        )
    return {
        "group": group,
        "status": "frozen_native_geometry_reconstructed",
        "total_frames": len(frame_findings),
        "native_source_frames": source_count,
        "target_keep_frames": target_count,
        "native_proof": actual_native,
        "review_partition": {
            key: value for key, value in actual_partition.items()
            if key != "frame_origins"
        },
        "geometry_mode": spec.geometry_policy,
        "geometry_proof_algorithm": policy.proof_algorithm,
        "frames": frame_findings,
        "source_rgba_evidence": (
            "Pre-BC7 frame RGBA digests recorded in exact immutable "
            "shipped atlas; original Unity game assets not re-decoded."
        ),
    }


def audit_native_geometry(
    project_root: str | Path,
    profile_id: str = "sprite-suite-world-bc7-v2",
    group: str = DEFAULT_GROUP,
) -> dict:
    """Recompute a published native proof from genuine, SHA-pinned sources."""
    if not isinstance(profile_id, str) or ID.fullmatch(profile_id) is None:
        raise PivotNativeProvenanceError("Ungültige Profil-ID")
    if group != DEFAULT_GROUP:
        # Native review groups can be enabled only after separately reviewing
        # their exact loader/geometry/proof contract.
        raise PivotNativeProvenanceError("Derzeit nur anim_castle für die native Proof-Rekonstruktion zugelassen")
    root = Path(project_root).resolve(strict=True)
    preflight = audit_release(root, profile_id)
    if preflight["summary"]["errors"]:
        raise PivotNativeProvenanceError(
            "Veröffentlichter Produktionsbuild ist nicht manifest-/SHA-identisch"
        )

    try:
        profile_path = _safe_child(root, f"profiles/{profile_id}.json")
        index_path = _safe_child(
            root, f"dist/{profile_id}/StrongholdEuropeDE/Runtime/AssetBundles/index.json"
        )
        manifest_path = _safe_child(
            root, f"dist/{profile_id}/StrongholdEuropeDE/build-manifest.json"
        )
        profile, profile_sha = _read_json(profile_path)
        index, index_sha = _read_json(index_path)
        manifest, manifest_sha = _read_json(manifest_path)
    except (ReleasePreflightError, OSError) as exc:
        raise PivotNativeProvenanceError(f"Quell-/Profil-/Manifestfehler: {exc}") from exc
    if (
        profile_sha != preflight["source_hashes"]["profile_sha256"]
        or index_sha != preflight["source_hashes"]["index_sha256"]
        or manifest_sha != preflight["source_hashes"]["manifest_sha256"]
    ):
        raise PivotNativeProvenanceError("Profil/Bundleindex/Manifest seit Integritätsprüfung verändert")

    raw_specs = profile.get("gm_atlases")
    raw_groups = index.get("groups")
    if not isinstance(raw_specs, list) or not isinstance(raw_groups, list):
        raise PivotNativeProvenanceError("Profilliste oder BC7-Gruppenliste fehlt")
    selected_specs = [
        item for item in raw_specs
        if isinstance(item, dict) and item.get("gm_file_name") == group
    ]
    selected_bundles = [
        item for item in raw_groups
        if isinstance(item, dict) and item.get("group") == group
    ]
    if len(selected_specs) != 1 or len(selected_bundles) != 1:
        raise PivotNativeProvenanceError(
            "Native Gruppe im Profil/BC7-Index nicht eindeutig"
        )
    try:
        spec = AtlasGroupSpec.from_profile(selected_specs[0])
        cache = locate_published_group(root, selected_bundles[0])
    except (GMAtlasError, PivotCacheEvidenceError) as exc:
        raise PivotNativeProvenanceError(
            f"Native BC7-Bundleprovenienz fehlgeschlagen: {exc}"
        ) from exc
    if cache is None:
        raise PivotNativeProvenanceError(
            "Kein eindeutig passender veröffentlichter Cache-Atlas vorhanden"
        )

    mapping_path = _mapping_source(root)
    mapping, mapping_sha = _read_pinned_mapping(mapping_path)
    if (
        mapping.get("source_build_id") != manifest.get("source_build_id")
        or mapping.get("target_build_id") != manifest.get("target_build_id")
    ):
        raise PivotNativeProvenanceError(
            "Native Mapping-Quell-/Ziel-Build-IDs passen nicht zum Produktionsmanifest"
        )
    try:
        validated = validate_complete_group(mapping["sprites"], spec)
        result = reconstruct_group_proof(validated, cache, group)
    except (GMAtlasError, KeyError, TypeError, ValueError) as exc:
        raise PivotNativeProvenanceError(
            f"{group}: native Mapping-/Geometrieprüfung gescheitert: {exc}"
        ) from exc

    # Pin the original files again after the expensive mapping/proof walk.
    bundle_record = selected_bundles[0]
    try:
        bundle = _safe_child(
            root,
            f"dist/{profile_id}/StrongholdEuropeDE/{bundle_record['bundle_path']}"
        )
        if (
            _sha256_file(profile_path) != profile_sha
            or _sha256_file(index_path) != index_sha
            or _sha256_file(manifest_path) != manifest_sha
            or _sha256_file(mapping_path) != mapping_sha
            or _sha256_file(bundle) != bundle_record["bundle_sha256"]
            or _sha256_file(cache.atlas_path) != bundle_record["atlas_sha256"]
        ):
            raise PivotNativeProvenanceError(
                "Native Quellen oder veröffentlichtes BC7-Bundle während der Prüfung verändert"
            )
    except (OSError, KeyError, ReleasePreflightError) as exc:
        raise PivotNativeProvenanceError(
            f"Native Buildquellen nach der Prüfung nicht mehr sicher: {exc}"
        ) from exc

    return {
        "schema": SCHEMA,
        "profile_id": profile_id,
        "mapping_relative_path": "work/mapping/proposals.json.gz",
        "mapping_source_build_id": mapping["source_build_id"],
        "mapping_target_build_id": mapping["target_build_id"],
        "source_hashes": {
            "profile_sha256": profile_sha,
            "mapping_gzip_sha256": mapping_sha,
            "build_manifest_sha256": manifest_sha,
            "bundle_index_sha256": index_sha,
            "bundle_sha256": bundle_record["bundle_sha256"],
            "atlas_sha256": bundle_record["atlas_sha256"],
            "group_cache_key": cache.descriptor.cache_key,
        },
        "group_proof": result,
        "game_files_modified": False,
        "rebuild_performed": False,
        "release_allowed": False,
        "disclaimer": (
            "Published native geometry proof reconstructed from existing mapping "
            "and cached pre-BC7 digests; original resource.assets pixels not "
            "independently decoded. No new pivot, proof, bundle, or game write."
        ),
    }


def save_native_geometry_audit(report: dict, project_root: str | Path) -> Path:
    """Write a deterministic standalone report only after complete re-audit."""
    if not isinstance(report, dict) or report.get("schema") != SCHEMA:
        raise PivotNativeProvenanceError("Kein nativer Geometrie-Prüfbericht")
    root = Path(project_root).resolve(strict=True)
    current = audit_native_geometry(
        root, report.get("profile_id"), report.get("group_proof", {}).get("group")
    )
    if current != report:
        raise PivotNativeProvenanceError(
            "Mapping, BC7 oder Provenienz seit dem Bericht geändert"
        )
    relative = Path("work/reports/pivot-native-provenance")
    if any(_is_link(root.joinpath(*relative.parts[:n])) for n in range(1, len(relative.parts)+1)):
        raise PivotNativeProvenanceError("Verlinkter Berichtordner nicht erlaubt")
    folder = root.joinpath(*relative.parts)
    folder.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    digest = sha256(payload.encode("utf-8")).hexdigest()[:16]
    filename = f"{report['profile_id']}-{report['group_proof']['group']}-{digest}.json"
    target = folder / filename
    if target.exists():
        if not target.is_file() or _is_link(target) or target.read_text(encoding="utf-8") != payload:
            raise PivotNativeProvenanceError("Bestehender Provenienzbericht ist verändert")
        return target
    fd, temp = tempfile.mkstemp(dir=folder, prefix=".native-proof-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, target)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return target


__all__ = [
    "SCHEMA", "PivotNativeProvenanceError", "audit_native_geometry",
    "save_native_geometry_audit", "reconstruct_group_proof",
]

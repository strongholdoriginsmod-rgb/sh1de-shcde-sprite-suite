"""Pinned BC7 pivot-change intents; never mutate atlas inputs or game artifacts.

The shipped catalogue's index.json is *not* the BC7 builder's source of
pivot truth. A human approval must be tied to the original measurement,
the shipped PNG/index and the current manifest before producing even an
offline build-intent record. A separate future builder integration must
recompute native-geometry proofs and produce a fresh tested bundle.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import re
import tempfile

from .pivot_approvals import (
    APPROVAL_SCHEMA, PivotDecision, can_approve,
)
from .pivot_measurements import (
    PivotMeasurementError, load_measurements, review_measurements,
)
from .release_preflight import (
    ReleasePreflightError, _is_link, _read_json, _sha256_file,
    _safe_child, audit_release, ID,
)
from .pivot_bc7_cache import (
    PivotCacheEvidenceError, inspect_published_pivot,
    locate_published_group, project_group_cache_metadata,
)

SCHEMA = "stronghold-europe.pivot-bc7-stage.v1"
APPROVAL_FILE_NAME = re.compile(r"zinnen-entscheidung-([0-9a-f]{12})-([0-9a-f]{16})\.json\Z")
DECISIONS = {"freigegeben", "abgelehnt", "zurueckgestellt", "keine_aenderung"}
ROW_FIELDS = frozenset({
    "name", "status", "decision", "decided_at", "note", "source",
    "source_image", "source_image_sha256", "source_index",
    "source_index_sha256", "size", "offset_px", "measured_old",
    "current_pivot", "measured_new",
})
MAX_APPROVAL_BYTES = 4 * 1024 * 1024
MAX_ROWS = 4096


class PivotStageError(ValueError):
    """Missing, stale or mismatched pivot release evidence."""


def _selected_approval(root: Path, path: str | Path) -> Path:
    base = root / "work" / "reports" / "pivot-approval"
    item = Path(path)
    if not item.is_absolute():
        item = root / item
    folders = (root / "work", root / "work" / "reports", base)
    if (
        not item.is_file() or _is_link(item)
        or any(_is_link(folder) for folder in folders)
        or not base.resolve().is_relative_to(root)
        or not item.resolve().is_relative_to(base.resolve())
        or item.parent.resolve() != base.resolve()
    ):
        raise PivotStageError("Pivot-Freigabe muss eine direkte Datei im Projektberichtordner sein")
    if not APPROVAL_FILE_NAME.fullmatch(item.name):
        raise PivotStageError("Pivot-Freigabedateiname ist kein inhaltsadressierter Originalbericht")
    return item


def _load_approved_rows(
    root: Path, approval_path: Path, measurement_path: Path,
) -> tuple[list[dict], str, str]:
    """Reconstruct every row from the explicitly supplied original measurement."""
    try:
        stored, approval_sha = _read_json(approval_path, MAX_APPROVAL_BYTES)
        source = load_measurements(measurement_path)
        checks = review_measurements(source, root)
    except (ReleasePreflightError, PivotMeasurementError, OSError, ValueError) as exc:
        raise PivotStageError(f"Mess-/Freigabequellen ungültig: {exc}") from exc
    match = APPROVAL_FILE_NAME.fullmatch(approval_path.name)
    assert match is not None
    if (
        match.group(1) != source.sha256[:12]
        or match.group(2) != approval_sha[:16]
    ):
        raise PivotStageError("Freigabeberichtdateiname passt nicht zu den aktuellen SHA-256-Werten")
    if stored.get("schema") != APPROVAL_SCHEMA:
        raise PivotStageError("Unbekanntes Pivot-Freigabeformat")
    if stored.get("measurement_sha256") != source.sha256:
        raise PivotStageError("Originalmessung unterscheidet sich von freigegebener Messung")
    if stored.get("measurement_path") != str(measurement_path.resolve()):
        raise PivotStageError("Originalmessung muss ausdrücklich die damals geprüfte Datei sein")
    rows = stored.get("rows")
    if not isinstance(rows, list) or len(rows) > MAX_ROWS or len(rows) != len(checks):
        raise PivotStageError("Freigabezeilen passen nicht zu den ursprünglichen Messungen")
    if type(stored.get("approved_count")) is not int or type(stored.get("rejected_count")) is not int:
        raise PivotStageError("Freigabezähler fehlen oder sind ungültig")
    approved = []
    rejected = 0
    for position, (row, check) in enumerate(zip(rows, checks, strict=True)):
        if not isinstance(row, dict) or set(row) != ROW_FIELDS:
            raise PivotStageError(f"Freigabezeile {position} enthält unbekannte/fehlende Daten")
        measurement = check.measurement
        expected = {
            "name": measurement.name,
            "status": check.status,
            "source": check.side,
            "source_image": str(check.pixel_file) if check.pixel_file else None,
            "source_image_sha256": check.pixel_sha256,
            "source_index": str(check.index_file) if check.index_file else None,
            "source_index_sha256": check.index_sha256,
            "size": [measurement.width, measurement.height],
            "offset_px": [measurement.right, measurement.up],
            "measured_old": [measurement.pivot_x, measurement.pivot_y],
            "current_pivot": list(check.actual_pivot) if check.actual_pivot else None,
            "measured_new": [measurement.new_pivot_x, measurement.new_pivot_y],
        }
        for field, value in expected.items():
            # JSON-type-exact equality rejects booleans masquerading as
            # 0/1 pivots, or integers disguising float metadata.
            if json.dumps(row[field], sort_keys=True) != json.dumps(value, sort_keys=True):
                raise PivotStageError(
                    f"{measurement.name}: {field} widerspricht dem erneut geprüften Zustand"
                )
        action = row["decision"]
        if not isinstance(action, str) or action not in DECISIONS:
            raise PivotStageError(f"{measurement.name}: unbekannte Freigabeentscheidung")
        if action in ("freigegeben", "abgelehnt"):
            decision = PivotDecision(action, row["note"], row["decided_at"])
            try:
                decision.validate()
            except PivotMeasurementError as exc:
                raise PivotStageError(f"{measurement.name}: {exc}") from exc
            if action == "abgelehnt":
                rejected += 1
                if check.status != "pruefen":
                    raise PivotStageError(f"{measurement.name}: Ablehnung ohne prüfbare Änderung")
            else:
                if not can_approve(check):
                    raise PivotStageError(f"{measurement.name}: keine gültige ausgelieferte Ausgangsposition")
                # Distinct change: old and proposed must not already be equal.
                if check.actual_pivot == (measurement.new_pivot_x, measurement.new_pivot_y):
                    raise PivotStageError(f"{measurement.name}: ist bereits korrigiert")
                approved.append(row)
        else:
            if row["decided_at"] is not None or row["note"] != "":
                raise PivotStageError(f"{measurement.name}: inaktive Entscheidung mit gefälschter Bestätigung")
            if action == "keine_aenderung" and check.status != "bereits_passend":
                raise PivotStageError(f"{measurement.name}: fälschlich als unverändert gekennzeichnet")
            if action == "zurueckgestellt" and check.status == "bereits_passend":
                raise PivotStageError(f"{measurement.name}: bereits passend darf nicht zurückgestellt werden")
    if stored["approved_count"] != len(approved) or stored["rejected_count"] != rejected:
        raise PivotStageError("Freigabezähler weichen von den Einzelentscheidungen ab")
    return approved, approval_sha, source.sha256


def prepare_pivot_build_stage(
    project_root: str | Path, profile_id: str,
    approval_file: str | Path, measurement_file: str | Path,
) -> dict:
    """Produce source-bound *instructions* requiring a separate builder release.

    All reads are performed against current sources and finished artifacts;
    never invokes builder/install, changes index.json or records human approval.
    """
    if not isinstance(profile_id, str) or not ID.fullmatch(profile_id):
        raise PivotStageError("Ungültige Produktionsprofil-ID")
    root = Path(project_root).resolve(strict=True)
    approval = _selected_approval(root, approval_file)
    measurement = Path(measurement_file)
    if not measurement.is_absolute():
        measurement = root / measurement
    if _is_link(measurement) or not measurement.is_file():
        raise PivotStageError("Originalmessdatei muss explizit und unverlinkt vorliegen")
    measurement = measurement.resolve()
    approved, approval_sha, measurement_sha = _load_approved_rows(
        root, approval, measurement
    )

    # Verify entire current build rather than a stale historical QA report.
    baseline = audit_release(root, profile_id)
    if baseline["summary"]["errors"]:
        errors = [row["text"] for row in baseline["findings"] if row["schwere"] == "fehler"]
        raise PivotStageError(
            "Produktionsstand nicht unverändert/vertragsgemäß: " + "; ".join(errors[:4])
        )
    try:
        profile, profile_hash = _read_json(root / "profiles" / f"{profile_id}.json")
        index_path = root / "dist" / profile_id / "StrongholdEuropeDE" / "Runtime" / "AssetBundles" / "index.json"
        bundle_index, index_hash = _read_json(index_path)
    except (ReleasePreflightError, OSError) as exc:
        raise PivotStageError(f"Produktionsdaten nicht lesbar: {exc}") from exc
    if (
        profile.get("id") != profile_id
        or index_hash != baseline["source_hashes"]["index_sha256"]
        or profile_hash != baseline["source_hashes"]["profile_sha256"]
    ):
        raise PivotStageError("Profil- oder Bundleindex hat sich seit dem Release-Abgleich geändert")
    specs = profile.get("gm_atlases", [])
    groups = bundle_index.get("groups", [])
    if not isinstance(specs, list) or not isinstance(groups, list):
        raise PivotStageError("BC7-Profil- oder Index-Gruppen nicht prüfbar")
    spec_by_group = {
        s.get("gm_file_name"): s for s in specs if isinstance(s, dict)
        and isinstance(s.get("gm_file_name"), str)
    }
    idx_by_group = {
        g.get("group"): g for g in groups if isinstance(g, dict)
        and isinstance(g.get("group"), str)
    }

    changes = []
    for row in approved:
        name = row["name"]
        # Names in the original measurement were already checked against NAME.
        from .pivot_measurements import NAME
        match = NAME.fullmatch(name)
        assert match is not None
        group = match.group("group")
        spec = spec_by_group.get(group)
        bundle = idx_by_group.get(group)
        if spec is None or bundle is None:
            raise PivotStageError(f"{name}: nicht in genau diesem Produktionsprofil/-Bundle")
        geometry = spec.get("geometry_policy")
        review = spec.get("review_frame_policy")
        # A released bundle and geometry proof MUST change together with
        # any pivot-only mutation; their frozen hashes are not reinterpreted.
        changes.append({
            "name": name,
            "group": group,
            "old_pivot": row["current_pivot"],
            "proposed_pivot": row["measured_new"],
            "size": row["size"],
            "measured_offset_px": row["offset_px"],
            "source_image_sha256": row["source_image_sha256"],
            "source_index_sha256": row["source_index_sha256"],
            "bundle_path": bundle.get("bundle_path"),
            "bundle_sha256": bundle.get("bundle_sha256"),
            "geometry_policy": geometry,
            "review_frame_policy": review,
            "requires_proof_recalculation": True,
            "requires_bundle_rebuild": True,
            "application_allowed": False,
            "reason": (
                "Der BC7-Builder liest native Source-/Target-Metadaten, nicht "
                "den Katalogindex. Pivots, Gruppen-Geometrienachweis, Frame-"
                "Metadatenhash, BC7-Bundle und Validation müssen gemeinsam "
                "neu berechnet und separat freigegeben werden."
            ),
        })
    # Resolve the exact source-Atlas bound to the PUBLISHED BC7 bundle, not
    # merely the last cache entry for a matching group name. The catalogue
    # PNG often has different RGBA bytes than Unity's pre-BC7 frame: pivot
    # and dimensions are comparable, pixel digests are not interchangeable.
    grouped: dict[str, list[dict]] = {}
    for change in changes:
        grouped.setdefault(change["group"], []).append(change)
    still_needed: list[dict] = []
    already_in_bc7: list[dict] = []
    cache_impacts: list[dict] = []
    unverified_cache_groups: list[str] = []
    for group in sorted(grouped):
        group_rows = grouped[group]
        try:
            cached = locate_published_group(root, idx_by_group[group])
            if cached is None:
                unverified_cache_groups.append(group)
                for change in group_rows:
                    change["published_bc7_evidence"] = {
                        "status": "cache_nicht_verfuegbar",
                        "cache_verified": False,
                        "reason": (
                            "Kein eindeutig zum aktuellen Bundle passendes "
                            "verifiziertes Cache-Atlasobjekt gefunden. "
                            "Der Entwurf bleibt nicht anwendbar."
                        ),
                    }
                    still_needed.append(change)
                continue
            pending: dict[str, tuple[float, float]] = {}
            for change in group_rows:
                inspected = inspect_published_pivot(
                    cached,
                    change["name"],
                    measured_size=tuple(change["size"]),
                    measured_old=tuple(change["old_pivot"]),
                    measured_new=tuple(change["proposed_pivot"]),
                )
                if inspected["status"] == "bereits_im_bc7":
                    already_in_bc7.append({
                        "name": change["name"],
                        "group": group,
                        "bc7_pivot": inspected["bc7_pivot"],
                        "bundle_sha256": idx_by_group[group]["bundle_sha256"],
                        "cache_key": inspected["cache_key"],
                        "reason": "Im tatsächlich ausgelieferten BC7-Atlas schon korrekt",
                    })
                    continue
                change["published_bc7_evidence"] = inspected
                pending[change["name"]] = tuple(change["proposed_pivot"])
                still_needed.append(change)
            if pending:
                projected = project_group_cache_metadata(cached, pending)
                cache_impacts.append(projected)
                for change in group_rows:
                    if change["name"] in pending:
                        change["projected_cache_key"] = projected["projected_cache_key"]
                        change["current_cache_key"] = projected["original_cache_key"]
        except PivotCacheEvidenceError as exc:
            raise PivotStageError(
                f"{group}: publizierter BC7-Atlas kann nicht sicher "
                f"zugeordnet werden: {exc}"
            ) from exc
    changes = still_needed

    # The build may have changed while all files were being audited. Fail
    # closed before returning even a no-write plan.
    refreshed, refreshed_sha, refreshed_measure_sha = _load_approved_rows(
        root, approval, measurement
    )
    if (refreshed != approved or refreshed_sha != approval_sha
        or refreshed_measure_sha != measurement_sha):
        raise PivotStageError("Messung, Freigabe oder Spritequellen während des Abgleichs geändert")
    manifest_now = (root / "dist" / profile_id / "StrongholdEuropeDE"
                    / "build-manifest.json")
    if _sha256_file(manifest_now) != baseline["source_hashes"]["manifest_sha256"]:
        raise PivotStageError("Buildmanifest während der Prüfung geändert")
    if (
        _sha256_file(index_path) != index_hash
        or _sha256_file(root / "profiles" / f"{profile_id}.json") != profile_hash
    ):
        raise PivotStageError("Bundleindex oder Profil während der Prüfung geändert")
    build_root = root / "dist" / profile_id / "StrongholdEuropeDE"
    for group in grouped:
        record = idx_by_group[group]
        try:
            relative_bundle = record["bundle_path"]
            bundle_path = _safe_child(build_root, relative_bundle)
            if _sha256_file(bundle_path) != record["bundle_sha256"]:
                raise PivotStageError(
                    f"{group}: veröffentlichtes Bundle hat sich während der Prüfung geändert"
                )
        except (KeyError, OSError, ReleasePreflightError) as exc:
            raise PivotStageError(
                f"{group}: Bundle-Datei nicht mehr sicher überprüfbar: {exc}"
            ) from exc
    return {
        "schema": SCHEMA,
        "profile_id": profile_id,
        "source_hashes": {
            "measurement_sha256": measurement_sha,
            "approval_sha256": approval_sha,
            "profile_sha256": profile_hash,
            "build_manifest_sha256": baseline["source_hashes"]["manifest_sha256"],
            "bundle_index_sha256": index_hash,
        },
        "source_files": {
            "measurement": str(measurement),
            "approval": str(approval),
        },
        "baseline": {
            "verified_outputs": baseline["stats"]["verified_outputs"],
            "expected_outputs": baseline["stats"]["expected_outputs"],
            "validation_warning_count": baseline["summary"]["warnings"],
            "historical_validation_is_not_current_release_proof": True,
        },
        "change_count": len(changes),
        "changes": changes,
        "already_in_published_bc7": already_in_bc7,
        "already_in_published_bc7_count": len(already_in_bc7),
        "verified_cache_group_impacts": cache_impacts,
        "unverified_cache_groups": unverified_cache_groups,
        "state": "no_changes" if not changes else "requires_separate_bc7_rebuild",
        "installation_allowed": False,
        "warning": (
            "Nur unveränderlicher BC7-Änderungsentwurf; keine Anwendung auf "
            "Spiel, Sprite-Index, Cache, Pipeline oder Bundle. "
            "Proof-/Profilpins dürfen nicht stillschweigend umgeschrieben werden."
        ),
    }


def save_pivot_build_stage(report: dict, project_root: str | Path) -> Path:
    """Recheck all source contracts immediately before immutable report write."""
    if not isinstance(report, dict) or report.get("schema") != SCHEMA:
        raise PivotStageError("Unbekanntes BC7-Pivot-Stufenschema")
    root = Path(project_root).resolve(strict=True)
    paths = report.get("source_files", {})
    if not isinstance(paths, dict):
        raise PivotStageError("Fehlende ursprüngliche Mess-/Freigabepfade")
    updated = prepare_pivot_build_stage(
        root, report.get("profile_id"),
        paths.get("approval"), paths.get("measurement"),
    )
    if updated != report:
        raise PivotStageError("Quellen oder Build seit dem Stufenentwurf geändert – erneut prüfen")
    folder = root / "work" / "reports" / "pivot-bc7-stage"
    ancestors = (root / "work", root / "work" / "reports", folder)
    if any(_is_link(part) for part in ancestors):
        raise PivotStageError("Pivot-Berichtausgabe darf keinen Link/Junction enthalten")
    folder.mkdir(parents=True, exist_ok=True)
    if not folder.resolve().is_relative_to(root):
        raise PivotStageError("Pivot-Berichtordner liegt außerhalb des Projekts")
    payload = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    digest = sha256(payload.encode("utf-8")).hexdigest()[:16]
    dest = folder / f"{report['profile_id']}-{digest}.json"
    if dest.exists():
        if dest.is_file() and not _is_link(dest) and dest.read_text(encoding="utf-8") == payload:
            return dest
        raise PivotStageError("Vorhandener Stufenplan ist verändert")
    fd, temp = tempfile.mkstemp(dir=folder, prefix=".pivot-bc7-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, dest)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return dest

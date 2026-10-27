"""Explicit, source-bound Zinnenlineal review decisions, never an atlas writer.

An approval is a human preflight decision, not authorization to install or
rewrite images/indexes. Any later apply pipeline must re-check both PNG and
index digests and require a separate release action.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
from typing import Mapping

from .pivot_measurements import (
    MeasurementFile, PivotMeasurementError, PivotReview,
    load_measurements, review_measurements,
)

APPROVAL_SCHEMA = "stronghold-europe.pivot-approval.v1"
ACTIONS = frozenset(("freigegeben", "abgelehnt"))


@dataclass(frozen=True)
class PivotDecision:
    action: str
    note: str = ""
    recorded_at: str = ""

    def validate(self) -> None:
        if not isinstance(self.action, str) or self.action not in ACTIONS:
            raise PivotMeasurementError("Unbekannte Pivot-Freigabeentscheidung")
        if not isinstance(self.note, str) or len(self.note) > 400 or any(
            ord(ch) < 32 for ch in self.note
        ):
            raise PivotMeasurementError("Freigabekommentar ist ungültig oder zu lang")
        if not isinstance(self.recorded_at, str) or not self.recorded_at:
            raise PivotMeasurementError("Zeitpunkt der Entscheidung fehlt")
        try:
            when = datetime.fromisoformat(self.recorded_at)
        except ValueError as exc:
            raise PivotMeasurementError("Ungültiger Freigabezeitpunkt") from exc
        if when.tzinfo is None or when.utcoffset() is None:
            raise PivotMeasurementError("Freigabezeitpunkt benötigt eine Zeitzone")


def can_approve(row: PivotReview) -> bool:
    """Approval is strictly for a matching old pivot in the shipped index."""
    return (
        row.status == "pruefen"
        and row.side == "geliefert"
        and row.pixel_file is not None
        and row.index_file is not None
        and row.actual_pivot is not None
        and bool(row.pixel_sha256)
        and bool(row.index_sha256)
    )


def save_approval_report(
    measurement_file: MeasurementFile,
    reviews: list[PivotReview],
    project_root: str | Path,
    decisions: Mapping[str, PivotDecision],
) -> Path:
    """Save a content-addressed decision record without touching sprite assets.

    Fail closed when the measurement, source PNG, source index, or reviewed
    status has changed since the preview was loaded. A review from an
    unshipped fallback source cannot authorize any correction.
    """
    if not decisions:
        raise PivotMeasurementError("Keine bewusste Freigabeentscheidung vorhanden")
    if len(reviews) != len(measurement_file.entries) or any(
        r.measurement != m for r, m in zip(reviews, measurement_file.entries)
    ):
        raise PivotMeasurementError("Prüfreihen entsprechen nicht der Messdatei")
    names = {r.measurement.name for r in reviews}
    if not set(decisions).issubset(names):
        raise PivotMeasurementError("Entscheidung verweist auf unbekannten Frame")
    for name, decision in decisions.items():
        if not isinstance(name, str) or not isinstance(decision, PivotDecision):
            raise PivotMeasurementError("Ungültige Freigabeentscheidung")
        decision.validate()
    # Compare the exact bytes of the original input, not just decoded values.
    current = load_measurements(measurement_file.path)
    if current.sha256 != measurement_file.sha256:
        raise PivotMeasurementError("Messdatei nach der Vorschau geändert – neu laden")
    root = Path(project_root).resolve()
    # This rechecks index content, index pivot, real PNG geometry, and hashes.
    latest = review_measurements(current, root)
    if latest != reviews:
        raise PivotMeasurementError(
            "Sprite-Bild, Index oder Prüfergebnis nach der Vorschau geändert – neu laden"
        )
    for row in reviews:
        decision = decisions.get(row.measurement.name)
        if decision and decision.action == "freigegeben" and not can_approve(row):
            raise PivotMeasurementError(
                f"{row.measurement.name}: keine Freigabe ohne geprüften "
                "Ausgangspivot im ausgelieferten Index"
            )
    rows = []
    for row in reviews:
        m = row.measurement
        decision = decisions.get(m.name)
        action = (decision.action if decision else
                  "keine_aenderung" if row.status == "bereits_passend"
                  else "zurueckgestellt")
        rows.append({
            "name": m.name,
            "status": row.status,
            "decision": action,
            "decided_at": decision.recorded_at if decision else None,
            "note": decision.note if decision else "",
            "source": row.side,
            "source_image": str(row.pixel_file) if row.pixel_file else None,
            "source_image_sha256": row.pixel_sha256,
            "source_index": str(row.index_file) if row.index_file else None,
            "source_index_sha256": row.index_sha256,
            "size": [m.width, m.height],
            "offset_px": [m.right, m.up],
            "measured_old": [m.pivot_x, m.pivot_y],
            "current_pivot": list(row.actual_pivot) if row.actual_pivot else None,
            "measured_new": [m.new_pivot_x, m.new_pivot_y],
        })
    record = {
        "schema": APPROVAL_SCHEMA,
        "measurement_path": str(measurement_file.path.resolve()),
        "measurement_sha256": measurement_file.sha256,
        "disclaimer": (
            "Dokumentierte Sichtprüfungsentscheidung; keine Freigabe zum direkten "
            "Schreiben in Spiel, Atlas oder Arbeitskopie. Vor jeder späteren "
            "Anwendung Quelldateien und SHA-256 erneut prüfen."
        ),
        "approved_count": sum(r["decision"] == "freigegeben" for r in rows),
        "rejected_count": sum(r["decision"] == "abgelehnt" for r in rows),
        "rows": rows,
    }
    payload = json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    tag = sha256(payload.encode("utf-8")).hexdigest()[:16]
    folder = root / "work" / "reports" / "pivot-approval"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"zinnen-entscheidung-{measurement_file.sha256[:12]}-{tag}.json"
    if target.exists():
        if target.is_file() and target.read_text(encoding="utf-8") == payload:
            return target
        raise PivotMeasurementError("Vorhandenes Freigabeprotokoll weicht ab")
    fd, temp = tempfile.mkstemp(dir=folder, prefix=".zinnen-", suffix=".tmp")
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

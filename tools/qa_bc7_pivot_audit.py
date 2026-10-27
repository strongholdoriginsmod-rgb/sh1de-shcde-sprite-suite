"""Read-only current BC7 Atlas pivot audit for a Zinnenlineal measurement.

Requires no approval and performs no writes. It resolves the exact cache
atlas from the SHA-pinned published bundle, *not* an arbitrary older ref.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stronghold_europe_de.pivot_bc7_cache import (  # noqa: E402
    PivotCacheEvidenceError, inspect_published_pivot, locate_published_group,
)
from stronghold_europe_de.pivot_measurements import (  # noqa: E402
    PivotMeasurementError, load_measurements, review_measurements,
)
from stronghold_europe_de.release_preflight import (  # noqa: E402
    ReleasePreflightError, _read_json, audit_release,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Zinnenlineal-Pivot nur lesend gegen den real publizierten BC7-Atlas prüfen"
    )
    parser.add_argument("--profile", default="sprite-suite-world-bc7-v2")
    parser.add_argument(
        "--measurement", type=Path, required=True,
        help="Original-Zinnenlineal-Messdatei; keine Freigabe erforderlich",
    )
    args = parser.parse_args(argv)
    source = args.measurement
    if not source.is_absolute():
        source = ROOT / source
    try:
        data = load_measurements(source)
        indexed = review_measurements(data, ROOT)
        preflight = audit_release(ROOT, args.profile)
        if preflight["summary"]["errors"]:
            raise PivotCacheEvidenceError(
                "Produktionsbuild hat Integritätsfehler; Atlasprüfung nicht vertrauenswürdig"
            )
        bundle_path = (
            ROOT / "dist" / args.profile / "StrongholdEuropeDE"
            / "Runtime" / "AssetBundles" / "index.json"
        )
        index, _ = _read_json(bundle_path)
        group_records = {
            row.get("group"): row for row in index["groups"]
            if isinstance(row, dict) and isinstance(row.get("group"), str)
        }
        verified = already = rebuild = unknown = 0
        objects = {}
        for row in indexed:
            m = row.measurement
            if (
                row.status not in ("bereits_passend", "pruefen")
                or row.side != "geliefert"
                or m.group not in group_records
            ):
                unknown += 1
                print(f"NICHT PRÜFBAR {m.name}: {row.reason} ({row.side})")
                continue
            if m.group not in objects:
                objects[m.group] = locate_published_group(
                    ROOT, group_records[m.group]
                )
            cached = objects[m.group]
            if cached is None:
                unknown += 1
                print(f"NICHT PRÜFBAR {m.name}: kein hashidentischer publizierter Cache-Atlas")
                continue
            evidence = inspect_published_pivot(
                cached, m.name,
                measured_size=(m.width, m.height),
                measured_old=(m.pivot_x, m.pivot_y),
                measured_new=(m.new_pivot_x, m.new_pivot_y),
            )
            verified += 1
            if evidence["status"] == "bereits_im_bc7":
                already += 1
                print(
                    f"BEREITS IM BC7 {m.name}: Pivot {evidence['bc7_pivot']} "
                    f"(Cache {evidence['cache_key'][:12]})"
                )
            else:
                rebuild += 1
                print(
                    f"NEUBAU PRÜFEN {m.name}: aktueller BC7-Pivot "
                    f"{evidence['bc7_pivot']} → {evidence['measured_new']} "
                    "(separate Prüfung/Freigabe erforderlich)"
                )
        print(
            f"BC7-Pivot-Audit: {verified} verifiziert, {already} bereits richtig, "
            f"{rebuild} potenzielle Neuprüfung, {unknown} unbekannt. "
            "Keine Datei geändert."
        )
        return 1 if unknown or rebuild else 0
    except (
        OSError, ValueError, KeyError,
        PivotCacheEvidenceError, PivotMeasurementError, ReleasePreflightError
    ) as exc:
        print(f"BC7-Pivot-Abgleich blockiert: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

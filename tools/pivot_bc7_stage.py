"""Prepare a pinned *non-applicable* BC7 pivot-change intent.

No installer, source metadata modification, atlas repack or Unity build.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stronghold_europe_de.pivot_build_stage import (  # noqa: E402
    PivotStageError, prepare_pivot_build_stage, save_pivot_build_stage,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verifizierten BC7-Pivot-Stufenentwurf aus expliziten Quellen erstellen"
    )
    parser.add_argument("--profile", default="sprite-suite-world-bc7-v2")
    parser.add_argument("--approval", type=Path, required=True,
                        help="Explizit gewähltes inhaltsadressiertes Freigabeprotokoll")
    parser.add_argument("--measurement", type=Path, required=True,
                        help="Originale Zinnenlineal-Messdatei (wird erneut geprüft)")
    parser.add_argument("--check-only", action="store_true",
                        help="Nur prüfen; keinen Stufenbericht speichern")
    args = parser.parse_args(argv)
    try:
        stage = prepare_pivot_build_stage(
            ROOT, args.profile, args.approval, args.measurement,
        )
        print(
            f"BC7-Stufenstatus {stage['state']}: "
            f"{stage['change_count']} ausdrücklich freigegebene Korrekturen."
        )
        for row in stage["changes"]:
            provenance = row.get("published_bc7_evidence", {})
            suffix = (
                "verifizierter BC7-Cache" if provenance.get("cache_verified")
                else "BC7-Cache nicht zugeordnet – keine Anwendung erlaubt"
            )
            print(
                f"  {row['name']}: {row['old_pivot']} -> "
                f"{row['proposed_pivot']} (Proof/BC7-Neubau nötig; {suffix})"
            )
        for row in stage.get("already_in_published_bc7", []):
            print(
                f"  BEREITS IM BC7: {row['name']} Pivot {row['bc7_pivot']}; "
                "kein Neubau vorgeschlagen"
            )
        for group in stage.get("verified_cache_group_impacts", []):
            print(
                f"  CACHE-PROJEKTION: {group['group']} "
                f"{group['original_cache_key'][:12]} -> "
                f"{group['projected_cache_key'][:12]}; "
                "noch kein wirklicher Unity-/BC7-Neubau"
            )
        if not args.check_only:
            print("Nicht anwendbarer Stufenbericht:", save_pivot_build_stage(stage, ROOT))
        print("Keine Atlas-, Profil-, Spiel- oder Indexdateien verändert.")
        return 0
    except (OSError, ValueError, PivotStageError) as exc:
        print(f"BC7-Stufenentwurf abgelehnt: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

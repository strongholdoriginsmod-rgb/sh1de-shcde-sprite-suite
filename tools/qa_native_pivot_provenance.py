"""Recheck the published anim_castle native pivot proof from real inputs.

No Unity invocation, no caches/atlases/game writes. With --save-report
only a standalone content-addressed work/reports proof is published.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stronghold_europe_de.pivot_native_provenance import (  # noqa: E402
    PivotNativeProvenanceError, audit_native_geometry, save_native_geometry_audit,
)


def main(argv: list[str] | None = None) -> int:
    parser=argparse.ArgumentParser(
        description=(
            "Prüft native SH1DE-/Crusader-Mappingpivots gegen den "
            "tatsächlich veröffentlichten BC7-Atlas und eingefrorene Proofs"
        )
    )
    parser.add_argument("--profile",default="sprite-suite-world-bc7-v2")
    parser.add_argument("--group",default="anim_castle",
                        help="Aktuell nur anim_castle unabhängig abgenommen")
    parser.add_argument("--save-report",action="store_true",
                        help="Eigenständigen Prüfnachweis nur in work/reports speichern")
    args=parser.parse_args(argv)
    try:
        report=audit_native_geometry(ROOT,args.profile,args.group)
        summary=report["group_proof"]
        native=summary["native_proof"]
        partition=summary["review_partition"]
        print(f"Publizierter nativer BC7-Beweis: {args.profile}/{args.group}")
        print(
            f"{summary['total_frames']} Atlasframes = "
            f"{summary['native_source_frames']} SH1DE-Frames + "
            f"{summary['target_keep_frames']} unveränderte Crusader-Frames"
        )
        print("Mapping-GZIP:",report["source_hashes"]["mapping_gzip_sha256"])
        print("Geometrie:",native["geometry_proof_sha256"])
        print("Herkunft:",native["origin_proof_sha256"])
        print("Quell-RGBA-Proof:",native["source_rgba_sha256"])
        print("Review-Partition:",partition["provenance_sha256"])
        print("Max. Runtime-Ankerfehler (px):",
              native["runtime_anchor_max_error_px"])
        print("Geometrie-/Herkunfts-/Quell-RGBA-Hashes stimmen "
              "EXAKT mit dem eingefrorenen Produktionsprofil überein.")
        if args.save_report:
            output=save_native_geometry_audit(report,ROOT)
            print("Unveränderlicher Prüfbericht:",output)
        print("Keine Sprites, Bundles, Profile, Spiel- oder Cacheobjekte geändert.")
        return 0
    except (OSError,ValueError,PivotNativeProvenanceError) as exc:
        print(f"Nativer BC7-Proof abgelehnt: {exc}",file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())

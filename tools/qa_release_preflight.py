"""Read-only release preflight CLI (no game installation or atlas edits)."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stronghold_europe_de.release_preflight import (  # noqa: E402
    ReleasePreflightError, audit_release, save_preflight,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="SHA-256-Abgleich von BC7-Build, Profil, Index und optionaler Pivot-Freigabe."
    )
    parser.add_argument("--profile", default="sprite-suite-world-bc7-v2")
    parser.add_argument(
        "--approval", type=Path,
        help="Optional: explizit gewähltes JSON aus work/reports/pivot-approval",
    )
    parser.add_argument(
        "--check-only", action="store_true",
        help="Keinen Prüfbericht unter work/reports schreiben",
    )
    args = parser.parse_args(argv)
    try:
        report = audit_release(ROOT, args.profile, approval_file=args.approval)
        for row in report["findings"]:
            print(f"{row['schwere'].upper():8} {row['gruppe']}: {row['text']}")
        stats, summary = report["stats"], report["summary"]
        print(
            f"\n{summary['state']}: {summary['errors']} Fehler, "
            f"{summary['warnings']} Warnungen, "
            f"{stats['verified_outputs']}/{stats['expected_outputs']} Dateien verifiziert"
        )
        if not args.check_only:
            print(f"Prüfbericht: {save_preflight(report, ROOT)}")
        return 1 if summary["errors"] else 0
    except (ReleasePreflightError, OSError) as exc:
        print(f"Prüfung abgebrochen: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

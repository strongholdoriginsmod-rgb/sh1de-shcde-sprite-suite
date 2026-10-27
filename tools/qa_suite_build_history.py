"""Verify and display local Sprite Suite build history without side effects."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"src"))

from stronghold_europe_de.suite_build_history import (  # noqa: E402
    BuildHistoryError, read_build_history,
)


def _print(value: str, *, stream=None) -> None:
    sink = sys.stdout if stream is None else stream
    encoding = getattr(sink, "encoding", None) or "utf-8"
    sink.write(value.encode(encoding, "backslashreplace").decode(encoding) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only SHA-256-chain verification of the local BC7 build journal"
    )
    parser.add_argument("--limit", type=int, default=20,
                        help="Number of newest build attempts to print (1–50)")
    args = parser.parse_args(argv)
    if not 1 <= args.limit <= 50:
        parser.error("--limit must be between 1 and 50")
    try:
        entries=read_build_history(ROOT)
    except (OSError, ValueError, BuildHistoryError) as exc:
        _print(f"BUILD HISTORY INVALID: {exc}",stream=sys.stderr)
        return 2
    _print(f"BC7-Bauverlauf: {len(entries)} Versuche, SHA-256-Kette überprüft.")
    for run in entries[:args.limit]:
        _print(
            f"{run['started_utc']}  {run['profile_id']}  "
            f"{run['state']}  Lauf {run['run_id'][:12]}…"
        )
        sources=run.get("source_hashes")
        if sources:
            _print(
                "    Eingangs-SHA: "
                + ", ".join(
                    f"{name}={digest[:12]}…"
                    for name,digest in sorted(sources.items())
                )
            )
        else:
            _print("    Keine Eingangshashes für diesen älteren Start gespeichert.")
        if run["result"] is None:
            _print("    KEIN verifizierter Abschluss / keine Build-Freigabe.")
        else:
            result=run["result"]
            _print(
                f"    CLI-Code {result['exit_code']}, "
                f"{result['verified_files']} SHA-geprüfte Dateien; "
                "Ingame-/Releasefreigabe: NEIN."
            )
    _print("Nur lokale Historie. Keine Installation, kein erneuter Build.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

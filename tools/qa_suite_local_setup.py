"""Read-only local Suite setup diagnostics, never a build or release approval."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from stronghold_europe_de.suite_setup import diagnose_local_setup


def _line(text: str, *, file=None) -> None:
    stream = file if file is not None else sys.stdout
    codec = getattr(stream, "encoding", None) or "utf-8"
    stream.write(text.encode(codec, errors="backslashreplace").decode(codec) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = diagnose_local_setup(args.root)
    except (OSError, ValueError) as exc:
        _line("Einrichtungsdiagnose nicht möglich: " + str(exc), file=sys.stderr)
        return 2

    if args.json:
        _line(json.dumps(report, ensure_ascii=True, indent=2))
        return 0
    _line(
        f"Lokale Einrichtung: {report['warning_count']} Warnungen, "
        f"{report['notice_count']} Hinweise."
    )
    for item in report["checks"]:
        _line(f"[{item['state'].upper()}] {item['name']}: {item['detail']}")
        if item["state"] != "ok":
            _line("  Nächster Schritt: " + item["next_step"])
    _line("Nur lesend. Keine BC7- oder Ingame-/Releasefreigabe.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

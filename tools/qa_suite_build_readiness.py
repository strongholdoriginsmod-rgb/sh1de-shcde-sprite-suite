"""Inspect prerequisites for a Sprite Suite build without performing it."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stronghold_europe_de.suite_build_readiness import (  # noqa: E402
    BuildReadinessError, audit_build_readiness,
)


def _line(message: str, *, file=None) -> None:
    """Do not crash on Windows consoles with a cp1252-only code page."""
    stream = sys.stdout if file is None else file
    encoding = getattr(stream, "encoding", None) or "utf-8"
    stream.write(message.encode(encoding, "backslashreplace").decode(encoding) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Lokale Voraussetzungen für einen BC7-Paketbau, ohne Build/Installation"
    )
    parser.add_argument("--profile", default="sprite-suite-world-bc7-v2")
    parser.add_argument("--unity", type=str)
    parser.add_argument("--dotnet", type=str)
    parser.add_argument("--replace", action="store_true",
                        help="Die im Hauptfenster ausdrücklich gewählte Ersetzen-Option")
    args = parser.parse_args(argv)
    try:
        result = audit_build_readiness(
            ROOT, args.profile, replace=args.replace,
            unity_hint=args.unity, dotnet_hint=args.dotnet,
        )
    except (OSError, ValueError, BuildReadinessError) as exc:
        _line(f"Voraussetzungsprüfung fehlgeschlagen: {exc}", file=sys.stderr)
        return 2
    _line(
        f"Bau-Bereitschaft {result['profile_id']}: {result['state']}, "
        f"{result['blocker_count']} Blockaden, {result['notice_count']} Hinweise."
    )
    for check in result["checks"]:
        _line(f"  [{check['state'].upper()}] {check['name']}: {check['detail']}")
        if check["state"] != "ok":
            _line(f"    Nächster Schritt: {check['next_step']}")
    _line("Dies bestätigt keinen neuen BC7-Build oder Ingame-/Release-Test.")
    _line("Keine Profile, Spiel-, Cache- oder Ausgabedateien verändert.")
    return 2 if result["blocker_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

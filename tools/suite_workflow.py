"""Shortcuts for reading game assets and building a sprite package.

Nachsicht gilt ausschliesslich fuer die diagnostische Einrichtungspruefung.
Beim echten Paketbau muss die nachgelagerte Validierung erfolgreich sein.
Ein fehlgeschlagener Validate-Schritt darf niemals als erfolgreicher Bau
zurueckgemeldet werden. ``--streng`` (oder SEDE_STRENG=1) bleibt fuer
Diagnosen als blockierende Einstellung verfuegbar.
"""
from pathlib import Path
import argparse
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def strict_requested(flag: bool) -> bool:
    return flag or os.environ.get("SEDE_STRENG", "").strip().lower() in {"1", "ja", "an", "true", "on"}


def run_steps(steps, soft=frozenset(), strict=False):
    env = dict(os.environ)
    if strict:
        env["SEDE_STRENG"] = "1"
    warnings = 0
    for number, args in enumerate(steps):
        print("$ " + " ".join(args), flush=True)
        # Ausgabe ausdruecklich durchreichen: ohne eigenes Konsolenfenster erbt der
        # Unterprozess die Umleitung der Oberflaeche sonst nicht, und Fortschritt
        # wie Fehlermeldungen des Baus gingen verloren (29.09.2026 gefunden).
        try:
            sys.stdout.flush()
            handle = sys.stdout.fileno()
        except (AttributeError, OSError, ValueError):
            handle = None
        result = subprocess.run([sys.executable, *args], cwd=ROOT, env=env, stdout=handle,
                                stderr=subprocess.STDOUT if handle is not None else None,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode:
            if number in soft and not strict:
                warnings += 1
                print(f"WARNUNG (Nachsicht): Schritt meldete Code {result.returncode} - "
                      "Ablauf geht weiter. Details stehen oben; streng: --streng.", flush=True)
                continue
            return result.returncode
    if warnings:
        print(f"Fertig mit {warnings} Warnung(en). Gemessene Nachweise uebernimmt "
              "'tools/pin_digests.py --aus-protokoll'.", flush=True)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--streng", action="store_true", help="Abweichungen blockieren statt warnen")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("prepare", help="Read both games and map their sprites")
    sub.add_parser("check", help="Check selected tools and game paths")
    build = sub.add_parser("build", help="Build and validate the selected package")
    build.add_argument("--profile-id", required=True,
                       choices=sorted(p.stem for p in (ROOT / "profiles").glob("*.json")))
    build.add_argument("--replace", action="store_true")
    args = parser.parse_args(argv)
    strict = strict_requested(args.streng)
    cli = ["-m", "stronghold_europe_de"]
    if args.command == "prepare":
        steps = [cli + ["inventory", "--side", "both"], cli + ["map", "propose"]]
        soft = frozenset()
    elif args.command == "check":
        steps = [[str(ROOT / "tools/suite_bridge.py"), "preflight"], cli + ["doctor"]]
        soft = frozenset({0, 1})
    else:
        # Build outputs are version-bound. No previous 2.7 target, guessed QA
        # install or stale local config may silently authorize a 2.80 build.
        from target_selection_guard import TargetSelectionError, verify_active
        try:
            _, verified = verify_active(root=ROOT)
        except TargetSelectionError as exc:
            print(f"BUILD_BLOCKED: Kein freigegebenes versionspassendes Ziel: {exc}",flush=True)
            return 27
        print(f"BUILD_TARGET_VERIFIED: {verified.build_id} ({verified.files_checked}/5)",flush=True)
        steps = [cli + ["build", "--profile", "profiles/" + args.profile_id + ".json"]
                 + (["--replace"] if args.replace else []),
                 cli + ["validate", "--profile-id", args.profile_id]]
        # The build may have produced files, but a failed validator means
        # the package must NEVER be reported as a completed good build.
        # Lenient mode is appropriate for setup diagnostics only.
        soft = frozenset()
    return run_steps(steps, soft, strict)


if __name__ == "__main__":
    raise SystemExit(main())

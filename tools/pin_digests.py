"""Build repeatedly until every placement proof is measured and pinned.

Every group ships with cryptographic evidence that its frames landed where they
were supposed to: a geometry digest, an origin digest, a source-pixel digest,
and for some paths a derived or reviewed partition on top.  Those values cannot
be predicted - they are a property of the actual conversion - so a new group is
declared with placeholders and the build reports what it measured.

Doing that by hand meant reading a digest out of an error message and pasting it
into two places, once per group, dozens of times.  This does that loop.

    python tools/pin_digests.py

Anything that is not a proof mismatch stops the loop and is printed verbatim.
A placement error must never be papered over by a retry: if a frame landed in
the wrong slot, pinning its digest would only record the mistake as correct.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYTHON = Path(sys.executable)
PROFILE = PROJECT_ROOT / "profiles" / "europe-production.json"
CONTRACT = PROJECT_ROOT / "src" / "stronghold_europe_de" / "gm_atlas.py"

# A group name may contain spaces - "puff of smoke" is a real loader group - so
# these patterns must stop at the ": actual=" that follows the name, never at
# the first whitespace. Matching \S+ silently pinned "puff" and left the real
# group unmeasured, which showed up as one stubborn mismatch that would not
# converge however often the build ran.
NAME = r"(.+?)"

# Native source geometry: the group's frames carry their own placement proof.
GEOMETRY = re.compile(
    rf"Native source geometry proof changed for {NAME}: actual=\((\d+), "
    r"'([0-9a-f]{64})', '([0-9a-f]{64})', '([0-9a-f]{64})'"
)
# A derived partition is placed integrally on the target canvas and additionally
# reports how much mask alpha the placement discarded.
DERIVED = re.compile(
    rf"[Dd]erived frame proof changed for {NAME}: "
    r"actual=\((\d+), (\d+), '([0-9a-f]{64})'"
)
# The reviewed path splits frames into "the European source landed losslessly"
# and "kept the Crusader target"; neither count follows from the mapping alone.
REVIEW_PARTITION = re.compile(
    rf"Review frame partition changed for {NAME}: actual=\((\d+), (\d+), "
    r"'([0-9a-f]{64})', '([0-9a-f]{64})', '([0-9a-f]{64})'\)"
)
REVIEW_V2 = re.compile(
    rf"Review v2 action partition changed for {NAME}: actual=\((\d+), "
    r"'([0-9a-f]{64})', (\d+), '([0-9a-f]{64})', (\d+), "
    r"'([0-9a-f]{64})', '([0-9a-f]{64})'\)"
)
# A *contract* mismatch is the other direction: the code-pinned contract already
# holds reviewed, committed values and the profile disagrees.  The contract wins.
DERIVED_CONTRACT = re.compile(
    rf"Derived proof contract for {NAME} changed: "
    r"actual=\([^)]*\) expected=\((\d+), (\d+), '([0-9a-f]{64})'\)"
)
GEOMETRY_CONTRACT = re.compile(
    rf"Native geometry proof contract for {NAME} changed: "
    r"actual=\([^)]*\) expected=\((\d+), '([0-9a-f]{64})', "
    r"'([0-9a-f]{64})', '([0-9a-f]{64})'\)"
)


# Universal-Suite (29.09.2026): Drift des Zielspiels (Frame-Anzahl, Namen,
# Behalten-Anteil) - tritt beim Wechsel zwischen Spielstaenden auf, z.B.
# anim_drawbridge 128 -> 130 Bilder in 2.80.
TARGET_MANIFEST = re.compile(
    rf"Target frame manifest changed for {NAME}: actual=\((\d+), (\d+), (\d+), (\d+), "
    r"'([0-9a-f]{64})'\)"
)
KEEP_PARTITION = re.compile(rf"Crusader-keep partition changed for {NAME}: (\d+) != (\d+)")


def _set_atlas_fields(group: str, fields: dict) -> None:
    profile = _load()
    for atlas in profile["gm_atlases"]:
        if atlas["gm_file_name"] == group:
            atlas.update(fields)
    _save(profile)


def apply_measurements(flat: str) -> int:
    """Alle erkennbaren Messwerte aus einem Bau- oder Nachsichtprotokoll uebernehmen."""

    pinned = 0
    for match in TARGET_MANIFEST.finditer(flat):
        print(f"  uebernommen (Zielframes): {match.group(1)}")
        _set_atlas_fields(match.group(1), {
            "expected_frame_count": int(match.group(2)),
            "expected_main_count": int(match.group(3)),
            "expected_alt_count": int(match.group(4)),
            "expected_max_index": int(match.group(5)),
            "expected_names_sha256": match.group(6),
        })
        pinned += 1
    for match in KEEP_PARTITION.finditer(flat):
        print(f"  uebernommen (Behalten-Anteil): {match.group(1)}")
        _set_atlas_fields(match.group(1), {"sparse_keep_frame_count": int(match.group(2))})
        pinned += 1
    for match in GEOMETRY.finditer(flat):
        print(f"  uebernommen (Geometrie): {match.group(1)}")
        _pin_geometry(match.group(1), match.group(3), match.group(4), match.group(5))
        pinned += 1
    for match in DERIVED.finditer(flat):
        print(f"  uebernommen (abgeleitete Frames): {match.group(1)}")
        _pin_derived(match.group(1), int(match.group(2)), int(match.group(3)), match.group(4))
        pinned += 1
    for match in REVIEW_PARTITION.finditer(flat):
        print(f"  uebernommen (Review-Aufteilung): {match.group(1)}")
        _update_policy(match.group(1), "review_frame_policy", {
            "expected_source_frame_count": int(match.group(2)),
            "expected_target_frame_count": int(match.group(3)),
            "expected_source_names_sha256": match.group(4),
            "expected_target_names_sha256": match.group(5),
            "expected_provenance_sha256": match.group(6),
        })
        pinned += 1
    for match in REVIEW_V2.finditer(flat):
        print(f"  uebernommen (Review-Aktionen): {match.group(1)}")
        _update_policy(match.group(1), "review_frame_policy", {
            "expected_keep_frame_count": int(match.group(2)),
            "expected_keep_names_sha256": match.group(3),
            "expected_blocked_review_frame_count": int(match.group(4)),
            "expected_blocked_review_names_sha256": match.group(5),
            "expected_fractional_frame_count": int(match.group(6)),
            "expected_fractional_names_sha256": match.group(7),
            "expected_action_origin_status_sha256": match.group(8),
        })
        pinned += 1
    return pinned


def _load() -> dict:
    return json.loads(PROFILE.read_text(encoding="utf-8"))


def _save(profile: dict) -> None:
    PROFILE.write_text(
        json.dumps(profile, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _update_policy(group: str, key: str, fields: dict) -> None:
    profile = _load()
    for atlas in profile["gm_atlases"]:
        if atlas["gm_file_name"] == group and key in atlas:
            atlas[key].update(fields)
    _save(profile)


def _set_digest(block: str, field: str, value: str, group: str) -> str:
    """Ein Digest-Feld setzen, gleich ob dort ein Platzhalter oder ein Wert steht.

    Der Grund, warum es diese Funktion gibt, ist ein Fehler, der am 16.08.2026
    zwoelf Baudurchlaeufe gekostet hat. Gepinnt wurde vorher nur der
    Platzhalter:

        re.sub(rf'({field}=)"0" \\* 64', ...)

    Steht im Vertrag bereits ein echter Digest - und das ist nach dem ersten
    Pinnen immer der Fall - trifft dieses Muster nicht mehr. Der Aufruf lief
    ohne Fehler durch und aenderte nichts. Das Profil bekam den gemessenen
    Wert, der Code-Vertrag behielt den alten, und beim naechsten Durchlauf
    schrieb der Vertragszweig weiter unten den alten Wert ins Profil zurueck.
    Zwei Schreiber, entgegengesetzte Richtungen, kein Fortschritt.

    Deshalb wird hier beides ersetzt - und anschliessend nachgesehen, ob es
    wirklich dasteht. Ein stiller Fehlschlag ist genau das, was hier nicht
    noch einmal passieren darf.
    """

    patched, count = re.subn(
        rf'({re.escape(field)}=)(?:"0" \* 64|"[0-9a-f]{{64}}")',
        lambda match: match.group(1) + f'"{value}"',
        block,
    )
    if count != 1:
        raise SystemExit(
            f"{group}: {field} kommt {count}x vor, erwartet genau einmal - "
            "der Vertrag sieht anders aus als angenommen, nichts geschrieben"
        )
    if f'{field}="{value}"' not in patched:
        raise SystemExit(f"{group}: {field} liess sich nicht setzen")
    return patched


def _pin_geometry(group: str, geometry: str, origin: str, rgba: str) -> None:
    _update_policy(
        group,
        "geometry_policy",
        {
            "expected_geometry_proof_sha256": geometry,
            "expected_origin_proof_sha256": origin,
            "expected_source_rgba_sha256": rgba,
        },
    )
    text = CONTRACT.read_text(encoding="utf-8")
    block = re.search(
        rf'("{re.escape(group)}": NativeSourceGeometryContract\(.*?\n    \),)',
        text,
        re.S,
    )
    if block is None:
        raise SystemExit(f"Kein Geometrievertrag fuer {group}")
    patched = block.group(1)
    for field, value in (
        ("expected_geometry_proof_sha256", geometry),
        ("expected_origin_proof_sha256", origin),
        ("expected_source_rgba_sha256", rgba),
    ):
        patched = _set_digest(patched, field, value, group)
    CONTRACT.write_text(text.replace(block.group(1), patched), encoding="utf-8")


def _pin_derived(group: str, count: int, alpha: int, proof: str) -> None:
    _update_policy(
        group,
        "derived_frame_policy",
        {
            "expected_frame_count": count,
            "expected_discarded_mask_alpha": alpha,
            "expected_frame_proof_sha256": proof,
        },
    )
    text = CONTRACT.read_text(encoding="utf-8")
    block = re.search(
        rf'("{re.escape(group)}": DerivedFrameContract\(.*?\n    \),)', text, re.S
    )
    if block is None:
        raise SystemExit(f"Kein Derived-Vertrag fuer {group}")
    patched = block.group(1)
    patched = re.sub(r"(expected_frame_count=)\d+", rf"\g<1>{count}", patched)
    patched = re.sub(
        r"(expected_discarded_mask_alpha=)\d+", rf"\g<1>{alpha}", patched
    )
    patched = _set_digest(patched, "expected_frame_proof_sha256", proof, group)
    CONTRACT.write_text(text.replace(block.group(1), patched), encoding="utf-8")


def run_until_pinned(max_attempts: int = 80, collect: bool = True) -> int:
    """Build repeatedly until every proof is pinned.

    With `collect`, the builder records every proof mismatch instead of raising
    on the first, so one build measures them all and the loop converges in two
    runs rather than one per group. That matters: a build rebuilds the whole
    catalogue, so the one-at-a-time cost grows with its square.

    The build still fails while anything is unpinned - the collected mismatches
    are raised together before the output is promoted - so a run that ends
    successfully has verified every group, exactly as before.
    """

    environment = dict(os.environ)
    # Vermessen braucht den strengen Modus: nur dort scheitert ein Bau an
    # einem ungepinnten Nachweis und meldet den Messwert.
    environment["SEDE_STRENG"] = "1"
    environment.pop("SEDE_NACHSICHT", None)
    if collect:
        environment["SEDE_COLLECT_PROOF_MISMATCHES"] = "1"
    else:
        environment.pop("SEDE_COLLECT_PROOF_MISMATCHES", None)

    # Wachposten gegen Pendeln. Am 16.08.2026 lief diese Schleife zwoelf Mal
    # durch dieselben drei Gruppen, weil ein Schreiber ins Profil und ein
    # zweiter aus dem Vertrag zurueck arbeitete. Jeder Durchlauf baute den
    # ganzen Katalog neu - rund achtzehn Minuten fuer nichts. Sieht die
    # Schleife denselben Fehlertext ein zweites Mal, ist keine Messung mehr zu
    # holen; dann ist Abbrechen richtig und Weitermachen falsch.
    seen_blobs: dict[str, int] = {}

    for attempt in range(1, max_attempts + 1):
        completed = subprocess.run(
            [
                str(PYTHON),
                "-m",
                "stronghold_europe_de",
                "build",
                "--config",
                "config/installations.local.toml",
                "--profile",
                str(PROFILE.relative_to(PROJECT_ROOT)) if PROFILE.is_relative_to(PROJECT_ROOT) else str(PROFILE),
                "--replace",
            ],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            env=environment,
        )
        if completed.returncode == 0:
            print(f"Durchlauf {attempt}: Build erfolgreich")
            tail = completed.stdout.strip().splitlines()
            if tail:
                print(tail[-1])
            return 0
        blob = completed.stdout + completed.stderr
        flat = blob.replace("\n", " ")

        fingerprint = hashlib.sha256(flat.encode("utf-8", "replace")).hexdigest()
        seen_blobs[fingerprint] = seen_blobs.get(fingerprint, 0) + 1
        if seen_blobs[fingerprint] > 1:
            print(
                f"Durchlauf {attempt}: derselbe Fehler wie schon einmal - "
                "die Schleife pendelt, sie kommt nicht weiter."
            )
            print(
                "Zwei Schreiber arbeiten gegeneinander: Ein Zweig pinnt die "
                "Messung ins Profil, ein anderer schreibt den Code-Vertrag "
                "dorthin zurueck. Der Vertrag ist von Hand zu setzen."
            )
            print(blob.strip()[-2000:])
            return 1

        # In collect mode one run reports many. Pin every one before rebuilding.
        pinned = 0
        for match in GEOMETRY.finditer(flat):
            _pin_geometry(
                match.group(1), match.group(3), match.group(4), match.group(5)
            )
            pinned += 1
        for match in DERIVED.finditer(flat):
            _pin_derived(
                match.group(1),
                int(match.group(2)),
                int(match.group(3)),
                match.group(4),
            )
            pinned += 1
        for match in REVIEW_PARTITION.finditer(flat):
            print(f"  gepinnt (Review-Aufteilung): {match.group(1)}")
            _update_policy(
                match.group(1),
                "review_frame_policy",
                {
                    "expected_source_frame_count": int(match.group(2)),
                    "expected_target_frame_count": int(match.group(3)),
                    "expected_source_names_sha256": match.group(4),
                    "expected_target_names_sha256": match.group(5),
                    "expected_provenance_sha256": match.group(6),
                },
            )
            pinned += 1
        for match in REVIEW_V2.finditer(flat):
            print(f"  gepinnt (Review-Aktionen): {match.group(1)}")
            _update_policy(
                match.group(1),
                "review_frame_policy",
                {
                    "expected_keep_frame_count": int(match.group(2)),
                    "expected_keep_names_sha256": match.group(3),
                    "expected_blocked_review_frame_count": int(match.group(4)),
                    "expected_blocked_review_names_sha256": match.group(5),
                    "expected_fractional_frame_count": int(match.group(6)),
                    "expected_fractional_names_sha256": match.group(7),
                    "expected_action_origin_status_sha256": match.group(8),
                },
            )
            pinned += 1
        for match in TARGET_MANIFEST.finditer(flat):
            _set_atlas_fields(match.group(1), {
                "expected_frame_count": int(match.group(2)),
                "expected_main_count": int(match.group(3)),
                "expected_alt_count": int(match.group(4)),
                "expected_max_index": int(match.group(5)),
                "expected_names_sha256": match.group(6),
            })
            pinned += 1
        for match in KEEP_PARTITION.finditer(flat):
            _set_atlas_fields(match.group(1), {"sparse_keep_frame_count": int(match.group(2))})
            pinned += 1
        if pinned:
            print(f"Durchlauf {attempt}: {pinned} Nachweise vermessen")
            continue

        match = DERIVED_CONTRACT.search(flat)
        if match is not None:
            print(f"Durchlauf {attempt}: {match.group(1)} (Vertrag ins Profil)")
            _update_policy(
                match.group(1),
                "derived_frame_policy",
                {
                    "expected_frame_count": int(match.group(2)),
                    "expected_discarded_mask_alpha": int(match.group(3)),
                    "expected_frame_proof_sha256": match.group(4),
                },
            )
            continue

        match = GEOMETRY_CONTRACT.search(flat)
        if match is not None:
            print(f"Durchlauf {attempt}: {match.group(1)} (Vertrag ins Profil)")
            _update_policy(
                match.group(1),
                "geometry_policy",
                {
                    "expected_geometry_proof_sha256": match.group(3),
                    "expected_origin_proof_sha256": match.group(4),
                    "expected_source_rgba_sha256": match.group(5),
                },
            )
            continue

        print(f"Durchlauf {attempt}: kein Nachweisproblem - Abbruch")
        print(blob.strip()[-2000:])
        return 1

    print(f"Nach {max_attempts} Durchlaeufen immer noch nicht fertig.")
    return 1


def main(argv: list[str] | None = None) -> int:
    import argparse

    global PROFILE
    parser = argparse.ArgumentParser(description=__doc__.split(chr(10) * 2)[0])
    parser.add_argument("--profile", default="profiles/europe-production.json",
                        help="Profil, dessen Nachweise vermessen werden")
    parser.add_argument("--aus-protokoll", nargs="?", const="work/reports/nachsicht-nachweise.log",
                        help="nichts bauen, nur die Messwerte eines Nachsichtbaus uebernehmen")
    parser.add_argument("--max", type=int, default=80)
    args = parser.parse_args(argv)
    PROFILE = (PROJECT_ROOT / args.profile).resolve()
    if args.aus_protokoll:
        log = PROJECT_ROOT / args.aus_protokoll
        try:
            flat = log.read_text(encoding="utf-8").replace(chr(10), " ")
        except OSError:
            print(f"Kein Nachsichtprotokoll unter {log} - erst im Nachsichtmodus bauen.")
            return 0
        count = apply_measurements(flat)
        print(f"{count} Messwerte aus {log.name} in {PROFILE.name} uebernommen.")
        if count:
            log.rename(log.with_suffix(".uebernommen.log"))
        return 0
    return run_until_pinned(max_attempts=args.max)


if __name__ == "__main__":
    sys.exit(main())

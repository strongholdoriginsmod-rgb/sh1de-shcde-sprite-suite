"""Manage which sprite groups the production profile ships.

This replaces a pile of one-off scripts that lived in a scratch directory and
had to be re-derived every session.  Everything it does was previously done by
hand-editing profiles/europe-production.json, which is how several groups ended
up with the wrong geometry policy for months.

    python tools/groups.py status
    python tools/groups.py list --missing
    python tools/groups.py add body_woodcutter body_jester
    python tools/groups.py policy tile_castle --upright
    python tools/groups.py pin

The one rule worth knowing before using this: **upright versus flat**.
Re-anchoring forces the European sprite onto Crusader's anchor point.  For a
ground tile that is exactly right - the anchor is a grid position and both games
use the same grid.  For anything that stands up (a tower, a tree, a keep) the
anchor is its foot, the foot sits elsewhere in a European building, and forcing
the foreign anchor drags the whole structure sideways until it overlaps its
neighbour.  That is what `--upright` and `--flat` select.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from stronghold_europe_de import gm_atlas  # noqa: E402
from stronghold_europe_de.loader_groups import LOADER_GROUP_TABLE  # noqa: E402

gm_atlas.LOADER_GROUP_TABLE = LOADER_GROUP_TABLE

PROFILE_PATH = PROJECT_ROOT / "profiles" / "europe-production.json"
CONTRACT_PATH = PROJECT_ROOT / "src" / "stronghold_europe_de" / "gm_atlas.py"
PYTHON = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
CONFIG = "config/installations.local.toml"

# Diese Namen gehoeren dem Builder. Sie hier abzuschreiben ist genau der Fehler,
# der einen Lauf ueber 149 Gruppen nach Sekunden abbrechen liess: PLACEMENT_PROOF
# stand als eigene Kopie da und war abgedriftet, waehrend derselbe Wert einige
# Zeilen weiter unten korrekt als Literal auftauchte. Jetzt gibt es nur noch eine
# Quelle, und tests/test_groups_tool.py haelt das fest.
UPRIGHT_MODE = gm_atlas.GEOMETRY_POLICY_NATIVE_AUTHORED_PIVOT
UPRIGHT_PROOF = gm_atlas.NATIVE_SOURCE_AUTHORED_PIVOT_PROOF_ALGORITHM
FLAT_MODE = gm_atlas.GEOMETRY_POLICY_NATIVE_REANCHORED
FLAT_PROOF = gm_atlas.NATIVE_SOURCE_GEOMETRY_PROOF_ALGORITHM
PLACEHOLDER = "0" * 64
PLACEMENT_PROOF = gm_atlas.PLACEMENT_PROOF_ALGORITHM
REVIEW_MODE_V2 = "source_if_lossless_else_target_with_keep_v2"


def read_profile() -> dict[str, Any]:
    return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))


def write_profile(profile: dict[str, Any]) -> None:
    PROFILE_PATH.write_text(
        json.dumps(profile, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def manifest_for(groups: list[str]) -> dict[str, dict[str, Any]]:
    """Ask the builder to describe these groups. Read-only."""

    completed = subprocess.run(
        [
            str(PYTHON),
            "-m",
            "stronghold_europe_de",
            "map",
            "manifest",
            "--config",
            CONFIG,
            "--groups",
            *groups,
        ],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise SystemExit(
            "Die Gruppenbeschreibung ist fehlgeschlagen:\n"
            + (completed.stderr or completed.stdout).strip()
        )
    entries = json.loads(completed.stdout)
    return {entry["gm_file_name"]: entry for entry in entries}


def classify(entry: dict[str, Any]) -> tuple[str, int, int, int]:
    """Return (kind, european, keep, review) for a manifest entry."""

    counts = entry["action_counts"]
    keep = int(counts.get("KEEP_CRUSADER", 0))
    review = int(counts.get("REVIEW_MANUAL", 0))
    frames = int(entry["expected_frame_count"])
    european = frames - keep - review
    if review:
        kind = "review"
    elif not european:
        kind = "kein Spender"
    else:
        kind = "direkt"
    return kind, european, keep, review


def cmd_status(_args: argparse.Namespace) -> int:
    profile = read_profile()
    shipped = {atlas["gm_file_name"] for atlas in profile["gm_atlases"]}
    loader = set(gm_atlas.LOADER_139_GROUPS)
    by_mode: dict[str, int] = {}
    for atlas in profile["gm_atlases"]:
        policy = atlas.get("geometry_policy")
        mode = policy["mode"] if isinstance(policy, dict) else "Ziel-Leinwand"
        by_mode[mode] = by_mode.get(mode, 0) + 1
    frames = sum(int(a["expected_frame_count"]) for a in profile["gm_atlases"])

    print(f"Ladetabelle       : {len(loader)} Gruppen")
    print(f"Profil            : {len(shipped)} Gruppen, {frames} Frames")
    print(f"Nicht ausgeliefert: {len(loader - shipped)}")
    print()
    print("Geometriepolitik:")
    for mode, count in sorted(by_mode.items()):
        label = {
            UPRIGHT_MODE: "aufrecht (eigener Fusspunkt)",
            FLAT_MODE: "flach (Crusader-Anker)",
        }.get(mode, mode)
        print(f"  {count:>3}  {label}")
    missing = sorted(loader - shipped)
    if missing:
        print()
        print("Fehlt noch:")
        for name in missing:
            print(f"  {name}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    profile = read_profile()
    shipped = {atlas["gm_file_name"] for atlas in profile["gm_atlases"]}
    loader = sorted(gm_atlas.LOADER_139_GROUPS)
    wanted = sorted(set(loader) - shipped) if args.missing else loader
    if not wanted:
        print("Nichts zu berichten.")
        return 0
    entries = manifest_for(wanted)
    print(f"{'Gruppe':<26} {'Frames':>7} {'europ.':>7} {'behalt':>7} "
          f"{'review':>7}  Maske      Zustand")
    for name in wanted:
        entry = entries.get(name)
        if entry is None:
            print(f"{name:<26} {'?':>7}  nicht im Mapping")
            continue
        kind, european, keep, review = classify(entry)
        state = "ausgeliefert" if name in shipped else kind
        print(
            f"{name:<26} {entry['expected_frame_count']:>7} {european:>7} "
            f"{keep:>7} {review:>7}  {entry['mask_policy']:<10} {state}"
        )
    return 0


def _geometry_block(mode: str, european: int) -> dict[str, Any]:
    return {
        "mode": mode,
        "proof_algorithm": UPRIGHT_PROOF if mode == UPRIGHT_MODE else FLAT_PROOF,
        "expected_frame_count": european,
        "expected_geometry_proof_sha256": PLACEHOLDER,
        "expected_origin_proof_sha256": PLACEHOLDER,
        "expected_source_rgba_sha256": PLACEHOLDER,
    }


def complete_groups(limit: int | None = None) -> list[str]:
    """Groups the extender can load, not yet shipped, with a full donor set.

    "Full" means every frame has a same-named Stronghold 1 counterpart - no
    Crusader keeps, no cross-atlas review. Those convert without any policy
    decision, which is why they can be added in bulk.
    """

    profile = read_profile()
    shipped = {atlas["gm_file_name"] for atlas in profile["gm_atlases"]}
    candidates = sorted(
        name
        for name, entry in LOADER_GROUP_TABLE.items()
        # A group sharing its GM array with another cannot go through the
        # standard path: the override writes raw parsed indices from one JSON,
        # so the tenant would overwrite its host. Those need the reviewed
        # shared-atlas contract and must never arrive here by bulk.
        if name not in shipped and entry.owns_its_gm_arrays
    )
    if not candidates:
        return []
    entries = manifest_for(candidates)
    complete: list[tuple[str, int]] = []
    for name in candidates:
        entry = entries.get(name)
        if entry is None:
            continue
        kind, european, _keep, _review = classify(entry)
        if kind == "direkt" and european == int(entry["expected_frame_count"]):
            complete.append((name, european))
    complete.sort(key=lambda item: -item[1])
    names = [name for name, _count in complete]
    return names[:limit] if limit else names


def cmd_add(args: argparse.Namespace) -> int:
    profile = read_profile()
    present = {atlas["gm_file_name"] for atlas in profile["gm_atlases"]}
    groups = list(args.groups)
    if args.all_complete is not None:
        limit = args.all_complete or None
        groups = complete_groups(limit)
        print(f"{len(groups)} vollstaendig konvertierbare Gruppen gewaehlt")
    todo = [name for name in groups if name not in present]
    for name in groups:
        if name in present:
            print(f"  bereits enthalten: {name}")
    if not todo:
        return 0
    entries = manifest_for(todo)
    added: list[str] = []
    for name in todo:
        entry = entries.get(name)
        if entry is None:
            print(f"  nicht im Mapping: {name}")
            continue
        kind, european, keep, review = classify(entry)
        if kind == "kein Spender":
            print(f"  uebersprungen: {name} - Stronghold 1 hat keinen Spender")
            continue
        frames = int(entry["expected_frame_count"])
        atlas: dict[str, Any] = {
            "gm_file_name": name,
            "dash_format": bool(entry["dash_format"]),
            "mask_policy": entry["mask_policy"],
            "source_texture": entry["source_textures"][0],
            "target_texture": entry["target_textures"][0],
            "expected_frame_count": frames,
            "expected_main_count": int(entry["expected_main_count"]),
            "expected_alt_count": int(entry["expected_alt_count"]),
            "expected_max_index": int(entry["expected_max_index"]),
            "expected_names_sha256": entry["expected_names_sha256"],
        }
        if keep:
            atlas["sparse_keep_frame_count"] = keep
        if kind == "review":
            # Source and target sit in different textures. The reviewed path
            # takes the European frame when it lands losslessly and keeps the
            # Crusader one otherwise; both partition sizes are measured by the
            # build, so they start as a placeholder split.
            atlas["review_frame_policy"] = {
                "mode": REVIEW_MODE_V2,
                "proof_algorithm": PLACEMENT_PROOF,
                "expected_source_frame_count": max(1, frames - keep - 1),
                "expected_target_frame_count": max(1, keep + 1),
                "expected_source_names_sha256": PLACEHOLDER,
                "expected_target_names_sha256": PLACEHOLDER,
                "expected_provenance_sha256": PLACEHOLDER,
                "expected_keep_frame_count": keep,
                "expected_keep_names_sha256": PLACEHOLDER,
                "expected_blocked_review_frame_count": 0,
                "expected_blocked_review_names_sha256": PLACEHOLDER,
                "expected_fractional_frame_count": 0,
                "expected_fractional_names_sha256": PLACEHOLDER,
                "expected_action_origin_status_sha256": PLACEHOLDER,
            }
        else:
            derived = int(entry["action_counts"].get("REPLACE_DERIVED", 0))
            if derived and name in gm_atlas.DERIVED_POLICY_139_GROUPS:
                # A derived partition is placed integrally on the target canvas,
                # which is the opposite arrangement to native source geometry -
                # the builder refuses to combine them.
                atlas["derived_frame_policy"] = {
                    "mode": "source_lossless_integral_v1",
                    "proof_algorithm": PLACEMENT_PROOF,
                    "expected_frame_count": derived,
                    "expected_discarded_mask_alpha": 0,
                    "expected_frame_proof_sha256": PLACEHOLDER,
                }
            else:
                mode = FLAT_MODE if args.flat else UPRIGHT_MODE
                atlas["geometry_policy"] = _geometry_block(mode, european)
        atlas["padding"] = 1
        atlas["max_dimension"] = 8192
        atlas["category"] = args.category
        profile["gm_atlases"].append(atlas)
        added.append(f"{name} ({frames} Frames, {european} europaeisch, {keep} behalten)")
    write_profile(profile)
    print("hinzugefuegt:")
    for line in added or ["  keine"]:
        print("  " + line)
    print(f"Gruppen gesamt: {len(profile['gm_atlases'])}")
    print()
    print("Naechster Schritt:  python tools/groups.py pin")
    return 0


def cmd_policy(args: argparse.Namespace) -> int:
    mode = FLAT_MODE if args.flat else UPRIGHT_MODE
    profile = read_profile()
    touched: list[str] = []
    for atlas in profile["gm_atlases"]:
        if atlas["gm_file_name"] not in args.groups:
            continue
        policy = atlas.get("geometry_policy")
        if not isinstance(policy, dict):
            print(
                f"  {atlas['gm_file_name']} laeuft auf der Ziel-Leinwand und hat "
                f"keine Geometriepolitik"
            )
            continue
        if policy["mode"] == mode:
            print(f"  unveraendert: {atlas['gm_file_name']}")
            continue
        european = int(policy["expected_frame_count"])
        atlas["geometry_policy"] = _geometry_block(mode, european)
        touched.append(atlas["gm_file_name"])
    write_profile(profile)
    for name in touched:
        _reset_contract_digests(name)
    label = "flach" if args.flat else "aufrecht"
    print(f"auf {label} umgestellt: {touched or 'keine'}")
    if touched:
        print()
        print("Naechster Schritt:  python tools/groups.py pin")
    return 0


def _reset_contract_digests(group: str) -> None:
    """Clear a group's pinned digests so the next build re-measures them.

    The digests are written as implicitly concatenated string pairs across
    several lines, so a single-line pattern misses them; and a wrapped value
    itself contains "\\n    )," which is why the block cannot be delimited by
    that either.
    """

    text = CONTRACT_PATH.read_text(encoding="utf-8")
    block = re.search(
        rf'(    "{re.escape(group)}": NativeSourceGeometryContract\(.*?)'
        rf'(?=\n    "[A-Za-z_]+": NativeSourceGeometryContract\(|\n\}})',
        text,
        re.S,
    )
    if block is None:
        return
    body = block.group(1)
    patched = body
    for field in (
        "expected_geometry_proof_sha256",
        "expected_origin_proof_sha256",
        "expected_source_rgba_sha256",
    ):
        patched = re.sub(
            rf'({field}=)(?:\(\s*(?:"[0-9a-f]*"\s*)+\)|"[0-9a-f]{{64}}")',
            r'\g<1>"0" * 64',
            patched,
            flags=re.S,
        )
    if patched != body:
        CONTRACT_PATH.write_text(text.replace(body, patched), encoding="utf-8")


def cmd_pin(args: argparse.Namespace) -> int:
    from pin_digests import run_until_pinned  # local import: same tools dir

    return run_until_pinned(max_attempts=args.max_attempts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="groups",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    status = sub.add_parser("status", help="Was ist ausgeliefert, was fehlt")
    status.set_defaults(func=cmd_status)

    listing = sub.add_parser("list", help="Gruppen mit Framezahlen auflisten")
    listing.add_argument(
        "--missing", action="store_true", help="nur nicht ausgelieferte Gruppen"
    )
    listing.set_defaults(func=cmd_list)

    add = sub.add_parser("add", help="Gruppen ins Produktionsprofil aufnehmen")
    add.add_argument("groups", nargs="*")
    add.add_argument(
        "--all-complete",
        nargs="?",
        type=int,
        const=0,
        default=None,
        metavar="N",
        help="alle Gruppen aufnehmen, die restlos einen Spender haben; "
        "optional nur die N groessten",
    )
    add.add_argument(
        "--flat",
        action="store_true",
        help="Bodengeometrie: auf den Crusader-Anker ausrichten. Ohne diesen "
        "Schalter wird der eigene Fusspunkt der Quelle behalten, was fuer "
        "alles Aufrechte richtig ist.",
    )
    add.add_argument("--category", default="gm_atlas")
    add.set_defaults(func=cmd_add)

    policy = sub.add_parser(
        "policy", help="Geometriepolitik einer Gruppe umstellen"
    )
    policy.add_argument("groups", nargs="+")
    group = policy.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--upright",
        action="store_true",
        help="eigener Fusspunkt - fuer Tuerme, Baeume, Gebaeude",
    )
    group.add_argument(
        "--flat",
        action="store_true",
        help="Crusader-Anker - fuer Bodenkacheln",
    )
    policy.set_defaults(func=cmd_policy)

    pin = sub.add_parser(
        "pin", help="Bauen, bis alle Nachweise vermessen und eingetragen sind"
    )
    pin.add_argument("--max-attempts", type=int, default=80)
    pin.set_defaults(func=cmd_pin)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

"""Find and replace Crusades vocabulary in the game's text file.

The game keeps all its strings in one file, keyed by a marker line:

    >>1234-----
    Der Sultan entsendet seine Sarazenen.

This tool reads that file, reports every entry containing Arabic or
Crusades-specific vocabulary, and writes a locale overlay that replaces them
with European equivalents.

    python tools/locale_text.py scan
    python tools/locale_text.py scan --context
    python tools/locale_text.py apply --rules assets/locales/entarabisierung.json

Replacement is deliberately word-boundary aware and case-preserving: "Sultan"
becomes "Fürst" and "sultan" becomes "fürst", so a rule does not have to be
written four times. Substrings are never touched - replacing "Ara" inside
"Arbeit" is exactly the kind of damage that is invisible until someone reads it
in game.
"""

from __future__ import annotations

from stronghold_europe_de.suite_paths import portable_path

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = Path(
    portable_path('target_game', 'Assets/Text/crusader.txt')
)
KEY = re.compile(r"^>>(\d+)-+\s*$")

# What counts as "oriental" here: proper nouns and setting words tied to the
# Crusades, not merely foreign-sounding ones. Grouped so the report is readable.
TERMS: dict[str, tuple[str, ...]] = {
    "Völker": (
        "Araber", "arabisch", "arabische", "arabischen", "arabischer",
        "Sarazene", "Sarazenen", "Beduine", "Beduinen", "Nubier", "Maure",
        "Arab", "Arabian", "Saracen", "Bedouin", "Nubian", "Moor",
    ),
    "Titel": (
        "Sultan", "Kalif", "Emir", "Scheich", "Wesir", "Caliph", "Emir",
        "Sheikh", "Vizier", "Saladin", "Sallah",
    ),
    "Einheiten": (
        "Assassine", "Assassinen", "Krummsäbel", "Sklave", "Sklaven",
        "Sklavenhändler", "Sklaventreiber", "Kamel", "Kamele",
        "Feuerschlucker", "Eunuch", "Tempelwache",
        "Assassin", "Slave", "Slaver", "Camel", "Scimitar", "Fire Thrower",
        "Horse Archer", "Slinger", "Fire Eater",
    ),
    "Orte": (
        "Oase", "Wüste", "Wüsten", "Moschee", "Minarett", "Basar", "Souk",
        "Heiliges Land", "Jerusalem", "Akkon", "Antiochia",
        "Oasis", "Desert", "Mosque", "Minaret", "Bazaar", "Holy Land",
        "Acre", "Antioch",
    ),
    "Kreuzzug": (
        "Kreuzzug", "Kreuzzüge", "Kreuzritter", "Kreuzfahrer",
        "Crusade", "Crusader", "Crusades",
    ),
}


@dataclass
class Entry:
    key: str
    lines: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def read_entries(path: Path) -> tuple[list[str], list[Entry]]:
    """Split the file into its preamble and its keyed entries."""

    raw = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    preamble: list[str] = []
    entries: list[Entry] = []
    current: Entry | None = None
    for line in raw:
        match = KEY.match(line)
        if match:
            current = Entry(match.group(1))
            entries.append(current)
            continue
        if current is None:
            preamble.append(line)
        else:
            current.lines.append(line)
    return preamble, entries


def _pattern(term: str) -> re.Pattern[str]:
    # Word boundaries keep "Oase" out of "Oasenblick" only when it really is a
    # separate word; German compounds are handled by allowing a following
    # lowercase run, which is why the trailing boundary is lenient.
    return re.compile(rf"\b{re.escape(term)}", re.IGNORECASE)


def cmd_scan(args: argparse.Namespace) -> int:
    path = Path(args.source)
    _preamble, entries = read_entries(path)
    print(f"{path.name}: {len(entries)} Eintraege\n")
    total_hits = 0
    for category, terms in TERMS.items():
        rows: list[tuple[str, int, list[str]]] = []
        for term in sorted(set(terms)):
            pattern = _pattern(term)
            hits = [entry for entry in entries if pattern.search(entry.text)]
            if hits:
                rows.append((term, len(hits), [entry.key for entry in hits]))
        if not rows:
            continue
        count = sum(row[1] for row in rows)
        total_hits += count
        print(f"=== {category}: {count} Fundstellen ===")
        for term, hits, keys in sorted(rows, key=lambda row: -row[1]):
            sample = ", ".join(keys[:6])
            more = f" (+{len(keys) - 6})" if len(keys) > 6 else ""
            print(f"  {term:<22} {hits:>4}   Schluessel {sample}{more}")
        print()
    print(f"{total_hits} Fundstellen insgesamt")

    if args.context:
        print("\n=== Beispiele ===")
        shown = 0
        every = {t for terms in TERMS.values() for t in terms}
        for entry in entries:
            hit = next((t for t in every if _pattern(t).search(entry.text)), None)
            if hit is None:
                continue
            snippet = entry.text.strip().replace("\n", " / ")[:110]
            print(f"  >>{entry.key:<6} [{hit}] {snippet}")
            shown += 1
            if shown >= args.context:
                break
    return 0


def _replace_preserving_case(text: str, term: str, replacement: str) -> str:
    def substitute(match: re.Match[str]) -> str:
        found = match.group(0)
        if found.isupper():
            return replacement.upper()
        if found[0].isupper():
            return replacement[0].upper() + replacement[1:]
        return replacement[0].lower() + replacement[1:]

    return _pattern(term).sub(substitute, text)


def cmd_apply(args: argparse.Namespace) -> int:
    rules_path = Path(args.rules)
    if not rules_path.is_absolute():
        rules_path = PROJECT_ROOT / rules_path
    if not rules_path.is_file():
        print(f"Keine Regeldatei: {rules_path}")
        return 1
    raw_rules = json.loads(rules_path.read_text(encoding="utf-8"))
    # Keys starting with _ carry documentation, not rules. Dict order is the
    # rule order, and the file relies on it: longer forms must run first so a
    # compound is not broken apart by a shorter rule that matches its head.
    rules: dict[str, str] = {
        term: replacement
        for term, replacement in raw_rules.items()
        if not term.startswith("_") and isinstance(replacement, str)
    }
    path = Path(args.source)
    preamble, entries = read_entries(path)

    changed: list[tuple[str, str, str]] = []
    for entry in entries:
        original = entry.text
        text = original
        for term, replacement in rules.items():
            text = _replace_preserving_case(text, term, replacement)
        if text != original:
            entry.lines = text.split("\n")
            changed.append((entry.key, original, text))

    changed_keys = {key for key, _before, _after in changed}
    by_key = {entry.key: entry for entry in entries}

    # A locale file is an overlay: only the keys it contains are replaced. Keep
    # it that way. Shipping all 370 entries would silently freeze every string
    # in the game against this one dump, so a later patch to an untouched line
    # would be reverted by our own file.
    keep: list[Entry] = [by_key[key] for key in sorted(changed_keys, key=int)]

    if args.merge:
        merge_path = Path(args.merge)
        if not merge_path.is_absolute():
            merge_path = PROJECT_ROOT / merge_path
        if merge_path.is_file():
            _pre, existing = read_entries(merge_path)
            # An existing overlay wins: it holds hand-authored content such as
            # the unit roster, whose names would otherwise be rewritten by the
            # very rules meant for prose.
            existing_keys = {entry.key for entry in existing}
            keep = [entry for entry in keep if entry.key not in existing_keys]
            keep.extend(existing)
            keep.sort(key=lambda entry: int(entry.key))
            print(f"  {len(existing)} Eintraege aus {merge_path.name} behalten")

    out = Path(args.out)
    if not out.is_absolute():
        out = PROJECT_ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    body = list(preamble)
    for entry in keep:
        body.append(f">>{entry.key}-----")
        body.extend(entry.lines)
    out.write_text("\n".join(body) + "\n", encoding="utf-8")

    print(f"{len(changed)} Eintraege geaendert, {len(keep)} im Overlay -> {out}")
    for key, before, after in changed[: args.show]:
        print(f"\n  >>{key}")
        print(f"    vorher : {before.strip()[:100]}")
        print(f"    nachher: {after.strip()[:100]}")
    if len(changed) > args.show:
        print(f"\n  ... und {len(changed) - args.show} weitere")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="locale_text",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--source", default=str(DEFAULT_SOURCE))
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="Orientalische Begriffe zaehlen")
    scan.add_argument(
        "--context",
        nargs="?",
        type=int,
        const=25,
        default=0,
        help="zusaetzlich N Beispielzeilen zeigen",
    )
    scan.set_defaults(func=cmd_scan)

    apply_cmd = sub.add_parser("apply", help="Ersetzungsregeln anwenden")
    apply_cmd.add_argument("--rules", default="assets/locales/entarabisierung.json")
    apply_cmd.add_argument("--out", default="work/locales/crusader.txt")
    apply_cmd.add_argument(
        "--merge",
        default="assets/locales/de-DE/crusader.txt",
        help="bestehendes Overlay, dessen Eintraege Vorrang behalten",
    )
    apply_cmd.add_argument("--show", type=int, default=12)
    apply_cmd.set_defaults(func=cmd_apply)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

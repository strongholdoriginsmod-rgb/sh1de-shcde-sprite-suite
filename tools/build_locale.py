"""Generate the Europe DE locale overlays from the roster specification.

The SHCDE Script Extender loads ``{mod}/Locales/{locale}/crusader.txt`` by itself
(``GameAssetModManager.RegisterAll`` → ``GameTranslateAPI.LoadModLocalizations``),
so renaming the roster needs no runtime code at all.

Two properties of the extender's parser make this safe to generate:

* a section is stored **positionally** — line *i* of the section becomes
  ``{SECTION}_{i:03d}`` — so the file must pad up to the highest index it changes;
* an **empty line is skipped entirely** (``SaveTranslationSection`` tests
  ``!string.IsNullOrEmpty``), so a blank line leaves the original game string alone.

That second property is what lets this file express "change only these lines"
without reproducing a single character of Firefly's text. The generated overlays
contain nothing but our own names.

Only ``TEXT_CHIMP_NAMES`` is emitted, deliberately. The mouse-over bubble titles
live in ``TEXT_BUBBLE_HELP_TEXT``, and that section cannot be served from a locale
file at all, because the game reads it through *two* incompatible paths:

* units go through ``lookUpText(eTextSections, int)``, which the extender hooks
  before the game's ``index++``, so an override lands one line lower than the game's
  own key;
* ten building names are *literal* keys stored in ``HUD_Buildings.BuildingNames``
  and read through ``lookUpText(string)``, which carries no such shift.

Both paths resolve against the same ``_localizedTexts`` dictionary, so within that
one section the two consumers collide. Concretely: ``TEXT_BUBBLE_HELP_TEXT_349`` is
simultaneously the literal key of the Bedouin Stockade and the override key of the
Camel Lancer's bubble title. Writing it in a locale file renames the building.

The API route does not have this problem — ``SetTemporaryLookUpText`` and
``SetTemporaryLookUpTextEx`` write into *separate* dictionaries. Bubble titles
therefore belong in the runtime companion, not in this file.

``TEXT_CHIMP_NAMES`` is safe: a grep over the whole decompiled Assembly-CSharp finds
no literal ``"TEXT_CHIMP_NAMES_…"`` key anywhere, so it has exactly one consumer.

Usage::

    python tools/build_locale.py            # writes assets/locales/**/crusader.txt
    python tools/build_locale.py --check    # verifies the committed files match
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
ROSTER = REPO_ROOT / "docs" / "europe-unit-roster.json"
ROSTER_TEXT_SPEC = REPO_ROOT / "config" / "unit-roster-text.json"
OUTPUT_ROOT = REPO_ROOT / "assets" / "locales"

# Section numbers as written in a crusader.txt header line (``>>N-----``).
# The extender resolves them through SectionNames[N - 1].
SECTION_CHIMP_NAMES = 89
SECTION_BUBBLE_HELP_TEXT = 8

LOCALES = {
    "de-DE": "deDE",
    "en-US": "enUS",
}


def _load_roster() -> dict:
    return json.loads(ROSTER.read_text(encoding="utf-8"))


def _section(entries: dict[int, str]) -> list[str]:
    """Render one section, padding with blank lines so indices land correctly."""

    if not entries:
        return []
    lines = [""] * (max(entries) + 1)
    for index, value in entries.items():
        if not value:
            raise ValueError(f"refusing to write an empty override at index {index}")
        if "\n" in value or "\r" in value:
            raise ValueError(f"override at index {index} must be a single line")
        if value != value.strip():
            # The extender trims every line, so leading/trailing space is a silent
            # difference between what is written and what the game shows.
            raise ValueError(f"override at index {index} has surrounding whitespace")
        lines[index] = value
    return lines


def render_locale(roster: dict, locale: str, header: str) -> str:
    field = "europe_de" if locale.startswith("de") else "europe_en"

    names = {int(unit["chimp_value"]): unit[field] for unit in roster["units"]}

    lines = [header, ">>TEXTSTART", f">>{SECTION_CHIMP_NAMES}-----"]
    lines.extend(_section(names))
    return "\n".join(lines) + "\n"


SECTION_NAME_BY_NUMBER = {
    SECTION_BUBBLE_HELP_TEXT: "TEXT_BUBBLE_HELP_TEXT",
    SECTION_CHIMP_NAMES: "TEXT_CHIMP_NAMES",
}

# Literal "TEXT_BUBBLE_HELP_TEXT_nnn" keys read straight from
# HUD_Buildings.BuildingNames / GetBuildingName. A locale file must never write
# these positions, because the literal path carries no index shift and would
# rename a building instead of a unit.
LITERAL_BUBBLE_KEYS = frozenset(
    {"010", "011", "013", "022", "023", "024", "025", "026", "232", "349"}
)


def parse_like_extender(text: str) -> dict[str, str]:
    """Reimplement GameTranslateAPI.LoadLocalizationFile / SaveTranslationSection.

    Mirrors the extender exactly: every line is trimmed, ``>>TEXTSTART`` is
    skipped, a ``>>N-----`` line opens a section, and each collected line is
    stored under ``{SectionNames[N-1]}_{i:03d}`` unless it is empty.
    """

    translations: dict[str, str] = {}
    section_number: int | None = None
    collected: list[str] = []

    def flush() -> None:
        if section_number is None:
            return
        name = SECTION_NAME_BY_NUMBER.get(section_number)
        if name is None:
            raise ValueError(f"unmapped section number {section_number}")
        for index, value in enumerate(collected):
            if value:
                translations[f"{name}_{index:03d}"] = value

    for position, raw in enumerate(text.splitlines()):
        line = raw.strip()
        if position == 0 or line == ">>TEXTSTART":
            continue
        if line.startswith(">>") and "-----" in line:
            flush()
            section_number = int(line[2 : line.index("-")])
            collected = []
            continue
        if section_number is not None:
            collected.append(line)
    flush()
    return translations


def _verify(roster: dict, locale: str, text: str) -> int:
    field = "europe_de" if locale.startswith("de") else "europe_en"
    parsed = parse_like_extender(text)
    failures = 0
    for unit in roster["units"]:
        expected = unit[field]
        key = unit["text_key"]
        actual = parsed.get(key)
        marker = "OK  " if actual == expected else "FAIL"
        if actual != expected:
            failures += 1
        print(f"  [{marker}] {key} = {actual!r} (expected {expected!r})")

    extra = set(parsed) - {unit["text_key"] for unit in roster["units"]}
    if extra:
        failures += 1
        print(f"  [FAIL] unexpected keys written: {sorted(extra)}")

    # A locale file must never touch a key the game also reads literally.
    collisions = sorted(
        key
        for key in parsed
        if key.startswith("TEXT_BUBBLE_HELP_TEXT_")
        and key.rsplit("_", 1)[1] in LITERAL_BUBBLE_KEYS
    )
    if collisions:
        failures += 1
        print(f"  [FAIL] collides with a literal building key: {collisions}")
    else:
        print("  [OK  ] no literal-key collision")

    print(f"  {len(parsed)} keys parsed, {failures} problems")
    return failures


def cross_check(roster: dict) -> int:
    """Prove the design roster and the authoritative text spec still agree.

    Two files describe the same 15 units:

    * ``docs/europe-unit-roster.json`` — the design source this generator reads;
    * ``config/unit-roster-text.json`` — what the transactional runtime ships.

    They feed two transports that a build keeps mutually exclusive, so nothing
    else compares them. Without this check the locale profile and the runtime
    profile could ship different German names for the same unit while every
    existing gate stays green.
    """

    spec = json.loads(ROSTER_TEXT_SPEC.read_text(encoding="utf-8"))
    spec_units = {unit["id"]: unit for unit in spec["units"]}
    failures = 0

    for unit in roster["units"]:
        key = unit["key"]
        other = spec_units.get(key)
        if other is None:
            print(f"  [FAIL] {key}: missing from {ROSTER_TEXT_SPEC.name}")
            failures += 1
            continue
        for label, mine, theirs in (
            ("chimp", int(unit["chimp_value"]), int(other["chimp_raw"])),
            ("bubble", int(unit["bubble_index"]), int(other["bubble_raw"])),
            ("de", unit["europe_de"], other["de"]),
            ("en", unit["europe_en"], other["en"]),
        ):
            if mine != theirs:
                print(f"  [FAIL] {key}.{label}: design={mine!r} spec={theirs!r}")
                failures += 1

    unknown = sorted(set(spec_units) - {unit["key"] for unit in roster["units"]})
    if unknown:
        print(f"  [FAIL] only in {ROSTER_TEXT_SPEC.name}: {unknown}")
        failures += 1

    design_buildings = {item["scde_name"]: item for item in roster["buildings"]}
    spec_building_names = {"mercenary_post": "Mercenary Post", "bedouin_stockade": "Bedouin Stockade"}
    for other in spec["buildings"]:
        mapped = spec_building_names.get(other["id"])
        mine = design_buildings.get(mapped or "")
        if mine is None:
            print(f"  [FAIL] building {other['id']}: missing from the design roster")
            failures += 1
            continue
        if mine["europe_de"] != other["de"]:
            print(
                f"  [FAIL] {other['id']}.de: design={mine['europe_de']!r} "
                f"spec={other['de']!r}"
            )
            failures += 1
        # The design records the literal game-space key; the spec is raw space.
        design_raw = int(mine["name_key"].rsplit("_", 1)[1]) - 1
        if design_raw != int(other["title_raw"]):
            print(
                f"  [FAIL] {other['id']}.title: design_raw={design_raw} "
                f"spec={other['title_raw']}"
            )
            failures += 1

    if failures:
        print(f"  {failures} disagreements between the design roster and the text spec")
    else:
        print(
            f"  [OK  ] {len(roster['units'])} units and {len(spec['buildings'])} "
            "buildings agree on index, German and English text"
        )
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the committed overlays match the roster instead of writing",
    )
    parser.add_argument(
        "--verify-keys",
        action="store_true",
        help="re-parse the generated overlays the way the extender does",
    )
    parser.add_argument(
        "--cross-check",
        action="store_true",
        help="prove docs/europe-unit-roster.json and config/unit-roster-text.json agree",
    )
    args = parser.parse_args(argv)

    if args.cross_check:
        print(f"{ROSTER.name} vs {ROSTER_TEXT_SPEC.name}:")
        return 1 if cross_check(_load_roster()) else 0

    if args.verify_keys:
        roster = _load_roster()
        failures = 0
        for locale in LOCALES:
            target = OUTPUT_ROOT / locale / "crusader.txt"
            print(f"{target}:")
            failures += _verify(roster, locale, target.read_text(encoding="utf-8"))
        return 1 if failures else 0

    roster = _load_roster()
    failures = 0
    for locale, header in LOCALES.items():
        rendered = render_locale(roster, locale, header)
        target = OUTPUT_ROOT / locale / "crusader.txt"
        if args.check:
            current = target.read_text(encoding="utf-8") if target.is_file() else None
            if current != rendered:
                print(f"[STALE] {target}", file=sys.stderr)
                failures += 1
            else:
                print(f"[OK] {target}")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8", newline="\n")
        print(f"wrote {target} ({len(rendered.splitlines())} lines)")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

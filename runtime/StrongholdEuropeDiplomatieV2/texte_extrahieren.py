"""Zaehlt jeden ``Text("deutsch", "englisch")``-Aufruf der Diplomatie aus.

Grundlage der Uebersetzungen: nicht eine gepflegte Liste, sondern das, was der
Quelltext wirklich anzeigt. Schreibt ``texte/quelltexte.json`` (deutsch ->
englisch + Fundstellen) und meldet jeden ``Text(``-Aufruf, der nicht aus zwei
Literalen besteht - der muesste von Hand betrachtet werden.
"""

from __future__ import annotations

import collections
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SOURCES = tuple(sorted((PROJECT_ROOT / "runtime" / "StrongholdEuropeDE.Runtime").glob("Diplomacy*.cs"))) \
    + tuple(sorted((PROJECT_ROOT / "runtime" / "StrongholdEuropeDiplomatieV2").glob("DiplomacyV2*.cs")))
TEXTE_DIR = Path(__file__).resolve().parent / "texte"

LITERAL = r'"((?:[^"\\]|\\.)*)"'
# Eine Seite: ein oder mehrere Literale, mit '+' verkettet
SIDE = r"((?:\s*" + LITERAL + r"\s*\+?)+)"
CALL = re.compile(r"\bText\(\s*" + SIDE + r"\s*,\s*" + SIDE + r"\s*\)", re.S)
ANY_CALL = re.compile(r"\bText\(")
NON_LITERAL_CALL = re.compile(r'\bText\((?!\s*")')


def _unescape(value: str) -> str:
    return value.encode("utf-8").decode("unicode_escape").encode("latin-1").decode("utf-8")


def _join(side: str) -> str:
    return "".join(_unescape(m.group(1)) for m in re.finditer(LITERAL, side))


def extract(sources=SOURCES) -> tuple[dict[str, dict[str, object]], int, list[tuple[str, str]]]:
    pairs: dict[str, dict[str, object]] = collections.OrderedDict()
    calls = 0
    unmatched: list[tuple[str, str]] = []
    for path in sources:
        text = path.read_text(encoding="utf-8", errors="replace")
        calls += len(ANY_CALL.findall(text))
        for match in CALL.finditer(text):
            german, english = _join(match.group(1)), _join(match.group(3))
            slot = pairs.setdefault(german, {"en": english, "quellen": set()})
            if slot["en"] != english:
                slot.setdefault("en_varianten", set()).add(english)
            slot["quellen"].add(path.name)
        for match in NON_LITERAL_CALL.finditer(text):
            unmatched.append((path.name, text[match.start():match.start() + 90].replace("\n", " ")))
    return pairs, calls, unmatched


def main() -> int:
    pairs, calls, unmatched = extract()
    TEXTE_DIR.mkdir(exist_ok=True)
    data = {}
    for german, slot in pairs.items():
        entry = {"en": slot["en"], "quellen": sorted(slot["quellen"])}
        if "en_varianten" in slot:
            entry["en_varianten"] = sorted(slot["en_varianten"])
        data[german] = entry
    (TEXTE_DIR / "quelltexte.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(f"Text(-Aufrufe: {calls} | eindeutige deutsche Quelltexte: {len(pairs)}")
    print(f"nicht aus Literalen (von Hand pruefen): {len(unmatched)}")
    for name, ctx in unmatched:
        print("   ", name, "|", ctx)
    lengths = sorted(len(k) for k in pairs)
    if lengths:
        print(f"Laengen: min {lengths[0]}, median {lengths[len(lengths)//2]}, max {lengths[-1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

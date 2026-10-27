"""Uebersetzungen der Diplomatie fuer die im Spiel nativen Sprachen.

Warum (06.09.2026)
------------------
Die Diplomatie zeigt ihre Texte ueber ``Text("deutsch", "englisch")``; jede
andere Spielsprache sah Englisch. Der Benutzer hat den Umfang festgelegt:
Deutsch und Englisch bleiben Quelltext, dazu FR ES PT PL IT RU CS TR UK - Sprachen, die
Stronghold selbst mitbringt (``Translate.locale_*`` / ``FatControler.locale``:
frfr, eses, ptbr, plpl, itit, ruru, cscz, trtr, ukua). Am 08.09.2026
entsprechend dem erweiterten Nutzerauftrag um vier Spielsprachen ergaenzt.

Was hier passiert
-----------------
* ``texte/quelltexte.json`` ist die von ``texte_extrahieren.py`` aus dem
  Quelltext gezaehlte Liste aller deutschen Texte (Schluessel) samt Englisch.
  Keine gepflegte Liste: der Bau prueft, dass sie mit den ``Text(``-Aufrufen
  der Quellen uebereinstimmt - ein neuer Text ohne Eintrag bricht den Bau ab,
  statt still Englisch zu zeigen.
* ``texte/<locale>.json`` bildet jeden deutschen Schluessel auf die
  Uebersetzung ab. Jede Sprache muss vollstaendig sein, darf keinen fremden
  Schluessel und keinen leeren Text enthalten und muss den Leerzeichenrand der
  Verkettung erhalten (``" Tage"`` bleibt ``" jours"``).
* ``render_cs`` schreibt ``GeneratedDiplomacyTexts``; ``Text()`` schlaegt darin
  nach ``FatControler.locale`` nach und faellt sonst auf Englisch zurueck. Die
  Nachschlagehilfe wirft nie.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
TEXTE_DIR = PROJECT_DIR / "texte"
QUELLTEXTE = TEXTE_DIR / "quelltexte.json"
GENERATED_NAME = "GeneratedDiplomacyTexts.g.cs"

# Spielsprachen (FatControler.locale), fuer die eine Tabelle vorliegen muss.
# Deutsch (dede) und Englisch (enus) stehen im Quelltext selbst.
LOCALES = ("cscz", "eses", "frfr", "itit", "plpl", "ptbr", "ruru", "trtr", "ukua")

_CONTROL_CHARS = ("\r", "\n", "\t", "\0")


class TextFehler(ValueError):
    """Eine Uebersetzungstabelle passt nicht zum Quelltext."""


def load_source(path: Path = QUELLTEXTE) -> dict[str, dict[str, object]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not data:
        raise TextFehler(f"Quelltexte leer oder kein Objekt: {path}")
    for german, entry in data.items():
        if not isinstance(entry, dict) or not isinstance(entry.get("en"), str):
            raise TextFehler(f"Quelltext ohne englische Fassung: {german!r}")
    return data


def _extract_module():
    path = PROJECT_DIR / "texte_extrahieren.py"
    spec = importlib.util.spec_from_file_location(
        "stronghold_europe_diplomatie_v2_texte_extrahieren", path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def current_source_pairs() -> dict[str, str]:
    """Deutsch -> Englisch, frisch aus den ``Text(``-Aufrufen der Quellen."""

    pairs, _calls, _unmatched = _extract_module().extract()
    return {german: str(slot["en"]) for german, slot in pairs.items()}


def verify_source_current(source: dict[str, dict[str, object]]) -> None:
    """Der Vertrag zwischen Quelltext und Tabelle: gleiche Schluessel.

    Gemessen wird gegen den Quelltext, nicht gegen die Datei - ein
    ``Text(``-Aufruf, den niemand eingetragen hat, ist der Fehlerfall, den
    dieser Vertrag sichtbar machen soll.
    """

    current = current_source_pairs()
    new = sorted(set(current) - set(source))
    gone = sorted(set(source) - set(current))
    if new or gone:
        raise TextFehler(
            "texte/quelltexte.json ist veraltet - texte_extrahieren.py ausfuehren "
            "und die Uebersetzungen nachziehen. "
            f"Neu im Quelltext ({len(new)}): {new[:5]!r}; "
            f"nicht mehr im Quelltext ({len(gone)}): {gone[:5]!r}"
        )
    changed = [german for german, english in current.items()
               if source[german]["en"] != english]
    if changed:
        raise TextFehler("Englische Quelltexte sind veraltet: " + repr(changed[:5]))


def load_locale(locale: str, texte_dir: Path = TEXTE_DIR) -> dict[str, str]:
    path = texte_dir / f"{locale}.json"
    if not path.is_file():
        raise TextFehler(f"Uebersetzungstabelle fehlt: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TextFehler(f"Uebersetzungstabelle ist kein Objekt: {path}")
    return data


def _edge_shape(text: str) -> tuple[bool, bool]:
    return text.startswith(" "), text.endswith(" ")


def verify_locale(
    locale: str,
    table: dict[str, str],
    source: dict[str, dict[str, object]],
) -> None:
    missing = sorted(set(source) - set(table))
    extra = sorted(set(table) - set(source))
    if missing or extra:
        raise TextFehler(
            f"{locale}: {len(missing)} Quelltexte ohne Uebersetzung {missing[:5]!r}, "
            f"{len(extra)} fremde Schluessel {extra[:5]!r}"
        )
    for german, text in table.items():
        if not isinstance(text, str) or not text:
            raise TextFehler(f"{locale}: leere Uebersetzung fuer {german!r}")
        if any(char in text for char in _CONTROL_CHARS):
            raise TextFehler(f"{locale}: Steuerzeichen in {text!r}")
        # Der Leerzeichenrand traegt die Verkettung (" Tage", "Forderung: ").
        # Zwei gueltige Formen: die deutsche und die englische - Englisch
        # verkuerzt " moeglich." zu ".", das darf eine Sprache ebenso.
        english = str(source[german]["en"])
        expected_fields = sorted(re.findall(r"\{[0-9]+\}", german))
        if sorted(re.findall(r"\{[0-9]+\}", text)) != expected_fields:
            raise TextFehler(f"{locale}: Formatplatzhalter weichen ab: {german!r} -> {text!r}")
        if expected_fields and re.search(r"[{}]", re.sub(r"\{[0-9]+\}", "", text)):
            raise TextFehler(f"{locale}: Ungueltige Formatklammern: {text!r}")
        if _edge_shape(text) not in {_edge_shape(german), _edge_shape(english)}:
            raise TextFehler(
                f"{locale}: Leerzeichenrand weicht ab: {german!r} -> {text!r}"
            )


def load_all(
    texte_dir: Path = TEXTE_DIR,
    verify_sources: bool = True,
) -> tuple[dict[str, dict[str, object]], dict[str, dict[str, str]]]:
    source = load_source(texte_dir / "quelltexte.json")
    if verify_sources:
        verify_source_current(source)
    tables = {}
    for locale in LOCALES:
        table = load_locale(locale, texte_dir)
        verify_locale(locale, table, source)
        tables[locale] = table
    return source, tables


def signature(
    source: dict[str, dict[str, object]], tables: dict[str, dict[str, str]]
) -> str:
    digest = hashlib.sha256()
    for german in source:
        digest.update(german.encode("utf-8") + b"\0")
        for locale in LOCALES:
            digest.update(locale.encode("ascii") + b"=" + tables[locale][german].encode("utf-8") + b"\0")
    return digest.hexdigest()


def summary(
    source: dict[str, dict[str, object]], tables: dict[str, dict[str, str]]
) -> dict[str, object]:
    return {
        "kind": "diplomacy_texts_v1",
        "source_locales": ["dede", "enus"],
        "locales": list(LOCALES),
        "count": len(source),
        "sha256": signature(source, tables),
    }


def _cs(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r", "\\r")
        .replace("\n", "\\n")
        .replace("\t", "\\t")
        .replace("\0", "\\0")
    )
    return '"' + escaped + '"'


def render_cs(
    source: dict[str, dict[str, object]], tables: dict[str, dict[str, str]]
) -> str:
    keys = list(source)
    lines = [
        "// <auto-generated />",
        "// Erzeugt von runtime/StrongholdEuropeDiplomatieV2/bauen.py aus",
        "// texte/quelltexte.json und texte/<locale>.json. Nicht von Hand aendern.",
        "",
        "using System;",
        "using System.Collections.Generic;",
        "",
        "namespace StrongholdEuropeDE.Runtime",
        "{",
        "    /// <summary>",
        "    /// Uebersetzungen der Diplomatie fuer die im Spiel nativen",
        "    /// Sprachen. Schluessel ist der deutsche Quelltext; Deutsch und",
        "    /// Englisch stehen im Quelltext selbst. Die Nachschlagehilfe",
        "    /// wirft nie - ein Fehlschlag heisst Englisch.",
        "    /// </summary>",
        "    internal static class GeneratedDiplomacyTexts",
        "    {",
        f"        internal const int Count = {len(keys)};",
        f"        internal const string Sha256 = {_cs(signature(source, tables))};",
        "",
        "        internal static readonly string[] Locales =",
        "        {",
    ]
    lines.extend(f"            {_cs(locale)}," for locale in LOCALES)
    lines.extend(["        };", "", "        private static readonly string[] Keys =", "        {"])
    lines.extend(f"            {_cs(german)}," for german in keys)
    lines.extend(["        };", "", "        private static readonly string[][] Rows =", "        {"])
    for german in keys:
        lines.append("            new[]")
        lines.append("            {")
        lines.extend(f"                {_cs(tables[locale][german])}," for locale in LOCALES)
        lines.append("            },")
    lines.extend(
        [
            "        };",
            "",
            "        private static readonly Dictionary<string, int> Index = BuildIndex();",
            "",
            "        private static Dictionary<string, int> BuildIndex()",
            "        {",
            "            var index = new Dictionary<string, int>(",
            "                Keys.Length,",
            "                StringComparer.Ordinal);",
            "            for (int i = 0; i < Keys.Length; i++)",
            "            {",
            "                index[Keys[i]] = i;",
            "            }",
            "            return index;",
            "        }",
            "",
            "        internal static int LocaleColumn(string locale)",
            "        {",
            "            if (locale == null)",
            "            {",
            "                return -1;",
            "            }",
            "            for (int i = 0; i < Locales.Length; i++)",
            "            {",
            "                if (string.Equals(",
            "                        Locales[i],",
            "                        locale,",
            "                        StringComparison.OrdinalIgnoreCase))",
            "                {",
            "                    return i;",
            "                }",
            "            }",
            "            return -1;",
            "        }",
            "",
            "        /// <summary>",
            "        /// Uebersetzung fuer <paramref name=\"locale\"/>; false fuer",
            "        /// unbekannte Sprache oder unbekannten Text. Wirft nie.",
            "        /// </summary>",
            "        internal static bool TryTranslate(",
            "            string locale,",
            "            string german,",
            "            out string translated)",
            "        {",
            "            translated = null;",
            "            try",
            "            {",
            "                int column = LocaleColumn(locale);",
            "                int row;",
            "                if (column < 0",
            "                    || german == null",
            "                    || !Index.TryGetValue(german, out row))",
            "                {",
            "                    return false;",
            "                }",
            "                translated = Rows[row][column];",
            "                return !string.IsNullOrEmpty(translated);",
            "            }",
            "            catch (Exception)",
            "            {",
            "                translated = null;",
            "                return false;",
            "            }",
            "        }",
            "    }",
            "}",
            "",
        ]
    )
    return "\n".join(lines)


def write_generated(target: Path, texte_dir: Path = TEXTE_DIR) -> dict[str, object]:
    """Prueft alles, schreibt die C#-Tabelle nach ``target`` und liefert die
    Zusammenfassung fuer das Manifest."""

    source, tables = load_all(texte_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_cs(source, tables), encoding="utf-8", newline="\n")
    return summary(source, tables)

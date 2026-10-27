"""Kompatibilitaetsvertrag der Diplomatie: was das Plugin wirklich bindet.

Warum
-----
Bis zum 06.09.2026 entschied eine exakte Pruefsumme je Voraussetzungs-Assembly
ueber den Start. Gemessen: von den 84 Spiel- und 202 Extender-Mitgliedern, die
die fertige DLL bindet, fehlt in 2.7, 2.80, SE 1.39 und SE 1.44 kein einziges.
Die Pruefsumme schaltete also bei jedem Patch ab, ohne dass etwas Benutztes
gefehlt haette. Der Benutzer hat entschieden: es entscheidet das Mitglied.

Was hier passiert
-----------------
* ``extract_contract`` liest die IL der fertigen DLL (``ilspycmd -il``) und
  zaehlt jede Bindung an eine Fremdassembly vollstaendig aus: Typen, Methoden
  (mit Parameterzahl), Felder. Keine gepflegte Liste - eine gepflegte Liste
  veraltet still.
* ``render_contract_cs`` schreibt daraus ``GeneratedCompatibilityContract``,
  das der Laufzeitwaechter beim Start per Reflexion prueft.
* Der Bau laeuft zweimal: erst mit leerem Vertrag, dann mit dem gemessenen.
  Der zweite Durchgang muss dieselben Bindungen ergeben, sonst bricht der Bau
  ab - der Vertrag darf sich nicht selbst veraendern.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

CONTRACT_ASSEMBLIES = (
    "Assembly-CSharp",
    "SHCDESE",
    "Noesis.NoesisGUI",
    "R3",
    "0Harmony",
    "BepInEx",
    "Zhuqiaomon",
    "System.Memory",
    "UnityEngine",
    "UnityEngine.CoreModule",
    "UnityEngine.AssetBundleModule",
    "UnityEngine.AudioModule",
    "UnityEngine.ImageConversionModule",
)

KIND_TYPE = 0
KIND_METHOD = 1
KIND_FIELD = 2

# Abnahmepunkt 2 (06.09.2026): das Plugin darf weder den Europa-Mod noch
# Origins brauchen. Die IL nennt jede Fremdassembly in eckigen Klammern; ein
# Bezug auf eine dieser Familien bricht den Bau ab.
FORBIDDEN_REFERENCE_PREFIXES = (
    "StrongholdEuropeDE",
    "StrongholdOrigins",
    # Die Speicherbibliothek des Extenders: bis SE 1.45 "Zhuqiaomon", ab
    # SE 2.0.0 "RedBird" (Changelog: BREAKING CHANGE). Wer einen ihrer Typen
    # bindet - meist unbemerkt ueber eine SHCDESE-Signatur wie
    # TryGetUnitByIdEx oder GetAICArray -, bindet die Diplomatie an eine
    # Extender-Hauptversion. Der Zugang laeuft darum ueber
    # DiplomacyFeature.ScriptExtenderNativeBridge (Reflexion ueber den
    # Rueckgabetyp), und der Bau bricht hier ab, wenn jemand zurueckbaut.
    "Zhuqiaomon",
    "RedBird",
)
# IL-Schluesselwoerter, die ebenfalls in eckigen Klammern stehen
_IL_BRACKET_KEYWORDS = frozenset({"in", "out", "opt"})
# Namen duerfen mit einer Ziffer beginnen (['0Harmony']); reine Zahlen sind
# lokale Variablenplaetze (.locals init ([0] ...)), keine Assemblies.
_ANY_ASSEMBLY_REF = re.compile(r"\[('?)([A-Za-z0-9][A-Za-z0-9_.\-]*)\1\]")

_ASSEMBLY_ALTERNATION = "|".join(re.escape(name) for name in CONTRACT_ASSEMBLIES)
_TYPE_CHARS = r"[A-Za-z0-9_.`/]+"
_MEMBER_CHARS = r"[A-Za-z0-9_.`]+"
# Ein Typbezug: [asm]Ns.Typ oder ['asm']Ns.Typ/Geschachtelt
_TYPE_REF = re.compile(
    r"\[('?)(" + _ASSEMBLY_ALTERNATION + r")\1\](" + _TYPE_CHARS + ")"
)
# Hinter jedem Typbezug kann eine generische Instanz ('<...>') stehen und
# danach ein Mitglied ('::Name'). Was hinter dem Namen kommt, entscheidet die
# Art: '(' oder '<...>(' ist eine Methode (letzteres eine generische Methode
# wie Subscribe<T>(...) oder AddComponent<T>()), alles andere ein Feld.
_MEMBER_NAME = re.compile(_MEMBER_CHARS)


def _skip_generic_arguments(text: str, start: int) -> int:
    """Gibt den Index hinter dem '>' zurueck, das das '<' bei ``start``
    schliesst; generische Argumente koennen selbst geschachtelt sein."""

    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char == "<":
            depth += 1
        elif char == ">":
            depth -= 1
            if depth == 0:
                return index + 1
    raise ValueError("unbalanced generic argument list in IL")


def _member_kind(text: str, after_name: int) -> tuple[int, int]:
    """(Art, Parameterzahl) fuer das Mitglied, dessen Name bei ``after_name``
    endet. Gemessen am 06.09.2026: ohne die generische Form wurden
    ``Subscribe<T>(...)`` und ``AddComponent<T>()`` als Felder gezaehlt, und der
    Waechter schaltete wegen zweier Felder ab, die es nie gab."""

    position = after_name
    if position < len(text) and text[position] == "<":
        position = _skip_generic_arguments(text, position)
    if position < len(text) and text[position] == "(":
        return KIND_METHOD, _count_parameters(text, position)
    return KIND_FIELD, -1


@dataclass(frozen=True, order=True)
class Bindung:
    assembly: str
    type_name: str
    member: str
    kind: int
    parameters: int


def _clr_type_name(il_name: str) -> str:
    """IL schreibt geschachtelte Typen mit '/', die CLR mit '+'."""

    return il_name.replace("/", "+")


def _count_parameters(text: str, start: int) -> int:
    """Zaehlt die Parameter der Klammer, die bei ``start`` ('(') beginnt.

    Kommata innerhalb von ``<...>`` (generische Argumente) und ``[...]``
    (Assemblyverweise, Felder) trennen keine Parameter.
    """

    depth_round = 0
    depth_angle = 0
    depth_square = 0
    count = 0
    seen_content = False
    for index in range(start, len(text)):
        char = text[index]
        if char == "(":
            depth_round += 1
            continue
        if char == ")":
            depth_round -= 1
            if depth_round == 0:
                return count + 1 if seen_content else 0
            continue
        if char == "<":
            depth_angle += 1
        elif char == ">":
            depth_angle -= 1
        elif char == "[":
            depth_square += 1
        elif char == "]":
            depth_square -= 1
        elif (
            char == ","
            and depth_round == 1
            and depth_angle == 0
            and depth_square == 0
        ):
            count += 1
            continue
        if not char.isspace():
            seen_content = True
    raise ValueError("unbalanced parameter list in IL")


def extract_contract(il_text: str) -> list[Bindung]:
    """Alle Bindungen an Vertragsassemblies aus dem IL-Text, eindeutig."""

    found: set[Bindung] = set()
    for line in il_text.splitlines():
        if "[" not in line:
            continue
        for match in _TYPE_REF.finditer(line):
            assembly = match.group(2)
            type_name = _clr_type_name(match.group(3))
            found.add(Bindung(assembly, type_name, "", KIND_TYPE, -1))
            # Gemessen am 06.09.2026: R3EventHook`1<...>::get_Observable wurde
            # nur als Typ gezaehlt, das Mitglied blieb ungeprueft. Generische
            # Argumente des Typs werden deshalb uebersprungen, bevor nach
            # '::' gesucht wird; die darin genannten Typen findet finditer
            # ohnehin als eigene Bezuege.
            position = match.end(3)
            if position < len(line) and line[position] == "<":
                position = _skip_generic_arguments(line, position)
            if not line.startswith("::", position):
                continue
            name = _MEMBER_NAME.match(line, position + 2)
            if name is None:
                continue
            kind, parameters = _member_kind(line, name.end())
            found.add(Bindung(assembly, type_name, name.group(0), kind, parameters))
    return sorted(found)


def referenced_assemblies(il_text: str) -> list[str]:
    """Jede Fremdassembly, die die IL in eckigen Klammern nennt - auch die
    ausserhalb des Vertrags (mscorlib, System...). Generische Indizes
    (``[0]``) und Parameterattribute (``[out]``) sind keine Assemblies."""

    found: set[str] = set()
    for match in _ANY_ASSEMBLY_REF.finditer(il_text):
        name = match.group(2)
        if name in _IL_BRACKET_KEYWORDS or name.isdigit():
            continue
        found.add(name)
    return sorted(found)


def forbidden_references(il_text: str) -> list[str]:
    return [
        name
        for name in referenced_assemblies(il_text)
        if name.startswith(FORBIDDEN_REFERENCE_PREFIXES)
    ]


def assert_independent(il_text: str) -> None:
    """Bricht ab, wenn die DLL den Europa-Mod oder Origins braucht."""

    verboten = forbidden_references(il_text)
    if verboten:
        raise RuntimeError(
            "Die Diplomatie-DLL bindet verbotene Assemblies (Abnahmepunkt 2, "
            f"eigenstaendig; Speicherbibliothek nur ueber die Bruecke): "
            f"{', '.join(verboten)}"
        )


def contract_json(bindungen: list[Bindung]) -> str:
    """Der Vertrag als JSON - Eingabe fuer die Vertragspruefung gegen andere
    Fassungen von Spiel und Extender."""

    import json

    return json.dumps(
        [
            {
                "assembly": b.assembly,
                "type": b.type_name,
                "member": b.member,
                "kind": b.kind,
                "parameters": b.parameters,
            }
            for b in sorted(bindungen)
        ],
        indent=1,
    )


def signature(bindungen: list[Bindung]) -> str:
    digest = hashlib.sha256()
    for b in sorted(bindungen):
        digest.update(
            f"{b.assembly}|{b.type_name}|{b.member}|{b.kind}|{b.parameters}\n".encode("utf-8")
        )
    return digest.hexdigest()


def summary(
    bindungen: list[Bindung],
    il_text: str | None = None,
) -> dict[str, object]:
    per_assembly: dict[str, dict[str, int]] = {}
    for b in bindungen:
        slot = per_assembly.setdefault(
            b.assembly, {"types": 0, "methods": 0, "fields": 0}
        )
        if b.kind == KIND_TYPE:
            slot["types"] += 1
        elif b.kind == KIND_METHOD:
            slot["methods"] += 1
        else:
            slot["fields"] += 1
    result: dict[str, object] = {
        "kind": "il_member_contract_v1",
        "bindings": len(bindungen),
        "sha256": signature(bindungen),
        "per_assembly": dict(sorted(per_assembly.items())),
    }
    if il_text is not None:
        result["referenced_assemblies"] = referenced_assemblies(il_text)
        result["forbidden_reference_prefixes"] = list(FORBIDDEN_REFERENCE_PREFIXES)
        result["forbidden_references_found"] = forbidden_references(il_text)
    return result


def _cs(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render_contract_cs(
    bindungen: list[Bindung],
    engine_relative_path: str,
    engine_size: int,
    engine_sha256: str,
) -> str:
    ordered = sorted(bindungen)
    lines = [
        "// <auto-generated />",
        "// Erzeugt von runtime/StrongholdEuropeDiplomatieV2/bauen.py aus der IL",
        "// der fertigen DLL. Nicht von Hand aendern.",
        "",
        "namespace StrongholdEuropeDE.Runtime",
        "{",
        "    /// <summary>",
        "    /// Jede Bindung dieses Baus an eine Fremdassembly. Der Waechter",
        "    /// prueft beim Start, ob sie vorhanden ist - das Mitglied",
        "    /// entscheidet, nicht die Pruefsumme.",
        "    /// </summary>",
        "    internal static class GeneratedCompatibilityContract",
        "    {",
        f"        internal const int Count = {len(ordered)};",
        f"        internal const string Sha256 = {_cs(signature(ordered))};",
        f"        internal const string EngineRelativePath = {_cs(engine_relative_path)};",
        f"        internal const long EngineSize = {int(engine_size)};",
        f"        internal const string EngineSha256 = {_cs(engine_sha256)};",
        "        internal static readonly string[] Assemblies =",
        "        {",
    ]
    lines.extend(f"            {_cs(b.assembly)}," for b in ordered)
    lines.extend(["        };", "        internal static readonly string[] Types =", "        {"])
    lines.extend(f"            {_cs(b.type_name)}," for b in ordered)
    lines.extend(["        };", "        internal static readonly string[] Members =", "        {"])
    lines.extend(f"            {_cs(b.member)}," for b in ordered)
    lines.extend(["        };", "        internal static readonly int[] Kinds =", "        {"])
    lines.extend(f"            {b.kind}," for b in ordered)
    lines.extend(["        };", "        internal static readonly int[] Parameters =", "        {"])
    lines.extend(f"            {b.parameters}," for b in ordered)
    lines.extend(["        };", "    }", "}", ""])
    return "\n".join(lines)


def locate_ilspycmd(project_root: Path) -> Path:
    """Der Dekompilierer liegt in der Werkzeugkette des 2.7-Baums; ILSPYCMD
    in der Umgebung uebersteuert."""

    override = os.environ.get("ILSPYCMD")
    candidates = [Path(override)] if override else []
    candidates.append(
        project_root.parent / "StrongholdEuropeDE" / "work" / "toolchains"
        / "ilspycmd" / "ilspycmd.exe"
    )
    candidates.append(
        project_root / "work" / "toolchains" / "ilspycmd" / "ilspycmd.exe"
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        "ilspycmd nicht gefunden; ILSPYCMD setzen oder die Werkzeugkette unter "
        "StrongholdEuropeDE/work/toolchains/ilspycmd anlegen"
    )


def il_from_dll(ilspycmd: Path, dll: Path) -> str:
    """Die IL der fertigen DLL als Text (``ilspycmd -il``)."""

    environment = dict(os.environ)
    environment.setdefault("DOTNET_ROLL_FORWARD", "LatestMajor")
    environment["DOTNET_CLI_TELEMETRY_OPTOUT"] = "1"
    environment["DOTNET_NOLOGO"] = "1"
    completed = subprocess.run(
        [str(ilspycmd), "--disable-updatecheck", "-il", str(dll)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
        timeout=300,
        check=False,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        raise RuntimeError(
            "ilspycmd konnte die IL nicht erzeugen: "
            + "\n".join((completed.stdout + "\n" + completed.stderr).splitlines()[-10:])
        )
    return completed.stdout


def extract_from_il(il_text: str) -> list[Bindung]:
    bindungen = extract_contract(il_text)
    if not bindungen:
        raise RuntimeError("Die IL enthaelt keine einzige Vertragsbindung - Extraktion defekt")
    return bindungen


def extract_from_dll(ilspycmd: Path, dll: Path) -> list[Bindung]:
    return extract_from_il(il_from_dll(ilspycmd, dll))

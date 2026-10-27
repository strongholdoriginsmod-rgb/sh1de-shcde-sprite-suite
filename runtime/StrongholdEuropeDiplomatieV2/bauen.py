"""Baut Diplomatie V2 als vollstaendigen, eigenstaendigen V1-Nachfolger.

Ohne ``--install`` wird ausschliesslich unter ``work/`` und ``dist/`` gebaut.
Eine Installation ist absichtlich erst moeglich, nachdem das alte V1-Plugin
aus dem Ziel entfernt wurde: beide besitzen denselben Vanilla-HUD-Patch und
duerfen niemals gleichzeitig aktiv sein.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET


PROJECT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PROJECT_DIR.parent.parent
V1_PROJECT_DIR = PROJECT_DIR.parent / "StrongholdEuropeDiplomatie"
V1_BUILDER_PATH = V1_PROJECT_DIR / "bauen.py"


def _load_v1_builder():
    spec = importlib.util.spec_from_file_location(
        "stronghold_europe_diplomatie_v1_builder", V1_BUILDER_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"V1-Bauhelfer kann nicht geladen werden: {V1_BUILDER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


v1 = _load_v1_builder()

sys.path.insert(0, str(PROJECT_DIR))
import kompatibilitaet as kompat  # noqa: E402
import texte  # noqa: E402

EXTENDER_PINS_PATH = PROJECT_DIR / "extender-pins.json"
VERTRAGSPRUEFUNG_PROJECT = (
    PROJECT_ROOT / "runtime" / "StrongholdEuropeDiplomatieV2.Vertragspruefung"
    / "StrongholdEuropeDiplomatieV2.Vertragspruefung.csproj"
)
VERTRAGSPRUEFUNG_DLL = (
    PROJECT_ROOT / "work" / "runtime-tests" / "diplomacy-vertragspruefung"
    / "bin" / "StrongholdEuropeDiplomatieV2.Vertragspruefung.dll"
)


def _extender_pin() -> dict:
    return json.loads(EXTENDER_PINS_PATH.read_text(encoding="utf-8"))


def _resolve_extender_reference(pin: dict, extra_search: Path | None) -> Path:
    """Die gepinnte Extender- oder Begleit-DLL, gegen die uebersetzt wird.

    Liegt sie nicht in der Werkzeugkette, wird sie aus einer der
    Suchinstallationen geholt - immer mit Groessen- und Pruefsummenpruefung.
    Ohne diese Umlenkung uebersetzt der Bau gegen die aeltere
    Referenzinstallation des Europa-Baus, und ein typisch veraendertes
    Mitglied faellt erst im Spiel auf (gemessen 07.09.2026).
    """

    filename = Path(str(pin["relative_path"]).replace("\\", "/")).name
    ziel = (PROJECT_ROOT / str(pin["toolchain_dir"]) / filename).resolve()

    def passt(kandidat: Path) -> bool:
        if not kandidat.is_file():
            return False
        if kandidat.stat().st_size != int(pin["size"]):
            return False
        return v1._sha256(kandidat) == str(pin["sha256"])

    if passt(ziel):
        return ziel
    quellen: list[Path] = []
    if extra_search is not None:
        quellen.append(Path(extra_search))
    quellen.extend(Path(entry) for entry in pin.get("search_dirs", []))
    for wurzel in quellen:
        kandidat = wurzel / str(pin["relative_path"])
        if passt(kandidat):
            ziel.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(kandidat, ziel)
            if not passt(ziel):
                raise v1.BauFehler(f"Extender-Kopie entspricht nicht dem Pin: {ziel}")
            print(
                f"Extender-Grundfassung {pin['baseline_version']} uebernommen: "
                f"{kandidat}"
            )
            return ziel
    raise v1.BauFehler(
        "Die Extender-Grundfassung "
        f"{pin['baseline_version']} ({pin['size']:,} B, "
        f"{str(pin['sha256'])[:12]}...) wurde nicht gefunden. Gesucht in: "
        + ", ".join(str(q / str(pin["relative_path"])) for q in quellen)
        + f". Erwartet wird sie unter {ziel}."
    )


# Zhuqiaomon (SE 1.x) wurde mit SE 2.0 durch RedBird ersetzt.
_IDS_RETIRED_BY_SE2 = frozenset({"zhuqiaomon"})


def _with_extender_prerequisite(prerequisites, pin: dict, reference: Path):
    """Startvertrag und Compiler auf dieselbe gepruefte V2-Grundfassung setzen.

    Die gemeinsame V1-Voraussetzungstabelle bleibt unveraendert. SHCDESE und
    ausdruecklich gepinnte Begleitbibliotheken erhalten die geprueften
    V2-Identitaeten. Alle anderen Eintraege werden unveraendert uebernommen.
    """

    from stronghold_europe_de.runtime_prerequisites import (
        RuntimePrerequisiteError,
        _read_managed_assembly_metadata,
    )

    entries = [entry for entry in prerequisites.files if entry.id == "shcdese"]
    if len(entries) != 1:
        raise v1.BauFehler("Genau eine SHCDESE-Voraussetzung wird erwartet.")
    reference = reference.resolve()
    try:
        if (reference.stat().st_size != int(pin["size"])
                or v1._sha256(reference) != str(pin["sha256"])):
            raise v1.BauFehler(
                f"Extender-Referenz entspricht nicht dem V2-Pin: {reference}"
            )
        assembly_name, assembly_version, mvid = _read_managed_assembly_metadata(reference)
    except (OSError, RuntimePrerequisiteError) as error:
        raise v1.BauFehler(f"Extender-Identitaet nicht pruefbar: {reference}") from error

    def version_parts(value: str) -> tuple[int, ...]:
        if re.fullmatch(r"[0-9]+(?:\.[0-9]+){0,3}", value) is None:
            raise v1.BauFehler(f"Ungueltige Extender-Version: {value}")
        parts = tuple(int(part) for part in value.split("."))
        return parts + (0,) * (4 - len(parts))

    if (assembly_name != str(pin["assembly"])
            or version_parts(assembly_version) != version_parts(str(pin["baseline_version"]))):
        raise v1.BauFehler(
            f"Extender-Assembly passt nicht zum V2-Pin: {assembly_name} {assembly_version}"
        )
    replacement = replace(
        entries[0],
        relative_path=str(pin["relative_path"]),
        path=reference,
        size=int(pin["size"]),
        sha256=str(pin["sha256"]),
        assembly_name=assembly_name,
        assembly_version=assembly_version,
        mvid=mvid,
    )
    replacements = {"shcdese": replacement}
    removed_ids = set(pin.get("removed_ids", []))
    # 2026-09-28 (Claude): die gemeinsame Europa-Tabelle steht selbst auf
    # SE 2.11; eine vom Pin entfernte Kennung kann dort schon fehlen. Fehlen
    # darf nur, was SE 2.x nachweislich ausgemustert hat - ein Tippfehler im
    # Pin faellt weiterhin auf.
    already_gone = removed_ids - {entry.id for entry in prerequisites.files}
    if already_gone - _IDS_RETIRED_BY_SE2:
        raise v1.BauFehler("Unbekannte entfernte Extender-Voraussetzung")
    for companion in pin.get("companions", []):
        dependency_id = companion["id"]
        matches = [entry for entry in prerequisites.files if entry.id == dependency_id]
        if (dependency_id in replacements or len(matches) > 1 or dependency_id in removed_ids
                or (not matches and companion.get("add") is not True)):
            raise v1.BauFehler(
                f"Genau eine eindeutige Begleit-Voraussetzung wird erwartet: {dependency_id}"
            )
        companion_pin = dict(companion, baseline_version=pin["baseline_version"],
                             toolchain_dir=pin["toolchain_dir"], search_dirs=pin.get("search_dirs", []))
        companion_reference = _resolve_extender_reference(companion_pin, None)
        try:
            if (companion_reference.stat().st_size != int(companion["size"])
                    or v1._sha256(companion_reference) != str(companion["sha256"])):
                raise v1.BauFehler(f"Begleit-Referenz entspricht nicht dem V2-Pin: {dependency_id}")
            name, version, companion_mvid = _read_managed_assembly_metadata(companion_reference)
        except (OSError, RuntimePrerequisiteError) as error:
            raise v1.BauFehler(f"Begleit-Identitaet nicht pruefbar: {dependency_id}") from error
        if (name != companion["assembly"] or version != companion["assembly_version"]
                or companion_mvid != companion["mvid"]):
            raise v1.BauFehler(f"Begleit-Assembly passt nicht zum V2-Pin: {dependency_id}")
        replacements[dependency_id] = replace(matches[0] if matches else entries[0],
            id=dependency_id, roles=tuple(companion.get("roles", matches[0].roles if matches else ("runtime",))),
            path=companion_reference,
            relative_path=companion["relative_path"], size=companion["size"], sha256=companion["sha256"],
            assembly_name=name, assembly_version=version, mvid=companion_mvid)
    return replace(
        prerequisites,
        script_extender_version=str(pin["baseline_version"]),
        files=tuple(replacements.get(entry.id, entry)
                    for entry in prerequisites.files if entry.id not in removed_ids)
            + tuple(replacements[key] for key in sorted(replacements)
                    if key not in {entry.id for entry in prerequisites.files}),
    )


def _pruefe_signaturen(dll: Path, game_dir: Path) -> None:
    """Loest jede Mitgliedsreferenz gegen die Zielinstallation auf.

    Der Mitgliedervertrag fuehrt Name und Parameterzahl; das reicht nicht,
    wenn ein Mitglied denselben Namen behaelt und den Typ wechselt. Genau das
    ist am 07.09.2026 passiert. Vor der Installation wird deshalb geprueft,
    was der JIT im Spiel pruefen wuerde.
    """

    dotnet, environment = v1._resolve_pinned_dotnet_sdk(v1.load_config(v1.CONFIG_PATH))
    environment = dict(environment)
    environment.setdefault("DOTNET_ROLL_FORWARD", "Major")
    # Always build from current checker sources; an old DLL must not silently
    # weaken the signature gate after fixes to its resolver.
    subprocess.run(
        [dotnet, "build", str(VERTRAGSPRUEFUNG_PROJECT), "-c", "Release",
         "--nologo"],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=600,
        check=True,
    )
    se = game_dir / "BepInEx" / "plugins" / "000shcdese"
    managed = (
        game_dir / "Stronghold Crusader Definitive Edition_Data" / "Managed"
    )
    ziele = ";".join(
        str(pfad)
        for pfad in [
            se / "SHCDESE.dll",
            se / "R3.dll",
            se / "System.Memory.dll",
            game_dir / "BepInEx" / "core" / "0Harmony.dll",
            game_dir / "BepInEx" / "core" / "BepInEx.dll",
            managed / "Assembly-CSharp.dll",
            managed / "UnityEngine.CoreModule.dll",
            managed / "UnityEngine.dll",
            managed / "UnityEngine.AssetBundleModule.dll",
            managed / "UnityEngine.AudioModule.dll",
            managed / "UnityEngine.ImageConversionModule.dll",
            managed / "Noesis.NoesisGUI.dll",
            managed / "mscorlib.dll",
            managed / "System.dll",
            managed / "System.Core.dll",
        ]
        if pfad.is_file()
    )
    completed = subprocess.run(
        [dotnet, str(VERTRAGSPRUEFUNG_DLL), "--signaturen", str(dll),
         f"ziel={ziele}"],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        check=False,
    )
    if completed.returncode == 0:
        bericht = json.loads(completed.stdout)
        rows = bericht.get("results", [])
        if (bericht.get("compatible") is not True or len(rows) != 1
                or not isinstance(bericht.get("member_refs"), int)
                or bericht["member_refs"] <= 0
                or rows[0].get("checked") != bericht["member_refs"]
                or rows[0].get("skipped") != 0
                or rows[0].get("missing_count") != 0):
            raise v1.BauFehler("Signaturpruefung hat nicht jede Referenz vollstaendig aufgeloest")
        geprueft = sum(int(e["checked"]) for e in bericht["results"])
        print(
            f"Signaturen aufloesbar: {geprueft} von {bericht['member_refs']} "
            "Mitgliedsreferenzen gegen die Zielinstallation"
        )
        return
    fehler = completed.stdout
    try:
        bericht = json.loads(completed.stdout)
        fehler = "\n".join(
            "    " + eintrag
            for ergebnis in bericht["results"]
            for eintrag in ergebnis["missing"]
        )
    except Exception:
        pass
    raise v1.BauFehler(
        "Mitgliedsreferenzen lassen sich in der Zielinstallation nicht "
        "aufloesen - das Spiel wuerde beim ersten Zugriff ausfallen:\n"
        + fehler
    )

PLUGIN_FOLDER = "StrongholdEuropeDiplomatieV2"
ASSEMBLY_NAME = "StrongholdEuropeDiplomatieV2"
MOD_GUID = "strongholdeuropede.diplomatie.v2.private"
MOD_VERSION = "2.4.0"  # development only; not release-approved
PLUGIN_DISPLAY_NAME = "Stronghold Crusader Diplomatie V2 (Private)"
PACKAGE_DISPLAY_NAME = "Stronghold Crusader Diplomatie V2"
SAVE_DATA_IDENTIFIER = "StrongholdEuropeDE.Diplomacy.v2"
LEGACY_SAVE_DATA_IDENTIFIER = "StrongholdEuropeDE.Diplomacy.v1"
SAVE_ENVELOPE_SCHEMA_VERSION = 14
MINIMUM_SAVE_ENVELOPE_SCHEMA_VERSION = 2
XAML_OUTPUT = v1.XAML_OUTPUT
V2_XAML_FRAGMENT = PROJECT_DIR / "HUD_AlliesPanel.V2.fragment.xml"
V2_VANILLA_RESOURCE_KEYS = frozenset(
    {
        "BTN_SH_Plain",
        "BTN_RADIO_Image",
        "Panel_Divider",
        "booleanToVisibilityConverter",
        "UI-Buttons C001",
        "UI-Buttons C002",
        "UI-Buttons C003",
        "UI-Buttons C004",
    }
)
V2_REQUIRED_ELEMENT_NAMES = frozenset(
    {
        "CrusaderDiplomacyV2Panel",
        "CrusaderDiplomacyV2Ruler",
        "CrusaderDiplomacyV2Agreement",
        "CrusaderDiplomacyV2AttitudeTitle",
        "CrusaderDiplomacyV2AttitudeLine1",
        "CrusaderDiplomacyV2Gratitude",
        "CrusaderDiplomacyV2Respect",
        "CrusaderDiplomacyV2AttitudeLine2",
        "CrusaderDiplomacyV2Reliability",
        "CrusaderDiplomacyV2TrustCeiling",
        "CrusaderDiplomacyV2StrategicTitle",
        "CrusaderDiplomacyV2StrategicLine1",
        "CrusaderDiplomacyV2Threat",
        "CrusaderDiplomacyV2Dependency",
        "CrusaderDiplomacyV2StrategicLine2",
        "CrusaderDiplomacyV2CommonEnemies",
        "CrusaderDiplomacyV2AllianceCount",
        "CrusaderDiplomacyV2DemandTitle",
        "CrusaderDiplomacyV2DemandLine1",
        "CrusaderDiplomacyV2DemandLine2",
        "CrusaderDiplomacyV2ActionHint",
        "CrusaderDiplomacyV2Primary",
        "CrusaderDiplomacyV2PrimaryLabel",
        "CrusaderDiplomacyV2Fealty",
        "CrusaderDiplomacyV2FealtyLabel",
        "CrusaderDiplomacyV2DetailsPanel",
        "CrusaderDiplomacyV2Send",
        # Buendnisuebersicht (07.09.2026): zweite Ebene ueber derselben Tafel,
        # umgeschaltet mit einem fuenften Knopf in einer zweiten Reihe.
        "CrusaderDiplomacyV2OverviewButton",
        "CrusaderDiplomacyV2DetailsButton",
        "CrusaderDiplomacyV2DetailsLabel",
        "CrusaderDiplomacyV2OverviewLabel",
        "CrusaderDiplomacyV2OverviewPanel",
        "CrusaderDiplomacyV2OverviewTitle",
        "CrusaderDiplomacyV2OverviewHeader",
        "CrusaderDiplomacyV2OverviewRow1",
        "CrusaderDiplomacyV2OverviewRow2",
        "CrusaderDiplomacyV2OverviewRow3",
        "CrusaderDiplomacyV2OverviewRow4",
        "CrusaderDiplomacyV2OverviewRow5",
        "CrusaderDiplomacyV2OverviewRow6",
        "CrusaderDiplomacyV2OverviewRow7",
        "CrusaderDiplomacyV2OverviewFooter",
        "CrusaderDiplomacyV2SendLabel",
        "CrusaderDiplomacyV2Orders",
        "CrusaderDiplomacyV2OrdersLabel",
        "CrusaderDiplomacyV2Break",
        "CrusaderDiplomacyV2BreakLabel",
        # 10.09.2026: Forderungen entstehen auch bei Fuersten, mit denen noch
        # kein Buendnis besteht (Verhandlungsbedingungen). Die Uebersicht fuehrt
        # nur Verbuendete - der Ablehnen-Knopf der Aktionsleiste war fuer genau
        # jene Forderungen unerreichbar. Deshalb steht er auch in der
        # Detailansicht, unter den Kennzahlen.
        "CrusaderDiplomacyV2DeclineDemand",
        "CrusaderDiplomacyV2DeclineDemandLabel",
    }
)
V2_ACTION_CONTRACT = {
    "CrusaderDiplomacyV2Primary": "Request",
    "CrusaderDiplomacyV2Send": "Send",
    "CrusaderDiplomacyV2Orders": "Orders",
    "CrusaderDiplomacyV2Break": "Diplomacy:Break",
    "CrusaderDiplomacyV2DeclineDemand": "Diplomacy:DeclineDemand",
    "CrusaderDiplomacyV2Fealty": "Diplomacy:Fealty",
    # Buendnisuebersicht (07.09.2026), zweite Knopfreihe.
    "CrusaderDiplomacyV2OverviewButton": "Diplomacy:Overview",
    "CrusaderDiplomacyV2DetailsButton": "Diplomacy:Details",
}

# Name -> (Spalte, Reihe). Bis 08.09.2026 wurde die Lage aus dem Listenindex
# gerechnet (index % 3 / index // 3); mit dem siebten Knopf geht das nicht mehr
# auf, und eine Reihe mit einem einzigen Knopf ist unausgewogen (Einwand des
# Benutzers 07.09.2026). Reihe 3 traegt beide Forderungsaktionen: sie erscheinen
# und verschwinden gemeinsam mit der offenen Forderung.
V2_ALLIANCE_ACTION_GRID = {
    "Send": (0, 0), "RequestGoods": (1, 0), "Orders": (2, 0),
    "Fealty": (0, 1), "Break": (2, 1),
    "Fulfill": (0, 2), "Decline": (1, 2),
}
V2_ALLIANCE_ACTIONS = tuple(V2_ALLIANCE_ACTION_GRID)
V2_REQUIRED_ELEMENT_NAMES = V2_REQUIRED_ELEMENT_NAMES | frozenset({
    "CrusaderDiplomacyV2AllianceRoleHeader",
    "CrusaderDiplomacyV2AllianceDutyHeader",
}) | frozenset(
    f"CrusaderDiplomacyV2Alliance{kind}{row}"
    for kind in ("Row", "Member", "Role", "Duty", "Order")
    for row in range(1, 8)
) | frozenset(
    "CrusaderDiplomacyV2Alliance" + action + suffix
    for action in V2_ALLIANCE_ACTIONS for suffix in ("", "Label")
)

# The extended V2.4 Noesis trade panel participates in the SAME strict
# original XAML contract. A missing button, incorrect command or duplicated
# binding cannot silently ship as an inert decorative control.
V2_TRADE_ACTIONS = (
    "FromNext","ToNext",
    "From5","From10","From25","From100","From500",
    "To5","To10","To25","To100","To500",
    "Send","Accept","Decline","Counter","Close",
)
V2_TRADE_REQUIRED_ELEMENT_NAMES = frozenset(
    {
        "CrusaderDiplomacyV2TradeOpen",
        "CrusaderDiplomacyV2TradeOpenLabel",
        "CrusaderDiplomacyV2TradeGrid",
        "CrusaderDiplomacyV2TradeTitle",
        "CrusaderDiplomacyV2TradeRelationship",
        "CrusaderDiplomacyV2TradeOfferText",
        "CrusaderDiplomacyV2TradeRequestText",
        "CrusaderDiplomacyV2TradeIncoming",
        "CrusaderDiplomacyV2TradeStatus",
        "CrusaderDiplomacyV2TradeFromLabel",
        "CrusaderDiplomacyV2TradeToLabel",
        "CrusaderDiplomacyV2TradeOfferIcon",
        "CrusaderDiplomacyV2TradeRequestIcon",
        "CrusaderDiplomacyV2TradeFromAmountInput",
        "CrusaderDiplomacyV2TradeToAmountInput",
    }
) | frozenset(
    "CrusaderDiplomacyV2Trade" + action + suffix
    for action in V2_TRADE_ACTIONS
    for suffix in ("","Label")
)
V2_REQUIRED_ELEMENT_NAMES = V2_REQUIRED_ELEMENT_NAMES | V2_TRADE_REQUIRED_ELEMENT_NAMES

# Saubere, unveraenderte Crusader-DE-2.80-Oberflaeche aus einer Installation,
# in der nur BepInEx und der Script Extender 1.44 aktiv sind. Diese Dateien
# werden nicht ausgeliefert; sie sind der reproduzierbare Bau- und
# Kompatibilitaetsbeleg fuer alle vom Fragment verwendeten Vanilla-Ressourcen.
VANILLA_UI_REFERENCE_ROOT = (
    PROJECT_ROOT / "work" / "references" / "shcde-2.80-se144-ui"
)
VANILLA_UI_REFERENCE_FILES = (
    {
        "role": "radio_button_style",
        "relative_path": "BepInEx/plugins/000shcdese/Override/Assets/GUI/XAMLResources/BTN_RADIO_Image.xaml",
        "size": 4698,
        "sha256": "fe118b88611804da657db5c19a27b056dd0c7f1913530faf65742b5be62a559d",
    },
    {
        "role": "allies_panel",
        "relative_path": (
            "BepInEx/plugins/000shcdese/Override/Assets/GUI/"
            "XAMLResources/HUD_AlliesPanel.xaml"
        ),
        "size": 84163,
        "sha256": (
            "6c927ac4a28fa181b06ef2327c7a084de5c828cc0e4f4a4de46a42dbb40ed0d6"
        ),
    },
    {
        "role": "ui_master_atlas",
        "relative_path": (
            "BepInEx/plugins/000shcdese/Override/Assets/GUI/"
            "Sprites/UI-MasterAtlas.xaml"
        ),
        "size": 258119,
        "sha256": (
            "b4092a81bdef00449f65b37d3988c432c1862f409d085ff84c039a71007cfb88"
        ),
    },
    {
        "role": "plain_button_style",
        "relative_path": (
            "BepInEx/plugins/000shcdese/Override/Assets/GUI/"
            "XAMLResources/BTN_SH_Plain.xaml"
        ),
        "size": 4827,
        "sha256": (
            "b2b074a8c4cb4c0f6e69e48f067bcecab50860e6aa3b66298c0f27555f7c51e0"
        ),
    },
)
V2_RELEASE_STATUS = "in_game_acceptance_required"
V2_LOCAL_STYLE_KEYS = frozenset({"DiplomacyActionButton", "DiplomacyAllianceRow"})

# Die gemessenen Engine- und V1-Regelvertraege bleiben gemeinsame
# Voraussetzungen. Das V2-Projekt und alle V2-Identitaeten sind dagegen
# strikt getrennt.
v1.PROJECT_DIR = PROJECT_DIR
v1.ENGINE_PINS_PATH = V1_PROJECT_DIR / "engine-pins.json"
v1.PLUGIN_FOLDER = PLUGIN_FOLDER
v1.ASSEMBLY_NAME = ASSEMBLY_NAME
v1.MOD_GUID = MOD_GUID
v1.MOD_VERSION = MOD_VERSION
v1.SAVE_DATA_IDENTIFIER = SAVE_DATA_IDENTIFIER


def _verified_vanilla_ui_references() -> list[dict[str, object]]:
    try:
        reference_root = VANILLA_UI_REFERENCE_ROOT.resolve(strict=True)
    except FileNotFoundError as error:
        raise v1.BauFehler(
            "Saubere Crusader-DE-2.80-UI-Referenz fehlt: "
            f"{VANILLA_UI_REFERENCE_ROOT}"
        ) from error

    verified: list[dict[str, object]] = []
    reference_texts: list[str] = []
    for expected in VANILLA_UI_REFERENCE_FILES:
        candidate = reference_root / str(expected["relative_path"])
        try:
            path = candidate.resolve(strict=True)
        except FileNotFoundError as error:
            raise v1.BauFehler(
                "Vanilla-UI-Referenzdatei fehlt: " + str(candidate)
            ) from error
        if reference_root != path and reference_root not in path.parents:
            raise v1.BauFehler(
                "Vanilla-UI-Referenz verlaesst ihren festgelegten Stamm: "
                + str(path)
            )
        actual_size = path.stat().st_size
        actual_hash = v1._sha256(path)
        if (actual_size != expected["size"]
                or actual_hash != expected["sha256"]):
            raise v1.BauFehler(
                "Vanilla-UI-Referenz stimmt nicht mit Crusader DE 2.80/"
                "SHCDESE 1.44 ueberein: "
                f"{expected['relative_path']} ({actual_size} B, {actual_hash})"
            )
        reference_texts.append(path.read_text(encoding="utf-8"))
        verified.append(
            {
                "role": expected["role"],
                "relative_path": expected["relative_path"],
                "size": expected["size"],
                "sha256": expected["sha256"],
                "validation": "matched",
            }
        )

    resource_catalog = "\n".join(reference_texts)
    unavailable = sorted(
        key for key in V2_VANILLA_RESOURCE_KEYS
        if f'x:Key="{key}"' not in resource_catalog
        and f"StaticResource {key}" not in resource_catalog
    )
    if unavailable:
        raise v1.BauFehler(
            "Freigegebene V2-Ressourcen fehlen in der sauberen Vanilla-UI-"
            "Referenz: " + ", ".join(unavailable)
        )
    return verified


def _validate_v2_ui_contract(root: ET.Element, text: str) -> None:
    operations = list(root)
    _validate_patch_content_roots(root)
    height_operations = [
        operation for operation in operations
        if operation.tag == "Operation"
        and operation.get("Type") == "SetAttribute"
        and operation.get("AttributeName") == "Height"
        and operation.get("Value") == "484"
    ]
    native_detail_operations = [
        operation for operation in operations
        if operation.tag == "Operation"
        and operation.get("Type") == "SetAttribute"
        and operation.get("AttributeName") == "Name"
        and operation.get("Value") == "CrusaderDiplomacyNativeDetail"
    ]
    add_operations = [
        operation for operation in operations
        if operation.tag == "Operation" and operation.get("Type") == "Add"
    ]
    if (len(operations) != 4
            or len(height_operations) != 2
            or len(native_detail_operations) != 1
            or len(add_operations) != 1):
        raise v1.BauFehler(
            "V2-HUD-Fragment verletzt den festgelegten Vier-Operationen-Vertrag"
        )

    named: dict[str, list[ET.Element]] = {}
    for element in root.iter():
        name = element.get("Name")
        if name:
            named.setdefault(name, []).append(element)
    actual_v2_names = {
        name for name in named if name.startswith("CrusaderDiplomacyV2")
    }
    duplicate_v2_names = sorted(
        name for name in actual_v2_names if len(named[name]) != 1
    )
    if (actual_v2_names != V2_REQUIRED_ELEMENT_NAMES
            or duplicate_v2_names):
        raise v1.BauFehler(
            "V2-HUD-Elementvertrag weicht ab: "
            f"fehlend={sorted(V2_REQUIRED_ELEMENT_NAMES - actual_v2_names)} "
            f"zusaetzlich={sorted(actual_v2_names - V2_REQUIRED_ELEMENT_NAMES)} "
            f"mehrfach={duplicate_v2_names}"
        )

    panel = named["CrusaderDiplomacyV2Panel"][0]
    # The trade screen is a separate in-game Noesis pane and a true
    # input-capturing sibling, never an OS popup or HUD text overlay.
    trade_grid = named["CrusaderDiplomacyV2TradeGrid"][0]
    details = named["CrusaderDiplomacyV2DetailsPanel"][0]
    if trade_grid not in list(panel) or trade_grid in list(details):
        raise v1.BauFehler("Handelstafel muss ein eigenes Noesis-Pane innerhalb der Diplomatie sein")
    if any(trade_grid.get(k) != v for k,v in {
        "Width":"660","Height":"320","Visibility":"Collapsed"
    }.items()):
        raise v1.BauFehler("Handelstafel hat nicht die originale Fenstergeometrie")
    if named["CrusaderDiplomacyV2TradeOpen"][0] not in set(details.iter()):
        raise v1.BauFehler("Handelsfenster-Oeffnen ist nicht an die Detailansicht gebunden")
    trade_children = set(trade_grid.iter())
    for action in V2_TRADE_ACTIONS:
        name = "CrusaderDiplomacyV2Trade" + action
        button = named[name][0]
        if button not in trade_children or button.tag != "Button":
            raise v1.BauFehler("Handelsaktion fehlt in ihrem echten Fenster: " + name)
        if button.get("Command") != "{Binding AlliesClickCommand}":
            raise v1.BauFehler("Handelsaktion ohne Originalspiel-Command: "+name)
        if button.get("CommandParameter") != "Diplomacy:Trade:" + action + ":0:0":
            raise v1.BauFehler("Handelsaktion ohne eindeutigen gebundenen Handler: "+name)
        if button.get("Style") != "{StaticResource BTN_SH_Plain}":
            raise v1.BauFehler("Handelsaktion hat nicht den Original-Buttonstil: "+name)
    for side in ("From","To"):
        name = "CrusaderDiplomacyV2Trade" + side + "AmountInput"
        entry = named[name][0]
        if entry.tag != "TextBox" or entry not in trade_children or entry.get("MaxLength") != "5":
            raise v1.BauFehler("Handelsmenge benoetigt ein echtes TextBox-Eingabefeld: "+name)
    overview_panel = named["CrusaderDiplomacyV2OverviewPanel"][0]
    detail_panel = named["CrusaderDiplomacyV2DetailsPanel"][0]
    if overview_panel not in list(panel):
        raise v1.BauFehler("Die Uebersicht muss Kind der Diplomatie-Tafel sein")
    if detail_panel not in list(panel) or overview_panel in list(detail_panel):
        raise v1.BauFehler("Details und Uebersicht muessen unabhaengige Tafel-Seiten sein")
    detail_descendants = set(detail_panel.iter())
    for name in V2_ACTION_CONTRACT:
        action = named[name][0]
        is_tab = name.endswith("OverviewButton") or name.endswith("DetailsButton")
        if (action in detail_descendants) == is_tab:
            raise v1.BauFehler("Reiter/Detailaktion hat den falschen Sichtbarkeits-Elternknoten: " + name)
    expected_panel = {
        "Width": "660",
        # 09.09.2026 auf 320: mit "Forderung ablehnen" braucht die Uebersicht
        # eine dritte Knopfreihe (y=249..279). Der Umschalter sitzt weiter in
        # der Kopfzeile, nicht in einer eigenen Reihe. Schmalere Knoepfe kamen
        # nicht in Frage - abgeschnittene Beschriftungen waren der Grund fuer
        # den Durchfall von 2.2.4. Der native Rahmen ist 320 hoch und wird
        # ohnehin gestreckt (BDR_SH1DE60 ist ein Stil, kein festes Bild).
        "Height": "320",
        "Margin": "20,150,20,0",
        "HorizontalAlignment": "Center",
        "VerticalAlignment": "Top",
        "Visibility": "Collapsed",
    }
    if any(panel.get(key) != value for key, value in expected_panel.items()):
        raise v1.BauFehler(
            "V2-HUD-Haupttafel weicht von den geprueften Vanilla-Massen ab"
        )

    expected_margins = {
        "CrusaderDiplomacyV2Primary": "15,141,0,0",
        "CrusaderDiplomacyV2Send": "175,141,0,0",
        "CrusaderDiplomacyV2Orders": "335,141,0,0",
        "CrusaderDiplomacyV2Break": "495,141,0,0",
        "CrusaderDiplomacyV2DeclineDemand": "15,280,0,0",
        "CrusaderDiplomacyV2OverviewButton": "500,0,0,0",
        "CrusaderDiplomacyV2DetailsButton": "340,0,0,0",
        "CrusaderDiplomacyV2Fealty": "0,40,17,0",
    }
    for name, command_parameter in V2_ACTION_CONTRACT.items():
        action = named[name][0]
        is_tab = name in {"CrusaderDiplomacyV2OverviewButton", "CrusaderDiplomacyV2DetailsButton"}
        expected_action = {
            "Width": "190" if name == "CrusaderDiplomacyV2Fealty"
                else "200" if name == "CrusaderDiplomacyV2DeclineDemand" else "145",
            "Height": "29" if name == "CrusaderDiplomacyV2Fealty" else "37",
            "Margin": expected_margins[name],
            "Command": "{Binding AlliesClickCommand}",
            "CommandParameter": command_parameter,
            "MouseEnter": "MouseEnterRolloverHandler",
            "MouseLeave": "MouseLeaveRolloverHandler",
            "Style": "{StaticResource BTN_SH_Plain}",
        }
        if is_tab:
            expected_action.pop("MouseEnter")
            expected_action.pop("MouseLeave")
            expected_action["Style"] = "{StaticResource BTN_RADIO_Image}"
            expected_action["GroupName"] = "DiplomacyViews"
            if action.tag != "RadioButton" or action.get("MouseEnter") or action.get("MouseLeave"):
                raise v1.BauFehler("Native Radio-Reiter duerfen keine Button-Rolloverhandler verwenden")
        elif name == "CrusaderDiplomacyV2Fealty":
            expected_action["Style"] = "{StaticResource DiplomacyActionButton}"
        if any(action.get(key) != value
               for key, value in expected_action.items()):
            raise v1.BauFehler(
                "V2-HUD-Aktionsschaltflaeche weicht vom Vanilla-Vertrag ab: "
                + name
            )
        for sprite_index in range(1, 5):
            suffix = "PropEx.Sprite" + str(sprite_index)
            expected_sprite = (
                "{StaticResource UI-Buttons C00" + str(sprite_index) + "}"
            )
            sprites = [
                value for key, value in action.attrib.items()
                if key.endswith(suffix)
            ]
            if sprites != [expected_sprite]:
                raise v1.BauFehler(
                    "V2-HUD-Schaltflaeche benutzt nicht alle Vanilla-Zustaende: "
                    + name
                )

    overview_descendants = set(overview_panel.iter())
    scroll = next((e for e in overview_panel.iter() if e.tag == "ScrollViewer"), None)
    if (scroll is None or scroll.get("Height") != "86"
            or scroll.get("VerticalScrollBarVisibility") != "Auto"):
        raise v1.BauFehler("Die sieben Buendnismitglieder brauchen eine begrenzte, scrollbar erreichbare Liste")
    for row in range(1, 8):
        member = named[f"CrusaderDiplomacyV2AllianceMember{row}"][0]
        row_grid = named[f"CrusaderDiplomacyV2AllianceRow{row}"][0]
        if (member not in set(row_grid.iter()) or member not in overview_descendants
                or member.tag != "RadioButton" or member.get("GroupName") != "DiplomacyAllianceMembers"
                or member.get("Command") != "{Binding AlliesClickCommand}"
                or member.get("CommandParameter") != "Diplomacy:AllianceSelect:0:0"
                or member.get("Style") != "{StaticResource DiplomacyAllianceRow}"
                or member.get("IsEnabled") != "False" or member.get("MouseEnter") or member.get("MouseLeave")):
            raise v1.BauFehler("Buendniszeile muss ueber den nativen Radio-Vertrag sicher gebunden werden")
    for action_name, (column, row) in V2_ALLIANCE_ACTION_GRID.items():
        action = named["CrusaderDiplomacyV2Alliance" + action_name][0]
        expected = {
            "Width": "200", "Height": "30", "Margin": f"{17 + column * 212},{181 + row * 34},0,0",
            "Command": "{Binding AlliesClickCommand}",
            "CommandParameter": f"Diplomacy:AllianceAction:{action_name}:0:0",
            "Style": "{StaticResource DiplomacyActionButton}", "IsEnabled": "False",
            "MouseEnter": "MouseEnterRolloverHandler", "MouseLeave": "MouseLeaveRolloverHandler",
        }
        if action not in overview_descendants or any(action.get(k) != v for k, v in expected.items()):
            raise v1.BauFehler("Buendnisaktion hat keinen gueltigen Vanilla-/Zielbindungsvertrag: " + action_name)
        label = named["CrusaderDiplomacyV2Alliance" + action_name + "Label"][0]
        if (label not in overview_descendants or label.get("Width") != "192"
                or label.get("Margin") != f"{21 + column * 212},{186 + row * 34},0,0"
                or label.get("IsHitTestVisible") != "False"):
            raise v1.BauFehler("Buendnisbeschriftung liegt nicht innerhalb ihrer Aktion: " + action_name)
    for element in [named["CrusaderDiplomacyV2Alliance" + a][0] for a in V2_ALLIANCE_ACTIONS]:
        for index in range(1, 5):
            if [value for key, value in element.attrib.items() if key.endswith(f"PropEx.Sprite{index}")] != [
                    f"{{StaticResource UI-Buttons C00{index}}}"]:
                raise v1.BauFehler("Buendnisaktion braucht alle vier Original-Buttonzustaende")

    # 08.09.2026 native screenshots: original uniform images shrink to a tiny
    # centered strip in 602x24 rows / 190x23 actions. Test the rendered sprite
    # contract, not just the misleading outer control rectangle.
    resource_node = panel.find("Grid.Resources")
    style_key = "{http://schemas.microsoft.com/winfx/2006/xaml}Key"
    styles = {} if resource_node is None else {
        node.get(style_key): node for node in resource_node if node.tag == "Style"}
    if set(styles) != V2_LOCAL_STYLE_KEYS:
        raise v1.BauFehler("Lokale Diplomatiestile fehlen oder sind mehrdeutig")
    button_style = styles["DiplomacyActionButton"]
    sprites = list(button_style.iter("Image"))
    if (len(sprites) != 4 or any(node.get("Stretch") != "Fill" for node in sprites)
            or {node.get("Source") for node in sprites} != {
                "{TemplateBinding local:PropEx.Sprite" + str(index) + "}" for index in range(1, 5)}):
        raise v1.BauFehler("Breite Diplomatieaktionen brauchen vier flaechenfuellende Originalsprites")
    row_style = styles["DiplomacyAllianceRow"]
    row_backgrounds = [node for node in row_style.iter("Border") if node.get("Name") == "RowBackground"]
    if (list(row_style.iter("Image")) or len(row_backgrounds) != 1
            or any(row_backgrounds[0].get(prop) is not None for prop in ("Width", "Height"))):
        raise v1.BauFehler("Die Buendniszeile braucht eine durchgehende Auswahlflaeche")
    for style in styles.values():
        required_states = {"IsMouseOver", "IsPressed", "IsEnabled", "IsKeyboardFocused"}
        if style is row_style: required_states.add("IsChecked")
        if not required_states <= {node.get("Property") for node in style.iter("Trigger")}:
            raise v1.BauFehler("Lokaler Diplomatiestil verliert Bedienungszustaende")
    for row in range(1, 8):
        for part in ("OverviewRow", "AllianceRole", "AllianceDuty"):
            if named[f"CrusaderDiplomacyV2{part}{row}"][0].get("Foreground") != "#FFEFF3C6":
                raise v1.BauFehler("Buendniszeilentext braucht Kontrast auf der dunklen Auswahlflaeche")

    if text.count("CrusaderDiplomacyNativeDetail") != 1:
        raise v1.BauFehler(
            "Der native Detailbereich wird nicht genau einmal benannt"
        )


def _validate_patch_content_roots(root: ET.Element) -> None:
    # 08.09.2026, COPY SE 1.45 GameXAMLManagerAPI.ApplyPatchForPath:
    # Content.Elements().FirstOrDefault() silently drops every sibling after
    # the first. Validate emitted V1+V2 operations, not only the source tree's
    # presence of names: that previously accepted an entirely discarded panel.
    for operation in root.findall("Operation"):
        if operation.get("Type") not in {"Add", "InsertBefore", "InsertAfter", "Replace"}:
            continue
        contents = operation.findall("Content")
        if len(contents) != 1 or len(list(contents[0])) != 1:
            raise v1.BauFehler(
                "Jede XAML-Einfuegung braucht genau einen Content-Wurzelknoten; "
                "SE verwirft weitere Geschwister: " + str(operation.get("XPath"))
            )


def _validated_v2_xaml_fragment() -> tuple[str, list[str]]:
    if not V2_XAML_FRAGMENT.is_file():
        raise v1.BauFehler(f"V2-HUD-Fragment fehlt: {V2_XAML_FRAGMENT}")
    text = V2_XAML_FRAGMENT.read_text(encoding="utf-8")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as error:
        raise v1.BauFehler(f"V2-HUD-Fragment ist kein gueltiges XML: {error}") from error
    if root.tag != "Operations" or not list(root):
        raise v1.BauFehler(
            "V2-HUD-Fragment muss ausschliesslich Patch-Operationen enthalten"
        )
    for child in root:
        if child.tag != "Operation" or child.get("Type") not in {
            "Add",
            "SetAttribute",
        }:
            raise v1.BauFehler(
                "V2-HUD-Fragment enthaelt eine unerlaubte Patch-Struktur"
            )

    _validate_v2_ui_contract(root, text)

    # XML namespace identifiers are not external image/resource loads.
    # Remove only the exact XAML namespace declaration before URI screening.
    lowered = re.sub(r'xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"', '', text).lower()
    if any(
        marker in lowered
        for marker in (
            "http://",
            "https://",
            "file://",
            "pack://",
            ".png",
            ".dds",
            ".tga",
            "europe",
            "origins",
        )
    ):
        raise v1.BauFehler(
            "V2-HUD-Fragment darf keine externen oder Europe/Origins-Ressourcen laden"
        )
    resources = sorted(
        set(re.findall(r"\{StaticResource ([^}]+)\}", text))
    )
    unexpected = sorted(set(resources) - V2_VANILLA_RESOURCE_KEYS - V2_LOCAL_STYLE_KEYS)
    if unexpected:
        raise v1.BauFehler(
            "V2-HUD-Fragment referenziert nicht freigegebene Ressourcen: "
            + ", ".join(unexpected)
        )

    opening_end = text.find(">")
    closing_start = text.rfind("</Operations>")
    if opening_end < 0 or closing_start <= opening_end:
        raise v1.BauFehler("V2-HUD-Fragment kann nicht zerlegt werden")
    body = text[opening_end + 1 : closing_start].strip()
    if not body.startswith("<Operation"):
        raise v1.BauFehler("V2-HUD-Fragment beginnt nicht mit einer Operation")
    return body, sorted(set(resources) - V2_LOCAL_STYLE_KEYS)


def _compose_v2_xaml_patch(expected_v1_hash: str) -> tuple[str, list[str]]:
    actual_v1_hash = v1._sha256(v1.XAML_SOURCE)
    if actual_v1_hash != expected_v1_hash:
        raise v1.BauFehler(
            "HUD_AlliesPanel.xaml weicht vom festgeschriebenen V1-Abzug ab: "
            f"{actual_v1_hash} statt {expected_v1_hash}"
        )
    base = v1.XAML_SOURCE.read_text(encoding="utf-8")
    if base.count("</Patch>") != 1:
        raise v1.BauFehler("V1-HUD-Patch besitzt keinen eindeutigen Abschluss")
    fragment, resources = _validated_v2_xaml_fragment()
    composed = base.replace("</Patch>", fragment + "\n</Patch>", 1)
    # The unchanged V1 patch inherits this namespace from SE's parser context.
    # Supply it only to the offline reader; do not rewrite the shipped V1 prefix.
    context = ET.fromstring(
        '<PatchContext xmlns:local="clr-namespace:CrusaderDE">'
        + composed + '</PatchContext>'
    )
    _validate_patch_content_roots(context[0])
    return composed, resources


def _compile_source_snapshot(contract: Path, source: Path, compatibility: Path,
                             texts: Path) -> list[dict[str, object]]:
    """Hash the actual Compile inputs, project, and build/localization scripts."""
    project = PROJECT_DIR / "StrongholdEuropeDiplomatie.csproj"
    properties = {
        "SharedRuntimeDir": PROJECT_ROOT / "runtime/StrongholdEuropeDE.Runtime",
        "V1PluginSourceDir": V1_PROJECT_DIR,
        "DiplomacyFeatureSource": source,
        "GeneratedContractPath": contract,
        "GeneratedCompatibilityContractPath": compatibility,
        "GeneratedDiplomacyTextsPath": texts,
    }
    inputs = {project, PROJECT_DIR / "bauen.py", PROJECT_DIR / "texte.py",
              PROJECT_DIR / "texte_extrahieren.py", V2_XAML_FRAGMENT,
              EXTENDER_PINS_PATH, V1_BUILDER_PATH, v1.DIPLOMACY_PROFILE,
              v1.XAML_SOURCE, v1.ENGINE_PINS_PATH}
    inputs.update((PROJECT_DIR / "texte").glob("*.json"))
    for item in ET.parse(project).getroot().findall(".//Compile"):
        value = item.attrib["Include"]
        for key, replacement in properties.items():
            value = value.replace("$(" + key + ")", str(replacement))
        if "$(" in value:
            raise v1.BauFehler("Nicht aufgeloester Compile-Eingang: " + value)
        inputs.add((PROJECT_DIR / Path(value.replace("\\", "/"))).resolve())
    return [{"path": path.relative_to(PROJECT_ROOT).as_posix(),
             "size": path.stat().st_size, "sha256": v1._sha256(path)}
            for path in sorted(inputs)]


def _package(
    dll: Path,
    target: Path,
    pin: dict[str, object],
    source_adjustments: list[str],
    vanilla_ui_references: list[dict[str, object]],
    compatibility: dict[str, object] | None = None,
    translations: dict[str, object] | None = None,
    compiled_sources: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    dist_root = target.parent.resolve()
    if target.resolve().parent != dist_root or target.name != PLUGIN_FOLDER:
        raise v1.BauFehler(f"Unerwartetes V2-Paketziel: {target}")
    if target.exists():
        shutil.rmtree(target)
    (target / "Patches" / "Assets" / "GUI" / "XAMLResources").mkdir(
        parents=True
    )

    profile = json.loads(v1.DIPLOMACY_PROFILE.read_text(encoding="utf-8"))
    patch = profile["xaml_patches"][0]
    if patch.get("output") != XAML_OUTPUT:
        raise v1.BauFehler(f"HUD-Patch liegt unerwartet: {patch.get('output')}")
    composed_xaml, vanilla_resource_keys = _compose_v2_xaml_patch(
        str(patch.get("expected_sha256"))
    )

    shutil.copy2(dll, target / f"{ASSEMBLY_NAME}.dll")
    (target / XAML_OUTPUT.replace("/", os.sep)).write_text(
        composed_xaml,
        encoding="utf-8",
        newline="\n",
    )

    info = {
        "GUID": MOD_GUID,
        "Author": "Private",
        "Name": PACKAGE_DISPLAY_NAME,
        "Description": (
            "Eigenstaendige Crusader-Diplomatie und vollstaendiger Nachfolger "
            "der Diplomatie V1 mit persoenlichen "
            "Herrschern, Verhandlungsstufen, Pakten, Buendnispflege und "
            "automatischer V1-Spielstandsmigration"
        ),
        "Version": MOD_VERSION,
        "Website": "",
        "Manifest": 0,
    }
    (target / "info.json").write_text(
        json.dumps(info, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    outputs = []
    for item in sorted(path for path in target.rglob("*") if path.is_file()):
        if item.name == "build-manifest.json":
            continue
        outputs.append(
            {
                "relative_path": item.relative_to(target).as_posix(),
                "sha256": v1._sha256(item),
                "size": item.stat().st_size,
            }
        )
    manifest = {
        "schema_version": 2,
        "schema_kind": "package_build_manifest",
        "source_provenance": compiled_sources or [],
        "mod_info": info,
        "plugin_id": MOD_GUID,
        "incompatible_plugin_ids": ["strongholdeuropede.diplomatie.private"],
        "save_data_identifier": SAVE_DATA_IDENTIFIER,
        "legacy_save_data_identifier": LEGACY_SAVE_DATA_IDENTIFIER,
        "contains_complete_v1_feature_set": True,
        "legacy_identity_retained_for_save_migration": True,
        "save_format": {
            "primary_identifier": SAVE_DATA_IDENTIFIER,
            "legacy_identifier": LEGACY_SAVE_DATA_IDENTIFIER,
            "envelope_schema_version": SAVE_ENVELOPE_SCHEMA_VERSION,
            "minimum_supported_envelope_schema_version": (
                MINIMUM_SAVE_ENVELOPE_SCHEMA_VERSION
            ),
            "checksum": "SHA-256",
            "automatic_v1_migration": True,
            "rolling_v1_projection": True,
            "v1_projection_is_semantically_lossy": True,
        },
        "installation": {
            "replaces_folder": PLUGIN_FOLDER,
            "backup_root": "BepInEx/plugin-backups",
            "transactional_directory_swap": True,
        },
        "standalone_compatibility": {
            "game": "Stronghold Crusader Definitive Edition",
            "target_build_id": pin["target_build_id"],
            "display_version": pin["display_version"],
            "script_extender": _extender_pin()["baseline_version"],
            "requires_europe_mod": False,
            "requires_origins_mod": False,
            "clean_reference_basis": (
                "Crusader DE 2.80 with BepInEx and SHCDESE "
                + _extender_pin()["baseline_version"] + "; see acceptance report"
            ),
            "validated_ui_references": vanilla_ui_references,
        },
        "hud_composition": {
            "v1_base_sha256": v1._sha256(v1.XAML_SOURCE),
            "v2_fragment_sha256": v1._sha256(V2_XAML_FRAGMENT),
            "vanilla_resource_keys": vanilla_resource_keys,
            "external_assets": [],
            "root_height": 484,
            "detail_panel_bounds": {
                "width": 660,
                "height": 320,
                "left": 20,
                "top": 150,
                "bottom": 470,
            },
        },
        "compatibility_contract": compatibility or {"kind": "none"},
        "translations": translations or {"kind": "none"},
        "engine_pin": {
            "target_build_id": pin["target_build_id"],
            "display_version": pin["display_version"],
            "relative_path": pin["relative_path"],
            "size": pin["size"],
            "sha256": pin["sha256"],
            "verification": pin["verification"],
            "source_adjustments": list(source_adjustments),
        },
        "release_readiness": {
            "status": V2_RELEASE_STATUS,
            "public_release_ready": False,
            "engine_evidence": pin["verification"],
            "in_game_acceptance_recorded": False,
            "required_acceptance": [
                "at least two hours of advancing simulation with measured map epochs, days and journals",
                "tribute both directions, grace, persistent arrears, late payment, equality and persisted pending fealty quotes",
                "save/load before, during and after single/package transfers; repeated rollback recovery",
                "cold start on the pinned Crusader DE 2.80 build",
                "save, load, V1 migration and rolling V1 fallback",
                "single- and three-good one-click package transfers",
                "truce attack suppression and deliberate breach handling",
                "truce idle/attack animation observation for autonomous units before claiming visual peace",
                "truce protection across the human and all existing AI allies",
                "ground-fire suppression at protected treaty boundaries",
                "military inner-zone incursion breach handling",
                "truce, trade pact, alliance and targeted alliance break",
                "expanded diplomacy panel at every supported UI scale",
            ],
        },
        "outputs": outputs,
    }
    (target / "build-manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return manifest


def _verify_package(package: Path, manifest: dict[str, object]) -> None:
    expected_paths = set()
    for output in manifest["outputs"]:
        relative = output["relative_path"]
        expected_paths.add(relative)
        path = package / relative.replace("/", os.sep)
        if not path.is_file():
            raise v1.BauFehler(f"V2-Paketausgabe fehlt: {path}")
        if path.stat().st_size != output["size"] or v1._sha256(path) != output["sha256"]:
            raise v1.BauFehler(f"V2-Paketausgabe weicht vom Manifest ab: {path}")
    actual_paths = {
        path.relative_to(package).as_posix()
        for path in package.rglob("*")
        if path.is_file() and path.name != "build-manifest.json"
    }
    if actual_paths != expected_paths:
        raise v1.BauFehler(
            "V2-Paket enthaelt unerwartete Dateien: "
            f"fehlend={sorted(expected_paths - actual_paths)} "
            f"zusaetzlich={sorted(actual_paths - expected_paths)}"
        )


def _next_backup_path(backup_root: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = backup_root / f"{PLUGIN_FOLDER}-pre-{MOD_VERSION}-{stamp}"
    candidate = base
    suffix = 1
    while candidate.exists():
        candidate = backup_root / f"{base.name}-{suffix}"
        suffix += 1
    return candidate


def _install(
    package: Path,
    game_dir: Path,
    pin: dict[str, object],
) -> tuple[Path, Path | None]:
    plugins = (game_dir / "BepInEx" / "plugins").resolve()
    if not plugins.is_dir():
        raise v1.BauFehler(f"Kein BepInEx/plugins unter {game_dir}")

    target = plugins / PLUGIN_FOLDER
    staging = plugins / f".{PLUGIN_FOLDER}.install"

    old_plugin = plugins / "StrongholdEuropeDiplomatie"
    if old_plugin.exists():
        raise v1.BauFehler(
            "V1 ist noch aktiv. V2 wird nicht daneben installiert: "
            f"{old_plugin}. V1 zuerst als rueckholbare Sicherung aus "
            "BepInEx/plugins verschieben."
        )
    conflicting_patches = []
    for plugin_dir in sorted(plugins.iterdir(), key=lambda path: path.name.lower()):
        if (
            not plugin_dir.is_dir()
            or plugin_dir.name in {PLUGIN_FOLDER, staging.name}
        ):
            continue
        patch = plugin_dir / XAML_OUTPUT.replace("/", os.sep)
        if patch.is_file():
            conflicting_patches.append(patch)
    if conflicting_patches:
        raise v1.BauFehler(
            "Ein anderes Plugin besitzt denselben Diplomatie-HUD-Patch: "
            + ", ".join(str(path) for path in conflicting_patches)
        )

    engine = game_dir / str(pin["relative_path"]).replace("/", os.sep)
    if not engine.is_file():
        raise v1.BauFehler(f"Engine fehlt in der Zielinstallation: {engine}")
    actual_hash = v1._sha256(engine)
    if engine.stat().st_size != pin["size"] or actual_hash != pin["sha256"]:
        # 08.09.2026: the runtime's exact version fence also applies before
        # deployment. A successful MemberRef check does not attest native ABI.
        raise v1.BauFehler(
            "Die Zielinstallation faehrt eine andere Engine als der "
            f"V2-Bau beglaubigt ({pin['display_version']}). Vorgefunden: "
            f"{engine.stat().st_size} B, {actual_hash[:16]}... - "
            "Installation abgebrochen; fuer diese Engine ist ein belegter Neubau erforderlich."
        )

    package_manifest_path = package / "build-manifest.json"
    if not package_manifest_path.is_file():
        raise v1.BauFehler(
            f"V2-Installationspaket besitzt kein Manifest: {package}"
        )
    package_manifest = json.loads(
        package_manifest_path.read_text(encoding="utf-8")
    )
    if (
        package_manifest.get("schema_kind") != "package_build_manifest"
        or package_manifest.get("plugin_id") != MOD_GUID
    ):
        raise v1.BauFehler(
            "V2-Installationspaket besitzt nicht die erwartete Identitaet"
        )
    _verify_package(package, package_manifest)
    ui_references = package_manifest.get("standalone_compatibility", {}).get(
        "validated_ui_references"
    )
    if not isinstance(ui_references, list) or not ui_references:
        raise v1.BauFehler(
            "V2-Installationspaket besitzt keinen Vanilla-UI-Vertrag"
        )
    game_root = game_dir.resolve()
    for reference in ui_references:
        relative = reference.get("relative_path")
        if not isinstance(relative, str) or not relative:
            raise v1.BauFehler(
                "V2-Installationspaket besitzt einen ungueltigen UI-Pfad"
            )
        path = (game_root / relative.replace("/", os.sep)).resolve()
        try:
            path.relative_to(game_root)
        except ValueError as exception:
            raise v1.BauFehler(
                f"V2-UI-Vertrag verlaesst das Spielverzeichnis: {relative}"
            ) from exception
        if (
            not path.is_file()
            or path.stat().st_size != reference.get("size")
            or v1._sha256(path) != reference.get("sha256")
        ):
            raise v1.BauFehler(
                "Vanilla-UI-Datei weicht vom beglaubigten Stand ab: "
                f"{path} - Installation vor dem HUD-Patch abgebrochen."
            )

    if staging.exists():
        raise v1.BauFehler(
            "Eine fruehere Installationsstufe existiert bereits und bleibt "
            f"zur Pruefung erhalten: {staging}"
        )
    backup = None
    try:
        shutil.copytree(package, staging)
        staged_manifest_path = staging / "build-manifest.json"
        staged_manifest = json.loads(
            staged_manifest_path.read_text(encoding="utf-8")
        )
        _verify_package(staging, staged_manifest)

        if target.exists():
            backup_root = (game_dir / "BepInEx" / "plugin-backups").resolve()
            backup_root.mkdir(parents=True, exist_ok=True)
            backup = _next_backup_path(backup_root)
            os.replace(target, backup)
        os.replace(staging, target)
    except Exception:
        if backup is not None and backup.exists() and not target.exists():
            os.replace(backup, target)
            backup = None
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return target, backup


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--install",
        metavar="SPIELVERZEICHNIS",
        help="Nach dem Bau in eine V1-freie BepInEx-Installation legen.",
    )
    args = parser.parse_args()

    config = v1.load_config(v1.CONFIG_PATH)
    match = v1.verify_supported_builds(config, v1.SUPPORTED_BUILDS_PATH)
    prerequisites = v1._verify_prerequisites(config)
    extender_pin = _extender_pin()
    baseline_reference = _resolve_extender_reference(
        extender_pin,
        Path(args.install) if args.install else None,
    )
    prerequisites = _with_extender_prerequisite(
        prerequisites, extender_pin, baseline_reference
    )
    rules = v1._pinned_rules()
    pin = v1._engine_pin(match.target_id)
    print(
        f"Engine-Anmeldung: {pin['display_version']} ({match.target_id}), "
        f"{pin['size']:,} B, Beleg={pin['verification']}"
    )
    if pin["verification"] != "measured":
        print(
            "  ACHTUNG: Auf dieser Engine ist das Spielverhalten der "
            "Diplomatie noch nicht formal nachgemessen."
        )
    print(
        "  RELEASE-SPERRE: V2.2 benoetigt vor einer oeffentlichen Freigabe "
        "noch die protokollierte In-Game-Abnahme."
    )

    vanilla_ui_references = _verified_vanilla_ui_references()
    print(
        "Vanilla-UI-Vertrag bestaetigt: "
        f"{len(vanilla_ui_references)} Crusader-DE-2.80/SE-1.44-Dateien"
    )

    work_root = (config.output.work_dir / "runtime" / "diplomatie-v2").resolve()
    work_root.mkdir(parents=True, exist_ok=True)
    contract = work_root / "GeneratedDiplomatieContract.g.cs"
    contract_text = v1._contract_text(rules, prerequisites)
    used_members = v1._verify_members(contract_text)
    contract.write_text(contract_text, encoding="utf-8", newline="\n")
    print(
        f"V2-Vertrag erzeugt: {contract} "
        f"({len(rules)} Regelwerte, {used_members} Vertragsglieder)"
    )

    source, adjustments = v1._prepare_diplomacy_source(work_root, pin)

    # Kompatibilitaetsvertrag: erst mit leerem Vertrag uebersetzen, dann die
    # Bindungen aus der IL auszaehlen, den Vertrag schreiben und erneut
    # uebersetzen. Der zweite Durchgang muss dieselben Bindungen ergeben.
    ilspycmd = kompat.locate_ilspycmd(PROJECT_ROOT)
    compat_contract = work_root / "GeneratedCompatibilityContract.g.cs"
    compat_properties = [f"-p:GeneratedCompatibilityContractPath={compat_contract}"]

    print(
        f"Uebersetzt gegen Extender {extender_pin['baseline_version']}: "
        f"{baseline_reference}"
    )
    compat_properties.append(
        f"-p:SHCDESEBaselineReference={baseline_reference}"
    )

    # Uebersetzungen (06.09.2026): jede Text(-Stelle der Quellen muss in
    # texte/quelltexte.json stehen und in jeder nativen Spielsprache
    # uebersetzt sein - sonst bricht der Bau hier ab, statt im Spiel still
    # Englisch zu zeigen.
    texts_cs = work_root / texte.GENERATED_NAME
    try:
        translations = texte.write_generated(texts_cs)
    except texte.TextFehler as fehler:
        raise v1.BauFehler(f"Uebersetzungen unvollstaendig: {fehler}") from fehler
    compat_properties.append(f"-p:GeneratedDiplomacyTextsPath={texts_cs}")
    print(
        f"Uebersetzungen erzeugt: {translations['count']} Texte x "
        f"{len(translations['locales'])} Sprachen ({', '.join(translations['locales'])})"
    )
    compat_contract.write_text(
        kompat.render_contract_cs(
            [], str(pin["relative_path"]), int(pin["size"]), str(pin["sha256"])
        ),
        encoding="utf-8",
        newline="\n",
    )
    dll = v1._build(config, prerequisites, work_root, contract, source, compat_properties)
    il_text = kompat.il_from_dll(ilspycmd, dll)
    kompat.assert_independent(il_text)
    bindungen = kompat.extract_from_il(il_text)
    compat_contract.write_text(
        kompat.render_contract_cs(
            bindungen, str(pin["relative_path"]), int(pin["size"]), str(pin["sha256"])
        ),
        encoding="utf-8",
        newline="\n",
    )
    source_provenance = _compile_source_snapshot(contract, source, compat_contract, texts_cs)
    dll = v1._build(config, prerequisites, work_root, contract, source, compat_properties)
    if source_provenance != _compile_source_snapshot(contract, source, compat_contract, texts_cs):
        raise v1.BauFehler("Compile-Eingaben wurden waehrend des Baus geaendert")
    il_text = kompat.il_from_dll(ilspycmd, dll)
    kompat.assert_independent(il_text)
    bindungen_zweit = kompat.extract_from_il(il_text)
    if bindungen_zweit != bindungen:
        raise v1.BauFehler(
            "Der Kompatibilitaetsvertrag ist nicht stabil: der zweite Durchgang "
            f"bindet {len(bindungen_zweit)} statt {len(bindungen)} Mitglieder"
        )
    compatibility = kompat.summary(bindungen, il_text)
    contract_json_path = work_root / "kompatibilitaetsvertrag.json"
    contract_json_path.write_text(
        kompat.contract_json(bindungen), encoding="utf-8", newline="\n"
    )
    print(f"Vertrag als JSON: {contract_json_path}")
    print(
        "Eigenstaendig: keine Bindung an "
        + "/".join(kompat.FORBIDDEN_REFERENCE_PREFIXES)
        + "; Fremdassemblies: "
        + ", ".join(compatibility["referenced_assemblies"])
    )
    print(
        f"Kompatibilitaetsvertrag: {compatibility['bindings']} Bindungen, "
        + ", ".join(
            f"{name} {c['types']}T/{c['methods']}M/{c['fields']}F"
            for name, c in compatibility["per_assembly"].items()
        )
    )
    print(f"V2 uebersetzt: {dll} ({dll.stat().st_size:,} B)")

    package = (config.output.dist_dir / PLUGIN_FOLDER).resolve()
    manifest = _package(
        dll,
        package,
        pin,
        adjustments,
        vanilla_ui_references,
        compatibility,
        translations,
        source_provenance,
    )
    _verify_package(package, manifest)
    print(f"V2-Paket verifiziert: {package}")
    for output in manifest["outputs"]:
        print(f"  {output['size']:>10,} B  {output['relative_path']}")

    if args.install:
        install_root = Path(args.install).resolve(strict=True)
        _pruefe_signaturen(
            package / f"{ASSEMBLY_NAME}.dll",
            install_root,
        )
        target, backup = _install(
            package,
            install_root,
            pin,
        )
        if backup is not None:
            print(f"Vorherige V2 gesichert: {backup}")
        print(f"V2 installiert: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Read-only SHCDE Script Extender compatibility and latest-release preflight.

The SH1DE offline Unity patcher does not need SHCDESE. The Crusader Noesis
HUD bridge and asset mods can use SHCDESE v2.14.3, but an existing net481
C# runtime pinned to v2.11 is NOT automatically binary-compatible.
No installation, update, copy to game directories, or gameplay is performed.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
OFFICIAL_REPO = "https://gitlab.com/rawra-stronghold-crusader/shcde-script-extender"
LATEST_VERIFIED = (2, 14, 3)
LATEST_TAG = "v2.14.3"
LATEST_COMMIT = "4014ca67c96974a5e6d697665baf5351cbfebde6"
LATEST_DATE = "2026-10-19"
SE_DLL = Path("BepInEx/plugins/000shcdese/SHCDESE.dll")
SE_MANIFEST = Path("BepInEx/plugins/000shcdese/info.json")
BEP_DLL = Path("BepInEx/core/BepInEx.dll")
BEP_MIN = (5, 4, 23, 4)
GAME_DLL = Path("Stronghold Crusader Definitive Edition_Data/Managed/Assembly-CSharp.dll")
VERSION_RE = re.compile(r"\d+\.\d+\.\d+(?:\.\d+)?\Z")
KNOWN_UI_GAME_REQUIREMENTS = {"2.8.0.2": (2, 3, 0),
                              "2.8.0.1": (1, 41, 0),
                              "2.8.0.0": (1, 40, 0)}


class SeCompatibilityError(ValueError):
    pass


def version(value: object) -> tuple[int, int, int] | None:
    if not isinstance(value, str) or not VERSION_RE.fullmatch(value):
        return None
    parts = tuple(int(x) for x in value.split("."))
    if len(parts) == 4 and parts[3] != 0:
        return None
    return parts[:3]


def pe_file_version(path: Path) -> tuple[int, int, int, int] | None:
    """Read Windows PE metadata; do not load or execute the assembly."""
    try:
        import pefile
        pe = pefile.PE(str(path), fast_load=True)
        try:
            pe.parse_data_directories(
                directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]]
            )
            info = pe.VS_FIXEDFILEINFO
            if info:
                fixed = info[0]
                return (fixed.FileVersionMS >> 16,
                        fixed.FileVersionMS & 0xFFFF,
                        fixed.FileVersionLS >> 16,
                        fixed.FileVersionLS & 0xFFFF)
        finally:
            pe.close()
    except (OSError, AttributeError, ValueError, ImportError, TypeError, KeyError):
        return None
    return None


def read_json(path: Path, *, limit: int = 1_048_576) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise SeCompatibilityError(f"JSON fehlt oder ist unsicher: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (UnicodeError, OSError, ValueError) as exc:
        raise SeCompatibilityError(f"Ungültige JSON-Datei: {path}") from exc
    if not isinstance(value, dict):
        raise SeCompatibilityError(f"JSON-Wurzel kein Objekt: {path}")
    return value


def signed_plugins_enabled(config: Path) -> bool:
    """Parse the setting from the actual [Security] BepInEx config only."""
    if not config.exists():
        return False
    if config.is_symlink() or not config.is_file() or config.stat().st_size > 1024 * 1024:
        raise SeCompatibilityError("SE-Sicherheitskonfiguration fehlt oder ist verknüpft")
    current = ""
    option = None
    for line in config.read_text(encoding="utf-8-sig").splitlines():
        text = line.strip()
        if not text or text[0] in "#;":
            continue
        if text.startswith("[") and text.endswith("]"):
            current = text[1:-1].strip().casefold()
            continue
        if current == "security" and "=" in text:
            key, raw_value = text.split("=", 1)
            if key.strip().casefold() == "requiresignedbepinexplugins":
                if option is not None:
                    raise SeCompatibilityError("Doppelte Signaturpflicht in SE-Config")
                v = raw_value.strip().casefold()
                if v not in ("true", "false"):
                    raise SeCompatibilityError("Unbekannter Wert für RequireSignedBepInExPlugins")
                option = v == "true"
    return bool(option)


def _source_game_digest(game: Path, supported_builds: Path | None) -> tuple[str, bool]:
    from hashlib import file_digest
    dll = game / GAME_DLL
    if dll.is_symlink() or not dll.is_file():
        return "Spiel-Assembly-CSharp.dll fehlt", False
    with dll.open("rb") as stream:
        digest = file_digest(stream, "sha256").hexdigest()
    if supported_builds is None or not supported_builds.is_file():
        return "nicht versionierter Spielstand", False
    data = read_json(supported_builds)
    entries = data.get("target_builds", [])
    for candidate in entries if isinstance(entries, list) else []:
        if not isinstance(candidate, dict):
            continue
        for entry in candidate.get("files", []):
            if (isinstance(entry, dict) and
                entry.get("relative_path") == "Managed/Assembly-CSharp.dll" and
                entry.get("sha256") == digest):
                return candidate.get("id", "geprüfter SHCDE-Build"), True
    return "SHCDE-Spiel-Assembly nicht in den Source-Pins", False


def inspect(game: Path, *, supported_builds: Path | None = None,
            legacy_config: Path | None = None) -> dict:
    """Analyse only installed *Crusader DE* files. Never modify them."""
    game = Path(game).resolve(strict=True)
    if not game.is_dir():
        raise SeCompatibilityError("Das gewählte Ziel ist kein Spielverzeichnis")
    warnings: list[str] = []
    blocks: list[str] = []

    def warn(code: str) -> None:
        if code not in warnings:
            warnings.append(code)
    def block(code: str) -> None:
        if code not in blocks:
            blocks.append(code)

    se_file = game / SE_DLL
    manifest_file = game / SE_MANIFEST
    bepinex_file = game / BEP_DLL
    manifest = None
    declared = None
    if se_file.is_symlink() or not se_file.is_file():
        block("SCRIPT_EXTENDER_DLL_FEHLT")
        installed = None
    else:
        file_version = pe_file_version(se_file)
        installed = (file_version[:3] if file_version and file_version[3] == 0
                     else None)
        if installed is None:
            block("SCRIPT_EXTENDER_DLL_VERSION_NICHT_LESBAR")
    if manifest_file.is_file():
        try:
            manifest = read_json(manifest_file)
            declared = version(manifest.get("Version"))
            if manifest.get("GUID") != "000shcdese":
                block("SCRIPT_EXTENDER_GUID_UNGUELTIG")
            if declared is None:
                block("SCRIPT_EXTENDER_MANIFEST_VERSION_UNGUELTIG")
            elif installed is not None and declared != installed:
                block("SCRIPT_EXTENDER_DLL_MANIFEST_UNTERSCHIEDLICH")
        except SeCompatibilityError:
            block("SCRIPT_EXTENDER_MANIFEST_UNGUELTIG")
    else:
        block("SCRIPT_EXTENDER_MANIFEST_FEHLT")

    bepinex_ver = (pe_file_version(bepinex_file)
                   if bepinex_file.is_file() and not bepinex_file.is_symlink()
                   else None)
    if bepinex_ver is None:
        block("BEPINEX_5_NICHT_VERIFIZIERT")
    elif bepinex_ver < BEP_MIN or bepinex_ver[0] != 5:
        block("BEPINEX_VERSION_NICHT_UNTERSTUETZT")

    try:
        signing = signed_plugins_enabled(game / "BepInEx/config/000shcdese.cfg")
    except SeCompatibilityError:
        signing = None
        block("SE_SIGNATUR_KONFIGURATION_UNGUELTIG")

    if signing:
        warn("SE_SIGNATURPFLICHT_AKTIV")
        # The upstream preloader's trust list is embedded in its executable.
        # Presence of manifest/sig can never replace cryptographic review.
        block("PLUGIN_SIGNATUR_UNABHAENGIG_NICHT_VERIFIZIERT")

    game_id, game_pinned = _source_game_digest(game, supported_builds)
    if not game_pinned:
        warn("SPIEL_BUILD_NICHT_GEGEN_REFERENZ_PIN_VERIFIZIERT")
    declared_game_versions = manifest.get("SupportedGameVersions") if manifest else []
    if not isinstance(declared_game_versions, list):
        declared_game_versions = []
        warn("SE_GAME_VERSION_DEKLARATION_UNGUELTIG")
    if declared_game_versions and not all(isinstance(v, str) for v in declared_game_versions):
        declared_game_versions = []
        warn("SE_GAME_VERSION_DEKLARATION_UNGUELTIG")
    if installed and installed > LATEST_VERIFIED:
        warn("SE_NEUER_ALS_ZULETZT_VERIFIZIERTER_UPSTREAM_TAG")
    elif installed and installed < LATEST_VERIFIED:
        warn("NEUERER_OFFIZIELLER_SE_VERFUEGBAR")
    if installed and installed[0] == 1:
        warn("LEGACY_SE_1_X_EINGESCHRAENKTE_API_PARITAET")

    compatible_official_game = bool(
        installed and declared_game_versions and
        any(version_required <= installed
            for name, version_required in KNOWN_UI_GAME_REQUIREMENTS.items()
            if name in declared_game_versions)
    )
    if not compatible_official_game:
        warn("UI_MOD_VERSIONSFREIGABE_NICHT_NACHGEWIESEN")

    pinned_runtime_se = None
    if legacy_config is not None and legacy_config.is_file():
        pins = read_json(legacy_config)
        pinned_runtime_se = version(pins.get("script_extender_version"))
        if pinned_runtime_se is None:
            block("RUNTIME_SOURCE_PIN_UNGUELTIG")

    # Public 2.14.3 source still reads root.Elements("Operation") for both
    # <Patch> and <XamlPatch> Noesis files. This does not prove an in-game result.
    ui_static_ready = not blocks and compatible_official_game and game_pinned
    runtime_abi_exact = (
        bool(installed and pinned_runtime_se and installed == pinned_runtime_se)
    )
    if installed and pinned_runtime_se and not runtime_abi_exact:
        warn("RUNTIME_GEGEN_ANDERES_SE_GEBAUT_NEUBAU_ERFORDERLICH")
    # Even matching assembly versions don't alone confirm ABI / runtime hooks.
    return {
        "schema": "sprite-suite.shcdese-compatibility.v1",
        "official_latest_tag": LATEST_TAG,
        "official_latest_commit": LATEST_COMMIT,
        "official_latest_release_date": LATEST_DATE,
        "installed_version": ".".join(map(str, installed)) if installed else None,
        "declared_se_version": ".".join(map(str, declared)) if declared else None,
        "bepinex_version": ".".join(map(str, bepinex_ver)) if bepinex_ver else None,
        "shcde_game_build": game_id,
        "game_build_source_pinned": game_pinned,
        "upstream_game_compatibility_declared": compatible_official_game,
        "signature_enforcement": signing,
        "hud_noesis_static_ready": ui_static_ready,
        "runtime_compiled_for": (".".join(map(str, pinned_runtime_se))
                                 if pinned_runtime_se else None),
        "runtime_abi_version_matches": runtime_abi_exact,
        "runtime_in_game_verified": False,
        "warnings": warnings,
        "blocking_issues": blocks,
        "writes_to_game": False,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", required=True, type=Path,
                        help="Existierender SHCDE-Spielordner, nur lesen")
    parser.add_argument("--require-latest", action="store_true",
                        help="Mit Exitcode 2 ablehnen, wenn nicht exakt v2.14.3 installiert")
    parser.add_argument("--json", action="store_true",
                        help="Maschinenlesbaren Bericht auf stdout ausgeben")
    args = parser.parse_args(argv)
    try:
        result = inspect(
            args.game,
            supported_builds=ROOT / "config/supported-builds.json",
            legacy_config=ROOT / "config/runtime-prerequisites.json",
        )
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"SHCDESE_PRUEFUNG_FEHLGESCHLAGEN: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("SHCDE Script Extender:", result["installed_version"] or "nicht lesbar",
              "| offiziell neuester geprüfter Release:", LATEST_TAG)
        print("Spiel-Build:", result["shcde_game_build"],
              "| BepInEx:", result["bepinex_version"])
        print("Noesis-/HUD-Vorprüfung:",
              "PASS (statisch)" if result["hud_noesis_static_ready"] else "NICHT FREIGEGEBEN")
        print("Eigene C#-Runtime:",
              result["runtime_compiled_for"] or "kein Pin",
              "| Versionsidentität:",
              "passt" if result["runtime_abi_version_matches"] else "NEUBAU / ABI-Test erforderlich")
        for issue in result["warnings"]:
            print("HINWEIS:", issue)
        for issue in result["blocking_issues"]:
            print("BLOCKIERT:", issue)
        print("Keine Spielressourcen verändert. Laufzeittest weiterhin erforderlich.")
    if result["blocking_issues"] or (args.require_latest and result["installed_version"] != "2.14.3"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

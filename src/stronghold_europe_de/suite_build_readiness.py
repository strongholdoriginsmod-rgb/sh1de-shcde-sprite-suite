"""Read-only, actionable BC7 build readiness for Sprite Suite.

Unlike the deliberately lenient setup doctor, missing build prerequisites
stay blockers. This does not build, install, certify a release, or run
Unity or dotnet; it only inspects configuration and pinned input files.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .asset_stream_builder import AssetStreamBuildError, _resolve_toolchain
from .config import ConfigurationError, load_config
from .mod_builder import ModBuildError, _validate_group_backend_selection, load_profile
from .pivot_native_provenance import PivotNativeProvenanceError, _read_pinned_mapping
from .release_preflight import (
    ID, _bad_constant, _is_link, _sha256_file, _strict_pairs,
)
from .sdk_toolchain import (
    find_dotnet_sdk, resolve_dotnet_directory, sdk_minimum, sdk_supported,
)
from .suite_setup import SOURCE_DIR, TARGET_DIR

SCHEMA = "stronghold-europe.suite-build-readiness.v1"


class BuildReadinessError(ValueError):
    """Invalid or inconsistent inspection input."""


def _source(root: Path, relative: str) -> Path:
    current = root
    for part in relative.split("/"):
        if part in ("", ".", "..") or ":" in part or "\\" in part:
            raise BuildReadinessError("Unsicherer Quellpfad")
        current = current / part
        if _is_link(current):
            raise BuildReadinessError("Quellpfad enthält einen Link/Junction")
    return current


def _checked_file(path: Path, size_limit: int, label: str) -> str:
    if (not path.is_file() or _is_link(path)
        or not 0 < path.stat().st_size <= size_limit):
        raise BuildReadinessError(f"{label} fehlt oder ist unsicher")
    return _sha256_file(path)


def _saved_toolchains(root: Path) -> tuple[dict, str | None]:
    """Read exactly the local toolchain hints used by Suite.load_environment."""
    path = _source(root, "config/toolchains.local.json")
    if not path.exists():
        return {}, None
    digest = _checked_file(path, 512 * 1024, "Gespeicherte Toolchain")
    try:
        record = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_strict_pairs,
            parse_constant=_bad_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise BuildReadinessError(
            f"Gespeicherte Toolchain-Konfiguration fehlerhaft: {exc}"
        ) from exc
    if (
        not isinstance(record, dict)
        or any(
            name in record
            and (not isinstance(record[name], str) or len(record[name]) > 2048)
            for name in ("unity_editor", "dotnet_directory")
        )
    ):
        raise BuildReadinessError("Gespeicherte Toolchain-Pfade sind ungültig")
    return record, digest


def _same_choice(selected: str | None, active: Path) -> bool:
    if not selected:
        return True
    try:
        return Path(selected).expanduser().resolve(strict=True) == active.resolve(strict=True)
    except (ValueError, OSError, RuntimeError):
        return False


def _same_game_choice(selected: str | None, active: Path, kind: str) -> bool:
    """Treat a selected install root and its canonical *_Data folder alike."""
    if _same_choice(selected, active):
        return True
    if not selected:
        return True
    try:
        chosen = Path(selected).expanduser().resolve(strict=True)
        saved = active.resolve(strict=True)
        if kind == "source":
            return chosen / SOURCE_DIR == saved
        if kind == "target":
            return chosen.name == TARGET_DIR and chosen.parent == saved
    except (OSError, ValueError, RuntimeError):
        return False
    return False


def _sdk_directory(hint: str | None) -> Path | None:
    try:
        if hint:
            return resolve_dotnet_directory(Path(hint))
        return find_dotnet_sdk()
    except (OSError, ValueError, RuntimeError):
        return None


def _sdk_on_disk(hint: str | None) -> tuple[bool, str]:
    """Inspect stable SDK directories; never launch the .NET CLI."""
    if hint:
        try:
            folder = resolve_dotnet_directory(Path(hint))
        except (OSError, ValueError) as exc:
            return False, f"Ausgewählter .NET-Pfad ungültig: {exc}"
    else:
        folder = find_dotnet_sdk()
        if folder is None:
            return False, (
                "Kein stabiles .NET-SDK gefunden (PATH, portables SDK, "
                "DOTNET_ROOT oder Windows-Installation). Nur Runtime reicht nicht."
            )
    executable = folder / ("dotnet.exe" if (folder / "dotnet.exe").exists() else "dotnet")
    sdk = folder / "sdk"
    if not executable.is_file() or _is_link(executable):
        return False, "dotnet-Programm fehlt"
    if not sdk.is_dir() or _is_link(sdk):
        return False, "SDK-Unterordner fehlt; nur Runtime ist nicht ausreichend"
    valid = [
        entry.name for entry in sdk.iterdir()
        if entry.is_dir() and not _is_link(entry) and sdk_supported(entry.name)
    ]
    if not valid:
        return False, f"Kein stabiles .NET-SDK ab {sdk_minimum()} installiert"
    return True, (
        f"SDK {', '.join(sorted(valid))} auf Datenträger gefunden; "
        "Programm nicht ausgeführt"
    )


def audit_build_readiness(
    project_root: str | Path, profile_id: str, *,
    replace: bool = False,
    unity_hint: str | None = None,
    dotnet_hint: str | None = None,
    source_hint: str | None = None,
    target_hint: str | None = None,
) -> dict[str, Any]:
    """Report prerequisites for an ATTEMPT, never a build/release approval."""
    if not isinstance(profile_id, str) or not ID.fullmatch(profile_id):
        raise BuildReadinessError("Ungültige Profil-ID")
    if type(replace) is not bool:
        raise BuildReadinessError("Ersetzen-Auswahl muss boolesch sein")
    if any(value is not None and (
        not isinstance(value, str) or len(value) > 2048
    ) for value in (unity_hint, dotnet_hint, source_hint, target_hint)):
        raise BuildReadinessError("Ungültige Toolchain-Pfade")
    root = Path(project_root).resolve(strict=True)
    rows: list[dict] = []
    hashes: dict[str, str] = {}

    def add(name: str, state: str, detail: str, next_step: str) -> None:
        if state not in ("ok", "blockiert", "hinweis"):
            raise AssertionError(state)
        rows.append({
            "name": name, "state": state,
            "detail": detail, "next_step": next_step,
        })

    profile = None
    backend_is_v2 = False
    runtime_needed = False
    try:
        path = _source(root, f"profiles/{profile_id}.json")
        hashes["profile_sha256"] = _checked_file(path, 4 * 1024 * 1024, "Profil")
        profile = load_profile(path)
        if profile.get("id") != profile_id:
            raise BuildReadinessError("Profil-ID stimmt nicht mit dem Dateinamen überein")
        _validate_group_backend_selection(profile)
        atlas_backend = profile.get("atlas_backend")
        backend_is_v2 = isinstance(atlas_backend, dict) and (
            atlas_backend.get("kind") == "unity_assetbundle_bc7_visual_equivalence_v2"
        )
        runtime_needed = profile.get("runtime") is not None
        add("Profil", "ok", f"{profile_id}: gültiger Vertrag; "
            f"SHA-256 {hashes['profile_sha256'][:16]}…", "Keine Aktion")
    except (OSError, ValueError, TypeError, ModBuildError) as exc:
        add("Profil", "blockiert", str(exc),
            "Paket bauen → ein gültiges Profil wählen")

    config = None
    try:
        path = _source(root, "config/installations.local.toml")
        hashes["config_sha256"] = _checked_file(path, 512 * 1024, "Spielkonfiguration")
        config = load_config(path)
        missing = []
        for label, directory in (("SH1DE", config.source.data_dir),
                                 ("SHCDE", config.target.data_dir)):
            if not directory.is_dir() or not (directory / "resources.assets").is_file():
                missing.append(f"{label}: Original-resources.assets fehlt")
        if config.target.game_dir is None or not config.target.game_dir.is_dir():
            missing.append("Crusader-Spielordner nicht vorhanden")
        if not _same_game_choice(source_hint, config.source.data_dir, "source"):
            missing.append(
                "Angezeigter SH1DE-Spielordner ist noch nicht gespeichert"
            )
        if (
            config.target.game_dir is not None
            and not _same_game_choice(target_hint, config.target.game_dir, "target")
        ):
            missing.append(
                "Angezeigter Crusader-Spielordner ist noch nicht gespeichert"
            )
        if missing:
            raise BuildReadinessError("; ".join(missing))
        add("Originalspiele", "ok", "Spielordner und beide resources.assets vorhanden "
            "(Inhalt nicht erneut inventarisiert)", "Keine Aktion")
    except (OSError, ValueError, ConfigurationError) as exc:
        add("Originalspiele", "blockiert", str(exc),
            "Einrichten → Spielordner wählen → Pfade speichern")

    try:
        mapping = _source(root, "work/mapping/proposals.json.gz")
        if not mapping.is_file() or _is_link(mapping):
            raise BuildReadinessError("Original-Mapping fehlt")
        data, digest = _read_pinned_mapping(mapping)
        hashes["mapping_sha256"] = digest
        if not all(isinstance(data.get(key), str) and data[key]
                   for key in ("source_build_id", "target_build_id")):
            raise BuildReadinessError("Quell-/Ziel-Build-IDs fehlen")
        add("Mapping", "ok", f"{len(data['sprites'])} Spritevorschläge, "
            f"SHA-256 {digest[:16]}…", "Nach Ressourcenänderungen: Spiele neu einlesen")
    except (OSError, ValueError, PivotNativeProvenanceError) as exc:
        add("Mapping", "blockiert", str(exc),
            "Einrichten → Spiele einlesen")

    saved_toolchains = {}
    try:
        saved_toolchains, pinned_sha = _saved_toolchains(root)
        if pinned_sha is not None:
            hashes["toolchains_sha256"] = pinned_sha
    except (OSError, ValueError, BuildReadinessError) as exc:
        add(
            "Toolchain-Einstellungen", "blockiert", str(exc),
            "Einrichten → Unity-/.NET-Pfade kontrollieren und speichern"
        )

    if profile is None:
        add("Unity-BC7", "hinweis", "Backend ohne gültiges Profil unbekannt",
            "Zuerst Profil reparieren")
        add(".NET-SDK", "hinweis", "Runtime-Anforderung ohne Profil unbekannt",
            "Zuerst Profil reparieren")
    else:
        if backend_is_v2:
            try:
                # A typed but UNSAVED path is not automatically passed to
                # suite_workflow. Verify the editor that the subsequent real
                # launcher will actually choose, not a hypothetical path.
                saved_unity = saved_toolchains.get("unity_editor")
                editor = _resolve_toolchain(
                    root, Path(saved_unity) if saved_unity else None
                )
                if not _same_choice(unity_hint, editor.executable):
                    raise BuildReadinessError(
                        "Gewählter Unity-Pfad weicht vom tatsächlichen "
                        "Builder-Pfad ab; unter Einrichten speichern"
                    )
                contract_path = _source(
                    root, "config/unity-assetbundle-toolchain.json"
                )
                hashes["unity_contract_sha256"] = _checked_file(
                    contract_path, 512 * 1024, "Unity-Pin"
                )
                contract = json.loads(contract_path.read_text(encoding="utf-8"))
                if editor.executable_sha256 != contract.get("windows_executable_sha256"):
                    raise BuildReadinessError(
                        "Unity.exe-SHA-256 weicht von der festgeschriebenen Version ab"
                    )
                add("Unity-BC7", "ok",
                    "Unity 2021.3.45f2 samt Revision und SHA-256 bestätigt; "
                    "nicht gestartet",
                    "Keine Aktion")
            except (OSError, ValueError, AssetStreamBuildError) as exc:
                add("Unity-BC7", "blockiert", str(exc),
                    "Einrichten → exakt Unity 2021.3.45f2 wählen "
                    "(Unity 6000 ist kein Ersatz)")
        else:
            add("Unity-BC7", "hinweis",
                "Profil verwendet keinen V2-BC7-Backendvertrag",
                "Profiltyp beachten")
        if runtime_needed:
            saved_sdk = saved_toolchains.get("dotnet_directory")
            actual_sdk = _sdk_directory(saved_sdk)
            selected_sdk = _sdk_directory(dotnet_hint)
            if dotnet_hint and (actual_sdk is None or selected_sdk != actual_sdk):
                valid, detail = (
                    False,
                    "Ausgewähltes .NET-SDK ist nicht als tatsächlich "
                    "verwendeter SDK-Pfad gespeichert. Erst Einrichten → Pfade speichern."
                )
            else:
                valid, detail = _sdk_on_disk(saved_sdk)
            add(".NET-SDK", "ok" if valid else "blockiert",
                detail, "Einrichten → .NET SDK ab 8.0.100 wählen"
                if not valid else "SDK wurde nicht gestartet")
        else:
            add(".NET-SDK", "hinweis", "Profil verlangt keine Runtime-DLL",
                "Keine Aktion")

    output_target = None
    output_exists = None
    if config is None:
        add("Paketausgabe", "hinweis",
            "Ausgabeort ohne gültige Spielkonfiguration nicht bestimmbar",
            "Erst Spielpfade einrichten")
    else:
        target = config.output.dist_dir / profile_id / config.output.mod_folder_name
        output_target = str(target)
        output_exists = target.exists()
        if _is_link(target) or _is_link(target.parent):
            add("Paketausgabe", "blockiert",
                "Ausgabeziel enthält einen Link/Junction",
                "Ausgabe manuell untersuchen")
        elif target.exists() and not target.is_dir():
            add("Paketausgabe", "blockiert",
                "Ausgabeziel existiert, ist aber kein Verzeichnis",
                "Unsichere Ausgabe manuell untersuchen")
        elif target.exists() and not replace:
            add("Paketausgabe", "blockiert",
                "Paketordner existiert bereits und Ersetzen ist nicht gewählt",
                "Paket bauen → Ersetzen bewusst aktivieren, alte Ausgabe vorher sichern")
        elif target.exists():
            add("Paketausgabe", "hinweis",
                "Vorhandenes Paket könnte beim Bauen ersetzt werden",
                "Vorherige Ausgabe sichern und bewusst prüfen")
        else:
            add("Paketausgabe", "ok",
                "Für dieses Profil ist noch keine Zielausgabe vorhanden",
                "Keine Aktion")

    # Recheck inexpensive source identities to catch mid-audit changes.
    for name, relative in (
        ("profile_sha256", f"profiles/{profile_id}.json"),
        ("config_sha256", "config/installations.local.toml"),
        ("mapping_sha256", "work/mapping/proposals.json.gz"),
        ("unity_contract_sha256", "config/unity-assetbundle-toolchain.json"),
        ("toolchains_sha256", "config/toolchains.local.json"),
    ):
        if name not in hashes:
            continue
        current = _source(root, relative)
        if not current.is_file() or _sha256_file(current) != hashes[name]:
            raise BuildReadinessError("Quellen während der Prüfung verändert: " + relative)

    blockers = sum(row["state"] == "blockiert" for row in rows)
    notices = sum(row["state"] == "hinweis" for row in rows)
    return {
        "schema": SCHEMA, "profile_id": profile_id,
        "replace_selected": replace,
        "state": "blockiert" if blockers else "bauversuch_moeglich",
        "ready_for_attempt": blockers == 0,
        "blocker_count": blockers, "notice_count": notices,
        "checks": rows, "source_hashes": hashes,
        "output_target": output_target,
        "output_exists_at_check": output_exists,
        "no_changes_made": True, "build_executed": False,
        "release_certified": False,
        "disclaimer": (
            "Only selected local prerequisites were inspected. This does "
            "not verify a complete Unity/BC7 build, pinned geometry, "
            "shader equivalence, in-game behaviour or a release."
        ),
    }


__all__ = [
    "SCHEMA", "BuildReadinessError", "audit_build_readiness",
    "recheck_build_readiness_before_start",
]



def recheck_build_readiness_before_start(
    project_root: str | Path,
    profile_id: str,
    *,
    replace: bool,
    report: dict[str, Any],
) -> None:
    """Fail closed over the form and pinned files after human confirmation.

    This is an additional UI guard, NOT a replacement for the transaction's
    own toolchain/source/proof validators. In particular, the report is never
    treated as a reusable permission token or release certificate.
    """
    if (
        not isinstance(report, dict)
        or report.get("schema") != SCHEMA
        or report.get("profile_id") != profile_id
        or report.get("replace_selected") is not replace
        or report.get("state") != "bauversuch_moeglich"
        or report.get("ready_for_attempt") is not True
        or type(report.get("blocker_count")) is not int
        or report["blocker_count"] != 0
        or report.get("no_changes_made") is not True
        or report.get("build_executed") is not False
        or report.get("release_certified") is not False
    ):
        raise BuildReadinessError(
            "Bau-Bereitschaft ist ungültig oder gehört zu einer anderen Auswahl"
        )
    rows = report.get("checks")
    if not isinstance(rows, list):
        raise BuildReadinessError("Bau-Bereitschaft hat keine geprüften Voraussetzungen")
    by_name = {}
    for item in rows:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("name"), str)
            or item["name"] in by_name
            or item.get("state") not in {"ok", "hinweis"}
        ):
            raise BuildReadinessError("Bau-Bereitschaft enthält widersprüchliche Prüfzeilen")
        by_name[item["name"]] = item
    if (
        set(by_name) != {
            "Profil", "Originalspiele", "Mapping", "Unity-BC7",
            ".NET-SDK", "Paketausgabe"
        }
        or any(by_name[name]["state"] != "ok"
               for name in ("Profil", "Originalspiele", "Mapping"))
    ):
        raise BuildReadinessError("Erforderliche Basisnachweise fehlen")
    hashes = report.get("source_hashes")
    if not isinstance(hashes, dict):
        raise BuildReadinessError("Quellprüfsummen fehlen")
    expected = {
        "profile_sha256": f"profiles/{profile_id}.json",
        "config_sha256": "config/installations.local.toml",
        "mapping_sha256": "work/mapping/proposals.json.gz",
    }
    if "toolchains_sha256" in hashes:
        expected["toolchains_sha256"] = "config/toolchains.local.json"
    if by_name["Unity-BC7"]["state"] == "ok":
        expected["unity_contract_sha256"] = "config/unity-assetbundle-toolchain.json"
    if set(hashes) != set(expected):
        raise BuildReadinessError(
            "Bau-Bereitschaft hat unvollständige oder fremde SHA-256-Eingänge"
        )
    root = Path(project_root).resolve(strict=True)
    for key, relative in expected.items():
        path = _source(root, relative)
        try:
            if (
                not isinstance(hashes[key], str)
                or len(hashes[key]) != 64
                or not path.is_file()
                or _sha256_file(path) != hashes[key]
            ):
                raise BuildReadinessError(
                    f"Quellstand seit dem Bau-Check geändert: {relative}"
                )
        except OSError as exc:
            raise BuildReadinessError(
                f"Quellstand nicht mehr lesbar: {relative}"
            ) from exc

    # A new output folder appearing while the confirmation dialog is open
    # must not be overwritten even with a checked 'replace' option.
    try:
        config = load_config(_source(root, "config/installations.local.toml"))
        target = config.output.dist_dir / profile_id / config.output.mod_folder_name
        if (
            str(target) != report.get("output_target")
            or type(report.get("output_exists_at_check")) is not bool
            or target.exists() is not report["output_exists_at_check"]
            or _is_link(target) or _is_link(target.parent)
            or (target.exists() and not target.is_dir())
        ):
            raise BuildReadinessError(
                "Paketausgabe hat sich während der Bestätigung verändert"
            )
    except (OSError, ConfigurationError) as exc:
        raise BuildReadinessError(
            f"Paketausgabe nicht mehr sicher überprüfbar: {exc}"
        ) from exc

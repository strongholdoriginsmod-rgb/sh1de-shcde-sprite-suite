"""Safe, incremental local setup: game directories and tools are independent.

The GUI and suite.py CLI share this backend. Nothing is written to a
game directory or package output, and saved local settings survive a
toolchain-only or game-only update. This is setup, not build readiness.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile
import tomllib

from .config import ConfigurationError, load_config
from .sdk_toolchain import (
    find_dotnet_sdk, installed_sdk_versions, resolve_dotnet_directory,
)

SOURCE_DIR = "Stronghold 1 Definitive Edition_Data"
TARGET_DIR = "Stronghold Crusader Definitive Edition_Data"


def normalized_games(source: Path, target: Path) -> tuple[Path, Path, Path]:
    """Allow choosing game roots or the canonical *_Data folders."""
    first = source.expanduser().resolve(strict=True)
    second = target.expanduser().resolve(strict=True)
    if first.name != SOURCE_DIR:
        first /= SOURCE_DIR
    if second.name == TARGET_DIR:
        second = second.parent
    second_data = second / TARGET_DIR
    if not first.is_dir() or not second_data.is_dir():
        raise ValueError(
            "Spielordner noch unvollständig: Bitte SH1DE- und SHCDE-"
            "Installationsordner (oder ihre *_Data-Unterordner) wählen."
        )
    return first, second, second_data


def normalized_unity(selection: Path) -> Path:
    """Accept Unity.exe, the Editor folder or the version install root."""
    path = selection.expanduser().resolve(strict=True)
    if path.is_dir():
        path = next(
            (candidate for candidate in (path / "Unity.exe",
                                         path / "Editor" / "Unity.exe")
             if candidate.is_file()),
            path,
        )
    if not path.is_file() or path.name.casefold() != "unity.exe":
        raise ValueError(
            "Unity-Auswahl: Bitte Unity.exe, ihren Editor-Ordner "
            "oder den Unity-Versionsordner wählen."
        )
    return path


def _strict_pairs(pairs: list[tuple[str, object]]) -> dict:
    record: dict = {}
    for name, value in pairs:
        if name in record:
            raise ValueError("Doppelter Eintrag in lokalen Werkzeug-Einstellungen: " + name)
        record[name] = value
    return record


def _existing(path: Path) -> bytes | None:
    if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
        raise ValueError(f"Lokale Einstellung ist ein Link/Junction: {path}")
    if not path.exists():
        return None
    if not path.is_file() or path.stat().st_size > 512 * 1024:
        raise ValueError(f"Lokale Einstellung ist keine reguläre kleine Datei: {path}")
    return path.read_bytes()


def _render_default(first: Path, second: Path, second_data: Path) -> str:
    quote = lambda path: json.dumps(str(path).replace("\\", "/"), ensure_ascii=False)
    return (
        '[source]\nname = "Stronghold 1 Definitive Edition"\ndata_dir = ' + quote(first)
        + '\n\n[target]\nname = "Stronghold Crusader Definitive Edition"\ngame_dir = ' + quote(second)
        + '\ndata_dir = ' + quote(second_data)
        + '\n\n[output]\nwork_dir = "work"\ncache_dir = "cache"\nstate_dir = "state"\n'
        'dist_dir = "dist"\nmod_folder_name = "StrongholdEuropeDE"\n\n'
        '[policy]\nprivate_local_only = true\nallow_game_archive_writes = false\nallow_unknown_builds = false\n'
    )


def _update_game_values(previous: str, first: Path, second: Path,
                        second_data: Path) -> str:
    """Edit only three existing keys; preserve output policy, comments, extras."""
    wanted = {
        ("source", "data_dir"): first,
        ("target", "game_dir"): second,
        ("target", "data_dir"): second_data,
    }
    seen: set[tuple[str, str]] = set()
    section = ""
    output: list[str] = []
    for line in previous.splitlines(keepends=True):
        heading = re.fullmatch(
            r"\s*\[([a-zA-Z0-9_.-]+)\]\s*(?:#.*)?", line.rstrip("\r\n")
        )
        if heading is not None:
            section = heading.group(1)
        assignment = re.match(r"^(\s*([a-zA-Z0-9_-]+)\s*=\s*).*$", line)
        match_key = (section, assignment.group(2)) if assignment else None
        if match_key in wanted:
            if match_key in seen:
                raise ValueError("Spielkonfiguration enthält mehrdeutige Felder")
            seen.add(match_key)
            newline = "\r\n" if line.endswith("\r\n") else "\n"
            output.append(
                assignment.group(1)
                + json.dumps(str(wanted[match_key]).replace("\\", "/"), ensure_ascii=False)
                + newline
            )
        else:
            output.append(line)
    if seen != set(wanted):
        raise ValueError("Spielkonfiguration hat fehlende Pfadfelder")
    return "".join(output)


def _stage(path: Path, data: bytes) -> Path:
    fd, name = tempfile.mkstemp(prefix=".suite-setup-", suffix=".tmp", dir=path.parent)
    candidate = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        candidate.unlink(missing_ok=True)
        raise
    return candidate


def _backup(path: Path, old: bytes) -> Path:
    """Keep the original bytes when changing a previously stored setting."""
    moment = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    candidate = path.with_name(path.name + ".bak-" + moment)
    with candidate.open("xb") as stream:
        stream.write(old)
        stream.flush()
        os.fsync(stream.fileno())
    return candidate


def save_local_setup(root: Path, *, source: Path | None = None,
                     target: Path | None = None, unity: Path | None = None,
                     dotnet: Path | None = None, replace: bool = False,
                     repair_toolchains: bool = False) -> dict:
    """Validate all requested changes first, then publish atomically per file.

    Existing settings are never cleared by omitted inputs. A changed game
    selection requires --replace (GUI asks first). Existing files are
    backed up; no temporary or backup file is ever used as build approval.
    """
    root = root.resolve(strict=True)
    if not any(value is not None for value in (source, target, unity, dotnet)):
        raise ValueError(
            "Keine Pfade ausgewählt. Spielordner oder Unity/.NET-SDK einzeln angeben."
        )
    if repair_toolchains and unity is None and dotnet is None:
        raise ValueError("Werkzeugreparatur benötigt einen gewählten Unity- oder SDK-Pfad")
    config_dir = root / "config"
    if (not config_dir.is_dir() or config_dir.is_symlink()
            or (hasattr(config_dir, "is_junction") and config_dir.is_junction())):
        raise ValueError("Projekt-Konfigurationsordner fehlt oder ist ein Link")
    game_path = config_dir / "installations.local.toml"
    tools_path = config_dir / "toolchains.local.json"
    game_old = _existing(game_path)
    tools_old = _existing(tools_path)
    proposals: list[tuple[Path, bytes | None, bytes]] = []

    if source is not None or target is not None:
        previous = None
        if game_old is not None:
            try:
                previous = load_config(game_path)
            except (OSError, ValueError, TypeError, KeyError, tomllib.TOMLDecodeError):
                if not replace or source is None or target is None:
                    raise ValueError(
                        "Bestehende Spielkonfiguration ist ungültig. Beide Spiele "
                        "neu wählen und nach Sicherung ausdrücklich ersetzen."
                    ) from None
        if source is None:
            if previous is None:
                raise ValueError("SH1DE-Spielordner fehlt; Unity/.NET getrennt speicherbar.")
            source = previous.source.data_dir
        if target is None:
            if previous is None:
                raise ValueError("SHCDE-Spielordner fehlt; Unity/.NET getrennt speicherbar.")
            target = previous.target.game_dir
        first, second, second_data = normalized_games(source, target)
        same = (previous is not None
                and previous.source.data_dir == first
                and previous.target.game_dir == second
                and previous.target.data_dir == second_data)
        if game_old is not None and not same and not replace:
            raise ValueError(
                "Gespeicherte Spielpfade würden geändert. "
                "Mit --replace nach Prüfung ausdrücklich bestätigen."
            )
        if not same:
            new_text = (_update_game_values(
                game_old.decode("utf-8"), first, second, second_data
            ) if previous is not None else _render_default(first, second, second_data))
            new_bytes = new_text.encode("utf-8")
            if new_bytes != game_old:
                proposals.append((game_path, game_old, new_bytes))

    if unity is not None or dotnet is not None:
        try:
            settings = _toolchain_record(tools_old) if tools_old is not None else {}
        except (UnicodeError, ValueError, TypeError) as exc:
            if not repair_toolchains:
                raise ValueError(
                    f"Werkzeug-Konfiguration ungültig: {exc}. "
                    "Für eine gesicherte Reparatur --repair-toolchain angeben."
                ) from exc
            settings = {}
        settings = dict(settings)
        if unity is not None:
            settings["unity_editor"] = str(normalized_unity(unity))
        if dotnet is not None:
            settings["dotnet_directory"] = str(resolve_dotnet_directory(dotnet))
        new_bytes = (json.dumps(settings, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        if new_bytes != tools_old:
            proposals.append((tools_path, tools_old, new_bytes))

    staged: list[tuple[Path, bytes | None, Path]] = []
    try:
        for path, old, new in proposals:
            stage = _stage(path, new)
            staged.append((path, old, stage))
            if path == game_path:
                # Validate the actual persisted representation before replacing.
                load_config(stage)
        for path, old, stage in staged:
            if _existing(path) != old:
                raise ValueError(
                    f"Einstellung wurde während des Speicherns geändert: {path.name}"
                )
        # Prepare both backups before changing either file. If a second
        # replacement fails, restore the first from its preserved bytes.
        backups = [
            str(_backup(path, old)) for path, old, _ in staged if old is not None
        ]
        published: list[tuple[Path, bytes | None]] = []
        try:
            for path, old, stage in staged:
                os.replace(stage, path)
                published.append((path, old))
        except OSError as exc:
            rollback_errors = []
            for path, old in reversed(published):
                try:
                    if old is None:
                        path.unlink()
                    else:
                        restoration = _stage(path, old)
                        try:
                            os.replace(restoration, path)
                        finally:
                            restoration.unlink(missing_ok=True)
                except OSError as recovery_exc:
                    rollback_errors.append(str(recovery_exc))
            if rollback_errors:
                raise OSError(
                    "Speichern teilweise fehlgeschlagen; Wiederherstellung "
                    "unvollständig. Sicherungen prüfen: " + ", ".join(backups)
                ) from exc
            raise OSError(
                "Speichern fehlgeschlagen, vorherige Einstellungen wiederhergestellt"
            ) from exc
        return {
            "game_updated": any(p == game_path for p, _, _ in staged),
            "tools_updated": any(p == tools_path for p, _, _ in staged),
            "backup_files": backups,
            "unchanged": not staged,
        }
    finally:
        for _, _, stage in staged:
            stage.unlink(missing_ok=True)

def _toolchain_record(content: bytes) -> dict:
    """Parse a bounded settings document without duplicate or invalid paths."""
    def reject_constant(value: str):
        raise ValueError("Unzulässige JSON-Konstante: " + value)

    result = json.loads(
        content.decode("utf-8"), object_pairs_hook=_strict_pairs,
        parse_constant=reject_constant,
    )
    if not isinstance(result, dict):
        raise ValueError("JSON-Wurzel muss ein Objekt sein")
    for name in ("unity_editor", "dotnet_directory"):
        if name in result and (
            not isinstance(result[name], str) or len(result[name]) > 2048
        ):
            raise ValueError(name + " muss ein kurzer Textpfad sein")
    return result


def inspect_toolchain_hints(root: Path) -> tuple[dict, tuple[str, ...]]:
    """Read local tool paths without stopping unrelated Suite workflows.

    Missing settings are normal. Invalid bytes are never repaired, replaced
    or trusted here. The strict BC7 readiness validator is intentionally
    independent of this lenient navigation/setup reader.
    """
    path = root / "config" / "toolchains.local.json"
    try:
        content = _existing(path)
        if content is None:
            return {}, ()
        return _toolchain_record(content), ()
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        return {}, (
            "Lokale Werkzeugkonfiguration nicht verwendbar: "
            + str(exc)
            + ". Andere Suite-Funktionen bleiben nutzbar. "
            "Zum Reparieren einen Werkzeugpfad wählen und die "
            "gesicherte Wiederherstellung ausdrücklich bestätigen.",
        )


def diagnose_local_setup(root: Path) -> dict:
    """Read-only, actionable setup diagnosis (not BC7 readiness)."""
    root = root.resolve(strict=True)
    checks: list[dict[str, str]] = []

    def add(name: str, state: str, detail: str, next_step: str) -> None:
        checks.append({
            "name": name, "state": state, "detail": detail,
            "next_step": next_step,
        })

    game_path = root / "config" / "installations.local.toml"
    try:
        content = _existing(game_path)
        if content is None:
            add("Spielpfade", "hinweis", "Noch keine lokalen Spiele gespeichert.",
                "Einrichten → Spiele auswählen; Werkzeuge dürfen vorher eingerichtet werden.")
        else:
            config = load_config(game_path)
            missing = [
                label for label, data in (
                    ("SH1DE", config.source.data_dir),
                    ("SHCDE", config.target.data_dir),
                ) if not (data / "resources.assets").is_file()
            ]
            if config.target.game_dir is None or not config.target.game_dir.is_dir():
                missing.append("Crusader-Spielverzeichnis")
            if missing:
                add("Spielpfade", "warnung",
                    "Gespeicherte Originaldateien/Ordner fehlen: " + ", ".join(missing),
                    "Einrichten → Spielpfade korrigieren; bisherige Konfiguration wird gesichert.")
            else:
                add("Spielpfade", "ok",
                    "Beide Spielordner und resources.assets vorhanden; "
                    "Originaldateiinhalte noch nicht geprüft.",
                    "Vor dem BC7-Bau erneut die vollständigen Bauvoraussetzungen prüfen.")
    except (OSError, UnicodeError, ValueError, TypeError, KeyError) as exc:
        add("Spielpfade", "warnung",
            "Gespeicherte Spielkonfiguration konnte nicht gelesen werden: " + str(exc),
            "Beide Spielordner wählen und Änderung mit vorheriger Sicherung bestätigen.")

    settings, warnings = inspect_toolchain_hints(root)
    if warnings:
        add("Werkzeug-Einstellungen", "warnung", warnings[0],
            "Bei Reparatur erst den Werkzeugpfad auswählen, dann Backup bestätigen.")
    elif settings:
        add("Werkzeug-Einstellungen", "ok",
            "Gespeicherte Werkzeug-Konfiguration lesbar; "
            "Pfade werden unabhängig geprüft.",
            "Keine Aktion, falls die Einzelprüfungen passen.")
    else:
        add("Werkzeug-Einstellungen", "hinweis",
            "Noch keine benutzerdefinierten Werkzeugpfade gespeichert.",
            "Vorhandene SDKs können automatisch gefunden werden.")

    unity = settings.get("unity_editor")
    if unity:
        try:
            editor = Path(unity).expanduser()
            usable = editor.name.casefold() == "unity.exe" and editor.is_file()
        except (ValueError, OSError):
            usable = False
        add("Unity", "ok" if usable else "warnung",
            ("Ausgewähltes Unity.exe vorhanden; Version, Revision und SHA-256 "
             "hier noch nicht bestätigt."
             if usable else "Ausgewählter Unity-Editor existiert nicht mehr."),
            ("Bauvoraussetzungen prüfen" if usable
             else "Unity 2021.3.45f2 auswählen oder Pfad korrigieren."))
    else:
        add("Unity", "hinweis", "Kein Unity-Editor lokal ausgewählt.",
            "Für einen BC7-Neubau Unity 2021.3.45f2 wählen; "
            "andere Arbeitsbereiche bleiben nutzbar.")

    hint = settings.get("dotnet_directory")
    sdk_dir: Path | None = None
    if hint:
        try:
            sdk_dir = resolve_dotnet_directory(Path(hint))
            if not installed_sdk_versions(sdk_dir):
                sdk_dir = None
        except (ValueError, OSError, RuntimeError):
            sdk_dir = None
    discovered = find_dotnet_sdk(root)
    if sdk_dir is not None:
        add(".NET-SDK", "ok",
            "Gespeichertes stabiles SDK gefunden: " + str(sdk_dir)
            + "; nicht ausgeführt.",
            "Echter Builder prüft die SDK-Version vor dem Bau erneut.")
    elif discovered is not None:
        add(".NET-SDK", "hinweis" if not hint else "warnung",
            "Kompatibles SDK automatisch auffindbar: " + str(discovered)
            + ("; gespeicherter Pfad ist veraltet." if hint else ".")
            + " Programm nicht gestartet.",
            "Bei einem veralteten Eintrag: Einrichten → SDK-Auswahl aktualisieren.")
    else:
        add(".NET-SDK", "warnung" if hint else "hinweis",
            "Kein stabiles vollständiges SDK ab 8.0.100 gefunden.",
            "SDK auswählen, falls das Profil eine Runtime-DLL benötigt.")

    return {
        "schema": "stronghold-europe.suite-local-setup-diagnostics.v1",
        "checks": checks,
        "warning_count": sum(item["state"] == "warnung" for item in checks),
        "notice_count": sum(item["state"] == "hinweis" for item in checks),
        "no_changes_made": True,
        "build_executed": False,
        "release_certified": False,
    }


def read_game_path_hints(root: Path) -> tuple[dict[str, str], tuple[str, ...]]:
    """Read saved game paths defensively for the GUI's initial fields.

    A malformed local TOML document may not stop the Suite opening.
    No file is changed or automatically repaired by this reader.
    """
    path = root / "config" / "installations.local.toml"
    try:
        content = _existing(path)
        if content is None:
            return {}, ()
        config = load_config(path)
        return {
            "source": str(config.source.data_dir),
            "target": str(config.target.game_dir),
        }, ()
    except (
        OSError, UnicodeError, ValueError, TypeError, KeyError,
        AttributeError, IndexError, RecursionError,
    ) as exc:
        return {}, (
            "Gespeicherte Spielkonfiguration nicht lesbar: " + str(exc)
            + ". Die vorhandene Datei bleibt unangetastet. "
            "Beide Spiele bei Bedarf erneut auswählen und Änderung "
            "mit vorheriger Sicherung bestätigen.",
        )

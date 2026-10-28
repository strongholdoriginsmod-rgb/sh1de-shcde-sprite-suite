"""Zielspiele verwalten und auf SHCDE-SE 2.11.0 ausrichten - mit Rueckweg.

Die Suite ist auf Script Extender 2.11.0 ausgerichtet. Dieses Werkzeug kennt
mehrere Spielinstallationen (z.B. das 2.7-Spiel auf E: und die 2.80-Kopie auf D:),
schaltet das aktive Ziel um und installiert SE 2.11.0 oder einen Modordner in ein
Zielspiel. Vor jedem Schreibvorgang wird gesichert; jede Sicherung laesst sich
wieder einspielen, und das Einspielen sichert seinerseits den Stand davor.
Hin und her geht damit beliebig oft.

    python tools/ziel_se211.py liste
    python tools/ziel_se211.py hinzufuegen --name d-kopie --spiel "<Spielordner von SHC:DE>"
    python tools/ziel_se211.py aktivieren d-kopie
    python tools/ziel_se211.py se-installieren d-kopie
    python tools/ziel_se211.py sicherungen d-kopie
    python tools/ziel_se211.py zurueckspielen d-kopie --sicherung <id>
    python tools/ziel_se211.py mod-installieren d-kopie --quelle dist/benutzer/StrongholdEuropeDE

Das Spiel muss dabei geschlossen sein; laeuft es, gibt es eine Warnung.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import subprocess
import sys
import tomllib
import zipfile
import os
import re
import tempfile
from target_selection_guard import (
    TargetSelectionError, verify_target,verify_registered,verify_active,
)
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ZIELE = PROJECT_ROOT / "config" / "ziele.json"
CONFIG = PROJECT_ROOT / "config" / "installations.local.toml"
SE_ZIP_CANDIDATES = (
    PROJECT_ROOT / "extras" / "shcdese" / "SHCDESE-2.11.0.zip",
    PROJECT_ROOT.parent / "daten" / "script-extender" / "SHCDESE-2.11.0.zip",
)
SE_ZIP_SHA256 = "a7b2c58ffb07df60e5c2510795179b060da2f3b89fd32dedd1a1c257e93374c5"
DATA = "Stronghold Crusader Definitive Edition_Data"
KNOWN_GAMES = {
    "2df11d73": "SHC:DE 2.7",
    "01da4c57": "SHC:DE 2.80",
}
SE_PATHS = ("BepInEx/plugins/000shcdese", "BepInEx/config/000shcdese.cfg", "BepInEx/config/uuimgui.cfg",
            "msvcp140.dll", "shcde-vanilla.bat", "shcde-vanilla.sh")


def say(text=""):
    print(text, flush=True)


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return default


def save_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def file_version(path: Path) -> str | None:
    try:
        import pefile

        pe = pefile.PE(str(path), fast_load=True)
        pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]])
        for info in getattr(pe, "FileInfo", []) or []:
            for entry in info:
                for table in getattr(entry, "StringTable", []) or []:
                    value = table.entries.get(b"FileVersion") or table.entries.get(b"ProductVersion")
                    if value:
                        return value.decode("utf-8", "replace")
    except Exception:
        return None
    return None


def targets() -> dict:
    """Do not *implicitly* make a legacy 2.7 target active.

    A target is active only after an explicit, full 5-file verified choice.
    """
    default={"schema":"stronghold-europe.ziele.v1","ziele":{},"aktiv":None}
    if not ZIELE.exists():
        return default
    data=load_json(ZIELE,default)
    if (not isinstance(data,dict) or data.get("schema")!=default["schema"]
            or not isinstance(data.get("ziele"),dict)
            or (data.get("aktiv") is not None and
                data["aktiv"] not in data["ziele"])):
        raise TargetSelectionError("Zielregistry beschädigt; kein Ziel wird aktiviert")
    return data

def atomic_save_bytes(path: Path, content: bytes):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix="."+path.name+"-",suffix=".tmp",
                            dir=path.parent)
    try:
        with os.fdopen(fd,"wb") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def safe_target(name):
    """Reverify bytes on EACH installation/rollback/write action."""
    active,att=verify_active(root=PROJECT_ROOT)
    if active!=name:
        raise TargetSelectionError(
            f"Ziel '{name}' ist nicht aktiv. Bitte Version prüfen und explizit aktivieren.")
    return att.game_dir


def safe_component(name: str) -> str:
    if (not isinstance(name,str) or
            not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}",name) or
            name in (".","..") or name.endswith(".") or
            name.upper().split(".")[0] in {"CON","NUL","PRN","AUX"}):
        raise SystemExit("Unsicherer Plugin-/Ordnername")
    return name


FOREIGN_COMMUNITY_PLUGIN_FOLDERS = frozenset({
    "000shcdese", "apishared_serp", "crusaderdetweaker",
    "fixes", "serpsmods", "serpsmodshost",
})


def assert_safe_restore_paths(game: Path, paths):
    if not isinstance(paths,list):
        raise SystemExit("Sicherungsindex enthält keine gültigen Pfade")
    for relative in paths:
        if not isinstance(relative,str) or not relative:
            raise SystemExit("Sicherungsindex enthält einen ungültigen Pfad")
        resolved=(game/relative).resolve()
        if not resolved.is_relative_to(game.resolve()) or ".." in Path(relative).parts:
            raise SystemExit("Sicherungsindex enthält einen Pfad außerhalb des Zielspiels")
        segments = relative.replace("\\", "/").split("/")
        if (len(segments) >= 3 and segments[0].casefold() == "bepinex"
                and segments[1].casefold() == "plugins"
                and segments[2].casefold() in FOREIGN_COMMUNITY_PLUGIN_FOLDERS):
            raise SystemExit("Sicherungsindex verweist auf geschütztes Fremdplugin: " + relative)


def describe(name: str, spec: dict) -> dict:
    game = Path(spec["spiel"])
    info = {"name": name, "spiel": str(game), "vorhanden": game.is_dir()}
    acs = game / DATA / "Managed" / "Assembly-CSharp.dll"
    if acs.is_file():
        digest = sha256(acs)
        info["spielstand"] = KNOWN_GAMES.get(digest[:8], f"unbekannt ({digest[:8]})")
    se = game / "BepInEx" / "plugins" / "000shcdese" / "SHCDESE.dll"
    info["se"] = file_version(se) if se.is_file() else None
    manifest = load_json(game / "BepInEx" / "plugins" / "StrongholdEuropeDE" / "build-manifest.json", None)
    info["europa_mod"] = manifest.get("profile_id") if isinstance(manifest, dict) else None
    info["sicherungen"] = len(load_json(backup_root(game) / "sicherungen.json", {"eintraege": []})["eintraege"])
    return info


def game_running() -> bool:
    """Detect both game EXE names; fail closed if tasklist cannot be inspected."""
    try:
        result = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"], capture_output=True,
            text=True, encoding="cp850", errors="replace", timeout=10,
        )
        if result.returncode != 0:
            return True
        names = {row[0].strip().casefold()
                 for row in csv.reader(result.stdout.splitlines()) if row}
        return bool(names & {
            "stronghold crusader.exe",
            "stronghold crusader definitive edition.exe",
        })
    except (OSError, subprocess.TimeoutExpired, csv.Error):
        return True


def backup_root(game: Path) -> Path:
    return game / "_suite-sicherungen"


def make_backup(game: Path, paths: list[str], reason: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    root = backup_root(game)
    target = root / stamp
    n = 1
    while target.exists():
        n += 1
        target = root / f"{stamp}-{n}"
    target.mkdir(parents=True)
    saved = []
    for relative in paths:
        source = game / relative
        if source.is_dir():
            shutil.copytree(source, target / relative)
            saved.append(relative)
        elif source.is_file():
            (target / relative).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target / relative)
            saved.append(relative)
    index = load_json(root / "sicherungen.json", {"eintraege": []})
    index["eintraege"].append({"id": target.name, "zeit": datetime.now().isoformat(timespec="seconds"),
                               "grund": reason, "pfade": paths, "gesichert": saved})
    save_json(root / "sicherungen.json", index)
    say(f"Gesichert nach {target} ({len(saved)} Eintraege)")
    return target.name


def remove_paths(game: Path, paths: list[str]) -> None:
    for relative in paths:
        path = game / relative
        if path.is_dir():
            shutil.rmtree(path)
        elif path.is_file():
            path.unlink()


def resolve(name: str) -> tuple[str, Path]:
    data = targets()
    spec = data["ziele"].get(name)
    if spec is None:
        raise SystemExit(f"Ziel '{name}' unbekannt. Bekannt: {', '.join(data['ziele']) or '-'}")
    return name, Path(spec["spiel"])


# ------------------------------------------------------------------ commands

def cmd_liste(args) -> int:
    data = targets()
    rows = [describe(name, spec) | {"aktiv": name == data.get("aktiv")} for name, spec in data["ziele"].items()]
    if args.json:
        print(json.dumps({"ziele": rows}, ensure_ascii=False))
        return 0
    for row in rows:
        mark = "*" if row["aktiv"] else " "
        se = row["se"] or "kein SE"
        hint = ""
        say(f"{mark} {row['name']:<14} {row.get('spielstand', '?'):<16} SE {se:<12} Europa-Mod: {row['europa_mod'] or '-':<28}"
            f" Sicherungen: {row['sicherungen']}{hint}")
        say(f"    {row['spiel']}")
    return 0


def cmd_hinzufuegen(args) -> int:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,50}",args.name):
        raise SystemExit("Ungültiger Zielname: nur Buchstaben, Ziffern, _ und -")
    try:
        att=verify_target(
            args.spiel,PROJECT_ROOT/"config"/"supported-builds.json",
            PROJECT_ROOT/"work"/"mapping"/"proposals.json.gz")
    except TargetSelectionError as exc:
        raise SystemExit(f"Ziel nicht eingetragen: {exc}") from exc
    data=targets()
    existing=data["ziele"].get(args.name)
    if existing and Path(existing["spiel"]).resolve()!=att.game_dir:
        raise SystemExit("Zielname bereits mit anderem Spielordner registriert")
    data["ziele"][args.name]={
        "spiel":str(att.game_dir).replace("\\","/"),
        "name":args.anzeige or args.name,
        "build_id":att.build_id,
        "verified_files":att.files_checked,
    }
    # Registering is intentionally NOT activation.
    atomic_save_bytes(ZIELE,(json.dumps(data,indent=2,ensure_ascii=False)+"\n").encode())
    say(f"Geprüftes Ziel '{args.name}' registriert: {att.build_id} (5/5); NICHT aktiviert.")
    return 0


def cmd_aktivieren(args) -> int:
    try:
        att=verify_registered(args.name,root=PROJECT_ROOT)
    except TargetSelectionError as exc:
        raise SystemExit(f"Zielaktivierung verweigert: {exc}") from exc
    data=targets()
    if att.build_id!=data["ziele"][args.name].get("build_id"):
        raise SystemExit("Zielbuild seit Registrierung verändert; bitte erneut registrieren")
    old_config=CONFIG.read_bytes() if CONFIG.is_file() else None
    old_registry=ZIELE.read_bytes() if ZIELE.is_file() else None
    try:
        config=tomllib.loads(old_config.decode("utf-8")) if old_config else {}
    except (UnicodeError,ValueError):
        raise SystemExit("Bestehende Konfiguration ungültig – zuerst gesichert reparieren")
    source=args.source_data or config.get("source",{}).get("data_dir","")
    if not source:
        raise SystemExit("SH1DE-Quelle fehlt: --source-data <verifizierter SH1DE_Data-Ordner>")
    try:
        from target_selection_guard import verify_source
        source_path=verify_source(source,PROJECT_ROOT/"config"/"supported-builds.json")
    except TargetSelectionError as exc:
        raise SystemExit(f"Quellspiel ist nicht freigegeben: {exc}") from exc
    game=str(att.game_dir).replace("\\","/")
    source=str(source_path).replace("\\","/")
    output=config.get("output",{})
    lines=[
        "[source]",'name = "Stronghold 1 Definitive Edition"',
        f"data_dir = {json.dumps(source)}","",
        "[target]",f"name = {json.dumps(data['ziele'][args.name].get('name',args.name))}",
        f"game_dir = {json.dumps(game)}",
        f"data_dir = {json.dumps(game+'/'+DATA)}","",
        "[output]",
        'work_dir = "work"','cache_dir = "cache"','state_dir = "state"',
        'dist_dir = "dist"','mod_folder_name = "StrongholdEuropeDE"',"",
        "[policy]","private_local_only = true",
        "allow_game_archive_writes = false","allow_unknown_builds = false","",
    ]
    if isinstance(config.get("target",{}).get("runtime_reference_root"),str):
        at=lines.index("[output]")
        lines.insert(at,f"runtime_reference_root = {json.dumps(config['target']['runtime_reference_root'])}")
    data["aktiv"]=args.name
    candidate=("\n".join(lines)).encode("utf-8")
    registry=(json.dumps(data,indent=2,ensure_ascii=False)+"\n").encode("utf-8")
    try:
        atomic_save_bytes(CONFIG,candidate)
        atomic_save_bytes(ZIELE,registry)
    except OSError:
        # Transactional best effort: restore both old sidecars on any error.
        if old_config is None:
            CONFIG.unlink(missing_ok=True)
        else:atomic_save_bytes(CONFIG,old_config)
        if old_registry is None:
            ZIELE.unlink(missing_ok=True)
        else:atomic_save_bytes(ZIELE,old_registry)
        raise
    say(f"Verbindliches Ziel aktiviert: {args.name}; {att.build_id}; "
        f"5/5 Zielhashes und 5/5 SH1DE-Quellhashes; unknown builds gesperrt.")
    say("Keine Installation und kein Build gestartet.")
    return 0


def se_zip(explicit: str | None) -> Path:
    candidates = [Path(explicit)] if explicit else list(SE_ZIP_CANDIDATES)
    for candidate in candidates:
        if candidate.is_file():
            if sha256(candidate) != SE_ZIP_SHA256:
                raise SystemExit(
                    f"Script-Extender-Archiv hat falschen SHA-256: {candidate.name}")
            return candidate
    raise SystemExit("SHCDESE-2.11.0.zip nicht gefunden (extras/shcdese/ oder --zip angeben).")


def cmd_se_installieren(args) -> int:
    name, _ = resolve(args.name)
    try:game=safe_target(name)
    except TargetSelectionError as exc:raise SystemExit(str(exc)) from exc
    if game_running():
        raise SystemExit("Spiel läuft: SE-Installation vor Sicherung abgebrochen.")
    # Do not destroy a user's newer or unidentifiable Script Extender.
    # This is a historical, hash-pinned 2.11 installer, not a 2.14.x updater.
    previous = game / "BepInEx/plugins/000shcdese/SHCDESE.dll"
    if previous.is_symlink():
        raise SystemExit("Verlinkte Extender-DLL: Abbruch")
    if previous.exists():
        # Historic CLI only: preserve downgrade protection without importing
        # an interactive SE-version checker or requiring a particular version.
        old_version = file_version(previous)
        match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:\.0)?", old_version or "")
        old_parsed = tuple(map(int, match.groups())) if match else None
        if old_parsed is None:
            raise SystemExit("Vorhandene SE-DLL-Version konnte nicht geprüft werden")
        if old_parsed > (2, 11, 0):
            raise SystemExit(
                f"Vorhandener Script Extender {old_version} ist neuer als "
                "dieser historische 2.11-Installer. Keine Rückstufung."
            )
    # Historic 2.11 is not a compatible base for current APIShared >=0.9.2.
    # There is no independently pinned or game-tested SE 2.14.x upgrade
    # package in this tool. Never offer a misleading automatic downgrade.
    from community_mod_compat import load_json as load_compat_contract
    contract=load_compat_contract(PROJECT_ROOT/"config"/"shcde-community-compat-20261022.json")
    required=contract["plugin_contracts"]["api_shared_minimum_se"]
    from community_mod_compat import version as semver
    if semver("2.11.0") < semver(required):
        raise SystemExit(
            f"SE 2.11.0 ist für das angeforderte Community-Mod-Ökosystem zu alt "
            f"(APIShared benötigt >= {required}). Diese historische SE-Installation "
            "ist gesperrt; 2.14.x benötigt eigenen geprüften Build/ABI-/Hash-Nachweis.")
    archive_path = se_zip(args.zip)
    backup = make_backup(game, list(SE_PATHS), f"vor SE 2.11.0 aus {archive_path.name}")
    remove_paths(game, ["BepInEx/plugins/000shcdese"])
    with zipfile.ZipFile(archive_path) as archive:
        count = 0
        for member in archive.infolist():
            target = (game / member.filename).resolve()
            if not target.is_relative_to(game.resolve()):
                raise SystemExit("Unsicherer Dateipfad im SE-Archiv: Abbruch")
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target.open("wb") as out:
                shutil.copyfileobj(source, out)
            count += 1
    say(f"SE 2.11.0 in {game} installiert ({count} Dateien). Rueckweg: zurueckspielen {name} --sicherung {backup}")
    if not (game / "BepInEx" / "core" / "BepInEx.dll").is_file():
        say("WARNUNG: BepInEx fehlt in diesem Spiel - SE braucht eine vorhandene BepInEx-Installation.")
    return 0


def cmd_mod_installieren(args) -> int:
    name, _ = resolve(args.name)
    try:game=safe_target(name)
    except TargetSelectionError as exc:raise SystemExit(str(exc)) from exc
    source = Path(args.quelle)
    if not source.is_absolute():
        source = PROJECT_ROOT / source
    folder = args.ordner or source.name
    safe_component(folder)
    if not source.is_dir() or source.is_symlink():
        raise SystemExit("Ungültiger Modordner; Quelle muss existieren und normal sein")
    if game_running():
        raise SystemExit("Spiel läuft: Modinstallation abgebrochen.")
    # Never route the generic installer onto community-owned plugin folders.
    # SpriteSuite owns exactly StrongholdEuropeDE, not APIShared/SE/Fixes/etc.
    if folder.casefold() in FOREIGN_COMMUNITY_PLUGIN_FOLDERS:
        raise SystemExit(
            f"Zielordner {folder} gehört einem Fremdprojekt. "
            "Dessen offiziellen Installer verwenden; SpriteSuite überschreibt ihn nicht.")
    if folder.casefold()=="strongholdeuropede":
        from community_mod_compat import CompatibilityError, require_safe_to_install
        try:
            require_safe_to_install(game,source,project=PROJECT_ROOT)
        except CompatibilityError as exc:
            raise SystemExit(str(exc)) from exc
    relative = f"BepInEx/plugins/{folder}"
    backup = make_backup(game, [relative], f"vor Mod-Installation {folder} aus {source}")
    remove_paths(game, [relative])
    shutil.copytree(source, game / relative)
    say(f"{folder} installiert. Rueckweg: zurueckspielen {name} --sicherung {backup}")
    return 0


def cmd_mod_entfernen(args) -> int:
    name, _ = resolve(args.name)
    try:game=safe_target(name)
    except TargetSelectionError as exc:raise SystemExit(str(exc)) from exc
    safe_component(args.ordner)
    if args.ordner.casefold() in FOREIGN_COMMUNITY_PLUGIN_FOLDERS:
        raise SystemExit("Fremdprojekt geschützt: SpriteSuite darf " + args.ordner + " nicht entfernen.")
    if game_running():
        raise SystemExit("Spiel läuft: Entfernen abgebrochen.")
    relative = f"BepInEx/plugins/{args.ordner}"
    backup = make_backup(game, [relative], f"vor Entfernen von {args.ordner}")
    remove_paths(game, [relative])
    say(f"{args.ordner} entfernt. Rueckweg: zurueckspielen {name} --sicherung {backup}")
    return 0


def cmd_sicherungen(args) -> int:
    name, game = resolve(args.name)
    index = load_json(backup_root(game) / "sicherungen.json", {"eintraege": []})
    if args.json:
        print(json.dumps(index, ensure_ascii=False))
        return 0
    for entry in index["eintraege"]:
        say(f"{entry['id']}  {entry['zeit']}  {entry['grund']}  ({', '.join(entry['gesichert']) or 'leer'})")
    if not index["eintraege"]:
        say("keine Sicherungen")
    return 0


def cmd_zurueckspielen(args) -> int:
    name, _ = resolve(args.name)
    try:game=safe_target(name)
    except TargetSelectionError as exc:raise SystemExit(str(exc)) from exc
    index = load_json(backup_root(game) / "sicherungen.json", {"eintraege": []})
    entry = next((e for e in index["eintraege"] if e["id"] == args.sicherung), None)
    if entry is None:
        raise SystemExit(f"Sicherung {args.sicherung} nicht gefunden.")
    assert_safe_restore_paths(game,entry.get("pfade"))
    assert_safe_restore_paths(game,entry.get("gesichert"))
    if game_running():
        raise SystemExit("Spiel läuft: Wiederherstellung abgebrochen.")
    before = make_backup(game, entry["pfade"], f"vor Zurueckspielen von {entry['id']}")
    remove_paths(game, entry["pfade"])
    source_root = backup_root(game) / entry["id"]
    for relative in entry["gesichert"]:
        source = source_root / relative
        target = game / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
    say(f"Stand {entry['id']} zurueckgespielt. Der Stand davor liegt in Sicherung {before} (Weg zurueck).")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("liste", help="bekannte Zielspiele mit Spielstand, SE-Version und Europa-Mod")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_liste)
    p = sub.add_parser("hinzufuegen", help="Zielspiel eintragen")
    p.add_argument("--name", required=True)
    p.add_argument("--spiel", required=True)
    p.add_argument("--anzeige")
    p.set_defaults(func=cmd_hinzufuegen)
    p = sub.add_parser("aktivieren", help="Explizites, vollversionsgeprüftes SHCDE-Ziel wählen")
    p.add_argument("name")
    p.add_argument("--source-data", help="verifizierter SH1DE *_Data-Quellordner")
    p.set_defaults(func=cmd_aktivieren)
    p = sub.add_parser("se-installieren", help="SHCDE-SE 2.11.0 ins Zielspiel installieren (mit Sicherung)")
    p.add_argument("name")
    p.add_argument("--zip")
    p.set_defaults(func=cmd_se_installieren)
    p = sub.add_parser("mod-installieren", help="einen Modordner ins Zielspiel kopieren (mit Sicherung)")
    p.add_argument("name")
    p.add_argument("--quelle", required=True)
    p.add_argument("--ordner", help="Ordnername unter BepInEx/plugins (Standard: Name der Quelle)")
    p.set_defaults(func=cmd_mod_installieren)
    p = sub.add_parser("mod-entfernen", help="einen Modordner entfernen (mit Sicherung)")
    p.add_argument("name")
    p.add_argument("--ordner", required=True)
    p.set_defaults(func=cmd_mod_entfernen)
    p = sub.add_parser("sicherungen", help="Sicherungen eines Zielspiels")
    p.add_argument("name")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_sicherungen)
    p = sub.add_parser("zurueckspielen", help="eine Sicherung wieder einspielen (sichert vorher den aktuellen Stand)")
    p.add_argument("name")
    p.add_argument("--sicherung", required=True)
    p.set_defaults(func=cmd_zurueckspielen)
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())

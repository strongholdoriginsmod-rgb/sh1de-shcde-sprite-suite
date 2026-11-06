#!/usr/bin/env python3
"""Version-pinned, opt-in read-only SHCDE game damage/renderer probe.

Default mode compiles and tests an isolated DLL in a temporary directory.
--install-qa explicitly installs it ONLY into the marked isolated QA clone.
--remove-qa removes only that exact copy with its matching receipt.
No original Steam/game installation is modified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "runtime" / "StrongholdEuropeDE.BuildingDamage.LiveAudit" / "BuildingDamageLiveAudit.cs"
EXPECTED_MARKER = "SpriteSuite isolated Steam build 24816905 QA clone; originals are read-only."
SE_SHA = "5cb1c33be5463086505a17f5c48aaa357d733cfff7240e101c821f0e3c668498"
GAME_SHA = "bc8b6a395f01d48557db413600c8dd8d1fdfd3abdf97bfbbb68a3c56b04fd789"
PLUGIN_NAME = "SpriteSuiteBuildingDamageLiveAudit"
ASSEMBLY_NAME = "SpriteSuite.BuildingDamage.LiveAudit.dll"
RECEIPT_NAME = "sprite-suite-qa-receipt.json"
INFO_NAME = "info.json"
QA_SAVE_RELATIVE = Path("SpriteSuite_QA_Saves") / "SpriteSuite_Damage_Test.sav"
COMPILER = Path(r"C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe")

REFS = (
    "BepInEx/core/BepInEx.dll",
    "BepInEx/core/0Harmony.dll",
    "BepInEx/plugins/000shcdese/SHCDESE.dll",
    "Stronghold Crusader Definitive Edition_Data/Managed/Assembly-CSharp.dll",
    "Stronghold Crusader Definitive Edition_Data/Managed/UnityEngine.dll",
    "Stronghold Crusader Definitive Edition_Data/Managed/UnityEngine.CoreModule.dll",
    "Stronghold Crusader Definitive Edition_Data/Managed/Noesis.NoesisGUI.dll",
    "Stronghold Crusader Definitive Edition_Data/Managed/UnityEngine.TilemapModule.dll",
    "Stronghold Crusader Definitive Edition_Data/Managed/UnityEngine.GridModule.dll",
)


class QAFailure(ValueError):
    pass


def must(condition: bool, message: str) -> None:
    if not condition:
        raise QAFailure(message)


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_root(path: Path) -> tuple[Path, dict]:
    path = path.resolve(strict=True)
    must(path.is_dir() and not path.is_symlink(), "QA-Zielverzeichnis fehlt.")
    marker = path / ".sprite-suite-qa-copy.marker"
    must(marker.is_file() and marker.read_text(encoding="utf-8").strip() ==
         EXPECTED_MARKER, "Kein freigegebener, markierter QA-Klon – Abbruch.")
    files = {name: path / Path(name) for name in REFS}
    for name, source in files.items():
        must(source.is_file() and not source.is_symlink(),
             "QA-Vertragsdatei fehlt: " + name)
        must(source.resolve().is_relative_to(path),
             "QA-Referenz verlässt den geprüften Spielklon.")
    hashes = {"se": sha_file(files[REFS[2]]), "game": sha_file(files[REFS[3]])}
    must(hashes["se"] == SE_SHA and hashes["game"] == GAME_SHA,
         "QA-ABI-DLLs haben nicht die getesteten SHA-256-Werte.")
    return path, {"hashes": hashes, "files": files}


def validate_qa_save(qa: Path, save: Path) -> str:
    expected = qa / QA_SAVE_RELATIVE
    must(expected.is_file() and not expected.is_symlink(),
         "Die eindeutige QA-Spielstandkopie fehlt.")
    must(save.resolve(strict=True) == expected.resolve(strict=True),
         "Nur die ausdrücklich kopierte Datei im QA-Klon darf geladen werden.")
    must(50000 <= expected.stat().st_size <= 9_000_000,
         "QA-Spielstanddatei hat eine unerwartete Größe.")
    return sha_file(expected)


def compile_probe(qa: Path, details: dict, output: Path,
                  qa_save_sha: str | None = None,
                  qa_canary: bool = False) -> dict:
    must(COMPILER.is_file(), "C#-Framework-Compiler fehlt.")
    must(SRC.is_file(), "QA-Plugin-Quelle fehlt.")
    text = SRC.read_text(encoding="utf-8")
    must(text.count("__SE_SHA256__") == 1 and
         text.count("__GAME_SHA256__") == 1,
         "Unbekannte QA-Codevorlage.")
    text = text.replace("__SE_SHA256__", details["hashes"]["se"]).replace(
        "__GAME_SHA256__", details["hashes"]["game"])
    if qa_save_sha is not None:
        must(text.count("__QA_SAVE_SHA256__") == 1,
             "Unbekannte QA-Kartenlade-Vorlage.")
        text = text.replace("__QA_SAVE_SHA256__", qa_save_sha)
    source = output / "BuildingDamageLiveAudit.generated.cs"
    source.write_text(text, encoding="utf-8", newline="\n")
    dll = output / ASSEMBLY_NAME
    args = [str(COMPILER), "/nologo", "/target:library",
            "/out:" + str(dll)]
    if qa_save_sha is not None:
        args.append("/define:SHCDE_QA_AUTOMAP")
    if qa_canary:
        must(qa_save_sha is not None, "QA-Sprite-Kanarientest erfordert eine geprüfte Spielstandkopie.")
        args.append("/define:SHCDE_QA_SPRITE_CANARY")
    args += ["/r:" + str(details["files"][name]) for name in REFS]
    args.append(str(source))
    completed = subprocess.run(args, capture_output=True, text=True,
                               errors="replace", timeout=90, cwd=output,
                               check=False)
    if completed.returncode != 0:
        raise QAFailure("Compile-only Runtime-Abnahme fehlgeschlagen:\n" +
                        "\n".join((completed.stdout + completed.stderr).splitlines()[-20:]))
    must(dll.is_file() and dll.stat().st_size >= 4096,
         "Compiler hat keine gültige DLL geschrieben.")
    return {"dll": dll, "sha256": sha_file(dll), "size": dll.stat().st_size,
            "gameRoot": str(qa), "gameSha256": details["hashes"]["game"],
            "scriptExtenderSha256": details["hashes"]["se"],
            "qaCanary": bool(qa_canary)}


def install_qa(qa: Path, output: Path, result: dict) -> dict:
    destination = qa / "BepInEx" / "plugins" / PLUGIN_NAME
    must(not destination.exists(), "QA-Pluginverzeichnis existiert bereits; nichts überschreiben.")
    destination.mkdir(parents=False, exist_ok=False)
    try:
        dll_path = destination / ASSEMBLY_NAME
        with dll_path.open("xb") as handle:
            handle.write(result["dll"].read_bytes())
        canary = bool(result.get("qaCanary"))
        info = {
            "GUID": PLUGIN_NAME, "Author": "SpriteSuite QA",
            "Name": "Building Damage Single-Sprite QA Canary" if canary else "Building Damage Read-only Live QA",
            "Description": "ONE temporarily changed sprite in isolated QA clone with restoration" if canary else "Read-only evidence collection; no sprite, game, or renderer edits",
            "Version": "0.1.0", "SupportedGameVersions": ["2.8.0.2"],
            "Manifest": 1, "NetworkMode": 1
        }
        with (destination / INFO_NAME).open("x", encoding="utf-8") as handle:
            json.dump(info, handle, ensure_ascii=False, indent=2)
        receipt = {
            "format": "spritesuite-building-damage-qa-receipt",
            "version": 1, "readOnly": not canary,
            "rendererWrites": canary, "qaCanary": canary,
            "inGameTested": False, "dllSHA256": sha_file(dll_path),
            "infoSHA256": sha_file(destination / INFO_NAME),
            "gameSHA256": result["gameSha256"],
            "scriptExtenderSHA256": result["scriptExtenderSha256"]
        }
        with (destination / RECEIPT_NAME).open("x", encoding="utf-8") as handle:
            json.dump(receipt, handle, indent=2)
        return {"installedQA": True, "path": str(dll_path), "receipt": receipt}
    except Exception:
        if destination.is_dir():
            for filename in (ASSEMBLY_NAME, RECEIPT_NAME, INFO_NAME):
                (destination / filename).unlink(missing_ok=True)
            destination.rmdir()
        raise


def remove_qa(qa: Path) -> dict:
    destination = qa / "BepInEx" / "plugins" / PLUGIN_NAME
    receipt_file = destination / RECEIPT_NAME
    info = destination / INFO_NAME
    dll = destination / ASSEMBLY_NAME
    must(destination.is_dir() and not destination.is_symlink()
         and receipt_file.is_file() and dll.is_file(),
         "Keine von SpriteSuite dokumentierte QA-Installation vorhanden.")
    receipt = json.loads(receipt_file.read_text(encoding="utf-8"))
    # Old QA-only probe versions had no SHCDESE info.json. Allow exact,
    # hash-verified uninstall to clear that test installation safely.
    with_info = "infoSHA256" in receipt
    expected = {RECEIPT_NAME, ASSEMBLY_NAME}
    if with_info:
        expected.add(INFO_NAME)
    must({p.name for p in destination.iterdir()} == expected,
         "Unbekannte Dateien im QA-Pluginverzeichnis – keine Löschung.")
    trusted_mode = (receipt.get("readOnly") is True and
                    receipt.get("rendererWrites") is False) or (
                    receipt.get("qaCanary") is True and
                    receipt.get("readOnly") is False and
                    receipt.get("rendererWrites") is True)
    must(receipt.get("format") == "spritesuite-building-damage-qa-receipt" and
         trusted_mode and
         receipt.get("dllSHA256") == sha_file(dll) and
         (not with_info or receipt.get("infoSHA256") == sha_file(info)),
         "QA-Installation wurde seit der Abnahme verändert.")
    must(receipt.get("gameSHA256") == GAME_SHA and
         receipt.get("scriptExtenderSHA256") == SE_SHA,
         "QA-Original-ABI-Vertrag stimmt nicht mehr.")
    dll.unlink()
    if with_info:
        info.unlink()
    receipt_file.unlink()
    destination.rmdir()
    return {"removedQA": True, "path": str(destination)}


def evaluate_log(path: Path) -> dict:
    must(path.is_file() and path.stat().st_size < 64 * 1024 * 1024,
         "QA-Log fehlt oder ist zu groß.")
    raw = path.read_bytes()
    log_digest = hashlib.sha256(raw).hexdigest()
    events: list[dict[str, str]] = []
    for line in raw.decode("utf-8", errors="replace").splitlines():
        if "SHCDE_DAMAGE_QA|" not in line:
            continue
        payload = line.split("SHCDE_DAMAGE_QA|", 1)[1]
        fields: dict[str, str] = {}
        for pair in payload.split("|"):
            if "=" in pair:
                key, value = pair.split("=", 1)
                if key in fields:
                    raise QAFailure("Doppelte QA-Log-Eigenschaft: " + key)
                fields[key] = value.strip()
        if fields:
            events.append(fields)
    start = [e for e in events if e.get("event") == "start"]
    running = bool(start) and all(e.get("status") == "read_only" for e in start)
    canary_mode = bool(start) and all(e.get("status") == "qa_sprite_canary" for e in start)
    disabled = any(e.get("status") == "disabled" for e in start)
    shutdown = sum(e.get("event") == "shutdown" for e in events)
    heartbeats = [i for i, e in enumerate(events) if e.get("event") == "runner_heartbeat"]
    host_destroyed = [i for i, e in enumerate(events) if e.get("event") == "host_destroyed"]
    canary_applied = [e for e in events if e.get("event") == "qa_canary" and e.get("status") == "applied"]
    canary_restored = [e for e in events if e.get("event") == "qa_canary" and e.get("status") == "restored"]
    same_canary_tile = (len(canary_applied) == 1 and len(canary_restored) == 1 and
        all(canary_applied[0].get(key) and
            canary_applied[0].get(key) == canary_restored[0].get(key)
            for key in ("building_id", "global_id", "tile_id")))
    clean_canary_shutdown = any(
        e.get("event") == "shutdown" and e.get("status") == "unpatched"
        and e.get("sprite_writes") == "2" for e in events)
    tile_restored = (canary_mode and same_canary_tile and not disabled and
        not any(e.get("event") == "read_error" for e in events) and
        canary_restored[0].get("original_restored", "").lower() == "true" and
        canary_restored[0].get("writes") == "2")
    canary_verified = tile_restored and clean_canary_shutdown
    runner_survived_host = bool(host_destroyed and
        any(i > host_destroyed[0] for i in heartbeats))
    tiles = [e for e in events if e.get("event") == "tile_graphic"]
    footprints = [e for e in events if e.get("event") == "building_footprint"]
    failures = [e for e in events if e.get("event") == "read_error"]
    render_samples = [e for e in events if e.get("event") == "building_render_tiles"]
    render_with_pixels = [
        e for e in render_samples
        if e.get("building_id", "").isdigit()
        and e.get("global_id", "").isdigit()
        and e.get("assigned_sprites", "").isdigit()
        and int(e["assigned_sprites"]) > 0
        and e.get("renderer_modified") == "false"
    ]
    render_tilemap = [
        e for e in render_with_pixels
        if e.get("tilemap_sprites", "").isdigit()
        and int(e["tilemap_sprites"]) > 0
    ]
    # Correlate the SAME building global identity and a tile actually
    # listed in its footprint; counts alone never establish ownership.
    footprint_owners: dict[tuple[str, str], set[str]] = {}
    for entry in footprints:
        key = (entry.get("building_id", ""), entry.get("global_id", ""))
        if not all(key):
            continue
        ids: set[str] = set()
        for item in entry.get("tiles", "").split(";"):
            candidate = item.split(":", 1)[0]
            if candidate.isdigit():
                ids.add(candidate)
        footprint_owners.setdefault(key, set()).update(ids)
    correlated: set[tuple[str, str, str]] = set()
    for entry in tiles:
        key = (entry.get("building_id", ""), entry.get("global_id", ""))
        tile_id = entry.get("tile_id", "")
        if (tile_id in footprint_owners.get(key, set())
                and entry.get("renderer_modified") == "false"
                and entry.get("sprite") not in ("", "null", "none", None)):
            correlated.add((*key, tile_id))
    return {
        "sourceLogSHA256": log_digest,
        "readOnlyProbeStarted": running,
        "qaSpriteCanaryStarted": canary_mode,
        "qaCanaryApplications": len(canary_applied),
        "qaCanaryRestorations": len(canary_restored),
        "qaCanaryTileRestoredVerified": tile_restored,
        "qaCanaryCleanShutdownVerified": clean_canary_shutdown,
        "qaCanaryRebindAndRestoreVerified": canary_verified,
        "probeDisabled": disabled,
        "shutdownEvents": shutdown,
        "runnerHeartbeatCount": len(heartbeats),
        "hostDestroyedCount": len(host_destroyed),
        "runnerSurvivedHost": runner_survived_host,
        "tileGraphicObservations": len(tiles),
        "buildingFootprintObservations": len(footprints),
        "buildingRendererTileSamples": len(render_samples),
        "buildingSamplesWithAssignedSprite": len(render_with_pixels),
        "buildingSamplesWithTilemapSprite": len(render_tilemap),
        "directlySampledBuildingTypes": sorted({
            entry["type"] for entry in render_with_pixels if entry.get("type", "").isdigit()
        }, key=int),
        "readErrors": len(failures),
        "correlatedTiles": len(correlated),
        "correlatedBuildingIdentities": len({(b, g) for b, g, _ in correlated}),
        "liveTileFootprintCorrelationObserved": running and not disabled and bool(correlated),
        "liveGraphicMappingProved": False, # Only read-only evidence; game rendering not modified.
        "rendererReplacementProved": False,
        "inGameFullDamageSwitchingProved": False
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qa-root", required=True, type=Path)
    parser.add_argument("--expected-log-sha256",
                        help="Bei --verify-log: SHA-256 des unveränderten Spielprotokolls")
    parser.add_argument("--qa-canary", action="store_true",
                        help="Nur mit --qa-save: eine Grafik-Kachel kurz ändern und durch die Engine wiederherstellen")
    parser.add_argument("--qa-save", type=Path,
                        help="Nur explizite Testkopie SpriteSuite_QA_Saves/SpriteSuite_Damage_Test.sav; "
                             "lädt eine Spielkarte im isolierten QA-Klon, ohne Original-Save zu überschreiben")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--build-only", action="store_true")
    mode.add_argument("--install-qa", action="store_true")
    mode.add_argument("--remove-qa", action="store_true")
    mode.add_argument("--verify-log", type=Path)
    args = parser.parse_args(argv)
    try:
        qa, details = verify_root(args.qa_root)
        if args.qa_save is not None and not (args.build_only or args.install_qa):
            raise QAFailure("--qa-save ist nur für --build-only oder --install-qa zulässig.")
        save_sha = validate_qa_save(qa, args.qa_save) if args.qa_save else None
        if args.qa_canary:
            must(bool(save_sha) and (args.build_only or args.install_qa),
                 "--qa-canary benötigt --qa-save sowie --build-only/--install-qa.")
        if args.remove_qa:
            output = remove_qa(qa)
        elif args.verify_log:
            output = evaluate_log(args.verify_log)
            if args.expected_log_sha256:
                must(len(args.expected_log_sha256) == 64 and
                     all(ch in "0123456789abcdefABCDEF" for ch in args.expected_log_sha256) and
                     args.expected_log_sha256.lower() == output["sourceLogSHA256"],
                     "QA-Log SHA-256 entspricht nicht der angegebenen Beweissicherung.")
        else:
            must(args.expected_log_sha256 is None,
                 "--expected-log-sha256 ist nur mit --verify-log zulässig.")
            with tempfile.TemporaryDirectory(prefix="spritesuite_shcde_damage_qa_") as dirname:
                build = compile_probe(qa, details, Path(dirname), save_sha, args.qa_canary)
                if save_sha:
                    build["qaSaveSHA256"] = save_sha
                output = {k: v for k, v in build.items() if k != "dll"}
                output["compiled"] = True
                output["gameModified"] = False
                output["runtimeHookInstalled"] = False
                if args.install_qa:
                    output.update(install_qa(qa, Path(dirname), build))
                    output["gameModified"] = True
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0
    except (OSError, QAFailure, ValueError, json.JSONDecodeError,
            subprocess.TimeoutExpired) as exc:
        print("QA abgebrochen: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

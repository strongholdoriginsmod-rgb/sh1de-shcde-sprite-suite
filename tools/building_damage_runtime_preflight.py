#!/usr/bin/env python3
"""Offline, non-installing preflight for SpriteSuite SHCDE building-damage libraries.

Reads the explicit damage-manifest.json and its PNGs from an export ZIP.
Checks version, thresholds, bounds, SHA-256, paths and masks, then writes a
separate, read-only *candidate* index. This tool does not alter game files and
does not claim renderer compatibility.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import sys
import zipfile
import zlib

FORMAT = "stronghold-building-damage-library"
CANDIDATE_FORMAT = "stronghold-building-damage-runtime-preflight"
TABLE_SCHEMA = "stronghold-building-damage-runtime-table-v1"
MAX_BYTES = 192 * 1024 * 1024
MAX_UNPACKED = 192 * 1024 * 1024
MAX_ENTRIES = 12288
MAX_PROFILES = 128
MAX_STAGES = 32
MAX_TILES = 4096
IDENT = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
HEX64 = re.compile(r"^[a-f0-9]{64}$")
PATH = re.compile(r"^damage/[A-Za-z0-9_-]{1,80}/(?:mechanical|fire)/(?:0|[1-9][0-9]?)/[0-9]{4}(?:_m)?\.png$")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class PreflightError(ValueError):
    pass


def must(condition: bool, message: str) -> None:
    if not condition:
        raise PreflightError(message)


def ident(value: object, label: str) -> str:
    must(isinstance(value, str) and IDENT.fullmatch(value) is not None,
         label + ": ungültige interne ID.")
    return value


def exact_int(value: object, minimum: int, maximum: int, label: str) -> int:
    must(type(value) is int and minimum <= value <= maximum,
         f"{label}: Zahl außerhalb {minimum}..{maximum}.")
    return value


def digest(value: object, label: str) -> str:
    must(isinstance(value, str) and HEX64.fullmatch(value) is not None,
         label + ": ungültige SHA-256-Prüfsumme.")
    return value


def png_dimensions(raw: bytes) -> tuple[int, int]:
    """Validate *every* PNG chunk, bounded IDAT stream and scanline filters.

    A correct IHDR and a matching manifest SHA alone do not prove that the
    export contains a decodable PNG. SpriteSuite emits IHDR/IDAT/IEND RGBA8
    with no ancillary chunks; unfamiliar variants fail closed.
    """
    must(len(raw) >= 45 and raw.startswith(PNG_SIGNATURE), "Ungültiges PNG.")
    pos = len(PNG_SIGNATURE)
    width = height = None
    chunks: list[bytes] = []
    saw_idat = saw_end = False
    while pos < len(raw):
        must(pos + 12 <= len(raw), "Abgeschnittenes PNG-Chunksystem.")
        count = struct.unpack_from(">I", raw, pos)[0]
        must(count <= MAX_UNPACKED and count <= len(raw) - pos - 12,
             "PNG-Chunk ist unzulässig groß oder abgeschnitten.")
        kind = raw[pos + 4:pos + 8]
        payload = raw[pos + 8:pos + 8 + count]
        expected_crc = struct.unpack_from(">I", raw, pos + 8 + count)[0]
        must(zlib.crc32(raw[pos + 4:pos + 8 + count]) & 0xffffffff ==
             expected_crc, "PNG-Chunk-CRC fehlerhaft.")
        if kind == b"IHDR":
            must(pos == 8 and count == 13 and width is None,
                 "PNG-IHDR ist ungültig oder mehrfach vorhanden.")
            width, height, depth, color, compression, filter_method, interlace = (
                struct.unpack(">IIBBBBB", payload))
            must(1 <= width <= 16384 and 1 <= height <= 16384 and
                 width * height <= 16777216, "PNG überschreitet Bildbudget.")
            must((depth, color, compression, filter_method, interlace) ==
                 (8, 6, 0, 0, 0),
                 "Die Runtime-Bibliothek benötigt ein nichtinterlaced RGBA8-PNG.")
        elif kind == b"IDAT":
            must(width is not None and not saw_end, "PNG-IDAT ohne IHDR.")
            chunks.append(payload)
            saw_idat = True
        elif kind == b"IEND":
            must(saw_idat and count == 0 and
                 pos + 12 == len(raw), "PNG-Endmarker ist ungültig.")
            saw_end = True
        else:
            raise PreflightError("Unbekannter PNG-Chunk; nur SpriteSuite-RGBA8 zulässig.")
        pos += count + 12
    must(saw_end and chunks, "PNG enthält keine vollständigen IDAT-Daten.")
    # zlib's max_length prevents an adversarial compressed IDAT from
    # expanding beyond the exact expected RGBA8 raster.
    row_length = width * 4 + 1
    exact = row_length * height
    try:
        inflater = zlib.decompressobj()
        pixels = inflater.decompress(b"".join(chunks), exact + 1)
    except zlib.error as exc:
        raise PreflightError("PNG-IDAT kann nicht dekomprimiert werden.") from exc
    must(len(pixels) == exact and inflater.eof and
         not inflater.unconsumed_tail and not inflater.unused_data,
         "PNG-IDAT hat unvollständige oder überschüssige Bilddaten.")
    for start in range(0, exact, row_length):
        must(pixels[start] <= 4, "Ungültiger PNG-Zeilenfilter.")
    return width, height


def archive_map(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    info = archive.infolist()
    must(0 < len(info) <= MAX_ENTRIES, "Unzulässige Zahl ZIP-Dateien.")
    must(sum(row.file_size for row in info) <= MAX_UNPACKED,
         "ZIP überschreitet entpacktes Datenbudget.")
    names = {}
    seen_folded = set()
    for row in info:
        name = row.filename
        must(name.casefold() not in seen_folded, "ZIP-Dateiname ist ohne Groß-/Kleinschreibung doppelt.")
        seen_folded.add(name.casefold())
        must(row.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED) and
             not (row.flag_bits & 1), "ZIP benötigt Store/Deflate ohne Verschlüsselung.")
        must(name not in names and not row.is_dir() and
             (row.external_attr >> 16) & 0o170000 != 0o120000,
             "ZIP enthält doppelte Dateien, Ordner oder symbolische Links.")
        must(name and not name.startswith("/") and
             "\\" not in name and ":" not in name and
             all(part not in ("", ".", "..") for part in name.split("/")),
             "Unsicherer ZIP-Dateiname.")
        must(name in ("damage-manifest.json", "README.txt") or PATH.fullmatch(name),
             "Unbekanntes Dateiformat oder unsicherer Pfad: " + name[:80])
        names[name] = row
    must("damage-manifest.json" in names, "Schadensmanifest fehlt.")
    return names


def strict_pairs(pairs):
    obj = {}
    for name, value in pairs:
        must(name not in obj, "Doppelte JSON-Eigenschaft: " + name[:60])
        obj[name] = value
    return obj


def reject_nonfinite(value):
    raise PreflightError("Nicht-endlicher numerischer JSON-Wert: " + value)


def require_keys(obj: object, fields: tuple[str, ...], label: str) -> dict:
    must(isinstance(obj, dict), label + " muss ein JSON-Objekt sein.")
    for field in fields:
        must(field in obj, label + " benötigt " + field)
    return obj


def read_library(package: Path) -> dict:
    must(package.is_file() and not package.is_symlink(), "Exportarchiv fehlt.")
    must(package.stat().st_size <= MAX_BYTES, "Exportarchiv überschreitet 192 MiB.")
    zip_hash = hashlib.sha256(package.read_bytes()).hexdigest()
    with zipfile.ZipFile(package, "r") as archive:
        names = archive_map(archive)
        raw_manifest = archive.read("damage-manifest.json")
        must(len(raw_manifest) < 2_000_000, "Manifest ist zu groß.")
        manifest = json.loads(raw_manifest.decode("utf-8"),
                              object_pairs_hook=strict_pairs,
                              parse_constant=reject_nonfinite)
        require_keys(manifest, ("format", "version", "target", "runtimeHookInstalled",
                                "hpUnit", "buildings"), "Schadensmanifest")
        must(manifest["format"] == FORMAT and type(manifest["version"]) is int
             and manifest["version"] == 1, "Unbekannte Schadensbibliothek.")
        must(manifest["target"] == "Stronghold Crusader: Definitive Edition",
             "Falsches Zielspiel.")
        must(manifest["runtimeHookInstalled"] is False and
             manifest["hpUnit"] == "percent_of_maximum_hp",
             "Export darf keine ungeprüfte Runtime-Installation behaupten.")
        buildings = manifest["buildings"]
        must(isinstance(buildings, list) and 1 <= len(buildings) <= MAX_PROFILES,
             "Ungültige Gebäudeanzahl.")
        used_names, used_types, referenced, validated = set(), set(), set(), []
        unmapped, unbound = [], []
        for raw in buildings:
            group = require_keys(raw, ("id", "name", "intactScene", "stages"),
                                 "Gebäude")
            group_id = ident(group["id"], "Originalgebäude")
            ident(group["intactScene"], "Originalszene")
            must(group_id not in used_names, "Doppelte Gebäudegruppen.")
            used_names.add(group_id)
            building_name = group["name"]
            must(isinstance(building_name, str) and 0 < len(building_name) <= 240,
                 "Ungültiger Gebäudename.")
            game_type = group.get("gameBuildingType")
            if game_type is not None:
                exact_int(game_type, 0, 4095, "Gebäudetyp im Spiel")
                must(game_type not in used_types,
                     "Spiel-Gebäudetyp mehrfach zugewiesen.")
                used_types.add(game_type)
            else:
                unmapped.append(group_id)
            must(group.get("gameBuildingTypeVerifiedInGame") is False,
                 "Spielprüfung ist nicht durch Export als abgeschlossen belegbar.")
            stages = group["stages"]
            must(isinstance(stages, list) and 1 <= len(stages) <= MAX_STAGES,
                 "Ungültige Zahl Schadensstufen.")
            step_keys, stage_names, sorted_stages = set(), set(), []
            for item in stages:
                stage = require_keys(item, ("id", "damageKind", "hpAtOrBelow",
                                            "scene", "settings", "tiles"), "Stufe")
                stage_id = ident(stage["id"], "Stufen-ID")
                scene_id = ident(stage["scene"], "Stufenszene")
                kind = stage["damageKind"]
                must(kind in ("mechanical", "fire"), "Unbekannte Schadensursache.")
                hp = exact_int(stage["hpAtOrBelow"], 0, 99, "HP-Schwelle")
                approval = stage.get("approvalDigest")
                if approval is not None:
                    digest(approval, "Freigabe-Zustandsprüfsumme")
                else:
                    unbound.append(f"{group_id}:{stage_id}")
                must((kind, hp) not in step_keys and stage_id not in stage_names,
                     "Doppelte HP-Schwelle oder Stufen-ID.")
                step_keys.add((kind, hp))
                stage_names.add(stage_id)
                settings = require_keys(stage["settings"],
                    ("a", "b", "width", "height", "anchor", "order"), "Tile-Einstellungen")
                a = exact_int(settings["a"], 1, 64, "Raster links")
                b = exact_int(settings["b"], 1, 64, "Raster rechts")
                width = exact_int(settings["width"], 2, 64, "Tile-Breite")
                height = exact_int(settings["height"], 2, 2048, "Rautenhöhe")
                must(width % 2 == height % 2 == 0 and
                     settings["anchor"] in ("bottom", "pivot") and
                     settings["order"] in ("ascending", "descending"),
                     "Ungültiges iso-Raster.")
                tiles = stage["tiles"]
                must(isinstance(tiles, list) and 1 <= len(tiles) <= min(MAX_TILES, a * b),
                     "Ungültige Zahl Stufentiles.")
                slots, tile_report = set(), []
                for tile in tiles:
                    row = require_keys(tile, ("slot", "image", "sha256", "dx", "dy",
                                              "pivot", "ppu"), "Tile")
                    slot = exact_int(row["slot"], 0, a * b - 1, "Rasterplatz")
                    must(slot not in slots, "Tile-Rasterplatz doppelt.")
                    slots.add(slot)
                    image_name = row["image"]
                    expected = f"damage/{group_id}/{kind}/{hp}/{slot:04d}.png"
                    must(image_name == expected, "Tile-Dateipfad stimmt nicht zur Stufe.")
                    must(image_name in names and image_name not in referenced,
                         "Tile fehlt oder wird mehrfach verwendet.")
                    raw_png = archive.read(image_name)
                    raw_hash = hashlib.sha256(raw_png).hexdigest()
                    must(raw_hash == digest(row["sha256"], "Tile-Prüfsumme"),
                         "Tile-SHA-256 stimmt nicht: " + image_name)
                    iw, ih = png_dimensions(raw_png)
                    must(iw <= width and iw <= 64 and ih <= 16384,
                         "Tile überschreitet 64 Pixel oder vorgegebenes Raster.")
                    referenced.add(image_name)
                    exact_int(row["dx"], -16384, 16384, "Tile-Versatz X")
                    exact_int(row["dy"], -16384, 16384, "Tile-Versatz Y")
                    pivot = require_keys(row["pivot"], ("x", "y"), "Pivot")
                    must(all(type(pivot[axis]) in (int, float) and
                             0 <= pivot[axis] <= 1 for axis in ("x", "y")),
                         "Ungültiger Pivot.")
                    must(type(row["ppu"]) in (float, int) and
                         0 < row["ppu"] <= 65536, "Ungültiger PPU-Wert.")
                    if "mask" in row:
                        mask_name = expected.replace(".png", "_m.png")
                        must(row["mask"] == mask_name and mask_name in names and
                             mask_name not in referenced, "Unzulässige Tile-Maske.")
                        raw_mask = archive.read(mask_name)
                        must(png_dimensions(raw_mask) == (iw, ih),
                             "Materialmaske hat eine andere Größe als das Tile.")
                        if "maskSha256" not in row:
                            raise PreflightError(
                                "Maske ohne SHA-256. Bitte mit aktueller SpriteSuite neu exportieren.")
                        must(hashlib.sha256(raw_mask).hexdigest() ==
                             digest(row["maskSha256"], "Materialmasken-Hash"),
                             "Materialmaske SHA-256 stimmt nicht.")
                        referenced.add(mask_name)
                    tile_report.append({"slot": slot, "image": image_name,
                                        "width": iw, "height": ih})
                sorted_stages.append({
                    "id": stage_id, "sceneId": scene_id, "damageKind": kind,
                    "hpAtOrBelow": hp, "approvalDigest": approval,
                    "tiles": sorted(tile_report, key=lambda t: t["slot"])
                })
            sorted_stages.sort(key=lambda row: (
                0 if row["damageKind"] == "mechanical" else 1, -row["hpAtOrBelow"]))
            validated.append({"buildingGroupId": group_id,
                              "name": building_name, "gameBuildingType": game_type,
                              "stages": sorted_stages})
        unexpected = set(names) - referenced - {"damage-manifest.json", "README.txt"}
        must(not unexpected, "Paket enthält unreferenzierte Tile-/Maskendateien.")
    return {
        "format": CANDIDATE_FORMAT, "version": 1,
        "packageSHA256": zip_hash, "game": manifest["target"],
        "profiles": sorted(validated, key=lambda b:
                           (b["gameBuildingType"] is None,
                            b["gameBuildingType"] or -1, b["buildingGroupId"])),
        "unmappedBuildingGroups": sorted(unmapped),
        "unboundApprovedStages": sorted(unbound),
        "mappedTypes": sorted(used_types),
        "readOnly": True, "runtimeHookInstalled": False,
        "rendererMappingValidated": False,
        "inGameTested": False,
        "note": "HP and art data only. No sprite renderer registration, event subscriptions or native writes."
    }


def table_lines(report: dict) -> list[str]:
    lines = [f"# {TABLE_SCHEMA}",
             "# Generated from SHA-verified damage library; not an active game mod",
             "# package-sha256 " + report["packageSHA256"],
             "building_type\tbuilding_group\tdamage_kind\thp_le\tstage_id\tscene_id"]
    for profile in report["profiles"]:
        game_type = profile["gameBuildingType"]
        if game_type is None:
            continue
        for stage in profile["stages"]:
            lines.append("\t".join((str(game_type), profile["buildingGroupId"],
                                    stage["damageKind"], str(stage["hpAtOrBelow"]),
                                    stage["id"], stage["sceneId"])))
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--expected-sha256", help="Optional erwarteter SHA-256 des ZIPs")
    parser.add_argument("--output", type=Path, help="Neuer Ordner für read-only Testplan")
    parser.add_argument("--require-bound-approval", action="store_true",
                        help="Optional: nur Pakete mit gebundenen Abnahmen vorbereiten")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--prepare", action="store_true", help="Generierte Referenzdaten in einen neuen Ordner schreiben")
    mode.add_argument("--dry-run", action="store_true", help="Nur das ZIP ohne Schreibzugriffe prüfen (Standard)")
    args = parser.parse_args(argv)
    try:
        report = read_library(args.package)
        if args.expected_sha256:
            must(report["packageSHA256"] == digest(args.expected_sha256,
                "Erwartete SHA-256"), "Paket hat nicht die freigegebene Prüfsumme.")
        report["tableLines"] = len(table_lines(report)) - 4
        report["prepared"] = bool(args.prepare)
        if args.prepare:
            if args.require_bound_approval:
                must(not report["unboundApprovedStages"],
                     "Der gewählte Prüfmodus verlangt gebundene Abnahmen für alle Stufen.")
            must(args.output is not None, "--prepare benötigt --output.")
            must(not args.output.exists(), "Ausgabeordner existiert bereits.")
            args.output.mkdir(parents=True, exist_ok=False)
            # Exclusive writes; never alter a previously generated preview.
            with (args.output / "building-damage-candidate.tsv").open(
                    "x", encoding="utf-8", newline="\n") as handle:
                handle.write("\n".join(table_lines(report)) + "\n")
            with (args.output / "building-damage-preflight.json").open(
                    "x", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(report, ensure_ascii=False,
                                        sort_keys=True, indent=2) + "\n")
        print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    except (PreflightError, ValueError, KeyError, OSError, UnicodeError,
            zipfile.BadZipFile, json.JSONDecodeError) as error:
        print("Preflight: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

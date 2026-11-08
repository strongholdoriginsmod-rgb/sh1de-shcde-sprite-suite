#!/usr/bin/env python3
"""Validate SpriteSuite image briefs and generate candidates with local Codex.

The default validates offline. --execute uses the managed ChatGPT session.
Original images, raw model output and source-bound review receipts remain separate.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import zipfile

from building_damage_codex import (
    normalize_model_output, png_dimensions,
)
from sprite_codex_session import session

FORMAT = "sprite-suite.ai-image-edit"
MODELS = {"gpt-image-2.6-sunburst", "gpt-image-2.6-flare"}
CLASSES = {"building", "unit", "animation", "texture", "vegetation", "hud", "ui", "other"}
NAMES = {"request.json", "reference.png", "model_reference.png", "WORKFLOW.txt"}
MAX_BUNDLE = 64 * 1024 * 1024
MAX_EXPANDED = 128 * 1024 * 1024
MAX_RESULT = 48 * 1024 * 1024


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_request(bundle: Path | io.BytesIO) -> tuple[dict, list[tuple[str, bytes]]]:
    if isinstance(bundle, Path):
        if (not bundle.is_file() or bundle.is_symlink()
                or bundle.stat().st_size > MAX_BUNDLE):
            raise ValueError("Anfrage-ZIP fehlt, ist verlinkt oder überschreitet Dateibudget.")
    elif not isinstance(bundle, io.BytesIO) or bundle.getbuffer().nbytes > MAX_BUNDLE:
        raise ValueError("Anfrage-ZIP überschreitet Dateibudget.")
    with zipfile.ZipFile(bundle) as archive:
        files = archive.infolist()
        if (len(files) != 4 or {item.filename for item in files} != NAMES
                or len({item.filename for item in files}) != 4
                or sum(item.file_size for item in files) > MAX_EXPANDED):
            raise ValueError("Unerwarteter ZIP-Inhalt oder Größe.")
        if any(item.is_dir() or (item.external_attr >> 16) & 0o170000 == stat.S_IFLNK
               for item in files):
            raise ValueError("Verlinkte ZIP-Einträge werden abgewiesen.")
        request_bytes = archive.read("request.json")
        request = json.loads(request_bytes)
        original = archive.read("reference.png")
        registered = archive.read("model_reference.png")
    if not isinstance(request, dict):
        raise ValueError("Anfrage ist kein JSON-Objekt.")
    if request.get("provider") not in {None, "codex-chatgpt"}:
        raise ValueError("Anfrage benötigt den lokalen ChatGPT-/Codex-Client.")
    if request.get("format") != FORMAT or request.get("version") != 1:
        raise ValueError("Unbekanntes SpriteSuite-KI-Anfrageformat.")
    if request.get("model") not in MODELS or request.get("assetClass") not in CLASSES:
        raise ValueError("Nicht freigegebenes Bildmodell oder Assetformat.")
    variants = request.get("variants")
    if type(variants) is not int or not 1 <= variants <= 4:
        raise ValueError("Variantenanzahl muss 1 bis 4 betragen.")
    if (request.get("quality") != "high" or
            request.get("complexity") != "high" or
            request.get("background") != "transparent" or
            request.get("output_format") != "png" or
            request.get("requiresManualApproval") is not True or
            request.get("automaticInstallation") is not False):
        raise ValueError("Anfrage verletzt die kontrollierte Ausgabe.")
    goal = request.get("goal")
    prompt = request.get("prompt")
    if (not isinstance(goal, str) or len(goal.strip()) < 8 or len(goal) > 4000
            or not isinstance(prompt, str) or not 40 <= len(prompt) <= 32000):
        raise ValueError("Unzulässige Zielbeschreibung oder Promptlänge.")
    if request.get("referenceFiles") != ["model_reference.png"]:
        raise ValueError("Referenz muss die registrierte Vorlagendatei sein.")
    plan = request.get("registration")
    keys = ("width", "height", "scale", "left", "top", "sourceWidth", "sourceHeight")
    if (not isinstance(plan, dict)
            or any(type(plan.get(key)) is not int for key in keys)):
        raise ValueError("Registrierung ist unvollständig oder nicht ganzzahlig.")
    w, h, scale, left, top, sw, sh = (plan[key] for key in keys)
    if ((w, h) not in {(1024, 1024), (1536, 1024), (1024, 1536)}
            or scale < 1 or sw < 1 or sh < 1 or
            left < 0 or top < 0 or left + sw * scale > w or top + sh * scale > h
            or request.get("size") != f"{w}x{h}"
            or request.get("referenceWidth") != sw
            or request.get("referenceHeight") != sh):
        raise ValueError("Registrierung oder Ausgabemaße sind inkonsistent.")
    if (png_dimensions(original) != (sw, sh)
            or png_dimensions(registered) != (w, h)
            or request.get("referenceSHA256") != _sha(original)
            or request.get("modelReferenceSHA256") != _sha(registered)):
        raise ValueError("Original- oder Modellreferenz ist nicht SHA-verifiziert.")
    if "input_fidelity" in request:
        raise ValueError("GPT Image 2.6 unterstützt input_fidelity nicht.")
    request["_request_sha256"] = _sha(request_bytes)
    return request, [("model_reference.png", registered)]


def _safe_output(output: Path) -> Path:
    absolute = output.expanduser().absolute().resolve(strict=False)
    # Canonicalize parent junctions first. Never write into a game or BepInEx tree.
    for part in absolute.parts:
        item = part.casefold()
        if ("stronghold crusader definitive edition" in item or
                "stronghold 1 definitive edition" in item or
                item in {"bepinex", "000shcdese"}):
            raise ValueError("Ausgabe innerhalb eines Spielverzeichnisses verboten.")
    for parent in list(absolute.parents)[:10]:
        if ((parent / "UnityPlayer.dll").is_file() and
                any((parent / name).is_file() for name in (
                    "Stronghold Crusader Definitive Edition.exe",
                    "Stronghold 1 Definitive Edition.exe"))):
            raise ValueError("Ausgabe unter einer Spielinstallation ist verboten.")
    if output.is_symlink() or (absolute.exists() and (not absolute.is_dir() or any(absolute.iterdir()))):
        raise ValueError("Kandidatenordner muss neu oder leer sein; vorhandene Ergebnisse schützen.")
    return absolute


def _generate_one(request: dict, images: list[tuple[str, bytes]]) -> tuple[bytes, str | None]:
    with tempfile.TemporaryDirectory(prefix="spritesuite-workshop-") as folder:
        cwd = Path(folder)
        with session(cwd) as codex:
            raw, generation_id = codex.generate(cwd, request, images)
    if len(raw) > MAX_RESULT:
        raise ValueError("Kandidaten-PNG überschreitet Größenbudget.")
    png_dimensions(raw)
    return raw, generation_id


def _write_status(target: Path, info: dict) -> None:
    """Atomic local progress receipt; a killed worker is never certified as done."""
    tmp = target / ".run-status.tmp"
    with tmp.open("x", encoding="utf-8") as file:
        json.dump(info, file, indent=2, ensure_ascii=False)
        file.write("\n")
        file.flush()
        os.fsync(file.fileno())
    os.replace(tmp, target / "run-status.json")


def execute(request: dict, images: list[tuple[str, bytes]], output: Path) -> dict:
    from PIL import Image  # noqa: F401 -- required for deterministic inverse registration
    target = _safe_output(output)
    try:
        target.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise ValueError("Ausgabeordner existiert bereits; neuen Kandidatenordner wählen.") from exc
    rows = []
    candidate_count = 0
    status = {"schema": "sprite-suite.ai-execution.v1",
              "requestSHA256": request["_request_sha256"],
              "expectedVariants": request["variants"],
              "completedVariants": 0, "status": "running",
              "needsManualReview": True, "installed": False}
    _write_status(target, status)
    try:
        for index in range(1, request["variants"] + 1):
            raw, request_id = _generate_one(request, images)
            fitted, alignment = normalize_model_output(raw, request)
            prefix = f"variant_{index:02d}"
            with (target / (prefix + "_model_raw.png")).open("xb") as file:
                file.write(raw)
            if fitted:
                with (target / (prefix + ".png")).open("xb") as file:
                    file.write(fitted)
            meta = {
                "format": "sprite-suite.ai-candidate",
                "version": 1, "variant": index,
                "assetClass": request["assetClass"], "model": request["model"],
                "requestSHA256": request["_request_sha256"],
                "referenceSHA256": request["referenceSHA256"],
                "modelOutputSHA256": _sha(raw),
                "candidateSHA256": _sha(fitted) if fitted else None,
                "provider": "codex-chatgpt", "generationId": request_id,
                "registration": alignment,
                "needsManualReview": True,
                "inGameTested": False, "originalGameModified": False
            }
            with (target / (prefix + "_meta.json")).open("x", encoding="utf-8") as file:
                json.dump(meta, file, ensure_ascii=False, indent=2)
            rows.append(meta)
            candidate_count += int(fitted is not None)
            status["completedVariants"] = index
            status["status"] = "running"
            _write_status(target, status)
    except (ValueError, OSError, RuntimeError, TypeError, KeyError) as exc:
        status["status"] = "partial_failure"
        status["errorType"] = type(exc).__name__
        _write_status(target, status)
        raise
    status["status"] = ("candidates_ready_for_review" if candidate_count == request["variants"]
                        else "alignment_review_required")
    status["normalizedCandidates"] = candidate_count
    _write_status(target, status)
    return {"generated": len(rows), "normalizedCandidates": candidate_count,
            "candidates": rows, "output": str(target),
            "requestSHA256": request["_request_sha256"],
            "needsManualReview": True, "installed": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Default: validate only, no network")
    mode.add_argument("--execute", action="store_true", help="Generate candidates with the local ChatGPT/Codex session")
    args = parser.parse_args(argv)
    try:
        request, images = load_request(args.bundle)
        _safe_output(args.output)
        if args.execute:
            result = execute(request, images, args.output)
        else:
            result = {
                "dryRun": True, "model": request["model"],
                "assetClass": request["assetClass"],
                "variants": request["variants"],
                "sourceSHA256": request["referenceSHA256"],
                "requestSHA256": request["_request_sha256"],
                "output": str(args.output),
                "provider": "codex-chatgpt", "networkRequest": False,
                "requiresExecute": True,
                "needsManualReview": True, "gameFilesModified": False
            }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError, ImportError,
            zipfile.BadZipFile, json.JSONDecodeError) as exc:
        print("KI-WERKSTATT: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

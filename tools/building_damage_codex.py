#!/usr/bin/env python3
"""Validate and execute SpriteSuite image jobs through Codex with ChatGPT sign-in."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import struct
import sys
import zipfile
import tempfile

from sprite_codex_session import session

MODELS = {"gpt-image-2.6-sunburst", "gpt-image-2.6-flare"}
SOURCE_NAMES = ("reference.png", "previous.png", "candidate.png", "model_reference.png", "model_previous.png", "model_candidate.png")
MAX_ZIP_BYTES = 30 * 1024 * 1024
MAX_PNG_BYTES = 48 * 1024 * 1024


def png_dimensions(data: bytes) -> tuple[int, int]:
    if (len(data) < 33 or data[:8] != b"\x89PNG\r\n\x1a\n"
            or data[12:16] != b"IHDR"):
        raise ValueError("Ungültiges PNG.")
    w, h = struct.unpack(">II", data[16:24])
    if w < 1 or h < 1 or w > 16384 or h > 16384 or w * h > 16777216:
        raise ValueError("PNG überschreitet das 16-Megapixel-Budget.")
    return w, h


def load_request(bundle: Path | io.BytesIO) -> tuple[dict, list[tuple[str, bytes]]]:
    if isinstance(bundle, Path) and (not bundle.is_file() or bundle.stat().st_size > MAX_ZIP_BYTES):
        raise ValueError("Bundle fehlt oder ist zu groß.")
    with zipfile.ZipFile(bundle) as archive:
        entries = archive.infolist()
        if len(entries) > 8 or sum(e.file_size for e in entries) > MAX_PNG_BYTES:
            raise ValueError("Bundle enthält zu viele oder zu große Dateien.")
        names = [e.filename for e in entries]
        if len(set(names)) != len(names) or any(
                name not in (*SOURCE_NAMES, "request.json", "CODEX.md")
                for name in names):
            raise ValueError("Unbekannte Dateinamen im Bundle.")
        request = json.loads(archive.read("request.json"))
        if not isinstance(request, dict) or not isinstance(request.get("stageId"), str):
            raise ValueError("Ungültige Anfrage-Metadaten.")
        if request.get("format") != "stronghold-building-damage-request" or request.get("version") != 1:
            raise ValueError("Unbekanntes Schadens-Request-Format.")
        if request.get("provider") not in {None, "codex-chatgpt"}:
            raise ValueError("Unbekannter Bildanbieter.")
        if request.get("model", next(iter(MODELS))) not in MODELS:
            raise ValueError("Unbekanntes historisches GPT-Image-2.6-Modell.")
        if request.get("quality") not in {"medium", "high"} or request.get("size") not in {"auto", "1024x1024", "1536x1024", "1024x1536"}:
            raise ValueError("Ungültige Bildgenerierungs-Einstellungen.")
        prompt = request.get("prompt")
        if not isinstance(prompt, str) or not 20 <= len(prompt) <= 32000:
            raise ValueError("Promptlänge ist unzulässig.")
        refs = request.get("referenceFiles")
        if (not isinstance(refs, list) or not refs or refs[0] not in ("reference.png", "model_reference.png")
                or len(refs) > 4 or len(set(refs)) != len(refs)
                or any(name not in SOURCE_NAMES for name in refs)):
            raise ValueError("Ungültige Referenzbildliste.")
        images = [(name, archive.read(name)) for name in refs]
        original = archive.read("reference.png")
    for name, image in images:
        if len(image) > MAX_PNG_BYTES:
            raise ValueError(f"{name}: Bilddatei zu groß.")
        png_dimensions(image)
    source_sha = hashlib.sha256(original).hexdigest()
    if "input_fidelity" in request:
        raise ValueError("GPT Image 2.6 unterstützt input_fidelity nicht; Parameter entfernen.")
    if request.get("referenceSHA256") != source_sha:
        raise ValueError("Originalreferenz wurde seit Bundlerstellung verändert (SHA-256).")
    if png_dimensions(original) != (
            request.get("referenceWidth"), request.get("referenceHeight")):
        raise ValueError("Originalreferenzgröße stimmt nicht mit Request überein.")
    registration = request.get("registration")
    if registration is not None:
        if not isinstance(registration, dict) or refs[0] != "model_reference.png":
            raise ValueError("Ungültige Modellreferenz-Registrierung.")
        keys = ("width", "height", "scale", "left", "top", "sourceWidth", "sourceHeight")
        if any(type(registration.get(key)) is not int for key in keys):
            raise ValueError("Registrierung benötigt ganzzahlige Koordinaten.")
        w, h, scale, left, top, sw, sh = [registration[k] for k in keys]
        if (w not in (1024, 1536) or h not in (1024, 1536)
                or scale < 1 or sw != request["referenceWidth"] or sh != request["referenceHeight"]
                or left < 0 or top < 0 or left + sw * scale > w or top + sh * scale > h
                or request.get("size") != f"{w}x{h}"
                or png_dimensions(images[0][1]) != (w, h)):
            raise ValueError("Modellreferenz oder Bildregistrierung stimmt nicht.")
    return request, images


def normalize_model_output(data: bytes, request: dict) -> tuple[bytes | None, dict]:
    """Invert a nearest-neighbour registered model canvas without silently cropping art."""
    plan = request.get("registration")
    if not plan:
        return data, {"registered": False, "candidateWritten": True}
    try:
        from PIL import Image
    except ImportError as exc:
        raise ValueError("Zum Rückrechnen des GPT-Modellbildes ist Pillow erforderlich.") from exc
    dimensions = png_dimensions(data)
    expected = (plan["width"], plan["height"])
    if dimensions != expected:
        return None, {"registered": True, "candidateWritten": False,
                      "reason": "Modell lieferte andere Canvasgröße als angefordert.",
                      "expectedDimensions": list(expected)}
    with Image.open(io.BytesIO(data)) as im:
        if "A" not in im.getbands() and "transparency" not in im.info:
            return None, {"registered": True, "candidateWritten": False,
                          "reason": "PNG besitzt keinen Alphakanal."}
        rgba = im.convert("RGBA")
        left, top, sw, sh, scale = [plan[k] for k in
                                    ("left", "top", "sourceWidth", "sourceHeight", "scale")]
        box = (left, top, left + sw * scale, top + sh * scale)
        alpha = rgba.getchannel("A")
        outside = alpha.copy()
        outside.paste(0, box)
        outside_nonzero = sum(v > 0 for v in outside.tobytes())
        allowed = max(20, int(sw * sh * scale * scale * 0.0001))
        if outside_nonzero > allowed:
            return None, {"registered": True, "candidateWritten": False,
                          "reason": "Transparente Registrierungszone enthält zusätzliche Bildpixel.",
                          "strayPixels": outside_nonzero, "tolerance": allowed}
        crop = rgba.crop(box)
        fitted = crop.resize((sw, sh), Image.Resampling.NEAREST)
        output = io.BytesIO()
        fitted.save(output, format="PNG")
        return output.getvalue(), {
            "registered": True, "candidateWritten": True,
            "downsampleFactor": scale, "strayPixels": outside_nonzero,
            "sourceRectangle": list(box), "sampling": "nearest"
        }


def execute(request: dict, images: list[tuple[str, bytes]], output: Path) -> dict:
    if output.exists():
        raise ValueError("Ausgabeordner existiert bereits. Wähle einen neuen Ordner.")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="spritesuite-codex-") as folder:
        cwd = Path(folder)
        with session(cwd) as codex:
            data, generation_id = codex.generate(cwd, request, images)
    meta, files = result_files(data, generation_id, request)
    output.mkdir(exist_ok=False)
    for name, payload in files.items():
        with (output / name).open("xb") as handle:
            handle.write(payload)
    return meta


def result_files(data: bytes, generation_id: str | None, request: dict) -> tuple[dict, dict]:
    dims = png_dimensions(data)
    expected = [request["referenceWidth"], request["referenceHeight"]]
    fitted, alignment = normalize_model_output(data, request)
    if fitted is None and list(dims) == expected:
        fitted = data
        alignment = {"registered": False, "candidateWritten": True}
    final_dims = list(png_dimensions(fitted)) if fitted is not None else None
    meta = {
        "format": "stronghold-building-damage-candidate", "version": 1,
        "stageId": request["stageId"], "provider": "codex-chatgpt", "generationId": generation_id,
        "originalSHA256": request["referenceSHA256"],
        "modelOutputSHA256": hashlib.sha256(data).hexdigest(),
        "candidateSHA256": hashlib.sha256(fitted).hexdigest() if fitted is not None else None,
        "referenceDimensions": expected, "modelOutputDimensions": list(dims),
        "candidateDimensions": final_dims, "dimensionsMatch": final_dims == expected,
        "needsManualReview": True, "inGameTested": False, "alignment": alignment
    }
    files = {"model_candidate_raw.png": data,
             "candidate-meta.json": json.dumps(meta, indent=2, ensure_ascii=False).encode("utf-8")}
    if fitted is not None:
        files["candidate.png"] = fitted
    return meta, files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, help="Anfrage-ZIP aus dem Sprite-Editor")
    parser.add_argument("--output", type=Path, help="Neuer Kandidatenordner")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Anfrage nur prüfen (Standard)")
    mode.add_argument("--execute", action="store_true", help="Ein Bild mit dem ChatGPT-Konto in Codex erzeugen")
    mode.add_argument("--status", action="store_true", help="ChatGPT-Anmeldung im lokalen Codex-Client prüfen")
    mode.add_argument("--login", action="store_true", help="Anmeldung bei ChatGPT im Browser öffnen")
    args = parser.parse_args(argv)
    try:
        if args.status or args.login:
            if args.bundle or args.output:
                parser.error("--status und --login akzeptieren kein Bundle und keinen Ausgabeordner")
            with tempfile.TemporaryDirectory(prefix="spritesuite-codex-") as folder, session(Path(folder)) as codex:
                if args.login:
                    codex.login()
                result = {"chatgptConnected": codex.connected()}
        else:
            if not args.bundle or not args.output:
                parser.error("--bundle und --output sind für Bildanfragen erforderlich")
            request, images = load_request(args.bundle)
            result = (execute(request, images, args.output) if args.execute else {
                "dryRun": True, "provider": "codex-chatgpt", "stageId": request["stageId"],
                "referenceFiles": [name for name, _ in images], "output": str(args.output)
            })
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (ValueError, KeyError, OSError, zipfile.BadZipFile) as exc:
        print("Fehler: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

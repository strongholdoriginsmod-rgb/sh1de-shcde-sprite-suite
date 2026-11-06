#!/usr/bin/env python3
"""Codex-callable GPT-Image-2.6 damage candidate bridge; never changes game or project files."""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import sys
import urllib.error
import urllib.request
import uuid
import zipfile

MODELS = {"gpt-image-2.6-sunburst", "gpt-image-2.6-flare"}
SOURCE_NAMES = ("reference.png", "previous.png", "candidate.png", "model_reference.png", "model_previous.png", "model_candidate.png")
API_URL = "https://api.openai.com/v1/images/edits"
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


def load_request(bundle: Path) -> tuple[dict, list[tuple[str, bytes]]]:
    if not bundle.is_file() or bundle.stat().st_size > MAX_ZIP_BYTES:
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
        if request.get("format") != "stronghold-building-damage-request" or request.get("version") != 1:
            raise ValueError("Unbekanntes Schadens-Request-Format.")
        if request.get("model") not in MODELS:
            raise ValueError("Nur bestätigte GPT-Image-2.6-Modelle sind zulässig.")
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


def multipart(request: dict, images: list[tuple[str, bytes]]) -> tuple[bytes, str]:
    boundary = "SpriteSuite" + uuid.uuid4().hex
    out = bytearray()
    def field(key: str, value: str):
        out.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{value}\r\n".encode("utf-8"))
    for key in ("model", "prompt", "quality", "background", "output_format", "size",
                "complexity"):
        if key in request:
            field(key, request[key])
    for name, data in images:
        out.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"image[]\"; filename=\"{name}\"\r\nContent-Type: image/png\r\n\r\n".encode("ascii"))
        out.extend(data)
        out.extend(b"\r\n")
    out.extend(f"--{boundary}--\r\n".encode("ascii"))
    return bytes(out), f"multipart/form-data; boundary={boundary}"


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
    key = os.environ.get("OPENAI_API_KEY")
    if not key or not key.strip():
        raise ValueError("OPENAI_API_KEY ist nicht gesetzt; kein API-Aufruf erfolgt.")
    if output.exists() and any(output.iterdir()):
        raise ValueError("Ausgabeordner ist nicht leer; existierende Kandidaten bleiben erhalten.")
    if request.get("registration"):
        try:
            from PIL import Image  # noqa: F401
        except ImportError as exc:
            raise ValueError("Für den registrierten GPT-Image-Workflow Pillow installieren.") from exc
    body, content_type = multipart(request, images)
    url_request = urllib.request.Request(API_URL, data=body, headers={
        "Authorization": "Bearer " + key.strip(),
        "Content-Type": content_type,
        "Accept": "application/json"
    }, method="POST")
    try:
        with urllib.request.urlopen(url_request, timeout=240) as response:
            raw = response.read(MAX_PNG_BYTES * 2 + 1)
            request_id = response.headers.get("x-request-id", "")
    except urllib.error.HTTPError as exc:
        # No secret, source image or full response body in the error.
        raise ValueError(f"OpenAI Image API: HTTP {exc.code}. Keine Datei übernommen.") from None
    if len(raw) > MAX_PNG_BYTES * 2:
        raise ValueError("API-Antwort überschreitet Dateibudget.")
    result = json.loads(raw)
    items = result.get("data", [])
    if len(items) != 1 or not isinstance(items[0].get("b64_json"), str):
        raise ValueError("API hat kein einzelnes Base64-PNG geliefert.")
    candidate = base64.b64decode(items[0]["b64_json"], validate=True)
    dims = png_dimensions(candidate)
    if len(candidate) > MAX_PNG_BYTES:
        raise ValueError("Kandidatenbild zu groß.")
    fitted, alignment = normalize_model_output(candidate, request)
    final_dimensions = png_dimensions(fitted) if fitted else dims
    meta = {
        "format": "stronghold-building-damage-candidate", "version": 1,
        "stageId": request["stageId"], "model": request["model"],
        "originalSHA256": request["referenceSHA256"],
        "modelOutputSHA256": hashlib.sha256(candidate).hexdigest(),
        "candidateSHA256": hashlib.sha256(fitted).hexdigest() if fitted else None,
        "referenceDimensions": [request["referenceWidth"], request["referenceHeight"]],
        "modelOutputDimensions": list(dims),
        "candidateDimensions": list(final_dimensions),
        "dimensionsMatch": list(final_dimensions) == [request["referenceWidth"], request["referenceHeight"]],
        "needsManualReview": True, "inGameTested": False,
        "alignment": alignment, "apiRequestId": request_id
    }
    output.mkdir(parents=True, exist_ok=True)
    # Always retain the unmodified paid image as a separate reference.
    if request.get("registration"):
        with (output / "model_candidate_raw.png").open("xb") as handle:
            handle.write(candidate)
    if fitted:
        with (output / "candidate.png").open("xb") as handle:
            handle.write(fitted)
    with (output / "candidate-meta.json").open("x", encoding="utf-8") as handle:
        json.dump(meta, handle, indent=2, ensure_ascii=False)
    return meta


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, type=Path, help="Exportiertes ZIP aus dem Sprite Editor")
    parser.add_argument("--output", required=True, type=Path, help="Neuer/leer vorhandener Kandidatenordner")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Nur Bundle und Anfrage prüfen (Standard)")
    mode.add_argument("--execute", action="store_true", help="Kostenpflichtigen API-Aufruf ausdrücklich ausführen")
    args = parser.parse_args(argv)
    try:
        request, images = load_request(args.bundle)
        if args.execute:
            result = execute(request, images, args.output)
        else:
            result = {
                "dryRun": True, "model": request["model"], "stageId": request["stageId"],
                "referenceFiles": [name for name, _ in images],
                "output": str(args.output), "wouldCall": API_URL,
                "requiresExplicitExecute": True
            }
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (ValueError, KeyError, OSError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        print("Fehler: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

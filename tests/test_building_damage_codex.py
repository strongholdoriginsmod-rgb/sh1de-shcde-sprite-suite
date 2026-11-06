"""Offline tests for the Codex-callable Image-2.6 damage editor adapter."""
from __future__ import annotations

import base64
from contextlib import redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest import mock
import warnings
import zipfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import building_damage_codex as B  # noqa: E402


def png(w=64, h=32):
    """Minimal correct RGBA PNG with red opaque pixels and alpha elsewhere."""
    def chunk(name, data):
        return struct.pack(">I", len(data)) + name + data + struct.pack(
            ">I", zlib.crc32(name + data) & 0xffffffff)
    raw = b"".join(b"\x00" + bytes([140, 80, 30, 255] * w)
                   for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" +
            chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(raw)) +
            chunk(b"IEND", b""))


def request_for(source, model="gpt-image-2.6-sunburst"):
    return {
        "format": "stronghold-building-damage-request", "version": 1,
        "model": model, "prompt": "Damage the building without changing camera or anchor.",
        "quality": "high", "complexity": "high",
        "background": "transparent", "output_format": "png", "size": "auto",
        "stageId": "stage_fixture", "referenceWidth": 64, "referenceHeight": 32,
        "referenceSHA256": hashlib.sha256(source).hexdigest(),
        "referenceFiles": ["reference.png"]
    }


def bundle(path, source, request=None, extra=None):
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("reference.png", source)
        archive.writestr("request.json", json.dumps(request or request_for(source)))
        for name, content in (extra or {}).items():
            archive.writestr(name, content)


class FakeResponse:
    headers = {"x-request-id": "request_fake"}
    def __init__(self, output):
        self.output = output
    def __enter__(self):
        return self
    def __exit__(self, *_):
        return False
    def read(self, _max_bytes):
        return self.output


class DamageCodexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = png()
        self.bundle_path = self.root / "request.zip"
        bundle(self.bundle_path, self.source)

    def test_offline_default_dry_run_no_api_and_no_output(self):
        output = self.root / "output"
        with mock.patch.object(B.urllib.request, "urlopen",
                               side_effect=AssertionError("Network not allowed")):
            stream = io.StringIO()
            with redirect_stdout(stream):
                code = B.main(["--bundle", str(self.bundle_path),
                               "--output", str(output)])
            self.assertEqual(code, 0)
        self.assertTrue(json.loads(stream.getvalue())["dryRun"])
        self.assertFalse(output.exists())

    def test_damaged_reference_and_missing_reference_rejected(self):
        bad = request_for(self.source)
        bad["referenceSHA256"] = "a" * 64
        bundle(self.bundle_path, self.source, bad)
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            B.load_request(self.bundle_path)
        bad = request_for(self.source)
        bad["referenceWidth"] = 65
        bundle(self.bundle_path, self.source, bad)
        with self.assertRaisesRegex(ValueError, "größe"):
            B.load_request(self.bundle_path)

    def test_unknown_model_and_unsupported_fidelity_rejected(self):
        bad = request_for(self.source, "another-model")
        bundle(self.bundle_path, self.source, bad)
        with self.assertRaisesRegex(ValueError, "GPT-Image-2.6"):
            B.load_request(self.bundle_path)
        bad = request_for(self.source)
        bad["input_fidelity"] = "high"
        bundle(self.bundle_path, self.source, bad)
        with self.assertRaisesRegex(ValueError, "input_fidelity"):
            B.load_request(self.bundle_path)

    def test_explicit_execute_requires_out_of_band_api_key(self):
        req, images = B.load_request(self.bundle_path)
        output = self.root / "output"
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "OPENAI_API_KEY"):
                B.execute(req, images, output)
        self.assertFalse(output.exists())

    def test_multipart_contains_image_refs_and_valid_26_fields(self):
        req, images = B.load_request(self.bundle_path)
        body, mime = B.multipart(req, images)
        self.assertIn("multipart/form-data; boundary=", mime)
        self.assertIn(b'name="model"', body)
        self.assertIn(b'gpt-image-2.6-sunburst', body)
        self.assertIn(b'name="complexity"', body)
        self.assertIn(b'name="image[]"', body)
        self.assertNotIn(b'input_fidelity', body)
        self.assertIn(self.source, body)

    def test_mock_api_generates_candidate_and_provenance_without_overwrites(self):
        req, images = B.load_request(self.bundle_path)
        response = json.dumps({"data": [
            {"b64_json": base64.b64encode(self.source).decode()}
        ]}).encode()
        output = self.root / "candidate"
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test-unit"}, clear=True):
            with mock.patch.object(B.urllib.request, "urlopen", return_value=FakeResponse(response)) as invoke:
                result = B.execute(req, images, output)
        self.assertEqual(result["candidateDimensions"], [64, 32])
        self.assertEqual(result["apiRequestId"], "request_fake")
        self.assertTrue(result["needsManualReview"])
        self.assertEqual((output / "candidate.png").read_bytes(), self.source)
        self.assertEqual(json.loads((output / "candidate-meta.json").read_text(encoding="utf-8"))["candidateSHA256"],
                         hashlib.sha256(self.source).hexdigest())
        http_request = invoke.call_args.args[0]
        self.assertEqual(http_request.full_url, "https://api.openai.com/v1/images/edits")
        self.assertNotIn("sk-test-unit", (output / "candidate-meta.json").read_text(encoding="utf-8"))
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test-unit"}, clear=True):
            with self.assertRaisesRegex(ValueError, "nicht leer"):
                B.execute(req, images, output)

    def test_registered_pixel_canvas_roundtrip_and_stray_pixel_guard(self):
        from PIL import Image
        registration = {
            "width": 1024, "height": 1024, "scale": 14,
            "left": 64, "top": 512, "sourceWidth": 64, "sourceHeight": 32
        }
        original = Image.open(io.BytesIO(self.source)).convert("RGBA")
        model = Image.new("RGBA", (1024, 1024))
        model.paste(original.resize((896, 448), Image.Resampling.NEAREST), (64, 512))
        stream = io.BytesIO()
        model.save(stream, format="PNG")
        model_bytes = stream.getvalue()
        req = request_for(self.source)
        req["registration"] = registration
        req["size"] = "1024x1024"
        req["referenceFiles"] = ["model_reference.png"]
        bundle(self.bundle_path, self.source, req, extra={"model_reference.png": model_bytes})
        loaded, images = B.load_request(self.bundle_path)
        self.assertEqual([name for name, _ in images], ["model_reference.png"])
        raw, stats = B.normalize_model_output(model_bytes, loaded)
        self.assertTrue(stats["candidateWritten"])
        self.assertEqual(stats["strayPixels"], 0)
        restored = Image.open(io.BytesIO(raw)).convert("RGBA")
        self.assertEqual(restored.size, original.size)
        self.assertEqual(restored.tobytes(), original.tobytes())

        model.putpixel((0, 0), (255, 0, 0, 255))
        other = io.BytesIO()
        model.save(other, format="PNG")
        raw, report = B.normalize_model_output(other.getvalue(), loaded)
        self.assertTrue(report["candidateWritten"], "a single stray pixel is within the warning tolerance")
        for x in range(100):
            model.putpixel((x, 1), (255, 0, 0, 255))
        other = io.BytesIO()
        model.save(other, format="PNG")
        raw, report = B.normalize_model_output(other.getvalue(), loaded)
        self.assertIsNone(raw)
        self.assertFalse(report["candidateWritten"])
        self.assertGreater(report["strayPixels"], report["tolerance"])

    def test_registered_api_keeps_raw_and_only_writes_aligned_candidate(self):
        from PIL import Image
        registration = {
            "width": 1024, "height": 1024, "scale": 14,
            "left": 64, "top": 512, "sourceWidth": 64, "sourceHeight": 32
        }
        original = Image.open(io.BytesIO(self.source)).convert("RGBA")
        model = Image.new("RGBA", (1024, 1024))
        model.paste(original.resize((896, 448), Image.Resampling.NEAREST), (64, 512))
        stream = io.BytesIO()
        model.save(stream, format="PNG")
        model_bytes = stream.getvalue()
        req = request_for(self.source)
        req.update(registration=registration, size="1024x1024",
                   referenceFiles=["model_reference.png"])
        bundle(self.bundle_path, self.source, req, extra={"model_reference.png": model_bytes})
        loaded, images = B.load_request(self.bundle_path)
        output = self.root / "registered"
        response = json.dumps({"data": [{"b64_json": base64.b64encode(model_bytes).decode()}]}).encode()
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test-unit"}, clear=True):
            with mock.patch.object(B.urllib.request, "urlopen", return_value=FakeResponse(response)):
                result = B.execute(loaded, images, output)
        self.assertTrue(result["alignment"]["registered"])
        self.assertTrue(result["dimensionsMatch"])
        self.assertEqual(result["candidateDimensions"], [64, 32])
        self.assertEqual(result["modelOutputDimensions"], [1024, 1024])
        self.assertTrue((output / "model_candidate_raw.png").is_file())
        self.assertEqual(Image.open(output / "candidate.png").convert("RGBA").tobytes(),
                         original.tobytes())

    def test_malicious_archive_names_rejected(self):
        bundle(self.bundle_path, self.source, extra={"../evil.png": self.source})
        with self.assertRaisesRegex(ValueError, "Dateinamen"):
            B.load_request(self.bundle_path)

    def test_corrupt_png_header_rejected(self):
        with self.assertRaisesRegex(ValueError, "Ungültiges PNG"):
            B.png_dimensions(b"not a png")
        with self.assertRaisesRegex(ValueError, "Megapixel"):
            B.png_dimensions(png(64, 32)[:16] + struct.pack(">II", 9999, 9999) + png(64, 32)[24:])


if __name__ == "__main__":
    unittest.main()

"""Offline adversarial tests for the SHCDE building-damage runtime handoff."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import zipfile
import zlib

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import building_damage_runtime_preflight as P  # noqa: E402


def image(w=64, h=32):
    def part(name, data):
        return (struct.pack(">I", len(data)) + name + data +
                struct.pack(">I", zlib.crc32(name + data)))
    return (b"\x89PNG\r\n\x1a\n" +
            part(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)) +
            part(b"IDAT", zlib.compress(b"".join(b"\x00" + bytes([160, 90, 70, 255])*w
                                                     for _ in range(h)))) +
            part(b"IEND", b""))


def fixture(mask=False, mapped=True):
    png = image()
    stages = []
    entries = {}
    for kind, hp in (("mechanical", 75), ("mechanical", 40), ("fire", 50)):
        base = f"damage/g_abbey/{kind}/{hp}/"
        name = base + "0000.png"
        entries[name] = png
        row = {"slot": 0, "image": name, "sha256": hashlib.sha256(png).hexdigest(),
               "dx": 0, "dy": 0, "pivot": {"x": 0.5, "y": 0.0}, "ppu": 64}
        if mask:
            mask_name = base + "0000_m.png"
            entries[mask_name] = png
            row.update(mask=mask_name, maskSha256=hashlib.sha256(png).hexdigest())
        stages.append({
            "id": "d_" + kind + str(hp), "damageKind": kind, "hpAtOrBelow": hp,
            "approvalDigest": "a" * 64,  # synthetic self-consistency marker, never a signature
            "scene": "g_" + kind + str(hp),
            "settings": {"a": 1, "b": 1, "width": 64, "height": 32,
                         "anchor": "bottom", "order": "ascending"},
            "tiles": [row]
        })
    manifest = {
        "format": "stronghold-building-damage-library", "version": 1,
        "target": "Stronghold Crusader: Definitive Edition",
        "runtimeHookInstalled": False, "hpUnit": "percent_of_maximum_hp",
        "rule": "Use lowest threshold T where current HP percent <= T",
        "buildings": [{
            "id": "g_abbey", "name": "Abbey", "intactScene": "g_abbey",
            "gameBuildingType": 108 if mapped else None,
            "gameBuildingTypeVerifiedInGame": False, "stages": stages
        }]
    }
    return manifest, entries


def save(path, manifest, entries, extra=None):
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("damage-manifest.json", json.dumps(manifest, ensure_ascii=False))
        archive.writestr("README.txt", "Synthetic test: no install or game hook.")
        for name, data in entries.items():
            archive.writestr(name, data)
        for name, data in (extra or {}).items():
            archive.writestr(name, data)


class DamageRuntimePreflightTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.base = Path(self.folder.name)
        self.package = self.base / "damage.zip"
        self.manifest, self.entries = fixture()
        save(self.package, self.manifest, self.entries)

    def test_strict_contract_carries_stage_damage_kind_and_game_type(self):
        result = P.read_library(self.package)
        self.assertEqual(result["mappedTypes"], [108])
        self.assertEqual(result["unmappedBuildingGroups"], [])
        self.assertFalse(result["runtimeHookInstalled"])
        self.assertFalse(result["rendererMappingValidated"])
        self.assertFalse(result["inGameTested"])
        self.assertEqual([stage["hpAtOrBelow"] for stage in result["profiles"][0]["stages"]],
                         [75, 40, 50])
        table = P.table_lines(result)
        self.assertEqual(table[0], "# stronghold-building-damage-runtime-table-v1")
        self.assertTrue(table[2].endswith(hashlib.sha256(self.package.read_bytes()).hexdigest()))
        self.assertEqual(table[-1].split("\t")[2], "fire")
        self.assertEqual(len(table), 7)

    def test_unmapped_building_produces_no_runtime_candidate(self):
        manifest, entries = fixture(mapped=False)
        save(self.package, manifest, entries)
        report = P.read_library(self.package)
        self.assertEqual(report["mappedTypes"], [])
        self.assertEqual(report["unmappedBuildingGroups"], ["g_abbey"])
        self.assertEqual(len(P.table_lines(report)), 4)


    def test_legacy_unbound_approval_is_auditable_but_never_prepared(self):
        manifest = deepcopy(self.manifest)
        del manifest["buildings"][0]["stages"][0]["approvalDigest"]
        save(self.package, manifest, self.entries)
        report = P.read_library(self.package)
        self.assertEqual(report["unboundApprovedStages"], ["g_abbey:d_mechanical75"])
        self.assertEqual(len(P.table_lines(report)), 6, "one missing stage is excluded from runtime TSV")
        output = self.base / "unbound-output"
        self.assertEqual(P.main(["--package", str(self.package), "--dry-run"]), 0)
        self.assertEqual(P.main(["--package", str(self.package), "--prepare",
                                 "--output", str(output)]), 2)
        self.assertFalse(output.exists(), "incomplete package cannot become a prepared table")

    def test_forged_malformed_state_digest_rejected(self):
        manifest = deepcopy(self.manifest)
        manifest["buildings"][0]["stages"][1]["approvalDigest"] = "1234notsha"
        save(self.package, manifest, self.entries)
        with self.assertRaisesRegex(P.PreflightError, "Freigabe-Zustandsprüfsumme"):
            P.read_library(self.package)

    def test_masks_require_sha_and_match_image_dimensions(self):
        manifest, entries = fixture(mask=True)
        save(self.package, manifest, entries)
        result = P.read_library(self.package)
        self.assertEqual(result["mappedTypes"], [108])
        del manifest["buildings"][0]["stages"][0]["tiles"][0]["maskSha256"]
        save(self.package, manifest, entries)
        with self.assertRaisesRegex(P.PreflightError, "Maske ohne SHA-256"):
            P.read_library(self.package)

    def test_tampered_tile_sha_refused(self):
        manifest = deepcopy(self.manifest)
        manifest["buildings"][0]["stages"][0]["tiles"][0]["sha256"] = "a"*64
        save(self.package, manifest, self.entries)
        with self.assertRaisesRegex(P.PreflightError, "Tile-SHA-256"):
            P.read_library(self.package)

    def test_tampered_mask_sha_refused(self):
        manifest, entries = fixture(mask=True)
        manifest["buildings"][0]["stages"][0]["tiles"][0]["maskSha256"] = "b"*64
        save(self.package, manifest, entries)
        with self.assertRaisesRegex(P.PreflightError, "Materialmaske SHA-256"):
            P.read_library(self.package)

    def test_unknown_or_duplicate_paths_refused(self):
        save(self.package, self.manifest, self.entries, {"../escape.png": image()})
        with self.assertRaisesRegex(P.PreflightError, "Unsicherer ZIP-Dateiname|unsicherer Pfad"):
            P.read_library(self.package)
        save(self.package, self.manifest, self.entries,
             {"damage/g_abbey/mechanical/75/0000_m.png": image()})
        with self.assertRaisesRegex(P.PreflightError, "unreferenzierte"):
            P.read_library(self.package)

    def test_duplicate_threshold_and_building_type_refused(self):
        manifest = deepcopy(self.manifest)
        manifest["buildings"][0]["stages"][1]["hpAtOrBelow"] = 75
        save(self.package, manifest, self.entries)
        with self.assertRaisesRegex(P.PreflightError, "Doppelte HP"):
            P.read_library(self.package)
        manifest = deepcopy(self.manifest)
        second = deepcopy(manifest["buildings"][0])
        second["id"] = "g_second"
        manifest["buildings"].append(second)
        save(self.package, manifest, self.entries)
        with self.assertRaisesRegex(P.PreflightError, "Spiel-Gebäudetyp mehrfach"):
            P.read_library(self.package)

    def test_invalid_sprite_geometry_refused(self):
        manifest = deepcopy(self.manifest)
        manifest["buildings"][0]["stages"][0]["settings"]["width"] = 66
        save(self.package, manifest, self.entries)
        with self.assertRaisesRegex(P.PreflightError, "Tile-Breite"):
            P.read_library(self.package)

    def test_preflight_never_changes_source_and_output_is_exclusive(self):
        digest = hashlib.sha256(self.package.read_bytes()).hexdigest()
        output = self.base / "candidate"
        self.assertEqual(P.main(["--package", str(self.package)]), 0)
        self.assertFalse(output.exists())
        self.assertEqual(P.main(["--package", str(self.package), "--prepare",
                                 "--output", str(output), "--expected-sha256", digest]), 0)
        self.assertIn("building_type\tbuilding_group", (output / "building-damage-candidate.tsv").read_text())
        self.assertTrue((output / "building-damage-preflight.json").is_file())
        self.assertEqual(hashlib.sha256(self.package.read_bytes()).hexdigest(), digest)
        self.assertEqual(P.main(["--package", str(self.package), "--prepare",
                                 "--output", str(output)]), 2)

    def test_false_claim_runtime_hook_is_blocked(self):
        manifest = deepcopy(self.manifest)
        manifest["runtimeHookInstalled"] = True
        save(self.package, manifest, self.entries)
        with self.assertRaisesRegex(P.PreflightError, "Runtime-Installation"):
            P.read_library(self.package)

    def test_duplicate_manifest_json_fields_rejected(self):
        original = json.dumps(self.manifest, ensure_ascii=False)
        duplicate = original.replace('"version": 1,',
                                     '"version": 1, "version": 1,', 1)
        with zipfile.ZipFile(self.package, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("damage-manifest.json", duplicate)
            archive.writestr("README.txt", "synthetic")
            for name, data in self.entries.items():
                archive.writestr(name, data)
        with self.assertRaisesRegex(P.PreflightError, "Doppelte JSON"):
            P.read_library(self.package)

    def test_case_insensitive_duplicate_path_rejected(self):
        origin = next(iter(self.entries))
        save(self.package, self.manifest, self.entries,
             {origin.upper(): self.entries[origin]})
        with self.assertRaisesRegex(P.PreflightError, "Groß-/Kleinschreibung"):
            P.read_library(self.package)

    def test_png_crc_and_idat_integrity_even_with_updated_manifest_sha(self):
        png = image()
        idat = png.index(b"IDAT")
        broken_crc = bytearray(png)
        broken_crc[idat + 5] ^= 3
        with self.assertRaisesRegex(P.PreflightError, "CRC"):
            P.png_dimensions(bytes(broken_crc))
        corrupt_inflate = bytearray(png)
        corrupt_inflate[idat + 4] ^= 127
        chunk_start = idat - 4
        count = struct.unpack_from(">I", corrupt_inflate, chunk_start)[0]
        crc = zlib.crc32(corrupt_inflate[idat:idat + 4 + count])
        struct.pack_into(">I", corrupt_inflate, idat + 4 + count, crc)
        with self.assertRaisesRegex(P.PreflightError, "IDAT"):
            P.png_dimensions(bytes(corrupt_inflate))
        manifest = deepcopy(self.manifest)
        first = manifest["buildings"][0]["stages"][0]["tiles"][0]
        first["sha256"] = hashlib.sha256(corrupt_inflate).hexdigest()
        entries = dict(self.entries)
        entries[first["image"]] = bytes(corrupt_inflate)
        save(self.package, manifest, entries)
        with self.assertRaisesRegex(P.PreflightError, "IDAT"):
            P.read_library(self.package)

    def test_idat_bomb_and_trailing_png_bytes_refused(self):
        png = image(1, 1)
        def pack_chunk(kind, payload):
            return (struct.pack(">I", len(payload)) + kind + payload +
                    struct.pack(">I", zlib.crc32(kind + payload)))
        small = png[:33] + pack_chunk(b"IDAT", zlib.compress(b"\x00" * 100000)) + \
                pack_chunk(b"IEND", b"")
        with self.assertRaisesRegex(P.PreflightError, "Bilddaten"):
            P.png_dimensions(small)
        with self.assertRaisesRegex(P.PreflightError, "Endmarker"):
            P.png_dimensions(png + b"not-a-part-of-png")

    def test_unknown_ancillary_png_chunk_refused(self):
        png = image(1, 1)
        def pack_chunk(kind, data):
            return (struct.pack(">I", len(data)) + kind + data +
                    struct.pack(">I", zlib.crc32(kind + data)))
        extra = png[:33] + pack_chunk(b"tEXt", b"unsafe") + png[33:]
        with self.assertRaisesRegex(P.PreflightError, "Unbekannter PNG-Chunk"):
            P.png_dimensions(extra)

    def test_raw_png_ihdr_crc_is_checked(self):
        bad = bytearray(image())
        bad[19] ^= 3
        with self.assertRaisesRegex(P.PreflightError, "CRC"):
            P.png_dimensions(bytes(bad))


if __name__ == "__main__":
    unittest.main()

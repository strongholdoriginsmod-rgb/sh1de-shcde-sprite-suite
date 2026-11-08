"""Read-only capability and DLL-signature studio for SHCDE modding components.

An installed DLL is NOT proof of a working Script Extender hook, APIShared ABI,
Noesis/XAML binding or multiplayer safety. No DLL is loaded or executed.
"""
from __future__ import annotations

import argparse
from hashlib import file_digest
import json
import os
from pathlib import Path
import re
import struct
from typing import Any

from suite_environment_discovery import GAME_DATA, _safe_path

SCHEMA = "sprite-suite.runtime-capability-inspection.v1"
EXPECTED_SCHEMA = "sprite-suite.runtime-reference-hashes.v1"
MAX_DLL = 256 * 1024**2
MAX_COMPONENTS = 80
SHA_RE = re.compile(r"[a-fA-F0-9]{64}\Z")
COMPONENTS = ("ScriptExtender", "APIShared", "Serp")


class RuntimeCapabilityError(ValueError):
    pass


def _u16(blob: bytes, offset: int) -> int:
    if offset < 0 or offset + 2 > len(blob):
        raise RuntimeCapabilityError("Ungültiger DLL-Header")
    return struct.unpack_from("<H", blob, offset)[0]


def _u32(blob: bytes, offset: int) -> int:
    if offset < 0 or offset + 4 > len(blob):
        raise RuntimeCapabilityError("Ungültiger DLL-Header")
    return struct.unpack_from("<I", blob, offset)[0]


def pe_signature(file: Path) -> dict[str, Any]:
    """Safely parse PE/CLI structure without loading the binary as code."""
    with file.open("rb") as f:
        header = f.read(min(file.stat().st_size, 1024 * 1024))
        if len(header) < 0x40 or header[:2] != b"MZ":
            return {"pe": False, "managed_cli": False, "error": "not_pe"}
        offset = _u32(header, 0x3c)
        if offset < 0x40 or offset + 24 > len(header) or header[offset:offset+4] != b"PE\0\0":
            return {"pe": False, "managed_cli": False, "error": "invalid_pe_signature"}
        machine = _u16(header, offset + 4)
        sections = _u16(header, offset + 6)
        opt_size = _u16(header, offset + 20)
        start = offset + 24
        if sections > 96 or opt_size < 96 or start + opt_size + sections * 40 > len(header):
            return {"pe": False, "managed_cli": False, "error": "truncated_pe_headers"}
        magic = _u16(header, start)
        if magic not in (0x10B, 0x20B):
            return {"pe": False, "managed_cli": False, "error": "unknown_pe_format"}
        dir_start = start + (96 if magic == 0x10B else 112)
        result: dict[str, Any] = {
            "pe": True, "machine": hex(machine),
            "pe_format": "PE32" if magic == 0x10B else "PE32+",
            "managed_cli": False, "metadata_version": None
        }
        if dir_start + 15 * 8 > start + opt_size:
            return result
        clr_rva = _u32(header, dir_start + 14 * 8)
        clr_size = _u32(header, dir_start + 14 * 8 + 4)
        if not clr_rva or clr_size < 16:
            return result

        section_start = start + opt_size
        def physical(rva: int) -> int | None:
            for index in range(sections):
                sec = section_start + 40 * index
                size = _u32(header, sec + 8)
                virtual = _u32(header, sec + 12)
                raw_size = _u32(header, sec + 16)
                raw_offset = _u32(header, sec + 20)
                if virtual <= rva < virtual + max(size, raw_size) and rva - virtual < raw_size:
                    physical_offset = raw_offset + rva - virtual
                    if physical_offset + 16 <= file.stat().st_size:
                        return physical_offset
            return None
        clr_offset = physical(clr_rva)
        if clr_offset is None:
            result["header_warning"] = "clr_rva_unmapped"
            return result
        f.seek(clr_offset)
        clr = f.read(20)
        if len(clr) < 16:
            result["header_warning"] = "clr_header_truncated"
            return result
        meta_rva, meta_size = struct.unpack_from("<II", clr, 8)
        meta_offset = physical(meta_rva) if meta_size >= 16 else None
        if meta_offset is None:
            result["header_warning"] = "clr_metadata_unmapped"
            return result
        f.seek(meta_offset)
        meta = f.read(min(meta_size, 256))
        if len(meta) < 20 or meta[:4] != b"BSJB":
            result["header_warning"] = "invalid_clr_metadata"
            return result
        version_length = _u32(meta, 12)
        if not 0 < version_length <= 128 or 16 + version_length > len(meta):
            result["header_warning"] = "invalid_clr_version"
            return result
        version = meta[16:16+version_length].split(b"\0", 1)[0]
        result["managed_cli"] = True
        result["metadata_version"] = version.decode("ascii", "replace")
        return result


def hash_reference(path: str | Path | None) -> dict[str, list[str]]:
    if path is None:
        return {}
    file = _safe_path(path)
    if not file or not file.is_file() or file.stat().st_size > 1_000_000:
        raise RuntimeCapabilityError("Referenzmanifest fehlt, ist verknüpft oder zu groß")
    try:
        raw = json.loads(file.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise RuntimeCapabilityError("Referenzmanifest ist ungültig") from exc
    if (not isinstance(raw, dict) or raw.get("schema") != EXPECTED_SCHEMA
            or not isinstance(raw.get("expected"), dict) or not raw["expected"]):
        raise RuntimeCapabilityError("Unbekanntes Hashreferenz-Schema")
    result = {}
    for component, hashes in raw["expected"].items():
        if (component not in COMPONENTS or not isinstance(hashes, list)
                or not 0 < len(hashes) <= 32
                or not all(isinstance(h, str) and SHA_RE.fullmatch(h) for h in hashes)):
            raise RuntimeCapabilityError("Ungültige DLL-Hashreferenz")
        result[component] = [h.lower() for h in hashes]
    return result


def _candidate_paths(root: Path) -> list[tuple[str, Path]]:
    plugin = root / "BepInEx" / "plugins"
    if not plugin.is_dir() or _safe_path(plugin) is None:
        return []
    files: list[tuple[str, Path]] = []
    sentinel = plugin / "000shcdese" / "SHCDESE.dll"
    if _safe_path(sentinel) and sentinel.is_file():
        files.append(("ScriptExtender", sentinel))
    # Exactly two levels, bounded. Do not walk vendor trees or the rest of the disk.
    for container in list(plugin.iterdir())[:256]:
        if _safe_path(container) is None:
            continue
        members = ([container] if container.is_file() else
                   list(container.iterdir())[:128] if container.is_dir() else [])
        for file in members:
            if _safe_path(file) is None or not file.is_file() or file.suffix.casefold() != ".dll":
                continue
            name = file.stem.casefold()
            kind = "APIShared" if "apishared" in name or "sharedapi" in name else (
                "Serp" if "serp" in name else None)
            if kind is not None:
                files.append((kind, file))
            if len(files) >= MAX_COMPONENTS:
                return files
    return files


def inspect_game(root: Path | str, *, reference: dict[str, list[str]] | None = None) -> dict:
    location = _safe_path(root)
    if location is None or not location.is_dir():
        raise RuntimeCapabilityError("Spielordner fehlt oder ist verknüpft")
    refs = reference or {}
    game_file = location / GAME_DATA["shcde"] / "resources.assets"
    structural = (_safe_path(game_file) is not None and game_file.is_file())
    records = []
    for component, file in _candidate_paths(location):
        if (_safe_path(file) is None or not file.is_file()
                or file.stat().st_size > MAX_DLL or file.stat().st_size < 2):
            records.append({"component": component, "file": str(file),
                            "status": "invalid_or_oversized", "abi_verified": False})
            continue
        before = file.stat()
        with file.open("rb") as stream:
            digest = file_digest(stream, "sha256").hexdigest()
        try:
            signature = pe_signature(file)
        except (OSError, ValueError, RuntimeCapabilityError):
            signature = {"pe": False, "managed_cli": False, "error": "unreadable_header"}
        after = file.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise RuntimeCapabilityError("DLL während der Prüfung verändert")
        expected = refs.get(component)
        records.append({
            "component": component, "file": str(file), "size": before.st_size,
            "sha256": digest, "signature": signature,
            "reference_sha256_match": (digest in expected if expected is not None else None),
            "reference_provided": expected is not None,
            "abi_verified": False,
            "in_game_lifecycle_verified": False,
        })
    counts = {name: sum(row["component"] == name for row in records) for name in COMPONENTS}
    return {
        "schema": SCHEMA, "game_root": str(location), "game_structural_match": structural,
        "components": records, "counts": counts,
        "ambiguous_components": [name for name in COMPONENTS if counts[name] > 1],
        "notes": [
            "Presence, PE/CLI structure and SHA-256 are offline evidence only.",
            "A matching user-supplied SHA is not native ABI or game-version approval.",
            "Real APIShared/Serp exports and Script Extender lifecycle require version-pinned QA."
        ],
        "executed_discovered_dlls": False,
        "modified_game": False,
        "runtime_abi_verified": False,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--game-root", required=True, type=Path,
                   help="Existing SHCDE game/QA root (read-only)")
    p.add_argument("--reference", type=Path,
                   help="Optional local SHA-256 reference manifest, never an ABI approval")
    args = p.parse_args(argv)
    try:
        result = inspect_game(args.game_root, reference=hash_reference(args.reference))
    except (OSError, RuntimeCapabilityError) as exc:
        p.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

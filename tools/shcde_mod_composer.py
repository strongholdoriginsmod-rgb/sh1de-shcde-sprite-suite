#!/usr/bin/env python3
"""Compose freely selected SHCDE mod folders and ZIPs with byte-exact provenance.

All asset extensions, version strings and user-chosen input/output folders are
accepted. The only rejected entries are structurally ambiguous/unsafe archive
paths (absolute paths, traversals and duplicate normalized Windows names).
No game files are changed, and output never replaces an existing file.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from dataclasses import dataclass
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sys
import tempfile
import unicodedata
from zipfile import BadZipFile, ZipFile, ZIP_DEFLATED, ZipInfo

from suite_windows_paths import is_link_or_reparse, is_reserved_windows_component

SCHEMA = "spritesuite.shcde.mod-composition.v1"
PROVENANCE_PATH = ".spritesuite/composition.json"


def entry_name(value: str) -> str:
    """Interpret ZIP member names as Windows-portable relative POSIX paths."""
    if not isinstance(value, str) or not value or "\0" in value:
        raise ValueError("Empty or NUL-containing mod archive member")
    path = value.replace("\\", "/")
    if path.startswith("/") or ":" in path.split("/", 1)[0]:
        raise ValueError("Absolute or drive-qualified mod member: " + value)
    parts = path.split("/")
    if any(part in ("", ".", "..") or is_reserved_windows_component(part) for part in parts):
        raise ValueError("Ambiguous or escaping mod member: " + value)
    normalized = "/".join(unicodedata.normalize("NFC", part) for part in parts)
    if len(normalized) > 32000:
        raise ValueError("Member path cannot be represented by Windows")
    return normalized


def path_key(value: str) -> str:
    return entry_name(value).casefold()


@dataclass(frozen=True)
class Member:
    source_index: int
    source_name: str
    member: str
    size: int
    identity: str     # "dir" or "zip"
    real_path: Path | None = None
    zip_index: int = -1


def _file_stream(member: Member, opened_zips: dict[int, ZipFile]):
    if member.identity == "dir":
        return member.real_path.open("rb")
    zip_ = opened_zips[member.source_index]
    return zip_.open(zip_.infolist()[member.zip_index], "r")


def _hash_member(member: Member, opened_zips: dict[int, ZipFile]) -> str:
    h = hashlib.sha256()
    with _file_stream(member, opened_zips) as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _scan_directory(root: Path, index: int):
    for candidate in sorted(root.rglob("*"), key=lambda p: p.relative_to(root).as_posix().casefold()):
        if is_link_or_reparse(candidate):
            raise ValueError("Linked file or directory in mod input: " + str(candidate))
        if candidate.is_dir():
            continue
        if not candidate.is_file():
            raise ValueError("Linked or special file in mod input: " + str(candidate))
        name = entry_name(candidate.relative_to(root).as_posix())
        yield Member(index, root.name, name, candidate.stat().st_size, "dir", candidate)


def _scan_zip(root: Path, index: int, archive: ZipFile):
    inherited_receipt = PROVENANCE_PATH in archive.namelist()
    if inherited_receipt:
        checked = inspect(root)
        if checked["integrityErrors"]:
            raise ValueError("Input composition failed verification: " +
                             "; ".join(checked["integrityErrors"]))
    for i, member in enumerate(archive.infolist()):
        if member.is_dir():
            continue
        name = entry_name(member.filename)
        # A verified prior export is a reusable mod input. Its internal
        # receipt describes that input, while the new receipt describes the
        # current combination. Never duplicate the reserved ZIP member.
        if inherited_receipt and name == PROVENANCE_PATH:
            continue
        yield Member(index, root.name, name, member.file_size, "zip", zip_index=i)


def scan_sources(sources: list[Path], opened_zips: dict[int, ZipFile]) -> list[list[Member]]:
    if not sources:
        raise ValueError("Choose at least one mod directory or ZIP")
    scanned: list[list[Member]] = []
    for index, source in enumerate(sources):
        path = source.resolve(strict=True)
        if path.is_dir():
            files = list(_scan_directory(path, index))
        elif path.is_file() and path.suffix.lower() == ".zip":
            archive = opened_zips[index] = ZipFile(path, "r")
            files = list(_scan_zip(path, index, archive))
        else:
            raise ValueError("Mod source must be a directory or ZIP: " + str(source))
        if not files:
            raise ValueError("Mod source is empty: " + str(source))
        scanned.append(files)
    return scanned


def plan_sources(sources: list[Path], *, policy: str = "last", include_hashes: bool = True,
                 stack: ExitStack | None = None,
                 opened_zips: dict[int, ZipFile] | None = None) -> tuple[dict, list[Member]]:
    if policy not in ("first", "last", "error"):
        raise ValueError("Unknown conflict policy")
    own_stack = stack is None
    if stack is None:
        stack = ExitStack()
    try:
        opened = opened_zips if opened_zips is not None else {}
        all_members = scan_sources([Path(x) for x in sources], opened)
        for archive in opened.values():
            stack.callback(archive.close)
        selected: dict[str, Member] = {}
        seen: dict[str, list[Member]] = {}
        conflicts: list[dict] = []
        for files in all_members:
            for member in files:
                key = path_key(member.member)
                seen.setdefault(key, []).append(member)
                previous = selected.get(key)
                if previous is not None:
                    if previous.member != member.member:
                        differences = "case_or_unicode"
                    else:
                        differences = "same_path"
                    conflicts.append({
                        "path": member.member,
                        "earlierSource": previous.source_name,
                        "laterSource": member.source_name,
                        "type": differences,
                        "winner": "first" if policy == "first" else "last" if policy == "last" else "none",
                    })
                    if policy == "error":
                        continue
                    if policy == "first":
                        continue
                selected[key] = member
        if policy == "error" and conflicts:
            raise ValueError("Conflicting mod paths: " +
                             ", ".join(x["path"] for x in conflicts[:6]))
        if path_key(PROVENANCE_PATH) in selected:
            raise ValueError("Input owns the reserved SpriteSuite composition receipt path")
        chosen = sorted(selected.values(), key=lambda m: m.member.casefold())
        records = []
        for member in chosen:
            entry = {"path": member.member, "source": member.source_name,
                     "sourceIndex": member.source_index, "bytes": member.size}
            if include_hashes:
                entry["sha256"] = _hash_member(member, opened)
            records.append(entry)
        report = {"schema": SCHEMA, "sources": [Path(s).name for s in sources],
                  "conflictPolicy": policy, "files": len(chosen),
                  "totalUncompressedBytes": sum(m.size for m in chosen),
                  "conflicts": conflicts, "entries": records,
                  "requiresCreativeApproval": False, "versionRestricted": False}
        report["upstreamCompositions"] = [
            {"sourceIndex": index, "receiptSHA256": hashlib.sha256(
                archive.read(PROVENANCE_PATH)).hexdigest()}
            for index, archive in opened.items()
            if PROVENANCE_PATH in archive.namelist()
        ]
        return report, chosen
    finally:
        if own_stack:
            stack.close()


def compose(sources: list[Path], destination: Path, *, policy: str = "last") -> dict:
    output = Path(destination)
    if output.exists():
        raise FileExistsError("Will not overwrite an existing mod ZIP: " + str(output))
    if output.suffix.lower() != ".zip":
        raise ValueError("Destination must name a ZIP archive")
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, staged_name = tempfile.mkstemp(prefix=".spritesuite-compose-", suffix=".zip",
                                              dir=output.parent)
    os.close(descriptor)
    staged = Path(staged_name)
    try:
        with ExitStack() as stack:
            archives: dict[int, ZipFile] = {}
            report, selected = plan_sources(sources, policy=policy, stack=stack,
                                            opened_zips=archives)
            with ZipFile(staged, "w", compression=ZIP_DEFLATED, compresslevel=6,
                         allowZip64=True) as product:
                for member, planned in zip(selected, report["entries"]):
                    info = ZipInfo(member.member, date_time=(2020, 1, 1, 0, 0, 0))
                    info.compress_type = ZIP_DEFLATED
                    info.external_attr = 0o100644 << 16
                    digest = hashlib.sha256()
                    size = 0
                    with product.open(info, "w", force_zip64=True) as sink:
                        with _file_stream(member, archives) as source:
                            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                                sink.write(chunk)
                                digest.update(chunk)
                                size += len(chunk)
                    if digest.hexdigest() != planned["sha256"] or size != planned["bytes"]:
                        raise ValueError("Mod source changed during export: " + member.member)
                raw = json.dumps(report, ensure_ascii=False, indent=2,
                                 sort_keys=True).encode("utf-8") + b"\n"
                product.writestr(PROVENANCE_PATH, raw, compress_type=ZIP_DEFLATED)
        # A hard-link publication is exclusive and exposes only the complete
        # file. It also preserves a target created by a concurrent exporter.
        if os.name == "nt":
            os.rename(staged, output)
        else:
            os.link(staged, output)
    finally:
        staged.unlink(missing_ok=True)
    result = {"zip": str(output), "sha256": sha256_file(output),
              "files": report["files"], "conflicts": report["conflicts"],
              "uncompressedBytes": report["totalUncompressedBytes"]}
    return result


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect(path: Path) -> dict:
    archive_path = Path(path)
    with ZipFile(archive_path) as archive:
        failures = []
        duplicate_keys: set[str] = set()
        paths: set[str] = set()
        total = 0
        for member in archive.infolist():
            if member.is_dir():
                continue
            try:
                key = path_key(member.filename)
            except ValueError as err:
                failures.append(str(err))
                continue
            if key in paths:
                duplicate_keys.add(key)
            paths.add(key)
            total += member.file_size
        broken = archive.testzip()
        if broken is not None:
            failures.append("Corrupt ZIP member: " + broken)
        if duplicate_keys:
            failures.append("Case/Unicode-colliding members: " + ", ".join(sorted(duplicate_keys)))
        receipt = None
        if PROVENANCE_PATH in archive.namelist():
            try:
                receipt = json.loads(archive.read(PROVENANCE_PATH))
                if not isinstance(receipt, dict):
                    raise ValueError("Composition receipt must be an object")
                expected = receipt.get("entries")
                if receipt.get("schema") != SCHEMA or not isinstance(expected, list):
                    raise ValueError("Unknown composition receipt")
                recorded = set()
                for entry in expected:
                    name = entry_name(entry["path"])
                    key = path_key(name)
                    if key in recorded or name == PROVENANCE_PATH:
                        raise ValueError("Duplicate receipt member")
                    recorded.add(key)
                    raw = archive.read(name)
                    if len(raw) != entry["bytes"] or hashlib.sha256(raw).hexdigest() != entry["sha256"]:
                        failures.append("Composition member changed: " + name)
                if recorded != paths - {path_key(PROVENANCE_PATH)}:
                    failures.append("Composition receipt inventory differs")
            except (ValueError, UnicodeError, KeyError, TypeError):
                failures.append("Invalid composition receipt")
        return {"archive": str(archive_path), "sha256": sha256_file(archive_path),
                "zipMembers": len(paths), "uncompressedBytes": total,
                "integrityErrors": failures, "receipt": receipt,
                "gameModified": False}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="action", required=True)
    for name in ("plan", "compose"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--source", action="append", type=Path, required=True,
                         help="Select any directory or ZIP; repeat to combine mods")
        cmd.add_argument("--conflicts", choices=("first", "last", "error"), default="last")
        if name == "compose":
            cmd.add_argument("--output", required=True, type=Path)
    view = sub.add_parser("inspect")
    view.add_argument("--archive", required=True, type=Path)
    args = p.parse_args(argv)
    try:
        if args.action == "plan":
            report, _ = plan_sources(args.source, policy=args.conflicts)
        elif args.action == "compose":
            report = compose(args.source, args.output, policy=args.conflicts)
        else:
            report = inspect(args.archive)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if not report.get("integrityErrors") else 2
    except (OSError, ValueError, KeyError, RuntimeError, BadZipFile) as exc:
        print("SHCDE Mod Composer: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

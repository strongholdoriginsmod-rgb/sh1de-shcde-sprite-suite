"""Pack or restore the artwork inputs referenced by SpriteSuite profiles.

Installation is dry-run by default. Every ZIP entry is bounded and verified
before writing; missing files are created exclusively (never replaced), with
best-effort rollback of files created by a failed restore.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import zipfile

from suite_windows_paths import is_link_or_reparse, is_reserved_windows_component

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = "PROJECT-INPUTS.json"
MAX_FILES = 25_000
MAX_BYTES = 2 * 1024 ** 3
MAX_FILE_BYTES = 512 * 1024 ** 2
MAX_MANIFEST_BYTES = 2 * 1024 ** 2
_HASH = re.compile(r"[0-9a-f]{64}\Z")


def safe_relative(value: str) -> PurePosixPath:
    """Validate portable input paths, including names reserved by Windows."""
    if not isinstance(value, str) or not value or len(value) > 240:
        raise ValueError("Invalid project input path")
    if "\\" in value or "\x00" in value or value.startswith("/"):
        raise ValueError("Invalid project input path: " + value[:120])
    parts = value.split("/")
    if parts[0] not in {"assets", "work"} or any(
        part in {"", ".", ".."} or is_reserved_windows_component(part)
        for part in parts
    ):
        raise ValueError("Invalid project input path: " + value[:120])
    return PurePosixPath(*parts)


def _no_links(root: Path, path: Path) -> None:
    """Reject reparse points in the root-to-file chain."""
    if is_link_or_reparse(root):
        raise ValueError("Linked project root is not supported")
    current = path
    while current != root:
        if is_link_or_reparse(current):
            raise ValueError("Linked project input or destination: " + str(current))
        if current == current.parent:
            raise ValueError("Input escapes selected project")
        current = current.parent


def _target(root: Path, relative: PurePosixPath) -> Path:
    raw = root.joinpath(*relative.parts)
    _no_links(root, raw)
    if not raw.resolve(strict=False).is_relative_to(root):
        raise ValueError("Project input escapes selected destination")
    return raw


def inputs(project: Path, profile_root: Path | None = None) -> list[Path]:
    """Find only regular project files required by profiles and BC7 config."""
    project = Path(project).resolve(strict=True)
    profile_root = project if profile_root is None else Path(profile_root)
    found: set[Path] = set()

    def visit(value: object) -> None:
        if isinstance(value, dict):
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, str) and value.startswith(("assets/", "work/")):
            raw = _target(project, safe_relative(value))
            if not raw.exists():
                raise FileNotFoundError(value)
            for file in ([raw] if raw.is_file() else raw.rglob("*")):
                _no_links(project, file)
                if file.is_file():
                    found.add(file)

    for profile in sorted((profile_root / "profiles").glob("*.json")):
        visit(json.loads(profile.read_text(encoding="utf-8-sig")))
    visit(json.loads(
        (profile_root / "config/ui-textures-bc7-v1.json").read_text(
            encoding="utf-8-sig"
        )
    ))
    return sorted(found)


def digest(path: Path) -> str:
    h = sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def pack(project: Path, output: Path, profile_root: Path | None = None) -> dict:
    """Create a new ZIP without overwriting a previous user archive."""
    project = Path(project).resolve(strict=True)
    files = inputs(project, profile_root)
    records = []
    total = 0
    seen = set()
    for file in files:
        relative = file.relative_to(project).as_posix()
        safe_relative(relative)
        folded = relative.casefold()
        if folded in seen:
            raise ValueError("Case-colliding project input paths")
        seen.add(folded)
        size = file.stat().st_size
        total += size
        if size > MAX_FILE_BYTES or total > MAX_BYTES or len(files) > MAX_FILES:
            raise ValueError("Project input size or file count limit exceeded")
        records.append({"path": relative, "bytes": size, "sha256": digest(file)})
    manifest = json.dumps({"schema": 1, "files": records},
                          ensure_ascii=False, indent=2).encode("utf8") + b"\n"
    if len(manifest) > MAX_MANIFEST_BYTES:
        raise ValueError("Project input manifest exceeds limit")
    output = Path(output)
    if output.suffix.lower() != ".zip" or is_link_or_reparse(output):
        raise ValueError("Choose a new regular .zip output file")
    if output.exists():
        raise FileExistsError("Project archive already exists")
    for parent in (output.parent, *output.parent.parents):
        if is_link_or_reparse(parent):
            raise ValueError("Linked archive output directory is not allowed")
    output.parent.mkdir(parents=True, exist_ok=True)
    created = False
    try:
        with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED,
                             compresslevel=6) as archive:
            created = True
            archive.writestr(MANIFEST, manifest)
            for file, row in zip(files, records):
                _no_links(project, file)
                before = file.stat()
                archive.write(file, row["path"])
                after = file.stat()
                if ((before.st_size, before.st_mtime_ns) !=
                    (after.st_size, after.st_mtime_ns) or
                    digest(file) != row["sha256"]):
                    raise ValueError("Project input changed during archive creation")
        return {"files": len(files), "bytes": total, "sha256": digest(output)}
    except Exception:
        if created:
            output.unlink(missing_ok=True)
        raise


def _records(archive: zipfile.ZipFile) -> list[dict]:
    """Validate member names and bounded manifest before extracting bytes."""
    members = archive.infolist()
    if not 1 <= len(members) <= MAX_FILES + 1:
        raise ValueError("Invalid project input archive file count")
    by_name: dict[str, zipfile.ZipInfo] = {}
    case_names = set()
    total = 0
    for info in members:
        key = info.filename.casefold()
        kind = (info.external_attr >> 16) & 0o170000
        if (key in case_names or info.is_dir() or
            kind not in (0, stat.S_IFREG) or info.flag_bits & 1 or
            info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
            raise ValueError("Duplicate, linked or unsupported ZIP member")
        case_names.add(key)
        by_name[info.filename] = info
        if info.filename == MANIFEST:
            if info.file_size > MAX_MANIFEST_BYTES:
                raise ValueError("Project input manifest too large")
        else:
            safe_relative(info.filename)
            total += info.file_size
            if (info.file_size > MAX_FILE_BYTES or total > MAX_BYTES or
                (info.file_size > 1024 * 1024 and
                 info.file_size > max(1, info.compress_size) * 1000)):
                raise ValueError("Project archive exceeds safe size limits")
    if MANIFEST not in by_name:
        raise ValueError("Project input manifest missing")
    try:
        data = json.loads(archive.read(MANIFEST).decode("utf8"))
    except (ValueError, UnicodeError, RuntimeError, zipfile.BadZipFile) as exc:
        raise ValueError("Cannot read project input manifest") from exc
    if not isinstance(data, dict) or data.get("schema") != 1:
        raise ValueError("Unsupported project input manifest")
    rows = data.get("files")
    if not isinstance(rows, list) or len(rows) != len(members)-1:
        raise ValueError("Project input manifest file list is incomplete")
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"path", "bytes", "sha256"}:
            raise ValueError("Invalid input manifest entry")
        name = row["path"]
        if not isinstance(name, str):
            raise ValueError("Invalid input file name")
        safe_relative(name)
        expected = by_name.get(name)
        if (name.casefold() in seen or expected is None or
            type(row["bytes"]) is not int or row["bytes"] != expected.file_size or
            not isinstance(row["sha256"], str) or
            not _HASH.fullmatch(row["sha256"])):
            raise ValueError("Inconsistent project input manifest entry")
        seen.add(name.casefold())
    if set(by_name) != {row["path"] for row in rows} | {MANIFEST}:
        raise ValueError("Unlisted project input in ZIP")
    return rows


def _copy_checked(archive: zipfile.ZipFile, row: dict, target: Path) -> None:
    """Create one file exclusively, never replacing an existing destination."""
    fd, name = tempfile.mkstemp(prefix=".project-input-", suffix=".tmp",
                                dir=target.parent)
    stage = Path(name)
    try:
        checked = sha256()
        count = 0
        with os.fdopen(fd, "wb") as dst, archive.open(row["path"]) as src:
            for block in iter(lambda: src.read(1024 * 1024), b""):
                count += len(block)
                if count > row["bytes"]:
                    raise ValueError("Archive member exceeds declared size")
                checked.update(block)
                dst.write(block)
            dst.flush()
            os.fsync(dst.fileno())
        if count != row["bytes"] or checked.hexdigest() != row["sha256"]:
            raise ValueError("Project input checksum mismatch: " + row["path"])
        # 'xb' is atomic with respect to a newly-created destination.
        # shutil.move/Path.replace could silently overwrite an intervening file.
        created = False
        try:
            with target.open("xb") as dst:
                created = True
                with stage.open("rb") as src:
                    shutil.copyfileobj(src, dst, length=1024 * 1024)
                dst.flush()
                os.fsync(dst.fileno())
        except Exception:
            # Only the successful exclusive-open owner may clean this path.
            if created and not is_link_or_reparse(target):
                target.unlink(missing_ok=True)
            raise
    finally:
        stage.unlink(missing_ok=True)


def install(archive_path: Path, destination: Path, write: bool = False) -> dict:
    """Check all ZIP files first, then create only missing project inputs."""
    destination = Path(destination)
    if is_link_or_reparse(destination):
        raise ValueError("Linked destination is not supported")
    root = destination.resolve(strict=False)
    archive_path = Path(archive_path)
    if (is_link_or_reparse(archive_path) or not archive_path.is_file() or
        archive_path.stat().st_size > MAX_BYTES + MAX_MANIFEST_BYTES):
        raise ValueError("Invalid project input ZIP")
    try:
        with zipfile.ZipFile(archive_path) as archive:
            rows = _records(archive)
            plan = []
            for row in rows:
                target = _target(root, safe_relative(row["path"]))
                h = sha256()
                size = 0
                with archive.open(row["path"]) as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        size += len(chunk)
                        if size > row["bytes"]:
                            raise ValueError("Archive member exceeds declared size")
                        h.update(chunk)
                if size != row["bytes"] or h.hexdigest() != row["sha256"]:
                    raise ValueError("Archive checksum mismatch: " + row["path"])
                if target.exists():
                    if not target.is_file() or digest(target) != row["sha256"]:
                        raise ValueError("Existing modified input: " + row["path"])
                else:
                    plan.append((row, target))
            if not write:
                return {"checked": len(rows), "new_files": len(plan), "written": 0}
            created = []
            try:
                for row, target in plan:
                    _target(root, safe_relative(row["path"]))
                    target.parent.mkdir(parents=True, exist_ok=True)
                    # If a file appeared after validation, refuse rather than
                    # overwriting it; the exclusive open inside _copy_checked
                    # prevents a second race.
                    if target.exists() or is_link_or_reparse(target):
                        raise FileExistsError("Project input destination now exists: " + row["path"])
                    _copy_checked(archive, row, target)
                    created.append(target)
                return {"checked": len(rows), "new_files": len(plan),
                        "written": len(plan)}
            except Exception:
                for created_path in reversed(created):
                    if created_path.is_file() and not is_link_or_reparse(created_path):
                        created_path.unlink()
                raise
    except (zipfile.BadZipFile, EOFError, RuntimeError) as exc:
        raise ValueError("Corrupt or unreadable project input ZIP") from exc


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("pack", help="Collect project artwork without changing source files")
    build.add_argument("--source-project", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    restore = sub.add_parser("install", help="Validate an archive (dry-run by default)")
    restore.add_argument("--archive", type=Path, required=True)
    restore.add_argument("--write", action="store_true",
                         help="Create verified missing files; never overwrite existing files")
    args = parser.parse_args()
    result = pack(args.source_project, args.output, ROOT) if args.command == "pack" else (
        install(args.archive, ROOT, args.write)
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

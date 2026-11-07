"""Safe, version-neutral local workspace for freely editable HUD/menu assets.

The workspace is private under work/ and contains authored Override/ and
Patches/ paths accepted by se_asset_package. Nothing writes a game install.
Native resource-key mapping remains explicit; no UI XAML keys are invented.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
from typing import Literal

from PIL import Image, ImageOps, UnidentifiedImageError
from suite_windows_paths import (
    is_link_or_reparse as _linked,
    is_reserved_windows_component as _windows_reserved_name,
)

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "work"
DEFAULT = WORK / "hud-menu-werkstatt"
BASELINES = ".hud-menu-metadata"  # Sibling under work/, never the package source
CATEGORIES = {
    "Menüs / UI-Bilder": "Override/Assets/GUI/Images",
    "HUD / UI-Sprites": "Override/Assets/GUI/Sprites",
    "Spiel-Sprites": "Override/Sprites",
    "Zusätzliche Atlanten": "Override/Atlas",
}
PATCH_FOLDER = "Patches/Assets/GUI"
MEDIA_FOLDERS = ("Override/Assets/GUI/Video", "Locales")
_MAX_SOURCE = 128 * 1024 * 1024
_MAX_PIXELS = 30_000_000
_ALLOWED_SOURCE = {".png", ".jpg", ".jpeg", ".webp"}
_SAFE_NAME = re.compile(r"[^\w. -]+", re.UNICODE)


class WorkshopError(ValueError):
    """A source, output or snapshot would be unsafe or inconsistent."""


@dataclass(frozen=True)
class WorkshopAsset:
    relative_path: str
    name: str
    kind: str
    status: str
    size: int
    baseline_path: Path | None
    path: Path


def _sha(data: bytes) -> str:
    return sha256(data).hexdigest()


def workspace(path: Path | str = DEFAULT, *, create: bool = False) -> Path:
    """Resolve only a descendant of work/; never follow user-created links."""
    work = WORK.resolve()
    raw = Path(path)
    if not raw.is_absolute():
        raw = ROOT / raw
    if _linked(raw):
        raise WorkshopError("Symbolic workspaces are not allowed")
    target = raw.resolve(strict=False)
    if target == work or not target.is_relative_to(work):
        raise WorkshopError("Workspace must be strictly inside SpriteSuite/work/")
    if target.exists() and not target.is_dir():
        raise WorkshopError("Workspace is not a directory")
    # Both symlinked parents and junctions must be rejected, even when the
    # final target would still resolve inside work/.
    node = raw
    while node != work and node != node.parent:
        if _linked(node):
            raise WorkshopError("Workspace path contains a symlink")
        node = node.parent
    if create:
        target.mkdir(parents=True, exist_ok=True)
    return target


def _relative(relative: str, *, patch: bool = False) -> PurePosixPath:
    if not isinstance(relative, str) or not relative or "\\" in relative or "\x00" in relative:
        raise WorkshopError("Invalid asset path")
    name = PurePosixPath(relative)
    if name.is_absolute() or any(
        part in ("", ".", "..") or part.endswith((" ", "."))
        or _windows_reserved_name(part) or ":" in part
        for part in relative.split("/")
    ):
        raise WorkshopError("Unsafe resource-key path")
    if len(relative) > 230:
        raise WorkshopError("Resource path too long")
    if patch:
        if not relative.startswith(PATCH_FOLDER + "/") or name.suffix.lower() != ".xaml":
            raise WorkshopError("Only GUI XAML patches can use Patches/")
    elif name.parts[0] == "Locales":
        if (len(name.parts) != 3 or name.parts[2] != "crusader.txt" or
                not re.fullmatch(r"[a-z]{2}-[A-Z]{2}", name.parts[1])):
            raise WorkshopError("Only Locales/xx-XX/crusader.txt is supported")
    elif relative.startswith("Override/Assets/GUI/Video/"):
        if name.suffix.lower() != ".webm":
            raise WorkshopError("Only WebM video is supported in the menu video directory")
    elif (name.suffix.lower() not in {".png", ".jpg", ".jpeg", ".dds", ".xaml", ".json"}
          or not any(relative.startswith(prefix + "/") for prefix in CATEGORIES.values())):
        raise WorkshopError("Unsupported HUD/menu resource path")
    return name


def _existing(root: Path, relative: str, *, patch: bool = False) -> Path:
    rel = _relative(relative, patch=patch)
    path = root.joinpath(*rel.parts)
    if not path.is_file() or _linked(path) or path.resolve() != path:
        raise WorkshopError("Asset missing or symlinked")
    return path


def filename(value: str) -> str:
    """Make a safe human-readable PNG resource name (without hidden rewrites)."""
    if not isinstance(value, str):
        raise WorkshopError("Image name is required")
    if ("/" in value or "\\" in value or ":" in value or
            value.startswith(".") or value.strip() != value):
        raise WorkshopError("Unsafe image/resource name")
    candidate = _SAFE_NAME.sub("_", value.strip())
    candidate = candidate.strip(" .")
    if (not candidate or len(candidate) > 85 or
            candidate.casefold() in {"con", "nul", "prn", "aux"} or
            candidate.startswith(".") or _windows_reserved_name(candidate)):
        raise WorkshopError("Unsafe PNG image name")
    if candidate.lower().endswith(".png"):
        candidate = candidate[:-4]
    if not candidate or candidate in {".", ".."}:
        raise WorkshopError("Invalid PNG image name")
    return candidate + ".png"


def _image_png(source: Path) -> bytes:
    if _linked(source) or not source.is_file():
        raise WorkshopError("Image source missing or symlinked")
    if source.suffix.casefold() not in _ALLOWED_SOURCE:
        raise WorkshopError("Only PNG, JPEG and WebP images can be imported")
    before = source.stat()
    if before.st_size > _MAX_SOURCE:
        raise WorkshopError("Source image exceeds 128 MiB")
    try:
        with Image.open(source) as src:
            if (src.width <= 0 or src.height <= 0 or
                    src.width > 16384 or src.height > 16384 or
                    src.width * src.height > _MAX_PIXELS):
                raise WorkshopError("Invalid image dimensions")
            image = ImageOps.exif_transpose(src).convert("RGBA")
            out = BytesIO()
            image.save(out, "PNG")
            data = out.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise WorkshopError("Cannot decode image") from exc
    after = source.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise WorkshopError("Image changed during import")
    return data


def _write_new(path: Path, data: bytes | Path) -> None:
    # Never follow a user-created symlink in the destination parent chain.
    node = path.parent
    work = WORK.resolve()
    if not path.resolve(strict=False).is_relative_to(work):
        raise WorkshopError("Output escapes the work directory")
    while node != work and node != node.parent:
        if _linked(node):
            raise WorkshopError("Linked parent directory is unsafe")
        node = node.parent
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or _linked(path):
        raise WorkshopError(f"Existing files are never replaced: {path.name}")
    fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=".sprite-suite-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as stream:
            if isinstance(data, Path):
                before = data.stat()
                with data.open("rb") as source:
                    shutil.copyfileobj(source, stream, length=1024 * 1024)
                after = data.stat()
                if ((before.st_size, before.st_mtime_ns) !=
                    (after.st_size, after.st_mtime_ns) or stream.tell() != before.st_size):
                    raise WorkshopError("Quelldatei wurde beim Kopieren geändert")
            else:
                stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        # Publish without replacement even if another process created the
        # destination after the existence check. Windows rename also works on exFAT.
        if os.name == "nt":
            os.rename(temp_name, path)
        else:
            os.link(temp_name, path)
    finally:
        Path(temp_name).unlink(missing_ok=True)


def _metadata_dir(root: Path) -> Path:
    """Return the relocatable metadata folder; preserve legacy files intact.

    The directory identifier uses the project path relative to work/.
    Legacy absolute-path metadata is copied and verified on first access;
    game files and user artwork are never touched.
    """
    from hud_menu_metadata_paths import metadata_dir
    return metadata_dir(root, work=WORK, folder=BASELINES,
                        sha=_sha, error=WorkshopError)


def _baseline(root: Path, relative: str) -> tuple[Path, Path]:
    token = _sha(relative.encode("utf-8"))
    baseline_dir = _metadata_dir(root) / "import-baselines"
    # Use a stable, compact 128-bit filename on every machine, not only when
    # the current installation path happens to be long. This preserves the
    # same baseline filenames when an editable project ZIP is relocated.
    # Keep existing 64-character filenames readable without modifying them.
    legacy = (baseline_dir / (token + ".png"),
              baseline_dir / (token + ".json"))
    if any(path.exists() or _linked(path) for path in legacy):
        return legacy
    short = token[:32]
    return baseline_dir / (short + ".png"), baseline_dir / (short + ".json")


def _record_new(root: Path, relative: str, png: bytes, *, source: str) -> Path:
    file = root.joinpath(*_relative(relative).parts)
    backup, meta = _baseline(root, relative)
    if backup.exists() or meta.exists() or file.exists():
        raise WorkshopError("A resource or its baseline already exists")
    _write_new(backup, png)
    try:
        record = {"schema": "sprite-suite.hud-menu-workspace.v1",
                  "resource": relative, "baseline_sha256": _sha(png),
                  "source_label": source}
        _write_new(meta, (json.dumps(record, ensure_ascii=False, indent=2) + "\n").encode())
        try:
            _write_new(file, png)
        except Exception:
            meta.unlink(missing_ok=True)
            raise
    except Exception:
        backup.unlink(missing_ok=True)
        raise
    return file


def import_image(
    source: Path | str, *,
    folder: str = "Menüs / UI-Bilder",
    name: str | None = None,
    project: Path | str = DEFAULT,
) -> Path:
    root = workspace(project, create=True)
    if folder not in CATEGORIES:
        raise WorkshopError("Unknown editor asset category")
    src = Path(source)
    # A cloned/work copy can be imported; the source is never modified.
    base = filename(name if name is not None else src.stem)
    relative = CATEGORIES[folder] + "/" + base
    return _record_new(root, relative, _image_png(src), source=src.name)


def duplicate_image(
    relative: str, *, name: str, folder: str,
    project: Path | str = DEFAULT,
) -> Path:
    """Copy a user-edited PNG to a new key, without modifying its source."""
    root = workspace(project)
    if folder not in CATEGORIES:
        raise WorkshopError("Unknown target asset category")
    source = _existing(root, relative)
    if source.suffix.lower() != ".png":
        raise WorkshopError("Only bitmaps can be duplicated")
    # Validate the edited image before making a separate source snapshot.
    data = _image_png(source)
    target = CATEGORIES[folder] + "/" + filename(name)
    return _record_new(root, target, data, source="copy of " + relative)


def create_image(
    name: str, width: int, height: int, *,
    folder: str = "Menüs / UI-Bilder",
    project: Path | str = DEFAULT,
) -> Path:
    root = workspace(project, create=True)
    if folder not in CATEGORIES:
        raise WorkshopError("Unknown editor asset category")
    if (type(width) is not int or type(height) is not int or
            not 1 <= width <= 4096 or not 1 <= height <= 4096 or
            width * height > _MAX_PIXELS):
        raise WorkshopError("New bitmap dimensions must be 1–4096 px")
    output = BytesIO()
    Image.new("RGBA", (width, height), (0, 0, 0, 0)).save(output, "PNG")
    return _record_new(root, CATEGORIES[folder] + "/" + filename(name),
                       output.getvalue(), source="new transparent image")


def import_patch(
    source: Path | str, *, name: str | None = None,
    target_document: str | None = None,
    project: Path | str = DEFAULT,
) -> Path:
    root = workspace(project, create=True)
    src = Path(source)
    if not src.is_file() or _linked(src) or src.suffix.lower() != ".xaml":
        raise WorkshopError("Please choose a regular XAML patch")
    if src.stat().st_size > 2 * 1024 * 1024:
        raise WorkshopError("XAML patch exceeds 2 MiB")
    from se_asset_package import _check_xml
    _check_xml(src, patch=True)
    candidate = target_document if target_document is not None else (name or src.name)
    if not candidate.endswith(".xaml") or candidate.startswith("."):
        raise WorkshopError("XAML patch name must end with .xaml")
    rel = PATCH_FOLDER + "/" + candidate
    _relative(rel, patch=True)
    dest = root / rel
    _write_new(dest, src.read_bytes())
    return dest


def import_media(
    source: Path | str, *, resource: str, project: Path | str = DEFAULT,
) -> Path:
    """Import Origins media/localization with original resource hierarchy.

    Accept only Script Extender menu WebM and locale files. No transparent
    LFS pointers, symlinks, or shared-game modifications are allowed.
    """
    root = workspace(project, create=True)
    src = Path(source)
    if not src.is_file() or _linked(src) or src.stat().st_size > 256 * 1024**2:
        raise WorkshopError("Invalid or oversized media source")
    relative = _relative(resource).as_posix()
    from se_asset_package import _validate_asset
    _validate_asset(src, relative)
    before = src.stat()
    blob = src.read_bytes()
    after = src.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise WorkshopError("Media changed during import")
    dest = root / relative
    _write_new(dest, blob)
    return dest


def import_mod_file(source: Path, relative: str, *, project: Path | str = DEFAULT) -> Path:
    """Copy arbitrary bytes to the selected project-relative package path."""
    root = workspace(project, create=True)
    target = root.joinpath(*mod_file_path(relative).parts)
    source = Path(source).resolve(strict=True)
    if not source.is_file():
        raise WorkshopError("Quelle ist keine reguläre Datei")
    _write_new(target, source)
    return target


def mod_file_path(relative: str) -> PurePosixPath:
    from se_asset_package import AssetModError, mod_relative_path

    try:
        return mod_relative_path(relative)
    except AssetModError as exc:
        raise WorkshopError(str(exc)) from exc


def list_assets(project: Path | str = DEFAULT, *, include_mod_files: bool = False) -> list[WorkshopAsset]:
    root = workspace(project, create=True)
    results = []
    folders = (root,) if include_mod_files else (
        root / base for base in [*CATEGORIES.values(), PATCH_FOLDER, *MEDIA_FOLDERS]
    )
    for parent in folders:
        if not parent.exists():
            continue
        if _linked(parent):
            raise WorkshopError(f"Asset directory is symlinked: {parent}")
        for entry in sorted(parent.rglob("*")):
            if _linked(entry):
                raise WorkshopError(f"Linked asset not allowed: {entry}")
            if not entry.is_file():
                continue
            rel = entry.relative_to(root).as_posix()
            try:
                _relative(rel, patch=rel.startswith("Patches/"))
            except WorkshopError:
                mod_file_path(rel)
                if include_mod_files:
                    results.append(WorkshopAsset(
                        relative_path=rel, name=entry.name, kind="Mod-Datei",
                        status="Ohne Importbasis", size=entry.stat().st_size,
                        baseline_path=None, path=entry,
                    ))
                continue
            original, meta = _baseline(root, rel)
            if original.is_file() and meta.is_file():
                record = json.loads(meta.read_text("utf8"))
                expected = record.get("baseline_sha256")
                if (record.get("resource") != rel or _sha(original.read_bytes()) != expected):
                    raise WorkshopError(f"Corrupt baseline for {rel}")
                status = "Unverändert" if _sha(entry.read_bytes()) == expected else "Bearbeitet"
                baseline = original
            else:
                status, baseline = "Ohne Importbasis", None
            kind = "XAML-Patch" if rel.startswith("Patches/") else (
                "Menüvideo" if rel.startswith("Override/Assets/GUI/Video/") else
                "Sprache" if rel.startswith("Locales/") else next(
                (label for label,prefix in CATEGORIES.items() if rel.startswith(prefix+"/")),
                "Sonstiges"))
            results.append(WorkshopAsset(
                relative_path=rel,name=entry.name,kind=kind,status=status,
                size=entry.stat().st_size,baseline_path=baseline,path=entry))
    return results


def restore_image(relative: str, *, project: Path | str = DEFAULT) -> Path:
    root = workspace(project)
    file = _existing(root, relative)
    backup, meta = _baseline(root, relative)
    if not backup.is_file() or not meta.is_file():
        raise WorkshopError("No checked original copy for this image")
    record = json.loads(meta.read_text("utf8"))
    data = backup.read_bytes()
    if record.get("resource") != relative or _sha(data) != record.get("baseline_sha256"):
        raise WorkshopError("Source baseline SHA-256 is invalid")
    before = file.read_bytes()
    if before == data:
        return file
    # Keep the user's edited file in a non-package backup folder.
    history = _metadata_dir(root) / "revisions"
    history.mkdir(parents=True, exist_ok=True)
    # Compact stable IDs keep private revision history inside Windows MAX_PATH
    # even when the Suite is installed under a nested user directory.
    revision = history / (_sha(relative.encode())[:32] + "-" + _sha(before)[:16] + ".png")
    if not revision.exists():
        _write_new(revision, before)
    write_png(relative, data, project=root, expected_sha256=_sha(before))
    return file


def write_png(
    relative: str, png: bytes, *, project: Path | str = DEFAULT,
    expected_sha256: str,
) -> Path:
    """Save atomically only when the editor's original on-disk SHA still matches."""
    root = workspace(project)
    path = _existing(root, relative)
    if path.suffix.lower() != ".png":
        raise WorkshopError("Pixel editor only writes PNGs")
    if _sha(path.read_bytes()) != expected_sha256:
        raise WorkshopError("File changed externally; reload before overwriting")
    try:
        with Image.open(BytesIO(png)) as image:
            image.verify()
    except (OSError, UnidentifiedImageError) as exc:
        raise WorkshopError("Invalid edited PNG") from exc
    fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=".hud-edit-", suffix=".png")
    try:
        with os.fdopen(fd, "wb") as dst:
            dst.write(png)
            dst.flush()
            os.fsync(dst.fileno())
        if _linked(path) or _sha(path.read_bytes()) != expected_sha256:
            raise WorkshopError("Image changed while saving")
        os.replace(temp_name, path)
    finally:
        Path(temp_name).unlink(missing_ok=True)
    return path


def audit_assets(project: Path | str = DEFAULT) -> dict:
    """Run the exact version-neutral asset builder's validators, no package write."""
    from se_asset_package import _discover
    root = workspace(project)
    files = _discover(root)
    return {"assets": len(files), "total_bytes": sum(row[2] for row in files),
            "bytes_sha256": _sha(json.dumps(
                [(row[0],row[3]) for row in files],separators=(",",":")).encode())}

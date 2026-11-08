"""Standalone PNG + XAML atlas workspace; no game installation is required.

The original PNG and XAML are immutable, hash-pinned workspace snapshots.
History stores rectangular RGBA replacement patches, applied in order without
alpha blending: transparent pixels (including their RGB) replace pixels too.
Overlapping resources and aliases are legal; the last applied patch wins.
Preview decodes only on demand and returns a crop, never a cached full atlas.
Pillow may transiently decode the complete PNG to service a crop. Export decodes
one complete atlas. PNG pixel values outside edited rectangles are unchanged;
PNG compression/ancillary metadata are not promised byte-identical on rebuild.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
from typing import Callable
import uuid
import warnings
from xml.etree import ElementTree as ET

from PIL import Image

from suite_windows_paths import is_link_or_reparse, safe_relative_file
from ui_atlas import read_atlas, UiAtlasError

SCHEMA = "spritesuite.ui-atlas-workspace/v1"
MAX_PIXELS = 128 * 1024 * 1024
MAX_XML_BYTES = 16 * 1024 * 1024
MANIFEST = "atlas-project.json"
Cancel = Callable[[], bool] | None


class AtlasWorkspaceError(ValueError):
    def __init__(self, code: str, message: str, **details: object):
        super().__init__(message)
        self.code = code
        self.details = details


def _fail(code: str, message: str, **details: object):
    raise AtlasWorkspaceError(code, message, **details)


def _cancel(cancel: Cancel) -> None:
    if cancel is not None and cancel():
        _fail("cancelled", "Operation cancelled before publication")


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _path(value: str | Path) -> Path:
    path = Path(value).absolute()
    for part in (path, *path.parents):
        if is_link_or_reparse(part):
            _fail("unsafe_path", "Linked paths are not accepted", path=str(path))
    return path.resolve(strict=False)


def _regular(value: str | Path) -> Path:
    path = _path(value)
    if not path.is_file():
        _fail("missing_file", "Expected an existing regular file", path=str(path))
    return path


def _png(path: Path) -> Image.Image:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)
            image = Image.open(path)
        if image.format != "PNG":
            image.close()
            _fail("invalid_png", "Source must be a PNG", path=str(path))
        if image.width <= 0 or image.height <= 0 or image.width * image.height > MAX_PIXELS:
            image.close()
            _fail("pixel_budget", "PNG exceeds the 128 Mi-pixel budget", path=str(path))
        return image
    except AtlasWorkspaceError:
        raise
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        _fail("invalid_png", "PNG cannot be decoded", path=str(path), reason=str(exc))


def _rgba(path: Path, box: tuple[int, int, int, int] | None = None) -> Image.Image:
    try:
        with _png(path) as image:
            # Crop before RGBA conversion avoids a second full RGBA allocation.
            return (image.crop(box) if box is not None else image).convert("RGBA")
    except (OSError, ValueError) as exc:
        if isinstance(exc, AtlasWorkspaceError):
            raise
        _fail("invalid_png", "PNG pixel data cannot be decoded", path=str(path), reason=str(exc))


def preview_png(path: str | Path, max_size: tuple[int, int] = (512, 384)) -> Image.Image:
    """Validate a replacement PNG using the atlas budget; return display RGBA.

    Only this returned thumbnail is resized. Replacement/export pixels continue
    to come from the full-resolution source and the requested explicit fit.
    """
    if len(max_size) != 2 or any(type(value) is not int or value <= 0 for value in max_size):
        _fail("invalid_arguments", "Thumbnail dimensions must be positive integers")
    with _png(_regular(path)) as image:
        image.thumbnail(max_size, Image.Resampling.NEAREST)
        return image.convert("RGBA")


def _tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _key(element: ET.Element) -> str | None:
    return element.get("{http://schemas.microsoft.com/winfx/2006/xaml}Key") or element.get("Key")


def _parse_entries(xaml: Path, png_name: str, width: int, height: int, atlas_key: str | None = None) -> tuple[str, str, list[dict], list[dict]]:
    raw = xaml.read_bytes()
    if len(raw) > MAX_XML_BYTES:
        _fail("invalid_xml", "XAML exceeds the 16 MiB budget")
    # Detect declarations even in UTF-16/32 input before invoking any XML parser.
    if re.search(br"<!\s*(?:DOCTYPE|ENTITY)\b", raw.replace(b"\0", b""), re.I):
        _fail("unsafe_xml", "DOCTYPE and ENTITY declarations are not allowed")
    try:
        root = ET.fromstring(raw)
    except (ET.ParseError, ValueError) as exc:
        _fail("invalid_xml", "XAML cannot be parsed", reason=str(exc))
    sheets: dict[str, str] = {}
    for node in root.iter():
        if _tag(node) == "BitmapImage":
            key, uri = _key(node), node.get("UriSource")
            if not key or not uri or key in sheets:
                _fail("invalid_xml", "BitmapImage requires a unique Key and UriSource")
            # URI values are labels only. Nothing here fetches or evaluates XAML.
            uri_check = uri.strip()
            if re.match(r"^[a-z][a-z0-9+.-]*:", uri_check, re.I) or uri_check.startswith(("//", "\\\\")):
                _fail("unsafe_xml", "Remote or absolute URI sources are not accepted", uri=uri)
            sheets[key] = uri
    matches = ([atlas_key] if atlas_key in sheets else []) if atlas_key is not None else [
        key for key, uri in sheets.items() if uri.replace("\\", "/").split("/")[-1].casefold() == png_name.casefold()]
    if len(matches) != 1:
        _fail("atlas_selection", "PNG filename must select exactly one BitmapImage", png=png_name, matches=matches)
    selected = matches[0]
    # Reuse the existing strict TexturePacker parser for its normal format. It
    # assumes the first sheet and rejects sanitized filename collisions, neither
    # assumption applies to multi-atlas workspaces (patch names use UUIDs).
    legacy_crops = None
    if len(sheets) == 1:
        try:
            _, legacy_crops = read_atlas(xaml)
        except UiAtlasError:
            pass  # The binding-aware checks below are authoritative here.
    entries = []
    seen: set[str] = set()
    for node in root.iter():
        if _tag(node) != "CroppedBitmap":
            continue
        key, source, rect = _key(node), node.get("Source"), node.get("SourceRect")
        if not key or key in seen:
            _fail("invalid_xml", "CroppedBitmap keys must be present and unique", key=key)
        seen.add(key)
        binding = re.fullmatch(r"\{\s*(?:StaticResource|DynamicResource)\s+([^{}]+?)\s*\}", source or "")
        if not binding or binding.group(1) not in sheets:
            _fail("invalid_xml", "CroppedBitmap must refer to a known BitmapImage", key=key)
        if binding.group(1) != selected:
            continue
        parts = re.split(r"\s*[,;]\s*", rect.strip()) if rect else []
        if len(parts) != 4 or any(not re.fullmatch(r"[+-]?\d+", item) for item in parts):
            _fail("invalid_rect", "SourceRect must contain four integers", key=key)
        x, y, w, h = map(int, parts)
        if min(x, y) < 0 or min(w, h) <= 0 or x + w > width or y + h > height:
            _fail("invalid_rect", "SourceRect lies outside its PNG", key=key)
        entries.append(dict(key=key, x=x, y=y, width=w, height=h))
    if not entries:
        _fail("no_entries", "Selected PNG has no CroppedBitmap entries")
    if legacy_crops is not None:
        legacy_entries = [dict(key=crop.key, x=crop.x, y=crop.y, width=crop.width, height=crop.height) for crop in legacy_crops]
        if legacy_entries == entries:
            entries = legacy_entries
    other = [dict(atlas_key=key, uri=uri, code="unprovided_atlas_source") for key, uri in sheets.items() if key != selected]
    return selected, sheets[selected], entries, other


def _box(entry: dict) -> tuple[int, int, int, int]:
    return entry["x"], entry["y"], entry["x"] + entry["width"], entry["y"] + entry["height"]


def _json_bytes(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


@contextmanager
def _commit_lock(workspace: Path):
    """OS-released lock closes the revision-check/replace race across processes."""
    path = _path(workspace / "atlas-project.lock")
    with path.open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            _fail("workspace_busy", "Another operation is committing this workspace; retry after it finishes")
        try:
            yield
        finally:
            stream.seek(0)
            try:
                if os.name == "nt":
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass  # Closing the file also releases the OS lock.


class AtlasProject:
    """One immutable atlas snapshot with autosaved, persistent ROI undo/redo."""

    def __init__(self, workspace: Path, manifest: dict):
        self.workspace = workspace
        self._manifest = manifest
        self._manifest_sha = _sha(workspace / MANIFEST)

    @classmethod
    def create(cls, png: str | Path, xaml: str | Path, workspace: str | Path, *, cancel: Cancel = None, atlas_key: str | None = None) -> "AtlasProject":
        _cancel(cancel)
        png, xaml, workspace = _regular(png), _regular(xaml), _path(workspace)
        if workspace.exists():
            _fail("already_exists", "Choose a new workspace directory", path=str(workspace))
        if not workspace.parent.is_dir():
            _fail("missing_directory", "Workspace parent directory does not exist")
        with _png(png) as image:
            width, height = image.size
        selected, sheet, entries, unresolved = _parse_entries(xaml, png.name, width, height, atlas_key)
        staging = Path(tempfile.mkdtemp(prefix="atlas-create-", dir=workspace.parent))
        try:
            (staging / "source").mkdir()
            (staging / "patches").mkdir()
            sources = {}
            for kind, source in (("png", png), ("xaml", xaml)):
                _cancel(cancel)
                digest = _sha(source)
                relative = f"source/atlas.{kind}"
                shutil.copyfile(source, staging / relative)
                if _sha(staging / relative) != digest or _sha(source) != digest:
                    _fail("source_changed", "Source changed while it was copied")
                sources[kind] = dict(file=relative, sha256=digest, original_path=str(source))
            # Decode snapshot once to catch truncated/corrupt PNG data at import.
            try:
                with _png(staging / sources["png"]["file"]) as image:
                    image.load()
            except OSError as exc:
                _fail("invalid_png", "PNG pixel data cannot be decoded", reason=str(exc))
            manifest = dict(schema=SCHEMA, width=width, height=height, sheet=sheet, atlas_key=selected, unresolved_sources=unresolved,
                            sources=sources, entries=entries, history=[], cursor=0, revision=uuid.uuid4().hex)
            (staging / MANIFEST).write_bytes(_json_bytes(manifest))
            _cancel(cancel)
            if workspace.exists():
                _fail("already_exists", "Workspace already exists")
            os.rename(staging, workspace)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
        return cls.open(workspace)

    @classmethod
    def open(cls, workspace: str | Path) -> "AtlasProject":
        workspace = _path(workspace)
        try:
            manifest_path = _regular(workspace / MANIFEST)
            if manifest_path.stat().st_size > MAX_XML_BYTES:
                _fail("invalid_manifest", "Manifest is too large")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            if isinstance(exc, AtlasWorkspaceError):
                raise
            _fail("invalid_manifest", "Cannot read atlas workspace manifest", reason=str(exc))
        project = cls(workspace, manifest)
        project._verify()
        return project

    def _managed(self, relative: str) -> Path:
        try:
            return safe_relative_file(self.workspace, relative)
        except (ValueError, TypeError) as exc:
            _fail("unsafe_path", "Manifest contains an unsafe path", reason=str(exc))

    def _verify(self) -> None:
        try:
            m = self._manifest
            if not isinstance(m, dict) or m.get("schema") != SCHEMA:
                _fail("invalid_manifest", "Unsupported atlas workspace schema")
            if _sha(_regular(self.workspace / MANIFEST)) != self._manifest_sha:
                _fail("stale_workspace", "Workspace was modified by another session; reopen it")
            if any(type(m[k]) is not int or m[k] <= 0 for k in ("width", "height")) or m["width"] * m["height"] > MAX_PIXELS:
                _fail("invalid_manifest", "Invalid atlas dimensions")
            if not isinstance(m["history"], list) or type(m["cursor"]) is not int or not 0 <= m["cursor"] <= len(m["history"]):
                _fail("invalid_manifest", "Invalid history cursor")
            if not isinstance(m["revision"], str) or not re.fullmatch(r"[0-9a-f]{32}", m["revision"]):
                _fail("invalid_manifest", "Invalid revision token")
            if set(m["sources"]) != {"png", "xaml"}:
                _fail("invalid_manifest", "Workspace requires exactly one PNG and XAML snapshot")
            for kind, source in m["sources"].items():
                if source["file"] != f"source/atlas.{kind}":
                    _fail("unsafe_path", "Source snapshot path changed")
                if not isinstance(source["original_path"], str) or not Path(source["original_path"]).is_absolute():
                    _fail("invalid_manifest", "Invalid original source path")
                path = _regular(self._managed(source["file"]))
                if _sha(path) != source["sha256"]:
                    _fail("integrity_error", "Workspace source hash changed", file=source["file"])
            with _png(self._managed(m["sources"]["png"]["file"])) as image:
                if image.size != (m["width"], m["height"]):
                    _fail("integrity_error", "Source dimensions changed")
            atlas_key, sheet, parsed, unresolved = _parse_entries(self._managed(m["sources"]["xaml"]["file"]),
                                       Path(m["sources"]["png"]["original_path"]).name, m["width"], m["height"], m["atlas_key"])
            if parsed != m["entries"] or sheet != m["sheet"] or unresolved != m["unresolved_sources"]:
                _fail("integrity_error", "Manifest rectangles disagree with source XAML")
            by_key = {entry["key"]: entry for entry in parsed}
            for entry in m["entries"]:
                if any(type(entry[field]) is not int for field in ("x", "y", "width", "height")):
                    _fail("invalid_manifest", "Entry rectangles require integer coordinates")
            for patch in m["history"]:
                if not isinstance(patch["file"], str) or not re.fullmatch(r"patches/[0-9a-f]{32}\.png", patch["file"]):
                    _fail("unsafe_path", "History patch path changed")
                if patch["key"] not in by_key or patch["rect"] != by_key[patch["key"]]:
                    _fail("invalid_manifest", "History target rectangle changed")
                if any(type(patch["rect"][field]) is not int for field in ("x", "y", "width", "height")):
                    _fail("invalid_manifest", "History rectangles require integer coordinates")
                path = _regular(self._managed(patch["file"]))
                if _sha(path) != patch["sha256"]:
                    _fail("integrity_error", "Workspace patch hash changed", file=patch["file"])
                with _png(path) as image:
                    rect = patch["rect"]
                    if image.size != (rect["width"], rect["height"]) or image.mode != "RGBA":
                        _fail("integrity_error", "Workspace patch dimensions or mode changed")
        except (KeyError, TypeError, AttributeError, OSError) as exc:
            _fail("invalid_manifest", "Malformed workspace manifest", reason=str(exc))

    @property
    def entries(self) -> list[dict]:
        return copy.deepcopy(self._manifest["entries"])

    def info(self) -> dict:
        self._verify()
        m = self._manifest
        source_warnings = []
        for kind, source in m["sources"].items():
            try:
                original = _regular(source["original_path"])
                if _sha(original) != source["sha256"]:
                    source_warnings.append(dict(code="source_changed", source=kind))
            except (AtlasWorkspaceError, OSError):
                source_warnings.append(dict(code="source_unavailable", source=kind))
        return dict(schema=SCHEMA, workspace=str(self.workspace), width=m["width"], height=m["height"],
                    sheet=m["sheet"], atlas_key=m["atlas_key"], xaml_name=Path(m["sources"]["xaml"]["original_path"]).name,
                    source_xaml=str(self._managed(m["sources"]["xaml"]["file"])),
                    entry_count=len(m["entries"]), history_count=len(m["history"]),
                    cursor=m["cursor"], can_undo=m["cursor"] > 0, can_redo=m["cursor"] < len(m["history"]),
                    revision=m["revision"], currentRevisionToken=m["revision"], sources=copy.deepcopy(m["sources"]),
                    warnings=source_warnings + copy.deepcopy(m["unresolved_sources"]))

    def _expected(self, expected_revision: str | None) -> None:
        self._verify()
        if expected_revision is not None and expected_revision != self._manifest["revision"]:
            _fail("stale_revision", "Atlas revision changed; inspect current state before editing")

    def _entry(self, key: str) -> dict:
        for entry in self._manifest["entries"]:
            if entry["key"] == key:
                return entry
        _fail("unknown_key", "Atlas entry does not exist", key=key)

    def original_preview(self, key: str) -> Image.Image:
        self._verify()
        return _rgba(self._managed(self._manifest["sources"]["png"]["file"]), _box(self._entry(key)))

    def preview(self, key: str) -> Image.Image:
        image = self.original_preview(key)
        target = self._entry(key)
        tx, ty, tr, tb = _box(target)
        for patch in self._manifest["history"][:self._manifest["cursor"]]:
            px, py, pr, pb = _box(patch["rect"])
            left, top, right, bottom = max(tx, px), max(ty, py), min(tr, pr), min(tb, pb)
            if left < right and top < bottom:
                with _rgba(self._managed(patch["file"]), (left - px, top - py, right - px, bottom - py)) as roi:
                    image.paste(roi, (left - tx, top - ty))
        return image

    def _save(self, manifest: dict, cancel: Cancel = None) -> None:
        self._verify()
        manifest["revision"] = uuid.uuid4().hex
        payload = _json_bytes(manifest)
        if len(payload) > MAX_XML_BYTES:
            _fail("manifest_budget", "History manifest exceeds the 16 MiB budget")
        descriptor, name = tempfile.mkstemp(prefix="atlas-save-", suffix=".tmp", dir=self.workspace)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            with _commit_lock(self.workspace):
                _cancel(cancel)
                # Check under the OS lock before replacing state; stale handles
                # cannot silently discard a concurrent GUI/CLI action.
                if _sha(self.workspace / MANIFEST) != self._manifest_sha:
                    _fail("stale_workspace", "Workspace was modified by another session")
                os.replace(name, self.workspace / MANIFEST)
                self._manifest = manifest
                self._manifest_sha = hashlib.sha256(payload).hexdigest()
        finally:
            if os.path.exists(name):
                os.unlink(name)

    @staticmethod
    def _fit(image: Image.Image, size: tuple[int, int], fit: str) -> Image.Image:
        if fit not in {"exact", "contain", "stretch"}:
            _fail("invalid_fit", "fit must be exact, contain or stretch")
        if image.size == size:
            return image.copy()
        if fit == "exact":
            _fail("size_mismatch", "Replacement size must equal the fixed target rectangle", source=list(image.size), target=list(size))
        if fit == "stretch":
            return image.resize(size, Image.Resampling.NEAREST)
        ratio = min(size[0] / image.width, size[1] / image.height)
        resized_size = (max(1, min(size[0], int(image.width * ratio))), max(1, min(size[1], int(image.height * ratio))))
        with image.resize(resized_size, Image.Resampling.NEAREST) as resized:
            result = Image.new("RGBA", size, (0, 0, 0, 0))
            result.paste(resized, ((size[0] - resized.width) // 2, (size[1] - resized.height) // 2))
        return result

    def _apply(self, key: str, image: Image.Image, fit: str, provenance: dict, *, operation: str, cancel: Cancel) -> dict:
        self._verify()
        _cancel(cancel)
        rect = self._entry(key)
        fitted = self._fit(image, (rect["width"], rect["height"]), fit)
        relative = f"patches/{uuid.uuid4().hex}.png"
        path = self._managed(relative)
        try:
            fitted.save(path, format="PNG")
            manifest = copy.deepcopy(self._manifest)
            patch = dict(id=uuid.uuid4().hex, operation=operation, key=key, rect=copy.deepcopy(rect),
                         file=relative, sha256=_sha(path), fit=fit, provenance=provenance)
            manifest["history"] = manifest["history"][:manifest["cursor"]] + [patch]
            manifest["cursor"] = len(manifest["history"])
            self._save(manifest, cancel)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        finally:
            fitted.close()
        return dict(ok=True, operation=operation, key=key, revision=self._manifest["revision"], cursor=self._manifest["cursor"])

    def replace(self, key: str, source_png: str | Path, fit: str = "exact", *, cancel: Cancel = None, expected_revision: str | None = None) -> dict:
        self._expected(expected_revision)
        _cancel(cancel)
        source = _regular(source_png)
        digest = _sha(source)
        with _rgba(source) as image:
            if _sha(source) != digest:
                _fail("source_changed", "Replacement PNG changed while being read")
            return self._apply(key, image, fit, dict(kind="png", path=str(source), sha256=digest), operation="replace", cancel=cancel)

    def replace_from(self, key: str, source_project: "AtlasProject | str | Path", source_key: str, fit: str = "exact", *, cancel: Cancel = None, expected_revision: str | None = None) -> dict:
        self._expected(expected_revision)
        _cancel(cancel)
        donor = source_project if isinstance(source_project, AtlasProject) else AtlasProject.open(source_project)
        with donor.preview(source_key) as image:
            provenance = dict(kind="atlas", workspace=str(donor.workspace), key=source_key, rect=copy.deepcopy(donor._entry(source_key)),
                              revision=donor._manifest["revision"], source_sha256=donor._manifest["sources"]["png"]["sha256"],
                              rgba_sha256=hashlib.sha256(image.tobytes()).hexdigest())
            return self._apply(key, image, fit, provenance, operation="replace_from", cancel=cancel)

    def restore(self, key: str, *, expected_revision: str | None = None, cancel: Cancel = None) -> dict:
        self._expected(expected_revision)
        _cancel(cancel)
        with self.original_preview(key) as image:
            return self._apply(key, image, "exact", dict(kind="original", sha256=self._manifest["sources"]["png"]["sha256"]), operation="restore", cancel=cancel)

    def _history(self, step: int, cancel: Cancel = None) -> dict:
        _cancel(cancel)
        self._verify()
        cursor = self._manifest["cursor"] + step
        if not 0 <= cursor <= len(self._manifest["history"]):
            _fail("no_undo" if step < 0 else "no_redo", "No history action available")
        manifest = copy.deepcopy(self._manifest)
        manifest["cursor"] = cursor
        self._save(manifest, cancel)
        return dict(ok=True, operation="undo" if step < 0 else "redo", cursor=cursor, revision=manifest["revision"])

    def undo(self, *, expected_revision: str | None = None, cancel: Cancel = None) -> dict:
        self._expected(expected_revision)
        return self._history(-1, cancel)

    def redo(self, *, expected_revision: str | None = None, cancel: Cancel = None) -> dict:
        self._expected(expected_revision)
        return self._history(1, cancel)

    def _export(self, output: str | Path, image: Image.Image, cancel: Cancel, key: str | None = None) -> dict:
        output = _path(output)
        if output.suffix.lower() != ".png":
            _fail("invalid_output", "Export filename must end in .png")
        if output.exists():
            _fail("already_exists", "Export never overwrites an existing file", path=str(output))
        if output.is_relative_to(self.workspace) and not output.is_relative_to(self.workspace / "exports"):
            _fail("unsafe_path", "Export outside the managed workspace")
        if not output.parent.is_dir():
            _fail("missing_directory", "Output parent directory does not exist")
        descriptor, name = tempfile.mkstemp(prefix="atlas-export-", suffix=".tmp", dir=output.parent)
        os.close(descriptor)
        try:
            image.save(name, format="PNG")
            digest = _sha(Path(name))
            self._verify()
            _cancel(cancel)
            # Hard-link publication is atomic and fails if another file won the
            # destination name. The temporary is always on the same filesystem.
            try:
                os.link(name, output)
            except FileExistsError:
                _fail("already_exists", "Export target already exists", path=str(output))
            return dict(ok=True, output=str(output), sha256=digest, width=image.width, height=image.height,
                        key=key, revision=self._manifest["revision"])
        finally:
            Path(name).unlink(missing_ok=True)

    def export_png(self, output: str | Path, *, cancel: Cancel = None) -> dict:
        self._verify()
        _cancel(cancel)
        with _rgba(self._managed(self._manifest["sources"]["png"]["file"])) as image:
            for patch in self._manifest["history"][:self._manifest["cursor"]]:
                _cancel(cancel)
                with _rgba(self._managed(patch["file"])) as roi:
                    image.paste(roi, (patch["rect"]["x"], patch["rect"]["y"]))
            return self._export(output, image, cancel)

    def export_crop(self, key: str, output: str | Path, *, cancel: Cancel = None) -> dict:
        _cancel(cancel)
        with self.preview(key) as image:
            return self._export(output, image, cancel, key)

    def export_pair(self, output_dir: str | Path, *, cancel: Cancel = None) -> dict:
        """Publish a new PNG/XAML directory and provenance receipt as one unit.

        Additional BitmapImage resources are reported, never fetched or invented.
        Relative URI subdirectories are retained so the unchanged XAML resolves
        the selected PNG. The ordinary flat atlas produces two sibling files.
        """
        self._verify()
        _cancel(cancel)
        destination = _path(output_dir)
        if destination.exists():
            _fail("already_exists", "Choose a new export directory")
        if destination.is_relative_to(self.workspace) and not destination.is_relative_to(self.workspace / "exports"):
            _fail("unsafe_path", "Export outside managed source and history directories")
        if not destination.parent.is_dir():
            _fail("missing_directory", "Export parent directory does not exist")
        staging = Path(tempfile.mkdtemp(prefix="atlas-pair-", dir=destination.parent))
        try:
            uri = self._manifest["sheet"].replace("\\", "/")
            try:
                png = safe_relative_file(staging, uri, allowed_suffixes=frozenset({".png"}))
            except ValueError:
                _fail("unsafe_path", "Selected PNG URI cannot be safely exported", uri=uri)
            png.parent.mkdir(parents=True, exist_ok=True)
            self.export_png(png, cancel=cancel)
            xaml_name = Path(self._manifest["sources"]["xaml"]["original_path"]).name
            xaml = safe_relative_file(staging, xaml_name)
            if xaml == png or xaml.name == "atlas-receipt.json":
                _fail("invalid_output", "Export filenames collide")
            shutil.copyfile(self._managed(self._manifest["sources"]["xaml"]["file"]), xaml)
            receipt = dict(schema=SCHEMA + "/export", revision=self._manifest["revision"], atlas_key=self._manifest["atlas_key"],
                           png=dict(file=uri, sha256=_sha(png)), xaml=dict(file=xaml_name, sha256=_sha(xaml)),
                           sources=copy.deepcopy(self._manifest["sources"]),
                           applied_history=copy.deepcopy(self._manifest["history"][:self._manifest["cursor"]]),
                           warnings=copy.deepcopy(self._manifest["unresolved_sources"]))
            (staging / "atlas-receipt.json").write_bytes(_json_bytes(receipt))
            receipt_sha256 = _sha(staging / "atlas-receipt.json")
            self._verify()
            _cancel(cancel)
            if destination.exists():
                _fail("already_exists", "Export directory already exists")
            os.rename(staging, destination)
            return dict(ok=True, workspace=str(self.workspace), png=str(destination / uri), xaml=str(destination / xaml_name),
                        receipt=str(destination / "atlas-receipt.json"), receipt_sha256=receipt_sha256,
                        revision=self._manifest["revision"], warnings=receipt["warnings"])
        finally:
            if staging.exists():
                shutil.rmtree(staging)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create", help="Create a new workspace from a PNG and XAML pair")
    create.add_argument("--png", type=Path, required=True)
    create.add_argument("--xaml", type=Path, required=True)
    create.add_argument("--workspace", type=Path, required=True)
    create.add_argument("--atlas-key", help="Explicit BitmapImage key when multiple bindings share a PNG filename")
    for command in ("info", "list", "crop", "replace", "replace-from", "restore", "undo", "redo", "export", "export-pair"):
        sub = commands.add_parser(command)
        sub.add_argument("--workspace", type=Path, required=True)
        if command in {"crop", "replace", "replace-from", "restore"}:
            sub.add_argument("--key", required=True)
        if command in {"crop", "export", "export-pair"}:
            sub.add_argument("--output", type=Path, required=True)
        if command in {"replace", "replace-from"}:
            sub.add_argument("--fit", choices=("exact", "contain", "stretch"), default="exact")
        if command == "replace":
            sub.add_argument("--source", type=Path, required=True)
        if command == "replace-from":
            sub.add_argument("--source-workspace", type=Path, required=True)
            sub.add_argument("--source-key", required=True)
        if command in {"replace", "replace-from", "restore", "undo", "redo"}:
            sub.add_argument("--expected-revision")
        if command == "list":
            sub.add_argument("--query", default="")
            sub.add_argument("--offset", type=int, default=0)
            sub.add_argument("--limit", type=int, default=100)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "create":
            result = AtlasProject.create(args.png, args.xaml, args.workspace, atlas_key=args.atlas_key).info()
        else:
            project = AtlasProject.open(args.workspace)
            if args.command == "info":
                result = project.info()
            elif args.command == "list":
                if args.offset < 0 or not 1 <= args.limit <= 500:
                    _fail("invalid_arguments", "offset must be nonnegative; limit must be 1..500")
                entries = project.entries
                matches = [entry for entry in entries if args.query.casefold() in entry["key"].casefold()]
                end = args.offset + args.limit
                result = dict(entries=matches[args.offset:end], total=len(entries), matched=len(matches),
                              next_offset=end if end < len(matches) else None)
            elif args.command == "crop":
                result = project.export_crop(args.key, args.output)
            elif args.command == "replace":
                result = project.replace(args.key, args.source, args.fit, expected_revision=args.expected_revision)
            elif args.command == "replace-from":
                result = project.replace_from(args.key, args.source_workspace, args.source_key, args.fit, expected_revision=args.expected_revision)
            elif args.command == "restore":
                result = project.restore(args.key, expected_revision=args.expected_revision)
            elif args.command == "undo":
                result = project.undo(expected_revision=args.expected_revision)
            elif args.command == "redo":
                result = project.redo(expected_revision=args.expected_revision)
            elif args.command == "export-pair":
                result = project.export_pair(args.output)
            else:
                result = project.export_png(args.output)
        print(json.dumps(dict(ok=True, result=result), ensure_ascii=False))
        return 0
    except AtlasWorkspaceError as exc:
        print(json.dumps(dict(ok=False, error=dict(code=exc.code, message=str(exc), details=exc.details)), ensure_ascii=False))
        return 2
    except OSError as exc:
        print(json.dumps(dict(ok=False, error=dict(code="io_error", message=str(exc))), ensure_ascii=False))
        return 2


if __name__ == "__main__":
    # Native tool subprocesses and Windows shells receive the same JSON encoding.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())

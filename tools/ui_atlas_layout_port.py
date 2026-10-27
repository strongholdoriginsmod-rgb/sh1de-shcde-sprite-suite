"""Port verified UI-atlas edits between named XAML layouts.

The source store must have been produced from the supplied source export.  Only
named crops whose pixels differ from that export are copied into the target
export.  Target-only crops and unchanged target pixels therefore remain from
the new game build instead of inheriting an obsolete packed-sheet layout.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class LayoutPortError(RuntimeError):
    """The source edits cannot be mapped exactly to the target layout."""


@dataclass(frozen=True)
class Crop:
    atlas: str
    directory: str
    key: str
    filename: str
    x: int
    y: int
    width: int
    height: int
    baseline_pixels_sha256: str

    @property
    def box(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.x + self.width, self.y + self.height)


@dataclass(frozen=True)
class Atlas:
    sheet: str
    width: int
    height: int
    directory: str
    crops: dict[str, Crop]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _pixel_digest(image: Image.Image) -> str:
    rgba = image if image.mode == "RGBA" else image.convert("RGBA")
    return hashlib.sha256(rgba.tobytes()).hexdigest()


def _input_path(value: str, label: str) -> Path:
    path = Path(value)
    resolved = path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()
    if not resolved.exists():
        raise LayoutPortError(f"{label} fehlt: {resolved}")
    return resolved


def _target_export_path(value: str) -> Path:
    path = _input_path(value, "Zielexport")
    work_root = (PROJECT_ROOT / "work").resolve()
    if path == work_root or not path.is_relative_to(work_root):
        raise LayoutPortError(
            f"Zielexport muss unter {work_root} liegen, nicht {path}"
        )
    if not path.is_dir() or path.is_symlink():
        raise LayoutPortError("Zielexport ist kein regulaerer Ordner")
    return path


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise LayoutPortError(f"{label} ist nicht lesbar: {path}") from exc
    if not isinstance(value, dict):
        raise LayoutPortError(f"{label} ist kein JSON-Objekt")
    return value


def _flat_name(value: Any, label: str) -> str:
    text = str(value)
    if not text or Path(text).name != text or text in {".", ".."}:
        raise LayoutPortError(f"Unsicherer {label}: {text!r}")
    return text


def _positive_int(value: Any, label: str, *, allow_zero: bool = False) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise LayoutPortError(f"{label} ist nicht ganzzahlig") from exc
    minimum = 0 if allow_zero else 1
    if number < minimum:
        raise LayoutPortError(f"{label} ist kleiner als {minimum}")
    return number


def _digest(value: Any, label: str) -> str:
    text = str(value)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise LayoutPortError(f"{label} ist kein kleingeschriebener SHA-256")
    return text


def _load_index(root: Path, label: str) -> tuple[dict[str, Any], dict[str, Atlas]]:
    raw = _read_json(root / "index.json", f"{label}-Index")
    if raw.get("schema_version") != 1 or not isinstance(raw.get("atlases"), list):
        raise LayoutPortError(f"{label}-Index hat einen unbekannten Vertrag")
    atlases: dict[str, Atlas] = {}
    global_keys: set[str] = set()
    for atlas_raw in raw["atlases"]:
        if not isinstance(atlas_raw, dict) or not isinstance(atlas_raw.get("crops"), list):
            raise LayoutPortError(f"{label}-Atlas ist unvollstaendig")
        sheet = _flat_name(atlas_raw.get("sheet"), f"{label}-Blatt")
        directory = _flat_name(atlas_raw.get("directory"), f"{label}-Atlasordner")
        if sheet in atlases:
            raise LayoutPortError(f"{label}-Blatt ist doppelt: {sheet}")
        width = _positive_int(atlas_raw.get("sheet_width"), f"{label}/{sheet}/Breite")
        height = _positive_int(atlas_raw.get("sheet_height"), f"{label}/{sheet}/Hoehe")
        crops: dict[str, Crop] = {}
        filenames: set[str] = set()
        for crop_raw in atlas_raw["crops"]:
            if not isinstance(crop_raw, dict):
                raise LayoutPortError(f"{label}/{sheet}: Ausschnitt ist kein Objekt")
            key = str(crop_raw.get("key", ""))
            filename = _flat_name(crop_raw.get("file"), f"{label}/{sheet}/Datei")
            if not key or key in crops or key in global_keys or filename in filenames:
                raise LayoutPortError(f"{label}/{sheet}: doppelter Key/Dateiname {key!r}")
            x = _positive_int(crop_raw.get("x"), f"{label}/{key}/x", allow_zero=True)
            y = _positive_int(crop_raw.get("y"), f"{label}/{key}/y", allow_zero=True)
            crop_width = _positive_int(crop_raw.get("width"), f"{label}/{key}/Breite")
            crop_height = _positive_int(crop_raw.get("height"), f"{label}/{key}/Hoehe")
            if x + crop_width > width or y + crop_height > height:
                raise LayoutPortError(f"{label}/{key}: Ausschnitt liegt ausserhalb des Blatts")
            crop = Crop(
                atlas=sheet,
                directory=directory,
                key=key,
                filename=filename,
                x=x,
                y=y,
                width=crop_width,
                height=crop_height,
                baseline_pixels_sha256=_digest(
                    crop_raw.get("baseline_pixels_sha256"),
                    f"{label}/{key}/Baseline",
                ),
            )
            crops[key] = crop
            global_keys.add(key)
            filenames.add(filename)
        atlas_dir = root / directory
        if not atlas_dir.is_dir() or atlas_dir.is_symlink():
            raise LayoutPortError(f"{label}-Atlasordner fehlt: {atlas_dir}")
        atlases[sheet] = Atlas(sheet, width, height, directory, crops)
    return raw, atlases


def _load_store(
    root: Path,
    *,
    source_index_path: Path,
    source_atlases: dict[str, Atlas],
) -> dict[str, Path]:
    raw = _read_json(root / "store-manifest.json", "Quellablagenmanifest")
    if raw.get("schema_version") != 1 or raw.get("origin") != "derived":
        raise LayoutPortError("Quellablage ist keine abgeleitete UI-Ablage")
    if raw.get("source_export_index_sha256") != _sha256_file(source_index_path):
        raise LayoutPortError("Quellablage und Quellexport gehoeren nicht zusammen")
    entries = raw.get("sheets")
    if not isinstance(entries, list) or not entries:
        raise LayoutPortError("Quellablage hat keine Blattpins")
    paths: dict[str, Path] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise LayoutPortError("Quellablagenblatt ist kein Objekt")
        sheet = _flat_name(entry.get("file"), "Quellablagenblatt")
        if sheet in paths or sheet not in source_atlases:
            raise LayoutPortError(f"Unerwartetes oder doppeltes Quellblatt: {sheet}")
        atlas = source_atlases[sheet]
        if (
            _positive_int(entry.get("width"), f"{sheet}/Breite") != atlas.width
            or _positive_int(entry.get("height"), f"{sheet}/Hoehe") != atlas.height
        ):
            raise LayoutPortError(f"Quellblattgroesse weicht vom Export ab: {sheet}")
        path = root / sheet
        expected_hash = _digest(entry.get("sha256"), f"{sheet}/SHA-256")
        if not path.is_file() or path.is_symlink() or _sha256_file(path) != expected_hash:
            raise LayoutPortError(f"Quellblatt fehlt oder weicht vom Pin ab: {sheet}")
        paths[sheet] = path
    if set(paths) != set(source_atlases):
        raise LayoutPortError("Quellablage und Quellexport haben verschiedene Blaetter")
    expected_entries = set(paths) | {"store-manifest.json"}
    actual_entries = {entry.name for entry in root.iterdir()}
    if actual_entries != expected_entries:
        raise LayoutPortError("Quellablage enthaelt einen unerwarteten Dateisatz")
    return paths


def _read_crop(path: Path, crop: Crop, label: str) -> Image.Image:
    if not path.is_file() or path.is_symlink():
        raise LayoutPortError(f"{label} fehlt: {path}")
    try:
        with Image.open(path) as opened:
            opened.load()
            image = opened.convert("RGBA")
    except Exception as exc:
        raise LayoutPortError(f"{label} ist nicht lesbar: {path}") from exc
    if image.size != (crop.width, crop.height):
        raise LayoutPortError(
            f"{label} hat {image.width}x{image.height} statt "
            f"{crop.width}x{crop.height}"
        )
    return image


def _write_png_atomic(image: Image.Image, destination: Path) -> None:
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".png", dir=destination.parent
    )
    os.close(handle)
    temporary = Path(temporary_name)
    try:
        image.save(temporary, format="PNG", optimize=True)
        with Image.open(temporary) as reopened:
            reopened.load()
            if reopened.convert("RGBA").tobytes() != image.tobytes():
                raise LayoutPortError(f"PNG-Ruecklesepruefung fehlgeschlagen: {destination}")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def port_layout(source_export: Path, source_store: Path, target_export: Path) -> dict[str, Any]:
    source_index, source_atlases = _load_index(source_export, "Quelle")
    target_index, target_atlases = _load_index(target_export, "Ziel")
    store_paths = _load_store(
        source_store,
        source_index_path=source_export / "index.json",
        source_atlases=source_atlases,
    )
    if set(source_atlases) != set(target_atlases):
        raise LayoutPortError("Quell- und Zielindex haben verschiedene Atlasblaetter")

    prepared: list[tuple[Path, Image.Image, str]] = []
    counts: dict[str, int] = {}
    moved_geometry = 0
    target_only: list[str] = []
    for sheet_name, source_atlas in source_atlases.items():
        target_atlas = target_atlases[sheet_name]
        target_only.extend(
            f"{sheet_name}:{key}" for key in sorted(set(target_atlas.crops) - set(source_atlas.crops))
        )
        try:
            with Image.open(store_paths[sheet_name]) as opened:
                opened.load()
                source_sheet = opened.convert("RGBA")
        except Exception as exc:
            raise LayoutPortError(f"Quellblatt ist nicht dekodierbar: {sheet_name}") from exc
        if source_sheet.size != (source_atlas.width, source_atlas.height):
            raise LayoutPortError(f"Quellblattgroesse ist falsch: {sheet_name}")

        changed = 0
        for key, source_crop in source_atlas.crops.items():
            baseline_path = source_export / source_crop.directory / source_crop.filename
            baseline = _read_crop(baseline_path, source_crop, f"Quellbaseline {key}")
            if _pixel_digest(baseline) != source_crop.baseline_pixels_sha256:
                raise LayoutPortError(f"Quellbaseline-Pin weicht ab: {key}")
            edited = source_sheet.crop(source_crop.box)
            if _pixel_digest(edited) == source_crop.baseline_pixels_sha256:
                continue
            target_crop = target_atlas.crops.get(key)
            if target_crop is None:
                raise LayoutPortError(f"Geaenderter Quell-Key fehlt im Ziel: {sheet_name}:{key}")
            if (source_crop.width, source_crop.height) != (
                target_crop.width,
                target_crop.height,
            ):
                raise LayoutPortError(
                    f"Geaenderter Key hat im Ziel eine andere Groesse: {sheet_name}:{key}"
                )
            target_path = target_export / target_crop.directory / target_crop.filename
            target_baseline = _read_crop(target_path, target_crop, f"Zielbaseline {key}")
            if _pixel_digest(target_baseline) != target_crop.baseline_pixels_sha256:
                raise LayoutPortError(f"Zielexport wurde vor dem Port veraendert: {key}")
            if (source_crop.x, source_crop.y) != (target_crop.x, target_crop.y):
                moved_geometry += 1
            prepared.append((target_path, edited.copy(), f"{sheet_name}:{key}"))
            changed += 1
        counts[sheet_name] = changed

    for destination, image, _key in prepared:
        _write_png_atomic(image, destination)

    report = {
        "schema": "stronghold-europe-ui-layout-port-v1",
        "source_target_build_id": source_index.get("target_build_id"),
        "target_target_build_id": target_index.get("target_build_id"),
        "source_export_index_sha256": _sha256_file(source_export / "index.json"),
        "target_export_index_sha256": _sha256_file(target_export / "index.json"),
        "source_store_manifest_sha256": _sha256_file(source_store / "store-manifest.json"),
        "ported_crop_count": len(prepared),
        "ported_crop_counts_by_sheet": counts,
        "ported_crops_with_moved_geometry": moved_geometry,
        "target_only_crop_count": len(target_only),
        "target_only_crops": target_only,
        "ported_keys": [key for _path, _image, key in prepared],
    }
    report_path = target_export / "layout-port-report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-export", required=True)
    parser.add_argument("--source-store", required=True)
    parser.add_argument("--target-export", required=True)
    args = parser.parse_args()
    try:
        source_export = _input_path(args.source_export, "Quellexport")
        source_store = _input_path(args.source_store, "Quellablage")
        target_export = _target_export_path(args.target_export)
        report = port_layout(source_export, source_store, target_export)
    except LayoutPortError as exc:
        parser.error(str(exc))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

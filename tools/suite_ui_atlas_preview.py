"""Read-only GUI preview of UI atlas exports with untrusted-index containment.

Only ui_atlas.py --check/import may validate game-build provenance and
authorize pixel conversion. This helper never reads game assets or writes.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

class UiPreviewIndexError(ValueError):
    """A UI export cannot safely be previewed by the GUI."""

_HEX64 = re.compile(r"[0-9a-fA-F]{64}\Z")
_MAX_INDEX_BYTES = 32 * 1024 * 1024
_MAX_CROPS = 100_000


def _leaf(value, label: str, *, suffix: str | None = None) -> str:
    if (
        not isinstance(value, str) or not value or len(value) > 240
        or value in {".", ".."} or "/" in value or "\\" in value
        or ":" in value or "\x00" in value
        or Path(value).name != value
    ):
        raise UiPreviewIndexError(f"{label} enthält einen unsicheren Dateinamen")
    if suffix and not value.lower().endswith(suffix):
        raise UiPreviewIndexError(f"{label} muss auf {suffix} enden")
    return value


def _hex(value, label: str) -> None:
    if not isinstance(value, str) or not _HEX64.fullmatch(value):
        raise UiPreviewIndexError(f"{label} hat keinen gültigen SHA-256-Wert")


def _positive_int(value, label: str, *, allow_zero=False) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or (
        value < 0 if allow_zero else value <= 0
    ):
        raise UiPreviewIndexError(f"{label} ist keine zulässige Pixelzahl")
    return value


def read_ui_preview_index(folder: Path) -> list[dict]:
    """Check preview-only structure, index names, file containment and presence.

    No implicit build approval: the authoritative CLI tool rechecks the
    selected installed game's XAML, Unity texture SHA and every crop pixel.
    """
    try:
        root = folder.expanduser().resolve(strict=True)
        index_path = root / "index.json"
        if not root.is_dir() or index_path.is_symlink() or not index_path.is_file():
            raise UiPreviewIndexError("Kein regulärer UI-Export mit index.json vorhanden")
        if index_path.stat().st_size > _MAX_INDEX_BYTES:
            raise UiPreviewIndexError("UI-Index ist ungewöhnlich groß")
        document = json.loads(index_path.read_text(encoding="utf-8-sig"))
    except UiPreviewIndexError:
        raise
    except (OSError, UnicodeError, ValueError, RuntimeError) as exc:
        raise UiPreviewIndexError(f"index.json nicht lesbar: {exc}") from exc

    if (
        not isinstance(document, dict)
        or set(document) != {
            "schema_version", "target_build_id", "texture_asset_name",
            "texture_asset_sha256", "atlases"
        }
        or document["schema_version"] != 1
        or not isinstance(document["target_build_id"], str)
        or not document["target_build_id"]
        or not isinstance(document["atlases"], list)
        or not document["atlases"]
    ):
        raise UiPreviewIndexError("UI-Index hat keinen vollständigen Exportvertrag")
    _leaf(document["texture_asset_name"], "Unity-Assetdatei")
    _hex(document["texture_asset_sha256"], "Unity-Quellhash")

    entries: list[dict] = []
    atlas_names: set[str] = set()
    all_keys: set[str] = set()
    for atlas in document["atlases"]:
        if not isinstance(atlas, dict) or set(atlas) != {
            "dictionary", "dictionary_sha256", "sheet", "sheet_width",
            "sheet_height", "directory", "crops"
        }:
            raise UiPreviewIndexError("Atlasindex ist unvollständig oder erweitert")
        directory = _leaf(atlas["directory"], "Atlasordner")
        dictionary = _leaf(atlas["dictionary"], "XAML-Dictionary", suffix=".xaml")
        _leaf(atlas["sheet"], "Atlasblatt", suffix=".png")
        _hex(atlas["dictionary_sha256"], "XAML-Quellhash")
        _positive_int(atlas["sheet_width"], "Blattbreite")
        _positive_int(atlas["sheet_height"], "Blatthöhe")
        if directory in atlas_names:
            raise UiPreviewIndexError("Atlasordner kommt doppelt vor")
        atlas_names.add(directory)
        crops = atlas["crops"]
        if not isinstance(crops, list) or not crops:
            raise UiPreviewIndexError(f"{directory}: keine UI-Ausschnitte")
        parent = root / directory
        if parent.is_symlink() or not parent.is_dir():
            raise UiPreviewIndexError(f"{directory}: fehlender oder verlinkter Atlasordner")
        if parent.resolve() != parent:
            raise UiPreviewIndexError(f"{directory}: Atlasordner liegt außerhalb des Exports")
        files: set[str] = set()
        for entry in crops:
            if len(entries) >= _MAX_CROPS:
                raise UiPreviewIndexError("UI-Export enthält zu viele Ausschnitte")
            if not isinstance(entry, dict) or set(entry) != {
                "key", "file", "x", "y", "width", "height",
                "baseline_pixels_sha256"
            }:
                raise UiPreviewIndexError(f"{directory}: beschädigter Ausschnittseintrag")
            name = _leaf(entry["file"], "PNG-Ausschnitt", suffix=".png")
            key = entry["key"]
            if not isinstance(key, str) or not key or key in all_keys or name in files:
                raise UiPreviewIndexError(f"{directory}: doppelter oder leerer Sprite-Schlüssel")
            # Match the same Windows filename normalization as the exporter.
            expected = re.sub(r'[<>:"/\\\\|?*]', "_", key) + ".png"
            if name != expected:
                raise UiPreviewIndexError(
                    f"{directory}: Dateiname entspricht nicht dem XAML-Schlüssel"
                )
            all_keys.add(key)
            files.add(name)
            _hex(entry["baseline_pixels_sha256"], "PNG-Quellhash")
            for field in ("x", "y", "width", "height"):
                _positive_int(entry[field], f"{name}/{field}",
                              allow_zero=field in ("x", "y"))
            if (
                entry["x"] + entry["width"] > atlas["sheet_width"]
                or entry["y"] + entry["height"] > atlas["sheet_height"]
            ):
                raise UiPreviewIndexError(f"{name}: Ausschnitt außerhalb des Atlasblattes")
            image = parent / name
            if image.is_symlink() or not image.is_file() or image.resolve() != image:
                raise UiPreviewIndexError(f"{directory}/{name}: PNG fehlt oder ist ein Link")
            entries.append({
                **entry, "atlas": directory, "path": image,
                "preview_only": True,
            })
    return entries


SH1_HUD_BUILD_ID = "stronghold-1-definitive-edition-original-hud-v1"
SH1_HUD_SOURCE_SCHEMA = "sprite-suite.stronghold1.hud-edit.v1"
SH1_HUD_ATLASES = {"UI-MasterAtlas", "UI-ROL", "UI-CandleAtlas"}


def validate_sh1_hud_preview(folder: Path, entries: list[dict]) -> None:
    """Require matching SH1 source/atlas provenance before switching GUI modes.

    This is a *preview* consistency check, never a substitute for
    ui_sh1_hud.py check/build which verifies original XAML and pixels.
    """
    root = folder.expanduser().resolve(strict=True)
    source_meta = root / "sh1_hud_source.json"
    if source_meta.is_symlink() or not source_meta.is_file():
        raise UiPreviewIndexError(
            "SH1-HUD-Herkunft fehlt oder ist eine unsichere Dateiverknüpfung"
        )
    if source_meta.stat().st_size > 1024 * 1024:
        raise UiPreviewIndexError("SH1-HUD-Herkunftsmanifest ist zu groß")
    try:
        document = json.loads((root / "index.json").read_text(encoding="utf-8-sig"))
        meta = json.loads(source_meta.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise UiPreviewIndexError(
            f"SH1-HUD-Herkunftsmanifest ist nicht lesbar: {exc}"
        ) from exc

    if (
        not isinstance(document, dict)
        or document.get("target_build_id") != SH1_HUD_BUILD_ID
        or document.get("texture_asset_name") != "globalgamemanagers.assets"
        or not isinstance(meta, dict)
        or meta.get("schema") != SH1_HUD_SOURCE_SCHEMA
        or meta.get("source") != "Stronghold 1 Definitive Edition"
        or meta.get("source_globalgamemanagers_sha256")
        != document.get("texture_asset_sha256")
        or not isinstance(meta.get("editable_images"), int)
        or isinstance(meta.get("editable_images"), bool)
        or meta["editable_images"] != len(entries)
        or not isinstance(meta.get("baseline_files"), list)
        or len(meta["baseline_files"]) != 3
    ):
        raise UiPreviewIndexError(
            "SH1-HUD-Herkunft, Exportindex oder Crop-Anzahl widersprüchlich"
        )
    atlas_list = document.get("atlases")
    if (
        not isinstance(atlas_list, list)
        or len(atlas_list) != 3
        or {item["atlas"] for item in entries} != SH1_HUD_ATLASES
        or {atlas.get("directory") for atlas in atlas_list
            if isinstance(atlas, dict)} != SH1_HUD_ATLASES
    ):
        raise UiPreviewIndexError(
            "SH1-HUD-Export benötigt genau die drei eigenen Atlasblätter"
        )
    baseline = {}
    for entry in meta["baseline_files"]:
        if not isinstance(entry, dict):
            raise UiPreviewIndexError("SH1-HUD-Baseline ist unvollständig")
        sheet = entry.get("sheet")
        if sheet in baseline or sheet not in {
            f"{name}.png" for name in SH1_HUD_ATLASES
        }:
            raise UiPreviewIndexError("SH1-HUD-Baseline enthält fremde Blätter")
        _hex(entry.get("sha256"), "SH1-HUD-Baselineblatt")
        _hex(entry.get("dictionary_sha256"), "SH1-XAML-Baseline")
        baseline[sheet] = entry
    if set(baseline) != {f"{name}.png" for name in SH1_HUD_ATLASES}:
        raise UiPreviewIndexError("SH1-HUD-Baselineblätter fehlen")
    for atlas in atlas_list:
        named = baseline.get(atlas["sheet"])
        if (
            named is None
            or named.get("dictionary") != atlas["dictionary"]
            or named["dictionary_sha256"] != atlas["dictionary_sha256"]
        ):
            raise UiPreviewIndexError(
                "SH1-HUD-Baseline-XAML passt nicht zum angezeigten Atlas"
            )

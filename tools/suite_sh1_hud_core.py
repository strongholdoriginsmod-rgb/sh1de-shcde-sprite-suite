"""Source-pinned SH1 HUD Studio core and safe legacy Origins key comparison.

Original SH1 Noesis keys remain authoritative. Never reuse Crusader X/Y or
Unity path IDs without explicit separate checks. No game writes here.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from PIL import Image

from ui_sh1_hud import ATLAS_NAMES, ROOT, HudError, digest_file, pixel_digest
from suite_ui_atlas_preview import read_ui_preview_index, validate_sh1_hud_preview

WORK = ROOT / "work"


def under_work(value: str | Path) -> Path:
    """Accept a genuine workspace beneath the current portable Sprite Suite."""
    original = Path(value)
    if not original.is_absolute():
        original = ROOT / original
    work = WORK.resolve()
    resolved = original.resolve()
    if resolved == work or not resolved.is_relative_to(work):
        raise HudError("HUD-Arbeitsordner muss unter SpriteSuite/work liegen")
    if any(p.is_symlink() for p in (original, *original.parents) if p.exists()):
        raise HudError("HUD-Arbeitsordner darf keine symbolische Dateiverknüpfung sein")
    return resolved


def load_project(folder: str | Path) -> list[dict]:
    """Reuse the original SpriteSuite UI preview/index validator."""
    root = under_work(folder)
    entries = read_ui_preview_index(root)
    validate_sh1_hud_preview(root, entries)
    if not entries:
        raise HudError("Der HUD-Export enthält keine Originalausschnitte")
    return entries


def entry_state(entry: dict) -> str:
    """Compare RGBA bytes with the XAML-pinned baseline digest."""
    path = Path(entry["path"])
    if path.is_symlink() or not path.is_file():
        return "Fehlt"
    with Image.open(path) as image:
        if image.size != (entry["width"], entry["height"]):
            return "Größe falsch"
        digest = pixel_digest(image.convert("RGBA"))
    return "Original" if digest == entry["baseline_pixels_sha256"] else "Geändert"


def original_crop(workspace: str | Path, entry: dict) -> Image.Image:
    """Read an original crop from the hashed original atlas without changing it."""
    root = under_work(workspace)
    atlas = entry["atlas"]
    if atlas not in ATLAS_NAMES:
        raise HudError("Unbekanntes Stronghold-1-Atlasblatt")
    png = root / "baseline" / (atlas + ".png")
    meta = json.loads((root / "sh1_hud_source.json").read_text(encoding="utf8"))
    expected = next(
        (item["sha256"] for item in meta["baseline_files"]
         if item["sheet"] == atlas + ".png"), None
    )
    if png.is_symlink() or not png.is_file() or not expected or digest_file(png) != expected:
        raise HudError("Die originale Atlasbasis wurde seit dem Export verändert")
    x, y, w, h = (entry[key] for key in ("x", "y", "width", "height"))
    with Image.open(png) as sheet:
        if x < 0 or y < 0 or x + w > sheet.width or y + h > sheet.height:
            raise HudError("Originalausschnitt liegt außerhalb des Basisatlas")
        cropped = sheet.crop((x, y, x + w, y + h)).convert("RGBA")
    if pixel_digest(cropped) != entry["baseline_pixels_sha256"]:
        raise HudError("Originalausschnitt entspricht nicht der gepinnten Pixelquelle")
    return cropped


def restore_original(workspace: str | Path, entry: dict, *, expected_disk_hash: str | None = None) -> Path:
    """Atomically reset one crop, keeping a verified undo backup outside the project."""
    root = under_work(workspace)
    entries = load_project(root)
    matching = [e for e in entries if e["atlas"] == entry.get("atlas")
                and e["key"] == entry.get("key") and e["file"] == entry.get("file")]
    if len(matching) != 1:
        raise HudError("Bildschlüssel fehlt im geprüften HUD-Projekt")
    actual = matching[0]
    path = Path(actual["path"])
    if path.is_symlink() or not path.is_file() or path.resolve() != path:
        raise HudError("Der Bildpfad wurde unerwartet verändert")
    state = entry_state(actual)
    if state == "Original":
        return path
    if state != "Geändert":
        raise HudError("Beschädigter oder fehlender Bildausschnitt")
    current_hash = digest_file(path)
    if expected_disk_hash and current_hash != expected_disk_hash:
        raise HudError("Bild wurde inzwischen extern verändert – bitte neu laden")
    original = original_crop(root, actual)

    # Backups are outside the user-editable export directory. Export --replace
    # cannot silently destroy the only existing version of an edited crop.
    recover = under_work(WORK / "sh1-hud-ruecksetzen")
    recover.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", actual["key"])[:72]
    backup = recover / f"{stamp}-{actual['atlas']}-{safe}-{current_hash[:10]}.png"
    backup.write_bytes(path.read_bytes())
    if digest_file(backup) != current_hash:
        backup.unlink(missing_ok=True)
        raise HudError("Vorherige Bildfassung konnte nicht unverändert gesichert werden")

    staged = None
    try:
        fd, filename = tempfile.mkstemp(dir=path.parent, prefix=".sh1-reset-", suffix=".png")
        os.close(fd)
        staged = Path(filename)
        original.save(staged, "PNG")
        with Image.open(staged) as probe:
            if pixel_digest(probe) != actual["baseline_pixels_sha256"]:
                raise HudError("Neuer Originalausschnitt konnte nicht überprüft werden")
        if path.is_symlink() or digest_file(path) != current_hash:
            raise HudError("Bild wurde während der Wiederherstellung verändert")
        os.replace(staged, path)
        return backup
    finally:
        if staged is not None and staged.exists():
            staged.unlink()


def compare_legacy(workspace: str | Path, origins_export: str | Path) -> dict:
    """Read-only bridge between SH1 native keys and historical Origins exports.

    Original Origins tooling targeted 4 SHCDE atlases, while SH1 uses its
    own 3 sheets. Common XAML keys can be linked; coordinate matching is
    neither guaranteed nor claimed.
    """
    source = load_project(workspace)
    older = Path(origins_export).expanduser().resolve(strict=True)
    other = read_ui_preview_index(older)
    native = {entry["key"]: entry for entry in source}
    legacy = {entry["key"]: entry for entry in other}
    common = native.keys() & legacy.keys()
    same_size = sorted(key for key in common if
                       (native[key]["width"], native[key]["height"])
                       == (legacy[key]["width"], legacy[key]["height"]))
    resized = sorted(common - set(same_size))
    return {
        "schema": "sprite-suite.sh1-hud-origins-keybridge.v1",
        "sh1_count": len(native),
        "origins_count": len(legacy),
        "same_key_count": len(common),
        "same_dimensions_count": len(same_size),
        "different_dimensions_count": len(resized),
        "only_sh1_count": len(native.keys() - legacy.keys()),
        "only_origins_count": len(legacy.keys() - native.keys()),
        "matching_keys": same_size,
        "resize_review_keys": resized,
        "only_sh1_keys": sorted(native.keys() - legacy.keys()),
        "only_origins_keys": sorted(legacy.keys() - native.keys()),
        "reference_type": "named-key-contract-only",
        "layout_positions_shared": False,
        "unity_path_ids_shared": False,
        "writes_to_game": False,
    }

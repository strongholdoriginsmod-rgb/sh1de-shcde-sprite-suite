from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from PIL import Image

from .builds import verify_supported_builds
from .config import BuilderConfig
from .hashing import sha256_file


class InstalledArtError(RuntimeError):
    """Installed artwork cannot be proven to match its recorded build."""


@dataclass(frozen=True)
class InstalledFrame:
    name: str
    image: Image.Image
    mask: Image.Image | None
    pivot_x: float
    pivot_y: float
    pixels_per_unit: float
    origin: str


@dataclass(frozen=True)
class VerifiedInstalledMod:
    root: Path
    build_manifest: Mapping[str, Any]
    output_by_path: Mapping[str, Mapping[str, Any]]


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise InstalledArtError(f"{label} ist nicht lesbares UTF-8-JSON: {path}") from exc
    if not isinstance(value, dict):
        raise InstalledArtError(f"{label} ist kein JSON-Objekt: {path}")
    return value


def _safe_relative(value: object) -> str:
    text = str(value).replace("\\", "/")
    candidate = Path(text)
    if (
        not text
        or candidate.is_absolute()
        or ".." in candidate.parts
        or candidate.as_posix() != text
    ):
        raise InstalledArtError(f"Unsicherer relativer Installationspfad: {value!r}")
    return text


def _finite(value: object, label: str) -> float:
    if isinstance(value, bool):
        raise InstalledArtError(f"{label} ist keine endliche Zahl")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise InstalledArtError(f"{label} ist keine endliche Zahl") from exc
    if not math.isfinite(number):
        raise InstalledArtError(f"{label} ist keine endliche Zahl")
    return number


def verify_installed_mod(config: BuilderConfig) -> VerifiedInstalledMod:
    """Verify the complete managed install and its approved game-build IDs."""

    if config.target.game_dir is None:
        raise InstalledArtError("Kein Crusader-Spielordner konfiguriert")
    plugins = (config.target.game_dir / "BepInEx" / "plugins").resolve()
    root = (plugins / config.output.mod_folder_name).resolve()
    if plugins not in root.parents or not root.is_dir():
        raise InstalledArtError(f"Verwaltete Modinstallation fehlt: {root}")

    install_manifest_path = config.output.state_dir / "install-manifest.json"
    install_manifest = _read_object(install_manifest_path, "Installationsmanifest")
    if install_manifest.get("schema_version") != 1:
        raise InstalledArtError("Unbekanntes Installationsmanifest-Schema")
    try:
        recorded_destination = Path(str(install_manifest["destination"])).resolve()
        raw_files = install_manifest["files"]
    except KeyError as exc:
        raise InstalledArtError("Installationsmanifest ist unvollständig") from exc
    if recorded_destination != root:
        raise InstalledArtError(
            f"Installationsmanifest zeigt auf {recorded_destination}, erwartet ist {root}"
        )
    if not isinstance(raw_files, dict) or not raw_files:
        raise InstalledArtError("Installationsmanifest enthält keine Dateiliste")
    expected = {
        _safe_relative(name): str(digest).lower()
        for name, digest in raw_files.items()
    }
    if any(re.fullmatch(r"[0-9a-f]{64}", digest) is None for digest in expected.values()):
        raise InstalledArtError("Installationsmanifest enthält einen ungültigen SHA-256")
    actual = {
        path.relative_to(root).as_posix(): path
        for path in root.rglob("*")
        if path.is_file()
    }
    if set(actual) != set(expected):
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        raise InstalledArtError(
            "Installierter Dateisatz weicht vom verwalteten Manifest ab: "
            f"fehlend={missing[:8]}, zusätzlich={extra[:8]}"
        )
    for relative, path in sorted(actual.items()):
        if sha256_file(path) != expected[relative].lower():
            raise InstalledArtError(f"Installierte Datei wurde verändert: {relative}")

    build_manifest_path = root / "build-manifest.json"
    build_manifest = _read_object(build_manifest_path, "Build-Manifest")
    outputs = build_manifest.get("outputs")
    if not isinstance(outputs, list) or any(not isinstance(item, dict) for item in outputs):
        raise InstalledArtError("Build-Manifest enthält keine gültige Ausgabeliste")
    output_by_path: dict[str, Mapping[str, Any]] = {}
    for output in outputs:
        relative = _safe_relative(output.get("relative_path", ""))
        if relative in output_by_path:
            raise InstalledArtError(f"Doppelter Build-Ausgabepfad: {relative}")
        digest = str(output.get("sha256", ""))
        if relative not in expected or expected[relative].lower() != digest.lower():
            raise InstalledArtError(f"Build- und Installationsmanifest widersprechen sich: {relative}")
        output_by_path[relative] = output
    if set(output_by_path) != set(expected) - {"build-manifest.json"}:
        raise InstalledArtError(
            "Build-Manifest und installierter Dateisatz haben keine exakte "
            "1:1-Ausgabemenge"
        )

    supported = config.project_root / "config" / "supported-builds.json"
    match = verify_supported_builds(config, supported)
    if build_manifest.get("source_build_id") != match.source_id:
        raise InstalledArtError("Installierter Mod gehört nicht zum aktuellen SH1DE-Build")
    if build_manifest.get("target_build_id") != match.target_id:
        raise InstalledArtError("Installierter Mod gehört nicht zum aktuellen SHCDE-Build")
    return VerifiedInstalledMod(root, build_manifest, output_by_path)


def _load_rgba(path: Path, label: str) -> Image.Image:
    try:
        with Image.open(path) as opened:
            opened.load()
            return opened.convert("RGBA")
    except Exception as exc:
        raise InstalledArtError(f"{label} ist kein lesbares Bild: {path}") from exc


def _atlas_frames(mod: VerifiedInstalledMod, group: str) -> dict[str, InstalledFrame] | None:
    prefix = f"Override/Atlas/{group}/"
    json_relative = prefix + "atlas.json"
    if json_relative not in mod.output_by_path:
        return None
    required = {json_relative, prefix + "atlas.png"}
    present = {name for name in mod.output_by_path if name.startswith(prefix)}
    if not required <= present or not present <= required | {prefix + "atlas_m.png"}:
        raise InstalledArtError(f"Unvollständiger oder fremder Atlas-Dateisatz für {group}: {present}")
    descriptor = _read_object(mod.root / json_relative, f"Atlasbeschreibung {group}")
    if set(descriptor) != {"pixelsPerUnit", "frames"}:
        raise InstalledArtError(f"Atlasbeschreibung {group} hat unbekannte Felder")
    atlas = _load_rgba(mod.root / (prefix + "atlas.png"), f"Farbatlas {group}")
    mask_path = mod.root / (prefix + "atlas_m.png")
    mask = _load_rgba(mask_path, f"Maskenatlas {group}") if mask_path.is_file() else None
    if mask is not None and mask.size != atlas.size:
        raise InstalledArtError(f"Maskenatlasgröße weicht für {group} ab")
    raw_frames = descriptor.get("frames")
    if not isinstance(raw_frames, list) or not raw_frames:
        raise InstalledArtError(f"Atlas {group} enthält keine Frames")
    default_ppu = _finite(descriptor.get("pixelsPerUnit"), f"{group}.pixelsPerUnit")
    if default_ppu <= 0:
        raise InstalledArtError(f"Atlas {group} hat keine positive PPU")
    frames: dict[str, InstalledFrame] = {}
    rect_owners: dict[tuple[int, int, int, int], tuple[bytes, bytes | None]] = {}
    distinct_rectangles: list[tuple[int, int, int, int, str]] = []
    for index, raw in enumerate(raw_frames):
        if not isinstance(raw, dict):
            raise InstalledArtError(f"{group} Frames[{index}] ist kein Objekt")
        if set(raw) != {"name", "rect", "pivot", "pixelsPerUnit"}:
            raise InstalledArtError(f"{group} Frames[{index}] hat unbekannte Felder")
        name = str(raw.get("name", ""))
        if not name or name in frames:
            raise InstalledArtError(f"Leerer oder doppelter Atlasframe in {group}: {name!r}")
        rect = raw.get("rect")
        pivot = raw.get("pivot")
        if (
            not isinstance(rect, dict)
            or set(rect) != {"x", "y", "w", "h"}
            or not isinstance(pivot, dict)
            or set(pivot) != {"x", "y"}
        ):
            raise InstalledArtError(f"Rechteck/Pivot fehlt für {name}")
        try:
            values = tuple(rect[key] for key in ("x", "y", "w", "h"))
            if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
                raise TypeError
            x, y, width, height = values
        except (KeyError, TypeError) as exc:
            raise InstalledArtError(f"Ungültiges Atlasrechteck für {name}") from exc
        if (
            x < 0
            or y < 0
            or width <= 0
            or height <= 0
            or x + width > atlas.width
            or y + height > atlas.height
        ):
            raise InstalledArtError(f"Atlasrechteck verlässt das Blatt: {name}")
        box = (x, atlas.height - y - height, x + width, atlas.height - y)
        image = atlas.crop(box)
        frame_mask = mask.crop(box) if mask is not None else None
        pixels = (image.tobytes(), frame_mask.tobytes() if frame_mask is not None else None)
        rect_key = (x, y, width, height)
        previous = rect_owners.get(rect_key)
        if previous is not None and previous != pixels:
            raise InstalledArtError(f"Geteiltes Atlasrechteck enthält widersprüchliche Pixel: {name}")
        if previous is None:
            for other_x, other_y, other_w, other_h, other_name in distinct_rectangles:
                if (
                    x < other_x + other_w
                    and other_x < x + width
                    and y < other_y + other_h
                    and other_y < y + height
                ):
                    raise InstalledArtError(
                        f"Atlasrechtecke überlappen: {other_name} und {name}"
                    )
            distinct_rectangles.append((x, y, width, height, name))
        rect_owners[rect_key] = pixels
        ppu = _finite(raw.get("pixelsPerUnit"), f"{name}.PPU")
        if ppu <= 0:
            raise InstalledArtError(f"{name}.PPU ist nicht positiv")
        frames[name] = InstalledFrame(
            name=name,
            image=image,
            mask=frame_mask,
            pivot_x=_finite(pivot.get("x"), f"{name}.pivot.x"),
            pivot_y=_finite(pivot.get("y"), f"{name}.pivot.y"),
            pixels_per_unit=ppu,
            origin="installed-atlas",
        )
    return frames


def installed_group_frames(
    mod: VerifiedInstalledMod,
    group: str,
    expected_names: Sequence[str],
) -> dict[str, InstalledFrame] | None:
    """Return exact installed overrides, or None when the group is unmodified."""

    atlas = _atlas_frames(mod, group)
    if atlas is not None:
        if set(atlas) != set(expected_names):
            raise InstalledArtError(
                f"Installierter Atlas {group} deckt nicht exakt die Mapping-Gruppe ab: "
                f"fehlend={sorted(set(expected_names) - set(atlas))[:8]}, "
                f"zusätzlich={sorted(set(atlas) - set(expected_names))[:8]}"
            )
    combined = dict(atlas or {})

    direct: dict[str, InstalledFrame] = {}
    for name in expected_names:
        relative = f"Override/Sprites/{name}.png"
        if relative not in mod.output_by_path:
            continue
        output = mod.output_by_path[relative]
        metadata = output.get("metadata")
        if not isinstance(metadata, dict) or metadata.get("frame") != name:
            raise InstalledArtError(f"Metadaten des installierten Einzelbilds sind ungültig: {name}")
        image = _load_rgba(mod.root / relative, f"Installiertes Einzelbild {name}")
        mask_relative = f"Override/Sprites/{name}_m.png"
        frame_mask = None
        if mask_relative in mod.output_by_path:
            frame_mask = _load_rgba(mod.root / mask_relative, f"Installierte Maske {name}")
            if frame_mask.size != image.size:
                raise InstalledArtError(f"Installierte Maskengröße weicht ab: {name}")
        direct[name] = InstalledFrame(
            name=name,
            image=image,
            mask=frame_mask,
            pivot_x=_finite(metadata.get("target_pivot_x"), f"{name}.pivot.x"),
            pivot_y=_finite(metadata.get("target_pivot_y"), f"{name}.pivot.y"),
            # The direct-replacement format does not carry a PPU. The caller
            # replaces this placeholder with the target slot's verified PPU;
            # the effective direct-sprite geometry is inherited from that
            # target slot by the loader.
            pixels_per_unit=64.0,
            origin="installed-sprite",
        )
    # A direct sprite wins by name over an atlas in the Extender. Supporting
    # both here is important: the profile contract allows that shadowing only
    # after explicit consent, and an export must reproduce the same order.
    combined.update(direct)
    return combined or None


def reject_other_override_plugins(
    config: BuilderConfig, group: str, frame_names: Sequence[str]
) -> None:
    """Fail when another file-based plugin can shadow the exported result."""

    if config.target.game_dir is None:
        raise InstalledArtError("Kein Crusader-Spielordner konfiguriert")
    plugins = (config.target.game_dir / "BepInEx" / "plugins").resolve()
    managed = (plugins / config.output.mod_folder_name).resolve()
    conflicts: list[str] = []
    for candidate in plugins.iterdir():
        if not candidate.is_dir() or candidate.resolve() == managed:
            continue
        atlas = candidate / "Override" / "Atlas" / group
        if atlas.exists():
            conflicts.append(str(atlas))
        sprites = candidate / "Override" / "Sprites"
        if sprites.is_dir():
            for name in frame_names:
                if (sprites / f"{name}.png").exists() or (sprites / f"{name}_m.png").exists():
                    conflicts.append(str(sprites / name))
                    break
    if conflicts:
        raise InstalledArtError(
            "Andere Plugins können dieselben Grafiken überstimmen; 'installierte Mod' "
            f"ist deshalb nicht eindeutig: {conflicts[:8]}"
        )

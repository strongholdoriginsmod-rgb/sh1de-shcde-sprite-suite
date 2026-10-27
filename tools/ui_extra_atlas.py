"""Build and verify *additional* SHCDE Noesis UI atlas pages from user PNGs.

Produces a portable, isolated GUI override CANDIDATE: new PNG atlas pages,
Noesis XAML dictionaries, and a copy of ApplicationResources.xaml with
explicit MergedDictionaries entries. Does NOT install or claim the game
can load new atlas resources without a separate runtime test.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "sprite-suite.shcde-extra-ui-atlas.v1"
MERGED_PATH = "XAMLResources/ApplicationResources.xaml"
REL_SPRITES = Path("Override/Assets/GUI/Sprites")
REL_RESOURCES = Path("Override/Assets/GUI/XAMLResources")
MANIFEST = "extra-ui-atlas-manifest.json"
MAX_PAGES = 32
MAX_INPUTS = 8192
MAX_ASSET_PIXELS = 16_777_216
SHEET_SIZES = (256, 512, 1024, 2048, 4096)
NS_X = "{http://schemas.microsoft.com/winfx/2006/xaml}"


class ExtraAtlasError(RuntimeError):
    pass


def _sha(file: Path) -> str:
    h = hashlib.sha256()
    with file.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _pixel_sha(image: Image.Image) -> str:
    return hashlib.sha256(image.convert("RGBA").tobytes()).hexdigest()


def _identifier(value: str, label: str) -> str:
    if (not isinstance(value, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{1,55}", value)
            or ".." in value or value.endswith(("-", "_"))):
        raise ExtraAtlasError(f"{label}: nur 2–56 ASCII-Zeichen, beginnend mit Buchstabe")
    return value


def _asset_stem(stem: str) -> str:
    if not isinstance(stem, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,119}", stem):
        raise ExtraAtlasError(f"Unsicherer Bildname: {stem!r}")
    if stem != stem.strip() or ".." in stem or stem.endswith("."):
        raise ExtraAtlasError(f"Bildname enthält unsichere Leer-/Punkt-Folgen: {stem!r}")
    return stem


def _in_project(path: str | Path, section: str, *, existing: bool) -> Path:
    raw = Path(path)
    if not raw.is_absolute():
        raw = ROOT / raw
    safe_root = (ROOT / section).resolve()
    actual = raw.resolve(strict=False)
    if actual == safe_root or not actual.is_relative_to(safe_root):
        raise ExtraAtlasError(f"Nur echte Unterordner von {safe_root} zulässig: {actual}")
    if existing and (not actual.exists() or not actual.is_dir()):
        raise ExtraAtlasError(f"Eingabeordner fehlt: {actual}")
    current = raw
    while current != current.parent:
        if current.is_symlink():
            raise ExtraAtlasError(f"Symbolischer Pfad nicht zugelassen: {current}")
        current = current.parent
    return actual


def _read_only_gui(path: Path) -> Path:
    gui = path.resolve(strict=True)
    if not gui.is_dir() or gui.is_symlink():
        raise ExtraAtlasError("Noesis-GUI-Referenzverzeichnis fehlt")
    app = gui / "XAMLResources" / "ApplicationResources.xaml"
    if not app.is_file() or app.is_symlink():
        raise ExtraAtlasError("Originale ApplicationResources.xaml fehlt")
    return gui


def _native_target_asset(gui: Path, game_asset: str | Path) -> dict:
    """Bind the new UI override to the *same* real SHCDE installation.

    Every existing game atlas is a native Unity Texture2D, not a loose PNG.
    Additional PNGs are a proposed Noesis override; this check proves source
    build identity and native geometry, not successful loading at runtime.
    """
    file = Path(game_asset)
    if (file.name != "globalgamemanagers.assets" or file.is_symlink()
            or not file.is_file()):
        raise ExtraAtlasError("Ungültige SHCDE globalgamemanagers.assets")
    file = file.resolve(strict=True)
    expected_gui = (
        file.parent.parent / "BepInEx" / "plugins" / "000shcdese" /
        "Override" / "Assets" / "GUI"
    ).resolve()
    if gui != expected_gui:
        raise ExtraAtlasError("Noesis-Originale und Unity-Asset müssen zur selben SHCDE-Installation gehören")
    import UnityPy

    sizes = {
        "UI-MasterAtlas": (8192, 8192),
        "UI-TrailAtlas": (8192, 8192),
        "UI-Colour1Atlas": (4096, 4096),
        "UI-Colour2Atlas": (4096, 4096),
    }
    env = UnityPy.load(str(file))
    found = {}
    for obj in env.objects:
        if obj.type.name != "Texture2D":
            continue
        name = obj.peek_name()
        if name not in sizes:
            continue
        if name in found:
            raise ExtraAtlasError(f"Doppelte Unity-UI-Textur: {name}")
        data = obj.read()
        if (int(data.m_Width), int(data.m_Height)) != sizes[name]:
            raise ExtraAtlasError(f"Original-UI-Abmessungen stimmen nicht: {name}")
        if int(data.m_TextureFormat) != 25:
            raise ExtraAtlasError(f"UI-Originaltextur hat nicht das erwartete BC7-Format: {name}")
        found[name] = {
            "path_id": str(obj.path_id),
            "width": int(data.m_Width),
            "height": int(data.m_Height),
            "texture_format": int(data.m_TextureFormat),
        }
    if set(found) != set(sizes):
        raise ExtraAtlasError("Die vier nativen SHCDE-UI-Texturen fehlen")
    return {
        "asset": str(file),
        "sha256": _sha(file),
        "native_unity_textures": found,
        "offline_only_no_gameplay_certification": True,
    }


def _references(gui: Path) -> tuple[set[str], bytes, dict]:
    """Block name collisions with existing original GUI resource keys."""
    keys: set[str] = set()
    collision_counter: dict[str, str] = {}
    references = {}
    filenames = [p for group in ("Sprites", "XAMLResources")
                 for p in sorted((gui / group).rglob("*.xaml"))
                 if p.is_file()]
    if len(filenames) > 1000:
        raise ExtraAtlasError("Ungewöhnlich viele Noesis-Ressourcen-Dictionaries")
    # Actual SHCDE originals include non-XML payload AFTER the closing tag
    # in FRONT_Story.xaml. Do not reject an otherwise usable original resource
    # collection, and do not edit/truncate those unrelated XAML files.
    # Scan x:Key attributes conservatively, including keys on markup which
    # ElementTree cannot parse due to an appended binary resource table.
    key_pattern = re.compile(rb'\bx:Key\s*=\s*(["\x27])([^"\x27]{1,240})\1')
    for file in filenames:
        if file.is_symlink() or not file.resolve().is_relative_to(gui):
            raise ExtraAtlasError("Noesis-XAML-Verknüpfungen sind nicht erlaubt")
        if file.stat().st_size > 10_000_000:
            raise ExtraAtlasError("Ungewöhnlich großes Noesis-XAML-Dictionary")
        data = file.read_bytes()
        for match in key_pattern.finditer(data):
            raw_key = match.group(2)
            try:
                from html import unescape
                key = unescape(raw_key.decode("utf-8"))
            except UnicodeError:
                raise ExtraAtlasError(f"Ungültiger x:Key im Original: {file.name}")
            folded = key.casefold()
            if folded not in collision_counter:
                collision_counter[folded] = key
            keys.add(folded)
        if file.name in (
            "UI-MasterAtlas.xaml", "UI-TrailAtlas.xaml",
            "UI-Colour1Atlas.xaml", "UI-Colour2Atlas.xaml",
        ):
            # These four native dictionaries must be valid standalone XAML.
            try:
                ET.fromstring(data)
            except ET.ParseError as exc:
                raise ExtraAtlasError(f"SHCDE Atlas-XAML defekt: {file.name}: {exc}") from exc
            references[file.name] = hashlib.sha256(data).hexdigest()
    if len(references) != 4:
        raise ExtraAtlasError("SHCDE verlangt alle vier originalen Atlasdictionaries")
    app = gui / "XAMLResources" / "ApplicationResources.xaml"
    original = app.read_bytes()
    try:
        root = ET.fromstring(original)
    except ET.ParseError as exc:
        raise ExtraAtlasError(f"ApplicationResources.xaml ungültig: {exc}") from exc
    source_attr = [e.attrib.get("Source") for e in root.iter()
                   if "Source" in e.attrib]
    expected = {
        "../Sprites/UI-MasterAtlas.xaml",
        "../Sprites/UI-TrailAtlas.xaml",
        "../Sprites/UI-Colour1Atlas.xaml",
        "../Sprites/UI-Colour2Atlas.xaml",
    }
    if not expected.issubset(source_attr):
        raise ExtraAtlasError("Die vier Originalatlanten fehlen in der zentralen Noesis-Ressourcenliste")
    return keys, original, references


@dataclass(frozen=True)
class Asset:
    key: str
    path: Path
    width: int
    height: int
    sha256: str
    rgba_sha256: str


@dataclass
class Page:
    name: str
    size: int
    gutter: int
    x: int = field(init=False)
    y: int = field(init=False)
    row_height: int = 0
    entries: list[tuple[Asset, tuple[int, int, int, int]]] = field(default_factory=list)

    def __post_init__(self):
        self.x = self.gutter
        self.y = self.gutter

    def allocate(self, asset: Asset) -> tuple[int, int, int, int] | None:
        stride_x = asset.width + self.gutter
        stride_y = asset.height + self.gutter
        if asset.width + 2 * self.gutter > self.size or asset.height + 2 * self.gutter > self.size:
            return None
        x, y, line_height = self.x, self.y, self.row_height
        if x + stride_x > self.size:
            x = self.gutter
            y += line_height
            line_height = 0
        if y + stride_y > self.size:
            return None
        rectangle = (x, y, asset.width, asset.height)
        self.x = x + stride_x
        self.y = y
        self.row_height = max(line_height, stride_y)
        self.entries.append((asset, rectangle))
        return rectangle


def _collect_assets(folder: Path, prefix: str, keys: set[str]) -> list[Asset]:
    files = sorted([f for f in folder.iterdir() if f.is_file()],
                   key=lambda p: p.name.casefold())
    if not files or len(files) > MAX_INPUTS:
        raise ExtraAtlasError("Der Eingabeordner benötigt 1 bis 8192 PNG-Dateien")
    used: set[str] = set()
    assets = []
    for file in files:
        if file.suffix.casefold() != ".png" or file.is_symlink():
            raise ExtraAtlasError(f"Nur reguläre PNG-Dateien erlaubt: {file.name}")
        stem = _asset_stem(file.stem)
        key = f"{prefix}.{stem}"
        folded = key.casefold()
        if folded in used or folded in keys:
            raise ExtraAtlasError(f"Doppelter oder bereits bestehender Noesis-Schlüssel: {key}")
        used.add(folded)
        with Image.open(file) as image:
            if image.format != "PNG":
                raise ExtraAtlasError("Das angegebene Bild ist keine echte PNG-Datei")
            width, height = image.size
            if width < 1 or height < 1 or width * height > MAX_ASSET_PIXELS:
                raise ExtraAtlasError(f"Neue Grafik außerhalb der Größenbegrenzung: {key}")
            rgba_sha = _pixel_sha(image)
        assets.append(Asset(key, file, width, height, _sha(file), rgba_sha))
    return assets


def _layout(assets: list[Asset], stem: str, size: int, gutter: int,
            max_pages: int) -> list[Page]:
    if size not in SHEET_SIZES:
        raise ExtraAtlasError(f"Blattgröße muss eine der Größen {SHEET_SIZES} sein")
    if type(gutter) is not int or not (2 <= gutter <= 64):
        raise ExtraAtlasError("Atlasabstand muss zwischen 2 und 64 Pixel liegen")
    if type(max_pages) is not int or not (1 <= max_pages <= MAX_PAGES):
        raise ExtraAtlasError("Nicht mehr als 32 Atlasblätter zulässig")
    pages: list[Page] = []
    for asset in sorted(assets, key=lambda item: (-item.height, -item.width, item.key.casefold())):
        if asset.width + 2*gutter > size or asset.height + 2*gutter > size:
            raise ExtraAtlasError(f"Grafik größer als das gewünschte Atlasblatt: {asset.key}")
        placed = False
        for page in pages:
            if page.allocate(asset) is not None:
                placed = True
                break
        if placed:
            continue
        if len(pages) >= max_pages:
            raise ExtraAtlasError("Zusätzliche Atlasblätter überschreiten die bewusste Seitenbegrenzung")
        page = Page(f"{stem}-{len(pages) + 1:03d}", size, gutter)
        assert page.allocate(asset) is not None
        pages.append(page)
    return pages


def _page_xaml(page: Page, existing: set[str]) -> bytes:
    if page.name.casefold() in existing:
        raise ExtraAtlasError(f"Atlas-Schlüssel überschneidet bereits eine Noesis-Ressource: {page.name}")
    head = [
        '<ResourceDictionary xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" '
        'xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml">',
        f'  <BitmapImage x:Key="{page.name}" UriSource="{page.name}.png"/>',
    ]
    for asset, (x, y, w, h) in sorted(page.entries, key=lambda item: item[0].key.casefold()):
        key = escape(asset.key, {'"': "&quot;"})
        head.append(
            f'  <CroppedBitmap x:Key="{key}" Source="{{StaticResource {page.name}}}" '
            f'SourceRect="{x},{y},{w},{h}"/>'
        )
    head.append("</ResourceDictionary>")
    result = ("\n".join(head) + "\n").encode("utf-8")
    ET.fromstring(result)
    return result


def _updated_resources(original: bytes, pages: list[Page]) -> bytes:
    # Byte-preserving insertion. Leave ALL legacy Noesis resources unchanged.
    anchor = b'<ResourceDictionary Source="../Sprites/UI-Colour2Atlas.xaml" />'
    if original.count(anchor) != 1:
        raise ExtraAtlasError("SHCDE-Atlas-Dictionary-Anker fehlt oder ist mehrfach vorhanden")
    newline = b"\r\n" if b"\r\n" in original else b"\n"
    prefix = b""
    for page in pages:
        line = f'        <ResourceDictionary Source="../Sprites/{page.name}.xaml" />'.encode("ascii")
        if line in original:
            raise ExtraAtlasError(f"Zusätzliches Blatt {page.name} ist bereits eingetragen")
        prefix += newline + line
    patched = original.replace(anchor, anchor + prefix)
    doc = ET.fromstring(patched)
    declared = [e.attrib.get("Source") for e in doc.iter() if e.attrib.get("Source")]
    for page in pages:
        if declared.count("../Sprites/" + page.name + ".xaml") != 1:
            raise ExtraAtlasError("Neues Noesis-Ressourcendictionary nicht genau einmal eingebunden")
    return patched


def _write_page(page: Page, destination: Path, original_keys: set[str]) -> dict:
    target = destination / REL_SPRITES
    target.mkdir(parents=True, exist_ok=True)
    sheet = Image.new("RGBA", (page.size, page.size), (0, 0, 0, 0))
    entries: list[dict] = []
    for asset, rect in page.entries:
        x, y, width, height = rect
        if _sha(asset.path) != asset.sha256:
            raise ExtraAtlasError(f"Quell-PNG wurde während des Atlasbaus verändert: {asset.key}")
        with Image.open(asset.path) as opened:
            if opened.size != (width, height):
                raise ExtraAtlasError(f"Quelldimension verändert: {asset.key}")
            picture = opened.convert("RGBA")
        if _pixel_sha(picture) != asset.rgba_sha256:
            raise ExtraAtlasError("Quellpixel-SHA änderte sich während des Packens")
        sheet.paste(picture, (x, y))
        entries.append({
            "key": asset.key, "source_file": asset.path.name,
            "source_file_sha256": asset.sha256,
            "source_rgba_sha256": asset.rgba_sha256,
            "rect": [x, y, width, height], "page": page.name,
        })
    target_png = target / (page.name + ".png")
    target_xaml = target / (page.name + ".xaml")
    sheet.save(target_png, format="PNG", optimize=True)
    target_xaml.write_bytes(_page_xaml(page, original_keys))
    with Image.open(target_png) as reopened:
        if reopened.size != (page.size, page.size):
            raise ExtraAtlasError("Erzeugtes Atlasblatt wurde mit falscher Größe gespeichert")
        atlas = reopened.convert("RGBA")
    for entry in entries:
        x, y, w, h = entry["rect"]
        result = atlas.crop((x, y, x + w, y + h))
        if _pixel_sha(result) != entry["source_rgba_sha256"]:
            raise ExtraAtlasError(f"Pixelidentität des Atlas-Ausschnitts fehlgeschlagen: {entry['key']}")
    return {
        "name": page.name, "size": [page.size, page.size],
        "gutter": page.gutter,
        "png": str(REL_SPRITES / target_png.name).replace("\\", "/"),
        "png_sha256": _sha(target_png),
        "xaml": str(REL_SPRITES / target_xaml.name).replace("\\", "/"),
        "xaml_sha256": _sha(target_xaml),
        "sprites": sorted(entries, key=lambda row: row["key"].casefold()),
    }


def _commit_directory(stage: Path, destination: Path, replace: bool):
    backup = destination.with_name(destination.name + ".extra-atlas-old")
    if backup.exists():
        raise ExtraAtlasError("Nicht aufgeräumte frühere Atlas-Sicherung vorhanden")
    if destination.exists() and not replace:
        raise ExtraAtlasError("Ziel besteht bereits, nur --replace darf ein Paket ersetzen")
    if destination.exists():
        if destination.is_symlink() or not destination.is_dir():
            raise ExtraAtlasError("Ziel ist kein regulärer Ausgabeordner")
        os.replace(destination, backup)
    try:
        os.replace(stage, destination)
    except Exception:
        if backup.exists() and not destination.exists():
            os.replace(backup, destination)
        raise
    if backup.exists():
        shutil.rmtree(backup)


def build(
    source_dir: str | Path, gui_originals: str | Path, output: str | Path, *,
    stem: str = "SpriteSuiteExtra", prefix: str = "Extra",
    size: int = 1024, gutter: int = 2, max_pages: int = 16,
    replace: bool = False, target_game: str | Path | None = None,
) -> dict:
    source = _in_project(source_dir, "work", existing=True)
    target = _in_project(output, "dist", existing=False)
    stem = _identifier(stem, "Atlas-Grundname")
    prefix = _identifier(prefix, "Namensraum")
    gui = _read_only_gui(Path(gui_originals))
    if target.exists() and not replace:
        raise ExtraAtlasError("Ausgabepaket besteht bereits und --replace wurde nicht bestätigt")
    original_keys, app_original, dictionaries = _references(gui)
    native = _native_target_asset(gui, target_game) if target_game else None
    assets = _collect_assets(source, prefix, original_keys)
    pages = _layout(assets, stem, size, gutter, max_pages)
    for page in pages:
        if page.name.casefold() in original_keys or page.name.casefold() in {
            asset.key.casefold() for asset in assets
        }:
            raise ExtraAtlasError(f"Name des neuen Atlasblatts kollidiert: {page.name}")
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix="." + target.name + "-building-", dir=target.parent))
    try:
        sheets = [_write_page(page, stage, original_keys) for page in pages]
        destination_app = stage / REL_RESOURCES / "ApplicationResources.xaml"
        destination_app.parent.mkdir(parents=True, exist_ok=True)
        patched_app = _updated_resources(app_original, pages)
        destination_app.write_bytes(patched_app)
        note = (
            "# SHCDE zusätzliche UI-Atlasblätter – lokaler Kandidat\n\n"
            "Enthält neue PNG-Bildatlanten, Noesis-XAML-CroppedBitmaps und "
            "eine kopierte ApplicationResources.xaml mit neuen Dictionary-Verweisen.\n"
            "Original-Atlanten und installierte Spiele wurden nicht geändert.\n"
            "Neues XAML ist nicht automatisch durch die HUD-Zustandslogik referenziert.\n"
            "Für sichtbare neue HUD-Elemente braucht die Anwendung zusätzlich "
            "bewusst angepasste XAML-Views/Bindings. Runtime-Laden nicht nachgewiesen.\n"
            "Neue Assets als individuelle PNGs unter dem Quellordner weiterbearbeiten; "
            "bei geändertem Quellstand nur mit --replace neu erzeugen.\n"
        )
        (stage / "LIESMICH.md").write_text(note, encoding="utf-8")
        manifest = {
            "schema": SCHEMA, "atlas_stem": stem, "key_namespace": prefix,
            "source_folder": str(source),
            "source_images_count": len(assets),
            "page_size": size, "gutter": gutter,
            "original_gui_reference": str(gui),
            "original_application_resources_sha256": hashlib.sha256(app_original).hexdigest(),
            "application_resources": str(REL_RESOURCES / destination_app.name).replace("\\", "/"),
            "application_resources_sha256": _sha(destination_app),
            "original_dictionary_sha256": dictionaries,
            "native_shcde_source": native,
            "pages": sheets,
            "output_type": "noesis-ui-extra-atlas-candidate",
            "original_game_installation_modified": False,
            "new_hud_logic_added": False,
            "runtime_game_tested": False,
        }
        (stage / MANIFEST).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        _verify_files(stage, manifest, check_sources=True, check_reference=True)
        _commit_directory(stage, target, replace)
        return manifest
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def _exact_file(root: Path, rel: str) -> Path:
    """Read a manifest file only when it is contained and not a symlink."""
    if not isinstance(rel, str):
        raise ExtraAtlasError("Manifest enthält keinen regulären relativen Pfad")
    p = Path(rel)
    if (p.is_absolute() or ".." in p.parts or not p.parts
            or "\\" in rel or ":" in rel or "\x00" in rel):
        raise ExtraAtlasError("Unsicherer Pfad in Atlas-Manifest")
    resolved = root / p
    if not resolved.is_file() or resolved.is_symlink() or not resolved.resolve().is_relative_to(root.resolve()):
        raise ExtraAtlasError(f"Ausgabedatei fehlt oder ist verlinkt: {rel}")
    return resolved


def _rectangles_nonoverlapping(rows: list[dict], size: int, gutter: int) -> None:
    # Inclusive gutter separation, no adjacent/overlapping sprite pixels.
    active: list[dict] = []
    for row in sorted(rows, key=lambda e: (e["rect"][0], e["rect"][1])):
        x, y, w, h = row["rect"]
        if any(type(v) is not int for v in (x, y, w, h)):
            raise ExtraAtlasError("Atlasrechtecke benötigen ganzzahlige Koordinaten")
        if x < gutter or y < gutter or w < 1 or h < 1 or x+w+gutter > size or y+h+gutter > size:
            raise ExtraAtlasError("Atlasrechteck kollidiert mit dem Seitenrand")
        active = [other for other in active if other["rect"][0] + other["rect"][2] + gutter > x]
        for prior in active:
            a, b, c, e = prior["rect"]
            if (a < x+w+gutter and x < a+c+gutter and
                    b < y+h+gutter and y < b+e+gutter):
                raise ExtraAtlasError("Atlasrechtecke einschließlich Sicherheitsabstand überlappen")
        active.append(row)


def _verify_files(root: Path, manifest: dict, *,
                  check_sources: bool, check_reference: bool) -> dict:
    if manifest.get("schema") != SCHEMA or not isinstance(manifest.get("pages"), list):
        raise ExtraAtlasError("Unbekannte Atlas-Manifestversion")
    if not (1 <= len(manifest["pages"]) <= MAX_PAGES):
        raise ExtraAtlasError("Ungültige Seitenanzahl")
    page_size = manifest.get("page_size")
    gutter = manifest.get("gutter")
    if page_size not in SHEET_SIZES or type(gutter) is not int or not 2 <= gutter <= 64:
        raise ExtraAtlasError("Manifestspeicher-/Abstandsgrenzen ungültig")
    manifest_source = (
        _in_project(manifest.get("source_folder"), "work", existing=True)
        if check_sources else None
    )
    manifest_gui = (
        _read_only_gui(Path(manifest.get("original_gui_reference")))
        if check_reference else None
    )
    app_path = str(REL_RESOURCES / "ApplicationResources.xaml").replace("\\", "/")
    if manifest.get("application_resources") != app_path:
        raise ExtraAtlasError("Manifest referenziert eine fremde Noesis-Hauptdatei")
    patched = _exact_file(root, app_path).read_bytes()
    if hashlib.sha256(patched).hexdigest() != manifest.get("application_resources_sha256"):
        raise ExtraAtlasError("Gepatchte Noesis-Hauptdatei hat einen falschen SHA-256")

    keys: set[str] = set()
    seen_sources: set[str] = set()
    page_names: set[str] = set()
    expected_files = {app_path, MANIFEST, "LIESMICH.md"}
    total_sprites = 0
    for page in manifest["pages"]:
        name = _identifier(page.get("name"), "Atlasblatt")
        if name.casefold() in page_names or name.casefold() in keys:
            raise ExtraAtlasError("Doppelter neuer Atlasname")
        page_names.add(name.casefold())
        if page.get("size") != [page_size, page_size] or page.get("gutter") != gutter:
            raise ExtraAtlasError("Atlasgröße oder Abstand widerspricht Manifest")
        pngrel = str(REL_SPRITES / (name + ".png")).replace("\\", "/")
        xamlrel = str(REL_SPRITES / (name + ".xaml")).replace("\\", "/")
        if page.get("png") != pngrel or page.get("xaml") != xamlrel:
            raise ExtraAtlasError("Atlasdateinamen im Manifest sind manipuliert")
        expected_files.update((pngrel, xamlrel))
        png = _exact_file(root, pngrel)
        xaml = _exact_file(root, xamlrel)
        if _sha(png) != page.get("png_sha256") or _sha(xaml) != page.get("xaml_sha256"):
            raise ExtraAtlasError("Erstellter PNG-Atlas oder XAML wurde nachträglich verändert")

        xml = ET.fromstring(xaml.read_bytes())
        bitmap_nodes = [e for e in xml if e.tag.endswith("BitmapImage")]
        crop_nodes = [e for e in xml if e.tag.endswith("CroppedBitmap")]
        if len(bitmap_nodes) != 1 or bitmap_nodes[0].attrib.get(NS_X + "Key") != name:
            raise ExtraAtlasError("Falsche BitmapImage-Grundressource in XAML")
        if bitmap_nodes[0].attrib.get("UriSource") != name + ".png":
            raise ExtraAtlasError("Atlas-XAML referenziert eine fremde PNG-Textur")
        rows = page.get("sprites")
        if not isinstance(rows, list) or not rows:
            raise ExtraAtlasError("Ein neues Atlasblatt benötigt Bilder")
        if len(crop_nodes) != len(rows):
            raise ExtraAtlasError("XAML-Crops und Manifest enthalten verschieden viele Einträge")
        _rectangles_nonoverlapping(rows, page_size, gutter)
        xaml_keys = {}
        for e in crop_nodes:
            key = e.attrib.get(NS_X + "Key", "")
            if key.casefold() in xaml_keys:
                raise ExtraAtlasError("Doppelter Noesis-CroppedBitmap-Schlüssel")
            xaml_keys[key.casefold()] = e

        with Image.open(png) as original:
            if original.size != (page_size, page_size) or original.mode != "RGBA":
                raise ExtraAtlasError("Erstellter Atlas hat nicht das vereinbarte RGBA-Format")
            decoded = original.convert("RGBA")
        expected = Image.new("RGBA", (page_size, page_size), (0, 0, 0, 0))
        for item in rows:
            key = item.get("key", "")
            if (not isinstance(key, str) or key.casefold() in keys
                    or key.casefold() in page_names):
                raise ExtraAtlasError("Doppelter oder fremder Noesis-Sprite-Schlüssel")
            keys.add(key.casefold())
            element = xaml_keys.get(key.casefold())
            x, y, w, h = item["rect"]
            if (element is None or element.get("Source") != "{StaticResource " + name + "}"
                    or element.get("SourceRect") != f"{x},{y},{w},{h}"):
                raise ExtraAtlasError(f"Noesis-XAML-/Manifest-Rechteck weicht ab: {key}")
            if check_sources:
                source_name = item.get("source_file")
                _asset_stem(Path(source_name).stem)
                if (Path(source_name).name != source_name or "\\" in source_name
                        or "/" in source_name or not source_name.lower().endswith(".png")):
                    raise ExtraAtlasError("Unsicherer Eingabe-PNG-Name im Manifest")
                if source_name.casefold() in seen_sources:
                    raise ExtraAtlasError("Quell-PNG mehrfach im Atlas verwendet")
                seen_sources.add(source_name.casefold())
                src = manifest_source / source_name
                if src.is_symlink() or not src.is_file():
                    raise ExtraAtlasError("Original-Eingabe-PNG fehlt oder ist verlinkt")
                if _sha(src) != item.get("source_file_sha256"):
                    raise ExtraAtlasError(f"Eingabe-PNG wurde verändert: {source_name}")
                with Image.open(src) as image:
                    if image.size != (w, h) or _pixel_sha(image) != item.get("source_rgba_sha256"):
                        raise ExtraAtlasError("Eingabegröße/-pixel stimmen nicht mit dem Atlas überein")
                    rgba = image.convert("RGBA")
                expected.paste(rgba, (x, y))
            if _pixel_sha(decoded.crop((x, y, x+w, y+h))) != item.get("source_rgba_sha256"):
                raise ExtraAtlasError(f"Atlas-Pixelausschnitt unterscheidet sich: {key}")
            total_sprites += 1
        if set(xaml_keys) != {r["key"].casefold() for r in rows}:
            raise ExtraAtlasError("Atlas-XAML enthält unerwartete Ressourcen")
        if check_sources and decoded.tobytes() != expected.tobytes():
            raise ExtraAtlasError("Nicht deklarierte/gefälschte Pixel im Atlasblatt")
    if total_sprites != manifest.get("source_images_count"):
        raise ExtraAtlasError("Erstellte Spritezahl widerspricht dem Quellbestand")
    if len(seen_sources) != total_sprites and check_sources:
        raise ExtraAtlasError("Quelldateien im Manifest unvollständig")
    all_files = {
        str(p.relative_to(root)).replace("\\", "/")
        for p in root.rglob("*") if p.is_file()
    }
    if all_files != expected_files:
        raise ExtraAtlasError("Paket hat fehlende oder unerwartete Dateien")
    if manifest_gui is not None:
        native_keys, app_original, dictionaries = _references(manifest_gui)
        if manifest.get("original_dictionary_sha256") != dictionaries:
            raise ExtraAtlasError("Native SHCDE-Atlasdictionaries seit Erzeugung verändert")
        if hashlib.sha256(app_original).hexdigest() != manifest.get(
            "original_application_resources_sha256"
        ):
            raise ExtraAtlasError("Native SHCDE ApplicationResources wurde verändert")
        if any(key in native_keys for key in keys | page_names):
            raise ExtraAtlasError("Neue Ressourcen kollidieren mit ursprünglichen SHCDE-Keys")
        simulated = _updated_resources(
            app_original, [Page(page["name"], page_size, gutter)
                           for page in manifest["pages"]]
        )
        if patched != simulated:
            raise ExtraAtlasError("Noesis-Dictionary-Merge verändert Originalinhalt")
        if manifest.get("native_shcde_source") is not None:
            record = manifest["native_shcde_source"]
            actual = _native_target_asset(manifest_gui, record.get("asset"))
            if record != actual:
                raise ExtraAtlasError("Native SHCDE-Spielquelle oder Texturen haben sich verändert")
    return {
        "pages_verified": len(page_names),
        "images_verified": total_sprites,
        "original_gui_checked": check_reference,
        "source_pngs_checked": check_sources,
        "runtime_game_tested": False,
        "native_shcde_source_pinned": bool(manifest.get("native_shcde_source")),
    }


def verify(destination: str | Path, *, check_sources=True, check_reference=True):
    root = _in_project(destination, "dist", existing=True)
    manifest = json.loads(_exact_file(root, MANIFEST).read_text(encoding="utf-8"))
    return _verify_files(root, manifest, check_sources=check_sources,
                         check_reference=check_reference)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    cmds = parser.add_subparsers(dest="action", required=True)
    b = cmds.add_parser("build", help="Separate neue UI-Atlasblätter aus eigenem PNG-Ordner bauen")
    b.add_argument("--source", required=True)
    b.add_argument("--gui-reference", required=True)
    b.add_argument("--out", required=True)
    b.add_argument("--stem", default="SpriteSuiteExtra")
    b.add_argument("--namespace", default="Extra")
    b.add_argument("--size", type=int, choices=SHEET_SIZES, default=1024)
    b.add_argument("--gutter", type=int, default=2)
    b.add_argument("--max-pages", type=int, default=16)
    b.add_argument("--replace", action="store_true")
    b.add_argument("--target-game", help="Optional: exakt passende SHCDE-Unity-Quelldatei")
    v = cmds.add_parser("verify", help="Atlaskandidat, XAML und Pixel erneut prüfen")
    v.add_argument("--from", dest="folder", required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == "build":
            result = build(args.source, args.gui_reference, args.out,
                           stem=args.stem, prefix=args.namespace,
                           size=args.size, gutter=args.gutter,
                           max_pages=args.max_pages, replace=args.replace,
                           target_game=args.target_game)
            summary = {"new_pages": len(result["pages"]), "new_assets": result["source_images_count"],
                       "output": str(_in_project(args.out, "dist", existing=True)),
                       "game_installation_modified": False}
        else:
            summary = verify(args.folder)
        print(json.dumps(summary, indent=2, ensure_ascii=False), flush=True)
        return 0
    except (ExtraAtlasError, ValueError, OSError, RuntimeError, ET.ParseError) as exc:
        print("EXTRA_UI_ATLAS_ABGELEHNT:", exc, file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

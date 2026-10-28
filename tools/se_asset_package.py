"""Version-neutral static SHCDE asset-mod packaging; no C# runtime or SE install.

Prepares an asset-only mod folder for an already installed Script Extender.
Do not claim identical Asset/XAML API behavior in every historical release.
The builder neither detects nor pins a Script Extender version and never
installs or changes a game, plugin or Steam directory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import sys
import tempfile
from xml.parsers import expat
import zipfile

from PIL import Image, UnidentifiedImageError

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "work"
OUT = WORK / "se-asset-mods"
_GUID = re.compile(r"[a-zA-Z][a-zA-Z0-9._-]{2,63}\Z")
_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+\Z")
_VALID_START = frozenset({"Override", "Patches"})
_MAX_FILES = 10000
_MAX_BYTES = 2 * 1024**3
_MAX_FILE = 512 * 1024**2
_MAX_XAML = 2 * 1024**2
_XAML_OPERATIONS = frozenset({
    "Add", "Remove", "Replace", "InsertBefore", "InsertAfter",
    "SetAttribute", "AddNamespace",
})


class AssetModError(RuntimeError):
    """Unsafe, incomplete or unverified static asset-mod package."""


def _inside_work(folder: Path | str, *, existing: bool) -> Path:
    base = WORK.resolve()
    if not base.is_dir():
        raise AssetModError("Sprite-Suite work/-Verzeichnis fehlt")
    raw = Path(folder)
    if not raw.is_absolute():
        raw = ROOT / raw
    if raw.is_symlink():
        raise AssetModError("Verknüpfte Quell- oder Zielordner nicht zulässig")
    resolved = raw.resolve(strict=existing)
    if resolved == base or not resolved.is_relative_to(base):
        raise AssetModError("Ein- und Ausgabe nur unter SpriteSuite/work/")
    for candidate in (raw, *raw.parents):
        if candidate == base:
            break
        if candidate.is_symlink():
            raise AssetModError("Symbolische Ordnerverknüpfung im Pfad")
    return resolved


def _relative_key(path: Path) -> str:
    parts = path.parts
    if not parts or parts[0] not in _VALID_START:
        raise AssetModError("Dateien müssen unter Override/ oder Patches/ liegen")
    if any(
        not part or part in (".", "..") or part.endswith((" ", "."))
        or ":" in part or "\\" in part or os.path.isreserved(part)
        for part in parts
    ):
        raise AssetModError("Unsicherer Asset-Pfad")
    posix = PurePosixPath(*parts).as_posix()
    win = PureWindowsPath(posix)
    if win.is_absolute() or win.drive:
        raise AssetModError("Ungültiger Windows-Assetpfad")
    return posix


def _check_xml(file: Path, *, patch: bool) -> None:
    if file.stat().st_size > _MAX_XAML:
        raise AssetModError("XAML-Datei überschreitet die 2-MB-Grenze")
    raw = file.read_bytes()
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise AssetModError("DOCTYPE/ENTITY ist in Asset-XAML verboten")
    parser = expat.ParserCreate()  # Raw XML parser accepts Noesis prefixes.
    count = 0
    depth = 0
    root = None
    operation_count = 0

    def start(name: str, attrs: dict) -> None:
        nonlocal depth, root, operation_count, count
        depth += 1
        count += 1
        if depth > 96 or count > 50000:
            raise AssetModError("XAML-Verschachtelung oder Knotenzahl ungültig")
        if root is None:
            root = name
            if patch and name not in {"Patch", "XamlPatch"}:
                raise AssetModError("XAML-Patch muss <Patch> oder <XamlPatch> verwenden")
        if patch and depth == 2:
            if name != "Operation":
                raise AssetModError("XAML-Patch darf nur Operation-Kinder enthalten")
            operation_count += 1
            if operation_count > 2000:
                raise AssetModError("Zu viele XAML-Operationen")
            op_type = attrs.get("Type")
            if op_type not in _XAML_OPERATIONS:
                raise AssetModError("Unbekannter XAML-Patch-Operationstyp")
            if op_type != "AddNamespace" and not attrs.get("XPath", "").strip():
                raise AssetModError("XAML-Patch enthält leeren XPath")
        if patch and depth == 3 and name not in {"Content"} and root in {"Patch", "XamlPatch"}:
            # Operation may have only one Content subtree for replacement
            raise AssetModError("Unbekanntes direktes Kind einer Operation")

    def end(_name: str) -> None:
        nonlocal depth
        depth -= 1

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.ExternalEntityRefHandler = lambda *unused: 0
    try:
        parser.Parse(raw, True)
    except expat.ExpatError as exc:
        raise AssetModError(f"XML-Syntax nicht gültig: {file.name}: {exc}") from exc
    if patch and operation_count < 1:
        raise AssetModError("Leere XAML-Patchdatei")


def _validate_asset(path: Path, relative: str) -> None:
    suffix = path.suffix.casefold()
    if relative.startswith("Patches/"):
        if suffix != ".xaml" or "/Assets/GUI/" not in f"/{relative}":
            raise AssetModError("Nur statische Noesis-XAML-Patches unter Patches/Assets/GUI/")
        _check_xml(path, patch=True)
        return
    if not relative.startswith("Override/"):
        raise AssetModError("Kein Asset-Override-Pfad")
    # Strictly version-neutral asset-only package: no Lua, runtime DLL, binary
    # executables, hooks or arbitrary metadata files in the mod.
    if suffix not in {".png", ".jpg", ".jpeg", ".dds", ".xaml", ".json"}:
        raise AssetModError("Nur statische PNG/JPG/DDS/XAML/JSON-Assets zugelassen")
    if not relative.startswith((
        "Override/Sprites/", "Override/Atlas/", "Override/Assets/GUI/",
    )):
        raise AssetModError("Nur GUI-/Sprite-/Atlas-Override-Pfade zugelassen")
    if suffix in {".png", ".jpg", ".jpeg"}:
        try:
            with Image.open(path) as image:
                if (image.format not in {"PNG", "JPEG"} or
                        image.width <= 0 or image.height <= 0 or
                        image.width > 16384 or image.height > 16384):
                    raise AssetModError("Bildformat oder Abmessungen ungültig")
                image.verify()
        except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
            raise AssetModError(f"PNG/JPG nicht lesbar: {relative}") from exc
    elif suffix == ".dds":
        with path.open("rb") as stream:
            if stream.read(4) != b"DDS " or len(stream.read(124)) != 124:
                raise AssetModError("DDS-Datei ohne vollständigen Header")
    elif suffix == ".xaml":
        _check_xml(path, patch=False)
    elif suffix == ".json":
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(obj, dict):
                raise AssetModError("Atlas-/Material-JSON muss Objekt sein")
        except (UnicodeError, ValueError, OSError) as exc:
            raise AssetModError(f"Asset-JSON unlesbar: {relative}") from exc


def _discover(source: Path) -> list[tuple[str, Path, int, str]]:
    if not source.is_dir():
        raise AssetModError("Asset-Mod-Quellordner fehlt")
    items = []
    folded = set()
    total = 0
    for file in sorted(source.rglob("*")):
        if file.is_symlink():
            raise AssetModError(f"Symbolische Asset-Datei: {file.name}")
        if file.is_dir():
            continue
        if not file.is_file():
            raise AssetModError(f"Kein reguläres Asset: {file.name}")
        relative = _relative_key(file.relative_to(source))
        if relative.casefold() in folded:
            raise AssetModError(f"Doppelte Assets auf Windows: {relative}")
        folded.add(relative.casefold())
        before = file.stat()
        if before.st_size > _MAX_FILE:
            raise AssetModError(f"Asset über 512 MB: {relative}")
        total += before.st_size
        if total > _MAX_BYTES:
            raise AssetModError("Asset-Paket über 2 GB")
        _validate_asset(file, relative)
        digest = hashlib.sha256()
        with file.open("rb") as stream:
            for chunk in iter(lambda: stream.read(4 * 1024**2), b""):
                digest.update(chunk)
        after = file.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise AssetModError("Quelldatei während der Prüfung geändert")
        items.append((relative, file, before.st_size, digest.hexdigest()))
        if len(items) > _MAX_FILES:
            raise AssetModError("Mehr als 10.000 Assets")
    if not items:
        raise AssetModError("Keine Override-/Patch-Dateien vorhanden")
    return items


def build(source: Path | str, guid: str, *, name: str, author: str,
          target: Path | str | None = None, version: str = "1.0.0") -> dict:
    if not _GUID.fullmatch(guid) or os.path.isreserved(guid):
        raise AssetModError("Ungültige Mod-GUID")
    if not _VERSION.fullmatch(version):
        raise AssetModError("Ungültige Mod-Version")
    if not name.strip() or len(name) > 120 or len(author) > 120:
        raise AssetModError("Mod-Name bzw. Autor zu lang oder leer")
    source_root = _inside_work(source, existing=True)
    output = _inside_work(target or (OUT / guid), existing=False)
    if (output == source_root or output.is_relative_to(source_root) or
            source_root.is_relative_to(output)):
        raise AssetModError("Quelle und Ausgabe dürfen sich nicht überschneiden")
    if output.exists() or output.with_suffix(".zip").exists():
        raise AssetModError("Asset-Mod-Paket existiert bereits – kein Überschreiben")
    files = _discover(source_root)
    info = {
        "GUID": guid, "Name": name.strip(), "Author": author.strip() or "Sprite Suite",
        "Description": "Static sprite/HUD/GUI asset pack. No runtime plugin.",
        "Version": version, "Manifest": 0, "AssetMode": "Global", "NetworkMode": 0,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".asset-mod-stage-", dir=output.parent))
    zip_stage = None
    try:
        folder = staging / guid
        folder.mkdir()
        (folder / "info.json").write_text(
            json.dumps(info, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        for relative, src, size, digest in files:
            dest = folder.joinpath(*PurePosixPath(relative).parts)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest)
            if dest.stat().st_size != size:
                raise AssetModError("Asset-Kopie hat andere Dateigröße")
            h = hashlib.sha256()
            with dest.open("rb") as stream:
                for chunk in iter(lambda: stream.read(4 * 1024**2), b""):
                    h.update(chunk)
            if h.hexdigest() != digest:
                raise AssetModError("Asset während des Paketbaus verändert")
        # Portable asset-only archive, with canonical BepInEx root. Do not
        # silently install it, including in any version of the game.
        fd, temp_name = tempfile.mkstemp(
            prefix=".asset-mod-zip-", suffix=".zip", dir=output.parent
        )
        os.close(fd)
        zip_stage = Path(temp_name)
        with zipfile.ZipFile(zip_stage, mode="w",
                             compression=zipfile.ZIP_DEFLATED) as archive:
            for asset in sorted(folder.rglob("*")):
                if asset.is_file():
                    rel = asset.relative_to(folder).as_posix()
                    archive.write(
                        asset, arcname=f"BepInEx/plugins/{guid}/{rel}"
                    )
        with zipfile.ZipFile(zip_stage, mode="r") as verified_zip:
            if verified_zip.testzip() is not None:
                raise AssetModError("ZIP-Paket CRC-Prüfung fehlgeschlagen")
        os.rename(folder, output)
        os.rename(zip_stage, output.with_suffix(".zip"))
        return {
            "schema": "sprite-suite.se-asset-only.v1",
            "guid": guid, "se_version_required": None,
            "runtime_dll": False, "source_files": len(files),
            "asset_mod_folder": str(output),
            "zip": str(output.with_suffix(".zip")),
            "manifest": info,
        }
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        if zip_stage is not None and zip_stage.exists():
            zip_stage.unlink()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True,
                        help="Arbeitsordner unter work/ mit Override/ und Patches/")
    parser.add_argument("--guid", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--author", default="")
    parser.add_argument("--out", type=Path,
                        help="Ziel unter work/, Standard work/se-asset-mods/<GUID>")
    args = parser.parse_args(argv)
    try:
        result = build(args.source, args.guid, name=args.name,
                       author=args.author, target=args.out)
    except (AssetModError, OSError, ValueError) as exc:
        print(f"ASSET_MOD_FEHLER: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

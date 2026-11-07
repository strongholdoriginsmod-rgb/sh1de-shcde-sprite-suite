"""Version-neutral SHCDE mod packaging with unrestricted editing by default.

Any existing source folder, asset path and file type can be packaged. The old
static-only compatibility checks remain available via --strict-static, but are
not imposed on normal mod creation. Building a ZIP is not a game installation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import tempfile
from xml.parsers import expat
import zipfile

from PIL import Image, UnidentifiedImageError
from suite_windows_paths import is_link_or_reparse as _linked
from suite_windows_paths import is_reserved_windows_component

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "work"
OUT = WORK / "se-asset-mods"
_GUID = re.compile(r"[a-zA-Z][a-zA-Z0-9._-]{2,63}\Z")
_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+\Z")
_VALID_START = frozenset({"Override", "Patches", "Locales"})
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
    if _linked(raw):
        raise AssetModError("Verknüpfte Quell- oder Zielordner nicht zulässig")
    resolved = raw.resolve(strict=existing)
    if resolved == base or not resolved.is_relative_to(base):
        raise AssetModError("Ein- und Ausgabe nur unter SpriteSuite/work/")
    for candidate in (raw, *raw.parents):
        if candidate == base:
            break
        if _linked(candidate):
            raise AssetModError("Symbolische Ordnerverknüpfung im Pfad")
    return resolved


def _relative_key(path: Path, *, strict_static: bool = False) -> str:
    parts = path.parts
    if strict_static and (not parts or parts[0] not in _VALID_START):
        raise AssetModError("Statischer Mod benötigt Override/, Patches/ oder Locales/")
    return mod_relative_path(path.as_posix()).as_posix()


def mod_relative_path(relative: str) -> PurePosixPath:
    """A Windows-compatible package path, independent of its resource type."""
    if not isinstance(relative, str) or any(
        not part or part in (".", "..") or part.endswith((" ", "."))
        or is_reserved_windows_component(part)
        or any(char in '\\:*?"<>|' or ord(char) < 32 for char in part)
        for part in relative.split("/")
    ):
        raise AssetModError("Unsicherer Asset-Pfad")
    return PurePosixPath(relative)


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


def _validate_locale(path: Path, relative: str) -> None:
    """Only Script Extender positional crusader.txt files, never arbitrary text."""
    parts = PurePosixPath(relative).parts
    if (len(parts) != 3 or parts[0] != "Locales" or
            not re.fullmatch(r"[a-z]{2}-[A-Z]{2}", parts[1]) or
            parts[2] != "crusader.txt" or path.stat().st_size > 2 * 1024**2):
        raise AssetModError("Only Locales/xx-XX/crusader.txt is allowed")
    raw = path.read_bytes()
    if b"\x00" in raw or b"\r" in raw or raw.startswith(b"version https://git-lfs"):
        raise AssetModError("Invalid locale file or unresolved LFS pointer")
    try:
        lines = raw.decode("utf-8-sig").splitlines()
    except UnicodeError as exc:
        raise AssetModError("Locale must be UTF-8") from exc
    if not (3 <= len(lines) <= 50000 and
            re.fullmatch(r"[A-Za-z]{2,12}", lines[0]) and
            lines[1] == ">>TEXTSTART"):
        raise AssetModError("Missing localization header")
    sections = 0
    for line in lines[2:]:
        if line.startswith(">>"):
            if not re.fullmatch(r">>[1-9][0-9]{0,2}-----", line):
                raise AssetModError("Malformed locale section")
            sections += 1
        elif not sections or len(line) > 20000:
            raise AssetModError("Malformed locale entry")
    if not sections:
        raise AssetModError("Locale contains no numbered section")


def _validate_webm(path: Path, relative: str) -> None:
    if (not relative.startswith("Override/Assets/GUI/Video/") or
            path.suffix.lower() != ".webm" or path.stat().st_size < 32 or
            path.stat().st_size > 256 * 1024**2):
        raise AssetModError("Only bounded menu WebM videos are allowed")
    with path.open("rb") as stream:
        head = stream.read(4096)
    if (not head.startswith(b"\x1a\x45\xdf\xa3") or
            b"\x42\x82\x84webm" not in head[:1024] or
            b"version https://git-lfs" in head):
        raise AssetModError("Invalid WebM header or unresolved LFS pointer")


def _validate_asset(path: Path, relative: str) -> None:
    suffix = path.suffix.casefold()
    if relative.startswith("Locales/"):
        _validate_locale(path, relative)
        return
    if suffix == ".webm":
        _validate_webm(path, relative)
        return
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


def _discover(source: Path, *, strict_static: bool = False) -> list[tuple[str, Path, int, str]]:
    if not source.is_dir():
        raise AssetModError("Asset-Mod-Quellordner fehlt")
    items = []
    folded = set()
    total = 0
    for file in sorted(source.rglob("*")):
        if strict_static and _linked(file):
            raise AssetModError(f"Symbolische Asset-Datei: {file.name}")
        if file.is_dir():
            continue
        if not file.is_file():
            raise AssetModError(f"Kein reguläres Asset: {file.name}")
        relative = _relative_key(file.relative_to(source), strict_static=strict_static)
        if relative.casefold() in folded:
            raise AssetModError(f"Doppelte Assets auf Windows: {relative}")
        folded.add(relative.casefold())
        before = file.stat()
        if strict_static and before.st_size > _MAX_FILE:
            raise AssetModError(f"Asset über 512 MB: {relative}")
        total += before.st_size
        if strict_static and total > _MAX_BYTES:
            raise AssetModError("Asset-Paket über 2 GB")
        if strict_static:
            _validate_asset(file, relative)
        digest = hashlib.sha256()
        with file.open("rb") as stream:
            for chunk in iter(lambda: stream.read(4 * 1024**2), b""):
                digest.update(chunk)
        after = file.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise AssetModError("Quelldatei während der Prüfung geändert")
        items.append((relative, file, before.st_size, digest.hexdigest()))
        if strict_static and len(items) > _MAX_FILES:
            raise AssetModError("Mehr als 10.000 Assets")
    if not items:
        raise AssetModError("Keine Override-/Patch-Dateien vorhanden")
    return items


def package_zip_path(output: Path) -> Path:
    return output.with_name(output.name + ".zip")


def build(source: Path | str, guid: str, *, name: str, author: str,
          target: Path | str | None = None, version: str = "1.0.0",
          strict_static: bool = False) -> dict:
    if (not isinstance(guid, str) or not guid or guid in (".", "..") or
            any(ch in guid for ch in '/\\:*?"<>|\x00') or
            is_reserved_windows_component(guid) or
            (strict_static and not _GUID.fullmatch(guid))):
        raise AssetModError("Mod-Kennung ist kein verwendbarer Ordnername")
    if not isinstance(version, str) or not version.strip() or (strict_static and not _VERSION.fullmatch(version)):
        raise AssetModError("Mod-Version fehlt oder ist im optionalen statischen Modus nicht verwendbar")
    if not name.strip() or (strict_static and (len(name) > 120 or len(author) > 120)):
        raise AssetModError("Mod-Name fehlt oder überschreitet die optionale statische Mod-Grenze")
    if strict_static:
        source_root = _inside_work(source, existing=True)
        output = _inside_work(target or (OUT / guid), existing=False)
    else:
        source_root = Path(source).expanduser().resolve(strict=True)
        output = Path(target or (OUT / guid)).expanduser().resolve(strict=False)
    if (output == source_root or output.is_relative_to(source_root) or
            source_root.is_relative_to(output)):
        raise AssetModError("Quelle und Ausgabe dürfen sich nicht überschneiden")
    archive_path = package_zip_path(output)
    if output.exists() or archive_path.exists():
        raise AssetModError("Asset-Mod-Paket existiert bereits – kein Überschreiben")
    files = _discover(source_root, strict_static=strict_static)
    info = {
        "GUID": guid, "Name": name.strip(), "Author": author.strip() or "Sprite Suite",
        "Description": ("Static asset pack" if strict_static else "Custom mod bundle"),
        "Version": version, "Manifest": 0, "AssetMode": "Global", "NetworkMode": 0,
    }
    supplied_info = next((src for relative, src, _, _ in files
                          if relative.casefold() == "info.json"), None)
    if supplied_info is not None:
        # Keep a user-authored manifest exactly as supplied rather than
        # replacing it with the default asset-only metadata.
        try:
            info = json.loads(supplied_info.read_text(encoding="utf-8"))
        except (ValueError, UnicodeError):
            info = None
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".asset-mod-stage-", dir=output.parent))
    zip_stage = None
    try:
        folder = staging / guid
        folder.mkdir()
        if supplied_info is None:
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
        try:
            if os.name == "nt":
                os.rename(zip_stage, archive_path)
            else:
                os.link(zip_stage, archive_path)
        except OSError:
            os.rename(output, folder)
            raise
        return {
            "schema": ("sprite-suite.se-asset-only.v1" if strict_static
                       else "sprite-suite.unrestricted-mod-bundle.v1"),
            "guid": guid, "se_version_required": None,
            "runtime_dll": any(name.casefold().endswith(".dll") for name, *_ in files),
            "source_files": len(files),
            "asset_mod_folder": str(output),
            "zip": str(archive_path),
            "manifest": info,
        }
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        if zip_stage is not None and zip_stage.exists():
            zip_stage.unlink()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True,
                        help="Beliebiger Quellordner mit gewünschten Mod-Dateien")
    parser.add_argument("--guid", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--author", default="")
    parser.add_argument("--out", type=Path,
                        help="Frei wählbares Ziel, Standard work/se-asset-mods/<GUID>")
    parser.add_argument("--strict-static", action="store_true",
                        help="Optionale Prüfung nur für statische Asset-Mods")
    args = parser.parse_args(argv)
    try:
        result = build(args.source, args.guid, name=args.name,
                       author=args.author, target=args.out, strict_static=args.strict_static)
    except (AssetModError, OSError, ValueError) as exc:
        print(f"ASSET_MOD_FEHLER: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

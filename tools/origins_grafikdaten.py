"""Stronghold Origins graphics inventory and guarded editable working copies.

The source repository contains both mod-authored and game-derived LFS assets.
Keep its binaries separate from the public Sprite Suite. All 13k+ path IDs
remain browseable with this source-pinned manifest; image editing requires a
user-owned complete LFS checkout and makes an isolated copy below work/.
No game installation is ever modified.
"""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
OFFICIAL_URL = "https://gitlab.com/strongholdoriginsmod/stronghold-europe-grafikdaten.git"
PRIVATE_GITHUB_URL = "https://github.com/strongholdoriginsmod-rgb/sh1de-shcde-sprite-suite.git"
PRIVATE_GITHUB_BRANCH = "graphics/stronghold-europe-grafikdaten"
SOURCE_REVISION = "66dd212217831016d454483f41859258d5d3dc89"
SCHEMA = "sprite-suite.origins-grafikdaten-inventory.v1"
INVENTORY = ROOT / "config" / "origins-grafikdaten-inventory.json"
EDIT_WORK = ROOT / "work" / "origins-grafikdaten-edits"
_SHA1 = re.compile(r"[0-9a-f]{40}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_LFS = re.compile(
    rb"\Aversion https://git-lfs.github.com/spec/v1\r?\n"
    rb"oid sha256:([0-9a-f]{64})\r?\n"
    rb"size ([0-9]+)\r?\n?\Z",
)
LFS_TYPES = {".png", ".jpg", ".jpeg", ".webm", ".dds", ".ora",
             ".zip", ".v1", ".v2", ".dll"}
PREVIEW_TYPES = {".png", ".jpg", ".jpeg"}


class GraphicsDataError(RuntimeError):
    """A graphics-data source or editable copy is missing or untrusted."""


def secure_relative(value: object) -> str:
    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        raise GraphicsDataError("Grafikpfad ist nicht relativ bzw. enthält Sonderzeichen")
    path = PurePosixPath(value)
    win = PureWindowsPath(value)
    if (path.is_absolute() or win.is_absolute() or win.drive or
            any(os.path.isreserved(part) for part in value.split("/")) or
            any(part in {"", ".", ".."} or part.endswith((" ", "."))
                or any(ch in part for ch in ':<>"|?*')
                for part in value.split("/"))):
        raise GraphicsDataError("Unsicherer Grafikpfad: " + value)
    return path.as_posix()


def classification(path: str) -> str:
    """Groups all graphically useful files without dropping miscellaneous ones."""
    p = path.casefold()
    components = p.split("/")
    if (p.startswith("assets/ui/") or
            p.startswith("assets/concepts/ui-") or
            p.startswith("daten/origins/ui-") or
            p.startswith("sandbox/hud/") or
            "/gui/" in p or
            p.endswith(".xaml") or
            any(part.startswith(("ui-", "hud_")) for part in components) or
            any(pat in p for pat in ("/hud/", "/branding/", "/menu-background"))):
        return "hud-gui"
    if (p.startswith("assets/sprites/") or p.startswith("daten/png-atlanten-") or
            "/sprites/" in p or "/sprites" in p or
            p.endswith(".dds")):
        return "sprites"
    if p.startswith("assets/concepts/"):
        return "concepts"
    if p.startswith("daten/"):
        return "packages"
    if p.startswith("work/"):
        return "local-project"
    return "other"


def git_output(root: Path, *args: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True, check=False, timeout=45,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GraphicsDataError("Git-Quelldaten konnten nicht gelesen werden") from exc
    if result.returncode:
        raise GraphicsDataError(
            f"Git-Verifizierung fehlgeschlagen: {args[:2]}: "
            + result.stderr.decode("utf8", "replace")[:280]
        )
    return result.stdout


def source_repo(value: Path | str, *, expected_commit: str | None = None) -> Path:
    """Verify the exact known repo and commit, including a clone without checkout."""
    if expected_commit is None:
        expected_commit = SOURCE_REVISION
    given = Path(value).resolve(strict=True)
    if not given.is_dir():
        raise GraphicsDataError("Grafikdatenquelle ist kein Ordner")
    root = Path(git_output(given, "rev-parse", "--show-toplevel")
                .decode("utf8").strip()).resolve(strict=True)
    if root != given:
        raise GraphicsDataError("Bitte den Wurzelordner des Grafikdaten-Repos wählen")
    current = git_output(root, "rev-parse", "HEAD").decode("ascii").strip()
    if current != expected_commit:
        raise GraphicsDataError(
            f"Der Grafikdaten-Stand hat sich geändert: {current}. "
            "Zuerst Inventar und Kompatibilität neu prüfen."
        )
    remote = git_output(root, "remote", "get-url", "origin").decode("utf8").strip()
    if remote.casefold() not in {
        OFFICIAL_URL.casefold(),
        OFFICIAL_URL.removesuffix(".git").casefold(),
        "git@gitlab.com:strongholdoriginsmod/stronghold-europe-grafikdaten.git",
        # Same data tree and exact source revision on a separate branch of
        # the PRIVATE SpriteSuite GitHub repository. Never accept an arbitrary
        # GitHub origin or a different commit with matching file names.
        PRIVATE_GITHUB_URL.casefold(),
        PRIVATE_GITHUB_URL.removesuffix(".git").casefold(),
        PRIVATE_GITHUB_URL.replace("https://", "https://strongholdoriginsmod-rgb@").casefold(),
        "git@github.com:strongholdoriginsmod-rgb/sh1de-shcde-sprite-suite.git",
    }:
        raise GraphicsDataError(
            "Quelle ist nicht das bekannte Stronghold-Origins-Grafikdaten-Repository"
        )
    return root


def inventory_from_tree(repo: Path | str) -> dict:
    root = source_repo(repo)
    raw = git_output(root, "ls-tree", "-rz", "--full-tree", SOURCE_REVISION)
    assets: list[dict] = []
    folded: set[str] = set()
    for blob in raw.split(b"\x00"):
        if not blob:
            continue
        try:
            header, path_bytes = blob.split(b"\t", 1)
            mode, kind, oid = header.decode("ascii").split(" ")
            path = secure_relative(path_bytes.decode("utf8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise GraphicsDataError("Ungültiger Git-Tree-Eintrag") from exc
        if kind != "blob" or not _SHA1.fullmatch(oid):
            raise GraphicsDataError("Nicht unterstütztes Git-Tree-Objekt")
        lower = path.casefold()
        if lower in folded:
            raise GraphicsDataError("Kollidierende Pfadnamen unter Windows: " + path)
        folded.add(lower)
        suffix = PurePosixPath(path).suffix.lower()
        assets.append({
            "path": path,
            "kind": classification(path),
            "format": suffix[1:] if suffix else "",
            "git_blob_sha1": oid,
            "requires_lfs": suffix in LFS_TYPES or path.endswith("/build-manifest.json"),
            "is_regular": mode in {"100644", "100755"},
        })
    assets.sort(key=lambda row: row["path"])
    counter = Counter(row["kind"] for row in assets)
    return {
        "schema": SCHEMA,
        "source_url": OFFICIAL_URL,
        "source_commit": SOURCE_REVISION,
        "entry_count": len(assets),
        "categories": dict(sorted(counter.items())),
        "contains_game_derived_resources": True,
        "distribution_policy": "local-authorized-checkout-only",
        "asset_blobs_embedded": False,
        "entries": assets,
    }


def load_inventory(path: Path | str = INVENTORY) -> dict:
    file = Path(path)
    if file.is_symlink() or not file.is_file() or file.stat().st_size > 5_000_000:
        raise GraphicsDataError("Grafikdaten-Inventar fehlt, ist verknüpft oder zu groß")
    try:
        value = json.loads(file.read_text(encoding="utf8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise GraphicsDataError("Grafikdaten-Inventar ist unlesbar") from exc
    if (not isinstance(value, dict) or value.get("schema") != SCHEMA or
            value.get("source_url") != OFFICIAL_URL or
            value.get("source_commit") != SOURCE_REVISION):
        raise GraphicsDataError("Nicht freigegebener Grafikdaten-Vertrag")
    entries = value.get("entries")
    if not isinstance(entries, list) or value.get("entry_count") != len(entries):
        raise GraphicsDataError("Grafikdaten-Einträge fehlen oder sind unvollständig")
    keys = set()
    for item in entries:
        if not isinstance(item, dict):
            raise GraphicsDataError("Ungültiger Grafikdaten-Eintrag")
        path = secure_relative(item.get("path"))
        if path.casefold() in keys:
            raise GraphicsDataError("Doppelte Grafiknamen")
        keys.add(path.casefold())
        if not _SHA1.fullmatch(str(item.get("git_blob_sha1", ""))):
            raise GraphicsDataError("Ungültige Git-Dateiidentität")
        if item.get("kind") != classification(path):
            raise GraphicsDataError("Manipulierte Grafikklassifikation")
    actual_counts = dict(sorted(Counter(x["kind"] for x in entries).items()))
    if value.get("categories") != actual_counts:
        raise GraphicsDataError("Grafikdaten-Gruppen stimmen nicht")
    return value


def checked_source_file(repo: Path | str, item: dict) -> Path:
    """Checks the local checkout against the committed normal/LFS bytes."""
    root = source_repo(repo)
    relative = secure_relative(item["path"])
    if classification(relative) != item["kind"] or not item.get("is_regular"):
        raise GraphicsDataError("Der Grafikeintrag ist nicht zur Bearbeitung freigegeben")
    file = root.joinpath(*PurePosixPath(relative).parts)
    if not file.is_file() or file.is_symlink() or not file.resolve().is_relative_to(root):
        raise GraphicsDataError("Grafik noch nicht ausgecheckt: " + relative)
    # Inventory data never authorizes an untracked Git object. Verify the
    # selected file's blob directly against the immutable source Git tree.
    tree = git_output(root, "ls-tree", "-z", SOURCE_REVISION, "--", relative)
    expected_line = b"100644 blob " + item["git_blob_sha1"].encode("ascii") + b"\t" + relative.encode("utf8") + b"\x00"
    if tree != expected_line:
        raise GraphicsDataError("Grafikeintrag stimmt nicht zum gepinnten Git-Baum")
    raw = git_output(root, "cat-file", "blob", item["git_blob_sha1"])
    m = _LFS.fullmatch(raw)
    if item["requires_lfs"] and m is None:
        raise GraphicsDataError("Die Original-LFS-Speicherreferenz fehlt: " + relative)
    if m:
        with file.open("rb") as fh:
            first = fh.read(60)
        if first.startswith(b"version https://git-lfs.github.com/spec/v1"):
            raise GraphicsDataError("Git LFS noch nicht heruntergeladen: git lfs pull")
        declared = int(m.group(2))
        if file.stat().st_size != declared:
            raise GraphicsDataError("Grafikgröße weicht vom Git-LFS-Pin ab")
        digest = sha256()
        with file.open("rb") as stream:
            for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() != m.group(1).decode("ascii"):
            raise GraphicsDataError("Grafik-SHA-256 stimmt nicht zum LFS-Objekt")
    else:
        actual_sha = git_output(root, "hash-object", "--no-filters", "--", str(file))
        if actual_sha.decode("ascii").strip() != item["git_blob_sha1"]:
            raise GraphicsDataError("Grafikdatei wurde seit dem Git-Export verändert")
    return file


def read_catalog_item(index: dict, relative: str) -> dict:
    target = secure_relative(relative)
    result = next((x for x in index["entries"] if x["path"] == target), None)
    if result is None:
        raise GraphicsDataError("Grafik ist nicht im geprüften Inventar")
    return result


def safe_edit_folder(folder: Path) -> Path:
    work = (ROOT / "work").resolve()
    raw = Path(folder)
    dest = raw.resolve()
    if dest == work or not dest.is_relative_to(work) or raw.is_symlink():
        raise GraphicsDataError("Bearbeitung nur in einem Unterordner von work/")
    for candidate in (raw, *raw.parents):
        if candidate.exists() and candidate.is_symlink():
            raise GraphicsDataError("Symbolische Ordnerverknüpfung abgewiesen")
    return dest


def copy_for_editing(repo: Path, inventory: dict, relative: str,
                     output: Path = EDIT_WORK) -> tuple[Path, Path]:
    """Copy one named, SHA-verified file without touching the original."""
    item = read_catalog_item(inventory, relative)
    src = checked_source_file(repo, item)
    root = safe_edit_folder(output)
    filename = root.joinpath(*PurePosixPath(relative).parts)
    sidecar = filename.with_name(filename.name + ".source.json")
    if filename.exists() or sidecar.exists():
        raise GraphicsDataError("Bearbeitung existiert bereits. Kein Überschreiben.")
    if src.stat().st_size > 1_000_000_000:
        raise GraphicsDataError("Einzeldatei ist größer als 1 GB")
    # Every nested parent must resolve below work/; symlinked ancestors can
    # redirect an otherwise safe-looking relative file path outside the Suite.
    if not filename.resolve().is_relative_to(root):
        raise GraphicsDataError("Ziel führt außerhalb des Arbeitsverzeichnisses")
    for parent in (filename.parent, *filename.parent.parents):
        if parent == root:
            break
        if parent.is_symlink():
            raise GraphicsDataError("Verknüpfter Unterordner im Arbeitsverzeichnis")
    filename.parent.mkdir(parents=True, exist_ok=True)
    if not filename.parent.resolve().is_relative_to(root):
        raise GraphicsDataError("Ausgabeordner wurde während des Imports verändert")
    original_hash = sha256()
    with src.open("rb") as original_stream:
        for block in iter(lambda: original_stream.read(4 * 1024 * 1024), b""):
            original_hash.update(block)
    manifest = {
        "schema": "sprite-suite.origins-grafikdaten-workcopy.v1",
        "git_source_commit": inventory["source_commit"],
        "relative_path": relative,
        "git_blob_sha1": item["git_blob_sha1"],
        "original_sha256": original_hash.hexdigest(),
    }
    stage = None
    try:
        fd, name = tempfile.mkstemp(prefix=".origin-asset-", dir=filename.parent)
        with os.fdopen(fd, "wb") as stream, src.open("rb") as original:
            shutil.copyfileobj(original, stream, length=4 * 1024 * 1024)
        stage = Path(name)
        copy_hash = sha256()
        with stage.open("rb") as output_stream:
            for block in iter(lambda: output_stream.read(4 * 1024 * 1024), b""):
                copy_hash.update(block)
        if copy_hash.hexdigest() != manifest["original_sha256"]:
            raise GraphicsDataError("Arbeitskopie SHA-256-Prüfung fehlgeschlagen")
        with sidecar.open("x", encoding="utf8", newline="\n") as fh:
            json.dump(manifest, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        # No overwrite: the GUI/CLI must never silently replace a user edit.
        if filename.exists():
            raise GraphicsDataError("Zieldatei wurde zeitgleich erstellt")
        os.rename(stage, filename)
        return filename, sidecar
    except Exception:
        sidecar.unlink(missing_ok=True)
        raise
    finally:
        if stage is not None and stage.exists():
            stage.unlink()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("audit", help="Prüft alle Einträge aus dem gepinnten Git-Baum")
    scan.add_argument("--repo", type=Path, required=True)
    scan.add_argument("--write-index", type=Path)
    copy = sub.add_parser("copy", help="Eine Datei in work/ zur Bearbeitung kopieren")
    copy.add_argument("--repo", type=Path, required=True)
    copy.add_argument("--path", required=True)
    copy.add_argument("--out", type=Path, default=EDIT_WORK)
    copy.add_argument("--index", type=Path, default=INVENTORY)
    verify = sub.add_parser("verify", help="Eine Datei gegen Git/LFS prüfen")
    verify.add_argument("--repo", type=Path, required=True)
    verify.add_argument("--path", required=True)
    verify.add_argument("--index", type=Path, default=INVENTORY)
    args = parser.parse_args(argv)
    try:
        if args.command == "audit":
            info = inventory_from_tree(args.repo)
            if args.write_index:
                dest = args.write_index
                if not dest.resolve().is_relative_to(ROOT.resolve()):
                    raise GraphicsDataError("Inventar darf nur unter der Suite liegen")
                if dest.exists():
                    raise GraphicsDataError("Vorhandenes Inventar wird nicht überschrieben")
                dest.parent.mkdir(parents=True, exist_ok=True)
                with dest.open("x", encoding="utf8", newline="\n") as stream:
                    json.dump(info, stream, ensure_ascii=False, separators=(",", ":"))
                    stream.write("\n")
            print(json.dumps({
                "commit": info["source_commit"], "entries": info["entry_count"],
                "categories": info["categories"], "asset_blobs_embedded": False,
            }, ensure_ascii=False))
        elif args.command == "verify":
            item = read_catalog_item(load_inventory(args.index), args.path)
            file = checked_source_file(args.repo, item)
            print(f"GRAFIK_SHA_VERIFIZIERT {file}")
        else:
            target, sidecar = copy_for_editing(
                args.repo, load_inventory(args.index), args.path, args.out
            )
            print(f"ORIGINS_ARBEITSKOPIE_ERSTELLT {target}\nQUELLENNACHWEIS {sidecar}")
    except (GraphicsDataError, OSError, ValueError) as exc:
        print(f"GRAFIKDATEN_FEHLER: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

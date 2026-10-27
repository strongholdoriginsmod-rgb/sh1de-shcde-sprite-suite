"""Install pinned MPFB asset packs into the isolated Blender user tree.

This script runs inside Blender after MPFB has registered.  It deliberately
does not use ``ZipFile.extractall``: every member is validated, hashes are
checked against the project contract, and conflicting existing files stop the
installation instead of being overwritten silently.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import sys
import tempfile
import zipfile


def _arguments() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--packages", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    return parser.parse_args(argv)


def _dynamic_import(suffix: str, symbol: str):
    matches = sorted(name for name in sys.modules if name.endswith(suffix))
    if len(matches) != 1:
        raise RuntimeError(f"Expected exactly one loaded {suffix!r} module, found {matches}")
    module = importlib.import_module(matches[0])
    return getattr(module, symbol)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validated_members(archive: zipfile.ZipFile) -> tuple[str | None, list[zipfile.ZipInfo]]:
    members = [member for member in archive.infolist() if not member.filename.startswith("__MACOSX/")]
    roots: set[str] = set()
    has_root_packs = False
    for member in members:
        name = member.filename.replace("\\", "/")
        path = PurePosixPath(name)
        if not name or path.is_absolute() or ".." in path.parts or ":" in path.parts[0]:
            raise RuntimeError(f"Unsafe asset-pack member path: {member.filename!r}")
        unix_mode = member.external_attr >> 16
        if stat.S_ISLNK(unix_mode):
            raise RuntimeError(f"Symbolic links are forbidden in asset packs: {member.filename!r}")
        if path.parts[0] == "packs":
            has_root_packs = True
        elif not path.parts[0].startswith("."):
            roots.add(path.parts[0])
    if has_root_packs:
        return None, members
    if len(roots) != 1:
        raise RuntimeError(f"Asset pack has no unambiguous root: {sorted(roots)}")
    prefix = next(iter(roots))
    if not any(PurePosixPath(member.filename.replace("\\", "/")).parts[:2] == (prefix, "packs") for member in members):
        raise RuntimeError("Asset pack does not contain a packs/ metadata directory")
    return prefix, members


def _install_archive(path: Path, target_root: Path) -> dict[str, int | str]:
    installed = 0
    reused = 0
    with zipfile.ZipFile(path, "r") as archive:
        bad_member = archive.testzip()
        if bad_member is not None:
            raise RuntimeError(f"CRC failure in {path.name}: {bad_member}")
        prefix, members = _validated_members(archive)
        with tempfile.TemporaryDirectory(prefix="se-mpfb-") as temporary_name:
            temporary = Path(temporary_name)
            for member in members:
                parts = PurePosixPath(member.filename.replace("\\", "/")).parts
                if prefix is not None:
                    if not parts or parts[0] != prefix:
                        continue
                    parts = parts[1:]
                if not parts:
                    continue
                relative = Path(*parts)
                temporary_path = temporary / relative
                destination = target_root / relative
                if member.is_dir():
                    temporary_path.mkdir(parents=True, exist_ok=True)
                    continue
                temporary_path.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member, "r") as source, temporary_path.open("wb") as sink:
                    shutil.copyfileobj(source, sink, length=1024 * 1024)
                if destination.exists():
                    if not destination.is_file() or _sha256(destination) != _sha256(temporary_path):
                        raise RuntimeError(f"Refusing conflicting MPFB asset overwrite: {destination}")
                    reused += 1
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                os.replace(temporary_path, destination)
                installed += 1
    return {"file": path.name, "installed_files": installed, "reused_files": reused}


def main() -> None:
    args = _arguments()
    manifest = json.loads(args.manifest.resolve().read_text(encoding="utf-8"))
    LocationService = _dynamic_import("mpfb.services.locationservice", "LocationService")
    AssetService = _dynamic_import("mpfb.services.assetservice", "AssetService")
    target_root = Path(LocationService.get_user_data()).resolve()
    target_root.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, int | str]] = []
    for pack in manifest["asset_packs"]:
        archive = (args.packages.resolve() / pack["file"]).resolve()
        if not archive.is_file():
            if pack["required"]:
                raise RuntimeError(f"Required MPFB asset pack is missing: {archive}")
            continue
        if archive.stat().st_size != int(pack["bytes"]):
            raise RuntimeError(f"Byte count differs for {archive.name}")
        if _sha256(archive) != pack["sha256"]:
            raise RuntimeError(f"SHA-256 differs for {archive.name}")
        result = _install_archive(archive, target_root)
        result["sha256"] = pack["sha256"]
        result["license"] = pack["license"]
        results.append(result)

    AssetService.update_all_asset_lists()
    AssetService.rescan_pack_metadata()
    installed_pack_names = AssetService.get_pack_names()
    report = {
        "schema_version": 1,
        "manifest_sha256": _sha256(args.manifest.resolve()),
        "target_root": str(target_root),
        "archives": results,
        "installed_pack_names": installed_pack_names,
        "system_assets_present": bool(AssetService.system_assets_pack_is_installed()),
    }
    if not report["system_assets_present"]:
        raise RuntimeError("MPFB did not recognize the installed system asset pack")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("STRONGHOLD_EUROPE_HUMAN_TOOLCHAIN_READY " + json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()

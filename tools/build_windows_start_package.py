"""Build a Windows first-run package from a committed source and bare CPython.

The package creates its venv and installs hash-locked dependencies on first
launch. Local virtual environments, installed third-party libraries and private
game data are excluded from this distribution.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import tempfile
from typing import NamedTuple
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_FILES = (
    "python.exe", "pythonw.exe", "python3.dll", "vcruntime140.dll",
    "vcruntime140_1.dll", "LICENSE.txt",
)
RUNTIME_LIBRARIES = {
    "libcrypto-3.dll", "libssl-3.dll", "libffi-8.dll", "sqlite3.dll",
    "libcrypto-3-x64.dll", "libssl-3-x64.dll",
    "tcl86t.dll", "tk86t.dll", "tcl90.dll", "tcl9tk90.dll", "zlib1.dll",
}
SOURCE_LOCAL_DIRS = {
    ".git", ".venv", "python", "site-packages", "__pycache__",
    ".pytest_cache", "work", "cache", "dist", "state",
}
SOURCE_RUNTIME_SUFFIXES = {
    ".dll", ".exe", ".pyd", ".so", ".dylib", ".assets", ".sav",
    ".map", ".trail", ".bank", ".fsb", ".gm1", ".dds",
}
FIRST_RUN = """SpriteSuite Windows Startpaket

1. Das ZIP vollständig in einen eigenen Ordner entpacken.
2. Suite starten.cmd öffnen.
3. Beim ersten Start lädt setup.ps1 die festgelegten Python-Abhängigkeiten
   aus PyPI und prüft deren SHA-256-Werte gegen die mitgelieferte Lockdatei.
   Dafür ist eine Internetverbindung erforderlich. Der erste Start dauert
   länger und legt die Umgebung .venv im Paketordner an.
4. Nach erfolgreicher Einrichtung startet SpriteSuite. Weitere Starts nutzen
   diese Umgebung. Nach einem abgebrochenen ersten Setup wird es erneut
   versucht.

CPython ist enthalten. Eine separate Python-Installation wird nicht benötigt.
Spielinstallationen und eigene Projekte werden über die Suite ausgewählt.
Die Einrichtung installiert lokal heruntergeladene Abhängigkeiten. Deren
jeweilige Lizenzbedingungen liegen bei den Paketen.

SpriteSuite Windows first-run package

Extract the complete ZIP and run Suite starten.cmd. The first launch needs
Internet access to install the SHA-256-locked dependencies from PyPI into
.venv. CPython is included. Subsequent launches use the installed environment.
An interrupted first setup is retried on the next launch.
"""


class BuildResult(NamedTuple):
    archive: Path
    sha256: str
    source_commit: str
    python_version: str


def _digest(path: Path) -> str:
    with path.open("rb") as source:
        return sha256(source.read()).hexdigest()


def _run(command: list[str], cwd: Path) -> str:
    environment = {
        key: value for key, value in os.environ.items()
        if key.upper() not in {"PYTHONHOME", "PYTHONPATH"}
    }
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        command, cwd=cwd, env=environment, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=120,
    )
    if result.returncode:
        raise ValueError("Build command failed: " + (result.stderr or result.stdout).strip())
    return result.stdout.strip()


def _runtime_info(home: Path) -> dict:
    code = (
        "import ensurepip,json,struct,sys; print(json.dumps({"
        "'version':list(sys.version_info[:3]),'bits':struct.calcsize('P')*8,"
        "'platform':sys.platform,'modules':sorted(sys.stdlib_module_names),"
        "'pip':ensurepip.version()}))"
    )
    info = json.loads(_run([str(home / "python.exe"), "-I", "-S", "-c", code], home))
    if info["platform"] != "win32" or info["bits"] != 64:
        raise ValueError("A Windows x64 CPython source is required.")
    if info["version"][:2] not in ([3, 13], [3, 14]):
        raise ValueError("This setup supports CPython 3.13 or 3.14.")
    return info


def _regular_files(directory: Path):
    for path in sorted(directory.rglob("*")):
        if path.is_symlink() or path.is_junction():
            raise ValueError("Linked runtime source entries are unsupported.")
        if path.is_file():
            if path.suffix.lower() not in {".pyc", ".pyo", ".pdb"} and "__pycache__" not in path.parts:
                yield path


def _runtime_sources(home: Path, info: dict) -> dict[str, Path]:
    """Select stdlib modules by CPython's own module list, plus its support DLLs."""
    sources = {}
    minor = info["version"][1]
    top = (*RUNTIME_FILES, f"python3{minor}.dll")
    optional = {"vcruntime140_1.dll"}
    for name in top:
        path = home / name
        if not path.is_file():
            if name in optional:
                continue
            raise ValueError("CPython source is missing " + name)
        sources[name] = path
    modules = set(info["modules"])
    for path in sorted((home / "Lib").iterdir()):
        if path.name == "site-packages" or path.name == "__pycache__":
            continue
        if path.stem not in modules:
            continue
        candidates = _regular_files(path) if path.is_dir() else (path,)
        for file in candidates:
            if file.is_symlink() or file.is_junction():
                raise ValueError("Linked stdlib entries are unsupported.")
            relative = file.relative_to(home).as_posix()
            if file.suffix.lower() in {".pyc", ".pyo", ".pdb"}:
                continue
            if "/ensurepip/_bundled/" in relative:
                if file.name != f"pip-{info['pip']}-py3-none-any.whl":
                    continue
            sources[relative] = file
    for path in sorted((home / "DLLs").iterdir()):
        if not path.is_file():
            continue
        if path.name in RUNTIME_LIBRARIES or (path.suffix.lower() == ".pyd" and path.stem in modules):
            sources[path.relative_to(home).as_posix()] = path
    tcl = home / "tcl"
    if tcl.is_dir():
        for path in _regular_files(tcl):
            sources[path.relative_to(home).as_posix()] = path
    for name in (
        "Lib/venv/__init__.py",
        "Lib/ensurepip/__init__.py",
        f"Lib/ensurepip/_bundled/pip-{info['pip']}-py3-none-any.whl",
    ):
        if name not in sources:
            raise ValueError("Full CPython source is missing " + name)
    if not any(name in sources for name in (
        "Lib/venv/scripts/nt/python.exe", "Lib/venv/scripts/nt/venvlauncher.exe",
    )):
        raise ValueError("Full CPython source is missing its Windows venv launcher.")
    for name, path in sources.items():
        if path.is_symlink() or path.is_junction() or path.resolve() != path:
            raise ValueError("Runtime source escapes the selected directory.")
        if not path.resolve().is_relative_to(home):
            raise ValueError("Runtime source escapes the selected directory.")
    return sources


def _source_name(name: str) -> PurePosixPath:
    relative = PurePosixPath(name)
    if relative.is_absolute() or "\\" in name or ":" in name or ".." in relative.parts:
        raise ValueError("Unsafe source archive path.")
    if not relative.parts or relative.parts[0].lower() in SOURCE_LOCAL_DIRS:
        raise ValueError("The committed source contains local runtime or state files.")
    if "site-packages" in {part.lower() for part in relative.parts}:
        raise ValueError("The committed source contains installed packages.")
    if relative.suffix.lower() in SOURCE_RUNTIME_SUFFIXES:
        raise ValueError("The committed source contains a binary runtime or game file.")
    if relative.parts[0].lower() == "config" and ".local." in relative.name.lower():
        raise ValueError("The committed source contains local configuration.")
    return relative


def _extract_source(archive_path: Path, destination: Path) -> None:
    seen = set()
    with ZipFile(archive_path) as archive:
        if archive.testzip() is not None:
            raise ValueError("Git source archive CRC failed.")
        for item in archive.infolist():
            relative = _source_name(item.filename)
            key = str(relative).casefold()
            if key in seen:
                raise ValueError("Source archive has duplicate Windows paths.")
            seen.add(key)
            mode = item.external_attr >> 16
            if mode and stat.S_ISLNK(mode):
                raise ValueError("Source archive contains a symbolic link.")
            target = destination.joinpath(*relative.parts)
            if not target.resolve().is_relative_to(destination):
                raise ValueError("Source path escapes the new package.")
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(item) as source, target.open("xb") as output:
                shutil.copyfileobj(source, output)


def _write_zip(source: Path, output: Path, timestamp: tuple[int, ...]) -> None:
    with ZipFile(output, "x", ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(source.rglob("*")):
            if not path.is_file():
                continue
            info = ZipInfo("SpriteSuite/" + path.relative_to(source).as_posix(), timestamp)
            info.compress_type = ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, path.read_bytes())
    with ZipFile(output) as archive:
        if archive.testzip() is not None:
            raise ValueError("Start package ZIP CRC failed.")
        expected = {
            "SpriteSuite/" + path.relative_to(source).as_posix(): _digest(path)
            for path in source.rglob("*") if path.is_file()
        }
        if set(archive.namelist()) != set(expected):
            raise ValueError("Start package ZIP file inventory differs.")
        for name, digest in expected.items():
            if sha256(archive.read(name)).hexdigest() != digest:
                raise ValueError("Start package ZIP content SHA-256 differs.")


def build_start_package(
    source_root: Path, source_ref: str, python_home: Path, output_dir: Path,
) -> BuildResult:
    source_root = Path(source_root).resolve(strict=True)
    python_home = Path(python_home).resolve(strict=True)
    output_dir = Path(output_dir).absolute()
    if output_dir.exists():
        raise FileExistsError("Output directory already exists.")
    parent = output_dir.parent.resolve(strict=True)
    output_dir = parent / output_dir.name
    commit = _run(["git", "rev-parse", "--verify", source_ref + "^{commit}"], source_root)
    epoch = int(_run(["git", "show", "-s", "--format=%ct", commit], source_root))
    info = _runtime_info(python_home)
    runtime = _runtime_sources(python_home, info)
    python_version = ".".join(map(str, info["version"]))
    with tempfile.TemporaryDirectory(prefix=".spritesuite-start-", dir=parent) as staging:
        stage = Path(staging).resolve()
        if not stage.is_relative_to(parent):
            raise ValueError("Build staging is outside its selected parent.")
        source_zip = stage / "committed-source.zip"
        _run(["git", "archive", "--format=zip", "--output=" + str(source_zip), commit], source_root)
        package = stage / "SpriteSuite"
        package.mkdir()
        _extract_source(source_zip, package)
        version = (package / "VERSION").read_text("utf-8").strip()
        if not version or any(not part.isdigit() for part in version.split(".")):
            raise ValueError("The committed source has an invalid application VERSION.")
        lock_name = f"requirements-py3{info['version'][1]}-win_amd64.lock"
        lock = package / lock_name
        if not lock.is_file() or "--hash=sha256:" not in lock.read_text("utf-8"):
            raise ValueError("The committed source lacks the matching hash lock.")
        setup = package / "setup.ps1"
        if "--require-hashes" not in setup.read_text("utf-8"):
            raise ValueError("The committed setup does not enforce hash-locked installation.")
        for name in ("Suite starten.cmd", "tools/suite_start.py"):
            if not (package / name).is_file():
                raise ValueError("The committed source is missing its startup entrypoint.")
        runtime_manifest = []
        for relative, path in sorted(runtime.items()):
            dest = package / "python" / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, dest)
            runtime_manifest.append({
                "path": "python/" + relative, "bytes": dest.stat().st_size,
                "sha256": _digest(dest),
            })
        _run([
            str(package / "python/python.exe"), "-I", "-S", "-c",
            "import ctypes,ensurepip,ssl,sqlite3,tkinter,venv; tkinter.Tcl(); "
            "print('CPython runtime dependencies verified')",
        ], package)
        metadata = {
            "schema": "spritesuite.windows-start-package.v1",
            "source_commit": commit,
            "source_archive_sha256": _digest(source_zip),
            "application_version": version,
            "python_version": python_version,
            "python_architecture": "x64",
            "dependency_lock": lock_name,
            "dependency_lock_sha256": _digest(lock),
            "setup_sha256": _digest(setup),
            "first_start_requires_internet": True,
            "preinstalled_third_party_packages": False,
            "runtime_files": runtime_manifest,
        }
        (package / "START-PACKAGE.json").write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
        )
        (package / "FIRST-RUN.txt").write_text(FIRST_RUN, encoding="utf-8")
        release = stage / "release"
        release.mkdir()
        archive_name = f"SpriteSuite-Windows-Start-v{version}-py3{info['version'][1]}-x64.zip"
        archive = release / archive_name
        when = datetime.fromtimestamp(max(epoch, 315532800), timezone.utc)
        _write_zip(package, archive, when.timetuple()[:6])
        digest = _digest(archive)
        (release / (archive_name + ".sha256")).write_text(
            digest + " *" + archive_name + "\n", encoding="ascii",
        )
        (release / "START-PACKAGE-BUILD.json").write_text(
            json.dumps({**metadata, "archive": archive_name, "archive_sha256": digest,
                        "zip_crc_verified": True}, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        if output_dir.exists():
            raise FileExistsError("Output appeared during the build.")
        release.rename(output_dir)
    return BuildResult(output_dir / archive_name, digest, commit, python_version)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--source-ref", required=True)
    parser.add_argument("--python-home", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = build_start_package(
            args.source_root, args.source_ref, args.python_home, args.output,
        )
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print("Start package build failed: " + str(exc))
        return 2
    print(json.dumps(result._asdict(), default=str, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

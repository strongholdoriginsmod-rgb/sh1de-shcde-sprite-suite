"""Build a relocatable Windows ZIP with bundled CPython and dependencies.

Run on an authorized Windows packaging machine with Python 3.13 and a populated
matching venv. Exports ONLY committed project files (git archive); no local
game files, private workspaces, caches, or user settings. Never overwrites an
existing output. The ZIP needs no globally installed Python or admin rights.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from zipfile import ZipFile, ZIP_DEFLATED, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
PYTHON_FILES = (
    "python.exe", "pythonw.exe", "python3.dll", "python313.dll",
    "vcruntime140.dll", "vcruntime140_1.dll", "LICENSE.txt",
)
PYTHON_DIRS = ("DLLs", "Lib", "tcl")
VENV_DIRS = ("Scripts", "Lib")
VERSION = (ROOT / "VERSION").read_text("utf8").strip()
if not VERSION or not all(part.isdigit() for part in VERSION.split(".")):
    raise RuntimeError("VERSION must be a numeric dotted application version")
OUT_NAME = f"SpriteSuite-Windows-Portable-v{VERSION}-py313-x64.zip"


def _ignore(directory: str, names: list[str]) -> list[str]:
    banned = {"__pycache__", ".pytest_cache", "pip-wheel-metadata"}
    ignored = []
    for name in names:
        low = name.lower()
        if (name in banned or low.endswith((".pdb", ".pyc", ".pyo"))
                or low.startswith("__editable__.stronghold_europe_de")
                or low in {"test", "tests"} and Path(directory).name == "Lib"):
            ignored.append(name)
    return ignored


def _subprocess(*cmd: str, cwd: Path) -> str:
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                            encoding="utf8", check=True, timeout=90)
    return result.stdout.strip()


def _check_binary_sources(python: Path, venv: Path) -> None:
    if sys.platform != "win32":
        raise RuntimeError("Portable packaging requires Windows")
    missing = [
        str(python / name) for name in PYTHON_FILES
        if name != "vcruntime140_1.dll" and not (python / name).is_file()
    ]
    missing += [str(python / name) for name in PYTHON_DIRS
                if not (python / name).is_dir()]
    missing += [str(venv / name) for name in VENV_DIRS
                if not (venv / name).is_dir()]
    missing += [str(venv / "Scripts" / n) for n in ("python.exe", "pythonw.exe")
                if not (venv / "Scripts" / n).is_file()]
    if missing:
        raise RuntimeError("Missing portable runtime files: " + repr(missing))
    version = _subprocess(str(python / "python.exe"), "-c",
                          "import sys;print('%d.%d' % sys.version_info[:2])",
                          cwd=python)
    venv_version = _subprocess(str(venv / "Scripts" / "python.exe"),
                              "-c", "import sys;print('%d.%d' % sys.version_info[:2])",
                              cwd=venv)
    if version != "3.13" or venv_version != version:
        raise RuntimeError("Matching CPython 3.13 runtime and venv required")


def _copy_whitelist(
    src: Path, dst: Path, names: tuple[str, ...], *,
    exclude_base_site_packages: bool = False,
    venv_python_executables_only: bool = False,
) -> None:
    """Copy only the runtime whitelist; exclude unrelated base installations.

    Python's base Lib/site-packages can contain years of user-owned or
    unpublished packages. The portable distribution must carry only the
    independently hash-locked dependencies from the dedicated venv.
    """
    def ignore(directory: str, entries: list[str]) -> list[str]:
        skipped = _ignore(directory, entries)
        if exclude_base_site_packages and Path(directory) == src / "Lib":
            skipped.extend(
                entry for entry in entries
                if entry.casefold() in {"site-packages", "dist-packages"}
            )
        if venv_python_executables_only and Path(directory) == src / "Scripts":
            # pip launchers, activation scripts and other console .exe files
            # embed the *builder's* private venv location in their shebang.
            # The Suite starts only through its own python/pythonw command.
            skipped.extend(
                entry for entry in entries
                if entry.casefold() not in {"python.exe", "pythonw.exe"}
            )
        return skipped

    for name in names:
        source = src / name
        if not source.exists():
            if name == "vcruntime140_1.dll":
                continue
            raise RuntimeError("Missing whitelisted path " + str(source))
        target = dst / name
        if source.is_dir():
            shutil.copytree(source, target, ignore=ignore)
        elif source.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        else:
            raise RuntimeError("Unexpected filesystem entry " + str(source))


def _write_reproducible_zip(package: Path, archive: Path) -> int:
    """Zip stable file bytes without developer timestamps or paths in headers."""
    count = 0
    with ZipFile(archive, "w", ZIP_DEFLATED, compresslevel=6, allowZip64=True) as z:
        for file in sorted(package.rglob("*")):
            if not file.is_file():
                continue
            relative = file.relative_to(package.parent).as_posix()
            info = ZipInfo(relative, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            with file.open("rb") as source, z.open(info, "w", force_zip64=True) as target:
                shutil.copyfileobj(source, target, length=1024 * 1024)
            count += 1
    return count


def build(python: Path, venv: Path, out: Path) -> dict:
    python = python.resolve(strict=True)
    venv = venv.resolve(strict=True)
    out = out.resolve()
    _check_binary_sources(python, venv)
    if out.exists():
        raise RuntimeError("Output directory already exists; refusing overwrite: " + str(out))
    out.parent.mkdir(parents=True, exist_ok=True)
    # Build in a new *sibling* folder. A failure never creates a misleading
    # half-built public release directory; the final rename happens last.
    final_out = out
    out = Path(tempfile.mkdtemp(prefix=".spritesuite-portable-stage-", dir=out.parent))
    package = out / "SpriteSuite"
    package.mkdir()
    archive = out / OUT_NAME
    source = out / ".git-source.zip"
    try:
        commit = _subprocess("git", "rev-parse", "HEAD", cwd=ROOT)
        subprocess.run(
            ["git", "archive", "--format=zip", "--output", str(source), commit],
            cwd=ROOT, check=True, timeout=120,
        )
        with ZipFile(source) as files:
            for entry in files.infolist():
                path = Path(entry.filename)
                if path.is_absolute() or ".." in path.parts:
                    raise RuntimeError("Unsafe git archive entry")
            files.extractall(package)
        source.unlink()
        print("COPY: committed source", flush=True)
        _copy_whitelist(
            python, package / "python", PYTHON_FILES + PYTHON_DIRS,
            exclude_base_site_packages=True,
        )
        if (package / "python" / "Lib" / "site-packages").exists():
            raise RuntimeError("Private base Python packages leaked into runtime")
        print("COPY: CPython 3.13 runtime", flush=True)
        _copy_whitelist(
            venv, package / ".venv", VENV_DIRS,
            venv_python_executables_only=True,
        )
        private_scripts = {entry.name.casefold() for entry in
                           (package / ".venv" / "Scripts").iterdir()}
        if private_scripts != {"python.exe", "pythonw.exe"}:
            raise RuntimeError("Portable venv contains unexpected or missing executables")
        print("COPY: application dependencies", flush=True)
        # Only the first-run launcher will make .venv relocatable.
        (package / ".venv" / "pyvenv.cfg").write_text(
            "home = PORTABLE_LAUNCHER_WILL_SET_THIS\n"
            "include-system-site-packages = false\n"
            "version = 3.13.15\n", encoding="utf8"
        )
        site = package / ".venv" / "Lib" / "site-packages"
        if not site.is_dir():
            raise RuntimeError("Bundled venv contains no site-packages")
        (site / "stronghold_europe_universal.pth").write_text(
            "../../../src\n", encoding="utf8"
        )
        (package / "PORTABEL_STARTEN.txt").write_text(
            "SPRITE SUITE - WINDOWS PORTABEL\n"
            "\n"
            "1. Die ZIP-Datei vollstaendig entpacken.\n"
            "2. Im entpackten Ordner SpriteSuite / Suite starten.cmd doppelklicken.\n"
            "3. Python muss NICHT separat installiert werden.\n"
            "   Kein Administrator und kein pip / setup.ps1 erforderlich.\n"
            "4. Diagnose ohne GUI: Suite starten.cmd --self-test\n"
            "\n"
            "Original-Spiele und persoenliche Dateien werden nicht mitgeliefert.\n"
            "Toolchains wie Unity/.NET koennen fuer einzelne Buildfunktionen\n"
            "weiterhin separat erforderlich sein.\n"
            "Quellcommit: " + commit + "\n", encoding="utf8"
        )
        # A relocation-proof start must work without any Python on PATH.
        # The test opens both Tk and Qt from the bundled private environment.
        env = dict(os.environ)
        env["PATH"] = str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32")
        env["PATH"] += os.pathsep + os.environ.get("SystemRoot", "C:/Windows")
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        smoke = subprocess.run(
            [str(package / "python" / "python.exe"),
             str(package / "tools" / "suite_start.py"), "--self-test"],
            cwd=package, env=env, capture_output=True, text=True,
            encoding="utf8", errors="replace", timeout=60,
        )
        if smoke.returncode != 0 or "GUI_BACKENDS_READY=1" not in smoke.stdout:
            raise RuntimeError(
                "Bundled Python/Tk/Qt startup failed: "
                + (smoke.stdout + smoke.stderr)[-1200:]
            )
        # Do not embed a developer-specific build path in the ZIP.
        (package / ".venv" / "pyvenv.cfg").write_text(
            "home = PORTABLE_LAUNCHER_WILL_SET_THIS\n"
            "include-system-site-packages = false\n"
            "version = 3.13.15\n", encoding="utf8",
        )
        print("SMOKE: Python, Tk and Qt ready without system Python", flush=True)
        provenance = {
            "schema": "sprite-suite.windows-portable.v1",
            "source_commit": commit,
            "application_version": VERSION,
            "python": "CPython 3.13, redistributed locally",
            "python_requires_installation": False,
            "separate_python_required": False,
            "packager_windows_smoke_passed": True,
            "cross_computer_smoke_passed": False,
            "private_game_assets_included": False,
        }
        (package / "PORTABLE-BUILD.json").write_text(
            json.dumps(provenance, ensure_ascii=False, indent=2) + "\n",
            encoding="utf8",
        )
        print("ZIP: compressing self-contained Windows distribution", flush=True)
        count = _write_reproducible_zip(package, archive)
        hasher = sha256()
        with archive.open("rb") as stream:
            for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
                hasher.update(chunk)
        digest = hasher.hexdigest()
        (out / (OUT_NAME + ".sha256")).write_text(
            digest + "  " + OUT_NAME + "\n", encoding="ascii"
        )
        report = {"archive": str(final_out / OUT_NAME), "sha256": digest,
                  "source_commit": commit, "version": VERSION, "files": count,
                  "bytes": archive.stat().st_size,
                  "unpacked": str(final_out / "SpriteSuite")}
        if final_out.exists():
            raise RuntimeError("Release destination appeared during the build")
        os.rename(out, final_out)
        print(json.dumps(report, indent=2), flush=True)
        return report
    except Exception:
        # The unique staging folder is ours. Refuse to clean a swapped link.
        if out.is_dir() and not out.is_symlink():
            shutil.rmtree(out)
        raise


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--python-home", type=Path, required=True)
    ap.add_argument("--venv", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    try:
        build(a.python_home, a.venv, a.out)
        return 0
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print("PORTABLE_BUILD_ERROR:", exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

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
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
PYTHON_FILES = (
    "python.exe", "pythonw.exe", "python3.dll", "python313.dll",
    "vcruntime140.dll", "vcruntime140_1.dll", "LICENSE.txt",
)
PYTHON_DIRS = ("DLLs", "Lib", "tcl")
VENV_DIRS = ("Scripts", "Lib")
OUT_NAME = "SpriteSuite-Windows-Portable-Neue-Oberflaeche-2026-10-28.zip"


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


def _copy_whitelist(src: Path, dst: Path, names: tuple[str, ...]) -> None:
    for name in names:
        source = src / name
        if not source.exists():
            if name == "vcruntime140_1.dll":
                continue
            raise RuntimeError("Missing whitelisted path " + str(source))
        target = dst / name
        if source.is_dir():
            shutil.copytree(source, target, ignore=_ignore)
        elif source.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        else:
            raise RuntimeError("Unexpected filesystem entry " + str(source))


def build(python: Path, venv: Path, out: Path) -> dict:
    python = python.resolve(strict=True)
    venv = venv.resolve(strict=True)
    out = out.resolve()
    _check_binary_sources(python, venv)
    if out.exists():
        raise RuntimeError("Output directory already exists; refusing overwrite: " + str(out))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.mkdir()
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
        _copy_whitelist(python, package / "python",
                        PYTHON_FILES + PYTHON_DIRS)
        print("COPY: CPython 3.13 runtime", flush=True)
        _copy_whitelist(venv, package / ".venv", VENV_DIRS)
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
        count = 0
        with ZipFile(archive, "w", ZIP_DEFLATED, compresslevel=6, allowZip64=True) as z:
            for file in sorted(package.rglob("*")):
                if not file.is_file():
                    continue
                z.write(file, file.relative_to(out).as_posix())
                count += 1
        hasher = sha256()
        with archive.open("rb") as stream:
            for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
                hasher.update(chunk)
        digest = hasher.hexdigest()
        (out / (OUT_NAME + ".sha256")).write_text(
            digest + "  " + OUT_NAME + "\n", encoding="ascii"
        )
        report = {"archive": str(archive), "sha256": digest,
                  "source_commit": commit, "files": count,
                  "bytes": archive.stat().st_size,
                  "unpacked": str(package)}
        print(json.dumps(report, indent=2), flush=True)
        return report
    except Exception:
        if source.exists():
            source.unlink()
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

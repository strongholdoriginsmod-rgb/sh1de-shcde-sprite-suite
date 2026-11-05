"""Build a relocatable Windows ZIP with bundled CPython and dependencies.

Default release: audited CPython 3.13 plus its matching venv.
Optional --python-minor 15 --experimental requires a distinct CPython 3.15
runtime, version-matched venv and all 27 SHA-256-locked local QA wheels.
Exports ONLY committed project files (git archive); no local game files,
private workspaces, caches, or user settings. Never overwrites an output.
Both ZIPs start without globally installed Python or admin privileges.
The Python 3.15 ZIP is an EXPERIMENTAL QA artifact, not public Stable.
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
EXPERIMENTAL_PY315_NAME = (
    f"SpriteSuite-Windows-Portable-v{VERSION}-py315-x64-EXPERIMENTAL.zip"
)
PY315_FILES = (
    "python.exe", "pythonw.exe", "python3.dll", "python3t.dll",
    "python315.dll", "vcruntime140.dll", "vcruntime140_1.dll",
    "LICENSE.txt",
)
PY315_DIRS = ("DLLs", "Lib")


def _python_executable_runtime_version(home:Path)->tuple[int,int,int]:
    value = _subprocess(str(home/"python.exe"),"-c",
                 "import sys;print('.'.join(map(str, sys.version_info[:3])))",
                 cwd=home)
    try:
        components=tuple(int(v) for v in value.split("."))
    except ValueError as exc:
        raise RuntimeError("Cannot determine Python source version") from exc
    if len(components)!=3:
        raise RuntimeError("Unexpected Python runtime version")
    return components



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


def _check_binary_sources_315(python:Path,venv:Path)->None:
    if sys.platform!="win32":
        raise RuntimeError("Windows x64 packaging requires Windows")
    missing=[str(python/name) for name in PY315_FILES
             if not (python/name).is_file()]
    missing += [str(python/name) for name in PY315_DIRS
                if not (python/name).is_dir()]
    missing += [str(venv/name) for name in VENV_DIRS
                if not (venv/name).is_dir()]
    missing += [str(venv/"Scripts"/name) for name in ("python.exe","pythonw.exe")
                if not (venv/"Scripts"/name).is_file()]
    if missing:
        raise RuntimeError("Incomplete Python 3.15 portable sources: "+repr(missing))
    version=_python_executable_runtime_version(python)
    # Confirm the venv interpreter directly against its own base runtime.
    observed=_subprocess(str(venv/"Scripts"/"python.exe"),"-c",
                    "import sys;print('.'.join(map(str,sys.version_info[:3])))",
                    cwd=venv)
    if version[:2]!=(3,15) or observed!=".".join(map(str,version)):
        raise RuntimeError("Python 3.15 base/venv versions differ")
    # Safety: test the actual runtime against installed project dependencies.
    probe=_subprocess(str(venv/"Scripts"/"python.exe"),"-c",
       "import sys,tkinter,PIL,UnityPy,numpy,scipy,PySide6;"
       "from PySide6.QtWidgets import QApplication;"
       "print('PY315_RUNTIME_OK')",cwd=venv)
    if "PY315_RUNTIME_OK" not in probe:
        raise RuntimeError("Python 3.15 dependency import did not complete")
    # Hash locked source wheels are necessary but not sufficient: the active
    # venv must contain those exact versions and be internally consistent.
    lock=ROOT/"requirements-py315-win_amd64.lock"
    if not lock.is_file():
        raise RuntimeError("Python 3.15 requires committed dependency lock")
    pins={}
    for raw in lock.read_text("utf-8").splitlines():
        line=raw.strip()
        if "==" in line and line.endswith(chr(92)) and not line.startswith("#"):
            name,expected=line[:-1].strip().split("==",1)
            pins[name]=expected
    if len(pins)<27:
        raise RuntimeError("Incomplete Python 3.15 dependency lock")
    import json
    script=("from importlib import metadata; import json; "
        "names="+repr(list(pins))+"; "
        "print(json.dumps({n:metadata.version(n) for n in names}))")
    output=_subprocess(str(venv/"Scripts"/"python.exe"),"-c",script,cwd=venv)
    actual=json.loads(output)
    mismatch={name:(version,actual.get(name)) for name,version in pins.items()
              if actual.get(name)!=version}
    if mismatch:
        raise RuntimeError("Python 3.15 venv differs from lock: "+repr(mismatch))
    check=subprocess.run([str(venv/"Scripts"/"python.exe"),"-m","pip","check"],
                  cwd=venv,capture_output=True,text=True,encoding="utf8",
                  errors="replace",timeout=45)
    if check.returncode!=0:
        raise RuntimeError("Python 3.15 venv pip check failed: "
                           +(check.stdout+check.stderr)[-800:])


def _verify_cp315_hashed_wheelhouse(wheelhouse:Path)->dict:
    """Fail closed unless every tested 3.15 wheel byte matches the Git lock."""
    from packaging.utils import canonicalize_name,parse_wheel_filename
    wheelhouse=Path(wheelhouse)
    if (not wheelhouse.is_dir() or wheelhouse.is_symlink()
            or any(parent.is_symlink() for parent in wheelhouse.parents)):
        raise RuntimeError("CPython 3.15 requires a real local wheelhouse")
    lock=ROOT/"requirements-py315-win_amd64.lock"
    if not lock.is_file() or lock.is_symlink():
        raise RuntimeError("Missing source-committed CPython 3.15 hash lock")
    rows=[line.strip() for line in lock.read_text("utf-8").splitlines()
          if line.strip() and not line.lstrip().startswith("#")]
    if len(rows)%2 or len(rows)<24:
        raise RuntimeError("Malformed or incomplete CPython 3.15 wheel hash lock")
    expected={}
    for i in range(0,len(rows),2):
        line=rows[i]
        if not line.endswith("\\") or "==" not in line:
            raise RuntimeError("Malformed CPython 3.15 lock requirement")
        name,version=line[:-1].strip().split("==",1)
        key=canonicalize_name(name)
        second=rows[i+1]
        if (key in expected or
                not second.startswith("--hash=sha256:") or
                len(second)!=len("--hash=sha256:")+64):
            raise RuntimeError("Duplicate or invalid hash in CPython 3.15 lock")
        expected[key]=(version,second.split(":")[-1].lower())
    wheels={}
    for file in wheelhouse.glob("*.whl"):
        if file.is_symlink() or not file.is_file():
            raise RuntimeError("Linked or missing QA wheel file")
        name,version,_build,_tags=parse_wheel_filename(file.name)
        key=canonicalize_name(name)
        if key not in expected or key in wheels:
            raise RuntimeError("Unexpected/duplicate CPython 3.15 wheel: "+file.name)
        if str(version)!=expected[key][0]:
            raise RuntimeError("Wrong Python 3.15 wheel version: "+file.name)
        digest=sha256()
        with file.open("rb") as stream:
            for block in iter(lambda:stream.read(4*1024*1024),b""):
                digest.update(block)
        if digest.hexdigest()!=expected[key][1]:
            raise RuntimeError("CPython 3.15 wheel SHA-256 mismatch: "+file.name)
        wheels[key]=file
    if len(wheels)!=len(expected):
        raise RuntimeError("Missing CPython 3.15 locked wheels: "
                +repr(sorted(set(expected)-set(wheels))))
    return {"hash_locked_wheels":len(wheels),
            "wheel_bytes":sum(path.stat().st_size for path in wheels.values()),
            "requirements_sha256":sha256(lock.read_bytes()).hexdigest()}


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


def _is_protected_windows_temp(path: Path) -> bool:
    """Avoid staging Tcl scripts beneath Windows' protected system Temp.

    CPython can read init.tcl there with pathlib, while Tcl's native 'source'
    may still fail with ENOENT. A relocated runtime on a regular user-writable
    drive has been independently tested with real Tk initialization.
    """
    system_root = os.environ.get("SystemRoot") or os.environ.get("WINDIR")
    if not system_root:
        return False
    protected = str((Path(system_root) / "Temp").resolve()).casefold()
    actual = str(path.resolve()).casefold()
    return actual == protected or actual.startswith(protected + os.sep)


def build(python: Path, venv: Path, out: Path, *,
          python_minor:int=13, experimental:bool=False,
          wheelhouse:Path|None=None) -> dict:
    python = python.resolve(strict=True)
    venv = venv.resolve(strict=True)
    out = out.resolve()
    # The most important safety contract is checked BEFORE reading the
    # interpreter or probing modules. Never alter an existing destination.
    if out.exists():
        raise RuntimeError("Output directory already exists; refusing overwrite: "+str(out))
    wheel_provenance={}
    if python_minor==13:
        _check_binary_sources(python,venv)
        python_files,python_dirs=PYTHON_FILES,PYTHON_DIRS
        out_name=OUT_NAME
    elif python_minor==15 and experimental:
        if wheelhouse is None:
            raise RuntimeError(
                "Python 3.15 experimental requires --wheelhouse with 27 "
                "SHA-256-locked QA wheels")
        wheel_provenance=_verify_cp315_hashed_wheelhouse(wheelhouse)
        _check_binary_sources_315(python,venv)
        python_files,python_dirs=PY315_FILES,PY315_DIRS
        out_name=EXPERIMENTAL_PY315_NAME
    else:
        raise RuntimeError("Only tested Python 3.13 release or explicitly "
             "experimental Python 3.15 package may be built")
    # Ordinary releases already validate 3.13 through _check_binary_sources.
    # Preserve the mockable failure/rollback contracts in its unit tests.
    version=(_python_executable_runtime_version(python)
             if (python_minor==15 or (python/"python.exe").is_file())
             else (3,13,15))
    minor=f"{version[0]}.{version[1]}.{version[2]}"
    # No unverified Python installation is published as public Stable.
    if python_minor==15 and not experimental:
        raise RuntimeError("Python 3.15 requires explicit experimental flag")
    if out.exists():
        raise RuntimeError("Output directory already exists; refusing overwrite: " + str(out))
    if _is_protected_windows_temp(out):
        raise RuntimeError(
            "Windows system Temp cannot be used for portable Tcl/Tk staging; "
            "choose a new output directory on a normal user-writable drive."
        )
    out.parent.mkdir(parents=True, exist_ok=True)
    # Build in a new *sibling* folder. A failure never creates a misleading
    # half-built public release directory; the final rename happens last.
    final_out = out
    out = Path(tempfile.mkdtemp(prefix=".spritesuite-portable-stage-", dir=out.parent))
    package = out / "SpriteSuite"
    package.mkdir()
    archive = out / out_name
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
            python, package / "python", python_files + python_dirs,
            exclude_base_site_packages=True,
        )
        if (package / "python" / "Lib" / "site-packages").exists():
            raise RuntimeError("Private base Python packages leaked into runtime")
        print(f"COPY: CPython {minor} runtime", flush=True)
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
            f"version = {minor}\n", encoding="utf8"
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
            # Include the *start* of a Python traceback. A SyntaxError prints
            # the entire -c source after the actual exception; the old [-1200:]
            # often contained only that source and hid the useful error.
            raise RuntimeError(
                f"Bundled Python/Tk/Qt startup failed (exit {smoke.returncode})"
                + "\nSTDOUT:\n" + smoke.stdout[:4000]
                + "\nSTDERR BEGIN:\n" + smoke.stderr[:5000]
                + "\nSTDERR END:\n" + smoke.stderr[-1600:]
            )
        # Do not embed a developer-specific build path in the ZIP.
        (package / ".venv" / "pyvenv.cfg").write_text(
            "home = PORTABLE_LAUNCHER_WILL_SET_THIS\n"
            "include-system-site-packages = false\n"
            f"version = {minor}\n", encoding="utf8",
        )
        print("SMOKE: Python, Tk and Qt ready without system Python", flush=True)
        provenance = {
            "schema": "sprite-suite.windows-portable.v1",
            "source_commit": commit,
            "application_version": VERSION,
            "python": f"CPython {minor}, redistributed locally",
            "experimental_runtime":bool(experimental),
            "public_stable_approved":False,
            "python_wheel_lock_verified":(
                python_minor==13 or wheel_provenance.get("hash_locked_wheels",0)>=27),
            "experimental_python315_wheel_provenance":wheel_provenance,
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
        (out / (out_name + ".sha256")).write_text(
            digest + "  " + out_name + "\n", encoding="ascii"
        )
        report = {"archive": str(final_out / out_name), "sha256": digest,
                  "experimental_runtime":bool(experimental),
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
    ap.add_argument("--python-minor",type=int,choices=(13,15),default=13)
    ap.add_argument("--experimental",action="store_true",
                    help="Only for Python 3.15, not a public Stable release")
    ap.add_argument("--wheelhouse",type=Path,
                    help="Required: locally audited 27 hashed CPython 3.15 wheels")
    a = ap.parse_args()
    try:
        build(a.python_home, a.venv, a.out,
              python_minor=a.python_minor,experimental=a.experimental,
              wheelhouse=a.wheelhouse)
        return 0
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print("PORTABLE_BUILD_ERROR:", exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

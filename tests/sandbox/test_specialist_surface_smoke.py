"""Every specialist module imports and every argparse CLI explains itself.

These are import/help smoke tests, not proofs that every tool operation works.
They intentionally do not run commands that edit artwork or game files.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
TOOLS = tuple(sorted((ROOT / "tools").glob("*.py")))


def _env(tmp_path: Path) -> dict:
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONPATH"] = os.pathsep.join(filter(None, (
        str(ROOT / "tools"), str(ROOT / "src"), str(ROOT),
        os.environ.get("PYTHONPATH",""),
    )))
    for kind, key in (("user","USERPROFILE"),("local","LOCALAPPDATA"),
                      ("roaming","APPDATA")):
        path = tmp_path / kind
        path.mkdir(parents=True,exist_ok=True)
        env[key] = str(path)
    return env


def _execute(path: Path, *, help_only: bool, env: dict):
    command = ([sys.executable,str(path),"--help"] if help_only else
               [sys.executable,"-c",
                "import importlib,sys; importlib.import_module(sys.argv[1])",
                path.stem])
    try:
        run = subprocess.run(
            command, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
            capture_output=True, timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW",0),
        )
    except subprocess.TimeoutExpired:
        return path.name + ": timed out"
    except OSError as exc:
        return path.name + ": " + str(exc)
    if run.returncode:
        tail=(run.stdout+b"\n"+run.stderr).decode("utf8",errors="replace")[-600:]
        return path.name + " (" + str(run.returncode) + "): " + tail
    return None


def _all_failing(paths, env, help_only):
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(_execute, p, help_only=help_only, env=env):p
                   for p in paths}
        return [result for future in as_completed(futures)
                if (result:=future.result()) is not None]


def test_all_145_tool_modules_import_without_configured_game(tmp_path):
    assert len(TOOLS) >= 145, "A previously tracked tool disappeared"
    errors = _all_failing(TOOLS, _env(tmp_path), False)
    assert not errors, "\n\n".join(sorted(errors))


def test_every_argparse_tool_prints_help_without_game_installation(tmp_path):
    tools = [
        path for path in TOOLS
        if "argparse.ArgumentParser" in path.read_text("utf8")
        and "__main__" in path.read_text("utf8")
    ]
    assert len(tools) >= 75, "CLI entrypoint coverage unexpectedly decreased"
    errors = _all_failing(tools, _env(tmp_path), True)
    assert not errors, "\n\n".join(sorted(errors))

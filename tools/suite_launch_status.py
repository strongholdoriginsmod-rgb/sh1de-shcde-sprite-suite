"""A detached GUI is successful only after its Tk event loop reports ready."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import time


def announce_ready(path: Path, pid: int) -> None:
    """Publish a single explicit readiness marker through an atomic rename."""
    path = Path(path)
    if not path.parent.is_dir() or path.is_symlink():
        raise OSError("Unsafe or missing startup marker directory")
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".ready-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump({"schema":1,"ready":True,"pid":pid},output)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(name,path)
    finally:
        Path(name).unlink(missing_ok=True)


def await_ready(process, path: Path, *, timeout: float = 16.0) -> tuple[bool, str]:
    """Wait for the actual child event loop without claiming mere spawn success."""
    deadline=time.monotonic()+timeout
    path=Path(path)
    while time.monotonic()<deadline:
        if path.is_file():
            try:
                data=json.loads(path.read_text("utf8"))
                if (data.get("schema")==1 and data.get("ready") is True
                        and data.get("pid")==process.pid):
                    return True,"GUI_READY=1"
            except (OSError,UnicodeError,ValueError,AttributeError):
                pass
        code=process.poll()
        if code is not None:
            return False,f"GUI exited before readiness (exit={code})"
        time.sleep(0.1)
    return False,"No GUI readiness confirmation; the child may still be running"

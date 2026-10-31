"""A detached GUI is successful only after its Tk event loop reports ready."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
import tempfile
import time


def announce_ready(path: Path, pid: int, *, nonce: str | None = None) -> None:
    """Publish a one-time event-loop proof, independent of venv redirector PID."""
    if nonce is not None and re.fullmatch(r"[0-9a-f]{32}", nonce) is None:
        raise ValueError("Startup nonce must be a 128-bit hex token")
    path = Path(path)
    if not path.parent.is_dir() or path.is_symlink():
        raise OSError("Unsafe or missing startup marker directory")
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".ready-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            record={"schema":1,"ready":True,"pid":pid}
            if nonce is not None:
                record["nonce"]=nonce
            json.dump(record,output)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(name,path)
    finally:
        Path(name).unlink(missing_ok=True)


def await_ready(
    process, path: Path, *, timeout: float = 16.0,
    nonce: str | None = None,
) -> tuple[bool, str]:
    """Check a one-use capability token, not the Windows redirector process ID.

    The venv python/pythonw launchers spawn a second interpreter and may
    return a different PID from os.getpid() inside the running Tk event loop.
    A fresh 128-bit token plus a private, unique marker path binds readiness
    to this invocation without trusting that implementation-specific PID.
    """
    if nonce is not None and re.fullmatch(r"[0-9a-f]{32}", nonce) is None:
        raise ValueError("Startup nonce must be a 128-bit hex token")
    deadline=time.monotonic()+timeout
    path=Path(path)
    while time.monotonic()<deadline:
        if path.is_file():
            try:
                data=json.loads(path.read_text("utf8"))
                valid_pid=(type(data.get("pid")) is int and data["pid"]>0)
                valid_identity=(
                    data.get("nonce")==nonce if nonce is not None
                    else data.get("pid")==process.pid
                )
                if (data.get("schema")==1 and data.get("ready") is True
                        and valid_pid and valid_identity and process.poll() is None):
                    return True,"GUI_READY=1"
            except (OSError,UnicodeError,ValueError,AttributeError):
                pass
        code=process.poll()
        if code is not None:
            return False,f"GUI exited before readiness (exit={code})"
        time.sleep(0.1)
    return False,"No GUI readiness confirmation; the child may still be running"

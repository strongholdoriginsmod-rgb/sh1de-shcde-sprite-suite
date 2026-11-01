"""Short, private Windows filesystem scratch space for legacy csc.exe.

The .NET Framework 4 CSC compiler can fail with ERROR_INSUFFICIENT_BUFFER
when a nested source project's compilation output path is very long. This
module keeps ONLY temporary compiler inputs/outputs in a short user-local
folder, never in a game installation or an unrelated user's directory.

All build evidence is copied and reverified in its final private work/ folder.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import os
import tempfile
from typing import Iterator

from suite_windows_paths import is_link_or_reparse as linked


class CSharpScratchError(ValueError):
    pass


def _short_csc_base()->Path:
    profile=os.environ.get("LOCALAPPDATA")
    if not profile:
        # Windows user profile path is preferred over system Temp. A normal
        # temporary directory remains the fallback for restricted CI.
        profile=tempfile.gettempdir()
    root=Path(profile)/"SpriteSuite"/"CSharpScratch"
    if root.exists():
        if not root.is_dir() or linked(root):
            raise CSharpScratchError("Private CSC temporary folder is linked")
    else:
        root.mkdir(parents=True,exist_ok=True)
    return root


@contextmanager
def short_csharp_scratch()->Iterator[Path]:
    """Create/dispose a short user-owned path; never return it as final output."""
    root=_short_csc_base()
    with tempfile.TemporaryDirectory(prefix="sm-",dir=root) as directory:
        path=Path(directory)
        if linked(path):
            raise CSharpScratchError("Compiler scratch folder is linked")
        yield path

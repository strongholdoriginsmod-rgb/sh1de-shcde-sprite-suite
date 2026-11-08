"""Start SpriteSuite 3 Modding Studio CLI/GUI from a project checkout."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stronghold_europe_de.modding_studio.cli import main

if __name__ == "__main__":
    raise SystemExit(main())

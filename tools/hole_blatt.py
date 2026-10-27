"""Ein heruntergeladenes Blatt aus dem Download-Ordner uebernehmen.

Auf den Dateinamen ist kein Verlass: beobachtet wurden der richtige Name, ein
fremder Name und eine .tmp-Datei mit Zufalls-UUID. Auf das Bildmass ist es
ebenfalls nicht - der Eigentuemer laedt im selben Ordner eigene Bilder herunter,
und beim ersten Versuch wurde so ein fremdes 1672x941-Bild eingesammelt.
Eindeutig ist allein die Byte-Zahl, die der Browser beim Holen gemeldet hat.

Aufruf:  python tools/hole_blatt.py <nummer> <bytes>
"""
from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

from PIL import Image

DOWNLOADS = Path.home() / "Downloads"
ZIEL = Path(__file__).resolve().parents[1] / "work" / "ui-europa-buttons" / "blaetter"


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    nummer, bytes_soll = sys.argv[1], int(sys.argv[2])
    treffer = [p for p in DOWNLOADS.iterdir() if p.is_file() and p.stat().st_size == bytes_soll]
    if len(treffer) != 1:
        print(f"nicht eindeutig: {[p.name for p in treffer]}")
        return 1
    quelle = treffer[0]
    im = Image.open(quelle)
    ZIEL.mkdir(parents=True, exist_ok=True)
    ziel = ZIEL / f"blatt-{nummer}.png"
    shutil.copy(quelle, ziel)
    pruef = hashlib.sha256(ziel.read_bytes()).hexdigest()[:16]
    print(f"{quelle.name} -> {ziel.name}  {im.size[0]}x{im.size[1]} {im.mode}  {bytes_soll} B  sha {pruef}")
    try:
        quelle.unlink()
    except OSError:
        print("  (Quelle noch vom Browser gehalten, bleibt liegen)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

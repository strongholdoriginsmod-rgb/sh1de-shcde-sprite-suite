"""Gemalte Gegenstaende aus einem farbigen Blatt freistellen.

Anders als die Schwarzweissblaetter (`ui_button_zeichen.py`) liefert der
Generator hier fertig gemalte Gegenstaende auf weissem Grund. Freigestellt wird
darum nicht ueber eine Helligkeitsschwelle, sondern als **Weissmatte**:

- Hintergrund ist, was nahe an Weiss und nahezu unbunt ist.
- Die Deckung ergibt sich weich aus dem Abstand zu Weiss, damit
  Kantenglaettung und der weiche Schlagschatten erhalten bleiben statt
  ausgestanzt zu werden.
- Anschliessend wird die Farbe **gegen Weiss entmischt**
  (`c = (c - (1-a)*255) / a`). Ohne diesen Schritt behaelt jeder halb deckende
  Randpixel einen weissen Schleier, der auf dem dunklen Ring als heller Saum
  auffaellt.

Die Zuordnung der Teile zu den zwoelf Feldern arbeitet wie beim
Schwarzweissschneider ueber Zusammenhangskomponenten und Mehrheit, weil auch
hier Gegenstaende ueber ihre Rasterzelle hinausragen.

Ablage: work/ui-europa-buttons/gemalt/<name>.png (RGBA)
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "work" / "ui-europa-buttons"
BLAETTER = OUT / "blaetter"
GEMALT = OUT / "gemalt"

SPALTEN, ZEILEN = 4, 3
WEISS_HART = 246.0   # darueber gilt ein Pixel als reiner Hintergrund
WEISS_WEICH = 200.0  # darunter gilt er als voll deckend
BUNT = 0.10          # ab dieser Buntheit zaehlt ein heller Pixel als Gegenstand
MINDEST = 400        # Komponenten darunter sind Rauschen oder Schattenfetzen
KANTE = 512


def _deckung(bild: np.ndarray) -> np.ndarray:
    """Weiche Deckung aus dem Abstand zu Weiss."""
    tief = bild.min(axis=-1)
    hoch = bild.max(axis=-1)
    buntheit = (hoch - tief) / np.maximum(hoch, 1.0)
    a = np.clip((WEISS_HART - tief) / (WEISS_HART - WEISS_WEICH), 0.0, 1.0)
    return np.maximum(a, np.clip(buntheit / BUNT, 0.0, 1.0) * (tief < WEISS_HART))


def _entmischen(bild: np.ndarray, a: np.ndarray) -> np.ndarray:
    sicher = np.maximum(a, 1e-3)[..., None]
    return np.clip((bild - (1.0 - a[..., None]) * 255.0) / sicher, 0, 255)


def blatt_schneiden(pfad: Path, namen: list[str], spalten: int = SPALTEN,
                    zeilen: int = ZEILEN) -> list[dict]:
    if len(namen) != spalten * zeilen:
        raise SystemExit(f"{pfad.name}: {len(namen)} Namen fuer {spalten * zeilen} Felder")
    bild = np.asarray(Image.open(pfad).convert("RGB"), dtype=np.float32)
    h, w = bild.shape[:2]
    a = _deckung(bild)
    fest = a > 0.55
    fest = ndimage.binary_closing(fest, np.ones((3, 3), bool))
    marken, anzahl = ndimage.label(fest, structure=np.ones((3, 3), bool))

    ys, xs = np.mgrid[0:h, 0:w]
    zellen = (np.minimum((ys * zeilen) // h, zeilen - 1) * spalten
              + np.minimum((xs * spalten) // w, spalten - 1))
    felder = spalten * zeilen
    groessen = np.bincount(marken.ravel(), minlength=anzahl + 1)
    kreuz = np.zeros((anzahl + 1, felder), dtype=np.int64)
    np.add.at(kreuz, (marken.ravel(), zellen.ravel()), 1)
    zugehoerig = np.full(anzahl + 1, -1, dtype=np.int16)
    for m in range(1, anzahl + 1):
        if groessen[m] >= MINDEST:
            zugehoerig[m] = int(np.argmax(kreuz[m]))

    GEMALT.mkdir(parents=True, exist_ok=True)
    bericht = []
    for i, name in enumerate(namen):
        gehoert = np.isin(marken, np.nonzero(zugehoerig == i)[0])
        if not gehoert.any():
            bericht.append({"zeichen": name, "warnung": "Feld leer"})
            continue
        # Der weiche Saum liegt ausserhalb der harten Maske; drei Pixel Weitung
        # holen ihn zurueck, ohne den Nachbarn anzufassen.
        saum = ndimage.binary_dilation(gehoert, iterations=3)
        deckung = np.where(saum, a, 0.0)
        farbe = _entmischen(bild, deckung)

        yy, xx = np.nonzero(deckung > 0.04)
        kasten = (int(xx.min()), int(yy.min()), int(xx.max()) + 1, int(yy.max()) + 1)
        rgba = np.concatenate([farbe, (deckung * 255)[..., None]], axis=-1)
        aus = Image.fromarray(rgba.clip(0, 255).round().astype(np.uint8), "RGBA").crop(kasten)
        s = KANTE / max(aus.size)
        aus = aus.resize((max(1, round(aus.width * s)), max(1, round(aus.height * s))), Image.LANCZOS)
        aus.save(GEMALT / f"{name}.png")

        bericht.append({
            "zeichen": name, "feld": i, "groesse": list(aus.size),
            "teile": int((zugehoerig == i).sum()),
            "flaeche": round(float(gehoert.sum()) / (bild[..., 0].size / felder), 3),
            "ueberstand": bool(kreuz[np.nonzero(zugehoerig == i)[0], i].sum()
                               < groessen[np.nonzero(zugehoerig == i)[0]].sum()),
        })
    return bericht


def kontaktbogen(namen: list[str], ziel: Path, zelle: int = 190) -> None:
    spalten = 6
    reihen = (len(namen) + spalten - 1) // spalten
    bogen = Image.new("RGB", (spalten * zelle, reihen * (zelle + 20)), (54, 52, 48))
    d = ImageDraw.Draw(bogen)
    for i, name in enumerate(namen):
        p = GEMALT / f"{name}.png"
        bx, by = (i % spalten) * zelle, (i // spalten) * (zelle + 20)
        if p.exists():
            im = Image.open(p).convert("RGBA")
            im.thumbnail((zelle - 16, zelle - 16))
            bogen.paste(im, (bx + (zelle - im.width) // 2, by + (zelle - im.height) // 2), im)
        d.text((bx + 4, by + zelle + 4), name, fill=(232, 228, 220))
    bogen.save(ziel)


def main() -> int:
    import sys
    if len(sys.argv) < 5:
        print("Aufruf: python tools/ui_button_zeichen_farbe.py <blatt> <spalten> <zeilen> <name1> ...")
        return 2
    pfad = Path(sys.argv[1])
    spalten, zeilen = int(sys.argv[2]), int(sys.argv[3])
    namen = sys.argv[4:]
    bericht = blatt_schneiden(pfad, namen, spalten, zeilen)
    for b in bericht:
        w = f"  << {b['warnung']}" if b.get("warnung") else ""
        u = "  ueberstehend" if b.get("ueberstand") else ""
        print(f"  {b['zeichen']:20s} {str(b.get('groesse','-')):12s} Teile {b.get('teile','-'):>3}"
              f"  Flaeche {b.get('flaeche','-')}{u}{w}")
    ziel = OUT / "kontaktbogen_gemalt.png"
    kontaktbogen(namen, ziel)
    print(f"\nKontaktbogen: {ziel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

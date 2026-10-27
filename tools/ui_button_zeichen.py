"""Zeichen aus den erzeugten Blaettern schneiden.

Die Blaetter kommen als 1254x1254 grosse Rasterbilder mit zwoelf weissen
Piktogrammen auf schwarzem Grund.

**Nicht starr am Raster geschnitten.** Gemessen an Blatt 2 ragen fuenf von
zwoelf Zeichen ueber ihre Rasterzelle hinaus - der Wurfarm der Blide, der Bart
des Schluessels, die Schulter des Harnischs. Ein Schnitt entlang der
Zellgrenzen wuerde sie abschneiden. Stattdessen werden alle Zusammenhangs-
komponenten des Blattes bestimmt und jede der Zelle zugeschlagen, in der die
**Mehrheit ihrer Pixel** liegt. Das haelt ein ueberstehendes Zeichen ganz und
zieht trotzdem nichts vom Nachbarn herein.

Jedes Zeichen wird in zwei Ebenen zerlegt:

- **Silhouette**: der Umriss mit gefuellten Innenloechern. Sie traegt die
  Metallfuellung.
- **Detail**: genau die Innenloecher - die Fugen, Reifen und Kanten, die der
  Generator hineinzeichnet. Sie werden als dunklere Gravur eingesetzt statt als
  Loch, weil ein 30 Pixel breites Zeichen mit durchsichtigen Fugen zerfaellt.

Beide Ebenen behalten die Kantenglaettung des Blattes; binaer arbeitet nur die
Komponenten- und Lochsuche.

Ablage: work/ui-europa-buttons/zeichen/<name>.png
        (RGBA, Alpha = Silhouette, Rotkanal = Detailstaerke)
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
ZEICHEN = OUT / "zeichen"

SPALTEN, ZEILEN = 4, 3
SCHWELLE = 128
SAUM = 3     # Pixel, um die die Komponentenmaske geweitet wird (Kantenglaettung)
MINDEST = 40  # Komponenten darunter sind Rauschen
KANTE = 512  # laengste Kante des abgelegten Zeichens


def _zellzuordnung(grau: np.ndarray) -> tuple[np.ndarray, int]:
    """Jedem Pixel die Nummer seiner Zelle geben (0..11)."""
    h, w = grau.shape
    ys, xs = np.mgrid[0:h, 0:w]
    spalte = np.minimum((xs * SPALTEN) // w, SPALTEN - 1)
    zeile = np.minimum((ys * ZEILEN) // h, ZEILEN - 1)
    return zeile * SPALTEN + spalte, SPALTEN * ZEILEN


def blatt_schneiden(pfad: Path, namen: list[str]) -> list[dict]:
    if len(namen) != SPALTEN * ZEILEN:
        raise SystemExit(f"{pfad.name}: {len(namen)} Namen fuer {SPALTEN * ZEILEN} Felder")
    grau = np.asarray(Image.open(pfad).convert("L"), dtype=np.uint8)
    binaer = grau >= SCHWELLE
    marken, anzahl = ndimage.label(binaer, structure=np.ones((3, 3), bool))
    zellen, felder = _zellzuordnung(grau)

    # Jede Komponente geht an die Zelle, in der die Mehrheit ihrer Pixel liegt.
    zugehoerig = np.zeros(anzahl + 1, dtype=np.int16) - 1
    ueberstand = np.zeros(anzahl + 1, dtype=bool)
    groessen = np.bincount(marken.ravel(), minlength=anzahl + 1)
    kreuz = np.zeros((anzahl + 1, felder), dtype=np.int64)
    np.add.at(kreuz, (marken.ravel(), zellen.ravel()), 1)
    for m in range(1, anzahl + 1):
        if groessen[m] < MINDEST:
            continue
        zeile = kreuz[m]
        beste = int(np.argmax(zeile))
        zugehoerig[m] = beste
        ueberstand[m] = zeile[beste] < groessen[m]

    ZEICHEN.mkdir(parents=True, exist_ok=True)
    bericht = []
    for i, name in enumerate(namen):
        gehoert = np.isin(marken, np.nonzero(zugehoerig == i)[0])
        if not gehoert.any():
            bericht.append({"zeichen": name, "warnung": "Feld leer"})
            continue
        gefuellt = ndimage.binary_fill_holes(gehoert)
        saum = ndimage.binary_dilation(gefuellt, iterations=SAUM)
        weich = np.where(saum, grau, 0)
        silhouette = np.maximum(weich, gefuellt * 255).astype(np.uint8)
        detail = (silhouette.astype(np.int16) - weich.astype(np.int16)).clip(0, 255).astype(np.uint8)

        ys, xs = np.nonzero(silhouette > 24)
        kasten = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
        sil = Image.fromarray(silhouette).crop(kasten)
        det = Image.fromarray(detail).crop(kasten)
        s = KANTE / max(sil.size)
        ziel = (max(1, round(sil.width * s)), max(1, round(sil.height * s)))
        sil, det = sil.resize(ziel, Image.LANCZOS), det.resize(ziel, Image.LANCZOS)
        Image.merge("RGBA", (det, Image.new("L", ziel, 0), Image.new("L", ziel, 0), sil)).save(
            ZEICHEN / f"{name}.png")

        teile = int((zugehoerig == i).sum())
        flaeche = float(gefuellt.sum()) / (grau.size / felder)
        bericht.append({
            "zeichen": name, "feld": i, "groesse": list(ziel), "teile": teile,
            "flaeche": round(flaeche, 3),
            "detailanteil": round(float(np.asarray(det).mean() / max(1e-6, np.asarray(sil).mean())), 3),
            "ueberstand": bool(ueberstand[np.nonzero(zugehoerig == i)[0]].any()),
            "warnung": "sehr wenig Flaeche" if flaeche < 0.02 else None,
        })
    return bericht


def kontaktbogen(namen: list[str], ziel: Path, zelle: int = 190) -> None:
    spalten = 6
    reihen = (len(namen) + spalten - 1) // spalten
    bogen = Image.new("RGB", (spalten * zelle, reihen * (zelle + 20)), (36, 40, 38))
    d = ImageDraw.Draw(bogen)
    for i, name in enumerate(namen):
        p = ZEICHEN / f"{name}.png"
        bx, by = (i % spalten) * zelle, (i // spalten) * (zelle + 20)
        if p.exists():
            im = Image.open(p).convert("RGBA")
            flach = Image.new("RGBA", im.size, (0xC9, 0xA2, 0x27, 0))
            flach.putalpha(im.getchannel("A"))
            dunkel = Image.new("RGBA", im.size, (0x6E, 0x50, 0x10, 0))
            dunkel.putalpha(im.getchannel("R"))
            flach.alpha_composite(dunkel)
            flach.thumbnail((zelle - 16, zelle - 16))
            bogen.paste(flach, (bx + (zelle - flach.width) // 2, by + (zelle - flach.height) // 2), flach)
        d.text((bx + 4, by + zelle + 4), name, fill=(230, 230, 220))
    bogen.save(ziel)


def main() -> int:
    auftraege = json.loads((OUT / "auftraege.json").read_text(encoding="utf-8"))
    alle: list[str] = []
    for blatt in auftraege["blaetter"]:
        pfad = BLAETTER / f"blatt-{blatt['nummer']}.png"
        if not pfad.exists():
            print(f"Blatt {blatt['nummer']} ({blatt['name']}): noch nicht da")
            continue
        namen = [z[0] for z in blatt["zeichen"]]
        bericht = blatt_schneiden(pfad, namen)
        alle.extend(namen)
        print(f"Blatt {blatt['nummer']} ({blatt['name']}):")
        for b in bericht:
            w = f"  << {b['warnung']}" if b.get("warnung") else ""
            u = "  ueberstehend" if b.get("ueberstand") else ""
            print(f"  {b['zeichen']:22s} {str(b.get('groesse', '-')):12s} Teile {b.get('teile', '-'):>3}"
                  f"  Flaeche {b.get('flaeche', '-')}  Detail {b.get('detailanteil', '-')}{u}{w}")
    if alle:
        ziel = OUT / "kontaktbogen_zeichen.png"
        kontaktbogen(alle, ziel)
        print(f"\nKontaktbogen: {ziel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

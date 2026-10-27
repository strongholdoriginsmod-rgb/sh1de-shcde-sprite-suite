"""Die Traeger der Knopfgrafiken: Wappenschild, Ring, Scheibe, Rolle, Rahmen.

Jeder Traeger wird ueberabgetastet gezeichnet und liefert neben dem Bild das
**Zeichenfeld** zurueck - das Rechteck in Zielpixeln, in das spaeter das
Zeichen gesetzt wird - und die Farbe, die das Zeichen in diesem Zustand traegt.

Die Zustandsnamen sind die des Bestands (`ruhend`, `ueberfahren`, `gedrueckt`,
`aus`), nicht erfundene. Welche Nummer welchen Zustand traegt, steht in
`work/ui-europa-buttons/motive.json`.

Aufruf zur Sichtprobe:  python tools/ui_button_rahmen.py
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

from ui_nordlicht import (PAL, SS, einfaerben, fase, flaeche, korn_auflegen,
                          maske_aus_kreis, maske_aus_polygon, mische,
                          radialer_verlauf, rand, schatten, schrumpfen,
                          senkrechter_verlauf, verkleinern, wappenschild_pfad)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "work" / "ui-europa-buttons"


@dataclass
class Traeger:
    bild: Image.Image
    feld: tuple[int, int, int, int]
    zeichenfarbe: tuple[int, int, int]
    zeichendeckung: float = 1.0


# --- Zustandstafeln -------------------------------------------------------
# Grundton oben, Grundton unten, Randfarbe, Zeichenfarbe, Gesamtdeckung.
SCHILD = {
    "ruhend":      ("schiefer_hell", "schiefer",        "messing",      "messing",     1.0),
    "ueberfahren": ("gruenspan",     "schiefer_hell",   "messing_hell", "pergament",   1.0),
    "gedrueckt":   ("zinnober_dunkel", "zinnober_tief", "messing_tief", "pergament",   1.0),
    "aus":         ("zinn",          "zinn_tief",       "zinn_hell",    "zinn_tief",   0.70),
}

RING = {
    "ruhend":      ("zinn_hell", "zinn_tief",     "schiefer",       "pergament", 1.0),
    "ueberfahren": ("messing_hell", "messing",    "schiefer_hell",  "pergament", 1.0),
    "gedrueckt":   ("messing", "messing_tief",    "zinnober_tief",  "pergament", 1.0),
    "aus":         ("zinn_hell", "zinn",           "zinn_tief",      "zinn_tief", 0.70),
}

RAHMEN2 = {
    "ruhend":      ("schiefer_hell", "schiefer", "messing",      "pergament", 1.0),
    "ueberfahren": ("gruenspan", "schiefer_hell", "messing_hell", "pergament", 1.0),
}

ROLLE = {
    "ruhend":      ("pergament", "messing",      1.0),
    "ueberfahren": ("pergament", "gruenspan",    1.0),
}


def _grund(maske: Image.Image, oben: str, unten: str, saat: int) -> Image.Image:
    fuell = senkrechter_verlauf(maske.size, PAL[oben], PAL[unten])
    fuell = korn_auflegen(fuell, staerke=5, saat=saat)
    return flaeche(maske, fuell)


# Umrissbeiwerte des Wappenschilds, gegen `UI-Buttons A001` angepasst:
# Rasterlauf ueber Schulterhoehe, Flankenzug, Rand und Hoehenversatz,
# beste Deckung IoU 0,969. Nicht nach Gefuehl aendern - der Lauf steht in
# `docs/AGENT_COORDINATION.md` und ist in Minuten wiederholt.
SCHILD_SCHULTER = 0.44
SCHILD_ZUG = 0.62
SCHILD_RAND = 0.050   # Anteil der Breite
SCHILD_VERSATZ = 0.014  # Anteil der Hoehe, nach unten


def _schildmaske(W: int, H: int, w: int, h: int) -> Image.Image:
    dy = SCHILD_VERSATZ * h * SS
    pfad = wappenschild_pfad(W, H, rand=SCHILD_RAND * w * SS,
                             schulteranteil=SCHILD_SCHULTER, zug=SCHILD_ZUG)
    return maske_aus_polygon((W, H), [(x, y + dy) for x, y in pfad])


def wappenschild(w: int, h: int, zustand: str, saat: int = 4711) -> Traeger:
    oben, unten, randfarbe, zeichen, deckung = SCHILD[zustand]
    W, H = w * SS, h * SS
    umriss = _schildmaske(W, H, w, h)
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    im.alpha_composite(schatten(umriss, int(0.9 * SS), 1.6 * SS, 0.45))
    im.alpha_composite(_grund(umriss, oben, unten, saat))
    band = rand(umriss, 1.6 * SS)
    im.alpha_composite(einfaerben(band, PAL[randfarbe]))
    im.alpha_composite(flaeche(umriss, fase(umriss, staerke=int(0.7 * SS), licht=0.30, schatten=0.32)))
    aus = verkleinern(im, w, h)
    if deckung < 1.0:
        aus.putalpha(aus.getchannel("A").point(lambda p: int(p * deckung)))
    feld = (int(w * 0.17), int(h * 0.13), int(w * 0.83), int(h * 0.72))
    return Traeger(aus, feld, PAL[zeichen])


def scheibe(w: int, h: int, zustand: str = "ruhend", saat: int = 4712) -> Traeger:
    W, H = w * SS, h * SS
    r = min(W, H) / 2 - 1.2 * SS
    mitte = (W / 2, H / 2)
    umriss = maske_aus_kreis((W, H), mitte, r)
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    im.alpha_composite(schatten(umriss, int(0.8 * SS), 1.4 * SS, 0.45))
    fuell = radialer_verlauf((W, H), PAL["zinnober_mittel"], PAL["zinnober_tief"],
                             mitte=(W * 0.38, H * 0.32))
    im.alpha_composite(flaeche(umriss, korn_auflegen(fuell, staerke=5, saat=saat)))
    im.alpha_composite(einfaerben(rand(umriss, 1.3 * SS), PAL["messing_tief"]))
    im.alpha_composite(flaeche(umriss, fase(umriss, staerke=int(0.8 * SS), licht=0.34, schatten=0.30)))
    aus = verkleinern(im, w, h)
    feld = (int(w * 0.20), int(h * 0.20), int(w * 0.80), int(h * 0.80))
    return Traeger(aus, feld, PAL["pergament"])


def ring(w: int, h: int, zustand: str, kasten: tuple[int, int, int, int], saat: int = 4713) -> Traeger:
    """Ringknopf. `kasten` ist das gemessene Inhaltsrechteck im Blatt."""
    metall_oben, metall_unten, feldfarbe, zeichen, deckung = RING[zustand]
    W, H = w * SS, h * SS
    x0, y0, x1, y1 = (v * SS for v in kasten)
    mitte = ((x0 + x1) / 2, (y0 + y1) / 2)
    r_aussen = min(x1 - x0, y1 - y0) / 2 - 0.8 * SS
    r_innen = r_aussen * 0.72
    aussen = maske_aus_kreis((W, H), mitte, r_aussen)
    innen = maske_aus_kreis((W, H), mitte, r_innen)
    reif = ImageChops.subtract(aussen, innen)

    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    im.alpha_composite(schatten(aussen, int(1.0 * SS), 1.8 * SS, 0.45))
    feld_fuell = radialer_verlauf((W, H), mische(PAL[feldfarbe], PAL["pergament"], 0.14),
                                  PAL[feldfarbe], mitte=(mitte[0] - r_innen * 0.3, mitte[1] - r_innen * 0.35))
    im.alpha_composite(flaeche(innen, korn_auflegen(feld_fuell, staerke=4, saat=saat)))
    metall = senkrechter_verlauf((W, H), PAL[metall_oben], PAL[metall_unten])
    im.alpha_composite(flaeche(reif, korn_auflegen(metall, staerke=4, saat=saat + 1)))
    im.alpha_composite(flaeche(reif, fase(reif, staerke=int(0.9 * SS), licht=0.40, schatten=0.34)))
    im.alpha_composite(einfaerben(rand(innen, 0.9 * SS), PAL["nacht"]).point(lambda p: p))

    aus = verkleinern(im, w, h)
    if deckung < 1.0:
        aus.putalpha(aus.getchannel("A").point(lambda p: int(p * deckung)))
    rr = int(r_innen / SS * 0.80)
    cx, cy = int(mitte[0] / SS), int(mitte[1] / SS)
    feld = (cx - rr, cy - rr, cx + rr, cy + rr)
    return Traeger(aus, feld, PAL[zeichen])


def ring_grund(w: int, h: int, zustand: str, feldfarbe: str, saat: int = 4714) -> Traeger:
    """Ring mit voll gefuelltem Grund - traegt die beiden Panzerhandschuhe."""
    metall = "messing" if zustand == "ruhend" else "messing_hell"
    W, H = w * SS, h * SS
    mitte = (W / 2, H / 2)
    r_aussen = min(W, H) / 2 - 1.2 * SS
    r_innen = r_aussen * 0.80
    aussen = maske_aus_kreis((W, H), mitte, r_aussen)
    innen = maske_aus_kreis((W, H), mitte, r_innen)
    reif = ImageChops.subtract(aussen, innen)
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    im.alpha_composite(schatten(aussen, int(0.9 * SS), 1.6 * SS, 0.45))
    grund = radialer_verlauf((W, H), mische(PAL[feldfarbe], PAL["pergament"], 0.18), PAL[feldfarbe],
                             mitte=(W * 0.38, H * 0.32))
    im.alpha_composite(flaeche(innen, korn_auflegen(grund, staerke=4, saat=saat)))
    im.alpha_composite(flaeche(reif, senkrechter_verlauf((W, H), PAL[metall], PAL["messing_tief"])))
    im.alpha_composite(flaeche(reif, fase(reif, staerke=int(0.9 * SS), licht=0.42, schatten=0.34)))
    aus = verkleinern(im, w, h)
    r = int(r_innen / SS * 0.86)
    feld = (w // 2 - r, h // 2 - r, w // 2 + r, h // 2 + r)
    return Traeger(aus, feld, PAL["pergament"])


def steinrahmen(w: int, h: int, zustand: str, saat: int = 4715) -> Traeger:
    oben, unten, randfarbe, zeichen, _ = RAHMEN2[zustand]
    W, H = w * SS, h * SS
    aussen = Image.new("L", (W, H), 0)
    ImageDraw.Draw(aussen).rounded_rectangle([1.0 * SS, 1.0 * SS, W - 1.0 * SS, H - 1.0 * SS],
                                             radius=2.5 * SS, fill=255)
    innen = Image.new("L", (W, H), 0)
    ImageDraw.Draw(innen).rounded_rectangle([9.0 * SS, 9.0 * SS, W - 9.0 * SS, H - 9.0 * SS],
                                            radius=1.5 * SS, fill=255)
    band = ImageChops.subtract(aussen, innen)
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    im.alpha_composite(flaeche(innen, senkrechter_verlauf((W, H), PAL["nacht"], PAL["schiefer"])))
    im.alpha_composite(_grund(band, oben, unten, saat))
    im.alpha_composite(einfaerben(rand(innen, 1.1 * SS), PAL[randfarbe]))
    im.alpha_composite(flaeche(band, fase(band, staerke=int(0.8 * SS), licht=0.30, schatten=0.34)))
    aus = verkleinern(im, w, h)
    feld = (int(w * 0.16), int(h * 0.16), int(w * 0.84), int(h * 0.84))
    return Traeger(aus, feld, PAL[zeichen])


def schriftrolle(w: int, h: int, zustand: str, saat: int = 4716) -> Traeger:
    grundfarbe, linie, _ = ROLLE[zustand]
    W, H = w * SS, h * SS
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    blatt = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(blatt)
    d.rectangle([2.0 * SS, 14.0 * SS, W - 2.0 * SS, H - 14.0 * SS], fill=255)
    walze = Image.new("L", (W, H), 0)
    dw = ImageDraw.Draw(walze)
    for y in (9.0, H / SS - 9.0):
        dw.rounded_rectangle([0.5 * SS, (y - 5.5) * SS, W - 0.5 * SS, (y + 5.5) * SS],
                             radius=5.5 * SS, fill=255)
    ganz = ImageChops.lighter(blatt, walze)
    im.alpha_composite(schatten(ganz, int(1.0 * SS), 1.8 * SS, 0.45))
    papier = senkrechter_verlauf((W, H), PAL[grundfarbe],
                                 mische(PAL[grundfarbe], PAL["messing_tief"], 0.30))
    im.alpha_composite(flaeche(blatt, korn_auflegen(papier, staerke=7, saat=saat)))
    walzenfarbe = senkrechter_verlauf((W, H), mische(PAL[grundfarbe], PAL["pergament"], 0.5),
                                      mische(PAL[grundfarbe], PAL["messing_tief"], 0.45))
    im.alpha_composite(flaeche(walze, korn_auflegen(walzenfarbe, staerke=6, saat=saat + 1)))
    im.alpha_composite(flaeche(walze, fase(walze, staerke=int(1.0 * SS), licht=0.38, schatten=0.34)))
    d2 = ImageDraw.Draw(im)
    for y in (17.0, H / SS - 17.0):
        d2.rectangle([3.0 * SS, y * SS, W - 3.0 * SS, (y + 0.9) * SS], fill=(*PAL[linie], 230))
    aus = verkleinern(im, w, h)
    feld = (int(w * 0.16), int(h * 0.24), int(w * 0.84), int(h * 0.76))
    return Traeger(aus, feld, PAL["zinnober_dunkel"])


def wappen_gross(w: int, h: int, zustand: str, saat: int = 4717) -> Traeger:
    """Der grosse Wappenschild - traegt das Kreuz selbst, kein eigenes Zeichen."""
    t = wappenschild(w, h, zustand, saat)
    W, H = w * SS, h * SS
    umriss = _schildmaske(W, H, w, h)
    innen = schrumpfen(umriss, 3.0 * SS)
    kreuz = Image.new("L", (W, H), 0)
    dk = ImageDraw.Draw(kreuz)
    breite = W * 0.20
    dk.rectangle([W / 2 - breite / 2, 0, W / 2 + breite / 2, H], fill=255)
    dk.rectangle([0, H * 0.34 - breite / 2, W, H * 0.34 + breite / 2], fill=255)
    kreuz = ImageChops.multiply(kreuz, innen)
    farbe = PAL["zinnober"] if zustand != "aus" else PAL["zinn"]
    lage = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    lage.alpha_composite(einfaerben(kreuz, farbe))
    lage.alpha_composite(flaeche(kreuz, fase(kreuz, staerke=int(0.6 * SS), licht=0.26, schatten=0.26)))
    bild = t.bild.copy()
    bild.alpha_composite(verkleinern(lage, w, h))
    return Traeger(bild, (0, 0, 0, 0), PAL["pergament"])


def leer(w: int, h: int) -> Traeger:
    """Kein Traeger - das Zeichen steht frei."""
    return Traeger(Image.new("RGBA", (w, h), (0, 0, 0, 0)), (0, 0, w, h), PAL["messing"])


def _sichtprobe() -> None:
    zeilen = [
        ("wappenschild", [wappenschild(60, 70, z) for z in ("ruhend", "ueberfahren", "gedrueckt", "aus")]),
        ("scheibe", [scheibe(48, 50)]),
        ("ring", [ring(129, 200, z, (3, 38, 126, 161)) for z in ("ruhend", "ueberfahren", "gedrueckt")]),
        ("ring_grund", [ring_grund(100, 100, z, f) for z, f in
                        (("ruhend", "nacht"), ("ueberfahren", "nacht"),
                         ("ruhend", "gruenspan"), ("ueberfahren", "gruenspan"))]),
        ("steinrahmen", [steinrahmen(113, 113, z) for z in ("ruhend", "ueberfahren")]),
        ("schriftrolle", [schriftrolle(100, 136, z) for z in ("ruhend", "ueberfahren")]),
        ("wappen_gross", [wappen_gross(100, 122, z) for z in ("ruhend", "ueberfahren")]),
    ]
    zelle, breit = 220, 0
    hoehe = len(zeilen) * (zelle + 22)
    breit = max(len(t) for _, t in zeilen) * zelle
    bogen = Image.new("RGB", (breit, hoehe), (46, 46, 52))
    d = ImageDraw.Draw(bogen)
    for zi, (name, traeger) in enumerate(zeilen):
        by = zi * (zelle + 22)
        for ti, t in enumerate(traeger):
            bx = ti * zelle
            for ax in range(bx, bx + zelle, 12):
                for ay in range(by, by + zelle, 12):
                    ton = (118, 118, 124) if ((ax - bx) // 12 + (ay - by) // 12) % 2 == 0 else (156, 156, 162)
                    d.rectangle([ax, ay, ax + 11, ay + 11], fill=ton)
            b = t.bild
            s = min((zelle - 16) / b.width, (zelle - 16) / b.height)
            b2 = b.resize((max(1, int(b.width * s)), max(1, int(b.height * s))), Image.NEAREST)
            bogen.paste(b2, (bx + (zelle - b2.width) // 2, by + (zelle - b2.height) // 2), b2)
        d.text((4, by + zelle + 4), name, fill=(240, 240, 240))
    OUT.mkdir(parents=True, exist_ok=True)
    ziel = OUT / "sichtprobe_traeger.png"
    bogen.save(ziel)
    print(f"{ziel}  {bogen.size[0]}x{bogen.size[1]}")


if __name__ == "__main__":
    _sichtprobe()

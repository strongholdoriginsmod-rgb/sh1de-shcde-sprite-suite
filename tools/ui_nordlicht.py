"""Nordlicht - Palette und Zeichenprimitive fuer die europaeischen Knopfgrafiken.

Die Palette stammt aus `docs/UI_NEUDESIGN.md` §3.1 und wird hier nicht neu
erfunden; sie steht dort als Ersatz fuer `Theme.Brushes.DarkRed.xaml`, damit
Menue und Spieloberflaeche dieselben elf Farbwerte fuehren.

Gezeichnet wird durchweg vierfach ueberabgetastet und erst zum Schluss auf die
Zielgroesse verkleinert. Bei Kantenlaengen von 48 bis 129 Pixeln ist das der
Unterschied zwischen einer Treppe und einer Rundung; ohne Ueberabtastung sieht
ein 60x70 grosser Wappenschild an der unteren Spitze ausgefranst aus.
"""
from __future__ import annotations

import math
from typing import Iterable, Sequence

from PIL import Image, ImageChops, ImageDraw, ImageFilter

SS = 4  # Ueberabtastung

PAL = {
    "schiefer":         (0x24, 0x30, 0x29),
    "schiefer_hell":    (0x35, 0x47, 0x3D),
    "pergament":        (0xE8, 0xDF, 0xC8),
    "messing":          (0xC9, 0xA2, 0x27),
    "gruenspan":        (0x5E, 0x8C, 0x7B),
    "zinnober":         (0xB3, 0x3A, 0x24),
    "zinnober_hell":    (0xD9, 0x83, 0x6A),
    "zinnober_mittel":  (0xC0, 0x51, 0x2F),
    "zinnober_dunkel":  (0x8E, 0x3B, 0x27),
    "zinnober_tief":    (0x6E, 0x34, 0x23),
}

# Abgeleitete Toene. Messing hell/dunkel tragen den Verlauf im Metall, Zinn
# traegt den abgeschalteten Zustand.
PAL["messing_hell"] = (0xE6, 0xC8, 0x62)
PAL["messing_tief"] = (0x8A, 0x6D, 0x18)
PAL["zinn"] = (0x8C, 0x90, 0x8A)
PAL["zinn_hell"] = (0xB4, 0xB8, 0xB1)
PAL["zinn_tief"] = (0x5C, 0x60, 0x5C)
PAL["nacht"] = (0x14, 0x1B, 0x18)


def mische(a: Sequence[int], b: Sequence[int], t: float) -> tuple[int, int, int]:
    """Lineare Mischung zweier Farben, t=0 gibt a, t=1 gibt b."""
    t = max(0.0, min(1.0, t))
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def leinwand(w: int, h: int) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    """Ueberabgetastete, leere Leinwand plus Zeichenstift."""
    im = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
    return im, ImageDraw.Draw(im)


def verkleinern(im: Image.Image, w: int, h: int) -> Image.Image:
    return im.resize((w, h), Image.LANCZOS)


def senkrechter_verlauf(groesse: tuple[int, int], oben, unten) -> Image.Image:
    """Volle Flaeche mit senkrechtem Farbverlauf, undurchsichtig."""
    w, h = groesse
    streifen = Image.new("RGB", (1, h))
    px = streifen.load()
    for y in range(h):
        px[0, y] = mische(oben, unten, y / max(1, h - 1))
    return streifen.resize((w, h), Image.BILINEAR).convert("RGBA")


def radialer_verlauf(groesse: tuple[int, int], innen, aussen, mitte=None) -> Image.Image:
    """Volle Flaeche mit radialem Verlauf. Traegt die Woelbung der Scheiben."""
    w, h = groesse
    cx, cy = mitte or (w / 2, h / 2)
    rmax = math.hypot(max(cx, w - cx), max(cy, h - cy)) or 1.0
    im = Image.new("RGBA", (w, h))
    px = im.load()
    for y in range(h):
        for x in range(w):
            t = math.hypot(x - cx, y - cy) / rmax
            r, g, b = mische(innen, aussen, t)
            px[x, y] = (r, g, b, 255)
    return im


def einfaerben(maske: Image.Image, farbe) -> Image.Image:
    """Maske (L) als undurchsichtige Flaeche einer Farbe."""
    im = Image.new("RGBA", maske.size, (*farbe, 0))
    im.putalpha(maske)
    return im


def flaeche(maske: Image.Image, fuellung: Image.Image) -> Image.Image:
    """Fuellung auf die Maske beschneiden."""
    im = fuellung.convert("RGBA").copy()
    alt = im.getchannel("A")
    im.putalpha(ImageChops.multiply(alt, maske))
    return im


def fase(maske: Image.Image, staerke: int = 2, licht: float = 0.55, schatten: float = 0.45) -> Image.Image:
    """Fase aus der Maske: helle Kante oben links, dunkle unten rechts.

    Kein Bump-Mapping, sondern die Differenz der Maske zu zwei verschobenen
    Kopien. Das genuegt fuer flache Zeichen und kostet nichts.
    """
    w, h = maske.size
    hoch = ImageChops.subtract(maske, ImageChops.offset(maske, staerke, staerke))
    tief = ImageChops.subtract(maske, ImageChops.offset(maske, -staerke, -staerke))
    hoch = hoch.filter(ImageFilter.GaussianBlur(staerke * 0.6))
    tief = tief.filter(ImageFilter.GaussianBlur(staerke * 0.6))
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    im.paste(Image.new("RGBA", (w, h), (255, 255, 255, 255)),
             (0, 0), hoch.point(lambda p: int(p * licht)))
    im.paste(Image.new("RGBA", (w, h), (0, 0, 0, 255)),
             (0, 0), tief.point(lambda p: int(p * schatten)))
    return ImageChops.multiply(im, Image.new("RGBA", (w, h), (255, 255, 255, 255)))


def schatten(maske: Image.Image, versatz: int, weichheit: float, deckung: float = 0.5) -> Image.Image:
    s = ImageChops.offset(maske, versatz, versatz).filter(ImageFilter.GaussianBlur(weichheit))
    return einfaerben(s.point(lambda p: int(p * deckung)), (0, 0, 0))


def wappenschild_pfad(w: int, h: int, rand: float = 0.0, schulteranteil: float = 0.52,
                      zug: float = 0.62) -> list[tuple[float, float]]:
    """Umriss eines Heater Shield: gerade Schulter, gerade Flanken, Spitze unten.

    Die Flanke ist eine quadratische Bezierkurve von der Schulterhoehe zur
    Spitze; ein reines Polygon knickt sichtbar, ein Halbkreis wird zu bauchig.
    `zug` bestimmt, wie lange die Flanke senkrecht bleibt: klein rundet frueh
    zu einem U aus, gross laesst die Kurve erst kurz vor der Spitze einbiegen.
    Am Bestand (`UI-Buttons A001`) abgeglichen.
    """
    x0, y0, x1, y1 = rand, rand, w - rand, h - rand
    schulter = y0 + (y1 - y0) * schulteranteil
    spitze = ((x0 + x1) / 2, y1)
    stuetze = schulter + (y1 - schulter) * zug

    def flanke(xs: float) -> list[tuple[float, float]]:
        aus = []
        for i in range(1, 33):
            t = i / 32
            px = (1 - t) ** 2 * xs + 2 * (1 - t) * t * xs + t ** 2 * spitze[0]
            py = (1 - t) ** 2 * schulter + 2 * (1 - t) * t * stuetze + t ** 2 * spitze[1]
            aus.append((px, py))
        return aus

    punkte: list[tuple[float, float]] = [(x0, y0), (x1, y0), (x1, schulter)]
    punkte.extend(flanke(x1))
    punkte.extend(reversed(flanke(x0)))
    punkte.append((x0, schulter))
    return punkte


def maske_aus_polygon(groesse: tuple[int, int], punkte: Iterable[tuple[float, float]]) -> Image.Image:
    m = Image.new("L", groesse, 0)
    ImageDraw.Draw(m).polygon(list(punkte), fill=255)
    return m


def maske_aus_kreis(groesse: tuple[int, int], mitte, radius: float) -> Image.Image:
    m = Image.new("L", groesse, 0)
    cx, cy = mitte
    ImageDraw.Draw(m).ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=255)
    return m


def rand(maske: Image.Image, staerke: float) -> Image.Image:
    """Randband einer Maske: Maske minus einwaerts geschrumpfte Maske."""
    innen = maske.filter(ImageFilter.MinFilter(_ungerade(staerke)))
    return ImageChops.subtract(maske, innen)


def schrumpfen(maske: Image.Image, staerke: float) -> Image.Image:
    return maske.filter(ImageFilter.MinFilter(_ungerade(staerke)))


def _ungerade(v: float) -> int:
    k = max(3, int(round(v)) * 2 + 1)
    return k if k % 2 else k + 1


def korn(groesse: tuple[int, int], staerke: int = 6, saat: int = 4711) -> Image.Image:
    """Feines, wiederholungsfreies Korn als Graustufenbild um 128 herum.

    Eigener linearer Kongruenzgenerator statt `random`, damit dieselbe Saat in
    jeder Sitzung dasselbe Korn ergibt und ein Neubau byte-gleich bleibt.
    """
    w, h = groesse
    zustand = saat & 0xFFFFFFFF
    werte = bytearray(w * h)
    for i in range(w * h):
        zustand = (1103515245 * zustand + 12345) & 0x7FFFFFFF
        werte[i] = 128 + ((zustand >> 16) % (2 * staerke + 1)) - staerke
    im = Image.frombytes("L", (w, h), bytes(werte))
    return im.filter(ImageFilter.GaussianBlur(0.5))


def korn_auflegen(bild: Image.Image, staerke: int = 6, saat: int = 4711) -> Image.Image:
    k = korn(bild.size, staerke, saat).convert("RGB")
    grund = bild.convert("RGBA")
    gemischt = ImageChops.overlay(grund.convert("RGB"), k)
    aus = gemischt.convert("RGBA")
    aus.putalpha(grund.getchannel("A"))
    return aus

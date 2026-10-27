"""Die orientalischen Motive der S-Reihe ersetzen - und sonst nichts.

Gepruefte Bestandsaufnahme der 101 Ausschnitte: nicht europaeisch sind genau
**vierzehn**, in fuenf Motiven.

| Ausschnitte | ist | soll |
|---|---|---|
| `S035/S036` | Rundschild mit Buckel, sarazenisch | europaeischer Rundschild |
| `S055..S057` | Kreuzritter im weissen Waffenrock mit rotem Kreuz | Ritter |
| `S058..S060` | arabischer Krieger, barbeinig | Speertraeger |
| `S079..S081` | arabischer Arbeiter, barfuss | Bauer |
| `S091..S093` | arabischer Traeger mit Schild | Waffenknecht |

Alles uebrige - Vorraete, Waffen, Ruestung, Feuer, Mauerbau, Handel, Krone,
Schaedel, Panzerhandschuh, Schriftrolle, das St.-Georgs-Kreuz auf `S033/S034` -
ist bereits europaeisch und wird **nicht angefasst**.

**Der Traeger bleibt der Originalknopf.** Ersetzt wird nur die Flaeche, auf der
die alte Figur sass; sie wird aus dem geernteten Ring aufgefuellt und die neue
Figur an dieselbe Stelle in derselben Groesse gesetzt. So bleiben Ring, Feld,
Randlicht und Alphakante des Bestands unangetastet, und der neue Knopf sitzt in
der Reihe seiner Nachbarn, als haette er immer dazugehoert.

Aufruf:  python tools/ui_button_bauen_s.py
Ablage:  work/ui-europa-buttons/fertig/UI-Buttons S0xx.png
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[1]
CRU = ROOT / "work" / "ui" / "UI-MasterAtlas"
ARBEIT = ROOT / "work" / "ui-europa-buttons"
GEMALT = ARBEIT / "gemalt"
TRAEGER = ARBEIT / "traeger"
FERTIG = ARBEIT / "fertig"

RING_ZUSTAENDE = ["ruhend", "ueberfahren", "gedrueckt"]

# (erster Ausschnitt, gemalte Gestalt, Zustaende)
RINGE = [
    ("S055", "ritter",       RING_ZUSTAENDE),
    ("S058", "speertraeger", RING_ZUSTAENDE),
    ("S079", "bauer",        RING_ZUSTAENDE),
    ("S091", "waffenknecht", RING_ZUSTAENDE),
]

SCHATTEN_VERSATZ = 2
SCHATTEN_WEICHE = 1.2
SCHATTEN_DECKUNG = 0.40
HELLIGKEIT_ANGLEICH = 0.7  # 0 = gar nicht, 1 = ganz auf den Bestand ziehen


def _lade(pfad: Path) -> np.ndarray:
    return np.asarray(Image.open(pfad).convert("RGBA"), dtype=np.float32)


# Ringgeometrie, am Bestand gemessen: Inhalt (3, 38) bis (126, 161) im
# 129x200-Blatt, also Mitte (64.5, 99.5) und Aussenradius 61.5. Das Innenfeld
# reicht bis 80 % davon, dahinter beginnt der Metallreif.
RING_MITTE = (64.5, 99.5)
RING_AUSSEN = 61.5
FELD_ANTEIL = 0.80


def innenfeld(form: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
    h, w = form
    ys, xs = np.mgrid[0:h, 0:w]
    r = np.hypot(xs - RING_MITTE[0], ys - RING_MITTE[1])
    return r <= RING_AUSSEN * FELD_ANTEIL, r


def leerer_knopf(original: np.ndarray) -> np.ndarray:
    """Den Knopf ohne Figur rekonstruieren - je Radius der Median ueber alle Winkel.

    Der ganze Knopf ist kreissymmetrisch: Innenfeld, Metallreif, Randlicht und
    Alphakante haengen nur vom Radius ab. Die Figur haengt es nicht. Der Median
    ueber alle Winkel eines Radius trifft deshalb den Knopf und wirft die Figur
    weg - **auch ausserhalb des Innenfelds**, wo im ersten Anlauf Speerschaft
    und Fahnenzipfel stehen geblieben waren, und **auch im Alphakanal**, wo die
    alte Speerspitze sonst als Loch im Nichts haengen bliebe.
    """
    h, w = original.shape[:2]
    ys, xs = np.mgrid[0:h, 0:w]
    r = np.hypot(xs - RING_MITTE[0], ys - RING_MITTE[1])
    stufe = np.rint(r).astype(np.int32)
    aus = np.zeros_like(original)
    grenze = int(np.ceil(r.max()))
    for k in range(grenze + 1):
        wo = stufe == k
        if wo.sum() < 6:
            continue
        aus[wo] = np.median(original[wo], axis=0)
    return aus


def alte_figur(original: np.ndarray, schwelle: float = 30.0) -> np.ndarray:
    """Wo sitzt die Figur? Ueber die Kreissymmetrie des Innenfelds.

    Der erste Ansatz verglich mit dem geernteten Ring. Das war falsch, weil
    dessen Innenfeld verfaerbt war: der Abstand wurde ueberall gross, die
    Maske verschlang den Metallreif, und das Stopfen loeschte ihn. Der Reif
    wird jetzt gar nicht erst betrachtet.

    Das Innenfeld ist ein kreissymmetrischer Verlauf, die Figur ist es nicht.
    Also wird je Radius der Median ueber alle Winkel gebildet - eine Figur
    verdeckt an einem Radius nie mehr als einen Teil des Kreises - und was
    davon abweicht, ist die Figur.
    """
    h, w = original.shape[:2]
    feld, r = innenfeld((h, w))
    stufe = np.rint(r).astype(np.int32)
    vorlage = np.zeros_like(original[..., :3])
    for k in range(int(RING_AUSSEN * FELD_ANTEIL) + 1):
        wo = feld & (stufe == k)
        if wo.sum() < 6:
            continue
        vorlage[wo] = np.median(original[..., :3][wo], axis=0)
    maske = feld & (np.abs(original[..., :3] - vorlage).max(axis=-1) > schwelle)
    maske = ndimage.binary_closing(maske, np.ones((5, 5), bool))
    maske = ndimage.binary_opening(maske, np.ones((3, 3), bool))
    marken, n = ndimage.label(maske, np.ones((3, 3), bool))
    if n:
        groessen = np.bincount(marken.ravel())
        groessen[0] = 0
        gross = np.nonzero(groessen >= max(30, 0.12 * groessen.max()))[0]
        maske = np.isin(marken, gross)
    return maske


def figurmaske(original: np.ndarray, leer: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Die alte Figur in zwei Teilen: im Innenfeld und ausserhalb davon.

    Der Unterschied ist noetig, weil auch der **Metallreif** vom Radialmedian
    abweicht - er traegt ein gerichtetes Licht, hell oben, dunkel unten. Wer
    einfach jede Abweichung ersetzt, buegelt dieses Licht mit weg; genau das
    ist im ersten Anlauf passiert, der Knopf wurde matt und flach.

    Im Innenfeld ist jede nennenswerte Abweichung die Figur. Ausserhalb wird
    nur genommen, was **stark** abweicht und ueber eine geodaetische Weitung
    mit der Figur im Feld **zusammenhaengt** - das trifft Speerschaft und
    Fahnenzipfel und laesst den Reif in Ruhe.
    """
    feld, _ = innenfeld(original.shape[:2])
    abweichung = np.abs(original - leer).max(axis=-1)

    innen = feld & (abweichung > 30)
    innen = ndimage.binary_closing(innen, np.ones((5, 5), bool))
    innen = ndimage.binary_opening(innen, np.ones((3, 3), bool))
    marken, n = ndimage.label(innen, np.ones((3, 3), bool))
    if n:
        groessen = np.bincount(marken.ravel())
        groessen[0] = 0
        innen = np.isin(marken, np.nonzero(groessen >= max(25, 0.10 * groessen.max()))[0])

    # Was ueber den runden Knopf hinausragt, ist zweifelsfrei Figur: der
    # rekonstruierte leere Knopf ist dort durchsichtig. Das trifft Speerschaft
    # und Fahnenzipfel ohne jede Schwelle.
    ueberstand = (leer[..., 3] < 32) & (original[..., 3] > 32)

    kandidat = (~feld) & ((abweichung > 38) | ueberstand)
    front = (innen | ueberstand).copy()
    for _ in range(10):
        gewachsen = ndimage.binary_dilation(front, np.ones((3, 3), bool)) & (kandidat | innen | ueberstand)
        if (gewachsen == front).all():
            break
        front = gewachsen
    aussen = (front | ueberstand) & ~innen
    return innen, aussen


def grund_leeren_ganz(original: np.ndarray, leer: np.ndarray,
                      innen: np.ndarray, aussen: np.ndarray) -> np.ndarray:
    """Innen aus dem Knopf selbst stopfen, aussen aus dem Radialmedian."""
    aus = grund_leeren(original, innen)
    if aussen.any():
        weich = ndimage.gaussian_filter(aussen.astype(np.float32), 1.0)[..., None]
        aus = aus * (1 - weich) + leer * weich
    return aus


def grund_leeren(original: np.ndarray, alt: np.ndarray) -> np.ndarray:
    """Die alte Figur aus dem Knopf herausstopfen - aus dem Knopf selbst.

    Der erste Versuch fuellte die Flaeche aus dem gemittelten Ring. Das ging
    schief: die Motive der siebzehn Ringknoepfe sind gross und warm, so dass
    der Median im Zentrum ins Braeunliche zieht - das neue Innenfeld war
    sichtbar rostfarben statt silbrig. Der Knopf selbst kennt seine
    Feldfarbe dagegen genau; gestopft wird deshalb aus dem naechstgelegenen
    freien Pixel desselben Bildes und anschliessend geglaettet, damit keine
    Naht bleibt.
    """
    feld, _ = innenfeld(original.shape[:2])
    weit = ndimage.binary_dilation(alt, iterations=3) & feld
    frei = feld & ~weit
    if frei.sum() < 50:
        return original.copy()
    _, index = ndimage.distance_transform_edt(~frei, return_indices=True)
    gestopft = original[index[0], index[1]]
    aus = original.copy()
    farbe = np.where(weit[..., None], gestopft[..., :3], original[..., :3])
    weich = np.stack([ndimage.gaussian_filter(farbe[..., k], 2.0) for k in range(3)], axis=-1)
    uebergang = np.clip(ndimage.gaussian_filter(weit.astype(np.float32), 2.2) * 1.5, 0, 1)[..., None]
    aus[..., :3] = farbe * (1 - uebergang) + weich * uebergang
    return aus


def helligkeit_angleichen(neu: np.ndarray, deckung: np.ndarray,
                          alt_bild: np.ndarray, alt: np.ndarray) -> np.ndarray:
    """Die neue Gestalt auf Helligkeit und Kontrast der alten ziehen.

    Der Bildgenerator malt heller und flauer als der Bestand. Ohne Angleich
    fiele der neue Knopf zwischen seinen Nachbarn auf. Angeglichen wird nur die
    Helligkeit, nicht der Farbton - sonst faerbt sich die Gestalt in Richtung
    des Waffenrocks, den sie ersetzt.
    """
    fest = deckung > 0.6
    if fest.sum() < 40 or alt.sum() < 40:
        return neu
    lum_neu = neu[..., :3].mean(axis=-1)
    ist_m, ist_s = lum_neu[fest].mean(), max(lum_neu[fest].std(), 1e-3)
    alt_lum = alt_bild[..., :3].mean(axis=-1)
    soll_m, soll_s = alt_lum[alt].mean(), max(alt_lum[alt].std(), 1e-3)
    m = soll_m * HELLIGKEIT_ANGLEICH + ist_m * (1 - HELLIGKEIT_ANGLEICH)
    s = soll_s * HELLIGKEIT_ANGLEICH + ist_s * (1 - HELLIGKEIT_ANGLEICH)
    ziel = m + (lum_neu - ist_m) * (s / ist_s)
    faktor = np.where(lum_neu > 1e-3, ziel / np.maximum(lum_neu, 1e-3), 1.0)[..., None]
    return np.clip(neu[..., :3] * faktor, 0, 255)


def einsetzen(original: np.ndarray, gestalt: Image.Image,
              hoehenanteil: float = 1.0) -> Image.Image:
    h, w = original.shape[:2]
    leer = leerer_knopf(original)
    alt_innen, alt_aussen = figurmaske(original, leer)
    alt = alt_innen | alt_aussen
    if not alt.any():
        raise SystemExit("alte Figur nicht gefunden")

    # Die neue Gestalt bekommt einen festen Platz im Innenfeld statt des
    # Kastens der alten. Der alte Kasten taugt nicht als Mass: bei S058 reichte
    # er wegen des Speers weit ueber den Knopf hinaus, die neue Gestalt waere
    # daran winzig geworden.
    r_feld = RING_AUSSEN * FELD_ANTEIL
    kw, kh = int(2 * r_feld * 0.80), int(2 * r_feld * 0.94 * hoehenanteil)
    kx0 = int(RING_MITTE[0] - kw / 2)
    ky1 = int(RING_MITTE[1] + r_feld * 0.94)
    kx1 = kx0 + kw

    s = min(kw / gestalt.width, kh / gestalt.height)
    neu = gestalt.resize((max(1, round(gestalt.width * s)), max(1, round(gestalt.height * s))),
                         Image.LANCZOS)
    lage = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ox = kx0 + (kx1 - kx0 - neu.width) // 2
    oy = ky1 - neu.height          # auf der Standlinie der alten Figur absetzen
    lage.paste(neu, (ox, oy))
    lage_a = np.asarray(lage, dtype=np.float32)
    deckung = lage_a[..., 3] / 255.0

    # Auf das Innenfeld beschneiden. Ohne das ragten Speerspitze und
    # Schildecke ueber den Ring hinaus in die Durchsichtigkeit - im Spiel
    # haetten sie frei im Nichts gehangen.
    feld, _ = innenfeld((h, w))
    deckung *= feld
    farbe = helligkeit_angleichen(lage_a, deckung, original, alt_innen)

    aus = grund_leeren_ganz(original, leer, alt_innen, alt_aussen)
    schatten = ndimage.gaussian_filter(
        np.roll(np.roll(deckung, SCHATTEN_VERSATZ, axis=0), SCHATTEN_VERSATZ, axis=1),
        SCHATTEN_WEICHE) * SCHATTEN_DECKUNG
    schatten = np.clip(schatten - deckung, 0, 1) * (aus[..., 3] > 32)
    aus[..., :3] *= (1.0 - schatten[..., None])
    aus[..., :3] = aus[..., :3] * (1 - deckung[..., None]) + farbe * deckung[..., None]
    aus[..., 3] = np.maximum(aus[..., 3], 0)
    return Image.fromarray(aus.clip(0, 255).round().astype(np.uint8), "RGBA")


def schild_ersetzen(name: str, gestalt: Image.Image) -> Image.Image:
    """`S035/S036`: der Knopf **ist** der Schild, es gibt keinen Traeger.

    Der neue Schild wird auf den Inhaltskasten des alten skaliert und traegt
    dessen Alphakante nicht - er bringt seine eigene mit, denn der Umriss
    aendert sich (Buckelschild bleibt rund, aber Rand und Nietenkranz sind
    andere). Angeglichen wird die Helligkeit: die beiden Fassungen des
    Bestands unterscheiden sich genau darin, und ohne Angleich waere der
    Unterschied zwischen ruhend und ueberfahren verschwunden.
    """
    original = _lade(CRU / name)
    h, w = original.shape[:2]
    fest = original[..., 3] > 40
    ys, xs = np.nonzero(fest)
    kx0, ky0 = int(xs.min()), int(ys.min())
    kw, kh = int(xs.max()) - kx0 + 1, int(ys.max()) - ky0 + 1

    s = min(kw / gestalt.width, kh / gestalt.height)
    neu = gestalt.resize((max(1, round(gestalt.width * s)), max(1, round(gestalt.height * s))),
                         Image.LANCZOS)
    lage = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    lage.paste(neu, (kx0 + (kw - neu.width) // 2, ky0 + (kh - neu.height) // 2))
    lage_a = np.asarray(lage, dtype=np.float32)
    deckung = lage_a[..., 3] / 255.0
    farbe = helligkeit_angleichen(lage_a, deckung, original, fest)
    aus = np.zeros_like(lage_a)
    aus[..., :3] = farbe
    aus[..., 3] = lage_a[..., 3]
    return Image.fromarray(aus.clip(0, 255).round().astype(np.uint8), "RGBA")


def main() -> int:
    FERTIG.mkdir(parents=True, exist_ok=True)
    bericht = []
    for erster, gestaltname, zustaende in RINGE:
        nr = int(erster[1:])
        pfad = GEMALT / f"{gestaltname}.png"
        if not pfad.exists():
            raise SystemExit(f"Gestalt fehlt: {pfad}")
        gestalt = Image.open(pfad).convert("RGBA")
        for i, zustand in enumerate(zustaende):
            name = f"UI-Buttons S{nr + i:03d}.png"
            original = _lade(CRU / name)
            bild = einsetzen(original, gestalt)
            soll = Image.open(CRU / name).size
            if bild.size != soll:
                raise SystemExit(f"{name}: {bild.size} statt {soll}")
            bild.save(FERTIG / name)
            bericht.append({"datei": name, "gestalt": gestaltname, "zustand": zustand})

    schild = Image.open(GEMALT / "rundschild.png").convert("RGBA")
    for name in ("UI-Buttons S035.png", "UI-Buttons S036.png"):
        bild = schild_ersetzen(name, schild)
        soll = Image.open(CRU / name).size
        if bild.size != soll:
            raise SystemExit(f"{name}: {bild.size} statt {soll}")
        bild.save(FERTIG / name)
        bericht.append({"datei": name, "gestalt": "rundschild",
                        "zustand": "ruhend" if name.endswith("S035.png") else "ueberfahren"})

    (ARBEIT / "bericht_s.json").write_text(json.dumps(bericht, indent=2, ensure_ascii=False),
                                           encoding="utf-8")
    print(f"neu gebaut: {len(bericht)} Ausschnitte")
    for b in bericht:
        print(f"  {b['datei']}  {b['gestalt']:14s} {b['zustand']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

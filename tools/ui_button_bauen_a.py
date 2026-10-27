"""Die beiden orientalischen Zeichen der A-Reihe ersetzen - und sonst nichts.

Gepruefte Bestandsaufnahme: von den 66 Ausschnitten der A-Reihe sind genau
**acht** nicht europaeisch, naemlich `A049..A052` (Krummsaebel) und
`A059..A062` (Krummdolch). Turm, Hammer, Apfel, Haus, Schild, Sichel, Torhaus,
Schwert, Schluessel, Auskunftszeichen, Abbruchzeichen, Rueckpfeil, Horn,
Mauerkrone und Blide sind bereits europaeische Motive und werden **nicht
angefasst**.

Ersetzt wird nur das Zeichen, nicht der Traeger: die Crusader-Platte bleibt in
allen vier Zustaenden erhalten (Holz, dunkelrot, rot, abgeschaltet), damit sich
die neuen Knoepfe nahtlos in die vorhandene Oberflaeche fuegen. Die
Goldschattierung stammt aus `ui_gold_lernen.py` und ist am Bestand gemessen,
nicht geschaetzt.

Aufruf:  python tools/ui_button_bauen_a.py
Ablage:  work/ui-europa-buttons/fertig/UI-Buttons A0xx.png
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

from ui_gold_lernen import SEKTOREN, TIEFE

ROOT = Path(__file__).resolve().parents[1]
CRU = ROOT / "work" / "ui" / "UI-MasterAtlas"
SH1 = ROOT / "work" / "ui-sh1-dict" / "UI-MasterAtlas"
ARBEIT = ROOT / "work" / "ui-europa-buttons"
FERTIG = ARBEIT / "fertig"

# Neue Motive: Schluessel des ersten Ausschnitts -> (Zeichen, Zustaende)
NEU = [
    ("A049", "ritterschwert", ["ruhend", "ueberfahren", "gedrueckt", "aus"]),
    ("A059", "dolch",         ["ruhend", "ueberfahren", "gedrueckt", "aus"]),
]

# Zeichenkasten, gemessen als Vereinigung aller Zeichen des Bestands ([5,4,54,59])
# und um drei Pixel eingerueckt, damit ein neues Zeichen nicht weiter an die
# Plattenkante stoesst als jedes vorhandene.
# Gemessen an den zwoelf Zeichen des Bestands: im Mittel 42x51 Pixel, also
# deutlich groesser als der erste Ansatz von 43x49 mit dreifacher Einrueckung.
KASTEN = (8, 6, 52, 58)

SCHATTEN_VERSATZ = 2
SCHATTEN_WEICHE = 1.0
SCHATTEN_DECKUNG = 0.45


def _maske_einpassen(pfad: Path, kasten: tuple[int, int, int, int],
                     blatt: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
    """Zeichen auf den Kasten skalieren, seitenverhaeltnistreu und mittig."""
    zeichen = Image.open(pfad).convert("RGBA")
    kx0, ky0, kx1, ky1 = kasten
    kw, kh = kx1 - kx0, ky1 - ky0
    s = min(kw / zeichen.width, kh / zeichen.height)
    neu = (max(1, round(zeichen.width * s)), max(1, round(zeichen.height * s)))
    zeichen = zeichen.resize(neu, Image.LANCZOS)
    w, h = blatt
    sil = Image.new("L", (w, h), 0)
    det = Image.new("L", (w, h), 0)
    ox = kx0 + (kw - neu[0]) // 2
    oy = ky0 + (kh - neu[1]) // 2
    sil.paste(zeichen.getchannel("A"), (ox, oy))
    det.paste(zeichen.getchannel("R"), (ox, oy))
    return np.asarray(sil, dtype=np.float32) / 255.0, np.asarray(det, dtype=np.float32) / 255.0


def tafel_spreizen(tafel: np.ndarray, gewinn: float = 1.7) -> np.ndarray:
    """Den Glanz zurueckholen, den das Mitteln weggenommen hat.

    Die Tafel entsteht als Mittelwert ueber zwoelf Motive. Der Mittelwert
    daempft genau das, was ein Relief lesbar macht: die helle Kante oben links
    und die dunkle unten rechts. Gemessen liegt die Spannweite ueber die
    Sektoren im Nachbau bei rund 60 % der Spannweite im Bestand. Deshalb wird
    die Abweichung vom Stufenmittel gespreizt - die mittlere Helligkeit jeder
    Stufe bleibt dabei unveraendert, nur ihr Kontrast waechst.
    """
    mittel = tafel.mean(axis=1, keepdims=True)
    return np.clip(mittel + (tafel - mittel) * gewinn, 0, 255)


def farbe_angleichen(farbe: np.ndarray, maske: np.ndarray, ziel: np.ndarray) -> np.ndarray:
    """Mittelwert und Streuung des Reliefs auf die gemessenen Werte ziehen.

    Der erste Nachbau lag bei Mittel [140, 123, 83] und Streuung [32, 34, 31],
    der Bestand bei [173, 159, 114] und [57, 65, 63] - also zu dunkel und mit
    halbem Kontrast. Beides ruehrt daher, dass die gelernte Tafel ein
    Mittelwert ueber zwoelf Motive ist und die Zeichen des Bestands dicker sind
    als die neuen, also mehr ruhige Innenflaeche haben. Statt an Beiwerten zu
    drehen, wird hier die Farbverteilung direkt auf die gemessene gezogen.
    """
    fest = maske > 0.5
    if fest.sum() < 20:
        return farbe
    ist_mittel = farbe[fest].mean(axis=0)
    ist_streuung = np.maximum(farbe[fest].std(axis=0), 1e-3)
    soll_mittel, soll_streuung = ziel
    return np.clip(soll_mittel + (farbe - ist_mittel) * (soll_streuung / ist_streuung), 0, 255)


def maske_verdicken(maske: np.ndarray, staerke: float = 1.0) -> np.ndarray:
    """Duenne Zeichen aufdicken, damit die Fase Platz hat.

    Gemessen: die Zeichen des Bestands belegen 394 bis 1373 Pixel bei
    aehnlichem Kasten, die erzeugten nur 247. Sie sind also strichiger. Eine
    Form, die nirgends breiter als vier Pixel ist, besteht ausschliesslich aus
    Fase und liest sich flach - es fehlt die ruhige Oberseite, die ein Relief
    ueberhaupt erst als erhaben zeigt. Ein Pixel Aufdickung genuegt, mehr
    verklebt die Innenzeichnung.
    """
    weich = ndimage.gaussian_filter(maske, staerke * 0.7)
    return np.clip(np.maximum(maske, weich * 1.8), 0, 1)


def _relief(maske: np.ndarray, tafel: np.ndarray) -> np.ndarray:
    fest = maske > 0.5
    d = ndimage.distance_transform_edt(fest)
    stufe = np.clip(np.rint(d), 0, TIEFE - 1).astype(np.int16)
    gy, gx = np.gradient(ndimage.gaussian_filter(d, 0.8))
    sektor = ((np.arctan2(gy, gx) + np.pi) / (2 * np.pi) * SEKTOREN).astype(np.int16) % SEKTOREN
    farbe = tafel[stufe, sektor]

    # Glanzkante: das Licht faellt von links oben. Die Tafel traegt die
    # Richtung bereits, aber gemittelt ueber zwoelf Motive - der schmale,
    # fast weisse Grat an der Oberkante ueberlebt das Mitteln nicht.
    kante = (d > 0) & (d <= 1.8)
    licht = np.clip(-(gx + gy) / np.maximum(np.hypot(gx, gy), 1e-6), 0, 1)
    grat = (kante * licht)[..., None] * 0.45
    return np.clip(farbe + (255.0 - farbe) * grat, 0, 255)


def grund_aus_original(original: np.ndarray, platte: np.ndarray) -> np.ndarray:
    """Originalknopf nehmen und nur die Flaeche des alten Zeichens ersetzen.

    Die geerntete Platte ist sauber, hat beim Stopfen aber ihre Holzmaserung
    eingebuesst. Gebraucht wird sie ohnehin nur dort, wo das alte Zeichen sass.
    Ueberall sonst ist der Originalknopf selbst die beste Vorlage - er bringt
    Maserung, Randabdunklung und Kantenlicht unveraendert mit.
    """
    abstand = np.abs(original[..., :3] - platte[..., :3]).max(axis=-1)
    alt = abstand > 24
    alt = ndimage.binary_closing(alt, np.ones((3, 3), bool))
    alt = ndimage.binary_dilation(alt, iterations=2)
    weich = ndimage.gaussian_filter(alt.astype(np.float32), 1.0)[..., None]
    aus = original.copy()
    aus[..., :3] = original[..., :3] * (1 - weich) + platte[..., :3] * weich
    return aus


def knopf_bauen(platte: np.ndarray, zeichenpfad: Path, tafel: np.ndarray,
                ziel: np.ndarray) -> Image.Image:
    h, w = platte.shape[:2]
    sil, det = _maske_einpassen(zeichenpfad, KASTEN, (w, h))
    sil = maske_verdicken(sil)
    farbe = farbe_angleichen(_relief(sil, tafel), sil, ziel)

    # Eingeschnittene Linien als Gravur: dunkler, nicht durchsichtig. Ein
    # 40 Pixel breites Zeichen mit durchsichtigen Fugen zerfaellt.
    farbe = farbe * (1.0 - 0.30 * det[..., None])

    aus = platte.copy()
    schatten = ndimage.gaussian_filter(
        np.roll(np.roll(sil, SCHATTEN_VERSATZ, axis=0), SCHATTEN_VERSATZ, axis=1),
        SCHATTEN_WEICHE) * SCHATTEN_DECKUNG
    schatten = np.clip(schatten - sil, 0, 1)
    aus[..., :3] *= (1.0 - schatten[..., None])
    aus[..., :3] = aus[..., :3] * (1 - sil[..., None]) + farbe * sil[..., None]
    aus[..., 3] = np.maximum(aus[..., 3], sil * 255)
    return Image.fromarray(aus.clip(0, 255).round().astype(np.uint8), "RGBA")


def main() -> int:
    FERTIG.mkdir(parents=True, exist_ok=True)
    tafeln = np.load(ARBEIT / "gold" / "tafel.npz")
    bericht = {"uebernommen": [], "neu": []}


    for erster, zeichen, zustaende in NEU:
        nr = int(erster[1:])
        pfad = ARBEIT / "zeichen" / f"{zeichen}.png"
        if not pfad.exists():
            raise SystemExit(f"Zeichen fehlt: {pfad}")
        for i, zustand in enumerate(zustaende):
            platte = np.asarray(
                Image.open(ARBEIT / "traeger" / f"wappenschild_crusader_{zustand}.png").convert("RGBA"),
                dtype=np.float32)
            name = f"UI-Buttons A{nr + i:03d}.png"
            original = np.asarray(Image.open(CRU / name).convert("RGBA"), dtype=np.float32)
            grund = grund_aus_original(original, platte)
            bild = knopf_bauen(grund, pfad, tafel_spreizen(tafeln[zustand]),
                               tafeln[f"ziel_{zustand}"])
            soll = Image.open(CRU / name).size
            if bild.size != soll:
                raise SystemExit(f"{name}: {bild.size} statt {soll}")
            bild.save(FERTIG / name)
            bericht["neu"].append({"datei": name, "zeichen": zeichen, "zustand": zustand})

    (ARBEIT / "bericht_a.json").write_text(json.dumps(bericht, indent=2, ensure_ascii=False),
                                           encoding="utf-8")
    print(f"neu gebaut: {len(bericht['neu'])} Ausschnitte, alles uebrige bleibt unberuehrt")
    for b in bericht["neu"]:
        print(f"  {b['datei']}  {b['zeichen']:14s} {b['zustand']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

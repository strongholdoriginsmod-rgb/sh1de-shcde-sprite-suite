"""Die Goldschattierung aus den echten Knoepfen lernen statt sie nachzuahmen.

Die Zeichen auf `UI-Buttons A001..A066` sind poliertes Goldrelief: eine flache
Oberseite, eine umlaufende Fase, Licht von links oben, darunter ein weicher
Schlagschatten. Dieses Aussehen laesst sich messen statt schaetzen.

**Wie gemessen wird.** Aus jedem echten Knopf wird das Zeichen freigestellt,
indem die geerntete leere Platte abgezogen wird. Fuer jeden Zeichenpixel werden
zwei Merkmale bestimmt:

- der **Abstand zur Zeichenkante** in Pixeln (Distanztransformation), gekappt
  bei sechs - so breit ist die Fase im Bestand;
- die **Richtung**, in die der Abstand waechst, in zwoelf Sektoren.

Der Mittelwert der Farbe je Merkmalspaar ergibt eine Nachschlagetafel. Sie
enthaelt genau das, was das Auge als Relief liest: aussen an der oberen linken
Kante hell, aussen rechts unten dunkel, innen der ruhige Grundton.

Die Tafel wird an einem Zeichen geprueft, das nicht ins Lernen eingeht - der
Fehler steht im Bericht.

Ablage: work/ui-europa-buttons/gold/tafel.npz + probe.png
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[1]
CRU = ROOT / "work" / "ui" / "UI-MasterAtlas"
SH1 = ROOT / "work" / "ui-sh1-dict" / "UI-MasterAtlas"
TRAEGER = ROOT / "work" / "ui-europa-buttons" / "traeger"
OUT = ROOT / "work" / "ui-europa-buttons" / "gold"

# Je Zustand eine eigene Tafel: das Gold nimmt die Farbe der Platte auf, und
# der abgeschaltete Zustand ist nicht bloss blasser, sondern entsaettigt.
# A029/A030/A031/A032 (Schwert) bleiben als Probe draussen.
LERNEN = {
    "ruhend":      ["A001", "A005", "A009", "A013", "A017", "A021", "A025",
                    "A049", "A053", "A056", "A059", "A063"],
    "ueberfahren": ["A002", "A006", "A010", "A014", "A018", "A022", "A026",
                    "A050", "A054", "A057", "A060", "A064"],
    "gedrueckt":   ["A003", "A007", "A011", "A015", "A019", "A023", "A027",
                    "A051", "A055", "A058", "A061", "A065"],
    "aus":         ["A004", "A008", "A012", "A016", "A020", "A024", "A028",
                    "A052", "A062", "A066"],
}
PROBE = {"ruhend": "A029", "ueberfahren": "A030", "gedrueckt": "A031", "aus": "A032"}

TIEFE = 7      # Abstandsstufen 0..6, darueber gilt "innen"
SEKTOREN = 12


def _quelle(schluessel: str) -> Path:
    """Immer Crusader.

    Gelernt wird gegen die **Crusader**-Platte, weil die neuen Zeichen dort
    eingesetzt werden. Stronghold 1 fuehrt dieselben Knoepfe mit gruenem statt
    rotem Zustandsgrund; die Tafel aus SH1 auf eine Crusader-Platte zu legen
    haette dem Gold einen gruenen Stich gegeben.
    """
    return CRU / f"UI-Buttons {schluessel}.png"


def zeichen_freistellen(schluessel: str, platte: np.ndarray,
                        schwelle: float = 30.0) -> tuple[np.ndarray, np.ndarray]:
    """Zeichenmaske und Farbe aus einem echten Knopf herausloesen."""
    knopf = np.asarray(Image.open(_quelle(schluessel)).convert("RGBA"), dtype=np.float32)
    abstand = np.abs(knopf[..., :3] - platte[..., :3]).max(axis=-1)
    maske = (abstand > schwelle) & (knopf[..., 3] > 128)
    maske = ndimage.binary_closing(maske, np.ones((3, 3), bool))
    maske = ndimage.binary_opening(maske, np.ones((2, 2), bool))
    # Der Schlagschatten liegt unter dem Zeichen und ist dunkler als die Platte.
    heller = knopf[..., :3].mean(axis=-1) > platte[..., :3].mean(axis=-1)
    return maske & heller, knopf


def merkmale(maske: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Abstand zur Kante (gekappt) und Richtungssektor des Abstandsgefaelles."""
    d = ndimage.distance_transform_edt(maske)
    stufe = np.clip(np.rint(d), 0, TIEFE - 1).astype(np.int16)
    gy, gx = np.gradient(ndimage.gaussian_filter(d, 0.8))
    winkel = np.arctan2(gy, gx)
    sektor = ((winkel + np.pi) / (2 * np.pi) * SEKTOREN).astype(np.int16) % SEKTOREN
    return stufe, sektor


def tafel_lernen(schluessel: list[str], platte: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    summe = np.zeros((TIEFE, SEKTOREN, 3), dtype=np.float64)
    zahl = np.zeros((TIEFE, SEKTOREN), dtype=np.int64)
    for k in schluessel:
        maske, knopf = zeichen_freistellen(k, platte)
        if maske.sum() < 60:
            continue
        stufe, sektor = merkmale(maske)
        np.add.at(summe, (stufe[maske], sektor[maske]), knopf[..., :3][maske])
        np.add.at(zahl, (stufe[maske], sektor[maske]), 1)
    return summe, zahl


def tafel_schliessen(summe: np.ndarray, zahl: np.ndarray) -> np.ndarray:
    """Leere Faecher aus dem Nachbarn derselben Stufe fuellen."""
    tafel = np.zeros_like(summe)
    besetzt = zahl > 0
    tafel[besetzt] = summe[besetzt] / zahl[besetzt][..., None]
    for t in range(TIEFE):
        if not besetzt[t].any():
            quelle = max((s for s in range(TIEFE) if besetzt[s].any()),
                         key=lambda s: -abs(s - t))
            tafel[t] = tafel[quelle]
            continue
        for s in range(SEKTOREN):
            if besetzt[t, s]:
                continue
            nah = [x for x in range(SEKTOREN) if besetzt[t, x]]
            naechster = min(nah, key=lambda x: min(abs(x - s), SEKTOREN - abs(x - s)))
            tafel[t, s] = tafel[t, naechster]
    # Die innerste Stufe soll ruhig sein: ueber die Sektoren mitteln.
    tafel[TIEFE - 1] = tafel[TIEFE - 1].mean(axis=0)
    return tafel


def einfaerben(maske: np.ndarray, tafel: np.ndarray) -> np.ndarray:
    stufe, sektor = merkmale(maske)
    return tafel[stufe, sektor]


def _emblemkasten(schluessel: list[str], platte: np.ndarray) -> list[int]:
    """Wo sitzen die Zeichen im Bestand? Vereinigung aller Zeichenkaesten."""
    x0 = y0 = 10 ** 6
    x1 = y1 = -1
    for k in schluessel:
        maske, _ = zeichen_freistellen(k, platte)
        if maske.sum() < 60:
            continue
        ys, xs = np.nonzero(maske)
        x0, y0 = min(x0, int(xs.min())), min(y0, int(ys.min()))
        x1, y1 = max(x1, int(xs.max()) + 1), max(y1, int(ys.max()) + 1)
    return [x0, y0, x1, y1]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    tafeln, bericht = {}, {"zustaende": {}}
    hoehe = breite = 0
    for zustand, schluessel in LERNEN.items():
        platte = np.asarray(
            Image.open(TRAEGER / f"wappenschild_crusader_{zustand}.png").convert("RGBA"),
            dtype=np.float32)
        hoehe, breite = platte.shape[:2]
        summe, zahl = tafel_lernen(schluessel, platte)
        tafel = tafel_schliessen(summe, zahl)
        tafeln[zustand] = tafel

        probe = PROBE[zustand]
        maske, echt = zeichen_freistellen(probe, platte)
        gemalt = einfaerben(maske, tafel)
        fehler = float(np.abs(gemalt[maske] - echt[..., :3][maske]).mean())
        spanne = float(echt[..., :3][maske].std())

        h, w = maske.shape
        vergleich = Image.new("RGBA", (w * 3, h), (0, 0, 0, 0))
        vergleich.paste(Image.open(_quelle(probe)).convert("RGBA"), (0, 0))
        nachbau = platte.copy()
        nachbau[..., :3] = np.where(maske[..., None], gemalt, platte[..., :3])
        vergleich.paste(Image.fromarray(nachbau.clip(0, 255).astype(np.uint8), "RGBA"), (w, 0))
        nur = np.zeros((h, w, 4), dtype=np.float32)
        nur[..., :3] = gemalt
        nur[..., 3] = maske * 255
        vergleich.paste(Image.fromarray(nur.clip(0, 255).astype(np.uint8), "RGBA"), (2 * w, 0))
        vergleich.resize((w * 12, h * 4), Image.NEAREST).save(OUT / f"probe_{zustand}.png")

        farben = []
        for k in schluessel:
            m, knopf = zeichen_freistellen(k, platte)
            if m.sum() >= 60:
                farben.append(knopf[..., :3][m])
        alle = np.concatenate(farben)
        tafeln[f"ziel_{zustand}"] = np.stack([alle.mean(axis=0), alle.std(axis=0)])

        kaesten = []
        for k in schluessel:
            m, _ = zeichen_freistellen(k, platte)
            if m.sum() < 60:
                continue
            ys, xs = np.nonzero(m)
            kaesten.append((int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)))

        bericht["zustaende"][zustand] = {
            "gold_mittel": [round(float(v), 1) for v in alle.mean(axis=0)],
            "gold_streuung": [round(float(v), 1) for v in alle.std(axis=0)],
            "zeichenkasten_mittel": [round(sum(k[0]) / len(kaesten), 1) if False else
                                     round(sum(a for a, _ in kaesten) / len(kaesten), 1),
                                     round(sum(b for _, b in kaesten) / len(kaesten), 1)],
            "gelernt_aus": schluessel, "probe": probe,
            "faecher_besetzt": int((zahl > 0).sum()),
            "stichproben": int(zahl.sum()),
            "mittlerer_fehler": round(fehler, 2),
            "streuung_im_zeichen": round(spanne, 2),
        }

    platte0 = np.asarray(Image.open(TRAEGER / "wappenschild_crusader_ruhend.png").convert("RGBA"),
                         dtype=np.float32)
    kasten = _emblemkasten(LERNEN["ruhend"], platte0)
    bericht["emblemkasten"] = kasten
    bericht["blattgroesse"] = [breite, hoehe]
    bericht["faecher_gesamt"] = TIEFE * SEKTOREN
    np.savez(OUT / "tafel.npz", kasten=np.array(kasten), **tafeln)
    (OUT / "bericht.json").write_text(json.dumps(bericht, indent=2, ensure_ascii=False),
                                      encoding="utf-8")
    print("Emblemkasten", bericht["emblemkasten"], "im Blatt", bericht["blattgroesse"])
    for z, b in bericht["zustaende"].items():
        print(f"  {z:12s} Faecher {b['faecher_besetzt']:>2}/{bericht['faecher_gesamt']}"
              f"  Proben {b['stichproben']:>5}  Fehler {b['mittlerer_fehler']:>6}"
              f"  Streuung {b['streuung_im_zeichen']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

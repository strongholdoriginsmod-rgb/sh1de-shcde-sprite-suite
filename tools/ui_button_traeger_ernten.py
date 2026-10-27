"""Die Traeger aus dem Spielbestand zurueckgewinnen statt sie zu erfinden.

Der Auftrag heisst Stronghold-1-Stil. Den gibt es nicht nachzubauen - er liegt
vor: `UI-Buttons A001..A048` fuehren beide Spiele unter demselben Schluessel und
in derselben Groesse, und ein Vergleich zeigt, dass sie **dasselbe Bild** sind.
Der einzige Unterschied ist die Zustandsfarbe: Stronghold 1 legt Gruen unter,
Crusader Rot. Fuer die europaeische Fassung ist also Stronghold 1 die Vorlage.

Nur: Jede Platte traegt bereits ein Zeichen. Um die **leere** Platte zu bekommen,
wird ueber alle Motive derselben Zustandsgruppe der Pixelmedian gebildet. Die
Zeichen sitzen an verschiedenen Stellen, die Platte ist ueberall gleich - der
Median behaelt die Platte und wirft die Zeichen weg. Acht Motive genuegen.

Fuer die Ringknoepfe der S-Reihe geht das nicht so einfach: dort sitzen alle
Motive in der Mitte, ein reiner Median bliebe im Zentrum verunreinigt. Das
Innenfeld ist aber kreissymmetrisch, darum wird es als **Median ueber Radius**
gebildet - ueber alle Winkel und alle siebzehn Motive zugleich. Damit ist selbst
im Zentrum die Mehrheit der Stichprobe sauber.

Ablage: work/ui-europa-buttons/traeger/<name>.png
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[1]
CRU = ROOT / "work" / "ui" / "UI-MasterAtlas"
SH1 = ROOT / "work" / "ui-sh1-dict" / "UI-MasterAtlas"
OUT = ROOT / "work" / "ui-europa-buttons" / "traeger"

# Wappenschild: Motivanfaenge mit Platte, je Zustand um eins versetzt.
# Crusader fuehrt mehr Motive auf derselben Platte als Stronghold 1 (Saebel,
# Horn, Krone, Dolch, Blide kommen dazu). Fuer die Ernte zaehlt jede zusaetzliche
# Stichprobe, darum wird je Zustand ausdruecklich aufgezaehlt statt gerechnet -
# A053..A058 fuehren nur drei Zustaende und wuerden jede Rechnung verschieben.
SCHILD_SH1 = {
    "ruhend":      [1, 5, 9, 13, 17, 21, 25, 29],
    "ueberfahren": [2, 6, 10, 14, 18, 22, 26, 30],
    "gedrueckt":   [3, 7, 11, 15, 19, 23, 27, 31],
    "aus":         [4, 8, 12, 16, 20, 24, 28, 32],
}
SCHILD_CRU = {
    "ruhend":      [1, 5, 9, 13, 17, 21, 25, 29, 49, 53, 56, 59, 63],
    "ueberfahren": [2, 6, 10, 14, 18, 22, 26, 30, 50, 54, 57, 60, 64],
    "gedrueckt":   [3, 7, 11, 15, 19, 23, 27, 31, 51, 55, 58, 61, 65],
    "aus":         [4, 8, 12, 16, 20, 24, 28, 32, 52, 62, 66],
}
SCHILD_ZUSTAENDE = ["ruhend", "ueberfahren", "gedrueckt", "aus"]

# Ringknopf: erster Ausschnitt jeder Dreiergruppe.
RING_MOTIVE = [48, 51, 55, 58, 61, 64, 67, 70, 73, 76, 79, 82, 85, 88, 91, 94, 97]
RING_ZUSTAENDE = ["ruhend", "ueberfahren", "gedrueckt"]


def _stapel(pfade: list[Path]) -> np.ndarray:
    bilder = [np.asarray(Image.open(p).convert("RGBA"), dtype=np.float32) for p in pfade]
    formen = {b.shape for b in bilder}
    if len(formen) != 1:
        raise SystemExit(f"uneinheitliche Groessen: {formen}")
    return np.stack(bilder)


def median_platte(pfade: list[Path]) -> Image.Image:
    """Pixelmedian ueber mehrere Motive - loescht die Zeichen, behaelt die Platte."""
    return Image.fromarray(np.median(_stapel(pfade), axis=0).round().astype(np.uint8), "RGBA")


def _streuungsmaske(stapel: np.ndarray, schwelle: float = 26.0, weiten: int = 2) -> np.ndarray:
    """Wo die Motive stark auseinandergehen, sitzt ein Zeichen und keine Platte."""
    spanne = stapel[..., :3].max(axis=0) - stapel[..., :3].min(axis=0)
    maske = spanne.max(axis=-1) > schwelle
    for _ in range(weiten):
        geweitet = maske.copy()
        geweitet[1:, :] |= maske[:-1, :]
        geweitet[:-1, :] |= maske[1:, :]
        geweitet[:, 1:] |= maske[:, :-1]
        geweitet[:, :-1] |= maske[:, 1:]
        maske = geweitet
    return maske


def platte_stopfen(pfade: list[Path]) -> tuple[Image.Image, float]:
    """Median, danach die verunreinigte Flaeche aus der Nachbarschaft stopfen.

    Acht Motive reichen fuer einen sauberen Median nicht, wenn die Zeichen alle
    mittig sitzen und einander ueberlappen - dann ist die Mehrheit der
    Stichprobe an denselben Pixeln verdeckt und der Median behaelt einen
    Geisterrest.

    Gestopft wird nur die **Farbe**, nie das Alpha: Der Umriss der Platte steht
    im Median bereits richtig, und ein erster Versuch, ihn zeilenweise
    mitzurechnen, hat ihn nach links und rechts ausgefranst.

    Das Stopfen selbst nimmt fuer jeden verdorbenen Pixel den naechstgelegenen
    sauberen **innerhalb der Platte** und legt anschliessend eine leichte
    Weichzeichnung darueber, damit keine Nahtkante stehen bleibt. Fuer eine
    waagerecht gemaserte Holzflaeche mit Randabdunklung reicht das.
    """
    stapel = _stapel(pfade)
    median = np.median(stapel, axis=0)
    schmutz = _streuungsmaske(stapel, schwelle=34.0, weiten=1)
    alpha = median[..., 3]
    # Relative Schwelle: der abgeschaltete Zustand ist durchgehend
    # halbdurchsichtig, eine feste Schwelle von 200 haelt ihn faelschlich
    # fuer leer und bricht die Ernte ab.
    innen = alpha > 0.5 * alpha.max()
    sauber = innen & ~schmutz
    if not sauber.any():
        raise SystemExit("keine sauberen Pixel in der Platte")

    # Die Platte ist links-rechts symmetrisch. Wo eine Seite verdeckt ist, ist
    # es die andere meist nicht - das Spiegeln hebt den sauberen Anteil von
    # rund einem Achtel auf etwa die Haelfte, bevor ueberhaupt gestopft wird.
    gespiegelt = median[:, ::-1]
    spiegel_sauber = sauber[:, ::-1]
    nehmen = ~sauber & spiegel_sauber & innen
    median = np.where(nehmen[..., None], gespiegelt, median)
    sauber = sauber | nehmen
    schmutz = innen & ~sauber

    _, index = ndimage.distance_transform_edt(~sauber, return_indices=True)
    gestopft = median[index[0], index[1]]
    farbe = np.where(schmutz[..., None], gestopft[..., :3], median[..., :3])

    # Das Spiegeln setzt eine Naht auf die Mittelachse und das Stopfen eine
    # zweite an den Rand des gestopften Bereichs. Beide verschwinden, wenn die
    # gestopfte Flaeche kraeftiger geglaettet wird - die Platte ist ohnehin ein
    # ruhiger Verlauf mit waagerechter Maserung, sie verliert dabei nichts.
    weich = np.stack([ndimage.gaussian_filter(farbe[..., k], 1.4) for k in range(3)], axis=-1)
    uebergang = np.clip(ndimage.gaussian_filter(schmutz.astype(np.float32), 2.4) * 1.6, 0, 1)[..., None]
    farbe = farbe * (1 - uebergang) + weich * uebergang

    aus = np.concatenate([farbe, median[..., 3:4]], axis=-1)
    return (Image.fromarray(aus.clip(0, 255).round().astype(np.uint8), "RGBA"),
            float((schmutz & innen).sum() / max(1, innen.sum())))


def radialer_median(pfade: list[Path], mitte: tuple[float, float], r_max: float) -> Image.Image:
    """Kreissymmetrischer Wiederaufbau: Median ueber alle Winkel und alle Motive.

    Ergibt ein Bild, das nur noch vom Radius abhaengt. Die Zeichen sitzen zwar
    alle mittig, streuen aber ueber Winkel und Motiv genug, dass der Median an
    jedem Radius die Traegerfarbe trifft.
    """
    stapel = _stapel(pfade)
    n, h, w, _ = stapel.shape
    ys, xs = np.mgrid[0:h, 0:w]
    r = np.hypot(xs - mitte[0], ys - mitte[1])
    stufen = np.minimum(r.astype(np.int32), int(r_max) + 1)
    aus = np.zeros((h, w, 4), dtype=np.float32)
    flach = stapel.reshape(n, h * w, 4)
    stufen_flach = stufen.ravel()
    for stufe in range(int(r_max) + 2):
        wo = stufen_flach == stufe
        if not wo.any():
            continue
        probe = flach[:, wo, :].reshape(-1, 4)
        aus.reshape(h * w, 4)[wo] = np.median(probe, axis=0)
    return Image.fromarray(aus.round().astype(np.uint8), "RGBA")


def _feld_ersetzen(traeger: Image.Image, feld: Image.Image, mitte, radius: float) -> Image.Image:
    """Das kreissymmetrische Innenfeld in die gemediante Platte einsetzen."""
    maske = Image.new("L", traeger.size, 0)
    ImageDraw.Draw(maske).ellipse(
        [mitte[0] - radius, mitte[1] - radius, mitte[0] + radius, mitte[1] + radius], fill=255)
    aus = traeger.copy()
    aus.paste(feld, (0, 0), maske)
    return aus


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    bericht = {}

    # --- Wappenschild aus Stronghold 1 -----------------------------------
    for zustand in SCHILD_ZUSTAENDE:
        pfade = [SH1 / f"UI-Buttons A{n:03d}.png" for n in SCHILD_SH1[zustand]]
        fehlt = [p.name for p in pfade if not p.exists()]
        if fehlt:
            raise SystemExit(f"fehlt in Stronghold 1: {fehlt}")
        bild, anteil = platte_stopfen(pfade)
        ziel = OUT / f"wappenschild_{zustand}.png"
        bild.save(ziel)
        bericht[ziel.name] = {"quelle": "Stronghold 1", "stichprobe": len(pfade),
                              "groesse": bild.size, "gestopft": round(anteil, 3)}

    # --- Wappenschild aus Crusader, zum Vergleich -------------------------
    for zustand in SCHILD_ZUSTAENDE:
        pfade = [CRU / f"UI-Buttons A{n:03d}.png" for n in SCHILD_CRU[zustand]]
        bild, anteil = platte_stopfen(pfade)
        ziel = OUT / f"wappenschild_crusader_{zustand}.png"
        bild.save(ziel)
        bericht[ziel.name] = {"quelle": "Crusader", "stichprobe": len(pfade),
                              "groesse": bild.size, "gestopft": round(anteil, 3)}

    # --- Ringknopf aus Crusader ------------------------------------------
    # Inhaltsrechteck gemessen: (3, 38) bis (126, 161) im 129x200-Blatt.
    mitte, r_aussen = (64.5, 99.5), 61.5
    for i, zustand in enumerate(RING_ZUSTAENDE):
        pfade = [CRU / f"UI-Buttons S{n + i:03d}.png" for n in RING_MOTIVE]
        platte = median_platte(pfade)
        feld = radialer_median(pfade, mitte, r_aussen)
        bild = _feld_ersetzen(platte, feld, mitte, r_aussen * 0.80)
        ziel = OUT / f"ring_{zustand}.png"
        bild.save(ziel)
        bericht[ziel.name] = {"quelle": "Crusader", "stichprobe": len(pfade), "groesse": bild.size,
                              "verfahren": "Median + radialer Median im Innenfeld"}

    # --- Rote Marke: S001 ist bereits die leere Scheibe -------------------
    scheibe = Image.open(CRU / "UI-Buttons S001.png").convert("RGBA")
    scheibe.save(OUT / "scheibe_ruhend.png")
    bericht["scheibe_ruhend.png"] = {"quelle": "Crusader S001 unveraendert", "groesse": scheibe.size}

    (OUT / "bericht.json").write_text(json.dumps(bericht, indent=2, ensure_ascii=False), encoding="utf-8")
    for name, b in bericht.items():
        g = f"  gestopft {b['gestopft']:.0%}" if "gestopft" in b else ""
        print(f"  {name:38s} {b['groesse']}  {b.get('quelle')}{g}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

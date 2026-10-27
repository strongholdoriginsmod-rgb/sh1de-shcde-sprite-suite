"""Die Oberflaeche namensgleich auf Stronghold 1 umstellen.

Ersetzt den Weg ueber `ui_pair.py`/`ui_apply.py` fuer alles, was sich **benennen**
laesst. Grundlage ist der Fund vom 20.08.2026 (siehe `tools/ui_sh1_dict.py`):
Stronghold 1 DE fuehrt eigene Noesis-Woerterbuecher, und beide Spiele vergeben
darin **dieselben Schluessel**. Was in Crusader `UI-Buildings O013` heisst, heisst
in Stronghold 1 ebenso und zeigt dasselbe Motiv — den berittenen Ritter, einmal
in roter, einmal in blauer Livree.

Damit ist die Zuordnung keine Schaetzung mehr. Gemessen an dieser Installation:

    Crusader-Slots                        3886
    Crusader-Motive (ohne Farbfassungen)  2172
    namensgleich in Stronghold 1          1262
      davon pixelgenau gleich gross         861
      davon anders gross                    401

Gegenprobe, dass Namensgleichheit nicht Zufall ist: paart man Crusader-Slots mit
zufaelligen Stronghold-1-Ausschnitten, stimmt die Groesse in 1,3 % der Faelle;
zieht man zufaellig aus derselben Gruppe, in 39,2 %. Ueber den Namen: 68,2 %.

## Die Spielerfarbe

Crusader fuehrt je farbtragendem Motiv acht Fassungen (Grundfassung = **rot**,
dazu `Blue`, `Green`, `Light Blue`, `Orange`, `Black`, `Purple`, `Yellow`).
Stronghold 1 fuehrt **keine** — sein Auszug ist durchweg blau.

Gemessen ueber 109 farbtragende Familien: Stronghold 1s Livree liegt bei
H = 199,8 Grad, S = 0,95. Crusaders Fassung `Blue` liegt bei H = 203,3, S = 0,88.
Das ist dieselbe Farbe. **Stronghold 1s Ausschnitte sind ohne jede Umfaerbung die
`Blue`-Fassung**, und die uebrigen sieben lassen sich daraus ableiten.

Die Ableitung ist an Crusaders eigenen Fassungen gemessen, nicht geraten: ueber
188 Familien, auf der Maske „wo unterscheidet sich `Blue` von der Grundfassung",
ergibt sich je Ziel ein Farbton, ein Saettigungs- und ein Helligkeitsfaktor.
Die Gegenprobe faerbt Crusaders eigene `Blue`-Fassung um und vergleicht mit
Crusaders echter Zielfassung:

    Green       mittlerer Kanalfehler  7,3   Median  6,3
    Light Blue                        11,2          8,5
    Orange                             9,3          8,5
    Black                              7,4          6,2
    Purple                             6,6          6,3
    Yellow                            11,7         11,0
    Grundfassung (rot)                13,2          9,8

Zum Vergleich: die BC7-Kompression allein verschiebt zwischen zwei Blaettern
rund ein Viertel aller Pixel um acht Stufen. Der Fehler der Umfaerbung liegt in
derselben Groessenordnung — sie ist damit so genau, wie die Vorlage ueberhaupt
hergibt.

## Was das Werkzeug NICHT tut

- Es skaliert nichts stillschweigend. `--groessen` schaltet die
  groessenverschiedenen Paare zu; ohne die Angabe bleiben sie unangetastet und
  werden nur gezaehlt.
- Es fasst keine Motive zusammen. Jeder Slot bekommt seinen namensgleichen
  Ausschnitt oder gar nichts.
- Es beruehrt keine Datei ausserhalb des angegebenen Exportbaums.

## Ablauf

    python tools/ui_sh1_dict.py  --out work/ui-sh1-dict
    python tools/ui_atlas.py export --out work/ui-sh1-umstellung --replace
    python tools/ui_sh1_umstellung.py zuordnen --out work/ui-sh1-zuordnung
    python tools/ui_sh1_umstellung.py boegen   --aus work/ui-sh1-zuordnung
    python tools/ui_sh1_umstellung.py anwenden --aus work/ui-sh1-zuordnung \\
        --baum work/ui-sh1-umstellung --schreiben
    python tools/ui_atlas.py check  --from work/ui-sh1-umstellung
    python tools/ui_atlas.py import --from work/ui-sh1-umstellung --store sh1-umstellung
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import sys

import numpy as np

try:
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover - das venv hat es immer
    print("Pillow fehlt. Bitte im Projekt-venv arbeiten.", file=sys.stderr)
    raise

Image.MAX_IMAGE_PIXELS = None

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Die sieben benannten Fassungen. Die achte, die Grundfassung, traegt keinen
# Zusatz und ist rot.
FASSUNGEN = ("Blue", "Green", "Light Blue", "Orange", "Black", "Purple", "Yellow")
GRUNDFASSUNG = ""

# Aus `work/_blau_nach.py` gemessen: Zielfarbton, Saettigungs- und
# Helligkeitsfaktor, jeweils bezogen auf Stronghold 1s blaue Livree.
# `Blue` fehlt mit Absicht — dort ist die Vorlage bereits richtig.
FARBMODELL: dict[str, dict[str, float]] = {
    "Green": {"h": 105.5, "s": 0.747, "v": 0.926},
    "Light Blue": {"h": 185.5, "s": 0.807, "v": 1.009},
    "Orange": {"h": 29.2, "s": 0.912, "v": 1.079},
    "Black": {"h": 30.0, "s": 0.077, "v": 0.543},
    "Purple": {"h": 271.3, "s": 0.694, "v": 0.812},
    "Yellow": {"h": 45.7, "s": 0.902, "v": 1.122},
    GRUNDFASSUNG: {"h": 8.0, "s": 1.128, "v": 1.090},
}

# Der Livree-Fangbereich. Stronghold 1s Livree liegt ueber 109 Familien bei
# H = 199,8 mit dem 10./90. Perzentil bei 198,0/204,8 — der Bereich ist also
# reichlich weit gefasst und trifft trotzdem kaum etwas anderes.
LIVREE_H = (175.0, 235.0)
LIVREE_S = 0.35
LIVREE_V = 0.10
# Ueber diesem Anteil an der sichtbaren Flaeche ist „das ist Livree" nicht mehr
# glaubhaft; solche Motive werden gemeldet und nicht umgefaerbt.
LIVREE_HOECHSTANTEIL = 0.55

# Ab hier gilt ein namensgleiches Paar als „zeigt schon dasselbe".
GLEICH_SCHWELLE = 0.01
GLEICH_STUFEN = 16

# Die Einteilung der groessenverschiedenen Paare ist danach gemacht, WIEVIEL
# Qualitaet das Einpassen kostet — nicht danach, wie die Rechtecke heissen.
# `faktor` ist der Einpassfaktor min(cw/sw, ch/sh), `leerraum` der Anteil des
# Slot-Rechtecks, der nach seitenverhaeltnistreuem Einpassen leer bleibt.
FEIN_UNTEN, FEIN_OBEN = 0.80, 1.25
LEERRAUM_SCHRANKE = 0.15

UNSAFE = re.compile(r'[<>:"/\\|?*]')

# ---------------------------------------------------------------------------
# Slots, deren Geometrie im XAML festgenagelt ist
# ---------------------------------------------------------------------------
# Am 20.08.2026 im Spiel aufgefallen und danach am XAML nachgewiesen: fuer eine
# Handvoll Slots ist zentriertes Einpassen nicht bloss unschoen, sondern falsch.
# Nicht weil das Bild schlechter aussaehe, sondern weil ANDERE Elemente auf die
# Kanten dieses Bildes gesetzt sind. Ein durchsichtiger Rand verschiebt sie mit.
#
# `fuellen` — der Ausschnitt wird ungleichmaessig auf das ganze Rechteck gezogen.
#   Noetig fuer jeden Schluessel, den das XAML als **gekachelten** `ImageBrush`
#   benutzt. Beleg, `BTN_SH_Glow.xaml:46`:
#
#       <ImageBrush ImageSource="{StaticResource Button_01_Center}"
#                   Viewport="0,0,29.5,31" ViewportUnits="Absolute"
#                   TileMode="Tile" />
#
#   Das ganze 118x124-Bild wird in jede 29,5x31-Kachel gequetscht und
#   wiederholt. Drei durchsichtige Spalten links und rechts — genau der Rest,
#   den `min(118/56, 124/62) = 2,0` uebrig laesst — erscheinen dann als Fuge in
#   JEDER Kachel. Im Spiel sah man acht senkrechte Striche pro Knopf.
#   Crusaders eigene Fassung hat dort waagerecht Rand 0; das ist die Vorgabe.
#   Die Formaenderung betraegt 118/56 gegen 124/62, also 5,4 % — auf einer
#   Kachel unsichtbar.
#
# `linksbuendig-fortsetzen` — gleichmaessig skalieren, den Inhalt an Crusaders
#   linke Inhaltskante legen und das rechte Ende durch Wiederholen der letzten
#   Spalte bis an Crusaders rechte Inhaltskante verlaengern.
#   Noetig fuer die Schildleiste des Hauptmenues. Beleg,
#   `BTN_NewFrontend.xaml:20-75`: die Leiste wird in einem 720x173-Gitter
#   gezeichnet, und das Symbol daneben sitzt in einem **fest vermassten**
#   Kasten (`Width="123" Height="135" Margin="10,0,0,0"`, Bild 93x102
#   zentriert). Das Symbol folgt der Leiste also nicht.
#   Gemessen: Crusaders Inhalt beginnt bei x=9, meine zentrierte Fassung bei
#   x=90 — das Schild rutschte 81 Punkte nach rechts, das Symbol blieb stehen
#   und hing links daneben in der Luft.
#   Das Verlaengern ist verlustfrei: die letzten acht Spalten der
#   Stronghold-1-Leiste sind untereinander **byte-gleich** (Streuung 0,000),
#   die Leiste endet also in einer konstanten Spalte.
SONDERPLATZIERUNG: dict[str, str] = {
    "Button_01_Center": "fuellen",
    "Button_02_Center": "fuellen",
    "Button_03_Center": "fuellen",
    "Button_04_Center": "fuellen",
    "btn_shield_bar_01": "linksbuendig-fortsetzen",
    "btn_shield_bar_01_gray": "linksbuendig-fortsetzen",
    "btn_shield_bar_01_rollover": "linksbuendig-fortsetzen",
    "btn_shield_bar_01_rollover_gray": "linksbuendig-fortsetzen",
}

KLASSEN_REIHENFOLGE = (
    "deckungsgleich",
    "gleich_gross",
    "feinpassung",
    "randlast",
    "verkleinern",
    "vergroessern",
)
# Was `anwenden` ohne zusaetzliche Schalter einsetzt: die beiden Klassen, bei
# denen weder Raten noch sichtbarer Qualitaetsverlust im Spiel ist.
KLASSEN_STANDARD = ("gleich_gross", "feinpassung")

SH1_XAML_STANDARD = PROJECT_ROOT / "work" / "ui-sh1-dict"
CRU_SPRITES = None  # wird aus ui_atlas geholt


class UmstellungError(RuntimeError):
    """Die Umstellung laesst sich nicht sicher rechnen oder schreiben."""


def _unter_work(value: str, zweck: str) -> Path:
    path = Path(value)
    path = path if path.is_absolute() else (PROJECT_ROOT / path)
    path = path.resolve()
    work = (PROJECT_ROOT / "work").resolve()
    if path == work or not path.is_relative_to(work):
        raise UmstellungError(f"{zweck} muss unter {work} liegen, nicht {path}")
    return path


def dateiname(key: str) -> str:
    return UNSAFE.sub("_", key) + ".png"


def zerlege(key: str) -> tuple[str, str]:
    """Schluessel in Grundname und Fassung zerlegen."""

    for fassung in FASSUNGEN:
        if key.endswith(" " + fassung):
            return key[: -(len(fassung) + 1)], fassung
    return key, GRUNDFASSUNG


# ---------------------------------------------------------------- Woerterbuecher


def lies_woerterbuch(ordner: Path) -> dict[str, dict]:
    """Alle CroppedBitmap eines Ordners voller XAML-Woerterbuecher."""

    sys.path.insert(0, str(PROJECT_ROOT / "tools"))
    from ui_atlas import UiAtlasError, read_atlas

    eintraege: dict[str, dict] = {}
    dateien = sorted(ordner.glob("*.xaml"))
    if not dateien:
        raise UmstellungError(f"Keine .xaml in {ordner}")
    for datei in dateien:
        try:
            _, crops = read_atlas(datei)
        except UiAtlasError as error:
            raise UmstellungError(f"{datei.name}: {error}") from error
        for crop in crops:
            if crop.key in eintraege:
                raise UmstellungError(f"Doppelter Schluessel ueber Woerterbuecher: {crop.key}")
            eintraege[crop.key] = {
                "woerterbuch": datei.stem,
                "x": crop.x,
                "y": crop.y,
                "w": crop.width,
                "h": crop.height,
                "datei": f"{datei.stem}/{crop.filename}",
            }
    return eintraege


def crusader_woerterbuch() -> dict[str, dict]:
    sys.path.insert(0, str(PROJECT_ROOT / "tools"))
    import ui_atlas

    sprites, _, _ = ui_atlas._configured_sources()
    return lies_woerterbuch(sprites)


# ------------------------------------------------------------------- Farbwerkzeug


def _hsv(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    a = rgb.astype(np.float64) / 255.0
    mx = a.max(axis=-1)
    mn = a.min(axis=-1)
    d = mx - mn
    h = np.zeros_like(mx)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    m = (d > 0) & (mx == r)
    h[m] = ((g - b)[m] / d[m]) % 6
    m = (d > 0) & (mx == g)
    h[m] = ((b - r)[m] / d[m]) + 2
    m = (d > 0) & (mx == b)
    h[m] = ((r - g)[m] / d[m]) + 4
    return h / 6.0, np.where(mx > 0, d / np.maximum(mx, 1e-9), 0.0), mx


def _rgb(h: np.ndarray, s: np.ndarray, v: np.ndarray) -> np.ndarray:
    i = np.floor(h * 6.0)
    f = h * 6.0 - i
    p = v * (1 - s)
    q = v * (1 - f * s)
    t = v * (1 - (1 - f) * s)
    i = i.astype(int) % 6
    r = np.choose(i, [v, q, p, p, t, v])
    g = np.choose(i, [t, v, v, q, p, p])
    b = np.choose(i, [p, p, t, v, v, q])
    return np.clip(np.stack([r, g, b], axis=-1) * 255 + 0.5, 0, 255).astype(np.uint8)


def livree_maske(bild: np.ndarray) -> np.ndarray:
    """Wo traegt der Stronghold-1-Ausschnitt Spielerfarbe?"""

    h, s, v = _hsv(bild[:, :, :3])
    grad = h * 360.0
    return (
        (grad > LIVREE_H[0])
        & (grad < LIVREE_H[1])
        & (s > LIVREE_S)
        & (v > LIVREE_V)
        & (bild[:, :, 3] > 0)
    )


def umfaerben(bild: np.ndarray, fassung: str) -> tuple[np.ndarray, int]:
    """Stronghold 1s blaue Livree in die verlangte Spielerfarbe ziehen."""

    if fassung == "Blue":
        return bild.copy(), 0
    modell = FARBMODELL[fassung]
    maske = livree_maske(bild)
    ergebnis = bild.copy()
    anzahl = int(maske.sum())
    if anzahl == 0:
        return ergebnis, 0
    h, s, v = _hsv(bild[:, :, :3])
    neu_h = np.full(h[maske].shape, modell["h"] / 360.0)
    neu_s = np.clip(s[maske] * modell["s"], 0.0, 1.0)
    neu_v = np.clip(v[maske] * modell["v"], 0.0, 1.0)
    ergebnis[:, :, :3][maske] = _rgb(neu_h, neu_s, neu_v)
    return ergebnis, anzahl


# --------------------------------------------------------------------- Zuordnung


def _unterschied(a: np.ndarray, b: np.ndarray) -> float:
    return float((np.abs(a.astype(np.int16) - b.astype(np.int16)).max(axis=2) > GLEICH_STUFEN).mean())


def geometrie(cru: dict, sh1: dict) -> tuple[str, float, float]:
    """Klasse, Einpassfaktor und Leerraum eines namensgleichen Paares.

    Die Klassen sind nach dem Preis geordnet, den das Einpassen kostet:

    ``gleich_gross``  Rechteck stimmt aufs Pixel — hineinlegen, fertig.
    ``feinpassung``   Faktor 0,80…1,25 und wenig Leerraum. Der Massstabssprung
                      liegt unter dem, was auf einem 24-Punkt-Symbol sichtbar
                      waere; hier wird ohne Rueckfrage skaliert.
    ``randlast``      Faktor im selben Band, aber das Seitenverhaeltnis weicht
                      so ab, dass mehr als ein Siebtel des Slots leer bleibt.
    ``verkleinern``   unter 0,80 — sichtbarer Detailverlust.
    ``vergroessern``  ueber 1,25. Fast immer genau 2,0: Crusader fuehrt sein
                      Rahmenwerk in doppelter Aufloesung.
    """

    cw, ch = cru["w"], cru["h"]
    sw, sh = sh1["w"], sh1["h"]
    if (cw, ch) == (sw, sh):
        return "gleich_gross", 1.0, 0.0
    faktor = min(cw / sw, ch / sh)
    breite = max(1, round(sw * faktor))
    hoehe = max(1, round(sh * faktor))
    leerraum = 1.0 - (breite * hoehe) / (cw * ch)
    if faktor < FEIN_UNTEN:
        return "verkleinern", faktor, leerraum
    if faktor > FEIN_OBEN:
        return "vergroessern", faktor, leerraum
    if leerraum > LEERRAUM_SCHRANKE:
        return "randlast", faktor, leerraum
    return "feinpassung", faktor, leerraum


def zuordnen(cru_dict: dict[str, dict], sh1_dict: dict[str, dict],
             cru_baum: Path, sh1_baum: Path) -> dict:
    """Je Crusader-Familie entscheiden, was Stronghold 1 dazu hergibt."""

    familien: dict[str, dict[str, str]] = defaultdict(dict)
    for key in cru_dict:
        grund, fassung = zerlege(key)
        familien[grund][fassung] = key

    eintraege: list[dict] = []
    ohne: list[str] = []
    for grund in sorted(familien):
        if grund not in sh1_dict:
            ohne.append(grund)
            continue
        cru = cru_dict[grund]
        sh1 = sh1_dict[grund]
        fassungen = familien[grund]
        farbtragend = len(fassungen) > 1
        klasse, faktor, leerraum = geometrie(cru, sh1)
        eintrag = {
            "grund": grund,
            "klasse": klasse,
            "faktor": round(faktor, 4),
            "leerraum": round(leerraum, 4),
            "farbtragend": farbtragend,
            "slots": {f: fassungen[f] for f in sorted(fassungen)},
            "crusader": {"datei": cru["datei"], "w": cru["w"], "h": cru["h"]},
            "sh1": {"datei": sh1["datei"], "w": sh1["w"], "h": sh1["h"]},
        }
        if eintrag["klasse"] == "gleich_gross":
            pfad_c = cru_baum / cru["datei"]
            pfad_s = sh1_baum / sh1["datei"]
            if pfad_c.is_file() and pfad_s.is_file():
                a = np.asarray(Image.open(pfad_c).convert("RGBA"))
                b = np.asarray(Image.open(pfad_s).convert("RGBA"))
                unterschied = _unterschied(a, b)
                eintrag["unterschied"] = round(unterschied, 4)
                if unterschied < GLEICH_SCHWELLE:
                    eintrag["klasse"] = "deckungsgleich"
        if farbtragend:
            pfad_s = sh1_baum / sh1["datei"]
            if pfad_s.is_file():
                bild = np.asarray(Image.open(pfad_s).convert("RGBA"))
                sichtbar = int((bild[:, :, 3] > 128).sum())
                anteil = float(livree_maske(bild).sum()) / max(sichtbar, 1)
                eintrag["livree_anteil"] = round(anteil, 4)
                if anteil > LIVREE_HOECHSTANTEIL:
                    eintrag["livree_verdaechtig"] = True
        eintraege.append(eintrag)

    return {
        "schema_version": 1,
        "quelle": "namensgleiche Schluessel aus beiden Noesis-Woerterbuechern",
        "farbmodell": FARBMODELL,
        "eintraege": eintraege,
        "ohne_gegenstueck": ohne,
    }


def bericht(zuordnung: dict) -> list[str]:
    eintraege = zuordnung["eintraege"]
    zeilen: list[str] = []
    klassen = Counter(e["klasse"] for e in eintraege)
    slots = Counter()
    for e in eintraege:
        slots[e["klasse"]] += len(e["slots"])
    zeilen.append(f"{'Klasse':26} {'Familien':>9} {'Slots':>7}")
    for name in KLASSEN_REIHENFOLGE:
        if klassen[name]:
            zeilen.append(f"{name:26} {klassen[name]:9} {slots[name]:7}")
    zeilen.append(f"{'ohne Gegenstueck':26} {len(zuordnung['ohne_gegenstueck']):9}")
    farb = [e for e in eintraege if e["farbtragend"]]
    zeilen.append("")
    zeilen.append(f"farbtragende Familien mit Gegenstueck: {len(farb)}"
                  f"  ({sum(len(e['slots']) for e in farb)} Slots)")
    verdaechtig = [e for e in farb if e.get("livree_verdaechtig")]
    if verdaechtig:
        zeilen.append(f"  davon mit unglaubhaft grosser Livree-Flaeche: {len(verdaechtig)}")
    duenn = [e for e in farb if e.get("livree_anteil", 1.0) < 0.02]
    zeilen.append(f"  davon praktisch ohne Livree (<2 %): {len(duenn)}"
                  f" — acht gleiche Fassungen, wie in Crusader auch")
    return zeilen


# ---------------------------------------------------------------------- Anwenden


def _einpassen(sh1: Image.Image, ziel: tuple[int, int], anker: str,
               fuellen: float = 0.0) -> Image.Image:
    """Den Ausschnitt auf die Slotgroesse bringen, Seitenverhaeltnis gewahrt.

    ## Warum die Mitte der richtige Anker ist — gemessen, nicht gesetzt

    Am 20.08.2026 an der Vorlage nachgesehen, die die Bausymbole zeichnet
    (`XAMLResources/BTN_Building.xaml`): das `<Image>` traegt **kein**
    `Stretch`-Attribut und keine Ausrichtung. Damit gilt die Voreinstellung
    `Stretch="Uniform"` in einer Zelle, die die ganze Schaltflaeche fuellt —
    das Bild wird also seitenverhaeltnistreu in den Knopf skaliert und
    **zentriert**. Eine Grundlinie, an der `unten-mitte` etwas ausrichten
    koennte, gibt es in der Vorlage nicht.

    ## Was Leerraum kostet

    Weil `Uniform` das **Rechteck** in den Knopf einpasst und nicht das Motiv,
    geht durchsichtiger Rand im Rechteck eins zu eins als gezeichnete Flaeche
    verloren. Gemessen ueber die eingesetzten Klassen: `gleich_gross` 0 %,
    `feinpassung` im Median 2,9 %, `randlast` 26 %, `verkleinern` 24 %.
    Ueber 30 % liegen **32 Familien / 50 Slots** von 1622.

    `fuellen` erlaubt, diesen Rand teilweise zurueckzuholen: der Ausschnitt
    darf um bis zu diesen Anteil ungleichmaessig gedehnt werden, bevor der
    Rest als Rand stehen bleibt. `0.0` ist die Voreinstellung und laesst das
    Seitenverhaeltnis unangetastet.
    """

    zw, zh = ziel
    faktor = min(zw / sh1.width, zh / sh1.height)
    breite = max(1, int(round(sh1.width * faktor)))
    hoehe = max(1, int(round(sh1.height * faktor)))
    if fuellen > 0.0:
        # Die schmalere Kante bis zur Deckelgrenze nachziehen. Der Deckel gilt
        # je Kante, damit aus einer erlaubten Dehnung von 12 % nicht ueber zwei
        # Kanten eine Formaenderung von 25 % wird.
        breite = min(zw, max(1, int(round(breite * (1.0 + fuellen)))))
        hoehe = min(zh, max(1, int(round(hoehe * (1.0 + fuellen)))))
    if (breite, hoehe) != sh1.size:
        # Ganzzahlige Vergroesserung bleibt hart — Crusaders Rahmenwerk ist an
        # mehreren Stellen genau die doppelt aufgeloeste Fassung desselben
        # Bildes, und LANCZOS wuerde die Kanten weich machen.
        ganzzahlig = (
            fuellen == 0.0 and faktor >= 2 and abs(faktor - round(faktor)) < 0.02
        )
        sh1 = sh1.resize((breite, hoehe),
                         Image.NEAREST if ganzzahlig else Image.LANCZOS)
    leinwand = Image.new("RGBA", (zw, zh), (0, 0, 0, 0))
    x = (zw - breite) // 2
    y = (zh - hoehe) // 2 if anker == "mitte" else zh - hoehe
    leinwand.paste(sh1, (x, y))
    return leinwand


def _inhaltsrand(bild: Image.Image) -> tuple[int, int, int, int]:
    """Wieviel durchsichtiger Rand steht links, rechts, oben, unten?"""

    kasten = bild.getbbox()
    if kasten is None:
        return (0, 0, 0, 0)
    links, oben, rechts, unten = kasten
    return (links, bild.width - rechts, oben, bild.height - unten)


def _fuellen_ganz(sh1: Image.Image, ziel: tuple[int, int]) -> Image.Image:
    """Ungleichmaessig auf das ganze Rechteck ziehen — fuer gekachelte Brushes."""

    return sh1.resize(ziel, Image.LANCZOS)


def _linksbuendig_fortsetzen(
    sh1: Image.Image, ziel: tuple[int, int], vorbild: Image.Image
) -> Image.Image:
    """Inhalt an die linke Kante des Vorbilds legen und rechts fortsetzen."""

    zw, zh = ziel
    faktor = min(zw / sh1.width, zh / sh1.height)
    ganzzahlig = faktor >= 2 and abs(faktor - round(faktor)) < 0.02
    breite = max(1, int(round(sh1.width * faktor)))
    hoehe = max(1, int(round(sh1.height * faktor)))
    skaliert = sh1.resize((breite, hoehe),
                          Image.NEAREST if ganzzahlig else Image.LANCZOS)

    ziel_links = _inhaltsrand(vorbild)[0]
    quelle_links = _inhaltsrand(skaliert)[0]
    versatz_x = max(0, min(zw - breite, ziel_links - quelle_links))
    leinwand = Image.new("RGBA", (zw, zh), (0, 0, 0, 0))
    leinwand.paste(skaliert, (versatz_x, (zh - hoehe) // 2))

    # Rechtes Ende bis an die Inhaltskante des Vorbilds verlaengern.
    #
    # Nicht durch Wiederholen der letzten Spalte: gemessen laeuft das goldene
    # Flechtband bis an die Kante, die letzte Spalte weicht von der viertletzten
    # um 141 Stufen ab. Ein Spaltenwiederholer ergaebe senkrechte Streifen.
    #
    # Stattdessen wird nur der BALKEN gedehnt und der Schildkopf in Ruhe
    # gelassen. Der Kopf ist die Stelle links, an der der Inhalt deutlich hoeher
    # steht als der Balken; rechts davon ist die Leiste ein waagerecht
    # gleichfoermiges Band, dem eine Dehnung um wenige Prozent nichts ausmacht.
    # Die Nahtstelle bleibt dieselbe Spalte, es entsteht also keine Kante.
    inhalt_rechts = zw - _inhaltsrand(leinwand)[1]
    soll_rechts = zw - _inhaltsrand(vorbild)[1]
    if inhalt_rechts >= soll_rechts:
        return leinwand

    feld = np.asarray(leinwand)
    hoehe_je_spalte = (feld[:, :, 3] > 16).sum(axis=0)
    balken = int(np.median(hoehe_je_spalte[versatz_x + breite // 2 : inhalt_rechts]))
    kopf = np.where(hoehe_je_spalte > balken * 1.35)[0]
    schnitt = int(kopf[-1]) + 1 if len(kopf) else versatz_x
    if not versatz_x < schnitt < inhalt_rechts - 8:
        return leinwand

    band = leinwand.crop((schnitt, 0, inhalt_rechts, zh))
    gedehnt = band.resize((soll_rechts - schnitt, zh), Image.LANCZOS)
    leinwand.paste(gedehnt, (schnitt, 0))
    return leinwand


def uebernehmen(quelle: Path, baum: Path, *, schreiben: bool) -> tuple[list[str], list[str]]:
    """Von Hand erzeugte Ausschnitte in den Exportbaum zurueckholen.

    Ohne diesen Schritt verliert jeder Neubau des Exportbaums die Bilder, fuer
    die es in Stronghold 1 kein Gegenstueck gibt und die deshalb gezeichnet
    wurden — am 17.08. waren das `Arabic Lord` und `Arabic Lord Over`. Ein
    solcher Verlust faellt nicht auf: der Slot traegt dann wieder Crusaders
    Original, und `ui_atlas.py check` ist damit zufrieden.

    Geprueft wird gegen den Exportbaum, nicht geglaubt: eine Uebernahme, die
    nicht auf das Slot-Rechteck passt, wird abgewiesen statt skaliert.
    """

    index = json.loads((baum / "index.json").read_text(encoding="utf-8"))
    ort: dict[str, Path] = {}
    for atlas in index["atlases"]:
        for crop in atlas["crops"]:
            ort[crop["file"]] = baum / atlas["directory"] / crop["file"]

    genommen: list[str] = []
    probleme: list[str] = []
    for datei in sorted(quelle.glob("*.png")):
        ziel = ort.get(datei.name)
        if ziel is None:
            probleme.append(f"{datei.name}: kein Slot dieses Namens im Exportbaum")
            continue
        with Image.open(ziel) as offen:
            soll = offen.size
        with Image.open(datei) as offen:
            bild = offen.convert("RGBA")
            bild.load()
        if bild.size != soll:
            probleme.append(
                f"{datei.name}: {bild.width}x{bild.height} statt {soll[0]}x{soll[1]}"
            )
            continue
        if schreiben:
            bild.save(ziel)
        genommen.append(datei.name)
    return genommen, probleme


def anwenden(zuordnung: dict, sh1_baum: Path, baum: Path, *,
             klassen: set[str], anker: str, schreiben: bool,
             gruppen: list[str] | None, fuellen: float = 0.0,
             vorbild_baum: Path | None = None) -> dict:
    if not (baum / "index.json").is_file():
        raise UmstellungError(
            f"{baum} ist kein Exportbaum — index.json fehlt. Erst anlegen mit:\n"
            f"  python tools/ui_atlas.py export --out {baum.relative_to(PROJECT_ROOT)} --replace"
        )
    index = json.loads((baum / "index.json").read_text(encoding="utf-8"))
    slot_ort: dict[str, tuple[str, str]] = {}
    for atlas in index["atlases"]:
        for crop in atlas["crops"]:
            slot_ort[crop["key"]] = (atlas["directory"], crop["file"])

    zaehler = Counter()
    geschrieben: list[str] = []
    probleme: list[str] = []
    for eintrag in zuordnung["eintraege"]:
        if eintrag["klasse"] not in klassen:
            zaehler["klasse uebersprungen"] += 1
            continue
        if gruppen and eintrag["grund"].split(" ")[0] not in gruppen:
            continue
        quelle = sh1_baum / eintrag["sh1"]["datei"]
        if not quelle.is_file():
            probleme.append(f"{eintrag['grund']}: Quelle fehlt {quelle}")
            continue
        with Image.open(quelle) as offen:
            sh1_bild = offen.convert("RGBA")
            sh1_bild.load()

        for fassung, key in eintrag["slots"].items():
            ort = slot_ort.get(key)
            if ort is None:
                probleme.append(f"{key}: im Exportbaum nicht gefunden")
                continue
            ziel = baum / ort[0] / ort[1]
            if not ziel.is_file():
                probleme.append(f"{key}: Slotdatei fehlt {ziel}")
                continue
            with Image.open(ziel) as offen:
                slot_groesse = offen.size

            bild = sh1_bild
            if eintrag["farbtragend"] and not eintrag.get("livree_verdaechtig"):
                feld, _ = umfaerben(np.asarray(bild), fassung)
                bild = Image.fromarray(feld, "RGBA")
            elif eintrag["farbtragend"]:
                zaehler["livree verdaechtig, nicht umgefaerbt"] += 1

            sonder = SONDERPLATZIERUNG.get(key)
            if sonder == "fuellen":
                bild = _fuellen_ganz(bild, slot_groesse)
                zaehler["sonderplatzierung fuellen"] += 1
            elif sonder == "linksbuendig-fortsetzen":
                vorbild_pfad = (vorbild_baum / ort[0] / ort[1]) if vorbild_baum else None
                if vorbild_pfad is None or not vorbild_pfad.is_file():
                    probleme.append(
                        f"{key}: Sonderplatzierung braucht den unveraenderten "
                        f"Crusader-Auszug (--crusader)"
                    )
                    continue
                with Image.open(vorbild_pfad) as offen:
                    vorbild = offen.convert("RGBA")
                    vorbild.load()
                bild = _linksbuendig_fortsetzen(bild, slot_groesse, vorbild)
                zaehler["sonderplatzierung linksbuendig"] += 1
            elif bild.size != slot_groesse:
                bild = _einpassen(bild, slot_groesse, anker, fuellen)
            if schreiben:
                bild.save(ziel)
            geschrieben.append(key)
            zaehler[eintrag["klasse"]] += 1

    return {
        "geschrieben": geschrieben,
        "zaehler": dict(zaehler),
        "probleme": probleme,
        "schreiben": schreiben,
    }


# ------------------------------------------------------------------ Kontaktboegen


def boegen(zuordnung: dict, cru_baum: Path, sh1_baum: Path, ziel: Path,
           *, zelle: int = 128, spalten: int = 8) -> int:
    ziel.mkdir(parents=True, exist_ok=True)
    nach_gruppe: dict[str, list[dict]] = defaultdict(list)
    for eintrag in zuordnung["eintraege"]:
        nach_gruppe[eintrag["grund"].split(" ")[0]].append(eintrag)
    gebaut = 0
    for gruppe, eintraege in sorted(nach_gruppe.items()):
        eintraege = sorted(eintraege, key=lambda e: e["grund"])
        for teil in range(0, len(eintraege), spalten * 6):
            teilmenge = eintraege[teil : teil + spalten * 6]
            zeilen = (len(teilmenge) + spalten - 1) // spalten
            breite = spalten * (zelle * 2 + 8) + 8
            hoehe = zeilen * (zelle + 18) + 8
            bogen = Image.new("RGBA", (breite, hoehe), (28, 28, 32, 255))
            stift = ImageDraw.Draw(bogen)
            for i, eintrag in enumerate(teilmenge):
                r, c = divmod(i, spalten)
                x = 8 + c * (zelle * 2 + 8)
                y = 8 + r * (zelle + 18)
                for j, pfad in enumerate((cru_baum / eintrag["crusader"]["datei"],
                                          sh1_baum / eintrag["sh1"]["datei"])):
                    kasten = (x + j * zelle, y)
                    if pfad.is_file():
                        with Image.open(pfad) as offen:
                            bild = offen.convert("RGBA")
                            bild.thumbnail((zelle, zelle), Image.LANCZOS)
                        bogen.alpha_composite(
                            bild,
                            (kasten[0] + (zelle - bild.width) // 2,
                             kasten[1] + (zelle - bild.height) // 2),
                        )
                    else:
                        stift.rectangle(
                            (kasten[0], kasten[1], kasten[0] + zelle, kasten[1] + zelle),
                            outline=(200, 60, 60, 255),
                        )
                stift.line((x + zelle, y, x + zelle, y + zelle), fill=(90, 90, 110, 255))
                marke = eintrag["klasse"][:3]
                stift.text((x + 2, y + zelle + 3),
                           f"{eintrag['grund'][:28]}  [{marke}]",
                           fill=(210, 210, 220, 255))
            name = UNSAFE.sub("_", gruppe) + (f"-{teil // (spalten * 6) + 1}" if len(eintraege) > spalten * 6 else "")
            bogen.save(ziel / f"{name}.png")
            gebaut += 1
    return gebaut


# ---------------------------------------------------------------------- Befehle


def cmd_zuordnen(args: argparse.Namespace) -> int:
    ziel = _unter_work(args.out, "Ausgabe")
    sh1_baum = _unter_work(args.sh1, "Stronghold-1-Auszug")
    cru_baum = _unter_work(args.crusader, "Crusader-Auszug")
    cru = crusader_woerterbuch()
    sh1 = lies_woerterbuch(sh1_baum)
    daten = zuordnen(cru, sh1, cru_baum, sh1_baum)
    ziel.mkdir(parents=True, exist_ok=True)
    (ziel / "zuordnung.json").write_text(
        json.dumps(daten, indent=1, ensure_ascii=False), encoding="utf-8"
    )
    zeilen = bericht(daten)
    (ziel / "bericht.txt").write_text("\n".join(zeilen) + "\n", encoding="utf-8")
    print("\n".join(zeilen))
    print(f"\ngeschrieben: {ziel / 'zuordnung.json'}")
    return 0


def cmd_boegen(args: argparse.Namespace) -> int:
    aus = _unter_work(args.aus, "Zuordnung")
    daten = json.loads((aus / "zuordnung.json").read_text(encoding="utf-8"))
    gebaut = boegen(
        daten,
        _unter_work(args.crusader, "Crusader-Auszug"),
        _unter_work(args.sh1, "Stronghold-1-Auszug"),
        aus / "boegen",
    )
    print(f"{gebaut} Kontaktboegen in {aus / 'boegen'}")
    return 0


def cmd_anwenden(args: argparse.Namespace) -> int:
    aus = _unter_work(args.aus, "Zuordnung")
    daten = json.loads((aus / "zuordnung.json").read_text(encoding="utf-8"))
    klassen = set(KLASSEN_STANDARD)
    if args.deckungsgleich:
        klassen.add("deckungsgleich")
    if args.randlast:
        klassen.add("randlast")
    if args.verkleinern:
        klassen.add("verkleinern")
    if args.vergroessern:
        klassen.add("vergroessern")
    if args.alles:
        klassen |= set(KLASSEN_REIHENFOLGE)
    baum = _unter_work(args.baum, "Exportbaum")
    ergebnis = anwenden(
        daten,
        _unter_work(args.sh1, "Stronghold-1-Auszug"),
        baum,
        klassen=klassen,
        anker=args.anker,
        schreiben=args.schreiben,
        gruppen=args.gruppe or None,
        fuellen=args.fuellen,
        vorbild_baum=_unter_work(args.crusader, "Crusader-Auszug"),
    )
    print(f"Klassen: {', '.join(sorted(klassen))}")
    if args.fuellen:
        print(f"Randausgleich: bis {args.fuellen:.0%} ungleichmaessige Dehnung")
    for name, zahl in sorted(ergebnis["zaehler"].items()):
        print(f"  {name:36} {zahl:6}")
    print(f"  {'Slots insgesamt':36} {len(ergebnis['geschrieben']):6}")
    probleme = list(ergebnis["probleme"])

    if args.uebernehmen:
        quelle = _unter_work(args.uebernehmen, "Uebernahme")
        genommen, wund = uebernehmen(quelle, baum, schreiben=args.schreiben)
        probleme += wund
        print(f"  {'von Hand uebernommen':36} {len(genommen):6}")
        for name in genommen:
            print(f"      {name}")

    for zeile in probleme[:20]:
        print(f"  Problem: {zeile}", file=sys.stderr)
    if len(probleme) > 20:
        print(f"  ... und {len(probleme) - 20} weitere", file=sys.stderr)
    if not args.schreiben:
        print("\nProbelauf — nichts geschrieben. Mit --schreiben ausfuehren.")
    return 1 if probleme else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ui_sh1_umstellung",
        description="Crusaders Oberflaeche ueber namensgleiche Schluessel auf Stronghold 1 umstellen.",
    )
    unter = parser.add_subparsers(dest="befehl", required=True)

    for name, hilfe in (("zuordnen", "Zuordnung rechnen und berichten"),
                        ("boegen", "Kontaktboegen bauen"),
                        ("anwenden", "in einen Exportbaum schreiben")):
        p = unter.add_parser(name, help=hilfe)
        p.add_argument("--sh1", default="work/ui-sh1-dict")
        p.add_argument("--crusader", default="work/ui-cru-voll")
        if name == "zuordnen":
            p.add_argument("--out", default="work/ui-sh1-zuordnung")
        else:
            p.add_argument("--aus", default="work/ui-sh1-zuordnung")
        if name == "anwenden":
            p.add_argument("--baum", required=True)
            p.add_argument("--schreiben", action="store_true")
            p.add_argument("--gruppe", action="append")
            p.add_argument("--anker", choices=("unten-mitte", "mitte"), default="mitte")
            p.add_argument("--deckungsgleich", action="store_true",
                           help="auch Paare einsetzen, die schon dasselbe zeigen")
            p.add_argument("--randlast", action="store_true",
                           help="auch Paare, die viel Rand im Slot leer lassen")
            p.add_argument("--verkleinern", action="store_true",
                           help="auch Paare, die sichtbar verkleinert werden muessen")
            p.add_argument("--vergroessern", action="store_true",
                           help="auch Paare, die vergroessert werden muessen (Rahmenwerk, meist genau 2x)")
            p.add_argument("--alles", action="store_true",
                           help="jede Klasse einsetzen")
            p.add_argument("--uebernehmen", metavar="ORDNER",
                           help="von Hand erzeugte PNGs aus ORDNER nach dem Einsetzen "
                                "zurueckholen (Groesse wird geprueft, nicht skaliert)")
            p.add_argument("--fuellen", type=float, default=0.0, metavar="ANTEIL",
                           help="durchsichtigen Rand durch ungleichmaessige Dehnung bis "
                                "zu diesem Anteil je Kante zurueckholen (0 = aus)")

    args = parser.parse_args(argv)
    befehle = {"zuordnen": cmd_zuordnen, "boegen": cmd_boegen, "anwenden": cmd_anwenden}
    try:
        return befehle[args.befehl](args)
    except UmstellungError as error:
        print(f"Fehler: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

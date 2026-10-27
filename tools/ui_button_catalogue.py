"""Motivkatalog der Knopfgrafiken (UI-Buttons S*/A*) im UI-MasterAtlas.

Gruppiert die 167 Ausschnitte in Motivfamilien. Zustaende (Ring silber/gold,
Schildgrund braun/dunkelrot/rot/grau) liegen im Bestand als aufeinander
folgende Nummern; die Familie wird deshalb ueber einen Lauf benachbarter
Nummern mit kleinem Bildabstand gebildet, nicht ueber globales Clustern.

Ausgabe: work/ui-europa-buttons/katalog.json + kontaktbogen_familien.png
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
ATLAS = ROOT / "work" / "ui" / "UI-MasterAtlas"
OUT = ROOT / "work" / "ui-europa-buttons"
SIG = 24
THRESHOLD = float(os.environ.get("KATALOG_SCHWELLE", "0.20"))


def signature(im: Image.Image):
    """Alphamaske + normierte Gradientenstaerke.

    Die Zustaende einer Familie unterscheiden sich fast nur im Farbton der
    Traegerflaeche. Ein Farbwechsel in einer glatten Flaeche erzeugt kaum
    Gradient, die Umrisslinie des Zeichens dagegen sehr viel. Darum traegt die
    Gradientenstruktur das Motiv durch den Zustandswechsel, waehrend ein
    Grauwert-Vergleich daran zerfaellt (gemessen: 97 statt 49 Familien).
    """
    im = im.convert("RGBA")
    a = im.getchannel("A").resize((SIG, SIG), Image.BILINEAR)
    alpha = [p / 255.0 for p in a.get_flattened_data()]

    big = SIG * 3
    lum = im.convert("L").resize((big, big), Image.BILINEAR)
    px = list(lum.get_flattened_data())
    grad = Image.new("L", (big, big))
    gp = []
    for y in range(big):
        for x in range(big):
            i = y * big + x
            gx = px[i + 1] - px[i - 1] if 0 < x < big - 1 else 0
            gy = px[i + big] - px[i - big] if 0 < y < big - 1 else 0
            gp.append(min(255, int((gx * gx + gy * gy) ** 0.5)))
    grad.putdata(gp)
    g = grad.resize((SIG, SIG), Image.BILINEAR)
    edges = [p / 255.0 for p in g.get_flattened_data()]
    peak = max(edges) or 1e-6
    edges = [e / peak for e in edges]
    return alpha, edges


def dist(s1, s2):
    a1, e1 = s1
    a2, e2 = s2
    da = sum(abs(x - y) for x, y in zip(a1, a2)) / len(a1)
    de = sum(abs(x - y) for x, y in zip(e1, e2)) / len(e1)
    return da * 2.0 + de


def main() -> int:
    files = sorted(
        p for p in ATLAS.glob("UI-Buttons *.png")
        if re.fullmatch(r"[SA]\d{3}", p.stem.split(" ")[-1])
    )
    if not files:
        print("keine Knopfgrafiken gefunden", file=sys.stderr)
        return 1

    recs = []
    for p in files:
        im = Image.open(p).convert("RGBA")
        recs.append({
            "key": p.stem.split(" ")[-1],
            "datei": p.name,
            "groesse": list(im.size),
            "_sig": signature(im),
        })

    families, cur = [], [recs[0]]
    for prev, rec in zip(recs, recs[1:]):
        same_series = prev["key"][0] == rec["key"][0]
        adjacent = int(rec["key"][1:]) == int(prev["key"][1:]) + 1
        same_size = prev["groesse"] == rec["groesse"]
        d = dist(cur[0]["_sig"], rec["_sig"])
        if same_series and adjacent and same_size and d < THRESHOLD:
            cur.append(rec)
        else:
            families.append(cur)
            cur = [rec]
    families.append(cur)

    OUT.mkdir(parents=True, exist_ok=True)
    katalog = []
    for i, fam in enumerate(families, 1):
        katalog.append({
            "familie": f"F{i:02d}",
            "reihe": fam[0]["key"][0],
            "mitglieder": [r["key"] for r in fam],
            "zustaende": len(fam),
            "groesse": fam[0]["groesse"],
            "dateien": [r["datei"] for r in fam],
        })
    (OUT / "katalog.json").write_text(
        json.dumps({"quelle": str(ATLAS), "familien": katalog}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    cols, cell = 10, 132
    rows = (len(families) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell, rows * (cell + 30)), (52, 52, 58))
    dr = ImageDraw.Draw(sheet)
    for i, fam in enumerate(families):
        bx, by = (i % cols) * cell, (i // cols) * (cell + 30)
        for ax in range(bx, bx + cell, 11):
            for ay in range(by, by + cell, 11):
                tone = (118, 118, 124) if ((ax - bx) // 11 + (ay - by) // 11) % 2 == 0 else (158, 158, 164)
                dr.rectangle([ax, ay, ax + 10, ay + 10], fill=tone)
        im = Image.open(ATLAS / fam[0]["datei"]).convert("RGBA")
        im.thumbnail((cell - 10, cell - 10))
        sheet.paste(im, (bx + (cell - im.width) // 2, by + (cell - im.height) // 2), im)
        dr.text((bx + 4, by + cell + 2), f"F{i+1:02d}  {fam[0]['key']}", fill=(245, 245, 245))
        dr.text((bx + 4, by + cell + 14), f"{len(fam)}x  {fam[0]['groesse'][0]}x{fam[0]['groesse'][1]}", fill=(190, 190, 200))
    sheet.save(OUT / "kontaktbogen_familien.png")

    print(f"Ausschnitte {len(recs)}  Familien {len(families)}")
    for f in katalog:
        print(f"  {f['familie']}  {f['reihe']}  {f['zustaende']}x  {f['groesse'][0]}x{f['groesse'][1]}  {', '.join(f['mitglieder'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

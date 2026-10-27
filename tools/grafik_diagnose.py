"""Grafik-Diagnose: die Fehlerklassen, die uns schon begegnet sind, mechanisch finden.

Jede Pruefung ist aus einem echten Fall abgeleitet und nennt ihn:

  anker        Zinnen (09/2026): Pivot 1,0 bzw. 0,0 ist eine Kantenkonvention.
               Ausgelieferte Frames, deren Pixelanker vom erwarteten abweicht,
               sitzen im Spiel verschoben.
  objekte      Huetten (09/2026): Ein Kachelobjekt wurde nur teilweise auf einen
               Spender umgelenkt; der alte Sockel blieb stehen.
  umlenkungen  Kornspeicher/Waffenkammer (09/2026): gleicher Grundriss beweist
               nicht dieselbe Gebaeudeart. Erzeugt Gegenueberstellungen
               Ziel <-> Spender zur Sichtpruefung.
  drift        Zugbruecke (09/2026): das Zielspiel hat andere Frame-Anzahlen als
               das Profil erwartet (2.7 <-> 2.80).
  leinwand     leere oder fehlende Frames, BC7-Blockraster, Maskenpaare.
  bundles      Bundles gegen index.json (Groesse, SHA-256, CRC32).
  alles        alles zusammen, Bericht nach work/diagnose/bericht.json

Nur lesend. Befunde sind Hinweise mit Schweregrad (fehler/warnung/info) und,
wo moeglich, einem vorgeschlagenen Behebungsbefehl fuer den Asset-Katalog.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
import zlib
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

import asset_katalog as katalog  # noqa: E402

OUT = PROJECT_ROOT / "work" / "diagnose"
FOOTPRINTS = (1, 4, 9, 16, 25, 36, 49, 64, 81, 100, 121)


def finding(kind, severity, group, text, frames=None, fix=None, data=None):
    return {"pruefung": kind, "schwere": severity, "gruppe": group, "text": text,
            "frames": frames or [], "behebung": fix, "daten": data or {}}


def say(text=""):
    print(text, flush=True)


def load_atlas(bundle: Path) -> dict | None:
    import UnityPy

    env = UnityPy.load(str(bundle))
    for obj in env.objects:
        if obj.type.name == "TextAsset":
            script = obj.read().m_Script
            if isinstance(script, (bytes, bytearray)):
                script = bytes(script).decode("utf-8")
            try:
                return json.loads(script)
            except ValueError:
                continue
    return None


def delivered_groups(mod: Path) -> list[dict]:
    index = katalog.load_json(mod / "Runtime" / "AssetBundles" / "index.json", {"groups": []})
    return index.get("groups", [])


def mapping_by_name() -> dict[str, dict]:
    return {str(row.get("name")): row for row in katalog.mapping().get("sprites", [])}


# ------------------------------------------------------------------ checks

def check_anker(mod: Path, only: set[str] | None, tolerance: float) -> list[dict]:
    rows = mapping_by_name()
    results = []
    for entry in delivered_groups(mod):
        group = str(entry.get("group"))
        slug = str(entry.get("slug") or group).lower()
        if only and group.lower() not in only and slug not in only:
            continue
        atlas = load_atlas(mod / entry["bundle_path"])
        if atlas is None:
            results.append(finding("anker", "warnung", group, "Atlas im Bundle nicht lesbar"))
            continue
        bad = []
        for frame in atlas.get("frames", []):
            name = str(frame.get("name"))
            row = rows.get(name)
            if row is None or not row.get("target"):
                continue
            target, source = row["target"], row.get("source") or {}
            w, h = frame["rect"]["width"], frame["rect"]["height"]
            px, py = frame["pivot"]["x"], frame["pivot"]["y"]
            tw, th = float(target["width"]), float(target["height"])
            tpx, tpy = float(target["pivot_x"]), float(target["pivot_y"])
            sw, sh = float(source.get("width") or 0), float(source.get("height") or 0)
            spx, spy = float(source.get("pivot_x") or 0), float(source.get("pivot_y") or 0)
            # Kantenkonvention (Zinnen-Befund): ein Ziel-Pivot von exakt 1 haelt
            # die rechte/obere Kante fest - auch auf anderer Leinwand.
            for axis, (tp, size, tsize) in enumerate(((tpx, w, tw), (tpy, h, th))):
                if abs(tp - 1.0) < 1e-6 and abs(size - tsize) > 0.5:
                    delivered = (px, py)[axis]
                    if abs(delivered - 1.0) > 1e-6:
                        bad.append({"frame": name, "achse": "xy"[axis], "ziel_pivot": tp,
                                    "geliefert_pivot": round(delivered, 6),
                                    "versatz_px": round((delivered - 1.0) * size, 1),
                                    "art": "Kantenkonvention verletzt"})
            # Pixelanker: zulaessig ist der absolute Crusader-Anker, der eigene
            # SH1-Anker oder die Kantenregel. Nur was zu keinem passt, ist verdaechtig.
            devs = []
            for axis, (p_, size, tp, tsize, sp, ssize) in enumerate(
                    ((px, w, tpx, tw, spx, sw), (py, h, tpy, th, spy, sh))):
                anchor = p_ * size
                candidates = [tp * tsize, tp * size]
                if ssize:
                    candidates += [sp * ssize, sp * size]
                if abs(tp - 1.0) < 1e-6:
                    candidates.append(size)
                devs.append(min(abs(anchor - c) for c in candidates))
            if max(devs) > tolerance:
                bad.append({"frame": name, "versatz_px": [round(devs[0], 1), round(devs[1], 1)],
                            "art": "Pixelanker passt weder zu Crusader noch zu SH1"})
        if bad:
            worst = max(bad, key=lambda b: max(abs(v) for v in (b["versatz_px"] if isinstance(b["versatz_px"], list) else [b["versatz_px"]])))
            names = sorted({b["frame"] for b in bad}, key=katalog.frame_sort_key)
            results.append(finding(
                "anker", "fehler" if any(b["art"] == "Kantenkonvention verletzt" for b in bad) else "warnung", group,
                f"{len(names)} Frames mit verschobenem Anker (groesster Versatz {worst['versatz_px']} px, {worst['art']})",
                names[:200],
                f"asset_katalog.py uebernehmen {group} <frame> --quelle geliefert --modus fusspunkt  "
                "(oder --modus oben-links fuer Kantenanker)",
                {"einzelheiten": bad[:500]}))
    return results


def check_objekte(only: set[str] | None) -> list[dict]:
    from stronghold_europe_de.gm_atlas import frame_overrides_for

    results = []
    groups = [g for g in katalog.known_groups() if g.startswith("tile_")]
    for group in groups:
        if only and group.lower() not in only:
            continue
        rows = katalog.group_rows(group)
        overrides = {o.target_name: o.donor_name for o in frame_overrides_for(group)}
        if not overrides:
            continue
        # Umgelenkte Plaetze zu Clustern zusammenfassen (Luecke <= 4). Innerhalb
        # eines Clusters darf kein Platz mehr Crusader bleiben (Huetten-Fall), und
        # die Clustergroesse sollte ein Vielfaches ueblicher Grundrisse sein.
        actions = {katalog.frame_number(str(r["name"]))[0]: (str(r["name"]), r.get("action")) for r in rows
                   if not katalog.frame_number(str(r["name"]))[1]}
        redirected = sorted(katalog.frame_number(n)[0] for n, d in overrides.items() if d)
        clusters: list[list[int]] = []
        for index in redirected:
            if clusters and index - clusters[-1][-1] <= 4:
                clusters[-1].append(index)
            else:
                clusters.append([index])
        for cluster in clusters:
            lo, hi = cluster[0], cluster[-1]
            gaps = [actions[i][0] for i in range(lo, hi + 1) if i in actions and i not in cluster]
            if gaps:
                results.append(finding(
                    "objekte", "fehler", group,
                    f"Objekt {lo}-{hi}: {len(cluster)} Teile umgelenkt, {len(gaps)} dazwischen bleiben Crusader "
                    "(Huetten-Fall: europaeisches Haus auf arabischem Sockel) - ganzes Objekt umlenken",
                    gaps[:60],
                    f"asset_katalog.py umlenken {group} --ziel {lo}-{hi} --spender <Spenderbereich gleicher Laenge>",
                    {"umgelenkt": [actions[i][0] for i in cluster if i in actions], "luecken": gaps}))
            elif not any(len(cluster) % f == 0 for f in (16, 9, 25, 4, 36, 49, 64, 81, 100, 121)) and len(cluster) > 1:
                results.append(finding(
                    "objekte", "warnung", group,
                    f"Umgelenkter Block {lo}-{hi} hat {len(cluster)} Teile - kein Vielfaches ueblicher Grundrisse (4/9/16/25...)",
                    [actions[lo][0]] if lo in actions else []))
    return results


def check_umlenkungen(only: set[str] | None, sheets: bool) -> list[dict]:
    from stronghold_europe_de.gm_atlas import FRAME_OVERRIDES_139

    results = []
    review = katalog.load_json(PROJECT_ROOT / "config" / "umlenkungen-pruefung.json", {"geprueft": {}}).get("geprueft", {})
    for group, overrides in sorted(FRAME_OVERRIDES_139.items()):
        if only and group.lower() not in only:
            continue
        redirects = [o for o in overrides if o.donor_name]
        if not redirects:
            continue
        # zusammenhaengende Zielbloecke
        blocks: list[list] = []
        for o in sorted(redirects, key=lambda o: katalog.frame_sort_key(o.target_name)):
            ti = katalog.frame_number(o.target_name)[0]
            if blocks and ti == katalog.frame_number(blocks[-1][-1].target_name)[0] + 1:
                blocks[-1].append(o)
            else:
                blocks.append([o])
        for block in blocks:
            key = f"{group}:{block[0].target_name}"
            status = review.get(key)
            sheet = None
            if sheets:
                sheet = render_pair_sheet(group, block)
            results.append(finding(
                "umlenkungen", "info" if status == "ok" else "warnung", group,
                f"{block[0].target_name} .. {block[-1].target_name} <- {block[0].donor_name} .. {block[-1].donor_name} "
                f"({len(block)} Frames) - {'geprueft' if status == 'ok' else 'Spender-Identitaet ungeprueft'}: {block[0].reason[:90]}",
                [o.target_name for o in block],
                "Gegenueberstellung ansehen und als geprueft markieren (grafik_diagnose.py geprueft ...)",
                {"bild": str(sheet) if sheet else None, "schluessel": key}))
    return results


def render_pair_sheet(group: str, block) -> Path | None:
    from PIL import Image, ImageDraw

    try:
        katalog.ensure_side(group, "crusader")
        katalog.ensure_side(group, "stronghold1")
    except SystemExit:
        return None
    cru, sh1 = katalog.side_dir("crusader", group), katalog.side_dir("stronghold1", group)
    pairs = []
    for o in block[:36]:
        a, b = cru / f"{o.target_name}.png", sh1 / f"{o.donor_name}.png"
        pairs.append((Image.open(a).convert("RGBA") if a.is_file() else None,
                      Image.open(b).convert("RGBA") if b.is_file() else None, o))
    if not pairs:
        return None
    cell_w = max(max((p[0].width if p[0] else 0), (p[1].width if p[1] else 0)) for p in pairs) + 8
    cell_h = max(max((p[0].height if p[0] else 0), (p[1].height if p[1] else 0)) for p in pairs) + 22
    cols = min(8, len(pairs))
    rows = (len(pairs) + cols - 1) // cols
    sheet = Image.new("RGBA", (cols * cell_w, rows * cell_h * 2 + 20), (45, 45, 45, 255))
    draw = ImageDraw.Draw(sheet)
    draw.text((4, 2), f"{group}: oben Crusader-Ziel, unten SH1-Spender", fill=(255, 220, 120, 255))
    for i, (a, b, o) in enumerate(pairs):
        x, y = (i % cols) * cell_w, 20 + (i // cols) * cell_h * 2
        for image, offset, label in ((a, 0, o.target_name), (b, cell_h, o.donor_name)):
            if image is not None:
                sheet.alpha_composite(image, (x + 4, y + offset + cell_h - image.height - 4))
            draw.text((x + 2, y + offset + 2), label.split(" ")[-1].split("-")[-1], fill=(200, 200, 200, 255))
    target = OUT / "umlenkungen" / f"{katalog.slug(group)}-{katalog.slug(block[0].target_name)}.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(target)
    return target


def check_drift(profile: Path) -> list[dict]:
    data = katalog.load_json(profile, {"gm_atlases": []})
    counts: dict[str, dict] = defaultdict(lambda: {"frames": 0, "keep": 0, "max": -1})
    for row in katalog.mapping().get("sprites", []):
        c = counts[str(row.get("group")).casefold()]
        c["frames"] += 1
        c["keep"] += row.get("action") == "KEEP_CRUSADER"
        c["max"] = max(c["max"], katalog.frame_number(str(row.get("name")))[0])
    results = []
    for atlas in data.get("gm_atlases", []):
        group = str(atlas.get("gm_file_name"))
        c = counts.get(group.casefold())
        if c is None:
            results.append(finding("drift", "warnung", group, "Gruppe fehlt im Mapping des Zielspiels"))
            continue
        expected = atlas.get("expected_frame_count")
        if expected is not None and expected != c["frames"]:
            results.append(finding(
                "drift", "warnung", group,
                f"Zielspiel hat {c['frames']} Frames, Profil erwartet {expected} (anderer Spielstand?)",
                fix="Nachsichtbau laufen lassen, dann 'Nachweise uebernehmen' (pin_digests.py --aus-protokoll)",
                data={"ist": c["frames"], "soll": expected}))
    return results


def check_leinwand(mod: Path, only: set[str] | None) -> list[dict]:
    import numpy as np
    import UnityPy

    results = []
    for entry in delivered_groups(mod):
        group = str(entry.get("group"))
        if only and group.lower() not in only:
            continue
        env = UnityPy.load(str(mod / entry["bundle_path"]))
        atlas, textures = None, {}
        for obj in env.objects:
            if obj.type.name == "TextAsset":
                script = obj.read().m_Script
                if isinstance(script, (bytes, bytearray)):
                    script = bytes(script).decode("utf-8")
                try:
                    atlas = json.loads(script)
                except ValueError:
                    pass
            elif obj.type.name == "Texture2D":
                data = obj.read()
                textures[str(data.m_Name)] = np.asarray(data.image.convert("RGBA"))
        if atlas is None or not textures:
            continue
        empty = []
        page_main = {}
        for page in atlas.get("pages", []):
            wanted = Path((page.get("main") or {}).get("asset_path", "")).stem
            page_main[page["id"]] = next((t for n, t in textures.items() if n == wanted or n.endswith(wanted)),
                                         next(iter(textures.values())))
            if page.get("width", 0) % 4 or page.get("height", 0) % 4:
                results.append(finding("leinwand", "warnung", group,
                                       f"Seite {page['id']} {page.get('width')}x{page.get('height')} ist kein Vielfaches von 4 "
                                       "- Unity faellt dann still auf RGBA32 zurueck (Speicher!)"))
        for frame in atlas.get("frames", []):
            pixels = page_main.get(frame.get("page", 0))
            if pixels is None:
                continue
            r = frame["rect"]
            height = pixels.shape[0]
            crop = pixels[height - (r["y"] + r["height"]):height - r["y"], r["x"]:r["x"] + r["width"], 3]
            if crop.size and int(crop.max()) == 0:
                empty.append(str(frame.get("name")))
        if empty:
            results.append(finding("leinwand", "info", group,
                                   f"{len(empty)} vollstaendig transparente Frames (gewollt z.B. bei anim_castle 128-138; sonst pruefen)",
                                   empty[:200]))
    return results


def check_bundles(mod: Path) -> list[dict]:
    index_path = mod / "Runtime" / "AssetBundles" / "index.json"
    index = katalog.load_json(index_path, None)
    if index is None:
        return [finding("bundles", "warnung", "-", f"kein index.json unter {index_path}")]
    bad = []
    for group in index.get("groups", []):
        path = mod / group["bundle_path"]
        if not path.is_file():
            bad.append((group["bundle"], "fehlt"))
            continue
        data = path.read_bytes()
        problems = []
        if len(data) != group["bundle_size_bytes"]:
            problems.append("Groesse")
        if hashlib.sha256(data).hexdigest() != group["bundle_sha256"]:
            problems.append("SHA-256")
        if f"{zlib.crc32(data) & 0xFFFFFFFF:08x}" != group["bundle_crc32"]:
            problems.append("CRC32")
        if problems:
            bad.append((group["bundle"], ", ".join(problems)))
    if not bad:
        return [finding("bundles", "info", "-", f"{len(index.get('groups', []))} Bundles stimmen mit index.json ueberein")]
    return [finding("bundles", "fehler", name, f"Bundle weicht ab: {what}") for name, what in bad]


# ------------------------------------------------------------------ main

def resolve_mod(value: str | None) -> Path | None:
    if value:
        return Path(value)
    return katalog.default_mod_dir()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("pruefung", choices=("anker", "objekte", "umlenkungen", "drift", "leinwand", "bundles", "alles"))
    parser.add_argument("--mod", help="ausgelieferter Modordner (Standard: Zielspiel, sonst neuester Bau)")
    parser.add_argument("--gruppen", help="nur diese Gruppen, kommagetrennt")
    parser.add_argument("--profil", default="profiles/europe-production-bc7-v2.json")
    parser.add_argument("--toleranz", type=float, default=1.5, help="erlaubter Ankerversatz in Pixeln")
    parser.add_argument("--bilder", action="store_true", help="Gegenueberstellungen fuer Umlenkungen zeichnen")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    only = {g.strip().lower() for g in args.gruppen.split(",")} if args.gruppen else None
    mod = resolve_mod(args.mod)
    needs_mod = args.pruefung in ("anker", "leinwand", "bundles", "alles")
    if needs_mod and mod is None:
        say("Hinweis: kein ausgelieferter Stand gefunden - Pruefungen am Bundle werden uebersprungen.")
    results: list[dict] = []
    todo = ("anker", "objekte", "umlenkungen", "drift", "leinwand", "bundles") if args.pruefung == "alles" else (args.pruefung,)
    for name in todo:
        say(f"== {name}")
        try:
            if name == "anker" and mod:
                results += check_anker(mod, only, args.toleranz)
            elif name == "objekte":
                results += check_objekte(only)
            elif name == "umlenkungen":
                results += check_umlenkungen(only, args.bilder)
            elif name == "drift":
                results += check_drift(PROJECT_ROOT / args.profil)
            elif name == "leinwand" and mod:
                results += check_leinwand(mod, only)
            elif name == "bundles" and mod:
                results += check_bundles(mod)
        except Exception as exc:  # Nachsicht: eine gescheiterte Pruefung stoppt die anderen nicht
            results.append(finding(name, "warnung", "-", f"Pruefung konnte nicht laufen: {exc}"))
    OUT.mkdir(parents=True, exist_ok=True)
    report = {"mod": str(mod) if mod else None, "befunde": results}
    (OUT / "bericht.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    if args.json:
        print(json.dumps(report, ensure_ascii=False))
        return 0
    order = {"fehler": 0, "warnung": 1, "info": 2}
    for item in sorted(results, key=lambda r: (order.get(r["schwere"], 3), r["pruefung"], r["gruppe"])):
        say(f"[{item['schwere'].upper():7}] {item['pruefung']:<11} {item['gruppe']:<22} {item['text']}")
        if item["behebung"]:
            say(f"           -> {item['behebung']}")
    counts = defaultdict(int)
    for item in results:
        counts[item["schwere"]] += 1
    say(f"Bericht: {OUT / 'bericht.json'}  ({dict(counts)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

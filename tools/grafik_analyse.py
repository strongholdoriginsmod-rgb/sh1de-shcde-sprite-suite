"""Grafik-Analyse: ausgelieferte Atlanten prüfen und Spielbilder zuordnen.

Fasst die Einzelskripte aus dem Hütten-Fall (September 2026) zu einem
Werkzeug zusammen. Nichts hiervon verändert Profile oder Installationen;
es wird nur gelesen und nach --out geschrieben.

    python tools/grafik_analyse.py bundles-pruefen --plugin <Mod-Ordner>
    python tools/grafik_analyse.py bundle-export --bundle <sede.gm.X.bc7.v2> --out <Ordner>
    python tools/grafik_analyse.py finden --bild <Foto.png> --frames <Ordner> [--bereich x0 y0 x1 y1]
    python tools/grafik_analyse.py zensus --bundle <...> --crusader <Ordner> --sh1 <Ordner>
    python tools/grafik_analyse.py vergleich --a <Ordner> --b <Ordner>

Erfahrungswerte: SHC:DE zeichnet im Editor 1:1, echte Treffer liegen bei
NCC >= 0,99. Große, teilweise verdeckte Frames erkennt man besser mit
--modus deckung. BC7 ist verlustbehaftet: Deckungswerte immer gegen eine
Kontrollgruppe bekannt guter Plätze lesen, nie gegen 1,0.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zlib
from collections import Counter
from pathlib import Path


def _frame_index(path: Path) -> int | None:
    try:
        return int(path.stem.rsplit(" ", 1)[1])
    except (IndexError, ValueError):
        return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


# ------------------------------------------------------------------ bundles

def load_bundle(bundle: Path):
    """Return {index: (rgba ndarray, frame meta)} from one sede.gm bundle."""
    import numpy as np
    import UnityPy

    env = UnityPy.load(str(bundle))
    atlas = texture = None
    for obj in env.objects:
        if obj.type.name == "TextAsset":
            script = obj.read().m_Script
            if isinstance(script, (bytes, bytearray)):
                script = bytes(script).decode("utf-8")
            atlas = json.loads(script)
        elif obj.type.name == "Texture2D":
            texture = np.asarray(obj.read().image.convert("RGBA"))
    if atlas is None or texture is None:
        raise SystemExit(f"Fehler: {bundle.name} enthält keinen atlas.v3 oder keine Textur")
    height = texture.shape[0]
    frames = {}
    for frame in atlas["frames"]:
        r = frame["rect"]
        # Unity-Texturen liegen y-von-unten.
        top = height - (r["y"] + r["height"])
        frames[int(frame["index"])] = (
            texture[top:height - r["y"], r["x"]:r["x"] + r["width"]],
            frame,
        )
    return frames, atlas


def cmd_bundles_pruefen(args) -> int:
    plugin = Path(args.plugin)
    index_path = plugin / "Runtime" / "AssetBundles" / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    print(f"index.json  sha256={_sha256(index_path)}")
    bad = 0
    for group in index["groups"]:
        path = plugin / group["bundle_path"]
        if not path.is_file():
            print(f"FEHLT   {group['bundle']}")
            bad += 1
            continue
        data = path.read_bytes()
        problems = []
        if len(data) != group["bundle_size_bytes"]:
            problems.append("Größe")
        if hashlib.sha256(data).hexdigest() != group["bundle_sha256"]:
            problems.append("SHA-256")
        if f"{zlib.crc32(data) & 0xFFFFFFFF:08x}" != group["bundle_crc32"]:
            problems.append("CRC32")
        if problems:
            bad += 1
            print(f"FEHLER  {group['bundle']}: {', '.join(problems)}")
    print(f"{len(index['groups'])} Bundles geprüft, {bad} Abweichungen")
    if bad == 0:
        print("erfolgreich")
    return 1 if bad else 0


def cmd_bundle_export(args) -> int:
    from PIL import Image

    bundle = Path(args.bundle)
    frames, atlas = load_bundle(bundle)
    group = args.group or atlas.get("group") or bundle.name.split(".")[2]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for index, (pixels, meta) in sorted(frames.items()):
        Image.fromarray(pixels).save(out / f"{group} {index:03d}.png")
    (out / "atlas.v3.json").write_text(json.dumps(atlas, indent=1), encoding="utf-8")
    print(f"{len(frames)} Frames aus {bundle.name} nach {out} geschrieben")
    return 0


# ------------------------------------------------------------------ finden

def _gray(rgb):
    return rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114


def _frames_in(directory: Path, lo: int, hi: int):
    for path in sorted(directory.glob("*.png")):
        index = _frame_index(path)
        if index is not None and lo <= index <= hi:
            yield index, path


def cmd_finden(args) -> int:
    import numpy as np
    from PIL import Image
    from scipy.signal import fftconvolve

    shot = np.asarray(Image.open(args.bild).convert("RGB"), dtype=np.float64)
    x0, y0, x1, y1 = args.bereich or (0, 0, shot.shape[1], shot.shape[0])
    region = shot[y0:y1, x0:x1]
    results = []
    for index, path in _frames_in(Path(args.frames), args.von, args.bis):
        image = np.asarray(Image.open(path).convert("RGBA"), dtype=np.float64)
        h, w = image.shape[:2]
        if h > region.shape[0] or w > region.shape[1]:
            continue
        mask = (image[..., 3] > 200).astype(np.float64)
        n = mask.sum()
        if n < args.min_pixel:
            continue
        if args.modus == "ncc":
            S = _gray(region)
            T = _gray(image[..., :3])
            Tc = (T - (T * mask).sum() / n) * mask
            denom = np.sqrt((Tc * Tc).sum())
            if denom < 1e-6:
                continue
            flipped = mask[::-1, ::-1]
            num = fftconvolve(S, Tc[::-1, ::-1], mode="valid")
            sum_s = fftconvolve(S, flipped, mode="valid")
            sum_s2 = fftconvolve(S * S, flipped, mode="valid")
            var = np.maximum(sum_s2 - sum_s * sum_s / n, 1e-9)
            score = num / (np.sqrt(var) * denom)
            k = int(np.argmax(score))
            yy, xx = np.unravel_index(k, score.shape)
            results.append((float(score[yy, xx]), index, xx + x0, yy + y0, w, h, int(n), None))
        else:
            T = image[..., :3] * mask[..., None]
            ssd = np.zeros((region.shape[0] - h + 1, region.shape[1] - w + 1))
            for c in range(3):
                ssd += fftconvolve(region[..., c] ** 2, mask[::-1, ::-1], mode="valid")
                ssd += (T[..., c] ** 2).sum()
                ssd -= 2 * fftconvolve(region[..., c], T[::-1, ::-1, c], mode="valid")
            k = int(np.argmin(ssd))
            yy, xx = np.unravel_index(k, ssd.shape)
            sub = region[yy:yy + h, xx:xx + w]
            dmax = np.abs(sub - image[..., :3]).max(axis=2)
            cover = float((dmax[mask > 0] <= args.toleranz).mean())
            rmse = float(np.sqrt(max(ssd[yy, xx], 0) / (3 * n)))
            results.append((cover, index, xx + x0, yy + y0, w, h, int(n), rmse))
    results.sort(key=lambda r: r[0], reverse=True)
    label = "NCC" if args.modus == "ncc" else "Deckung"
    for score, index, x, y, w, h, n, rmse in results[: args.anzahl]:
        extra = f"  RMSE={rmse:6.2f}" if rmse is not None else ""
        print(f"{label}={score:.4f}  Frame {index:>5}  Lage=({x},{y})  {w}x{h}  px={n}{extra}")
    if not results:
        print("keine passenden Frames (Bereich zu klein oder Ordner leer?)")
    return 0


# ------------------------------------------------------------------ zensus

def cmd_zensus(args) -> int:
    import numpy as np
    from PIL import Image

    def load_dir(directory):
        out = {}
        if directory and Path(directory).is_dir():
            for path in Path(directory).glob("*.png"):
                index = _frame_index(path)
                if index is not None:
                    out[index] = np.asarray(Image.open(path).convert("RGBA")).astype(int)
        return out

    def agree(a, b, tol=16):
        if b is None or a.shape != b.shape:
            return None
        mask = (a[..., 3] > 250) | (b[..., 3] > 250)
        if mask.sum() == 0:
            return 1.0
        return float((np.abs(a - b).max(axis=2)[mask] <= tol).mean())

    frames, _ = load_bundle(Path(args.bundle))
    crusader, sh1 = load_dir(args.crusader), load_dir(args.sh1)
    rows = []
    for index, (pixels, _) in sorted(frames.items()):
        pixels = pixels.astype(int)
        a_cru, a_sh1 = agree(pixels, crusader.get(index)), agree(pixels, sh1.get(index))
        if a_sh1 is not None and a_sh1 >= args.schwelle:
            kind = "EU"
        elif a_cru is not None and a_cru >= args.schwelle:
            kind = "CRU"
        else:
            kind = "?"
        rows.append((index, kind, a_cru, a_sh1, pixels.shape[:2]))
    print(f"{Path(args.bundle).name}: {len(rows)} Plätze")
    for kind, count in Counter(r[1] for r in rows).most_common():
        print(f"  {kind:>3}: {count}")
    print("\nPlätze ohne eindeutige Herkunft (umgelenkt oder fremde Leinwand):")
    for index, kind, a_cru, a_sh1, shape in rows:
        if kind == "?":
            print(f"  {index:5d}  Form={shape}  zu_Crusader={a_cru}  zu_SH1={a_sh1}")
    return 0


# ------------------------------------------------------------------ vergleich

def cmd_vergleich(args) -> int:
    def collect(root: Path):
        return {p.relative_to(root).as_posix(): p for p in root.rglob("*") if p.is_file()}

    a, b = collect(Path(args.a)), collect(Path(args.b))
    changed = only_a = only_b = 0
    for name in sorted(a.keys() | b.keys()):
        if name not in b:
            only_a += 1
            print(f"nur A    {name}")
        elif name not in a:
            only_b += 1
            print(f"nur B    {name}")
        elif a[name].stat().st_size != b[name].stat().st_size or _sha256(a[name]) != _sha256(b[name]):
            changed += 1
            print(f"anders   {name}")
    print(f"{len(a)} / {len(b)} Dateien: {changed} anders, {only_a} nur A, {only_b} nur B")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("bundles-pruefen", help="alle Bundles gegen index.json prüfen")
    p.add_argument("--plugin", required=True, help="Ordner StrongholdEuropeDE (Mod)")
    p.set_defaults(func=cmd_bundles_pruefen)

    p = sub.add_parser("bundle-export", help="Frames eines Bundles als PNG ausgeben")
    p.add_argument("--bundle", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--group")
    p.set_defaults(func=cmd_bundle_export)

    p = sub.add_parser("finden", help="exportierte Frames in einem Spielbild suchen")
    p.add_argument("--bild", required=True)
    p.add_argument("--frames", required=True)
    p.add_argument("--bereich", type=int, nargs=4, metavar=("X0", "Y0", "X1", "Y1"))
    p.add_argument("--von", type=int, default=0)
    p.add_argument("--bis", type=int, default=10**9)
    p.add_argument("--modus", choices=("ncc", "deckung"), default="ncc")
    p.add_argument("--toleranz", type=float, default=12.0)
    p.add_argument("--min-pixel", type=int, default=300)
    p.add_argument("--anzahl", type=int, default=15)
    p.set_defaults(func=cmd_finden)

    p = sub.add_parser("zensus", help="jeden Platz eines Bundles einer Quelle zuordnen")
    p.add_argument("--bundle", required=True)
    p.add_argument("--crusader", help="Export des Crusader-Originals")
    p.add_argument("--sh1", help="Export des Stronghold-1-Spenders")
    p.add_argument("--schwelle", type=float, default=0.90)
    p.set_defaults(func=cmd_zensus)

    p = sub.add_parser("vergleich", help="zwei Mod-Ordner Datei für Datei vergleichen")
    p.add_argument("--a", required=True)
    p.add_argument("--b", required=True)
    p.set_defaults(func=cmd_vergleich)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

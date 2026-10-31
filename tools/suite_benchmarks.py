"""Deterministic synthetic preview performance sample (no user artwork)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

from PIL import Image
from suite_preview_render import checkerboard, preview_dimensions


def measure(*, side: int, repeats: int) -> dict:
    if not isinstance(side,int) or not 1<=side<=4096:
        raise ValueError("Image side must be 1..4096 pixels")
    if not isinstance(repeats,int) or not 1<=repeats<=10:
        raise ValueError("Repetitions must be 1..10")
    source=Image.new("RGBA",(side,side),(98,165,182,180))
    size,capped=preview_dimensions(source.size,4.0)
    timings=[]
    for _ in range(repeats):
        start=time.perf_counter()
        result=checkerboard(source,size)
        assert result.size==size and result.mode=="RGB"
        timings.append(round((time.perf_counter()-start)*1000,2))
    return {
        "source_pixels":side*side,
        "display_pixels":size[0]*size[1],
        "display_limited":capped,
        "render_milliseconds":timings,
        "measured_peak_process_rss":"not-measured",
    }


def main(argv: list[str] | None = None) -> int:
    parser=argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sides",nargs="+",type=int,default=[256,1024,2048])
    parser.add_argument("--repeats",type=int,default=2)
    parser.add_argument("--output",type=Path,help="Optional NEW JSON file (never overwrite)")
    args=parser.parse_args(argv)
    results=[measure(side=side,repeats=args.repeats) for side in args.sides]
    document={"schema":"spritesuite.synthetic-preview-benchmark.v1",
              "game_assets_used":False,"measurements":results}
    text=json.dumps(document,indent=2)+"\n"
    if args.output is not None:
        if args.output.suffix.lower()!=".json" or not args.output.parent.is_dir():
            parser.error("Please choose a new JSON file in an existing folder")
        with args.output.open("x",encoding="utf8") as opened:
            opened.write(text)
    print(text)
    return 0


if __name__=="__main__":
    raise SystemExit(main())

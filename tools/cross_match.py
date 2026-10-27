"""Find the best European stand-in for a Crusader group, ignoring names.

The conversion pipeline matches groups by name. That is the safe default and it
is why `Tree_Oak` fails: Crusader redrew its oak, so the same-named Stronghold 1
group no longer fits the target canvas.

An aggressive conversion does not have to accept that. Nothing in the loader
cares which source pixels fill a target slot — only that the frame fits the
target canvas at the pivot-aligned offset. So for every target group we can ask a
different question: *which Stronghold 1 group fits best, whatever it is called?*

This is a metadata-only prefilter. For each candidate pairing it reports the
fraction of target frames whose source counterpart fits without clipping the
canvas, using the same absolute-pivot arithmetic as `DERIVED_GEOMETRY_POLICY.md`.
It decodes no pixels, so it is cheap enough to score every pairing. A promising
pair still needs the real alpha proof from `map geometry-audit`.

Usage::

    python tools/cross_match.py Tree_Oak body_deer
    python tools/cross_match.py Tree_Oak --top 10
    python tools/cross_match.py --category vegetation
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from stronghold_europe_de.mapping import _group_name  # noqa: E402
from stronghold_europe_de.unity_inventory import read_inventory  # noqa: E402

INVENTORY = REPO_ROOT / "work" / "inventory"


def group_frames(inventory: dict) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for sprite in inventory["sprites"]:
        grouped.setdefault(_group_name(str(sprite["name"])), []).append(sprite)
    return grouped


def geometry(sprite: dict) -> tuple[float, float, float, float]:
    width = float(sprite["width"])
    height = float(sprite["height"])
    return width, height, float(sprite["pivot_x"]) * width, float(sprite["pivot_y"]) * height


def fit_score(source: list[dict], target: list[dict]) -> dict:
    """Fraction of target frames a source frame can occupy without clipping.

    Frames are paired by position after sorting on slot order, which is how an
    animation set lines up when the names differ. A source frame fits when, after
    aligning absolute pivots, its rectangle stays inside the target canvas.
    """

    pairs = min(len(source), len(target))
    if pairs == 0:
        return {"pairs": 0, "fits": 0, "share": 0.0, "median_slack": 0.0}

    fits = 0
    slack: list[float] = []
    for index in range(pairs):
        sw, sh, spx, spy = geometry(source[index])
        tw, th, tpx, tpy = geometry(target[index])
        left = tpx - spx
        bottom = tpy - spy
        if left >= -0.001 and bottom >= -0.001 and left + sw <= tw + 0.001 and bottom + sh <= th + 0.001:
            fits += 1
            slack.append(min(tw - sw, th - sh))
    slack.sort()
    median = slack[len(slack) // 2] if slack else 0.0
    return {
        "pairs": pairs,
        "fits": fits,
        "share": fits / pairs,
        "median_slack": median,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("targets", nargs="*", help="Crusader group names to find a stand-in for")
    parser.add_argument("--top", type=int, default=8, help="candidates to list per target")
    parser.add_argument(
        "--min-frames",
        type=int,
        default=0,
        help="ignore source groups with fewer frames than this",
    )
    parser.add_argument(
        "--like",
        action="append",
        default=[],
        help="only consider source groups containing this substring; repeatable. "
        "Without it the ranking is geometry-only and will happily propose a "
        "knight torso for an oak tree — supply the semantics yourself.",
    )
    args = parser.parse_args(argv)

    if not args.like:
        print(
            "Hinweis: ohne --like rangiert nur die Geometrie. Die Vorschlaege "
            "koennen inhaltlich unsinnig sein.\n",
            file=sys.stderr,
        )

    source = group_frames(read_inventory(INVENTORY / "source.resources.json.gz"))
    target = group_frames(read_inventory(INVENTORY / "target.resources.json.gz"))

    for name in args.targets:
        frames = target.get(name)
        if not frames:
            print(f"\n{name}: not a Crusader group")
            continue
        frames = sorted(frames, key=lambda s: str(s["name"]))
        print(f"\n=== {name}  ({len(frames)} Crusader frames) ===")
        print(f"{'Kandidat aus SH1DE':<28}{'Frames':>8}{'Paare':>7}{'passt':>8}{'Anteil':>9}  Reserve")
        print("-" * 78)

        scored = []
        for candidate, source_frames in source.items():
            if len(source_frames) < args.min_frames:
                continue
            if args.like and not any(
                needle.casefold() in candidate.casefold() for needle in args.like
            ):
                continue
            ordered = sorted(source_frames, key=lambda s: str(s["name"]))
            result = fit_score(ordered, frames)
            if result["pairs"] == 0:
                continue
            coverage = result["pairs"] / len(frames)
            scored.append((result["share"] * coverage, candidate, len(source_frames), result))

        scored.sort(reverse=True)
        for _rank, candidate, count, result in scored[: args.top]:
            marker = "  <- gleichnamig" if candidate == name else ""
            print(
                f"{candidate:<28}{count:>8}{result['pairs']:>7}{result['fits']:>8}"
                f"{100 * result['share']:>8.0f}%  {result['median_slack']:>5.0f}px{marker}"
            )
        if not scored:
            print("  keine Kandidaten")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

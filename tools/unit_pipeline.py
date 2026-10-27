"""Reusable production CLI for wholly new animated unit artwork.

One JSON manifest is the only unit-specific input.  The same commands are used
for the European slinger and the planned follow-up units:

    python tools/unit_pipeline.py spec-check --spec config/unit-production/european-slinger.json
    python tools/unit_pipeline.py prototype --spec ... --from work/export --out work/prototype
    python tools/unit_pipeline.py build --spec ... --from work/export --out work/complete
    python tools/unit_pipeline.py sheet --spec ... --from work/export --rendered work/prototype --out review.png
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from stronghold_europe_de.unit_production import (  # noqa: E402
    UnitProductionError,
    build_comparison_sheet,
    build_unit_series,
    load_unit_spec,
    render_prototype,
)


DEFAULT_PROTOTYPE_SLOTS = (
    "0,3,7,128,131,135,512,515,519,640,643,647,744,747,751,"
    "900,903,907,1048,1051,1055,1104,1107,1111,1200,1203,1207,0x,3x,7x"
)


def _frame_names(group: str, slots: str) -> list[str]:
    result: list[str] = []
    for raw in slots.split(","):
        suffix = raw.strip()
        if not suffix:
            continue
        if not suffix.removesuffix("x").isdigit():
            raise UnitProductionError(f"Invalid frame slot {suffix!r}")
        result.append(f"{group}-{suffix}")
    if not result or len(result) != len(set(result)):
        raise UnitProductionError("Prototype slots must be non-empty and unique")
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Retarget game motion onto a newly rendered manifest-defined unit; "
            "donor RGB is never used."
        )
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("spec-check", "prototype", "build", "sheet"):
        command = sub.add_parser(name)
        command.add_argument("--spec", type=Path, required=True)
        if name != "spec-check":
            command.add_argument("--from", dest="source", type=Path, required=True)
        if name in {"prototype", "build"}:
            command.add_argument("--out", type=Path, required=True)
        if name in {"prototype", "sheet"}:
            command.add_argument("--slots", default=DEFAULT_PROTOTYPE_SLOTS)
        if name == "sheet":
            command.add_argument("--rendered", type=Path, required=True)
            command.add_argument("--out", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        spec = load_unit_spec(args.spec, project_root=PROJECT_ROOT)
        if args.command == "spec-check":
            print(
                json.dumps(
                    {
                        "unit_id": spec.unit_id,
                        "group": spec.group,
                        "frames": spec.expected_frames,
                        "reference": spec.reference_path.as_posix(),
                        "reference_sha256": spec.reference_sha256,
                        "renderer": "articulated-reference-v1",
                        "donor_rgb_used": False,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        frame_names = (
            _frame_names(spec.group, args.slots)
            if args.command in {"prototype", "sheet"}
            else []
        )
        if args.command == "prototype":
            stats = render_prototype(
                args.source.resolve(), args.out.resolve(), spec, frame_names
            )
            print(json.dumps([asdict(item) for item in stats], indent=2))
            return 0
        if args.command == "sheet":
            build_comparison_sheet(
                args.source.resolve(),
                args.rendered.resolve(),
                args.out.resolve(),
                spec,
                frame_names,
            )
            print(f"Vergleichstafel: {args.out.resolve()}")
            return 0
        report = build_unit_series(args.source.resolve(), args.out.resolve(), spec)
        print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
        return 0
    except UnitProductionError as exc:
        print(f"Einheitenproduktion abgelehnt: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

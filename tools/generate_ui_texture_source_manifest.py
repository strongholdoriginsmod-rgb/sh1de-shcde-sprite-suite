from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

from PIL import Image, UnidentifiedImageError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from stronghold_europe_de import ui_asset_bundle as uiab  # noqa: E402


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _entry(
    path: Path,
    *,
    noesis_path: str,
    source_kind: str,
    source: str,
    namespace: str,
) -> dict[str, object]:
    try:
        with Image.open(path) as image:
            image.load()
            if image.format != "PNG" or image.mode != "RGBA":
                raise ValueError("not an explicit RGBA PNG")
            width, height = image.size
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        raise SystemExit(f"Unsupported UI source {path}: {exc}") from exc
    path_hash = sha256(noesis_path.encode("utf-8")).hexdigest()[:16]
    return {
        "bundle": "per_entry_v1",
        "expected_source_sha256": _sha256_file(path),
        # Match both the source game's imported GUI textures and SHCDE-SE's
        # historical PNG loader.  Both expose UI images with bilinear sampling.
        "filter_mode": "Bilinear",
        "height": height,
        "id": f"{namespace}-{path_hash}",
        "noesis_path": noesis_path,
        "source": source,
        "source_kind": source_kind,
        "width": width,
    }


def build_manifest(mod_root: Path, campaign_root: Path) -> dict[str, object]:
    workspace = PROJECT_ROOT.resolve(strict=True)
    mod = mod_root.resolve(strict=True)
    campaign = campaign_root.resolve(strict=True)
    expected_campaign = (
        workspace
        / "work/private-inputs/stronghold-europa-kampagnen"
        / "Override/Assets/GUI/Images"
    ).resolve(strict=True)
    if campaign != expected_campaign:
        raise SystemExit(
            "Campaign input must be the canonical private work copy: "
            + str(expected_campaign)
        )

    gui_root = mod / "Override/Assets/GUI"
    europe_files = sorted(
        (path for path in gui_root.rglob("*.png") if path.is_file()),
        key=lambda path: path.relative_to(mod).as_posix(),
    )
    campaign_files = sorted(campaign.glob("*.png"), key=lambda path: path.name)
    if len(europe_files) != 9:
        raise SystemExit(f"Expected exactly 9 Europe UI PNGs, found {len(europe_files)}")
    if len(campaign_files) != 105:
        raise SystemExit(
            f"Expected exactly 105 campaign UI PNGs, found {len(campaign_files)}"
        )

    rows: list[dict[str, object]] = []
    for path in europe_files:
        relative = path.relative_to(mod).as_posix()
        if not relative.startswith("Override/Assets/GUI/"):
            raise SystemExit(f"Europe UI path escaped the exact root: {relative}")
        noesis = relative.removeprefix("Override/")
        rows.append(
            _entry(
                path,
                noesis_path=noesis,
                source_kind="profile_output",
                source=relative,
                namespace="europe",
            )
        )
    private_prefix = (
        "work/private-inputs/stronghold-europa-kampagnen/"
        "Override/Assets/GUI/Images"
    )
    for path in campaign_files:
        rows.append(
            _entry(
                path,
                noesis_path=f"Assets/GUI/Images/{path.name}",
                source_kind="private_work_file",
                source=f"{private_prefix}/{path.name}",
                namespace="campaign",
            )
        )
    rows.sort(key=lambda row: str(row["id"]))
    identity = [
        {"id": row["id"], "noesis_path": row["noesis_path"]}
        for row in rows
    ]
    return {
        "alpha_mode": uiab.ALPHA_MODE,
        "entries": rows,
        "expected_entry_count": len(rows),
        "expected_entry_set_sha256": sha256(
            json.dumps(
                identity,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        "schema": uiab.SOURCE_SCHEMA,
        "texture_contract": {
            "alpha_is_transparency": False,
            "aniso_level": 0,
            "bc_block_padding": uiab.BLOCK_PADDING_MODE,
            "compression": "BC7-HQ100-force-maximum",
            "format": "BC7",
            "mipmaps": False,
            "npot_scale": "None",
            "readable": False,
            "s_rgb": True,
            "wrap_mode": "Clamp",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate the pinned 114-entry private UI BC7 source manifest."
    )
    parser.add_argument("--mod-root", type=Path, required=True)
    parser.add_argument("--campaign-root", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "config/ui-textures-bc7-v1.json",
    )
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    manifest = build_manifest(args.mod_root, args.campaign_root)
    payload = json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    ).encode("utf-8") + b"\n"
    output = args.output.resolve()
    if not args.write:
        print(
            f"Would write {len(manifest['entries'])} entries to {output}; "
            f"sha256={sha256(payload).hexdigest()}"
        )
        return 0
    if output != (PROJECT_ROOT / "config/ui-textures-bc7-v1.json").resolve():
        raise SystemExit("Output must be config/ui-textures-bc7-v1.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    if temporary.exists():
        raise SystemExit(f"Refusing to replace stale temporary file: {temporary}")
    temporary.write_bytes(payload)
    temporary.replace(output)
    print(
        f"Wrote {len(manifest['entries'])} entries to {output}; "
        f"sha256={sha256(payload).hexdigest()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

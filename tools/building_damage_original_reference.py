#!/usr/bin/env python3
"""Extract exact original SHCDE building sprite pixels and preview all orientations.

READS game resources.assets, the original pinned SpriteSuite mapping, and a
SHA-checked real SHCDE graphics audit log; never reads/modifies save state or
writes to the game installation. Creates a new exclusive export folder.
Eight isometric mappings are visual hypotheses, NOT gameplay renderer approval.
"""
from __future__ import annotations

import argparse
import gzip
import io
import hashlib
import json
import math
from pathlib import Path
import re
import sys

from building_damage_layer_audit import AuditError, analyze_events, parse_log_bytes

MAX_FRAMES = 128
MAX_FILE_BYTES = 200 * 1024 * 1024
MAX_MAPPING_DECOMPRESSED_BYTES = 128 * 1024 * 1024
SHCDESE_BUILDING_API_SHA256 = "5cb1c33be5463086505a17f5c48aaa357d733cfff7240e101c821f0e3c668498"
SHA = re.compile(r"^[a-f0-9]{64}$")
FRAME_NAME = re.compile(r"^(tile_buildings1|tile_buildings2|tile_goods) ([0-9]{1,4})$")

class OriginalImageError(ValueError):
    pass


def need(condition, message):
    if not condition:
        raise OriginalImageError(message)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def checked_bytes(path: Path, expected: str, *, limit: int | None = None) -> bytes:
    need(SHA.fullmatch(expected) is not None, "Explicit lowercase SHA-256 required.")
    need(path.is_file() and not path.is_symlink(),
         "Expected regular, non-symlink source file: " + str(path))
    if limit:
        need(path.stat().st_size <= limit, "Source file exceeds budget.")
    data = path.read_bytes()
    need(digest(data) == expected, "Source SHA-256 mismatch: " + str(path))
    return data


def verified_mapping(path: Path, expected: str) -> dict[str, dict]:
    compressed = checked_bytes(path, expected, limit=80*1024*1024)
    # Python gzip.decompress has no expansion budget; a signed compressed
    # mapping can otherwise allocate unbounded memory if its bytes change.
    # Enforce a strict cap even when parsing a pre-existing repository file.
    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as archive:
        expanded = archive.read(MAX_MAPPING_DECOMPRESSED_BYTES + 1)
    need(len(expanded) <= MAX_MAPPING_DECOMPRESSED_BYTES,
         "Decompressed sprite mapping exceeds 128 MiB limit.")
    data = json.loads(expanded.decode("utf-8"))
    need(data.get("target_build_id") ==
         "local-shcde-2.80-unity-2021.3.45f2",
         "Mapping belongs to another game build.")
    by_name = {}
    for row in data["sprites"]:
        name = row.get("name")
        if not isinstance(name, str) or not FRAME_NAME.fullmatch(name):
            continue
        if name in by_name:
            raise OriginalImageError("Duplicate sprite name: " + name)
        by_name[name] = row
    return by_name


def target_from_log(log: Path, log_sha: str, building_id: int,
                    global_id: int) -> tuple[dict, dict]:
    raw = checked_bytes(log, log_sha, limit=64*1024*1024)
    audit = analyze_events(parse_log_bytes(raw))
    matching = [b for b in audit["buildings"] if
                b["buildingId"] == building_id and b["globalId"] == global_id]
    need(len(matching) == 1, "Building ID/global ID absent or ambiguous.")
    building = matching[0]
    visual = building["graphicSlotCandidates"]
    need(visual["status"] == "complete_drawn_rectangle_orientation_unverified",
         "Real log does not contain a complete visual sprite grid.")
    need(1 <= visual["distinctGraphicTiles"] <= MAX_FRAMES and
         len(visual["hypotheses"]) in (1, 4, 8),
         "Unsafe or incomplete original sprite grid.")
    all_frames = building["drawingGraphics"]
    need(len(all_frames) == visual["distinctGraphicTiles"],
         "Graphic mapping includes duplicate draw events or missing grid cells.")
    need(all(FRAME_NAME.fullmatch(str(f["sprite"])) for f in all_frames),
         "This visual export requires known original tile sprite names.")
    return building, visual


def game_type_label(catalog: Path, expected_sha: str, game_type: int) -> str:
    """Verify numeric eStructs values against the pinned actual extender DLL."""
    data = json.loads(checked_bytes(catalog, expected_sha,
                                    limit=1024*1024).decode("utf-8"))
    need(data.get("format") == "spritesuite-shcdese-building-type-index" and
         data.get("version") == 1 and
         data.get("sourceDLLSHA256") == SHCDESE_BUILDING_API_SHA256 and
         data.get("enumType") == "SHCDESE.Interop.eStructs",
         "Building type catalog does not match the verified SHCDESE API.")
    values = data.get("values")
    need(isinstance(values, list) and 1 <= len(values) <= 4096,
         "Malformed native game building type enum.")
    matches = []
    for row in values:
        need(isinstance(row, dict) and type(row.get("value")) is int and
             type(row.get("name")) is str and
             re.fullmatch(r"STRUCT_[A-Z_0-9]{1,80}", row["name"]) is not None,
             "Invalid building type catalog entry.")
        if row["value"] == game_type:
            matches.append(row["name"])
    need(len(matches) == 1,
         "Missing or ambiguous real SHCDE building type: " + str(game_type))
    return matches[0]


def read_original_frames(asset_path: Path, selected: list[dict],
                         mapping: dict[str, dict]) -> dict[str, dict]:
    # Delay import so the offline tests can exercise geometry and security
    # without requiring UnityPy or the game installation.
    need(asset_path.is_file() and not asset_path.is_symlink() and
         asset_path.name == "resources.assets" and
         asset_path.stat().st_size <= MAX_FILE_BYTES,
         "Expected a bounded, non-symlink SHCDE resources.assets file.")
    by_id = {}
    for sprite in selected:
        name = sprite["sprite"]
        meta = mapping.get(name)
        need(meta is not None and isinstance(meta.get("target"), dict),
             "Original native sprite absent from pinned catalog: " + name)
        target = meta["target"]
        path_id = target.get("path_id")
        need(type(path_id) is int and path_id > 0,
             "Invalid native Sprite path ID.")
        need(path_id not in by_id or by_id[path_id] == name,
             "Multiple native sprite names reference the same Unity PathID.")
        by_id[path_id] = name
    need(len(by_id) <= MAX_FRAMES, "Original asset read budget exceeded.")

    import UnityPy
    env = UnityPy.load(str(asset_path))
    located = {}
    for obj in env.objects:
        if obj.path_id in by_id:
            need(obj.type.name == "Sprite", "Expected original Sprite in Unity archive.")
            loaded = obj.read()
            need(loaded.m_Name == by_id[obj.path_id],
                 "Unity sprite label does not match pinned mapping.")
            image = loaded.image.convert("RGBA")
            name = by_id[obj.path_id]
            meta = mapping[name]["target"]
            need(image.width == int(meta["width"]) and
                 image.height == int(meta["height"]) and
                 1 <= image.width <= 64 and 1 <= image.height <= 2048,
                 "Native sprite dimensions mismatch, or exceed budget: " + name)
            located[name] = {
                "image": image, "pathId": obj.path_id,
                "pivotX": float(meta["pivot_x"]),
                "pivotY": float(meta["pivot_y"]),
                "ppu": float(meta["pixels_per_unit"]),
                "nativeTexture": meta["texture_name"],
            }
    need(set(located) == set(by_id.values()),
         "Native assets incomplete for one or more drawn graphics.")
    return located


def visual_positions(a: int, b: int, tile_width=64, tile_height=32):
    result = []
    for diagonal in range(a + b - 1):
        for u in range(min(a - 1, diagonal),
                       max(0, diagonal - b + 1) - 1, -1):
            v = diagonal - u
            result.append({"u":u,"v":v,"x":(v-u)*tile_width//2,
                           "bottom": -diagonal * tile_height//2})
    return result


def composite_candidate(slots: list[dict], sprites: dict[str, dict],
                        tile_width: int = 64, tile_height: int = 32):
    from PIL import Image
    need(1 <= len(slots) <= MAX_FRAMES, "Invalid candidate slot count.")
    a, b = slots[0]["spriteA"], slots[0]["spriteB"]
    ps = visual_positions(a, b, tile_width, tile_height)
    need(len(ps) == len(slots), "Candidate size does not match grid.")
    frames = []
    for slot_index, row in enumerate(slots):
        image = sprites[row["sprite"]]["image"]
        metadata = sprites[row["sprite"]]
        pos = ps[slot_index]
        left = math.floor(pos["x"] - image.width * metadata["pivotX"] + .5)
        top = math.floor(pos["bottom"] - image.height * (1-metadata["pivotY"]) + .5)
        frames.append((left, top, image))
    x0 = min(x for x, _, _ in frames) - 16
    y0 = min(y for _, y, _ in frames) - 16
    right = max(x + image.width for x, y, image in frames) + 16
    bottom = max(y + image.height for x, y, image in frames) + 16
    need(right-x0 <= 2400 and bottom-y0 <= 2400,
         "Candidate composite exceeded image budget.")
    canvas = Image.new("RGBA", (right-x0, bottom-y0))
    for x, y, image in frames:  # original SpriteSuite paint order ascending slot
        canvas.alpha_composite(image, (x-x0, y-y0))
    return canvas


def build_frames(building: dict, visual: dict, sprites: dict) -> dict:
    from PIL import Image, ImageDraw, ImageFont
    by_id = {frame["tileId"]: frame for frame in building["drawingGraphics"]}
    preview = []
    for hypothesis in visual["hypotheses"]:
        slots = []
        for tile in hypothesis["slots"]:
            frame = by_id[tile["tileId"]]
            slots.append({**tile, "sprite": frame["sprite"],
                          "spriteA": hypothesis["spriteA"],
                          "spriteB": hypothesis["spriteB"]})
        preview.append({
            "orientation": hypothesis["orientation"],
            "spriteA": hypothesis["spriteA"],
            "spriteB": hypothesis["spriteB"],
            "slots": slots,
            "composite": composite_candidate(slots, sprites)
        })
    need(bool(preview), "No preview hypotheses.")
    card_w, card_h = 620, 400
    cols = 4 if len(preview) > 4 else len(preview)
    rows = math.ceil(len(preview)/cols)
    sheet = Image.new("RGB", (cols*card_w, rows*card_h), (236, 235, 229))
    draw = ImageDraw.Draw(sheet)
    for index, candidate in enumerate(preview):
        x = index%cols * card_w
        y = index//cols * card_h
        checker = Image.new("RGB", (card_w-20, card_h-42), (244,244,244))
        for row in range(0, checker.height, 16):
            for col in range(0, checker.width, 16):
                if ((row+col)//16)%2:
                    ImageDraw.Draw(checker).rectangle((col,row,col+15,row+15),
                        fill=(223,223,223))
        comp = candidate["composite"].copy()
        if comp.width > checker.width - 15 or comp.height > checker.height - 15:
            comp.thumbnail((checker.width-15, checker.height-15), Image.Resampling.NEAREST)
        checker.paste(comp, ((checker.width-comp.width)//2,
                            (checker.height-comp.height)//2), comp)
        sheet.paste(checker, (x+10, y+36))
        draw.rectangle((x,y,x+card_w-1,y+card_h-1),outline=(140,140,140),width=2)
        draw.text((x+12,y+9),
                  f"{index+1}. {candidate['orientation']}  |  {candidate['spriteA']}x{candidate['spriteB']}",
                  fill=(25,30,40))
    return preview, sheet


def save_export(output: Path, building: dict, visual: dict,
                data: dict[str,dict], asset_sha: str, mapping_sha: str,
                log_sha: str, type_label: str | None = None,
                type_catalog_sha: str | None = None):
    """Publish the original sprite art atomically, never leave partial results."""
    import os
    import shutil
    need(not output.exists(), "Output directory already exists; refuse overwrite.")
    need(output.parent.is_dir(), "Output parent must exist.")
    temporary = output.parent / (output.name + ".spritesuite-" + str(os.getpid()) + ".working")
    need(not temporary.exists(), "Temporary destination already exists.")
    try:
        report = _save_export_inplace(
            temporary, building, visual, data, asset_sha, mapping_sha, log_sha,
            type_label, type_catalog_sha)
        need(not output.exists(), "Output appeared while preparing the export.")
        temporary.rename(output)
        return report
    except Exception:
        # This path was created exclusively by this invocation, not user data.
        if temporary.is_dir() and not temporary.is_symlink():
            shutil.rmtree(temporary)
        raise


def _save_export_inplace(output: Path, building: dict, visual: dict,
                         data: dict[str,dict], asset_sha: str,
                         mapping_sha: str, log_sha: str,
                         type_label: str | None, type_catalog_sha: str | None):
    from PIL import Image
    output.mkdir(parents=False, exist_ok=False)
    raw_dir = output/"raw_sprites"
    raw_dir.mkdir(exist_ok=False)
    raw_manifest={}
    for name, item in sorted(data.items()):
        safe_name = name.replace(" ", "_") + ".png"
        with (raw_dir/safe_name).open("xb") as f:
            item["image"].save(f,format="PNG")
        raw_manifest[name] = {
            "png": "raw_sprites/"+safe_name,
            "pngSHA256": digest((raw_dir/safe_name).read_bytes()),
            "rgbaSHA256": digest(item["image"].tobytes()),
            "width": item["image"].width,
            "height": item["image"].height,
            "pivotX": item["pivotX"],
            "pivotY": item["pivotY"],
            "ppu": item["ppu"],
            "unityPathId": item["pathId"],
            "texture": item["nativeTexture"],
        }
    hypotheses, sheet=build_frames(building, visual, data)
    with (output/"original_orientation_contact_sheet.png").open("xb") as file:
        sheet.save(file,format="PNG")
    mapping=[]
    for candidate in hypotheses:
        image_name="preview_"+candidate["orientation"]+".png"
        with (output/image_name).open("xb") as f:
            candidate["composite"].save(f,format="PNG")
        mapping.append({"orientation":candidate["orientation"],
             "spriteA": candidate["spriteA"], "spriteB":candidate["spriteB"],
             "preview":image_name,"previewSHA256":digest((output/image_name).read_bytes()),
             "slots":candidate["slots"],"reviewed":False,
             "approvedForRenderer":False})
    report={
        "format":"spritesuite-shcde-original-graphics-visual-proof",
        "version":1,"readOnly":True,
        "gameAssetSHA256":asset_sha,"mappingSHA256":mapping_sha,
        "sourceGameLogSHA256":log_sha,
        "buildingId":building["buildingId"],
        "globalId":building["globalId"],"gameBuildingType":building["buildingType"],
        "gameBuildingTypeName":type_label,
        "gameBuildingTypeCatalogSHA256":type_catalog_sha,
        "drawnSpriteTileCount":visual["distinctGraphicTiles"],
        "graphicsGridA":visual["graphicsWidth"],
        "graphicsGridB":visual["graphicsHeight"],
        "occupiedTileCount":building["footprintTileCount"],
        "graphicTilesOutsideNativeFootprint":building["drawingTilesOutsideNativeFootprint"],
        "nativeSpriteImages":raw_manifest,"orientations":mapping,
        "orientationVerifiedInGame":False,
        "approvedDamageModelsAvailable":False,
        "runtimeDamageSwitchingInstalled":False
    }
    with (output/"original_sprite_reference.json").open("x",encoding="utf8",newline="\n") as f:
        json.dump(report,f,ensure_ascii=False,indent=2)
        f.write("\n")
    return report


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--log",required=True,type=Path)
    p.add_argument("--expected-log-sha256",required=True)
    p.add_argument("--mapping",required=True,type=Path)
    p.add_argument("--expected-mapping-sha256",required=True)
    p.add_argument("--asset",required=True,type=Path)
    p.add_argument("--expected-asset-sha256",required=True)
    p.add_argument("--building-id",required=True,type=int)
    p.add_argument("--global-id",required=True,type=int)
    p.add_argument("--output",required=True,type=Path)
    p.add_argument("--type-catalog",type=Path)
    p.add_argument("--expected-type-catalog-sha256")
    args=p.parse_args(argv)
    try:
        building, visual=target_from_log(args.log,args.expected_log_sha256,
                                         args.building_id,args.global_id)
        mapping=verified_mapping(args.mapping,args.expected_mapping_sha256)
        names={frame["sprite"] for frame in building["drawingGraphics"]}
        for name in names:
            need(name in mapping, "Sprite not present in native mapping: "+name)
        print(f"Verified {len(names)} unique native sprites for {args.building_id}/"
              f"{args.global_id} and {len(visual['hypotheses'])} orientations.",flush=True)
        asset_sha=args.expected_asset_sha256
        need(SHA.fullmatch(asset_sha) is not None,
             "Expected native asset SHA-256 must be supplied.")
        need(args.asset.stat().st_size <= MAX_FILE_BYTES,
             "Unity asset index too large.")
        with args.asset.open("rb") as source:
            sha=hashlib.file_digest(source,"sha256").hexdigest()
        need(sha==asset_sha, "Native resource asset SHA-256 mismatch.")
        need(bool(args.type_catalog) == bool(args.expected_type_catalog_sha256),
             "Both type catalog and its SHA-256 must be specified together.")
        label = game_type_label(args.type_catalog,
            args.expected_type_catalog_sha256,building["buildingType"]) if args.type_catalog else None
        frames=read_original_frames(args.asset,
                        building["drawingGraphics"],mapping)
        report=save_export(args.output,building,visual,frames,asset_sha,
                           args.expected_mapping_sha256,args.expected_log_sha256,
                           label,args.expected_type_catalog_sha256)
        print(json.dumps({
            "output":str(args.output),
            "graphics":report["drawnSpriteTileCount"],
            "nativeSpriteFiles":len(report["nativeSpriteImages"]),
            "hypotheses":len(report["orientations"]),
            "sourceGameLogSHA256":report["sourceGameLogSHA256"],
            "contactSheet":str(args.output/"original_orientation_contact_sheet.png"),
            "orientationVerifiedInGame":False,
        },indent=2,ensure_ascii=False))
        return 0
    except (OriginalImageError,AuditError,OSError,UnicodeError,KeyError,ValueError) as e:
        print("Original image proof failed: "+str(e),file=sys.stderr)
        return 2

if __name__=="__main__":
    sys.exit(main())

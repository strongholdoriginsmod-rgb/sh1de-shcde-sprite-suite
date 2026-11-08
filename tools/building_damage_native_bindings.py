#!/usr/bin/env python3
"""Create a NON-ACTIVE type-19 runtime binding proposal from exact native pixels.

A source-pixel-matched and geometrically coherent orientation is still not an
in-game renderer approval. Never install this config as an active damage mod.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
from PIL import Image

SHA256 = re.compile(r"^[0-9a-f]{64}$")


class BindingError(ValueError):
    pass


def need(condition, reason):
    if not condition:
        raise BindingError(reason)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def source(path: Path, expected: str, limit: int = 1024 * 1024) -> bytes:
    need(SHA256.fullmatch(expected) is not None, "Expected SHA-256 required.")
    need(path.is_file() and not path.is_symlink() and path.stat().st_size <= limit,
         "Source missing, unsafe or too large: " + str(path))
    raw = path.read_bytes()
    need(digest(raw) == expected, "Source SHA-256 mismatch: " + str(path))
    return raw


def generate(reference: Path, reference_sha256: str,
             draft: Path, draft_sha256: str) -> dict:
    ref = json.loads(source(reference, reference_sha256))
    stages = json.loads(source(draft, draft_sha256))
    need(ref.get("format") == "spritesuite-shcde-original-graphics-visual-proof" and
         ref.get("gameBuildingType") == 19 and
         ref.get("gameBuildingTypeName") == "STRUCT_GRANARY" and
         ref.get("graphicsGridA") == ref.get("graphicsGridB") == 4 and
         ref.get("drawnSpriteTileCount") == 16 and
         ref.get("orientationVerifiedInGame") is False and
         ref.get("approvedDamageModelsAvailable") is False,
         "Native granary provenance or approval state differs from the audited contract.")
    need(stages.get("format") == "spritesuite-building-damage-draft-generation-requests" and
         stages.get("gameBuildingType") == 19 and
         stages.get("nativeBaseSceneId") == "g_native_19" and
         stages.get("modelGenerationExecuted") is False and
         stages.get("generatedDamageAssets") == 0 and
         stages.get("approvedDamageStages") == 0 and
         stages.get("readyRequestCount") == 2 and
         stages.get("blockedRequestCount") == 6 and
         len(stages.get("requests", [])) == 8,
         "Draft stages are not the expected unapproved granary progression.")
    choices = [row for row in ref.get("orientations", [])
               if row.get("orientation") == "xy-u-v"]
    need(len(choices) == 1, "The visually coherent xy-u-v hypothesis is unavailable.")
    chosen = choices[0]
    need(chosen.get("reviewed") is False and
         chosen.get("approvedForRenderer") is False and
         chosen.get("spriteA") == chosen.get("spriteB") == 4 and
         len(chosen.get("slots", [])) == 16,
         "Unexpected renderer approval flag or orientation slot count.")
    preview_name = chosen.get("preview", "")
    need(preview_name == "preview_xy-u-v.png", "Unexpected original preview filename.")
    source(reference.parent / preview_name, chosen["previewSHA256"], 8 * 1024 * 1024)

    bindings = []
    seen_tiles, seen_coords, seen_sprites = set(), set(), set()
    for index, tile in enumerate(chosen["slots"]):
        name = tile.get("sprite", "")
        path_id = tile.get("tileId")
        coords = (tile.get("x"), tile.get("y"))
        need(tile.get("inNativeFootprint") is True and
             isinstance(path_id, int) and path_id > 0 and
             all(isinstance(p, int) for p in coords) and
             path_id not in seen_tiles and coords not in seen_coords and
             name not in seen_sprites and re.fullmatch(r"tile_buildings2 [0-9]{1,4}", name),
             "Non-unique or invalid original graphic tile in slot " + str(index))
        seen_tiles.add(path_id)
        seen_coords.add(coords)
        seen_sprites.add(name)
        gm, image = tile.get("gm"), tile.get("image")
        need(str(gm) == "7" and str(image).isdigit() and
             name == "tile_buildings2 " + str(image),
             "Native file/image numbers differ from observed SpriteMapping.")
        metadata = ref["nativeSpriteImages"].get(name)
        need(isinstance(metadata, dict), "Original image metadata missing: " + name)
        png_path = PurePosixPath(metadata.get("png", ""))
        need(len(png_path.parts) == 2 and png_path.parts[0] == "raw_sprites" and
             re.fullmatch(r"tile_buildings2_[0-9]{1,4}\.png", png_path.parts[1]),
             "Unsafe or incorrect native PNG path.")
        raw_png = source(reference.parent.joinpath(*png_path.parts), metadata["pngSHA256"])
        with Image.open(io.BytesIO(raw_png)) as image_file:
            need(1 <= image_file.width <= 64 and
                 1 <= image_file.height <= 512 and
                 image_file.size == (metadata["width"], metadata["height"]),
                 "Original PNG geometry exceeds native tile budget.")
            rgba = image_file.convert("RGBA")
        need(rgba.size == (metadata["width"], metadata["height"]) and
             digest(rgba.tobytes()) == metadata["rgbaSHA256"] and
             metadata.get("ppu") == 64.0 and
             0.0 <= metadata.get("pivotX", -1) <= 1.0 and
             0.0 <= metadata.get("pivotY", -1) <= 1.0,
             "Original pixel, dimensions, pivot or PPU mismatch in " + name)
        bindings.append({
            "buildingType": 19,
            "buildingGlobalId": ref["globalId"],  # QA instance only, not universal
            "buildingGroupId": "g_native_19",
            "sourceSprite": name, "matchGmImage": True,
            "gm": 7, "image": int(image), "slot": index,
            "ownerOffsetX": 0, "ownerOffsetY": 0,
            "overridePivot": False, "overridePpu": False,
        })
    need(len(seen_coords) == 16 and
         max(x for x, _ in seen_coords) - min(x for x, _ in seen_coords) == 3 and
         max(y for _, y in seen_coords) - min(y for _, y in seen_coords) == 3,
         "Measured tile grid is not complete 4x4.")
    return {
        "enabled": False, "previewEnabled": False,
        "firePersistsUntilRepaired": True, "pollFrames": 12,
        "damageArchive": "DO_NOT_INSTALL_UNAPPROVED_GRANARY.zip",
        "damageDirectory": "DamageAssets",
        "bindings": bindings,
        "provenance": {
            "status": "proposal_only_not_approved_for_install_or_game_renderer",
            "visualCandidate": "xy-u-v",
            "mappingConfirmedInGame": False,
            "sourceGameBuildingType": 19,
            "sourceBuildingId": ref["buildingId"],
            "sourceGlobalId": ref["globalId"],
            "sourceGameLogSHA256": ref["sourceGameLogSHA256"],
            "sourceAssetSHA256": ref["gameAssetSHA256"],
            "sourceMappingSHA256": ref["mappingSHA256"],
            "originalReferenceSHA256": reference_sha256,
            "unapprovedDraftManifestSHA256": draft_sha256,
            "originalPngRGBAValidated": len(bindings),
            "approvedDamageStages": 0,
            "fullHpFireGameQaProved": False,
        }
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--expected-reference-sha256", required=True)
    parser.add_argument("--draft-manifest", type=Path, required=True)
    parser.add_argument("--expected-draft-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = generate(args.reference, args.expected_reference_sha256,
                          args.draft_manifest, args.expected_draft_sha256)
        target = args.output
        need(target.parent.is_dir() and not target.is_symlink(),
             "Output directory missing.")
        serialized = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        with target.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(serialized)
        print(json.dumps({
            "output": str(target), "proposedBindings": len(result["bindings"]),
            "sha256": digest(serialized.encode("utf-8")),
            "enabled": False, "approvedDamageStages": 0,
            "visualOrientationVerifiedInGame": False,
        }, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, "Unapproved native binding proposal refused: " + str(error) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())

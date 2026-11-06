"""Correlate read-only SHCDE damage, footprint and Unity Tilemap observations.

The correlation is an evidence aid for free SpriteSuite modding, not an
installation gate or proof that a replacement sprite can be displayed.
Only events within the same explicit QA map/load segment may be joined.
"""
from __future__ import annotations

import re

_DIGITS = re.compile(r"^[0-9]+$")
_COORDS = re.compile(r"^-?[0-9]+,-?[0-9]+$")


def _xy(value: str) -> tuple[int, int] | None:
    if not _COORDS.fullmatch(value):
        return None
    a, b = value.split(",", 1)
    return int(a), int(b)


def _identity(event: dict[str, str], epoch: int) -> tuple[int, str, str, str] | None:
    values = tuple(event.get(key, "") for key in
                   ("building_id", "global_id", "type"))
    if not all(_DIGITS.fullmatch(value) for value in values):
        return None
    return epoch, *values


def _footprint(value: str) -> dict[str, tuple[int, int]]:
    result = {}
    for row in value.split(";"):
        tile_id, separator, coordinate = row.partition(":")
        xy = _xy(coordinate) if separator else None
        if _DIGITS.fullmatch(tile_id) and xy is not None:
            result[tile_id] = xy
    return result


def _render_rows(value: str) -> list[tuple[str, tuple[int, int], str, str]]:
    rows = []
    for part in value.split(";"):
        cols = part.split(":", 3)
        if len(cols) != 4:
            continue
        tile_id, coords, original, tilemap = cols
        xy = _xy(coords)
        if _DIGITS.fullmatch(tile_id) and xy is not None:
            rows.append((tile_id, xy, original, tilemap))
    return rows


def _sprite_name(value: str) -> str:
    """The audit appends ~widthxheight~PPU to a sanitized sprite name."""
    return value.split("~", 1)[0]


def correlate_events(events: list[dict[str, str]]) -> dict:
    """Join actual tile IDs, coordinates, building identity and sprite names.

    A visual mapping is only a candidate even when all three sources agree:
    a runtime HP swap, masks, refresh, and game rendering remain untested.
    """
    graphic: dict[tuple[int, str, str, str], dict[str, dict]] = {}
    footprints: dict[tuple[int, str, str, str], dict[str, tuple[int, int]]] = {}
    renders: list[tuple[tuple[int, str, str, str], dict]] = []
    epoch = 0
    starts = 0
    graphics_seen = footprints_seen = render_events = 0
    direct_tilemap = set()
    direct_name_matches = set()
    direct_name_mismatches = set()
    for event in events:
        kind = event.get("event")
        if kind == "start":
            if starts:
                epoch += 1
            starts += 1
        elif (kind == "qa_save_load" and event.get("status") == "requested"
              or kind in ("map_reset", "map_unload", "scene_reload")):
            epoch += 1
        key = _identity(event, epoch)
        if key is None:
            continue
        if kind == "tile_graphic":
            graphics_seen += 1
            tile_id = event.get("tile_id", "")
            xy = _xy(event.get("x", "") + "," + event.get("y", ""))
            if (not _DIGITS.fullmatch(tile_id) or xy is None
                    or event.get("renderer_modified") != "false"):
                continue
            graphic.setdefault(key, {})[tile_id] = {
                "xy": xy, "sprite": event.get("sprite", ""),
                "gm": event.get("gm", ""), "image": event.get("image", ""),
            }
            actual = _sprite_name(event.get("tilemap_sprite", ""))
            if actual not in ("", "none", "null"):
                direct_tilemap.add((key, tile_id))
                if actual == event.get("sprite"):
                    direct_name_matches.add((key, tile_id))
                else:
                    direct_name_mismatches.add((key, tile_id))
        elif kind == "building_footprint":
            footprints_seen += 1
            footprints.setdefault(key, {}).update(_footprint(event.get("tiles", "")))
        elif kind == "building_render_tiles":
            render_events += 1
            if event.get("renderer_modified") != "false":
                continue
            for tile_id, xy, original, tilemap in _render_rows(event.get("samples", "")):
                renders.append((key, {
                    "tileId": tile_id, "xy": xy,
                    "tileImage": original, "tilemapSprite": tilemap,
                }))
    shared = set(graphic) & set(footprints)
    graphic_and_footprint = set()
    for key in shared:
        for tile_id, row in graphic[key].items():
            if footprints[key].get(tile_id) == row["xy"]:
                graphic_and_footprint.add((key, tile_id))
    render_footprint = set()
    render_graphic = set()
    combined = set()
    tilemap_present = set()
    tilemap_disagreements = set()
    examples = []
    for key, sample in renders:
        tile_id = sample["tileId"]
        ident = (key, tile_id)
        foot_ok = footprints.get(key, {}).get(tile_id) == sample["xy"]
        gfx = graphic.get(key, {}).get(tile_id)
        graphic_ok = bool(gfx and gfx["xy"] == sample["xy"] and
                          _sprite_name(sample["tileImage"]) == gfx["sprite"])
        base = _sprite_name(sample["tileImage"])
        actual = _sprite_name(sample["tilemapSprite"])
        has_tilemap = actual not in ("", "null", "none")
        if foot_ok:
            render_footprint.add(ident)
        if graphic_ok:
            render_graphic.add(ident)
        if foot_ok and graphic_ok:
            combined.add(ident)
            if has_tilemap:
                tilemap_present.add(ident)
            if has_tilemap and base not in ("", "none") and base != actual:
                tilemap_disagreements.add(ident)
        if len(examples) < 12:
            examples.append({
                "buildingId": key[1], "globalId": key[2], "buildingType": key[3],
                "mapSegment": key[0], "tileId": tile_id,
                "x": sample["xy"][0], "y": sample["xy"][1],
                "tileImage": sample["tileImage"],
                "tilemapSprite": sample["tilemapSprite"],
                "graphicImage": gfx["image"] if gfx else None,
                "graphicGM": gfx["gm"] if gfx else None,
                "footprintMatch": foot_ok, "graphicMatch": graphic_ok,
            })
    if not render_events and not direct_tilemap:
        note = "No per-building Unity Tilemap observations in this log."
    elif not render_events and direct_tilemap:
        note = ("Direct read-only Tilemap sprite observations exist; a separate "
                "building footprint link and visual replacement remain unproven.")
    elif not render_footprint:
        note = "No same-building/global-id/position footprint correlation."
    elif not combined:
        note = "Footprint tiles found; no matching graphic tile and sprite names."
    elif not tilemap_present:
        note = "Read-only graphic correlation found; no Tilemap sprite observed."
    else:
        note = ("Read-only mapping candidate observed. A visible HP-dependent "
                "renderer replacement, masks and rollback are not proven.")
    return {
        "mapSegments": epoch + 1,
        "graphicEventCount": graphics_seen,
        "footprintEventCount": footprints_seen,
        "renderTileEventCount": render_events,
        "renderTileSampleCount": len(renders),
        "directTilemapSpriteSamples": len(direct_tilemap),
        "directTilemapOriginalSpriteNameMatches": len(direct_name_matches),
        "directTilemapSpriteNameDifferences": len(direct_name_mismatches),
        "directTilemapBuildingCount": len({key for key, _ in direct_tilemap}),
        "graphicFootprintIdentityCount": len(shared),
        "graphicFootprintSpatialTileCount": len(graphic_and_footprint),
        "renderFootprintSpatialTileCount": len(render_footprint),
        "renderGraphicSpriteTileCount": len(render_graphic),
        "renderCombinedTileCount": len(combined),
        "renderCombinedBuildingCount": len({key for key, _ in combined}),
        "renderCombinedTilemapSpriteCount": len(tilemap_present),
        "renderTilemapSpriteNameDisagreements": len(tilemap_disagreements),
        "readOnlyTilemapCandidateObserved": bool(tilemap_present or direct_tilemap),
        "renderEvidenceNote": note,
        "renderTileExamples": examples,
        "visualReplacementVerified": False,
        "hpDamageSwitchVerified": False,
    }

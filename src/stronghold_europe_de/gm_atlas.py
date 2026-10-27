from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import os
from math import isfinite
from pathlib import Path
import re
import struct
from typing import Any, Iterable, Mapping, Sequence

from PIL import Image

from .loader_groups import LOADER_GROUP_TABLE, SHARED_GM_ENUM_ALIASES
from .derived_feasibility import PLACEMENT_PROOF_ALGORITHM
from .mapping import keep_crusader, redirect_source


class GMAtlasError(ValueError):
    """Raised when an atlas would not be safe for the SHCDE-SE 1.39 loader."""


# ---------------------------------------------------------------------------
# Measuring every placement proof in one build instead of one per build.
#
# A group declares its proofs as placeholders and the build reports what it
# measured. With one report per run, pinning N new groups costs N complete
# builds - and a build rebuilds every group, so the cost grows with the square
# of the catalogue. At 140 groups that is over half a day of rebuilding to
# learn 140 digests.
#
# In collect mode a proof mismatch is recorded instead of raised, so a single
# build measures them all. Three properties make that safe:
#
#   * Only proof mismatches are collected. A misplaced frame, a wrong array
#     size, a missing donor - anything meaning the output is wrong rather than
#     merely unrecorded - still raises immediately.
#   * The build still fails: everything collected is raised together at the
#     end, the output transaction rolls back, and nothing unverified can reach
#     an installation.
#   * It is off unless a tool asks for it.
# ---------------------------------------------------------------------------
COLLECT_PROOFS_ENV = "SEDE_COLLECT_PROOF_MISMATCHES"
_collected_proof_mismatches: list[str] = []


# Nachsichtmodus der Universal-Suite (29.09.2026, Nutzerwunsch: "Nachsicht
# ist Standard, restriktiv nur separat einschaltbar"): abweichende Nachweise
# werden gesammelt, als WARNUNG ausgegeben und in
# work/reports/nachsicht-nachweise.log festgehalten; der Bau laeuft weiter.
# Die gemessenen Werte uebernimmt danach tools/pin_digests.py --aus-protokoll
# (Knopf "Nachweise uebernehmen"). Streng wird es nur mit SEDE_STRENG=1 (oder
# SEDE_NACHSICHT=0) - so laufen die Testsuite und die Nachweis-Vermessung.
NACHSICHT_ENV = "SEDE_NACHSICHT"
STRENG_ENV = "SEDE_STRENG"
_AN = {"1", "ja", "an", "true", "on"}
_AUS = {"0", "nein", "aus", "false", "off"}


def nachsicht_aktiv() -> bool:
    if os.environ.get(STRENG_ENV, "").strip().lower() in _AN:
        return False
    return os.environ.get(NACHSICHT_ENV, "").strip().lower() not in _AUS


def collecting_proof_mismatches() -> bool:
    return os.environ.get(COLLECT_PROOFS_ENV) == "1" or nachsicht_aktiv()


def _nachsicht_protokoll(messages: list[str]) -> None:
    import datetime
    import sys as _sys

    for message in messages:
        print(f"WARNUNG (Nachsicht): {message}", file=_sys.stderr, flush=True)
    try:
        report = Path(os.environ.get("SEDE_NACHSICHT_LOG") or
                      Path(__file__).resolve().parents[2] / "work" / "reports" / "nachsicht-nachweise.log")
        report.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now().isoformat(timespec="seconds")
        with report.open("a", encoding="utf-8") as stream:
            for message in messages:
                stream.write(stamp + chr(9) + message.replace(chr(10), " ") + chr(10))
    except OSError:
        pass


def proof_mismatch(message: str) -> None:
    """Report a proof that does not match its pin.

    Raises unless the caller asked for every mismatch in one pass, in which
    case it is recorded and raised with the others when the build finishes.
    """

    if not collecting_proof_mismatches():
        raise GMAtlasError(message)
    _collected_proof_mismatches.append(message)


def raise_collected_proof_mismatches() -> None:
    """Fail the build with everything collected. Always called at the end."""

    if not _collected_proof_mismatches:
        return
    collected = list(_collected_proof_mismatches)
    _collected_proof_mismatches.clear()
    if nachsicht_aktiv():
        _nachsicht_protokoll(collected)
        return
    raise GMAtlasError(
        f"{len(collected)} Platzierungsnachweise weichen ab:\n"
        + "\n".join(collected)
    )


# This is intentionally a reviewed allow-list.  Each entry was checked against
# GameAtlasManagerAPI._gmFileNameToEnum in the locally installed SHCDE-SE 1.39
# source.  More groups must be added only after their naming and mask policy are
# inspected in that loader version.
LOADER_139_GROUPS: dict[str, tuple[bool, str, bool]] = {
    "anim_stocks": (True, "required", True),
    "float_pop_circ-2": (True, "forbidden", True),
    "body_brazier": (True, "forbidden", True),
    "anim_ducking_stool": (True, "required", True),
    "anim_dungeon": (True, "required", True),
    "puff of smoke": (True, "forbidden", True),
    "body_steam": (True, "forbidden", True),
    "anim_shields": (True, "required", True),
    "anim_armourer": (True, "required", True),
    "body_animal_burning_small": (True, "forbidden", True),
    "anim_gibbet": (True, "required", True),
    "anim_market": (True, "required", True),
    "anim_stake": (True, "required", True),
    "anim_gallows": (True, "forbidden", True),
    "body_animal_burning_big": (True, "forbidden", True),
    "anim_rack": (True, "required", True),
    "anim_chopping_block": (True, "required", True),
    "anim_woodcutter": (True, "required", True),
    "anim_hunter": (True, "required", True),
    "body_missile_cow": (True, "forbidden", True),
    "smoke-30x30": (True, "forbidden", True),
    "oil_dropped": (False, "forbidden", True),
    "body_disease": (True, "forbidden", True),
    "anim_tunnels": (True, "required", True),
    "anim_killing_pits": (True, "forbidden", True),
    "anim_stables": (True, "required", True),
    "anim_healer": (True, "forbidden", True),
    "anim_pitch_dugout": (True, "required", True),
    "anim_dancing_bear": (True, "forbidden", True),
    "anim_maypole": (True, "required", True),
    "anim_baker": (True, "required", True),
    "anim_fletcher": (True, "required", True),
    "blast3": (True, "forbidden", True),
    "anim_tanner": (True, "required", True),
    "cursors": (True, "forbidden", True),
    "float_pop_circ-1": (True, "forbidden", True),
    "anim_brewer": (True, "required", True),
    "anim_poleturner": (True, "required", True),
    "anim_drawbridge": (True, "forbidden", True),
    "anim_boiled_oil": (True, "forbidden", True),
    "body_missile_fire": (True, "forbidden", True),
    "body_missile_2": (True, "forbidden", True),
    "body_siege_tower": (True, "forbidden", True),
    "anim_iron_miner": (True, "required", True),
    "body_missile": (True, "forbidden", True),
    "body_ballista": (True, "required", True),
    "anim_blacksmith": (True, "required", True),
    "body_crow": (True, "forbidden", True),
    "body_mangonel": (True, "required", True),
    "body_horse_trader": (True, "required", True),
    "body_ghost": (True, "required", True),
    "body_fire2": (True, "forbidden", True),
    "anim_quarry": (True, "required", True),
    "body_drunkard": (True, "required", True),
    "body_battering_ram": (True, "required", True),
    "body_man_burning": (True, "required", True),
    "body_cow": (True, "required", True),
    "body_trebutchet": (True, "required", True),
    "body_catapult": (True, "required", True),
    "body_juggler": (True, "required", True),
    "body_fire": (True, "forbidden", True),
    "body_ox": (True, "required", True),
    "body_priest": (True, "required", True),
    "body_rabbit": (True, "required", True),
    "body_iron_miner": (True, "required", True),
    "body_girl": (True, "required", True),
    "body_boy": (True, "required", True),
    "body_dog": (True, "required", True),
    "body_stonemason": (True, "required", True),
    "body_innkeeper": (True, "required", True),
    "body_miller": (True, "required", True),
    "body_brewer": (True, "required", True),
    "body_armourer": (True, "required", True),
    "body_baker": (True, "required", True),
    "body_pikeman": (True, "required", True),
    "body_tanner": (True, "required", True),
    "body_tunnelor": (True, "required", True),
    "body_crossbowman": (True, "required", True),
    "body_fletcher": (True, "required", True),
    "body_wolf": (True, "forbidden", True),
    "body_spearman": (True, "required", True),
    "body_siege_engineer": (True, "required", True),
    "body_maceman": (True, "required", True),
    "body_blacksmith": (True, "required", True),
    "body_archer": (True, "required", True),
    "body_deer": (True, "required", True),
    "body_farmer": (True, "required", True),
    "anim_flag_small": (True, "required", True),
    "body_gate": (True, "forbidden", True),
    "anim_windmill": (True, "required", True),
    "anim_inn": (True, "required", True),
    "anim_farmer": (True, "required", True),
    # spriteLoader.SpriteLoad calls loadSprites("Sprites/treeSprites",
    # makeMask: true, foliage: true), and tree_apple is registered with
    # plainShader=false plus appleFoliageColours.
    # False means the atlas loader's hard-coded Unlit/TeamColour material does
    # not match vanilla's Unlit/Foliage material.  Generation is allowed only
    # with an explicit profile acknowledgement and the result is not considered
    # runtime-verified until a visual test passes.
    "tree_apple": (True, "required", False),
    # These groups use body8Sprites with makeMask=true, foliage=false and
    # plainShader=false.  SHCDE-SE 1.39's atlas material (Unlit/TeamColour)
    # therefore matches vanilla.  Jester/lady palettes remain in gmColors;
    # the atlas override does not replace those arrays.
    "body_fighting_monk": (True, "required", True),
    "body_fire_eater": (True, "required", True),
    "body_fireman": (True, "required", True),
    "body_healer": (True, "required", True),
    "body_jester": (True, "required", True),
    "body_ladder_bearer": (True, "required", True),
    "body_lady": (True, "required", True),
    "body_pitch_worker": (True, "required", True),
    "body_poleturner": (True, "required", True),
    "body_tent": (True, "required", True),
    "body_trader": (True, "required", True),
    "body_woodcutter": (True, "required", True),
    # These terrain groups are read from AllTileSprites, are registered with
    # dashFormat=false and plainShader=true, and have no companion mask atlas.
    # Supplying atlas_m.png would make SHCDE-SE 1.39 replace the vanilla plain
    # material with Unlit/TeamColour, so the absence of a mask is mandatory.
    "tile_land_and_stones": (False, "forbidden", True),
    "tile_chevrons": (False, "forbidden", True),
    "tile_farmland": (False, "forbidden", True),
    "tile_flatties": (False, "forbidden", True),
    "tile_cliffs": (False, "forbidden", True),
    "killing_pits": (False, "forbidden", True),
    "pitch_ditches": (False, "forbidden", True),
    # tile_walls is the sparse case: Crusader exposes 35 frames at indices 1-33,
    # 48 and 63, so the vanilla array is 64 slots wide. Stronghold 1 DE has 45
    # further wall frames which must not be emitted; the frozen name digest and
    # expected_max_index=63 keep the array width intact.
    "tile_walls": (False, "forbidden", True),
    # These four dominant AllTileSprites groups own their complete GM arrays and
    # use the same plain/no-mask loader path as the terrain groups above. Their
    # full SH1DE source sets satisfy the frozen native-geometry contracts below,
    # including the sparse tile_land3 array whose occupied slots end at 315.
    "tile_land8": (False, "forbidden", True),
    "tile_land_macros": (False, "forbidden", True),
    "tile_goods": (False, "forbidden", True),
    "tile_land3": (False, "forbidden", True),
    # The complete workshop tile array follows the same AllTileSprites,
    # space-numbered, plain/no-mask path.  All 2,016 SH1DE slots are covered by
    # a source-only native-geometry contract; no Crusader frame is admitted.
    "tile_workshops": (False, "forbidden", True),
    # The three building arrays the player sees most: farm huts, hovels, the
    # Arabian houses and the churches. Same AllTileSprites, space-numbered,
    # plain/no-mask loader path as the workshops above, and each owns its
    # complete GM array (verified via `map manifest`: owns_its_gm_arrays=true,
    # dash_format=false, mask_policy=forbidden for all three).
    "tile_buildings1": (False, "forbidden", True),
    "tile_buildings2": (False, "forbidden", True),
    "tile_churches": (False, "forbidden", True),
    # The castle itself - walls, towers, gatehouses. 1,234 slots of which only
    # 27 have no European donor. Same AllTileSprites, space-numbered,
    # plain/no-mask path as the workshops.
    "tile_castle": (False, "forbidden", True),
    # Vegetation. Same treeSprites/dash-format/team-mask registration as
    # tree_apple, which is proven in game; the companion restores Unlit/Foliage
    # for each of them after the atlas loader forces Unlit/TeamColour.
    "tree_pine": (True, "required", True),
    "Tree_Oak": (True, "required", True),
    "Tree_Chestnut": (True, "required", True),
    "tree_birch": (True, "required", True),
    "tree_shrub1": (True, "required", True),
    "tree_shrub2": (True, "required", True),
    # GM_SEA is a separate, loader-owned sparse array (not the shared
    # GM_NEW_SEA storage used by tile_sea_new_01/tile_sea_shore).  Its complete
    # 1,159-frame SH1DE donor set follows the same plain/no-mask AllTile path.
    "tile_sea8": (False, "forbidden", True),
    # These water effects own complete, contiguous dash-formatted GM arrays.
    # Although their source textures also have companion masks, spriteLoader
    # registers all three GM IDs with plainShader=true, so vanilla uses the
    # plain material path and an override mask must be absent. Their reviewed
    # policy deliberately preserves SH1DE's authored native pivot and PPU.
    "anim_whitecaps_wave": (True, "forbidden", True),
    "body_splash": (True, "forbidden", True),
    "body_seagull": (True, "forbidden", True),
    # Building and goods animations read anims1Sprites/anims1Sprites_m, but
    # spriteLoader registers both with plainShader=true, so vanilla uses
    # plainMaterials and omitting atlas_m.png selects the same material family.
    # Both use the space-numbered form and were unreachable until the group model
    # was taken from the loader table.
    "anim_buildings2": (False, "forbidden", True),
    "anim_goods": (False, "forbidden", True),
    # The tunnelers' guild owns the six space-numbered slots 1..6 (array size
    # seven).  Vanilla registers GM_ANIM_TUNNELERS_GUILD with plainShader=true,
    # so the override must omit anims1Sprites_m despite that texture existing.
    "anim_tunnelors_guild": (False, "forbidden", True),
    # The dog-cage animation owns one complete, contiguous 42-slot GM array.
    # It is dash-formatted, reads anims1Sprites/anims1Sprites_m, and vanilla
    # registers it on the Unlit/TeamColour path.  Its SH1DE and SHCDE names
    # match exactly; all frames still require the normal integral, lossless
    # target-canvas adaptation performed by the standard atlas builder.
    "anim_dog_cage": (True, "required", True),
    # These small effects are loaded from body7Sprites/body7Sprites_m or
    # anims1Sprites/anims1Sprites_m, but spriteLoader.addGMFile registers each
    # one with plainShader=true.  Vanilla therefore discards the source-atlas
    # team-colour material for these GM IDs and uses plainMaterials.  Omitting
    # atlas_m.png makes the 1.39 override select that same material family.
    "rock_chips": (False, "forbidden", True),
    "cracks": (False, "forbidden", True),
    "anim_heads": (True, "forbidden", True),
    # Both body groups own their complete arrays, use dash-formatted names and
    # are registered with the vanilla Unlit/TeamColour path.  Their SH1DE
    # counterparts live on body7Sprites while SHCDE moved them to
    # body13Sprites, so production is allowed only through the explicit,
    # pixel-proven mixed-frame policy below.
    "body_mother": (True, "required", True),
    "body_shield": (True, "required", True),
    # Chickens remain on their own complete GM arrays, retain the vanilla
    # animalColours palette, and use the TeamColour material/mask pair.  Their
    # SH1DE pixels live on body5Sprites while Crusader moved the target slots to
    # body1Sprites.  Both groups were audited frame-by-frame before allow-listing.
    "body_chicken": (True, "required", True),
    "body_chicken_brown": (True, "required", True),
    # The swordsman likewise owns its complete array and uses TeamColour with
    # the default palette.  The 32 SH1DE-only body13Sprites frames are excluded
    # because the frozen target manifest contains only the 1,184 body7 slots.
    "body_swordsman": (True, "required", True),
    # body_lord owns its complete GM array and retains the loader's
    # lordLadyColours palette.  Its target manifest deliberately contains both
    # reviewed SH1 candidates and Crusader-only KEEP slots, so it is available
    # only through the explicit v2 mixed-frame contract below.
    "body_lord": (True, "required", True),
}


# Everything above was filled in by hand, one group at a time, and covered 58 of
# the 195 groups the extender's loader table describes.  That gap was never a
# technical limit - it was 137 groups nobody had got round to looking at, which
# is why the peasant, the archer, the spearman, the blacksmith and most of the
# rest of the population were still Crusader art.
#
# Checking the hand-written entries against the loader table shows they are not
# judgement calls at all.  Across all 58 there is not one exception:
#
#     dash_format  == LoaderGroup.dash_format
#     mask_policy  == "forbidden" if LoaderGroup.plain_shader else "required"
#
# Both follow from what the loader itself records, so deriving them for the
# remaining groups reproduces exactly the same values a careful reader would
# have written down.
#
# The third field says whether the atlas loader's Unlit/TeamColour material
# matches what vanilla registers.  Exactly one group carries False - tree_apple,
# the first foliage group examined, before the runtime gained FoliageGroup to
# repair those materials after the fact.  Every other group, foliage included,
# carries True.  Derived entries therefore get True, and any group that turns
# out to need otherwise is added to the table above, where it will win.
def _derive_loader_groups() -> dict[str, tuple[bool, str, bool]]:
    derived: dict[str, tuple[bool, str, bool]] = {}
    for name, entry in LOADER_GROUP_TABLE.items():
        if name in LOADER_139_GROUPS:
            # A reviewed entry always wins over a derived one.
            continue
        if not entry.owns_its_gm_arrays:
            # Two groups share one GM array: the host reserves the tenant's
            # slots and the tenant writes at an offset.  The atlas override
            # allocates from a single JSON and always writes raw parsed
            # indices, so such a group put through the standard path would
            # write over its co-tenant.  These need the reviewed shared-atlas
            # contract, and must not be derived into availability.
            continue
        derived[name] = (
            entry.dash_format,
            "forbidden" if entry.plain_shader else "required",
            True,
        )
    return derived


LOADER_139_GROUPS.update(_derive_loader_groups())


@dataclass(frozen=True, order=True)
class FrameSlot:
    """The exact gmSprites/gmAltSprites slot selected by the 1.39 loader."""

    index: int
    is_alt: bool


REVIEW_FRAME_POLICY_MODE_V1 = "source_if_lossless_else_target_v1"
REVIEW_FRAME_POLICY_MODE_V2 = "source_if_lossless_else_target_with_keep_v2"
# V3: der geprueft freigegebene Review-Frame wird wie eine Gelaendekachel ueber
# die native Quellgeometrie gerendert - eigene Leinwand, eigener Pivot. Es gibt
# dann keine Zielleinwand, an der etwas beschnitten werden koennte, also auch
# keine Abweisung. Gemessen am Mapping: bei body_lord weist V2 heute 824 von
# 1216 Frames ab, weil das europaeische Bild groesser ist als der Crusader-Slot
# (docs/CLIPPING.md). V3 nimmt der Gruppe nur die Beschneidung, nicht die
# Partition: welcher Slot aus Europa kommt und welcher eine Crusader-Kopie
# bleibt, steht weiterhin in der review_frame_policy.
REVIEW_FRAME_POLICY_MODE_V3 = "source_native_geometry_else_keep_v3"
DERIVED_FRAME_POLICY_MODE = "source_lossless_integral_v1"
# Backwards-compatible public name used by the existing v1 profiles/tests.
REVIEW_FRAME_POLICY_MODE = REVIEW_FRAME_POLICY_MODE_V1
SOURCE_FRAME_ORIGIN = "SOURCE_SH1DE"
TARGET_FRAME_ORIGIN = "TARGET_SHCDE"
KEEP_CRUSADER_PROOF_STATUS = "KEEP_CRUSADER_EXACT"
# Eigener Statusname mit Absicht: `AUTO_LOSSLESS_INTEGRAL` behauptet eine
# bestandene Platzierungspruefung auf der Zielleinwand. Unter V3 findet diese
# Pruefung gar nicht statt - es gibt keine Zielleinwand. Der Status muss den
# gefuehrten Beweis benennen, nicht bloss das Ergebnis.
NATIVE_SOURCE_PROOF_STATUS = "NATIVE_SOURCE_GEOMETRY_EXACT"
REVIEW_INDIVIDUAL_SOURCE_ONLY_MODE = "review_individual_source_only_v1"
REVIEW_INDIVIDUAL_CONTRACT_KIND = (
    "shcdese_review_individual_source_only_contract_v1"
)
REVIEW_INDIVIDUAL_CONTRACT_PREFIX = (
    "Contracts/review_individual_source_only_v1/"
)
REVIEW_INDIVIDUAL_MAIN_CATEGORY = "review_individual_source_sprite"
REVIEW_INDIVIDUAL_MASK_CATEGORY = "review_individual_source_team_mask"
REVIEW_139_GROUP_TEXTURES: dict[str, tuple[str, str]] = {
    "body_mother": ("body7Sprites", "body13Sprites"),
    "body_shield": ("body7Sprites", "body13Sprites"),
    "body_chicken": ("body5Sprites", "body1Sprites"),
    "body_chicken_brown": ("body5Sprites", "body1Sprites"),
    "body_swordsman": ("body13Sprites", "body7Sprites"),
    "body_lord": ("body2Sprites", "body14Sprites"),
    # Die Burganimation: Mauerecken, Torboegen, Turmschaefte und deren
    # Schadensstufen. Gemessen am Sprite-Mapping liegen ihre 95 Spender in
    # AllTileSprites, waehrend Crusader die Gruppe in anims1Sprites fuehrt -
    # damit ist sie atlasuebergreifend und erreicht den Review-Pfad. Sie fehlte
    # im Profil vollstaendig, weshalb jede beschaedigte Mauer und jedes
    # Eckstueck orientalisch blieb.
    "anim_castle": ("AllTileSprites", "anims1Sprites"),
    # The building arrays. Unlike the body groups above, source and target sit
    # in the same texture: both games keep their building tiles in
    # AllTileSprites. The building arrays are deliberately absent: mapping.py
    # only assigns REVIEW_MANUAL across atlases, so a same-texture group can
    # never reach the review path. They use sparse_keep_frame_count instead,
    # which ships the donor-less slots as verbatim Crusader copies.
}

# Welche Review-Gruppe ihre Frames ueberhaupt nativ rendern DARF. Die Liste
# allein schaltet nichts ein: eine Gruppe rendert erst dann nativ, wenn sie hier
# steht UND ihr Profil ausdruecklich review_frame_policy.mode = V3 zusammen mit
# einem nativen geometry_policy-Objekt angibt. Ohne Profilangabe verhaelt sich
# die Gruppe unveraendert.
#
# `body_lord`: gemessen am Mapping betraegt der Abstand zwischen Quell- und
# Zielanker bis zu 84 px waagerecht und 53 px senkrecht, auf 1192 von 1216
# Frames ueber 1 px. Deshalb ist hier nur der AUTHORED-Pivot zulaessig (siehe
# den Waechter in AtlasGroupSpec.from_profile): er setzt jeden Quellpixel an
# dieselbe Stelle relativ zum Anker wie die heutige Zielleinwand-Platzierung,
# verschiebt also nichts. Der reanchored-Modus wuerde jeden Frame um genau
# diesen Ankerabstand versetzen.
#
# `anim_castle` steht bewusst NICHT hier: dort betraegt der Ankerabstand bis zu
# 260 px senkrecht, und bei einem Mauereck ist das eine Platzierungs-, keine
# Groessenfrage. Erst nach Sicht, siehe docs/CLIPPING.md.
# body_swordsman kam am 15.08.2026 dazu, aus einer Messung im Spiel: Von den
# fuenf noch gemischten Gruppen ist er die einzige, deren Mischung man SIEHT.
# Sieben seiner acht Gehzyklen enthalten einzelne Stronghold-1-Frames zwischen
# Crusader-Frames, und bei 14 von 128 Schritten wechselt die Figur mitten im
# Schritt die Gestalt - Plattenritter gegen Wappenrock, bis zu 19 px Versatz an
# der Unterkante. Das ist der rutschende Soldat, den der Nutzer gemeldet hat.
# Huhn, Mutter und Schild bleiben bewusst draussen: Sie sind zwar ebenso
# gemischt, aber gemessen deckungsgleich (<= 0,5 px, dasselbe Motiv) - dort
# waere die Umstellung Aufwand ohne sichtbare Wirkung.
# anim_castle am 19.08.2026 dazugenommen, auf ausdrueckliche Ansage des
# Eigentuemers ("keine Crusader-Teile an Bergfrieden, Torhaeusern oder Tuermen").
# Dieselbe Krankheit wie beim rutschenden Soldaten, nur andersherum: 20 der 95
# Spenderframes sind in der Crusader-Leinwand zu gross und fallen deshalb auf
# das Crusader-Bild zurueck. Der Unterschied zu den Koerpergruppen ist der
# Geometriemodus - Bauwerke haengen an ihrem Kachelanker und brauchen den
# umgerechneten Pivot (`native_source_reanchored_v1`), nicht den uebernommenen.
REVIEW_NATIVE_GEOMETRY_139_GROUPS = frozenset(
    {"body_lord", "body_swordsman", "anim_castle"}
)


@dataclass(frozen=True)
class DerivedFrameContract:
    """Trusted 1.39 proof values for a group's complete derived partition."""

    expected_frame_count: int
    expected_discarded_mask_alpha: int
    expected_frame_proof_sha256: str


DERIVED_POLICY_139_CONTRACTS: dict[str, DerivedFrameContract] = {
    # These terrain groups combine geometry-identical source frames with a
    # small, explicitly frozen REPLACE_DERIVED partition.  The group manifest
    # still binds every target slot; this contract binds every frame that
    # requires target-canvas placement evidence.
    "tile_farmland": DerivedFrameContract(
        expected_frame_count=1,
        expected_discarded_mask_alpha=0,
        expected_frame_proof_sha256=(
            "ed10b8bff1670287f8ef5352c4eeee48"
            "04f84262e8c41341cc563c4114fa8a28"
        ),
    ),
    "tile_flatties": DerivedFrameContract(
        expected_frame_count=16,
        expected_discarded_mask_alpha=0,
        expected_frame_proof_sha256=(
            "674a86d52d77cd4ba4a3f13315dec2ca"
            "40c1cd2b8a4012ec100dd56bcfc94e80"
        ),
    ),
    "tile_cliffs": DerivedFrameContract(
        expected_frame_count=1,
        expected_discarded_mask_alpha=0,
        expected_frame_proof_sha256=(
            "e87643dbcde7eb68addf15d4bad8561e"
            "238759dbe2871e03183571a6d5b8b436"
        ),
    ),
    "anim_dog_cage": DerivedFrameContract(
        expected_frame_count=42,
        expected_discarded_mask_alpha=34680,
        expected_frame_proof_sha256=(
            "061aab55b387cd58721a9987d8cd3d480"
            "e8e3319bac2d661f007f7f17843b5da"
        ),
    ),
    "anim_tunnelors_guild": DerivedFrameContract(
        expected_frame_count=6,
        expected_discarded_mask_alpha=0,
        expected_frame_proof_sha256=(
            "a85b48ded34b07ce2231d45fc948a562"
            "728205ba273b13b709255c680b97404d"
        ),
    ),
}
DERIVED_POLICY_139_GROUPS = frozenset(DERIVED_POLICY_139_CONTRACTS)

SOURCE_REMAP_POLICY_MODE = "reviewed_cross_index_source_v1"
SOURCE_REMAP_PROOF_ALGORITHM = "cross_index_exact_canvas_rgba_blue_guard_v1"


@dataclass(frozen=True)
class SourceRemapFrameContract:
    """One reviewed SH1DE donor redirected into a different target slot."""

    target_name: str
    source_name: str
    target_path_id: int
    source_path_id: int
    expected_source_rgba_sha256: str
    expected_output_rgba_sha256: str
    expected_visible_blue_pixel_count: int


@dataclass(frozen=True)
class SourceRemapContract:
    """Pinned proof values for a complete per-group cross-index remap set."""

    source_texture: str
    target_texture: str
    frames: tuple[SourceRemapFrameContract, ...]
    expected_mapping_sha256: str
    expected_proof_sha256: str
    expected_source_rgba_sha256: str
    expected_output_rgba_sha256: str
    expected_visible_blue_pixel_count: int


@dataclass(frozen=True)
class FrameOverride:
    """One target slot exempted from its group's otherwise complete conversion.

    `donor` names the SH1DE frame to use instead; `None` keeps the Crusader
    frame.  Both spellings end in a state the pipeline already validates - a
    redirect becomes an ordinary proposal against a different donor, a keep
    becomes the same shape as a frame SH1DE never had.
    """

    target_name: str
    donor_name: str | None
    reason: str


# Ausnahmen je Gruppe. Eine Gruppe wird konvertiert, WEIL der europaeische
# Spender passt; hier stehen die Plaetze, an denen er nachweislich nicht passt.
# Das ist eine Entscheidung, keine Messung - die Messung, auf der sie beruht,
# steht in docs/BAUMDEFEKTE.md, und jede Aenderung an dieser Tabelle bricht die
# Nachweise ihrer Gruppe, bis neu gepinnt wird.
FRAME_OVERRIDES_139: dict[str, tuple[FrameOverride, ...]] = {}


def _tree_fell_overrides(
    group: str, terminal: Sequence[int], early: Sequence[int]
) -> tuple[FrameOverride, ...]:
    """Die Fällsequenz-Ausnahmen einer Baumgruppe, gemessen am 15.08.2026.

    Beide Spiele legen die 148 Bilder gleich an (0-99 vier Standschleifen,
    100-145 vier Fällsequenzen, 146 abgestorben, 147 Stumpf), und ueber die
    Standschleifen passt der Spender ueberall. In den Fällsequenzen nicht:

    `terminal` - Crusader laesst den Baum an Ort und Stelle zusammensinken und
    behaelt einen kleinen aufrechten Stumpf; Stronghold 1 kippt ihn um und legt
    einen GANZEN Baum quer, mit sichtbarer Saegeflaeche. An diesen Plaetzen ist
    der Spender das Zwei- bis Sechsfache der Slotbreite. Das ist die gemeldete
    Beobachtung "gefällte Bäume, die nie ein Holzfäller gefällt hat".

    `early` - der Stronghold-1-Baum faellt vier bis fuenf Bilder frueher. Bei
    `tree_pine` Index 121 steht bei Crusader eine noch weitgehend aufrechte
    Palme (96 % Resthoehe), geliefert wird ein bereits flach liegender
    Nadelbaum (46 %).

    Behalten, nicht umlenken - und zwar aus der Messung heraus: Innerhalb einer
    solchen Strecke fuehrt Stronghold 1 durchweg DASSELBE Bild (Tree_Chestnut
    112 bis 116 alle 340x180). Das vorhergehende Bild ist dort also derselbe
    liegende Baum, eine Umlenkung darauf gewaenne nichts. Crusaders eigene
    Sequenz ist an Crusaders eigenen Slots dagegen per Definition stimmig.
    """

    return tuple(
        FrameOverride(
            target_name=f"{group}-{index}",
            donor_name=None,
            reason=reason,
        )
        for indices, reason in (
            (terminal, "SH1DE lays a whole tree flat where Crusader keeps a stump"),
            (early, "SH1DE reaches the ground four to five frames early"),
        )
        for index in indices
    )


FRAME_OVERRIDES_139.update(
    {
        "Tree_Chestnut": _tree_fell_overrides(
            "Tree_Chestnut",
            terminal=(112, 113, 114, 115, 116, 128, 138, 145),
            early=(108, 120),
        ),
        # 138 steht in der Messtabelle als Randfall, wird aber mitgenommen: Es
        # ist das Schlussbild der Groessenklasse 3, und genau dort zeigen die
        # beiden anderen Gruppen den Defekt deutlich ueber der Schwelle.
        "tree_pine": _tree_fell_overrides(
            "tree_pine",
            terminal=(115, 116, 127, 128, 138),
            early=(120, 121, 122, 123, 132, 133, 134),
        ),
        "Tree_Oak": _tree_fell_overrides(
            "Tree_Oak",
            terminal=(115, 116, 138, 145),
            early=(),
        ),
        # Die Birke ist ein anderer Fall als die drei oben, und deshalb steht
        # sie hier gesondert: Nicht ihre Fällsequenz ist entartet, sondern die
        # Blöcke sind gegeneinander verschoben. Stronghold 1 führt für
        # tree_birch nur 73 Bilder (0-72), Crusader 148. Was bei Crusader an
        # 55-72 eine stehende SCHWINGSCHLEIFE ist, ist bei Stronghold 1 an
        # denselben Indizes bereits Fällsequenz - ein Baum, der im Wind stehen
        # soll, liegt dort quer.
        #
        # Nachgemessen am Mapping (Zielverhältnis < 0,95 und Quellverhältnis
        # > 1,15): 55-60, 66-70 und 72 kippen, das sind zwölf. Index 65 liegt
        # mit 1,11 knapp darunter und wird trotzdem mitgenommen - er ist das
        # Übergangsbild in die Strecke 66-70, und ihn allein europäisch zu
        # lassen ergäbe mitten in der Schleife einen Sprung vom kippenden zum
        # stehenden Baum.
        "tree_birch": tuple(
            FrameOverride(
                target_name=f"tree_birch-{index}",
                donor_name=None,
                reason=(
                    "SH1DE shows a felled birch where Crusader sways upright"
                ),
            )
            for index in (55, 56, 57, 58, 59, 60, 65, 66, 67, 68, 69, 70, 72)
        )
        # Die zweite Haelfte des Birkenproblems, geloest am 21.08.2026.
        # Stronghold 1 fuehrt fuer tree_birch nur 73 Bilder (0-72). Die Indizes
        # 73-147 blieben deshalb Dattelpalmen - darunter eine vollstaendige
        # stehende Groessenklasse, die so weiter auf der Karte stand.
        #
        # `Tree_Oak` fuehrt fuer dieselben Indizes europaeische Baeume und
        # dekodiert aus derselben Quelltextur `treeSprites`; die Umlenkung ist
        # damit zulaessig. Ausgenommen sind die vier Indizes, an denen Tree_Oak
        # selbst keinen Spender hat (115, 116, 138, 145) - dort waere die
        # Umlenkung wirkungslos und der Bauer wiese sie ab.
        + tuple(
            FrameOverride(
                target_name=f"tree_birch-{index}",
                donor_name=f"Tree_Oak-{index}",
                reason=(
                    "SH1DE has no birch beyond index 72; the oak of the same "
                    "index is European and shares the treeSprites texture"
                ),
            )
            for index in range(73, 148)
            if index not in (115, 116, 138, 145)
        ),
        # Der Lehmbau in tile_buildings2, umgelenkt am 21.08.2026,
        # auf das GANZE Kachelobjekt erweitert am 04.09.2026.
        #
        # Crusader fuehrt drei Varianten desselben flachdachigen Putzbaus mit
        # Dachbruestung - 1192-1207, 1208-1223 (mit Aussentreppe) und 1224-1239
        # (Stroh auf dem Dach). Stronghold 1 hat dafuer kein Gegenstueck; die
        # aufragenden Plaetze standen deshalb weiter als arabisches Haus auf
        # europaeischer Wiese (docs/ORIENTALISCHE_RESTE.md, Prioritaet hoch).
        #
        # Umgelenkt wird auf drei VERSCHIEDENE europaeische Haeuser derselben
        # Gruppe, damit aus drei Varianten nicht dreimal dasselbe Haus wird:
        #
        #     1192-1207 -> 010-025   weissgetuenchte Strohdachkate
        #     1208-1223 -> 781-796   Strohdachkate auf Holzstaendern
        #     1224-1239 -> 797-812   Strohdachkate, andere Dachform
        #
        # KORRIGIERT am 04.09.2026, nachdem der Eigentuemer die zweite und
        # dritte Huette erkannt hat: die bis dahin benutzten Bloecke 278-293
        # und 294-309 sind der KORNSPEICHER und die WAFFENKAMMER, nicht
        # Wohnhaeuser. Sie passten nur, weil `BuildingScales` fuer
        # MAPPER_HOVEL, MAPPER_GRANARY und MAPPER_ARMOURY dieselbe Kantenlaenge
        # 4 fuehrt - der Grundriss beweist also gar nichts ueber die Identitaet.
        # Mechanisch nachgezaehlt: ZWOELF Bloecke der Gruppe tragen denselben
        # Grundriss, davon lesen sich fuenf als Bauernkate (010, 765, 781, 797,
        # 813); der Rest sind offene Plattformen, ein Schmelzofen und ein
        # Kessel. Belegbild: work/huetten-2026-09-04/grundriss_bloecke.png.
        # NICHT belegt und offen: ob 765-828 die Huetten-Varianten von
        # Stronghold 1 sind oder Hofgebaeude - die Sprite-Auswahl je Bauwerk
        # ist nativ (CreatePrefab), im Dekompilat steht sie nicht.
        #
        # Zulaessig ist das, weil alle sechs Bloecke DASSELBE Kachelobjekt
        # tragen - gemessen, nicht angenommen: `part_count` 16 und `part_id`
        # 0..15 fortlaufend im klassischen GM1, gleiche relative Kachellage
        # aller 16 Teile, und in den ausgelieferten DE-Leinwaenden derselbe
        # Grundriss `GGGGGGRGGRRGRRRR` (G = flache 64x32-Raute, R = aufragend).
        #
        # WARUM ALLE 16 TEILE, seit 04.09.2026: Bis dahin waren nur die sieben
        # aufragenden Spalten je Block umgelenkt (Teile 6, 9, 10, 12, 13, 14,
        # 15), die neun flachen blieben Crusader. Das war falsch. Die flachen
        # Kacheln des Lehmbaus sind kein neutraler Boden, sondern sein
        # SANDPUTZ-SOCKEL und der Hofboden: eine niedrige Putzmauer, die ueber
        # vier Rauten laeuft, plus Sandflecken davor. Vor jedem europaeischen
        # Haus stand dadurch eine arabische Hofecke.
        #
        # Belegt am Testerfoto vom 04.09.2026 (Fehlerbote 2026-09-04_102407_b1c7,
        # "Fehler bei 3 Huetten"): Vorlagensuche im Bildschirmfoto findet an den
        # Bodenplaetzen aller drei Huetten die Crusader-Pixel mit Deckung 100 %
        # und mittlerer Abweichung 1,0-1,8 (Slots 1196/1199/1200/1203,
        # 1212/1215/1216/1219, 1228/1231/1232/1235), waehrend die aufragenden
        # Plaetze die europaeischen Spenderpixel zeigen.
        #
        # NICHT umgelenkt sind die uebrigen unveraenderten Bloecke derselben
        # Gruppe: 1182-1191 ist ein Wasserbecken, 1250-1264 und 1325-1359 sind
        # Zelte. Das Muster allein haette sie mitgenommen und aus dem Becken ein
        # Haus gemacht - erst der Blick auf die Bilder hat sie ausgeschlossen.
        "tile_buildings2": tuple(
            FrameOverride(
                target_name=f"tile_buildings2 {ziel + versatz}",
                donor_name=f"tile_buildings2 {spender + versatz:03d}",
                reason=(
                    "Crusader keeps a flat-roofed mud house where SH1DE has no "
                    "counterpart; redirect the whole 16-tile object to a "
                    "European house of the same tile footprint"
                ),
            )
            for ziel, spender in ((1192, 10), (1208, 781), (1224, 797))
            for versatz in range(16)
        ),
    }
)


def _mosque_to_church_overrides() -> tuple[FrameOverride, ...]:
    """Die drei Moscheen auf die drei Kirchen derselben Groessenklasse lenken.

    `tile_churches` fuehrt ZWEI vollstaendige Garnituren, und das ist gemessen,
    nicht vermutet: Die 741 Bilder zerfallen restlos in sieben quadratische
    Bloecke - 169 + 81 + 36 + 36 + 169 + 169 + 81 = 741. Die Seitenlaengen
    13/9/6 sind genau die Werte, die BuildingScales fuer MAPPER_CHURCH1/2/3
    fuehrt (BuildingScales.cs:827, 963, 999).

        christlich (Kreuz)   klein 251-286   mittel 170-250   gross   1-169
        islamisch (Halbmond) klein 287-322   mittel 661-741   gross 492-660
        Truemmer                                              gross 323-491

    Beide Garnituren haengen an DENSELBEN drei Mappern. Die Menueknoepfe
    ButtonBuildSmallChurch und ButtonBuildSmallMosque senden beide
    STRUCT_CHURCH1 und unterscheiden sich nur im Symbol (HUD_Main.xaml:644-731);
    umgeschaltet wird nach lord_Type in {1, 2, 6, 7}, den arabischen und
    beduinischen Lords (HUD_Main.cs:2291-2345). Es gibt also kein eigenes
    Moschee-Bauwerk - die Moschee ist dieselbe Kirche in anderer Haut.

    Daraus folgt der Weg: nicht Halbmonde wegretuschieren, sondern die
    Moschee-Plaetze auf die Kirchen-Plaetze derselben Groessenklasse umlenken.
    Die Mod ersetzt 1-286 bereits durch Stronghold-1-Grafik; die
    Mapping-Grenze faellt exakt auf die Blockgrenze 286/287. Umgelenkt wird
    damit auf bereits europaeisches Bild.

    Die Bloecke sind gleich gebaut, deshalb genuegt ein fester Versatz je
    Groessenklasse. Slotvertraeglichkeit gemessen: bei gross sind 148 der 169
    Plaetze hoehengleich, 18 Moschee-Plaetze hoeher (die Minarette) und drei
    um je 1 px niedriger; bei mittel drei Plaetze um 1 bis 3 px; bei klein
    neun Plaetze bis 24 px. Ob die niedrigeren sauber sitzen, entscheidet der
    Blick auf das gebaute Ergebnis - das ist ausdruecklich noch nicht gesehen.
    """

    blocks = (
        # (Moschee-Anfang, Moschee-Ende, Versatz zum Kirchenblock)
        (287, 322, -36),    # klein  -> 251-286
        (661, 741, -491),   # mittel -> 170-250
        (492, 660, -491),   # gross  ->   1-169
    )
    return tuple(
        FrameOverride(
            # Dreistellig mit fuehrenden Nullen - so heissen die Frames
            # tatsaechlich ("tile_churches 001"). Ohne Auffuellen findet die
            # Spendersuche die Bloecke 1-99 nicht, und die Gruppenpruefung
            # bricht ab. Sie tut das laut, das ist der Wachposten.
            target_name=f"tile_churches {index:03d}",
            donor_name=f"tile_churches {index + offset:03d}",
            reason="Mosque slot drawn from the European church of the same size",
        )
        for low, high, offset in blocks
        for index in range(low, high + 1)
    )


# ABGESCHALTET am 16.08.2026, nach dem ersten Bauversuch. Der Bauer weist die
# Umlenkung ab:
#
#     error: Source PathID/name mismatch: tile_churches 251 != tile_churches 287
#
# mod_builder prueft unabhaengig von der Gruppenpruefung, dass Spendername und
# Zielname uebereinstimmen. Der Umlenk-Zweig von FRAME_OVERRIDES_139 war damit
# nie durchgehend funktionsfaehig - die eine bestehende Umlenkung im Projekt
# (tile_cliffs 032 auf 031) laeuft ueber source_remap_policy, einen anderen
# Weg, den der Bauer kennt.
#
# Damit die uebrige Auslieferung nicht daran haengt, bleibt die Tabelle hier
# stehen und wird nicht eingehaengt. Zum Aktivieren fehlen ZWEI Dinge:
#   1. mod_builder muss den Umlenk-Fall kennen (die Namensgleichheitspruefung
#      darf fuer einen erklaerten Spender nicht greifen).
#   2. Das Blockmodell muss entschieden sein - ein zweiter Agent misst ein
#      dreieckiges Kachelraster statt quadratischer Bloecke.
# FRAME_OVERRIDES_139["tile_churches"] = _mosque_to_church_overrides()


# Der Lord ist die einzige ausgelieferte Gruppe, deren beide Spiele NICHT
# dieselbe Animationstabelle fuehren. Gemessen am Ladetabelleneintrag:
# Stronghold 1 meldet `addGMFile(959, "body_lord", ...)`, Crusader
# `addGMFile(1679, ...)` - 120 gegen 210 Phasen zu je acht Richtungen
# (Index = Phase * 8 + Richtung; nachgesehen an den Kontaktboegen: Frame 0-7
# ist eine volle Drehung derselben Pose).
#
# Ohne diese Tabelle wird jeder Platz vom Frame GLEICHEN NAMENS beliefert, und
# das ist nur fuer die ersten 32 Phasen richtig. Gegengeprueft an den Bildern
# beider Spiele:
#
#   Phase 0-15   beide: Gehen ohne Waffe          -> Namensgleichheit stimmt
#   Phase 16-31  beide: Gehen mit geschulterter Waffe
#   Phase 60-71  Crusader zeigt, Stronghold 1 schlaegt bereits zu
#   Phase 80-152 Crusader schlaegt mit der Axt, Stronghold 1 ist laengst
#                beim Sterben
#   Phase 153-179 beide: Waffe faellt zu Boden, Haende hoch, Zusammenbruch
#   Phase 180-209 Crusader steht ruhig - Stronghold 1 hat dafuer gar keine
#                Phasen mehr (ab 120 endet seine Tabelle)
#
# Daraus die beiden gemeldeten Fehler: der Lord spielte ab Phase ~36 die
# falsche Handlung, und ab Phase 120 (Frame 960) fehlte jeder Spender, sodass
# 720 Plaetze als Kreuzritter stehenblieben - er wechselte im Kampf und im Tod
# sichtbar die Gestalt.
#
# Die Zuordnung ist gemessen, nicht geschaetzt: Jede Phase beider Gruppen wurde
# in allen acht Richtungen ankerrichtig auf eine gemeinsame Leinwand gelegt
# (Pivot auf Pivot, native Groesse) und ueber die Alphamaske verglichen; aus
# der so entstandenen Abstandsmatrix (210 x 120) stammt die Zuordnung ueber
# eine monotone Verlaufsanpassung (DTW) in zwei Abschnitten - Bewegung/Kampf
# (Crusader 0-152 gegen Stronghold 1 0-95) und Sterben (153-179 gegen 96-119).
# Monoton, damit innerhalb eines Blocks kein Bild aus der Reihe faellt: eine
# laengere Crusader-Strecke haelt eine Stronghold-1-Phase, sie springt nie
# zurueck. Crusaders Ruhestrecke 180-209 haelt bewusst eine einzige Phase (0);
# eine Schleife dort hiesse, dass der Lord im Bergfried auf der Stelle geht.
LORD_ANIMATION_PHASE_MAP: tuple[int, ...] = (
    0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14,  # 0-14
    15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29,  # 15-29
    30, 31, 32, 32, 32, 32, 32, 32, 32, 33, 34, 35, 36, 36, 36,  # 30-44
    36, 36, 36, 36, 37, 38, 39, 40, 41, 42, 43, 44, 44, 44, 44,  # 45-59
    44, 44, 44, 45, 46, 47, 48, 49, 49, 50, 51, 51, 52, 52, 52,  # 60-74
    52, 52, 53, 54, 55, 56, 57, 57, 58, 58, 59, 59, 60, 60, 61,  # 75-89
    62, 62, 62, 62, 63, 63, 64, 64, 65, 66, 66, 66, 67, 67, 68,  # 90-104
    68, 69, 69, 70, 71, 71, 72, 72, 73, 73, 74, 74, 74, 75, 75,  # 105-119
    76, 77, 78, 79, 79, 79, 79, 79, 79, 80, 80, 80, 80, 80, 81,  # 120-134
    82, 82, 82, 82, 82, 83, 84, 85, 86, 87, 88, 89, 90, 91, 92,  # 135-149
    93, 94, 95, 96, 96, 96, 96, 97, 98, 99, 100, 101, 102, 103, 104,  # 150-164
    105, 106, 107, 108, 109, 110, 111, 112, 113, 114, 115, 116, 117, 118, 119,  # 165-179
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,  # 180-194
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,  # 195-209
)
LORD_ANIMATION_DIRECTIONS = 8
LORD_SOURCE_PHASE_COUNT = 120


def _lord_animation_overrides() -> tuple[FrameOverride, ...]:
    """Jede Hauptphase des Crusader-Lords auf die europaeische Phase derselben
    Handlung umlenken.

    Die Richtung bleibt unangetastet - umgelenkt wird nur die Phase, und zwar
    fuer alle acht Richtungen gleich. Phasen, die schon von sich aus stimmen
    (0-31), stehen nicht in der Tabelle; dort greift weiter die
    Namensgleichheit. Die Alt-Frames bleiben ebenfalls unberuehrt: beide Spiele
    fuehren dort genau 256 Bilder mit denselben Indizes.
    """

    if len(LORD_ANIMATION_PHASE_MAP) * LORD_ANIMATION_DIRECTIONS != 1680:
        raise GMAtlasError(
            "The lord animation map must cover all 1,680 main frames"
        )
    if any(
        not 0 <= donor < LORD_SOURCE_PHASE_COUNT
        for donor in LORD_ANIMATION_PHASE_MAP
    ):
        raise GMAtlasError(
            "The lord animation map names a phase Stronghold 1 does not have"
        )
    return tuple(
        FrameOverride(
            target_name=(
                f"body_lord-{phase * LORD_ANIMATION_DIRECTIONS + direction}"
            ),
            donor_name=(
                f"body_lord-{donor * LORD_ANIMATION_DIRECTIONS + direction}"
            ),
            reason=(
                "Crusader animation phase filled from the Stronghold 1 lord "
                "phase of the same action"
            ),
        )
        for phase, donor in enumerate(LORD_ANIMATION_PHASE_MAP)
        if phase != donor
        for direction in range(LORD_ANIMATION_DIRECTIONS)
    )


# Die Umlenkung ist bewusst KEIN Eintrag in FRAME_OVERRIDES_139: Jene Tabelle
# gilt fuer jede Gruppe dieses Namens, auch fuer die kleinen Pruefgruppen der
# Tests. Eine Umlenkung ueber 1.416 Plaetze darf nur greifen, wo das Profil sie
# ausdruecklich bestellt - genauso, wie es source_remap_policy handhabt.
ANIMATION_REMAP_POLICY_MODE = "reviewed_animation_phase_table_v1"
ANIMATION_REMAP_139_TABLES: dict[str, tuple[int, ...]] = {
    "body_lord": LORD_ANIMATION_PHASE_MAP,
}
_ANIMATION_REMAP_OVERRIDES: dict[str, tuple[FrameOverride, ...]] = {
    "body_lord": _lord_animation_overrides(),
}


def animation_remap_phase_digest(group: str) -> str:
    """Der Fingerabdruck der Phasentabelle, ueber den das Profil sie pinnt."""

    table = ANIMATION_REMAP_139_TABLES.get(group)
    if table is None:
        raise GMAtlasError(f"{group} has no reviewed animation phase table")
    return hashlib.sha256(
        "".join(
            f"{phase}\t{donor}\n" for phase, donor in enumerate(table)
        ).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class AnimationRemapPolicy:
    """Explicit profile opt-in to the reviewed animation phase table."""

    mode: str
    expected_phase_count: int
    expected_redirect_count: int
    expected_phase_map_sha256: str


def _parse_animation_remap_policy(
    raw: object, group: str
) -> AnimationRemapPolicy:
    if not isinstance(raw, dict):
        raise GMAtlasError(f"animation_remap_policy for {group} must be an object")
    expected_keys = {
        "mode",
        "expected_phase_count",
        "expected_redirect_count",
        "expected_phase_map_sha256",
    }
    if set(raw) != expected_keys:
        raise GMAtlasError(
            f"animation_remap_policy fields changed for {group}: "
            f"actual={sorted(raw)} expected={sorted(expected_keys)}"
        )
    if raw.get("mode") != ANIMATION_REMAP_POLICY_MODE:
        raise GMAtlasError(
            f"Unsupported animation_remap_policy mode for {group}: "
            f"{raw.get('mode')!r}"
        )
    table = ANIMATION_REMAP_139_TABLES.get(group)
    if table is None:
        raise GMAtlasError(f"{group} has no reviewed animation phase table")
    overrides = _ANIMATION_REMAP_OVERRIDES[group]
    actual = (len(table), len(overrides), animation_remap_phase_digest(group))
    expected = (
        raw.get("expected_phase_count"),
        raw.get("expected_redirect_count"),
        raw.get("expected_phase_map_sha256"),
    )
    if actual != expected:
        raise GMAtlasError(
            f"Animation phase table for {group} changed: "
            f"actual={actual} expected={expected}"
        )
    return AnimationRemapPolicy(
        mode=ANIMATION_REMAP_POLICY_MODE,
        expected_phase_count=len(table),
        expected_redirect_count=len(overrides),
        expected_phase_map_sha256=animation_remap_phase_digest(group),
    )


def _load_user_frame_overrides() -> None:
    """Eigene Umlenkungen der Universal-Suite (config/frame-overrides.local.json).

    Format: {"gruppen": {"<gruppe>": [{"ziel": "<name>", "spender": "<name>"
    oder null, "grund": "..."}]}}. Ein Eintrag ersetzt eine gleichnamige
    Zielzeile der Projekttabelle. Wie jede Aenderung an dieser Tabelle bricht
    er die Nachweise seiner Gruppe, bis neu gepinnt wird (tools/pin_digests.py).
    """

    path = Path(__file__).resolve().parents[2] / "config" / "frame-overrides.local.json"
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    for group, rows in (document.get("gruppen", {}) if isinstance(document, dict) else {}).items():
        extra: dict[str, FrameOverride] = {}
        for row in rows if isinstance(rows, list) else ():
            try:
                target = str(row["ziel"])
                donor = row.get("spender")
                extra[target] = FrameOverride(
                    target_name=target,
                    donor_name=None if donor in (None, "") else str(donor),
                    reason=str(row.get("grund") or "Benutzerumlenkung (Universal-Suite)"),
                )
            except (KeyError, TypeError):
                continue
        if not extra:
            continue
        kept = tuple(o for o in FRAME_OVERRIDES_139.get(group, ()) if o.target_name not in extra)
        FRAME_OVERRIDES_139[group] = kept + tuple(extra.values())


_load_user_frame_overrides()


def frame_overrides_for(group: str) -> tuple[FrameOverride, ...]:
    """The pinned per-frame exemptions of `group`, empty when it has none."""

    return FRAME_OVERRIDES_139.get(group, ())


def frame_overrides_for_spec(spec: "AtlasGroupSpec") -> tuple[FrameOverride, ...]:
    """Die Ausnahmen einer Gruppe samt der vom Profil bestellten Umlenkung."""

    overrides = frame_overrides_for(spec.gm_file_name)
    if spec.animation_remap_policy is not None:
        overrides = overrides + _ANIMATION_REMAP_OVERRIDES[spec.gm_file_name]
    return overrides


SOURCE_REMAP_139_CONTRACTS: dict[str, SourceRemapContract] = {
    # SH1DE's nominal tile_cliffs 032 is a 64x46 opaque blue mapper chevron,
    # not cliff art.  Slot 033 is absent and 034 starts the snow-cliff cohort.
    # The immediately preceding dark-cliff frame is therefore the conservative
    # Europe-only donor for Crusader's 64x334 dark-cliff target slot 032.
    "tile_cliffs": SourceRemapContract(
        source_texture="AllTileSprites",
        target_texture="AllTileSprites",
        frames=(
            SourceRemapFrameContract(
                target_name="tile_cliffs 032",
                source_name="tile_cliffs 031",
                # ZIELABHAENGIG: PathIDs sind Eigenschaft des Zielspiels.
                # 108905 gilt fuer SHC:DE 2.7, 108907 fuer 2.80 - gemessen am
                # 2.80-Mapping (work/mapping/proposals.json.gz, 04.09.2026).
                # Dieser Baum baut gegen 2.80; der StrongholdEuropeDE-Baum
                # (Ziel 2.7) traegt weiter 108905. Die Quellseite (SH1DE) ist
                # unveraendert.
                target_path_id=108907,
                source_path_id=4131,
                expected_source_rgba_sha256=(
                    "9b144e7dd325ef7376333c484f3b8613"
                    "a0e83d24d8fc901b440db96e2f935576"
                ),
                expected_output_rgba_sha256=(
                    "9b144e7dd325ef7376333c484f3b8613"
                    "a0e83d24d8fc901b440db96e2f935576"
                ),
                expected_visible_blue_pixel_count=0,
            ),
        ),
        # ZIELABHAENGIG wie die PathID darueber: beide Digests fassen die
        # PathIDs mit, die Pixel nicht (source/output_rgba bleiben gleich).
        # Werte fuer SHC:DE 2.80, gemessen am 04.09.2026; 2.7 trug
        # 6ef7d8d5... bzw. 267f01c5...
        expected_mapping_sha256=(
            "62a1d90f34c165f238c3099297747980"
            "826733ff5dc5859cbe660ee252cad8c5"
        ),
        expected_proof_sha256=(
            "27c7b0215081cec03f72e161074291ea"
            "84e1aab14dea3b1069a7aa88ec81267d"
        ),
        expected_source_rgba_sha256=(
            "6f4457f9a4338070d4200b8e39d8e40"
            "f7846a017d04b2ebef08716a81851f6bf"
        ),
        expected_output_rgba_sha256=(
            "75319576d2b953902195a36f508cdc74"
            "39bad46a3202ed032497199134cdfa7d"
        ),
        expected_visible_blue_pixel_count=0,
    ),
}


@dataclass(frozen=True)
class SourceRemapPolicy:
    """Explicit profile opt-in to an internally reviewed cross-index remap."""

    mode: str
    proof_algorithm: str
    expected_frame_count: int
    expected_mapping_sha256: str
    expected_proof_sha256: str
    expected_source_rgba_sha256: str
    expected_output_rgba_sha256: str
    expected_visible_blue_pixel_count: int

    @classmethod
    def from_profile(
        cls,
        raw: object,
        group: str,
        expected_group_frame_count: int,
    ) -> "SourceRemapPolicy":
        if not isinstance(raw, dict):
            raise GMAtlasError(
                f"source_remap_policy for {group} must be an object"
            )
        expected_keys = {
            "mode",
            "proof_algorithm",
            "expected_frame_count",
            "expected_mapping_sha256",
            "expected_proof_sha256",
            "expected_source_rgba_sha256",
            "expected_output_rgba_sha256",
            "expected_visible_blue_pixel_count",
        }
        if set(raw) != expected_keys:
            raise GMAtlasError(
                f"source_remap_policy fields changed for {group}: "
                f"actual={sorted(raw)} expected={sorted(expected_keys)}"
            )
        if raw.get("mode") != SOURCE_REMAP_POLICY_MODE:
            raise GMAtlasError(
                f"Unsupported source_remap_policy mode for {group}: "
                f"{raw.get('mode')!r}"
            )
        if raw.get("proof_algorithm") != SOURCE_REMAP_PROOF_ALGORITHM:
            raise GMAtlasError(
                f"Source remap proof algorithm for {group} changed: "
                f"{raw.get('proof_algorithm')!r}"
            )
        policy = cls(
            mode=SOURCE_REMAP_POLICY_MODE,
            proof_algorithm=SOURCE_REMAP_PROOF_ALGORITHM,
            expected_frame_count=_positive_int(
                raw, "expected_frame_count", group
            ),
            expected_mapping_sha256=_require_sha256(
                raw, "expected_mapping_sha256", group
            ),
            expected_proof_sha256=_require_sha256(
                raw, "expected_proof_sha256", group
            ),
            expected_source_rgba_sha256=_require_sha256(
                raw, "expected_source_rgba_sha256", group
            ),
            expected_output_rgba_sha256=_require_sha256(
                raw, "expected_output_rgba_sha256", group
            ),
            expected_visible_blue_pixel_count=_nonnegative_int(
                raw, "expected_visible_blue_pixel_count", group
            ),
        )
        if policy.expected_frame_count > expected_group_frame_count:
            raise GMAtlasError(
                f"Source remap frame count for {group} exceeds its target "
                f"manifest: {policy.expected_frame_count} > "
                f"{expected_group_frame_count}"
            )
        contract = SOURCE_REMAP_139_CONTRACTS.get(group)
        if contract is None:
            raise GMAtlasError(
                f"{group} has no reviewed source-remap contract"
            )
        expected = (
            len(contract.frames),
            contract.expected_mapping_sha256,
            contract.expected_proof_sha256,
            contract.expected_source_rgba_sha256,
            contract.expected_output_rgba_sha256,
            contract.expected_visible_blue_pixel_count,
        )
        actual = (
            policy.expected_frame_count,
            policy.expected_mapping_sha256,
            policy.expected_proof_sha256,
            policy.expected_source_rgba_sha256,
            policy.expected_output_rgba_sha256,
            policy.expected_visible_blue_pixel_count,
        )
        if actual != expected:
            raise GMAtlasError(
                f"Source remap contract for {group} changed: "
                f"actual={actual} expected={expected}"
            )
        return policy

# How a source frame is fitted into its target slot.
#
# `target_canvas` is the historical default and the conservative rule from
# AGENTS.md: the source is pasted onto a canvas of the Crusader size at the
# pivot-aligned offset, and any clipped non-transparent pixel fails the build.
#
# `native_source_reanchored_v1` keeps the source frame at its own size and instead
# recomputes the normalised pivot so the absolute anchor is unchanged:
#
#     pivot_x = (target_pivot_x * target_width)  / source_width
#     pivot_y = (target_pivot_y * target_height) / source_height
#
# Clipping then cannot occur, because the canvas is the art. This is sound only
# because `GameAtlasManagerAPI.ApplySingle` builds every overridden sprite from
# our atlas JSON — rect, pivot and pixels-per-unit are ours to choose — and
# because pixels-per-unit is identical on both sides for every measured frame.
# See docs/NATIVE_GEOMETRY_OPTION.md.
GEOMETRY_POLICY_TARGET_CANVAS = "target_canvas"
GEOMETRY_POLICY_NATIVE_REANCHORED = "native_source_reanchored_v1"
GEOMETRY_POLICY_NATIVE_AUTHORED_PIVOT = "native_source_authored_pivot_v1"
GEOMETRY_POLICIES = frozenset(
    {
        GEOMETRY_POLICY_TARGET_CANVAS,
        GEOMETRY_POLICY_NATIVE_REANCHORED,
        GEOMETRY_POLICY_NATIVE_AUTHORED_PIVOT,
    }
)
NATIVE_SOURCE_GEOMETRY_PROOF_ALGORITHM = (
    "native_source_rgba_target_anchor_float32_ppu_v1"
)
NATIVE_SOURCE_AUTHORED_PIVOT_PROOF_ALGORITHM = (
    "native_source_rgba_authored_pivot_float32_ppu_v1"
)
NATIVE_SOURCE_ANCHOR_TOLERANCE_PX = 1e-4

# Eck-Konvention der Sprite-Anker (gemessen 2026-09-04, siehe
# docs/TUERME_UND_TORHAEUSER.md, Abschnitt "Der Anker ist eine Ecke").
#
# `native_source_reanchored_v1` haelt den Anker als ABSTAND ZUR UNTEREN bzw.
# LINKEN Kante fest. Das ist richtig, solange der Anker von dort aus gemessen
# ist - bei den Kachelstreifen (`tile_*`, Pivot 16,5 px ueber der Unterkante)
# und bei den Fusspunkten der Einheiten trifft das zu.
#
# Es ist FALSCH, sobald der Zielslot seinen Anker an der OBEREN bzw. RECHTEN
# Kante fuehrt, also einen normalisierten Pivot von exakt 1,0. Dann ist nicht
# der Abstand nach unten die feste Groesse, sondern der nach oben - er ist
# null. Der bisherige Weg legt den Anker stattdessen `Zielhoehe` ueber die
# Unterkante der QUELLE und verschiebt das Bild damit um genau
# `Zielhoehe - Quellhoehe`.
#
# Das ist die Ursache der verrutschten Zinnenoverlays: `anim_castle` fuehrt
# alle Vordergrund- und Abschlussstuecke mit Pivot (0, 1). In BEIDEN Spielen.
# 27 Frames sind betroffen, die neun Vordergrundmasken der Tuerme (1-4),
# Torhaeuser (11-14) und des Bergfrieds (27) sitzen dadurch 18 bis 80 px zu
# tief, die Abschlussstuecke 2 bis 38 px zu hoch.
#
# Belegt an drei unabhaengigen Messungen:
#  1. Beide Spiele hinterlegen fuer diese Frames exakt Pivot (0, 1).
#  2. Silhouetten-Korrelation auf den Frames, deren Grafik in beiden Spielen
#     nahezu gleich ist (7, 9, 117, 126): der gemessene Versatz ist genau der,
#     den die Eck-Konvention vorhersagt, und nicht der ausgelieferte.
#  3. Feldfoto des Testers vom 27.08.2026 (Fehlerpaket 132922, "The Bulls eye",
#     STRUCT_TOWER4): die Maske `anim_castle 002` liegt dort mit
#     Korrelation 0,9991 bei Bildschirm-y 467, der Anker des Slots bei 449 -
#     18 px, also exakt `Zielhoehe - Quellhoehe` = 183 - 165.
#
# Absichtlich NICHT geaendert: Pivots ausserhalb [0,1] (der Zielausschnitt ist
# dann selbst ein Beschnitt einer groesseren Flaeche) und alle Bruchteil-Pivots
# (echte Layoutpunkte, etwa Fuesse). Der Schnitt bleibt damit auf die 27
# anim_castle-Frames begrenzt; projektweit gemessen aendert sich sonst nichts.
NATIVE_CORNER_PIVOT_EPSILON = 1e-6


def native_reanchored_anchor(
    target_pivot: float,
    target_size: float,
    source_size: float,
) -> float:
    """Absoluter Anker ueber der unteren bzw. linken Kante der QUELLE.

    Regelfall ist Crusaders Abstand zu dieser Kante. Fuehrt der Zielslot
    seinen Anker dagegen an der gegenueberliegenden Kante (normalisierter
    Pivot exakt 1,0), dann ist der Abstand DORTHIN die feste Groesse - er ist
    null, und der Anker liegt auf der Kante der Quelle.

    Beide Seiten - Erzeugung und Nachweis - rechnen ueber diese eine Funktion,
    damit sie nicht auseinanderlaufen koennen.
    """

    if abs(target_pivot - 1.0) <= NATIVE_CORNER_PIVOT_EPSILON:
        return source_size
    return target_pivot * target_size


def native_reanchored_anchor_y(
    target_pivot_y: float,
    target_height: float,
    source_height: float,
) -> float:
    """Senkrechter Anker; duenne Huelle um :func:`native_reanchored_anchor`."""

    return native_reanchored_anchor(target_pivot_y, target_height, source_height)

# A sparsely converted group keeps the Crusader art for every slot without a
# European donor.  Those frames are byte copies of the target sprite, not
# conversions, so they carry their own provenance block instead of entering the
# geometry or derived proofs.
SPARSE_KEEP_POLICY_MODE = "sparse_keep_crusader_target_copy_v1"
SPARSE_KEEP_PROOF_ALGORITHM = "target_sprite_rgba_copy_v1"

SHARED_GM_ATLAS_PROFILE_KEY = "shared_gm_atlases"
SHARED_GM_ATLAS_MODE = "shared_gm_atlas_v1"
SHARED_GM_ATLAS_KIND = "shcdese_shared_gm_atlas_1_39"


@dataclass(frozen=True)
class NativeSourceGeometryContract:
    """Pinned source-only proof values for a complete loader-owned GM array."""

    source_texture: str
    target_texture: str
    expected_frame_count: int
    expected_geometry_proof_sha256: str
    expected_origin_proof_sha256: str
    expected_source_rgba_sha256: str
    source_anchor_tolerance_px: float = NATIVE_SOURCE_ANCHOR_TOLERANCE_PX
    expected_source_anchor_max_error_px: float | None = None


@dataclass(frozen=True)
class SharedGMAtlasMemberContract:
    """One logical loader registration fused into a shared physical atlas."""

    gm_file_name: str
    slot_offset: int
    expected_frame_count: int
    expected_names_sha256: str
    expected_geometry_proof_sha256: str
    expected_origin_proof_sha256: str
    expected_source_rgba_sha256: str
    expected_source_anchor_max_error_px: float
    expected_runtime_anchor_max_error_px: float


@dataclass(frozen=True)
class SharedGMAtlasContract:
    """Pinned topology and source-only proof for one shared GM array."""

    host_gm_file_name: str
    gm_enum: str
    source_texture: str
    target_texture: str
    expected_frame_count: int
    expected_max_index: int
    expected_null_slot_count: int
    expected_combined_names_sha256: str
    expected_output_names_sha256: str
    expected_slot_logical_output_sha256: str
    expected_slot_logical_source_rgba_sha256: str
    members: tuple[SharedGMAtlasMemberContract, ...]


SHARED_GM_ATLAS_139_CONTRACTS: dict[str, SharedGMAtlasContract] = {
    # spriteLoader registers two folders into the same GM_NEW_SEA array.  The
    # host reserves the tenant's 816 slots; the tenant writes at ID_Offset
    # 2167.  SHCDE-SE's atlas override, however, allocates from one JSON and
    # always writes raw parsed indices.  The safe representation is therefore
    # one physical host atlas whose tenant frames use host-prefixed pseudo
    # names for slots 2168..2983.
    "tile_sea_new_01": SharedGMAtlasContract(
        host_gm_file_name="tile_sea_new_01",
        gm_enum="GM_NEW_SEA",
        source_texture="AllTileSprites",
        target_texture="AllTileSprites",
        expected_frame_count=1753,
        expected_max_index=2983,
        expected_null_slot_count=1231,
        expected_combined_names_sha256=(
            "9714764395ed6f77d443d60bc8c119e8"
            "96796b216ece60d37048f2320e1f4190"
        ),
        expected_output_names_sha256=(
            "52a2255fd429380f768a2c40f6f43176"
            "3a445d7aa75898baff59440b60f1f039"
        ),
        expected_slot_logical_output_sha256=(
            "a393ce810f33752b1c70b40fdb2169e3"
            "f817723e12890633b177cc23f6b84a11"
        ),
        expected_slot_logical_source_rgba_sha256=(
            "a1e300b06b38fc826857336c60e15d11"
            "ffd985c525ea67cabe47a2e6d6eba0ff"
        ),
        members=(
            SharedGMAtlasMemberContract(
                gm_file_name="tile_sea_new_01",
                slot_offset=0,
                expected_frame_count=937,
                expected_names_sha256=(
                    "36c20f221da9f1a693739101326cbe0a"
                    "7ebac74681297ab6341f145203e856b2"
                ),
                expected_geometry_proof_sha256=(
                    "3131901f474606fd9d02863ed4a19881"
                    "61ecc9b8ecceed6c69d5651314f253b9"
                ),
                expected_origin_proof_sha256=(
                    "6bb4fe3b6db9b1d3f22832735e107391"
                    "b3308cd881d3986e49ecba898524db78"
                ),
                expected_source_rgba_sha256=(
                    "532cf898889d6526c818e409da0bab263"
                    "313c08959e3ce57b72903176828866b"
                ),
                expected_source_anchor_max_error_px=6.526708602905273e-05,
                expected_runtime_anchor_max_error_px=5.960464477539062e-07,
            ),
            SharedGMAtlasMemberContract(
                gm_file_name="tile_sea_shore",
                slot_offset=2167,
                expected_frame_count=816,
                expected_names_sha256=(
                    "c5957aa67e7fcf92d8ae1ab6f7f14e95"
                    "e9efff237b9d16222381e4c1e4346e72"
                ),
                expected_geometry_proof_sha256=(
                    "1c91751939814e3c9306c37a0aab5a70"
                    "3b48285cc4a902c05345c9e71684ba9a"
                ),
                expected_origin_proof_sha256=(
                    "1c454a5c012fc666641e673fbcdfe41f4"
                    "77414d4a1acd6e488cf719469485b78"
                ),
                expected_source_rgba_sha256=(
                    "648f098ae7bc2e9b274d9a7e4581966d"
                    "d0ed175e7d63ab0350df8bc3bca3af78"
                ),
                expected_source_anchor_max_error_px=0.0,
                expected_runtime_anchor_max_error_px=0.0,
            ),
        ),
    ),
}


NATIVE_SOURCE_REANCHORED_139_CONTRACTS: dict[
    str, NativeSourceGeometryContract
] = {
    "anim_buildings2": NativeSourceGeometryContract(
        source_texture="anims1Sprites",
        target_texture="anims1Sprites",
        expected_frame_count=123,
        expected_geometry_proof_sha256="34163d017615b03dcd8644510b53831e00f67a9d403843b019104382aa6abc76",
        expected_origin_proof_sha256="fb3ded6f1f4d913ba84a92d2f206463277c0e71df69fed0fa0312e6edde83dd6",
        expected_source_rgba_sha256="5bbbf6fc3108a8f3bd8592a1e363dfbc1b73d144588ef12adecdfda869c59f72",
        source_anchor_tolerance_px=0.51,
    ),
    # Tuerme, Torhaeuser und der Bergfriedaufbau. Unter `target_canvas` fielen
    # 20 der 95 Spenderframes mit BLOCKED_ALPHA_CLIP auf Crusader zurueck, weil
    # Europas Mauern Zinnen tragen und in Crusaders Leinwand nicht passen
    # (docs/TUERME_UND_TORHAEUSER.md, Ursache 1). Die Vorbedingung des nativen
    # Weges ist dort gemessen: Pixel pro Einheit sind auf allen 95 gemeinsamen
    # Frames beidseitig 64,0. Der Modus laesst die Quellleinwand stehen und
    # rechnet nur den Pivot um; klippen kann dann kein Frame mehr.
    "anim_castle": NativeSourceGeometryContract(
        source_texture="AllTileSprites",
        target_texture="anims1Sprites",
        expected_frame_count=95,
        expected_geometry_proof_sha256=(
            "f0be1cb1beb096ff4d518bd48dfa4ee23ec86382a1e7ea14edd1b07a8dd88152"
        ),
        expected_origin_proof_sha256=(
            "7fc71756f809738686a270b71d3a107e7eae97dfd913c729bd3ad5be72468298"
        ),
        expected_source_rgba_sha256=(
            "4a08b4309e74089447d082b75411fe31956a9a2107bfc809cda4ebb7d590cf20"
        ),
        # Hier ist die Toleranz ausnahmsweise gross, und das ist gemessen, nicht
        # nachgegeben: 32 der 95 Frames verankern die beiden Spiele an
        # verschiedenen Enden derselben Leinwand. Die Mauerschaefte 106-121
        # (64x260 auf beiden Seiten, dasselbe Motiv, nur anderes Material)
        # tragen in Stronghold 1 den Pivot (0,1) und in Crusader (0,0) - macht
        # exakt 260 px Unterschied. Das ist eine Konvention der Datensaetze,
        # keine Verschiebung des Bildes: geliefert wird nach Crusaders Anker,
        # weil Crusaders Engine zeichnet. Die eigentliche Schranke bleibt
        # `expected_geometry_proof_sha256` - dort steht jede einzelne Zahl jeder
        # Zeile drin, ein abweichender Pivot faellt sofort auf. Zusaetzlich ist
        # das beobachtete Maximum unten exakt festgenagelt.
        source_anchor_tolerance_px=260.0,
        expected_source_anchor_max_error_px=260.0,
    ),
    "tile_land8": NativeSourceGeometryContract(
        source_texture="AllTileSprites",
        target_texture="AllTileSprites",
        expected_frame_count=512,
        expected_geometry_proof_sha256=(
            "98079c48fba72cfd1637956c50ed38f9"
            "24d6878ba8bab30fdba0cb4710111fb6"
        ),
        expected_origin_proof_sha256=(
            "53999249225a145f95dad648bf01c4ddc"
            "e44e2ffd2c6571f359feebe44f0ee7b"
        ),
        expected_source_rgba_sha256=(
            "8911b594479884be599c0c4b7140267c"
            "4d3d8098e3c4ffd519a3434d0c3be746"
        ),
    ),
    "tile_workshops": NativeSourceGeometryContract(
        source_texture="AllTileSprites",
        target_texture="AllTileSprites",
        expected_frame_count=2016,
        expected_geometry_proof_sha256=(
            "64109fdd845b1b3338d213bf203afc02"
            "6d80c89f4ed961fd379a7608c2466039"
        ),
        expected_origin_proof_sha256=(
            "2814b9e841a930134c787a88dd401374"
            "41ccdb9ba3f5611c88b078df683cc968"
        ),
        expected_source_rgba_sha256=(
            "ae6c3f55f3e53741c368f5697d08da6"
            "e765020949f3aa1dc67a205dae870a0e2"
        ),
        # The source and target pivots for 401 derived frames differ by one
        # half-pixel (plus inventory float noise).  The emitted float32 pivot
        # is still computed from, and lands on, the target anchor; this bound
        # applies only to the separately reported SH1DE-vs-SHCDE source delta.
        source_anchor_tolerance_px=0.501,
        expected_source_anchor_max_error_px=0.5001575499773026,
    ),
    "tile_sea8": NativeSourceGeometryContract(
        source_texture="AllTileSprites",
        target_texture="AllTileSprites",
        expected_frame_count=1159,
        expected_geometry_proof_sha256=(
            "a39d976b8d67ef4853d2df458a93906e"
            "9161f6957a0dfbac3bd4035d3ac44aec"
        ),
        expected_origin_proof_sha256=(
            "c2f958707beb196c553cfd91a3ecc066"
            "16ea4b02bb24da6b641dfcd49b0434b5"
        ),
        expected_source_rgba_sha256=(
            "122dc5c3ab398569c4f5aa396c716980"
            "89ac0bf65092c59f29ca5ad37e9c31f3"
        ),
        expected_source_anchor_max_error_px=2.9981136322021484e-05,
    ),
    # Castle, churches and the first building array. Same sparse arrangement as
    # tile_buildings2 below: the European frames carry the geometry proof, the
    # donor-less slots are verbatim Crusader copies and stay out of it. Digests
    # are placeholders until the first build reports the measured values; the
    # build fails closed against them, so a placeholder cannot ship unreviewed.
    "tile_churches": NativeSourceGeometryContract(
        source_texture="AllTileSprites",
        target_texture="AllTileSprites",
        # 286 bis zum 16.08.2026: damals deckte der Nachweis nur die drei
        # christlichen Bloecke 1-286. Seit die drei Moschee-Bloecke auf sie
        # umgelenkt werden, kommen 286 weitere Plaetze aus Europa - 572.
        # Es bleiben die 169 Truemmerkacheln 323-491 bei Crusader.
        expected_frame_count=286,
        expected_geometry_proof_sha256="fb355abc70c4769392ed59e1bd7c8daa70ca1963575c75712e34edf155ff8639",
        expected_origin_proof_sha256="65a8e75e5fdf28274c30ca43ff5f36e51787278e75511d4f6de18f440cb51fc5",
        expected_source_rgba_sha256="7461987c2d3c69f51158a2aa9ffeb10f84be0ccd1fcf0948a70338fe91bdd6d2",
        source_anchor_tolerance_px=0.51,
    ),
    "tile_buildings1": NativeSourceGeometryContract(
        source_texture="AllTileSprites",
        target_texture="AllTileSprites",
        expected_frame_count=430,
        expected_geometry_proof_sha256="75ee3a46caa7c5202e92cf4c87a1b9eac5881463d13d0795813b604e8acd2722",
        expected_origin_proof_sha256="732eecdeb332d8065bfdd6e6dd9e3f668d97a68148474e29c5649a7123654678",
        expected_source_rgba_sha256="2ff489de2aad1a6a52718819342eab38b78d001456a5c503d47bb4f9e9799e0f",
        source_anchor_tolerance_px=0.51,
    ),
    "tile_buildings2": NativeSourceGeometryContract(
        source_texture="AllTileSprites",
        target_texture="AllTileSprites",
        # 1066 bis zum 04.09.2026: damals waren nur die sieben aufragenden
        # Teile je Lehmbau-Block umgelenkt. Seit die drei Bloecke vollstaendig
        # umgelenkt werden, kommen 27 Bodenkacheln dazu - 1093.
        expected_frame_count=1093,
        expected_geometry_proof_sha256="4b9f71a839447d6e881758daca31b2d921897a7ae5460315532dd37104596227",
        expected_origin_proof_sha256="bd82bd016c4066d5119e9a492c0f722ce26b34631007cc000707a76d1400a723",
        expected_source_rgba_sha256="366fa92c7f974441af1f9937f175c5a716678a5ce664d32a7d1dd8894604557d",
        # Terrain re-anchors exactly, buildings do not.  Two classes were
        # measured here: 1.1e-4 px of float32 rounding, and a real half-pixel
        # offset where the SH1 sprite sits on the other side of a pixel
        # boundary.  On an isometric tile that is invisible, and the bound
        # stays below a whole pixel so genuine misplacements still fail.
        source_anchor_tolerance_px=0.51,
    ),
    "tile_castle": NativeSourceGeometryContract(
        source_texture="AllTileSprites",
        target_texture="AllTileSprites",
        expected_frame_count=1207,
        expected_geometry_proof_sha256="e73213e49531d1e68099d84e86b771abb820002da2dcc5e3cd8872b321441b2c",
        expected_origin_proof_sha256="2540e9a6b5b1ab7990aafe6443e8de6e3b33dd3beabfc056ccd1406aeea16329",
        expected_source_rgba_sha256="ac20342436dea66f416f3df407a41f36ad297f845aad92af79f88eaedbc6c09f",
        source_anchor_tolerance_px=0.51,
    ),
    "tile_land_macros": NativeSourceGeometryContract(
        source_texture="AllTileSprites",
        target_texture="AllTileSprites",
        expected_frame_count=1648,
        expected_geometry_proof_sha256=(
            "b77d87b893dcde102e859ac7bd20b941b"
            "6ad44337f3c7e63c67a42506da60b60"
        ),
        expected_origin_proof_sha256=(
            "4e7c0d307739686cdbd177e43e142a12"
            "42c0da16c8b6df86121b5b2faea7fe29"
        ),
        expected_source_rgba_sha256=(
            "a15824f4665cc4f5be7ce46ee82ea3eb"
            "d86546b31f7c2b8774615559c414c0de"
        ),
    ),
    "tile_goods": NativeSourceGeometryContract(
        source_texture="AllTileSprites",
        target_texture="AllTileSprites",
        expected_frame_count=1032,
        expected_geometry_proof_sha256=(
            "099e929ef65584d88cb8910afade0ade"
            "12a2b835bad080790c655fe957e29b1e"
        ),
        expected_origin_proof_sha256=(
            "a20062f59c014ae9d46f61b82cb0094c"
            "6117d71da860e92742c335b7c85abb80"
        ),
        expected_source_rgba_sha256=(
            "7ecf80f28ee5bd5dd442ae19103acf3e"
            "e5cc4264e5c1a6017b64a4363d5d7b25"
        ),
    ),
    "tile_land3": NativeSourceGeometryContract(
        source_texture="AllTileSprites",
        target_texture="AllTileSprites",
        expected_frame_count=195,
        expected_geometry_proof_sha256=(
            "107d6de6ae91b105ccb695a9cbf4ebe8"
            "964c976a58b00df3a23135f44f8e0663"
        ),
        expected_origin_proof_sha256=(
            "42fec7bf240c873d9c81ffd173eca387"
            "bc5be0f069b5b65cd968999726317423"
        ),
        expected_source_rgba_sha256=(
            "08219d1cd53e945164d53a847c58f780"
            "e1dce5bab4425f31d25c8aa2f8bf4c3c"
        ),
    ),
}


NATIVE_SOURCE_AUTHORED_PIVOT_139_CONTRACTS: dict[
    str, NativeSourceGeometryContract
] = {
    # Drei Gruppen, die im Spiel an Burg und Landschaft sichtbar sind und im
    # Profil fehlten: die Banner, das Geroell und die Ruinen. Alle drei liegen
    # beidseitig im selben Atlas und laufen deshalb ueber den Sparse-Pfad; die
    # Digests sind gemessen, nicht geschaetzt.
    "anim_flags": NativeSourceGeometryContract(
        source_texture="anims1Sprites",
        target_texture="anims1Sprites",
        expected_frame_count=128,
        expected_geometry_proof_sha256="0bec2a2a760032058fc31c369e120be16a6e496ffcc2aad02025401a2a052916",
        expected_origin_proof_sha256="eff88c6abba40731b5f345fd5fe29a2ac066c0735350534e8b994b0f3d387c54",
        expected_source_rgba_sha256="162192d65fa9906c5489079b25912c4e2ae04402d42ecf76aec7061094ddd17f",
        source_anchor_tolerance_px=0.51,
    ),
    "tile_rocks8": NativeSourceGeometryContract(
        source_texture="AllTileSprites",
        target_texture="AllTileSprites",
        expected_frame_count=544,
        expected_geometry_proof_sha256="199db2c9f451405b1df27e2da27c430c22b24386eb1eeb3a728c1c65afc1f810",
        expected_origin_proof_sha256="65cdf09e333270b6f61f8ef3a6e3bfb831501ad932de9132fbf9bc27ae19cf7e",
        expected_source_rgba_sha256="9367e9dcfd17dd6ac309a2488d6e6e128778baada87f5040e553266424bf1ee9",
        source_anchor_tolerance_px=0.51,
    ),
    "tile_ruins": NativeSourceGeometryContract(
        source_texture="AllTileSprites",
        target_texture="AllTileSprites",
        expected_frame_count=100,
        expected_geometry_proof_sha256="ce5d734f83e1b18ea8ac69bb64f3470a988e8b0de3710d88248d33b84a18337f",
        expected_origin_proof_sha256="17cb141d07551e455dca2849134ce4db943eb89a7a173710e577b86da9c3ab5c",
        expected_source_rgba_sha256="43e47195592992cc42a1666c4d1552872d35344d40d86ae507276d28cfe26c6e",
        source_anchor_tolerance_px=0.51,
    ),
    "anim_stocks": NativeSourceGeometryContract(
        source_texture="anims1Sprites",
        target_texture="anims1Sprites",
        expected_frame_count=7,
        expected_geometry_proof_sha256="40507bed45a9ffe71d5deb1908933b30073f92510c61d0ea0e74e080d27b474e",
        expected_origin_proof_sha256="cdf6d543a2d4e8a934c0252d871ab60491517c5f28f1522525f7ebbd768d4202",
        expected_source_rgba_sha256="c567c82f677f9c1823f3aaafc7f18b758e4c82d1b503de69958a8ed841eb6cf7",
        source_anchor_tolerance_px=0.51,
    ),
    "float_pop_circ-2": NativeSourceGeometryContract(
        source_texture="anims1Sprites",
        target_texture="anims1Sprites",
        expected_frame_count=8,
        expected_geometry_proof_sha256="ea97ff91a4de901fd403016b34c849018a11d09e4622300f5d680ac786fffb65",
        expected_origin_proof_sha256="85f29dd8e5a207181783531c3865d9fa2a62fdace89f86d7c84fa07ec313994e",
        expected_source_rgba_sha256="1274c0ed31a588ba0a5f3b97eb4b3eb6cc67f1d2a39fd0486575f52cee6ad148",
        source_anchor_tolerance_px=0.51,
    ),
    "body_brazier": NativeSourceGeometryContract(
        source_texture="body4Sprites",
        target_texture="body4Sprites",
        expected_frame_count=8,
        expected_geometry_proof_sha256="3abeaa036c97d717eaa8b0c754c25d9c2580a8ed120424d61954e4ac0e6dba55",
        expected_origin_proof_sha256="572f8beaf0300f18e51f6491b3d7a3cbf466736e3b7d91a6fe926e78ca0f046e",
        expected_source_rgba_sha256="e43e5768200c5c7ddad197b6a39bd02ecf29d54ef41ff3af67660ddedc34d11b",
        source_anchor_tolerance_px=0.51,
    ),
    "anim_ducking_stool": NativeSourceGeometryContract(
        source_texture="anims1Sprites",
        target_texture="anims1Sprites",
        expected_frame_count=10,
        expected_geometry_proof_sha256="933771012cc83f7001b7a6a7c8b2cc47849f2c5c8333d49c0fb495ef8398faf6",
        expected_origin_proof_sha256="2ea6bfd565a1044f5443062e8c12948e6bfaabb8e9f667a88cfa3e1d217bba03",
        expected_source_rgba_sha256="a70407677a5b2fa74fc79e43a06d981ad6b02a96b288baf27407079799f99cab",
        source_anchor_tolerance_px=0.51,
    ),
    "anim_dungeon": NativeSourceGeometryContract(
        source_texture="anims1Sprites",
        target_texture="anims1Sprites",
        expected_frame_count=13,
        expected_geometry_proof_sha256="4d9caef40a4df23bdce4df462dab8ba830fc5ea6871ce9aeadff9a3bf75dca5b",
        expected_origin_proof_sha256="b2ce5f9e69faef298d9fa5cd0dab8e5588ebddb6193bc103441ec1419cab1453",
        expected_source_rgba_sha256="02003f25f4ee6ae2985830ab1c72973f08a2d630f984a09d753b34614a282b70",
        source_anchor_tolerance_px=0.51,
    ),
    "puff of smoke": NativeSourceGeometryContract(
        source_texture="body7Sprites",
        target_texture="body7Sprites",
        expected_frame_count=16,
        expected_geometry_proof_sha256="dcf62583ef50a0aa05d30d24b458ccda75295ed65352ab32f1c33775a4d8fabb",
        expected_origin_proof_sha256="e1abc5f7e31dfaccff0723ba06dda154ccc40d1733ceb0737c48766ab5861be7",
        expected_source_rgba_sha256="8c976b89848ecd4a878e31b0ba6655c96035216e9bbeba1226264d7a488019b7",
        source_anchor_tolerance_px=0.51,
    ),
    "body_steam": NativeSourceGeometryContract(
        source_texture="body7Sprites",
        target_texture="body7Sprites",
        expected_frame_count=16,
        expected_geometry_proof_sha256="91fa2c0e25342f67b1c4a4e5201bba9cf9c1cb4c6fca228288fa4683bbe51239",
        expected_origin_proof_sha256="8969417a544c841d80829418bb65b488c5f6eb6f29dab2ca00b8bd9a7b2d67b6",
        expected_source_rgba_sha256="d54f284234b45db488fa97914b1fda2b26c272d861d11b5dbb76e2b2b008d711",
        source_anchor_tolerance_px=0.51,
    ),
    "anim_shields": NativeSourceGeometryContract(
        source_texture="anims1Sprites",
        target_texture="anims1Sprites",
        expected_frame_count=16,
        expected_geometry_proof_sha256="690c56353ea2dc27d432846dc8e7c56370ce1a2d754e4650ac52be1b3374a658",
        expected_origin_proof_sha256="84f3f4be33174dbb34f078f586e2ef71ea3845173274b0908d89c94c0fd950cf",
        expected_source_rgba_sha256="afcd2379c27706f7d7be5c92baefc5589eac9b14de5b3d3afb31f1c309b16827",
        source_anchor_tolerance_px=0.51,
    ),
    "anim_armourer": NativeSourceGeometryContract(
        source_texture="anims1Sprites",
        target_texture="anims1Sprites",
        expected_frame_count=16,
        expected_geometry_proof_sha256="e1f83485a0b706aa51ea74cc65b8cc27e9e77f27f8753ea8b6645930bee7f108",
        expected_origin_proof_sha256="580e0a73d26b4f810ee4b14390bd90fba5513923f603e557275fb1c42d875d07",
        expected_source_rgba_sha256="e80e4a46bafe4feb6a9c0248c48e17cb0264112007ec247e41562525b2eed532",
        source_anchor_tolerance_px=0.51,
    ),
    "body_animal_burning_small": NativeSourceGeometryContract(
        source_texture="body7Sprites",
        target_texture="body7Sprites",
        expected_frame_count=17,
        expected_geometry_proof_sha256="7794c19d4b97959f39b644f59746ef34e37c2fd254dc20939581c79c67fa36ec",
        expected_origin_proof_sha256="9c1fafa7fa88982b6e9a309dd1e432375c7fbeb91c9a1fa794017c987919685d",
        expected_source_rgba_sha256="fe75ed350924029d8125db0cc95f2d5528ae597e65cf08ddd27fd566dd00f2cd",
        source_anchor_tolerance_px=0.51,
    ),
    "anim_gibbet": NativeSourceGeometryContract(
        source_texture="anims1Sprites",
        target_texture="anims1Sprites",
        expected_frame_count=17,
        expected_geometry_proof_sha256="2df92e52a72bd947cc274f88995dacf9c7f0e309532580ac9668be5d52671a33",
        expected_origin_proof_sha256="daa956dafaa278b49d3fd90df8bf8b87bf0e11f4a732fff55fa1c7317e29fe34",
        expected_source_rgba_sha256="dd9e29da4c4ff7a173c102068b58ec179a90eaae60d7a00968f9039f9f6371aa",
        source_anchor_tolerance_px=0.51,
    ),
    "anim_market": NativeSourceGeometryContract(
        source_texture="anims1Sprites",
        target_texture="anims1Sprites",
        expected_frame_count=18,
        expected_geometry_proof_sha256="6ad888e0593c6412466bf8ab4a94f3fce8fc57b5f3a115057555457810bf0648",
        expected_origin_proof_sha256="acb96531c2dee72becec3f90bd153d1083b66e04f63023f7a9c8c2a4cdd022e0",
        expected_source_rgba_sha256="6d64302b8de0ec5066fb29c3134b6800c8707996807225d72b7c62f5b7207cb3",
        source_anchor_tolerance_px=0.51,
    ),
    "anim_stake": NativeSourceGeometryContract(
        source_texture="anims1Sprites",
        target_texture="anims1Sprites",
        expected_frame_count=20,
        expected_geometry_proof_sha256="862bbcfa079e25d9b5d96c51325eeda66464b66f7af8755fb5cec32a44030149",
        expected_origin_proof_sha256="a7e4346633d36f3aff131d8ba8d6523837d6ea347b74d64a05c4bbe47317cb03",
        expected_source_rgba_sha256="05b7684361d0a96e1801faf04cbe5ba53eac5b30cd245e3100fe09c88b88d1a6",
        source_anchor_tolerance_px=0.51,
    ),
    "anim_gallows": NativeSourceGeometryContract(
        source_texture="anims1Sprites",
        target_texture="anims1Sprites",
        expected_frame_count=20,
        expected_geometry_proof_sha256="51c19df451e1e962a0123102bec01773fc62c0f235874ef2dc979a5eb0c6adca",
        expected_origin_proof_sha256="c1471e0a093249d7bdc9726778cc2b4e835a5a5a7a228d3cc99bd4cda9db30b5",
        expected_source_rgba_sha256="2dec04d564a6934bec5da7f4125f32e920859e2d7897c97c402282fe544e2e71",
        source_anchor_tolerance_px=0.51,
    ),
    "body_animal_burning_big": NativeSourceGeometryContract(
        source_texture="body7Sprites",
        target_texture="body7Sprites",
        expected_frame_count=21,
        expected_geometry_proof_sha256="7e60a86ae62fa15e03f4137dce6162dd512303dfc07ff3a91e3d561a69be701f",
        expected_origin_proof_sha256="700ca8a53c97bad22edc9b06986ee757e8068d7f2eca4c7167821668d10f3e58",
        expected_source_rgba_sha256="8bca9aa5010a09013f0096da89a02ff7274449097d55f2b51f6272c5f13938ca",
        source_anchor_tolerance_px=0.51,
    ),
    "anim_rack": NativeSourceGeometryContract(
        source_texture="anims1Sprites",
        target_texture="anims1Sprites",
        expected_frame_count=21,
        expected_geometry_proof_sha256="cec5b4a5741a8a39f873c38d47a9fd033c68265a1271dda48eda312522709327",
        expected_origin_proof_sha256="b780fad45afcf090a5f2ba57aaebe9c4cfa9063276f4f16f4b7cd8af37208225",
        expected_source_rgba_sha256="99e6d77752ba9476bb8b44bca68baa58e540efee2cbae1b628db268f0ec8e3d8",
        source_anchor_tolerance_px=0.51,
    ),
    "anim_chopping_block": NativeSourceGeometryContract(
        source_texture="anims1Sprites",
        target_texture="anims1Sprites",
        expected_frame_count=21,
        expected_geometry_proof_sha256="72cd5e4a2691ca741b3388c554ac7dc21450b1647d2e08e781db2b301eba716c",
        expected_origin_proof_sha256="7af46eb5b56438d712d0bcf32fe324aee971f2eea60b5e531a3495b5d8fd828d",
        expected_source_rgba_sha256="eff1565d1014041f60e2c13747e9bef3b85bd99adac8f168043afbf3282bc6f7",
        source_anchor_tolerance_px=0.51,
    ),
    "anim_woodcutter": NativeSourceGeometryContract(
        source_texture="anims1Sprites",
        target_texture="anims1Sprites",
        expected_frame_count=25,
        expected_geometry_proof_sha256="83d381957e44ac87f79bd43a1b68a2bfbee1c7c685ce9cc68dfd6c8d59e781fb",
        expected_origin_proof_sha256="d8282e53e5c35ab6fd1366470d9eccfa49560250b39e54ad3cb68031cd915969",
        expected_source_rgba_sha256="ac801ded797c0c869eb99dbe1361cd8ed4cf8565e9db563c9e546c8d34086ada",
        source_anchor_tolerance_px=0.51,
    ),
    "anim_hunter": NativeSourceGeometryContract(
        source_texture="anims1Sprites",
        target_texture="anims1Sprites",
        expected_frame_count=25,
        expected_geometry_proof_sha256="6ea307aaa76bd4014c266d7979cd66bd4162ef41c67e9b8466df3638730b1576",
        expected_origin_proof_sha256="e679f6bcb468342861acbf41dd20fc3200641307eb48c9b58daa73a4c7cacc57",
        expected_source_rgba_sha256="18a761098ecdd8dfba56b472b550bc7a727764cea6ab8fa80b505a2934885cb8",
        source_anchor_tolerance_px=0.51,
    ),
    "body_missile_cow": NativeSourceGeometryContract(
        source_texture="body7Sprites",
        target_texture="body7Sprites",
        expected_frame_count=29,
        expected_geometry_proof_sha256="2ec42620093a05d190939b42b524c831f93612db53a31d0cd3ddc34f9df1c074",
        expected_origin_proof_sha256="fdfdb90d8fb6a6d73fca0aa9788b4a7e9b835d3c2300ab77569de0bdfc36a04d",
        expected_source_rgba_sha256="0b63c0c56ab23590f88d8b1afa5148e174eb26df1af51c0c22876acf7ac20191",
        source_anchor_tolerance_px=0.51,
    ),
    "smoke-30x30": NativeSourceGeometryContract(
        source_texture="body7Sprites",
        target_texture="body7Sprites",
        expected_frame_count=32,
        expected_geometry_proof_sha256="ce4a1b5aab561219065e3a5c235eb810c3d53ff9d4a827c5e9dd2421a2425f0d",
        expected_origin_proof_sha256="ebdad73458144d27b7cde74c25de13f730d71ff3ac904ae52cc46f4c5e26b02d",
        expected_source_rgba_sha256="563c11da363d1af691e25cd1057040814f9c480f59b1abfa6c5f9919cc191c87",
        source_anchor_tolerance_px=0.51,
    ),
    "oil_dropped": NativeSourceGeometryContract(
        source_texture="body7Sprites",
        target_texture="body7Sprites",
        expected_frame_count=32,
        expected_geometry_proof_sha256="f20101510995705354eb896b1fbadbd48e39322566b82b8e39122047afdd36ce",
        expected_origin_proof_sha256="5482c63e006a27bf04e7dac6a0425995b20d35acf13fcefa55dd845f8c5bc769",
        expected_source_rgba_sha256="77574586e0c3233f706971a3bc98461f157d29b2557127d444c77fc3252b2ccd",
        source_anchor_tolerance_px=0.51,
    ),
    "body_disease": NativeSourceGeometryContract(
        source_texture="body4Sprites",
        target_texture="body4Sprites",
        expected_frame_count=32,
        expected_geometry_proof_sha256="65163e42081d999053435f58f55b68354cd20e35fc65269b3932e96cbc6a6c4d",
        expected_origin_proof_sha256="cc5c94dd4e234541c3b7a4ed5e309dcaaef75ce1cbe4822b1ace5c13e7966a6b",
        expected_source_rgba_sha256="bd08b21651ac3266011ed4f0129c02f3aec296312bbfecae2fa124423f39e18d",
        source_anchor_tolerance_px=0.51,
    ),
    "anim_tunnels": NativeSourceGeometryContract(
        source_texture="anims1Sprites",
        target_texture="anims1Sprites",
        expected_frame_count=32,
        expected_geometry_proof_sha256="b49cd3dc99ecd8e27b88a85b0045a975cbae1a710243b4856efbdc6bb933b307",
        expected_origin_proof_sha256="1d566850c02806d330537fbeb0499ad76d4e00d873f168208834b6a2e4539367",
        expected_source_rgba_sha256="9a7e22bd52d8e6dfcfb2c27216e6dbc3ab32849032f45d60766f69e7607ac907",
        source_anchor_tolerance_px=0.51,
    ),
    "anim_killing_pits": NativeSourceGeometryContract(
        source_texture="anims1Sprites",
        target_texture="anims1Sprites",
        expected_frame_count=32,
        expected_geometry_proof_sha256="2bda2897cee3e51a8ee0a5b922e9272f0b77a25d24a2aebeea2188191a44d3fd",
        expected_origin_proof_sha256="98efd3ea2a6c6e428bbaf021de10f420fffa78e8785e449774f31821569978ca",
        expected_source_rgba_sha256="1e234bbb4cf904111fafd14a4b1660988c73c833fc6b21b60a80769e8fdfe7c7",
        source_anchor_tolerance_px=0.51,
    ),
    "anim_stables": NativeSourceGeometryContract(
        source_texture="anims1Sprites",
        target_texture="anims1Sprites",
        expected_frame_count=42,
        expected_geometry_proof_sha256="3b3b313fcfb1ff5d66a81f78aa4b0bebc94ece7b4cc8b3907b11980711319776",
        expected_origin_proof_sha256="3077799008361d82e9de195fda2df5d13e97652c265736966ad0910d13d397f1",
        expected_source_rgba_sha256="d7ce9c65194c6ad3993053f678280752616501d148853180d457dca654342d2e",
        source_anchor_tolerance_px=0.51,
    ),
    "anim_healer": NativeSourceGeometryContract(
        source_texture="anims1Sprites",
        target_texture="anims1Sprites",
        expected_frame_count=42,
        expected_geometry_proof_sha256="064961269aedb44303a341fceadbdea5a79eb4ec8237e25fe07fa87c76a277c9",
        expected_origin_proof_sha256="0f7f24712ba2f3435a46665f0ac80004b2544e98d272a629d9ef4fa644efa0fa",
        expected_source_rgba_sha256="8c53a27906e66b3a0adcae416e8f1a9ceb0688d99d19be3aa02febe72638b953",
        source_anchor_tolerance_px=0.51,
    ),
    "anim_pitch_dugout": NativeSourceGeometryContract(
        source_texture="anims1Sprites",
        target_texture="anims1Sprites",
        expected_frame_count=48,
        expected_geometry_proof_sha256="f45b17f7ae755dc98c204f62ea08a6cef430fb100373f03a113f22322a3efc44",
        expected_origin_proof_sha256="044074afa0e237399c76ce27ffb90991cd33ae9e9927bf77fb83aeec2051bc94",
        expected_source_rgba_sha256="ffff047de1cb32010a86bc78c6bb351acacc49bb6e62e224758dfd65e7b02fe2",
        source_anchor_tolerance_px=0.51,
    ),
    "anim_dancing_bear": NativeSourceGeometryContract(
        source_texture="anims1Sprites",
        target_texture="anims1Sprites",
        expected_frame_count=55,
        expected_geometry_proof_sha256="e35c96c4dd005fd7af9ada8eacf71e86c9f13033e6b2a7765cbe1f1186df17db",
        expected_origin_proof_sha256="038342e0bafd8e7b754ec5a36c1aceff4135912714c7773b7c091f606bdebb1a",
        expected_source_rgba_sha256="7004af1458d63fd8f769d54007ca2c15f6d510d1db898833c90d62f03d4e2015",
        source_anchor_tolerance_px=0.51,
    ),
    "anim_maypole": NativeSourceGeometryContract(
        source_texture="anims1Sprites",
        target_texture="anims1Sprites",
        expected_frame_count=64,
        expected_geometry_proof_sha256="3b5dbe3bf9378f76a92ce1d3b13e3cf46d418d9f3cddf38693dea30129be99d5",
        expected_origin_proof_sha256="df2e440f3fae39e99184edab9ec0a87d0fce92408b3e3c9615b14295f6c54d51",
        expected_source_rgba_sha256="06637a37c84eba7c52e8dea4ef9e0a3d0fb1942e565b8b690e07c048e69a1adf",
        source_anchor_tolerance_px=0.51,
    ),
    "anim_baker": NativeSourceGeometryContract(
        source_texture="anims1Sprites",
        target_texture="anims1Sprites",
        expected_frame_count=68,
        expected_geometry_proof_sha256="a6f2b2e66757be28d37363856b2750a2657ad269f1f0fb338db36050f79bbd93",
        expected_origin_proof_sha256="66075f8d62672eb2560c8513da79828af8e2adfc0a608a1f21bd45a9b7cbcaeb",
        expected_source_rgba_sha256="79cbfe5266e4fb42db8ec35ed5b11567501c3273455de70f960838058c09d832",
        source_anchor_tolerance_px=0.51,
    ),
    "anim_fletcher": NativeSourceGeometryContract(
        source_texture="anims1Sprites",
        target_texture="anims1Sprites",
        expected_frame_count=72,
        expected_geometry_proof_sha256="27070eaccb7b245b98bf0d4f1aa27313f1a641c97efa08898c639655c3744b40",
        expected_origin_proof_sha256="5881cf47a46f7784f0614a216739d7ea060441dfb48371daf55760d89926081a",
        expected_source_rgba_sha256="4fa974aae5b871728a24e4241ce26bbd1c139441d752e4cf43656d9b4634e031",
        source_anchor_tolerance_px=0.51,
    ),
    "blast3": NativeSourceGeometryContract(
        source_texture="body7Sprites",
        target_texture="body7Sprites",
        expected_frame_count=73,
        expected_geometry_proof_sha256="b1ecaa9b3829bfe0894ebe077d16e314524600590296b12eae12e9a57745b313",
        expected_origin_proof_sha256="6e559ea096be991d11b9cd841034365c5c9eb145cf9b4f7654e167a469776441",
        expected_source_rgba_sha256="fd087a925583936be06bf5e23658864f6c7c82c77187cfab91cbbb0726261d6a",
        source_anchor_tolerance_px=0.51,
    ),
    "anim_tanner": NativeSourceGeometryContract(
        source_texture="anims1Sprites",
        target_texture="anims1Sprites",
        expected_frame_count=76,
        expected_geometry_proof_sha256="55681a47c467c29ce01602c03add7eb388bdc7ee14797a9653e78ba6658fe2fa",
        expected_origin_proof_sha256="01483b691e92038de9c440d98b3d75f297ea68086cd07101adcabde91d8247e1",
        expected_source_rgba_sha256="8700aceb22ecbd2f20d58bd48ee250a2f19b7fa03eed953ffa78e963adba66c8",
        source_anchor_tolerance_px=0.51,
    ),
    "cursors": NativeSourceGeometryContract(
        source_texture="anims1Sprites",
        target_texture="anims1Sprites",
        expected_frame_count=89,
        expected_geometry_proof_sha256="22f2f6dc582711310279257828d547e228223fcc10e952a2accac2f8b287587b",
        expected_origin_proof_sha256="e2855c5e031252bcf73db93d6f9d14e25ba870d091b518c165d00e81631c9fda",
        expected_source_rgba_sha256="3572f7f584236d910fd0a6c168294169c90cc08c6a582c646080c8c1679e2a90",
        source_anchor_tolerance_px=0.51,
    ),
    "float_pop_circ-1": NativeSourceGeometryContract(
        source_texture="anims1Sprites",
        target_texture="anims1Sprites",
        expected_frame_count=101,
        expected_geometry_proof_sha256="643eca318e5f941b3bb00edadf35b4f9d0925d48c23a14db588fbd2072318dbf",
        expected_origin_proof_sha256="9e7d3658168f83d46d456f771703c3290add15eaad08f861206bf14211520bf0",
        expected_source_rgba_sha256="6ec636a6c8f2b33a5ab48ac9c1f646c7e2b4508f23c0820d76e745ad1f53a82a",
        source_anchor_tolerance_px=0.51,
    ),
    "anim_brewer": NativeSourceGeometryContract(
        source_texture="anims1Sprites",
        target_texture="anims1Sprites",
        expected_frame_count=112,
        expected_geometry_proof_sha256="dd52d9b4d7d63389d488319539d458050c0a0fa0f17fe1af624619c607f0a430",
        expected_origin_proof_sha256="c894f0c859639b5890f41e838e5e57b83efb255e33d0b592f9a1b04156cd1010",
        expected_source_rgba_sha256="f716372dcafaad835b704ff4b1da9ea5475764dbec7d67e805841914b4f87d82",
        source_anchor_tolerance_px=0.51,
    ),
    "anim_poleturner": NativeSourceGeometryContract(
        source_texture="anims1Sprites",
        target_texture="anims1Sprites",
        expected_frame_count=127,
        expected_geometry_proof_sha256="2e655cdf2696a0c5b5585e0739ba748ea4683d8c32130e360324ea9d6ba18a0c",
        expected_origin_proof_sha256="a1cdd8564ff6d1995c1da5408b58e9a0a7207549eeb083a367c86184c146f3ff",
        expected_source_rgba_sha256="e99c1d79235e6ce000e7d68c406ceac5be5f4bfd191f3855a214e1b1c30afd11",
        source_anchor_tolerance_px=0.51,
    ),
    "anim_drawbridge": NativeSourceGeometryContract(
        source_texture="anims1Sprites",
        target_texture="anims1Sprites",
        expected_frame_count=128,
        expected_geometry_proof_sha256="bd2c7bffa003b89d25f8d58f5a070576490b2ee9164b06b652bfde1309d430c1",
        expected_origin_proof_sha256="be07dc8b338c4b67b6f61f2c39e9664775b2218b16d74d774a19d6e7dbda20be",
        expected_source_rgba_sha256="d59401be42d4a26d7e40a3e39049c9ebada2e59a1138dbbac96ddfadbcec4647",
        source_anchor_tolerance_px=0.51,
    ),
    "anim_boiled_oil": NativeSourceGeometryContract(
        source_texture="anims1Sprites",
        target_texture="anims1Sprites",
        expected_frame_count=138,
        expected_geometry_proof_sha256="6ca4de2155d2135b3d97d1b1f3b909f66c2fbec94171bf5596e3765ffe40548e",
        expected_origin_proof_sha256="cdd09bd32864b5c23a32f67b24ca67f5c6623ead9715507362429e4d79f18a30",
        expected_source_rgba_sha256="d8d28b7038ceb765ad42da30087f7d9a58a44140b5e96ce011e181a6db0d1fa8",
        source_anchor_tolerance_px=0.51,
    ),
    "body_missile_fire": NativeSourceGeometryContract(
        source_texture="body7Sprites",
        target_texture="body7Sprites",
        expected_frame_count=144,
        expected_geometry_proof_sha256="d50ca6e9ac3d7d14036ab18a4e6d1f27c4a5927f41d9339d65bf96ea45f828e4",
        expected_origin_proof_sha256="4a23e962ca978ba56af1372f18b06138ae4686d6070d203e19a890be174608b1",
        expected_source_rgba_sha256="6260036f0e7553c9ec4eed2373897feb49c1b8ef22d26bb3e9c3ce4ba6cf70bb",
        source_anchor_tolerance_px=0.51,
    ),
    "body_missile_2": NativeSourceGeometryContract(
        source_texture="body7Sprites",
        target_texture="body7Sprites",
        expected_frame_count=144,
        expected_geometry_proof_sha256="91fffde02683287e5261d6a8fc1e52433781fd8c54c96c26cb7967eb97149982",
        expected_origin_proof_sha256="38861c448e9fcca922524d1d593356ece0a0d88e1fa365e7c286ffbf39946953",
        expected_source_rgba_sha256="a4c91c0b853e73f3b0818ef637db23269a28224d0fb30629bee5d880bd6d7300",
        source_anchor_tolerance_px=0.51,
    ),
    "body_siege_tower": NativeSourceGeometryContract(
        source_texture="body4Sprites",
        target_texture="body4Sprites",
        expected_frame_count=153,
        expected_geometry_proof_sha256="ae7c6a3773688b9add7d9f74e51c8b8a5b2d59234c112a3cc77034604d780631",
        expected_origin_proof_sha256="21144e7513dc1d9d0aca7135938ceaf01b088ae48d3ed0c1cde31dfa965e8c3f",
        expected_source_rgba_sha256="487ded549e776715327baa4e4455a345269d2de84c454b48d3ce1423ac02cc95",
        source_anchor_tolerance_px=0.51,
    ),
    "anim_iron_miner": NativeSourceGeometryContract(
        source_texture="anims1Sprites",
        target_texture="anims1Sprites",
        expected_frame_count=170,
        expected_geometry_proof_sha256="d5b89aa7b86d2cc35725aa4367578814e91375d3b2a69069bc24b1782301b0db",
        expected_origin_proof_sha256="3c53777c371f13798982c66797c0ebf6fb40c4e1fef34376a705ee6e450c9272",
        expected_source_rgba_sha256="b1e3a2dfae539e1bd3c7126639014d69e295b6c9bfa2ceecbcd37286db1082d7",
        source_anchor_tolerance_px=0.51,
    ),
    "body_missile": NativeSourceGeometryContract(
        source_texture="body7Sprites",
        target_texture="body7Sprites",
        expected_frame_count=184,
        expected_geometry_proof_sha256="8f2c21ea2ee8b915c6f7db0a547eecb7e4590098367863383640be13f3d9c6c4",
        expected_origin_proof_sha256="f662101fc296041b099badc4911246196a536db72c144d2f0b1dcb40f37bee26",
        expected_source_rgba_sha256="7c8ecc56388f9844d9679653ffb314cb409d4f7509c689ca64e496cc3a5bfc18",
        source_anchor_tolerance_px=0.51,
    ),
    "body_ballista": NativeSourceGeometryContract(
        source_texture="body4Sprites",
        target_texture="body4Sprites",
        expected_frame_count=184,
        expected_geometry_proof_sha256="3ff5a9f2667028fa89dd0a3e8320f4426d2889d128a8f57a87b2e5f7d026dbfa",
        expected_origin_proof_sha256="69cefbda5a315be3aefba3f444d8f849816c12ab3e975f0b07a1c0816c45e3d2",
        expected_source_rgba_sha256="8db4d766bba6c1f9c3e7f1cc71c4507caa905b3c4d2bd10b87b408a445c56db9",
        source_anchor_tolerance_px=0.51,
    ),
    "anim_blacksmith": NativeSourceGeometryContract(
        source_texture="anims1Sprites",
        target_texture="anims1Sprites",
        expected_frame_count=199,
        expected_geometry_proof_sha256="6cee49ecf9c9c54791ef459206bb6c19cacad4f16d578086599ac641e33b738b",
        expected_origin_proof_sha256="06b2918a2de281a429e5b8a510201f40662080c4c41e7ad69429a3c916f40da2",
        expected_source_rgba_sha256="ed70146b128bf2ec89497bfee69b0895fdeebdb2d58bf50686060eed29c889a4",
        source_anchor_tolerance_px=0.51,
    ),
    "body_crow": NativeSourceGeometryContract(
        source_texture="body5Sprites",
        target_texture="body5Sprites",
        expected_frame_count=208,
        expected_geometry_proof_sha256="e5766289bb131b9f753e1201ee02f9399948470f2775939736e83267a504f4c8",
        expected_origin_proof_sha256="8f7ea3fbee98d445aa33d84bc748ee8dfd3293bf79f9d0334cd0dd2770eb319a",
        expected_source_rgba_sha256="4378ebe3894b68adadedce94631d8279bbd71c67230deb233735fde702558fed",
        source_anchor_tolerance_px=0.51,
    ),
    "body_mangonel": NativeSourceGeometryContract(
        source_texture="body4Sprites",
        target_texture="body4Sprites",
        expected_frame_count=256,
        expected_geometry_proof_sha256="03828eb75a29911ab84358e098991444ab133dc45f1a9c6e2e2c578e6b5e1243",
        expected_origin_proof_sha256="bea601b96295e21ed98ae833c203c2003a9cac5dcc4fae685604939e12e4261c",
        expected_source_rgba_sha256="404ee2a74ea5af23bab7a5d22460a58e03c815c4db92c12507f4af083f118974",
        source_anchor_tolerance_px=0.51,
    ),
    "body_horse_trader": NativeSourceGeometryContract(
        source_texture="body5Sprites",
        target_texture="body5Sprites",
        expected_frame_count=256,
        expected_geometry_proof_sha256="4d8e301a11da80cd80b3b65558112a5eebe2ba54f8f2508ceb160778e738c58e",
        expected_origin_proof_sha256="90764389063c5925ad65ab0685fb0e7f4b21c44b2c4f90c8d1830453dfa0df87",
        expected_source_rgba_sha256="c8c47aab92b06d631e0e9139b29596c78c5f630513dc587ab5d18e9afeac15b2",
        source_anchor_tolerance_px=0.51,
    ),
    "body_ghost": NativeSourceGeometryContract(
        source_texture="body4Sprites",
        target_texture="body4Sprites",
        expected_frame_count=256,
        expected_geometry_proof_sha256="63b64eb84e2121d4562eff4df49b85b48e5c59f6d9286282d6adcfdb618bd1b8",
        expected_origin_proof_sha256="3d5d29072d8bf5a5e82c5d472c9f9fa5e1b6862ad1ea62d527f6d7e312ea3717",
        expected_source_rgba_sha256="743e2eb8d730dae8b52a9cb3d5e5514b0a6fb7938ac2a0ca9f5ae3f9b656e19a",
        source_anchor_tolerance_px=0.51,
    ),
    "body_fire2": NativeSourceGeometryContract(
        source_texture="body7Sprites",
        target_texture="body7Sprites",
        expected_frame_count=294,
        expected_geometry_proof_sha256="79f0d81121a7fe888b8faafb501a1fa57b28a57d0cec2f2f12751b942a8d321d",
        expected_origin_proof_sha256="ff2c9f97f363e11e6ed66169cb8d7d443874abb67fd5e45d1ce97e94510fc633",
        expected_source_rgba_sha256="d88d7a98ce15cc7e2f115ea77cb2ec8dde1d271e4179650df1e05d009be21d75",
        source_anchor_tolerance_px=0.51,
    ),
    "anim_quarry": NativeSourceGeometryContract(
        source_texture="anims1Sprites",
        target_texture="anims1Sprites",
        expected_frame_count=323,
        expected_geometry_proof_sha256="2ef4e52362894230608a746bcdc52fd6ca2ff901d3e9a933bb80adf53bf9ad45",
        expected_origin_proof_sha256="96d4fb8bcf7b0eb59c680cc76db27493507b38dcf0e8a315959f916ae341e89f",
        expected_source_rgba_sha256="b8f15071acf00ba7c25a466c89bd8387530cff4d9ad7d2681d9ed1d39d4a8ee1",
        source_anchor_tolerance_px=0.51,
    ),
    "body_drunkard": NativeSourceGeometryContract(
        source_texture="body1Sprites",
        target_texture="body1Sprites",
        expected_frame_count=400,
        expected_geometry_proof_sha256="98c60e694c2b0ab7d67a6293248f0053dcf47d3d175fc9f48ddf28d51fb9c8ea",
        expected_origin_proof_sha256="d1109218fb17befa585a0398c523aa8d900b1a24df6ef487ccc74e2723b42f2a",
        expected_source_rgba_sha256="640ca83d222f6e52ea2573e33920bd673a5fe0c98ce3f434366e0d22f5daf8a9",
        source_anchor_tolerance_px=0.51,
    ),
    "body_battering_ram": NativeSourceGeometryContract(
        source_texture="body7Sprites",
        target_texture="body7Sprites",
        expected_frame_count=425,
        expected_geometry_proof_sha256="67b1a9c799c198eb578f39ddcff1f20ae4b921526440e8091f617d6abb48c54d",
        expected_origin_proof_sha256="6e7c430385b67d18b25628a00bb5536d00d7ef51090e0cf81868d3bd7db274bc",
        expected_source_rgba_sha256="26fd228649a4eb4c64f33850d3e84b847e4e79551fc27221c3b2b8b8e4743466",
        source_anchor_tolerance_px=0.51,
    ),
    "body_man_burning": NativeSourceGeometryContract(
        source_texture="body1Sprites",
        target_texture="body1Sprites",
        expected_frame_count=440,
        expected_geometry_proof_sha256="04dc941242db549e7c3e138c5df1303dc8bf675eb541a8e9e19a3fbaf05c950e",
        expected_origin_proof_sha256="9ba39a393a2cf1d152ebcdcd2bb4219d2b50c0ff331a7650ef559808b65afbf4",
        expected_source_rgba_sha256="bfbddd9efe2000e068c25093ab1293bb92446d37bc8d37023d059e1f674d536e",
        source_anchor_tolerance_px=0.51,
    ),
    "body_cow": NativeSourceGeometryContract(
        source_texture="body5Sprites",
        target_texture="body5Sprites",
        expected_frame_count=480,
        expected_geometry_proof_sha256="0af96b9e89574c97d26727151b894f11fb177c1706bcbf552adff6e81b776d68",
        expected_origin_proof_sha256="92dfde0890c9950822ee3fee74db1f69a6c8fd0354ef8ec8eed6381d649b4714",
        expected_source_rgba_sha256="3a3cf9a5b7fd55a2c686870ac024371cb46db9ace66b543816472452aa283606",
        source_anchor_tolerance_px=0.51,
    ),
    "body_trebutchet": NativeSourceGeometryContract(
        source_texture="body4Sprites",
        target_texture="body4Sprites",
        expected_frame_count=504,
        expected_geometry_proof_sha256="cfb842479236c9473026915567f4c92d7bb3076b6d146212e2fde6f811cbf05e",
        expected_origin_proof_sha256="887b64158506edf3ec3177717fb1ab57976f2f560bdec26cf7d86227249ad02b",
        expected_source_rgba_sha256="41f8e9652b2d3f16ac5619f8682ad3df195b531db21893456f78f904707cd390",
        source_anchor_tolerance_px=0.51,
    ),
    "body_catapult": NativeSourceGeometryContract(
        source_texture="body4Sprites",
        target_texture="body4Sprites",
        expected_frame_count=529,
        expected_geometry_proof_sha256="f9fe3a2beb1443454416f861fe3707aff337dd1d349bdd5855f71bd3cfd662cd",
        expected_origin_proof_sha256="16609123c1b89c5e61c23b0bb1f4abfc4003c23e2093bccb8c973f4bf3807593",
        expected_source_rgba_sha256="c5a9775c81a1e45fdf1d5e7e51e50cc906e89999a621dade86fcff63b68001ff",
        source_anchor_tolerance_px=0.51,
    ),
    "body_juggler": NativeSourceGeometryContract(
        source_texture="body2Sprites",
        target_texture="body2Sprites",
        expected_frame_count=724,
        expected_geometry_proof_sha256="1395b10f9e1b3098f7ff060989db38c9b7c5e717ba0f89f3ec566c82a292351f",
        expected_origin_proof_sha256="025b305f4629cb41fce9422258af2505c22b24c912fec9974f0e5a36939044bd",
        expected_source_rgba_sha256="8105b3260052987269b2c0ad6b887d3171231b62fb8945e1510f4acd83481a83",
        source_anchor_tolerance_px=0.51,
    ),
    "body_fire": NativeSourceGeometryContract(
        source_texture="body7Sprites",
        target_texture="body7Sprites",
        expected_frame_count=732,
        expected_geometry_proof_sha256="dff1af24789fd375ae317e413247ab3155638d51f3621d2dc3ed8f09eee7592f",
        expected_origin_proof_sha256="a0d1f489e9f0b56705628439458797626e6a54eb4010a2a0624d557d9dedf3b6",
        expected_source_rgba_sha256="1f00f2c0042562d02024a595f5a1f187a01db159d5334b68a0f7894f677ea484",
        source_anchor_tolerance_px=0.51,
    ),
    "body_ox": NativeSourceGeometryContract(
        source_texture="body5Sprites",
        target_texture="body5Sprites",
        expected_frame_count=768,
        expected_geometry_proof_sha256="7f2bf53499ff8c94bff7fd593b00e966ab137e521f89b787fb2708f52307f3ba",
        expected_origin_proof_sha256="e9d9db2835fe98cf4f112d59a5c433ac1b3ac652a25352b9da54948c9afe55b6",
        expected_source_rgba_sha256="6bbc4afa248374a56b6c5ff44ded2e8f2c161b629655091e630bef1d96b7eebb",
        source_anchor_tolerance_px=0.51,
    ),
    "body_priest": NativeSourceGeometryContract(
        source_texture="body2Sprites",
        target_texture="body2Sprites",
        expected_frame_count=784,
        expected_geometry_proof_sha256="e7b7765bf7be0f75505fabeb6514a2215dfd86ebc7cf1a2318c82a6f88052808",
        expected_origin_proof_sha256="74957e78569473ea5a1ac8af37865464f8e4bf379b10ff97526dfab606e5da8e",
        expected_source_rgba_sha256="52eb1f4c762209fd0af74da2e968f178fe3b0749eda1ca0602e689f11b557f82",
        source_anchor_tolerance_px=0.51,
    ),
    "body_rabbit": NativeSourceGeometryContract(
        source_texture="body5Sprites",
        target_texture="body5Sprites",
        expected_frame_count=896,
        expected_geometry_proof_sha256="ef83de43adc0bc8349163e4577ed2f5212a6609888ad790194b13bc48344d6d3",
        expected_origin_proof_sha256="ca336d4dee3975d72e669a979140f8fbff97ae6fce67568eba29f3858b3f0155",
        expected_source_rgba_sha256="8e4ffc45ecaa50f6524b5ed8f736c6fd12341015d9f0250c3f3fd5e8f69e1af7",
        source_anchor_tolerance_px=0.51,
    ),
    "body_iron_miner": NativeSourceGeometryContract(
        source_texture="body2Sprites",
        target_texture="body2Sprites",
        expected_frame_count=896,
        expected_geometry_proof_sha256="a89c2915ed87d6cce02e06b20b303d347f57ec8fcdd1f75cc7abc0b0e3e8bc87",
        expected_origin_proof_sha256="4f108bf64d8ddf61d54c48eddb4003ac3496406059e4fa9a478cd88f014e43e8",
        expected_source_rgba_sha256="534e3553eca4e8017da60818d3c1293f5e86fc4501794667bf815350ad430dc0",
        source_anchor_tolerance_px=0.51,
    ),
    "body_girl": NativeSourceGeometryContract(
        source_texture="body1Sprites",
        target_texture="body1Sprites",
        expected_frame_count=912,
        expected_geometry_proof_sha256="5c87fb770663c7ce876009f0e697ce6ed438a74927e1e03871dc56125c1976e2",
        expected_origin_proof_sha256="74a5bf4da9b6cacae5d0607d16f72a53a80050152fce5e16f221cf2e7e14e240",
        expected_source_rgba_sha256="b282b2ec6a6594cd9c014fc4a601324a7a9b9b5ef3cfd40d699df40261ad581a",
        source_anchor_tolerance_px=0.51,
    ),
    "body_boy": NativeSourceGeometryContract(
        source_texture="body1Sprites",
        target_texture="body1Sprites",
        expected_frame_count=912,
        expected_geometry_proof_sha256="8796ad2adfb8a41084e28df1b964ec6e3252f1245d92519891171a4b712e71b8",
        expected_origin_proof_sha256="ab4ff1d9e65356591131a3ecd7da73fab4fc26f4cebc6eb8ec39b39080641e55",
        expected_source_rgba_sha256="e88491e3fb599118d2215525762d33470a1cebcfc461637398a596d528db90b5",
        source_anchor_tolerance_px=0.51,
    ),
    "body_dog": NativeSourceGeometryContract(
        source_texture="body5Sprites",
        target_texture="body5Sprites",
        expected_frame_count=915,
        expected_geometry_proof_sha256="b7e61ff19055bbb9feb03d12160a5c52e224089428776dfaa1956b9e1b8e5d5d",
        expected_origin_proof_sha256="9189fb48de1642d3cb3935dc9430aac71c6347bb9679493f38a38ae4365747ac",
        expected_source_rgba_sha256="fb9f4fac66800f1977248d1a6805d64a9200f1ab47cf5a946c42e766dccf84d0",
        source_anchor_tolerance_px=0.51,
    ),
    "body_stonemason": NativeSourceGeometryContract(
        source_texture="body2Sprites",
        target_texture="body2Sprites",
        expected_frame_count=1032,
        expected_geometry_proof_sha256="50c4764b8eab0db837227bdbefe6381c9d01b32eef216e02e86f80def856260e",
        expected_origin_proof_sha256="67e735be8eeace7c7a574320202ff710efb0f077e23b6759f014cd65de84b22b",
        expected_source_rgba_sha256="547819cc97ef1b6fb5570cfdcac92f8437207dc91cdaa7158ef6e08e61d13571",
        source_anchor_tolerance_px=0.51,
    ),
    "body_innkeeper": NativeSourceGeometryContract(
        source_texture="body2Sprites",
        target_texture="body2Sprites",
        expected_frame_count=1070,
        expected_geometry_proof_sha256="b7d31179a0e6be52e48fcb3f8a3324d5c358ca2ef8d76234fb38915e35c9c5e0",
        expected_origin_proof_sha256="9b14105394a1e5d2f87b3deb71132e9a9c7ce409cd0c179a1e031b64491cf6fe",
        expected_source_rgba_sha256="bc64fbd481d2ebb591baca9409f0c7b8469ee6ad0880d6d2b29ef52e2ecf95cb",
        source_anchor_tolerance_px=0.51,
    ),
    "body_miller": NativeSourceGeometryContract(
        source_texture="body1Sprites",
        target_texture="body1Sprites",
        expected_frame_count=1164,
        expected_geometry_proof_sha256="059f41b2a5fec40cf18b278a4f81705e81ffbd310e9f59fe9cf84b8e0a4e847b",
        expected_origin_proof_sha256="f3d79b407603a1f8e202523b8a48e00b63a75d6978a8baa954af3b6ae129d897",
        expected_source_rgba_sha256="ec3c6c22ad5f94f994aca88d4079eed380fe91614a91a7f88d1f857705bc19c9",
        source_anchor_tolerance_px=0.51,
    ),
    "body_brewer": NativeSourceGeometryContract(
        source_texture="body1Sprites",
        target_texture="body1Sprites",
        expected_frame_count=1168,
        expected_geometry_proof_sha256="dabc6124c73e7f15e2760a509386b3f9a6a0143339c16068fd734fbbb91cc6ea",
        expected_origin_proof_sha256="e7b33fde24824ad1ca8c02a9b3745aae17ccede2283389f232c96fd843d261b8",
        expected_source_rgba_sha256="a554e206bb01befe31188a599c436a6b48ec60c2dc34202217ecfc472a21a4a2",
        source_anchor_tolerance_px=0.51,
    ),
    "body_armourer": NativeSourceGeometryContract(
        source_texture="body2Sprites",
        target_texture="body2Sprites",
        expected_frame_count=1168,
        expected_geometry_proof_sha256="9dd733bca29250ad20b8a24529049a8ae4d811587437026e3d1a1e4262bd85c9",
        expected_origin_proof_sha256="0b69550f7c015d21007cdd072b4a4568ebac77969aab74d1c4b1f6a8cd66a796",
        expected_source_rgba_sha256="a342877b850c06f00d22dcf9e5fc3212c26d0c08d28f15ce55a125da317edf35",
        source_anchor_tolerance_px=0.51,
    ),
    "body_baker": NativeSourceGeometryContract(
        source_texture="body1Sprites",
        target_texture="body1Sprites",
        expected_frame_count=1172,
        expected_geometry_proof_sha256="468210b5d2052828e969959ff0b443f8f28284bba29d564d4450ddfc8eb202d4",
        expected_origin_proof_sha256="d805935666b7a4510bcfcecd75a292136b59042c11f9a37642d858830c020a0a",
        expected_source_rgba_sha256="a5d0278cb3dbaae0d9d644a483f35dac0807c2d9d36b3248e85287e72bc56b91",
        source_anchor_tolerance_px=0.51,
    ),
    "body_pikeman": NativeSourceGeometryContract(
        source_texture="body13Sprites",
        target_texture="body13Sprites",
        expected_frame_count=1270,
        expected_geometry_proof_sha256="1975824c1e692fb3e3749ed625a5c728329dd718be57d6ad6fbf1fd9ad0f2f50",
        expected_origin_proof_sha256="41f283eb10a23b38c788bde86d3cdad4e7bd1f430bdb9a6271844dc7557979e4",
        expected_source_rgba_sha256="c30ff19a4b1918296bfbc292733a161c29637a5f30cffea78d9ba22fcb3ce423",
        source_anchor_tolerance_px=0.51,
    ),
    "body_tanner": NativeSourceGeometryContract(
        source_texture="body1Sprites",
        target_texture="body1Sprites",
        expected_frame_count=1296,
        expected_geometry_proof_sha256="51324ae29bf2e7beb5b74b56fc2d7d6d7940fed0f9c98daa93c865142a3e2b09",
        expected_origin_proof_sha256="f820f3d0e838a5b6a62be2d44d8d66a9e459c0d4565b4fb70100c362ff3a3935",
        expected_source_rgba_sha256="090011aaa1b911ac0309e1aa966533a92802f2b2fb393e3204f7bf2b842392e9",
        source_anchor_tolerance_px=0.51,
    ),
    "body_tunnelor": NativeSourceGeometryContract(
        source_texture="body13Sprites",
        target_texture="body13Sprites",
        expected_frame_count=1344,
        expected_geometry_proof_sha256="391bb4ed12260b16cd1fb5c58e9d7474cf415b471a8c6e2e0e8c352967f1fa1c",
        expected_origin_proof_sha256="48fe0dc5bf39c8b268e31946f87cfea0965b05ce92a0f137df7ad03d24c70f02",
        expected_source_rgba_sha256="f92a2e22bcafe9412e34b99dad609dc75fe1d8a4a0826d0109fbda36156341a4",
        source_anchor_tolerance_px=0.51,
    ),
    "body_crossbowman": NativeSourceGeometryContract(
        source_texture="body13Sprites",
        target_texture="body13Sprites",
        expected_frame_count=1349,
        expected_geometry_proof_sha256="57bdfff8ca6a5087d81add756f5b598c5a603cea12285bc4989827d65dbe96c4",
        expected_origin_proof_sha256="67617010a27690266effe3bfe1353b3018c0db34d4a599a89b1197f80e2c3b22",
        expected_source_rgba_sha256="17dfc3306e82d4a04a82c6c0f7bf67dbf45ad5ccf586fe3b00220c2de2c6463f",
        source_anchor_tolerance_px=0.51,
    ),
    "body_fletcher": NativeSourceGeometryContract(
        source_texture="body1Sprites",
        target_texture="body1Sprites",
        expected_frame_count=1424,
        expected_geometry_proof_sha256="b8b60116c8b66825a7dd7900cccde513e256ad58fd12bf63f19229e0cdb9bfab",
        expected_origin_proof_sha256="3451415b91f912d8e1840fce9daeb4ee7b543ce212f2cb7b23ad7bc1d9bca1a0",
        expected_source_rgba_sha256="14250102327d63b61d0e51acb0ceb7759c6e5f10334bfc73d77af7305867345f",
        source_anchor_tolerance_px=0.51,
    ),
    "body_wolf": NativeSourceGeometryContract(
        source_texture="body5Sprites",
        target_texture="body5Sprites",
        expected_frame_count=1440,
        expected_geometry_proof_sha256="6a0866df2c8128191a08700d4a51b07973fdbe09f1eef4a5e32b2b1b345a1982",
        expected_origin_proof_sha256="aa16f8a1cc37b9bc84423b4a4da8610d0b52e43d3083c135a769a3bfb7a9692a",
        expected_source_rgba_sha256="6e2091ae1c309c4df7e249558c43011c93f1a64aeb1b4ec9a7f9c3853d7d9c4c",
        source_anchor_tolerance_px=0.51,
    ),
    "body_spearman": NativeSourceGeometryContract(
        source_texture="body13Sprites",
        target_texture="body13Sprites",
        expected_frame_count=1632,
        expected_geometry_proof_sha256="36591dac38e893a69aedf19eb0fad53d19b9d23188eded2ed0ae562cfa439610",
        expected_origin_proof_sha256="81d64595528cc65d5166f330d5b1ebf75f6a8dfea128d854d6c882742aaa5be6",
        expected_source_rgba_sha256="d4a94ec2ab8c99595f8ae9194796ce7e9282fc36fbf05e6eca3b20270116232f",
        source_anchor_tolerance_px=0.51,
    ),
    "body_siege_engineer": NativeSourceGeometryContract(
        source_texture="body13Sprites",
        target_texture="body13Sprites",
        expected_frame_count=1660,
        expected_geometry_proof_sha256="9cfacbdb258180919038dc0b355976d4205394dcaea034f6882e301c1f1a8328",
        expected_origin_proof_sha256="82903dcfefb8a2fafbe71a86307bf28829713150264d89b9c194240c506f7e37",
        expected_source_rgba_sha256="10a20d464cce94e4808df641064eb0ff5e57f9799675a8874e1657460d40c178",
        source_anchor_tolerance_px=0.51,
    ),
    "body_maceman": NativeSourceGeometryContract(
        source_texture="body13Sprites",
        target_texture="body13Sprites",
        expected_frame_count=1712,
        expected_geometry_proof_sha256="55dcbefaf34f702c3f902c7a8fdcd2449c814f931a66215f3746b75aa105500a",
        expected_origin_proof_sha256="5e9af07f5014a2d903aa9c11068d0ad9239a1836c0b6e2c7a75e5e237626f9e1",
        expected_source_rgba_sha256="5b94bb1789db2b1ca2fe0a6aa1c169092ccc2f54b74a614d5cb9b2e27b1cdd85",
        source_anchor_tolerance_px=0.51,
    ),
    "body_blacksmith": NativeSourceGeometryContract(
        source_texture="body1Sprites",
        target_texture="body1Sprites",
        expected_frame_count=1728,
        expected_geometry_proof_sha256="6ad41fb391c0d5ba394be3cdfb4f928e1e460722b715b9dd51de39a4016a9d01",
        expected_origin_proof_sha256="e983f27a6341c3904ed686a50a41b30d8c1d097c1b662d132e6e45dde815a9f2",
        expected_source_rgba_sha256="3d34c8a0035544b099e661d45ffd0935638e413d9df9e432f0dc34d94cfbe209",
        source_anchor_tolerance_px=0.51,
    ),
    "body_archer": NativeSourceGeometryContract(
        source_texture="body1Sprites",
        target_texture="body1Sprites",
        expected_frame_count=1960,
        expected_geometry_proof_sha256="7b14a8e55e7e26893ad4ecdfc93df21871354d088d7044926ff594b9d1c07b5d",
        expected_origin_proof_sha256="05ab1e671a91b3fc6ffb0765fe5685eed57be92c5bef8136a173b3ac264eee3e",
        expected_source_rgba_sha256="3b5488314581d80359ea60d08c2b83f8002d7fcb0f63db75e4cef8c5de50a678",
        source_anchor_tolerance_px=0.51,
    ),
    "body_deer": NativeSourceGeometryContract(
        source_texture="body5Sprites",
        target_texture="body5Sprites",
        expected_frame_count=2696,
        expected_geometry_proof_sha256="92cd678a5fbad61bc4a9fee5fab5e4ec1c5f218af4232c11c49047892c863b9c",
        expected_origin_proof_sha256="abdc54d8c7fc3f7524c3d6351f6b2554e9a496514c58993ee08ad80731e5c915",
        expected_source_rgba_sha256="a91d52b328fef33d51e520dcf0894dde84ec590e5c3b37ad113e63b4214418d3",
        source_anchor_tolerance_px=0.51,
    ),
    "body_farmer": NativeSourceGeometryContract(
        source_texture="body2Sprites",
        target_texture="body2Sprites",
        expected_frame_count=2928,
        expected_geometry_proof_sha256="662b68a009ba786bfe39fa50886eb4da13405d42a8c2d8ca3cd3cdaa966d6175",
        expected_origin_proof_sha256="4b8e3282402d1556b2b940a8302203de9c7ea3f89c9e2c8f4ec0015ac8c8792a",
        expected_source_rgba_sha256="e0d0b5e3d82e24fc2262b8fa9b73f8851fbd1f410c31883b409213da97034bae",
        source_anchor_tolerance_px=0.51,
    ),
    # Seit 21.08.2026 deckt die Birke 131 europaeische Frames ab: 148 Zielslots
    # abzueglich 13 bewusster Schwingschleifen-Keeps und vier donorloser
    # Oak-Umlenkungen (115, 116, 138, 145). Profil, Vertrag und die drei
    # gemessenen Digests pinnen genau diesen heutigen Satz; der historische
    # 60-Frame-Befund aus REVIEW_FINDINGS R7 wurde durch die spaetere
    # Oak-Umlenkung fuer 73-147 abgeloest.
    "tree_birch": NativeSourceGeometryContract(
        source_texture="treeSprites",
        target_texture="treeSprites",
        expected_frame_count=131,
        expected_geometry_proof_sha256="92f32c8fd474e40e13daf99b8b46de72eac253f3d587371affebcfa1731fe9ac",
        expected_origin_proof_sha256="a3033f966231a067d1684cb03309f921040c4610ec769ceaea6ffebf963ed34f",
        expected_source_rgba_sha256="f9485378c9cf7680e9af9ce647355de80ea68fd9b2368ffd071044a8eab01330",
        source_anchor_tolerance_px=0.51,
    ),
    "body_woodcutter": NativeSourceGeometryContract(
        source_texture="body8Sprites",
        target_texture="body8Sprites",
        expected_frame_count=1368,
        expected_geometry_proof_sha256="0ccba4fa4565557b0851109de33a77ab2f45d38b2c40df1a855cecc2b42657eb",
        expected_origin_proof_sha256="1d1655a001f6cec94f73461ea425be6663dcbe17b4a280117affc7aee1e5abde",
        expected_source_rgba_sha256="ec50a59b6dff3604a218db6f760193311fa6c9331eb47ba1ebeb3a21a61eae99",
        source_anchor_tolerance_px=0.51,
    ),
    "body_trader": NativeSourceGeometryContract(
        source_texture="body8Sprites",
        target_texture="body8Sprites",
        expected_frame_count=512,
        expected_geometry_proof_sha256="bdeaf7aa65f82d4442e4778f6ebe7a1f218052a81693a4112d676a73f82260d8",
        expected_origin_proof_sha256="c0d1d00cb4519880ad91facd68a15731bdf38c06faa179d01cbf82e9267cec42",
        expected_source_rgba_sha256="f75bda5ae1986941c3a1c9faf9f6a0f8efcd7a6c28ac08a03f8c81907c91bd12",
        source_anchor_tolerance_px=0.51,
    ),
    "body_tent": NativeSourceGeometryContract(
        source_texture="body8Sprites",
        target_texture="body8Sprites",
        expected_frame_count=3,
        expected_geometry_proof_sha256="9c55c3fae80dfb920b25127bac10b6f22efa7cdb973bafff6eba39cef423a74b",
        expected_origin_proof_sha256="7e64363ced32e8cdb8081229d3a2972e87f227c9e62cf7ce9ebf5ba823db82e6",
        expected_source_rgba_sha256="35d4beeea4671a70b3acc33df2dcd189a66dcc68d2e8f7efb101d21f9eb8ec6d",
        source_anchor_tolerance_px=0.51,
    ),
    "body_poleturner": NativeSourceGeometryContract(
        source_texture="body8Sprites",
        target_texture="body8Sprites",
        expected_frame_count=1872,
        expected_geometry_proof_sha256="8585d2a6565e5d5e7ac6d16171d248f7893e23c13169c33be91e6ebd3985253e",
        expected_origin_proof_sha256="3380fea3fa25c44350cadfc026fe3c88abba4ebb1b64be41f62a4b111e5b81b9",
        expected_source_rgba_sha256="7eea9f0d1d5b043bad3fb2a01f0b15003011f4ff2ede1f1b2792ae597d4f435a",
        source_anchor_tolerance_px=0.51,
    ),
    "body_pitch_worker": NativeSourceGeometryContract(
        source_texture="body8Sprites",
        target_texture="body8Sprites",
        expected_frame_count=776,
        expected_geometry_proof_sha256="882b0695745cbc860e608a31b4b6d4451dcebcf5262135f086a5e0445ba132e8",
        expected_origin_proof_sha256="5ff4cd65ae025c60d75187241ed20553a515db8aca2150913a74a7bbd18392ad",
        expected_source_rgba_sha256="b6036a72c2a6210cc1a02d7c8bd4a5b14825641dc3e7d7fec8d3a464d0d524f9",
        source_anchor_tolerance_px=0.51,
    ),
    "body_lady": NativeSourceGeometryContract(
        source_texture="body8Sprites",
        target_texture="body8Sprites",
        expected_frame_count=896,
        expected_geometry_proof_sha256="8e29051e92e213add2048fa359b29b3b4518d7694bb6258e0dbbb73e0734bad5",
        expected_origin_proof_sha256="8a67a09a24978c5a36f371738f9bb5cf623af0037a05fca24fa39cf237be891b",
        expected_source_rgba_sha256="56bac3bd3757bd6dca2173ae435d3348f4c02556b960fcb651f045f5bebc3bb6",
        source_anchor_tolerance_px=0.51,
    ),
    "body_ladder_bearer": NativeSourceGeometryContract(
        source_texture="body8Sprites",
        target_texture="body8Sprites",
        expected_frame_count=471,
        expected_geometry_proof_sha256="03b5cd2384edd017740f9db032600df0e93b86308954e938bd4d5e30d97d6f96",
        expected_origin_proof_sha256="0c9029025ac0e4ceea0bf4753e11e15350a5d8e19d2c64911ee049c171c17bb1",
        expected_source_rgba_sha256="a74ef172ca9bddabbb26e147f428123ad8ce0030c391812951c37f7ae2dd0256",
        source_anchor_tolerance_px=0.51,
    ),
    "body_jester": NativeSourceGeometryContract(
        source_texture="body8Sprites",
        target_texture="body8Sprites",
        expected_frame_count=1024,
        expected_geometry_proof_sha256="0feaad4b7f28e305bef918fa7007fc7bfddc0fc0262e763d03f1d1406226152c",
        expected_origin_proof_sha256="a660ba88f8f09cbec40a68bfa1f175944512054d5e881165f13445b1a49503c3",
        expected_source_rgba_sha256="5ff84840eaf025b206d40f8e15bfb4b20b4dced13ff2ba9e1365d6bbbcd1ed06",
        source_anchor_tolerance_px=0.51,
    ),
    "body_healer": NativeSourceGeometryContract(
        source_texture="body8Sprites",
        target_texture="body8Sprites",
        expected_frame_count=768,
        expected_geometry_proof_sha256="3a0b620ec80f9dc4ec5ed7b04fd63c7249466c0abd2d76dff0914f4d6c1e9363",
        expected_origin_proof_sha256="b8e4ba07e85a9a83a98f9ae972c804b6180b8953f75ff67e6308f00ab36ed711",
        expected_source_rgba_sha256="c575d1062e5e4da3b288f981092682b1eec7f15947cef97240feccc81f81e083",
        source_anchor_tolerance_px=0.51,
    ),
    "body_fireman": NativeSourceGeometryContract(
        source_texture="body8Sprites",
        target_texture="body8Sprites",
        expected_frame_count=1236,
        expected_geometry_proof_sha256="54791329326213bf61bb59a5e1af211053da59d7e785847817d6ec2ffcb3d4be",
        expected_origin_proof_sha256="f2554a84175a4239c965f497e1f069f97b8c5aa37900e101071ebf5811fb48a3",
        expected_source_rgba_sha256="38c72acd872df494a165426c34d663edc3f5ed7ab150025cc054bf58a7d8c755",
        source_anchor_tolerance_px=0.51,
    ),
    "body_fire_eater": NativeSourceGeometryContract(
        source_texture="body8Sprites",
        target_texture="body8Sprites",
        expected_frame_count=625,
        expected_geometry_proof_sha256="d41ca25d5c17521e9cd0cb7ee441535329eb504860d61e28f5f8d3d55a728084",
        expected_origin_proof_sha256="fcdf8d790f45d1c25579c6ef62ef70d897864f0c4cdb3096ccd0dd337babbd96",
        expected_source_rgba_sha256="b4db25085cf16ab439753563f64ad6159db7662af51082c8b0616bf61024700c",
        source_anchor_tolerance_px=0.51,
    ),
    "body_fighting_monk": NativeSourceGeometryContract(
        source_texture="body8Sprites",
        target_texture="body8Sprites",
        expected_frame_count=1248,
        expected_geometry_proof_sha256="f5574d2d38d0e404246e9066a31cd4f93ac359e7da0484544ae36163c8aea965",
        expected_origin_proof_sha256="8fe8048aa50cdef48cfb5f0975408e18c6a93537f13f80c0c22ad8c60bb339cb",
        expected_source_rgba_sha256="81215d7fec943b89e11089ff95414dab821d92de840608f92530b053a8cf89b6",
        source_anchor_tolerance_px=0.51,
    ),
    "anim_goods": NativeSourceGeometryContract(
        source_texture="anims1Sprites",
        target_texture="anims1Sprites",
        expected_frame_count=184,
        expected_geometry_proof_sha256="2124df1f83caeae18f9433baf53861957545e2c409b2d401cc2fb312530627bd",
        expected_origin_proof_sha256="9ced077457464d4e3083c28277603cb4dba2614f9a9a837353284e841b47496b",
        expected_source_rgba_sha256="b50bb12b2564f7a0956b120f741355bb72e9618ce4d6190e8ce461f151dac67f",
        source_anchor_tolerance_px=0.51,
    ),
    "anim_flag_small": NativeSourceGeometryContract(
        source_texture="anims1Sprites",
        target_texture="anims1Sprites",
        expected_frame_count=32,
        expected_geometry_proof_sha256="4b29850f85a7301ae0927aaf4000f471efd0c22f6bef67d4d9859035e62b0f13",
        expected_origin_proof_sha256="370be543c48a5261a48eea389ac0731b48280d189dcb09f667b93c92d2cfeea9",
        expected_source_rgba_sha256="ba89c8bcbe4104c013ad12b6c9a6cc060a58ecd1aca856611abba228e11ed814",
        source_anchor_tolerance_px=0.51,
    ),
    "body_gate": NativeSourceGeometryContract(
        source_texture="body4Sprites",
        target_texture="body4Sprites",
        expected_frame_count=48,
        expected_geometry_proof_sha256="1feab06ec993f565c7c3cada5a52c8a01e1fdc4d1e46f1159149e689885ae88b",
        expected_origin_proof_sha256="bad885e23ecb53d493a6d92b109ba3e3444e405995b9390d89131950986c3e98",
        expected_source_rgba_sha256="9d72fbd599dcede5285c43d8288e928932d1b2059d09ed5324830383eddffd1a",
        source_anchor_tolerance_px=0.51,
    ),
    "anim_windmill": NativeSourceGeometryContract(
        source_texture="anims1Sprites",
        target_texture="anims1Sprites",
        expected_frame_count=75,
        expected_geometry_proof_sha256="65cefd097982bf90187d7453c8b185db9cc94730e2a837835657b3c8a0fc8121",
        expected_origin_proof_sha256="2f08f98e156a84563eaad4c444824042cf46dd8cbd35ae8996d5a14685a5c757",
        expected_source_rgba_sha256="bcdc54e3daf265a01527f157bbe16cdb23c64e685f07509a987d6cd4310bd2ca",
        source_anchor_tolerance_px=0.51,
    ),
    "anim_inn": NativeSourceGeometryContract(
        source_texture="anims1Sprites",
        target_texture="anims1Sprites",
        expected_frame_count=71,
        expected_geometry_proof_sha256="2bf2d4572667fdedb713b2510845285bde9c70fde2c864cf9a69a85eb6de396a",
        expected_origin_proof_sha256="0991b08d6628a6901e675026fa7a414285f6c1f57c4b94796d4a12bbd627bbb6",
        expected_source_rgba_sha256="0e9d9d9bf416e8fbeb05fd09dfeaeb54babee159dd7ebd521bbe81da3fdee016",
        source_anchor_tolerance_px=0.51,
    ),
    "anim_farmer": NativeSourceGeometryContract(
        source_texture="anims1Sprites",
        target_texture="anims1Sprites",
        expected_frame_count=79,
        expected_geometry_proof_sha256="77d8758698a4e51edb5213416e824d68b52e6ca32880803f7e42f7a31055564d",
        expected_origin_proof_sha256="4e08301009c9c41d02e6230caa420e4fd84494c2adab1889c1fb6576d926656d",
        expected_source_rgba_sha256="11526a67438555796f8ad930bf5ffd221e711b8a08b6d327d7522eb3757cb7bf",
        source_anchor_tolerance_px=0.51,
    ),
    # Vegetation. Native geometry is what makes these convertible at all: under
    # the old target-canvas policy Tree_Oak came out at 0 percent and
    # Tree_Chestnut at 1 percent, because Crusader redrew the trees on smaller
    # canvases. Emitting the Stronghold 1 canvas with a re-anchored pivot
    # removes that constraint entirely.
    # Die drei Fällgruppen fuehren seit dem 15.08.2026 weniger als 148: Der
    # Geometrienachweis deckt nur die Frames, die tatsaechlich aus Europa
    # kommen, und in den Fällsequenzen behalten 26 Plaetze die Crusader-Grafik
    # (FRAME_OVERRIDES_139, gemessen in docs/BAUMDEFEKTE.md).
    "tree_pine": NativeSourceGeometryContract(
        source_texture="treeSprites",
        target_texture="treeSprites",
        expected_frame_count=136,
        expected_geometry_proof_sha256="47eaeb4b6bd03f7bbc061a11b3e5c4b96a035e2a0bfdf30056beca07c75a3447",
        expected_origin_proof_sha256="308a5f6858a91ae55c6e0ac3a901548df3689d693fa6820023e5c50ba8d6cbf5",
        expected_source_rgba_sha256="434225bba27129733e62cc25b71290575d9534d5288b6d1f4fe25dc9c9a12661",
        source_anchor_tolerance_px=0.51,
    ),
    "Tree_Oak": NativeSourceGeometryContract(
        source_texture="treeSprites",
        target_texture="treeSprites",
        expected_frame_count=144,
        expected_geometry_proof_sha256="47f772f1d4518e19b803cbf4c320ec7493344b6f7e7dfdad3d68cb9437b4d889",
        expected_origin_proof_sha256="55831cec0a5018bc8db2deebf710b0896081ed7438d3344e6335f7f055fc03af",
        expected_source_rgba_sha256="4ab7f54d849c197d9db17cdf0aa03cb82fdb65cc83b862f91ba58b08896c2d61",
        source_anchor_tolerance_px=0.51,
    ),
    "Tree_Chestnut": NativeSourceGeometryContract(
        source_texture="treeSprites",
        target_texture="treeSprites",
        expected_frame_count=138,
        expected_geometry_proof_sha256="5e4d833ffe0cb3f0fb9a06b6aceafa571ecca247a2382a12d66dac2affd805e8",
        expected_origin_proof_sha256="ed6940e6424456a051a032cb5d1d5783efd1f0d652360255873b719d7e6412ff",
        expected_source_rgba_sha256="8dae0bcd339666ffbc5e878ccd4a5ebdd7dd088cf6cbf13a1846220826f8eadd",
        source_anchor_tolerance_px=0.51,
    ),
    "tree_shrub1": NativeSourceGeometryContract(
        source_texture="treeSprites",
        target_texture="treeSprites",
        expected_frame_count=25,
        expected_geometry_proof_sha256="abe2d72c8c32a2c6399b36837b90d9c681f05a147625388aa9a1df46281fee8f",
        expected_origin_proof_sha256="b3441999801e3745d49ddba13536c5872e068cd63f70de77bc849431b1246df9",
        expected_source_rgba_sha256="280f0d1327d44bcc10f1376fdc54d9b3c0029a06fdac29916a5f9d7de57bcf01",
        source_anchor_tolerance_px=0.51,
    ),
    "tree_shrub2": NativeSourceGeometryContract(
        source_texture="treeSprites",
        target_texture="treeSprites",
        expected_frame_count=25,
        expected_geometry_proof_sha256="5dd8221e61e2625f9a8791f60958d3ec30dcdf6f30b21e143cfac69d0eb4a343",
        expected_origin_proof_sha256="785d2d7bd008ab77f236eedabfd95bce652ba32a39a48f67bf6db7859d6bf9f5",
        expected_source_rgba_sha256="4e4bf19f068bfc370f83a33798dd258222d0f0fc37cf105fdeddab1171b38bc1",
        source_anchor_tolerance_px=0.51,
    ),
    "anim_whitecaps_wave": NativeSourceGeometryContract(
        source_texture="anims1Sprites",
        target_texture="anims1Sprites",
        expected_frame_count=212,
        expected_geometry_proof_sha256=(
            "e18d5ae89cf2c937855b46638c8e3b54"
            "095fe7142c1615cf2f79db279578ed7d"
        ),
        expected_origin_proof_sha256=(
            "d1ed78917cad02ca4468939d98e330fc8"
            "665a7fdc581624048abd8cbd8c357d0"
        ),
        expected_source_rgba_sha256=(
            "a9d6a4418b35e4d3249e473019706ce0"
            "328806c5546c1a36431cb4efc1a164e9"
        ),
    ),
    "body_splash": NativeSourceGeometryContract(
        source_texture="body7Sprites",
        target_texture="body7Sprites",
        expected_frame_count=24,
        expected_geometry_proof_sha256=(
            "c6d3716a30ea46b5bc26dd7efd45b7a6"
            "a27d97e1fd454f8288adb4958c45a579"
        ),
        expected_origin_proof_sha256=(
            "8bb1ceebbcb3c9bd068a7e56339e6f9be"
            "58cf0c9e34e5297941fbd1212fc204e"
        ),
        expected_source_rgba_sha256=(
            "9075999ca45dc2f56dcba8969dd0ab20"
            "a9c3132d8e32d2ebd50c441e12d97858"
        ),
    ),
    "body_seagull": NativeSourceGeometryContract(
        source_texture="body5Sprites",
        target_texture="body5Sprites",
        expected_frame_count=144,
        expected_geometry_proof_sha256=(
            "9d45ab2cbf3c456b4ec1a98d2df6ba3"
            "48390734c44baa06e46a65a435711a2ce"
        ),
        expected_origin_proof_sha256=(
            "bdea23ee25e3c3144fb43572ad2bab39"
            "2103b8cd40da04135490e7b72515b63c"
        ),
        expected_source_rgba_sha256=(
            "5fff8832776a15fd61658f209322ba3d"
            "b95d14e7a37ba1199bd805da05dec459"
        ),
    ),
}


# Eigene Tabelle fuer die nativ rendernden REVIEW-Gruppen, mit Absicht getrennt
# von NATIVE_SOURCE_AUTHORED_PIVOT_139_CONTRACTS: ein Eintrag dort macht die
# native Geometrie fuer die Gruppe PFLICHT (`required_native_source_geometry_
# contract` weiter unten, ausgewertet in AtlasGroupSpec.from_profile). Fuer
# body_lord haette das jedes bestehende Profil ohne geometry_policy sofort
# ungueltig gemacht - europe-production.json, lord-review-canary.json,
# review7-canary.json. Hier eingetragene Vertraege sind stattdessen VERFUEGBAR,
# wenn ein Profil sie ausdruecklich waehlt; waehlt es sie nicht, bleibt die
# Gruppe bei ihrer bisherigen, ebenfalls eingefrorenen V1/V2-Partition.
#
# Die Tabelle ist heute leer. Die drei Pixel-Digests einer nativen Gruppe
# (geometry/origin/source_rgba) lassen sich nur aus einem Build messen; ein
# Platzhalter waere hier kein Gewinn, weil er in Vertrag UND Profil gleichzeitig
# ersetzt werden muesste. Vorgehen fuer body_lord siehe docs/CLIPPING.md.
NATIVE_SOURCE_REVIEW_AUTHORED_PIVOT_139_CONTRACTS: dict[
    str, NativeSourceGeometryContract
] = {
    # Der Lord unter V3: Alle 1216 Spenderframes behalten ihre eigene Leinwand
    # und ihren authored pivot. Die Entscheidung dahinter ist des Nutzers und
    # woertlich notiert: "Lieber einen etwas zu grossen Lord als einen
    # flackernden." Unter V2 wurden 824 der 1216 als BLOCKED_ALPHA_CLIP
    # abgewiesen, und der Lord wechselte im Spiel sichtbar zwischen
    # europaeischer und Crusader-Fassung. Die drei Digests hat der
    # Kanarienlauf mit SEDE_COLLECT_PROOF_MISMATCHES=1 gemessen.
    # Der Schwertkaempfer: alle 1184 Frames haben einen Spender, kein einziger
    # ist KEEP_CRUSADER. Unter V1 wurden davon 1028 abgewiesen, weil das
    # Stronghold-1-Bild groesser war als der Crusader-Slot - und die 156
    # durchgelassenen standen als Fremdkoerper mitten in den Gehzyklen.
    "body_swordsman": NativeSourceGeometryContract(
        source_texture="body13Sprites",
        target_texture="body7Sprites",
        expected_frame_count=1184,
        expected_geometry_proof_sha256="c30a8016a4bce06c2a2efe4e665a9c2adcf45ef65fea7c61afcd3f8c2c3492ee",
        expected_origin_proof_sha256="23ed4e3180b5f8747dcb2ba0319e2cba93adf4d8efc16d7922048bc89bc40227",
        expected_source_rgba_sha256="4005765dc81493717a79412d00b9fc037a76e211e42a306dd88162b22e55551f",
        source_anchor_tolerance_px=0.51,
    ),
    "body_lord": NativeSourceGeometryContract(
        source_texture="body2Sprites",
        target_texture="body14Sprites",
        # 1.936 statt der frueheren 1.216: Seit der Animationsumlenkung
        # (LORD_ANIMATION_PHASE_MAP) traegt JEDER Platz der Gruppe ein
        # europaeisches Bild - auch die 720, die vorher Crusader blieben.
        expected_frame_count=1936,
        expected_geometry_proof_sha256="202fd0992e4e1f5bcf6ee61cddcbc1818ca14ed204f29a384ee97e77c12e1615",
        expected_origin_proof_sha256="6ed67e40cf545980c72c06e8a88d699798f40099ace7eb0a08dbfe0ecab0fb3a",
        expected_source_rgba_sha256="d5cdd1386ba83d13c52e9a837d26f71edba9730e0a7fe121caf18b7cbd983370",
        source_anchor_tolerance_px=0.51,
    ),
}


def native_source_geometry_contract(
    group: str, mode: str
) -> NativeSourceGeometryContract | None:
    """Return only the contract reviewed for this exact native mode."""

    if mode == GEOMETRY_POLICY_NATIVE_REANCHORED:
        return NATIVE_SOURCE_REANCHORED_139_CONTRACTS.get(group)
    if mode == GEOMETRY_POLICY_NATIVE_AUTHORED_PIVOT:
        if group in REVIEW_NATIVE_GEOMETRY_139_GROUPS:
            review_contract = (
                NATIVE_SOURCE_REVIEW_AUTHORED_PIVOT_139_CONTRACTS.get(group)
            )
            if (
                review_contract is not None
                and group in NATIVE_SOURCE_AUTHORED_PIVOT_139_CONTRACTS
            ):
                # Zwei Vertraege fuer denselben Modus koennten sich
                # widersprechen; welcher gilt, waere Auslegungssache.
                raise GMAtlasError(
                    f"Native authored-pivot contract for {group} is ambiguous: "
                    "it appears in both the review and the standard table"
                )
            if review_contract is not None:
                return review_contract
        return NATIVE_SOURCE_AUTHORED_PIVOT_139_CONTRACTS.get(group)
    return None


def required_native_source_geometry_contract(
    group: str,
) -> tuple[str, NativeSourceGeometryContract] | None:
    """Find the one frozen native mode assigned to a loader-owned group."""

    matches = [
        (mode, contract)
        for mode, contracts in (
            (
                GEOMETRY_POLICY_NATIVE_REANCHORED,
                NATIVE_SOURCE_REANCHORED_139_CONTRACTS,
            ),
            (
                GEOMETRY_POLICY_NATIVE_AUTHORED_PIVOT,
                NATIVE_SOURCE_AUTHORED_PIVOT_139_CONTRACTS,
            ),
        )
        if (contract := contracts.get(group)) is not None
    ]
    if len(matches) > 1:
        raise GMAtlasError(
            f"Native source geometry mode is ambiguous for {group}: "
            f"{[mode for mode, _ in matches]}"
        )
    return matches[0] if matches else None


@dataclass(frozen=True)
class NativeSourceGeometryPolicy:
    """Explicit opt-in to native SH1DE canvases with frozen provenance."""

    mode: str
    proof_algorithm: str
    expected_frame_count: int
    expected_geometry_proof_sha256: str
    expected_origin_proof_sha256: str
    expected_source_rgba_sha256: str

    @classmethod
    def from_profile(
        cls,
        raw: object,
        group: str,
        expected_group_frame_count: int,
    ) -> "NativeSourceGeometryPolicy":
        if not isinstance(raw, dict):
            raise GMAtlasError(
                f"geometry_policy for {group} must be a frozen contract object"
            )
        expected_keys = {
            "mode",
            "proof_algorithm",
            "expected_frame_count",
            "expected_geometry_proof_sha256",
            "expected_origin_proof_sha256",
            "expected_source_rgba_sha256",
        }
        if set(raw) != expected_keys:
            raise GMAtlasError(
                f"geometry_policy fields changed for {group}: "
                f"actual={sorted(raw)} expected={sorted(expected_keys)}"
            )
        mode = raw.get("mode")
        if mode not in {
            GEOMETRY_POLICY_NATIVE_REANCHORED,
            GEOMETRY_POLICY_NATIVE_AUTHORED_PIVOT,
        }:
            raise GMAtlasError(
                f"Unsupported geometry_policy mode for {group}: {mode!r}"
            )
        proof_algorithm = raw.get("proof_algorithm")
        expected_algorithm = (
            NATIVE_SOURCE_GEOMETRY_PROOF_ALGORITHM
            if mode == GEOMETRY_POLICY_NATIVE_REANCHORED
            else NATIVE_SOURCE_AUTHORED_PIVOT_PROOF_ALGORITHM
        )
        if proof_algorithm != expected_algorithm:
            raise GMAtlasError(
                f"Native geometry proof algorithm for {group} changed: "
                f"{proof_algorithm!r}"
            )
        policy = cls(
            mode=mode,
            proof_algorithm=proof_algorithm,
            expected_frame_count=_positive_int(
                raw, "expected_frame_count", group
            ),
            expected_geometry_proof_sha256=_require_sha256(
                raw, "expected_geometry_proof_sha256", group
            ),
            expected_origin_proof_sha256=_require_sha256(
                raw, "expected_origin_proof_sha256", group
            ),
            expected_source_rgba_sha256=_require_sha256(
                raw, "expected_source_rgba_sha256", group
            ),
        )
        if policy.expected_frame_count != expected_group_frame_count:
            raise GMAtlasError(
                f"Native geometry policy for {group} does not cover the complete "
                f"target manifest: {policy.expected_frame_count} != "
                f"{expected_group_frame_count}"
            )
        contract = native_source_geometry_contract(group, mode)
        if contract is None:
            raise GMAtlasError(
                f"{group} has no reviewed native-source geometry contract "
                f"for {mode}"
            )
        actual = (
            policy.expected_frame_count,
            policy.expected_geometry_proof_sha256,
            policy.expected_origin_proof_sha256,
            policy.expected_source_rgba_sha256,
        )
        expected = (
            contract.expected_frame_count,
            contract.expected_geometry_proof_sha256,
            contract.expected_origin_proof_sha256,
            contract.expected_source_rgba_sha256,
        )
        if actual != expected:
            proof_mismatch(
                f"Native geometry proof contract for {group} changed: "
                f"actual={actual} expected={expected}"
            )
        return policy


def native_reanchored_pivot(
    source: Mapping[str, Any],
    target: Mapping[str, Any],
    frame_name: str | None = None,
) -> tuple[float, float]:
    """Normalised pivot that preserves the target's absolute anchor.

    The sprite keeps the source canvas but lands on exactly the anchor Crusader
    expects, so nothing moves on the tile.

    Welche KANTE dabei die feste Groesse traegt, entscheidet
    :func:`native_reanchored_anchor` je Achse aus dem Zielpivot: bei exakt 1,0
    die obere bzw. rechte, sonst die untere bzw. linke.

    ``frame_name`` wird nur noch fuer Fehlermeldungen mitgefuehrt; eine
    Ausnahmeliste je Frame gibt es seit dem 04.09.2026 nicht mehr.
    """

    source_width = float(source["width"])
    source_height = float(source["height"])
    target_width = float(target["width"])
    target_height = float(target["height"])
    target_pivot_x = float(target["pivot_x"])
    target_pivot_y = float(target["pivot_y"])
    if (
        not all(
            isfinite(value)
            for value in (
                source_width,
                source_height,
                target_width,
                target_height,
                target_pivot_x,
                target_pivot_y,
            )
        )
        or source_width <= 0
        or source_height <= 0
        or target_width <= 0
        or target_height <= 0
    ):
        raise GMAtlasError(f"Invalid source canvas: {source_width}x{source_height}")
    anchor_x = native_reanchored_anchor(
        target_pivot_x, target_width, source_width
    )
    anchor_y = native_reanchored_anchor(
        target_pivot_y, target_height, source_height
    )
    # GameAtlasManagerAPI reads JSON pivots with GetSingle. Quantising here
    # makes the proof cover the exact float that Sprite.Create will receive.
    return (
        _float32(anchor_x / source_width),
        _float32(anchor_y / source_height),
    )


def _float32(value: float) -> float:
    try:
        result = struct.unpack("<f", struct.pack("<f", float(value)))[0]
    except (OverflowError, struct.error, TypeError, ValueError) as exc:
        raise GMAtlasError(f"Value cannot be represented as float32: {value!r}") from exc
    if not isfinite(result):
        raise GMAtlasError(f"Value is not a finite float32: {value!r}")
    return result


def native_authored_pivot(source: Mapping[str, Any]) -> tuple[float, float]:
    """Return the exact float32 pivot authored in the SH1DE source sprite."""

    try:
        pivot_x = source["pivot_x"]
        pivot_y = source["pivot_y"]
    except (KeyError, TypeError) as exc:
        raise GMAtlasError("Native authored pivot metadata is incomplete") from exc
    return _float32(pivot_x), _float32(pivot_y)


def native_authored_pixels_per_unit(source: Mapping[str, Any]) -> float:
    """Return the exact positive float32 PPU authored in SH1DE."""

    try:
        pixels_per_unit = _float32(source["pixels_per_unit"])
    except (KeyError, TypeError) as exc:
        raise GMAtlasError("Native authored PPU metadata is incomplete") from exc
    if pixels_per_unit <= 0:
        raise GMAtlasError("Native authored PPU must be positive")
    return pixels_per_unit


@dataclass(frozen=True)
class DerivedFramePolicy:
    """Freeze the complete REPLACE_DERIVED proof set for a reviewed GM group."""

    mode: str
    proof_algorithm: str
    expected_frame_count: int
    expected_discarded_mask_alpha: int
    expected_frame_proof_sha256: str

    @classmethod
    def from_profile(
        cls,
        raw: object,
        group: str,
        expected_group_frame_count: int,
    ) -> "DerivedFramePolicy":
        if not isinstance(raw, dict):
            raise GMAtlasError(
                f"derived_frame_policy for {group} must be an object"
            )
        expected_keys = {
            "mode",
            "proof_algorithm",
            "expected_frame_count",
            "expected_discarded_mask_alpha",
            "expected_frame_proof_sha256",
        }
        if set(raw) != expected_keys:
            raise GMAtlasError(
                f"derived_frame_policy fields changed for {group}: "
                f"actual={sorted(raw)} expected={sorted(expected_keys)}"
            )
        mode = raw.get("mode")
        if mode != DERIVED_FRAME_POLICY_MODE:
            raise GMAtlasError(
                f"Unsupported derived_frame_policy mode for {group}: {mode!r}"
            )
        proof_algorithm = raw.get("proof_algorithm")
        if proof_algorithm != PLACEMENT_PROOF_ALGORITHM:
            raise GMAtlasError(
                f"Derived proof algorithm for {group} changed: "
                f"{proof_algorithm!r}"
            )
        frame_count = _positive_int(raw, "expected_frame_count", group)
        if frame_count > expected_group_frame_count:
            raise GMAtlasError(
                f"Derived proof frame count for {group} exceeds the complete "
                f"target manifest: {frame_count} > {expected_group_frame_count}"
            )
        policy = cls(
            mode=mode,
            proof_algorithm=proof_algorithm,
            expected_frame_count=frame_count,
            expected_discarded_mask_alpha=_nonnegative_int(
                raw, "expected_discarded_mask_alpha", group
            ),
            expected_frame_proof_sha256=_require_sha256(
                raw, "expected_frame_proof_sha256", group
            ),
        )
        contract = DERIVED_POLICY_139_CONTRACTS.get(group)
        if (
            contract is not None
            and policy.expected_frame_count != contract.expected_frame_count
        ):
            raise GMAtlasError(
                f"Derived proof frame count for {group} changed: "
                f"actual={policy.expected_frame_count} "
                f"expected={contract.expected_frame_count}"
            )
        if contract is not None and (
            policy.expected_discarded_mask_alpha
            != contract.expected_discarded_mask_alpha
            or policy.expected_frame_proof_sha256
            != contract.expected_frame_proof_sha256
        ):
            actual = (
                policy.expected_frame_count,
                policy.expected_discarded_mask_alpha,
                policy.expected_frame_proof_sha256,
            )
            expected = (
                contract.expected_frame_count,
                contract.expected_discarded_mask_alpha,
                contract.expected_frame_proof_sha256,
            )
            proof_mismatch(
                f"Derived proof contract for {group} changed: "
                f"actual={actual} expected={expected}"
            )
        return policy


@dataclass(frozen=True)
class ReviewFramePolicy:
    mode: str
    proof_algorithm: str
    expected_source_frame_count: int
    expected_target_frame_count: int
    expected_source_names_sha256: str
    expected_target_names_sha256: str
    expected_provenance_sha256: str
    expected_keep_frame_count: int = 0
    expected_keep_names_sha256: str = ""
    expected_blocked_review_frame_count: int = 0
    expected_blocked_review_names_sha256: str = ""
    expected_fractional_frame_count: int = 0
    expected_fractional_names_sha256: str = ""
    expected_action_origin_status_sha256: str = ""

    @property
    def includes_keep(self) -> bool:
        return self.mode in {
            REVIEW_FRAME_POLICY_MODE_V2,
            REVIEW_FRAME_POLICY_MODE_V3,
        }

    @property
    def renders_native_source(self) -> bool:
        """Wird jeder REVIEW_MANUAL-Frame ueber die Quellgeometrie gerendert?"""

        return self.mode == REVIEW_FRAME_POLICY_MODE_V3

    @classmethod
    def from_profile(
        cls,
        raw: object,
        group: str,
        expected_frame_count: int,
    ) -> "ReviewFramePolicy":
        if not isinstance(raw, dict):
            raise GMAtlasError(f"review_frame_policy for {group} must be an object")
        mode = raw.get("mode")
        if mode not in {
            REVIEW_FRAME_POLICY_MODE_V1,
            REVIEW_FRAME_POLICY_MODE_V2,
            REVIEW_FRAME_POLICY_MODE_V3,
        }:
            raise GMAtlasError(
                f"Unsupported review_frame_policy mode for {group}: {mode!r}"
            )
        expected_keys = {
            "mode",
            "proof_algorithm",
            "expected_source_frame_count",
            "expected_target_frame_count",
            "expected_source_names_sha256",
            "expected_target_names_sha256",
            "expected_provenance_sha256",
        }
        if mode in {REVIEW_FRAME_POLICY_MODE_V2, REVIEW_FRAME_POLICY_MODE_V3}:
            # V3 fuehrt denselben Feldsatz wie V2. Nur die Werte aendern sich:
            # blocked ist per Bauart 0, target deckt sich mit keep.
            expected_keys.update(
                {
                    "expected_keep_frame_count",
                    "expected_keep_names_sha256",
                    "expected_blocked_review_frame_count",
                    "expected_blocked_review_names_sha256",
                    "expected_fractional_frame_count",
                    "expected_fractional_names_sha256",
                    "expected_action_origin_status_sha256",
                }
            )
        if set(raw) != expected_keys:
            raise GMAtlasError(
                f"review_frame_policy fields changed for {group}: "
                f"actual={sorted(raw)} expected={sorted(expected_keys)}"
            )
        proof_algorithm = raw.get("proof_algorithm")
        if proof_algorithm != PLACEMENT_PROOF_ALGORITHM:
            raise GMAtlasError(
                f"Review proof algorithm for {group} changed: {proof_algorithm!r}"
            )
        source_count = _positive_int(
            raw, "expected_source_frame_count", group
        )
        # Unter V3 darf die Zielpartition LEER sein, unter V1 und V2 nicht.
        #
        # V3 heisst "alle Spenderframes nativ rendern, den Rest behalten" - und
        # der Rest kann leer sein. body_swordsman ist genau dieser Fall: 1184
        # Frames, alle mit Spender, kein einziger KEEP_CRUSADER. Unter V1 und V2
        # bleibt die Positivforderung, weil dort eine leere Zielpartition
        # bedeutet, dass die Politik ueberhaupt nichts zu entscheiden hat.
        #
        # Das ist ausdruecklich NICHT derselbe Fall wie am 13.08., als hier
        # schon einmal keep > 0 gelockert wurde: Damals gab es mit V1 eine
        # richtige Heimat fuer Gruppen ohne Keep-Frames, und der Test, der die
        # Forderung hielt, hatte recht. V1 rendert aber auf der Zielleinwand und
        # weist zu grosse Frames ab - fuer eine Gruppe, die nativ rendern soll,
        # gibt es keine solche Alternative.
        if mode == REVIEW_FRAME_POLICY_MODE_V3:
            target_count = _nonnegative_int(
                raw, "expected_target_frame_count", group
            )
        else:
            target_count = _positive_int(
                raw, "expected_target_frame_count", group
            )
        if source_count + target_count != expected_frame_count:
            raise GMAtlasError(
                f"Review frame partition for {group} does not cover the complete "
                f"target manifest: source={source_count} target={target_count} "
                f"frames={expected_frame_count}"
            )
        keep_count = 0
        keep_digest = ""
        blocked_count = 0
        blocked_digest = ""
        fractional_count = 0
        fractional_digest = ""
        action_origin_status_digest = ""
        if mode in {REVIEW_FRAME_POLICY_MODE_V2, REVIEW_FRAME_POLICY_MODE_V3}:
            # Dieselbe Begruendung wie bei target_count oben: Unter V3 ist eine
            # leere Keep-Menge gueltig, weil keep == target gilt (blocked ist
            # dort verboten). Unter V2 bleibt die Positivforderung - dort ist
            # das Behalten der Zweck der Politik.
            keep_count = (
                _nonnegative_int(raw, "expected_keep_frame_count", group)
                if mode == REVIEW_FRAME_POLICY_MODE_V3
                else _positive_int(raw, "expected_keep_frame_count", group)
            )
            blocked_count = _nonnegative_int(
                raw, "expected_blocked_review_frame_count", group
            )
            fractional_count = _nonnegative_int(
                raw, "expected_fractional_frame_count", group
            )
            if keep_count + blocked_count != target_count:
                raise GMAtlasError(
                    f"Review v2 target partition for {group} changed: "
                    f"keep={keep_count} blocked={blocked_count} target={target_count}"
                )
            if fractional_count != 0:
                raise GMAtlasError(
                    f"Review v2 for {group} has no approved fractional render rule"
                )
            if mode == REVIEW_FRAME_POLICY_MODE_V3 and blocked_count != 0:
                # Unter V3 gibt es keine Zielleinwand und damit keinen Weg,
                # einen Frame abzuweisen. Eine Zahl ungleich null waere ein
                # Rueckfall auf die Zielleinwand - hier verboten, nicht bloss
                # unwahrscheinlich.
                raise GMAtlasError(
                    f"Review v3 for {group} cannot block a frame: "
                    f"blocked={blocked_count}"
                )
            keep_digest = _require_sha256(
                raw, "expected_keep_names_sha256", group
            )
            blocked_digest = _require_sha256(
                raw, "expected_blocked_review_names_sha256", group
            )
            fractional_digest = _require_sha256(
                raw, "expected_fractional_names_sha256", group
            )
            action_origin_status_digest = _require_sha256(
                raw, "expected_action_origin_status_sha256", group
            )
        return cls(
            mode=mode,
            proof_algorithm=proof_algorithm,
            expected_source_frame_count=source_count,
            expected_target_frame_count=target_count,
            expected_source_names_sha256=_require_sha256(
                raw, "expected_source_names_sha256", group
            ),
            expected_target_names_sha256=_require_sha256(
                raw, "expected_target_names_sha256", group
            ),
            expected_provenance_sha256=_require_sha256(
                raw, "expected_provenance_sha256", group
            ),
            expected_keep_frame_count=keep_count,
            expected_keep_names_sha256=keep_digest,
            expected_blocked_review_frame_count=blocked_count,
            expected_blocked_review_names_sha256=blocked_digest,
            expected_fractional_frame_count=fractional_count,
            expected_fractional_names_sha256=fractional_digest,
            expected_action_origin_status_sha256=action_origin_status_digest,
        )


ATLAS_GROUP_PROFILE_KEYS = frozenset(
    {
        "gm_file_name",
        "dash_format",
        "mask_policy",
        "source_texture",
        "target_texture",
        "expected_frame_count",
        "expected_main_count",
        "expected_alt_count",
        "expected_max_index",
        "expected_names_sha256",
        "padding",
        "max_dimension",
        "category",
        "acknowledge_loader_139_foliage_material_mismatch",
        "review_frame_policy",
        "derived_frame_policy",
        "source_remap_policy",
        "animation_remap_policy",
        "geometry_policy",
        "sparse_keep_frame_count",
    }
)
REVIEW_INDIVIDUAL_PROFILE_KEYS = ATLAS_GROUP_PROFILE_KEYS | frozenset(
    {"expected_source_main_count", "expected_source_alt_count"}
)


@dataclass(frozen=True)
class AtlasGroupSpec:
    gm_file_name: str
    dash_format: bool
    mask_policy: str
    source_texture: str
    target_texture: str
    expected_frame_count: int
    expected_main_count: int
    expected_alt_count: int
    expected_max_index: int
    expected_names_sha256: str
    padding: int = 1
    max_dimension: int = 8192
    category: str = "gm_atlas"
    loader_material_compatible: bool = True
    review_frame_policy: ReviewFramePolicy | None = None
    derived_frame_policy: DerivedFramePolicy | None = None
    source_remap_policy: SourceRemapPolicy | None = None
    # Nur gesetzt, wenn das Profil die geprueft freigegebene Phasentabelle
    # ausdruecklich bestellt (heute allein body_lord).
    animation_remap_policy: AnimationRemapPolicy | None = None
    geometry_policy: str = GEOMETRY_POLICY_TARGET_CANVAS
    native_source_geometry_policy: NativeSourceGeometryPolicy | None = None
    # Frames with no European donor. The atlas still carries them - copied
    # verbatim from Crusader - because ApplySingle sizes the GM array from the
    # highest index in our JSON. Omitting the tail would truncate the array and
    # delete those sprites from the game rather than preserve them.
    sparse_keep_frame_count: int | None = None

    @property
    def uses_native_geometry(self) -> bool:
        return self.geometry_policy in {
            GEOMETRY_POLICY_NATIVE_REANCHORED,
            GEOMETRY_POLICY_NATIVE_AUTHORED_PIVOT,
        }

    @property
    def uses_authored_source_geometry(self) -> bool:
        return self.geometry_policy == GEOMETRY_POLICY_NATIVE_AUTHORED_PIVOT

    @classmethod
    def from_profile(cls, raw: object) -> "AtlasGroupSpec":
        if not isinstance(raw, dict):
            raise GMAtlasError("GM atlas entries must be objects")
        unexpected = set(raw) - ATLAS_GROUP_PROFILE_KEYS
        if unexpected:
            raise GMAtlasError(
                f"Unknown GM atlas fields: {sorted(unexpected)}"
            )
        name = raw.get("gm_file_name")
        if not isinstance(name, str) or not name:
            raise GMAtlasError("gm_file_name must be a non-empty string")
        # The loader fact is checked before the reviewed allow-list on purpose:
        # array ownership is not a review decision, and adding such a group to
        # the allow-list must never be enough to make it producible.
        loader_group = LOADER_GROUP_TABLE.get(name)
        if loader_group is not None and not loader_group.owns_its_gm_arrays:
            raise GMAtlasError(
                f"{name} does not own its {loader_group.gm_enum} arrays "
                f"(ID_Offset={loader_group.id_offset}, "
                f"additionalStorage={loader_group.additional_storage}); the 1.39 "
                "atlas API sizes the array from the override JSON and writes at "
                "the raw index, which would truncate and misindex the shared array"
            )
        if name not in LOADER_139_GROUPS:
            raise GMAtlasError(
                f"GM group is not verified against the SHCDE-SE 1.39 loader: {name!r}"
            )
        loader_dash_format, loader_mask_policy, material_compatible = LOADER_139_GROUPS[name]
        dash_format = raw.get("dash_format")
        mask_policy = raw.get("mask_policy")
        if dash_format is not loader_dash_format:
            raise GMAtlasError(
                f"dash_format for {name} must match loader 1.39: {loader_dash_format}"
            )
        if mask_policy != loader_mask_policy:
            raise GMAtlasError(
                f"mask_policy for {name} must match the reviewed policy: "
                f"{loader_mask_policy}"
            )
        if (
            not material_compatible
            and raw.get("acknowledge_loader_139_foliage_material_mismatch") is not True
        ):
            raise GMAtlasError(
                f"{name} uses Unlit/Foliage in vanilla, but the SHCDE-SE 1.39 "
                "atlas loader hard-codes Unlit/TeamColour; the profile must "
                "acknowledge the required visual runtime gate"
            )

        expected_hash_raw = raw.get("expected_names_sha256")
        expected_hash = (
            expected_hash_raw.lower()
            if isinstance(expected_hash_raw, str)
            else ""
        )
        if re.fullmatch(r"[0-9a-f]{64}", expected_hash) is None:
            raise GMAtlasError(f"Invalid expected_names_sha256 for {name}")

        padding = raw.get("padding", 1)
        max_dimension = raw.get("max_dimension", 8192)
        if type(padding) is not int:
            raise GMAtlasError(f"Atlas padding for {name} must be an integer")
        if type(max_dimension) is not int:
            raise GMAtlasError(f"max_dimension for {name} must be an integer")
        if padding < 1 or padding > 16:
            raise GMAtlasError(f"Atlas padding for {name} must be between 1 and 16")
        if not _is_power_of_two(max_dimension) or not 256 <= max_dimension <= 8192:
            raise GMAtlasError(
                f"max_dimension for {name} must be a power of two from 256 through 8192"
            )

        source_texture = raw.get("source_texture")
        target_texture = raw.get("target_texture")
        if (
            not isinstance(source_texture, str)
            or not source_texture
            or not isinstance(target_texture, str)
            or not target_texture
        ):
            raise GMAtlasError(f"Source and target textures are required for {name}")

        category = raw.get("category", "gm_atlas")
        if not isinstance(category, str) or not category:
            raise GMAtlasError(f"Atlas category for {name} must be a non-empty string")

        expected_frame_count = _positive_int(
            raw, "expected_frame_count", name
        )
        raw_derived_policy = raw.get("derived_frame_policy")
        derived_frame_policy = (
            DerivedFramePolicy.from_profile(
                raw_derived_policy, name, expected_frame_count
            )
            if raw_derived_policy is not None
            else None
        )
        if name in DERIVED_POLICY_139_GROUPS:
            if derived_frame_policy is None:
                raise GMAtlasError(
                    f"{name} requires an explicit derived_frame_policy"
                )
        elif derived_frame_policy is not None:
            raise GMAtlasError(
                f"{name} has no reviewed derived-frame contract"
            )
        raw_review_policy = raw.get("review_frame_policy")
        review_frame_policy = (
            ReviewFramePolicy.from_profile(
                raw_review_policy, name, expected_frame_count
            )
            if raw_review_policy is not None
            else None
        )
        review_texture_contract = REVIEW_139_GROUP_TEXTURES.get(name)
        if review_texture_contract is not None:
            if review_frame_policy is None:
                raise GMAtlasError(
                    f"{name} requires an explicit review_frame_policy"
                )
            if (source_texture, target_texture) != review_texture_contract:
                raise GMAtlasError(
                    f"Review texture contract changed for {name}: "
                    f"actual={(source_texture, target_texture)} "
                    f"expected={review_texture_contract}"
                )
        elif review_frame_policy is not None:
            raise GMAtlasError(
                f"{name} has no reviewed mixed-texture contract"
            )
        if derived_frame_policy is not None and review_frame_policy is not None:
            raise GMAtlasError(
                f"{name} cannot combine derived and mixed-review policies"
            )
        raw_source_remap_policy = raw.get("source_remap_policy")
        source_remap_policy = (
            SourceRemapPolicy.from_profile(
                raw_source_remap_policy, name, expected_frame_count
            )
            if raw_source_remap_policy is not None
            else None
        )
        source_remap_contract = SOURCE_REMAP_139_CONTRACTS.get(name)
        if source_remap_contract is not None:
            if source_remap_policy is None:
                raise GMAtlasError(
                    f"{name} requires an explicit source_remap_policy"
                )
            if (source_texture, target_texture) != (
                source_remap_contract.source_texture,
                source_remap_contract.target_texture,
            ):
                raise GMAtlasError(
                    f"Source remap texture contract changed for {name}: "
                    f"actual={(source_texture, target_texture)} expected="
                    f"{(source_remap_contract.source_texture, source_remap_contract.target_texture)}"
                )
        elif source_remap_policy is not None:
            raise GMAtlasError(
                f"{name} has no reviewed source-remap contract"
            )
        if source_remap_policy is not None and review_frame_policy is not None:
            raise GMAtlasError(
                f"{name} cannot combine source remap and mixed-review policies"
            )
        raw_animation_remap_policy = raw.get("animation_remap_policy")
        animation_remap_policy = (
            _parse_animation_remap_policy(raw_animation_remap_policy, name)
            if raw_animation_remap_policy is not None
            else None
        )
        if (
            animation_remap_policy is not None
            and source_remap_policy is not None
        ):
            # Zwei Umlenkwege auf denselben Plaetzen waeren Auslegungssache.
            raise GMAtlasError(
                f"{name} cannot combine animation remap and source remap"
            )

        raw_geometry_policy = raw.get(
            "geometry_policy", GEOMETRY_POLICY_TARGET_CANVAS
        )
        native_source_geometry_policy = None
        if isinstance(raw_geometry_policy, dict):
            # Keep-Crusader frames are copied, not re-anchored, so the geometry
            # proof covers only the frames that actually come from Europe.
            if (
                review_frame_policy is not None
                and review_frame_policy.renders_native_source
            ):
                # Eine V3-Gruppe zaehlt ihre Crusader-Kopien in der
                # review_frame_policy, nicht in sparse_keep_frame_count; beide
                # schliessen sich weiter unten ohnehin aus.
                european_frame_count = (
                    expected_frame_count
                    - review_frame_policy.expected_keep_frame_count
                )
            else:
                raw_keep = raw.get("sparse_keep_frame_count")
                european_frame_count = expected_frame_count - (
                    raw_keep
                    if isinstance(raw_keep, int) and not isinstance(raw_keep, bool)
                    else 0
                )
            native_source_geometry_policy = NativeSourceGeometryPolicy.from_profile(
                raw_geometry_policy, name, european_frame_count
            )
            geometry_policy = native_source_geometry_policy.mode
        elif isinstance(raw_geometry_policy, str):
            geometry_policy = raw_geometry_policy
        else:
            raise GMAtlasError(
                f"geometry_policy for {name} must be a string or object"
            )
        if geometry_policy not in GEOMETRY_POLICIES:
            raise GMAtlasError(
                f"Unknown geometry_policy for {name}: {geometry_policy!r}"
            )
        if geometry_policy in {
            GEOMETRY_POLICY_NATIVE_REANCHORED,
            GEOMETRY_POLICY_NATIVE_AUTHORED_PIVOT,
        } and native_source_geometry_policy is None:
            raise GMAtlasError(
                f"Native geometry for {name} requires a frozen contract object"
            )
        required_native = required_native_source_geometry_contract(name)
        if required_native is not None and native_source_geometry_policy is None:
            raise GMAtlasError(
                f"{name} requires an explicit frozen native-source geometry policy"
            )
        if native_source_geometry_policy is not None:
            native_contract = native_source_geometry_contract(
                name, native_source_geometry_policy.mode
            )
            if native_contract is None:
                raise GMAtlasError(
                    f"{name} has no reviewed contract for "
                    f"{native_source_geometry_policy.mode}"
                )
            if (source_texture, target_texture) != (
                native_contract.source_texture,
                native_contract.target_texture,
            ):
                raise GMAtlasError(
                    f"Native geometry texture contract changed for {name}: "
                    f"actual={(source_texture, target_texture)} expected="
                    f"{(native_contract.source_texture, native_contract.target_texture)}"
                )
            if (
                required_native is not None
                and required_native[0] != native_source_geometry_policy.mode
            ):
                raise GMAtlasError(
                    f"Native geometry mode changed for {name}: "
                    f"actual={native_source_geometry_policy.mode} "
                    f"expected={required_native[0]}"
                )
        # Beide nativen Modi sind hier zulaessig, und das ist keine Lockerung
        # der Schranke: Die Freigabeliste bleibt die Schranke. Welcher der
        # beiden Modi richtig ist, entscheidet die Gruppe - Koerper uebernehmen
        # den gezeichneten Pivot, Bauwerke rechnen ihn auf ihren Kachelanker um.
        # Die Zielleinwand kommt in keinem der beiden Faelle vor, und nur darum
        # geht es der Regel: V3 darf nicht behaupten, nativ zu rendern, wenn die
        # Gruppe in Wahrheit auf der Crusader-Leinwand landet.
        native_review_allowed = (
            review_frame_policy is not None
            and review_frame_policy.renders_native_source
            and name in REVIEW_NATIVE_GEOMETRY_139_GROUPS
            and geometry_policy
            in {
                GEOMETRY_POLICY_NATIVE_AUTHORED_PIVOT,
                GEOMETRY_POLICY_NATIVE_REANCHORED,
            }
        )
        if (
            review_frame_policy is not None
            and review_frame_policy.renders_native_source
            and not native_review_allowed
        ):
            # V3 von der anderen Seite verriegelt: die Partition darf nicht
            # behaupten, nativ zu rendern, wenn die Gruppe dafuer nicht
            # freigegeben ist oder gar keine native Geometrie fuehrt.
            raise GMAtlasError(
                f"{name} is not approved to render its review frames natively: "
                f"geometry_policy={geometry_policy!r}"
            )
        if geometry_policy in {
            GEOMETRY_POLICY_NATIVE_REANCHORED,
            GEOMETRY_POLICY_NATIVE_AUTHORED_PIVOT,
        } and review_frame_policy and not native_review_allowed:
            # The mixed-review contract freezes per-frame origins against the
            # target canvas; combining the two would invalidate its proof set.
            #
            # Unter V3 ist das anders und deshalb dreifach eng geoeffnet (Modus
            # V3 UND Freigabeliste UND authored-pivot): dort beschreibt die
            # review_frame_policy nur noch die PARTITION - welcher Slot aus
            # Europa kommt und welcher eine Crusader-Kopie bleibt -, waehrend
            # die geometry_policy das RENDERN beschreibt. Jedes der beiden
            # Objekte behaelt genau eine Aufgabe, sie widersprechen sich nicht.
            raise GMAtlasError(
                f"{name} cannot combine native geometry with a mixed-review policy"
            )
        if geometry_policy in {
            GEOMETRY_POLICY_NATIVE_REANCHORED,
            GEOMETRY_POLICY_NATIVE_AUTHORED_PIVOT,
        } and derived_frame_policy:
            raise GMAtlasError(
                f"{name} cannot combine native geometry with a target-canvas "
                "derived-frame policy"
            )
        if geometry_policy in {
            GEOMETRY_POLICY_NATIVE_REANCHORED,
            GEOMETRY_POLICY_NATIVE_AUTHORED_PIVOT,
        } and source_remap_policy:
            raise GMAtlasError(
                f"{name} cannot combine native geometry with a cross-index "
                "source-remap policy"
            )

        raw_sparse_keep = raw.get("sparse_keep_frame_count")
        sparse_keep: int | None = None
        if raw_sparse_keep is not None:
            if (
                isinstance(raw_sparse_keep, bool)
                or not isinstance(raw_sparse_keep, int)
                or raw_sparse_keep < 1
            ):
                raise GMAtlasError(
                    f"sparse_keep_frame_count for {name} must be a positive integer"
                )
            if review_frame_policy is not None:
                raise GMAtlasError(
                    f"{name} cannot combine a sparse keep count with the review "
                    "frame policy"
                )
            if raw_sparse_keep >= expected_frame_count:
                raise GMAtlasError(
                    f"sparse_keep_frame_count for {name} leaves no European frame"
                )
            sparse_keep = raw_sparse_keep

        return cls(
            gm_file_name=name,
            dash_format=loader_dash_format,
            mask_policy=loader_mask_policy,
            source_texture=source_texture,
            target_texture=target_texture,
            expected_frame_count=expected_frame_count,
            expected_main_count=_positive_int(raw, "expected_main_count", name),
            expected_alt_count=_nonnegative_int(raw, "expected_alt_count", name),
            expected_max_index=_nonnegative_int(raw, "expected_max_index", name),
            expected_names_sha256=expected_hash,
            padding=padding,
            max_dimension=max_dimension,
            category=category,
            loader_material_compatible=material_compatible,
            review_frame_policy=review_frame_policy,
            derived_frame_policy=derived_frame_policy,
            source_remap_policy=source_remap_policy,
            animation_remap_policy=animation_remap_policy,
            geometry_policy=geometry_policy,
            native_source_geometry_policy=native_source_geometry_policy,
            sparse_keep_frame_count=sparse_keep,
        )

    @property
    def require_mask(self) -> bool:
        return self.mask_policy == "required"


SHARED_GM_MEMBER_PROFILE_KEYS = frozenset(
    {
        "gm_file_name",
        "slot_offset",
        "expected_frame_count",
        "expected_names_sha256",
        "expected_geometry_proof_sha256",
        "expected_origin_proof_sha256",
        "expected_source_rgba_sha256",
        "expected_source_anchor_max_error_px",
        "expected_runtime_anchor_max_error_px",
    }
)
SHARED_GM_ATLAS_PROFILE_KEYS = frozenset(
    {
        "mode",
        "host_gm_file_name",
        "gm_enum",
        "dash_format",
        "mask_policy",
        "source_texture",
        "target_texture",
        "expected_frame_count",
        "expected_main_count",
        "expected_alt_count",
        "expected_max_index",
        "expected_array_size",
        "expected_null_slot_count",
        "expected_combined_names_sha256",
        "expected_output_names_sha256",
        "expected_slot_logical_output_sha256",
        "expected_slot_logical_source_rgba_sha256",
        "geometry_policy",
        "members",
        "padding",
        "max_dimension",
        "category",
    }
)


@dataclass(frozen=True)
class SharedGMAtlasMemberSpec:
    gm_file_name: str
    slot_offset: int
    expected_frame_count: int
    expected_names_sha256: str
    expected_geometry_proof_sha256: str
    expected_origin_proof_sha256: str
    expected_source_rgba_sha256: str
    expected_source_anchor_max_error_px: float
    expected_runtime_anchor_max_error_px: float

    @classmethod
    def from_profile(
        cls, raw: object, host: str
    ) -> "SharedGMAtlasMemberSpec":
        if not isinstance(raw, dict):
            raise GMAtlasError(f"Shared GM member for {host} must be an object")
        if set(raw) != SHARED_GM_MEMBER_PROFILE_KEYS:
            raise GMAtlasError(
                f"Shared GM member fields changed for {host}: "
                f"actual={sorted(raw)} expected={sorted(SHARED_GM_MEMBER_PROFILE_KEYS)}"
            )
        name = raw.get("gm_file_name")
        if not isinstance(name, str) or not name:
            raise GMAtlasError(f"Shared GM member for {host} has no name")

        def finite_nonnegative(field: str) -> float:
            value = raw.get(field)
            if isinstance(value, bool):
                raise GMAtlasError(f"Shared GM member {name} has invalid {field}")
            try:
                number = float(value)
            except (TypeError, ValueError) as exc:
                raise GMAtlasError(
                    f"Shared GM member {name} has invalid {field}"
                ) from exc
            if not isfinite(number) or number < 0:
                raise GMAtlasError(f"Shared GM member {name} has invalid {field}")
            return number

        return cls(
            gm_file_name=name,
            slot_offset=_nonnegative_int(raw, "slot_offset", name),
            expected_frame_count=_positive_int(
                raw, "expected_frame_count", name
            ),
            expected_names_sha256=_require_sha256(
                raw, "expected_names_sha256", name
            ),
            expected_geometry_proof_sha256=_require_sha256(
                raw, "expected_geometry_proof_sha256", name
            ),
            expected_origin_proof_sha256=_require_sha256(
                raw, "expected_origin_proof_sha256", name
            ),
            expected_source_rgba_sha256=_require_sha256(
                raw, "expected_source_rgba_sha256", name
            ),
            expected_source_anchor_max_error_px=finite_nonnegative(
                "expected_source_anchor_max_error_px"
            ),
            expected_runtime_anchor_max_error_px=finite_nonnegative(
                "expected_runtime_anchor_max_error_px"
            ),
        )


@dataclass(frozen=True)
class SharedGMAtlasSpec:
    mode: str
    host_gm_file_name: str
    gm_enum: str
    dash_format: bool
    mask_policy: str
    source_texture: str
    target_texture: str
    expected_frame_count: int
    expected_main_count: int
    expected_alt_count: int
    expected_max_index: int
    expected_array_size: int
    expected_null_slot_count: int
    expected_combined_names_sha256: str
    expected_output_names_sha256: str
    expected_slot_logical_output_sha256: str
    expected_slot_logical_source_rgba_sha256: str
    geometry_policy: str
    proof_algorithm: str
    members: tuple[SharedGMAtlasMemberSpec, ...]
    padding: int
    max_dimension: int
    category: str

    @property
    def member_names(self) -> tuple[str, ...]:
        return tuple(member.gm_file_name for member in self.members)

    def output_atlas_spec(self) -> AtlasGroupSpec:
        """Return the physical host manifest consumed by the generic packer."""

        return AtlasGroupSpec(
            gm_file_name=self.host_gm_file_name,
            dash_format=self.dash_format,
            mask_policy=self.mask_policy,
            source_texture=self.source_texture,
            target_texture=self.target_texture,
            expected_frame_count=self.expected_frame_count,
            expected_main_count=self.expected_main_count,
            expected_alt_count=self.expected_alt_count,
            expected_max_index=self.expected_max_index,
            expected_names_sha256=self.expected_output_names_sha256,
            padding=self.padding,
            max_dimension=self.max_dimension,
            category=self.category,
            loader_material_compatible=True,
            geometry_policy=self.geometry_policy,
        )

    @classmethod
    def from_profile(cls, raw: object) -> "SharedGMAtlasSpec":
        if not isinstance(raw, dict):
            raise GMAtlasError("Shared GM atlas entries must be objects")
        if set(raw) != SHARED_GM_ATLAS_PROFILE_KEYS:
            raise GMAtlasError(
                "Shared GM atlas fields changed: "
                f"actual={sorted(raw)} expected={sorted(SHARED_GM_ATLAS_PROFILE_KEYS)}"
            )
        host = raw.get("host_gm_file_name")
        if not isinstance(host, str) or not host:
            raise GMAtlasError("Shared GM atlas has no host_gm_file_name")
        contract = SHARED_GM_ATLAS_139_CONTRACTS.get(host)
        if contract is None:
            raise GMAtlasError(
                f"Shared GM host is not reviewed against loader 1.39: {host!r}"
            )
        if raw.get("mode") != SHARED_GM_ATLAS_MODE:
            raise GMAtlasError(
                f"Unsupported shared GM atlas mode for {host}: {raw.get('mode')!r}"
            )
        geometry = raw.get("geometry_policy")
        expected_geometry_keys = {"mode", "proof_algorithm"}
        if not isinstance(geometry, dict) or set(geometry) != expected_geometry_keys:
            raise GMAtlasError(
                f"Shared GM geometry policy fields changed for {host}"
            )
        if geometry.get("mode") != GEOMETRY_POLICY_NATIVE_REANCHORED:
            raise GMAtlasError(
                f"Shared GM atlas {host} requires native source geometry"
            )
        if geometry.get("proof_algorithm") != NATIVE_SOURCE_GEOMETRY_PROOF_ALGORITHM:
            raise GMAtlasError(
                f"Shared GM atlas {host} geometry proof algorithm changed"
            )
        raw_members = raw.get("members")
        if not isinstance(raw_members, list) or not raw_members:
            raise GMAtlasError(f"Shared GM atlas {host} has no members")
        members = tuple(
            SharedGMAtlasMemberSpec.from_profile(item, host)
            for item in raw_members
        )
        padding = raw.get("padding")
        max_dimension = raw.get("max_dimension")
        if type(padding) is not int or not 1 <= padding <= 16:
            raise GMAtlasError(f"Shared GM atlas padding is invalid for {host}")
        if (
            type(max_dimension) is not int
            or not _is_power_of_two(max_dimension)
            or not 256 <= max_dimension <= 8192
        ):
            raise GMAtlasError(
                f"Shared GM atlas max_dimension is invalid for {host}"
            )
        category = raw.get("category")
        if not isinstance(category, str) or not category:
            raise GMAtlasError(f"Shared GM atlas category is invalid for {host}")
        gm_enum = raw.get("gm_enum")
        source_texture = raw.get("source_texture")
        target_texture = raw.get("target_texture")
        if not all(
            isinstance(value, str) and value
            for value in (gm_enum, source_texture, target_texture)
        ):
            raise GMAtlasError(f"Shared GM atlas strings are invalid for {host}")
        if raw.get("dash_format") is not False or raw.get("mask_policy") != "forbidden":
            raise GMAtlasError(
                f"Shared GM atlas {host} must be space-numbered and plain/no-mask"
            )
        spec = cls(
            mode=SHARED_GM_ATLAS_MODE,
            host_gm_file_name=host,
            gm_enum=str(gm_enum),
            dash_format=False,
            mask_policy="forbidden",
            source_texture=str(source_texture),
            target_texture=str(target_texture),
            expected_frame_count=_positive_int(
                raw, "expected_frame_count", host
            ),
            expected_main_count=_positive_int(
                raw, "expected_main_count", host
            ),
            expected_alt_count=_nonnegative_int(
                raw, "expected_alt_count", host
            ),
            expected_max_index=_nonnegative_int(
                raw, "expected_max_index", host
            ),
            expected_array_size=_positive_int(
                raw, "expected_array_size", host
            ),
            expected_null_slot_count=_nonnegative_int(
                raw, "expected_null_slot_count", host
            ),
            expected_combined_names_sha256=_require_sha256(
                raw, "expected_combined_names_sha256", host
            ),
            expected_output_names_sha256=_require_sha256(
                raw, "expected_output_names_sha256", host
            ),
            expected_slot_logical_output_sha256=_require_sha256(
                raw, "expected_slot_logical_output_sha256", host
            ),
            expected_slot_logical_source_rgba_sha256=_require_sha256(
                raw, "expected_slot_logical_source_rgba_sha256", host
            ),
            geometry_policy=GEOMETRY_POLICY_NATIVE_REANCHORED,
            proof_algorithm=NATIVE_SOURCE_GEOMETRY_PROOF_ALGORITHM,
            members=members,
            padding=padding,
            max_dimension=max_dimension,
            category=category,
        )
        expected_contract = (
            contract.gm_enum,
            contract.source_texture,
            contract.target_texture,
            contract.expected_frame_count,
            contract.expected_frame_count,
            0,
            contract.expected_max_index,
            contract.expected_max_index + 1,
            contract.expected_null_slot_count,
            contract.expected_combined_names_sha256,
            contract.expected_output_names_sha256,
            contract.expected_slot_logical_output_sha256,
            contract.expected_slot_logical_source_rgba_sha256,
            contract.members,
        )
        actual_contract = (
            spec.gm_enum,
            spec.source_texture,
            spec.target_texture,
            spec.expected_frame_count,
            spec.expected_main_count,
            spec.expected_alt_count,
            spec.expected_max_index,
            spec.expected_array_size,
            spec.expected_null_slot_count,
            spec.expected_combined_names_sha256,
            spec.expected_output_names_sha256,
            spec.expected_slot_logical_output_sha256,
            spec.expected_slot_logical_source_rgba_sha256,
            tuple(
                SharedGMAtlasMemberContract(**member.__dict__)
                for member in spec.members
            ),
        )
        if actual_contract != expected_contract:
            raise GMAtlasError(
                f"Shared GM atlas contract for {host} changed: "
                f"actual={actual_contract} expected={expected_contract}"
            )
        if spec.expected_frame_count + spec.expected_null_slot_count != spec.expected_array_size:
            raise GMAtlasError(f"Shared GM atlas null partition changed for {host}")
        aliases = SHARED_GM_ENUM_ALIASES.get(spec.gm_enum)
        if aliases != spec.member_names:
            raise GMAtlasError(
                f"Shared GM alias order changed for {host}: {aliases!r}"
            )
        return spec


@dataclass(frozen=True)
class SharedGMFramePlan:
    member_gm_file_name: str
    logical_name: str
    output_name: str
    output_slot: FrameSlot
    proposal: dict[str, Any]


@dataclass(frozen=True)
class ValidatedSharedGMAtlas:
    spec: SharedGMAtlasSpec
    frames: tuple[SharedGMFramePlan, ...]

    def output_group(self) -> ValidatedGroup:
        output_spec = self.spec.output_atlas_spec()
        proposals = tuple(
            {"name": frame.output_name} for frame in self.frames
        )
        return ValidatedGroup(
            spec=output_spec,
            proposals=proposals,
            slots=tuple(frame.output_slot for frame in self.frames),
            array_size=self.spec.expected_array_size,
            names_sha256=self.spec.expected_output_names_sha256,
        )


@dataclass(frozen=True)
class ReviewIndividualSourceOnlySpec:
    """A complete review policy rendered as proven source-name overrides only.

    The embedded :class:`AtlasGroupSpec` still freezes and validates every
    target loader slot.  This wrapper changes only the output backend: proven
    SH1DE frames become individual PNG pairs, while blocked and Crusader-only
    frames remain untouched in the vanilla arrays.
    """

    group: AtlasGroupSpec
    expected_source_main_count: int
    expected_source_alt_count: int

    @classmethod
    def from_profile(cls, raw: object) -> "ReviewIndividualSourceOnlySpec":
        if not isinstance(raw, dict):
            raise GMAtlasError(
                f"{REVIEW_INDIVIDUAL_SOURCE_ONLY_MODE} entries must be objects"
            )
        unexpected = set(raw) - REVIEW_INDIVIDUAL_PROFILE_KEYS
        if unexpected:
            raise GMAtlasError(
                f"Unknown sparse review fields: {sorted(unexpected)}"
            )
        group_raw = {
            key: value
            for key, value in raw.items()
            if key not in {"expected_source_main_count", "expected_source_alt_count"}
        }
        group = AtlasGroupSpec.from_profile(group_raw)
        policy = group.review_frame_policy
        if policy is None or not policy.includes_keep:
            raise GMAtlasError(
                f"Sparse review group {group.gm_file_name} requires the complete "
                "v2 KEEP review_frame_policy"
            )
        if not group.require_mask:
            raise GMAtlasError(
                f"Sparse review group {group.gm_file_name} must emit a mask for "
                "every individual source sprite"
            )
        source_main = _nonnegative_int(
            raw, "expected_source_main_count", group.gm_file_name
        )
        source_alt = _nonnegative_int(
            raw, "expected_source_alt_count", group.gm_file_name
        )
        if source_main + source_alt != policy.expected_source_frame_count:
            raise GMAtlasError(
                f"Sparse source slot partition for {group.gm_file_name} changed: "
                f"main={source_main} alt={source_alt} "
                f"source={policy.expected_source_frame_count}"
            )
        return cls(
            group=group,
            expected_source_main_count=source_main,
            expected_source_alt_count=source_alt,
        )


@dataclass(frozen=True)
class ValidatedGroup:
    spec: AtlasGroupSpec
    proposals: tuple[dict[str, Any], ...]
    slots: tuple[FrameSlot, ...]
    array_size: int
    names_sha256: str


@dataclass(frozen=True)
class AtlasFrame:
    name: str
    slot: FrameSlot
    image: Image.Image
    mask: Image.Image | None
    pivot_x: float
    pivot_y: float
    pixels_per_unit: float


@dataclass(frozen=True)
class FramePlacement:
    name: str
    slot: FrameSlot
    x: int
    y_from_top: int
    width: int
    height: int
    pivot_x: float
    pivot_y: float
    pixels_per_unit: float

    def json_frame(self, atlas_height: int) -> dict[str, Any]:
        # Pillow uses a top-left origin.  Unity's Sprite.Create Rect and the
        # Script Extender atlas schema use a bottom-left origin.
        y_from_bottom = atlas_height - self.y_from_top - self.height
        return {
            "name": self.name,
            "rect": {
                "x": self.x,
                "y": y_from_bottom,
                "w": self.width,
                "h": self.height,
            },
            "pivot": {"x": self.pivot_x, "y": self.pivot_y},
            "pixelsPerUnit": self.pixels_per_unit,
        }


@dataclass(frozen=True)
class BuiltAtlas:
    spec: AtlasGroupSpec
    image: Image.Image
    mask: Image.Image | None
    placements: tuple[FramePlacement, ...]
    atlas_json: dict[str, Any]
    array_size: int
    names_sha256: str
    unique_region_count: int


def _positive_int(raw: dict[str, Any], field: str, group: str) -> int:
    value = _nonnegative_int(raw, field, group)
    if value == 0:
        raise GMAtlasError(f"{field} for {group} must be positive")
    return value


def _nonnegative_int(raw: dict[str, Any], field: str, group: str) -> int:
    value = raw.get(field)
    # Profile data comes from JSON, whose booleans and numbers can otherwise be
    # coerced surprisingly by Python (``bool`` subclasses ``int`` and
    # ``1.0 == 1``).  Count fields are an exact schema boundary: accept only a
    # JSON integer represented by the built-in ``int`` type.
    if type(value) is not int:
        raise GMAtlasError(f"{field} for {group} must be an integer")
    if value < 0:
        raise GMAtlasError(f"{field} for {group} must be a non-negative integer")
    return value


def _require_sha256(raw: dict[str, Any], field: str, group: str) -> str:
    value = str(raw.get(field, "")).lower()
    if re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise GMAtlasError(f"Invalid {field} for {group}")
    return value


def _is_power_of_two(value: int) -> bool:
    return value > 0 and value & (value - 1) == 0


def _next_power_of_two(value: int) -> int:
    if value <= 1:
        return 1
    return 1 << (value - 1).bit_length()


def parse_loader_frame_name(
    sprite_name: str,
    gm_file_name: str,
    dash_format: bool,
) -> FrameSlot | None:
    """Mirror the useful subset of SHCDE-SE 1.39 ParseFrameIndex safely.

    The loader compares the prefix case-insensitively, parses a decimal index,
    and sends a lower-case trailing ``x`` frame to ``gmAltSprites``.  The
    builder deliberately rejects ambiguous forms accepted accidentally by
    ``TrimEnd('x')`` such as ``-1xx``.
    """

    separator = "-" if dash_format else " "
    prefix = gm_file_name + separator
    if sprite_name[: len(prefix)].casefold() != prefix.casefold():
        return None
    suffix = sprite_name[len(prefix) :]
    match = re.fullmatch(r"([0-9]+)(x?)", suffix)
    if match is None:
        return None
    index = int(match.group(1))
    if index < 0:
        return None
    return FrameSlot(index=index, is_alt=bool(match.group(2)))


def _names_digest(names: Iterable[str]) -> str:
    payload = "".join(name + "\n" for name in names).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def shared_gm_atlas_proof(
    rows: Sequence[Mapping[str, Any]],
    spec: SharedGMAtlasSpec,
) -> dict[str, Any]:
    """Validate the exact logical-to-physical slot fusion and source pixels."""

    expected_fields = {
        "slot",
        "member_gm_file_name",
        "logical_name",
        "output_name",
        "source_rgba_sha256",
    }
    member_by_name = {member.gm_file_name: member for member in spec.members}
    slots: list[int] = []
    logical_names: list[str] = []
    output_names: list[str] = []
    member_names: dict[str, list[str]] = {
        member.gm_file_name: [] for member in spec.members
    }
    member_rgba_lines: dict[str, list[str]] = {
        member.gm_file_name: [] for member in spec.members
    }
    slot_logical_output_lines: list[str] = []
    slot_logical_rgba_lines: list[str] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping) or set(row) != expected_fields:
            actual = sorted(row) if isinstance(row, Mapping) else type(row).__name__
            raise GMAtlasError(
                f"Shared GM proof row {index} fields changed: {actual!r}"
            )
        slot = row.get("slot")
        member_name = row.get("member_gm_file_name")
        logical_name = row.get("logical_name")
        output_name = row.get("output_name")
        rgba = row.get("source_rgba_sha256")
        if type(slot) is not int or slot < 0:
            raise GMAtlasError(f"Shared GM proof row {index} has invalid slot")
        if member_name not in member_by_name:
            raise GMAtlasError(
                f"Shared GM proof row {index} has unknown member: {member_name!r}"
            )
        if not isinstance(logical_name, str) or not logical_name:
            raise GMAtlasError(
                f"Shared GM proof row {index} has invalid logical name"
            )
        if not isinstance(output_name, str) or not output_name:
            raise GMAtlasError(
                f"Shared GM proof row {index} has invalid output name"
            )
        if not isinstance(rgba, str) or re.fullmatch(r"[0-9a-f]{64}", rgba) is None:
            raise GMAtlasError(
                f"Shared GM proof row {index} has invalid source RGBA digest"
            )
        member = member_by_name[str(member_name)]
        logical_slot = parse_loader_frame_name(
            logical_name, member.gm_file_name, spec.dash_format
        )
        output_slot = parse_loader_frame_name(
            output_name, spec.host_gm_file_name, spec.dash_format
        )
        if (
            logical_slot is None
            or logical_slot.is_alt
            or output_slot is None
            or output_slot.is_alt
            or output_slot.index != slot
            or logical_slot.index + member.slot_offset != slot
        ):
            raise GMAtlasError(
                f"Shared GM proof row {index} does not preserve its loader slot"
            )
        slots.append(slot)
        logical_names.append(logical_name)
        output_names.append(output_name)
        member_names[member.gm_file_name].append(logical_name)
        member_rgba_lines[member.gm_file_name].append(
            f"{logical_name}\t{rgba}\n"
        )
        slot_logical_output_lines.append(
            f"{slot}\t{logical_name}\t{output_name}\n"
        )
        slot_logical_rgba_lines.append(f"{slot}\t{logical_name}\t{rgba}\n")

    if slots != sorted(slots) or len(slots) != len(set(slots)):
        raise GMAtlasError("Shared GM proof rows are not in unique slot order")
    member_frame_counts = {
        name: len(names) for name, names in member_names.items()
    }
    member_names_sha256 = {
        name: _names_digest(names) for name, names in member_names.items()
    }
    member_source_rgba_sha256 = {
        name: hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()
        for name, lines in member_rgba_lines.items()
    }
    result = {
        "frame_count": len(rows),
        "array_size": max(slots, default=-1) + 1,
        "null_slot_count": max(slots, default=-1) + 1 - len(slots),
        "combined_names_sha256": _names_digest(logical_names),
        "output_names_sha256": _names_digest(output_names),
        "slot_logical_output_sha256": hashlib.sha256(
            "".join(slot_logical_output_lines).encode("utf-8")
        ).hexdigest(),
        "slot_logical_source_rgba_sha256": hashlib.sha256(
            "".join(slot_logical_rgba_lines).encode("utf-8")
        ).hexdigest(),
        "member_frame_counts": member_frame_counts,
        "member_names_sha256": member_names_sha256,
        "member_source_rgba_sha256": member_source_rgba_sha256,
    }
    expected = {
        "frame_count": spec.expected_frame_count,
        "array_size": spec.expected_array_size,
        "null_slot_count": spec.expected_null_slot_count,
        "combined_names_sha256": spec.expected_combined_names_sha256,
        "output_names_sha256": spec.expected_output_names_sha256,
        "slot_logical_output_sha256": spec.expected_slot_logical_output_sha256,
        "slot_logical_source_rgba_sha256": (
            spec.expected_slot_logical_source_rgba_sha256
        ),
        "member_frame_counts": {
            member.gm_file_name: member.expected_frame_count
            for member in spec.members
        },
        "member_names_sha256": {
            member.gm_file_name: member.expected_names_sha256
            for member in spec.members
        },
        "member_source_rgba_sha256": {
            member.gm_file_name: member.expected_source_rgba_sha256
            for member in spec.members
        },
    }
    if result != expected:
        raise GMAtlasError(
            f"Shared GM atlas proof changed for {spec.host_gm_file_name}: "
            f"actual={result} expected={expected}"
        )
    return result


def derived_frame_proof_digest(rows: Sequence[Mapping[str, Any]]) -> str:
    """Hash loader-ordered, lossless derived-placement evidence exactly."""

    expected_fields = {
        "name",
        "status",
        "left",
        "bottom",
        "main_lost_alpha",
        "mask_lost_alpha",
        "discarded_mask_alpha",
    }
    canonical: list[str] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise GMAtlasError(
                f"Derived proof row {index} must be an object"
            )
        if set(row) != expected_fields:
            raise GMAtlasError(
                f"Derived proof row {index} fields changed: "
                f"actual={sorted(row)} expected={sorted(expected_fields)}"
            )
        name = row.get("name")
        status = row.get("status")
        if not isinstance(name, str) or not name:
            raise GMAtlasError(f"Derived proof row {index} has no frame name")
        if status != "AUTO_LOSSLESS_INTEGRAL":
            raise GMAtlasError(
                f"Derived proof row {index} is not lossless integral: {status!r}"
            )
        values: list[int] = []
        for field in (
            "left",
            "bottom",
            "main_lost_alpha",
            "mask_lost_alpha",
            "discarded_mask_alpha",
        ):
            value = row.get(field)
            if type(value) is not int:
                raise GMAtlasError(
                    f"Derived proof row {index} field {field} must be an integer"
                )
            values.append(value)
        left, bottom, main_lost, mask_lost, discarded = values
        if main_lost != 0 or mask_lost != 0 or discarded < 0:
            raise GMAtlasError(
                f"Derived proof row {index} is lossy or malformed"
            )
        canonical.append(
            f"{name}\t{status}\t{left}\t{bottom}\t{main_lost}\t"
            f"{mask_lost}\t{discarded}\n"
        )
    return hashlib.sha256("".join(canonical).encode("utf-8")).hexdigest()


def visible_blue_pixel_count(image: Image.Image) -> int:
    """Count visible, strongly blue-dominant pixels in an RGBA frame."""

    rgba = image if image.mode == "RGBA" else image.convert("RGBA")
    return sum(
        alpha > 0
        and blue >= 96
        and blue >= red + 48
        and blue >= green + 48
        for red, green, blue, alpha in rgba.get_flattened_data()
    )


def source_remap_proof(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Validate and hash exact-canvas cross-index SH1DE donor evidence."""

    expected_fields = {
        "target_name",
        "source_name",
        "target_path_id",
        "source_path_id",
        "source_texture",
        "target_texture",
        "source_width",
        "source_height",
        "target_width",
        "target_height",
        "source_pivot_x",
        "source_pivot_y",
        "target_pivot_x",
        "target_pivot_y",
        "source_pixels_per_unit",
        "target_pixels_per_unit",
        "source_rgba_sha256",
        "output_rgba_sha256",
        "visible_blue_pixel_count",
    }
    mapping_lines: list[str] = []
    proof_lines: list[str] = []
    source_lines: list[str] = []
    output_lines: list[str] = []
    target_names: set[str] = set()
    source_names: set[str] = set()
    blue_total = 0
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise GMAtlasError(
                f"Source remap proof row {index} must be an object"
            )
        if set(row) != expected_fields:
            raise GMAtlasError(
                f"Source remap proof row {index} fields changed: "
                f"actual={sorted(row)} expected={sorted(expected_fields)}"
            )
        target_name = row.get("target_name")
        source_name = row.get("source_name")
        if (
            not isinstance(target_name, str)
            or not target_name
            or target_name in target_names
            or not isinstance(source_name, str)
            or not source_name
            or source_name in source_names
            or target_name == source_name
        ):
            raise GMAtlasError(
                f"Source remap proof row {index} has invalid names"
            )
        target_names.add(target_name)
        source_names.add(source_name)

        path_ids: list[int] = []
        for field in ("target_path_id", "source_path_id"):
            value = row.get(field)
            if type(value) is not int or value == 0:
                raise GMAtlasError(
                    f"Source remap proof row {index} has invalid {field}"
                )
            path_ids.append(value)
        target_path_id, source_path_id = path_ids

        textures: list[str] = []
        for field in ("source_texture", "target_texture"):
            value = row.get(field)
            if not isinstance(value, str) or not value:
                raise GMAtlasError(
                    f"Source remap proof row {index} has invalid {field}"
                )
            textures.append(value)
        source_texture, target_texture = textures

        dimensions: list[int] = []
        for field in (
            "source_width",
            "source_height",
            "target_width",
            "target_height",
        ):
            value = row.get(field)
            if type(value) is not int or value <= 0:
                raise GMAtlasError(
                    f"Source remap proof row {index} has invalid {field}"
                )
            dimensions.append(value)
        source_width, source_height, target_width, target_height = dimensions

        numeric_fields = (
            "source_pivot_x",
            "source_pivot_y",
            "target_pivot_x",
            "target_pivot_y",
            "source_pixels_per_unit",
            "target_pixels_per_unit",
        )
        numbers: dict[str, float] = {}
        for field in numeric_fields:
            raw_value = row.get(field)
            if isinstance(raw_value, bool):
                raise GMAtlasError(
                    f"Source remap proof row {index} has invalid {field}"
                )
            try:
                value = float(raw_value)
            except (TypeError, ValueError) as exc:
                raise GMAtlasError(
                    f"Source remap proof row {index} has invalid {field}"
                ) from exc
            if not isfinite(value):
                raise GMAtlasError(
                    f"Source remap proof row {index} has non-finite {field}"
                )
            numbers[field] = value

        if (
            (source_width, source_height) != (target_width, target_height)
            or numbers["source_pivot_x"] != numbers["target_pivot_x"]
            or numbers["source_pivot_y"] != numbers["target_pivot_y"]
            or numbers["source_pixels_per_unit"] <= 0
            or numbers["source_pixels_per_unit"]
            != numbers["target_pixels_per_unit"]
        ):
            raise GMAtlasError(
                f"Source remap proof row {index} is not exact-canvas"
            )

        source_rgba = row.get("source_rgba_sha256")
        output_rgba = row.get("output_rgba_sha256")
        for field, digest in (
            ("source_rgba_sha256", source_rgba),
            ("output_rgba_sha256", output_rgba),
        ):
            if not isinstance(digest, str) or re.fullmatch(
                r"[0-9a-f]{64}", digest
            ) is None:
                raise GMAtlasError(
                    f"Source remap proof row {index} has invalid {field}"
                )
        if source_rgba != output_rgba:
            raise GMAtlasError(
                f"Source remap proof row {index} changed source pixels"
            )
        blue_count = row.get("visible_blue_pixel_count")
        if type(blue_count) is not int or blue_count < 0:
            raise GMAtlasError(
                f"Source remap proof row {index} has invalid blue count"
            )
        blue_total += blue_count

        mapping_lines.append(
            f"{target_name}\t{source_name}\t{target_path_id}\t"
            f"{source_path_id}\n"
        )
        source_lines.append(
            f"{target_name}\t{source_name}\t{source_rgba}\n"
        )
        output_lines.append(f"{target_name}\t{output_rgba}\n")
        float_values = [numbers[field].hex() for field in numeric_fields]
        proof_lines.append(
            f"{target_name}\t{source_name}\t{target_path_id}\t"
            f"{source_path_id}\t{source_texture}\t{target_texture}\t"
            f"{source_width}\t{source_height}\t{target_width}\t"
            f"{target_height}\t" + "\t".join(float_values)
            + f"\t{source_rgba}\t{output_rgba}\t{blue_count}\n"
        )

    return {
        "frame_count": len(rows),
        "mapping_sha256": hashlib.sha256(
            "".join(mapping_lines).encode("utf-8")
        ).hexdigest(),
        "proof_sha256": hashlib.sha256(
            "".join(proof_lines).encode("utf-8")
        ).hexdigest(),
        "source_rgba_sha256": hashlib.sha256(
            "".join(source_lines).encode("utf-8")
        ).hexdigest(),
        "output_rgba_sha256": hashlib.sha256(
            "".join(output_lines).encode("utf-8")
        ).hexdigest(),
        "visible_blue_pixel_count": blue_total,
    }


def source_remap_reference_proof(
    rows: Sequence[Mapping[str, Any]], contract: SourceRemapContract,
) -> dict[str, Any]:
    """Compare reference pixels/geometry independently of serialized PathIDs.

    Only current object identifiers are normalized. Donor/target names, pixels,
    texture identity, canvas, pivots and PPU must still match the reviewed proof.
    Callers retain source_remap_proof(rows) as the exact per-build provenance.
    """
    source_remap_proof(rows)  # Validate actual nonzero IDs and complete row shape.
    if len(rows) != len(contract.frames):
        raise GMAtlasError("Source remap reference cohort changed")
    normalized = []
    for row, frame in zip(rows, contract.frames, strict=True):
        if row["target_name"] != frame.target_name or row["source_name"] != frame.source_name:
            raise GMAtlasError("Source remap semantic donor/target changed")
        normalized.append({**row, "target_path_id": frame.target_path_id,
                           "source_path_id": frame.source_path_id})
    return source_remap_proof(normalized)


def native_source_geometry_proof(
    rows: Sequence[Mapping[str, Any]],
    *,
    source_anchor_tolerance_px: float = NATIVE_SOURCE_ANCHOR_TOLERANCE_PX,
) -> dict[str, Any]:
    """Validate and hash a loader-ordered, source-only native frame set.

    The source-authored anchor must agree with Crusader within the explicitly
    reviewed group tolerance. The emitted pivot is separately checked against
    the much tighter global runtime tolerance after the same float32 conversion
    performed by the 1.39 JSON loader. No row may claim Crusader pixels, a
    resized canvas, or a changed PPU.
    """

    if (
        isinstance(source_anchor_tolerance_px, bool)
        or not isinstance(source_anchor_tolerance_px, (int, float))
        or not isfinite(float(source_anchor_tolerance_px))
        or source_anchor_tolerance_px < 0
    ):
        raise GMAtlasError(
            "Native source anchor tolerance must be a finite non-negative number"
        )

    expected_fields = {
        "name",
        "origin",
        "source_width",
        "source_height",
        "target_width",
        "target_height",
        "source_pivot_x",
        "source_pivot_y",
        "target_pivot_x",
        "target_pivot_y",
        "output_pivot_x",
        "output_pivot_y",
        "source_pixels_per_unit",
        "target_pixels_per_unit",
        "output_pixels_per_unit",
        "source_rgba_sha256",
    }
    geometry_lines: list[str] = []
    origin_lines: list[str] = []
    rgba_lines: list[str] = []
    names: set[str] = set()
    maximum_source_anchor_error = 0.0
    maximum_runtime_anchor_error = 0.0
    target_origin_count = 0
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise GMAtlasError(f"Native geometry proof row {index} must be an object")
        if set(row) != expected_fields:
            raise GMAtlasError(
                f"Native geometry proof row {index} fields changed: "
                f"actual={sorted(row)} expected={sorted(expected_fields)}"
            )
        name = row.get("name")
        if not isinstance(name, str) or not name or name in names:
            raise GMAtlasError(
                f"Native geometry proof row {index} has an invalid/duplicate name"
            )
        names.add(name)
        origin = row.get("origin")
        if origin == TARGET_FRAME_ORIGIN:
            target_origin_count += 1
        if origin != SOURCE_FRAME_ORIGIN:
            raise GMAtlasError(
                f"Native geometry proof row {index} is not SH1DE-only: {origin!r}"
            )

        dimensions: list[int] = []
        for field in (
            "source_width",
            "source_height",
            "target_width",
            "target_height",
        ):
            value = row.get(field)
            if type(value) is not int or value <= 0:
                raise GMAtlasError(
                    f"Native geometry proof row {index} has invalid {field}: "
                    f"{value!r}"
                )
            dimensions.append(value)
        source_width, source_height, target_width, target_height = dimensions

        numeric_fields = (
            "source_pivot_x",
            "source_pivot_y",
            "target_pivot_x",
            "target_pivot_y",
            "output_pivot_x",
            "output_pivot_y",
            "source_pixels_per_unit",
            "target_pixels_per_unit",
            "output_pixels_per_unit",
        )
        numbers: dict[str, float] = {}
        for field in numeric_fields:
            raw_value = row.get(field)
            if isinstance(raw_value, bool):
                raise GMAtlasError(
                    f"Native geometry proof row {index} has invalid {field}"
                )
            try:
                value = float(raw_value)
            except (TypeError, ValueError) as exc:
                raise GMAtlasError(
                    f"Native geometry proof row {index} has invalid {field}"
                ) from exc
            if not isfinite(value):
                raise GMAtlasError(
                    f"Native geometry proof row {index} has non-finite {field}"
                )
            numbers[field] = value

        source_ppu = numbers["source_pixels_per_unit"]
        target_ppu = numbers["target_pixels_per_unit"]
        output_ppu = numbers["output_pixels_per_unit"]
        if source_ppu <= 0 or source_ppu != target_ppu or target_ppu != output_ppu:
            raise GMAtlasError(
                f"Native geometry proof row {index} changes PPU: "
                f"source={source_ppu} target={target_ppu} output={output_ppu}"
            )

        source_anchor_x = numbers["source_pivot_x"] * source_width
        source_anchor_y = numbers["source_pivot_y"] * source_height
        target_anchor_x = numbers["target_pivot_x"] * target_width
        target_anchor_y = numbers["target_pivot_y"] * target_height
        source_error = max(
            abs(source_anchor_x - target_anchor_x),
            abs(source_anchor_y - target_anchor_y),
        )
        maximum_source_anchor_error = max(
            maximum_source_anchor_error, source_error
        )
        if source_error > source_anchor_tolerance_px:
            raise GMAtlasError(
                f"Native source anchor differs for {name}: {source_error} px"
            )

        # Welche Kante den Anker traegt, entscheidet der Zielpivot je Achse.
        # Dieselbe Funktion wie in der Erzeugung, damit kein Nachweis gegen
        # eine andere Rechnung geprueft wird als die, die den Wert erzeugt hat.
        expected_anchor_x = native_reanchored_anchor(
            numbers["target_pivot_x"], target_width, source_width
        )
        expected_anchor_y = native_reanchored_anchor(
            numbers["target_pivot_y"], target_height, source_height
        )
        expected_output_x = _float32(expected_anchor_x / source_width)
        expected_output_y = _float32(expected_anchor_y / source_height)
        output_pivot_x = numbers["output_pivot_x"]
        output_pivot_y = numbers["output_pivot_y"]
        if (
            output_pivot_x != expected_output_x
            or output_pivot_y != expected_output_y
        ):
            raise GMAtlasError(
                f"Native output pivot is not the reviewed float32 target anchor "
                f"for {name}"
            )
        runtime_error = max(
            abs(output_pivot_x * source_width - expected_anchor_x),
            abs(output_pivot_y * source_height - expected_anchor_y),
        )
        maximum_runtime_anchor_error = max(
            maximum_runtime_anchor_error, runtime_error
        )
        if runtime_error > NATIVE_SOURCE_ANCHOR_TOLERANCE_PX:
            raise GMAtlasError(
                f"Native runtime anchor differs for {name}: {runtime_error} px"
            )

        rgba_sha256 = row.get("source_rgba_sha256")
        if not isinstance(rgba_sha256, str) or re.fullmatch(
            r"[0-9a-f]{64}", rgba_sha256
        ) is None:
            raise GMAtlasError(
                f"Native geometry proof row {index} has invalid source RGBA digest"
            )
        float_values = [numbers[field].hex() for field in numeric_fields]
        geometry_lines.append(
            f"{name}\t{source_width}\t{source_height}\t{target_width}\t"
            f"{target_height}\t" + "\t".join(float_values) + "\n"
        )
        origin_lines.append(f"{name}\t{origin}\n")
        rgba_lines.append(f"{name}\t{rgba_sha256}\n")

    return {
        "frame_count": len(rows),
        "geometry_proof_sha256": hashlib.sha256(
            "".join(geometry_lines).encode("utf-8")
        ).hexdigest(),
        "origin_proof_sha256": hashlib.sha256(
            "".join(origin_lines).encode("utf-8")
        ).hexdigest(),
        "source_rgba_sha256": hashlib.sha256(
            "".join(rgba_lines).encode("utf-8")
        ).hexdigest(),
        "target_origin_count": target_origin_count,
        "source_anchor_max_error_px": maximum_source_anchor_error,
        "runtime_anchor_max_error_px": maximum_runtime_anchor_error,
    }


def native_source_authored_pivot_proof(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Validate native SH1DE frames that retain authored pivot and PPU.

    The target contributes only the already frozen loader name/slot manifest.
    Each proof row therefore contains no target geometry at all. The metadata
    digest canonicalises loader-ordered source dimensions plus the exact
    float32 values that SHCDE-SE passes to ``Sprite.Create``.
    """

    expected_fields = {
        "name",
        "origin",
        "source_width",
        "source_height",
        "source_pivot_x",
        "source_pivot_y",
        "output_pivot_x",
        "output_pivot_y",
        "source_pixels_per_unit",
        "output_pixels_per_unit",
        "source_rgba_sha256",
    }
    geometry_lines: list[str] = []
    origin_lines: list[str] = []
    rgba_lines: list[str] = []
    names: set[str] = set()
    target_origin_count = 0
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise GMAtlasError(
                f"Native authored proof row {index} must be an object"
            )
        if set(row) != expected_fields:
            raise GMAtlasError(
                f"Native authored proof row {index} fields changed: "
                f"actual={sorted(row)} expected={sorted(expected_fields)}"
            )
        name = row.get("name")
        if not isinstance(name, str) or not name or name in names:
            raise GMAtlasError(
                f"Native authored proof row {index} has an invalid/duplicate name"
            )
        names.add(name)
        origin = row.get("origin")
        if origin == TARGET_FRAME_ORIGIN:
            target_origin_count += 1
        if origin != SOURCE_FRAME_ORIGIN:
            raise GMAtlasError(
                f"Native authored proof row {index} is not SH1DE-only: "
                f"{origin!r}"
            )

        dimensions: list[int] = []
        for field in ("source_width", "source_height"):
            value = row.get(field)
            if type(value) is not int or value <= 0:
                raise GMAtlasError(
                    f"Native authored proof row {index} has invalid {field}: "
                    f"{value!r}"
                )
            dimensions.append(value)
        source_width, source_height = dimensions

        numbers: dict[str, float] = {}
        for field in (
            "source_pivot_x",
            "source_pivot_y",
            "output_pivot_x",
            "output_pivot_y",
            "source_pixels_per_unit",
            "output_pixels_per_unit",
        ):
            raw_value = row.get(field)
            if isinstance(raw_value, bool):
                raise GMAtlasError(
                    f"Native authored proof row {index} has invalid {field}"
                )
            try:
                value = float(raw_value)
            except (TypeError, ValueError) as exc:
                raise GMAtlasError(
                    f"Native authored proof row {index} has invalid {field}"
                ) from exc
            if not isfinite(value):
                raise GMAtlasError(
                    f"Native authored proof row {index} has non-finite {field}"
                )
            numbers[field] = value

        source_pivot_x = _float32(numbers["source_pivot_x"])
        source_pivot_y = _float32(numbers["source_pivot_y"])
        source_ppu = _float32(numbers["source_pixels_per_unit"])
        if source_ppu <= 0:
            raise GMAtlasError(
                f"Native authored proof row {index} has non-positive source PPU"
            )
        if (
            numbers["output_pivot_x"] != source_pivot_x
            or numbers["output_pivot_y"] != source_pivot_y
        ):
            raise GMAtlasError(
                f"Native authored output pivot differs from SH1DE for {name}"
            )
        if numbers["output_pixels_per_unit"] != source_ppu:
            raise GMAtlasError(
                f"Native authored output PPU differs from SH1DE for {name}"
            )

        rgba_sha256 = row.get("source_rgba_sha256")
        if not isinstance(rgba_sha256, str) or re.fullmatch(
            r"[0-9a-f]{64}", rgba_sha256
        ) is None:
            raise GMAtlasError(
                f"Native authored proof row {index} has invalid source RGBA digest"
            )
        geometry_lines.append(
            f"{name}\t{source_width}\t{source_height}\t"
            f"{source_pivot_x.hex()}\t{source_pivot_y.hex()}\t"
            f"{source_ppu.hex()}\n"
        )
        origin_lines.append(f"{name}\t{origin}\n")
        rgba_lines.append(f"{name}\t{rgba_sha256}\n")

    return {
        "frame_count": len(rows),
        "geometry_proof_sha256": hashlib.sha256(
            "".join(geometry_lines).encode("utf-8")
        ).hexdigest(),
        "origin_proof_sha256": hashlib.sha256(
            "".join(origin_lines).encode("utf-8")
        ).hexdigest(),
        "source_rgba_sha256": hashlib.sha256(
            "".join(rgba_lines).encode("utf-8")
        ).hexdigest(),
        "target_origin_count": target_origin_count,
    }


def sparse_keep_frame_proof(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Validate and hash the Crusader slots a sparse group copies unchanged.

    These frames exist because ``ApplySingle`` sizes the GM array from the
    highest index in our atlas.json: leaving a donor-less slot out would not
    preserve its Crusader tile, it would truncate the array and delete every
    tile above the last replaced one.  Each row therefore claims a byte copy of
    one SHCDE sprite - the target canvas, the target pivot and the target PPU,
    with no conversion of any kind.
    """

    expected_fields = {
        "name",
        "origin",
        "proof_status",
        "target_path_id",
        "target_width",
        "target_height",
        "target_pivot_x",
        "target_pivot_y",
        "output_pivot_x",
        "output_pivot_y",
        "target_pixels_per_unit",
        "output_pixels_per_unit",
        "target_rgba_sha256",
    }
    name_lines: list[str] = []
    proof_lines: list[str] = []
    rgba_lines: list[str] = []
    names: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise GMAtlasError(f"Sparse keep proof row {index} must be an object")
        if set(row) != expected_fields:
            raise GMAtlasError(
                f"Sparse keep proof row {index} fields changed: "
                f"actual={sorted(row)} expected={sorted(expected_fields)}"
            )
        name = row.get("name")
        if not isinstance(name, str) or not name or name in names:
            raise GMAtlasError(
                f"Sparse keep proof row {index} has an invalid/duplicate name"
            )
        names.add(name)
        if row.get("origin") != TARGET_FRAME_ORIGIN:
            raise GMAtlasError(
                f"Sparse keep proof row {index} is not Crusader-only: "
                f"{row.get('origin')!r}"
            )
        if row.get("proof_status") != KEEP_CRUSADER_PROOF_STATUS:
            raise GMAtlasError(
                f"Sparse keep proof row {index} has an unexpected status: "
                f"{row.get('proof_status')!r}"
            )
        path_id = row.get("target_path_id")
        if isinstance(path_id, bool) or not isinstance(path_id, int):
            raise GMAtlasError(
                f"Sparse keep proof row {index} has an invalid target PathID"
            )
        dimensions: list[int] = []
        for field in ("target_width", "target_height"):
            value = row.get(field)
            if type(value) is not int or value <= 0:
                raise GMAtlasError(
                    f"Sparse keep proof row {index} has invalid {field}: "
                    f"{value!r}"
                )
            dimensions.append(value)
        width, height = dimensions
        numeric_fields = (
            "target_pivot_x",
            "target_pivot_y",
            "output_pivot_x",
            "output_pivot_y",
            "target_pixels_per_unit",
            "output_pixels_per_unit",
        )
        numbers: dict[str, float] = {}
        for field in numeric_fields:
            raw_value = row.get(field)
            if isinstance(raw_value, bool):
                raise GMAtlasError(
                    f"Sparse keep proof row {index} has invalid {field}"
                )
            try:
                value = float(raw_value)
            except (TypeError, ValueError) as exc:
                raise GMAtlasError(
                    f"Sparse keep proof row {index} has invalid {field}"
                ) from exc
            if not isfinite(value):
                raise GMAtlasError(
                    f"Sparse keep proof row {index} has non-finite {field}"
                )
            numbers[field] = value
        if (
            numbers["output_pivot_x"] != numbers["target_pivot_x"]
            or numbers["output_pivot_y"] != numbers["target_pivot_y"]
        ):
            raise GMAtlasError(
                f"Sparse keep frame re-anchors the Crusader sprite: {name}"
            )
        if (
            numbers["target_pixels_per_unit"] <= 0
            or numbers["output_pixels_per_unit"]
            != numbers["target_pixels_per_unit"]
        ):
            raise GMAtlasError(f"Sparse keep frame changes the Crusader PPU: {name}")
        rgba_sha256 = row.get("target_rgba_sha256")
        if not isinstance(rgba_sha256, str) or re.fullmatch(
            r"[0-9a-f]{64}", rgba_sha256
        ) is None:
            raise GMAtlasError(
                f"Sparse keep proof row {index} has invalid target RGBA digest"
            )
        name_lines.append(f"{name}\n")
        proof_lines.append(
            f"{name}\t{path_id}\t{width}\t{height}\t"
            + "\t".join(numbers[field].hex() for field in numeric_fields)
            + "\n"
        )
        rgba_lines.append(f"{name}\t{rgba_sha256}\n")

    return {
        "frame_count": len(rows),
        "names_sha256": hashlib.sha256(
            "".join(name_lines).encode("utf-8")
        ).hexdigest(),
        "geometry_proof_sha256": hashlib.sha256(
            "".join(proof_lines).encode("utf-8")
        ).hexdigest(),
        "target_rgba_sha256": hashlib.sha256(
            "".join(rgba_lines).encode("utf-8")
        ).hexdigest(),
    }


def review_individual_payload_digest(
    rows: Sequence[Mapping[str, Any]],
) -> str:
    """Bind the ordered individual main/mask PNG payload without listing it.

    Callers supply loader-sorted rows.  The digest covers each logical name,
    both serialized PNG hashes and their common target-canvas geometry.
    """

    canonical: list[str] = []
    for index, row in enumerate(rows):
        name = row.get("name")
        main_sha256 = row.get("main_sha256")
        mask_sha256 = row.get("mask_sha256")
        width = row.get("width")
        height = row.get("height")
        if not isinstance(name, str) or not name:
            raise GMAtlasError(f"Sparse payload row {index} has no frame name")
        if not isinstance(main_sha256, str) or re.fullmatch(
            r"[0-9a-f]{64}", main_sha256
        ) is None:
            raise GMAtlasError(
                f"Sparse payload row {index} has an invalid main digest"
            )
        if not isinstance(mask_sha256, str) or re.fullmatch(
            r"[0-9a-f]{64}", mask_sha256
        ) is None:
            raise GMAtlasError(
                f"Sparse payload row {index} has an invalid mask digest"
            )
        if (
            isinstance(width, bool)
            or not isinstance(width, int)
            or width <= 0
            or isinstance(height, bool)
            or not isinstance(height, int)
            or height <= 0
        ):
            raise GMAtlasError(
                f"Sparse payload row {index} has invalid geometry: "
                f"{width!r}x{height!r}"
            )
        canonical.append(
            f"{name}\t{main_sha256}\t{mask_sha256}\t{width}\t{height}\n"
        )
    return hashlib.sha256("".join(canonical).encode("utf-8")).hexdigest()


AUTHORED_SPRITE_KIND = "authored_sprite_v1"
AUTHORED_SPRITE_CATEGORY = "authored_sprite"
AUTHORED_SPRITE_MASK_CATEGORY = "authored_sprite_team_mask"


def authored_sprite_foot_point(
    width: int,
    height: int,
    target: Mapping[str, Any],
) -> tuple[float, float]:
    """Where a hand-drawn frame of ``width``x``height`` will sit in game.

    Measured at the source, not assumed: SHCDE-SE 1.39
    ``GameSpriteManagerAPI.CreateReplacementSprite`` (lines 113-119 of the
    decompiled ``GameSpriteManagerAPI.cs``) divides the Crusader sprite's pivot
    by the Crusader rect, then hands that *normalised* fraction to
    ``Sprite.Create`` together with a rect spanning the whole new texture.  The
    delivered canvas may therefore be any size, but the foot point is not free:
    it always lands at

        (pivot_x * own width, pivot_y * own height)

    counted from the left and from the BOTTOM, which is Unity's order and the
    opposite of Pillow's row order.  A frame drawn on a different canvas keeps
    its old *relative* anchor and thus moves on the tile - which looks almost
    right and is very hard to trace back.  This function exists so that the
    single rule has one home shared by the builder and ``tools/sprites.py``.
    """

    return (
        float(target["pivot_x"]) * float(width),
        float(target["pivot_y"]) * float(height),
    )


def authored_sprite_names_digest(names: Iterable[str]) -> str:
    """Digest the delivered frame names, plainly sorted.

    Plain sorting rather than loader slot order on purpose: this digest is
    recomputed by ``profile_contract`` from the manifest alone, where the
    group's ``dash_format`` is not available.  One rule, two independent
    recomputations.
    """

    return _names_digest(sorted(names))


def authored_sprite_payload_digest(rows: Sequence[Mapping[str, Any]]) -> str:
    """Bind every delivered pixel and every declared foot point in one value.

    A row carries the logical frame name, the delivered canvas, the foot point
    the loader will use for it, and the SHA-256 of the colour PNG and of the
    mask PNG (``-`` when the group carries no mask).  Repainting a single pixel
    or moving a frame onto another canvas changes the digest, so the profile pin
    fails the build - which is the only protection against a silently displaced
    frame that this transport can have.
    """

    canonical: list[str] = []
    for index, row in enumerate(sorted(rows, key=lambda item: str(item.get("name")))):
        name = row.get("name")
        main_sha256 = row.get("main_sha256")
        mask_sha256 = row.get("mask_sha256")
        width = row.get("width")
        height = row.get("height")
        foot_x = row.get("foot_px_x")
        foot_y = row.get("foot_px_y")
        if not isinstance(name, str) or not name:
            raise GMAtlasError(f"Authored payload row {index} has no frame name")
        if not isinstance(main_sha256, str) or re.fullmatch(
            r"[0-9a-f]{64}", main_sha256
        ) is None:
            raise GMAtlasError(
                f"Authored payload row {index} has an invalid main digest"
            )
        if mask_sha256 != "-" and (
            not isinstance(mask_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", mask_sha256) is None
        ):
            raise GMAtlasError(
                f"Authored payload row {index} has an invalid mask digest"
            )
        if (
            isinstance(width, bool)
            or not isinstance(width, int)
            or width <= 0
            or isinstance(height, bool)
            or not isinstance(height, int)
            or height <= 0
        ):
            raise GMAtlasError(
                f"Authored payload row {index} has invalid geometry: "
                f"{width!r}x{height!r}"
            )
        try:
            foot = f"{float(foot_x):.4f},{float(foot_y):.4f}"
        except (TypeError, ValueError) as exc:
            raise GMAtlasError(
                f"Authored payload row {index} has no numeric foot point"
            ) from exc
        canonical.append(
            f"{name}\t{width}x{height}\t{foot}\t{main_sha256}\t{mask_sha256}\n"
        )
    return hashlib.sha256("".join(canonical).encode("utf-8")).hexdigest()


def validate_complete_group(
    mapping_sprites: Sequence[dict[str, Any]],
    spec: AtlasGroupSpec,
) -> ValidatedGroup:
    labelled = [
        proposal
        for proposal in mapping_sprites
        if str(proposal.get("group", "")) == spec.gm_file_name
    ]
    parseable = [
        proposal
        for proposal in mapping_sprites
        if parse_loader_frame_name(
            str(proposal.get("name", "")), spec.gm_file_name, spec.dash_format
        )
        is not None
    ]
    labelled_names = {str(proposal.get("name", "")) for proposal in labelled}
    parseable_names = {str(proposal.get("name", "")) for proposal in parseable}
    if labelled_names != parseable_names:
        raise GMAtlasError(
            f"Mapping group classification disagrees with loader names for "
            f"{spec.gm_file_name}"
        )
    if not labelled:
        raise GMAtlasError(f"No target frames found for {spec.gm_file_name}")

    # Ausnahmen einzelner Plaetze. Angewendet wird VOR jeder Pruefung, damit
    # der Rest der Funktion die Ausnahme nicht als Sonderfall kennen muss: eine
    # Umlenkung wird ein gewoehnlicher Vorschlag gegen einen anderen Spender,
    # ein Behalten die Form, die ein Frame ohne Spender ohnehin haette.
    overrides = {
        override.target_name: override
        for override in frame_overrides_for_spec(spec)
    }
    if overrides:
        unknown = sorted(set(overrides) - labelled_names)
        if unknown:
            raise GMAtlasError(
                f"Frame overrides for {spec.gm_file_name} name frames the group "
                f"does not have: {unknown}"
            )
        donors = {
            str(candidate.get("name", "")): candidate.get("source")
            for candidate in labelled
        }
        # Gruppenfremde Spender. Bis zum 21.08.2026 suchte die Umlenkung nur
        # in `labelled`, also in der eigenen Gruppe - und genau daran scheiterte
        # der Fall, fuer den die Umlenkung am meisten brauchte: `tree_birch`
        # fuehrt 148 Dattelpalmen, Stronghold 1 liefert dafuer nur 73 Bilder,
        # und fuer 73-147 gibt es in DIESER Gruppe niemanden, der spenden
        # koennte. `Tree_Oak` hat fuer dieselben Indizes europaeische Baeume.
        #
        # Zulaessig ist ein fremder Spender nur aus DERSELBEN Quelltextur:
        # der Atlasbau dekodiert die Quellbilder aus `spec.source_texture`,
        # ein Spender aus einer anderen Textur waere zur Bauzeit gar nicht
        # geladen. Die Pruefung steht deshalb unten an der Fundstelle und
        # nicht hier - so nennt die Fehlermeldung den konkreten Frame.
        fremde_spender = {
            str(candidate.get("name", "")): candidate.get("source")
            for candidate in mapping_sprites
            if str(candidate.get("group", "")) != spec.gm_file_name
            and candidate.get("source") is not None
        }

    validated: list[tuple[FrameSlot, dict[str, Any]]] = []
    names_seen: set[str] = set()
    slots_seen: set[FrameSlot] = set()
    for proposal in labelled:
        name = str(proposal.get("name", ""))
        override = overrides.get(name)
        if override is not None:
            if override.donor_name is None and proposal.get("source") is None:
                # BEHALTEN ohne Spender waere wirkungslos - der Platz behaelt
                # Crusader ohnehin - und hiesse, dass die Messung dahinter
                # veraltet ist.
                #
                # UMLENKEN ohne Spender ist dagegen genau der interessante
                # Fall, und er war hier bis zum 16.08.2026 mitverboten. Ein
                # Platz, den Stronghold 1 gar nicht kennt, ist der einzige, bei
                # dem eine Umlenkung ueberhaupt etwas gewinnt: Sie holt Bild
                # von woanders, statt eine bestehende Zuordnung zu verschieben.
                # Die Moschee in tile_churches ist der Anlass - alle 455
                # Plaetze ab 287 fuehren source = null, und ohne diese
                # Unterscheidung liess sich keiner davon umlenken.
                raise GMAtlasError(
                    f"Frame override for {name} has nothing to override: the "
                    f"frame has no SH1DE donor"
                )
            if override.donor_name is None:
                proposal = keep_crusader(proposal)
            else:
                donor = donors.get(override.donor_name)
                if donor is None:
                    donor = fremde_spender.get(override.donor_name)
                    if donor is not None:
                        spender_textur = str(donor.get("texture_name", ""))
                        if spender_textur != spec.source_texture:
                            raise GMAtlasError(
                                f"Frame override for {name} names the "
                                f"cross-group donor {override.donor_name!r} "
                                f"from texture {spender_textur!r}, but "
                                f"{spec.gm_file_name} decodes from "
                                f"{spec.source_texture!r}"
                            )
                if donor is None:
                    raise GMAtlasError(
                        f"Frame override for {name} names the donor "
                        f"{override.donor_name!r}, which is neither a frame of "
                        f"{spec.gm_file_name} with a source nor a frame of "
                        f"another group with one"
                    )
                proposal = redirect_source(proposal, donor)
        slot = parse_loader_frame_name(name, spec.gm_file_name, spec.dash_format)
        if slot is None:
            raise GMAtlasError(f"Unparseable frame in {spec.gm_file_name}: {name!r}")
        if name in names_seen:
            raise GMAtlasError(f"Duplicate frame name in {spec.gm_file_name}: {name}")
        if slot in slots_seen:
            raise GMAtlasError(
                f"Duplicate {'alt' if slot.is_alt else 'main'} slot "
                f"{slot.index} in {spec.gm_file_name}"
            )
        names_seen.add(name)
        slots_seen.add(slot)

        action = str(proposal.get("action", ""))
        if spec.review_frame_policy is None:
            approved_actions = {"REPLACE_EXACT", "REPLACE_DERIVED"}
            # Same-atlas groups never receive REVIEW_MANUAL - mapping.py only
            # assigns it across atlases - so the review path cannot serve them.
            # A group with partial European coverage declares its keep count
            # instead and ships those frames straight from Crusader.
            if spec.sparse_keep_frame_count is not None:
                approved_actions.add("KEEP_CRUSADER")
        elif spec.review_frame_policy.includes_keep:
            approved_actions = {"REVIEW_MANUAL", "KEEP_CRUSADER"}
        else:
            approved_actions = {"REVIEW_MANUAL"}
        if action not in approved_actions:
            raise GMAtlasError(
                f"Frame {name} is not approved for rendering: {action}"
            )
        source = proposal.get("source")
        target = proposal.get("target")
        if not isinstance(target, dict):
            raise GMAtlasError(f"Frame {name} has no complete target metadata")
        if action == "KEEP_CRUSADER":
            if source is not None:
                raise GMAtlasError(
                    f"Crusader-only frame unexpectedly has source metadata: {name}"
                )
        else:
            if not isinstance(source, dict):
                raise GMAtlasError(f"Frame {name} has no complete source metadata")
            if source.get("texture_name") != spec.source_texture:
                raise GMAtlasError(
                    f"Unexpected source texture for {name}: {source.get('texture_name')}"
                )
        if target.get("texture_name") != spec.target_texture:
            raise GMAtlasError(
                f"Unexpected target texture for {name}: {target.get('texture_name')}"
            )
        _validate_target_metadata(name, target)
        validated.append((slot, proposal))

    validated.sort(key=lambda item: (item[0].index, item[0].is_alt, item[1]["name"]))
    slots = tuple(slot for slot, _ in validated)
    proposals = tuple(proposal for _, proposal in validated)
    names = tuple(str(proposal["name"]) for proposal in proposals)
    digest = _names_digest(names)
    main_count = sum(not slot.is_alt for slot in slots)
    alt_count = len(slots) - main_count
    max_index = max(slot.index for slot in slots)
    actual = (len(slots), main_count, alt_count, max_index, digest)
    expected = (
        spec.expected_frame_count,
        spec.expected_main_count,
        spec.expected_alt_count,
        spec.expected_max_index,
        spec.expected_names_sha256,
    )
    if actual != expected:
        proof_mismatch(
            f"Target frame manifest changed for {spec.gm_file_name}: "
            f"actual={actual}, expected={expected}"
        )
    keep_names = [
        str(proposal["name"])
        for proposal in proposals
        if proposal.get("action") == "KEEP_CRUSADER"
    ]
    expected_keep = (
        spec.sparse_keep_frame_count
        if spec.sparse_keep_frame_count is not None
        else 0
    )
    if spec.review_frame_policy is None and len(keep_names) != expected_keep:
        proof_mismatch(
            f"Crusader-keep partition changed for {spec.gm_file_name}: "
            f"{len(keep_names)} != {expected_keep}"
        )
    if spec.derived_frame_policy is not None:
        derived_names = [
            str(proposal["name"])
            for proposal in proposals
            if proposal.get("action") == "REPLACE_DERIVED"
        ]
        if len(derived_names) != spec.derived_frame_policy.expected_frame_count:
            proof_mismatch(
                f"Derived frame partition changed for {spec.gm_file_name}: "
                f"{len(derived_names)} != "
                f"{spec.derived_frame_policy.expected_frame_count}"
            )
    return ValidatedGroup(
        spec=spec,
        proposals=proposals,
        slots=slots,
        array_size=max_index + 1,
        names_sha256=digest,
    )


def validate_shared_gm_atlas(
    mapping_sprites: Sequence[dict[str, Any]],
    spec: SharedGMAtlasSpec,
) -> ValidatedSharedGMAtlas:
    """Fuse all reviewed logical registrations into one host-slot manifest."""

    host_loader = LOADER_GROUP_TABLE.get(spec.host_gm_file_name)
    if host_loader is None:
        raise GMAtlasError(
            f"Shared GM host disappeared: {spec.host_gm_file_name}"
        )
    topology_array_size = (
        host_loader.declared_image_count + host_loader.additional_storage + 1
    )
    if (
        host_loader.gm_enum != spec.gm_enum
        or host_loader.id_offset != 0
        or host_loader.additional_storage <= 0
        or topology_array_size != spec.expected_array_size
        or host_loader.dash_format is not spec.dash_format
        or host_loader.plain_shader is not True
    ):
        raise GMAtlasError(
            f"Shared GM host topology changed for {spec.host_gm_file_name}"
        )

    plans: list[SharedGMFramePlan] = []
    output_slots: set[FrameSlot] = set()
    logical_names_in_output_order: list[str] = []
    output_names_in_output_order: list[str] = []
    member_counts: dict[str, int] = {}
    member_name_digests: dict[str, str] = {}
    for member in spec.members:
        loader = LOADER_GROUP_TABLE.get(member.gm_file_name)
        if (
            loader is None
            or loader.gm_enum != spec.gm_enum
            or loader.id_offset != member.slot_offset
            or loader.dash_format is not spec.dash_format
            or loader.plain_shader is not True
        ):
            raise GMAtlasError(
                f"Shared GM member topology changed for {member.gm_file_name}"
            )
        labelled = [
            proposal
            for proposal in mapping_sprites
            if str(proposal.get("group", "")) == member.gm_file_name
        ]
        parseable = [
            proposal
            for proposal in mapping_sprites
            if parse_loader_frame_name(
                str(proposal.get("name", "")),
                member.gm_file_name,
                spec.dash_format,
            )
            is not None
        ]
        if {str(item.get("name", "")) for item in labelled} != {
            str(item.get("name", "")) for item in parseable
        }:
            raise GMAtlasError(
                f"Mapping classification changed for shared GM member "
                f"{member.gm_file_name}"
            )
        member_rows: list[tuple[FrameSlot, dict[str, Any]]] = []
        for proposal in labelled:
            logical_name = str(proposal.get("name", ""))
            logical_slot = parse_loader_frame_name(
                logical_name, member.gm_file_name, spec.dash_format
            )
            if logical_slot is None or logical_slot.is_alt:
                raise GMAtlasError(
                    f"Shared GM member frame is unparseable: {logical_name!r}"
                )
            if proposal.get("action") not in {
                "REPLACE_EXACT",
                "REPLACE_DERIVED",
            }:
                raise GMAtlasError(
                    f"Shared GM frame is not source-approved: {logical_name}"
                )
            source = proposal.get("source")
            target = proposal.get("target")
            if not isinstance(source, dict) or not isinstance(target, dict):
                raise GMAtlasError(
                    f"Shared GM frame lacks source/target metadata: {logical_name}"
                )
            if source.get("texture_name") != spec.source_texture:
                raise GMAtlasError(
                    f"Shared GM source texture changed for {logical_name}"
                )
            if target.get("texture_name") != spec.target_texture:
                raise GMAtlasError(
                    f"Shared GM target texture changed for {logical_name}"
                )
            _validate_target_metadata(logical_name, target)
            member_rows.append((logical_slot, proposal))
        member_rows.sort(
            key=lambda item: (item[0].index, item[1]["name"])
        )
        member_names = [str(proposal["name"]) for _, proposal in member_rows]
        member_counts[member.gm_file_name] = len(member_rows)
        member_name_digests[member.gm_file_name] = _names_digest(member_names)
        for logical_slot, proposal in member_rows:
            output_slot = FrameSlot(
                index=logical_slot.index + member.slot_offset,
                is_alt=False,
            )
            if output_slot in output_slots:
                raise GMAtlasError(
                    f"Shared GM output slot collision: {output_slot.index}"
                )
            output_slots.add(output_slot)
            separator = "-" if spec.dash_format else " "
            output_name = (
                f"{spec.host_gm_file_name}{separator}{output_slot.index:03d}"
            )
            logical_name = str(proposal["name"])
            if (
                member.gm_file_name == spec.host_gm_file_name
                and output_name != logical_name
            ):
                raise GMAtlasError(
                    f"Shared GM host name is not canonical: {logical_name!r}"
                )
            plans.append(
                SharedGMFramePlan(
                    member_gm_file_name=member.gm_file_name,
                    logical_name=logical_name,
                    output_name=output_name,
                    output_slot=output_slot,
                    proposal=proposal,
                )
            )

    plans.sort(
        key=lambda item: (
            item.output_slot.index,
            item.output_slot.is_alt,
            item.output_name,
        )
    )
    logical_names_in_output_order.extend(plan.logical_name for plan in plans)
    output_names_in_output_order.extend(plan.output_name for plan in plans)
    slot_logical_output_digest = hashlib.sha256(
        "".join(
            f"{plan.output_slot.index}\t{plan.logical_name}\t{plan.output_name}\n"
            for plan in plans
        ).encode("utf-8")
    ).hexdigest()
    actual = (
        len(plans),
        max((plan.output_slot.index for plan in plans), default=-1),
        spec.expected_array_size - len(plans),
        _names_digest(logical_names_in_output_order),
        _names_digest(output_names_in_output_order),
        slot_logical_output_digest,
        member_counts,
        member_name_digests,
    )
    expected = (
        spec.expected_frame_count,
        spec.expected_max_index,
        spec.expected_null_slot_count,
        spec.expected_combined_names_sha256,
        spec.expected_output_names_sha256,
        spec.expected_slot_logical_output_sha256,
        {
            member.gm_file_name: member.expected_frame_count
            for member in spec.members
        },
        {
            member.gm_file_name: member.expected_names_sha256
            for member in spec.members
        },
    )
    if actual != expected:
        raise GMAtlasError(
            f"Shared GM mapping manifest changed for {spec.host_gm_file_name}: "
            f"actual={actual} expected={expected}"
        )
    return ValidatedSharedGMAtlas(spec=spec, frames=tuple(plans))


def validate_review_frame_partition(
    validated: ValidatedGroup,
    frame_origins: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """Freeze the pixel origin of every review frame in loader-slot order."""

    policy = validated.spec.review_frame_policy
    if policy is None:
        raise GMAtlasError(
            f"{validated.spec.gm_file_name} has no review_frame_policy"
        )
    expected_names = [str(item["name"]) for item in validated.proposals]
    actual_names = [str(item.get("name", "")) for item in frame_origins]
    if actual_names != expected_names:
        raise GMAtlasError(
            f"Review provenance order changed for {validated.spec.gm_file_name}"
        )

    if policy.includes_keep:
        expected_actions = [str(item.get("action", "")) for item in validated.proposals]
        actual_actions = [str(item.get("action", "")) for item in frame_origins]
        if actual_actions != expected_actions:
            raise GMAtlasError(
                f"Review action provenance changed for {validated.spec.gm_file_name}"
            )
        allowed_relations = (
            {
                (
                    "REVIEW_MANUAL",
                    SOURCE_FRAME_ORIGIN,
                    NATIVE_SOURCE_PROOF_STATUS,
                ),
                (
                    "KEEP_CRUSADER",
                    TARGET_FRAME_ORIGIN,
                    KEEP_CRUSADER_PROOF_STATUS,
                ),
            }
            if policy.renders_native_source
            else {
                ("REVIEW_MANUAL", SOURCE_FRAME_ORIGIN, "AUTO_LOSSLESS_INTEGRAL"),
                ("REVIEW_MANUAL", TARGET_FRAME_ORIGIN, "BLOCKED_ALPHA_CLIP"),
                (
                    "KEEP_CRUSADER",
                    TARGET_FRAME_ORIGIN,
                    KEEP_CRUSADER_PROOF_STATUS,
                ),
            }
        )
        for item in frame_origins:
            relation = (
                str(item.get("action", "")),
                str(item.get("origin", "")),
                str(item.get("proof_status", "")),
            )
            if relation not in allowed_relations:
                raise GMAtlasError(
                    f"Invalid review v2 provenance for {item.get('name')}: "
                    f"action={relation[0]!r} origin={relation[1]!r} "
                    f"proof_status={relation[2]!r}"
                )
    else:
        allowed = {
            SOURCE_FRAME_ORIGIN: "AUTO_LOSSLESS_INTEGRAL",
            TARGET_FRAME_ORIGIN: "BLOCKED_ALPHA_CLIP",
        }
        for item in frame_origins:
            origin = str(item.get("origin", ""))
            proof_status = str(item.get("proof_status", ""))
            if origin not in allowed or proof_status != allowed[origin]:
                raise GMAtlasError(
                    f"Invalid review provenance for {item.get('name')}: "
                    f"origin={origin!r} proof_status={proof_status!r}"
                )

    source_names = [
        name
        for name, item in zip(actual_names, frame_origins, strict=True)
        if item["origin"] == SOURCE_FRAME_ORIGIN
    ]
    target_names = [
        name
        for name, item in zip(actual_names, frame_origins, strict=True)
        if item["origin"] == TARGET_FRAME_ORIGIN
    ]
    provenance_digest = hashlib.sha256(
        "".join(
            f"{name}\t{item['origin']}\n"
            for name, item in zip(actual_names, frame_origins, strict=True)
        ).encode("utf-8")
    ).hexdigest()
    actual = (
        len(source_names),
        len(target_names),
        _names_digest(source_names),
        _names_digest(target_names),
        provenance_digest,
    )
    expected = (
        policy.expected_source_frame_count,
        policy.expected_target_frame_count,
        policy.expected_source_names_sha256,
        policy.expected_target_names_sha256,
        policy.expected_provenance_sha256,
    )
    if actual != expected:
        proof_mismatch(
            f"Review frame partition changed for {validated.spec.gm_file_name}: "
            f"actual={actual}, expected={expected}"
        )
    metadata = {
        "mode": policy.mode,
        "proof_algorithm": policy.proof_algorithm,
        "source_frame_count": len(source_names),
        "target_frame_count": len(target_names),
        "source_names_sha256": actual[2],
        "target_names_sha256": actual[3],
        "provenance_sha256": provenance_digest,
        "target_passthrough_exact": True,
        "frame_origins": [dict(item) for item in frame_origins],
    }
    if policy.includes_keep:
        keep_names = [
            name
            for name, item in zip(actual_names, frame_origins, strict=True)
            if item["action"] == "KEEP_CRUSADER"
        ]
        blocked_review_names = [
            name
            for name, item in zip(actual_names, frame_origins, strict=True)
            if item["action"] == "REVIEW_MANUAL"
            and item["origin"] == TARGET_FRAME_ORIGIN
        ]
        fractional_names = [
            name
            for name, item in zip(actual_names, frame_origins, strict=True)
            if item["proof_status"] == "REVIEW_LOSSLESS_FRACTIONAL"
        ]
        if policy.renders_native_source and target_names != keep_names:
            # Unter V3 ist das strukturell wahr: nur KEEP_CRUSADER kann noch
            # eine Crusader-Herkunft tragen. Faellt es auseinander, hat ein
            # REVIEW_MANUAL-Frame doch auf die Zielleinwand zurueckgegriffen.
            raise GMAtlasError(
                f"Review v3 target frames are not exactly the keep frames for "
                f"{validated.spec.gm_file_name}: "
                f"target={len(target_names)} keep={len(keep_names)}"
            )
        action_origin_status_digest = hashlib.sha256(
            "".join(
                f"{name}\t{item['action']}\t{item['origin']}\t"
                f"{item['proof_status']}\n"
                for name, item in zip(actual_names, frame_origins, strict=True)
            ).encode("utf-8")
        ).hexdigest()
        v2_actual = (
            len(keep_names),
            _names_digest(keep_names),
            len(blocked_review_names),
            _names_digest(blocked_review_names),
            len(fractional_names),
            _names_digest(fractional_names),
            action_origin_status_digest,
        )
        v2_expected = (
            policy.expected_keep_frame_count,
            policy.expected_keep_names_sha256,
            policy.expected_blocked_review_frame_count,
            policy.expected_blocked_review_names_sha256,
            policy.expected_fractional_frame_count,
            policy.expected_fractional_names_sha256,
            policy.expected_action_origin_status_sha256,
        )
        if v2_actual != v2_expected:
            proof_mismatch(
                f"Review v2 action partition changed for "
                f"{validated.spec.gm_file_name}: "
                f"actual={v2_actual}, expected={v2_expected}"
            )
        metadata.update(
            {
                "keep_frame_count": len(keep_names),
                "keep_names_sha256": v2_actual[1],
                "blocked_review_frame_count": len(blocked_review_names),
                "blocked_review_names_sha256": v2_actual[3],
                "fractional_frame_count": len(fractional_names),
                "fractional_names_sha256": v2_actual[5],
                "action_origin_status_sha256": action_origin_status_digest,
                "action_counts": {
                    action: sum(item["action"] == action for item in frame_origins)
                    for action in ("REVIEW_MANUAL", "KEEP_CRUSADER")
                },
            }
        )
    return metadata


def describe_group_manifest(
    mapping_sprites: Sequence[dict[str, Any]],
    gm_file_name: str,
) -> dict[str, Any]:
    """Measure the frozen manifest a profile entry for this group would need.

    Freezing counts and a name digest by hand is the project's main source of
    toil and its easiest place to introduce a silent array truncation. This
    reports exactly what ``validate_complete_group`` will later demand, plus the
    facts a reviewer needs to decide whether the group may be produced at all:
    the loader registration, the source/target textures and the action mix.

    It deliberately performs no gate of its own. A group reported here is a
    candidate, never an approval.
    """

    loader_group = LOADER_GROUP_TABLE.get(gm_file_name)
    if loader_group is None:
        raise GMAtlasError(
            f"{gm_file_name!r} is not a registered loader group in the pinned build"
        )
    frames = [
        proposal
        for proposal in mapping_sprites
        if parse_loader_frame_name(
            str(proposal.get("name", "")), gm_file_name, loader_group.dash_format
        )
        is not None
    ]
    if not frames:
        raise GMAtlasError(f"No target frames found for {gm_file_name}")

    slotted = []
    for proposal in frames:
        slot = parse_loader_frame_name(
            str(proposal["name"]), gm_file_name, loader_group.dash_format
        )
        assert slot is not None
        slotted.append((slot, proposal))
    slotted.sort(key=lambda item: (item[0].index, item[0].is_alt, item[1]["name"]))

    slots = [slot for slot, _ in slotted]
    names = tuple(str(proposal["name"]) for _, proposal in slotted)
    main_count = sum(not slot.is_alt for slot in slots)
    max_index = max(slot.index for slot in slots)
    actions = Counter(str(proposal.get("action", "")) for _, proposal in slotted)
    source_textures = sorted(
        {
            str(proposal["source"]["texture_name"])
            for _, proposal in slotted
            if isinstance(proposal.get("source"), dict)
        }
    )
    target_textures = sorted(
        {
            str(proposal["target"]["texture_name"])
            for _, proposal in slotted
            if isinstance(proposal.get("target"), dict)
        }
    )
    return {
        "gm_file_name": gm_file_name,
        "gm_enum": loader_group.gm_enum,
        "dash_format": loader_group.dash_format,
        "mask_policy": "forbidden" if loader_group.plain_shader else "required",
        "owns_its_gm_arrays": loader_group.owns_its_gm_arrays,
        "custom_palette": loader_group.custom_palette,
        "declared_image_count": loader_group.declared_image_count,
        "expected_frame_count": len(slots),
        "expected_main_count": main_count,
        "expected_alt_count": len(slots) - main_count,
        "expected_max_index": max_index,
        "expected_names_sha256": _names_digest(names),
        "loader_array_size": max_index + 1,
        "action_counts": dict(sorted(actions.items())),
        "source_textures": source_textures,
        "target_textures": target_textures,
    }


def _validate_target_metadata(name: str, target: dict[str, Any]) -> None:
    for field in ("width", "height"):
        value = float(target.get(field, 0))
        if not isfinite(value) or value <= 0 or abs(value - round(value)) > 1e-3:
            raise GMAtlasError(f"Invalid target {field} for {name}: {value}")
    for field in ("pivot_x", "pivot_y"):
        value = float(target.get(field, float("nan")))
        if not isfinite(value):
            raise GMAtlasError(f"Invalid target {field} for {name}: {value}")
    ppu = float(target.get("pixels_per_unit", 0))
    if not isfinite(ppu) or ppu <= 0:
        raise GMAtlasError(f"Invalid target pixels_per_unit for {name}: {ppu}")


def _validate_frame(frame: AtlasFrame, spec: AtlasGroupSpec) -> None:
    parsed = parse_loader_frame_name(frame.name, spec.gm_file_name, spec.dash_format)
    if parsed != frame.slot:
        raise GMAtlasError(f"Frame slot/name mismatch for {frame.name}")
    if frame.image.mode != "RGBA":
        raise GMAtlasError(f"Frame must be RGBA: {frame.name} ({frame.image.mode})")
    if frame.image.width <= 0 or frame.image.height <= 0:
        raise GMAtlasError(f"Frame has invalid dimensions: {frame.name}")
    if not isfinite(frame.pivot_x) or not isfinite(frame.pivot_y):
        raise GMAtlasError(f"Frame has non-finite pivot: {frame.name}")
    if not isfinite(frame.pixels_per_unit) or frame.pixels_per_unit <= 0:
        raise GMAtlasError(f"Frame has invalid PPU: {frame.name}")
    if spec.require_mask:
        if frame.mask is None:
            raise GMAtlasError(f"Required team mask is missing: {frame.name}")
        if frame.mask.mode != "RGBA" or frame.mask.size != frame.image.size:
            raise GMAtlasError(
                f"Team mask geometry/mode differs for {frame.name}: "
                f"image={frame.image.mode}/{frame.image.size}, "
                f"mask={frame.mask.mode}/{frame.mask.size}"
            )
    elif frame.mask is not None:
        raise GMAtlasError(f"Unexpected team mask for plain GM group: {frame.name}")


def _shelf_layout(
    frames: Sequence[AtlasFrame],
    atlas_width: int,
    padding: int,
) -> tuple[list[FramePlacement], int] | None:
    ordered = sorted(
        frames,
        key=lambda frame: (
            -(frame.image.height + padding * 2),
            -(frame.image.width + padding * 2),
            frame.slot.index,
            frame.slot.is_alt,
            frame.name,
        ),
    )
    placements: list[FramePlacement] = []
    cursor_x = 0
    cursor_y = 0
    row_height = 0
    for frame in ordered:
        box_width = frame.image.width + padding * 2
        box_height = frame.image.height + padding * 2
        if box_width > atlas_width:
            return None
        if cursor_x and cursor_x + box_width > atlas_width:
            cursor_y += row_height
            cursor_x = 0
            row_height = 0
        placements.append(
            FramePlacement(
                name=frame.name,
                slot=frame.slot,
                x=cursor_x + padding,
                y_from_top=cursor_y + padding,
                width=frame.image.width,
                height=frame.image.height,
                pivot_x=frame.pivot_x,
                pivot_y=frame.pivot_y,
                pixels_per_unit=frame.pixels_per_unit,
            )
        )
        cursor_x += box_width
        row_height = max(row_height, box_height)
    return placements, cursor_y + row_height


def _choose_layout(
    frames: Sequence[AtlasFrame],
    padding: int,
    max_dimension: int,
) -> tuple[int, int, tuple[FramePlacement, ...]]:
    minimum_width = max(frame.image.width + padding * 2 for frame in frames)
    candidate = max(256, _next_power_of_two(minimum_width))
    candidates: list[tuple[tuple[int, int, int, int], int, int, list[FramePlacement]]] = []
    while candidate <= max_dimension:
        result = _shelf_layout(frames, candidate, padding)
        if result is not None:
            placements, used_height = result
            atlas_height = max(256, _next_power_of_two(used_height))
            if atlas_height <= max_dimension:
                score = (
                    candidate * atlas_height,
                    max(candidate, atlas_height),
                    abs(candidate - atlas_height),
                    candidate,
                )
                candidates.append((score, candidate, atlas_height, placements))
        candidate *= 2
    if not candidates:
        raise GMAtlasError(
            f"Frames do not fit a {max_dimension}x{max_dimension} atlas"
        )
    _, width, height, selected = min(candidates, key=lambda item: item[0])
    return width, height, tuple(selected)


def _pixel_key(frame: AtlasFrame) -> tuple[int, int, bytes, bytes | None]:
    main_digest = hashlib.sha256(frame.image.tobytes()).digest()
    mask_digest = (
        hashlib.sha256(frame.mask.tobytes()).digest()
        if frame.mask is not None
        else None
    )
    return (frame.image.width, frame.image.height, main_digest, mask_digest)


def _deduplicate_frames(
    frames: Sequence[AtlasFrame],
) -> tuple[list[AtlasFrame], dict[str, str]]:
    """Return canonical pixel regions and the canonical name for every frame.

    Stronghold intentionally has many logical frame names that point at the
    same atlas rectangle.  Packing every logical name separately can exceed
    Unity's 8192px texture ceiling, while the 1.39 loader explicitly permits
    multiple JSON entries to use one Rect.  Dimensions, main RGBA bytes and
    (when present) mask RGBA bytes all participate in the identity.
    """

    canonical_by_key: dict[tuple[int, int, bytes, bytes | None], AtlasFrame] = {}
    canonical_name: dict[str, str] = {}
    unique: list[AtlasFrame] = []
    for frame in frames:
        key = _pixel_key(frame)
        canonical = canonical_by_key.get(key)
        if canonical is None:
            canonical_by_key[key] = frame
            canonical = frame
            unique.append(frame)
        else:
            # SHA-256 is used as the compact dictionary key.  Confirm byte
            # equality before sharing a Rect so a collision can never change
            # game pixels silently.
            same_main = canonical.image.tobytes() == frame.image.tobytes()
            same_mask = (
                canonical.mask is None
                and frame.mask is None
                or canonical.mask is not None
                and frame.mask is not None
                and canonical.mask.tobytes() == frame.mask.tobytes()
            )
            if not same_main or not same_mask:
                raise GMAtlasError(f"Pixel digest collision for {frame.name}")
        canonical_name[frame.name] = canonical.name
    return unique, canonical_name


def build_atlas(
    validated: ValidatedGroup,
    frames: Sequence[AtlasFrame],
) -> BuiltAtlas:
    spec = validated.spec
    by_name: dict[str, AtlasFrame] = {}
    slots: set[FrameSlot] = set()
    for frame in frames:
        _validate_frame(frame, spec)
        if frame.name in by_name:
            raise GMAtlasError(f"Duplicate rendered frame: {frame.name}")
        if frame.slot in slots:
            raise GMAtlasError(f"Duplicate rendered slot: {frame.slot}")
        by_name[frame.name] = frame
        slots.add(frame.slot)

    expected_names = {str(proposal["name"]) for proposal in validated.proposals}
    if set(by_name) != expected_names:
        missing = sorted(expected_names - set(by_name))
        extra = sorted(set(by_name) - expected_names)
        raise GMAtlasError(
            f"Rendered frame set is incomplete for {spec.gm_file_name}: "
            f"missing={missing[:10]}, extra={extra[:10]}"
        )

    ordered_frames = [by_name[str(proposal["name"])] for proposal in validated.proposals]
    unique_frames, canonical_name = _deduplicate_frames(ordered_frames)
    width, height, placements = _choose_layout(
        unique_frames, spec.padding, spec.max_dimension
    )
    atlas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    mask = Image.new("RGBA", (width, height), (0, 0, 0, 0)) if spec.require_mask else None
    canonical_placement = {placement.name: placement for placement in placements}
    for frame in unique_frames:
        placement = canonical_placement[frame.name]
        # A target-passthrough frame may contain meaningful RGB bytes beneath
        # zero alpha. Alpha compositing normalizes those hidden bytes against
        # the transparent atlas background and breaks byte-exact roundtrips.
        # A raw RGBA paste preserves all four channels while the shelf layout
        # already guarantees that logical regions never overlap.
        atlas.paste(frame.image, (placement.x, placement.y_from_top))
        if mask is not None:
            assert frame.mask is not None
            mask.paste(frame.mask, (placement.x, placement.y_from_top))

    logical_placements: list[FramePlacement] = []
    for frame in ordered_frames:
        canonical = canonical_placement[canonical_name[frame.name]]
        logical_placements.append(
            FramePlacement(
                name=frame.name,
                slot=frame.slot,
                x=canonical.x,
                y_from_top=canonical.y_from_top,
                width=frame.image.width,
                height=frame.image.height,
                pivot_x=frame.pivot_x,
                pivot_y=frame.pivot_y,
                pixels_per_unit=frame.pixels_per_unit,
            )
        )
    json_placements = tuple(
        sorted(
            logical_placements,
            key=lambda item: (item.slot.index, item.slot.is_alt, item.name),
        )
    )
    ppu_values = {placement.pixels_per_unit for placement in json_placements}
    default_ppu = next(iter(ppu_values)) if len(ppu_values) == 1 else 64.0
    atlas_json = {
        "pixelsPerUnit": default_ppu,
        "frames": [placement.json_frame(height) for placement in json_placements],
    }
    validate_built_atlas(
        atlas,
        mask,
        atlas_json,
        spec,
        validated.array_size,
        validated.names_sha256,
    )
    return BuiltAtlas(
        spec=spec,
        image=atlas,
        mask=mask,
        placements=json_placements,
        atlas_json=atlas_json,
        array_size=validated.array_size,
        names_sha256=validated.names_sha256,
        unique_region_count=len(unique_frames),
    )


def validate_built_atlas(
    atlas: Image.Image,
    mask: Image.Image | None,
    atlas_json: dict[str, Any],
    spec: AtlasGroupSpec,
    expected_array_size: int,
    expected_names_sha256: str,
) -> None:
    if atlas.mode != "RGBA":
        raise GMAtlasError(f"Atlas is not RGBA: {atlas.mode}")
    if not _is_power_of_two(atlas.width) or not _is_power_of_two(atlas.height):
        raise GMAtlasError(f"Atlas dimensions are not powers of two: {atlas.size}")
    if atlas.width > spec.max_dimension or atlas.height > spec.max_dimension:
        raise GMAtlasError(f"Atlas exceeds configured maximum: {atlas.size}")
    if spec.require_mask:
        if mask is None or mask.mode != "RGBA" or mask.size != atlas.size:
            raise GMAtlasError("Atlas team mask is missing or has different geometry")
    elif mask is not None:
        raise GMAtlasError("Plain atlas unexpectedly has a team mask")

    raw_frames = atlas_json.get("frames")
    if not isinstance(raw_frames, list) or not raw_frames:
        raise GMAtlasError("atlas.json has no frames")
    names: list[str] = []
    slots: set[FrameSlot] = set()
    occupied: list[tuple[int, int, int, int, str]] = []
    max_index = -1
    for raw in raw_frames:
        name = str(raw.get("name", ""))
        slot = parse_loader_frame_name(name, spec.gm_file_name, spec.dash_format)
        if slot is None:
            raise GMAtlasError(f"atlas.json contains an unparseable frame: {name!r}")
        if slot in slots:
            raise GMAtlasError(f"atlas.json contains duplicate loader slot: {slot}")
        slots.add(slot)
        names.append(name)
        max_index = max(max_index, slot.index)
        rect = raw.get("rect") or {}
        values = [rect.get(field) for field in ("x", "y", "w", "h")]
        if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
            raise GMAtlasError(f"atlas.json rect is not integral for {name}")
        x, y, width, height = values
        if width <= 0 or height <= 0 or x < 0 or y < 0:
            raise GMAtlasError(f"atlas.json rect is invalid for {name}: {rect}")
        if x + width > atlas.width or y + height > atlas.height:
            raise GMAtlasError(f"atlas.json rect escapes atlas for {name}: {rect}")
        occupied.append((x, y, x + width, y + height, name))
        pivot = raw.get("pivot") or {}
        for field in ("x", "y"):
            value = float(pivot.get(field, float("nan")))
            if not isfinite(value):
                raise GMAtlasError(f"atlas.json pivot is invalid for {name}")
        ppu = float(raw.get("pixelsPerUnit", atlas_json.get("pixelsPerUnit", 0)))
        if not isfinite(ppu) or ppu <= 0:
            raise GMAtlasError(f"atlas.json PPU is invalid for {name}")

    if len(names) != spec.expected_frame_count:
        raise GMAtlasError(
            f"atlas.json frame count changed: {len(names)} != {spec.expected_frame_count}"
        )
    if _names_digest(names) != expected_names_sha256:
        raise GMAtlasError("atlas.json ordered frame-name digest changed")
    if max_index + 1 != expected_array_size:
        raise GMAtlasError(
            f"SHCDE-SE array size changed: {max_index + 1} != {expected_array_size}"
        )
    for index, left in enumerate(occupied):
        for right in occupied[index + 1 :]:
            same_rect = left[:4] == right[:4]
            overlap = not (
                left[2] <= right[0]
                or right[2] <= left[0]
                or left[3] <= right[1]
                or right[3] <= left[1]
            )
            if overlap and not same_rect:
                raise GMAtlasError(f"Atlas frames overlap: {left[4]} and {right[4]}")


def write_atlas_json(atlas_json: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(atlas_json, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

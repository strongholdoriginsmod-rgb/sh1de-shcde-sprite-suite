"""Functional sprite-index and light conversions observed in installed runtime.

No game images or executable code are embedded. The versioned GM table stores
interoperability IDs; nontrivial sea remaps match SpriteMapping's input/output
rules and are tested at interval boundaries.
"""
from dataclasses import dataclass
from .native_runtime import load_contract


@dataclass(frozen=True)
class RuntimeSprite:
    group: str
    frame: int
    light: int = 0
    float_colour: int = 0


def sea_light(level: int) -> int:
    return 50 if level <= 2 else level + 48


def remap_tile_frame(file_id: int, frame: int, light: int = 0):
    """Runtime tile function resets light before applying per-file transforms."""
    output_light = 0
    if file_id == 38:
        return None  # no-game-tile/debug only, never an invented grass tile
    if file_id == 5:
        if 1 <= frame < 64:
            base = 1 if frame <= 32 else 5
            n = frame-base
            frame, output_light = n % 4 + base, sea_light(n // 4)
        elif frame < 150:
            if 65 <= frame <= 104:
                n = frame-65
                frame, output_light = 9+n//8, sea_light(n%8)
            else:
                frame = 1
        elif 205 <= frame <= 332:
            base = 205 + ((frame-205)//32)*32
            n = frame-base
            frame, output_light = base+n%4, sea_light(n//4)
        elif 333 <= frame <= 340:
            frame, output_light = 333, sea_light(frame-333)
        elif 533 <= frame <= 660:
            base = 533 + ((frame-533)//32)*32
            n = frame-base
            frame, output_light = base+n%4, sea_light(n//4)
        elif 661 <= frame <= 668:
            frame, output_light = 661, sea_light(frame-661)
        elif 669 <= frame <= 732:
            n = frame-669
            frame, output_light = 669+n%8, sea_light(n//8)
        elif 733 <= frame <= 764:
            n = frame-733
            frame, output_light = 733+n%4, sea_light(n//4)
        elif frame >= 1805:
            n = frame-1805
            frame, output_light = 1805+n%60, sea_light(n//60)
    elif file_id == 6:
        if frame in (3,4): frame=1
        elif frame in (7,8): frame=5
        if 24 <= frame <= 197 or 297 <= frame <= 305:
            output_light=max(0,light-2)+10
    elif file_id in (15,55):
        if 5 <= frame <= 8: output_light=max(0,light-2)+10
    elif file_id == 166:
        if 1 <= frame < 1477:
            n=frame-1
            frame,output_light=n%246+1,n//246
        elif 2168 <= frame < 7064:
            n=frame-2168
            frame,output_light=n%816+2168,n//816
    return int(frame), int(output_light)


def light_multiplier(code: int) -> float:
    if 1 <= code <= 7:
        return 1.0-code*0.1
    if 11 <= code <= 17:
        return 1.0-(code-10)*0.06
    return {50:1.0,51:0.95,52:0.9,53:0.85,54:0.8,55:0.85}.get(code,1.0)


# Exact Unity TilemapManager tint constants from the SHA-256-locked
# Assembly-CSharp.dll. This does not model unverified foliage/wind shaders.
TILE_FLOAT_COLOURS = {
    55:(83/85,0.3019608,0.003921569),  # red
    56:(0.23137255,0.64705884,1/15),  # green
    57:(29/85,28/85,0.8784314),       # blue
    58:(0.8980392,0.85490197,0.49803922), # tan
    59:(0.5019608,)*3,                # grey
    60:(56/85,23/85,2/15),           # brown
    61:(0.2509804,)*3,                # black
    62:(0.5019608,)*3,                # grey
    63:(0.8235294,0.8235294,1.0),    # faint blue
}


def tile_tint_components(light: int=0, float_colour: int=0):
    """Reproduce gameTile.setTileColour's precedence and component colours.

    A nonzero floatColour ignores shadow values (even if it isn't a known
    active tint). Otherwise shading follows exact 0..7, 11..17 and 50..55
    palettes from the installed engine's tilemap manager.
    """
    if float_colour != 0:
        return TILE_FLOAT_COLOURS.get(float_colour,(1.0,1.0,1.0))
    shadow=light_multiplier(light)
    return (shadow,shadow,shadow)


class RuntimeSpriteResolver:
    def __init__(self, contract=None):
        self.contract = contract or load_contract()

    def resolve(self, file_id: int, frame: int, *, tile=True, light=0, float_colour=0):
        if file_id <= 0 or frame < 0:
            return None
        if tile:
            mapped=remap_tile_frame(file_id,frame,light)
            if mapped is None:return None
            frame,light=mapped
        else:
            light=0
            rules = self.contract.get("body_frame_rules", {})
            if file_id in rules.get("one_based_gm_ids", []):
                frame -= 1
            elif file_id == 85:
                if frame <= 101:
                    frame -= 1
                else:
                    file_id, frame = 218, frame - 203
            elif file_id == 167:
                frame = (29 if frame >= 145 else frame) - 1
            elif file_id == 223:
                frame = (29 if frame >= 209 else frame) - 1
            elif file_id not in rules.get("direct_gm_ids", []):
                return None
            if frame < 0:
                return None
        sources=self.contract['gm_files'].get(str(file_id),[])
        for source in sources:  # highest runtime offset first (sea-shore split)
            offset=source['first_runtime_frame']
            if frame >= offset:
                return RuntimeSprite(
                    source['group'],frame-offset,light,
                    float_colour if tile else 0,
                )
        return None

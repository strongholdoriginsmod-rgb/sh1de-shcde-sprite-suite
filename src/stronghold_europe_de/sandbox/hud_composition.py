"""Measured, clip-aware reconstruction of the *build-menu layer* of HUD_Main.

All offsets are from the SHA256-pinned local XAML file's settled Swish1
state. The parent HUD (economy, selection panels, dynamic game controls) is
not represented by this single build-menu sublayer.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

class HudGeometryError(ValueError):
    pass


def _pair(raw, name, *, min_value=-8192, max_value=8192):
    if not isinstance(raw,list) or len(raw)!=2:
        raise HudGeometryError(f"{name}: 2 numbers expected")
    if any(not isinstance(x,(int,float)) or isinstance(x,bool) or
           not isfinite(x) or not min_value<=x<=max_value for x in raw):
        raise HudGeometryError(f"{name}: invalid numbers")
    return tuple(float(x) for x in raw)


def _rect(raw,name):
    if not isinstance(raw,list) or len(raw)!=4:
        raise HudGeometryError(f"{name}: rectangle expected")
    xy=_pair(raw[:2],name)
    wh=_pair(raw[2:],name,min_value=0,max_value=8192)
    if wh[0]<=0 or wh[1]<=0:
        raise HudGeometryError(f"{name}: dimensions must be positive")
    return xy+wh


@dataclass(frozen=True)
class HudComposition:
    scene_width: float
    scene_height: float
    pixel_scale: float
    scroll_parent: tuple[float,float]
    scroll_clip: tuple[float,float,float,float]
    scroll_offset: tuple[float,float]
    menu_parent: tuple[float,float]
    menu_clip: tuple[float,float,float,float]
    menu_offset: tuple[float,float]

    @classmethod
    def from_contract(cls,contract):
        try:
            layout=contract["layout"]
            data=layout["composition"]
            scroll=data["scroll"]
            menu=data["build_menu"]
            width,height=_pair(data["alignment_size"],"alignment_size",min_value=1)
            scale=layout["pixel_scale"]
            if not isinstance(scale,(int,float)) or isinstance(scale,bool) or not 0<scale<=2:
                raise HudGeometryError("pixel_scale out of bounds")
            return cls(
                width,height,float(scale),
                _pair(scroll["parent_margin"],"scroll parent"),
                _rect(scroll["clip_rect"],"scroll clip"),
                _pair(scroll["translated_position"],"scroll position"),
                _pair(menu["parent_margin"],"menu parent"),
                _rect(menu["clip_rect"],"menu clip"),
                (
                    _pair(menu["child_margin"],"child margin")[0]+
                    _pair(menu["settled_translate"],"settled translate")[0],
                    _pair(menu["child_margin"],"child margin")[1]+
                    _pair(menu["settled_translate"],"settled translate")[1],
                ),
            )
        except (KeyError,TypeError) as exc:
            raise HudGeometryError(f"Incomplete XAML HUD placement: {exc}") from exc

    def image_pos(self):
        return (
            self.scroll_parent[0]+self.scroll_offset[0],
            self.scroll_parent[1]+self.scroll_offset[1],
        )

    def button_pos(self,command):
        x,y=command["x"],command["y"]
        if (not isinstance(x,(int,float)) or not isinstance(y,(int,float))
                or not isfinite(x) or not isfinite(y)):
            raise HudGeometryError("Invalid XAML button margin")
        return (
            self.menu_parent[0]+self.menu_offset[0]+float(x),
            self.menu_parent[1]+self.menu_offset[1]+float(y),
        )

    def button_scale(self,command,pix_width,pix_height):
        if pix_width <= 0 or pix_height <= 0:
            raise HudGeometryError("Empty sprite crop")
        scale=self.pixel_scale
        width,height=command.get("width"),command.get("height")
        if width is not None:
            if width<=0:raise HudGeometryError("Invalid width")
            scale=min(scale,float(width)/pix_width)
        if height is not None:
            if height<=0:raise HudGeometryError("Invalid height")
            scale=min(scale,float(height)/pix_height)
        return scale

    def scroll_visible_rect(self):
        x,y,w,h=self.scroll_clip
        return (
            x+self.scroll_parent[0],y+self.scroll_parent[1],w,h
        )

    def menu_visible_rect(self):
        x,y,w,h=self.menu_clip
        return (
            x+self.menu_parent[0],y+self.menu_parent[1],w,h
        )

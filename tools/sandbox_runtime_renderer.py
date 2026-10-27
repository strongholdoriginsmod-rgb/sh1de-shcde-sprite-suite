"""Render exact native engine file/frame/height decisions with local sprites.

This replaces guessed tile and object frames, not Unity's complete shader
pipeline. Foliage wind, special effects and some animation layers remain
separate parity tasks. No game binary/art is distributed by this module.
"""
from __future__ import annotations
from collections import OrderedDict
from dataclasses import dataclass
import math
import numpy as np
from PIL import Image
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPixmap, QPainter
from stronghold_europe_de.sandbox.runtime_graphics import (
    RuntimeSprite, RuntimeSpriteResolver, tile_tint_components,
)
from sandbox_asset_preview import to_pixmap

@dataclass(frozen=True)
class EngineSpriteHit:
    """Visible, alpha-tested graphics primitive from a paused game snapshot."""
    kind: str
    x: int
    y: int
    ref: RuntimeSprite
    source_file: int
    source_frame: int
    anchor_x: float
    anchor_y: float
    opacity: float


class NativeCommandRenderer:
    def __init__(self, owner, snapshot):
        self.owner = owner
        self.snapshot = snapshot
        self.resolver = RuntimeSpriteResolver()
        from sandbox_engine_assets import EngineSpriteAssets
        self.assets = EngineSpriteAssets(owner._map_path)
        self.images = OrderedDict()
        self.missing = set()
        self.overview = None
        self.overview_rect = None
        self.max_images = 2048

    def invalidate(self):
        self.images.clear()
        self.missing.clear()
        self.assets.invalidate()
        self.overview = None

    def _pixmap(self, ref):
        if ref is None:
            return None
        key = (ref.group, ref.frame, ref.light, ref.float_colour)
        if key in self.images:
            self.images.move_to_end(key)
            return self.images[key]
        try:
            frame = self.assets.frame(ref.group, ref.frame, self.owner._source)
        except (OSError, ValueError, RuntimeError) as exc:
            self.owner.message.emit(f"Original-Sprite nicht ladbar: {ref.group}/{ref.frame}: {exc}")
            frame = None
        if frame is None:
            self.missing.add(key[:2])
            value = None
        else:
            rgba = frame.image.convert('RGBA')
            multipliers = tile_tint_components(ref.light,ref.float_colour)
            if multipliers != (1.0,1.0,1.0):
                channels=rgba.split()
                rgba=Image.merge('RGBA',tuple(
                    band.point([max(0,min(255,round(i*f))) for i in range(256)])
                    for band,f in zip(channels[:3],multipliers)
                )+(channels[3],))
            proxy = type('RuntimePixels', (), {'image':rgba})()
            value = (to_pixmap(proxy, checkerboard=False), frame.foot)
        self.images[key] = value
        self.owner._texture_signatures[(ref.group,ref.frame)] = self.owner._signature(ref.group,ref.frame)
        if len(self.images)>self.max_images:
            self.images.popitem(last=False)
        return value

    def _tile_reference(self, record):
        x,y,file,frame = map(int,record[1:5])
        # Respect user ground experiments, but don't replace native building
        # sprites just because their ground height coincides with an override.
        if not self.assets.original_only and file in (2,5,12,55,56,60,166):
            values = self.owner._channels.at(x,y)
            manual = self.owner.terrain_tests.get(values[3005]) if self.owner.terrain_tests else None
            if manual is None and self.owner.surface_tests and 3037 in values:
                manual = self.owner.surface_tests.get(values[3037])
            if manual is not None:
                return RuntimeSprite(manual.group,manual.frame,0,int(record[7]))
        return self.resolver.resolve(
            file,frame,light=int(record[6]),float_colour=int(record[7])
        )

    def _draw(self, painter, ref, x, y, opacity=1.0):
        value = self._pixmap(ref)
        if value is None:
            return
        pix,foot = value
        if opacity != 1.0:
            painter.save();painter.setOpacity(max(0,min(1,opacity)))
        painter.drawPixmap(QPointF(x-foot[0],y-foot[1]),pix)
        if opacity != 1.0:
            painter.restore()

    def _floor(self, painter, r):
        x,y = int(r[1]),int(r[2])
        if int(r[3]) in (0,38):
            return
        height=int(r[5])
        cx,cy=x*32+16,y*16+16-height*2
        # Original native cap/wall/cliff command. Surface panels and vertical
        # sides are different sprites; rendering them twice as floor is wrong.
        cap_file,cap_frame=int(r[11]),int(r[12])
        if cap_file in (3,9,10):
            front=[self.snapshot.tile(x-1,y+1),self.snapshot.tile(x+1,y+1)]
            visible=any(t is None or int(t[5])<height for t in front)
            if visible:
                # Chevron lookup indexes its GM array directly; unlike a
                # body/tree animation it is NOT a one-based getBodyImage call.
                ref=self.resolver.resolve(cap_file,cap_frame,tile=True)
                floor_ref=self._tile_reference(r)
                if ref is not None and floor_ref is not None:
                    ref=RuntimeSprite(
                        ref.group,ref.frame,floor_ref.light,floor_ref.float_colour
                    )
                self._draw(painter,ref,cx,cy)
        self._draw(painter,self._tile_reference(r),cx,cy)

    def _actor_placement(self, r):
        kind,x,y,file,frame = map(int,r[:5])
        if file <= 0 or frame < 0:
            return None
        opacity=max(0.0,min(1.0,(32-int(r[11]))/32))
        if opacity <= 0:
            return None
        if kind == 1:
            if not self.owner.show_original_trees:
                return None
            # A manually assigned tree is a selectable QGraphicsItem.
            if (not self.assets.original_only and
                    self.owner.visual_mappings.get('tree',file) is not None):
                return None
            dx,dy = 14,8
        elif kind in (2,3):
            dx,dy = int(r[8]),int(r[9])
            if dx>128:dx-=256
            if dy>128:dy-=256
        elif kind == 4:
            ref=self.resolver.resolve(file,frame,tile=False)
            if ref is None:return None
            return (ref, x*32+16-30+int(r[8])*2,
                    y*16+16-14+int(r[9])*2, opacity)
        else:
            return None
        cx=x*32+16-32+2*(dx+1)
        cy=y*16+16-16+2*(dy+1)+int(r[5])*2
        ref=self.resolver.resolve(file,frame,tile=False)
        if ref is None:return None
        return (ref,cx,cy,opacity)

    def _actor(self, painter, r):
        placement=self._actor_placement(r)
        if placement is not None:
            self._draw(painter,*placement)

    def _pick_commands(self, r):
        """Reverse paint order inside a single native engine command."""
        x,y,file,frame=map(int,r[1:5])
        kind=int(r[0])
        if kind != 0:
            placement=self._actor_placement(r)
            return [] if placement is None else [("actor",*placement)]
        if file in (0,38):
            return []
        height=int(r[5])
        cx,cy=x*32+16,y*16+16-height*2
        floor=self._tile_reference(r)
        out=[]
        if floor is not None:
            out.append(("floor", floor,cx,cy,1.0))
        cap_file,cap_frame=int(r[11]),int(r[12])
        if cap_file in (3,9,10):
            front=[self.snapshot.tile(x-1,y+1),self.snapshot.tile(x+1,y+1)]
            visible=any(t is None or int(t[5])<height for t in front)
            if visible:
                cap=self.resolver.resolve(cap_file,cap_frame,tile=True)
                if cap is not None:
                    if floor is not None:
                        cap=RuntimeSprite(
                            cap.group,cap.frame,floor.light,floor.float_colour
                        )
                    out.append(("height-side",cap,cx,cy,1.0))
        return out

    def pick_graphic(self, px: float, py: float):
        """Select the *visible original sprite* under a map pixel.

        The engine draws records by y then tile/actor order; walk that order
        backwards and use the actual rendered alpha, not the 32x16 bounding
        tile. This selects multi-tile keeps, trees and units where they appear,
        even when their art extends into neighboring terrain tiles.
        """
        if not math.isfinite(px) or not math.isfinite(py):
            return None
        records=self.snapshot.draw_records
        # Conservative bounds include tall castles, height offsets and
        # sub-tile actor positions. Vectorized filtering prevents decoding
        # thousands of unrelated atlas sprites on every mouse click.
        # Native tiles are 32x16; even the largest supported building sprites
        # span only a limited surrounding neighbourhood, not half the map.
        # Bound *command centres* first, then reject distant anchors before
        # touching expensive Unity/BC7 sprite images.
        x0,x1=math.floor((px-768)/32),math.ceil((px+768)/32)
        y0,y1=math.floor((py-384)/16),math.ceil((py+1536)/16)
        mask=((records[:,1]>=x0)&(records[:,1]<=x1)&
              (records[:,2]>=y0)&(records[:,2]<=y1))
        candidates=records[mask]
        for row in reversed(candidates):
            x,y,file,frame=map(int,row[1:5])
            for kind,ref,cx,cy,opacity in self._pick_commands(row):
                if opacity*255 <= 24:
                    continue
                # The retained rendered sprite footprints do not extend beyond
                # this conservative visible-art radius on the pinned build.
                if not (-768 <= px-cx <= 768 and -384 <= py-cy <= 1536):
                    continue
                value=self._pixmap(ref)
                if value is None:continue
                pix,foot=value
                ix=math.floor(px-(cx-foot[0]))
                iy=math.floor(py-(cy-foot[1]))
                if 0<=ix<pix.width() and 0<=iy<pix.height():
                    if pix.toImage().pixelColor(ix,iy).alpha()*opacity>24:
                        return EngineSpriteHit(
                            kind,x,y,ref,file,frame,cx,cy,opacity
                        )
        return None

    def draw_area(self, painter: QPainter, rect: QRectF):
        # Height displacement and tall buildings extend beyond their ground
        # tile/chunk. Cull with conservative margins to keep cliff/roof seams.
        x0=max(0,int((rect.left()-512)//32));x1=min(799,int((rect.right()+512)//32))
        y0=max(0,int((rect.top()-256)//16));y1=min(799,int((rect.bottom()+1024)//16))
        for y in range(y0,y1+1):
            for r in self.snapshot.rows[y]:
                if not x0 <= int(r[1]) <= x1:
                    continue
                if r[0]==0:self._floor(painter,r)
                else:self._actor(painter,r)

    def draw_overview(self, painter, target_rect):
        bounds = self.owner.scene().sceneRect()
        if self.overview is None or self.overview_rect != bounds:
            factor=min(1.0,2048/max(bounds.width(),bounds.height()))
            size=(max(1,math.ceil(bounds.width()*factor)),
                  max(1,math.ceil(bounds.height()*factor)))
            image=QPixmap(*size);image.fill(Qt.GlobalColor.transparent)
            draw=QPainter(image)
            draw.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform,False)
            draw.scale(factor,factor)
            draw.translate(-bounds.x(),-bounds.y())
            self.draw_area(draw,bounds)
            draw.end()
            self.overview=image
            self.overview_rect=QRectF(bounds)
        painter.drawPixmap(bounds,self.overview,QRectF(self.overview.rect()))

    def native_height(self,x,y):
        r=self.snapshot.tile(x,y)
        return int(r[5]) if r is not None else 0

    def pick_tile(self, px, py):
        """Pick the visible original sprite, including raised ground/roofs."""
        fx,fy=math.floor(px/32),math.floor(py/16)
        for y in range(min(799,fy+65),max(-1,fy-5),-1):
            for x in range(min(799,fx+3),max(-1,fx-4),-1):
                r=self.snapshot.tile(x,y)
                if r is None or int(r[3]) in (0,38):
                    continue
                ref=self._tile_reference(r)
                value=self._pixmap(ref)
                if value is None:continue
                pix,foot=value
                ix=int(px-(x*32+16-foot[0]))
                iy=int(py-(y*16+16-int(r[5])*2-foot[1]))
                if 0<=ix<pix.width() and 0<=iy<pix.height():
                    if pix.toImage().pixelColor(ix,iy).alpha()>24:
                        return x,y
        return fx,fy

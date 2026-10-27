"""Map-radar projection, calibrated against native playable diamond and radar.

Important: the raw 800-row native diamond contains padding and is not
the logical 400x400 (or smaller) playable world. For the three inspected
SHCDE .map fixtures the *actual* radar orientation is:
    screen_x = reversed native v-axis; screen_y = native u-axis
where u=(x+y-399)/2 and v=(y-x+399)/2.
Water-coded native areas align with blue radar pixels only under this
orientation and when the world (non-padding) bounds determine the scale.
"""
from __future__ import annotations
from dataclasses import dataclass

NATIVE_HALF = 400
NATIVE_TOP_X = 399


@dataclass(frozen=True)
class RadarProjection:
    left: float
    top: float
    width: float
    height: float
    playable_bounds: tuple[float, float, float, float] | None = None

    def __post_init__(self):
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Radarkartenausschnitt muss eine positive Größe besitzen")
        if self.playable_bounds is not None:
            umin, umax, vmin, vmax = self.playable_bounds
            if not (umin < umax and vmin < vmax and
                    self.width > 1 and self.height > 1):
                raise ValueError("Ungültige spielbare Originalkarten-Grenzen")

    @classmethod
    def from_image(cls, image):
        """Bounding rectangle of actual original map preview pixels."""
        rgb = image.convert("RGB")
        bbox = rgb.getbbox()
        if not bbox:
            return cls(0, 0, image.width, image.height)
        left, top, right, bottom = bbox
        return cls(left, top, right-left, bottom-top)

    @classmethod
    def from_original_geometry(cls, image, geometry):
        """True map scale and verified orientation for loaded native layers.

        Generic/unknown maps without a populated 3003 border retain the
        independent older geometry-only navigation, rather than being assigned
        false playable bounds.
        """
        measured = cls.from_image(image)
        if geometry is None or geometry.flags is None or geometry.padding_tiles == 0:
            return measured
        return cls(
            measured.left, measured.top, measured.width, measured.height,
            (geometry.u_min, geometry.u_max, geometry.v_min, geometry.v_max),
        )

    def native_to_radar(self, x: float, y: float) -> tuple[float, float]:
        u = (x + y - NATIVE_TOP_X) / 2
        v = (y - x + NATIVE_TOP_X) / 2
        if self.playable_bounds is not None:
            umin, umax, vmin, vmax = self.playable_bounds
            # Cross-validated on Antioch, Crusader Demo and A Mighty Oasis:
            # the original radar's horizontal axis is mirrored native v.
            return (
                self.left + (vmax - v) / (vmax - vmin) * (self.width - 1),
                self.top + (u - umin) / (umax - umin) * (self.height - 1),
            )
        # This fallback preserves earlier navigation for maps lacking 3003.
        return (self.left + u * self.width / NATIVE_HALF,
                self.top + v * self.height / NATIVE_HALF)

    def radar_to_native(self, rx: float, ry: float) -> tuple[float, float]:
        if self.playable_bounds is not None:
            umin, umax, vmin, vmax = self.playable_bounds
            v = vmax - (rx-self.left) / (self.width-1) * (vmax-vmin)
            u = umin + (ry-self.top) / (self.height-1) * (umax-umin)
        else:
            u = (rx-self.left) * NATIVE_HALF / self.width
            v = (ry-self.top) * NATIVE_HALF / self.height
        return (u-v + NATIVE_TOP_X, u+v)

    def contains_radar(self, rx, ry):
        return (self.left <= rx < self.left + self.width and
                self.top <= ry < self.top + self.height)

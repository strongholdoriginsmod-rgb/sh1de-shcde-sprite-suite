"""Selection artwork from sprites ALREADY rendered by the active map canvas.

Never invoke FrameSource, UnityPy, atlas export, or an arbitrary image path.
An engine command's ID comes from a paused native snapshot; its cached
pixels may be original, supplied, or work-modified. Only an explicit
original-only renderer flag permits a 'read-only original' provenance.
Original building/tree type IDs are not mapped to sprites here.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CachedHudArtwork:
    kind: str
    group: str
    frame: int
    pixmap: object
    source: str

    @property
    def identity(self):
        return f"{self.group}/{self.frame}"


def selection_artwork(canvas, kind: str, language="de") -> CachedHudArtwork | None:
    """Resolve displayed pixels without *any* disk, decode or export call."""
    if not canvas.has_map() or canvas.history is None:
        return None
    en = language == "en"
    if kind == "overlay":
        selected = canvas.select_id()
        if not selected:
            return None
        record = next(
            (p for p in canvas.history.overlay.objects if p.id == selected),
            None,
        )
        # Only items owned by this *same* scene with an actually loaded
        # frame. The missing-frame magenta placeholder is not real artwork.
        item = getattr(canvas, "_items", {}).get(selected)
        if (record is None or item is None or
                getattr(item, "object_id", None) != selected or
                not getattr(item, "source_loaded", False) or
                item.scene() is not canvas.scene()):
            return None
        pix = item.pixmap()
        if pix is None or pix.isNull():
            return None
        return CachedHudArtwork(
            "overlay", record.group, record.frame, pix,
            "Displayed working-copy sprite, NOT original game art"
            if en else "Angezeigte Arbeitsgrafik, KEIN Originalspiel-Nachweis",
        )

    if kind == "engine" and canvas.engine_active():
        hit = canvas.last_engine_pick
        renderer = canvas.runtime_renderer
        if (hit is None or renderer is None or
                renderer.owner is not canvas or
                renderer.snapshot is not canvas.runtime_snapshot):
            return None
        ref = hit.ref
        cache_key = (ref.group, ref.frame, ref.light, ref.float_colour)
        cached = renderer.images.get(cache_key)
        if not cached or cached[0] is None or cached[0].isNull():
            return None
        # The cache is populated exclusively by the existing map renderer.
        # Do not call _pixmap(), because that could export missing frames.
        original_only = bool(renderer.assets.original_only)
        source = (
            ("Original Unity sprite from read-only resource mode"
             if en else "Original-Unity-Sprite aus Nur-Lese-Modus")
            if original_only else
            ("Displayed renderer frame; pixels may be local work/catalog art"
             if en else
             "Angezeigter Renderer-Frame; ggf. lokale Arbeits-/Kataloggrafik")
        )
        return CachedHudArtwork("engine", ref.group, ref.frame, cached[0], source)
    # Never invent a picture for raw type codes in map sections 1013/1014,
    # for individual tile values, or for an unselected/invalid frame.
    return None

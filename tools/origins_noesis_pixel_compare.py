"""Exact-pixel comparison of two captured Noesis/game screenshots.

A verification instrument, NOT a substitute for the actual game renderer.
No rescale, automatic alignment or fake screenshot may produce parity claims.
"""
from __future__ import annotations
from hashlib import sha256
from pathlib import Path
import json
import os
import shutil
import tempfile

from PIL import Image,UnidentifiedImageError


class PixelCompareError(ValueError): pass


def _read_image(path:Path)->Image.Image:
    file=Path(path)
    if not file.is_file() or file.is_symlink() or file.stat().st_size>256*1024**2:
        raise PixelCompareError("Echtes PNG-Bild fehlt oder ist zu groß")
    try:
        with Image.open(file) as image:
            if (image.format!="PNG" or image.width<2 or image.height<2
                    or image.width>8192 or image.height>8192
                    or image.width*image.height>32_000_000):
                raise PixelCompareError("Ungültiger PNG-Referenzrahmen")
            image.load()
            return image.convert("RGBA")
    except (OSError,UnidentifiedImageError,Image.DecompressionBombError) as exc:
        raise PixelCompareError("Ungültige oder nicht lesbare PNG-Referenz") from exc


def compare_captured_frames(before:Path,after:Path,output:Path, *,
                            max_channel_error:int=0,
                            source_kind:str="user-captured-noesis") -> dict:
    """Compare exact pixels while leaving source images byte-identical.

    The source kind is self-declared provenance. A report does NOT attest an
    in-game render unless the caller supplies independently verified captures.
    """
    if type(max_channel_error) is not int or not 0<=max_channel_error<=255:
        raise PixelCompareError("Pixel-Kanal-Toleranz muss 0..255 sein")
    if not isinstance(source_kind,str) or len(source_kind)>100:
        raise PixelCompareError("Ungültiger Referenztyp")
    first=_read_image(before)
    second=_read_image(after)
    if first.size!=second.size:
        raise PixelCompareError(
            "Exakter Noesis-Abgleich benötigt dieselbe Auflösung "
            "und Pixel-Ausrichtung: "+str(first.size)+" vs. "+str(second.size))
    import numpy as np
    a=np.asarray(first,dtype=np.int16)
    b=np.asarray(second,dtype=np.int16)
    delta=np.abs(a-b)
    change=np.max(delta,axis=2)
    mask=change>max_channel_error
    total=first.width*first.height
    changed=int(np.count_nonzero(mask))
    mean=float(delta.mean())
    peak=int(delta.max())
    highlight=np.zeros((first.height,first.width,4),dtype=np.uint8)
    highlight[...,0]=np.clip(change*2,0,255).astype(np.uint8)
    highlight[...,3]=np.where(mask,255,0).astype(np.uint8)
    overlay=Image.blend(first,second,0.5)
    heat=Image.fromarray(highlight,"RGBA")
    output=Path(output)
    if output.exists() or output.is_symlink():
        raise PixelCompareError("Pixel-Abnahmeordner existiert bereits")
    output.parent.mkdir(parents=True,exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix=".noesis-compare-",dir=output.parent))
    try:
        heat.save(stage/"differences.png",format="PNG")
        overlay.save(stage/"half-overlay.png",format="PNG")
        report={
            "schema":"sprite-suite.noesis-pixel-compare.v1",
            "reference":str(before),"current":str(after),
            "reference_sha256":sha256(Path(before).read_bytes()).hexdigest(),
            "current_sha256":sha256(Path(after).read_bytes()).hexdigest(),
            "resolution":[first.width,first.height],
            "channel_tolerance":max_channel_error,
            "changed_pixels":changed,"total_pixels":total,
            "changed_fraction":round(changed/total,10),
            "mean_absolute_channel_difference":round(mean,6),
            "maximum_channel_difference":peak,
            "pixel_identical":changed==0,
            "source_kind":source_kind,
            "native_noesis_renderer_invoked":False,
            "game_render_parity_attested":False,
            "user_must_supply_native_game_captures_for_parity":True,
            "game_installation_modified":False,
        }
        (stage/"comparison.json").write_text(json.dumps(
            report,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
        os.rename(stage,output)
    finally:
        if stage.exists() and not stage.is_symlink():
            shutil.rmtree(stage)
    return {"output":str(output),
            "heatmap":str(output/"differences.png"),
            "overlay":str(output/"half-overlay.png"),
            "report":str(output/"comparison.json"),**report}

"""One read-only source inspector for SpriteSuite sprites, masks, DDS and atlases.

This is a shared analyzer used by the *existing* unified project workflow;
it is not a second asset editor, writer, package builder or runtime decoder.
"""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import struct
from typing import Any

from PIL import Image, UnidentifiedImageError

MAX_BYTES = 64 * 1024 * 1024
MAX_PIXELS = 4096 * 4096
MAX_JSON_BYTES = 1024 * 1024
SHA = "sha256"
DDS_FOURCC = {b"DXT1": "BC1", b"DXT3": "BC2", b"DXT5": "BC3"}


class AssetInspectionError(ValueError):
    pass


def _is_link(path: Path) -> bool:
    try:
        return path.is_symlink() or bool(
            getattr(path.lstat(), "st_file_attributes", 0) & 0x400
        )
    except (OSError, ValueError):
        return True


def _strict_pairs(pairs: list[tuple[str, Any]]) -> dict:
    data = {}
    for name, value in pairs:
        if name in data:
            raise AssetInspectionError("Doppelter JSON-Schlüssel: " + name)
        data[name] = value
    return data


def _regular(path: Path) -> bytes:
    path = Path(path).absolute()
    if _is_link(path) or not path.is_file():
        raise AssetInspectionError("Asset fehlt oder ist verknüpft")
    before = path.stat()
    if not 1 <= before.st_size <= MAX_BYTES:
        raise AssetInspectionError("Assetgröße außerhalb des 64-MiB-Lesebudgets")
    if _is_link(path.parent):
        raise AssetInspectionError("Asset-Elternordner ist verknüpft")
    with path.open("rb") as inp:
        chunks, size = [], 0
        while data := inp.read(1024 * 1024):
            size += len(data)
            if size > MAX_BYTES:
                raise AssetInspectionError("Asset überschreitet Dateibudget")
            chunks.append(data)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, getattr(before, "st_ino", None)) != (
            after.st_size, after.st_mtime_ns, getattr(after, "st_ino", None)):
        raise AssetInspectionError("Asset hat sich während der Prüfung geändert")
    if size != before.st_size:
        raise AssetInspectionError("Asset wurde während des Lesens verändert")
    return b"".join(chunks)


def _png(payload: bytes) -> dict:
    try:
        with Image.open(BytesIO(payload)) as image:
            if image.format != "PNG" or getattr(image, "n_frames", 1) != 1:
                raise AssetInspectionError("Kein einbildriges PNG")
            width, height = image.size
            if (width < 1 or height < 1 or width * height > MAX_PIXELS):
                raise AssetInspectionError("PNG überschreitet das Pixelbudget")
            original_mode = image.mode
            rgba = image.convert("RGBA")
            pixels = rgba.tobytes()
            bbox = rgba.getchannel("A").getbbox()
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        raise AssetInspectionError("PNG ist nicht lesbar oder beschädigt") from exc
    visible = partial = hidden_rgb = 0
    for i in range(0, len(pixels), 4):
        alpha = pixels[i + 3]
        if alpha:
            visible += 1
        if 0 < alpha < 255:
            partial += 1
        if alpha == 0 and (pixels[i] or pixels[i + 1] or pixels[i + 2]):
            hidden_rgb += 1
    return {
        "format": "PNG", "width": width, "height": height,
        "source_mode": original_mode, "rgba_sha256": sha256(pixels).hexdigest(),
        "alpha_bbox": list(bbox) if bbox else None,
        "visible_pixels": visible, "partial_alpha_pixels": partial,
        "hidden_rgb_pixels": hidden_rgb,
        "all_transparent": visible == 0,
        "pixel_contract": "inspect_only_not_bc7_quality_approval",
    }


def _dds(payload: bytes) -> dict:
    if len(payload) < 128 or payload[:4] != b"DDS ":
        raise AssetInspectionError("DDS-Signatur oder Header fehlt")
    if struct.unpack_from("<I", payload, 4)[0] != 124:
        raise AssetInspectionError("DDS_HEADER muss exakt 124 Bytes groß sein")
    height, width = struct.unpack_from("<II", payload, 12)
    depth, mipmaps = struct.unpack_from("<II", payload, 24)
    if width < 1 or height < 1 or width * height > MAX_PIXELS:
        raise AssetInspectionError("DDS-Abmessungen außerhalb des Pixelbudgets")
    if struct.unpack_from("<I", payload, 76)[0] != 32:
        raise AssetInspectionError("DDS_PIXELFORMAT muss 32 Bytes groß sein")
    fourcc = payload[84:88]
    fmt = DDS_FOURCC.get(fourcc)
    dxgi = None
    if fourcc == b"DX10":
        if len(payload) < 148:
            raise AssetInspectionError("DDS DX10-Zusatzheader fehlt")
        dxgi = struct.unpack_from("<I", payload, 128)[0]
        fmt = {71: "BC1", 72: "BC1_sRGB", 74: "BC2", 77: "BC3",
               98: "BC7", 99: "BC7_sRGB"}.get(dxgi)
    if fmt is None:
        raise AssetInspectionError("DDS-Kompression nicht für diesen Inspector unterstützt")
    block_size = 8 if fmt.startswith("BC1") else 16
    image_bytes = ((width + 3) // 4) * ((height + 3) // 4) * block_size
    header_bytes = 148 if fourcc == b"DX10" else 128
    if len(payload) < header_bytes + image_bytes:
        raise AssetInspectionError("DDS-Blockpayload ist abgeschnitten")
    return {
        "format": "DDS", "compression": fmt, "dxgi_format": dxgi,
        "width": width, "height": height,
        "mipmap_declared": mipmaps, "depth_declared": depth,
        "base_level_bytes": image_bytes,
        "header_bytes": header_bytes, "payload_bytes": len(payload) - header_bytes,
        "complete_mip_chain_verified": False,
        "runtime_material_verified": False,
    }


def _atlas(payload: bytes) -> dict:
    if len(payload) > MAX_JSON_BYTES or payload.startswith(b"\xef\xbb\xbf"):
        raise AssetInspectionError("Atlas-JSON ist zu groß oder enthält ein BOM")
    try:
        raw = json.loads(payload.decode("utf-8"), object_pairs_hook=_strict_pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise AssetInspectionError("Atlas-JSON ist ungültig") from exc
    if not isinstance(raw, dict) or len(raw) > 256:
        raise AssetInspectionError("Atlas-Metadaten brauchen ein begrenztes JSON-Objekt")
    return {
        "format": "Atlas-JSON", "top_level_keys": sorted(raw),
        "sprite_names": list(raw.get("frames", {}).keys())[:512]
            if isinstance(raw.get("frames"), dict) else [],
        "atlas_schema_verified": False,
        "pivot_scale_verified": False,
        "runtime_material_verified": False,
    }


def inspect_asset(path: Path, *, relative_label: str | None = None) -> dict:
    """Inspect source bytes without changing them, importing DLLs or writing reports."""
    path = Path(path).absolute()
    raw = _regular(path)
    digest = sha256(raw).hexdigest()
    label = relative_label or path.name
    result = {
        "schema": "sprite-suite.shared-asset-inspection.v1",
        "path": label, "sha256": digest, "bytes": len(raw),
        "verified_original_bytes_unchanged": True,
        "native_game_compatibility": False,
        "checks": [],
    }
    ext = path.suffix.casefold()
    if ext == ".png":
        details = _png(raw)
        if details["hidden_rgb_pixels"]:
            result["checks"].append({
                "level": "REVIEW", "code": "HIDDEN_RGB_ALPHA",
                "detail": "Transparente RGB-Ränder im Atlas/BC7 visuell prüfen",
            })
        if details["partial_alpha_pixels"]:
            result["checks"].append({
                "level": "REVIEW", "code": "PARTIAL_ALPHA",
                "detail": "Fransen, Premultiplication und Masken getrennt prüfen",
            })
    elif ext == ".dds":
        details = _dds(raw)
    elif ext == ".json":
        details = _atlas(raw)
    elif ext == ".xaml":
        if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
            raise AssetInspectionError("XML-DTDs oder Entitäten sind nicht erlaubt")
        # Existing visual XAML editor owns XAML diff/patch validation.
        details = {"format": "XAML", "xml_parsed": False,
                   "runtime_noesis_verified": False,
                   "delegate_to": "existing_unified_noesis_editor"}
    else:
        raise AssetInspectionError("Unbekanntes Assetformat für gemeinsame Inspektion")
    result["details"] = details
    result["checks"].append({
        "level": "INFO", "code": "OFFLINE_ONLY",
        "detail": "Kein Shader-/Material- oder echtes Unity-/SHCDE-Verhalten nachgewiesen",
    })
    return result


def inspect_image_mask(image: Path, mask: Path) -> dict:
    """Compare a user-specified pair; never invent material ownership."""
    main = inspect_asset(image)
    other = inspect_asset(mask)
    if main["details"]["format"] != "PNG" or other["details"]["format"] != "PNG":
        raise AssetInspectionError("Farb-/Materialpaar erfordert zwei PNG-Quellen")
    same = (
        main["details"]["width"] == other["details"]["width"]
        and main["details"]["height"] == other["details"]["height"]
    )
    return {
        "schema": "sprite-suite.shared-asset-pair.v1",
        "image": main, "mask": other,
        "dimensions_match": same,
        "status": "REVIEW" if same else "BLOCK",
        "material_semantics_verified": False,
        "game_installed": False,
    }

"""Manual original Scribe reference frames, NEVER gameplay Scribe simulation.

The installed SHCDE atlas contains B001..B045 and C001..C044, but
B045 is 178x164 rather than the standard 374x414. Numeric names do NOT
prove animation order/timing or their relationship to Settings_Scribe.
This viewer is explicitly user-stepped with NO automatic timer.

Requires OriginalGameUICrops: an independently verified installed Unity/XAML
source and checksummed private PNG cache. The manifest's Scribe rectangles
are checked against the installed XAML before even showing the first frame.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import json
import xml.etree.ElementTree as ET

from sandbox_native_hud_crop_provider import OriginalGameUICrops, OriginalUICropError

FAMILIES = {"B": 45, "C": 44}
STANDARD_SIZE = (374, 414)
B045_SIZE = (178, 164)
XAML_NS = "{http://schemas.microsoft.com/winfx/2006/xaml}"


class ScribeReferenceError(ValueError):
    pass


def reference_key(family: str, number: int) -> str:
    """Strict reference ID; no gameplay-state inference or arbitrary paths."""
    if (family not in FAMILIES or type(number) is not int or
            not 1 <= number <= FAMILIES[family]):
        raise ScribeReferenceError("Unknown Scribe reference family/frame")
    return f"UI-Scribe {family}{number:03d}"


def reference_dimensions(family: str, number: int) -> tuple[int,int]:
    reference_key(family, number)
    return B045_SIZE if (family, number) == ("B", 45) else STANDARD_SIZE


class ManualScribeReference:
    """Verified source access for user-stepped, never auto-played reference art."""

    def __init__(self, original: OriginalGameUICrops):
        if not isinstance(original, OriginalGameUICrops):
            raise ScribeReferenceError("Only verified original SHCDE UI art accepted")
        try:
            manifest=json.loads(original.manifest_path.read_text(encoding="utf8"))
            dictpath=Path(manifest["dictionary_xaml"])
            expected=manifest["dictionary_sha256"]
            if not dictpath.is_file():
                raise ScribeReferenceError("Installed XAML reference missing")
            content=dictpath.read_bytes()
            if sha256(content).hexdigest()!=expected:
                raise ScribeReferenceError("XAML source hash changed")
            root=ET.fromstring(content)
            expected_keys={
                reference_key(f,n)
                for f,count in FAMILIES.items()
                for n in range(1,count+1)
            }
            mapping={}
            for child in root:
                key=child.get(XAML_NS+"Key")
                if not child.tag.endswith("CroppedBitmap") or key not in expected_keys:
                    continue
                raw=child.get("SourceRect")
                if not raw or key in mapping:
                    raise ScribeReferenceError("Ambiguous Scribe XAML crop")
                rect=tuple(int(v.strip()) for v in raw.split(","))
                if len(rect)!=4 or min(rect)<0:
                    raise ScribeReferenceError("Invalid Scribe XAML crop")
                mapping[key]=rect
            for family,count in FAMILIES.items():
                for number in range(1,count+1):
                    key=reference_key(family,number)
                    expected_size=reference_dimensions(family,number)
                    rect=mapping.get(key)
                    stored=original.entries.get(key)
                    if (rect is None or len(rect)!=4 or
                            rect[2:]!=expected_size or
                            not isinstance(stored,dict) or
                            stored.get("rect")!=list(rect)):
                        raise ScribeReferenceError(
                            f"Scribe source/XAML contract mismatch: {key}"
                        )
        except (OSError,UnicodeError,ValueError,KeyError,TypeError,
                ET.ParseError) as exc:
            raise ScribeReferenceError("Cannot verify Scribe source/XAML frames") from exc
        self.original=original

    def pixmap(self, family: str, number: int):
        """Lazy SHA-256 checked original PNG, not a queued animation frame."""
        key=reference_key(family,number)
        try:
            return self.original.crop(key)
        except (OSError,OriginalUICropError) as exc:
            raise ScribeReferenceError(f"Missing/corrupt reference: {key}") from exc

    def description(self, family: str, number: int, language="de") -> str:
        key=reference_key(family,number)
        special=(family,number)==("B",45)
        if language=="en":
            suffix=("Special size 178×164; NOT an approved animation ending"
                    if special else "No playback timing or game trigger proven")
            return f"{key} · Original SHCDE pixels · MANUAL reference · {suffix}"
        suffix=("Sonderformat 178×164; KEIN nachgewiesenes Animationsende"
                if special else "Abspielzeit und Spielauslöser nicht nachgewiesen")
        return f"{key} · Original-SHCDE-Pixel · MANUELLE Referenz · {suffix}"


def find_scribe_reference(original: OriginalGameUICrops | None):
    if original is None:
        return None
    try:
        return ManualScribeReference(original)
    except ScribeReferenceError:
        return None

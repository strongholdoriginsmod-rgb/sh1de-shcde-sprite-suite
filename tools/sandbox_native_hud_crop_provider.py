"""Game-HUD original-UI crop provider (private, source-bound local cache).

Only reads regenerated QA crops in work/. Never bundles game pixels,
extracts Unity assets in the UI, edits or installs XAML, or claims game-state
parity. Missing/mismatched source fails CLOSED to the caller.
"""
from __future__ import annotations

from functools import lru_cache
from hashlib import sha256
from pathlib import Path
import json,re

from PySide6.QtGui import QPixmap

ROOT=Path(__file__).resolve().parents[1]
DEFAULT_CROPS=ROOT/"work/original-ui-native-crops-20261015/manifest.json"
HEX64=re.compile(r"[0-9a-f]{64}")
SAFE_PNG=re.compile(r"[0-9a-f]{24}\.png")


class OriginalUICropError(ValueError):
    pass


@lru_cache(maxsize=8)
def _file_digest(path: str, mtime_ns: int, size: int) -> str:
    """Compute installed-source fingerprint once per known file version."""
    h=sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda:stream.read(1024*1024),b""):
            h.update(block)
    return h.hexdigest()


def _verified_file(path: Path, expected: str):
    if not isinstance(expected,str) or HEX64.fullmatch(expected) is None:
        raise OriginalUICropError("Expected valid SHA-256 source fingerprint")
    if not path.is_file():
        raise OriginalUICropError(f"Original UI source missing: {path.name}")
    stat=path.stat()
    if _file_digest(str(path.resolve()),stat.st_mtime_ns,stat.st_size)!=expected:
        raise OriginalUICropError(f"Original UI source SHA mismatch: {path.name}")


class OriginalGameUICrops:
    """Manifest-gated QPixmap loader for original *pixels*, not original HUD AI."""

    def __init__(self, contract: dict, path: Path=DEFAULT_CROPS):
        self.manifest_path=Path(path).resolve()
        self.directory=self.manifest_path.parent
        try:
            data=json.loads(self.manifest_path.read_text(encoding="utf8"))
        except (OSError,UnicodeError,ValueError) as exc:
            raise OriginalUICropError("No valid local original UI crop manifest") from exc
        if (data.get("schema")!="sprite-suite.shcde-native-ui-crops.v1" or
                data.get("source_kind")!="UNMODIFIED_LOCAL_GAME_UNITY_UI_TEXTURE" or
                data.get("texture_name")!="UI-MasterAtlas" or
                data.get("texture_format")!=25 or
                data.get("scribe_state_mapping")!="UNVERIFIED_MANUAL_REFERENCE_ONLY"):
            raise OriginalUICropError("Original UI crop source contract mismatch")
        source=Path(data.get("source",""))
        dictionary=Path(data.get("dictionary_xaml",""))
        hud=Path(data.get("hud_main_xaml",""))
        if (source.name!="globalgamemanagers.assets" or
                dictionary.name!="UI-MasterAtlas.xaml" or
                hud.name!="HUD_Main.xaml"):
            raise OriginalUICropError("Unrecognized original UI source names")
        if (data["dictionary_sha256"]!=contract["source"]["dictionary_sha256"] or
                data["hud_main_sha256"]!=contract["source"]["xaml_sha256"]):
            raise OriginalUICropError("Original UI XAML differs from HUD contract")
        for path,hash_field in (
            (source,"source_sha256"),(dictionary,"dictionary_sha256"),
            (hud,"hud_main_sha256"),
        ):
            _verified_file(path,data[hash_field])
        self.source_sha256=data["source_sha256"]
        self.entries=data.get("entries",{})
        if not isinstance(self.entries,dict) or len(self.entries)>1000:
            raise OriginalUICropError("Unexpected original UI crop inventory")
        # Require all test icons, but keep Scribe B/C strictly reference-only.
        for key,xywh in contract["rectangles"].items():
            entry=self.entries.get(key)
            if not isinstance(entry,dict) or entry.get("rect")!=list(xywh):
                raise OriginalUICropError(f"Missing original crop/rect: {key}")
        self._cache={}

    def crop(self,key: str):
        if key in self._cache:
            return self._cache[key]
        entry=self.entries.get(key)
        if not isinstance(entry,dict):
            raise OriginalUICropError(f"Unknown original UI crop: {key}")
        name=entry.get("name","")
        if not isinstance(name,str) or not SAFE_PNG.fullmatch(name):
            raise OriginalUICropError("Unsafe original UI crop filename")
        path=self.directory/name
        if path.parent.resolve()!=self.directory:
            raise OriginalUICropError("UI crop escapes local QA directory")
        _verified_file(path,entry.get("png_sha256"))
        pix=QPixmap(str(path))
        rect=entry.get("rect",[])
        if pix.isNull() or len(rect)!=4 or pix.size().width()!=rect[2] or pix.size().height()!=rect[3]:
            raise OriginalUICropError(f"UI crop dimensions invalid: {key}")
        self._cache[key]=pix
        return pix


def find_original_game_crops(contract: dict) -> OriginalGameUICrops | None:
    try:
        return OriginalGameUICrops(contract)
    except (OSError,KeyError,TypeError,OriginalUICropError):
        return None

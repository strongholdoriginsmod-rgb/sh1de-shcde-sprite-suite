"""Lossless Stronghold Sandkasten v1 scene data and validation.

The historical renderer's *own* render/scene_items implementation remains
authoritative for frame, seed, GM1 tile-layout and animation semantics.
No flattening or partial conversion is allowed when saving a v1 document.
"""
from __future__ import annotations

from copy import deepcopy
import math
import re
from uuid import NAMESPACE_URL, uuid5

V1_SCHEMA="stronghold-europe.sandkasten.v1"
_GROUP=re.compile(r"^[A-Za-z0-9_-]{1,256}$")
COLOURS=frozenset(("keine","rot","blau","gelb","gruen",
                   "orange","lila","tuerkis","grau"))

class LegacyFormatError(ValueError):
    pass

def valid_int(value,lo=0,hi=999999):
    return type(value) is int and lo<=value<=hi

def _group(value):
    return isinstance(value,str) and _GROUP.fullmatch(value) is not None

def validate_v1(raw):
    """Reject unsupported semantic fields instead of silently discarding them."""
    if not isinstance(raw,dict) or raw.get("schema")!=V1_SCHEMA:
        raise LegacyFormatError("Kein historisches Sandkasten-v1-Dokument")
    if set(raw)-{"schema","name","karte","boden","objekte","hud"}:
        raise LegacyFormatError("Unbekannte historische Kopffelder")
    if not isinstance(raw.get("name"),str) or not 1<=len(raw["name"])<=200:
        raise LegacyFormatError("Ungültiger historischer Szenenname")
    size=raw.get("karte")
    if not (isinstance(size,list) and len(size)==2 and
            all(valid_int(v,1,64) for v in size)):
        raise LegacyFormatError("Historische Kartengröße außerhalb 1..64")
    w,h=size
    ground=raw.get("boden")
    if ground is not None:
        if not isinstance(ground,dict) or set(ground)-{"gruppe","frames","saat"}:
            raise LegacyFormatError("Nicht unterstützter historischer Boden")
        if not _group(ground.get("gruppe")):
            raise LegacyFormatError("Ungültige Boden-Spritegruppe")
        frames=ground.get("frames")
        if not isinstance(frames,list) or not 1<=len(frames)<=10000 or not all(
                valid_int(v) for v in frames):
            raise LegacyFormatError("Ungültige Boden-Framefolge")
        if not valid_int(ground.get("saat",1),-2147483648,2147483647):
            raise LegacyFormatError("Ungültiger Boden-Saatwert")
    hud=raw.get("hud")
    if hud is not None and (
        not isinstance(hud,dict) or set(hud)-{"sichtbar"} or
        not isinstance(hud.get("sichtbar"),bool)):
        raise LegacyFormatError("Nicht unterstützter HUD-Szenenzustand")
    entries=raw.get("objekte")
    if not isinstance(entries,list) or len(entries)>10000:
        raise LegacyFormatError("Historische Objektliste ungültig")
    for i,obj in enumerate(entries):
        if not isinstance(obj,dict):
            raise LegacyFormatError(f"Objekt {i} ist kein Datensatz")
        kind=obj.get("art")
        if kind not in ("kachelobjekt","sprite"):
            raise LegacyFormatError(f"Objekt {i}: unbekannter Typ {kind}")
        allowed={"art","gruppe","x","y","titel","team"}
        allowed|=({"von","spalten","zeilen","layout"} if kind=="kachelobjekt"
                  else {"frame","animation","alt"})
        if set(obj)-allowed:
            raise LegacyFormatError(f"Objekt {i}: unbekannte Felder {set(obj)-allowed}")
        if not _group(obj.get("gruppe")):
            raise LegacyFormatError(f"Objekt {i}: ungültige Spritegruppe")
        if not (valid_int(obj.get("x"),0,w-1) and valid_int(obj.get("y"),0,h-1)):
            raise LegacyFormatError(f"Objekt {i}: Position außerhalb der Karte")
        if obj.get("team","rot") not in COLOURS:
            raise LegacyFormatError(f"Objekt {i}: ungültige Teamfarbe")
        if not isinstance(obj.get("titel",""),str) or len(obj.get("titel",""))>250:
            raise LegacyFormatError(f"Objekt {i}: Titel ungültig")
        if kind=="kachelobjekt":
            if not valid_int(obj.get("von")):
                raise LegacyFormatError(f"Objekt {i}: GM1-Startframe ungültig")
            c,r=obj.get("spalten"),obj.get("zeilen")
            if not valid_int(c,1,64) or not valid_int(r,1,64) or c*r>4096:
                raise LegacyFormatError(f"Objekt {i}: Kompositgröße ungültig")
            if not isinstance(obj.get("layout","gm1"),str) or len(obj.get("layout","gm1"))>40:
                raise LegacyFormatError(f"Objekt {i}: Kompositlayout ungültig")
            if obj["x"]+c>w or obj["y"]+r>h:
                raise LegacyFormatError(f"Objekt {i}: GM1-Komposit verlässt Kartenraster")
        else:
            if not valid_int(obj.get("frame",0)):
                raise LegacyFormatError(f"Objekt {i}: Frame ungültig")
            if "alt" in obj and type(obj["alt"]) is not bool:
                raise LegacyFormatError(f"Objekt {i}: Alternative-Frame ungültig")
            animation=obj.get("animation")
            if animation is not None:
                if (not isinstance(animation,dict) or
                    set(animation)-{"von","bis","fps"}):
                    raise LegacyFormatError(f"Objekt {i}: Animationsformat ungültig")
                lo,hi=animation.get("von"),animation.get("bis")
                fps=animation.get("fps",10)
                if (not valid_int(lo) or not valid_int(hi,lo) or
                    not isinstance(fps,(int,float)) or type(fps) is bool or
                    not math.isfinite(fps) or not 0<fps<=120):
                    raise LegacyFormatError(f"Objekt {i}: Framefolge/FPS ungültig")
    return raw

def legacy_id(index):
    # Internal UI identity is *not* written into the historical JSON.
    return uuid5(NAMESPACE_URL,f"sprite-suite.legacy-scene-v1.item:{index}").hex

def copy_entries(raw):
    return {legacy_id(i):deepcopy(entry)
            for i,entry in enumerate(raw["objekte"])}

def replace_fields(entry, obj):
    record=deepcopy(entry)
    record["gruppe"]=obj.group
    record["x"]=obj.x
    record["y"]=obj.y
    if record["art"]=="kachelobjekt":
        record["von"]=obj.frame
    else:
        record["frame"]=obj.frame
    if "team" in record or obj.team!="rot":
        record["team"]=obj.team
    return record

def render_items_at(raw,tick):
    # Pure, retained original renderer's layout/ground/animation logic;
    # importing here avoids dependency cycles in editable scene model.
    from sandkasten import scene_items
    return scene_items(raw,tick)

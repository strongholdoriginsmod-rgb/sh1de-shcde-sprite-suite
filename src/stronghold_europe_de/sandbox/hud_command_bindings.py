"""User-assigned art-command -> Sprite Suite working-frame bindings.

This is a test tool, not a claim of recovered Stronghold structure IDs.
"""
from __future__ import annotations
import json, os, re, tempfile
from pathlib import Path
from dataclasses import dataclass

from .save_target_guard import guard_existing_json

SCHEMA="stronghold-europe.sandbox.hud-command-binding.v1"
TOKEN=re.compile(r"^[A-Z][A-Z0-9_]{1,120}$")
GROUP=re.compile(r"^[A-Za-z0-9_-]{1,120}$")

@dataclass(frozen=True)
class HudCommandFrame:
    group: str
    frame: int
    def validate(self):
        if (not isinstance(self.group,str) or not GROUP.fullmatch(self.group) or
                type(self.frame) is not int or not 0<=self.frame<=999999):
            raise ValueError("Ungültige HUD-Spritezuordnung")

class HudCommandBindings:
    def __init__(self,bindings=None,allowed=None):
        self.bindings=dict(bindings or {})
        self.allowed=set(allowed) if allowed is not None else None
        self.validate()

    def validate(self):
        if len(self.bindings)>300:
            raise ValueError("Zu viele HUD-Zuordnungen")
        for command, frame in self.bindings.items():
            if (not isinstance(command,str) or not TOKEN.fullmatch(command)) or (
                self.allowed is not None and command not in self.allowed
            ):
                raise ValueError("HUD-Befehl nicht durch XAML bestätigt")
            if not isinstance(frame,HudCommandFrame):
                raise ValueError("Ungültiger HUD-Zuordnungstyp")
            frame.validate()

    def bind(self,command,group,frame):
        copy=dict(self.bindings)
        copy[command]=HudCommandFrame(group,frame)
        replacement=HudCommandBindings(copy,self.allowed)
        self.bindings=replacement.bindings

    def clear(self,command):
        if command in self.bindings:
            del self.bindings[command]

    def get(self,command):
        return self.bindings.get(command)

    def serialize(self):
        self.validate()
        return {"schema":SCHEMA,"bindings":{key:{"group":value.group,"frame":value.frame}
                for key,value in sorted(self.bindings.items())}}

    @classmethod
    def deserialize(cls,data,allowed=None):
        if not isinstance(data,dict) or data.get("schema")!=SCHEMA:
            raise ValueError("Unbekanntes HUD-Mapping")
        if set(data)-{"schema","bindings"}:
            raise ValueError("Unbekannte HUD-Mapping-Kopffelder")
        source=data.get("bindings")
        if not isinstance(source,dict):
            raise ValueError("Ungültige HUD-Bindings")
        result={}
        for key,item in source.items():
            if not isinstance(item,dict) or set(item)!={"group","frame"}:
                raise ValueError("Ungültige HUD-Bindings")
            result[key]=HudCommandFrame(item["group"],item["frame"])
        return cls(result,allowed)


def load_bindings(path,allowed):
    path=Path(path)
    if not path.is_file():
        return HudCommandBindings(allowed=allowed)
    return HudCommandBindings.deserialize(json.loads(path.read_text(encoding="utf-8")),allowed)


def save_bindings(path,bindings):
    dest=Path(path)
    if dest.suffix!=".json":
        raise ValueError("HUD-Mapping nur als JSON")
    text=json.dumps(bindings.serialize(),ensure_ascii=False,indent=2)+"\n"
    guard_existing_json(
        dest,lambda raw: HudCommandBindings.deserialize(raw, bindings.allowed),
        ValueError,"HUD-Befehlsbindung"
    )
    dest.parent.mkdir(parents=True,exist_ok=True)
    fd,temp=tempfile.mkstemp(dir=dest.parent,prefix=".hud-",suffix=".tmp")
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp,dest)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)

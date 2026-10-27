"""Read-only Zinnenlineal pivot measurement inspection.

The Unity in-game tool writes zinnenlineal.versatz.v1. Its offsets are
measured displacement, NOT automatically safe corrections to Sprite Suite
atlases. Never silently edit work indices, raw GM files, or installed games:
the candidate pivot may already be present in the current delivered sprite.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import tempfile

from PIL import Image, ImageDraw

SCHEMA = "zinnenlineal.versatz.v1"
REPORT_SCHEMA = "stronghold-europe.pivot-review.v1"
NAME = re.compile(r"^(?P<group>[A-Za-z][A-Za-z0-9_]{0,90})[ -](?P<number>[0-9]{1,7})(?P<alt>x?)$")
MAX_BYTES = 2 * 1024 * 1024
MAX_RECORDS = 4096
EPSILON = 2e-5


class PivotMeasurementError(ValueError):
    pass


def _finite(value, label: str, limit: float = 100.0) -> float:
    if type(value) not in (float,int) or not math.isfinite(value):
        raise PivotMeasurementError(f"{label}: ungültige Zahl")
    value=float(value)
    if abs(value)>limit:
        raise PivotMeasurementError(f"{label}: außerhalb des zulässigen Messbereichs")
    return value


def _integer(value, label: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise PivotMeasurementError(f"{label}: ungültige Ganzzahl")
    return value


@dataclass(frozen=True)
class Measurement:
    name: str
    group: str
    number: int
    right: int
    up: int
    width: int
    height: int
    pivot_x: float
    pivot_y: float
    new_pivot_x: float
    new_pivot_y: float

    @classmethod
    def from_dict(cls, item: dict):
        if not isinstance(item,dict):
            raise PivotMeasurementError("Jede Messung muss ein JSON-Objekt sein")
        name=item.get("name")
        if not isinstance(name,str) or not (match:=NAME.fullmatch(name)):
            raise PivotMeasurementError("Ungültiger Sprite-Name (Gruppe und Nummer)")
        group=item.get("gruppe")
        if group != match.group("group"):
            raise PivotMeasurementError(f"{name}: Gruppennamen stimmen nicht überein")
        number=_integer(item.get("nummer"),"nummer",0,1_000_000)
        if int(match.group("number")) != number:
            raise PivotMeasurementError(f"{name}: Frame-Nummer stimmt nicht überein")
        width=_integer(item.get("breite"),"breite",1,8192)
        height=_integer(item.get("hoehe"),"hoehe",1,8192)
        right=_integer(item.get("rechts"),"rechts",-4096,4096)
        up=_integer(item.get("hoch"),"hoch",-4096,4096)
        pivot_x=_finite(item.get("pivot_x"),"pivot_x",4)
        pivot_y=_finite(item.get("pivot_y"),"pivot_y",4)
        new_x=_finite(item.get("neu_pivot_x"),"neu_pivot_x",4)
        new_y=_finite(item.get("neu_pivot_y"),"neu_pivot_y",4)
        if abs(new_x-(pivot_x-right/width))>EPSILON:
            raise PivotMeasurementError(f"{name}: neuer Pivot-X widerspricht dem gemessenen Versatz")
        if abs(new_y-(pivot_y-up/height))>EPSILON:
            raise PivotMeasurementError(f"{name}: neuer Pivot-Y widerspricht dem gemessenen Versatz")
        if "pixel_je_einheit" in item:
            unit=_finite(item["pixel_je_einheit"],"pixel_je_einheit",2048)
            if unit<=0:
                raise PivotMeasurementError(f"{name}: Pixel-pro-Einheit muss positiv sein")
        return cls(name,group,number,right,up,width,height,pivot_x,pivot_y,new_x,new_y)


@dataclass(frozen=True)
class MeasurementFile:
    path: Path
    sha256: str
    entries: tuple[Measurement,...]


def load_measurements(path: str | Path) -> MeasurementFile:
    path=Path(path)
    if not path.is_file() or path.stat().st_size>MAX_BYTES:
        raise PivotMeasurementError("Messdatei fehlt oder ist zu groß")
    try:
        content=path.read_bytes()
        raw=json.loads(content.decode("utf-8-sig"))
    except (ValueError,UnicodeError,OSError) as exc:
        raise PivotMeasurementError(f"Messdatei ist kein gültiges JSON: {exc}") from exc
    if not isinstance(raw,dict) or raw.get("schema")!=SCHEMA:
        raise PivotMeasurementError("Falsches Zinnenlineal-Messformat")
    rows=raw.get("frames")
    if not isinstance(rows,list) or len(rows)>MAX_RECORDS:
        raise PivotMeasurementError("Ungültige Anzahl an Zinnenlineal-Einträgen")
    items=tuple(Measurement.from_dict(v) for v in rows)
    names=[v.name for v in items]
    if len(names)!=len(set(names)):
        raise PivotMeasurementError("Doppelte Sprite-Einträge in der Messdatei")
    return MeasurementFile(path,sha256(content).hexdigest(),items)


@dataclass(frozen=True)
class PivotReview:
    measurement: Measurement
    status: str
    reason: str
    side: str | None
    pixel_file: Path | None
    actual_pivot: tuple[float,float] | None
    index_file: Path | None = None
    pixel_sha256: str | None = None
    index_sha256: str | None = None


def _hash_file(path: Path) -> str:
    digest=sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda:stream.read(1024*1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_in(directory: Path, filename: str) -> Path | None:
    if not isinstance(filename,str) or not filename or "\\" in filename:
        return None
    rel=Path(filename)
    if rel.suffix.lower() != ".png" or rel.is_absolute() or any(part in (".","..") for part in rel.parts):
        return None
    base=directory.resolve()
    path=(directory/rel).resolve()
    return path if path.is_relative_to(base) and path.is_file() else None


def review_measurements(measurements: MeasurementFile, project_root: str | Path) -> list[PivotReview]:
    root=Path(project_root)
    output=[]
    for item in measurements.entries:
        matches=[]
        for side in ("geliefert","crusader","arbeit"):
            folder=root/"work"/"katalog"/side/item.group
            index=folder/"index.json"
            try:
                if (not index.is_file() or
                    not index.resolve().is_relative_to(folder.resolve()) or
                    index.stat().st_size>MAX_BYTES):
                    continue
                index_bytes=index.read_bytes()
                if len(index_bytes)>MAX_BYTES:
                    continue
                document=json.loads(index_bytes.decode("utf-8"))
                if not isinstance(document,dict) or document.get("group")!=item.group:
                    continue
                frames=document.get("frames")
                if not isinstance(frames,list):
                    continue
                found=[e for e in frames if isinstance(e,dict) and e.get("name")==item.name]
                if len(found)!=1:  # Never approve an ambiguous duplicate index record.
                    continue
                entry=found[0]
                if "pivot_x" in entry:
                    px=float(entry["pivot_x"])
                    py=float(entry["pivot_y"])
                else:
                    eff=entry.get("effective",{})
                    px=float(eff["pivot_x"])
                    py=float(eff["pivot_y"])
                w,h=int(entry["width"]),int(entry["height"])
                if not all(math.isfinite(v) for v in (px,py)):
                    raise ValueError("Non-finite pivot")
                path=_file_in(folder,entry.get("file"))
                if path is None:
                    continue
                # Real image geometry, not merely untrusted index metadata.
                with Image.open(path) as image:
                    if image.size != (w,h):
                        continue
                matches.append((side,path,w,h,px,py,index.resolve(),
                                _hash_file(path),sha256(index_bytes).hexdigest()))
            except (ValueError,TypeError,KeyError,StopIteration,OSError,UnicodeError):
                continue
        if not matches:
            output.append(PivotReview(item,"nicht_gefunden",
                                      "Kein verifizierbarer lokaler PNG-/Index-Frame",None,None,None))
            continue
        # Prioritize the actual deployed version; do not infer correctness
        # from an unmodified Crusader base when delivery already contains
        # a newly aligned overlay.
        side,path,w,h,px,py,index_path,pixel_digest,index_digest=matches[0]
        old=(item.pivot_x,item.pivot_y)
        candidate=(item.new_pivot_x,item.new_pivot_y)
        present=(px,py)
        if (w,h)!=(item.width,item.height):
            status,reason=("geometrie_abweichend","Quellbild hat andere Größe; Pivot nicht übertragbar")
        elif all(abs(a-b)<=EPSILON for a,b in zip(present,candidate)):
            status,reason=("bereits_passend","Der aktuelle Pivot entspricht bereits der Korrektur")
        elif all(abs(a-b)<=EPSILON for a,b in zip(present,old)):
            status,reason=("pruefen","Messung passt zum aktuellen Pivot; Korrektur visuell prüfen")
        else:
            status,reason=("referenz_abweichend","Aktueller Pivot stimmt weder mit Ausgang noch Korrektur überein")
        output.append(PivotReview(item,status,reason,side,path,present,
                                  index_path,pixel_digest,index_digest))
    return output


def render_comparison(review: PivotReview, width: int = 900, height: int = 360) -> Image.Image:
    """Two grounded sprites sharing a fixed world-anchor crosshair.

    Left = currently installed/source index. Right = proposed new Pivot.
    No pixel editing, cropping of original source, or image regeneration.
    """
    width=max(440,min(1700,int(width)))
    height=max(220,min(800,int(height)))
    result=Image.new("RGB",(width,height),(31,35,39))
    draw=ImageDraw.Draw(result)
    draw.text((16,10),f"Vorher ({review.side or '-'})",fill=(231,235,229))
    draw.text((width//2+16,10),"Nachher (Messvorschlag)",fill=(231,235,229))
    if review.pixel_file is None or review.actual_pivot is None:
        draw.text((20,90),review.reason,fill=(236,187,100))
        return result
    with Image.open(review.pixel_file) as source:
        rgba=source.convert("RGBA")
    width_card=width//2
    scale=min((width_card-55)/max(rgba.width,1),(height-95)/max(rgba.height,1),1.5)
    size=(max(1,round(rgba.width*scale)),max(1,round(rgba.height*scale)))
    tile=rgba.resize(size,Image.Resampling.NEAREST)
    # The crosshair is a shared world point. Image positions are determined
    # solely by normalized pivots (Unity Y increases from the bottom).
    for card,pivot in [(0,review.actual_pivot),(1,
                    (review.measurement.new_pivot_x,review.measurement.new_pivot_y))]:
        base=card*width_card
        anchor_x=base+width_card//2
        anchor_y=height//2+12
        foot_x=round(pivot[0]*size[0])
        foot_y=round((1-pivot[1])*size[1])
        x,y=anchor_x-foot_x,anchor_y-foot_y
        overlay=Image.new("RGBA",result.size,(0,0,0,0))
        overlay.paste(tile,(x,y))
        result=Image.alpha_composite(result.convert("RGBA"),overlay).convert("RGB")
        draw=ImageDraw.Draw(result)
        draw.line((anchor_x-12,anchor_y,anchor_x+12,anchor_y),fill="#ffda78",width=2)
        draw.line((anchor_x,anchor_y-12,anchor_x,anchor_y+12),fill="#ffda78",width=2)
        draw.text((base+15,height-34),f"Pivot: {pivot[0]:.6f}, {pivot[1]:.6f}",
                  fill=(238,226,189))
    return result


def save_review_report(
    measurement_file: MeasurementFile, reviews: list[PivotReview],
    project_root: str | Path,
) -> Path:
    root=Path(project_root).resolve()
    current=load_measurements(measurement_file.path)
    if current.sha256!=measurement_file.sha256 or review_measurements(current,root)!=reviews:
        raise PivotMeasurementError("Messung oder Sprite-Quellen seit der Vorschau geändert – neu laden")
    folder=root/"work"/"reports"/"pivot-review"
    folder.mkdir(parents=True,exist_ok=True)
    report={
        "schema":REPORT_SCHEMA,
        "measurement_sha256":measurement_file.sha256,
        "measurement_path":str(measurement_file.path),
        "disclaimer":"Nur Freigabevorschlag, keine Änderungen an Atlas, Spiel oder Arbeitskopie.",
        "rows":[{
            "name":r.measurement.name,"status":r.status,"reason":r.reason,
            "source":r.side,"source_image":str(r.pixel_file) if r.pixel_file else None,
            "source_image_sha256":r.pixel_sha256,
            "source_index":str(r.index_file) if r.index_file else None,
            "source_index_sha256":r.index_sha256,
            "current_pivot":list(r.actual_pivot) if r.actual_pivot else None,
            "measured_old":[r.measurement.pivot_x,r.measurement.pivot_y],
            "measured_new":[r.measurement.new_pivot_x,r.measurement.new_pivot_y],
            "offset_px":[r.measurement.right,r.measurement.up],
            "size":[r.measurement.width,r.measurement.height],
        }for r in reviews],
    }
    payload=json.dumps(report,ensure_ascii=False,indent=2)+"\n"
    tag=sha256(payload.encode("utf-8")).hexdigest()[:12]
    target=folder/f"zinnen-review-{measurement_file.sha256[:12]}-{tag}.json"
    if target.is_file():
        if target.read_text(encoding="utf-8")==payload:
            return target
        raise PivotMeasurementError("Bestehender Prüfbericht hat abweichenden Inhalt")
    fd,temp=tempfile.mkstemp(dir=folder,prefix=".zinnen-review-",suffix=".tmp")
    try:
        with os.fdopen(fd,"w",encoding="utf-8",newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp,target)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return target

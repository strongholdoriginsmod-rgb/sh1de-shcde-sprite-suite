"""Version-neutral HUD/menu layout model and export adapter.

Layouts are persisted outside the package source, under work/.hud-menu-metadata.
A layout preserves original resource paths and numeric geometry; the renderer
uses those same fields for transparent PNG output and asset-only packages.
Never writes an installed game or invents Noesis XAML keys/Unity IDs.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from hashlib import sha256
from io import BytesIO
import json
import math
import os
from pathlib import Path
import re
import tempfile
import uuid

from PIL import Image, UnidentifiedImageError

from hud_menu_workspace import (
    WORK, WorkshopError, _existing, _metadata_dir, _relative, filename,
    workspace,
)

SCHEMA = "sprite-suite.hud-menu-layout.v1"
EXPORT_SCHEMA = "sprite-suite.hud-menu-layout-export.v1"
MAX_LAYERS = 256
MAX_PIXELS = 16_777_216
MAX_SIDE = 4096
MAX_LAYER_SIDE = 8192
ANCHORS = {
    "nw": (0.0, 0.0), "n": (0.5, 0.0), "ne": (1.0, 0.0),
    "w": (0.0, 0.5), "center": (0.5, 0.5), "e": (1.0, 0.5),
    "sw": (0.0, 1.0), "s": (0.5, 1.0), "se": (1.0, 1.0),
}
_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,47}\Z")
_RESOURCE = "Override/Assets/GUI/Images/"
MAX_SCENE_BYTES = 1024 * 1024


def _hash(data: bytes) -> str:
    return sha256(data).hexdigest()


def _finite(value, field_name: str, *, low=-32768., high=32768.) -> float:
    if type(value) not in (int, float):
        raise WorkshopError("Invalid numerical " + field_name)
    num = float(value)
    if not math.isfinite(num) or num < low or num > high:
        raise WorkshopError("Out-of-range " + field_name)
    return num


def _size(value, field_name: str, maximum=MAX_LAYER_SIDE) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise WorkshopError("Invalid " + field_name)
    return value


def _layout_name(name: str) -> str:
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise WorkshopError("Layout name: only 1–48 ASCII letters, digits, _ and -")
    return name


@dataclass
class Layer:
    id: str
    asset: str
    x: float
    y: float
    width: int
    height: int
    rotation: float = 0.0
    anchor: str = "nw"
    pivot_x: float = 0.5
    pivot_y: float = 0.5
    opacity: int = 255
    visible: bool = True
    locked: bool = False
    name: str = ""

    def validate(self, root: Path, *, inspect_file=True) -> None:
        if not isinstance(self.id, str) or not re.fullmatch(r"[0-9a-f]{32}", self.id):
            raise WorkshopError("Invalid layer identifier")
        relative = _relative(self.asset).as_posix()
        if not relative.startswith("Override/") or not relative.lower().endswith(".png"):
            raise WorkshopError("Only workspace PNG assets can be placed in layouts")
        if inspect_file:
            _existing(root, relative)
        self.x = _finite(self.x, "x")
        self.y = _finite(self.y, "y")
        self.width = _size(self.width, "width")
        self.height = _size(self.height, "height")
        if self.width * self.height > MAX_PIXELS:
            raise WorkshopError("Placed image exceeds the pixel budget")
        self.rotation = _finite(self.rotation, "rotation", low=-3600., high=3600.)
        if self.anchor not in ANCHORS:
            raise WorkshopError("Invalid anchor")
        self.pivot_x = _finite(self.pivot_x, "pivot_x", low=0., high=1.)
        self.pivot_y = _finite(self.pivot_y, "pivot_y", low=0., high=1.)
        if type(self.opacity) is not int or not 0 <= self.opacity <= 255:
            raise WorkshopError("Opacity must be 0–255")
        if type(self.visible) is not bool or type(self.locked) is not bool:
            raise WorkshopError("Invalid visible/locked flag")
        if not isinstance(self.name, str) or len(self.name) > 120:
            raise WorkshopError("Invalid layer name")

    def as_json(self):
        return {
            "id": self.id, "asset": self.asset, "name": self.name,
            "x": round(self.x, 4), "y": round(self.y, 4),
            "width": self.width, "height": self.height,
            "rotation": round(self.rotation, 4),
            "anchor": self.anchor,
            "pivot_x": round(self.pivot_x, 5),
            "pivot_y": round(self.pivot_y, 5),
            "opacity": self.opacity, "visible": self.visible,
            "locked": self.locked,
        }


@dataclass
class Scene:
    name: str = "menu-layout"
    width: int = 1280
    height: int = 720
    background: tuple[int, int, int, int] = (24, 30, 39, 0)
    layers: list[Layer] = field(default_factory=list)
    target_resource: str = ""

    def validate(self, project: Path, *, inspect_files=True):
        _layout_name(self.name)
        self.width = _size(self.width, "canvas width", MAX_SIDE)
        self.height = _size(self.height, "canvas height", MAX_SIDE)
        if self.width * self.height > MAX_PIXELS:
            raise WorkshopError("Canvas exceeds 16.7 million pixels")
        if (not isinstance(self.background, (list, tuple))
                or len(self.background) != 4
                or any(type(c) is not int or c < 0 or c > 255
                       for c in self.background)):
            raise WorkshopError("Invalid RGBA background")
        self.background = tuple(self.background)
        if not isinstance(self.layers, list) or len(self.layers) > MAX_LAYERS:
            raise WorkshopError("Too many layers")
        ids = set()
        for layer in self.layers:
            if not isinstance(layer, Layer):
                raise WorkshopError("Invalid scene layer")
            layer.validate(project, inspect_file=inspect_files)
            if layer.id in ids:
                raise WorkshopError("Duplicate layer ID")
            ids.add(layer.id)
        if not isinstance(self.target_resource, str) or len(self.target_resource) > 230:
            raise WorkshopError("Invalid target resource")
        if self.target_resource:
            target = _relative(self.target_resource).as_posix()
            if not target.startswith(_RESOURCE) or not target.lower().endswith(".png"):
                raise WorkshopError("Layout target must be Override/Assets/GUI/Images/*.png")

    def as_json(self):
        return {
            "schema": SCHEMA, "name": self.name, "width": self.width,
            "height": self.height, "background": list(self.background),
            "target_resource": self.target_resource,
            "layers": [layer.as_json() for layer in self.layers],
        }

    def clone(self):
        return scene_from_json(self.as_json(), project=None)


def scene_from_json(doc: dict, project: Path | None) -> Scene:
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        raise WorkshopError("Unsupported layout document schema")
    if not isinstance(doc.get("layers"), list) or len(doc["layers"]) > MAX_LAYERS:
        raise WorkshopError("Invalid layer list")
    required = set(Layer.__dataclass_fields__)
    layers = []
    for row in doc["layers"]:
        if not isinstance(row, dict) or set(row) != required:
            raise WorkshopError("Invalid layer record")
        layers.append(Layer(**row))
    result = Scene(
        name=doc["name"], width=doc["width"], height=doc["height"],
        background=doc["background"], layers=layers,
        target_resource=doc.get("target_resource", ""),
    )
    # For cloned scenes without disk: do not scan filesystem each pointer event.
    result.validate(project or Path("."), inspect_files=project is not None)
    return result


def scene_file(project: Path | str, name: str) -> Path:
    root = workspace(project, create=True)
    destination = _metadata_dir(root) / "layouts" / (
        _layout_name(name) + ".scene.json"
    )
    # This also protects readers: a symlinked layouts/ directory must not
    # redirect the GUI into an unrelated user file outside the workspace.
    _safe_output_path(destination)
    return destination


def load_scene(project: Path | str, name: str) -> tuple[Scene, str]:
    root = workspace(project)
    path = scene_file(root, name)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_SCENE_BYTES:
        raise WorkshopError("Saved layout missing, linked or too large")
    source = path.read_bytes()
    try:
        doc = json.loads(source.decode("utf8"))
        result = scene_from_json(doc, root)
    except (UnicodeError, KeyError, TypeError, ValueError) as exc:
        raise WorkshopError("Invalid or tampered saved scene") from exc
    if result.name != name:
        raise WorkshopError("Saved layout name mismatch")
    return result, _hash(source)


def _safe_output_path(target: Path) -> None:
    """Reject every linked ancestor before reading or writing output bytes."""
    root = WORK.resolve()
    target = Path(target)
    resolved = target.resolve(strict=False)
    if not resolved.is_relative_to(root):
        raise WorkshopError("Output would escape SpriteSuite/work/")
    node = target
    while node != root and node != node.parent:
        if node.is_symlink():
            raise WorkshopError("Linked output path or parent is not permitted")
        node = node.parent


def _atomic_save(target: Path, data: bytes, *, expected_hash: str | None) -> str:
    _safe_output_path(target)
    if target.is_symlink():
        raise WorkshopError("Linked output is not permitted")
    if target.exists():
        if expected_hash is None or _hash(target.read_bytes()) != expected_hash:
            raise WorkshopError("Output was edited externally; reload before replacing")
    elif expected_hash is not None:
        raise WorkshopError("Previously saved file disappeared")
    if target.parent.is_symlink():
        raise WorkshopError("Output directory is linked")
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".layout-", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if target.exists() and _hash(target.read_bytes()) != expected_hash:
            raise WorkshopError("Output was changed during the save")
        os.replace(tmp, target)
    finally:
        Path(tmp).unlink(missing_ok=True)
    return _hash(data)


def save_scene(scene: Scene, project: Path | str, *,
               expected_hash: str | None = None) -> tuple[Path, str]:
    root = workspace(project, create=True)
    scene.validate(root)
    dest = scene_file(root, scene.name)
    data = (json.dumps(scene.as_json(), ensure_ascii=False,
                       indent=2, sort_keys=True) + "\n").encode("utf8")
    if len(data) > MAX_SCENE_BYTES:
        raise WorkshopError("Scene metadata exceeds 1 MiB")
    if dest.exists() and expected_hash is not None:
        _safe_output_path(dest)
        previous = dest.read_bytes()
        if _hash(previous) != expected_hash:
            raise WorkshopError("Layout changed externally; reload before save")
        if previous != data:
            # Every successfully superseded set of positions remains locally
            # recoverable, entirely outside the game's asset package input.
            revision = dest.parent / "revisions" / (
                scene.name + "-" + _hash(previous)[:20] + ".scene.json")
            if not revision.exists():
                _atomic_save(revision, previous, expected_hash=None)
            elif _hash(revision.read_bytes()) != _hash(previous):
                raise WorkshopError("Saved layout revision was altered")
    return dest, _atomic_save(dest, data, expected_hash=expected_hash)


def layer_by_id(scene: Scene, item_id: str) -> Layer:
    return next((l for l in scene.layers if l.id == item_id), None) or (
        _missing_layer(item_id)
    )


def _missing_layer(item_id):
    raise WorkshopError("Layer not found: " + str(item_id))


def add_layer(scene: Scene, project: Path | str, source: str, *,
              x: float | None = None, y: float | None = None) -> Layer:
    root = workspace(project)
    asset = _relative(source).as_posix()
    if len(scene.layers) >= MAX_LAYERS:
        raise WorkshopError("Layer count exceeds 256")
    path = _existing(root, asset)
    if path.suffix.lower() != ".png":
        raise WorkshopError("Only PNGs can be placed in the layout")
    with Image.open(path) as img:
        width, height = img.size
    layer = Layer(
        id=uuid.uuid4().hex, asset=asset,
        x=float(x if x is not None else max(0, (scene.width-width)/2)),
        y=float(y if y is not None else max(0, (scene.height-height)/2)),
        width=width, height=height, name=path.stem,
    )
    layer.validate(root)
    scene.layers.append(layer)
    return layer


def duplicate_layer(scene: Scene, item_id: str, *,
                    dx: float = 20, dy: float = 20) -> Layer:
    original = layer_by_id(scene, item_id)
    if len(scene.layers) >= MAX_LAYERS:
        raise WorkshopError("Maximum of 256 scene layers")
    new = replace(original, id=uuid.uuid4().hex,
                  x=original.x+dx, y=original.y+dy,
                  name=original.name+" Kopie", locked=False)
    place = scene.layers.index(original)
    scene.layers.insert(place+1, new)
    return new


def move_layer(scene: Scene, item_id: str, dx: float, dy: float, *,
               snap: int = 1) -> Layer:
    item = layer_by_id(scene, item_id)
    if item.locked:
        raise WorkshopError("Layer is locked")
    if type(snap) is not int or not 1 <= snap <= 128:
        raise WorkshopError("Invalid grid increment")
    # A click without actual movement must never shift an image just because
    # its saved coordinates are off-grid. Preserve the untouched axis too.
    if abs(dx)>1e-9:
        item.x = round(_finite(item.x+dx, "x") / snap) * snap
    if abs(dy)>1e-9:
        item.y = round(_finite(item.y+dy, "y") / snap) * snap
    return item


def set_geometry(scene: Scene, item_id: str, **changes) -> Layer:
    layer = layer_by_id(scene, item_id)
    if layer.locked and set(changes) - {"locked", "visible"}:
        raise WorkshopError("Locked layer cannot be transformed")
    fields = set(Layer.__dataclass_fields__) - {"id", "asset"}
    if set(changes) - fields:
        raise WorkshopError("Unknown transform parameter")
    result = replace(layer, **changes)
    result.validate(Path("."), inspect_file=False)
    scene.layers[scene.layers.index(layer)] = result
    return result


def resize_handle(scene: Scene, item_id: str, grip: str,
                  dx: float, dy: float, *, keep_ratio: bool = False,
                  snap: int = 1) -> Layer:
    """Resize by canvas handles; preserve image geometry and anchor placement.

    Pointer deltas are converted into the rotated layer's own axes. The
    opposite grip remains stationary for unrotated images. No source PNG
    is stretched until preview/render/export uses the stored dimensions.
    """
    old = layer_by_id(scene, item_id)
    if old.locked:
        raise WorkshopError("Layer is locked")
    if grip not in {"nw", "n", "ne", "w", "e", "sw", "s", "se"}:
        raise WorkshopError("Invalid resize grip")
    if type(snap) is not int or not 1 <= snap <= 128:
        raise WorkshopError("Invalid grid")
    theta = math.radians(old.rotation)
    c, s = math.cos(theta), math.sin(theta)
    local_dx, local_dy = c*dx+s*dy, -s*dx+c*dy
    dw = (-local_dx if "w" in grip else local_dx if "e" in grip else 0.)
    dh = (-local_dy if "n" in grip else local_dy if "s" in grip else 0.)
    if keep_ratio:
        factors = []
        if "w" in grip or "e" in grip:
            factors.append((old.width+dw)/old.width)
        if "n" in grip or "s" in grip:
            factors.append((old.height+dh)/old.height)
        scale = max(.01, max(factors,key=lambda value: abs(value-1))) if factors else 1.
        dw,dh = old.width*(scale-1),old.height*(scale-1)
    new_w = max(1,min(MAX_LAYER_SIDE,round((old.width+dw)/snap)*snap))
    new_h = max(1,min(MAX_LAYER_SIDE,round((old.height+dh)/snap)*snap))
    if new_w*new_h > MAX_PIXELS:
        raise WorkshopError("Resized layer exceeds pixel budget")
    shift_x = old.width-new_w if "w" in grip else 0
    shift_y = old.height-new_h if "n" in grip else 0
    # Convert the edge shift back into canvas space.
    global_dx = c*shift_x-s*shift_y
    global_dy = s*shift_x+c*shift_y
    ax,ay=ANCHORS[old.anchor]
    new_origin_x,new_origin_y=origin_of(old)
    return set_geometry(scene,item_id,width=new_w,height=new_h,
        x=new_origin_x+global_dx+new_w*ax,
        y=new_origin_y+global_dy+new_h*ay)


def remove_layers(scene: Scene, ids: set[str]) -> None:
    if any(layer.locked for layer in scene.layers if layer.id in ids):
        raise WorkshopError("Cannot delete locked layers")
    scene.layers[:] = [layer for layer in scene.layers if layer.id not in ids]


def reorder(scene: Scene, item_id: str, direction: int) -> None:
    current = layer_by_id(scene, item_id)
    if current.locked:
        raise WorkshopError("Locked layer cannot change order")
    index = scene.layers.index(current)
    if direction not in (-1, 1):
        raise WorkshopError("Invalid order change")
    neighbor = index + direction
    if not 0 <= neighbor < len(scene.layers):
        return
    scene.layers[index], scene.layers[neighbor] = scene.layers[neighbor], current


def origin_of(layer: Layer) -> tuple[float, float]:
    ax, ay = ANCHORS[layer.anchor]
    return (layer.x - layer.width*ax, layer.y - layer.height*ay)


def pivot_of(layer: Layer) -> tuple[float, float]:
    origin_x, origin_y = origin_of(layer)
    return (origin_x+layer.width*layer.pivot_x,
            origin_y+layer.height*layer.pivot_y)


def transform_point(layer: Layer, local_x: float, local_y: float) -> tuple[float, float]:
    origin_x, origin_y = origin_of(layer)
    px, py = pivot_of(layer)
    angle = math.radians(layer.rotation)
    c, s = math.cos(angle), math.sin(angle)
    x, y = origin_x+local_x-px, origin_y+local_y-py
    return (px+c*x-s*y, py+s*x+c*y)


def rotated_corners(layer: Layer) -> tuple[tuple[float,float], ...]:
    return tuple(transform_point(layer,x,y) for x,y in (
        (0,0),(layer.width,0),(layer.width,layer.height),(0,layer.height),
    ))


def hit_test(scene: Scene, x: float, y: float) -> str | None:
    for layer in reversed(scene.layers):
        if not layer.visible:
            continue
        ox, oy = origin_of(layer)
        px, py = pivot_of(layer)
        c = math.cos(math.radians(layer.rotation))
        s = math.sin(math.radians(layer.rotation))
        dx, dy = x-px, y-py
        local_x = px+c*dx+s*dy-ox
        local_y = py-s*dx+c*dy-oy
        if 0 <= local_x <= layer.width and 0 <= local_y <= layer.height:
            return layer.id
    return None


def _render_layer(layer: Layer, source: Path, scene_width: int,
                  scene_height: int) -> tuple[Image.Image, tuple[int,int]] | None:
    if not layer.visible:
        return None
    if source.is_symlink() or not source.is_file():
        raise WorkshopError("Missing or linked layer image")
    with Image.open(source) as original:
        if original.width*original.height > MAX_PIXELS:
            raise WorkshopError("Layer bitmap exceeds pixel limit")
        image = original.convert("RGBA")
    if image.size != (layer.width,layer.height):
        image = image.resize((layer.width,layer.height),Image.Resampling.LANCZOS)
    if layer.opacity < 255:
        image.putalpha(image.getchannel("A").point(
            lambda alpha: (alpha*layer.opacity)//255
        ))
    corners = rotated_corners(layer)
    lo_x = max(0, math.floor(min(x for x,_ in corners)) - 2)
    lo_y = max(0, math.floor(min(y for _,y in corners)) - 2)
    hi_x = min(scene_width, math.ceil(max(x for x,_ in corners)) + 2)
    hi_y = min(scene_height, math.ceil(max(y for _,y in corners)) + 2)
    if lo_x >= hi_x or lo_y >= hi_y:
        return None
    angle = math.radians(layer.rotation)
    c,s = math.cos(angle),math.sin(angle)
    px,py = pivot_of(layer)
    local_px = layer.width*layer.pivot_x
    local_py = layer.height*layer.pivot_y
    # Output pixel -> scaled source pixel; custom pivot is preserved exactly.
    params = (
        c,s,local_px+c*(lo_x-px)+s*(lo_y-py),
        -s,c,local_py-s*(lo_x-px)+c*(lo_y-py),
    )
    patch = image.transform((hi_x-lo_x,hi_y-lo_y),
        Image.Transform.AFFINE,params,resample=Image.Resampling.BICUBIC)
    return patch,(lo_x,lo_y)


def render_scene(scene: Scene, project: Path | str) -> Image.Image:
    root = workspace(project)
    scene.validate(root)
    output = Image.new("RGBA",(scene.width,scene.height),scene.background)
    for layer in scene.layers:
        if layer.visible and layer.opacity:
            result = _render_layer(
                layer, _existing(root,layer.asset), scene.width, scene.height
            )
            if result is not None:
                image,position = result
                output.alpha_composite(image, dest=position)
    return output


def render_preview(scene: Scene, project: Path | str, *,
                   max_width: int, max_height: int) -> tuple[Image.Image, float]:
    scene.validate(workspace(project))
    if max_width < 10 or max_height < 10:
        raise WorkshopError("Preview viewport is too small")
    ratio = min(1., max_width/scene.width, max_height/scene.height)
    if ratio >= 0.999:
        return render_scene(scene,project), 1.
    # Preview is a resized copy of the EXACT composed export image, rather
    # than rounding each element's x/y/width and introducing one-pixel drift.
    # The Canvas selection handles still use the original floating coordinates.
    full=render_scene(scene,project)
    size=(max(1,round(scene.width*ratio)),
          max(1,round(scene.height*ratio)))
    return full.resize(size,Image.Resampling.LANCZOS), ratio


def _asset_hashes(scene: Scene, root: Path) -> list[dict]:
    found = {}
    for layer in scene.layers:
        if layer.asset not in found:
            source = _existing(root, layer.asset)
            found[layer.asset] = _hash(source.read_bytes())
    return [{"path":key,"sha256":value} for key,value in sorted(found.items())]


def export_composition(scene: Scene, project: Path | str, *,
                       resource_name: str, scene_sha256: str) -> dict:
    """Bake all layer transforms into a version-free, package-ready HUD PNG.

    The manifest is outside the package inputs. The only accepted overwrite
    is a previous export with an intact own output hash (never user artwork).
    """
    root = workspace(project)
    scene.validate(root)
    _check_saved_scene(scene,root,scene_sha256)
    name = filename(resource_name)
    relative = _RESOURCE + name
    output = root / relative
    metadata = _metadata_dir(root) / "exports" / (name+".json")
    _safe_output_path(output)
    _safe_output_path(metadata)
    if output.is_symlink() or metadata.is_symlink():
        raise WorkshopError("Export destination is linked")
    old_manifest = None
    expected = None
    if output.exists():
        if not metadata.is_file():
            raise WorkshopError("A user image already owns this resource key")
        old_manifest = json.loads(metadata.read_text("utf8"))
        if old_manifest.get("resource") != relative:
            raise WorkshopError("Export provenance does not match the resource key")
        expected = old_manifest.get("png_sha256")
        if not isinstance(expected,str) or _hash(output.read_bytes()) != expected:
            raise WorkshopError("Export image was modified externally")
    elif metadata.exists():
        raise WorkshopError("Export provenance exists but the PNG is missing")
    # Export must never overwrite an input image, even one inserted earlier.
    if any(layer.asset == relative for layer in scene.layers):
        raise WorkshopError("The composition cannot overwrite an input layer")
    asset_hashes = _asset_hashes(scene,root)
    rendered = render_scene(scene,root)
    if asset_hashes != _asset_hashes(scene,root):
        raise WorkshopError("A source image changed during layout rendering")
    stream = BytesIO()
    rendered.save(stream,format="PNG")
    png = stream.getvalue()
    manifest = {
        "schema": EXPORT_SCHEMA, "resource": relative,
        "scene_name": scene.name, "scene_sha256": scene_sha256,
        "canvas": [scene.width,scene.height],
        "png_sha256": _hash(png),
        "assets": asset_hashes,
        "layers": [layer.as_json() for layer in scene.layers],
        "note": "Positions and transforms baked into PNG; XAML placement of the "
                "composite resource must be mapped against the target game.",
    }
    if output.exists():
        _atomic_save(output,png,expected_hash=expected)
    else:
        _atomic_save(output,png,expected_hash=None)
    serialized=(json.dumps(manifest,indent=2,ensure_ascii=False)+"\n").encode("utf8")
    old_meta_hash = (_hash(metadata.read_bytes()) if metadata.is_file() else None)
    _atomic_save(metadata,serialized,expected_hash=old_meta_hash)
    return {"png":str(output),"manifest":str(metadata),
            "resource":relative,"sha256":_hash(png),
            "scene_sha256":scene_sha256, "layers":len(scene.layers)}


def _check_saved_scene(scene: Scene, root: Path,
                       scene_sha256: str) -> None:
    """Tie a baked export to the current saved, unmodified layout JSON."""
    if not isinstance(scene_sha256,str) or not re.fullmatch(
            r"[a-f0-9]{64}",scene_sha256):
        raise WorkshopError("A saved layout checksum is required")
    stored,actual=load_scene(root,scene.name)
    if actual!=scene_sha256 or stored.as_json()!=scene.as_json():
        raise WorkshopError(
            "Saved layout differs from current positions; save and re-export")


def audit_export(scene: Scene, project: Path | str, *,
                 scene_sha256: str) -> dict:
    """Confirm the visible layout, latest input pixels and baked PNG agree."""
    root = workspace(project)
    scene.validate(root)
    _check_saved_scene(scene,root,scene_sha256)
    if not scene.target_resource:
        raise WorkshopError("Layout has no exported target resource")
    name = Path(scene.target_resource).name
    output = root / scene.target_resource
    manifest_file = _metadata_dir(root) / "exports" / (name + ".json")
    _safe_output_path(output)
    _safe_output_path(manifest_file)
    if not output.is_file() or not manifest_file.is_file():
        raise WorkshopError("The latest layout has not been exported")
    if manifest_file.stat().st_size > MAX_SCENE_BYTES:
        raise WorkshopError("Export manifest too large")
    try:
        meta = json.loads(manifest_file.read_text("utf8"))
    except (UnicodeError,ValueError,OSError) as exc:
        raise WorkshopError("Export manifest cannot be parsed") from exc
    if (meta.get("schema") != EXPORT_SCHEMA
            or meta.get("resource") != scene.target_resource
            or meta.get("scene_sha256") != scene_sha256
            or meta.get("layers") != [l.as_json() for l in scene.layers]):
        raise WorkshopError("Export is stale; save and re-export the current layout")
    if _hash(output.read_bytes()) != meta.get("png_sha256"):
        raise WorkshopError("Export PNG has been changed externally")
    if meta.get("assets") != _asset_hashes(scene,root):
        raise WorkshopError("An input PNG changed; re-export the layout")
    return meta


def prepare_package_source(
    scene: Scene, project: Path | str, *, scene_sha256: str,
    include_patches: bool = False,
) -> Path:
    """Stage an immutable, isolated asset-only package input.

    The regular package builder is never pointed at raw editable layers.
    This export holds only the baked, position-correct composite and optional
    explicitly validated user-provided XAML patches. Source game untouched.
    """
    from se_asset_package import _discover
    import shutil

    root = workspace(project)
    meta = audit_export(scene,root,scene_sha256=scene_sha256)
    source_png = root / scene.target_resource
    expected = {scene.target_resource:meta["png_sha256"]}
    if include_patches:
        parent = root / "Patches" / "Assets" / "GUI"
        if parent.exists():
            _safe_output_path(parent)
            for patch in sorted(parent.rglob("*.xaml")):
                if patch.is_symlink():
                    raise WorkshopError("Linked XAML patch")
                rel = patch.relative_to(root).as_posix()
                from hud_menu_workspace import _relative
                _relative(rel,patch=True)
                expected[rel] = _hash(patch.read_bytes())

    # The output identity includes actual patch contents, not only the
    # boolean "include patches". Editing one XAML creates a new clean source
    # folder instead of reusing an obsolete staged package.
    package_id = _hash(json.dumps(
        sorted(expected.items()),separators=(",",":")
    ).encode("utf8"))[:20]
    code = scene.name + "-" + package_id
    base = WORK.resolve() / "hud-menu-composite-sources"
    target = base / code
    _safe_output_path(target)

    def validate_bundle(folder: Path) -> None:
        _safe_output_path(folder)
        if folder.is_symlink() or not folder.is_dir():
            raise WorkshopError("Invalid prepared package directory")
        paths=[p for p in folder.rglob("*") if p.is_file()]
        present={p.relative_to(folder).as_posix():p for p in paths}
        if set(present) != set(expected):
            raise WorkshopError("Prepared package differs from recorded export")
        for name,recorded_hash in expected.items():
            file=present[name]
            _safe_output_path(file)
            if file.is_symlink() or _hash(file.read_bytes()) != recorded_hash:
                raise WorkshopError("Prepared package differs from recorded export")
        # The regular asset-packager validates actual formats after provenance.
        files = _discover(folder)
        if {relative:digest for relative,_,_,digest in files} != expected:
            raise WorkshopError("Prepared package differs from recorded export")

    if target.exists():
        validate_bundle(target)
        return target
    base.mkdir(parents=True,exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".layout-package-",dir=base))
    try:
        for relative,digest in expected.items():
            source = root / relative
            from hud_menu_workspace import _relative
            _relative(relative,patch=relative.startswith("Patches/"))
            source_path = _existing(root,relative,patch=relative.startswith("Patches/"))
            dest = temporary / relative
            dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(source_path,dest)
            if _hash(dest.read_bytes()) != digest:
                raise WorkshopError("Package source changed during copying")
        validate_bundle(temporary)
        if target.exists():
            validate_bundle(target)
        else:
            os.rename(temporary,target)
        return target
    finally:
        if temporary.exists():
            shutil.rmtree(temporary,ignore_errors=True)


class History:
    """Pure scene undo/redo. One drag gesture commits one snapshot."""

    def __init__(self, scene: Scene, *, limit=80):
        self.scene = scene.clone()
        self._before: list[dict] = []
        self._after: list[dict] = []
        self.limit = max(1, min(300, int(limit)))

    def commit(self, old: Scene) -> bool:
        before = old.as_json()
        if before == self.scene.as_json():
            return False
        self._before.append(before)
        del self._before[:-self.limit]
        self._after.clear()
        return True

    def undo(self) -> bool:
        if not self._before:
            return False
        self._after.append(self.scene.as_json())
        self.scene = scene_from_json(self._before.pop(),None)
        return True

    def redo(self) -> bool:
        if not self._after:
            return False
        self._before.append(self.scene.as_json())
        self.scene = scene_from_json(self._after.pop(),None)
        return True

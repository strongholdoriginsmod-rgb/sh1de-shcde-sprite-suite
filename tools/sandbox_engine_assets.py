"""Local original-game sprite access for authoritative engine frame IDs.

Read-only Unity archives are decoded lazily. Missing ordinary catalog frames
are exported into the existing *derived* Crusader catalog so pixel editing can
use them. No original game resources and no authored working copies are changed.
"""
from __future__ import annotations
from pathlib import Path
import copy
import hashlib
import json
import os
import tempfile

import asset_katalog as catalog
from sandkasten import Frame, FrameSource
from stronghold_europe_de.sandbox.native_runtime import load_contract, sha256
from stronghold_europe_de.sandbox.save_target_guard import guard_existing_json


def _validate_original_catalog_index(data, group):
    """Never replace malformed, foreign or future-version asset catalogs."""
    allowed = {"schema_version", "group", "game", "frames"}
    if (not isinstance(data, dict) or set(data) - allowed or
            type(data.get("schema_version")) is not int or
            data["schema_version"] != 1 or
            data.get("group") != group or
            data.get("game") != "crusader"):
        raise ValueError("Unknown native source catalog schema/group")
    frames = data.get("frames")
    if not isinstance(frames,list) or len(frames)>100_000:
        raise ValueError("Invalid or excessively large native index")
    record_fields = {
        "name","file","width","height","pivot_x","pivot_y",
        "pixels_per_unit","native_source"
    }
    names = set()
    for entry in frames:
        if (not isinstance(entry,dict) or set(entry)-record_fields or
                not isinstance(entry.get("name"),str) or
                not isinstance(entry.get("file"),str)):
            raise ValueError("Unknown native source frame fields")
        name, filename = entry["name"],entry["file"]
        if (not name or name in names or not filename.endswith(".png") or
                Path(filename).name!=filename or "/" in filename or
                "\\" in filename):
            raise ValueError("Duplicate or unsafe native source frame entry")
        names.add(name)


class EngineSpriteAssets:
    def __init__(self, map_path):
        self.data_dir = Path(map_path).resolve().parents[2]
        self.asset_path = self.data_dir / "resources.assets"
        self.original_only = False
        self._environment = None
        self._readers = None
        self._original_frames = {}
        self._indices = {}
        self._delivered_attempted = set()
        self._source_hash = None
        self.missing = set()
        self.exported = 0
        self.contract = load_contract()
        self._groups = {
            row['group']:row for group in self.contract['gm_files'].values() for row in group
        }

    def invalidate(self):
        self._indices.clear()

    def _index(self, directory):
        file = directory / "index.json"
        try:
            signature = (file.stat().st_mtime_ns, file.stat().st_size)
        except OSError:
            return {}
        key = str(file)
        if key not in self._indices or self._indices[key][0] != signature:
            raw = catalog.index_of(directory)
            self._indices[key] = (signature, {str(f['name']): f for f in raw.get('frames', [])})
        return self._indices[key][1]

    def _has(self, directory, name):
        record = self._index(directory).get(name)
        return record is not None and (directory / record['file']).is_file()

    def _initialize_unity(self):
        if self._readers is not None:
            return
        import UnityPy
        if not self.asset_path.is_file():
            raise FileNotFoundError(f"Original-Spritearchiv fehlt: {self.asset_path}")
        # Library lookup and original resources belong to the same explicitly
        # ABI-validated local game installation, not arbitrary user JSON paths.
        self._source_hash = sha256(self.asset_path)
        self._environment = UnityPy.load(str(self.asset_path))
        readers = {}
        for obj in self._environment.objects:
            if obj.type.name == 'Sprite':
                name = obj.peek_name()
                if name in readers:
                    raise ValueError(f"Doppelter Original-Spritename: {name}")
                readers[name] = obj
        self._readers = readers

    def original(self, group, number):
        key = (group, number)
        if key in self._original_frames:
            return self._original_frames[key]
        spec = self._groups.get(group)
        if spec is None:
            self.missing.add(key)
            return None
        self._initialize_unity()
        prefix = spec['resource_prefix']
        name = f"{prefix}-{number}" if spec['dash_format'] else f"{prefix} {number:03d}"
        reader = self._readers.get(name)
        if reader is None:
            self.missing.add(key)
            self._original_frames[key] = None
            return None
        sprite = reader.read()
        image = sprite.image.convert('RGBA')
        pivot = sprite.m_Pivot
        # SpriteHelper returns the actual Unity-trimmed RGBA canvas; the
        # original normalized pivot is interpreted on that canvas as elsewhere
        # in Sprite Suite. Atlas rotations/tight packing are handled by UnityPy.
        foot = (float(pivot.x)*image.width, (1.0-float(pivot.y))*image.height)
        result = Frame(image, None, foot, "crusader-original")
        self._original_frames[key] = result
        return result

    def _export_missing(self, group, number, frame):
        name = catalog.native_name(group, number)
        folder = catalog.side_dir('crusader', group)
        if self._has(folder, name):
            return
        # catalog.index_of() uses a deliberately forgiving loader intended
        # for *reading*. For WRITES it could silently replace a damaged or
        # unrelated index.json with a default blank catalog.
        index_path=folder/'index.json'
        guard_existing_json(
            index_path, lambda raw:_validate_original_catalog_index(raw,group),
            ValueError, "Abgeleiteter Originalsprite-Katalog"
        )
        folder.mkdir(parents=True, exist_ok=True)
        # Some callers cache the parsed dictionary: a failed export must not
        # append a phantom frame to that shared in-memory index.
        data = copy.deepcopy(catalog.index_of(folder))
        data.setdefault('schema_version', 1)
        data.setdefault('group', group)
        data.setdefault('game', 'crusader')
        data.setdefault('frames', [])
        existing = next((entry for entry in data['frames'] if entry.get('name') == name), None)
        if existing is not None:
            # Preserve a pre-existing, possibly authored index. Original-only
            # preview can still use the direct in-memory frame without writes.
            return
        filename = name + '.png'
        dest = folder / filename
        if dest.exists():
            return  # never replace an unrelated pre-existing PNG
        width,height = frame.image.size
        record = {
            'name':name, 'file':filename, 'width':width, 'height':height,
            'pivot_x':frame.foot[0]/width, 'pivot_y':1-frame.foot[1]/height,
            'pixels_per_unit':64,
            'native_source':{'resource':str(self.asset_path),'sha256':self._source_hash},
        }
        created_png=False
        try:
            fd,temp = tempfile.mkstemp(dir=folder,prefix='.native-',suffix='.png')
            os.close(fd)
            try:
                frame.image.save(temp, 'PNG')
                os.replace(temp,dest)
                created_png=True
            finally:
                if os.path.exists(temp):os.unlink(temp)
            data['frames'].append(record)
            fd,temp = tempfile.mkstemp(dir=folder,prefix='.native-index-',suffix='.json')
            try:
                with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as output:
                    json.dump(data,output,ensure_ascii=False,indent=2)
                    output.write('\n');output.flush();os.fsync(output.fileno())
                os.replace(temp,index_path)
            finally:
                if os.path.exists(temp):os.unlink(temp)
            created_png=False  # Image AND metadata now committed.
        finally:
            if created_png:
                # The new PNG is ours. On a failed index write it cannot
                # remain as an unregistered file blocking all future retries.
                dest.unlink(missing_ok=True)
        self._indices.pop(str(index_path),None)
        self.exported += 1

    def frame(self, group, number, source):
        if self.original_only:
            return self.original(group, number)
        name = catalog.native_name(group, number)
        work = catalog.work_dir(group)
        delivered = catalog.side_dir('geliefert', group)
        original = catalog.side_dir('crusader', group)
        if group not in self._delivered_attempted:
            self._delivered_attempted.add(group)
            if not (delivered/'index.json').is_file():
                try:
                    catalog.ensure_side(group,'geliefert')
                except (OSError, ValueError, SystemExit):
                    pass
        if self._has(delivered,name) or self._has(original,name):
            return source.frame(group,name)
        # Missing-atlas fallback must not attempt a failing per-frame external
        # export requiring an unrelated installations.local.toml.
        image = self.original(group,number)
        if image is not None:
            self._export_missing(group,number,image)
            source._indices.pop(('crusader', group), None)
            source._cache.pop((group, name), None)
            if self._has(work,name):
                # A saved pixel edit takes priority as it does in FrameSource.
                entry = self._index(work)[name]
                return source._load(work,entry,'arbeit')
        return image

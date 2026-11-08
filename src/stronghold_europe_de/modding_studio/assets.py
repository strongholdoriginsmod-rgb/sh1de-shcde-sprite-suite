"""Read-only map/AIV/Lord/audio/modpack analysis; never installs game files."""
from __future__ import annotations

from hashlib import sha256
import io
from pathlib import Path
import wave

from .catalog import version_tuple
from .report import (
    Report, analyze_items, exact_object, integer, one_of, text,
)
from .safety import (
    StudioError, child_path, file_sha, is_link, read_file, read_json,
    relative_path, require_id, require_sha, json_bytes,
)

PROTECTED_BINARIES = frozenset({
    "bepinex.dll", "shcdese.dll", "apishared.dll", "apishared.content.dll",
    "0harmony.dll", "unityengine.dll", "assembly-csharp.dll",
    "redbird.core.dll", "redbird.x64.dll", "r3.dll", "nlua.dll",
})
AUDIO_EVENTS = frozenset({
    "mission_start", "unit_settled", "building_built",
    "victory", "defeat", "attack", "selection",
})
MAX_INSPECTED_FILES = 2500


def maps(section: dict, workspace: Path) -> Report:
    report = Report("maps")
    resources = []
    def check(raw: dict, index: int) -> None:
        label = f"maps.resources[{index}]"
        exact_object(raw, {"id", "path", "format", "sha256"}, label)
        path = relative_path(raw["path"], label + ".path")
        format_ = one_of(
            raw["format"], {"map", "trail", "aivjson"}, label + ".format"
        )
        if not path.endswith("." + format_):
            raise StudioError(label + " path extension and declared format differ")
        expected = require_sha(raw["sha256"], label + ".sha256")
        payload = read_file(workspace, path)
        actual = sha256(payload).hexdigest()
        if expected != actual:
            raise StudioError(label + " source SHA-256 pin differs from actual bytes")
        if format_ == "aivjson":
            decoded = read_json(workspace, path)
            if type(decoded) not in {dict, list}:
                raise StudioError("DE AIVJSON must be a JSON object or array")
        resources.append({
            "id": raw["id"], "format": format_, "path": path,
            "sha256": actual, "bytes": len(payload),
        })
        if format_ != "aivjson":
            report.add(
                "REVIEW", "MAP_BINARY_NOT_PARSED",
                "Source digest verified; PKWARE-DCL sections/CRC, keeps and "
                "placement layers require Serp MapParser or TrailEditor.",
                path,
            )
        else:
            report.add(
                "REVIEW", "AIVJSON_NOT_NATIVE_PROVEN",
                "JSON is readable, but DE AIV mapper/build-order semantics "
                "require the independently validated AIVParser.",
                path,
            )
    analyze_items(report, section["resources"], "resources", check)
    report.facts = {"resources": resources, "writes_original_sources": False}
    return report


def lords(section: dict, workspace: Path) -> Report:
    report = Report("lords")
    profiles = []
    def check(raw: dict, index: int) -> None:
        label = f"lords.profiles[{index}]"
        exact_object(
            raw, {"id", "name", "meta_path", "aiv_path", "media"}, label
        )
        name = text(raw["name"], label + ".name", 120)
        metadata = relative_path(raw["meta_path"], label + ".meta_path")
        if not metadata.endswith(".json"):
            raise StudioError("lord metadata must be JSON")
        info = read_json(workspace, metadata)
        if not isinstance(info, dict):
            raise StudioError(label + " lord metadata must be a JSON object")
        aiv = raw["aiv_path"]
        if aiv is not None:
            aiv = relative_path(aiv, label + ".aiv_path")
            if not aiv.endswith(".aivjson"):
                raise StudioError("only DE .aivjson, never HD .aiv or raw .baiv")
            content = read_json(workspace, aiv)
            if type(content) not in {dict, list}:
                raise StudioError(label + " AIVJSON has invalid JSON root")
        media = raw["media"]
        if not isinstance(media, list) or len(media) > 128:
            raise StudioError(label + ".media must contain at most 128 entries")
        results = []
        used = set()
        for i, item in enumerate(media):
            ml = f"{label}.media[{i}]"
            exact_object(item, {"path", "kind", "sha256"}, ml)
            path = relative_path(item["path"], ml + ".path")
            if path.casefold() in used:
                raise StudioError(ml + " repeated case-insensitive path")
            used.add(path.casefold())
            kind = one_of(item["kind"], {"image", "audio", "video"}, ml + ".kind")
            ext = path.rsplit(".", 1)[-1].lower()
            valid = {
                "image": {"png", "jpg", "jpeg"},
                "audio": {"wav", "ogg"},
                "video": {"webm", "mp4"},
            }
            if ext not in valid[kind]:
                raise StudioError(ml + " media extension does not match type")
            expected = require_sha(item["sha256"], ml + ".sha256")
            actual = file_sha(workspace, path)
            if actual != expected:
                raise StudioError(ml + " media SHA-256 identity changed")
            results.append({"path": path, "kind": kind, "sha256": actual})
        profiles.append({
            "id": raw["id"], "name": name, "meta_path": metadata,
            "aiv_path": aiv, "media": results,
        })
        report.add(
            "REVIEW", "LORD_RUNTIME_UNVERIFIED",
            "Files and hashes can be checked offline; serialized Lord identity, "
            "selected AIC, speech routing and actual runtime behavior require "
            "a separate loaded-game test.",
            raw["id"],
        )
    analyze_items(report, section["profiles"], "profiles", check)
    report.facts["profiles"] = profiles
    return report


def audio(section: dict, workspace: Path) -> Report:
    report = Report("audio")
    clips: dict[str, dict] = {}
    def clip_check(raw: dict, index: int) -> None:
        label = f"audio.clips[{index}]"
        exact_object(raw, {"id", "path", "sha256"}, label)
        path = relative_path(raw["path"], label + ".path")
        if not path.lower().endswith(".wav"):
            raise StudioError(label + " must be a RIFF .wav clip")
        expected = require_sha(raw["sha256"], label + ".sha256")
        payload = read_file(workspace, path, 64 * 1024 * 1024)
        if sha256(payload).hexdigest() != expected:
            raise StudioError(label + " source WAV SHA-256 changed")
        try:
            with wave.open(io.BytesIO(payload), "rb") as wav:
                channels = wav.getnchannels()
                rate = wav.getframerate()
                bits = wav.getsampwidth() * 8
                frames = wav.getnframes()
                compression = wav.getcomptype()
                decoded = wav.readframes(frames)
        except (wave.Error, EOFError, OSError) as exc:
            raise StudioError(label + " is not a readable WAV file") from exc
        if (
            channels not in {1, 2}
            or bits != 16
            or compression != "NONE"
            or not 8000 <= rate <= 192000
            or not 1 <= frames <= 192000 * 60 * 20
        ):
            raise StudioError(label + " is not bounded mono/stereo PCM16")
        if len(decoded) != frames * channels * 2:
            raise StudioError(label + " WAV PCM payload is truncated")
        clips[raw["id"]] = {
            "path": path, "sha256": expected, "sample_rate": rate,
            "channels": channels, "frames": frames, "bits": bits,
        }
    analyze_items(report, section["clips"], "clips", clip_check)
    cues = []
    def cue_check(raw: dict, index: int) -> None:
        label = f"audio.cues[{index}]"
        exact_object(
            raw, {"id", "clip_id", "event", "volume_percent", "cooldown_ticks"},
            label,
        )
        clip_id = require_id(raw["clip_id"], label + ".clip_id")
        if clip_id not in clips:
            raise StudioError(label + " references unknown or invalid clip")
        event = one_of(raw["event"], set(AUDIO_EVENTS), label + ".event")
        volume = integer(raw["volume_percent"], label + ".volume_percent", 0, 200)
        cooldown = integer(raw["cooldown_ticks"], label + ".cooldown_ticks", 0, 1_000_000)
        cues.append({
            "id": raw["id"], "clip_id": clip_id, "event": event,
            "volume_percent": volume, "cooldown_ticks": cooldown,
        })
    analyze_items(report, section["cues"], "cues", cue_check)
    report.facts = {"clips": clips, "cues": cues}
    if cues:
        report.add(
            "REVIEW", "SOUND_NATIVE_BRIDGE_NOT_CONNECTED",
            "WAV and cue preview only. APIShared SoundEvents need live source "
            "capability validation; submission does not prove audibility.",
        )
    return report


def workshop(section: dict, workspace: Path) -> Report:
    report = Report("workshop")
    mods: list[dict] = []
    used_guids: set[str] = set()
    def check(raw: dict, index: int) -> None:
        label = f"workshop.mods[{index}]"
        exact_object(
            raw, {"id", "guid", "version", "manifest_path", "requires"}, label
        )
        guid = text(raw["guid"], label + ".guid", 128)
        if guid.casefold() in used_guids:
            raise StudioError(label + " duplicate mod/plugin GUID")
        used_guids.add(guid.casefold())
        version_tuple(raw["version"])
        manifest_path = relative_path(raw["manifest_path"], label + ".manifest_path")
        if not manifest_path.endswith("info.json"):
            raise StudioError(label + " must point to an info.json")
        meta = read_json(workspace, manifest_path, 1024 * 1024)
        if type(meta) is not dict:
            raise StudioError(label + " info.json is not an object")
        if meta.get("GUID") != guid or meta.get("Version") != raw["version"]:
            raise StudioError(label + " manifest GUID/version does not match package")
        reqs = raw["requires"]
        if not isinstance(reqs, list) or len(reqs) > 64:
            raise StudioError(label + " must declare at most 64 dependencies")
        manifest_dependencies = meta.get("Dependencies", [])
        if not isinstance(manifest_dependencies, list):
            raise StudioError(label + " info.json Dependencies must be an array")
        actual_dependencies = []
        for dep_index, dep in enumerate(manifest_dependencies):
            if not isinstance(dep, dict) or not isinstance(dep.get("GUID"), str):
                raise StudioError(label + " info.json has an invalid dependency GUID")
            actual_dependencies.append(dep["GUID"])
        names = []
        for dep in reqs:
            name = text(dep, label + ".requires", 128)
            if name.casefold() == guid.casefold():
                raise StudioError(label + " cannot depend on itself")
            if name.casefold() in [n.casefold() for n in names]:
                raise StudioError(label + " duplicate dependency")
            names.append(name)
        if sorted(dep.casefold() for dep in names) != sorted(
            dep.casefold() for dep in actual_dependencies
        ):
            raise StudioError(
                label + " declared dependency identities differ from info.json"
            )
        folder = manifest_path.rpartition("/")[0]
        if not folder:
            raise StudioError(label + " package must live in a namespaced folder")
        origin = child_path(workspace, folder)
        if not origin.is_dir():
            raise StudioError(label + " plugin folder is missing")
        files = []
        count = 0
        try:
            paths = sorted(origin.rglob("*"))
        except (OSError, RuntimeError) as exc:
            raise StudioError(label + " package files cannot be enumerated") from exc
        if len(paths) > MAX_INSPECTED_FILES:
            raise StudioError(label + " too many package files")
        for path in paths:
            if is_link(path):
                raise StudioError(label + " package contains a linked entry")
            if path.is_dir():
                continue
            count += 1
            if not path.is_file():
                raise StudioError(label + " contains unsupported filesystem object")
            part = path.relative_to(workspace).as_posix()
            suffix = path.name.lower()
            if suffix in PROTECTED_BINARIES:
                raise StudioError(label + " includes protected shared/game DLL: " + suffix)
            if suffix.endswith(".dll"):
                report.add(
                    "REVIEW", "UNVERIFIED_DLL", "Custom DLL requires an independent "
                    "ABI/dependency/antimalware review", part,
                )
            if path.stat().st_size > 128 * 1024 * 1024:
                raise StudioError(label + " file exceeds bounded package size")
            files.append({
                "path": part, "bytes": path.stat().st_size,
                "sha256": file_sha(workspace, part),
            })
        mods.append({
            "id": raw["id"], "guid": guid, "version": raw["version"],
            "requires": names, "manifest_path": manifest_path,
            "file_count": count,
            "file_inventory_sha256": sha256(json_bytes(files)).hexdigest(),
        })
    analyze_items(report, section["mods"], "mods", check)
    available = {item["guid"].casefold() for item in mods}
    edges = {item["guid"].casefold(): [] for item in mods}
    for item in mods:
        key = item["guid"].casefold()
        for dependency in item["requires"]:
            dep = dependency.casefold()
            if dep not in available:
                report.add(
                    "REVIEW", "EXTERNAL_PLUGIN_DEPENDENCY",
                    "External dependency must be installed and version verified",
                    dependency,
                )
            else:
                edges[key].append(dep)
    visiting: set[str] = set()
    visited: set[str] = set()
    def visit(node: str) -> None:
        if node in visited:
            return
        if node in visiting:
            report.add("BLOCK", "DEPENDENCY_CYCLE", "plugin dependency cycle", node)
            return
        visiting.add(node)
        for dep in edges[node]:
            visit(dep)
        visiting.remove(node)
        visited.add(node)
    for node in sorted(edges):
        visit(node)
    report.facts = {
        "mods": mods, "external_dependencies": sorted(
            {dep for item in mods for dep in item["requires"]
             if dep.casefold() not in available}
        ),
        "installation": "disabled",
        "workshop_publishing": "requires_explicit_external_consent",
    }
    return report

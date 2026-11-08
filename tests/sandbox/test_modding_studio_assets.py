"""Synthetic source-integrity coverage for map, AIV, Lord, audio and modpack."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import io
import json
from pathlib import Path
import sys
import wave

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from stronghold_europe_de.modding_studio.engine import analyze
from stronghold_europe_de.modding_studio.model import project_template
from stronghold_europe_de.modding_studio.safety import (
    create_file, create_json, json_bytes, StudioError,
)


@pytest.fixture
def area(tmp_path: Path) -> tuple[Path, dict]:
    root = tmp_path / "safety"
    root.mkdir()
    return root, project_template("asset_studio", "Test Art")


def _codes(result, module):
    return {row["code"] for row in result["modules"][module]["findings"]}


def test_map_source_digest_is_verified_without_parsing_native_sections(area):
    root, p = area
    source = b"SHCDE synthetic mock map bytes, not a game map"
    create_file(root, "maps/test.map", source)
    p["modules"]["maps"]["resources"] = [{
        "id": "demo", "path": "maps/test.map", "format": "map",
        "sha256": sha256(source).hexdigest(),
    }]
    result = analyze(root, p)
    assert result["modules"]["maps"]["facts"]["resources"][0]["sha256"] == sha256(source).hexdigest()
    assert "MAP_BINARY_NOT_PARSED" in _codes(result, "maps")
    p["modules"]["maps"]["resources"][0]["sha256"] = "0" * 64
    assert result["status"] != "BLOCKED"
    assert analyze(root, p)["status"] == "BLOCKED"


def test_map_aivjson_is_distinct_from_hd_aiv_and_sav(area):
    root, p = area
    item = json_bytes({"unitSlots": []})
    create_file(root, "aiv/castle.aivjson", item)
    p["modules"]["maps"]["resources"] = [{
        "id": "castle", "path": "aiv/castle.aivjson",
        "format": "aivjson", "sha256": sha256(item).hexdigest(),
    }]
    assert analyze(root, p)["status"] == "REVIEW"
    p["modules"]["maps"]["resources"][0]["path"] = "aiv/castle.sav"
    assert analyze(root, p)["status"] == "BLOCKED"


def test_lord_media_and_aiv_identity(area):
    root, p = area
    create_json(root, "lords/lordmeta.json", {"name": "Demo Lord"})
    create_json(root, "lords/keep.aivjson", {"frames": []})
    png = b"not-real-media-used-only-for-hash-check"
    create_file(root, "lords/portrait.png", png)
    p["modules"]["lords"]["profiles"] = [{
        "id": "lord_one",
        "name": "Demo Lord",
        "meta_path": "lords/lordmeta.json",
        "aiv_path": "lords/keep.aivjson",
        "media": [{
            "path": "lords/portrait.png", "kind": "image",
            "sha256": sha256(png).hexdigest(),
        }],
    }]
    result = analyze(root, p)
    assert result["modules"]["lords"]["facts"]["profiles"][0]["id"] == "lord_one"
    p["modules"]["lords"]["profiles"][0]["media"][0]["sha256"] = "b" * 64
    assert analyze(root, p)["status"] == "BLOCKED"
    p["modules"]["lords"]["profiles"][0]["media"][0]["sha256"] = sha256(png).hexdigest()
    p["modules"]["lords"]["profiles"][0]["aiv_path"] = "lords/test.aiv"
    assert analyze(root, p)["status"] == "BLOCKED"


def _wav(bits: int = 16) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(bits // 8)
        audio.setframerate(22050)
        audio.writeframes(b"\x00" * 440)
    return buf.getvalue()


def test_audio_pcm16_source_clip_and_cue(area):
    root, p = area
    data = _wav()
    create_file(root, "sounds/announcement.wav", data)
    p["modules"]["audio"]["clips"] = [{
        "id": "announcement", "path": "sounds/announcement.wav",
        "sha256": sha256(data).hexdigest(),
    }]
    p["modules"]["audio"]["cues"] = [{
        "id": "announce", "clip_id": "announcement", "event": "mission_start",
        "volume_percent": 100, "cooldown_ticks": 100,
    }]
    result = analyze(root, p)
    clip = result["modules"]["audio"]["facts"]["clips"]["announcement"]
    assert clip["sample_rate"] == 22050
    assert clip["bits"] == 16
    assert "SOUND_NATIVE_BRIDGE_NOT_CONNECTED" in _codes(result, "audio")
    p["modules"]["audio"]["cues"][0]["clip_id"] = "missing"
    assert analyze(root, p)["status"] == "BLOCKED"


def test_audio_must_be_single_or_stereo_pcm16(area):
    root, p = area
    data = _wav(bits=8)
    create_file(root, "sounds/wrong.wav", data)
    p["modules"]["audio"]["clips"] = [{
        "id": "wrong", "path": "sounds/wrong.wav",
        "sha256": sha256(data).hexdigest(),
    }]
    assert "INVALID_ENTRY" in _codes(analyze(root, p), "audio")


def _mod(root: Path, ident: str, guid: str, requires=None):
    if requires is None:
        requires = []
    relative = f"mods/{ident}/info.json"
    create_json(
        root, relative,
        {"GUID": guid, "Version": "1.0.0",
         "Dependencies": [{"GUID": dep} for dep in requires]},
    )
    return {
        "id": ident, "guid": guid, "version": "1.0.0",
        "manifest_path": relative, "requires": requires,
    }


def test_workshop_manifest_dependencies_without_install(area):
    root, p = area
    p["modules"]["workshop"]["mods"] = [
        _mod(root, "alpha", "example.alpha", ["example.beta"]),
        _mod(root, "beta", "example.beta"),
    ]
    result = analyze(root, p)
    assert result["modules"]["workshop"]["facts"]["mods"][0]["guid"] == "example.alpha"
    assert result["status"] == "SOURCE_PASS"
    p["modules"]["workshop"]["mods"][1]["requires"] = ["example.alpha"]
    (root / "mods/beta/info.json").write_bytes(json_bytes({
        "GUID": "example.beta", "Version": "1.0.0",
        "Dependencies": [{"GUID": "example.alpha"}],
    }))
    assert "DEPENDENCY_CYCLE" in _codes(analyze(root, p), "workshop")


def test_workshop_protected_shared_dll_rejected(area):
    root, p = area
    p["modules"]["workshop"]["mods"] = [_mod(root, "alpha", "example.alpha")]
    create_file(root, "mods/alpha/BepInEx.dll", b"mock-protected")
    assert "INVALID_ENTRY" in _codes(analyze(root, p), "workshop")


def test_workshop_unknown_external_dependencies_not_assumed_installed(area):
    root, p = area
    p["modules"]["workshop"]["mods"] = [
        _mod(root, "alpha", "example.alpha", ["APIShared_Serp"]),
    ]
    report = analyze(root, p)
    assert report["status"] == "REVIEW"
    assert "EXTERNAL_PLUGIN_DEPENDENCY" in _codes(report, "workshop")


def test_workshop_duplicate_guid_is_blocking(area):
    root, p = area
    p["modules"]["workshop"]["mods"] = [
        _mod(root, "alpha", "example.alpha"),
        _mod(root, "beta", "EXAMPLE.alpha"),
    ]
    assert "INVALID_ENTRY" in _codes(analyze(root, p), "workshop")


def test_audio_truncated_pcm16_payload_is_rejected(area):
    root, project = area
    incomplete = _wav()[:-2]
    create_file(root, "sounds/truncated.wav", incomplete)
    project["modules"]["audio"]["clips"] = [{
        "id": "bad_wav", "path": "sounds/truncated.wav",
        "sha256": sha256(incomplete).hexdigest(),
    }]
    result = analyze(root, project)
    assert result["status"] == "BLOCKED"
    assert "INVALID_ENTRY" in _codes(result, "audio")


def test_workshop_refuses_dependency_drift_between_project_and_info(area):
    root, project = area
    project["modules"]["workshop"]["mods"] = [
        _mod(root, "alpha", "example.alpha", ["APIShared_Serp"]),
    ]
    project["modules"]["workshop"]["mods"][0]["requires"] = []
    result = analyze(root, project)
    assert result["status"] == "BLOCKED"
    assert "INVALID_ENTRY" in _codes(result, "workshop")

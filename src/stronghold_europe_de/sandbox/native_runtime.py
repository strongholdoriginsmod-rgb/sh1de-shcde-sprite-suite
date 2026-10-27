"""Read-only graphics decisions from the user's installed SHCDE engine.

The native DLL is never copied into the project and is used only in a short-
lived subprocess. A temporary MAP COPY is loaded in editor/paused mode; no
save or game-action entrypoint is ever called. Unknown DLL builds are refused.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "config" / "sandbox-native-render-contract-v1.json"
RECORD_WORDS = 21
MAX_RECORDS = 700000
MAX_BYTES = MAX_RECORDS * RECORD_WORDS * 2
SNAPSHOT_SCHEMA = "sprite-suite.native-render-snapshot.v1"
CAPTURE_REVISION = "paused-editor-full-map-1"


class NativeRuntimeError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_contract(path=CONTRACT):
    try:
        content = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise NativeRuntimeError(f"Engine-Vertrag nicht lesbar: {exc}") from exc
    if not isinstance(content, dict) or content.get("schema") != "sprite-suite.native-render-contract.v1":
        raise NativeRuntimeError("Unbekanntes Engine-ABI-Format")
    for field in ("dll_sha256", "managed_sha256"):
        if not isinstance(content.get(field), str) or not re.fullmatch(r"[0-9a-f]{64}", content[field]):
            raise NativeRuntimeError("Original-Engine-Prüfsumme fehlt im ABI-Vertrag")
    abi = content.get("abi")
    if (not isinstance(abi, dict) or abi.get("entry_shorts") != RECORD_WORDS or
            abi.get("array_shorts") != 14700000 or abi.get("max_entries") != MAX_RECORDS or
            abi.get("pixels_per_unit") != 64 or abi.get("height_divisor") != 32):
        raise NativeRuntimeError("Unbekannte Grafik-Befehlsgeometrie")
    groups = content.get("gm_files")
    if not isinstance(groups, dict) or not 1 <= len(groups) <= 512:
        raise NativeRuntimeError("Ungültige Engine-Spritegruppen")
    for gm, entries in groups.items():
        if not isinstance(gm, str) or not gm.isascii() or not gm.isdecimal() or not 0 <= int(gm) < 512:
            raise NativeRuntimeError("Ungültige Engine-GM-Nummer")
        if not isinstance(entries, list) or not 1 <= len(entries) <= 4:
            raise NativeRuntimeError("Ungültige Engine-Atlasregistrierung")
        offsets = []
        for entry in entries:
            if not isinstance(entry, dict):
                raise NativeRuntimeError("Ungültiger Engine-Atlaseintrag")
            for key in ("group", "resource_prefix"):
                if not isinstance(entry.get(key), str) or not re.fullmatch(r"[A-Za-z0-9_ -]{1,90}", entry[key]):
                    raise NativeRuntimeError("Unsicherer Spritegruppen-/Ressourcenname")
            for key in ("first_runtime_frame", "nominal_frames"):
                if type(entry.get(key)) is not int or not 0 <= entry[key] <= 100000:
                    raise NativeRuntimeError("Ungültiger Engine-Atlasindex")
            offsets.append(entry["first_runtime_frame"])
        if offsets != sorted(set(offsets), reverse=True):
            raise NativeRuntimeError("Engine-Atlasbereiche sind nicht eindeutig sortiert")
    rules = content.get("body_frame_rules")
    if not isinstance(rules, dict):
        raise NativeRuntimeError("Original-Animationsindex-Regeln fehlen")
    for name in ("one_based_gm_ids", "direct_gm_ids", "special_gm_ids"):
        ids = rules.get(name)
        if not isinstance(ids, list) or any(type(x) is not int or not 0 <= x < 512 for x in ids):
            raise NativeRuntimeError("Ungültige Original-Animationsindex-Regeln")
    return content


@dataclass
class RuntimeSnapshot:
    records: np.ndarray
    metadata: dict

    def __post_init__(self):
        records = self.records
        if (records.dtype != np.dtype("<i2") or records.ndim != 2 or
                records.shape[1] != RECORD_WORDS or not 0 < len(records) <= MAX_RECORDS):
            raise NativeRuntimeError("Ungültige Original-Engine-Grafikdaten")
        tiles = np.flatnonzero(records[:, 0] == 0)
        if not len(tiles):
            raise NativeRuntimeError("Engine lieferte keine Karten-Kacheln")
        coords = records[tiles, 1:3]
        if np.any(coords < 0) or np.any(coords >= 800):
            raise NativeRuntimeError("Engine-Koordinaten liegen außerhalb der Karte")
        self.tile_lookup = np.full((800, 800), -1, dtype=np.int32)
        self.tile_lookup[coords[:, 1], coords[:, 0]] = tiles
        if np.count_nonzero(self.tile_lookup >= 0) != len(tiles):
            raise NativeRuntimeError("Doppelte Engine-Kachelbefehle")
        self.draw_records = records[np.isin(records[:, 0], [0, 1, 2, 3, 4, 7, 9])]
        visible_tiles = self.draw_records[self.draw_records[:, 0] == 0]
        self.visible_tile_count = int(np.sum((visible_tiles[:, 3] != 38) & (visible_tiles[:, 3] > 0)))
        self.object_count = int(np.sum(self.draw_records[:, 0] != 0))
        # Native first frame arrives in row order but sort explicitly for safe
        # use with separately captured snapshots. Objects follow tile floors.
        order = np.lexsort((self.draw_records[:, 1], self.draw_records[:, 0] != 0,
                            self.draw_records[:, 2]))
        self.draw_records = self.draw_records[order]
        edges = np.searchsorted(self.draw_records[:, 2], np.arange(801))
        self.rows = [self.draw_records[edges[y]:edges[y+1]] for y in range(800)]

    def tile(self, x: int, y: int):
        if not 0 <= x < 800 or not 0 <= y < 800:
            return None
        i = int(self.tile_lookup[y, x])
        return None if i < 0 else self.records[i]


def read_snapshot(folder: Path, expected_map_sha: str, expected_dll_sha: str):
    metadata = json.loads((folder / "snapshot.json").read_text(encoding="utf-8"))
    if (metadata.get("schema") != SNAPSHOT_SCHEMA or
            metadata.get("map_sha256") != expected_map_sha or
            metadata.get("dll_sha256") != expected_dll_sha or
            metadata.get("capture_revision") != CAPTURE_REVISION):
        raise NativeRuntimeError("Engine-Snapshot gehört nicht zu dieser Karten-/Spielversion")
    path = folder / "records.bin"
    size = path.stat().st_size
    count = metadata.get("record_count")
    if type(count) is not int or not 0 < count <= MAX_RECORDS or size != count * 42:
        raise NativeRuntimeError("Engine-Snapshot hat eine falsche Datenlänge")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != metadata.get("records_sha256"):
        raise NativeRuntimeError("Engine-Snapshot-Prüfsumme falsch")
    return RuntimeSnapshot(np.frombuffer(data, dtype="<i2").reshape(count, 21), metadata)


def capture_snapshot(map_path: str | Path, cache_dir: str | Path | None = None):
    source = Path(map_path).resolve()
    if os.name != "nt":
        raise NativeRuntimeError("Original-Engine benötigt die lokale Windows-Spielinstallation")
    game_data = source.parents[2]  # <game_data>/StreamingAssets/Maps/file.map
    library = game_data / "Plugins" / "x86_64" / "CrusaderDE.dll"
    managed = game_data / "Managed" / "Assembly-CSharp.dll"
    if not library.is_file() or not managed.is_file():
        raise NativeRuntimeError("Original-Engine neben dieser Karte nicht gefunden")
    contract = load_contract()
    dll_sha, map_sha = sha256(library), sha256(source)
    if dll_sha != contract["dll_sha256"] or sha256(managed) != contract["managed_sha256"]:
        raise NativeRuntimeError("Diese Spiel-Engine-Version hat noch keinen verifizierten ABI-Vertrag")
    cache_root = Path(cache_dir) if cache_dir else ROOT / "work" / "sandbox-engine-cache"
    key = hashlib.sha256((map_sha + dll_sha + CAPTURE_REVISION).encode()).hexdigest()
    folder = cache_root / key
    if (folder / "snapshot.json").is_file():
        try:
            return read_snapshot(folder, map_sha, dll_sha)
        except (NativeRuntimeError, OSError, ValueError):
            pass  # Rebuild only derived data; never touch the MAP source.
    cache_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="capture-", dir=cache_root) as temp:
        work = Path(temp)
        env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONIOENCODING="utf-8")
        command = [sys.executable, "-m", __name__, "--worker", str(source), str(game_data), str(work)]
        try:
            result = subprocess.run(command, env=env, cwd=work, capture_output=True,
                                    text=True, encoding="utf-8", errors="replace", timeout=45)
        except subprocess.TimeoutExpired as exc:
            raise NativeRuntimeError("Original-Engine-Aufnahme nach 45 Sekunden beendet") from exc
        if result.returncode:
            raise NativeRuntimeError("Original-Engine-Aufnahme fehlgeschlagen: " +
                                     (result.stderr or result.stdout)[-1400:])
        snapshot = read_snapshot(work, map_sha, dll_sha)
        if sha256(source) != map_sha:
            raise NativeRuntimeError("Originalkarte änderte sich während der Aufnahme")
        folder.mkdir(parents=True, exist_ok=True)
        for name in ("records.bin", "snapshot.json"):
            os.replace(work / name, folder / name)
        return snapshot


def _worker(map_path, game_data_path, output_path):
    """Known ABI only. Executed in a separate process, with isolated save paths."""
    import ctypes as C
    import shutil
    import struct
    original, game_data, output = Path(map_path), Path(game_data_path), Path(output_path)
    contract = load_contract()
    library = game_data / "Plugins" / "x86_64" / "CrusaderDE.dll"
    if sha256(library) != contract["dll_sha256"]:
        raise NativeRuntimeError("Native Bibliothek hat sich geändert")
    if sha256(game_data / "Managed" / "Assembly-CSharp.dll") != contract["managed_sha256"]:
        raise NativeRuntimeError("Managed Grafikvertrag hat sich geändert")
    before = sha256(original)
    cloned = output / "source-copy.map"
    shutil.copy2(original, cloned)
    saves = output / "isolated-saves"
    saves.mkdir(exist_ok=True)
    os.chdir(output)
    C.windll.kernel32.SetErrorMode(0x0001 | 0x0002 | 0x8000)
    handle = os.add_dll_directory(str(library.parent))
    engine = C.WinDLL(str(library))
    P, I = C.c_void_p, C.c_int
    set_path = engine.DLL_SetPath
    set_path.argtypes, set_path.restype = [P, I, P, I, P, I], I
    prepared = []
    for text in (str(game_data / "StreamingAssets") + "/",
                 str(saves / "unused-multiplayer.sav"), str(saves) + "/"):
        raw = text.encode("utf-16le")
        prepared.append((C.create_string_buffer(raw), len(raw)))
    set_path(prepared[0][0], prepared[0][1], prepared[1][0], prepared[1][1],
             prepared[2][0], prepared[2][1])
    meta = C.create_string_buffer(1024 * 1024)
    initialize = engine.DLL_PreInitMap_Editor
    initialize.argtypes, initialize.restype = [I, I, I, I, P], None
    initialize(160, 0, 0, 0, meta)
    load = engine.DLL_LoadSaveGame
    load.argtypes, load.restype = [P, I, P, I], I
    raw = str(cloned).encode("utf-16le")
    path_buffer = C.create_string_buffer(raw)
    if load(path_buffer, len(raw), meta, 1) <= 0:
        raise NativeRuntimeError("Original-Engine lehnte die Kartenkopie ab")
    header = struct.unpack_from("<20i", meta)
    memory = (C.c_int16 * 14700000)()
    radar = C.create_string_buffer(800 * 800 * 4)
    state = C.create_string_buffer(1024 * 1024)
    chores = C.create_string_buffer(1000000)
    selected = (I * 20000)()
    tick = engine.DLL_RunTick
    pointer_arguments = {0, 1, 8, 29, 30}
    tick.argtypes = [P if i in pointer_arguments else I for i in range(38)]
    tick.restype = I
    # Full map frame, editor paused. No input, no multiplayer, no save/action.
    count = tick(memory, radar, 0, -1, -1, 0, 0, 0, state, 1,
                 0, 0, 0, 0, 0, 0, 0, 400, 400, 800, 800, 200, 200,
                 1, 1, 0, 0, 400, 400, chores, selected, 0, -1, -1, 0, 799, 0, 799)
    if not 0 < count <= MAX_RECORDS:
        raise NativeRuntimeError(f"Original-Engine meldet ungültige Datensatzanzahl {count}")
    data = C.string_at(C.addressof(memory), count * 42)
    if sha256(original) != before or sha256(cloned) != before:
        raise NativeRuntimeError("Kartenbytes wurden während der Engine-Aufnahme geändert")
    metadata = {"schema": SNAPSHOT_SCHEMA, "capture_revision": CAPTURE_REVISION,
                "map_sha256": before, "dll_sha256": contract["dll_sha256"],
                "managed_sha256": contract["managed_sha256"], "record_count": count,
                "records_sha256": hashlib.sha256(data).hexdigest(),
                "source_name": original.name, "map_size": header[1],
                "map_rotation": header[2], "paused": True}
    RuntimeSnapshot(np.frombuffer(data, dtype="<i2").reshape(count, 21), metadata)
    (output / "records.bin").write_bytes(data)
    (output / "snapshot.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"records": count, "map": original.name, "unchanged": True}))


if __name__ == "__main__":
    if len(sys.argv) != 5 or sys.argv[1] != "--worker":
        raise SystemExit("Only the isolated native snapshot worker is supported")
    _worker(*sys.argv[2:])

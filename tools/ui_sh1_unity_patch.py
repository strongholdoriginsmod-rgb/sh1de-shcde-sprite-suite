"""Create a source-pinned, format-preserving Stronghold 1 Unity HUD candidate.

The target is an isolated directory under Sprite Suite's dist/, never a game
installation. Changes only the changed RGBA32 rows and BC7 4x4 GPU blocks in
globalgamemanagers.assets, without Unity container reserialization.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from PIL import Image

from ui_sh1_hud import (
    ATLAS_NAMES, HudError, check_workspace, commit, digest_file,
    ensure_under, locate, monobehaviour_name, require_disjoint_output, stage_for,
)

IMAGE_OFFSETS = frozenset({100, 108})
FORMAT_AND_SHAPE = {
    "UI-MasterAtlas": (4, 8192, 4096),
    "UI-ROL": (25, 4096, 4096),
    "UI-CandleAtlas": (25, 2048, 4096),
}
DEFAULT_OUTPUT = "dist/sh1-hud-unity-kandidat"
MAX_PATCHES = 100_000
MAX_BC7_BLOCKS = 8192
MAX_BC7_VISUAL_ERROR = 64


@dataclass(frozen=True)
class BytePatch:
    offset: int
    before: bytes
    after: bytes
    texture: str

    def __post_init__(self):
        if self.offset < 0 or not self.before or len(self.before) != len(self.after):
            raise HudError("Leerer, ungleicher oder negativer Unity-Patch")


def diff_blocks(base: Image.Image, edited: Image.Image, crops: Sequence[dict]) -> set[tuple[int, int]]:
    """Find 4×4 BC7 blocks with an actual modified pixel (including alpha)."""
    dirty: set[tuple[int, int]] = set()
    for entry in crops:
        x, y, width, height = entry["rect"]
        if any(type(v) is not int for v in (x, y, width, height)):
            raise HudError("Ungültige XAML-Koordinaten")
        if x < 0 or y < 0 or width < 1 or height < 1 or x + width > base.width or y + height > base.height:
            raise HudError("XAML-Ausschnitt außerhalb des SH1-Atlanten")
        orig = memoryview(base.crop((x, y, x + width, y + height)).tobytes()).cast("I")
        new = memoryview(edited.crop((x, y, x + width, y + height)).tobytes()).cast("I")
        for index, (a, b) in enumerate(zip(orig, new)):
            if a != b:
                local_y, local_x = divmod(index, width)
                dirty.add(((x + local_x) // 4, (y + local_y) // 4))
                if len(dirty) > MAX_PATCHES:
                    raise HudError("Zu viele Änderungen für einen gezielten BC7-Blockpatch")
    return dirty


def rgba_patches(base: Image.Image, edited: Image.Image, crops: Sequence[dict],
                 *, start: int, texture: str) -> list[BytePatch]:
    """Emit exact RGBA32 byte rows using Unity's bottom-up row order."""
    if base.size != edited.size or base.mode != "RGBA" or edited.mode != "RGBA":
        raise HudError("RGBA-Quellen müssen exakt dieselbe Größe und RGBA-Farben haben")
    patches: list[BytePatch] = []
    for entry in crops:
        x, y, width, height = entry["rect"]
        for absolute_y in range(y, y + height):
            box = (x, absolute_y, x + width, absolute_y + 1)
            previous = base.crop(box).tobytes()
            wanted = edited.crop(box).tobytes()
            if previous != wanted:
                # Keep the rewrite bounded to the changed pixel span, not
                # the complete (possibly 1752px wide) HUD rectangle row.
                a = memoryview(previous).cast("I")
                b = memoryview(wanted).cast("I")
                changed = [i for i in range(width) if a[i] != b[i]]
                lo, hi = changed[0], changed[-1] + 1
                offset = start + ((base.height - 1 - absolute_y) * base.width + x + lo) * 4
                patches.append(BytePatch(
                    offset, previous[lo * 4:hi * 4], wanted[lo * 4:hi * 4], texture
                ))
                if len(patches) > MAX_PATCHES:
                    raise HudError("Zu viele RGBA-Zeilenänderungen")
    return patches


def bc7_patches(base: Image.Image, edited: Image.Image, crops: Sequence[dict],
                *, start: int, texture_data: bytes, texture: str,
                max_blocks: int) -> tuple[list[BytePatch], list[tuple[int, int]]]:
    from UnityPy.export import Texture2DConverter as converter

    if base.size != edited.size or base.mode != "RGBA" or edited.mode != "RGBA":
        raise HudError("BC7-Quellen müssen RGBA und gleich dimensioniert sein")
    if base.width % 4 or base.height % 4 or len(texture_data) != base.width * base.height:
        raise HudError("BC7-Atlas besitzt falsche 4x4-Blockgeometrie")
    dirty = sorted(diff_blocks(base, edited, crops), key=lambda xy: (xy[1], xy[0]))
    if len(dirty) > max_blocks:
        raise HudError(
            f"{texture}: {len(dirty)} veränderte BC7-Blöcke überschreiten die "
            f"Sicherheitsgrenze {max_blocks}; bewusst --max-bc7-blocks erhöhen"
        )
    patches: list[BytePatch] = []
    encoded_blocks = []
    for bx, by in dirty:
        x, y = bx * 4, by * 4
        block = edited.crop((x, y, x + 4, y + 4))
        payload, actual_format = converter.image_to_texture2d(block, 25)
        if int(actual_format) != 25 or len(payload) != 16:
            raise HudError(f"{texture}: der BC7-Encoder lieferte kein 16-Byte-Format")
        # Unity Texture2D stores BC7 blocks in bottom-up row order.
        block_index = ((base.height // 4 - 1 - by) * (base.width // 4) + bx) * 16
        old = texture_data[block_index:block_index + 16]
        if old == payload:
            raise HudError(
                f"{texture}: Änderung in BC7-Block ({bx},{by}) verschwindet bei "
                "der Kompression; bitte einen stärkeren Pixelkontrast wählen"
            )
        patches.append(BytePatch(start + block_index, old, payload, texture))
        encoded_blocks.append((bx, by))
    return patches, encoded_blocks


def verify_native_provenance(env, workspace: Path, source_images: dict) -> dict:
    """Independently bind every exported XAML/PNG baseline to the real Unity game.

    A self-updated JSON hash cannot prove that a workspace contains authentic
    Stronghold-1 coordinates. Compare against resources actually embedded in
    the source-pinned Unity container before any game byte can be changed.

    Accept older Windows exports whose text-mode file writes doubled CRLF.
    New exports preserve the original Unity XAML bytes verbatim.
    """
    native = {}
    for obj in env.objects:
        if obj.type.name != "MonoBehaviour":
            continue
        raw = bytes(obj.get_raw_data())
        name = monobehaviour_name(raw)
        if name not in ATLAS_NAMES:
            continue
        first = raw.find(b"<ResourceDictionary")
        last = raw.rfind(b"</ResourceDictionary>")
        if first < 0 or last <= first or name in native:
            raise HudError(f"Original-XAML fehlt oder ist nicht eindeutig: {name}")
        native[name] = raw[first:last + len(b"</ResourceDictionary>")]
    if set(native) != set(ATLAS_NAMES):
        raise HudError("Unity-Original-XAML der drei SH1-HUD-Atlanten fehlt")

    if set(source_images) != set(ATLAS_NAMES):
        raise HudError("Nicht alle originalen SH1-Atlanten wurden entschlüsselt")
    legacy = 0
    for name in ATLAS_NAMES:
        stored = (workspace / "baseline" / (name + ".xaml")).read_bytes()
        raw = native[name]
        # Older exports used Path.write_text under Windows; that doubled CRLF
        # in the native files but left pixel mapping/keys unchanged.
        if stored != raw:
            if stored != raw.replace(b"\n", b"\r\n"):
                raise HudError(f"{name}: gespeicherte Basis entspricht nicht der Original-XAML im Unity-Asset")
            legacy += 1
        source = source_images[name]
        if source.mode != "RGBA":
            raise HudError(f"{name}: intern unerwarteter Pixelmodus")
        with Image.open(workspace / "baseline" / (name + ".png")) as png:
            if png.size != source.size:
                raise HudError(f"{name}: Original-PNG hat andere Dimensionen als das Unity-Asset")
            baseline = png.convert("RGBA")
        # Compare in small strips: never create another 134MB bytes object.
        for y in range(0, source.height, 128):
            rect = (0, y, source.width, min(source.height, y + 128))
            if source.crop(rect).tobytes() != baseline.crop(rect).tobytes():
                raise HudError(f"{name}: gespeicherte Original-PNG stammt nicht aus dem Unity-Asset")
    return {
        "xaml_dictionaries_checked": len(native),
        "baseline_images_checked": len(source_images),
        "legacy_xaml_accepted": legacy,
    }


def texture_offset(obj, data, source_size: int, expected_name: str) -> tuple[int, bytes]:
    if obj.type.name != "Texture2D" or data.m_Name != expected_name:
        raise HudError("Unity-Objekt-/Texturidentität weicht ab")
    fmt, width, height = FORMAT_AND_SHAPE[expected_name]
    if (int(data.m_TextureFormat), data.m_Width, data.m_Height) != (fmt, width, height):
        raise HudError(f"{expected_name}: Originalformat oder Abmessungen verändert")
    if getattr(data, "m_MipCount", None) != 1:
        raise HudError(f"{expected_name}: Mipmap-Stapel wird nicht unterstützt")
    stream = data.m_StreamData
    if stream is None or stream.path or stream.size or stream.offset:
        raise HudError(f"{expected_name}: externe oder verschobene Streamdaten verboten")
    image_data = bytes(data.image_data)
    expected_length = width * height * (4 if fmt == 4 else 1)
    if len(image_data) != expected_length:
        raise HudError(f"{expected_name}: unpassende Texturblockgröße")
    raw = obj.get_raw_data()
    offset = len(raw) - len(image_data) - 16
    if offset not in IMAGE_OFFSETS or raw[offset:offset + len(image_data)] != image_data:
        raise HudError(f"{expected_name}: nicht unterstützte Unity-Serialisierung")
    absolute_start = obj.byte_start + offset
    if obj.byte_start < 0 or absolute_start + len(image_data) > source_size:
        raise HudError(f"{expected_name}: Texturbereich liegt außerhalb des Unity-Containers")
    return absolute_start, image_data


def _validate_and_apply(source: Path, target: Path, patches: list[BytePatch]) -> None:
    """Verify original spans before applying an ordered, non-overlapping patch."""
    original_size = source.stat().st_size
    if target.stat().st_size != original_size:
        raise HudError("Unity-Kopie hat eine andere Länge als das Original")
    ordered = sorted(patches, key=lambda p: p.offset)
    last = 0
    with source.open("rb") as origin, target.open("r+b") as dest:
        for patch in ordered:
            if patch.offset < last or patch.offset + len(patch.after) > original_size:
                raise HudError("Überlappender oder überlaufender Unity-Bytepatch")
            origin.seek(patch.offset)
            dest.seek(patch.offset)
            current = origin.read(len(patch.before))
            if current != patch.before or dest.read(len(patch.before)) != current:
                raise HudError("Unity-Basisdaten entsprechen nicht dem gepinnten Patch")
            dest.seek(patch.offset)
            dest.write(patch.after)
            last = patch.offset + len(patch.after)
    # Compare all unchanged source bytes to the output, not just the patches.
    with source.open("rb") as origin, target.open("rb") as dest:
        position = 0
        for patch in ordered:
            remaining = patch.offset - position
            while remaining:
                length = min(2 * 1024 * 1024, remaining)
                if origin.read(length) != dest.read(length):
                    raise HudError("Ein unveränderter Unity-Datenbereich unterscheidet sich")
                remaining -= length
            if origin.read(len(patch.before)) != patch.before:
                raise HudError("Unity-Originaldaten während des Schreibens verändert")
            if dest.read(len(patch.after)) != patch.after:
                raise HudError("Unity-Patchdaten weichen nach dem Schreiben ab")
            position = patch.offset + len(patch.after)
        while data := origin.read(2 * 1024 * 1024):
            if dest.read(len(data)) != data:
                raise HudError("Nicht gepinnte Unity-Daten wurden verändert")
        if dest.read(1):
            raise HudError("Ausgabe enthält zusätzliche Bytes")


def _validate_reopened_asset(target: Path, plan: dict, edited, source_images, *,
                             max_visual_error: int = MAX_BC7_VISUAL_ERROR) -> dict:
    import UnityPy

    # Load bytes in memory: a file-backed UnityPy mmap prevents atomically
    # renaming the staged candidate on Windows while the reader is alive.
    env = UnityPy.load(target.read_bytes())
    found = {}
    for obj in env.objects:
        if obj.type.name != "Texture2D":
            continue
        name = obj.peek_name()
        if name not in FORMAT_AND_SHAPE:
            continue
        if name in found:
            raise HudError(f"Ausgabe enthält mehrfachen UI-Atlas: {name}")
        data = obj.read()
        texture_offset(obj, data, target.stat().st_size, name)
        found[name] = data
    if set(found) != set(FORMAT_AND_SHAPE):
        raise HudError("Die drei Unity-HUD-Texturen fehlen nach dem Wiederöffnen")
    checked = {}
    for name, blocks in plan.items():
        if not blocks:
            continue
        current = found[name].image.convert("RGBA")
        if name == "UI-MasterAtlas":
            for x, y, width, height in blocks:
                box = (x, y, x + width, y + height)
                if current.crop(box).tobytes() != edited[name].crop(box).tobytes():
                    raise HudError("RGBA32-Textur ließ sich nicht pixelgenau rekonstruieren")
            checked[name] = {"format": 4, "rgba_rows_checked": len(blocks)}
        else:
            max_error, total_error, count = 0, 0, 0
            visible_max_error = 0.0
            for bx, by in blocks:
                box = (bx * 4, by * 4, bx * 4 + 4, by * 4 + 4)
                actual = current.crop(box).tobytes()
                original = source_images[name].crop(box).tobytes()
                wanted = edited[name].crop(box).tobytes()
                if actual == original:
                    raise HudError(f"{name}: neuer BC7-Block blieb visuell unverändert")
                for index in range(0, len(actual), 4):
                    have = actual[index:index + 4]
                    expected = wanted[index:index + 4]
                    for channel in range(4):
                        err = abs(have[channel] - expected[channel])
                        max_error = max(max_error, err)
                        total_error += err
                        count += 1
                    # Compare visible colors with premultiplied alpha: arbitrary
                    # RGB differences below alpha=0 must not reject valid BC7.
                    visible_max_error = max(
                        visible_max_error,
                        abs(have[3] - expected[3]),
                        *(abs(have[channel] * have[3]
                               - expected[channel] * expected[3]) / 255.0
                          for channel in range(3)),
                    )
            if visible_max_error > max_visual_error:
                raise HudError(
                    f"{name}: BC7 sichtbare Farbabweichung "
                    f"{visible_max_error:.1f} überschreitet den Grenzwert "
                    f"{max_visual_error}. Nur nach eigener Bildkontrolle "
                    "mit --max-bc7-visual-error erhöhen."
                )
            checked[name] = {
                "format": 25, "bc7_blocks_checked": len(blocks),
                "maximum_channel_error": max_error,
                "maximum_visible_channel_error": round(visible_max_error, 3),
                "mean_channel_error": round(total_error / max(count, 1), 3),
            }
    return checked


def create_candidate(source: Path, workspace: Path, target_folder: Path, *,
                     replace: bool = False, max_blocks: int = MAX_BC7_BLOCKS,
                     max_visual_error: int = MAX_BC7_VISUAL_ERROR) -> dict:
    import UnityPy

    source = locate(source)
    workspace = locate(workspace)
    target_folder = ensure_under(locate(target_folder), "dist")
    require_disjoint_output(target_folder, source, workspace)
    if source.name != "globalgamemanagers.assets" or not source.is_file():
        raise HudError("Es wird die original benannte Unity-Datei globalgamemanagers.assets benötigt")
    if type(max_blocks) is not int or max_blocks < 1 or max_blocks > 500_000:
        raise HudError("Ungültiges BC7-Kompressionsbudget")
    if type(max_visual_error) is not int or not 0 <= max_visual_error <= 255:
        raise HudError("Ungültiger Grenzwert für BC7-Farbabweichung")
    result, images = check_workspace(workspace, construct=True)
    source_digest = digest_file(source)
    if source_digest != result["source_sha256"]:
        raise HudError("Die originale Unity-Datei passt nicht zum HUD-Export (SHA-256)")
    edited = dict(images)
    changes = {name: [] for name in FORMAT_AND_SHAPE}
    for crop in result["changed"]:
        changes[crop["atlas"]].append(crop)
    env = UnityPy.load(str(source))
    asset_objects = {}
    patches: list[BytePatch] = []
    bc7_blocks: dict[str, list[tuple[int, int]]] = {}
    rgba_rows = []
    source_images = {}
    for obj in env.objects:
        if obj.type.name != "Texture2D":
            continue
        name = obj.peek_name()
        if name not in FORMAT_AND_SHAPE:
            continue
        if name in asset_objects:
            raise HudError(f"Original-Unity-Datei enthält doppelten UI-Atlas: {name}")
        data = obj.read()
        start, image_data = texture_offset(obj, data, source.stat().st_size, name)
        asset_objects[name] = str(obj.path_id)
        base = data.image.convert("RGBA")
        source_images[name] = base
        if not changes[name]:
            continue
        desired = edited[name]
        if base.size != desired.size:
            raise HudError("Original-Unity-Atlas und bearbeitete PNG-Geometrie unterscheiden sich")
        if FORMAT_AND_SHAPE[name][0] == 4:
            rows = rgba_patches(base, desired, changes[name], start=start, texture=name)
            patches.extend(rows)
            for patch in rows:
                scanline = (base.height - 1 - (patch.offset - start) // (base.width * 4))
                x = ((patch.offset - start) % (base.width * 4)) // 4
                rgba_rows.append((x, scanline, len(patch.after) // 4, 1))
        else:
            found, dirty = bc7_patches(
                base, desired, changes[name],
                start=start, texture_data=image_data, texture=name,
                max_blocks=max_blocks
            )
            patches.extend(found)
            bc7_blocks[name] = dirty
        print("HUD_UNITY_TEXTURE_PLAN", name, "patch_count",
              len(rows) if name == "UI-MasterAtlas" else len(found), flush=True)
    if set(asset_objects) != set(FORMAT_AND_SHAPE):
        raise HudError("Unity-Datei enthält nicht alle drei originalen HUD-Texturen")
    provenance = verify_native_provenance(env, workspace, source_images)
    stage = stage_for(target_folder, replace)
    try:
        output = stage / source.name
        shutil.copyfile(source, output)
        if digest_file(source) != source_digest:
            raise HudError("Quell-Unity-Datei änderte sich beim Kopieren")
        _validate_and_apply(source, output, patches)
        quality = _validate_reopened_asset(
            output,
            {"UI-MasterAtlas": rgba_rows, **bc7_blocks},
            edited,
            source_images,
            max_visual_error=max_visual_error,
        )
        candidate_digest = digest_file(output)
        bytes_updated = sum(len(p.after) for p in patches)
        manifest = {
            "schema": "sprite-suite.sh1-unity-hud-candidate.v1",
            "source_sha256": source_digest,
            "candidate_sha256": candidate_digest,
            "original_unity_bytes": source.stat().st_size,
            "candidate_unity_bytes": output.stat().st_size,
            "source_workspace": str(workspace),
            "textures_by_path_id": asset_objects,
            "validated_crops": result["checked"],
            "verified_original_resources": provenance,
            "edited_crops": result["changed"],
            "byte_patches": len(patches),
            "byte_regions": bytes_updated,
            "bc7_changed_block_count": {name: len(value) for name, value in bc7_blocks.items()},
            "quality_after_reopen": quality,
            "max_allowed_bc7_visible_channel_error": max_visual_error,
            "original_installation_modified": False,
            "runtime_game_tested": False,
        }
        (stage / "sh1_unity_hud_candidate.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf8"
        )
        (stage / "BITTE_LESEN.md").write_text(
            "# Stronghold 1: geprüfte Unity-HUD-Kandidatendatei\n\n"
            "Die Datei globalgamemanagers.assets ist eine **lokal aus deinem Spiel "
            "abgeleitete, noch nicht im Spiel getestete Kopie**. "
            "Sie wurde als isolierter Kandidat erzeugt. Originaldateien wurden nicht verändert.\n\n"
            "Der verlustfreie RGBA32-Atlas wurde ausschließlich in den geänderten "
            "Zeilen angepasst; BC7 nur in den geänderten 4x4-Blöcken. "
            "BC7 ist verlustbehaftet und kann Nachbarpixel im selben Block mit verändern.\n\n"
            "Ein Einbau in die Spielinstallation ist hier absichtlich nicht automatisiert. "
            "Vor einem späteren, gesondert freigegebenen Einbau müssen "
            "Datei- und Versionsidentität, Spielstart, HUD-Anzeige, alle Eingaben und "
            "ein sicherer Rückweg nachgewiesen werden. "
            "Die Unity-Kopie niemals öffentlich weiterverbreiten.\n",
            encoding="utf8"
        )
        commit(stage, target_folder, replace)
        print("SH1_UNITY_HUD_CANDIDATE_OK", target_folder, "patches", len(patches),
              "changed_crops", len(result["changed"]), flush=True)
        return manifest
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True,
                        help="Original Stronghold 1 globalgamemanagers.assets (nur lesen)")
    parser.add_argument("--from", dest="workspace", default="work/sh1-hud-editierbar",
                        help="Bearbeitetes HUD mit vollständigem lokalen Quellmanifest")
    parser.add_argument("--out", default=DEFAULT_OUTPUT,
                        help="Neues Verzeichnis UNTER dist/ für Unity-Kandidat")
    parser.add_argument("--replace", action="store_true",
                        help="Bestehende isolierte Kandidatendateien bewusst ersetzen")
    parser.add_argument("--max-bc7-blocks", type=int, default=MAX_BC7_BLOCKS)
    parser.add_argument("--max-bc7-visual-error", type=int,
                        default=MAX_BC7_VISUAL_ERROR,
                        help="Maximale sichtbare Farbkanalabweichung bei BC7 (0-255, Standard 64)")
    args = parser.parse_args(argv)
    try:
        create_candidate(locate(args.source), locate(args.workspace),
                         locate(args.out), replace=args.replace,
                         max_blocks=args.max_bc7_blocks,
                         max_visual_error=args.max_bc7_visual_error)
        return 0
    except (HudError, ValueError, OSError, RuntimeError) as exc:
        print(f"SH1_UNITY_HUD_ABGELEHNT: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

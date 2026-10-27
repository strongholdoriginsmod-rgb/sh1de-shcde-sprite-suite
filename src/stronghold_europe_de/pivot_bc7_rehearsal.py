"""Isolated, synthetic BC7 V2 pivot metadata rehearsal.

This exercises the *real* AtlasGroupInput -> preflight -> Unity project
preparer and group cache descriptor factory. It deliberately does not run
Unity, publish a cache object, patch a profile or consume game sprites.
No output is promotable. Missing exact Unity 2021.3.45f2 is not bypassed.

All writes are confined to a newly created staging directory beneath
work/pivot-bc7-rehearsals; a completed directory is immutable. Retrying
a matching run verifies every byte before reusing its attestation.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

from PIL import Image, ImageDraw

from . import unity_asset_bundle as unity_module
from .asset_stream_contract import (
    AssetStreamContractError, QualityPolicy, TexturePolicy, parse_atlas_v3
)
from .asset_stream_incremental_v2 import build_group_cache_descriptors
from .pivot_bc7_cache import _finite_f32, EPSILON
from .release_preflight import _is_link
from .unity_asset_bundle import (
    AtlasGroupInput, FrameSource, UnityAssetBundleError,
    BC7_MAIN_BC7_MASK_TEXTURE_POLICY_ID,
    BC7_MEASUREMENT_POLICY_ID, BC7_MEASUREMENT_POLICY_SHA256,
    BC7_VERIFIER_ID, fingerprint_atlas_groups_v2,
    preflight_atlas_groups_v2,
    prepare_unity_asset_bundle_project_v2, validate_prepared_project_v2,
)

SCHEMA = "stronghold-europe.pivot-bc7-synthetic-rehearsal.v1"
DIRECTORY = "pivot-bc7-rehearsals"
FIXTURE_ID = "tiny-synthetic-two-groups-v1"
EXAMPLE_UNITY_HASH = "0" * 64  # NEVER a real Unity toolchain identity
GROUPS = (("anim_castle", 54), ("anim_drawbridge", 55))
CHANGED = "anim_castle"
UNCHANGED = "anim_drawbridge"
FRAME_SUFFIX = " 002"
FIXTURE_SIZE = (48, 40)
MAX_REHEARSAL_FILES = 256
SHA = re.compile(r"[0-9a-f]{64}\Z")
EVIDENCE_NAME = re.compile(r"evidence-([0-9a-f]{16})\.json\Z")


class PivotRehearsalError(ValueError):
    """The synthetic rehearsal input/output is unsafe or inconsistent."""


def _canonical(value: object) -> bytes:
    try:
        return (
            json.dumps(value, ensure_ascii=False, allow_nan=False,
                       sort_keys=True, separators=(",", ":")).encode("utf-8")
            + b"\n"
        )
    except (ValueError, TypeError) as exc:
        raise PivotRehearsalError("Noncanonical rehearsal evidence") from exc


def _hash(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _direct(root: Path, relative: Path) -> Path:
    current = root
    for component in relative.parts:
        if component in ("..", ".") or not component:
            raise PivotRehearsalError("Unsafe output component")
        current = current / component
        if _is_link(current):
            raise PivotRehearsalError(f"Linked rehearsal path rejected: {current}")
    return current


def _walk_exact(root: Path) -> tuple[list[dict], list[str]]:
    files: list[dict] = []
    dirs: list[str] = []
    pending = [root]
    number = 0
    while pending:
        folder = pending.pop()
        with os.scandir(folder) as entries:
            for entry in entries:
                number += 1
                if number > MAX_REHEARSAL_FILES:
                    raise PivotRehearsalError("Rehearsal tree unexpectedly large")
                path = Path(entry.path)
                if _is_link(path):
                    raise PivotRehearsalError("Links/junctions forbidden in rehearsal")
                relative = path.relative_to(root).as_posix()
                if entry.is_dir(follow_symlinks=False):
                    dirs.append(relative)
                    pending.append(path)
                elif entry.is_file(follow_symlinks=False):
                    files.append({
                        "path": relative, "sha256": _hash(path),
                        "size": path.stat().st_size,
                    })
                else:
                    raise PivotRehearsalError("Unexpected rehearsal entry type")
    return sorted(files, key=lambda x:x["path"]), sorted(dirs)


def _fixture_image(path: Path, secondary: bool) -> None:
    image = Image.new("RGBA", FIXTURE_SIZE, (0, 0, 0, 0))
    pen = ImageDraw.Draw(image)
    if secondary:
        pen.rectangle((6, 8, 40, 34), fill=(130, 65, 70, 245))
        pen.line((0, 0, 47, 39), fill=(230, 180, 80, 255), width=2)
    else:
        pen.polygon(((5,34),(6,16),(25,4),(43,19),(42,34)),
                    fill=(160, 110, 70, 235))
        pen.rectangle((19, 20, 28, 34), fill=(34, 32, 45, 255))
    image.save(path, format="PNG")
    image.close()


def _groups(source_root: Path, selected_y: float) -> tuple[AtlasGroupInput, ...]:
    specs: list[AtlasGroupInput] = []
    for name, number in GROUPS:
        frame = FrameSource(
            name=name + FRAME_SUFFIX, index=2, alt=False,
            main_path=(source_root / f"{name}.png").resolve(strict=True),
            mask_path=None, width=FIXTURE_SIZE[0], height=FIXTURE_SIZE[1],
            pivot_x=0.0, pivot_y=(selected_y if name == CHANGED else 1.0),
            pixels_per_unit=64.0,
        )
        specs.append(AtlasGroupInput(
            group=name, gm_id=number, dash_format=False, array_size=3,
            lifetime="map", mask_policy="forbidden",
            material_binding="plain_shared_v1", frames=(frame,),
        ))
    return tuple(specs)


def _safe_sources(project_root: Path) -> tuple[Path, dict[str,str]]:
    if _is_link(project_root / "work"):
        raise PivotRehearsalError("Linked project work directory")
    editor = project_root / "tools" / "unity_asset_bundle" / "StrongholdEuropeAssetBundleBuilder.cs"
    sources = (
        editor,
        project_root / "config" / "unity-assetbundle-toolchain.json",
        project_root / "src" / "stronghold_europe_de" / "unity_asset_bundle.py",
        project_root / "src" / "stronghold_europe_de" / "asset_stream_incremental_v2.py",
        Path(__file__).resolve(strict=True),
    )
    recorded: dict[str,str] = {}
    for source in sources:
        if not source.is_file() or _is_link(source):
            raise PivotRehearsalError(f"Required direct builder source missing: {source}")
        recorded[source.as_posix()] = _hash(source)
    return editor, recorded


def _unity_readiness(project_root: Path) -> dict:
    """Read the exact pinned editor identity without launching an executable."""
    path=project_root / "config" / "unity-assetbundle-toolchain.json"
    try:
        contract=json.loads(path.read_text(encoding="utf-8"))
    except (OSError,UnicodeError,json.JSONDecodeError) as exc:
        raise PivotRehearsalError("Pinned Unity configuration is unreadable") from exc
    if (
        not isinstance(contract,dict)
        or contract.get("version")!=unity_module.UNITY_VERSION
        or contract.get("revision")!=unity_module.UNITY_REVISION
        or contract.get("build_target")!=unity_module.BUILD_TARGET
    ):
        raise PivotRehearsalError("Pinned Unity editor identity differs from V2 backend")
    expected=contract.get("windows_executable_sha256")
    options=contract.get("discovery_relative_paths")
    size=contract.get("windows_executable_size_bytes")
    if (
        not isinstance(expected,str) or SHA.fullmatch(expected) is None
        or type(size) is not int or size<=0
        or not isinstance(options,list) or not options
        or not all(isinstance(o,str) and o.startswith("work/toolchains/")
                   and ".." not in Path(o).parts and "\\" not in o
                   for o in options)
    ):
        raise PivotRehearsalError("Malformed pinned Unity binary identity")
    status="exact_editor_missing"
    for relative in options:
        candidate=_direct(project_root,Path(relative))
        if not candidate.exists():
            continue
        if not candidate.is_file() or candidate.stat().st_size!=size or _hash(candidate)!=expected:
            raise PivotRehearsalError("Present Unity editor fails required SHA-256/size pin")
        status="exact_executable_hash_matches"
        break
    return {
        "required_version":contract["version"],
        "required_revision":contract["revision"],
        "required_sha256":expected,
        "discovery_status":status,
        "unity_was_launched":False,
        "unity_binary_fully_usable":False,
    }


def _prepped_snapshot(root: Path, prepared, fps, descriptors) -> dict:
    validate_prepared_project_v2(prepared)
    if prepared.pipeline_version != 2 or prepared.quality_mode != "measurement_nonpromotable":
        raise PivotRehearsalError("V2 preparation is not nonpromotable")
    if (
        prepared.index_path.exists()
        or prepared.report_path.exists()
        or (prepared.quality_report_path is not None and
            prepared.quality_report_path.exists())
    ):
        raise PivotRehearsalError("Unity may have unexpectedly run")
    groups = {}
    for item, descriptor in zip(fps, descriptors, strict=True):
        name = item.spec.group
        atlas_file = (
            prepared.project_path / "Assets" / "Generated"
            / "Groups" / item.slug / "atlas.v3.json"
        )
        atlas = parse_atlas_v3(atlas_file.read_bytes())
        names = [frame.name for frame in atlas.frames]
        if len(atlas.frames)!=1 or names != [name+FRAME_SUFFIX]:
            raise PivotRehearsalError("Synthetic frame identity drifted")
        main_file = (
            prepared.project_path / "Assets" / "Generated"
            / "Groups" / item.slug / "page-000-main.png"
        )
        groups[name] = {
            "frame": names[0],
            "pivot": [atlas.frames[0].pivot.x, atlas.frames[0].pivot.y],
            "rect": [atlas.frames[0].rect.width, atlas.frames[0].rect.height],
            "pixels_per_unit": atlas.frames[0].pixels_per_unit,
            "atlas_sha256": _hash(atlas_file),
            "frames_sha256": atlas.frames_sha256,
            "page_png_sha256": _hash(main_file),
            "cache_key_projection": descriptor.cache_key,
            "frame_bindings": dict(item.frame_bindings),
        }
        if descriptor.as_dict()["frames"] != item.frame_bindings:
            raise PivotRehearsalError("Group cache descriptor mismatched original V2 inputs")
    return {
        "build_id": prepared.build_id,
        "build_input_sha256": _hash(prepared.build_input_path),
        "template_sha256": _hash(prepared.index_template_path),
        "groups": groups,
        "input_relative_path": prepared.build_input_path.relative_to(root).as_posix(),
        "project_relative_path": prepared.project_path.relative_to(root).as_posix(),
    }


def _snapshot(
    project_root: Path, scratch: Path,
    *,
    old_y: float, new_y: float, editor: Path,
) -> dict:
    fixtures = scratch / "synthetic-fixtures"
    fixtures.mkdir()
    for i,(group,_) in enumerate(GROUPS):
        _fixture_image(fixtures / f"{group}.png", i == 1)
    original_hashes = {
        name: _hash(fixtures / f"{name}.png") for name, _ in GROUPS
    }
    snapshots = {}
    texture_policy = TexturePolicy(
        id=BC7_MAIN_BC7_MASK_TEXTURE_POLICY_ID,
        main_format="BC7", mask_format="BC7"
    )
    quality_policy = QualityPolicy(
        state="measurement_nonpromotable",
        id=BC7_MEASUREMENT_POLICY_ID,
        sha256=BC7_MEASUREMENT_POLICY_SHA256,
        verifier_id=BC7_VERIFIER_ID
    )
    for name, pivot in (("old", old_y), ("proposed", new_y)):
        work = scratch / name
        work.mkdir()
        groups = _groups(fixtures, pivot)
        fingerprints = fingerprint_atlas_groups_v2(groups)
        descriptors = build_group_cache_descriptors(
            project_root=project_root, fingerprints=fingerprints,
            editor_source=editor,
            unity_executable_sha256=EXAMPLE_UNITY_HASH,
            texture_policy=texture_policy, quality_policy=quality_policy,
            foliage_groups=(),
        )
        plan = preflight_atlas_groups_v2(groups)
        prepared = prepare_unity_asset_bundle_project_v2(
            work, plan, editor_source=editor,
            quality_mode="measurement_nonpromotable",
        )
        snapshots[name] = _prepped_snapshot(scratch, prepared, fingerprints, descriptors)
    old, new = snapshots["old"], snapshots["proposed"]
    if old["build_id"] == new["build_id"]:
        raise PivotRehearsalError("Pivot-only change did not invalidate the V2 build seed")
    for group,_ in GROUPS:
        a,b = old["groups"][group],new["groups"][group]
        if a["page_png_sha256"]!=b["page_png_sha256"]:
            raise PivotRehearsalError("Pivot change unexpectedly changed atlas pixels")
        if a["frame_bindings"]["main_rgba_sha256"]!=b["frame_bindings"]["main_rgba_sha256"]:
            raise PivotRehearsalError("Pivot change unexpectedly changed input source pixels")
        if a["rect"]!=b["rect"] or a["pixels_per_unit"]!=b["pixels_per_unit"]:
            raise PivotRehearsalError("Pivot-only change altered frame geometry or PPU")
    c1,c2=old["groups"][CHANGED],new["groups"][CHANGED]
    u1,u2=old["groups"][UNCHANGED],new["groups"][UNCHANGED]
    if not (c1["cache_key_projection"]!=c2["cache_key_projection"]
            and c1["frame_bindings"]["metadata_sha256"]!=c2["frame_bindings"]["metadata_sha256"]
            and c1["frames_sha256"]!=c2["frames_sha256"]
            and c1["atlas_sha256"]!=c2["atlas_sha256"]):
        raise PivotRehearsalError("Changed group's metadata invalidation is incomplete")
    if any(u1[k]!=u2[k] for k in (
        "cache_key_projection","frame_bindings","frames_sha256","atlas_sha256",
        "page_png_sha256"
    )):
        raise PivotRehearsalError("Unaffected group changed its cache/atlas contract")
    if c1["pivot"] != [0.0, old_y] or c2["pivot"] != [0.0,new_y]:
        raise PivotRehearsalError("Prepared Unity pivots differ from requested fixture")
    return {
        "synthetic_fixture_sha256": original_hashes,
        "old":old, "proposed":new,
        "changed_groups":[CHANGED],
        "unchanged_groups":[UNCHANGED],
        "pixel_pages_identical":True,
        "changed_group_key_invalidated":True,
        "unaffected_group_key_stable":True,
    }


def _prior(result: Path, digest: str) -> Path:
    if _is_link(result) or not result.is_dir():
        raise PivotRehearsalError("Previous rehearsal is unsafe")
    evidence = sorted(result.glob("evidence-*.json"))
    if len(evidence)!=1 or EVIDENCE_NAME.fullmatch(evidence[0].name) is None:
        raise PivotRehearsalError("Previous rehearsal has no unique immutable attestation")
    path=evidence[0]
    if _is_link(path) or path.stat().st_size>512*1024:
        raise PivotRehearsalError("Previous rehearsal evidence is unsafe")
    content=path.read_bytes()
    if sha256(content).hexdigest()[:16] != EVIDENCE_NAME.fullmatch(path.name).group(1):
        raise PivotRehearsalError("Previous attestation hash changed")
    try:
        report=json.loads(content.decode("utf-8"))
    except (UnicodeError,json.JSONDecodeError) as exc:
        raise PivotRehearsalError("Unreadable previous attestation") from exc
    if (
        report.get("schema")!=SCHEMA or report.get("run_id")!=digest
        or report.get("release_allowed") is not False
        or report.get("unity_executed") is not False
    ):
        raise PivotRehearsalError("Previous attestation identity disagrees")
    artifact_list=report.get("artifacts")
    directories=report.get("directories")
    if not isinstance(artifact_list,list) or not isinstance(directories,list):
        raise PivotRehearsalError("Previous artifact directory inventory invalid")
    files_now, dirs_now = _walk_exact(result)
    expected = sorted([*artifact_list,
        {"path":path.name,"sha256":_hash(path),"size":len(content)}],key=lambda x:x["path"])
    if files_now != expected or dirs_now != directories:
        raise PivotRehearsalError("Previous rehearsal artifacts or directories changed")
    return path


def prepare_synthetic_pivot_rehearsal(
    project_root: str | Path,
    *,
    old_pivot_y: float=1.10909091,
    new_pivot_y: float=1.0,
) -> Path:
    """Build two real V2 Unity *input projects*; never run Unity/encoder.

    Returned evidence is bound to every prepared byte and kept entirely
    beneath project/work. No production inputs, profiles, caches or games
    are changed. The two tiny RGBA PNGs are deliberately synthetic.
    """
    root=Path(project_root).resolve(strict=True)
    try:
        old,new=_finite_f32(old_pivot_y),_finite_f32(new_pivot_y)
    except ValueError as exc:
        raise PivotRehearsalError(str(exc)) from exc
    if abs(old-new)<=EPSILON:
        raise PivotRehearsalError("Both pivots already match; no rebuild rehearsal necessary")
    editor,sources=_safe_sources(root)
    unity_readiness=_unity_readiness(root)
    identity={
        "fixture":FIXTURE_ID,"pivots":[old,new],
        "source_sha256":sources,
        "measurement_only":True,"synthetic_unity_executable_sha256":EXAMPLE_UNITY_HASH,
    }
    run_id=sha256(_canonical(identity)).hexdigest()[:20]
    work=_direct(root,Path("work"))
    parent=_direct(root,Path("work")/DIRECTORY)
    parent.mkdir(parents=True,exist_ok=True)
    result=_direct(root,Path("work")/DIRECTORY/run_id)
    if result.exists():
        previous=_prior(result,run_id)
        report=json.loads(previous.read_text(encoding="utf-8"))
        if (
            report.get("identity") != identity
            or report.get("installation_allowed") is not False
            or report.get("asset_bundle_produced") is not False
            or report.get("quality_state") != "measurement_nonpromotable"
        ):
            raise PivotRehearsalError("Previous rehearsal is not the same synthetic contract")
        return previous
    scratch=Path(tempfile.mkdtemp(prefix=f".prepare-{run_id}-",dir=parent))
    published=False
    try:
        tested=_snapshot(root,scratch,old_y=old,new_y=new,editor=editor)
        # All code and the expected Unity C# builder must remain pinned.
        for filename,expected in sources.items():
            if _hash(Path(filename)) != expected:
                raise PivotRehearsalError("Builder source changed during rehearsal")
        artifacts,directories=_walk_exact(scratch)
        evidence={
            "schema":SCHEMA, "run_id":run_id,
            "pinned_unity_editor":unity_readiness,
            "project_root":str(root),
            "identity":identity,
            "tested":tested,
            "artifacts":artifacts,
            "directories":directories,
            "unity_executed":False,
            "unity_binary_verified":False,
            "quality_state":"measurement_nonpromotable",
            "release_allowed":False,
            "installation_allowed":False,
            "asset_bundle_produced":False,
            "disclaimer": (
                "Synthetic two-group BC7 V2 input rehearsal only: not SHCDE art, "
                "not real Unity encoding/roundtrip, not an approved profile/cache "
                "update, not a game installation."
            ),
        }
        payload=_canonical(evidence)
        attested=scratch/f"evidence-{sha256(payload).hexdigest()[:16]}.json"
        with attested.open("xb") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        if result.exists():
            raise PivotRehearsalError("Another rehearsal published the same run")
        os.rename(scratch,result)
        published=True
        return result/attested.name
    except (OSError,AssetStreamContractError,UnityAssetBundleError) as exc:
        raise PivotRehearsalError(f"V2 synthetic rehearsal failed: {exc}") from exc
    finally:
        if not published and scratch.is_dir() and not _is_link(scratch):
            # Only our freshly generated, private staging directory.
            shutil.rmtree(scratch)


__all__=["SCHEMA","PivotRehearsalError","prepare_synthetic_pivot_rehearsal"]

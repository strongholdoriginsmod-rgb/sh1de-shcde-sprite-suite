"""Publish an authored atlas pair into the existing editable Suite project."""
from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
import json
from pathlib import Path
import shutil
from uuid import uuid4

from PIL import Image

import hud_menu_workspace as hud
from suite_output_transaction import OutputBatch, OutputConflictError
from suite_windows_paths import safe_relative_file, is_link_or_reparse


def _sha(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _state(path: Path) -> str | None:
    if any(is_link_or_reparse(p) for p in (path, *path.parents)):
        raise ValueError("Verknüpfter Atlaspfad")
    if not path.exists():
        return None
    if not path.is_file():
        raise ValueError("Atlasziel ist keine Datei")
    return _sha(path)


def publish_pair(project: Path, pair: dict, *, cancel=None) -> dict:
    """Reuse the guarded file publisher and retain replaced project revisions.

    Ordinary flat atlas pairs use one OutputBatch. URI subdirectories use
    multiple batches with hash-guarded outer rollback. No game is modified.
    Recovery files are retained if a foreign write prevents safe rollback.
    """
    from ui_atlas_workspace import AtlasProject

    root = hud.workspace(project)
    workspace = AtlasProject.open(Path(pair["workspace"]))
    info = workspace.info()
    if pair.get("revision") != info["revision"]:
        raise ValueError("Atlas-Arbeitsstand wurde seit dem Export geändert")
    receipt_path = Path(pair["receipt"])
    if _state(receipt_path) is None or receipt_path.stat().st_size > 32 * 1024**2:
        raise ValueError("Atlas-Exportbeleg fehlt oder ist zu groß")
    if _sha(receipt_path) != pair.get("receipt_sha256"):
        raise ValueError("Atlas-Exportbeleg wurde seit dem Export verändert")
    proof = json.loads(receipt_path.read_text("utf-8"))
    if proof.get("revision") != info["revision"]:
        raise ValueError("Atlas-Exportbeleg gehört zu einem anderen Zustand")
    files = []
    for kind, suffix in (("png", ".png"), ("xaml", ".xaml")):
        record = proof[kind]
        source = safe_relative_file(receipt_path.parent, record["file"],
                                    allowed_suffixes=frozenset({suffix}))
        if source != Path(pair[kind]).absolute() or _state(source) != record["sha256"]:
            raise ValueError("Atlas-Exportdatei stimmt nicht mit ihrem Beleg überein")
        relative = "Override/Assets/GUI/Sprites/" + record["file"]
        destination = safe_relative_file(root, relative, allowed_suffixes=frozenset({suffix}))
        files.append(dict(source=source, destination=destination, relative=relative,
                          sha256=record["sha256"], before=_state(destination)))
    if files[1]["sha256"] != info["sources"]["xaml"]["sha256"]:
        raise ValueError("Atlas-XAML wurde verändert")
    with Image.open(files[0]["source"]) as image:
        if image.format != "PNG" or image.size != (info["width"], info["height"]):
            raise ValueError("Atlas-PNG hat andere Abmessungen")
        image.verify()
    folded = [f["relative"].casefold() for f in files]
    if len(set(folded)) != len(folded):
        raise ValueError("Atlas-Ausgabepfade kollidieren")
    if cancel is not None and cancel():
        raise ValueError("Atlasübernahme vor Veröffentlichung abgebrochen")
    # Compact private revision IDs keep ordinary nested Suite paths usable on
    # portable Windows runtimes that still apply the legacy MAX_PATH limit.
    metadata = hud._metadata_dir(root) / "atlas-pubs" / uuid4().hex[:12]
    if any(is_link_or_reparse(p) for p in (metadata, *metadata.parents)):
        raise ValueError("Verknüpfter Atlas-Revisionspfad")
    metadata.mkdir(parents=True, exist_ok=False)
    groups = defaultdict(list)
    for index, item in enumerate(files):
        if item["before"] is not None:
            backup = metadata / f"before-{index}{item['source'].suffix}"
            shutil.copyfile(item["destination"], backup)
            if _sha(backup) != item["before"] or _state(item["destination"]) != item["before"]:
                raise OutputConflictError("Projektatlas änderte sich beim Sichern")
            item["backup"] = backup
        groups[item["destination"].parent].append(item)
    committed = []
    result = dict(schema="spritesuite.ui-atlas-project-publication.v1", project=str(root),
                  revision=info["revision"], atlas_workspace=str(workspace.workspace),
                  files=[dict(relative_path=f["relative"], sha256=f["sha256"],
                              previous_sha256=f["before"]) for f in files],
                  warnings=pair.get("warnings", []), original_game_files_modified=False,
                  installed_into_game=False, revisions=str(metadata))
    receipt = metadata / "publication.json"
    try:
        for parent, entries in groups.items():
            with OutputBatch(parent) as batch:
                for item in entries:
                    staged = batch.stage(item["destination"].name)
                    if _state(item["destination"]) != item["before"]:
                        raise OutputConflictError("Projektatlas wurde während der Übernahme verändert")
                    shutil.copyfile(item["source"], staged)
                    if _sha(staged) != item["sha256"] or _state(item["source"]) != item["sha256"]:
                        raise OutputConflictError("Atlasexport wurde während der Übernahme verändert")
                if cancel is not None and cancel():
                    raise ValueError("Atlasübernahme vor Veröffentlichung abgebrochen")
                if (AtlasProject.open(Path(pair["workspace"])).info()["revision"] != info["revision"] or
                        _state(receipt_path) != pair["receipt_sha256"]):
                    raise OutputConflictError("Atlas-Arbeitsstand oder Exportbeleg wurde inzwischen verändert")
                batch.publish()
            committed.extend(entries)
        receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except BaseException:
        conflicts = []
        for item in reversed(committed):
            path = item["destination"]
            try:
                state = _state(path)
                if state == item["before"]:
                    continue
                if state != item["sha256"]:
                    raise OutputConflictError("Fremde Änderung während Atlas-Rücknahme")
                if item["before"] is None:
                    path.unlink()
                else:
                    with OutputBatch(path.parent) as rollback:
                        staged = rollback.stage(path.name)
                        shutil.copyfile(item["backup"], staged)
                        if _sha(staged) != item["before"] or _state(path) != item["sha256"]:
                            raise OutputConflictError("Atlas-Rücknahme konnte nicht verifiziert werden")
                        rollback.publish()
            except (OSError, ValueError, OutputConflictError):
                conflicts.append(str(path))
        if conflicts:
            raise OutputConflictError("Fremde Dateien erhalten; Atlasrevisionen zur Wiederherstellung: " +
                                      str(metadata) + "; " + "; ".join(conflicts))
        raise
    result["receipt"] = str(receipt)
    return result

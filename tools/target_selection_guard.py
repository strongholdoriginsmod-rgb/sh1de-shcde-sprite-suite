"""Read-only exact-build attestations and explicit target gating.

These gates never select a 2.7 target for a 2.80 mapping. A verified game
folder remains read-only until the user explicitly selects and confirms it.
"""
from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
import gzip
import json
from pathlib import Path
import re
import tomllib

CANONICAL=(
 "globalgamemanagers","resources.assets","resources.assets.resS",
 "sharedassets1.assets","Managed/Assembly-CSharp.dll",
)
DATA="Stronghold Crusader Definitive Edition_Data"

class TargetSelectionError(ValueError):
    pass

@dataclass(frozen=True)
class TargetAttestation:
    game_dir: Path
    data_dir: Path
    build_id: str
    mapping_build_id: str
    files_checked: int

def mapping_target_build_id(mapping: Path) -> str:
    if not mapping.is_file():
        raise TargetSelectionError("Sprite-Mapping fehlt. Zuerst die Spiele einlesen.")
    # The target_build_id appears after a >100K frame list in proposals.json.gz.
    # A rolling tail avoids retaining the entire mapping in RAM.
    tail=""
    try:
        with gzip.open(mapping,"rt",encoding="utf-8") as source:
            while True:
                block=source.read(1<<20)
                if not block:break
                tail=(tail+block)[-4096:]
    except (OSError, UnicodeError, EOFError) as exc:
        raise TargetSelectionError(f"Mapping nicht lesbar: {exc}") from exc
    match=re.search(r'"target_build_id"\s*:\s*"([^"]+)"',tail)
    if not match:
        raise TargetSelectionError("Mapping-Zielversion nicht nachgewiesen")
    return match.group(1)

def verify_target(game_root: str|Path, builds_file: str|Path,
                  mapping_file: str|Path) -> TargetAttestation:
    root=Path(game_root).resolve(strict=False)
    if root.name==DATA:root=root.parent
    data=root/DATA
    if not data.is_dir():
        raise TargetSelectionError(f"Kein vollständiges SHCDE-Spiel: {root}")
    if root.is_symlink() or data.is_symlink():
        raise TargetSelectionError("Verknüpfte Spielziele werden nicht aktiviert")
    try:
        builds=json.loads(Path(builds_file).read_text(encoding="utf-8"))
        references=builds["target_builds"]
    except (OSError,UnicodeError,ValueError,KeyError,TypeError) as exc:
        raise TargetSelectionError(f"Freigabe-Pins nicht lesbar: {exc}") from exc
    mapping_build=mapping_target_build_id(Path(mapping_file))
    reference=next((b for b in references if b.get("id")==mapping_build),None)
    if reference is None:
        raise TargetSelectionError(
            f"Mapping-Ziel {mapping_build} ist nicht in supported-builds freigegeben")
    entries={record.get("relative_path"):record for record in reference.get("files",[])}
    if set(entries)!=set(CANONICAL):
        raise TargetSelectionError("Freigabe-Pins sind nicht vollständig")
    # Fast size rejection prevents hashing GB-sized assets for a wrong build.
    for relative in CANONICAL:
        candidate=data/relative
        if candidate.is_symlink() or not candidate.is_file():
            raise TargetSelectionError(f"Quelldatei fehlt oder ist verknüpft: {relative}")
        if candidate.stat().st_size!=entries[relative].get("size"):
            raise TargetSelectionError(
                f"Falsche SHCDE-Version für Mapping {mapping_build}: "
                f"{relative} hat eine abweichende Dateigröße")
    for relative in CANONICAL:
        candidate=data/relative
        digest=sha256()
        try:
            with candidate.open("rb") as handle:
                for chunk in iter(lambda:handle.read(4<<20),b""):
                    digest.update(chunk)
        except OSError as exc:
            raise TargetSelectionError(f"Zieldatei nicht lesbar: {exc}") from exc
        if digest.hexdigest()!=entries[relative]["sha256"]:
            raise TargetSelectionError(
                f"Falscher SHA-256 in {relative}: Ziel ist NICHT freigegeben")
    return TargetAttestation(root,data,mapping_build,mapping_build,len(CANONICAL))

def verify_registered(name, *, root:Path):
    registry=root/"config"/"ziele.json"
    if not registry.is_file():
        raise TargetSelectionError("Keine Zielregistry; bitte Ziel explizit hinzufügen")
    try:
        document=json.loads(registry.read_text(encoding="utf-8"))
        spec=document["ziele"][name]
    except (OSError,ValueError,KeyError,TypeError) as exc:
        raise TargetSelectionError(f"Unbekanntes Ziel {name}: {exc}") from exc
    return verify_target(spec["spiel"],root/"config"/"supported-builds.json",
                         root/"work"/"mapping"/"proposals.json.gz")

def verify_active(*, root:Path):
    registry=root/"config"/"ziele.json"
    config=root/"config"/"installations.local.toml"
    try:
        entries=json.loads(registry.read_text(encoding="utf-8"))
        name=entries.get("aktiv")
        if not name or name not in entries["ziele"]:
            raise TargetSelectionError("Kein ausdrücklich aktives Produktionsziel")
        record=tomllib.loads(config.read_text(encoding="utf-8"))
    except (OSError,ValueError,KeyError,TypeError) as exc:
        raise TargetSelectionError(f"Kein gültiges aktives Installationsziel: {exc}") from exc
    attestation=verify_registered(name,root=root)
    if Path(record["target"]["game_dir"]).resolve()!=attestation.game_dir:
        raise TargetSelectionError("Aktives Ziel und Installationskonfiguration widersprechen sich")
    if record.get("policy",{}).get("allow_unknown_builds") is not False:
        raise TargetSelectionError("Unsichere Policy: unbekannte Builds müssen verboten sein")
    return name,attestation

def verify_source(source_data: str|Path, builds_file: str|Path) -> Path:
    """Exact SH1DE build, independently from target and its mapping."""
    path=Path(source_data).resolve(strict=False)
    if path.name=="Stronghold 1 Definitive Edition_Data":
        data=path
    else:
        data=path/"Stronghold 1 Definitive Edition_Data"
    if not data.is_dir():
        raise TargetSelectionError("SH1DE-Quelldatenordner fehlt")
    try:
        builds=json.loads(Path(builds_file).read_text(encoding="utf-8"))
        references=builds["source_builds"]
    except (ValueError,OSError,KeyError,TypeError) as exc:
        raise TargetSelectionError(f"SH1DE-Quellpins fehlen: {exc}") from exc
    for reference in references:
        pins={obj.get("relative_path"):obj for obj in reference["files"]}
        if set(pins)!=set(CANONICAL):continue
        if not all((data/rel).is_file() and not (data/rel).is_symlink() and
                   (data/rel).stat().st_size==pins[rel]["size"]
                   for rel in CANONICAL):
            continue
        matches=True
        for rel in CANONICAL:
            digest=sha256()
            with (data/rel).open("rb") as stream:
                for chunk in iter(lambda:stream.read(4<<20),b""):
                    digest.update(chunk)
            if digest.hexdigest()!=pins[rel]["sha256"]:
                matches=False
                break
        if matches:return data
    raise TargetSelectionError("SH1DE-Quellversion stimmt nicht mit supported-builds überein")

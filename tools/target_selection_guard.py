"""Read-only exact-build attestations and explicit target gating.

These gates never select a 2.7 target for a 2.80 mapping. A verified game
folder remains read-only until the user explicitly selects and confirms it.
"""
from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
import gzip
import hashlib
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

def inspect_target(game_root: str | Path, builds_file: str | Path) -> TargetAttestation:
    """Fingerprint any intact SHCDE generation, with no version allowlist.

    Historical installations retain their original IDs. New builds use the
    exact content-derived ID produced by the regular SpriteSuite builder.
    """
    raw = Path(game_root)
    root = raw.resolve(strict=False)
    if root.name == DATA:
        root = root.parent
    data = root / DATA
    if not data.is_dir():
        raise TargetSelectionError(f"SHCDE game directory missing: {root}")
    if raw.is_symlink() or root.is_symlink() or data.is_symlink():
        raise TargetSelectionError("Symlinked game directories are not allowed")
    try:
        doc = json.loads(Path(builds_file).read_text(encoding="utf-8"))
        references = doc["target_builds"]
        if not isinstance(references, list):
            raise ValueError("target_builds must be a list")
    except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
        raise TargetSelectionError(f"Reference-build list unreadable: {exc}") from exc
    actual = []
    for relative in CANONICAL:
        path = data / relative
        if path.is_symlink() or not path.is_file():
            raise TargetSelectionError(f"Required game file missing or symlinked: {relative}")
        before = path.stat()
        digest = sha256()
        try:
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(4 << 20), b""):
                    digest.update(chunk)
        except OSError as exc:
            raise TargetSelectionError(f"Game file cannot be read: {exc}") from exc
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (
            after.st_size, after.st_mtime_ns
        ):
            raise TargetSelectionError(f"Game file changed during hashing: {relative}")
        actual.append((relative, after.st_size, digest.hexdigest()))
    keys = set(actual)
    for reference in references:
        if not isinstance(reference, dict):
            continue
        try:
            expected = {
                (str(entry["relative_path"]), int(entry["size"]),
                 str(entry["sha256"]).lower())
                for entry in reference["files"]
            }
        except (KeyError, ValueError, TypeError):
            continue
        if expected == keys:
            identity = str(reference["id"])
            return TargetAttestation(root, data, identity, identity, len(actual))
    serialized = json.dumps(sorted(keys), separators=(",", ":")).encode("utf-8")
    identity = "installed-target-" + hashlib.sha256(serialized).hexdigest()
    return TargetAttestation(root, data, identity, identity, len(actual))


def verify_target(
    game_root: str | Path, builds_file: str | Path,
    mapping_file: str | Path,
) -> TargetAttestation:
    """Accept every game build, but never apply a mismatched sprite mapping."""
    attestation = inspect_target(game_root, builds_file)
    mapping_build = mapping_target_build_id(Path(mapping_file))
    if mapping_build != attestation.build_id:
        raise TargetSelectionError(
            "Mapping belongs to a different game build: "
            f"mapping={mapping_build}, game={attestation.build_id}. "
            "Re-import the games; no game version is categorically blocked."
        )
    return TargetAttestation(
        attestation.game_dir, attestation.data_dir, attestation.build_id,
        mapping_build, attestation.files_checked,
    )


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
    # Unknown game version strings never invalidate an explicitly chosen target.
    return name,attestation

def verify_source(source_data: str | Path, builds_file: str | Path) -> Path:
    """Accept any intact SH1DE build; the game directory is read-only."""
    raw = Path(source_data)
    resolved = raw.resolve(strict=False)
    data = (resolved if resolved.name == "Stronghold 1 Definitive Edition_Data"
            else resolved / "Stronghold 1 Definitive Edition_Data")
    if not data.is_dir() or raw.is_symlink() or data.is_symlink():
        raise TargetSelectionError("SH1DE source directory missing or symlinked")
    for relative in CANONICAL:
        path = data / relative
        if path.is_symlink() or not path.is_file():
            raise TargetSelectionError(f"SH1DE source file missing or symlinked: {relative}")
        before = path.stat()
        digest = sha256()
        try:
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(4 << 20), b""):
                    digest.update(chunk)
        except OSError as exc:
            raise TargetSelectionError(f"SH1DE source not readable: {exc}") from exc
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise TargetSelectionError(f"SH1DE source changed during hashing: {relative}")
    return data

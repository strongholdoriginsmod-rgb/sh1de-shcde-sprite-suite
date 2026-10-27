"""Read-only inventory of historic Sprite Suite QA and migration tools.

Old projects may pin SHCDE 2.7/2.80, 152 groups and specific DLL hashes.
Do not copy or execute these tools merely because their filenames exist.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile


@dataclass(frozen=True)
class Candidate:
    file: str
    purpose: str
    risk: str
    note: str


CANDIDATES: tuple[Candidate,...] = (
    Candidate("ram_acceptance.py","RAM / Laufzeitprotokolle","versiongebunden",
              "Logauswertung übernehmen, historische Grenzwerte separat neu kalibrieren."),
    Candidate("full152_ingame_acceptance.py","Ingame-Stabilität","versiongebunden",
              "PIDs und installierte Manifest-Hashes prüfen, nie automatisch starten."),
    Candidate("native_selection_probe.py","Engine-Auswahl","versiongebunden",
              "Nur mit zur DLL passenden RVA-/Versionspins verwenden."),
    Candidate("asset_stream_canary_ladder.py","BC7-Kanarieprüfung","versiongebunden",
              "Historische Quell-/Gruppenpins vor Portierung abgleichen."),
    Candidate("verify_cold_ab_bc7_v2.py","Kalter Atlasstart / Integrität","versiongebunden",
              "Historischen festen Build-Hash nicht auf aktuelle Pakete anwenden."),
    Candidate("runtime_install.py","Runtime-DLL-Austausch","schreibend",
              "Installiert DLLs; ohne eigenen Transaktions-/Rollback-Nachweis nicht anbieten."),
    Candidate("install_manifest_abgleichen.py","Installationsnachweise","schreibend",
              "Nur in diagnostisch getrenntem Wiederherstellungsworkflow."),
    Candidate("system_workflows.py","PowerShell-Buildabläufe","schreibend",
              "Ruft auch Installationsschritte auf; nicht über Prüfknopf starten."),
    Candidate("build_modding_exe.py","EXE-Paketierung","versiongebunden",
              "Erst aktuelle Laufzeit und Setup-Lock prüfen."),
    Candidate("shcdese_install.py","Script-Extender-Installer","schreibend",
              "Niemals automatisch fremde Spielinstallation ändern."),
)


class InventoryError(ValueError):
    pass


def _hash(path: Path) -> str:
    digest=sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b""):
            digest.update(chunk)
    return digest.hexdigest()


def inventory_legacy_tools(source_root: str | Path, target_root: str | Path) -> dict:
    source=Path(source_root).resolve()
    target=Path(target_root).resolve()
    if source==target:
        raise InventoryError("Altes Vergleichsprojekt und aktuelle Sprite Suite sind identisch.")
    if not (source/"tools").is_dir():
        raise InventoryError("Der ausgewählte Altbestand besitzt keinen tools-Ordner.")
    if not (target/"tools").is_dir():
        raise InventoryError("Die aktuelle Sprite Suite besitzt keinen tools-Ordner.")
    tools=[]
    for candidate in CANDIDATES:
        old=source/"tools"/candidate.file
        new=target/"tools"/candidate.file
        if not old.is_file():
            status="nicht_gefunden"
            old_sha=None
        else:
            old_sha=_hash(old)
            if not new.is_file():
                status="nur_im_altbestand"
            elif _hash(new)==old_sha:
                status="bereits_identisch"
            else:
                status="abweichende_version"
        tools.append({
            "name":candidate.file,
            "zweck":candidate.purpose,
            "risiko":candidate.risk,
            "status":status,
            "hinweis":candidate.note,
            "alte_sha256":old_sha,
            "aktuelle_sha256":_hash(new) if new.is_file() else None,
            "quelle":str(old) if old.is_file() else None,
        })
    return {
        "schema":"stronghold-europe.qa-tools-inventory.v1",
        "source_root":str(source),
        "target_root":str(target),
        "disclaimer":"Nur Hash-/Inventurvergleich; kein Kopieren, keine Ausführung, kein Installieren.",
        "tools":tools,
        "legacy_test_module_count":len(tuple((source/"tests").rglob("test_*.py")))
                                  if (source/"tests").is_dir() else 0,
        "current_test_module_count":len(tuple((target/"tests").rglob("test_*.py")))
                                   if (target/"tests").is_dir() else 0,
    }


def save_inventory(report: dict, target_root: str | Path) -> Path:
    target=Path(target_root).resolve()
    if report.get("schema")!="stronghold-europe.qa-tools-inventory.v1":
        raise InventoryError("Inventarvertrag ist ungültig")
    if report.get("target_root")!=str(target):
        raise InventoryError("Inventar gehört zu einer anderen Sprite Suite")
    payload=json.dumps(report,ensure_ascii=False,indent=2)+"\n"
    tag=sha256(payload.encode("utf-8")).hexdigest()[:16]
    output=target/"work"/"reports"/"qa-inventory"/f"qa-tools-{tag}.json"
    output.parent.mkdir(parents=True,exist_ok=True)
    if output.is_file():
        if output.read_text(encoding="utf-8")==payload:
            return output
        raise InventoryError("Bestehender QA-Bericht hat unerwartet anderen Inhalt")
    fd,tmp=tempfile.mkstemp(dir=output.parent,prefix=".qa-inventory-",suffix=".tmp")
    try:
        with os.fdopen(fd,"w",encoding="utf-8",newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp,output)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return output

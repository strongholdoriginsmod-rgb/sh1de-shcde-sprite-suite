"""Read-only, source-bound project-wide release preflight for Sprite Suite.

This is an *offline integrity inventory*, not the game/runtime acceptance.
It never modifies installed games, project sources, caches, or deliverables.
Only save_preflight() may publish an independent work/reports JSON snapshot.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Callable

SCHEMA = "stronghold-europe.release-preflight.v1"
ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,95}\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")
MAX_JSON_BYTES = 12 * 1024 * 1024
MAX_OUTPUTS = 4096
MAX_APPROVAL_ROWS = 4096
MAX_TREE_FILES = 8192
WINDOWS_REPARSE = 0x400


class ReleasePreflightError(ValueError):
    """A selected source is too unsafe or ambiguous to inspect."""


def _is_link(path: Path) -> bool:
    try:
        stat = path.lstat()
        return path.is_symlink() or bool(
            getattr(stat, "st_file_attributes", 0) & WINDOWS_REPARSE
        )
    except OSError:
        return False


def _safe_child(root: Path, relative: str) -> Path:
    """Accept only portable, unlinked files strictly below a trusted root."""
    if (
        not isinstance(relative, str)
        or not relative
        or relative.startswith("/")
        or "\\" in relative
        or ":" in relative
        or "//" in relative
    ):
        raise ReleasePreflightError("Unsicherer relativer Ausgabepfad")
    parts = relative.split("/")
    if any(p in ("", ".", "..") for p in parts):
        raise ReleasePreflightError("Unsicherer relativer Ausgabepfad")
    if _is_link(root):
        raise ReleasePreflightError("Verlinkter Ausgangsordner")
    item = root
    for part in parts:
        item = item / part
        if _is_link(item):
            raise ReleasePreflightError("Link/Junction innerhalb der Ausgabe")
    if not item.resolve().is_relative_to(root.resolve()):
        raise ReleasePreflightError("Pfad verlässt den geprüften Ausgabeordner")
    return item


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _strict_pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ReleasePreflightError(f"Doppeltes JSON-Feld: {key}")
        result[key] = value
    return result


def _bad_constant(value: str) -> object:
    raise ReleasePreflightError(f"JSON-Sonderzahl verboten: {value}")


def _read_json(path: Path, size_limit: int = MAX_JSON_BYTES) -> tuple[dict, str]:
    if not path.is_file() or _is_link(path):
        raise ReleasePreflightError(f"JSON-Datei fehlt oder ist verlinkt: {path.name}")
    if path.stat().st_size > size_limit:
        raise ReleasePreflightError(f"JSON-Datei zu groß: {path.name}")
    try:
        data = path.read_bytes()
        if len(data) > size_limit:
            raise ReleasePreflightError(f"JSON-Datei zu groß: {path.name}")
        parsed = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_strict_pairs,
            parse_constant=_bad_constant,
        )
    except (UnicodeError, OSError, json.JSONDecodeError) as exc:
        raise ReleasePreflightError(
            f"JSON nicht lesbar: {path.name}: {exc}"
        ) from exc
    if not isinstance(parsed, dict):
        raise ReleasePreflightError(f"JSON-Wurzel muss Objekt sein: {path.name}")
    return parsed, sha256(data).hexdigest()


def _manifest_files(root: Path) -> tuple[set[str], set[str], list[str]]:
    """Walk without following links; keep strict file/directory bounds."""
    actual: set[str] = set()
    directories: set[str] = set()
    problems: list[str] = []
    if _is_link(root):
        return set(), set(), ["Ausgabeordner ist Link/Junction"]
    pending = [root]
    count = 0
    while pending:
        folder = pending.pop()
        with os.scandir(folder) as iterator:
            for entry in iterator:
                count += 1
                if count > MAX_TREE_FILES:
                    raise ReleasePreflightError("Ausgabe enthält zu viele Dateisystemeinträge")
                relative = Path(entry.path).relative_to(root).as_posix()
                candidate = Path(entry.path)
                if _is_link(candidate):
                    problems.append(f"Nicht zulässiger Link/Junction: {relative}")
                elif entry.is_dir(follow_symlinks=False):
                    directories.add(relative)
                    pending.append(candidate)
                elif entry.is_file(follow_symlinks=False):
                    actual.add(relative)
                else:
                    problems.append(f"Unbekannter Dateityp: {relative}")
    return actual, directories, problems


def _finding(level: str, group: str, message: str) -> dict:
    return {
        "schwere": level,
        "pruefung": "Release",
        "gruppe": group,
        "text": message,
    }


def audit_release(
    project_root: str | Path,
    profile_id: str,
    *,
    approval_file: str | Path | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> dict:
    """Inspect the pinned profile, entire deliverable, index, and optional approvals."""
    if not isinstance(profile_id, str) or not ID.fullmatch(profile_id):
        raise ReleasePreflightError("Ungültige Profil-ID")
    root = Path(project_root).resolve(strict=True)
    findings: list[dict] = []

    def add(level: str, group: str, message: str) -> None:
        findings.append(_finding(level, group, message))

    sources: dict[str, str | None] = {
        "profile_sha256": None, "manifest_sha256": None,
        "index_sha256": None, "validation_report_sha256": None,
        "approval_sha256": None,
    }
    stats = {"expected_outputs": 0, "verified_outputs": 0,
             "verified_bytes": 0, "profile_groups": 0, "index_groups": 0}

    profile_path = root / "profiles" / f"{profile_id}.json"
    try:
        profile, sources["profile_sha256"] = _read_json(profile_path)
    except ReleasePreflightError as exc:
        add("fehler", "Profil", str(exc))
        profile = {}
    if profile:
        if profile.get("id") != profile_id or profile.get("schema_version") != 1:
            add("fehler", "Profil", "Profil-ID oder Profil-Schema passt nicht")
        else:
            add("info", "Profil", f"Profil {profile_id} eingelesen und SHA-256 erfasst")
    specs = profile.get("gm_atlases", [])
    if not isinstance(specs, list):
        add("fehler", "Spritegruppen", "gm_atlases ist keine Liste")
        specs = []
    group_names = [spec.get("gm_file_name") if isinstance(spec, dict) else None
                   for spec in specs]
    group_ids = {g.casefold() for g in group_names if isinstance(g, str) and g}
    stats["profile_groups"] = len(group_names)
    if len(group_ids) != len(group_names):
        add("fehler", "Spritegruppen", "Ungültige oder doppelte Profil-Spritegruppen")

    mod = root / "dist" / profile_id / "StrongholdEuropeDE"
    if not mod.is_dir() or _is_link(mod):
        add("fehler", "Ausgabe", "Kein sicherer fertig gebauter Modordner für das Profil")
        return _finish(profile_id, sources, stats, findings)
    manifest_path = mod / "build-manifest.json"
    try:
        manifest, sources["manifest_sha256"] = _read_json(manifest_path)
    except ReleasePreflightError as exc:
        add("fehler", "Manifest", str(exc))
        return _finish(profile_id, sources, stats, findings)

    if manifest.get("schema_version") != 1 or manifest.get("profile_id") != profile_id:
        add("fehler", "Manifest", "Manifest-Schema oder Profilbindung stimmt nicht")
    elif profile and manifest.get("mod_info") != profile.get("mod_info"):
        add("fehler", "Manifest", "Mod-Metadaten widersprechen dem aktuellen Profil")
    else:
        add("info", "Manifest", "Manifestprofil und Mod-Metadaten übereinstimmend")
    outputs = manifest.get("outputs")
    if not isinstance(outputs, list) or not 0 < len(outputs) <= MAX_OUTPUTS:
        add("fehler", "Ausgabedateien", "Ungültige Manifest-Ausgabeliste")
        return _finish(profile_id, sources, stats, findings)
    stats["expected_outputs"] = len(outputs)
    paths: dict[str, dict] = {}
    folded: set[str] = set()
    faulty: list[str] = []
    for index, item in enumerate(outputs):
        if not isinstance(item, dict):
            faulty.append(f"Datensatz {index}: kein Objekt")
            continue
        rel, size, digest = (
            item.get("relative_path"), item.get("size"), item.get("sha256")
        )
        if (
            not isinstance(rel, str)
            or type(size) is not int or size < 0
            or not isinstance(digest, str) or not SHA.fullmatch(digest)
        ):
            faulty.append(f"Datensatz {index}: Metadaten ungültig")
            continue
        try:
            path = _safe_child(mod, rel)
        except ReleasePreflightError as exc:
            faulty.append(f"{rel}: {exc}")
            continue
        if rel == "build-manifest.json" or rel.casefold() in folded:
            faulty.append(f"Doppelter/reservierter Dateiname: {rel}")
            continue
        folded.add(rel.casefold())
        paths[rel] = item
        if not path.is_file():
            faulty.append(f"Fehlend: {rel}")
            continue
        try:
            if path.stat().st_size != size:
                faulty.append(f"Größe verändert: {rel}")
                continue
            if _sha256_file(path) != digest:
                faulty.append(f"SHA-256 verändert: {rel}")
                continue
        except OSError as exc:
            faulty.append(f"Nicht lesbar: {rel}: {exc}")
            continue
        stats["verified_outputs"] += 1
        stats["verified_bytes"] += size
        if progress and (index % 20 == 0 or index == len(outputs) - 1):
            progress(index + 1, len(outputs))
    if faulty:
        add("fehler", "Datei-Integrität",
            f"{len(faulty)} fehlerhafte Ausgaben; Beispiele: " +
            "; ".join(faulty[:8]))
    else:
        add("info", "Datei-Integrität",
            f"Alle {len(outputs)} Dateien mit Größe und SHA-256 bestätigt "
            f"({stats['verified_bytes']} Bytes)")
    try:
        actual, directories, unsafe = _manifest_files(mod)
        expected_files = set(paths) | {"build-manifest.json"}
        expected_directories: set[str] = set()
        for relative in paths:
            parent = Path(relative).parent
            while parent != Path("."):
                expected_directories.add(parent.as_posix())
                parent = parent.parent
        missing = sorted(expected_files - actual)
        extra = sorted(actual - expected_files)
        unexpected_dirs = sorted(directories - expected_directories)
        if missing or extra or unexpected_dirs or unsafe:
            add("fehler", "Dateibestand",
                f"Nicht manifestgebundene Dateien/Links: fehlend={missing[:5]}, "
                f"zusätzlich={extra[:5]}, leere/fremde Ordner={unexpected_dirs[:5]}, "
                f"gefährlich={unsafe[:5]}")
        else:
            add("info", "Dateibestand", "Ausgabe enthält genau manifestierte Dateien")
    except (OSError, ReleasePreflightError) as exc:
        add("fehler", "Dateibestand", str(exc))
    index_entry = [r for r in outputs if isinstance(r, dict) and
                   r.get("category") == "asset_bundle_index"]
    if len(index_entry) != 1 or index_entry[0].get("relative_path") != (
        "Runtime/AssetBundles/index.json"
    ):
        add("fehler", "Bundleindex", "Kein eindeutiger BC7-Bundleindex im Manifest")
    else:
        index_path = mod / "Runtime" / "AssetBundles" / "index.json"
        try:
            bundle_index, sources["index_sha256"] = _read_json(index_path)
            if sources["index_sha256"] != index_entry[0].get("sha256"):
                raise ReleasePreflightError("Bundleindex nicht manifestidentisch")
            if bundle_index.get("backend_kind") != (
                profile.get("atlas_backend") or {}
            ).get("kind"):
                add("fehler", "Bundleindex", "Atlas-Backend unterscheidet sich vom Profil")
            index_groups = bundle_index.get("groups")
            if not isinstance(index_groups, list):
                add("fehler", "Bundleindex", "Bundle-Gruppenfeld ungültig")
            else:
                stats["index_groups"] = len(index_groups)
                found: set[str] = set()
                incorrect: list[str] = []
                for index_row in index_groups:
                    if not isinstance(index_row, dict):
                        incorrect.append("Ungültiger Gruppen-Datensatz")
                        continue
                    group = index_row.get("group")
                    rel = index_row.get("bundle_path")
                    digest = index_row.get("bundle_sha256")
                    if not isinstance(group, str) or group.casefold() in found:
                        incorrect.append(f"Doppelte/ungültige Gruppe: {group!r}")
                        continue
                    found.add(group.casefold())
                    artifact = paths.get(rel) if isinstance(rel, str) else None
                    if (not artifact or artifact.get("category") != "asset_bundle"
                        or artifact.get("sha256") != digest):
                        incorrect.append(f"{group}: Bundle/Manifest inkonsistent")
                if found != group_ids:
                    incorrect.append(
                        f"Gruppenmenge abweichend: nur im Profil="
                        f"{sorted(group_ids - found)[:5]}, "
                        f"nur im Bundle={sorted(found - group_ids)[:5]}"
                    )
                referenced = {
                    row.get("bundle_path") for row in index_groups
                    if isinstance(row, dict) and isinstance(row.get("bundle_path"), str)
                }
                declared = {
                    rel for rel, entry in paths.items()
                    if entry.get("category") == "asset_bundle"
                }
                if referenced != declared:
                    incorrect.append(
                        f"Bundle-Dateimenge abweichend: nicht referenziert="
                        f"{sorted(declared - referenced)[:5]}, "
                        f"nicht deklariert={sorted(referenced - declared)[:5]}"
                    )
                if incorrect:
                    add("fehler", "Bundle-Gruppen",
                        f"{len(incorrect)} Abweichungen: " + "; ".join(incorrect[:8]))
                else:
                    add("info", "Bundle-Gruppen",
                        f"{len(found)} Spritegruppen in Profil/Index/Bundle-Manifest konsistent")
        except (OSError, ReleasePreflightError) as exc:
            add("fehler", "Bundleindex", str(exc))
    validation = root / "work" / "reports" / f"{profile_id}-validation.json"
    if validation.is_file():
        try:
            data, sources["validation_report_sha256"] = _read_json(validation)
            count = data.get("passed")
            failed = data.get("failed")
            if (data.get("schema_version") != 1
                or type(count) is not int or type(failed) is not int):
                raise ReleasePreflightError("Ungültiger historischer Validierungsbericht")
            add("warnung" if failed or not data.get("ok") else "info",
                "Validierungsbericht",
                f"Gespeicherter Bericht: {count} bestanden, {failed} fehlgeschlagen. "
                "Historischer Nachweis; enthält keine Bindung an den jetzt "
                "geprüften Manifest-SHA-256.")
        except ReleasePreflightError as exc:
            add("warnung", "Validierungsbericht", str(exc))
    else:
        add("warnung", "Validierungsbericht",
            "Kein gespeicherter Validierungsbericht. "
            "Den vollständigen Profil-Validator vor Freigabe gesondert ausführen.")
    if approval_file is not None:
        _audit_approval(root, Path(approval_file), findings, sources, group_ids)
    else:
        add("info", "Pivot-Freigaben",
            "Kein Freigabeprotokoll ausgewählt; Pivot-Anwendung nicht geprüft.")
    add("info", "Prüfgrenze",
        "Dies bestätigt nur lokalen Build und Quelldateien. "
        "Ingame-Abnahme, vollständiger Builder-Neubau, Shader und "
        "metadatenreine Pivot-Übernahme sind NICHT freigegeben.")
    return _finish(profile_id, sources, stats, findings)


def _audit_approval(
    root: Path, selection: Path, findings: list[dict],
    sources: dict[str, str | None], profile_groups: set[str],
) -> None:
    """Check manually selected approval evidence without trusting stored paths."""
    base = root / "work" / "reports" / "pivot-approval"
    try:
        filename = selection.name
        if selection.resolve() != (base / filename).resolve():
            raise ReleasePreflightError("Freigabeprotokoll außerhalb des Berichtordners")
        path = _safe_child(base, filename)
        report, sources["approval_sha256"] = _read_json(path)
        if report.get("schema") != "stronghold-europe.pivot-approval.v1":
            raise ReleasePreflightError("Unbekanntes Pivot-Freigabeschema")
        rows = report.get("rows")
        if not isinstance(rows, list) or len(rows) > MAX_APPROVAL_ROWS:
            raise ReleasePreflightError("Ungültige Freigabezeilen")
        approved = [r for r in rows if isinstance(r, dict) and r.get("decision") == "freigegeben"]
        wrong: list[str] = []
        pending: list[str] = []
        already: list[str] = []
        from .pivot_measurements import NAME, EPSILON
        for row in approved:
            name = row.get("name")
            match = NAME.fullmatch(name) if isinstance(name, str) else None
            if not match or row.get("status") != "pruefen" or row.get("source") != "geliefert":
                wrong.append(f"{name}: unzulässige Freigabedaten")
                continue
            group = match.group("group")
            if group.casefold() not in profile_groups:
                wrong.append(f"{name}: Gruppe nicht im gewählten Profil")
                continue
            folder = root / "work" / "katalog" / "geliefert" / group
            try:
                index = _safe_child(folder, "index.json")
                contents, index_hash = _read_json(index, MAX_JSON_BYTES)
                frames = contents.get("frames", [])
                matches = [f for f in frames if isinstance(f, dict) and f.get("name") == name]
                if len(matches) != 1:
                    raise ReleasePreflightError("Kein eindeutiger Spriteframe")
                meta = matches[0]
                pixel = _safe_child(folder, meta.get("file"))
                pixel_hash = _sha256_file(pixel)
                if (
                    row.get("source_index_sha256") != index_hash
                    or row.get("source_image_sha256") != pixel_hash
                    or row.get("source_index") != str(index.resolve())
                    or row.get("source_image") != str(pixel.resolve())
                ):
                    raise ReleasePreflightError("Index- oder Bildstand hat sich geändert")
                current = (float(meta["pivot_x"]), float(meta["pivot_y"]))
                old, target = row.get("measured_old"), row.get("measured_new")
                if (
                    not isinstance(old, list) or not isinstance(target, list)
                    or len(old) != 2 or len(target) != 2
                ):
                    raise ReleasePreflightError("Pivot-Koordinaten fehlen")
                if all(abs(a - float(b)) <= EPSILON for a, b in zip(current, target)):
                    already.append(name)
                elif all(abs(a - float(b)) <= EPSILON for a, b in zip(current, old)):
                    pending.append(name)
                else:
                    raise ReleasePreflightError("Ausgangs- und Zielpivot widersprechen dem Index")
            except (OSError, ValueError, TypeError, KeyError, ReleasePreflightError) as exc:
                wrong.append(f"{name}: {exc}")
        if wrong:
            findings.append(_finding("fehler", "Pivot-Freigaben",
                                     f"{len(wrong)} ungültige/veraltete Freigaben: " +
                                     "; ".join(wrong[:5])))
        if pending:
            findings.append(_finding("warnung", "Pivot-Freigaben",
                                     f"{len(pending)} geprüfte Korrekturen warten auf "
                                     "separaten Metadaten-/BC7-Releasevertrag: " +
                                     ", ".join(pending[:5])))
        if already or (not wrong and not pending):
            findings.append(_finding("info", "Pivot-Freigaben",
                                     f"Protokoll geprüft: {len(approved)} freigegeben, "
                                     f"{len(already)} aktuell bereits passend. "
                                     "Eine Freigabe führt keine Änderung aus."))
    except (OSError, ReleasePreflightError) as exc:
        findings.append(_finding("fehler", "Pivot-Freigaben", str(exc)))


def _finish(profile_id: str, sources: dict, stats: dict, findings: list[dict]) -> dict:
    errors = sum(x["schwere"] == "fehler" for x in findings)
    warnings = sum(x["schwere"] == "warnung" for x in findings)
    return {
        "schema": SCHEMA,
        "profile_id": profile_id,
        "source_hashes": sources,
        "stats": stats,
        "summary": {
            "errors": errors, "warnings": warnings,
            "state": "blockiert" if errors else "hinweise" if warnings else "offline_ok",
        },
        "findings": findings,
        "disclaimer": (
            "Offline-Integritätsabgleich, keine Ingame-Abnahme oder Runtime-Freigabe, "
            "keine automatische Freigabe oder Installation."
        ),
    }


def save_preflight(report: dict, project_root: str | Path) -> Path:
    """Publish only a deterministic work/reports snapshot; never touch artifacts."""
    if report.get("schema") != SCHEMA:
        raise ReleasePreflightError("Unbekanntes Release-Berichtformat")
    root = Path(project_root).resolve()
    folder = root / "work" / "reports" / "release-preflight"
    folder.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    digest = sha256(payload.encode("utf-8")).hexdigest()[:16]
    name = report.get("profile_id")
    if not isinstance(name, str) or not ID.fullmatch(name):
        raise ReleasePreflightError("Ungültige Profil-ID in Bericht")
    target = folder / f"{name}-{digest}.json"
    if target.exists():
        if target.is_file() and target.read_text(encoding="utf-8") == payload:
            return target
        raise ReleasePreflightError("Bestehendes Prüfprotokoll ist beschädigt")
    fd, temp = tempfile.mkstemp(dir=folder, prefix=".preflight-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, target)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return target

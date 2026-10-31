"""Read-only project milestones; file presence never implies a release approval."""
from __future__ import annotations

from pathlib import Path

from suite_windows_paths import is_link_or_reparse


def milestones(root: Path) -> tuple[tuple[str,str,str],...]:
    """A human workflow, not a permission to build, install or ship."""
    root = Path(root)
    work = root / "work"
    project = work / "hud-menu-werkstatt"
    dist = root / "dist" / "europe-production"
    project_exists = project.is_dir() and not is_link_or_reparse(project)
    build_exists = dist.is_dir() and not is_link_or_reparse(dist)
    return (
        ("Arbeitsprojekt",
         "vorhanden" if project_exists else "offen",
         "Projekt öffnen und Änderungen speichern" if project_exists
         else "HUD & Menüs → Arbeitsprojekt anlegen"),
        ("Komposition",
         "nicht nachgewiesen",
         "Layout speichern, PNG und Positionsmanifest prüfen"),
        ("Modpaket",
         "nicht validiert" if build_exists else "offen",
         "Paket bauen und unabhängige Validierung durchführen"),
        ("QA-Spielkopie",
         "nicht nachgewiesen",
         "Nur gesicherte Mod in ausdrücklich gewählter QA-Kopie testen"),
        ("Ingame",
         "nicht abgenommen",
         "Sichtbarkeit, Shader, Fokus und bestehende Klickzonen im Spiel prüfen"),
    )


def milestone_text(root: Path) -> str:
    steps = milestones(root)
    return "  |  ".join(f"{name}: {state}" for name,state,_next in steps)

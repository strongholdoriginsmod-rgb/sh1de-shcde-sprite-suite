"""Curated, navigation-only cross-workflow index for existing Stronghold tools.

No script is imported, spawned, copied, or approved by this index. CLI argument
forms, validation and execution remain owned by the existing Suite catalog.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Specialist:
    filename: str
    title_de: str
    title_en: str
    category_de: str
    category_en: str
    keywords: tuple[str, ...] = ()


# Functional specialists only; internal libraries and historical hard-pinned
# installers do not become new top-level commands merely because they exist.
SPECIALISTS: tuple[Specialist, ...] = (
    Specialist("suite_tool_inventory.py", "Historische Werkzeugmatrix", "Historic tool inventory",
               "Prüfen", "Inspection", ("sha256", "versionen", "historisch", "duplikate")),
    Specialist("suite_compatibility_preflight.py", "Kompatibilitätsprüfung", "Compatibility preflight",
               "Prüfen", "Inspection", ("steam", "python", "abi", "runtime")),
    Specialist("grafik_analyse.py", "Grafikanalyse", "Graphics analysis",
               "Prüfen", "Inspection", ("bundles", "pixel", "bildvergleich", "atlas")),
    Specialist("grafik_diagnose.py", "Grafikdiagnose", "Graphics diagnosis",
               "Prüfen", "Inspection", ("fehler", "kacheln", "pivots")),
    Specialist("qa_suite_build_readiness.py", "Bauvoraussetzungen prüfen", "Check build readiness",
               "Prüfen", "Inspection", ("unity", "dotnet", "profil", "build")),
    Specialist("building_damage_codex.py", "Gebäude-Schadensmodelle mit GPT Image 2.6", "Building damage models with GPT Image 2.6",
               "Grafik", "Graphics", ("zerstoerung", "destruction", "fire", "mechanical", "hp", "damage", "codex", "gpt image")),
    Specialist("sprites.py", "Sprites exportieren und bearbeiten", "Export and edit sprites",
               "Grafik", "Graphics", ("png", "import", "frames", "katalog")),
    Specialist("kachelraster_gm1.py", "GM1-Kachelraster", "GM1 tile grid",
               "Grafik", "Graphics", ("tile", "isometrie", "raster")),
    Specialist("ui_sh1_hud.py", "SH1-HUD-Austausch", "SH1 HUD exchange",
               "Grafik", "Graphics", ("stronghold 1", "ui", "export")),
    Specialist("unit_pipeline.py", "Einheiten-Pipeline", "Unit production pipeline",
               "Grafik", "Graphics", ("animation", "3d", "einheiten")),
    Specialist("ui_atlas.py", "UI-Atlanten", "UI atlases",
               "Atlas", "Atlas", ("noesis", "hud", "export", "import")),
    Specialist("se_atlas.py", "Script-Extender-AtlasBuilder", "Script Extender AtlasBuilder",
               "Atlas", "Atlas", ("bc7", "dds", "override")),
    Specialist("background_v2_pipeline.py", "Hintergrund-Pipeline", "Background pipeline",
               "Atlas", "Atlas", ("background", "mask", "europe")),
    Specialist("origins_grafikdaten.py", "Origins-Grafikdaten", "Origins graphics",
               "Atlas", "Atlas", ("origins", "lfs", "ui")),
    Specialist("se_asset_package.py", "DLL-freies Assetpaket", "DLL-free asset package",
               "Paket", "Package", ("zip", "semod", "assets")),
    Specialist("qa_release_preflight.py", "Release-Vorabprüfung", "Release preflight",
               "Paket", "Package", ("sha256", "manifest", "qa")),
    Specialist("suite_workflow.py", "Suite-Pipeline", "Suite pipeline",
               "Paket", "Package", ("prepare", "check", "build")),
    Specialist("ziel_se211.py", "Zielspiele und Mods verwalten", "Manage target games and mods",
               "Ziele", "Targets", ("installation", "backup", "restore", "deinstallieren")),
)

_TOOL_DIR = Path(__file__).resolve().parent


def _safe_catalog_path(app, filename: str) -> Path | None:
    """Trust only an unchanged file from this Suite's own tools directory."""
    paths = getattr(app, "catalog_paths", None)
    if not isinstance(paths, dict):
        return None
    candidate = paths.get(filename)
    if candidate is None:
        return None
    try:
        path = Path(candidate)
        if (path.name != filename or path.suffix != ".py"
                or path.is_symlink() or not path.is_file()
                or path.resolve().parent != _TOOL_DIR):
            return None
        return path
    except (OSError, ValueError, RuntimeError, TypeError):
        return None


def available_specialists(app) -> tuple[Specialist, ...]:
    """Hide unavailable tools; never manufacture a runnable catalog entry."""
    return tuple(tool for tool in SPECIALISTS
                 if _safe_catalog_path(app, tool.filename) is not None)


def open_specialist(app, filename: str) -> None:
    """Navigate to an EXISTING catalog form. Nothing in the tool is run."""
    if filename not in {item.filename for item in SPECIALISTS}:
        raise ValueError("Tool ist nicht als Fachwerkzeug freigegeben")
    if _safe_catalog_path(app, filename) is None:
        raise FileNotFoundError("Fachwerkzeug fehlt im vorhandenen Katalog")
    # Validate the whole target before changing any UI selection.
    page = app.catalog_page
    choice = app.catalog_tool
    loader = app.load_catalog
    app.open_tab(page)
    choice.set(filename)
    loader()

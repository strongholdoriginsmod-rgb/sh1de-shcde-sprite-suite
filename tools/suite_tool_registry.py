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
    Specialist('shcde_workbench.py', 'SHCDE-Fachwerkstatt – 16 Bereiche', 'SHCDE workbench – 16 domains',
               'Projekt', 'Project', ('apishared', 'serp', 'aic', 'aiv', 'lua', 'runtime', 'mission', 'audio')),
    Specialist('shcde_mod_project.py', 'SHCDE-Projekt verbinden', 'Link SHCDE project',
               'Projekt', 'Project', ('projekt', 'gemeinsam', 'assets', 'manifest')),
    Specialist('shcde_mod_composer.py', 'Modpakete zusammenführen', 'Compose mod packages',
               'Paket', 'Package', ('modpack', 'konflikte', 'zip', 'sha256')),
    Specialist('shcde_api_native_index.py', 'API- und Native-Referenzen durchsuchen', 'Search API and native references',
               'Prüfen', 'Inspection', ('shcdese', 'apishared', 'serp', 'csharp', 'dll', 'signatur')),
    Specialist('shcde_game_inspector.py', 'Spielinspektor bauen', 'Build game inspector',
               'Runtime', 'Runtime', ('dll', 'bepinex', 'diagnose', 'game')),
    Specialist('shcde_gameplay_rules.py', 'Gameplay-Regeln bauen', 'Build gameplay rules',
               'Runtime', 'Runtime', ('balancing', 'plugin', 'regeln', 'csharp')),
    Specialist('shcde_aiv_lord_studio.py', 'AIV und eigene Lords', 'AIV and custom lords',
               'Spielinhalt', 'Game content', ('burg', 'ki', 'lord', 'aiv')),
    Specialist('shcde_mod_settings.py', 'Mod-Einstellungen bearbeiten', 'Edit mod settings',
               'Projekt', 'Project', ('apishared', 'settings', 'konfiguration')),
    Specialist('shcde_scenario_graph.py', 'Szenario- und Missionsgraph', 'Scenario and mission graph',
               'Spielinhalt', 'Game content', ('lua', 'mission', 'trigger', 'simulation')),
    Specialist('shcde_pathing_report.py', 'Wegfindungsprotokoll auswerten', 'Analyze pathfinding log',
               'Prüfen', 'Inspection', ('pathing', 'performance', 'log')),
    Specialist('shcde_qa_suite.py', 'SHCDE-Projekt und Bau prüfen', 'Check SHCDE project and build',
               'Prüfen', 'Inspection', ('qa', 'build', 'projekt', 'modpack')),
    Specialist("modding_studio.py", "Modding Studio – 12 Arbeitsbereiche", "Modding Studio – 12 workspaces",
               "Projekt", "Project", ("apishared", "serp", "aiv", "mission", "lua", "modding", "studio")),
    Specialist("building_damage_native_bindings.py", "Native Gebäude-Zuordnungen", "Native building bindings",
               "Grafik", "Graphics", ("damage", "hp", "feuer", "native", "granary", "raster")),

    Specialist("suite_tool_inventory.py", "Historische Werkzeugmatrix", "Historic tool inventory",
               "Prüfen", "Inspection", ("sha256", "versionen", "historisch", "duplikate")),
    Specialist("suite_compatibility_preflight.py", "Kompatibilitätsprüfung", "Compatibility preflight",
               "Prüfen", "Inspection", ("steam", "python", "abi", "runtime")),
    Specialist("suite_environment_discovery.py", "Spiel- und Entwicklungsumgebung erkennen", "Detect game and build environment",
               "Prüfen", "Inspection", ("automatisch", "steam", "unity", "python", "dotnet", "shcdese", "apishared", "serp")),
    Specialist("suite_runtime_capabilities.py", "Runtime-Capabilities und DLL-Signaturen", "Runtime capability and DLL signature inspection",
               "Prüfen", "Inspection", ("shcdese", "apishared", "serp", "dll", "pe", "sha256", "abi", "capability")),
    Specialist("suite_asset_inspector.py", "Gemeinsamer Sprite-, Atlas-, Masken- und XAML-Inspektor", "Shared sprite, atlas, mask and XAML inspector",
               "Prüfen", "Inspection", ("sprite", "atlas", "dds", "bc7", "mask", "maske", "material", "xaml", "noesis", "assets")),
    Specialist("grafik_analyse.py", "Grafikanalyse", "Graphics analysis",
               "Prüfen", "Inspection", ("bundles", "pixel", "bildvergleich", "atlas")),
    Specialist("grafik_diagnose.py", "Grafikdiagnose", "Graphics diagnosis",
               "Prüfen", "Inspection", ("fehler", "kacheln", "pivots")),
    Specialist("qa_suite_build_readiness.py", "Bauvoraussetzungen prüfen", "Check build readiness",
               "Prüfen", "Inspection", ("unity", "dotnet", "profil", "build")),
    Specialist("building_damage_layer_audit.py", "Gebäude-Grafiklayer und Footprints vergleichen",
               "Compare building graphical layers and gameplay footprints",
               "Prüfen", "Inspection", ("footprint", "tileimage", "layer", "sprite", "gameplay", "qa", "damage")),
    Specialist("suite_building_damage_live_mod.py", "HP- und Feuerschäden im Spiel",
               "Build and install HP/fire building damage runtime",
               "Paket", "Package", ("gebaude", "hp", "feuer", "fire", "mechanical", "schaden", "damage", "runtime", "bepinex", "mod", "install")),
    Specialist("building_damage_bindings.py", "Gebäudesprite-Zuordnungen frei bearbeiten",
               "Generate editable building sprite mappings",
               "Grafik", "Graphics", ("gebaude", "building", "slot", "sprite", "mapping", "rotation", "feuer", "damage")),
    Specialist("building_damage_package_check.py", "HP-/Feuerpaket prüfen",
               "Inspect building damage artwork and bindings",
               "Prüfen", "Inspection", ("gebaude", "hp", "fire", "damage", "png", "sha256", "zip")),
    Specialist("qa_building_damage_live.py", "Gebäude-Live-Renderer-Nachweis (QA-Klon)",
               "Live building renderer evidence (QA clone only)",
               "Prüfen", "Inspection", ("building", "footprint", "shcdese", "renderer", "live", "qa", "hp", "damage")),
    Specialist("qa_building_damage_runtime.py", "Gebäude-Runtime, Footprint und SHCDESE prüfen",
               "Audit building damage runtime and SHCDESE footprint",
               "Prüfen", "Inspection", ("footprint", "occupied tiles", "shcdese", "csharp", "hp", "damage", "renderer")),
    Specialist("building_damage_runtime_preflight.py", "Gebäude-Schadensmodelle prüfen",
               "Validate building damage libraries",
               "Prüfen", "Inspection", ("gebaeudeschaden", "hp", "fire", "mechanical", "sha256", "manifest")),
    Specialist("building_damage_original_reference.py", "Originalgebäude aus Renderer-Nachweisen",
               "Extract original building sprites from renderer evidence",
               "Grafik", "Graphics", ("original", "building", "granary", "reference", "sprite", "damage", "unity")),
    Specialist("origins_native_live_install.py", "Origins-Kampagne für das Spiel bauen",
               "Build Origins campaign for the game",
               "Paket", "Package", ("origins", "noesis", "xaml", "kampagne", "campaign", "runtime", "hud")),
    Specialist("building_damage_codex.py", "KI-Gebäudesprites mit Codex und ChatGPT",
               "AI building sprites with Codex and ChatGPT",
               "Grafik", "Graphics", ("zerstoerung", "destruction", "fire", "mechanical", "hp", "damage", "codex", "gpt image")),
    Specialist("suite_ai_codex.py", "KI-Werkstatt für Sprites und UI", "AI workshop for sprites and UI",
               "Grafik", "Graphics", ("ki", "gpt image", "sprite", "animation", "einheiten", "hud", "kandidat", "freigabe", "codex")),
    Specialist("suite_live_noesis_log_audit.py", "Noesis-Liveprotokoll prüfen",
               "Inspect live Noesis logs",
               "Prüfen", "Inspection", ("noesis", "in-game", "xaml", "log", "hud", "script extender")),
    Specialist("qa_workstream_census.py", "Arbeitszweige und Änderungen prüfen",
               "Audit branches and worktrees",
               "Prüfen", "Inspection", ("git", "worktree", "entwicklung", "abgleich", "audit")),
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
    Specialist("ui_atlas_workspace.py", "UI-Atlas aus PNG und XAML bearbeiten", "Edit UI atlas from PNG and XAML",
               "Atlas", "Atlas", ("masteratlas", "crops", "replace", "undo", "png", "xaml")),
    Specialist("se_atlas.py", "Script-Extender-AtlasBuilder", "Script Extender AtlasBuilder",
               "Atlas", "Atlas", ("bc7", "dds", "override")),
    Specialist("background_v2_pipeline.py", "Hintergrund-Pipeline", "Background pipeline",
               "Atlas", "Atlas", ("background", "mask", "europe")),
    Specialist("origins_grafikdaten.py", "Origins-Grafikdaten", "Origins graphics",
               "Atlas", "Atlas", ("origins", "lfs", "ui")),
    Specialist("se_asset_package.py", "Freies Modpaket", "Unrestricted mod package",
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
    # A previously entered filter must not hide the selected specialist.
    search = getattr(app, "catalog_search", None)
    if search is not None:
        search.set("")
    app.open_tab(page)
    choice.set(filename)
    loader()

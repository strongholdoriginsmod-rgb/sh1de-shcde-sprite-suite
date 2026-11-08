"""Declarative risk labels for dynamically generated specialist-tool forms.

Unlisted actions are *unknown*, never silently treated as read-only. This is
UI guidance; every real write is still governed by the tool's own validators.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ToolPolicy:
    category: str
    de: str
    requires_confirmation: bool = True


READ=ToolPolicy("read","Nur lesende Diagnose", requires_confirmation=False)
WORK=ToolPolicy("workspace","Erzeugt oder verändert Dateien im Arbeitsbereich", requires_confirmation=False)
GAME=ToolPolicy("game","Kann eine ausgewählte Spiel-/QA-Installation verändern")
NETWORK=ToolPolicy("external","Kann externe Ressourcen abrufen")
UNKNOWN=ToolPolicy("unknown","Seiteneffekte nicht klassifiziert – Eingaben sorgfältig prüfen")

RISK_TOOLS: dict[str,ToolPolicy]={
    "modding_studio.py":WORK,
    "building_damage_native_bindings.py":WORK,
    "qa_hp_fire_live_log.py":READ,
    "qa_hp_fire_game_evidence.py":READ,
    "suite_tool_inventory.py":READ,
    "suite_environment_discovery.py":READ,
    "suite_runtime_capabilities.py":READ,
    "suite_asset_inspector.py":READ,
    "suite_ai_codex.py":NETWORK,
    "building_damage_layer_audit.py":READ,
    "qa_building_damage_runtime.py":WORK,
    "qa_building_damage_live.py":GAME,
    "suite_building_damage_live_mod.py":WORK,
    "building_damage_bindings.py":WORK,
    "building_damage_package_check.py":READ,
    "building_damage_codex.py":NETWORK,
    "building_damage_original_reference.py":WORK,
    "building_damage_runtime_preflight.py":READ,
    "suite_live_noesis_log_audit.py":READ,
    "qa_workstream_census.py":READ,
    "build_portable_windows.py":WORK,
    "background_v2_pipeline.py":WORK,
    "ui_atlas_layout_port.py":WORK,
    "ui_apply.py":WORK,
    "ui_einpflegen.py":WORK,
    "ui_sh1_umstellung.py":WORK,
    "ui_sh1_unity_patch.py":WORK,
    "se_asset_package.py":WORK,
    "hud_menu_project_transfer.py":WORK,
    "suite_workflow.py":WORK,
    "ui_atlas.py":WORK,
    "ui_atlas_workspace.py":WORK,
    "suite_ui_atlas_workspace.py":WORK,
    "ui_extra_atlas.py":WORK,
    "build_locale.py":WORK,
    "sprites.py":WORK,
    "project_inputs.py":WORK,
    "origins_grafikdaten.py":NETWORK,
    "ziel_se211.py":GAME,
}


def classify(tool: str, args: list[str] | tuple[str,...]) -> ToolPolicy:
    if "--help" in args or "-h" in args:
        return READ
    name=Path(tool).name
    command={arg.casefold() for arg in args}
    if name=="ui_atlas_workspace.py":
        return READ if command & {"info", "list"} else WORK
    if name in {"Suite","Pipeline","suite_workflow.py"}:
        if "install" in command or "uninstall" in command:
            return GAME
        if "check" in command or "doctor" in command or "verify" in command:
            return READ
        return WORK
    if name=="suite_building_damage_live_mod.py":
        return GAME if "--install" in command else WORK
    if name=="qa_building_damage_live.py":
        if "--install-qa" in command or "--remove-qa" in command:
            return GAME
        if "--verify-log" in command:
            return READ
        return WORK  # build-only compiles into isolated temporary workspace
    if name in {"qa_hp_fire_live_log.py", "qa_hp_fire_game_evidence.py"}:
        return WORK if "--output" in command else READ
    if name in {"shcde_game_inspector.py", "shcde_gameplay_rules.py"}:
        return GAME if {"--install", "--remove", "install", "remove"} & command else WORK
    if name == "shcde_workbench.py":
        return READ if {"--catalog", "--self-test"} & command else WORK
    if name in {"shcde_mod_project.py", "shcde_mod_composer.py"}:
        return READ if {"inspect", "plan"} & command else WORK
    if name in {"shcde_api_native_index.py", "shcde_pathing_report.py",
                "shcde_mod_settings.py", "shcde_aiv_lord_studio.py",
                "shcde_scenario_graph.py", "shcde_qa_suite.py"}:
        return WORK if {"--output", "--report", "export", "build", "package", "set", "new"} & command else READ
    if name=="modding_studio.py":
        return READ if command & {"modules", "catalog", "check", "native-search", "api-search"} else WORK
    if name=="building_damage_layer_audit.py":
        return WORK if "--output" in command else READ
    if name=="building_damage_runtime_preflight.py":
        return WORK if "--prepare" in command else READ
    if name=="suite_live_noesis_log_audit.py":
        return WORK if "--out" in command else READ
    if name=="qa_workstream_census.py":
        return WORK if "--out" in command else READ
    if name=="origins_native_live_install.py":
        return GAME if {"--install", "--rollback"} & command else WORK
    if name=="suite_ai_codex.py":
        return NETWORK if "--execute" in command else WORK
    if name=="building_damage_codex.py":
        return NETWORK if {"--execute", "--login"} & command else READ
    if name=="ziel_se211.py":
        if {"installieren","deinstallieren","zurueckspielen"} & command:
            return GAME
        return UNKNOWN
    if name=="project_inputs.py":
        if "install" in command and "--write" not in command:
            return READ
        return WORK
    return RISK_TOOLS.get(name,UNKNOWN)


def explain(tool: str, args: list[str] | tuple[str,...]) -> str:
    policy=classify(tool,args)
    return f"Risikoklasse: {policy.de}.\nBitte Quelldateien, Zielordner und Sicherungen prüfen."

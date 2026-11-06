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
    requires_confirmation: bool = False


READ=ToolPolicy("read","Nur lesende Diagnose")
WORK=ToolPolicy("workspace","Erzeugt oder verändert Dateien im Arbeitsbereich")
GAME=ToolPolicy("game","Kann eine ausgewählte Spiel-/QA-Installation verändern")
NETWORK=ToolPolicy("external","Kann externe Ressourcen abrufen")
UNKNOWN=ToolPolicy("unknown","Seiteneffekte nicht klassifiziert – Eingaben sorgfältig prüfen")

RISK_TOOLS: dict[str,ToolPolicy]={
    "suite_tool_inventory.py":READ,
    "qa_building_damage_runtime.py":WORK,
    "qa_building_damage_live.py":GAME,
    "building_damage_codex.py":NETWORK,
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
    if name in {"Suite","Pipeline","suite_workflow.py"}:
        if "install" in command or "uninstall" in command:
            return GAME
        if "check" in command or "doctor" in command or "verify" in command:
            return READ
        return WORK
    if name=="qa_building_damage_live.py":
        if "--install-qa" in command or "--remove-qa" in command:
            return GAME
        if "--verify-log" in command:
            return READ
        return WORK  # build-only compiles into isolated temporary workspace
    if name=="building_damage_runtime_preflight.py":
        return WORK if "--prepare" in command else READ
    if name=="suite_live_noesis_log_audit.py":
        return WORK if "--out" in command else READ
    if name=="qa_workstream_census.py":
        return WORK if "--out" in command else READ
    if name=="building_damage_codex.py":
        return NETWORK if "--execute" in command else READ
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

# Sprite Suite: model- and data-focused Sandbox QA without visible windows.
#
# All test modules are selected explicitly. Any future test module that
# imports Tkinter is rejected here rather than secretly opening a window.
# PySide6 tests use QT_QPA_PLATFORM=offscreen and have no visible desktop.
# No original game files, installed resources or release output are written.
#
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools/qa_sandbox_headless.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Project venv missing: $python"
}
$env:QT_QPA_PLATFORM = "offscreen"
$env:SEDE_SPRACHE = "de"
$env:PYTHONDONTWRITEBYTECODE = "1"
$tests = @(
    "test_map_sections",
    "test_native_runtime",
    "test_radar_projection",
    "test_radar_calibration",
    "test_map_importer",
    "test_scene_model",
    "test_native_overlay",
    "test_native_layers",
    "test_native_surface_mapping",
    "test_native_terrain_mapping",
    "test_native_visual_mapping",
    "test_original_trees",
    "test_start_keep_audit",
    "test_maps_configuration",
    "test_pivot_native_provenance",
    "test_save_destination_safety",
    "test_model_payload_integrity",
    "test_native_tile_bijection",
    "test_pivot_bc7_cache",
    "test_mapping_save_destination_safety",
    "test_hud_original_art",
    "test_animation_panel",
    "test_editor_workflow",
    "test_pixel_editor_integration",
    "test_cross_workspace_navigation",
    "test_gameplay_mode_workspace",
    "test_sandbox_compact_layout",
    "test_hud_compact_workflow",
    "test_original_scene_compatibility",
    "test_original_tool_contracts"
) | ForEach-Object { Join-Path $root ("tests\sandbox\" + $_ + ".py") }
foreach ($path in $tests) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Missing headless Sandbox test: $path"
    }
    if (Select-String -LiteralPath $path -Pattern '\btkinter\b|\btk\.Tk\s*\(' -Quiet) {
        throw "Headless test unexpectedly opens Tk: $path"
    }
}
$reports = Join-Path $root "work\reports\ui-audit"
New-Item -ItemType Directory -Force -Path $reports | Out-Null
$junit = Join-Path $reports "sandbox-headless-system-20261021.xml"
Write-Output "HEADLESS_SANDBOX_MODULES=$($tests.Count)"
Write-Output "HEADLESS_QT_PLATFORM=$env:QT_QPA_PLATFORM"
Write-Output "HEADLESS_JUNIT=$junit"
& $python -m pytest -q --disable-warnings "--junitxml=$junit" @tests
exit $LASTEXITCODE

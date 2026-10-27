# Additional Sprite Suite headless coverage beyond the 28-module baseline.
# No Tk/win32 desktop APIs; Qt is forced to the offscreen QPA platform.
# All test modules were reviewed for explicit process execution and are
# constrained to tmp_path / read-only original-game input where applicable.
# This is NOT the native Windows/Tk acceptance suite or release certification.
$ErrorActionPreference="Stop"
$root=Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root
$py=Join-Path $root ".venv\Scripts\python.exe"
if(-not (Test-Path -LiteralPath $py -PathType Leaf)){throw "Python missing"}
$env:QT_QPA_PLATFORM="offscreen"
$env:SEDE_SPRACHE="de"
$env:PYTHONDONTWRITEBYTECODE="1"
$names=@(
    "test_asset_preview",
    "test_engine_assets",
    "test_engine_export_atomicity",
    "test_engine_sprite_picking",
    "test_engine_tile_colours",
    "test_gameplay_artwork_cache",
    "test_gameplay_context_states",
    "test_gui_smoke",
    "test_hud_chrome_geometry",
    "test_native_canvas",
    "test_native_engine_seams",
    "test_original_hud_crop_provider",
    "test_original_visual_gui",
    "test_overlay_recovery",
    "test_pivot_native_proof_rows",
    "test_pixel_editor",
    "test_qt_language_accessibility",
    "test_original_gui_command_parity",
    "test_legacy_v1_editor_lossless",
    "test_target_selection_version_guard",
    "test_community_mod_compat",
    "test_studio_action_wiring",
    "test_sandbox_png_export",
    "test_reference_compare",
    "test_runtime_renderer_gui",
    "test_sprite_palette",
    "test_studio_live_reload",
    "test_test_board",
    "test_scribe_manual_reference",
    "test_ui_bc7_crops",
    "test_native_layers_gui",
    "test_pivot_bc7_rehearsal",
    "test_pivot_build_stage",
    "test_release_preflight",
    "test_suite_build_completion",
    "test_suite_build_history",
    "test_qa_inventory"
)
$tests=@($names | ForEach-Object {Join-Path $root ("tests\sandbox\"+$_+".py")})
foreach($file in $tests){
    if(-not (Test-Path -LiteralPath $file -PathType Leaf)){throw "Missing: $file"}
    if(Select-String -LiteralPath $file -Pattern '\btkinter\b|\btk\.Tk\s*\(|\bToplevel\s*\(|\bmainloop\s*\(|\bsubprocess\b|\bPopen\s*\(' -Quiet){
        throw "Rejected module with desktop/process launch call: $file"
    }
}
$reports=Join-Path $root "work\reports\ui-audit"
New-Item -ItemType Directory -Force -Path $reports | Out-Null
$xml=Join-Path $reports "sandbox-headless-additional-20261022.xml"
Write-Output "ADDITIONAL_HEADLESS_MODULES=$($tests.Count)"
Write-Output "QT_QPA_PLATFORM=$env:QT_QPA_PLATFORM"
Write-Output "JUNIT=$xml"
& $py -m pytest -q --disable-warnings "--junitxml=$xml" @tests
exit $LASTEXITCODE

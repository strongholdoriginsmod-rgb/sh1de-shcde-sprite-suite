# Sprite Suite full offscreen/model acceptance over BOTH independently
# approved headless module lists. One pytest interpreter catches cross-module
# state leakage that two individually green runs could miss.
# No Tk roots, windows, game writes, installs, or release builders.
$ErrorActionPreference="Stop"
$project=Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $project
$py=Join-Path $project ".venv\Scripts\python.exe"
if(-not (Test-Path -LiteralPath $py -PathType Leaf)){throw "Virtualenv missing"}
$env:QT_QPA_PLATFORM="offscreen"
$env:SEDE_SPRACHE="de"
$env:PYTHONDONTWRITEBYTECODE="1"
$base=Join-Path $PSScriptRoot "qa_sandbox_headless.ps1"
$additional=Join-Path $PSScriptRoot "qa_sandbox_headless_additional.ps1"
$moduleNames=@(
    foreach($file in @($base,$additional)){
        if(-not (Test-Path -LiteralPath $file)){throw "Headless scope file missing: $file"}
        foreach($line in Get-Content -LiteralPath $file){
            if($line -match '^\s*"(test_[A-Za-z0-9_]+)"\s*,?\s*$'){
                $Matches[1]
            }
        }
    }
)
if($moduleNames.Count -ne 67){throw "Unexpected module count: $($moduleNames.Count)"}
if(($moduleNames|Sort-Object -Unique).Count -ne $moduleNames.Count){
    throw "Duplicate headless test module across lists"
}
$tests=@()
foreach($name in $moduleNames){
    $path=Join-Path $project ("tests\sandbox\"+$name+".py")
    if(-not (Test-Path -LiteralPath $path -PathType Leaf)){
        throw "Missing Sandbox test: $name"
    }
    if(Select-String -LiteralPath $path -Pattern '\btkinter\b|\btk\.Tk\s*\(|\bToplevel\s*\(|\bmainloop\s*\(' -Quiet){
        throw "Tk desktop test rejected from headless system run: $path"
    }
    $tests+=$path
}
$reportRoot=Join-Path $project "work\reports\ui-audit"
New-Item -ItemType Directory -Force -Path $reportRoot|Out-Null
$junit=Join-Path $reportRoot "sandbox-headless-community-67modules-qt-stable-20261022.xml"
Write-Output "HEADLESS_SYSTEM_MODULES=$($tests.Count)"
Write-Output "QT_QPA_PLATFORM=$env:QT_QPA_PLATFORM"
Write-Output "HEADLESS_COMBINED_JUNIT=$junit"
& $py -m pytest -q --disable-warnings "--junitxml=$junit" @tests
$testExit=$LASTEXITCODE
Write-Output "HEADLESS_PYTEST_EXIT=$testExit"
exit $testExit

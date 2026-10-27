param([string]$Python = '', [string]$Wheelhouse = '')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
    if ($Python) { & $Python -m venv .venv }
    else { & py -3.13 -m venv .venv }
    if ($LASTEXITCODE -ne 0) { throw 'Python-Umgebung konnte nicht erstellt werden.' }
}
$suitePython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
$installArgs = @('-m', 'pip', 'install', '--require-hashes', '-r', 'requirements-py313-win_amd64.lock')
if ($Wheelhouse) { $installArgs += @('--no-index', '--find-links', $Wheelhouse) }
& $suitePython @installArgs
if ($LASTEXITCODE -ne 0) { throw 'Abhaengigkeiten konnten nicht hashgeprueft installiert werden.' }
& $suitePython -m pip install --no-build-isolation --no-deps -e .
if ($LASTEXITCODE -ne 0) { throw 'Lokales Paket konnte nicht installiert werden.' }
& $suitePython -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Abhaengigkeitspruefung fehlgeschlagen.' }
Write-Host 'Bereit. Weiter: ./.venv/Scripts/python.exe suite.py configure --help'

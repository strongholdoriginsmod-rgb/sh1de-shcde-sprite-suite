param([string]$Python = '', [string]$Wheelhouse = '')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

# For source checkouts only. The Windows portable ZIP has Python bundled.
$venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$choice = $null
if (-not (Test-Path -LiteralPath $venvPython)) {
    $candidates = @()
    if ($Python) {
        $candidates += ,@{ Executable = $Python; Args = @() }
    } else {
        $candidates += ,@{ Executable = 'py'; Args = @('-3.13') }
        $candidates += ,@{ Executable = 'py'; Args = @('-3.14') }
    }
    foreach ($candidate in $candidates) {
        try {
            $arguments = @($candidate.Args)
            $text = (& $candidate.Executable @arguments --version 2>&1 | Out-String).Trim()
            if ($LASTEXITCODE -eq 0 -and $text -match '^Python 3\.(13|14)\.') {
                $choice = $candidate
                break
            }
        } catch { continue }
    }
    if (-not $choice) {
        throw ('Python 3.13/3.14 fehlt. Fuer Windows ohne Python bitte ' +
               'das SpriteSuite-Windows-Portable-ZIP aus GitHub Releases ' +
               'herunterladen, entpacken und Suite starten.cmd ausfuehren.')
    }
    $arguments = @($choice.Args)
    & $choice.Executable @arguments -m venv '.venv'
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $venvPython)) {
        throw 'Python-Umgebung konnte nicht erstellt werden.'
    }
}
$version = (& $venvPython -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")').Trim()
if ($LASTEXITCODE -ne 0 -or $version -notin @('3.13', '3.14')) {
    throw ('Fuer diesen Quellcode-Build wird Python 3.13/3.14 benoetigt. ' +
           'Ohne Python bitte das Windows-Portable-ZIP nutzen.')
}
$lock = ('requirements-py{0}-win_amd64.lock' -f ($version -replace '\.', ''))
if (-not (Test-Path -LiteralPath $lock)) { throw ('Hash-Lock fehlt: ' + $lock) }
$installArgs = @('-m', 'pip', 'install', '--require-hashes', '-r', $lock)
if ($Wheelhouse) { $installArgs += @('--no-index', '--find-links', $Wheelhouse) }
& $venvPython @installArgs
if ($LASTEXITCODE -ne 0) { throw 'Abhaengigkeiten konnten nicht hashgeprueft installiert werden.' }
& $venvPython -m pip install --no-build-isolation --no-deps -e .
if ($LASTEXITCODE -ne 0) { throw 'Lokales Paket konnte nicht installiert werden.' }
& $venvPython -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Abhaengigkeitspruefung fehlgeschlagen.' }
Write-Host 'Bereit. Weiter: ./.venv/Scripts/python.exe suite.py configure --help'

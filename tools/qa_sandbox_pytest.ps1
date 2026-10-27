# Run the installed Windows venv's Sandbox tests with a STABLE Tcl/Tk startup.
#
# Windows Tk sometimes fails to load a DIFFERENT ttk/*.tcl file on a later
# independent Tk() in a long pytest process, even when those files exist.
# Setting TCL_LIBRARY / TK_LIBRARY from within Python was too late on this
# toolchain. This script sets them in the launching PowerShell process,
# BEFORE the test Python interpreter is created.
#
# Usage:
# powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\qa_sandbox_pytest.ps1 -q tests\sandbox
#
# No system environment changes, installed game modifications, or builds.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Missing project virtualenv Python: $python"
}
$basePrefix = (& $python -c 'import sys; print(sys.base_prefix)') | Select-Object -Last 1
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($basePrefix)) {
    throw 'Cannot resolve Python base prefix for local Tcl/Tk'
}
$tclBase = Join-Path $basePrefix 'tcl'
$tcl = Join-Path $tclBase 'tcl8.6'
$tk = Join-Path $tclBase 'tk8.6'
foreach ($file in @(
    (Join-Path $tcl 'init.tcl'),
    (Join-Path $tk 'tk.tcl'),
    (Join-Path $tk 'ttk\defaults.tcl'),
    (Join-Path $tk 'ttk\utils.tcl'),
    (Join-Path $tk 'ttk\combobox.tcl')
)) {
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) {
        throw "Python Tcl/Tk installation incomplete: $file"
    }
}
$env:TCL_LIBRARY = $tcl
$env:TK_LIBRARY = $tk
Write-Output "QA_TCL_TK_BEFORE_PYTHON_START: $tcl | $tk"
& $python -m pytest @args
exit $LASTEXITCODE

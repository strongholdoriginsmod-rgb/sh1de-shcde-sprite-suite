$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
$python=Join-Path $root '.venv\Scripts\python.exe'
$prefix=(& $python -c 'import sys; print(sys.base_prefix)') | Select-Object -Last 1
if ($LASTEXITCODE -ne 0) { throw 'Cannot read Python base prefix' }
$tcl=Join-Path $prefix 'tcl\tcl8.6'
$tk=Join-Path $prefix 'tcl\tk8.6'
foreach($f in @((Join-Path $tcl 'init.tcl'),(Join-Path $tk 'tk.tcl'),(Join-Path $tk 'ttk\combobox.tcl'),(Join-Path $tk 'spinbox.tcl'))) {
    if(-not (Test-Path -LiteralPath $f)) {throw "Missing Tcl/Tk file: $f"}
}
$env:TCL_LIBRARY=$tcl
$env:TK_LIBRARY=$tk
Write-Output "NATIVE_TK_STARTUP=$tcl | $tk"
& $python (Join-Path $root 'work\qa_native_windows_lifecycle_20261022.py') @args
exit $LASTEXITCODE

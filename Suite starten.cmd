@echo off
rem Stronghold Europe / ORIGINS - Universal-Suite starten (start the universal suite)
setlocal
set "ROOT=%~dp0"
if not exist "%ROOT%python\python.exe" if exist "%ROOT%komplett\python-mit-paketen.zip" (
  echo Entpacke mitgeliefertes Python ... / unpacking bundled Python ...
  powershell -NoProfile -Command "Expand-Archive -LiteralPath '%ROOT%komplett\python-mit-paketen.zip' -DestinationPath '%ROOT%' -Force"
)
if exist "%ROOT%python\python.exe" (
  "%ROOT%python\python.exe" "%ROOT%tools\suite_start.py" %*
  goto ende
)
if not exist "%ROOT%.venv\Scripts\python.exe" (
  echo Erste Einrichtung: Python-Umgebung wird angelegt ... / first run: creating the Python environment ...
  powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%setup.ps1"
)
"%ROOT%.venv\Scripts\python.exe" "%ROOT%tools\suite_start.py" %*
:ende
if errorlevel 1 pause

@echo off
rem Portable Windows ZIP: python\python.exe and .venv are included.
rem Source checkout: setup.ps1 supports installed Python 3.13/3.14.
setlocal
set "ROOT=%~dp0"
if not exist "%ROOT%python\python.exe" if exist "%ROOT%komplett\python-mit-paketen.zip" (
  echo Entpacke mitgeliefertes Python ... / unpacking bundled Python ...
  powershell -NoProfile -Command "Expand-Archive -LiteralPath '%ROOT%komplett\python-mit-paketen.zip' -DestinationPath '%ROOT%' -Force"
  if errorlevel 1 goto fehler
)
if exist "%ROOT%python\python.exe" (
  "%ROOT%python\python.exe" "%ROOT%tools\suite_start.py" %*
  goto ende
)
if not exist "%ROOT%.venv\Scripts\python.exe" (
  echo Python-Umgebung fehlt. Richte Quellcode-Version ein ...
  powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%setup.ps1"
  if errorlevel 1 goto fehler
)
if not exist "%ROOT%.venv\Scripts\python.exe" goto fehler
"%ROOT%.venv\Scripts\python.exe" "%ROOT%tools\suite_start.py" %*
goto ende
:fehler
echo.
echo Die Suite konnte nicht gestartet werden.
echo Ohne Python-Installation bitte die Windows-Portable-ZIP aus den
echo GitHub-Releases herunterladen und vollstaendig entpacken.
pause
exit /b 1
:ende
if errorlevel 1 pause
exit /b %errorlevel%

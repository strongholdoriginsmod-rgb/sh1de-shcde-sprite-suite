@echo off
rem Portable Windows: initialize the private Python environment before Qt.
rem Source checkout: preserve the existing .venv/portable fallback.
setlocal
set "ROOT=%~dp0"
if exist "%ROOT%python\python.exe" (
  "%ROOT%python\python.exe" "%ROOT%tools\suite_start.py" --portable-bootstrap
  if errorlevel 1 goto fehler
)
if exist "%ROOT%.venv\Scripts\python.exe" (
  "%ROOT%.venv\Scripts\python.exe" "%ROOT%tools\sandbox_studio.py" %*
  goto ende
)
if exist "%ROOT%python\python.exe" (
  echo Portable Python-Umgebung nicht gefunden.
) else (
  echo Python-Umgebung fehlt. Zuerst Suite starten.cmd verwenden.
)
goto fehler
:fehler
echo.
echo Sandbox Studio konnte nicht gestartet werden.
pause
exit /b 1
:ende
if errorlevel 1 pause
exit /b %errorlevel%

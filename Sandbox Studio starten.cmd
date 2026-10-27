@echo off
setlocal
set "ROOT=%~dp0"
if exist "%ROOT%.venv\Scripts\python.exe" (
  "%ROOT%.venv\Scripts\python.exe" "%ROOT%tools\sandbox_studio.py" %*
) else if exist "%ROOT%python\python.exe" (
  "%ROOT%python\python.exe" "%ROOT%tools\sandbox_studio.py" %*
) else (
  echo Python-Umgebung fehlt. Zuerst Suite starten.cmd verwenden.
  exit /b 1
)
if errorlevel 1 pause

@echo off
setlocal
cd /d "%~dp0"
if not exist "%~dp0.venv\Scripts\python.exe" (
  echo SpriteSuite-Python fehlt: .venv\Scripts\python.exe
  echo Bitte zuerst die reguläre SpriteSuite-Einrichtung abschliessen.
  pause
  exit /b 2
)
"%~dp0.venv\Scripts\python.exe" "%~dp0tools\modding_studio.py" gui
if errorlevel 1 (
  echo Modding Studio konnte nicht gestartet werden. Siehe Fehlermeldung oben.
  pause
  exit /b 1
)
endlocal

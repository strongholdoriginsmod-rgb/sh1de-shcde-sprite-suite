@echo off
rem HTML-Sprite-Editor oeffnen (DE/EN umschaltbar) / open the HTML sprite editor (DE/EN)
if exist "%~dp0python\pythonw.exe" (
  start "" "%~dp0python\pythonw.exe" "%~dp0tools\sprite_editor_local.py" en
  exit /b
)
if exist "%~dp0.venv\Scripts\pythonw.exe" (
  start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0tools\sprite_editor_local.py" en
  exit /b
)
start "" "%~dp0extras\sprite-editor\Stronghold_Sprite_Editor_EN.html"

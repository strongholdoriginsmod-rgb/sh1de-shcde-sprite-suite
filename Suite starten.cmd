@echo off
rem Windows start package installs its locked dependencies on first launch.
rem The offline portable ZIP already contains its configured .venv.
setlocal
set "ROOT=%~dp0"
set "PS=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%ROOT%python\python.exe" if exist "%ROOT%komplett\python-mit-paketen.zip" (
  echo Entpacke mitgeliefertes Python ... / unpacking bundled Python ...
  "%PS%" -NoProfile -Command "Expand-Archive -LiteralPath '%ROOT%komplett\python-mit-paketen.zip' -DestinationPath '%ROOT%' -Force"
  if errorlevel 1 goto fehler
)
if exist "%ROOT%python\python.exe" goto mit_python
if not exist "%ROOT%.venv\Scripts\python.exe" (
  echo Python-Umgebung fehlt. Richte Quellcode-Version ein ...
  "%PS%" -NoProfile -ExecutionPolicy Bypass -File "%ROOT%setup.ps1"
  if errorlevel 1 goto fehler
)
if not exist "%ROOT%.venv\Scripts\python.exe" goto fehler
"%ROOT%.venv\Scripts\python.exe" "%ROOT%tools\suite_start.py" %*
goto ende
:mit_python
if not exist "%ROOT%.venv\Scripts\python.exe" goto einrichten
if exist "%ROOT%START-PACKAGE.json" if not exist "%ROOT%.venv\spritesuite-start-ready.txt" goto einrichten
goto starten
:einrichten
echo Erster Start: Die Python-Abhaengigkeiten werden aus PyPI geladen.
echo Dafuer wird eine Internetverbindung benoetigt. Details: FIRST-RUN.txt
"%PS%" -NoProfile -ExecutionPolicy Bypass -File "%ROOT%setup.ps1" -Python "%ROOT%python\python.exe"
if errorlevel 1 goto fehler
if not exist "%ROOT%.venv\Scripts\python.exe" goto fehler
if exist "%ROOT%START-PACKAGE.json" (
  > "%ROOT%.venv\spritesuite-start-ready.txt" echo configured
  if errorlevel 1 goto fehler
)
:starten
"%ROOT%python\python.exe" "%ROOT%tools\suite_start.py" %*
goto ende
:fehler
echo.
echo Die Suite konnte nicht gestartet werden.
echo Startpaket: Internetverbindung pruefen, FIRST-RUN.txt lesen und erneut starten.
echo Quellcode-Version: Python 3.13/3.14 installieren oder das Windows-Startpaket nutzen.
pause
exit /b 1
:ende
set "SUITE_EXIT=%errorlevel%"
if not "%SUITE_EXIT%"=="0" pause
exit /b %SUITE_EXIT%

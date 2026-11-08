# SpriteSuite 3 – synthetisches Beispiel

Dieses Beispiel enthält **keine Dateien aus Stronghold oder APIShared**.

```powershell
.\.venv\Scripts\python.exe tools\modding_studio.py check examples\modding-studio
.\.venv\Scripts\python.exe tools\modding_studio.py simulate examples\modding-studio --events events.json
```

In einer normalen Entwicklerinstallation außerhalb des Repositorys am besten das
ganze Beispiel in den persönlichen Arbeitsordner unter `work/studios/` kopieren
(als neues Projekt, ohne vorhandene Daten zu überschreiben).

`sounds/test_tone.wav` ist ein künstlich erzeugter, leiser kurzer Testton
und keine Original-Spielgrafik oder -musik. `events.json` liefert einen
`mission_start`-Event bei Tick 0 und einen Goldwert bei Tick 50.
Die Suite erzeugt daraus keine Ingame-Mission oder live Engine-Befehle.

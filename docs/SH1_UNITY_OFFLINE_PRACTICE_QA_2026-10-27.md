# Stronghold 1 DE – Offline-Unity-HUD-Kandidat: Praxisprüfung (27.10.2026)

Der SpriteSuite-Befehl `tools/ui_sh1_unity_patch.py` erzeugt aus einem lokal exportierten Stronghold-1-HUD und einer **exakt übereinstimmenden Original-Unity-Datei** eine isolierte, erneut lesbare `globalgamemanagers.assets`.

## Verifizierte Durchführung

Testumgebung: eigene lokale Stronghold-1-DE-Installation; `UnityPy 1.25.3` und `Pillow 12.3.0`. Die Original-Quelldatei blieb unverändert; alle Testausgaben wurden unter `dist/` angelegt und sind **nicht Teil des Git-Repositories**.

| Szenario | Ergebnis |
|---|---|
| Unveränderte HUD-Arbeitskopie (1.391 Sprites) | **Bestanden.** 0 Patches; erzeugte Unity-Datei SHA-256-identisch mit dem Original |
| Isolierte QA-Kopie mit einer Pixeländerung in `UI-HUD 005`, `ROL-A001` und `Candle01` | **Bestanden.** Drei bearbeitete Sprites, genau drei Byte-Patches |
| `UI-MasterAtlas` (RGBA32, 8192 × 4096) | **Bestanden.** Ein geänderter Pixel, pixelgetreue Prüfung nach Unity-Reopen |
| `UI-ROL` (BC7, 4096 × 4096) | **Bestanden.** Genau ein neu kodierter 4×4-Block, keine sichtbare Kanalabweichung im Testfall |
| `UI-CandleAtlas` (BC7, 2048 × 4096) | **Bestanden.** Genau ein neu kodierter 4×4-Block, keine sichtbare Kanalabweichung im Testfall |
| Quellbindung | **Bestanden.** Drei native XAML-Dictionaries und drei Originalbaseline-Atlanten direkt gegen den Unity-Container validiert |
| Automatisierte Regressionstests für HUD-/Unity-Werkzeuge | **37 bestanden** im geprüften Branchzustand |

Die Tests nutzten ausschließlich lokal vorhandene, eigene Originalressourcen; **keine** proprietären Unity-Asset-Dateien oder PNG-Atlanten werden mit GitLab verteilt.

## Reproduzierbarer Offline-Befehl

Im Wurzelverzeichnis der Sprite Suite (Windows; Pfad zur eigenen Installation anpassen):

```powershell
.venv\Scripts\python.exe tools\ui_sh1_unity_patch.py --source "D:\Pfad\Stronghold 1 Definitive Edition_Data\globalgamemanagers.assets" --from work/sh1-hud-editierbar --out dist/sh1-hud-unity-kandidat
```

Die Ausgabe ist `dist/sh1-hud-unity-kandidat/globalgamemanagers.assets` mit `sh1_unity_hud_candidate.json` (Hashwerte, Änderungen, Geometrie und Qualität) und `BITTE_LESEN.md`. Die Eingabe muss zum Export-SHA-256 passen. Die PNGs werden nicht automatisch in das installierte Spiel übernommen.

## Was noch **nicht** nachgewiesen ist

Der Unity-Kandidat wurde offline serialisierungs- und pixeltechnisch geprüft, **aber nicht im laufenden Spiel getestet**. Eine automatisierte Installation in die Originalinstallation wird absichtlich **nicht** ausgeführt. Ein Einbau muss separat gegen den genauen Spielbuild, HUD-Anzeige, Interaktion, Start-/Speicherstände und vollständigen Rückbau geprüft werden. BC7 ist verlustbehaftet; die Grenzwerte des Werkzeugs bleiben aktiv.

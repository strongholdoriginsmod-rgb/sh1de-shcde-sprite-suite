# Stronghold 1 DE: HUD in Sprite Suite bearbeiten

Die Sprite Suite erhält hier einen eigenen **Stronghold-1-Definitive-Edition-HUD-Editor**. Das Modul verwendet drei originale Stronghold-1-UI-Atlanten und deren **aus den MonoBehaviour-Objekten der eigenen Spielinstallation ausgelesene XAML-Rechtecke**. Das ist ausdrücklich **kein** Crusader-DE-UI-Layout.

## Bearbeitungsumfang

| Originalatlas | Abmessungen | UI-Ausschnitte |
|---|---:|---:|
| `UI-MasterAtlas` | 8192 × 4096 | 1.323 |
| `UI-ROL` | 4096 × 4096 | 55 |
| `UI-CandleAtlas` | 2048 × 4096 | 13 |
| **Summe** | | **1.391** |

Das Original-HUD enthält u.a. Elemente mit Schlüsseln wie `UI-HUD 005` und `UI-HUD 007`. Einzelbilder lassen sich pixelgenau verändern und in drei Gesamtatlanten zurückführen. Bildabmessungen und ursprüngliche Spritepositionen werden geprüft.

## Voraussetzungen

- Ein eigenes, rechtmäßig zugängliches **Stronghold 1 Definitive Edition** mit `Stronghold 1 Definitive Edition_Data/globalgamemanagers.assets`.
- Eine eingerichtete Sprite Suite mit dem bestehenden Projekt-Python und den Paketen **Pillow** sowie **UnityPy**. Optional für die GUI ein Windows-PC mit tkinter.
- Ausreichend freier Speicherplatz für drei große PNG-Atlanten und über tausend editierbare Einzelbilder.
- **Keine Original-Grafikdateien sind Teil dieses öffentlichen Repositorys.** Sie werden lokal aus deiner eigenen Spielinstallation erzeugt.

## Einrichten und HUD starten

Nach dem Auschecken dieses Branches aus dem Projektordner (unter Windows):

```powershell
.venv\Scripts\python.exe tools\ui_sh1_hud.py export --source "D:\Pfad\zu\Stronghold 1 Definitive Edition_Data\globalgamemanagers.assets" --out work/sh1-hud-editierbar
```

Die lokal gewonnenen 1.391 PNGs und die Original-XAML-Wörterbücher liegen danach unter `work/sh1-hud-editierbar` (gitignoriert). Neue Exporte bewahren die originalen XAML-Zeilenumbrüche jetzt **bytegenau**. Bereits bestehende Projekte mit früher verdoppelten Windows-Zeilenumbrüchen bleiben kompatibel.

Anschließend die Sprite Suite über `Suite starten.cmd` öffnen und den Reiter **Oberfläche** auswählen (in älteren lokalen Versionen auch **UI-Fläche** genannt). Der zusätzliche Bereich **Stronghold 1 DE – HUD-Editor** bietet:

1. **Original-HUD exportieren**: Spiel-Assetdatei auswählen und Arbeitskopien generieren.
2. **SH1-HUD laden**: 1.391 Grafiken nach Ressourcenschlüssel suchen, auswählen und ansehen.
3. **Gewähltes Bild bearbeiten**: PNG-Pixeleditor mit Pinsel, Radierer, Pipette, Zoom, Rückgängig/Wiederholen, PNG-Import gleicher Größe und Speichern.
4. **SH1-HUD prüfen**: Quellrechtecke, originale Pixelchecksummen, Bildgrößen und Dateivollständigkeit kontrollieren.
5. **SH1-HUD-Atlanten bauen**: Geprüfte PNG-Grafiken in die drei Unity-kompatibel dimensionierten Blätter zusammensetzen.
6. **Geprüfte Unity-Kopie erzeugen**: Die Original-Unity-Datei per SHA-256 mit dem HUD-Projekt abgleichen, nur tatsächlich geänderte RGBA-/BC7-Bildbereiche in einer separaten Datei ersetzen und anschließend vollständig prüfen. **Kein Einbau ins installierte Spiel.**

Alternativ über die Konsole:

```powershell
.venv\Scripts\python.exe tools\ui_sh1_hud.py check --from work/sh1-hud-editierbar
.venv\Scripts\python.exe tools\ui_sh1_hud.py build --from work/sh1-hud-editierbar --out dist/sh1-hud-editierte-atlanten
```

Erzeugte Atlanten und das Änderungsmanifest liegen unter `dist/sh1-hud-editierte-atlanten/` (gitignoriert).

**Schutz gegen Datenverlust:** Die Ausgabeordner dürfen nicht identisch mit dem HUD-Arbeitsordner sein und diesen auch nicht enthalten oder darin liegen. Gleiches gilt für die originale Unity-Quelldatei. Auch mit `--replace` verweigert die Sprite Suite solche sich überschneidenden Quell- und Zielpfade. Ein unterbrochener Verzeichniswechsel stellt den bisherigen Ausgabeordner wieder her.

## Wichtig: isolierter Unity-Kandidat, kein automatischer Spielpatch

Die Bilder können in der Sprite Suite geändert und als zusammenhängende Atlanten **exportiert** werden. Mit dem optionalen Befehl **Geprüfte Unity-Kopie erzeugen** ist außerdem ein **Offline-Einbau** in eine separate Kopie der zum Arbeitsprojekt passenden Unity-Datei möglich: Er erhält unveränderte Originalbytes und bearbeitet nur geänderte Pixelbereiche beziehungsweise BC7-Blöcke. Die installierten Spielarchive werden **nicht** überschrieben.

Die neu zusammengesetzte Unity-Kopie wurde zusätzlich gegen die **wirklichen Noesis-XAML- und Pixel-Originale aus der ausgewählten Unity-Datei** geprüft. Bei großen sichtbaren BC7-Farbabweichungen stoppt der Vorgang standardmäßig. Der Kandidat wurde auf Dateiformat, Bytebereiche und Grafiken nachgeprüft, **aber noch nicht im laufenden Spiel getestet**. Deshalb wird weder eine automatische Installation noch eine Ingame-Freigabe behauptet. [Technischer Ablauf und Grenzen](STRONGHOLD1_UNITY_HUD_KANDIDAT.md).

Crusader-spezifische Menüschaltflächen für den Import ins Crusader-Produktionsprofil sind bei aktivem SH1-Projekt blockiert. SH1- und Crusader-XAML-Koordinaten dürfen nicht vermischt werden.

## Was ist öffentlich, was bleibt lokal?

**Im GitLab-Repository:** Quellcode `tools/ui_sh1_hud.py`, `tools/ui_sh1_unity_patch.py`, `tools/suite_sh1_hud_editor.py`, `tools/suite_ui_atlas_preview.py`, `tools/suite_usability.py`, die UI-Integration in `tools/suite.pyw`, synthetische Tests und beide Anleitungen.

**Nicht im GitLab-Repository:** Firefly-/Stronghold-Texturen, einzelne Original-PNGs, ganze Spiel-Assets, Sprachdateien, Videodateien, aus Spielen rekonstruierte XAML-Dictionaries sowie die zuvor lokal erzeugten Übergabe-ZIPs. Diese bleiben beim jeweiligen berechtigten Nutzer.

## Nachweis und Grenzen

Auf der autorisierten lokalen Installation wurden alle 1.391 SH1-Ausschnitte extrahiert, geladen und geprüft. Ein Test mit **einem** veränderten PNG erzeugte wieder drei Atlanten, wobei die anderen Pixel erhalten blieben. Falsche PNG-Abmessungen wurden zurückgewiesen. Das bestätigt den Export-/Editor-/Rückbauweg, nicht die automatische Verwendung im laufenden Spiel.

Die Veröffentlichung erhebt keinen Anspruch auf offizielle Zusammenarbeit mit Firefly Studios und vergibt **keine** Lizenz an proprietären Spielressourcen.

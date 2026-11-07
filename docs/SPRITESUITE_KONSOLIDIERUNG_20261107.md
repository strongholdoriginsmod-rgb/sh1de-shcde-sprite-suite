# SpriteSuite-Konsolidierung vom 7. November 2026

Der Arbeitszweig integration/spritesuite-final-consolidation führt die beiden Renderer-Linien von f78b39f und d09397d zusammen. Die [Inventur](SPRITESUITE_INVENTUR_20261107.md) dokumentiert Herkunft, lokale Änderungen und Archivierung. Der [Runtime-Bericht](SPRITESUITE_HP_FEUER_RUNTIME_20261107.md) enthält Befehle, konkrete Messwerte und offene Spielprüfungen.

| Arbeitsablauf | Gemeinsame Daten und Einstieg | Nachweis |
|---|---|---|
| Gebäude und Schadensbibliothek | Sprite-Editor, Originalgruppe, HP-/Feuer-Szenen, Pixel- und Masken-PNGs, damage-manifest.json | Edge-Dateidialoge, Paketexport einschließlich Entwürfen, unabhängige Pixel- und Manifestprüfungen |
| KI-Schadensstufen und neue Versionen | Derselbe Sprite-Editor verwendet den lokalen Codex-Client über Loopback. Der Client übernimmt Konto und Bildgenerierung. Der Editor baut Prompt, Referenz und neue Szenen. | Echter Codex-Edit und echter Edge-Auftrag über das Konto mit bestätigter Referenz und PNG. Im echten Edge-Auftrag wurde der 1536 × 1024 große Codex-Output zunächst als Kandidat gespeichert. Bei einer Wiederholung mit demselben PNG ergab die ausdrückliche Rasteranpassung 25 bearbeitbare Tiles. Die 1.192 ausgeblendeten Randpixel blieben im Kandidaten-PNG erhalten. Edge-Integration mit kontrollierten Bildantworten für drei HP-/Feuer-Stufen und eine neue Version. |
| Originale aus Spielnachweisen | Tilemap-/Layer-Evidence, SHA-geprüfter Unity-Export, bearbeitbares .shsprite und ORA, unabhängige Stufenanfragen | Original der Kornkammer aus der vorhandenen QA-Kopie extrahiert, 16/16 PNGs SHA-identisch und RGBA-Roundtrip bestätigt |
| HP-/Feuer-Runtime | Freie Schadensbibliothek und Sprite-Bindings zum LiveMod-Paket. Klassifizierung und Wiederherstellung in C#. | DLLs gegen reale Spielbibliotheken kompiliert. Rollback, Dateiintegrität und Logreihenfolge getestet. Historisches Spielprotokoll belegt visuelle Vorschauzyklen. |
| Freie Modpakete | Desktop-Projekt mit HUD-/Noesis-, Bild-, Medien- und beliebigen Moddateien. Gemeinsamer Paketexport und bearbeitbares Projektarchiv. | Gemischter ZIP-Roundtrip, SHA, Wiederherstellung und Tk-Import. Archivschema v2 liest vorhandene v1-Archive. |
| HUD und Einheiten | Bestehende Noesis-/XAML-Werkzeuge, Sprite-/Atlas-/Animationspfade und Projekttransfer | Gezielte Regressionen und Browser-Roundtrips. Zielspielprüfungen für sämtliche Profile bleiben offen. |

## Verifikation und Freigabestand

- 145 Node-Tests über Editor, Bild-/Projektformate, Tile-Überlappung, Schäden und native Quellen.
- 49 Edge-Browserprüfungen und 16 direkte Datei-URL-Prüfungen. Der zusätzliche Loopback-Test prüft den englischen Codex-Einstieg, Referenzfolge, Tile-Import und die Prüfung fremder Origins.
- 217 fokussierte Pytest-Tests im gemeinsamen Stand, einschließlich Runtime, Noesis/XAML, Projekttransfer, Datenvalidierung und Paketierung. Die enthaltenen zehn Codex-Adaptertests laufen auch separat über unittest. 59 C#-Assertions und drei kompilierte DLL-Varianten einschließlich Prüfmodulen.
- 77 angrenzende Python-Regressionen zum Projekt, zu HUD und Paketen sowie zwei gezielte Tests der neuen freien Projektintegration.
- Deterministische deutsche und englische HTML-Ausgabe. Die Prüfroutine gleicht die Edge-Berichte und 163 Datei-Prüfsummen mit dem Editorpaket ab.
- Die vollständige Sandbox-Suite hatte Fehler im Fixture-Aufbau und blieb im GUI-Layout-Bereich hängen. Sie ist kein Freigabenachweis.
- Das getrennte Spielerprofil für einen reproduzierbaren Spieltest ist offen. 128 historische Zyklen sind Vorschau-Ereignisse bei 100/100 HP und null Brandticks. Aktive HP-/Feuer-/Reparaturereignisse, Kartenwechsel und visuelle Abnahme aller Slot-/Maskenvarianten bleiben zu prüfen.

Für den Portable-Kandidaten werden der konkrete Quellcommit, die ZIP-Prüfsumme und der Entpacktest separat protokolliert. Die Entwicklungszweige bleiben bis zur vollständigen Integrationsprüfung verfügbar. Die Inventur dokumentiert neun archivierte Arbeitsbestände und ihre Prüfsummen.

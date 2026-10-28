# HUD- & Menüwerkstatt – ein durchgängiger Bearbeitungsweg

**Stand: 28. Oktober 2026 · Sprite Suite 2.0 · Windows**

Die Universal-Suite hat einen eigenen Bereich **HUD & Menüs**.
Er verknüpft die vorhandenen Spezialwerkzeuge für UI-/Menübilder
mit einer **versionsneutralen** lokalen Arbeitswerkstatt. Die
installierten Stronghold-Spiele und der vorhandene Script Extender
werden weder beim Editieren noch beim Paketbau verändert.

## Werkzeuge

| Grafik | HUD & Menüs | Spezialwerkzeug |
|---|---|---|
| Menühintergrund, Schaltfläche, Dialog-Textur | Bild importieren, Alpha bearbeiten, vorher/nachher, Ressourcenschlüssel | ORIGINS Grafiken, Noesis-UI-Atlanten |
| HUD-Elemente | Pinsel, Radierer, Füllen, Pipette, Linie, Rechteck, Zoom, Raster, Undo/Redo | SH1 HUD-Studio mit 1.391 Originalausschnitten |
| Sprite-Atlas / Varianten | Eigenen Resource-Key duplizieren, Pixel- und Alpha-Bearbeitung | AtlasBuilder für PNG/BC7-DDS, HTML-Sprite-Editor, ORA-Layer |
| Menü- und Noesis-XAML | XAML-Patch importieren und mit validierendem Texteditor anpassen | Noesis-XAML-Atlasbau, eigene ResourceDictionary-Pins |
| Origins Blau/Silber und historische Grafik | Geprüfte LFS-Quelle als separate Bearbeitungskopie übernehmen | ORIGINS-Katalog mit 13.562 Originalpfaden und SHA-Prüfung |

Eine bekannte, unbekannte, ältere oder neuere **Spiel- oder
Script-Extender-Versionsnummer** ist keine pauschale Sperre.
Eine native Funktion ist nur dann kompatibel, wenn ihre tatsächlich
installierte API/ABI zum Zielspiel passt.

## Direkter visueller Layout-Designer

Im Reiter **HUD & Menüs** bietet **Layout-Designer · direkt ziehen &
skalieren** eine interaktive Gesamtvorschau mit Ebenen, Verschieben,
Skalieren, Drehen, Mehrfachauswahl, Copy/Paste, Zoom, Snap/Raster,
Anker/Pivot, numerischen Positionen, Undo/Redo und dauerhaftem
JSON-Szenenstand. Der Export bäckt die Koordinaten exakt in eine
zusammengesetzte PNG und schreibt ein separates Positions-/SHA-Manifest.
Das Modpaket erhält standardmäßig **nur die exportierte Grafik**, nicht
ungefragt sämtliche Rohbilder. Der XAML-/Noesis-Einbau ist weiterhin
an das tatsächliche Zielspiel anzupassen.

[Ausführliche Anleitung: Layout-Designer und Positionsexport](HUD_MENU_LAYOUT_DESIGNER_2026-10-28.md).

## Schritt für Schritt

1. **Suite starten.cmd → HUD & Menüs**. Auch über Strg+K erreichbar.
2. Eigenes PNG, JPEG oder WebP in **Menüs / UI-Bilder**, **HUD /
   UI-Sprites**, **Spiel-Sprites** oder **Zusätzliche Atlanten**
   importieren. Die Quelldatei bleibt unverändert; die neue
   Arbeitskopie wird RGBA-PNG. Alternativ ein transparentes PNG
   mit gewählter Pixelgröße neu erzeugen.
3. Links nach Resource-Key suchen und filtern. **Ausgewählte Grafik
   bearbeiten** öffnet Pinsel, Radierer, Füllen, Pipette, Linie,
   Rechteck, Pixelraster, Zoom, Alpha, Ebenenimport, Größenänderung
   und Rückgängig/Wiederholen. Sehr große Bilder extern bearbeiten.
4. **Vorher/Nachher** zeigt den importierten Originalzustand und
   die Arbeitskopie. Ein Restore sichert das bearbeitete Bild
   unter work/.hud-menu-metadata/.../revisions und setzt
   nur die lokale Arbeitskopie zurück. Die externe Quelle wird
   niemals verändert.
5. **Bild mit neuem Resource-Key duplizieren** erstellt neue
   Ressourcenvarianten in den vier Kategorien, ohne die ursprüngliche
   Zuordnung oder den vorherigen Bearbeitungsstand zu überschreiben.
6. Eigenen Noesis-XAML-Menüpatch importieren; der integrierte
   Texteditor validiert Syntax und unterstützte XAML-Operationen.
   Resourcenschlüssel oder historische Spiel-IDs werden nicht
   erfunden oder automatisch in die Spielinstallation geschrieben.
7. **Assets & XAML prüfen** prüft dieselben Sicherheits-,
   Dateiformat- und Ressourcenkontrakte wie der Paketbuilder.
   **DLL-freies HUD-/Menüpaket bauen** erstellt unter
   work/se-asset-mods ein Manifest-0-Paket inklusive ZIP,
   ohne Spielinstallation, SE-Versionspin oder eigene Runtime-DLL.

## Resource-Key-Ordner

- Override/Assets/GUI/Images/ – Menügrafiken
- Override/Assets/GUI/Sprites/ – HUD und UI-Sprites
- Override/Sprites/ – Spiel-Sprites
- Override/Atlas/ – zusätzliche Atlasressourcen
- Patches/Assets/GUI/ – statische, validierte XAML-Patches

Bei der Auswahl aus **ORIGINS Grafiken** wird die vorhandene
Git-/LFS-Quellidentität geprüft, bevor eine Bearbeitungskopie
in den Werkstattordner gelangt. Das originale GitLab-/GitHub-
Grafikdatenrepository bleibt getrennt. Baseline und Revisionen
liegen außerhalb der exportierbaren Override-/Patches-Ordner
unter work/.hud-menu-metadata/.

## Grenzen, die keine Versionssperren sind

Die interne Pixeloberfläche bearbeitet Bilder bis 4 Mio Pixel;
größere Grafiken bleiben mit externen Bildeditoren zugänglich.
Neue Bilder sind maximal 4096 x 4096 Pixel groß. Der Paketbau
begrenzt Eingaben auf maximal 10.000 Dateien und 2 GiB.
Sichere Pfade, gültige XAML-Strukturen und korrekte PNG/DDS-
Dateiformate werden weiterhin verlangt.

Ein neu erzeugtes Bild erzeugt **nicht automatisch** eine
neue Schaltfläche im Spiel. Noesis-XAML-/Atlas-Referenzen
müssen anhand der gewählten Spielinstallation kontrolliert
zugeordnet werden. Native Shader-/Hook-Kompatibilität und
echtes HUD-/Menü-Rendering im Spiel sind von den
Quelltests nicht vollständig bewiesen.

## Tests

- tests/sandbox/test_hud_menu_workshop.py
- tests/sandbox/test_hud_menu_workshop_gui.py
- tests/sandbox/test_suite_command_search.py
- tests/sandbox/test_sh1_hud_studio.py
- tests/sandbox/test_origins_grafikdaten.py
- tests/sandbox/test_ui_extra_atlas.py

Die Tests arbeiten mit synthetischen Dateien, prüfen Imports,
Alpha, neue und duplizierte Bilder, Resource-Keys, Original-
Snapshots und Restore, Schreibkonflikte, XAML, Manifest-0-Pakete,
Pfadschutz und echte Tk-Bearbeitung. Sie ersetzen keine
vollständige Game-/Unity-/Noesis-Ingame-Abnahme.

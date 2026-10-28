# HUD- und Menü-Layout-Designer: direkte Bearbeitung in der Vorschau

**Stand: 28. Oktober 2026.** Diese Erweiterung ergänzt die bereits
integrierte HUD-/Menüwerkstatt der Sprite Suite. Ausgangsmaterial,
Spiele und Script Extender bleiben unberührt. Die Oberfläche ist
versionsneutral; die echte Noesis- und native Ingame-Kompatibilität
muss am Zielspiel geprüft werden.

## Öffnen und Bearbeiten

1. **Suite starten.cmd → HUD & Menüs** öffnen. Ein eigenes PNG, JPEG
   oder WebP importieren oder ein transparentes Bild anlegen.
2. **Layout-Designer · direkt ziehen & skalieren** wählen oder
   **Layout · Live-Vorschau → Interaktive Vorschau öffnen**.
3. Oben Layoutname, Zoom und optional Raster/Snapping einstellen.
   Bei Bedarf **Neu** auswählen und die Canvasgröße eingeben.
4. Rechts eine vorhandene Arbeits-PNG auswählen und **Bild einfügen**.
   Alternativ über **PNG importieren** ein eigenes Bild einlesen.
   Die ursprüngliche Quelldatei bleibt unverändert.
5. **Klick** wählt die Ebene, **Ziehen** verschiebt sie direkt in der
   Vorschau. **Ecken und Seitenkanten** skalieren; der **grüne Griff**
   dreht die Ebene um ihren Pivot. Mit **Shift** proportional skalieren
   oder mehrere Ebenen auswählen. Bei Snapping rasten Positionen
   und Größen am wählbaren Pixelraster ein.
6. Über die Ebenenliste Ebenen auswählen, sichtbar/unsichtbar
   schalten, sperren, nach vorne/hinten verschieben und gemeinsam
   ausrichten. Kopieren, Einfügen, Duplizieren, Löschen und
   Undo/Redo sind vorhanden. Pfeiltasten verschieben um 1 Pixel,
   Shift+Pfeil um 10 Pixel.
7. Im Eigenschaftenblock **X, Y, Breite, Höhe, Rotation,
   Deckkraft (0–255), Anker (neun Positionen), Pivot X/Y (0–1)**
   exakt eingeben. **Werte anwenden** schreibt den Zustand in
   den Undo/Redo-Verlauf. Für Pixelmalerei **Original-Pixeleditor**
   öffnen; dessen Änderungen sind in der Layout-Vorschau sichtbar.
8. **Speichern** (Strg+S) legt die gesamte Szene als JSON ab.
   **Laden** rekonstruiert die Positionen und die Ebenenfolge.
   Frühere gespeicherte Revisionen bleiben erhalten. Extern
   geänderte Layoutdateien werden nicht blind überschrieben.

## Weiterverarbeitung der Positionen

**Layout → PNG + Positionsdaten** erzeugt zwei zusammengehörige
Dateien: eine transparente, zusammengesetzte PNG-Ressource unter
work/Werkstatt/Override/Assets/GUI/Images/NAME.png und ein
Herkunfts-/Positionsmanifest unter work/.hud-menu-metadata/
(PROJEKT)/exports/NAME.png.json.

Verschiebungen, Drehungen, Größen und Deckkraft sind in die
PNG-Pixel eingerechnet. Die Vorschau verwendet exakt die gleiche
komponierte Szene und skaliert sie lediglich zur Anzeige.
Das Manifest enthält alle Ebenen, Resource-Keys, X/Y, Breite/Höhe,
Rotation, Pivot, Anker, Z-Reihenfolge, Sichtbarkeit, Deckkraft,
Quell-SHA-256 und SHA-256 der endgültigen PNG.

**Asset-Mod-Paket bauen** prüft, ob gespeicherte Szene, Export und
alle Quellbilder zusammenpassen. Nach jeder Positions- oder
Pixeländerung ist der **Export erneut auszuführen**.
Standardmäßig wird nur die fertig zusammengesetzte PNG in einen
separaten Paket-Quellordner übernommen, nicht jedes Rohbild.
Optional können eigene geprüfte XAML-Patches hinzugefügt werden.
Der vorhandene Paketbuilder erstellt daraus ein DLL-freies
Manifest-0-Modverzeichnis samt ZIP unter work/se-asset-mods/,
ohne Script-Extender-Versionspin und ohne Spielinstallation.

## Speichervertrag

Das JSON-Schema heißt sprite-suite.hud-menu-layout.v1.
Jede Ebene speichert: id, asset, name, x, y, width, height,
rotation, anchor, pivot_x, pivot_y, opacity, visible, locked.
Die Position x/y bezeichnet den gewählten Anker auf dem Canvas,
nicht zwingend die linke obere Bildecke. Der Pivot steuert die
Rotation um den normierten Bildpunkt. Die Z-Reihenfolge entspricht
der Reihenfolge der Ebenen im JSON.

Szenen liegen unter
work/.hud-menu-metadata/PROJEKTHASH/layouts/NAME.scene.json.
Vorherige Dateistände bleiben in layouts/revisions/.
Zur Weitergabe eines vollständigen bearbeitbaren Projekts
gehören sowohl die Werkstattbilder als auch diese Metadaten.
Eine exportierte PNG enthält die sichtbaren Transformationen,
ist jedoch kein verlustfrei editierbares Ebenenprojekt.

## Grenzen und Sicherheit

- Eine zusammengesetzte Grafik ist ein echtes PNG. Für neue
  Spielschaltflächen müssen Noesis-XAML-/ResourceDictionary- oder
  Atlasreferenzen im passenden Spielkontext gesondert zugeordnet
  werden. Der Editor erfindet diese Bindungen nicht automatisch.
- Keine Spielarchive, Extender-DLLs oder fremden Modordner werden
  verändert. Quelleingaben bleiben Arbeitskopien unter work/.
  Symlinks, Pfadausbrüche und manipulierte Export-Hashes sind
  nicht zulässig.
- Canvas maximal 4096×4096 bzw. 16,7 Mio Pixel und 256 Ebenen,
  außerdem begrenzte Bildformate und geprüftes XAML. Das sind
  Integritäts- und Leistungsgrenzen, keine Spielversionssperren.
- Native Shader-/Noesis-Menüparität, Game-Hooks, Save/Load und
  tatsächlich neue Button-Aktionen sind durch eine Desktopvorschau
  **nicht allgemein im laufenden Spiel nachgewiesen**.

## Tests

- tests/sandbox/test_hud_menu_layout.py: Schema, Positionen,
  Revisionen, Renderer, Exporte und SHA-/Pfadkonflikte.
- tests/sandbox/test_hud_menu_layout_gui.py: echte Tk-Gesten
  (Verschieben, Skalieren, Drehen, Undo/Redo, Speichern/Laden,
  Kopieren/Einfügen und Asset-Mod-Export).
- Weiterhin erforderlich: bestehende Suite-/HUD-/Noesis-Tests
  und separate End-to-End-Abnahme im tatsächlich laufenden Spiel.

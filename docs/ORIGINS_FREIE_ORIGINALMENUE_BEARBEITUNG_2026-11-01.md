# SpriteSuite – Original-Noesis-Menüfenster frei gestalten

**Arbeitsstand:** 1. November 2026
**Entwicklungsprojekt:** E:\SpriteSuite_Origins_Manuell_20261101
**Zweig:** feature/origins-manual-menu-runtime-20261101

## Freiheit statt Manipulationsschutz

Eigene, gültige XAML-Dokumente, Styles und Grafiken werden nicht
auf historische Prüfsummen oder eine vorgeschriebene Attributliste begrenzt.
Alte Herkunftshashes sind Informationen, keine Sperren. Absichtlich
bearbeitete Origins-Grafiken können auch mit geändertem Branding-Hash
importiert werden. Die Abweichung wird lediglich im Importbericht notiert.

Nur technische Voraussetzungen bleiben: gültiges XML, sichere Dateipfade,
nicht verknüpfte Mod-Ausgaben und die Trennung der Arbeitskopie vom Spiel.
Neue CommandParameter, Bindings, Hover-/Mouse-Handler, Attribute und
Styles dürfen frei bearbeitet werden, sind aber nicht ohne passenden
Spielhandler automatisch ausführbar.

## Workflow

**HUD & Menüs → Original-Menüseiten gestalten** öffnet den
originalbasierten visuellen Editor.

1. Original-XAML öffnen, beispielsweise FrontendMenus.xaml aus einem
   installierten Script Extender unter
   BepInEx/plugins/000shcdese/Override/Assets/GUI/XAML/.
   Die Quelldatei wird nur gelesen. Über **Vorhandenen Mod-Patch einblenden**
   können anschließend auch ältere Origins-/Noesis-Patches auf die
   Arbeitskopie angewendet werden. Fehlende XPath-Ziele werden angezeigt;
   vorhandene Änderungen bleiben frei bearbeitbar.
2. Vollständige XML-Hierarchie mit benannten und unbenannten Knoten
   ansehen; einzelne Fenster/Seiten sowie verborgene Controls wählen.
3. Elemente ziehen, Größe und Drehwinkel verändern, duplizieren,
   hinzufügen, löschen, umsortieren. Rückgängig/Wiederholen verwenden.
4. Attribute, Texte, Farben, Styles, Bilder, Resource-Keys,
   CommandParameter und eigene Events direkt bearbeiten. Der komplette
   XAML-Quelltext ist im Expertenmodus editierbar.
5. Für die Grafikvorschau bei Bedarf einen zusätzlichen Originalbildordner
   auswählen. Dieser wird nur gelesen; Bilder aus dem eigenen Override-
   Verzeichnis werden ebenfalls angezeigt, soweit die Dateien vorhanden sind.
   Ein **Original-Screenshot als Bildreferenz** kann zusätzlich hinter die
   bearbeitbaren Ebenen gelegt werden. Diese Referenz wird in den privaten
   Revisionen gesichert, aber niemals als Spiel-Overlay mit ausgeliefert.
6. **Patch + Revision speichern.** Der Editor legt die vollständig
   bearbeitete Datei und den Noesis-Patch reproduzierbar im Projekt ab.
7. **Asset-Mod ZIP erzeugen.** Der statische Builder paketiert XAML,
   weitere Overrides, Menübilder, WebM-Dateien und Locales, soweit sie
   als gültige Projektdateien vorliegen. Keine automatische Installation.

## Wo Dateien liegen

- Original: vom Nutzer ausgewählter Quellpfad, bleibt unverändert
- Aktiver Patch: work/<Projekt>/Patches/Assets/GUI/XAML/<Menü>.xaml
- Editierbare Revisionen: work/.origins-visual-revisions/<Projekt-ID>/
  <Menü>/rev-0001/ mit source.xaml, edited.xaml, patch.xaml,
  revision.json und gegebenenfalls previous-package-patch.xaml
- Paket: work/se-asset-mods/<Mod-ID>.zip, Script-Extender-konforme Struktur
  BepInEx/plugins/<Mod-ID>/Patches/Assets/GUI/XAML/...
- Eigene Bilder: work/<Projekt>/Override/Assets/GUI/Images/

Ein neuer Stand kann aus edited.xaml erneut geöffnet werden, auch wenn
diese Datei außerhalb der Suite bewusst weiterbearbeitet wurde. Der
vorherige eigene Patch wird bei Aktualisierung in der neuen Revision
gesichert. Keine erzwungene Rückkehr zum historischen Ausgangs-Hash.

## Nachgewiesene Ergebnisse

- Echte installierte FrontendMenus.xaml: 383.851 Bytes und 1.077 originale
  XML-Elemente eingelesen; rund 500 platzierbare visuelle Nodes.
- Echtes Windows-Tk-Fenster mit 1.077 Hierarchieeinträgen gestartet;
  beliebige CommandParameter und Undo/Redo getestet.
- Position geändert, Element hinzugefügt, Rotation gesetzt; daraus ein
  Patch von 196.577 Bytes erzeugt.
- Statisches Asset-Mod-ZIP origins-original-qa.zip erfolgreich erstellt,
  mit neuem Menüknopf und frei definiertem CommandParameter.
- Originale Spiel-XAML vor und nach der Verarbeitung byteidentisch.
- Bearbeitete Version erneut geöffnet und als weitere Revision und
  Paketpatch gespeichert; externe XML- und Asset-Tests bestanden.
- Originalbilder können für die Vorschau aus einem zusätzlich gewählten
  lokalen Bildordner angezeigt werden.
- Privater QA-Nachweis: work/origins-original-layout-qa-20261101/
  qa-real-menu.json; keine Steam-Dateien überschrieben.

## Noch nicht vollständig gleichwertig zu Photoshop/Illustrator

Die Arbeitsfläche ist eine **geometrische Noesis-Vorschau**, kein
pixelgenauer integrierter Noesis-Renderer. Live-Bindings, Responsive-
Layout, Textmetriken, Style-Templates, Animationen, Hover-/Pressed-
VisualStates und WebM-Video können vom echten Spiel abweichen. Manche
originalen Bilder sind nicht als eigenständige PNGs verfügbar.

Ein manuell gesetzter CommandParameter wird gespeichert und paketiert,
aber erst nach der Registrierung eines passenden Script-Extender/C#-
Handlers zur echten Spielaktion. Die historische Origins-Runtime aus
Spielversion 2.7.0 ist für Steam-Build 24816905 nicht automatisch
binärkompatibel. Native Spielintegration und vollständige Ingame-
Abnahme sind weiterhin separate Aufgaben.

**Status:** Freie Dokument-, Ebenen- und XAML-Bearbeitung mit
reproduzierbaren Mod-Patches ist implementiert und offline getestet.
Exakte Noesis-Livevorschau und sämtliche historischen Runtime-Funktionen
sind noch nicht vollständig integriert.

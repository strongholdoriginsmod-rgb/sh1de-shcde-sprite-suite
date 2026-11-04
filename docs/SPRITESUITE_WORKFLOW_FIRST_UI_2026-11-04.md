# SpriteSuite 2.0.0 – Workflow-first GUI (4. November 2026)

**Status: lokal überprüfter UX-Kandidat, keine öffentliche Stable-/Ingame-Freigabe.**

## Warum die vorherige Oberfläche nicht ausreichte

Die originale Projektseite stapelte vier Schrittkarten, mehrere volle Import- und Aktionszeilen und ein langes Exportformular oberhalb einer starren Dateiliste. Bei 1020 × 680 Pixeln verschwanden **Prüfen** und **Exportieren** unter dem Fensterrand. Der Layout-Designer reservierte mehrere Werkzeugleisten und eine höhenfüllende Ebenenliste, die die transformierbaren Felder verdeckte. Beim ersten Öffnen wurde der Zoom manchmal aus einer noch nicht dimensionierten Zeichenfläche (150-Pixel-Fallback) berechnet. Die Spielvorschau zeigte redundante Tk- und Qt-Leisten.

## Überarbeitung

- **Eine Projekt-Werkbank:** Projektaktionen im Kopf; Bild-/XAML-Import, Kategorien und Dateiliste links, große skalierende Auswahlvorschau mit direktem Pixel-/Layout-/Noesis-Einstieg rechts.
- **Immer sichtbare Ausgabeschritte:** feste untere Leiste zum Prüfen und zum Erstellen des verifizierten statischen Mod-ZIPs, Ergebnisstatus und gezielte Fehlerhinweise.
- **Technische Exportdetails erst auf Wunsch:** Mod-ID und Paketname bleiben änderbar, benötigen aber keine dauerhafte komplette Formularzeile.
- **Seitenleiste auf Aufgaben reduziert:** fünf primäre Arbeitsbereiche; Strg+K-Suche; übrige Werkzeuge, Log, Spracheinstellungen und Legacy-Reiter in einer einklappbaren Gruppe.
- **Layout-Designer:** kompakte Kopf-/Ansichtsleiste; Import, Ebenenplatzierung und Export in einer festen unteren Aktionsleiste; Position/Größe/Rotation im sichtbaren Inspector statt unter übergroßer Layer-Tabelle. Der initiale Zoom wird nach tatsächlicher Canvas-Geometrie berechnet.
- **Spielvorschau:** doppelte Tk-Werkzeugleisten werden in das Menü »Werkzeuge« ausgelagert; die eingebettete originale Qt-Engine und ihre Sicherheitsgrenzen bleiben unverändert.

## Unveränderte Verträge

Projektwechsel, unsichere Eingabepfade, ungespeicherte Editorfenster, Noesis-/Asset-Exportbelege, Projekt-ZIP-Sicherung und Wiederherstellung sowie die Steam-Diagnose bleiben an den bisherigen Daten- und Sicherheitscode gebunden. **Ein statisches Mod-ZIP wird nicht automatisch installiert.** Native Spiel-/Noesis-/C#-ABI-Anbindung und Atlas-Rollback müssen in einer eigenen autorisierten QA-Kopie unabhängig nachgewiesen werden.

## Zielgrößen und Prüfung

- **1020 × 680 px**: Import, Bild-/Layout-/Noesis-Aktionen, Prüfung und Export müssen im Fenster sichtbar und anklickbar bleiben, ohne die ganze Seite vertikal scrollen zu müssen.
- **1440 × 850 px**: Die Vorschau nutzt den Großteil des verfügbaren Arbeitsbereichs; die Dateiliste bleibt nutzbar.
- **1280 × 800 px Layout-Designer**: Der Zoom nutzt die tatsächlich gemessene Zeichnungsfläche, Ebeneneigenschaften sind sichtbar und der Export sitzt fest in der unteren Leiste.
- Die neuen Tests in `tests/sandbox/test_suite_unified_workflow_gui.py` prüfen die genannten Zustände, einschließlich echter Tk-Fenstergeometrien und Preview-Skalierung.

## Bereitstellung

Dieser Zweig wird getrennt vom bisherigen technischen Release-Kandidaten erstellt, damit sich die neue Bedienoberfläche auf dem Zielrechner beurteilen lässt. Eine erfolgreiche Python-/Tk-/Qt-/ZIP-Prüfung ist kein Ersatz für einen unabhängigen Test mit einem realen Bild- und Noesis-Projekt und einem zweiten Windows-Rechner.

## Kompakter Seitentitel

Die eingeklappte Werkzeuggruppe verwendet auch im kleinsten unterstützten Fenster die kurze Beschriftung »Werkzeuge«; längere Aktionsbeschreibungen werden in der Seitenleiste umgebrochen statt seitlich abgeschnitten.

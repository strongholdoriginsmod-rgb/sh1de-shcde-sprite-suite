# Bearbeitbare HUD-/Menüprojekte sichern und auf einem anderen PC öffnen

**Gültig ab:** SpriteSuite-Projektarchiv-Ausgabe vom 29. Oktober 2026.

## Was gespeichert wird

Die Funktion **Projekt sichern …** erstellt eine ZIP-Datei mit:

- allen zugehörigen Projektdateien unter `Override/` und `Patches/`;
- sämtlichen gespeicherten Layouts mit Ebenen, Positionen, Drehungen und Ankern;
- ursprünglichen Importzuständen und älteren Bearbeitungsrevisionen;
- Positionsmanifesten und den zuletzt exportierten zusammengesetzten PNGs;
- der zuletzt gewählten Bilddatei und dem Namen des letzten gespeicherten Layouts.

Nicht übernommen werden die installierten Spiele, Programmlaufzeiten,
globale Einstellungen, Spiel-QA-Installationsbelege und Dateien außerhalb
des ausgewählten Projekts. Das ZIP enthält **bearbeitbare Projektdateien**,
nicht automatisch eine funktionierende Spiel-Modinstallation.

## Projekt auf dem ersten PC sichern

1. SpriteSuite starten und links **HUD & Menüs** öffnen.
2. Oberhalb der Bildliste prüfen, dass bei **Aktives Projekt** der
   richtige Projektname steht.
3. Falls der Pixel-, Text- oder Layout-Designer noch geöffnet ist:
   **Projekt sichern …** erkennt ungespeicherte Änderungen und fragt,
   ob sie zuerst gespeichert werden sollen. **Ja** sichert die
   Bearbeitungen vor dem ZIP. Bei **Nein** oder fehlgeschlagenem Speichern
   wird **kein Archiv** erstellt.
4. In **HUD & Menüs** auf **Projekt sichern …** klicken.
5. Einen **neuen** ZIP-Dateinamen wählen. Bestehende ZIP-Dateien
   werden absichtlich nicht überschrieben.
6. Den angezeigten Dateipfad und SHA-256-Wert aufbewahren. ZIP auf USB-Stick
   oder in einen ausdrücklich ausgewählten Ordner kopieren.

## Projekt auf dem anderen PC öffnen

1. Die Windows-Portable-SpriteSuite in einen neuen Ordner entpacken und
   mit **Suite starten.cmd** starten. Python muss nicht installiert werden.
2. Links **HUD & Menüs** öffnen und **Projekt aus ZIP öffnen …** wählen.
   Sind im aktuellen Projekt noch Bearbeitungen ungespeichert, wird
   vor dem Projektwechsel ausdrücklich nach dem Speichern gefragt.
3. Die zuvor gesicherte ZIP-Datei auswählen.
4. Einen **neuen Projektnamen** eingeben, zum Beispiel `MeineMenues2`.
   Ein bereits vorhandener Projekt- und Metadatenordner kann nicht
   überschrieben werden.
5. Die Dateianzahl in der Bestätigung prüfen und die Wiederherstellung
   ausdrücklich erlauben.
6. **3 Layout gestalten** öffnen. Das letzte gespeicherte Layout sollte
   direkt wieder ausgewählt sein. Position und Ebenenliste prüfen.
7. Bei Bedarf **Layout → PNG + Positionsdaten** erneut exportieren,
   bevor ein neues Spiel-Modpaket gebaut wird.

## Technische Sicherheitsregeln

- Die ZIP enthält eine vollständige Dateiliste mit SHA-256-Hashes.
- Vor dem Schreiben werden Archivstruktur, Dateinamen, Anzahl und
  entpackte Größe kontrolliert. Jede übertragene Datei wird erneut
  anhand ihres SHA-256-Hashes geprüft.
- Absolute Pfade, Verzeichniswechsel per `..`, doppelte Dateinamen,
  ZIP-Symlinks und unbekannte Archivbereiche werden zurückgewiesen.
- Es werden **nur neue Ordner unter `SpriteSuite/work/`** erstellt.
  Vorhandene Projekte werden weder ersetzt noch zusammengeführt.
- QA-Spielinstallationsbelege werden aus Sicherheitsgründen nicht auf
  den anderen Computer übertragen.
- Import-Basisbilder bleiben unverändert; es werden keine externen
  Quellgrafiken oder Spieleinstallationen überschrieben.
- Beim Archivieren prüft die Suite offene Bearbeitungsfenster und bietet
  das Speichern der Änderungen an. Wird dies abgelehnt oder schlägt
  es fehl, wird kein scheinbar vollständiges ZIP erzeugt.
- Beim Wechsel des Arbeitsprojekts verwendet der Layout-Designer nie
  das noch offene Fenster des vorherigen Projekts als neue Szene.

## Vorherige SpriteSuite-Versionen

Ältere SpriteSuite-Versionen haben ihre Metadatenordner aus dem
**absoluten Installationspfad** berechnet. Die neue Version übernimmt
die vorhandene alte Ablage beim ersten Zugriff, verifiziert die
kopierten Dateien und lässt den alten Stand bestehen.

**Wichtig:** Die neue Version sollte diese Migration auf dem Computer
mit dem ursprünglichen Arbeitsordner ausführen, *bevor* nur
`work/` auf einen anderen PC kopiert wird.

Wurde `work/` bereits verschoben, ohne den ursprünglichen absoluten
Pfad oder die Ausgangsinstallation zu erhalten, kann eine alte
Metadatenkennung nicht in jedem Fall eindeutig zugeordnet werden.
Die Suite errät nicht, wem unzugeordnete alte Layoutdaten gehören.
In diesem Fall die ursprüngliche Installation als Sicherung aufbewahren,
anstatt unklare Altdateien manuell umzubenennen.

## Unterschied: Projektarchiv und Modpaket

| Archiv für die Bearbeitung | Modpaket für das Spiel |
| --- | --- |
| Gespeicherte Ebenen, Rohbilder, Revisionen und Exportbelege | Ausgewählte spielbezogene Override- und Patchdateien |
| Auf anderem Computer im Editor wieder bearbeitbar | Für das jeweilige Zielspiel bestimmt |
| Keine Spielinstallation verändert | Muss ausdrücklich in einer geeigneten Spielkopie getestet werden |
| Kann auch für reine Menü-Entwürfe verwendet werden | Statische Noesis-Overlays sind nicht automatisch anklickbar |

## Grenzen der bisherigen Prüfung

Erfolgreich getestet wurden Export, Import, Integrität, Ablehnung
unsicherer Archive, Speichern/Wiederladen nach Pfadwechsel und die
Tk-Oberfläche mit synthetischen Grafiken. Ein unabhängiger Test auf
einem zweiten physischen Windows-Rechner und ein vollständiger
Ingame-Funktionstest sind weiterhin gesonderte Abnahmekriterien.

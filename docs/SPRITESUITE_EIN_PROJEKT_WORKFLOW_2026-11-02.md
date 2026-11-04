# SpriteSuite – Ein Projekt, ein bearbeitbarer Workflow

Stand: 2. November 2026
Zweig: feature/streamlined-shared-project-workflow-20261102

## Das Problem

Bisher waren HUD-Werkstatt, Pixel-Editor, Noesis-Originalseiten-Editor,
Layout-Designer und Paketbau unterschiedliche Einstiege. Der Anwender
musste mehrfach dieselbe Quelle wählen. Noesis-Originalkopien und
Revisionen gehörten noch nicht zur portablen Projektsicherung.
Ein syntaktisch korrektes Paket ist zudem kein Beleg, dass die
Spielintegration einen Resource-Key oder C#-Command wirklich ausführt.

## Der neue Normalablauf

1. Mein Mod-Projekt öffnen oder anlegen. Alle Änderungen liegen unter
   SpriteSuite/work. Die bestehende HUD-Sitzung hält das aktuelle
   Projekt fest; Pixel & Layout arbeitet mit genau demselben Projekt.
2. Dateien hinzufügen: PNG/JPG/WebP werden als eigene bearbeitbare
   Arbeitskopie importiert. Eine originale Noesis-XAML wird mit voller
   SHA-256-Prüfung als private Quelle gesichert und nicht fälschlich
   als schon fertiger Mod-Patch eingestuft.
3. Bearbeiten: Doppelklick öffnet den existierenden Pixel-/Text-Editor.
   HUD-Layout öffnet den Ebenen-Designer. Noesis-Menüseite öffnet
   den kompletten Originalseiten-Designer. Offene Editorfenster werden
   wiederverwendet. Projektbilder werden ohne Doppelimport mit
   ausgewählten Noesis-Image-Elementen verbunden.
4. Prüfen: Die echten Paketvalidatoren prüfen jede bearbeitete Datei.
   Fehlende Noesis-Verweise und unbelegte neue Laufzeitkommandos sind
   Hinweise, keine fingierten Ergebnisse.
5. Mod-ZIP bauen: Der bestehende Script-Extender-Assetpaketbau erzeugt
   ein neues Manifest-0-ZIP und schreibt nie in eine Spielinstallation.
   Anschließend werden Dateiliste, CRC, SHA-256 jeder Ressource
   und Manifest gegen das bearbeitete Projekt verglichen. Ein
   überprüfter ZIP-Hash wird außerhalb des Spielordners gesichert.
   Nach Änderungen zeigt die Suite das vorherige ZIP als veraltet.

## Bearbeitbares Projekt-ZIP vs. fertiges Mod-ZIP

Projekt sichern (ZIP) enthält eigene Arbeitsdateien, importierte
Ursprünge, editierbare Layouts, die Noesis-Originalkopie und
sämtliche Noesis-Revisionsdateien. Nach dem Wiederherstellen unter
einem anderen Projektpfad lassen sie sich erneut öffnen und bearbeiten.
Alte maschinenspezifische Exportpfade werden absichtlich nicht
übernommen. Eine Original-XAML kann urheberrechtlich geschützte
Spielinhalte enthalten: Projektarchive sind private Sicherungen,
keine öffentlichen Mods.

Das installierbare Mod-ZIP enthält ausschließlich zugelassene Dateien
unter Override/, Patches/ und Locales/ sowie die BepInEx-Manifestdatei.
Es enthält keine Original-XAML-Snapshots, Revisionen oder Laufzeit-DLLs.
Es wird niemals automatisch in die Spielinstallation kopiert.

Für Windows verwendet die XAML-Originalablage einen kompakten SHA-Ordner,
prüft aber trotzdem den vollen SHA-256. Ältere vollständige
SHA-Verzeichnisnamen bleiben lesbar.

## Die sichtbare Hauptnavigation

Im normalen Modus: Mein Mod-Projekt, Pixel & Layout,
Spielvorschau, Prüfen & Fehler, Zielspiel & Mods.
Die zweite obere Navigationsleiste wird nicht gleichzeitig angezeigt.
Alle älteren Spezialwerkzeuge bleiben über Weitere Bereiche,
Suche (Strg+K) und Alle Reiter erreichbar. Die Spezial-Werkstatt
bietet einen Rückweg in das aktive Mod-Projekt.

## Grenzen und echte Abnahme

Ein technisch korrektes und reproduzierbares Assetpaket ist noch
kein Nachweis, dass das installierte Spiel eine neue Bildressource
sichtbar rendert. Dasselbe gilt für C#-Menükommandos, Kartenstarts
und Saisonwechsel. Echte Noesis-Live-Pixel werden nur aus einem
laufenden, verifizierten Spielprozess übernommen. Die tatsächliche
Ingame-Abnahme bleibt separat und wird nie von Datei-Existenz oder
Offline-Mock-Tests vorgetäuscht.

Alle hier beschriebenen manuellen Projektoperationen arbeiten in
der SpriteSuite-Arbeitskopie und ändern keine Spieloriginale.


## Abschließende Verbindungen des Normalmodus

- Die alte HUD-Spezialwerkstatt zeigt im normalen Modus keine zweite
  vollständige Fünf-Schritte-Anleitung und keine doppelten
  Projekt-Sicherungsaktionen mehr. Unter "Weitere Grafikwerkzeuge" lassen
  sie sich weiterhin ausdrücklich öffnen; die Projekt-Hauptansicht
  enthält die direkt sichtbare Sicherungs- und Wiederherstellungsfunktion.
- Beim Öffnen einer anderen Original-XAML fragt das Programm zuerst
  nach allen ungespeicherten Änderungen am bisherigen Dokument.
  Wenn die Benutzerin oder der Benutzer die Sicherung ablehnt,
  bleibt die bisherige Quelle und der bisherige Editor erhalten.
  Nach dem Speichern wird der alte Noesis-Editor nicht irrtümlich
  als Editor der neuen Quelle wiederverwendet.
- Beim Wechsel des gesamten Projekts werden die gespeicherten
  projektgebundenen Pixel-, Text-, Layout- und Noesis-Editorfenster
  geschlossen, damit spätere Speichervorgänge nicht versehentlich
  einen fremden Projektkontext anzeigen. Ungespeicherte Änderungen
  werden zuvor geprüft; ein abgelehntes Speichern blockiert den Wechsel.
- Die Workflows und die bearbeitbaren Projekt-ZIPs sind auf
  Windows-Datenträgerpfade geprüft. Snapshot-Pfade wurden für das
  traditionelle Windows-Limit gekürzt, ohne die vollständige
  Hashprüfung zu reduzieren.

In der umfangreichen GUI-Regression muss der historische Leitfaden
explizit geöffnet werden. Er ist weiterhin funktional, aber nicht
mehr die automatisch geöffnete Hauptseite.

## Fortschreibung: robuste Windows-Pfade (3. November 2026)

Neue Import-Baselines und private Bildrevisionen erhalten stabile, kompakte
Hash-Dateinamen (128 Bit des Pfad-SHA-256, zusätzlich durch das vollständige
SHA-256 der Bilddaten im Baseline-Datensatz geschützt). Das reduziert das
Risiko des historischen Windows-MAX_PATH-Fehlers bei tiefen Projektpfaden
und bleibt über Projekt-ZIP-Umzüge hinweg stabil. Bestehende 64-stellige
Hash-Dateinamen bleiben lesbar und für private Projekt-ZIPs zulässig.
Der Import überschreibt weiterhin keine vorhandene Baseline; private
Originale und Spielinstallationen bleiben unberührt.

Diese Verbesserung ist eine Dateisystem-/Projektarchiv-Regression, kein
realer Ingame-, Noesis- oder unabhängiger Portable-Hardwarenachweis.

## Fortschreibung: sichere Projektwechsel und Exportnachweise (4. November 2026)

Beim Wechsel eines Projekts wird kein Zielordner mehr vorsorglich
angelegt. Ein nicht existentes Ziel wird abgewiesen; das explizite
"Neues Projekt" und die geprüfte ZIP-Wiederherstellung bleiben die
einzigen Wege zum Anlegen eines neuen Projekts. Ein abgelehnter
Speicherdialog verändert den alten Kontext nicht. Der neue Sitzungsstand
wird erst erfolgreich gespeichert, bevor bereits gespeicherte
Editorfenster des bisherigen Projekts geschlossen werden. Das erneute
Aktivieren desselben Projekts hält offene Editorfenster erhalten.

Ein fehlgeschlagener neuer Mod-ZIP-Bau entfernt die alte Paketdatei
nicht, zeigt sie aber auch nicht als Ergebnis des fehlgeschlagenen
Versuchs an. "Ergebnisordner öffnen" prüft den gespeicherten Beleg,
das tatsächlich vorhandene ZIP samt SHA-256 sowie die Übereinstimmung
mit den aktuellen Projektassets erneut. Veränderte oder veraltete
Ergebnisse werden nicht als noch gültig geöffnet. Diese Prüfung
erzeugt keine echte Ingame-Freigabe und installiert keine Mods.

Die Regression deckt sowohl die Sperren als auch erfolgreiche normale
Projekt- und Exportpfade ab. Die spätere vollständige Ingame- und
Hardwareabnahme bleibt ausdrücklich offen.

## Fortschreibung: Python 3.14 / Tcl-Tk 9 (4. November 2026)

Die Windows-Oberfläche kann nicht denselben Tcl/Tk-Dateibaum für Python
3.13 und 3.14 voraussetzen: Die vorhandene Python-3.13-Laufzeit nutzt
Tcl/Tk 8.6 mit init.tcl/tk.tcl in Ordnern, während die geprüfte
Python-3.14-Laufzeit Tcl/Tk 9.0 mit nativen Python-ZipFS-Bibliotheken
(lib*tcl/tk*9.0.*.zip) verwendet.

Die Bootstrap-Prüfung validiert für Tcl/Tk 9 die nativen Library-ZIPs
auf notwendige Skripte, Dateigrößen, ZIP-Prüfsummen und unsichere
Archivpfade. Die ZIPs bleiben unverändert und werden nicht mit den
Tcl-8.6-Skriptordnern verwechselt. Für Tcl/Tk 8.6 bleibt der
inhaltsadressierte, private Cache erhalten. Die Auswahl berücksichtigt
die tatsächlich geladene Tcl-/Tk-Version des Interpreters und verändert
keine systemweiten Einstellungen.

Diese lokale Runtime-Prüfung und GUI-Regression sind kein Nachweis
eines auf zweitem Windows-Rechner bestätigten Portable-Pakets und keine
Ingame- oder Noesis-Hardwareabnahme.

## Lokale Prüfnachweise der Entwicklungsrunde vom 4. November 2026

- Windows x64 / Python 3.13: 89 Tests aus dem gemeinsamen Projektworkflow,
  den zugehörigen HUD-, Archiv- und Navigationstests bestanden.
- Windows x64 / Python 3.14: 43 Tests der vollständigen neuen
  Workflow-GUI-Testdatei, Projektpipeline, Exportbelege und Tcl/Tk-Prüfung
  im ersten kombinierten Lauf bestanden.
- Nach der abschließenden Bindung von Tcl/Tk 9 an die tatsächlich gestartete
  Python-Laufzeit: Python 3.13 mit 17 bestandenen und 2 sinnvoll
  versionsbedingt übersprungenen Tcl-/Exportbelegprüfungen; Python 3.14
  mit 19 bestandenen, 0 übersprungenen Tests.
- Echte Tk-Fenster wurden lokal unter Python 3.13 (Tcl 8.6) und
  Python 3.14 (Tcl 9.0) geöffnet und geschlossen.
- Alle Testfälle verwenden synthetische Projekte, Mod-ZIPs oder
  Laufzeitquellen. Kein echter Spiel-, Atlas-, Plugin-, Hardware-
  oder unabhängiger GitHub-CI-Nachweis wurde dadurch erzeugt.

Alle Arbeiten verbleiben uncommittet im lokalen Entwicklungszweig;
es wurde kein Mod in einer Spielinstallation installiert und keine
neue portable Ausgabe veröffentlicht.

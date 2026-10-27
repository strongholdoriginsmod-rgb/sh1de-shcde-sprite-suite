# Dauerhafter lokaler Paketbau- und Prüfverlauf

**Entwicklungsstand: 12. Oktober 2026.**

Die Sprite Suite protokolliert ab dieser Erweiterung tatsächliche, aus der
Suite gestartete BC7-Bauversuche auch über einen Neustart der Anwendung hinaus.
Ein bestehendes altes Produktionspaket erzeugt **keinen** nachträglich
erfundenen Bauversuch. Ein nur synthetisch getesteter GUI-Status wird
nicht in den Produktionsverlauf geschrieben.

## Nutzung im Hauptfenster

Unter **Paket bauen → Bauverlauf anzeigen** wird die lokal gespeicherte
Historie erneut gelesen und vollständig auf ihre SHA-256-Kette geprüft.
Nach dem Start der Suite informiert eine zusätzliche Statuszeile über die
Anzahl der Bauversuche und das letzte dokumentierte Ergebnis.

Die Tabelle zeigt Startzeit (UTC), die damals tatsächlich verwendete
Profil-ID und den gespeicherten Status. Die vollständigen
SHA-256-Bindungen der beim Bauversuch geprüften Eingangsdateien
(Profil, Spielpfadkonfiguration, Mapping und gegebenenfalls Unity-
und Toolchainkonfiguration) werden ebenfalls aufgezeichnet,
sofern der Start über den neuen Bereitschaftscheck erfolgte.
Alte Einträge ohne solche Bindungen bleiben lesbar und werden
im Detaildialog ausdrücklich als **nicht mit Quell-Hashes belegt**
gekennzeichnet. Ein ausgewählter Eintrag
zeigt die detailspezifischen Nachweise: Ersetzen-Wahl, CLI-Exitcode,
Offline-Prüfergebnis, Anzahl/Umfang der bestätigten Dateien,
Manifestprüfsumme, Fehler und Warnungen sowie den ausdrücklichen
Hinweis, dass keine Ingame- oder Releasefreigabe vorliegt.

Der Verlauf ist ein **historischer** Nachweis. Ein damals
gespeichertes offline_ok besagt niemals, dass die
Produktionsdateien *heute* noch dieselben SHA-256-Werte haben.
Der Dialog verweist deshalb für den aktuellen Paketstand auf
**Diagnose & Reparatur → Gesamten Build prüfen (SHA-256)**.

**Bauergebnis anzeigen** bleibt das Ergebnis eines tatsächlich
in der aktuellen Sitzung abgeschlossenen Bauversuchs. Der
**Bauverlauf** ist dagegen die von früheren Sitzungen
unabhängig wieder einlesbare Historie. Beide dürfen nicht
miteinander verwechselt werden.

## Gespeicherte Zustände

- **unbestaetigt:** Der Bauversuch wurde begonnen und vor dem
  Aufruf der Build-CLI persistiert, aber kein gültiger
  Terminaleintrag wurde gespeichert. Nach Absturz/unerwartetem
  Beenden kann daraus weder ein Erfolg noch ein gescheitertes
  Paket zweifelsfrei abgeleitet werden.
- **start_fehlgeschlagen:** Der Werkzeugstart wurde versucht
  und schlug vor der Durchführung fehl.
- **abschlusspruefung_fehlgeschlagen:** Der Bauversuch endete,
  aber die unabhängige Bewertung des Ergebnisses konnte nicht
  vollständig durchgeführt werden.
- **tool_failed / offline_failed / audit_failed:** Eindeutig
  negativ oder nicht nachgewiesen, selbst wenn auf der
  Festplatte noch ein früheres gutes Paket existiert.
- **same_manifest:** Offlineintegrität ist okay, doch das
  Manifest entspricht dem Vorzustand; daraus darf nicht
  auf neu entstandene Bytes geschlossen werden.
- **offline_warnings / offline_ok:** In der damaligen Sitzung
  klassifiziertes, lokal gespeichertes Offline-Ergebnis.
  Das ist **keine** Behauptung, dass die Dateien seitdem
  unverändert geblieben sind. Vor der Nutzung muss der
  aktuelle Release-Preflight erneut ausgeführt werden.

Der Builder kann nur starten, wenn sein vorangestellter
Verlaufseintrag sicher auf dem Datenträger abgelegt wurde.
Kann die Historie nicht geschrieben oder ein vorhandener
Eintrag nicht verifiziert werden, wird der neue Start
verweigert; bereits vorhandene Dateien werden nicht
überschrieben oder automatisch repariert.

## Speichervertrag und Sicherheitsgrenzen

Lokaler Speicherort (von Git ignoriert):

    work/reports/suite-build-history/

Es gibt maximal 500 verkettete Ereigniseinträge (Start und
Abschluss zählen einzeln). Ein Ereignis hat einen eindeutigen
vollständigen SHA-256 im Dateinamen und den vollständigen Hash
des Vorgängers im unveränderlich serialisierten JSON.
Sequenzlücken, unerkannte Dateien, doppelte Abschlüsse,
fremde Profilausgaben, geänderte Bytes und unerlaubte
Symlinks/Junctions führen zum Abbruch der Überprüfung.
Außerdem werden unmögliche UTC-Zeitstempel, fremde/quellfremde
Hashbindungen und intern widersprüchliche Ergebnisangaben
blockiert: Eine Offline-Erfolgsmeldung benötigt Manifest-SHA,
positive verifizierte Bytemenge, keinen Integritätsfehler und
eine konsistente Unterscheidung zum Vorher-Manifest.
Ein identischer alter Manifesthash kann nicht gleichzeitig
als neue, abweichende Ausgabe bestätigt werden.

Jeder neue Eintrag wird über eine exklusive, atomisch
angelegte Datei veröffentlicht; der Writer benutzt eine
lokale Sperre gegen parallele Änderungen. Bleibt bei einem
Absturz eine Sperre/temporäre Datei übrig, wird nichts
still gelöscht: Ein Nutzer muss den Zustand separat
prüfen. Die 500-Ereignis-Grenze erfordert später eine
bewusste externe Archivierung statt automatischer
Löschung älterer Nachweise.

**Ehrliche Manipulationsgrenze:** Diese rein lokal gespeicherte
SHA-256-Kette erkennt Einzeländerungen und Lücken. Sie ist
keine digitale Signatur und kein vertrauenswürdiger Zeitstempel.
Wer die gesamte lokale Historie einschließlich einer
vollständigen Endkette neu schreiben oder deren letztes
Endstück entfernen kann, lässt sich damit allein nicht
kryptografisch nachweisen. Die gespeicherten Events werden
deshalb **niemals** als Installations-, Profiländerungs-
oder Releaseberechtigung behandelt.

## Kommandozeile

Aus dem Projektordner, vollständig nur lesend:

~~~powershell
.\.venv\Scripts\python.exe tools\qa_suite_build_history.py
.\.venv\Scripts\python.exe tools\qa_suite_build_history.py --limit 10
~~~

Exitcode 0 bedeutet: Die vorhandene vollständige lokale
SHA-256-Kette ist strukturell konsistent (auch wenn
sie leer ist oder nicht abgeschlossene Builds enthält).
Exitcode 2 bedeutet: beschädigter/nicht lesbarer Verlauf.
Auch ein Exitcode 0 ist **kein** neuer Release-Preflight.

## Tests und Auslieferungsgrenzen

- tests/sandbox/test_suite_build_history.py: Starts/Abschlüsse,
  neuer Sitzungsleser, ungeklärte Läufe, manipulierte Dateien,
  Sequenzlücken, doppelte Ergebnisse, falsche Ausgaben,
  lokale Sperren, Dateigrößen und CLI.
- tests/sandbox/test_suite_build_completion_gui.py:
  Persistenz ohne echten Builder, Historienanzeige,
  veraltete asynchrone Antworten, Beschädigung und
  blockierte Starts bei nicht schreibbarem Verlauf.
- tools/qa_suite_embedded.py: Zugriff im normalen
  Windows-Hauptfenster einschließlich Qt-Sandbox.
- Es wurde kein neuer Unity-/BC7-Bau, keine automatische
  Installation und keine Ingame-Abnahme ausgeführt.

Der tatsächliche Nachweis einer momentan auf dem Datenträger
vorhandenen BC7-Ausgabe erfolgt weiterhin über den separaten
tools/qa_release_preflight.py.


## Abschlussabnahme am 12. Oktober 2026

Die fortgesetzte, bereits im Entwicklungszweig vorbereitete Historie
wurde gegen den echten V2-Paketbau- und SHA-256-Abschlussvertrag
nachgeschärft und vollständig getestet:

- 44 lokale Historienfälle plus 15 Abschluss-Kernfälle:
  **59 bestanden**, einschließlich manipulierter Ereignisse,
  unterbrochener Starts, doppelt registrierter Abschlüsse und
  nicht zum ursprünglichen Manifest passender Offline-Erfolge.
- 10 echte Tk-GUI-Abschluss-/Verlaufsfälle bestanden:
  persistierter Start, Wiederlesen, Fehler- und
  Sperrbehandlung, kleineres Fenster und veraltete Antworten.
- Echter Windows-Tk-/Qt-Hauptfensterlauf:
  **PERSISTENT_BUILD_HISTORY_VIEW_ACCESSIBLE** und **QA_PASS**.
- Vollständige Projektregression nach Nachbesserung des älteren
  GUI-Testharness: **514 bestanden, 0 fehlgeschlagen,
  0 übersprungen** (491,56 Sekunden, Exitcode 0).
- Separater veröffentlichter Produktions-Preflight:
  **154/154 Dateien und 149 Gruppen**, 0 Fehler, 0 Warnungen.
- Der lokale Bauverlauf ist aktuell leer; seine read-only
  CLI-Abfrage legte kein Verlaufsverzeichnis an.

Die zusätzlich gespeicherten Quell-SHA-256 bezeichnen die
**beim Start überprüften** Eingänge. Sie sind keine unabhängige
Neuextraktion der Originalspielpixels und kein fortlaufender
Status der heutigen Builddateien. Ein alter offline_ok-Eintrag
darf nie anstelle eines **neuen** Release-Preflights
für einen aktuellen Mod verwendet werden.

**Weder ein neuer Unity-/BC7-Build noch eine Installation oder
Ingame-Freigabe wurde durchgeführt.**

# Paketbau-Abschluss in der Sprite Suite

**Stand: 12. Oktober 2026.** In der regulären Windows-Hauptanwendung.
Diese Anzeige ist keine automatische Installation und keine Ingame-Freigabe.

## Was beim Abschluss jetzt sichtbar ist

Unter **Paket bauen** gibt es nach einem in dieser Sitzung tatsächlich
gestarteten Build die Zeile **Bauabschluss** und die Schaltfläche
**Bauergebnis anzeigen**.

Die Suite unterscheidet zwei voneinander unabhängige Schritte:

1. **Build + verbindliche CLI-Validierung.** Die ursprüngliche
   suite_workflow.py-Baukette muss beide Schritte mit Exitcode 0 beenden.
   Auch im sonst nachsichtigen Einrichtungssystem wird eine
   fehlgeschlagene Bau-Nachvalidierung nicht zu einem Erfolg umgedeutet.
2. **Unabhängige Offline-Datei- und SHA-256-Prüfung.** Erst nach
   erfolgreichem CLI-Abschluss wird mit dem bestehenden
   release_preflight.audit_release die vollständige veröffentlichte
   Ausgabe geprüft. Diese Hash-Prüfung läuft in einem separaten
   Hintergrundthread und blockiert die Tk-/Qt-Oberfläche nicht.

Die Statusanzeige nennt **stets die Profil-ID des gerade
abgeschlossenen Bauversuchs**, auch wenn inzwischen ein anderes
Profil im Vorlagenwähler ausgewählt ist.

## Status-Unterscheidungen

| Status | Was tatsächlich nachgewiesen ist |
| --- | --- |
| BAU / VALIDIERUNG FEHLGESCHLAGEN | CLI-Fehler, fehlerhafte Nachvalidierung oder Abbruch; keine Anerkennung eines älteren Pakets |
| ABSCHLUSSPRÜFUNG FEHLGESCHLAGEN | Der anschließende unabhängige Offline-Abgleich konnte nicht verlässlich beendet werden |
| SHA-256-INTEGRITÄT FEHLGESCHLAGEN | CLI meldete Erfolg, aber das veröffentlichte Paket erfüllt die Offline-Hash-Kontrolle nicht |
| NICHT OFFLINE VERIFIZIERT | Die gewählte Ausgabe liegt außerhalb der vom aktuellen Release-Preflight unterstützten kanonischen Verzeichnisstruktur |
| AUSGABE IDENTISCH ZUM VORHERSTAND | Offline-Integrität ist korrekt, doch der Manifest-Hash entspricht dem Wert **vor** dem Bauversuch. Ein frisch generiertes anderes Paket ist dadurch nicht belegbar |
| OFFLINE OK MIT HINWEISEN | Alle erwarteten Paketbytes wurden bestätigt; separate Warnungen verlangen Aufmerksamkeit |
| OFFLINE SHA-256 OK | CLI-Bau + verbindliche Validierung erfolgreich und aktuelle Paketdateien unabhängig hashgeprüft |

Auch nach einem grün wirkenden Offline-Ergebnis steht immer
**Ingame-Abnahme AUSSTEHEND** im Hauptfenster. Es gibt keine
automatische Runtime- oder Releasefreigabe und keine Installation.

Für **nichtkanonische** (individuell verlegte) Ausgabeziele
behauptet die Software keine Hash-Abnahme mit einem Prüfer, der
eigentlich auf dist/<profil>/StrongholdEuropeDE festgelegt ist.

## Dauerhafter Verlauf nach einem Neustart

Zusätzlich zum Ergebnis des gerade in dieser Sitzung ausgeführten
Bauversuchs gibt es unter **Paket bauen → Bauverlauf anzeigen** jetzt
einen lokalen, bei jedem Öffnen erneut SHA-256-verketteten
Ereignisverlauf. Er zeigt auch nach einem Neustart die damals
tatsächlich erfassten Starts, CLI-Ausgänge und Offline-Resultate.
Nach einem Prozessabbruch ohne gespeicherten Abschluss lautet der
Status ausdrücklich **unbestätigt**, nicht bestanden.

Die Kette speichert *Nachweise über vergangene Prüfungen*, keine
aktuelle Hash-/Ingamefreigabe und keine Berechtigung zur
Veränderung von Produktions- oder Spieldateien.
[Speicherformat, Prüfgrenzen und Tests](BUILD_HISTORY.md).

## Verhalten bei Fehler und Abbruch

Vor dem Start nimmt die Suite nur die Manifestidentität des bisher
vorhandenen Pakets auf. Diese wird nicht verändert.

Schlägt der eigentliche Build- oder Validierungsprozess fehl, wird
**keine** SHA-Prüfung eines vorhandenen älteren Pakets als
Beweis des neuen Bauversuchs verwendet. Der Fehler bleibt sichtbar;
der Dialog nennt den CLI-Exitcode und die fehlenden Beweise.

Nur wenn der CLI-Lauf erfolgreich endet, führt die Suite den
vollständigen unabhängigen Offline-Abgleich aus. Der bisherige
und der danach beobachtete Manifesthash werden verglichen.
Ein identischer Manifesthash ist kein Fehler per se (deterministische
Builds können identische Bytes erzeugen), wird aber bewusst
**nicht** als Nachweis eines neu entstandenen Pakets ausgegeben.

Die Tk-Oberfläche bleibt während der SHA-256-Prüfung bedienbar.
Jede angezeigte Prüfung ist an ihren originalen Buildlauf
gebunden; veraltete Hintergrundantworten dürfen neue
Bauergebnisse nicht überschreiben.

## Ergebnisknopf und Nachweisgrenzen

**Bauergebnis anzeigen** zeigt die konkret erfassten Felder:
Profil, Exitcode, Integritätsstatus, Anzahl/Byteumfang der
verifizierten Dateien, Fehler und Warnungen, Manifest-SHA-256,
Vergleich zum Vorzustand sowie den ausdrücklichen Hinweis auf
die fehlende Ingame- und Releaseabnahme.

Der Dialog ist **nur lesend**. Er hat keinen Installations-,
Profilbearbeitungs-, Cache-Publish- oder Unity-Auslöseknopf.
Er ist kein Ersatz für die manuell geprüften Ingame-Bilder,
die noch offene Material-/Shaderparität oder die gepinnte
Unity-2021.3.45f2-Neukompilierung.

## Qualitätsprüfung

- tests/sandbox/test_suite_build_completion.py prüft
  die Unterscheidung zwischen CLI-Fehler, Offline-Fehler,
  Warnungen, unverändertem vorherigem Manifest, fremden
  Ausgabepfaden und geänderten Dateien während des Audits.
- tests/sandbox/test_suite_build_completion_gui.py prüft
  die Bindung an einen echten gestarteten UI-Auftrag,
  den asynchronen Abschluss, den Detaildialog und
  fehlende automatische Installation.
- Die bisherige Pipeline und der SHA-256-Abgleich bleiben
  unverändert; die neue Ebene schreibt keinerlei Spieldateien
  oder Pakete und startet beim Testen keinen echten BC7-Builder.
- tools/qa_suite_embedded.py überprüft den sichtbaren
  Abschlussstatus im normalen Windows-Tk-/Qt-Hauptfenster
  mit einem klar als **synthetisch** bezeichneten Fehlerfall.

**Wichtig:** Ein echter neuer Unity-Encoder-/BC7-Lauf wurde
für diese UI-Erweiterung nicht durchgeführt. Der lokal
vorhandene Produktionsbau kann unabhängig weiterhin mit
tools/qa_release_preflight.py überprüft werden.


## Abnahme auf dem autorisierten Windows-Projekt

- **Vollständige Projektsuite:** 465 Tests bestanden,
  keiner fehlgeschlagen, 1 wegen der portablen Tcl/Tk-Bibliothek
  übersprungen (523,12 Sekunden, Exitcode 0).
- **Übersprungener GUI-Fall separat wiederholt:**
  test_catalog_selection_never_retains_frame_from_other_group –
  **1 passed** (14,97 Sekunden). Der Fall wurde damit
  unabhängig vom Tcl/Tk-Initialisierungsproblem bestätigt.
- **Neue gezielte Abschluss-Kernfälle:** 15 bestanden,
  darunter alter Manifeststand, fehlgeschlagener Validator,
  korrupte SHA-Audit-Antworten, fremdes Ausgabeverzeichnis,
  geändertes Manifest und entfernte Ausgabe-Konfiguration.
- **GUI-Fälle:** Ergebnisanzeige und Hintergrundaufrufe geprüft;
  bei einem gemeinsamen kleinen GUI-Lauf trat einmal ein
  Tcl/Tk-Initialisierungs-Skip auf, der ausgelassene Fehlerfall
  wurde anschließend separat bestanden. Auch die
  alte Werkzeug-Abschlussereignis-Race wurde separat bestanden.
- **Echter Windows-Hauptfenster-Test:** QA_PASS inklusive
  SYNTHETIC_BUILD_COMPLETION_STATUS_VISIBLE und sämtlicher
  vorheriger Sandbox-/Katalog-/Pivot-/Release-Checks.
- **Produktionspaket rein lesend geprüft:** unverändert
  154/154 Dateien und 149 Gruppen; 0 Integritätsfehler
  und 0 Warnungen.

**Nicht erfolgt:** neuer Unity-BC7-Encoderlauf,
produktiver Bundle-Neubau, automatische Installation oder
eine tatsächliche neue Ingame-Abnahme.

# Sprite Suite – Feature-Benutzbarkeit und End-to-End-Prüfung

**Umfang:** Die gesamte normale Windows-Hauptanwendung, nicht nur
isolierte Python-Module. Geprüft wurden Einrichtung, Paketbau,
Asset-Katalog, Diagnose & Reparatur, Sandbox-Integration,
Editor/Austausch, Spielziele, Legacy-Werkzeuge und DE/EN-Navigation.

**Keine Sprite-, Modpaket-, Profil- oder Spielinstallation wurde für
diese UX-Prüfung ausgeführt.** Schreibende Funktionen wurden mit
Testdoubles überprüft, der bestehende produktive BC7-Build separat
rein lesend geprüft.

## Ausgangsbefund – bei realen Fenstergrößen reproduziert

Ein programmatischer Tk-Layout-Audit hat die Anwendung bei
**1320 × 800** und **1020 × 680** Pixeln geöffnet. Im kleinen Fenster
waren relevante Buttons ohne Scrollmöglichkeit vom Pack-Manager
nicht dargestellt:

| Bereich | Befund vor Korrektur |
| --- | --- |
| Einrichten | .NET-Download und Anleitung am unteren Ende nicht erreichbar |
| Asset-Katalog | Neu laden, Im Sandkasten zeigen und Profiländerung nicht sichtbar |
| Diagnose & Reparatur | Als geprüft markieren wurde von der Buttonleiste verdrängt |
| Editor & Austausch | ORA zusammensetzen/zerlegen am Fensterende nicht sichtbar |
| Paketbau | Fortgeschrittene Bauaktionen sind im Basismodus bewusst ausgeblendet |
| Hauptnavigation | Die manuelle Reiterleiste wird bei vielen Bereichen schnell unübersichtlich |

Zusätzlich wurden tatsächlich ausgeführte Callback-Pfade geprüft.
Ohne Gruppe reagierten mehrere Exportfunktionen still.
Bei ungültigem ORA-Startindex bzw. Raster konnte
ein ValueError aus dem Tk-Callback entweichen.
Bei HTML-Editor und ORA-Import lief der zweite Schritt nach
**1,5 bzw. 2,5 Sekunden**, auch wenn der vorgelagerte CLI-Lauf
noch nicht beendet war oder fehlschlug.
Der Katalog konnte eine Frame-Auswahl aus der vorigen Gruppe
beibehalten und ein externer Gruppensprung war nicht mit der
Baumauswahl abgeglichen. Das Index-Sprungfeld ignorierte
ungültige oder nicht vorhandene Nummern ohne Hinweis.

## Änderungen an der normalen Oberfläche

### Auffindbarkeit und Navigation

Eine neue **Schnellnavigation** liegt stets oberhalb der Reiterleiste.
Sie nennt sämtliche wichtigen Bereiche (Setup, Sprites,
Katalog, Diagnose, Sandbox, Editor, Spielziele, Paketbau und
Legacy-Tools) und öffnet bei Bedarf auch einen versteckten
erweiterten Bereich. Der bewusst gewählte Status
**Erweiterte Werkzeuge anzeigen** wird im privaten
Anwendungseinstellungsfile gespeichert und beim nächsten
Start wiederhergestellt; beim allerersten Start bleibt der
einfache Modus erhalten. Der Schnellnavigator aktualisiert
sich, wenn der Benutzer manuell den Reiter wechselt,
sowie beim Umschalten auf Deutsch bzw. Englisch.

### Kleine Fenster und Tastatur

Der Asset-Katalog hat jetzt:

- Eine eigene Zeile für die Katalogaktionen statt
  einer überladenen gemeinsamen Titelleiste.
- Eine jederzeit sichtbare, bewusst bestätigungspflichtige
  Schaltfläche zum Übernehmen bearbeiteter Frames ins Profil.
- Vertikal scrollbare Werkzeugaktionen, ein scrollbares
  Frame-Kachelraster und eine horizontale Scrollleiste
  für den Vier-Seiten-Vergleich.
- Einen gruppenabhängigen Suchzähler, ein
  explizites Such-Löschen (✕) und einen sichtbaren
  Hinweis bei null Treffern.
- Zum Frame springen mit verständlichen Meldungen
  bei ungültigem/nicht vorhandenem Index.
- Synchronisierung von externer Navigation
  (z. B. Diagnose → Katalog) und Baumkategorie;
  beim Gruppenwechsel keine alte Frame-Auswahl.
- Korrekte Canvas-Klickkoordinaten nach vertikalem Scrollen.

Die Einrichten- und Editor/Austausch-Seiten wurden zu
durchgängig scrollbar erreichbaren Formularen.
Mausrad und Tastaturfokus funktionieren nur im
jeweiligen Formular, ohne das native Sandbox-Studio
oder andere Fenster global abzufangen.
Für die Diagnose sind Prüfschalter und Verwaltungsaktionen
nun in getrennten Zeilen untergebracht.

### Verständliche, sichere Aktionen

- Keine stillen No-op-Aktionen mehr bei fehlender
  Editor- oder Atlasgruppe.
- Falsche ORA-Start-/Rasterzahlen und ungültige
  Rasterbereiche werden abgefangen, ohne eine
  Datei anzulegen oder ein CLI-Werkzeug zu starten.
- Beim Bauen eines SE-Atlas erhält der Benutzer eine
  Meldung, falls das gewählte Atlasprojekt
  noch nicht erstellt wurde.
- Das Ändern von Profilen (Katalog anwenden,
  Diagnose-Proofs übernehmen) verlangt
  jetzt einen klaren Dialog mit Default **Nein**.
  Ohne bearbeitete Katalogframes erfolgt
  kein unerwarteter Profilauftrag.
- Der HTML-Sprite-Editor wird erst geöffnet,
  wenn der Gruppenexport wirklich Exitcode 0 hat.
- Ein ORA-Ergebnis wird erst importiert,
  wenn das Zerlegen wirklich Exitcode 0 hat.
  Bei Fehlern oder Benutzerabbruch bleibt
  die Folgeaktion aus und der Hinweis im
  laufenden Prozessprotokoll sichtbar.
- Es wird weiterhin maximal ein CLI-Werkzeug
  gleichzeitig ausgeführt; der globale
  Abbrechen-Knopf bleibt unverändert.

## Umfang der technischen Abnahme

Die neuen Tests liegen unter
tests/sandbox/test_suite_usability.py und überprüfen
eine echte Universal-Suite-Instanz bei 1020 × 680 sowie
1320 × 800 Pixeln. Geprüft werden unter anderem:

- Anwählbarkeit aller zentralen Reiter und Schnellnavigation
  einschließlich bewusst versteckter alter Reiter.
- Persistenz der erweiterten Ansicht und Sprachwechsel
  DE/EN bei dynamischer Navigation.
- Erreichbarkeit des Katalog-Profilbuttons,
  des Reload-Buttons und der scrollbaren Editor-/ORA-
  und Einrichtungsschaltflächen.
- Rücksetzen alter Frame-Auswahlen, Gruppen-/Baumsynchronisierung,
  Filterlöschen und verständliche Index-Sprungfehler.
- Fehlende ORA-/Atlas-/Editor-Eingaben mit Dialog statt
  Fehlertraceback oder unbeabsichtigtem Ausführen.
- Profilübernahme nur nach ausdrücklicher Rückfrage.
- Fortsetzung mehrstufiger CLI-Arbeitsabläufe
  ausschließlich bei Exitcode 0;
  bei Fehler oder belegtem Runner keine Folgeaktion.
- Bereits vorhandene Tests und der reale native
  Tk-/Qt-Hauptfenster-Smoke-Test bleiben obligatorisch.

## Bestehende Grenzen, die nicht schöngefärbt werden

- Ein echter Unity-/BC7-Neubau braucht weiterhin die exakte
  Unity-Version 2021.3.45f2 und neue Geometrie-/Release-Proofs.
- Native Sandbox-Shader, Wasser, Nebel und Gameplay-HUD-Parität
  sind nicht vollständig identisch mit dem Zielspiel.
- Bei den älteren Spezialtools in der Werkzeugliste
  kann eine Funktion weiterhin echte Projektdateien ändern;
  die neue Schnellnavigation erweitert lediglich die
  Auffindbarkeit, nicht die Berechtigungen.
- Manche dynamisch erzeugten deutschen Diagnoseberichte
  und CLI-Ausgaben werden trotz englischer UI bewusst
  weiterhin auf Deutsch protokolliert.
- Für den allerersten Start werden Originalspielordner
  und gegebenenfalls die vorgesehenen Toolchains benötigt;
  Bedienbarkeit ersetzt keine vorhandenen Game-Assets.

**Ziel:** Alle sichtbaren Standardaktionen sind erreichbar,
nicht stille, ehrliche Statuskommunikation; gefährdende
Arbeitsfolgen nicht durch starre Wartezeiten.

## Abschließende Abnahme am 12. Oktober 2026

- Komplette Python-Projektsuite: **392 passed in 213.04s**, Exitcode 0; keine Tests übersprungen.
- Eigene Benutzbarkeitssuite: **13 passed, 1 skipped** bei gemeinsamem Tk-Lauf; der wegen instabiler portabler Tcl/Tk-Initialisierung übersprungene Schnellnavigationstest wurde separat mit **1 passed** bestätigt.
- Die GUI-Test-Fixture verwendet eine isolierte Workspace-Sperrdatei unter dem temporären pytest-Verzeichnis. Dadurch bleibt die produktive Ein-Instanz-Sperre unverändert und echte lokale Sprite-Suite-Prozesse werden nicht gestört.
- Echter Windows-Tk-/Qt-Hauptfenster-Smoke-Test: **QA_PASS**, inklusive FULL_SUITE_QUICK_NAV_ACCESSIBLE, Katalog/Sandbox-Übergängen, nativem Pivot-Beweis und eingebettetem Qt-Fenster.
- Python-Kompilierungsprüfung, JSON-Syntax, pip check und Windows-CRLF-konformer Git-Diff-Check erfolgreich.
- Diese Abnahme prüft **Bedienbarkeit und sichere Aufrufabläufe**; sie ersetzt keinen echten Unity-BC7-Neubau und keinen umfassenden Ingame-Test.


## Fortsetzung: Bauvoraussetzungen vor einem echten BC7-Neubau

Im Paketbau-Reiter ist jetzt der separate Button
**Bauvoraussetzungen prüfen** erreichbar. Der Hintergrundworker liest
das gewählte Profil, die lokalen Spielpfade, das Original-GZIP-Mapping,
den exakt gepinnten Unity-Editor, den .NET-SDK-Dateibestand und
die vorhandene Ausgabe, ohne einen Bauvorgang auszulösen.

Wichtig für die Bedienung: Die bisherige Einrichtungskontrolle arbeitet
standardmäßig nachsichtig und kann Warnungen ohne Abbruch melden.
Der neue Check behandelt **fehlende Voraussetzungen als Blockaden**
und stellt sie mit konkreten Einrichtungsschritten dar.
Er führt keine automatischen Reparaturen aus. Der eigentliche
**Paket bauen (mit Vorprüfung)**-Button verwendet denselben
aktuellen Check und verlangt danach eine ausdrückliche Bestätigung.
Quellhashes und Ausgabestatus werden vor dem Start erneut geprüft.
Eine fehlerhafte CLI-Nachvalidierung ist unabhängig vom
Nachsichtmodus ein Baufehler, keine Warnung mit Erfolgscode.
Anwendungsfelder für Unity/.NET/Spiele müssen gespeichert sein
oder dem tatsächlichen automatisch gefundenen Builderpfad entsprechen.

Der Status wird nach einer Änderung am Profil, am Ersetzen-Schalter
oder an Unity-/SDK-Eingaben ungültig. Insbesondere darf ein
vorheriges positives Ergebnis nicht stillschweigend für eine
andere Profil-/Toolchainkombination verwendet werden.

Der aktuell kontrollierte Produktionsprofilname
sprite-suite-world-bc7-v2 erhält eine **blockierte**
Neubau-Bereitschaft: die lokale Spielkonfiguration fehlt,
Unity 2021.3.45f2 ist nicht am exakt gepinnten
Werkzeugpfad vorhanden und ein vollständiges lokales
.NET-SDK wurde nicht verifiziert. Das alte, separat
bereits ausgelieferte BC7-Paket ist davon zu unterscheiden;
die neue Prüfung ist kein Release-Test.

Tests: tests/sandbox/test_suite_build_readiness.py sowie
test_suite_build_readiness_gui.py; unabhängiger
Windows-Hauptfenstersmoke in tools/qa_suite_embedded.py.
Weitere Bedienung: docs/BUILD_READINESS.md.


## Nachtrag: Keine Bau-Validierung als Warnung durchrutschen lassen

Am 12. Oktober 2026 wurde ein weiterer durchgängiger UX-Sicherheitsfall
umgesetzt und abgenommen: Der zuvor separate Bereitschaftsstatus war
noch nicht an den tatsächlichen **Paket bauen**-Knopf gebunden.
Darüber hinaus konnte der nachsichtige CLI-Workflow bei einer
fehlgeschlagenen *Nachvalidierung* bislang mit Erfolgscode enden.

Der Bauknopf führt jetzt vor **jedem** Bauversuch dieselbe frische
Hintergrundprüfung wie **Bauvoraussetzungen prüfen** aus.
Fehlende Spielpfade, Unity-Pins, SDKs, Mappings und unsichere
Paketausgaben blockieren. Eine erfolgreiche Prüfung verlangt
dennoch eine explizite Ja/Nein-Entscheidung (Standard Nein)
und eine erneute Quellen-/Ausgabekontrolle vor dem tatsächlichen Start.

Unspeicherte Einrichten-Eingaben können keine fälschlich positive
Bau-Bereitschaft mehr vortäuschen; Unterschiede zwischen
einem angezeigten Editor, den gespeicherten lokalen Einstellungen
und dem wirklich ausgewählten Unity-Editor werden als Blockaden
benannt. Der CLI-Bau meldet gescheiterte Nachvalidierung jetzt
unabhängig vom nachsichtigen Setupmodus als Fehler.

**Gesamtregression:** 445 Tests bestanden, keine Testfehler
(359,84 Sekunden). Echte Windows-Hauptfensterabnahme:
BC7_BUILD_BUTTON_GATED und QA_PASS. Zusätzlich bestätigt der
lesende Produktions-Preflight unverändert 154 Dateien,
149 BC7-Gruppen, 0 Fehler und 0 Warnungen.

[Abnahme und Bedienung](BUILD_READINESS.md).


## Erweiterung: eindeutiger Paketbau-Abschluss im Hauptfenster

Der Paketbau hat jetzt eine eigene Statuszeile und
**Bauergebnis anzeigen**, die den CLI-Exitcode samt zwingender
Nachvalidierung und einen **getrennten SHA-256-Offline-Abgleich**
darstellen. Ein fehlerhafter oder abgebrochener Bauversuch
kann keine bestehende frühere Paketausgabe als Erfolg erben.
Beim identischen Vorher-/Nachher-Manifest wird ausdrücklich
darauf hingewiesen, dass damit keine neuen Bytes belegt
sind. Alle Zustände behalten die Grenze
**Ingame-Abnahme AUSSTEHEND; keine Releasefreigabe**.

Der Bauabschluss bleibt an das konkrete ursprüngliche Profil
und den beobachteten Werkzeuglauf gebunden. Alte, noch in der
Tk-Warteschlange befindliche Werkzeug-Abschlussereignisse
können nicht dem neuen Build zugeordnet werden.
Die SHA-256-Prüfung läuft lesend im Hintergrund;
währenddessen bleibt das Hauptfenster responsiv.

Die reale Windows-Tk-/Qt-Abnahme bestätigte
SYNTHETIC_BUILD_COMPLETION_STATUS_VISIBLE und QA_PASS.
Der neue UI-Test verwendete einen ausdrücklich als
**synthetisch** gekennzeichneten Ergebnisfall,
keinen echten Produktions-Build.

Gesamte Projekttestsuite:
**465 bestanden, 0 fehlgeschlagen, 1 übersprungen
(523,12 Sekunden)**. Der einzelne Tcl/Tk-bedingt
übersprungene Katalogtest bestand separat (**1 passed**).
Produktions-Preflight: **154/154 Dateien,
149 Gruppen, 0 Fehler, 0 Warnungen**.

Vollständige Grenzen: docs/BUILD_COMPLETION.md.


## Dauerhafter lokaler Bauverlauf – Fortsetzung

Mit **Paket bauen → Bauverlauf anzeigen** kann die Suite nun ihre
tatsächlich gestarteten Buildversuche auch über Anwendungsneustarts
nachvollziehen. Jeder Start und jeder Abschluss werden als getrennte,
SHA-256-inhaltsadressierte Ereignisse in einem sequenziell verketteten
lokalen Journal abgelegt (nur in work/reports/, nicht in Git).

Die Anzeige unterscheidet abgebrochene/nicht bestätigte Bauversuche,
Startfehler, Fehler der unabhängigen Abschlussprüfung sowie
die damals gespeicherten Offline-Ergebnisse. Ein tatsächlicher
neuer Bauversuch wird gesperrt, wenn das Journal nicht sicher
gelesen oder erweitert werden kann. Beschädigte Einträge werden
nicht automatisch überschrieben oder repariert.

Der echte Paketbau bleibt weiterhin hinter der neuen
Bauvoraussetzungsprüfung, der ausdrücklichen Startzustimmung und
der verpflichtenden Nachvalidierung. Ein gespeichertes
Historien-„offline_ok“ ist keine Freigabe des heute vorhandenen
Pakets: Dafür muss der aktuelle Release-Preflight erneut laufen.

Tests: tests/sandbox/test_suite_build_history.py und
tests/sandbox/test_suite_build_completion_gui.py sowie
der native Tk-/Qt-Smoke-Test. Technische Grenzen:
[BUILD_HISTORY.md](BUILD_HISTORY.md).


## Abschluss: Dauerhafte Bauversuchs-Historie

Die Bedienung unter **Paket bauen** wurde um **Bauverlauf anzeigen**
ergänzt. Start- und Abschlussereignisse werden als SHA-256-verkettete,
begrenzt große lokale Datenobjekte dauerhaft gespeichert.
Der Dialog zeigt historische Provenienz (inklusive der beim Start
geprüften Eingangsdatei-Hashes), unbestätigte und fehlgeschlagene
Läufe sowie fehlende Release- und Ingamefreigaben. Anders als die
aktuelle Bauabschlussanzeige funktioniert die Historie auch
nach einem Neustart.

Die damalige Offlineintegrität wird nicht als heutige
Dateiintegrität ausgegeben: Zur erneuten Prüfung ist
**Diagnose & Reparatur → Gesamten Build prüfen (SHA-256)**
vorgesehen. Mutierte oder inkonsistente Protokolle sperren
den erneuten Bauversuch statt eine alte Freigabe zu erfinden.

Abnahme: **59 Kern-/Verlaufsfälle** bestanden,
**10 echte Tk-GUI-Fälle** bestanden, Windows-Tk-/Qt-Smoke
**QA_PASS**, vollständige Projektsuite
**514 passed in 491.56s**, 0 fehlgeschlagen/übersprungen.
Der echte Produktions-Preflight blieb bei 154/154 Dateien,
149 Gruppen, 0 Fehlern und 0 Warnungen. Kein Build oder
Spieleingriff während dieser Fortsetzung.

Einzelheiten: [BUILD_HISTORY.md](BUILD_HISTORY.md).


## Kompatibilitätsschritt: stabile .NET-SDKs ohne PATH-Zwang

Die Suite verwendet nun eine gemeinsame lesende SDK-Suche für
Einrichtungs-Vorschlag, BC7-Bauvoraussetzungen, Diagnose und
tatsächlichen Runtime-Builder: zuerst vorhandene PATH-Installationen,
anschließend portable `work/toolchains/dotnet-*`, DOTNET_ROOT bzw.
DOTNET_ROOT_X64 und übliche Windows-Systeminstallationen.
Ein veraltetes SDK oder eine reine Runtime im PATH verhindert nicht
mehr die Erkennung eines anderweitig vorhandenen stabilen SDKs.
Explizit ausgewählte unpassende Pfade bleiben erkennbar, statt
unbemerkt ignoriert zu werden.

Der Builder führt weiterhin einen eigenen `dotnet --version`-Probeaufruf
aus, bevor ein neuer Runtime-Build beginnt. Es gibt **keinen**
automatischen Unity-Versionswechsel, keine gelockerte Profil- oder
Manifestprüfung und keine eigenmächtige Änderung des Spiels.

Am lokalen Rechner erkennt die nur lesende Kontrolle nun das
SDK **10.0.401** unter `work/toolchains` und meldet für das
V2-Produktionsprofil nur noch **2 Blockaden statt 3**: lokale
Spielpfade und die tatsächlich erforderliche Unity-Version.
Die vorhandenen 154 Dateien des alten Pakets werden nicht geändert.
Neue isolierte Tests decken portable Fallbacks, veraltete PATH-SDKs,
DOTNET_ROOT, explizite Fehlkonfiguration und den verpflichtenden
Builder-Probeaufruf ab.


Die bisherige **65-Zeichen-Heuristik** des separaten Setup-Preflights
meldet einen langen Projektpfad jetzt nur noch als **WARNUNG**.
Sie ist keine zuverlässige Aussage darüber, ob Unity an diesem
Pfad tatsächlich scheitert. Ein funktionierender SDK-/Unity-Check
wird daher nicht mehr allein wegen der Pfadlänge als gescheitert
klassifiziert. Der echte Builder und seine Nachvalidierung bleiben
verbindlich; ein neuer Build wurde dafür nicht gestartet.


### Abschlussabnahme: SDK-Kompatibilität und verständliche Warnungen

- Neue isolierte Kompatibilitätstests: **8 bestanden** (portable SDK-Suche,
  DOTNET_ROOT, Runtime-only-/Altversionen, explizite Auswahl,
  obligatorische Builder-Probe und heuristische Pfadlängenwarnung).
- Gezielt ausgeführte GUI-/Buildtests: **29 bestanden**.
- Vollständige Projektregression: **522 bestanden, 0 fehlgeschlagen,
  0 übersprungen**, Exitcode 0 (510,81 Sekunden).
- Echtes Windows-Tk-/Qt-Hauptfenster: **QA_PASS**, einschließlich
  BC7_BUILD_READINESS_BLOCKERS_VISIBLE, BC7_BUILD_BUTTON_GATED,
  SYNTHETIC_BUILD_COMPLETION_STATUS_VISIBLE und
  PERSISTENT_BUILD_HISTORY_VIEW_ACCESSIBLE (Exitcode 0).
- Eigenständiger Produktions-Preflight: **154/154 SHA-256-Dateien,
  149 BC7-Gruppen, 0 Fehler und 0 Warnungen**.
- SDK 10.0.401 ist auf dem Rechner vorhanden; ein frischer
  Bereitschaftscheck meldet nur die zwei übrigen Voraussetzungen:
  lokale Spielpfadkonfiguration und Unity 2021.3.45f2.

Die neuen Prüfungen ändern weder das alte Produktionspaket noch die
Spielinstallation. Sie ersetzen keinen echten Unity-/BC7-Neubau,
keine Ingame-Abnahme und keine Releasefreigabe.


## Fortsetzung: inkrementelle und verlustarme Einrichtung

Die ursprüngliche Aktion `Pfade speichern` verlangte auch für reine
Unity-/SDK-Änderungen beide Spielordner. Außerdem ersetzte der
Konfigurator ungefragt sämtliche Werkzeugpfade durch die neu
übergebenen Felder und schrieb die Spielkonfiguration schon vor
der anschließenden Projektvalidierung.

Das neue Modul `stronghold_europe_de.suite_setup` trennt beide
Konfigurationsbereiche:

- Unity und .NET können einzeln auch vor einer Spielinstallation
  gespeichert werden; nicht angegebene Optionen bleiben erhalten.
- Spielroot und kanonische `*_Data`-Ordner sind gleichwertige
  Bedienangaben. Nach der Normalisierung wird ein unveränderter
  Spielpfad nicht erneut geschrieben.
- Ein bereits gespeicherter, tatsächlich geänderter Spielpfad
  verlangt im Hauptfenster eine explizite Bestätigung. Der
  CLI-Weg benutzt dafür `--replace`.
- Benutzerdefinierte Ausgabepfade, Policies, Kommentare und
  zusätzliche Konfigurationsschlüssel bleiben bei Spielpfadänderungen
  bestehen.
- Neue Spielkonfigurationen werden in einer temporären Datei
  über den echten `load_config`-Vertrag validiert, bevor die
  aktive Konfiguration ersetzt wird. Bestehende Versionen werden
  als lokale Backup-Dateien erhalten.
- Beide Dateiaustauschvorgänge erfolgen pro Datei atomar;
  scheitert der zweite, stellt der Konfigurator die erste
  Einstellung aus ihren vorherigen Bytes wieder her.
- Eine unvollständige Spielauswahl lässt im Hauptfenster
  ausdrücklich die Alternative zu, zunächst nur vorhandene
  Werkzeugangaben zu speichern.

Dabei werden keine Spiele, Profile, Assets, BC7-Pakete,
Installationen oder Cachedateien verändert. Das Speichern von
Werkzeugpfaden ist **keine** Bestätigung von Unity-Identität,
BC7-Baubarkeit, aktuellem SHA-256-Paketstatus oder Ingame-Freigabe.

Die gezielten Setup-/Bereitschaftstests inklusive GUI-Handler,
simuliertem zweitem Schreibfehler und Wiederherstellung sind
unter `tests/sandbox/test_suite_setup.py` dokumentiert.


## Abschlussabnahme am 13. Oktober 2026: schrittweise Einrichtung

Die bisherige Spiel-/Toolchain-Konfiguration wurde auf ein
inkrementelles, vor dem Schreiben prüfendes Verfahren umgestellt.
Neue Werkzeuge lassen sich getrennt speichern; bestehende
Spielpfade, Zusatzoptionen und Werkzeugangaben werden nicht unnötig
ersetzt. Geänderte Spielpfade erfordern eine bewusste Freigabe.
Bei Fehlern während des Dateiaustauschs werden vorherige
Konfigurationsbytes wiederhergestellt, und vorhandene Versionen
bleiben als Sicherungen erhalten.

**Abschließende Nachweise auf dem echten Windows-Rechner:**

- Vollständige Projekttestsuite: **540 bestanden, 0 fehlgeschlagen,
  0 übersprungen** in 616,05 Sekunden, Exitcode 0.
- Echter Windows-Tk-/Qt-Hauptfenstertest:
  **SETUP_TOOL_ONLY_SUBMISSION_NO_DISK_WRITE** und **QA_PASS**,
  einschließlich Navigations-, Katalog-, BC7-Baustart-,
  Bauabschluss- und Historienprüfung, Exitcode 0.
- Neuer GUI-Test erfasst den reinen SDK-Speicherauftrag, ohne die
  CLI auszuführen. Nach Abschluss existieren im echten Projekt
  weder `config/installations.local.toml` noch
  `config/toolchains.local.json`: Der Test hat also keine
  lokalen Installationseinstellungen angelegt.
- Unabhängiger SHA-256-Produktions-Preflight: **154/154 Dateien,
  149 BC7-Gruppen**, 0 Fehler, 0 Warnungen, Exitcode 0.
- Die historische Bewertung mit 1.009 bestandenen Prüfungen
  ist ausdrücklich kein neuer Unity-Build oder Ingame-Nachweis.
- Die vollständige Regression ist zusätzlich unter
  `work/reports/suite-setup-full-regression-20261013.log`,
  die Windows-QA unter
  `work/reports/suite-setup-native-gui-20261013.log` archiviert.

Es wurde kein neuer Produktions-Build ausgelöst, kein Mod installiert
und weder eine Spielinstallation noch das vorhandene BC7-Paket
verändert. Die Ingame-Abnahme bleibt ausstehend.


## Weitere Stabilisierung: Werkzeug-Konfiguration und Setup-Diagnose

Die lokale `config/toolchains.local.json` wurde zuvor an mehreren Stellen
unterschiedlich eingelesen: Ein fehlerhafter Inhalt konnte `suite.py`
für nicht betroffene Aktionen stoppen, im Hauptfenster wurden Fehler
teilweise verschluckt, und der portable Start konnte eine kaputte
Konfiguration automatisch überschreiben.

**Verhalten nach der Änderung:**

- Der gemeinsame lesende Parser prüft JSON-Duplikate, ungültige
  Konstanten, Wurzeltypen sowie die beiden bekannten Toolchain-Pfade.
  Fehler werden als konkrete **Warnungen** gezeigt; die Datei bleibt
  unangetastet und andere Werkzeuge können starten.
- Der portable Starter ergänzt fehlende beziehungsweise tatsächlich
  nicht mehr verwendbare SDK-/Unity-Pfade aus passenden portablen
  Installationen. Bei einer Änderung wird die bisherige gültige
  Konfigurationsdatei gesichert. Eine strukturell beschädigte Datei
  wird **niemals automatisch repariert**.
- Eine explizite Reparatur ist über den GUI-Dialog
  **Werkzeugkonfiguration gesichert reparieren?** mit Standardantwort
  **Nein** oder die CLI-Option `--repair-toolchain` möglich.
  Dabei wird die beschädigte Originaldatei bytegenau als
  `.bak-...` bewahrt, bevor ein neuer gültiger Tool-Pfad gespeichert
  wird. Wenn Reparatur abgelehnt wird, dürfen unabhängig gültige
  Spielpfade dennoch gespeichert werden.
- Die GUI übernimmt die aktuell gespeicherten Werkzeugpfade vor
  jedem Werkzeugstart neu und behält nicht unbeabsichtigt alte
  `PATH`-/Unity-Werte aus einem früheren Lauf.
- Unter **Einrichten → Einrichtungsstatus** gibt es jetzt eine
  zusätzliche **rein lesende Diagnose**. Fehlende Spielinstallation,
  veralteter SDK-/Unity-Pfad oder beschädigtes JSON werden getrennt
  mit einem Handlungshinweis aufbereitet.
- Die entsprechende CLI-Abfrage lautet
  `tools/qa_suite_local_setup.py` bzw. mit `--json`; ihr
  Exitcode 0 bedeutet ausschließlich: Bericht lesbar. Es findet
  kein Bau, keine Installation und keine Releasefreigabe statt.

**Sicherheitsgrenzen bleiben erhalten:** Die unabhängige
BC7-Bau-Bereitschaft akzeptiert weiterhin kein fehlerhaftes
Toolchain-JSON als erfolgreichen Nachweis. Selbst ein grüner
lesender Einrichtungsstatus ersetzt weder den gepinnten Unity-Pin,
den tatsächlichen .NET-Probeaufruf noch den unabhängigen
SHA-256-Release-Preflight.


### Abnahme der Werkzeugkonfigurations-Stabilisierung

- **560 Projekttests bestanden**, 0 fehlgeschlagen, 0 übersprungen,
  vollständige Regression 473,87 Sekunden, Exitcode 0.
- Echter Windows-Tk-/Qt-Hauptfensterlauf: **QA_PASS** und
  **SETUP_READ_ONLY_DIAGNOSTICS_ACCESSIBLE** sowie
  **SETUP_TOOL_ONLY_SUBMISSION_NO_DISK_WRITE**, Exitcode 0.
- Gezielte neue Setup-, SDK- und Readiness-Prüfungen:
  **82 Tests bestanden**; defekte JSON-Werte, verweigerte Reparatur,
  erhaltene Backup-Bytes, portabler Launcher, CLI, GUI und
  zurückgesetzte Werkzeugumgebungen eingeschlossen.
- Der read-only Einrichtungsstatus meldet am aktuellen Rechner
  0 Warnungen und 4 Hinweise: keine Spiel-/Werkzeugdatei konfiguriert,
  Unity für BC7 nicht gewählt, stabiles portables SDK 10.0.401
  gefunden (nicht ausgeführt).
- Unabhängiger Produktions-Preflight bestätigt erneut:
  **154/154 Dateien, 149 BC7-Gruppen**, 0 Fehler und 0 Warnungen.
- Weder die lokale `installations.local.toml` noch die
  `toolchains.local.json` wurden für die Abnahme angelegt.
  Die vollständige Regression wurde protokolliert unter
  `work/reports/suite-toolchain-recovery-regression-20261013.log`,
  die Windows-QA unter
  `work/reports/suite-toolchain-recovery-native-20261013.log`.

Der Abschluss betrifft die Zuverlässigkeit der Suite-Navigation
und Einrichtungsabläufe, nicht einen neuen Unity-/BC7-Produktionsbau.
Ingame- und Shader-/HUD-Abnahmen sind dadurch nicht erfolgt.


## Abschluss der Sandbox-Bedienbarkeitsrunde: 13. Oktober 2026

Die vorige reine Start-/HWND-Abnahme war kein ausreichender Nachweis für
einen tatsächlich bedienbaren Karteneditor. Ein geprüfter Screenshot
zeigte zu lange Aktionsleisten, breite fest eingeblendete Palette,
rechte Mini-Tabs und teils horizontal überlaufende Inspector-Formulare.
Hinzu kam eine **Win32-DPI-Doppel-Skalierung** der eingebetteten Qt-Ansicht.

**Implementierte Verbesserung:** Die eingebettete Sandbox startet jetzt
kartenorientiert mit versteckter linker Palette und nur dem relevanten
Karten-Inspector rechts. Die wichtigsten Aktionen heißen
**Karte öffnen, Palette, Inspector, Fokus, Layout zurück**. Weitere
Tools liegen in einem erkennbaren Dropdown. Die rechte Werkzeugauswahl
öffnet Animation, HUDs, Grafikvorschau und Inspector gezielt; ein
zuvor bereits gewählter Eintrag lässt sich nach dem Schließen zuverlässig
erneut öffnen. Das komplette Studio bleibt im selben Tk-/Qt-Fenster,
ohne verlorene oder schwebende Dock-Fenster.

Die DPI-Anpassung übergibt ausschließlich die physische Größe des
Tk-Host-HWNDs an Win32 `SetWindowPos`. Qt verarbeitet seine logischen
Maße selbst nach `WM_SIZE`. Die tatsächliche Inspektorbreite wird erst
danach an den aktuellen Platz angepasst, mit kurzen Bedienbeschriftungen
und vorhandenen Tooltips.

**Native Windows-Abnahme, nicht nur GUI-Imports:**

| Äußeres Suite-Fenster | Qt-Ansicht (logisch) | Nutzbare Kartenseite (logisch) | Inspector-Überlauf |
|---|---|---|---|
| 1500 × 930 | 1168 × 550 | 872 × 459 | 0 px |
| 1020 × 680 | 784 × 350 | 505 × 259 | 0 px |

Die Windows-QA hat die tatsächlichen Win32-Client-Rechtecke des
Tk-Hosts/Qt-Kindfensters, Qt-DPI-Umrechnung, nicht abgeschnittene
äußere Buttons, reale `ttk.Button.invoke()`-Klickwege, den Fokusmodus,
Palette, Inspector, wiederholte HUD-Auswahl, Reset, Navigation zwischen
Asset-Katalog und Sandbox, Originalkarten- und Testfeldansichten sowie
das sichere Schließen kontrolliert.

- Echter Tk-/Qt-Lauf: **QA_PASS**, Exitcode 0, Bericht in
  `work/reports/sandbox-layout-native-20261013.log`.
- Qt-Komponenten- und Sandbox-Integrationstests zusammen mit dem
  Setup-Regressionsteil: **59 bestanden**, Exitcode 0.
- **Gesamte Projekttestsuite: 574 bestanden, 0 fehlgeschlagen,
  0 übersprungen**, 501,12 Sekunden, Exitcode 0.
  Log: `work/reports/sandbox-layout-full-regression-20261013.log`.
- Unabhängiger SHA-256-Release-Preflight unverändert:
  **154/154 Dateien**, **149 BC7-Gruppen**, 0 Fehler, 0 Warnungen.
- Auch die zuvor noch nicht eingecheckte TOML-Einrichtungsrobustheit
  ist in diesen Tests enthalten: beschädigte lokale Spielpfad-Einträge
  verhindern nicht das Öffnen des Einrichtungsfensters und bleiben
  bis zu einer bestätigten Korrektur unverändert.

Es wurde weder ein neuer Unity-/BC7-Produktionsbau ausgelöst noch
ein Paket installiert oder eine Spiel-Originaldatei geändert.
**Die Ingame-Abnahme und der Unity-/Shader-Gleichheitsnachweis
bleiben ausdrücklich ausstehend.**

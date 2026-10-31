# SpriteSuite – Umsetzung der 19 Maßnahmen vom 31. Oktober 2026

**Prüfstand:** Lokaler Entwicklungszweig `fix/quality-gates-and-resilience-20261031`, Grundlage `49ed134`. Diese Datei ist ein offener technischer Abnahmebericht, **kein veröffentlichtes Release und keine Ingame-Bestätigung**.

## Prüfkriterien und tatsächlich abgeschlossene Tests

Die Änderungen befinden sich ausschließlich in einem neuen Git-Worktree. Reale Spiele, eigene Grafiken, installierte Mods und `work/` des ursprünglichen Projekts wurden nicht verändert.

- **Windows/Python 3.14, vollständiger instrumentierter Lauf:** **1.422 bestanden, 0 fehlgeschlagen, 33 übersprungen**. JUnit, vollständiges Log und Coverage-JSON liegen im gesicherten Testnachweis. Dauer: 513,42 Sekunden.
- **Zusätzlicher synthetischer Installer-Lebenszyklus:** **8 bestanden, 0 fehlgeschlagen** in eigenem JUnit-Lauf. Die separate Ausführung liegt daran, dass diese acht Tests nach dem Start der vollständigen Sammlung ergänzt wurden. Keine doppelte Zählung als ein einziger Komplettlauf.
- **Gemessene Gesamt-Zeilenabdeckung:** **42,28 %** gegenüber 40,39 % im letzten dokumentierten Vorgängerstand. Unterprozesse werden nicht zwingend im selben Coverage-Lauf erfasst.
- **Statisches Inventar:** **153 direkte Python-Werkzeugmodule** (vorher 145, jetzt acht zusätzliche Hilfs-/Prüfmodule), **1.710 Funktionen/Methoden**, 138 Python-Testdateien, 98 Module mit direkter Erwähnung in Tests und 55 ohne solche Referenz.
- **Synthetische Grafik-Performance:** 256² Pixel / 400%-Vorschau etwa 9–12 ms, 1024² etwa 36–38 ms, 2048² etwa 43–53 ms beim reinen Checkerboard-Rendern auf der untersuchten Maschine. Peak-RAM und vollständige GUI-Latenz **nicht gemessen**.

33 Tests mit privaten Originalspiel-/Grafikbelegen bleiben übersprungen, nicht bestanden. Die neue Release-Gate-Anwendung blockiert, solange solche Nachweise, ein verifiziertes Portable-Paket oder die separate Ingame-/Hardwareabnahme fehlen.

## Maßnahmen einzeln

| ID | Priorität | Status dieser Entwicklungsrunde | Tatsächlich implementiert / offene Abnahme |
|---|---|---|---|
| A01 | P0 | **extern blockiert** | Version/Portable-Builder vorbereitet; GitHub-Git-Installation hat keine zugänglichen App-Installationen. Öffentliche CI, PR und Release erfordern GitHub-Freigabe/Anmeldedaten und echte Python-3.13-Paketlaufzeit. |
| A02 | P0 | **wesentlich erweitert, nicht vollständig** | Echte Installer-Transaktion mit ausschließlich synthetischen Quellen: Neuinstallation, explizite Ersetzung, Deinstallation, Hash-Besitzbeleg, veränderte Dateien, Ablehnung, Spieleprozess-Sperre, künstlicher Fehler nach Manifest-Umbenennung und Rücknahme. Vollständige Matrix aller Umbenennungs-/Zugriffs-/Parallelfehler bleibt offen. |
| A03 | P0 | **Teilabschluss** | Validatoren `validate_mod`, `validate_runtime_log` und `profile_output_contract_checks` mit negativen, unveränderlichen Testinputs geprüft. Die riesigen Kernfunktionen wurden **nicht** riskant ohne Golden-Tests neu strukturiert; echte Unity-BC7-Golden-Korpora fehlen. |
| A04 | P0 | **fachliche Freigabe offen** | Existierende Noesis-Werkstatt kennzeichnet statische Overlays und `IsHitTestVisible=False` bereits ausdrücklich. Kein neues funktionales ViewModel-/Lua-/C#-Binding erfunden; dafür wären echte Spiel- und Script-Extender-Tests erforderlich. |
| A05 | P0 | **für ausgewählte Exportpfade umgesetzt** | Gemeinsame `OutputBatch`-Stage-/Hash-/Rollback-Hilfe und Integrationen für Gefechts-/Missions-Hintergründe und UI-Button-Katalog, vorheriger gesicherter UI-Atlas-Port unverändert. Bei unaufgelösten fremden Änderungen bleiben Recovery-Backups erhalten. Keine zugesagte Stromausfall-Atomarität oder automatischer Schutz aller historischen Werkzeuge. |
| A06 | P1 | **umgesetzt, mit Grenze** | `ImagePreview` prüft Quellzustand vor Decoder-Aufruf, rendert ein einziges Bitmap statt Tausender Tk-Kacheln und begrenzt die Vorschau auf maximal 2.048 Pixel Kantenlänge und rund 4 Mio. Pixel. Originalbilder bleiben pixelgenau. Separater Decoder-Worker und volle Zoom-Kachelansicht sind noch offen. |
| A07 | P1 | **umgesetzt, gezielt geprüft** | Begrenzte Tk-Ereignisqueue, UI-Budget von 180 Events/Zyklus, höchstens etwa 3.000 dargestellte Textzeilen, vollständiges lokales Job-Dateilog und maximal 8 MiB Data-Capture; Fail-Closed bei zu großen JSON-Antworten. Rotationsregeln und extreme Speicherlasten brauchen zusätzliche Tests. |
| A08 | P1 | **umgesetzt** | GUI-Start meldet Erfolg erst nach Tk-Ereignisschleifen-Handshake; bei frühem Crash lokales Fehlerprotokoll und Fehlercode. Synthetische Fenster-/Crash-Tests vorhanden; frische Portable-Startprüfung auf zweitem PC fehlt. |
| A09 | P1 | **teilweise umgesetzt** | Paketmetadaten `2.0.0` und Python-Versionsvertrag `3.13/3.14` vereinheitlicht; NumPy/SciPy als Asset-Abhängigkeiten genannt. Globale Migration aller historischen Versionstrings und installierten Kundenkopien nicht vorgenommen. |
| A10 | P1 | **Builder gehärtet, Release ausstehend** | Windows-Portable-Build verwendet gestagtes Ausgabeverzeichnis, reproduzierbare ZIP-Header, versionierten Namen und Quellcommit-Metadaten; Test für Zwischenfehler und Quellpaket-Wiederholbarkeit. Echter Py3.13-Build mit unveränderter Laufzeit und zweitem Gerät fehlt. |
| A11 | P1 | **vorhandener sicherer Transfer erhalten; Erweiterung offen** | Bereits bestehende geprüfte ZIP-Projektübertragung bleibt bestehen. Vollständige Trennung von Anwendungsprogramm und auswählbarem externem Projekt-Speicherort wurde nicht risikolos in diese Entwicklungsrunde hineingezwungen. |
| A12 | P1 | **begonnene Entkopplung** | Neue reine Module für Output-Transaktion, Fortschrittszustand, Diagnose, Sicherheitsklassifizierung, Vorschau und Freigabeprüfung. Tk/Qt-Hauptmodule mit mehreren Tausend Zeilen sind absichtlich noch nicht grundsätzlich neu geschrieben. |
| A13 | P1 | **erste durchgängige Übersicht** | Startseite zeigt Projekt→Mod→Ingame-Stufen. Bloße Existenz einer Build-Datei oder eines Installationsmanifests wird nicht mehr als unabhängiger Freigabenachweis dargestellt. Vollständige Hash-/Zeitpunkt-Verknüpfung über alle Stufen bleibt offen. |
| A14 | P1 | **synthetische Vorprüfungen, reale Referenzen offen** | Vorhandene 13/49 synthetische Kartentests und neue Fehler-/Rollbacktests; kein urheberrechtlich geschütztes Originalbild verteilt. Annotierte echte Golden-Bildmasken mit IoU-/Shader-Nachweis fehlen. |
| A15 | P2 | **manuelle Freigabe offen** | Frühere Tastatur-/DPI-/Accessible-Name-Tests erhalten. Echter Screenreader, 200%-DPI und Hochkontrast müssen auf physischer Windows-Oberfläche mit Belegen getestet werden. |
| A16 | P2 | **erste datensparsame Umsetzung** | Opt-in-Button `Diagnose exportieren`, JSON nur mit Programm-/Paketversionen und booleschen Bereitschaftshinweisen; keine absolute Spielpfade, Benutzernamen oder Rohlogs; neue Datei exklusiv. Detailliertes, redigierbares Fehlerpaket mit Crash-Kontext bleibt offen. |
| A17 | P2 | **synthetische Belastungsrunde** | Wiederholtes Erstellen/Schließen von 20 Vorschauen, 5.000 Job-Zeilen, große künstliche Bilder, Fehler-Injektion in mehrere Outputs. 100–500 vollständige Tk/Qt-Zyklen und mehrere Stunden realer Unity-Builds bleiben offen. |
| A18 | P2 | **Risikoklassifizierung integriert, nicht katalogweit fertig** | Dynamischer Werkzeugkatalog zeigt explizite Side-Effect-Klassen, wichtige Werkzeuge sind eingetragen, unbekannte Aktionen gelten nie automatisch als lesend. Vollständiges deklaratives Eingabe-/Ausgabe-/Dry-Run-Schema aller 145 Tools fehlt. |
| A19 | P2 | **erste Benchmarks, komplette Pipelinebudgets offen** | Synthetisches Pillow-Vorschaubenchmark mit exportierbaren Messwerten und festem Pixelbudget. Runtime-, Atlasdecode-, BC7-, Unity- und ZIP-Peak-RAM-Budgets auf einer definierten Testmaschine fehlen noch. |

## Neue Quellkomponenten und Abnahmetests

- `tools/suite_output_transaction.py`: isolierte Datei-Staging- und Rücknahme-Logik; `tests/sandbox/test_suite_output_transaction.py`, `test_suite_output_integrations.py`.
- `tools/suite_preview_render.py`: begrenzte Vorschau; `test_suite_preview_limits.py`, `test_suite_synthetic_stress.py`.
- `tools/suite_launch_status.py`: Start-Handshake; `test_suite_launch_handshake.py`.
- `tools/suite_diagnostics.py`: private Support-Diagnose; `test_suite_workflow_and_diagnostics.py`.
- `tools/suite_workflow_status.py`: Status-Stufen ohne ungeprüfte Erfolgsmeldung.
- `tools/suite_tool_policy.py`: Risikoanzeige in dynamischem Werkzeugkatalog; `test_suite_tool_policy.py`.
- `tools/suite_benchmarks.py`: künstliche Bild-Benchmarks, keine privaten Grafiken.
- `tools/suite_distribution_gate.py`: unabhängiger Freigabe-Gate, muss automatisierte, portable und manuelle Nachweise sehen; `test_suite_distribution_gate.py`.
- `tests/sandbox/test_installer_ownership_contracts.py`, `test_installer_lifecycle_synthetic.py`, `test_core_validation_negative_contracts.py`: Installer- und Validatorverhalten im künstlichen Dateibaum.
- `tests/sandbox/test_suite_release_reproducibility.py`, `test_suite_job_limits.py`: reproduzierbare Paketstruktur und begrenztes GUI-Logging.

## Produktgrenzen, die nicht weggetestet werden dürfen

1. **Niemals einen Git-Commit, PR, CI-Status oder Windows-Portable-Release behaupten, der nicht wirklich auf GitHub veröffentlicht wurde.**
2. **Ein XML-Patch oder ein sinthetischer Klick-Test ist kein Noesis-/Ingame-Nachweis.** Das originale Spiel und seine installierten Versionen müssen gezielt in einer autorisierten QA-Kopie geprüft werden.
3. **Ein ZIP-Quellcodepaket ist keine Portable-Anwendung.** Eine neue Python-unabhängige Windows-Ausgabe braucht CPython 3.13 x64, reale Qt-/Tk-Startprüfung, Hashes und 2. Geräteabnahme.
4. **Die Release-Gate-Logik kann nur die Existenz und Konsistenz der Nachweise prüfen.** Sie kann weder Screenshot-Echtheit noch menschliches Testurteil selbst feststellen.
5. **Migrations-/Versionsneutralität darf Benutzerdateien niemals automatisch überschreiben.** Die bestehende funktionierende ZIP-Projektübertragung bleibt der sichere Pfad, bis eine externe Projektablage separat entwickelt und geprüft ist.
6. **Bei unvollständigem Mehrdatei-Rollback gilt Recovery erforderlich**, nicht „erfolgreich“. Alte Staging-Backups werden in diesem Fall nicht gelöscht.

## Empfohlene notwendige externe Freigabeschritte

**Gate I / Veröffentlichung:** Berechtigten GitHub-Zugang verbinden; lokal getesteten Commit in PR und CI einbringen; Matrix Windows/Python 3.13 und 3.14 sowie zielgerichtete Python-3.11-Kompatibilität der historischen Archive beweisen.

**Gate II / Installer:** Echte Spiele bleiben unberührt, bis vollständige synthetische Fehlermatrix samt Recovery dokumentiert ist. Separate Spielkopien verwenden.

**Gate III / GUI:** Zwei unterschiedliche Windows-10/11-x64-Maschinen und mehrere Auflösungen/DPI-Stufen, Messprotokoll über GDI/Peak-RAM, lang laufende Builds und echtes Abbrechen.

**Gate IV / Spiel:** Rechtmäßig vorhandene Noesis-/Script-Extender-Dateien und Spiel-GUIs auf QA-Kopie, statische Overlay-Positionen und unveränderte Klick-/Fokus-/Hover-/Tastaturbereiche, Originalgrafik-Goldens. Funktionale Bindings bleiben separat zu entwickeln.

**Release nur nach menschlich belegter Abnahme.** Teilweise erledigte Punkte dürfen nicht als „vollständig umgesetzt“ abgehakt werden.

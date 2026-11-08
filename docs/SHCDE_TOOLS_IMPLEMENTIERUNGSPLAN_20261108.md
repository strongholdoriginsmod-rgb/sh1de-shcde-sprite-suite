# Stronghold-/SpriteSuite-Toolintegration: überprüfbarer Implementierungsplan

Stand 08.11.2026. Geltungsbereich E:\SpriteSuite_ToolIntegration_20261108. Die Reihenfolge entspricht der tatsächlich ausgeführten Arbeit; jeder Schritt besitzt ein Rückfallkriterium.

## Phase I: Bestandsaufnahme und Änderungsschutz

**01 – Quellidentität fixieren.** Ausgangskopie des neueren aktuellen Suite-Workflows aus E:\SpriteSuite_SHCDE_Expansion_20261108; Kopie ohne .git, work, cache, dist, state, historische Release-/Interpreter-Artefakte und lokale Secrets. Isoliertes lokales Git erstellen, nur die konkret betrachteten Python-/Testdateien als Rückweg einchecken. Ursprungsverzeichnisse bleiben unverändert. Abbruch bei fehlenden Dateien oder verdächtigen Junctions.

**02 – Audit-Quellen und Sicherheiten einordnen.** Analyse vom 06.11. mit 96 Wurzeln und aktuellem Branch-Bestand abgleichen. Versionsgebundene Read-only-Probes von installationsschreibenden Tools getrennt benennen. Keine fremde historische Datei in die neue Suite kopieren, bevor eine konkrete Funktion, das Datenformat, der Test und der Schutzvertrag belegt sind.

**03 – Ausgangstest ausführen.** Nur fokussierte Python-GUI-, Navigation-, Policy- und Inventurtests in einem neuen work/-Tempordner. Rückgabecode und Fehlermeldungen aufheben. Bestehende rote Tests sind zu erklären, nicht pauschal zu ignorieren. Besondere Aufmerksamkeit auf Windows-Tk/Grafik-Umgebung.

## Phase II: Gemeinsame Fachwerkzeug-Navigation

**04 – Registry als einzige kuratierte Fachliste verwenden.** Die bereits existierende suite_tool_registry.py nicht duplizieren und keine zweite künstliche Parser-Definition einführen. Nur Tools aus dem realen app.catalog_paths, mit vorhandenem regulären .py-File unter dem Suite-eigenen tools/-Ordner, als Navigationsziel zulassen; externe Links, ungültige und fehlende Tools ausschließen.

**05 – Strg+K integrieren.** build_navigation_targets(app) erweitert die vorhandenen Workspace-/Editor-/Sandbox-/Diagnose-/Build-Ziele dynamisch um tool:<dateiname>. Suchaliasse auf Deutsch und Englisch funktionieren mit existierender Normalisierung. Ein Klick wählt das existierende Katalogformular aus, ohne subprocess oder Import des Toolmoduls. Wenn der Katalog in einer reduzierten Fake-GUI fehlt, bleibt das Suchergebnis aus.

**06 – Expertenkatalog durchsuchen.** Im vorhandenen Katalog ein einfaches Textfilterfeld hinzufügen; Standard zeigt weiterhin alle vorhandenen Einträge einschließlich Pipeline und Expertenfunktionen. Wenn nach einer Auswahl gefiltert wird, muss der ausgewählte Toolname konsistent bleiben. Die seitengleiche Strg+K-Navigation darf beim Öffnen nicht an einem früheren Filter scheitern. Der Katalog darf keine internen Dateien selbst ausführen, bevor ein Benutzer den Befehl ausdrücklich bestätigt.

## Phase III: Hilfesicherheit und Ausführungsrisiko

**07 – Statische Hilfe.** suite_catalog.py um einen reinen Renderer der AST-basiert gewonnenen Parserinformationen ergänzen. Er soll Beschreibung, Unterbefehle, Optionen, Pflichtfelder, vordefinierte Werte und den Hinweis auf statische/nicht-ausgeführte Analyse darstellen. Für rein imperative Python-Skripte ohne Parser explizit die Dokumentation anzeigen, keine scheinbar vollständige CLI-Hilfe versprechen. Maximalgröße für Anzeige begrenzen.

**08 – Alle UI-Hilfepfade vom Prozessstart entkoppeln.** Center.catalog_help benutzt nur den Renderer und messagebox (oder einen scrollbaren read-only Dialog, falls praktisch), nie run_catalog. Eine manuell im Argumentfeld eingegebene Hilfeanforderung --help oder -h wird ebenfalls als statische Hilfe geroutet; Sicherheitslabel READ reicht allein nicht, wenn irgendwo ein Skript gestartet wird. Keine neue Bequemlichkeit darf alte Module unbemerkt importieren.

**09 – Risikoklassifizierung bei Ausführung wiederherstellen.** suite_tool_policy.classify und explain als zentrale Metadaten verwenden. Für unbekannte, externe, arbeitsbereichsschreibende oder spielschreibende Aufrufe einen separaten Bestätigungsdialog mit Name, Argumentsatz und Risiko anzeigen; Standardantwort Nein. Nur demonstrierbar rein lesende, ausdrücklich gewählte Aktionen dürfen ohne weitere Sicherheitsfrage starten. Bei unsicherer Klassifikation muss der Nutzer vor Ausführung bestätigen. Back-End-Validatoren und bestehende Installer-Sicherungen bleiben unverändert.

**10 – Keine pauschale Übernahme alter Installer.** Historische Version-Pins und Script-Extender-Tools bleiben read-only Quellen für den SHA-Vergleich; kein automatischer CLI-Import, Batch-Ausführungsmodus, offener Workspace-Write oder Game-Install in dieser Runde.

## Phase IV: Absicherung und Nachweise

**11 – Synthetische adversariale Tests.** Angreiferähnliches Skript mit Top-Level-Schreiboperation als Text in temporärer Datei: describe/static_help darf nichts anlegen; Center.catalog_help darf run_catalog nicht aufrufen. Testfälle für fehlenden/externen Registry-Pfad, für Hilfeanforderung im Ausführen-Formular, unbekannte oder Game-/Workspace-Risikoklasse, DE/EN-Suchziele und Filter-Rücknavigation.

**12 – Regression des vorhandenen Bestands.** Gefilterte komplette Python-Suite und zusätzliche Module suites/unified/projekt und besonders GUI/Workflow-Tests. Bei Fehlern nach Ursache unterscheiden: echte Produktabweichung, fehlende lokale Spiele-/Unity-Abhängigkeit, unvollständige Fixture oder aktueller WIP-Zustand. Anzahl und genaue Testauswahl statt pauschalem PASS dokumentieren.

**13 – Praxisinventur ohne Nebenwirkungen.** Einmal suite_tool_inventory.py gegen tatsächlich vorhandene E:\SS QA und E:\GS\StrongholdEurope-Projekt sowie E:\GS\StrongholdOrigins-Projekt ausführen; Ergebnis in lokales work/reports-Verzeichnis schreiben, niemals im historischen Quellbaum. Scanner darf keine DLL öffnen, Spielmod installieren oder Testskripte importieren.

**14 – Integritätscheck.** AST-Syntaxcheck aller veränderten Python-Dateien, git diff --check, Testauswertung; nur im isolierten Quellordner abschließen. Erzeugtes Paket bleibt ein Quellstand, keine native installierbare Freigabe. Rückweg: Commit 3e73119 auf gesondertem Integrationszweig, alte E:-Quellwurzeln unverändert.

**15 – Nutzer- und Entwicklerübergabe.** Dokumentieren: was bereits bestand, was wirklich geändert wurde, welche Altwerkzeuge absichtlich nicht übernommen wurden, wie die neue Suite gestartet und der Werkzeugkatalog verwendet wird, woran separate native Ingame-/Release-Gates scheitern bzw. offen sind, welche Tests tatsächlich bestanden.

## Abnahmebedingungen (verbindlich)

1. Es gibt keine neuen Prozesse bei Ctrl+K, reinem Filterwechsel, AST-Parseranzeige oder CLI-Hilfe.
2. Fehlende/externe Registry-Datei führt nicht zu einem startbaren Tool, sondern zu keiner Navigation oder klarer Fehlermeldung.
3. Eine Toolausführung mit Side-Effects ist ausdrücklich sichtbar, Risiko wird angegeben, Standard ist Abbruch. Ein Verneinen führt zu keiner Ausführung.
4. Historische SHA-Differenzen bleiben unverändert und werden nur beobachtet; keine Lösch- oder Installations-Aktionen.
5. Alle geänderten Dateien sind in der isolierten Kopie per Git nachvollziehbar, Quellkopie der laufenden Entwicklung bleibt unverändert.
6. Testfehler werden mit Ursachen und nicht durch Testabschaltung oder erfundene Erfolgszahlen behandelt.
7. Ingame-, native ABI-, Spielprofil- und Portable-Abnahme sind separate Prüfungen und werden nicht allein aus diesem Audit abgeleitet.

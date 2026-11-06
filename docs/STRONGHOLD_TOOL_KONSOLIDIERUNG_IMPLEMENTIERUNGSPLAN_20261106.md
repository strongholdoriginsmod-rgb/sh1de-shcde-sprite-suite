# Stronghold/SpriteSuite – kleinschrittiger Implementierungsplan
Stand 06.11.2026. Dieser Plan wurde VOR den funktionalen Codeänderungen in einem eigenen Git-Worktree festgeschrieben.
Arbeitszweig: E:\SpriteSuite_ToolConsolidation_20261106, feature/stronghold-tool-consolidation-20261106, Basis dffce3f.

## Leitprinzip
Bestehende Spezialimplementierungen verbinden, nicht erneut schreiben. Der normal sichtbare Weg ist das bereits vorhandene Mod-Projekt. Experten erhalten einen einheitlichen, gezielt adressierbaren Einstieg in ihren bestehenden Katalog. Jede automatische oder implizite Ausführung alter Tools ist verboten.

## Reihenfolge mit überprüfbaren Zwischenständen

### 00 – Eingriff begrenzen
- Nur E:\SpriteSuite_ToolConsolidation_20261106 unter eigener Branch bearbeiten.
- Quelldaten auf E:\SU_base, E:\SpriteSuite, E:\SpriteSuite_TileOverlap_20261106, die beiden Game-Installationen, Claude-/Codex-Arbeitskopien und die Python-3.13-/3.15-Portable-Releases NICHT ändern.
- Ausgangsstand via git rev-parse HEAD und git status verifizieren; wenn ungeklärte Änderungen existieren, vor dem ersten Edit stoppen.

### 01 – Ausgangslage vollständig inventarisieren
- Aktuelle tools/, src/, extras/sprite-editor/, installer/ und tests/ als unterschiedliche Komponenten behandeln.
- In historischen Wurzeln nur explizit vorhandene tools/ lesen; Dateinamen, SHA-256, Dateilänge und Vergleichsstatus ermitteln. Ein SHA-Match belegt Byteidentität, kein Vertrauensniveau.
- Claude-/Codex-Entwicklungsübergaben anhand ihrer tatsächlich vorhandenen Dateien klassifizieren; Sessiondaten oder Arbeitskopien nicht als installierte Werkzeuge missverstehen.
- Differenzlisten mit Status identisch, abweichend, nur_alt, nur_aktuell und fehlend dokumentieren.

### 02 – Bestandsfunktionen statt Ersatz suchen
- tools/suite_center.pyw: vorhandene Katalogauswahl, load_catalog, catalog_paths und catalog_tool prüfen.
- tools/suite_command_search.py: vorhandene Suchziele und ausschließlich navigierende Callbacks prüfen.
- tools/suite_tool_policy.py: bestehende Risikoetiketten wiederverwenden; unbekannt NICHT in read-only umklassifizieren.
- src/stronghold_europe_de/qa_inventory.py: feste historische Zehnerliste als Altfunktion erhalten; generellen Vergleich separat ergänzen.
- tools/suite_unified_workflow.py: Projektzustand bleibt Single Source of Truth.

### 03 – Änderungsgrenzen anhand realer Tests einfrieren
- Basistests ohne Produktänderungen ausführen: tests/sandbox/test_suite_command_search.py, test_suite_tool_policy.py, test_qa_inventory.py.
- Node-Editor-Tests ausschließlich im eigenen, bestehenden TileOverlap-Zweig lesen/ausführen; dort nichts für die Konsolidierung editieren.
- Nur weiterarbeiten, wenn Basis grün ist und die geänderten Quellen nicht den Spielinstallationsbereich berühren.

### 04 – Fachwerkzeug-Registry additiv erstellen
- Neue reine Metadatendatei tools/suite_tool_registry.py.
- Kuratiert nur vorhandene CLI-Fachwerkzeuge mit dokumentierter Aufgabe, DE/EN-Titel, Kategorie und Suchaliasen referenzieren.
- Verfügbarkeit anhand des bereits erzeugten app.catalog_paths prüfen: bei nicht vorhandenem Tool KEIN Suchziel; keine automatisch ergänzten Executables oder fremden Pfade.
- Weder Tools importieren noch Prozesse starten. Existing scripts und ihre Argument-Parser bleiben unverändert.

### 05 – Strg+K und Werkzeugkatalog verbinden
- build_navigation_targets(app) ergänzt für wirklich vorhandene, kuratierte Registry-Einträge Ziele mit stabilen tool:<dateiname>-IDs.
- Auswahl einer Fundstelle: zuerst Eintrag im existierenden Katalog validieren, dann vorhandenen Reiter öffnen, StringVar auswählen, load_catalog() zur reinen AST-Formdarstellung aufrufen.
- Keine subprocess-, build-, export-, install- oder config-Schritte bei Suche/Navigation. Alle existierenden Navigationsziele bleiben erhalten.
- Suchbegrenzung und deutsch/englische Suche bleiben mit bisherigen Regeln kompatibel.

### 06 – Maschinenlesbare Vollinventur als eigenes lesendes CLI
- tools/suite_tool_inventory.py ergänzt einen rein lokalen SHA-256-/Namensvergleich für eine Basis und beliebig viele ausdrücklich angegebene historische Wurzeln.
- Nur reguläre Tool-Code-Dateien im direkten tools/-Ordner; Links/Junctions nicht durchlaufen, interne Bibliotheken nur als Dateien und nicht durch Import bewerten.
- Pro Datei: Name, SHA-256, Bytes, eindeutiger Status, vorhandene Registry-Kategorie, Risikoetikett und statisch erkannter __main__-Einstieg.
- JSON oder Markdown auf STDOUT, keine Änderung eines Projektpfads durch einen Scan.
- Historische namensgleiche Dateien niemals überschreiben oder direkt importieren. Datenformat versionieren und deterministisch sortieren.

### 07 – Synthetische und sicherheitsbezogene Tests
- Neue Tests für Dateiidentität, unterschiedliche Inhalte, only-in-old, only-in-current, mehrere Quellen, leere gültige Tools-Verzeichnisse, Junction/Symlink und beschädigte/ungültige Eingaben.
- Im Test Dateien mit absichtlich gefährlichem Python-Quellcode anlegen; der Scanner darf keinen Inhalt importieren oder starten.
- Manipulierte Fake-GUI: Navigation darf kein app.run, subprocess, install oder config speichern auslösen; unknown files dürfen nicht als Fachwerkzeug registriert werden.
- Fehlende Katalogeinträge müssen vor jeder Zustandsänderung abgewiesen werden.
- Risikoklassen remain guidance only, never execute permission.

### 08 – Regressionen ausführen
- python -m pytest -q -p no:cacheprovider tests/sandbox/test_suite_command_search.py tests/sandbox/test_suite_tool_policy.py tests/sandbox/test_qa_inventory.py tests/sandbox/test_suite_tool_inventory.py
- Ergänzend relevante Original-Workflow-/Integrationstests ausführen.
- python -m compileall nur auf geänderte Python-Dateien, ohne Schreiben außerhalb Testarbeitskopie; vorzugsweise ast.parse zur reinen Syntaxprüfung.
- git diff --check, Git-Status und klare Diff-Prüfung; jede rote Prüfung analysieren, nicht wegignorieren.

### 09 – Realen Referenzbestand gegen das neue CLI prüfen
- Python-3.15-Zweig als read-only Basis, dann SU_base, SU/projekt, GS und SS QA als explizite Vergleichsquellen.
- Zahlen mit der unabhängigen Vorab-Erhebung abgleichen. Abweichungen erklären, keine stillen Umdefinitionen.
- Resultierende Reports nach ausdrücklicher Dateiausgabe nur im eigenen Branch unter work/reports/tool-consolidation/ ablegen; JSON ohne Geheimnisse.
- Keine automatisch ausgeführten Alt-CLI-Tools.

### 10 – Integration im isolierten GUI-Kontext prüfen
- Prüfen, dass neue Treffer wirklich den Katalog und das exakt gewählte Tool öffnen, ohne den Werkzeugprozess zu starten.
- GUI-Sprachwechsel/Strg+K, vorhandene Suche und bestehender manueller Ausführen-Dialog müssen weiterhin funktionieren.
- Falls die GUI im CI/headless nicht ausführbar ist, dokumentieren und KEINE GUI-Freigabe behaupten.

### 11 – Vorhandene Benutzerdaten abgleichen
- Den unveränderten Commit dffce3f als Integrationsbasis angeben.
- Separat nachweisen, dass der noch offene TileOverlap-Zweig auf derselben Basis beruht; aber dortige 36 Work-in-progress-Änderungen weder committen noch einspielen.
- Keine Änderungen der alten SU_base-Runtime, kein Upgrade des SE, kein Build/Installer.

### 12 – Dokumentation und Entscheidung aktualisieren
- Bericht mit Toolzahlen, SHA-Differenzen, neuen Bedienwegen, Testbelegen, offenen Kandidaten und expliziten Nicht-Integrationen ergänzen.
- Verbleibende manuelle Freigaben für Spieltests, geänderte ABI und spätere Git-Übernahme offen ausweisen.
- Eine zukunftsfähige gemeinsame Tool-Metadatenbasis ist Erfolg; eine pauschale Reduktion historischer Entwicklungszweige NICHT.

### 13 – Abschlussgate und Rückweg
- Alle Änderungen bleiben in der eigenständigen Git-Branch; nicht zu main pushen und keinen Release ersetzen.
- git status, git diff --check, Testprotokoll und Dateiübersicht prüfen. Nur den isolierten Branch committen, wenn alle gezielten Tests grün sind.
- Rückweg: Branch nicht mergen; der ursprüngliche stabile SHA dffce3f, alle Originalverzeichnisse, Archive und Spieldateien sind unverändert.
- Bei Problemen nur die neu eingeführten Registry-/Inventur-Änderungen im eigenen Zweig zurücknehmen, keine fremden Arbeitskopien zurücksetzen.

## Definition of Done
- Bereits existente 205 Tool-Dateien bleiben byteidentisch erhalten.
- Fachwerkzeuge aus Strg+K im vorhandenen Katalog direkt auswählbar, ohne Ausführung.
- Maschineller Vergleich über mehrere historische Wurzeln vorhanden; identische Dateien werden als identisch angezeigt, abweichende als zu prüfen.
- Unbekannte/versionsgebundene Werkzeuge weder eingespielt noch unbemerkt ausgeführt.
- Bestehende Tests und neue Sicherheits-/Navigationstests grün; Spielinstallationen nicht angerührt.
- README/Analyse/Plan nennen klar, dass Ingame- und zweitgerätebasierte Freigaben weiterhin getrennte Gates sind.
# Abnahme und Implementierungsnachweis: Stronghold-/SpriteSuite-Werkzeuge

Stand 08.11.2026. Quelle ist die isolierte Arbeitskopie E:\SpriteSuite_ToolIntegration_20261108. Der Auftrag wurde in einem zusammenhängenden Arbeitsgang als Analyse → Plan → nicht-destruktive Implementierung → Regression → Nachweis durchgeführt.

## I. Ausgangsstand und Schutz

- Quellstand: E:\SpriteSuite_SHCDE_Expansion_20261108, als separate lokale Kopie ohne fremde Git-Interna und Laufzeit-/Spieldaten.
- Zusätzliche validierte GUI-Referenzen: E:\SpriteSuite_FinalCandidate_20261106; ausschließlich suite.pyw und suite_universal.pyw nach AST-Methodenvergleich übernommen und vorher unter work\pre_modern_gui_backup in der isolierten Kopie gesichert.
- Bereits bekannte Sicherheitsregeln aus E:\GS\StrongholdEurope-Projekt\AGENTS.md, CLAUDE.md wurden berücksichtigt: Originalspiele sind Eingaben, keine Arbeitsdateien.
- Isolierter Git-Checkpoint 3e73119 (Integration-Branch). Kein Push, kein Merge in fremde Zweige, keine Spielinstallation und keine freigegebene Release-Aktualisierung.
- E:\SpriteSuite mit fremden nicht eingecheckten Änderungen; die aktuelle SHCDE-Expansion und frühere Claude-/Codex-/QA-Kopien bleiben unverändert.
- Historische native Runtime-/ABI-/RVA-/Installer-Skripte wurden nicht ausgeführt und nicht übernommen.

## II. Umfang der Erhebung

Die allgemeine Quellinventur fand 96 ausgewählte E:-Wurzeln. 69.754 quellcodeartige Rohvorkommen reduzierten sich nach Ausschluss typischer eingebetteter Interpreter auf 37.908 Quellvorkommen mit 2.432 unterschiedlichen SHA-256-Inhalten. Davon sind 35.476 Wiederholungen. Diese Zahlen sind NICHT die Zahl funktionsfähiger Tools. Absolut alle jemals vorhandenen Binär- oder Archivprogramme lassen sich ohne weitere externe Medien nicht beweisen.

Die zweite, reproduzierbare Werkzeugmatrix untersuchte zusätzlich die direkten und verschachtelten tools/-Dateien von acht realen Entwicklungswurzeln, darunter E:\SS QA, E:\GS\StrongholdEurope-Projekt, E:\GS\StrongholdOrigins-Projekt, E:\SU_base und E:\GSX. Sie ist bewusst beschränkt auf Dateien mit Quellcode-Endungen, überspringt Cache-/Vendorpfade und folgt keinen Links.

Lokale Evidenz:
- C:\Users\matth\Documents\SHCDE_Tools_Consolidation_20261106\analysis_rebased.json
- work\reports\tool-integration\full_tool_matrix.json und full_tool_matrix.md
- work\reports\tool-integration\tool_summary.json
- work\reports\tool-integration\source_integrity.json
- work\reports\tool-integration\backend_final_junit.xml (nach finaler Testausführung)

## III. Umgesetzte Integration – nicht als Neuimplementierung vorhandener Backends

### A. Ein Einstieg in bestehende Fachwerkzeuge

- tools/suite_command_search.py verknüpft die bereits vorhandene kuratierte Registry mit Strg+K.
- tools/suite_center.pyw bietet einen filterbaren Expertenkatalog, DE/EN-Fachaliasse und unveränderte bestehende Parserformulare.
- tools/suite_tool_registry.py navigiert ausschließlich zu lokalen vorhandenen Python-Toolquellen. Filterzustände können ausgewählte Treffer nicht mehr verstecken.
- tools/suite_catalog.py stellt statisch analysierte CLI-Hilfe dar. Module mit potentiellen Top-Level-Nebenwirkungen werden bei Hilfe nicht gestartet.
- suite.py leitet die direkte Werkzeughilfe ebenfalls über statische Quellprüfung statt einen Skript-Prozess.
- tools/suite_tool_policy.py verlangt für unbekannte, externe, schreibende und spieländernde Aktionen eine gesonderte Bestätigung; voreingestellt ist Abbruch.
- tools/suite_tool_inventory.py ergänzt optionalen rekursiven, rein lesenden SHA-Vergleich und unterscheidet identisch, abweichend, nur_aktuell, nur_historisch sowie unprüfbar.

### B. Ein Projektzustand und flexibler, abgesicherter Paketbau

- tools/suite_unified_project.py nutzt den vorhandenen Paket-Builder statt eine parallele ZIP-Pipeline zu schaffen.
- tools/se_asset_package.py repariert die fehlende package_zip_path-Schnittstelle; vollständige Dateinamen mit Punkten bleiben erhalten; das Exportziel wird ohne Überschreibung gesichert.
- Strenger statischer Asset-Export und freies Mod-Projekt sind getrennt. Für freie Projekte dürfen eigene Moddateien byteidentisch übernommen werden. Ist ein eigenes info.json vorhanden, bleibt es erhalten.
- Eine native Datei ohne eigenes Manifest erzeugt nur dann ein explizites, als UNGEPRÜFT gekennzeichnetes Offline-Entwurfsarchiv, wenn der Benutzer bewusst den Projekt-Exporter verwendet. Der eigenständige Standard-CLI-Exporter verlangt weiterhin einen authored Manifest-Nachweis.
- tools/hud_menu_workspace.py prüft frei hinzugefügte Projektdateien ebenfalls in der gemeinsamen Inventur. Unbekannte Payloads werden nicht ausgeführt.
- Benutzergewähltes „Mod-ZIP speichern unter“ baut zunächst vollständig intern unter work/, überprüft ZIP-Mitglieder, SHA und Projektstand und veröffentlicht danach ausschließlich das geprüfte ZIP am gewünschten neuen Dateipfad – nie ein Mod-/Spiel-Verzeichnis.
- Freie Anzeigenamen/Versionskennungen sind nur im ausdrücklichen Projektexport möglich. Der statische Standardexport behält seine formalen Versionsvorgaben.
- Der Exportbericht unterscheidet ZIP-Dateiintegrität, native ABI und reale Spielabnahme ausdrücklich.

### C. Veraltete oder riskante Spezialwerkzeugverträge korrigiert

- tools/ui_apply.py, ui_einpflegen.py: gemeinsame geschützte Pfadauflösung gegen Traversal, Junction, Windows-Gerätenamen, falsche Dateien; Einpflege skaliert kleine Motive nicht ungewollt hoch.
- tools/suite_windows_paths.py: zentraler reiner Dateipfadprüfer statt unvollständiger eigener Pfadfilter.
- tools/ui_pair.py, ui_rahmen.py, ui_sh1_extract.py, ui_sh1_umstellung.py, ui_vorlage.py sowie ui_apply und ui_einpflegen: globale Abschaltung von Pillow-MAX_IMAGE_PIXELS entfernt. Der Decompression-Bomb-Schutz bleibt aktiv.
- tools/background_v2_pipeline.py und ui_button_catalogue.py: vorher/bei Fehlerschlägen unvollständige Mehrdatei-Ausgaben werden über den vorhandenen OutputBatch gemeinsam vorbereitet und transaktional veröffentlicht.
- tools/se_asset_package.py: echte WebM-Menü- und UTF-8-Locale-Validierung statt unbedingter Ablehnung oder ungeprüfter Freigabe.
- pyproject.toml: der zum neueren Python-3.13–3.15-Quellzweig passende Version-2.0.0-Vertrag aus einem vorhandenen geprüften Kandidaten übernommen; keine neue frei erfundene Abhängigkeit.

### D. GUI-Versionen abgleichen, nicht alte Klassen zurückkopieren

- Vor Übernahme der beiden neueren GUI-Quellen wurden die AST-Klassenmethoden gegen den alten Stand verglichen; keine vormals vorhandenen Methoden fehlten im neueren Referenzstand.
- Moderne Navigationsleiste, Hauptprojektseite und die alten Fachreiter verwenden dieselbe Suite und dieselben Daten.
- ModernShell erhält DE/EN-Subtitle, Archive-Aktionslabels und die richtige Rootbindung der Advanced-Checkbox.
- Der gemeinsame Workflow übersetzt auch persistente echte Knöpfe, Spaltenüberschriften und das „Mehr“-Menü, nicht nur Statusmeldungen.
- Der visuelle/technische ZIP-Entwurf ohne geprüfte native Laufzeit wird als ENTWURF und nicht als spielbereiter Mod angezeigt.

## IV. Neue bzw. verbesserte Regressionstests

- tests/sandbox/test_suite_catalog_safety_20261108.py: Schädlicher Top-Level-Code wird beim Lesen der CLI-Hilfe niemals ausgeführt; Fehlpfade, Registry, Hilfeargumente und schreibende Aktionen werden gesperrt bzw. bestätigt.
- tests/sandbox/test_suite_mod_package_bridge_20261108.py: Erweiterter statischer/unrestricted Export, manipulierte Pfade, expliziter Draft-Vertrag, DLL-Binäridentität, ZIP-Dateinamen mit Punkten und exklusiver sicherer Save-As-Export.
- tests/sandbox/test_suite_tool_inventory.py: rekursiver Dateiabgleich, Links/Junctions, untergeordnete Quellen und gleiche/differierende Hashes.
- tests/sandbox/test_suite_tool_policy.py: wieder aktivierte ausdrückliche Sicherheitsbestätigung statt stiller Spieländerungen.
- tests/sandbox/test_suite_command_search.py: echte aktuelle Navigation statt historischer fester Reiterpositionen; sichtbarer Sidebar-Suchknopf statt bewusst verborgener Legacy-Toolbar.
- tests/sandbox/test_suite_unified_workflow_gui.py: Exportfehler enthalten eine überprüfbare Fehlermeldung statt nur AttributeError.
- Bereits vorhandene Tests für Spezialwerkzeuge, Release-Quellen, Build-Workflow, Projekt-Roundtrip, Ausgabetransaktionen, Tk-ModernShell, Origins-Medien und Noesis sind Teil der ausgewählten Regressionen.

## V. Abnahme und reproduzierbare Befehle

Im isolierten Ordner E:\SpriteSuite_ToolIntegration_20261108 gilt als Testinterpreter E:\SpriteSuite\.venv\Scripts\python.exe (Python 3.13), mit den PYTHONPATH-Unterordnern tools und src. Alle pytest-Läufe nutzten isolierte basetemp-Pfade unter work/; der finale Windows-Pfadlängentest nutzte ausschließlich das kurze Verzeichnis q/ innerhalb der Integrationskopie. Kein Test wurde ins Spiel installiert.

- Erste neue Fokustests: 39 bestanden, später mit CLI-Hilfe 40.
- Statischer Paketbau und neue Moddatei-/Pfadsicherheit: 34 bestanden.
- Spezialbild-/Mehrdatei-Transaktionsregression: 47 bestanden.
- Moderne Hauptoberfläche als eigener vollständiger Lauf: 14 bestanden.
- Gemeinsamer Projekt-GUI-Workflow als eigener vollständiger Lauf: 26 bestanden.
- Größerer Backendlauf vor der Pillow-/Sidebar-Korrektur: 191 bestanden, 3 fehlgeschlagen. Die tatsächliche Ursache war siebenfaches globales Deaktivieren von Image.MAX_IMAGE_PIXELS sowie der veraltete Test eines absichtlich ausgeblendeten Legacy-Suchknopfs.
- Zweiter Backendlauf: 192 bestanden, 2 fehlgeschlagen. Die zwei Origins-XAML-Testbelege hatten durch den überlangen Windows-basetemp-Pfad eine zu lange Kombination von Verzeichnissen und SHA-Dateinamen.
- Beide Originalszenarien mit kurzem isolierten Testpfad E:\SpriteSuite_ToolIntegration_20261108\q einzeln: 2/2 bestanden, ohne eine Zeile des getesteten Origins-Codes zu ändern.
- Abschließende aktuelle Backend-Sammelabnahme mit kurzem Windows-Pfad und allen 21 ausgewählten Testmodulen: **194 bestanden, 0 fehlgeschlagen**, Exitcode 0. Nachweis: work\reports\tool-integration\backend_final_junit.xml und backend_final.log.
- Separate vollständige GUI-Abnahme: **14/14 Modern-Shell-Tests** und **26/26 Unified-Workflow-GUI-Tests** bestanden.
- Gesamtsumme der drei getrennt gezählten finalen Testgruppen: **234 bestandene Tests**. Frühere Wiederholungsläufe sind nicht addiert. Eine native Ingame-Abnahme oder vollständige Prüfung aller vorhandenen Testmodule ist damit NICHT behauptet.

## VI. Nicht übernommene / bewusst offene Bereiche

1. Historische SS-QA-RAM-, Full152-, native Selection- und Cold-Start-Abnahmen sind an ältere Quell-/Spiel-/Manifest-Hashes gebunden; ihre Messwerte sind kein aktuelles Release-Gate.
2. Alt-Skripte wie runtime_install.py, shcdese_install.py und system_workflows.py können DLLs, Spielinstallationen oder Script Extender verändern. Sie bleiben als Referenz getrennt; keine automatische Migration oder Ausführung.
3. StrongholdOrigins-Kampagnen-/Lua-/C#-Runtime hat eigene Missions-/Versionsverträge. Der gemeinsame Editor kann kompatible Assets bearbeiten, aber die native Kampagnenstate-Machine bleibt eigenständig.
4. Es gab keinen echten SHCDE-Spielstart, keinen Script-Extender-ABI-DLL-Test, keine neue Noesis-Ingame-Automation, keinen Live-Paket-Installer und keine öffentliche Releasefreigabe.
5. Eine 100-prozentige semantische Vollabnahme aller historischen Quell- und Binärprogramme ist durch den SHA-Fundstellenabgleich nicht ersetzt.
6. Kein historisches Verzeichnis wurde gelöscht, keine fremde Git-Arbeit zurückgesetzt, keine Originalspiel-Datei ersetzt. Das ist ein absichtlicher Sicherheitsentscheid, keine übersehene Dublette.

## VII. Wiederherstellung und Übergabe

- Isolierter Quellbestand: E:\SpriteSuite_ToolIntegration_20261108
- Prüf- und Belegdateien: E:\SpriteSuite_ToolIntegration_20261108\work\reports\tool-integration
- Ältere GUI-Quellen zur Rücknahme: work\pre_modern_gui_backup
- Git-Ausgangs-Checkpoint: 3e73119, isolierter Branch integration/shcde-tool-workflow-20261108
- Analyse und Vorannahmen: docs\SHCDE_TOOLS_ANALYSE_20261108.md
- Ausführlicher Stufenplan: docs\SHCDE_TOOLS_IMPLEMENTIERUNGSPLAN_20261108.md
- Bedienung: docs\SHCDE_TOOLS_ANLEITUNG_20261108.md

Die isolierte Quellkopie ist das implementierte Ergebnis. Sie wird nicht automatisch in die öffentlich verteilte SpriteSuite oder das installierte Spiel kopiert. Eine spätere Freigabe soll über einen gesonderten geprüften Merge mit den dann aktuellen parallelen Änderungen, reale Windows-Portable- und Ingame-QA sowie eigenständige Native-ABI-Gates erfolgen.

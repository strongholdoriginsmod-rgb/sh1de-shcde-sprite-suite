# Stronghold / SpriteSuite: Gesamtaudit der verfügbaren Entwicklungswerkzeuge

Stand: 08.11.2026. Arbeit ausschließlich an einer isolierten lokalen Quellkopie unter E:\SpriteSuite_ToolIntegration_20261108.
Status vor der Umsetzung: überprüfter Befund; keine Ingame- oder native Releasefreigabe.

## 1. Datenherkunft, Reichweite und Zählweise

Die untersuchten Arbeitsbestände liegen unter E:\SpriteSuite, E:\GS, E:\GSX, E:\SU, E:\SU_base, E:\SS QA, weiteren SS*/SpriteSuite*/SCDE*-Wurzeln und historischen Stronghold-Origins-Quellen. Claude-Projektmetadaten und Codex-Entwicklungsordner wurden als Quellhinweise, nicht als automatisch lauffähige Tools behandelt.

Der breit angelegte lokale Dateiscan vom 06.11. hat 96 E:-Wurzeln und 69.754 quellcodeartige Vorkommen erfasst. Nach Ausschluss erkennbarer eingebetteter Python-Laufzeiten blieben 37.908 Quelldatei-Vorkommen mit 2.432 unterschiedlichen SHA-256-Inhalten und 35.476 byteidentischen Wiederholungen. Ein enger Abgleich von 23 direkten tools/-Quellbäumen fand 41 historische direkte Dateinamen, die in der damaligen Suite fehlten; der breitere Vergleich einschließlich Unterverzeichnissen meldete 53 Kandidatennamen. Diese Zählungen sind nicht identisch definiert.

Keine dieser Zahlen bezeichnet selbstständige, funktionierende Programme. Nicht vollständig geprüft wurden kompilierte Binärdateien, eingebettete Spielassets, alle vergangenen externen Datenträger und sämtliche Claude-/Codex-Sitzungsinhalte. Vollständigkeit im Sinne aller jemals existierenden Dateien lässt sich nicht behaupten. Die maschinenlesbaren Rohinventare liegen unter C:\Users\matth\Documents\SHCDE_Tools_Consolidation_20261106.

Die ältere E:\SpriteSuite-Arbeitskopie weist umfangreiche ungesicherte Änderungen auf. Andere jüngere E:-Zweige und historische Veröffentlichungen sind nicht gleichbedeutend mit dem aktiven Quellstand. Die Quellkopie dieser Arbeit stammt aus E:\SpriteSuite_SHCDE_Expansion_20261108, wobei Git-Interna, Spielstände, Runtime-Installationen, Caches und lokale Einstellungen ausgeschlossen wurden. Der externe Stand wird nicht verändert.

## 2. Funktionsgruppen und Integrationsentscheidung

| Bereich | Aktueller funktionsführender Ort | Entscheidung |
|---|---|---|
| Projekt, Quellen, Speichern | suite_unified_project.py, suite_unified_workflow.py | Ein Projektzustand; keine zweite Workbench |
| Navigation und Werkzeugkatalog | suite_universal.pyw, suite_center.pyw, suite_command_search.py | Gemeinsame kuratierte Suche und Fachfilter |
| CLI-Formulare | suite_catalog.py (statische AST-Auswertung) | Hilfe ausschließlich statisch, keine impliziten Skriptstarts |
| Spezial-Sprites, ORA, Tile, GM1 | sprites.py, tile_objects.py, kachelraster_gm1.py, Editor | Originalformat- und Geometrieverträge bewahren |
| HUD, Noesis, XAML, Origins-UI | hud_menu_*, ui_sh1_*, origins_* | In Suite auffindbar, separate Versions-/Formatprüfungen |
| Asset-Atlas, Unity, BC7 | se_atlas.py, ui_atlas.py, src/stronghold_europe_de/asset_stream_* | Status-/Arbeitsschrittkette integrieren, Encoder getrennt |
| Sandbox und Live-Vorschau | sandbox_* und src/stronghold_europe_de/sandbox | Vorhandene eingebettete Ansicht beibehalten |
| Grafik-/Pivot-/Manifest-Diagnose | grafik_*, pivot_*, qa_release_preflight.py | Lesende Prüfung ohne Spielveränderung |
| Build und Installation | suite_workflow.py, ziel_se211.py, Installer | Ausführung sichtbar und gesondert bestätigt |
| Historische QA | qa_inventory.py und suite_tool_inventory.py | Allgemeiner Hashvergleich ergänzend zur Zehnerliste |
| HP-/Feuer-/Damage-Renderer | building_damage_*, qa_building_damage_* | Bereits vorhanden, Tests getrennt von Ingame-Gate |
| Historische C#-/Lua-/SE-Sonden | SS QA, SU_base, StrongholdOrigins-Projekt | Keine automatischen Binär-/RVA-/ABI-Übernahmen |

Die historische RAM-Abnahme hat feste Zähl- und Speichergrenzen, und der alte Full152-Lauf verlangt gebundene EXE-/Manifest-Identitäten und längere Beobachtung. Das PowerShell-Werkzeug system_workflows.py kann über grosser_lauf.ps1 bauen und installieren. Daher dürfen historische Werkzeuge nicht unbesehen im aktuellen dynamischen UI als harmlose Diagnose angeboten werden.

## 3. Konkrete überprüfbare Defekte in der vorgefundenen neueren Quellkopie

A. Die Registry suite_tool_registry.py deklariert vorhandene Spezialwerkzeuge. Sie wird aber in der kopierten suite_command_search.py nicht in build_navigation_targets eingebunden: Die Tool-Tests erwarten tool:-Treffer und finden keine. Vorhandene Registry ist damit in der Tastatursuche funktionslos.

B. In suite_center.pyw ruft catalog_help() bei erkannten argparse-Feldern run_catalog(..., --help) auf. Das ist echte Skriptausführung. Bei Modulen mit Top-Level-Nebenwirkungen wird bereits durch das Anzeigen von Hilfe geschrieben, obwohl suite_catalog.py die Parserdaten statisch lesen kann.

C. Die gleiche Katalogoberfläche startet aus catalog_run() ohne gesonderte Zustimmung; selbst bei Zielinstallationswerkzeugen. Eine Quellprüfung und eine Ausführung sind unterschiedliche Aktionen. Ein expliziter Klick auf „Ausführen“ allein ersetzt keine Klarstellung von Risiko/Ziel/Argumenten für unbekannte oder installationsschreibende Tools.

D. Der Werkzeugkatalog listet weitgehend die Namen aller direkten Python-Dateien. Damit sind interne Fachbausteine, alte Helfer und menschlich bedienbare Programme schwer unterscheidbar. Eine dynamische Textfilterung und die gemeinsame kuratierte Registry erleichtern die Bedienung, ohne eine zweite Tool-Implementierung zu schaffen.

E. Der SHA-Vergleicher arbeitet ausschließlich im direkten tools/-Ordner. Das ist für seine dokumentierte Quelltools-Matrix richtig, aber nicht für eine absolute Vollständigkeitsbehauptung. Das Modul darf nicht plötzlich Assets oder unbekannte Unterprogramme importieren. Optionales Erkunden weiterer Entwicklungswurzeln bleibt eine eigene sichere Bestandsphase.

F. In der vorgefundenen Quelle lief der fokussierte Test-Baselineversuch zunächst mit fehlendem work/-Temporärordner in Fixture-Probleme. Nach Erstellen des isolierten Arbeitsordners ergab sich der reproduzierbare Ausgangswert 21 bestandene und 4 fehlgeschlagene Tests (Navigation, GUI, Safety-Policy). Die GUI-Abweichung ist getrennt zu analysieren; ein grüner Teststand war zu Beginn NICHT gegeben.

## 4. Sicherheits- und Versionsgrenzen

Keine Änderung an Originaldateien unter den installierten Stronghold-1-/Crusader-Data-Ordnern, EXEs, DLLs, SE-Plugins, realen Mods oder anderen parallel benutzten Arbeitskopien. Keine automatische Übertragung alter nativer Runtime-Binaries. Weder Build-Validierung noch historische Logs ersetzen Ingame-Abnahme. Export ohne explizite Zielauswahl und positive Prüfrechnung darf nie als Release markiert werden.

Unterschiedliche Dateihashes beweisen Änderungsbedarf zur Prüfung, nicht automatisch, welche Fassung korrekt ist. Gleiche Hashes beweisen identische Bytes, nicht gleiche Herkunft und nicht, dass ein Tool noch gebraucht wird. Im Zweifel bleiben alte Tools erhalten und werden als historisch/ungeprüft gekennzeichnet.

## 5. Zielzustand

Ein einziges bestehendes SpriteSuite-Projekt mit dem vorhandenen Expertenkatalog; Strg+K findet sichere Fachziele, auch in Deutsch/Englisch. Der Katalog ist filterbar, zeigt statisch belegte CLI-Hilfe und eine aktuelle Risikoeinstufung; Ausführungen sind vom Navigieren und vom Anzeigen der Hilfe getrennt. Eine reproduzierbare SHA-Matrix bleibt schreibgeschützt. Synthetische Tests beweisen insbesondere, dass Suche/Hilfe nie Skripte ausführen.

## 6. Nachweisschlüssel und Reproduktionspfad

Quell-Audit: C:\Users\matth\Documents\SHCDE_Tools_Consolidation_20261106\analysis_rebased.json und code_inventory.jsonl.
Vorhandener früherer Plan: docs\STRONGHOLD_TOOL_KONSOLIDIERUNG_IMPLEMENTIERUNGSPLAN_20261106.md.
Lokaler Ausgangs-Checkpoint: isoliertes Git-Repository im neuen Quellordner, Commit 3e73119.
Dieses Dokument wird durch einen gesonderten Implementierungsplan und einen Testbericht ergänzt.

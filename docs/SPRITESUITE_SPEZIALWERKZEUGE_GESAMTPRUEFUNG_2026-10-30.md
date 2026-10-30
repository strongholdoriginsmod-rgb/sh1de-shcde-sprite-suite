# SpriteSuite – kritische Prüfung sämtlicher Spezialwerkzeuge

**Stand:** 30. Oktober 2026 · **Quelle:** separater lokaler Reparaturzweig. Kein veröffentlichter GitHub-Stand und keine neue Portable-Freigabe.

## Prüfergebnis

| Prüfschritt | Messwert | Aussage |
|---|---:|---|
| Inventarisierte Werkzeugmodule | 145 | Sämtliche direkten `tools/*.py` erfasst |
| Werkzeugfunktionen und Methoden (AST) | 1681 | Statische Erfassung, **keine** Einzel-Funktionsabnahme |
| Python-Quelldateien im statischen Scan | 263 | Parserprüfung ohne Syntaxfehler |
| GUI-Startdateien (*.pyw) | 3 | Zusätzlich separat syntaktisch geprüft |
| Python-Testdateien im Reparaturstand | 123 | Bestehende und ergänzte Testdateien |
| Sichere Modulimport-Tests | 145/145 | Import in frischem Python-Prozess ohne konfiguriertes Spiel |
| CLI-Hilfe-Aufrufe | 77 bestanden | Nur Module mit Argparse-Einstiegspunkt, **keine** tatsächliche Export-/Modinstallation |
| Vollständige Regressionstests (Reparaturstand) | 1296 bestanden; 0 fehlgeschlagen; 33 übersprungen | 1329 Tests gesammelt |
| Gemessene Python-Zeilenabdeckung | 39.8% | Gesamte instrumentierte Quellbereiche, einschließlich historischer Werkzeuge |
| Module ohne direkte Nennung in Tests | 59 | Indikator für Funktionstest-Lücken; indirekte Tests möglich |

## Vorgehensweise und Sicherheitsgrenzen

Der Test erfolgte in einem **separaten Git-Worktree**, mit künstlichen Testprojekten, schreibgeschützten Originalreferenzen soweit vorgesehen, isolierten Python-Abhängigkeiten und ohne Änderungen an Benutzerprojekten. Modul-Imports, Argparse-`--help`, Testfälle, Syntax, Dateipfade, Archivprüfungen, Quellenintegrität und GUI-/Engine-Verträge wurden getrennt bewertet. Für private Spielressourcen ausgefallene Testfälle werden als **übersprungen** und nicht als bestanden geführt. Externe Windows-Hardware, echte Spielinteraktion und jede fachliche Sonderfunktion pro Eingabedatensatz sind **nicht** vollständig abgenommen.

## Festgestellte und behobene Fehler

1. **Projektdatei-ZIP-Import** (`project_inputs.py`): vorher Dateiersetzung möglich; jetzt feste Größen- und Namensregeln, SHA-256, ZIP-Strukturprüfung, exklusive Ziel-Dateierstellung, sichere Abbruchlogik und Regressionstests.
2. **Original-Engine-Aufnahme** (`native_runtime.py`): Unterprozess verlor vorhandenen `PYTHONPATH` und damit NumPy in isolierten Installationen; verifizierter Quellpfad und vorhandener Modulpfad werden gemeinsam übergeben.
3. **Spezialisierte Bildwerkzeuge** (sieben UI-Module): globales Deaktivieren des Pillow-Decompression-Bomb-Schutzes entfernt; Schutz bleibt aktiv.
4. **HUD-XAML-Diagnosewerkzeuge** (`hud_buildings.py`, `hud_tree.py`): kein Importfehler ohne konfiguriertes Spiel; explicit `--xaml`, kontrollierte Fehler und schreibgeschützte Extraktion statt unguarded Import.
5. **Windows-Konsole** (`build_locale.py`): Hilfeausgabe auf Standard-Codepages ohne Unicode-Crash, gut lesbare Einleitung.
6. **Python 3.14 aus Quellcode**: bisher fehlende GUI/NumPy/SciPy-Pakete ergänzt; vollständiger Hash-Lock wurde durch pip `--dry-run --require-hashes` erfolgreich aufgelöst.
7. **Qualitätsregressionen**: historischer Atlas-Vergleich akzeptiert nur die beiden absichtlich geänderten Hilfetexte; GUI-Umschaltertest prüft korrekt den Wechsel des Ausgangszustands.
8. **Bild-Erzeugung und UI-Import** (`ui_einpflegen.py`): Kleine Motive werden nicht mehr unbemerkt hochskaliert. Import-Zielpfade müssen vollständig innerhalb des Exportordners liegen. Der gleiche Pfadschutz gilt für die Zuordnungsdateien aus `ui_apply.py`.
9. **Tk-Mehrfensterfall** (`suite_center.pyw`, `suite_universal.pyw`): Einstellungen werden an den eigenen Tk-Interpreter gebunden; der Schalter für erweiterte Werkzeuge wird auch bei mehreren Tk-Fenstern geprüft.

## Weiterhin nicht vollumfänglich nachgewiesen

- **Echte Ingame-Aktionen**: Statische Noesis-XAML-Vorschau ist nicht gleichzusetzen mit erfolgreich neu positionierten, klickbaren Spielbuttons.
- **Jede Funktionskombination**: Der statische AST-Scan erfasst 1681 Methoden/Funktionen, aber ein Großteil wird nicht durch dedizierte Tests erreicht.
- **Private Original- und Spieldaten**: Übersprungene Szenarien fehlen weiterhin der unabhängigen manuellen Freigabe.
- **Unabhängiger zweiter Windows-PC und End-to-End-Bedienung**: Diese Abnahme ist nicht durch GUI-Mocktests zu ersetzen.
- **Neue GitHub-Actions-Pipeline**: Workflow ist im lokalen Quellstand vorbereitet, die Veröffentlichung bleibt mangels Schreibrechten (HTTP 403) ungeprüft.

## Nachweis je Arbeitsbereich

| Bereich | Automatisiert geprüft | Noch nicht gleichbedeutend mit Freigabe |
|---|---|---|
| Projekt-ZIP, Dateiimport, Metadaten | Synthetic Roundtrips, Checksummen, Konflikte, Grenzwerte | Übertragung großer realer Benutzerprojekte auf zweiten PC |
| UI-Atlas, Bild-Einpflege, Paarung | Import-/CLI-Smoke und synthetische Bild- und Pfadtests | Vollständige visuelle Kontrolle sämtlicher Atlasvarianten |
| Sprite-/Vegetationswerkzeuge | Modulprüfung, deterministische Bild- und Geometrie-Regeln | Alle realen Spielsprites und Animationen ingame |
| Karten-/Original-Engine | Native Snapshot-, Rendering- und Auswahltests | Freigabe sämtlicher Karten-/Spielversionen |
| HUD/Noesis/XAML | Syntax, Sicherheitsregeln, Diagnostik und synthetische Layout-Tests | Tatsächliche klickbare Spielelemente in einer echten Spielrunde |
| Windows-Tk/Qt-Oberfläche | Automatisierte UI-Tests und Mehrfenster-Regression | Bedienung auf mehreren physischen Benutzer-PCs |
| CI und Paketierung | Lokale Testpipeline, Integritätskontrollen, Hash-Lock-Dry-Run | GitHub-Schreibzugriff und öffentliches neues Windows-Portable-Paket |

## Fehler- oder Risikomarker in Quelltexten

Die folgende Tabelle zeigt **Suchtreffer**, keine nachgewiesenen Schwachstellen. Dateischreib-, Lösch-, Unterprozess- und Netzwerkzugriffe können legitim und entsprechend geschützt sein.

| Kennzeichen | Anzahl erfasster Vorkommen |
|---|---:|
| subprocess | 16 |
| delete | 82 |
| overwrite | 181 |
| download | 16 |
| code_eval | 1 |

## Modul-Matrix (alle 145 Werkzeugmodule)

**Import:** separat geprüfter Import. **CLI:** `--help`-Prüfung (n/a = kein Argparse-Einstieg). **Testbezug:** nur statische Referenz in einer Testdatei. **Coverage:** instrumentierte Zeilen des vollständigen Testlaufs, ohne importierte Unterprozesse.

| Modul | LOC | Methoden | Import | CLI | Testbezüge | Coverage | Statische Review-Hinweise |
|---|---:|---:|---|---|---:|---:|---|
| `asset_katalog.py` | 1056 | 55 | ok | ok | 2 | 25% | subprocess, delete, overwrite |
| `atlas_contract_gui.py` | 7 | 0 | ok | n/a | 0 | 0% | – |
| `background_review.py` | 208 | 8 | ok | ok | 0 | 0% | overwrite |
| `background_v2_audit.py` | 213 | 10 | ok | ok | 0 | 0% | overwrite |
| `background_v2_inner_blend.py` | 89 | 2 | ok | ok | 0 | 0% | overwrite |
| `background_v2_manual_mask.py` | 116 | 3 | ok | ok | 0 | 0% | overwrite |
| `background_v2_masked_edit.py` | 270 | 9 | ok | ok | 0 | 0% | overwrite |
| `background_v2_pipeline.py` | 242 | 12 | ok | ok | 0 | 0% | overwrite |
| `background_v2_pointed_window.py` | 181 | 4 | ok | ok | 0 | 0% | overwrite |
| `background_v2_refine_mask.py` | 103 | 3 | ok | ok | 0 | 0% | overwrite |
| `backgrounds.py` | 393 | 13 | ok | ok | 0 | 0% | delete, overwrite |
| `boar_recolour.py` | 231 | 5 | ok | ok | 0 | 0% | delete, overwrite |
| `build_locale.py` | 317 | 8 | ok | ok | 0 | 0% | overwrite |
| `build_portable_windows.py` | 230 | 6 | ok | ok | 1 | 22% | subprocess, delete, overwrite |
| `build_ui_bc7_cache.py` | 117 | 2 | ok | ok | 0 | 0% | overwrite |
| `check_stale_artifacts.py` | 90 | 2 | ok | ok | 0 | 0% | – |
| `community_mod_compat.py` | 347 | 8 | ok | ok | 1 | 73% | delete, overwrite |
| `compose_runtime_refresh.py` | 327 | 6 | ok | ok | 0 | 0% | delete, overwrite |
| `compose_ui_bc7_candidate.py` | 84 | 1 | ok | ok | 0 | 0% | – |
| `cross_match.py` | 153 | 4 | ok | ok | 0 | 0% | – |
| `deorientalise.py` | 312 | 6 | ok | ok | 0 | 0% | overwrite |
| `editor_bruecke.py` | 295 | 12 | ok | ok | 1 | 0% | – |
| `europeanize_backgrounds.py` | 208 | 10 | ok | ok | 0 | 0% | overwrite |
| `fortification_visual_recipes.py` | 189 | 6 | ok | ok | 0 | 0% | delete |
| `generate_ui_texture_source_manifest.py` | 193 | 4 | ok | ok | 0 | 0% | overwrite |
| `grafik_analyse.py` | 303 | 14 | ok | ok | 0 | 0% | – |
| `grafik_diagnose.py` | 419 | 14 | ok | ok | 0 | 0% | overwrite |
| `groups.py` | 448 | 13 | ok | ok | 10 | 0% | subprocess, overwrite |
| `hole_blatt.py` | 48 | 1 | ok | n/a | 0 | 0% | delete |
| `hud_buildings.py` | 113 | 6 | ok | ok | 1 | 81% | download |
| `hud_menu_layout.py` | 806 | 43 | ok | n/a | 7 | 88% | delete, overwrite |
| `hud_menu_metadata_paths.py` | 119 | 3 | ok | n/a | 1 | 85% | delete, overwrite |
| `hud_menu_noesis_integration.py` | 464 | 19 | ok | ok | 2 | 78% | delete, overwrite, download |
| `hud_menu_noesis_qa.py` | 196 | 9 | ok | n/a | 2 | 76% | subprocess, delete |
| `hud_menu_project_transfer.py` | 415 | 12 | ok | n/a | 2 | 83% | delete, overwrite |
| `hud_menu_workspace.py` | 395 | 18 | ok | n/a | 9 | 85% | delete, overwrite |
| `hud_tree.py` | 97 | 4 | ok | ok | 1 | 74% | download |
| `kachelraster_gm1.py` | 76 | 2 | ok | ok | 0 | 0% | – |
| `locale_text.py` | 270 | 8 | ok | ok | 0 | 0% | overwrite |
| `locate_unit.py` | 175 | 4 | ok | ok | 0 | 0% | – |
| `make_reference_root.py` | 104 | 3 | ok | ok | 0 | 0% | delete, overwrite |
| `modding_host.py` | 249 | 9 | ok | n/a | 0 | 0% | – |
| `native_geometry_probe.py` | 157 | 3 | ok | ok | 0 | 0% | – |
| `origins_grafikdaten.py` | 391 | 11 | ok | ok | 2 | 71% | subprocess, delete, overwrite, download |
| `pin_digests.py` | 450 | 10 | ok | ok | 1 | 0% | subprocess, overwrite |
| `pin_xaml.py` | 72 | 1 | ok | ok | 0 | 0% | overwrite |
| `pivot_bc7_stage.py` | 71 | 1 | ok | ok | 1 | 82% | – |
| `pivot_native_proof_rows.py` | 118 | 2 | ok | n/a | 1 | 94% | – |
| `pivot_review_gui.py` | 432 | 18 | ok | n/a | 3 | 86% | – |
| `project_inputs.py` | 331 | 11 | ok | ok | 1 | 84% | delete, overwrite |
| `qa_bc7_pivot_audit.py` | 112 | 1 | ok | ok | 1 | 76% | – |
| `qa_native_pivot_provenance.py` | 64 | 1 | ok | ok | 1 | 51% | – |
| `qa_pivot_bc7_rehearsal.py` | 59 | 1 | ok | ok | 1 | 51% | – |
| `qa_release_preflight.py` | 49 | 1 | ok | ok | 1 | 85% | – |
| `qa_suite_build_history.py` | 67 | 2 | ok | ok | 1 | 89% | – |
| `qa_suite_build_readiness.py` | 55 | 2 | ok | ok | 1 | 39% | – |
| `qa_suite_command_search.py` | 133 | 4 | ok | n/a | 0 | 0% | – |
| `qa_suite_embedded.py` | 879 | 7 | ok | n/a | 2 | 0% | overwrite |
| `qa_suite_guided_home.py` | 118 | 3 | ok | n/a | 0 | 0% | – |
| `qa_suite_local_setup.py` | 47 | 2 | ok | ok | 1 | 68% | – |
| `sandbox_animation_panel.py` | 181 | 12 | ok | n/a | 1 | 84% | – |
| `sandbox_asset_preview.py` | 186 | 7 | ok | n/a | 1 | 94% | – |
| `sandbox_compact_layout.py` | 466 | 24 | ok | n/a | 1 | 95% | – |
| `sandbox_editor_panel.py` | 99 | 4 | ok | n/a | 0 | 95% | – |
| `sandbox_engine_assets.py` | 226 | 9 | ok | n/a | 4 | 92% | delete, overwrite |
| `sandbox_game_hud.py` | 412 | 16 | ok | n/a | 3 | 93% | – |
| `sandbox_gameplay_artwork.py` | 83 | 2 | ok | n/a | 2 | 98% | – |
| `sandbox_gameplay_context.py` | 139 | 4 | ok | n/a | 1 | 100% | – |
| `sandbox_gameplay_mode.py` | 1072 | 27 | ok | n/a | 1 | 82% | – |
| `sandbox_hud_chrome_geometry.py` | 60 | 4 | ok | n/a | 3 | 100% | – |
| `sandbox_hud_original_art.py` | 497 | 22 | ok | n/a | 6 | 49% | – |
| `sandbox_legacy_v1_dialog.py` | 226 | 9 | ok | n/a | 0 | 93% | – |
| `sandbox_native_canvas.py` | 1062 | 68 | ok | n/a | 8 | 83% | overwrite |
| `sandbox_native_hud_crop_provider.py` | 113 | 5 | ok | n/a | 2 | 82% | – |
| `sandbox_native_panel.py` | 415 | 20 | ok | n/a | 2 | 94% | – |
| `sandbox_pixel_editor.py` | 362 | 23 | ok | n/a | 5 | 91% | delete, overwrite |
| `sandbox_png_export.py` | 81 | 3 | ok | n/a | 2 | 88% | delete, overwrite |
| `sandbox_qt_locale.py` | 309 | 13 | ok | n/a | 1 | 95% | – |
| `sandbox_reference_compare.py` | 179 | 8 | ok | n/a | 1 | 79% | overwrite |
| `sandbox_runtime_renderer.py` | 295 | 14 | ok | n/a | 3 | 81% | overwrite |
| `sandbox_scribe_reference.py` | 121 | 6 | ok | n/a | 2 | 88% | download |
| `sandbox_sprite_palette.py` | 120 | 5 | ok | n/a | 1 | 91% | – |
| `sandbox_studio.py` | 1806 | 86 | ok | ok | 24 | 76% | overwrite, code_eval |
| `sandbox_suite_embed.py` | 403 | 23 | ok | n/a | 6 | 40% | – |
| `sandbox_test_board.py` | 524 | 36 | ok | n/a | 4 | 79% | – |
| `sandkasten.py` | 919 | 40 | ok | ok | 6 | 26% | overwrite |
| `se_asset_package.py` | 314 | 9 | ok | ok | 8 | 76% | delete, overwrite |
| `se_atlas.py` | 169 | 9 | ok | ok | 1 | 0% | subprocess, overwrite |
| `show_installed.py` | 120 | 2 | ok | ok | 0 | 0% | – |
| `silhouette.py` | 416 | 10 | ok | ok | 0 | 0% | overwrite |
| `slot_blank.py` | 174 | 5 | ok | ok | 0 | 0% | delete, overwrite |
| `sprites.py` | 1801 | 25 | ok | ok | 13 | 0% | delete, overwrite |
| `stone_recolour.py` | 211 | 4 | ok | ok | 0 | 0% | overwrite |
| `suite_bridge.py` | 88 | 1 | ok | ok | 2 | 59% | subprocess, download |
| `suite_catalog.py` | 145 | 10 | ok | n/a | 0 | 49% | – |
| `suite_command_search.py` | 308 | 15 | ok | n/a | 1 | 94% | – |
| `suite_hud_menu_editor.py` | 418 | 25 | ok | n/a | 2 | 56% | overwrite |
| `suite_hud_menu_layout_editor.py` | 1418 | 73 | ok | n/a | 2 | 79% | delete, overwrite |
| `suite_hud_menu_noesis_dialog.py` | 373 | 13 | ok | n/a | 1 | 84% | – |
| `suite_hud_menu_session.py` | 124 | 4 | ok | n/a | 5 | 88% | delete, overwrite |
| `suite_hud_menu_workshop.py` | 887 | 39 | ok | n/a | 3 | 73% | overwrite |
| `suite_layout_flow.py` | 51 | 1 | ok | n/a | 1 | 100% | – |
| `suite_modern_shell.py` | 305 | 13 | ok | n/a | 0 | 95% | – |
| `suite_origins_grafikdaten.py` | 313 | 18 | ok | n/a | 0 | 66% | – |
| `suite_sh1_hud_core.py` | 170 | 6 | ok | n/a | 3 | 84% | delete, overwrite |
| `suite_sh1_hud_editor.py` | 391 | 23 | ok | n/a | 3 | 70% | delete, overwrite |
| `suite_sh1_hud_studio.py` | 637 | 29 | ok | n/a | 0 | 33% | delete, overwrite |
| `suite_sh1_origins_palette.py` | 107 | 2 | ok | n/a | 1 | 100% | – |
| `suite_start.py` | 166 | 4 | ok | n/a | 3 | 39% | subprocess, overwrite |
| `suite_ui_atlas_preview.py` | 226 | 5 | ok | n/a | 3 | 82% | – |
| `suite_usability.py` | 200 | 12 | ok | n/a | 1 | 81% | – |
| `suite_windows_paths.py` | 39 | 2 | ok | n/a | 0 | 96% | – |
| `suite_workflow.py` | 93 | 3 | ok | ok | 4 | 92% | subprocess |
| `target_selection_guard.py` | 184 | 6 | ok | n/a | 3 | 81% | – |
| `tile_objects.py` | 380 | 14 | ok | ok | 1 | 0% | – |
| `ui_ablage_loesen.py` | 143 | 3 | ok | ok | 0 | 0% | delete, overwrite |
| `ui_apply.py` | 519 | 7 | ok | ok | 2 | 42% | overwrite |
| `ui_atlas.py` | 1186 | 25 | ok | ok | 3 | 58% | delete, overwrite, download |
| `ui_atlas_layout_port.py` | 351 | 15 | ok | ok | 0 | 0% | delete, overwrite |
| `ui_button_bauen_a.py` | 212 | 8 | ok | n/a | 0 | 0% | overwrite |
| `ui_button_bauen_s.py` | 352 | 11 | ok | n/a | 0 | 0% | overwrite |
| `ui_button_catalogue.py` | 139 | 3 | ok | n/a | 0 | 0% | overwrite |
| `ui_button_motive.py` | 166 | 1 | ok | n/a | 0 | 0% | – |
| `ui_button_rahmen.py` | 287 | 11 | ok | n/a | 0 | 0% | overwrite |
| `ui_button_traeger_ernten.py` | 228 | 7 | ok | n/a | 0 | 0% | overwrite |
| `ui_button_zeichen.py` | 161 | 4 | ok | n/a | 0 | 0% | overwrite |
| `ui_button_zeichen_farbe.py` | 149 | 5 | ok | n/a | 0 | 0% | overwrite |
| `ui_einpflegen.py` | 285 | 6 | ok | ok | 2 | 55% | overwrite |
| `ui_extra_atlas.py` | 720 | 22 | ok | ok | 1 | 77% | delete, overwrite, download |
| `ui_extra_atlas_gui.py` | 247 | 16 | ok | n/a | 0 | 0% | – |
| `ui_gold_lernen.py` | 224 | 8 | ok | n/a | 0 | 0% | – |
| `ui_nordlicht.py` | 205 | 18 | ok | n/a | 0 | 0% | – |
| `ui_pair.py` | 552 | 12 | ok | ok | 2 | 11% | overwrite |
| `ui_rahmen.py` | 182 | 4 | ok | ok | 1 | 16% | overwrite |
| `ui_sh1_dict.py` | 283 | 6 | ok | ok | 1 | 19% | – |
| `ui_sh1_extract.py` | 194 | 4 | ok | ok | 1 | 23% | overwrite |
| `ui_sh1_hud.py` | 383 | 14 | ok | ok | 9 | 80% | delete, overwrite |
| `ui_sh1_to_shcde_bridge.py` | 610 | 19 | ok | ok | 1 | 60% | delete, overwrite |
| `ui_sh1_to_shcde_gui.py` | 374 | 26 | ok | n/a | 0 | 0% | – |
| `ui_sh1_umstellung.py` | 889 | 24 | ok | ok | 1 | 12% | overwrite |
| `ui_sh1_unity_patch.py` | 487 | 10 | ok | ok | 3 | 58% | delete, overwrite |
| `ui_vorlage.py` | 401 | 8 | ok | ok | 1 | 13% | overwrite |
| `unit_pipeline.py` | 127 | 3 | ok | ok | 0 | 0% | – |
| `vegetation_gen.py` | 789 | 21 | ok | ok | 1 | 34% | delete, overwrite |
| `ziel_se211.py` | 560 | 26 | ok | ok | 4 | 49% | subprocess, delete, overwrite |

## Testfall-Provenienz

- `all-tests-junit.xml`: vollständiger Ausgangslauf.
- `fixed-tests-junit.xml`: vollständiger Lauf nach Reparaturen.
- `inventory.json`: Modul- und Funktionsinventar mit Testreferenzen.
- `import-smoke.json`: 145 getrennte Import-Tests.
- `cli-help.json`: 77 Hilfeaufrufe und nicht anwendbare Module.
- `coverage-fixed.json`: gemessene Testabdeckung.

## Hinweise zur Weiterarbeit

Das **Windows-Portable-Release darf erst nach erfolgreicher neuer CI**, Prüfsumme des Installerpakets und manueller Abnahme als aktualisiert bezeichnet werden. Bis dahin die vorherige Installation und den gesamten `work/`-Ordner als unveränderte Sicherung aufbewahren.

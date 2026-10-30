# SpriteSuite – vertiefte Prüfung der Spezialwerkzeuge

**Stand:** 30. Oktober 2026. **Status:** lokal geprüft; neue Korrekturen noch nicht auf GitHub veröffentlicht.

## Belastbare Testergebnisse

| Prüfverfahren | Ergebnis | Aussage |
|---|---:|---|
| Vollständige Windows/Python-3.14-Testsammlung | **1331 bestanden / 0 fehlgeschlagen / 33 übersprungen** | 1364 Fälle gesammelt |
| Erfasste Werkzeugmodule | 145 | Direkte Python-Module im Ordner `tools/` |
| Erfasste Funktionen und Methoden | 1684 | Statische Zählung, keine Einzelfunktionsabnahme |
| Python-Testdateien | 125 | Enthält neue Regressionstests |
| Modul-Importe, isolierte Python-Prozesse | 145/145 bestanden | Verarbeitet keine Benutzergrafiken |
| Kommandozeilenhilfe | 77/77 bestanden | 68 Module ohne passendes CLI-Testprofil |
| Direkte Modulreferenz in Tests | 90/145 | Statischer Testbezug, kein Funktionstest-Nachweis |
| Ohne direkte Modulreferenz in Tests | 55 | Weitere fachliche Vertiefung erforderlich |
| Gemessene Zeilenabdeckung über Quellbereiche | **40.39 %** | Bezieht auch historisches, nur isoliert gestartetes Programm ein |

Die vollständige Testsammlung benutzt künstliche Testprojekte und bei Bedarf
einzelne bereits vorhandene lokale Originalreferenzen. Die übersprungenen
Tests benötigen zusätzliche private Originaldaten und dürfen nicht als
bestanden interpretiert werden.

## Neue Fehler und Korrekturen

### 1. Umzug veränderter UI-Atlas-Ausschnitte

Das zuvor nicht direkt getestete `ui_atlas_layout_port.py` schrieb
geänderte PNG-Ausschnitte nacheinander in den Zielexport. Fiel ein zweiter
Schreibvorgang oder die Berichtserstellung aus, blieben gemischte Versionen
bestehen. Dies wurde zunächst reproduziert und dann wie folgt abgesichert:

- Alle neuen PNGs und der Bericht werden zuerst in einem temporären Ordner vorbereitet.
- Vor dem Austausch werden Originaldateien gesichert und erneut geprüft.
- Fehlgeschlagene Veröffentlichungen lösen eine bytegenaue Wiederherstellung aus.
- Reservierte Windows-Namen, doppelte Zielordner und ungültige JSON-Dimensionen werden abgewiesen.
- Identische Quell- und Zielexporte werden ausdrücklich verweigert.
- Externe Änderungen vor der Veröffentlichung werden erkannt und nicht still überschrieben.

Diese Rücknahme hilft bei regulären Python- und Datenträgerfehlern.
Ein plötzlicher Stromausfall zwischen einzelnen Dateiaustauschen ist
**nicht** als vollständig atomare Transaktion nachgewiesen.

### 2. Hintergrundkarten und Missionsfamilien

Das zuvor nur oberflächlich geprüfte `background_v2_pipeline.py` erzeugte
Teilergebnisse, wenn eine späte Quelle fehlte oder beschädigt war.
Jetzt werden **alle 13 Gefechts- und alle 49 Missionsoriginale** vor dem
ersten Ausgabeschritt auf regulären PNG-Aufbau geprüft.
Zusätzlich müssen die sieben Grafiken einer Missionsfamilie gleiche
Abmessungen besitzen. Fehler während eines späteren Ausgabevorgangs
können dennoch Teilresultate verursachen; vollständige Ausgabe-
Transaktionen sind für diese Werkzeuge nicht nachgewiesen.

### 3. UI-Button-Motivkatalog

Der zuvor nicht direkt getestete `ui_button_catalogue.py` wurde
mit synthetischen PNG-Dateien durchgehend getestet:
Farbumschläge bei gleichem Motiv, Erkennung verschiedener Umrisse,
Sortierung benachbarter Familien, Kontaktbogen, deterministische
JSON-Ausgabe und Verweigerung korrupter Quelldateien.
Dabei war keine Programmkorrektur erforderlich.

## Pro Modul – Abdeckung und Funktionsnachweis

Ein Import- oder Hilfe-Test allein beweist weder die Vollständigkeit
der Bildverarbeitung noch sichere Installation oder echte Bedienbarkeit.
Die folgende Matrix macht die automatische Abdeckung für alle 145
Werkzeugmodule einzeln prüfbar.

| Modul | LOC | Funktionen | Import | Hilfe | Testbezüge | Zeilenabdeckung |
|---|---:|---:|---|---|---:|---:|
| `asset_katalog.py` | 1056 | 55 | passed | bestanden | 2 | 25 % |
| `atlas_contract_gui.py` | 7 | 0 | passed | n/a | 0 | 0 % |
| `background_review.py` | 208 | 8 | passed | bestanden | 0 | 0 % |
| `background_v2_audit.py` | 213 | 10 | passed | bestanden | 0 | 0 % |
| `background_v2_inner_blend.py` | 89 | 2 | passed | bestanden | 0 | 0 % |
| `background_v2_manual_mask.py` | 116 | 3 | passed | bestanden | 0 | 0 % |
| `background_v2_masked_edit.py` | 270 | 9 | passed | bestanden | 0 | 0 % |
| `background_v2_pipeline.py` | 273 | 13 | passed | bestanden | 1 | 56 % |
| `background_v2_pointed_window.py` | 181 | 4 | passed | bestanden | 0 | 0 % |
| `background_v2_refine_mask.py` | 103 | 3 | passed | bestanden | 0 | 0 % |
| `backgrounds.py` | 393 | 13 | passed | bestanden | 1 | 0 % |
| `boar_recolour.py` | 231 | 5 | passed | bestanden | 0 | 0 % |
| `build_locale.py` | 317 | 8 | passed | bestanden | 0 | 0 % |
| `build_portable_windows.py` | 230 | 6 | passed | bestanden | 1 | 22 % |
| `build_ui_bc7_cache.py` | 117 | 2 | passed | bestanden | 0 | 0 % |
| `check_stale_artifacts.py` | 90 | 2 | passed | bestanden | 0 | 0 % |
| `community_mod_compat.py` | 347 | 8 | passed | bestanden | 1 | 73 % |
| `compose_runtime_refresh.py` | 327 | 6 | passed | bestanden | 0 | 0 % |
| `compose_ui_bc7_candidate.py` | 84 | 1 | passed | bestanden | 0 | 0 % |
| `cross_match.py` | 153 | 4 | passed | bestanden | 0 | 0 % |
| `deorientalise.py` | 312 | 6 | passed | bestanden | 0 | 0 % |
| `editor_bruecke.py` | 295 | 12 | passed | bestanden | 1 | 0 % |
| `europeanize_backgrounds.py` | 208 | 10 | passed | bestanden | 0 | 0 % |
| `fortification_visual_recipes.py` | 189 | 6 | passed | bestanden | 0 | 0 % |
| `generate_ui_texture_source_manifest.py` | 193 | 4 | passed | bestanden | 0 | 0 % |
| `grafik_analyse.py` | 303 | 14 | passed | bestanden | 0 | 0 % |
| `grafik_diagnose.py` | 419 | 14 | passed | bestanden | 0 | 0 % |
| `groups.py` | 448 | 13 | passed | bestanden | 10 | 0 % |
| `hole_blatt.py` | 48 | 1 | passed | n/a | 0 | 0 % |
| `hud_buildings.py` | 113 | 6 | passed | bestanden | 1 | 81 % |
| `hud_menu_layout.py` | 806 | 43 | passed | n/a | 7 | 88 % |
| `hud_menu_metadata_paths.py` | 119 | 3 | passed | n/a | 1 | 85 % |
| `hud_menu_noesis_integration.py` | 464 | 19 | passed | bestanden | 2 | 78 % |
| `hud_menu_noesis_qa.py` | 196 | 9 | passed | n/a | 2 | 76 % |
| `hud_menu_project_transfer.py` | 415 | 12 | passed | n/a | 2 | 83 % |
| `hud_menu_workspace.py` | 395 | 18 | passed | n/a | 9 | 85 % |
| `hud_tree.py` | 97 | 4 | passed | bestanden | 1 | 74 % |
| `kachelraster_gm1.py` | 76 | 2 | passed | bestanden | 0 | 0 % |
| `locale_text.py` | 270 | 8 | passed | bestanden | 0 | 0 % |
| `locate_unit.py` | 175 | 4 | passed | bestanden | 0 | 0 % |
| `make_reference_root.py` | 104 | 3 | passed | bestanden | 0 | 0 % |
| `modding_host.py` | 249 | 9 | passed | n/a | 0 | 0 % |
| `native_geometry_probe.py` | 157 | 3 | passed | bestanden | 0 | 0 % |
| `origins_grafikdaten.py` | 391 | 11 | passed | bestanden | 2 | 71 % |
| `pin_digests.py` | 450 | 10 | passed | bestanden | 1 | 0 % |
| `pin_xaml.py` | 72 | 1 | passed | bestanden | 0 | 0 % |
| `pivot_bc7_stage.py` | 71 | 1 | passed | bestanden | 1 | 82 % |
| `pivot_native_proof_rows.py` | 118 | 2 | passed | n/a | 1 | 94 % |
| `pivot_review_gui.py` | 432 | 18 | passed | n/a | 3 | 86 % |
| `project_inputs.py` | 331 | 11 | passed | bestanden | 1 | 84 % |
| `qa_bc7_pivot_audit.py` | 112 | 1 | passed | bestanden | 1 | 76 % |
| `qa_native_pivot_provenance.py` | 64 | 1 | passed | bestanden | 1 | 51 % |
| `qa_pivot_bc7_rehearsal.py` | 59 | 1 | passed | bestanden | 1 | 51 % |
| `qa_release_preflight.py` | 49 | 1 | passed | bestanden | 1 | 85 % |
| `qa_suite_build_history.py` | 67 | 2 | passed | bestanden | 1 | 89 % |
| `qa_suite_build_readiness.py` | 55 | 2 | passed | bestanden | 1 | 39 % |
| `qa_suite_command_search.py` | 133 | 4 | passed | n/a | 0 | 0 % |
| `qa_suite_embedded.py` | 879 | 7 | passed | n/a | 2 | 0 % |
| `qa_suite_guided_home.py` | 118 | 3 | passed | n/a | 0 | 0 % |
| `qa_suite_local_setup.py` | 47 | 2 | passed | bestanden | 1 | 68 % |
| `sandbox_animation_panel.py` | 181 | 12 | passed | n/a | 1 | 84 % |
| `sandbox_asset_preview.py` | 186 | 7 | passed | n/a | 1 | 94 % |
| `sandbox_compact_layout.py` | 466 | 24 | passed | n/a | 1 | 95 % |
| `sandbox_editor_panel.py` | 99 | 4 | passed | n/a | 0 | 95 % |
| `sandbox_engine_assets.py` | 226 | 9 | passed | n/a | 4 | 92 % |
| `sandbox_game_hud.py` | 412 | 16 | passed | n/a | 3 | 93 % |
| `sandbox_gameplay_artwork.py` | 83 | 2 | passed | n/a | 2 | 98 % |
| `sandbox_gameplay_context.py` | 139 | 4 | passed | n/a | 1 | 100 % |
| `sandbox_gameplay_mode.py` | 1072 | 27 | passed | n/a | 1 | 82 % |
| `sandbox_hud_chrome_geometry.py` | 60 | 4 | passed | n/a | 3 | 100 % |
| `sandbox_hud_original_art.py` | 497 | 22 | passed | n/a | 6 | 49 % |
| `sandbox_legacy_v1_dialog.py` | 226 | 9 | passed | n/a | 0 | 93 % |
| `sandbox_native_canvas.py` | 1062 | 68 | passed | n/a | 8 | 83 % |
| `sandbox_native_hud_crop_provider.py` | 113 | 5 | passed | n/a | 2 | 82 % |
| `sandbox_native_panel.py` | 415 | 20 | passed | n/a | 2 | 94 % |
| `sandbox_pixel_editor.py` | 362 | 23 | passed | n/a | 5 | 91 % |
| `sandbox_png_export.py` | 81 | 3 | passed | n/a | 2 | 88 % |
| `sandbox_qt_locale.py` | 309 | 13 | passed | n/a | 1 | 95 % |
| `sandbox_reference_compare.py` | 179 | 8 | passed | n/a | 1 | 79 % |
| `sandbox_runtime_renderer.py` | 295 | 14 | passed | n/a | 3 | 81 % |
| `sandbox_scribe_reference.py` | 121 | 6 | passed | n/a | 2 | 88 % |
| `sandbox_sprite_palette.py` | 120 | 5 | passed | n/a | 1 | 91 % |
| `sandbox_studio.py` | 1806 | 86 | passed | bestanden | 24 | 76 % |
| `sandbox_suite_embed.py` | 403 | 23 | passed | n/a | 6 | 40 % |
| `sandbox_test_board.py` | 524 | 36 | passed | n/a | 4 | 79 % |
| `sandkasten.py` | 919 | 40 | passed | bestanden | 6 | 26 % |
| `se_asset_package.py` | 314 | 9 | passed | bestanden | 8 | 76 % |
| `se_atlas.py` | 169 | 9 | passed | bestanden | 1 | 0 % |
| `show_installed.py` | 120 | 2 | passed | bestanden | 0 | 0 % |
| `silhouette.py` | 416 | 10 | passed | bestanden | 0 | 0 % |
| `slot_blank.py` | 174 | 5 | passed | bestanden | 0 | 0 % |
| `sprites.py` | 1801 | 25 | passed | bestanden | 13 | 0 % |
| `stone_recolour.py` | 211 | 4 | passed | bestanden | 0 | 0 % |
| `suite_bridge.py` | 88 | 1 | passed | bestanden | 2 | 59 % |
| `suite_catalog.py` | 145 | 10 | passed | n/a | 0 | 49 % |
| `suite_command_search.py` | 308 | 15 | passed | n/a | 1 | 94 % |
| `suite_hud_menu_editor.py` | 418 | 25 | passed | n/a | 2 | 56 % |
| `suite_hud_menu_layout_editor.py` | 1418 | 73 | passed | n/a | 2 | 78 % |
| `suite_hud_menu_noesis_dialog.py` | 373 | 13 | passed | n/a | 1 | 84 % |
| `suite_hud_menu_session.py` | 124 | 4 | passed | n/a | 5 | 88 % |
| `suite_hud_menu_workshop.py` | 887 | 39 | passed | n/a | 3 | 73 % |
| `suite_layout_flow.py` | 51 | 1 | passed | n/a | 1 | 100 % |
| `suite_modern_shell.py` | 305 | 13 | passed | n/a | 0 | 95 % |
| `suite_origins_grafikdaten.py` | 313 | 18 | passed | n/a | 0 | 66 % |
| `suite_sh1_hud_core.py` | 170 | 6 | passed | n/a | 3 | 84 % |
| `suite_sh1_hud_editor.py` | 391 | 23 | passed | n/a | 3 | 70 % |
| `suite_sh1_hud_studio.py` | 637 | 29 | passed | n/a | 0 | 33 % |
| `suite_sh1_origins_palette.py` | 107 | 2 | passed | n/a | 1 | 100 % |
| `suite_start.py` | 166 | 4 | passed | n/a | 3 | 39 % |
| `suite_ui_atlas_preview.py` | 226 | 5 | passed | n/a | 3 | 82 % |
| `suite_usability.py` | 200 | 12 | passed | n/a | 1 | 81 % |
| `suite_windows_paths.py` | 39 | 2 | passed | n/a | 0 | 96 % |
| `suite_workflow.py` | 93 | 3 | passed | bestanden | 4 | 92 % |
| `target_selection_guard.py` | 184 | 6 | passed | n/a | 3 | 81 % |
| `tile_objects.py` | 380 | 14 | passed | bestanden | 1 | 0 % |
| `ui_ablage_loesen.py` | 143 | 3 | passed | bestanden | 0 | 0 % |
| `ui_apply.py` | 519 | 7 | passed | bestanden | 2 | 42 % |
| `ui_atlas.py` | 1186 | 25 | passed | bestanden | 3 | 58 % |
| `ui_atlas_layout_port.py` | 479 | 17 | passed | bestanden | 1 | 76 % |
| `ui_button_bauen_a.py` | 212 | 8 | passed | n/a | 0 | 0 % |
| `ui_button_bauen_s.py` | 352 | 11 | passed | n/a | 0 | 0 % |
| `ui_button_catalogue.py` | 139 | 3 | passed | n/a | 1 | 97 % |
| `ui_button_motive.py` | 166 | 1 | passed | n/a | 0 | 0 % |
| `ui_button_rahmen.py` | 287 | 11 | passed | n/a | 0 | 0 % |
| `ui_button_traeger_ernten.py` | 228 | 7 | passed | n/a | 0 | 0 % |
| `ui_button_zeichen.py` | 161 | 4 | passed | n/a | 0 | 0 % |
| `ui_button_zeichen_farbe.py` | 149 | 5 | passed | n/a | 0 | 0 % |
| `ui_einpflegen.py` | 285 | 6 | passed | bestanden | 2 | 55 % |
| `ui_extra_atlas.py` | 720 | 22 | passed | bestanden | 1 | 77 % |
| `ui_extra_atlas_gui.py` | 247 | 16 | passed | n/a | 0 | 0 % |
| `ui_gold_lernen.py` | 224 | 8 | passed | n/a | 0 | 0 % |
| `ui_nordlicht.py` | 205 | 18 | passed | n/a | 0 | 0 % |
| `ui_pair.py` | 552 | 12 | passed | bestanden | 2 | 11 % |
| `ui_rahmen.py` | 182 | 4 | passed | bestanden | 1 | 16 % |
| `ui_sh1_dict.py` | 283 | 6 | passed | bestanden | 1 | 19 % |
| `ui_sh1_extract.py` | 194 | 4 | passed | bestanden | 1 | 23 % |
| `ui_sh1_hud.py` | 383 | 14 | passed | bestanden | 9 | 80 % |
| `ui_sh1_to_shcde_bridge.py` | 610 | 19 | passed | bestanden | 1 | 60 % |
| `ui_sh1_to_shcde_gui.py` | 374 | 26 | passed | n/a | 0 | 0 % |
| `ui_sh1_umstellung.py` | 889 | 24 | passed | bestanden | 1 | 12 % |
| `ui_sh1_unity_patch.py` | 487 | 10 | passed | bestanden | 3 | 58 % |
| `ui_vorlage.py` | 401 | 8 | passed | bestanden | 1 | 13 % |
| `unit_pipeline.py` | 127 | 3 | passed | bestanden | 0 | 0 % |
| `vegetation_gen.py` | 789 | 21 | passed | bestanden | 1 | 34 % |
| `ziel_se211.py` | 560 | 26 | passed | bestanden | 4 | 49 % |

## Nachweise und Grenzen

Das lokale Nachweisarchiv enthält den vollständigen JUnit-Bericht,
den Coverage-JSON-Bericht, die Modulmatrix, die 145 einzelnen Import-
Ergebnisse und 77 CLI-Hilfe-Ergebnisse.
Echte Ingame-Interaktion, vollständige Noesis-Buttons, unabhängiger
zweiter Windows-PC, der vollständige Python-3.13-CI-Lauf und die
33 übersprungenen privaten Referenzprüfungen sind **nicht** erledigt.

Das neue Windows-Portable-Release darf erst nach erfolgreicher
Veröffentlichung und eigenständiger Installations-/Spieleprüfung
als aktualisiert bezeichnet werden. Die vorhandene Installation
und den gesamten Benutzerdatenordner `work/` unangetastet lassen.

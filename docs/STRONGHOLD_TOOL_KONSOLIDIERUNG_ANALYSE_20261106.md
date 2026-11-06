# Stronghold/SpriteSuite – vollständiger Abgleich der erschlossenen Tool-Quellbäume
Stand: 06.11.2026. Zweck: belastbare Entscheidung über Integration, NICHT automatische Bereinigung.
Basis: E:\SpriteSuite_PythonLatestCompat_20261105, Git dffce3f, eigener isolierter Worktree.

## Umfang und Erhebungsverfahren
- Ausschließlich Stronghold, Stronghold Europe/Origins, SpriteSuite und historische QA-/Codex-/Claude-Entwicklungsstände. Andere Anwendungen bleiben unberührt.
- 104 Hauptordner unter E:\ gesichtet; gezielt 23 Stronghold-Quellbäume mit eigenem tools/-Verzeichnis durch Dateinamen, Byte-SHA-256 und Existenz verglichen. Zusätzlich wurden historische Übergabe-/QA-Bäume, die Codex-Arbeitsablage und Claude-Projektmetadaten gesichtet. Claude-/Codex-Sitzungsprotokolle sind keine automatisch integrierbaren ausführbaren Tools.
- Es wurden keine fremden Skripte für die Bestandsaufnahme importiert oder gestartet. Ein gleicher Dateiname ist keine Funktionsidentität, ein gleicher SHA-256-Inhalt dagegen byteidentisch. Versionsbezogene Spiel- und Runtime-Prüfungen wurden nicht durch einen aktuellen Ingame-Test ersetzt.
- Nicht als unabhängige Programme gezählt: Release-ZIPs, Portable-Entpackungen, Browserprofile, interne Python-Module ohne separaten Einstieg, DLLs, Binärtools und wiederherstellbare Caches. Diese verbleiben als Referenz oder Laufzeitartefakt erhalten.

## Vergleich der 23 Tools-Quellbäume
Spalten: Dateien; byteidentisch mit aktueller Python-3.15-Basis; gleicher Name, abweichende Bytes; nur im historischen Baum.
| Quelle relativ zu E:\ | Dateien | Identisch | Abweichend | Alt-exklusiv |
|---|---:|---:|---:|---:|
| SpriteSuite_PythonLatestCompat_20261105 | 205 | 205 | 0 | 0 |
| SpriteSuite_TileOverlap_20261106 | 205 | 205 | 0 | 0 |
| SpriteSuite_GameLiveIntegration_20261105 | 204 | 197 | 6 | 1 |
| SpriteSuite_Handbook_20261104 | 204 | 195 | 8 | 1 |
| SpriteSuite_GuideCompatibility_20261104 | 203 | 196 | 7 | 0 |
| SpriteSuite_GuideCompatibility_Reaudit_20261104 | 203 | 197 | 6 | 0 |
| SpriteSuite_UX_MinutiösQA_20261104 | 199 | 193 | 6 | 0 |
| SpriteSuite_UX_Rebuild_20261104 | 198 | 190 | 8 | 0 |
| SpriteSuite_Integrated_20261104 | 197 | 190 | 7 | 0 |
| SpriteSuite_ReleaseCandidate_20261104_Reviewed | 197 | 190 | 7 | 0 |
| SpriteSuite_Origins_Manuell_20261101 | 191 | 182 | 9 | 0 |
| SpriteSuite_SteamCompatibility_20261101 | 167 | 154 | 13 | 0 |
| SpriteSuite_PrivateReferenceQA_20261101 | 161 | 148 | 13 | 0 |
| SpriteSuite | 138 | 112 | 26 | 0 |
| SU\projekt | 104 | 52 | 25 | 27 |
| GSX\sh1de-shcde-sprite-suite-main | 89 | 44 | 22 | 23 |
| SS111QA | 86 | 44 | 21 | 21 |
| SS110FinalQA | 85 | 44 | 21 | 20 |
| SS110QA | 85 | 44 | 21 | 20 |
| SS QA | 83 | 44 | 21 | 18 |
| SU_base | 82 | 39 | 22 | 21 |
| GS\StrongholdEurope-Projekt | 74 | 36 | 23 | 15 |
| GS\StrongholdOrigins-Projekt | 12 | 0 | 0 | 12 |

Querschnitt: 41 historische Tool-Dateinamen fehlen dem aktuellen 205-Dateien-Bestand. 62 Tool-Dateinamen kommen in mehreren, byteabweichenden Fassungen vor. Innerhalb der aktuellen 205 Dateien waren keine zwei Dateien unterschiedlicher Namen byteidentisch. Das ist kein Beweis für Abwesenheit semantischer Doppelarbeit.

## Fachlicher Funktions- und Integrationsbefund
| Funktionsfamilie | Vorhandene Quelle / Einbindung | Entscheidung |
|---|---|---|
| Gemeinsames Mod-Projekt und HUD-Bearbeitung | tools/suite_unified_workflow.py, suite_unified_project.py, suite_hud_menu_workshop.py | Bereits integriert; keine zweite Zustandsmaschine oder Projektablage schaffen |
| Import, Bearbeitung, Raster und Rückimport | tools/sprites.py, tile_objects.py, kachelraster_gm1.py, src/.../tile_roundtrip.py, extras/sprite-editor | Bereits gemeinsam verwendete Format-/Kachelschnittstellen; Überlappungsänderungen nur separat nach isolierter Abnahme |
| SH1 HUD, Origins, Noesis, XAML | tools/ui_sh1_hud.py, suite_sh1_hud_studio.py, origins_grafikdaten.py, ui_sh1_unity_patch.py | Fachfunktionen bestehen, via vorhandene Werkstatt erreichbar; keine ungetestete Verschmelzung der Datenmodelle |
| Atlanten und BC7 | tools/se_atlas.py, ui_atlas.py, src/.../asset_stream_builder.py, unity_asset_bundle.py | Ziel- und Formatverträge unterscheiden; nur Übergabe und Navigation vereinheitlichen |
| Diagnose und Release | tools/grafik_diagnose.py, qa_release_preflight.py, qa_suite_build_readiness.py, src/.../release_preflight.py | Read-only-Prüfpfade beibehalten; niemals Bereitheit als Ingame-Freigabe deklarieren |
| Paketbau und Installation | tools/suite_workflow.py, ziel_se211.py, target_selection_guard.py | Paketbau/Validierung blockierend, Installationszugriff explizit und mit Sicherung; KEIN automatischer Übergang vom Prüfen zum Installieren |
| Laufzeit/Diplomatie/Native | E:\SU_base, runtime/*.cs, historische SE-1.44/2.11-Stände | ABI- und Threadaffinität versionsgebunden; keine automatische DLL-/Script-Extender-Fusion |
| Spezialprogramme | tools/suite_center.pyw und suite_catalog.py | Alle Python-Skripte wurden weitgehend anhand der Dateiendung angezeigt; sichere Auffindbarkeit muss von ausführbaren Fachwerkzeugen unterscheiden |
| Strg+K | tools/suite_command_search.py | Findet Arbeitsbereiche und einige Werkzeuge, wählt aber nicht gezielt die vielen CLI-Fachwerkzeuge im vorhandenen Werkzeugkatalog |
| Historische QA-Inventur | src/.../qa_inventory.py | Vergleicht nur zehn fest benannte Kandidaten; für Komplettvergleich durch allgemeine, lesende Toolmatrix ergänzen |

## Historisch nur zusätzlich vorhandene Werkzeuge – Risikogruppen
- Versions- und ABI-gebundene QA: ram_acceptance.py, full152_ingame_acceptance.py, native_selection_probe.py, native_crash_handler.py, reanchor_rvas.py, verify_cold_ab_bc7_v2.py, asset_stream_canary_ladder.py und weitere BC7-Hardpin-Helfer. Nicht als aktueller Beleg verwendbar.
- Installations- oder Spiellaufzeit-Schreiber: runtime_install.py, shcdese_install.py, shcdese_current_install.py, install_manifest_abgleichen.py, system_workflows.py, install-campaign.ps1, install-runtime-package.ps1. Nicht automatisch importieren, starten oder in eine Sammel-CLI einhängen.
- Alte Build-/SDK-Helfer: build_modding_exe.py, suite_sdk_check.py, suite_build_report.py, grosser_lauf.ps1, disassemblieren.ps1, verschiedene C#-Sonden. Erst getrennte Versions-/Funktionsprüfung.
- Origins-Karten-/Kampagnenwerkzeuge: scan-maps.py, check-start-keeps.py, build-ui-palette.py, make-trail.py, pack-mission.ps1. Potenziell nützlich; Karten-Eingaben, Pfade und Zielformat sind vor Portierung gesondert zu beweisen.
- Branch-spezifische Spezialprüfungen: suite_live_noesis_log_audit.py und verify_illustrated_manual.py. Keine doppelte dauerhafte Implementierung ohne nachgewiesenen Bedarf.

## Qualitäts- und Zustandsbefunde
1. Aktueller Referenzzweig PythonLatestCompat: HEAD dffce3f, keine getrackten Änderungen; Basis für isolierte Konsolidierungsarbeiten.
2. E:\SpriteSuite hat zahlreiche nicht eingecheckte Änderungen; E:\SU_base enthält umfangreiche geänderte/entfernte Dateien; E:\SpriteSuite_TileOverlap_20261106 hat 36 veränderte getrackte Dateien. Diese Arbeitsstände sind nicht zu ersetzen oder automatisch zu committen.
3. Node-Regressionen im TileOverlap-Zweig: 114 bestanden, 0 fehlgeschlagen. Python-Basistests für Navigation, Policy und Altinventur: 14 bestanden.
4. Im TileOverlap-Zweig meldete git diff --check bereits Whitespace an einem generierten Browser-Ergebnis-JSON. Das ist ein vorhandener Arbeitsstands-Befund, kein nachgewiesener Fehler der Tile-Algorithmen.
5. Der TileOverlap-Zweig und PythonLatestCompat sind bei allen 205 Tools byteidentisch, unterscheiden sich aber in der noch nicht eingecheckten HTML-Editor-Implementierung. Diese bleibt ausdrücklich außerhalb dieses Patches.
6. Verbleibende Unsicherheit: Native Ingame-Abnahme, Benutzeroberflächen-Sichtprüfung auf Zweitgerät und ausführbare Altwerkzeuge wurden nicht durch eine bloße SHA-Dateiinventur bestätigt.

## Entscheidungsmatrix für Zusammenlegung
**SOFORT sinnhaft:** eine einzige kuratierte, nur navigierende Fachwerkzeug-Registrierung für Strg+K und den bereits vorhandenen CLI-Katalog; allgemeine reproduzierbare, komplett lesende SHA-Werkzeugmatrix mit Funktions-/Risikometadaten.
**SPÄTER und separat:** ausgewählte native QA-Leser, Origins-Kartenanalyse, UI-BC7-Workflow, wenn versionierte Testfixtures, Spielversionen, Abnahme und Rückweg belegt sind.
**NICHT zusammenlegen:** echte Spielinstallation und Read-only-Diagnose; Alt-Runtime-Sonden und aktuelle Plugin-ABI; Alpha-/Tile-Datenmodelle ohne Roundtrip; bestehende unveröffentlichte Zweige; release-/installationsspezifische Hardpins.
**NICHT löschen:** historische Branches, unveröffentlichte Releases, Testprotokolle, Quellen und Backupstände aufgrund bloßer Namens- oder Byteähnlichkeit.

## Abgrenzung
Dies ist eine vollständige maschinelle NAMENS-/HASH-Inventur der 23 erschlossenen Stronghold-tools-Quellbäume und eine gezielte Prüfung der Integrationspfade, nicht die Behauptung eines formalen Vollbeweises sämtlicher Binärprogramme oder aller Altversionen. Die maschinenlesbare, alle gefundenen Dateien enthaltende Toolmatrix wird im isolierten Arbeitszweig erstellt und ist auditierbar.
# Gebäudeschaden – Fortsetzung und Live-QA vom 08.11.2026

**Abnahmestatus: TEILBESTANDEN. Keine Produktivfreigabe und keine vollständig bewiesene automatische Gebäudeschadensdarstellung.**

Dieser Bericht dokumentiert die wirklich ausgeführten Arbeiten und ihre offenen Sperren. Die getrennten alten Quell- und Releaseverzeichnisse wurden weder gelöscht noch überschrieben.

## Stand und Provenienz

- Neuer isolierter Quellzweig: `E:\SpriteSuite_DamageCompletionQA_20261108`, Branch `feature/damage-completion-qa-20261108`, Ausgangscommit `673eb09` aus `E:\SpriteSuite_UNIFIED_RELEASE_20261108`.
- Das zweite parallele Wiederherstellungsverzeichnis `E:\SpriteSuite_FinalUnified_20261108` hat weiterhin eigene uncommittete Änderungen und wurde **nicht** zusammengeführt; alte defekte Git-Worktree-Referenzen ebenfalls unverändert belassen.
- Originales Kornkammer-Referenzmanifest: `E:\SpriteSuite_FinalAudit_20261106\LiveGameQA\OriginalGranary_19_Provenance_20261107\original_sprite_reference.json`; SHA-256 `8d75ac8ddd1d0020af9212536aa922aecbc526b2730ede60eaa502efcb38a997`.
- Entwurfsmanifest: `E:\SpriteSuite_FinalAudit_20261106\LiveGameQA\Granary_19_Sequential_DamageDrafts_20261107\draft_pipeline_manifest.json`; SHA-256 `983f82f6d0cd315fac082d092030fb3fa2d91ca0fac693676b84862a00897dd3`.
- Korrekte Typen gemäß SHCDESE: `19=STRUCT_GRANARY` (Kornkammer), `104=STRUCT_POND` (Teich). Typ 104 ist nur historisches QA-Testobjekt und darf nicht als Kornkammer-Schadensreferenz gelten.
- Die acht mechanischen/Brand-Stufen sind Anfragen/Entwürfe: `modelGenerationExecuted=false`, `generatedDamageAssets=0`, `approvedDamageStages=0`. Ohne Bilder und Freigaben keine produktive Umschaltung.

## 16 Original-Slots

- Original-Grafikfamilie `tile_buildings2`, Bilder 278–293, zusammenhängendes 4×4-Raster. Aus den acht Montagehypothesen ist `xy-u-v` visuell plausibel, **nicht** im Spiel visuell bestätigt.
- Neuer, separat getesteter Generator `tools/building_damage_native_bindings.py` prüft SHA-gepinnte Originalquelle, alle 16 PNG-/RGBA-Hashes, Native-Pivots, Maße, PPU, Slot- und Raster-Eindeutigkeit sowie die ausdrücklich unfreigegebene Stufenliste.
- Lokaler Output: `work\granary_type19_16slots_unapproved_proposal.json`; SHA-256 `3274a3840769b0b23a285f170d3f0da76bc211b8e212b31be65e985052d68168`. Flags: `enabled=false`, `previewEnabled=false`, `mappingConfirmedInGame=false`, `approvedDamageStages=0`, `fullHpFireGameQaProved=false`.
- Es werden keine freigegebenen Modellbilder vorgetäuscht und keine fremden Originalpixel verändert.

## Abgesicherte Codeintegration

- Früher separat entwickelte HP-/Feuer-C#-Runtime, Werkzeuge und Regressionen wurden ausschließlich in den **neuen** Quellzweig kopiert, ältere Originalverzeichnisse und produktive Spielinstallationen blieben unberührt.
- Neue `tilemap_sprite`-Diagnostik des Readonly-Observers liest den tatsächlichen Unity-Tilemap-Sprite zusätzlich zur Feldreferenz (null- und fehlertolerant). Build gegen die reale SHCDESE-Spiel-ABI erfolgreich; nur Build, nicht installiert.
- Die alte HP-/Feuer-Runtime meldete bloße Feldzuweisungen als `renderer_modified=true`. Im neuen C#-Code bedeutet `stage_applied|sprite_field_written=true|renderer_modified=false` ausschließlich eine Feldzuweisung. Nur ein unabhängiges `tilemapRef.GetSprite()`-Readback darf `stage_tilemap_verified|tilemap_readback_matches=true|renderer_modified=true` melden.
- Neue QA-Auswertungen und Regressionstests verweigern eine visuelle Freigabe bei fehlendem, alten, gefälschtem oder räumlich anderem Tilemap-Readback. Die neue Runtime wurde erfolgreich, aber **ohne Spielinstallation**, kompiliert: DLL SHA-256 `1b09bc0259ec8d9e9065c107846ae4984e2a21fa701819b2c59cbc902ebf3775`.
- Auch `suite_tool_policy.py` und `suite_tool_registry.py` wurden im isolierten Branch um die tatsächlich vorhandenen HP-/Feuer-Spezialwerkzeuge ergänzt.

## Nachweise durch automatisierte Tests

- Original-Provenienz: **10/10 bestanden**. Nativer editierbarer Sprite-Roundtrip: **6/6 bestanden**. Sequenzielle Codex-/Freigabe-Regressionen: **11/11 bestanden**.
- Readonly-Live-QA-Logik: **10/10 bestanden**. Neue SHA-geprüfte native 16-Slot-Bindings: **6/6 bestanden**.
- **Abschließende Runtime-Suite: 88 Pytests und 7 Untertests bestanden**; inklusive neuer Negativtests gegen falsche Tilemap-Bestätigung. Separater GUI-Sandbox-Test mangels PySide6 übersprungen, keine GUI-Abnahme.
- C#-Readonly-Plugin gegen reale ABI nur gebaut: SHA-256 `b3859db5f8fe471e71dd6ad794ac3c8a00d2a46f2bdf447f61661656c8529146`; `gameModified=false`.

## Isolierter echter Spieltest: NICHT bestanden

- Eine neue 8025-Dateien-Kopie mit ca. 7,47 GiB unter `E:\SSLiveGame_DamageLifecycleQA_20261108` angelegt. Nur dort QA-HP/Feuer-Test-DLL und isolierter Profilmarker eingerichtet; keine Installation in Steam-Original oder Release.
- Game-Assembly SHA-256 `bc8b6a395f01d48557db413600c8dd8d1fdfd3abdf97bfbbb68a3c56b04fd789`; SHCDESE SHA-256 `5cb1c33be5463086505a17f5c48aaa357d733cfff7240e101c821f0e3c668498`; temporäre Test-DLL SHA-256 `b24b800cec8362fd0c010b9f3b9be6df90dcdd4e96c307d7b220c5a0f019c536`.
- Test-Save SHA-256 **vor und nach Spielende gleich**: `d29716f6fa72fc440607b3910f16eefb0abb8ee0743d060e3e93fd13f1fb24c7`. Die eigentliche Spielkopie wurde nach dem Test beendet.
- Der Test lud einen echten Spielstand und erfasste Typ-104-Teich mit HP100/100, Feuer 0. Er setzte über die native SHCDESE-API tatsächlich **HP60/100, Feuer0** bei `preview=False`, ohne den Save zu speichern.
- Die **alte** Renderer-Runtime meldete 64 `stage_applied`-Schreibzugriffe für `qa_mechanical75`, ohne echten Tilemap-Readback. Der unabhängige Testtreiber fand an seinen 36 Footprint-/Terrain-Renderzellen **0 passende Stage-Sprites**, brach die Mechanical-Phase mit `TimeoutException: phase_timeout` ab und ließ das Spiel beenden. Die Runtime protokollierte beim Shutdown 64 Feldwiederherstellungen.
- Das erzeugte `Baseline.png` ist intakt, zeigt bei manueller Sichtprüfung aber vorwiegend Logo und schwarzen Ladebildschirm, **kein sichtbar untersuchbares Gebäude**. SHA-256 `038db8a3d8718196765125a53c6848267247ea4189e7fa55b29b3fd2367226d1`.
- Live-Log SHA-256 `a67f7dad80fb33124725e323c3917078713413c67ff89d128195eb2e8a329ad9`. Audits: `work\lifecycle_qa_health_evidence_20261108.json` (`canarySequenceProved=false`), `work\lifecycle_qa_layer_evidence_20261108.json` und `work\lifecycle_hp_fire_logaudit_20261108.json` (`nativeTilemapReadbackProved=false`).
- Das Layer-Audit sah 240 grafische Zeichenevents, davon **108 außerhalb der Gameplay-Footprints**. Elf vollständige, unbestätigte grafische Raster und 88 mögliche Ausrichtungen bleiben. Terrain-/Footprint-Objekte sind nicht zwingend die SpriteMapping-Zeichenschicht; ein Feldschreibvorgang ist kein Sichtbarkeitsnachweis.
- Keine tatsächliche Brenn-/Reparatur-/Neuaufbau-/Reload-Sequenz erfolgreich bestätigt. Der Test blieb **rot**. Die nun härtete C#-Readback-Fassung war beim Spielversuch noch nicht installiert; ihr Build/Test ist nicht mit Live-Beweis gleichzusetzen.

## Historischer Preview-Test

- Historisches Log `E:\SSLiveGame_HPFire_QA_20261107\BepInEx\LogOutput.log`, SHA-256 `57ec6022cc47d79ee19ee41caf4ee0383e94537c0c8b9304dda9e4dd02baf164`, enthält **128 mechanisch/Brand/Wiederherstellungs-Feldzyklen** mit `preview=True` und **256 alte ungeprüfte Rendererbehauptungen**.
- Aktueller Prüfer schreibt `nativeTilemapReadbackProved=false` und `actualGameplayHpChangeProved=false`; Quellreport unter `work\legacy_hp_fire_logaudit_20261108.json`.

## Freigabesperren und nächste Schritte

1. Echte Gebäude-Zeichenschicht und ihre sprite-eigenen Tilemap-Pixel für Typ 19 anhand verifizierter `SpriteMapping`-Ereignisse erfassen; alle 16 Zellen, Originalpixel und `xy-u-v`-Slots **im sichtbaren Spiel** nachweisen.
2. Die acht Schadensbilder erst tatsächlich erzeugen, pixel-/maskengetreu prüfen und in der vorhandenen sequenziellen Freigabepipeline als echte Assets freigeben. Kein synthetischer Typwechsel und kein implizites Freigabeflag.
3. Mit diesen Assets den automatischen HP-Verlust, Brand, Löschen, Reparieren, Kartenreload und Neubau im isolierten QA-Spiel anhand tatsächlicher HP-/Feuerwerte, separatem Tilemap-Readback, sichtbaren Screenshots und unverändertem Test-Save überprüfen.
4. **Nur danach** die bestandenen Änderungen nach konfliktgeprüftem Abgleich in den Releasezweig übernehmen. Der hier dokumentierte getrennte Branch ist ein gesicherter Entwicklungsstand, **keine vollständige Produktfreigabe**.

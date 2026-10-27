# SHCDE-Community-Kompatibilität – SpriteSuite (Teilabnahme, KEINE Freigabe)

**Geprüft:** 22. Oktober 2026 · **Projekt:** `E:\SpriteSuite`, Branch `feature/sandbox-studio` · **bestehender Git-HEAD:** `00276ec`  
**Auftrag:** Alle benannten Rawra-, APIShared-, Ensrick-, Serpens- und AI-Toolkit-Projekte als aktuelle Kompatibilitätsreferenzen berücksichtigen, Konflikte vor Schreiboperationen erkennen und keine unbelegte Ingame-Parität behaupten.

## 1. Veröffentlichte Upstream-Versionen und Verträge

| Projekt | geprüfter Stand | belastbarer Vertrag / Risiko |
| --- | --- | --- |
| [Rawra – vorbereitetes BepInEx](https://gitlab.com/rawra-stronghold-crusader/shcde-bepinex/-/releases) | `v1.1.0`, 07.09.2026 | Vorbereiteter Windows-x64-BepInEx-Loader; nicht als eigenständiger Mod-Hook-Eigentümer betrachten. |
| [Rawra – Script Extender](https://gitlab.com/rawra-stronghold-crusader/shcde-script-extender/-/releases) | `v2.14.3`, 19.10.2026 | Plugin `000shcdese`; C#-/Lua-API, Asset API, Noesis, map archive, AIV/AIC. Native/PInvoke-Verträge sind versionsgebunden. |
| [Rawra – Fixes](https://gitlab.com/rawra-stronghold-crusader/shcde-fixes/-/releases) | `v1.29.0`, 22.10.2026 | Plugin-GUID `fixes`; harte BepInEx-Abhängigkeit auf `000shcdese`; optional aktivierte AI-, Pathfinder-, Einheit-, Bau- und Grafikfixes. |
| [APIShared](https://github.com/SHCDE-APIShared/APIShared/releases/tag/APIShared/v0.9.2) | `0.9.2`, 15.10.2026 | Plugin `APIShared_Serp`, DLL `APIShared.dll`, `net481`, mind. SE **2.14.0**; genau **eine** zentrale Installation, keine DLL-Kopie im Konsumenten. |
| [Ensrick – Crusader DE Tweaker](https://gitlab.com/ensrick7/crusader-de-tweaker/-/releases) | `v2.11.2`, 19.10.2026 | Plugin `CrusaderDETweaker`; Config unter `BepInEx/config/CrusaderDETweaker` bleibt Eigentum des Tweakers. |
| [Serpens – Mods](https://github.com/Serpens66/Stronghold-Crusader-DE-Mods/releases/tag/SerpsMods/v1.0.28) | `SerpsMods/v1.0.28`, 15.10.2026 | Mehrere unabhängig geladene Mods; GUIDs/Abhängigkeiten und Engine-Hook-Besitz müssen **je Plugin** getestet werden. |
| [Schlossgespensty – AI Toolkit](https://github.com/Schlossgespensty/AI-Toolkit/releases/tag/0.8.0) | `0.8.0`, 09.10.2026 | Klassisches Stronghold-Crusader/UCP-Electron-Tool; native **`.aiv`**-Dateien, `character.json`, `lines.json`. Kein belegter DE-`.aivjson`-Importer. Quellcode hat derzeit keine freigegebene allgemeine Repository-Lizenz. |

**Quelle wichtiger Invarianten:** [APIShared README](https://github.com/SHCDE-APIShared/APIShared/blob/main/README.md), [APIShared info.json](https://github.com/SHCDE-APIShared/APIShared/blob/main/info.json), [APIShared Architecture](https://github.com/SHCDE-APIShared/APIShared/blob/main/ARCHITECTURE.md), [Drittanbieter-Anleitung](https://github.com/SHCDE-APIShared/APIShared/blob/main/docs/THIRD_PARTY_GUIDE.md), [Tweaker Developer Notes](https://github.com/Ensrick/crusader-de-tweaker/blob/main/DEVELOPER_NOTES.md). Der APIShared-Quellstand kann der veröffentlichten DLL voraus sein; ein Quellbranch ist kein ersatzweise getestetes Releaseartefakt.

## 2. Serpens-Helfer: kein stilles Dateiformat-Crossmapping

| Werkzeug | tatsächlicher Vertrag | SpriteSuite-Folge |
| --- | --- | --- |
| [AIVParser](https://github.com/Serpens66/Stronghold-Crusader-DE-Mods/blob/main/Helpers/AIVParser/README.md) | DE-`.aivjson` lesen, 100×100 Burgkoordinaten, Keep-/Footprint-/Buildorder-Daten; klassisches `.aiv` und natives `.baiv` ausdrücklich nicht V1 | UI darf DE-AIVJSON nicht als klassisches AI-Toolkit-AIV öffnen/speichern; keine automatische Datenmigration. |
| [MapParser](https://github.com/Serpens66/Stronghold-Crusader-DE-Mods/blob/main/Helpers/MapParser/README.md) | `.map` und `.trail` read-only, PKWARE-DCL-Sektionen und CRC; **kein** direkter `.sav`/`.msv`-Parser | Originalkarten bleiben nur lesend; dieses API ersetzt weder SaveExtractor noch vollständige Spielsimulation. |
| [SaveExtractor](https://github.com/Serpens66/Stronghold-Crusader-DE-Mods/blob/main/Helpers/SaveExtractor/ANLEITUNG.txt) | `.sav` in neues `<Save-Name>.extracted` zerlegen, enthaltene Karte und aktive AIVs je CPU plus `mapping.md`; Quell-Save nicht verändert | Nur isolierte Exporte; keine Übergabe der `.sav` direkt an den MapParser. |
| [TrailEditor](https://github.com/Serpens66/Stronghold-Crusader-DE-Mods/blob/main/Helpers/TrailEditor/README.md) | `.trail` verlustfrei exportieren/repacken, gesonderte Ausgabe; aktueller Writer Restartformat **60**, Setupformat **-12** (SHCDE 2.8) | Bestehende Quellen nicht überschreiben; Formatversionen und Map-/AIV-Container getrennt prüfen. |
| [AtlasBuilder](https://github.com/Serpens66/Stronghold-Crusader-DE-Mods/blob/main/Helpers/AtlasBuilder/USAGE.md) | `Override/Atlas/<GM-Gruppe>/atlas.json` mit `atlas.png/.dds` und optional Maske; SE >=2.4, BC7-DDS >=2.8; Pivots, PPU, 4×4-Blöcke und Maskenregeln | **Nicht identisch** zu SpriteSuites Unity-AssetBundle-`.v1`/`.v2`-Paketen. Für Cross-Import wären explizite Konverter, Pixel-/Pivot-Vergleich und Tests nötig. |

## 3. Aktuelle SpriteSuite und reale QA-Installation

- SpriteSuite-Plugin: `strongholdeuropede.private`, Runtime-DLL `StrongholdEuropeDE.Runtime.dll`, eigener Ordner `BepInEx/plugins/StrongholdEuropeDE`. Kein mitgeliefertes APIShared-, BepInEx-, Script-Extender- oder Harmony-DLL-Duplikat im geprüften `dist/europe-production-bc7-v2`-Modpaket.
- `runtime/StrongholdEuropeDE.Runtime/StrongholdEuropeRuntimePlugin.cs` deklarierte `BepInDependency("000shcdese","2.0.0")` und optionale Fixes-Abhängigkeit. Eigene Harmony-/Low-Level-Laufzeitpatches sind vorhanden: keine nachgewiesene gemeinsame Hook-Reihenfolge mit Fixes/APIShared/Serpens/Tweaker.
- `config/runtime-prerequisites.json` pinnt für das bisherige eigene Runtime-Build exakt **SE 2.11.0**; der 2.14.3-Upstream-Release ersetzt diese ABI-Pins nicht von selbst.
- Vorhandene lesend untersuchte `E:\SSGameQA`: `BepInEx.dll` 5.4.23.5 hat den erwarteten Pin; `000shcdese` meldet **1.44.0** und verfehlt den **2.11.0**-Pin. Nur `000shcdese` und SpriteSuite-`strongholdeuropede.private` sind registriert. Keine gemeinsame APIShared-/Tweaker-/Fixes-/Serpens-Laufzeit vorhanden.
- **Folge:** Diese QA-Kopie kann den aktuellen APIShared-0.9.2-Vertrag (SE >=2.14.0) nicht erfüllen. Ebenso ist eine aktuelle SpriteSuite-Runtime-Ingame-Freigabe mit ihrem SE1.44-Stand nicht belegt. Kein automatisches Update/Downgrade und kein neuer Build wurden ausgeführt.
- Rawra Fixes kann Sprite-Offsets/AI- und Bauverhalten beeinflussen, Tweaker verändert Spielstats/Kosten/Schaden. Scripting- und Sprite-Asset-Mods dürfen diese Werte nicht als statische Vanilla-Invarianten oder konfliktfreie Originalsimulation behaupten.
- APIShared verlangt zentrale Hook-Eigentümerschaft. Künftige eigenständige SpriteSuite-Events sollen APIShared-Kapazitäten verwenden, wo ihre **veröffentlichte** API und Laufzeitversion bestätigt sind, statt konkurrierende Native-Detours zu installieren.
- Tweaker: Load-Reihenfolge Game Defaults → TOML → CSV → dynamische Multiplikatoren; `-1` im Schadens-CSV bedeutet „überspringen“, `0` **schreibt Null**. Laufzeitschreibzugriffe erst nach Map-Start/-Load-Post, nicht während `LibraryLoaded`. Multiplayer-HostSync besitzt eigene Dateien; keine SpriteSuite-Konfigurationsüberschreibung.

## 4. Implementierte Sicherungen

1. `config/shcde-community-compat-20261022.json`: versionsgebundener Quell- und Formatsnapshot; nicht als unbefristete Versionsfreigabe.
2. `tools/community_mod_compat.py`: lesende `--game-root`-Prüfung (optional `--candidate`) auf Plugin-Manifest/GUID-Duplikate, SE-/BepInEx-Pins, APIShared-Mindestversion, Fremd-DLLs, fremde Ziel-Ordner und ungetestete Hook-Koexistenz. JSON nur unter `work/`.
3. `tools/ziel_se211.py`: Fremdmod-Ordner dürfen weder installiert/überschrieben noch entfernt oder über Sicherungen zurückgeschrieben werden; SpriteSuite-Installation nur nach unabhängiger Ziel- und Community-Sicherheitsprüfung **vor** Sicherung/Kopie. Die historische automatische SE-2.11-Installation ist für das verlangte APIShared-Ökosystem gesperrt.
4. `tests/sandbox/test_community_mod_compat.py`: negative Tests für APIShared-SE-Mismatch, doppelte GUIDs, verbotene Fremd-DLLs, alternative GUID-Besitzverhältnisse, Fixes-Koexistenz ohne Ingame-Proof, Install/Remove/Restore-Fail-Closed, reales lesendes QA-Ziel und Helper-Formatgrenzen.
5. Ursprüngliche AssetBundle- und Editorfunktionen bleiben erhalten. Fremde Upstream-Repositories werden weder geändert noch in die Suite kopiert.

## 5. Abnahmestatus und weitere Voraussetzungen

**REIN LESENDER QA-BERICHT:** `work/reports/ui-audit/shcde-community-compat-20261022.json`. Ergebnis **BLOCKED** (SHCDESE-DLL stimmt nicht mit der aktuell geprüften SpriteSuite-ABI überein). Keine Spielmodifikation.

**Die gesamte gewünschte gemeinsame Mod-Konfiguration ist NICHT FREIGEGEBEN.** Für reale Freigabe: separates Testspiel mit exakt gepinnten Rawra-SE2.14.x/BepInEx-, APIShared-, Fixes-, Tweaker- und Serpens-Versionen; unabhängiger Rebuild der eigenen Runtime gegen diese ABI, SHA-/Paketprüfung, Spielstart-/Mapwechsel-/Save-/Multiplayer- und Hook-Konflikttests, BC7-/Noesis-/GM-Masken-/Atlasvergleich und Ausschluss von Konfigüberschreibungen. Der Benutzer muss das Installationsziel selbst ausdrücklich wählen; hier wurde keines aktiviert.

**Versionsänderungen nach dem 22.10.2026** erfordern eine neue Quellen-/Releaseprüfung. Ein statischer Test ist keine Bestätigung tatsächlicher Ingame-Kompatibilität.

## 6. Zusätzlicher Identitäts- und Herkunftsnachweis (Folgeprüfung)

Beim zweiten Quell-gegen-Paket-Abgleich wurde eine bisher nicht ausreichend getrennte Identität festgestellt:

- Der **Paketmanifest-GUID** `info.json` ist `strongholdeuropede.private`; dieser beschreibt das gesonderte Modpaket.
- Die **tatsächliche BepInEx-Runtime-Plugin-ID** stammt aus `GeneratedAudioContract.PluginId` in `StrongholdEuropeRuntimePlugin.cs` beziehungsweise `src/stronghold_europe_de/runtime_build.py`: `strongholdeuropede.runtime.private`.
- Beide Werte sind **absichtlich verschiedene Verträge**; weder muss man sie gleichsetzen noch darf man daraus zwei installierte DLL-Kopien ableiten.
- Das ausgelieferte `dist/europe-production-bc7-v2/StrongholdEuropeDE/Runtime/audio-profile.tsv` nennt `script_extender_version = 1.44.0.0`. Die **jetzt maßgebliche** `config/runtime-prerequisites.json` fordert `2.11.0`. Dadurch fehlen ein gegenwärtig konsistenter Quell-/Paket-Buildbeleg und eine geprüfte 2.14.x-Upstream-ABI.
- Ein zweiter **blockierender** Auditcode `PACKAGE_SE_ATTESTATION_MISMATCH` verhindert, dass ein altes 1.44-Artefakt als gegen 2.11 oder 2.14 geprüft ausgegeben wird. `PACKAGE_RUNTIME_GUID_MISMATCH` schützt zusätzlich die echte Runtime-ID.
- Die tatsächliche QA-Auditdatei `work/reports/ui-audit/shcde-community-compat-20261022.json` führt nun **beide** P0-Sperren `RUNTIME_ABI_PIN_MISMATCH` und `PACKAGE_SE_ATTESTATION_MISMATCH`. Die GUID-Prüfung ist korrekt; der Versionskonflikt wird nicht verdeckt.

**Ergänzte Negativfälle**: fehlende/duplizierte Runtime-Attestation, falsche Runtime-Plugin-ID, Paket-SE-1.44 bei Quellpin2.11, verschachtelte unbekannte DLL ohne Manifest und geschützte Fremdmod-Remove-/Restore-Pfade. Nach dieser Erweiterung waren **44 gezielte Tests bestanden, 0 fehlgeschlagen**.

**Reproduzierbare Kommandos, alle ohne Installations-/Produktionsschreibzugriff:**

```powershell
Set-Location E:\SpriteSuite
.\.venv\Scripts\python.exe tools\community_mod_compat.py --game-root E:\SSGameQA --candidate E:\SpriteSuite\dist\europe-production-bc7-v2\StrongholdEuropeDE --json-out E:\SpriteSuite\work\reports\ui-audit\shcde-community-compat-20261022.json
.\.venv\Scripts\python.exe -m pytest -q tests\sandbox\test_community_mod_compat.py tests\sandbox\test_original_tool_contracts.py tests\sandbox\test_target_selection_version_guard.py
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tools\qa_sandbox_headless_system.ps1
```

**Der Community-Audit gibt bei sicher erkanntem Versionskonflikt bewusst Exitcode 2 zurück** – das ist ein erfolgreich erkannter, blockierender Zustand, **kein** bestandener Ingame-Kompatibilitätstest.

Die vollständige Schlussabnahme benötigt weiterhin einen neuen, exakt gepinnten 2.14.x-Testzweig, ein eigenes Runtime-Rebuild nach Original-/Quell-Hashprüfung, APIShared-/Fixes-/Tweaker-/Serpens-Koexistenztests im gestarteten Spiel und explizite Zustimmung zum Testziel. Bis dahin wird keine Vollkompatibilität behauptet.

## 7. Zusätzlicher Qt-Regressionsbefund und Schutz

Der erste erweiterte 67-Modul-Headless-Run (vor Runtime-ID-Prüfung) endete vollständig mit **671 bestanden, 0 fehlgeschlagen, 0 übersprungen**. Anschließend wurde der Sicherheitsprüfer um paketinterne Runtime-/SE-Provenienz ergänzt. Der zwischenzeitlich gestartete zweite Run wurde zum Einbau dieser zusätzlichen Validierung **bewusst beendet** und ist keine Abnahme.

Ein nachfolgender kombinierter Qt-Lauf mit diesen Prüfungen traf nach etwa 63 % auf einen **nativen Windows ACCESS_VIOLATION** in `test_legacy_v1_editor_lossless.py:128` beim Aufruf von `QGraphicsItem.setSelected(True)`. Dieser Run gilt als **NICHT BESTANDEN**, nicht als Skip oder regulärer Python-Testfehler. Der Fehlerpfad war die mögliche Reentranz zwischen dem Qt-Szenen-Neuaufbau und dem Animationsslider:

1. `sandbox_animation_panel.py` blockiert programmgesteuerte Slider-Signale bei der Objektauswahl – Objektauswahl ist kein Scrub-Auftrag.
2. `sandbox_test_board.py` kapselt den historischen Qt-Neuaufbau mit `_legacy_rebuilding`, unterdrückt temporäre Auswahlereignisse und publiziert die endgültige Auswahl erst nach Abschluss des Neuaufbaus.
3. `test_legacy_v1_editor_lossless.py` prüft zusätzlich **24 aufeinanderfolgende V1-Auswahlwechsel**, Framevorschau und unveränderte Szenen-History.

Der danach gezielt ausgeführte V1-/Animations-/Editor-Testlauf ergab **8 bestanden, 0 fehlgeschlagen**. Ein erneuter **vollständiger** 67-Modul-Lauf ist für die Endabnahme verpflichtend; bis zu dessen bestätigt fehlerfreiem Abschluss darf die Qt-Gesamtreihe nicht grün gewertet werden. Die Qt-Offscreen-Tests sind weiterhin kein Ersatz für native Tk/Qt-DPI-/Screenreader- oder Ingame-Kompatibilitätsprüfungen.

## 8. Abschließende komplette Regression nach dem Qt-Stabilitätsfix

Die zwischenzeitliche Native-`ACCESS_VIOLATION` wurde ausdrücklich NICHT als Skip umgedeutet. Die `QGraphicsScene`-Auswahl und der Animationsslider wurden gegen reentrante Qt-Objektlöschung geschützt und mit 24 V1-Auswahlwechseln erneut geprüft.

**Tatsächlich vollständig beendeter Schlusslauf:** `67` Module, **677 bestanden, 0 fehlgeschlagen, 0 Fehler, 0 übersprungen**, `HEADLESS_PYTEST_EXIT=0`, **390,68 Sekunden**.

- `work/reports/ui-audit/sandbox-headless-community-67modules-qt-stable-20261022.xml` – vollständige JUnit mit 677 einzelnen `testcase`-Einträgen
- `work/reports/ui-audit/sandbox-headless-community-67modules-qt-stable-20261022.log` – Konsolenlauf und bestätigter Exit 0
- `work/reports/ui-audit/shcde-community-integrity-proof-qt-stable-20261022.json` – unabhängige JUnit-/Modullisten-Konsistenz, zwei versionierte Community-P0-Sperren, getrennte Paket-/Runtime-ID sowie 3 Original-Spielhashes
- `work/qa_verify_community_integrity_20261022.py` – reproduzierbarer lesender Verifizierer

Der unabhängige Proof meldete **PASS** in allen geprüften Punkten: 677/677 JUnit-Fälle, 67/67 erwartete Module, 0 Skip/Error/Failure, aktuelle QA-Community-Kompatibilität **korrekt BLOCKED**, `RUNTIME_ABI_PIN_MISMATCH` und `PACKAGE_SE_ATTESTATION_MISMATCH` korrekt erfasst, echte Runtime-ID und Paketmanifest getrennt, 3/3 unveränderte Originalspiel-Dateihashes, unveränderter Git-HEAD `00276ec`.

**Abnahmegrenze:** Die komplette ausdrücklich definierte Headless-/Qt-Offscreen-Regression ist damit bestanden. Sie ersetzt **keinen gemeinsamen Spielstart** mit den neuesten Rawra-, APIShared-, Ensrick- und Serpens-Mods, keine Mehrspieler-/Save-/Shader-/Hook-Parität, kein versionspin-geprüftes SE-2.14.x-Rebuild und keinen echten produktiven Installationslauf. **Gesamt-Release weiterhin NICHT FREIGEGEBEN.** Keine Installationen, keine Originalspiel-Dateischreibzugriffe, kein Git-Commit.

# Sprite Suite – Originalpixel-Audit und Quellenwechsel im Spiel-HUD

**Datum:** 15.10.2026 · **Projekt:** `E:\SpriteSuite` · **Branch:** `feature/sandbox-studio` · **HEAD:** `00276ec`

**Abnahmeurteil: Technischer Teilnachweis, KEINE Original-Spielablauf-, Shader- oder Gesamt-UI-Freigabe.**

## Ausgangsfehler: passende XAML-Koordinaten, unpassender Pixelatlas

Die ursprüngliche `config/sandbox-hud-original-art-v1.json` verwendet XAML-Originalrechtecke aus der installierten Datei `HUD_Main.xaml` und `UI-MasterAtlas.xaml`, aber als Pixelquelle das eigens abgeleitete
`assets/ui/derived/ui-europa-geprueft/UI-MasterAtlas.png`. Dieser Europa-Override ist im Unterschied zum unmodifizierten Original **anders gepackt**. Beispiel: `UI-Scribe B001` zeigt im Europa-Store mehrere zusammengeschnittene Icons/Personen; dieselben XAML-Koordinaten im **originalen** Spielatlas ergeben einen vollständigen Schreiber. Ein zweiter abgeleiteter Store `origins-blue-silver` zeigte die gleiche strukturelle Unverträglichkeit.

Das zuvor als „verifiziert“ bezeichnete Alt-HUD kann damit nicht als originalpixelidentisch gelten. Die in den früheren Runden zugesicherte Byteidentität der XAML-Dictionary-Datei **beweist gerade nicht**, dass diese XAML-Rechtecke mit einem umgepackten Atlas kompatibel sind. Die frühere Europakunst bleibt unangetastet und im eigenen Editormodus weiterhin verfügbar; ihre fehlende Original-Bildzuordnung ist ausdrücklich zu benennen.

Quellennachweise, jeweils aus der autorisierten lokalen SHCDE-Installation unter `E:\SSGameQA`:
- **Original-UI-Asset:** `Stronghold Crusader Definitive Edition_Data/globalgamemanagers.assets`; SHA-256 `84acb0f8fce92551872b004c51bf7201ed07ebc0de85837ef0af0e14c0841fc3`.
- **Installiertes UI-XAML-Wörterbuch:** `BepInEx/plugins/000shcdese/Override/Assets/GUI/Sprites/UI-MasterAtlas.xaml`; SHA-256 `b4092a81bdef00449f65b37d3988c432c1862f409d085ff84c039a71007cfb88`.
- **Installierte HUD-Datei:** `BepInEx/plugins/000shcdese/Override/Assets/GUI/XAMLResources/HUD_Main.xaml`; SHA-256 `b84c40b60ac4b790f9ecb5ae712234664ddedb3c73a69988dd5a8b8187a4ab74`.
- **Lokaler umgepackter Europaatlas:** `assets/ui/derived/ui-europa-geprueft/UI-MasterAtlas.png`; SHA-256 `cfbc7915123c73e908caaaeee8358860ac8662d3501ce4b2318897689abf7652`.

## 1. Originalressourcen nachgewiesen

`globalgamemanagers.assets` besitzt eine echte Unity-`Texture2D` `UI-MasterAtlas` (8192×8192, Format 25/BC7, 14 Mipmap-Stufen); außerdem Original-`UI-TrailAtlas`, `UI-Colour1Atlas` und `UI-Colour2Atlas`. Es wurden **nur Metadaten beziehungsweise die jeweils benötigten BC7-Blöcke** gelesen, nicht das vollständige 8192²-RGBA-Blatt im UI entschlüsselt. Der wiederverwendbare Decoder `src/stronghold_europe_de/sandbox/ui_bc7_crops.py` hält Rechtecke auf 4×4-Kompressionsblöcke beschränkt und verwirft unsichere/zu große Koordinaten.

`tests/sandbox/test_ui_bc7_crops.py` prüfte den partiellen Decoder an einem synthetischen BC7-Bild gegen die vollständige Pillow-Dekodierung, einschließlich vertikalem Flip, Rand- und Fehlerfällen: **21 bestanden**.

Die separate, rein lokale, *nicht zu installierende* QA-Ablage
`work/original-ui-native-crops-20261015/` enthält genau **354** mit SHA-256 gepinnte und dimensionierte Originalgrafik-PNGs samt `manifest.json`:
- **265** echte Original-HUD- und -Bauressourcen mit unveränderten Quellrechten aus `UI-MasterAtlas.xaml`.
- **89** vollständige Schreiber-Frames (`UI-Scribe B001…B045` und `UI-Scribe C001…C044`). Diese sind **ausschließlich manuelle Referenzen**: Spielzustand, Timing, B/C-Auswahl, Affekt und Skinwechsel wurden *nicht* verifiziert.

Damit ist die **Pixelherkunft einzelner statischer XAML-Quellrechtecke** nachgewiesen, nicht deren Verwendung zur richtigen Spielzeit.

## 2. Implementierung in der eingebetteten Sandbox

Neues `tools/sandbox_native_hud_crop_provider.py`: `OriginalGameUICrops` prüft vor dem Anzeigen Quell- und HUD-XAML-Hashes, alle 265 XAML-Rechtecke, sichere PNG-Dateinamen, SHA-256 und Abmessungen der tatsächlichen PNGs. Fehler führen zu **text-only Befehlen** statt zum stillen Rückfall auf die visuell unpassende Europagrafik. Originalspiel-Dateien werden weder im UI dekodiert noch geändert; der Quell-Hash der 225-MB-Datei wird pro Dateiversion gecacht.

`tools/sandbox_gameplay_mode.py`: Bauicons und das XAML-Element `UI-HUD 007` werden auf das nachgewiesene Originalmaterial umgestellt, während die Qt-Schaltflächen, echte Karte, eingebettete Minikarte und Editor-Kommandos interaktiv bleiben. Jeder sichtbare Kommandobutton kennzeichnet seine Originalpixel-Herkunft und die ausdrücklich *noch nicht* verifizierte Laufzeitbedingung. Der Editor behält die lokal bearbeitete europäische UI und dieselbe native Karte. **Kein neuer originaler Baubefehl oder Beraterautomat wird behauptet.**

`work/qa_export_native_ui_crops_20261015.py` erzeugt/verifiziert die lokale Quelle deterministisch, ersetzt keine vorhandene abweichende Datei und schreibt nur in `work/`. Diese QA-Pixel sind nicht Teil eines Releases.

## 3. Belegdateien im Projekt

- `work/reports/ui-audit/historic-hud-portrait-resource-inventory-20261015.json`
- `work/reports/ui-audit/original-ui-atlas-metadata-20261015.json`
- `work/reports/ui-audit/ui-scribe-original-bc7-crops-20261015.jpg`
- `work/reports/ui-audit/hud-scribe-two-derived-stores-20261015.jpg`
- `work/reports/ui-audit/native-ui-cropped-bc7-reference-20261015.jpg`
- `work/reports/ui-audit/native-ui-cropped-bc7-evidence-20261015.json`
- `work/reports/ui-audit/sprite-gameplay-1168x542.png`
- `work/reports/ui-audit/sprite-gameplay-784x342.png`
- `work/reports/ui-audit/hud-geometry-verification-20261014.json`
- `work/reports/ui-audit/suite-embedded-original-ui-crops-1500x930.png` (nur bei bestätigtem nativen Tk-/Qt-Testlauf).

## 4. Abnahmestufen und noch offene Blocker

**Aktualisierung nach ausgeführten Tests am 15.10.2026:**
- Kombinierte Regression (10 Testdateien einschließlich `test_ui_bc7_crops.py`, `test_original_hud_crop_provider.py`, `test_gameplay_mode_workspace.py`, `test_native_engine_seams.py` und bestehender HUD-/Qt-Tests): **96 passed** in 399,60 Sekunden, Exit 0. Die längere Laufzeit ist kein Grund, die 96 Fälle als Gesamt-Release-Abnahme zu zählen.
- Quell-/Hash-Fehlerprüfungen des `OriginalGameUICrops`-Providers: **8 passed** als isolierter Test. Echte Iconpixel wurden in Qt mit der SHA-geprüften Quelle verglichen, gleichzeitig stimmt das Editor-Europa-Pixmap absichtlich **nicht** mit der originalen XAML-Crop-Datei überein.
- Teil-BC7-Decoder: **21 passed** als isolierter Test einschließlich winziger, ungerader Randrechtecke, vertikalem Flip, ganzem Testbild und invaliden Quellen.
- Echte Originalkarte in Qt bei 1168×542, 784×342 und 960×470: **GAMEPLAY_VISUAL_QA_PASS**. Bild `sprite-gameplay-1168x542.png` zeigt nun **passende originale Gebäudesymbole über der originalen HUD-Pergamenttextur**.
- In der tatsächlich eingebetteten Windows/Tk-/Qt-Hauptsuite bei 1500×930: der Button wurde pixelweise mit `OriginalGameUICrops.crop()` verglichen, einschließlich Herkunftstooltip und Quellhintergrund. **NATIVE_SHA_PINNED_ORIGINAL_UI_ICONS_PASS**. Beleg: `work/reports/ui-audit/suite-embedded-original-ui-crops-1500x930.png`. Bei 1020×680 wurde die eingebettete HUD-Geometrie ebenfalls erneut geprüft.
- Vollständiger nativer Windows/Tk-/Qt-Testlauf: **QA_PASS**, Exit 0, 165,36 Sekunden. Neben `NATIVE_SHA_PINNED_ORIGINAL_UI_ICONS_PASS` meldete er die vorhandenen `NATIVE_CACHED_ARTWORK_HUD_PASS`, `NATIVE_GREEN_SPINE_ACTIONS_PASS`, `CATALOGUE_GAME_HUD_PLACEMENT_SYNC_PASS` und die bisherigen Diagnose-/Release-Preflight-/Werkzeug-Navigationsprüfungen. Die Freigabe betrifft die konkreten geprüften Abläufe, nicht sämtliche historischen Workflows.

Die Schreiber-Bildfolgen **werden bewusst nicht automatisch animiert**, denn weder das `HUD_Main.xaml` noch die Verfügbarkeit der BC7-Pixel belegen die originale zustandsabhängige Reihenfolge im laufenden Spiel. Die `SCRIBE`-Avatar-Dateien im installierten `Assets/GUI/Avatars` sind teilweise bloße Masken; aus ihrem Namen lässt sich kein vollständig funktionaler Berater rekonstruieren. Die originalen `UI-Scribe B/C`-Ausschnitte sind dagegen wirkliche vollständige Quellbilder.

- **HUD-01 P0:** Echte Spielberatungs-, Ressourcen-, Zeit-, Animations-, Baubedingungs- und UI-State-Machine-Verträge weiterhin *nicht abgenommen*. Statische Quellpixel ≠ dynamisches Spiel-HUD.
- **MAP-01 P0:** Engine bleibt ein pausierter Snapshot; zeitgleicher Kamera-/Shader-/Wasser-/Licht-/Szenenabgleich offen.
- **PIPE-01 P0:** Juni-Toolchain, Dependencies, identische alte Workflow-Ausgabehashes noch unbelegt.
- **UI-01 P1:** Multi-Monitor-DPI, Screenreader, Benutzer- und Langzeittests offen.

**Originalschutz:** Weder `.map` noch `globalgamemanagers.assets`, XAML, Unity-Archive oder veröffentlichte Atlasstores wurden überschrieben. Keine Installation, kein Build-/Release-Commit; vorgefundene uncommittete Änderungen erhalten. Die QA-Nachweise liegen nur auf dem lokalen Windows-Arbeitsrechner.

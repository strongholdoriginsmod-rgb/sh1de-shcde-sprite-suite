# Sprite Suite – reale HUD-Auswahlzustände und bedingte Bauaktionen

**Stand:** 14.10.2026 (Fortsetzung nach der HUD-Geometrie-Teilprüfung)  
**Projekt:** `E:\SpriteSuite`, Branch `feature/sandbox-studio`  
**Abnahmestufe:** Funktionaler Zwischenschritt, keine 1:1-Originalspielparität.

## 1. Ermittelter Ist-Zustand

Der vorhandene `NativeMapCanvas` lieferte bereits echte Auswahlereignisse:
`picked` mit originalen Kartenkanälen,
`original_building_selected` (Sektion 1013),
`original_tree_selected` (Sektion 1014),
`object_selected` für das Arbeits-Overlay sowie
`engine_sprite_picked` aus dem pausierten Runtime-Snapshot.
Das bisherige Spiel-HUD benutzte diese Informationen nicht für
einen sichtbaren, wechselseitigen rechten HUD-Zustand.

Das XAML-Baukommando-Manifest enthielt **141 Befehle** und
**11 gemeinsame Icon-Positionen mit bedingten Alternativen**.
Die erste Spielmodus-Implementierung zeigte bei solchen Positionen
immer das zuerst gefundene Icon, selbst wenn der Benutzer eine
andere Variante im Auswahldropdown auswählte. Das war ein echter
visueller/Funktions-Widerspruch.

## 2. Implementierte Korrekturen

### Tatsächliche Karten-/Auswahlansicht

- Neues `tools/sandbox_gameplay_context.py` als Qt-unabhängiges,
  unveränderliches Datenmodell `HudContext`: Auswahl wird
  aus der **aktuell** selektierten Original- oder Overlay-Quelle
  gelesen, statt alte GUI-Texte wiederzuverwenden.
- Originalgebäude: Typ-ID, Besitzer, UID, Koordinaten, Datensatznummer
  mit deutlicher Kennzeichnung *Original / nur lesen*.
- Originalvegetation: echte Rohgruppe, Rohvariante, Rohzustand,
  Position und Datensatznummer; **keine spekulative Baumart**.
- Kacheln: unveränderte Rohwerte der Kanäle 3004, 3005 und 3037,
  fehlende Kanäle ausdrücklich als unbekannt. Keine Materialableitung.
- Engine-Snapshot-Grafik: originaler Befehlsbezug und Quellframe,
  aber **keine** Behauptung über dynamische Simulation oder Shader.
- Eigenes Overlay-Sprite: Arbeitsgruppe, Frame, Team, Position
  und ID aus der editierbaren Arbeitskopie, klar getrennt von den
  schreibgeschützten Originalkartenobjekten.
- Nach Quellkartenwechsel werden alte angeklickte Kachelwerte
  zurückgesetzt. Die Szene wird für die Anzeige nicht neu geladen,
  Originalkarten und Unity-Dateien werden nicht geändert.
- Die frühere rechte Minikarte erhält einen
  **reversiblen Auswahl-/Radar-Zustand** im selben HUD.
  Der echte `NativeMiniMap` bleibt als dasselbe Qt-Objekt erhalten
  und folgt weiterhin der Kamera. Die Auswahl kann automatisch
  erscheinen oder über den kleinen Umschalter zurück zur Minikarte
  wechseln. `Prüfen` öffnet den vorhandenen nativen Karten-Inspector
  im Editor statt einen neuen Parallel-Inspector zu erzeugen.
- Die Auswahlkopfzeile wird nur einmal angezeigt.
  Die rechte Spalte wurde gemäß dem historischen Spiel-HUD breiter
  aufgeteilt, damit IDs und Ortsangaben bei kleiner HUD-Höhe nicht
  hinter den Schaltflächen verschwinden.
- DE/EN-Begriffe und zugängliche Kontrollnamen ergänzt.

### Bedingte XAML-Bauaktionen

- Der sichtbare Slot ersetzt bei einer bewusst gewählten bedingten
  Variante **auch sein Icon, Tooltip, AccessibleName und Klickziel**.
  Mehrere Alternativen werden weiterhin nicht überlagert.
- Das XAML definiert Original-Kommandonamen, **nicht** die aktuell
  simulierte Bauoption der Game-Engine. Das Dropdown bleibt daher eine
  manuelle Testauswahl. Ohne nachweisliche Nutzerbindung führt ein
  Klick zu keiner Sprite-Platzierung.
- Während eines Bauseitenwechsels verzögert eintreffende alte Qt-Klicks
  dürfen keine Aktion der früheren Seite oder eines zufällig gleich
  positionierten Slots auslösen.

## 3. Echte, unveränderte Originalkarten geprüft

Quelle (nur gelesen):
`E:\SSGameQA\Stronghold Crusader Definitive Edition_Data\StreamingAssets\Maps\Antioch.map`

SHA-256 vor und nach der Prüfung:
`c0b4317d3d708f721b5a0b27f04d2f2114063b3f587d04985fd7ca2d0ad6ff51`

Faktische QA-Auswahlzustände:

| Zustand | Gelesene originale Daten | Nachweis |
| --- | --- | --- |
| Bauwerk | Typ-ID 55, Besitzer 3, Kachel (387,501), UID 805 | Sektion 1013, nur lesen |
| Vegetation | Rohgruppe 30, Variante 18, Zustand 8, Kachel (415,482) | Sektion 1014, Spriteart offen |
| Kachel | (415,482), 3005=8, 3004=476, 3037=16 | Unveränderte Rohwerte |
| Overlay | `tree_pine/20` per Qt-Mausklick gesetzt, zurückgenommen und wiederholt | Nur temporäre Arbeitskopie |

Evidenz unter `work/reports/ui-audit/`:
`gameplay-selection-state-verification-20261014.json`,
`gameplay-context-building-1168x542.png`,
`gameplay-context-tree-1168x542.png`,
`gameplay-context-tile-1168x542.png` sowie
`suite-embedded-gameplay-selection-1500x930.png`.
Es handelt sich um **verschiedene Karten- und Spielzustände**
gegenüber den vier historischen Game-Screenshots; aus den Bildern
wird daher **keine Pixel- oder Shaderparität** abgeleitet.

## 4. Teststand und Gefährdungsschutz

- `tests/sandbox/test_gameplay_context_states.py`:
  Original-, Overlay-, Baum-, Kachel- und Engine-Snapshot-Zustände
  ohne Typvermutungen; fehlende und gelöschte Datensätze.
- `tests/sandbox/test_gameplay_mode_workspace.py`:
  echte lokale Kartenobjekte und Umschaltung von Minikarte/Info,
  Sprachwechsel, Rückweg zum Inspector, funktionale XAML-Alternativen,
  stale-event-Schutz.
- Die erste Fassung eines Qt-GUI-Tests **brach nativ ab**, weil
  `has_map()` auf einem nicht initialisierten Canvas künstlich
  auf `True` gesetzt wurde. Das war kein gültiger Test einer
  Originalkarte. Die betroffenen GUI-Prüfungen wurden auf das
  tatsächlich geladene, nur lesend benutzte Kartenabbild umgestellt.
  Der separate rein datenbezogene Modelltest nutzt weiterhin
  zulässige Fake-Records ohne Qt-Renderer.
- `work/qa_gameplay_context_selection_20261014.py`:
  **GAMEPLAY_CONTEXT_REALMAP_QA_PASS**;
  Vergleich von Originalkarten- und Overlay-Serialisierung vorher/
  nachher unverändert.
- `work/qa_gameplay_interaction_oct14.py`:
  **GAMEPLAY_CLICK_UNDO_REDO_QA_PASS**; nun einschließlich des
  dazugehörigen sichtbaren Overlay-Auswahlzustands.
- `work/qa_gameplay_real_mouse_pick_20261014.py`:
  **MOUSE_BUILDING_PICK_PASS** bei einer wirklichen
  `QTest.mouseClick`-Eingabe auf die native Kartenansicht nach
  Kamerazentrierung. Das ausgewählte Originalgebäude ist Datensatz 23,
  Typ-ID 55, Besitzer 3; der live aktualisierte rechte HUD-Kopf meldete
  `Originalbauwerk`, keine künstliche Szenenselektion. Der
  Original-`.map`-SHA-256 blieb ebenfalls identisch
  (**MOUSE_PICK_ORIGINAL_SOURCE_UNCHANGED**). Das prüft eine konkrete
  Eingabeposition, nicht sämtliche Objekttypen/Kameralagen.
- `tools/qa_suite_embedded.py` auf dem echten Windows-Desktop:
  **NATIVE_ORIGINAL_SELECTION_READONLY_PASS** und **QA_PASS**,
  unter Erhalt der nativen Tk-/Qt-Kindfenster-Einbettung bei
  1500×930 und 1020×680.
- Die fünf gezielten lokalen Testdateien
  `test_gameplay_context_states.py`,
  `test_gameplay_mode_workspace.py`,
  `test_sandbox_compact_layout.py`,
  `test_hud_compact_workflow.py`,
  `test_hud_composition.py` wurden auch nach dem letzten
  Seitenwechsel-Schutz nochmals kombiniert ausgeführt:
  **40 bestanden**.

## 5. Verbleibende Abnahmeblocker

**HUD-01 (P0) offen:** Die reinen Auswahl-/Werkstattsignale beweisen
keine 1:1-Bau-, Kampf-, Berater-, Wirtschafts- oder Ressourcenlogik.
Die übrigen HUD-Layer, Spielportrait-Assets, Originalrahmen, Zustands-
und Shaderanimationen fehlen weiterhin als nachgewiesene Gesamtlösung.

**HUD-02 (P0) teilweise adressiert:** Reversibler Spiel-/Editor-Modus,
selbe Karte und Auswahlzustand; keine vollständige Unity-UI-Rekonstruktion.

**MAP-01 (P0) offen:** Pausierter Runtime-Snapshot statt zeitgleichem
Originalspiel. Identische Kamera, Zoom, Tageszeit und Renderzustände
müssen vor einem echten Pixelvergleich hergestellt werden.

**PIPE-01 (P0) offen:** Historischer Juni-Workflow und die vollständigen
Daten-/Versionen-/Ausgabehash-Verträge noch nicht nachgewiesen.
Keine Installations- oder Buildfreigabe aus diesem Teiltest.

**UI-01 (P1) offen:** Bedienaufgaben bei wechselnden Windows-DPI-Werten,
Langzeit- und Screenreaderprüfung müssen folgen.

Die vorbestehenden, uncommitteten UI-Änderungen bleiben unangetastet.
Original-`.map`, installierte Spieldateien und Originalscreenshots
wurden nicht ersetzt oder geändert. Die Änderungen werden **nicht**
als vollständig abgenommen eingecheckt.

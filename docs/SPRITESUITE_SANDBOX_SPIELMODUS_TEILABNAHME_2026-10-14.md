# Sprite Suite – eingebetteter Spielmodus: technische Teilabnahme, 14.10.2026

**Status: implementierter, getesteter Zwischenschritt – KEINE 1:1-Originalspiel-Abnahme.**
Anknüpfung an `SPRITESUITE_UI_PIPELINE_PARITAETSAUDIT_2026-10-14.md`
(Commit `00276ec`). Die Blocker HUD-01/HUD-02 bleiben hinsichtlich
vollständiger Originaltreue OFFEN. MAP-01, PIPE-01 und die volle
Bedienbarkeitsabnahme wurden nicht erledigt.

## Was konkret geändert wurde

- `tools/sandbox_gameplay_mode.py` (neu): unteres, durchgehendes und
  bedienbares Qt-HUD unter dem echten NativeMapCanvas. Die Bauicons
  stammen aus den bereits verifizierten lokalen XAML-/Atlas-Crops.
  Kategorieseiten A–N und bedingte Varianten sind erreichbar.
  Der Renderer ist eine **Teilrekonstruktion**, kein Unity-/Noesis-HUD.
- `tools/sandbox_compact_layout.py`: explizit umschaltbarer Spielmodus
  und Experte/Editor-Modus. Eine bereits geladene native Karte öffnet
  die eingebettete Suite standardmäßig im Spielmodus; ohne Karte bleibt
  der Editor zur Quellwahl sichtbar. Qt-Toolbar, Karten-/Editor-Tabs
  und Docks werden im Spielmodus versteckt, nicht zerstört.
  `takeCentralWidget()` erhält den bisherigen Karten-Canvas und
  dessen History über sämtliche Moduswechsel.
- Es wird dieselbe `NativeMiniMap` von der Karten-Inspector-Spalte ins
  untere HUD und zurück verschoben: kein zweiter Radar, keine
  neue Kameraprojektion oder fingierte Minikarte.
- XAML-Kommandoklicks synchronisieren die ausgewählte Bauaktion in
  der ursprünglichen Icon-Werkstatt. Nur bereits vom Benutzer definierte
  `HudCommandBindings` dürfen ein tatsächliches Overlay-Platzieren
  vormerken. Nicht gebundene XAML-Befehle sind KEIN Engine-Mapping.
- Speicheraktion speichert ausdrücklich **nur** das Arbeits-Overlay.
  Undo/Redo benutzen die bestehenden Map-Canvas-Kommandos.
  Die Ressourcenanzeige nennt keine erfundenen Wirtschaftsbestände.
- `tools/sandbox_qt_locale.py` und
  `config/sandbox-qt-sprachen.json`: DE/EN-Anzeigenamen,
  Bauseiten und dynamische Overlay-Zählung in der Spielansicht.
- `tests/sandbox/test_gameplay_mode_workspace.py` (neu):
  reversible Moduswechsel, Canvas-/History-/Radar-Identität,
  Fallback ohne Originalkarte, Größe, reale Command-Bindings
  einschließlich Nichtplatzierung ohne Bindung, Werkzeug-Rückweg
  und Sprachwechsel.
- `tools/qa_suite_embedded.py`: der bereits lokal veränderte
  Windows-Einbettungstest bekam additive Prüfungen zur neuen
  Spielmodus-Startlage und einen zusätzlichen nativen Screenshot.
  Seine vorherigen, nicht eingecheckten Änderungen wurden beibehalten.

## Gemessene Ergebnisse, keine Pixelparitätsbehauptung

Testquelle: `E:/SSGameQA/Stronghold Crusader Definitive
Edition_Data/StreamingAssets/Maps/Antioch.map` (nur gelesen);
Renderer: der existierende native Engine-Snapshot und dessen echte
Sprite-Vorschau. Die Minikarte nutzt das echte Kartenradar.

| Qt-Viewport | sichtbarer NativeMapCanvas | unteres HUD | Aussage |
| --- | --- | --- | --- |
| 1168×542 | 1164×338 | 1168×157 | Nicht überlappende Karte und HUD |
| 960×470 | 956×287 | 960×136 | Zwischenlayout |
| 784×342 | 780×179 | 784×116 | Kompakter Zustand mit vergrößerter HUD-Mindesthöhe |

Die anfängliche 98-px-HUD-Höhe **schnitt** beim kleinsten Viewport
Beschriftungen ab. Korrektur: Mindesthöhe 116 px,
bei wenig Platz 32-px-Icongrößen, kompakter Kartentext und kürzere
Ressourcen-/Snapshot-Meldung. Anschließend erneut gerendert und
sichtgeprüft. Sichtbare Bedienung bei der kleinsten Fensterhöhe ist
damit VERBESSERT, eine umfassende Mensch-/DPI-Abnahme aber OFFEN.

Lokale, reproduzierbare Belege:
- `work/qa_gameplay_visual_oct14.py`: lesender Qt-Realmap-Probelauf
- `work/reports/ui-audit/sprite-gameplay-1168x542.png`
- `work/reports/ui-audit/sprite-gameplay-960x470.png`
- `work/reports/ui-audit/sprite-gameplay-784x342.png`
- `work/reports/ui-audit/suite-embedded-gameplay-1500x930.png`
  (Qt-Kindfenster **tatsächlich** innerhalb der Tk-Windows-Hauptsuite)

## Ausgeführte Prüfungen

- Gezielte eingebettete Qt-/HUD-Tests:
  `test_gameplay_mode_workspace.py`,
  `test_sandbox_compact_layout.py`,
  `test_hud_compact_workflow.py`:
  **19 bestanden**.
- `work/qa_gameplay_visual_oct14.py`: echte Antioch-Karte,
  drei Viewports, dynamische Minikarte, Erhalt von Karten- und
  Editormodus: **GAMEPLAY_VISUAL_QA_PASS**.
- `work/qa_gameplay_interaction_oct14.py`: auf der echten, nur lesend
  geladenen Antioch-Karte `tree_pine/20` über den Spiel-HUD-Knopf
  vorbereitet, mit einem Qt-Mausklick im gültigen Tile (397,431)
  in das **flüchtige Overlay** gesetzt, über HUD rückgängig gemacht,
  wiederhergestellt und nochmals rückgängig gemacht. Overlay-Serialisierung
  am Ende wieder identisch zum Anfang; SHA-256 der `.map` vorher/nachher
  identisch. **GAMEPLAY_CLICK_UNDO_REDO_QA_PASS** (kein Speicherdialog
  oder Installationszugriff ausgelöst).
- Drei weitere gezielte Testsuiten zu XAML-Komposition, Native-Seams
  und Runner-Integrität: **15 bestanden**.
- `tools/qa_suite_embedded.py` auf dem Windows-Desktop:
  native Tk-/Qt-HWND-Elternschaft, Layouts bei 1500×930 und
  1020×680, Katalog-/Werkzeug-Rückwege und neuer
  Spielmodus-Nachweis: **QA_PASS**.
- `git diff --check` für die neu editierten, zuvor sauberen
  Qt-Layout-/Sprachdateien: keine neuen Whitespace-Probleme.
  Der vollständige Arbeitsbaum enthielt vorher schon umfangreiche
  fremde/unfertige UI-Änderungen; sein globaler Diff-Check ist
  deshalb nicht aussagekräftig für diese Teilfunktion.

## Grenzen und nächste reale Abnahmeschritte

1. **HUD-01 weiterhin P0:** Die unteren Original-Spielleisten,
   Berater-/Einheitenportraits, vollständigen Zustandswechsel,
   passgenauen Rahmen, ökonomischen Ressourcen, Original-Shader
   und Bedingungslogiken sind nicht 1:1 rekonstruiert. Die
   aus lokaler europäischer XAML-Art gewonnenen Icons beweisen
   keine Original-Unity-Laufzeitparität.
2. **HUD-02 teilweise adressiert:** Spiel- und Editorarbeitsplatz sind
   sichtbar getrennt, mit geteiltem Karten-/Overlaymodell.
   Die Funktionalität wurde getestet, aber noch nicht vollständig
   gegen das Original-HUD von September visuell abgenommen.
3. **MAP-01 offen:** Kamerazustand, identische Renderauflösung,
   Shader, Wasser, Wind, Animation, Szenenzeitpunkt und Pixelvergleiche
   gegen Original-Gameplay-Bilder fehlen.
4. **UI-01 offen:** 784×342 Qt erlauben nur rund 179 px Karte.
   Benutzertests mit echten Auswahl-, Platzierungs-, Undo- und
   Speichern-Aufgaben bei unterschiedlichen DPI sind nötig.
5. **PIPE-01 offen:** Keinerlei neue Behauptung zu historischen
   Juni-Pipelines, installierten Werkzeugversionen oder Ausgabehashes.
6. Der komplette 609+-Regressionstestbestand ist in diesem
   Teilauftrag ausdrücklich **nicht** als bestanden erklärt.

Die vier wiedergefundenen Original-Spielbilder und
`gameplay_reference_2026-09-05_review.jpg` bleiben allein
lokale visuelle Referenzen. Der neue HUD-Balken ist eine prüfbare
funktionale Basis, aber keine nachgewiesene Kopie des Originals.

## Git- und Originalschutz

Ausgangsbranch: `feature/sandbox-studio`, Ausgangs-HEAD
`00276ec`. Die vorgefundenen uncommitteten Qt-, Suite-,
Sprach-, HUD- und QA-Arbeiten wurden weder zurückgesetzt noch
als vollständig fertig eingecheckt. Die neuen Dateien und
isolierten UI-/Sprachänderungen sind absichtlich zunächst Teil
des laufenden Arbeitsbaums, bis der verbleibende HUD-Abgleich
separat abgenommen werden kann. Die originale installierte
`.map`, Unity- und Assetdateien wurden nicht modifiziert.

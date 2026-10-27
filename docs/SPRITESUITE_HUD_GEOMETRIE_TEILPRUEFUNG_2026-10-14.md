# Sprite Suite – Original-HUD-Geometrie und Spielmodus, 14.10.2026

**Status: Teilverbesserung anhand echter Referenzmessungen, keine Gesamt-HUD-Abnahme.**
Dieser Nachweis ergänzt `SPRITESUITE_UI_PIPELINE_PARITAETSAUDIT_2026-10-14.md`
und `SPRITESUITE_SANDBOX_SPIELMODUS_TEILABNAHME_2026-10-14.md`.
Die Referenzbilder wurden nur gelesen. Keine Screenshot-Pixel werden als
statischer, vermeintlich dynamischer Spielzustand in die Anwendung eingebaut.

## 1. Originalreferenz und Grenzen

`E:/SU/projekt/sandbox/hud/hud.json` nennt die Bildschirmfläche
**2560×1440**, HUD-Start **(1060,1123)** und vier originale Spielaufnahmen
vom 04./05.09.2026 auf D:. Alle vier existieren und wurden anhand SHA-256
erfasst. Der frühere `tools/sandkasten.py` projizierte den zusammengestellten
Screenshot-Ausschnitt `hud.png` statisch auf die Welt. Das war eine visuelle
Referenz, keine vollständig spielbare GUI.

- Historische HUD-Ausschnittsgröße: **1500×317** px.
- Anteil horizontal: **58,594 %**, Beginn bei **41,406 %** der Breite.
- Anteil vertikal: **22,014 %**, Beginn bei **77,986 %** der Höhe.
- Gemessene Funktionszonen im Screenshot: linker Pergament-Baubereich,
  schmale grüne Befehlsleiste, gerahmte Minikarte und rechte wechselnde
  Berater-/Objekt-/Spielbereiche. Die vier Spielbilder zeigen unterschiedliche
  Bau-/Zustandskonstellationen, also keine universelle statische HUD-Textur.
- Die verifizierten lokalen XAML-Crops besitzen für die untersuchte
  `HUD_Main.xaml`-Baukompositionsschicht genau einen `UI-HUD 007`-Hintergrund
  im Manifest; er zeigt andere Oberflächenkunst, **nicht** den vollständigen
  Pergament-/Minikarten-/Berater-Composite des Originalspiels.
  Diese Quelle ist ein **lokal abgeleiteter Europa-Override**, kein
  unverändertes Spiel-Unity-Atlas-Original.

Lokaler Bildkontaktbogen (nur QA):
`work/reports/ui-audit/hud-original-bottom-contact-sheet.jpg`.
Quellbild-Prüfsummen und Screenshot-Evidenz:
`work/reports/ui-audit/hud-geometry-verification-20261014.json`.

## 2. Implementierte Überlagerung, keine zweite Welt

`tools/sandbox_compact_layout.py` hält nun die bisherigen
`QTabWidget`/`NativeMapCanvas` im vollständig ausfüllenden
`GameplayMapHost`. Der aktive `EmbeddedGameplayHUD` wird als
**separates, rechts unten fixiertes Overlay** darüber positioniert.
Nur die tatsächlichen HUD-Elemente belegen Mausfläche; die Spielwelt
links und unterhalb des früheren breiten HUD-Streifens bleibt als Karte
erreichbar. Im Expertenmodus wird das Overlay ausgeblendet, der
gleiche Canvas mit derselben Overlay-History bleibt bestehen.

Die proportionale Lage basiert explizit auf
`REFERENCE_SCREEN=(2560,1440)` und
`REFERENCE_HUD=(1060,1123,1500,317)`. Die Funktion
`gameplay_hud_bounds()` ist separat testbar. Bei zu wenig Platz
(<1050 logische Pixel Breite oder <400 Pixel Hosthöhe) wechselt sie
bewusst auf eine volle Breite bei mindestens 116 Pixel HUD-Höhe.
Das ist ein **Bedienbarkeits-Fallback**, keine Originaltreue.

`tools/sandbox_gameplay_mode.py`: Die Overlay-Fläche ist ausdrücklich
opak bemalt, damit die darunterliegende Engine-Karte nicht durch
Text-/Button-Lücken durchscheint. Die Baukommando-Zone erhält
einen **abgeleiteten neutralen Pergamentfarbton**; dieser ist
kein behaupteter Original-Shader oder nicht vorhandener Originalrahmen.
Die vorhandenen, SHA-verifizierten lokalen XAML-Crop-Icons bleiben
anklickbar; Befehlsdaten und Bindungssicherheit bleiben gleich.
In engen Ansichten werden nur die Icon-Beschriftungen ausgeblendet,
der vollständige zugängliche Name und Tooltip bleiben erhalten.
Die reale und weiterhin kameraabhängige `NativeMiniMap` wird
nicht dupliziert, sondern beim Moduswechsel umgehängt.

## 3. Gemessene Geometrie der realen Karte

Quelle: echte `Antioch.map` aus `E:/SSGameQA`, **nur gelesen**.
Messungen direkt aus Qt-Widgetgrößen; HUD-Rechteck relativ zum
zentralen Host. Die drei neuen Screenshots wurden vorliegenden
Originalen nicht pixelweise gleichgesetzt (Kamera/Szene/Zustand
unterscheiden sich).

| Qt-Hauptansicht | Karten-Canvas | Host | HUD-Rechteck (x,y,w,h) | Teststufe |
| --- | --- | --- | --- | --- |
| 1168×542 | 1164×495 | 1168×499 | (484,383,684,116) | Historische Lage proportional |
| 960×470 | 956×423 | 960×427 | (0,303,960,124) | Bedien-Fallback |
| 784×342 | 780×295 | 784×299 | (0,183,784,116) | Bedien-Fallback |

Für den breiten Host 1168×499:
- Horizontale linke Kante neu **41,438 %** vs. Referenz
  **41,406 %**, absolute Abweichung **0,032 Prozentpunkte**.
- HUD-Höhe neu **23,246 %** des Hosts vs. Referenz
  **22,014 %** des Bildschirms; Unterschied
  **1,233 Prozentpunkte**, durch Mindesthöhe 116 px.
- Das ist eine **Geometrieannäherung der HUD-Gesamtfläche**,
  kein Nachweis über die Subzonen, Original-Pixel oder Spielaktionen.

QA-Abbildungen:
`work/reports/ui-audit/sprite-gameplay-1168x542.png`,
`sprite-gameplay-960x470.png`,
`sprite-gameplay-784x342.png` und
`suite-embedded-gameplay-1500x930.png`.
JSON-Messung:
`work/reports/ui-audit/hud-geometry-verification-20261014.json`.

## 4. Nachweisstand

- Neue Parameter- und GUI-Regressionen in
  `tests/sandbox/test_gameplay_mode_workspace.py`:
  HUD-Referenzposition, kleiner Viewport, vollständig sichtbarer
  Karten-Canvas hinter dem HUD, Tooltip-/Button-Erreichbarkeit,
  gemeinsame Minikarte und Canvas-History, reversible Editoransicht.
- Gemeinsam mit `test_sandbox_compact_layout.py` und
  `test_hud_compact_workflow.py`: **25 Tests bestanden**.
  Einschließlich `test_hud_composition.py` zusammen
  **30 Tests bestanden**. Dabei werden die XAML-Icon-Klicks
  auch über die tatsächlichen Qt-Buttons ausgelöst; fehlende
  Benutzerbindungen dürfen keine Platzierung starten.
- `work/qa_gameplay_visual_oct14.py`:
  **GAMEPLAY_VISUAL_QA_PASS**, mit Quelle, SHA, Qt-Rechtecken,
  gemessenen normierten Werten und Belegbildern.
- `work/qa_gameplay_interaction_oct14.py`: per echtem Qt-Klick
  `tree_pine/20` in das flüchtige Antioch-Overlay platziert,
  rückgängig/wiederholt/rückgängig, Original-.map-SHA256 gleich:
  **GAMEPLAY_CLICK_UNDO_REDO_QA_PASS**.
- `tools/qa_suite_embedded.py` auf dem tatsächlichen Windows-Desktop:
  Qt bleibt in Tk eingebettet; bei Hauptfenstern 1500×930 und 1020×680
  sind Spiel-HUD-Rechteck, unverkleinerter Karten-Canvas, dynamische
  Minikarte und Moduswechsel geprüft: **QA_PASS**,
  **GAMEPLAY_NATIVE_LAYOUT_PASS** jeweils für beide Größen.
  Screenshot-Belege:
  `work/reports/ui-audit/suite-embedded-gameplay-1500x930.png`
  und `suite-embedded-gameplay-1020x680.png`.
  Der kleine Fall ist ausdrücklich ein bedienbarer Vollbreite-Fallback,
  keine behauptete pixelidentische Original-HUD-Geometrie.

## 5. Noch ausdrücklich NICHT abgenommen

**HUD-01 (P0)**: Unterleiste intern nicht 1:1, Beraterportraits und
andere dynamische rechte Zustände fehlen, echte Ressourcen/Wirtschaft
fehlen, die schmale grüne Befehlsleiste ist nicht rekonstruierte
Unity-Steuerlogik. Original-Rahmen, originaler Pergament-/Holz-Shader,
Hover-/Clipping-/Animationszustände sind offen.

**HUD-02 (P0)**: Getrennte und reversible Game-/Editor-Modi sowie
dieselbe Karte sind jetzt funktional, aber Gesamtparität nicht bewiesen.

**MAP-01 (P0)**: Die Original-Engine liefert einen pausierten Snapshot,
kein vollständig zeitsynchrones Original-Gameplay. Für echte Pixelparität
werden zeitgleiche Originalspielbilder bei identischer Kamera,
Auflösung, Zoom, Szene, Wetter und Spielzustand benötigt.

**UI-01 (P1)**: 1020×680 unter Tk ergibt nur 784×342 logische
Qt-Pixel; visuelle Bedientests bei DPI-Skalierung und Bildschirmlesern
bleiben offen. Der Vollbreite-Fallback ist bewusst nicht originalgetreu.

**PIPE-01 (P0)**: Historische Juni-Baseline, Versionierung,
Ausgabehashes und vollständige Pipelineidentität sind hiervon
unberührt. Keine neue Freigabe-/Bauaussage ableitbar.

## 6. Quellschutz und Git

Arbeit in `E:/SpriteSuite`, Branch `feature/sandbox-studio`.
Die vorgefundenen Änderungen und die in der vorigen Runde
entwickelten neuen Qt-Module wurden nicht zurückgesetzt. Die
Referenzbilder bleiben lokal und werden weder in Auslieferung
noch in UI-Hintergründe als vorgetäuschte Laufzeitgrafik übernommen.
Kein Release-/Installationsprozess, kein Umschreiben von Unity-/Map-Dateien.
Die weitere visuelle Originalabnahme bleibt ein offener Auftrag.

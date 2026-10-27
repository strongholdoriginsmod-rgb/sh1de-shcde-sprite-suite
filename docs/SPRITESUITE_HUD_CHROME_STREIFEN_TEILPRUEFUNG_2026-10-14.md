# Sprite Suite – historischer HUD-Befehlsstreifen und Minikartenrahmen

**Stand:** 14.10.2026 – Fortsetzung der visuellen HUD-Paritätsprüfung  
**Projekt:** `E:/SpriteSuite`, Branch `feature/sandbox-studio`, HEAD `00276ec`  
**Status:** Nachweisbarer, interaktiver **Teilnachbau der HUD-Chrome**, keine 1:1-Spiellaufzeit-Abnahme.

## I. Was die originalen Referenzen tatsächlich hergeben

Die vier wiedergefundenen Spielbilder liegen auf dem QA-Rechner vor
(je 2560 × 1440 Pixel). Die separat dokumentierte, aus den Bildern
abgeleitete HUD-Maske `E:/SU/projekt/sandbox/hud/hud.png` misst
1500 × 317 Pixel; der HUD-Beginn ist im Bildschirm (1060,1123).
Die vier Spielbilder beweisen ein räumliches Gestaltungsmuster,
**nicht** die Existenz einer rekonstruierbaren, interaktiven
Unity- oder Noesis-HUD-Pipeline in der Sprite Suite.

Der grüne, schmale Befehlsstreifen ist im 1500-Pixel-Ausschnitt
in etwa von **x=957 bis x=1015** sichtbar (Messbereiche
y≈235/275). Er trennt die pergamentfarbene Bauleiste vom
rechten Radar-/Auswahlbereich. Vorher bot die Sandbox nur
allgemeine Qt-Werkzeugknöpfe und die Minikarte ohne klaren
separaten Befehlsstreifen.

Quell-SHA-256 zum auditierbaren Originalschutz:

- `E:/SU/projekt/sandbox/hud/hud.png`:
  `c5c51ded393e2e362cb860cef5adebe3985968968c1172e15e6970e5793ea706`
- `E:/SU/projekt/sandbox/hud/hud.json`:
  `d6bf7b2be6c1da188fbecccdc800186b14051eda33695e9b94dae6eca751b4cc`
- Echte nur lesend geladene `Antioch.map`:
  `c0b4317d3d708f721b5a0b27f04d2f2114063b3f587d04985fd7ca2d0ad6ff51`

Die UI zeichnet **keine** statischen Spiel-Screenshots, Ressourcenstände,
Porträts oder Minikartenbilder aus diesen Quellen als vermeintlich
lebendes Spiel. Die originale Spielgrafik dient nur zur
Messung der Stellung und zur nachvollziehbaren Farbanmutung.

## II. Implementierte, tatsächlich klickbare HUD-Chrome

- Neues `tools/sandbox_hud_chrome_geometry.py` als reine
  Geometriemessung: Referenzbild 2560×1440,
  HUD-Ausschnitt 1500×317, grüner Befehlsstreifen
  etwa [957,1015]. Die Streifenbreite passt sich der
  verfügbaren HUD-Breite mit einem Minimum von 26 und
  Maximum von 52 logischen Qt-Pixeln an. Das ist eine
  nutzbare Annäherung, kein Original-XAML-Constraint-Beweis.
- `tools/sandbox_gameplay_mode.py` erhält eine eigene grüne
  `QFrame`-Leiste mit drei **echten Sprite-Suite-Aktionen**:
  `M` zeigt dieselbe kameraabhängige Original-Minimap,
  `i` schaltet zwischen Radar und realen Auswahl-/Rohdaten,
  und `›` öffnet den vorhandenen Originalkarten-Inspector.
  Diese Aktionen werden **nicht** als originalgetreue
  Stronghold-Spielbefehle ausgegeben.
- Der Minikartenbereich besitzt nun einen gesonderten
  warmen Holz-/Goldrahmen; die Auswahlansicht einen
  abgesetzten Datenrahmen. Die darunterliegende Karte
  wird nicht ausgetauscht oder neu geladen.
- Der schmale Streifen ist ein Qt-Kindwidget, kein
  Overlay einer alten Screenshot-Baustelle. Die
  Original-Minimap bleibt **dieselbe** `NativeMiniMap`,
  auch beim Umschalten in den Experteneditor.
- Tooltips und AccessibleNames für die drei Aktionen
  reagieren auf DE/EN. Beim Wechsel von Auswahl zu Radar
  wird zudem der Kopfzeilen-Tooltip auf echte
  Radarinformation zurückgesetzt; kein alter Objekttext
  bleibt fälschlich am Radar hängen.

## III. Zahlen aus tatsächlicher real-map Qt-Bildprüfung

Die Messungen sind im JSON-Bericht
`work/reports/ui-audit/hud-geometry-verification-20261014.json`
inklusive der Original-SHA-Prüfsummen und gerenderten
Screenshot-Hashes abgelegt.

| Qt-Fenster | HUD (w×h) | grünes Widget (x,y,w,h) im HUD | Abweichung der linken Kante |
| --- | --- | --- | --- |
| 1168×542 | 684×116 | (447,4,26,108) | +1,551 Prozentpunkte |
| 784×342 | 784×116 | (506,4,30,108) | +0,741 Prozentpunkte |
| 960×470 | 960×124 | (619,4,37,116) | +0,679 Prozentpunkte |

Die Referenzkante liegt bei 957/1500 ≈ **63,8 %**
der HUD-Breite. Die obige Abweichung ist eine
**Teilflächen-Positionsmessung**, kein Pixelgleichheitstest.
Das kleinere Fenster benutzt weiterhin absichtlich
den vollbreiten Bedien-Fallback; dessen äußerer HUD-Rahmen
ist daher gerade **nicht** originalgetreu.

Visuelle, lokale QA-Belege:
- `work/reports/ui-audit/sprite-gameplay-1168x542.png`
- `work/reports/ui-audit/sprite-gameplay-784x342.png`
- `work/reports/ui-audit/sprite-gameplay-960x470.png`
- `work/reports/ui-audit/suite-embedded-gameplay-1500x930.png`
- `work/reports/ui-audit/suite-embedded-gameplay-1020x680.png`

## IV. Abnahmetests und Einschränkungen

**59 gezielte Python/Qt-Tests bestanden** über:
`test_hud_chrome_geometry.py`,
`test_gameplay_context_states.py`,
`test_gameplay_mode_workspace.py`,
`test_sandbox_compact_layout.py`,
`test_hud_compact_workflow.py`,
`test_hud_composition.py`,
`test_native_engine_seams.py`.

Geprüft: Verhältnis zum gemessenen Screenshot-Ausschnitt,
dynamische Breite, Bedienbarkeit von M/i/› bei 1168×542
und 784×342, realer Objekt-Datensatz, Radar-Rückweg,
bereits existierender Qt-Inspector, Identität von Canvas,
History und Minikarte, deaktivierter Inspector ohne
native Karte sowie umschaltbare DE/EN-Zugriffsnamen.

`work/qa_gameplay_visual_oct14.py`:
**GAMEPLAY_VISUAL_QA_PASS**, alle drei Qt-Fenstergrößen
mit gemessenen Rechtecken, SHA und Zustandsberechnung.

`tools/qa_suite_embedded.py` auf dem tatsächlichen
Windows/Tk-/Qt-Hauptfenster: **QA_PASS** und
**NATIVE_GREEN_SPINE_ACTIONS_PASS**. Originalgebäude auswählen,
auf Minikarte wechseln, Kontext erneut anzeigen,
über den schmalen Streifen zum echten Editor-Inspector gehen.
Weiterhin beide Hauptfenstergrößen 1500×930 und 1020×680.

Zusätzliche **technische High-DPI-Simulation**, nicht
systemweite Windows-DPI-Abnahme:
`work/qa_hud_chrome_qt_scale_20261014.py`
bei Qt-Skalierung **1,25** und **1,50**, jeweils mit beiden
Fenstern 1168×542 und 784×342.
Alle vier Kombinationen bestanden mit skalierter
Qt-Geräteauflösung, benutzbaren und zugänglichen
Leistenknöpfen sowie Radar-/Info-Umschaltung.
Evidenz:
`work/reports/ui-audit/hud-chrome-qt-scale-1.25.json`,
`hud-chrome-qt-scale-1.50.json` und die entsprechenden PNGs.
Die Tests ersetzen **nicht** manuelle DPI-, Screenreader-,
Tastaturfokus- oder Langzeitsitzungsprüfungen.

`git diff --check` für die in dieser Runde bereits
getrackten Python-Dateien ergab keine neuen
Whitespace-Fehler. Der vorgefundene umfangreiche
uncommittete Arbeitsstand bleibt bestehen. Die
neuen Hilfsdateien und Tests wurden nicht als
fertiges Gesamtrelease eingecheckt. Kein
Originalspiel-/Release-/Mod-Installationslauf.

## V. Noch offene verbindliche Blocker

- **HUD-01 P0:** Originale dynamische Berater-/Porträts,
  Wirtschafts- und Spielbefehle, HUD-Zeit/Zustandslogik,
  Shader und Animationen sind **nicht** übernommen.
  Ein grüner Qt-Streifen ist nicht automatisch
  der originale Unity-Befehlscontroller.
- **HUD-02 P0:** Gemeinsamer NativeMapCanvas und
  reversible Spiel-/Editoransicht nachgewiesen,
  Spieloberfläche als Ganzes noch nicht abgenommen.
- **MAP-01 P0:** Pausierter Engine-Snapshot,
  Shader-/Wasser-/Zeit-/Kameravergleich mit
  synchronisierten Originalaufnahmen offen.
- **PIPE-01 P0:** Historische Juni-Werkzeugversionen,
  Pipelines, Ausgaben und reproduzierte Hashes offen.
- **UI-01 P1:** Echtes Windows-DPI über mehrere
  Monitore, Screenreader, Fensterfokus und
  Alltagsszenarien offen.

**Gesamturteil:** Ein neuer, klar messbarer Schritt
zur HUD-Formtreue mit echten Bedienwegen und
getrennten Nachweisen. Keine exakte Original-HUD-
oder vollständige Sprite-Suite-Abnahme.

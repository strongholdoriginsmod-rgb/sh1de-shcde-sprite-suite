# Sprite Suite – Sandbox-HUD: Aktions- und Kartenzustandsintegrität

**Stand:** 14.10.2026 – Fortsetzung der UI-/Pipeline-Paritätsprüfung  
**Branch:** `feature/sandbox-studio`  
**Qualitätsaussage:** Gezielte Arbeitsabläufe nachgewiesen; **keine** HUD-01-, MAP-01- oder PIPE-01-Gesamtabnahme.

## Warum diese Änderung notwendig war

Im eingebetteten Spiel-HUD waren `Rückgängig`, `Wiederholen` und
`Sichern` auch ohne passenden Verlauf oder ungespeicherte Änderung
aktiv. Der bisherige `Platzieren`-Knopf zeigte nicht, ob bereits ein
Sprite vorgemerkt war. Bei Katalog → Sandbox konnten zudem das
aktuelle Karten-Platzierungsziel und die im seitlichen, für den Nutzer
unsichtbaren Funktions-HUD gewählte Gruppe/Framenummer auseinanderlaufen.

Auch nach einem gescheiterten nativen Kartenimport ließ der alte
Fehlerpfad möglicherweise Engine-/Minikarten- und GUI-Zustände der
vorherigen Karte sichtbar. Ein geladenes Radar beweist aber keine
native Originalkarte und darf weder Speichern noch Platzieren
autorisieren.

## Implementierte Schutz- und Bedienregeln

- `tools/sandbox_gameplay_context.py` bietet das reine,
  Qt-unabhängige `GameplayActionState`-Datenmodell.
  `can_undo`/`can_redo` stammen aus den echten
  `OverlayHistory.undo_stack`/`redo_stack`. `can_save`
  vergleicht die aktuelle Arbeitskopie mit `SandboxStudio._saved_overlay`.
  Bei unbekannter Baseline oder fehlender nativer Karte ist Speichern
  **nicht autorisiert**. Ungültige/leer eingegebene Sprite-Gruppen
  aktivieren keine neue Platzierung.
- `tools/sandbox_native_canvas.py`: `placement_changed`-Signal
  und `cancel_placement()`. Derselbe Abbruchweg wird über die
  Escape-Taste oder die dynamische untere HUD-Schaltfläche aufgerufen.
  Der Abbruch verwirft **keine** platzierten Arbeitsobjekte,
  verändert **keine** Originalkarte und löst **keinen** Save aus.
- `tools/sandbox_gameplay_mode.py`: Der Knopf wechselt reversibel
  zwischen `Platzieren` und `Abbrechen` bzw. `Place`/`Cancel`.
  Sein Tooltip enthält die tatsächlich vorgemerkte Gruppe und
  Framenummer, beispielsweise `tree_pine/20`. Undo, Redo
  und Save folgen dem tatsächlichen Zustand und haben
  sinnvolle Deaktivierungshinweise.
- Eine von der Tk-Suite oder einem XAML-Command veranlasste
  `NativeMapCanvas.arm_placement(group, frame)`-Aktion gleicht
  die versteckte Funktions-HUD-Gruppe **mit exakt diesem Frame**
  ab. Nach dem Abbrechen wird daher nicht versehentlich das
  zuvor gewählte Arbeits-Sprite erneut scharfgeschaltet.
  Die Auswahl wird innerhalb der Qt-Reaktion blocksignaliert
  synchronisiert, ohne ein zweites Platzierungsereignis auszulösen.
- `tools/sandbox_studio.py`: `overlay_state_changed`
  meldet nach gesicherter Arbeitskopie beziehungsweise neuem
  Karten-Baseline-Vertrag die verfügbaren Aktionen neu.
  Strg+S und das HUD nutzen weiterhin den originalen
  `save_map_overlay`-Sicherheitsweg; keine zweite Speicherung
  oder Installationslogik.
- **Negativer Ladeweg:** Scheitert die native Kartendekodierung,
  während der Radar-Preview noch gelesen werden kann, werden
  alte Karten-Engine, Canvas-Quelle, History, Sprite-Auswahl,
  Cursor, Platzierung und native Minikarte bereinigt.
  `placement_changed`, `modified` und
  `overlay_state_changed` aktualisieren das UI danach auf
  *keine native Karte, keine Bearbeitungsfreigabe*.
  Ein späteres erfolgreiches Neuladen ist ohne Neustart möglich.

## Testmatrix (getrennte Beweisaussagen)

| Ablauf | Prüfung | Ergebnis |
| --- | --- | --- |
| Kein nativer Kartenstand | Platzieren/Undo/Redo/Save gesperrt, DE/EN stabil | Bestanden |
| Originalkarte geladen, aber clean | Undo/Redo/Save gesperrt, Platzieren erlaubt | Bestanden |
| Aktive Platzierung | Schaltfläche zeigt Abbrechen, behält group/frame, Cancel/Esc synchron | Bestanden |
| Temporäre Overlay-Änderung | Undo aktiviert, Save aktiviert, Redo erst nach Undo | Bestanden |
| Undo zum gespeicherten Baseline-Stand | Save deaktiviert, Redo aktiviert | Bestanden |
| Tatsächliches Speichern | Nur `tmp_path/hud-working.overlay.json`; nach Save wieder clean | Bestanden |
| Erneutes Undo nach Save und Redo | Dirty-Status wird korrekt zurückgenommen | Bestanden |
| Katalog → Game HUD → Cancel → Place | `tree_pine/20` bleibt exakt erhalten | Bestanden |
| Zwei reale Originalkarten | Antioch → Crusader Demo → Antioch; HUD-Auswahl/Undo/Save frisch | Bestanden |
| Absichtlich fehlgeschlagene native Dekodierung | Nur Radar bleibt; kein altes Speichern/Platzieren | Bestanden |
| Wiederherstellung nach Ladefehler | Originalkarte erneut geöffnet, Engine und Minikarte wieder nutzbar | Bestanden |
| Tatsächliche Tk-/Qt-Windows-Einbettung | Vorhandene UI-Aktionen und eingebettetes HUD bei zwei Größen | **QA_PASS** |

**48 kombinierte gezielte Python-/Qt-Tests bestanden** (Dateien:
`test_gameplay_context_states.py`,
`test_gameplay_mode_workspace.py`,
`test_sandbox_compact_layout.py`,
`test_hud_compact_workflow.py`,
`test_hud_composition.py`,
`test_native_engine_seams.py`). Diese Zahl ist **nicht**
der vollständige 609+-Regressionstestbestand.

Der reale Windows-Suite-Test `tools/qa_suite_embedded.py`
meldete `QA_PASS`, einschließlich
`CATALOGUE_GAME_HUD_PLACEMENT_SYNC_PASS`,
`NATIVE_ORIGINAL_SELECTION_READONLY_PASS` und
`GAMEPLAY_NATIVE_LAYOUT_PASS` bei 1500×930 und 1020×680.
Der echte Platzieren/Undo/Redo-Maustest
`work/qa_gameplay_interaction_oct14.py` meldete
`GAMEPLAY_CLICK_UNDO_REDO_QA_PASS`.
Die echte Zwei-Karten-Prüfung
`work/qa_gameplay_map_transition_20261014.py` meldete
`GAMEPLAY_MAP_RELOAD_QA_PASS`.

## Quellen, Belege und Hashschutz

**Originale wurden ausschließlich gelesen**, nicht geändert,
installiert oder paketiert:

- `Antioch.map`:
  `c0b4317d3d708f721b5a0b27f04d2f2114063b3f587d04985fd7ca2d0ad6ff51`
- `Crusader Demo.map`:
  `6e2e01cddea9d74cb5fbec0c3be1d3b8f5f04875e21c101bed2a404c9e78c469`

Quelle lokal:
`E:/SSGameQA/Stronghold Crusader Definitive Edition_Data/StreamingAssets/Maps/`.

Maschinenlesbare Karte-A→B→A-Quelle-und-Zustands-Prüfung:
`work/reports/ui-audit/gameplay-real-map-transition-20261014.json`.
Native Win32-Bildprüfung:
`work/reports/ui-audit/suite-embedded-gameplay-1500x930.png`.
Der Screenshot zeigt nach einer wirklichen Kataloganbindung
`Abbrechen` neben den Spielicons und der echten Minikarte,
nicht ein fingiertes statisches Gameplay-HUD.

`git diff --check` der in dieser Arbeitsrunde gezielt editierten
Python-/Qt-Dateien: keine neuen Whitespace-Probleme.
Git-HEAD vor und nach diesen Arbeiten `00276ec`;
bereits bestehende uncommittete Arbeiten bewusst erhalten und
**nicht** als gesamtes fertiges Release eingecheckt.

## Offene Abnahmeblocker

- **HUD-01 P0:** Rechtsseitige Spiel-Berater-/Porträtzustände,
  vollständige Ressourcen-/Wirtschaftslogik, originale GUI-Rahmen,
  Animationen und Noesis/Unity-State-Verträge nicht rekonstruiert.
  Die nun konsistenten Werkstattaktionen sind keine originalen
  Spiel-Baubefehle.
- **MAP-01 P0:** Der echte Kartenkern bleibt ein pausierter
  Runtime-Snapshot; Shader-, Wasser-, Zeit- und Kameraparität
  gegen die vier historischen Originalspielbilder offen.
- **PIPE-01 P0:** Ursprüngliche Juni-Toolchain, Versionspins,
  Kommando-/Abbruchverträge und identische Buildausgaben ungeprüft.
- **UI-01 P1:** DPI-/Screenreader-/Langzeitsitzung und vollständige
  Bedienaufgaben vor Release noch nicht abgenommen.

**Gesamturteil:** Die Zustandsintegrität des integrierten HUDs ist
erheblich besser geprüft. Das ist eine nachgewiesene Teilkorrektur,
keine 1:1-Sprite-Suite-Gesamtabnahme.

# Nachprüfung Sandbox Studio — 10. Oktober 2026

## Prüfgegenstand und Ergebnis

**Umgebung:** Windows-PC `DESKTOP-O008GV9`; Projekt
`E:\SpriteSuite`; Branch `feature/sandbox-studio`; Ausgangscommit
`899eb12`.

Es handelt sich um eine **erneute Quellcode-, Qt-Offscreen- und
Originalkartendaten-Prüfung**, nicht um einen Nachweis eines pixelidentischen
Stronghold-Crusader-DE-Renderers.

### Nachprüfungen

| Prüfung | Konkretes Ergebnis | Aussagekraft |
|---|---|---|
| Git-Arbeitsverzeichnis und Commit | Ausgangscommit `899eb12`, Branch `feature/sandbox-studio`, keine vorherigen ungespeicherten Codeänderungen | Vorheriger Git-Bericht bestätigt |
| Vollständige Sandbox-Tests vor Korrekturen | **80 bestanden** | Automatische Tests, nicht alle GUI-Workflows |
| Vollständige Sandbox-Tests nach Korrekturen | **83 bestanden** | Neue Live-Reload- und Dialog-Lifecycle-Regressionstests |
| Originalkartentest | `Antioch.map` geladen: **1.139 Vegetationsdatensätze**, **27 Gebäudedatensätze** | Gegen tatsächlich vorhandene Spielkarte geprüft |
| Originalgrafik-Layer | Baum-Rohgruppe 31 mit `tree_birch/0` testweise verbunden; **10 QGraphicsPixmapItem-Objekte** mit echten, nicht leeren Atlas-Pixmaps erzeugt | Benutzerdefinierte Bildzuordnung, nicht als originale Engine-ID verifiziert |
| UI-Funktionen | Kartenreiter sichtbar; Pixeleditor und Bildvergleich geöffnet; Original-Radarkarte 200 px breit; Radar-Navigation ausgelöst | Automatischer Qt-Offscreen-Praxistest, keine vollständige manuelle Spielsession |
| Overlay über Menübefehl | `Karten-Overlay speichern` tatsächlich ausgelöst, Datei unter `work\verify_20261010.overlay.json` geschrieben | Menüanbindung bestätigt |
| Spielkarte unverändert | SHA-256 von `Antioch.map` vor/nach dem E2E-Test identisch | Originaldatei wurde durch diesen Test nicht verändert |
| Pixelvergleich | Identische Screenshot-Daten liefern MAE 0.0 und 0.0 % Fehler | Rechenalgorithmus bestätigt; **kein echter Spiel-Screenshot-Abgleich** |
| Visuelle Darstellung | Screenshot `work\verify_20261010_actual_mapping.png` kontrolliert | Terrain wirkt sichtbar künstlich; Pixelidentität mit Spiel **nicht** bestätigt |

### Aufgedeckte und behobene Defekte

1. **Sofortige Terrain-Aktualisierung:** `SandboxStudio._update_map_asset`
   hatte die Textur- und Signatur-Caches gelöscht, aber die bereits
   gerenderten Karten-Chunks **nicht**. Reproduktion: vor Signal 20
   gecachte Chunks, nach Signal immer noch 20. Die neue Methode
   `NativeMapCanvas.refresh_terrain_assets` leert ausdrücklich alle
   betroffenen Caches und setzt die Spritequelle zurück. Dieselbe
   Reproduktion zeigt nach dem Signal 0 Chunks. Der neue Regressionstest
   überprüft dies mit der echten Karte.
2. **Lebenszyklus des Pixel-Editors:** Ein geschlossenes Dialogfenster
   blieb in `SandboxStudio._pixel_dialogs` referenziert. Der Dialog
   sendet jetzt bei akzeptiertem Schließen ein `closed`-Signal und
   wird aus der Liste entfernt. Der Qt-Test und der unabhängige E2E-Test
   bestätigen nach dem Schließen 0 offene Dialoge.
3. **Gemappte Original-Sprites:** Ein Grafikspeicher-Signal aktualisiert
   jetzt auch Zuordnungen zu echten Originalgebäuden und -bäumen,
   nicht nur frei platzierte Overlay-Objekte. Ein Regressionstest
   kontrolliert den Aufruf.

### Strikte Grenzen

- `native_tile_material()` ist eine **vorläufige Code-zu-Material-
  Heuristik** und verwendet deterministische Beispiel-Frame-Indizes;
  Terrainhöhe, Wasser, Küsten, Wege, Gebäude-Skin-/Footprint-Auflösung,
  Wetter und Shader sind nicht 1:1 rekonstruiert.
- Das Spiel-HUD ist ein **selbst gebautes Test-HUD** aus Qt-Widgets,
  kein pixelgenau reproduziertes originales Stronghold-/Noesis-HUD.
- Originalbauwerke und -vegetation sind positionsgetreu erkannte
  Rohdatensätze; tatsächliche Spielgrafik wird nur dort gezeigt, wo
  eine separate lokale Zuordnung gewählt wurde.
- Ein Abgleich gegen einen **wirklichen Screenshot aus laufendem
  Crusader DE** mit exakt gleicher Kamera/Zoom und UI wurde bei dieser
  Nachprüfung nicht ausgeführt. Die aktuelle Testabdeckung darf
  nicht als optischer Paritätsnachweis ausgegeben werden.
- Der E2E-Test läuft mit `QT_QPA_PLATFORM=offscreen`, was sich von
  einer vollständigen manuellen Windows-Sitzung unterscheidet.

### Wiederholbare Befehle

```powershell
cd E:\SpriteSuite
$env:PYTHONPATH='E:\SpriteSuite\src'
$env:QT_QPA_PLATFORM='offscreen'
.\.venv\Scripts\python.exe -m pytest -q tests\sandbox
.\.venv\Scripts\python.exe .\work\audit_20261010_e2e.py
.\.venv\Scripts\python.exe .\work\audit_20261010_cache.py
```

**Fazit:** Die geprüften Editor-Grundfunktionen existieren und sind
funktionsfähig. Die Behauptung einer endgültigen, spielgenauen Sandbox
wäre momentan nicht gerechtfertigt.

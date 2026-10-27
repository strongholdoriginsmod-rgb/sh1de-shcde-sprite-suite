# Sprite Suite – HUD-Rendergrafik mit prüfbarem Quellennachweis

**Datum:** 15. Oktober 2026  
**Projekt:** `E:\SpriteSuite`, Branch `feature/sandbox-studio`  
**Status:** Begrenzte, funktionierende Teilrekonstruktion – **keine HUD-/Shader-/Produktionsfreigabe**.

## Ziel und gemessener Ausgangsbefund

Die vier Originalspielbilder vom September zeigen dynamische Bildbereiche
rechts im Spiel-HUD. Bisherige Testleisten hatten dort nur Textauswahl
oder statische Dekoration. Eine Übernahme historischer Screenshots
als angeblich lebendes Beraterporträt wäre irreführend.

Ein rein lesender Realmap-Probelauf mit `Antioch.map`
ergab **1.863 bereits im Qt-Renderer vorhandene Pixmap-Cacheeinträge**
während der getesteten Szene. `tree_cactii/1` und mehrere
Terrainframes waren über reale `EngineSpriteHit`-Referenzen erreichbar.
Das belegt verfügbare *gerenderte* Pixel, nicht den unveränderten
Original-Unity-Assetstatus jedes einzelnen Frames.

## Implementierung

- `tools/sandbox_gameplay_artwork.py` (neu):
  `selection_artwork(canvas, kind)` liest Pixel **nur** aus
  einer gegenwärtig ausgewählten `NativePlacedSprite`-Instanz
  oder dem Cache der aktiven `NativeCommandRenderer`-Instanz.
  Die Lookup-Funktion ruft weder `_pixmap()` noch UnityPy,
  Atlas-Export, Dateisuche oder Netzwerkroutinen auf.
- Der Engine-Cachetreffer erfordert exakt passenden
  `(group,frame,light,float_colour)`-Schlüssel, dieselbe
  Canvas- und Runtime-Snapshot-Identität und aktiven
  Engine-Anzeigemodus. Der Herkunftshinweis unterscheidet
  expliziten `original_only`-Quellenmodus und gemischte
  lokale Arbeits-/Kataloggrafiken. Ein Frame-Cacheeintrag
  ist **keine** Quelle für andere Objekte mit vermeintlich
  gleichem Typ.
- `tools/sandbox_native_canvas.py`: Die vorhandenen
  Overlay-QGraphicsItems merken, ob tatsächlich ein Frame
  geladen wurde. Ein pinker Platzhalter bei fehlender
  Ressource wird **nicht** als Grafikvorschau freigegeben.
- `tools/sandbox_gameplay_mode.py`: Neuer `G`-Knopf
  im schmalen grünen Befehlsstreifen öffnet eine dritte
  rechte Ansicht mit **kleiner dynamischer Spritevorschau**,
  Frameidentität und vollständiger Quellenangabe als
  Tooltip/AccessibleName. `M`, `i` und der Inspector
  bleiben an dieselbe Karte und Minikarte gebunden.
  Das Bild wird lediglich im Speicher auf die kleine
  Anzeige skaliert; keine Arbeits-/Originalpixel werden
  gespeichert, ersetzt oder als historische Porträts ausgegeben.
- Rohcodierte Originalgebäude aus Sektion 1013, Vegetation
  aus Sektion 1014 und Bodenwerte haben ausdrücklich
  **keine angenommene Typ-zu-Sprite-Zuordnung**. Bei diesen
  Auswahlzuständen ist `G` gesperrt, und ein eventuell
  zuvor angezeigtes Bild wird gelöscht.
- Beim Rückgängig, Kartenwechsel, Engine-Cachewechsel
  oder gelöschtem Overlay wird ein veraltetes Vorschaubild
  nicht wiederverwendet. Ein expliziter M-/G-/Info-Klick
  überstimmt einen bereits wartenden älteren Qt-Auswahlwechsel.
- Der tatsächliche Karten-Renderer kann im Zuge der
  regulären Bildvorschau seinen Cache neu aufbauen.
  Nach einem Engine-Pick wird deshalb **einmalig**
  nach 75 ms der Cache erneut *lesend* kontrolliert,
  wenn die Grafik beim ersten Auswahlereignis noch fehlte.
  Kein dauerhaftes Polling, kein implizites Sprite-Exportieren.

## Nachweise auf der echten, nicht veränderten Karte

Quellkarte:
`E:\SSGameQA\Stronghold Crusader Definitive Edition_Data\StreamingAssets\Maps\Antioch.map`

SHA-256 vor und nach dem QA-Durchlauf identisch:
`c0b4317d3d708f721b5a0b27f04d2f2114063b3f587d04985fd7ca2d0ad6ff51`

`work/qa_hud_rendered_art_20261015.py` erzeugt ausschließlich
QA-Dateien unter `work/reports/ui-audit`.
Es wählte einen echten bereits gecachten Engine-Snapshot-Treffer
und setzte ein Arbeits-Overlay rein flüchtig; nach Undo stimmt
die Overlay-Serialisierung wieder mit dem Anfangszustand überein.
Ergebnis: **HUD_RENDERED_ART_PROVENANCE_PASS**.

- `hud-rendered-art-engine-cache-1168x542.png`: Anzeige von
  `tree_cactii/1` mit gemischtem Renderquellen-Hinweis.
- `hud-rendered-art-original-type-unmapped-1168x542.png`:
  ein echtes Originalgebäude wurde ohne hypothetisches
  Porträt oder Spritebild selektiert.
- `hud-rendered-art-working-sprite-1168x542.png`:
  `tree_pine/20` zeigt seine gegenwärtig dargestellte
  Arbeitsgrafik; kein Originalspiel-Assetanspruch.
- `hud-rendered-art-provenance-20261015.json`:
  Schema-, Frame-, Tooltips-/Herkunfts- und Bild-SHA-Daten.
- `work/qa_hud_selection_asset_sources_20261015.py`:
  separater lesender Nachweis der ursprünglich 1.863
  Rendercache-Einträge im getesteten Karten-/Zoomzustand.

## Verifikation

- `tests/sandbox/test_gameplay_artwork_cache.py`:
  Kein fiktives Bild für Roh-Typen, kein Cachetreffer bei
  fremdem Renderer/Snapshot, leeren oder falschen Pixmaps,
  nicht geladenen Overlay-Pixeln oder fehlender Karte.
- `tests/sandbox/test_gameplay_mode_workspace.py`:
  Echte Bitmap-Auswahl, M/G/Inspector-Wechsel,
  Sprachumschaltung, Undo/Clear und kein Ghost-Bild.
  Ein zunächst aufgetretener Render-Timing-Fehler
  ist mit dem einmaligen Cache-Abgleich abgesichert.
  Die realmap-Testfixture verwirft flüchtige Änderungen
  beim Testabbruch nun ohne blockierenden Offscreen-Dialog
  oder Dateischreibvorgang.
- **65 kombinierte Qt-/Python-Regressionstests bestanden**
  (inklusive vorhandener Karten-, HUD-, native Engine-
  und gemessener HUD-Chrome-Prüfungen).
- Simulatorischer Qt-Skalierungstest 125 % und 150 %:
  vier bestehende HUD-/Minikartenfensterkombinationen
  bestanden, einschließlich des im Ruhezustand korrekt
  gesperrten zusätzlichen Grafikknopfs.
  **Keine** systemweite Multi-Monitor-/Screenreader-Abnahme.
- Native Windows-Suite `tools/qa_suite_embedded.py`:
  **QA_PASS**, einschließlich **NATIVE_CACHED_ARTWORK_HUD_PASS**.
  Die tatsächlich eingebettete Tk-/Qt-Kindfensteransicht zeigt
  einen gecachten `tree_cactii/1`-Frame mit vollständiger
  Identität; danach ist die reale Minikarte wieder erreichbar.
  `work/reports/ui-audit/suite-embedded-cached-artwork-1500x930.png`
  ist der auf dem Windows-Desktop aufgenommene Bildnachweis.
  Bei 1020×680 wurde die bestehende HUD-Einbettung ebenfalls
  bestätigt. Die Engine-Trefferquelle für diesen nativen Test
  war der geladene Frame-Cache, kein unabhängig durchgeführter
  Pixelabgleich zum historischen Originalspiel.

## Weiterhin offene kritische Blocker

**HUD-01:** Weder originale dynamische Beraterporträts noch
Spielwirtschaft, Baubedingungen, UI-State-Machine,
Animation oder shadergetreue Rahmen sind dadurch bewiesen.
Der neue G-Knopf ist ein *Sprite-Suite-Arbeitswerkzeug*,
kein vom Stronghold-Spiel zurückgewonnener Originalbefehl.

**HUD-02:** Spiel-/Editorzustände bleiben teilweise nachgewiesen,
keine vollständige Alltags- oder Originalparität.

**MAP-01:** Engine-Stand ist pausiert; Kamera-/Zeit-/Shader-
und Pixelgleichheit zu historischen Spielbildern offen.

**PIPE-01:** Kein neuer Nachweis der Juni-Originaltools,
Abhängigkeiten, Konfigurationen und Pipeline-Ausgabehashes.

**UI-01:** Reale Windows-DPI-, Screenreader- und lange
Bedien-/Sitzungstests sind weiter offen.

Die vier alten Originalaufnahmen sowie originale Unity-/Map-
Dateien wurden nicht umgeschrieben. Der umfangreiche,
bereits vorbestehende uncommittete Git-Arbeitsstand
wurde nicht zurückgesetzt, zusammengeführt oder als
fertiges Release eingecheckt.

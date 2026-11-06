# SHCDE: echte Gebäude-/Sprite-Layer und Renderer-Kanarie

Stand: 06.11.2026, lokaler QA-Entwicklungszweig `qa/shcde-damage-map-load-20261106`, Grundlage `0dd2458`.

## 1. Reale Spielmessung

Die isolierte, markierte Spielkopie `E:\SSLiveGame_20261105` wurde mit unveränderten, SHA-verifizierten SHCDESE- und Game-Assemblies gestartet. Der vorhandene Spielstand `Kratersee-16.sav` wurde als eigene Testkopie geladen. Die Originalquelle und weitere 33 Spielstände wurden vor und nach dem Lauf überprüft; alle 34 stimmen byteweise mit der Sicherung überein.

Die Protokolldatei `E:\SpriteSuite_FinalAudit_20261106\LiveGameQA\CorrelatedTileLayer_20261106.log` (SHA-256 `f6d4bf905053b16cbcb4facbc22bec057277a6623ffe98ea79e9bbf94bfa6cee`) enthält:

- 240 tatsächliche `SpriteMapping.setGenericBuildingTileGraphic`-Aufrufe mit GameBuilding-Identität und GameSprite-`gm/image`.
- 80 `GameBuildingManagerAPI.GetOccupiedTileIds`-Footprints.
- 12 gezielte Abfragen der entsprechenden GameMap-Tiles nach abgeschlossener Grafikinitialisierung.
- **132** Grafik-Events für Kacheln innerhalb des nativen Belegungsrasters, **108** für Kacheln außerhalb der nativen Belegung.
- Die direkt mit `GameMap.getMapTile` abgefragten Sprites waren hauptsächlich `tile_land_macros`/andere Gelände-Sprites, nicht die Gebäudelayer. `tilemapRef.GetSprite(x,y)` ergab auf diesen Koordinaten null.
- Die ursprünglichen Gebäude-Graphic-Hooks lieferten dagegen Sprite-Familien `tile_buildings1`, `tile_buildings2` und `tile_goods`.

**Architekturfolge:** Gameplay-Footprint, GameMap-Grundlayer und Gebäude-Grafiklayer dürfen nicht als dieselbe Tilemenge behandelt werden. Insbesondere dürfen die 108 außerhalb des Belegungsrasters gezeichneten Gebäude-Bildteile nicht verloren gehen. Der tatsächliche Hook `SpriteMapping.setGenericBuildingTileGraphic` ist die geeignete Ausgangsstelle für weitere, nachweisbare per-Instanz-Rendererzuordnungen, nicht das globale Überschreiben von Gelände-Tiles.

Zur reproduzierbaren Offline-Auswertung existiert `tools/building_damage_layer_audit.py`. Beispiel:

```powershell
python tools/building_damage_layer_audit.py --log "E:\SpriteSuite_FinalAudit_20261106\LiveGameQA\CorrelatedTileLayer_20261106.log" --expected-sha256 f6d4bf905053b16cbcb4facbc22bec057277a6623ffe98ea79e9bbf94bfa6cee
```

Die vollständige maschinenlesbare Auswertung steht unter `E:\SpriteSuite_FinalAudit_20261106\LiveGameQA\CorrelatedTileLayer_20261106_audit.json`. Sie enthält getrennte Gebäude-IDs, Grafik-, Footprint- und Grundlayer-Evidenz und erteilt **keine** unbelegte Renderfreigabe.

## 2. Tatsächlicher ein-Kachel-Kanarientest

Es wurde über `tools/qa_building_damage_live.py --qa-canary` ausschließlich im isolierten QA-Klon eine zusätzliche, **explizit schreibende** Kompilierungsoption aktiviert. Die Standard-Pluginfassung bleibt read-only. Alle QA-Pfade, Engine-/SE-DLLs und die Testkopie des Spielstands waren dabei prüfsummengebunden. Die Testkomponente verändert höchstens eine Grafik-Kachel kurz und ruft danach die ursprüngliche Engine-Methode zur Wiederherstellung auf.

Erster Live-Lauf (Log `SingleSpriteCanary_20261106.log`, SHA-256 `ea2211243346544e85810d0b9199aaf037edf9d0eeca98fb5b7bb427a281f857`):

- Gebäude **77**, Global-ID **661027**, Tile-ID **17866**.
- Sprite `tile_buildings1 504` wurde durch `tile_buildings1 501` derselben Grafikfamilie ersetzt.
- Nach dem beschränkten Frame-Budget Originalsprite wiederhergestellt: `original_restored=True`, `writes=2`.
- Protokollierter `Application.quitting`-/Harmony-Rückbau mit `sprite_writes=2`.

Zweiter Live-Lauf, strengere Identitätsprotokollierung (Log `StrongCanary_20261106.log`, SHA-256 `a7af59bf0ca7e7e3877361631b553bd9dc80deedf0e7239e4f59021154de9a07`):

- **Dieselbe** Gebäude-ID 77, Global-ID 661027 und Tile-ID 17866 beim Schreiben und Wiederherstellen.
- `original_restored=True`, `writes=2`, null Lese-Fehler.
- Dieser zweite Prozess endete ohne dokumentiertes `Application.quitting`. Die strenge Auswertung unterscheidet deswegen `qaCanaryTileRestoredVerified=true` und `qaCanaryCleanShutdownVerified=false`. Beide Wahrheitswerte bleiben sichtbar und werden nicht als pauschaler Erfolg überschrieben.
- Bei beiden Läufen wurde das Plugin nach Prozessende vollständig und prüfsummenkontrolliert deinstalliert. Die angelegte Testkopie wurde ebenfalls anhand des SHA-256-Werts entfernt. Keine dauerhafte Spiel-, Spielstand- oder Shaderänderung.

Damit ist für eine einzelne Instanz die **technische Rebind-/Restore-Fähigkeit** im wirklichen SHCDE-Spiel bestätigt. Weder eine lückenlose visuelle Bildabnahme noch die vollständige HP-/Feuer-basierte Bildfolge ist damit bereits bewiesen.

## 3. Funktionsumfang und weiter offenes Release-Gate

**Bereits bestanden:** SHA-gebundene Codex-/SpriteSuite-Asset- und Schadenspaket-Workflows, getrennte mechanische und Feuer-HP-Schwellen, SpriteSuite-Tile-Overlap, Offline-C#-Selektor, echtes Spielevent-/Tile-/Grafiklayer-Monitoring und ein vollständig rücksetzbarer Einzelkacheltest.

**Für vollständige Freigabe noch erforderlich:**

1. Eine vom Benutzer freigegebene, originale Gebäudemodellreihe mit tatsächlich dazugehörigen PNG-Tiles für die konkret im Spiel ermittelte `gameBuildingType`-ID.
2. Die vollständige Zuordnung der **grafisch** gezeichneten Tiles (einschließlich der Bildteile außerhalb des Gameplay-Footprints) zu den SpriteSuite-Slots und deren Reihenfolge/Rotation; bloßes `GetOccupiedTileIds` reicht nicht.
3. Die überprüfte Übernahme der Stage-Sprites (RGBA, Pivots, PPU, Höhen, Teamfarbe und Materialmasken) in die Unity-Assetlebensdauer.
4. Die automatische Auswahl bei tatsächlichen HP-Änderungen, aktivem Brand, Reparatur, Zerstörung, Map-Reload und wiederverwendeten Gebäude-IDs.
5. Visuelle In-Game-Abnahme gegen die originalen Ruinen/Abtei-Bilder, einschließlich Seam-/Bilinear-/Transparenzkontrolle und vollständigem Vanilla-Rollback.
6. Erst danach einen aktiven, standardmäßig installierbaren Schadens-Renderer über einen versionsgebundenen Funktionsschalter freigeben.

Die QA-Kanarie selbst wird in den Quellstand aufgenommen, jedoch **nicht** automatisch ins Spiel installiert oder als fertige Schadensmodell-Umschaltung bezeichnet.

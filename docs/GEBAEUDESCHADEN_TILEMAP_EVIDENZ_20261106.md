# SpriteSuite: konkrete Tilemap-Sprite-Zuordnung als nächster Modding-Schritt

Stand: 6. November 2026; isolierte Quelle `feature/spritesuite-render-evidence-20261106`, Basis `0dd2458`.

## Warum die Erweiterung nötig ist

Der ältere isolierte QA-Spielstand `AutoLoadedKratersee_20261106.log` enthält 240 `tile_graphic`- und 80 `building_footprint`-Ereignisse, aber **null** Paare mit derselben Gebäude-ID, Global-ID und passender Tile-Position. Daraus kann weder die Reihenfolge des Grafikrasters noch ein tatsächlich dargestelltes Tilemap-Sprite belegt werden. Selbst die in `0dd2458` nachgewiesene IL-Kette `GameMapTile.tileImage` → `TileData.set_sprite` beweist keine sichtbare, instanzbezogene und rücksetzbare Schadensdarstellung.

## Neue rein lesende QA-Quelle

Der separate Quellcode `runtime/StrongholdEuropeDE.BuildingDamage.LiveAudit/BuildingDamageLiveAudit.cs` liest nun – ergänzend zur vorherigen Footprint- und SpriteMapping-Diagnose – die konkrete `GameMapTile.tileImage`-Referenz und `GameMapTile.tilemapRef.GetSprite(Vector3Int)`.

- Im bereits existierenden `tile_graphic`-Ereignis wird die zusätzliche Eigenschaft `tilemap_sprite` samt Name, Pixelabmessungen und PPU ausgegeben.
- Für erstmals beobachtete Gebäudeinstanzen mit gültigem Footprint folgt `building_render_tiles`. Enthalten sind `building_id`, `global_id`, Typ, Tilezahl, Zahl abgetasteter Tiles und `samples` in der Form `Tile-ID:X,Y:tileImage~Breite×Höhe~PPU:tilemapSprite~Breite×Höhe~PPU`. Die Diagnose lässt alle Gebäudetypen und Rasterformen grundsätzlich zu; aus Gründen des übersichtlichen Logs werden bis zu 64 Tiles pro Gebäude und 40 verschiedene beobachtete Instanzen protokolliert.
- Es werden nur Referenzen gelesen. Es gibt keine `SetSprite`, `SetTile`, `RefreshTile` oder Sprite-Zuweisungen und keine automatische Kartenladung. Kann eine einzelne Tilemap ihre Sprite-Referenz nicht liefern, wird dieser Lesefehler protokolliert; die unabhängig erfasste Original-`tileImage`-/SpriteMapping-Information bleibt trotzdem erhalten.
- Der vorhandene `qa_building_damage_live.py --build-only` bindet für die reine Kompilation die Unity-Module `TilemapModule` und `GridModule`. Ein Testbau gegen den markierten separaten QA-Spielklon mit den bereits geprüften Script-Extender-/Game-DLLs ist erfolgreich. Diese Prüfung installiert nichts und ist ausdrücklich kein Runtime-Pixelergebnis.

## Auswertung ohne Spielzugriff

`tools/building_damage_render_evidence.py` ist eine reine Datenfunktion. Sie erweitert den bestehenden Aufruf:

```powershell
python tools/qa_building_damage_live.py --qa-root E:\SSLiveGame_20261105 --verify-log "E:\Pfad\zu\LogOutput.log"
```

Die Ausgabe unterscheidet:
- direkte `tilemap_sprite`-Sichtungen und Namensabweichungen zu `tileImage`;
- echte Übereinstimmungen der Gebäude-/Global-ID zwischen Grafik- und Footprint-Ereignissen;
- identische Tile-ID **und** X/Y-Position zwischen Footprint, SpriteMapping und Tilemap-Leseprobe;
- gemeinsame Tiles und Gebäude mit zusätzlicher tatsächlich belegter Tilemap-Sprite-Referenz;
- getrennte Protokollsegmente bei protokolliertem Kartenladebeginn, erneutem Start oder Reset, damit gleichnamige IDs nicht pauschal über Karten hinweg kombiniert werden.

`readOnlyTilemapCandidateObserved` bedeutet ausschließlich eine belastbare **lesende Referenzbeobachtung**. `liveGraphicMappingProved`, `visualReplacementVerified`, `rendererReplacementProved` und `inGameFullDamageSwitchingProved` bleiben falsch. Für die echte SpriteSuite-Modifikation sind Slotgeometrie, Pivots, Masken, Layer, Kartenübergänge, Live-HP und tatsächliche Anzeige im Spiel noch separat nachzuweisen.

## Prüfstand und offene Arbeit

- Kompilation des erweiterten C#-Beobachters als **isolierte DLL**, ohne Installation, auf der zuvor markierten QA-Spielkopie: bestanden.
- Gezielte Python-Regressionen der Parser- und bisherigen Live-Plugin-Verträge: bestanden (20/20).
- Rückwärtige Auswertung von `AutoLoadedKratersee_20261106.log` und `StaticObserverSuccess_20261106-172451.log`: keine neuen Tilemap-Ereignisse vorhanden; keine Grafikzuordnung erfunden.
- Das parallele, uncommittete QA-Experiment `E:\SpriteSuite_DamageGameMapQA_20261106` enthält zusätzlich eine mögliche automatische Ladung einer kopierten Testkarte. Diese experimentelle Kartenladefunktion wurde hier **nicht übernommen**, da sie keine normale Editorfunktion ist und ein laufender QA-Spielprozess parallel existiert. Die reine Tilemap-Leselogik wurde unabhängig implementiert und kompiliert.

Nächster echter Nachweis: Im isolierten QA-Spiel auf einer real geladenen Karte die neuen Ereignisse sammeln, mit dem Auswerter konkrete Gebiets-/Instanz-/Spritepaarungen erzeugen, dann einen separat aktivierbaren per-Instanz-Schadensrenderer mit Rückkehr zur intakten Grafik für Reparatur und Kartenwechsel entwickeln.

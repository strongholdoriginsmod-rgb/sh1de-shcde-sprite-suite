# SHCDE Gebäudeschaden – echter In-Game-QA-Start, 06.11.2026

Implementiert: `runtime/StrongholdEuropeDE.BuildingDamage.LiveAudit/BuildingDamageLiveAudit.cs` als separater, **nur lesender** BepInEx-Beobachter. `tools/qa_building_damage_live.py` kann ihn mit der exakt geprüften QA-Spielkopie kompilieren, optional ausschließlich dort installieren, Logs auswerten und anhand SHA-256-gebundener Belege vollständig zurückbauen. Sechs Offline-Tests kontrollieren Version, Marker, eindeutige Installation, Rückbau und Logbewertung.

## Tatsächlich getesteter lokaler Spielstand

- Isolierter QA-Klon: `E:\SSLiveGame_20261105` mit exakter Markerdatei `.sprite-suite-qa-copy.marker`.
- Script Extender SHCDESE 2.14.3, SHA256 `5cb1c33be5463086505a17f5c48aaa357d733cfff7240e101c821f0e3c668498`.
- Game Assembly-CSharp SHA256 `bc8b6a395f01d48557db413600c8dd8d1fdfd3abdf97bfbbb68a3c56b04fd789`.
- Der lokale Compiler erzeugte ein 13-KiB-Plugin gegen echte lokale BepInEx, Harmony, Unity, Game- und SHCDESE-DLLs. Das Plugin änderte keine Originaldateien.
- Erster realer QA-Start: BepInEx lud den Plugin-Typ, aber seine eigene Versionsprüfung verweigerte die Aktivierung, da `Assembly.Location` im laufenden Script Extender nicht lesbar war. Behoben durch auf die Marker-QA-Kopie beschränkte Dateiprüfungen und vollständige `info.json`-Metadaten.
- Zweiter und dritter realer QA-Start: BepInEx bestätigte `SHCDE_DAMAGE_QA|event=start|status=read_only|...|renderer_modified=false`; nach Start wurde jedoch `event=shutdown|status=unpatched|sprite_writes=0` protokolliert. `DontDestroyOnLoad(gameObject)` allein änderte dies nicht.
- Die Windows-Sitzung war gesperrt; die Bildschirmaufnahme zeigte nur die Anmeldemaske. Es konnte **keine Spielkarte mit Gebäuden** geöffnet werden. Im archivierten BepInEx-Log existieren **0** `tile_graphic`- und **0** `building_footprint`-Messungen. Keine Pixel-/HP-/Spielwert-Schreibzugriffe.
- Das QA-Spiel wurde jeweils regulär mit WM_CLOSE beendet. Der Diagnose-Plugin wurde danach über SHA- und Receipt-gebundenen `--remove-qa` vollständig deinstalliert, ohne die Originalinstallation zu verändern. Logs liegen unter `E:\SpriteSuite_FinalAudit_20261106\LiveGameQA`.

## QA-CLI

```powershell
python tools/qa_building_damage_live.py --qa-root E:\SSLiveGame_20261105 --build-only
python tools/qa_building_damage_live.py --qa-root E:\SSLiveGame_20261105 --install-qa
python tools/qa_building_damage_live.py --qa-root E:\SSLiveGame_20261105 --verify-log E:\SSLiveGame_20261105\BepInEx\LogOutput.log
python tools/qa_building_damage_live.py --qa-root E:\SSLiveGame_20261105 --remove-qa
```

Das neue Logformat unterscheidet das bloße Laden des Plugins von tatsächlichen Messungen. Die Zuordnung ist nur als **Beobachtung** bestätigt, wenn tile-ID, global-ID und building-ID zwischen einer `tile_graphic`- und einer `building_footprint`-Zeile tatsächlich übereinstimmen. Auch dann bleibt `liveGraphicMappingProved=false`, denn ein Tile-Ereignis ist kein validierter Ersatzrenderer.

## Ausstehende letzte technische Belege

Eine interaktiv zugängliche QA-Spielkarte muss für mindestens ein einfaches und ein mehrkacheliges Gebäude belegen, welche Tile-/SpriteRenderer-/Material-/Masken-Objekte mit welcher HP-/Feuerursache verknüpft sind. Insbesondere muss die Lebensdauer des BepInEx-Beobachters über den Mapwechsel überprüft werden. Danach erst per-Instanz- und per-Kachel-Spriteumschaltung implementieren, Vanilla-Rollback, Feuer/Mechanik/Reparatur/Mapreload prüfen und erst dann Runtime-Hook aktivieren.

**Ein vollständiger aktivierter und spielgetesteter Schadensrenderer ist mit diesem QA-Stand nicht belegt.**

## Korrektur und nachgewiesener Spiel-Lebenszyklus (06.11.2026, 17:24 MEZ)

Die vorherige Schlussfolgerung, dass ein zweites `DontDestroyOnLoad`-GameObject den BepInEx-Lebenszyklus dauerhaft stabilisiert, wurde durch den echten dritten Spielstart **widerlegt**: Auch dessen `OnDestroy` lief unmittelbar nach dem Chainloader-Start. Diese Änderung ist deshalb **nicht** der finale Implementierungsstand.

Die korrigierte Fassung unter `runtime/StrongholdEuropeDE.BuildingDamage.LiveAudit/BuildingDamageLiveAudit.cs` nutzt einen **gewöhnlichen C#-Zustandsbeobachter ohne eigenes Unity-GameObject**, gehalten von einer statischen Referenz und den Harmony-/`Application.onBeforeRender`-Callbacks. Nur die BepInEx-Startkomponente kann zerstört werden; der Beobachter wird beim Spielende durch `Application.quitting` mit `Harmony.UnpatchSelf()` abgebaut.

Der konkrete, vierte Start aus der markierten QA-Kopie `E:\SSLiveGame_20261105` hat Folgendes protokolliert:

- `event=start|status=read_only` gegen den exakt geprüften SHCDESE-2.14.3- und `Assembly-CSharp.dll`-Hash;
- `event=host_bootstrap|status=static_observer` und anschließend `event=host_destroyed|static_observer_independent=true`;
- **drei spätere** `event=runner_heartbeat`-Signale bei **60**, **300** und **900** Frames, alle auf **Thread 1**;
- beim regulären Beenden des QA-Spiels `event=shutdown|status=unpatched|reason=application_quitting|sprite_writes=0`;
- **0** Lese-Fehler, **0** Sprite-Schreibzugriffe, **0** Tile-Graphic-/Footprint-Beobachtungen, da keine interaktive Spielkarte geladen wurde.

Originalprotokoll (unverändert und mit SHA-256 nach dem Schließen der QA-Prozessinstanz gesichert): `E:\SpriteSuite_FinalAudit_20261106\LiveGameQA\StaticObserverSuccess_20261106-172451.log`, SHA-256 `61da999880e1e0ea315ea5d5d5d185f61d29a12d88489377e16bfb6debd2732b`. Maschinenlesbare Abnahme: `StaticObserverSuccess_20261106-172451_report.json` am selben Ort.

Die temporäre QA-Plugin-Installation wurde **nach dem Spielende** per Receipt-, Game-, SHCDESE- und Plugin-SHA-256 geprüft und vollständig mit `--remove-qa` entfernt. Die normale Steam-Installation sowie alle Originalspiel-Sprites wurden nicht verändert.

**Beweisgrenze:** Damit ist der **Lebenszyklus** der nur lesenden Spiel-Integration im tatsächlich gestarteten QA-Spiel erstmals bestätigt. Eine Per-Gebäude-Sprite-/Masken-/Renderer-Zuordnung oder aktivierte, spielgetestete HP-abhängige Schadensmodellumschaltung ist weiterhin **nicht** bestätigt. Ein echter Szenen-/Gebäudebefund muss folgen, sobald auf der entsperrten Desktop-Sitzung eine Spielkarte geladen werden kann.

## Statischer Renderer-Pfad der tatsächlich installierten Game-Assembly

Die lokale, mit SHA-256 `bc8b6a395f01d48557db413600c8dd8d1fdfd3abdf97bfbbb68a3c56b04fd789` gepinnte `Assembly-CSharp.dll` wurde zusätzlich über `Mono.Cecil.dll` **nur gelesen**; der Spielprozess musste dafür nicht gestartet werden.

Das geprüfte IL zeigt:

- `GameMapTile::tileImage` ist ein Feld vom Typ `UnityEngine.Sprite`; `GameMapTile::tilemapRef` ist eine `UnityEngine.Tilemaps.Tilemap`.
- `SpriteMapping::setGenericBuildingTileGraphic(GameMapTile,int,int,int)` enthält **22** `stfld GameMapTile::tileImage`-Anweisungen für die verschiedenen Gebäude-/GM-Verzweigungen.
- `SpriteMapping::setOpenTileGraphic(GameMapTile)` schreibt ebenfalls das Sprite, und `GameMap::wipeTiles()` kann dieses Feld zurücksetzen.
- `gameTile::GetTileData(Vector3Int,ITilemap,ref TileData)` liest `GameMapTile::tileImage` an IL-Offsets **357** und **506** und führt Sprite-Schreibzugriffe in `TileData.set_sprite` aus (u. a. Offsets **386** und **511**).
- `GameMap::processTestMap` liest die bestehende Kachel-Bildreferenz.

Damit ist eine **Unity-Tilemap-Versorgung über `GameMapTile.tileImage`** für den exakt geprüften Spiel-Build strukturell nachgewiesen. Nicht nachgewiesen ist, dass die SpriteSuite-Slotnummer unmittelbar einer bestimmten Spiel-Kachel entspricht, oder dass eine spätere Änderung am Feld ohne korrektes `RefreshTile`, Teamfarben-/Materialmasken, Kollisionen und Map-Lifecycle vollständig und fehlerfrei sichtbar bleibt. Ebenso könnten reguläre SpriteMapping-Aufrufe neu gesetzte Bildreferenzen überschreiben. Ein geplanter Schadensmodell-Renderer muss deshalb ursprüngliche Sprite-/Materialwerte instanzspezifisch protokollieren und im Fehlerfall vollständig wiederherstellen, statt allein einen globalen GM-Atlas auszutauschen.

Der tatsächlich ausgeführte QA-Beobachter ist weiterhin nur lesend. Ein aktiver, grafikändernder Mod-Hook gehört **nicht** zum nachgewiesenen aktuellen Stand.

## Ergänzung: direkte Tilemap-Referenzmessung (separater Quellstand)

Die technische IL-Hypothese ist nun durch einen getrennt kompilierten **Leseadapter** für `GameMapTile.tileImage` sowie `tilemapRef.GetSprite` vorbereitet. Er ergänzt das vorhandene `tile_graphic`-Ereignis um `tilemap_sprite` und protokolliert im `building_render_tiles`-Ereignis die Tiles einer Gebäudeinstanz mit gemessener XY-Position und Spritebeschreibung. Die Auswertung wurde um echte Mehrfachübereinstimmung von Gebäude-ID, Global-ID, Tile-ID, Position und Spritebezeichnung erweitert. Scheinbare Übereinstimmungen allein aufgrund gleicher Typ-/Kachelanzahl zählen nicht.

Dies ist zunächst ein **QA-Quellstand ohne neuen In-Game-Einsatz**. Die echten älteren `AutoLoadedKratersee_20261106.log`-Ereignisse (240 Grafik, 80 Footprints) beweisen weiterhin **keine gemeinsame Identität**. Der zusätzliche Quelltext ist mit dem QA-Compiler erfolgreich gebaut worden, aber im laufenden Spiel noch nicht als Quelle neuer `building_render_tiles`-Ereignisse bestätigt. Weder Installation noch automatische Spielstandladung gehören zu diesem Schritt. Einzelheiten: `GEBAEUDESCHADEN_TILEMAP_EVIDENZ_20261106.md`.

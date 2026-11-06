# Gebäudeschaden: SHCDE-Footprint-/Sprite-Zuordnung

Stand: 06.11.2026. Isolierter Zweig `feature/shcde-building-footprint-proof-20261106`, aufgebaut auf gemeinsamer Integration `d4dd387`.

## Technischer Befund

Die offizielle SHCDE Script Extender API bietet folgende **lesende** Schnittstellen:

- `GameBuildingManagerAPI.GetOccupiedTileIds(int)` → `int[]` mit belegten Tile-IDs einer konkreten Gebäudeinstanz;
- `GameBuildingManagerAPI.GetOccupyTileGridSize(int)` → `int` für das native Belegungsraster;
- `GameBuildingManagerAPI.IsValid(int)`, `GetGlobalId(int)`, `GetType(int)` → unverwechselbare Gebäudeidentität über eine einzelne Abfrage;
- `GameTileManagerAPI.IsValidTileId(int)`, `GetTileVectorFromId(int)`, `GetTileId(int,int)` → tatsächliche isometrische Koordinatenumrechnung, **keine Annahme** `id=y*800+x`;
- `GameTileManagerAPI.GetTileBuildingId(int)` → unabhängige Prüfung, ob dieselbe Gebäude-ID wirklich Eigentümer der Tile-Position ist;
- `GameTileManagerAPI.IsTileInsideMapBounds(int,int)` → Begrenzung auf die gültige Spielfeld-Diamantfläche.

Offizielle Dokumentation: https://rawra-stronghold-crusader.gitlab.io/shcde-script-extender/api/SHCDESE.API.GameBuildingManagerAPI.html sowie https://rawra-stronghold-crusader.gitlab.io/shcde-script-extender/api/SHCDESE.API.GameTileManagerAPI.html.

Im bestehenden `FortificationVisualRouter.cs` wurde für **Mauern** bereits eine positionsbezogene Nachverarbeitung von `SpriteMapping.setGenericBuildingTileGraphic(GameMapTile,int,int,int)` eingesetzt. Daraus folgt nicht, dass ein generischer Renderer-Hook für alle Gebäudetypen, Alpha-Masken, Partikel und Zerstörungsstadien ohne zusätzliche Messung geeignet ist.

## Implementierte Trennung

`runtime/StrongholdEuropeDE.Runtime/BuildingDamageFootprintAudit.cs` arbeitet ohne SHCDESE/Unity-Abhängigkeit. Aus einer normierten, mit Global-ID versehenen Gebäudesnapshot-Liste erzeugt es eine rein diagnostische Liste aller passenden isometrischen Zuordnungshypothesen. Die Slot-Reihenfolge wird exakt nach `SpriteCore.positions` berechnet: aufsteigende Diagonale, darin absteigendes `u`.

- Bei 3×3 vollständiger Belegung: acht geometrisch mögliche Richtungen/Spiegelungen, **keine** automatisch bestätigte Renderer-Orientierung.
- Bei einem rechteckigen 2×3-Footprint: vier mögliche Orientierungen, je nach Achszuordnung.
- Bei einem 1×1-Footprint: nur eine geometrische Zuordnung, trotzdem **kein** bewiesener Sprite-Renderer-Hook.
- Bei einem 3×3-Spiel-Footprint zu einem 5×5-SpriteSuite-Raster: klare `sprite_grid_count_mismatch`-Diagnose statt falscher Übernahme; dies ist ein synthetischer Gegenfall, **keine** Behauptung über den echten Grundriss der Abtei.
- Doppelte Tile-IDs, doppelte Positionen, unvollständige rechteckige Belegung, ungültige Koordinaten und übergroße Arrays werden abgewiesen.
- Überschneidungen zwischen zwei unterschiedlichen Gebäudeidentitäten lassen sich mit `SharedTileIds` feststellen, ohne Renderereigentum zu behaupten.
- `Report.ToTsv()` liefert eine deterministische, nur lesende Beweis-/Testansicht: `stronghold-building-footprint-evidence.v1`. Das ist **kein** installierbares Spiel-Asset.

`BuildingDamageFootprintGameSource.cs` ergänzt einen getrennten Adapter für die veröffentlichten API-Signaturen, **nur bei expliziter Compilerdefinition** `SHCDE_BUILDING_DAMAGE_FOOTPRINT_API`. Er prüft die Global-ID, den Typ und die aktuellen API-Singletons vor/nach der Abfrage, die sichere Tile-ID, den Eigentümer über `GetTileBuildingId`, die isometrische Vorwärts-/Rückwärtskonversion und Map-Grenzen. Bei jeder Ausnahme oder Abweichung wird **kein** Snapshot freigegeben.

Die bestehenden Render-Routinen, Spielevents, BepInEx-Host-Lebenszyklen, Global-/Atlas-Overrides und Installationspfade bleiben unberührt. Es werden keine Spielprozesse gestartet.

## Versionierter Übergabevertrag

Der freigegebene SpriteSuite-Export enthält bereits pro Stufe `settings.a` und `settings.b`. Der Offline-Preflight überprüft jetzt, dass **alle** Stufen eines Gebäudes dasselbe Raster besitzen, und übernimmt die Dimensionen in ein `stronghold-building-damage-runtime-table-v2`-TSV:

`building_type, building_group, sprite_a, sprite_b, damage_kind, hp_le, stage_id, scene_id`.

Der C#-Parser nimmt weiterhin explizit **v1**-Tabellen an, allerdings mit den Geometriemaßen `0,0` (unbekannt). V1-Datensätze sind für die HP-Auswahl lesbar, aber sie dürfen **keinen** geometrisch „kompatiblen“ Fußabdruck melden. V2-Einträge mit widersprüchlichen Dimensionen pro Gebäudetyp werden abgelehnt.

Diese Tabelle beweist keine echte Gebäude-Spieltyp-Zuordnung oder Spielrenderung. Der manuell eingegebene Typ ist weiter nur eine zu prüfende Hypothese.

## Lokale API-Signaturen tatsächlich gegen zwei DLLs kompiliert

Die beiden vorhandenen **lokalen QA-Referenzen** wurden ausschließlich gelesen und über einen temporären C#-Bibliotheksbau gebunden:

| QA-Quelle | SHCDESE AssemblyVersion | SHA-256 | Ergebnis |
|---|---|---|---|
| `E:\SSLiveGame_20261105\BepInEx\plugins\000shcdese\SHCDESE.dll` | `2.14.3.0` | `5cb1c33be5463086505a17f5c48aaa357d733cfff7240e101c821f0e3c668498` | Compile-only **bestanden** inkl. `RedBird.Core.dll` und `netstandard.dll` |
| `E:\SSGameQA\BepInEx\plugins\000shcdese\SHCDESE.dll` | `1.44.0.0` | `b724001f6eeede2afe535c1a5367b456859cead405c57f4b6d9fba922dcf5c7b` | Compile-only **bestanden** |

Dies beweist lediglich, dass die abgefragten Methoden in den beiden konkreten Assembly-Oberflächen existieren. Es beweist **keine** Laufzeit-Kompatibilität, keine sichere Multithreading-/Map-Lifecycle-Nutzung, keinen freigegebenen Unity-Renderer-Zugriff und keine In-Game-Installation.

Reproduzierbare Offline-Prüfung (aus dem SpriteSuite-Arbeitsverzeichnis):

```powershell
python tools/qa_building_damage_runtime.py
python tools/qa_building_damage_runtime.py --verify-shcdese "E:\SSLiveGame_20261105\BepInEx\plugins\000shcdese\SHCDESE.dll" --verify-shcdese "E:\SSGameQA\BepInEx\plugins\000shcdese\SHCDESE.dll"
```

Das QA-Tool erzeugt nur temporäre Test-/Compilerdateien und entfernt sie. Der Script-Extender, die Steam-/QA-Installation und die Projektdateien bleiben unangetastet.

## Noch zu beweisen – bevor dynamische Gebäudeschäden angezeigt werden dürfen

1. Eine **gezielte read-only In-Game-Messung**, die Spiel-Build-ID, verwendete SHCDESE-DLL-SHA, Gebäudetyp, Global-ID, belegte Tile-IDs und Koordinaten für mindestens je ein einfaches und ein mehrkacheliges Gebäude festhält.
2. Gegenprobe `GetTileBuildingId` bei Spawn, HP-Verlust, Feuer, Reparatur, Zerstörung/Löschen, Map-Reload und Gebäudeslot-Wiederverwendung. Nicht jedes grafische „Tile“ muss mit einem belegten Gameplay-Tile identisch sein.
3. Zuordnung einer **konkreten** visuellen Sprite-/Tile-Referenz zu einem der bislang nur hypothetischen acht/vier Orientierungen, mit Original-Spielrender-/Atlas-/Material-Messungen statt dem Sortieren nativer Tile-IDs.
4. Eindeutige Zuordnung von SpriteSuite-SpriteSlot `0..n` zur tatsächlichen darzustellenden Sprite-/Layer-Instanz, auch wenn ein Sprite-Raster mehr Kacheln hat als die Gameplay-Okkupation.
5. Nachweis von sicherer Instanzbindung, alten Sprite-/Material-/Alpha-/Teamfarben-Zuständen und vollständiger Wiederherstellung bei Renderfehler, Mapwechsel, Multiplayer/Replays.
6. Erst nach diesen Voraussetzungen kann das eigentliche Gameplay-Umschalten schrittweise mit einem deaktivierten Feature-Flag und eigener Canary-Testinstallation umgesetzt werden.

Bis dahin bleibt `RendererMappingVerified` absichtlich `false` und kein neuer Rendering-Hook aktiv.

## Abnahmelauf auf dem isolierten Integrationskandidaten

- `python tools/qa_building_damage_runtime.py --verify-shcdese ...` bestand: **19** Python-Preflight-Tests, ein echter synthetischer SpriteSuite-5×5-Bibliotheksexport, **62** C#-HP-/TSV-/ZIP-Assertions, **29** C#-Gebäude-Leseassertions, **49** Footprint-/Orientierungs- und tatsächliche DLL-Compile-Gegenproben. Beide SHCDESE-DLLs wurden durch denselben automatisierten Befehl rein statisch geprüft, keinerlei API-Aufruf im laufenden Spiel.
- `node --test` für Sprite-/Tile-/Overlap-/Damage: **136/136** bestanden.
- `pytest` Werkzeugkatalog/Policy/Inventur: **24/24** bestanden.
- Codex-API-Mocks: **10/10** bestanden.
- `verify_release.py`: **162/162** SHA-256-Dateien und deterministische HTML-Fassungen bestätigt; die bestehenden Browserreports dokumentieren **49** alte und **15** Schadenprüfungen. Diese Browser-Suiten wurden für die rein lesenden C#-Änderungen **nicht neu ausgeführt**, ihre HTML-Prüfsummen blieben unverändert.

Der isolierte Kandidat wird nur per geprüftem Git-Commit in den bisherigen gemeinsamen Integrationszweig zurückgeführt. Keine fremden Worktrees, Steam-Dateien, SHCDESE-DLLs, Spieldaten oder aktiven Renderer wurden verändert.

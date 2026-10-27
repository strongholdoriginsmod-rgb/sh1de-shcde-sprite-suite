# API-Nachweis fuer SHCDE-SE 1.44.0

Geprueft wurde das offizielle Release-Artefakt `SHCDESE.dll` mit:

- Dateiversion `1.44.0.0`
- Produktversion `1.44.0+35a2aa19d3c43d1bbd97735e29912a120e664265`
- Groesse `1.355.264` Byte
- SHA-256 `b724001f6eeede2afe535c1a5367b456859cead405c57f4b6d9fba922dcf5c7b`

Die Namen wurden am Quellstand des offiziellen Tags `v1.44.0` unter
`work/se144src/shcde-script-extender-main/` gegengeprueft. Die Datei unter
`cache/decompiled/shcdese_project/` belegt dieselben Kernhooks, gehoert aber
nicht zum gepinnten 1.44-Binaerstand und ist deshalb nur eine zweite Kontrolle.

## Hooks und EventArgs

| Lua-Name | 1.44-Export | verwendete Felder |
|---|---|---|
| `OnBuildWall` | `EventAPI/BuildingR3EventHooks.cs` | `Phase`, `PlayerId`, `TileXBegin`, `TileYBegin`, `TileXEnd`, `TileYEnd`, `WallType`, `BuildWallsMaximum`, `SkipOriginalFunction` aus `Buildings/BuildWallEventArgs.cs` und `EventHookBase.cs` |
| `OnBuildStructure` | gleiche Exportdatei | `Phase`, `PlayerId`, `TileX`, `TileY`, `Mappers`, `BuildingScaleUnknown`, `Unknown1`, `IsFree`, `SkipOriginalFunction` |
| `OnPlacementValidation` | gleiche Exportdatei | `Phase`, `PlayerId`, `TileX`, `TileY`, `Mappers`, `Unknown1`, `Unknown2`, `CustomValidationRules`, `ForceBlockPlacementState`, `SkipOriginalFunction` aus `Buildings/BuildingPlacementValidationEventArgs.cs` und `EventHookBase.cs` |
| `OnPlayerSubtractResource` | `EventAPI/PlayerR3EventHooks.cs` | `Phase`, `PlayerId`, `Good`, `Amount`, `DontSubtract`, `SkipOriginalFunction` |
| `OnBuildingTileTakeDamage` | `EventAPI/BuildingR3EventHooks.cs` | `Phase`, `TileId`, `TileX`, `TileY`, `Damage`, `Unknown1`, `PlayerIdSource`, `Unknown3`, `Unknown4`, `SkipOriginalFunction` |
| `OnUnitMovement` | `EventAPI/UnitR3EventHooks.cs` | `Phase`, `UnitId` |
| `OnGatehouseQuery` | `EventAPI/BuildingR3EventHooks.cs` | `Phase`, `UnitId`, `BuildingId`, `ShouldClose` |
| `OnBuildingRepair` | gleiche Exportdatei | `Phase`, `PlayerId`, `BuildingId`, `WoodCost`, `StoneCost`, `BuildingGlobalId`, `SkipOriginalFunction` |
| `OnBuildingCalculateStoneRepairCost` | gleiche Exportdatei | `Phase`, `BuildingId`, `RepairCost`, `SkipOriginalFunction` |
| `OnBuildingCalculateWoodRepairCost` | gleiche Exportdatei | dieselben Felder |
| `OnWallBulldoze` | gleiche Exportdatei | `Phase`, `PlayerId`, `TileId`, `SkipOriginalFunction` |
| `OnBuildingBulldoze` | gleiche Exportdatei | `Phase`, `BuildingId`, `SkipOriginalFunction` |

Die Hook-Anbindung wurde zusaetzlich in
`Detours/BulkBuildingDetours.cs`, `Detours/BulkPlayerDetours.cs` und
`Detours/BulkUnitDetours.cs` verfolgt. Wichtige Folgen:

- `OnBuildWall` erzeugt immer Pre und Post und wertet `SkipOriginalFunction`
  nicht aus.
- `OnBuildStructure` und `OnBuildingTileTakeDamage` erzeugen ebenfalls immer
  Pre, nativen Aufruf und Post; ihre 1.44-Detours werten
  `SkipOriginalFunction` nicht aus. Dasselbe gilt fuer `OnWallBulldoze` und
  `OnBuildingBulldoze`.
- `OnPlacementValidation` erzeugt Pre, ruft mit den sechs gegebenenfalls
  veraenderten nativen Eingaben die Originalfunktion und erzeugt Post aus den
  urspruenglichen Eingaben. `CustomValidationRules` kann danach den internen
  Blockierungszustand ueberschreiben. Der native `originalResult` wird jedoch
  weder in Pre noch in Post eingetragen; die EventArgs besitzen kein Feld
  `ReturnValue`, `Allowed` oder `IsBlocked`. Die Sonde protokolliert deshalb
  nur Eingaben und Override-Felder und leitet kein Platzierungsurteil ab.
  `SkipOriginalFunction` wird von diesem Detour ebenfalls nicht ausgewertet.
- `OnPlayerSubtractResource`, `OnBuildingRepair` und `OnUnitMovement` werten
  `SkipOriginalFunction` aus und lassen bei `true` den nativen Aufruf sowie
  Post aus.
- Die beiden Repair-Cost-Hooks besitzen nur Pre.
- `OnGatehouseQuery` besitzt ebenfalls nur Pre. `ShouldClose == null` laesst das native
  Ergebnis bestehen; die Sonde schreibt das Feld nie.
- Der Damage-Detour heisst in 1.44
  `c_game_buildingtile_take_melee_damage_hook`. Eine Abdeckung weiterer
  Schadensarten wird nicht aus dem allgemeinen XML-Kommentar abgeleitet.

`LUAR3Hook.Subscribe` belegt, dass ein Lua-Callback genau das EventArgs-Objekt
erhaelt. `LuaHookManager.GetHook` und `LUAR3Subscription.Unsubscribe` belegen
den verwendeten Abo-Lebenszyklus.

## Gelesene Lua-Funktionen

Die finalen Namen entstehen jeweils aus `[LuaApiNamespace]` plus
`[LuaApiExport]`; das ist in `Extensions/LuaExtensions.cs` und
`LUA/DocsGen/LuaApiExportAttribute.cs` implementiert.

- `GameTileManagerAPI.cs`:
  `Tile_GetId`, `Tile_GetTileVectorFromId`, `Tile_IsInsideMapBounds`,
  `Tile_GetPropertyFlag`, `Tile_GetHeight`, `Tile_GetState`,
  `Tile_GetDefaultHeight`, `Tile_GetOwnerId`, `Tile_GetBuildingId`,
  `Tile_GetType`, `Tile_IsWalkableAndUnoccupied`.
- `GameBuildingManagerAPI.cs`:
  `Building_IsValid`, `Building_GetType`, `Building_GetOwner`,
  `Building_GetCurrentHealth`, `Building_GetMaxHealth`,
  `Building_GetBeginTileId`, `Building_GetBuildingOccupyTileGridSize`,
  `Building_GetOccupiedTileIds`.
- `GamePlayerManagerAPI.cs`:
  `Player_GetLocalId`, `Player_GetCurrentMapName`, `Player_GetGoodAmount`.
- `GameUnitManagerAPI.cs`:
  `Unit_GetLocalPosition`, `Unit_GetUnityPosition`, `Unit_GetOwner`,
  `Unit_GetType`.
- `LUA/LUANetworkAPI.cs`:
  `Net_IsNetworkedEnvironmentAsync`. Der Callback wird durch
  `UnityMainThreadDispatcher.DispatchGetAsync` aufgerufen.

`LuaManager.RegisterEnums` registriert `eMappers` und `eEventHookPhase` als
geboxte .NET-Enums. Deshalb vergleicht die Sonde sie ausschliesslich mit `==`
oder `tostring`, nie mit `tonumber`.

## Mapper- und Struct-Anker fuer die neuen Varianten

Jeder neue Name wurde einzeln sowohl am offiziellen 1.44-Quellstand als auch am
Dekompilat geprueft:

| Zweck | Mapper | Struct | Beleg |
|---|---|---|---|
| Treppenweg | `MAPPER_STAIR = 27` | `STRUCT_STAIRS = 113` | `Interop/Enums.cs` und `Interop/EStructs.cs`; die CrusaderDE-Tabelle in `work/decompiled-origins-audit/CrusaderDE/MainViewModel.cs:33327` ordnet `STRUCT_STAIRS` Mapper 27 zu |
| Wachturm-Slot | `MAPPER_TOWER1 = 110` | `STRUCT_TOWER1 = 74` | dieselben Enum-Dateien; `Extensions/EnumExtensions.cs:109` und `:258` belegen beide Richtungen, die CrusaderDE-Tabelle zusaetzlich `MainViewModel.cs:33287` |
| Treppen-Referenzen | `MAPPER_STAIR1 = 181`, `MAPPER_STAIR2 = 182`, `MAPPER_STAIR3 = 183`, `MAPPER_STAIR4 = 184`, `MAPPER_STAIR5 = 185`, `MAPPER_STAIR6 = 186` | kein belegter Struct-Anker | jeder Name einzeln in `Interop/Enums.cs:543-553`; Spiel-Lookup einzeln in `MainViewModel.cs:33638-33643` |

Die numerischen Werte stammen aus dem gepinnten 1.44-Binaerartefakt und stimmen
mit `cache/decompiled/shcdese_project/SHCDESE.Interop/eMappers.cs` sowie
`eStructs.cs` ueberein. Der 1.44-`EnumExtensions`-Switch enthaelt fuer
`MAPPER_STAIR` keine Mapper-zu-Struct-Verzweigung; deshalb wird der Treppenanker
nicht als Beleg fuer den tatsaechlich ausgeloesten Hook ausgegeben.

Fuer 181-186 belegt die Vollsuche nur die gemeinsame `MAPPER_STAIR`-
Namensfamilie. Orientierung, Funktion und eine Verknuepfung zu Mapper 27 oder
zur Variante `wooden_stairs` sind nicht statisch belegt. Die Sonde fuehrt sie
darum mit `reference=true`; keiner dieser Werte vervollstaendigt das
Primaerurteil.

`OnBuildWall` und `OnBuildStructure` akzeptieren in ihren EventArgs den
jeweiligen Mapper ohne eine statische Fallunterscheidung fuer 27 oder 110. Im
verwalteten Extender-Quelltext ist deshalb nicht entscheidbar, welcher Hook bei
der echten Auswahl feuert. Die Sonde abonniert beide und protokolliert den
beobachteten Weg als `BUILD|kind=wall` beziehungsweise `kind=structure`.

Die Felder der beiden EventArgs enthalten keine Varianten-ID, keinen
Menueeintrag und keinen sonstigen Variantenkontext. `wooden_stairs` teilt
Basismapper 27 mit der nativen Treppe; `wooden_platform` teilt Basismapper 110
mit dem nativen Crusader-Wachturm. Diese Identitaet muss daher durch den festen
Kontroll-/Variantenablauf und das externe Testprotokoll belegt werden, nicht
durch Interpretation des Mapperwerts.

`Tile_GetTileVectorFromId` und `Unit_GetLocalPosition` liefern
`UnmanagedVector2<T>`. Dessen Quelltyp besitzt die oeffentlichen Felder `X`
und `Y`; die offiziellen Lua-Beispiele greifen ebenfalls mit `.X` und `.Y`
darauf zu. `Building_GetOccupiedTileIds` liefert dagegen ein .NET-`int[]`.
Die Sonde iteriert dieses Array nicht mit `pairs`/`ipairs`, sondern liest seine
Laenge ueber `.Length` (mit defensiven, geschuetzten Alternativen).

`Unit_GetUnityPosition` liefert `System.Numerics.Vector3`. Die Feldnamen `X`,
`Y` und `Z` sind im 1.44-Quellstand belegt; das tatsaechliche NLua-Marshalling
dieses Typs ist bis zum Pruefstand-/Spiellauf offen. Darum ist jeder Zugriff
einzeln mit `pcall` geschuetzt und ein nicht lesbarer Wert bleibt `na`. Der
API-Code liefert bei unbekannter oder fehlender Unity-Einheit den Nullvektor;
die Sonde markiert ihn `zero_or_unavailable` und verwendet ihn nicht als
Z-Aenderung. Der Movement-Handler merkt sich eine hart begrenzte Zahl Einheiten
und liest die Unity-Position nur auf bereits beobachteten Zielkacheln. Er
schreibt nur nach lokalem Kachelwechsel oder belegter Unity-Z-Aenderung.
`Tile_FindPath`
wird nicht aufgerufen und nicht als Traversalnachweis missbraucht.

## Nur in C# messbare offene Punkte

`EngineInterface.StartMapperItem(int)` ruft `DLL_StartMapAction` auf und gibt
dessen Mapperwert zurueck (`EngineInterface.cs:6901`). `PlaceMapperItem(...)`
ruft `DLL_MapAction` auf (`EngineInterface.cs:6909`). Keine der beiden Methoden
besitzt einen `[LuaApiExport]`; die Extender-Verzeichnisse `API`, `LUA` und
`EventAPI` enthalten dafuer keinen Export. Eine direkte Messung von Eingabe und
Engine-Rueckgabe braucht daher einen spaeteren C#-Begleiter.

Dasselbe gilt fuer die oeffentlichen `Span`-Rohgrids in
`Interop/GameTileManagerView.cs`: PillarGFX, ShowHi, MiscDisplay,
PathConnection, Delay, Logic, WallOwner, Structure, Height, DefaultHeight,
GFX, AlphaGFX, Construction, WallGFX, Noise, StructureWas und GatePath. Es gibt
keinen Lua-Leser fuer diese Rohwerte. Bei `AlphaGFX` ist nur das C#-Packformat
bekannt (Atlas in den hohen 16 Bit, Bildindex in den niedrigen 16 Bit).
`Tile_RefreshTileAreaVisuals` ist zwar exportiert, schreibt/aktualisiert aber
nur und ist weder Leser noch fuer diese Nur-Lese-Sonde zulaessig.

## Lebenszyklus

`LuaManager.InitSingleAssetMod` und `UnloadAssetMods` belegen die drei
Einstiegspunkte `mod_init()`, `mod_load(isEditor)` und `mod_unload()`. Der
Script Extender fuehrt das Skript je Kartenladung neu aus, waehrend native
R3-Abonnements fortleben koennen. Darum liegt jedes Subscription-Handle in
`__zzsonde18_festungsbau_subs`, wird vor einem Start und beim Entladen
abbestellt, und ein unvollstaendiger Altbestand sperrt den Neustart.

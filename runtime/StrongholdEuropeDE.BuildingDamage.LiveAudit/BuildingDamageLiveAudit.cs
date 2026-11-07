using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using BepInEx;
using HarmonyLib;
using CrusaderDE;
using SHCDESE.API;

namespace StrongholdEuropeDE.BuildingDamage.LiveAudit
{
    /// <summary>
    /// QA-only, version-locked, observation-only BepInEx probe.
    /// NEVER sets tileImage, changes HP, patches the native game or loads mod art.
    /// Can be enabled only on an isolated QA clone with confirmed assembly hashes.
    /// </summary>
    [BepInPlugin("org.spritesuite.shcde.damage.liveaudit",
                 "SpriteSuite SHCDE Building Damage Read-only QA",
                 "0.1.0")]
    public sealed class BuildingDamageLiveAudit : BaseUnityPlugin
    {
        private void Awake()
        {
            try
            {
                BuildingDamageRuntimeObserver.Start(Logger);
                Logger.LogInfo("SHCDE_DAMAGE_QA|event=host_bootstrap|status=static_observer");
            }
            catch (Exception error)
            {
                Logger.LogError("SHCDE_DAMAGE_QA|event=host_bootstrap|status=disabled|exception="
                    + error.GetType().Name);
            }
        }

        private void OnDestroy()
        {
            // Chainloader removes plugin components during startup. The plain
            // C# observer must NOT be stopped here: it is held by the static
            // Harmony callback and Unity.Application delegates until quitting.
            Logger.LogInfo("SHCDE_DAMAGE_QA|event=host_destroyed|static_observer_independent=true");
        }
    }

    internal sealed class BuildingDamageRuntimeObserver
    {
        private BepInEx.Logging.ManualLogSource Logger;
        private const string ApprovedSeSha256 = "__SE_SHA256__";
        private const string ApprovedGameSha256 = "__GAME_SHA256__";
        private const string QaMarker = "SpriteSuite isolated Steam build 24816905 QA clone; originals are read-only.";
        private const int MaximumTileReports = 240;
        private const int MaximumFootprintReports = 80;
        private const int FootprintPollInterval = 300;
        private const int MaximumBuildingScan = 2048;
        private const int MaximumTilesPerBuilding = 4096;

        private Harmony _harmony;
        private int _mainThread;
        private int _frames;
        private int _tileReports;
        private int _footprintReports;
        private int _errorReports;
        private int _renderTileReports;
        private const int MaximumRenderTileReports = 40;
        private readonly HashSet<string> _seenRenderInstances =
            new HashSet<string>(StringComparer.Ordinal);
#if SHCDE_QA_SPRITE_CANARY
        // Never enabled in the production build; one native graphical tile
        // can be rebound once and restored by the original engine method.
        private bool _canaryAttempted, _canaryActive;
        private int _canaryStartFrame, _canaryBuildingId, _canaryGlobalId, _canaryFile, _canaryImage, _canaryLight, _canaryTileId, _canaryWrites;
        private GameMapTile _canaryTile;
        private UnityEngine.Sprite _canaryOriginal;
#endif
        private bool _enabled;
#if SHCDE_QA_AUTOMAP
        private const string ExpectedQaSaveSha256 = "__QA_SAVE_SHA256__";
        private const string QaSaveRelative = "SpriteSuite_QA_Saves\\SpriteSuite_Damage_Test.sav";
        private bool _loadAttempted;
        private int _lastReadinessLog;
#endif
        private readonly HashSet<string> _seenTiles = new HashSet<string>(StringComparer.Ordinal);
        private readonly HashSet<string> _seenFootprints = new HashSet<string>(StringComparer.Ordinal);
        private static BuildingDamageRuntimeObserver _active;

        private static string Hex(byte[] bytes)
        {
            var output = new StringBuilder(bytes.Length * 2);
            foreach (byte b in bytes)
                output.Append(b.ToString("x2", CultureInfo.InvariantCulture));
            return output.ToString();
        }

        private static string FileSha256(string path)
        {
            if (string.IsNullOrWhiteSpace(path) || !File.Exists(path))
                throw new InvalidOperationException("Assembly file is unavailable");
            using (FileStream file = File.OpenRead(path))
            using (SHA256 hasher = SHA256.Create())
                return Hex(hasher.ComputeHash(file));
        }

        private BuildingDamageRuntimeObserver(BepInEx.Logging.ManualLogSource logger)
        {
            if (logger == null) throw new ArgumentNullException("logger");
            Logger = logger;
        }

        internal static void Start(BepInEx.Logging.ManualLogSource logger)
        {
            if (_active != null) return;
            var instance = new BuildingDamageRuntimeObserver(logger);
            _active = instance;
            instance.Begin();
        }

        private void Begin()
        {
            _mainThread = Thread.CurrentThread.ManagedThreadId;
            try
            {
                // The observer has no Unity GameObject. Static Harmony and
                // Application event delegates outlive scene transitions.
                string root = Paths.GameRootPath;
                if (string.IsNullOrWhiteSpace(root))
                    throw new InvalidOperationException("game_root_missing");
                string marker = Path.Combine(root, ".sprite-suite-qa-copy.marker");
                if (!File.Exists(marker) || !string.Equals(
                        File.ReadAllText(marker).Trim(), QaMarker, StringComparison.Ordinal))
                {
                    Logger.LogWarning("SHCDE_DAMAGE_QA|event=start|status=disabled|reason=unmarked_game_root");
                    return;
                }
                string se = FileSha256(Path.Combine(root, "BepInEx", "plugins",
                    "000shcdese", "SHCDESE.dll"));
                string game = FileSha256(Path.Combine(root,
                    "Stronghold Crusader Definitive Edition_Data", "Managed",
                    "Assembly-CSharp.dll"));
                AssemblyName loadedSe = typeof(GameBuildingManagerAPI).Assembly.GetName();
                AssemblyName loadedGame = typeof(SpriteMapping).Assembly.GetName();
                if (loadedSe.Name != "SHCDESE" ||
                    loadedSe.Version.ToString() != "2.14.3.0" ||
                    loadedGame.Name != "Assembly-CSharp")
                    throw new InvalidOperationException("loaded_assembly_identity_mismatch");
                if (!string.Equals(se, ApprovedSeSha256, StringComparison.Ordinal) ||
                    !string.Equals(game, ApprovedGameSha256, StringComparison.Ordinal))
                {
                    Logger.LogWarning("SHCDE_DAMAGE_QA|event=start|status=disabled|reason=assembly_hash_mismatch");
                    return;
                }

                MethodInfo target = typeof(SpriteMapping).GetMethod(
                    "setGenericBuildingTileGraphic",
                    BindingFlags.Instance | BindingFlags.Static |
                    BindingFlags.Public | BindingFlags.NonPublic,
                    null,
                    new Type[] { typeof(GameMapTile), typeof(int), typeof(int), typeof(int) },
                    null);
                MethodInfo postfix = typeof(BuildingDamageRuntimeObserver).GetMethod(
                    "ObserveTilePostfix",
                    BindingFlags.Static | BindingFlags.NonPublic);
                if (target == null || target.ReturnType != typeof(void) || postfix == null)
                {
                    Logger.LogWarning("SHCDE_DAMAGE_QA|event=start|status=disabled|reason=tile_graphic_abi_mismatch");
                    return;
                }

                _active = this;
                _harmony = new Harmony("org.spritesuite.shcde.damage.liveaudit");
                _harmony.Patch(target, postfix: new HarmonyMethod(postfix));
                UnityEngine.Application.onBeforeRender += OnBeforeRender;
                UnityEngine.Application.quitting += OnQuitting;
                _enabled = true;
#if SHCDE_QA_SPRITE_CANARY
                Logger.LogInfo("SHCDE_DAMAGE_QA|event=start|status=qa_sprite_canary|se_sha256=" +
                    se + "|game_sha256=" + game + "|gamecopy_only=true");
#else
                Logger.LogInfo("SHCDE_DAMAGE_QA|event=start|status=read_only|se_sha256=" +
                    se + "|game_sha256=" + game + "|renderer_modified=false");
#endif
            }
            catch (Exception e)
            {
                _enabled = false;
                try { UnityEngine.Application.onBeforeRender -= OnBeforeRender; } catch (Exception) { }
                try { UnityEngine.Application.quitting -= OnQuitting; } catch (Exception) { }
                if (_harmony != null)
                {
                    try { _harmony.UnpatchSelf(); } catch (Exception) { }
                }
                _active = null;
                Logger.LogError("SHCDE_DAMAGE_QA|event=start|status=disabled|error=" +
                    e.GetType().Name + "|reason=" + Sanitize(e.Message, 96));
            }
        }

        private static void ObserveTilePostfix(GameMapTile tile, int file, int image, int light)
        {
            BuildingDamageRuntimeObserver app = _active;
            if (app == null || !app._enabled || tile == null ||
                Thread.CurrentThread.ManagedThreadId != app._mainThread ||
                app._tileReports >= MaximumTileReports)
                return;

            try
            {
                GameTileManagerAPI tiles = GameTileManagerAPI.Instance;
                GameBuildingManagerAPI buildings = GameBuildingManagerAPI.Instance;
                if (tiles == null || buildings == null) return;

                int x = tile.gameMapX, y = tile.gameMapY;
                if (!tiles.IsTileInsideMapBounds(x, y)) return;
                int tileId = tiles.GetTileId(x, y);
                if (tileId < 0 || !tiles.IsValidTileId(tileId)) return;
                int buildingId = tiles.GetTileBuildingId(tileId);
                if (buildingId <= 0 || !buildings.IsValid(buildingId)) return;

                int globalBefore = buildings.GetGlobalId(buildingId);
                if (globalBefore <= 0) return;
                int buildingType = (int)buildings.GetType(buildingId);
                int current = buildings.GetCurrentHealth(buildingId);
                int maximum = buildings.GetMaxHealth(buildingId);
                int fire = buildings.GetOnFireTicks(buildingId);
                if (maximum <= 0 || current < 0 || current > maximum) return;
                if (!buildings.IsValid(buildingId) ||
                    buildings.GetGlobalId(buildingId) != globalBefore ||
                    tiles.GetTileBuildingId(tileId) != buildingId)
                    return;

                int[] occupied = buildings.GetOccupiedTileIds(buildingId);
                int occupiedIndex = -1;
                int occupiedCount = occupied == null ? -1 : occupied.Length;
                if (occupied != null && occupied.Length <= MaximumTilesPerBuilding)
                    for (int position = 0; position < occupied.Length; position++)
                        if (occupied[position] == tileId)
                        {
                            occupiedIndex = position;
                            break;
                        }
                string sprite = tile.tileImage == null ? "null" :
                    Sanitize(tile.tileImage.name, 64);
                string tilemapSprite = "none";
                if (tile.tilemapRef != null)
                {
                    try
                    {
                        var active = tile.tilemapRef.GetSprite(
                            new UnityEngine.Vector3Int(x, y, 0));
                        tilemapSprite = DescribeSprite(active);
                    }
                    catch (Exception readError)
                    {
                        // A missing Tilemap reference must not discard the
                        // independently measured SpriteMapping observation.
                        app.ReportFailure("tilemap_sprite", readError);
                    }
                }
                string key = globalBefore.ToString(CultureInfo.InvariantCulture) +
                    ":" + tileId.ToString(CultureInfo.InvariantCulture) +
                    ":" + file.ToString(CultureInfo.InvariantCulture) +
                    ":" + image.ToString(CultureInfo.InvariantCulture) +
                    ":" + sprite;
                if (!app._seenTiles.Add(key)) return;
                app._tileReports++;
                app.Logger.LogInfo("SHCDE_DAMAGE_QA|event=tile_graphic|building_id=" +
                    buildingId + "|global_id=" + globalBefore + "|type=" + buildingType +
                    "|hp=" + current + "|max_hp=" + maximum + "|fire_ticks=" + fire +
                    "|tile_id=" + tileId + "|x=" + x + "|y=" + y +
                    "|gm=" + file + "|image=" + image + "|sprite=" + sprite +
                    "|tilemap_sprite=" + tilemapSprite +
                    "|occupied_index=" + occupiedIndex +
                    "|occupied_count=" + occupiedCount +
                    "|renderer_modified=false");
#if SHCDE_QA_SPRITE_CANARY
                app.TryApplyQaCanary(tile, tileId, buildingId, globalBefore,
                    buildingType, occupiedIndex, file, image, light);
#endif
            }
            catch (Exception e)
            {
                app.ReportFailure("tile_graphic", e);
            }
        }

        private static string Sanitize(string input, int maximum)
        {
            if (string.IsNullOrEmpty(input)) return "none";
            input = input.Replace('|', '_').Replace('=', '_')
                .Replace('\r', ' ').Replace('\n', ' ');
            return input.Length <= maximum ? input : input.Substring(0, maximum);
        }

        private void ReportFailure(string context, Exception ex)
        {
            if (++_errorReports <= 5)
                Logger.LogWarning("SHCDE_DAMAGE_QA|event=read_error|context=" +
                    context + "|exception=" + ex.GetType().Name);
        }

        private void OnBeforeRender()
        {
            Update();
        }

        private void Update()
        {
            if (!_enabled || Thread.CurrentThread.ManagedThreadId != _mainThread)
                return;
            _frames++;
#if SHCDE_QA_SPRITE_CANARY
            if (_canaryActive && _frames >= _canaryStartFrame + 120)
                RestoreQaCanary("frame_budget");
#endif
#if SHCDE_QA_AUTOMAP
            TryOpenQaSave();
#endif
            if (_frames == 60 || _frames == 300 || _frames == 900)
                Logger.LogInfo("SHCDE_DAMAGE_QA|event=runner_heartbeat|frames=" + _frames
                    + "|thread=" + Thread.CurrentThread.ManagedThreadId
                    + "|tile_reports=" + _tileReports
                    + "|footprints=" + _footprintReports
                    + "|renderer_modified=false");
            if (_frames % FootprintPollInterval != 0 ||
                (_footprintReports >= MaximumFootprintReports &&
                 _renderTileReports >= MaximumRenderTileReports))
                return;

            try
            {
                GameBuildingManagerAPI buildings = GameBuildingManagerAPI.Instance;
                GameTileManagerAPI tiles = GameTileManagerAPI.Instance;
                if (buildings == null || tiles == null) return;
                int[] ids = buildings.GetAllAliveBuildings();
                if (ids == null || ids.Length > MaximumBuildingScan) return;

                int scanned = 0;
                foreach (int id in ids)
                {
                    if (scanned++ > 256 || id <= 0 || !buildings.IsValid(id)) continue;
                    int global = buildings.GetGlobalId(id);
                    if (global <= 0) continue;
                    int type = (int)buildings.GetType(id);
                    int width = buildings.GetOccupyTileGridSize(id);
                    int[] occupied = buildings.GetOccupiedTileIds(id);
                    if (occupied == null || occupied.Length == 0 ||
                        occupied.Length > MaximumTilesPerBuilding ||
                        width < 1 || width > 64) continue;

                    var footprint = new StringBuilder();
                    bool valid = true;
                    for (int j = 0; j < occupied.Length; j++)
                    {
                        int tileId = occupied[j];
                        if (!tiles.IsValidTileId(tileId) ||
                            tiles.GetTileBuildingId(tileId) != id)
                        {
                            valid = false;
                            break;
                        }
                        var xy = tiles.GetTileVectorFromId(tileId);
                        if (tiles.GetTileId(xy.X, xy.Y) != tileId)
                        {
                            valid = false;
                            break;
                        }
                        if (j > 0) footprint.Append(';');
                        footprint.Append(tileId).Append(':')
                            .Append(xy.X).Append(',').Append(xy.Y);
                    }
                    if (!valid || !buildings.IsValid(id) ||
                        buildings.GetGlobalId(id) != global) continue;

                    // An occupied footprint can be present before Unity has
                    // populated tileImage. Retry sprite evidence on later
                    // passes even if the footprint has already been reported.
                    if (_footprintReports < MaximumFootprintReports)
                    {
                        string key = global + ":" + type + ":" + footprint;
                        if (_seenFootprints.Add(key))
                        {
                            _footprintReports++;
                            Logger.LogInfo("SHCDE_DAMAGE_QA|event=building_footprint|building_id=" +
                                id + "|global_id=" + global + "|type=" + type +
                                "|grid=" + width + "|tile_count=" + occupied.Length +
                                "|tiles=" + footprint.ToString() +
                                "|renderer_mapping_verified=false|renderer_modified=false");
                        }
                    }
                    ObserveTilemapArt(id, global, type, occupied, tiles);
                    if (_footprintReports >= MaximumFootprintReports &&
                        _renderTileReports >= MaximumRenderTileReports) break;
                }
            }
            catch (Exception e)
            {
                ReportFailure("footprint", e);
            }
        }

#if SHCDE_QA_AUTOMAP
        private void TryOpenQaSave()
        {
            if (_loadAttempted || _frames < 1200 || _frames % 300 != 0)
                return;
            try
            {
                // Native map loading is a normal game operation, but is enabled
                // only on the SHA-pinned isolated QA clone and QA save copy.
                bool director = Director.instance != null;
                bool editor = EditorDirector.instance != null;
                bool view = CrusaderDE.MainViewModel.Instance != null;
                bool menu = view && CrusaderDE.MainViewModel.Instance.HUDIngameMenu != null;
                bool mapFile = MapFileManager.Instance != null;
                if (!director || !editor || !menu || !mapFile)
                {
                    if (_frames - _lastReadinessLog >= 900)
                    {
                        _lastReadinessLog = _frames;
                        Logger.LogInfo("SHCDE_DAMAGE_QA|event=qa_save_wait|frames=" + _frames +
                            "|director=" + director + "|editor=" + editor +
                            "|view=" + view + "|menu=" + menu + "|map_file=" + mapFile);
                    }
                    return;
                }

                string root = Paths.GameRootPath;
                string path = Path.GetFullPath(Path.Combine(root, QaSaveRelative));
                string qaDir = Path.GetFullPath(Path.Combine(root, "SpriteSuite_QA_Saves")) +
                    Path.DirectorySeparatorChar;
                if (!path.StartsWith(qaDir, StringComparison.OrdinalIgnoreCase))
                    throw new InvalidOperationException("unsafe_qa_save_path");
                if (!File.Exists(path) || !string.Equals(FileSha256(path),
                        ExpectedQaSaveSha256, StringComparison.Ordinal))
                    throw new InvalidOperationException("qa_save_sha256_mismatch");

                _loadAttempted = true;
                // Header is created by the game's own map-file manager.
                FileHeader header = MapFileManager.Instance.GetFileInfoFromFileName(
                    path, "SpriteSuite_Damage_Test.sav", 0, true);
                string headerSource = "qa_copy";
                if (header == null)
                {
                    var indexed = MapFileManager.Instance.GetSaves(0, true, false, false);
                    int indexedCount = indexed == null ? 0 : indexed.Count;
                    if (indexed != null)
                        foreach (FileHeader item in indexed)
                        {
                            if (item != null && item.fileName != null &&
                                item.fileName.EndsWith("Kratersee-16.sav",
                                    StringComparison.OrdinalIgnoreCase))
                            {
                                header = item;
                                headerSource = "game_indexed_save";
                                break;
                            }
                        }
                    Logger.LogInfo("SHCDE_DAMAGE_QA|event=qa_save_header|indexed_saves=" +
                        indexedCount + "|indexed_match=" + (header != null));
                }
                if (header == null)
                {
                    // The real game loader uses the byte stream from the
                    // separately hash-checked path. This object only provides
                    // optional restart/radar/achievement metadata.
                    header = new FileHeader();
                    header.fileName = path;
                    header.display_filename = "SpriteSuite QA Damage";
                    headerSource = "minimal_metadata";
                }
                Logger.LogInfo("SHCDE_DAMAGE_QA|event=qa_save_load|status=requested|frames=" +
                    _frames + "|sha256=" + ExpectedQaSaveSha256 +
                    "|header=" + headerSource + "|game_save_copy_only=true");
                EditorDirector.instance.loadSaveGame(path, "SpriteSuite QA Damage", header);
                Logger.LogInfo("SHCDE_DAMAGE_QA|event=qa_save_load|status=returned|frames=" +
                    _frames + "|renderer_modified=false");
            }
            catch (Exception error)
            {
                _loadAttempted = true; // fail closed, never auto-retry a native map load
                Logger.LogWarning("SHCDE_DAMAGE_QA|event=qa_save_load|status=failed|exception=" +
                    error.GetType().Name + "|reason=" + Sanitize(error.Message, 100));
            }
        }
#endif

        private static string DescribeSprite(UnityEngine.Sprite sprite)
        {
            if (sprite == null) return "none";
            UnityEngine.Rect rect = sprite.rect;
            string name = Sanitize(sprite.name, 46)
                .Replace(':', '_').Replace(';', '_').Replace(',', '_');
            return name + "~" + ((int)rect.width).ToString(CultureInfo.InvariantCulture) +
                "x" + ((int)rect.height).ToString(CultureInfo.InvariantCulture) +
                "~" + sprite.pixelsPerUnit.ToString("0.##", CultureInfo.InvariantCulture);
        }

        private void ObserveTilemapArt(int buildingId, int globalId, int type,
            int[] tileIds, GameTileManagerAPI tiles)
        {
            if (tileIds == null || tileIds.Length == 0 ||
                _renderTileReports >= MaximumRenderTileReports || GameMap.instance == null)
                return;
            string key = globalId.ToString(CultureInfo.InvariantCulture) + ":" +
                type.ToString(CultureInfo.InvariantCulture);
            if (_seenRenderInstances.Contains(key)) return;
            try
            {
                var samples = new StringBuilder();
                int selected = Math.Min(tileIds.Length, 64);
                int observed = 0, assignedSprites = 0, tilemapSprites = 0;
                for (int i = 0; i < selected; i++)
                {
                    int tileId = tileIds[i];
                    var xy = tiles.GetTileVectorFromId(tileId);
                    GameMapTile tile = GameMap.instance.getMapTile(xy.X, xy.Y);
                    if (tile == null) continue;
                    string source = DescribeSprite(tile.tileImage);
                    if (tile.tileImage != null) assignedSprites++;
                    string target = "none";
                    if (tile.tilemapRef != null)
                    {
                        try
                        {
                            var activeSprite = tile.tilemapRef.GetSprite(
                                new UnityEngine.Vector3Int(xy.X, xy.Y, 0));
                            target = DescribeSprite(activeSprite);
                            if (activeSprite != null) tilemapSprites++;
                        }
                        catch (Exception readError)
                        {
                            // Preserve tileImage evidence even if this
                            // particular Tilemap cannot return a sprite.
                            ReportFailure("render_tilemap_sprite", readError);
                        }
                    }
                    if (samples.Length > 0) samples.Append(';');
                    samples.Append(tileId).Append(':').Append(xy.X).Append(',')
                        .Append(xy.Y).Append(':').Append(source).Append(':')
                        .Append(target);
                    observed++;
                }
                if (assignedSprites == 0 && tilemapSprites == 0) return;
                _seenRenderInstances.Add(key);
                _renderTileReports++;
                Logger.LogInfo("SHCDE_DAMAGE_QA|event=building_render_tiles|building_id=" +
                    buildingId + "|global_id=" + globalId + "|type=" + type +
                    "|tile_count=" + tileIds.Length +
                    "|sample_count=" + observed + "|assigned_sprites=" + assignedSprites +
                    "|tilemap_sprites=" + tilemapSprites +
                    "|samples=" + samples.ToString() +
                    "|renderer_modified=false");
            }
            catch (Exception error)
            {
                ReportFailure("render_tile_read", error);
            }
        }

#if SHCDE_QA_SPRITE_CANARY
        private void TryApplyQaCanary(GameMapTile tile, int tileId, int buildingId,
            int globalId, int type, int occupiedIndex, int file, int image, int light)
        {
            // Only a single known, original GAME sprite in the isolated QA
            // game; do not alter HP or any asset/user project file.
            if (_canaryAttempted || _canaryActive || !_loadAttempted ||
                _frames < 1200 || type != 104 || file != 6 ||
                occupiedIndex < 0 || tile.tileImage == null ||
                tile.tilemapRef == null)
                return;
            try
            {
                spriteLoader loader = spriteLoader.instance;
                if (loader == null) return;
                UnityEngine.Sprite original = tile.tileImage;
                UnityEngine.Sprite alternative = null;
                foreach (int offset in new int[] { 1, -1, 2, -2, 3, -3, 4, -4 })
                {
                    int candidateId = image + offset;
                    if (candidateId < 0) continue;
                    UnityEngine.Sprite candidate = loader.GetGMSprite(
                        (Enums.GM)file, candidateId);
                    if (candidate == null || candidate == original) continue;
                    if (candidate.rect.width != original.rect.width ||
                        candidate.rect.height != original.rect.height ||
                        candidate.pixelsPerUnit != original.pixelsPerUnit ||
                        candidate.pivot != original.pivot)
                        continue;
                    alternative = candidate;
                    break;
                }
                if (alternative == null) return;
                GameBuildingManagerAPI buildings = GameBuildingManagerAPI.Instance;
                GameTileManagerAPI tiles = GameTileManagerAPI.Instance;
                if (buildings == null || tiles == null || !buildings.IsValid(buildingId) ||
                    buildings.GetGlobalId(buildingId) != globalId ||
                    tiles.GetTileBuildingId(tileId) != buildingId)
                    return;
                _canaryAttempted = true;
                _canaryActive = true;
                _canaryTile = tile;
                _canaryOriginal = original;
                _canaryFile = file;
                _canaryImage = image;
                _canaryLight = light;
                _canaryBuildingId = buildingId;
                _canaryGlobalId = globalId;
                _canaryTileId = tileId;
                _canaryStartFrame = _frames;
                tile.tileImage = alternative;
                _canaryWrites++;
                Logger.LogInfo("SHCDE_DAMAGE_QA|event=qa_canary|status=applied|building_id=" +
                    buildingId + "|global_id=" + globalId + "|tile_id=" + tileId +
                    "|original_sprite=" + Sanitize(original.name, 50) +
                    "|alternative_sprite=" + Sanitize(alternative.name, 50) +
                    "|writes=" + _canaryWrites + "|time_limited=true|test_only=true");
            }
            catch (Exception error)
            {
                ReportFailure("qa_canary_apply", error);
            }
        }

        private void RestoreQaCanary(string reason)
        {
            if (!_canaryActive) return;
            _canaryActive = false;
            try
            {
                GameBuildingManagerAPI buildings = GameBuildingManagerAPI.Instance;
                GameTileManagerAPI tiles = GameTileManagerAPI.Instance;
                if (buildings == null || tiles == null ||
                    !buildings.IsValid(_canaryBuildingId) ||
                    buildings.GetGlobalId(_canaryBuildingId) != _canaryGlobalId ||
                    tiles.GetTileBuildingId(_canaryTileId) != _canaryBuildingId)
                {
                    Logger.LogWarning("SHCDE_DAMAGE_QA|event=qa_canary|status=restore_blocked|reason=building_identity_changed");
                    return;
                }
                if (_canaryTile == null) throw new InvalidOperationException("missing_tile");
                // Re-run the exact original game's method, not a guessed
                // position-based terrain sprite lookup. Our one-shot flag
                // prevents the Harmony postfix from applying the canary again.
                SpriteMapping.setGenericBuildingTileGraphic(_canaryTile,
                    _canaryFile, _canaryImage, _canaryLight);
                _canaryWrites++;
                if (_canaryTile.tilemapRef != null)
                    _canaryTile.tilemapRef.RefreshAllTiles();
                bool restored = _canaryTile.tileImage != null &&
                    _canaryOriginal != null &&
                    _canaryTile.tileImage.name == _canaryOriginal.name;
                Logger.LogInfo("SHCDE_DAMAGE_QA|event=qa_canary|status=restored|reason=" +
                    reason + "|building_id=" + _canaryBuildingId +
                    "|global_id=" + _canaryGlobalId + "|tile_id=" + _canaryTileId +
                    "|original_restored=" + restored + "|writes=" + _canaryWrites);
                if (!restored)
                    Logger.LogWarning("SHCDE_DAMAGE_QA|event=qa_canary|status=restore_mismatch");
            }
            catch (Exception error)
            {
                ReportFailure("qa_canary_restore", error);
            }
        }
#endif

        private void OnQuitting()
        {
            Shutdown("application_quitting");
        }

        private void Shutdown(string reason)
        {
            if (!_enabled && _harmony == null) return;
#if SHCDE_QA_SPRITE_CANARY
            RestoreQaCanary("application_quitting");
#endif
            _enabled = false;
            try { UnityEngine.Application.onBeforeRender -= OnBeforeRender; }
            catch (Exception e) { ReportFailure("unsubscribe_before_render", e); }
            try { UnityEngine.Application.quitting -= OnQuitting; }
            catch (Exception e) { ReportFailure("unsubscribe_quitting", e); }
            if (_harmony != null)
            {
                try { _harmony.UnpatchSelf(); } catch (Exception e) { ReportFailure("unpatch", e); }
                _harmony = null;
            }
            if (ReferenceEquals(_active, this)) _active = null;
#if SHCDE_QA_SPRITE_CANARY
            Logger.LogInfo("SHCDE_DAMAGE_QA|event=shutdown|status=unpatched|reason=" +
                reason + "|sprite_writes=" + _canaryWrites + "|canary_mode=true");
#else
            Logger.LogInfo("SHCDE_DAMAGE_QA|event=shutdown|status=unpatched|reason=" +
                reason + "|sprite_writes=0");
#endif
        }
    }
}

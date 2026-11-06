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
        private bool _enabled;
        private readonly HashSet<string> _seenRenderInstances =
            new HashSet<string>(StringComparer.Ordinal);
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
                Logger.LogInfo("SHCDE_DAMAGE_QA|event=start|status=read_only|se_sha256=" +
                    se + "|game_sha256=" + game + "|renderer_modified=false");
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

        private static void ObserveTilePostfix(GameMapTile tile, int file, int image)
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
                    "|renderer_modified=false");
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
            if (_frames == 60 || _frames == 300 || _frames == 900)
                Logger.LogInfo("SHCDE_DAMAGE_QA|event=runner_heartbeat|frames=" + _frames
                    + "|thread=" + Thread.CurrentThread.ManagedThreadId
                    + "|tile_reports=" + _tileReports
                    + "|footprints=" + _footprintReports
                    + "|renderer_modified=false");
            if (_frames % FootprintPollInterval != 0 ||
                _footprintReports >= MaximumFootprintReports)
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

                    string key = global + ":" + type + ":" + footprint;
                    if (!_seenFootprints.Add(key)) continue;
                    _footprintReports++;
                    Logger.LogInfo("SHCDE_DAMAGE_QA|event=building_footprint|building_id=" +
                        id + "|global_id=" + global + "|type=" + type +
                        "|grid=" + width + "|tile_count=" + occupied.Length +
                        "|tiles=" + footprint.ToString() +
                        "|renderer_mapping_verified=false|renderer_modified=false");
                    ObserveTilemapArt(id, global, type, occupied, tiles);
                    if (_footprintReports >= MaximumFootprintReports) break;
                }
            }
            catch (Exception e)
            {
                ReportFailure("footprint", e);
            }
        }

        // Read only the actual Unity Tilemap and GameMapTile sprite references.
        // This is diagnostics, never a replacement renderer or map mutation.
        private static string DescribeSprite(UnityEngine.Sprite sprite)
        {
            if (sprite == null) return "none";
            UnityEngine.Rect rect = sprite.rect;
            string name = Sanitize(sprite.name, 46)
                .Replace(':', '_').Replace(';', '_').Replace(',', '_');
            return name + "~" +
                ((int)rect.width).ToString(CultureInfo.InvariantCulture) + "x" +
                ((int)rect.height).ToString(CultureInfo.InvariantCulture) + "~" +
                sprite.pixelsPerUnit.ToString("0.##", CultureInfo.InvariantCulture);
        }

        private void ObserveTilemapArt(int buildingId, int globalId, int type,
            int[] tileIds, GameTileManagerAPI tiles)
        {
            if (tileIds == null || tileIds.Length == 0 ||
                _renderTileReports >= 40 || GameMap.instance == null)
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
                if (observed == 0) return;
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

        private void OnQuitting()
        {
            Shutdown("application_quitting");
        }

        private void Shutdown(string reason)
        {
            if (!_enabled && _harmony == null) return;
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
            Logger.LogInfo("SHCDE_DAMAGE_QA|event=shutdown|status=unpatched|reason=" +
                reason + "|sprite_writes=0");
        }
    }
}

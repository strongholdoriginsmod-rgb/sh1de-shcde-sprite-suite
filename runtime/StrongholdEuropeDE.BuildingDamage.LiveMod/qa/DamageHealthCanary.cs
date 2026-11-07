using System;
using System.Collections.Generic;
using System.IO;
using System.Security.Cryptography;
using System.Threading;
using BepInEx;
using BepInEx.Logging;
using R3;
using SHCDESE.API;
using SHCDESE.EventAPI;
using SHCDESE.EventAPI.MapLoader;
using SHCDESE.Interop;
using UnityEngine;

namespace SpriteSuite.BuildingDamage.QA
{
    [BepInPlugin("org.spritesuite.hp-fire-healthqa", "SpriteSuite HP Fire Actual Value QA", "0.2.0")]
    public sealed class DamageHealthQaHost : BaseUnityPlugin
    {
        private void Awake()
        {
            try { ActualHealthCanary.Start(Logger); }
            catch (Exception e)
            {
                Logger.LogError("SPRITESUITE_HEALTH_QA|event=disabled|reason=" +
                    ActualHealthCanary.Field(e.Message));
            }
        }
    }

    // Test-only driver. Production code never changes gameplay values.
    internal sealed class ActualHealthCanary
    {
        private const int TargetGlobalId = 661027;
        private const int TargetType = 104;
        private const string MechanicalStage = "SpriteSuite:qa_mechanical75:";
        private const string FireStage = "SpriteSuite:qa_fire40:";
        private const int PhaseTimeoutSeconds = 30;
        private const int SettleFrames = 24;
        private static ActualHealthCanary active;

        private sealed class TileSample
        {
            internal int X, Y;
            internal Sprite Original;
        }

        private readonly ManualLogSource log;
        private readonly int mainThread = Thread.CurrentThread.ManagedThreadId;
        private readonly string save;
        private readonly string saveSha256;
        private readonly string evidence;
        private readonly bool quitOnFinish =
            Environment.GetEnvironmentVariable("SPRITESUITE_HEALTH_QA_QUIT") == "1";
        private readonly IDisposable loadSubscription;
        private readonly List<TileSample> baseline = new List<TileSample>();
        private GameMap map;
        private int id, global, maximum;
        private int owner, buildX, buildY, elevation, visualOwner, variation;
        private bool changedHp, rebuilt, pausedBefore, changedPause;
        private int frame, phaseFrame, lastLoadFrame, loadPosts, expectedLoadPost;
        private DateTime deadline;
        private Phase phase;
        private string screenshot;

        private enum Phase
        {
            Ready, Baseline, Mechanical, Burning, Extinguished, Repaired,
            BeforeReload, ReloadBaseline, ReloadMechanical, ReloadRepaired,
            Removed, NewBaseline, NewMechanical, NewRepaired, Cleanup
        }

        private ActualHealthCanary(ManualLogSource logger, string savePath,
            string hash, string evidencePath)
        {
            log = logger;
            save = savePath;
            saveSha256 = hash;
            evidence = evidencePath;
            var observable = MapLoaderR3EventHooks.OnLoadSave.Observable;
            if (observable == null) throw new InvalidOperationException("save_events_unavailable");
            loadSubscription = ObservableSubscribeExtensions.Subscribe(observable, OnLoadSave);
            Enter(Phase.Ready, 120);
        }

        internal static void Start(ManualLogSource logger)
        {
            if (active != null) return;
            string root = Path.GetFullPath(Paths.GameRootPath).TrimEnd(Path.DirectorySeparatorChar);
            string expectedRoot = Environment.GetEnvironmentVariable("SPRITESUITE_HEALTH_QA_ROOT");
            string marker = Path.Combine(root, ".spritesuite-health-qa");
            if (string.IsNullOrWhiteSpace(expectedRoot) ||
                !string.Equals(Path.GetFullPath(expectedRoot).TrimEnd(Path.DirectorySeparatorChar),
                    root, StringComparison.OrdinalIgnoreCase) || !File.Exists(marker) ||
                File.ReadAllText(marker).Trim() != "SpriteSuite HP/fire QA with isolated player profile.")
                throw new InvalidOperationException("qa_root_not_marked");

            string saveDirectory = Path.Combine(root, "SpriteSuite_QA_Saves");
            string save = Path.Combine(saveDirectory, "SpriteSuite_Damage_Test.sav");
            string hash = Environment.GetEnvironmentVariable("SPRITESUITE_HEALTH_QA_SAVE_SHA256");
            if (string.IsNullOrWhiteSpace(hash) || hash.Length != 64 ||
                !File.Exists(save) || IsReparse(saveDirectory) || IsReparse(save) ||
                !string.Equals(FileHash(save), hash, StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("qa_save_hash_mismatch");

            string output = Path.Combine(root, "SpriteSuite_QA_Evidence");
            Directory.CreateDirectory(output);
            if (IsReparse(output)) throw new InvalidOperationException("qa_evidence_is_reparse_point");
            string evidence = Path.Combine(output, "hp-fire-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(evidence);
            active = new ActualHealthCanary(logger, save, hash.ToLowerInvariant(), evidence);
            Application.onBeforeRender += active.OnBeforeRender;
            Application.quitting += active.OnQuit;
            active.Event("started", "save_sha256=" + active.saveSha256 +
                "|evidence=" + Path.GetFileName(evidence) + "|mode=in_memory_api_values");
        }

        private static bool IsReparse(string path)
        {
            return (File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0;
        }

        private static string FileHash(string path)
        {
            using (var hash = SHA256.Create())
            using (var stream = File.OpenRead(path))
                return BitConverter.ToString(hash.ComputeHash(stream)).Replace("-", "").ToLowerInvariant();
        }

        internal static string Field(string value)
        {
            return (value ?? "").Replace('|', '_').Replace('=', '_')
                .Replace('\r', ' ').Replace('\n', ' ');
        }

        private void Event(string name, string fields)
        {
            log.LogInfo("SPRITESUITE_HEALTH_QA|event=" + name + "|phase=" + phase +
                "|frame=" + frame + "|" + fields);
        }

        private void Enter(Phase next, int timeout = PhaseTimeoutSeconds)
        {
            phase = next;
            phaseFrame = frame;
            deadline = DateTime.UtcNow.AddSeconds(timeout);
            screenshot = null;
        }

        private void OnLoadSave(LoadSaveGameEventArgs args)
        {
            if (args == null || args.Phase != EventHookPhase.Post || args.LoadingEditorMap ||
                !string.Equals(args.FileName, save, StringComparison.OrdinalIgnoreCase)) return;
            Volatile.Write(ref lastLoadFrame, Volatile.Read(ref frame));
            Interlocked.Increment(ref loadPosts);
            Event("save_post", "load_posts=" + loadPosts + "|save_sha256=" + saveSha256);
        }

        private void RequestLoad(Phase next)
        {
            if (!string.Equals(FileHash(save), saveSha256, StringComparison.Ordinal))
                throw new InvalidOperationException("qa_save_changed");
            RestorePause();
            var header = MapFileManager.Instance.GetFileInfoFromFileName(
                save, "SpriteSuite_Damage_Test.sav", 0, true);
            if (header == null) header = new FileHeader {
                fileName = save, display_filename = "SpriteSuite QA Damage"
            };
            expectedLoadPost = loadPosts + 1;
            Enter(next);
            Event("load_requested", "expected_post=" + expectedLoadPost +
                "|save_sha256=" + saveSha256);
            EditorDirector.instance.loadSaveGame(save, "SpriteSuite QA Damage", header);
        }

        private bool Loaded()
        {
            return Volatile.Read(ref loadPosts) >= expectedLoadPost &&
                frame - Volatile.Read(ref lastLoadFrame) >= SettleFrames &&
                GameMap.instance != null;
        }

        private bool Same(GameBuildingManagerAPI api)
        {
            return api != null && map != null && map == GameMap.instance && id > 0 &&
                api.IsValid(id) && api.GetGlobalId(id) == global && (int)api.GetType(id) == TargetType;
        }

        private bool Capture(GameBuildingManagerAPI api, int candidate, int wantedGlobal)
        {
            if (api == null || !api.IsValid(candidate) || (int)api.GetType(candidate) != TargetType ||
                api.GetGlobalId(candidate) != wantedGlobal) return false;
            int full = api.GetMaxHealth(candidate);
            if (full <= 0 || full > short.MaxValue || api.GetCurrentHealth(candidate) != full ||
                api.GetOnFireTicks(candidate) != 0) return false;
            map = GameMap.instance;
            id = candidate;
            global = wantedGlobal;
            maximum = full;
            int[] cells = api.GetOccupiedTileIds(id);
            if (cells == null || cells.Length == 0) return false;
            baseline.Clear();
            var tiles = GameTileManagerAPI.Instance;
            foreach (int cell in cells)
            {
                if (!tiles.IsValidTileId(cell) || tiles.GetTileBuildingId(cell) != id) continue;
                var xy = tiles.GetTileVectorFromId(cell);
                GameMapTile tile = map.getMapTile(xy.X, xy.Y);
                if (tile == null || tile.tileImage == null ||
                    tile.tileImage.name.StartsWith("SpriteSuite:", StringComparison.Ordinal)) continue;
                Sprite rendered = Rendered(tile, xy.X, xy.Y);
                if (rendered != tile.tileImage) continue;
                baseline.Add(new TileSample { X = xy.X, Y = xy.Y, Original = rendered });
            }
            if (baseline.Count == 0)
            {
                var xy = tiles.GetTileVectorFromId(cells[0]);
                Focus(map.getMapTile(xy.X, xy.Y), xy.X, xy.Y);
                return false;
            }
            var center = baseline[baseline.Count / 2];
            Focus(map.getMapTile(center.X, center.Y), center.X, center.Y);
            return true;
        }

        private static Sprite Rendered(GameMapTile tile, int x, int y)
        {
            if (tile == null || tile.tilemapRef == null) return null;
            return tile.tilemapRef.GetSprite(new Vector3Int(x, y, 0));
        }

        private static void Focus(GameMapTile tile, int x, int y)
        {
            if (tile == null || tile.tilemapRef == null || CameraControls2D.instance == null) return;
            Vector3 center = tile.tilemapRef.GetCellCenterWorld(new Vector3Int(x, y, 0));
            CameraControls2D.instance.setCameraPos(center.x, center.y + tile.height);
        }

        private bool CaptureOriginal(GameBuildingManagerAPI api)
        {
            if (api == null || GameMap.instance == null) return false;
            int[] alive = api.GetAllAliveBuildings();
            if (alive == null) return false;
            foreach (int candidate in alive)
                if (Capture(api, candidate, TargetGlobalId)) return true;
            return false;
        }

        private void SetPaused(bool value)
        {
            if (!changedPause) pausedBefore = Director.instance.Paused;
            Director.instance.SetPausedState(value);
            changedPause = true;
        }

        private void RestorePause()
        {
            if (changedPause && Director.instance != null) Director.instance.SetPausedState(pausedBefore);
            changedPause = false;
        }

        private void Set(GameBuildingManagerAPI api, Phase next, int hp, ushort fire)
        {
            if (!Same(api)) throw new InvalidOperationException("building_identity_changed");
            changedHp = true;
            api.SetCurrentHealth(id, checked((short)hp));
            api.SetOnFireTicks(id, fire);
            Enter(next);
            Event("set_values", "building_id=" + id + "|global_id=" + global +
                "|requested_hp=" + hp + "|requested_fire_ticks=" + fire +
                "|hp=" + api.GetCurrentHealth(id) + "|max=" + api.GetMaxHealth(id) +
                "|fire_ticks=" + api.GetOnFireTicks(id));
        }

        private bool Observe(GameBuildingManagerAPI api, int hp, bool burning,
            string expectedStage, bool image = true)
        {
            if (!Same(api)) throw new InvalidOperationException("building_identity_changed");
            if (frame - phaseFrame < SettleFrames) return false;
            int hpActual = api.GetCurrentHealth(id);
            int fire = api.GetOnFireTicks(id);
            if (hpActual != hp || (fire > 0) != burning)
            {
                if ((frame - phaseFrame) % 120 == 0)
                    Event("waiting_values", "expected_hp=" + hp + "|hp=" + hpActual +
                        "|fire_ticks=" + fire);
                return false;
            }
            if (screenshot != null)
                return File.Exists(screenshot) && new FileInfo(screenshot).Length > 32 &&
                    frame - phaseFrame >= SettleFrames + 3;

            int fieldMatches = 0, renderedMatches = 0;
            foreach (TileSample sample in baseline)
            {
                GameMapTile tile = map.getMapTile(sample.X, sample.Y);
                Sprite field = tile == null ? null : tile.tileImage;
                Sprite rendered = Rendered(tile, sample.X, sample.Y);
                bool matched = expectedStage == null ? field == sample.Original :
                    field != null && field.name.StartsWith(expectedStage, StringComparison.Ordinal);
                if (matched) fieldMatches++;
                if (matched && rendered == field) renderedMatches++;
            }
            if (renderedMatches != baseline.Count || renderedMatches == 0)
            {
                if ((frame - phaseFrame) % 120 == 0)
                    Event("waiting_renderer", "baseline_tiles=" + baseline.Count +
                        "|field_matches=" + fieldMatches + "|rendered_matches=" + renderedMatches +
                        "|stage=" + (expectedStage ?? "original"));
                return false;
            }
            Event("observed", "building_id=" + id + "|global_id=" + global +
                "|type=" + TargetType + "|hp=" + hpActual + "|max=" + api.GetMaxHealth(id) +
                "|fire_ticks=" + fire + "|baseline_tiles=" + baseline.Count +
                "|field_matches=" + fieldMatches + "|rendered_matches=" + renderedMatches +
                "|stage=" + (expectedStage ?? "original"));
            if (!image) return true;
            screenshot = Path.Combine(evidence, phase + ".png");
            ScreenCapture.CaptureScreenshot(screenshot);
            Event("screenshot_requested", "file=" + Path.GetFileName(screenshot) +
                "|width=" + Screen.width + "|height=" + Screen.height);
            return false;
        }

        private unsafe void RemoveForRebuild(GameBuildingManagerAPI api)
        {
            GameBuilding* data;
            if (!Same(api) || !api.TryGetBuildingById(id, out data))
                throw new InvalidOperationException("rebuild_target_missing");
            owner = api.GetOwner(id);
            buildX = data->r_TilePositionXBegin;
            buildY = data->r_TilePositionYBegin;
            elevation = data->r_HeightElevation;
            visualOwner = checked((int)data->r_SpritePlayerColorId);
            variation = data->r_SpriteVariationIndex;
            rebuilt = true;
            SetPaused(false);
            if (!api.DeleteBuildingSafe(id)) throw new InvalidOperationException("delete_failed");
            Enter(Phase.Removed);
            Event("delete_requested", "building_id=" + id + "|global_id=" + global +
                "|x=" + buildX + "|y=" + buildY);
        }

        private void Spawn(GameBuildingManagerAPI api)
        {
            if (Same(api) || api.GetAllAliveBuildings() == null) return;
            var tiles = GameTileManagerAPI.Instance;
            int tile = tiles.GetTileId(buildX, buildY);
            if (!tiles.IsValidTileId(tile) || tiles.GetTileBuildingId(tile) != 0) return;
            Event("removed", "building_id=" + id + "|global_id=" + global +
                "|tile_owner=0|x=" + buildX + "|y=" + buildY);
            long result = api.Create(owner, buildX, buildY, checked((short)elevation),
                (eStructs)TargetType, 1, visualOwner, variation);
            Enter(Phase.NewBaseline);
            Event("create_requested", "native_result=" + result + "|previous_id=" + id +
                "|previous_global_id=" + global);
        }

        private void OnBeforeRender()
        {
            if (Thread.CurrentThread.ManagedThreadId != mainThread) return;
            frame++;
            try
            {
                if (DateTime.UtcNow > deadline)
                    throw new TimeoutException("phase_timeout");
                var api = GameBuildingManagerAPI.Instance;
                if (phase == Phase.Ready)
                {
                    if (frame >= 1200 && Director.instance != null && EditorDirector.instance != null &&
                        MapFileManager.Instance != null && CrusaderDE.MainViewModel.Instance != null &&
                        CrusaderDE.MainViewModel.Instance.HUDIngameMenu != null)
                        RequestLoad(Phase.Baseline);
                    return;
                }
                if (phase == Phase.Baseline || phase == Phase.ReloadBaseline || phase == Phase.Cleanup)
                {
                    if (!Loaded()) return;
                    if (screenshot == null && !CaptureOriginal(api)) return;
                    if (!Observe(api, maximum, false, null, phase != Phase.Cleanup)) return;
                    if (phase == Phase.Cleanup)
                    {
                        rebuilt = false;
                        changedHp = false;
                        Event("completed", "verified_save_posts=" + loadPosts +
                            "|unchanged_save_sha256=" + FileHash(save));
                        Finish(0);
                        return;
                    }
                    SetPaused(true);
                    Set(api, phase == Phase.Baseline ? Phase.Mechanical : Phase.ReloadMechanical,
                        maximum * 60 / 100, 0);
                    return;
                }
                switch (phase)
                {
                    case Phase.Mechanical:
                        if (Observe(api, maximum * 60 / 100, false, MechanicalStage))
                            Set(api, Phase.Burning, maximum * 30 / 100, 1500);
                        break;
                    case Phase.Burning:
                        if (Observe(api, maximum * 30 / 100, true, FireStage))
                            Set(api, Phase.Extinguished, maximum * 35 / 100, 0);
                        break;
                    case Phase.Extinguished:
                        if (Observe(api, maximum * 35 / 100, false, FireStage))
                            Set(api, Phase.Repaired, maximum, 0);
                        break;
                    case Phase.Repaired:
                        if (Observe(api, maximum, false, null))
                            Set(api, Phase.BeforeReload, maximum * 30 / 100, 1500);
                        break;
                    case Phase.BeforeReload:
                        if (Observe(api, maximum * 30 / 100, true, FireStage, false))
                            RequestLoad(Phase.ReloadBaseline);
                        break;
                    case Phase.ReloadMechanical:
                        if (Observe(api, maximum * 60 / 100, false, MechanicalStage))
                            Set(api, Phase.ReloadRepaired, maximum, 0);
                        break;
                    case Phase.ReloadRepaired:
                        if (Observe(api, maximum, false, null, false))
                            RemoveForRebuild(api);
                        break;
                    case Phase.Removed:
                        Spawn(api);
                        break;
                    case Phase.NewBaseline:
                        if (screenshot == null)
                        {
                            var tiles = GameTileManagerAPI.Instance;
                            int cell = tiles.GetTileId(buildX, buildY);
                            int newId = tiles.GetTileBuildingId(cell);
                            if (newId <= 0 || !api.IsValid(newId)) return;
                            int newGlobal = api.GetGlobalId(newId);
                            if (newGlobal <= 0 || newGlobal == TargetGlobalId ||
                                !Capture(api, newId, newGlobal)) return;
                        }
                        if (Observe(api, maximum, false, null))
                        {
                            SetPaused(true);
                            Set(api, Phase.NewMechanical, maximum * 60 / 100, 0);
                        }
                        break;
                    case Phase.NewMechanical:
                        if (Observe(api, maximum * 60 / 100, false, MechanicalStage))
                            Set(api, Phase.NewRepaired, maximum, 0);
                        break;
                    case Phase.NewRepaired:
                        if (Observe(api, maximum, false, null, false))
                            RequestLoad(Phase.Cleanup);
                        break;
                }
            }
            catch (Exception error)
            {
                Event("failed", "reason=" + Field(error.GetType().Name + ": " + error.Message));
                Restore();
                Finish(1);
            }
        }

        private void Finish(int exitCode)
        {
            Detach();
            if (quitOnFinish) Application.Quit(exitCode);
        }

        private void Restore()
        {
            try
            {
                var api = GameBuildingManagerAPI.Instance;
                if (changedHp && Same(api))
                {
                    api.SetCurrentHealth(id, checked((short)maximum));
                    api.SetOnFireTicks(id, 0);
                }
                RestorePause();
                if (rebuilt)
                    Event("discard_session_required", "reason=rebuild_was_memory_only");
            }
            catch (Exception error)
            {
                Event("restore_failed", "reason=" + Field(error.Message));
            }
        }

        private void OnQuit()
        {
            Restore();
            Detach();
        }

        private void Detach()
        {
            Application.onBeforeRender -= OnBeforeRender;
            Application.quitting -= OnQuit;
            loadSubscription.Dispose();
            if (ReferenceEquals(active, this)) active = null;
        }
    }
}

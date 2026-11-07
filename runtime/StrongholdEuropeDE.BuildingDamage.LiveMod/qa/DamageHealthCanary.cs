// Isolated integration QA only: simulate ACTUAL in-game building HP and fire.
// This plugin is deliberately separate from the production sprite renderer.
// It is never included by build_windows.ps1, only compiled with the QA command.
using System;
using System.Threading;
using BepInEx;
using BepInEx.Logging;
using SHCDESE.API;
using UnityEngine;

namespace SpriteSuite.BuildingDamage.QA
{
    [BepInPlugin("org.spritesuite.hp-fire-healthqa", "SpriteSuite HP Fire Actual Value QA", "0.1.0")]
    public sealed class DamageHealthQaHost : BaseUnityPlugin
    {
        private void Awake()
        {
            Logger.LogInfo("SPRITESUITE_HEALTH_QA|event=host_awake");
            ActualHealthCanary.Start(Logger);
        }

        private void OnDestroy()
        {
            Logger.LogInfo("SPRITESUITE_HEALTH_QA|event=host_destroyed|static_runner=true");
        }
    }

    internal sealed class ActualHealthCanary
    {
        private const int TargetGlobalId = 661027;  // measured QA save instance
        private const int TargetBuildingType = 104; // real SHCDE graphic 8x8 model
        private const int WaitFrames = 170;        // each phase lets the renderer poll
        private static ActualHealthCanary _active;

        private readonly ManualLogSource log;
        private readonly int mainThread;
        private int frame;
        private int phase;
        private int phaseStart;
        private int buildingId;
        private int globalId;
        private int originalHp;
        private int originalMax;
        private ushort originalFire;
        private GameMap originalMap;
        private bool captured;

        private ActualHealthCanary(ManualLogSource logger)
        {
            log = logger;
            mainThread = Thread.CurrentThread.ManagedThreadId;
        }

        internal static void Start(ManualLogSource logger)
        {
            if (_active != null) return;
            var monitor = new ActualHealthCanary(logger);
            _active = monitor;
            Application.onBeforeRender += monitor.OnBeforeRender;
            Application.quitting += monitor.OnQuit;
            logger.LogInfo("SPRITESUITE_HEALTH_QA|event=started|target_global_id=" +
                TargetGlobalId + "|target_type=" + TargetBuildingType);
        }

        private bool StillSame(GameBuildingManagerAPI buildings)
        {
            return captured && buildings != null && originalMap == GameMap.instance &&
                buildings.IsValid(buildingId) &&
                buildings.GetGlobalId(buildingId) == globalId &&
                (int)buildings.GetType(buildingId) == TargetBuildingType;
        }

        private void Capture(GameBuildingManagerAPI buildings)
        {
            if (buildings == null || GameMap.instance == null) return;
            int[] ids = buildings.GetAllAliveBuildings();
            if (ids == null) return;
            foreach (int id in ids)
            {
                if (id <= 0 || !buildings.IsValid(id)) continue;
                if (buildings.GetGlobalId(id) != TargetGlobalId ||
                    (int)buildings.GetType(id) != TargetBuildingType) continue;
                int max = buildings.GetMaxHealth(id);
                int hp = buildings.GetCurrentHealth(id);
                if (max <= 0 || hp <= 0) continue;
                originalMap = GameMap.instance;
                globalId = TargetGlobalId;
                buildingId = id;
                originalMax = max;
                originalHp = hp;
                originalFire = buildings.GetOnFireTicks(id);
                captured = true;
                phase = 1;
                phaseStart = frame;
                log.LogInfo("SPRITESUITE_HEALTH_QA|event=captured|building_id=" + id +
                    "|global_id=" + globalId + "|hp=" + hp + "|max=" + max +
                    "|fire_ticks=" + originalFire);
                return;
            }
        }

        private void Set(GameBuildingManagerAPI buildings, int hp, ushort fire, string label)
        {
            // Control one known instance in one isolated QA scene, never any
            // original Steam save, other buildings or third-party mods.
            if (!StillSame(buildings)) throw new InvalidOperationException("QA instance changed");
            int requestedHp = Math.Max(1, Math.Min(short.MaxValue, hp));
            buildings.SetCurrentHealth(buildingId, checked((short)requestedHp));
            buildings.SetOnFireTicks(buildingId, fire);
            log.LogInfo("SPRITESUITE_HEALTH_QA|event=" + label +
                "|global_id=" + globalId + "|building_id=" + buildingId +
                "|requested_hp=" + requestedHp + "|actual_hp=" +
                buildings.GetCurrentHealth(buildingId) + "|max=" +
                buildings.GetMaxHealth(buildingId) +
                "|actual_fire_ticks=" + buildings.GetOnFireTicks(buildingId));
        }

        private void OnBeforeRender()
        {
            if (Thread.CurrentThread.ManagedThreadId != mainThread) return;
            frame++;
            try
            {
                var api = GameBuildingManagerAPI.Instance;
                if (!captured)
                {
                    if (frame % 20 == 0) Capture(api);
                    return;
                }
                if (!StillSame(api))
                {
                    log.LogWarning("SPRITESUITE_HEALTH_QA|event=identity_changed|abort=true");
                    Detach(false);
                    return;
                }
                if (frame - phaseStart < WaitFrames) return;
                switch (phase)
                {
                    case 1:
                        Set(api, originalMax * 60 / 100, 0, "mechanical_hp_changed");
                        break;
                    case 2:
                        Set(api, originalMax * 30 / 100, 1500, "fire_started");
                        break;
                    case 3:
                        Set(api, originalMax * 35 / 100, 0, "fire_extinguished");
                        break;
                    case 4:
                        Set(api, originalHp, originalFire, "fully_repaired");
                        break;
                    case 5:
                        log.LogInfo("SPRITESUITE_HEALTH_QA|event=completed|global_id=" +
                            globalId + "|hp=" + api.GetCurrentHealth(buildingId) +
                            "|fire_ticks=" + api.GetOnFireTicks(buildingId));
                        Detach(false);
                        return;
                    default:
                        return;
                }
                phase++;
                phaseStart = frame;
            }
            catch (Exception error)
            {
                log.LogError("SPRITESUITE_HEALTH_QA|event=exception|phase=" + phase +
                    "|error=" + error.GetType().Name + "|reason=" + error.Message);
                Detach(true);
            }
        }

        private void OnQuit()
        {
            Detach(true);
        }

        private void Detach(bool restore)
        {
            Application.onBeforeRender -= OnBeforeRender;
            Application.quitting -= OnQuit;
            if (restore)
            {
                try
                {
                    var api = GameBuildingManagerAPI.Instance;
                    if (StillSame(api))
                    {
                        api.SetCurrentHealth(buildingId, checked((short)originalHp));
                        api.SetOnFireTicks(buildingId, originalFire);
                        log.LogInfo("SPRITESUITE_HEALTH_QA|event=original_hp_restored|hp=" +
                            api.GetCurrentHealth(buildingId) +
                            "|fire_ticks=" + api.GetOnFireTicks(buildingId));
                    }
                }
                catch (Exception error)
                {
                    log.LogWarning("SPRITESUITE_HEALTH_QA|event=restore_failed|reason=" +
                        error.GetType().Name);
                }
            }
            if (ReferenceEquals(_active, this)) _active = null;
        }
    }
}

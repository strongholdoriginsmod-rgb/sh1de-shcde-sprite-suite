// Optional read-only SHCDE entity/HP/owner inspector compiled against the
// installed Script Extender, with no native detour or game-state mutation.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Threading;
using BepInEx;
using BepInEx.Logging;
using CrusaderDE;
using SHCDESE.API;
using UnityEngine;

namespace SpriteSuite.ShcdeInspector
{
    [BepInPlugin("org.spritesuite.shcde.inspector", "SpriteSuite SHCDE Inspector", "0.1.0")]
    public sealed class InspectorHost : BaseUnityPlugin
    {
        private void Awake()
        {
            InspectorObserver.Start(Logger);
            Logger.LogInfo("SHCDE_INSPECT|event=host_started|read_only=true");
        }
        private void OnDestroy()
        {
            // This host component can be destroyed by the BepInEx chainloader.
            Logger.LogInfo("SHCDE_INSPECT|event=host_destroyed|observer_independent=true");
        }
    }

    internal sealed class InspectorObserver
    {
        private static InspectorObserver _active;
        private readonly ManualLogSource _log;
        private readonly int _thread;
        private readonly Dictionary<string, string> _previous = new Dictionary<string, string>(StringComparer.Ordinal);
        private readonly string _configPath;
        private GameMap _map;
        private DateTime _configModified;
        private int _frame;
        private int _reports;
        private int _errors;
        private int _interval = 180;
        private int _maxReports = 10000;
        private int _maxBuildings = 512;
        private int _maxUnits = 512;
        private int _globalFilter;
        private bool _buildings = true;
        private bool _units = true;

        private InspectorObserver(ManualLogSource logger)
        {
            _log = logger;
            _thread = Thread.CurrentThread.ManagedThreadId;
            _configPath = Path.Combine(Paths.GameRootPath, "BepInEx", "plugins",
                                       "SpriteSuiteShcdeInspector", "inspector.ini");
            LoadConfig();
        }

        internal static void Start(ManualLogSource logger)
        {
            if (_active != null) return;
            var observer = new InspectorObserver(logger);
            _active = observer;
            Application.onBeforeRender += observer.OnRender;
            Application.quitting += observer.OnQuit;
            logger.LogInfo("SHCDE_INSPECT|event=started|read_only=true|thread=" + observer._thread);
        }

        private void LoadConfig()
        {
            if (!File.Exists(_configPath)) return;
            DateTime stamp = File.GetLastWriteTimeUtc(_configPath);
            if (stamp == _configModified) return;
            foreach (string raw in File.ReadAllLines(_configPath))
            {
                string line = raw.Trim();
                int sep = line.IndexOf('=');
                if (sep <= 0 || line.StartsWith("#")) continue;
                string key = line.Substring(0, sep).Trim().ToLowerInvariant();
                string value = line.Substring(sep + 1).Trim();
                int number;
                if (int.TryParse(value, NumberStyles.Integer, CultureInfo.InvariantCulture, out number))
                {
                    if (key == "interval_frames" && number > 0) _interval = number;
                    else if (key == "max_reports" && number > 0) _maxReports = number;
                    else if (key == "max_units" && number > 0) _maxUnits = number;
                    else if (key == "max_buildings" && number > 0) _maxBuildings = number;
                    else if (key == "global_id" && number >= 0) _globalFilter = number;
                }
                bool flag;
                if (bool.TryParse(value, out flag))
                {
                    if (key == "buildings") _buildings = flag;
                    if (key == "units") _units = flag;
                }
            }
            _configModified = stamp;
            _previous.Clear();
            _log.LogInfo("SHCDE_INSPECT|event=configuration|interval=" + _interval +
                         "|filter_global_id=" + _globalFilter);
        }

        private void OnRender()
        {
            if (Thread.CurrentThread.ManagedThreadId != _thread) return;
            _frame++;
            if (_frame % 300 == 0)
                try { LoadConfig(); } catch (Exception ex) { Error("config", ex); }
            if (_frame % _interval != 0 || _reports >= _maxReports) return;
            try
            {
                if (!object.ReferenceEquals(_map, GameMap.instance))
                {
                    _map = GameMap.instance;
                    _previous.Clear();
                    _log.LogInfo("SHCDE_INSPECT|event=map_changed|frame=" + _frame);
                }
                if (_map == null) return;
                if (_buildings) Buildings();
                if (_units) Units();
            }
            catch (Exception ex) { Error("poll", ex); }
        }

        private void Observe(string kind, int id, int global, int type,
                             int hp, int max, string extra)
        {
            if (global <= 0 || (_globalFilter != 0 && global != _globalFilter)) return;
            string key = kind + ":" + global;
            string state = id + ":" + type + ":" + hp + ":" + max + ":" + extra;
            string previous;
            if (_previous.TryGetValue(key, out previous) && previous == state) return;
            _previous[key] = state;
            _reports++;
            _log.LogInfo("SHCDE_INSPECT|event=" + kind + "|frame=" + _frame +
                "|id=" + id + "|global_id=" + global + "|type=" + type +
                "|hp=" + hp + "|max_hp=" + max + "|" + extra + "|read_only=true");
        }

        private void Buildings()
        {
            var api = GameBuildingManagerAPI.Instance;
            if (api == null) return;
            int[] ids = api.GetAllAliveBuildings();
            if (ids == null) return;
            int seen = 0;
            foreach (int id in ids)
            {
                if (seen++ >= _maxBuildings || _reports >= _maxReports) break;
                if (id <= 0 || !api.IsValid(id)) continue;
                int global = api.GetGlobalId(id);
                int type = (int)api.GetType(id);
                int hp = api.GetCurrentHealth(id);
                int max = api.GetMaxHealth(id);
                int fire = api.GetOnFireTicks(id);
                if (!api.IsValid(id) || api.GetGlobalId(id) != global) continue;
                Observe("building", id, global, type, hp, max, "fire_ticks=" + fire);
            }
        }

        private void Units()
        {
            var api = GameUnitManagerAPI.Instance;
            if (api == null) return;
            int[] ids = api.GetAllAliveUnits();
            if (ids == null) return;
            int seen = 0;
            foreach (int id in ids)
            {
                if (seen++ >= _maxUnits || _reports >= _maxReports) break;
                if (id <= 0 || !api.IsValid(id)) continue;
                int global = api.GetGlobalId(id);
                int type = (int)api.GetType(id);
                int hp = api.GetCurrentHealth(id);
                int max = api.GetMaxHealth(id);
                int owner = api.GetOwner(id);
                if (!api.IsValid(id) || api.GetGlobalId(id) != global) continue;
                Observe("unit", id, global, type, hp, max, "owner=" + owner);
            }
        }

        private void Error(string context, Exception exception)
        {
            if (++_errors <= 12)
                _log.LogWarning("SHCDE_INSPECT|event=read_error|context=" + context +
                    "|exception=" + exception.GetType().Name);
        }

        private void OnQuit()
        {
            Application.onBeforeRender -= OnRender;
            Application.quitting -= OnQuit;
            if (ReferenceEquals(_active, this)) _active = null;
            _log.LogInfo("SHCDE_INSPECT|event=shutdown|records=" + _reports +
                         "|sprite_writes=0|gameplay_writes=0");
        }
    }
}

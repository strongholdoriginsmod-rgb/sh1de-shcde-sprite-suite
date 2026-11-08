// Optional creator-owned SHCDE unit, combat and building balance rules.
// All method names/signatures are verified against the selected SHCDESE API.
// This is an independent BepInEx plugin, not a patch of CrusaderDE.dll.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Threading;
using BepInEx;
using BepInEx.Logging;
using CrusaderDE;
using SHCDESE.API;
using SHCDESE.Interop;
using UnityEngine;

namespace SpriteSuite.ShcdeGameplay
{
    [BepInPlugin("org.spritesuite.shcde.gameplay", "SpriteSuite Gameplay Rules", "0.1.0")]
    public sealed class GameplayHost : BaseUnityPlugin
    {
        private void Awake() { GameplayObserver.Start(Logger); }
        private void OnDestroy()
        {
            Logger.LogInfo("SHCDE_RULES|event=host_destroyed|static_runner=true");
        }
    }

    internal sealed class Rule
    {
        public string Kind;
        public int Type;
        public uint Value;
    }
    internal sealed class AppliedRule
    {
        public Rule Rule;
        public uint Original;
    }

    internal sealed class GameplayObserver
    {
        private static GameplayObserver _active;
        private readonly ManualLogSource _log;
        private readonly int _thread;
        private readonly string _file;
        private readonly List<AppliedRule> _activeRules = new List<AppliedRule>();
        private DateTime _modified;
        private int _frame;
        private int _errors;
        private bool _ready;

        private GameplayObserver(ManualLogSource log)
        {
            _log = log;
            _thread = Thread.CurrentThread.ManagedThreadId;
            _file = Path.Combine(Paths.GameRootPath, "BepInEx", "plugins",
                                 "SpriteSuiteGameplayRules", "rules.tsv");
        }

        internal static void Start(ManualLogSource log)
        {
            if (_active != null) return;
            var observer = new GameplayObserver(log);
            _active = observer;
            Application.onBeforeRender += observer.OnRender;
            Application.quitting += observer.OnQuit;
            log.LogInfo("SHCDE_RULES|event=start|config=rules.tsv|gameplay_write_only_when_configured=true");
        }

        private static List<Rule> ParseRules(string text)
        {
            var rules = new List<Rule>();
            foreach (string raw in text.Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries))
            {
                string line = raw.Trim();
                if (line.Length == 0 || line.StartsWith("#")) continue;
                string[] parts = line.Split('\t');
                if (parts.Length != 3) throw new FormatException("Rule must have three tab-separated columns");
                string kind = parts[0].Trim().ToLowerInvariant();
                if (kind != "unit-hp" && kind != "building-hp" && kind != "unit-range")
                    throw new FormatException("Unknown rule type: " + kind);
                int type;
                uint number;
                if (!int.TryParse(parts[1], NumberStyles.Integer,
                        CultureInfo.InvariantCulture, out type) ||
                    !uint.TryParse(parts[2], NumberStyles.Integer,
                        CultureInfo.InvariantCulture, out number))
                    throw new FormatException("Expected integer ID and nonnegative value");
                if (kind == "unit-range" && number > int.MaxValue)
                    throw new FormatException("Unit attack range exceeds engine int");
                rules.Add(new Rule { Kind = kind, Type = type, Value = number });
            }
            return rules;
        }

        private void OnRender()
        {
            if (Thread.CurrentThread.ManagedThreadId != _thread) return;
            if (++_frame % 60 != 0) return;
            if (GameMap.instance == null ||
                GameUnitManagerAPI.Instance == null ||
                GameBuildingManagerAPI.Instance == null) return;
            try
            {
                if (!_ready)
                {
                    _ready = true;
                    _log.LogInfo("SHCDE_RULES|event=game_ready|frame=" + _frame);
                }
                if (!File.Exists(_file)) return;
                DateTime modified = File.GetLastWriteTimeUtc(_file);
                if (modified == _modified) return;
                // Parse before changing any live state; malformed edits do not
                // erase the last working rule set.
                List<Rule> next = ParseRules(File.ReadAllText(_file));
                Restore();
                foreach (Rule rule in next)
                    try { Apply(rule); }
                    catch (Exception e) { Report("apply:" + rule.Kind, e); }
                _modified = modified;
                _log.LogInfo("SHCDE_RULES|event=rules_reloaded|count=" + next.Count +
                    "|applied=" + _activeRules.Count);
            }
            catch (Exception ex) { Report("reload", ex); }
        }

        private void Apply(Rule rule)
        {
            var units = GameUnitManagerAPI.Instance;
            var buildings = GameBuildingManagerAPI.Instance;
            uint previous;
            if (rule.Kind == "unit-hp")
            {
                var type = (eChimps)rule.Type;
                previous = units.GetDefaultHealth(type);
                units.SetDefaultHealth(type, rule.Value);
            }
            else if (rule.Kind == "building-hp")
            {
                var type = (eStructs)rule.Type;
                int value = buildings.GetDefaultHealth(type);
                if (value < 0) throw new InvalidOperationException("Negative original health");
                previous = (uint)value;
                buildings.SetDefaultHealth(type, rule.Value);
            }
            else
            {
                var type = (eChimps)rule.Type;
                int value = units.GetUnitAttackRange(type);
                if (value < 0) throw new InvalidOperationException("Negative original attack range");
                previous = (uint)value;
                if (!units.SetUnitAttackRange(type, checked((int)rule.Value)))
                    throw new InvalidOperationException("Script Extender rejected attack range");
            }
            _activeRules.Add(new AppliedRule { Rule = rule, Original = previous });
            _log.LogInfo("SHCDE_RULES|event=applied|kind=" + rule.Kind +
                "|type=" + rule.Type + "|before=" + previous +
                "|after=" + rule.Value);
        }

        private void Restore()
        {
            for (int i = _activeRules.Count - 1; i >= 0; --i)
            {
                AppliedRule item = _activeRules[i];
                var rule = item.Rule;
                try
                {
                    if (rule.Kind == "unit-hp")
                    {
                        var type = (eChimps)rule.Type;
                        var units = GameUnitManagerAPI.Instance;
                        if (units != null && units.GetDefaultHealth(type) == rule.Value)
                            units.SetDefaultHealth(type, item.Original);
                    }
                    else if (rule.Kind == "building-hp")
                    {
                        var type = (eStructs)rule.Type;
                        var buildings = GameBuildingManagerAPI.Instance;
                        if (buildings != null && buildings.GetDefaultHealth(type) == (int)rule.Value)
                            buildings.SetDefaultHealth(type, item.Original);
                    }
                    else
                    {
                        var type = (eChimps)rule.Type;
                        var units = GameUnitManagerAPI.Instance;
                        if (units != null && units.GetUnitAttackRange(type) == (int)rule.Value)
                            units.SetUnitAttackRange(type, (int)item.Original);
                    }
                    _log.LogInfo("SHCDE_RULES|event=restore_checked|kind=" + rule.Kind +
                        "|type=" + rule.Type);
                }
                catch (Exception ex) { Report("restore:" + rule.Kind, ex); }
            }
            _activeRules.Clear();
        }

        private void Report(string context, Exception ex)
        {
            if (++_errors <= 30)
                _log.LogWarning("SHCDE_RULES|event=error|context=" + context +
                                "|reason=" + ex.GetType().Name);
        }

        private void OnQuit()
        {
            Restore();
            Application.onBeforeRender -= OnRender;
            Application.quitting -= OnQuit;
            if (ReferenceEquals(_active, this)) _active = null;
            _log.LogInfo("SHCDE_RULES|event=shutdown|rules_cleared=true");
        }
    }
}

using System;
using System.Globalization;
using System.Linq;
using System.Text;
using BepInEx;
using CrusaderDE;
using HarmonyLib;
using SHCDESE.API;
using StrongholdEuropeDE.Runtime;
using UnityEngine;
using UnityObject = UnityEngine.Object;

namespace StrongholdEuropeDE.Diplomatie
{
    /// <summary>
    /// Die Diplomatie als eigenstaendiges Plugin.
    /// </summary>
    /// <remarks>
    /// Herausgeloest aus dem Europa-Mod, weil sie dort einkompiliert war: ein
    /// Neubau des Europa-Pakets mit "diplomacy": false hat sie am 05.09.2026
    /// stumm wieder abgeschaltet, ohne dass an der Diplomatie etwas geaendert
    /// worden waere. Als eigenes Plugin ueberlebt sie jede Auslieferung des
    /// Grafikpakets, und das Vorhandensein des Ordners ist der Schalter.
    ///
    /// Das Plugin ist bewusst duenn: es prueft die Faehigkeiten, meldet die
    /// Funktion beim Erweiterungswirt an und taktet sie. V1 und der getrennt
    /// gebaute V2-Nachfolger benutzen dadurch denselben bewaehrten Host sowie
    /// dieselben Transport-, Team-, Kampf- und UI-Sicherungen.
    /// </remarks>
#if DIPLOMACY_V2
    [BepInPlugin(
        PluginId,
        "Stronghold Crusader Diplomatie V2 (Private)",
    "2.3.9")]
    [BepInIncompatibility("strongholdeuropede.diplomatie.private")]
#else
    [BepInPlugin(
        PluginId,
        "Stronghold Europe Diplomatie (Private)",
        "1.1.0")]
#endif
    // V2 checks the available SE members at startup. A different release
    // may load; the image-specific native truce hook checks its own contract.
#if DIPLOMACY_V2
    [BepInDependency("000shcdese", BepInDependency.DependencyFlags.SoftDependency)]
#else
    [BepInDependency("000shcdese", "1.44.0")]
#endif
#if !DIPLOMACY_V2
    [BepInDependency(
        "strongholdeuropede.runtime.private",
        BepInDependency.DependencyFlags.SoftDependency)]
#endif
    public sealed class DiplomatiePlugin : BaseUnityPlugin
    {
#if DIPLOMACY_V2
        internal const string PluginId =
            "strongholdeuropede.diplomatie.v2.private";
        private const string HarmonyId =
            "strongholdeuropede.diplomatie.v2.harmony";
        private const string FeatureId = "gameplay.diplomacy.v2";
        private const string RuntimeLogPrefix =
            "SEDE_RUNTIME_V2|lane=diplomacy_v2";
#else
        internal const string PluginId = "strongholdeuropede.diplomatie.private";
        private const string HarmonyId = "strongholdeuropede.diplomatie.harmony";
        private const string FeatureId = "gameplay.diplomacy";
        private const string RuntimeLogPrefix =
            "SEDE_RUNTIME_V1|lane=diplomacy";
#endif

        private Harmony _harmony;
        private ExtensionFeatureHost _extensionHost;
        private DiplomacyFeature _diplomacy;
#if !DIPLOMACY_V2
        private EuropeCapabilities _capabilities;
#endif
        private GameObject _hostObject;
        private DiplomatiePersistentHost _host;
        private bool _terminalLogged;
        private bool _featureFailureLogged;
        private bool _shuttingDown;
        private bool _applicationQuitting;
        private bool _rosterDiagnoseGeschrieben;
        private bool _rosterBereitGemeldet;
        private int _rosterTakte;

        private void Awake()
        {
            try
            {
                UnityObject.DontDestroyOnLoad(gameObject);

#if DIPLOMACY_V2
                // Unknown engines/extenders stay passive. The generated binary
                // identities are attested before any feature or hook activation;
                // member-name/arity checks cannot establish native ABI safety.
                CompatibilityReport report = DiplomatieCompatibilityGuard.Probe();
                Logger.LogInfo(
                    RuntimeLogPrefix + "|event=compatibility"
                    + "|status=" + (report.Compatible ? "ok" : "incompatible")
                    + "|bindings=" + report.BindingsPresent.ToString(
                        CultureInfo.InvariantCulture)
                    + "/" + report.BindingsChecked.ToString(
                        CultureInfo.InvariantCulture)
                    + "|attested=" + report.PrerequisitesAttested.ToString(
                        CultureInfo.InvariantCulture)
                    + "/" + report.PrerequisitesTotal.ToString(
                        CultureInfo.InvariantCulture)
                    + "|engine=" + (report.EngineAttested
                        ? "attested"
                        : "unverified:" + report.EngineDigestPrefix)
                    + "|contract=" + GeneratedCompatibilityContract.Sha256
                        .Substring(0, 12));
                foreach (string id in report.Unattested)
                {
                    Logger.LogWarning(
                        RuntimeLogPrefix + "|event=compatibility"
                        + "|status=unattested_prerequisite|id=" + id);
                }
                if (!report.EngineAttested)
                {
                    Logger.LogWarning(
                        RuntimeLogPrefix + "|event=compatibility"
                        + "|status=unverified_engine|reason="
                        + (report.EngineFailure ?? "unknown"));
                }
                // Entscheidung 09.09.2026: eine fremde Spielfassung laedt.
                // Sie wird aber benannt, damit ein Fehlerbericht von einer
                // ungeprueften Fassung als solcher zu erkennen ist.
                foreach (string drift in report.GameSideDrift)
                {
                    Logger.LogWarning(
                        RuntimeLogPrefix + "|event=compatibility"
                        + "|status=unattested_game_file|id=" + drift);
                }
                if (report.GameSideDrift.Count > 0)
                {
                    Logger.LogWarning(
                        RuntimeLogPrefix + "|event=compatibility"
                        + "|status=unverified_game_build|files="
                        + report.GameSideDrift.Count.ToString(
                            CultureInfo.InvariantCulture)
                        + "|note=loaded_anyway_by_user_request");
                }
                if (!report.Compatible)
                {
                    int shown = 0;
                    foreach (string missing in report.MissingAssemblies)
                    {
                        if (shown++ < 20)
                        {
                            Logger.LogError(RuntimeLogPrefix
                                + "|event=compatibility|status=missing_assembly|name=" + missing);
                        }
                    }
                    foreach (string missing in report.MissingTypes)
                    {
                        if (shown++ < 20)
                        {
                            Logger.LogError(RuntimeLogPrefix
                                + "|event=compatibility|status=missing_type|name=" + missing);
                        }
                    }
                    foreach (string missing in report.MissingMembers)
                    {
                        if (shown++ < 20)
                        {
                            Logger.LogError(RuntimeLogPrefix
                                + "|event=compatibility|status=missing_member|name=" + missing);
                        }
                    }
                    LogTerminal("failed", "incompatible:" + report.FirstProblem);
                    enabled = false;
                    return;
                }
#else
                _capabilities = EuropeCapabilities.Probe();
                Logger.LogInfo(_capabilities.Report);
                if (!_capabilities.Core)
                {
                    LogTerminal("failed", "core:" + _capabilities.CoreFailure);
                    enabled = false;
                    return;
                }
                if (!_capabilities.R3)
                {
                    // Kein harter Ausfall: ohne R3 laeuft die Diplomatie nicht,
                    // aber das Spiel und jedes andere Plugin bleiben unberuehrt.
                    LogTerminal("failed", "r3_unavailable");
                    enabled = false;
                    return;
                }
#endif

                _harmony = new Harmony(HarmonyId);
                _extensionHost = new ExtensionFeatureHost();
                DiplomacyFeature candidate = new DiplomacyFeature(
                    _harmony,
                    message => Logger.LogInfo(message),
                    message => Logger.LogWarning(message),
                    message => Logger.LogError(message));

                string registrationFailure;
                if (!_extensionHost.TryRegister(candidate, out registrationFailure))
                {
                    LogTerminal("failed", "claim_registration:" + registrationFailure);
                    ShutdownAndRollback("claim registration failed");
                    enabled = false;
                    return;
                }

                _extensionHost.ActivateAll();
                ExtensionFeatureSnapshot snapshot = FindSnapshot(FeatureId);
                if (snapshot == null || snapshot.State != ExtensionFeatureState.Active)
                {
                    LogTerminal(
                        "failed",
                        snapshot == null ? "missing_snapshot" : snapshot.Failure);
                    ShutdownAndRollback("activation failed");
                    enabled = false;
                    return;
                }

                _diplomacy = candidate;
                CreatePersistentHost();
                LogTerminal("active", null);
            }
            catch (Exception exception)
            {
                LogTerminal("failed", "startup_failure");
                Logger.LogError(
                    "Diplomatie failed closed; no unsupported patch remains active: "
                    + exception);
                ShutdownAndRollback("initialization failure");
                enabled = false;
            }
        }

        internal void DiplomatieTick()
        {
            if (_shuttingDown || _extensionHost == null)
            {
                return;
            }
            RosterDiagnose();
            try
            {
                _extensionHost.TickAll();
                ExtensionFeatureSnapshot snapshot = FindSnapshot(FeatureId);
                // Die eigentliche Feature-Referenz muss bis zum sicheren
                // Shutdown erhalten bleiben. RequiresFailClosedHooks kann nur
                // darüber feststellen, ob unbewiesene Team-/Transferzustände
                // weiterhin durch die nativen Schutz-Hooks eingefroren werden
                // müssen. Ein eigener Marker verhindert die Log-Flut.
                if (!_featureFailureLogged
                    && _diplomacy != null
                    && snapshot != null
                    && snapshot.State == ExtensionFeatureState.Failed)
                {
                    Logger.LogError(
                        RuntimeLogPrefix + "|event=feature"
                        + "|status=failed_closed|reason=" + SafeReason(snapshot.Failure));
                    _featureFailureLogged = true;
                }
            }
            catch (Exception exception)
            {
                Logger.LogError("Diplomatie tick encountered an error: " + exception);
            }
        }

        /// <summary>
        /// Eine Zeile je Karte: was die Aufstellungspruefung der Diplomatie
        /// tatsaechlich vorfindet.
        /// </summary>
        /// <remarks>
        /// CaptureRosterAndCoalitions wirft „offline skirmish does not have
        /// exactly one local human" fuer ZWEI verschiedene Lagen — der lokale
        /// Spieler steht nicht in der Lebendliste, ODER er ist im
        /// computer_register eingetragen. Am 05.09.2026 stand im Protokoll
        /// nur die Meldung, nicht welche Haelfte griff. Diese Zeile
        /// unterscheidet die beiden.
        ///
        /// Rein lesend, und ausschliesslich ueber Kennungen 1..8: die
        /// Lebendliste des Extenders fuehrt Spieler 0 mit, und eine Abfrage
        /// auf den beendet das Spiel wortlos.
        /// </remarks>
        private void RosterDiagnose()
        {
            try
            {
                GameData daten = GameData.Instance;
                object zustand = daten == null ? null : daten.lastGameState;
                if (daten == null || zustand == null)
                {
                    // Keine Karte geladen. Die Sperren fallen, damit die
                    // naechste Karte wieder ihre Zeilen schreibt.
                    _rosterDiagnoseGeschrieben = false;
                    _rosterBereitGemeldet = false;
                    _rosterTakte = 0;
                    return;
                }
                _rosterTakte++;

                GamePlayerManagerAPI spieler = GamePlayerManagerAPI.Instance;
                int lokal = spieler == null ? -1 : spieler.GetLocalPlayerId();
                int[] lebend = spieler == null
                    ? new int[0]
                    : (spieler.GetAlivePlayerIds() ?? new int[0]);

                // Zweite Zeile, genau einmal: der Augenblick, in dem die
                // Lebendliste zum ersten Mal steht. Ohne sie waere ein
                // wartender Bootstrap nicht von einem nie startenden zu
                // unterscheiden - beide schweigen.
                if (!_rosterBereitGemeldet && lebend.Length > 0)
                {
                    _rosterBereitGemeldet = true;
                    Logger.LogInfo(
                        RuntimeLogPrefix + "|event=roster_bereit"
                        + "|nach_takten=" + _rosterTakte.ToString(
                            CultureInfo.InvariantCulture)
                        + "|alive=[" + string.Join(
                            ",",
                            lebend.Select(
                                v => v.ToString(CultureInfo.InvariantCulture))
                                .ToArray())
                        + "]");
                }

                if (_rosterDiagnoseGeschrieben)
                {
                    return;
                }
                _rosterDiagnoseGeschrieben = true;

                var gueltig = new StringBuilder();
                var rechner = new StringBuilder();
                var mannschaften = new StringBuilder();
                for (int id = 1; id <= 8; id++)
                {
                    gueltig.Append(
                        daten.lastGameState.is_valid_player(id) ? 'x' : '-');
                    rechner.Append(
                        daten.lastGameState.is_skirmish_player(id) ? 'x' : '-');
                    // Die Teamnummer entscheidet, wen die Diplomatie fuer einen
                    // Startverbuendeten haelt - und damit, welche Sendung ueber
                    // die native Strecke geht. Der Spieler sieht davon nichts.
                    if (mannschaften.Length > 0)
                    {
                        mannschaften.Append(',');
                    }
                    mannschaften.Append(
                        spieler == null
                            ? "?"
                            : spieler.GetPlayerTeam(id).ToString(
                                CultureInfo.InvariantCulture));
                }
                int lokalesTeam = spieler == null || lokal < 1 || lokal > 8
                    ? -1
                    : spieler.GetPlayerTeam(lokal);

                Logger.LogInfo(
                    RuntimeLogPrefix + "|event=roster_diagnose"
                    + "|local=" + lokal.ToString(CultureInfo.InvariantCulture)
                    + "|game_player_id=" + daten.playerID.ToString(
                        CultureInfo.InvariantCulture)
                    + "|alive=[" + string.Join(
                        ",",
                        lebend.Select(
                            v => v.ToString(CultureInfo.InvariantCulture))
                            .ToArray())
                    + "]|alive_contains_local="
                    + (lokal >= 1 && lokal <= 8 && lebend.Contains(lokal)
                        ? "true"
                        : "false")
                    + "|valid_1_8=" + gueltig
                    + "|skirmish_1_8=" + rechner
                    + "|local_is_skirmish="
                    + (lokal >= 1 && lokal <= 8
                        && daten.lastGameState.is_skirmish_player(lokal)
                        ? "true"
                        : "false")
                    + "|local_team=" + lokalesTeam.ToString(
                        CultureInfo.InvariantCulture)
                    + "|teams_1_8=" + mannschaften
                    + "|startverbuendete=" + Startverbuendete(
                        spieler, lokalesTeam, lokal));
            }
            catch (Exception exception)
            {
                // Beobachtbarkeit darf keine Verfuegbarkeitsabhaengigkeit
                // werden: eine misslungene Diagnose bleibt eine Zeile.
                try
                {
                    Logger.LogWarning(
                        RuntimeLogPrefix + "|event=roster_diagnose"
                        + "|status=unavailable|reason="
                        + exception.GetType().Name);
                }
                catch
                {
                }
            }
        }

        internal void DiplomatieApplicationQuit()
        {
            _applicationQuitting = true;
            ShutdownAndRollback("application quit");
        }

        internal void DiplomatieHostDestroyed(bool applicationQuitting)
        {
            _applicationQuitting = _applicationQuitting || applicationQuitting;
            ShutdownAndRollback(
                applicationQuitting
                    ? "application quit"
                    : "persistent diplomacy host destroyed");
        }

        private void OnApplicationQuit()
        {
            DiplomatieApplicationQuit();
        }

        private void OnDestroy()
        {
            if (_applicationQuitting || IsUnityNull(_hostObject))
            {
                ShutdownAndRollback(
                    _applicationQuitting
                        ? "application quit"
                        : "plugin component destroyed without a persistent host");
            }
        }

        private void CreatePersistentHost()
        {
            GameObject hostObject = null;
            try
            {
                hostObject = new GameObject("StrongholdEuropeDE.DiplomatieHost");
                UnityObject.DontDestroyOnLoad(hostObject);
                hostObject.hideFlags = HideFlags.HideAndDontSave;
                DiplomatiePersistentHost host =
                    hostObject.AddComponent<DiplomatiePersistentHost>();
                host.Bind(this);
                _hostObject = hostObject;
                _host = host;
                hostObject = null;
            }
            finally
            {
                if (!IsUnityNull(hostObject))
                {
                    UnityObject.Destroy(hostObject);
                }
            }
        }

        private void ShutdownAndRollback(string reason)
        {
            if (_shuttingDown)
            {
                return;
            }
            _shuttingDown = true;
            try
            {
                Logger.LogInfo(
                    RuntimeLogPrefix + "|event=shutdown|reason="
                    + SafeReason(reason));
            }
            catch
            {
                // Eine Protokollzeile darf nichts beenden koennen.
            }

            if (_applicationQuitting)
            {
                try
                {
                    Logger.LogInfo(
                        RuntimeLogPrefix + "|event=shutdown"
                        + "|status=process_exit|rollback=not_required");
                }
                catch
                {
                }
                // Unity is terminating the process. Restoring teams and
                // unpatching native callbacks at this point cannot protect a
                // future frame because no future frame exists; it only turns
                // a normal quit into a synthetic fail_closed rollback.
                return;
            }

            bool preserveFailClosedHooks = false;
            if (_extensionHost != null)
            {
                try
                {
                    _extensionHost.RollbackAll();
                }
                catch (Exception exception)
                {
                    Logger.LogError(
                        "Diplomatie rollback encountered an error: " + exception);
                }
                preserveFailClosedHooks =
                    _diplomacy != null && _diplomacy.RequiresFailClosedHooks;
                if (preserveFailClosedHooks)
                {
                    Logger.LogError(
                        "Diplomacy native rollback remains unproven; "
                        + "retaining runtime hooks and save recovery "
                        + "while the game is paused.");
                }
                _extensionHost = null;
                _diplomacy = null;
            }

            if (_harmony != null && !preserveFailClosedHooks)
            {
                try
                {
                    _harmony.UnpatchSelf();
                }
                catch (Exception exception)
                {
                    Logger.LogError(
                        "Diplomatie unpatch encountered an error: " + exception);
                }
                _harmony = null;
            }

            if (!IsUnityNull(_hostObject))
            {
                try
                {
                    UnityObject.Destroy(_hostObject);
                }
                catch (Exception exception)
                {
                    Logger.LogWarning(
                        "Diplomatie host teardown errored: " + exception.GetType().Name);
                }
            }
            _hostObject = null;
            _host = null;
        }

        private ExtensionFeatureSnapshot FindSnapshot(string id)
        {
            if (_extensionHost == null)
            {
                return null;
            }
            foreach (ExtensionFeatureSnapshot snapshot in _extensionHost.Snapshot())
            {
                if (string.Equals(snapshot.Id, id, StringComparison.Ordinal))
                {
                    return snapshot;
                }
            }
            return null;
        }

        private void LogTerminal(string status, string reason)
        {
            if (_terminalLogged)
            {
                return;
            }
            _terminalLogged = true;
            try
            {
                string line = RuntimeLogPrefix + "|event=feature"
                    + "|status=" + status;
                if (!string.IsNullOrEmpty(reason))
                {
                    line += "|reason=" + SafeReason(reason);
                }
                if (string.Equals(status, "failed", StringComparison.Ordinal))
                {
                    Logger.LogError(line);
                }
                else
                {
                    Logger.LogInfo(line);
                }
            }
            catch
            {
                // Beobachtbarkeit darf keine Verfuegbarkeitsabhaengigkeit werden.
            }
        }

        /// <summary>
        /// Wen die Diplomatie ab Kartenstart fuer verbuendet haelt.
        /// </summary>
        /// <remarks>
        /// Dieselbe Regel wie <c>CaptureRosterAndCoalitions</c>:
        /// <c>localTeam &gt; 0 &amp;&amp; GetPlayerTeam(anderer) == localTeam</c>.
        /// Sie wird hier nachgerechnet, nicht abgefragt — die Diplomatie
        /// veroeffentlicht ihre Koalitionsliste nicht, und geraten wird nicht.
        /// </remarks>
        private static string Startverbuendete(
            GamePlayerManagerAPI spieler,
            int lokalesTeam,
            int lokal)
        {
            if (spieler == null || lokalesTeam <= 0)
            {
                return "keine";
            }
            var treffer = new StringBuilder();
            for (int id = 1; id <= 8; id++)
            {
                if (id == lokal || spieler.GetPlayerTeam(id) != lokalesTeam)
                {
                    continue;
                }
                if (treffer.Length > 0)
                {
                    treffer.Append(',');
                }
                treffer.Append(id.ToString(CultureInfo.InvariantCulture));
            }
            return treffer.Length == 0 ? "keine" : treffer.ToString();
        }

        private static string SafeReason(string value)
        {
            if (string.IsNullOrEmpty(value))
            {
                return "unknown";
            }
            return value.Replace('|', ' ').Replace('\r', ' ').Replace('\n', ' ');
        }

        private static bool IsUnityNull(UnityObject value)
        {
            return value == null;
        }
    }
}

using System.Globalization;

namespace StrongholdEuropeDE.Runtime
{
    internal static class RuntimeLogContract
    {
        internal const string Initialized =
            "SEDE_RUNTIME_V1|event=runtime|status=initialized";
        internal const string InitializationFailed =
            "SEDE_RUNTIME_V1|event=runtime|status=failed_closed";
        internal const string AudioInactive =
            "SEDE_RUNTIME_V1|event=audio|status=inactive";
        internal const string AudioActive =
            "SEDE_RUNTIME_V1|event=audio|status=active|tracks=17";
        internal const string AudioFailed =
            "SEDE_RUNTIME_V1|event=audio|status=failed_closed";
        internal const string FoliageInactive =
            "SEDE_RUNTIME_V1|event=foliage|status=inactive";
        internal const string FoliageSucceeded =
            "SEDE_RUNTIME_V1|event=foliage|status=success|gm=tree_apple|materials=7"
            + "|main_cpu_readable=false|mask_cpu_readable=false";
        internal static string FoliageGroupApplied(string group)
        {
            return "SEDE_RUNTIME_V1|event=foliage_group|status=success|gm=" + group;
        }

        internal const string FoliageFailed =
            "SEDE_RUNTIME_V1|event=foliage|status=failed_closed|gm=tree_apple";
        internal const string RosterInactive =
            "SEDE_RUNTIME_V1|event=roster_names|status=inactive";
        internal const string MusicRouteInactive =
            "SEDE_RUNTIME_V1|event=music_route|status=inactive";
        internal const string FarmPlacementInactive =
            "SEDE_RUNTIME_V1|event=farm_placement|status=inactive";
        // unsuitable is the TileType mask the rule *rejects*: BeachOrWaves = 32.
        // Logged as a number so a silent change to the rule is visible in a
        // runtime report.
        //
        // Stand bis zum 16.08.2026: 96, also BeachOrWaves | CoarseSand. Damit
        // hat diese Zeile GELOGEN, nachdem CoarseSand aus der Regel genommen
        // wurde - grober Sand ist in Crusader der gewoehnliche Boden, sein
        // Ausschluss beschraenkte Farmen auf die Oase. Die Zahl steht hier
        // fest verdrahtet und wird NICHT aus FarmPlacementRule.Unsuitable
        // berechnet; wer die Regel aendert, muss sie hier nachziehen. Genau
        // dafuer ist sie da - und genau das ist einmal misslungen.
        //
        // It used to log arable=145, an allow-list of Foliage | OasisGrass |
        // ThickFoliage. That mask could never admit ordinary ground, because
        // ordinary ground is TileType.NoneOrDirt = 0 and zero passes no bit test
        // - which is why farms stayed oasis-only through two attempted fixes.
        internal const string FarmPlacementActive =
            "SEDE_RUNTIME_V1|event=farm_placement|status=active|farms=4|unsuitable=32";
        internal const string FarmPlacementFailed =
            "SEDE_RUNTIME_V1|event=farm_placement|status=failed_closed";

        internal const string WorkerMilitiaInactive =
            "SEDE_RUNTIME_V1|event=worker_militia|status=inactive";
        internal const string WorkerMilitiaFailed =
            "SEDE_RUNTIME_V1|event=worker_militia|status=failed_closed";
        internal const string WorkerMilitiaMultiplayerSuppressed =
            "SEDE_RUNTIME_V1|event=worker_militia|status=suppressed"
            + "|reason=networked";

        internal static string WorkerMilitiaSessionScope(
            bool networked,
            bool localHost,
            int activePlayers,
            int otherHumanPlayers)
        {
            // other_humans counts REMOTE humans only (the game's own
            // steamID > 1000 && !isSelf && !skirmishAI roster semantics);
            // the old active_humans field counted every AI lord and misled
            // for two days.
            return "SEDE_RUNTIME_V1|event=worker_militia_scope|status="
                + RuntimeSessionScopeDecision.Status(
                    networked,
                    localHost,
                    otherHumanPlayers)
                + "|networked=" + (networked ? "true" : "false")
                + "|local_host=" + (localHost ? "true" : "false")
                + "|active_players=" + activePlayers.ToString(
                    CultureInfo.InvariantCulture)
                + "|other_humans=" + otherHumanPlayers.ToString(
                    CultureInfo.InvariantCulture);
        }

        internal static string WorkerMilitiaActiveLine()
        {
            return "SEDE_RUNTIME_V1|event=worker_militia|status=active"
                + "|hunter=ranged|woodcutter=melee|divisor="
                + GeneratedWorkerMilitiaContract.DamageDivisor.ToString(
                    CultureInfo.InvariantCulture)
                + "|hunter_guard="
                + GeneratedWorkerMilitiaContract.HunterGuardRadius.ToString(
                    CultureInfo.InvariantCulture)
                + "|woodcutter_guard="
                + GeneratedWorkerMilitiaContract.WoodcutterGuardRadius.ToString(
                    CultureInfo.InvariantCulture)
                + "|hunter_pursuit="
                + GeneratedWorkerMilitiaContract.HunterPursuitRadius.ToString(
                    CultureInfo.InvariantCulture)
                + "|woodcutter_pursuit="
                + GeneratedWorkerMilitiaContract.WoodcutterPursuitRadius.ToString(
                    CultureInfo.InvariantCulture)
                + "|selection=native_selected_state_single|combat=per_unit";
        }

        internal static string WorkerMilitiaSelectionEvidence(string unit)
        {
            return "SEDE_RUNTIME_V1|event=worker_militia_evidence"
                + "|status=selected|unit=" + unit;
        }

        internal static string WorkerMilitiaUiReadyEvidence(
            string unit,
            string route)
        {
            return "SEDE_RUNTIME_V1|event=worker_militia_evidence"
                + "|status=ui_ready|unit=" + unit + "|route=" + route
                + "|thread_match=true|native_singleton=true"
                + "|info_source=unit_fields|information_bound=true"
                + "|building=true|troops=false"
                + "|control_groups=false|panel_visible=true"
                + "|image_bound=true|name=true|type=true|comment=true"
                + "|stable_tick=true";
        }

        internal static string WorkerMilitiaCommandEvidence(
            string unit,
            string mode)
        {
            return "SEDE_RUNTIME_V1|event=worker_militia_evidence"
                + "|status=command|unit=" + unit + "|mode=" + mode;
        }

        internal static string WorkerMilitiaNativeMoveEvidence(string unit)
        {
            return "SEDE_RUNTIME_V1|event=worker_militia_evidence"
                + "|status=native_move|unit=" + unit;
        }

        internal static string WorkerMilitiaNativeWorkMoveSuppressedEvidence(
            string unit,
            string phase)
        {
            return "SEDE_RUNTIME_V1|event=worker_militia_evidence"
                + "|status=native_work_move_suppressed|unit=" + unit
                + "|phase=" + phase + "|occupancy=true";
        }

        internal static string WorkerMilitiaRightClickTelemetry(
            string phase,
            long gesture,
            string status,
            string reason,
            int workerId,
            int leftState,
            bool rightDown,
            bool rightUp,
            int hoveredUnitId,
            bool groundValid,
            int groundX,
            int groundY,
            int moveSequence)
        {
            // Diagnostic input telemetry deliberately does not use the
            // SEDE_RUNTIME_V1 evidence prefix. It must remain observable in a
            // canary log without becoming acceptance evidence for a command.
            return "Worker militia right-click telemetry: phase=" + phase
                + " gesture=" + gesture.ToString(CultureInfo.InvariantCulture)
                + " status=" + status + " reason=" + reason
                + " worker_id=" + workerId.ToString(CultureInfo.InvariantCulture)
                + " left_state=" + leftState.ToString(CultureInfo.InvariantCulture)
                + " right_down=" + (rightDown ? "true" : "false")
                + " right_up=" + (rightUp ? "true" : "false")
                + " hovered_raw=" + hoveredUnitId.ToString(
                    CultureInfo.InvariantCulture)
                + " ground_valid=" + (groundValid ? "true" : "false")
                + " ground_x=" + groundX.ToString(CultureInfo.InvariantCulture)
                + " ground_y=" + groundY.ToString(CultureInfo.InvariantCulture)
                + " move_sequence=" + moveSequence.ToString(
                    CultureInfo.InvariantCulture) + ".";
        }

        internal static string WorkerMilitiaNativeStateRestoredEvidence(
            string unit)
        {
            return "SEDE_RUNTIME_V1|event=worker_militia_evidence"
                + "|status=native_state_restored|unit=" + unit;
        }

        internal static string WorkerMilitiaHunterDamageEvidence(
            string mode,
            int archerDamage,
            int weakDamage)
        {
            return "SEDE_RUNTIME_V1|event=worker_militia_evidence"
                + "|status=hunter_damage|mode=" + mode + "|archer="
                + archerDamage.ToString(CultureInfo.InvariantCulture)
                + "|weak=" + weakDamage.ToString(CultureInfo.InvariantCulture);
        }

        internal static string WorkerMilitiaWoodcutterDamageEvidence(
            string mode,
            int damage)
        {
            return "SEDE_RUNTIME_V1|event=worker_militia_evidence"
                + "|status=woodcutter_damage|mode=" + mode + "|damage="
                + damage.ToString(CultureInfo.InvariantCulture);
        }

        internal static string WorkerMilitiaHoldStartedEvidence(
            string unit,
            int deadlineMilliseconds)
        {
            return "SEDE_RUNTIME_V1|event=worker_militia_evidence"
                + "|status=hold_started|unit=" + unit
                + "|deadline_ms=" + deadlineMilliseconds.ToString(
                    CultureInfo.InvariantCulture);
        }

        internal static string WorkerMilitiaHoldCompletedEvidence(string unit)
        {
            return "SEDE_RUNTIME_V1|event=worker_militia_evidence"
                + "|status=hold_completed|unit=" + unit
                + "|reason=no_contact";
        }

        internal static string WorkerMilitiaCombatDirectWorkEvidence(
            string unit,
            string mode)
        {
            return "SEDE_RUNTIME_V1|event=worker_militia_evidence"
                + "|status=combat_to_direct_work|unit=" + unit
                + "|mode=" + mode + "|guard_clear=true";
        }

        internal static string WorkerMilitiaHandoffRestoredEvidence(
            string unit,
            string mode,
            string reason,
            int commandMode,
            int originalCommandMode,
            int liveWorkLink,
            int originalWorkLink,
            int liveTribe,
            int originalTribe)
        {
            return "SEDE_RUNTIME_V1|event=worker_militia_evidence"
                + "|status=handoff_restored|unit=" + unit
                + "|mode=" + mode + "|reason=" + reason
                + "|command_mode="
                + commandMode.ToString(CultureInfo.InvariantCulture)
                + "|original_command_mode="
                + originalCommandMode.ToString(CultureInfo.InvariantCulture)
                + "|occupancy=true|work_link="
                + liveWorkLink.ToString(CultureInfo.InvariantCulture)
                + "|original_work_link="
                + originalWorkLink.ToString(CultureInfo.InvariantCulture)
                + "|tribe="
                + liveTribe.ToString(CultureInfo.InvariantCulture)
                + "|original_tribe="
                + originalTribe.ToString(CultureInfo.InvariantCulture)
                + "|return_move=false";
        }

        internal static string WorkerMilitiaDirectWorkResumedEvidence(
            string unit,
            string mode,
            string reason,
            string proof)
        {
            return "SEDE_RUNTIME_V1|event=worker_militia_evidence"
                + "|status=direct_work_resumed|unit=" + unit
                + "|mode=" + mode + "|reason=" + reason
                + "|proof=" + proof + "|occupancy=true";
        }

        internal static string WorkerMilitiaQuarantineRecoveredEvidence(
            string scope,
            string reason)
        {
            return "SEDE_RUNTIME_V1|event=worker_militia_evidence"
                + "|status=selection_quarantine_recovered|scope=" + scope
                + "|reason=" + reason;
        }

        internal static string WorkerMilitiaPerformanceEvidence(
            int samples,
            long meanMicroseconds,
            long p99Microseconds,
            bool withinBudget)
        {
            return "SEDE_RUNTIME_V1|event=worker_militia_evidence"
                + "|status=performance|samples="
                + samples.ToString(CultureInfo.InvariantCulture)
                + "|mean_us="
                + meanMicroseconds.ToString(CultureInfo.InvariantCulture)
                + "|p99_us="
                + p99Microseconds.ToString(CultureInfo.InvariantCulture)
                + "|budget_ok=" + (withinBudget ? "true" : "false");
        }

        internal static string FarmPlacementSummary(long allowed, long blocked)
        {
            return "SEDE_RUNTIME_V1|event=farm_placement|status=summary|allowed="
                + allowed.ToString(CultureInfo.InvariantCulture)
                + "|blocked="
                + blocked.ToString(CultureInfo.InvariantCulture);
        }

        internal const string DockPlacementInactive =
            "SEDE_RUNTIME_V1|event=dock_placement|status=inactive";
        // mode=measure bleibt die Zeile des reinen Messstands: die Bahn liest
        // die vier Hafen-Mapper 195-198 und schreibt nichts. Traegt das Profil
        // den Regelblock (GeneratedDockRulesContract.Enabled), sagt die
        // Aktivzeile stattdessen mode=enforce und nennt die drei Regelwerte -
        // genau die verlangte, sichtbare Vertragsaenderung: ein Stand, der den
        // Hafen abweist, kann das nicht stillschweigend tun (dieselbe
        // Ueberlegung wie unsuitable=96 oben).
        internal const string DockPlacementActive =
            "SEDE_RUNTIME_V1|event=dock_placement|status=active|mappers=4|mode=measure";

        internal static string DockPlacementActiveLine()
        {
            if (!GeneratedDockRulesContract.Enabled)
            {
                return DockPlacementActive;
            }
            return "SEDE_RUNTIME_V1|event=dock_placement|status=active|mappers=4|mode=enforce"
                + "|wood=" + GeneratedDockRulesContract.WoodCost.ToString(
                    CultureInfo.InvariantCulture)
                + "|gold=" + GeneratedDockRulesContract.GoldCost.ToString(
                    CultureInfo.InvariantCulture)
                + "|health=" + GeneratedDockRulesContract.Health.ToString(
                    CultureInfo.InvariantCulture);
        }

        internal const string DockPlacementFailed =
            "SEDE_RUNTIME_V1|event=dock_placement|status=failed_closed";

        // blocked ist immer dabei: 0 im Messmodus, sonst die Zahl der
        // abgewiesenen Landkacheln - so unterscheidet das Protokoll einen
        // Stand, der nur zaehlt, von einem, der sperrt.
        internal static string DockPlacementSummary(long tiles, long water, long blocked)
        {
            return "SEDE_RUNTIME_V1|event=dock_placement|status=summary|tiles="
                + tiles.ToString(CultureInfo.InvariantCulture)
                + "|water="
                + water.ToString(CultureInfo.InvariantCulture)
                + "|blocked="
                + blocked.ToString(CultureInfo.InvariantCulture);
        }

        internal static string MusicRouteActive(int entries, string digest)
        {
            return "SEDE_RUNTIME_V1|event=music_route|status=active|entries="
                + entries.ToString(CultureInfo.InvariantCulture)
                + "|digest=" + digest;
        }

        internal static string RosterActive(string locale, string digest)
        {
            return "SEDE_RUNTIME_V1|event=roster_names|status=active|locale="
                + locale
                + "|entries=64|hud_controls=17|digest=" + digest;
        }

        internal static string RosterHudVerified(int generation)
        {
            return "SEDE_RUNTIME_V1|event=roster_ui|status=verified|controls=17|generation="
                + generation.ToString(CultureInfo.InvariantCulture);
        }

        internal const string RosterMonitorHealthy =
            "SEDE_RUNTIME_V1|event=roster_monitor|status=healthy"
            + "|entries=64|hud_controls=17";

        internal static string RosterFailedClosed(string reason)
        {
            return "SEDE_RUNTIME_V1|event=roster_names|status=failed_closed|reason="
                + reason;
        }

        internal static string RosterRestartRequired(string reason)
        {
            return "SEDE_RUNTIME_V1|event=roster_names|status=restart_required|reason="
                + reason;
        }

        internal static string RosterCleanup(
            int entries,
            int controls,
            string trigger)
        {
            return "SEDE_RUNTIME_V1|event=roster_cleanup|status=restored|entries="
                + entries.ToString(CultureInfo.InvariantCulture)
                + "|hud_controls="
                + controls.ToString(CultureInfo.InvariantCulture)
                + "|trigger="
                + trigger;
        }
    }
}

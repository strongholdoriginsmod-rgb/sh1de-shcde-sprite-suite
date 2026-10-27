using System;
using System.IO;
using System.Threading;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// Every CrusaderDE.dll address the worker militia reads, calls or
    /// patches, one record per engine build.
    /// </summary>
    /// <remarks>
    /// <para>
    /// The 2.80 record was derived on 2026-09-28 from the 2.7 record with
    /// tools/reanchor_rvas.py (masked byte signatures; data addresses by
    /// unanimous vote over their referencing instructions) and checked with
    /// tools/compare_functions.py: the command-target routine, the census,
    /// the player-selection clear, the whole hunter update (1,052
    /// instructions) and the speech selector are identical modulo
    /// relocation; the four leaf helpers are identical up to their ret.
    /// Independent anchors that agree: LocalPlayer 0x88E2D70 is SE 2.11's
    /// LocalPlayerIdVA signature target, CurrentContextUnitId 0x92F2C4 and
    /// the arrival predicate 0x1882A0 match the engine-research notes of
    /// 2026-09-27. Evidence: work/reanchor/militia-280-*.json.
    /// </para>
    /// <para>
    /// Struct offsets (GameUnit stride 0x490, array bias 0x65C, building
    /// stride 0x32C) are the same in both builds and stay where they are.
    /// </para>
    /// <para>
    /// An engine that matches no record leaves <see cref="Current"/> null.
    /// Only the militia then declines in Prepare; nothing else is affected.
    /// </para>
    /// </remarks>
    internal sealed class WorkerMilitiaNativeLayout
    {
        internal const string EngineRelativePath =
            "Stronghold Crusader Definitive Edition_Data/Plugins/x86_64/CrusaderDE.dll";

        internal string Name;
        internal long EngineSize;
        internal string EngineSha256;

        // Globals
        internal int UnitManagerRva;
        internal int CurrentContextUnitIdRva;
        internal int LocalPlayerRva;
        internal int CursorBlockRva;
        internal int SelectionStateRva;
        internal int CursorKindRva;
        internal int MapperItemRva;
        internal int SelectionTribeRva;
        internal int SelectionPendingRva;
        internal int SelectionFlagRva;
        internal int HudSubModeRva;
        internal int HudPrevSubModeRva;
        internal int AppModeRva;
        internal int AppSubModeRva;
        internal int CandidateCountRva;
        internal int LastMouseStateRva;
        internal int LastRightDownRva;
        internal int LastRightUpRva;
        internal int SelectionOnRva;
        internal int SelectionEstablishedRva;
        internal int TileFlagArrayRva;
        internal int CursorTileRva;

        // Functions the militia calls or claims
        internal int UnitSelectionMarkerClearRva;
        internal int PlayerSelectionClearRva;
        internal int MoveHereRva;

        // Selection-class census (WorkerMilitiaCommandClass)
        internal int CensusFunctionRva;
        internal int CensusCounterRegisterLoadRva;
        internal int CensusWindowBaseRva;
        internal int CensusWindowLimitRva;
        internal int CensusCaseLookupRva;
        internal int CensusCaseTableRva;
        internal int CensusJumpTableRva;

        // Command-target chain (WorkerMilitiaCommandClass)
        internal int CommandTargetFunctionRva;
        internal int CommandTargetFallbackRva;
        internal int CommandTargetExitRva;

        // Hunter update state machine (WorkerMilitiaHunterMoveState)
        internal int HunterUpdateRegisterSetupRva;
        internal int HunterFinalStateDispatchRva;
        internal int HunterState6EBodyRva;
        internal int HunterUnknownStateBodyRva;
        internal int HunterUpdateEpilogueRva;
        internal int MovementArrivalPredicateRva;
        internal int MovementContextClearRva;

        // Speech selector (WorkerMilitiaSpeechSelector, parked)
        internal int SpeechSelectorRva;
        internal int SpeechSelectorFileOffset;

        // Native "turn this living unit into +0x2C6 now" (unit manager, unit
        // id). The per-unit tick reaches it through alive state 4 (0x183BF8);
        // the engine also calls it directly outside the tick (0x6F60C,
        // 0x6D82A). 2.7 anchored by a unique 24-byte prologue match.
        internal int TransformUnitRva;

        internal static readonly WorkerMilitiaNativeLayout Crusader27 =
            new WorkerMilitiaNativeLayout
            {
                Name = "2.7",
                EngineSize = 3446272,
                EngineSha256 =
                    "20c4157bf4b4724082d69cb696358ca82d2af613494e191b5290369d810ad924",
                UnitManagerRva = 0x67E53C0,
                CurrentContextUnitIdRva = 0x92E234,
                LocalPlayerRva = 0x88E0D30,
                CursorBlockRva = 0x60AB4A8,
                SelectionStateRva = 0x60AB4CC,
                CursorKindRva = 0x60AB4C0,
                MapperItemRva = 0x60AB3BC,
                SelectionTribeRva = 0x7CC36E0,
                SelectionPendingRva = 0x7CC3700,
                SelectionFlagRva = 0x7CC36FC,
                HudSubModeRva = 0x3663E60,
                HudPrevSubModeRva = 0x3663E78,
                AppModeRva = 0x3663E48,
                AppSubModeRva = 0x3663E4C,
                CandidateCountRva = 0x8E9FD4,
                LastMouseStateRva = 0x8E9A08,
                LastRightDownRva = 0x8E9A03,
                LastRightUpRva = 0x8E9A0C,
                SelectionOnRva = 0x34A7C70,
                SelectionEstablishedRva = 0x34A7C74,
                TileFlagArrayRva = 0x48F5110,
                CursorTileRva = 0x3A0FD88,
                UnitSelectionMarkerClearRva = 0x185960,
                PlayerSelectionClearRva = 0x199300,
                MoveHereRva = 0x18ED50,
                CensusFunctionRva = 0x196F90,
                CensusCounterRegisterLoadRva = 0x196F97,
                CensusWindowBaseRva = 0x197083,
                CensusWindowLimitRva = 0x197086,
                CensusCaseLookupRva = 0x197091,
                CensusCaseTableRva = 0x1972F4,
                CensusJumpTableRva = 0x197268,
                CommandTargetFunctionRva = 0x18C1A0,
                CommandTargetFallbackRva = 0x18C409,
                CommandTargetExitRva = 0x18C40E,
                HunterUpdateRegisterSetupRva = 0x12EAEC,
                HunterFinalStateDispatchRva = 0x1301DD,
                HunterState6EBodyRva = 0x1301E3,
                HunterUnknownStateBodyRva = 0x130253,
                HunterUpdateEpilogueRva = 0x130262,
                MovementArrivalPredicateRva = 0x187080,
                MovementContextClearRva = 0x196680,
                SpeechSelectorRva = 0x3BC0,
                SpeechSelectorFileOffset = 0x2FC0,
                TransformUnitRva = 0x194A50,
            };

        internal static readonly WorkerMilitiaNativeLayout Crusader280 =
            new WorkerMilitiaNativeLayout
            {
                Name = "2.80",
                EngineSize = 3450880,
                EngineSha256 =
                    "1e6d4c2e10cc35a7b8082a7e2bcd8bb20680ebeda803d9b943257b948145cb2b",
                UnitManagerRva = 0x67E7400,
                CurrentContextUnitIdRva = 0x92F2C4,
                LocalPlayerRva = 0x88E2D70,
                CursorBlockRva = 0x60AC548,
                SelectionStateRva = 0x60AC56C,
                CursorKindRva = 0x60AC560,
                MapperItemRva = 0x60AC45C,
                SelectionTribeRva = 0x7CC5720,
                SelectionPendingRva = 0x7CC5740,
                SelectionFlagRva = 0x7CC573C,
                HudSubModeRva = 0x3664EF0,
                HudPrevSubModeRva = 0x3664F08,
                AppModeRva = 0x3664ED8,
                AppSubModeRva = 0x3664EDC,
                CandidateCountRva = 0x8EB064,
                // The mouse block's first fields moved by 0x1090; its +0x2B
                // field moved by 0x1091. Only exact references voted here.
                LastMouseStateRva = 0x8EAA98,
                LastRightDownRva = 0x8EAA93,
                LastRightUpRva = 0x8EAA9C,
                SelectionOnRva = 0x34A8D00,
                SelectionEstablishedRva = 0x34A8D04,
                TileFlagArrayRva = 0x48F61B0,
                CursorTileRva = 0x3A10E28,
                UnitSelectionMarkerClearRva = 0x186B80,
                PlayerSelectionClearRva = 0x19A530,
                MoveHereRva = 0x18FF70,
                CensusFunctionRva = 0x1981C0,
                CensusCounterRegisterLoadRva = 0x1981C7,
                CensusWindowBaseRva = 0x1982B3,
                CensusWindowLimitRva = 0x1982B6,
                CensusCaseLookupRva = 0x1982C1,
                CensusCaseTableRva = 0x198524,
                CensusJumpTableRva = 0x198498,
                CommandTargetFunctionRva = 0x18D3C0,
                CommandTargetFallbackRva = 0x18D629,
                CommandTargetExitRva = 0x18D62E,
                HunterUpdateRegisterSetupRva = 0x12FBEC,
                HunterFinalStateDispatchRva = 0x1312DD,
                HunterState6EBodyRva = 0x1312E3,
                HunterUnknownStateBodyRva = 0x131353,
                HunterUpdateEpilogueRva = 0x131362,
                MovementArrivalPredicateRva = 0x1882A0,
                MovementContextClearRva = 0x1978B0,
                SpeechSelectorRva = 0x3BC0,
                SpeechSelectorFileOffset = 0x2FC0,
                TransformUnitRva = 0x195C70,
            };

        internal static readonly WorkerMilitiaNativeLayout[] Known =
        {
            Crusader280,
            Crusader27,
        };

        private static readonly Lazy<WorkerMilitiaNativeLayout> Resolved =
            new Lazy<WorkerMilitiaNativeLayout>(
                ResolveFromDisk,
                LazyThreadSafetyMode.ExecutionAndPublication);

        /// <summary>
        /// The record of the CrusaderDE.dll this process runs, or null.
        /// Resolved once; never throws.
        /// </summary>
        internal static WorkerMilitiaNativeLayout Current
        {
            get { return Resolved.Value; }
        }

        internal static string DescribeCurrent()
        {
            WorkerMilitiaNativeLayout layout = Current;
            return layout == null ? "unknown" : layout.Name;
        }

        private static WorkerMilitiaNativeLayout ResolveFromDisk()
        {
            try
            {
                string path = Path.GetFullPath(Path.Combine(
                    BepInEx.Paths.GameRootPath,
                    EngineRelativePath.Replace('/', Path.DirectorySeparatorChar)));
                var file = new FileInfo(path);
                if (!file.Exists)
                {
                    return null;
                }
                foreach (WorkerMilitiaNativeLayout candidate in Known)
                {
                    if (candidate.EngineSize != file.Length)
                    {
                        continue;
                    }
                    string digest = Hashing.Sha256FileStable(
                        path,
                        candidate.EngineSize);
                    return string.Equals(
                            digest,
                            candidate.EngineSha256,
                            StringComparison.Ordinal)
                        ? candidate
                        : null;
                }
                return null;
            }
            catch (Exception)
            {
                // A layout that cannot be proven is no layout. The caller
                // declines the militia; logging happens in Prepare.
                return null;
            }
        }
    }
}
